#!/usr/bin/env python3
"""
traveler.py — Dejar VeraCrypt DENTRO del dispositivo (Traveler's Disk).

Sin esto, un dispositivo cifrado con VeraCrypt solo sirve en equipos que ya
tengan VeraCrypt instalado, que es justo lo contrario de lo que hace el resto
del proyecto: rclone y el Python viajan en el propio dispositivo. Aquí viaja
también VeraCrypt.

**No hay CLI para esto.** El diálogo «Traveler Disk Setup» de VeraCrypt no copia
los binarios instalados: los EXTRAE del `VeraCrypt Setup.exe` que hay junto a
ellos, con su formato autoextraíble propio y verificando la firma
(`Mount.c`, `TravelerDlgProc`). Replicar eso en Python puro, sin dependencias,
no es razonable. Lo que sí es exacto y sí se puede hacer es lo otro que hace ese
mismo diálogo cuando VeraCrypt ya corre en modo portátil: copiar los ficheros
tal cual. Y funciona porque `DriverLoad()` (`Common/Dlgcode.c`) carga el driver
de **la carpeta del propio ejecutable**:

    GetModuleFileName(NULL, driverPath, …);     // …\\VeraCrypt\\VeraCrypt.exe
    StringCbCatW(driverPath, …, IsARM()? L"\\veracrypt-arm64.sys"
                                       : L"\\veracrypt-x64.sys");

Así que con `VeraCrypt.exe` y su `.sys` al lado, en `<raíz>/VeraCrypt/`, ya hay
un traveler disk que monta.

Tres cosas que hay que decir y no esconder:

  1. **Sigue haciendo falta ser administrador** en el equipo donde se enchufe.
     Cargar un driver no se puede hacer de otra forma, y la documentación de
     VeraCrypt lo dice igual de claro para su modo portátil. Esto ahorra
     instalar, no ahorra el UAC.
  2. **Aquí no se verifica la firma** de lo que se copia, y VeraCrypt sí lo hace
     (`VerifyModuleSignature`). Sin dependencias y sin un envoltorio de COM no
     sale a cuenta: el origen es la carpeta de VeraCrypt instalada, que ya exige
     administrador para escribirse. Lo que no vale es dar a entender que se ha
     comprobado.
  3. **Solo viaja la arquitectura del equipo que lo prepara.** Un VeraCrypt
     instalado moderno ya no lleva x86 —`Setup.h`, `szCompressedFiles`: solo x64
     y arm64— y deja en su carpeta el driver de la máquina. Bien: como el x64
     emulado sí corre en Windows ARM, un traveler disk hecho en x64 vale en los
     dos. Al revés no. Es la misma caída de un solo sentido que ya documenta
     `model.BIN_FALLBACK_DIRS`, y por eso `comprobar()` dice qué arquitectura
     lleva en vez de limitarse a decir que está.

Todo esto vive en la raíz FÍSICA del volumen, junto al `.hc` —no en
`device_root`, que con VeraCrypt es el contenedor montado—: si estuviera dentro
del contenedor haría falta VeraCrypt para llegar a VeraCrypt.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import DEVICE_LABEL, IS_WIN, InstallError
from .device import Check

CARPETA = "VeraCrypt"               # dentro de la raíz física del volumen
AUTORUN = "autorun.inf"

# Lo único sin lo que no se puede montar. El driver va aparte porque su nombre
# lleva la arquitectura y no se puede escribir aquí (ver `drivers()`).
IMPRESCINDIBLE = "VeraCrypt.exe"

# Lo que se lleva si está. El Expander es el que puede AGRANDAR el contenedor
# más adelante, y es lo que hace segura la estrategia «empieza pequeño»; la
# licencia viaja porque estamos copiando su programa.
ACOMPANAN = ("VeraCrypt Format.exe", "VeraCryptExpander.exe",
             "License.txt", "NOTICE", "LICENSE")

DRIVERS = "veracrypt*.sys"


def origen(vc: dict | None) -> Path | None:
    """La carpeta de donde copiar: donde está el VeraCrypt de este equipo."""
    ruta = (vc or {}).get("mount")
    return Path(ruta).parent if ruta else None


def drivers(carpeta: Path) -> list[Path]:
    """Los `.sys` que hay en esa carpeta.

    Se cogen por patrón y no por nombre: el instalador de VeraCrypt deja el de
    la máquina (`veracrypt-x64.sys` o `veracrypt-arm64.sys`) y una instalación
    portátil los tiene todos. Copiar los que haya es correcto en los dos casos;
    inventarse un nombre, no."""
    try:
        return sorted(p for p in carpeta.glob(DRIVERS) if p.is_file())
    except OSError:
        return []


def arquitecturas(carpeta: Path) -> list[str]:
    """Para qué máquinas sirve lo que hay en esa carpeta: ['x64'], ['arm64']…"""
    nombres = []
    for sys_file in drivers(carpeta):
        tallo = sys_file.stem                      # veracrypt-x64
        nombres.append(tallo.split("-", 1)[1] if "-" in tallo else "x86")
    return sorted(set(nombres))


def plan(vc: dict | None, raiz: Path) -> list[tuple[Path, Path]]:
    """Qué se copiaría y adónde, sin tocar nada.

    Devuelve pares (origen, destino), y la lista vacía si no hay de dónde
    copiar. Es puro a propósito: es lo que se puede probar en seco."""
    fuente = origen(vc)
    if fuente is None or not fuente.is_dir():
        return []
    destino = Path(raiz) / CARPETA
    pares = []
    for nombre in (IMPRESCINDIBLE, *ACOMPANAN):
        candidato = fuente / nombre
        if candidato.is_file():
            pares.append((candidato, destino / nombre))
    pares += [(d, destino / d.name) for d in drivers(fuente)]
    return pares


def instalar(vc: dict | None, raiz: Path) -> list[Path]:
    """Copia VeraCrypt a `<raiz>/VeraCrypt/`. Devuelve lo que ha quedado.

    Se sobrescribe lo que hubiera: esto es idempotente a propósito, porque es
    también la forma de poner al día un traveler disk viejo cuando el usuario
    actualiza su VeraCrypt."""
    if not IS_WIN:
        raise InstallError(
            "El traveler disk es cosa de Windows: en Linux y macOS VeraCrypt "
            "necesita instalarse (driver y FUSE), y no se puede llevar en el "
            "dispositivo.")
    pares = plan(vc, raiz)
    if not pares:
        raise InstallError(
            "No encuentro los ficheros de VeraCrypt de este equipo, así que no "
            "hay nada que copiar al dispositivo.")
    if not any(o.name == IMPRESCINDIBLE for o, _ in pares):
        raise InstallError(
            f"En la carpeta de VeraCrypt no está {IMPRESCINDIBLE}: sin él no se "
            "puede montar nada desde el dispositivo.")

    destino = Path(raiz) / CARPETA
    try:
        destino.mkdir(parents=True, exist_ok=True)
        escritos = []
        for fuente, final in pares:
            shutil.copy2(fuente, final)
            escritos.append(final)
    except OSError as e:
        raise InstallError(f"No he podido copiar VeraCrypt al dispositivo: {e}") from e
    return escritos


def autorun_texto(label: str = DEVICE_LABEL) -> str:
    """El `autorun.inf` que se deja en la raíz.

    En Windows moderno esto **no** ejecuta nada al conectar —AutoRun lleva
    desactivado para unidades extraíbles desde Windows 7, y eso está bien—, pero
    `label` e `icon` sí los sigue leyendo el Explorador: la unidad deja de
    llamarse «Disco extraíble» y lleva su icono. Las entradas `shell\\…` son las
    del menú contextual, que también funcionan.

    El formato es el que escribe el propio VeraCrypt (`Mount.c`)."""
    return (
        "[autorun]\n"
        f"label={label}\n"
        f"icon={CARPETA}\\VeraCrypt.exe\n"
        f"action=Montar el volumen {label}\n"
        f"shell\\montar=Montar el volumen {label}\n"
        f"shell\\montar\\command={CARPETA}\\VeraCrypt.exe\n"
        f"shell\\desmontar=Desmontar todos los volúmenes\n"
        f"shell\\desmontar\\command={CARPETA}\\VeraCrypt.exe /q /u\n"
    )


def write_autorun(raiz: Path, label: str = DEVICE_LABEL) -> Path | None:
    """Escribe el `autorun.inf`. **Mejor esfuerzo**, como `deploy.write_guide()`.

    VeraCrypt lo escribe en UTF-16 (`_wfopen(…, L"w,ccs=UNICODE")`) y aquí se
    hace igual: es lo que sabe leer el Explorador cuando la etiqueta lleva
    acentos. Que no se pueda escribir no rompe nada —la unidad se seguirá
    llamando «Disco extraíble»—, así que no se levanta."""
    destino = Path(raiz) / AUTORUN
    try:
        destino.write_text(autorun_texto(label), encoding="utf-16")
    except OSError:
        return None
    return destino


def exe_portatil(raiz: Path, nombre: str = IMPRESCINDIBLE) -> Path:
    """La ruta de uno de los ejecutables que viajan en el dispositivo."""
    return Path(raiz) / CARPETA / nombre


def instalado(raiz: Path) -> bool:
    """¿Lleva este volumen un VeraCrypt utilizable?"""
    try:
        return (exe_portatil(raiz).is_file()
                and bool(drivers(Path(raiz) / CARPETA)))
    except OSError:
        return False


def comprobar(raiz: Path) -> list[Check]:
    """Qué VeraCrypt lleva el dispositivo, para la verificación del último paso.

    Dice la arquitectura, no solo que esté: un traveler disk preparado en un
    Windows ARM **no** sirve en un PC de sobremesa, y eso hay que leerlo aquí y
    no descubrirlo con el dispositivo en la mano."""
    raiz = Path(raiz)
    carpeta = raiz / CARPETA
    checks: list[Check] = []

    try:
        hay_exe = exe_portatil(raiz).is_file()
    except OSError as e:
        return [Check("VeraCrypt portátil", False, f"no se puede leer: {e}")]

    checks.append(Check("VeraCrypt portátil", hay_exe,
                        str(carpeta) if hay_exe
                        else "no está: hará falta VeraCrypt instalado en cada equipo"))
    if not hay_exe:
        return checks

    arcs = arquitecturas(carpeta)
    if not arcs:
        detalle = "falta el driver (.sys): el ejecutable solo no monta nada"
    elif "arm64" in arcs and "x64" not in arcs:
        detalle = "solo arm64: no servirá en un Windows x64"
    else:
        detalle = ", ".join(arcs) + " (el x64 también vale en Windows ARM)"
    checks.append(Check("Driver de VeraCrypt", bool(arcs), detalle))

    hay_expander = exe_portatil(raiz, "VeraCryptExpander.exe").is_file()
    checks.append(Check("VeraCrypt Expander", hay_expander,
                        "sirve para agrandar el contenedor más adelante"
                        if hay_expander else
                        "no está: el contenedor no se podrá agrandar desde aquí"))
    return checks
