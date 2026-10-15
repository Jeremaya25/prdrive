"""F30: un atajo global con XGrabKey llega con otra aplicación delante (fila K3), y uno ocupado se rechaza (K4)."""

import ctypes
import os
import shutil
import subprocess
import time

import comun

CODIGO = "F30"
SISTEMA = "L"
QUE = ("atajo global con XGrabKey (X11): llega con otra aplicación con el foco, que no ve la "
       "tecla; uno que tiene otro cliente se rechaza al ponerlo")

KEY_PRESS_MASK, KEY_PRESS = 1, 2
REVERT_TO_PARENT, CURRENT_TIME = 2, 0


class OtraAplicacion:
    """Otro cliente de X con una ventana que tiene el foco y apunta las teclas que le llegan."""

    def __init__(self, x):
        """Crea su ventana, la enseña y le da el foco."""
        self.x = x
        self.d = x.XOpenDisplay(None)
        raiz = x.XDefaultRootWindow(self.d)
        self.ventana = x.XCreateSimpleWindow(self.d, raiz, 10, 10, 200, 100, 0, 0, 0)
        x.XSelectInput(self.d, self.ventana, KEY_PRESS_MASK)
        x.XMapRaised(self.d, self.ventana)
        x.XSync(self.d, 0)
        time.sleep(0.2)
        x.XSetInputFocus(self.d, self.ventana, REVERT_TO_PARENT, CURRENT_TIME)
        x.XSync(self.d, 0)
        self.evento = (ctypes.c_long * 24)()

    def foco(self):
        """Devuelve si su ventana tiene el foco."""
        f, r = ctypes.c_ulong(), ctypes.c_int()
        self.x.XGetInputFocus(self.d, ctypes.byref(f), ctypes.byref(r))
        return f.value == self.ventana

    def teclas(self, keysym):
        """Cuántos KeyPress de esa tecla le han llegado (los de los modificadores solos, no)."""
        class XKeyEvent(ctypes.Structure):
            """`XKeyEvent` de Xlib.h."""
            _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong),
                        ("send_event", ctypes.c_int), ("display", ctypes.c_void_p),
                        ("window", ctypes.c_ulong), ("root", ctypes.c_ulong),
                        ("subwindow", ctypes.c_ulong), ("time", ctypes.c_ulong),
                        ("x", ctypes.c_int), ("y", ctypes.c_int),
                        ("x_root", ctypes.c_int), ("y_root", ctypes.c_int),
                        ("state", ctypes.c_uint), ("keycode", ctypes.c_uint),
                        ("same_screen", ctypes.c_int)]

        codigo = self.x.XKeysymToKeycode(self.d, self.x.XStringToKeysym(keysym.encode()))
        n = 0
        while self.x.XPending(self.d) > 0:
            self.x.XNextEvent(self.d, ctypes.byref(self.evento))
            tecla = ctypes.cast(ctypes.byref(self.evento), ctypes.POINTER(XKeyEvent)).contents
            if tecla.type == KEY_PRESS and tecla.keycode == codigo:
                n += 1
        return n


def libx11():
    """libX11 con las firmas de lo que usa la prueba."""
    x = ctypes.CDLL("libX11.so.6")
    v, ul = ctypes.c_void_p, ctypes.c_ulong
    x.XOpenDisplay.restype, x.XOpenDisplay.argtypes = v, [ctypes.c_char_p]
    x.XDefaultRootWindow.restype, x.XDefaultRootWindow.argtypes = ul, [v]
    x.XCreateSimpleWindow.restype = ul
    x.XCreateSimpleWindow.argtypes = [v, ul, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
                                      ctypes.c_uint, ctypes.c_uint, ul, ul]
    x.XSelectInput.argtypes = [v, ul, ctypes.c_long]
    x.XMapRaised.argtypes = [v, ul]
    x.XSetInputFocus.argtypes = [v, ul, ctypes.c_int, ul]
    x.XGetInputFocus.argtypes = [v, ctypes.c_void_p, ctypes.c_void_p]
    x.XSync.argtypes = [v, ctypes.c_int]
    x.XPending.argtypes = [v]
    x.XNextEvent.argtypes = [v, v]
    x.XFlush.argtypes = [v]
    x.XStringToKeysym.restype, x.XStringToKeysym.argtypes = ul, [ctypes.c_char_p]
    x.XKeysymToKeycode.restype, x.XKeysymToKeycode.argtypes = ctypes.c_ubyte, [v, ul]
    return x


def probar(p: comun.Prueba) -> None:
    """Agarra en un Xvfb, con otra ventana con el foco, y pulsa con XTEST."""
    comun.apt("xvfb", "libx11-6", "libxtst6")
    if not shutil.which("Xvfb"):
        raise comun.Saltada("sin Xvfb")
    from ui import atajos, atajos_linux as al

    xvfb = subprocess.Popen(["Xvfb", ":77", "-screen", "0", "800x600x24", "-nolisten", "tcp"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.environ["DISPLAY"] = ":77"
    try:
        x = libx11()
        if not comun.esperar(lambda: bool(x.XOpenDisplay(None)), 10):
            raise comun.Saltada("Xvfb no arranca")
        xt = ctypes.CDLL("libXtst.so.6")
        xt.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int,
                                         ctypes.c_ulong]
        otra = OtraAplicacion(x)
        p.ver("la otra aplicación tiene el foco", otra.foco(), True)

        pulsados, puestos = [], []
        motor = al.X11(pulsados.append, lambda co, re: puestos.append((co, re)))
        p.ver("el motor de X11 arranca", motor.arrancar(), True)
        ocupa = al.Xlib()
        p.ver("un tercer cliente agarra antes Ctrl+Alt+V",
              ocupa.agarrar(ocupa.keycode("v"), 0x4 | 0x8), 0)
        motor.poner({atajos.SINCRONIZAR: "ctrl+alt+s", atajos.VENTANA: "ctrl+alt+v"})
        comun.esperar(lambda: bool(puestos), 5)
        p.ver("al ponerlos, el ocupado se rechaza con su motivo (BadAccess)",
              puestos[-1][1] if puestos else None, {atajos.VENTANA: atajos.YA_LA_USA})

        d = otra.d

        def pulsar(*nombres):
            """Pulsa y suelta esas teclas con XTEST."""
            codigos = [x.XKeysymToKeycode(d, x.XStringToKeysym(n.encode())) for n in nombres]
            for k in codigos:
                xt.XTestFakeKeyEvent(d, k, 1, 0)
            for k in reversed(codigos):
                xt.XTestFakeKeyEvent(d, k, 0, 0)
            x.XFlush(d)

        pulsar("Control_L", "Alt_L", "s")
        p.ver("Ctrl+Alt+S con la otra aplicación delante llega como su acción",
              comun.esperar(lambda: pulsados == [atajos.SINCRONIZAR], 5), True)
        time.sleep(0.3)
        p.ver("  y la otra aplicación no recibe la S", otra.teclas("s"), 0)
        pulsar("a")
        time.sleep(0.3)
        p.ver("  una tecla sin atajo sí le llega a ella", otra.teclas("a"), 1)
        pulsar("Num_Lock")
        pulsar("Control_L", "Alt_L", "s")
        p.ver("  con el bloqueo numérico encendido, también llega",
              comun.esperar(lambda: pulsados == [atajos.SINCRONIZAR] * 2, 5), True)
        pulsar("Num_Lock")
        puestos.clear()
        motor.poner({})
        comun.esperar(lambda: bool(puestos), 5)
        pulsar("Control_L", "Alt_L", "s")
        time.sleep(0.5)
        p.ver("soltados, ya no llegan y la tecla vuelve a la aplicación",
              (pulsados.count(atajos.SINCRONIZAR), otra.teclas("s")), (2, 1))
        motor.cerrar()
        ocupa.cerrar()
    finally:
        xvfb.kill()
        xvfb.wait()
