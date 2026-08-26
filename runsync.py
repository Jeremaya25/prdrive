#!/usr/bin/env python3
"""
runsync.py — Lanzador del sync del pen.

Sin argumentos abre la UI (paquete `ui/`: Tkinter si se puede, menú de consola si
no) con dos caminos:

  * Sincronizar ahora (todas las parejas o una selección).
  * Iniciar un SERVICIO periódico: un proceso en segundo plano, sin ventana, que
    sincroniza las parejas elegidas cada N minutos.

Este fichero no dibuja nada: le pregunta a `ui` qué se quiere hacer y lo hace. Lo
suyo es el servicio y la coordinación con él.

El servicio solo se detiene en dos casos:
  1. El pen deja de estar conectado (se comprueba cada pocos segundos).
  2. Se vuelve a ejecutar runsync: el lanzador detecta el servicio anterior, le
     pide parar, espera, y muestra la UI inicial de nuevo.

Coordinación servicio <-> lanzador (todo en state/, viaja con el pen):
    daemon.lock.json  <- quién es el servicio (pid, host, arranque, último ciclo)
    daemon.stop       <- su presencia le pide al servicio que pare
    daemon.log        <- diario del servicio (recortado automáticamente)
    ui_prefs.json     <- lo último que se eligió en la UI (lo gestiona ui.prefs)

Esa memoria precarga la UI siguiente y sirve de valor por defecto a --auto, por
delante de [daemon] del TOML. Solo la escribe la UI: --auto y --daemon únicamente
la leen, para que un arranque automático no reescriba lo que decidiste a mano.

Con argumentos, se pasan tal cual a sync.py (así `runsync.bat --doctor` sigue
funcionando), salvo dos flags propios:

  --auto [--interval N] [parejas]  arranca el servicio sin UI y sin preguntar
      nada, con la última elección de la UI (o, si no la hay, con los valores de
      [daemon] del TOML). Es lo que lanza penwatch.py al detectar el pen.
  --daemon                          punto de entrada interno del servicio.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import ui  # noqa: E402
from common import model, store  # noqa: E402
from common.store import pid_alive  # noqa: E402
from ui import prefs  # noqa: E402

SELF = Path(__file__).resolve()
SENTINEL = model.CONFIG_FILE          # si esto no se ve, el pen no está
LOCK = model.STATE_DIR / "daemon.lock.json"
STOP = model.STATE_DIR / "daemon.stop"
DLOG = model.STATE_DIR / "daemon.log"

POLL_SECONDS = 2.0        # cadencia de comprobación de parada / pen ausente
STOP_WAIT_SECONDS = 15.0  # cuánto espera el lanzador a que pare el servicio
DLOG_MAX_BYTES = 256 * 1024
HOST = prefs.HOST

CREATE_NO_WINDOW = model.CREATE_NO_WINDOW
CREATE_NEW_PROCESS_GROUP = 0x00000200


# ---------------------------------------------------------------------------
# Utilidades comunes
# ---------------------------------------------------------------------------

def pen_present() -> bool:
    try:
        return SENTINEL.exists()
    except OSError:
        return False


def read_lock() -> dict | None:
    return store.read_json(LOCK) or None


def write_lock(data: dict) -> None:
    store.write_json(LOCK, data)


def dlog(msg: str) -> None:
    """Diario del servicio. Se abre y cierra en cada línea para no mantener
    ningún descriptor abierto sobre el pen (bloquearía la extracción segura)."""
    line = f"{store.stamp()} {msg}\n"
    try:
        if DLOG.exists() and DLOG.stat().st_size > DLOG_MAX_BYTES:
            tail = DLOG.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]
            DLOG.write_text("\n".join(tail) + "\n", encoding="utf-8")
        with DLOG.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass  # pen ausente o de solo lectura: el diario no es vital


# ---------------------------------------------------------------------------
# Parada del servicio anterior (lado lanzador)
# ---------------------------------------------------------------------------

def stop_previous_daemon() -> str | None:
    """Si hay un servicio registrado, le pide parar y espera. Devuelve un mensaje
    para el usuario, o None si no había nada."""
    info = read_lock()
    if info is None:
        return None

    pid = int(info.get("pid", -1))
    if info.get("host") != HOST or not pid_alive(pid):
        # Rastro de otro equipo (pen extraído sin más) o proceso ya muerto.
        LOCK.unlink(missing_ok=True)
        STOP.unlink(missing_ok=True)
        return (f"Había un registro de un servicio ya inexistente "
                f"(pid {pid}, host {info.get('host')}); limpiado.")

    STOP.touch()
    deadline = time.monotonic() + STOP_WAIT_SECONDS
    while time.monotonic() < deadline:
        if read_lock() is None:
            return f"Servicio anterior (pid {pid}) detenido."
        time.sleep(0.3)

    # No ha contestado a tiempo: probablemente está en mitad de una pareja.
    # Se le deja el daemon.stop puesto (parará al terminarla) y se libera el lock.
    LOCK.unlink(missing_ok=True)
    return (f"El servicio (pid {pid}) está ocupado (¿sincronización en curso?); "
            f"parará al terminar la pareja actual.")


# ---------------------------------------------------------------------------
# El servicio (lado daemon)
# ---------------------------------------------------------------------------

def stop_requested() -> bool:
    try:
        return STOP.exists()
    except OSError:
        return False


def run_pair_quiet(name: str) -> tuple[int, str]:
    """Ejecuta sync.py para una pareja, sin terminal. Con stdin cerrado, las
    preguntas interactivas de sync.py toman el valor por defecto: una pareja que
    requiera --resync se SALTA (a propósito: un resync no se lanza solo)."""
    proc = subprocess.run(
        [sys.executable, str(model.SYNC_PY), name],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        errors="replace",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def daemon_cycle(pairs: list[str], lock_data: dict) -> None:
    results = {}
    for name in pairs:
        if stop_requested() or not pen_present():
            return
        t0 = time.monotonic()
        rc, output = run_pair_quiet(name)
        secs = time.monotonic() - t0
        if rc != 0:
            results[name] = f"ERROR rc={rc}"
            dlog(f"[{name}] FALLÓ (rc={rc}, {secs:.0f}s); salida:")
            for line in output.splitlines()[-12:]:
                dlog(f"[{name}]   {line}")
        elif "saltada" in output.lower():
            results[name] = "saltada (requiere --resync manual)"
            dlog(f"[{name}] saltada: requiere --resync; ejecútalo a mano desde la UI")
        else:
            results[name] = f"OK ({secs:.0f}s)"
            dlog(f"[{name}] OK ({secs:.0f}s)")
    lock_data["last_cycle"] = store.stamp()
    lock_data["last_results"] = results
    write_lock(lock_data)


def daemon_main(pairs: list[str], interval_min: float) -> int:
    # Fuera del pen: mantener el cwd en el USB impediría su extracción segura.
    os.chdir(tempfile.gettempdir())

    STOP.unlink(missing_ok=True)
    lock_data = {
        "pid": os.getpid(),
        "host": HOST,
        "started": store.stamp(),
        "pairs": pairs,
        "interval_min": interval_min,
    }
    write_lock(lock_data)
    dlog(f"servicio iniciado: pid={os.getpid()} host={HOST} "
         f"parejas={','.join(pairs)} intervalo={interval_min:g}m")

    reason = "desconocido"
    try:
        while True:
            if not pen_present():
                reason = "pen no conectado"
                break
            if stop_requested():
                reason = "parada solicitada por el lanzador"
                break
            daemon_cycle(pairs, lock_data)
            wake = time.monotonic() + interval_min * 60
            stop = False
            while time.monotonic() < wake:
                if not pen_present():
                    reason, stop = "pen no conectado", True
                    break
                if stop_requested():
                    reason, stop = "parada solicitada por el lanzador", True
                    break
                time.sleep(POLL_SECONDS)
            if stop:
                break
    finally:
        dlog(f"servicio detenido: {reason}")
        # Limpiar solo lo propio: si el lanzador ya "robó" el lock y hay un
        # servicio nuevo, su registro no se toca.
        info = read_lock()
        if info and info.get("pid") == os.getpid() and info.get("host") == HOST:
            LOCK.unlink(missing_ok=True)
        STOP.unlink(missing_ok=True)
    return 0


def spawn_daemon(pairs: list[str], interval_min: float) -> str:
    cmd = [str(SELF), "--daemon", "--interval", str(interval_min), *pairs]
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "cwd": tempfile.gettempdir(),
    }
    if os.name == "nt":
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        exe = str(pythonw) if pythonw.exists() else sys.executable
        kwargs["creationflags"] = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    else:
        exe = sys.executable
        kwargs["start_new_session"] = True

    proc = subprocess.Popen([exe, *cmd], **kwargs)
    return (f"Servicio iniciado (pid {proc.pid}): {', '.join(pairs)} "
            f"cada {interval_min:g} min.\n"
            f"Se detendrá solo si se extrae el pen o si vuelves a ejecutar runsync.\n"
            f"Diario: {DLOG}")


def run_interactive(extra_args: list[str]) -> int:
    """sync.py en la consola actual, heredando stdin/stdout (preguntas incluidas)."""
    return subprocess.run([sys.executable, str(model.SYNC_PY), *extra_args]).returncode


# ---------------------------------------------------------------------------
# Caminos de entrada
# ---------------------------------------------------------------------------

def ui_flow() -> int:
    """Sin argumentos: parar el servicio anterior, preguntar, y hacer lo pedido."""
    startup_msg = stop_previous_daemon()

    try:
        config = model.load_config()
    except model.ConfigError as e:
        return ui.fatal(str(e))

    choice, frontend = ui.start(config, startup_msg)
    if choice is None:
        return 0

    # Se recuerda para la próxima UI y para --auto. "doctor" no toca la selección
    # de parejas, así que tampoco la sobrescribe.
    if choice.action in ("manual", "daemon"):
        prefs.save_prefs(choice.action, list(choice.pairs), choice.minutes,
                         config.names)

    if choice.action == "daemon":
        frontend.info(spawn_daemon(list(choice.pairs), choice.minutes))
        return 0

    if choice.action == "doctor":
        return frontend.run_sync("Doctor", ["--doctor"])

    args = list(choice.pairs)
    pending = [n for n in ui.pair_status_notes(config) if n in args]
    if pending and frontend.approve_resync(pending):
        args.append("--yes")
    return frontend.run_sync("Sincronización manual", args)


def auto_start(rest: list[str]) -> int:
    """--auto: arranca el servicio sin UI, para quien lo lanza sin nadie delante
    (penwatch.py al conectar el pen, un acceso directo, cron). Las parejas y el
    intervalo salen de la última elección de la UI, y si no hay ninguna, de
    [daemon] del TOML; lo que se indique aquí manda sobre ambos. Solo lee esa
    memoria: un arranque automático nunca reescribe lo decidido a mano.
    Se para antes el servicio anterior, si lo hubiera."""
    interval: float | None = None
    if rest and rest[0] == "--interval":
        try:
            interval = float(rest[1])
        except (IndexError, ValueError):
            return ui.fatal("--interval necesita un número de minutos.")
        rest = rest[2:]

    try:
        config = model.load_config()
    except model.ConfigError as e:
        return ui.fatal(str(e))

    names = config.names
    d_pairs, d_interval, memo = prefs.startup_defaults(config)
    unknown = [n for n in rest if n not in names]
    if unknown:
        dlog(f"--auto: parejas desconocidas, ignoradas: {', '.join(unknown)}")
    pairs = [n for n in rest if n in names] or d_pairs
    if memo and not rest:
        dlog(f"--auto: parejas de la última elección de la UI: {', '.join(pairs)}")

    msg = stop_previous_daemon()
    if msg:
        print(msg)
        dlog(f"--auto: {msg}")
    msg = spawn_daemon(pairs, interval if interval is not None else d_interval)
    print(msg)
    dlog("--auto: " + msg.splitlines()[0])
    return 0


def main() -> int:
    args = sys.argv[1:]

    if args and args[0] == "--auto":
        return auto_start(args[1:])

    if args and args[0] == "--daemon":
        rest = args[1:]
        interval = model.DEFAULT_INTERVAL_MIN
        if rest and rest[0] == "--interval":
            interval = float(rest[1])
            rest = rest[2:]
        if not rest:
            return ui.fatal("--daemon necesita al menos una pareja.")
        return daemon_main(rest, interval)

    if args:
        # Passthrough: runsync.bat --doctor, runsync.bat obsidian --resync, etc.
        # También se para el servicio: va a tocar el mismo estado.
        msg = stop_previous_daemon()
        if msg:
            print(msg)
        return run_interactive(args)

    return ui_flow()


if __name__ == "__main__":
    raise SystemExit(main())
