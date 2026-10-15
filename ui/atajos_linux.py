#!/usr/bin/env python3
"""Los atajos de teclado globales del agente en Linux: `XGrabKey` en X11 y el portal en Wayland.

Solo ponen y oyen: qué combinación es de qué acción, qué hace cada una y sobre
qué unidad lo decide `ui/atajos.py`. Cada uno corre en un hilo suyo con su
conexión (a X o al bus de sesión), y el agente les habla con `poner()` y
`cerrar()`, que despiertan el hilo por un pipe, como a la bandeja
(`ui/bandeja_linux.py`). Ellos le hablan con dos funciones que reciben al
crearse: `pulsado(accion)` cuando se pulsa un atajo, y `puestos(combos,
rechazados)` cuando acaban de poner lo pedido, con el motivo de cada
combinación que el sistema no ha dejado poner. Las dos se llaman desde su
hilo: tienen que ser baratas y seguras entre hilos.

**X11** (`X11`, con `Xlib` por ctypes contra `libX11.so.6`, sin bibliotecas):
cada combinación se agarra en la ventana raíz con `XGrabKey` («Xlib -
C Language X Interface», capítulo 12, «Input Device Functions»). El servidor
contesta `BadAccess` si otro cliente ya la tiene: el error llega por el
manejador de `XSetErrorHandler` tras un `XSync`, y esa combinación se suelta y
se da por rechazada. Se agarra cuatro veces, con y sin los bloqueos de
mayúsculas y numérico (`atajos.BLOQUEOS_X11`). Las repeticiones de una tecla
mantenida no repiten la acción: `XkbSetDetectableAutoRepeat` hace que lleguen
solo como `KeyPress` sin su `KeyRelease`, y una tecla que ya estaba abajo no
cuenta. Si el servidor se va (fin de sesión), Xlib llama a su manejador de
errores de E/S y, por defecto, termina el proceso: con
`XSetIOErrorExitHandler` (libX11 1.7) el hilo acaba y el agente sigue
(comprobado con un Xvfb que se mata, `tests/test_atajos_linux.py`). Queda una
rendija: si se va justo mientras se buscan las teclas al cambiar los atajos,
libX11 puede pedir el mapa del teclado y no recuperarse de esa respuesta que
no llega (visto: una violación de segmento). `X11._poner()` la estrecha con
un `XSync` antes de buscarlas; mientras solo se esperan atajos no hay
ninguna.

**Wayland** (`Portal`): el compositor no deja a un cliente agarrar teclas, así
que se pide al portal `org.freedesktop.portal.GlobalShortcuts`
(«XDG Desktop Portal», interfaz GlobalShortcuts) por el bus de sesión con
`common/dbus.py`: `CreateSession` y `BindShortcuts` con cada acción como
atajo y la combinación como disparador preferido (`atajos.portal()`). Las
dos contestan con un objeto `Request` y su señal `Response` llega después: la
de `BindShortcuts`, cuando el usuario ha confirmado en la ventana del
escritorio, que puede cambiar la tecla o cancelar. Lo que no venga en la
respuesta se da por rechazado. Cada atajo pulsado es la señal `Activated` con
su id. Para cambiar los atajos se cierra la sesión y se abre otra. Lo que se
pide mientras se espera una respuesta no se queda detrás de ella, que puede no
llegar nunca: la petición que espera se cierra (`Request.Close`). Antes de
nada se registra como `prdrive` (`org.freedesktop.host.portal.Registry`, que
solo existe en portales recientes: sin él sigue igual), el nombre del acceso
del menú que pone el instalador, que es con el que el escritorio los guarda.
Sin el portal no hay atajos, y se dice por qué (`atajos.SIN_PORTAL`).

**Sin probar en un escritorio de verdad**: las filas de «Atajos de teclado» de
`docs/superpowers/pruebas/2026-09-25-equipo-pendiente-en-real.md`.
"""

from __future__ import annotations

import os
import select
import threading
from typing import Any, Callable, Mapping

from common import APP_NAME, dbus
from ui import atajos

ESPERA_ARRANQUE = 5.0
"""Segundos que espera `arrancar()` a saber si hay conexión."""
ESPERA_BUCLE = 30.0             # sin nada que hacer, el hilo se despierta igual

KEY_PRESS, KEY_RELEASE = 2, 3   # X.h
BAD_ACCESS = 10                 # X.h: «BadAccess»
X_GRAB_KEY = 33                 # Xproto.h: el código de la petición GrabKey
GRAB_MODE_ASYNC = 1             # X.h


_MANEJADORES: dict[str, Any] = {}
"""Los manejadores de errores de Xlib, puestos una vez por proceso.

`XSetErrorHandler` y `XSetIOErrorHandler` valen para todo el proceso, no para
una conexión: cada error se apunta en la lista de la conexión de la que viene
(`_ERRORES`), y las referencias se guardan aquí porque ctypes no las mantiene
vivas por su cuenta.
"""
_ERRORES: dict[int, list[tuple[int, int]]] = {}
"""Los errores de X de cada conexión abierta, por su puntero `Display`."""
_ROTAS: set[int] = set()
"""Las conexiones cuyo servidor se ha ido."""


def _manejadores(ctypes: Any, x: Any) -> None:
    """Pone, si no estaban, los manejadores de errores de Xlib de este proceso.

    Sin ellos Xlib termina el proceso: con un error del servidor (el
    `BadAccess` de una tecla que tiene otro) y cuando el servidor se va.
    """
    if _MANEJADORES:
        return

    class XErrorEvent(ctypes.Structure):
        """`XErrorEvent` de Xlib.h."""
        _fields_ = [("type", ctypes.c_int), ("display", ctypes.c_void_p),
                    ("resourceid", ctypes.c_ulong), ("serial", ctypes.c_ulong),
                    ("error_code", ctypes.c_ubyte), ("request_code", ctypes.c_ubyte),
                    ("minor_code", ctypes.c_ubyte)]

    def apuntar(dpy, error) -> int:
        """Apunta un error del servidor en su conexión en vez de terminar el proceso."""
        _ERRORES.setdefault(dpy or 0, []).append(
            (error.contents.error_code, error.contents.request_code))
        return 0

    def de_es(dpy) -> int:
        """El servidor se ha ido: se marca la conexión."""
        _ROTAS.add(dpy or 0)
        return 0

    _MANEJADORES["error"] = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p,
                                             ctypes.POINTER(XErrorEvent))(apuntar)
    _MANEJADORES["es"] = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)(de_es)
    _MANEJADORES["salida"] = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)(
        lambda dpy, _datos: _ROTAS.add(dpy or 0))
    x.XSetErrorHandler(_MANEJADORES["error"])
    x.XSetIOErrorHandler(_MANEJADORES["es"])


class Xlib:
    """Las llamadas a libX11 que hace el hilo de X11, por ctypes.

    Se crea y se usa en ese hilo y solo en él: Xlib no es seguro entre hilos
    sin `XInitThreads()`, y aquí no le hace falta.

    Raises:
        OSError: Si no hay `libX11.so.6` o no se puede abrir la pantalla.
    """

    def __init__(self) -> None:
        """Abre la pantalla de `DISPLAY` y pone los manejadores de errores."""
        import ctypes

        self.ct = ctypes
        x = ctypes.CDLL("libX11.so.6")
        self.x = x

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

        self.XKeyEvent = XKeyEvent
        self.evento = (ctypes.c_long * 24)()      # XEvent: una unión de 24 long
        x.XOpenDisplay.restype = ctypes.c_void_p
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XDefaultRootWindow.restype = ctypes.c_ulong
        x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x.XConnectionNumber.argtypes = [ctypes.c_void_p]
        x.XStringToKeysym.restype = ctypes.c_ulong
        x.XStringToKeysym.argtypes = [ctypes.c_char_p]
        x.XKeysymToKeycode.restype = ctypes.c_ubyte
        x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x.XGrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong,
                               ctypes.c_int, ctypes.c_int, ctypes.c_int]
        x.XUngrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong]
        x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x.XPending.argtypes = [ctypes.c_void_p]
        x.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        _manejadores(ctypes, x)
        self.dpy = x.XOpenDisplay(None)
        if not self.dpy:
            raise OSError(f"no se puede abrir la pantalla {os.environ.get('DISPLAY', '')!r}")
        self.errores = _ERRORES.setdefault(self.dpy, [])
        if hasattr(x, "XSetIOErrorExitHandler"):           # libX11 1.7
            x.XSetIOErrorExitHandler.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                 ctypes.c_void_p]
            x.XSetIOErrorExitHandler(self.dpy, _MANEJADORES["salida"], None)
        if hasattr(x, "XkbSetDetectableAutoRepeat"):
            x.XkbSetDetectableAutoRepeat.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                     ctypes.c_void_p]
            x.XkbSetDetectableAutoRepeat(self.dpy, 1, None)
        self.raiz = x.XDefaultRootWindow(self.dpy)

    @property
    def roto(self) -> bool:
        """Indica si el servidor se ha ido: la conexión ya no sirve."""
        return self.dpy is None or self.dpy in _ROTAS

    def fileno(self) -> int:
        """Devuelve el descriptor de la conexión, para `select`."""
        return int(self.x.XConnectionNumber(self.dpy))

    def vivo(self) -> bool:
        """Hace un viaje de ida y vuelta al servidor y dice si sigue ahí.

        Si se ha ido, `XSync` lo descubre por el camino que Xlib sabe
        recuperar (`_XReply`), y no dentro de otra llamada.
        """
        if self.roto:
            return False
        self.x.XSync(self.dpy, 0)
        return not self.roto

    def keycode(self, keysym: str) -> int:
        """Devuelve el código de la tecla con ese keysym en este teclado, o 0 si no la tiene."""
        sym = self.x.XStringToKeysym(keysym.encode("ascii"))
        return int(self.x.XKeysymToKeycode(self.dpy, sym)) if sym else 0

    def agarrar(self, keycode: int, mascara: int) -> int:
        """Agarra una tecla con esos modificadores en la ventana raíz.

        Returns:
            0 si se ha podido; si no, el código de error de X (`BAD_ACCESS`).
        """
        self.errores.clear()
        self.x.XGrabKey(self.dpy, keycode, mascara, self.raiz, 0, GRAB_MODE_ASYNC,
                        GRAB_MODE_ASYNC)
        self.x.XSync(self.dpy, 0)
        return next((codigo for codigo, peticion in self.errores if peticion == X_GRAB_KEY),
                    self.errores[0][0] if self.errores else 0)

    def soltar(self, keycode: int, mascara: int) -> None:
        """Suelta una tecla agarrada."""
        self.x.XUngrabKey(self.dpy, keycode, mascara, self.raiz)
        self.x.XSync(self.dpy, 0)

    def eventos(self) -> list[tuple[int, int, int]]:
        """Devuelve los eventos de teclado que han llegado, sin esperar.

        Returns:
            `(tipo, keycode, estado)` de cada `KeyPress` y `KeyRelease`.
        """
        salida = []
        while not self.roto and self.x.XPending(self.dpy) > 0:
            self.x.XNextEvent(self.dpy, self.ct.byref(self.evento))
            tecla = self.ct.cast(self.ct.byref(self.evento),
                                 self.ct.POINTER(self.XKeyEvent)).contents
            if tecla.type in (KEY_PRESS, KEY_RELEASE):
                salida.append((tecla.type, int(tecla.keycode), int(tecla.state)))
        return salida

    def cerrar(self) -> None:
        """Cierra la conexión con el servidor, si sigue."""
        if self.dpy and not self.roto:
            self.x.XCloseDisplay(self.dpy)
        _ERRORES.pop(self.dpy or 0, None)
        _ROTAS.discard(self.dpy or 0)
        self.dpy = None


def abrir_xlib() -> Any:
    """Abre la conexión con el servidor X de esta sesión.

    Punto de indirección: los tests ponen uno de mentira.

    Raises:
        OSError: Si no hay libX11 o no se puede abrir la pantalla.
    """
    return Xlib()


class _Hilo:
    """Lo que comparten los dos: el hilo, el pipe que lo despierta y lo pedido.

    Args:
        pulsado: `pulsado(accion)`, cuando se pulsa un atajo.
        puestos: `puestos(combos, rechazados)`, cuando acaba de poner lo pedido.

    Attributes:
        motivo: Por qué no hay atajos, si `arrancar()` ha dicho que no.
    """

    nombre = ""
    suspende = True

    def __init__(self, pulsado: Callable[[str], None],
                 puestos: Callable[[dict, dict], None]) -> None:
        """Prepara el hilo sin conectar todavía a nada."""
        self.pulsado = pulsado
        self.puestos = puestos
        self.motivo = ""
        self._pipe = os.pipe()
        os.set_blocking(self._pipe[1], False)
        self._cerrojo = threading.Lock()
        self._pendiente: dict | None = None
        self._salir = False
        self._hilo: threading.Thread | None = None
        self._listo = threading.Event()
        self._abierto = False
        self._acabado = False           # el hilo ha salido de `_correr()`
        self._huerfano = False          # `cerrar()` se cansó de esperarlo: el pipe lo cierra él
        self._pipe_cerrado = False

    def arrancar(self) -> bool:
        """Conecta en su hilo y devuelve si se pueden poner atajos."""
        self._hilo = threading.Thread(target=self._vivir, name=f"atajos-{self.nombre}",
                                      daemon=True)
        self._hilo.start()
        self._listo.wait(ESPERA_ARRANQUE)
        return self._abierto

    def poner(self, combos: Mapping[str, str]) -> None:
        """Pide que los atajos sean exactamente estos (por acción), sin esperar.

        La respuesta llega por `puestos()`.
        """
        with self._cerrojo:
            self._pendiente = dict(combos)
        self._despertar()

    def cerrar(self) -> None:
        """Pide al hilo que suelte los atajos y acabe, y espera a que se vaya.

        Ido el hilo, cierra el pipe que lo despertaba. Si no se va a tiempo
        (una llamada al bus que tarda, al entrar en la sesión), lo cierra el
        hilo al acabar: el agente vuelve a intentarlo más tarde con otro, y
        cada intento no puede dejar un pipe abierto.
        """
        self._salir = True
        self._despertar()
        if self._hilo is not None and self._hilo is not threading.current_thread():
            self._hilo.join(ESPERA_ARRANQUE)
        with self._cerrojo:
            if self._hilo is None or self._acabado:
                self._cerrar_pipe()
            else:
                self._huerfano = True

    def _vivir(self) -> None:
        """Es el hilo: `_correr()` y, si `cerrar()` ya no lo esperaba, cierra el pipe."""
        try:
            self._correr()
        finally:
            with self._cerrojo:
                self._acabado = True
                if self._huerfano:
                    self._cerrar_pipe()

    def _cerrar_pipe(self) -> None:
        """Cierra el pipe, una sola vez (con `_cerrojo` tomado)."""
        if self._pipe_cerrado:
            return
        self._pipe_cerrado = True
        for fd in self._pipe:
            try:
                os.close(fd)
            except OSError:
                pass

    def _despertar(self) -> None:
        """Despierta al hilo por el pipe."""
        try:
            os.write(self._pipe[1], b"!")
        except OSError:
            pass                # lleno: ya hay un despertar pendiente

    def _tomar(self) -> dict | None:
        """Devuelve lo pedido que falta por poner, y lo olvida."""
        with self._cerrojo:
            pendiente, self._pendiente = self._pendiente, None
        return pendiente

    def _vaciar_pipe(self) -> None:
        """Lee lo que haya en el pipe."""
        try:
            os.read(self._pipe[0], 4096)
        except OSError:
            pass

    def _correr(self) -> None:
        """Es el hilo: conecta, y atiende hasta que se cierra."""
        raise NotImplementedError


class X11(_Hilo):
    """Los atajos con `XGrabKey`, en un hilo con su conexión a X.

    Args:
        pulsado: `pulsado(accion)`, cuando se pulsa un atajo.
        puestos: `puestos(combos, rechazados)`, cuando acaba de poner lo pedido.
        abrir: Abre la conexión; por defecto, `abrir_xlib()`.
    """

    nombre = atajos.NOMBRE_MECANISMO[atajos.X11]
    suspende = True

    def __init__(self, pulsado: Callable[[str], None], puestos: Callable[[dict, dict], None],
                 abrir: Callable[[], Any] | None = None) -> None:
        """Prepara el hilo sin abrir todavía la pantalla."""
        super().__init__(pulsado, puestos)
        self._abrir = abrir or (lambda: abrir_xlib())
        self.xlib: Any = None
        self._agarradas: dict[tuple[int, int], str] = {}
        self._abajo: set[int] = set()

    def _correr(self) -> None:
        """Abre la pantalla y atiende sus eventos y lo pedido hasta que se cierra."""
        try:
            try:
                self.xlib = self._abrir()
                self._abierto = True
            except OSError as e:
                self.motivo = f"no se puede hablar con X: {e}"
                return
        finally:
            self._listo.set()
        try:
            while not self._salir and not self.xlib.roto:
                pendiente = self._tomar()
                if pendiente is not None:
                    self._poner(pendiente)
                for tipo, keycode, estado in self.xlib.eventos():
                    self._tecla(tipo, keycode, estado)
                try:
                    listos, _, _ = select.select([self.xlib, self._pipe[0]], [], [],
                                                 ESPERA_BUCLE)
                except (OSError, ValueError):
                    return
                if self._pipe[0] in listos:
                    self._vaciar_pipe()
        finally:
            self._soltar_todo()
            self.xlib.cerrar()

    def _soltar_todo(self) -> None:
        """Suelta todas las teclas agarradas."""
        for (keycode, mascara) in list(self._agarradas):
            for bloqueo in atajos.BLOQUEOS_X11:
                self.xlib.soltar(keycode, mascara | bloqueo)
        self._agarradas.clear()

    def _poner(self, combos: Mapping[str, str]) -> None:
        """Suelta lo agarrado, agarra lo pedido y dice qué no se ha podido.

        Antes de buscar las teclas se mira que el servidor siga ahí
        (`Xlib.vivo()`): buscar una puede pedirle a X el mapa del teclado, y si
        el servidor se va justo en ese viaje, libX11 no siempre se recupera.
        Solo pasa al cambiar los atajos, nunca mientras se esperan.
        """
        if not self.xlib.vivo():
            self.puestos(dict(combos), {a: atajos.SIN_RESPUESTA for a, c in combos.items() if c})
            return
        self._soltar_todo()
        rechazados: dict[str, str] = {}
        for accion in atajos.ACCIONES:
            combo = combos.get(accion)
            if not combo:
                continue
            try:
                mascara, keysym = atajos.x11(combo)
            except ValueError:
                rechazados[accion] = "no se entiende"
                continue
            keycode = self.xlib.keycode(keysym)
            if not keycode:
                rechazados[accion] = atajos.SIN_ESA_TECLA
                continue
            hechas: list[int] = []
            for bloqueo in atajos.BLOQUEOS_X11:
                if self.xlib.agarrar(keycode, mascara | bloqueo):
                    break
                hechas.append(bloqueo)
            if len(hechas) < len(atajos.BLOQUEOS_X11):
                for bloqueo in hechas:
                    self.xlib.soltar(keycode, mascara | bloqueo)
                rechazados[accion] = atajos.YA_LA_USA
            else:
                self._agarradas[(keycode, mascara)] = accion
        self.puestos(dict(combos), rechazados)

    def _tecla(self, tipo: int, keycode: int, estado: int) -> None:
        """Hace lo que toca con un evento de teclado agarrado."""
        if tipo == KEY_RELEASE:
            self._abajo.discard(keycode)
            return
        if keycode in self._abajo:
            return                      # la repetición de una tecla que sigue abajo
        accion = self._agarradas.get((keycode, atajos.de_x11(estado)))
        if accion is not None:
            self._abajo.add(keycode)
            self.pulsado(accion)


PORTAL_DESTINO = "org.freedesktop.portal.Desktop"
PORTAL_RUTA = "/org/freedesktop/portal/desktop"
ATAJOS_PORTAL = "org.freedesktop.portal.GlobalShortcuts"
"""La interfaz de los atajos globales del portal."""
PETICION = "org.freedesktop.portal.Request"
SESION = "org.freedesktop.portal.Session"
REGISTRO = "org.freedesktop.host.portal.Registry"
"""Donde un programa que no va en un sandbox dice su nombre al portal."""
REGLA_RESPUESTA = f"type='signal',interface='{PETICION}',member='Response'"
REGLA_PULSADO = f"type='signal',interface='{ATAJOS_PORTAL}',member='Activated'"
RESPUESTA_CANCELADA = 1         # «the user cancelled the interaction»
V = dbus.Variante


class Portal(_Hilo):
    """Los atajos con el portal GlobalShortcuts, en un hilo con su conexión al bus de sesión.

    Args:
        pulsado: `pulsado(accion)`, cuando se pulsa un atajo.
        puestos: `puestos(combos, rechazados)`, cuando acaba de poner lo pedido.
        conectar: Abre el bus de sesión; por defecto, `dbus.Conexion.sesion`.
    """

    nombre = atajos.NOMBRE_MECANISMO[atajos.PORTAL]
    # Los atajos del portal los recibe el compositor: soltarlos mientras se
    # graba obligaría a confirmarlos otra vez en su ventana al volver a ponerlos.
    suspende = False

    def __init__(self, pulsado: Callable[[str], None], puestos: Callable[[dict, dict], None],
                 conectar: Callable[[], dbus.Conexion] | None = None) -> None:
        """Prepara el hilo sin conectar todavía al bus."""
        super().__init__(pulsado, puestos)
        self._conectar = conectar or dbus.Conexion.sesion
        self.bus: dbus.Conexion | None = None
        self._sesion = ""
        self._vez = 0
        self._espera: tuple[str, str, dict] | None = None   # (paso, ruta, combos)

    def _correr(self) -> None:
        """Conecta, mira que haya portal y atiende lo pedido y sus señales."""
        try:
            try:
                self.bus = self._conectar()
                try:
                    self.bus.llamar(PORTAL_DESTINO, PORTAL_RUTA, dbus.PROPIEDADES, "Get",
                                    "ss", [ATAJOS_PORTAL, "version"])
                except dbus.Error:
                    self.motivo = atajos.SIN_PORTAL
                    self.bus.cerrar()
                    return
                try:
                    self.bus.llamar(PORTAL_DESTINO, PORTAL_RUTA, REGISTRO, "Register",
                                    "sa{sv}", [APP_NAME, {}])
                except dbus.Error:
                    pass                # un portal anterior al registro: sigue igual
                self.bus.escuchar(REGLA_RESPUESTA)
                self.bus.escuchar(REGLA_PULSADO)
                self._abierto = True
            except (dbus.Error, OSError) as e:
                self.motivo = f"no hay bus de sesión ({e})"
                return
        finally:
            self._listo.set()
        try:
            self._bucle()
        finally:
            self._cerrar_sesion()
            self.bus.cerrar()

    def _turno(self) -> bool:
        """Atiende las señales que ya han llegado y lo pedido, sin esperar.

        Lo pedido entra aunque se esté esperando la respuesta a lo anterior
        (`_abandonar()`): esa respuesta puede no llegar nunca.

        Returns:
            Si ha hecho algo. Una llamada al portal puede traer con su
            respuesta la señal que la sigue, y esa ya no despierta al `select`:
            hay que volver a mirar hasta que no quede nada.
        """
        hecho = False
        for s in self.bus.atender(0):
            self._senal(s)
            hecho = True
        pendiente = self._tomar()
        if pendiente is not None:
            self._abandonar()
            self._poner(pendiente)
            hecho = True
        return hecho

    def _abandonar(self) -> None:
        """Deja la petición al portal que espera su respuesta, si hay una.

        Su `Response` puede no llegar nunca (la ventana del escritorio se quedó
        abierta, el portal se reinició), y lo que se pide después no puede
        esperarla: se cierra (`Request.Close`, que quita su ventana y hace que
        no se mande la respuesta) y, si llegara, ya no es de nadie. No se le
        contesta al agente: lo pidió hace más de su plazo, porque pide una
        cosa a la vez, y lo nuevo puede ser lo mismo.
        """
        if self._espera is None:
            return
        _paso, ruta, _combos = self._espera
        self._espera = None
        try:
            self.bus.llamar(PORTAL_DESTINO, ruta, PETICION, "Close")
        except (dbus.Error, OSError):
            pass

    def _bucle(self) -> None:
        """Atiende el bus y lo pedido hasta que se cierra o se va el bus."""
        while not self._salir:
            try:
                while self._turno() and not self._salir:
                    pass
            except (dbus.Error, OSError):
                return
            try:
                listos, _, _ = select.select([self.bus, self._pipe[0]], [], [], ESPERA_BUCLE)
            except (OSError, ValueError):
                return
            if self._pipe[0] in listos:
                self._vaciar_pipe()

    def _ficha(self) -> str:
        """Devuelve una ficha nueva para el `handle_token` de una petición."""
        self._vez += 1
        return f"{APP_NAME}{os.getpid()}_{self._vez}"

    def _cerrar_sesion(self) -> None:
        """Cierra la sesión del portal, si hay una: sus atajos dejan de valer."""
        if self._sesion and self.bus is not None:
            try:
                self.bus.llamar(PORTAL_DESTINO, self._sesion, SESION, "Close")
            except (dbus.Error, OSError):
                pass
        self._sesion = ""

    def _poner(self, combos: Mapping[str, str]) -> None:
        """Cierra la sesión de antes y, si se pide alguno, abre otra para atarlos."""
        self._cerrar_sesion()
        combos = {a: c for a, c in combos.items() if c}
        if not combos:
            self.puestos({}, {})
            return
        ficha = self._ficha()
        try:
            ruta = self.bus.llamar(PORTAL_DESTINO, PORTAL_RUTA, ATAJOS_PORTAL, "CreateSession",
                                   "a{sv}", [{"handle_token": ficha,
                                              "session_handle_token": ficha}])[0]
        except dbus.Error:
            self.puestos(combos, {a: atajos.RECHAZADA_PORTAL for a in combos})
            return
        self._espera = ("crear", ruta, combos)

    def _atar(self, combos: dict) -> None:
        """Pide al portal los atajos de la sesión abierta.

        Si el portal da un error en vez de su `Request`, se dan por no puestos
        en el acto: nadie va a mandar la respuesta.
        """
        lista = []
        for accion in atajos.ACCIONES:
            if accion not in combos:
                continue
            datos = {"description": V("s", f"{APP_NAME}: {atajos.NOMBRES[accion]}")}
            try:
                datos["preferred_trigger"] = V("s", atajos.portal(combos[accion]))
            except ValueError:
                pass
            lista.append((accion, datos))
        try:
            ruta = self.bus.llamar(PORTAL_DESTINO, PORTAL_RUTA, ATAJOS_PORTAL, "BindShortcuts",
                                   "oa(sa{sv})sa{sv}",
                                   [self._sesion, lista, "", {"handle_token": self._ficha()}])[0]
        except dbus.Error:
            self.puestos(combos, {a: atajos.RECHAZADA_PORTAL for a in combos})
            return
        self._espera = ("atar", ruta, combos)

    def _senal(self, s: dbus.Mensaje) -> None:
        """Hace lo que toca con una respuesta del portal o un atajo pulsado."""
        if s.miembro == "Activated" and s.interfaz == ATAJOS_PORTAL:
            if len(s.cuerpo) >= 2 and s.cuerpo[0] == self._sesion \
                    and s.cuerpo[1] in atajos.ACCIONES:
                self.pulsado(s.cuerpo[1])
            return
        if s.miembro != "Response" or self._espera is None or s.ruta != self._espera[1]:
            return
        paso, _ruta, combos = self._espera
        self._espera = None
        codigo = s.cuerpo[0] if s.cuerpo else 2
        resultados = s.cuerpo[1] if len(s.cuerpo) > 1 and isinstance(s.cuerpo[1], dict) else {}
        if codigo != 0:
            motivo = atajos.CANCELADA_PORTAL if codigo == RESPUESTA_CANCELADA \
                else atajos.RECHAZADA_PORTAL
            self.puestos(combos, {a: motivo for a in combos})
            return
        if paso == "crear":
            self._sesion = str(resultados.get("session_handle") or "")
            if not self._sesion:
                self.puestos(combos, {a: atajos.RECHAZADA_PORTAL for a in combos})
                return
            self._atar(combos)
            return
        atados = {str(par[0]) for par in resultados.get("shortcuts") or []
                  if isinstance(par, (tuple, list)) and par}
        self.puestos(combos, {a: atajos.RECHAZADA_PORTAL for a in combos if a not in atados})


def poner(mecanismo: str, pulsado: Callable[[str], None],
          puestos: Callable[[dict, dict], None]) -> _Hilo:
    """Crea los atajos de ese mecanismo (`atajos.X11` o `atajos.PORTAL`), sin arrancarlos."""
    return Portal(pulsado, puestos) if mecanismo == atajos.PORTAL else X11(pulsado, puestos)
