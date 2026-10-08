"""Maneja la interfaz REAL de Tk de prdrive (0.6.5 o 0.7.1) en su proceso y la cronometra.

Lo lanza `ronda.py` a través de `entrada.py`, con el Python del runtime. Variables:

  BENCH_T0         `time.time()` justo antes de lanzar este proceso
  BENCH_DEVICE     una copia nueva del dispositivo de muestra (su `.prdrive/` lleva el código)
  BENCH_FLOW       parejas | ajustes | wizard | agente
  BENCH_APP        árbol de código que importar en vez de DEVICE/.prdrive (wizard y agente)
  BENCH_SCALE      `tk scaling` forzado en cada nuevo `Tk()` (2.0 = Windows al 150 %)
  BENCH_PNGCACHE   fichero pickle de `icons._PNGS`, cargado antes de arrancar la
                   aplicación (el «y si los PNG estuvieran en disco»)
  BENCH_PNGCACHE_OUT  fichero donde volcar (mezclando) los PNG de este proceso al
                   salir, ya medido; no los carga, así que no altera lo que mide
  BENCH_XFT        ui (`import ui` primero: la 0.7.1 precarga sola su Tk con Xft)
                   precarga (el banco lo precarga como `ui.tk_con_xft`: la 0.6.5)
                   Solo cuenta en Linux; en Windows no hay Xft.
  BENCH_PANES=0    no recorrer los paneles / subdiálogos de «Ajustes» tras medir
  BENCH_OUT        fichero donde van los resultados (un JSON por línea)
  BENCH_CAPTURA    directorio donde capturar cada pantalla (entonces los tiempos no valen)
  BENCH_CAND       nombre del candidato, para el nombre de las capturas
  BANCO_CAPTURA    ruta de `banco/captura.py`

El punto de entrada es el `runsync.py` del propio dispositivo (`ui_flow()`: registro
de la ventana, para el servicio anterior, carga el config, `ui.start` ->
`main_window`) y, para el asistente y el agente, sus funciones de ventana. Solo se
sustituye:
  - `tkinter.Tk.mainloop`: una sonda que `update()`a la ventana enseñada, anota la
    hora, cancela los `after(300)` pendientes, maneja las pantallas y cierra.
  - `tkinter.Misc.wait_window`: `update()`a el diálogo enseñado (el `mostrar()` del
    módulo ya lo centró, enseñó y capturó), anota y lo destruye.
  - `common.catalog.load`: bloquea hasta que el banco lo suelta (un remoto que aún
    no ha contestado), así «Parejas» pinta primero con la copia local, como en un
    dispositivo de verdad; luego se suelta y se mide el repintado.
  - `common.update.check`: sin red.
Nada de los árboles de código se modifica. Los tiempos se escriben a medida que se
miden (`utiles.escribir`).
"""
import os
import sys
import time

T_DRIVER = time.time()
T0 = float(os.environ.get("BENCH_T0") or T_DRIVER)

import threading  # noqa: E402
from pathlib import Path  # noqa: E402

import utiles  # noqa: E402

DEVICE = Path(os.environ["BENCH_DEVICE"]).resolve()
APP = Path(os.environ["BENCH_APP"]).resolve() if os.environ.get("BENCH_APP") else DEVICE / ".prdrive"
SCALE = os.environ.get("BENCH_SCALE") or ""
PNGCACHE = os.environ.get("BENCH_PNGCACHE") or ""
PNGCACHE_OUT = os.environ.get("BENCH_PNGCACHE_OUT") or ""
FLOW = os.environ.get("BENCH_FLOW", "parejas")
XFT = os.environ.get("BENCH_XFT", "ui")
PANES = os.environ.get("BENCH_PANES", "1") != "0"
CAPTURA = os.environ.get("BENCH_CAPTURA") or ""
CAND = os.environ.get("BENCH_CAND", "tk")

NOTES: dict = {"t_driver_ms": round((T_DRIVER - T0) * 1000, 1)}


def ms(a, b):
    return round((b - a) * 1000, 1)


def record(scenario, value_ms, **detail):
    utiles.escribir(scenario, value_ms, detail)


def shot(pantalla, ventana):
    """Captura la ventana tal como se ve en pantalla (solo con BENCH_CAPTURA; tras medir)."""
    if not CAPTURA:
        return
    nombre = f"{CAND}-{pantalla}.png"
    info = utiles.capturar_ventana(ventana, Path(CAPTURA) / nombre)
    utiles.escribir("_captura", 0, {"screen": pantalla, "file": nombre, "info": info})


# ----------------------------------------------------------------------------
# Importes, en el orden en que los hace el punto de entrada real.
# ----------------------------------------------------------------------------
sys.path.insert(0, str(APP))
os.chdir(APP)

if XFT == "precarga":
    NOTES["xft_precargado_por_el_banco"] = utiles.tk_con_xft()

import ui  # noqa: E402,F401  -- lo primero que importa runsync.py (la 0.7.1 precarga aquí Xft)
import tkinter as tk  # noqa: E402
from tkinter import ttk  # noqa: E402

from common import catalog, update  # noqa: E402

if PNGCACHE:
    # El «y si»: los PNG de los iconos los pintó un proceso anterior y se guardaron
    # en disco, así que `icons._foto()` los encuentra en `_PNGS` y solo los decodifica.
    import pickle
    from ui import icons as _icons
    if Path(PNGCACHE).is_file():
        _t = time.perf_counter()
        with open(PNGCACHE, "rb") as _f:
            _icons._PNGS.update(pickle.load(_f))
        NOTES["pngcache_load_ms"] = round((time.perf_counter() - _t) * 1000, 1)
        NOTES["pngcache_entries"] = len(_icons._PNGS)
        NOTES["pngcache_bytes"] = Path(PNGCACHE).stat().st_size

T_IMPORTS = time.time()

# --- sin red ----------------------------------------------------------------
update.check = lambda force=False: (None, None)
CAT_EVENT = threading.Event()
_real_cached = catalog.cached


def _catalogo_que_tarda(raw_local=None):
    """Un remoto que contesta cuando el banco lo dice, con el mismo catálogo."""
    CAT_EVENT.wait(60)
    c = _real_cached()
    if c is None:
        return None, "sin copia"
    try:
        return c._replace(source="remote"), None
    except Exception:                                    # noqa: BLE001
        return c, None


catalog.load = _catalogo_que_tarda


# --- ayudas ------------------------------------------------------------------
def walk(w):
    stack = [w]
    while stack:
        cur = stack.pop()
        yield cur
        try:
            stack += list(cur.winfo_children())
        except Exception:                                # noqa: BLE001
            pass


def counts(w):
    ws = list(walk(w))
    d = {"widgets": len(ws) - 1}
    try:                      # en Windows solo los widgets mapeados tienen HWND
        d["mapped"] = sum(1 for x in ws[1:] if x.winfo_ismapped())
    except Exception:                                    # noqa: BLE001
        pass
    by = {}
    for x in ws[1:]:
        by[x.winfo_class()] = by.get(x.winfo_class(), 0) + 1
    d["by_class"] = dict(sorted(by.items(), key=lambda kv: -kv[1]))
    try:
        d["images"] = len(w.image_names())
    except Exception:                                    # noqa: BLE001
        pass
    try:
        d["styles"] = len(w.tk.splitlist(w.tk.call("ttk::style", "theme", "styles")))
    except Exception:                                    # noqa: BLE001
        pass
    d["rss_mb"] = utiles.rss_mb()
    try:
        d["tk_scaling"] = round(float(w.tk.call("tk", "scaling")), 4)
        d["tk"] = str(w.tk.call("info", "patchlevel"))
        d["pantalla"] = f"{w.winfo_screenwidth()}x{w.winfo_screenheight()}"
    except Exception:                                    # noqa: BLE001
        pass
    return d


def find_button(w, *texts):
    for x in walk(w):
        if isinstance(x, (ttk.Button, tk.Button)):
            try:
                t = str(x.cget("text"))
            except Exception:                            # noqa: BLE001
                continue
            if t in texts:
                return x
    return None


def cancel_afters(root):
    try:
        for p in root.tk.splitlist(root.tk.call("after", "info")):
            root.after_cancel(p)
    except Exception:                                    # noqa: BLE001
        pass


def fontsystem(root):
    try:
        return str(root.tk.call("::tk::pkgconfig", "get", "fontsystem"))
    except Exception:                                    # noqa: BLE001
        return "?"


# --- los ganchos ---------------------------------------------------------------
HOOK: dict = {}


def _wait_window(self, window=None):
    w = window if window is not None else self
    w.update()
    t = time.time()
    handler = HOOK.pop("on_shown", None)
    if handler is not None:
        handler(w, t)
    try:
        if w.winfo_exists():
            w.destroy()
    except tk.TclError:
        pass


tk.Misc.wait_window = _wait_window

PANES_071 = (("reparacion", "Reparación"), ("volumen", "Nombre e icono"),
             ("actualizaciones", "Actualizaciones"), ("configuracion", "Configuración"))
SUBS_065 = (("configuracion", "Configuración…"), ("volumen", "Nombre e icono de la unidad…"),
            ("reparacion", "Reparación…"))


def _encargo_de(dlg):
    s = getattr(dlg, "sondeo", None)
    return s, getattr(s, "_encargo", None)


def on_parejas(dlg, t, t_req, label):
    d = counts(dlg)
    if label == "first":
        record("open-parejas", ms(t_req, t), **d)
        record("cold-parejas", ms(T0, t), start_main_ms=NOTES.get("start_main_ms"),
               widgets=d["widgets"], mapped=d.get("mapped"), images=d.get("images"),
               rss_mb=d["rss_mb"])
        shot("parejas", dlg)
    else:
        NOTES["open_parejas_second_ms"] = ms(t_req, t)
    # El remoto contesta ahora: se mide el repintado que sigue (llegado -> refrescar).
    s, enc = _encargo_de(dlg)
    CAT_EVENT.set()
    if enc is not None and not CAPTURA:
        limite = time.time() + 5
        while not enc.hecho and time.time() < limite:
            time.sleep(0.001)
        try:
            t1 = time.perf_counter()
            s._mirar()
            dlg.update()
            t2 = time.perf_counter()
            NOTES["parejas_remote_arrival_repaint_ms_" + label] = round((t2 - t1) * 1000, 1)
            NOTES["parejas_after_arrival_widgets_" + label] = counts(dlg)["widgets"]
        except Exception as e:                           # noqa: BLE001
            NOTES["arrival_error"] = repr(e)


def drive_parejas(root):
    btn = find_button(root, "Parejas…")
    if btn is None:
        NOTES["error"] = "no hay botón «Parejas…»"
        return
    for label in (("first",) if CAPTURA else ("first", "second")):
        CAT_EVENT.clear()
        t_req = time.time()
        HOOK["on_shown"] = lambda dlg, t, tr=t_req, lb=label: on_parejas(dlg, t, tr, lb)
        btn.invoke()
        CAT_EVENT.set()
        root.update()


def drive_ajustes(root):
    btn = find_button(root, "Ajustes…")
    if btn is None:
        NOTES["error"] = "no hay botón «Ajustes…»"
        return
    t_req = time.time()

    def shown(dlg, t):
        d = counts(dlg)
        record("open-ajustes", ms(t_req, t), **d)
        shot("ajustes", dlg)
        if CAPTURA or not PANES:
            return
        per = {}
        if find_button(dlg, "Reparación") is not None:          # 0.7.1: barra lateral + panel
            for clave, rotulo in PANES_071:
                b = find_button(dlg, rotulo)
                if b is None:
                    per[clave] = None
                    continue
                t0 = time.time()
                b.invoke()
                dlg.update()
                t1 = time.time()
                c = counts(dlg)
                per[clave] = {"ms": ms(t0, t1), "widgets": c["widgets"],
                              "images": c.get("images"), "styles": c.get("styles"),
                              "mapped": c.get("mapped")}
            if per.get("reparacion"):
                record("switch-pane", per["reparacion"]["ms"], from_pane="configuracion",
                       to_pane="reparacion", per_pane=per,
                       widgets=per["reparacion"]["widgets"],
                       mapped=per["reparacion"]["mapped"],
                       images=per["reparacion"]["images"], rss_mb=utiles.rss_mb())
        else:                                                   # 0.6.5: lista -> subdiálogos
            for clave, rotulo in SUBS_065:
                b = find_button(dlg, rotulo)
                if b is None:
                    per[clave] = None
                    continue
                got = {}

                def sub(w, t2, got=got):
                    got["t"] = t2
                    got["c"] = counts(w)
                HOOK["on_shown"] = sub
                t0 = time.time()
                b.invoke()
                HOOK.pop("on_shown", None)
                if "t" in got:
                    per[clave] = {"ms": ms(t0, got["t"]), "widgets": got["c"]["widgets"],
                                  "images": got["c"].get("images"),
                                  "styles": got["c"].get("styles"),
                                  "mapped": got["c"].get("mapped")}
            if per.get("reparacion"):
                record("switch-pane", per["reparacion"]["ms"], from_pane="ajustes-list",
                       to_pane="reparacion",
                       analogue="la 0.6.5 no tiene paneles: «Reparación…» cierra «Ajustes» y "
                                "abre su propio diálogo; esto mide clic -> pintado",
                       per_pane=per, widgets=per["reparacion"]["widgets"],
                       mapped=per["reparacion"]["mapped"],
                       images=per["reparacion"]["images"], rss_mb=utiles.rss_mb())

    HOOK["on_shown"] = shown
    btn.invoke()


def probe(self, n=0):
    root = self
    root.update()
    t = time.time()
    NOTES["start_main_ms"] = ms(T0, t)
    cancel_afters(root)
    d = counts(root)
    d.update(fontsystem=fontsystem(root), python_startup_ms=NOTES["t_driver_ms"],
             imports_ms=ms(T_DRIVER, T_IMPORTS), flow=FLOW)
    if FLOW == "parejas":
        record("start-main", NOTES["start_main_ms"], **d)
        shot("main", root)
    elif FLOW in ("wizard", "agente"):
        record("start-" + FLOW, NOTES["start_main_ms"], **d)
        shot(FLOW, root)
    else:
        NOTES["start_main_detail"] = d
    try:
        if FLOW == "parejas":
            drive_parejas(root)
        elif FLOW == "ajustes":
            drive_ajustes(root)
    except Exception:                                    # noqa: BLE001
        import traceback
        NOTES["error"] = traceback.format_exc()
    cancel_afters(root)
    try:
        root.destroy()
    except tk.TclError:
        pass


tk.Tk.mainloop = probe
tk.Misc.mainloop = probe

if SCALE:
    _orig_tk_init_scale = tk.Tk.__init__

    def _tk_init_scale(self, *a, **k):
        _orig_tk_init_scale(self, *a, **k)
        self.tk.call("tk", "scaling", float(SCALE))
    tk.Tk.__init__ = _tk_init_scale

# ----------------------------------------------------------------------------
# Corre el punto de entrada del dispositivo, como lo haría runsync.bat / runsync.sh.
# ----------------------------------------------------------------------------
sys.argv = [str(APP / "runsync.py")]
try:
    if FLOW == "wizard":
        from ui import tk_install  # noqa: E402
        NOTES["exit"] = tk_install.run_wizard()
    elif FLOW == "agente":
        from ui import tk_agente  # noqa: E402
        NOTES["exit"] = tk_agente.preguntar("PRDRIVE-2", 120)
    else:
        import runsync  # noqa: E402  -- el código de módulo es lo que corre el script al arrancar
        NOTES["exit"] = runsync.main()
except SystemExit as e:
    NOTES["exit"] = e.code
except Exception:                                        # noqa: BLE001
    import traceback
    NOTES["error"] = traceback.format_exc()

CAT_EVENT.set()
if PNGCACHE or PNGCACHE_OUT:
    import pickle
    from ui import icons as _icons
    if PNGCACHE:
        # Cuántos PNG tuvo que pintar este proceso además de los que traía del disco.
        NOTES["pngcache_nuevos"] = len(_icons._PNGS) - NOTES.get("pngcache_entries", 0)
    if PNGCACHE_OUT:
        try:
            _prev = {}
            if Path(PNGCACHE_OUT).is_file():
                with open(PNGCACHE_OUT, "rb") as _f:
                    _prev = pickle.load(_f)
            _prev.update(_icons._PNGS)
            with open(PNGCACHE_OUT, "wb") as _f:
                pickle.dump(_prev, _f, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as e:                           # noqa: BLE001
            NOTES["pngcache_error"] = repr(e)

utiles.escribir("_notes", 0, NOTES)
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)   # sin esperar a hilos de la aplicación que quedaran vivos
