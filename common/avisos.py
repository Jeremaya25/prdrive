#!/usr/bin/env python3
"""Avisos nativos del sistema, sin Tk.

El agente no carga Tk nunca: avisa con lo que el sistema ya tiene para eso.
Evita así los intérpretes Tk en hilos propios (`Tcl_AsyncDelete`) que exigía la
ventanita de `ui.avisar_fallo`.
- Linux: `org.freedesktop.Notifications.Notify` en el bus de sesión (*Desktop
  Notifications Specification*), con `common/dbus.py`. Sin bus o sin nadie que
  atienda ese nombre, no hay aviso.
- Windows: `Shell_NotifyIconW` con `NIF_INFO`, que en Windows 10 y 11 sale como
  notificación del sistema sin registrar un AppUserModelID. El globo necesita
  un icono del área de notificación donde colgarse: el de la bandeja del agente
  (`GLOBO`, que pone `ui/bandeja_windows.py`) o, si no la hay, uno de paso
  sobre una ventana de solo mensajes que se quita a los pocos segundos. Sin
  probar en un Windows real.

`enviar()` es un punto de indirección de módulo, como `catalog.run()`: los
tests lo sustituyen, y quien lo llama apunta el aviso en su diario cuando
devuelve False.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from . import APP_NAME

IS_WIN = os.name == "nt"

SEGUNDOS_WINDOWS = 12.0
"""Segundos que se queda el icono de paso en Windows.

Quitarlo antes retira también el aviso de la pantalla.
"""

ICONO: Path | None = None
"""Icono de los avisos de Windows, o `None` para el de información del sistema.

Lo pone quien sabe dónde está el `.ico` repintado (el agente, al arrancar).
"""

GLOBO = None
"""Función de la bandeja que cuelga el aviso de su propio icono, si está puesta.

Firma: `GLOBO(titulo, texto, urgente) -> bool`. Si devuelve False se usa el
icono de paso.
"""


def enviar(titulo: str, texto: str, urgente: bool = False) -> bool:
    """Enseña un aviso del sistema; nunca lanza.

    Returns:
        True si se ha podido mostrar.
    """
    try:
        return _windows(titulo, texto, urgente) if IS_WIN else _linux(titulo, texto, urgente)
    except Exception:                                   # noqa: BLE001
        return False


NOTIFICACIONES = "org.freedesktop.Notifications"
RUTA_NOTIFICACIONES = "/org/freedesktop/Notifications"
# Hint `urgency` de la especificación: 0 baja, 1 normal, 2 crítica. Un fallo es
# normal: una crítica no se va sola en muchos escritorios.
URGENCIA_NORMAL, URGENCIA_BAJA = 1, 0


def argumentos_notify(titulo: str, texto: str, urgente: bool) -> list:
    """Devuelve los ocho argumentos de `Notify(susssasa{sv}i)`.

    Son: aplicación, a quién sustituye (0: a nadie), icono, título, cuerpo,
    acciones, hints y duración (-1: la que decida el servidor).
    """
    from .dbus import Variante
    return [APP_NAME, 0, "", titulo, texto, [],
            {"urgency": Variante("y", URGENCIA_NORMAL if urgente else URGENCIA_BAJA)},
            -1]


def _linux(titulo: str, texto: str, urgente: bool) -> bool:
    """Envía el aviso por D-Bus a `org.freedesktop.Notifications`."""
    from . import dbus
    with dbus.Conexion.sesion() as bus:
        bus.llamar(NOTIFICACIONES, RUTA_NOTIFICACIONES, NOTIFICACIONES, "Notify",
                   "susssasa{sv}i", argumentos_notify(titulo, texto, urgente))
    return True


# Constantes de la API de Windows (shellapi.h, winuser.h).
NIM_ADD, NIM_DELETE = 0, 2
NIF_ICON, NIF_TIP, NIF_INFO = 0x2, 0x4, 0x10
NIIF_INFO, NIIF_WARNING = 0x1, 0x2
HWND_MESSAGE = -3
IDI_INFORMATION = 32516
IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x10, 0x40


def _windows(titulo: str, texto: str, urgente: bool) -> bool:
    """Cuelga el aviso del icono de la bandeja o, si no hay, de uno de paso."""
    if GLOBO is not None and GLOBO(titulo, texto, urgente):
        return True
    return _de_paso(titulo, texto, urgente)


_TIPOS: dict = {}
"""Caché de los tipos `ctypes`, que solo se definen en Windows y una vez."""


def notifyicondata():
    """Devuelve el tipo `NOTIFYICONDATAW` en la forma de Vista en adelante.

    Sigue `shellapi.h`, con `hBalloonIcon` al final. Es la única definición: la
    usan el icono de paso y la bandeja.
    """
    if "NOTIFYICONDATAW" not in _TIPOS:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            """Estructura `GUID` de Windows."""
            _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                        ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

        class NOTIFYICONDATAW(ctypes.Structure):
            """Estructura `NOTIFYICONDATAW` de `shellapi.h`."""
            _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                        ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                        ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                        ("szTip", ctypes.c_wchar * 128), ("dwState", wintypes.DWORD),
                        ("dwStateMask", wintypes.DWORD), ("szInfo", ctypes.c_wchar * 256),
                        ("uVersion", wintypes.UINT), ("szInfoTitle", ctypes.c_wchar * 64),
                        ("dwInfoFlags", wintypes.DWORD), ("guidItem", GUID),
                        ("hBalloonIcon", wintypes.HICON)]

        _TIPOS["NOTIFYICONDATAW"] = NOTIFYICONDATAW
    return _TIPOS["NOTIFYICONDATAW"]


def _de_paso(titulo: str, texto: str, urgente: bool) -> bool:
    """Lanza el aviso en un hilo propio y espera a saber si se ha puesto.

    La ventana y el icono son de ese hilo de principio a fin (Windows solo deja
    destruir una ventana al hilo que la creó), y el hilo se queda los segundos
    que dura el aviso para quitar el icono después.

    Returns:
        True si el aviso se ha puesto en pantalla antes de 5 segundos.
    """
    listo = threading.Event()
    resultado = [False]

    def hilo() -> None:
        """Ejecuta `_globo` y avisa de que ha terminado, salga como salga."""
        try:
            _globo(titulo, texto, urgente, listo, resultado)
        finally:
            listo.set()

    threading.Thread(target=hilo, name="aviso", daemon=True).start()
    listo.wait(5.0)
    return resultado[0]


def _globo(titulo: str, texto: str, urgente: bool, listo: threading.Event,
           resultado: list) -> None:
    """Muestra el aviso con un icono temporal sobre una ventana de solo mensajes.

    Args:
        listo: Se activa en cuanto se sabe si el aviso se puso.
        resultado: Lista de un elemento donde se deja ese resultado.
    """
    import ctypes
    from ctypes import wintypes

    NOTIFYICONDATAW = notifyicondata()

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                       wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                       wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.LoadIconW.restype = wintypes.HICON
    user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPVOID]
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyIcon.argtypes = [wintypes.HICON]
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]

    # Ventana de solo mensajes de la clase `STATIC`, que ya existe: no hay que
    # registrar clase ni procedimiento, y no recibe difusiones.
    ventana = user32.CreateWindowExW(0, "STATIC", APP_NAME, 0, 0, 0, 0, 0,
                                     wintypes.HWND(HWND_MESSAGE), None, None, None)
    if not ventana:
        return
    icono_propio = None
    try:
        if ICONO is not None and Path(ICONO).is_file():
            icono_propio = user32.LoadImageW(None, str(ICONO), IMAGE_ICON, 0, 0,
                                             LR_LOADFROMFILE | LR_DEFAULTSIZE)
        icono = icono_propio or user32.LoadIconW(None, ctypes.c_void_p(IDI_INFORMATION))
        datos = NOTIFYICONDATAW()
        datos.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        datos.hWnd = ventana
        datos.uID = 1
        datos.uFlags = NIF_ICON | NIF_TIP | NIF_INFO
        datos.hIcon = icono
        datos.szTip = APP_NAME
        datos.szInfoTitle = titulo[:63]
        datos.szInfo = texto[:255]
        datos.dwInfoFlags = NIIF_WARNING if urgente else NIIF_INFO
        if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(datos)):
            return
        resultado[0] = True
        listo.set()
        time.sleep(SEGUNDOS_WINDOWS)
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(datos))
    finally:
        if icono_propio:
            user32.DestroyIcon(icono_propio)
        user32.DestroyWindow(ventana)
