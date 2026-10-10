#!/usr/bin/env python3
"""Un fichero de estado que otro proceso tiene ocupado un instante, en Windows.

`store.write_text()` sustituye el fichero con `os.replace()`, y en Windows eso
falla mientras otro lo tenga abierto; mientras se sustituye, abrirlo también
falla. Las dos cosas duran milisegundos y `store.insistir()` las espera. Sin
esperar, la escritura se perdía y la lectura contestaba «aquí no hay nada»:

- la selección de parejas de la ventana no quedaba guardada si el agente estaba
  leyendo `ui_prefs.json` en ese instante;
- el agente leía un `ui_prefs.json` a medio sustituir como «sin recuerdo», se
  quedaba con todas las parejas del TOML y, como apunta la fecha del fichero
  que ha leído, no lo volvía a leer.

La regla de `insistir()` se comprueba en cualquier sistema forzando
`store.IS_WIN`; lo que hace Windows con un fichero ocupado, solo allí y con un
fichero ocupado de verdad.
"""

import os
import sys
import threading
import types

from _harness import Checks, tmpdir

import _agente_falso as F
import agente
from common import equipo, store
from ui import prefs

c = Checks("ficheros de estado ocupados (store.insistir)")
SOLO_WINDOWS = ("(saltado) solo en Windows: en POSIX un fichero abierto por otro se deja "
                "sustituir y abrir")


def ocupar(ruta):
    """Abre `ruta` sin compartirla y devuelve cómo soltarla.

    Es como la tiene quien la está sustituyendo: abrirla da una violación de
    uso compartido, que Python enseña como `PermissionError`.
    """
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    GENERIC_READ, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL = 0x80000000, 3, 0x80
    handle = k32.CreateFileW(str(ruta), GENERIC_READ, 0, None, OPEN_EXISTING,
                             FILE_ATTRIBUTE_NORMAL, None)
    if not handle or handle == wintypes.HANDLE(-1).value:
        raise OSError(ctypes.get_last_error(), f"no he podido ocupar {ruta}")
    return lambda: k32.CloseHandle(handle)


def soltar_en(segundos: float, soltar) -> threading.Timer:
    """Llama a `soltar()` pasados `segundos`, desde otro hilo."""
    reloj = threading.Timer(segundos, soltar)
    reloj.start()
    return reloj


INSTANTE = 0.1
"""Segundos que las pruebas tienen ocupado un fichero: mucho menos que `store.ESPERA_OCUPADO`."""

carpeta = tmpdir("prdrive-ocupado-")
dato = carpeta / "dato.json"
store.write_json(dato, {"n": 1})

# --- La regla, en cualquier sistema -----------------------------------------
llamadas = []


def tarda():
    """Falla dos veces por ocupado y a la tercera contesta."""
    llamadas.append(1)
    if len(llamadas) < 3:
        raise PermissionError(13, "ocupado")
    return "ya"


def nunca():
    """Falla siempre por ocupado."""
    llamadas.append(1)
    raise PermissionError(13, "ocupado")


def no_esta():
    """Falla porque el fichero no está."""
    llamadas.append(1)
    raise FileNotFoundError(2, "no está")


def veces(hacer, ruta) -> tuple[str, int]:
    """Devuelve con qué acaba `insistir()` y cuántas veces llamó a `hacer`."""
    llamadas.clear()
    try:
        return str(store.insistir(hacer, ruta)), len(llamadas)
    except OSError as e:
        return type(e).__name__, len(llamadas)


de_verdad = store.IS_WIN, store.ESPERA_OCUPADO
try:
    store.IS_WIN = True
    c("insiste mientras el fichero esté ocupado y devuelve lo que al fin conteste",
      veces(tarda, dato), ("ya", 3))
    store.ESPERA_OCUPADO = 0.05
    final, n = veces(nunca, dato)
    c("pasado el plazo lanza el `PermissionError`, tras varios intentos",
      (final, n > 1), ("PermissionError", True))
    store.ESPERA_OCUPADO = de_verdad[1]
    c("una carpeta donde iba el fichero no es un fichero ocupado: a la primera",
      veces(nunca, carpeta), ("PermissionError", 1))
    c("ni lo que ya no está (el dispositivo extraído): a la primera",
      veces(nunca, carpeta / "no-esta" / "dato.json"), ("PermissionError", 1))
    c("otro error tampoco se espera", veces(no_esta, dato), ("FileNotFoundError", 1))
    store.IS_WIN = False
    c("fuera de Windows un `PermissionError` es de permisos: a la primera",
      veces(nunca, dato), ("PermissionError", 1))
finally:
    store.IS_WIN, store.ESPERA_OCUPADO = de_verdad

# --- Lo que hace Windows, con un fichero ocupado de verdad ------------------
if os.name != "nt":
    print(f"  {SOLO_WINDOWS}")
    sys.exit(c.report())

lector = dato.open("r", encoding="utf-8")
reloj = soltar_en(INSTANTE, lector.close)
c("se escribe aunque un lector tenga abierto el destino un instante",
  store.write_json(dato, {"n": 2}), True)
reloj.join()
c("  y queda lo nuevo", store.read_json(dato), {"n": 2})

reloj = soltar_en(INSTANTE, ocupar(dato))
c("se lee aunque el fichero no se deje abrir un instante", store.read_json(dato), {"n": 2})
reloj.join()

try:
    store.ESPERA_OCUPADO = 0.05
    with dato.open("r", encoding="utf-8"):
        c("si no lo sueltan a tiempo, la escritura dice que no ha podido",
          store.write_json(dato, {"n": 3}), False)
    c("  y el fichero sigue con lo que tenía", store.read_json(dato), {"n": 2})
    soltar = ocupar(dato)
    try:
        c("y una lectura que no lo consigue contesta que no hay nada, sin lanzar",
          store.read_json(dato), {})
    finally:
        soltar()
finally:
    store.ESPERA_OCUPADO = de_verdad[1]

# --- La selección de la ventana, con el agente leyéndola --------------------
prefs.PREFS = carpeta / "ui_prefs.json"
CFG = types.SimpleNamespace(names=["docs", "fotos", "espejo"])
prefs.guardar_parejas(CFG, ["docs", "fotos"])
lector = prefs.PREFS.open("r", encoding="utf-8")
reloj = soltar_en(INSTANTE, lector.close)
pendiente = prefs.SeleccionPendiente()
pendiente.poner(CFG, ["docs"])
c("la selección se guarda aunque alguien esté leyendo `ui_prefs.json`",
  pendiente.volcar(), True)
reloj.join()
c("  y es la que queda escrita", prefs.read_prefs().get("pairs"), ["docs"])

# --- El agente, con `ui_prefs.json` a medio sustituir -----------------------
F.preparar()
UID = "c" * 32
RAIZ = F.unidad(UID, parejas=("docs", "fotos", "espejo"))
equipo.guardar_ajustes(equipo.Ajustes().con_unidad(equipo.Unidad(UID, equipo.DAEMON)))
F.RAICES[:] = [RAIZ]
ag = F.nuevo()
F.vueltas(ag, 2)
con = ag.conexiones[UID]


def atendidas() -> list[str]:
    """Las parejas que el agente tiene por las del servicio de la raíz."""
    return [p.nombre for p in con.servicio.parejas] if con.servicio else []


c("(sin recuerdo, el agente atiende todas las parejas del TOML)",
  atendidas(), ["docs", "fotos", "espejo"])
recuerdo = agente.estado_de(RAIZ) / "ui_prefs.json"
store.write_json(recuerdo, {"action": "daemon", "pairs": ["docs"],
                            "known": ["docs", "fotos", "espejo"]})
reloj = soltar_en(INSTANTE, ocupar(recuerdo))
F.vueltas(ag, 1)
reloj.join()
c("el agente lee la selección aunque el fichero no se deje abrir en esa vuelta",
  atendidas(), ["docs"])
F.vueltas(ag, 3)
c("  y no se queda con las parejas que la ventana desmarcó", atendidas(), ["docs"])

sys.exit(c.report())
