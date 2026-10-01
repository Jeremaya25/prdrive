#!/usr/bin/env python3
"""Vigilante de arranque automático: lanza `runsync.py` al conectar el dispositivo.

Se instala EN EL EQUIPO (no en el dispositivo), detecta en qué unidad se ha
montado el dispositivo y lanza `runsync.py` en cuanto es legible. Sin permisos
de administrador: tarea programada de usuario en Windows, servicio de usuario
de systemd en Linux (autostart XDG si no hay systemd).

    python penwatch.py install [--mode ui|sync|daemon] [--poll N]
                               [--extra-root RUTA]
    python penwatch.py uninstall     # quita la tarea/servicio y el vigilante
    python penwatch.py status        # qué hay instalado y si ve el dispositivo
    python penwatch.py probe         # solo detección: dónde busca y qué encuentra
    python penwatch.py run [--once]  # el bucle del vigilante (lo llama la tarea)

Cómo reconoce el dispositivo: por el fichero de control `.prdrive/PRDRIVE`. Ni
la letra ni el punto de montaje sirven: cambian de equipo a equipo y de un día
a otro. El fichero puede llevar una línea `id=<hex>` (`install` la escribe si
no existía o estaba vacío) y entonces se exige que el id coincida, para no
confundirlo con otro USB que también llevara un PRDRIVE. Antes de lanzar nada
se comprueba que esté `.prdrive/runsync.py`. Va dentro de `.prdrive/` para no
dejar un fichero suelto entre los datos del usuario: da igual dónde esté
mientras la ruta sea relativa a la raíz.

Con VeraCrypt, `.prdrive/` está DENTRO del contenedor y hasta abrirlo no hay
nada que ver. Fuera queda el vestíbulo (`common/vestibulo.py`), con una marca
que lleva el mismo id: con ella el vigilante reconoce el dispositivo cerrado y
le pide a VeraCrypt que lo abra (VeraCrypt pide la contraseña en su ventana),
una vez por conexión. Cuando el volumen aparece montado se sigue como siempre.
En Linux sin VeraCrypt no lo abre él (udisks2 y cryptsetup piden la contraseña
por una terminal): lo apunta en el diario, y si alguien lo abre con
`abrir-prdrive.sh` lo encuentra montado y sigue igual.

Por qué sondea y no espera un evento del sistema: el volumen cifrado no se
puede leer hasta desbloquearlo (BitLocker/LUKS), y eso tarda lo que tarde la
persona en teclear la contraseña. El evento útil no es «ha llegado» sino «ya se
lee», y eso solo se sabe intentándolo. Sondear un marcador cuesta un `stat`
cada pocos segundos, funciona igual en los dos sistemas y da lo mismo que el
dispositivo estuviera puesto desde el arranque o se enchufe a media sesión.

Permanencia: se registra para el USUARIO que ejecuta `install` y arranca solo
en cada inicio de sesión, así que sobrevive a reinicios y apagados. En Windows
es una tarea con disparador de inicio de sesión; en Linux, una unidad de
usuario con `WantedBy=default.target` (más `loginctl enable-linger`, que
`install` intenta activar, para que vigile también sin sesión abierta).

Convivencia con un medio que puede desaparecer a media frase:
- Nunca escribe en el dispositivo ni se mete dentro (ni cwd ni ficheros
  abiertos): bloquearía la extracción segura. Su configuración, su estado y su
  diario viven en el equipo.
- Toda lectura del dispositivo va en `try/except OSError`: un volumen cifrado y
  bloqueado, o retirado en mitad de la llamada, responde con error, no con un
  educado «no existe».
- Solo lanza runsync cuando el marcador se ha leído bien en dos sondeos
  seguidos, para no arrancar sobre un montaje a medias.
- Nada se relanza mientras el dispositivo siga puesto: hace falta que
  desaparezca para volver a armar el disparo.

Su propio Python: no depende de un Python instalado en el equipo. `install`
copia el Python que lleva el dispositivo para esta plataforma a `runtime/<id>/`
y registra la tarea con esa copia: así sigue funcionando cuando alguien
actualiza o desinstala su Python, que antes lo rompía en silencio (se guardaba
el `sys.executable`). Cada versión va en su carpeta, con el `id` sacado del
sello del runtime. En cada detección se compara el sello del dispositivo con el
de la copia y, si difieren, se copia la nueva AL LADO y se cambia el puntero de
`watch.json` de una vez: sustituir la carpeta en su sitio no se puede, porque
en Windows no se renombra la carpeta de un `pythonw.exe` que corre (y el
vigilante corre justo desde ahí). Luego se vuelve a registrar la tarea y se
recogen las viejas. Si el dispositivo no lleva Python para este equipo
(instalación ligera) se usa el del sistema y `status` lo dice.

Modos (`--mode`, se decide al instalar y se guarda en el equipo):

    ui      (por defecto) abre la UI de runsync.py: tú decides qué hacer.
    sync    una pasada del servicio, en silencio, y nada más (runsync --auto --once).
    daemon  arranca el servicio periódico (runsync --auto).

Qué parejas y cada cuánto NO se decide aquí: son los del servicio, que viven en
el dispositivo y se eligen en su ventana. El vigilante no lee configuración del
dispositivo: lanza runsync sin ellos y runsync los lee allí. Así el servicio es
uno solo, se arranque a mano o al enchufar, y el intervalo que se ve en la
ventana es el que se usa. En los tres modos, una pareja bisync que necesite
`--resync` se SALTA: un resync no se lanza solo.

La copia que corre en el equipo es la que hizo `install` y NADA la pone al día
sola: `refresh_runtime()` refresca el Python, no este fichero. `copia_al_dia()`
la compara con la del dispositivo, y `status` (y la ventana) lo dicen cuando no
coinciden: reinstalar es lo que la pone al día.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

APP_NAME = "prdrive"
"""Nombre de la marca.

Copia de `common/__init__.py`, la única consentida: penwatch se copia al equipo
y tiene que arrancar con el dispositivo desconectado, así que no puede importar
nada del proyecto. Un test comprueba que las dos copias no se separan.
"""
APP = "PrDriveWatch"
"""Nombre del vigilante en el equipo (su carpeta en Windows y su tarea)."""
TASK_NAME = APP
"""Windows: nombre de la tarea programada."""
UNIT_NAME = f"{APP_NAME}-watch.service"
"""Linux: nombre de la unidad de usuario de systemd."""

SCRIPT_DIR = Path(__file__).resolve().parent
APP_SUBDIR = f".{APP_NAME}"
"""Carpeta oculta del código, en la raíz del dispositivo."""
STRUCT_MARKER = Path(APP_SUBDIR) / "runsync.py"
"""Lo que se va a lanzar: si no está, la unidad no es este proyecto."""
CONTROL_FILE = Path(APP_SUBDIR) / APP_NAME.upper()
"""Fichero de control: dice quién es esta unidad."""
CONTAINER_FILE = f"{APP_NAME.upper()}.hc"
"""Contenedor VeraCrypt del dispositivo, en su raíz física.

Es copia de `common/vestibulo.py`, con su test, igual que `VESTIBULE_MARKER`,
las `TRAVELER_*`, `OPEN_SCRIPT` y `UDISKS_TCRYPT_CONF`.
"""
VESTIBULE_MARKER = f".{APP_NAME}-vestibulo"
"""Marca oculta del vestíbulo, fuera del contenedor; lleva el mismo `id=`."""
TRAVELER_DIR = "VeraCrypt"
"""Carpeta del VeraCrypt que viaja junto al contenedor."""
TRAVELER_EXE = "VeraCrypt.exe"
"""El `VeraCrypt.exe` de los dispositivos de antes."""
TRAVELER_PORTABLE = "VeraCrypt-{arq}.exe"
"""Nombre del portable oficial: un ejecutable por arquitectura."""
TRAVELER_ARCHS = ("x64", "arm64")
"""Arquitecturas para las que viaja el portable."""
OPEN_SCRIPT = f"abrir-{APP_NAME}.sh"
"""Script del vestíbulo que abre el contenedor con udisks2 o cryptsetup."""
UDISKS_TCRYPT_CONF = Path("/etc/udisks2/tcrypt.conf")
"""Fichero sin el que udisks2 no reconoce un contenedor VeraCrypt.

Lo mira al arrancar el servicio (`src/main.c` de udisks).
"""
RUNTIME_SUBDIR = Path(APP_SUBDIR) / "runtime"
"""Carpeta de los Python del dispositivo, uno por plataforma.

Copiada de `install/runtime_bin.py`, con su test, igual que `RUNTIME_STAMP`.
"""
RUNTIME_STAMP = "PRDRIVE-RUNTIME"
"""Sello de versión de cada runtime."""
UI_LOCK_REL = Path(APP_SUBDIR) / "state" / "ui.lock.json"
"""Registro de la ventana abierta de runsync.

Copiado de `runsync.py`, con su test, igual que `DAEMON_LOCK_REL`. Se LEE para
no lanzar una segunda instancia encima y nunca se escribe: desde aquí nadie
escribe en el dispositivo.
"""
DAEMON_LOCK_REL = Path(APP_SUBDIR) / "state" / "daemon.lock.json"
"""Registro del servicio de runsync."""
HOST = socket.gethostname()
"""Nombre de este equipo; el mismo que apunta `ui/prefs.py`."""

POLL_SECONDS = 5.0
"""Segundos entre sondeos del dispositivo."""
STABLE_CHECKS = 2
"""Sondeos seguidos legibles antes de dar el dispositivo por montado."""
STOP_WAIT_SECONDS = 8.0
"""Segundos que `stop` espera a que pare el vigilante."""
LOG_MAX_BYTES = 256 * 1024
"""Tamaño del diario a partir del cual `log` lo recorta."""
LOG_KEEP_LINES = 400
"""Líneas con las que se queda el diario al recortarlo."""

IS_WIN = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000
"""Flag de creación de procesos de Windows: sin consola."""
CREATE_NEW_PROCESS_GROUP = 0x00000200
"""Flag de creación de procesos de Windows: grupo propio."""

CONTROL_TEMPLATE = """\
# PRDRIVE — fichero de control del dispositivo. NO LO BORRES.
# Es lo que permite reconocer esta unidad se monte donde se monte (F:, /media/...).
# Lo usa .prdrive/penwatch.py para lanzar la sincronización al conectarla.
id={device_id}
"""
"""Contenido del fichero de control; `device_id` es el `id=` que lo ata al vestíbulo."""


def host_dir() -> Path:
    """Devuelve dónde vive el vigilante en el equipo: por usuario, sin privilegios."""
    if IS_WIN:
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / APP
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / f"{APP_NAME}-watch"


HOST_DIR = host_dir()
"""Carpeta del vigilante en el equipo: su configuración, estado, diario y Python."""
CONFIG_FILE = HOST_DIR / "watch.json"
"""`watch.json`: la configuración con la que se instaló."""
STATE_FILE = HOST_DIR / "state.json"
"""Estado del vigilante entre sondeos (qué ha lanzado y qué ha visto)."""
LOG_FILE = HOST_DIR / "penwatch.log"
STOP_FILE = HOST_DIR / "stop"
"""Fichero que, si existe, le pide al vigilante que pare."""
SELF_COPY = HOST_DIR / "penwatch.py"
"""La copia de este script que corre en el equipo."""
RUNTIMES_DIR = HOST_DIR / "runtime"
"""Copias del Python del dispositivo, una carpeta por versión."""
UNIT_FILE = Path.home() / ".config" / "systemd" / "user" / UNIT_NAME
DESKTOP_FILE = Path.home() / ".config" / "autostart" / f"{APP_NAME}-watch.desktop"


def stamp() -> str:
    """Devuelve la hora actual con el formato de los diarios."""
    return f"{datetime.now():%Y-%m-%d %H:%M:%S}"


def log(msg: str) -> None:
    """Añade una línea al diario del vigilante.

    Se abre y cierra en cada línea y se recorta solo (`LOG_MAX_BYTES`).
    """
    try:
        HOST_DIR.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > LOG_MAX_BYTES:
            tail = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
            LOG_FILE.write_text("\n".join(tail[-LOG_KEEP_LINES:]) + "\n", encoding="utf-8")
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{stamp()} {msg}\n")
    except OSError:
        pass  # el diario nunca es motivo para romper nada


def read_json(path: Path) -> dict:
    """Lee un JSON del equipo; si no está o no es válido, `{}`."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_json(path: Path, data: dict) -> None:
    """Escribe un JSON del equipo de forma atómica.

    Hace falta porque `status` puede estar leyendo a la vez.
    """
    try:
        HOST_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        log(f"no he podido escribir {path.name}: {e}")


def pid_alive(pid: int) -> bool:
    """Indica si el proceso `pid` está vivo.

    Duplicado a propósito de `runsync.py`: el vigilante vive en el equipo y no
    puede importar nada del dispositivo, que puede no estar. En Windows NO vale
    `os.kill(pid, 0)`, que MATA el proceso en vez de comprobarlo.
    """
    if pid <= 0:
        return False
    if IS_WIN:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(handle, ctypes.byref(code))
        k32.CloseHandle(handle)
        return bool(ok) and code.value == STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def kill_pid(pid: int) -> None:
    """Termina el proceso `pid`; si no se puede, no hace nada."""
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, creationflags=CREATE_NO_WINDOW)
        else:
            import signal
            os.kill(pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        pass


def run_quiet(cmd: list[str]) -> subprocess.CompletedProcess:
    """Ejecuta una orden capturando su salida, sin consola.

    Si no se puede lanzar, devuelve un resultado con código 127.
    """
    kwargs: dict = {"capture_output": True, "text": True, "errors": "replace"}
    if IS_WIN:
        kwargs["creationflags"] = CREATE_NO_WINDOW
    try:
        return subprocess.run(cmd, **kwargs)
    except OSError as e:
        return subprocess.CompletedProcess(cmd, 127, "", str(e))


_ERRORMODE_SET = False
"""Si ya se ha cambiado el modo de error del proceso, que se hace una sola vez."""


def windows_roots() -> list[Path]:
    """Devuelve las raíces de las unidades de Windows, sin tocar letras vacías."""
    global _ERRORMODE_SET
    import ctypes
    k32 = ctypes.windll.kernel32
    if not _ERRORMODE_SET:
        # Sin esto, sondear una unidad sin medio saca el diálogo «No hay disco
        # en la unidad».
        k32.SetErrorMode(0x0001 | 0x8000)  # SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX
        _ERRORMODE_SET = True
    DRIVE_REMOVABLE, DRIVE_FIXED = 2, 3
    roots: list[Path] = []
    mask = k32.GetLogicalDrives()
    for i in range(26):
        if not (mask >> i) & 1:
            continue
        root = f"{chr(ord('A') + i)}:\\"
        # Un dispositivo puede presentarse como extraíble o como fijo según el firmware.
        if k32.GetDriveTypeW(root) in (DRIVE_REMOVABLE, DRIVE_FIXED):
            roots.append(Path(root))
    return roots


def _unescape_mount(mp: str) -> str:
    """Deshace los escapes octales de `/proc/self/mounts` en un punto de montaje."""
    for esc, ch in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
        mp = mp.replace(esc, ch)
    return mp


MOUNTS_FILE = Path("/proc/self/mounts")
"""Lista de montajes de Linux.

Sustituible, para que los tests no miren el sistema de verdad. Lista todo lo
montado desde un `/dev` (también `/dev/mapper/…`), de modo que cualquiera de
las vías que abren un contenedor sale dos veces: aquí y bajo
`POSIX_MOUNT_BASES`.
"""
POSIX_MOUNT_BASES = ("/media", "/run/media", "/mnt", "/Volumes")
"""Dónde montan lo extraíble en POSIX, uno o dos niveles por debajo.

VeraCrypt (`/media/veracrypt1`…), udisks2 (`/media/$USER/…` en Debian y Ubuntu,
`/run/media/$USER/…` en Fedora y Arch), cryptsetup desde `abrir-prdrive.sh`
(`/mnt/prdrive-<id>`) y macOS (`/Volumes`). Sustituible, como `MOUNTS_FILE`.
"""


def posix_roots() -> list[Path]:
    """Devuelve los puntos de montaje respaldados por un dispositivo de bloque.

    Más los sitios donde los escritorios montan lo extraíble
    (`POSIX_MOUNT_BASES`).
    """
    roots: list[Path] = []
    try:
        for line in MOUNTS_FILE.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0].startswith("/dev/"):
                roots.append(Path(_unescape_mount(parts[1])))
    except OSError:
        pass  # macOS y demás: se cubre con los directorios de abajo
    for base in POSIX_MOUNT_BASES:
        try:
            for child in Path(base).iterdir():      # /media/dispositivo
                if not child.is_dir():
                    continue
                roots.append(child)
                try:
                    roots += [g for g in child.iterdir() if g.is_dir()]  # /media/usuario/dispositivo
                except OSError:
                    pass
        except OSError:
            continue
    return roots


def candidate_roots(cfg: dict) -> list[Path]:
    """Devuelve las raíces donde buscar el dispositivo, sin repetidas.

    Las `extra_roots` de la configuración van primero.
    """
    roots = [Path(r) for r in cfg.get("extra_roots", [])]
    roots += windows_roots() if IS_WIN else posix_roots()
    seen: set[str] = set()
    unique: list[Path] = []
    for r in roots:
        key = str(r).rstrip("\\/").lower() or str(r)
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def control_id(root: Path) -> str | None:
    """Devuelve el `id=` del fichero de control de `root`, o `None` si no lleva ninguno.

    Propaga `OSError`: quien llama decide qué significa no poder leerlo.
    """
    for line in (root / CONTROL_FILE).read_text(
            encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.lower().startswith("id="):
            return line[3:].strip() or None
    return None


def find_pen(cfg: dict) -> Path | None:
    """Devuelve la raíz del dispositivo, o `None`.

    Cualquier `OSError` significa «ahora mismo no»: un volumen bloqueado
    responde con un error de permisos y no con «no existe».
    """
    want = cfg.get("device_id")
    for root in candidate_roots(cfg):
        try:
            if not (root / CONTROL_FILE).is_file():
                continue
            if want and control_id(root) != want:
                continue
            if not (root / STRUCT_MARKER).is_file():
                log(f"{root}: hay {CONTROL_FILE} pero falta {STRUCT_MARKER}; ignorada")
                continue
            return root
        except OSError:
            continue
    return None


def vestibule_id(root: Path) -> str | None:
    """Devuelve el `id=` de la marca del vestíbulo, o `None` si no lleva ninguno.

    Propaga `OSError`, como `control_id()`.
    """
    for line in (root / VESTIBULE_MARKER).read_text(
            encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.lower().startswith("id="):
            return line[3:].strip() or None
    return None


def find_vestibule(cfg: dict) -> Path | None:
    """Devuelve la raíz FÍSICA de este dispositivo, cerrado, o `None`.

    Solo con id: sin él no se sabe de quién es el contenedor, y pedir la
    contraseña de otro dispositivo sería peor que no pedir ninguna.
    """
    want = cfg.get("device_id")
    if not want:
        return None
    for root in candidate_roots(cfg):
        try:
            if ((root / VESTIBULE_MARKER).is_file() and vestibule_id(root) == want
                    and (root / CONTAINER_FILE).is_file()):
                return root
        except OSError:
            continue
    return None


def installed_veracrypt() -> str | None:
    """Devuelve el VeraCrypt INSTALADO en este equipo, o `None`; nunca el que viaja.

    En Windows, el de Archivos de programa; en Linux, `veracrypt` en el PATH.
    """
    if IS_WIN:
        for k in ("ProgramFiles", "ProgramW6432"):
            if not os.environ.get(k):
                continue
            exe = Path(os.environ[k]) / "VeraCrypt" / "VeraCrypt.exe"
            try:
                if exe.is_file():
                    return str(exe)
            except OSError:
                continue
        return None
    return shutil.which("veracrypt")


def _con_escritorio() -> bool:
    """Indica si hay una sesión gráfica (donde pedir la contraseña)."""
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def veracrypt_command(root: Path | None, container: Path | None = None,
                      dest: str = "", respaldo: str | None = None) -> list[str] | None:
    """Devuelve la orden que abre el contenedor, o `None` si no hay con qué.

    Sin contraseña: la pide VeraCrypt en su ventana. El VeraCrypt instalado va
    antes que el que viaja en la unidad: con otra versión instalada, el que
    viaja no puede cargar su driver (`ERR_DRIVER_VERSION`). Del que viaja, el
    portable de la arquitectura NATIVA del equipo (VeraCrypt escoge el driver
    por ella y un driver no se emula) y detrás el `VeraCrypt.exe` de un
    dispositivo de antes. En Linux, solo con escritorio: sin él no hay dónde
    pedir la contraseña, ni la de administrador que montar exige.

    Con `container` es la raíz cifrada de un EQUIPO, que abre el agente: el
    contenedor no está en la raíz de ninguna unidad y se da entero. Va el
    VeraCrypt instalado y, si no hay, `respaldo`.

    Args:
        root: Raíz física del dispositivo.
        container: Ruta del contenedor de una raíz de equipo.
        dest: Dónde montarlo: la letra fija (`/letter`) en Windows, porque los
            programas apuntan a la raíz y no puede cambiar de un día a otro; la
            carpeta fija en Linux.
        respaldo: El portable del agente, que se lo pasa ya comprobado
            (penwatch no importa nada del proyecto); pide administrador cada
            vez que carga su driver.
    """
    if container is not None:
        exe = installed_veracrypt() or respaldo
        if exe is None:
            return None
        if IS_WIN:
            letra = ["/letter", dest.rstrip(":\\/")[:1].upper()] if dest else []
            return [exe, "/volume", str(container), *letra,
                    "/mountoption", "rm",
                    "/mountoption", f"label={APP_NAME.upper()}",
                    "/history", "n", "/cache", "n", "/quit"]
        if not _con_escritorio():
            return None
        return [exe, str(container), *([dest] if dest else [])]
    container = root / CONTAINER_FILE
    if IS_WIN:
        candidates = [Path(os.environ[k]) / "VeraCrypt" / "VeraCrypt.exe"
                      for k in ("ProgramFiles", "ProgramW6432") if os.environ.get(k)]
        arch = native_arch()
        if arch in TRAVELER_ARCHS:
            candidates.append(root / TRAVELER_DIR / TRAVELER_PORTABLE.format(arq=arch))
        candidates.append(root / TRAVELER_DIR / TRAVELER_EXE)
        for exe in candidates:
            try:
                if exe.is_file():
                    return [str(exe), "/volume", str(container),
                            "/mountoption", "rm",
                            "/mountoption", f"label={APP_NAME.upper()}",
                            "/history", "n", "/cache", "n", "/quit"]
            except OSError:
                continue
        return None
    exe = shutil.which("veracrypt")
    if not exe or not _con_escritorio():
        return None
    return [exe, str(container)]


def open_container(root: Path, cwd: Path | None = None) -> bool:
    """Le pide a VeraCrypt que abra el contenedor de `root`. No espera.

    Hace lo mismo que `Abrir PRDRIVE.bat` (`install/vestibulo.py`, con las
    citas del código de VeraCrypt) menos lanzar runsync: eso lo hace el bucle
    cuando el volumen aparece montado, así se respeta el modo (`daemon` no abre
    ventana) y no hay dos lanzamientos peleándose por el registro de la
    ventana. Si se ha abierto lo dirá `find_pen()` en los sondeos siguientes:
    VeraCrypt, sin administrador y en modo portátil, se relanza elevado y sale
    con 0 antes de que nadie escriba la contraseña, así que su salida no dice
    nada.

    Args:
        root: Raíz física del dispositivo.
        cwd: Carpeta de trabajo del proceso, en el equipo como en `launch()`:
            la del vigilante por defecto, o la de quien llama (el agente
            residente).

    Returns:
        `True` si lo ha lanzado.
    """
    cmd = veracrypt_command(root)
    if cmd is None and not IS_WIN:
        log(linux_closed_note(root))
        return False
    if cmd is None:
        log(f"{root}: dispositivo cifrado y cerrado, pero no hay VeraCrypt con el "
            "que abrirlo")
        return False
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL, "cwd": str(cwd or HOST_DIR),
                    "close_fds": True}
    if IS_WIN:
        kwargs["creationflags"] = CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(cmd, **kwargs)
    except OSError as e:
        log(f"no he podido lanzar VeraCrypt: {e}")
        return False
    log(f"abriendo el contenedor de {root} con {cmd[0]}; la contraseña la pide VeraCrypt")
    return True


def linux_open_route() -> str | None:
    """Devuelve con qué abriría `abrir-prdrive.sh` el contenedor en este Linux.

    El mismo orden que el script: `veracrypt`, `udisks2` (si existe
    `UDISKS_TCRYPT_CONF`) o `cryptsetup`; `None` si con nada. Con `/usr/sbin` y
    `/sbin`, como el script: Debian no los pone en el PATH de un usuario y ahí
    vive cryptsetup.
    """
    path = os.pathsep.join(p for p in (os.environ.get("PATH", ""), "/usr/sbin", "/sbin")
                           if p)
    if shutil.which("veracrypt", path=path):
        return "veracrypt"
    try:
        tcrypt = UDISKS_TCRYPT_CONF.is_file()
    except OSError:
        tcrypt = False
    if tcrypt and shutil.which("udisksctl", path=path):
        return "udisks2"
    if shutil.which("cryptsetup", path=path):
        return "cryptsetup"
    return None


def linux_closed_note(root: Path) -> str:
    """Devuelve la línea del diario cuando no puede abrirlo: por qué, y cómo sí.

    `abrir-prdrive.sh` lo abre con udisks2 o cryptsetup, pero los dos piden la
    contraseña por una terminal (`udisksctl unlock` la lee de la que controla
    el proceso, cryptsetup de stdin) y el vigilante no tiene ninguna. Que el
    escritorio la pida solo tras un `udisksctl loop-setup` (GNOME Shell, Files,
    Dolphin) está POR PROBAR (U4 en #51): hasta entonces no pone el loop por su
    cuenta y deja dicho qué vía tiene este equipo. Abierto a mano,
    `posix_roots()` lo encuentra y el lanzamiento sigue; la regla de una vez
    por conexión no cambia.
    """
    route = linux_open_route()
    if route is None:
        return (f"{root}: dispositivo cifrado y cerrado, y este equipo no tiene con "
                f"qué abrirlo: ni VeraCrypt, ni udisks2 con {UDISKS_TCRYPT_CONF}, ni "
                "cryptsetup")
    why = {"veracrypt": "hay VeraCrypt, pero no escritorio donde pida la contraseña",
           "udisks2": "sin VeraCrypt; este equipo lo abre con udisks2, sin administrador",
           "cryptsetup": "sin VeraCrypt; este equipo lo abre con cryptsetup, con sudo",
           }[route]
    return (f"{root}: dispositivo cifrado y cerrado; {why}. La contraseña se pide en "
            f"una terminal: «sh {root / OPEN_SCRIPT}»")


def native_arch() -> str:
    """Devuelve la CPU del equipo: `x64`, `arm64` u otra cosa en minúsculas.

    En Windows se pregunta a `IsWow64Process2`, por lo mismo que en
    `common/model.py` (que no se puede importar desde aquí): un Python x64
    emulado en un ARM64 oye `AMD64` en todos los demás sitios.
    """
    if IS_WIN:
        try:
            import ctypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.GetCurrentProcess.restype = ctypes.c_void_p
            k32.IsWow64Process2.argtypes = [ctypes.c_void_p,
                                            ctypes.POINTER(ctypes.c_ushort),
                                            ctypes.POINTER(ctypes.c_ushort)]
            proceso, nativa = ctypes.c_ushort(), ctypes.c_ushort()
            if k32.IsWow64Process2(k32.GetCurrentProcess(), ctypes.byref(proceso),
                                   ctypes.byref(nativa)):
                valor = {0xAA64: "arm64", 0x8664: "x64"}.get(nativa.value)
                if valor:
                    return valor
        except (OSError, AttributeError, ValueError):
            pass
    maquina = platform.machine().lower()
    if maquina in ("aarch64", "aarch64_be", "arm64"):
        return "arm64"
    if maquina in ("x86_64", "amd64", "x64"):
        return "x64"
    return maquina


def runtime_keys_for(so: str, arch: str) -> list[str]:
    """Devuelve los runtimes del dispositivo que sirven en ese equipo, por preferencia.

    La misma cadena que `runsync.bat` y `install/platforms.candidates()`: un
    Windows ARM64 prefiere el suyo y ejecuta el x64 emulado; Linux no emula.

    Args:
        so: `windows` o `linux`.
        arch: `x64` o `arm64`.
    """
    if so == "windows":
        return {"arm64": ["windows-arm64", "windows-x64"],
                "x64": ["windows-x64"]}.get(arch, [])
    if so == "linux":
        return {"arm64": ["linux-arm64"], "x64": ["linux-x64"]}.get(arch, [])
    return []


def host_runtime_keys() -> list[str]:
    """Devuelve los runtimes que sirven en ESTE equipo.

    Función de módulo para que los tests elijan la plataforma.
    """
    so = "windows" if IS_WIN else ("linux" if sys.platform.startswith("linux")
                                   else sys.platform)
    return runtime_keys_for(so, native_arch())


def interpreter_rel(key: str, windowless: bool = False) -> str:
    """Devuelve el intérprete de un runtime, relativo a su carpeta.

    Args:
        key: Clave de la plataforma del runtime.
        windowless: `pythonw` en vez de `python` (Windows).
    """
    if key.startswith("windows-"):
        return "pythonw.exe" if windowless else "python.exe"
    return "bin/python3"


def device_runtime(root: Path) -> tuple[str, Path, str] | None:
    """Devuelve `(clave, carpeta, sello)` del Python del dispositivo para este equipo.

    Es `None` si no lleva ninguno que sirva. Solo lee: un runtime sin
    intérprete o sin sello es uno a medias y no cuenta.
    """
    for key in host_runtime_keys():
        carpeta = root / RUNTIME_SUBDIR / key
        try:
            if not (carpeta / interpreter_rel(key)).is_file():
                continue
            return key, carpeta, (carpeta / RUNTIME_STAMP).read_text(
                encoding="utf-8", errors="replace")
        except OSError:
            continue
    return None


def stamp_id(stamp: str) -> str:
    """Devuelve el nombre de la carpeta de una versión.

    Sale del sello, así que dos sellos distintos nunca comparten carpeta.
    """
    return hashlib.sha256(stamp.encode("utf-8")).hexdigest()[:12]


def copy_runtime(key: str, src: Path, stamp: str) -> Path:
    """Copia el runtime del dispositivo a `RUNTIMES_DIR/<id>/` y devuelve la carpeta.

    Si esa versión ya está copiada no hace nada. Si no, copia a una carpeta de
    trabajo y la renombra al final: una copia interrumpida (el dispositivo se
    desenchufa a mitad) no deja nada que parezca bueno. Del dispositivo solo se
    lee, y cada fichero se cierra al copiarlo.
    """
    destino = RUNTIMES_DIR / stamp_id(stamp)
    try:
        if ((destino / RUNTIME_STAMP).read_text(encoding="utf-8") == stamp
                and (destino / interpreter_rel(key)).is_file()):
            return destino
    except OSError:
        pass
    RUNTIMES_DIR.mkdir(parents=True, exist_ok=True)
    trabajo = RUNTIMES_DIR / f".{destino.name}.tmp-{os.getpid()}"
    shutil.rmtree(trabajo, ignore_errors=True)
    try:
        shutil.copytree(src, trabajo)
        if not IS_WIN:
            # Desde exFAT llega sin bit de ejecución; aquí sí se puede poner.
            interprete = trabajo / interpreter_rel(key)
            interprete.chmod(interprete.stat().st_mode | 0o755)
        if destino.exists():
            shutil.rmtree(destino)          # una copia vieja sin el sello bueno
        os.replace(trabajo, destino)
    except OSError:
        shutil.rmtree(trabajo, ignore_errors=True)
        raise
    return destino


def _dentro(ruta: Path, raiz: Path) -> bool:
    """Indica si `ruta` está dentro de `raiz`, una vez resueltas."""
    try:
        ruta.resolve().relative_to(raiz.resolve())
        return True
    except (OSError, ValueError):
        return False


def host_python(root: Path | None = None) -> str | None:
    """Devuelve un Python del EQUIPO, o `None`.

    Uno que viva en el dispositivo no vale: al desenchufarlo, la tarea se
    quedaría sin intérprete.

    Args:
        root: El dispositivo, cuyos Python se descartan.
    """
    nombres = ("python", "python3") if IS_WIN else ("python3", "python")
    for exe in (sys.executable, *(shutil.which(n) for n in nombres)):
        if not exe:
            continue
        if root is not None and _dentro(Path(exe), root):
            continue
        return exe
    return None


def choose_python(root: Path) -> tuple[str, dict | None, str]:
    """Elige con qué Python arrancará el vigilante.

    La copia del del dispositivo si lleva uno para este equipo; si no, el del
    sistema, con una nota que `status` enseña.

    Returns:
        `(python, runtime, nota)`.

    Raises:
        RuntimeError: Si no hay ninguno.
    """
    encontrado = device_runtime(root)
    if encontrado:
        key, src, stamp = encontrado
        destino = copy_runtime(key, src, stamp)
        return (str(destino / interpreter_rel(key)),
                {"key": key, "id": destino.name, "stamp": stamp}, "")
    claves = host_runtime_keys()
    plataforma = claves[0] if claves else f"{sys.platform} {native_arch()}"
    exe = host_python(root)
    if not exe:
        raise RuntimeError(
            f"El dispositivo no lleva Python para {plataforma} y en este equipo no "
            f"hay ninguno instalado. Vuelve a ejecutar el instalador de prdrive y "
            f"pulsa «Añadir plataformas…», o instala Python 3.11+.")
    return exe, None, (f"el dispositivo no lleva Python para {plataforma}: "
                       f"se usa el del equipo")


def _runtime_root(exe: str | None) -> Path | None:
    """Devuelve la carpeta de `RUNTIMES_DIR` de ese intérprete, si es de allí."""
    if not exe:
        return None
    try:
        rel = Path(exe).resolve().relative_to(RUNTIMES_DIR.resolve())
    except (OSError, ValueError):
        return None
    return RUNTIMES_DIR / rel.parts[0] if rel.parts else None


def prune_runtimes(cfg: dict) -> None:
    """Recoge las copias del Python que ya no usa nadie.

    Se conservan tres: la de `python_exe` (con la que se lanza), la de
    `task_python` (con la que arranca la tarea al iniciar sesión, que puede ser
    otra si no se pudo volver a registrar) y la del proceso actual. Lo que no
    se pueda borrar (en uso) se queda para la próxima vez.
    """
    guardar = {r.name for r in (_runtime_root(cfg.get("python_exe")),
                                _runtime_root(cfg.get("task_python")),
                                _runtime_root(sys.executable)) if r}
    try:
        hijos = list(RUNTIMES_DIR.iterdir())
    except OSError:
        return
    for hijo in hijos:
        if hijo.name not in guardar:
            shutil.rmtree(hijo, ignore_errors=True)


def register(cfg: dict) -> str:
    """Registra la tarea (Windows) o el servicio de usuario (Linux) con `cfg`.

    Función de módulo para que los tests no registren nada de verdad.

    Returns:
        El mensaje de lo que ha hecho, para el diario.
    """
    return register_windows(cfg) if IS_WIN else register_linux(cfg)


def refresh_runtime(root: Path, cfg: dict) -> dict:
    """Refresca la copia del Python si el dispositivo trae otro.

    Nunca lanza: un refresco que falla deja el vigilante con la copia que ya
    tenía, que sigue funcionando, y lo apunta en el diario.

    Returns:
        El `cfg` con el que seguir (el mismo si no había nada que hacer).
    """
    encontrado = device_runtime(root)
    if encontrado is None:
        return cfg
    key, src, stamp = encontrado
    actual = cfg.get("runtime") or {}
    if actual.get("stamp") == stamp and Path(cfg.get("python_exe") or "").is_file():
        return cfg
    try:
        destino = copy_runtime(key, src, stamp)
    except OSError as e:
        log(f"no he podido copiar el Python del dispositivo: {e}")
        return cfg

    nuevo = dict(cfg)
    nuevo["python_exe"] = str(destino / interpreter_rel(key))
    nuevo["runtime"] = {"key": key, "id": destino.name, "stamp": stamp}
    nuevo.pop("runtime_note", None)
    log(f"el dispositivo trae otro Python ({key}); copia nueva en {destino}")
    try:
        log(register(nuevo))
        nuevo["task_python"] = nuevo["python_exe"]
    except (OSError, RuntimeError) as e:
        log(f"no he podido volver a registrar el vigilante con el Python nuevo: {e}")
    write_json(CONFIG_FILE, nuevo)
    prune_runtimes(nuevo)
    return nuevo


def python_for_launch(cfg: dict) -> str:
    """Devuelve el Python con el que lanzar runsync.

    En Windows, `pythonw`: sin él cada lanzamiento abre una consola.
    """
    exe = cfg.get("python_exe") or sys.executable
    if IS_WIN:
        # Sin pythonw, cada lanzamiento abre una consola.
        w = Path(exe).with_name("pythonw.exe")
        if w.exists():
            return str(w)
    return exe


def _vivo_aqui(root: Path, rel: Path) -> dict | None:
    """Devuelve ese registro del dispositivo si es de un proceso vivo de ESTE equipo.

    Solo de este equipo: el fichero viaja dentro del dispositivo, así que el
    pid de otra máquina no dice nada de la nuestra. No limpia lo rancio (de eso
    se encarga runsync): aquí no se escribe en el dispositivo, que bloquearía
    su extracción.
    """
    info = read_json(root / rel)
    if not isinstance(info, dict) or info.get("host") != HOST:
        return None
    try:
        pid = int(info.get("pid", -1))
    except (TypeError, ValueError):
        return None
    return info if pid_alive(pid) else None


def aplicacion_en_marcha(root: Path) -> str | None:
    """Devuelve qué hay ya en marcha para este dispositivo en este equipo, o `None`.

    Lanzar encima de una ventana abierta o de un servicio no aporta nada y
    estorba: dos sincronizaciones a la vez se pelean por el lock de bisync, y
    una segunda ventana le quitaría el servicio a la primera. Se devuelve la
    frase para el diario, que es lo único que se hace con esto.
    """
    ventana = _vivo_aqui(root, UI_LOCK_REL)
    if ventana is not None:
        return f"la ventana de runsync ya está abierta (pid {ventana.get('pid')})"
    servicio = _vivo_aqui(root, DAEMON_LOCK_REL)
    if servicio is not None:
        return f"el servicio periódico ya está en marcha (pid {servicio.get('pid')})"
    return None


def launch(root: Path, cfg: dict) -> bool:
    """Lanza runsync según el modo de `cfg`.

    Returns:
        `True` si lo ha lanzado.
    """
    mode = cfg.get("mode", "ui")
    args = [python_for_launch(cfg), str(root / STRUCT_MARKER)]
    # Ni parejas ni intervalo: son los del servicio y runsync los lee del
    # dispositivo (un `watch.json` antiguo que los traiga no manda). `sync` va
    # por `--auto --once`: sin parejas, `runsync.py` a secas abriría la
    # ventana.
    if mode == "daemon":
        args.append("--auto")
    elif mode == "sync":
        args += ["--auto", "--once"]
    # mode 'ui': runsync.py sin argumentos abre la UI.

    if mode == "ui" and not IS_WIN and not (os.environ.get("DISPLAY") or
                                            os.environ.get("WAYLAND_DISPLAY")):
        log("aviso: modo 'ui' sin DISPLAY; runsync no podrá abrir ventana "
            "(usa --mode daemon o --mode sync en equipos sin escritorio)")

    # cwd en el equipo, NUNCA en el dispositivo: impediría extraerlo.
    kwargs: dict = {"stdin": subprocess.DEVNULL, "cwd": str(HOST_DIR), "close_fds": True}
    handle = None
    if mode == "sync":
        try:  # una sincronización silenciosa sin rastro no sirve de nada
            handle = LOG_FILE.open("a", encoding="utf-8", errors="replace")
        except OSError:
            handle = None
    kwargs["stdout"] = handle or subprocess.DEVNULL
    kwargs["stderr"] = subprocess.STDOUT if handle else subprocess.DEVNULL
    if IS_WIN:
        kwargs["creationflags"] = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(args, **kwargs)
    except OSError as e:
        log(f"no he podido lanzar runsync: {e}")
        return False
    finally:
        if handle:
            handle.close()  # el hijo ya tiene su copia del descriptor
    log(f"runsync lanzado (pid {proc.pid}, modo {mode}): {' '.join(args[1:])}")
    return True


def watch_loop(once: bool = False) -> int:
    """Es el bucle del vigilante: sondea y lanza una vez por conexión.

    Args:
        once: Una sola pasada, sin dormir (`run --once`) y sin esperar el
            segundo sondeo.

    Returns:
        0 al terminar.
    """
    cfg = read_json(CONFIG_FILE)
    poll = max(1.0, float(cfg.get("poll_seconds", POLL_SECONDS)))
    STOP_FILE.unlink(missing_ok=True)

    state = read_json(STATE_FILE)
    state.update({"watcher_pid": os.getpid(), "started": stamp()})
    write_json(STATE_FILE, state)
    log(f"vigilante iniciado (pid {os.getpid()}, modo {cfg.get('mode', 'ui')}, "
        f"sondeo {poll:g}s{', una pasada' if once else ''})")

    stable = 0
    stable_vestibule = 0
    try:
        while True:
            root = find_pen(cfg)

            if root is None:
                if state.get("launched") or state.get("root"):
                    log("dispositivo no disponible; disparo rearmado")
                    state.update({"launched": False, "root": None})
                    # Si lo que queda es su entrada, se ha cerrado el
                    # contenedor con la unidad puesta: es «Expulsar», no una
                    # conexión nueva. Sin apuntarlo, un vigilante instalado con
                    # el contenedor abierto pediría la contraseña.
                    if not state.get("vestibule"):
                        cerrado = find_vestibule(cfg)
                        if cerrado is not None:
                            state["vestibule"] = str(cerrado)
                    write_json(STATE_FILE, state)
                stable = 0
                # ¿Está el dispositivo, pero cerrado? Una vez por conexión: si
                # se cancela la contraseña no se vuelve a preguntar hasta que
                # desaparezca y vuelva, ni tras «Expulsar» (la unidad sigue
                # puesta y lo que se quiere es quitarla).
                vestibule = find_vestibule(cfg)
                if vestibule is None:
                    stable_vestibule = 0
                    if state.get("vestibule"):
                        log("entrada del dispositivo cifrado retirada; apertura rearmada")
                        state["vestibule"] = None
                        write_json(STATE_FILE, state)
                elif not state.get("vestibule"):
                    stable_vestibule += 1
                    if stable_vestibule >= (1 if once else STABLE_CHECKS):
                        log(f"dispositivo cifrado detectado en {vestibule}")
                        ok = open_container(vestibule)
                        state.update({"vestibule": str(vestibule),
                                      "vestibule_open": stamp(),
                                      "vestibule_open_ok": ok})
                        write_json(STATE_FILE, state)
                        stable_vestibule = 0
            elif not state.get("launched"):
                stable += 1
                if stable >= (1 if once else STABLE_CHECKS):
                    log(f"dispositivo detectado en {root}")
                    ocupado = aplicacion_en_marcha(root)
                    if ocupado:
                        # El disparo se da por gastado como si se hubiera
                        # lanzado: reintentarlo cada minuto con la ventana
                        # abierta solo llenaría el diario. Se rearma al
                        # desaparecer el dispositivo.
                        log(f"no lanzo nada: {ocupado}")
                        state.update({"launched": True, "root": str(root),
                                      "last_launch": stamp(), "last_launch_ok": None,
                                      "last_skip": ocupado})
                        stable = 0
                    else:
                        # Antes de lanzar: si el dispositivo trae otro Python,
                        # se lanza ya con la copia nueva.
                        cfg = refresh_runtime(root, cfg)
                        ok = launch(root, cfg)
                        state.update({"launched": ok, "root": str(root),
                                      "last_launch": stamp(), "last_launch_ok": ok,
                                      "last_skip": None})
                        # Si falla se reintenta en ~1 min, por si el
                        # dispositivo se estaba desbloqueando.
                        stable = 0 if ok else -int(60 / poll)
                    write_json(STATE_FILE, state)
            else:
                stable = 0
                if state.get("root") != str(root):  # remontado en otra letra
                    state["root"] = str(root)
                    write_json(STATE_FILE, state)

            if once:
                return 0
            time.sleep(poll)
            if STOP_FILE.exists():
                log("parada solicitada")
                return 0
    except KeyboardInterrupt:
        log("interrumpido por teclado")
        return 0
    finally:
        state = read_json(STATE_FILE)
        if state.get("watcher_pid") == os.getpid():
            state.pop("watcher_pid", None)
            write_json(STATE_FILE, state)
        STOP_FILE.unlink(missing_ok=True)


def stop_running_watcher() -> str | None:
    """Para el vigilante que hubiera.

    Primero por las buenas (fichero `stop`) y, si no contesta, por las malas.

    Returns:
        Qué ha hecho, o `None` si no había ninguno en marcha.
    """
    if IS_WIN:
        run_quiet(["schtasks", "/End", "/TN", TASK_NAME])
    elif shutil.which("systemctl"):
        run_quiet(["systemctl", "--user", "stop", UNIT_NAME])

    pid = int(read_json(STATE_FILE).get("watcher_pid") or -1)
    if not pid_alive(pid):
        return None
    try:
        HOST_DIR.mkdir(parents=True, exist_ok=True)
        STOP_FILE.touch()
    except OSError:
        pass
    deadline = time.monotonic() + STOP_WAIT_SECONDS
    while time.monotonic() < deadline and pid_alive(pid):
        time.sleep(0.3)
    STOP_FILE.unlink(missing_ok=True)
    if pid_alive(pid):
        kill_pid(pid)
        return f"vigilante anterior (pid {pid}) terminado a la fuerza."
    return f"vigilante anterior (pid {pid}) detenido."


TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>{user}</Author>
    <Description>{description}</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{user}</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{workdir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""
"""Plantilla de la tarea programada de Windows.

Siempre para el USUARIO que ejecuta `install` y disparada por su inicio de
sesión: así el vigilante vuelve solo tras un reinicio o un apagado.
"""


def current_user() -> str:
    """Devuelve el usuario que ejecuta esto, para quien se registra la tarea."""
    if IS_WIN:
        domain = os.environ.get("USERDOMAIN", "")
        user = os.environ.get("USERNAME", "")
        return f"{domain}\\{user}" if domain and user else (user or getpass.getuser())
    try:
        return getpass.getuser()
    except OSError:
        return os.environ.get("USER", "")


TASK_DESCRIPTION = ("Vigila la conexion del dispositivo (fichero PRDRIVE) y lanza "
                    "runsync.py.")
"""Descripción de la tarea programada del vigilante."""


def task_xml(user: str, command: str, arguments: str, workdir: str,
             description: str) -> str:
    """Devuelve el XML de una tarea por usuario que arranca al iniciar sesión.

    Está aparte de `register_windows()` para que el agente residente registre
    la suya con las mismas trampas ya resueltas: UTF-16,
    `DisallowStartIfOnBatteries` en false (un portátil a batería no arrancaba
    nada) y `ExecutionTimeLimit` PT0S (sin él, Windows la mata a las 72 h).
    """
    return TASK_XML.format(user=xml_escape(user), command=xml_escape(command),
                           arguments=xml_escape(arguments), workdir=xml_escape(workdir),
                           description=xml_escape(description))


def register_task(name: str, command: str, arguments: str, workdir: Path,
                  description: str, user: str | None = None) -> str:
    """Registra (o sustituye) la tarea `name` y devuelve el mensaje de lo hecho.

    Raises:
        RuntimeError: Si no puede crearla.
    """
    user = user or current_user()
    xml = task_xml(user, command, arguments, str(workdir), description)
    workdir.mkdir(parents=True, exist_ok=True)
    fichero = workdir / "task.xml"
    # schtasks /XML quiere el fichero en UTF-16; en UTF-8 falla con acentos.
    fichero.write_text(xml, encoding="utf-16")
    res = run_quiet(["schtasks", "/Create", "/TN", name, "/XML", str(fichero), "/F"])
    if res.returncode != 0:
        # Plan B: la forma simple, que no admite ajustes (con ella Windows puede
        # negarse a arrancar la tarea con el portátil a batería).
        log(f"schtasks /XML ha fallado ({res.stderr.strip() or res.stdout.strip()}); "
            f"probando la forma simple")
        res = run_quiet(["schtasks", "/Create", "/TN", name,
                         "/TR", f'"{command}" {arguments}', "/SC", "ONLOGON", "/F"])
        if res.returncode != 0:
            raise RuntimeError(f"no he podido crear la tarea: "
                               f"{res.stderr.strip() or res.stdout.strip()}")
    return (f"Tarea '{name}' creada para {user}: arranca en cada inicio de "
            f"sesión (sobrevive a reinicios).")


def register_windows(cfg: dict) -> str:
    """Registra la tarea del vigilante con la copia de este script en el equipo."""
    return register_task(TASK_NAME, python_for_launch(cfg), f'"{SELF_COPY}" run',
                         HOST_DIR, TASK_DESCRIPTION, cfg.get("user"))


def desktop_exec(args: list[str]) -> str:
    """Devuelve la línea `Exec=` de un `.desktop`.

    Según la *Desktop Entry Specification* («The Exec key»): cada argumento
    entre comillas dobles, con `"`, `` ` ``, `$` y la barra invertida escapados
    con una barra; ENCIMA, la regla de escape de todo valor de tipo cadena
    dobla cada barra; y el `%` (códigos de campo) se dobla. Sin comillas, una
    ruta con espacios (un usuario «Ana María») partía la orden en dos.
    """
    partes = []
    for arg in args:
        citado = "".join("\\" + ch if ch in '"`$\\' else ch for ch in arg)
        partes.append('"' + citado.replace("\\", "\\\\") + '"')
    return " ".join(partes).replace("%", "%%")


def autostart_desktop(name: str, args: list[str], comment: str = "") -> str:
    """Devuelve un autostart XDG (`~/.config/autostart/*.desktop`) que lanza `args`."""
    return ("[Desktop Entry]\nType=Application\n"
            f"Name={name}\n"
            + (f"Comment={comment}\n" if comment else "")
            + f"Exec={desktop_exec(args)}\n"
            "X-GNOME-Autostart-enabled=true\nNoDisplay=true\n")


UNIT_TEMPLATE = """[Unit]
Description=prdrive — vigila la conexion del dispositivo y lanza runsync.py

[Service]
Type=simple
ExecStart={python} {script} run
Restart=on-failure
RestartSec=10
WorkingDirectory={workdir}

[Install]
WantedBy=default.target
"""
"""Unidad de usuario de systemd del vigilante."""


def register_linux(cfg: dict) -> str:
    """Registra la unidad de usuario de systemd o, sin systemd, un autostart XDG.

    Returns:
        El mensaje de lo hecho.
    """
    python = cfg.get("python_exe") or sys.executable
    user = cfg.get("user") or current_user()
    if shutil.which("systemctl"):
        UNIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        UNIT_FILE.write_text(UNIT_TEMPLATE.format(
            python=python, script=SELF_COPY, workdir=HOST_DIR), encoding="utf-8")
        run_quiet(["systemctl", "--user", "daemon-reload"])
        # Para que el modo 'ui' pueda abrir ventana desde el servicio.
        run_quiet(["systemctl", "--user", "import-environment",
                   "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY"])
        res = run_quiet(["systemctl", "--user", "enable", UNIT_NAME])
        if res.returncode == 0:
            extra = ""
            if shutil.which("loginctl"):
                # Sin linger, la unidad solo vive mientras haya sesión abierta.
                lres = run_quiet(["loginctl", "enable-linger", user])
                extra = ("\n  linger activado: vigila también sin sesión abierta."
                         if lres.returncode == 0 else
                         f"\n  (no he podido activar linger: {lres.stderr.strip()}; "
                         f"ejecútalo a mano con: loginctl enable-linger {user})")
            return (f"Servicio '{UNIT_NAME}' instalado y activado para {user}: "
                    f"arranca en cada inicio de sesión." + extra)
        log(f"systemctl enable ha fallado: {res.stderr.strip()}")

    DESKTOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    DESKTOP_FILE.write_text(
        autostart_desktop(f"{APP_NAME} Watch", [python, str(SELF_COPY), "run"]),
        encoding="utf-8")
    return (f"Autostart XDG instalado en {DESKTOP_FILE} (no hay systemd de "
            f"usuario): arranca al iniciar el escritorio.")


def unregister() -> list[str]:
    """Quita la tarea, la unidad y el autostart que hubiera.

    Returns:
        Un mensaje por cada cosa quitada.
    """
    msgs = []
    if IS_WIN:
        res = run_quiet(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
        msgs.append(f"Tarea '{TASK_NAME}' eliminada." if res.returncode == 0
                    else f"No había tarea '{TASK_NAME}' que eliminar.")
    else:
        if shutil.which("systemctl") and UNIT_FILE.exists():
            run_quiet(["systemctl", "--user", "disable", "--now", UNIT_NAME])
            UNIT_FILE.unlink(missing_ok=True)
            run_quiet(["systemctl", "--user", "daemon-reload"])
            msgs.append(f"Servicio '{UNIT_NAME}' desactivado y eliminado.")
        if DESKTOP_FILE.exists():
            DESKTOP_FILE.unlink(missing_ok=True)
            msgs.append(f"Autostart '{DESKTOP_FILE.name}' eliminado.")
        if not msgs:
            msgs.append("No había servicio ni autostart que eliminar.")
    return msgs


def start_now(cfg: dict) -> str:
    """Arranca el vigilante ya, sin esperar al próximo inicio de sesión.

    Returns:
        El mensaje de cómo ha ido.
    """
    if IS_WIN:
        res = run_quiet(["schtasks", "/Run", "/TN", TASK_NAME])
        if res.returncode == 0:
            return "Vigilante arrancado."
        return (f"No he podido arrancarlo ahora ({res.stderr.strip()}); "
                f"arrancará al iniciar sesión.")
    if shutil.which("systemctl") and UNIT_FILE.exists():
        res = run_quiet(["systemctl", "--user", "start", UNIT_NAME])
        if res.returncode == 0:
            return "Vigilante arrancado."
        return (f"No he podido arrancarlo ahora ({res.stderr.strip()}); "
                f"arrancará al iniciar sesión.")
    try:
        subprocess.Popen([cfg.get("python_exe") or sys.executable, str(SELF_COPY), "run"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, cwd=str(HOST_DIR),
                         start_new_session=True, close_fds=True)
        return "Vigilante arrancado."
    except OSError as e:
        return f"No he podido arrancarlo ahora ({e}); arrancará al iniciar sesión."


def device_root_from_here() -> Path:
    """Devuelve la raíz del dispositivo desde el que se ejecuta `install`.

    Es el padre de la carpeta de la aplicación.

    Raises:
        SystemExit: Si no se ejecuta desde un dispositivo.
    """
    root = SCRIPT_DIR.parent
    if not (root / STRUCT_MARKER).is_file():
        sys.exit(f"'install' hay que ejecutarlo desde el dispositivo: no "
                 f"encuentro {root / STRUCT_MARKER}")
    return root


def ensure_control_file(root: Path) -> str | None:
    """Se asegura de que hay un `.prdrive/PRDRIVE` y devuelve su `id`.

    Un PRDRIVE que ya traiga contenido NO se toca (es de quien lo puso): la
    unidad se reconocerá por su sola presencia. Uno vacío sí se rellena con la
    plantilla, que no pierde nada y añade el id. Si el volumen es de solo
    lectura se sigue adelante sin id.

    Returns:
        El `id`, o `None` si no lo hay.
    """
    path = root / CONTROL_FILE
    try:
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None
        if text is not None and text.strip():
            device_id = control_id(root)
            print(f"  fichero de control: {path}"
                  + (f" (id {device_id[:8]}…)" if device_id else
                     " (sin id: se reconocerá solo por su presencia)"))
            return device_id
        device_id = uuid.uuid4().hex
        path.write_text(CONTROL_TEMPLATE.format(device_id=device_id), encoding="utf-8")
        verbo = "rellenado" if text is not None else "creado"
        print(f"  fichero de control {verbo}: {path} (id {device_id[:8]}…)")
        return device_id
    except OSError as e:
        print(f"  aviso: no he podido leer/escribir {path} ({e}); la unidad se "
              f"reconocerá solo por su presencia.")
        return None


def cmd_install(args: argparse.Namespace) -> int:
    """Instala el vigilante en este equipo.

    Para el vigilante anterior, copia este script y el Python del dispositivo,
    escribe `watch.json`, registra la tarea y la arranca.

    Returns:
        0 si ha ido bien; 1 si no ha podido.
    """
    dispositivo = device_root_from_here()
    user = current_user()
    print(f"Dispositivo: {dispositivo}")
    print(f"Usuario: {user}")
    device_id = ensure_control_file(dispositivo)

    msg = stop_running_watcher()
    if msg:
        print(f"  {msg}")

    HOST_DIR.mkdir(parents=True, exist_ok=True)
    if Path(__file__).resolve() != SELF_COPY.resolve():
        shutil.copy2(__file__, SELF_COPY)

    try:
        python_exe, runtime, nota = choose_python(dispositivo)
    except (OSError, RuntimeError) as e:
        print(f"ERROR: {e}")
        return 1
    print(f"  Python del vigilante: {python_exe}"
          + (f" (copia del del dispositivo, {runtime['key']})" if runtime else
             f"\n  aviso: {nota}"))

    cfg = {
        "mode": args.mode,
        "poll_seconds": args.poll,
        "device_id": device_id,
        "extra_roots": list(args.extra_root or []),
        "python_exe": python_exe,
        "runtime": runtime,
        "runtime_note": nota,
        "user": user,
        "installed": stamp(),
        "installed_from": str(dispositivo),
    }
    write_json(CONFIG_FILE, cfg)

    # El dispositivo está puesto AHORA (se instala desde él): se marca como ya
    # atendido para no abrir una UI nada más instalar.
    write_json(STATE_FILE, {"launched": True, "root": str(dispositivo),
                            "note": "montaje presente durante la instalación"})

    try:
        print("  " + register(cfg))
    except (OSError, RuntimeError) as e:
        print(f"ERROR: {e}")
        return 1
    cfg["task_python"] = python_exe
    write_json(CONFIG_FILE, cfg)
    prune_runtimes(cfg)

    if not args.no_start:
        print("  " + start_now(cfg))

    print(f"\nModo: {args.mode}"
          + ("" if args.mode == "ui" else
             " (con las parejas y el intervalo del servicio, que viven en el "
             "dispositivo)"))
    print(f"Config y diario del vigilante: {HOST_DIR}")
    print("El disparo se arma al desconectar el dispositivo: la próxima vez que lo "
          "conectes (y desbloquees) se lanzará runsync.")
    print(f'Comprobar: python "{SELF_COPY}" status')
    return 0


def cmd_uninstall(_args: argparse.Namespace) -> int:
    """Quita el vigilante de este equipo; el dispositivo no se toca."""
    for m in unregister():
        print(f"  {m}")
    msg = stop_running_watcher()
    if msg:
        print(f"  {msg}")
    if HOST_DIR.exists():
        try:
            shutil.rmtree(HOST_DIR)
            print(f"  Eliminado {HOST_DIR}")
        except OSError as e:
            print(f"  Aviso: no he podido borrar {HOST_DIR}: {e}")
    print(f"Desinstalado. El dispositivo no se ha tocado (el fichero {CONTROL_FILE} sigue "
          f"ahí; puedes borrarlo si no vas a usar esto en ningún equipo).")
    return 0


def registered_state() -> str:
    """Devuelve una frase con lo que el sistema tiene registrado del vigilante."""
    if IS_WIN:
        res = run_quiet(["schtasks", "/Query", "/TN", TASK_NAME])
        return (f"tarea '{TASK_NAME}': registrada" if res.returncode == 0
                else f"tarea '{TASK_NAME}': NO registrada")
    bits = []
    if UNIT_FILE.exists():
        res = run_quiet(["systemctl", "--user", "is-enabled", UNIT_NAME])
        bits.append(f"unidad '{UNIT_NAME}': {res.stdout.strip() or 'presente'}")
    if DESKTOP_FILE.exists():
        bits.append(f"autostart: {DESKTOP_FILE}")
    return "; ".join(bits) or "sin servicio ni autostart registrados"


def copia_al_dia() -> bool:
    """Indica si la copia del vigilante en este equipo es este mismo `penwatch.py`.

    Llamado desde el dispositivo (la ventana, o `penwatch status` desde
    `.prdrive/`), compara la copia que corre en el equipo con la que trae el
    dispositivo. Nada la pone al día salvo `install`, así que tras actualizar
    el dispositivo el equipo puede seguir con la anterior.

    Desde la propia copia no hay con qué comparar, y sin poder leerse a sí
    mismo tampoco: en los dos casos `True`, no se acusa a nadie sin pruebas.
    Sin copia en el equipo, `False`: lo que el sistema tenga registrado apunta
    a un fichero que no existe.
    """
    propio = Path(__file__).resolve()
    if propio == SELF_COPY.resolve():
        return True
    try:
        mio = propio.read_bytes()
    except OSError:
        return True
    try:
        return SELF_COPY.read_bytes() == mio
    except OSError:
        return False


LABEL_WIDTH = 23
"""Ancho de la columna de etiquetas de `status`.

La CLI y la UI de runsync pintan lo mismo sin repetir el formato.
"""


def _python_row(cfg: dict) -> str:
    """Devuelve con qué Python arranca el vigilante: el suyo o el del sistema."""
    exe = cfg.get("python_exe") or "(sin apuntar)"
    runtime = cfg.get("runtime")
    if runtime:
        return f"copia propia del de {runtime.get('key')}: {exe}"
    nota = cfg.get("runtime_note")
    return f"el del equipo: {exe}" + (f" — {nota}" if nota else "")


def _disparo_row(state: dict) -> str:
    """Devuelve el último disparo: cuándo fue y cómo acabó.

    Un disparo puede no haber lanzado nada a propósito (ya había ventana
    abierta o servicio en marcha) y eso no es un fallo: poner «FALLÓ» mandaría
    a buscar una avería que no existe.
    """
    cuando = state.get("last_launch") or "(ninguno)"
    if state.get("last_skip"):
        return f"{cuando} — sin lanzar: {state['last_skip']}"
    if state.get("last_launch_ok", True) is False:
        return f"{cuando} (FALLÓ)"
    return cuando


def status_rows() -> list[tuple[str, str]]:
    """Devuelve qué hay instalado y cómo está, como pares `(etiqueta, valor)`.

    Una etiqueta vacía es una línea suelta, sin columna. Devolver filas en vez
    de imprimirlas permite que la UI de runsync enseñe exactamente lo mismo que
    la línea de comandos sin analizar texto.
    """
    cfg = read_json(CONFIG_FILE)
    state = read_json(STATE_FILE)
    filas = [
        ("Directorio en el equipo",
         f"{HOST_DIR} {'(OK)' if HOST_DIR.exists() else '(NO EXISTE)'}"),
        ("Registro en el sistema", registered_state()),
    ]
    if not cfg:
        filas.append(("", "Sin configuración: este equipo no tiene el vigilante instalado."))
    else:
        # Parejas e intervalo solo los traen los `watch.json` antiguos, y la
        # copia vieja que los lee los usa: se enseñan mientras estén.
        filas += [
            ("Usuario registrado", f"{cfg.get('user')}"),
            ("Modo", f"{cfg.get('mode')}"
                     + (f"  parejas={','.join(cfg['pairs'])}" if cfg.get("pairs") else "")
                     + (f"  intervalo={cfg['interval']:g}m" if cfg.get("interval") else "")),
            ("Sondeo", f"cada {cfg.get('poll_seconds', POLL_SECONDS):g}s"),
            ("Instalado", f"{cfg.get('installed')} desde {cfg.get('installed_from')}"),
            ("Python del vigilante", _python_row(cfg)),
            ("Dispositivo esperado (id)",
             cfg.get("device_id") or f"(solo por presencia de {CONTROL_FILE})"),
        ]
        if not copia_al_dia():
            filas.append(("", "La copia del vigilante de este equipo no es la de "
                              "este dispositivo: reinstálalo para ponerla al día."))

    pid = int(state.get("watcher_pid") or -1)
    root = find_pen(cfg)
    filas += [
        ("Vigilante", f"vivo (pid {pid})" if pid_alive(pid) else "parado"),
        ("Último disparo", _disparo_row(state)),
        ("Disparo armado", "no (dispositivo ya atendido)" if state.get("launched") else "sí"),
        ("Dispositivo ahora mismo", str(root) if root else _cerrado_row(cfg)),
    ]
    return filas


def _cerrado_row(cfg: dict) -> str:
    """Devuelve si, sin dispositivo a la vista, está puesto pero cifrado y cerrado."""
    vestibule = find_vestibule(cfg)
    return (f"cifrado y cerrado, en {vestibule}" if vestibule is not None
            else "no detectado")


def log_tail(lines: int = 10) -> list[str]:
    """Devuelve las últimas líneas del diario del vigilante, si lo hay."""
    try:
        if not LOG_FILE.exists():
            return []
        return LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    except OSError:
        return []


def probe_rows() -> list[tuple[str, str]]:
    """Devuelve `(raíz candidata, qué se ha encontrado en ella)`."""
    cfg = read_json(CONFIG_FILE)
    filas = []
    for root in candidate_roots(cfg):
        try:
            if (not (root / CONTROL_FILE).is_file()
                    and (root / VESTIBULE_MARKER).is_file()):
                device_id = vestibule_id(root)
                note = ("dispositivo cifrado, cerrado"
                        + (f" (id {device_id[:8]}…)" if device_id else " (sin id)"))
            elif not (root / CONTROL_FILE).is_file():
                note = f"sin {CONTROL_FILE}"
            elif not (root / STRUCT_MARKER).is_file():
                note = f"{CONTROL_FILE} OK, pero falta {STRUCT_MARKER}"
            else:
                device_id = control_id(root)
                note = f"{CONTROL_FILE} OK" + (f" (id {device_id[:8]}…)" if device_id else " (sin id)")
        except OSError as e:
            note = f"no legible ({e.__class__.__name__})"
        filas.append((str(root), note))
    return filas


def detected_pen() -> Path | None:
    """Devuelve la raíz del dispositivo con la configuración instalada, o `None`."""
    return find_pen(read_json(CONFIG_FILE))


def cmd_status(_args: argparse.Namespace) -> int:
    """Imprime qué hay instalado y la cola del diario."""
    for label, value in status_rows():
        print(f"{label:<{LABEL_WIDTH}} : {value}" if label else value)
    tail = log_tail()
    if tail:
        print(f"\n--- últimas {len(tail)} líneas de {LOG_FILE.name} ---")
        for line in tail:
            print("  " + line)
    return 0


def cmd_probe(_args: argparse.Namespace) -> int:
    """Imprime dónde busca el dispositivo y qué encuentra."""
    print(f"Buscando el fichero de control '{CONTROL_FILE}' en la raíz de:")
    for root, note in probe_rows():
        print(f"  {root:<28} {note}")
    root = detected_pen()
    print(f"\nPen detectado: {root if root else 'ninguno'}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Ejecuta el bucle del vigilante; es lo que lanza la tarea."""
    return watch_loop(once=args.once)


def main() -> int:
    """Atiende la línea de comandos del vigilante.

    Los subcomandos son `install`, `uninstall`, `status`, `probe` y `run`.
    """
    ap = argparse.ArgumentParser(
        description="Arranque automático de runsync al conectar el dispositivo.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("install", help="Instala el vigilante en ESTE equipo.")
    p.add_argument("--mode", choices=["ui", "sync", "daemon"], default="ui",
                   help="Qué hacer al detectar el dispositivo (por defecto: ui). "
                        "Las parejas y el intervalo son los del servicio, en el "
                        "dispositivo.")
    p.add_argument("--poll", type=float, default=POLL_SECONDS,
                   help="Segundos entre sondeos del dispositivo (por defecto: 5).")
    p.add_argument("--extra-root", action="append", default=[],
                   help="Ruta extra donde buscar el dispositivo (repetible).")
    p.add_argument("--no-start", action="store_true",
                   help="Registra el vigilante pero no lo arranca todavía.")
    p.set_defaults(func=cmd_install)

    sub.add_parser("uninstall", help="Quita el vigilante de ESTE equipo."
                   ).set_defaults(func=cmd_uninstall)
    sub.add_parser("status", help="Qué hay instalado y si se ve el dispositivo ahora."
                   ).set_defaults(func=cmd_status)
    sub.add_parser("probe", help="Solo detección: dónde busca y qué encuentra."
                   ).set_defaults(func=cmd_probe)

    p = sub.add_parser("run", help="El bucle del vigilante (lo llama la tarea).")
    p.add_argument("--once", action="store_true",
                   help="Una sola pasada y salir (para probar).")
    p.set_defaults(func=cmd_run)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
