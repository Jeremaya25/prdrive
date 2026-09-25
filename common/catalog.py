#!/usr/bin/env python3
"""
catalog.py — El catálogo global de parejas, que vive en el remoto del usuario.

`sync_config.toml` dice qué sincroniza ESTE dispositivo; el catálogo
(`<remote>:<catalog_path>`) dice qué parejas existen, y es el mismo fichero para
todos los dispositivos. El alta y la baja de una pareja ocurren ahí primero; cada
dispositivo se limita a elegir cuáles de ellas usa y, si le hace falta, a
modificar su copia local dejándola marcada como divergente.

Desde que el instalador despliega el código él mismo, esto es **lo único** que
el proyecto guarda en el remoto: configuración, y nunca programas.

Tres cosas gobiernan este módulo:

  * **Leer nunca puede matar la ventana.** `load()` intenta el remoto, y si no
    hay red cae a la copia de `state/catalog.toml`. Sin copia devuelve `None` y
    un aviso, y la pantalla sigue abriéndose con lo que ya tiene el dispositivo.
  * **Escribir es lo peligroso.** Este fichero gobierna borrados en todos los
    dispositivos, así que `push()` verifica el TOML generado antes de subirlo,
    se niega si el remoto ha cambiado bajo sus pies y deja ahí un `.bak`.
  * **La escritura pierde los comentarios intercalados.** El serializador de
    `config_file` conserva la cabecera —que es el manual del esquema— y nada
    más. Es una decisión tomada: reutilizar el serializador ya probado, que se
    niega a escribir lo que no se relee igual, vale más que conservar unos
    `# ---`.

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

# Valor de fábrica, no la ruta de nadie: cada usuario pone la suya. Se cambia por
# dispositivo desde [defaults].catalog_path, y el instalador la pregunta en su
# paso de conexión. `install/profile.py` la importa de aquí para que instalador
# y dispositivo no puedan discrepar.
DEFAULT_CATALOG_PATH = "/prdrive-catalog/pairs.toml"
BAK_SUFFIX = ".bak"
# El fichero dentro de la carpeta del catálogo: sale de la ruta de fábrica para
# no escribirlo dos veces. Es lo que se sugiere cuando alguien pone la carpeta.
FICHERO = PurePosixPath(DEFAULT_CATALOG_PATH).name

# El catálogo son unos kilobytes, así que aquí no se espera por ancho de banda:
# se espera a un servidor que puede no estar. Y quien espera es la ventana de
# parejas, que se abre al conectar el dispositivo. Con los valores de rclone por
# defecto (5 min de --timeout, 3 reintentos) una wifi mala congela la UI varios
# minutos; con estos, un remoto inalcanzable se resuelve en segundos y se cae a
# la copia.
NET_FLAGS = ["--contimeout", "10s", "--timeout", "20s",
             "--retries", "1", "--low-level-retries", "2"]
TIMEOUT = 90                       # red de seguridad del subproceso, no la normal


def cache_toml() -> Path:
    """La última copia buena del catálogo, para poder abrir la pantalla sin red.

    Funciones y no constantes: `tests/_harness.sandbox()` reengancha
    `model.STATE_DIR` en caliente, y una constante calculada al importar se
    quedaría apuntando al dispositivo de verdad."""
    return model.STATE_DIR / "catalog.toml"


def cache_meta() -> Path:
    return model.STATE_DIR / "catalog.json"


class Catalog(NamedTuple):
    """El catálogo tal y como se ha leído, con de dónde y de cuándo."""
    raw: dict                  # el dict crudo de tomllib
    text: str                  # el fichero tal cual: la base contra la que se escribe
    source: str                # 'remote' | 'cache'
    stamp: str                 # cuándo se leyó
    endpoint: str              # 'remote:/ruta/al/pairs.toml'

    @property
    def editable(self) -> bool:
        """Solo se escribe sobre lo que se acaba de leer del remoto.

        Subir partiendo de la copia local sería escribir a ciegas encima de lo
        que otro dispositivo haya hecho mientras tanto."""
        return self.source == "remote"

    @property
    def defaults(self) -> dict:
        return dict(self.raw.get("defaults") or {})

    @property
    def names(self) -> list[str]:
        return [p["name"] for p in self.raw.get("pair") or [] if p.get("name")]


def endpoint(raw_local: Mapping[str, Any] | None = None) -> str:
    """Dónde está el catálogo, según los [defaults] de este dispositivo."""
    defaults = dict((raw_local or {}).get("defaults") or {})
    remote = defaults.get("catalog_remote") or defaults.get("remote") or model.DEFAULT_REMOTE
    path = defaults.get("catalog_path") or DEFAULT_CATALOG_PATH
    return f"{remote}:{path}"


def problema_de_ruta(ruta: str) -> str | None:
    """Qué tiene de malo una ruta de catálogo recién tecleada, o None si nada.

    Sin red solo se puede saber si nombra un fichero `.toml`, y basta para el
    error que de verdad se comete: poner la carpeta (`/prdrive-catalog`) en vez
    del fichero (`/prdrive-catalog/pairs.toml`). Vacía no es un problema: quien
    la pide cae a `DEFAULT_CATALOG_PATH`.

    Se aplica a lo que se TECLEA —el paso Conexión del instalador y los dos
    formularios de [defaults]—, nunca a lo que ya está escrito en un
    dispositivo: un catálogo sin extensión que hoy funciona no puede dejar de
    leerse por una actualización. Para ese caso está `explicar_carpeta()`."""
    limpia = (ruta or "").strip()
    if not limpia or limpia.lower().endswith(".toml"):
        return None
    return (f"La ruta del catálogo tiene que ser la de su fichero .toml, no la de "
            f"la carpeta: «{limpia}» no termina en .toml. Si el catálogo está "
            f"dentro, sería «{_dentro(limpia)}».")


def validar_ruta_editada(antes: Mapping[str, Any] | None,
                         despues: Mapping[str, Any] | None) -> None:
    """ConfigError si unos [defaults] editados ponen una carpeta por
    `catalog_path`. Solo si la CAMBIAN: guardar otro ajuste no puede
    tropezar con una ruta que ya estaba y que, si está ahí, funciona."""
    nueva = str((despues or {}).get("catalog_path") or "")
    if nueva == str((antes or {}).get("catalog_path") or ""):
        return
    problema = problema_de_ruta(nueva)
    if problema:
        raise ConfigError(problema)


def _dentro(ruta: str) -> str:
    """El `pairs.toml` de esa carpeta. Vale para una ruta y para un endpoint:
    `nas:` a secas es la raíz del remoto, y ahí no se antepone ninguna barra."""
    if not ruta or ruta.endswith((":", "/")):
        return ruta + FICHERO
    return f"{ruta}/{FICHERO}"


# ---------------------------------------------------------------------------
# rclone
# ---------------------------------------------------------------------------

def _binary() -> str:
    """Como model.rclone_binary(), pero sin sys.exit.

    Este módulo lo usa la UI, y ahí matar el proceso es cerrarle la ventana al
    usuario en las narices en vez de decirle qué falta."""
    if model.rclone_path() is None:
        raise ConfigError(
            f"No encuentro el binario de rclone en: {model.BIN_DIR / model.rclone_name()}\n"
            f"Sin él no se puede hablar con el catálogo.")
    return model.rclone_binary()


def run(args: list[str]) -> subprocess.CompletedProcess:
    """rclone con el config y el cwd del dispositivo.

    El cwd es `model.APP_DIR` porque `rclone.conf` resuelve contra él sus rutas
    relativas (`key_file`, `known_hosts_file`), que es lo que lo hace portable.
    CREATE_NO_WINDOW porque la UI puede correr bajo pythonw y si no cada
    invocación abriría una consola."""
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = model.CREATE_NO_WINDOW
    return subprocess.run(
        [_binary(), "--config", str(model.RCLONE_CONF), *NET_FLAGS, *args],
        cwd=str(model.APP_DIR), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=TIMEOUT, **kwargs)


def _parse(text: str, where: str) -> dict:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"El catálogo {where} no es TOML válido: {e}") from e


# ---------------------------------------------------------------------------
# Una carpeta no es un catálogo
# ---------------------------------------------------------------------------

# Quien pregunta a rclone: `run` aquí, `remote.Rclone.run` en el instalador.
Ejecutar = Callable[[list[str]], subprocess.CompletedProcess]


def _es_carpeta(ejecutar: Ejecutar, donde: str) -> bool | None:
    """Lo que dice `rclone lsjson --stat` de esa ruta: True si es una carpeta,
    False si es un fichero y None si no se sabe —no existe (rc 3), no contesta,
    o la respuesta no es la esperada—. Un «no se sabe» nunca se convierte en
    diagnóstico: un diagnóstico falso es peor que ninguno."""
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
    """Si la ruta del catálogo es una carpeta, qué decirle al usuario; si no, None.

    `rclone cat` de una carpeta NO falla: concatena, recursivamente, todos los
    ficheros que hay dentro —medido con rclone v1.75.1: el `pairs.toml`, el
    `.bak` que deja `push()` y las notas de `devices/` de `fleet`— y sale con 0.
    Lo que llega es un TOML con dos `[defaults]`, y `tomllib` contesta «Cannot
    declare ('defaults',) twice», que no se parece en nada a la causa (#48).

    Por eso, cuando algo huele mal, se le pregunta al remoto qué es esa ruta
    (`lsjson --stat`, que para una carpeta da `"IsDir": true`). Huele mal si lo
    leído no sirve (`fallo`) o si la ruta no termina en `.toml`: así se pillan
    también la carpeta vacía y la que solo tiene un `pairs.toml`, que `cat` lee
    sin error. En el camino bueno no cuesta ninguna ida y vuelta más. Tampoco
    se pregunta cuando falla el propio `cat`: sin red la pregunta tardaría lo
    mismo en no llegar, y quien espera es una ventana."""
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


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

def _write_cache(cat: Catalog) -> None:
    """Guardar la copia local. Que falle no es un error: el dispositivo puede
    estar de solo lectura o haberse extraído a media frase."""
    try:
        cache_toml().parent.mkdir(parents=True, exist_ok=True)
        cache_toml().write_text(cat.text, encoding="utf-8", newline="\n")
    except OSError:
        return
    store.write_json(cache_meta(), {"pulled_at": cat.stamp, "endpoint": cat.endpoint})


def pull(raw_local: Mapping[str, Any] | None = None) -> Catalog:
    """Leer el catálogo del remoto y cachearlo. ConfigError si no se puede, o
    si la ruta resulta ser una carpeta (ver `explicar_carpeta`): lo que `cat`
    trae de ahí no se cachea, porque no es el catálogo."""
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
    """La última copia buena, sin tocar la red. None si no hay o no sirve."""
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
    """El catálogo y, si algo no ha ido bien, qué decirle al usuario.

    Nunca lanza: la pantalla de parejas tiene que abrirse igual sin red."""
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


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------

def push(new_raw: Mapping[str, Any], base_text: str,
         raw_local: Mapping[str, Any] | None = None) -> list[str]:
    """Subir el catálogo. Devuelve qué se ha hecho.

    El orden importa: primero se genera y se verifica el texto, después se
    comprueba que el remoto sigue siendo el que se leyó, y solo entonces se
    escribe —con copia previa—. Así ningún fallo intermedio deja el catálogo a
    medias, y el peor caso posible es no haber escrito nada."""
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


# ---------------------------------------------------------------------------
# Comparación con lo que tiene el dispositivo
# ---------------------------------------------------------------------------

def pairs_by_name(cat: Catalog | None) -> dict[str, dict]:
    if cat is None:
        return {}
    return {p["name"]: dict(p) for p in cat.raw.get("pair") or [] if p.get("name")}


def find_pair(cat: Catalog | None, name: str) -> dict | None:
    return pairs_by_name(cat).get(name)


def diff_keys(a: Mapping[str, Any] | None, b: Mapping[str, Any] | None) -> tuple[str, ...]:
    """En qué claves difieren dos parejas (o dos [defaults]), en orden."""
    uno, otro = dict(a or {}), dict(b or {})
    return tuple(sorted(k for k in set(uno) | set(otro) if uno.get(k) != otro.get(k)))
