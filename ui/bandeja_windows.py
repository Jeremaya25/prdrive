#!/usr/bin/env python3
"""La bandeja del agente en Windows, con `Shell_NotifyIconW`.

Solo DIBUJA: qué icono, qué texto y qué menú lo decide `ui/bandeja.py`, y lo
que se elige en el menú son peticiones al agente (`pedir(dict)`), las mismas
que las del buzón. Nada de Tk: ctypes contra user32 y shell32, sin
dependencias, y **sin probar en un Windows real** (ver
`docs/superpowers/pruebas/2026-09-25-equipo-pendiente-en-real.md`).
- **Un hilo propio con su ventana y su bucle de mensajes.** Windows entrega los
  mensajes de una ventana al hilo que la creó y solo ese hilo puede destruirla.
  El agente sigue en el suyo; se hablan con `PostMessageW` (de aquí para allá:
  `poner()`, `globo()`, `cerrar()`) y con `pedir()` (de allá para aquí: lo que
  se elige en el menú).
- **Una ventana oculta de nivel superior, NO de solo mensajes.** El diseño
  decía «de solo mensajes», pero esas no reciben difusiones («Message-Only
  Windows», en la documentación de Win32) y dos de las que hacen falta lo son:
  `WM_DEVICECHANGE` con `DBT_DEVICEARRIVAL` de un volumen (VeraCrypt anuncia
  así sus montajes, `BroadcastDeviceChange()` en `Common/Dlgcode.c`) y
  `TaskbarCreated`, que llega cuando el Explorador se reinicia y hay que volver
  a poner el icono. Nunca se enseña.
- **`WM_DEVICECHANGE`** despierta al agente para que recorra las unidades en
  racha (`montajes()`), en vez de recorrerlas cada 5 s como penwatch. Los
  avisos de extracción de un handle (`DBT_DEVTYP_HANDLE`: el de la carpeta de
  una pareja vigilada, que `common/avisos_carpeta.py` registra en esta
  ventana) van a `dispositivo()` ANTES de contestar: con
  `DBT_DEVICEQUERYREMOVE` Windows espera a esa respuesta para seguir con la
  extracción, y el handle tiene que estar cerrado para entonces.
- **`WM_POWERBROADCAST`** con `PBT_APMRESUMEAUTOMATIC` (vuelta de la
  suspensión) pide `despertar`: la batería, la red y los remotos sin conexión
  se miran enseguida (sección 6 del diseño).
- **El menú** es `TrackPopupMenu` con `TPM_RETURNCMD`: devuelve el id elegido
  en vez de mandar `WM_COMMAND`. Antes, `SetForegroundWindow` a la ventana
  propia y después un `WM_NULL`: sin eso el menú no se cierra al pinchar fuera
  (es la receta de la documentación de `TrackPopupMenu`). Se abre con el botón
  derecho y con el izquierdo.
- **El menú es propio** (`MFT_OWNERDRAW`), con el aspecto del tablero «Bandeja
  del sistema» del rediseño: cada fila la mide `Api.medir()` y la pinta
  `Api.pintar()` (fondo, glifo o icono, texto y galón) con los colores del tema
  que tenga el sistema al abrirlo y la letra del programa; Windows sigue
  llevando el ratón, el teclado, los desplegables y el marco. Cómo es cada fila
  lo deciden `aspecto()` y `pintura()`, sin nada de Windows. Si no se puede
  preparar, es el menú de Windows: las entradas con `icono` llevan su glifo de
  `ui/icons.py` (`icons.pixeles_menu()`) como `hbmpItem`, un DIB de 32 bits con
  alfa premultiplicado, del color del texto del menú (`GetSysColor`), al tamaño
  del icono pequeño. Se crean al abrir el menú y se borran al cerrarlo.
- **El desplegable de cada dispositivo** lleva su icono a color
  (`bandeja.Emblema`, `pixeles_emblema()`): la marca pintada en su color o su
  `.ico` propio, que carga Windows (`LoadImageW` con `LR_LOADFROMFILE`, lo
  mismo que hace el Explorador con el `icon=` de su `autorun.inf`) y se pasa a
  un DIB con `DrawIconEx`. Un icono sin alfa sale transparente donde lo dice su
  máscara (`alfa_desde_mascara()`). Lo que no se pueda leer es la marca: el
  menú no falla por un icono.
- **El doble clic en un desplegable es su «Configurar»**: la entrada `defecto`
  de un submenú (`SetMenuDefaultItem`, en negrita) es la que Windows elige
  cuando se abre ese submenú con doble clic, y cierra el menú como si se
  hubiera elegido («Default Menu Items», en «About Menus» de la documentación
  de Win32), así que `TrackPopupMenu` devuelve su id. Un clic simple abre el
  submenú, como en todo Windows: hacer que ejecutara algo obligaría a
  interceptar el ratón dentro del menú y rompería la forma normal de abrirlo.
- **Los avisos** cuelgan del propio icono (`NIM_MODIFY` + `NIF_INFO`), que en
  Windows 10 y 11 salen como notificación del sistema: `common/avisos.GLOBO`
  apunta a `globo()` mientras la bandeja vive.
- **Los iconos** son los cinco `bandeja-<estado>.ico` que `ui/icons.py` repinta
  en la carpeta del agente, cargados con `LoadImageW` al tamaño del icono
  pequeño del sistema (`SM_CXSMICON`), con la densidad declarada
  (`theme.nitidez()`) para que ese tamaño sea el de verdad.

Todo lo que toca Windows está en `Api`; `Bandeja` habla con ella y los tests le
ponen una de mentira (`tests/test_bandeja_windows.py`).
"""

from __future__ import annotations

import os
import stat
import threading
from pathlib import Path
from typing import Any, Callable, NamedTuple

from common import APP_NAME, avisos, equipo
from ui import bandeja, icons

# Mensajes de ventana (winuser.h).
WM_NULL = 0x0000
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_CONTEXTMENU = 0x007B
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_POWERBROADCAST = 0x0218
WM_DEVICECHANGE = 0x0219
WM_APP = 0x8000
WM_ICONO = WM_APP + 1           # lo que manda el icono: clics, en `lParam`
WM_PONER = WM_APP + 2           # hay una vista nueva que enseñar
WM_GLOBO = WM_APP + 3           # hay un aviso que colgar del icono

PBT_APMRESUMESUSPEND = 0x0007   # vuelta de la suspensión, con alguien delante
PBT_APMRESUMEAUTOMATIC = 0x0012  # vuelta de la suspensión, siempre
DBT_DEVNODES_CHANGED = 0x0007
DBT_DEVICEARRIVAL = 0x8000
DBT_DEVICEQUERYREMOVE = 0x8001
DBT_DEVICEQUERYREMOVEFAILED = 0x8002
DBT_DEVICEREMOVEPENDING = 0x8003
DBT_DEVICEREMOVECOMPLETE = 0x8004
DBT_DEVTYP_HANDLE = 6
AVISOS_DE_HANDLE = (DBT_DEVICEQUERYREMOVE, DBT_DEVICEQUERYREMOVEFAILED,
                    DBT_DEVICEREMOVEPENDING, DBT_DEVICEREMOVECOMPLETE)
"""Los avisos de extracción que llegan por cada handle registrado (dbt.h)."""

# Shell_NotifyIconW (shellapi.h).
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_INFO, NIIF_WARNING = 0x1, 0x2
ID_ICONO = 1

# Menús.
MF_STRING, MF_GRAYED, MF_CHECKED, MF_POPUP, MF_SEPARATOR = 0x0, 0x1, 0x8, 0x10, 0x800
MIIM_BITMAP, MIIM_DATA, MIIM_FTYPE = 0x80, 0x20, 0x100
MFT_OWNERDRAW, MFT_SEPARATOR = 0x100, 0x800
MIM_BACKGROUND, MIM_APPLYTOSUBMENUS = 0x2, 0x80000000
WM_DRAWITEM, WM_MEASUREITEM = 0x002B, 0x002C
ODT_MENU = 1
ODS_SELECTED, ODS_GRAYED, ODS_DISABLED = 0x1, 0x2, 0x4
COLOR_MENUTEXT = 7

# Lo que pinta las filas del menú (wingdi.h, winuser.h).
LOGPIXELSY = 90
FW_NORMAL, FW_BOLD = 400, 700
DEFAULT_CHARSET, CLEARTYPE_QUALITY, TRANSPARENT = 1, 5, 1
DT_VCENTER, DT_SINGLELINE, DT_CALCRECT, DT_NOPREFIX = 0x4, 0x20, 0x400, 0x800
DT_END_ELLIPSIS = 0x8000
AC_SRC_OVER, AC_SRC_ALPHA = 0x0, 0x1
SM_CXSMICON = 49
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
DI_MASK, DI_IMAGE, DI_NORMAL = 0x1, 0x2, 0x3
TPM_RIGHTBUTTON, TPM_NONOTIFY, TPM_RETURNCMD = 0x2, 0x80, 0x100
TPM_RIGHTALIGN, TPM_BOTTOMALIGN = 0x8, 0x20
PRIMER_ID = 100
"""El primer id de las entradas del menú: los que devuelve `TrackPopupMenu`."""

ESPERA_ARRANQUE = 5.0
"""Segundos que espera `arrancar()` a saber si hay ventana."""
ESPERA_GLOBO = 2.0
"""Segundos que espera `globo()` a que Windows acepte el aviso."""


def texto_menu(texto: str) -> str:
    """Devuelve el texto de una entrada con los `&` doblados.

    Un `&` en un menú marca la tecla de acceso de la letra siguiente: el de un
    nombre de unidad se dobla para que salga tal cual.
    """
    return texto.replace("&", "&&")


def numerar(menu: tuple[bandeja.Entrada, ...], primero: int = PRIMER_ID
            ) -> dict[int, bandeja.Entrada]:
    """Devuelve un id por entrada que se puede elegir, en el orden del árbol.

    No lo llevan los separadores ni los submenús. Es lo que devuelve
    `TrackPopupMenu`.
    """
    ids: dict[int, bandeja.Entrada] = {}

    def recorrer(entradas) -> None:
        """Numera las entradas y las de los submenús, en orden."""
        for e in entradas:
            if e.separador:
                continue
            if e.hijos:
                recorrer(e.hijos)
            else:
                ids[primero + len(ids)] = e
    recorrer(menu)
    return ids


def alfa_desde_mascara(color: bytes, mascara: bytes) -> bytes:
    """Devuelve el dibujo de un icono sin alfa con la transparencia de su máscara.

    Es lo que hace falta con un `.ico` de 24 bits o menos: `DrawIconEx` con
    `DI_NORMAL` lo pinta con la máscara AND (operaciones de bits que no tocan
    el alfa), así que en un DIB de 32 bits vacío queda todo a alfa 0, que en un
    menú es invisible. Con `DI_MASK` sobre otro DIB vacío la máscara sale negra
    donde el icono es opaco y blanca donde es transparente (el color de texto y
    el de fondo por defecto del DC).

    Args:
        color: El dibujo con `DI_NORMAL`, BGRA.
        mascara: La máscara con `DI_MASK`, BGRA, del mismo tamaño.

    Returns:
        BGRA con alfa 255 donde la máscara es negra y todo a cero donde no.
    """
    salida = bytearray(len(color))
    for i in range(0, min(len(color), len(mascara)) - 3, 4):
        if not any(mascara[i:i + 3]):
            salida[i:i + 3] = color[i:i + 3]
            salida[i + 3] = 255
    return bytes(salida)


def pixeles_emblema(emblema: bandeja.Emblema, lado: int,
                    de_ico: Callable[[str, int], bytes | None]) -> bytes:
    """Devuelve el icono de un dispositivo como imagen de su entrada de menú.

    Es su `.ico` propio si es un fichero que cabe en `icons.MAX_ICO` y `de_ico`
    lo pinta; si no, o si algo falla, la marca en el color de `emblema.campo`.
    Nunca lanza: el menú no se queda sin abrir por un icono.

    Args:
        emblema: Lo que decide `ui/bandeja.py`.
        lado: El tamaño del icono pequeño del sistema, en píxeles.
        de_ico: Pinta un `.ico` a `lado` × `lado` (`Api._pixeles_ico()`):
            BGRA premultiplicado de arriba abajo, o `None`.

    Returns:
        `lado` × `lado` × 4 bytes, BGRA premultiplicado de arriba abajo.
    """
    if emblema.ico:
        try:
            info = os.stat(emblema.ico)
            if stat.S_ISREG(info.st_mode) and info.st_size <= icons.MAX_ICO:
                datos = de_ico(emblema.ico, lado)
                if datos and len(datos) == lado * lado * 4:
                    return datos
        except Exception:                               # noqa: BLE001
            pass
    try:
        return icons.pixeles_marca(lado, emblema.campo)
    except Exception:                                   # noqa: BLE001
        return icons.pixeles_marca(lado)


class Aspecto(NamedTuple):
    """Cómo se pinta el menú: el tablero «Bandeja del sistema» del rediseño.

    Los colores son `#RRGGBB` del tema que tenga el sistema al abrir el menú;
    las medidas, las del diseño en píxeles a la densidad de la pantalla.

    Args:
        fondo: El del menú y de cada fila (`surface`).
        elegida: El de la fila bajo el ratón o con su desplegable abierto
            (`accent-soft`).
        tinta: El texto y los glifos (`ink`).
        apagada: Lo que no se puede elegir (`disabled`).
        tenue: El galón de un desplegable (`ink-3`).
        linea: El separador (`line-soft`).
        alto: El de una fila (`size-control`, 34).
        alto_separador: El del separador con su aire (1 + 4 + 4).
        grosor: El de la línea del separador.
        margen: El relleno de cada lado (`space-4`, 16).
        hueco: Entre el icono y el texto (`space-3`, 12).
        icono: Un glifo (`size-icon`, 16).
        emblema: El icono de un dispositivo (la marca pequeña, 20); es también
            el ancho de la columna de iconos, para que los textos se alineen.
        galon: El galón de un desplegable (12).
        letra: El alto de la letra (`text-body`, 13,5).
    """

    fondo: str
    elegida: str
    tinta: str
    apagada: str
    tenue: str
    linea: str
    alto: int
    alto_separador: int
    grosor: int
    margen: int
    hueco: int
    icono: int
    emblema: int
    galon: int
    letra: int


def aspecto(oscuro: bool, ppp: int = 96) -> Aspecto:
    """Devuelve el aspecto del menú con el tema del sistema y a la densidad `ppp`."""
    from ui import theme
    paleta = theme.OSCURO if oscuro else theme.CLARO

    def px(diseno: float) -> int:
        """Una medida del diseño (a 96 ppp) en píxeles de esta pantalla."""
        return max(1, round(diseno * (ppp or 96) / 96))

    return Aspecto(fondo=paleta["SUPERFICIE"], elegida=paleta["ACENTO_SUAVE"],
                   tinta=paleta["TINTA"], apagada=paleta["APAGADO"],
                   tenue=paleta["TINTA3"], linea=paleta["LINEA_SUAVE"],
                   alto=px(34), alto_separador=px(1) + 2 * px(4), grosor=px(1),
                   margen=px(16), hueco=px(12), icono=px(16), emblema=px(20),
                   galon=px(12), letra=px(13.5))


class Pintura(NamedTuple):
    """Lo que lleva una fila del menú al pintarla, sin nada de Windows.

    Args:
        fondo: El color de la fila.
        tinta: El del texto y del glifo.
        negrita: Si el texto va en negrita: la entrada por defecto.
        glifo: El de `icons.GLIFOS` que lleva delante, o `None`.
        emblema: El icono de un dispositivo, o `None`.
        lado: El tamaño del icono, en píxeles.
        x_icono: Dónde empieza el icono, desde el borde izquierdo de la fila.
        x_texto: Dónde empieza el texto.
        galon: Si lleva el galón de un desplegable a la derecha.
        apagada: Si no se puede elegir.
    """

    fondo: str
    tinta: str
    negrita: bool
    glifo: str | None
    emblema: bandeja.Emblema | None
    lado: int
    x_icono: int
    x_texto: int
    galon: bool
    apagada: bool


def pintura(entrada: bandeja.Entrada, estado: int, a: Aspecto) -> Pintura:
    """Decide cómo se pinta una fila según su entrada y su estado (`ODS_*`).

    La elegida va sobre `elegida` (en el tablero, la del desplegable
    abierto); una que no se puede elegir, en `apagada` y sin resaltar. Una
    entrada marcada lleva el visto como icono, como «Pedir la contraseña al
    iniciar» en el tablero. Sin icono, el texto empieza en el margen.
    """
    apagada = not entrada.activa or bool(estado & (ODS_GRAYED | ODS_DISABLED))
    elegida = bool(estado & ODS_SELECTED) and not apagada
    glifo = "ok" if entrada.marcada else (
        entrada.icono if entrada.icono in icons.GLIFOS else None)
    emblema = entrada.emblema
    lado = a.emblema if emblema is not None else a.icono
    con_icono = emblema is not None or glifo is not None
    return Pintura(fondo=a.elegida if elegida else a.fondo,
                   tinta=a.apagada if apagada else a.tinta,
                   negrita=entrada.defecto,
                   glifo=None if emblema is not None else glifo,
                   emblema=emblema, lado=lado,
                   x_icono=a.margen + (a.emblema - lado) // 2,
                   x_texto=a.margen + (a.emblema + a.hueco if con_icono else 0),
                   galon=bool(entrada.hijos), apagada=apagada)


def ancho_fila(p: Pintura, ancho_texto: int, a: Aspecto) -> int:
    """Devuelve lo que mide de ancho una fila con un texto de `ancho_texto` píxeles."""
    return p.x_texto + ancho_texto + (a.hueco + a.galon if p.galon else 0) + a.margen


def colorref(color: str) -> int:
    """Devuelve un `#RRGGBB` como `COLORREF` de Windows (`0x00BBGGRR`)."""
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    return r | (g << 8) | (b << 16)


def estructuras(ct: Any, wt: Any) -> tuple[Any, Any]:
    """Devuelve las estructuras `MENUITEMINFOW` y `BITMAPINFOHEADER`.

    Están fuera de `Api` para que los tests monten una con bibliotecas de
    mentira.
    """

    class MENUITEMINFOW(ct.Structure):
        """Estructura `MENUITEMINFOW` de winuser.h."""
        _fields_ = [("cbSize", wt.UINT), ("fMask", wt.UINT),
                    ("fType", wt.UINT), ("fState", wt.UINT),
                    ("wID", wt.UINT), ("hSubMenu", wt.HMENU),
                    ("hbmpChecked", wt.HBITMAP),
                    ("hbmpUnchecked", wt.HBITMAP),
                    ("dwItemData", ct.c_size_t), ("dwTypeData", wt.LPWSTR),
                    ("cch", wt.UINT), ("hbmpItem", wt.HBITMAP)]

    class BITMAPINFOHEADER(ct.Structure):
        """Estructura `BITMAPINFOHEADER` de wingdi.h."""
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG),
                    ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                    ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                    ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                    ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                    ("biClrImportant", wt.DWORD)]

    return MENUITEMINFOW, BITMAPINFOHEADER


def estructuras_dibujo(ct: Any, wt: Any) -> dict[str, Any]:
    """Devuelve las estructuras con las que se pinta un menú propio (winuser.h, wingdi.h).

    `MEASUREITEMSTRUCT` y `DRAWITEMSTRUCT` (lo que llega con `WM_MEASUREITEM`
    y `WM_DRAWITEM`), `MENUINFO` y `BLENDFUNCTION`, por nombre.
    """

    class MEASUREITEMSTRUCT(ct.Structure):
        """Estructura `MEASUREITEMSTRUCT` de winuser.h."""
        _fields_ = [("CtlType", wt.UINT), ("CtlID", wt.UINT), ("itemID", wt.UINT),
                    ("itemWidth", wt.UINT), ("itemHeight", wt.UINT),
                    ("itemData", ct.c_size_t)]

    class DRAWITEMSTRUCT(ct.Structure):
        """Estructura `DRAWITEMSTRUCT` de winuser.h."""
        _fields_ = [("CtlType", wt.UINT), ("CtlID", wt.UINT), ("itemID", wt.UINT),
                    ("itemAction", wt.UINT), ("itemState", wt.UINT),
                    ("hwndItem", wt.HWND), ("hDC", wt.HDC), ("rcItem", wt.RECT),
                    ("itemData", ct.c_size_t)]

    class MENUINFO(ct.Structure):
        """Estructura `MENUINFO` de winuser.h."""
        _fields_ = [("cbSize", wt.DWORD), ("fMask", wt.DWORD), ("dwStyle", wt.DWORD),
                    ("cyMax", wt.UINT), ("hbrBack", wt.HBRUSH),
                    ("dwContextHelpID", wt.DWORD), ("dwMenuData", ct.c_size_t)]

    class BLENDFUNCTION(ct.Structure):
        """Estructura `BLENDFUNCTION` de wingdi.h."""
        _fields_ = [("BlendOp", ct.c_ubyte), ("BlendFlags", ct.c_ubyte),
                    ("SourceConstantAlpha", ct.c_ubyte), ("AlphaFormat", ct.c_ubyte)]

    return {"MEASUREITEMSTRUCT": MEASUREITEMSTRUCT, "DRAWITEMSTRUCT": DRAWITEMSTRUCT,
            "MENUINFO": MENUINFO, "BLENDFUNCTION": BLENDFUNCTION}


class Dibujo:
    """Lo que hace falta mientras un menú propio está abierto.

    Args:
        aspecto: Colores y medidas (`aspecto()`).
        letras: La letra de las filas, normal (`False`) y en negrita (`True`).
        pincel: El del fondo del menú.

    Attributes:
        filas: Las entradas del menú: su posición es el `itemData` de cada fila.
    """

    def __init__(self, aspecto: Aspecto, letras: dict[bool, Any], pincel: Any) -> None:
        """Guarda lo preparado; las filas se añaden al construir el menú."""
        self.aspecto = aspecto
        self.letras = letras
        self.pincel = pincel
        self.filas: list[bandeja.Entrada] = []


class Bandeja:
    """El icono de la bandeja del agente.

    `pedir(peticion)` y `montajes()` se llaman desde el hilo de la bandeja:
    tienen que ser baratos y seguros entre hilos (el agente los mete en una
    cola y se despierta).

    Args:
        carpeta_iconos: Donde están los `bandeja-<estado>.ico`.
        pedir: Lo que se elige en el menú, como petición al agente.
        montajes: Avisa de que ha cambiado algún volumen.
        api: Las llamadas a Windows; por defecto, `Api`. Los tests le ponen una
            de mentira.

    Attributes:
        dispositivo: Quien atiende los avisos de extracción de un handle
            (`avisos_carpeta.ReadDirectoryChanges.dispositivo`), si hay alguien:
            se le llama con el aviso y el handle, desde el hilo de la bandeja y
            antes de contestar a Windows.
    """

    def __init__(self, carpeta_iconos: Path, pedir: Callable[[dict], None],
                 montajes: Callable[[], None], api: Any = None) -> None:
        """Prepara la bandeja sin crear todavía la ventana."""
        self.carpeta = Path(carpeta_iconos)
        self.pedir = pedir
        self.montajes = montajes
        self.api = api
        self.dispositivo: Callable[[int, int], None] | None = None
        self.hwnd = None
        self.vista = bandeja.Vista(icons.BIEN, bandeja.tip("arrancando"), ())
        self._pendiente: bandeja.Vista | None = None
        self._globos: list[tuple[str, str, bool, threading.Event, list]] = []
        self._cerrojo = threading.Lock()
        self._iconos: dict[str, Any] = {}
        self._puesto = False
        self._taskbar_created = 0
        self._hilo: threading.Thread | None = None
        self._listo = threading.Event()

    def arrancar(self) -> bool:
        """Crea la ventana y pone el icono, en su hilo; devuelve si la ventana existe.

        Con ventana llegan `WM_DEVICECHANGE` y los demás aunque el icono
        todavía no esté: al iniciar sesión la barra de tareas puede no existir
        aún y entonces se pone al llegar `TaskbarCreated`. Sin ventana, el
        agente sigue sin bandeja, sondea como penwatch y avisa con el icono de
        paso.
        """
        self._hilo = threading.Thread(target=self._correr, name="bandeja", daemon=True)
        self._hilo.start()
        self._listo.wait(ESPERA_ARRANQUE)
        if self.hwnd:
            avisos.GLOBO = self.globo
        return bool(self.hwnd)

    @property
    def puesta(self) -> bool:
        """Indica si el icono está en la barra de tareas."""
        return self._puesto

    def poner(self, vista: bandeja.Vista) -> None:
        """Pide al hilo de la bandeja que enseñe esa vista."""
        with self._cerrojo:
            self._pendiente = vista
        self._avisar(WM_PONER)

    def globo(self, titulo: str, texto: str, urgente: bool = False) -> bool:
        """Cuelga un aviso del icono y devuelve si Windows lo ha aceptado."""
        if self.hwnd is None or not self._puesto:
            return False
        hecho, resultado = threading.Event(), [False]
        with self._cerrojo:
            self._globos.append((titulo, texto, urgente, hecho, resultado))
        if threading.current_thread() is self._hilo:
            self._colgar_globos()
        elif not self._avisar(WM_GLOBO):
            return False
        hecho.wait(ESPERA_GLOBO)
        return resultado[0]

    def cerrar(self) -> None:
        """Cierra la ventana y espera a que el hilo acabe."""
        if avisos.GLOBO == self.globo:
            avisos.GLOBO = None
        self._avisar(WM_CLOSE)
        if self._hilo is not None and self._hilo is not threading.current_thread():
            self._hilo.join(ESPERA_ARRANQUE)

    def _avisar(self, mensaje: int) -> bool:
        """Manda un mensaje a la ventana de la bandeja y devuelve si se ha podido."""
        return self.hwnd is not None and bool(self.api.post(self.hwnd, mensaje))

    def _correr(self) -> None:
        """Es el hilo de la bandeja: crea la ventana, pone el icono y corre el bucle."""
        try:
            if self.api is None:
                self.api = Api()
            self._taskbar_created = self.api.mensaje_registrado("TaskbarCreated")
            self.hwnd = self.api.ventana(self._mensaje)
            if self.hwnd:
                self._pendiente = self._pendiente or self.vista
                self._poner_icono()
        except Exception:                               # noqa: BLE001
            if self.hwnd:
                self.api.destruir(self.hwnd)
            self.hwnd = None
        finally:
            self._listo.set()
        if self.hwnd:
            self.api.bucle()

    def _mensaje(self, hwnd, msg: int, wparam: int, lparam: int) -> int | None:
        """Hace lo que toca con cada mensaje de la ventana.

        Devuelve `None` para dejar lo que haga Windows por defecto
        (`DefWindowProcW`).
        """
        if msg == WM_ICONO:
            if lparam in (WM_RBUTTONUP, WM_LBUTTONUP, WM_CONTEXTMENU):
                self._menu()
            return 0
        if msg in (WM_MEASUREITEM, WM_DRAWITEM):
            # Las filas del menú abierto (`Api.menu`): las mide y las pinta la Api.
            hecho = (self.api.medir(lparam) if msg == WM_MEASUREITEM
                     else self.api.pintar(lparam))
            return 1 if hecho else None
        if msg == WM_PONER:
            self._poner_icono()
            return 0
        if msg == WM_GLOBO:
            self._colgar_globos()
            return 0
        if msg == WM_DEVICECHANGE:
            atender = self.dispositivo
            if wparam in AVISOS_DE_HANDLE and lparam and atender is not None:
                h = self.api.handle_de(lparam)
                if h is not None:
                    try:
                        atender(wparam, h)
                    except Exception:                   # noqa: BLE001
                        pass                # un fallo del motor no impide la extracción
            if wparam in (DBT_DEVICEARRIVAL, DBT_DEVICEREMOVECOMPLETE, DBT_DEVNODES_CHANGED):
                self.montajes()
            return None                     # y que Windows conteste lo suyo (TRUE)
        if msg == WM_POWERBROADCAST:
            if wparam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND):
                self.pedir({"pide": equipo.PIDE_DESPERTAR})
            return None
        if self._taskbar_created and msg == self._taskbar_created:
            # El Explorador se ha reiniciado y se ha llevado el icono.
            self._puesto = False
            self._poner_icono()
            return 0
        if msg == WM_CLOSE:
            self.api.destruir(hwnd)
            return 0
        if msg == WM_DESTROY:
            if self._puesto:
                self.api.notificar(NIM_DELETE, hwnd=hwnd, id=ID_ICONO, flags=0)
                self._puesto = False
            for h in self._iconos.values():
                if h:
                    self.api.soltar_icono(h)
            self._iconos.clear()
            self.api.salir()
            return 0
        return None

    def _icono(self, estado: str):
        """Devuelve el icono de ese estado, cargado una vez; si falta, el de `BIEN`."""
        if estado not in self._iconos:
            ruta = icons.fichero_bandeja(self.carpeta, estado)
            self._iconos[estado] = self.api.icono(ruta) if ruta.is_file() else None
        return self._iconos[estado] or self._iconos.get(icons.BIEN)

    def _poner_icono(self) -> None:
        """Pone el icono en la barra de tareas, o lo cambia si ya está."""
        with self._cerrojo:
            vista, self._pendiente = self._pendiente, None
        if vista is not None:
            self.vista = vista
        campos = dict(hwnd=self.hwnd, id=ID_ICONO, flags=NIF_MESSAGE | NIF_ICON | NIF_TIP,
                      callback=WM_ICONO, icono=self._icono(self.vista.icono),
                      tip=self.vista.tip)
        if self._puesto:
            self.api.notificar(NIM_MODIFY, **campos)
        else:
            self._puesto = bool(self.api.notificar(NIM_ADD, **campos))

    def _colgar_globos(self) -> None:
        """Cuelga del icono los avisos pendientes y dice a quien espera cómo ha ido."""
        with self._cerrojo:
            globos, self._globos = self._globos, []
        for titulo, texto, urgente, hecho, resultado in globos:
            resultado[0] = self._puesto and bool(self.api.notificar(
                NIM_MODIFY, hwnd=self.hwnd, id=ID_ICONO, flags=NIF_INFO,
                info=texto[:255], info_titulo=titulo[:63],
                info_flags=NIIF_WARNING if urgente else NIIF_INFO))
            hecho.set()

    def _menu(self) -> None:
        """Enseña el menú y manda al agente las peticiones de la entrada elegida."""
        ids = numerar(self.vista.menu)
        elegido = self.api.menu(self.hwnd, self.vista.menu, ids)
        entrada = ids.get(elegido) if elegido else None
        if entrada is not None and entrada.activa:
            for peticion in entrada.pide:
                self.pedir(dict(peticion))


class Api:
    """Las llamadas a user32 y shell32 que hace la bandeja.

    Se crea en el hilo de la bandeja, que es el dueño de la ventana.
    """

    CLASE = f"{APP_NAME}Bandeja"

    def __init__(self) -> None:
        """Carga las bibliotecas de Windows y declara las firmas de lo que se usa."""
        import ctypes
        from ctypes import wintypes

        try:                            # el icono pequeño, a su tamaño de verdad
            from ui import theme
            theme.nitidez()
        except Exception:                               # noqa: BLE001
            pass
        self.ct, self.wt = ctypes, wintypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        LRESULT = ctypes.c_ssize_t
        self.WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                                          wintypes.WPARAM, wintypes.LPARAM)
        u = self.user32
        u.DefWindowProcW.restype = LRESULT
        u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                     wintypes.LPARAM]
        u.CreateWindowExW.restype = wintypes.HWND
        u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                      wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                      wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                   wintypes.LPARAM]
        u.DestroyWindow.argtypes = [wintypes.HWND]
        u.RegisterWindowMessageW.restype = wintypes.UINT
        u.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
        u.LoadImageW.restype = wintypes.HANDLE
        u.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                 ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u.DestroyIcon.argtypes = [wintypes.HICON]
        u.CreatePopupMenu.restype = wintypes.HMENU
        u.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t,
                                  wintypes.LPCWSTR]
        u.SetMenuDefaultItem.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
        u.TrackPopupMenu.restype = ctypes.c_int
        u.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                     wintypes.LPVOID]
        u.DestroyMenu.argtypes = [wintypes.HMENU]
        u.GetMenuItemCount.restype = ctypes.c_int
        u.GetMenuItemCount.argtypes = [wintypes.HMENU]
        u.GetSysColor.restype = wintypes.DWORD
        u.GetSysColor.argtypes = [ctypes.c_int]

        MENUITEMINFOW, BITMAPINFOHEADER = estructuras(ctypes, wintypes)
        self.MENUITEMINFOW, self.BITMAPINFOHEADER = MENUITEMINFOW, BITMAPINFOHEADER
        u.DrawIconEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HICON,
                                 ctypes.c_int, ctypes.c_int, wintypes.UINT,
                                 wintypes.HBRUSH, wintypes.UINT]
        u.SetMenuItemInfoW.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.BOOL,
                                       ctypes.POINTER(MENUITEMINFOW)]
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self.gdi32.CreateDIBSection.restype = wintypes.HBITMAP
        self.gdi32.CreateDIBSection.argtypes = [wintypes.HDC,
                                                ctypes.POINTER(BITMAPINFOHEADER),
                                                wintypes.UINT,
                                                ctypes.POINTER(ctypes.c_void_p),
                                                wintypes.HANDLE, wintypes.DWORD]
        self.gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        self.gdi32.CreateCompatibleDC.restype = wintypes.HDC
        self.gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        self.gdi32.SelectObject.restype = wintypes.HGDIOBJ
        self.gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        self.gdi32.DeleteDC.argtypes = [wintypes.HDC]
        self._firmas_de_dibujo()
        self._pixeles: dict[tuple, bytes] = bandeja.CacheAcotada()   # iconos ya pintados
        self._dibujo: Dibujo | None = None  # el menú propio abierto, si lo hay
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                  wintypes.UINT, wintypes.UINT]
        u.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        u.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        self.kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        self.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self.NOTIFYICONDATAW = avisos.notifyicondata()
        self.shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD,
                                                   ctypes.POINTER(self.NOTIFYICONDATAW)]
        self._proc = None                   # la referencia que ctypes necesita viva

    def _firmas_de_dibujo(self) -> None:
        """Declara las llamadas de user32 y gdi32 con las que se pinta el menú propio."""
        ct, wt, u, g = self.ct, self.wt, self.user32, self.gdi32
        self.DIBUJO = estructuras_dibujo(ct, wt)
        u.GetDC.restype = wt.HDC
        u.GetDC.argtypes = [wt.HWND]
        u.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
        u.SetMenuInfo.argtypes = [wt.HMENU, ct.POINTER(self.DIBUJO["MENUINFO"])]
        u.FillRect.argtypes = [wt.HDC, ct.POINTER(wt.RECT), wt.HBRUSH]
        u.DrawTextW.argtypes = [wt.HDC, wt.LPCWSTR, ct.c_int, ct.POINTER(wt.RECT), wt.UINT]
        g.GetDeviceCaps.argtypes = [wt.HDC, ct.c_int]
        g.CreateFontW.restype = wt.HFONT
        g.CreateFontW.argtypes = [ct.c_int, ct.c_int, ct.c_int, ct.c_int, ct.c_int,
                                  wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD,
                                  wt.DWORD, wt.DWORD, wt.DWORD, wt.LPCWSTR]
        g.CreateSolidBrush.restype = wt.HBRUSH
        g.CreateSolidBrush.argtypes = [wt.COLORREF]
        g.SetTextColor.argtypes = [wt.HDC, wt.COLORREF]
        g.SetBkMode.argtypes = [wt.HDC, ct.c_int]
        g.ExcludeClipRect.argtypes = [wt.HDC, ct.c_int, ct.c_int, ct.c_int, ct.c_int]
        g.GdiAlphaBlend.argtypes = [wt.HDC, ct.c_int, ct.c_int, ct.c_int, ct.c_int,
                                    wt.HDC, ct.c_int, ct.c_int, ct.c_int, ct.c_int,
                                    self.DIBUJO["BLENDFUNCTION"]]

    def handle_de(self, lparam: int) -> int | None:
        """Devuelve el handle de un aviso de `WM_DEVICECHANGE` que es de un handle, o `None`.

        `lParam` apunta a un `DEV_BROADCAST_HDR` (dbt.h); si su tipo es
        `DBT_DEVTYP_HANDLE`, es un `DEV_BROADCAST_HANDLE` y se lee su
        `dbch_handle`.
        """
        ct, wt = self.ct, self.wt

        class DEV_BROADCAST_HDR(ct.Structure):
            """`DEV_BROADCAST_HDR` de dbt.h."""
            _fields_ = [("dbch_size", wt.DWORD), ("dbch_devicetype", wt.DWORD),
                        ("dbch_reserved", wt.DWORD)]

        class DEV_BROADCAST_HANDLE(ct.Structure):
            """El principio de `DEV_BROADCAST_HANDLE` de dbt.h, hasta su handle."""
            _fields_ = [("dbch_size", wt.DWORD), ("dbch_devicetype", wt.DWORD),
                        ("dbch_reserved", wt.DWORD), ("dbch_handle", wt.HANDLE)]

        cabecera = ct.cast(lparam, ct.POINTER(DEV_BROADCAST_HDR)).contents
        if cabecera.dbch_devicetype != DBT_DEVTYP_HANDLE:
            return None
        return ct.cast(lparam, ct.POINTER(DEV_BROADCAST_HANDLE)).contents.dbch_handle

    def mensaje_registrado(self, nombre: str) -> int:
        """Devuelve el número de un mensaje registrado con `RegisterWindowMessageW`."""
        return int(self.user32.RegisterWindowMessageW(nombre))

    def ventana(self, manejar: Callable) -> Any:
        """Crea la ventana oculta y devuelve su `hwnd`.

        Args:
            manejar: El procedimiento `manejar(hwnd, msg, wparam, lparam)`; si
                devuelve `None`, hace `DefWindowProcW`.
        """
        ct, wt, u = self.ct, self.wt, self.user32

        def proc(hwnd, msg, wparam, lparam):
            """Llama a `manejar` sin dejar que un fallo suyo tumbe el bucle."""
            try:
                r = manejar(hwnd, msg, wparam, lparam)
            except Exception:                           # noqa: BLE001
                r = None                    # un fallo de la bandeja no tumba el bucle
            return u.DefWindowProcW(hwnd, msg, wparam, lparam) if r is None else r

        class WNDCLASSW(ct.Structure):
            """Estructura `WNDCLASSW` de winuser.h."""
            _fields_ = [("style", wt.UINT), ("lpfnWndProc", self.WNDPROC),
                        ("cbClsExtra", ct.c_int), ("cbWndExtra", ct.c_int),
                        ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                        ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                        ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]

        self._proc = self.WNDPROC(proc)
        instancia = self.kernel32.GetModuleHandleW(None)
        clase = WNDCLASSW()
        clase.lpfnWndProc = self._proc
        clase.hInstance = instancia
        clase.lpszClassName = self.CLASE
        u.RegisterClassW.argtypes = [ct.POINTER(WNDCLASSW)]
        u.RegisterClassW(ct.byref(clase))       # ya registrada (otro arranque): vale
        WS_EX_TOOLWINDOW, WS_POPUP = 0x80, 0x80000000
        return u.CreateWindowExW(WS_EX_TOOLWINDOW, self.CLASE, APP_NAME, WS_POPUP,
                                 0, 0, 0, 0, None, None, instancia, None)

    def bucle(self) -> None:
        """Corre el bucle de mensajes hasta que llega `WM_QUIT`."""
        msg = self.wt.MSG()
        while self.user32.GetMessageW(self.ct.byref(msg), None, 0, 0) > 0:
            self.user32.TranslateMessage(self.ct.byref(msg))
            self.user32.DispatchMessageW(self.ct.byref(msg))

    def salir(self) -> None:
        """Pide que acabe el bucle de mensajes."""
        self.user32.PostQuitMessage(0)

    def destruir(self, hwnd) -> None:
        """Destruye la ventana."""
        self.user32.DestroyWindow(hwnd)

    def post(self, hwnd, mensaje: int) -> bool:
        """Manda un mensaje a la ventana sin esperar y devuelve si se ha podido."""
        return bool(self.user32.PostMessageW(hwnd, mensaje, 0, 0))

    def icono(self, ruta: Path):
        """Carga un `.ico` al tamaño del icono pequeño del sistema.

        Devuelve `None` si no se puede.
        """
        lado = self.user32.GetSystemMetrics(SM_CXSMICON) or 16
        return self.user32.LoadImageW(None, str(ruta), IMAGE_ICON, lado, lado,
                                      LR_LOADFROMFILE) or None

    def soltar_icono(self, h) -> None:
        """Libera un icono cargado con `icono()`."""
        self.user32.DestroyIcon(h)

    def notificar(self, accion: int, hwnd=None, id: int = ID_ICONO, flags: int = 0,
                  callback: int = 0, icono=None, tip: str = "", info: str = "",
                  info_titulo: str = "", info_flags: int = 0) -> bool:
        """Hace una operación de `Shell_NotifyIconW` sobre el icono.

        Devuelve si ha ido bien.
        """
        datos = self.NOTIFYICONDATAW()
        datos.cbSize = self.ct.sizeof(self.NOTIFYICONDATAW)
        datos.hWnd, datos.uID, datos.uFlags = hwnd, id, flags
        datos.uCallbackMessage = callback
        if icono:
            datos.hIcon = icono
        datos.szTip = tip[:127]
        datos.szInfo, datos.szInfoTitle = info[:255], info_titulo[:63]
        datos.dwInfoFlags = info_flags
        return bool(self.shell32.Shell_NotifyIconW(accion, self.ct.byref(datos)))

    def _seccion(self, lado: int, hdc=None) -> tuple[Any, Any]:
        """Crea un DIB de 32 bits de arriba abajo, a ceros.

        Returns:
            `(mapa de bits, dirección de sus píxeles)`, o `(None, None)`.
        """
        ct = self.ct
        cabecera = self.BITMAPINFOHEADER(biSize=ct.sizeof(self.BITMAPINFOHEADER),
                                         biWidth=lado, biHeight=-lado, biPlanes=1,
                                         biBitCount=32, biCompression=0)
        bits = ct.c_void_p()
        h = self.gdi32.CreateDIBSection(hdc, ct.byref(cabecera), 0, ct.byref(bits),
                                        None, 0)
        if not h or not bits.value:
            if h:
                self.gdi32.DeleteObject(h)
            return None, None
        return h, bits.value

    def _dib(self, datos: bytes, lado: int):
        """Devuelve un mapa de bits de menú con esos píxeles, o `None` si no se puede."""
        try:
            h, bits = self._seccion(lado)
            if h is None:
                return None
            self.ct.memmove(bits, datos, len(datos))
            return h
        except Exception:                               # noqa: BLE001
            return None

    def _bitmap(self, nombre: str, lado: int, color: str):
        """Devuelve el glifo `nombre` como mapa de bits de menú.

        Es `None` si no se puede: una entrada sin icono sigue siendo una
        entrada.
        """
        try:
            return self._dib(self._glifo(nombre, lado, color), lado)
        except Exception:                               # noqa: BLE001
            return None

    def _glifo(self, nombre: str, lado: int, color: str) -> bytes:
        """Devuelve los píxeles del glifo `nombre` a ese tamaño y color, ya pintados una vez."""
        clave = (nombre, lado, color)
        if clave not in self._pixeles:
            self._pixeles[clave] = icons.pixeles_menu(nombre, lado, color)
        return self._pixeles[clave]

    def _emblema(self, emblema: bandeja.Emblema, lado: int) -> bytes:
        """Devuelve los píxeles del icono de un dispositivo, ya pintados una vez.

        Lo pintado se guarda por tamaño y, para un `.ico`, por su ruta, su
        tamaño y su fecha: el nombre ya cambia con el dibujo
        (`icono-propio-<hash>.ico`), así que no se vuelve a leer de la unidad
        cada vez que se abre el menú.
        """
        try:
            clave: tuple = ("emblema", emblema.campo, lado)
            if emblema.ico:
                info = os.stat(emblema.ico)
                clave += (emblema.ico, info.st_size, info.st_mtime_ns)
        except OSError:
            clave = ("emblema", emblema.campo, lado)
            emblema = bandeja.Emblema(campo=emblema.campo)
        if clave not in self._pixeles:
            self._pixeles[clave] = pixeles_emblema(emblema, lado, self._pixeles_ico)
        return self._pixeles[clave]

    def _bitmap_emblema(self, emblema: bandeja.Emblema, lado: int):
        """Devuelve el icono de un dispositivo como mapa de bits de menú, o `None`."""
        try:
            return self._dib(self._emblema(emblema, lado), lado)
        except Exception:                               # noqa: BLE001
            return None

    def _dibujar_icono(self, icono, lado: int, como: int) -> bytes | None:
        """Pinta un icono cargado en un DIB de 32 bits vacío y devuelve sus píxeles.

        Args:
            icono: El `HICON`.
            lado: El tamaño, en píxeles.
            como: `DI_NORMAL` (el dibujo) o `DI_MASK` (la máscara).
        """
        g = self.gdi32
        hdc = g.CreateCompatibleDC(None)
        if not hdc:
            return None
        try:
            h, bits = self._seccion(lado, hdc)
            if h is None:
                return None
            anterior = g.SelectObject(hdc, h)
            try:
                if not self.user32.DrawIconEx(hdc, 0, 0, icono, lado, lado, 0, None, como):
                    return None
                g.GdiFlush()
                return self.ct.string_at(bits, lado * lado * 4)
            finally:
                g.SelectObject(hdc, anterior)
                g.DeleteObject(h)
        finally:
            g.DeleteDC(hdc)

    def _pixeles_ico(self, ruta: str, lado: int) -> bytes | None:
        """Pinta un `.ico` a `lado` px como imagen de menú, o devuelve `None`.

        Lo lee Windows (`LoadImageW` con `LR_LOADFROMFILE`, que elige la imagen
        que mejor sirve a ese tamaño) y lo pinta `DrawIconEx` en un DIB vacío:
        con alfa, sale ya premultiplicado (`AlphaBlend`); sin él, la
        transparencia la pone su máscara (`alfa_desde_mascara()`).
        """
        icono = self.user32.LoadImageW(None, str(ruta), IMAGE_ICON, lado, lado,
                                       LR_LOADFROMFILE)
        if not icono:
            return None
        try:
            color = self._dibujar_icono(icono, lado, DI_NORMAL)
            if color is None or any(color[3::4]):
                return color
            mascara = self._dibujar_icono(icono, lado, DI_MASK)
            return None if mascara is None else alfa_desde_mascara(color, mascara)
        finally:
            self.user32.DestroyIcon(icono)

    def menu(self, hwnd, entradas: tuple[bandeja.Entrada, ...],
             ids: dict[int, bandeja.Entrada]) -> int:
        """Construye el menú, lo enseña donde está el ratón y devuelve el id elegido.

        Es un menú propio (`MFT_OWNERDRAW`): cada fila la mide `medir()` y la
        pinta `pintar()` con el aspecto del rediseño (`aspecto()`), y Windows
        sigue llevando el ratón, el teclado, los desplegables y el cierre. El
        texto de cada entrada se le da igual, para el lector de pantalla. Si
        no se puede preparar (la letra, el pincel), es el menú de Windows con
        los glifos como `hbmpItem`.

        Devuelve 0 si no se elige ninguno.
        """
        u = self.user32
        por_entrada = {id(e): n for n, e in ids.items()}
        lado = u.GetSystemMetrics(SM_CXSMICON) or 16
        c = int(u.GetSysColor(COLOR_MENUTEXT))          # 0x00BBGGRR
        tinta = f"#{c & 0xFF:02x}{(c >> 8) & 0xFF:02x}{(c >> 16) & 0xFF:02x}"
        bitmaps: list = []
        try:
            self._dibujo = self._preparar(hwnd)
        except Exception:                               # noqa: BLE001
            self._dibujo = None
        dibujo = self._dibujo

        def propia(h, e) -> None:
            """Hace propia la última entrada de `h`: la pintará `pintar()`."""
            info = self.MENUITEMINFOW()
            info.cbSize = self.ct.sizeof(self.MENUITEMINFOW)
            info.fMask = MIIM_FTYPE | MIIM_DATA
            info.fType = MFT_OWNERDRAW | (MFT_SEPARATOR if e.separador else 0)
            info.dwItemData = len(dibujo.filas)
            dibujo.filas.append(e)
            u.SetMenuItemInfoW(h, u.GetMenuItemCount(h) - 1, True, self.ct.byref(info))

        def poner_icono(h, e) -> None:
            """Le pone a la última entrada de `h` el icono de `e`, si lo tiene.

            El de un dispositivo (`emblema`) o, si no, su glifo.
            """
            if e.emblema is not None:
                b = self._bitmap_emblema(e.emblema, lado)
            elif e.icono and e.icono in icons.GLIFOS:
                b = self._bitmap(e.icono, lado, tinta)
            else:
                return
            if b is None:
                return
            bitmaps.append(b)
            info = self.MENUITEMINFOW()
            info.cbSize = self.ct.sizeof(self.MENUITEMINFOW)
            info.fMask = MIIM_BITMAP
            info.hbmpItem = b
            u.SetMenuItemInfoW(h, u.GetMenuItemCount(h) - 1, True, self.ct.byref(info))

        def adornar(h, e) -> None:
            """La deja propia o, en el menú de Windows, le pone su icono."""
            if dibujo is not None:
                propia(h, e)
            elif not e.separador:
                poner_icono(h, e)

        def construir(lista) -> Any:
            """Construye el menú de una lista de entradas, con sus submenús."""
            h = u.CreatePopupMenu()
            for e in lista:
                if e.separador:
                    u.AppendMenuW(h, MF_SEPARATOR, 0, None)
                    adornar(h, e)
                elif e.hijos:
                    u.AppendMenuW(h, MF_POPUP | (0 if e.activa else MF_GRAYED),
                                  construir(e.hijos), texto_menu(e.texto))
                    adornar(h, e)
                else:
                    n = por_entrada[id(e)]
                    u.AppendMenuW(h, MF_STRING | (0 if e.activa else MF_GRAYED)
                                  | (MF_CHECKED if e.marcada else 0), n, texto_menu(e.texto))
                    adornar(h, e)
                    if e.defecto:
                        u.SetMenuDefaultItem(h, n, 0)
            return h

        raiz = construir(entradas)
        if dibujo is not None:
            # El fondo de todo el menú, también lo que no son filas (su margen).
            MENUINFO = self.DIBUJO["MENUINFO"]
            info = MENUINFO(cbSize=self.ct.sizeof(MENUINFO),
                            fMask=MIM_BACKGROUND | MIM_APPLYTOSUBMENUS,
                            hbrBack=dibujo.pincel)
            u.SetMenuInfo(raiz, self.ct.byref(info))
        try:
            punto = self.wt.POINT()
            u.GetCursorPos(self.ct.byref(punto))
            u.SetForegroundWindow(hwnd)
            # La bandeja está en una esquina inferior derecha: el menú crece
            # hacia arriba y hacia la izquierda del cursor, no hacia fuera.
            elegido = u.TrackPopupMenu(raiz, TPM_RIGHTBUTTON | TPM_NONOTIFY | TPM_RETURNCMD
                                       | TPM_RIGHTALIGN | TPM_BOTTOMALIGN,
                                       punto.x, punto.y, 0, hwnd, None)
            u.PostMessageW(hwnd, WM_NULL, 0, 0)
        finally:
            u.DestroyMenu(raiz)             # destruye también los submenús
            for b in bitmaps:               # pero no sus mapas de bits: son nuestros
                self.gdi32.DeleteObject(b)
            self._soltar_dibujo()
        return int(elegido or 0)

    def _preparar(self, hwnd) -> Dibujo:
        """Prepara un menú propio: el aspecto del tema de ahora, sus dos letras y su fondo.

        El tema se mira cada vez (el agente vive días y el sistema puede pasar
        a oscuro); la letra es la del programa si este proceso la cargó
        (`theme.cargar_fuentes()`, que ya llamó `theme.nitidez()`) o la del
        sistema.

        Raises:
            OSError: Si Windows no da la letra o el pincel; entonces el menú es
                el de Windows.
        """
        from ui import theme
        u, g = self.user32, self.gdi32
        hdc = u.GetDC(hwnd)
        try:
            ppp = g.GetDeviceCaps(hdc, LOGPIXELSY) or 96
        finally:
            u.ReleaseDC(hwnd, hdc)
        a = aspecto(theme.sistema_oscuro(), ppp)
        familia = "Noto Sans" if theme.cargar_fuentes() else "Segoe UI"
        dibujo = Dibujo(a, {}, None)
        try:
            for negrita in (False, True):
                letra = g.CreateFontW(-a.letra, 0, 0, 0, FW_BOLD if negrita else FW_NORMAL,
                                      0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0,
                                      familia)
                if not letra:
                    raise OSError("CreateFontW")
                dibujo.letras[negrita] = letra
            dibujo.pincel = g.CreateSolidBrush(colorref(a.fondo))
            if not dibujo.pincel:
                raise OSError("CreateSolidBrush")
        except Exception:
            self._dibujo = dibujo
            self._soltar_dibujo()
            raise
        return dibujo

    def _soltar_dibujo(self) -> None:
        """Libera las letras y el pincel del menú propio, si lo había."""
        dibujo, self._dibujo = self._dibujo, None
        if dibujo is None:
            return
        for h in [*dibujo.letras.values(), dibujo.pincel]:
            if h:
                self.gdi32.DeleteObject(h)

    def medir(self, lparam: int) -> bool:
        """Contesta a `WM_MEASUREITEM`: el alto y el ancho de una fila del menú propio.

        Devuelve si era una de sus filas; si no, que conteste Windows.
        """
        d = self._dibujo
        if d is None or not lparam:
            return False
        m = self.ct.cast(lparam, self.ct.POINTER(self.DIBUJO["MEASUREITEMSTRUCT"])).contents
        if m.CtlType != ODT_MENU or m.itemData >= len(d.filas):
            return False
        e, a = d.filas[m.itemData], d.aspecto
        if e.separador:
            m.itemWidth, m.itemHeight = 0, a.alto_separador
            return True
        p = pintura(e, 0, a)
        m.itemWidth = ancho_fila(p, self._ancho_texto(e.texto, p.negrita), a)
        m.itemHeight = a.alto
        return True

    def _ancho_texto(self, texto: str, negrita: bool) -> int:
        """Devuelve lo que mide `texto` de ancho con la letra del menú, en píxeles.

        Lo mide `DrawTextW` con `DT_CALCRECT`, la misma llamada que lo pinta:
        otra medida difiere en algún píxel y el texto salía cortado con «…».
        """
        u, g = self.user32, self.gdi32
        hdc = u.GetDC(None)
        try:
            antes = g.SelectObject(hdc, self._dibujo.letras[negrita])
            caja = self.wt.RECT(0, 0, 0, 0)
            u.DrawTextW(hdc, texto, -1, self.ct.byref(caja),
                        DT_CALCRECT | DT_SINGLELINE | DT_NOPREFIX)
            g.SelectObject(hdc, antes)
            return int(caja.right - caja.left)
        finally:
            u.ReleaseDC(None, hdc)

    def pintar(self, lparam: int) -> bool:
        """Contesta a `WM_DRAWITEM`: pinta una fila del menú propio en su estado.

        La fila entera es nuestra: el fondo, el icono, el texto y el galón del
        desplegable. Al acabar se recorta del DC, porque detrás Windows pinta
        su flecha de desplegable y saldría encima del galón. Devuelve si era
        una de sus filas.
        """
        d = self._dibujo
        if d is None or not lparam:
            return False
        s = self.ct.cast(lparam, self.ct.POINTER(self.DIBUJO["DRAWITEMSTRUCT"])).contents
        if s.CtlType != ODT_MENU or s.itemData >= len(d.filas):
            return False
        e, a, hdc, g = d.filas[s.itemData], d.aspecto, s.hDC, self.gdi32
        r = self.wt.RECT(s.rcItem.left, s.rcItem.top, s.rcItem.right, s.rcItem.bottom)
        alto = r.bottom - r.top
        if e.separador:
            self._rellenar(hdc, r, a.fondo)
            medio = r.top + (alto - a.grosor) // 2
            self._rellenar(hdc, self.wt.RECT(r.left, medio, r.right, medio + a.grosor), a.linea)
        else:
            p = pintura(e, s.itemState, a)
            self._rellenar(hdc, r, p.fondo)
            if p.emblema is not None:
                # Un icono a color no se tiñe: apagado, se aclara.
                self._componer(hdc, self._emblema(p.emblema, p.lado), p.lado,
                               r.left + p.x_icono, r.top + (alto - p.lado) // 2,
                               110 if p.apagada else 255)
            elif p.glifo is not None:
                self._componer(hdc, self._glifo(p.glifo, p.lado, p.tinta), p.lado,
                               r.left + p.x_icono, r.top + (alto - p.lado) // 2)
            fin = r.right - a.margen - (a.hueco + a.galon if p.galon else 0)
            caja = self.wt.RECT(r.left + p.x_texto, r.top, fin, r.bottom)
            g.SetBkMode(hdc, TRANSPARENT)
            g.SetTextColor(hdc, colorref(p.tinta))
            antes = g.SelectObject(hdc, d.letras[p.negrita])
            self.user32.DrawTextW(hdc, e.texto, -1, self.ct.byref(caja),
                                  DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX | DT_END_ELLIPSIS)
            g.SelectObject(hdc, antes)
            if p.galon:
                self._componer(hdc, self._glifo("derecha", a.galon,
                                                p.tinta if p.apagada else a.tenue),
                               a.galon, r.right - a.margen - a.galon,
                               r.top + (alto - a.galon) // 2)
        g.ExcludeClipRect(hdc, r.left, r.top, r.right, r.bottom)
        return True

    def _rellenar(self, hdc, rect, color: str) -> None:
        """Rellena un rectángulo del DC con un color `#RRGGBB`."""
        pincel = self.gdi32.CreateSolidBrush(colorref(color))
        try:
            self.user32.FillRect(hdc, self.ct.byref(rect), pincel)
        finally:
            self.gdi32.DeleteObject(pincel)

    def _componer(self, hdc, datos: bytes, lado: int, x: int, y: int,
                  opacidad: int = 255) -> None:
        """Pone un icono (BGRA premultiplicado) sobre el DC, con su alfa (`GdiAlphaBlend`)."""
        g = self.gdi32
        memoria = g.CreateCompatibleDC(hdc)
        if not memoria:
            return
        try:
            h, bits = self._seccion(lado, memoria)
            if h is None:
                return
            try:
                self.ct.memmove(bits, datos, min(len(datos), lado * lado * 4))
                antes = g.SelectObject(memoria, h)
                mezcla = self.DIBUJO["BLENDFUNCTION"](AC_SRC_OVER, 0, opacidad, AC_SRC_ALPHA)
                g.GdiAlphaBlend(hdc, x, y, lado, lado, memoria, 0, 0, lado, lado, mezcla)
                g.SelectObject(memoria, antes)
            finally:
                g.DeleteObject(h)
        finally:
            g.DeleteDC(memoria)
