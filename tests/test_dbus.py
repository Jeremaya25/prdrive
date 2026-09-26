#!/usr/bin/env python3
"""
El cliente de D-Bus (`common/dbus.py`), los avisos (`common/avisos.py`) y las
sondas de la moderación (`common/moderacion.py`).

Nada de esto habla con un bus de verdad: el bus es falso, un hilo al otro lado
de un `socketpair` (o de un socket en un temporal, para lo que abre el bus por
su dirección) que saluda como dice la especificación y contesta lo que el test
le manda. La serialización se compara con bytes calculados a mano con las
reglas de la *D-Bus Specification* y con el `Hello` canónico que cualquier
cliente manda al conectarse.
"""

import os
import socket
import threading
import time
from pathlib import Path

from _harness import Checks, tmpdir

from common import avisos, dbus, moderacion

c = Checks("D-Bus, avisos y moderación")


# --- serialización ---------------------------------------------------------------

def b(firma, *valores) -> bytes:
    return bytes(dbus.Escritor().escribir(firma, valores).buf)


c("u: little-endian", b("u", 0x12345678), bytes.fromhex("78563412"))
c("s: longitud, bytes y nulo", b("s", "foo"), bytes.fromhex("03000000") + b"foo\0")
c("g: longitud de un byte", b("g", "sv"), b"\x02sv\0")
c("b: un booleano ocupa cuatro bytes", b("b", True), bytes.fromhex("01000000"))
c("y seguido de u: relleno hasta 4", b("yu", 1, 2), bytes.fromhex("01000000 02000000"))
c("x: alineado a 8 detrás de un byte", b("yx", 7, -1),
  bytes.fromhex("07000000 00000000 ffffffff ffffffff"))
c("a{sv}: longitud sin el relleno, entradas alineadas a 8",
  b("a{sv}", {"a": dbus.Variante("i", 1)}),
  bytes.fromhex("10000000 00000000 01000000 6100 016900 000000 01000000"))
c("array vacío de estructuras: el relleno va igual",
  b("a(ii)", []), bytes.fromhex("00000000 00000000"))
c("(iiay): el IconPixmap de la bandeja",
  b("(iiay)", (1, 2, b"\xff\x00")),
  bytes.fromhex("01000000 02000000 02000000 ff00"))
c("ay: bytes tal cual", b("ay", b"abc"), bytes.fromhex("03000000") + b"abc")

HELLO = (b"l\x01\x00\x01\x00\x00\x00\x00\x01\x00\x00\x00m\x00\x00\x00"
         b"\x01\x01o\x00\x15\x00\x00\x00/org/freedesktop/DBus\x00\x00\x00"
         b"\x02\x01s\x00\x14\x00\x00\x00org.freedesktop.DBus\x00\x00\x00\x00"
         b"\x03\x01s\x00\x05\x00\x00\x00Hello\x00\x00\x00"
         b"\x06\x01s\x00\x14\x00\x00\x00org.freedesktop.DBus\x00\x00\x00\x00")
hello = dbus.Mensaje(dbus.METHOD_CALL, 1, 0,
                     {dbus.PATH: dbus.RUTA_BUS, dbus.INTERFACE: dbus.BUS,
                      dbus.MEMBER: "Hello", dbus.DESTINATION: dbus.BUS})
c("el Hello, byte a byte como el canónico", hello.a_bytes(), HELLO)
c("y su longitud se sabe por la cabecera", dbus.longitud(HELLO), len(HELLO))
c("con menos de 16 bytes todavía no", dbus.longitud(HELLO[:15]), None)
leido = dbus.leer_mensaje(HELLO)
c("y se lee de vuelta", (leido.tipo, leido.serie, leido.miembro, leido.ruta),
  (dbus.METHOD_CALL, 1, "Hello", dbus.RUTA_BUS))

firma = "a{sv}(iiay)asbdvx"
valores = [{"k": dbus.Variante("as", ["x", "y"]), "n": dbus.Variante("u", 7)},
           (3, -4, b"\x01\x02\x03"), ["uno", "dos"], False, 2.5,
           dbus.Variante("(si)", ("t", 9)), -(2 ** 40)]
m = dbus.Mensaje(dbus.METHOD_RETURN, 5, 0, {dbus.SIGNATURE: firma,
                                           dbus.REPLY_SERIAL: 4}, valores)
vuelta = dbus.leer_mensaje(m.a_bytes())
c("ida y vuelta de una firma retorcida (las variantes llegan desenvueltas)",
  vuelta.cuerpo, [{"k": ["x", "y"], "n": 7}, (3, -4, b"\x01\x02\x03"),
                  ["uno", "dos"], False, 2.5, ("t", 9), -(2 ** 40)])
c("partir una firma en tipos completos", dbus.partir("sa{sv}(ia(ii))v"),
  ["s", "a{sv}", "(ia(ii))", "v"])
try:
    dbus.partir("a{sv")
    c("una firma sin cerrar se rechaza", False, True)
except dbus.Error:
    c("una firma sin cerrar se rechaza", True, True)
big = dbus.Mensaje(dbus.METHOD_RETURN, 1, 0, {dbus.SIGNATURE: "s", dbus.REPLY_SERIAL: 1},
                   ["x"]).a_bytes()
big_endian = b"B" + big[1:4] + big[4:8][::-1] + big[8:12][::-1] + big[12:16][::-1]
try:
    dbus.longitud(b"X" + big[1:])
    c("un orden de bytes desconocido se rechaza", False, True)
except dbus.Error:
    c("un orden de bytes desconocido se rechaza", True, True)
c("un mensaje big-endian dice su longitud igual", dbus.longitud(big_endian), len(big))

c("dirección: path con %XX, abstract y lo que no es unix",
  dbus.destinos("unix:path=/run/user/1000/bu%73,guid=x;unix:abstract=/tmp/y;tcp:host=a"),
  ["/run/user/1000/bus", b"\0/tmp/y"])


# --- un bus falso ------------------------------------------------------------------

class BusFalso(threading.Thread):
    """El otro lado del socket: saluda, apunta lo que recibe y contesta con
    `responder(mensaje)` → ("ok", firma, cuerpo) | ("error", nombre, texto) |
    ("señal", Mensaje, luego) | None."""

    def __init__(self, sock, responder=None):
        super().__init__(daemon=True)
        self.sock = sock
        self.responder = responder or (lambda m: None)
        self.auth: list[bytes] = []
        self.recibidos: list[dbus.Mensaje] = []
        self.serie = 100

    def _linea(self, pendiente: bytes) -> tuple[bytes, bytes]:
        while b"\r\n" not in pendiente:
            trozo = self.sock.recv(4096)
            if not trozo:
                raise EOFError
            pendiente += trozo
        linea, _, resto = pendiente.partition(b"\r\n")
        return linea, resto

    def mandar(self, tipo, campos, firma="", cuerpo=()):
        self.serie += 1
        if firma:
            campos = {**campos, dbus.SIGNATURE: firma}
        self.sock.sendall(dbus.Mensaje(tipo, self.serie, 0, campos, list(cuerpo)).a_bytes())

    def run(self):
        try:
            nulo = self.sock.recv(1)
            self.auth.append(nulo)
            linea, pendiente = self._linea(b"")
            self.auth.append(linea)
            self.sock.sendall(b"OK 0123456789abcdef\r\n")
            linea, pendiente = self._linea(pendiente)
            self.auth.append(linea)
            while True:
                while dbus.longitud(pendiente) is None or len(pendiente) < dbus.longitud(pendiente):
                    trozo = self.sock.recv(65536)
                    if not trozo:
                        return
                    pendiente += trozo
                n = dbus.longitud(pendiente)
                m, pendiente = dbus.leer_mensaje(pendiente[:n]), pendiente[n:]
                self.recibidos.append(m)
                if m.miembro == "Hello":
                    self.mandar(dbus.METHOD_RETURN, {dbus.REPLY_SERIAL: m.serie}, "s",
                                [":1.42"])
                    continue
                if m.miembro == "AddMatch":
                    self.mandar(dbus.METHOD_RETURN, {dbus.REPLY_SERIAL: m.serie})
                    continue
                r = self.responder(m)
                if r is None:
                    continue
                if r[0] == "señal":
                    self.mandar(dbus.SIGNAL, {dbus.PATH: "/x", dbus.INTERFACE: "a.b",
                                              dbus.MEMBER: r[1]}, "s", ["hola"])
                    r = r[2]
                if r[0] == "ok":
                    self.mandar(dbus.METHOD_RETURN, {dbus.REPLY_SERIAL: m.serie}, r[1], r[2])
                elif r[0] == "error":
                    self.mandar(dbus.ERROR, {dbus.REPLY_SERIAL: m.serie,
                                             dbus.ERROR_NAME: r[1]}, "s", [r[2]])
        except (OSError, EOFError):
            return


def conectar(responder=None):
    uno, otro = socket.socketpair()
    bus = BusFalso(otro, responder)
    bus.start()
    uno.settimeout(5)
    return dbus.Conexion(uno, uid=1000), bus


def responder(m):
    if m.miembro == "Suma":
        return ("ok", "i", [sum(m.cuerpo)])
    if m.miembro == "Rompe":
        return ("error", "org.ejemplo.Error.Roto", "se ha roto")
    if m.miembro == "ConSenal":
        return ("señal", "Aviso", ("ok", "s", ["hecho"]))
    if m.miembro == "Get":
        return ("ok", "v", [dbus.Variante("u", 3)])
    return None


con, bus = conectar(responder)
c("el saludo empieza con un byte nulo", bus.auth[0], b"\0")
c("AUTH EXTERNAL con el uid en decimal escrito en hexadecimal",
  bus.auth[1], b"AUTH EXTERNAL " + b"1000".hex().encode())
c("y cierra con BEGIN", bus.auth[2], b"BEGIN")
c("el guid del OK queda apuntado", con.guid, "0123456789abcdef")
c("Hello primero, y el nombre único es el que da el bus", con.nombre, ":1.42")
c("una llamada con su respuesta",
  con.llamar("org.ejemplo", "/e", "org.ejemplo.I", "Suma", "ii", [2, 3]), [5])
llamada = bus.recibidos[-1]
c("  que lleva destino, ruta, interfaz y firma",
  (llamada.campos.get(dbus.DESTINATION), llamada.ruta, llamada.interfaz, llamada.firma),
  ("org.ejemplo", "/e", "org.ejemplo.I", "ii"))
try:
    con.llamar("org.ejemplo", "/e", "org.ejemplo.I", "Rompe")
    c("un error del otro lado se lanza como dbus.Error", False, True)
except dbus.Error as e:
    c("un error del otro lado se lanza como dbus.Error", (e.nombre, e.mensaje),
      ("org.ejemplo.Error.Roto", "se ha roto"))
c("una señal que llega antes de la respuesta no se pierde",
  con.llamar("org.ejemplo", "/e", "org.ejemplo.I", "ConSenal"), ["hecho"])
s = con.senal()
c("  y se recoge después", (s.miembro, s.cuerpo) if s else None, ("Aviso", ["hola"]))
c("no hay más señales", con.senal(0.05), None)
c("una propiedad llega desenvuelta", con.propiedad("org.x", "/x", "org.x", "P"), 3)
g = bus.recibidos[-1]
c("  por Properties.Get(ss)", (g.interfaz, g.miembro, g.cuerpo),
  (dbus.PROPIEDADES, "Get", ["org.x", "P"]))
try:
    con.llamar("org.ejemplo", "/e", "org.ejemplo.I", "Calla", espera=0.2)
    c("quien no contesta da NoReply", False, True)
except dbus.Error as e:
    c("quien no contesta da NoReply", e.nombre, "org.freedesktop.DBus.Error.NoReply")
con.escuchar("type='signal'")
c("escuchar es un AddMatch con la regla",
  (bus.recibidos[-1].miembro, bus.recibidos[-1].cuerpo), ("AddMatch", ["type='signal'"]))
con.cerrar()


# --- la mitad que contesta ------------------------------------------------------------
import _bus_falso as B  # noqa: E402


def rompe():
    raise ValueError("adrede")


con, bus = B.conectar()
con.exportar("/e/uno", dbus.Interfaz("org.ejemplo.I", metodos={
    "Suma": dbus.Metodo("ii", "i", lambda a, b: [a + b]),
    "Rompe": dbus.Metodo("", "", rompe),
    "Quien": dbus.Metodo("", "s", lambda: ["yo"])}, propiedades={
    "N": ("u", lambda: 7)}))
hilo = threading.Thread(target=lambda: [con.atender(0.05) for _ in range(40)], daemon=True)
hilo.start()
c("una llamada a un método exportado se contesta",
  bus.llamar("/e/uno", "org.ejemplo.I", "Suma", "ii", [2, 3]), ("ok", [5]))
c("  sin interfaz, por el nombre del método (es opcional)",
  bus.llamar("/e/uno", None, "Quien"), ("ok", ["yo"]))
c("  un fallo de quien la atiende es Failed, no una excepción",
  bus.llamar("/e/uno", "org.ejemplo.I", "Rompe")[:2], ("error", dbus.E_FALLO))
c("  una interfaz que no está, UnknownInterface",
  bus.llamar("/e/uno", "org.otra", "Suma", "ii", [1, 1])[:2], ("error", dbus.E_INTERFAZ))
c("GetAll de una interfaz sin propiedades: vacío, no error",
  bus.llamar("/e/uno", dbus.PROPIEDADES, "GetAll", "s", ["org.otra"]), ("ok", [{}]))
c("  Get de una que no existe, UnknownProperty",
  bus.llamar("/e/uno", dbus.PROPIEDADES, "Get", "ss", ["org.ejemplo.I", "X"])[:2],
  ("error", dbus.E_PROPIEDAD))
c("  Introspect de /e: el nodo hijo",
  '<node name="uno"/>' in bus.llamar("/e", dbus.INTROSPECCION, "Introspect")[1][0], True)
c("con NO_REPLY_EXPECTED no se contesta",
  bus.llamar("/e/uno", "org.ejemplo.I", "Suma", "ii", [1, 1], espera=0.3,
             flags=dbus.NO_REPLY_EXPECTED), None)
hilo.join()


def reentrante(m):
    # Como un watcher que, antes de contestar, le pregunta algo al que llama.
    if m.miembro == "Registra":
        bus.mandar_despues = bus.llamar("/e/uno", dbus.PROPIEDADES, "Get", "ss",
                                        ["org.ejemplo.I", "N"])
        return ("ok", "", [])
    return None


bus.responder = lambda m: threading.Thread(
    target=lambda: bus._contestar(m) if reentrante(m) else None, daemon=True).start()
c("mientras espera una respuesta, contesta a quien le pregunta",
  (con.llamar("org.w", "/w", "org.w", "Registra"), bus.mandar_despues), ([], ("ok", [7])))
c("pedir_nombre(): RequestName sin cola", con.pedir_nombre("org.ejemplo.Yo"), True)
con.emitir("/e/uno", "org.ejemplo.I", "Cambio", "s", ["x"])
time.sleep(0.2)
s = bus.emitidas("Cambio")
c("emitir(): una señal con su ruta, interfaz y cuerpo",
  [(x.ruta, x.interfaz, x.cuerpo) for x in s], [("/e/uno", "org.ejemplo.I", ["x"])])
con.cerrar()


# --- abrir por dirección ---------------------------------------------------------------

def servir(ruta: Path, responder):
    """Un bus falso escuchando en un socket de fichero; atiende lo que llegue."""
    servidor = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    servidor.bind(str(ruta))
    servidor.listen(4)
    atendidos: list[BusFalso] = []

    def aceptar():
        while True:
            try:
                s, _ = servidor.accept()
            except OSError:
                return
            bus = BusFalso(s, responder)
            atendidos.append(bus)
            bus.start()

    threading.Thread(target=aceptar, daemon=True).start()
    return servidor, atendidos


DIR = tmpdir("prdrive-dbus-")
notificaciones: list[dbus.Mensaje] = []


def escritorio(m):
    if m.miembro == "Notify":
        notificaciones.append(m)
        return ("ok", "u", [7])
    return None


servidor, _ = servir(DIR / "sesion", escritorio)
os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={DIR / 'sesion'}"
c("un aviso por Notify en el bus de sesión",
  avisos.enviar("Ha fallado docs", "Mira la ventana", urgente=True), True)
n = notificaciones[-1]
c("  a org.freedesktop.Notifications", (n.campos.get(dbus.DESTINATION), n.interfaz, n.ruta),
  (avisos.NOTIFICACIONES, avisos.NOTIFICACIONES, avisos.RUTA_NOTIFICACIONES))
c("  con la firma de la especificación", n.firma, "susssasa{sv}i")
c("  y lo que se quería decir", n.cuerpo[:5] + [n.cuerpo[6], n.cuerpo[7]],
  ["prdrive", 0, "", "Ha fallado docs", "Mira la ventana", {"urgency": 1}, -1])
os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={DIR / 'no-existe'}"
c("sin bus de sesión el aviso no sale, y no lanza", avisos.enviar("t", "x"), False)
servidor.close()


# --- moderación ------------------------------------------------------------------------

def nm(valor):
    def responde(m):
        if m.miembro == "Get" and m.cuerpo == [moderacion.NM, "Metered"]:
            return ("ok", "v", [dbus.Variante("u", valor)])
        return ("error", "org.freedesktop.DBus.Error.ServiceUnknown", "no está")
    return responde


real_win = moderacion.IS_WIN
moderacion.IS_WIN = False
for valor, esperado in ((1, True), (3, True), (2, False), (4, False), (0, None)):
    ruta = DIR / f"sistema-{valor}"
    srv, _ = servir(ruta, nm(valor))
    os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = f"unix:path={ruta}"
    c(f"NetworkManager Metered={valor}", moderacion.red_medida(), esperado)
    srv.close()
os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = f"unix:path={DIR / 'no-existe'}"
c("sin NetworkManager no se sabe", moderacion.red_medida(), None)

c("coste de Windows sin restricciones: no medida",
  moderacion.coste_medido(moderacion.NLM_COST_UNRESTRICTED), False)
c("tarifa fija: medida", moderacion.coste_medido(moderacion.NLM_COST_FIXED), True)
c("variable: medida", moderacion.coste_medido(moderacion.NLM_COST_VARIABLE), True)
c("en itinerancia: medida",
  moderacion.coste_medido(moderacion.NLM_COST_UNRESTRICTED | moderacion.NLM_COST_ROAMING),
  True)


def fuentes(**cada):
    raiz = tmpdir("prdrive-power-")
    for nombre, ficheros in cada.items():
        (raiz / nombre).mkdir()
        for k, v in ficheros.items():
            (raiz / nombre / k).write_text(v + "\n")
    moderacion.POWER_SUPPLY = raiz
    return moderacion.energia()


c("un sobremesa sin batería: enchufado",
  fuentes(AC={"type": "Mains", "online": "1"}), moderacion.Energia())
c("portátil enchufado cargando",
  fuentes(AC={"type": "Mains", "online": "1"},
          BAT0={"type": "Battery", "capacity": "40", "status": "Charging"}),
  moderacion.Energia(False, 40))
c("portátil a batería",
  fuentes(AC={"type": "Mains", "online": "0"},
          BAT0={"type": "Battery", "capacity": "15", "status": "Discharging"}),
  moderacion.Energia(True, 15))
c("dos baterías: cuenta la más baja",
  fuentes(BAT0={"type": "Battery", "capacity": "80", "status": "Discharging"},
          BAT1={"type": "Battery", "capacity": "12", "status": "Discharging"}),
  moderacion.Energia(True, 12))
c("la batería del ratón no alimenta el equipo",
  fuentes(AC={"type": "Mains", "online": "1"},
          hidpp={"type": "Battery", "scope": "Device", "capacity": "5",
                 "status": "Discharging"}), moderacion.Energia())
c("umbral de carga («Not charging») sin fuente Mains: enchufado",
  fuentes(BAT0={"type": "Battery", "capacity": "60", "status": "Not charging"}),
  moderacion.Energia(False, 60))
moderacion.POWER_SUPPLY = DIR / "no-existe"
c("sin /sys: enchufado", moderacion.energia(), moderacion.Energia())
moderacion.IS_WIN = real_win

c("un DNS que no resuelve es de red",
  moderacion.es_de_red('Failed to create file system for "nas:": couldn\'t connect '
                       'SSH: dial tcp: lookup nas.casa: no such host'), True)
c("un servidor que no contesta es de red",
  moderacion.es_de_red("dial tcp 10.0.0.2:22: i/o timeout"), True)
c("una contraseña mala no es de red",
  moderacion.es_de_red("ssh: handshake failed: ssh: unable to authenticate"), False)
c("demasiados borrados no es de red",
  moderacion.es_de_red("too many deletes (>25%, 30 of 100)"), False)

raise SystemExit(c.report())
