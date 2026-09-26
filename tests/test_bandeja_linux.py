#!/usr/bin/env python3
"""
La bandeja de Linux (`ui/bandeja_linux.py`): StatusNotifierItem + dbusmenu.

Sin escritorio: el bus es `_bus_falso`, que hace de bus, de
`StatusNotifierWatcher` y de anfitrión que pregunta. Se comprueba:

  * el menú como lo pide dbusmenu (`GetLayout`, propiedades, casillas,
    submenús, separadores, `_` doblados) y que un cambio renumera y avisa con
    `LayoutUpdated`, sin que un clic tardío haga otra cosa;
  * que el icono se registra en el watcher con su nombre
    `org.kde.StatusNotifierItem-<pid>-1` y contesta lo que pregunta un
    anfitrión (`GetAll`, `IconPixmap` en ARGB32 de orden de red, `ToolTip`,
    `Menu`, introspección);
  * que un clic en el menú o `Activate` son las peticiones de la entrada, al
    agente; una apagada no pide nada;
  * la caída: sin watcher `puesta` es False (el acceso del menú hace sus
    veces), y si aparece después se registra solo; si se va, deja de estarlo;
  * la vuelta de la suspensión (`PrepareForSleep(false)` de logind) pide
    `despertar`; sin bus de sesión no hay bandeja; y `cerrar()` acaba el hilo.
"""

import os
import sys
import time

from _harness import Checks

import _bus_falso as B
from common import dbus, equipo
from ui import bandeja, bandeja_linux as bl, icons

c = Checks("La bandeja de Linux")


def esperar(cond, segundos=3.0):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


# --- el menú de dbusmenu, sin bus ---------------------------------------------------

E = bandeja.Entrada
ABRIR = E("Abrir mi_raíz", ({"pide": equipo.PIDE_ABRIR, "id": "r"},), defecto=True)
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


# --- en el bus: con watcher ------------------------------------------------------------

def bandeja_con(dueños=(bl.WATCHER,), sistema=None):
    pedidas: list[dict] = []
    buses = []

    def conectar():
        con, bus = B.conectar(dueños=dueños)
        buses.append(bus)
        return con

    def conectar_sistema():
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

# --- el watcher se va y vuelve (Plasma se reinicia) ----------------------------------------
bus.dueño(bl.WATCHER, "")
c("si el watcher se va, el icono ya no está", esperar(lambda: not b.puesta), True)
bus.dueño(bl.WATCHER, ":1.99")
c("  y al volver, se registra otra vez él solo",
  (esperar(lambda: b.puesta), bus.registrados), (True, [nombre, nombre]))

# --- la suspensión --------------------------------------------------------------------
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

# --- sin watcher: la caída al lanzador ------------------------------------------------------
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
    raise dbus.Error("org.freedesktop.DBus.Error.NoServer", "sin bus de sesión")


b = bl.Bandeja(lambda p: None, sin_bus)
c("sin bus de sesión, no hay bandeja", (b.arrancar(), b.puesta), (False, False))

con, bus = B.conectar(dueños=(bl.WATCHER,))
c("hay_bandeja(): pregunta por el watcher", bl.hay_bandeja(con), True)
con.cerrar()


# --- el agente la pone -----------------------------------------------------------------
import agente  # noqa: E402

pedidas_ag: list = []


class AgenteFalso:
    def pedir(self, p):
        pedidas_ag.append(p)


class VigiaFalso:
    despertado = 0

    def despertar(self, montajes=False):
        VigiaFalso.despertado += 1


diario: list = []
agente.diario = diario.append
agente.IS_WIN = False
real = bl.Bandeja


class SinWatcher(real):
    def __init__(self, pedir):
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
