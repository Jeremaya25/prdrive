#!/usr/bin/env python3
"""
La bandeja de Windows (`ui/bandeja_windows.py`), con un Windows de mentira.

`Bandeja` habla con Windows solo a través de su `Api`; aquí se le pone una que
apunta lo que se le pide y tiene un bucle de mensajes de verdad en el hilo de
la bandeja (una cola). Así se comprueba, sin Windows:

  * el icono se pone al arrancar, con el del estado y la línea del ratón, y se
    cambia con `poner()` desde otro hilo;
  * sin barra de tareas todavía (al iniciar sesión) la ventana vive igual, y el
    icono se pone al llegar `TaskbarCreated`, que también lo repone si el
    Explorador se reinicia;
  * el menú: lo elegido son peticiones al agente; lo apagado no pide nada;
  * `WM_DEVICECHANGE` despierta el recorrido; la vuelta de la suspensión pide
    `despertar`;
  * los avisos cuelgan del icono (`NIF_INFO`) y `avisos` los manda por ahí;
  * al cerrar se quita el icono, se sueltan los iconos y acaba el hilo.

Lo que llama de verdad a user32 y shell32 (`Api`) solo se puede probar en
Windows: está en la lista de pruebas en real.
"""

import queue
import sys
import threading
import time

from _harness import Checks, tmpdir

from common import avisos, equipo
from ui import bandeja, bandeja_windows as bw, icons

c = Checks("la bandeja de Windows, con un Windows de mentira")

TASKBAR = 0xC123


class ApiFalsa:
    def __init__(self, barra: bool = True):
        self.barra = barra                  # ¿existe ya la barra de tareas?
        self.cola: queue.Queue = queue.Queue()
        self.llamadas: list = []
        self.manejar = None
        self.elegir = 0                     # el id que «elige» el menú
        self.menus: list = []
        self.soltados: list = []
        self.fin = threading.Event()

    def mensaje_registrado(self, nombre):
        return TASKBAR if nombre == "TaskbarCreated" else 0

    def ventana(self, manejar):
        self.manejar = manejar
        return 777

    def bucle(self):
        while True:
            msg, w, l = self.cola.get()
            if msg is None:
                break
            self.manejar(777, msg, w, l)
        self.fin.set()

    def salir(self):
        self.cola.put((None, 0, 0))

    def destruir(self, hwnd):
        self.manejar(hwnd, bw.WM_DESTROY, 0, 0)

    def post(self, hwnd, msg):
        self.cola.put((msg, 0, 0))
        return True

    def enviar(self, msg, w=0, l=0):
        """Lo que manda Windows (una difusión, un clic en el icono)."""
        self.cola.put((msg, w, l))

    def icono(self, ruta):
        return f"H:{ruta.name}"

    def soltar_icono(self, h):
        self.soltados.append(h)

    def notificar(self, accion, **campos):
        self.llamadas.append((accion, campos))
        return accion != bw.NIM_ADD or self.barra

    def menu(self, hwnd, entradas, ids):
        self.menus.append((entradas, ids))
        return self.elegir


def esperar(condicion, segundos=3.0) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.01)
    return condicion()


CARPETA = tmpdir("prdrive-agente-")
icons.write_bandeja(CARPETA)
PEDIDAS: list = []
MONTAJES: list = []
api = ApiFalsa()
b = bw.Bandeja(CARPETA, PEDIDAS.append, lambda: MONTAJES.append(1), api=api)
c("arranca con su ventana", b.arrancar(), True)
c("  y pone el icono", b.puesta, True)
accion, campos = api.llamadas[0]
c("  con NIM_ADD, el icono de «bien» y el mensaje de vuelta",
  (accion, campos["icono"], campos["callback"], campos["flags"]),
  (bw.NIM_ADD, "H:bandeja-bien.ico", bw.WM_ICONO, bw.NIF_MESSAGE | bw.NIF_ICON | bw.NIF_TIP))
c("  y los avisos pasan a colgarse de él", avisos.GLOBO == b.globo, True)

vista = bandeja.vista({"pausado": True, "unidades": [
    {"id": "u1", "nombre": "PRDRIVE-1", "atendida": True, "en_lista": True}]})
b.poner(vista)
c("poner() desde otro hilo cambia icono y línea (NIM_MODIFY)",
  esperar(lambda: api.llamadas[-1][0] == bw.NIM_MODIFY
          and api.llamadas[-1][1]["icono"] == "H:bandeja-pausa.ico"), True)
c("  con la línea de la vista", api.llamadas[-1][1]["tip"], "prdrive — en pausa")

# --- el menú ---------------------------------------------------------------------
ids = bw.numerar(vista.menu)
api.elegir = next(n for n, e in ids.items() if e.texto == "Reanudar")
api.enviar(bw.WM_ICONO, 0, bw.WM_RBUTTONUP)
c("clic derecho: menú, y lo elegido va al agente",
  esperar(lambda: PEDIDAS == [{"pide": equipo.PIDE_SIGUE}]), True)
api.elegir = next(n for n, e in ids.items() if e.texto == "Abrir PRDRIVE-1")
api.enviar(bw.WM_ICONO, 0, bw.WM_LBUTTONUP)
c("  el izquierdo también abre el menú",
  esperar(lambda: PEDIDAS[-1] == {"pide": equipo.PIDE_ABRIR, "id": "u1"}), True)
api.elegir = next(n for n, e in ids.items() if not e.activa)
antes = len(PEDIDAS)
api.enviar(bw.WM_ICONO, 0, bw.WM_RBUTTONUP)
esperar(lambda: len(api.menus) == 3)
time.sleep(0.05)
c("  una entrada apagada no pide nada", len(PEDIDAS), antes)
api.elegir = 0
api.enviar(bw.WM_ICONO, 0, bw.WM_RBUTTONUP)
esperar(lambda: len(api.menus) == 4)
time.sleep(0.05)
c("  cerrar el menú sin elegir, tampoco", len(PEDIDAS), antes)
c("  mover el ratón por encima no abre nada",
  (api.enviar(bw.WM_ICONO, 0, 0x0200), time.sleep(0.05), len(api.menus))[2], 4)

c("numerar: ni separadores ni submenús llevan id; los hijos, sí",
  [e.texto for e in bw.numerar((bandeja.Entrada("a"), bandeja.SEPARADOR,
                                bandeja.Entrada("s", hijos=(bandeja.Entrada("h"),))),
                               ).values()], ["a", "h"])
c("un & de un nombre sale tal cual en el menú", bw.texto_menu("Tom & Jerry"),
  "Tom && Jerry")

# --- lo que difunde Windows --------------------------------------------------------
api.enviar(bw.WM_DEVICECHANGE, bw.DBT_DEVICEARRIVAL, 0)
c("WM_DEVICECHANGE (llega un volumen) despierta el recorrido",
  esperar(lambda: MONTAJES == [1]), True)
api.enviar(bw.WM_DEVICECHANGE, 0x0018, 0)      # DBT_CONFIGCHANGED: nada que ver
time.sleep(0.05)
c("  otros WM_DEVICECHANGE no", MONTAJES, [1])
api.enviar(bw.WM_POWERBROADCAST, bw.PBT_APMRESUMEAUTOMATIC, 0)
c("la vuelta de la suspensión pide «despertar»",
  esperar(lambda: PEDIDAS[-1] == {"pide": equipo.PIDE_DESPERTAR}), True)
antes = len([a for a, _ in api.llamadas if a == bw.NIM_ADD])
api.enviar(TASKBAR)
c("TaskbarCreated (el Explorador reiniciado) vuelve a poner el icono",
  esperar(lambda: len([a for a, _ in api.llamadas if a == bw.NIM_ADD]) == antes + 1), True)
c("  con la última vista", api.llamadas[-1][1]["tip"], "prdrive — en pausa")

# --- los avisos --------------------------------------------------------------------
c("un aviso se cuelga del icono", b.globo("PRDRIVE-1: falla docs", "Mira la ventana", True),
  True)
accion, campos = api.llamadas[-1]
c("  con NIF_INFO, título y texto, y de aviso si es urgente",
  (accion, campos["flags"], campos["info_titulo"], campos["info"], campos["info_flags"]),
  (bw.NIM_MODIFY, bw.NIF_INFO, "PRDRIVE-1: falla docs", "Mira la ventana", bw.NIIF_WARNING))
c("avisos.enviar en Windows usa la bandeja, sin icono de paso",
  (avisos._windows("t", "x", False), api.llamadas[-1][1]["info_titulo"]), (True, "t"))

# --- cerrar --------------------------------------------------------------------------
b.cerrar()
c("al cerrar se quita el icono", esperar(lambda: api.llamadas[-1][0] == bw.NIM_DELETE), True)
c("  se sueltan los iconos cargados", sorted(api.soltados),
  ["H:bandeja-bien.ico", "H:bandeja-pausa.ico"])
c("  acaba su hilo", api.fin.is_set(), True)
c("  y los avisos vuelven a su icono de paso", avisos.GLOBO, None)
c("  un aviso ya no se cuelga", b.globo("t", "x"), False)

# --- sin barra de tareas al arrancar ---------------------------------------------------
api = ApiFalsa(barra=False)
b = bw.Bandeja(CARPETA, PEDIDAS.append, lambda: None, api=api)
c("sin barra de tareas todavía, la ventana vive igual", (b.arrancar(), b.puesta),
  (True, False))
c("  y un aviso no se cuelga (va al icono de paso)", b.globo("t", "x"), False)
api.barra = True
api.enviar(TASKBAR)
c("  al llegar TaskbarCreated se pone el icono", esperar(lambda: b.puesta), True)
b.cerrar()

# --- sin ventana ---------------------------------------------------------------------
class SinVentana(ApiFalsa):
    def ventana(self, manejar):
        return None


b = bw.Bandeja(CARPETA, PEDIDAS.append, lambda: None, api=SinVentana())
c("sin ventana no hay bandeja, y el agente sigue sin ella", b.arrancar(), False)
c("  ni se tocan los avisos", avisos.GLOBO, None)

# --- un icono que falta ----------------------------------------------------------------
(CARPETA / "bandeja-aviso.ico").unlink()
api = ApiFalsa()
b = bw.Bandeja(CARPETA, PEDIDAS.append, lambda: None, api=api)
b.arrancar()
b.poner(bandeja.vista({"unidades": [{"id": "u", "nombre": "U", "fallando": ["x"]}]}))
c("sin el .ico de un estado se usa el de «bien»",
  esperar(lambda: api.llamadas[-1][1].get("icono") == "H:bandeja-bien.ico"
          and "falla" in api.llamadas[-1][1].get("tip", "")), True)
b.cerrar()

sys.exit(c.report())
