#!/usr/bin/env python3
"""
tk.py — La interfaz gráfica (Tkinter).

Es la que se usa cuando se llega por doble clic en `runsync.pyw`, es decir sin
consola detrás: por eso aquí no basta con elegir, hace falta además poder
enseñar la salida de la sincronización y preguntar sí/no, cosas que en el modo
consola hace la propia terminal.

`import tkinter` va dentro de cada función a propósito, no arriba: importar este
módulo no puede fallar en un equipo sin tkinter, porque el fallo tiene que
saltar cuando se intenta abrir la ventana, que es cuando `ui.start()` puede
recogerlo y caer al menú de consola.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading

from common import model
from common.model import Config

from . import Choice, pair_status_notes, prefs

TITLE = "PerePen Sync"


class TkFrontend:
    """El frontend gráfico. Ver el protocolo `ui.Frontend`."""

    def ask(self, config: Config, startup_msg: str | None) -> Choice | None:
        return main_window(config, startup_msg)

    def approve_resync(self, pending: list[str]) -> bool:
        from tkinter import messagebox
        root = root_oculto()
        answer = messagebox.askyesno(
            TITLE,
            "Estas parejas requieren --resync (primera vez, baseline perdido o "
            "filtros cambiados):\n\n  " + "\n  ".join(pending) +
            "\n\nEl resync compara ambos lados y fija la referencia; no borra por "
            "diferencias.\n¿Ejecutarlo ahora? (si no, esas parejas se saltarán)")
        root.destroy()
        return bool(answer)

    def info(self, msg: str) -> None:
        from tkinter import messagebox
        root = root_oculto()
        messagebox.showinfo(TITLE, msg)
        root.destroy()

    def run_sync(self, title: str, args: list[str]) -> int:
        return output_window(title, [sys.executable, str(model.SYNC_PY), *args])


def root_oculto():
    """Un Tk invisible en mitad de la pantalla, del que colgar un messagebox suelto.

    Los messagebox se colocan respecto a su ventana padre, y un Tk recién creado
    está en la esquina superior izquierda: sin mover el padre, el aviso sale
    arrinconado aunque no se vea la ventana de la que cuelga."""
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    root.geometry(f"+{root.winfo_screenwidth() // 2}+{root.winfo_screenheight() // 2}")
    return root


def centrar(win, parent=None) -> None:
    """Coloca una ventana en el centro: de su padre si lo hay, si no de la pantalla.

    El `update_idletasks()` no es opcional: hasta que Tk no ha resuelto la
    disposición, `winfo_width()` vale 1 y el centro saldría a ojo."""
    win.update_idletasks()
    ancho = max(win.winfo_width(), win.winfo_reqwidth())
    alto = max(win.winfo_height(), win.winfo_reqheight())
    pantalla_x, pantalla_y = win.winfo_screenwidth(), win.winfo_screenheight()

    if parent is not None and parent.winfo_ismapped():
        x = parent.winfo_rootx() + (parent.winfo_width() - ancho) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - alto) // 2
        # Un diálogo puede ser bastante mayor que su padre —la pantalla de
        # parejas lo es—, así que centrado sobre un padre pegado a un borde se
        # saldría. Solo se recoloca si el padre está en la pantalla principal:
        # con dos monitores las coordenadas pueden ser negativas, y ahí
        # "corregir" sería arrastrar el diálogo a la otra pantalla.
        if 0 <= parent.winfo_rootx() < pantalla_x:
            x = max(0, min(x, pantalla_x - ancho))
            y = max(0, min(y, pantalla_y - alto))
    else:
        x = max(0, (pantalla_x - ancho) // 2)
        # Un pelín por encima del centro geométrico, que es donde el ojo lo
        # espera y deja sitio por abajo para los diálogos hijos.
        y = max(0, (pantalla_y - alto) // 2 - alto // 8)
    win.geometry(f"+{x}+{y}")


def modal(parent, title: str):
    """Un diálogo hijo, todavía OCULTO. Se enseña con `mostrar()`.

    Nace oculto porque hasta que no están puestos todos los widgets no se sabe
    cuánto ocupa, y sin saberlo no se puede centrar. Enseñarlo antes sería verlo
    aparecer en una esquina y pegar el salto al centro."""
    import tkinter as tk
    dlg = tk.Toplevel(parent)
    dlg.title(f"{TITLE} — {title}")
    dlg.transient(parent)
    dlg.resizable(False, False)
    dlg.withdraw()
    return dlg


def mostrar(dlg, parent=None) -> None:
    """Centra el diálogo sobre su padre, lo enseña y espera a que se cierre.

    El `grab_set()` va aquí y no en `modal()` porque Tk no deja capturar una
    ventana que no está visible, y por eso `deiconify()` lleva detrás un
    `update_idletasks()`: sin él el mapeo puede seguir pendiente. Si aun así
    fallara, se sigue: un diálogo sin captura es un incordio, pero uno que no se
    abre es un cuelgue."""
    import tkinter as tk
    centrar(dlg, parent)
    dlg.deiconify()
    dlg.update_idletasks()
    try:
        dlg.grab_set()
    except tk.TclError:
        pass
    dlg.wait_window()


def main_window(config: Config, startup_msg: str | None) -> Choice | None:
    """La ventana principal: qué parejas, cada cuánto, y qué hacer con ellas.
    Devuelve la elección, o None si se cierra sin elegir.
    Lanza ImportError/TclError si no hay entorno gráfico."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    from . import tk_pairs, tk_watch

    root = tk.Tk()  # TclError aquí si no hay display -> fallback consola
    root.title(TITLE)
    root.resizable(False, False)
    root.withdraw()          # se enseña ya centrada, ver el final de la función
    result: dict = {"choice": None}
    vista: dict = {"config": config, "aviso": startup_msg}

    frame = ttk.Frame(root, padding=12)
    frame.grid(sticky="nsew")

    def recargar() -> None:
        """El config ha cambiado bajo nuestros pies: releerlo y repintar.

        Si ha quedado ilegible se dice y se conserva el anterior en pantalla, que
        es mejor que quedarse con una ventana en blanco."""
        try:
            vista["config"] = model.load_config()
        except model.ConfigError as e:
            messagebox.showerror(TITLE, f"El config no se puede leer:\n\n{e}")
            return
        vista["aviso"] = None
        render()
        centrar(root)   # quitar o añadir parejas le cambia el alto

    def render() -> None:
        for hijo in frame.winfo_children():
            hijo.destroy()

        config = vista["config"]
        names = config.names
        notes = pair_status_notes(config)
        d_pairs, d_interval, memo = prefs.startup_defaults(config)
        row = 0

        if vista["aviso"]:
            ttk.Label(frame, text=vista["aviso"], foreground="#775500",
                      wraplength=340, justify="left").grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
            row += 1

        ttk.Label(frame, text="Parejas:").grid(row=row, column=0, sticky="w")
        row += 1
        if memo:
            ttk.Label(frame, text=memo, foreground="#666666").grid(
                row=row, column=0, columnspan=2, sticky="w", padx=(12, 0))
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
            if kind not in ("manual", "daemon"):
                result["choice"] = Choice(kind)
                root.destroy()
                return
            # El intervalo se recoge también en "manual": ahí no se usa, pero
            # forma parte de lo que se recuerda para la próxima vez.
            try:
                minutes = max(1.0, float(interval_var.get().replace(",", ".")))
            except ValueError:
                minutes = d_interval
            result["choice"] = Choice(kind, tuple(sel), minutes)
            root.destroy()

        # Configuración arriba, separada: no son cosas que se ejecuten, son
        # pantallas de las que se vuelve aquí.
        ajustes = ttk.Frame(frame)
        ajustes.grid(row=row, column=0, columnspan=2, pady=(12, 0), sticky="w")
        ttk.Button(ajustes, text="Parejas…",
                   command=lambda: tk_pairs.open_dialog(root, vista["config"])
                   and recargar()).grid(row=0, column=0, padx=3)
        ttk.Button(ajustes, text="Arranque automático…",
                   command=lambda: tk_watch.open_dialog(root, vista["config"])).grid(row=0, column=1, padx=3)
        row += 1

        ttk.Separator(frame, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=8)
        row += 1

        buttons = ttk.Frame(frame)
        buttons.grid(row=row, column=0, columnspan=2)
        ttk.Button(buttons, text="Sincronizar ahora",
                   command=lambda: choose("manual")).grid(row=0, column=0, padx=3)
        ttk.Button(buttons, text="Iniciar servicio",
                   command=lambda: choose("daemon")).grid(row=0, column=1, padx=3)
        ttk.Button(buttons, text="Doctor",
                   command=lambda: choose("doctor")).grid(row=0, column=2, padx=3)
        ttk.Button(buttons, text="Salir",
                   command=root.destroy).grid(row=0, column=3, padx=3)

    render()
    centrar(root)
    root.deiconify()
    root.mainloop()
    return result["choice"]


def output_window(title: str, cmd: list[str], parent=None) -> int:
    """Ejecuta una orden y muestra su salida en una ventana con desplazamiento.

    Sustituye a la consola cuando no la hay, así que la usan tanto sync.py como
    penwatch.py: recibe la orden entera y no supone a quién llama. Cerrar la
    ventana a mitad de faena corta el proceso (bisync se recupera con --recover
    en la siguiente pasada).

    Con `parent` se cuelga de una ventana existente en vez de crear un Tk nuevo:
    tkinter no lleva bien dos intérpretes a la vez, y desde un diálogo ya hay uno
    en marcha."""
    import tkinter as tk
    from tkinter import ttk

    proc = subprocess.Popen(
        cmd,
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

    if parent is None:
        root = tk.Tk()
        esperar = root.mainloop
    else:
        root = tk.Toplevel(parent)
        root.transient(parent)
        esperar = root.wait_window
    root.withdraw()          # igual que los diálogos: se enseña ya colocada
    root.title(f"{TITLE} — {title}")
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
                    root.title(f"{TITLE} — {title} — {verdict}")
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
    centrar(root, parent)
    root.deiconify()
    root.update_idletasks()
    if parent is not None:
        try:
            root.grab_set()  # después de enseñarla: Tk no captura lo que no se ve
        except tk.TclError:
            pass
    root.after(120, poll)
    esperar()
    if proc.poll() is None:
        proc.terminate()
    return state["rc"] if state["rc"] is not None else 1
