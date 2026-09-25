#!/usr/bin/env python3
"""
dbus.py — Un cliente de D-Bus sin dependencias: la mitad que LLAMA.

Linux habla con el escritorio por D-Bus: los avisos
(`org.freedesktop.Notifications`), si la red es de uso medido (la propiedad
`Metered` de NetworkManager) y, más adelante, la bandeja y la señal de
suspender. Python no trae D-Bus y el proyecto no admite dependencias, así que
esto lo implementa con el mismo espíritu que `ui/qr.py`: completo en lo que usa,
y con las constantes citando la especificación, como `common/bisync.py` cita a
rclone. Todo lo de aquí sale de la *D-Bus Specification* de freedesktop.org
(https://dbus.freedesktop.org/doc/dbus-specification.html); cada sección dice
de qué apartado.

Lo que hay:

  * las direcciones de los buses (`sesion()`, `sistema()`), «Server Addresses»;
  * el saludo `EXTERNAL`, «Authentication Protocol»;
  * la serialización de mensajes, «Message Protocol» → «Marshaling»: firmas,
    alineación, arrays, diccionarios, estructuras y variantes;
  * llamar a un método y esperar su respuesta o su error, leer una propiedad y
    escuchar señales (`AddMatch`), «Message Bus Specification».

Lo que NO hay, a propósito: exportar objetos en el bus (eso es la bandeja de
Linux, otra fase), pasar descriptores de fichero (`h` se serializa como el
índice que es, pero no se mandan descriptores) y la autenticación
`DBUS_COOKIE_SHA1`, que un bus de sesión local no pide.

Está en `common/` porque lo usan cosas que no son la ventana —los avisos y la
moderación del agente— y no importa nada de Tk. Nada aquí es imprescindible:
quien lo usa captura `Error` y `OSError` y sigue sin D-Bus, que es lo que pasa
en un equipo sin escritorio.
"""

from __future__ import annotations

import os
import select
import socket
import struct
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, NamedTuple


class Error(Exception):
    """Un error de D-Bus: la respuesta ERROR a una llamada, o el bus que no
    contesta como la especificación dice que tiene que contestar."""

    def __init__(self, nombre: str, mensaje: str = "") -> None:
        super().__init__(f"{nombre}: {mensaje}" if mensaje else nombre)
        self.nombre = nombre
        self.mensaje = mensaje


class Variante(NamedTuple):
    """Un valor con su firma, para mandar una `v`.

    Al leer, las variantes se desenvuelven y llega el valor a secas; al escribir
    hace falta decir el tipo, porque un 1 de Python puede ser un `y`, un `i`, un
    `u` o un `x`, y quien lo recibe los distingue."""
    firma: str
    valor: Any


# ---------------------------------------------------------------------------
# Marshaling («Message Protocol» → «Marshaling (Wire Format)»)
# ---------------------------------------------------------------------------

# La alineación de cada tipo básico, de la tabla del apartado «Marshaling».
# Las estructuras y las entradas de diccionario se alinean a 8; las variantes,
# a 1 (su firma es una `g`). El relleno es siempre de ceros.
ALINEACION = {"y": 1, "b": 4, "n": 2, "q": 2, "i": 4, "u": 4, "x": 8, "t": 8,
              "d": 8, "h": 4, "s": 4, "o": 4, "g": 1, "a": 4, "(": 8, "{": 8,
              "v": 1}
_FIJOS = {"y": "B", "n": "h", "q": "H", "i": "i", "u": "I", "x": "q", "t": "Q",
          "d": "d", "h": "I"}
# «Valid Signatures»: un array no puede pasar de 2^26 bytes (64 MiB), y un
# mensaje entero de 2^27 (128 MiB). Se comprueba al leer: un bus que manda más
# no es uno de verdad.
MAX_ARRAY = 1 << 26
MAX_MENSAJE = 1 << 27


def partir(firma: str) -> list[str]:
    """Una firma partida en sus tipos completos: 'sa{sv}(ii)' → ['s', 'a{sv}', '(ii)']."""
    tipos, i = [], 0
    while i < len(firma):
        fin = _fin_de_tipo(firma, i)
        tipos.append(firma[i:fin])
        i = fin
    return tipos


def _fin_de_tipo(firma: str, i: int) -> int:
    if i >= len(firma):
        raise Error("org.freedesktop.DBus.Error.InvalidSignature", firma)
    c = firma[i]
    if c == "a":
        return _fin_de_tipo(firma, i + 1)
    if c in "({":
        cierre = ")" if c == "(" else "}"
        j, nivel = i + 1, 1
        while j < len(firma):
            if firma[j] == c:
                nivel += 1
            elif firma[j] == cierre:
                nivel -= 1
                if nivel == 0:
                    return j + 1
            j += 1
        raise Error("org.freedesktop.DBus.Error.InvalidSignature", firma)
    if c in ALINEACION:
        return i + 1
    raise Error("org.freedesktop.DBus.Error.InvalidSignature", firma)


def firma_de(valor: Any) -> str:
    """La firma que se le supone a un valor de Python sin `Variante`.

    Solo para lo inequívoco; lo demás tiene que ir con su `Variante`."""
    if isinstance(valor, Variante):
        return "v"
    if isinstance(valor, bool):
        return "b"
    if isinstance(valor, int):
        return "i"
    if isinstance(valor, float):
        return "d"
    if isinstance(valor, str):
        return "s"
    if isinstance(valor, (bytes, bytearray)):
        return "ay"
    raise TypeError(f"no sé qué firma darle a {type(valor).__name__}; usa Variante")


class Escritor:
    """Serializa valores en little-endian, que es lo que escribe este lado."""

    def __init__(self) -> None:
        self.buf = bytearray()

    def alinear(self, n: int) -> None:
        self.buf += b"\0" * (-len(self.buf) % n)

    def escribir(self, firma: str, valores: Iterable[Any]) -> "Escritor":
        tipos = partir(firma)
        valores = list(valores)
        if len(tipos) != len(valores):
            raise TypeError(f"la firma {firma!r} pide {len(tipos)} valores y hay "
                            f"{len(valores)}")
        for tipo, valor in zip(tipos, valores):
            self._uno(tipo, valor)
        return self

    def _uno(self, tipo: str, valor: Any) -> None:
        c = tipo[0]
        self.alinear(ALINEACION[c])
        if c in _FIJOS:
            self.buf += struct.pack("<" + _FIJOS[c], valor)
        elif c == "b":
            self.buf += struct.pack("<I", 1 if valor else 0)
        elif c in "so":
            datos = valor.encode("utf-8")
            self.buf += struct.pack("<I", len(datos)) + datos + b"\0"
        elif c == "g":
            datos = valor.encode("ascii")
            self.buf += struct.pack("<B", len(datos)) + datos + b"\0"
        elif c == "v":
            if not isinstance(valor, Variante):
                valor = Variante(firma_de(valor), valor)
            self._uno("g", valor.firma)
            self._uno(valor.firma, valor.valor)
        elif c == "(":
            self.escribir(tipo[1:-1], valor)
        elif c == "a":
            self._array(tipo[1:], valor)
        else:
            raise Error("org.freedesktop.DBus.Error.InvalidSignature", tipo)

    def _array(self, elemento: str, valor: Any) -> None:
        # «The array length is a UINT32 giving the length in bytes of the array
        # data, NOT including the padding after the length». El relleno hasta
        # la alineación del elemento va SIEMPRE, también con el array vacío.
        hueco = len(self.buf)
        self.buf += b"\0\0\0\0"
        self.alinear(ALINEACION[elemento[0]])
        inicio = len(self.buf)
        if elemento == "y":
            self.buf += bytes(valor)
        elif elemento[0] == "{":
            clave, dato = partir(elemento[1:-1])
            elementos = valor.items() if isinstance(valor, dict) else valor
            for k, v in elementos:
                self.alinear(8)
                self._uno(clave, k)
                self._uno(dato, v)
        else:
            for v in valor:
                self._uno(elemento, v)
        self.buf[hueco:hueco + 4] = struct.pack("<I", len(self.buf) - inicio)


class Lector:
    """Lee valores de un mensaje, en el orden de bytes que diga su cabecera."""

    def __init__(self, datos: bytes, orden: str = "<", pos: int = 0) -> None:
        self.datos = datos
        self.orden = orden
        self.pos = pos

    def alinear(self, n: int) -> None:
        self.pos += -self.pos % n

    def _tomar(self, n: int) -> bytes:
        if self.pos + n > len(self.datos):
            raise Error("org.freedesktop.DBus.Error.InvalidArgs", "mensaje corto")
        trozo = self.datos[self.pos:self.pos + n]
        self.pos += n
        return trozo

    def leer(self, firma: str) -> list[Any]:
        return [self._uno(t) for t in partir(firma)]

    def _uno(self, tipo: str) -> Any:
        c = tipo[0]
        self.alinear(ALINEACION[c])
        if c in _FIJOS:
            formato = self.orden + _FIJOS[c]
            return struct.unpack(formato, self._tomar(struct.calcsize(formato)))[0]
        if c == "b":
            return struct.unpack(self.orden + "I", self._tomar(4))[0] != 0
        if c in "so":
            n = struct.unpack(self.orden + "I", self._tomar(4))[0]
            texto = self._tomar(n + 1)[:-1]
            return texto.decode("utf-8", errors="replace")
        if c == "g":
            n = self._tomar(1)[0]
            return self._tomar(n + 1)[:-1].decode("ascii", errors="replace")
        if c == "v":
            firma = self._uno("g")
            return self._uno(firma)
        if c == "(":
            return tuple(self.leer(tipo[1:-1]))
        if c == "a":
            return self._array(tipo[1:])
        raise Error("org.freedesktop.DBus.Error.InvalidSignature", tipo)

    def _array(self, elemento: str) -> Any:
        n = struct.unpack(self.orden + "I", self._tomar(4))[0]
        if n > MAX_ARRAY:
            raise Error("org.freedesktop.DBus.Error.LimitsExceeded",
                        f"array de {n} bytes")
        self.alinear(ALINEACION[elemento[0]])
        fin = self.pos + n
        if elemento == "y":
            return self._tomar(n)
        if elemento[0] == "{":
            clave, dato = partir(elemento[1:-1])
            resultado = {}
            while self.pos < fin:
                self.alinear(8)
                k = self._uno(clave)
                resultado[k] = self._uno(dato)
            return resultado
        lista = []
        while self.pos < fin:
            lista.append(self._uno(elemento))
        return lista


# ---------------------------------------------------------------------------
# Mensajes («Message Protocol» → «Message Format»)
# ---------------------------------------------------------------------------

# Tipos de mensaje.
METHOD_CALL, METHOD_RETURN, ERROR, SIGNAL = 1, 2, 3, 4
# Flags.
NO_REPLY_EXPECTED = 0x1
# Campos de la cabecera: el código y el tipo de su valor.
PATH, INTERFACE, MEMBER, ERROR_NAME, REPLY_SERIAL = 1, 2, 3, 4, 5
DESTINATION, SENDER, SIGNATURE, UNIX_FDS = 6, 7, 8, 9
_TIPO_CAMPO = {PATH: "o", INTERFACE: "s", MEMBER: "s", ERROR_NAME: "s",
               REPLY_SERIAL: "u", DESTINATION: "s", SENDER: "s", SIGNATURE: "g",
               UNIX_FDS: "u"}
VERSION_PROTOCOLO = 1
# La parte fija de la cabecera: orden de bytes, tipo, flags, versión, longitud
# del cuerpo, serie y la longitud del array de campos (firma `yyyyuua(yv)`).
_FIJA = 16


@dataclass
class Mensaje:
    tipo: int
    serie: int = 0
    flags: int = 0
    campos: dict[int, Any] = field(default_factory=dict)
    cuerpo: list[Any] = field(default_factory=list)

    @property
    def firma(self) -> str:
        return self.campos.get(SIGNATURE, "")

    @property
    def miembro(self) -> str:
        return self.campos.get(MEMBER, "")

    @property
    def interfaz(self) -> str:
        return self.campos.get(INTERFACE, "")

    @property
    def ruta(self) -> str:
        return self.campos.get(PATH, "")

    def a_bytes(self) -> bytes:
        cuerpo = Escritor()
        if self.firma:
            cuerpo.escribir(self.firma, self.cuerpo)
        cab = Escritor()
        cab.escribir("yyyyuu", [ord("l"), self.tipo, self.flags, VERSION_PROTOCOLO,
                                len(cuerpo.buf), self.serie])
        cab.escribir("a(yv)", [[(codigo, Variante(_TIPO_CAMPO[codigo], valor))
                                for codigo, valor in sorted(self.campos.items())]])
        # «The length of the header must be a multiple of 8, allowing the body
        # to begin on an 8-byte boundary».
        cab.alinear(8)
        return bytes(cab.buf) + bytes(cuerpo.buf)


def longitud(datos: bytes) -> int | None:
    """Cuántos bytes ocupa el mensaje que empieza en `datos`, o None si todavía
    no ha llegado su parte fija."""
    if len(datos) < _FIJA:
        return None
    orden = {ord("l"): "<", ord("B"): ">"}.get(datos[0])
    if orden is None:
        raise Error("org.freedesktop.DBus.Error.InvalidArgs",
                    f"orden de bytes desconocido: {datos[0]!r}")
    cuerpo, _serie, campos = struct.unpack(orden + "III", datos[4:16])
    cabecera = _FIJA + campos
    total = cabecera + (-cabecera % 8) + cuerpo
    if total > MAX_MENSAJE:
        raise Error("org.freedesktop.DBus.Error.LimitsExceeded",
                    f"mensaje de {total} bytes")
    return total


def leer_mensaje(datos: bytes) -> Mensaje:
    """Un mensaje entero (`longitud()` bytes) convertido en `Mensaje`."""
    orden = "<" if datos[0] == ord("l") else ">"
    lector = Lector(datos, orden)
    _o, tipo, flags, version, _largo, serie = lector.leer("yyyyuu")
    if version != VERSION_PROTOCOLO:
        raise Error("org.freedesktop.DBus.Error.InvalidArgs",
                    f"versión de protocolo {version}")
    campos = {codigo: valor for codigo, valor in lector.leer("a(yv)")[0]}
    lector.alinear(8)
    m = Mensaje(tipo, serie, flags, campos)
    if m.firma:
        m.cuerpo = lector.leer(m.firma)
    return m


# ---------------------------------------------------------------------------
# Direcciones («Server Addresses», «Well-known Message Bus Instances»)
# ---------------------------------------------------------------------------

def _desescapar(texto: str) -> str:
    """Los valores de una dirección van con los bytes raros como %XX."""
    salida = bytearray()
    i = 0
    while i < len(texto):
        if texto[i] == "%" and i + 3 <= len(texto):
            try:
                salida.append(int(texto[i + 1:i + 3], 16))
                i += 3
                continue
            except ValueError:
                pass            # un % que no escapa nada: se deja tal cual
        salida += texto[i].encode("utf-8")
        i += 1
    return salida.decode("utf-8", errors="replace")


def destinos(direccion: str) -> list[str | bytes]:
    """A qué sockets se puede llamar con esa dirección, en orden.

    Una dirección son varias separadas por ';', cada una `transporte:clave=valor,…`.
    Solo se entiende `unix` (con `path`, `abstract` o `runtime=yes`): el bus de
    un escritorio Linux es eso. Un socket abstracto se devuelve como bytes con
    el nulo delante, que es como lo nombra Linux."""
    salida: list[str | bytes] = []
    for trozo in direccion.split(";"):
        transporte, _, resto = trozo.partition(":")
        if transporte != "unix":
            continue
        claves = {}
        for par in resto.split(","):
            k, _, v = par.partition("=")
            if k:
                claves[k] = _desescapar(v)
        if "path" in claves:
            salida.append(claves["path"])
        elif "abstract" in claves:
            salida.append(b"\0" + claves["abstract"].encode("utf-8"))
        elif claves.get("runtime") == "yes" and os.environ.get("XDG_RUNTIME_DIR"):
            salida.append(os.path.join(os.environ["XDG_RUNTIME_DIR"], "bus"))
    return salida


def direccion_sesion() -> str | None:
    """«The address of the session bus is … DBUS_SESSION_BUS_ADDRESS». Sin ella,
    la de los sistemas con systemd: `$XDG_RUNTIME_DIR/bus`."""
    direccion = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    if direccion:
        return direccion
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    return f"unix:path={runtime}/bus" if runtime else None


# «If DBUS_SYSTEM_BUS_ADDRESS is not set, … unix:path=/var/run/dbus/system_bus_socket».
SISTEMA_POR_DEFECTO = "unix:path=/var/run/dbus/system_bus_socket"


def direccion_sistema() -> str:
    return os.environ.get("DBUS_SYSTEM_BUS_ADDRESS") or SISTEMA_POR_DEFECTO


# ---------------------------------------------------------------------------
# La conexión
# ---------------------------------------------------------------------------

BUS = "org.freedesktop.DBus"
RUTA_BUS = "/org/freedesktop/DBus"
PROPIEDADES = "org.freedesktop.DBus.Properties"
ESPERA = 5.0            # segundos que se espera una respuesta, por defecto


class Conexion:
    """Una conexión autenticada a un bus, con su nombre único ya pedido."""

    def __init__(self, sock: socket.socket, uid: int | None = None) -> None:
        self.sock = sock
        self._serie = 0
        self._pendiente = b""
        self.senales: list[Mensaje] = []
        self.llamadas: list[Mensaje] = []        # llamadas que nos hacen a nosotros
        self._autenticar(os.getuid() if uid is None and hasattr(os, "getuid")
                         else (uid or 0))
        self.nombre = self.llamar(BUS, RUTA_BUS, BUS, "Hello")[0]

    # --- abrir -----------------------------------------------------------------

    @classmethod
    def abrir(cls, direccion: str, espera: float = ESPERA) -> "Conexion":
        ultimo: Exception | None = None
        for destino in destinos(direccion):
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(espera)
            try:
                sock.connect(destino)
                return cls(sock)
            except (OSError, Error) as e:
                sock.close()
                ultimo = e
        raise ultimo or Error("org.freedesktop.DBus.Error.BadAddress", direccion)

    @classmethod
    def sesion(cls) -> "Conexion":
        direccion = direccion_sesion()
        if not direccion:
            raise Error("org.freedesktop.DBus.Error.NoServer", "sin bus de sesión")
        return cls.abrir(direccion)

    @classmethod
    def sistema(cls) -> "Conexion":
        return cls.abrir(direccion_sistema())

    def cerrar(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self) -> "Conexion":
        return self

    def __exit__(self, *_exc) -> None:
        self.cerrar()

    # --- «Authentication Protocol» ---------------------------------------------

    def _linea(self) -> str:
        while b"\r\n" not in self._pendiente:
            trozo = self.sock.recv(4096)
            if not trozo:
                raise Error("org.freedesktop.DBus.Error.AuthFailed",
                            "el bus ha cerrado durante el saludo")
            self._pendiente += trozo
            if len(self._pendiente) > 16384:
                raise Error("org.freedesktop.DBus.Error.AuthFailed", "saludo enorme")
        linea, _, self._pendiente = self._pendiente.partition(b"\r\n")
        return linea.decode("ascii", errors="replace")

    def _autenticar(self, uid: int) -> None:
        """«The client must first send a single nul byte», y luego `AUTH EXTERNAL`
        con el uid en decimal escrito en hexadecimal ASCII. El servidor contesta
        `OK <guid>` y el cliente cierra con `BEGIN`; a partir de ahí, mensajes."""
        self.sock.sendall(b"\0")
        self.sock.sendall(b"AUTH EXTERNAL " + str(uid).encode("ascii").hex().encode("ascii")
                          + b"\r\n")
        respuesta = self._linea()
        if not respuesta.startswith("OK "):
            raise Error("org.freedesktop.DBus.Error.AuthFailed", respuesta)
        self.guid = respuesta[3:].strip()
        self.sock.sendall(b"BEGIN\r\n")

    # --- enviar y recibir --------------------------------------------------------

    def _siguiente_serie(self) -> int:
        # «The serial … must not be zero». Da la vuelta mucho antes de importar.
        self._serie = self._serie % 0xFFFFFFFF + 1
        return self._serie

    def enviar(self, m: Mensaje) -> int:
        m.serie = self._siguiente_serie()
        self.sock.sendall(m.a_bytes())
        return m.serie

    def _recibir(self, hasta: float) -> Mensaje | None:
        """El siguiente mensaje que llegue antes de `hasta` (monotónico), o None."""
        while True:
            total = longitud(self._pendiente)
            if total is not None and len(self._pendiente) >= total:
                datos, self._pendiente = self._pendiente[:total], self._pendiente[total:]
                return leer_mensaje(datos)
            queda = hasta - time.monotonic()
            if queda <= 0:
                return None
            listos, _, _ = select.select([self.sock], [], [], queda)
            if not listos:
                return None
            trozo = self.sock.recv(65536)
            if not trozo:
                raise Error("org.freedesktop.DBus.Error.Disconnected", "el bus ha cerrado")
            self._pendiente += trozo

    def llamar(self, destino: str | None, ruta: str, interfaz: str | None,
               metodo: str, firma: str = "", args: Iterable[Any] = (),
               espera: float = ESPERA) -> list[Any]:
        """Llama a un método y devuelve el cuerpo de la respuesta.

        Lanza `Error` con el nombre de error que mande el otro lado, o con
        `NoReply` si no contesta a tiempo. Lo que llegue entretanto (señales,
        llamadas a nosotros) se guarda, no se pierde."""
        campos = {PATH: ruta, MEMBER: metodo}
        if destino:
            campos[DESTINATION] = destino
        if interfaz:
            campos[INTERFACE] = interfaz
        if firma:
            campos[SIGNATURE] = firma
        serie = self.enviar(Mensaje(METHOD_CALL, campos=campos, cuerpo=list(args)))
        hasta = time.monotonic() + espera
        while True:
            m = self._recibir(hasta)
            if m is None:
                raise Error("org.freedesktop.DBus.Error.NoReply",
                            f"{interfaz}.{metodo} no contesta")
            if m.campos.get(REPLY_SERIAL) == serie:
                if m.tipo == ERROR:
                    texto = m.cuerpo[0] if m.cuerpo and isinstance(m.cuerpo[0], str) else ""
                    raise Error(m.campos.get(ERROR_NAME, "desconocido"), texto)
                return m.cuerpo
            self._guardar(m)

    def _guardar(self, m: Mensaje) -> None:
        if m.tipo == SIGNAL:
            self.senales.append(m)
        elif m.tipo == METHOD_CALL:
            self.llamadas.append(m)

    def propiedad(self, destino: str, ruta: str, interfaz: str, nombre: str,
                  espera: float = ESPERA) -> Any:
        """`org.freedesktop.DBus.Properties.Get`: el valor, ya desenvuelto."""
        return self.llamar(destino, ruta, PROPIEDADES, "Get", "ss",
                           [interfaz, nombre], espera)[0]

    def escuchar(self, regla: str) -> None:
        """Pide al bus las señales que casen con la regla («Match Rules»), p. ej.
        "type='signal',interface='org.freedesktop.login1.Manager'"."""
        self.llamar(BUS, RUTA_BUS, BUS, "AddMatch", "s", [regla])

    def senal(self, espera: float = 0.0) -> Mensaje | None:
        """La siguiente señal recibida, esperando como mucho `espera` segundos."""
        hasta = time.monotonic() + espera
        while not self.senales:
            m = self._recibir(hasta)
            if m is None:
                return None
            self._guardar(m)
        return self.senales.pop(0)

    def tiene_dueno(self, nombre: str) -> bool:
        """¿Hay alguien registrado con ese nombre en el bus? (`NameHasOwner`)."""
        return bool(self.llamar(BUS, RUTA_BUS, BUS, "NameHasOwner", "s", [nombre])[0])
