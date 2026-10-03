#!/usr/bin/env python3
"""Los avisos de que vuelve la red (`common/red.py`) y lo que hace el agente con ellos.

Sin tocar la red del equipo: Windows es una `Api` de mentira, netlink un par de
sockets por donde el test manda los mensajes que mandaría el núcleo, y
NetworkManager el bus falso de `tests/_bus_falso.py` haciendo de bus del
sistema. Se comprueba:
- `Direcciones`, la parte pura de netlink: la lista del principio no avisa,
  una dirección global nueva sí, la que solo se renueva no, ni la de enlace
  local ni la provisional de IPv6 hasta que deja de serlo.
- La fuente de Linux: pide la lista, avisa con una dirección nueva y con
  `StateChanged` de NetworkManager hacia un estado conectado, sigue con una de
  las dos si la otra falta o se va, vuelve a pedir la lista tras `ENOBUFS`, y
  `cerrar()` acaba su hilo. Sin ninguna, no escucha, y el agente arranca igual.
- La de Windows: avisa con los niveles que dicen que hay red, una función que
  falta (Windows anterior a la 2004) no es un error, y se cancela al cerrar.
- El agente: una ráfaga de avisos es UNA sonda, cuando se calma; con avisos,
  un remoto que no contesta no se sondea cada 5 min sino a los 30; al volver
  escribe «vuelve la conexión con …» y sus parejas siguen; un aviso que llega
  con la sonda en marcha no se pierde.
"""

import errno
import os
import socket
import struct
import sys
import threading
import time

from _harness import Checks

import _agente_falso as F
import _bus_falso as B
import agente
from common import dbus, equipo, planificador as pl, red

c = Checks("los avisos de que vuelve la red")


def esperar(cond, segundos=3.0):
    """Espera hasta `segundos` a que `cond()` sea cierta; devuelve si lo fue."""
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def mensaje(tipo, serie=0, direccion=b"\xc0\xa8\x01\x0a", familia=socket.AF_INET,
            prefijo=24, flags=0, ambito=red.RT_SCOPE_UNIVERSE, indice=2,
            local=None, flags32=None):
    """Un mensaje de rtnetlink de una dirección, como lo manda el núcleo."""
    cuerpo = red.IFADDRMSG.pack(familia, prefijo, flags, ambito, indice)
    atributos = [(red.IFA_ADDRESS, direccion), (red.IFA_LOCAL, local or direccion)]
    if flags32 is not None:
        atributos.append((red.IFA_FLAGS, struct.pack("=I", flags32)))
    for tipo_attr, valor in atributos:
        cuerpo += red.ATRIBUTO.pack(red.ATRIBUTO.size + len(valor), tipo_attr) + valor
        cuerpo += b"\0" * (-len(cuerpo) % 4)
    return red.CABECERA.pack(red.CABECERA.size + len(cuerpo), tipo, 0, serie, 0) + cuerpo


def fin(serie=1, tipo=red.NLMSG_DONE):
    """El `NLMSG_DONE` (o `NLMSG_ERROR`) con que el núcleo cierra la lista."""
    return red.CABECERA.pack(red.CABECERA.size + 4, tipo, 0x2, serie, 0) + b"\0" * 4


CASA = b"\xc0\xa8\x01\x0a"          # 192.168.1.10
OTRA = b"\x0a\x00\x00\x05"          # 10.0.0.5, una VPN
V6 = bytes.fromhex("20010db8000000000000000000000001")

# Direcciones: lo puro de netlink
d = red.Direcciones()
pet = d.peticion()
largo, tipo, flags, serie, _ = red.CABECERA.unpack_from(pet)
c("la petición es un RTM_GETADDR de la lista entera, con su serie",
  (largo, tipo, flags, serie, len(pet)),
  (24, red.RTM_GETADDR, red.NLM_F_REQUEST | red.NLM_F_DUMP, 1, 24))
c("  de todas las familias", red.IFADDRMSG.unpack_from(pet, 16)[0], socket.AF_UNSPEC)
c("la lista del principio no avisa: ya estaba", d.leer(mensaje(red.RTM_NEWADDR, 1)), False)
c("  pero se apunta", len(d.usables), 1)
c("  y sigue volcando hasta su NLMSG_DONE", d.volcando, True)
c("un NLMSG_DONE de otra petición no la acaba", (d.leer(fin(7)), d.volcando),
  (False, True))
d.leer(fin(1))
c("con el suyo, acaba", d.volcando, False)
c("la misma dirección otra vez (una renovación del DHCP) no avisa",
  d.leer(mensaje(red.RTM_NEWADDR)), False)
c("una dirección global nueva (una VPN, otra red) avisa",
  d.leer(mensaje(red.RTM_NEWADDR, direccion=OTRA)), True)
c("una de enlace local, no", d.leer(mensaje(red.RTM_NEWADDR, direccion=b"\xa9\xfe\x01\x02",
                                           ambito=253)), False)
c("  ni la de la propia máquina", d.leer(mensaje(red.RTM_NEWADDR, direccion=b"\x7f\0\0\x01",
                                                ambito=254)), False)
c("  y ninguna de las dos se cuenta", len(d.usables), 2)
c("una IPv6 provisional (detección de duplicados en curso) todavía no",
  d.leer(mensaje(red.RTM_NEWADDR, direccion=V6, familia=socket.AF_INET6, prefijo=64,
                 flags=red.IFA_F_TENTATIVE)), False)
c("  cuando la pasa, sí", d.leer(mensaje(red.RTM_NEWADDR, direccion=V6,
                                        familia=socket.AF_INET6, prefijo=64)), True)
c("IFA_FLAGS manda sobre los 8 bits de la cabecera",
  d.leer(mensaje(red.RTM_NEWADDR, direccion=b"\x0a\0\0\x09", flags32=red.IFA_F_DADFAILED)),
  False)
c("si una que contaba vuelve a ser provisional (el enlace cayó), deja de contar",
  (d.leer(mensaje(red.RTM_NEWADDR, direccion=V6, familia=socket.AF_INET6, prefijo=64,
                  flags=red.IFA_F_TENTATIVE)), len(d.usables)), (False, 2))
c("una que se va no avisa", d.leer(mensaje(red.RTM_DELADDR, direccion=OTRA)), False)
c("  y si vuelve, es nueva", d.leer(mensaje(red.RTM_NEWADDR, direccion=OTRA)), True)
c("varios mensajes en un datagrama, avisa si alguno es nuevo",
  d.leer(mensaje(red.RTM_NEWADDR) + mensaje(red.RTM_NEWADDR, direccion=b"\x0a\0\0\x07")),
  True)
c("en un enlace punto a punto cuenta la dirección propia (IFA_LOCAL), no la del otro",
  (d.leer(mensaje(red.RTM_NEWADDR, direccion=b"\x0a\x08\0\x01", local=b"\x0a\x08\0\x02")),
   (socket.AF_INET, 2, 24, b"\x0a\x08\0\x02") in d.usables), (True, True))
c("un datagrama cortado no rompe nada", d.leer(mensaje(red.RTM_NEWADDR, direccion=V6)[:30]),
  False)
c("  ni un mensaje que no es de direcciones",
  d.leer(red.CABECERA.pack(20, 16, 0, 0, 0) + b"\0" * 4), False)
d.peticion()
c("pedir la lista otra vez olvida lo sabido y vuelve a volcar",
  (d.serie, d.volcando, len(d.usables)), (2, True, 0))
c("  un NLMSG_ERROR de esa petición también la acaba",
  (d.leer(fin(2, red.NLMSG_ERROR)), d.volcando), (False, False))

# Windows, con una Api de mentira
red_es_win = red.IS_WIN


class ApiFalsa:
    """La `ApiWindows` de mentira: guarda la llamada y apunta lo cancelado.

    Attributes:
        llamada: Lo que llamaría Windows con el nivel nuevo.
        cancelados: Los manejadores cancelados.
        falla: La excepción que lanza `suscribir()`, si alguna.
    """
    def __init__(self, falla=None):
        """Prepara la Api; con `falla`, `suscribir()` la lanza."""
        self.llamada = None
        self.cancelados = []
        self.falla = falla

    def suscribir(self, avisar_nivel):
        """Guarda la llamada y devuelve un manejador de mentira."""
        if self.falla is not None:
            raise self.falla
        self.llamada = avisar_nivel
        return "H:red"

    def cancelar(self, manejador):
        """Apunta el manejador cancelado."""
        self.cancelados.append(manejador)


red.IS_WIN = True
avisos = []
api = ApiFalsa()
w = red.AvisosDeRed(lambda: avisos.append(1), api=api)
c("Windows: se suscribe a NotifyNetworkConnectivityHintChange",
  (w.arrancar(), w.activa, w.fuente), (True, True, "NotifyNetworkConnectivityHintChange"))
for nivel in (red.NIVEL_INTERNET, red.NIVEL_NINGUNO, red.NIVEL_LOCAL, red.NIVEL_DESCONOCIDO,
              red.NIVEL_LIMITADO, red.NIVEL_OCULTO):
    api.llamada(nivel)
c("  avisa con internet, solo red local o un portal cautivo; sin red, nada",
  len(avisos), 3)
w.avisar = lambda: 1 / 0
api.llamada(red.NIVEL_INTERNET)
c("  un fallo de quien recibe el aviso no llega a Windows", True, True)
w.cerrar()
w.cerrar()
c("  al cerrar se cancela, una vez", (api.cancelados, w.activa), (["H:red"], False))
for motivo, falla in (("no exporta la función (anterior a la 2004)",
                       AttributeError("NotifyNetworkConnectivityHintChange")),
                      ("no acepta la suscripción", OSError(87, "ERROR_INVALID_PARAMETER"))):
    w = red.AvisosDeRed(lambda: None, api=ApiFalsa(falla))
    c(f"  si Windows {motivo}: no escucha, sin error", (w.arrancar(), w.activa, w.fuente),
      (False, False, ""))
    w.cerrar()
red.IS_WIN = red_es_win
if os.name == "nt":
    try:
        real = red.ApiWindows()
        c("la ApiWindows de verdad carga iphlpapi (sin suscribirse)", real._llamada, None)
    except AttributeError:
        print("  (saltado) este Windows no tiene NotifyNetworkConnectivityHintChange")
else:
    try:
        red.ApiWindows()
        fallo = "no falló"
    except AttributeError:
        fallo = "AttributeError"
    c("fuera de Windows, ApiWindows() es un AttributeError (lo que arrancar() calla)",
      fallo, "AttributeError")

# Linux: netlink de mentira + NetworkManager en un bus del sistema falso
if os.name == "nt" or not hasattr(socket, "AF_UNIX"):
    print("  (saltado) el hilo de Linux: select() sobre un pipe y sockets de Unix")
else:
    NM_EN = ":1.5"

    class NetlinkFalso:
        """El lado de la fuente de un netlink de mentira, que puede fallar al leer.

        Un socket de datagramas no ve nunca un fin de fichero (netlink tampoco):
        lo que se le puede romper es la lectura (`falla`, un errno, una vez).
        """
        def __init__(self, sock):
            """Envuelve un socket de verdad, para que `select()` funcione."""
            self.sock, self.falla, self.enviados = sock, None, []

        def fileno(self):
            """Devuelve el descriptor del socket."""
            return self.sock.fileno()

        def send(self, datos):
            """Envía al lado del núcleo y lo apunta."""
            self.enviados.append(datos)
            return self.sock.send(datos)

        def recv(self, n):
            """Lee; si toca fallar, lanza ese errno (una vez)."""
            datos = self.sock.recv(n)
            if self.falla is not None:
                falla, self.falla = self.falla, None
                raise OSError(falla, os.strerror(falla))
            return datos

        def close(self):
            """Cierra el socket."""
            self.sock.close()

    def netlink_falso():
        """Devuelve `(lado de la fuente, lado del núcleo)`: un par de datagramas."""
        uno, otro = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        otro.settimeout(3)
        return NetlinkFalso(uno), otro

    def fuente(con_netlink=True, con_bus=True, dueños=(red.NM,)):
        """Arranca una fuente de Linux con lo que se le diga; la devuelve con sus otros lados."""
        lados, buses, avisos = {}, [], []

        def abrir_nl():
            if not con_netlink:
                raise OSError(errno.EPROTONOSUPPORT, "sin netlink")
            uno, otro = netlink_falso()
            lados["nucleo"], lados["fuente"] = otro, uno
            return uno

        def abrir_bus():
            if not con_bus:
                raise dbus.Error("org.freedesktop.DBus.Error.NoServer", "sin bus del sistema")
            con, bus = B.conectar(dueños=dueños)
            buses.append(bus)
            return con

        f = red.AvisosDeRed(lambda: avisos.append(time.monotonic()),
                            conectar_sistema=abrir_bus, conectar_netlink=abrir_nl)
        ok = f.arrancar()
        f.lado = lados.get("fuente")
        return f, ok, lados.get("nucleo"), (buses[0] if buses else None), avisos

    f, ok, nucleo, bus, avisos = fuente()
    c("Linux: escucha netlink y NetworkManager", (ok, f.activa, f.fuente),
      (True, True, "netlink y NetworkManager"))
    pedida = nucleo.recv(4096)
    c("  lo primero que pide a netlink es la lista de direcciones",
      red.CABECERA.unpack_from(pedida)[1], red.RTM_GETADDR)
    c("  y al bus del sistema, StateChanged y el dueño de NetworkManager",
      [x.cuerpo[0] for x in bus.recibidos if x.miembro == "AddMatch"],
      [red.REGLA_NM_ESTADO, red.REGLA_NM_DUENO])
    nucleo.send(mensaje(red.RTM_NEWADDR, 1) + fin(1))
    esperar(lambda: not f.direcciones.volcando)
    c("  la lista del principio no avisa", (f.direcciones.volcando, avisos), (False, []))
    nucleo.send(mensaje(red.RTM_NEWADDR, direccion=OTRA))
    c("  una dirección nueva, sí", esperar(lambda: len(avisos) == 1), True)
    nucleo.send(mensaje(red.RTM_NEWADDR, direccion=OTRA))
    time.sleep(0.1)
    c("  la misma otra vez, no", len(avisos), 1)
    bus.senal(red.NM_RUTA, red.NM, "StateChanged", "u", [red.NM_STATE_CONNECTED_GLOBAL],
              remitente=NM_EN)
    c("  NetworkManager conectado (global) avisa", esperar(lambda: len(avisos) == 2), True)
    for estado in (20, 40, 10):
        bus.senal(red.NM_RUTA, red.NM, "StateChanged", "u", [estado], remitente=NM_EN)
    time.sleep(0.1)
    c("  desconectado, conectando o dormido, no", len(avisos), 2)
    bus.senal(red.NM_RUTA, red.NM, "StateChanged", "u", [red.NM_STATE_CONNECTED_SITE],
              remitente=NM_EN)
    bus.senal(red.NM_RUTA, red.NM, "StateChanged", "u", [red.NM_STATE_CONNECTED_LOCAL],
              remitente=NM_EN)
    c("  del sitio (portal cautivo) y local (sin ruta por defecto), sí",
      esperar(lambda: len(avisos) == 4), True)
    bus.dueño(red.NM, "")
    c("NetworkManager se va: queda netlink",
      esperar(lambda: f.fuente == "netlink"), True)
    c("  y sigue oyendo", f.activa, True)
    f.lado.falla = errno.EIO
    nucleo.send(mensaje(red.RTM_NEWADDR))
    c("netlink falla al leer: se cierra, y ya no se oye nada",
      esperar(lambda: not f.activa), True)
    bus.dueño(red.NM, ":1.77")
    c("  NetworkManager vuelve: se oye otra vez",
      (esperar(lambda: f.activa), f.fuente), (True, "NetworkManager"))
    f.cerrar()
    nucleo.close()
    c("cerrar() acaba el hilo y el bus", (f._hilo.is_alive(), esperar(bus.cerrado.is_set)),
      (False, True))
    f.cerrar()
    c("  y se puede cerrar dos veces", f._pipe, None)

    f, ok, nucleo, bus, avisos = fuente(con_bus=False)
    c("sin bus del sistema, netlink basta", (ok, f.activa, f.fuente),
      (True, True, "netlink"))
    nucleo.recv(4096)
    nucleo.send(fin(1))
    esperar(lambda: not f.direcciones.volcando)
    f.lado.falla = errno.ENOBUFS
    nucleo.send(mensaje(red.RTM_NEWADDR))
    c("ENOBUFS (se han perdido avisos): avisa y vuelve a pedir la lista",
      (esperar(lambda: len(avisos) == 1), esperar(lambda: len(f.lado.enviados) == 2),
       f.direcciones.serie, f.direcciones.volcando, f.activa), (True, True, 2, True, True))
    c("  la petición nueva llega al núcleo con su serie",
      red.CABECERA.unpack_from(nucleo.recv(4096))[3], 2)
    f.cerrar()
    nucleo.close()

    f, ok, nucleo, bus, avisos = fuente(con_netlink=False, dueños=())
    c("sin netlink y sin NetworkManager en el bus: escucha, pero todavía no avisa",
      (ok, f.activa, f.fuente), (True, False, ""))
    bus.dueño(red.NM, ":1.5")
    c("  NetworkManager llega después: ya avisa", esperar(lambda: f.activa), True)
    f.cerrar()

    f, ok, nucleo, bus, avisos = fuente(con_netlink=False, con_bus=False)
    c("sin nada: no escucha, y no pasa nada", (ok, f.activa, f.fuente), (False, False, ""))
    f.cerrar()

    # La de verdad, si este núcleo la deja abrir: la lista llega y no avisa.
    try:
        de_verdad = red.abrir_netlink()
    except (OSError, AttributeError) as e:
        print(f"  (saltado) netlink de verdad: {e}")
    else:
        de_verdad.close()
        avisos = []
        f = red.AvisosDeRed(lambda: avisos.append(1),
                            conectar_sistema=lambda: (_ for _ in ()).throw(OSError("no")))
        c("con el netlink de este núcleo: escucha", (f.arrancar(), f.fuente),
          (True, "netlink"))
        c("  la lista llega entera y no avisa de lo que ya estaba",
          (esperar(lambda: not f.direcciones.volcando), avisos), (True, []))
        f.cerrar()

# El agente
F.preparar()


class AvisosFalsos:
    """Lo que oye la red, de mentira: activo o no."""
    def __init__(self, activa=True):
        """Prepara la fuente falsa."""
        self.activa, self.fuente = activa, "netlink"


UID = "e" * 32
RAIZ = F.unidad(UID, parejas=("docs",))
equipo.guardar_ajustes(equipo.Ajustes().con_unidad(equipo.Unidad(UID, equipo.DAEMON, "U")))
F.RAICES[:] = [RAIZ]
ag = F.nuevo()
ag.avisos_de_red = AvisosFalsos()
F.vueltas(ag, 2)
POL = ag.ajustes.politica
SIN_RED = "Failed to create file system: dial tcp: lookup nas: no such host\n"


def sondas():
    """Las sondas (`rclone lsd`) lanzadas a esa raíz."""
    return [x for x in F.LANZADOS if "lsd" in x.args and str(RAIZ) in " ".join(x.args)]


F.acabar(F.pasadas(RAIZ)[-1], 1, SIN_RED)
F.vueltas(ag, 1)
F.acabar(sondas()[-1], 1, SIN_RED)
F.vueltas(ag, 1)
c("el agente: un remoto sin red queda sin conexión y se avisa",
  (list(ag.entorno.sin_conexion), F.AVISOS[-1][0]), ([(UID, "nas")], "U: sin conexión con nas"))
c("  con avisos de red, la sonda siguiente es el respaldo de 30 min",
  ag.entorno.sin_conexion[(UID, "nas")], F.RELOJ[0] - agente.TICK + POL.sondeo_de_respaldo)
c("  lo dice su estado (agente.py status)", ag.resumen()["cambios_de_red"], "netlink")
F.pasar(POL.sondeo_sin_conexion)
F.vueltas(ag, 1)
F.pasar(20 * 60)
F.vueltas(ag, 1)
c("  a los 5 min no hay sonda, ni a los 25: no se sondea a ciegas", len(sondas()), 1)

DIARIO_ANTES = len(F.DIARIO)
for _ in range(4):                  # una ráfaga: cada interfaz, cada dirección
    ag.pedir({"pide": equipo.PIDE_CAMBIO_DE_RED})
    F.vueltas(ag, 1, cada=1.0)
c("una ráfaga de avisos de red no lanza nada mientras sigue", len(sondas()), 1)
F.vueltas(ag, 3, cada=agente.TICK)
c("  cuando se calma, una sola sonda", len(sondas()), 2)
c("  y una línea en el diario",
  F.DIARIO[DIARIO_ANTES:].count("la red ha cambiado: se prueban ya los remotos sin conexión"),
  1)
F.vueltas(ag, 3)
c("  no hay otra mientras esa sigue en marcha", len(sondas()), 2)
F.acabar(sondas()[-1], 0, "")
F.vueltas(ag, 1)
c("contesta: vuelve la conexión, y se dice en el diario",
  (ag.entorno.sin_conexion, f"[U] vuelve la conexión con nas" in F.DIARIO), ({}, True))
c("  y su pareja va enseguida", F.pasadas(RAIZ)[-1].args[-1], "docs")
F.acabar(F.pasadas(RAIZ)[-1], 0, "")
F.vueltas(ag, 1)

# Un aviso que llega con la sonda en marcha no se pierde.
F.acabar(F.pasadas(RAIZ)[-1], 0, "")
F.pasar(31 * 60)
F.vueltas(ag, 1)
F.acabar(F.pasadas(RAIZ)[-1], 1, SIN_RED)
F.vueltas(ag, 1)
en_marcha = sondas()[-1]
ag.pedir({"pide": equipo.PIDE_CAMBIO_DE_RED})
F.vueltas(ag, 1)
F.pasar(pl.ASENTAR_RED)
F.vueltas(ag, 1)
c("una ráfaga que se calma con la sonda en marcha espera", ag.cambio_de_red is not None,
  True)
n = len(sondas())
F.acabar(en_marcha, 1, SIN_RED)
F.vueltas(ag, 1)
c("  la sonda falla (la red aún no estaba), y la ráfaga lanza otra en vez de esperar 30 min",
  (len(sondas()), ag.cambio_de_red), (n + 1, None))

# Sin avisos: como antes, cada 5 min.
ag.avisos_de_red = AvisosFalsos(activa=False)
F.acabar(sondas()[-1], 1, SIN_RED)
F.vueltas(ag, 1)
c("sin avisos de red (o con la fuente sin oír nada), la sonda siguiente a los 5 min",
  ag.entorno.sin_conexion[(UID, "nas")], F.RELOJ[0] - agente.TICK + POL.sondeo_sin_conexion)
c("  y el estado no dice que los oiga", ag.resumen()["cambios_de_red"], "")
ag.entorno = pl.con_conexion(ag.entorno, UID, "nas")
F.vueltas(ag, 1)
F.acabar(F.pasadas(RAIZ)[-1], 0, "")
F.vueltas(ag, 1)
LINEA = "la red ha cambiado: se prueban ya los remotos sin conexión"
dichas = F.DIARIO.count(LINEA)
ag.pedir({"pide": equipo.PIDE_CAMBIO_DE_RED})
F.vueltas(ag, 5)
c("una ráfaga sin remotos sin conexión se olvida sin decir nada",
  (ag.cambio_de_red, F.DIARIO.count(LINEA), len(sondas())), (None, dichas, len(sondas())))

# poner_red: el agente arranca aunque no haya nada que oír
diario = []
agente.diario = diario.append
red_real = red.AvisosDeRed


class NadaQueOir(red_real):
    """Una fuente sin netlink ni bus del sistema."""
    def __init__(self, avisar):
        """Arranca sin nada."""
        super().__init__(avisar, api=ApiFalsa(AttributeError("x")),
                         conectar_sistema=lambda: (_ for _ in ()).throw(OSError("no")),
                         conectar_netlink=lambda: (_ for _ in ()).throw(OSError("no")))


class VigiaFalso:
    """Vigía de mentira que cuenta los despertares."""
    despertado = 0

    def despertar(self, montajes=False):
        """Cuenta un despertar."""
        VigiaFalso.despertado += 1


red.AvisosDeRed = NadaQueOir
c("poner_red sin nada que oír: None, y el agente sigue",
  agente.poner_red(ag, VigiaFalso()), None)
c("  lo dice en el diario, con sus 5 min",
  any("no oigo los cambios de red" in x and "5 min" in x for x in diario), True)


class ConAvisos(red_real):
    """Una fuente de Windows de mentira que escucha."""
    def __init__(self, avisar):
        """Arranca con una Api falsa."""
        super().__init__(avisar, api=ApiFalsa())
        self.windows = True


red.AvisosDeRed = ConAvisos
puesta = agente.poner_red(ag, VigiaFalso())
c("poner_red con algo que oír la devuelve y lo dice con sus 30 min de respaldo",
  (puesta is not None, any("oigo los cambios de red (NotifyNetwork" in x and "30 min" in x
                           for x in diario)), (True, True))
ag.peticiones = agente.queue.SimpleQueue()
puesta.api.llamada(red.NIVEL_INTERNET)
c("  cada aviso es un PIDE_CAMBIO_DE_RED en la cola del agente, y lo despierta",
  (ag.peticiones.get_nowait(), VigiaFalso.despertado),
  ({"pide": equipo.PIDE_CAMBIO_DE_RED}, 1))
puesta.cerrar()
red.AvisosDeRed = red_real
c("nada de esto trae Tk al agente", "tkinter" in sys.modules, False)
c("ni deja hilos de la red vivos",
  [t.name for t in threading.enumerate() if t.name == "red" and t.is_alive()], [])

sys.exit(c.report())
