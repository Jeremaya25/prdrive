#!/usr/bin/env python3
"""La prioridad de las pasadas que nadie está mirando.

Una pasada del servicio o del agente no tiene a nadie esperando, así que cede
el procesador y el disco a lo que el usuario esté haciendo. No la hace más
barata: la aparta cuando hay competencia, y sin competencia va igual de
rápida. Nunca lanza: si no se puede bajar, la pasada va como siempre.

- Windows: la clase `BELOW_NORMAL_PRIORITY_CLASS` (`SetPriorityClass`). La
  heredan sus hijos: `CreateProcess` da a un hijo que no pide clase la de su
  padre cuando esta es `IDLE_PRIORITY_CLASS` o `BELOW_NORMAL_PRIORITY_CLASS`,
  así que el rclone de la pasada va igual. La prioridad de E/S y la de memoria
  no tienen una API documentada para otro proceso y se quedan como estén.
- Linux: `nice` 10 (`setpriority(2)`) y la clase de E/S «best effort» al
  nivel 7, el más bajo (`ioprio_set(2)`). No la «idle»: con el disco ocupado
  puede no avanzar nada, y el lock de bisync (`--max-lock`) caduca si no se
  renueva. Las dos se heredan en `fork(2)`. Las dos son de cada hilo: se
  bajan antes de que el proceso lance nada.
"""

from __future__ import annotations

import os
import platform
import sys

IS_WIN = os.name == "nt"

CLASE_WINDOWS = 0x00004000
"""`BELOW_NORMAL_PRIORITY_CLASS`: la clase de una pasada desatendida en Windows.

Sirve también como `creationflags` de `subprocess.Popen`, que la pasa tal cual
a `CreateProcess`.
"""
_CLASES_BAJAS_WINDOWS = (0x00000040, CLASE_WINDOWS)  # IDLE y BELOW_NORMAL
_PROCESS_SET_INFORMATION = 0x0200
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

NICE = 10
"""El `nice` de una pasada desatendida en POSIX; uno mayor se respeta."""

IOPRIO_CLASE_BE = 2
"""`IOPRIO_CLASS_BE`, «best effort» (`include/uapi/linux/ioprio.h`)."""
IOPRIO_CLASE_IDLE = 3
"""`IOPRIO_CLASS_IDLE`: solo cuando nadie más usa el disco; se respeta si ya está."""
IOPRIO_NIVEL = 7
"""El nivel más bajo de la clase «best effort» (0 es el más alto)."""
_IOPRIO_WHO_PROCESS = 1
_IOPRIO_CLASS_SHIFT = 13

LLAMADAS_IOPRIO = {
    "x86_64": (251, 252), "amd64": (251, 252),
    "aarch64": (30, 31), "arm64": (30, 31),
    "i386": (289, 290), "i686": (289, 290),
    "armv7l": (314, 315), "armv6l": (314, 315),
}
"""Números de `ioprio_set` e `ioprio_get` por CPU, en Linux.

Son los de las tablas del kernel (`arch/x86/entry/syscalls/syscall_64.tbl` y
`syscall_32.tbl`, `include/uapi/asm-generic/unistd.h` para arm64 y
`arch/arm/tools/syscall.tbl`): la biblioteca estándar no trae la llamada.
"""


def bajar(pid: int | None = None) -> bool:
    """Baja la prioridad de ese proceso, o la del que llama; nunca la sube ni lanza.

    Args:
        pid: El proceso; sin él, el que llama (en Linux, su hilo).

    Returns:
        `True` si queda con prioridad baja; `False` si no se ha podido (el
        proceso ya no existe, o el sistema no deja).
    """
    try:
        if IS_WIN:
            return _bajar_windows(pid)
        return _bajar_posix(0 if pid is None else pid)
    except Exception:                                   # noqa: BLE001
        return False


def _bajar_windows(pid: int | None) -> bool:
    """Pone `BELOW_NORMAL_PRIORITY_CLASS` con `SetPriorityClass`, si no tiene ya una baja."""
    import ctypes
    from ctypes import wintypes

    # Una biblioteca propia: los argtypes no se mezclan con los de `ctypes.windll`.
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.GetPriorityClass.argtypes = (wintypes.HANDLE,)
    k32.GetPriorityClass.restype = wintypes.DWORD
    k32.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    k32.SetPriorityClass.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    if pid is None:
        handle, propio = k32.GetCurrentProcess(), True
    else:
        handle = k32.OpenProcess(
            _PROCESS_SET_INFORMATION | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        propio = False
    try:
        if k32.GetPriorityClass(handle) in _CLASES_BAJAS_WINDOWS:
            return True
        return bool(k32.SetPriorityClass(handle, CLASE_WINDOWS))
    finally:
        if not propio:
            k32.CloseHandle(handle)


def _bajar_posix(pid: int) -> bool:
    """Sube el `nice` hasta `NICE` y pone la E/S en «best effort» 7, si no estaban más bajos."""
    if os.getpriority(os.PRIO_PROCESS, pid) < NICE:
        os.setpriority(os.PRIO_PROCESS, pid, NICE)
    actual = leer_ioprio(pid)
    if actual is not None and actual[0] != IOPRIO_CLASE_IDLE \
            and actual != (IOPRIO_CLASE_BE, IOPRIO_NIVEL):
        _poner_ioprio(pid, IOPRIO_CLASE_BE, IOPRIO_NIVEL)
    return True


def _llamadas() -> tuple[int, int] | None:
    """Devuelve los números de `ioprio_set` e `ioprio_get` de esta CPU, o `None`."""
    if not sys.platform.startswith("linux"):
        return None
    return LLAMADAS_IOPRIO.get(platform.machine().lower())


def _syscall(*args: int) -> int:
    """Hace la llamada al sistema con esos argumentos; -1 si falla."""
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    return libc.syscall(*args)


def leer_ioprio(pid: int) -> tuple[int, int] | None:
    """Devuelve la clase y el nivel de E/S de ese proceso (0, el que llama).

    Returns:
        `(clase, nivel)` como los da `ioprio_get(2)`, o `None` fuera de Linux,
        en una CPU que no está en `LLAMADAS_IOPRIO` o si la llamada falla.
    """
    llamadas = _llamadas()
    if llamadas is None:
        return None
    valor = _syscall(llamadas[1], _IOPRIO_WHO_PROCESS, pid)
    if valor < 0:
        return None
    return valor >> _IOPRIO_CLASS_SHIFT, valor & ((1 << _IOPRIO_CLASS_SHIFT) - 1)


def _poner_ioprio(pid: int, clase: int, nivel: int) -> bool:
    """Pone con `ioprio_set(2)` esa clase y nivel de E/S; dice si se ha podido."""
    llamadas = _llamadas()
    if llamadas is None:
        return False
    valor = (clase << _IOPRIO_CLASS_SHIFT) | nivel
    return _syscall(llamadas[0], _IOPRIO_WHO_PROCESS, pid, valor) == 0
