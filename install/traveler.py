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
no es razonable. Lo que sí es exacto y sí se puede hacer es lo que hace ese
mismo diálogo con una instalación MSI: copiar los ficheros instalados,
**renombrando el driver**. Funciona porque `DriverLoad()` (`Common/Dlgcode.c`,
tag VeraCrypt_1.26.24) carga el driver de **la carpeta del propio ejecutable**,
con la arquitectura en el nombre:

    GetModuleFileName(NULL, driverPath, …);     // …\\VeraCrypt\\VeraCrypt.exe
    StringCbCatW(driverPath, …, IsARM()? L"\\veracrypt-arm64.sys"
                                       : L"\\veracrypt-x64.sys");

Y el instalador NO lo deja con ese nombre: en su carpeta lo guarda como
`veracrypt.sys` (`Setup/Setup.c`: el destino es `szFiles[i]+1`, o sea
`Averacrypt.sys` sin la letra; solo el ORIGEN dentro del paquete lleva la
arquitectura). Copiarlo tal cual —lo que se hacía— deja un traveler que no carga
el driver nunca: `DRIVER_NOT_FOUND` en el primer equipo sin VeraCrypt. El diálogo
de VeraCrypt, en el caso MSI, hace exactamente esto: `veracrypt.sys` →
`veracrypt-x64.sys`. Aquí la arquitectura se lee de la cabecera PE del propio
driver (`maquina_pe()`), no se supone.

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
  3. **Solo viaja la arquitectura del equipo que lo prepara, y solo vale en
     esa.** Un VeraCrypt instalado deja el driver de su máquina. Y aquí NO hay
     caída de un solo sentido como la de `model.BIN_FALLBACK_DIRS`: `IsARM()`
     (`Common/Dlgcode.c`) pregunta por la máquina NATIVA con
     `IsWow64Process2`, así que un `VeraCrypt.exe` x64 emulado en un Windows ARM
     busca `veracrypt-arm64.sys` —y aunque encontrara el x64, un driver no se
     emula nunca—. Por eso `comprobar()` dice qué arquitectura lleva en vez de
     limitarse a decir que está.

Todo esto vive en la raíz FÍSICA del volumen, junto al `.hc` —no en
`device_root`, que con VeraCrypt es el contenedor montado—: si estuviera dentro
del contenedor haría falta VeraCrypt para llegar a VeraCrypt.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from common import autorun, vestibulo

from . import CONTAINER_NAME, DEVICE_LABEL, IS_WIN, InstallError
from .device import Check

CARPETA = vestibulo.TRAVELER        # dentro de la raíz física del volumen
AUTORUN = autorun.FICHERO

# Lo único sin lo que no se puede montar. El driver va aparte porque su nombre
# lleva la arquitectura, y cuál sale de su cabecera (ver `nombre_portatil()`).
IMPRESCINDIBLE = vestibulo.TRAVELER_EXE

# Lo que se lleva si está. El Expander es el que puede AGRANDAR el contenedor
# más adelante, y es lo que hace segura la estrategia «empieza pequeño»; la
# licencia viaja porque estamos copiando su programa.
ACOMPANAN = ("VeraCrypt Format.exe", "VeraCryptExpander.exe",
             "License.txt", "NOTICE", "LICENSE")

DRIVERS = "veracrypt*.sys"

# El nombre con el que lo deja el instalador en SU carpeta (`Setup/Setup.c`), y
# el que busca `DriverLoad()` en modo portátil (`Common/Dlgcode.c`). No son el
# mismo, y esa diferencia es todo el problema del traveler.
DRIVER_INSTALADO = "veracrypt.sys"
DRIVER_PORTATIL = re.compile(r"^veracrypt-(x64|arm64)\.sys$", re.IGNORECASE)

# IMAGE_FILE_HEADER.Machine (winnt.h). x86 se reconoce para poder decir qué es,
# pero no viaja: `DriverLoad()` solo busca x64 y arm64.
MAQUINAS_PE = {0x8664: "x64", 0xAA64: "arm64", 0x014C: "x86"}


def origen(vc: dict | None) -> Path | None:
    """La carpeta de donde copiar: donde está el VeraCrypt de este equipo."""
    ruta = (vc or {}).get("mount")
    return Path(ruta).parent if ruta else None


def drivers(carpeta: Path) -> list[Path]:
    """Los `.sys` de VeraCrypt que hay en esa carpeta, se llamen como se llamen.

    Se cogen por patrón y no por nombre: una instalación deja
    `veracrypt.sys`, una carpeta portátil los `veracrypt-<arq>.sys`, y un
    traveler de las versiones anteriores de prdrive, el `veracrypt.sys` tal
    cual. Qué se hace con cada uno lo decide `plan()`."""
    try:
        return sorted(p for p in carpeta.glob(DRIVERS) if p.is_file())
    except OSError:
        return []


def maquina_pe(ruta: Path) -> str | None:
    """Para qué CPU es un binario de Windows, leído de su cabecera PE.

    Es la misma evidencia que usa Windows para cargarlo, y no una suposición
    sobre el equipo que prepara el dispositivo. El formato es fijo: el
    `e_lfanew` de la cabecera DOS (offset 0x3C) apunta a la firma `PE\\0\\0`,
    y detrás va `IMAGE_FILE_HEADER.Machine`, un uint16 little-endian. None si
    no se puede leer o no es un PE."""
    try:
        with open(ruta, "rb") as f:
            if f.read(2) != b"MZ":
                return None
            f.seek(0x3C)
            desplazamiento = int.from_bytes(f.read(4), "little")
            f.seek(desplazamiento)
            if f.read(4) != b"PE\0\0":
                return None
            maquina = f.read(2)
    except OSError:
        return None
    if len(maquina) != 2:
        return None
    return MAQUINAS_PE.get(int.from_bytes(maquina, "little"))


def nombre_portatil(driver: Path) -> str | None:
    """Con qué nombre tiene que viajar ese driver para que VeraCrypt lo cargue.

    Uno que ya lleva la arquitectura en el nombre se queda como está. El
    `veracrypt.sys` de una instalación se renombra con la arquitectura de su
    cabecera, que es lo que hace el propio diálogo de VeraCrypt en el caso MSI
    (`Mount.c`, `TravelerDlgProc`: `veracrypt.sys` → `veracrypt-x64.sys`).
    None si no hay forma de saberlo, o si es de una CPU que `DriverLoad()` no
    busca: un nombre inventado es un traveler que no monta."""
    if DRIVER_PORTATIL.match(driver.name):
        return driver.name.lower()
    if driver.name.lower() != DRIVER_INSTALADO:
        return None
    arq = maquina_pe(driver)
    return f"veracrypt-{arq}.sys" if arq in ("x64", "arm64") else None


def arquitecturas(carpeta: Path) -> list[str]:
    """Para qué máquinas sirve lo que hay en esa carpeta: ['x64'], ['arm64']…

    Solo cuentan los nombres que `DriverLoad()` busca. Un `veracrypt.sys`
    suelto no sirve en modo portátil y por eso no suma, aunque sea x64."""
    nombres = []
    for sys_file in drivers(carpeta):
        encaje = DRIVER_PORTATIL.match(sys_file.name)
        if encaje:
            nombres.append(encaje.group(1).lower())
    return sorted(set(nombres))


def plan(vc: dict | None, raiz: Path) -> list[tuple[Path, Path]]:
    """Qué se copiaría y adónde, sin tocar nada.

    Devuelve pares (origen, destino), y la lista vacía si no hay de dónde
    copiar. Es puro a propósito: es lo que se puede probar en seco. Un driver
    del que no se sabe con qué nombre tiene que viajar (`nombre_portatil()`) no
    entra: `instalar()` protesta si al final no viaja ninguno."""
    fuente = origen(vc)
    if fuente is None or not fuente.is_dir():
        return []
    destino = Path(raiz) / CARPETA
    pares = []
    for nombre in (IMPRESCINDIBLE, *ACOMPANAN):
        candidato = fuente / nombre
        if candidato.is_file():
            pares.append((candidato, destino / nombre))
    finales: dict[str, Path] = {}
    for driver in drivers(fuente):
        final = nombre_portatil(driver)
        # Si la carpeta trae el `veracrypt-x64.sys` y además el `veracrypt.sys`
        # de la misma CPU, gana el que ya tenía el nombre bueno.
        if final and (final not in finales
                      or DRIVER_PORTATIL.match(driver.name)):
            finales[final] = driver
    pares += [(driver, destino / final) for final, driver in sorted(finales.items())]
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
    if not any(DRIVER_PORTATIL.match(d.name) for _, d in pares):
        raise InstallError(
            "No sé con qué nombre tiene que viajar el driver de VeraCrypt de este "
            "equipo: no hay un veracrypt-x64.sys ni un veracrypt-arm64.sys, y la "
            "cabecera del veracrypt.sys no dice que sea de ninguna de las dos. Sin "
            "eso, VeraCrypt portátil no puede cargarlo.")

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


def autorun_texto(label: str = DEVICE_LABEL,
                  contenedor: str = CONTAINER_NAME) -> str:
    """El `autorun.inf` que se deja en la raíz.

    En Windows moderno esto **no** ejecuta nada al conectar —AutoRun lleva
    desactivado para unidades extraíbles desde Windows 7, y eso está bien—, pero
    `label` e `icon` sí los sigue leyendo el Explorador: la unidad deja de
    llamarse «Disco extraíble» y lleva su icono. Qué hace el Explorador con las
    entradas `shell\\…` en un extraíble NO está comprobado aquí; si las
    enseña, que hagan lo correcto.

    El formato es el que escribe el propio VeraCrypt (`Mount.c`,
    `TravelerDlgProc`), con dos correcciones que salen de su código:

      * «Montar» lleva `/v "<contenedor>"`, relativo a la raíz y entre comillas
        como en el suyo. Sin él solo se abría la ventana de VeraCrypt.
      * «Desmontar» es `/dismount` y no `/u`: `/unmount` (`/u`) no existe en
        1.25.9 ni en 1.26.7, y un argumento desconocido aborta con
        COMMAND_LINE_ERROR. `/dismount` lo aceptan todas."""
    return (
        "[autorun]\n"
        f"label={label}\n"
        f"icon={autorun.ICONO_VERACRYPT}\n"
        f"action=Montar el volumen {label}\n"
        f"shell\\montar=Montar el volumen {label}\n"
        f'shell\\montar\\command={CARPETA}\\VeraCrypt.exe /q /m rm /v "{contenedor}"\n'
        f"shell\\desmontar=Desmontar todos los volúmenes\n"
        f"shell\\desmontar\\command={CARPETA}\\VeraCrypt.exe /q /dismount\n"
    )


def write_autorun(raiz: Path, label: str = DEVICE_LABEL) -> Path | None:
    """Escribe el `autorun.inf`. **Mejor esfuerzo**, como `deploy.write_guide()`.

    Si la unidad ya tiene uno, su nombre y su icono se quedan: pueden venir de
    «Ajustes» → «Nombre e icono de la unidad» (`ui/volumen.py`), y esto está
    para poner al día las órdenes de VeraCrypt, no para deshacer lo que eligió
    el usuario. Cómo se escribe —UTF-16, como VeraCrypt— lo dice
    `common/autorun.py`. Que no se pueda escribir no rompe nada —la unidad se
    seguirá llamando «Disco extraíble»—, así que no se levanta."""
    texto = autorun_texto(label)
    actual = autorun.leer(raiz)
    if actual.ruta is not None:
        texto = autorun.con(texto, actual.etiqueta, actual.icono)
    try:
        return autorun.escribir(raiz, texto)
    except OSError:
        return None


def exe_portatil(raiz: Path, nombre: str = IMPRESCINDIBLE) -> Path:
    """La ruta de uno de los ejecutables que viajan en el dispositivo."""
    return Path(raiz) / CARPETA / nombre


def instalado(raiz: Path) -> bool:
    """¿Lleva este volumen un VeraCrypt utilizable?

    Con un driver que VeraCrypt portátil cargue (`arquitecturas()`), no con uno
    cualquiera: el `veracrypt.sys` que dejaban las versiones anteriores está,
    pero no sirve."""
    try:
        return (exe_portatil(raiz).is_file()
                and bool(arquitecturas(Path(raiz) / CARPETA)))
    except OSError:
        return False


def comprobar(raiz: Path) -> list[Check]:
    """Qué VeraCrypt lleva el dispositivo, para la verificación del último paso.

    Dice la arquitectura, no solo que esté: cada una vale SOLO en la suya (ver
    el docstring del módulo), y eso hay que leerlo aquí y no descubrirlo con el
    dispositivo en la mano."""
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
    if not arcs and (carpeta / DRIVER_INSTALADO).is_file():
        detalle = ("el driver se copió como veracrypt.sys, que VeraCrypt portátil "
                   "no busca: vuelve a pulsar «Llevar VeraCrypt en el dispositivo»")
    elif not arcs:
        detalle = "falta el driver (.sys): el ejecutable solo no monta nada"
    elif arcs == ["x64"]:
        detalle = "x64: en un Windows ARM no monta (un driver no se emula)"
    elif arcs == ["arm64"]:
        detalle = "arm64: en un Windows x64 no monta"
    else:
        detalle = ", ".join(arcs)
    checks.append(Check("Driver de VeraCrypt", bool(arcs), detalle))

    hay_expander = exe_portatil(raiz, "VeraCryptExpander.exe").is_file()
    checks.append(Check("VeraCrypt Expander", hay_expander,
                        "sirve para agrandar el contenedor más adelante"
                        if hay_expander else
                        "no está: el contenedor no se podrá agrandar desde aquí"))
    return checks
