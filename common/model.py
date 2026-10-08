#!/usr/bin/env python3
"""El modelo de datos de `sync_config.toml`.

El TOML se lee una vez y se convierte en objetos ya resueltos (`Config` con sus
`Pair`, y cada pareja con su `Mode`). A partir de ahí nadie vuelve a preguntar
por claves del TOML ni repite `.get(clave, defecto)`, y `defaults` deja de
viajar por las firmas: la jerarquía de configuración se resuelve solo aquí.

Añadir un flag de rclone sigue siendo cosa del TOML, no de este módulo.
"""

from __future__ import annotations

import fnmatch
import os
import platform
import re
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

# tomllib es stdlib desde Python 3.11; en versiones anteriores se recurre a
# `tomli`.
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore
    except ModuleNotFoundError:
        sys.exit("Necesitas Python 3.11+ (tomllib) o instalar tomli: pip install tomli")


APP_DIR = Path(__file__).resolve().parent.parent
"""La carpeta de la aplicación (`.prdrive/` en un dispositivo provisionado).

Contiene `sync_config.toml`, `rclone.conf`, `bin/` y `keys/`, y contra ella
rclone resuelve las rutas relativas de su config. Sale de `__file__` (este
módulo vive en `<app>/common/`), así que nada depende de la letra de unidad ni
del nombre de la carpeta.
"""
DEVICE_ROOT = APP_DIR.parent  # las rutas `local` del config son relativas a aquí
CONFIG_FILE = APP_DIR / "sync_config.toml"
RCLONE_CONF = APP_DIR / "rclone.conf"
STATE_DIR = APP_DIR / "state"
FILTERS_DIR = APP_DIR / "filters"
LOG_DIR = APP_DIR / "logs"

SYNC_PY = APP_DIR / "sync.py"  # a quien lanzan la UI y el servicio
RUNSYNC_PY = APP_DIR / "runsync.py"  # el vigilante del llavero lo relanza
PENWATCH_PY = APP_DIR / "penwatch.py"

TIPO_UNIDAD = "unidad"
"""Tipo de raíz por defecto: un dispositivo extraíble.

Es lo que se asume cuando el fichero de control no tiene línea `tipo=`.
"""
TIPO_EQUIPO = "equipo"
"""Tipo de la raíz que deja el asistente «En este equipo» en el ordenador.

Lleva `tipo=equipo` en el fichero de control.

Un penwatch viejo solo lee `id=` y lo ignora.
"""


def tipo_raiz(app_dir: Path | str | None = None) -> str:
    """Lee el tipo de raíz del fichero de control de una carpeta de programa.

    Repite el nombre del fichero (`<app>/PRDRIVE`) como `fleet.py` y
    `penwatch.CONTROL_FILE`; un test las ata.

    Args:
        app_dir: Carpeta del programa; por defecto, la que está corriendo.

    Returns:
        El valor de la línea `tipo=`, o `TIPO_UNIDAD` si falta el fichero o la
        línea.
    """
    ruta = Path(app_dir or APP_DIR) / "PRDRIVE"
    try:
        texto = ruta.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return TIPO_UNIDAD
    for linea in texto.splitlines():
        linea = linea.strip()
        if linea.lower().startswith("tipo="):
            return linea[5:].strip().lower() or TIPO_UNIDAD
    return TIPO_UNIDAD


def es_equipo(app_dir: Path | str | None = None) -> bool:
    """Indica si la carpeta de programa es una raíz de equipo (`tipo=equipo`)."""
    return tipo_raiz(app_dir) == TIPO_EQUIPO


def daemon_lock() -> Path:
    """Devuelve la ruta del registro del servicio (`daemon.lock.json`).

    Lo escribe `runsync.py` y lo lee quien deba saber si hay algo en marcha
    antes de tocar el estado (p. ej. borrar un bloqueo de bisync). Es una
    función y no una constante porque los tests mueven `STATE_DIR` al vuelo.
    `penwatch.py` guarda su propia copia de la ruta (no puede importar nada del
    dispositivo) y un test las ata.
    """
    return STATE_DIR / "daemon.lock.json"


def ui_lock() -> Path:
    """Devuelve la ruta del registro de la ventana abierta (`ui.lock.json`).

    Ver `daemon_lock`.
    """
    return STATE_DIR / "ui.lock.json"


class ConfigError(Exception):
    """El config es inválido.

    Se lanza en vez de llamar a `sys.exit` porque la UI comparte este modelo y
    matar el proceso le cerraría la ventana al usuario. Los puntos de entrada
    por línea de comandos la capturan y salen con su mensaje.
    """


DEFAULT_REMOTE = "remote"
DEFAULT_MODE = "bisync"

DEFAULT_DEVICE_REMOTE = "disp"
"""Nombre del remote `combine` con el que el lado local deja de ser una ruta absoluta.

Lo escribe el instalador en los `[defaults]` de cada dispositivo nuevo
(`install/deploy.device_config`). Vive aquí porque este módulo decide qué
nombres valen (`_device_remote_name`) y qué se hace con ellos
(`Config.pen_environment`).
"""
RAIZ_UPSTREAM = "raiz"
"""Nombre del upstream `combine` de la RAÍZ del dispositivo (pareja con `local = "."`).

Tiene que ser un nombre y no `.`. Sale en el prefijo de los listados de bisync,
así que cambiarlo invalida esos baselines. Ver `Pair.top_level_dir`.
"""
DEFAULT_CATALOG_PATH = "/prdrive-catalog/remote.toml"
"""Ruta del catálogo de fábrica; cada usuario pone la suya.

Se cambia por dispositivo con `[defaults].catalog_path` y el instalador la
pregunta en su paso de conexión. Vive aquí y no en `common/catalog.py` (que la
reexporta) porque la pareja del llavero cuelga de la carpeta del catálogo y
este módulo no puede importar aquel, que lo importa a él.
"""

LLAVERO = "keychain"
"""Nombre de la pareja del llavero, que construye el código cuando hay `[keychain]`.

Es también su carpeta en `state/` y `filters/`, y queda reservado mientras el
llavero esté activo: una pareja del usuario no puede llamarse así.
"""
LLAVERO_LOCAL = ".keychain"
"""Carpeta del llavero en la raíz del dispositivo, oculta como `.prdrive/`."""
LLAVERO_REMOTO = "keychain"
"""Subcarpeta del llavero dentro de la carpeta del catálogo, en el remoto."""
LLAVERO_REGLAS = ("- *.old.kdbx", "+ *.kdbx", "+ LEEME.txt", "- **")
"""Los filtros de la pareja del llavero, en su orden: solo viaja lo que tiene que viajar.

Las bases (`*.kdbx`, también las copias de un conflicto, que acaban en `.kdbx`
por `suffix-keep-extension`) y el compañero fijo `LEEME.txt` (H-12). No viajan
los temporales del guardado de KeePassXC (`<base>.kdbx.XXXXXX`, H-11), la copia
de antes de guardar (`<base>.old.kdbx`), los `.passkey` ni nada exportado en
claro (S6). El orden importa: gana la primera regla que casa.
"""
LLAVERO_FLAGS: Mapping[str, Any] = {"conflict-loser": "num", "resync-mode": "newer"}
"""Los flags propios de la pareja del llavero, encima de los de bisync.

`conflict-loser = num`: el perdedor de un conflicto se queda al lado, numerado,
para combinarlo (H-14); no sale por `.prversions/` como en el resto de parejas
versionadas (`sync.py` solo pone `delete` si no hay otro). `resync-mode =
newer`: un `--resync` se queda con la base más nueva de los dos lados, no con
la del dispositivo (H-13). Solo va en un `--resync`: rclone lo toma como uno
(`setResyncDefaults()`), y `sync.build_command()` lo quita de las demás.
"""
LLAVERO_LLAVE = "llave.keyx"
"""El fichero llave de un llavero sin contraseña (`[keychain] llave_interna`), en `.keychain/`.

Nombre fijo, así que no hace falta apuntar su ruta por equipo. No lo deja pasar
ningún filtro de `LLAVERO_REGLAS`: es lo que **no** viaja nunca al remoto.
"""
REGLA_SIN_LLAVERO = f"- /{LLAVERO_LOCAL}/**"
"""La regla que reciben las parejas del usuario que sincronizan la raíz entera.

Sin ella, una pareja con `local = "."` llevaría la base por otro camino, con
otras reglas, y sin la comprobación previa del llavero.
"""
REGLA_SIN_PROGRAMA = f"- /{APP_DIR.name}/**"
"""La regla que reciben las parejas del usuario que sincronizan la raíz entera.

Deja fuera la carpeta del programa (`.prdrive/` en un dispositivo): lleva su
clave privada (`keys/`) y su `rclone.conf`, y no hay pareja que deba subirla al
remoto ni, en un espejo hacia abajo, borrarla. Va antes que `REGLA_SIN_LLAVERO`
y que cualquier `+` de la pareja, y no la quita ningún TOML.
"""

VERSIONS_DIR = ".prversions"
"""Carpeta de versiones de una pareja, dentro de su propia raíz (`Pair.versions_path1`).

rclone rechaza un `--backup-dir` que solape con el destino («destination and
parameter to --backup-dir mustn't overlap») y aborta la pareja con error
crítico. Por eso `bisync.filters_content` la excluye siempre con la PRIMERA
regla: rclone aplica las reglas en orden y gana la primera que casa.
"""
RUIDO_DEL_SISTEMA = (
    "system volume information", "$recycle.bin", "recycler", "lost+found",
    ".ds_store", ".spotlight-v100", ".fseventsd", ".trashes", "desktop.ini",
    "autorun.inf", ".trash-*",
)
"""Lo que el sistema deja en la raíz de cualquier volumen, en minúsculas.

Cada entrada es un patrón de `fnmatch` (`.Trash-1000` lleva el uid de quien
tiró algo) que se compara con el nombre en minúsculas: Windows escribe
`$RECYCLE.BIN` y `$Recycle.Bin` según la versión. No es contenido de nadie, y
de ahí sale lo que el instalador no cuenta como «cosas de otro»
(`install/device.RUIDO`) y lo que el agente no mira al vigilar una pareja que
sincroniza la raíz del dispositivo (`common/huella.py`): un recorrido que
tropieza con el `System Volume Information` de Windows (acceso denegado)
dejaría esa pareja sin vigilancia.
"""
DEFAULT_INTERVAL_MIN = 30.0  # minutos entre ciclos del servicio

CREATE_NO_WINDOW = 0x08000000
"""Flag de creación de procesos de Windows: no abrir consola.

rclone es una app de consola: lanzada desde un proceso sin consola (`pythonw`,
el servicio), Windows le abriría una ventana nueva por invocación.
"""
CREATE_NEW_PROCESS_GROUP = 0x00000200
"""Flag de creación de procesos de Windows: un proceso suelto, que no recibe el Ctrl+C de quien lo lanza."""


_MAQUINAS_PE = {
    0x8664: "amd64",
    0xAA64: "arm64",
    0x01C4: "arm",  # ARM de 32 bits (ARMNT)
    0x014C: "x86",
}
"""Tipos de máquina de la cabecera PE: lo que contesta `IsWow64Process2`."""


def maquina_nativa_windows() -> int | None:
    """Devuelve el tipo de máquina nativa según `IsWow64Process2`.

    Es función de módulo y no un bloque de `machine_arch()` porque es lo único
    de aquí que depende del equipo donde corre: un test la sustituye para
    simular un ARM sin necesitar uno.

    Returns:
        El código de máquina PE (p. ej. 0xAA64 para arm64), o `None` si no se
        sabe: fuera de Windows, antes de Windows 10 1709 o sin ctypes.
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.argtypes = []
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.IsWow64Process2.argtypes = [ctypes.c_void_p,
                                        ctypes.POINTER(ctypes.c_ushort),
                                        ctypes.POINTER(ctypes.c_ushort)]
        k32.IsWow64Process2.restype = ctypes.c_int
        proceso = ctypes.c_ushort()
        nativa = ctypes.c_ushort()
        if not k32.IsWow64Process2(k32.GetCurrentProcess(),
                                   ctypes.byref(proceso), ctypes.byref(nativa)):
            return None
        return nativa.value or None
    except (OSError, AttributeError, ValueError):
        return None


def machine_arch() -> str:
    """Devuelve la arquitectura del equipo (`platform.machine()` corregido).

    Windows on ARM ejecuta los binarios x64 emulados y les miente: en un Python
    x64 sobre un Snapdragon, `platform.machine()`, `PROCESSOR_ARCHITECTURE` y
    `GetNativeSystemInfo()` contestan 'AMD64', y `PROCESSOR_ARCHITEW6432` solo
    lo pone Windows en procesos de 32 bits. Solo `IsWow64Process2()` (Windows
    10 1709+) da por separado la máquina nativa.

    Importa porque instalador y dispositivo no corren con el mismo Python: el
    instalador es un .exe x64 y el `runsync.py` del dispositivo corre con el
    Python del equipo, ARM64 nativo en un portátil ARM. Sin esto rclone iría a
    `bin/x64` y el dispositivo lo buscaría en `bin/arm`.
    """
    nativa = maquina_nativa_windows()
    if nativa in _MAQUINAS_PE:
        return _MAQUINAS_PE[nativa]
    return platform.machine().lower()


def arch_dir() -> str:
    """Devuelve el subdirectorio de `bin/` que corresponde a la CPU: `arm` o `x64`.

    Si no reconoce la arquitectura avisa por consola y usa `x64`.
    """
    machine = machine_arch()
    if machine.startswith("arm") or machine in {"aarch64", "aarch64_be", "arm64"}:
        return "arm"
    if machine in {"x86_64", "amd64", "x64", "i386", "i686", "x86"}:
        return "x64"
    print(f"Aviso: arquitectura '{machine}' no reconocida; usando bin/x64.")
    return "x64"


def carpetas_bin(app_dir: Path) -> tuple[Path, ...]:
    """Devuelve, por orden, dónde buscar rclone dentro de una carpeta de programa.

    En Windows ARM64 la lista añade `bin/x64`: los x64 se ejecutan emulados,
    pero un x64 no ejecuta ARM, así que la lista no es simétrica.

    Args:
        app_dir: Carpeta del programa. Se recibe porque el agente residente
            busca el rclone de raíces que no son la suya; para este dispositivo
            son `BIN_DIR` y `BIN_FALLBACK_DIRS`.
    """
    propia = app_dir / "bin" / arch_dir()
    if os.name == "nt" and arch_dir() == "arm":
        return (propia, app_dir / "bin" / "x64")
    return (propia,)


BIN_DIR, *_recambios = carpetas_bin(APP_DIR)
BIN_FALLBACK_DIRS: tuple[Path, ...] = tuple(_recambios)
"""Carpetas alternativas donde buscar rclone (`bin/x64` en Windows ARM64)."""


def rclone_name() -> str:
    """Devuelve el nombre del ejecutable de rclone en este sistema."""
    return "rclone.exe" if os.name == "nt" else "rclone"


RCLONE_DEL_AGENTE = "PRDRIVE_RCLONE"
"""Variable de entorno con la que el agente residente pasa su propio rclone.

Es el rclone comprobado contra la versión fijada al instalarlo: así el agente
no ejecuta el binario que traiga la unidad, lo único suyo que la huella de
`agente.huella()` no cubre barato. Llega sola a todo lo que cuelga del agente:
la pasada, la ventana que abre y lo que esa ventana lance.
"""


def rclone_del_agente() -> Path | None:
    """Devuelve el rclone que ha pasado el agente, o `None` si no ha pasado ninguno."""
    ruta = os.environ.get(RCLONE_DEL_AGENTE, "").strip()
    return Path(ruta) if ruta else None


def rclone_path() -> Path | None:
    """Devuelve el rclone del dispositivo, o `None` si no hay ninguno utilizable.

    Si el agente ha pasado el suyo, ese y solo ese (`None` si falta): caer en
    el de la unidad es justo lo que el agente quiere evitar.
    """
    del_agente = rclone_del_agente()
    if del_agente is not None:
        try:
            return del_agente if del_agente.is_file() else None
        except OSError:
            return None
    for carpeta in (BIN_DIR, *BIN_FALLBACK_DIRS):
        binary = carpeta / rclone_name()
        try:
            if binary.is_file():
                return binary
        except OSError:
            continue
    return None


def rclone_binary() -> str:
    """Devuelve la ruta ejecutable del rclone de este dispositivo.

    Raises:
        SystemExit: Si no hay rclone utilizable, con el mensaje que dice cómo
            arreglarlo.
    """
    binary = rclone_path()
    if binary is None and rclone_del_agente() is not None:
        sys.exit(
            f"El agente de este equipo ha pasado su rclone ({rclone_del_agente()}) "
            f"y no está ahí. Vuelve a instalar el agente o actualízalo."
        )
    if binary is None:
        # Lo normal es un dispositivo sin preparar para este equipo: la cura es
        # el instalador, que baja el rclone fijado y lo comprueba, no buscar
        # uno a mano.
        sys.exit(
            f"No encuentro el binario de rclone en: {BIN_DIR / rclone_name()}\n"
            f"Este dispositivo no se preparó para esta plataforma. Vuelve a "
            f"ejecutar el instalador de prdrive, elige este dispositivo y pulsa "
            f"«Añadir plataformas…»."
        )
    return ejecutable(binary)


def ejecutable(binary: Path) -> str:
    """Devuelve una ruta desde la que se pueda ejecutar ese rclone.

    En exFAT no hay bit de ejecución: en POSIX se copia al temporal y se le
    pone. Está aparte de `rclone_binary()` para que el agente lo use con el
    rclone de otra raíz.

    Args:
        binary: Ruta del binario de rclone.

    Returns:
        La misma ruta, o la de la copia ejecutable en el directorio temporal.
    """
    if os.name == "nt" or os.access(binary, os.X_OK):
        return str(binary)
    tmp = Path(tempfile.gettempdir()) / "rclone_portable"
    shutil.copy2(binary, tmp)
    tmp.chmod(tmp.stat().st_mode | stat.S_IXUSR | stat.S_IRUSR)
    return str(tmp)


def flags_to_args(flags: Mapping[str, Any]) -> list[str]:
    """Traduce `{nombre: valor}` a argumentos de línea de comandos de rclone.

        clave = true          -> --clave
        clave = false / None  -> (se omite)
        clave = 4 / "texto"   -> --clave 4 / --clave texto
        clave = ["a", "b"]    -> --clave a --clave b

    Vive aquí y no en `sync.py` porque es el último paso de la traducción
    config -> comando y hay dos sitios más que deben traducir igual sin
    arrastrar el motor: la UI, que enseña en qué se convierten, y el
    instalador, que monta órdenes de rclone antes de que exista ningún
    dispositivo.

    Args:
        flags: Flags ya fusionados; los `_` de las claves pasan a `-`.
    """
    args: list[str] = []
    for key, value in flags.items():
        flag = "--" + str(key).replace("_", "-")
        if value is True:
            args.append(flag)
        elif value is False or value is None:
            continue
        elif isinstance(value, (list, tuple)):
            args += [item for v in value for item in (flag, str(v))]
        else:
            args += [flag, str(value)]
    return args


FLAGS_RESERVADOS: Mapping[str, str] = {
    "config": "lo pone sync.py: es el rclone.conf del dispositivo",
    "log-file": "lo pone sync.py: cada pasada escribe en su propio log",
    "dry-run": "es --dry-run de sync.py, para que valga en todas las parejas",
    "workdir": "lo pone sync.py: state/<pareja>/, y cambiarlo mueve el baseline",
    "resync": "es --resync de sync.py, que además pregunta antes",
    "filters-file": "sale de los patrones incluir/excluir de la pareja",
    "filter": "usa los patrones incluir/excluir; mezclarlos rompe el filtrado",
    "filter-from": "usa los patrones incluir/excluir; mezclarlos rompe el filtrado",
    "include": "usa el cuadro «Incluir»",
    "exclude": "usa el cuadro «Excluir»",
    # Los cuatro del versionado salen de la casilla «Guardar versiones», y el
    # sufijo además depende de la pasada (lleva su fecha y su hora): no hay
    # forma de escribirlo aquí que signifique algo.
    "backup-dir": "el versionado de bisync usa --backup-dir1/2, no este",
    "backup-dir1": "sale de la casilla «Guardar versiones»: es <pareja>/.prversions",
    "backup-dir2": "sale de la casilla «Guardar versiones»: es <pareja>/.prversions",
    "suffix": "lo pone sync.py: la marca de tiempo de ESTA pasada",
    "suffix-keep-extension": "lo pone sync.py junto con --suffix",
}
"""Flags que `sync.py` pone por su cuenta, con el motivo de cada uno.

Salen de `build_command()` y `filter_args()`. `problema_flag()` los rechaza al
parsear, no al ejecutar: rclone recibiría el flag dos veces y, en el caso de
`--workdir` o `--filters-file`, eso es apuntar a bisync a un baseline que no es
el suyo.
"""

_MOTIVO_PROGRAMA = "lanza un programa en este equipo, y el config viaja con el dispositivo"

QUITALO = "Quítalo del config."
"""Con lo que acaba el rechazo de un flag: el config se arregla a mano.

Un config rechazado deja la ventana cerrada (`ui.fatal`), así que cada mensaje
dice qué hay que quitar.
"""


def normalizar_flag(nombre: str) -> str:
    """Devuelve el nombre con el que rclone verá el flag.

    En él `_` es `-` y no se distingue entre mayúsculas y minúsculas.
    """
    return str(nombre).strip().replace("_", "-").lower()


def problema_flag(nombre: str) -> str | None:
    """Dice por qué un flag de rclone no puede ir en el config.

    No vale ni lo que pone `sync.py` por su cuenta (`FLAGS_RESERVADOS`) ni un
    flag que hace que rclone ejecute un programa de este equipo: el config
    viaja con el dispositivo y se edita a mano, y esa orden correría en el
    equipo donde se enchufe. Son los que acaban en `-command` o `-ssh`, más
    `metadata-mapper`, `rc` y los `rc-*`. Se citan del código de rclone:
    `--password-command` (fs/config), `--metadata-mapper`
    (fs/config/configflags), `ssh` de backend/sftp, `bearer_token_command` de
    backend/webdav y el servidor `rc` (fs/rc/rcflags). La regla del sufijo
    también deja fuera como flag los `--sftp-*-command` del remote, que siguen
    valiendo en el `rclone.conf`.

    `flags_to_args()` pega la clave tal cual detrás de `--`, así que una clave
    con `=` (`"sftp-ssh=sh -c id" = true`) llegaría a rclone como
    `--sftp-ssh=sh -c id`: se mira lo que hay antes del `=`.

    Args:
        nombre: El flag sin los guiones; vale con `_` o con mayúsculas.

    Returns:
        El motivo, o `None` si el flag vale.
    """
    clave = normalizar_flag(nombre).split("=", 1)[0].strip()
    motivo = FLAGS_RESERVADOS.get(clave)
    if motivo:
        return motivo
    if clave.endswith(("-command", "-ssh")) or clave in ("metadata-mapper", "rc") \
            or clave.startswith("rc-"):
        return _MOTIVO_PROGRAMA
    return None


def problema_extra(args: Iterable[str]) -> str | None:
    """Dice por qué una lista de argumentos de rclone no puede ir en el config.

    Se mira cada argumento que empieza por `--` por su nombre (lo que va entre
    los guiones y el `=`, si lo hay), con las mismas reglas que `problema_flag()`.
    Los cortos de un guion pasan: ninguno lanza un programa. Un valor suelto
    (`8M`, `sh -c id`) tampoco se mira: no es un flag.

    Returns:
        La frase entera, que nombra el primer argumento rechazado y acaba
        diciendo que se quite, o `None` si todos valen.
    """
    for arg in args:
        arg = str(arg)
        if not arg.startswith("--"):
            continue
        nombre = arg[2:].split("=", 1)[0]
        motivo = problema_flag(nombre)
        if motivo:
            return f"'--{nombre}' no se admite: {motivo}. {QUITALO}"
    return None


def problema_valor_flag(valor: Any) -> str | None:
    """Dice por qué el valor de un flag no puede ir en el config.

    `flags_to_args()` emite `--clave valor`, y un flag booleano no consume el
    argumento siguiente: `checksum = "--sftp-ssh=sh -c id"` llegaría a rclone
    como `--checksum --sftp-ssh=sh -c id`. Cada texto del valor (el propio, o
    los de su lista) pasa por `problema_extra()`; lo que no empieza por `--`
    (`8M`, `25`, `newer`, `-1`) no se toca.

    Returns:
        La misma frase que `problema_extra()`, o `None` si el valor vale.
    """
    if isinstance(valor, str):
        return problema_extra((valor,))
    if isinstance(valor, (list, tuple)):
        return problema_extra(v for v in valor if isinstance(v, str))
    return None


NOMBRE_REMOTE = re.compile(r"(?!-)[\w.+@-]+(?: [\w.+@-]+)*")
"""Un nombre de remote de rclone que no es una cadena de conexión.

Es la regla que rclone documenta para el nombre de un remote: letras, números,
`_ . + @ -` y espacios entre palabras; sin `,` `:` `=` ni comillas, sin empezar
por `-` y sin espacios al final. Sin ella, `nas,ssh='sh -c id'` sería un
remote de `sftp` con su propia orden `ssh`, y `:sftp,host=x` uno creado al vuelo.
"""


def problema_remote(nombre: Any, clave: str = "remote") -> str | None:
    """Dice por qué un `remote` no vale como nombre de remote de rclone.

    Se junta con la ruta (`nombre:ruta`) y va tal cual a rclone, que lo lee
    como cadena de conexión si lleva opciones.

    Args:
        nombre: El valor a comprobar.
        clave: Cómo se llama la clave en el mensaje: `remote` en una pareja y
            en `[defaults]`, `catalog_remote` en este último.

    Returns:
        El motivo, que empieza por «'remote' no vale» (o por el nombre de la
        otra clave), o `None` si vale.
    """
    if not isinstance(nombre, str):
        return f"'{clave}' no vale: tiene que ser un texto."
    if not NOMBRE_REMOTE.fullmatch(nombre):
        return (f"'{clave}' no vale ({nombre!r}): es el nombre de un remote del "
                f"rclone.conf, con letras, números, espacios entre palabras y "
                f". _ + @ -, sin empezar por '-' ni llevar ',' ':' '=' o comillas "
                f"(rclone lo leería como opciones de la conexión).")
    return None


def _comprobar_capas(donde: str, tabla: str, flags: Any, extra: Any) -> None:
    """Comprueba los flags y el `extra_flags` de una capa del config.

    Una `flags` que no es una tabla no es de su incumbencia. El `extra_flags`
    se mira tal como lo leerá `_as_tuple()`, que es lo que llega a rclone.

    Args:
        donde: Cómo se llama la capa en el mensaje (`[defaults]` o `[<pareja>]`).
        tabla: Cómo se llama su tabla de flags (`[defaults.flags]` o `[pair.flags]`).
        flags: Su tabla `flags`, tal como sale del TOML.
        extra: Su `extra_flags`, tal como sale del TOML.

    Raises:
        ConfigError: Si algún flag, su valor o algún argumento no vale
            (`problema_flag()`, `problema_valor_flag()`, `problema_extra()`), o
            `extra_flags` no se puede leer como lista de textos.
    """
    if isinstance(flags, Mapping):
        for clave, valor in flags.items():
            motivo = problema_flag(clave)
            if motivo:
                raise ConfigError(
                    f"{donde} {tabla} '{clave}' no se admite: {motivo}. {QUITALO}")
            motivo = problema_valor_flag(valor)
            if motivo:
                raise ConfigError(f"{donde} {tabla} '{clave}': en su valor, {motivo}")
    # Lo que emite `_as_tuple()` y nada menos: una tabla en línea da sus claves.
    try:
        argumentos = _as_tuple(extra)
    except TypeError:
        raise ConfigError(f"{donde} extra_flags tiene que ser una lista de textos.") from None
    motivo = problema_extra(argumentos)
    if motivo:
        raise ConfigError(f"{donde} extra_flags: {motivo}")


def _comprobar_remote(donde: str, valor: Any, clave: str) -> None:
    """Lanza `ConfigError` si `valor` no vale como nombre de remote (`problema_remote()`)."""
    motivo = problema_remote(valor, clave)
    if motivo:
        raise ConfigError(
            f"{donde} {motivo} Deja solo el nombre del remote o quita la clave del config.")


def comprobar_seguridad(crudo: Mapping[str, Any], equipo: bool = False, *,
                        carpeta_programa: str | None = None) -> None:
    """Rechaza del config en bruto lo que no puede llegar a la línea de órdenes de rclone.

    Es el único sitio de estas comprobaciones, y mira el TOML tal como sale de
    `tomllib`: `parse_config()` la llama la primera, y quien lee el config a
    pelo (el agente, `agente.leer_servicio()`, porque la raíz puede ser de otra
    versión, y el `sync.py` de una de antes no comprueba nada) la llama
    también. Por eso tolera cualquier forma (tablas que no lo son, nombres que
    no son texto, ninguna `[[pair]]`) y no decide nada más: un modo o una clave
    desconocidos no son asunto suyo.

    Comprueba, en `[defaults]`, el `remote` y el `catalog_remote` en cuanto
    están, aunque vacíos (acaban como `remote:ruta` para el llavero y el
    catálogo, ver `carpeta_del_catalogo()`, y un `remote` vacío dejaría a la
    pareja en `:ruta`, donde un `remote_path` hecho a propósito sería una
    cadena de conexión), los flags y el `extra_flags`; y en cada pareja con
    nombre, su `remote`, sus flags, su `extra_flags` y su `local` si es un
    texto (`problema_local()`: uno que falta lo dice `_build_pair()`).

    Args:
        crudo: El config tal como salió del TOML.
        equipo: Si la raíz es de equipo (`es_equipo()`), donde además cada
            `local` tiene que ser una carpeta de dentro (`problema_local_equipo()`).
        carpeta_programa: El nombre de la carpeta del programa de la raíz que
            se lee, para `problema_local()`; por defecto, la del programa que
            corre.

    Raises:
        ConfigError: Con la capa (`[defaults]` o `[<pareja>]`), la clave o el
            argumento y qué hacer con él.
    """
    if not isinstance(crudo, Mapping):
        return
    defaults = crudo.get("defaults")
    if isinstance(defaults, Mapping):
        for clave in ("remote", "catalog_remote"):
            if clave in defaults:
                _comprobar_remote("[defaults]", defaults[clave], clave)
        _comprobar_capas("[defaults]", "[defaults.flags]", defaults.get("flags"),
                         defaults.get("extra_flags"))
    parejas = crudo.get("pair")
    if not isinstance(parejas, (list, tuple)):
        return
    for pareja in parejas:
        if not isinstance(pareja, Mapping) or not isinstance(pareja.get("name"), str):
            continue
        donde = f"[{pareja['name']}]"
        if "remote" in pareja:
            _comprobar_remote(donde, pareja["remote"], "remote")
        _comprobar_capas(donde, "[pair.flags]", pareja.get("flags"),
                         pareja.get("extra_flags"))
        local = pareja.get("local")
        if isinstance(local, str):
            motivo = problema_local(local, equipo, carpeta_programa=carpeta_programa)
            if motivo:
                raise ConfigError(f"{donde} {motivo}")


BASE_FLAGS: Mapping[str, Any] = {
    "verbose": True,
    "create-empty-src-dirs": True,
    "stats": "2s",
    "stats-one-line": True,
}
"""Flags que lleva toda ejecución, sea cual sea el modo.

`stats` y `stats-one-line` hacen que rclone escriba una línea de progreso cada
pocos segundos (la de fábrica es un bloque por minuto); de ahí saca `sync.py`
el progreso en vivo (`common/progress.py`). Van en esta capa y no en el código
para que una pareja pueda cambiarlos como cualquier otro flag; sin ellos no hay
progreso, pero la pasada va igual.
"""


@dataclass(frozen=True)
class Mode:
    """Qué subcomando de rclone es cada modo, en qué sentido va y con qué flags.

    Args:
        name: Nombre del modo en el TOML (`bisync`, `up`, `down`, `up-mirror`,
            `down-mirror`).
        verb: Subcomando de rclone (`bisync`, `copy` o `sync`).
        source: Extremo de origen (`local` o `remote`): un nombre, no una ruta.
            Quién es origen y quién destino es justo lo que distingue `up` de
            `down`.
        dest: Extremo de destino, con el mismo criterio.
        flags: Flags propios del modo.
    """
    name: str
    verb: str
    source: str
    dest: str
    flags: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_bisync(self) -> bool:
        """Indica si el modo usa `rclone bisync`."""
        return self.verb == "bisync"

    @property
    def origen_local(self) -> bool:
        """Indica si el lado local es origen: lo que cambia allí hay que subirlo.

        Es la condición de `watch`: en `down` y `down-mirror` un cambio local
        no es algo que la pasada vaya a enviar.
        """
        return self.source == "local"


MODES: Mapping[str, Mode] = {m.name: m for m in (
    Mode("bisync", "bisync", "local", "remote", {
        "conflict-resolve": "newer",
        "conflict-suffix": "conflicto-dispositivo,conflicto-remoto",
        "max-delete": 25,
        "resilient": True,
        "recover": True,
        "max-lock": "2m",
    }),
    Mode("up", "copy", "local", "remote"),
    Mode("down", "copy", "remote", "local"),
    Mode("up-mirror", "sync", "local", "remote", {"max-delete": 50}),
    Mode("down-mirror", "sync", "remote", "local", {"max-delete": 50}),
)}
"""Los modos disponibles, por nombre.

Flags propios de `bisync`:
- `resilient`: los errores «menores» no obligan a `--resync` en la pasada
  siguiente.
- `recover`: una interrupción brusca se recupera sola en la pasada siguiente.
- `max-lock`: caduca el `.lck` que deja un proceso muerto (mínimo 2m).
- `max-delete`: una ruta local vacía o desmontada no debe arrasar el otro lado.
  El 25 NO es una cuenta de ficheros sino un porcentaje:
  `Options.applyContext()` (cmd/bisync/cmd.go) lee el `--max-delete` global, lo
  acota a 0..100 y pone `ci.MaxDelete = -1` («reset MaxDelete for
  fs/operations, bisync handles this parameter specially»), y `excessDeletes()`
  (cmd/bisync/deltas.go) compara deleted / oldCount contra ese porcentaje del
  listado ANTERIOR. El 50 de `up-mirror` y `down-mirror` sí es una cuenta: el
  `--max-delete` corriente de `sync`. No iguales los dos números.
- `conflict-suffix`: un sufijo POR LADO. Con el de fábrica y `--conflict-loser
  num`, rclone llama al perdedor `.conflictN` con el primer número libre
  (cmd/bisync/resolve.go: `resolve`, `numerate`), que es un orden y no un lado.
  Con dos sufijos el nombre dice el lado y sigue numerado, así que un segundo
  conflicto sobre el mismo fichero no pisa la copia del primero (con
  `--conflict-loser pathname` sí). Lo lee `common/conflicts.py`.
"""


def _as_tuple(value: Any) -> tuple[str, ...]:
    """Normaliza un valor del TOML (nada, un string o una lista) a tupla de strings."""
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


@dataclass(frozen=True)
class Pair:
    """Una `[[pair]]` del TOML con todas sus capas ya fusionadas.

    `flags` y los patrones de filtrado llegan resueltos: nadie aguas abajo
    necesita saber que existían unos `[defaults]`.

    Args:
        name: Nombre de la pareja.
        mode: Su modo.
        local: Ruta relativa al dispositivo, con `/` y sin barras sueltas.
        remote_path: Ruta dentro del remote.
        remote_name: Nombre del remote de rclone.
        includes: Patrones `include`.
        excludes: Patrones `exclude`.
        flags: Flags de rclone ya fusionados (`BASE_FLAGS` < modo <
            `[defaults.flags]` < `[pair.flags]`).
        extra_flags: Argumentos en bruto añadidos al final del comando.
        use_filters_file: Si los patrones van en un fichero de filtros (solo
            bisync).
        device_remote: Nombre del remote `combine` del lado local, o `None` si
            el local es una ruta.
        versions: Si la pareja guarda versiones de lo que pierde cada lado.
        watch: Si el agente residente la sincroniza poco después de que cambien
            sus ficheros locales, sin esperar al intervalo (solo en los modos
            donde el local es origen).
        reglas: Reglas de filtrado (`+ patrón` o `- patrón`) que van antes que
            `includes` y `excludes`, en su orden. Las pone el código, no el
            TOML: las del llavero, y en una pareja de la raíz entera
            `REGLA_SIN_PROGRAMA` y, con `[keychain]`, `REGLA_SIN_LLAVERO`.
        llavero: Si es la pareja del llavero, la que construye el código.
        llave_interna: Si el llavero va sin contraseña, solo con su fichero llave
            (`[keychain] llave_interna`): solo se sincroniza en un dispositivo
            cifrado (`common/cifrada.py`).
    """
    name: str
    mode: Mode
    local: str
    remote_path: str
    remote_name: str
    includes: tuple[str, ...]
    excludes: tuple[str, ...]
    flags: Mapping[str, Any]
    extra_flags: tuple[str, ...]
    use_filters_file: bool
    device_remote: str | None
    versions: bool
    watch: bool = False
    reglas: tuple[str, ...] = ()
    llavero: bool = False
    llave_interna: bool = False

    @property
    def es_raiz(self) -> bool:
        """Indica si la pareja sincroniza la raíz entera del dispositivo (`local = "."`)."""
        return not self.tramos_locales

    @property
    def local_abs(self) -> Path:
        """Devuelve la carpeta local de la pareja, resuelta bajo la raíz."""
        return (DEVICE_ROOT / self.local).resolve()

    @property
    def local_endpoint(self) -> str:
        """Devuelve el extremo local tal como se le pasa a rclone.

        Con `device_remote` el lado local es un remote propio y su nombre ya no
        depende de dónde esté montado el dispositivo.
        """
        if self.device_remote:
            return f"{self.device_remote}:{self.ruta_en_combine}"
        return str(self.local_abs)

    @property
    def remote_endpoint(self) -> str:
        """Devuelve el extremo remoto (`remote:ruta`)."""
        return f"{self.remote_name}:{self.remote_path}"

    def endpoint(self, kind: str) -> str:
        """Devuelve el extremo `local` o `remote` tal como se le pasa a rclone."""
        return self.local_endpoint if kind == "local" else self.remote_endpoint

    @property
    def source(self) -> str:
        """Devuelve el extremo de origen según el modo de la pareja."""
        return self.endpoint(self.mode.source)

    @property
    def dest(self) -> str:
        """Devuelve el extremo de destino según el modo de la pareja."""
        return self.endpoint(self.mode.dest)

    @property
    def is_bisync(self) -> bool:
        """Indica si la pareja usa `rclone bisync`."""
        return self.mode.is_bisync

    @property
    def workdir(self) -> Path:
        """Devuelve el workdir de bisync: uno por pareja.

        Así sus listados no se mezclan.
        """
        return STATE_DIR / self.name

    @property
    def tramos_locales(self) -> tuple[str, ...]:
        """Devuelve la ruta local partida, sin los tramos vacíos ni `.`."""
        partida = self.local.replace("\\", "/").split("/")
        return tuple(t for t in partida if t not in ("", "."))

    @property
    def top_level_dir(self) -> str:
        """Devuelve el primer tramo de la ruta local: el upstream de `combine`.

        Una pareja que sincroniza la RAÍZ del dispositivo (`local = "."`) no
        tiene primer tramo y no vale dejarlo en `.`: rclone limpia la ruta
        antes de buscar el upstream, así que `disp:.` pasa a ser el upstream ""
        y falla con «combine for remote "": directory not found». Por eso la
        raíz se declara con un nombre de verdad (`RAIZ_UPSTREAM`).
        """
        tramos = self.tramos_locales
        return tramos[0] if tramos else RAIZ_UPSTREAM

    @property
    def top_level_abs(self) -> Path:
        """Devuelve la carpeta a la que apunta `top_level_dir`."""
        tramos = self.tramos_locales
        return (DEVICE_ROOT / tramos[0]).resolve() if tramos else DEVICE_ROOT.resolve()

    @property
    def ruta_en_combine(self) -> str:
        """Devuelve la ruta de la pareja vista desde dentro del remote `combine`.

        Para todas menos la raíz es la ruta local tal cual.
        """
        return "/".join((self.top_level_dir,) + self.tramos_locales[1:])

    @property
    def wants_filters_file(self) -> bool:
        """Indica si la pareja usa `--filters-file` (exclusivo de bisync).

        En el resto de modos van `--include` y `--exclude`.
        """
        return self.is_bisync and self.use_filters_file

    @property
    def versions_path1(self) -> str:
        """Devuelve el `--backup-dir1`: lo que pierde el lado local.

        Los dos extremos son los de la pareja con la carpeta detrás; no hay una
        tercera ruta que configurar. Path1 es `source` y Path2 es `dest`, que
        es como `build_command` se los pasa a rclone (en bisync `source` es el
        lado local). Se construyen con `/` también en Windows: rclone admite la
        barra en una ruta local y así no hay dos ramas.
        """
        return f"{self.source.rstrip('/')}/{VERSIONS_DIR}"

    @property
    def versions_path2(self) -> str:
        """Devuelve el `--backup-dir2`: lo que pierde el lado remoto."""
        return f"{self.dest.rstrip('/')}/{VERSIONS_DIR}"


def _build_pair(raw: Mapping[str, Any], defaults: Mapping[str, Any]) -> Pair:
    """Construye una `Pair` fundiendo las capas de configuración.

    Los flags van de menos a más prioridad: `BASE_FLAGS` < modo <
    `[defaults.flags]` < `[pair.flags]`.

    Args:
        raw: La `[[pair]]` tal como sale del TOML.
        defaults: La tabla `[defaults]`.

    Raises:
        ConfigError: Si falta una clave obligatoria, el nombre o el modo no
            valen, `versions` se pide en un modo que no es bisync, o el
            `remote` que acaba usando no es un nombre de remote. Los flags, el
            `extra_flags` y el `local` ya los ha comprobado
            `comprobar_seguridad()`.
    """
    name = raw.get("name")
    if not name:
        raise ConfigError("Hay una [[pair]] sin 'name' en el config.")
    problema = problema_nombre(name)
    if problema:
        raise ConfigError(f"[{name}] {problema}")
    for required in ("local", "remote_path"):
        if required not in raw:
            raise ConfigError(f"[{name}] falta '{required}' en el config.")

    mode_name = raw.get("mode", DEFAULT_MODE)
    mode = MODES.get(mode_name)
    if mode is None:
        raise ConfigError(f"[{name}] modo inválido: '{mode_name}'. Válidos: {sorted(MODES)}")

    # El versionado se apoya en `--backup-dir1/2` y en apartar al perdedor de
    # un conflicto, que son cosas de bisync. En copy/sync no hay dos lados que
    # guardar: vale más decirlo al parsear que dejar la clave sin efecto.
    versions = bool(raw.get("versions", False))
    if versions and not mode.is_bisync:
        raise ConfigError(
            f"[{name}] 'versions' solo vale en modo bisync, y esta pareja es "
            f"'{mode_name}'. Quita la clave o cambia el modo.")

    watch = _leer_watch(name, raw, mode)

    # El que sale de la cadena de fallbacks, el que va a rclone: ninguna rama
    # se salta la comprobación aunque `comprobar_seguridad()` no la haya visto.
    remote = raw.get("remote", defaults.get("remote", DEFAULT_REMOTE))
    _comprobar_remote(f"[{name}]", remote, "remote")

    return Pair(
        name=name,
        mode=mode,
        local=normalizar_local(raw["local"]),
        remote_path=raw["remote_path"],
        remote_name=remote,
        includes=_as_tuple(defaults.get("include")) + _as_tuple(raw.get("include")),
        excludes=_as_tuple(defaults.get("exclude")) + _as_tuple(raw.get("exclude")),
        flags={**BASE_FLAGS, **mode.flags,
               **defaults.get("flags", {}), **raw.get("flags", {})},
        extra_flags=_as_tuple(defaults.get("extra_flags")) + _as_tuple(raw.get("extra_flags")),
        use_filters_file=raw.get("use_filters_file",
                                 defaults.get("use_filters_file", True)),
        device_remote=_device_remote_name(defaults),
        versions=versions,
        watch=watch,
    )


def carpeta_del_catalogo(defaults: Mapping[str, Any]) -> tuple[str, str]:
    """Devuelve el remote y la carpeta del catálogo de un dispositivo.

    Es la misma cuenta que `catalog.endpoint()`: `catalog_remote` o el
    `remote` de las parejas, y la carpeta de `catalog_path`.

    Returns:
        `(remote, carpeta)`, con la carpeta acabada en `/` salvo que sea la
        raíz del remote, que es `""`.
    """
    remote = defaults.get("catalog_remote") or defaults.get("remote") or DEFAULT_REMOTE
    ruta = str(defaults.get("catalog_path") or DEFAULT_CATALOG_PATH)
    return str(remote), ruta[:ruta.rfind("/") + 1]


def _build_llavero(tabla: Any, defaults: Mapping[str, Any]) -> Pair:
    """Construye la pareja del llavero a partir de `[keychain]` y los `[defaults]`.

    El TOML no la puede cambiar: es bisync con versiones, en `.keychain/` y en
    la subcarpeta `keychain/` de la carpeta del catálogo, con sus filtros y sus
    flags (`LLAVERO_REGLAS`, `LLAVERO_FLAGS`). Ni los flags ni los filtros de
    `[defaults]` le llegan: un `conflict-resolve` común, por ejemplo, cambiaría
    qué base gana. Del dispositivo solo toma el remote del catálogo y su
    `device_remote`.

    Raises:
        ConfigError: Si `[keychain]` no es una tabla o no dice qué base es, o si
            `llave_interna` no es un booleano o falta `fichero_llave`.
    """
    if not isinstance(tabla, Mapping):
        raise ConfigError("[keychain] tiene que ser una tabla.")
    base = tabla.get("base")
    if not isinstance(base, str) or not base.endswith(".kdbx") or base == ".kdbx" \
            or any(c in base for c in "/\\:") or base.startswith("."):
        # `.kdbx` en minúsculas: los filtros de rclone distinguen, y `+ *.kdbx`
        # no dejaría pasar una `.KDBX`.
        raise ConfigError("[keychain] tiene que decir qué base lleva, con «base = "
                          "\"<nombre>.kdbx\"», un nombre suelto que acabe en .kdbx "
                          "(en minúsculas).")
    interna = tabla.get("llave_interna", False)
    if not isinstance(interna, bool):
        raise ConfigError("[keychain] llave_interna tiene que ser true o false.")
    if interna and not tabla.get("fichero_llave"):
        raise ConfigError("[keychain] llave_interna = true necesita fichero_llave = true: "
                          "la base se abre solo con su fichero llave.")
    remote, carpeta = carpeta_del_catalogo(defaults)
    mode = MODES["bisync"]
    return Pair(
        name=LLAVERO, mode=mode, local=LLAVERO_LOCAL,
        remote_path=carpeta + LLAVERO_REMOTO, remote_name=remote,
        includes=(), excludes=(),
        flags={**BASE_FLAGS, **mode.flags, **LLAVERO_FLAGS},
        extra_flags=(), use_filters_file=True,
        device_remote=_device_remote_name(defaults), versions=True,
        reglas=LLAVERO_REGLAS, llavero=True, llave_interna=interna)


def _leer_watch(name: str, raw: Mapping[str, Any], mode: Mode) -> bool:
    """Lee y valida la clave `watch` de una pareja.

    Args:
        name: Nombre de la pareja, para el mensaje.
        raw: La `[[pair]]` tal como sale del TOML.
        mode: Su modo ya resuelto.

    Returns:
        Si la pareja pide vigilar sus cambios locales.

    Raises:
        ConfigError: Si no es un booleano, o se pide (`true`) en un modo donde
            el local no es origen. `watch = false` vale en cualquiera.
    """
    valor = raw.get("watch", False)
    if not isinstance(valor, bool):
        raise ConfigError(
            f"[{name}] 'watch' tiene que ser true o false, no {valor!r}.")
    if valor and not mode.origen_local:
        validos = ", ".join(m.name for m in MODES.values() if m.origen_local)
        raise ConfigError(
            f"[{name}] 'watch' solo vale donde el origen es el dispositivo "
            f"({validos}), y esta pareja es '{mode.name}'. Quita la clave o "
            "cambia el modo.")
    return valor


def pide_watch(raw: Mapping[str, Any]) -> bool:
    """Dice si una `[[pair]]` en bruto pide vigilar sus cambios locales.

    Es la misma regla que `_leer_watch()` pero sin lanzar: quien lee el TOML a
    pelo (el agente, que no pasa por `parse_config()` porque la unidad puede
    ser de otra versión) solo quiere un sí o un no. Cuenta únicamente el `true`
    literal y solo en un modo conocido donde el local es origen; cualquier otra
    cosa (un string, un número, una clave en un modo que no la admite) es no.

    Args:
        raw: La `[[pair]]` tal como sale del TOML.
    """
    if raw.get("watch") is not True:
        return False
    nombre = raw.get("mode", DEFAULT_MODE)
    mode = MODES.get(nombre) if isinstance(nombre, str) else None
    return mode is not None and mode.origen_local


def es_ruido_del_sistema(nombre: str) -> bool:
    """Indica si ese nombre es de lo que el sistema deja en la raíz de un volumen.

    Args:
        nombre: El nombre de una entrada, sin ruta y con cualquier mayúscula.

    Returns:
        Si casa con algún patrón de `RUIDO_DEL_SISTEMA`.
    """
    minusculas = nombre.lower()
    return any(fnmatch.fnmatchcase(minusculas, patron) for patron in RUIDO_DEL_SISTEMA)


def normalizar_local(local: Any) -> str:
    """Devuelve el `local` de una pareja como lo entiende el motor.

    Las barras invertidas pasan a `/` y se quitan las de los extremos: es lo
    que hace `_build_pair()` y lo que tiene que hacer quien lea el TOML a pelo
    (el agente, al decidir qué carpeta vigilar). `.` queda como `.`.

    Args:
        local: El valor de `local` tal como está en el TOML.
    """
    return str(local).replace("\\", "/").strip("/")


def problema_nombre(name: Any) -> str | None:
    """Dice por qué un nombre de pareja no vale.

    El nombre acaba en la línea de órdenes de `sync.py` (un `--resync` como
    nombre se leería como la opción y arrastraría a todas las parejas), en
    `state/<pareja>/` y en `filters/<pareja>.txt` (con `/` o `..` saldría de
    esas carpetas). La ventana no deja escribirlos, pero el TOML se edita a
    mano y llega de otras versiones: la regla es del parser.

    Returns:
        El motivo, o `None` si el nombre vale.
    """
    if not isinstance(name, str):
        return "el nombre tiene que ser un texto"
    if name.startswith("-"):
        return "el nombre no puede empezar por '-' (se leería como una opción)"
    if name in (".", "..") or any(c in name for c in "/\\:") \
            or any(ord(c) < 32 for c in name):
        return ("el nombre no puede llevar '/', '\\', ':' ni caracteres de control, "
                "ni ser '.' o '..' (es el nombre de su carpeta en state/ y filters/)")
    return None


def problema_local_equipo(local: str) -> str | None:
    """Dice por qué un `local` no vale en una raíz del equipo.

    Tiene que ser una carpeta DENTRO de la raíz: la raíz entera sincronizaría
    el propio `.prdrive/` con la clave dentro (y todo `~` si la raíz es la
    carpeta personal), y un `..` o una ruta absoluta saldrían de la raíz a
    cualquier sitio del ordenador. Es una función aparte para que el asistente
    lo diga al teclearlo con las mismas palabras que al parsear.

    Returns:
        El motivo, o `None` si el `local` vale.
    """
    texto = str(local)
    tramos = [t for t in texto.replace("\\", "/").split("/") if t not in ("", ".")]
    if not tramos:
        return (f"local = \"{texto}\" es la raíz entera, y en una raíz del equipo "
                f"eso no se puede sincronizar: arrastraría la carpeta del programa "
                f"(con la clave) y, con la carpeta personal, todo el usuario. Pon "
                f"una carpeta de dentro.")
    if ".." in tramos or Path(texto).is_absolute() or re.match(r"^[A-Za-z]:", texto) \
            or texto.startswith(("/", "\\")):
        return (f"local = \"{texto}\" sale de la raíz del equipo. Las parejas van en "
                f"carpetas de dentro, con la ruta relativa a ella.")
    return None


def problema_local(local: Any, equipo: bool = False, *,
                   carpeta_programa: str | None = None) -> str | None:
    """Dice por qué el `local` de una pareja no vale.

    El `local` es una carpeta de DENTRO del dispositivo, relativa a su raíz. Con
    un `..` o una letra de unidad (`C:`) la pareja sincronizaría, y en un espejo
    borraría, carpetas del ordenador; la del programa lleva la clave, y la del
    llavero tiene su propia pareja (`[keychain]`). Se mira el texto del config
    tal cual (`\\` cuenta como `/`): una barra al principio se tolera porque
    `normalizar_local()` la quita y hay dispositivos en uso que la llevan.

    Args:
        local: El valor de `local` tal como está en el TOML.
        equipo: Si la raíz es de equipo; entonces se aplica antes
            `problema_local_equipo()`, con sus mismas palabras.
        carpeta_programa: El nombre de la carpeta del programa de la raíz a la
            que pertenece el `local`. Por defecto es el de la que corre
            (`APP_DIR.name`), que es la de la raíz cuando el config se lee desde
            su propio programa; quien lee el de otra raíz (el agente, que corre
            en su carpeta y no en la `.prdrive` de la unidad) tiene que decirlo.

    Returns:
        El motivo, que empieza por `local = "<valor>"`, o `None` si vale.
    """
    texto = str(local)
    if equipo:
        motivo = problema_local_equipo(texto)
        if motivo:
            return motivo
    tramos = [t for t in texto.replace("\\", "/").split("/") if t not in ("", ".")]
    if ".." in tramos or (tramos and re.match(r"[A-Za-z]:", tramos[0])):
        return (f"local = \"{texto}\" sale del dispositivo (lleva un '..' o una letra "
                f"de unidad): la pareja sincronizaría carpetas del ordenador. Pon una "
                f"carpeta de dentro del dispositivo, con la ruta relativa a su raíz.")
    primero = tramos[0].lower() if tramos else ""
    if primero == (carpeta_programa or APP_DIR.name).lower():
        return (f"local = \"{texto}\" cae en «{tramos[0]}»: es la carpeta del "
                f"programa, con su clave. Pon otra carpeta de dentro del dispositivo.")
    if primero == LLAVERO_LOCAL.lower():
        return (f"local = \"{texto}\" cae en «{tramos[0]}»: es la del llavero, que "
                f"tiene su propia pareja ([keychain]). Pon otra carpeta de dentro del "
                f"dispositivo.")
    return None


def _device_remote_name(defaults: Mapping[str, Any]) -> str | None:
    """Devuelve el nombre del remote `combine` del dispositivo, validado.

    El nombre viaja en variables de entorno `RCLONE_CONFIG_<NOMBRE>_*`, que no
    admiten cualquier cosa.

    Returns:
        El nombre, o `None` si `[defaults]` no define `device_remote`.

    Raises:
        ConfigError: Si el nombre no es alfanumérico sin guiones.
    """
    name = defaults.get("device_remote")
    if not name:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise ConfigError(
            f"'device_remote' debe ser alfanumérico sin guiones (va en una "
            f"variable de entorno RCLONE_CONFIG_<NOMBRE>_*): '{name}'")
    return name


def _upstream(nombre: str, ruta: Path) -> str:
    r"""Devuelve un tramo del `upstreams` del remote `combine`, tal como rclone lo lee.

    rclone parsea `upstreams` como `fs.SpaceSepList` (fs/types.go): un CSV con
    el espacio de separador, donde un campo solo va entrecomillado si empieza
    por comilla y una comilla dentro de un campo sin entrecomillar es un error
    de sintaxis. Por eso las comillas envuelven el PAR ENTERO `nombre=ruta` y
    no la ruta: `.="F:\"` lo rechaza con «bare " in non-quoted-field» y tumba
    TODAS las parejas del dispositivo. Entre comillas caben la barra final de
    la raíz de una unidad (`F:\`) y los espacios de la ruta, que es para lo que
    hacen falta. Una comilla dentro de la ruta se dobla, como manda el CSV.
    """
    texto = str(ruta).replace('"', '""')
    return f'"{nombre}={texto}"'


@dataclass(frozen=True)
class Config:
    """La configuración completa del dispositivo, resuelta.

    Args:
        pairs: Las parejas, en el orden del TOML.
        daemon: La tabla `[daemon]` en bruto.
        keep_logs: Si se guardan también los logs de las pasadas buenas.
        device_remote: Nombre del remote `combine` del lado local, o `None`.
        llavero: La tabla `[keychain]` en bruto, o `None` sin llavero. La
            pareja que sale de ella va la última de `pairs`.
    """
    pairs: tuple[Pair, ...]
    daemon: Mapping[str, Any]
    keep_logs: bool
    device_remote: str | None
    llavero: Mapping[str, Any] | None = None

    @property
    def names(self) -> list[str]:
        """Devuelve los nombres de las parejas del TOML, en su orden.

        Sin la del llavero: son las que se eligen en la ventana, en el menú y
        en el servicio. `pairs` sí la lleva, y por eso `sync.py` sin nombres la
        corre con las demás.
        """
        return [p.name for p in self.del_usuario]

    @property
    def del_usuario(self) -> tuple[Pair, ...]:
        """Devuelve las parejas del TOML, sin la del llavero.

        Son las que se enseñan como parejas: la del llavero tiene su propia
        línea en la ventana y no se elige ni se edita.
        """
        return tuple(p for p in self.pairs if not p.llavero)

    @property
    def pareja_llavero(self) -> Pair | None:
        """Devuelve la pareja del llavero, o `None` si el dispositivo no lo lleva."""
        return next((p for p in self.pairs if p.llavero), None)

    def select(self, wanted: Iterable[str]) -> list[Pair]:
        """Devuelve las parejas pedidas, en el orden del TOML.

        Aborta si alguna no existe: un nombre mal escrito no puede acabar en
        «pues no sincronizo eso».

        Raises:
            ConfigError: Si alguna pareja pedida no existe.
        """
        wanted = set(wanted)
        chosen = [p for p in self.pairs if p.name in wanted]
        missing = wanted - {p.name for p in chosen}
        if missing:
            raise ConfigError(
                f"No existen estas parejas en el config: {', '.join(sorted(missing))}")
        return chosen

    def pen_environment(self) -> dict[str, str]:
        """Devuelve las variables que definen el remote `combine` del dispositivo.

        Un remote `alias` NO sirve: `backend/alias/alias.go` devuelve el Fs de
        destino tal cual, así que con destino local `f.Name()` vuelve a ser
        "local" y la ruta absoluta reaparece en el nombre de los listados. Un
        `combine` sí es un Fs propio y el lado local pasa a llamarse
        `dispositivo:sync-data/x` en cualquier máquina.

        Se calcula con TODAS las parejas, no solo las seleccionadas, para que
        el remote sea idéntico ejecutes lo que ejecutes.

        Returns:
            Las variables, o un diccionario vacío si no hay `device_remote`.

        Raises:
            ConfigError: Si dos parejas piden el mismo upstream para carpetas
                distintas.
        """
        if not self.device_remote:
            return {}
        tops: dict[str, Path] = {}
        for pareja in self.pairs:
            nombre, ruta = pareja.top_level_dir, pareja.top_level_abs
            # El mismo nombre para carpetas distintas solo ocurre con la raíz
            # (`local = "."` es `RAIZ_UPSTREAM`) y otra pareja con una carpeta
            # que se llama igual: sería un upstream apuntando a donde no es, en
            # silencio.
            if tops.setdefault(nombre, ruta) != ruta:
                raise ConfigError(
                    f"Dos parejas declaran el upstream '{nombre}' apuntando a "
                    f"carpetas distintas ({tops[nombre]} y {ruta}). Renombra la "
                    f"carpeta '{nombre}' de la raíz del dispositivo.")
        upstreams = " ".join(_upstream(n, tops[n]) for n in sorted(tops))
        return {
            f"RCLONE_CONFIG_{self.device_remote.upper()}_TYPE": "combine",
            f"RCLONE_CONFIG_{self.device_remote.upper()}_UPSTREAMS": upstreams,
        }


def parse_config(data: Mapping[str, Any], equipo: bool = False) -> Config:
    """Resuelve el config en bruto a un `Config`.

    Args:
        data: El TOML ya leído.
        equipo: Si es el de una raíz del equipo (`es_equipo()`), donde cada
            `local` tiene que ser una carpeta de dentro. No se deduce aquí
            porque el catálogo pasa por esta misma función y en él una pareja
            de la raíz entera es legítima para las unidades.

    Cada pareja que sincroniza la raíz entera recibe `REGLA_SIN_PROGRAMA`
    delante de sus filtros. Con `[keychain]`, la pareja del llavero va la última
    (`_build_llavero()`), su nombre queda reservado y esas parejas reciben
    además `REGLA_SIN_LLAVERO`, detrás de la del programa.

    Raises:
        ConfigError: Si el config trae algo que no puede llegar a rclone
            (`comprobar_seguridad()`), no hay ninguna `[[pair]]`, alguna no es
            válida, `[defaults]` lleva `watch`, que es de cada pareja, o
            `[keychain]` no vale o choca con una pareja que se llama como la
            suya.
    """
    comprobar_seguridad(data, equipo)
    defaults = data.get("defaults", {})
    raw_pairs = data.get("pair", [])
    if not raw_pairs:
        raise ConfigError("El config no tiene ninguna [[pair]] definida.")
    if isinstance(defaults, Mapping) and "watch" in defaults:
        # Solo se lee de `[[pair]]` (`_leer_watch()`): en `[defaults]` no haría
        # nada y parecería que vigila todas las parejas.
        raise ConfigError(
            "[defaults] no admite 'watch': vigilar los cambios locales se pide "
            "pareja a pareja, con 'watch = true' en cada [[pair]] que lo quiera.")
    pairs = tuple(_build_pair(p, defaults) for p in raw_pairs)
    tabla = data.get("keychain")
    if tabla is not None and any(p.name == LLAVERO for p in pairs):
        raise ConfigError(
            f"Hay una pareja que se llama '{LLAVERO}', que es el nombre de la "
            f"del llavero. Renómbrala o quita [keychain].")
    reglas_raiz = (REGLA_SIN_PROGRAMA,) + ((REGLA_SIN_LLAVERO,) if tabla is not None else ())
    pairs = tuple(replace(p, reglas=reglas_raiz + p.reglas) if p.es_raiz else p
                  for p in pairs)
    if tabla is not None:
        pairs += (_build_llavero(tabla, defaults),)
    return Config(
        pairs=pairs,
        daemon=data.get("daemon", {}),
        keep_logs=bool(defaults.get("keep_logs", False)),
        device_remote=_device_remote_name(defaults),
        llavero=dict(tabla) if isinstance(tabla, Mapping) else None,
    )


def load_config() -> Config:
    """Lee y resuelve el `sync_config.toml` de este dispositivo.

    Raises:
        ConfigError: Si el fichero no existe o su contenido no es válido.
    """
    if not CONFIG_FILE.exists():
        raise ConfigError(f"No existe el fichero de configuración: {CONFIG_FILE}")
    with CONFIG_FILE.open("rb") as f:
        return parse_config(tomllib.load(f), equipo=es_equipo())
