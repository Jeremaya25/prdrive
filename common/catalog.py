#!/usr/bin/env python3
"""El catálogo global de parejas, que vive en el remoto del usuario.

`sync_config.toml` dice qué sincroniza ESTE dispositivo; el catálogo
(`<remote>:<catalog_path>`) dice qué parejas existen y es el mismo fichero para
todos. El alta y la baja de una pareja ocurren ahí primero; cada dispositivo se
limita a elegir cuáles usa y, si le hace falta, a modificar su copia local
dejándola marcada como divergente. Es lo único que el proyecto guarda en el
remoto: configuración, nunca programas.

Tres cosas gobiernan este módulo:
- Leer nunca puede matar la ventana: `load()` intenta el remoto y, sin red, cae
  a `state/catalog.toml`. Sin copia devuelve `None` y un aviso, y la pantalla
  se abre con lo que ya tiene el dispositivo.
- Escribir es lo peligroso: este fichero gobierna borrados en todos los
  dispositivos, así que `push()` verifica el TOML generado, se niega si el
  remoto ha cambiado bajo sus pies y deja un `.bak`.
- La escritura pierde los comentarios intercalados: el serializador de
  `config_file` conserva la cabecera (el manual del esquema) y nada más. Se
  prefiere reutilizar un serializador probado que se niega a escribir lo que no
  se relee igual.

`run()` es una función de módulo a propósito: los tests la sustituyen entera y
así ninguno toca la red.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, NamedTuple

from . import config_file, model, store
from .model import ConfigError

DEFAULT_CATALOG_PATH = "/prdrive-catalog/pairs.toml"
"""Ruta del catálogo de fábrica; cada usuario pone la suya.

Se cambia por dispositivo con `[defaults].catalog_path` y el instalador la
pregunta en su paso de conexión. `install/profile.py` la importa de aquí para
que instalador y dispositivo no puedan discrepar.
"""
BAK_SUFFIX = ".bak"
FICHERO = PurePosixPath(DEFAULT_CATALOG_PATH).name
"""Nombre del fichero dentro de la carpeta del catálogo.

Sale de la ruta de fábrica para no escribirlo dos veces; es lo que se sugiere
cuando alguien pone la carpeta.
"""

NET_FLAGS = ["--contimeout", "10s", "--timeout", "20s",
             "--retries", "1", "--low-level-retries", "2"]
"""Flags de rclone para que un remoto muerto no congele la ventana.

El catálogo son unos kilobytes: aquí no se espera por ancho de banda sino por
un servidor que puede no estar, y quien espera es la ventana de parejas. Con
los valores de rclone por defecto (5 min de `--timeout`, 3 reintentos) una wifi
mala congela la UI varios minutos; con estos, un remoto inalcanzable se
resuelve en segundos y se cae a la copia.
"""
TIMEOUT = 90  # segundos; red de seguridad del subproceso, no el tiempo normal


def cache_toml() -> Path:
    """Devuelve la ruta de la última copia buena del catálogo (`state/catalog.toml`).

    Permite abrir la pantalla sin red. Es función y no constante porque
    `tests/_harness.sandbox()` reengancha `model.STATE_DIR` en caliente y una
    constante calculada al importar se quedaría apuntando al dispositivo de
    verdad.
    """
    return model.STATE_DIR / "catalog.toml"


def cache_meta() -> Path:
    """Devuelve la ruta de los metadatos de la copia (`state/catalog.json`)."""
    return model.STATE_DIR / "catalog.json"


class Catalog(NamedTuple):
    """El catálogo tal como se ha leído, con de dónde y de cuándo.

    Args:
        raw: El dict crudo de `tomllib`.
        text: El fichero tal cual: la base contra la que se escribe.
        source: `remote` o `cache`.
        stamp: Cuándo se leyó.
        endpoint: `remote:/ruta/al/pairs.toml`.
    """
    raw: dict
    text: str
    source: str
    stamp: str
    endpoint: str

    @property
    def editable(self) -> bool:
        """Indica si se puede escribir: solo sobre lo que se acaba de leer del remoto.

        Subir partiendo de la copia local sería escribir a ciegas encima de lo
        que otro dispositivo haya hecho mientras tanto.
        """
        return self.source == "remote"

    @property
    def defaults(self) -> dict:
        """Devuelve la tabla `[defaults]` del catálogo."""
        return dict(self.raw.get("defaults") or {})

    @property
    def names(self) -> list[str]:
        """Devuelve los nombres de las parejas del catálogo."""
        return [p["name"] for p in self.raw.get("pair") or [] if p.get("name")]


def endpoint(raw_local: Mapping[str, Any] | None = None) -> str:
    """Devuelve dónde está el catálogo (`remote:ruta`).

    Sale de los `[defaults]` del dispositivo.

    Args:
        raw_local: El `sync_config.toml` en bruto; sin él, los valores de
            fábrica.
    """
    defaults = dict((raw_local or {}).get("defaults") or {})
    remote = defaults.get("catalog_remote") or defaults.get("remote") or model.DEFAULT_REMOTE
    path = defaults.get("catalog_path") or DEFAULT_CATALOG_PATH
    return f"{remote}:{path}"


def problema_de_ruta(ruta: str) -> str | None:
    """Dice qué tiene de malo una ruta de catálogo recién tecleada.

    Sin red solo se puede saber si nombra un fichero `.toml`, y basta para el
    error que de verdad se comete: poner la carpeta (`/prdrive-catalog`) en vez
    del fichero (`/prdrive-catalog/pairs.toml`). Una ruta vacía no es un
    problema: quien la pide cae a `DEFAULT_CATALOG_PATH`.

    Se aplica a lo que se TECLEA (el paso Conexión y los dos formularios de
    `[defaults]`), nunca a lo ya escrito en un dispositivo: un catálogo sin
    extensión que hoy funciona no puede dejar de leerse por una actualización.
    Para ese caso está `explicar_carpeta()`.

    Returns:
        El motivo, o `None` si la ruta vale.
    """
    limpia = (ruta or "").strip()
    if not limpia or limpia.lower().endswith(".toml"):
        return None
    return (f"La ruta del catálogo tiene que ser la de su fichero .toml, no la de "
            f"la carpeta: «{limpia}» no termina en .toml. Si el catálogo está "
            f"dentro, sería «{_dentro(limpia)}».")


def validar_ruta_editada(antes: Mapping[str, Any] | None,
                         despues: Mapping[str, Any] | None) -> None:
    """Rechaza unos `[defaults]` editados que ponen una carpeta como `catalog_path`.

    Solo si la CAMBIAN: guardar otro ajuste no puede tropezar con una ruta que
    ya estaba y, si está ahí, funciona.

    Raises:
        ConfigError: Si la ruta cambiada no nombra un fichero `.toml`.
    """
    nueva = str((despues or {}).get("catalog_path") or "")
    if nueva == str((antes or {}).get("catalog_path") or ""):
        return
    problema = problema_de_ruta(nueva)
    if problema:
        raise ConfigError(problema)


def _dentro(ruta: str) -> str:
    """Devuelve el `pairs.toml` de esa carpeta.

    Vale para una ruta y para un endpoint: `nas:` a secas es la raíz del remoto
    y ahí no se antepone ninguna barra.
    """
    if not ruta or ruta.endswith((":", "/")):
        return ruta + FICHERO
    return f"{ruta}/{FICHERO}"


def _binary() -> str:
    """Devuelve el rclone como `model.rclone_binary()`, pero sin `sys.exit`.

    La usa la UI, y ahí matar el proceso cerraría la ventana en vez de decir
    qué falta.

    Raises:
        ConfigError: Si no hay rclone.
    """
    if model.rclone_path() is None:
        raise ConfigError(
            f"No encuentro el binario de rclone en: "
            f"{model.rclone_del_agente() or model.BIN_DIR / model.rclone_name()}\n"
            f"Sin él no se puede hablar con el catálogo.")
    return model.rclone_binary()


def run(args: list[str]) -> subprocess.CompletedProcess:
    """Ejecuta rclone con el config y el cwd del dispositivo.

    El cwd es `model.APP_DIR` porque `rclone.conf` resuelve contra él sus rutas
    relativas (`key_file`, `known_hosts_file`), que es lo que lo hace portable.
    Lleva `CREATE_NO_WINDOW` porque la UI puede correr bajo `pythonw` y cada
    invocación abriría una consola.

    Args:
        args: Argumentos de rclone tras `--config` y `NET_FLAGS`.
    """
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = model.CREATE_NO_WINDOW
    return subprocess.run(
        [_binary(), "--config", str(model.RCLONE_CONF), *NET_FLAGS, *args],
        cwd=str(model.APP_DIR), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=TIMEOUT, **kwargs)


def _parse(text: str, where: str) -> dict:
    """Parsea el TOML del catálogo.

    Raises:
        ConfigError: Si no es TOML válido; `where` dice de qué catálogo.
    """
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"El catálogo {where} no es TOML válido: {e}") from e


# Quien pregunta a rclone: `run` aquí, `remote.Rclone.run` en el instalador.
Ejecutar = Callable[[list[str]], subprocess.CompletedProcess]
"""Quien pregunta a rclone: `run` aquí, `remote.Rclone.run` en el instalador."""


def _es_carpeta(ejecutar: Ejecutar, donde: str) -> bool | None:
    """Pregunta a rclone (`lsjson --stat`) si esa ruta es una carpeta.

    Un «no se sabe» nunca se convierte en diagnóstico: uno falso es peor que
    ninguno.

    Returns:
        True si es una carpeta, False si es un fichero y `None` si no se sabe
        (no existe, no contesta o la respuesta no es la esperada).
    """
    try:
        res = ejecutar(["lsjson", "--stat", donde])
    except (OSError, subprocess.SubprocessError, ConfigError):
        return None
    if res.returncode != 0:
        return None
    try:
        info = json.loads(res.stdout or "")
    except ValueError:
        return None
    if not isinstance(info, dict) or not isinstance(info.get("IsDir"), bool):
        return None
    return info["IsDir"]


def explicar_carpeta(ejecutar: Ejecutar, donde: str,
                     fallo: bool = False) -> str | None:
    """Dice qué decirle al usuario si la ruta del catálogo es una carpeta.

    `rclone cat` de una carpeta NO falla: concatena, recursivamente, todos los
    ficheros de dentro (medido con rclone v1.75.1: el `pairs.toml`, el `.bak`
    de `push()` y las notas de `devices/`) y sale con 0. Llega un TOML con dos
    `[defaults]` y `tomllib` contesta «Cannot declare ('defaults',) twice», que
    no se parece a la causa.

    Por eso, cuando algo huele mal, se pregunta al remoto qué es esa ruta
    (`lsjson --stat` da `"IsDir": true` para una carpeta). Huele mal si lo
    leído no sirve (`fallo`) o si la ruta no termina en `.toml`, que pilla
    también la carpeta vacía y la que solo tiene un `pairs.toml`, que `cat` lee
    sin error. En el camino bueno no cuesta ninguna ida y vuelta más, y no se
    pregunta cuando falla el propio `cat`: sin red la pregunta tardaría lo
    mismo en no llegar.

    Args:
        ejecutar: Quien ejecuta rclone (`Ejecutar`).
        donde: Endpoint del catálogo, `remote:ruta`.
        fallo: Si lo leído no se pudo interpretar.

    Returns:
        El mensaje, o `None` si no es una carpeta o no se puede saber.
    """
    ruta = donde.partition(":")[2]
    if not (fallo or problema_de_ruta(ruta)):
        return None
    if _es_carpeta(ejecutar, donde) is not True:
        return None
    motivo = (f"La ruta del catálogo, {donde}, es una carpeta y no un fichero: "
              f"tiene que apuntar al fichero del catálogo.")
    if _es_carpeta(ejecutar, _dentro(donde)) is False:
        return (f"{motivo} Dentro hay un {FICHERO}, así que seguramente es "
                f"«{_dentro(ruta)}».")
    return f"{motivo} Por ejemplo «{_dentro(ruta)}», si es ahí donde está."


def _write_cache(cat: Catalog) -> None:
    """Guarda la copia local; que falle no es un error.

    El dispositivo puede estar de solo lectura o haberse extraído a media
    frase.
    """
    try:
        cache_toml().parent.mkdir(parents=True, exist_ok=True)
        cache_toml().write_text(cat.text, encoding="utf-8", newline="\n")
    except OSError:
        return
    store.write_json(cache_meta(), {"pulled_at": cat.stamp, "endpoint": cat.endpoint})


def pull(raw_local: Mapping[str, Any] | None = None) -> Catalog:
    """Lee el catálogo del remoto y lo cachea.

    Lo que `cat` trae de una carpeta no se cachea: no es el catálogo (ver
    `explicar_carpeta`).

    Raises:
        ConfigError: Si no se puede leer, no es TOML válido o la ruta es una
            carpeta.
    """
    where = endpoint(raw_local)
    res = run(["cat", where])
    if res.returncode != 0:
        raise ConfigError(f"No pude leer el catálogo {where}: "
                          f"{(res.stderr or '').strip()}")
    texto = res.stdout or ""
    try:
        raw = _parse(texto, where)
    except ConfigError as e:
        raise ConfigError(explicar_carpeta(run, where, fallo=True)
                          or str(e)) from e
    carpeta = explicar_carpeta(run, where)
    if carpeta:
        raise ConfigError(carpeta)
    cat = Catalog(raw=raw, text=texto, source="remote",
                  stamp=store.stamp(), endpoint=where)
    _write_cache(cat)
    return cat


def cached() -> Catalog | None:
    """Devuelve la última copia buena, sin tocar la red.

    Es `None` si no hay copia o no sirve.
    """
    try:
        text = cache_toml().read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    meta = store.read_json(cache_meta())
    return Catalog(raw=raw, text=text, source="cache",
                   stamp=str(meta.get("pulled_at") or "fecha desconocida"),
                   endpoint=str(meta.get("endpoint") or endpoint()))


def load(raw_local: Mapping[str, Any] | None = None) -> tuple[Catalog | None, str | None]:
    """Devuelve el catálogo y, si algo no ha ido bien, qué decirle al usuario.

    Nunca lanza: la pantalla de parejas tiene que abrirse igual sin red. Sin
    remoto cae a la copia local (no editable); sin copia devuelve `None`.
    """
    try:
        return pull(raw_local), None
    except ConfigError as e:
        motivo = str(e).strip()
    except (OSError, subprocess.SubprocessError) as e:
        motivo = str(e)

    copia = cached()
    if copia is not None:
        return copia, (f"Sin conexión con el catálogo. Se enseña la copia local del "
                       f"{copia.stamp}; no se puede editar el catálogo hasta que "
                       f"vuelva la conexión.\n{motivo}")
    return None, (f"No hay catálogo ni copia local, así que solo se puede trabajar "
                  f"con las parejas que ya tiene este dispositivo.\n{motivo}")


def push(new_raw: Mapping[str, Any], base_text: str,
         raw_local: Mapping[str, Any] | None = None) -> list[str]:
    """Sube el catálogo al remoto y devuelve qué se ha hecho.

    El orden importa: primero se genera y verifica el texto, después se
    comprueba que el remoto sigue siendo el que se leyó y solo entonces se
    escribe, con copia previa. Así ningún fallo intermedio deja el catálogo a
    medias y el peor caso es no haber escrito nada.

    Args:
        new_raw: El catálogo nuevo, en bruto.
        base_text: El texto leído del remoto sobre el que se parte.
        raw_local: El config en bruto del dispositivo, para saber dónde está el
            catálogo.

    Raises:
        ConfigError: Si el texto generado no se relee igual, si el remoto
            cambió desde que se leyó o si falla algún paso de rclone.
    """
    where = endpoint(raw_local)
    text = config_file.dumps_checked(new_raw, config_file.header_of(base_text))

    actual = run(["cat", where])
    if actual.returncode != 0:
        raise ConfigError(f"No pude releer el catálogo {where} antes de escribir: "
                          f"{(actual.stderr or '').strip()}. No se ha escrito nada.")
    if actual.stdout != base_text:
        raise ConfigError(
            "El catálogo ha cambiado en el remoto desde que lo leíste, así que no "
            "se ha escrito nada. Otro dispositivo lo ha tocado mientras tanto: cierra "
            "la pantalla y vuelve a abrirla para partir de la versión buena, y "
            "repite el cambio.")

    hechos: list[str] = []
    copia = run(["copyto", where, where + BAK_SUFFIX])
    if copia.returncode != 0:
        raise ConfigError(f"No pude dejar la copia {where}{BAK_SUFFIX}: "
                          f"{(copia.stderr or '').strip()}. No se ha escrito nada.")
    hechos.append(f"Copia previa en {where}{BAK_SUFFIX}")

    tmpdir = Path(tempfile.mkdtemp(prefix="prdrive-cat-"))
    try:
        tmp = tmpdir / "pairs.toml"
        tmp.write_text(text, encoding="utf-8", newline="\n")
        subida = run(["copyto", str(tmp), where])
        if subida.returncode != 0:
            raise ConfigError(f"No pude escribir el catálogo {where}: "
                              f"{(subida.stderr or '').strip()}. "
                              f"La versión anterior sigue en {where}{BAK_SUFFIX}.")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    hechos.append(f"Catálogo actualizado en {where}")

    _write_cache(Catalog(raw=dict(new_raw), text=text, source="remote",
                         stamp=store.stamp(), endpoint=where))
    return hechos


def pairs_by_name(cat: Catalog | None) -> dict[str, dict]:
    """Devuelve las parejas del catálogo por nombre; vacío si no hay catálogo."""
    if cat is None:
        return {}
    return {p["name"]: dict(p) for p in cat.raw.get("pair") or [] if p.get("name")}


def find_pair(cat: Catalog | None, name: str) -> dict | None:
    """Devuelve la pareja del catálogo con ese nombre, o `None`."""
    return pairs_by_name(cat).get(name)


def diff_keys(a: Mapping[str, Any] | None, b: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Devuelve, ordenadas, las claves en que difieren dos parejas.

    Vale también para dos `[defaults]`.
    """
    uno, otro = dict(a or {}), dict(b or {})
    return tuple(sorted(k for k in set(uno) | set(otro) if uno.get(k) != otro.get(k)))
