#!/usr/bin/env python3
r"""VeraCrypt y BitLocker para cifrar el dispositivo, sin Tkinter.

Dos formas de cifrar, con repartos de trabajo muy distintos:
- **VeraCrypt**: este módulo crea y monta un contenedor `PRDRIVE.hc` en la raíz
  del volumen físico, y la estructura del dispositivo vive DENTRO. Es lo que
  hace portable el cifrado: no depende de la edición de Windows ni de nada
  instalado en el equipo. Tampoco de VeraCrypt: en Windows, si no está
  instalado, se usa el VeraCrypt Portable oficial, bajado y comprobado por
  `install/veracrypt_bin.py`; en Linux, el instalado o el AppImage oficial.
- **BitLocker**: cifra el volumen entero y aquí solo se guía y se comprueba;
  cifrar de verdad lo hace el diálogo de Windows. Comprobarlo no pasa por
  `manage-bde` ni por `Get-BitLockerVolume` (los dos exigen elevar) sino por la
  propiedad del shell que usa el Explorador, que se lee sin permisos y sin
  lanzar nada (ver la sección de BitLocker). «No he podido comprobarlo» sigue
  siendo una respuesta de primera clase y no se disfraza de «está todo bien».

Tres reglas que no se pueden relajar:
- **Regla 1. La passphrase nunca se enseña ni se registra.** En Windows la CLI
  de VeraCrypt solo admite la contraseña como argumento, así que ya es visible
  en la lista de procesos mientras dura la orden (no se puede evitar), pero
  nada de lo que sale de aquí para pintar o para un log la lleva: para eso está
  `redact()`. En Linux se usa `--stdin`, que evita el problema del todo.
- **Regla 2. El montaje no se da por bueno por el código de retorno.**
  VeraCrypt eleva a un ayudante por UAC y lo que devuelve el proceso lanzado no
  dice si el volumen quedó montado. Se comprueba mirando si el punto de montaje
  se puede leer.
- **Regla 3. `/dynamic` se pregunta antes, nunca se prueba a ver.** VeraCrypt
  aborta con ERR_DYNAMIC_NOT_SUPPORTED si el anfitrión no admite ficheros
  dispersos, y esa comprobación es nuestra: `soporta_dispersos()`.

No hay favorito de VeraCrypt para montar al conectar. Hubo uno
(`write_favorite()`) y no funcionaba ni tenía arreglo que mereciera la pena
(VeraCrypt, tag 1.26.24, igual en `master`):
- Guardaba el contenedor como `\\?\Volume{GUID}\PRDRIVE.hc` para no depender de
  la letra. El temporizador de `Mount/Mount.c` resuelve esa forma con
  `VolumeGuidPathToDevicePath()` (`Common/Dlgcode.c`), que solo acepta rutas
  que TERMINAN en `}\` (un volumen entero): con un fichero detrás devuelve
  vacío y el favorito se salta con `continue`.
- `StartOnLogon=1` en `Configuration.xml` no registraba nada: el arranque con
  Windows lo escribe `ManageStartupSeq()` en el registro y solo se llama desde
  los diálogos de Preferencias y de Favoritos.
- `Favorite Volumes.xml` se escribía desde cero y borraba los favoritos de la
  persona.

Hacerlo bien exigiría guardar el contenedor por LETRA, escribir en el registro
de otra aplicación y depender de que la letra esté libre. Lo sustituye el
vestíbulo: `penwatch` abre el contenedor al conectar en cualquier equipo que lo
tenga, y fuera de eso está «Abrir PRDRIVE».
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from common import model, store

from . import CREATE_NO_WINDOW, DEVICE_LABEL, IS_WIN, InstallError, bundle_dir
from . import veracrypt_bin

MOUNT_TIMEOUT = 90.0
"""Segundos que se espera a ver el volumen montado.

VeraCrypt puede pedir UAC y tardar lo suyo.
"""
MOUNT_POLL = 0.5
"""Segundos entre cada comprobación de si el volumen ya está montado."""
PASSWORD_MARK = "***"
"""Lo que sustituye a la contraseña en cualquier texto que salga de aquí."""

FILE_SUPPORTS_SPARSE_FILES = 0x00000040     # winnt.h
SONDA_BYTES = 8 * 1024 ** 2
"""Bytes que se escriben para medir la velocidad de la unidad."""
SONDA_NOMBRE = ".prdrive-sonda.tmp"
"""Fichero temporal de esa medida, que se borra al acabar."""

WIN_CANDIDATES = {
    "mount": ["VeraCrypt.exe", r"C:\Program Files\VeraCrypt\VeraCrypt.exe",
              r"C:\Program Files (x86)\VeraCrypt\VeraCrypt.exe"],
    "format": ["VeraCrypt Format.exe",
               r"C:\Program Files\VeraCrypt\VeraCrypt Format.exe",
               r"C:\Program Files (x86)\VeraCrypt\VeraCrypt Format.exe"],
}
"""Dónde buscar los ejecutables de VeraCrypt en Windows.

Primero el `PATH` y luego las carpetas de instalación habituales.
"""
POSIX_CANDIDATES = [
    "veracrypt", "/usr/bin/veracrypt", "/usr/local/bin/veracrypt",
    "/Applications/VeraCrypt.app/Contents/MacOS/VeraCrypt",
]
"""Dónde buscar `veracrypt` en Linux y macOS."""

FILESYSTEMS = ("exFAT", "NTFS", "FAT") if IS_WIN else ("exFAT", "NTFS", "ext4")
"""Sistemas de ficheros que se ofrecen para el volumen de dentro."""

CONTRASENA_MAX = 128
"""Longitud máxima de la contraseña, en bytes UTF-8.

Es `MAX_PASSWORD` de `Common/Password.h` (tag VeraCrypt_1.26.24). VeraCrypt
mide BYTES y no letras (la CLI convierte con `WideCharToMultiByte(CP_UTF8,
…)`): una letra con tilde cuenta dos.
"""
CONTRASENA_AVISO = 20
"""Longitud, en bytes UTF-8, por debajo de la cual VeraCrypt avisa.

Es `PASSWORD_LEN_WARNING`: pregunta si de verdad se quiere una contraseña tan
corta.
"""


def _first_exe(candidatos: list[str]) -> str | None:
    """Devuelve el primer candidato que existe, o `None`.

    Un nombre con separador se busca como ruta; uno sin él, en el `PATH`.
    """
    for c in candidatos:
        if os.sep in c or (os.altsep and os.altsep in c):
            if Path(c).is_file():
                return c
        else:
            found = shutil.which(c)
            if found:
                return found
    return None


def arquitectura_vc() -> str:
    """Devuelve `arm64` en un Windows ARM64 y `x64` en los demás.

    Es qué ejecutables del VeraCrypt Portable usa ESTE equipo. VeraCrypt elige
    su driver por la máquina NATIVA (`IsARM()` en `Common/Dlgcode.c` pregunta a
    `IsWow64Process2`) y aquí se pregunta lo mismo por el mismo camino que todo
    lo demás del proyecto (`model.machine_arch()`, que cuelga de
    `model.maquina_nativa_windows()`): el instalador es un .exe x64 y en un
    Windows ARM oiría «AMD64» de cualquier otro sitio. El x64 emulado también
    cargaría el driver arm64 que viaja a su lado, pero no hay por qué emular lo
    que existe nativo.
    """
    return "arm64" if model.machine_arch() in ("arm64", "aarch64") else "x64"


def _en_carpeta(carpeta: Path) -> dict | None:
    """Devuelve los ejecutables de montar y de formatear de esa carpeta, o `None`.

    Valen los nombres del portable oficial (`VeraCrypt-<arq>.exe` y `VeraCrypt
    Format-<arq>.exe`, los de este equipo: el portable no trae ningún
    `VeraCrypt.exe`, #38) o los de una instalación. Los dos de la misma
    disposición: mezclar el de montar de una con el de formatear de otra es
    mezclar versiones.
    """
    arq = arquitectura_vc()
    for montar, formatear in ((veracrypt_bin.montar(arq), veracrypt_bin.formatear(arq)),
                              ("VeraCrypt.exe", "VeraCrypt Format.exe")):
        try:
            if (carpeta / montar).is_file() and (carpeta / formatear).is_file():
                return {"mount": str(carpeta / montar),
                        "format": str(carpeta / formatear)}
        except OSError:
            continue
    return None


def portatil(vc: dict | None) -> bool:
    """Indica si ese VeraCrypt es el Portable (los nombres llevan la arquitectura).

    Lo que cambia para quien lo usa es el UAC: sin su driver instalado, cada
    operación se relanza elevada (`InitApp`, `LaunchElevatedProcess` en
    `Common/Dlgcode.c`), y la pantalla lo avisa.
    """
    nombre = Path((vc or {}).get("mount") or "").name.lower()
    return nombre in {veracrypt_bin.montar(a).lower()
                      for a in veracrypt_bin.ARQUITECTURAS}


def find_veracrypt(extra_dir: str | Path | None = None) -> dict | None:
    """Devuelve los ejecutables de VeraCrypt, o `None`.

    En Windows son dos binarios distintos (montar y formatear); en Linux y
    macOS los dos papeles los hace el mismo `veracrypt --text`. Bajarlo no se
    hace aquí: es una descarga y la pide la pantalla con su botón.

    Orden en Windows: la carpeta del usuario, el VeraCrypt INSTALADO (con otro
    instalado y su driver cargado, el portable falla con ERR_DRIVER_VERSION:
    `Common/Dlgcode.c`, `DriverAttach`) y, si no hay ninguno, el Portable
    oficial que ya esté en la caché del instalador y siga siendo el comprobado
    (`veracrypt_bin.cached()`). En Linux: esa carpeta, el instalado y el
    AppImage oficial fijado que ya esté en la caché
    (`veracrypt_bin.appimage_en_cache()`).

    Args:
        extra_dir: Carpeta que indique el usuario cuando no está donde se
            espera: una instalación o un Portable descomprimido, las dos valen.
    """
    if IS_WIN:
        if extra_dir:
            hallado = _en_carpeta(Path(extra_dir))
            if hallado is not None:
                return hallado
        mount = _first_exe(WIN_CANDIDATES["mount"])
        fmt = _first_exe(WIN_CANDIDATES["format"])
        if mount and fmt:
            return {"mount": mount, "format": fmt}
        cache = veracrypt_bin.cached()
        return _en_carpeta(cache) if cache is not None else None

    candidatos = list(POSIX_CANDIDATES)
    if extra_dir:
        candidatos.insert(0, str(Path(extra_dir) / "veracrypt"))
        candidatos.insert(0, str(extra_dir))
    vc = _first_exe(candidatos)
    if vc:
        return {"mount": vc, "format": vc}
    # Sin instalado, el AppImage oficial de la caché si sigue siendo el
    # comprobado; bajarlo lo pide la pantalla, como el Portable en Windows.
    cache = veracrypt_bin.en_cache_para_este_equipo()
    if cache is None:
        return None
    exe = str(cache / veracrypt_bin.APPIMAGE_EXE)
    return {"mount": exe, "format": exe, "appimage": True}


def appimage(vc: dict | None) -> bool:
    """Indica si ese VeraCrypt es el AppImage oficial fijado (Linux, sin instalar)."""
    return bool((vc or {}).get("appimage"))


UNIDADES = {"k": 1024, "m": 1024 ** 2, "g": 1024 ** 3, "t": 1024 ** 4}
"""Multiplicador de cada sufijo de tamaño (`20G`, `500M`)."""
MARGEN = 50 * 1024 ** 2
"""Bytes que se dejan libres al pedir `max`."""

RESERVA_VIAJERO = 256 * 1024 ** 2
"""Bytes que se dejan libres al pedir `max` con VeraCrypt de viaje.

Se aplica si la unidad va a llevar VeraCrypt en su raíz física
(`install/traveler.py`). Son ~29 MB, pero ponerlo al día copia el nuevo AL LADO
del viejo antes de cambiarlos, así que en ese momento hace falta el doble, más
el vestíbulo y el `autorun.inf`, y algo para versiones que pesen más. Con
`MARGEN`, un contenedor `max` dejaba la unidad sin sitio para su primera
actualización (y uno dinámico, al crecer, se lo comía).
"""


def size_to_bytes(raw: str, free: int, tope: int | None = None,
                  viajero: bool = False) -> int:
    """Convierte `20G`, `500M` o `max` en bytes.

    Args:
        raw: El tamaño escrito.
        free: Bytes libres en la unidad.
        tope: Lo más que admite el sistema de ficheros (`tope_contenedor()`).
            Solo recorta `max`, que es «todo lo que quepa»: un tamaño escrito a
            mano por encima no se rebaja en silencio, lo rechaza
            `create_container()` diciendo por qué.
        viajero: La unidad va a llevar VeraCrypt fuera del contenedor, y `max`
            deja `RESERVA_VIAJERO` en vez de `MARGEN`.

    Raises:
        InstallError: Si el tamaño no se entiende.
    """
    texto = str(raw).strip().lower()
    if texto in {"max", ""}:
        maximo = max(0, free - (RESERVA_VIAJERO if viajero else MARGEN))
        return min(maximo, tope) if tope is not None else maximo
    try:
        if texto[-1] in UNIDADES:
            return int(float(texto[:-1].replace(",", ".")) * UNIDADES[texto[-1]])
        return int(float(texto.replace(",", ".")))
    except (ValueError, IndexError) as e:
        raise InstallError(
            f"No entiendo el tamaño '{raw}'. Usa 20G, 500M o 'max'.") from e


SISTEMAS_FAT = {"fat", "fat12", "fat16", "fat32", "vfat", "msdos"}
"""Nombres de sistema de ficheros que no admiten ficheros de 4 GiB o más."""
TOPE_FAT = 4095 * 1024 ** 2
"""Lo más grande que puede ser un contenedor en FAT: 4095 MiB.

Un contenedor es UN fichero y FAT32 no admite 4 GiB o más; la mayoría de
pendrives de 32 GB o menos vienen así de fábrica. No son 4 GiB − 1 porque
VeraCrypt redondea `/size` HACIA ARRIBA al tamaño de sector
(`Format/Tcformat.c`, tag VeraCrypt_1.26.24: «correct volume size to be
multiple of sector size»); 4095 MiB es múltiplo de cualquier sector.
"""


def sistema_de_ficheros(root: str | Path) -> str:
    """Devuelve el sistema de ficheros de la unidad de `root`, o `""` si no se sabe.

    `root` puede ser una carpeta: se pregunta a su volumen. Es función de
    módulo para que los tests la sustituyan, como `soporta_dispersos()`.
    """
    from . import device
    try:
        return device.volume_for(device.raiz_del_volumen(root)).filesystem or ""
    except (OSError, TypeError, AttributeError):
        return ""


def tope_contenedor(filesystem: str) -> int | None:
    """Devuelve lo más grande que puede ser un contenedor en ese sistema de ficheros.

    `None` es «sin tope que importe». Se compara el nombre entero y en
    minúsculas: `exfat` contiene «fat» y no tiene nada que ver.
    """
    return TOPE_FAT if (filesystem or "").strip().lower() in SISTEMAS_FAT else None


TOPE_SIN_DISPERSOS = 64 * 1024 ** 3
"""Bytes a partir de los cuales no se propone más tamaño sin ficheros dispersos.

Sin dispersos, cada giga propuesto es un giga que hay que ESCRIBIR en la unidad
antes de poder seguir instalando: proponer casi el disco entero convertía uno
de 1 TB en una espera de horas, para un contenedor que casi nadie va a llenar.
Con dispersos no cuesta nada y el tamaño deja de ser una decisión.
"""


def suggested_size(free: int, dinamico: bool = False, tope: int | None = None) -> str:
    """Devuelve el tamaño que se propone por defecto.

    Con contenedor dinámico, `max`: solo ocupa lo que se guarde dentro. Sin él,
    el hueco menos un giga de respiro pero con `TOPE_SIN_DISPERSOS`, porque ese
    número es minutos de escritura (ver `soporta_dispersos()`). Y nunca más de
    lo que admite la unidad.

    Args:
        free: Bytes libres en la unidad.
        dinamico: Si el contenedor se crea disperso.
        tope: Lo más que admite el sistema de ficheros (`tope_contenedor()`).
    """
    if dinamico:
        return "max"
    limite = min(max(0, free - 1024 ** 3), TOPE_SIN_DISPERSOS)
    if tope is not None and limite > tope:
        return f"{tope // 1024 ** 2}M"
    return f"{max(1, int(limite / 1024 ** 3))}G"


def free_drive_letter(preferida: str = "P") -> str:
    """Devuelve una letra de unidad libre, la preferida si puede ser.

    Se le pregunta al kernel (`GetLogicalDrives`): es instantáneo, no abre
    ninguna ventana y no hace falta PowerShell. Fuera de Windows devuelve `""`.

    Raises:
        InstallError: Si no queda ninguna letra libre.
    """
    if not IS_WIN:
        return ""
    import ctypes
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    usadas = {chr(65 + i) for i in range(26) if mask & (1 << i)}
    for letra in [preferida.upper(), *"PQRSTUVWXYZNMLKJIHGFED"]:
        if letra and letra not in usadas:
            return letra
    raise InstallError("No queda ninguna letra de unidad libre.")


def soporta_dispersos(root: str | Path) -> bool:
    """Indica si el sistema de ficheros de `root` admite ficheros dispersos.

    Es LA pregunta de la que depende que crear el contenedor tarde segundos o
    media hora, y hay que contestarla ANTES. Con `/quick` sobre un
    contenedor-fichero, `FormatNoFs()` (src/Common/Format.c, tag
    VeraCrypt_1.26.24) escribe un sector a cero cada 128 MiB *a propósito*
    («forcing Windows to allocate the disk space of each 128 MiB chunk
    immediately»). Cada escritura cae más allá del valid data length y NTFS
    rellena de ceros todo el hueco anterior: se acaba escribiendo el contenedor
    entero, que en un USB a 30 MB/s son media hora por cada 50 GiB. `/dynamic`
    marca el fichero como disperso con FSCTL_SET_SPARSE (Format.c:407, que
    además exige quickFormat, ya se pasa) y esa caminata solo asigna un clúster
    por tramo. Se paga en negación plausible (se ve cuánto ocupa de verdad) y
    en errores de E/S dentro del volumen si la unidad se llena.

    Al recibir `/dynamic`, VeraCrypt hace esta misma consulta y **aborta** con
    ERR_DYNAMIC_NOT_SUPPORTED si sale que no (Tcformat.c:6338). Por eso se
    pregunta por la bandera y no por el nombre del sistema de ficheros: es la
    misma prueba que hace él y no hay que mantener aquí una lista de los que la
    cumplen.

    En POSIX no hay bandera que leer: se prueba (`_dispersos_posix()`). Ahí no
    decide `/dynamic`, que no existe en su CLI, sino si el `--quick` de la
    1.26.29 dejará el contenedor disperso (`creacion_dispersa()`).

    `root` puede ser una carpeta (la del contenedor de la raíz de un equipo):
    `GetVolumeInformationW` solo acepta la raíz de un volumen, así que se le
    pregunta a la suya (`device.raiz_del_volumen()`).

    Es función de módulo para que los tests la sustituyan, como
    `_leer_estado_bitlocker()`.
    """
    if not IS_WIN:
        return _dispersos_posix(root)
    import ctypes
    from ctypes import byref, c_wchar_p, create_unicode_buffer
    from ctypes.wintypes import DWORD

    from . import device

    ruta = str(device.raiz_del_volumen(root))
    if not ruta.endswith(("\\", "/")):
        ruta += "\\"
    flags = DWORD(0)
    try:
        nombre = create_unicode_buffer(261)         # MAX_PATH + 1
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            c_wchar_p(ruta), None, 0, None, None, byref(flags), nombre, 261)
    except OSError:
        return False
    return bool(ok) and bool(flags.value & FILE_SUPPORTS_SPARSE_FILES)


DISPERSO_NOMBRE = ".prdrive-disperso.tmp"
"""Fichero temporal de la prueba de ficheros dispersos en POSIX."""


def _dispersos_posix(root: str | Path) -> bool:
    """Indica si este sistema de ficheros deja un fichero con un hueco sin ocupar.

    La prueba es la evidencia misma: 1 MiB de tamaño con un solo byte al final,
    y se mira cuánto ocupa de verdad (`st_blocks`, en bloques de 512 bytes).
    ext4, btrfs o xfs lo dejan en un bloque; FAT y exFAT, que no saben de
    dispersos, lo rellenan entero. Se escribe en la propia carpeta y se borra.
    Cualquier fallo es «no»: prometer que ocupa poco y que ocupe entero es peor
    que lo contrario.
    """
    prueba = Path(root) / DISPERSO_NOMBRE
    try:
        with open(prueba, "wb") as f:
            f.seek(1024 ** 2 - 1)
            f.write(b"\0")
            f.flush()
            os.fsync(f.fileno())
        return os.stat(prueba).st_blocks * 512 < 1024 ** 2 // 2
    except (OSError, AttributeError):
        return False
    finally:
        try:
            prueba.unlink()
        except OSError:
            pass


def creacion_dispersa(root: str | Path, vc: dict | None) -> bool | None:
    """Indica si el contenedor que se cree en `root` con `vc` saldrá disperso.

    `True` o `False` cuando se sabe, `None` cuando depende de algo que no se
    puede preguntar sin ejecutarlo. En Windows es `/dynamic`, que se pasa solo
    si el disco lo admite (`soporta_dispersos()`). En Linux, `--quick` se pasa
    siempre (`create_command`) y deja el contenedor disperso desde la 1.26.29;
    antes se ignora. Con el AppImage fijado la versión se sabe; con un
    VeraCrypt instalado no, y la pantalla lo dice así en vez de prometer nada.
    """
    if not soporta_dispersos(root):
        return False
    if IS_WIN or appimage(vc):
        return True
    return None


def medir_escritura(root: str | Path, muestra: int = SONDA_BYTES) -> float | None:
    """Devuelve los bytes por segundo que admite esa unidad, medidos, o `None`.

    Sirve para poder decir «≈ 14 min» en vez de «esto puede tardar bastante»,
    que es lo único honesto cuando no hay dispersos y hay que escribir el
    contenedor entero. El `fsync` no es opcional: sin él se mediría la caché
    del sistema, que en un USB miente por un orden de magnitud. La sonda se
    borra siempre, también si falla a medias. Es función de módulo: los tests
    la sustituyen y así ninguno escribe nada.

    Args:
        root: Carpeta de la unidad donde se escribe la sonda.
        muestra: Bytes que se escriben.
    """
    sonda = Path(root) / SONDA_NOMBRE
    bloque = b"\0" * (1024 ** 2)
    vueltas = max(1, muestra // len(bloque))
    try:
        inicio = time.monotonic()
        with open(sonda, "wb") as f:
            for _ in range(vueltas):
                f.write(bloque)
            f.flush()
            os.fsync(f.fileno())
        transcurrido = time.monotonic() - inicio
    except OSError:
        return None
    finally:
        try:
            sonda.unlink()
        except OSError:
            pass
    if transcurrido <= 0:
        return None
    return (vueltas * len(bloque)) / transcurrido


def estimar_creacion(root: str | Path, size_bytes: int) -> float | None:
    """Devuelve los segundos que costará escribir un contenedor así, o `None`.

    Solo describe el caso lento, el que hay que escribir entero: con contenedor
    dinámico no se escribe el volumen y esto no se pregunta (quien llama lo
    sabe por `soporta_dispersos()`).
    """
    velocidad = medir_escritura(root)
    if not velocidad:
        return None
    return size_bytes / velocidad


AVISO_RAFAGA = ("en memorias USB suele tardar bastante más, porque la velocidad "
                "baja cuando se llena su caché. Mientras se crea verás el avance "
                "real, si la unidad deja medirlo")
"""Lo que la sonda NO puede saber, dicho siempre al lado de su número.

Mide la ráfaga: muchas memorias USB escriben rápido los primeros gigas en una
caché (SLC) y, llena, bajan a su velocidad real, a menudo la mitad o la cuarta
parte. Una sonda más grande no lo arregla, porque esa caché puede ser de varios
gigas. Caso real (#46): más de 100 GB en exFAT, la sonda midió unos 75 MB/s, se
dijo «unos 23 min» y a los 40 seguía escribiendo. Por eso el número es un
mínimo, y el de verdad lo da el avance medido mientras se crea (`Seguimiento`).
"""


def _duracion(segundos: float) -> str:
    """Devuelve la espera en palabras: «unos 23 min» o «unas 1,5 h».

    Las horas empiezan en hora y media, que es la primera cifra que no se lee
    mejor en minutos («unas 1,0 h» no la diría nadie), y con coma decimal.
    """
    if segundos < 90 * 60:
        return f"unos {max(2, round(segundos / 60))} min"
    horas = f"{segundos / 3600:.1f}".replace(".", ",").removesuffix(",0")
    return f"unas {horas} h"


def describir_espera(segundos: float | None) -> str:
    """Devuelve la estimación en algo que se pueda leer de un vistazo.

    Es un MÍNIMO y lo dice: sale de la velocidad de ráfaga (`AVISO_RAFAGA`).
    Quien llama pone delante lo que se va a escribir y detrás el punto.
    """
    if segundos is None:
        return "no he podido medir la velocidad de la unidad"
    if segundos < 90:
        return f"en principio menos de dos minutos; {AVISO_RAFAGA}"
    return f"al menos {_duracion(segundos)}; {AVISO_RAFAGA}"


MUESTREO_S = 1.0  # segundos entre lecturas del contador
VENTANA_S = 60.0  # la velocidad que vale es la de este último rato
VENTANA_MIN_S = 30.0  # con menos rato escribiendo, no se da tiempo restante
PARADO_S = 30.0  # sin moverse este rato, el contador ya no dice nada
TOPE_AVANCE = 0.99  # hasta que create_container() vuelva, nunca el 100 %

SECTOR_SYSFS = 512
"""Bytes por sector de `/sys/dev/block/…/stat`: siempre 512."""
SYS_DEV_BLOCK = Path("/sys/dev/block")
"""Carpeta de sysfs con un enlace a cada dispositivo de bloques, por `mayor:menor`."""

# winioctl.h: `IOCTL_DISK_PERFORMANCE` es CTL_CODE(IOCTL_DISK_BASE, 0x0008,
# METHOD_BUFFERED, FILE_ANY_ACCESS), con IOCTL_DISK_BASE = FILE_DEVICE_DISK = 7
# y CTL_CODE(t, f, m, a) = (t << 16) | (a << 14) | (f << 2) | m.
FILE_DEVICE_DISK = 0x00000007
METHOD_BUFFERED = 0
FILE_ANY_ACCESS = 0


def _ctl_code(tipo: int, funcion: int, metodo: int, acceso: int) -> int:
    """Compone un código de control de E/S como la macro `CTL_CODE` de winioctl.h."""
    return (tipo << 16) | (acceso << 14) | (funcion << 2) | metodo


IOCTL_DISK_PERFORMANCE = _ctl_code(FILE_DEVICE_DISK, 0x0008, METHOD_BUFFERED,
                                   FILE_ANY_ACCESS)            # 0x00070020
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3


def _disk_performance():
    """Devuelve la clase `DISK_PERFORMANCE` de winioctl.h, campo a campo.

        LARGE_INTEGER BytesRead, BytesWritten, ReadTime, WriteTime, IdleTime;
        DWORD         ReadCount, WriteCount, QueueDepth, SplitCount;
        LARGE_INTEGER QueryTime;
        DWORD         StorageDeviceNumber;
        WCHAR         StorageManagerName[8];

    88 bytes en total. Con tipos de tamaño fijo y no los de `wintypes`, para
    que la disposición se pueda comprobar en cualquier sistema (un `c_wchar`
    son cuatro bytes en Linux; un WCHAR, dos). Se construye al llamarla, como
    el resto de ctypes de este módulo.
    """
    import ctypes

    class DISK_PERFORMANCE(ctypes.Structure):
        """Estructura `DISK_PERFORMANCE` de winioctl.h."""
        _fields_ = [("BytesRead", ctypes.c_int64),
                    ("BytesWritten", ctypes.c_int64),
                    ("ReadTime", ctypes.c_int64),
                    ("WriteTime", ctypes.c_int64),
                    ("IdleTime", ctypes.c_int64),
                    ("ReadCount", ctypes.c_uint32),
                    ("WriteCount", ctypes.c_uint32),
                    ("QueueDepth", ctypes.c_uint32),
                    ("SplitCount", ctypes.c_uint32),
                    ("QueryTime", ctypes.c_int64),
                    ("StorageDeviceNumber", ctypes.c_uint32),
                    ("StorageManagerName", ctypes.c_uint16 * 8)]

    return DISK_PERFORMANCE


def _escritos_windows(root: str | Path) -> int | None:
    r"""Devuelve `BytesWritten` de `DISK_PERFORMANCE` del volumen de `root`, o `None`.

    El volumen es `\\.\G:`. Se abre con acceso 0 y compartido para leer y
    escribir: la documentación de `CreateFileW` dice que con acceso 0 se pueden
    consultar los atributos de un dispositivo sin acceder a él ni al medio, y
    `IOCTL_DISK_PERFORMANCE` es FILE_ANY_ACCESS, así que el administrador de
    E/S no le pide nada más al handle. Que el driver tampoco pida administrador
    es la prueba P1.

    Un handle por lectura, cerrado enseguida: uno abierto toda la creación
    sería una cosa más agarrada al volumen del que cuelga el contenedor. Y la
    primera llamada puede ser la que ENCIENDE los contadores (la documentación
    de esa IOCTL dice «enables performance counters»): por eso solo vale la
    diferencia con la inicial, que se lee antes de lanzar VeraCrypt.

    La alternativa para P1 si el volumen no contesta es el disco
    (`\\.\PhysicalDriveN`, vía IOCTL_STORAGE_GET_DEVICE_NUMBER). No está aquí a
    propósito: mezclar las dos cuentas en una misma creación daría un salto que
    se leería como avance.
    """
    unidad = str(root)[:2]
    if len(unidad) != 2 or unidad[1] != ":" or not unidad[0].isalpha():
        return None                 # una ruta UNC o sin letra: no hay volumen que abrir

    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                wintypes.HANDLE]
    k32.DeviceIoControl.restype = wintypes.BOOL
    k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID,
                                    wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                    ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = k32.CreateFileW(f"\\\\.\\{unidad.upper()}", 0,
                             FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                             OPEN_EXISTING, 0, None)
    if not handle or handle == wintypes.HANDLE(-1).value:
        return None
    try:
        estructura = _disk_performance()
        datos = estructura()
        devueltos = wintypes.DWORD(0)
        ok = k32.DeviceIoControl(handle, IOCTL_DISK_PERFORMANCE, None, 0,
                                 ctypes.byref(datos), ctypes.sizeof(datos),
                                 ctypes.byref(devueltos), None)
        hasta = estructura.BytesWritten.offset + estructura.BytesWritten.size
        if not ok or devueltos.value < hasta:
            return None
        return int(datos.BytesWritten)
    finally:
        k32.CloseHandle(handle)


def _escritos_linux(root: str | Path) -> int | None:
    """Devuelve los bytes escritos en el dispositivo de bloques de `root`.

    `/sys/dev/block/<mayor>:<menor>` es el enlace al dispositivo del `st_dev`
    (Documentation/ABI/testing/sysfs-dev del kernel), y si es una partición su
    `stat` ya es solo de ella. El séptimo campo son los sectores escritos,
    siempre de 512 bytes sea cual sea el tamaño de sector del disco
    (Documentation/block/stat.rst: «standard UNIX 512-byte sectors»). Cuenta lo
    que llega al dispositivo, después de la caché de páginas: lo que de verdad
    se ha escrito.

    Raises:
        OSError: Si el sistema de ficheros no tiene dispositivo de bloques
            (tmpfs, o el número anónimo de btrfs), que no tiene ese fichero.
    """
    st = os.stat(root)
    ruta = SYS_DEV_BLOCK / f"{os.major(st.st_dev)}:{os.minor(st.st_dev)}" / "stat"
    campos = ruta.read_text(encoding="ascii").split()
    return int(campos[6]) * SECTOR_SYSFS


def bytes_escritos(root: str | Path) -> int | None:
    """Devuelve los bytes escritos hasta ahora en el dispositivo de `root`, o `None`.

    Es un contador del sistema, no de esta creación: lo que vale es la
    diferencia entre dos lecturas. Cualquier fallo es `None` y se captura
    `Exception`, como en `bitlocker_status()`: en Windows hay ctypes debajo y
    esto es un adorno que no puede tumbar la creación. Es función de módulo
    para que los tests la sustituyan, como `soporta_dispersos()`.
    """
    try:
        valor = _escritos_windows(root) if IS_WIN else _escritos_linux(root)
    except Exception:                             # noqa: BLE001 — ver docstring
        return None
    return valor if valor is None or valor >= 0 else None


def avance(muestras: list[tuple[float, int | None]],
           size_bytes: int) -> tuple[float, float | None] | None:
    """Devuelve `(fracción, segundos que quedan)` a partir de las lecturas, o `None`.

    Es pura: toda la aritmética, nada de disco. Devuelve `None` («no se sabe»)
    cuando:
    - falta la lectura inicial o falla la última;
    - el contador baja en algún momento: se reinició o cuenta otra cosa, y ya
      no hay manera de fiarse de él en toda la creación;
    - no se ha movido nunca: todavía no se escribe (el aviso de UAC de la copia
      elevada) o este contador no ve estas escrituras;
    - lleva más de `PARADO_S` sin moverse.

    La fracción es lo escrito entre el tamaño, con tope en `TOPE_AVANCE`: el
    contador ve también lo que escriba cualquier otro en esa unidad, y después
    del relleno aún quedan la cabecera de respaldo y el formato de dentro.

    El tiempo que queda sale de la velocidad de los últimos `VENTANA_S`, no de
    la de la sonda: cuando se llena la caché de la memoria USB y la velocidad
    cae, en un minuto el tiempo que queda sube con ella. La ventana empieza
    como pronto en la última lectura antes del primer movimiento, para que la
    espera del UAC no pase por lentitud; y con menos de `VENTANA_MIN_S` de
    escritura el tiempo que queda es `None`: hay fracción, pero todavía no hay
    velocidad.

    Args:
        muestras: Lecturas `(t, bytes)` en orden, con `t` en segundos de un
            reloj monótono y la primera leída ANTES de lanzar VeraCrypt;
            `bytes` es `None` cuando esa lectura falló.
        size_bytes: Tamaño del contenedor.
    """
    if not muestras or size_bytes <= 0:
        return None
    if muestras[0][1] is None or muestras[-1][1] is None:
        return None
    leidas = [(t, b) for t, b in muestras if b is not None]
    arranque = ultimo_movimiento = None
    for (ta, a), (tb, b) in zip(leidas, leidas[1:]):
        if b < a:
            return None
        if b > a:
            if arranque is None:
                arranque = ta
            ultimo_movimiento = tb
    t_fin, b_fin = leidas[-1]
    if ultimo_movimiento is None or t_fin - ultimo_movimiento > PARADO_S:
        return None

    escritos = b_fin - leidas[0][1]
    fraccion = min(TOPE_AVANCE, escritos / size_bytes)

    desde = max(t_fin - VENTANA_S, arranque)
    t_base, b_base = next((t, b) for t, b in leidas if t >= desde)
    tramo = t_fin - t_base
    if tramo < VENTANA_MIN_S:
        return fraccion, None
    velocidad = (b_fin - b_base) / tramo
    if velocidad <= 0:
        return fraccion, None
    return fraccion, max(0, size_bytes - escritos) / velocidad


def describir_restante(segundos: float) -> str:
    """Devuelve el tiempo que queda en palabras."""
    if segundos < 60:
        return "queda menos de un minuto"
    if segundos < 90:
        return "queda un minuto y pico"
    return f"quedan {_duracion(segundos)}"


def describir_avance(fraccion: float, restante: float | None) -> str:
    """Devuelve el avance en palabras: «43 % · quedan unos 25 min».

    La cifra se trunca: 99,9 % no es 100 %.
    """
    cifra = f"{int(fraccion * 100 + 1e-9)} %"
    if restante is None:
        return f"{cifra} · calculando cuánto queda"
    return f"{cifra} · {describir_restante(restante)}"


class Seguimiento:
    """El avance de una creación, leído del volumen en un hilo propio.

    VeraCrypt crea con `/silent` y no cuenta nada, pero lo que escribe acaba en
    el disco y el disco lleva la cuenta. Se apunta ese contador justo antes de
    lanzar la orden y se vuelve a leer cada segundo: lo que ha crecido, entre
    lo que mide el contenedor, es cuánto va. Es el único canal, igual que el
    log de rclone lo es para `progress.py`, y con las mismas reglas: puramente
    informativo y **mejor sin número que con uno falso**. Si el contador no se
    puede leer, baja o se queda quieto, no hay avance y la ventana vuelve a la
    barra sin cifra.

    Lo arranca `create_container()`, que es quien sabe cuándo se lanza
    VeraCrypt, y lo lee la ventana con `progreso()`, que no toca el disco: solo
    devuelve lo último que calculó el hilo. Leer el contador puede tardar (una
    IOCTL a una memoria USB ocupada escribiendo) y el hilo de Tk no puede
    esperar a nadie.

    Sin verificar en hardware (#46, pruebas P1–P7): que Windows conteste sin
    administrador, que su cuenta incluya el relleno de ceros del sistema de
    ficheros y lo que escribe la copia elevada de Format, y el camino de Linux
    sobre una memoria USB. Mientras no se pruebe protege la vuelta a la barra
    indeterminada: con un contador que no sirve, nada cambia respecto a no
    tenerlo.

    Args:
        cada: Segundos entre lecturas.
        reloj: Reloj monótono; los tests lo sustituyen.
    """

    def __init__(self, cada: float = MUESTREO_S, reloj=time.monotonic):
        """Prepara el seguimiento sin leer nada todavía."""
        self.cada = cada
        self.reloj = reloj
        self.muestras: list[tuple[float, int | None]] = []
        self._raiz: str | Path = ""
        self._tamano = 0
        self._ultimo: tuple[float, float | None] | None = None
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None

    def empezar(self, raiz: str | Path, size_bytes: int) -> None:
        """Apunta la lectura inicial y arranca el hilo.

        Se llama justo antes de lanzar VeraCrypt. Nada de aquí puede impedir la
        creación: si falla, no hay avance.

        Args:
            raiz: Carpeta de la unidad donde se crea el contenedor.
            size_bytes: Tamaño del contenedor.
        """
        self._raiz, self._tamano = raiz, size_bytes
        try:
            self._apuntar()
            self._hilo = threading.Thread(target=self._bucle, daemon=True,
                                          name="prdrive-avance")
            self._hilo.start()
        except Exception:                         # noqa: BLE001 — ver docstring
            self._ultimo = None

    def _apuntar(self) -> None:
        """Lee el contador y recalcula el avance."""
        self.muestras.append((self.reloj(), bytes_escritos(self._raiz)))
        self._ultimo = avance(self.muestras, self._tamano)

    def _bucle(self) -> None:
        """Lee el contador cada `cada` segundos hasta que se pare o falle.

        Es un adorno: cualquier excepción lo deja sin avance en vez de
        molestar.
        """
        while not self._parar.wait(self.cada):
            try:
                self._apuntar()
            except Exception:                     # noqa: BLE001 — un adorno
                self._ultimo = None
                return

    def parar(self) -> None:
        """Para el hilo."""
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join(timeout=2)      # solo espera si una lectura se colgó

    def leer(self) -> tuple[float, float | None] | None:
        """Devuelve `(fracción, segundos que quedan)`, o `None`.

        Si el hilo lleva más de `PARADO_S` sin apuntar nada (colgado en una
        lectura), lo último que calculó ya no vale.
        """
        if not self.muestras or self.reloj() - self.muestras[-1][0] > PARADO_S:
            return None
        return self._ultimo

    def progreso(self) -> tuple[float, str] | None:
        """Devuelve `(fracción, texto)` para `ui.tk.working()`, o `None`."""
        medida = self.leer()
        return None if medida is None else (medida[0], describir_avance(*medida))


def redact(cmd: list[str], password: str) -> list[str]:
    """Devuelve la misma orden con la contraseña tapada.

    Es para enseñarla o registrarla. Se compara por valor y no por posición
    porque la contraseña aparece pegada al flag en unas formas (`--password=X`)
    y suelta en otras (`/password X`).
    """
    limpio = []
    for arg in cmd:
        if password and arg == password:
            limpio.append(PASSWORD_MARK)
        elif password and password in arg:
            limpio.append(arg.replace(password, PASSWORD_MARK))
        else:
            limpio.append(arg)
    return limpio


def create_command(vc: dict, container: Path, size_bytes: int, password: str,
                   filesystem: str, dinamico: bool = False) -> list[str]:
    """Devuelve la orden de crear el contenedor.

    `/quick` (Windows) evita rellenar el fichero entero de datos ALEATORIOS,
    que en un contenedor de varios gigas sobre USB son horas. A cambio, el
    espacio libre de dentro no queda indistinguible del contenido: no es un
    problema para un dispositivo de trabajo, pero conviene saberlo. No evita
    que se escriba el contenedor entero de CEROS: eso es `dinamico` (ver
    `soporta_dispersos()`).

    Args:
        vc: Los ejecutables de VeraCrypt.
        container: Dónde se crea el `.hc`.
        size_bytes: Tamaño del contenedor.
        password: La contraseña.
        filesystem: Sistema de ficheros de dentro.
        dinamico: Añade `/dynamic`; quien llama tiene que haber preguntado
            antes por `soporta_dispersos()`, porque sobre exFAT VeraCrypt
            aborta.
    """
    if IS_WIN:
        extra = ["/dynamic"] if dinamico else []
        return [vc["format"], "/create", str(container),
                "/size", str(size_bytes), "/password", password,
                "/encryption", "AES", "/hash", "sha512",
                "/filesystem", filesystem, "/pim", "0",
                *extra, "/quick", "/silent", "/force"]
    # --stdin: en Linux la contraseña va por la entrada estándar y no aparece
    # en la lista de procesos.
    #
    # Aquí NO hay /dynamic (no existe en su CLI), pero desde la 1.26.29
    # `--quick` hace lo mismo con un contenedor-fichero: hasta la 1.26.24,
    # TextUserInterface.cpp forzaba `options->Quick = false` en esa rama (el
    # volumen se escribía entero), y la 1.26.29 ya no tiene esa línea y el
    # aviso de `--quick` dice que el ahorro depende de que el sistema de
    # ficheros admita dispersos. Visto con el AppImage 1.26.29: un contenedor
    # FAT de 20 MiB ocupa 352 KiB. Se pasa siempre: la 1.26.24 lo ignora sin
    # quejarse (sale con 0 y el fichero ocupa sus 20 MiB) y el AppImage fijado
    # es la 1.26.29.
    return [vc["format"], "--text", "--create", str(container),
            "--volume-type=normal", f"--size={size_bytes}",
            "--encryption=AES", "--hash=sha512", f"--filesystem={filesystem}",
            "--pim=0", "--keyfiles=", "--random-source=/dev/urandom",
            "--quick", "--stdin", "--non-interactive"]


def mount_command(vc: dict, container: Path, password: str,
                  destino: str | Path, etiqueta: str = "") -> list[str]:
    """Devuelve la orden de montar el contenedor.

    `/m rm` monta como MEDIO EXTRAÍBLE y no es un adorno: sin él Windows crea
    `$RECYCLE.BIN` DENTRO del contenedor, o sea dentro de lo que mira rclone, y
    además fuerza más desmontajes. `System Volume Information` no lo evita: en
    Windows 11 24H2 aparece al montar igual que en cualquier USB (visto en las
    pruebas en G:, H-5). No molesta: ninguna pareja sincroniza la raíz del
    dispositivo y `device.RUIDO` la ignora. `/m` se puede repetir: el propio
    `autorun.inf` que genera VeraCrypt emite `/m rm` y `/m ro` en la misma
    orden (Mount.c, TravelerDlgProc).

    `/m label=` es solo cómo lo llama el Explorador; no toca el sistema de
    ficheros de dentro, así que no depende de haberlo formateado de una manera.

    En POSIX no se pasa `rm`: su propio parser lo tiene bajo `#ifdef
    TC_WINDOWS` (CommandLineInterface.cpp) y allí no hace falta, porque Linux
    no deja esas carpetas.

    Args:
        vc: Los ejecutables de VeraCrypt.
        container: El `.hc`.
        password: La contraseña.
        destino: La letra (Windows) o la carpeta (POSIX) donde montar.
        etiqueta: Cómo lo llama el Explorador (solo Windows).
    """
    if IS_WIN:
        etiquetado = ["/m", f"label={etiqueta}"] if etiqueta else []
        return [vc["mount"], "/volume", str(container), "/letter", str(destino),
                "/password", password, "/pim", "0", "/cache", "n",
                "/m", "rm", *etiquetado, "/quit", "/silent"]
    return [vc["mount"], "--text", str(container), str(destino),
            "--pim=0", "--keyfiles=", "--protect-hidden=no",
            "--stdin", "--non-interactive"]


def dismount_command(vc: dict, punto: Path) -> list[str]:
    """Devuelve la orden de desmontar lo que hay en `punto`."""
    if IS_WIN:
        # En Windows se desmonta por letra, no por ruta.
        return [vc["mount"], "/dismount", str(punto)[0], "/quit", "/silent"]
    return [vc["mount"], "--text", "--dismount", str(punto), "--non-interactive"]


def _run(cmd: list[str], password: str = "", timeout: float | None = None):
    """Lanza una orden de VeraCrypt y devuelve el `CompletedProcess`.

    En POSIX la contraseña va por la entrada estándar (`--stdin`) y así no
    aparece en la lista de procesos. En Windows su CLI no lo admite y va como
    argumento; ahí lo único que se puede hacer es no repetirlo en ningún sitio
    (ver `redact()`). La entrada se cierra cuando no se usa: esto corre sin
    terminal y una orden esperando una respuesta se quedaría colgada.
    """
    kwargs: dict = {"text": True, "encoding": "utf-8", "errors": "replace",
                    "capture_output": True}
    if IS_WIN:
        kwargs["creationflags"] = CREATE_NO_WINDOW
        kwargs["stdin"] = subprocess.DEVNULL
    elif password:
        kwargs["input"] = password + "\n"
    else:
        kwargs["stdin"] = subprocess.DEVNULL
    if timeout is not None:
        kwargs["timeout"] = timeout
    return subprocess.run(cmd, **kwargs)


def _procesos(nombre: str) -> set[int]:
    """Devuelve los pid de los procesos vivos cuyo ejecutable se llama `nombre`.

    Solo Windows. Es una indirección de módulo, como
    `_volumenes_con_control()`: los tests la sustituyen. La instantánea de
    Toolhelp está en `common/store.py` porque el agente la necesita también y
    no lleva `install/`.
    """
    return store.procesos_llamados(nombre)


def _esperar_copia_elevada(ejecutable: str, antes: set[int]) -> None:
    """Espera a que terminen los `ejecutable` que no estaban en `antes`.

    Es la regla 2 aplicada a crear. VeraCrypt sin su driver instalado (el que
    viaja) y sin administrador se relanza elevado con `/q UAC` y el proceso
    lanzado sale con 0 a los dos segundos (`Common/Dlgcode.c`, `InitApp` y
    `LaunchElevatedProcess`), mientras la copia sigue escribiendo el
    contenedor. Esa copia es hija de la nuestra y cuando la nuestra sale ya
    existe: sale después del UAC, no antes. En G: Format volvía con el fichero
    128 KiB corto y seguía de 5 s a casi 3 min más; montar en ese hueco dejaba
    el volumen sin sistema de ficheros.

    Se reconoce por el nombre y por no estar antes de lanzar la orden: un
    Format que la persona ya tuviera abierto no hace esperar. El nombre es el
    del ejecutable lanzado (`VeraCrypt Format.exe` de una instalación,
    `VeraCrypt Format-x64.exe` o `-arm64.exe` del portable) porque la copia
    elevada es la misma imagen: `InitApp` relanza lo que le da
    `GetModuleFileNameW` (`Common/Dlgcode.c`). Sin límite de tiempo, como la
    orden sin relanzar: crear un contenedor grande sin `/dynamic` en un USB
    lento son minutos de verdad.
    """
    while _procesos(ejecutable) - antes:
        time.sleep(MOUNT_POLL)


def create_container(vc: dict, container: Path, size_bytes: int, password: str,
                     filesystem: str = "exFAT", dinamico: bool = False,
                     seguimiento: Seguimiento | None = None) -> None:
    """Crea el contenedor.

    Lo que se puede saber antes se dice antes: un tamaño que el sistema de
    ficheros de la unidad no admite se rechaza sin lanzar VeraCrypt, que
    fallaría a medias y sin decir por qué. Y lo que se sabe después, después de
    verdad: no vuelve hasta que termina la copia elevada, si VeraCrypt se ha
    relanzado (`_esperar_copia_elevada()`).

    Args:
        vc: Los ejecutables de VeraCrypt.
        container: Dónde se crea el `.hc`.
        size_bytes: Tamaño del contenedor.
        password: La contraseña.
        filesystem: Sistema de ficheros de dentro.
        dinamico: Si se crea disperso (`/dynamic`).
        seguimiento: Si lo hay, apunta el contador de la unidad justo antes de
            lanzar la orden y lo va leyendo hasta que vuelve: la espera es la
            misma, solo que medida.

    Raises:
        InstallError: Con lo que dijo VeraCrypt, o si el contenedor ya existe o
            no cabe en el sistema de ficheros.
    """
    if container.exists():
        raise InstallError(
            f"Ya existe {container}. Si quieres rehacerlo, bórralo tú a mano: "
            "el instalador no borra contenedores.")
    fs = sistema_de_ficheros(container.parent)
    tope = tope_contenedor(fs)
    if tope is not None and size_bytes > tope:
        raise InstallError(
            f"Esta unidad es {fs}, y en {fs} un fichero no puede llegar a 4 GiB: "
            f"el contenedor es un fichero. Elige {tope // 1024 ** 2}M o menos, o "
            "reformatea la unidad en exFAT o NTFS (eso borra lo que tenga).")
    cmd = create_command(vc, container, size_bytes, password, filesystem, dinamico)
    ejecutable = Path(cmd[0]).name
    antes = _procesos(ejecutable) if IS_WIN else set()
    if seguimiento is not None:
        seguimiento.empezar(container.parent, size_bytes)
    try:
        try:
            res = _run(cmd, password)
        except OSError as e:
            raise InstallError(f"No he podido lanzar VeraCrypt: {e}") from e
        if IS_WIN and res.returncode == 0:
            _esperar_copia_elevada(ejecutable, antes)
    finally:
        if seguimiento is not None:
            seguimiento.parar()
    if res.returncode != 0 or not container.exists():
        raise InstallError(
            "VeraCrypt no ha podido crear el contenedor "
            f"(código {res.returncode}).\n\n{_salida(res)}")


def wait_until_readable(punto: Path, timeout: float = MOUNT_TIMEOUT) -> bool:
    """Espera a poder LEER el punto de montaje y devuelve si lo logra.

    Que exista la letra no basta: entre que VeraCrypt dice que ha montado y que
    el volumen contesta pasa un rato, y en ese hueco un `iterdir()` falla.
    """
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        try:
            # Con `default` no lanza StopIteration: un volumen recién
            # formateado, vacío, también cuenta como legible.
            next(iter(punto.iterdir()), None)
            return True
        except OSError:
            pass            # todavía no está, o está a medio montar
        time.sleep(MOUNT_POLL)
    return False


def en_uso(container: Path) -> bool:
    """Indica si alguien tiene abierto el contenedor (si está montado).

    Mismo truco que `components.rclone_en_uso()`: se abre para escritura, que
    contesta sin enumerar procesos. Mientras el volumen está montado, VeraCrypt
    mantiene el `.hc` abierto en exclusiva y Windows devuelve
    ERROR_SHARING_VIOLATION.

    En POSIX esto NO es una respuesta: allí el contenedor se abre por un
    dispositivo de bucle y un segundo `open()` no molesta a nadie. Por eso
    `mounted_container()` pregunta a VeraCrypt y solo cae aquí en Windows.
    """
    try:
        if not Path(container).is_file():
            return False
        with open(container, "r+b"):
            return False
    except OSError:
        return True


def _volumenes_con_control() -> list[Path]:
    """Devuelve las unidades montadas que llevan el fichero de control de prdrive.

    Es una indirección de módulo, como `_leer_estado_bitlocker()`: los tests la
    sustituyen y así el barrido de unidades no entra en la batería.
    """
    from . import device
    return [v.root for v in device.list_volumes() if v.has_control]


def _entre_comillas(texto: str) -> str:
    """Devuelve la ruta tal como la escribe `StringConverter::QuoteSpaces()`.

    Es la de VeraCrypt y sale de src/Platform/StringConverter.cpp, igual en los
    tags VeraCrypt_1.26.24 y VeraCrypt_1.26.29 y en `master`. Solo entrecomilla
    si hay algún espacio (L' ', no un tabulador), con comillas simples, y dobla
    las simples de dentro: `/media/u/USB DISK` sale como `'/media/u/USB DISK'`,
    y `/media/u/O'Neil x` como `'/media/u/O''Neil x'`. Nada más: ni barras
    invertidas ni saltos de línea.
    """
    if " " not in texto:
        return texto
    return "'" + texto.replace("'", "''") + "'"


def _sin_comillas(campo: str) -> str | None:
    """Devuelve la inversa de `_entre_comillas()`, o `None` si no es suya.

    Es `None` si `campo` no es algo que `QuoteSpaces()` haya podido escribir.
    No hay ambigüedad: lo que devuelve QuoteSpaces lleva un espacio si y solo
    si lo ha entrecomillado. Un campo sin espacios es literal, aunque tenga
    comillas; uno con espacios tiene que ser `'…'` con todas las de dentro
    dobladas.
    """
    if " " not in campo:
        return campo
    if campo[0] != "'" or campo[-1] != "'":
        return None
    dentro = campo[1:-1]
    if "'" in dentro.replace("''", ""):
        return None             # una comilla suelta: QuoteSpaces no escribe eso
    return dentro.replace("''", "'")


def _punto_en_listado(listado: str, container: Path) -> Path | None:
    r"""Devuelve dónde lista `veracrypt --list` el montaje de `container`, o `None`.

    El formato es el de `UserInterface::ListMountedVolumes()`
    (src/Main/UserInterface.cpp, igual en los tags VeraCrypt_1.26.24 y
    VeraCrypt_1.26.29 y en `master`), un registro por volumen:

        <ranura>": " Q(ruta) (" " dispositivo | " - ") (" " Q(punto) | " - ") "\n"

    con Q = `QuoteSpaces()`. El dispositivo va sin comillas, pero es un nodo de
    /dev y no lleva espacios. La ruta del anfitrión es absoluta
    (CommandLineInterface.cpp la pasa por `wxFileName::Normalize` con
    `wxPATH_NORM_ABSOLUTE | wxPATH_NORM_DOTS`, sin resolver enlaces). El punto
    de montaje sale de `getmntent()` (src/Core/Unix/Linux/CoreLinux.cpp), que
    ya ha convertido el `\040` de /etc/mtab en un espacio de verdad: udisks
    monta en `/media/<usuario>/<ETIQUETA>`, y una etiqueta como «USB DISK»
    llega entre comillas en los dos campos.

    Por eso la ruta no se trocea: se CODIFICA. Se escribe la nuestra como la
    escribiría VeraCrypt y se mira si el registro empieza por ella y un
    espacio. Con las comillas de dentro dobladas, una comilla seguida de un
    espacio solo puede ser el cierre de ese campo, así que no hace falta
    adivinar dónde acaba. El punto de montaje es el último campo, o sea el
    resto del registro, y `-` sigue queriendo decir «sin montar».

    Lo único que QuoteSpaces no escapa es el salto de línea: una ruta que lo
    lleve parte su registro en dos y entonces ya no se sabe dónde acaba. Por la
    salida estándar solo salen registros (avisos y errores van a `wcerr`,
    TextUserInterface.cpp) y cada uno termina en '\n', así que una línea que no
    empieza por `<ranura>: `, o una última que no llega entera, invalida el
    listado entero. Mejor contestar `None`, intentar el montaje y que VeraCrypt
    diga lo suyo, que devolver una carpeta que no es.
    """
    *registros, cola = listado.split("\n")
    if cola:
        return None                 # el último registro no llegó entero
    propio = _entre_comillas(str(container)) + " "
    punto = None
    for registro in registros:
        ranura, dos_puntos, campos = registro.partition(": ")
        if not (dos_puntos and ranura.isascii() and ranura.isdigit()):
            return None             # un registro partido por un salto de línea
        if campos.startswith(propio):
            _dispositivo, _, resto = campos[len(propio):].partition(" ")
            punto = _sin_comillas(resto.strip(" "))
    return Path(punto) if punto and punto != "-" else None


def mounted_container(vc: dict, container: Path) -> Path | None:
    """Devuelve dónde está YA montado ese contenedor, o `None`.

    En POSIX se le pregunta a VeraCrypt: `--text --list` imprime, por volumen
    montado, la ruta del anfitrión y el punto de montaje
    (CommandLineInterface.cpp registra `--list`). Es una respuesta exacta
    siempre que se lea con su formato (`_punto_en_listado()`).

    En Windows NO hay listado por línea de órdenes (el suyo vive en el driver)
    y hay que ir por el otro lado, con dos condiciones que tienen que darse las
    dos. La primera es `en_uso()`, y es la que impide el falso positivo que
    importa: sin ella, otro prdrive enchufado a la vez (con su fichero de
    control, como es natural) se leería como «aquí está montado el nuestro» y
    el instalador seguiría adelante sobre el dispositivo equivocado. La segunda
    es que haya **exactamente una** unidad candidata, por lo mismo que
    `Conflicto.version(lado)` devuelve `None` con cero o con dos: cuando hay
    dos, adivinar es peor que no saberlo.

    La asimetría es real y se dice en vez de disimularse: en Windows, un
    contenedor recién creado, que todavía no tiene fichero de control, no se
    reconoce aquí y quien llama acaba intentando el montaje. No pasa nada: el
    mensaje de `explicar_montaje()` sí sabe leer `en_uso()`.
    """
    if not IS_WIN:
        try:
            res = _run([vc["mount"], "--text", "--list", "--non-interactive"],
                       timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return _punto_en_listado(res.stdout or "", container)

    if not en_uso(container):
        return None         # nadie lo tiene abierto: no está montado, y punto
    fisico = Path(container).parent
    candidatos = [r for r in _volumenes_con_control() if r != fisico]
    return candidatos[0] if len(candidatos) == 1 else None


def mount_container(vc: dict, container: Path, password: str,
                    letra: str | None = None,
                    etiqueta: str = DEVICE_LABEL,
                    punto_fijo: Path | None = None) -> Path:
    """Monta el contenedor y devuelve dónde ha quedado.

    NO se mira el código de retorno para decidir si ha ido bien: VeraCrypt
    eleva por UAC a un proceso aparte y lo que devuelve el lanzado no dice nada
    del montaje. Lo que decide es que el punto de montaje se pueda leer.

    Si ya estaba montado no se vuelve a montar: montar dos veces el mismo
    contenedor da una segunda letra o un error, y ninguna de las dos cosas es
    lo que quiere quien vuelve atrás en el asistente.

    Args:
        vc: Los ejecutables de VeraCrypt.
        container: El `.hc`.
        password: La contraseña.
        letra: La letra de unidad (solo Windows); si falta, una libre.
        etiqueta: Cómo lo llama el Explorador.
        punto_fijo: Para la raíz cifrada de un equipo en POSIX: se monta en esa
            carpeta (`~/PRDRIVE`) y no en una temporal, porque es donde el
            agente la buscará y donde apuntan los programas. En Windows lo fijo
            es la `letra`.

    Raises:
        InstallError: Si no existe el contenedor o no se llega a poder leer el
            montaje.
    """
    if not container.is_file():
        raise InstallError(f"No existe el contenedor {container}.")

    ya = mounted_container(vc, container)
    if ya is not None and wait_until_readable(ya, timeout=MOUNT_POLL):
        return ya

    if IS_WIN:
        destino = (letra or free_drive_letter()).rstrip(":").upper()
        punto = Path(f"{destino}:\\")
    elif punto_fijo is not None:
        punto = Path(punto_fijo)
        try:
            punto.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise InstallError(f"No he podido crear {punto}: {e}") from e
        destino = punto
    else:
        punto = Path(tempfile.mkdtemp(prefix="prdrive-mnt-"))
        destino = punto

    cmd = mount_command(vc, container, password, destino, etiqueta)
    try:
        res = _run(cmd, password, timeout=MOUNT_TIMEOUT)
    except subprocess.TimeoutExpired:
        res = None      # puede haber montado igualmente; lo dice el punto
    except OSError as e:
        raise InstallError(f"No he podido lanzar VeraCrypt: {e}") from e

    if wait_until_readable(punto):
        return punto

    detalle = _salida(res) if res is not None else "VeraCrypt no ha respondido a tiempo."
    raise InstallError(
        f"El contenedor no se ha montado en {punto}.\n\n{detalle}\n\n"
        + explicar_montaje(res, container))


def dismount(vc: dict, punto: Path) -> None:
    """Desmonta lo que hay en `punto`.

    Que falle no es grave: la persona puede hacerlo desde VeraCrypt.

    Raises:
        InstallError: Si VeraCrypt no ha podido desmontarlo.
    """
    try:
        res = _run(dismount_command(vc, punto), timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise InstallError(f"No he podido desmontar {punto}: {e}") from e
    if res.returncode != 0:
        raise InstallError(
            f"VeraCrypt no ha podido desmontar {punto} (código {res.returncode}).\n\n"
            f"{_salida(res)}\n\n¿Hay algún programa usando la unidad?")


def _salida(res) -> str:
    """Devuelve la salida de una orden como un texto para enseñar."""
    if res is None:
        return ""
    return ((res.stdout or "") + "\n" + (res.stderr or "")).strip() or "(sin salida)"


FALLOS_MONTAJE = (
    ("incorrect password", "La contraseña no es la de este contenedor."),
    ("not a veracrypt volume",
     "Ese fichero no es un contenedor de VeraCrypt, o está dañado."),
    ("administrator privileges",
     "VeraCrypt no ha conseguido permisos de administrador: o se canceló el "
     "aviso, o este usuario no puede darlos."),
    ("no such file", "VeraCrypt dice que no encuentra el contenedor."),
)
"""Agujas concretas en lo que dice VeraCrypt y su traducción, en minúsculas.

Mismo criterio que `sync.KNOWN_ERRORS`: lo específico primero y, si no casa
nada, el texto general SIN inventarse una causa.
"""


def explicar_montaje(res, container: Path) -> str:
    """Devuelve por qué no aparece montado el contenedor.

    En Windows `/silent` se traga los mensajes y el código de retorno no dice
    nada del montaje, así que lo normal es no tener ninguna aguja que buscar;
    ahí lo único que se puede afirmar es lo que se ha COMPROBADO (que el
    fichero está abierto) y, si tampoco, el texto general, que dice «lo más
    habitual» y no «ha pasado esto». Una causa inventada es peor que ninguna.
    """
    salida = _salida(res).lower()
    for aguja, explicacion in FALLOS_MONTAJE:
        if aguja in salida:
            return explicacion
    if IS_WIN and en_uso(container):
        return ("El contenedor está abierto, así que lo más probable es que YA "
                "esté montado: en otra unidad, o por otro usuario. Míralo en "
                "VeraCrypt antes de volver a intentarlo.")
    return ("Lo más habitual: la contraseña no es esa, o se ha cancelado el "
            "aviso de permisos de administrador que pide VeraCrypt para montar.")


def revisar_contrasena(password: str) -> tuple[str | None, str | None]:
    """Devuelve `(error, aviso)` sobre la contraseña de un contenedor NUEVO.

    El error impide seguir; el aviso se pregunta. Es lo que diría VeraCrypt si
    no le pasáramos `/silent`: su CLI de creación llama a
    `CheckPasswordLength(…, Silent, Silent)` (`Format/Tcformat.c`) y con
    `/silent` se salta la pregunta de «contraseña corta» (`Common/Password.c`).
    Sin esto se aceptaba cualquier contraseña no vacía para proteger la clave
    privada del remoto.

    Se mide en bytes UTF-8, como mide VeraCrypt (ver `CONTRASENA_MAX`).
    """
    largo = len(password.encode("utf-8"))
    if largo == 0:
        return "Falta la contraseña.", None
    if largo > CONTRASENA_MAX:
        return (f"La contraseña ocupa {largo} bytes y VeraCrypt admite como mucho "
                f"{CONTRASENA_MAX} (cada letra con tilde cuenta dos)."), None
    if largo < CONTRASENA_AVISO:
        return None, (
            f"La contraseña tiene menos de {CONTRASENA_AVISO} caracteres. "
            "VeraCrypt recomienda 20 o más: una corta se puede romper probando, "
            "y dentro del contenedor va la clave de tu remoto.\n\n"
            "¿Seguir con esta contraseña?")
    return None, None


def _es_la_guia(ruta: Path) -> bool:
    """Indica si `ruta` es la guía rápida que el instalador deja en la raíz.

    Es el `README.md` de `deploy.write_guide()`, y lo es solo si es idéntico a la
    guía que lleva este instalador: un `README.md` de la persona, con lo que sea
    dentro, es contenido suyo y cuenta como resto como cualquier otro. Una guía
    de otra versión tampoco se reconoce (y se lista): no se la da por nuestra a
    ojo.
    """
    from . import deploy
    try:
        return (ruta.name.lower() == deploy.GUIDE_TARGET.lower() and ruta.is_file()
                and ruta.read_bytes()
                == (bundle_dir() / deploy.GUIDE_SOURCE).read_bytes())
    except OSError:
        return False


def restos_en_claro(raiz_fisica: str | Path) -> list[str]:
    """Devuelve lo que un prdrive SIN cifrar dejó en la raíz física, si lo hay.

    Pasa al «Reinstalar desde cero» con VeraCrypt sobre un dispositivo que iba
    sin cifrar: el contenedor se crea al lado y la instalación anterior, con
    `.prdrive/keys/` y la clave del remoto en claro y las carpetas de datos,
    sigue ahí. Crear el contenedor no la mueve ni la borra, y no debe hacerlo
    solo: esas carpetas pueden llevar cambios que no están en el remoto.

    Returns:
        `.prdrive/` y lo que haya en la raíz que no sea ruido (`device.es_ruido()`:
        lo que deja el sistema o escribe el instalador) ni la guía rápida del
        instalador (`_es_la_guia()`: no lleva datos ni clave); es decir, las
        carpetas y ficheros de datos. La lista vacía si ahí no hay un prdrive.
    """
    from . import device
    raiz = Path(raiz_fisica)
    try:
        if not ((raiz / device.CONTROL_FILE).exists()
                or (raiz / device.STRUCT_MARKER).exists()):
            return []
        otros = sorted((p for p in raiz.iterdir()
                        if not device.es_ruido(p.name) and not _es_la_guia(p)),
                       key=lambda p: p.name.lower())
        return [f"{device.APP_SUBDIR}/"] + [
            p.name + ("/" if p.is_dir() else "") for p in otros]
    except OSError:
        return []


def hay_clave_en_claro(raiz_fisica: str | Path) -> bool:
    """Indica si la instalación sin cifrar de esa raíz tiene un fichero de clave.

    Es `.prdrive/keys/` con algún fichero dentro. Un remoto sin clave (otra
    forma de autenticarse, o ninguna) no la deja, y entonces no se puede decir
    que esté ahí.
    """
    from . import device
    try:
        return any(p.is_file() for p in (Path(raiz_fisica) / device.APP_SUBDIR
                                         / "keys").iterdir())
    except OSError:
        return False


def aviso_restos(restos: list[str], raiz_fisica: str | Path) -> str:
    """Devuelve el texto que se enseña cuando `restos_en_claro()` encuentra algo.

    Args:
        restos: Lo que devolvió `restos_en_claro()`.
        raiz_fisica: La raíz de la que salieron: dice si de verdad hay una clave
            en claro (`hay_clave_en_claro()`) de la que avisar.
    """
    lista = ", ".join(restos[:6]) + ("…" if len(restos) > 6 else "")
    cambios = "las carpetas pueden tener cambios que todavía no están en el remoto."
    clave = hay_clave_en_claro(raiz_fisica)
    return (
        f"En la raíz de la unidad sigue una instalación SIN CIFRAR: {lista}. "
        "Crear el contenedor no la mueve ni la borra. "
        + ("Ahí está la clave de tu remoto en claro (.prdrive/keys/), y " + cambios
           if clave else cambios.capitalize())
        + "\n\n"
        "Cuando hayas comprobado que no falta nada, bórrala a mano. Y en memoria "
        "flash borrar no garantiza que no se pueda recuperar"
        + (": si alguien pudo copiar el dispositivo mientras iba sin cifrar, "
           "cambia la clave del remoto." if clave else "."))


def comprobar_restos(raiz_fisica: str | Path) -> list:
    """Devuelve la fila del último paso: vacía si no hay restos, roja si los hay."""
    from .device import Check
    restos = restos_en_claro(raiz_fisica)
    if not restos:
        return []
    return [Check("Instalación sin cifrar", False,
                  "fuera del contenedor siguen " + ", ".join(restos[:6])
                  + ("…" if len(restos) > 6 else "")
                  + ": bórrala a mano cuando compruebes que no falta nada")]


from common import bitlocker as _bl
from common.bitlocker import (  # noqa: F401 — se reexportan con sus nombres de siempre
    BDE_DECRYPTING, BDE_ENCRYPTING, BDE_LOCKED, BDE_NOT_ENCRYPTABLE, BDE_OFF, BDE_ON,
    BDE_SUSPENDED, BDE_TEXTOS, BDE_WAITING, IID_ISHELLITEM2, PKEY_BITLOCKER_FMTID,
    PKEY_BITLOCKER_PID, BitLockerStatus)


def _leer_estado_bitlocker(ruta: str) -> int:
    """Devuelve el valor de `System.Volume.BitLockerProtection` (ver `common/bitlocker.py`).

    Es la indirección que sustituyen los tests; la lectura está en común.
    """
    return _bl._leer_estado_bitlocker(ruta)


def bitlocker_status(letra: str) -> BitLockerStatus:
    """Devuelve el estado de BitLocker de una unidad (ver `common.bitlocker.estado_de()`)."""
    return _bl.estado_de(letra, _leer_estado_bitlocker, IS_WIN)


def open_bitlocker_setup(letra: str) -> None:
    """Abre el asistente de BitLocker de Windows para esa unidad.

    Cifrar lo hace Windows, no nosotros: automatizarlo con manage-bde exige
    permisos, tarda mucho y falla de formas distintas en cada edición. Lo que
    sí aporta el instalador es abrirlo en el sitio y comprobar después.

    Son dos `os.startfile` y no un PowerShell con dos `Start-Process`: hacen lo
    mismo sin lanzar un intérprete de órdenes, que es justo lo que mira un
    antivirus. `ms-settings:` abre la página de cifrado, y la unidad abre el
    Explorador, que es donde está «Activar BitLocker» en las ediciones que no
    traen esa página. Se intentan por separado: si esta edición de Windows no
    resuelve `ms-settings:`, eso no puede llevarse por delante la ventana del
    Explorador, que es la que sirve en todas.

    Raises:
        InstallError: Si no es Windows o no se abre ninguna de las dos.
    """
    if not IS_WIN:
        raise InstallError("BitLocker es solo de Windows.")
    letra = letra.rstrip(":").upper()
    abiertas, fallos = 0, []
    for destino in ("ms-settings:deviceencryption", f"{letra}:\\"):
        try:
            os.startfile(destino)          # type: ignore[attr-defined]
            abiertas += 1
        except OSError as e:
            fallos.append(f"{destino}: {e}")
    if not abiertas:
        raise InstallError("No he podido abrir el asistente de BitLocker.\n\n"
                           + "\n".join(fallos))
