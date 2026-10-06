#!/usr/bin/env python3
"""Lo que sabe del sistema `common/expulsar.py`: qué se puede expulsar y cómo.

Nada toca el sistema de verdad:
- Linux: un sysfs y un `/proc/self/mounts` de mentira en un temporal, y un
  `udisksctl` que se apunta en vez de ejecutarse. Es extraíble un pendrive
  (`removable = 1`) y un disco USB (su camino pasa por `usbN`); no lo son un
  disco interno, un volumen de VeraCrypt (`/dev/mapper`) ni una carpeta que no
  es un punto de montaje. Sin `udisksctl`, nada es compatible. Desmonta sin
  forzar y solo apaga el disco si ha desmontado.
- Windows: la letra y el bus (USB, SD, MMC o declarado extraíble; nunca el
  disco del sistema, un volumen virtual ni una carpeta). La expulsión bloquea,
  desmonta y expulsa, y no desmonta si no consigue bloquear; si lo único que
  falla es expulsar el medio, ya está desmontada y se puede quitar.
"""

import os
import shutil
import struct
import time
from pathlib import Path

from _harness import Checks, tmpdir

import penwatch
from common import expulsar

c = Checks("expulsar: qué se puede expulsar y cómo")

# --- Linux ---------------------------------------------------------------
if os.name == "nt":
    print("  (saltado) la mitad de Linux: necesita enlaces simbólicos")
else:
    BASE = tmpdir("prdrive-sysfs-")
    SYS = BASE / "class" / "block"
    SYS.mkdir(parents=True)
    DEV = BASE / "devices"

    def disco(nombre: str, camino: str, removable: str, particion: str | None = None):
        """Crea un disco (y su partición) en el sysfs de mentira."""
        real = DEV / camino / "block" / nombre
        real.mkdir(parents=True)
        (real / "removable").write_text(removable + "\n", encoding="utf-8")
        os.symlink(real, SYS / nombre)
        if particion:
            (real / particion).mkdir()
            (real / particion / "partition").write_text("1\n", encoding="utf-8")
            os.symlink(real / particion, SYS / particion)

    disco("sdb", "pci0/usb1/1-2", "1", "sdb1")       # un pendrive
    disco("sdc", "pci0/usb1/1-3", "0", "sdc1")       # un disco USB
    disco("sda", "pci0/ata1", "0", "sda2")           # el disco interno
    disco("dm-0", "virtual", "0")                    # un volumen de VeraCrypt
    expulsar.SYS_BLOCK = SYS

    MONTAJES = tmpdir("prdrive-montajes-") / "mounts"
    MONTAJES.write_text(
        "/dev/sdb1 /media/u/PEN exfat rw 0 0\n"
        "/dev/sdc1 /media/u/DISCO\\040USB ext4 rw 0 0\n"
        "/dev/sda2 /media/u/INTERNO ext4 rw 0 0\n"
        "/dev/mapper/veracrypt1 /media/veracrypt1 exfat rw 0 0\n"
        "tmpfs /run/user/1000 tmpfs rw 0 0\n", encoding="utf-8")
    penwatch.MOUNTS_FILE = MONTAJES

    ORDENES: list[list[str]] = []
    SALIDA: list[tuple[int, str]] = [(0, "")]
    expulsar._ejecutar = lambda cmd: ORDENES.append(cmd) or SALIDA[0]
    UDISKS = ["/usr/bin/udisksctl"]
    shutil.which = lambda nombre: UDISKS[0] if nombre == "udisksctl" else None
    expulsar.IS_WIN = False

    PEN, USB, INT = Path("/media/u/PEN"), Path("/media/u/DISCO USB"), Path("/media/u/INTERNO")
    c("un pendrive (removable = 1) es compatible", expulsar.compatible(PEN), True)
    c("  un disco USB que no se declara extraíble, también (cuelga de usbN)",
      expulsar.compatible(USB), True)
    c("  el disco interno, no", expulsar.compatible(INT), False)
    c("  un volumen de VeraCrypt (/dev/mapper), no",
      expulsar.compatible(Path("/media/veracrypt1")), False)
    c("  una carpeta que no es un punto de montaje, no",
      expulsar.compatible(Path("/home/u/PRDRIVE")), False)
    c("  ni un montaje que no es de un dispositivo (tmpfs)",
      expulsar.compatible(Path("/run/user/1000")), False)
    UDISKS[0] = None
    c("sin udisksctl, nada es compatible", expulsar.compatible(PEN), False)
    r = expulsar.expulsar(PEN)
    c("  y expulsar lo dice y no lanza nada", (r.ok, ORDENES), (False, []))
    UDISKS[0] = "/usr/bin/udisksctl"

    r = expulsar.expulsar(PEN)
    c("expulsar desmonta la partición y apaga el disco entero",
      ORDENES, [["/usr/bin/udisksctl", "unmount", "-b", "/dev/sdb1"],
                ["/usr/bin/udisksctl", "power-off", "-b", "/dev/sdb"]])
    c("  y dice que ya se puede quitar", (r.ok, r.texto), (True, "Ya puedes quitarla."))

    ORDENES.clear()
    SALIDA[0] = (1, "Error unmounting /dev/sdb1: GDBus.Error:org.freedesktop.UDisks2."
                    "Error.DeviceBusy: target is busy")
    r = expulsar.expulsar(PEN)
    c("con algo abierto dentro no se fuerza ni se apaga: solo el desmontaje",
      [o[1] for o in ORDENES], ["unmount"])
    c("  y se dice por qué, en cristiano",
      (r.ok, "Algo la está usando" in r.texto), (False, True))

    ORDENES.clear()
    SALIDA[0] = (1, "Object /dev/sdb1 is not mounted")
    r = expulsar.expulsar(PEN)
    c("otro error de udisks se cuenta tal cual", (r.ok, r.texto),
      (False, "Object /dev/sdb1 is not mounted"))

    ORDENES.clear()
    SALIDA[0] = (0, "")
    r = expulsar.expulsar(Path("/media/u/NOESTA"))
    c("una unidad que ya no está montada no lanza nada", (r.ok, ORDENES), (False, []))

    expulsar._expulsar_linux = lambda raiz: 1 / 0
    r = expulsar.expulsar(PEN)
    c("lo inesperado es un resultado que no es ok, no una excepción",
      (r.ok, "No he podido expulsarla" in r.texto), (False, True))

# --- Windows -------------------------------------------------------------
expulsar.IS_WIN = True
os.environ["SystemDrive"] = "C:"
c("la raíz de una unidad es su letra", expulsar._letra(Path("e:\\")), "E:")
c("  una carpeta de esa unidad, no", expulsar._letra(Path("E:\\prdrive")), None)
c("  una ruta de Linux, tampoco", expulsar._letra(Path("/media/u/PEN")), None)

bus_real = expulsar._bus_windows
BUS = {"E:": (False, expulsar.BUS_USB),      # un pendrive que se dice fijo
       "F:": (False, expulsar.BUS_SD),
       "G:": (True, 11),                     # lo declara extraíble, sea cual sea el bus
       "H:": (False, 11),                    # SATA interno
       "C:": (False, expulsar.BUS_USB),      # el del sistema, aunque fuera USB
       "V:": (False, 0)}                     # un volumen virtual (VeraCrypt)
expulsar._bus_windows = lambda letra: BUS.get(letra)
c("Windows: un pendrive USB (aunque se diga fijo) es compatible",
  expulsar.compatible(Path("E:\\")), True)
c("  una tarjeta SD, también", expulsar.compatible(Path("F:\\")), True)
c("  lo que se declara extraíble, también", expulsar.compatible(Path("G:\\")), True)
c("  un disco interno, no", expulsar.compatible(Path("H:\\")), False)
c("  la unidad del sistema, nunca", expulsar.compatible(Path("C:\\")), False)
c("  un volumen virtual, no", expulsar.compatible(Path("V:\\")), False)
c("  una letra que no contesta, no", expulsar.compatible(Path("Z:\\")), False)
c("  una carpeta, no", expulsar.compatible(Path("E:\\prdrive")), False)

# `_bus_windows` lee el `STORAGE_DEVICE_DESCRIPTOR`: RemovableMedia en el byte 10 y
# BusType en el 28.
expulsar._bus_windows = bus_real


class Kernel:
    """Un kernel32 que solo sabe cerrar manejadores."""

    cerrados = 0

    def CloseHandle(self, h):                       # noqa: N802
        Kernel.cerrados += 1


DESCRIPTOR = bytearray(64)
DESCRIPTOR[10] = 1
struct.pack_into("<I", DESCRIPTOR, 28, expulsar.BUS_USB)
RESPUESTA = [bytes(DESCRIPTOR)]
expulsar._kernel32 = lambda: Kernel()
expulsar._abrir_volumen = lambda k, letra, acceso: 7
expulsar._ioctl = lambda k, h, codigo, entrada=b"", salida=0: RESPUESTA[0]
c("`_bus_windows` lee del descriptor si es extraíble y de qué bus",
  expulsar._bus_windows("E:"), (True, expulsar.BUS_USB))
c("  y cierra el manejador", Kernel.cerrados, 1)
RESPUESTA[0] = b"corto"
c("  una respuesta incompleta es «no sé»", expulsar._bus_windows("E:"), None)
RESPUESTA[0] = None
c("  y el sistema que no contesta, también", expulsar._bus_windows("E:"), None)
expulsar._abrir_volumen = lambda k, letra, acceso: None
c("  y una letra que no se abre", expulsar._bus_windows("E:"), None)

LLAMADAS: list[int] = []
RECHAZADAS: set[int] = set()
PEDIDO = []
expulsar._abrir_volumen = lambda k, letra, acceso: 7


def ioctl(k, h, codigo, entrada=b"", salida=0):
    """Apunta la llamada y la rechaza si el test lo dice."""
    LLAMADAS.append(codigo)
    if entrada:
        PEDIDO.append(entrada)
    return None if codigo in RECHAZADAS else b""


expulsar._ioctl = ioctl
time.sleep = lambda s: None
Kernel.cerrados = 0
r = expulsar.expulsar(Path("E:\\"))
c("expulsar bloquea, desmonta, deja sacar el medio y lo expulsa, en ese orden",
  LLAMADAS, [expulsar.FSCTL_LOCK_VOLUME, expulsar.FSCTL_DISMOUNT_VOLUME,
             expulsar.IOCTL_STORAGE_MEDIA_REMOVAL, expulsar.IOCTL_STORAGE_EJECT_MEDIA])
c("  sin impedir sacarlo (PreventMediaRemoval = 0)", PEDIDO, [b"\0"])
c("  va bien y suelta el manejador", (r.ok, Kernel.cerrados), (True, 1))

LLAMADAS.clear()
RECHAZADAS.add(expulsar.FSCTL_LOCK_VOLUME)
r = expulsar.expulsar(Path("E:\\"))
c("si no consigue bloquear (algo la usa), reintenta y NO desmonta ni fuerza",
  (LLAMADAS, r.ok, "Algo está usando la unidad E:" in r.texto),
  ([expulsar.FSCTL_LOCK_VOLUME] * expulsar.INTENTOS_BLOQUEO, False, True))

LLAMADAS.clear()
RECHAZADAS.clear()
RECHAZADAS.add(expulsar.FSCTL_DISMOUNT_VOLUME)
r = expulsar.expulsar(Path("E:\\"))
c("si no puede desmontar, no sigue", (LLAMADAS[-1], r.ok),
  (expulsar.FSCTL_DISMOUNT_VOLUME, False))

LLAMADAS.clear()
RECHAZADAS.clear()
RECHAZADAS.add(expulsar.IOCTL_STORAGE_EJECT_MEDIA)
r = expulsar.expulsar(Path("E:\\"))
c("si lo único que falla es expulsar el medio, ya está desmontada y se puede quitar",
  r.ok, True)

expulsar._abrir_volumen = lambda k, letra, acceso: None
r = expulsar.expulsar(Path("E:\\"))
c("si no puede abrir el volumen, lo dice", (r.ok, "no deja abrir la unidad E:" in r.texto),
  (False, True))
r = expulsar.expulsar(Path("E:\\carpeta"))
c("una carpeta no es la raíz de una unidad", (r.ok, "no es la raíz" in r.texto), (False, True))

raise SystemExit(c.report())
