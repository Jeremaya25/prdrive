#!/usr/bin/env python3
"""ui.start(): elegir frontend, y caer a la consola cuando el gráfico no se puede."""

import builtins
import sys
import tempfile
from pathlib import Path

from _harness import Checks, mkcfg

import ui
import ui.console
import ui.tk
from ui import prefs

c = Checks("fachada ui.start()")
prefs.PREFS = Path(tempfile.mkdtemp(prefix="perepen-start-")) / "ui_prefs.json"
for _m in (ui, ui.console, ui.tk):
    _m.pair_status_notes = lambda cfg: {}

CFG = mkcfg(["a", "b"], {"pairs": ["a"], "interval_minutes": 5})

try:
    import tkinter as tk
    from tkinter import ttk

    def walk(w):
        for hijo in w.winfo_children():
            yield hijo
            yield from walk(hijo)

    def fake_mainloop(self):
        for w in walk(self):
            if isinstance(w, ttk.Button) and w.cget("text") == "Doctor":
                w.invoke()
                return
    tk.Tk.mainloop = fake_mainloop

    choice, frontend = ui.start(CFG, None)
    c("con entorno gráfico: elección", choice, ui.Choice("doctor"))
    c("con entorno gráfico: frontend", type(frontend).__name__, "TkFrontend")

    # Sin entorno gráfico se cae a la consola y se reimprime el aviso de arranque,
    # porque la ventana que iba a enseñarlo no existe.
    original = ui.tk.TkFrontend.ask
    ui.tk.TkFrontend.ask = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sin display"))
    salida: list[str] = []
    real_input, real_print = builtins.input, builtins.print
    builtins.input = lambda prompt="": "4"
    builtins.print = lambda *a, **k: salida.append(" ".join(str(x) for x in a))
    try:
        choice, frontend = ui.start(CFG, "AVISO DE ARRANQUE")
    finally:
        builtins.input, builtins.print = real_input, real_print
        ui.tk.TkFrontend.ask = original

    c("fallback: elección", choice, ui.Choice("doctor"))
    c("fallback: frontend", type(frontend).__name__, "ConsoleFrontend")
    c("fallback: reimprime el aviso", any("AVISO DE ARRANQUE" in s for s in salida), True)
    c("fallback: y no lo duplica",
      sum(s.count("AVISO DE ARRANQUE") for s in salida), 1)
except tk.TclError as e:
    print(f"  (saltado) sin entorno gráfico: {e}")

# La consola no aprueba resyncs por su cuenta: sync.py hereda stdin y pregunta él.
c("consola no añade --yes", ui.console.ConsoleFrontend().approve_resync(["a"]), False)

sys.exit(c.report())
