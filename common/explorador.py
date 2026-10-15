#!/usr/bin/env python3
r"""El nombre y el icono de la letra de un volumen VeraCrypt en el Explorador de Windows.

El Explorador no lee nunca el `autorun.inf` de un volumen que monta VeraCrypt
(#63: su ficha de `MountPoints2` no tiene `_Autorun` y el shell da el icono
genérico, `imageres.dll,-35`, con la etiqueta del sistema de ficheros). Lo que
sí lee, para cualquier letra, son dos claves del registro de la persona:

    HKCU\Software\Classes\Applications\Explorer.exe\Drives\<letra>\DefaultIcon
    HKCU\Software\Classes\Applications\Explorer.exe\Drives\<letra>\DefaultLabel

con la ruta ABSOLUTA del icono y el nombre en su valor predeterminado. Visto en
un Windows 11 real (build 26100): `DefaultIcon` en la letra de un volumen
VeraCrypt abierto, y los dos en una letra de `subst`; una ventana nueva de
«Este equipo» los enseña sin reconectar nada y, al borrarlas, vuelve lo de
antes. No piden administrador. La de `...\Explorer\DriveIcons\<letra>` en HKCU
el shell la ignora.

Así que aquí se copia a esas claves lo que dice el `autorun.inf` del volumen
montado (`label=` e `icon=`, que siguen siendo lo único que manda: lo escribe
«Nombre e icono de la unidad», `ui/volumen.py`). Solo en Windows, solo para la
letra de un volumen de VeraCrypt (`de_veracrypt()`) y solo mientras está
abierto, porque la clave va por letra y la letra la puede tomar luego otra
unidad:
- `poner()` las escribe al abrir prdrive desde el volumen (ventana o servicio,
  `runsync.py`), al atenderlo el agente y al guardar un nombre o un icono.
- `quitar()` las borra al expulsarlo o bloquearlo, y `limpiar()` las que se han
  quedado huérfanas (cerrado desde VeraCrypt, o quitado sin expulsar).

**Cuáles son de prdrive:** cada subclave que se escribe lleva al lado del
predeterminado un valor `MARCA` con el id del dispositivo (el `id=` de su
fichero de control). Sin esa marca no es nuestra y no se toca, aunque esté en
la misma letra; y las claves de encima (`Drives\<letra>`, `Drives`,
`Explorer.exe`) solo se borran si quedan vacías.

Las llamadas al sistema son puntos de indirección que los tests sustituyen:
`de_veracrypt()`, `avisar_shell()`, `letra_de()` y `raiz_de()`, además de las
de `common/registro.py`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PureWindowsPath

from . import APP_NAME, autorun, registro

APLICACION = r"Software\Classes\Applications\Explorer.exe"
"""La clave del Explorador en las clases de la persona: se borra si queda vacía."""
DRIVES = APLICACION + r"\Drives"
"""Donde cuelga una subclave por letra."""
ICONO = "DefaultIcon"
NOMBRE = "DefaultLabel"
MARCA = APP_NAME.upper()
"""Nombre del valor que dice que una subclave es de prdrive; lleva el id del dispositivo."""

DISPOSITIVO_VERACRYPT = "\\Device\\VeraCryptVolume"
r"""Prefijo del dispositivo NT de un volumen que monta VeraCrypt.

Es `NT_MOUNT_PREFIX` (`Common/Apidrvr.h`), seguido de la letra: el propio
`VeraCrypt.exe` 1.26.29 lleva `\Device\VeraCryptVolume%c`, y en Windows 11
`QueryDosDeviceW("H:")` da `\Device\VeraCryptVolumeH` con el contenedor abierto
en H:.
"""

SHCNE_UPDATEITEM = 0x00002000
SHCNF_PATHW = 0x0005
"""`SHChangeNotify(SHCNE_UPDATEITEM, SHCNF_PATHW, …)`: «ha cambiado este elemento» (`shlobj_core.h`)."""

_RAIZ = re.compile(r"[A-Za-z]:[\\/]")


def letra_de(raiz: Path | str) -> str | None:
    r"""Devuelve la letra en mayúscula si `raiz` es la raíz de una unidad (`H:\`), o `None`.

    Una carpeta montada como volumen no tiene letra que nombrar. Es función de
    módulo para que los tests, sin letras de verdad, la sustituyan.
    """
    texto = str(raiz)
    return texto[0].upper() if _RAIZ.fullmatch(texto) else None


def raiz_de(letra: str) -> Path:
    """Devuelve la raíz de una letra, `H:\\`. Los tests la sustituyen."""
    return Path(f"{letra}:\\")


def de_veracrypt(letra: str) -> bool:
    """Indica si esa letra es un volumen que ha montado VeraCrypt.

    Lo dice el nombre de su dispositivo (`QueryDosDeviceW`), sin leer nada de la
    unidad: no saca el diálogo de «no hay disco» de un lector de tarjetas vacío.
    Un contenedor arrancado sin expulsar deja la letra con el mismo nombre hasta
    que se cierra en VeraCrypt; mientras, sigue contando como suyo. Punto de
    indirección. Fuera de Windows, o si no se puede preguntar, `False`.
    """
    if os.name != "nt":
        return False
    try:
        import ctypes

        destino = ctypes.create_unicode_buffer(1024)
        escritos = ctypes.windll.kernel32.QueryDosDeviceW(f"{letra}:", destino, 1024)
    except (OSError, AttributeError, ValueError):
        return False
    return bool(escritos) and destino.value.lower().startswith(DISPOSITIVO_VERACRYPT.lower())


def letra_veracrypt(raiz: Path | str) -> str:
    """Devuelve la letra de `raiz` si es la raíz de un volumen VeraCrypt, o vacío.

    Es donde `poner()` actúa: la ventana de «Nombre e icono» lo usa para decir
    cuándo se verá lo que guarde.
    """
    letra = letra_de(raiz)
    return letra if letra is not None and de_veracrypt(letra) else ""


def avisar_shell(raiz: Path | str) -> None:
    """Le dice al Explorador que esa unidad ha cambiado, para que la vuelva a pintar.

    Una ventana nueva de «Este equipo» ya lee las claves sin esto; es para la
    que está abierta. Punto de indirección; no lanza.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes

        avisar = ctypes.windll.shell32.SHChangeNotify
        avisar.argtypes = [wintypes.LONG, wintypes.UINT, wintypes.LPCVOID, wintypes.LPCVOID]
        avisar.restype = None
        avisar(SHCNE_UPDATEITEM, SHCNF_PATHW, ctypes.c_wchar_p(str(raiz)), None)
    except (OSError, AttributeError, ValueError):
        pass


def _carpeta(app: str | None) -> str:
    """Devuelve el nombre de la carpeta del programa en una raíz (`.prdrive`)."""
    if app:
        return app
    from . import model
    return model.APP_DIR.name


def _id(raiz: Path, app: str | None) -> str:
    """Devuelve el id del dispositivo que vive en esa raíz, o vacío si no hay ninguno."""
    from . import fleet
    return fleet.device_id(raiz / _carpeta(app))


def icono_absoluto(raiz: Path | str, icono: str) -> str:
    r"""Devuelve la ruta absoluta de un `icon=` relativo a esa raíz, o vacío si no vale.

    Vale un fichero que existe dentro de la raíz, dado relativo y sin `..`, y
    sin coma: `icon=fichero,3` elige uno de varios iconos de un `.exe` o un
    `.dll`, y el que pone prdrive es un `.ico` con uno solo.
    """
    if not icono or "," in icono or '"' in icono:
        return ""
    relativa = PureWindowsPath(icono)
    if relativa.drive or relativa.root or ".." in relativa.parts or not relativa.parts:
        return ""
    fichero = Path(raiz).joinpath(*relativa.parts)
    try:
        return str(fichero) if fichero.is_file() else ""
    except OSError:
        return ""


def _clave(letra: str, sub: str = "") -> str:
    return f"{DRIVES}\\{letra}" + (f"\\{sub}" if sub else "")


def _fijar(letra: str, sub: str, valor: str, dispositivo: str) -> bool:
    """Deja `valor` en esa subclave de la letra, o la quita si va vacío.

    Una subclave que existe con algo dentro y sin `MARCA` es de otro y no se
    toca. La marca va antes que el valor: si algo corta a medias, queda una
    subclave nuestra sin nada que enseñar.

    Returns:
        Si ha cambiado algo.

    Raises:
        OSError: Si el registro no deja escribir o borrar.
    """
    clave = _clave(letra, sub)
    marca = registro.leer(clave, MARCA)
    if marca is None and registro.vacia(clave) is False:
        return False
    if not valor:
        return marca is not None and registro.borrar(clave)
    if marca == dispositivo and registro.leer(clave) == valor:
        return False
    registro.escribir(clave, dispositivo, MARCA)
    registro.escribir(clave, valor)
    return True


def _podar(letra: str) -> None:
    """Borra la subclave de la letra y las de encima, de una en una, mientras queden vacías."""
    for clave in (_clave(letra), DRIVES, APLICACION):
        if registro.vacia(clave) is not True:
            return
        registro.borrar(clave)


def poner(raiz: Path | str, app: str | None = None) -> bool:
    """Le dice al Explorador el nombre y el icono de la unidad que está en `raiz`.

    Los saca del `autorun.inf` de `raiz` y los deja en las claves de su letra;
    lo que el fichero no tiene se quita de ellas. No hace nada si `raiz` no es
    la raíz de una letra de un volumen VeraCrypt, o si en ella no vive un
    dispositivo de prdrive (sin id no hay con qué marcarlas). No lanza: el
    nombre y el icono adornan, y quien llama sigue con lo suyo.

    Args:
        raiz: La raíz del volumen montado, donde están el `autorun.inf` y la
            carpeta del programa.
        app: El nombre de esa carpeta (`.prdrive`); por defecto, el de
            `APP_DIR`. El agente, cuyo `APP_DIR` es su propia carpeta, lo dice.

    Returns:
        Si las claves de esa letra quedan como dice el `autorun.inf`.
    """
    try:
        letra = letra_veracrypt(raiz)
        if not letra:
            return False
        dispositivo = _id(Path(raiz), app)
        if not dispositivo:
            return False
        actual = autorun.leer(raiz)
        cambiado = _fijar(letra, ICONO, icono_absoluto(raiz, actual.icono), dispositivo)
        cambiado = _fijar(letra, NOMBRE, actual.etiqueta, dispositivo) or cambiado
        _podar(letra)
    except Exception:                                   # noqa: BLE001
        return False
    if cambiado:
        avisar_shell(raiz)
    return True


def _quitar_letra(letra: str, dispositivo: str | None) -> bool:
    """Borra las subclaves de prdrive de esa letra (solo las de `dispositivo`, si se da)."""
    quitadas = False
    for sub in (ICONO, NOMBRE):
        clave = _clave(letra, sub)
        marca = registro.leer(clave, MARCA)
        if marca is not None and dispositivo in (None, marca):
            quitadas = registro.borrar(clave) or quitadas
    _podar(letra)
    return quitadas


def quitar(raiz: Path | str, dispositivo: str | None = None) -> bool:
    """Borra el nombre y el icono que prdrive le puso a la letra de `raiz`.

    Es para cuando el volumen se va (expulsarlo, bloquearlo o verlo
    desaparecer): la letra queda libre para otra unidad. Solo se van las
    subclaves con `MARCA`; las de otros, y las de encima con algo dentro, se
    quedan. No lanza.

    Args:
        raiz: La raíz del volumen, que puede no estar ya.
        dispositivo: Si se da, solo las de ese id: otra unidad nuestra que ya
            haya tomado la letra conserva las suyas.

    Returns:
        Si se ha borrado alguna.
    """
    try:
        letra = letra_de(raiz)
        return letra is not None and _quitar_letra(letra, dispositivo)
    except Exception:                                   # noqa: BLE001
        return False


def limpiar(app: str | None = None) -> list[str]:
    """Borra las claves de prdrive cuya letra ya no tiene ese dispositivo abierto.

    Son las que se quedan cuando el volumen se cierra sin pasar por prdrive
    (desde VeraCrypt, o quitando la unidad sin expulsar). Huérfana es la de
    una letra que no es un volumen VeraCrypt o en la que no vive el dispositivo
    de su `MARCA`. Por el camino se borran las subclaves de letra vacías. No
    lanza.

    Args:
        app: El nombre de la carpeta del programa en una raíz, como en `poner()`.

    Returns:
        Las letras de las que se ha borrado algo.
    """
    limpias = []
    try:
        for letra in registro.subclaves(DRIVES):
            if len(letra) != 1 or not letra.isalpha():
                continue
            letra = letra.upper()
            marcas = {registro.leer(_clave(letra, sub), MARCA) for sub in (ICONO, NOMBRE)}
            marcas.discard(None)
            vivo = de_veracrypt(letra) and _id(raiz_de(letra), app)
            huerfanas = [m for m in marcas if m != vivo]
            if not huerfanas:
                _podar(letra)
                continue
            if any([_quitar_letra(letra, m) for m in huerfanas]):
                limpias.append(letra)
    except Exception:                                   # noqa: BLE001
        pass
    return limpias
