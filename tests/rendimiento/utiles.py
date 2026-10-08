"""Lo común de la comprobación de tiempos (`tests/rendimiento/`).

Solo biblioteca estándar y nada de Tk arriba: lo importan el orquestador
(`correr.py`) y los procesos hijos (`driver.py`, `suelo.py`). No importa nada
que la aplicación no importe por su cuenta (el recuento de módulos del primer
pintado cuenta los de todo el proceso). Aquí está lo que cambia de un sistema a
otro: la memoria del proceso, cómo se identifica una ventana para capturarla,
cómo se enseña (el velo de DWM de la aplicación real), cómo se matan árboles de
procesos y cómo se vuelcan los resultados al fichero que lee el orquestador.
"""

from __future__ import annotations

import os
import sys

ES_WIN = sys.platform == "win32"
ES_LINUX = sys.platform.startswith("linux")


# ------------------------------------------------------------------ resultados
def escribir(escenario: str, ms: float, detalle: dict) -> None:
    """Añade una línea `{"scenario", "ms", "detail"}` al fichero de `BENCH_OUT`.

    Se escribe en cuanto se mide: si el proceso se cuelga después, lo medido
    antes llega igual a la ronda.
    """
    ruta = os.environ.get("BENCH_OUT")
    if not ruta:
        return
    import json
    with open(ruta, "a", encoding="utf-8") as f:
        f.write(json.dumps({"scenario": escenario, "ms": ms, "detail": detalle}) + "\n")


# --------------------------------------------------------------------- memoria
_PMC = None
_K32 = None
_PSAPI = None


def _rss_windows() -> float | None:
    """Devuelve el conjunto de trabajo del proceso, en MB (`GetProcessMemoryInfo`)."""
    global _PMC, _K32, _PSAPI
    import ctypes
    from ctypes import wintypes
    if _PMC is None:
        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]
        _PMC = PMC
        _K32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _K32.GetCurrentProcess.restype = wintypes.HANDLE
        _K32.GetCurrentProcess.argtypes = []
        _PSAPI = ctypes.WinDLL("psapi", use_last_error=True)
        _PSAPI.GetProcessMemoryInfo.restype = wintypes.BOOL
        _PSAPI.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC),
                                                wintypes.DWORD]
    datos = _PMC()
    datos.cb = ctypes.sizeof(datos)
    if not _PSAPI.GetProcessMemoryInfo(_K32.GetCurrentProcess(), ctypes.byref(datos),
                                       datos.cb):
        return None
    return round(datos.WorkingSetSize / (1024 * 1024), 1)


def rss_mb() -> float | None:
    """Devuelve la memoria residente del proceso en MB, o `None` si no se sabe."""
    try:
        if ES_WIN:
            return _rss_windows()
        for linea in open("/proc/self/status"):
            if linea.startswith("VmRSS:"):
                return round(int(linea.split()[1]) / 1024, 1)
    except Exception:                                    # noqa: BLE001
        pass
    return None


# ------------------------------------------------------------------ arranque Tk
def tk_con_xft() -> bool:
    """Carga el Tk con Xft del runtime antes que el de serie (solo Linux).

    Es lo que hace `ui.tk_con_xft()`; aquí para quien no importa `ui`. Tiene que
    correr antes del primer `import tkinter`. En Windows no hace nada.
    """
    if not ES_LINUX or "_tkinter" in sys.modules:
        return False
    from pathlib import Path
    ruta = Path(sys.prefix) / "lib" / "tk-xft" / "libtcl9tk9.0.so"
    if not ruta.is_file():
        return False
    try:
        import ctypes
        ctypes.CDLL(str(ruta), mode=ctypes.RTLD_GLOBAL)
    except OSError:
        return False
    return True


_densidad_declarada = False


def nitidez() -> None:
    """Declara ante Windows que el proceso dibuja a la densidad real.

    Copia de `ui.theme.nitidez()` (sin la carga de letra): conciencia de
    sistema, de la más nueva a la más vieja, todas mudas si fallan. Debe correr
    antes del primer `Tk()`. Fuera de Windows no hace nada.
    """
    global _densidad_declarada
    if _densidad_declarada or not ES_WIN:
        return
    _densidad_declarada = True
    import ctypes
    try:                                        # Windows 10 1703 en adelante
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-2)):
            return
    except Exception:                           # noqa: BLE001
        pass
    try:                                        # Windows 8.1
        if ctypes.windll.shcore.SetProcessDpiAwareness(1) == 0:
            return
    except Exception:                           # noqa: BLE001
        pass
    try:                                        # Windows Vista
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:                           # noqa: BLE001
        pass


# ---------------------------------------------------------------- enseñar ventana
DWMWA_CLOAK = 13


def _atributo_dwm(hwnd: int, atributo: int, valor: int) -> bool:
    """Le pone a una ventana un atributo de DWM de 4 bytes (copia de `ui.tk`)."""
    import ctypes
    from ctypes import wintypes
    poner = ctypes.WinDLL("dwmapi", use_last_error=True).DwmSetWindowAttribute
    poner.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.POINTER(ctypes.c_int),
                      wintypes.DWORD]
    poner.restype = ctypes.c_long                   # HRESULT
    dato = ctypes.c_int(valor)
    return poner(hwnd, atributo, ctypes.byref(dato), ctypes.sizeof(dato)) == 0


def ensenar(ventana) -> None:
    """Enseña una ventana retirada ya pintada entera (copia de `ui.tk.ensenar`).

    En Windows se enseña encubierta por DWM, se procesa todo lo pendiente
    (`update()`) y solo entonces se descubre; es lo que hace la aplicación
    real, sin la barra de título del tema. Fuera de Windows es un
    `deiconify()`.
    """
    hwnd = None
    if ES_WIN:
        try:
            ventana.update_idletasks()
            marco = int(ventana.wm_frame(), 16)
            if marco != int(ventana.winfo_id()) and _atributo_dwm(marco, DWMWA_CLOAK, 1):
                hwnd = marco
        except Exception:                               # noqa: BLE001
            hwnd = None
    ventana.deiconify()
    if hwnd is None:
        return
    try:
        ventana.update()
    except Exception:                                   # noqa: BLE001
        pass
    finally:
        try:
            _atributo_dwm(hwnd, DWMWA_CLOAK, 0)
        except Exception:                               # noqa: BLE001
            pass


# --------------------------------------------------------------------- capturas
def id_ventana(ventana) -> int:
    """El identificador que pide `captura.capturar`: HWND del marco en Windows, id X en Linux."""
    if ES_WIN:
        try:
            marco = int(ventana.wm_frame(), 16)
            if marco:
                return marco
        except Exception:                               # noqa: BLE001
            pass
    return int(ventana.winfo_id())


def capturar_ventana(ventana, ruta) -> dict:
    """Guarda en `ruta` lo que se ve de una ventana de Tk; nunca lanza.

    La sube al frente y deja que el sistema la componga antes de capturarla.
    """
    import time
    try:
        try:
            ventana.attributes("-topmost", True)
        except Exception:                               # noqa: BLE001
            pass
        ventana.lift()
        ventana.update_idletasks()
        ventana.update()
        time.sleep(0.25)
        ventana.update()
        import captura                            # al lado de este fichero
        return captura.capturar(id_ventana(ventana), ruta)
    except Exception as e:                              # noqa: BLE001
        return {"ok": False, "ancho": 0, "alto": 0, "colores": 0,
                "motivo": f"{type(e).__name__}: {e}"[:200]}
    finally:
        try:
            ventana.attributes("-topmost", False)
        except Exception:                               # noqa: BLE001
            pass


# --------------------------------------------------------------- matar procesos
def matar_arbol(proc) -> None:
    """Mata el proceso y todos sus descendientes.

    Windows: `taskkill /T /F /PID`. POSIX: el grupo entero (el hijo se lanzó con
    `start_new_session=True`, así que su pid es el del grupo).
    """
    import subprocess
    if ES_WIN:
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=30)
        except Exception:                               # noqa: BLE001
            pass
        try:
            proc.kill()
        except Exception:                               # noqa: BLE001
            pass
        return
    import signal
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
