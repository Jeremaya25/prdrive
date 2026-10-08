"""Maneja la interfaz REAL de Tk de prdrive (el árbol que toque) en su proceso, la cronometra y la cuenta.

Lo lanza `correr.py` a través de `entrada.py`, con el Python del runtime fijado.
Variables:

  BENCH_T0       `time.time()` justo antes de lanzar este proceso
  BENCH_DEVICE   una copia nueva del dispositivo de muestra (su `.prdrive/` lleva el código)
  BENCH_FLOW     parejas | ajustes | wizard | agente | log
  BENCH_APP      árbol de código que importar en vez de DEVICE/.prdrive (wizard, agente, log)
  BENCH_SCALE    `tk scaling` forzado en cada nuevo `Tk()` (2.0 = Windows al 150 %)
  BENCH_OUT      fichero donde van los resultados (un JSON por línea)
  BENCH_CAPTURA  directorio donde capturar cada pantalla (entonces los tiempos no valen)
  BENCH_NOMBRE   prefijo de los ficheros de captura

El punto de entrada es el `runsync.py` del propio dispositivo (`ui_flow()`: registro
de la ventana, para el servicio anterior, carga el config, `ui.start` ->
`main_window`) y, para el asistente, el agente y el log, sus funciones de ventana.
Nada de los árboles de código se modifica. Solo se sustituye:
  - `tkinter.Tk.mainloop`: una sonda que `update()`a la ventana enseñada, anota la
    hora, maneja las pantallas y cierra.
  - `tkinter.Misc.wait_window`: `update()`a el diálogo enseñado (el `mostrar()` del
    módulo ya lo centró y enseñó), anota y lo destruye.
  - `common.catalog.load`: bloquea hasta que el driver lo suelta (un remoto que aún
    no ha contestado), así «Parejas» pinta primero con la copia local, como en un
    dispositivo de verdad; luego se suelta y se mide el repintado.
  - `common.update.check`: sin red.

Esas sustituciones y los contadores se ponen con un buscador de importaciones
(`_Interceptor`), que actúa cuando la aplicación importa el módulo y no antes: así
el driver no importa por la aplicación nada de lo suyo, y el recuento de módulos
del primer pintado es el que ella carga de verdad (si el driver importara
`common.update`, un `import urllib` perezoso de `update.py` no se vería).

Lo que se mide va por línea JSON en `BENCH_OUT`, en cuanto se mide. `detail.cuentas`
lleva lo determinista de cada momento (no depende de la máquina):
  - `widgets`: los de esa ventana;
  - `tema`: cuántos `<<ThemeChanged>>` (pasadas de `ttk::ThemeChanged`) hubo desde el
    momento anterior; al abrir una pantalla tienen que ser 0;
  - `estilos_tardios`: estilos de ttk que existen ahora y no existían al crearse el
    primer widget ttk;
  - `modulos`: `len(sys.modules)` al llamar a `mainloop()` por primera vez, es
    decir, antes del primer pintado (solo en `start-*`).
"""
import os
import sys
import time

T_DRIVER = time.time()
T0 = float(os.environ.get("BENCH_T0") or T_DRIVER)

import utiles  # noqa: E402  -- solo `os` y `sys`: no cuenta como módulo de la aplicación

DEVICE = os.path.realpath(os.environ["BENCH_DEVICE"])
APP = os.path.realpath(os.environ.get("BENCH_APP") or os.path.join(DEVICE, ".prdrive"))
SCALE = os.environ.get("BENCH_SCALE") or ""
FLOW = os.environ.get("BENCH_FLOW", "parejas")
CAPTURA = os.environ.get("BENCH_CAPTURA") or ""
NOMBRE = os.environ.get("BENCH_NOMBRE", "tk")
LINEAS = 10000
"""Líneas de la salida del flujo `log`."""

NOTES: dict = {"t_driver_ms": round((T_DRIVER - T0) * 1000, 1)}
ESTADO: dict = {"modulos": None, "modulos_lista": None, "tema": 0, "estilos_primero": None,
                "apply": [], "catalogo": None}
LOG: dict = {"t0": None, "t1": None, "n": 0, "listo": False}
HOOK: dict = {}


def ms(a, b):
    return round((b - a) * 1000, 1)


def record(scenario, value_ms, **detail):
    utiles.escribir(scenario, value_ms, detail)


def shot(pantalla, ventana):
    """Captura la ventana tal como se ve en pantalla (solo con BENCH_CAPTURA; tras medir)."""
    if not CAPTURA:
        return
    nombre = f"{NOMBRE}-{pantalla}.png"
    info = utiles.capturar_ventana(ventana, os.path.join(CAPTURA, nombre))
    utiles.escribir("_captura", 0, {"screen": pantalla, "file": nombre, "info": info})


# ----------------------------------------------------------------------------
# Sustituciones y contadores, al importar cada módulo.
# ----------------------------------------------------------------------------
def n_estilos(w):
    return len(w.tk.splitlist(w.tk.call("ttk::style", "theme", "styles")))


def _parche_tkinter(m):
    m.Misc.wait_window = _wait_window
    m.Tk.mainloop = probe
    m.Misc.mainloop = probe
    orig_init = m.Tk.__init__

    def __init__(self, *a, **k):
        orig_init(self, *a, **k)
        if SCALE:
            self.tk.call("tk", "scaling", float(SCALE))
        # Una pasada de `ttk::ThemeChanged` genera el evento en "." y luego en cada
        # widget: solo cuenta el de ".". En Tcl, para no llamar a Python por widget.
        self.tk.eval('set ::prdrive_tema 0; bind . <<ThemeChanged>> '
                     '{+ if {"%W" eq "."} {incr ::prdrive_tema}}')
    m.Tk.__init__ = __init__
    if FLOW == "log":
        insert = m.Text.insert

        def insert_(self, index, chars, *args):
            t = time.perf_counter()
            r = insert(self, index, chars, *args)
            fin = time.perf_counter()
            if LOG["t0"] is None:
                LOG["t0"] = t
            LOG["t1"] = fin
            LOG["n"] += 1
            if "=== Terminado" in str(chars):
                LOG["listo"] = True
            return r
        m.Text.insert = insert_


def _parche_ttk(m):
    orig_init = m.Widget.__init__

    def __init__(self, *a, **k):
        orig_init(self, *a, **k)
        if ESTADO["estilos_primero"] is None:
            try:
                ESTADO["estilos_primero"] = n_estilos(self)
            except Exception:                            # noqa: BLE001
                ESTADO["estilos_primero"] = -1
    m.Widget.__init__ = __init__


def _parche_theme(m):
    orig = getattr(m, "apply", None)
    if orig is None:
        return

    def apply(widget):
        t = time.perf_counter()
        try:
            return orig(widget)
        finally:
            ESTADO["apply"].append(round((time.perf_counter() - t) * 1000, 1))
    m.apply = apply


def _parche_update(m):
    m.check = lambda force=False: (None, None)


def _parche_catalog(m):
    import threading
    evento = threading.Event()
    ESTADO["catalogo"] = evento
    real = m.cached

    def load(raw_local=None):
        """Un remoto que contesta cuando el driver lo dice, con el mismo catálogo."""
        evento.wait(60)
        c = real()
        if c is None:
            return None, "sin copia"
        try:
            return c._replace(source="remote"), None
        except Exception:                                # noqa: BLE001
            return c, None
    m.load = load


PARCHES = {"tkinter": _parche_tkinter, "tkinter.ttk": _parche_ttk, "ui.theme": _parche_theme,
           "common.update": _parche_update, "common.catalog": _parche_catalog}


class _Interceptor:
    """Un buscador de importaciones que, tras cargar un módulo de `PARCHES`, le aplica su parche."""

    def find_spec(self, nombre, ruta=None, destino=None):
        parche = PARCHES.get(nombre)
        if parche is None:
            return None
        import _frozen_importlib_external as externo      # ya cargado: no suma módulos
        spec = externo.PathFinder.find_spec(nombre, ruta)
        if spec is None or spec.loader is None:
            return None
        cargador = spec.loader
        ejecutar = cargador.exec_module

        def exec_module(modulo):
            ejecutar(modulo)
            try:
                parche(modulo)
            except Exception as e:                       # noqa: BLE001
                NOTES.setdefault("errores_parche", []).append(f"{nombre}: {e!r}")
        cargador.exec_module = exec_module
        return spec


sys.path.insert(0, APP)
os.chdir(APP)
sys.meta_path.insert(0, _Interceptor())


# ----------------------------------------------------------------------------
# Ayudas
# ----------------------------------------------------------------------------
def walk(w):
    stack = [w]
    while stack:
        cur = stack.pop()
        yield cur
        try:
            stack += list(cur.winfo_children())
        except Exception:                                # noqa: BLE001
            pass


def tema_nuevo(w):
    """Las pasadas de `<<ThemeChanged>>` desde la última vez que se preguntó."""
    try:
        n = int(w.tk.eval("set ::prdrive_tema"))
    except Exception:                                    # noqa: BLE001
        return None
    d = n - ESTADO["tema"]
    ESTADO["tema"] = n
    return d


def medir(w, con_modulos=False):
    """Lo que se cuenta de una ventana: `cuentas` (determinista) y el resto (se informa)."""
    ws = list(walk(w))
    d = {"widgets": len(ws) - 1}
    cuentas = {"widgets": len(ws) - 1, "tema": tema_nuevo(w)}
    try:
        primero = ESTADO["estilos_primero"]
        d["styles"] = n_estilos(w)
        cuentas["estilos_tardios"] = None if primero in (None, -1) else max(0, d["styles"] - primero)
    except Exception:                                    # noqa: BLE001
        pass
    if con_modulos:
        cuentas["modulos"] = ESTADO["modulos"]
        d["modulos_lista"] = ESTADO["modulos_lista"]
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
    d["rss_mb"] = utiles.rss_mb()
    try:
        d["tk_scaling"] = round(float(w.tk.call("tk", "scaling")), 4)
        d["tk"] = str(w.tk.call("info", "patchlevel"))
        d["pantalla"] = f"{w.winfo_screenwidth()}x{w.winfo_screenheight()}"
    except Exception:                                    # noqa: BLE001
        pass
    d["cuentas"] = cuentas
    return d


def find_button(w, *texts):
    import tkinter as tk
    from tkinter import ttk
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


def apply_ms():
    """Lo que tardó el primer `theme.apply()` del proceso, o None si no se llegó a medir."""
    return ESTADO["apply"][0] if ESTADO["apply"] else None


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
    except Exception:                                    # noqa: BLE001
        pass


# ----------------------------------------------------------------------------
# Los flujos
# ----------------------------------------------------------------------------
PANES = (("reparacion", "Reparación"), ("volumen", "Nombre e icono"),
         ("actualizaciones", "Actualizaciones"), ("configuracion", "Configuración"))


def _encargo_de(dlg):
    s = getattr(dlg, "sondeo", None)
    return s, getattr(s, "_encargo", None)


def on_parejas(dlg, t, t_req):
    d = medir(dlg)
    record("open-parejas", ms(t_req, t), **d)
    record("cold-parejas", ms(T0, t), start_main_ms=NOTES.get("start_main_ms"),
           widgets=d["widgets"], mapped=d.get("mapped"), images=d.get("images"),
           rss_mb=d["rss_mb"])
    shot("parejas", dlg)
    # El remoto contesta ahora: se mide el repintado que sigue (llegado -> refrescar).
    s, enc = _encargo_de(dlg)
    if ESTADO["catalogo"] is not None:
        ESTADO["catalogo"].set()
    if enc is not None and not CAPTURA:
        limite = time.time() + 5
        while not enc.hecho and time.time() < limite:
            time.sleep(0.001)
        try:
            t1 = time.perf_counter()
            s._mirar()
            dlg.update()
            t2 = time.perf_counter()
            record("catalogo-llega", round((t2 - t1) * 1000, 1), **medir(dlg))
        except Exception as e:                           # noqa: BLE001
            NOTES["arrival_error"] = repr(e)


def drive_parejas(root):
    btn = find_button(root, "Parejas…", "Parejas")
    if btn is None:
        NOTES["error"] = "no hay botón «Parejas…»"
        return
    if ESTADO["catalogo"] is not None:
        ESTADO["catalogo"].clear()
    root.update()
    tema_nuevo(root)
    t_req = time.time()
    HOOK["on_shown"] = lambda dlg, t: on_parejas(dlg, t, t_req)
    btn.invoke()
    if ESTADO["catalogo"] is not None:
        ESTADO["catalogo"].set()
    root.update()


def drive_ajustes(root):
    btn = find_button(root, "Ajustes…", "Ajustes")
    if btn is None:
        NOTES["error"] = "no hay botón «Ajustes…»"
        return
    root.update()
    tema_nuevo(root)
    t_req = time.time()

    def shown(dlg, t):
        record("open-ajustes", ms(t_req, t), **medir(dlg))
        shot("ajustes", dlg)
        if CAPTURA:
            return
        if find_button(dlg, "Reparación") is None:
            NOTES["error"] = "«Ajustes» no tiene la barra de apartados"
            return
        for clave, rotulo in PANES:
            b = find_button(dlg, rotulo)
            if b is None:
                NOTES.setdefault("sin_apartado", []).append(clave)
                continue
            dlg.update()
            tema_nuevo(dlg)
            t0 = time.time()
            b.invoke()
            dlg.update()
            t1 = time.time()
            record("pane-" + clave, ms(t0, t1), **medir(dlg))

    HOOK["on_shown"] = shown
    btn.invoke()


def drive_log(root):
    """Espera a que la salida de 10 000 líneas esté en el Text y apunta lo que tardó en meterla."""
    limite = time.time() + 60
    while time.time() < limite and not LOG["listo"]:
        root.update()
        time.sleep(0.005)
    if not LOG["listo"] or LOG["t0"] is None:
        NOTES["error"] = "la ventana de la pasada no llegó a mostrar toda la salida"
        return
    # Del primer `insert` al último: lo que la ventana tarda en tragarse la salida,
    # sin los 120 ms de espera hasta el primer sondeo ni la construcción de la ventana.
    record("log-10k", round((LOG["t1"] - LOG["t0"]) * 1000, 1), inserts=LOG["n"],
           lineas=LINEAS, rss_mb=utiles.rss_mb())
    shot("log", root)


def probe(self, n=0):
    root = self
    # Antes del primer pintado: lo que la aplicación ha importado hasta aquí.
    ESTADO["modulos"] = len(sys.modules)
    ESTADO["modulos_lista"] = sorted(sys.modules)
    root.update()
    t = time.time()
    NOTES["start_main_ms"] = ms(T0, t)
    if FLOW != "log":
        cancel_afters(root)            # el sondeo del log vive de un `after`
    d = medir(root, con_modulos=True)
    d.update(fontsystem=fontsystem(root), python_startup_ms=NOTES["t_driver_ms"], flow=FLOW)
    if ESTADO["apply"]:
        d["apply_llamadas"] = len(ESTADO["apply"])
    if FLOW == "parejas":
        record("start-main", NOTES["start_main_ms"], **d)
        if apply_ms() is not None:
            record("apply-main", apply_ms())
        shot("main", root)
    elif FLOW in ("wizard", "agente"):
        record("start-" + FLOW, NOTES["start_main_ms"], **d)
        if apply_ms() is not None:
            record("apply-" + FLOW, apply_ms())
        shot(FLOW, root)
    try:
        if FLOW == "parejas":
            drive_parejas(root)
        elif FLOW == "ajustes":
            drive_ajustes(root)
        elif FLOW == "log":
            drive_log(root)
    except Exception:                                    # noqa: BLE001
        import traceback
        NOTES["error"] = traceback.format_exc()
    cancel_afters(root)
    try:
        root.destroy()
    except Exception:                                    # noqa: BLE001
        pass


# ----------------------------------------------------------------------------
# Corre el punto de entrada del dispositivo, como lo haría runsync.bat / runsync.sh.
# ----------------------------------------------------------------------------
def guion(*nombres):
    """El primero de esos ficheros que existe en `APP`."""
    for nombre in nombres:
        ruta = os.path.join(APP, nombre)
        if os.path.isfile(ruta):
            return ruta
    raise FileNotFoundError(nombres)


sys.argv = [os.path.join(APP, "runsync.py")]
try:
    if FLOW == "wizard":
        from ui import tk_install  # noqa: E402
        NOTES["exit"] = tk_install.run_wizard()
    elif FLOW == "agente":
        # Como lo lanza el agente: `pregunta.py` si el árbol lo trae y, si no,
        # `agente.py pregunta`. Se compila el guion cada vez, igual que un `python guion`.
        ruta = guion("pregunta.py", "agente.py")
        sys.argv = [ruta, *(["pregunta"] if ruta.endswith("agente.py") else []),
                    "--nombre", "PRDRIVE-2", "--segundos", "120"]
        with open(ruta, encoding="utf-8") as f:
            fuente = f.read()
        exec(compile(fuente, ruta, "exec"), {"__name__": "__main__", "__file__": ruta})
    elif FLOW == "log":
        from ui import tk as uitk  # noqa: E402
        orden = [sys.executable, "-c",
                 f"for i in range({LINEAS}): print('linea %05d de la pasada de prueba: ' % i + 'x' * 70)"]
        NOTES["exit"] = uitk.output_window("Prueba", orden)
    else:
        import runsync  # noqa: E402  -- el código de módulo es lo que corre el script al arrancar
        NOTES["exit"] = runsync.main()
except SystemExit as e:
    NOTES["exit"] = e.code
except Exception:                                        # noqa: BLE001
    import traceback
    NOTES["error"] = traceback.format_exc()

if ESTADO["catalogo"] is not None:
    ESTADO["catalogo"].set()
utiles.escribir("_notes", 0, NOTES)
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)   # sin esperar a hilos de la aplicación que quedaran vivos
