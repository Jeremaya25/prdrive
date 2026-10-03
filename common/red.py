#!/usr/bin/env python3
"""Los avisos del sistema de que vuelve a haber red, para el agente.

Con un remoto «sin conexión» el agente lo sondea (`planificador.SONDA`) cuando
el sistema dice que la red ha cambiado, no a ciegas cada pocos minutos. Esto
oye ese cambio y llama a `avisar()`, que el agente convierte en la petición
`equipo.PIDE_CAMBIO_DE_RED` de su cola; agrupar la ráfaga y decidir qué se
sondea es cosa de `common/planificador.py` (`CambioDeRed`, `sondeo()`). El
aviso dice «hay red», no «el remoto contesta» (una VPN, un portal cautivo, el
DNS): por eso la sonda sigue haciendo falta.

Las fuentes, citadas como `common/dbus.py` cita la *D-Bus Specification*:
- **Windows**: `NotifyNetworkConnectivityHintChange` de iphlpapi (netioapi.h;
  Windows 10, versión 2004, compilación 19041, en adelante). El sistema llama,
  en un hilo suyo, cuando cambia el nivel de conectividad agregado
  (`NL_NETWORK_CONNECTIVITY_HINT`, nldef.h), y se avisa cuando ese nivel dice
  que hay alguna red (`NIVELES_CON_RED`). Se cancela con
  `CancelMibChangeNotify2`, nunca desde la propia llamada: su documentación
  avisa de que sería un interbloqueo. Un Windows más viejo no exporta la
  función: no hay avisos.
- **Linux, netlink** (`NETLINK_ROUTE`, rtnetlink(7)): los grupos
  `RTMGRP_IPV4_IFADDR` y `RTMGRP_IPV6_IFADDR` cuentan cada dirección que
  aparece, cambia o se va. Se avisa cuando aparece una dirección global y
  utilizable que no estaba (`Direcciones`): una red que vuelve, una VPN que se
  levanta, un cable que se enchufa. Una renovación del DHCP o del anuncio del
  router repite una dirección que ya estaba, y esa no avisa. Es del núcleo:
  vale con NetworkManager, systemd-networkd, ifupdown o lo que configure la
  red.
- **Linux, NetworkManager** (`org.freedesktop.NetworkManager` en el bus del
  sistema, «D-Bus API Reference» de NetworkManager): la señal
  `StateChanged(u)` cuando el estado pasa a uno conectado (`NM_CONECTADO`, el
  `NMState` de nm-dbus-interface.h). Ve lo que netlink no ve: un portal cautivo
  que por fin deja pasar (de `CONNECTED_SITE` a `CONNECTED_GLOBAL`) sin que
  cambie ninguna dirección. Si NetworkManager no está o se va
  (`NameOwnerChanged`), queda netlink.

Sin ninguna, `activa` es `False` y el agente sondea cada
`Politica.sondeo_sin_conexion`, como antes. Nada de esto lanza: una fuente que
no se abre no impide que el agente arranque; se pierde el aviso, no el agente.
Lo que la fuente no ve (el remoto que vuelve sin que cambie nada en este
equipo, una suscripción que nunca avisa) lo cubre el temporizador largo,
`Politica.sondeo_de_respaldo`.

Windows no necesita hilo: el sistema llama desde los suyos. En Linux hay uno
propio, con sus dos descriptores (el socket de netlink y el bus del sistema) y
un pipe para despertarlo al cerrar. Los tests ponen una `ApiWindows` de
mentira, el bus de `tests/_bus_falso.py` y un socket de netlink falso
(`tests/test_red.py`); nada de esto se ha visto en un equipo real.
"""

from __future__ import annotations

import errno
import os
import select
import socket
import struct
import threading
from typing import Any, Callable

from . import dbus
from .moderacion import NM, NM_RUTA

IS_WIN = os.name == "nt"

ESPERA_ARRANQUE = 5.0
"""Segundos que espera `arrancar()` a que el hilo abra sus fuentes."""
ESPERA_BUCLE = 60.0             # sin nada que hacer, el hilo se despierta igual

# Windows: `NL_NETWORK_CONNECTIVITY_LEVEL_HINT` (nldef.h), por orden.
NIVEL_DESCONOCIDO = 0           # NetworkConnectivityLevelHintUnknown
NIVEL_NINGUNO = 1               # NetworkConnectivityLevelHintNone
NIVEL_LOCAL = 2                 # NetworkConnectivityLevelHintLocalAccess
NIVEL_INTERNET = 3              # NetworkConnectivityLevelHintInternetAccess
NIVEL_LIMITADO = 4              # NetworkConnectivityLevelHintConstrainedInternetAccess
NIVEL_OCULTO = 5                # NetworkConnectivityLevelHintHidden
NIVELES_CON_RED = (NIVEL_LOCAL, NIVEL_INTERNET, NIVEL_LIMITADO)
"""Los niveles de conectividad de Windows con los que se avisa.

El local cuenta: el remoto puede ser un NAS de casa. El limitado (un portal
cautivo) también: la sonda dirá si se llega, y al pasar el portal el nivel
vuelve a cambiar. Sin red, desconocido u oculto, no hay nada que probar.
"""
NO_ERROR = 0

# Linux: rtnetlink (linux/netlink.h, linux/rtnetlink.h, linux/if_addr.h).
NLMSG_ERROR = 0x2
NLMSG_DONE = 0x3
NLM_F_REQUEST = 0x01
NLM_F_DUMP = 0x300              # NLM_F_ROOT | NLM_F_MATCH
RTM_NEWADDR, RTM_DELADDR, RTM_GETADDR = 20, 21, 22
RTMGRP_IPV4_IFADDR = 0x10
RTMGRP_IPV6_IFADDR = 0x100
IFA_ADDRESS, IFA_LOCAL, IFA_FLAGS = 1, 2, 8
IFA_F_DADFAILED = 0x08
IFA_F_TENTATIVE = 0x40
RT_SCOPE_UNIVERSE = 0
CABECERA = struct.Struct("=IHHII")
"""`struct nlmsghdr`: longitud, tipo, flags, serie y pid, en el orden del equipo."""
IFADDRMSG = struct.Struct("=BBBBI")
"""`struct ifaddrmsg`: familia, longitud del prefijo, flags, ámbito e índice."""
ATRIBUTO = struct.Struct("=HH")
"""`struct rtattr`: longitud y tipo."""
TAMANO_NETLINK = 65536          # bytes que se leen de una vez del socket

# Linux: NetworkManager, `NMState` (nm-dbus-interface.h).
NM_STATE_CONNECTED_LOCAL = 50
NM_STATE_CONNECTED_SITE = 60
NM_STATE_CONNECTED_GLOBAL = 70
NM_CONECTADO = (NM_STATE_CONNECTED_LOCAL, NM_STATE_CONNECTED_SITE,
                NM_STATE_CONNECTED_GLOBAL)
"""Los estados de NetworkManager con los que se avisa: local, del sitio y global.

Local es «sin ruta por defecto» y basta para un NAS de casa; global es que la
comprobación de conectividad ha llegado a internet.
"""
REGLA_NM_ESTADO = (f"type='signal',sender='{NM}',path='{NM_RUTA}',interface='{NM}',"
                   "member='StateChanged'")
"""La regla para oír `StateChanged` de NetworkManager («Match Rules»)."""
REGLA_NM_DUENO = (f"type='signal',sender='{dbus.BUS}',interface='{dbus.BUS}',"
                  f"member='NameOwnerChanged',arg0='{NM}'")
"""La regla para oír que NetworkManager llega, se va o se reinicia."""


def hay_red_windows(nivel: int) -> bool:
    """Indica si ese nivel de conectividad de Windows dice que hay alguna red."""
    return nivel in NIVELES_CON_RED


def _alinear(n: int) -> int:
    """Devuelve `n` redondeado a 4, el `NLMSG_ALIGN` y el `RTA_ALIGN` de netlink."""
    return (n + 3) & ~3


class Direcciones:
    """Las direcciones globales y utilizables del equipo, vistas por netlink.

    Es la parte pura de la fuente de netlink: recibe los datagramas tal cual y
    dice si ha aparecido una dirección que no estaba. Al empezar pide la lista
    entera (`peticion()`, un `RTM_GETADDR` con `NLM_F_DUMP`) y, hasta que el
    núcleo dice `NLMSG_DONE`, solo apunta: lo que ya estaba no es un cambio.

    Utilizable es de ámbito global (`RT_SCOPE_UNIVERSE`: ni la de enlace local
    ni la de la propia máquina) y ni provisional ni fallida en la detección de
    duplicados de IPv6 (`IFA_F_TENTATIVE`, `IFA_F_DADFAILED`). Una dirección
    que vuelve a ser provisional (el enlace ha caído y vuelto) deja de contar,
    y cuando pasa la detección cuenta como nueva.

    Attributes:
        usables: Las direcciones utilizables, como `(familia, índice, prefijo,
            dirección)`.
        volcando: Si todavía llega la lista pedida al empezar.
        serie: El número de serie de la última petición.
    """

    def __init__(self) -> None:
        """Empieza sin direcciones y a la espera de la lista."""
        self.usables: set[tuple[int, int, int, bytes]] = set()
        self.volcando = True
        self.serie = 0

    def peticion(self) -> bytes:
        """Devuelve la petición de la lista entera de direcciones, y empieza a volcar.

        Lo sabido se olvida: la lista que llegue es la que vale.
        """
        self.serie += 1
        self.volcando = True
        self.usables.clear()
        cuerpo = IFADDRMSG.pack(socket.AF_UNSPEC, 0, 0, 0, 0)
        return CABECERA.pack(CABECERA.size + len(cuerpo), RTM_GETADDR,
                             NLM_F_REQUEST | NLM_F_DUMP, self.serie, 0) + cuerpo

    def leer(self, datos: bytes) -> bool:
        """Lee un datagrama de netlink y devuelve si ha aparecido una dirección nueva.

        Un datagrama lleva uno o varios mensajes; lo que no se entiende (un
        mensaje cortado, otro tipo) se salta.
        """
        nueva = False
        pos = 0
        while pos + CABECERA.size <= len(datos):
            largo, tipo, _flags, serie, _pid = CABECERA.unpack_from(datos, pos)
            if largo < CABECERA.size or pos + largo > len(datos):
                break
            cuerpo = datos[pos + CABECERA.size:pos + largo]
            pos += _alinear(largo)
            if tipo in (NLMSG_DONE, NLMSG_ERROR):
                if serie == self.serie:
                    self.volcando = False       # acabada, o el núcleo no la da
                continue
            if tipo not in (RTM_NEWADDR, RTM_DELADDR):
                continue
            leida = self._direccion(cuerpo)
            if leida is None:
                continue
            clave, usable = leida
            if tipo == RTM_NEWADDR and usable:
                if clave not in self.usables:
                    self.usables.add(clave)
                    nueva = nueva or not self.volcando
            else:
                self.usables.discard(clave)
        return nueva

    @staticmethod
    def _direccion(cuerpo: bytes) -> tuple[tuple[int, int, int, bytes], bool] | None:
        """Devuelve la clave de la dirección de un `ifaddrmsg` y si es utilizable.

        La dirección propia es `IFA_LOCAL` y, sin ella, `IFA_ADDRESS` (en un
        enlace punto a punto `IFA_ADDRESS` es la del otro extremo). `IFA_FLAGS`,
        si viene, sustituye a los flags de 8 bits de la cabecera.

        Returns:
            `(clave, utilizable)`, o `None` si el mensaje no trae dirección.
        """
        if len(cuerpo) < IFADDRMSG.size:
            return None
        familia, prefijo, flags, ambito, indice = IFADDRMSG.unpack_from(cuerpo)
        atributos: dict[int, bytes] = {}
        pos = _alinear(IFADDRMSG.size)
        while pos + ATRIBUTO.size <= len(cuerpo):
            largo, tipo = ATRIBUTO.unpack_from(cuerpo, pos)
            if largo < ATRIBUTO.size or pos + largo > len(cuerpo):
                break
            atributos[tipo] = cuerpo[pos + ATRIBUTO.size:pos + largo]
            pos += _alinear(largo)
        if len(atributos.get(IFA_FLAGS, b"")) >= 4:
            flags = struct.unpack_from("=I", atributos[IFA_FLAGS])[0]
        direccion = atributos.get(IFA_LOCAL) or atributos.get(IFA_ADDRESS)
        if not direccion:
            return None
        usable = (ambito == RT_SCOPE_UNIVERSE
                  and not flags & (IFA_F_TENTATIVE | IFA_F_DADFAILED))
        return (familia, indice, prefijo, direccion), usable


def abrir_netlink() -> socket.socket:
    """Abre un socket de rtnetlink suscrito a los cambios de direcciones IPv4 e IPv6.

    No hace falta ser administrador: es lo que lee `ip monitor address`.

    Raises:
        OSError: Si el núcleo no lo deja abrir.
        AttributeError: Si no es Linux (no hay `AF_NETLINK`).
    """
    s = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, socket.NETLINK_ROUTE)
    try:
        s.bind((0, RTMGRP_IPV4_IFADDR | RTMGRP_IPV6_IFADDR))
    except OSError:
        s.close()
        raise
    return s


class ApiWindows:
    """Las llamadas a iphlpapi: suscribirse a los cambios de conectividad y cancelarlo.

    Raises:
        AttributeError: Si este Windows no exporta
            `NotifyNetworkConnectivityHintChange` (es anterior a la 2004).
        OSError: Si no se puede cargar iphlpapi.
    """

    def __init__(self) -> None:
        """Carga iphlpapi y declara las firmas de lo que se usa."""
        import ctypes
        from ctypes import wintypes

        class NL_NETWORK_CONNECTIVITY_HINT(ctypes.Structure):
            """Estructura `NL_NETWORK_CONNECTIVITY_HINT` de nldef.h."""
            _fields_ = [("ConnectivityLevel", ctypes.c_int),
                        ("ConnectivityCost", ctypes.c_int),
                        ("ApproachingDataLimit", ctypes.c_ubyte),
                        ("OverDataLimit", ctypes.c_ubyte),
                        ("Roaming", ctypes.c_ubyte)]

        self.ct, self.wt = ctypes, wintypes
        iphlpapi = ctypes.WinDLL("iphlpapi")
        # `PNETWORK_CONNECTIVITY_HINT_CHANGE_CALLBACK` (netioapi.h):
        # VOID (PVOID CallerContext, NL_NETWORK_CONNECTIVITY_HINT ConnectivityHint),
        # con la estructura por valor.
        self.LLAMADA = ctypes.WINFUNCTYPE(None, ctypes.c_void_p,
                                          NL_NETWORK_CONNECTIVITY_HINT)
        self._notificar = iphlpapi.NotifyNetworkConnectivityHintChange
        self._notificar.restype = wintypes.DWORD
        self._notificar.argtypes = [self.LLAMADA, ctypes.c_void_p, wintypes.BOOLEAN,
                                    ctypes.POINTER(wintypes.HANDLE)]
        self._cancelar = iphlpapi.CancelMibChangeNotify2
        self._cancelar.restype = wintypes.DWORD
        self._cancelar.argtypes = [wintypes.HANDLE]
        self._llamada = None                # la referencia que ctypes necesita viva

    def suscribir(self, avisar_nivel: Callable[[int], None]) -> Any:
        """Se suscribe y devuelve el manejador de la suscripción.

        Sin la notificación inicial (`InitialNotification` falso): solo los
        cambios.

        Args:
            avisar_nivel: Lo que se llama, en un hilo del sistema, con el nivel
                de conectividad nuevo.

        Raises:
            OSError: Si Windows no acepta la suscripción.
        """
        def llamada(_contexto, pista) -> None:
            """Pasa el nivel nuevo sin dejar que un fallo llegue a Windows."""
            try:
                avisar_nivel(int(pista.ConnectivityLevel))
            except Exception:                           # noqa: BLE001
                pass

        self._llamada = self.LLAMADA(llamada)
        manejador = self.wt.HANDLE()
        rc = self._notificar(self._llamada, None, False, self.ct.byref(manejador))
        if rc != NO_ERROR:
            self._llamada = None
            raise OSError(rc, f"NotifyNetworkConnectivityHintChange: error {rc}")
        return manejador

    def cancelar(self, manejador: Any) -> None:
        """Cancela la suscripción; desde aquí ya no llega ninguna llamada.

        `CancelMibChangeNotify2` espera a la llamada que esté en curso, así que
        quien la cancela no puede tener nada que esa llamada espere (su
        documentación). Lo único que espera la de Python es el GIL, y ctypes lo
        suelta mientras dura la de Windows. Solo después se suelta la función.
        """
        self._cancelar(manejador)
        self._llamada = None


class AvisosDeRed:
    """Lo que oye los cambios de red y llama a `avisar()` cuando vuelve a haberla.

    `avisar()` se llama desde otro hilo (uno de Windows o el de esta clase):
    tiene que ser barato y seguro entre hilos. El agente mete una petición en
    su cola y se despierta.

    Args:
        avisar: Lo que se llama cuando vuelve a haber red o cambia la que hay.
        api: Las llamadas a Windows; por defecto, `ApiWindows`. Los tests le
            ponen una de mentira.
        conectar_sistema: Abre el bus del sistema; por defecto,
            `dbus.Conexion.sistema`.
        conectar_netlink: Abre el socket de netlink ya suscrito; por defecto,
            `abrir_netlink`.
    """

    def __init__(self, avisar: Callable[[], None], api: Any = None,
                 conectar_sistema: Callable[[], dbus.Conexion] | None = None,
                 conectar_netlink: Callable[[], Any] | None = None) -> None:
        """Prepara las fuentes sin abrir ninguna todavía."""
        self.avisar = avisar
        self.windows = IS_WIN
        self.api = api
        self._conectar_sistema = conectar_sistema or dbus.Conexion.sistema
        self._conectar_netlink = conectar_netlink or abrir_netlink
        self._manejador: Any = None
        self.sistema: dbus.Conexion | None = None
        self._nm = False
        self._netlink: Any = None
        self.direcciones = Direcciones()
        self._pipe: tuple[int, int] | None = None
        self._salir = False
        self._hilo: threading.Thread | None = None
        self._listo = threading.Event()

    def arrancar(self) -> bool:
        """Se suscribe a lo que haya en este sistema y devuelve si escucha algo.

        En Linux, «escuchar» es tener abierto netlink o el bus del sistema:
        con el bus y sin NetworkManager todavía no avisa (`activa` es False),
        pero empieza a hacerlo si NetworkManager llega después.
        """
        if self.windows:
            try:
                if self.api is None:
                    self.api = ApiWindows()
                self._manejador = self.api.suscribir(self._nivel)
            except Exception:                           # noqa: BLE001
                self._manejador = None      # sin la función (AttributeError) o sin Windows
            return self._manejador is not None
        try:
            self._pipe = os.pipe()
            os.set_blocking(self._pipe[1], False)
        except OSError:
            return False
        self._hilo = threading.Thread(target=self._correr, name="red", daemon=True)
        self._hilo.start()
        self._listo.wait(ESPERA_ARRANQUE)
        return self._netlink is not None or self.sistema is not None

    @property
    def activa(self) -> bool:
        """Indica si ahora mismo se oyen los cambios de red."""
        if self.windows:
            return self._manejador is not None
        return self._netlink is not None or (self.sistema is not None and self._nm)

    @property
    def fuente(self) -> str:
        """Devuelve qué se oye, para el diario y `agente.py status`; vacío si nada."""
        if self.windows:
            return "NotifyNetworkConnectivityHintChange" if self._manejador is not None else ""
        partes = (["netlink"] if self._netlink is not None else []) + (
            ["NetworkManager"] if self.sistema is not None and self._nm else [])
        return " y ".join(partes)

    def cerrar(self) -> None:
        """Cancela la suscripción o para el hilo; se puede llamar más de una vez."""
        if self.windows:
            manejador, self._manejador = self._manejador, None
            if manejador is not None:
                try:
                    self.api.cancelar(manejador)
                except Exception:                       # noqa: BLE001
                    pass
            return
        self._salir = True
        if self._pipe is None:
            return
        try:
            os.write(self._pipe[1], b"!")
        except OSError:
            pass                    # lleno: ya hay un despertar pendiente
        if self._hilo is not None and self._hilo is not threading.current_thread():
            self._hilo.join(ESPERA_ARRANQUE)
            if self._hilo.is_alive():
                return              # sin cerrar el pipe: el hilo todavía lo mira
        for fd in self._pipe:
            try:
                os.close(fd)
            except OSError:
                pass
        self._pipe = None

    def _avisar(self) -> None:
        """Llama a `avisar()` sin dejar que un fallo suyo tumbe la fuente."""
        try:
            self.avisar()
        except Exception:                               # noqa: BLE001
            pass

    def _nivel(self, nivel: int) -> None:
        """Atiende la llamada de Windows con el nivel de conectividad nuevo."""
        if hay_red_windows(nivel):
            self._avisar()

    def _correr(self) -> None:
        """Es el hilo de Linux: abre las fuentes y las atiende hasta `cerrar()`."""
        try:
            self._abrir()
        finally:
            self._listo.set()
        try:
            self._bucle()
        finally:
            self._cerrar_netlink()
            self._cerrar_sistema()

    def _abrir(self) -> None:
        """Abre netlink (y pide la lista de direcciones) y el bus del sistema."""
        try:
            self._netlink = self._conectar_netlink()
            self._netlink.send(self.direcciones.peticion())
        except (OSError, AttributeError):
            self._cerrar_netlink()
        try:
            self.sistema = self._conectar_sistema()
            self.sistema.escuchar(REGLA_NM_ESTADO)
            self.sistema.escuchar(REGLA_NM_DUENO)
            self._nm = self.sistema.tiene_dueno(NM)
        except (dbus.Error, OSError):
            self._cerrar_sistema()

    def _bucle(self) -> None:
        """Espera a netlink, al bus o al pipe, y atiende lo que llegue."""
        while not self._salir and (self._netlink is not None or self.sistema is not None):
            self._atender_bus()
            fds: list[Any] = [self._pipe[0]]
            fds += [f for f in (self._netlink, self.sistema) if f is not None]
            try:
                listos, _, _ = select.select(fds, [], [], ESPERA_BUCLE)
            except (OSError, ValueError):
                return
            if self._pipe[0] in listos:
                try:
                    os.read(self._pipe[0], 4096)
                except OSError:
                    pass
            if self._netlink is not None and self._netlink in listos:
                self._leer_netlink()

    def _leer_netlink(self) -> None:
        """Lee un datagrama de netlink y avisa si ha aparecido una dirección.

        Si el núcleo ha tenido que tirar avisos (`ENOBUFS`: la cola del socket
        se ha llenado), algo ha cambiado y lo que se sabía ya no vale: se avisa
        y se vuelve a pedir la lista.
        """
        try:
            datos = self._netlink.recv(TAMANO_NETLINK)
        except BlockingIOError:
            return
        except OSError as e:
            if e.errno != errno.ENOBUFS:
                self._cerrar_netlink()
                return
            self._avisar()
            try:
                self._netlink.send(self.direcciones.peticion())
            except OSError:
                self._cerrar_netlink()
            return
        if not datos:
            self._cerrar_netlink()
            return
        if self.direcciones.leer(datos):
            self._avisar()

    def _atender_bus(self) -> None:
        """Atiende las señales que hayan llegado del bus del sistema."""
        if self.sistema is None:
            return
        try:
            senales = self.sistema.atender(0)
        except (dbus.Error, OSError):
            self._cerrar_sistema()      # sin bus queda netlink, si lo hay
            return
        for s in senales:
            if s.miembro == "NameOwnerChanged" and s.cuerpo[:1] == [NM]:
                self._nm = len(s.cuerpo) >= 3 and bool(s.cuerpo[2])
            elif (s.miembro == "StateChanged" and s.interfaz == NM and s.cuerpo
                  and s.cuerpo[0] in NM_CONECTADO):
                self._avisar()

    def _cerrar_netlink(self) -> None:
        """Cierra el socket de netlink, si está abierto."""
        if self._netlink is not None:
            try:
                self._netlink.close()
            except OSError:
                pass
        self._netlink = None

    def _cerrar_sistema(self) -> None:
        """Cierra el bus del sistema, si está abierto."""
        if self.sistema is not None:
            self.sistema.cerrar()
        self.sistema = None
        self._nm = False
