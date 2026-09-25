#!/usr/bin/env python3
"""
model.py — El modelo de datos de sync_config.toml.

El TOML se lee UNA vez y se convierte en objetos ya resueltos: `Config` con sus
`Pair`, y cada pareja con su `Mode`. A partir de ahí nadie vuelve a preguntar por
claves del TOML ni repite `.get(clave, por_defecto)`, y `defaults` deja de viajar
por todas las firmas: la jerarquía de configuración se conoce y se resuelve aquí,
que es el único sitio que la entiende.

Añadir un flag de rclone sigue siendo cosa del TOML, no de este fichero.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

# tomllib es stdlib desde Python 3.11. Fallback a 'tomli' en versiones viejas.
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore
    except ModuleNotFoundError:
        sys.exit("Necesitas Python 3.11+ (tomllib) o instalar tomli: pip install tomli")


# --- Rutas, todas deducidas de la ubicación de este fichero -------------------
#
# Este módulo vive en <carpeta de la app>/common/, así que la carpeta de la
# aplicación —la que contiene sync_config.toml, rclone.conf, bin/, keys/, y contra
# la que rclone resuelve las rutas relativas de su config— es el directorio padre,
# y el dispositivo el siguiente. En un dispositivo provisionado la carpeta se
# llama `.prdrive`; en un checkout, como se llame. Nada de esto depende de la
# letra de unidad ni del nombre, porque todo sale de `__file__`.
APP_DIR = Path(__file__).resolve().parent.parent
DEVICE_ROOT = APP_DIR.parent  # las rutas 'local' del config son relativas a aquí
CONFIG_FILE = APP_DIR / "sync_config.toml"
RCLONE_CONF = APP_DIR / "rclone.conf"
STATE_DIR = APP_DIR / "state"
FILTERS_DIR = APP_DIR / "filters"
LOG_DIR = APP_DIR / "logs"

SYNC_PY = APP_DIR / "sync.py"       # a quien lanzan la UI y el servicio
PENWATCH_PY = APP_DIR / "penwatch.py"


# Los dos registros que dicen quién está usando el dispositivo ahora mismo: el
# servicio periódico y la ventana. Los escribe `runsync.py`, y los lee también
# quien necesita saber si hay algo en marcha antes de tocar el estado —borrar un
# bloqueo de bisync, por ejemplo—. Funciones y no constantes porque los tests
# mueven `STATE_DIR` al vuelo, igual que `results.ruta_estado()`.
# (`penwatch.py` tiene su propia copia de estas rutas a la fuerza: no puede
# importar nada del dispositivo. Hay un test que ata las dos.)

def daemon_lock() -> Path:
    return STATE_DIR / "daemon.lock.json"


def ui_lock() -> Path:
    return STATE_DIR / "ui.lock.json"

class ConfigError(Exception):
    """El config es inválido.

    Se lanza en vez de hacer sys.exit porque este módulo lo usa también la UI,
    donde matar el proceso significa cerrarle la ventana al usuario en las
    narices en vez de enseñarle qué línea del TOML está mal. Los puntos de
    entrada por línea de comandos la capturan y salen con su mensaje, así que
    por consola no se nota la diferencia."""


DEFAULT_REMOTE = "remote"
DEFAULT_MODE = "bisync"

# El nombre del remote 'combine' con el que el lado local deja de ser una ruta
# absoluta. Lo escribe el instalador en los [defaults] de cada dispositivo nuevo
# (ver install/deploy.device_config), y está aquí porque es este módulo el que
# sabe qué nombres valen (`_device_remote_name`) y qué se hace con ellos
# (`Config.pen_environment`).
DEFAULT_DEVICE_REMOTE = "disp"
# El upstream de la RAÍZ del dispositivo, para la pareja cuyo `local` es "."
# (ver `Pair.top_level_dir`). Tiene que ser un nombre y no ".", y sale en el
# prefijo de los listados de bisync: cambiarlo invalida esos baselines.
RAIZ_UPSTREAM = "raiz"
# La carpeta de versiones de una pareja, DENTRO de su propia raíz (ver
# `Pair.versions_path1`). Vive dentro del pair porque es del pair: se lleva con
# él y no hay nada que configurar. Que quepa ahí depende de que el fichero de
# filtros la excluya —rclone rechaza un `--backup-dir` que solape con el destino
# («destination and parameter to --backup-dir mustn't overlap») y aborta la
# pareja con error crítico—, así que `bisync.filters_content` la emite y lo hace
# como PRIMERA regla, porque rclone aplica las reglas en orden y gana la que
# casa antes.
VERSIONS_DIR = ".prversions"
DEFAULT_INTERVAL_MIN = 30.0         # minutos entre ciclos del servicio

# rclone es una app de consola: lanzada desde un proceso sin consola (pythonw, el
# servicio) Windows le abriría UNA VENTANA NUEVA por invocación.
CREATE_NO_WINDOW = 0x08000000


# Tipos de máquina de la cabecera PE: es en lo que contesta IsWow64Process2.
_MAQUINAS_PE = {
    0x8664: "amd64",
    0xAA64: "arm64",
    0x01C4: "arm",      # ARM de 32 bits (ARMNT)
    0x014C: "x86",
}


def maquina_nativa_windows() -> int | None:
    """El tipo de máquina nativa según IsWow64Process2, o None si no se sabe.

    Función de módulo, y no un bloque dentro de `machine_arch()`, por lo mismo
    que `catalog.run()` y `update.fetch()`: es lo único de aquí que depende del
    equipo donde corre, así que es lo que un test sustituye para preguntar qué
    pasaría en un ARM sin necesitar uno."""
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
        return None     # Windows anterior a 1709, o sin ctypes: queda platform


def machine_arch() -> str:
    """La arquitectura del EQUIPO en minúsculas: platform.machine() corregido.

    Windows on ARM ejecuta los binarios x64 emulados y les miente sobre dónde
    están. En un Python x64 sobre un Snapdragon, `platform.machine()` y
    `PROCESSOR_ARCHITECTURE` contestan 'AMD64'; también `GetNativeSystemInfo()`,
    que promete justo lo contrario, porque para el emulador la máquina nativa ES
    x64; y `PROCESSOR_ARCHITEW6432`, el apaño clásico, solo lo pone Windows en
    los procesos de 32 bits, no en los x64 emulados. La única que contesta la
    verdad es `IsWow64Process2()` (Windows 10 1709+), que devuelve por separado
    el tipo de máquina nativa.

    Importa porque los dos lados no corren con el mismo Python: el instalador es
    un .exe x64 —se compila en un runner x64— y el `runsync.py` del dispositivo
    corre con el Python del equipo, que en un portátil ARM es ARM64 nativo. Sin
    esto el instalador dejaba rclone en `bin/x64` y el dispositivo lo buscaba en
    `bin/arm`."""
    nativa = maquina_nativa_windows()
    if nativa in _MAQUINAS_PE:
        return _MAQUINAS_PE[nativa]
    return platform.machine().lower()


def arch_dir() -> str:
    """Subdirectorio de bin/ según la arquitectura de la CPU."""
    machine = machine_arch()
    if machine.startswith("arm") or machine in {"aarch64", "aarch64_be", "arm64"}:
        return "arm"
    if machine in {"x86_64", "amd64", "x64", "i386", "i686", "x86"}:
        return "x64"
    print(f"Aviso: arquitectura '{machine}' no reconocida; usando bin/x64.")
    return "x64"


def carpetas_bin(app_dir: Path) -> tuple[Path, ...]:
    """Dónde buscar rclone en la carpeta de programa `app_dir`, por orden.

    Un Windows ARM64 ejecuta los x64 emulados, así que un dispositivo provisionado
    por un instalador que se creyó x64 —lo que pasaba antes de `machine_arch()`—
    sigue arrancando en vez de quedarse sin rclone. Al revés no vale: un x64 no
    ejecuta ARM, y por eso la lista no es simétrica.

    Recibe la carpeta porque el agente residente (`agente.py`) busca el rclone de
    raíces que no son la suya; para este dispositivo son `BIN_DIR` y
    `BIN_FALLBACK_DIRS`."""
    propia = app_dir / "bin" / arch_dir()
    if os.name == "nt" and arch_dir() == "arm":
        return (propia, app_dir / "bin" / "x64")
    return (propia,)


BIN_DIR, *_recambios = carpetas_bin(APP_DIR)
BIN_FALLBACK_DIRS: tuple[Path, ...] = tuple(_recambios)


def rclone_name() -> str:
    return "rclone.exe" if os.name == "nt" else "rclone"


def rclone_path() -> Path | None:
    """El rclone del dispositivo, o None si no hay ninguno utilizable."""
    for carpeta in (BIN_DIR, *BIN_FALLBACK_DIRS):
        binary = carpeta / rclone_name()
        try:
            if binary.is_file():
                return binary
        except OSError:
            continue
    return None


def rclone_binary() -> str:
    """Ruta ejecutable al binario portable de rclone (apaño para exFAT sin +x)."""
    binary = rclone_path()
    if binary is None:
        # Lo normal es un dispositivo que no se preparó para este equipo: la cura
        # es el instalador, que baja el rclone fijado y lo comprueba, no que
        # alguien busque uno a mano.
        sys.exit(
            f"No encuentro el binario de rclone en: {BIN_DIR / rclone_name()}\n"
            f"Este dispositivo no se preparó para esta plataforma. Vuelve a "
            f"ejecutar el instalador de prdrive, elige este dispositivo y pulsa "
            f"«Añadir plataformas…»."
        )
    return ejecutable(binary)


def ejecutable(binary: Path) -> str:
    """Una ruta que se pueda ejecutar para ese rclone.

    En exFAT no hay bit de ejecución: en POSIX se copia al temporal y se le pone.
    Aparte de `rclone_binary()` para que el agente lo use con el rclone de otra
    raíz."""
    if os.name == "nt" or os.access(binary, os.X_OK):
        return str(binary)
    tmp = Path(tempfile.gettempdir()) / "rclone_portable"
    shutil.copy2(binary, tmp)
    tmp.chmod(tmp.stat().st_mode | stat.S_IXUSR | stat.S_IRUSR)
    return str(tmp)


def flags_to_args(flags: Mapping[str, Any]) -> list[str]:
    """{nombre: valor} -> argumentos de rclone.

        clave = true          -> --clave
        clave = false / None  -> (se omite)
        clave = 4 / "texto"   -> --clave 4 / --clave texto
        clave = ["a", "b"]    -> --clave a --clave b

    Vive aquí, y no en sync.py, porque es el último paso de la traducción
    config -> comando: quien funde las capas de flags es este módulo, y hay dos
    sitios más que tienen que traducirlos exactamente igual sin arrastrar el
    motor —la UI, que enseña en qué se convierten, y el instalador, que monta
    órdenes de rclone antes de que exista ningún dispositivo—.
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


# ---------------------------------------------------------------------------
# Modos
# ---------------------------------------------------------------------------

# Flags que lleva toda ejecución, sea del modo que sea.
#
# --stats / --stats-one-line: cómo va la pasada, una línea cada pocos segundos
#               en el log (la de fábrica es un bloque cada minuto). De ahí saca
#               sync.py el progreso en vivo (common/progress.py). Van en esta
#               capa y no en el código para que una pareja los pueda cambiar
#               como cualquier otro flag; sin ellos no hay progreso, y la
#               pasada va igual.
BASE_FLAGS: Mapping[str, Any] = {
    "verbose": True,
    "create-empty-src-dirs": True,
    "stats": "2s",
    "stats-one-line": True,
}


@dataclass(frozen=True)
class Mode:
    """Qué subcomando de rclone es cada modo, en qué sentido va y con qué flags.

    `source`/`dest` son los nombres de los extremos ('local' o 'remote'), no las
    rutas: quién es origen y quién destino es justo lo que distingue `up` de
    `down`."""
    name: str
    verb: str
    source: str
    dest: str
    flags: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_bisync(self) -> bool:
        return self.verb == "bisync"


# --resilient : errores "menores" no obligan a --resync en la siguiente pasada.
# --recover   : una interrupción brusca se recupera sola en la siguiente pasada.
# --max-lock  : caduca el .lck que deja un proceso muerto (mínimo 2m).
# --max-delete: una ruta local vacía o desmontada no debe arrasar el otro lado.
#               El 25 de bisync NO es una cuenta de ficheros: es un porcentaje.
#               Options.applyContext() (cmd/bisync/cmd.go) lee el --max-delete
#               global, lo acota a 0..100 y acto seguido pone ci.MaxDelete = -1
#               ("reset MaxDelete for fs/operations, bisync handles this
#               parameter specially"), así que fs/operations ya no lo cuenta
#               como número de borrados. excessDeletes() (cmd/bisync/deltas.go)
#               compara deleted / oldCount contra ese porcentaje del listado
#               ANTERIOR. El 50 de up-mirror/down-mirror sí es una cuenta: ahí
#               es el --max-delete corriente de `sync`. No iguales los dos
#               números pensando que miden lo mismo.
# --conflict-suffix: un sufijo POR LADO. Con el de fábrica ("conflict") y
#               --conflict-loser num, rclone llama al perdedor `.conflictN` con
#               el primer número libre (cmd/bisync/resolve.go: resolve y
#               numerate), y ese número es un orden, no un lado: no hay forma
#               de saber después si la copia era la de este dispositivo o la
#               del remoto. Con dos sufijos distintos el nombre lo dice, y sigue
#               numerado, así que un segundo conflicto en el mismo fichero no
#               pisa la copia del primero (con --conflict-loser pathname sí la
#               pisaría: el nombre sería otra vez `.conflict1`). Quien lo lee es
#               common/conflicts.py.
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


# ---------------------------------------------------------------------------
# Pareja
# ---------------------------------------------------------------------------

def _as_tuple(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


@dataclass(frozen=True)
class Pair:
    """Una [[pair]] del TOML con todas sus capas ya fusionadas.

    `flags` y los patrones de filtrado llegan aquí resueltos; nadie aguas abajo
    necesita saber que existían unos `[defaults]`."""
    name: str
    mode: Mode
    local: str                 # relativa al dispositivo, con / y sin barras sueltas
    remote_path: str
    remote_name: str
    includes: tuple[str, ...]
    excludes: tuple[str, ...]
    flags: Mapping[str, Any]
    extra_flags: tuple[str, ...]
    use_filters_file: bool
    device_remote: str | None
    versions: bool

    # --- extremos tal y como se le pasan a rclone --------------------------

    @property
    def local_abs(self) -> Path:
        return (DEVICE_ROOT / self.local).resolve()

    @property
    def local_endpoint(self) -> str:
        """Con `device_remote` el lado local es un remote propio, y entonces su
        nombre ya no depende de dónde esté montado el dispositivo."""
        if self.device_remote:
            return f"{self.device_remote}:{self.ruta_en_combine}"
        return str(self.local_abs)

    @property
    def remote_endpoint(self) -> str:
        return f"{self.remote_name}:{self.remote_path}"

    def endpoint(self, kind: str) -> str:
        return self.local_endpoint if kind == "local" else self.remote_endpoint

    @property
    def source(self) -> str:
        return self.endpoint(self.mode.source)

    @property
    def dest(self) -> str:
        return self.endpoint(self.mode.dest)

    # --- resto ---------------------------------------------------------------

    @property
    def is_bisync(self) -> bool:
        return self.mode.is_bisync

    @property
    def workdir(self) -> Path:
        """Workdir de bisync: uno por pareja, para que sus listados no se mezclen."""
        return STATE_DIR / self.name

    @property
    def tramos_locales(self) -> tuple[str, ...]:
        """La ruta local partida, sin los tramos que no dicen nada ("." y "")."""
        partida = self.local.replace("\\", "/").split("/")
        return tuple(t for t in partida if t not in ("", "."))

    @property
    def top_level_dir(self) -> str:
        """Primer tramo de la ruta local: lo que se declara como upstream del
        remote 'combine' cuando se usa `device_remote`.

        Una pareja que sincroniza la RAÍZ del dispositivo (`local = "."`) no
        tiene primer tramo, y no vale dejarlo en ".": rclone limpia la ruta antes
        de buscar el upstream, así que `disp:.` se convierte en el upstream ""
        y falla con «combine for remote "": directory not found». Por eso la raíz
        se declara con un nombre de verdad."""
        tramos = self.tramos_locales
        return tramos[0] if tramos else RAIZ_UPSTREAM

    @property
    def top_level_abs(self) -> Path:
        """La carpeta a la que apunta ese upstream."""
        tramos = self.tramos_locales
        return (DEVICE_ROOT / tramos[0]).resolve() if tramos else DEVICE_ROOT.resolve()

    @property
    def ruta_en_combine(self) -> str:
        """La ruta de la pareja vista desde dentro del remote 'combine'. Para
        todas menos la raíz es la ruta local tal cual."""
        return "/".join((self.top_level_dir,) + self.tramos_locales[1:])

    @property
    def wants_filters_file(self) -> bool:
        """--filters-file es exclusivo de bisync; en el resto van --include/--exclude."""
        return self.is_bisync and self.use_filters_file

    # --- versiones -----------------------------------------------------------
    #
    # Los dos extremos son los de la pareja con la carpeta detrás, y no hay una
    # tercera ruta que configurar. Path1 es `source` y Path2 es `dest` porque es
    # así como se los pasa `build_command` a rclone, y en bisync `source` es el
    # lado local. Se construyen con "/" también en Windows: rclone admite la
    # barra en una ruta local y así la propiedad no tiene dos ramas.

    @property
    def versions_path1(self) -> str:
        """--backup-dir1: lo que pierde el lado local."""
        return f"{self.source.rstrip('/')}/{VERSIONS_DIR}"

    @property
    def versions_path2(self) -> str:
        """--backup-dir2: lo que pierde el lado remoto."""
        return f"{self.dest.rstrip('/')}/{VERSIONS_DIR}"


def _build_pair(raw: Mapping[str, Any], defaults: Mapping[str, Any]) -> Pair:
    """Funde las capas de configuración de una pareja. El orden de los flags va
    de menos a más prioridad: base < modo < [defaults.flags] < [pair.flags]."""
    name = raw.get("name")
    if not name:
        raise ConfigError("Hay una [[pair]] sin 'name' en el config.")
    for required in ("local", "remote_path"):
        if required not in raw:
            raise ConfigError(f"[{name}] falta '{required}' en el config.")

    mode_name = raw.get("mode", DEFAULT_MODE)
    mode = MODES.get(mode_name)
    if mode is None:
        raise ConfigError(f"[{name}] modo inválido: '{mode_name}'. Válidos: {sorted(MODES)}")

    # El versionado se apoya en --backup-dir1/--backup-dir2 y en que el perdedor
    # de un conflicto se aparte en vez de quedarse suelto: las tres cosas son de
    # bisync. En un copy/sync no hay dos lados que guardar, así que la clave no
    # significa nada ahí y vale más decirlo al parsear que dejarla sin efecto.
    versions = bool(raw.get("versions", False))
    if versions and not mode.is_bisync:
        raise ConfigError(
            f"[{name}] 'versions' solo vale en modo bisync, y esta pareja es "
            f"'{mode_name}'. Quita la clave o cambia el modo.")

    return Pair(
        name=name,
        mode=mode,
        local=str(raw["local"]).replace("\\", "/").strip("/"),
        remote_path=raw["remote_path"],
        remote_name=raw.get("remote", defaults.get("remote", DEFAULT_REMOTE)),
        includes=_as_tuple(defaults.get("include")) + _as_tuple(raw.get("include")),
        excludes=_as_tuple(defaults.get("exclude")) + _as_tuple(raw.get("exclude")),
        flags={**BASE_FLAGS, **mode.flags,
               **defaults.get("flags", {}), **raw.get("flags", {})},
        extra_flags=_as_tuple(defaults.get("extra_flags")) + _as_tuple(raw.get("extra_flags")),
        use_filters_file=raw.get("use_filters_file",
                                 defaults.get("use_filters_file", True)),
        device_remote=_device_remote_name(defaults),
        versions=versions,
    )


def _device_remote_name(defaults: Mapping[str, Any]) -> str | None:
    """El nombre viaja en variables de entorno RCLONE_CONFIG_<NOMBRE>_*, que no
    admiten cualquier cosa."""
    name = defaults.get("device_remote")
    if not name:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise ConfigError(
            f"'device_remote' debe ser alfanumérico sin guiones (va en una "
            f"variable de entorno RCLONE_CONFIG_<NOMBRE>_*): '{name}'")
    return name


# ---------------------------------------------------------------------------
# Configuración completa
# ---------------------------------------------------------------------------

def _upstream(nombre: str, ruta: Path) -> str:
    r"""Un tramo del `upstreams` del remote 'combine', tal y como rclone lo lee.

    rclone parsea `upstreams` como `fs.SpaceSepList` (fs/types.go), que es un
    CSV con el espacio de separador: un campo solo va entrecomillado si empieza
    por comilla, y una comilla dentro de un campo que no empezaba por comilla es
    un error de sintaxis. Por eso las comillas envuelven el PAR ENTERO
    `nombre=ruta` y no la ruta: entrecomillar solo la ruta daba `.="F:\"`, que
    rclone rechaza con «bare " in non-quoted-field» y tumbaba TODAS las parejas
    del dispositivo. Entre comillas caben tanto la barra final de la raíz de una
    unidad (`F:\`) como los espacios de la ruta, que es para lo que hacían
    falta. Una comilla dentro de la ruta se dobla, como manda el CSV.
    """
    texto = str(ruta).replace('"', '""')
    return f'"{nombre}={texto}"'


@dataclass(frozen=True)
class Config:
    pairs: tuple[Pair, ...]
    daemon: Mapping[str, Any]
    keep_logs: bool
    device_remote: str | None

    @property
    def names(self) -> list[str]:
        return [p.name for p in self.pairs]

    def select(self, wanted: Iterable[str]) -> list[Pair]:
        """Las parejas pedidas, en el orden del TOML. Aborta si alguna no existe:
        un nombre mal escrito no puede acabar en 'pues no sincronizo eso'."""
        wanted = set(wanted)
        chosen = [p for p in self.pairs if p.name in wanted]
        missing = wanted - {p.name for p in chosen}
        if missing:
            raise ConfigError(
                f"No existen estas parejas en el config: {', '.join(sorted(missing))}")
        return chosen

    def pen_environment(self) -> dict[str, str]:
        """Variables que definen el remote 'combine' del dispositivo en ejecución.

        Un remote 'alias' NO sirve: backend/alias/alias.go devuelve el Fs de
        destino tal cual, así que con destino local f.Name() vuelve a ser "local"
        y la ruta absoluta reaparece en el nombre de los listados. Un 'combine' sí
        es un Fs propio y el lado local pasa a llamarse "dispositivo:sync-data/x"
        en cualquier máquina.

        Se calcula con TODAS las parejas, no solo las seleccionadas, para que el
        remote sea idéntico ejecutes lo que ejecutes."""
        if not self.device_remote:
            return {}
        tops: dict[str, Path] = {}
        for pareja in self.pairs:
            nombre, ruta = pareja.top_level_dir, pareja.top_level_abs
            # Dos parejas que pidan el mismo nombre para carpetas distintas solo
            # puede pasar con la raíz: `local = "."` la declara como RAIZ_UPSTREAM
            # y otra pareja tiene una carpeta que se llama justo así. Sería un
            # upstream apuntando a donde no es, callando.
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


def parse_config(data: Mapping[str, Any]) -> Config:
    defaults = data.get("defaults", {})
    raw_pairs = data.get("pair", [])
    if not raw_pairs:
        raise ConfigError("El config no tiene ninguna [[pair]] definida.")
    return Config(
        pairs=tuple(_build_pair(p, defaults) for p in raw_pairs),
        daemon=data.get("daemon", {}),
        keep_logs=bool(defaults.get("keep_logs", False)),
        device_remote=_device_remote_name(defaults),
    )


def load_config() -> Config:
    if not CONFIG_FILE.exists():
        raise ConfigError(f"No existe el fichero de configuración: {CONFIG_FILE}")
    with CONFIG_FILE.open("rb") as f:
        return parse_config(tomllib.load(f))
