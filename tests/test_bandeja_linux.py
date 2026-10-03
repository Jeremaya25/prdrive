#!/usr/bin/env python3
"""La bandeja de Linux (`ui/bandeja_linux.py`): StatusNotifierItem + dbusmenu.

Sin escritorio: el bus es `_bus_falso`, que hace de bus, de
`StatusNotifierWatcher` y de anfitrión que pregunta. Se comprueba:
- El menú como lo pide dbusmenu (`GetLayout`, propiedades, casillas, submenús,
  separadores, `_` doblados) y que un cambio renumera y avisa con
  `LayoutUpdated`, sin que un clic tardío haga otra cosa.
- Que el icono se registra en el watcher con su nombre
  `org.kde.StatusNotifierItem-<pid>-1` y contesta lo que pregunta un anfitrión
  (`GetAll`, `IconPixmap` en ARGB32 de orden de red, `ToolTip`, `Menu`,
  introspección).
- Que un clic en el menú o `Activate` son las peticiones de la entrada, al
  agente; una apagada no pide nada.
- La caída: sin watcher `puesta` es False (el acceso del menú hace sus veces)
  y, si aparece después, se registra solo; si se va, deja de estarlo.
- La vuelta de la suspensión (`PrepareForSleep(false)` de logind) pide
  `despertar`; sin bus de sesión no hay bandeja; y `cerrar()` acaba el hilo.
"""

import os
import struct
import sys
import time
import zlib

from _harness import Checks, tmpdir

import _bus_falso as B
from common import dbus, equipo
from ui import bandeja, bandeja_linux as bl, icons

c = Checks("La bandeja de Linux")


def esperar(cond, segundos=3.0):
    """Espera hasta `segundos` a que `cond()` sea cierta; devuelve si lo fue."""
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


# el menú de dbusmenu, sin bus

E = bandeja.Entrada
ABRIR = E("Abrir mi_raíz", ({"pide": equipo.PIDE_ABRIR, "id": "r"},), defecto=True,
          icono=bandeja.I_EXPLORAR)
MENU = (E("Al día", activa=False), bandeja.SEPARADOR, ABRIR,
        E("Pedir la contraseña al iniciar sesión",
          ({"pide": equipo.PIDE_AJUSTE, "clave": "pedir_al_iniciar", "valor": False},),
          marcada=True),
        E("Sincronizar ahora", hijos=(E("Todas", ({"pide": "pasada", "id": "a"},
                                                  {"pide": "pasada", "id": "b"})),
                                      E("A", ({"pide": "pasada", "id": "a"},)))))
m = bl.Menu()
c("un menú nuevo empieza en la revisión 1", (m.poner(MENU), m.revision), (True, 1))
c("  el mismo menú no la sube", (m.poner(MENU), m.revision), (False, 1))
rev, (raiz, props, hijos) = 1, m.disposicion(0, -1)
c("GetLayout(0, -1): la raíz es un submenú con las cinco entradas",
  (raiz, props, len(hijos)), (0, {"children-display": dbus.Variante("s", "submenu")}, 5))
ids = [h.valor[0] for h in hijos]
c("  la cabecera, apagada", m.propiedades(ids[0]),
  {"label": dbus.Variante("s", "Al día"), "enabled": dbus.Variante("b", False)})
c("  el separador, con su tipo", m.propiedades(ids[1]),
  {"type": dbus.Variante("s", "separator")})
c("  un _ del nombre se dobla (dbusmenu lo leería como tecla de acceso)",
  m.propiedades(ids[2])["label"].valor, "Abrir mi__raíz")
c("  su icono, por nombre del tema del escritorio (icon-name)",
  m.propiedades(ids[2])["icon-name"], dbus.Variante("s", "folder-open"))
c("  sin icono, sin icon-name", "icon-name" in m.propiedades(ids[3]), False)
c("  todos los iconos de la bandeja tienen nombre en el tema",
  sorted(set(bandeja.ICONOS) - set(bl.ICONOS_DEL_TEMA)), [])
c("  la casilla, marcada", (m.propiedades(ids[3])["toggle-type"].valor,
                            m.propiedades(ids[3])["toggle-state"].valor), ("checkmark", 1))
sub = hijos[4].valor
c("  el submenú lleva children-display y sus dos hijos",
  (sub[1]["children-display"].valor, [h.valor[1]["label"].valor for h in sub[2]]),
  ("submenu", ["Todas", "A"]))
c("GetLayout(0, 0): sin hijos", m.disposicion(0, 0)[2], [])
c("GetLayout(0, 1): un nivel, el submenú sin los suyos", m.disposicion(0, 1)[2][4].valor[2], [])
c("  pidiendo solo 'label'", m.disposicion(ids[0], 0, ["label"])[1],
  {"label": dbus.Variante("s", "Al día")})
try:
    m.disposicion(9999, -1)
    c("un padre que no existe es un error", False, True)
except dbus.Error as e:
    c("un padre que no existe es un error", e.nombre, dbus.E_ARGUMENTOS)
c("pulsar «Abrir» son sus peticiones", m.pulsada(ids[2]), ABRIR.pide)
c("  «Todas» son las dos pasadas", m.pulsada(sub[2][0].valor[0]),
  ({"pide": "pasada", "id": "a"}, {"pide": "pasada", "id": "b"}))
c("  una apagada, un separador o un submenú, nada",
  (m.pulsada(ids[0]), m.pulsada(ids[1]), m.pulsada(ids[4])), ((), (), ()))
viejo = ids[2]
c("un menú distinto renumera y sube la revisión",
  (m.poner(MENU[2:]), m.revision, viejo in m.por_id), (True, 2, False))
c("  un clic de quien tenía abierto el anterior vale lo que decía",
  m.pulsada(viejo), ABRIR.pide)

px = icons.pixmap_bandeja(icons.AVISO, 16)
c("IconPixmap: 4 bytes por píxel", len(px), 16 * 16 * 4)
c("  ARGB en orden de red: la esquina es transparente (alfa primero, a 0)", px[0], 0)
centro = (8 * 16 + 4) * 4
c("  y el campo de la marca es opaco y del color de la marca",
  (px[centro], px[centro + 1:centro + 4]), (255, bytes(icons._rgb(icons.CAMPO))))
c("pixmaps(): un (ancho, alto, datos) por tamaño",
  [(w, h, len(d)) for w, h, d in bl.pixmaps(icons.BIEN)],
  [(s, s, s * s * 4) for s in bl.TAMANOS])

# el icono de un dispositivo: icon-data, un PNG

def png_rgba(datos: bytes) -> tuple[int, list[tuple[int, int, int, int]]]:
    """Decodifica un PNG RGBA de 8 bits sin filtrar (como los de `icons._png`).

    Returns:
        `(lado, píxeles RGBA de arriba abajo)`.
    """
    assert datos.startswith(icons.FIRMA_PNG)
    pos, ancho, idat = 8, 0, b""
    while pos < len(datos):
        n, = struct.unpack(">I", datos[pos:pos + 4])
        tipo, cuerpo = datos[pos + 4:pos + 8], datos[pos + 8:pos + 8 + n]
        if tipo == b"IHDR":
            ancho = struct.unpack(">I", cuerpo[:4])[0]
        elif tipo == b"IDAT":
            idat += cuerpo
        pos += 12 + n
    crudo, pixeles = zlib.decompress(idat), []
    fila = 1 + ancho * 4
    for y in range(ancho):
        assert crudo[y * fila] == 0
        trozo = crudo[y * fila + 1:(y + 1) * fila]
        pixeles += [tuple(trozo[i:i + 4]) for i in range(0, len(trozo), 4)]
    return ancho, pixeles


def ico_de(*imagenes: tuple[int, bytes], tipo: int = 1, cuantas: int | None = None) -> bytes:
    """Monta un .ico con esas imágenes `(lado, bytes)`."""
    n = len(imagenes) if cuantas is None else cuantas
    cabeza, cuerpo = struct.pack("<HHH", 0, tipo, n), b""
    desde = 6 + 16 * len(imagenes)
    for lado, img in imagenes:
        cabeza += struct.pack("<BBBBHHII", lado % 256, lado % 256, 0, 0, 1, 32, len(img),
                              desde + len(cuerpo))
        cuerpo += img
    return cabeza + cuerpo


def dib(lado: int, bgra: bytes, mascara: bytes = b"", bits: int = 32) -> bytes:
    """Una imagen DIB de .ico: cabecera, píxeles de abajo arriba y máscara AND."""
    return struct.pack("<IiiHHIIiiII", 40, lado, 2 * lado, 1, bits, 0, 0, 0, 0, 0, 0) \
        + bgra + mascara


def esperado(capas_rgba) -> list[tuple[int, int, int, int]]:
    """Los píxeles RGBA que deja `icons._png` de unas capas ya compuestas."""
    return [(r, g, b, round(a * 255)) for fila in capas_rgba for r, g, b, a in fila]


DISPOSITIVO = E("PRDRIVE_1", hijos=(
    E("Configurar", ({"pide": equipo.PIDE_ABRIR, "id": "u"},), defecto=True,
      icono=bandeja.I_CONFIGURAR),), emblema=bandeja.Emblema(campo=icons.CAMPOS["verde"]))
m = bl.Menu()
m.poner((DISPOSITIVO,))
d_id = m.hijos[0][0]
props = m.propiedades(d_id)
c("un dispositivo es un submenú con su icono como icon-data (un PNG), no icon-name",
  (props["children-display"].valor, props["icon-data"].firma, "icon-name" in props,
   props["label"].valor),
  ("submenu", "ay", False, "PRDRIVE__1"))
c("  la marca en el color de su campo, a TAMANO_EMBLEMA px",
  props["icon-data"].valor, icons.png_marca(bl.TAMANO_EMBLEMA, icons.CAMPOS["verde"]))
c("  pulsar el propio submenú no hace nada: «Configurar» es la primera de dentro",
  (m.pulsada(d_id), m.pulsada(m.hijos[d_id][0])),
  ((), ({"pide": equipo.PIDE_ABRIR, "id": "u"},)))
c("  y «Configurar» lleva el engranaje del tema",
  m.propiedades(m.hijos[d_id][0])["icon-name"].valor, "preferences-system")

rgba32 = icons._capas_rgba(icons._capas_marca(32), 64.0, 32)
lado, pix = png_rgba(icons.png_de_ico(icons.ico((16, 32, 48)), 32))
c("png_de_ico: de un .ico de la marca, la imagen de 32 px (un DIB) como PNG, igual",
  (lado, pix == esperado(rgba32)), (32, True))
grande = icons.png_de_ico(icons.ico((16, 128)), 32)
c("  si la más cercana por arriba es un PNG, va tal cual",
  (grande.startswith(icons.FIRMA_PNG), struct.unpack(">I", grande[16:20])[0]),
  (True, 128))
c("  sin ninguna tan grande, la mayor", png_rgba(icons.png_de_ico(icons.ico((16, 32)), 256))[0],
  32)
rojo = bytes([0, 0, 255, 0]) * 4                # 2×2 BGRA sin alfa
mascara = bytes([0x40, 0, 0, 0, 0x00, 0, 0, 0])  # abajo: transparente el de la derecha
lado, pix = png_rgba(icons.png_de_ico(ico_de((2, dib(2, rojo, mascara))), 2))
c("  un DIB de 32 bits sin alfa toma la transparencia de su máscara AND",
  pix, [(255, 0, 0, 255), (255, 0, 0, 255), (255, 0, 0, 255), (255, 0, 0, 0)])
buenos = ico_de((16, dib(16, bytes([1, 2, 3, 255]) * 256)))
basura = os.urandom(200)
c("  lo que no es un icono, o miente, no da nada y no lanza", [icons.png_de_ico(x, 16) for x in (
    b"", b"\0" * 5, basura, buenos[:40], buenos[:-10],
    ico_de((16, dib(16, b"\0" * 1024)), tipo=2),
    ico_de((16, dib(16, b"\0" * 1024)), cuantas=0),
    ico_de((16, dib(16, b"\0" * 1024)), cuantas=1000),
    ico_de((16, dib(16, b"\0" * 768, bits=24))),
    ico_de((16, icons.FIRMA_PNG + b"\0\0\0\x0dIHDR" + struct.pack(">II", 99, 99) + b"\0" * 9)),
    buenos + b"\0" * icons.MAX_ICO)], [None] * 11)
desplazado = bytearray(buenos)
struct.pack_into("<I", desplazado, 6 + 12, len(buenos) + 5)   # la imagen fuera del fichero
c("  ni una imagen que apunta fuera del fichero", icons.png_de_ico(bytes(desplazado), 16), None)

carpeta = tmpdir("prdrive-emblemas-")
propio = carpeta / "icono-propio-0123abcd.ico"
propio.write_bytes(icons.ico((16, 32)))
c("png_emblema: un .ico propio que se entiende, su imagen",
  bl.png_emblema(bandeja.Emblema(ico=str(propio))), icons.png_de_ico(propio.read_bytes(), 32))
roto = carpeta / "icono-propio-roto.ico"
roto.write_bytes(b"no es un icono")
morado = bandeja.Emblema(campo=icons.CAMPOS["morado"])
c("  uno roto, uno que no está o una carpeta: la marca de su campo",
  [bl.png_emblema(bandeja.Emblema(campo=morado.campo, ico=str(r))) for r in
   (roto, carpeta / "no.ico", carpeta)], [icons.png_marca(bl.TAMANO_EMBLEMA, morado.campo)] * 3)
tope = icons.MAX_ICO
icons.MAX_ICO = 10
bl._EMBLEMAS.clear()
c("  y uno que pasa de MAX_ICO, también", bl.png_emblema(bandeja.Emblema(ico=str(propio))),
  icons.png_marca(bl.TAMANO_EMBLEMA))
icons.MAX_ICO = tope

if os.name == "nt":
    # Lo que sigue corre el hilo de la bandeja, que se despierta con un pipe
    # vigilado por select(), y en Windows select() solo admite sockets. En
    # Windows la bandeja es otra (`ui/bandeja_windows.py`, su propio test).
    print("  (saltado) la bandeja en el bus: solo en Linux")
    sys.exit(c.report())


# en el bus: con watcher

def bandeja_con(dueños=(bl.WATCHER,), sistema=None):
    """Arranca una bandeja sobre buses falsos.

    Returns:
        `(bandeja, arrancó, bus de sesión, peticiones recibidas)`.
    """
    pedidas: list[dict] = []
    buses = []

    def conectar():
        """Conecta con un bus de sesión falso y lo apunta."""
        con, bus = B.conectar(dueños=dueños)
        buses.append(bus)
        return con

    def conectar_sistema():
        """Conecta con un bus del sistema falso, si el test lo ofrece."""
        if sistema is None:
            raise OSError("sin bus del sistema")
        con, bus = B.conectar()
        sistema.append(bus)
        return con

    b = bl.Bandeja(pedidas.append, conectar, conectar_sistema)
    ok = b.arrancar()
    return b, ok, (buses[0] if buses else None), pedidas


sistema: list = []
b, ok, bus, pedidas = bandeja_con(sistema=sistema)
nombre = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
c("arranca con bus de sesión y se registra", (ok, b.puesta, bus.registrados),
  (True, True, [nombre]))
req = [x for x in bus.recibidos if x.miembro == "RequestName"][0]
c("  con el nombre de la especificación, sin cola", req.cuerpo,
  [nombre, dbus.NOMBRE_SIN_COLA])
c("  escucha al watcher (NameOwnerChanged) y a su anfitrión",
  [x.cuerpo[0] for x in bus.recibidos if x.miembro == "AddMatch"],
  [bl.REGLA_WATCHER, bl.REGLA_ANFITRION])

VISTA = bandeja.Vista(icons.AVISO, bandeja.tip("2 avisos"), MENU, "2 avisos")
b.poner(VISTA)
c("poner(): NewIcon, NewStatus y NewToolTip, y el menú nuevo con LayoutUpdated",
  esperar(lambda: all(bus.emitidas(s) for s in
                      ("NewIcon", "NewStatus", "NewToolTip", "LayoutUpdated"))), True)
c("  el estado nuevo va en la señal", bus.emitidas("NewStatus")[0].cuerpo, [bl.ATENCION])
c("  y LayoutUpdated lleva la revisión y la raíz",
  bus.emitidas("LayoutUpdated")[-1].cuerpo, [b.menu.revision, 0])
c("  cada señal, en su ruta e interfaz",
  (bus.emitidas("NewIcon")[0].ruta, bus.emitidas("NewIcon")[0].interfaz,
   bus.emitidas("LayoutUpdated")[0].ruta, bus.emitidas("LayoutUpdated")[0].interfaz),
  (bl.RUTA_SNI, bl.SNI, bl.RUTA_MENU, bl.DBUSMENU))

r = bus.llamar(bl.RUTA_SNI, dbus.PROPIEDADES, "GetAll", "s", [bl.SNI])
todo = r[1][0] if r and r[0] == "ok" else {}
c("GetAll del icono: lo que lee un anfitrión",
  {k: todo.get(k) for k in ("Id", "Category", "Status", "ItemIsMenu", "Menu", "IconName")},
  {"Id": "prdrive", "Category": "ApplicationStatus", "Status": bl.ATENCION,
   "ItemIsMenu": True, "Menu": bl.RUTA_MENU, "IconName": ""})
c("  el IconPixmap del estado, en todos los tamaños",
  [(w, h, bytes(d) == icons.pixmap_bandeja(icons.AVISO, w)) for w, h, d in todo.get("IconPixmap", [])],
  [(s, s, True) for s in bl.TAMANOS])
c("  el ToolTip: título y el estado", todo.get("ToolTip"), ("", [], "prdrive", "2 avisos"))
r = bus.llamar(bl.RUTA_SNI, dbus.PROPIEDADES, "Get", "ss", [bl.SNI, "Title"])
c("Get de una propiedad", r, ("ok", ["prdrive"]))
r = bus.llamar(bl.RUTA_SNI, dbus.PROPIEDADES, "Set", "ssv", [bl.SNI, "Title",
                                                              dbus.Variante("s", "x")])
c("  y Set, que no", r[:2], ("error", dbus.E_SOLO_LECTURA))
r = bus.llamar(bl.RUTA_MENU, dbus.PROPIEDADES, "GetAll", "s", [bl.DBUSMENU])
c("GetAll del menú: la versión 3 de dbusmenu", (r[1][0]["Version"], r[1][0]["Status"]),
  (3, "normal"))
r = bus.llamar(bl.RUTA_SNI, dbus.INTROSPECCION, "Introspect")
c("Introspect del icono nombra su interfaz, su método y su señal",
  all(t in r[1][0] for t in ('<interface name="org.kde.StatusNotifierItem">',
                             '<method name="Activate">', '<signal name="NewStatus">',
                             '<property name="IconPixmap" type="a(iiay)" access="read"/>')),
  True)
r = bus.llamar("/", dbus.INTROSPECCION, "Introspect")
c("  y la de / enseña los dos nodos", ('<node name="MenuBar"/>' in r[1][0],
                                        '<node name="StatusNotifierItem"/>' in r[1][0]),
  (True, True))

r = bus.llamar(bl.RUTA_MENU, bl.DBUSMENU, "GetLayout", "iias", [0, -1, []])
revision, arbol = r[1]
c("GetLayout por el bus: la revisión y el árbol entero",
  (revision, len(arbol[2]), arbol[2][2][1]["label"]), (b.menu.revision, 5, "Abrir mi__raíz"))
abrir_id = arbol[2][2][0]
bus.llamar(bl.RUTA_MENU, bl.DBUSMENU, "Event", "isvu",
           [abrir_id, "clicked", dbus.Variante("s", ""), 0])
c("un clic en «Abrir» le pide al agente abrir esa raíz", pedidas, list(ABRIR.pide))
pedidas.clear()
bus.llamar(bl.RUTA_MENU, bl.DBUSMENU, "Event", "isvu",
           [abrir_id, "hovered", dbus.Variante("s", ""), 0])
bus.llamar(bl.RUTA_MENU, bl.DBUSMENU, "Event", "isvu",
           [arbol[2][0][0], "clicked", dbus.Variante("s", ""), 0])
c("  pasar por encima, o pulsar una apagada, no pide nada", pedidas, [])
r = bus.llamar(bl.RUTA_MENU, bl.DBUSMENU, "EventGroup", "a(isvu)",
               [[(arbol[2][3][0], "clicked", dbus.Variante("s", ""), 0),
                 (99999, "clicked", dbus.Variante("s", ""), 0)]])
c("EventGroup: la casilla pide su ajuste, y dice qué id no existe",
  (pedidas, r), ([dict(MENU[3].pide[0])], ("ok", [[99999]])))
pedidas.clear()
r = bus.llamar(bl.RUTA_MENU, bl.DBUSMENU, "GetGroupProperties", "aias",
               [[abrir_id], ["label", "enabled"]])
c("GetGroupProperties", r, ("ok", [[(abrir_id, {"label": "Abrir mi__raíz"})]]))
c("AboutToShow: nada que actualizar",
  bus.llamar(bl.RUTA_MENU, bl.DBUSMENU, "AboutToShow", "i", [0]), ("ok", [False]))
c("GetProperty", bus.llamar(bl.RUTA_MENU, bl.DBUSMENU, "GetProperty", "is",
                            [abrir_id, "label"]), ("ok", ["Abrir mi__raíz"]))
bus.llamar(bl.RUTA_SNI, bl.SNI, "Activate", "ii", [10, 10])
c("Activate (quien no respeta ItemIsMenu): la entrada por defecto", pedidas,
  list(ABRIR.pide))
pedidas.clear()
c("un método que no existe es UnknownMethod",
  bus.llamar(bl.RUTA_SNI, bl.SNI, "Rompe")[:2], ("error", dbus.E_METODO))
c("  una ruta que no existe, UnknownObject",
  bus.llamar("/nada", bl.SNI, "Activate", "ii", [0, 0])[:2], ("error", dbus.E_OBJETO))
c("  y los argumentos que no son, InvalidArgs",
  bus.llamar(bl.RUTA_SNI, bl.SNI, "Activate", "s", ["x"])[:2], ("error", dbus.E_ARGUMENTOS))
c("Peer.Ping contesta", bus.llamar(bl.RUTA_SNI, dbus.PEER, "Ping"), ("ok", []))

# el watcher se va y vuelve (Plasma se reinicia)
bus.dueño(bl.WATCHER, "")
c("si el watcher se va, el icono ya no está", esperar(lambda: not b.puesta), True)
bus.dueño(bl.WATCHER, ":1.99")
c("  y al volver, se registra otra vez él solo",
  (esperar(lambda: b.puesta), bus.registrados), (True, [nombre, nombre]))

# la suspensión
sis = sistema[0]
c("el bus del sistema escucha PrepareForSleep",
  [x.cuerpo[0] for x in sis.recibidos if x.miembro == "AddMatch"], [bl.REGLA_SUSPENDER])
sis.senal("/org/freedesktop/login1", bl.LOGIND_MANAGER, "PrepareForSleep", "b", [True],
          remitente=bl.LOGIND)
sis.senal("/org/freedesktop/login1", bl.LOGIND_MANAGER, "PrepareForSleep", "b", [False],
          remitente=bl.LOGIND)
c("la vuelta de la suspensión pide despertar (la ida, nada)",
  esperar(lambda: pedidas == [{"pide": equipo.PIDE_DESPERTAR}]), True)
b.cerrar()
c("cerrar() acaba el hilo y cierra la conexión",
  (b._hilo.is_alive(), esperar(bus.cerrado.is_set)), (False, True))

# sin watcher: la caída al lanzador
b, ok, bus, pedidas = bandeja_con(dueños=())
c("sin StatusNotifierWatcher: hay bus pero no icono", (ok, b.puesta, bus.registrados),
  (True, False, []))
bus.anfitrion = False
bus.dueño(bl.WATCHER, ":1.50")
c("  aparece el watcher: se registra", esperar(lambda: bus.registrados == [nombre]), True)
c("  pero sin anfitrión que lo enseñe, todavía no está puesto", b.puesta, False)
bus.senal(bl.RUTA_WATCHER, bl.WATCHER, "StatusNotifierHostRegistered", remitente=":1.50")
c("  hasta que llega uno", esperar(lambda: b.puesta), True)
b.cerrar()


def sin_bus():
    """Falla como un equipo sin bus de sesión."""
    raise dbus.Error("org.freedesktop.DBus.Error.NoServer", "sin bus de sesión")


b = bl.Bandeja(lambda p: None, sin_bus)
c("sin bus de sesión, no hay bandeja", (b.arrancar(), b.puesta), (False, False))

con, bus = B.conectar(dueños=(bl.WATCHER,))
c("hay_bandeja(): pregunta por el watcher", bl.hay_bandeja(con), True)
con.cerrar()


# el agente la pone
import agente  # noqa: E402

pedidas_ag: list = []


class AgenteFalso:
    """Agente de mentira que apunta las peticiones que recibe."""
    def pedir(self, p):
        """Apunta la petición."""
        pedidas_ag.append(p)


class VigiaFalso:
    """Vigía de mentira que cuenta los despertares."""
    despertado = 0

    def despertar(self, montajes=False):
        """Cuenta un despertar."""
        VigiaFalso.despertado += 1


diario: list = []
agente.diario = diario.append
agente.IS_WIN = False
real = bl.Bandeja


class SinWatcher(real):
    """Bandeja a la que nadie contesta como `StatusNotifierWatcher`."""
    def __init__(self, pedir):
        """Arranca con un bus de sesión falso y sin bus del sistema."""
        super().__init__(pedir, lambda: B.conectar()[0], sin_bus)


bl.Bandeja = SinWatcher
puesta = agente.poner_bandeja(AgenteFalso(), VigiaFalso())
c("en Linux el agente pone la de StatusNotifierItem", isinstance(puesta, real), True)
c("  sin watcher, lo dice en el diario: el acceso del menú hace sus veces",
  any("no tiene bandeja" in d for d in diario), True)
puesta.pedir({"pide": equipo.PIDE_PAUSA})
c("  lo que se elige en su menú va al agente y lo despierta",
  (pedidas_ag, VigiaFalso.despertado), ([{"pide": equipo.PIDE_PAUSA}], 1))
puesta.cerrar()
bl.Bandeja = lambda pedir: real(pedir, sin_bus)
c("  sin bus de sesión, ninguna", agente.poner_bandeja(AgenteFalso(), VigiaFalso()), None)
bl.Bandeja = real

sys.exit(c.report())
