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
# Este módulo vive en rclone-sync/common/, así que la carpeta de la aplicación
# —la que contiene sync_config.toml, rclone.conf, bin/, keys/, y contra la que
# rclone resuelve las rutas relativas de su config— es el directorio padre, y el
# pen el siguiente. Nada de esto depende de la letra de unidad.
APP_DIR = Path(__file__).resolve().parent.parent
PEN_ROOT = APP_DIR.parent  # las rutas 'local' del config son relativas a aquí
CONFIG_FILE = APP_DIR / "sync_config.toml"
RCLONE_CONF = APP_DIR / "rclone.conf"
STATE_DIR = APP_DIR / "state"
FILTERS_DIR = APP_DIR / "filters"
LOG_DIR = APP_DIR / "logs"

SYNC_PY = APP_DIR / "sync.py"       # a quien lanzan la UI y el servicio
PENWATCH_PY = APP_DIR / "penwatch.py"

class ConfigError(Exception):
    """El config es inválido.

    Se lanza en vez de hacer sys.exit porque este módulo lo usa también la UI,
    donde matar el proceso significa cerrarle la ventana al usuario en las
    narices en vez de enseñarle qué línea del TOML está mal. Los puntos de
    entrada por línea de comandos la capturan y salen con su mensaje, así que
    por consola no se nota la diferencia."""


DEFAULT_REMOTE = "synology"
DEFAULT_MODE = "bisync"
DEFAULT_INTERVAL_MIN = 30.0         # minutos entre ciclos del servicio

# rclone es una app de consola: lanzada desde un proceso sin consola (pythonw, el
# servicio) Windows le abriría UNA VENTANA NUEVA por invocación.
CREATE_NO_WINDOW = 0x08000000


def arch_dir() -> str:
    """Subdirectorio de bin/ según la arquitectura de la CPU."""
    machine = platform.machine().lower()
    if machine.startswith("arm") or machine in {"aarch64", "aarch64_be", "arm64"}:
        return "arm"
    if machine in {"x86_64", "amd64", "x64", "i386", "i686", "x86"}:
        return "x64"
    print(f"Aviso: arquitectura '{platform.machine()}' no reconocida; usando bin/x64.")
    return "x64"


BIN_DIR = APP_DIR / "bin" / arch_dir()


def rclone_binary() -> str:
    """Ruta ejecutable al binario portable de rclone (con apaño para pen sin +x)."""
    name = "rclone.exe" if os.name == "nt" else "rclone"
    binary = BIN_DIR / name
    if not binary.exists():
        sys.exit(
            f"No encuentro el binario de rclone en: {binary}\n"
            f"Descarga el rclone portable de tu plataforma y colócalo ahí."
        )
    if os.name == "nt" or os.access(binary, os.X_OK):
        return str(binary)
    tmp = Path(tempfile.gettempdir()) / "rclone_portable"
    shutil.copy2(binary, tmp)
    tmp.chmod(tmp.stat().st_mode | stat.S_IXUSR | stat.S_IRUSR)
    return str(tmp)


# ---------------------------------------------------------------------------
# Modos
# ---------------------------------------------------------------------------

# Flags que lleva toda ejecución, sea del modo que sea.
BASE_FLAGS: Mapping[str, Any] = {
    "verbose": True,
    "create-empty-src-dirs": True,
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
MODES: Mapping[str, Mode] = {m.name: m for m in (
    Mode("bisync", "bisync", "local", "remote", {
        "conflict-resolve": "newer",
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
    local: str                      # relativa al pen, con / y sin barras sueltas
    remote_path: str
    remote_name: str
    includes: tuple[str, ...]
    excludes: tuple[str, ...]
    flags: Mapping[str, Any]
    extra_flags: tuple[str, ...]
    use_filters_file: bool
    pen_remote: str | None

    # --- extremos tal y como se le pasan a rclone --------------------------

    @property
    def local_abs(self) -> Path:
        return (PEN_ROOT / self.local).resolve()

    @property
    def local_endpoint(self) -> str:
        """Con `pen_remote` el lado local es un remote propio, y entonces su
        nombre ya no depende de dónde esté montado el pen."""
        if self.pen_remote:
            return f"{self.pen_remote}:{self.local}"
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
    def top_level_dir(self) -> str:
        """Primer tramo de la ruta local: lo que se declara como upstream del
        remote 'combine' cuando se usa `pen_remote`."""
        return self.local.split("/")[0]

    @property
    def wants_filters_file(self) -> bool:
        """--filters-file es exclusivo de bisync; en el resto van --include/--exclude."""
        return self.is_bisync and self.use_filters_file


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
        pen_remote=_pen_remote_name(defaults),
    )


def _pen_remote_name(defaults: Mapping[str, Any]) -> str | None:
    """El nombre viaja en variables de entorno RCLONE_CONFIG_<NOMBRE>_*, que no
    admiten cualquier cosa."""
    name = defaults.get("pen_remote")
    if not name:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise ConfigError(
            f"'pen_remote' debe ser alfanumérico sin guiones (va en una variable "
            f"de entorno RCLONE_CONFIG_<NOMBRE>_*): '{name}'")
    return name


# ---------------------------------------------------------------------------
# Configuración completa
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Config:
    pairs: tuple[Pair, ...]
    daemon: Mapping[str, Any]
    keep_logs: bool
    pen_remote: str | None

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
        """Variables que definen el remote 'combine' del pen en tiempo de ejecución.

        Un remote 'alias' NO sirve: backend/alias/alias.go devuelve el Fs de
        destino tal cual, así que con destino local f.Name() vuelve a ser "local"
        y la ruta absoluta reaparece en el nombre de los listados. Un 'combine' sí
        es un Fs propio y el lado del pen pasa a llamarse "pen:sync-data/x" en
        cualquier máquina.

        Se calcula con TODAS las parejas, no solo las seleccionadas, para que el
        remote sea idéntico ejecutes lo que ejecutes."""
        if not self.pen_remote:
            return {}
        tops = sorted({p.top_level_dir for p in self.pairs})
        upstreams = " ".join(f'{t}="{(PEN_ROOT / t).resolve()}"' for t in tops)
        return {
            f"RCLONE_CONFIG_{self.pen_remote.upper()}_TYPE": "combine",
            f"RCLONE_CONFIG_{self.pen_remote.upper()}_UPSTREAMS": upstreams,
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
        pen_remote=_pen_remote_name(defaults),
    )


def load_config() -> Config:
    if not CONFIG_FILE.exists():
        raise ConfigError(f"No existe el fichero de configuración: {CONFIG_FILE}")
    with CONFIG_FILE.open("rb") as f:
        return parse_config(tomllib.load(f))
