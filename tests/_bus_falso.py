#!/usr/bin/env python3
"""
_bus_falso.py — Un bus de sesión de mentira que también pregunta.

El otro lado de un `socketpair`: saluda como dice la *D-Bus Specification*,
contesta lo que contesta el propio bus (`Hello`, `RequestName`, `AddMatch`,
`NameHasOwner`), hace de `StatusNotifierWatcher` si se le dice, apunta lo que
recibe (llamadas y señales) y puede LLAMAR al cliente como lo haría el
anfitrión de la bandeja (`llamar()`), esperando su respuesta. Lo que no sabe
contestar se lo pasa a `responder(mensaje)`, que devuelve ("ok", firma, cuerpo),
("error", nombre, texto) o None (no contesta).
"""

from __future__ import annotations

import socket
import threading

from common import dbus

CLIENTE = ":1.42"
ANFITRION = ":1.7"


class BusFalso(threading.Thread):
    def __init__(self, sock, responder=None, dueños=()):
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

    # --- lo que hace el test ---------------------------------------------------------

    def mandar(self, tipo, campos, firma="", cuerpo=()):
        with self._cerrojo:
            self.serie += 1
            serie = self.serie
            if firma:
                campos = {**campos, dbus.SIGNATURE: firma}
            self.sock.sendall(dbus.Mensaje(tipo, serie, 0, campos, list(cuerpo)).a_bytes())
        return serie

    def llamar(self, ruta, interfaz, miembro, firma="", cuerpo=(), espera=5.0,
               flags=0, destino=CLIENTE):
        """Llama al cliente como lo haría otro programa del bus. Devuelve
        ("ok", cuerpo) o ("error", nombre, texto); None si no contesta."""
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
        return [s for s in list(self.senales) if s.miembro == miembro]

    # --- el bus -------------------------------------------------------------------------

    def _linea(self, pendiente: bytes) -> tuple[bytes, bytes]:
        while b"\r\n" not in pendiente:
            trozo = self.sock.recv(4096)
            if not trozo:
                raise EOFError
            pendiente += trozo
        linea, _, resto = pendiente.partition(b"\r\n")
        return linea, resto

    def _contestar(self, m, firma="", cuerpo=()):
        self.mandar(dbus.METHOD_RETURN, {dbus.REPLY_SERIAL: m.serie}, firma, cuerpo)

    def run(self):
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
    """(conexión del cliente, bus falso ya en marcha)."""
    uno, otro = socket.socketpair()
    bus = BusFalso(otro, responder, dueños)
    bus.start()
    uno.settimeout(5)
    return dbus.Conexion(uno, uid=1000), bus
