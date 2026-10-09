"""Maneja la interfaz REAL de Tk de prdrive (el árbol que toque) en su proceso, la cronometra y la cuenta.

Lo lanza `correr.py` a través de `entrada.py`, con el Python del runtime fijado.
Variables:

  BENCH_T0       `time.time()` justo antes de lanzar este proceso
  BENCH_DEVICE   una copia nueva del dispositivo de muestra (su `.prdrive/` lleva el código)
  BENCH_FLOW     parejas | ajustes | principal | flota | wizard | agente | log
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
  - `common.fleet.leer`: la flota de muestra (doce dispositivos, `flota_de_muestra()`),
    que llega cuando el driver la suelta, como el catálogo: «Dispositivos» pinta primero
    sin ella y luego se mide lo que cuesta pintarla.
  - `common.update.check`: sin red.
  - `ui.tk.orden_sync` y `ui.tk.preguntar_resync`: ninguna pasada de verdad corre ni
    pregunta nada (la comprobación mide la ventana, no a `sync.py`): la pasada es
    `python -c pass` y el `--resync` se rechaza.
  - `common.store.write_json`: cuenta las escrituras bajo `BENCH_DEVICE` (`escrituras.marcar`).

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
    decir, antes del primer pintado (solo en `start-*`);
  - `escrituras`: las escrituras de `store.write_json` bajo el dispositivo que caben
    dentro del clic de `marcar`.

Cada momento nuevo funciona igual en el árbol del PR y en el de la base (la 0.7.1): lo que
solo el PR ofrece (`root.instantanea`, la lectura compartida de la principal) se usa si
está y se salta si no, y un momento que solo mide el PR se lee «nuevo», nunca falla.

El flujo `flota` abre «Parejas» con el catálogo sin contestar y, desde ella, «Dispositivos» (con
la flota sin llegar: `open-dispositivos`; luego llegando: `llega-flota` y `elegir-dispositivo`) y el
editor de flags de la pareja elegida (`open-flags`). El flujo `wizard` pulsa además «Siguiente» en
«¿Dónde?» y apunta lo que tarda en verse «Dispositivo» (`paso-dispositivo`, con la lectura real de
las unidades del equipo).
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
                "apply": [], "catalogo": None, "flota": None, "escrituras": 0, "cierre": None}
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


FLOTA_DE_MUESTRA = (
    ("Disco del taller", "0.7.1", ("windows-x64", "linux-x64"), 0.1, "largo-a", 3, 5),
    ("pendrive azul", "0.7.1", ("windows-x64", "linux-x64", "linux-arm64"), 0.5, "ok", 0, 4),
    ("Llave de la oficina", "0.7.1", ("windows-x64",), 2, "ok", 0, 2),
    ("SSD de viaje", "0.7.0", ("windows-x64", "linux-x64"), 5, "ok", 0, 5),
    ("Pen de fotos", "0.7.1", ("linux-x64",), 8, "largo-b", 1, 1),
    ("Pendrive rojo", "0.7.1", ("windows-x64",), 20, "ok", 0, 0),
    ("Disco de copias", "0.6.5", ("windows-x64", "windows-arm64"), 30, "ok", 0, 3),
    ("Pen de Marta", "0.7.1", ("windows-x64", "linux-x64"), 50, "largo-c", -1, 2),
    ("Unidad del portátil", "0.7.1", ("linux-x64", "linux-arm64"), 70, "ok", 0, 1),
    ("Pen de pruebas", "0.7.1", ("linux-x64",), 100, "ok", 0, 2),
    ("Disco del trastero", "0.7.0", ("windows-x64",), 140, "ok", 0, 0),
    ("Pen viejo", "0.5.2", ("windows-x64",), 24 * 10, "ok", 0, 3),
)
"""Los doce dispositivos de la flota de muestra, del visto hace menos al visto hace más.

Cada uno: nombre, versión, plataformas, horas desde que se le vio, resultado, días desde su
última pasada buena (0 si no falla, -1 si no consta ninguna) y cuántos equipos ha apuntado (de
0 a `MAX_EQUIPOS`). Tres fallan con un resultado largo, de los que parten en dos líneas en la
ficha; el segundo es ESTE dispositivo (`device_id()` del dispositivo de muestra); y el último
lleva más de una semana sin aparecer (sale apagado). El primero, el que la ventana elige al
llegar, falla y lleva los cinco equipos: es la ficha más alta.
"""

RESULTADOS_LARGOS = {
    "largo-a": "fallo en documentos, fotos, musica, trabajo, notas, videos, escaneos, facturas",
    "largo-b": "fallo en fotos, musica, trabajo, notas, videos, copias-del-taller, escaneos",
    "largo-c": "fallo en documentos, escaneos, facturas, proyectos, presupuestos, contratos",
}
"""El `last_result` de los dispositivos que fallan: lo bastante largo para partir a 440 px."""

EQUIPOS_DE_MUESTRA = ("PORTATIL-ANA", "SOBREMESA-OFICINA", "PC-TALLER", "MACBOOK-LUIS", "NUC-SALON")
"""Los nombres de red que se reparten los dispositivos de la flota de muestra."""


def flota_de_muestra(m, yo: str):
    """Los doce dispositivos de `FLOTA_DE_MUESTRA`, con los tipos del módulo `common.fleet` del árbol.

    Solo usa los campos que tienen todas las versiones (`id`, `nombre`, `version`, `plataformas`,
    `last_seen`, `last_result`, `equipos` y `ultima_buena`). Las fechas se cuentan hacia atrás desde
    ahora, así que lo que sale apagado, lo que falla y lo que se enseña no cambia de una pasada a
    otra, y los widgets de la ficha tampoco.

    Args:
        m: El módulo `common.fleet` del árbol que se mide.
        yo: El `id` de este dispositivo: el de la segunda fila.

    Returns:
        La lista que devolvería `fleet.leer()`, ya ordenada.
    """
    import hashlib
    from datetime import datetime, timedelta
    ahora = datetime.now().replace(microsecond=0)

    def sello(horas: float) -> str:
        return (ahora - timedelta(hours=horas)).strftime("%Y-%m-%d %H:%M:%S")

    flota = []
    for i, (nombre, version, plataformas, hace, resultado, buena, n_equipos) in enumerate(FLOTA_DE_MUESTRA):
        equipos = tuple(m.Equipo(EQUIPOS_DE_MUESTRA[(i + k) % len(EQUIPOS_DE_MUESTRA)],
                                 sello(hace + 7 * k)) for k in range(n_equipos))
        if buena == 0:
            ultima_buena = ""
        else:
            ultima_buena = getattr(m, "SIN_BUENA", "ninguna") if buena < 0 else sello(24 * buena)
        flota.append(m.Dispositivo(
            id=yo if i == 1 else hashlib.sha1(f"bench-flota-{i}".encode()).hexdigest()[:32],
            nombre=nombre, version=version,
            plataformas=plataformas, last_seen=sello(hace),
            last_result=RESULTADOS_LARGOS.get(resultado, resultado), equipos=equipos,
            ultima_buena=ultima_buena))
    return m.ordenar(flota)


def _parche_fleet(m):
    """Que la flota de «Dispositivos» sea la de muestra, y llegue cuando el driver lo diga.

    Como `_parche_catalog`, pero abierta de entrada: solo el flujo `flota` cierra la espera
    (`ESTADO["flota"].clear()`) antes de abrir «Dispositivos», para medir la ventana sin las
    notas y luego su llegada por separado. Sin ese cierre nada espera: ningún otro flujo lee
    la flota, y uno que lo hiciera no debe quedarse parado.
    """
    import threading
    evento = threading.Event()
    evento.set()
    ESTADO["flota"] = evento

    def leer(raw_local=None):
        """La flota de muestra y ningún aviso, tras esperar al driver."""
        evento.wait(60)
        try:
            yo = m.device_id() or "bench-0000-0000-0001"
        except Exception:                                # noqa: BLE001
            yo = "bench-0000-0000-0001"
        return flota_de_muestra(m, yo), None
    m.leer = leer


def _parche_store(m):
    """Cuenta las llamadas a `write_json` cuyo destino está bajo el dispositivo."""
    orig = m.write_json
    raiz = os.path.normcase(DEVICE) + os.sep

    def write_json(path, data):
        try:
            if os.path.normcase(os.path.abspath(os.fspath(path))).startswith(raiz):
                ESTADO["escrituras"] += 1
        except Exception:                                # noqa: BLE001
            pass
        return orig(path, data)
    m.write_json = write_json


def _parche_ui_tk(m):
    """Que ninguna pasada de verdad corra ni pregunte desde la ventana principal.

    La orden de la pasada es `python -c pass`; la pregunta del `--resync` (que
    bloquearía al driver) se contesta que no. Las dos las busca la ventana por su nombre
    en `ui.tk` en cada llamada, así que valen en el árbol de la base y en el del PR.
    """
    m.orden_sync = lambda args: [sys.executable, "-c", "pass"]
    m.preguntar_resync = lambda parent, pending, carpetas=None: False


PARCHES = {"tkinter": _parche_tkinter, "tkinter.ttk": _parche_ttk, "ui.theme": _parche_theme,
           "common.update": _parche_update, "common.catalog": _parche_catalog,
           "common.fleet": _parche_fleet, "common.store": _parche_store, "ui.tk": _parche_ui_tk}


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


def a_la_vista(w):
    """Si el widget y todos sus ascendientes hasta su ventana tienen gestor de geometría.

    Uno escondido con `grid_remove()`, o dentro de uno escondido, no cuenta: la
    ventana principal del PR guarda los bloques que no enseña.
    """
    try:
        while str(w) != str(w.winfo_toplevel()):
            if not w.winfo_manager():
                return False
            w = w.master
    except Exception:                                    # noqa: BLE001
        return False
    return True


def casillas_visibles(root):
    """Las casillas (`ttk.Checkbutton`) de la ventana que se ven, de arriba abajo."""
    from tkinter import ttk
    casillas = [x for x in walk(root) if isinstance(x, ttk.Checkbutton) and a_la_vista(x)]
    return sorted(casillas, key=lambda x: (x.winfo_rooty(), x.winfo_rootx()))


def ventanas_hijas(root):
    """Las ventanas de nivel superior que cuelgan directamente de `root`."""
    return [x for x in root.winfo_children() if x.winfo_class() == "Toplevel"]


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
    ESTADO["cierre"] = time.perf_counter()               # desde aquí se vuelve a la principal
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
    if not CAPTURA:
        elegir_filas(dlg)


def elegir_filas(dlg):
    """Elige otra fila de la lista (solo el resaltado) y luego otra pareja (con su editor).

    `elegir-fila` es `lista.elegir(otra, avisar=False)`: lo que cuesta resaltar. `elegir-pareja`
    es `elegir(otra, avisar=True)`: además comprueba que no se pierda nada escrito y carga la
    pareja en el editor. Las dos acaban con el `update()` que las pinta.
    """
    lista = getattr(dlg, "lista", None)
    orden = list(getattr(lista, "orden", ()))
    if len(orden) < 3:
        NOTES["error"] = f"la lista de «Parejas» tiene {len(orden)} filas: no se puede elegir otra"
        return
    primera = orden[1] if getattr(lista, "elegida", None) != orden[1] else orden[0]
    try:
        dlg.update()
        t0 = time.perf_counter()
        lista.elegir(primera, avisar=False)
        dlg.update()
        t1 = time.perf_counter()
        record("elegir-fila", ms(t0, t1))
        dlg.update()
        t0 = time.perf_counter()
        hecho = lista.elegir(orden[2], avisar=True)
        dlg.update()
        t1 = time.perf_counter()
        record("elegir-pareja", ms(t0, t1), elegida=bool(hecho))
    except Exception:                                    # noqa: BLE001
        import traceback
        NOTES["error"] = traceback.format_exc()


def reabrir_parejas(root, btn):
    """Pulsa «Parejas…» otra vez, con el remoto sin contestar, y apunta cuánto tarda en verse.

    La espera del catálogo se vuelve a cerrar antes y se suelta tras apuntar: si el remoto
    contestara al abrir, el repintado de su llegada (que puede pasar de un segundo) caería
    dentro de lo medido a veces sí y a veces no. Este momento tiene su propio manejador: no
    apunta `open-parejas`, `cold-parejas` ni `catalogo-llega`.
    """
    if ESTADO["catalogo"] is not None:
        ESTADO["catalogo"].clear()
    root.update()
    tema_nuevo(root)
    t_req = time.time()

    def reabierta(dlg, t):
        record("reabrir-parejas", ms(t_req, t), **medir(dlg))
        if ESTADO["catalogo"] is not None:
            ESTADO["catalogo"].set()
    HOOK["on_shown"] = reabierta
    btn.invoke()


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
    if not CAPTURA:
        reabrir_parejas(root, btn)


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
        # Un apartado que ya se vio: lo que cuesta volver a él (se rehace o se enseña el guardado).
        b = find_button(dlg, "Reparación")
        if b is not None:
            dlg.update()
            tema_nuevo(dlg)
            t0 = time.time()
            b.invoke()
            dlg.update()
            t1 = time.time()
            record("pane-otra-vez", ms(t0, t1), **medir(dlg))

    HOOK["on_shown"] = shown
    ESTADO["cierre"] = None
    btn.invoke()
    if ESTADO["cierre"] is not None and not CAPTURA:
        # Desde que se destruye «Ajustes» hasta que la principal queda quieta de nuevo.
        root.update()
        record("volver-ajustes", ms(ESTADO["cierre"], time.perf_counter()))


def llega_instantanea(root):
    """Recoge la lectura compartida de la principal, si el árbol la tiene, y la cronometra.

    Es el patrón de `catalogo-llega`. La espera es con `time.sleep`, sin `update()`: bombear
    el bucle de eventos antes de medir «Parejas» o «Ajustes» correría la precarga de módulos
    (`precargar_a_ratos`) solo en el PR y sesgaría todas las comparaciones. `cancel_afters`
    ya mató el sondeo de la ventana, así que se llama a `_mirar()` a mano: aplica la lectura
    en el hilo de Tk, que es lo que `llega-instantanea` mide (la lectura en sí corre en su
    hilo). Recogerla antes de abrir una pantalla deja la principal como la deja la base desde
    su primer pintado, con todo su contenido. Solo el flujo `principal` apunta el momento.

    El árbol de la 0.7.1 no tiene `instantanea` ni `sondeo_instantanea`: no se hace nada.
    """
    encargo = getattr(root, "instantanea", None)
    sondeo = getattr(root, "sondeo_instantanea", None)
    if encargo is None or sondeo is None:
        return
    limite = time.time() + 5
    while not encargo.hecho and time.time() < limite:
        time.sleep(0.001)
    t0 = time.perf_counter()
    sondeo._mirar()
    root.update()
    t1 = time.perf_counter()
    sondeo.seguir()                # `probe()` lo pausó; las lecturas de después, solas
    if FLOW == "principal" and not CAPTURA:
        record("llega-instantanea", ms(t0, t1), **medir(root))


def con_veredicto(ventana):
    """Si el título de la ventana de la pasada ya dice cómo acabó (`— OK`, `— ERROR (código N)`)."""
    titulo = str(ventana.title())
    return titulo.endswith("— OK") or "— ERROR" in titulo


def drive_principal(root):
    """Marca una pareja, lanza una pasada que no hace nada y vuelve de su ventana.

    `marcar`: el clic en una casilla y el `update()` que lo pinta; la cuenta
    `escrituras.marcar` son las escrituras de `write_json` dentro de ese tramo. La casilla
    se marca (si estaba marcada, antes se desmarca sin cronometrar), así que la selección
    nunca queda vacía: con ninguna pareja «Sincronizar ahora» no hace nada y la 0.7.1 no
    escribe la selección vacía. `sincronizar-ventana`: del clic hasta ver la ventana de la
    pasada. `volver-pasada`: de destruir esa ventana, ya terminada, hasta que la principal
    queda quieta.
    """
    casillas = casillas_visibles(root)
    if not casillas:
        NOTES["error"] = "la ventana principal no tiene ninguna casilla de pareja a la vista"
        return
    casilla = casillas[0]
    if casilla.instate(["selected"]):
        casilla.invoke()
        root.update()
    antes = ESTADO["escrituras"]
    t0 = time.perf_counter()
    casilla.invoke()
    root.update()
    t1 = time.perf_counter()
    record("marcar", ms(t0, t1), cuentas={"escrituras": ESTADO["escrituras"] - antes})

    ahora = find_button(root, "Sincronizar ahora")
    if ahora is None:
        NOTES["error"] = "no hay botón «Sincronizar ahora»"
        return
    limite = time.time() + 5
    while ahora.instate(["disabled"]) and time.time() < limite:
        root.update()
        time.sleep(0.005)
    if ahora.instate(["disabled"]):
        NOTES["error"] = "«Sincronizar ahora» sigue apagado 5 s después de marcar"
        return
    conocidas = {str(x) for x in ventanas_hijas(root)}
    t0 = time.perf_counter()
    ahora.invoke()
    nueva = None
    limite = t0 + 10
    while True:
        nueva = next((x for x in ventanas_hijas(root)
                      if str(x) not in conocidas and x.winfo_viewable()), None)
        if nueva is not None or time.perf_counter() > limite:
            break
        root.update()
    t1 = time.perf_counter()
    if nueva is None:
        NOTES["error"] = "«Sincronizar ahora» no abrió la ventana de la pasada en 10 s"
        return
    record("sincronizar-ventana", ms(t0, t1))

    limite = time.time() + 10
    while not con_veredicto(nueva) and time.time() < limite:
        root.update()
        time.sleep(0.005)
    titulo = str(nueva.title())
    if not titulo.endswith("— OK"):
        NOTES["error"] = f"la pasada de prueba no acabó bien en 10 s: «{titulo}»"
        return
    t0 = time.perf_counter()
    nueva.destroy()
    root.update()
    t1 = time.perf_counter()
    record("volver-pasada", ms(t0, t1))


def anotando(funcion):
    """Que un fallo del manejador de una ventana quede en `NOTES["error"]`.

    Los manejadores de `HOOK["on_shown"]` corren dentro del `invoke()` de un botón, y Tk se
    traga lo que lanza un botón (lo escribe en la salida y sigue): sin esto el momento que
    falta no diría por qué.
    """
    def envuelta(*args, **opciones):
        try:
            return funcion(*args, **opciones)
        except Exception:                                # noqa: BLE001
            import traceback
            NOTES["error"] = traceback.format_exc()
    envuelta.__name__ = funcion.__name__
    return envuelta


def drive_flota(root):
    """Abre «Dispositivos» y el editor de flags desde «Parejas» y apunta lo que cuesta cada cosa.

    «Parejas» se abre con el catálogo sin contestar (la espera se cierra en todo el flujo y se
    suelta al volver): se pinta con la copia local, como en un dispositivo, y lo que llegue
    después no cae dentro de lo medido. De ahí en adelante todo lo hace `en_parejas_de_la_flota`.
    """
    btn = find_button(root, "Parejas…", "Parejas")
    if btn is None:
        NOTES["error"] = "no hay botón «Parejas…»"
        return
    if ESTADO["catalogo"] is not None:
        ESTADO["catalogo"].clear()
    root.update()
    tema_nuevo(root)
    HOOK["on_shown"] = en_parejas_de_la_flota
    btn.invoke()
    if ESTADO["catalogo"] is not None:
        ESTADO["catalogo"].set()
    root.update()


@anotando
def en_parejas_de_la_flota(dlg, t):
    """«Parejas» ya está pintada: de aquí se abre «Dispositivos» y, al volver, el editor de flags."""
    boton = find_button(dlg, "Dispositivos…")
    if boton is None:
        NOTES["error"] = "«Parejas» no tiene el botón «Dispositivos…»"
        return
    if ESTADO["flota"] is not None:
        ESTADO["flota"].clear()                          # las notas llegan cuando el driver lo dice
    dlg.update()
    tema_nuevo(dlg)
    t_req = time.time()
    HOOK["on_shown"] = lambda fdlg, t_visto: en_dispositivos(fdlg, t_visto, t_req)
    boton.invoke()
    abrir_flags(dlg)


@anotando
def en_dispositivos(fdlg, t, t_req):
    """«Dispositivos» recién abierta, sin las notas: se apunta, y luego su llegada y elegir otro.

    `open-dispositivos` es del clic a verla pintada. `llega-flota` es `_mirar()` más el `update()`
    que repinta la tabla y la ficha cuando las notas llegan; la espera a que acabe su hilo es con
    `time.sleep`, sin `update()` (como en `catalogo-llega`): si no, el sondeo de la ventana podría
    recogerlas fuera de lo medido. `elegir-dispositivo` es `tabla.elegir(otra)` y su `update()`.
    """
    record("open-dispositivos", ms(t_req, t), **medir(fdlg))
    shot("dispositivos", fdlg)
    if ESTADO["flota"] is not None:
        ESTADO["flota"].set()
    sondeo, encargo = _encargo_de(fdlg)
    if encargo is None:
        NOTES["error"] = "«Dispositivos» no ha encargado la lectura de la flota (¿ya no tiene `sondeo`?)"
        return
    limite = time.time() + 5
    while not encargo.hecho and time.time() < limite:
        time.sleep(0.001)
    if not encargo.hecho:
        NOTES["error"] = "las notas de la flota no llegaron en 5 s"
        return
    t1 = time.perf_counter()
    sondeo._mirar()
    fdlg.update()
    t2 = time.perf_counter()
    record("llega-flota", ms(t1, t2), **medir(fdlg))
    shot("dispositivos-llena", fdlg)
    if not CAPTURA:
        elegir_dispositivo(fdlg)


def elegir_dispositivo(fdlg):
    """Elige otro dispositivo de la tabla (con su ficha) y apunta lo que tarda en verse."""
    tabla = getattr(fdlg, "tabla", None)
    orden = list(getattr(tabla, "orden", ()))
    if len(orden) < 3:
        NOTES["error"] = f"la tabla de «Dispositivos» tiene {len(orden)} filas: no se puede elegir otra"
        return
    otra = orden[1] if getattr(tabla, "elegida", None) != orden[1] else orden[0]
    fdlg.update()
    t0 = time.perf_counter()
    tabla.elegir(otra)
    fdlg.update()
    t1 = time.perf_counter()
    record("elegir-dispositivo", ms(t0, t1), elegida=getattr(tabla, "elegida", None) == otra)


def abrir_flags(dlg):
    """Despliega «Avanzado» en el editor de «Parejas» y abre el de flags de su pareja.

    El editor es el de la primera pareja, que es de este dispositivo y se puede editar: si
    «Editar flags…» está apagado (un editor de solo lectura) el flujo no mide nada y lo dice.
    """
    mostrar_avanzado = find_button(dlg, "Mostrar")
    if mostrar_avanzado is None:
        NOTES["error"] = "el editor de «Parejas» no tiene el botón «Mostrar» de «Avanzado»"
        return
    mostrar_avanzado.invoke()
    dlg.update()
    boton = find_button(dlg, "Editar flags…")
    if boton is None:
        NOTES["error"] = "«Avanzado» no tiene el botón «Editar flags…»"
        return
    if boton.instate(["disabled"]):
        NOTES["error"] = "«Editar flags…» está apagado: el editor de la pareja es de solo lectura"
        return
    tema_nuevo(dlg)
    t_req = time.time()
    HOOK["on_shown"] = lambda fdlg, t: en_flags(fdlg, t, t_req)
    boton.invoke()


@anotando
def en_flags(fdlg, t, t_req):
    """El editor de flags recién abierto."""
    record("open-flags", ms(t_req, t), **medir(fdlg))
    shot("flags", fdlg)


def drive_wizard(root):
    """Pulsa «Siguiente» en «¿Dónde?» y apunta lo que tarda en verse el paso «Dispositivo».

    «¿Dónde?» deja seguir con su respuesta de siempre, «En una unidad». El paso lista las
    unidades del equipo con la lectura de verdad (`device.list_volumes()`): en el clic mismo en
    la 0.7.1, y en un hilo cuando el paso las lee después de pintarse; lo medido es hasta el
    primer pintado del paso, no hasta que llega la lista.
    """
    btn = find_button(root, "Siguiente")
    if btn is None:
        NOTES["error"] = "el asistente no tiene el botón «Siguiente»"
        return
    root.update()
    if btn.instate(["disabled"]):
        NOTES["error"] = "«Siguiente» está apagado en «¿Dónde?»"
        return
    tema_nuevo(root)
    t0 = time.perf_counter()
    btn.invoke()
    root.update()
    t1 = time.perf_counter()
    record("paso-dispositivo", ms(t0, t1), **medir(root))
    shot("dispositivo", root)


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
    # La lectura de la principal no se recoge dentro de este `update()`, según caiga
    # el hilo: el primer pintado se cuenta sin ella, siempre, y la recoge
    # `llega_instantanea`. El árbol de la 0.7.1 no tiene sondeo.
    sondeo = getattr(root, "sondeo_instantanea", None)
    if sondeo is not None:
        sondeo.pausar()
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
        if FLOW in ("parejas", "ajustes", "principal", "flota"):
            llega_instantanea(root)
        if FLOW == "parejas":
            drive_parejas(root)
        elif FLOW == "ajustes":
            drive_ajustes(root)
        elif FLOW == "principal":
            drive_principal(root)
        elif FLOW == "flota":
            drive_flota(root)
        elif FLOW == "wizard":
            drive_wizard(root)
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

for _espera in (ESTADO["catalogo"], ESTADO["flota"]):
    if _espera is not None:
        _espera.set()
utiles.escribir("_notes", 0, NOTES)
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)   # sin esperar a hilos de la aplicación que quedaran vivos
