#!/usr/bin/env python3
"""Los atajos de teclado globales en Linux (`ui/atajos_linux.py`), con dobles y con un X de verdad.

- **X11** con una Xlib de mentira: cada combinación se agarra con y sin los
  bloqueos; una que tiene otro (`BadAccess`) se suelta entera y se dice; una
  tecla que el teclado no tiene, también; un `KeyPress` agarrado es la acción,
  una vez aunque se repita mientras sigue abajo; cerrar lo suelta todo.
- **El portal** con un bus de mentira (`tests/_bus_falso.py`): sin portal no
  hay atajos y se dice por qué; `CreateSession` y `BindShortcuts` con sus
  respuestas; lo que el escritorio no ata, o una cancelación, se dice; la
  señal `Activated` es la acción; cambiar los atajos cierra la sesión de antes.
- **X de verdad**, en un `Xvfb` propio que arranca el test (nunca la pantalla
  de quien lo corre: se le mandarían teclas): agarrar, que otro cliente tenga
  la combinación, pulsar con XTEST, el bloqueo de mayúsculas, la tecla
  mantenida y que el proceso sobrevive a que el servidor se vaya. Sin Xvfb,
  libX11 o libXtst, se salta.

En Windows solo corre la elección del motor: los hilos se despiertan con un
`select()` sobre un pipe, que allí no existe.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import threading
import time

from _harness import Checks

import _bus_falso
from common import dbus
from ui import atajos, atajos_linux as al

c = Checks("atajos de teclado en Linux")


def esperar(condicion, segundos=3.0) -> bool:
    """Espera hasta `segundos` a que se cumpla la condición; devuelve si se cumplió."""
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.01)
    return condicion()


c("elegir: Wayland es el portal y X11 XGrabKey",
  (type(al.poner(atajos.PORTAL, print, print)).__name__,
   type(al.poner(atajos.X11, print, print)).__name__), ("Portal", "X11"))

if os.name == "nt":
    # Lo que sigue corre los hilos de los motores, que se despiertan con un pipe
    # vigilado por select(), y en Windows select() solo admite sockets. En
    # Windows los atajos los pone la bandeja (`tests/test_bandeja_windows.py`).
    print("  (saltado) los motores de atajos de Linux: solo en Linux")
    sys.exit(c.report())


# --- X11 con una Xlib de mentira

class XlibFalsa:
    """Una conexión a X de mentira: apunta lo agarrado y entrega los eventos que le dan.

    Attributes:
        agarradas: Las `(keycode, máscara)` agarradas ahora.
        ocupadas: Las que tiene «otro cliente»: agarrarlas da `BadAccess`.
        teclado: El keycode de cada keysym que tiene este teclado.
    """

    def __init__(self):
        """Prepara la conexión, con un pipe que hace de su descriptor."""
        self.agarradas: set[tuple[int, int]] = set()
        self.ocupadas: set[tuple[int, int]] = set()
        self.teclado = {"s": 39, "v": 55, "F9": 75, "p": 33}
        self._eventos: list = []
        self._pipe = os.pipe()
        self.roto = False
        self.cerrada = False

    def fileno(self):
        """El descriptor que mira el `select` del hilo."""
        return self._pipe[0]

    def keycode(self, keysym):
        """El keycode de esa tecla, o 0 si este teclado no la tiene."""
        return self.teclado.get(keysym, 0)

    def agarrar(self, keycode, mascara):
        """Agarra, salvo que la tenga otro: entonces `BadAccess`."""
        if (keycode, mascara) in self.ocupadas:
            return al.BAD_ACCESS
        self.agarradas.add((keycode, mascara))
        return 0

    def soltar(self, keycode, mascara):
        """Suelta."""
        self.agarradas.discard((keycode, mascara))

    def llega(self, tipo, keycode, estado):
        """Le llega un evento de teclado del servidor."""
        self._eventos.append((tipo, keycode, estado))
        os.write(self._pipe[1], b"!")

    def eventos(self):
        """Entrega lo que ha llegado."""
        try:
            os.read(self._pipe[0], 4096) if self._eventos else None
        except OSError:
            pass
        salida, self._eventos = self._eventos, []
        return salida

    def vivo(self):
        """Si el servidor sigue ahí."""
        return not self.roto

    def cerrar(self):
        """Cierra."""
        self.cerrada = True


PULSADOS: list = []
PUESTOS: list = []
xf = XlibFalsa()
x = al.X11(PULSADOS.append, lambda combos, rechazados: PUESTOS.append((combos, rechazados)),
           abrir=lambda: xf)
c("X11: arranca con su conexión", (x.arrancar(), x.nombre, x.suspende), (True, "XGrabKey", True))
CTRL_ALT = 0x4 | 0x8
xf.ocupadas.add((55, CTRL_ALT | 0x10))      # ctrl+alt+v, solo con el bloqueo numérico
x.poner({atajos.SINCRONIZAR: "ctrl+alt+s", atajos.VENTANA: "ctrl+alt+v",
         atajos.CARPETA: "ctrl+alt+f24"})
c("  pone lo pedido y dice lo que no", esperar(lambda: bool(PUESTOS)), True)
c("  la que tiene otro (aunque sea con un bloqueo) y la tecla que no hay, con su motivo",
  PUESTOS[-1][1], {atajos.VENTANA: atajos.YA_LA_USA, atajos.CARPETA: atajos.SIN_ESA_TECLA})
c("  la buena, agarrada con y sin los bloqueos; de la ocupada no queda nada",
  sorted(xf.agarradas), sorted((39, CTRL_ALT | b) for b in atajos.BLOQUEOS_X11))
xf.llega(al.KEY_PRESS, 39, CTRL_ALT | 0x2)
c("un KeyPress agarrado es su acción, también con el bloqueo de mayúsculas",
  esperar(lambda: PULSADOS == [atajos.SINCRONIZAR]), True)
xf.llega(al.KEY_PRESS, 39, CTRL_ALT)
xf.llega(al.KEY_PRESS, 39, CTRL_ALT)
xf.llega(al.KEY_PRESS, 55, CTRL_ALT)
time.sleep(0.2)
c("  mantenida no se repite, y lo que no está agarrado no hace nada", PULSADOS,
  [atajos.SINCRONIZAR])
xf.llega(al.KEY_RELEASE, 39, CTRL_ALT)
xf.llega(al.KEY_PRESS, 39, CTRL_ALT | 0x10)
c("  soltada, la siguiente pulsación vale otra vez",
  esperar(lambda: PULSADOS == [atajos.SINCRONIZAR] * 2), True)
x.poner({atajos.PAUSAR: "super+p"})
c("otros atajos sueltan los de antes", (esperar(lambda: len(PUESTOS) == 2),
                                        sorted(xf.agarradas)),
  (True, sorted((33, 0x40 | b) for b in atajos.BLOQUEOS_X11)))
x.cerrar()
c("cerrar lo suelta todo y cierra la conexión", (xf.agarradas, xf.cerrada), (set(), True))


def sin_x():
    """Una pantalla que no se puede abrir."""
    raise OSError("no se puede abrir la pantalla ':9'")


x = al.X11(PULSADOS.append, lambda *a: None, abrir=sin_x)
c("sin X no arranca, y dice por qué", (x.arrancar(), "':9'" in x.motivo), (False, True))


# --- el portal, con un bus de mentira

SESION = "/org/freedesktop/portal/desktop/session/1_42/s1"
PETICIONES: list = []
RESPUESTAS = {"bind": (0, None)}
"""Lo que contesta el portal a `BindShortcuts`: `(código, ids atados o None = todos)`, `"error"`
o `"mudo"` (no manda nunca su `Response`)."""
CON_PORTAL = [True]


def responder(m):
    """Hace de portal: contesta y, poco después, manda la señal `Response`."""
    if m.miembro == "Get" and m.cuerpo[:1] == [al.ATAJOS_PORTAL]:
        if not CON_PORTAL[0]:
            return ("error", "org.freedesktop.DBus.Error.UnknownInterface", "sin portal")
        return ("ok", "v", [dbus.Variante("u", 1)])
    if m.miembro == "Register":
        PETICIONES.append(("Register", m.cuerpo[0]))
        return ("ok", "", [])
    if m.miembro == "Close":
        PETICIONES.append(("Close", m.ruta))
        return ("ok", "", [])
    if m.miembro == "CreateSession":
        ruta = f"/org/freedesktop/portal/desktop/request/1_42/{m.cuerpo[0]['handle_token']}"
        PETICIONES.append(("CreateSession", m.cuerpo[0]))
        threading.Timer(0.05, lambda: BUS.senal(
            ruta, al.PETICION, "Response", "ua{sv}",
            [0, {"session_handle": dbus.Variante("s", SESION)}])).start()
        return ("ok", "o", [ruta])
    if m.miembro == "BindShortcuts":
        if RESPUESTAS["bind"] == "error":
            return ("error", "org.freedesktop.portal.Error.Failed", "no")
        ruta = f"/org/freedesktop/portal/desktop/request/1_42/{m.cuerpo[3]['handle_token']}"
        PETICIONES.append(("BindShortcuts", m.cuerpo[0], m.cuerpo[1]))
        if RESPUESTAS["bind"] == "mudo":             # su ventana se queda abierta
            PETICIONES.append(("Request", ruta))
            return ("ok", "o", [ruta])
        codigo, atados = RESPUESTAS["bind"]
        lista = [(i, {"description": dbus.Variante("s", "x"),
                      "trigger_description": dbus.Variante("s", "Ctrl+Alt+S")})
                 for i, _datos in m.cuerpo[1] if atados is None or i in atados]
        threading.Timer(0.05, lambda: BUS.senal(
            ruta, al.PETICION, "Response", "ua{sv}",
            [codigo, {"shortcuts": dbus.Variante("a(sa{sv})", lista)}])).start()
        return ("ok", "o", [ruta])
    return None


CONEXION, BUS = _bus_falso.conectar(responder)
PULSADOS.clear()
PUESTOS.clear()
p = al.Portal(PULSADOS.append, lambda combos, rechazados: PUESTOS.append((combos, rechazados)),
              conectar=lambda: CONEXION)
c("portal: arranca si el portal tiene GlobalShortcuts", (p.arrancar(), p.suspende),
  (True, False))
c("  y se registra con el nombre del acceso del menú",
  esperar(lambda: ("Register", "prdrive") in PETICIONES), True)
c("  y escucha las respuestas y los atajos pulsados",
  sorted(m.cuerpo[0] for m in BUS.recibidos if m.miembro == "AddMatch"),
  sorted([al.REGLA_RESPUESTA, al.REGLA_PULSADO]))
RESPUESTAS["bind"] = (0, {atajos.SINCRONIZAR})
p.poner({atajos.SINCRONIZAR: "ctrl+alt+s", atajos.VENTANA: "super+shift+v"})
c("  abre una sesión y ata los atajos; lo que el escritorio no ata se dice",
  (esperar(lambda: bool(PUESTOS)), PUESTOS[-1][1] if PUESTOS else None),
  (True, {atajos.VENTANA: atajos.RECHAZADA_PORTAL}))
atar = next(x for x in PETICIONES if x[0] == "BindShortcuts")
c("  en su sesión, con su descripción y el disparador preferido",
  (atar[1], [(i, d.get("preferred_trigger")) for i, d in atar[2]],
   atar[2][0][1]["description"]),
  (SESION, [(atajos.SINCRONIZAR, "CTRL+ALT+s"), (atajos.VENTANA, "SHIFT+LOGO+v")],
   "prdrive: Sincronizar ahora"))
BUS.senal(al.PORTAL_RUTA, al.ATAJOS_PORTAL, "Activated", "osta{sv}",
          [SESION, atajos.SINCRONIZAR, 123, {}])
c("Activated de su sesión es la acción", esperar(lambda: PULSADOS == [atajos.SINCRONIZAR]),
  True)
BUS.senal(al.PORTAL_RUTA, al.ATAJOS_PORTAL, "Activated", "osta{sv}",
          ["/otra/sesion", atajos.VENTANA, 124, {}])
BUS.senal(al.PORTAL_RUTA, al.ATAJOS_PORTAL, "Activated", "osta{sv}",
          [SESION, "formatear", 125, {}])
time.sleep(0.2)
c("  la de otra sesión, o un id que no es una acción, no", PULSADOS, [atajos.SINCRONIZAR])
RESPUESTAS["bind"] = (al.RESPUESTA_CANCELADA, None)
p.poner({atajos.PAUSAR: "ctrl+alt+p"})
c("cambiarlos cierra la sesión de antes; cancelado en el escritorio, se dice",
  (esperar(lambda: len(PUESTOS) == 2), ("Close", SESION) in PETICIONES,
   PUESTOS[-1][1] if len(PUESTOS) == 2 else None),
  (True, True, {atajos.PAUSAR: atajos.CANCELADA_PORTAL}))
p.poner({})
c("sin ninguno, nada que atar", (esperar(lambda: len(PUESTOS) == 3), PUESTOS[-1]),
  (True, ({}, {})))
RESPUESTAS["bind"] = "error"
p.poner({atajos.CARPETA: "ctrl+alt+c"})
c("un error del portal en vez de su Request: no puesto en el acto, y el hilo sigue",
  (esperar(lambda: len(PUESTOS) == 4), PUESTOS[-1][1] if len(PUESTOS) == 4 else None,
   p._hilo.is_alive()),
  (True, {atajos.CARPETA: atajos.RECHAZADA_PORTAL}, True))
RESPUESTAS["bind"] = "mudo"
p.poner({atajos.CARPETA: "ctrl+alt+c"})
esperar(lambda: any(x[0] == "Request" for x in PETICIONES))
time.sleep(0.2)
colgada = next((x[1] for x in PETICIONES if x[0] == "Request"), "")
c("un portal que no contesta (su ventana se queda abierta): se espera, sin contestar",
  (bool(colgada), len(PUESTOS)), (True, 4))
RESPUESTAS["bind"] = (0, None)
p.poner({atajos.VENTANA: "super+shift+v"})
c("  lo siguiente que se pide no se queda detrás: cierra esa petición y se atiende",
  (esperar(lambda: len(PUESTOS) == 5), ("Close", colgada) in PETICIONES,
   PUESTOS[-1] if len(PUESTOS) == 5 else None),
  (True, True, ({atajos.VENTANA: "super+shift+v"}, {})))
c("  y a lo que se dejó no se le contesta nunca", (time.sleep(0.2), len(PUESTOS))[1], 5)
p.cerrar()
CONEXION, BUS = _bus_falso.conectar(responder)
CON_PORTAL[0] = False
p = al.Portal(PULSADOS.append, lambda *a: None, conectar=lambda: CONEXION)
c("sin el portal no hay atajos, y se dice por qué", (p.arrancar(), p.motivo),
  (False, atajos.SIN_PORTAL))
c("  y cerrar() cierra su pipe", (p.cerrar(), p._pipe_cerrado)[1], True)
SUELTA = threading.Event()


def bus_que_tarda():
    """Un bus de sesión que, al entrar en la sesión, tarda más de lo que se espera."""
    SUELTA.wait(5.0)
    raise OSError("el bus no contesta")


antes = al.ESPERA_ARRANQUE
al.ESPERA_ARRANQUE = 0.1
try:
    p = al.Portal(PULSADOS.append, lambda *a: None, conectar=bus_que_tarda)
    arranca = p.arrancar()
    p.cerrar()
    c("un hilo que no acaba a tiempo: no arranca, y cerrar() no le cierra el pipe aún",
      (arranca, p._pipe_cerrado), (False, False))
    SUELTA.set()
    c("  lo cierra el hilo al acabar (si no, cada reintento del agente dejaría uno abierto)",
      (esperar(lambda: not p._hilo.is_alive()), p._pipe_cerrado), (True, True))
finally:
    al.ESPERA_ARRANQUE = antes


# --- X de verdad, en un Xvfb propio

def x_de_verdad() -> str | None:
    """Devuelve por qué no se puede probar con un X de verdad, o `None` si se puede."""
    if os.name == "nt" or not shutil.which("Xvfb"):
        return "sin Xvfb"
    for biblioteca in ("libX11.so.6", "libXtst.so.6"):
        try:
            ctypes.CDLL(biblioteca)
        except OSError:
            return f"sin {biblioteca}"
    return None


porque = x_de_verdad()
if porque is not None:
    print(f"  (saltado) XGrabKey de verdad: {porque}")
else:
    pantalla = f":{90 + os.getpid() % 100}"
    xvfb = subprocess.Popen(["Xvfb", pantalla, "-screen", "0", "640x480x24", "-nolisten", "tcp"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    antes = os.environ.get("DISPLAY")
    os.environ["DISPLAY"] = pantalla
    try:
        X = ctypes.CDLL("libX11.so.6")
        X.XOpenDisplay.restype = ctypes.c_void_p
        X.XOpenDisplay.argtypes = [ctypes.c_char_p]
        d = None
        limite = time.monotonic() + 10
        while d is None and time.monotonic() < limite:
            d = X.XOpenDisplay(pantalla.encode()) or None
            if d is None:
                time.sleep(0.1)
        if d is None:
            print("  (saltado) XGrabKey de verdad: Xvfb no arranca")
        else:
            xt = ctypes.CDLL("libXtst.so.6")
            xt.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int,
                                             ctypes.c_ulong]
            X.XFlush.argtypes = [ctypes.c_void_p]
            X.XStringToKeysym.argtypes = [ctypes.c_char_p]
            X.XStringToKeysym.restype = ctypes.c_ulong
            X.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            X.XKeysymToKeycode.restype = ctypes.c_ubyte

            def teclas(*nombres, abajo=True, arriba=True):
                """Pulsa (y suelta) esas teclas con XTEST, como si fueran de verdad."""
                codigos = [X.XKeysymToKeycode(d, X.XStringToKeysym(n.encode()))
                           for n in nombres]
                if abajo:
                    for k in codigos:
                        xt.XTestFakeKeyEvent(d, k, 1, 0)
                if arriba:
                    for k in reversed(codigos):
                        xt.XTestFakeKeyEvent(d, k, 0, 0)
                X.XFlush(d)

            PULSADOS.clear()
            PUESTOS.clear()
            x = al.X11(PULSADOS.append, lambda co, re: PUESTOS.append((co, re)))
            c("X de verdad: arranca contra el Xvfb", x.arrancar(), True)
            otro = al.Xlib()
            c("  otro cliente agarra Ctrl+Alt+V antes",
              otro.agarrar(otro.keycode("v"), CTRL_ALT), 0)
            x.poner({atajos.SINCRONIZAR: "ctrl+alt+s", atajos.VENTANA: "ctrl+alt+v"})
            c("  BadAccess: la de otro se dice al ponerla",
              (esperar(lambda: bool(PUESTOS)), PUESTOS[-1][1] if PUESTOS else None),
              (True, {atajos.VENTANA: atajos.YA_LA_USA}))
            teclas("Control_L", "Alt_L", "s")
            c("  Ctrl+Alt+S pulsada con XTEST llega como su acción",
              esperar(lambda: PULSADOS == [atajos.SINCRONIZAR]), True)
            teclas("Caps_Lock")
            teclas("Control_L", "Alt_L", "s")
            teclas("Caps_Lock")
            c("  también con el bloqueo de mayúsculas",
              esperar(lambda: PULSADOS == [atajos.SINCRONIZAR] * 2), True)
            teclas("Control_L", "Alt_L", arriba=False)
            for _ in range(4):
                teclas("s", arriba=False)
            teclas("s", abajo=False)
            teclas("Control_L", "Alt_L", abajo=False)
            time.sleep(0.4)
            c("  mantenida (cuatro KeyPress) cuenta una vez", PULSADOS,
              [atajos.SINCRONIZAR] * 3)
            PUESTOS.clear()
            x.poner({})
            esperar(lambda: bool(PUESTOS))
            teclas("Control_L", "Alt_L", "s")
            time.sleep(0.4)
            c("  soltados, ya no llegan", PULSADOS, [atajos.SINCRONIZAR] * 3)
            otro.cerrar()
            PUESTOS.clear()
            x.poner({atajos.SINCRONIZAR: "ctrl+alt+s"})
            esperar(lambda: bool(PUESTOS))
            xvfb.kill()
            xvfb.wait()
            c("  si el servidor se va, el hilo acaba y el proceso sigue",
              esperar(lambda: not x._hilo.is_alive(), 5.0), True)
            x.cerrar()
    finally:
        if xvfb.poll() is None:
            xvfb.kill()
            xvfb.wait()
        if antes is None:
            os.environ.pop("DISPLAY", None)
        else:
            os.environ["DISPLAY"] = antes

sys.exit(c.report())
