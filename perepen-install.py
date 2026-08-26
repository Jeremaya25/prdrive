#!/usr/bin/env python3
"""
perepen-install.py — Instalador AUTÓNOMO de un pen PEREPEN nuevo desde el NAS.

Un único fichero, sin dependencias (solo stdlib, Python 3.11+). Se puede compartir
entre máquinas: no necesita un pen previo ni la copia maestra. Arranca el pen
completo directamente desde el Synology.

Qué hace (menú interactivo, o «instalación completa» de un tirón):
    1. Consigue rclone (lo busca; si no, lo descarga portable de rclone.org).
    2. Monta un remote SFTP efímero con la clave embebida (fichero temporal 0600).
    3. Descarga el catálogo de parejas del remote (pairs.toml).
    4. Formatea y etiqueta el dispositivo como PEREPEN (solo Windows).
    5. (Recordatorio) Cifras con BitLocker tú mismo y subes la clave de recuperación.
    6. Siembra el pen: down-mirror de /PJ/Perepen con las exclusiones de la pareja.
    7. Eliges qué parejas quieres y escribe el sync_config.toml del dispositivo.
    8. Inicializa esas parejas (--resync) usando el sync.py ya sembrado en el pen.

La creación de parejas nuevas en el catálogo NO está aquí: se hace desde un pen ya
provisionado, en runsync.py -> «Parejas…» -> bloque «Catálogo» (que usa la clave
completa del pen). Aquí el catálogo solo se lee.

Uso:
    python perepen-install.py            # menú interactivo
    python perepen-install.py --check    # solo comprueba rclone + conexión + catálogo
"""

from __future__ import annotations

import atexit
import base64
import getpass
import json
import os
import platform
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    sys.exit("Necesitas Python 3.11+ (tomllib).")

# =============================================================================
# Constantes embebidas (NO secretas salvo la clave privada, ver abajo)
# =============================================================================
NAS_HOST = "tictactoe.synology.me"
NAS_PORT = 22
NAS_USER = "Pereftp"
REMOTE_NAME = "synology"
MASTER_PATH = "/PJ/Perepen"                       # espejo maestro del pen en el NAS
CATALOG_PATH = "/PJ/Perepen-catalog/pairs.toml"   # catálogo global de parejas
PEN_LABEL = "PEREPEN"
CONTAINER_NAME = "PEREPEN.hc"      # contenedor VeraCrypt en la raíz del pen físico
RCLONE_BASE_URL = "https://downloads.rclone.org"

# known_hosts del NAS (claves públicas del host, NO son secreto: evitan el aviso TOFU).
KNOWN_HOSTS = """\
tictactoe.synology.me ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQChmXKQRN2LwkSEtTDChutIhkSiwsGuo7E1GBs2IMVZR2aTJ4kOH9RmCgdnwYOQIhbQqff6qDHQrNvKJcemk4GdsprZVALmzXTZ6+dJS3fhA3eQltQJnL5fh2+yR9N3hton/VAS4yVmLT7ZRy3O4NlIwzGaRXVQOBRwBFJAJWUehXDEMEPMEh1k2SXiUK0Qq1HhouIukkdOR5iDNivKDwEkEADiTfl/QCAhd8y/JbLH/swn2T/tJgSTNmj21NJ2UZs1wy8YFCq8QUPDQ50iMfT0ujrpGk5F7MPGQ3jUhtq/onqa/Mu9qwBHqMnNOGt/ho+fkg4zmZ4fqYmrNyMBRUmD
tictactoe.synology.me ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBBl1/bs8grGnIWrmUJST5swpExYyzhZKy7NHF+yydp/TYCV7O6L3n0xQO06sYQW+0Hdz8K+eYKojfm7POhAraVM=
tictactoe.synology.me ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMNgtdvqhyI9i01Qq0lrCuMMUZD/WpM+IPLILir8U60A
"""

# -----------------------------------------------------------------------------
# CLAVE PRIVADA SFTP (Pereftp), en base64.
#   ⚠ SECRETO. Quien tenga este fichero tiene acceso al NAS con esa clave.
#   Comparte este .py solo en privado. Si se filtra, ROTA la clave en el Synology.
# -----------------------------------------------------------------------------
PRIVATE_KEY_B64 = "LS0tLS1CRUdJTiBPUEVOU1NIIFBSSVZBVEUgS0VZLS0tLS0KYjNCbGJuTnphQzFyWlhrdGRqRUFBQUFBQkc1dmJtVUFBQUFFYm05dVpRQUFBQUFBQUFBQkFBQUFNd0FBQUF0emMyZ3RaVwpReU5UVXhPUUFBQUNCVXVEWUlnbE91NU5IS2VnT2p1UVl3WlluMDdBSUhCS2FyQWZqamFPUHFwd0FBQUppSjkvVFJpZmYwCjBRQUFBQXR6YzJndFpXUXlOVFV4T1FBQUFDQlV1RFlJZ2xPdTVOSEtlZ09qdVFZd1pZbjA3QUlIQkthckFmamphT1BxcHcKQUFBRUJudm5QYzM0NW0yM3JKT3hEUGpncFBZTmxJeGtJL0JscEY4ckhaUi8wY2tGUzROZ2lDVTY3azBjcDZBNk81QmpCbAppZlRzQWdjRXBxc0IrT05vNCtxbkFBQUFEM0pqYkc5dVpTMXplVzVqTFhCbGJnRUNBd1FGQmc9PQotLS0tLUVORCBPUEVOU1NIIFBSSVZBVEUgS0VZLS0tLS0K"

# Flags que replican la convención de sync.py (no lo importamos: este fichero es
# autónomo y corre antes de que exista ningún pen).
BASE_FLAGS = {"verbose": True, "create-empty-src-dirs": True}
DOWN_MIRROR_FLAGS = {"max-delete": 50}


# =============================================================================
# rclone: localizar o descargar el binario portable
# =============================================================================
def _os_arch() -> tuple[str, str]:
    """Devuelve (os, arch) con los nombres que usa rclone en sus zips."""
    sysname = {"windows": "windows", "darwin": "osx", "linux": "linux"}.get(
        platform.system().lower(), "linux"
    )
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64", "x64"}:
        arch = "amd64"
    elif machine.startswith("arm") or machine in {"aarch64", "arm64"}:
        arch = "arm64"
    elif machine in {"i386", "i686", "x86"}:
        arch = "386"
    else:
        arch = "amd64"
    return sysname, arch


def _cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    d = Path(base) / "perepen-install"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_rclone() -> str:
    """Ruta a un rclone ejecutable. Orden: junto al script -> PATH -> caché ->
    descarga portable de rclone.org."""
    exe = "rclone.exe" if os.name == "nt" else "rclone"
    here = Path(__file__).resolve().parent / exe
    if here.exists():
        return str(here)
    found = shutil.which("rclone")
    if found:
        return found

    cached = _cache_dir() / exe
    if cached.exists():
        return str(cached)

    sysname, arch = _os_arch()
    url = f"{RCLONE_BASE_URL}/rclone-current-{sysname}-{arch}.zip"
    print(f"rclone no encontrado; descargando portable:\n  {url}")
    tmp_zip = _cache_dir() / "rclone.zip"
    urllib.request.urlretrieve(url, tmp_zip)
    with zipfile.ZipFile(tmp_zip) as zf:
        member = next(m for m in zf.namelist() if m.endswith(exe))
        with zf.open(member) as src, open(cached, "wb") as dst:
            shutil.copyfileobj(src, dst)
    tmp_zip.unlink(missing_ok=True)
    if os.name != "nt":
        cached.chmod(cached.stat().st_mode | stat.S_IXUSR | stat.S_IRUSR)
    print(f"rclone listo: {cached}")
    return str(cached)


# =============================================================================
# Remote SFTP efímero (clave embebida -> ficheros temporales, borrados al salir)
# =============================================================================
_TMP_DIR: Path | None = None


def _cleanup_tmp() -> None:
    global _TMP_DIR
    if _TMP_DIR and _TMP_DIR.exists():
        shutil.rmtree(_TMP_DIR, ignore_errors=True)
    _TMP_DIR = None


def _install_cleanup_handlers() -> None:
    """Borra la clave temporal al salir: salida normal (atexit), Ctrl-C, y señales
    catchables (SIGTERM en Unix). Un kill DURO (SIGKILL, o TerminateProcess/kill en
    Windows) no se puede interceptar; para ese caso, el barrido de arranque de
    ephemeral_conf limpia las claves que hayan quedado de runs anteriores."""
    atexit.register(_cleanup_tmp)

    def _handler(signum, _frame):
        _cleanup_tmp()
        sys.exit(130 if signum == getattr(signal, "SIGINT", None) else 143)

    for name in ("SIGINT", "SIGTERM", "SIGBREAK", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                pass  # p.ej. no estamos en el hilo principal


def ephemeral_conf() -> str:
    """Escribe la clave + known_hosts + rclone.conf en un dir temporal y devuelve
    la ruta al rclone.conf. Todo se borra al salir (atexit)."""
    global _TMP_DIR
    if PRIVATE_KEY_B64.startswith("__INJECT"):
        sys.exit(
            "La clave privada no está embebida en este fichero. "
            "Inyecta PRIVATE_KEY_B64 antes de usar el instalador."
        )
    # Barrido de arranque: borra claves de runs anteriores que murieron de forma
    # brusca (kill duro en Windows, SIGKILL...), donde atexit/señales no llegan a
    # correr. Prefijo propio para NO tocar los puntos de montaje 'perepen-mnt-*'.
    base = Path(tempfile.gettempdir())
    for stale in base.glob("perepen-key-*"):
        shutil.rmtree(stale, ignore_errors=True)

    _TMP_DIR = Path(tempfile.mkdtemp(prefix="perepen-key-", dir=base))
    _install_cleanup_handlers()

    key_path = _TMP_DIR / "id_ed25519"
    key_path.write_bytes(base64.b64decode(PRIVATE_KEY_B64))
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass  # Windows: los permisos POSIX no aplican; el dir temp ya es del usuario.

    known_path = _TMP_DIR / "known_hosts"
    known_path.write_text(KNOWN_HOSTS, encoding="utf-8")

    conf_path = _TMP_DIR / "rclone.conf"
    conf_path.write_text(
        f"[{REMOTE_NAME}]\n"
        "type = sftp\n"
        f"host = {NAS_HOST}\n"
        f"port = {NAS_PORT}\n"
        f"user = {NAS_USER}\n"
        f"key_file = {key_path}\n"
        f"known_hosts_file = {known_path}\n"
        "disable_hashcheck = true\n"
        "shell_type = none\n",
        encoding="utf-8",
    )
    return str(conf_path)


def rclone(binary: str, conf: str, *args: str, capture: bool = False) -> subprocess.CompletedProcess:
    cmd = [binary, "--config", conf, *args]
    return subprocess.run(cmd, text=True, encoding="utf-8", errors="replace", capture_output=capture)


# =============================================================================
# Catálogo de parejas (pairs.toml en el remote)
# =============================================================================
def pull_catalog(binary: str, conf: str) -> dict:
    res = rclone(binary, conf, "cat", f"{REMOTE_NAME}:{CATALOG_PATH}", capture=True)
    if res.returncode != 0:
        sys.exit(f"No pude leer el catálogo {CATALOG_PATH}:\n{res.stderr}")
    return tomllib.loads(res.stdout)


def find_pair(catalog: dict, name: str) -> dict | None:
    for p in catalog.get("pair", []):
        if p.get("name") == name:
            return p
    return None


# =============================================================================
# Flags / filtros (misma convención que sync.py)
# =============================================================================
def flags_to_args(flags: dict) -> list[str]:
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


def build_filters(defaults: dict, pair: dict) -> list[str]:
    args: list[str] = []
    for pat in list(defaults.get("include", [])) + list(pair.get("include", [])):
        args += ["--include", pat]
    for pat in list(defaults.get("exclude", [])) + list(pair.get("exclude", [])):
        args += ["--exclude", pat]
    return args


# =============================================================================
# Emisor TOML mínimo (para el sync_config.toml del dispositivo)
# =============================================================================
def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _emit_table(d: dict, skip: set[str]) -> list[str]:
    return [f"{k} = {_toml_value(v)}" for k, v in d.items() if k not in skip and not isinstance(v, dict)]


def emit_config(defaults: dict, pairs: list[dict]) -> str:
    lines = [
        "# Generado por perepen-install.py — config de ESTE dispositivo.",
        "# El catálogo global vive en el remote (pairs.toml).",
        "",
        "[defaults]",
    ]
    lines += _emit_table(defaults, skip={"flags"})
    if defaults.get("flags"):
        lines += ["", "[defaults.flags]"]
        lines += _emit_table(defaults["flags"], skip=set())
    for p in pairs:
        lines += ["", "[[pair]]"]
        # Orden legible: name, local, remote_path, mode y luego el resto.
        order = ["name", "local", "remote_path", "mode", "remote", "include", "exclude"]
        for k in order:
            if k in p and not isinstance(p[k], dict):
                lines.append(f"{k} = {_toml_value(p[k])}")
        for k, v in p.items():
            if k not in order and k != "flags" and not isinstance(v, dict):
                lines.append(f"{k} = {_toml_value(v)}")
        if p.get("flags"):
            lines += ["", "[pair.flags]"]
            lines += _emit_table(p["flags"], skip=set())
    return "\n".join(lines) + "\n"


# =============================================================================
# Formateo + etiqueta (SOLO Windows)
# =============================================================================
def _ps(script: str, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        text=True, encoding="utf-8", errors="replace", capture_output=capture,
    )


def list_removable() -> list[dict]:
    res = _ps(
        "Get-Volume | Where-Object { $_.DriveType -eq 'Removable' -and $_.DriveLetter } | "
        "Select-Object DriveLetter, FileSystemLabel, FileSystem, Size | ConvertTo-Json -Compress"
    )
    out = (res.stdout or "").strip()
    if not out:
        return []
    data = json.loads(out)
    return [data] if isinstance(data, dict) else data


def choose_drive() -> str | None:
    """Elige una unidad extraíble (Windows) y devuelve su letra (p.ej. 'E')."""
    drives = list_removable()
    if not drives:
        print("No hay unidades EXTRAÍBLES conectadas.")
        return None
    print("\nUnidades extraíbles detectadas:")
    for i, d in enumerate(drives, 1):
        gb = round((d.get("Size") or 0) / 1024**3, 1)
        print(f"  {i}) {d['DriveLetter']}:  «{d.get('FileSystemLabel') or ''}»  "
              f"{d.get('FileSystem') or '?'}  {gb} GB")
    sel = input("Nº de unidad (Enter para cancelar): ").strip()
    if not sel.isdigit() or not (1 <= int(sel) <= len(drives)):
        return None
    return drives[int(sel) - 1]["DriveLetter"]


def choose_physical_pen() -> Path | None:
    """Ruta raíz del pen FÍSICO (exFAT), donde vivirá el contenedor .hc o los datos."""
    if os.name != "nt":
        p = input("Ruta de montaje del pen físico (p.ej. /media/USB), Enter cancela: ").strip()
        return Path(p) if p and Path(p).exists() else None
    letter = choose_drive()
    return Path(f"{letter}:\\") if letter else None


def format_volume(letter: str, fs: str, label: str) -> bool:
    """Formatea (Windows) la unidad `letter` como `fs` con etiqueta `label`. Destructivo."""
    print(f"\n⚠  Se BORRARÁ TODO en {letter}: y se formateará como {fs} con etiqueta {label}.")
    if input(f"Escribe la letra '{letter}' para confirmar: ").strip().upper() != letter.upper():
        print("Cancelado.")
        return False
    res = _ps(
        f"Format-Volume -DriveLetter {letter} -FileSystem {fs} "
        f"-NewFileSystemLabel {label} -Force -Confirm:$false",
        capture=True,
    )
    if res.returncode != 0:
        print(f"Falló el formateo:\n{res.stdout}\n{res.stderr}")
        return False
    print(f"Formateado y etiquetado {letter}: como {label}.")
    return True


# =============================================================================
# Cifrado VeraCrypt — contenedor .hc portable (Windows / macOS / Linux)
# =============================================================================
def _first_exe(candidates: list[str]) -> str | None:
    for c in candidates:
        if os.sep in c or (os.altsep and os.altsep in c):
            if Path(c).exists():
                return c
        else:
            found = shutil.which(c)
            if found:
                return found
    return None


def find_veracrypt() -> dict | None:
    """Localiza VeraCrypt. En Windows devuelve {'mount','format'} (dos .exe distintos);
    en macOS/Linux ambos apuntan al mismo binario `veracrypt --text`."""
    if os.name == "nt":
        mount = _first_exe(["VeraCrypt.exe", r"C:\Program Files\VeraCrypt\VeraCrypt.exe"])
        fmt = _first_exe(["VeraCrypt Format.exe", r"C:\Program Files\VeraCrypt\VeraCrypt Format.exe"])
        if mount and fmt:
            return {"mount": mount, "format": fmt}
        d = input("No encuentro VeraCrypt. Carpeta de instalación (Enter cancela): ").strip()
        if d:
            m, f = Path(d) / "VeraCrypt.exe", Path(d) / "VeraCrypt Format.exe"
            if m.exists() and f.exists():
                return {"mount": str(m), "format": str(f)}
        print("VeraCrypt no disponible.")
        return None
    vc = _first_exe([
        "veracrypt", "/usr/bin/veracrypt", "/usr/local/bin/veracrypt",
        "/Applications/VeraCrypt.app/Contents/MacOS/VeraCrypt",
    ])
    if not vc:
        vc = input("No encuentro 'veracrypt'. Ruta al binario (Enter cancela): ").strip() or None
        if not vc or not Path(vc).exists():
            print("VeraCrypt no disponible.")
            return None
    return {"mount": vc, "format": vc}


def prompt_passphrase() -> str | None:
    """Pide la passphrase dos veces (no se guarda en ningún sitio: apúntala en KeePass)."""
    while True:
        p1 = getpass.getpass("Passphrase VeraCrypt (no se muestra): ")
        if not p1:
            return None
        if p1 == getpass.getpass("Repite la passphrase: "):
            return p1
        print("No coinciden; reinténtalo.")


def _size_to_bytes(raw: str, pen_root: Path) -> int:
    """Convierte '20G'/'500M'/'max' a bytes (para el --size de Linux/macOS)."""
    free = shutil.disk_usage(str(pen_root)).free
    raw = raw.strip().lower()
    if raw in {"max", ""}:
        return free - 50 * 1024**2  # deja un pequeño margen
    units = {"k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}
    if raw[-1] in units:
        return int(float(raw[:-1]) * units[raw[-1]])
    return int(raw)


def prompt_container_size(pen_root: Path) -> str:
    free_gib = shutil.disk_usage(str(pen_root)).free / 1024**3
    default = f"{max(1, int(free_gib) - 1)}G"
    print(f"Espacio libre en el pen: {free_gib:.1f} GiB.")
    return input(f"Tamaño del contenedor [{default}] (o 'max'): ").strip() or default


def _free_drive_letter() -> str:
    res = _ps("(68..90 | ForEach-Object {[char]$_}) | "
              "Where-Object { -not (Test-Path ($_ + ':\\')) } | Select-Object -First 1")
    return (res.stdout or "").strip() or "V"


def vc_create_container(vc: dict, container: Path, size: str, password: str, fs: str, pen_root: Path) -> int:
    """Crea un contenedor VeraCrypt (AES/SHA-512) formateado con `fs`."""
    print("\nCreando el contenedor VeraCrypt (según el tamaño, puede tardar)...")
    if os.name == "nt":
        cmd = [vc["format"], "/create", str(container), "/size", size, "/password", password,
               "/encryption", "AES", "/hash", "sha512", "/filesystem", fs,
               "/pim", "0", "/quick", "/silent", "/force"]
    else:
        # Nota: --quick no aplica a contenedores-fichero (solo device-hosted); no se pasa.
        cmd = [vc["format"], "--text", "--create", str(container), "--volume-type=normal",
               f"--size={_size_to_bytes(size, pen_root)}", f"--password={password}",
               "--encryption=AES", "--hash=sha512", f"--filesystem={fs}",
               "--pim=0", "--keyfiles=", "--random-source=/dev/urandom", "--non-interactive"]
    return subprocess.run(cmd).returncode


def vc_mount(vc: dict, container: Path, password: str) -> tuple[int, Path | None]:
    """Monta el contenedor y devuelve (rc, ruta_montaje). Requiere admin/root."""
    if os.name == "nt":
        letter = _free_drive_letter()
        cmd = [vc["mount"], "/volume", str(container), "/letter", letter,
               "/password", password, "/pim", "0", "/quit", "/silent"]
        rc = subprocess.run(cmd).returncode
        return rc, (Path(f"{letter}:\\") if rc == 0 else None)
    mnt = Path(tempfile.mkdtemp(prefix="perepen-mnt-"))
    cmd = [vc["mount"], "--text", str(container), str(mnt), f"--password={password}",
           "--pim=0", "--keyfiles=", "--protect-hidden=no", "--non-interactive"]
    rc = subprocess.run(cmd).returncode
    return rc, (mnt if rc == 0 else None)


def vc_dismount(vc: dict, mount_loc: Path) -> int:
    if os.name == "nt":
        return subprocess.run([vc["mount"], "/dismount", str(mount_loc)[0], "/quit", "/silent"]).returncode
    return subprocess.run([vc["mount"], "--text", "--dismount", str(mount_loc), "--non-interactive"]).returncode


# =============================================================================
# Preparar el dispositivo (formato + cifrado) -> deja el pen_root listo
# =============================================================================
def prepare_device(state: dict) -> Path | None:
    """Formatea y (opcionalmente) cifra con VeraCrypt. Devuelve el pen_root a sembrar."""
    pen = choose_physical_pen()
    if not pen:
        return None

    print("\nCifrado:  1) Ninguno   2) BitLocker (manual, Windows)   3) VeraCrypt (contenedor .hc, automático)")
    enc = input("Elige [3]: ").strip() or "3"

    # Formateo del pen físico (solo Windows; en otros SO se asume ya formateado).
    if os.name == "nt":
        fs = input("Sistema de ficheros del pen [exFAT] / NTFS / FAT32: ").strip() or "exFAT"
        if not format_volume(str(pen)[0], fs, PEN_LABEL):
            return None
    else:
        print("(En macOS/Linux se asume el pen ya formateado y montado.)")

    if enc == "2":  # BitLocker manual
        print("\nRecordatorio: cifra ahora el pen con BitLocker y guarda la clave de "
              "recuperación en el remote (_bitlockers). Este instalador no lo hace por ti.")
        input("Pulsa Enter cuando el pen esté montado y desbloqueado...")
        state["pen_root"] = pen
        return pen

    if enc == "3":  # VeraCrypt (contenedor .hc)
        vc = find_veracrypt()
        if not vc:
            return None
        container = pen / CONTAINER_NAME
        size = prompt_container_size(pen)
        cfs = input("Sistema de ficheros DENTRO del contenedor [exFAT] / NTFS / FAT: ").strip() or "exFAT"
        password = prompt_passphrase()
        if not password:
            print("Cancelado (sin passphrase).")
            return None
        if vc_create_container(vc, container, size, password, cfs, pen) != 0:
            print("Falló la creación del contenedor VeraCrypt.")
            return None
        print("Contenedor creado. Montando (puede pedir permisos de admin/root)...")
        rc, mount_loc = vc_mount(vc, container, password)
        if rc != 0 or not mount_loc:
            print("Falló el montaje del contenedor.")
            return None
        print(f"Contenedor montado en {mount_loc}. Los datos PEREPEN viven aquí dentro.")
        state["veracrypt"] = vc
        state["vc_mount"] = mount_loc
        state["pen_root"] = mount_loc
        return mount_loc

    # enc == "1": sin cifrado
    state["pen_root"] = pen
    return pen


def mount_existing(state: dict) -> Path | None:
    """Monta un PEREPEN.hc ya existente para poder sembrar/inicializar por separado."""
    vc = state.get("veracrypt") or find_veracrypt()
    if not vc:
        return None
    pen = choose_physical_pen()
    if not pen:
        return None
    container = pen / CONTAINER_NAME
    if not container.exists():
        print(f"No existe {container}.")
        return None
    password = getpass.getpass("Passphrase VeraCrypt: ")
    rc, mount_loc = vc_mount(vc, container, password)
    if rc != 0 or not mount_loc:
        print("Falló el montaje.")
        return None
    print(f"Montado en {mount_loc}.")
    state["veracrypt"] = vc
    state["vc_mount"] = mount_loc
    state["pen_root"] = mount_loc
    return mount_loc


# =============================================================================
# Sembrado (down-mirror) e inicialización de parejas
# =============================================================================
def seed(binary: str, conf: str, pen_root: Path, catalog: dict, dry_run: bool) -> int:
    perepen = find_pair(catalog, "perepen")
    if not perepen:
        sys.exit("El catálogo no tiene la pareja 'perepen'.")
    defaults = catalog.get("defaults", {})

    flags: dict = {}
    flags.update(BASE_FLAGS)
    flags.update(DOWN_MIRROR_FLAGS)
    flags.update(defaults.get("flags", {}))
    flags.update(perepen.get("flags", {}))
    if dry_run:
        flags["dry-run"] = True

    cmd = ["sync", f"{REMOTE_NAME}:{MASTER_PATH}", str(pen_root)]
    cmd += build_filters(defaults, perepen)
    cmd += flags_to_args(flags)
    print(f"\n$ rclone --config <tmp> {' '.join(cmd)}")
    return rclone(binary, conf, *cmd).returncode


def select_pairs(catalog: dict) -> list[dict]:
    pairs = catalog.get("pair", [])
    print("\nParejas disponibles en el catálogo:")
    for i, p in enumerate(pairs, 1):
        print(f"  {i}) {p['name']:<12} {p.get('mode', 'bisync'):<12} "
              f"{p.get('local', '?')}  <->  {p.get('remote_path', '?')}")
    raw = input("Nºs separados por coma, o 'all' (Enter = ninguna): ").strip().lower()
    if not raw:
        return []
    if raw == "all":
        return list(pairs)
    idx = {int(x) for x in raw.replace(" ", "").split(",") if x.isdigit()}
    return [p for i, p in enumerate(pairs, 1) if i in idx]


def write_device_config(pen_root: Path, catalog: dict, selected: list[dict]) -> None:
    cfg_dir = pen_root / "rclone-sync"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    text = emit_config(catalog.get("defaults", {}), selected)
    (cfg_dir / "sync_config.toml").write_text(text, encoding="utf-8")
    print(f"Escrito {cfg_dir / 'sync_config.toml'} con {len(selected)} pareja(s).")


def init_pairs(pen_root: Path, selected: list[dict]) -> int:
    sync_dir = pen_root / "rclone-sync"
    sync_py = sync_dir / "sync.py"
    if not sync_py.exists():
        print(f"No encuentro {sync_py}. ¿Has sembrado el pen (paso de down-mirror)?")
        return 1
    for p in selected:  # crea las carpetas locales de cada pareja seleccionada
        (pen_root / p["local"]).mkdir(parents=True, exist_ok=True)
    names = [p["name"] for p in selected]
    cmd = [sys.executable, str(sync_py), *names, "--resync"]
    print(f"\n$ (cwd={sync_dir}) {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=str(sync_dir)).returncode


# =============================================================================
# Menú
# =============================================================================
def _yes(prompt: str) -> bool:
    return input(prompt).strip().lower() in {"s", "si", "sí", "y", "yes"}


def full_install(binary: str, conf: str, catalog: dict, state: dict) -> None:
    pen_root = prepare_device(state)
    if not pen_root:
        return

    print("\n== Siembra (dry-run) ==")
    if seed(binary, conf, pen_root, catalog, dry_run=True) != 0:
        print("El dry-run falló; reviso la conexión antes de seguir.")
        return
    if not _yes("¿Ejecutar la siembra REAL? [s/N] "):
        return
    if seed(binary, conf, pen_root, catalog, dry_run=False) != 0:
        print("La siembra falló.")
        return

    selected = select_pairs(catalog)
    write_device_config(pen_root, catalog, selected)
    if selected and _yes("¿Inicializar las parejas ahora (--resync)? [s/N] "):
        init_pairs(pen_root, selected)

    if state.get("vc_mount") and _yes("¿Desmontar el contenedor VeraCrypt ahora? [s/N] "):
        vc_dismount(state["veracrypt"], state["vc_mount"])
        state.pop("vc_mount", None)
    print("\n✔ Instalación completa.")


def ensure_pen_root(state: dict) -> Path | None:
    """Pen ya listo. Si no hay ninguno, ofrece montar un contenedor o dar una ruta/letra."""
    if state.get("pen_root"):
        return state["pen_root"]
    if _yes("¿Montar un contenedor PEREPEN.hc existente? [s/N] "):
        return mount_existing(state)
    if os.name == "nt":
        letter = input("Letra de unidad del pen ya montado (p.ej. E): ").strip().rstrip(":").upper()
        state["pen_root"] = Path(f"{letter}:\\") if letter else None
    else:
        p = input("Ruta del pen ya montado: ").strip()
        state["pen_root"] = Path(p) if p else None
    return state.get("pen_root")


def menu(binary: str, conf: str, catalog: dict) -> None:
    state: dict = {}
    actions = ("1) Preparar dispositivo (formato + cifrado)   2) Sembrar   "
               "3) Elegir parejas+config   4) Inicializar\n"
               "5) Instalación completa   6) Montar contenedor   7) Desmontar   0) Salir")
    while True:
        pen = state.get("pen_root") or "(sin elegir)"
        print(f"\n=== Instalador PEREPEN ===   pen: {pen}\n{actions}")
        choice = input("> ").strip()
        if choice == "0":
            return
        elif choice == "1":
            prepare_device(state)
        elif choice == "2":
            pen_root = ensure_pen_root(state)
            if pen_root:
                seed(binary, conf, pen_root, catalog, dry_run=True)
                if _yes("¿Siembra REAL? [s/N] "):
                    seed(binary, conf, pen_root, catalog, dry_run=False)
        elif choice == "3":
            pen_root = ensure_pen_root(state)
            if pen_root:
                write_device_config(pen_root, catalog, select_pairs(catalog))
        elif choice == "4":
            pen_root = ensure_pen_root(state)
            if pen_root:
                sel = select_pairs(catalog)
                if sel:
                    init_pairs(pen_root, sel)
        elif choice == "5":
            full_install(binary, conf, catalog, state)
        elif choice == "6":
            mount_existing(state)
        elif choice == "7":
            if state.get("vc_mount"):
                vc_dismount(state["veracrypt"], state["vc_mount"])
                state.pop("vc_mount", None)
                state.pop("pen_root", None)
            else:
                print("No hay contenedor montado por este instalador.")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # UI en español con acentos
        except Exception:
            pass
    binary = ensure_rclone()
    conf = ephemeral_conf()
    if "--check" in sys.argv:
        catalog = pull_catalog(binary, conf)
        pairs = [p["name"] for p in catalog.get("pair", [])]
        print(f"OK. rclone: {binary}")
        print(f"Conexión al NAS y catálogo OK. Parejas: {', '.join(pairs)}")
        return 0
    catalog = pull_catalog(binary, conf)
    print(f"Catálogo cargado: {len(catalog.get('pair', []))} parejas.")
    try:
        menu(binary, conf, catalog)
    except (KeyboardInterrupt, EOFError):
        print("\nCancelado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
