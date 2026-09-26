#!/usr/bin/env python3
"""
bandeja_windows.py — La bandeja del agente en Windows: `Shell_NotifyIconW`.

Solo DIBUJA: qué icono, qué texto y qué menú lo decide `ui/bandeja.py`, y lo
que se elige en el menú son peticiones al agente (`pedir(dict)`), las mismas
que las del buzón. Nada de Tk: ctypes contra user32 y shell32, sin
dependencias, y **sin probar en un Windows real** (ver
`docs/superpowers/pruebas/2026-09-25-equipo-pendiente-en-real.md`).

  * **Un hilo propio con su ventana y su bucle de mensajes.** Windows entrega
    los mensajes de una ventana al hilo que la creó, y solo ese hilo puede
    destruirla. El agente sigue en el suyo; se hablan con `PostMessageW` (de
    aquí para allá: `poner()`, `globo()`, `cerrar()`) y con `pedir()` (de allá
    para aquí: lo que se elige en el menú).
  * **Una ventana oculta de nivel superior, NO de solo mensajes.** El diseño
    decía «de solo mensajes», pero esas no reciben difusiones («Message-Only
    Windows», en la documentación de Win32), y dos de las que hacen falta lo
    son: `WM_DEVICECHANGE` con `DBT_DEVICEARRIVAL` de un volumen (VeraCrypt
    anuncia así sus montajes, `BroadcastDeviceChange()` en
    `Common/Dlgcode.c`) y `TaskbarCreated`, que llega cuando el Explorador se
    reinicia y hay que volver a poner el icono. Nunca se enseña.
  * **`WM_DEVICECHANGE`** despierta al agente para que recorra las unidades en
    racha (`montajes()`), en vez de recorrerlas cada 5 s como penwatch.
  * **`WM_POWERBROADCAST`** con `PBT_APMRESUMEAUTOMATIC` (vuelta de la
    suspensión) pide `despertar`: la batería, la red y los remotos sin
    conexión se miran enseguida (sección 6 del diseño).
  * **El menú** es `TrackPopupMenu` con `TPM_RETURNCMD`: devuelve el id
    elegido en vez de mandar `WM_COMMAND`. Antes, `SetForegroundWindow` a la
    ventana propia, y después un `WM_NULL`: sin eso el menú no se cierra al
    pinchar fuera (es la receta de la documentación de `TrackPopupMenu`).
    Se abre con el botón derecho y con el izquierdo; la entrada `defecto` va
    en negrita.
  * **Los avisos** cuelgan del propio icono (`NIM_MODIFY` + `NIF_INFO`), que
    en Windows 10 y 11 salen como notificación del sistema:
    `common/avisos.GLOBO` apunta a `globo()` mientras la bandeja vive.
  * **Los iconos** son los cinco `bandeja-<estado>.ico` que `ui/icons.py`
    repinta en la carpeta del agente, cargados con `LoadImageW` al tamaño del
    icono pequeño del sistema (`SM_CXSMICON`), con la densidad declarada
    (`theme.nitidez()`) para que ese tamaño sea el de verdad.

Todo lo que toca Windows está en `Api`; `Bandeja` habla con ella y los tests le
ponen una de mentira (`tests/test_bandeja_windows.py`).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

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
DBT_DEVICEREMOVECOMPLETE = 0x8004

# Shell_NotifyIconW (shellapi.h).
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_INFO, NIIF_WARNING = 0x1, 0x2
ID_ICONO = 1

# Menús.
MF_STRING, MF_GRAYED, MF_CHECKED, MF_POPUP, MF_SEPARATOR = 0x0, 0x1, 0x8, 0x10, 0x800
TPM_RIGHTBUTTON, TPM_NONOTIFY, TPM_RETURNCMD = 0x2, 0x80, 0x100
PRIMER_ID = 100

ESPERA_ARRANQUE = 5.0           # lo que espera `arrancar()` a saber si hay icono
ESPERA_GLOBO = 2.0


def texto_menu(texto: str) -> str:
    """Un `&` en un menú marca la tecla de acceso de la letra siguiente: el de
    un nombre de unidad se dobla para que salga tal cual."""
    return texto.replace("&", "&&")


def numerar(menu: tuple[bandeja.Entrada, ...], primero: int = PRIMER_ID
            ) -> dict[int, bandeja.Entrada]:
    """Un id por entrada que se puede elegir (ni separadores ni submenús), en
    el orden del árbol. Es lo que devuelve `TrackPopupMenu`."""
    ids: dict[int, bandeja.Entrada] = {}

    def recorrer(entradas) -> None:
        for e in entradas:
            if e.separador:
                continue
            if e.hijos:
                recorrer(e.hijos)
            else:
                ids[primero + len(ids)] = e
    recorrer(menu)
    return ids


class Bandeja:
    """El icono de la bandeja del agente.

    `pedir(peticion)` y `montajes()` se llaman desde el hilo de la bandeja:
    tienen que ser baratos y seguros entre hilos (el agente los mete en una
    cola y se despierta)."""

    def __init__(self, carpeta_iconos: Path, pedir: Callable[[dict], None],
                 montajes: Callable[[], None], api: Any = None) -> None:
        self.carpeta = Path(carpeta_iconos)
        self.pedir = pedir
        self.montajes = montajes
        self.api = api
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

    # --- desde el hilo del agente --------------------------------------------------

    def arrancar(self) -> bool:
        """Crea la ventana y pone el icono, en su hilo. True si la ventana
        existe: con ella llegan `WM_DEVICECHANGE` y los demás, aunque el icono
        todavía no esté (al iniciar sesión la barra de tareas puede no existir
        aún, y entonces se pone al llegar `TaskbarCreated`). False sin ventana:
        el agente sigue sin bandeja, sondea como penwatch y avisa con el icono
        de paso."""
        self._hilo = threading.Thread(target=self._correr, name="bandeja", daemon=True)
        self._hilo.start()
        self._listo.wait(ESPERA_ARRANQUE)
        if self.hwnd:
            avisos.GLOBO = self.globo
        return bool(self.hwnd)

    @property
    def puesta(self) -> bool:
        """¿Está el icono en la barra de tareas?"""
        return self._puesto

    def poner(self, vista: bandeja.Vista) -> None:
        with self._cerrojo:
            self._pendiente = vista
        self._avisar(WM_PONER)

    def globo(self, titulo: str, texto: str, urgente: bool = False) -> bool:
        """Cuelga un aviso del icono. True si Windows lo ha aceptado."""
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
        if avisos.GLOBO == self.globo:
            avisos.GLOBO = None
        self._avisar(WM_CLOSE)
        if self._hilo is not None and self._hilo is not threading.current_thread():
            self._hilo.join(ESPERA_ARRANQUE)

    def _avisar(self, mensaje: int) -> bool:
        return self.hwnd is not None and bool(self.api.post(self.hwnd, mensaje))

    # --- en el hilo de la bandeja ----------------------------------------------------

    def _correr(self) -> None:
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
        """Lo que hace la bandeja con cada mensaje. None: lo que haga Windows
        por defecto (`DefWindowProcW`)."""
        if msg == WM_ICONO:
            if lparam in (WM_RBUTTONUP, WM_LBUTTONUP, WM_CONTEXTMENU):
                self._menu()
            return 0
        if msg == WM_PONER:
            self._poner_icono()
            return 0
        if msg == WM_GLOBO:
            self._colgar_globos()
            return 0
        if msg == WM_DEVICECHANGE:
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
        if estado not in self._iconos:
            ruta = icons.fichero_bandeja(self.carpeta, estado)
            self._iconos[estado] = self.api.icono(ruta) if ruta.is_file() else None
        return self._iconos[estado] or self._iconos.get(icons.BIEN)

    def _poner_icono(self) -> None:
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
        with self._cerrojo:
            globos, self._globos = self._globos, []
        for titulo, texto, urgente, hecho, resultado in globos:
            resultado[0] = self._puesto and bool(self.api.notificar(
                NIM_MODIFY, hwnd=self.hwnd, id=ID_ICONO, flags=NIF_INFO,
                info=texto[:255], info_titulo=titulo[:63],
                info_flags=NIIF_WARNING if urgente else NIIF_INFO))
            hecho.set()

    def _menu(self) -> None:
        ids = numerar(self.vista.menu)
        elegido = self.api.menu(self.hwnd, self.vista.menu, ids)
        entrada = ids.get(elegido) if elegido else None
        if entrada is not None and entrada.activa:
            for peticion in entrada.pide:
                self.pedir(dict(peticion))


# ---------------------------------------------------------------------------
# Windows de verdad
# ---------------------------------------------------------------------------

class Api:
    """Las llamadas a user32 y shell32 que hace la bandeja. Se crea en el hilo
    de la bandeja, que es el dueño de la ventana."""

    CLASE = f"{APP_NAME}Bandeja"

    def __init__(self) -> None:
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

    def mensaje_registrado(self, nombre: str) -> int:
        return int(self.user32.RegisterWindowMessageW(nombre))

    def ventana(self, manejar: Callable) -> Any:
        """La ventana oculta, con `manejar(hwnd, msg, wparam, lparam)` como
        procedimiento (None → `DefWindowProcW`)."""
        ct, wt, u = self.ct, self.wt, self.user32

        def proc(hwnd, msg, wparam, lparam):
            try:
                r = manejar(hwnd, msg, wparam, lparam)
            except Exception:                           # noqa: BLE001
                r = None                    # un fallo de la bandeja no tumba el bucle
            return u.DefWindowProcW(hwnd, msg, wparam, lparam) if r is None else r

        class WNDCLASSW(ct.Structure):
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
        msg = self.wt.MSG()
        while self.user32.GetMessageW(self.ct.byref(msg), None, 0, 0) > 0:
            self.user32.TranslateMessage(self.ct.byref(msg))
            self.user32.DispatchMessageW(self.ct.byref(msg))

    def salir(self) -> None:
        self.user32.PostQuitMessage(0)

    def destruir(self, hwnd) -> None:
        self.user32.DestroyWindow(hwnd)

    def post(self, hwnd, mensaje: int) -> bool:
        return bool(self.user32.PostMessageW(hwnd, mensaje, 0, 0))

    def icono(self, ruta: Path):
        SM_CXSMICON, IMAGE_ICON, LR_LOADFROMFILE = 49, 1, 0x10
        lado = self.user32.GetSystemMetrics(SM_CXSMICON) or 16
        return self.user32.LoadImageW(None, str(ruta), IMAGE_ICON, lado, lado,
                                      LR_LOADFROMFILE) or None

    def soltar_icono(self, h) -> None:
        self.user32.DestroyIcon(h)

    def notificar(self, accion: int, hwnd=None, id: int = ID_ICONO, flags: int = 0,
                  callback: int = 0, icono=None, tip: str = "", info: str = "",
                  info_titulo: str = "", info_flags: int = 0) -> bool:
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

    def menu(self, hwnd, entradas: tuple[bandeja.Entrada, ...],
             ids: dict[int, bandeja.Entrada]) -> int:
        """Construye el menú, lo enseña donde está el ratón y devuelve el id
        elegido (0: ninguno)."""
        u = self.user32
        por_entrada = {id(e): n for n, e in ids.items()}

        def construir(lista) -> Any:
            h = u.CreatePopupMenu()
            for e in lista:
                if e.separador:
                    u.AppendMenuW(h, MF_SEPARATOR, 0, None)
                elif e.hijos:
                    u.AppendMenuW(h, MF_POPUP | (0 if e.activa else MF_GRAYED),
                                  construir(e.hijos), texto_menu(e.texto))
                else:
                    n = por_entrada[id(e)]
                    u.AppendMenuW(h, MF_STRING | (0 if e.activa else MF_GRAYED)
                                  | (MF_CHECKED if e.marcada else 0), n, texto_menu(e.texto))
                    if e.defecto:
                        u.SetMenuDefaultItem(h, n, 0)
            return h

        raiz = construir(entradas)
        try:
            punto = self.wt.POINT()
            u.GetCursorPos(self.ct.byref(punto))
            u.SetForegroundWindow(hwnd)
            elegido = u.TrackPopupMenu(raiz, TPM_RIGHTBUTTON | TPM_NONOTIFY | TPM_RETURNCMD,
                                       punto.x, punto.y, 0, hwnd, None)
            u.PostMessageW(hwnd, WM_NULL, 0, 0)
        finally:
            u.DestroyMenu(raiz)             # destruye también los submenús
        return int(elegido or 0)
