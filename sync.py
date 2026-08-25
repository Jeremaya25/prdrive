#!/usr/bin/env python3
"""
sync.py — Sincronización portable Synology <-> pen mediante rclone.

Todo vive en el pen y no depende de nada instalado en la máquina salvo
Python 3.11+ (para tomllib). El binario de rclone es portable (carpeta bin/).

Estructura esperada en el pen:

    PEN/
    ├── rclone-sync/
    │   ├── sync.py            <- este script
    │   ├── sync_config.toml   <- qué carpetas sincronizar y en qué dirección
    │   ├── rclone.conf        <- config de rclone (remote SFTP + ruta a la clave)
    │   ├── bin/<arch>/
    │   │   ├── rclone.exe     <- binario portable Windows
    │   │   └── rclone         <- binario portable Linux
    │   ├── keys/              <- clave privada SSH (el pen ya va cifrado con BitLocker)
    │   ├── filters/<pareja>.txt     <- filtros generados desde el TOML (+ su .md5)
    │   ├── state/<pareja>/    <- workdir de bisync, UNO POR PAREJA
    │   └── logs/            <- solo logs de ejecuciones fallidas
    └── sync-data/             <- aquí viven las carpetas locales que se sincronizan

Uso:
    python sync.py                 # ejecuta todas las parejas del config
    python sync.py obsidian fotos  # solo esas parejas
    python sync.py --list          # lista las parejas configuradas
    python sync.py --doctor        # diagnostica el estado de bisync y sale
    python sync.py --dry-run       # simula, no toca nada (úsalo SIEMPRE la 1a vez)
    python sync.py --resync        # rehace el baseline de bisync (1a vez o si se rompe)
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# tomllib es stdlib desde Python 3.11. Fallback a 'tomli' en versiones viejas.
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore
    except ModuleNotFoundError:
        sys.exit("Necesitas Python 3.11+ (tomllib) o instalar tomli: pip install tomli")

# --- Rutas, todas relativas a la ubicación del script (independiente de la letra de unidad) ---
SCRIPT_DIR = Path(__file__).resolve().parent
PEN_ROOT = SCRIPT_DIR.parent  # las rutas 'local' del config son relativas a aquí
CONFIG_FILE = SCRIPT_DIR / "sync_config.toml"
RCLONE_CONF = SCRIPT_DIR / "rclone.conf"
STATE_DIR = SCRIPT_DIR / "state"
FILTERS_DIR = SCRIPT_DIR / "filters"
LOG_DIR = SCRIPT_DIR / "logs"

LOG_TAIL_LINES = 15  # líneas de log que se vuelcan a consola cuando algo falla
SKIPPED = -1         # código interno: pareja no ejecutada (ni OK ni fallo)


def arch_dir() -> str:
    """Devuelve el subdirectorio de 'bin/' según la arquitectura de la CPU."""
    machine = platform.machine().lower()
    if machine.startswith("arm") or machine in {"aarch64", "aarch64_be", "arm64"}:
        return "arm"
    if machine in {"x86_64", "amd64", "x64", "i386", "i686", "x86"}:
        return "x64"
    print(f"Aviso: arquitectura '{platform.machine()}' no reconocida; usando bin/x64.")
    return "x64"


BIN_DIR = SCRIPT_DIR / "bin" / arch_dir()

# Modo -> (subcomando rclone, extremo ORIGEN, extremo DESTINO).
MODES = {
    "bisync":      ("bisync", "local",  "remote"),
    "up":          ("copy",   "local",  "remote"),
    "down":        ("copy",   "remote", "local"),
    "up-mirror":   ("sync",   "local",  "remote"),
    "down-mirror": ("sync",   "remote", "local"),
}

BASE_FLAGS = {
    "verbose": True,
    "create-empty-src-dirs": True,
}

# --resilient : errores "menores" no obligan a --resync en la siguiente pasada.
# --recover   : una interrupción brusca se recupera sola en la siguiente pasada.
# --max-lock  : caduca el .lck que deja un proceso muerto (mínimo 2m).
MODE_DEFAULT_FLAGS = {
    "bisync": {
        "conflict-resolve": "newer",
        "max-delete": 25,
        "resilient": True,
        "recover": True,
        "max-lock": "2m",
    },
    "up-mirror":   {"max-delete": 50},
    "down-mirror": {"max-delete": 50},
}

KNOWN_ERRORS = [
    ("cannot find prior Path1 or Path2 listings",
     "No hay baseline: primera vez, listados en otro sitio (¿cambió la ruta?) o "
     "un fallo crítico previo los invalidó. Solución: --resync."),
    ("filters file has changed",
     "Han cambiado los filtros. Solución: --resync (bisync no puede saber qué "
     "ficheros excluidos existían antes)."),
    ("filters file md5 hash not found",
     "Primer uso de este fichero de filtros. Solución: --resync."),
    ("must run --resync",
     "bisync ha invalidado el baseline y exige rehacerlo. Solución: --resync."),
    ("--max-delete",
     "Se han superado los borrados permitidos. Comprueba que la ruta local NO "
     "esté vacía o desmontada antes de forzar nada."),
    ("Access is denied",
     "Fichero bloqueado por otro proceso (Obsidian, KeePass, antivirus)."),
    ("lock file",
     "Hay un lock de otra ejecución. Si no hay ninguna corriendo, borra el .lck "
     "del workdir de la pareja."),
    ("known_hosts_file",
     "rclone no encuentra el fichero de known_hosts indicado en rclone.conf. "
     "Las rutas relativas de rclone.conf se resuelven contra rclone-sync/; "
     "comprueba que keys/known_hosts existe ahí."),
    ("Failed to create file system",
     "rclone no ha podido montar uno de los dos extremos. Suele ser una ruta o "
     "credencial mal resuelta en rclone.conf (revisa key_file y "
     "known_hosts_file), o el NAS inalcanzable."),
]


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


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        sys.exit(f"No existe el fichero de configuración: {CONFIG_FILE}")
    with CONFIG_FILE.open("rb") as f:
        return tomllib.load(f)


def temp_log(name: str) -> Path:
    """rclone escribe siempre a un log, pero en un temporal del sistema.

    Solo se conserva (moviéndolo a logs/) si la ejecución ha fallado. Si todo va
    bien no queda rastro y no se escribe en el pen: menos ciclos de escritura y
    una carpeta logs/ que solo contiene lo que hay que mirar."""
    fd, path = tempfile.mkstemp(prefix=f"rclone-sync-{name}-", suffix=".log")
    os.close(fd)
    return Path(path)


def keep_log(name: str, tmp: Path) -> Path:
    """Mueve un log temporal a logs/ y devuelve su ruta definitiva."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final = LOG_DIR / f"{name}_{stamp}.log"
    n = 1
    while final.exists():  # ejecución + reintento dentro del mismo segundo
        final = LOG_DIR / f"{name}_{stamp}_{n}.log"
        n += 1
    shutil.move(str(tmp), str(final))
    return final


def dispose_log(name: str, tmp: Path, rc: int, keep_always: bool) -> Path | None:
    """Descarta el log si la ejecución fue bien; si no, lo guarda en logs/."""
    if rc == 0 and not keep_always:
        tmp.unlink(missing_ok=True)
        return None
    return keep_log(name, tmp)


def ask_yes_no(question: str, default: bool = False) -> bool:
    """Sí/no por consola. Sin terminal interactiva no bloquea: devuelve 'default'."""
    if not sys.stdin or not sys.stdin.isatty():
        return default
    suffix = " [S/n] " if default else " [s/N] "
    try:
        answer = input(question + suffix).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not answer:
        return default
    return answer in {"s", "si", "sí", "y", "yes"}


# ---------------------------------------------------------------------------
# Nombre de sesión de bisync
#
# Réplica exacta de cmd/bisync/bilib/canonical.go (rclone master). Saber calcular
# el nombre que rclone va a buscar nos permite detectar ANTES de ejecutar que el
# baseline está guardado con otro prefijo (p.ej. el pen se montaba en G: y ahora
# en F:) y renombrarlo, en vez de comerse un error crítico.
#
#   FsPath(f)        -> "F:\ruta\" para el backend local, "remote:ruta/" para el resto
#   CanonicalPath(s) -> quita / y \ de los extremos y sustituye [\s\\/:?*] por _
#   SessionName      -> CanonicalPath(path1) + ".." + CanonicalPath(path2),
#                       quitando el sufijo {hexstring} que rclone añade cuando la
#                       config del remote viene de flags/env/connection string.
# ---------------------------------------------------------------------------

_NON_CANONICAL = re.compile(r"[\s\\/:?*]")


def canonical_path(remote: str) -> str:
    return _NON_CANONICAL.sub("_", remote.strip("\\/"))


def strip_hex_string(path: str) -> str:
    o, c = path.find("{"), path.find("}")
    if o >= 0 and c > o:
        return path[:o] + path[c + 1:]
    return path


def fs_path_local(p: str) -> str:
    sep = os.sep
    if os.name == "nt":
        p = p.replace("/", sep)
        if p.startswith("\\\\?\\"):
            p = p[4:]
    return p if p.endswith(sep) else p + sep


def fs_path_remote(s: str) -> str:
    return s if s.endswith("/") else s + "/"


def session_name(path1: str, path2: str) -> str:
    return strip_hex_string(canonical_path(path1)) + ".." + strip_hex_string(canonical_path(path2))


# ---------------------------------------------------------------------------
# Extremos: el pen como ruta local o como remote 'combine'
#
# Por qué NO sirve un remote 'alias': backend/alias/alias.go no devuelve un Fs
# envoltorio, hace `return cache.Get(ctx, fspath.JoinRootPath(opt.Remote, root))`,
# es decir devuelve el Fs de destino tal cual. Con destino local, f.Name() vuelve
# a ser "local" y FsPath reconstruye la ruta absoluta: el nombre del listado
# seguiría dependiendo de la letra de unidad. Un remote 'combine' sí es un Fs
# propio (Name() devuelve el nombre configurado), así que el lado del pen pasa a
# llamarse "pen:sync-data/obsidian" en cualquier máquina y en cualquier SO.
# ---------------------------------------------------------------------------

def pen_remote_name(defaults: dict) -> str | None:
    name = defaults.get("pen_remote")
    if not name:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        sys.exit(f"'pen_remote' debe ser alfanumérico sin guiones (va en una variable "
                 f"de entorno RCLONE_CONFIG_<NOMBRE>_*): '{name}'")
    return name


def local_rel(pair: dict) -> str:
    return pair["local"].replace("\\", "/").strip("/")


def local_abs(pair: dict) -> Path:
    return (PEN_ROOT / pair["local"]).resolve()


def endpoints_for(pair: dict, defaults: dict) -> dict[str, str]:
    """Cadenas tal cual se le pasan a rclone."""
    remote_name = pair.get("remote", defaults.get("remote", "synology"))
    pen = pen_remote_name(defaults)
    local = f"{pen}:{local_rel(pair)}" if pen else str(local_abs(pair))
    return {"remote": f"{remote_name}:{pair['remote_path']}", "local": local}


def expected_prefix(pair: dict, defaults: dict) -> str:
    """Nombre base (.path1.lst / .path2.lst) que rclone buscará para esta pareja."""
    ep = endpoints_for(pair, defaults)
    mode = pair.get("mode", "bisync")
    _, src_kind, dst_kind = MODES[mode]
    pen = pen_remote_name(defaults)

    def render(kind: str) -> str:
        value = ep[kind]
        if kind == "local" and not pen:
            return fs_path_local(value)
        return fs_path_remote(value)

    return session_name(render(src_kind), render(dst_kind))


def pen_environment(all_pairs: list[dict], defaults: dict) -> dict[str, str]:
    """Variables de entorno que definen el remote 'combine' del pen en tiempo de
    ejecución. Se calcula con TODAS las parejas (no solo las seleccionadas) para
    que el remote sea idéntico ejecutes lo que ejecutes."""
    pen = pen_remote_name(defaults)
    if not pen:
        return {}
    tops = sorted({local_rel(p).split("/")[0] for p in all_pairs})
    upstreams = " ".join(f'{t}="{(PEN_ROOT / t).resolve()}"' for t in tops)
    return {
        f"RCLONE_CONFIG_{pen.upper()}_TYPE": "combine",
        f"RCLONE_CONFIG_{pen.upper()}_UPSTREAMS": upstreams,
    }


# ---------------------------------------------------------------------------
# Filtros: un fichero por pareja, generado desde el TOML
#
# bisync guarda el md5 del fichero de filtros JUNTO AL PROPIO FICHERO
# (filtersFile + ".md5", ver cmd/bisync/cmd.go: applyFilters) y solo lo escribe
# durante un --resync. Si el fichero cambia sin resync, aborta con error crítico.
# Aquí comparamos el md5 nosotros ANTES de ejecutar y lo tratamos como "hace
# falta resync", que es una conversación, no un log rojo.
# ---------------------------------------------------------------------------

def filter_patterns(pair: dict, defaults: dict) -> tuple[list[str], list[str]]:
    includes = list(defaults.get("include", [])) + list(pair.get("include", []))
    excludes = list(defaults.get("exclude", [])) + list(pair.get("exclude", []))
    return includes, excludes


def filters_file_for(pair: dict, defaults: dict) -> Path | None:
    """Genera (si hace falta) filters/<pareja>.txt y devuelve su ruta.

    Solo para bisync: --filters-file es un flag exclusivo de ese subcomando.
    El contenido es determinista; si no cambia, no se reescribe el fichero.
    """
    if pair.get("mode", "bisync") != "bisync":
        return None
    if not pair.get("use_filters_file", defaults.get("use_filters_file", True)):
        return None

    includes, excludes = filter_patterns(pair, defaults)
    lines = ["# Generado por sync.py desde sync_config.toml. No editar a mano:",
             "# se regenera en cada ejecución. Cambiar los patrones exige --resync."]
    lines += [f"+ {p}" for p in includes]
    lines += [f"- {p}" for p in excludes]
    if includes:
        # Igual que --include: si hay reglas '+', todo lo demás queda fuera.
        lines.append("- **")
    content = "\n".join(lines) + "\n"

    FILTERS_DIR.mkdir(parents=True, exist_ok=True)
    path = FILTERS_DIR / f"{pair['name']}.txt"
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        path.write_text(content, encoding="utf-8", newline="\n")
    return path


def filters_state(ffile: Path | None) -> tuple[str, str]:
    """('ok'|'new'|'changed', detalle) comparando con el .md5 que guarda bisync."""
    if ffile is None:
        return "ok", "sin fichero de filtros"
    digest = hashlib.md5(ffile.read_bytes()).hexdigest()
    hash_file = Path(str(ffile) + ".md5")
    if not hash_file.exists():
        return "new", f"{ffile.name} sin hash previo"
    if hash_file.read_text(encoding="utf-8").strip() != digest:
        return "changed", f"{ffile.name} ha cambiado desde el último resync"
    return "ok", f"{ffile.name} sin cambios"


# ---------------------------------------------------------------------------
# Estado de bisync
# ---------------------------------------------------------------------------

def pair_workdir(name: str) -> Path:
    return STATE_DIR / name


def pair_state(name: str) -> tuple[str, str, str | None]:
    """('fresh'|'ok'|'broken', detalle, prefijo) mirando los .lst reales."""
    wd = pair_workdir(name)
    if not wd.exists():
        return "fresh", "sin workdir (nunca sincronizada)", None

    # OJO al orden: los .lst-err NO los limpia nadie (rclone solo renombra .lst ->
    # .lst-err al abortar; ver cmd/bisync/operations.go). Si después hay un juego
    # de listados válido, el baseline es bueno y esos ficheros son residuo.
    p1 = sorted(wd.glob("*.path1.lst"))
    p2 = sorted(wd.glob("*.path2.lst"))
    errs = sorted(wd.glob("*.lst-err"))
    residuo = f" (+{len(errs)} .lst-err residuales)" if errs else ""

    if p1 and p2:
        pre1 = {f.name[: -len(".path1.lst")] for f in p1}
        pre2 = {f.name[: -len(".path2.lst")] for f in p2}
        common = pre1 & pre2
        if len(common) != 1 or len(pre1) != 1 or len(pre2) != 1:
            return "broken", f"varios juegos de listados: {sorted(pre1 | pre2)}", None
        prefix = common.pop()
        return "ok", f"baseline '{prefix}'{residuo}", prefix

    if errs:
        return "broken", f"{len(errs)} listado(s) marcados .lst-err por un fallo crítico previo", None
    if p1 or p2:
        return "broken", "falta uno de los dos listados (.path1/.path2)", None
    return "fresh", "sin listados previos", None


def migrate_legacy_state(pair: dict, defaults: dict) -> None:
    """Mueve los listados del layout antiguo (todo suelto en state/) al workdir
    por pareja, identificando la pareja por el token del remoto en el nombre."""
    name = pair["name"]
    wd = pair_workdir(name)
    if wd.exists() and any(wd.glob("*.lst")):
        return
    remote_name = pair.get("remote", defaults.get("remote", "synology"))
    token = canonical_path(f"{remote_name}:{pair['remote_path']}")
    candidates = {
        f.name[: -len(".path1.lst")]
        for f in STATE_DIR.glob("*.path1.lst")
        if token in f.name
    }
    if len(candidates) != 1:
        return
    prefix = candidates.pop()
    wd.mkdir(parents=True, exist_ok=True)
    moved = 0
    for f in STATE_DIR.iterdir():
        if f.is_file() and f.name.startswith(prefix):
            shutil.move(str(f), str(wd / f.name))
            moved += 1
    if moved:
        print(f"  migrados {moved} fichero(s) de estado a {wd}")


def rename_prefix(name: str, old_prefix: str, new_prefix: str) -> None:
    wd = pair_workdir(name)
    for f in sorted(wd.iterdir()):
        if f.is_file() and f.name.startswith(old_prefix):
            f.rename(wd / (new_prefix + f.name[len(old_prefix):]))
    print(f"  listados renombrados: '{old_prefix}' -> '{new_prefix}'")


def normalize_prefix(pair: dict, defaults: dict) -> None:
    """Si el baseline está guardado con otro prefijo (la ruta del pen ha cambiado),
    lo renombra ANTES de ejecutar. El contenido de los .lst es relativo a la raíz
    sincronizada, así que renombrarlos es seguro."""
    name = pair["name"]
    status, _, prefix = pair_state(name)
    if status != "ok" or prefix is None:
        return
    want = expected_prefix(pair, defaults)
    if prefix != want:
        rename_prefix(name, prefix, want)


TIP_RE = re.compile(r"^\s*(Path1|Path2):\s*(.+?)\s*$", re.MULTILINE)


def heal_listings(pair: dict, defaults: dict, logfile: Path) -> bool:
    """Red de seguridad por si nuestro cálculo del prefijo no coincidiera con el
    de rclone: se lee el nombre esperado del propio log ('Tip: here are the
    filenames...') y se renombra el juego de listados."""
    name = pair["name"]
    if not logfile.exists():
        return False
    text = logfile.read_text(encoding="utf-8", errors="replace")
    if "cannot find prior Path1 or Path2 listings" not in text:
        return False
    want = dict(TIP_RE.findall(text))
    if "Path1" not in want:
        return False
    expected = Path(want["Path1"])
    if not expected.name.endswith(".path1.lst"):
        return False
    new_prefix = expected.name[: -len(".path1.lst")]
    status, _, old_prefix = pair_state(name)
    if status != "ok" or old_prefix is None or old_prefix == new_prefix:
        return False
    if expected.parent.name != pair_workdir(name).name:  # paranoia
        return False
    rename_prefix(name, old_prefix, new_prefix)
    return True


def print_log_tail(lpath: Path | None, lines: int = LOG_TAIL_LINES) -> None:
    if lpath is None or not lpath.exists():
        return
    tail = lpath.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    print(f"--- últimas {len(tail)} líneas de {lpath.name} ---")
    for line in tail:
        print("  " + line)
    print("---")


def explain_failure(lpath: Path | None) -> None:
    if lpath is None or not lpath.exists():
        return
    text = lpath.read_text(encoding="utf-8", errors="replace")
    for needle, explanation in KNOWN_ERRORS:
        if needle in text:
            print(f"  >> {explanation}")
            return


# ---------------------------------------------------------------------------
# Construcción y ejecución de comandos
# ---------------------------------------------------------------------------

def flags_to_args(flags: dict) -> list[str]:
    """{nombre: valor} -> argumentos de rclone.

        clave = true          -> --clave
        clave = false / None  -> (se omite)
        clave = 4 / "texto"   -> --clave 4 / --clave texto
        clave = ["a", "b"]    -> --clave a --clave b
    """
    args: list[str] = []
    for key, value in flags.items():
        flag = "--" + str(key).replace("_", "-")
        if value is True:
            args.append(flag)
        elif value is False or value is None:
            continue
        elif isinstance(value, (list, tuple)):
            for item in value:
                args += [flag, str(item)]
        else:
            args += [flag, str(value)]
    return args


def build_filter_args(pair: dict, defaults: dict, ffile: Path | None) -> list[str]:
    """Con fichero de filtros no se emiten --include/--exclude: se duplicarían
    las reglas y bisync dejaría de poder detectar cambios de filtrado."""
    if ffile is not None:
        return ["--filters-file", str(ffile)]
    includes, excludes = filter_patterns(pair, defaults)
    args: list[str] = []
    for pat in includes:
        args += ["--include", pat]
    for pat in excludes:
        args += ["--exclude", pat]
    return args


def build_command(
    binary: str,
    pair: dict,
    defaults: dict,
    ffile: Path | None,
    need_resync: bool,
    dry_run: bool,
) -> tuple[list[str], Path]:
    """Flags fusionados en capas (de menor a mayor prioridad):
        1. BASE_FLAGS  2. MODE_DEFAULT_FLAGS[mode]  3. defaults.flags  4. pair.flags
    Para añadir un flag nuevo NO se toca esta función: se escribe en el TOML."""
    name = pair["name"]
    mode = pair.get("mode", "bisync")
    verb, src_kind, dst_kind = MODES[mode]
    ep = endpoints_for(pair, defaults)
    lpath = temp_log(name)

    flags: dict = {}
    flags.update(BASE_FLAGS)
    flags.update(MODE_DEFAULT_FLAGS.get(mode, {}))
    flags.update(defaults.get("flags", {}))
    flags.update(pair.get("flags", {}))

    # Gestionados por el script: dependen de la ejecución, no se configuran.
    flags["config"] = str(RCLONE_CONF)
    flags["log-file"] = str(lpath)
    if dry_run:
        flags["dry-run"] = True
    if mode == "bisync":
        flags["workdir"] = str(pair_workdir(name))
        if need_resync:
            flags["resync"] = True

    cmd = [binary, verb, ep[src_kind], ep[dst_kind]]
    cmd += build_filter_args(pair, defaults, ffile)
    cmd += flags_to_args(flags)
    cmd += list(defaults.get("extra_flags", [])) + list(pair.get("extra_flags", []))
    return cmd, lpath


def _execute(cmd: list[str], dry_run: bool, env: dict[str, str]) -> int:
    tag = " [DRY-RUN]" if dry_run else ""
    print(f"  ejecutando{tag}: " + " ".join(cmd))
    # cwd FIJO en rclone-sync/: rclone.conf usa rutas relativas (key_file,
    # known_hosts_file) para que el pen siga siendo portable, y esas rutas se
    # resuelven contra el directorio de trabajo. No se puede depender de quién
    # nos haya lanzado ni desde dónde.
    kwargs: dict = {"cwd": str(SCRIPT_DIR)}
    if os.name == "nt":
        # rclone es una app de consola: si este proceso corre sin consola
        # (pythonw, servicio), Windows le crearía UNA VENTANA NUEVA por cada
        # invocación. Su salida va al --log-file, así que no se pierde nada.
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return subprocess.run(cmd, env={**os.environ, **env}, **kwargs).returncode


def pair_needs_resync(pair: dict, defaults: dict) -> tuple[bool, list[str]]:
    """Motivos por los que esta pareja bisync necesita --resync."""
    reasons = []
    status, detail, _ = pair_state(pair["name"])
    if status != "ok":
        reasons.append(f"estado {status}: {detail}")
    fstate, fdetail = filters_state(filters_file_for(pair, defaults))
    if fstate != "ok":
        reasons.append(f"filtros {fstate}: {fdetail}")
    return bool(reasons), reasons


def run_pair(
    binary: str,
    pair: dict,
    defaults: dict,
    env: dict[str, str],
    force_resync: bool,
    resync_approved: bool,
    dry_run: bool,
    keep_logs: bool,
) -> int:
    name = pair["name"]
    mode = pair.get("mode", "bisync")
    if mode not in MODES:
        sys.exit(f"[{name}] modo inválido: '{mode}'. Válidos: {sorted(MODES)}")

    tag = " [DRY-RUN]" if dry_run else ""
    print(f"\n=== {name} ({mode}){tag} ===")

    local_path = local_abs(pair)
    need_resync = force_resync
    ffile = filters_file_for(pair, defaults)

    if mode == "bisync":
        migrate_legacy_state(pair, defaults)
        normalize_prefix(pair, defaults)
        status, detail, _ = pair_state(name)
        needed, reasons = pair_needs_resync(pair, defaults)
        print(f"  estado: {status} — {detail}")
        need_resync = force_resync or needed

        if need_resync and not resync_approved:
            for r in reasons:
                print(f"  requiere --resync -> {r}")
            print(f"[{name}] Saltada: requiere --resync y no está aprobado.")
            return SKIPPED

        # Si YA había baseline y la carpeta local no está, algo va mal (pen a
        # medio montar). Crearla vacía haría que bisync viese "han borrado todo".
        if status == "ok" and not local_path.exists():
            print(f"[{name}] ERROR: existe baseline pero la ruta local '{local_path}' "
                  f"no existe. Se aborta (no se crea vacía a propósito).")
            return 2

    if not local_path.exists():
        print(f"[{name}] La ruta local '{local_path}' no existe. Creándola...")
        local_path.mkdir(parents=True, exist_ok=True)

    cmd, lpath = build_command(binary, pair, defaults, ffile, need_resync, dry_run)
    rc = _execute(cmd, dry_run, env)

    # Un solo reintento, y solo si podemos reparar el estado con certeza.
    # El log del intento fallido se conserva aunque el reintento salga bien:
    # documenta por qué hubo que reparar nada.
    if rc != 0 and mode == "bisync" and not dry_run and heal_listings(pair, defaults, lpath):
        dispose_log(name, lpath, rc, keep_always=False)
        print(f"[{name}] Reintentando tras reparar los listados...")
        cmd, lpath = build_command(binary, pair, defaults, ffile, False, dry_run)
        rc = _execute(cmd, dry_run, env)

    saved = dispose_log(name, lpath, rc, keep_logs)
    if rc == 0:
        print(f"[{name}] OK." + (f" Log: {saved}" if saved else ""))
    else:
        print(f"[{name}] FALLÓ (código {rc}). Log: {saved}")
        print_log_tail(saved)
        explain_failure(saved)
    return rc


def resolve_resync_approval(selected: list[dict], defaults: dict, assume_yes: bool) -> bool:
    """Decide UNA vez si se aprueban los --resync auto-detectados."""
    need = []
    for p in selected:
        if p.get("mode", "bisync") != "bisync":
            continue
        migrate_legacy_state(p, defaults)
        normalize_prefix(p, defaults)
        needed, reasons = pair_needs_resync(p, defaults)
        if needed:
            need.append((p["name"], reasons))
    if not need:
        return False

    print("Parejas bisync que requieren --resync:")
    for n, reasons in need:
        for r in reasons:
            print(f"  - {n:<15} {r}")
    print("El --resync compara ambos lados y fija la referencia; no borra por diferencias.")

    if assume_yes:
        print("--yes: se ejecutará --resync en todas.")
        return True
    approved = ask_yes_no("¿Ejecutar --resync en TODAS ahora?")
    if not approved:
        print("De acuerdo, esas parejas se saltarán. (Usa --yes para automatizar.)")
    return approved


def doctor(all_pairs: list[dict], defaults: dict) -> int:
    pen = pen_remote_name(defaults)
    print(f"Pen detectado en: {PEN_ROOT}")
    print(f"Workdir de estado: {STATE_DIR}")
    if pen:
        for k, v in pen_environment(all_pairs, defaults).items():
            print(f"  {k}={v}")
    else:
        print("  (sin pen_remote: el lado local va como ruta absoluta, el nombre "
              "de los listados depende de la letra de unidad)")
    print()

    stray = sorted(STATE_DIR.glob("*.lst")) if STATE_DIR.exists() else []
    if stray:
        print(f"Aviso: {len(stray)} listado(s) sueltos en la raíz de state/ "
              f"(layout antiguo). Se migrarán al ejecutar.\n")

    problems = 0
    for p in all_pairs:
        name = p["name"]
        mode = p.get("mode", "bisync")
        ep = endpoints_for(p, defaults)
        local = local_abs(p)
        print(f"[{name}] {mode}")
        print(f"  local : {ep['local']} {'(OK)' if local.exists() else '(NO EXISTE)'}")
        print(f"  remoto: {ep['remote']}")
        if mode != "bisync":
            print()
            continue

        status, detail, prefix = pair_state(name)
        want = expected_prefix(p, defaults)
        print(f"  estado: {status} — {detail}")
        print(f"  prefijo esperado: {want}")
        if prefix and prefix != want:
            print("  AVISO: el baseline está guardado con otro prefijo; se renombrará "
                  "en la próxima ejecución.")
        fstate, fdetail = filters_state(filters_file_for(p, defaults))
        print(f"  filtros: {fstate} — {fdetail}")

        wd = pair_workdir(name)
        if wd.exists():
            for f in sorted(wd.iterdir()):
                if f.is_file():
                    ts = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                    print(f"    {f.name:<62} {ts}")
            if list(wd.glob("*.lck")):
                print("  AVISO: hay lock(s). Si no hay ninguna ejecución en curso, "
                      "bórralos o espera a que caduquen (--max-lock).")
        if status != "ok" or fstate != "ok" or not local.exists():
            problems += 1
        print()

    print("Sin incidencias." if not problems else f"{problems} pareja(s) requieren atención.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sincronización portable Synology <-> pen (rclone)."
    )
    parser.add_argument("pairs", nargs="*",
                        help="Nombres de parejas a sincronizar (por defecto: todas).")
    parser.add_argument("--list", action="store_true",
                        help="Lista las parejas configuradas y sale.")
    parser.add_argument("--doctor", action="store_true",
                        help="Diagnostica el estado de bisync y sale.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simula sin modificar nada.")
    parser.add_argument("--resync", action="store_true",
                        help="Rehace el baseline de bisync.")
    parser.add_argument("--keep-logs", action="store_true",
                        help="Conserva también el log de las ejecuciones correctas "
                             "(por defecto solo se guarda el de las que fallan).")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="Responde 'sí' a todo (p.ej. resincronizar parejas sin "
                             "baseline). Útil para automatizar sin interacción.")
    args = parser.parse_args()

    # logs/ se crea solo cuando hay algo que guardar (ver dispose_log).
    for d in (STATE_DIR, FILTERS_DIR):
        d.mkdir(parents=True, exist_ok=True)

    config = load_config()
    defaults = config.get("defaults", {})
    all_pairs = config.get("pair", [])
    if not all_pairs:
        sys.exit("El config no tiene ninguna [[pair]] definida.")

    if args.list:
        print("Parejas configuradas:")
        for p in all_pairs:
            ep = endpoints_for(p, defaults)
            print(f"  - {p['name']:<15} {p.get('mode', 'bisync'):<12} "
                  f"{ep['local']}  <->  {ep['remote']}")
        return 0

    if args.doctor:
        return doctor(all_pairs, defaults)

    if args.pairs:
        wanted = set(args.pairs)
        selected = [p for p in all_pairs if p["name"] in wanted]
        missing = wanted - {p["name"] for p in selected}
        if missing:
            sys.exit(f"No existen estas parejas en el config: {', '.join(sorted(missing))}")
    else:
        selected = all_pairs

    if not RCLONE_CONF.exists():
        sys.exit(f"No existe {RCLONE_CONF}. Crea la config de rclone con el remote SFTP.")

    binary = rclone_binary()
    env = pen_environment(all_pairs, defaults)
    keep_logs = args.keep_logs or bool(defaults.get("keep_logs", False))

    resync_approved = args.resync or resolve_resync_approval(selected, defaults, args.yes)

    ok = failures = skipped = 0
    for pair in selected:
        rc = run_pair(binary, pair, defaults, env, args.resync, resync_approved,
                      args.dry_run, keep_logs)
        if rc == SKIPPED:
            skipped += 1
        elif rc == 0:
            ok += 1
        else:
            failures += 1

    resumen = f"\nHecho. {ok}/{len(selected)} parejas OK"
    if skipped:
        resumen += f", {skipped} saltada(s)"
    if failures:
        resumen += f", {failures} con errores"
    print(resumen + ".")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())