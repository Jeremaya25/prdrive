#!/usr/bin/env python3
"""`ui.start()`: elegir frontend, y caer a la consola cuando el gráfico no se puede."""

import builtins
import sys
from pathlib import Path

from _harness import Checks, mkcfg, tmpdir

import ui
import ui.console
import ui.tk
from ui import cifrado, prefs, segundo_plano

c = Checks("fachada ui.start()")
prefs.PREFS = tmpdir("prdrive-start-") / "ui_prefs.json"
for _m in (ui, ui.console, ui.tk):
    _m.pair_status_notes = lambda cfg: {}

CFG = mkcfg(["a", "b"], {"pairs": ["a"], "interval_minutes": 5})

# La ventana se prueba si hay Tk y pantalla; sin una de las dos (el suelo de Python 3.11
# de la CI no tiene `tkinter` ni pantalla) se salta, y la consola se prueba igual abajo.
try:
    import tkinter as tk
    _sonda = tk.Tk()
    _sonda.withdraw()
    _sonda.destroy()
    HAY_TK = True
except Exception as e:                                   # sin Tk o sin entorno gráfico
    print(f"  (saltado) sin entorno gráfico: {e}")
    HAY_TK = False

if HAY_TK:
    from tkinter import ttk

    def walk(w):
        """Recorre los widgets que cuelgan de `w`, en profundidad."""
        for hijo in w.winfo_children():
            yield hijo
            yield from walk(hijo)

    # «Iniciar servicio» es lo único que sale ya de la ventana: sincronizar y el
    # doctor corren dentro, en una salida hija, sin devolver ninguna elección.
    # Se puede pulsar cuando ha llegado la lectura del dispositivo que la
    # ventana hace tras pintarse: aquí, en el sitio y con el primer
    # `update_idletasks()`.
    segundo_plano.lanzar = segundo_plano.en_el_acto
    cifrado.expulsion = lambda **_k: None

    def fake_mainloop(self):
        """Bucle de mentira: deja llegar la lectura, pulsa «Iniciar servicio» y vuelve."""
        self.update_idletasks()
        for w in walk(self):
            if isinstance(w, ttk.Button) and w.cget("text") == "Iniciar servicio":
                w.invoke()
                return
    tk.Tk.mainloop = fake_mainloop

    choice, frontend = ui.start(CFG, None)
    c("con entorno gráfico: elección", choice, ui.Choice("daemon", ("a",), 5.0))
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

# La consola no aprueba resyncs por su cuenta: sync.py hereda stdin y pregunta él.
c("consola no añade --yes", ui.console.ConsoleFrontend().approve_resync(["a"]), False)

sys.exit(c.report())
