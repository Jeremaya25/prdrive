#!/usr/bin/env python3
"""
La ventana se dibuja a la densidad real de la pantalla.

Un proceso que no declara ser consciente de los ppp recibe de Windows una
pantalla de mentira —en un 4K al 200 %, 1472x920 a 96 ppp en lugar de 2944x1840
a 192— y el compositor **estira** después el mapa de bits hasta el panel de
verdad. Todo sale borroso, y no hay tamaño de letra que lo arregle: la letra se
está pintando con la mitad de píxeles de los que hay.

Declarada la densidad, `tk scaling` pasa de 1,33 a 2,67 y crece solo todo lo que
va en puntos, que es toda la tipografía. Lo que NO crece es lo que va en píxeles
sueltos, y ahí están los dos daños que este test vigila: una fila de tabla más
baja que su propia letra la recorta, y un párrafo con el ancho de corte en
píxeles se queda en una columna de la mitad de ancho.

Se comprueba también el origen, no solo el efecto: que ningún módulo de `ui/`
vuelva a escribir esas dos medidas como un entero suelto.
"""

from __future__ import annotations

import re
import sys

from _harness import REPO, Checks

c = Checks("densidad: la ventana se dibuja a los ppp de la pantalla")

from ui import theme  # noqa: E402


# --- 1. el proceso se declara consciente, y antes de que exista ningún Tk ---
#
# Va lo primero del fichero a propósito: Tk lee la densidad al arrancar su
# intérprete y no la vuelve a mirar, así que un `Tk()` anterior a esta llamada
# dejaría el test verde midiendo un intérprete que ya nació ciego.
if sys.platform == "win32":
    import ctypes

    theme.nitidez()
    theme.nitidez()          # es de proceso: repetirla no puede reventar

    nivel = ctypes.c_int()
    ctypes.windll.shcore.GetProcessDpiAwareness(None, ctypes.byref(nivel))
    c("el proceso deja de ser «no consciente de ppp»", nivel.value != 0, True)
else:
    print("  (saltado) la ceguera a los ppp es cosa de Windows")

try:
    import tkinter as tk
    from tkinter import font as tkfont
    from tkinter import ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())


# --- 2. una medida del diseño crece con la escala ---------------------------
#
# 1,3333 es `tk scaling` a 96 ppp, que es la densidad para la que están pensadas
# las medidas del diseño; 2,6667 es la misma pantalla al 200 %.
for escala, esperado in ((1.3333, 760), (2.6667, 1521)):
    raiz.tk.call("tk", "scaling", escala)
    c(f"medida(760) son {esperado} px con la escala en {escala}",
      round(raiz.winfo_pixels(theme.medida(760)) / 3), round(esperado / 3))


# --- 3. la fila de la tabla cabe la letra que la pinta ----------------------
#
# `rowheight` va en píxeles sueltos: con 28 fijos y una letra de 37 px de alto
# —Segoe UI 10 al 200 %—, la tabla de parejas recorta sus propias filas.
for escala in (1.3333, 2.6667):
    raiz.tk.call("tk", "scaling", escala)
    theme._puestos.clear()               # `apply` se hace una vez por intérprete
    theme.apply(raiz)
    alto_fila = int(ttk.Style(raiz).lookup("Treeview", "rowheight"))
    alto_letra = tkfont.Font(root=raiz, font=theme.fuente()).metrics("linespace")
    c(f"la fila ({alto_fila} px) cabe la letra ({alto_letra} px) con la escala en {escala}",
      alto_fila >= alto_letra, True)

raiz.destroy()


# --- 4. y que no vuelva a colarse una de esas dos medidas en píxeles --------
#
# El efecto se arregla una vez; el hábito vuelve. Estas dos opciones son las
# únicas de `ui/` que miden en píxeles algo que compite con el texto, así que
# aquí se prohíbe el entero suelto y se obliga a `theme.medida()`.
sueltos = []
for fuente_py in sorted((REPO / "ui").glob("*.py")):
    for n, linea in enumerate(fuente_py.read_text(encoding="utf-8").splitlines(), 1):
        if re.search(r"\b(wraplength|rowheight)\s*=\s*\d", linea):
            sueltos.append(f"{fuente_py.name}:{n}")
c("ningún wraplength/rowheight en píxeles sueltos en ui/", sueltos, [])

raise SystemExit(c.report())
