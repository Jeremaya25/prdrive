#!/usr/bin/env python3
"""El catálogo del remoto del usuario (`remote.toml`, antes `pairs.toml`).

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

El fichero tiene dos nombres posibles, porque ya no lleva solo parejas: los
remotos nuevos nacen con `remote.toml` y los de antes conservan `pairs.toml`
hasta que alguien los renombra (`renombrar()`, desde «Ajustes»). Da igual cuál
de los dos diga `catalog_path`: se lee el que haya, primero `remote.toml`
(`candidatos()`), y se escribe en el que se acaba de leer. Nunca se crea el
otro: un dispositivo de antes solo sabe leer `pairs.toml`, y dos ficheros
partirían la flota en dos catálogos.

`run()` es una función de módulo a propósito: los tests la sustituyen entera y
así ninguno toca la red.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import tomllib
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, NamedTuple, Sequence

from . import config_file, model, store
from .model import ConfigError

DEFAULT_CATALOG_PATH = model.DEFAULT_CATALOG_PATH
"""Ruta del catálogo de fábrica (`model.DEFAULT_CATALOG_PATH`), reexportada.

`install/profile.py` la importa de aquí para que instalador y dispositivo no
puedan discrepar. Con ella se sigue encontrando el `pairs.toml` de un remoto de
antes (`candidatos()`).
"""
BAK_SUFFIX = ".bak"
FICHERO = PurePosixPath(DEFAULT_CATALOG_PATH).name
"""Nombre del fichero dentro de la carpeta del catálogo.

Sale de la ruta de fábrica para no escribirlo dos veces; es lo que se sugiere
cuando alguien pone la carpeta.
"""
FICHERO_ANTERIOR = "pairs.toml"
"""El nombre de antes, que conserva un remoto hasta que se renombra."""
NOMBRES = (FICHERO, FICHERO_ANTERIOR)
"""Los dos nombres del catálogo, en el orden en que se buscan.

`remote.toml` va primero: si alguna vez están los dos (una subida que se cruzó
con el renombrado), manda ese.
"""
RC_NO_EXISTE = (3, 4)
"""Códigos con los que rclone dice que una ruta no existe: 3 carpeta, 4 fichero.

`cat` de un fichero que no está sale con 3 («directory not found»): rclone
busca una carpeta con ese nombre y no la encuentra (medido con v1.75.1 y el
backend local). En un remoto de cubetas sale con 0 y vacío: ver `leer()`.
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
SIN_FECHA = "fecha desconocida"
"""El `stamp` de una copia local cuyos metadatos no dicen cuándo se leyó."""


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
        endpoint: `remote:/ruta/al/remote.toml`: el fichero que se leyó de
            verdad, que con un remoto sin renombrar es su `pairs.toml`.
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
    """Devuelve dónde dice este dispositivo que está el catálogo (`remote:ruta`).

    Sale de los `[defaults]` del dispositivo. Qué fichero se lee de verdad lo
    decide `candidatos()`: si nombra uno de los dos nombres del catálogo, puede
    ser el otro.

    Args:
        raw_local: El `sync_config.toml` en bruto; sin él, los valores de
            fábrica.
    """
    defaults = dict((raw_local or {}).get("defaults") or {})
    remote = defaults.get("catalog_remote") or defaults.get("remote") or model.DEFAULT_REMOTE
    path = defaults.get("catalog_path") or DEFAULT_CATALOG_PATH
    return f"{remote}:{path}"


Ejecutar = Callable[[list[str]], subprocess.CompletedProcess]
"""Quien pregunta a rclone: `run` aquí, `remote.Rclone.run` en el instalador."""


def partir(donde: str) -> tuple[str, str]:
    """Separa una ruta o un endpoint en su carpeta, con la barra, y su nombre.

    `nas:remote.toml` es la raíz del remoto: la carpeta es `nas:`.
    """
    corte = max(donde.rfind("/"), donde.rfind(":"))
    return donde[:corte + 1], donde[corte + 1:]


def candidatos(donde: str) -> tuple[str, ...]:
    """Devuelve dónde buscar el catálogo, por orden.

    Si la ruta nombra uno de los dos nombres del catálogo (`NOMBRES`), son los
    dos en esa carpeta, `remote.toml` primero, nombre el que nombre. Así un
    dispositivo que dice `pairs.toml` lo sigue encontrando cuando el remoto se
    renombra, y uno nuevo que dice `remote.toml` encuentra el `pairs.toml` de un
    remoto de antes. Una ruta con otro nombre se lee tal cual.

    Args:
        donde: Endpoint o ruta del catálogo.
    """
    carpeta, nombre = partir(donde)
    if nombre not in NOMBRES:
        return (donde,)
    return tuple(carpeta + n for n in NOMBRES)


def leer(ejecutar: Ejecutar, donde: str) -> tuple[subprocess.CompletedProcess, str]:
    """Hace `cat` del catálogo con la regla de los dos nombres.

    Se pasa al candidato siguiente si rclone dice que el anterior no existe
    (`RC_NO_EXISTE`) o si lo trae vacío. Lo segundo es por los remotos de
    cubetas (S3, B2, GCS…), donde las carpetas no existen de verdad: ahí `cat`
    de un fichero que no está sale con 0 y nada, porque listar un prefijo
    vacío no es un error (`backend/s3/s3.go`, v1.75.1, sin
    `--s3-directory-markers`). Con cualquier otro fallo, sin red por ejemplo,
    se para: el siguiente tardaría lo mismo en no llegar. Si ninguno trae
    nada, vale la primera lectura vacía, que es un catálogo vacío como
    siempre. Lo usan los dos lectores del catálogo, el del dispositivo y el
    del instalador.

    Args:
        ejecutar: Quien ejecuta rclone (`Ejecutar`).
        donde: El endpoint del catálogo que dice el dispositivo.

    Returns:
        Lo que contestó el `cat` que cuenta y a qué endpoint se le hizo: el del
        fichero que trae algo si lo hay.
    """
    vacio: tuple[subprocess.CompletedProcess, str] | None = None
    for cual in candidatos(donde):        # nunca está vacía
        res = ejecutar(["cat", cual])
        if res.returncode == 0 and (res.stdout or "").strip():
            return res, cual
        if res.returncode == 0:
            vacio = vacio or (res, cual)
        elif res.returncode not in RC_NO_EXISTE:
            return res, cual
    return vacio or (res, cual)


def motivo_lectura(donde: str, cual: str, res: subprocess.CompletedProcess,
                   separador: str = ": ") -> str:
    """Dice por qué no se ha podido leer el catálogo.

    Si no está con ninguno de los dos nombres, los nombra a los dos: el que
    dice el dispositivo no es necesariamente el que falló.

    Args:
        donde: El endpoint del catálogo que dice el dispositivo.
        cual: El endpoint del último `cat` de `leer()`.
        res: Lo que contestó.
        separador: Lo que va entre la frase y lo que dijo rclone.
    """
    detalle = (res.stderr or "").strip()
    sitios = candidatos(donde)
    if res.returncode in RC_NO_EXISTE and len(sitios) > 1:
        return f"No hay catálogo en {' ni en '.join(sitios)}{separador}{detalle}"
    return f"No pude leer el catálogo {cual}{separador}{detalle}"


def problema_de_ruta(ruta: str) -> str | None:
    """Dice qué tiene de malo una ruta de catálogo recién tecleada.

    Sin red solo se puede saber si nombra un fichero `.toml`, y basta para el
    error que de verdad se comete: poner la carpeta (`/prdrive-catalog`) en vez
    del fichero (`/prdrive-catalog/remote.toml`). Vale cualquier `.toml`, los
    dos nombres del catálogo incluidos. Una ruta vacía no es un problema: quien
    la pide cae a `DEFAULT_CATALOG_PATH`.

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


def _dentro(ruta: str, nombre: str = FICHERO) -> str:
    """Devuelve el fichero de ese nombre dentro de esa carpeta.

    Vale para una ruta y para un endpoint: `nas:` a secas es la raíz del remoto
    y ahí no se antepone ninguna barra.
    """
    if not ruta or ruta.endswith((":", "/")):
        return ruta + nombre
    return f"{ruta}/{nombre}"


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


VERBOS_LECTURA = frozenset({"cat", "lsjson", "lsf", "lsd"})
"""Los verbos de rclone que solo leen del remoto: `run()` los apunta en `store`."""
VERBOS_COPIA = frozenset({"copy", "copyto"})
"""Los verbos que leen del remoto si el destino es un temporal local (`es_lectura()`)."""


def es_lectura(args: Sequence[str]) -> bool:
    """Dice si esa orden de rclone solo lee del remoto.

    Son lecturas `cat`, `lsjson`, `lsf` y `lsd`, y `copy`/`copyto` cuyo destino
    (el segundo argumento, justo tras el origen) es una ruta local dentro de la
    carpeta temporal del sistema: es como la flota baja las notas de `devices/`.
    Lo demás no lo es: una subida (`copyto` a un `remote:ruta`), `moveto`,
    `delete`, `deletefile`, `mkdir`, `purge`, `sync`, y una copia a cualquier
    otro sitio local, que sería escribir en una carpeta del usuario o del
    dispositivo. Ante lo que no sabe leer (flags antes de las rutas, sin
    destino) la respuesta es que no.

    Args:
        args: Los argumentos de rclone tal como se le dan a `run()`.
    """
    if not args:
        return False
    if args[0] in VERBOS_LECTURA:
        return True
    if args[0] in VERBOS_COPIA and len(args) >= 3 and not args[1].startswith("-"):
        return _es_temporal_local(args[2])
    return False


def _es_temporal_local(ruta: str) -> bool:
    """Dice si `ruta` es una carpeta local dentro de la temporal del sistema.

    Una ruta de rclone con `remote:` delante no es absoluta, y una relativa es
    del dispositivo (el cwd de rclone es `model.APP_DIR`): ninguna cuenta. La
    propia carpeta temporal tampoco, solo lo que hay dentro. `..` se resuelve
    antes de comparar, para que `/tmp/../home` no pase por temporal.
    """
    if not os.path.isabs(ruta):
        return False
    temporal = Path(os.path.abspath(tempfile.gettempdir()))
    destino = Path(os.path.abspath(ruta))
    return destino != temporal and destino.is_relative_to(temporal)


def run(args: list[str], apuntar: bool | None = None) -> subprocess.CompletedProcess:
    """Ejecuta rclone con el config y el cwd del dispositivo.

    El cwd es `model.APP_DIR` porque `rclone.conf` resuelve contra él sus rutas
    relativas (`key_file`, `known_hosts_file`), que es lo que lo hace portable.
    Lleva `CREATE_NO_WINDOW` porque la UI puede correr bajo `pythonw` y cada
    invocación abriría una consola. El hijo se crea como con `subprocess.run`,
    sin sesión ni grupo propios: si lo llama `sync.py` (la nota de la flota),
    `store.matar_arbol()` sigue alcanzándolo con el resto de la pasada.

    Una lectura se apunta mientras corre (`store.correr_apuntado()`) para que
    `store.matar_hijos()` la corte cuando se cierra la ventana; una escritura
    no, que cortarla a medias dejaría el remoto peor.

    Args:
        args: Argumentos de rclone tras `--config` y `NET_FLAGS`.
        apuntar: Si el hijo se apunta. Sin darlo, lo decide `es_lectura(args)`;
            quien dé `True` responde de que la orden no escribe.

    Returns:
        El resultado del proceso.

    Raises:
        ConfigError: Si no hay rclone.
        subprocess.TimeoutExpired: Si pasa `TIMEOUT`; el hijo ya está muerto.
    """
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = model.CREATE_NO_WINDOW
    if apuntar is None:
        apuntar = es_lectura(args)
    return store.correr_apuntado(
        [_binary(), "--config", str(model.RCLONE_CONF), *NET_FLAGS, *args],
        timeout=TIMEOUT, apuntar=apuntar, cwd=str(model.APP_DIR), text=True,
        encoding="utf-8", errors="replace", **kwargs)


def _parse(text: str, where: str) -> dict:
    """Parsea el TOML del catálogo.

    Raises:
        ConfigError: Si no es TOML válido; `where` dice de qué catálogo.
    """
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"El catálogo {where} no es TOML válido: {e}") from e


def _es_carpeta(ejecutar: Ejecutar, donde: str) -> bool | None:
    """Pregunta a rclone (`lsjson --stat`) si esa ruta es una carpeta.

    Un «no se sabe» nunca se convierte en diagnóstico: uno falso es peor que
    ninguno.

    Returns:
        True si es una carpeta, False si es un fichero y `None` si no se sabe
        (no existe, no contesta o la respuesta no es la esperada).
    """
    return _carpeta_en(_stat(ejecutar, donde))


def _stat(ejecutar: Ejecutar, donde: str) -> subprocess.CompletedProcess | None:
    """Devuelve lo que contesta `lsjson --stat` de esa ruta, o `None` si no contesta."""
    try:
        return ejecutar(["lsjson", "--stat", donde])
    except (OSError, subprocess.SubprocessError, ConfigError):
        return None


def _carpeta_en(res: subprocess.CompletedProcess | None) -> bool | None:
    """Lee el `IsDir` de lo que contestó `lsjson --stat`; `None` si no se sabe."""
    if res is None or res.returncode != 0:
        return None
    try:
        info = json.loads(res.stdout or "")
    except ValueError:
        return None
    if not isinstance(info, dict) or not isinstance(info.get("IsDir"), bool):
        return None
    return info["IsDir"]


def _existe(ejecutar: Ejecutar, donde: str) -> bool | None:
    """Pregunta a rclone (`lsjson --stat`) si en esa ruta hay un fichero.

    Returns:
        True si hay un fichero, False si rclone dice que no existe y `None` si
        no se sabe (no contesta, o ahí hay una carpeta).
    """
    res = _stat(ejecutar, donde)
    if res is not None and res.returncode in RC_NO_EXISTE:
        return False
    return True if _carpeta_en(res) is False else None


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
    también la carpeta vacía y la que solo tiene un fichero del catálogo, que
    `cat` lee sin error. En el camino bueno no cuesta ninguna ida y vuelta más,
    y no se pregunta cuando falla el propio `cat`: sin red la pregunta tardaría
    lo mismo en no llegar. Para sugerir el fichero se mira si dentro hay uno de
    los dos nombres, `remote.toml` primero.

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
    for nombre in NOMBRES:
        if _es_carpeta(ejecutar, _dentro(donde, nombre)) is False:
            return (f"{motivo} Dentro hay un {nombre}, así que seguramente es "
                    f"«{_dentro(ruta, nombre)}».")
    return f"{motivo} Por ejemplo «{_dentro(ruta)}», si es ahí donde está."


_CERROJO_COPIA = threading.Lock()
"""Un solo hilo a la vez escribe o lee la copia local.

Las pantallas leen el catálogo en hilos (`ui/segundo_plano.py`): uno que acaba
reescribe la copia mientras la ventana la lee (`cached()`) o mientras acaba
otro. Quien la escribe y quien la lee son la ventana y sus hilos, un solo
proceso, así que basta un cerrojo. Sin él:

- La copia son dos ficheros, el texto y sus metadatos, que se escriben uno
  detrás de otro y comparten el nombre del temporal (`catalog.tmp`): dos
  escrituras a la vez se lo pisan, y quien lee entre un fichero y el otro se
  lleva el texto de una lectura con la fecha y el endpoint de la anterior.
- En Windows, `os.replace()` (`store.write_text()`) no es atómico para quien
  mira: mientras dura, el destino no existe o no se deja abrir, así que
  `cached()` contestaría que no hay copia; y quien tenga abierto el destino en
  ese instante lo hace fallar (WinError 5) hasta que lo cierre, que es lo que
  `store.insistir()` espera, con un plazo.
  Medido en Windows 11 (NTFS, Python 3.14.8) con el equipo cargado: en un
  reemplazo que tardó 20 ms, el destino faltó de la carpeta 1,4 ms.
"""


def _write_cache(cat: Catalog) -> None:
    """Guarda la copia local; que falle no es un error.

    El dispositivo puede estar de solo lectura o haberse extraído a media
    frase. Cada fichero se sustituye entero (`store.write_text()`), nunca queda
    a medias ni vacío, y los dos se escriben con `_CERROJO_COPIA` tomado: quien
    lee la copia (`cached()`) ve la anterior o la nueva, con sus metadatos.
    """
    with _CERROJO_COPIA:
        try:
            cache_toml().parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        if not store.write_text(cache_toml(), cat.text):
            return
        meta = {"pulled_at": cat.stamp, "endpoint": cat.endpoint}
        anterior = store.read_json(cache_meta())
        sobra = str(anterior.get("duplicado") or "")
        if sobra and partir(sobra)[0] == partir(cat.endpoint)[0]:
            meta.update(duplicado=sobra, duplicado_visto=anterior.get("duplicado_visto", ""))
        store.write_json(cache_meta(), meta)


def apuntar_duplicado(sobra: str | None) -> None:
    """Apunta en la copia local que en la carpeta del catálogo están los dos nombres.

    O lo borra, con `None`. Lo apunta quien lo ve: `push()` cuando su subida a
    `pairs.toml` se cruza con un renombrado, y quien mira la carpeta antes de
    renombrar. Leer el catálogo no lo ve (sería una ida y vuelta más en cada
    lectura), pero sí lo borra cuando lee `pairs.toml` porque `remote.toml` no
    está. Lo enseña «Reparación» (`duplicado()`). Que falle no es un error.

    Args:
        sobra: El endpoint del `pairs.toml` que sobra, o `None` si ya no hay
            dos.
    """
    with _CERROJO_COPIA:
        meta = store.read_json(cache_meta())
        if sobra:
            meta.update(duplicado=sobra, duplicado_visto=store.stamp())
        elif "duplicado" in meta:
            meta.pop("duplicado", None)
            meta.pop("duplicado_visto", None)
        else:
            return
        try:
            cache_meta().parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        store.write_json(cache_meta(), meta)


def _metadatos() -> dict:
    """Lee los metadatos de la copia local sin cruzarse con quien la escribe.

    Returns:
        Lo que dice `state/catalog.json`, o `{}` si no hay o no se entiende.
    """
    with _CERROJO_COPIA:
        return store.read_json(cache_meta())


def duplicado() -> tuple[str, str] | None:
    """Devuelve el `pairs.toml` que sobra junto al `remote.toml`, y desde cuándo se sabe.

    Lee la copia local, sin red.

    Returns:
        `(endpoint del que sobra, sello de cuándo se vio)`, o `None` si no
        consta que haya dos.
    """
    meta = _metadatos()
    sobra = meta.get("duplicado")
    if not isinstance(sobra, str) or not sobra:
        return None
    return sobra, str(meta.get("duplicado_visto") or "")


def ultimo_leido() -> str:
    """Devuelve de qué fichero salió la copia local, o una cadena vacía si no hay.

    Lee los metadatos, sin red: es lo que dice si este remoto conserva todavía
    su `pairs.toml`.
    """
    leido = _metadatos().get("endpoint")
    return leido if isinstance(leido, str) else ""


def pull(raw_local: Mapping[str, Any] | None = None) -> Catalog:
    """Lee el catálogo del remoto y lo cachea.

    Lo que `cat` trae de una carpeta no se cachea: no es el catálogo (ver
    `explicar_carpeta`). El `Catalog` lleva el endpoint del fichero que se ha
    leído, que es donde `push()` escribirá.

    Raises:
        ConfigError: Si no se puede leer, no es TOML válido o la ruta es una
            carpeta.
    """
    where = endpoint(raw_local)
    res, donde = leer(run, where)
    if res.returncode != 0:
        raise ConfigError(motivo_lectura(where, donde, res))
    texto = res.stdout or ""
    try:
        raw = _parse(texto, donde)
    except ConfigError as e:
        raise ConfigError(explicar_carpeta(run, donde, fallo=True)
                          or str(e)) from e
    carpeta = explicar_carpeta(run, donde)
    if carpeta:
        raise ConfigError(carpeta)
    cat = Catalog(raw=raw, text=texto, source="remote",
                  stamp=store.stamp(), endpoint=donde)
    _write_cache(cat)
    if donde != candidatos(where)[0]:
        apuntar_duplicado(None)        # se ha leído pairs.toml porque no hay remote.toml
    return cat


_REINTENTOS_COPIA = 5
"""Veces que `cached()` intenta abrir la copia si Windows se la niega."""


def cached() -> Catalog | None:
    """Devuelve la última copia buena, sin tocar la red.

    Es `None` si no hay copia o no sirve.

    El texto y sus metadatos se leen con `_CERROJO_COPIA` tomado: si un hilo
    está reescribiendo la copia se le espera, que es lo que tarda en escribir
    dos ficheros pequeños, y lo que se devuelve es de una sola lectura.

    Queda quien no es prdrive: en Windows, un programa que tenga abierta la
    copia sin compartirla (un antivirus que la repasa recién escrita) hace que
    abrirla dé `PermissionError`. Dura un instante, así que se reintenta unas
    pocas veces antes de contestar que no hay copia, que la ventana enseñaría
    como «sin catálogo».
    """
    with _CERROJO_COPIA:
        for intento in range(_REINTENTOS_COPIA):
            try:
                text = cache_toml().read_text(encoding="utf-8")
                break
            except PermissionError:
                if intento + 1 == _REINTENTOS_COPIA:
                    return None
                time.sleep(0.02)
            except OSError:
                return None
        meta = store.read_json(cache_meta())
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    return Catalog(raw=raw, text=text, source="cache",
                   stamp=str(meta.get("pulled_at") or SIN_FECHA),
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
         raw_local: Mapping[str, Any] | None = None, ejecutar: Ejecutar | None = None,
         donde_pedido: str | None = None, cachear: bool = True) -> list[str]:
    """Sube el catálogo al remoto y devuelve qué se ha hecho.

    El orden importa: primero se genera y verifica el texto, después se
    comprueba que el remoto sigue siendo el que se leyó y solo entonces se
    escribe, con copia previa. Así ningún fallo intermedio deja el catálogo a
    medias y el peor caso es no haber escrito nada.

    Se escribe en el fichero que existe justo antes de escribir, con la misma
    regla que al leer (`leer()`): si otro dispositivo ha renombrado el catálogo
    mientras tanto, el contenido es el mismo y el cambio va al nombre nuevo.
    Una subida a `pairs.toml` se comprueba después: si en ese rato ha aparecido
    `remote.toml`, el cambio ha caído en el fichero que ya no vale, y se dice.

    Args:
        new_raw: El catálogo nuevo, en bruto.
        base_text: El texto leído del remoto sobre el que se parte.
        raw_local: El config en bruto del dispositivo, para saber dónde está el
            catálogo.
        ejecutar: Quien ejecuta rclone; sin él, el del dispositivo (`run()`). El
            instalador pasa el suyo, con su config efímero.
        donde_pedido: Dónde está el catálogo (`remote:ruta`); sin él, lo que
            dice `raw_local`.
        cachear: Si se deja la copia local del dispositivo (`state/`); el
            instalador no la deja, porque su `state/` no es el de ningún
            dispositivo.

    Raises:
        ConfigError: Si el texto generado no se relee igual, si el remoto
            cambió desde que se leyó, si falla algún paso de rclone o si la
            subida se cruzó con un renombrado.
    """
    rclone = ejecutar or run
    where = donde_pedido or endpoint(raw_local)
    text = config_file.dumps_checked(new_raw, config_file.header_of(base_text))

    actual, donde = leer(rclone, where)
    if actual.returncode != 0:
        raise ConfigError(f"No pude releer el catálogo antes de escribir. "
                          f"{motivo_lectura(where, donde, actual)}. "
                          f"No se ha escrito nada.")
    if actual.stdout != base_text:
        raise ConfigError(
            "El catálogo ha cambiado en el remoto desde que lo leíste, así que no "
            "se ha escrito nada. Otro dispositivo lo ha tocado mientras tanto: cierra "
            "la pantalla y vuelve a abrirla para partir de la versión buena, y "
            "repite el cambio.")

    hechos: list[str] = []
    copia = rclone(["copyto", donde, donde + BAK_SUFFIX])
    if copia.returncode != 0:
        raise ConfigError(f"No pude dejar la copia {donde}{BAK_SUFFIX}: "
                          f"{(copia.stderr or '').strip()}. No se ha escrito nada.")
    hechos.append(f"Copia previa en {donde}{BAK_SUFFIX}")

    tmpdir = Path(tempfile.mkdtemp(prefix="prdrive-cat-"))
    try:
        tmp = tmpdir / "catalogo.toml"
        tmp.write_text(text, encoding="utf-8", newline="\n")
        subida = rclone(["copyto", str(tmp), donde])
        if subida.returncode != 0:
            raise ConfigError(f"No pude escribir el catálogo {donde}: "
                              f"{(subida.stderr or '').strip()}. "
                              f"La versión anterior sigue en {donde}{BAK_SUFFIX}.")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    hechos.append(f"Catálogo actualizado en {donde}")

    sitios = candidatos(where)
    if len(sitios) > 1 and donde == sitios[1] and _existe(rclone, sitios[0]) is True:
        if cachear:
            apuntar_duplicado(donde)
        raise ConfigError(
            f"El cambio se ha subido a {donde}, pero mientras tanto otro "
            f"dispositivo ha renombrado el catálogo a {sitios[0]}, que es el que "
            f"vale: el cambio no cuenta. Vuelve a abrir la pantalla y repítelo. "
            f"«Reparación» explica qué hacer con el {FICHERO_ANTERIOR} que sobra.")

    if cachear:
        _write_cache(Catalog(raw=dict(new_raw), text=text, source="remote",
                             stamp=store.stamp(), endpoint=donde))
    return hechos


def nombres_en(ejecutar: Ejecutar, carpeta: str) -> frozenset[str] | None:
    """Devuelve qué ficheros del catálogo hay en esa carpeta del remoto.

    Es un `lsjson --files-only` de la carpeta, que no baja a `devices/`. Solo
    cuentan los dos nombres del catálogo y sus `.bak`.

    Args:
        ejecutar: Quien ejecuta rclone (`Ejecutar`).
        carpeta: La carpeta del catálogo, `remote:/ruta/`.

    Returns:
        Los nombres que hay; vacío si la carpeta no existe, y `None` si no se
        sabe.
    """
    try:
        res = ejecutar(["lsjson", "--files-only", carpeta])
    except (OSError, subprocess.SubprocessError, ConfigError):
        return None
    if res.returncode in RC_NO_EXISTE:
        return frozenset()
    if res.returncode != 0:
        return None
    try:
        lista = json.loads(res.stdout or "")
    except ValueError:
        return None
    if not isinstance(lista, list):
        return None
    buscados = set(NOMBRES) | {n + BAK_SUFFIX for n in NOMBRES}
    return frozenset(e["Name"] for e in lista
                     if isinstance(e, dict) and e.get("Name") in buscados)


class SinRenombrar(NamedTuple):
    """Dónde están los dos nombres del catálogo de este dispositivo.

    Args:
        nuevo: El endpoint de `remote.toml`.
        viejo: El endpoint de `pairs.toml`.
        carpeta: La carpeta de los dos, `remote:/ruta/`.
    """
    nuevo: str
    viejo: str
    carpeta: str


def sin_renombrar(raw_local: Mapping[str, Any] | None = None) -> SinRenombrar | None:
    """Devuelve los dos nombres del catálogo de este dispositivo.

    Returns:
        Los dos endpoints y su carpeta, o `None` si `catalog_path` nombra un
        fichero con otro nombre: ese no se renombra.
    """
    sitios = candidatos(endpoint(raw_local))
    if len(sitios) < 2:
        return None
    nuevo, viejo = sitios
    return SinRenombrar(nuevo, viejo, partir(nuevo)[0])


def apuntar_renombrado(viejo: str, nuevo: str) -> None:
    """Apunta en la copia local que el catálogo que se leía como `viejo` es ya `nuevo`."""
    with _CERROJO_COPIA:
        meta = store.read_json(cache_meta())
        if not meta:
            return
        if meta.get("endpoint") == viejo:
            meta["endpoint"] = nuevo
        meta.pop("duplicado", None)
        meta.pop("duplicado_visto", None)
        store.write_json(cache_meta(), meta)


def renombrar(raw_local: Mapping[str, Any] | None = None) -> list[str]:
    """Renombra el `pairs.toml` del remoto a `remote.toml`, con su `.bak`.

    Es un `moveto` en la misma carpeta: no reescribe el contenido, así que no
    pierde comentarios ni pasa por `push()`. Antes se mira qué hay, porque
    `moveto` pisa el destino sin preguntar. El `catalog_path` de los
    dispositivos no se toca: los que dicen `pairs.toml` encuentran el nombre
    nuevo con `candidatos()`.

    Returns:
        Lo que se ha hecho, línea a línea.

    Raises:
        ConfigError: Si no hay nada que renombrar, si están los dos nombres o
            si no se ha podido; el catálogo queda como estaba salvo que el
            mensaje diga otra cosa.
    """
    sitio = sin_renombrar(raw_local)
    if sitio is None:
        raise ConfigError(
            f"El catálogo de este dispositivo ({endpoint(raw_local)}) no se llama "
            f"{FICHERO_ANTERIOR} ni {FICHERO}: no hay nada que renombrar.")
    hay = nombres_en(run, sitio.carpeta)
    if hay is None:
        raise ConfigError(f"No he podido mirar qué hay en {sitio.carpeta}. No se ha "
                          f"tocado nada.")
    if FICHERO in hay:
        if FICHERO_ANTERIOR in hay:
            apuntar_duplicado(sitio.viejo)
            raise ConfigError(
                f"En {sitio.carpeta} ya están {FICHERO} y {FICHERO_ANTERIOR}. Vale "
                f"{FICHERO}: no se ha tocado nada. «Reparación» explica qué hacer "
                f"con el que sobra.")
        apuntar_duplicado(None)
        raise ConfigError(f"El catálogo ya se llama {FICHERO}: no hay nada que "
                          f"renombrar.")
    if FICHERO_ANTERIOR not in hay:
        raise ConfigError(f"En {sitio.carpeta} no hay ningún {FICHERO_ANTERIOR}: no "
                          f"hay nada que renombrar.")

    movido = run(["moveto", sitio.viejo, sitio.nuevo])
    if movido.returncode != 0:
        detalle = (movido.stderr or "").strip()
        despues = nombres_en(run, sitio.carpeta) or frozenset()
        if FICHERO in despues and FICHERO_ANTERIOR in despues:
            apuntar_duplicado(sitio.viejo)
            raise ConfigError(
                f"No he podido renombrar {sitio.viejo}: {detalle}. Se ha quedado "
                f"a medias, con los dos nombres en la carpeta; vale {FICHERO}. "
                f"«Reparación» explica qué hacer con el que sobra.")
        raise ConfigError(f"No he podido renombrar {sitio.viejo}: {detalle}. El "
                          f"catálogo sigue como estaba.")
    hechos = [f"{sitio.viejo} se llama ahora {sitio.nuevo}"]

    viejo_bak, nuevo_bak = sitio.viejo + BAK_SUFFIX, sitio.nuevo + BAK_SUFFIX
    if FICHERO_ANTERIOR + BAK_SUFFIX in hay and FICHERO + BAK_SUFFIX not in hay:
        copia = run(["moveto", viejo_bak, nuevo_bak])
        if copia.returncode == 0:
            hechos.append(f"La copia previa se llama ahora {nuevo_bak}")
        else:
            hechos.append(f"La copia previa se queda como {viejo_bak} "
                          f"({(copia.stderr or '').strip()}). No importa: la "
                          f"próxima escritura deja {nuevo_bak}.")
    apuntar_renombrado(sitio.viejo, sitio.nuevo)
    return hechos


APARTADO = ".apartado-"
"""Lo que se le añade al `pairs.toml` que sobra, delante de la fecha, al apartarlo."""


def apartar_sobrante(raw_local: Mapping[str, Any] | None = None) -> list[str]:
    """Aparta el `pairs.toml` que sobra junto a un `remote.toml`.

    Lo deja al lado como `pairs.toml.apartado-<fecha>`: no se borra, porque
    puede llevar un cambio que alguien quiera rescatar a mano, y con ese
    nombre ya no lo lee nadie. Antes se mira que sigan los dos: `moveto` no
    pregunta.

    Returns:
        Lo que se ha hecho, línea a línea.

    Raises:
        ConfigError: Si no están los dos nombres o no se ha podido; entonces no
            se ha tocado nada.
    """
    sitio = sin_renombrar(raw_local)
    if sitio is None:
        raise ConfigError(
            f"El catálogo de este dispositivo ({endpoint(raw_local)}) no se llama "
            f"{FICHERO_ANTERIOR} ni {FICHERO}: no hay nada que apartar.")
    hay = nombres_en(run, sitio.carpeta)
    if hay is None:
        raise ConfigError(f"No he podido mirar qué hay en {sitio.carpeta}. No se ha "
                          f"tocado nada.")
    if not (FICHERO in hay and FICHERO_ANTERIOR in hay):
        apuntar_duplicado(None)
        raise ConfigError(f"En {sitio.carpeta} ya no están los dos nombres del "
                          f"catálogo: no hay nada que apartar.")
    destino = f"{sitio.viejo}{APARTADO}{datetime.now():%Y%m%d-%H%M%S}"
    res = run(["moveto", sitio.viejo, destino])
    if res.returncode != 0:
        raise ConfigError(f"No he podido apartar {sitio.viejo}: "
                          f"{(res.stderr or '').strip()}. No se ha tocado nada.")
    apuntar_duplicado(None)
    return [f"{sitio.viejo} se ha apartado como {destino}: ya no lo lee nadie, "
            f"y no se ha borrado."]


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
