#!/usr/bin/env python3
"""
penwatch.py — Arranque automático al conectar el pen.

Instala EN EL EQUIPO (no en el pen) un vigilante que detecta en qué unidad se ha
montado el pen y lanza `runsync.py` en cuanto es legible. Sin permisos de
administrador: tarea programada de usuario en Windows, servicio de usuario de
systemd en Linux (autostart XDG si no hay systemd).

    python penwatch.py install [--mode ui|sync|daemon] [--pairs a b]
                               [--interval N] [--poll N] [--extra-root RUTA]
    python penwatch.py uninstall     # quita la tarea/servicio y el vigilante
    python penwatch.py status        # qué hay instalado y si ve el pen ahora
    python penwatch.py probe         # solo detección: dónde busca y qué encuentra
    python penwatch.py run [--once]  # el bucle del vigilante (lo llama la tarea)

Cómo se reconoce el pen
-----------------------
Por el fichero de control `PEREPEN` en la RAÍZ de la unidad. Ni la letra ni el
punto de montaje sirven: cambian de equipo a equipo y de un día para otro. El
fichero puede llevar dentro una línea `id=<hex>` (`install` la escribe si el
PEREPEN no existía o estaba vacío; si ya tenía contenido, no lo toca), y entonces
se exige además que el id coincida, para no confundir este pen con otro USB que
también llevara un PEREPEN. Antes de lanzar nada se comprueba que esté
`rclone-sync/runsync.py`: sin eso, la unidad no es este proyecto.

Por qué un vigilante que sondea y no un evento del sistema
----------------------------------------------------------
El pen va cifrado. Windows y Linux avisan de la llegada del DISPOSITIVO, pero el
volumen no se puede leer hasta que se desbloquea (BitLocker/LUKS), lo que puede
tardar lo que tarde el usuario en teclear la contraseña. El evento útil no es
"ha llegado" sino "ya se lee", y eso solo se sabe intentándolo. Sondear un
marcador cuesta un stat cada pocos segundos, funciona igual en los dos sistemas,
y da lo mismo si el pen estaba puesto desde el arranque o se enchufa a media
sesión.

Permanencia
-----------
El vigilante se registra para el USUARIO que ejecuta `install` y arranca solo en
cada inicio de sesión de ese usuario, así que sobrevive a reinicios y apagados
sin volver a tocar nada. En Windows es una tarea con disparador de inicio de
sesión; en Linux, una unidad de usuario con `WantedBy=default.target` (más
`loginctl enable-linger`, que `install` intenta activar, para que también vigile
sin sesión abierta).

Convivencia con un medio que puede desaparecer a media frase
------------------------------------------------------------
  * El vigilante NUNCA escribe en el pen ni se mete dentro de él (ni cwd ni
    ficheros abiertos): eso bloquearía la extracción segura. Su configuración,
    su estado y su diario viven en el equipo.
  * Toda lectura del pen va envuelta en try/except OSError: un volumen cifrado y
    bloqueado, o retirado en mitad de la llamada, responde con error, no con un
    educado "no existe".
  * Solo se lanza runsync cuando el marcador se ha leído bien en dos sondeos
    seguidos, para no arrancar sobre un montaje a medias.
  * Nada se relanza mientras el pen siga puesto: hace falta que desaparezca para
    volver a armar el disparo.

Modos (--mode, se decide al instalar y se guarda en el equipo)
--------------------------------------------------------------
  ui      (por defecto) abre la UI de runsync.py: tú decides qué hacer.
  sync    sincroniza una vez, en silencio, las parejas indicadas (o todas).
  daemon  arranca el servicio periódico con los valores del TOML (runsync --auto).

En los tres casos, una pareja bisync que necesite --resync se SALTA: un resync no
se lanza solo, igual que en el resto del proyecto.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

APP = "PerePenWatch"
TASK_NAME = "PerePenWatch"           # Windows: nombre de la tarea programada
UNIT_NAME = "perepen-watch.service"  # Linux: unidad de usuario de systemd

SCRIPT_DIR = Path(__file__).resolve().parent
CONTROL_FILE = "PEREPEN"                         # en la RAÍZ de la unidad
STRUCT_MARKER = Path("rclone-sync") / "runsync.py"  # lo que se va a lanzar

POLL_SECONDS = 5.0
STABLE_CHECKS = 2            # sondeos seguidos legibles antes de dar el pen por montado
STOP_WAIT_SECONDS = 8.0
LOG_MAX_BYTES = 256 * 1024
LOG_KEEP_LINES = 400

IS_WIN = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200

CONTROL_TEMPLATE = """\
# PEREPEN — fichero de control del pen. NO LO BORRES.
# Es lo que permite reconocer esta unidad se monte donde se monte (F:, /media/...).
# Lo usa rclone-sync/penwatch.py para lanzar la sincronización al conectar el pen.
id={pen_id}
"""


def host_dir() -> Path:
    """Dónde vive el vigilante en el equipo. Por usuario, sin privilegios."""
    if IS_WIN:
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / APP
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "perepen-watch"


HOST_DIR = host_dir()
CONFIG_FILE = HOST_DIR / "watch.json"
STATE_FILE = HOST_DIR / "state.json"
LOG_FILE = HOST_DIR / "penwatch.log"
STOP_FILE = HOST_DIR / "stop"
SELF_COPY = HOST_DIR / "penwatch.py"
TASK_XML_FILE = HOST_DIR / "task.xml"
UNIT_FILE = Path.home() / ".config" / "systemd" / "user" / UNIT_NAME
DESKTOP_FILE = Path.home() / ".config" / "autostart" / "perepen-watch.desktop"


# ---------------------------------------------------------------------------
# Utilidades (todo en el equipo: aquí sí se puede dar por hecho que el disco está)
# ---------------------------------------------------------------------------

def stamp() -> str:
    return f"{datetime.now():%Y-%m-%d %H:%M:%S}"


def log(msg: str) -> None:
    """Diario del vigilante. Se abre y cierra en cada línea; se recorta solo."""
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
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_json(path: Path, data: dict) -> None:
    """Escritura atómica: 'status' puede estar leyendo a la vez."""
    try:
        HOST_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        log(f"no he podido escribir {path.name}: {e}")


def pid_alive(pid: int) -> bool:
    """Duplicado a propósito de runsync.py: el vigilante vive en el equipo y no
    puede importar nada del pen (que puede no estar). OJO: en Windows NO vale
    os.kill(pid, 0), que MATA el proceso en vez de comprobarlo."""
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
    kwargs: dict = {"capture_output": True, "text": True, "errors": "replace"}
    if IS_WIN:
        kwargs["creationflags"] = CREATE_NO_WINDOW
    try:
        return subprocess.run(cmd, **kwargs)
    except OSError as e:
        return subprocess.CompletedProcess(cmd, 127, "", str(e))


# ---------------------------------------------------------------------------
# Detección del pen
#
# No se busca "una letra de unidad" ni "un punto de montaje": se busca el fichero
# de control PEREPEN en la raíz, que es lo único que sobrevive a cambiar de
# equipo, de sistema y de letra.
# ---------------------------------------------------------------------------

_ERRORMODE_SET = False


def windows_roots() -> list[Path]:
    """Raíces de las unidades existentes, sin tocar letras vacías."""
    global _ERRORMODE_SET
    import ctypes
    k32 = ctypes.windll.kernel32
    if not _ERRORMODE_SET:
        # Sin esto, sondear una unidad sin medio puede sacar el diálogo
        # "No hay disco en la unidad" en la cara del usuario.
        k32.SetErrorMode(0x0001 | 0x8000)  # SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX
        _ERRORMODE_SET = True
    DRIVE_REMOVABLE, DRIVE_FIXED = 2, 3
    roots: list[Path] = []
    mask = k32.GetLogicalDrives()
    for i in range(26):
        if not (mask >> i) & 1:
            continue
        root = f"{chr(ord('A') + i)}:\\"
        # Un pen puede presentarse como extraíble o como fijo según el firmware.
        if k32.GetDriveTypeW(root) in (DRIVE_REMOVABLE, DRIVE_FIXED):
            roots.append(Path(root))
    return roots


def _unescape_mount(mp: str) -> str:
    for esc, ch in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
        mp = mp.replace(esc, ch)
    return mp


def posix_roots() -> list[Path]:
    """Puntos de montaje respaldados por un dispositivo de bloque, más los sitios
    donde los escritorios montan lo extraíble."""
    roots: list[Path] = []
    try:
        for line in Path("/proc/self/mounts").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0].startswith("/dev/"):
                roots.append(Path(_unescape_mount(parts[1])))
    except OSError:
        pass  # macOS y demás: se cubre con los directorios de abajo
    for base in ("/media", "/run/media", "/mnt", "/Volumes"):
        try:
            for child in Path(base).iterdir():      # /media/pen
                if not child.is_dir():
                    continue
                roots.append(child)
                try:
                    roots += [g for g in child.iterdir() if g.is_dir()]  # /media/usuario/pen
                except OSError:
                    pass
        except OSError:
            continue
    return roots


def candidate_roots(cfg: dict) -> list[Path]:
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
    """El 'id=' de dentro del PEREPEN, o None si no lleva ninguno.
    Propaga OSError: quien llama decide qué significa no poder leerlo."""
    for line in (root / CONTROL_FILE).read_text(
            encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.lower().startswith("id="):
            return line[3:].strip() or None
    return None


def find_pen(cfg: dict) -> Path | None:
    """La raíz del pen, o None. Cualquier OSError significa 'ahora mismo no': un
    volumen bloqueado responde con error de permisos, no con 'no existe'."""
    want = cfg.get("pen_id")
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


# ---------------------------------------------------------------------------
# Lanzamiento de runsync
# ---------------------------------------------------------------------------

def python_for_launch(cfg: dict) -> str:
    exe = cfg.get("python_exe") or sys.executable
    if IS_WIN:
        # pythonw: sin él, cada lanzamiento abre una consola en la cara.
        w = Path(exe).with_name("pythonw.exe")
        if w.exists():
            return str(w)
    return exe


def launch(root: Path, cfg: dict) -> bool:
    mode = cfg.get("mode", "ui")
    args = [python_for_launch(cfg), str(root / STRUCT_MARKER)]
    if mode == "daemon":
        args.append("--auto")
        if cfg.get("interval"):
            args += ["--interval", str(cfg["interval"])]
        args += list(cfg.get("pairs", []))
    elif mode == "sync":
        args += list(cfg.get("pairs", []))   # sin parejas: todas
    # mode 'ui': runsync.py sin argumentos abre la UI.

    if mode == "ui" and not IS_WIN and not (os.environ.get("DISPLAY") or
                                            os.environ.get("WAYLAND_DISPLAY")):
        log("aviso: modo 'ui' sin DISPLAY; runsync no podrá abrir ventana "
            "(usa --mode daemon o --mode sync en equipos sin escritorio)")

    # cwd en el equipo, NUNCA en el pen: un cwd dentro del pen impide extraerlo.
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


# ---------------------------------------------------------------------------
# El bucle del vigilante
# ---------------------------------------------------------------------------

def watch_loop(once: bool = False) -> int:
    cfg = read_json(CONFIG_FILE)
    poll = max(1.0, float(cfg.get("poll_seconds", POLL_SECONDS)))
    STOP_FILE.unlink(missing_ok=True)

    state = read_json(STATE_FILE)
    state.update({"watcher_pid": os.getpid(), "started": stamp()})
    write_json(STATE_FILE, state)
    log(f"vigilante iniciado (pid {os.getpid()}, modo {cfg.get('mode', 'ui')}, "
        f"sondeo {poll:g}s{', una pasada' if once else ''})")

    stable = 0
    try:
        while True:
            root = find_pen(cfg)

            if root is None:
                if state.get("launched") or state.get("root"):
                    log("pen no disponible; disparo rearmado")
                    state.update({"launched": False, "root": None})
                    write_json(STATE_FILE, state)
                stable = 0
            elif not state.get("launched"):
                stable += 1
                if stable >= (1 if once else STABLE_CHECKS):
                    log(f"pen detectado en {root}")
                    ok = launch(root, cfg)
                    state.update({"launched": ok, "root": str(root),
                                  "last_launch": stamp(), "last_launch_ok": ok})
                    write_json(STATE_FILE, state)
                    # Si el lanzamiento falla no se da por hecho: se reintenta en
                    # ~1 min, por si el pen se estaba desbloqueando todavía.
                    stable = 0 if ok else -int(60 / poll)
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
    """Para el vigilante que hubiera: primero por las buenas (fichero 'stop'),
    y por las malas si no contesta."""
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


# ---------------------------------------------------------------------------
# Registro en el sistema: tarea (Windows) / servicio de usuario (Linux)
#
# Siempre para el USUARIO que ejecuta 'install', y disparado por su inicio de
# sesión: así el vigilante vuelve solo tras un reinicio o un apagado.
# ---------------------------------------------------------------------------

TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>{user}</Author>
    <Description>Vigila la conexion del pen (fichero PEREPEN) y lanza runsync.py.</Description>
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


def current_user() -> str:
    """El usuario que está ejecutando esto; es para quien se registra la tarea."""
    if IS_WIN:
        domain = os.environ.get("USERDOMAIN", "")
        user = os.environ.get("USERNAME", "")
        return f"{domain}\\{user}" if domain and user else (user or getpass.getuser())
    try:
        return getpass.getuser()
    except OSError:
        return os.environ.get("USER", "")


def register_windows(cfg: dict) -> str:
    exe = python_for_launch(cfg)
    user = cfg.get("user") or current_user()
    xml = TASK_XML.format(
        user=xml_escape(user),
        command=xml_escape(exe),
        arguments=xml_escape(f'"{SELF_COPY}" run'),
        workdir=xml_escape(str(HOST_DIR)),
    )
    # schtasks /XML quiere el fichero en UTF-16; en UTF-8 falla con acentos.
    TASK_XML_FILE.write_text(xml, encoding="utf-16")
    res = run_quiet(["schtasks", "/Create", "/TN", TASK_NAME,
                     "/XML", str(TASK_XML_FILE), "/F"])
    if res.returncode != 0:
        # Plan B: la forma simple, que no admite ajustes (con ella Windows puede
        # negarse a arrancar la tarea con el portátil a batería).
        log(f"schtasks /XML ha fallado ({res.stderr.strip() or res.stdout.strip()}); "
            f"probando la forma simple")
        res = run_quiet(["schtasks", "/Create", "/TN", TASK_NAME,
                         "/TR", f'"{exe}" "{SELF_COPY}" run',
                         "/SC", "ONLOGON", "/F"])
        if res.returncode != 0:
            raise RuntimeError(f"no he podido crear la tarea: "
                               f"{res.stderr.strip() or res.stdout.strip()}")
    return (f"Tarea '{TASK_NAME}' creada para {user}: arranca en cada inicio de "
            f"sesión (sobrevive a reinicios).")


UNIT_TEMPLATE = """[Unit]
Description=PerePen — vigila la conexion del pen y lanza runsync.py

[Service]
Type=simple
ExecStart={python} {script} run
Restart=on-failure
RestartSec=10
WorkingDirectory={workdir}

[Install]
WantedBy=default.target
"""


def register_linux(cfg: dict) -> str:
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
        "[Desktop Entry]\nType=Application\nName=PerePen Watch\n"
        f"Exec={python} {SELF_COPY} run\n"
        "X-GNOME-Autostart-enabled=true\nNoDisplay=true\n", encoding="utf-8")
    return (f"Autostart XDG instalado en {DESKTOP_FILE} (no hay systemd de "
            f"usuario): arranca al iniciar el escritorio.")


def unregister() -> list[str]:
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


# ---------------------------------------------------------------------------
# Órdenes
# ---------------------------------------------------------------------------

def pen_root_from_here() -> Path:
    """'install' se ejecuta desde el pen: la raíz es el padre de rclone-sync/."""
    root = SCRIPT_DIR.parent
    if not (root / STRUCT_MARKER).is_file():
        sys.exit(f"'install' hay que ejecutarlo desde el pen: no encuentro "
                 f"{root / STRUCT_MARKER}")
    return root


def ensure_control_file(root: Path) -> str | None:
    """Se asegura de que hay PEREPEN en la raíz y devuelve su 'id'.

    Un PEREPEN que ya traiga contenido NO se toca (es tuyo): el pen se reconocerá
    por su sola presencia. Uno vacío sí se rellena con la plantilla, que no
    pierde nada y añade el id. Si el pen es de solo lectura, se sigue adelante
    sin id.
    """
    path = root / CONTROL_FILE
    try:
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None
        if text is not None and text.strip():
            pen_id = control_id(root)
            print(f"  fichero de control: {path}"
                  + (f" (id {pen_id[:8]}…)" if pen_id else
                     " (sin id: se reconocerá solo por su presencia)"))
            return pen_id
        pen_id = uuid.uuid4().hex
        path.write_text(CONTROL_TEMPLATE.format(pen_id=pen_id), encoding="utf-8")
        verbo = "rellenado" if text is not None else "creado"
        print(f"  fichero de control {verbo}: {path} (id {pen_id[:8]}…)")
        return pen_id
    except OSError as e:
        print(f"  aviso: no he podido leer/escribir {path} ({e}); el pen se "
              f"reconocerá solo por su presencia.")
        return None


def cmd_install(args: argparse.Namespace) -> int:
    pen = pen_root_from_here()
    user = current_user()
    print(f"Pen: {pen}")
    print(f"Usuario: {user}")
    pen_id = ensure_control_file(pen)

    msg = stop_running_watcher()
    if msg:
        print(f"  {msg}")

    HOST_DIR.mkdir(parents=True, exist_ok=True)
    if Path(__file__).resolve() != SELF_COPY.resolve():
        shutil.copy2(__file__, SELF_COPY)

    cfg = {
        "mode": args.mode,
        "pairs": list(args.pairs or []),
        "interval": args.interval,
        "poll_seconds": args.poll,
        "pen_id": pen_id,
        "extra_roots": list(args.extra_root or []),
        "python_exe": sys.executable,
        "user": user,
        "installed": stamp(),
        "installed_from": str(pen),
    }
    write_json(CONFIG_FILE, cfg)

    # El pen está puesto AHORA (se está instalando desde él): se marca como ya
    # atendido para no abrir una UI en la cara nada más instalar.
    write_json(STATE_FILE, {"launched": True, "root": str(pen),
                            "note": "montaje presente durante la instalación"})

    try:
        print("  " + (register_windows(cfg) if IS_WIN else register_linux(cfg)))
    except (OSError, RuntimeError) as e:
        print(f"ERROR: {e}")
        return 1

    if not args.no_start:
        print("  " + start_now(cfg))

    print(f"\nModo: {args.mode}"
          + (f" (parejas: {', '.join(args.pairs)})" if args.pairs else "")
          + (f" (intervalo: {args.interval:g} min)" if args.interval else ""))
    print(f"Config y diario del vigilante: {HOST_DIR}")
    print("El disparo se arma al desconectar el pen: la próxima vez que lo "
          "conectes (y desbloquees) se lanzará runsync.")
    print(f'Comprobar: python "{SELF_COPY}" status')
    return 0


def cmd_uninstall(_args: argparse.Namespace) -> int:
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
    print(f"Desinstalado. El pen no se ha tocado (el fichero {CONTROL_FILE} sigue "
          f"ahí; puedes borrarlo si no vas a usar esto en ningún equipo).")
    return 0


def registered_state() -> str:
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


# Ancho de la columna de etiquetas de 'status'. Se saca aquí para que la CLI y
# la UI de runsync pinten lo mismo sin repetir el formato.
LABEL_WIDTH = 23


def status_rows() -> list[tuple[str, str]]:
    """Qué hay instalado y cómo está, como (etiqueta, valor).

    Una etiqueta vacía es una línea suelta, sin columna. Devolver filas en vez de
    imprimirlas permite que la UI de runsync enseñe exactamente lo mismo que la
    línea de comandos sin tener que analizar texto."""
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
        filas += [
            ("Usuario registrado", f"{cfg.get('user')}"),
            ("Modo", f"{cfg.get('mode')}"
                     + (f"  parejas={','.join(cfg['pairs'])}" if cfg.get("pairs") else "")
                     + (f"  intervalo={cfg['interval']:g}m" if cfg.get("interval") else "")),
            ("Sondeo", f"cada {cfg.get('poll_seconds', POLL_SECONDS):g}s"),
            ("Instalado", f"{cfg.get('installed')} desde {cfg.get('installed_from')}"),
            ("Pen esperado (id)",
             cfg.get("pen_id") or f"(solo por presencia de {CONTROL_FILE})"),
        ]

    pid = int(state.get("watcher_pid") or -1)
    root = find_pen(cfg)
    filas += [
        ("Vigilante", f"vivo (pid {pid})" if pid_alive(pid) else "parado"),
        ("Último disparo", f"{state.get('last_launch') or '(ninguno)'}"
                            f"{'' if state.get('last_launch_ok', True) else ' (FALLÓ)'}"),
        ("Disparo armado", "no (pen ya atendido)" if state.get("launched") else "sí"),
        ("Pen ahora mismo", str(root) if root else "no detectado"),
    ]
    return filas


def log_tail(lines: int = 10) -> list[str]:
    """Las últimas líneas del diario del vigilante, si lo hay."""
    try:
        if not LOG_FILE.exists():
            return []
        return LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    except OSError:
        return []


def probe_rows() -> list[tuple[str, str]]:
    """(raíz candidata, qué se ha encontrado en ella)."""
    cfg = read_json(CONFIG_FILE)
    filas = []
    for root in candidate_roots(cfg):
        try:
            if not (root / CONTROL_FILE).is_file():
                note = f"sin {CONTROL_FILE}"
            elif not (root / STRUCT_MARKER).is_file():
                note = f"{CONTROL_FILE} OK, pero falta {STRUCT_MARKER}"
            else:
                pen_id = control_id(root)
                note = f"{CONTROL_FILE} OK" + (f" (id {pen_id[:8]}…)" if pen_id else " (sin id)")
        except OSError as e:
            note = f"no legible ({e.__class__.__name__})"
        filas.append((str(root), note))
    return filas


def detected_pen() -> Path | None:
    return find_pen(read_json(CONFIG_FILE))


def cmd_status(_args: argparse.Namespace) -> int:
    for label, value in status_rows():
        print(f"{label:<{LABEL_WIDTH}} : {value}" if label else value)
    tail = log_tail()
    if tail:
        print(f"\n--- últimas {len(tail)} líneas de {LOG_FILE.name} ---")
        for line in tail:
            print("  " + line)
    return 0


def cmd_probe(_args: argparse.Namespace) -> int:
    print(f"Buscando el fichero de control '{CONTROL_FILE}' en la raíz de:")
    for root, note in probe_rows():
        print(f"  {root:<28} {note}")
    root = detected_pen()
    print(f"\nPen detectado: {root if root else 'ninguno'}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    return watch_loop(once=args.once)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Arranque automático de runsync al conectar el pen.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("install", help="Instala el vigilante en ESTE equipo.")
    p.add_argument("--mode", choices=["ui", "sync", "daemon"], default="ui",
                   help="Qué hacer al detectar el pen (por defecto: ui).")
    p.add_argument("--pairs", nargs="*", default=[],
                   help="Parejas para los modos sync/daemon (por defecto: todas).")
    p.add_argument("--interval", type=float,
                   help="Minutos entre pasadas en modo daemon (por defecto: el del TOML).")
    p.add_argument("--poll", type=float, default=POLL_SECONDS,
                   help="Segundos entre sondeos del pen (por defecto: 5).")
    p.add_argument("--extra-root", action="append", default=[],
                   help="Ruta extra donde buscar el pen (repetible).")
    p.add_argument("--no-start", action="store_true",
                   help="Registra el vigilante pero no lo arranca todavía.")
    p.set_defaults(func=cmd_install)

    sub.add_parser("uninstall", help="Quita el vigilante de ESTE equipo."
                   ).set_defaults(func=cmd_uninstall)
    sub.add_parser("status", help="Qué hay instalado y si se ve el pen ahora."
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
