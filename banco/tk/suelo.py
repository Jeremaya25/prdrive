"""El suelo: lo que cuesta CUALQUIER ventana de Tk en este runtime, sin una línea de prdrive.

Escenario `start-bare` (candidato `tk-bare`): de Python arrancando a una ventana
desnuda pintada (un `ttk.Label` y un `ttk.Button` con el tema por defecto):
arranque de Python, `import tkinter`, `Tk()` y `update()`. En Linux precarga el Tk
con Xft como hace la aplicación; en Windows no hay nada que precargar.
"""
import os
import time

T_DRIVER = time.time()
T0 = float(os.environ.get("BENCH_T0") or T_DRIVER)

import utiles  # noqa: E402


def main():
    t = {}
    a = time.time()
    t["xft_precargado"] = utiles.tk_con_xft()
    import tkinter as tk
    from tkinter import ttk
    t["import_tkinter_ms"] = round((time.time() - a) * 1000, 1)
    a = time.time()
    raiz = tk.Tk()
    t["Tk()_ms"] = round((time.time() - a) * 1000, 1)
    a = time.time()
    ttk.Label(raiz, text="hola").grid()
    ttk.Button(raiz, text="adios").grid()
    raiz.update()
    t["build_and_paint_ms"] = round((time.time() - a) * 1000, 1)
    t["total_ms"] = round((time.time() - T0) * 1000, 1)
    t["python_startup_ms"] = round((T_DRIVER - T0) * 1000, 1)
    t["fontsystem"] = str(raiz.tk.call("::tk::pkgconfig", "get", "fontsystem"))
    t["tk"] = str(raiz.tk.call("info", "patchlevel"))
    t["pantalla"] = f"{raiz.winfo_screenwidth()}x{raiz.winfo_screenheight()}"
    t["widgets"] = 2
    t["mapped"] = sum(1 for w in raiz.winfo_children() if w.winfo_ismapped())
    t["images"] = len(raiz.image_names())
    t["rss_mb"] = utiles.rss_mb()
    utiles.escribir("start-bare", t["total_ms"], t)
    raiz.destroy()
