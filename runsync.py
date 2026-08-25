#!/usr/bin/env python3
"""
runsync.py — Lanzador del sync del pen.

Sin argumentos abre una UI mínima (Tkinter si está disponible, menú de consola si
no) con dos caminos:

  * Sincronizar ahora (todas las parejas o una selección).
  * Iniciar un SERVICIO periódico: un proceso en segundo plano, sin ventana, que
    sincroniza las parejas elegidas cada N minutos.

No necesita terminal: lanzado con pythonw (doble clic en runsync.pyw de la raíz
del pen) la salida de las sincronizaciones se muestra en una ventana propia, y la
pregunta de "¿hacer --resync?" es un cuadro de diálogo. Lanzado desde una consola
(runsync.bat, terminal Linux) todo pasa por la consola, como siempre.

El servicio solo se detiene en dos casos:
  1. El pen deja de estar conectado (se comprueba cada pocos segundos).
  2. Se vuelve a ejecutar runsync: el lanzador detecta el servicio anterior, le
     pide parar, espera, y muestra la UI inicial de nuevo.

Coordinación servicio <-> lanzador (todo en state/, viaja con el pen):
    daemon.lock.json  <- quién es el servicio (pid, host, arranque, último ciclo)
    daemon.stop       <- su presencia le pide al servicio que pare
    daemon.log        <- diario del servicio (recortado automáticamente)

Con argumentos, se pasan tal cual a sync.py (así `runsync.bat --doctor` sigue
funcionando), salvo dos flags propios:

  --auto [--interval N] [parejas]  arranca el servicio con los valores de
      [daemon] del TOML, sin UI y sin preguntar nada. Es lo que lanza
      penwatch.py cuando detecta el pen recién conectado.
  --daemon                          punto de entrada interno del servicio.
"""

from __future__ import annotations

import json
import os
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import sync  # reutiliza load_config, STATE_DIR, pair_needs_resync...  # noqa: E402

SYNC_PY = SCRIPT_DIR / "sync.py"
SENTINEL = SCRIPT_DIR / "sync_config.toml"   # si esto no se ve, el pen no está
LOCK = sync.STATE_DIR / "daemon.lock.json"
STOP = sync.STATE_DIR / "daemon.stop"
DLOG = sync.STATE_DIR / "daemon.log"

POLL_SECONDS = 2.0        # cadencia de comprobación de parada / pen ausente
STOP_WAIT_SECONDS = 15.0  # cuánto espera el lanzador a que pare el servicio
DLOG_MAX_BYTES = 256 * 1024
DEFAULT_INTERVAL_MIN = 30.0
HOST = socket.gethostname()

# ¿Hay una consola de verdad detrás? Bajo pythonw, sys.stdout es None (y print()
# se convierte en un no-op silencioso, así que los print sueltos no rompen nada).
HAS_TTY = bool(sys.stdout) and sys.stdout.isatty()


# ---------------------------------------------------------------------------
# Utilidades comunes
# ---------------------------------------------------------------------------

def pen_present() -> bool:
    try:
        return SENTINEL.exists()
    except OSError:
        return False


def pid_alive(pid: int) -> bool:
    """¿Sigue vivo ese proceso? OJO: en Windows NO vale os.kill(pid, 0): con
    cualquier señal que no sea CTRL_C/CTRL_BREAK, os.kill llama a
    TerminateProcess, es decir, MATA el proceso en vez de comprobarlo."""
    if os.name == "nt":
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


def read_lock() -> dict | None:
    try:
        return json.loads(LOCK.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_lock(data: dict) -> None:
    """Escritura atómica: el lanzador puede estar leyendo a la vez."""
    tmp = LOCK.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, LOCK)


def dlog(msg: str) -> None:
    """Diario del servicio. Se abre y cierra en cada línea para no mantener
    ningún descriptor abierto sobre el pen (bloquearía la extracción segura)."""
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n"
    try:
        if DLOG.exists() and DLOG.stat().st_size > DLOG_MAX_BYTES:
            tail = DLOG.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]
            DLOG.write_text("\n".join(tail) + "\n", encoding="utf-8")
        with DLOG.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass  # pen ausente o de solo lectura: el diario no es vital


def fatal(msg: str) -> int:
    """Error irrecuperable, visible aunque no haya consola."""
    if sys.stderr:
        try:
            print(msg, file=sys.stderr)
        except OSError:
            pass
    if not HAS_TTY:
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("PerePen Sync", msg)
            root.destroy()
        except Exception:
            pass
    return 1


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
        [sys.executable, str(SYNC_PY), name],
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
    lock_data["last_cycle"] = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
    lock_data["last_results"] = results
    try:
        write_lock(lock_data)
    except OSError:
        pass


def daemon_main(pairs: list[str], interval_min: float) -> int:
    # Fuera del pen: mantener el cwd en el USB impediría su extracción segura.
    os.chdir(tempfile.gettempdir())

    STOP.unlink(missing_ok=True)
    lock_data = {
        "pid": os.getpid(),
        "host": HOST,
        "started": f"{datetime.now():%Y-%m-%d %H:%M:%S}",
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
    cmd = [str(SCRIPT_DIR / "runsync.py"), "--daemon", "--interval", str(interval_min), *pairs]
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
        CREATE_NO_WINDOW = 0x08000000
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        kwargs["creationflags"] = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    else:
        exe = sys.executable
        kwargs["start_new_session"] = True

    proc = subprocess.Popen([exe, *cmd], **kwargs)
    return (f"Servicio iniciado (pid {proc.pid}): {', '.join(pairs)} "
            f"cada {interval_min:g} min.\n"
            f"Se detendrá solo si se extrae el pen o si vuelves a ejecutar runsync.\n"
            f"Diario: {DLOG}")


# ---------------------------------------------------------------------------
# Datos para la UI
# ---------------------------------------------------------------------------

def pair_status_notes(config: dict) -> dict[str, str]:
    """'requiere resync' junto a las parejas bisync sin baseline válido."""
    notes = {}
    defaults = config.get("defaults", {})
    for p in config.get("pair", []):
        if p.get("mode", "bisync") != "bisync":
            continue
        try:
            needed, _ = sync.pair_needs_resync(p, defaults)
            if needed:
                notes[p["name"]] = "requiere resync"
        except Exception:
            pass
    return notes


def daemon_defaults(config: dict) -> tuple[list[str], float]:
    all_names = [p["name"] for p in config.get("pair", [])]
    dcfg = config.get("daemon", {})
    pairs = [n for n in dcfg.get("pairs", all_names) if n in all_names] or all_names
    return pairs, float(dcfg.get("interval_minutes", DEFAULT_INTERVAL_MIN))


def run_interactive(extra_args: list[str]) -> int:
    """sync.py en la consola actual, heredando stdin/stdout (preguntas incluidas)."""
    return subprocess.run([sys.executable, str(SYNC_PY), *extra_args]).returncode


# ---------------------------------------------------------------------------
# UI Tkinter
# ---------------------------------------------------------------------------

def gui_run_sync(title: str, args: list[str]) -> int:
    """Ejecuta sync.py y muestra su salida en una ventana con desplazamiento.
    Sustituye a la consola cuando no la hay. Cerrar la ventana a mitad de faena
    corta el proceso (bisync se recupera con --recover en la siguiente pasada)."""
    import tkinter as tk
    from tkinter import ttk

    proc = subprocess.Popen(
        [sys.executable, str(SYNC_PY), *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
    )
    q: queue.Queue = queue.Queue()
    DONE = object()

    def reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            q.put(line)
        q.put(DONE)

    threading.Thread(target=reader, daemon=True).start()

    root = tk.Tk()
    root.title(f"PerePen Sync — {title}")
    text = tk.Text(root, width=104, height=30, state="disabled",
                   font=("Consolas" if os.name == "nt" else "monospace", 9))
    scroll = ttk.Scrollbar(root, command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    close_btn = ttk.Button(root, text="Cerrar", command=root.destroy)
    text.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
    scroll.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)
    close_btn.grid(row=1, column=0, columnspan=2, pady=(0, 8))
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    state = {"rc": None}

    def append(line: str) -> None:
        text.configure(state="normal")
        text.insert("end", line)
        text.see("end")
        text.configure(state="disabled")

    def poll() -> None:
        try:
            while True:
                item = q.get_nowait()
                if item is DONE:
                    state["rc"] = proc.wait()
                    verdict = "OK" if state["rc"] == 0 else f"ERROR (código {state['rc']})"
                    append(f"\n=== Terminado: {verdict} ===\n")
                    root.title(f"PerePen Sync — {title} — {verdict}")
                    return
                append(item)
        except queue.Empty:
            pass
        root.after(120, poll)

    def on_close() -> None:
        if state["rc"] is None and proc.poll() is None:
            proc.terminate()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.after(120, poll)
    root.mainloop()
    if proc.poll() is None:
        proc.terminate()
    return state["rc"] if state["rc"] is not None else 1


def gui_ask_resync(pending: list[str]) -> bool:
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    answer = messagebox.askyesno(
        "PerePen Sync",
        "Estas parejas requieren --resync (primera vez, baseline perdido o "
        "filtros cambiados):\n\n  " + "\n  ".join(pending) +
        "\n\nEl resync compara ambos lados y fija la referencia; no borra por "
        "diferencias.\n¿Ejecutarlo ahora? (si no, esas parejas se saltarán)")
    root.destroy()
    return bool(answer)


def gui_info(msg: str) -> None:
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo("PerePen Sync", msg)
    root.destroy()


def tk_ui(config: dict, startup_msg: str | None) -> tuple | None:
    """Devuelve ('manual', parejas) | ('daemon', parejas, minutos) |
    ('doctor',) | None. Lanza ImportError/TclError si no hay entorno gráfico."""
    import tkinter as tk
    from tkinter import ttk

    names = [p["name"] for p in config.get("pair", [])]
    notes = pair_status_notes(config)
    d_pairs, d_interval = daemon_defaults(config)

    root = tk.Tk()  # TclError aquí si no hay display -> fallback consola
    root.title("PerePen Sync")
    root.resizable(False, False)
    result: dict = {"choice": None}

    frame = ttk.Frame(root, padding=12)
    frame.grid(sticky="nsew")
    row = 0

    if startup_msg:
        ttk.Label(frame, text=startup_msg, foreground="#775500",
                  wraplength=340, justify="left").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
        row += 1

    ttk.Label(frame, text="Parejas:").grid(row=row, column=0, sticky="w")
    row += 1
    vars_by_name: dict[str, tk.BooleanVar] = {}
    for name in names:
        var = tk.BooleanVar(value=(name in d_pairs))
        vars_by_name[name] = var
        label = name + (f"   ⚠ {notes[name]}" if name in notes else "")
        ttk.Checkbutton(frame, text=label, variable=var).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=(12, 0))
        row += 1

    ttk.Label(frame, text="Intervalo del servicio (min):").grid(
        row=row, column=0, sticky="w", pady=(10, 0))
    interval_var = tk.StringVar(value=f"{d_interval:g}")
    ttk.Spinbox(frame, from_=1, to=1440, textvariable=interval_var, width=6).grid(
        row=row, column=1, sticky="w", pady=(10, 0))
    row += 1

    def selected() -> list[str]:
        return [n for n in names if vars_by_name[n].get()]

    def choose(kind: str) -> None:
        sel = selected()
        if kind in ("manual", "daemon") and not sel:
            return  # nada marcado, nada que hacer
        if kind == "daemon":
            try:
                minutes = max(1.0, float(interval_var.get().replace(",", ".")))
            except ValueError:
                minutes = d_interval
            result["choice"] = ("daemon", sel, minutes)
        elif kind == "manual":
            result["choice"] = ("manual", sel)
        else:
            result["choice"] = (kind,)
        root.destroy()

    buttons = ttk.Frame(frame)
    buttons.grid(row=row, column=0, columnspan=2, pady=(12, 0))
    ttk.Button(buttons, text="Sincronizar ahora",
               command=lambda: choose("manual")).grid(row=0, column=0, padx=3)
    ttk.Button(buttons, text="Iniciar servicio",
               command=lambda: choose("daemon")).grid(row=0, column=1, padx=3)
    ttk.Button(buttons, text="Doctor",
               command=lambda: choose("doctor")).grid(row=0, column=2, padx=3)
    ttk.Button(buttons, text="Salir",
               command=root.destroy).grid(row=0, column=3, padx=3)

    root.mainloop()
    return result["choice"]


# ---------------------------------------------------------------------------
# UI de consola (fallback)
# ---------------------------------------------------------------------------

def console_ui(config: dict, startup_msg: str | None) -> tuple | None:
    names = [p["name"] for p in config.get("pair", [])]
    notes = pair_status_notes(config)
    d_pairs, d_interval = daemon_defaults(config)

    print("\n=== PerePen Sync ===")
    if startup_msg:
        print(startup_msg)
    for n in names:
        extra = f"   [{notes[n]}]" if n in notes else ""
        print(f"   - {n}{extra}")
    print("\n 1) Sincronizar todo ahora"
          "\n 2) Sincronizar parejas concretas"
          "\n 3) Iniciar servicio periódico"
          "\n 4) Doctor"
          "\n 0) Salir")
    try:
        option = input("Opción: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if option == "1":
        return ("manual", names)
    if option == "2":
        raw = input(f"Parejas (separadas por espacio) [{' '.join(names)}]: ").strip()
        sel = [n for n in raw.split() if n in names] or names
        return ("manual", sel)
    if option == "3":
        raw = input(f"Parejas del servicio [{' '.join(d_pairs)}]: ").strip()
        sel = [n for n in raw.split() if n in names] or d_pairs
        raw = input(f"Intervalo en minutos [{d_interval:g}]: ").strip()
        try:
            minutes = max(1.0, float(raw.replace(",", "."))) if raw else d_interval
        except ValueError:
            minutes = d_interval
        return ("daemon", sel, minutes)
    if option == "4":
        return ("doctor",)
    return None


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def ui_flow() -> int:
    startup_msg = stop_previous_daemon()

    try:
        config = sync.load_config()
    except SystemExit as e:  # load_config hace sys.exit con el mensaje
        return fatal(str(e))

    # UI gráfica si se puede; si no, menú de consola. El tipo de UI decide
    # también dónde vive la salida de las acciones.
    try:
        choice = tk_ui(config, startup_msg)
        graphical = True
    except Exception:
        if startup_msg:
            print(startup_msg)
        choice = console_ui(config, startup_msg=None)
        graphical = False

    if choice is None:
        return 0

    if choice[0] == "daemon":
        _, sel, minutes = choice
        msg = spawn_daemon(sel, minutes)
        if graphical:
            gui_info(msg)
        else:
            print(msg)
        return 0

    if choice[0] == "doctor":
        args = ["--doctor"]
    else:  # manual
        args = list(choice[1])
        if graphical:
            pending = [n for n in pair_status_notes(sync.load_config()) if n in args]
            if pending and gui_ask_resync(pending):
                args.append("--yes")

    if graphical:
        return gui_run_sync("doctor" if choice[0] == "doctor" else "sincronización", args)
    return run_interactive(args)


def auto_start(rest: list[str]) -> int:
    """--auto: arranca el servicio con los valores del TOML y sin UI, para quien
    lo lanza sin nadie delante (penwatch.py al conectar el pen, un acceso
    directo, cron). Las parejas y el intervalo salen de [daemon], salvo que se
    indiquen aquí. Se para antes el servicio anterior, si lo hubiera."""
    interval: float | None = None
    if rest and rest[0] == "--interval":
        try:
            interval = float(rest[1])
        except (IndexError, ValueError):
            return fatal("--interval necesita un número de minutos.")
        rest = rest[2:]

    try:
        config = sync.load_config()
    except SystemExit as e:
        return fatal(str(e))

    names = [p["name"] for p in config.get("pair", [])]
    d_pairs, d_interval = daemon_defaults(config)
    unknown = [n for n in rest if n not in names]
    if unknown:
        dlog(f"--auto: parejas desconocidas, ignoradas: {', '.join(unknown)}")
    pairs = [n for n in rest if n in names] or d_pairs

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
        interval = DEFAULT_INTERVAL_MIN
        if rest and rest[0] == "--interval":
            interval = float(rest[1])
            rest = rest[2:]
        if not rest:
            return fatal("--daemon necesita al menos una pareja.")
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