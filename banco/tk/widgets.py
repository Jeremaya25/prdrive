"""Microbenchmark del coste de un widget: cuánto cuestan N filas de `ttk.Label` + `ttk.Button`.

Uso (a través de `entrada.py`): widgets <plain|drawn> <N>

Un proceso nuevo por (modo, N). Se miden, en un `Toplevel` retirado, la creación y
colocación (`grid`) de N filas de un `ttk.Label` y un `ttk.Button` y, a
continuación, enseñarlo (`utiles.ensenar`, con el velo de DWM en Windows) y un
`update()`. Escenario `plain-N` o `drawn-N` del candidato `tk-widgets`.

  plain  los estilos de clam de serie (`theme_use("clam")`), con la densidad
         declarada en Windows y el Tk con Xft en Linux, igual que la aplicación.
  drawn  los estilos dibujados de la 0.7.1, aplicados con el `ui.theme.apply()` REAL
         del árbol de `BENCH_APP` (fuera del cronómetro: solo se mide la parte de
         los widgets).

Responde a «cuánto cuesta un widget en Windows y en Linux»: `por_widget_ms` es
`ms / (2 N)`. Una sola columna de filas, sin visor: con N grande la ventana es
más alta que la pantalla y solo se pinta lo visible, que es lo que pasaría en la
aplicación; `mapped` dice cuántos widgets quedaron mapeados.
"""
import os
import sys
import time

T_DRIVER = time.time()
T0 = float(os.environ.get("BENCH_T0") or T_DRIVER)

import utiles  # noqa: E402

CANDIDATO = "tk-widgets"


def main():
    modo, n = sys.argv[1], int(sys.argv[2])
    detalle = {"n": n, "modo": modo, "python_startup_ms": round((T_DRIVER - T0) * 1000, 1)}
    if modo == "drawn":
        app = os.path.abspath(os.environ["BENCH_APP"])
        sys.dont_write_bytecode = True        # el árbol del repo no se toca (ya trae sus .pyc)
        sys.path.insert(0, app)
        os.chdir(app)
        import ui  # noqa: F401  (precarga el Tk con Xft en Linux)
        from ui import theme
        theme.nitidez()
    else:
        utiles.tk_con_xft()
        utiles.nitidez()
    import tkinter as tk
    from tkinter import ttk

    raiz = tk.Tk()
    raiz.withdraw()
    a = time.perf_counter()
    if modo == "drawn":
        theme.apply(raiz)
        detalle["apply_ms"] = round((time.perf_counter() - a) * 1000, 1)
    else:
        ttk.Style(raiz).theme_use("clam")
    top = tk.Toplevel(raiz)
    top.withdraw()
    if modo == "drawn":
        top.configure(background=theme.PAPEL)
    top.update_idletasks()

    # --- lo que se mide ---
    t0 = time.perf_counter()
    for i in range(n):
        ttk.Label(top, text=f"Fila {i}").grid(row=i, column=0, sticky="w", padx=4, pady=1)
        ttk.Button(top, text="Abrir").grid(row=i, column=1, padx=4, pady=1)
    t1 = time.perf_counter()
    utiles.ensenar(top)
    top.update()
    t2 = time.perf_counter()
    # ----------------------

    ms = (t2 - t0) * 1000
    hijos = top.winfo_children()
    detalle.update({
        "crear_ms": round((t1 - t0) * 1000, 1), "enseñar_ms": round((t2 - t1) * 1000, 1),
        "widgets": len(hijos), "por_widget_ms": round(ms / max(1, len(hijos)), 3),
        "mapped": sum(1 for w in hijos if w.winfo_ismapped()),
        "images": len(raiz.image_names()),
        "styles": len(raiz.tk.splitlist(raiz.tk.call("ttk::style", "theme", "styles"))),
        "tk": str(raiz.tk.call("info", "patchlevel")),
        "tk_scaling": round(float(raiz.tk.call("tk", "scaling")), 4),
        "pantalla": f"{raiz.winfo_screenwidth()}x{raiz.winfo_screenheight()}",
        "ventana": f"{top.winfo_width()}x{top.winfo_height()}",
        "rss_mb": utiles.rss_mb()})
    utiles.escribir(f"{modo}-{n}", round(ms, 1), detalle)
    raiz.destroy()
