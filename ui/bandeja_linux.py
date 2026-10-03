#!/usr/bin/env python3
"""La bandeja del agente en Linux, con StatusNotifierItem y dbusmenu.

Solo DIBUJA, como `ui/bandeja_windows.py`: qué icono, qué texto y qué menú lo
decide `ui/bandeja.py`, y lo que se elige en el menú son peticiones al agente
(`pedir(dict)`), las mismas que las del buzón. Nada de Tk ni de bibliotecas:
exporta dos objetos en el bus de sesión con `common/dbus.py`, y **sin probar en
un escritorio real** (ver
`docs/superpowers/pruebas/2026-09-25-equipo-pendiente-en-real.md`).

Dos especificaciones, citadas como `common/bisync.py` cita a rclone:
- **StatusNotifierItem** (freedesktop.org, la que KDE propuso y usan Plasma, la
  extensión AppIndicator de GNOME, waybar…): el icono es un objeto
  `org.kde.StatusNotifierItem` en `/StatusNotifierItem`, bajo un nombre
  `org.kde.StatusNotifierItem-<pid>-<n>`, que se registra con
  `RegisterStatusNotifierItem` en `org.kde.StatusNotifierWatcher`. El dibujo
  viaja como `IconPixmap`, `a(iiay)` en ARGB32 de orden de red, que pinta
  `icons.pixmap_bandeja()`; los cambios se anuncian con `NewIcon`, `NewToolTip`
  y `NewStatus`. `ItemIsMenu` hace que el clic izquierdo también saque el menú,
  como en Windows; quien llame a `Activate` de todos modos recibe la entrada
  `defecto` (el «Configurar» del primer dispositivo, la raíz del equipo si la
  hay).
- **dbusmenu** (`com.canonical.dbusmenu`, versión 3): el menú es otro objeto,
  en `/MenuBar`, que el icono señala con su propiedad `Menu`. El anfitrión lo
  pide entero con `GetLayout` (cada entrada un `(ia{sv}av)` con su id, sus
  propiedades y sus hijos) y dice los clics con `Event(id, "clicked", …)`. Cada
  vez que el menú cambia se renumera y se emite `LayoutUpdated`; un clic en una
  entrada de la numeración anterior (el menú estaba abierto) vale lo que decía
  esa entrada. dbusmenu no tiene «entrada por defecto»: la negrita de Windows
  aquí no existe, y tampoco el doble clic que en Windows hace el «Configurar»
  de un desplegable. Un clic en una entrada con `children-display = submenu`
  abre el submenú y el anfitrión no lo manda como `clicked` (ni el importador
  de Qt de Plasma ni el `PopupSubMenuMenuItem` de la extensión AppIndicator de
  GNOME); si alguno lo mandara al abrirlo, hacer algo con él abriría la
  ventana al querer ver el submenú. Así que un submenú no hace nada al
  pulsarlo y «Configurar» es su primera entrada.
- **El icono de un dispositivo** va en `icon-data`, los bytes de un PNG
  (`png_emblema()`): la marca pintada en su color, o la imagen de su `.ico`
  propio que mejor sirve (`icons.png_de_ico()`, leído con límites). Las demás
  entradas llevan `icon-name`, un nombre del tema.

Lo que no es la bandeja pero vive en su hilo:
- **Sin `StatusNotifierWatcher`** (GNOME sin la extensión AppIndicator, un
  escritorio mínimo) el icono no se puede poner: `puesta` es `False` y hace sus
  veces el acceso «prdrive» del menú de aplicaciones (`agente.py abrir`). Se
  escucha `NameOwnerChanged` del watcher: si aparece después (el escritorio
  termina de arrancar después que el agente, o se activa la extensión), el
  icono se pone solo; si se reinicia, se vuelve a registrar. Es lo mismo que
  `TaskbarCreated` en Windows.
- **`PrepareForSleep(false)`** de logind, en el bus del sistema: la vuelta de
  la suspensión pide `despertar`, como `WM_POWERBROADCAST` en Windows.

Un hilo propio con su conexión: el bus solo se toca desde él. El agente le
habla con `poner()` y `cerrar()`, que despiertan el hilo por un pipe.
"""

from __future__ import annotations

import os
import select
import stat
import threading
from typing import Any, Callable

from common import APP_NAME, dbus, equipo
from ui import bandeja, icons

SNI = "org.kde.StatusNotifierItem"
"""La interfaz del icono, de la especificación StatusNotifierItem."""
RUTA_SNI = "/StatusNotifierItem"
WATCHER = "org.kde.StatusNotifierWatcher"
"""El nombre (y la interfaz) del watcher donde se registra el icono."""
RUTA_WATCHER = "/StatusNotifierWatcher"
DBUSMENU = "com.canonical.dbusmenu"
"""La interfaz del menú, de la especificación dbusmenu."""
RUTA_MENU = "/MenuBar"
VERSION_DBUSMENU = 3

LOGIND = "org.freedesktop.login1"
LOGIND_MANAGER = "org.freedesktop.login1.Manager"

CATEGORIA = "ApplicationStatus"
"""La `Category` de la especificación."""
ACTIVO, ATENCION = "Active", "NeedsAttention"
"""El `Status` de la especificación: `Active`, y `NeedsAttention` con un aviso.

`Passive` escondería el icono en el desbordamiento de Plasma: nunca se usa.
"""

TAMANOS = (16, 22, 24, 32, 48, 64)
"""Los tamaños que se mandan en `IconPixmap`: el anfitrión elige.

Plasma usa 22 a escala 1 y GNOME 16 × la escala; el resto, pantallas con más
densidad.
"""

ESPERA_ARRANQUE = 5.0
ESPERA_BUCLE = 30.0             # sin nada que hacer, el hilo se despierta igual

REGLA_WATCHER = (f"type='signal',sender='{dbus.BUS}',interface='{dbus.BUS}',"
                 f"member='NameOwnerChanged',arg0='{WATCHER}'")
"""La regla para oír cuándo el watcher llega, se va o se reinicia."""
REGLA_ANFITRION = (f"type='signal',interface='{WATCHER}',"
                   "member='StatusNotifierHostRegistered'")
"""La regla para oír cuándo se registra un anfitrión de iconos."""
REGLA_SUSPENDER = (f"type='signal',interface='{LOGIND_MANAGER}',"
                   "member='PrepareForSleep'")
"""La regla para oír la suspensión y su vuelta (logind, en el bus del sistema)."""

V = dbus.Variante
"""Atajo para crear variantes."""


def etiqueta(texto: str) -> str:
    """Devuelve el texto de una entrada con los `_` doblados.

    dbusmenu marca con `_` la tecla de acceso de la letra siguiente y pide `__`
    para un guion bajo de verdad: el de un nombre de unidad se dobla.
    """
    return texto.replace("_", "__")


_PIXMAPS: dict[str, list[tuple[int, int, bytes]]] = bandeja.CacheAcotada()
"""Los `IconPixmap` ya pintados, por estado (con tope: `bandeja.TOPE_CACHE`)."""


def pixmaps(estado: str) -> list[tuple[int, int, bytes]]:
    """Devuelve el `IconPixmap` de ese estado: `(ancho, alto, ARGB32)` por tamaño.

    `a(iiay)`. Se pinta la primera vez (poco más de 0,1 s) y se guarda.
    """
    if estado not in _PIXMAPS:
        _PIXMAPS[estado] = [(s, s, icons.pixmap_bandeja(estado, s)) for s in TAMANOS]
    return _PIXMAPS[estado]


ICONOS_DEL_TEMA = {
    bandeja.I_CONFIGURAR: "preferences-system",
    bandeja.I_EXPLORAR: "folder-open",
    bandeja.I_SINCRONIZAR: "view-refresh",
    bandeja.I_PAUSAR: "media-playback-pause",
    bandeja.I_REANUDAR: "media-playback-start",
    bandeja.I_BLOQUEAR: "system-lock-screen",
    bandeja.I_DESBLOQUEAR: "changes-allow",
    bandeja.I_ATENDER: "list-add",
    bandeja.I_ACTUALIZAR: "system-software-update",
    bandeja.I_CERRAR: "application-exit",
    bandeja.I_AVISO: "dialog-warning",
    bandeja.I_REINTENTAR: "view-refresh",
}
"""Los iconos de las entradas (`bandeja.I_*`) como nombres del tema del escritorio.

Es la propiedad `icon-name` de dbusmenu: el anfitrión los pinta a su tamaño y
en su color, también en modo oscuro, que un glifo pintado aquí no sabría. Casi
todos son de la *Icon Naming Specification* de freedesktop; `changes-allow` no,
pero lo traen Adwaita y Breeze. Un nombre que el tema no tenga deja la entrada
sin icono, nada más.
"""


TAMANO_EMBLEMA = 32
"""Lado, en píxeles, del PNG del icono de un dispositivo: el anfitrión lo escala.

Un menú pide 16 px a escala 1 y 32 a escala 2.
"""

_EMBLEMAS: dict[tuple, bytes] = bandeja.CacheAcotada()
"""Los `icon-data` ya pintados: la marca por color y cada `.ico` por ruta, tamaño y fecha.

Con tope (`bandeja.TOPE_CACHE`): cada `.ico` nuevo del usuario es una clave más.
"""


def _png_de_fichero(ruta: str) -> bytes | None:
    """Devuelve el PNG de un `.ico` propio, o `None` si no se puede leer o no se entiende.

    Solo un fichero normal de hasta `icons.MAX_ICO`, y no se lee más que eso
    aunque crezca entre medias. Se guarda por ruta, tamaño y fecha: el nombre
    ya cambia con el dibujo, así que no se relee de la unidad cada vez que el
    anfitrión pide el menú.
    """
    try:
        info = os.stat(ruta)
        if not stat.S_ISREG(info.st_mode) or info.st_size > icons.MAX_ICO:
            return None
        clave = ("ico", ruta, info.st_size, info.st_mtime_ns)
        if clave not in _EMBLEMAS:
            with open(ruta, "rb") as f:
                datos = f.read(icons.MAX_ICO + 1)
            _EMBLEMAS[clave] = icons.png_de_ico(datos, TAMANO_EMBLEMA) or b""
        return _EMBLEMAS[clave] or None
    except Exception:                                   # noqa: BLE001
        return None


def png_emblema(emblema: bandeja.Emblema) -> bytes:
    """Devuelve el `icon-data` de un dispositivo: su `.ico` si se entiende, si no la marca.

    Es la propiedad `icon-data` de dbusmenu, «PNG data of the icon». Nunca
    lanza: lo que no se pueda leer es la marca en el color de `emblema.campo`
    (o en el de prdrive, si ese tampoco se pudiera pintar).
    """
    if emblema.ico:
        datos = _png_de_fichero(emblema.ico)
        if datos:
            return datos
    for campo in (emblema.campo, icons.CAMPO):
        clave = ("marca", campo)
        try:
            if clave not in _EMBLEMAS:
                _EMBLEMAS[clave] = icons.png_marca(TAMANO_EMBLEMA, campo)
            return _EMBLEMAS[clave]
        except Exception:                               # noqa: BLE001
            continue
    return b""


class Menu:
    """El árbol de `bandeja.Entrada` numerado para dbusmenu.

    El 0 es la raíz. Cada vez que las entradas cambian se renumeran con ids
    NUEVOS y sube la revisión; la numeración anterior se guarda para el clic de
    alguien que tenía el menú abierto.
    """

    def __init__(self) -> None:
        """Crea un menú vacío, en la revisión 0."""
        self.revision = 0
        self.entradas: tuple[bandeja.Entrada, ...] = ()
        self.por_id: dict[int, bandeja.Entrada] = {}
        self.hijos: dict[int, list[int]] = {0: []}
        self._anterior: dict[int, bandeja.Entrada] = {}
        self._siguiente = 1

    def poner(self, entradas: tuple[bandeja.Entrada, ...]) -> bool:
        """Pone esas entradas y devuelve si han cambiado.

        Si han cambiado, hay que emitir `LayoutUpdated`.
        """
        if self.revision and entradas == self.entradas:
            return False
        self._anterior = self.por_id
        self.por_id, self.hijos = {}, {0: []}

        def numerar(lista, padre: int) -> None:
            """Numera las entradas de una lista y las de sus submenús."""
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
        """Indica si ese id existe en la numeración actual."""
        return n == 0 or n in self.por_id

    def propiedades(self, n: int, nombres=()) -> dict[str, dbus.Variante]:
        """Devuelve las propiedades de una entrada.

        Las que valen lo de por defecto (`visible` sí, `enabled` sí, `type`
        «standard») no se mandan, como pide la especificación.
        """
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
                if e.emblema is not None:
                    png = png_emblema(e.emblema)
                    if png:
                        p["icon-data"] = V("ay", png)
                elif e.icono in ICONOS_DEL_TEMA:
                    p["icon-name"] = V("s", ICONOS_DEL_TEMA[e.icono])
        if nombres:
            p = {k: v for k, v in p.items() if k in nombres}
        return p

    def disposicion(self, padre: int, profundidad: int, nombres=()) -> tuple:
        """Devuelve el `(ia{sv}av)` de `padre`, para `GetLayout`.

        Profundidad -1 es todo; 0, sin hijos; n, n niveles por debajo.
        """
        if not self.existe(padre):
            raise dbus.Error(dbus.E_ARGUMENTOS, f"no hay entrada {padre}")

        def nodo(n: int, queda: int) -> tuple:
            """Devuelve una entrada con sus hijos hasta la profundidad que queda."""
            hijos = [] if queda == 0 else [
                V("(ia{sv}av)", nodo(h, queda - 1)) for h in self.hijos.get(n, [])]
            return (n, self.propiedades(n, nombres), hijos)
        return nodo(padre, profundidad)

    def pulsada(self, n: int) -> tuple[dict, ...]:
        """Devuelve las peticiones de la entrada `n`.

        Son de esta numeración o de la anterior. No devuelve nada si no se
        puede elegir (apagada, separador, submenú).
        """
        e = self.por_id.get(n) or self._anterior.get(n)
        if e is None or e.separador or e.hijos or not e.activa:
            return ()
        return tuple(dict(p) for p in e.pide)


class Bandeja:
    """El icono del agente en la bandeja de un escritorio Linux.

    `pedir(peticion)` se llama desde el hilo de la bandeja: tiene que ser
    barato y seguro entre hilos (el agente lo mete en una cola y se despierta).
    `conectar()` y `conectar_sistema()` abren los buses; los tests ponen unos
    falsos.

    Args:
        pedir: Lo que se elige en el menú, como petición al agente.
        conectar: Abre el bus de sesión; por defecto, `dbus.Conexion.sesion`.
        conectar_sistema: Abre el bus del sistema; por defecto,
            `dbus.Conexion.sistema`.
    """

    def __init__(self, pedir: Callable[[dict], None],
                 conectar: Callable[[], dbus.Conexion] | None = None,
                 conectar_sistema: Callable[[], dbus.Conexion] | None = None) -> None:
        """Prepara la bandeja sin conectar todavía a ningún bus."""
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

    def arrancar(self) -> bool:
        """Conecta, exporta y se registra, en su hilo; devuelve si hay bus de sesión.

        Con él llegan la suspensión y el watcher que aparezca más tarde, aunque
        el icono todavía no esté (`puesta`). Sin bus, el agente sigue sin
        bandeja y el acceso del menú hace sus veces.
        """
        self._hilo = threading.Thread(target=self._correr, name="bandeja", daemon=True)
        self._hilo.start()
        self._listo.wait(ESPERA_ARRANQUE)
        return self.bus is not None

    @property
    def puesta(self) -> bool:
        """Indica si hay un icono en alguna bandeja.

        Es decir, si está registrado en un watcher que tiene un anfitrión que
        lo enseñe.
        """
        return self._registrado and self._anfitrion

    def poner(self, vista: bandeja.Vista) -> None:
        """Pide al hilo de la bandeja que enseñe esa vista."""
        with self._cerrojo:
            self._pendiente = vista
        self._despertar()

    def cerrar(self) -> None:
        """Pide al hilo que acabe y espera a que se vaya."""
        self._salir = True
        self._despertar()
        if self._hilo is not None and self._hilo is not threading.current_thread():
            self._hilo.join(ESPERA_ARRANQUE)

    def _despertar(self) -> None:
        """Despierta al hilo de la bandeja por el pipe."""
        try:
            os.write(self._pipe[1], b"!")
        except OSError:
            pass                # lleno: ya hay un despertar pendiente

    def _correr(self) -> None:
        """Es el hilo de la bandeja.

        Conecta a los buses, se registra y corre el bucle.
        """
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
        """Atiende los buses y las vistas pendientes.

        Sigue hasta que se cierre la bandeja o acabe la sesión.
        """
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
        """Atiende las señales de los dos buses."""
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
        """Hace lo que toca con una señal: el watcher, un anfitrión o la suspensión."""
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
        """Llama a `RegisterStatusNotifierItem` con nuestro nombre, si hay watcher.

        Si no hay anfitrión que enseñe los iconos, el registro vale igual y se
        espera a `StatusNotifierHostRegistered`.
        """
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
        """Aplica la vista pendiente y anuncia lo que ha cambiado en ella."""
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

    @staticmethod
    def _estado(vista: bandeja.Vista) -> str:
        """Devuelve el `Status` del icono para esa vista."""
        return ATENCION if vista.icono == icons.AVISO else ACTIVO

    def _tooltip(self) -> tuple:
        """Devuelve el `ToolTip`, de tipo `(sa(iiay)ss)`.

        Son un icono (ninguno), el título y la descripción.
        """
        return ("", [], APP_NAME, self.vista.frase or self.vista.tip)

    def _por_defecto(self) -> None:
        """Hace las peticiones de la entrada `defecto` («Configurar» del primer dispositivo)."""
        e = self.vista.defecto()
        if e is not None:
            for p in e.pide:
                self.pedir(dict(p))

    def _item(self) -> dbus.Interfaz:
        """Devuelve la interfaz `org.kde.StatusNotifierItem` que se exporta."""
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
        """Atiende un evento del menú y devuelve si el id existe.

        Solo `clicked` hace algo.
        """
        if not self.menu.existe(n) and n not in self.menu._anterior:
            return False
        if tipo == "clicked":
            for p in self.menu.pulsada(n):
                self.pedir(p)
        return True

    def _dbusmenu(self) -> dbus.Interfaz:
        """Devuelve la interfaz `com.canonical.dbusmenu` que se exporta."""
        m = self.menu

        def grupo(ids, nombres):
            """Devuelve las propiedades de un grupo de entradas.

            Si no se piden ids, son las de todas.
            """
            ids = list(ids) or [0, *m.por_id]
            return [[(n, m.propiedades(n, nombres)) for n in ids if m.existe(n)]]

        def propiedad(n, nombre):
            """Devuelve una propiedad de una entrada."""
            if not m.existe(n):
                raise dbus.Error(dbus.E_ARGUMENTOS, f"no hay entrada {n}")
            p = m.propiedades(n, (nombre,))
            if nombre not in p:
                raise dbus.Error(dbus.E_ARGUMENTOS, f"la entrada {n} no tiene {nombre}")
            return [p[nombre]]

        def eventos(lista):
            """Atiende un grupo de eventos y devuelve los ids que no existen."""
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
    """Indica si este escritorio tiene dónde poner el icono.

    Lo pregunta el asistente.
    """
    return bus.tiene_dueno(WATCHER)
