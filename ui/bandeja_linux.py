#!/usr/bin/env python3
"""
bandeja_linux.py — La bandeja del agente en Linux: StatusNotifierItem + dbusmenu.

Solo DIBUJA, como `ui/bandeja_windows.py`: qué icono, qué texto y qué menú lo
decide `ui/bandeja.py`, y lo que se elige en el menú son peticiones al agente
(`pedir(dict)`), las mismas que las del buzón. Nada de Tk ni de bibliotecas:
exporta dos objetos en el bus de sesión con `common/dbus.py`, y **sin probar en
un escritorio real** (ver
`docs/superpowers/pruebas/2026-09-25-equipo-pendiente-en-real.md`).

Dos especificaciones, citadas como `common/bisync.py` cita a rclone:

  * **StatusNotifierItem** (freedesktop.org, la que KDE propuso y usan Plasma,
    la extensión AppIndicator de GNOME, waybar…): el icono es un objeto
    `org.kde.StatusNotifierItem` en `/StatusNotifierItem`, bajo un nombre
    `org.kde.StatusNotifierItem-<pid>-<n>`, que se registra con
    `RegisterStatusNotifierItem` en `org.kde.StatusNotifierWatcher`. El dibujo
    viaja como `IconPixmap`, `a(iiay)` en ARGB32 de orden de red, que pinta
    `icons.pixmap_bandeja()`; los cambios se anuncian con `NewIcon`,
    `NewToolTip` y `NewStatus`. `ItemIsMenu` hace que el clic izquierdo
    también saque el menú, como en Windows; quien llame a `Activate` de todos
    modos recibe la entrada `defecto` (abrir la raíz del equipo).
  * **dbusmenu** (`com.canonical.dbusmenu`, versión 3): el menú es otro objeto,
    en `/MenuBar`, que el icono señala con su propiedad `Menu`. El anfitrión lo
    pide entero con `GetLayout` —cada entrada un `(ia{sv}av)` con su id, sus
    propiedades y sus hijos— y dice los clics con `Event(id, "clicked", …)`.
    Cada vez que el menú cambia se renumera y se emite `LayoutUpdated`; un
    clic en una entrada de la numeración anterior (el menú estaba abierto)
    vale lo que decía esa entrada. dbusmenu no tiene «entrada por defecto»:
    la negrita de Windows aquí no existe.

Lo que no es la bandeja pero vive en su hilo:

  * **Sin `StatusNotifierWatcher`** (GNOME sin la extensión AppIndicator, un
    escritorio mínimo) el icono no se puede poner: `puesta` es False, y hace
    sus veces el acceso «prdrive» del menú de aplicaciones (`agente.py
    abrir`). Se escucha `NameOwnerChanged` del watcher: si aparece después
    (el escritorio termina de arrancar después que el agente, o se activa la
    extensión), el icono se pone solo; si se reinicia, se vuelve a registrar.
    Es lo mismo que `TaskbarCreated` en Windows.
  * **`PrepareForSleep(false)`** de logind, en el bus del sistema: la vuelta
    de la suspensión pide `despertar`, como `WM_POWERBROADCAST` en Windows.

Un hilo propio con su conexión: el bus solo se toca desde él. El agente le
habla con `poner()` y `cerrar()`, que despiertan el hilo por un pipe.
"""

from __future__ import annotations

import os
import select
import threading
from typing import Any, Callable

from common import APP_NAME, dbus, equipo
from ui import bandeja, icons

SNI = "org.kde.StatusNotifierItem"
RUTA_SNI = "/StatusNotifierItem"
WATCHER = "org.kde.StatusNotifierWatcher"
RUTA_WATCHER = "/StatusNotifierWatcher"
DBUSMENU = "com.canonical.dbusmenu"
RUTA_MENU = "/MenuBar"
VERSION_DBUSMENU = 3

LOGIND = "org.freedesktop.login1"
LOGIND_MANAGER = "org.freedesktop.login1.Manager"

# `Category` y `Status` de la especificación. `Passive` escondería el icono en
# el desbordamiento de Plasma: nunca se usa. `NeedsAttention` con un aviso.
CATEGORIA = "ApplicationStatus"
ACTIVO, ATENCION = "Active", "NeedsAttention"

# Los tamaños que se mandan en `IconPixmap`: el anfitrión elige. Plasma usa 22
# a escala 1 y GNOME 16 × la escala; el resto, pantallas con más densidad.
TAMANOS = (16, 22, 24, 32, 48, 64)

ESPERA_ARRANQUE = 5.0
ESPERA_BUCLE = 30.0             # sin nada que hacer, el hilo se despierta igual

REGLA_WATCHER = (f"type='signal',sender='{dbus.BUS}',interface='{dbus.BUS}',"
                 f"member='NameOwnerChanged',arg0='{WATCHER}'")
REGLA_ANFITRION = (f"type='signal',interface='{WATCHER}',"
                   "member='StatusNotifierHostRegistered'")
REGLA_SUSPENDER = (f"type='signal',interface='{LOGIND_MANAGER}',"
                   "member='PrepareForSleep'")

V = dbus.Variante


def etiqueta(texto: str) -> str:
    """dbusmenu marca con `_` la tecla de acceso de la letra siguiente y pide
    `__` para un guion bajo de verdad: el de un nombre de unidad se dobla."""
    return texto.replace("_", "__")


_PIXMAPS: dict[str, list[tuple[int, int, bytes]]] = {}


def pixmaps(estado: str) -> list[tuple[int, int, bytes]]:
    """El `IconPixmap` de ese estado, `a(iiay)`: (ancho, alto, ARGB32) por
    tamaño. Se pinta la primera vez (poco más de 0,1 s) y se guarda."""
    if estado not in _PIXMAPS:
        _PIXMAPS[estado] = [(s, s, icons.pixmap_bandeja(estado, s)) for s in TAMANOS]
    return _PIXMAPS[estado]


# ---------------------------------------------------------------------------
# El menú como lo pide dbusmenu
# ---------------------------------------------------------------------------

class Menu:
    """El árbol de `bandeja.Entrada` numerado para dbusmenu.

    El 0 es la raíz. Cada vez que las entradas cambian se renumeran con ids
    NUEVOS y sube la revisión; la numeración anterior se guarda para el clic
    de alguien que tenía el menú abierto."""

    def __init__(self) -> None:
        self.revision = 0
        self.entradas: tuple[bandeja.Entrada, ...] = ()
        self.por_id: dict[int, bandeja.Entrada] = {}
        self.hijos: dict[int, list[int]] = {0: []}
        self._anterior: dict[int, bandeja.Entrada] = {}
        self._siguiente = 1

    def poner(self, entradas: tuple[bandeja.Entrada, ...]) -> bool:
        """True si ha cambiado (hay que emitir `LayoutUpdated`)."""
        if self.revision and entradas == self.entradas:
            return False
        self._anterior = self.por_id
        self.por_id, self.hijos = {}, {0: []}

        def numerar(lista, padre: int) -> None:
            for e in lista:
                n = self._siguiente
                # Un id es un `i`: da la vuelta antes de pasarse, sin el 0.
                self._siguiente = self._siguiente % 0x7FFFFFFE + 1
                self.por_id[n] = e
                self.hijos[padre].append(n)
                if e.hijos:
                    self.hijos[n] = []
                    numerar(e.hijos, n)
        numerar(entradas, 0)
        self.entradas = entradas
        self.revision += 1
        return True

    def existe(self, n: int) -> bool:
        return n == 0 or n in self.por_id

    def propiedades(self, n: int, nombres=()) -> dict[str, dbus.Variante]:
        """Las propiedades de una entrada. Las que valen lo de por defecto
        (`visible` sí, `enabled` sí, `type` «standard») no se mandan, como pide
        la especificación."""
        if n == 0:
            p = {"children-display": V("s", "submenu")}
        else:
            e = self.por_id[n]
            if e.separador:
                p = {"type": V("s", "separator")}
            else:
                p = {"label": V("s", etiqueta(e.texto))}
                if not e.activa:
                    p["enabled"] = V("b", False)
                if e.marcada is not None:
                    p["toggle-type"] = V("s", "checkmark")
                    p["toggle-state"] = V("i", 1 if e.marcada else 0)
                if e.hijos:
                    p["children-display"] = V("s", "submenu")
        if nombres:
            p = {k: v for k, v in p.items() if k in nombres}
        return p

    def disposicion(self, padre: int, profundidad: int, nombres=()) -> tuple:
        """`GetLayout`: el `(ia{sv}av)` de `padre`. Profundidad -1 es todo; 0,
        sin hijos; n, n niveles por debajo."""
        if not self.existe(padre):
            raise dbus.Error(dbus.E_ARGUMENTOS, f"no hay entrada {padre}")

        def nodo(n: int, queda: int) -> tuple:
            hijos = [] if queda == 0 else [
                V("(ia{sv}av)", nodo(h, queda - 1)) for h in self.hijos.get(n, [])]
            return (n, self.propiedades(n, nombres), hijos)
        return nodo(padre, profundidad)

    def pulsada(self, n: int) -> tuple[dict, ...]:
        """Las peticiones de la entrada `n`, de esta numeración o de la anterior.
        Nada si no se puede elegir (apagada, separador, submenú)."""
        e = self.por_id.get(n) or self._anterior.get(n)
        if e is None or e.separador or e.hijos or not e.activa:
            return ()
        return tuple(dict(p) for p in e.pide)


# ---------------------------------------------------------------------------
# La bandeja
# ---------------------------------------------------------------------------

class Bandeja:
    """El icono del agente en la bandeja de un escritorio Linux.

    `pedir(peticion)` se llama desde el hilo de la bandeja: tiene que ser barato
    y seguro entre hilos (el agente lo mete en una cola y se despierta).
    `conectar()` y `conectar_sistema()` abren los buses; los tests ponen unos
    falsos."""

    def __init__(self, pedir: Callable[[dict], None],
                 conectar: Callable[[], dbus.Conexion] | None = None,
                 conectar_sistema: Callable[[], dbus.Conexion] | None = None) -> None:
        self.pedir = pedir
        self._conectar = conectar or dbus.Conexion.sesion
        self._conectar_sistema = conectar_sistema or dbus.Conexion.sistema
        self.bus: dbus.Conexion | None = None
        self.sistema: dbus.Conexion | None = None
        self.nombre = f"{SNI}-{os.getpid()}-1"
        self.vista = bandeja.Vista(icons.BIEN, bandeja.tip("arrancando"), (), "Arrancando")
        self.menu = Menu()
        self.menu.poner(self.vista.menu)
        self._pendiente: bandeja.Vista | None = None
        self._cerrojo = threading.Lock()
        self._pipe = os.pipe()
        os.set_blocking(self._pipe[1], False)
        self._salir = False
        self._registrado = False
        self._anfitrion = False
        self._hilo: threading.Thread | None = None
        self._listo = threading.Event()

    # --- desde el hilo del agente --------------------------------------------------

    def arrancar(self) -> bool:
        """Conecta, exporta y se registra, en su hilo. True si hay bus de sesión:
        con él llegan la suspensión y el watcher que aparezca más tarde, aunque
        el icono todavía no esté (`puesta`). False sin bus: el agente sigue sin
        bandeja, y el acceso del menú hace sus veces."""
        self._hilo = threading.Thread(target=self._correr, name="bandeja", daemon=True)
        self._hilo.start()
        self._listo.wait(ESPERA_ARRANQUE)
        return self.bus is not None

    @property
    def puesta(self) -> bool:
        """¿Hay un icono en alguna bandeja? Registrado en un watcher que tiene
        un anfitrión que lo enseñe."""
        return self._registrado and self._anfitrion

    def poner(self, vista: bandeja.Vista) -> None:
        with self._cerrojo:
            self._pendiente = vista
        self._despertar()

    def cerrar(self) -> None:
        self._salir = True
        self._despertar()
        if self._hilo is not None and self._hilo is not threading.current_thread():
            self._hilo.join(ESPERA_ARRANQUE)

    def _despertar(self) -> None:
        try:
            os.write(self._pipe[1], b"!")
        except OSError:
            pass                # lleno: ya hay un despertar pendiente

    # --- en el hilo de la bandeja ----------------------------------------------------

    def _correr(self) -> None:
        try:
            try:
                self.bus = self._conectar()
                self.bus.exportar(RUTA_SNI, self._item())
                self.bus.exportar(RUTA_MENU, self._dbusmenu())
                if not self.bus.pedir_nombre(self.nombre):
                    raise dbus.Error(dbus.E_FALLO, f"{self.nombre} ya tiene dueño")
                self.bus.escuchar(REGLA_WATCHER)
                self.bus.escuchar(REGLA_ANFITRION)
                self._registrar()
            except (dbus.Error, OSError):
                if self.bus is not None:
                    self.bus.cerrar()
                self.bus = None
                return
            try:
                self.sistema = self._conectar_sistema()
                self.sistema.escuchar(REGLA_SUSPENDER)
            except (dbus.Error, OSError):
                if self.sistema is not None:
                    self.sistema.cerrar()
                self.sistema = None
        finally:
            self._listo.set()
        try:
            self._bucle()
        finally:
            for bus in (self.bus, self.sistema):
                if bus is not None:
                    bus.cerrar()
            self._registrado = False

    def _bucle(self) -> None:
        while not self._salir:
            try:
                self._atender_buses()
            except (dbus.Error, OSError):
                return                  # el bus de sesión se ha ido: fin de sesión
            fds: list[Any] = [self.bus, self._pipe[0]]
            if self.sistema is not None:
                fds.append(self.sistema)
            try:
                listos, _, _ = select.select(fds, [], [], ESPERA_BUCLE)
            except (OSError, ValueError):
                return
            if self._pipe[0] in listos:
                try:
                    os.read(self._pipe[0], 4096)
                except OSError:
                    pass
            if not self._salir:
                try:
                    self._poner_pendiente()
                except (dbus.Error, OSError):
                    return

    def _atender_buses(self) -> None:
        for s in self.bus.atender(0):
            self._senal(s)
        if self.sistema is not None:
            try:
                for s in self.sistema.atender(0):
                    self._senal(s)
            except (dbus.Error, OSError):
                self.sistema.cerrar()
                self.sistema = None     # sin él solo se pierde el aviso de suspender

    def _senal(self, s: dbus.Mensaje) -> None:
        if s.miembro == "NameOwnerChanged" and s.cuerpo[:1] == [WATCHER]:
            if len(s.cuerpo) >= 3 and s.cuerpo[2]:
                self._registrar()       # ha llegado, o se ha reiniciado
            else:
                self._registrado = False
        elif s.miembro == "StatusNotifierHostRegistered":
            self._anfitrion = True
        elif s.miembro == "PrepareForSleep" and s.cuerpo[:1] == [False]:
            self.pedir({"pide": equipo.PIDE_DESPERTAR})

    def _registrar(self) -> None:
        """`RegisterStatusNotifierItem` con nuestro nombre, si hay watcher. Si
        no hay anfitrión que enseñe los iconos, el registro vale igual y se
        espera a `StatusNotifierHostRegistered`."""
        self._registrado = False
        try:
            if not self.bus.tiene_dueno(WATCHER):
                return
            self.bus.llamar(WATCHER, RUTA_WATCHER, WATCHER, "RegisterStatusNotifierItem",
                            "s", [self.nombre])
        except dbus.Error:
            return
        self._registrado = True
        try:
            self._anfitrion = bool(self.bus.propiedad(WATCHER, RUTA_WATCHER, WATCHER,
                                                      "IsStatusNotifierHostRegistered"))
        except dbus.Error:
            self._anfitrion = True      # quien no lo dice, lo tendrá: se da por puesto

    def _poner_pendiente(self) -> None:
        with self._cerrojo:
            vista, self._pendiente = self._pendiente, None
        if vista is None:
            return
        antes, self.vista = self.vista, vista
        if vista.icono != antes.icono:
            self.bus.emitir(RUTA_SNI, SNI, "NewIcon")
            if self._estado(vista) != self._estado(antes):
                self.bus.emitir(RUTA_SNI, SNI, "NewStatus", "s", [self._estado(vista)])
        if (vista.tip, vista.frase) != (antes.tip, antes.frase):
            self.bus.emitir(RUTA_SNI, SNI, "NewToolTip")
        if self.menu.poner(vista.menu):
            self.bus.emitir(RUTA_MENU, DBUSMENU, "LayoutUpdated", "ui",
                            [self.menu.revision, 0])

    # --- lo que se exporta -----------------------------------------------------------

    @staticmethod
    def _estado(vista: bandeja.Vista) -> str:
        return ATENCION if vista.icono == icons.AVISO else ACTIVO

    def _tooltip(self) -> tuple:
        """`ToolTip`, `(sa(iiay)ss)`: icono (ninguno), título y descripción."""
        return ("", [], APP_NAME, self.vista.frase or self.vista.tip)

    def _por_defecto(self) -> None:
        e = self.vista.defecto()
        if e is not None:
            for p in e.pide:
                self.pedir(dict(p))

    def _item(self) -> dbus.Interfaz:
        nada = dbus.Metodo("ii", "", lambda x, y: None)
        return dbus.Interfaz(SNI, metodos={
            "ContextMenu": nada,
            "Activate": dbus.Metodo("ii", "", lambda x, y: self._por_defecto()),
            "SecondaryActivate": nada,
            "Scroll": dbus.Metodo("is", "", lambda delta, orientacion: None),
        }, propiedades={
            "Category": ("s", lambda: CATEGORIA),
            "Id": ("s", lambda: APP_NAME),
            "Title": ("s", lambda: APP_NAME),
            "Status": ("s", lambda: self._estado(self.vista)),
            "WindowId": ("i", lambda: 0),
            "IconName": ("s", lambda: ""),
            "IconPixmap": ("a(iiay)", lambda: pixmaps(self.vista.icono)),
            "OverlayIconName": ("s", lambda: ""),
            "OverlayIconPixmap": ("a(iiay)", lambda: []),
            "AttentionIconName": ("s", lambda: ""),
            "AttentionIconPixmap": ("a(iiay)", lambda: pixmaps(icons.AVISO)),
            "AttentionMovieName": ("s", lambda: ""),
            "ToolTip": ("(sa(iiay)ss)", self._tooltip),
            "ItemIsMenu": ("b", lambda: True),
            "Menu": ("o", lambda: RUTA_MENU),
            "IconThemePath": ("s", lambda: ""),
        }, senales={"NewTitle": "", "NewIcon": "", "NewAttentionIcon": "",
                    "NewOverlayIcon": "", "NewToolTip": "", "NewStatus": "s"})

    def _evento(self, n: int, tipo: str) -> bool:
        """Un evento del menú. Solo `clicked` hace algo. False si el id no existe."""
        if not self.menu.existe(n) and n not in self.menu._anterior:
            return False
        if tipo == "clicked":
            for p in self.menu.pulsada(n):
                self.pedir(p)
        return True

    def _dbusmenu(self) -> dbus.Interfaz:
        m = self.menu

        def grupo(ids, nombres):
            ids = list(ids) or [0, *m.por_id]
            return [[(n, m.propiedades(n, nombres)) for n in ids if m.existe(n)]]

        def propiedad(n, nombre):
            if not m.existe(n):
                raise dbus.Error(dbus.E_ARGUMENTOS, f"no hay entrada {n}")
            p = m.propiedades(n, (nombre,))
            if nombre not in p:
                raise dbus.Error(dbus.E_ARGUMENTOS, f"la entrada {n} no tiene {nombre}")
            return [p[nombre]]

        def eventos(lista):
            return [[n for n, tipo, _dato, _t in lista if not self._evento(n, tipo)]]

        return dbus.Interfaz(DBUSMENU, metodos={
            "GetLayout": dbus.Metodo("iias", "u(ia{sv}av)", lambda padre, prof, nombres: [
                m.revision, m.disposicion(padre, prof, nombres)]),
            "GetGroupProperties": dbus.Metodo("aias", "a(ia{sv})", grupo),
            "GetProperty": dbus.Metodo("is", "v", propiedad),
            "Event": dbus.Metodo("isvu", "", lambda n, tipo, dato, t: self._evento(n, tipo)
                                 and None),
            "EventGroup": dbus.Metodo("a(isvu)", "ai", eventos),
            "AboutToShow": dbus.Metodo("i", "b", lambda n: [False]),
            "AboutToShowGroup": dbus.Metodo("ai", "aiai", lambda ids: [
                [], [n for n in ids if not m.existe(n)]]),
        }, propiedades={
            "Version": ("u", lambda: VERSION_DBUSMENU),
            "TextDirection": ("s", lambda: "ltr"),
            "Status": ("s", lambda: "normal"),
            "IconThemePath": ("as", lambda: []),
        }, senales={"ItemsPropertiesUpdated": "a(ia{sv})a(ias)",
                    "LayoutUpdated": "ui", "ItemActivationRequested": "iu"})


def hay_bandeja(bus: dbus.Conexion) -> bool:
    """¿Tiene este escritorio dónde poner el icono? Lo pregunta el asistente."""
    return bus.tiene_dueno(WATCHER)
