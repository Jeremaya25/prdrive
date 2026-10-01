#!/usr/bin/env python3
"""Un bus de sesión de mentira que también pregunta.

El otro lado de un `socketpair`: saluda como dice la *D-Bus Specification*,
contesta lo que contesta el propio bus (`Hello`, `RequestName`, `AddMatch`,
`NameHasOwner`), hace de `StatusNotifierWatcher` si se le dice, apunta lo que
recibe (llamadas y señales) y puede LLAMAR al cliente como lo haría el
anfitrión de la bandeja (`llamar()`), esperando su respuesta. Lo que no sabe
contestar se lo pasa a `responder(mensaje)`, que devuelve `("ok", firma,
cuerpo)`, `("error", nombre, texto)` o `None` (no contesta).
"""

from __future__ import annotations

import socket
import threading

from common import dbus

CLIENTE = ":1.42"
"""Nombre único que el bus le da al cliente."""
ANFITRION = ":1.7"
"""Nombre único del anfitrión de la bandeja, el que llama al cliente."""


class BusFalso(threading.Thread):
    """El bus de mentira: un hilo que lee al cliente y le contesta.

    Attributes:
        sock: El socket del lado del bus.
        responder: Lo que contesta a lo que el bus no sabe.
        dueños: Los nombres con dueño en el bus.
        recibidos: Las llamadas que ha recibido el bus.
        senales: Las señales que ha recibido.
        registrados: Los items registrados en el `StatusNotifierWatcher`.
        anfitrion: Si hay un anfitrión de bandeja registrado.
        serie: El último número de serie que ha usado.
        cerrado: Se activa cuando acaba el hilo.
    """
    def __init__(self, sock, responder=None, dueños=()):
        """Prepara el bus sobre `sock`.

        Args:
            sock: El socket del lado del bus.
            responder: Lo que contesta a lo que el bus no sabe: `fn(mensaje)`.
            dueños: Los nombres que ya tienen dueño.
        """
        super().__init__(daemon=True)
        self.sock = sock
        self.responder = responder or (lambda m: None)
        self.dueños = set(dueños)
        self.recibidos: list[dbus.Mensaje] = []
        self.senales: list[dbus.Mensaje] = []
        self.registrados: list[str] = []
        self.anfitrion = True
        self.serie = 100
        self._esperando: dict[int, list] = {}
        self._cerrojo = threading.Lock()
        self.cerrado = threading.Event()

    def mandar(self, tipo, campos, firma="", cuerpo=()):
        """Manda un mensaje al cliente y devuelve su número de serie."""
        with self._cerrojo:
            self.serie += 1
            serie = self.serie
            if firma:
                campos = {**campos, dbus.SIGNATURE: firma}
            self.sock.sendall(dbus.Mensaje(tipo, serie, 0, campos, list(cuerpo)).a_bytes())
        return serie

    def llamar(self, ruta, interfaz, miembro, firma="", cuerpo=(), espera=5.0,
               flags=0, destino=CLIENTE):
        """Llama al cliente como lo haría otro programa del bus.

        Returns:
            `("ok", cuerpo)` o `("error", nombre, texto)`; `None` si no
            contesta.
        """
        hecho = threading.Event()
        caja: list = [hecho, None]
        campos = {dbus.PATH: ruta, dbus.MEMBER: miembro, dbus.SENDER: ANFITRION,
                  dbus.DESTINATION: destino}
        if interfaz:
            campos[dbus.INTERFACE] = interfaz
        with self._cerrojo:
            self.serie += 1
            serie = self.serie
            self._esperando[serie] = caja
            if firma:
                campos[dbus.SIGNATURE] = firma
            self.sock.sendall(dbus.Mensaje(dbus.METHOD_CALL, serie, flags, campos,
                                           list(cuerpo)).a_bytes())
        hecho.wait(espera)
        return caja[1]

    def senal(self, ruta, interfaz, miembro, firma="", cuerpo=(), remitente=dbus.BUS):
        """Manda una señal al cliente."""
        self.mandar(dbus.SIGNAL, {dbus.PATH: ruta, dbus.INTERFACE: interfaz,
                                  dbus.MEMBER: miembro, dbus.SENDER: remitente},
                    firma, cuerpo)

    def dueño(self, nombre, nuevo):
        """El bus anuncia que `nombre` ha cambiado de dueño (vacío: se ha ido)."""
        viejo = ":1.9" if nombre in self.dueños else ""
        if nuevo:
            self.dueños.add(nombre)
        else:
            self.dueños.discard(nombre)
        self.senal(dbus.RUTA_BUS, dbus.BUS, "NameOwnerChanged", "sss",
                   [nombre, viejo, nuevo])

    def emitidas(self, miembro):
        """Devuelve las señales recibidas con ese miembro."""
        return [s for s in list(self.senales) if s.miembro == miembro]

    def _linea(self, pendiente: bytes) -> tuple[bytes, bytes]:
        """Lee del socket una línea del saludo.

        Returns:
            La línea y lo que sobra.
        """
        while b"\r\n" not in pendiente:
            trozo = self.sock.recv(4096)
            if not trozo:
                raise EOFError
            pendiente += trozo
        linea, _, resto = pendiente.partition(b"\r\n")
        return linea, resto

    def _contestar(self, m, firma="", cuerpo=()):
        """Contesta a `m` con un `METHOD_RETURN`."""
        self.mandar(dbus.METHOD_RETURN, {dbus.REPLY_SERIAL: m.serie}, firma, cuerpo)

    def run(self):
        """Hace el saludo y atiende los mensajes del cliente hasta que cierra."""
        try:
            self.sock.recv(1)
            _linea, pendiente = self._linea(b"")
            self.sock.sendall(b"OK 0123456789abcdef\r\n")
            _linea, pendiente = self._linea(pendiente)
            while True:
                while dbus.longitud(pendiente) is None or \
                        len(pendiente) < dbus.longitud(pendiente):
                    trozo = self.sock.recv(65536)
                    if not trozo:
                        return
                    pendiente += trozo
                n = dbus.longitud(pendiente)
                m, pendiente = dbus.leer_mensaje(pendiente[:n]), pendiente[n:]
                self._uno(m)
        except (OSError, EOFError):
            return
        finally:
            self.cerrado.set()

    def _uno(self, m):
        """Atiende un mensaje: lo apunta y contesta lo que contesta un bus."""
        if m.tipo in (dbus.METHOD_RETURN, dbus.ERROR):
            caja = self._esperando.pop(m.campos.get(dbus.REPLY_SERIAL), None)
            if caja is not None:
                caja[1] = (("ok", m.cuerpo) if m.tipo == dbus.METHOD_RETURN else
                           ("error", m.campos.get(dbus.ERROR_NAME),
                            m.cuerpo[0] if m.cuerpo else ""))
                caja[0].set()
            return
        if m.tipo == dbus.SIGNAL:
            self.senales.append(m)
            return
        self.recibidos.append(m)
        if m.miembro == "Hello":
            self._contestar(m, "s", [CLIENTE])
        elif m.miembro in ("AddMatch", "RemoveMatch"):
            self._contestar(m)
        elif m.miembro == "RequestName":
            self.dueños.add(m.cuerpo[0])
            self._contestar(m, "u", [dbus.NOMBRE_PRINCIPAL])
        elif m.miembro == "NameHasOwner":
            self._contestar(m, "b", [m.cuerpo[0] in self.dueños])
        elif m.miembro == "RegisterStatusNotifierItem" and \
                "org.kde.StatusNotifierWatcher" in self.dueños:
            self.registrados.append(m.cuerpo[0])
            self._contestar(m)
        elif m.miembro == "Get" and m.cuerpo[1:] == ["IsStatusNotifierHostRegistered"]:
            self._contestar(m, "v", [dbus.Variante("b", self.anfitrion)])
        else:
            r = self.responder(m)
            if r is None:
                return
            if r[0] == "ok":
                self._contestar(m, r[1], r[2])
            else:
                self.mandar(dbus.ERROR, {dbus.REPLY_SERIAL: m.serie, dbus.ERROR_NAME: r[1]},
                            "s", [r[2]])


def conectar(responder=None, dueños=()):
    """Devuelve `(conexión del cliente, bus falso ya en marcha)`."""
    uno, otro = socket.socketpair()
    bus = BusFalso(otro, responder, dueños)
    bus.start()
    uno.settimeout(5)
    return dbus.Conexion(uno, uid=1000), bus
