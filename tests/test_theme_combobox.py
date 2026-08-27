#!/usr/bin/env python3
"""
El desplegable de un Combobox tiene que abrirse.

Su lista es una `listbox` de tk que ttk crea la primera vez que se despliega,
leyendo la base de opciones. `theme.apply()` deja ahí la fuente, y si el valor
no es una lista de Tcl válida —una familia con espacio sin llaves, «Segoe UI
10», que Tcl parte en tres— la creación de la listbox falla,
`ttk::combobox::Post` se corta antes de enseñar nada y el desplegable no se
abre nunca: el usuario se queda con el valor con el que nació.

Nada de esto salta al crear el Combobox, solo al desplegarlo, así que aquí se
despliega de verdad.
"""

import sys

from _harness import Checks

c = Checks("tema: el desplegable del Combobox")

try:
    import tkinter as tk
    from tkinter import ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(0)

from ui import theme

theme.apply(raiz)

# --- la fuente que se deja en la base de opciones la entiende Tcl -----------
for rol in ("texto", "titulo", "dialogo", "seccion", "rotulo", "fuerte",
            "pista", "mono", "mono_pequena", "etiqueta"):
    spec = theme.fuente_tcl(rol)
    try:
        raiz.tk.call("font", "actual", spec)
        problema = ""
    except tk.TclError as e:
        problema = str(e)
    c(f"«{spec}» ({rol}) es una fuente que Tcl entiende", problema, "")

# --- y el desplegable se abre ----------------------------------------------
var = tk.StringVar(value="uno")
combo = ttk.Combobox(raiz, textvariable=var, state="readonly",
                     values=["uno", "dos", "tres"])
combo.pack()
raiz.update()

try:
    raiz.tk.eval(f"ttk::combobox::Post {combo}")
    raiz.update()
    abierto = raiz.tk.eval(f"winfo ismapped {combo}.popdown")
except tk.TclError as e:
    abierto = f"error: {e}"
c("Post despliega la lista", abierto, "1")

if abierto == "1":
    c("la lista trae los tres valores",
      raiz.tk.eval(f"{combo}.popdown.f.l size"), "3")
    raiz.tk.eval(f"ttk::combobox::SelectEntry {combo} 1")
    c("elegir la segunda cambia la variable", var.get(), "dos")

raiz.destroy()
sys.exit(c.report())
