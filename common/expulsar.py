#!/usr/bin/env python3
"""Expulsar un volumen extraíble desde el agente, sin pasar por su ventana.

Es lo que hace el «Expulsar» del desplegable de una unidad en la bandeja
(`agente.Agente._expulsiones()`): el agente suelta la unidad y esto la
desmonta y, donde se puede, la apaga, para poder tirar del cable sin estropear
lo de dentro.

Solo se ofrece de un volumen COMPATIBLE: uno que el sistema monta directamente
de un dispositivo extraíble (USB o tarjeta). No lo son:
- Las raíces de este equipo, que son carpetas.
- Lo que vive dentro de un contenedor VeraCrypt: su volumen es virtual y se
  cierra con «Bloquear» o con «Expulsar PRDRIVE» (`common/vestibulo.py`).
- Un disco interno.

Nunca se fuerza: con algo abierto dentro, la unidad no se suelta y se dice. Las
dos mitades de este módulo (`compatible()` y `expulsar()`) son puntos de
indirección que los tests sustituyen, como las llamadas al sistema que hay
debajo (`_ejecutar()`, `_bus_windows()`, `_expulsar_windows()`).
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

IS_WIN = os.name == "nt"

SYS_BLOCK = Path("/sys/class/block")
"""Los dispositivos de bloque en sysfs (Linux); los tests apuntan a uno de mentira."""

ESPERA_ORDEN = 30.0  # segundos que se espera a `udisksctl`
INTENTOS_BLOQUEO = 4
"""Cuántas veces se intenta bloquear el volumen en Windows, medio segundo entre una y otra.

Un escritor lento (la caché que se vacía, un antivirus que acaba de mirarlo)
suelta el volumen enseguida; algo abierto de verdad, no.
"""

BUS_USB, BUS_SD, BUS_MMC = 7, 12, 13
"""`STORAGE_BUS_TYPE` de un pendrive USB y de las tarjetas SD y MMC (`ntddstor.h`)."""
BUS_EXTRAIBLES = (BUS_USB, BUS_SD, BUS_MMC)
"""Los buses de lo que se puede expulsar, aunque el dispositivo se declare fijo.

Un pendrive que se presenta como `Fixed` es la norma y no la excepción
(`install/device.list_volumes()`): por eso no basta el tipo de unidad y se mira
el bus.
"""


@dataclass(frozen=True)
class Resultado:
    """Cómo acabó una expulsión.

    Args:
        ok: Si la unidad quedó suelta y se puede quitar.
        texto: Lo que hay que decirle a la persona: cómo va a quitarla, o por
            qué no ha sido posible.
    """
    ok: bool
    texto: str = ""


def _ejecutar(cmd: list[str]) -> tuple[int, str]:
    """Ejecuta una orden sin consola ni entrada y devuelve su código y su salida.

    Returns:
        `(código, salida)`. Si no se puede lanzar o no acaba en `ESPERA_ORDEN`,
        el código es 127 y la salida dice por qué.
    """
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           stdin=subprocess.DEVNULL, timeout=ESPERA_ORDEN)
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)
    return r.returncode, (r.stderr or r.stdout or "").strip()


# --- Linux ---------------------------------------------------------------

def _origen(raiz: Path) -> str | None:
    """Devuelve el dispositivo de bloque (`/dev/sdb1`) montado en `raiz`, o `None`.

    Mira la tabla de montajes de `penwatch` (el mismo recorrido de unidades de
    todo el proyecto). Si hay varios montajes apilados en el mismo punto, el
    último.
    """
    import penwatch
    try:
        destino = raiz.resolve()
        origen = None
        for linea in penwatch.MOUNTS_FILE.read_text(encoding="utf-8").splitlines():
            partes = linea.split()
            if len(partes) >= 2 and partes[0].startswith("/dev/") \
                    and Path(penwatch._unescape_mount(partes[1])) == destino:
                origen = partes[0]
    except OSError:
        return None
    return origen


def _disco(origen: str) -> str | None:
    """Devuelve el nombre del disco entero al que pertenece ese dispositivo de bloque.

    `/dev/sdb1` es `sdb`; `/dev/sdb`, `sdb`. Con los enlaces resueltos
    (`/dev/mapper/x` es `dm-0`). `None` si sysfs no lo conoce.
    """
    nombre = Path(os.path.realpath(origen)).name
    base = SYS_BLOCK / nombre
    if not base.exists():
        return None
    if (base / "partition").exists():
        return Path(os.path.realpath(base)).parent.name
    return nombre


def _extraible_linux(disco: str) -> bool:
    """Indica si ese disco es extraíble: lo declara así o cuelga de un puerto USB.

    Los discos USB externos declaran `removable = 0` y los pendrives `1`; el
    camino de sysfs de los dos pasa por `usbN`. Un contenedor (`dm-N`) o un
    disco interno no cumple ninguna.
    """
    base = SYS_BLOCK / disco
    try:
        if (base / "removable").read_text(encoding="utf-8").strip() == "1":
            return True
    except OSError:
        pass
    return "/usb" in os.path.realpath(base)


def _compatible_linux(raiz: Path) -> bool:
    """Indica si `raiz` es un volumen extraíble montado que `udisksctl` sabe soltar."""
    if shutil.which("udisksctl") is None:
        return False
    origen = _origen(raiz)
    disco = _disco(origen) if origen else None
    return disco is not None and _extraible_linux(disco)


def _motivo_linux(salida: str) -> str:
    """Devuelve el motivo por el que `udisksctl` no ha podido desmontar, en cristiano."""
    if "busy" in salida.lower():
        return ("Algo la está usando: cierra lo que tenga abierto de ella (una ventana "
                "del explorador, un programa) y vuelve a pedirlo.")
    return salida.splitlines()[0] if salida else "El sistema no ha podido desmontarla."


def _expulsar_linux(raiz: Path) -> Resultado:
    """Desmonta el volumen con `udisksctl` y apaga su disco, sin forzar nada.

    Si `unmount` falla, la unidad sigue montada y se dice por qué. Apagar el
    disco es un extra: si falla (otra partición montada, un disco que no se
    deja), con el volumen ya desmontado se puede quitar igual.
    """
    udisks = shutil.which("udisksctl")
    origen = _origen(raiz)
    if udisks is None or origen is None:
        return Resultado(False, "Esta unidad ya no está montada aquí, o el sistema no "
                                "tiene udisks para soltarla.")
    rc, salida = _ejecutar([udisks, "unmount", "-b", origen])
    if rc != 0:
        return Resultado(False, _motivo_linux(salida))
    disco = _disco(origen)
    if disco is not None:
        _ejecutar([udisks, "power-off", "-b", f"/dev/{disco}"])
    return Resultado(True, "Ya puedes quitarla.")


# --- Windows -------------------------------------------------------------

def _letra(raiz: Path) -> str | None:
    """Devuelve la letra de la raíz de una unidad de Windows (`E:`), o `None`.

    Una carpeta cualquiera, aunque cuelgue de una letra, no es una unidad.
    """
    texto = str(raiz)
    if len(texto) >= 2 and texto[0].isalpha() and texto[1] == ":" \
            and not texto[2:].strip("\\/"):
        return texto[:2].upper()
    return None


FSCTL_LOCK_VOLUME = 0x00090018
FSCTL_DISMOUNT_VOLUME = 0x00090020
IOCTL_STORAGE_MEDIA_REMOVAL = 0x002D4804
IOCTL_STORAGE_EJECT_MEDIA = 0x002D4808
IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
"""Los códigos de `DeviceIoControl` que usa la expulsión (`winioctl.h`)."""


def _kernel32():
    """Devuelve kernel32 con los prototipos de lo que usa esto (solo Windows)."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                wintypes.HANDLE]
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID,
                                    wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                    ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    k32.DeviceIoControl.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    return k32


def _ioctl(k32, handle, codigo: int, entrada: bytes = b"", salida: int = 0) -> bytes | None:
    """Hace un `DeviceIoControl` y devuelve lo que contesta (vacío si no contesta nada).

    Returns:
        Los bytes de salida, o `None` si el sistema lo ha rechazado.
    """
    import ctypes
    from ctypes import wintypes
    ent = ctypes.create_string_buffer(entrada, max(len(entrada), 1))
    sal = ctypes.create_string_buffer(max(salida, 1))
    devueltos = wintypes.DWORD(0)
    ok = k32.DeviceIoControl(handle, codigo, ent if entrada else None, len(entrada),
                             sal if salida else None, salida, ctypes.byref(devueltos), None)
    return sal.raw[:devueltos.value] if ok else None


def _abrir_volumen(k32, letra: str, acceso: int):
    """Abre el volumen `letra` como dispositivo (`\\\\.\\E:`); `None` si no se puede."""
    import ctypes
    FILE_SHARE_READ, FILE_SHARE_WRITE, OPEN_EXISTING = 1, 2, 3
    handle = k32.CreateFileW(f"\\\\.\\{letra}", acceso, FILE_SHARE_READ | FILE_SHARE_WRITE,
                             None, OPEN_EXISTING, 0, None)
    return None if handle is None or handle == ctypes.c_void_p(-1).value else handle


def _bus_windows(letra: str) -> tuple[bool, int] | None:
    """Devuelve `(extraíble declarado, tipo de bus)` del disco de ese volumen, o `None`.

    Es `IOCTL_STORAGE_QUERY_PROPERTY` con `StorageDeviceProperty`, que no pide
    acceso al volumen: se pregunta con acceso 0. Del `STORAGE_DEVICE_DESCRIPTOR`
    se lee `RemovableMedia` (byte 10) y `BusType` (DWORD en el 28). Un volumen
    virtual (el de VeraCrypt), una unidad de red o una letra que no contesta
    salen como `None` o con un bus que no es de los extraíbles.
    """
    try:
        k32 = _kernel32()
        handle = _abrir_volumen(k32, letra, 0)
        if handle is None:
            return None
        try:
            consulta = struct.pack("<II4x", 0, 0)       # StorageDeviceProperty, estándar
            datos = _ioctl(k32, handle, IOCTL_STORAGE_QUERY_PROPERTY, consulta, 1024)
        finally:
            k32.CloseHandle(handle)
    except (OSError, AttributeError):
        return None
    if datos is None or len(datos) < 32:
        return None
    return datos[10] != 0, struct.unpack_from("<I", datos, 28)[0]


def _compatible_windows(raiz: Path) -> bool:
    """Indica si `raiz` es la letra de un volumen USB o de tarjeta que no es el del sistema."""
    letra = _letra(raiz)
    if letra is None or letra == os.environ.get("SystemDrive", "C:").upper():
        return False
    dato = _bus_windows(letra)
    return dato is not None and (dato[0] or dato[1] in BUS_EXTRAIBLES)


def _expulsar_windows(letra: str) -> Resultado:
    """Bloquea, desmonta y expulsa el volumen `letra`, sin forzar.

    Es lo que hace el «Quitar de forma segura» del sistema por debajo: con el
    volumen bloqueado (`FSCTL_LOCK_VOLUME`) nadie más lo tiene abierto, así que
    desmontarlo vacía lo pendiente y es seguro quitarlo. Si el bloqueo no se
    consigue (un programa o una ventana del Explorador lo usa), no se desmonta
    ni se fuerza. Si tras desmontar el sistema no expulsa el medio (algunos
    pendrives se declaran fijos), el volumen ya está desmontado y se puede
    quitar igual.
    """
    k32 = _kernel32()
    handle = _abrir_volumen(k32, letra, 0xC0000000)        # GENERIC_READ | GENERIC_WRITE
    if handle is None:
        return Resultado(False, f"El sistema no deja abrir la unidad {letra}.")
    try:
        for intento in range(INTENTOS_BLOQUEO):
            if _ioctl(k32, handle, FSCTL_LOCK_VOLUME) is not None:
                break
            if intento < INTENTOS_BLOQUEO - 1:
                time.sleep(0.5)
        else:
            return Resultado(False, f"Algo está usando la unidad {letra}: cierra lo que "
                                    f"tenga abierto de ella (una ventana del Explorador, "
                                    f"un programa) y vuelve a pedirlo.")
        if _ioctl(k32, handle, FSCTL_DISMOUNT_VOLUME) is None:
            return Resultado(False, f"El sistema no ha podido desmontar la unidad {letra}.")
        _ioctl(k32, handle, IOCTL_STORAGE_MEDIA_REMOVAL, b"\0")     # no impedir sacarlo
        _ioctl(k32, handle, IOCTL_STORAGE_EJECT_MEDIA)
        return Resultado(True, "Ya puedes quitarla.")
    finally:
        k32.CloseHandle(handle)


# --- Lo que usa el agente ------------------------------------------------

def compatible(raiz: Path) -> bool:
    """Indica si se puede ofrecer «Expulsar» de la unidad montada en `raiz`.

    Es verdad solo de un volumen que el sistema monta directamente de un
    dispositivo extraíble y que este equipo sabe soltar (Linux con `udisksctl`;
    Windows con una letra de USB o tarjeta que no sea la del sistema). Es un
    punto de indirección: los tests la sustituyen. Lee del sistema, así que no
    se llama en cada vuelta (`agente.Agente._compatible()`).
    """
    try:
        return _compatible_windows(raiz) if IS_WIN else _compatible_linux(raiz)
    except OSError:
        return False


def expulsar(raiz: Path) -> Resultado:
    """Suelta la unidad montada en `raiz` y dice cómo ha ido.

    Bloquea mientras dura (en Linux, hasta `ESPERA_ORDEN`): se llama desde un
    hilo. Nunca fuerza, y nunca lanza: lo que salga mal es un `Resultado` que
    no es `ok`. Es un punto de indirección: los tests la sustituyen.
    """
    try:
        if not IS_WIN:
            return _expulsar_linux(raiz)
        letra = _letra(raiz)
        if letra is None:
            return Resultado(False, f"{raiz} no es la raíz de una unidad.")
        return _expulsar_windows(letra)
    except Exception as e:                              # noqa: BLE001
        return Resultado(False, f"No he podido expulsarla: {e}")
