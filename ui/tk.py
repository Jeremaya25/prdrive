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
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        answer = messagebox.askyesno(
            TITLE,
            "Estas parejas requieren --resync (primera vez, baseline perdido o "
            "filtros cambiados):\n\n  " + "\n  ".join(pending) +
            "\n\nEl resync compara ambos lados y fija la referencia; no borra por "
            "diferencias.\n¿Ejecutarlo ahora? (si no, esas parejas se saltarán)")
        root.destroy()
        return bool(answer)

    def info(self, msg: str) -> None:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(TITLE, msg)
        root.destroy()

    def run_sync(self, title: str, args: list[str]) -> int:
        return output_window(title, args)


def main_window(config: Config, startup_msg: str | None) -> Choice | None:
    """La ventana principal: qué parejas, cada cuánto, y qué hacer con ellas.
    Devuelve la elección, o None si se cierra sin elegir.
    Lanza ImportError/TclError si no hay entorno gráfico."""
    import tkinter as tk
    from tkinter import ttk

    names = config.names
    notes = pair_status_notes(config)
    d_pairs, d_interval, memo = prefs.startup_defaults(config)

    root = tk.Tk()  # TclError aquí si no hay display -> fallback consola
    root.title(TITLE)
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
        # El intervalo se recoge también en "manual": ahí no se usa, pero forma
        # parte de lo que se recuerda para la próxima vez.
        try:
            minutes = max(1.0, float(interval_var.get().replace(",", ".")))
        except ValueError:
            minutes = d_interval
        result["choice"] = Choice(kind, tuple(sel), minutes)
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


def output_window(title: str, args: list[str]) -> int:
    """Ejecuta sync.py y muestra su salida en una ventana con desplazamiento.
    Sustituye a la consola cuando no la hay. Cerrar la ventana a mitad de faena
    corta el proceso (bisync se recupera con --recover en la siguiente pasada)."""
    import tkinter as tk
    from tkinter import ttk

    proc = subprocess.Popen(
        [sys.executable, str(model.SYNC_PY), *args],
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
    root.after(120, poll)
    root.mainloop()
    if proc.poll() is None:
        proc.terminate()
    return state["rc"] if state["rc"] is not None else 1
