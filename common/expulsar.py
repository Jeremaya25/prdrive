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
debajo (`_ejecutar()`, `_bus_windows()`, `_cadena_windows()`,
`_retirar_dispositivo()`, `_expulsar_windows()`).

En Windows, tras bloquear y desmontar el volumen se pide la retirada del
DISPOSITIVO, como el «Quitar hardware de forma segura» (`CM_Request_Device_EjectW`):
con solo expulsar el medio (`IOCTL_STORAGE_EJECT_MEDIA`) el dispositivo y su
letra seguían en el Explorador hasta quitar el pendrive. Si Windows lo veta se
dice por qué; si no hay dispositivo extraíble que retirar (un disco virtual),
se hace lo de siempre y se expulsa el medio.
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
IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x002D1080
"""Los códigos de `DeviceIoControl` que usa la expulsión (`winioctl.h`)."""

FILE_DEVICE_DISK = 7
"""`STORAGE_DEVICE_NUMBER.DeviceType` de un disco (`winioctl.h`)."""
CM_DEVCAP_REMOVABLE = 0x00000004
CM_DRP_CAPABILITIES = 0x00000010
CR_SUCCESS = 0x00000000
CR_REMOVE_VETOED = 0x00000017
"""Lo que usa el árbol de dispositivos (`cfgmgr32.h`): la capacidad de ser extraíble,
la propiedad que la lleva y los `CONFIGRET` que distinguen el sí del veto."""
GUID_DEVINTERFACE_DISK = "53f56307-b6bf-11d0-94f2-00a0c91efb8b"
DEVPKEY_INSTANCE_ID = ("78c34fc8-104a-4aca-9ea4-524d52996e57", 256)
"""La clase de interfaz de los discos y la propiedad con el id de instancia de un dispositivo
(`devpkey.h`: `DEVPKEY_Device_InstanceId`)."""
PROFUNDIDAD_MAXIMA = 16
"""Cuántos padres se suben como mucho: el árbol de un USB no pasa de media docena."""
LARGO_VETO = 260
"""Cuántos caracteres caben en el nombre de quien veta (`MAX_PATH`)."""

PNP_VETOS = {
    0: "Windows no da más explicación.",
    1: "Un dispositivo antiguo ({nombre}) no deja quitarla.",
    2: "Windows está cerrando lo que tenía abierto de ella: vuelve a pedirlo en unos segundos.",
    3: "Un programa la está usando ({nombre}): ciérralo y vuelve a pedirlo.",
    4: "Un servicio de Windows la está usando ({nombre}).",
    5: "Algo la tiene abierta ({nombre}): ciérralo y vuelve a pedirlo.",
    6: "Otro dispositivo depende de ella ({nombre}).",
    7: "Su controlador no deja quitarla ({nombre}).",
    8: "Windows no deja quitarla ahora.",
    9: "No hay energía bastante en el equipo para quitarla ahora.",
    10: "Windows no deja desactivarla ({nombre}).",
    11: "Un controlador antiguo ({nombre}) no deja quitarla.",
    12: "Faltan permisos para quitarla: prueba con una cuenta de administrador.",
}
"""Lo que Windows quiere decir con cada `PNP_VETO_TYPE` (`winnt.h`), en palabras.

`{nombre}` es quien veta: un programa, un servicio o un dispositivo, según el
tipo; si Windows no lo da se quita del texto (`_texto_veto()`).
"""


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


def _abrir_ruta(k32, ruta: str, acceso: int):
    """Abre `ruta` (un volumen o un dispositivo) con ese acceso; `None` si no se puede."""
    import ctypes
    FILE_SHARE_READ, FILE_SHARE_WRITE, OPEN_EXISTING = 1, 2, 3
    handle = k32.CreateFileW(ruta, acceso, FILE_SHARE_READ | FILE_SHARE_WRITE,
                             None, OPEN_EXISTING, 0, None)
    return None if handle is None or handle == ctypes.c_void_p(-1).value else handle


def _abrir_volumen(k32, letra: str, acceso: int):
    """Abre el volumen `letra` como dispositivo (`\\\\.\\E:`); `None` si no se puede."""
    return _abrir_ruta(k32, f"\\\\.\\{letra}", acceso)


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


@dataclass(frozen=True)
class Nodo:
    """Un dispositivo del árbol de Windows entre el disco de un volumen y la raíz.

    Args:
        id: Su id de instancia (`USB\\VID_…\\<serie>`), con el que se vuelve a
            localizar.
        extraible: Si se declara extraíble (`CM_DEVCAP_REMOVABLE`).
    """
    id: str
    extraible: bool


def _bytes_de(guid: str, pid: int | None = None):
    """Devuelve un búfer con ese GUID en el formato de Win32 (y, con `pid`, una `DEVPROPKEY`).

    Es lo que esperan `cfgmgr32` y `setupapi` por puntero: el GUID en
    pequeño-endian y, en la clave de una propiedad, su `pid` detrás. Un búfer en
    vez de una `Structure` porque solo se pasa por puntero.
    """
    import ctypes
    import uuid
    crudo = uuid.UUID(guid).bytes_le
    if pid is not None:
        crudo += struct.pack("<I", pid)
    return ctypes.create_string_buffer(crudo, len(crudo))


def _cfgmgr32():
    """Devuelve cfgmgr32 con los prototipos de lo que usa esto (solo Windows).

    Todos los `CONFIGRET` son `DWORD` y todos los `DEVINST`, también.
    """
    import ctypes
    from ctypes import wintypes
    cm = ctypes.WinDLL("cfgmgr32", use_last_error=True)
    ulong_p = ctypes.POINTER(wintypes.ULONG)
    dword_p = ctypes.POINTER(wintypes.DWORD)
    cm.CM_Get_Device_Interface_List_SizeW.argtypes = [ulong_p, ctypes.c_void_p,
                                                      wintypes.LPCWSTR, wintypes.ULONG]
    cm.CM_Get_Device_Interface_ListW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                                 ctypes.c_void_p, wintypes.ULONG,
                                                 wintypes.ULONG]
    cm.CM_Get_Device_Interface_PropertyW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p,
                                                     ulong_p, ctypes.c_void_p, ulong_p,
                                                     wintypes.ULONG]
    cm.CM_Locate_DevNodeW.argtypes = [dword_p, wintypes.LPCWSTR, wintypes.ULONG]
    cm.CM_Get_DevNode_Registry_PropertyW.argtypes = [wintypes.DWORD, wintypes.ULONG, ulong_p,
                                                     ctypes.c_void_p, ulong_p, wintypes.ULONG]
    cm.CM_Get_Parent.argtypes = [dword_p, wintypes.DWORD, wintypes.ULONG]
    cm.CM_Get_Device_IDW.argtypes = [wintypes.DWORD, ctypes.c_void_p, wintypes.ULONG,
                                     wintypes.ULONG]
    cm.CM_Request_Device_EjectW.argtypes = [wintypes.DWORD, ctypes.POINTER(ctypes.c_int),
                                            ctypes.c_void_p, wintypes.ULONG, wintypes.ULONG]
    for nombre in ("CM_Get_Device_Interface_List_SizeW", "CM_Get_Device_Interface_ListW",
                   "CM_Get_Device_Interface_PropertyW", "CM_Locate_DevNodeW",
                   "CM_Get_DevNode_Registry_PropertyW", "CM_Get_Parent",
                   "CM_Get_Device_IDW", "CM_Request_Device_EjectW"):
        getattr(cm, nombre).restype = wintypes.DWORD
    return cm


def _numero_de_dispositivo(k32, ruta: str) -> tuple[int, int] | None:
    """Devuelve `(tipo, número)` del disco que hay detrás de esa ruta de dispositivo, o `None`.

    Es `IOCTL_STORAGE_GET_DEVICE_NUMBER` (`STORAGE_DEVICE_NUMBER`: tipo,
    número y partición, tres DWORD), que no pide acceso: se pregunta con 0.
    """
    handle = _abrir_ruta(k32, ruta, 0)
    if handle is None:
        return None
    try:
        datos = _ioctl(k32, handle, IOCTL_STORAGE_GET_DEVICE_NUMBER, b"", 12)
    finally:
        k32.CloseHandle(handle)
    if datos is None or len(datos) < 8:
        return None
    tipo, numero = struct.unpack_from("<II", datos, 0)
    return tipo, numero


def _rutas_de_discos(cm) -> list[str]:
    """Devuelve las rutas de las interfaces de disco presentes (`GUID_DEVINTERFACE_DISK`)."""
    import ctypes
    from ctypes import wintypes
    guid = _bytes_de(GUID_DEVINTERFACE_DISK)
    largo = wintypes.ULONG(0)
    if cm.CM_Get_Device_Interface_List_SizeW(ctypes.byref(largo), guid,
                                             None, 0) != CR_SUCCESS or largo.value < 2:
        return []
    buffer = ctypes.create_unicode_buffer(largo.value)
    if cm.CM_Get_Device_Interface_ListW(guid, None, buffer, largo.value, 0) != CR_SUCCESS:
        return []
    return [r for r in ctypes.wstring_at(buffer, largo.value).split("\0") if r]


def _instancia_de_interfaz(cm, ruta: str) -> str | None:
    """Devuelve el id de instancia del dispositivo de esa interfaz, o `None` (`DEVPKEY_Device_InstanceId`)."""
    import ctypes
    from ctypes import wintypes
    clave = _bytes_de(*DEVPKEY_INSTANCE_ID)
    tipo = wintypes.ULONG(0)
    largo = wintypes.ULONG(LARGO_VETO * 2)             # bytes: es una cadena UTF-16
    buffer = ctypes.create_string_buffer(largo.value)
    if cm.CM_Get_Device_Interface_PropertyW(ruta, clave, ctypes.byref(tipo),
                                            buffer, ctypes.byref(largo), 0) != CR_SUCCESS:
        return None
    return ctypes.wstring_at(buffer, largo.value // 2).rstrip("\0") or None


def _nodo(cm, devinst: int) -> Nodo | None:
    """Devuelve el nodo de ese `DEVINST`: su id y si se declara extraíble, o `None`."""
    import ctypes
    from ctypes import wintypes
    buffer = ctypes.create_unicode_buffer(LARGO_VETO)
    if cm.CM_Get_Device_IDW(devinst, buffer, LARGO_VETO, 0) != CR_SUCCESS:
        return None
    capacidades = wintypes.ULONG(0)
    largo = wintypes.ULONG(4)
    if cm.CM_Get_DevNode_Registry_PropertyW(devinst, CM_DRP_CAPABILITIES, None,
                                            ctypes.byref(capacidades), ctypes.byref(largo),
                                            0) != CR_SUCCESS:
        capacidades.value = 0
    return Nodo(buffer.value, bool(capacidades.value & CM_DEVCAP_REMOVABLE))


def _cadena_windows(letra: str) -> list[Nodo] | None:
    """Devuelve el disco del volumen `letra` y sus padres hasta la raíz, o `None`.

    Es el camino volumen → disco → `CM_Get_Parent`: el número de dispositivo del
    volumen (`IOCTL_STORAGE_GET_DEVICE_NUMBER`) dice qué interfaz de disco es
    el suyo, de ella sale su dispositivo y de él, subiendo, los demás. El
    primero de la lista es el disco; el último, lo más alto que se alcanzó.
    `None` si algo no se deja preguntar: un volumen que abarca varios discos, uno
    que no es de disco, un sistema que no contesta. Un punto de indirección: los
    tests lo sustituyen.
    """
    import ctypes
    from ctypes import wintypes
    k32, cm = _kernel32(), _cfgmgr32()
    handle = _abrir_volumen(k32, letra, 0)
    if handle is None:
        return None
    try:
        numero = _ioctl(k32, handle, IOCTL_STORAGE_GET_DEVICE_NUMBER, b"", 12)
    finally:
        k32.CloseHandle(handle)
    if numero is None or len(numero) < 8:
        return None
    buscado = struct.unpack_from("<II", numero, 0)
    if buscado[0] != FILE_DEVICE_DISK:
        return None
    instancia = None
    for ruta in _rutas_de_discos(cm):
        if _numero_de_dispositivo(k32, ruta) == buscado:
            instancia = _instancia_de_interfaz(cm, ruta)
            break
    devinst = wintypes.DWORD(0)
    if instancia is None or cm.CM_Locate_DevNodeW(ctypes.byref(devinst), instancia, 0) != CR_SUCCESS:
        return None
    cadena: list[Nodo] = []
    actual = devinst.value
    for _ in range(PROFUNDIDAD_MAXIMA):
        nodo = _nodo(cm, actual)
        if nodo is None:
            break
        cadena.append(nodo)
        padre = wintypes.DWORD(0)
        if cm.CM_Get_Parent(ctypes.byref(padre), actual, 0) != CR_SUCCESS:
            break
        actual = padre.value
    return cadena or None


def _elegir_nodo(cadena: list[Nodo]) -> Nodo | None:
    """Elige qué dispositivo se retira: el primer padre del disco que se declara extraíble.

    Es el dispositivo que Windows enseña en «Quitar hardware de forma segura»
    (para un pendrive, el «dispositivo de almacenamiento masivo USB» y no su
    disco). Si ningún padre lo es, el propio disco, si lo es (un lector de
    tarjetas con el disco colgando de otro tipo de bus). `None` si nada de la
    cadena se declara extraíble: un disco virtual o uno interno.
    """
    for nodo in cadena[1:]:
        if nodo.extraible:
            return nodo
    return cadena[0] if cadena and cadena[0].extraible else None


def _dispositivo_a_retirar(letra: str) -> Nodo | None:
    """Devuelve el dispositivo que hay que retirar tras soltar el volumen, o `None`.

    Solo de un volumen que `_bus_windows()` da por extraíble (el criterio de
    `compatible()`: un bus USB, SD o MMC, o `RemovableMedia`): un disco virtual
    que cuelga de un árbol con algo extraíble no se retira. Sin dispositivo, la
    expulsión sigue como siempre, expulsando el medio.
    """
    dato = _bus_windows(letra)
    if dato is None or not (dato[0] or dato[1] in BUS_EXTRAIBLES):
        return None
    try:
        cadena = _cadena_windows(letra)
    except (OSError, AttributeError):
        return None
    return _elegir_nodo(cadena) if cadena else None


def _pedir_retirada(cm, devinst: int) -> tuple[int, int, str]:
    """Pide a Windows retirar ese `DEVINST` (`CM_Request_Device_EjectW`) y devuelve su contestación.

    Returns:
        `(CONFIGRET, tipo de veto, nombre de quien veta)`. Con `CR_SUCCESS` el
        dispositivo se ha ido; con `CR_REMOVE_VETOED`, los otros dos dicen por qué no.
    """
    import ctypes
    veto = ctypes.c_int(0)
    nombre = ctypes.create_unicode_buffer(LARGO_VETO)
    cr = cm.CM_Request_Device_EjectW(devinst, ctypes.byref(veto), nombre, LARGO_VETO, 0)
    return cr, veto.value, nombre.value


def _retirar_dispositivo(instancia: str) -> tuple[int, int, str]:
    """Retira el dispositivo de ese id de instancia como el «Quitar hardware de forma segura».

    Se vuelve a localizar por su id (un `DEVINST` guardado de antes podría ser
    de otro) y se pide la retirada: es lo que hace desaparecer su letra del
    Explorador. Espera a que Windows acabe. Un punto de indirección: los tests
    lo sustituyen.

    Returns:
        Lo de `_pedir_retirada()`; si ni siquiera se encuentra el dispositivo, el
        `CONFIGRET` de esa búsqueda y nada más.
    """
    import ctypes
    from ctypes import wintypes
    cm = _cfgmgr32()
    devinst = wintypes.DWORD(0)
    cr = cm.CM_Locate_DevNodeW(ctypes.byref(devinst), instancia, 0)
    if cr != CR_SUCCESS:
        return cr, 0, ""
    return _pedir_retirada(cm, devinst.value)


def _texto_veto(letra: str, tipo: int, nombre: str) -> str:
    """Devuelve por qué Windows no deja quitar la unidad `letra`, en cristiano."""
    plantilla = PNP_VETOS.get(tipo, PNP_VETOS[0])
    nombre = nombre.strip()
    if not nombre:
        plantilla = plantilla.replace(" ({nombre})", "")
    return f"Windows no deja quitar la unidad {letra}: {plantilla.format(nombre=nombre)}"


def _soltar(k32, handle, letra: str) -> Resultado | None:
    """Bloquea, desmonta y deja sacar el volumen abierto en `handle`, sin forzar.

    Es la secuencia de KB 165721: con el volumen bloqueado (`FSCTL_LOCK_VOLUME`,
    `INTENTOS_BLOQUEO` veces, medio segundo entre una y otra) nadie más lo
    tiene abierto, así que desmontarlo (`FSCTL_DISMOUNT_VOLUME`) vacía lo
    pendiente, y `IOCTL_STORAGE_MEDIA_REMOVAL` no impide sacarlo. Si el bloqueo
    no se consigue no se desmonta ni se fuerza.

    Returns:
        `None` si el volumen queda bloqueado, desmontado y sin impedir sacarlo;
        si no, el `Resultado` (no `ok`) que dice por qué no.
    """
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
    return None


def _expulsar_medio(letra: str) -> bool:
    """Expulsa el medio del volumen (`IOCTL_STORAGE_EJECT_MEDIA`) tras bloquearlo y desmontarlo.

    Se abre el volumen de nuevo y se suelta otra vez (`_soltar()`): abrirlo
    (`GENERIC_READ | GENERIC_WRITE`) no es un acceso directo al dispositivo, así
    que el sistema vuelve a montar el sistema de ficheros, y en ese hueco el
    Explorador o el indexador pueden haberlo abierto. Si la expulsión del medio
    es lo único que falla, la unidad ya está desmontada y se da por suelta.

    Returns:
        `True` si la unidad queda suelta o si el volumen ya no se puede abrir
        (el dispositivo se ha ido); `False` si se ha abierto pero no se ha
        podido bloquear o desmontar.
    """
    k32 = _kernel32()
    handle = _abrir_volumen(k32, letra, 0xC0000000)        # GENERIC_READ | GENERIC_WRITE
    if handle is None:
        return True
    try:
        if _soltar(k32, handle, letra) is not None:
            return False
        _ioctl(k32, handle, IOCTL_STORAGE_EJECT_MEDIA)
        return True
    finally:
        k32.CloseHandle(handle)


def _expulsar_windows(letra: str) -> Resultado:
    """Bloquea, desmonta y retira el dispositivo del volumen `letra`, sin forzar.

    Es lo que hace el «Quitar de forma segura» del sistema por debajo: con el
    volumen bloqueado (`FSCTL_LOCK_VOLUME`) nadie más lo tiene abierto, así que
    desmontarlo vacía lo pendiente y es seguro quitarlo. Si el bloqueo no se
    consigue (un programa o una ventana del Explorador lo usa), no se desmonta
    ni se fuerza.

    Con el volumen desmontado y el manejador cerrado (abierto, el volumen vetaría
    la retirada), se pide a Windows retirar el dispositivo extraíble
    (`_dispositivo_a_retirar()`), que es lo que hace desaparecer su letra; un
    veto se dice con su causa. Sin dispositivo que retirar (un disco virtual,
    uno que no se deja preguntar) se expulsa el medio con el mismo manejador.
    Si Windows no puede ni pedir la retirada, se expulsa el medio abriendo el
    volumen de nuevo y soltándolo otra vez (`_expulsar_medio()`): solo si eso
    tampoco se consigue se dice que no, con el `CONFIGRET`, y nunca que se puede
    quitar.
    """
    nodo = _dispositivo_a_retirar(letra)
    k32 = _kernel32()
    handle = _abrir_volumen(k32, letra, 0xC0000000)        # GENERIC_READ | GENERIC_WRITE
    if handle is None:
        return Resultado(False, f"El sistema no deja abrir la unidad {letra}.")
    try:
        fallo = _soltar(k32, handle, letra)
        if fallo is not None:
            return fallo
        if nodo is None:
            _ioctl(k32, handle, IOCTL_STORAGE_EJECT_MEDIA)
    finally:
        k32.CloseHandle(handle)
    if nodo is None:
        return Resultado(True, "Ya puedes quitarla.")
    cr, tipo, quien = _retirar_dispositivo(nodo.id)
    if cr == CR_REMOVE_VETOED:
        return Resultado(False, _texto_veto(letra, tipo, quien))
    if cr != CR_SUCCESS and not _expulsar_medio(letra):
        return Resultado(False, f"Windows no ha podido retirar la unidad {letra} "
                                f"(CONFIGRET {cr:#04x}) y tampoco se ha podido bloquear "
                                f"y desmontar de nuevo. No la quites todavía: usa "
                                f"«Quitar hardware de forma segura».")
    return Resultado(True, "Ya puedes quitarla.")


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
