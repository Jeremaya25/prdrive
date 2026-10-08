"""Arranque, escenarios y medidas del candidato Qt (PySide6) del banco de la interfaz.

Es del banco (temporal, ver `banco/LEEME.md`): port a Windows x64, Windows ARM64 y
Linux del prototipo Qt. Un proceso = un escenario. Lo lanza `banco/qt/ronda.py`, que
toma `BENCH_T0` (el `time.time()` justo antes de `Popen`). Imprime UNA línea JSON por
stdout; todo lo demás va a stderr.

  start-main    proceso -> ventana principal pintada
  cold-parejas  proceso -> principal pintada -> «Parejas» (5 parejas + 1 que el dispositivo no usa) pintada
  open-parejas  con la principal ya enseñada (+300 ms de reposo): pedir «Parejas» -> pintada (reloj interno)
  switch-pane   con «Ajustes» enseñado (+300 ms): cambiar de «Configuración» a «Reparación» -> pintado
  capturas      (no mide) una captura de pantalla de cada ventana, con `banco/captura.py`
  volcar        (no mide) vuelca a JSON lo que leen los módulos del dispositivo (`--canned`)
  comprobar     (no mide) importa Qt y dice la versión

«Pintada» = la ventana está expuesta, ha recibido su pintado, la cola de eventos está vacía y el
cliente del servidor gráfico ha sincronizado (`QGuiApplication.sync()`, que solo hace algo en X11).

Env: BENCH_QT (carpeta con PySide6/ y shiboken6/), BENCH_T0, BENCH_CANDIDATE, BENCH_CANNED (JSON),
BENCH_SALIDA=rapida (termina con `os._exit` en vez de salir por el intérprete).
"""
from __future__ import annotations

import gc
import json
import os
import sys
import time

T_PROC = time.time()
P0 = time.perf_counter()
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

QT = os.environ.get("BENCH_QT") or ""
if QT and os.path.isdir(QT):
    sys.path.insert(0, QT)
if sys.platform.startswith("linux"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")          # no sondear wayland si hay X

CANDIDATO = os.environ.get("BENCH_CANDIDATE") or "qt-pyside6"
LIMITE_PINTADO = 15.0
"""Segundos que se espera a que una ventana se pinte antes de dar el escenario por fallido."""

M: dict = {}                                                  # marcas de tiempo (ms desde el inicio del script)
ENTORNO: dict = {}                                            # qué Qt, qué plataforma, qué DPI: va en `detail`
ESTADO: dict = {}                                             # la QApplication, para medir después


def marca(nombre: str) -> float:
    M[nombre] = (time.perf_counter() - P0) * 1000
    return M[nombre]


# ------------------------------------------------------------------------------------------- memoria
def memoria_windows() -> dict:
    """Memoria del proceso con `GetProcessMemoryInfo` (MB): conjunto de trabajo, su pico y la privada."""
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):                              # PROCESS_MEMORY_COUNTERS_EX
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    f = k32.K32GetProcessMemoryInfo
    f.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    f.restype = wintypes.BOOL
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    if not f(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
        return {}
    mb = 1024 * 1024
    return {"rss_mb": round(pmc.WorkingSetSize / mb, 1), "peak_mb": round(pmc.PeakWorkingSetSize / mb, 1),
            "private_mb": round(pmc.PrivateUsage / mb, 1)}


def memoria_linux() -> dict:
    """RSS desde `/proc/self/status`; PSS y memoria propia (anónima) desde `smaps_rollup`; y lo mapeado de ficheros."""
    out: dict = {}
    try:
        with open("/proc/self/status") as f:
            for linea in f:
                if linea.startswith("VmRSS:"):
                    out["rss_mb"] = round(int(linea.split()[1]) / 1024, 1)
    except OSError:
        pass
    try:                                  # PSS reparte las páginas compartidas; Anonymous = memoria propia
        with open("/proc/self/smaps_rollup") as f:
            kv = {x.split(":")[0]: int(x.split()[1]) for x in f if x.split(":")[0] in ("Pss", "Anonymous")}
        out["pss_mb"] = round(kv.get("Pss", 0) / 1024, 1)
        out["anon_mb"] = round(kv.get("Anonymous", 0) / 1024, 1)
    except (OSError, ValueError):
        pass
    out["file_rss_mb"] = mapeado_mb()
    return out


def mapeado_mb() -> dict:
    """RSS (MB) de lo mapeado desde ficheros, por origen (Qt, runtime de Python, resto).

    Es lo que habría que LEER del disco en un arranque en frío: las páginas que el proceso
    ha tocado de cada biblioteca. Una estimación por abajo (la lectura adelantada trae más).
    """
    out = {"qt": 0.0, "python": 0.0, "otros": 0.0}
    try:
        actual = None
        with open("/proc/self/smaps") as f:
            for linea in f:
                partes = linea.split()
                if len(partes) >= 5 and "-" in partes[0] and not linea.startswith(("Rss", "Size")):
                    actual = partes[5] if len(partes) > 5 else ""
                elif linea.startswith("Rss:") and actual and actual.startswith("/"):
                    kb = int(partes[1])
                    clave = "qt" if "/PySide6/" in actual or "/shiboken6/" in actual else (
                        "python" if "/runtime" in actual or "python" in actual.lower() else "otros")
                    out[clave] += kb / 1024
    except OSError:
        pass
    return {k: round(v, 1) for k, v in out.items()}


def memoria() -> dict:
    try:
        return memoria_windows() if sys.platform == "win32" else memoria_linux()
    except Exception as e:                                    # noqa: BLE001
        print("memoria:", e, file=sys.stderr)
        return {}


# ------------------------------------------------------------------------------------------- salida
def emitir(escenario: str, ms: float, detalle: dict) -> None:
    """Imprime la línea JSON del escenario (con la memoria y el entorno); no termina el proceso."""
    detalle.update(memoria())
    try:
        describir_entorno()
    except Exception as e:                                    # noqa: BLE001
        print("entorno:", e, file=sys.stderr)
    detalle["entorno"] = ENTORNO
    try:                                  # la fuente con la que se pinta de verdad (¿cayó a otra?)
        from PySide6.QtGui import QFontInfo
        detalle["fuente_efectiva"] = QFontInfo(ESTADO["app"].font()).family()
    except Exception:                                         # noqa: BLE001
        pass
    print(json.dumps({"candidate": CANDIDATO, "scenario": escenario, "ms": round(ms, 1), "detail": detalle},
                     ensure_ascii=True), flush=True)


def fallo(escenario: str, texto: str) -> int:
    """Imprime la línea JSON de error del escenario."""
    print(json.dumps({"candidate": CANDIDATO, "scenario": escenario, "error": texto[:300]},
                     ensure_ascii=True), flush=True)
    print(f"{escenario}: {texto}", file=sys.stderr)
    return 4


def sin_dialogos_de_error() -> None:
    """En Windows, que un fallo (un `qFatal` al arrancar, una caída al salir) no abra la ventana de WER: colgaría el trabajo."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        # SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX
        ctypes.WinDLL("kernel32").SetErrorMode(0x0001 | 0x0002 | 0x8000)
    except Exception:                                         # noqa: BLE001
        pass


class Enlatado:
    """Los mismos datos que `datos.py`, ya leídos (JSON): aísla el coste del frontend del de los módulos headless."""

    def __init__(self, ruta: str) -> None:
        with open(ruta, encoding="utf-8") as f:
            self.j = json.load(f)
        self.j["estado"]["estado"] = tuple(self.j["estado"]["estado"])

    def estado_principal(self):
        return self.j["estado"]

    def parejas(self):
        return self.j["parejas"]

    def reparacion(self):
        return self.j["reparacion"]


def args() -> dict:
    a = {"scenario": "start-main", "device": os.environ.get("BENCH_DEVICE", ""),
         "tema": os.environ.get("PRDRIVE_TEMA", "claro"), "captura": "", "salida": "",
         "idle": 0.3, "canned": False}
    it = iter(sys.argv[1:])
    for k in it:
        if k == "--scenario":
            a["scenario"] = next(it)
        elif k == "--device":
            a["device"] = next(it)
        elif k == "--tema":
            a["tema"] = next(it)
        elif k == "--captura":
            a["captura"] = next(it)
        elif k == "--salida":
            a["salida"] = next(it)
        elif k == "--canned":
            a["canned"] = True
    return a


# ------------------------------------------------------------------------------------------- pintado
def pintada(app, win, limite: float = LIMITE_PINTADO) -> float:
    """Espera a que `win` esté expuesta y pintada y devuelve el `time.time()` de ese momento.

    Deja en `win.pintada_ok` si llegó a pintarse antes del límite.
    """
    from PySide6.QtCore import QAbstractEventDispatcher, QEventLoop
    from PySide6.QtGui import QGuiApplication
    disp = QAbstractEventDispatcher.instance()
    fin = time.perf_counter() + limite
    ok = False
    while time.perf_counter() < fin:
        app.processEvents()
        wh = win.windowHandle()
        if wh is not None and wh.isExposed() and win.pintados > 0:
            ok = True
            break
    quieto = 0
    while quieto < 2 and time.perf_counter() < fin:        # drenar hasta que no quede nada pendiente
        quieto = 0 if disp.processEvents(QEventLoop.ProcessEventsFlag.AllEvents) else quieto + 1
    QGuiApplication.sync()
    win.pintada_ok = ok
    return time.time()


def reposo(app, segundos: float) -> None:
    fin = time.perf_counter() + segundos
    while time.perf_counter() < fin:
        app.processEvents()
        time.sleep(0.004)


def limpiar(app) -> None:
    """Cierra y borra todas las ventanas y suelta las referencias antes de salir.

    Una ventana que sigue viva al terminar el intérprete (el ciclo
    `self -> botón -> lambda -> self` la retiene) hace caer a PySide en su
    limpieza al salir (QWidget::destroy; en Windows, además, un diálogo de WER).
    """
    try:
        import shiboken6
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QCoreApplication, QEvent
        for w in QApplication.topLevelWidgets():
            try:
                w.close()                     # WA_DeleteOnClose: pide borrarla (deleteLater)
            except RuntimeError:
                pass
        # Sin bucle de eventos en marcha, `processEvents()` no entrega los borrados diferidos.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        app.processEvents()
        for w in QApplication.topLevelWidgets():
            if shiboken6.isValid(w):
                shiboken6.delete(w)
        app.processEvents()
    except Exception as e:                                    # noqa: BLE001
        print("limpiar:", e, file=sys.stderr)
    gc.collect()


# ------------------------------------------------------------------------------------------- entorno
def describir_entorno() -> None:
    """Qué Qt, qué plataforma y qué pantalla: para que un número de Windows se pueda interpretar."""
    app, esquema_os = ESTADO["app"], ESTADO.get("esquema_os", "")
    import PySide6
    from PySide6 import QtCore
    from PySide6.QtCore import QLibraryInfo
    ENTORNO.update({"os": sys.platform, "python": sys.version.split()[0], "qt": QtCore.qVersion(),
                    "pyside": PySide6.__version__, "qpa": app.platformName(), "estilo": "Fusion",
                    "tema": "claro (forzado: setColorScheme(Light) + QPalette + QSS)",
                    "esquema_del_sistema": esquema_os})
    try:
        ENTORNO["plugins"] = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
        ENTORNO["rutas_de_plugins"] = QtCore.QCoreApplication.libraryPaths()
    except Exception:                                         # noqa: BLE001
        pass
    try:
        pant = app.primaryScreen()
        ENTORNO.update({"dpr": pant.devicePixelRatio(), "dpi_logico": round(pant.logicalDotsPerInch(), 1),
                        "pantalla": f"{pant.size().width()}x{pant.size().height()}"})
    except Exception:                                         # noqa: BLE001
        pass


# ------------------------------------------------------------------------------------------- volcado
def volcar(a: dict) -> int:
    """Escribe en `--salida` lo que leen los módulos del dispositivo (para `x-start-main-canned`)."""
    import datos
    datos.cargar_modulos(a["device"])
    j = {"estado": datos.estado_principal(), "parejas": datos.parejas(), "reparacion": datos.reparacion()}
    j["estado"]["raiz"] = "…/dev"
    with open(a["salida"], "w", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False, indent=1)
    print("volcado en", a["salida"], file=sys.stderr)
    return 0


# ------------------------------------------------------------------------------------------- principal
def main() -> int:
    import faulthandler
    faulthandler.enable()                    # una caída (p. ej. al salir) deja la traza de Python en stderr
    a = args()
    if a["scenario"] == "volcar":
        return volcar(a)
    t0 = float(os.environ.get("BENCH_T0") or T_PROC)
    d = {"py_start_ms": round((T_PROC - t0) * 1000, 1)}
    marca("inicio")
    # --- 1. import de Qt
    try:
        from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401
    except Exception as e:                                    # noqa: BLE001
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 2
    d["import_qt_ms"] = round(marca("import_qt") - M["inicio"], 1)
    if a["scenario"] == "comprobar":
        import PySide6
        print(json.dumps({"comprobar": True, "qt": QtCore.qVersion(), "pyside": PySide6.__version__,
                          "ms": d["import_qt_ms"]}), flush=True)
        return 0
    import preflight
    t = time.perf_counter()
    ok, motivo = preflight.comprobar(os.path.dirname(QtCore.__file__))
    d["preflight_ms"] = round((time.perf_counter() - t) * 1000, 2)
    d["preflight_ok"] = ok
    if not ok:
        print("preflight:", motivo, file=sys.stderr)
        if sys.platform != "win32":                           # en Windows se intenta igual
            return fallo(a["scenario"], f"falta una biblioteca del sistema: {motivo}")
    sin_dialogos_de_error()                  # ctypes ya está cargado (preflight): no cuesta nada
    # --- 2. módulos headless del dispositivo y estado (la misma lectura que haría cualquier frontend)
    import datos
    if a["canned"]:                      # ablación: sin los módulos headless (solo el coste del frontend)
        datos = Enlatado(os.environ.get("BENCH_CANNED") or "canned.json")
        st = datos.estado_principal()
        d["data_import_ms"] = d["data_read_ms"] = 0.0
    else:
        datos.cargar_modulos(a["device"])
        st = datos.estado_principal()
        d["data_import_ms"] = round(datos.T["imports_ms"], 1)
        d["data_read_ms"] = round(datos.T["estado_ms"], 1)
    marca("datos")
    # --- 3. QApplication, fuentes, estilo
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication
    import estilo
    plugins = preflight.carpeta_plugins(os.path.dirname(QtCore.__file__))
    if os.path.isdir(plugins):               # que Qt los encuentre aunque su ruta por defecto no cuadre con el wheel
        QCoreApplication.addLibraryPath(plugins)
    t = time.perf_counter()
    app = QApplication(["prdrive"])
    ESTADO["app"] = app
    d["qapp_ms"] = round((time.perf_counter() - t) * 1000, 1)
    t = time.perf_counter()
    fdir = os.path.join(a["device"], ".prdrive", "ui", "fuentes")
    cargadas = 0
    for f in sorted(os.listdir(fdir)):
        if f.endswith(".ttf"):
            cargadas += QFontDatabase.addApplicationFont(os.path.join(fdir, f)) >= 0
    base = QFont("Noto Sans")
    base.setPointSizeF(10)
    app.setFont(base)
    d["fonts_ms"] = round((time.perf_counter() - t) * 1000, 1)
    d["fuentes_cargadas"] = cargadas
    parts = {}
    t = time.perf_counter()
    app.setStyle("Fusion")
    parts["fusion"] = time.perf_counter() - t
    estilo.usar(a["tema"])
    t = time.perf_counter()
    try:
        esquema_os = app.styleHints().colorScheme().name      # lo que diría el sistema, antes de forzar
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark if a["tema"] == "oscuro" else Qt.ColorScheme.Light)
    except Exception as e:                                       # noqa: BLE001
        esquema_os = f"?: {e}"
        print("setColorScheme:", e, file=sys.stderr)
    parts["scheme"] = time.perf_counter() - t
    t = time.perf_counter()
    app.setPalette(estilo.paleta())
    parts["palette"] = time.perf_counter() - t
    t = time.perf_counter()
    hoja = estilo.hoja()
    parts["qss_gen"] = time.perf_counter() - t
    t = time.perf_counter()
    app.setStyleSheet(hoja)
    parts["qss_apply"] = time.perf_counter() - t
    d["style_ms"] = round(sum(parts.values()) * 1000, 1)
    d["style_parts_ms"] = {k: round(v * 1000, 2) for k, v in parts.items()}
    marca("qapp")
    ESTADO["esquema_os"] = esquema_os
    import pantallas
    try:
        if a["scenario"] == "capturas":
            return capturas(app, a, st, datos, pantallas)
        return escenario(app, a, t0, d, st, datos, pantallas)
    except Exception as e:                                       # noqa: BLE001
        import traceback
        traceback.print_exc()
        return fallo(a["scenario"], f"{type(e).__name__}: {e}")
    finally:
        limpiar(app)
        sys.stdout.flush()
        sys.stderr.flush()


def escenario(app, a: dict, t0: float, d: dict, st: dict, datos, pantallas) -> int:
    esc = a["scenario"]
    nombre = f"x-{esc}-canned" if a["canned"] else esc
    # --- 4. construir la ventana principal
    t = time.perf_counter()
    win = pantallas.VentanaPrincipal(st)
    win.adjustSize()
    win.centrar()
    d["build_main_ms"] = round((time.perf_counter() - t) * 1000, 1)
    # --- 5. enseñar y pintar
    t = time.perf_counter()
    win.show()
    tw = pintada(app, win)
    d["show_main_ms"] = round((time.perf_counter() - t) * 1000, 1)
    d["widgets"] = len(app.allWidgets())
    ms_main = (tw - t0) * 1000
    if not win.pintada_ok:
        return fallo(nombre, f"la ventana principal no se pintó en {LIMITE_PINTADO:.0f} s")
    if esc == "start-main":
        d["pintados"] = win.pintados
        emitir(nombre, ms_main, d)
    elif esc == "cold-parejas":
        tp = time.time()
        dp = datos.parejas()
        pw = pantallas.VentanaParejas(dp, st, win)
        pw.ajustar_a_pantalla()
        pw.centrar()
        d["build_parejas_ms"] = round((time.time() - tp) * 1000, 1)
        pw.show()
        tw2 = pintada(app, pw)
        if not pw.pintada_ok:
            return fallo(nombre, f"«Parejas» no se pintó en {LIMITE_PINTADO:.0f} s")
        d["main_painted_ms"] = round(ms_main, 1)
        d["parejas_phase_ms"] = round((tw2 - tp) * 1000, 1)
        d["widgets"] = len(app.allWidgets())
        emitir(nombre, (tw2 - t0) * 1000, d)
    elif esc == "open-parejas":
        reposo(app, a["idle"])
        t = time.perf_counter()
        dp = datos.parejas()
        t_data = time.perf_counter()
        pw = pantallas.VentanaParejas(dp, st, win)
        pw.ajustar_a_pantalla()
        pw.centrar()
        t_build = time.perf_counter()
        pw.show()
        pintada(app, pw)
        t_end = time.perf_counter()
        if not pw.pintada_ok:
            return fallo(nombre, f"«Parejas» no se pintó en {LIMITE_PINTADO:.0f} s")
        det = {"data_ms": round((t_data - t) * 1000, 1), "build_ms": round((t_build - t_data) * 1000, 1),
               "show_ms": round((t_end - t_build) * 1000, 1), "widgets": len(app.allWidgets()),
               "rows": len(dp["filas"])}
        # segunda apertura (ya con estilos/fuentes/glifos calientes) para ver el coste «caliente»
        pw.close()
        reposo(app, 0.1)
        t = time.perf_counter()
        dp = datos.parejas()
        pw2 = pantallas.VentanaParejas(dp, st, win)
        pw2.ajustar_a_pantalla()
        pw2.centrar()
        pw2.show()
        pintada(app, pw2)
        det["reopen_ms"] = round((time.perf_counter() - t) * 1000, 1)
        emitir(nombre, det["data_ms"] + det["build_ms"] + det["show_ms"], det)
    elif esc == "switch-pane":
        t_a = time.perf_counter()
        aj = pantallas.VentanaAjustes(st, datos, win)
        aj.mostrar("config")
        aj.centrar()
        aj.show()
        pintada(app, aj)
        first_ms = (time.perf_counter() - t_a) * 1000
        if not aj.pintada_ok:
            return fallo(nombre, f"«Ajustes» no se pintó en {LIMITE_PINTADO:.0f} s")
        reposo(app, a["idle"])
        t = time.perf_counter()
        aj.mostrar("reparacion")
        pintada(app, aj)
        # `pintados` solo cuenta el nivel superior: un cambio de panel repinta un trozo, no la ventana; por eso
        # `pintada` aquí cuenta como «cola vacía + sync». El primer pintado ya lo había superado.
        ms = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        aj.mostrar("config")
        pintada(app, aj)
        det = {"open_ajustes_ms": round(first_ms, 1), "revisit_ms": round((time.perf_counter() - t) * 1000, 1),
               "widgets": len(app.allWidgets())}
        t = time.perf_counter()
        aj.mostrar("actualizaciones")
        pintada(app, aj)
        det["third_pane_ms"] = round((time.perf_counter() - t) * 1000, 1)
        emitir(nombre, ms, det)
    else:
        return fallo(esc, "escenario desconocido")
    return 0


def capturas(app, a: dict, st: dict, datos, pantallas) -> int:
    """Guarda con `banco/captura.py` lo que se ve en pantalla de cada ventana, una línea JSON por captura."""
    destino = a["captura"]
    os.makedirs(destino, exist_ok=True)
    captura, motivo = None, ""
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))       # banco/
        sys.dont_write_bytecode = True       # no dejar un .pyc en la carpeta de otro
        import captura
    except Exception as e:                                       # noqa: BLE001
        motivo = f"no se pudo importar banco/captura.py: {type(e).__name__}: {e}"

    def foto(win, pantalla: str) -> None:
        win.show()
        win.raise_()
        win.activateWindow()
        pintada(app, win)
        reposo(app, 0.4)                     # que el escritorio componga lo pintado antes de copiarlo
        fichero = f"{CANDIDATO}-{pantalla}.png"
        if captura is None:
            info = {"ok": False, "ancho": 0, "alto": 0, "colores": 0, "motivo": motivo}
        else:
            info = captura.capturar(int(win.winId()), os.path.join(destino, fichero))
        info["pintada"] = bool(win.pintada_ok)
        print(json.dumps({"captura": fichero, "candidate": CANDIDATO, "screen": pantalla, "info": info},
                         ensure_ascii=True), flush=True)
        win.close()                          # se borra al cerrarla; la siguiente no queda tapada
        reposo(app, 0.1)

    principal = pantallas.VentanaPrincipal(st)
    principal.adjustSize()
    principal.centrar()
    foto(principal, "main")
    pw = pantallas.VentanaParejas(datos.parejas(), st)
    pw.ajustar_a_pantalla()
    pw.centrar()
    foto(pw, "parejas")
    aj = pantallas.VentanaAjustes(st, datos)
    aj.mostrar("config")
    aj.centrar()
    foto(aj, "ajustes")
    return 0
