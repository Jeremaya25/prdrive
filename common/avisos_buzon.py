#!/usr/bin/env python3
"""Avisa cuando alguien deja algo en el buzón del agente, para no mirarlo en cada vuelta.

El buzón (`agente.pide`, en la carpeta del agente) lo escriben otros procesos:
la ventana de una raíz, `agente.py pasada`, el instalador. El agente lo vaciaba
intentando renombrarlo en cada vuelta, cada 2 s, hubiera algo o no: era lo
único que le impedía esperar más cuando no atiende nada. Con un oyente
(`abrir()`), el sistema le dice cuándo aparece o se escribe ese fichero, y la
vuelta sin unidades puede ser de medio minuto (`agente.cuanto_esperar()`).

Se oye la carpeta del agente, sin sus subcarpetas, y solo cuenta el nombre del
buzón: lo demás que se escribe ahí (el estado, el diario, la salida de la
pasada) no despierta a nadie. Sirve con cualquier versión de quien pide: no
hace falta que avise, basta con que escriba.

- Linux: inotify. El oyente tiene `fd` y `leer()`; el vigía del agente lo
  espera junto a lo demás (`Vigia.oir_buzon()`).
- Windows: `ReadDirectoryChangesW` síncrona en un hilo propio, que llama a
  `avisar()`. La carpeta es del disco del equipo: no hay unidad que expulsar.

Si no se puede oír (otro sistema, sin descriptores de inotify), `abrir()`
devuelve `None` y el agente sigue mirando el buzón en cada vuelta.
"""

from __future__ import annotations

import ctypes
import os
import struct
import sys
import threading
from pathlib import Path
from typing import Any, Callable

ES_LINUX = sys.platform.startswith("linux")
ES_WINDOWS = os.name == "nt"

IN_CLOSE_WRITE = 0x00000008
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
CABECERA = struct.Struct("iIII")

FILE_LIST_DIRECTORY = 0x0001
FILE_SHARE_TODO = 0x1 | 0x2 | 0x4
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILTRO = 0x01 | 0x08 | 0x10         # FILE_NOTIFY_CHANGE_FILE_NAME | SIZE | LAST_WRITE
TAM_BUFER = 16 * 1024


def nombres_de_inotify(datos: bytes) -> list[str]:
    """Devuelve los nombres de los `struct inotify_event` de una lectura."""
    nombres, i = [], 0
    while i + CABECERA.size <= len(datos):
        _wd, _mask, _cookie, largo = CABECERA.unpack_from(datos, i)
        i += CABECERA.size
        nombres.append(os.fsdecode(datos[i:i + largo].split(b"\0", 1)[0]))
        i += largo
    return nombres


def nombres_de_windows(datos: bytes) -> list[str]:
    """Devuelve los nombres de un búfer de `FILE_NOTIFY_INFORMATION` (winnt.h)."""
    nombres, i = [], 0
    while i + 12 <= len(datos):
        siguiente, _accion, largo = struct.unpack_from("<III", datos, i)
        nombres.append(datos[i + 12:i + 12 + largo].decode("utf-16-le", "surrogatepass"))
        if not siguiente:
            break
        i += siguiente
    return nombres


class OyenteInotify:
    """El oyente de Linux: un descriptor de inotify sobre la carpeta del buzón.

    Attributes:
        fd: El descriptor que espera el vigía; -1 una vez cerrado.
    """

    def __init__(self, fd: int, nombre: str) -> None:
        self.fd = fd
        self._nombre = nombre

    def leer(self) -> bool:
        """Vacía el descriptor y dice si lo que ha llegado es del buzón."""
        es_el_buzon = False
        while self.fd >= 0:
            try:
                datos = os.read(self.fd, 16 * 1024)
            except InterruptedError:
                continue
            except OSError:
                break                       # vacío (`EAGAIN`) o cerrado
            if not datos:
                break
            if self._nombre in nombres_de_inotify(datos):
                es_el_buzon = True
        return es_el_buzon

    def cerrar(self) -> None:
        """Cierra el descriptor."""
        if self.fd >= 0:
            try:
                os.close(self.fd)
            except OSError:
                pass
        self.fd = -1


class OyenteWindows:
    """El oyente de Windows: un hilo que lee los cambios de la carpeta del buzón.

    Args:
        carpeta: La carpeta del agente.
        nombre: El nombre del buzón.
        avisar: A quién se llama, desde el hilo, cuando el buzón cambia.

    Attributes:
        fd: `None`: no hay descriptor que esperar; avisa el hilo.
    """

    def __init__(self, carpeta: str, nombre: str, avisar: Callable[[], None]) -> None:
        from ctypes import wintypes as wt

        self.fd = None
        self._nombre = nombre.lower()
        self._avisar = avisar
        self._cerrado = False
        k = self._k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateFileW.restype = wt.HANDLE
        k.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID, wt.DWORD,
                                  wt.DWORD, wt.HANDLE]
        k.ReadDirectoryChangesW.restype = wt.BOOL
        k.ReadDirectoryChangesW.argtypes = [wt.HANDLE, wt.LPVOID, wt.DWORD, wt.BOOL, wt.DWORD,
                                            wt.LPDWORD, wt.LPVOID, wt.LPVOID]
        k.CancelIoEx.argtypes = [wt.HANDLE, wt.LPVOID]
        k.CloseHandle.argtypes = [wt.HANDLE]
        h = k.CreateFileW(carpeta, FILE_LIST_DIRECTORY, FILE_SHARE_TODO, None, OPEN_EXISTING,
                          FILE_FLAG_BACKUP_SEMANTICS, None)
        if h is None or h == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        self._h = h
        self._hilo = threading.Thread(target=self._correr, name="avisos-buzon", daemon=True)
        self._hilo.start()

    def _correr(self) -> None:
        """Es el hilo: cada lectura espera, sin gastar nada, a que cambie algo en la carpeta."""
        from ctypes import wintypes as wt

        bufer = (ctypes.c_uint32 * (TAM_BUFER // 4))()
        leidos = wt.DWORD(0)
        while not self._cerrado:
            if not self._k.ReadDirectoryChangesW(self._h, bufer, TAM_BUFER, False, FILTRO,
                                                 ctypes.byref(leidos), None, None):
                break                       # cancelada al cerrar, o la carpeta ya no está
            datos = ctypes.string_at(ctypes.addressof(bufer), leidos.value)
            # 0 bytes es que se perdieron avisos: por si acaso, se avisa.
            if not datos or self._nombre in (n.lower() for n in nombres_de_windows(datos)):
                try:
                    self._avisar()
                except Exception:           # noqa: BLE001 — el oyente no se cae por quien escucha
                    pass

    def leer(self) -> bool:
        """No hay nada que leer: avisa el hilo."""
        return False

    def cerrar(self) -> None:
        """Para el hilo y cierra la carpeta."""
        self._cerrado = True
        self._k.CancelIoEx(self._h, None)
        self._k.CloseHandle(self._h)
        if self._hilo is not threading.current_thread():
            self._hilo.join(2.0)


def abrir(carpeta: Path | str, nombre: str, avisar: Callable[[], None]) -> Any | None:
    """Empieza a oír el buzón `nombre` de `carpeta`.

    Args:
        carpeta: La carpeta del agente (`equipo.DIR`); tiene que existir.
        nombre: El nombre del fichero del buzón.
        avisar: En Windows, a quién llama el hilo del oyente cuando el buzón
            cambia. En Linux no se usa: quien espera el `fd` llama a `leer()`.

    Returns:
        El oyente (`cerrar()`, `fd`, `leer()`), o `None` si aquí no se puede.
    """
    try:
        if ES_WINDOWS:
            return OyenteWindows(os.fspath(carpeta), nombre, avisar)
        if not ES_LINUX:
            return None
        libc = ctypes.CDLL(None, use_errno=True)
        libc.inotify_init1.argtypes = [ctypes.c_int]
        libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if fd < 0:
            return None
        if libc.inotify_add_watch(fd, os.fsencode(os.fspath(carpeta)),
                                  IN_CLOSE_WRITE | IN_MOVED_TO | IN_CREATE) < 0:
            os.close(fd)
            return None
        return OyenteInotify(fd, nombre)
    except (OSError, AttributeError):
        return None
