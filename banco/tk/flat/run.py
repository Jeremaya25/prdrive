"""Un arranque en frío de un escenario del prototipo `tk-flat` (Tk con ttk plano, 97 widgets en Parejas).

Uso (a través de `entrada.py`): flat.run <start-main|cold-parejas|open-parejas> [--captura RUTA.png]

Variables: BENCH_T0 (`time.time()` justo antes de lanzar), BENCH_OUT (dónde escribir la línea de
resultado), BANCO_FUENTES (la letra de la 0.7.1), BANCO_CAPTURA (ruta de `banco/captura.py`).
Los tiempos son los de `ronda.py`: de Python arrancando a la ventana enseñada y con `update()` hecho.

Portado a Windows: antes del primer `Tk()` se declara la densidad (`utiles.nitidez()`) y las ventanas se
enseñan con el velo de DWM (`utiles.ensenar()`), como hace la aplicación real. Solo el prototipo plano.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402  (carga Xft y la letra antes de tkinter)
import utiles  # noqa: E402
from core import Ctx, cargar_datos, contar_widgets, tk  # noqa: E402

import flat_app as mod  # noqa: E402

CANDIDATO = "tk-flat"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    escenario = args[0]
    captura = sys.argv[sys.argv.index("--captura") + 1] if "--captura" in sys.argv else None
    tema = "claro"
    t0_bench = float(os.environ.get("BENCH_T0") or core.T_PROC)

    t = time.perf_counter()
    datos = cargar_datos()
    core.marca("datos", t)
    t = time.perf_counter()
    utiles.nitidez()                       # Windows: la densidad, antes del primer Tk()
    raiz = tk.Tk()
    raiz.withdraw()
    core.marca("Tk()", t)
    t = time.perf_counter()
    ctx = Ctx(raiz, tema)
    raiz.configure(background=ctx.th.PAPEL)
    core.marca("ctx", t)
    detalle = {"u": round(ctx.u, 3), "xft_preload": core.XFT, "noto_resuelta": ctx.xft_real,
               "tema": tema, "arranque_python_ms": round((core.T_PROC - t0_bench) * 1000, 1),
               "tk": str(raiz.tk.call("info", "patchlevel")),
               "tk_scaling": round(float(raiz.tk.call("tk", "scaling")), 4),
               "pantalla": f"{raiz.winfo_screenwidth()}x{raiz.winfo_screenheight()}",
               "fontsystem": str(raiz.tk.call("::tk::pkgconfig", "get", "fontsystem"))}

    def mostrar(top, construir, titulo):
        """Construye en `top` (retirada), la centra y la enseña ya pintada.

        Devuelve los ms de construir, los de enseñar y lo construido."""
        top.title(titulo)
        top.configure(background=ctx.th.PAPEL)
        top.resizable(False, False)
        a = time.perf_counter()
        obj = construir(top)
        b = time.perf_counter()
        top.update_idletasks()
        w, h = top.winfo_reqwidth(), top.winfo_reqheight()
        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        libre = sh - int(os.environ.get("LEAN_MARGEN", "90"))          # lo que cabe: barra de título, panel…
        if h > libre and hasattr(mod, "encajar"):                       # más alta que la pantalla: visor con barra
            mod.encajar(ctx, top, obj, libre)
            top.update_idletasks()
            w, h = top.winfo_reqwidth(), top.winfo_reqheight()
        x, y = max(0, (sw - w) // 2), max(0, (sh - h) // 2)
        top.geometry(f"{w}x{h}+{x}+{y}")
        utiles.ensenar(top)
        top.update()
        c = time.perf_counter()
        return round((b - a) * 1000, 1), round((c - b) * 1000, 1), obj

    win = {}
    if escenario == "start-main":
        construir_ms, pintar_ms, win["l"] = mostrar(raiz, lambda top: mod.principal(ctx, top, datos, None), "Sincronizar")
        ms = (time.time() - t0_bench) * 1000
        pantalla = raiz
    elif escenario == "cold-parejas":
        top = tk.Toplevel(raiz)
        top.withdraw()
        construir_ms, pintar_ms, win["l"] = mostrar(top, lambda tp: mod.parejas(ctx, tp, datos), "Parejas")
        ms = (time.time() - t0_bench) * 1000
        pantalla = top
    elif escenario == "open-parejas":
        _, _, win["l"] = mostrar(raiz, lambda top: mod.principal(ctx, top, datos, None), "Sincronizar")
        detalle["start_main_ms"] = round((time.time() - t0_bench) * 1000, 1)
        # En un proceso ya en marcha: de la petición («Parejas…») a la pantalla pintada.
        time.sleep(0.05)
        raiz.update()
        t = time.perf_counter()
        top = tk.Toplevel(raiz)
        top.withdraw()
        construir_ms, pintar_ms, win["p"] = mostrar(top, lambda tp: mod.parejas(ctx, tp, datos), "Parejas")
        ms = (time.perf_counter() - t) * 1000
        pantalla = top
    else:
        raise SystemExit(f"escenario desconocido: {escenario}")

    detalle.update({"construir_ms": construir_ms, "enseñar_ms": pintar_ms, "rss_mb": utiles.rss_mb(),
                    "widgets": contar_widgets(pantalla if escenario != "open-parejas" else raiz),
                    "tiempos": core.TIEMPOS})
    try:
        detalle["mapped"] = sum(1 for w in _todos(pantalla) if w.winfo_ismapped())
        detalle["images"] = len(raiz.image_names())
    except Exception:                                    # noqa: BLE001
        pass
    utiles.escribir(escenario, round(ms, 1), detalle)
    if captura:
        info = core.foto(pantalla, captura)
        utiles.escribir("_captura", 0, {"file": os.path.basename(captura), "info": info})
    raiz.destroy()


def _todos(raiz):
    pila, salida = [raiz], []
    while pila:
        w = pila.pop()
        for h in w.winfo_children():
            salida.append(h)
            pila.append(h)
    return salida


if __name__ == "__main__":
    main()
