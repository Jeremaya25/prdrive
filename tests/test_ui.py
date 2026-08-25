#!/usr/bin/env python3
"""Los dos frontends salen precargados con lo que se eligió la última vez."""

import builtins
import sys
import tempfile
from pathlib import Path

from _harness import Checks, mkcfg

import ui
import ui.console
import ui.tk
from ui import prefs

c = Checks("precarga de los frontends")
prefs.PREFS = Path(tempfile.mkdtemp(prefix="perepen-ui-")) / "ui_prefs.json"

# Los frontends hacen 'from . import pair_status_notes', así que el sustituto va
# en cada módulo, no solo en el paquete.
for _m in (ui, ui.console, ui.tk):
    _m.pair_status_notes = lambda cfg: {}

CFG = mkcfg(["upload", "keepass", "obsidian", "perepen"],
            {"pairs": ["obsidian", "keepass"], "interval_minutes": 15})
prefs.save_prefs("manual", ["upload", "keepass"], 12.0, CFG.names)


# --- consola ---------------------------------------------------------------
respuestas = iter(["3", "", ""])
salida: list[str] = []
real_input, real_print = builtins.input, builtins.print
builtins.input = lambda prompt="": (salida.append(prompt), next(respuestas))[1]
builtins.print = lambda *a, **k: salida.append(" ".join(str(x) for x in a))
try:
    choice = ui.console.main_menu(CFG, None)
finally:
    builtins.input, builtins.print = real_input, real_print

texto = "\n".join(salida)
c("consola: propone lo recordado", choice, ui.Choice("daemon", ("upload", "keepass"), 12.0))
c("consola: se lee por nombre de campo",
  (choice.action, list(choice.pairs), choice.minutes), ("daemon", ["upload", "keepass"], 12.0))
c.contains("consola: anuncia el recuerdo", texto, "Precargado con la última elección")
c.contains("consola: parejas por defecto", texto, "[upload keepass]")
c.contains("consola: intervalo por defecto", texto, "[12]")


# --- ventana Tk -------------------------------------------------------------
try:
    import tkinter as tk
    from tkinter import ttk

    def walk(w):
        for hijo in w.winfo_children():
            yield hijo
            yield from walk(hijo)

    marcadas: list[str] = []
    etiquetas: list[str] = []

    def fake_mainloop(self):
        """Sustituye al bucle de eventos: inspecciona y pulsa un botón."""
        for w in walk(self):
            if isinstance(w, ttk.Checkbutton):
                if w.instate(["selected"]):
                    marcadas.append(w.cget("text"))
            elif isinstance(w, ttk.Label):
                etiquetas.append(w.cget("text"))
        for w in walk(self):
            if isinstance(w, ttk.Button) and w.cget("text") == "Sincronizar ahora":
                w.invoke()
                return

    tk.Tk.mainloop = fake_mainloop
    choice = ui.tk.main_window(CFG, None)
    c("tk: casillas precargadas", marcadas, ["upload", "keepass"])
    c("tk: la nota es visible",
      any("Precargado con la última elección" in e for e in etiquetas), True)
    c("tk: 'Sincronizar ahora' arrastra el intervalo",
      choice, ui.Choice("manual", ("upload", "keepass"), 12.0))
except tk.TclError as e:
    print(f"  (saltado) sin entorno gráfico: {e}")

sys.exit(c.report())
