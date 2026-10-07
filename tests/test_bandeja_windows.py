#!/usr/bin/env python3
"""La bandeja de Windows (`ui/bandeja_windows.py`), con un Windows de mentira.

`Bandeja` habla con Windows solo a través de su `Api`; aquí se le pone una que
apunta lo que se le pide y tiene un bucle de mensajes de verdad en el hilo de
la bandeja (una cola). Así se comprueba, sin Windows:
- El icono se pone al arrancar, con el del estado y la línea del ratón, y se
  cambia con `poner()` desde otro hilo.
- Sin barra de tareas todavía (al iniciar sesión) la ventana vive igual, y el
  icono se pone al llegar `TaskbarCreated`, que también lo repone si el
  Explorador se reinicia.
- El menú: lo elegido son peticiones al agente; lo apagado no pide nada.
- `WM_DEVICECHANGE` despierta el recorrido; la vuelta de la suspensión pide
  `despertar`. Los avisos de extracción de un handle (el de la carpeta de una
  pareja vigilada) van a `dispositivo()` antes de que la ventana conteste.
- Los avisos cuelgan del icono (`NIF_INFO`) y `avisos` los manda por ahí.
- Al cerrar se quita el icono, se sueltan los iconos y acaba el hilo.

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
    """La `Api` de mentira: apunta lo que se le pide y tiene un bucle de mensajes.

    Attributes:
        barra: Si existe ya la barra de tareas.
        cola: Los mensajes que el bucle va a repartir.
        llamadas: Las notificaciones pedidas, como `(acción, campos)`.
        manejar: El manejador de mensajes de la ventana.
        elegir: El id que «elige» el menú.
        menus: Los menús que se han pedido.
        soltados: Los iconos soltados.
        fin: Se activa al acabar el bucle.
    """
    def __init__(self, barra: bool = True):
        """Prepara la `Api` de mentira, con o sin barra de tareas."""
        self.barra = barra
        self.cola: queue.Queue = queue.Queue()
        self.llamadas: list = []
        self.manejar = None
        self.elegir = 0
        self.menus: list = []
        self.soltados: list = []
        self.fin = threading.Event()

    def mensaje_registrado(self, nombre):
        """Devuelve el id de `TaskbarCreated`, o 0 para otro nombre."""
        return TASKBAR if nombre == "TaskbarCreated" else 0

    def ventana(self, manejar):
        """Guarda el manejador y devuelve un manejador de ventana de mentira."""
        self.manejar = manejar
        return 777

    def bucle(self):
        """Reparte los mensajes de la cola hasta que llega el de salir."""
        while True:
            msg, w, l = self.cola.get()
            if msg is None:
                break
            self.manejar(777, msg, w, l)
        self.fin.set()

    def salir(self):
        """Pide al bucle que acabe."""
        self.cola.put((None, 0, 0))

    def destruir(self, hwnd):
        """Manda `WM_DESTROY` a la ventana."""
        self.manejar(hwnd, bw.WM_DESTROY, 0, 0)

    def post(self, hwnd, msg):
        """Deja un mensaje en la cola, como `PostMessageW`."""
        self.cola.put((msg, 0, 0))
        return True

    def enviar(self, msg, w=0, l=0):
        """Lo que manda Windows (una difusión, un clic en el icono)."""
        self.cola.put((msg, w, l))

    def handle_de(self, lparam):
        """El handle de un aviso `DBT_DEVTYP_HANDLE`: aquí, el `lParam` si es un número."""
        return lparam if isinstance(lparam, int) and lparam >= 1000 else None

    def icono(self, ruta):
        """Devuelve un manejador de icono de mentira."""
        return f"H:{ruta.name}"

    def soltar_icono(self, h):
        """Apunta el icono soltado."""
        self.soltados.append(h)

    def notificar(self, accion, **campos):
        """Apunta una notificación; `NIM_ADD` falla sin barra de tareas."""
        self.llamadas.append((accion, campos))
        return accion != bw.NIM_ADD or self.barra

    def menu(self, hwnd, entradas, ids):
        """Apunta el menú y devuelve lo que «elige» el test."""
        self.menus.append((entradas, ids))
        return self.elegir


def esperar(condicion, segundos=3.0) -> bool:
    """Espera hasta `segundos` a que se cumpla la condición; devuelve si se cumplió."""
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

vista = bandeja.vista({"pausado": True, "ausentes": ["C:\\x.hc"], "unidades": [
    {"id": "u1", "nombre": "PRDRIVE-1", "atendida": True, "en_lista": True}]})
b.poner(vista)
c("poner() desde otro hilo cambia icono y línea (NIM_MODIFY)",
  esperar(lambda: api.llamadas[-1][0] == bw.NIM_MODIFY
          and api.llamadas[-1][1]["icono"] == "H:bandeja-pausa.ico"), True)
c("  con la línea de la vista", api.llamadas[-1][1]["tip"], "prdrive · en pausa")

# el menú
ids = bw.numerar(vista.menu)
api.elegir = next(n for n, e in ids.items() if e.texto == "Reanudar")
api.enviar(bw.WM_ICONO, 0, bw.WM_RBUTTONUP)
c("clic derecho: menú, y lo elegido va al agente",
  esperar(lambda: PEDIDAS == [{"pide": equipo.PIDE_SIGUE}]), True)
api.elegir = next(n for n, e in ids.items() if e.texto == "Configurar")
api.enviar(bw.WM_ICONO, 0, bw.WM_LBUTTONUP)
c("  el izquierdo también abre el menú; «Configurar» de su desplegable abre su ventana",
  esperar(lambda: PEDIDAS[-1] == {"pide": equipo.PIDE_ABRIR, "id": "u1"}), True)
c("  el desplegable del dispositivo no lleva id (lo abre Windows) y sí su icono",
  ([e.texto for e in ids.values() if e.hijos], vista.menu[2].texto,
   vista.menu[2].emblema), ([], "PRDRIVE-1", bandeja.MARCA))
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

# lo que difunde Windows
api.enviar(bw.WM_DEVICECHANGE, bw.DBT_DEVICEARRIVAL, 0)
c("WM_DEVICECHANGE (llega un volumen) despierta el recorrido",
  esperar(lambda: MONTAJES == [1]), True)
api.enviar(bw.WM_DEVICECHANGE, 0x0018, 0)      # DBT_CONFIGCHANGED: nada que ver
time.sleep(0.05)
c("  otros WM_DEVICECHANGE no", MONTAJES, [1])
DISPOSITIVO: list = []
api.enviar(bw.WM_DEVICECHANGE, bw.DBT_DEVICEQUERYREMOVE, 4242)
time.sleep(0.05)
c("sin quien atienda los avisos de extracción no pasa nada", (DISPOSITIVO, MONTAJES), ([], [1]))
b.dispositivo = lambda evento, h: DISPOSITIVO.append((evento, h))
api.enviar(bw.WM_DEVICECHANGE, bw.DBT_DEVICEQUERYREMOVE, 4242)
c("el sistema pide la unidad de un handle nuestro: se le pasa al motor de avisos",
  esperar(lambda: DISPOSITIVO == [(bw.DBT_DEVICEQUERYREMOVE, 4242)]), True)
c("  y no es un cambio de montajes", MONTAJES, [1])
for evento in (bw.DBT_DEVICEQUERYREMOVEFAILED, bw.DBT_DEVICEREMOVEPENDING):
    api.enviar(bw.WM_DEVICECHANGE, evento, 4242)
api.enviar(bw.WM_DEVICECHANGE, bw.DBT_DEVICEREMOVECOMPLETE, 4242)
c("  y los demás de ese handle también", esperar(lambda: len(DISPOSITIVO) == 4) and [
    e for e, _ in DISPOSITIVO], [bw.DBT_DEVICEQUERYREMOVE, bw.DBT_DEVICEQUERYREMOVEFAILED,
                                bw.DBT_DEVICEREMOVEPENDING, bw.DBT_DEVICEREMOVECOMPLETE])
c("  la extracción acabada sigue despertando el recorrido", esperar(lambda: MONTAJES == [1, 1]),
  True)
api.enviar(bw.WM_DEVICECHANGE, bw.DBT_DEVICEQUERYREMOVE, 7)       # un volumen, no un handle
time.sleep(0.05)
c("  un aviso que no es de un handle no se le pasa", len(DISPOSITIVO), 4)
b.dispositivo = lambda evento, h: 1 / 0
api.enviar(bw.WM_DEVICECHANGE, bw.DBT_DEVICEQUERYREMOVE, 4242)
api.enviar(bw.WM_DEVICECHANGE, bw.DBT_DEVICEARRIVAL, 0)
c("  y si el motor falla, la bandeja sigue", esperar(lambda: MONTAJES == [1, 1, 1]), True)
b.dispositivo = None
api.enviar(bw.WM_POWERBROADCAST, bw.PBT_APMRESUMEAUTOMATIC, 0)
c("la vuelta de la suspensión pide «despertar»",
  esperar(lambda: PEDIDAS[-1] == {"pide": equipo.PIDE_DESPERTAR}), True)
antes = len([a for a, _ in api.llamadas if a == bw.NIM_ADD])
api.enviar(TASKBAR)
c("TaskbarCreated (el Explorador reiniciado) vuelve a poner el icono",
  esperar(lambda: len([a for a, _ in api.llamadas if a == bw.NIM_ADD]) == antes + 1), True)
c("  con la última vista", api.llamadas[-1][1]["tip"], "prdrive · en pausa")

# los avisos
c("un aviso se cuelga del icono", b.globo("PRDRIVE-1: falla docs", "Mira la ventana", True),
  True)
accion, campos = api.llamadas[-1]
c("  con NIF_INFO, título y texto, y de aviso si es urgente",
  (accion, campos["flags"], campos["info_titulo"], campos["info"], campos["info_flags"]),
  (bw.NIM_MODIFY, bw.NIF_INFO, "PRDRIVE-1: falla docs", "Mira la ventana", bw.NIIF_WARNING))
c("avisos.enviar en Windows usa la bandeja, sin icono de paso",
  (avisos._windows("t", "x", False), api.llamadas[-1][1]["info_titulo"]), (True, "t"))

# cerrar
b.cerrar()
c("al cerrar se quita el icono", esperar(lambda: api.llamadas[-1][0] == bw.NIM_DELETE), True)
c("  se sueltan los iconos cargados", sorted(api.soltados),
  ["H:bandeja-bien.ico", "H:bandeja-pausa.ico"])
c("  acaba su hilo", api.fin.is_set(), True)
c("  y los avisos vuelven a su icono de paso", avisos.GLOBO, None)
c("  un aviso ya no se cuelga", b.globo("t", "x"), False)

# sin barra de tareas al arrancar
api = ApiFalsa(barra=False)
b = bw.Bandeja(CARPETA, PEDIDAS.append, lambda: None, api=api)
c("sin barra de tareas todavía, la ventana vive igual", (b.arrancar(), b.puesta),
  (True, False))
c("  y un aviso no se cuelga (va al icono de paso)", b.globo("t", "x"), False)
api.barra = True
api.enviar(TASKBAR)
c("  al llegar TaskbarCreated se pone el icono", esperar(lambda: b.puesta), True)
b.cerrar()

# sin ventana
class SinVentana(ApiFalsa):
    """`Api` que no consigue crear la ventana."""
    def ventana(self, manejar):
        """Devuelve `None`: no hay ventana."""
        return None


b = bw.Bandeja(CARPETA, PEDIDAS.append, lambda: None, api=SinVentana())
c("sin ventana no hay bandeja, y el agente sigue sin ella", b.arrancar(), False)
c("  ni se tocan los avisos", avisos.GLOBO, None)

# un icono que falta
(CARPETA / "bandeja-aviso.ico").unlink()
api = ApiFalsa()
b = bw.Bandeja(CARPETA, PEDIDAS.append, lambda: None, api=api)
b.arrancar()
b.poner(bandeja.vista({"unidades": [{"id": "u", "nombre": "U", "fallando": ["x"]}]}))
c("sin el .ico de un estado se usa el de «bien»",
  esperar(lambda: api.llamadas[-1][1].get("icono") == "H:bandeja-bien.ico"
          and "falla" in api.llamadas[-1][1].get("tip", "")), True)
b.cerrar()

# el icono de un dispositivo
VERDE = bandeja.Emblema(campo=icons.CAMPOS["verde"])
llamado: list = []


def de_ico(ruta, lado):
    """Pinta un .ico de mentira: un cuadro opaco del tamaño pedido."""
    llamado.append(ruta)
    return bytes([1, 2, 3, 255]) * (lado * lado)


ICO = CARPETA / "icono-propio-0123abcd.ico"
ICO.write_bytes(icons.ico((16,)))
c("la marca en el color de su campo, sin leer nada",
  (bw.pixeles_emblema(VERDE, 16, de_ico), llamado), (icons.pixeles_marca(16, VERDE.campo), []))
c("  un .ico propio lo pinta Windows (de_ico), al tamaño del menú",
  bw.pixeles_emblema(bandeja.Emblema(ico=str(ICO)), 16, de_ico),
  bytes([1, 2, 3, 255]) * 256)
marca = icons.pixeles_marca(16)
c("  si no se puede pintar, o no del tamaño, o falla: la marca, sin error",
  [bw.pixeles_emblema(bandeja.Emblema(ico=str(ICO)), 16, f) == marca for f in
   (lambda r, l: None, lambda r, l: b"\0" * 10, lambda r, l: 1 / 0)], [True, True, True])
llamado.clear()
c("  si no está, ni se intenta",
  (bw.pixeles_emblema(bandeja.Emblema(ico=str(CARPETA / "no.ico")), 16, de_ico) == marca,
   llamado), (True, []))
tope = icons.MAX_ICO
icons.MAX_ICO = 10
c("  ni si pasa de MAX_ICO",
  (bw.pixeles_emblema(bandeja.Emblema(ico=str(ICO)), 16, de_ico) == marca, llamado),
  (True, []))
icons.MAX_ICO = tope
c("un icono sin alfa toma la transparencia de su máscara (negro = opaco)",
  bw.alfa_desde_mascara(bytes([10, 20, 30, 0, 40, 50, 60, 0]),
                        bytes([0, 0, 0, 0, 255, 255, 255, 0])),
  bytes([10, 20, 30, 255, 0, 0, 0, 0]))


# el menú de verdad (Api.menu) sobre un user32 y un gdi32 de mentira
import ctypes  # noqa: E402
from ctypes import wintypes  # noqa: E402


class User32:
    """user32 de mentira: apunta los menús que se construyen.

    Attributes:
        menus: Lo añadido a cada menú, `(flags, id o submenú, texto)`.
        defecto: Las entradas por defecto puestas, `(menú, id)`.
        bitmaps: Los mapas de bits puestos, `(menú, posición, mapa)`.
        elegir: El id que «elige» la persona.
    """
    def __init__(self):
        """Empieza sin menús."""
        self.menus, self.defecto, self.bitmaps, self.destruidos = {}, [], [], []
        self.elegir = 0
        self.cargados: list = []

    def GetSystemMetrics(self, n):
        """El icono pequeño: 16 px."""
        return 16

    def GetSysColor(self, n):
        """El texto del menú, negro."""
        return 0

    def CreatePopupMenu(self):
        """Un menú nuevo."""
        h = 1000 + len(self.menus)
        self.menus[h] = []
        return h

    def AppendMenuW(self, h, flags, ident, texto):
        """Añade una entrada."""
        self.menus[h].append((flags, ident, texto))

    def GetMenuItemCount(self, h):
        """Cuántas entradas tiene."""
        return len(self.menus[h])

    def SetMenuItemInfoW(self, h, pos, por_posicion, info):
        """Apunta el mapa de bits de una entrada."""
        self.bitmaps.append((h, pos, info._obj.hbmpItem))

    def SetMenuDefaultItem(self, h, ident, por_posicion):
        """Apunta la entrada por defecto de un menú."""
        self.defecto.append((h, ident))

    def LoadImageW(self, *args):
        """No carga nada: como un .ico que Windows no entiende."""
        self.cargados.append(args[1])
        return 0

    def GetCursorPos(self, punto):
        """El ratón, en el origen."""

    def SetForegroundWindow(self, hwnd):
        """Nada."""

    def TrackPopupMenu(self, *args):
        """Devuelve lo que «elige» la persona."""
        return self.elegir

    def PostMessageW(self, *args):
        """Nada."""

    def DestroyMenu(self, h):
        """Apunta el menú destruido."""
        self.destruidos.append(h)


class Gdi32:
    """gdi32 de mentira: DIB de verdad en memoria de Python.

    Attributes:
        dibs: Cada mapa de bits creado y su memoria.
        borrados: Los mapas de bits borrados.
    """
    def __init__(self):
        """Empieza sin mapas de bits."""
        self.dibs, self.borrados = {}, []

    def CreateDIBSection(self, hdc, cabecera, uso, bits, seccion, desde):
        """Crea un DIB a ceros y devuelve su manejador."""
        c_ = cabecera._obj
        memoria = ctypes.create_string_buffer(c_.biWidth * -c_.biHeight * 4)
        bits._obj.value = ctypes.addressof(memoria)
        h = 5000 + len(self.dibs)
        self.dibs[h] = memoria
        return h

    def DeleteObject(self, h):
        """Apunta el mapa de bits borrado."""
        self.borrados.append(h)


api = object.__new__(bw.Api)
api.ct, api.wt = ctypes, wintypes
api.MENUITEMINFOW, api.BITMAPINFOHEADER = bw.estructuras(ctypes, wintypes)
api.user32, api.gdi32, api._pixeles = User32(), Gdi32(), bandeja.CacheAcotada()
vista = bandeja.vista({"unidades": [
    {"id": "u1", "nombre": "Verde & Co", "en_lista": True, "atendida": True,
     "emblema": {"marca": "verde"}},
    {"id": "u2", "nombre": "Propia", "en_lista": True, "emblema": {"ico": str(ICO)}}]})
ids = bw.numerar(vista.menu)
configurar = [n for n, e in ids.items() if e.texto == "Configurar"]
api.user32.elegir = configurar[1]
c("Api.menu devuelve el id elegido: el «Configurar» del segundo dispositivo",
  ids[api.menu(777, vista.menu, ids)].pide, ({"pide": equipo.PIDE_ABRIR, "id": "u2"},))
u, g = api.user32, api.gdi32
raiz = min(u.menus)
populares = [(f, sub, t) for f, sub, t in u.menus[raiz] if f & bw.MF_POPUP]
c("  cada dispositivo es un submenú (MF_POPUP) con su nombre, & doblado",
  [t for _f, _s, t in populares], ["Verde && Co", "Propia"])
c("  en cada submenú, «Configurar» es la entrada por defecto: el doble clic la elige",
  sorted(u.defecto), sorted(zip([s for _f, s, _t in populares], configurar)))
iconos_raiz = {pos: h for m, pos, h in u.bitmaps if m == raiz}
c("  los dos desplegables llevan su icono (y «Pausar» y «Cerrar el agente», su glifo)",
  sorted(iconos_raiz), [0, 1, 3, 5])
c("  el primero, la marca en verde",
  bytes(g.dibs[iconos_raiz[0]]), icons.pixeles_marca(16, icons.CAMPOS["verde"]))
c("  el segundo, su .ico, que Windows no ha sabido cargar: la marca de prdrive",
  (u.cargados, bytes(g.dibs[iconos_raiz[1]]) == icons.pixeles_marca(16)),
  ([str(ICO)], True))
c("  y al cerrar se destruye el menú y se borran todos los mapas de bits",
  (u.destruidos, sorted(g.borrados)), ([raiz], sorted(g.dibs)))

for i in range(bandeja.TOPE_CACHE + 20):
    api._bitmap_emblema(bandeja.Emblema(campo=f"#{i:06x}"), 16)
c("la caché de iconos pintados tiene tope: cada icono nuevo no se queda para siempre",
  len(api._pixeles), bandeja.TOPE_CACHE)

sys.exit(c.report())
