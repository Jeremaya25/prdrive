#!/usr/bin/env python3
r"""Dejar VeraCrypt DENTRO del dispositivo (Traveler's Disk).

Sin esto, un dispositivo cifrado con VeraCrypt solo sirve en equipos que ya
tengan VeraCrypt instalado, que es lo contrario de lo que hace el resto del
proyecto: rclone y el Python viajan en el propio dispositivo, y aquí viaja
también VeraCrypt.

Qué viaja: el VeraCrypt Portable oficial, con sus nombres. El paquete de IDRIX,
bajado y comprobado por `install/veracrypt_bin.py` (versión y SHA-256 fijados
en `common/pins.py`), trae un ejecutable por arquitectura (`VeraCrypt-x64.exe`
y `VeraCrypt-arm64.exe`, con su Format y su Expander) y los dos drivers. Se
copian tal cual a `VeraCrypt\`, sin renombrar nada: es lo que hace el propio
diálogo «Traveler Disk Setup» de VeraCrypt en modo portátil (`Mount/Mount.c`,
`TravelerDlgProc`, tag VeraCrypt_1.26.24), y funciona porque `DriverLoad()`
(`Common/Dlgcode.c`) carga el driver de LA CARPETA DEL PROPIO EJECUTABLE, con
la arquitectura en el nombre:

    GetModuleFileName(NULL, driverPath, …);     // …\VeraCrypt\VeraCrypt-x64.exe
    StringCbCatW(driverPath, …, IsARM()? L"\veracrypt-arm64.sys"
                                       : L"\veracrypt-x64.sys");

Con las dos arquitecturas la unidad monta en un Windows x64 y en uno ARM64;
quien abre el contenedor (`Abrir PRDRIVE.bat`, penwatch) escoge la del equipo.

Es un componente: la carpeta lleva un sello, `PRDRIVE-VERACRYPT`
(`common/components.py`), con la versión y el SHA-256 de cada fichero, que se
escribe el último. `--update-components` la pone al día como al rclone.

Se sustituye, nunca se copia encima, como `deploy.install_runtime()`: la
carpeta nueva se hace al lado (`.VeraCrypt.nuevo-<pid>`), se aparta la de antes
y se coloca la nueva de un renombrado. Antes se mira el sitio libre de la raíz
física contra lo que se va a copiar y, si no cabe, no se toca nada: copiar
encima dejaba una mezcla de dos versiones si faltaba sitio a mitad.

Sin red, la copia de la instalación: si el portable no se puede BAJAR
(`veracrypt_bin.SinRed`) y este equipo tiene VeraCrypt, se copia el suyo, de
una sola arquitectura (la de este equipo) y SIN sello. El instalador de
VeraCrypt deja sus ficheros sin la arquitectura en el nombre (`VeraCrypt.exe`,
`veracrypt.sys`…; `Setup/Setup.c`: el destino es `szFiles[i]+1`) y aquí se les
pone, leída de su cabecera PE (`maquina_pe()`), que es lo que hace el diálogo
de VeraCrypt con una instalación MSI (`TravelerDlgProc`: `VeraCrypt.exe` →
`VeraCrypt-x64.exe`, `veracrypt.sys` → `veracrypt-x64.sys`). Un paquete que se
baja y no cuadra NO cae aquí: eso se dice. Y tampoco se cambia así un portable
con sello que ya esté en la unidad: sería cambiar dos arquitecturas comprobadas
por una sin comprobar.

Tres cosas que hay que decir y no esconder:
- Sigue haciendo falta ser administrador en el equipo donde se enchufe: cargar
  un driver no se puede hacer de otra forma, y la documentación de VeraCrypt lo
  dice igual para su modo portátil. Esto ahorra instalar, no el UAC.
- Aquí no se verifica la firma como la verifica VeraCrypt
  (`VerifyModuleSignature`). Lo del portable va comprobado contra el SHA-256
  que apuntó en `pins.py` quien comprobó a mano su firma; lo de una
  instalación, contra nada (viene de la carpeta de VeraCrypt instalada, que ya
  exige administrador para escribirse). No se da a entender otra cosa.
- Cada arquitectura vale solo en la suya: `IsARM()` (`Common/Dlgcode.c`)
  pregunta por la máquina NATIVA con `IsWow64Process2`, así que un VeraCrypt
  x64 emulado en un Windows ARM busca `veracrypt-arm64.sys` (y aunque
  encontrara el x64, un driver no se emula nunca). El portable lleva las dos;
  la copia de una instalación, una, y `comprobar()` dice cuál.

Todo esto vive en la raíz FÍSICA del volumen, junto al `.hc` y no en
`device_root`, que con VeraCrypt es el contenedor montado: dentro del
contenedor haría falta VeraCrypt para llegar a VeraCrypt.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from common import autorun, components, pins, vestibulo

from . import DEVICE_LABEL, IS_WIN, InstallError
from . import veracrypt_bin
from .device import Check
from .runtime_bin import file_sha256

CARPETA = vestibulo.TRAVELER  # dentro de la raíz física del volumen
AUTORUN = autorun.FICHERO
SELLO = components.VERACRYPT_STAMP
ARQUITECTURAS = vestibulo.TRAVELER_ARQUITECTURAS

IMPRESCINDIBLE = vestibulo.TRAVELER_EXE
"""Ejecutable de montar de una INSTALACIÓN.

El origen de la copia sin red y lo que llevan los dispositivos de antes.

Lo que viaja ahora lleva los nombres del portable
(`vestibulo.traveler_portatil()`).
"""

INSTALADOS = {"VeraCrypt.exe": veracrypt_bin.montar,
              "VeraCrypt Format.exe": veracrypt_bin.formatear,
              "VeraCryptExpander.exe": veracrypt_bin.expander}
"""Ejecutables de una instalación, y qué nombre toman en el portable."""

DRIVERS = "veracrypt*.sys"
"""Patrón con el que se buscan los drivers de VeraCrypt."""

DRIVER_INSTALADO = "veracrypt.sys"
"""Nombre del driver en la carpeta de una instalación de VeraCrypt.

Lo deja así `Setup/Setup.c`. No es el que busca `DriverLoad()` en modo portátil
(`Common/Dlgcode.c`, `DRIVER_PORTATIL`), y esa diferencia es todo el problema
del traveler hecho desde una instalación.
"""
DRIVER_PORTATIL = re.compile(r"^veracrypt-(x64|arm64)\.sys$", re.IGNORECASE)
"""Patrón del nombre del driver en modo portátil.

Es `veracrypt-x64.sys` o `veracrypt-arm64.sys`.
"""

MAQUINAS_PE = {0x8664: "x64", 0xAA64: "arm64", 0x014C: "x86"}
"""Valores de `IMAGE_FILE_HEADER.Machine` (winnt.h) y la arquitectura que son.

x86 se reconoce para poder decir qué es, pero no viaja: `DriverLoad()` solo
busca x64 y arm64.
"""

HOLGURA = 1024 ** 2
"""Bytes que se dejan de más al comprobar si cabe.

Cubren el sello, la entrada del directorio y el redondeo a clústeres de cada
fichero.
"""

Progreso = Callable[[str], None]
"""Función que recibe cada mensaje de avance."""


def origen(vc: dict | None) -> Path | None:
    """Devuelve la carpeta del VeraCrypt de este equipo: donde está su ejecutable."""
    ruta = (vc or {}).get("mount")
    return Path(ruta).parent if ruta else None


def drivers(carpeta: Path) -> list[Path]:
    """Devuelve los `.sys` de VeraCrypt de esa carpeta, se llamen como se llamen.

    Se cogen por patrón y no por nombre: una instalación deja `veracrypt.sys`,
    una carpeta portátil los `veracrypt-<arq>.sys` y un traveler de versiones
    anteriores de prdrive el `veracrypt.sys` tal cual. Qué se hace con cada uno
    lo decide `plan()`.
    """
    try:
        return sorted(p for p in carpeta.glob(DRIVERS) if p.is_file())
    except OSError:
        return []


def maquina_pe(ruta: Path) -> str | None:
    r"""Devuelve para qué CPU es un binario de Windows, leído de su cabecera PE.

    Es la misma evidencia que usa Windows para cargarlo y no una suposición
    sobre el equipo que prepara el dispositivo. El formato es fijo: el
    `e_lfanew` de la cabecera DOS (offset 0x3C) apunta a la firma `PE\0\0` y
    detrás va `IMAGE_FILE_HEADER.Machine`, un uint16 little-endian.

    Returns:
        La arquitectura de `MAQUINAS_PE`, o `None` si no se puede leer o no es
        un PE.
    """
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
    """Devuelve con qué nombre tiene que viajar ese driver para que VeraCrypt lo cargue.

    Uno que ya lleva la arquitectura en el nombre se queda como está. El
    `veracrypt.sys` de una instalación se renombra con la arquitectura de su
    cabecera, que es lo que hace el propio diálogo de VeraCrypt en el caso MSI
    (`Mount.c`, `TravelerDlgProc`: `veracrypt.sys` → `veracrypt-x64.sys`).

    Returns:
        El nombre, o `None` si no hay forma de saberlo o es de una CPU que
        `DriverLoad()` no busca: un nombre inventado es un traveler que no
        monta.
    """
    if DRIVER_PORTATIL.match(driver.name):
        return driver.name.lower()
    if driver.name.lower() != DRIVER_INSTALADO:
        return None
    arq = maquina_pe(driver)
    return f"veracrypt-{arq}.sys" if arq in ARQUITECTURAS else None


def arquitecturas(carpeta: Path) -> list[str]:
    """Devuelve para qué máquinas sirve esa carpeta: `['x64']`, `['arm64']`…

    Solo cuentan los nombres que `DriverLoad()` busca: un `veracrypt.sys`
    suelto no sirve en modo portátil y no suma, aunque sea x64.
    """
    nombres = []
    for sys_file in drivers(carpeta):
        encaje = DRIVER_PORTATIL.match(sys_file.name)
        if encaje:
            nombres.append(encaje.group(1).lower())
    return sorted(set(nombres))


def plan(vc: dict | None, raiz: Path) -> list[tuple[Path, Path]]:
    """Devuelve qué se copiaría del VeraCrypt de ESTE equipo y adónde, sin tocar nada.

    Es la copia sin red (ver el docstring del módulo): una instalación o una
    carpeta del portable que haya indicado el usuario. Es pura a propósito,
    para probarla en seco. Lo que no se sabe con qué nombre tiene que viajar no
    entra; `instalar()` protesta si al final no viaja lo imprescindible.

    Returns:
        Pares `(origen, destino)` con los nombres del portable; vacía si no hay
        de dónde copiar.
    """
    fuente = origen(vc)
    if fuente is None or not fuente.is_dir():
        return []
    destino = Path(raiz) / CARPETA
    finales: dict[str, Path] = {}
    # Lo que ya lleva el nombre del portable viaja tal cual…
    for arq in ARQUITECTURAS:
        for nombre in (veracrypt_bin.montar(arq), veracrypt_bin.formatear(arq),
                       veracrypt_bin.expander(arq)):
            if (fuente / nombre).is_file():
                finales[nombre] = fuente / nombre
    # …y lo de una instalación, con la arquitectura de su cabecera. Si la
    # carpeta trae las dos cosas, gana el que ya tenía el nombre bueno.
    for nombre, portatil in INSTALADOS.items():
        candidato = fuente / nombre
        arq = maquina_pe(candidato) if candidato.is_file() else None
        if arq in ARQUITECTURAS:
            finales.setdefault(portatil(arq), candidato)
    for driver in drivers(fuente):
        final = nombre_portatil(driver)
        if final and (final not in finales or DRIVER_PORTATIL.match(driver.name)):
            finales[final] = driver
    for nombre in veracrypt_bin.LICENCIAS:
        if (fuente / nombre).is_file():
            finales[nombre] = fuente / nombre
    return [(src, destino / nombre) for nombre, src in sorted(finales.items())]


def plan_portatil(origen_vc: Path, raiz: Path) -> list[tuple[Path, Path]]:
    """Devuelve lo que se copia del portable comprobado (la caché de `veracrypt_bin`).

    Son los ficheros que dice su sello, con su nombre; el sello va aparte, el
    último.
    """
    destino = Path(raiz) / CARPETA
    return [(Path(origen_vc) / n, destino / n)
            for n in sorted(veracrypt_bin.ficheros_de(origen_vc))]


@dataclass(frozen=True)
class Puesto:
    r"""Lo que ha quedado en `VeraCrypt\`.

    Args:
        carpeta: La carpeta `VeraCrypt\` de la unidad.
        ficheros: Lo escrito; vacío con `portatil` es que ya estaba al día y no
            se ha tocado.
        portatil: Si es el paquete oficial, con las dos arquitecturas y su
            sello; False es la copia de la instalación de este equipo.
        aviso: Por qué es la copia de una instalación, si lo es.
    """
    carpeta: Path
    ficheros: list[Path] = field(default_factory=list)
    portatil: bool = True
    aviso: str = ""

    @property
    def al_dia(self) -> bool:
        """Indica si ya estaba el portable y no se ha tocado nada."""
        return self.portatil and not self.ficheros


def espacio_libre(raiz: Path) -> int | None:
    """Devuelve los bytes libres de esa raíz, o `None` si no se puede saber.

    Es función de módulo para que los tests la sustituyan, como
    `crypto.soporta_dispersos()`: así «no cabe» se prueba sin llenar un disco.
    """
    try:
        return shutil.disk_usage(str(raiz)).free
    except OSError:
        return None


def _mb(n: int) -> str:
    """Devuelve esos bytes en MiB, sin decimales."""
    return f"{n / 1024 ** 2:.0f}"


def limpiar_restos(raiz: Path) -> None:
    """Barre lo que dejó un intercambio anterior, sin ruido y a mejor esfuerzo.

    Es como `components._limpiar_restos()`: un `.VeraCrypt.viejo-*` solo queda
    cuando no se pudo borrar, y lo que procede es volver a intentarlo ahora.
    """
    try:
        restos = [p for p in Path(raiz).iterdir() if vestibulo.es_resto_traveler(p.name)]
    except OSError:
        return
    for resto in restos:
        shutil.rmtree(resto, ignore_errors=True)
        try:
            resto.unlink(missing_ok=True)
        except OSError:
            pass


def sustituir(raiz: Path, pares: list[tuple[Path, Path]],
              sello: str | None = None) -> list[Path]:
    """Deja en `raiz/VeraCrypt/` exactamente los ficheros de `pares` y el sello.

    El sello, si lo hay, se escribe el último.

    Son los tres pasos de `deploy.install_runtime()`: la carpeta nueva al lado,
    la de antes apartada con un renombrado y la nueva en su sitio con otro.
    Antes de nada, el sitio: la nueva convive un momento con la de antes, así
    que hace falta lo que ocupa entera; si no lo hay, no se toca nada. Lo que
    va con sello se vuelve a resumir en la unidad contra él antes de colocarlo.

    Args:
        pares: Pares `(origen, destino)` a copiar.
        sello: Texto del sello, si lo hay.

    Returns:
        Lo escrito.

    Raises:
        InstallError: Si no cabe, no se puede copiar o colocar, o una copia no
            es igual que el original; lo que había queda como estaba.
    """
    raiz = Path(raiz)
    carpeta = raiz / CARPETA
    esperado = components.veracrypt_ficheros(sello) if sello else {}
    try:
        total = sum(src.stat().st_size for src, _ in pares) + len(sello or "")
    except OSError as e:
        raise InstallError(f"No he podido leer lo que hay que copiar: {e}") from e
    libre = espacio_libre(raiz)
    if libre is not None and libre < total + HOLGURA:
        raise InstallError(
            f"No cabe VeraCrypt en {raiz}: hacen falta unos {_mb(total + HOLGURA)} MB "
            f"y quedan {_mb(libre)} MB libres. No se ha tocado nada: el VeraCrypt "
            f"que llevaba sigue como estaba. Libera sitio en la unidad (fuera del "
            f"contenedor) y vuelve a intentarlo.")

    limpiar_restos(raiz)
    nuevo = raiz / f".{CARPETA}.nuevo-{os.getpid()}"
    viejo = raiz / f".{CARPETA}.viejo-{os.getpid()}"
    try:
        nuevo.mkdir(parents=True)
        for src, dst in pares:
            shutil.copyfile(src, nuevo / dst.name)
            if dst.name in esperado and file_sha256(nuevo / dst.name) != esperado[dst.name]:
                raise InstallError(
                    f"La copia de {dst.name} en {raiz} no es igual que el original. "
                    f"¿Falla la unidad? No se ha tocado el VeraCrypt que llevaba.")
        if sello is not None:
            (nuevo / SELLO).write_text(sello, encoding="utf-8", newline="\n")
    except (OSError, InstallError) as e:
        shutil.rmtree(nuevo, ignore_errors=True)
        if isinstance(e, InstallError):
            raise
        raise InstallError(f"No he podido copiar VeraCrypt a {raiz}: {e}\n"
                           f"El que llevaba sigue como estaba.") from e

    apartado = False
    if carpeta.exists():
        try:
            os.replace(carpeta, viejo)
            apartado = True
        except OSError as e:
            shutil.rmtree(nuevo, ignore_errors=True)
            raise InstallError(
                f"No he podido apartar {carpeta}: {e}\n\n¿Está VeraCrypt abierto "
                f"desde la unidad, o su driver cargado desde ahí? El que llevaba "
                f"sigue en su sitio.") from e
    try:
        os.replace(nuevo, carpeta)
    except OSError as e:
        if apartado:
            try:
                os.replace(viejo, carpeta)
            except OSError as otro:
                raise InstallError(
                    f"No he podido colocar VeraCrypt en {carpeta} ({e}) ni devolver "
                    f"a su sitio el que había ({otro}): está en {viejo}. Vuelve a "
                    f"pasar el instalador y pulsa «Añadir plataformas…».") from otro
        shutil.rmtree(nuevo, ignore_errors=True)
        raise InstallError(f"No he podido colocar VeraCrypt en {carpeta}: {e}\n"
                           f"El que llevaba sigue en su sitio.") from e
    if apartado:
        shutil.rmtree(viejo, ignore_errors=True)    # si no se deja, la próxima vez
    return ([carpeta / dst.name for _, dst in pares]
            + ([carpeta / SELLO] if sello is not None else []))


def poner_portatil(raiz: Path, origen_vc: Path) -> Puesto:
    """Deja en la unidad el portable de esa carpeta ya comprobada, con su sello.

    Si la unidad ya lleva exactamente ese (el mismo sello y cada fichero el que
    dice) no se toca: es lo que hace idempotente «Añadir plataformas…».
    """
    carpeta = Path(raiz) / CARPETA
    try:
        sello = (Path(origen_vc) / SELLO).read_text(encoding="utf-8")
    except (OSError, ValueError) as e:
        raise InstallError(f"El VeraCrypt de {origen_vc} no tiene sello: {e}") from e
    version = components.leer_sello(sello).get(components.VERACRYPT, "")
    try:
        puesto = (carpeta / SELLO).read_text(encoding="utf-8")
    except (OSError, ValueError):
        puesto = None
    if puesto == sello and veracrypt_bin.verificada(carpeta, version):
        return Puesto(carpeta)
    return Puesto(carpeta, sustituir(raiz, plan_portatil(origen_vc, raiz), sello))


def version_puesta(raiz: Path) -> str:
    """Devuelve la versión del sello del VeraCrypt de esa raíz, o `''` sin sello."""
    try:
        texto = (Path(raiz) / CARPETA / SELLO).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return ""
    return components.leer_sello(texto).get(components.VERACRYPT, "")


def _copiar_instalacion(vc: dict | None, raiz: Path, motivo: InstallError) -> Puesto:
    """Hace la copia sin red: el VeraCrypt de este equipo, sin sello.

    Raises:
        InstallError: Si la unidad ya lleva el portable, este equipo no tiene
            VeraCrypt que copiar o no se sabe cómo nombrar su driver.
    """
    if version_puesta(raiz):
        raise InstallError(
            f"{motivo}\n\nLa unidad ya lleva el VeraCrypt Portable, con sus dos "
            f"arquitecturas: se queda como está.") from motivo
    pares = plan(vc, raiz)
    montar = {veracrypt_bin.montar(a) for a in ARQUITECTURAS}
    if not any(d.name in montar for _, d in pares):
        raise InstallError(
            f"{motivo}\n\nY este equipo no tiene un VeraCrypt instalado que copiar "
            f"en su lugar.") from motivo
    if not any(DRIVER_PORTATIL.match(d.name) for _, d in pares):
        raise InstallError(
            "No sé con qué nombre tiene que viajar el driver de VeraCrypt de este "
            "equipo: no hay un veracrypt-x64.sys ni un veracrypt-arm64.sys, y la "
            "cabecera del veracrypt.sys no dice que sea de ninguna de las dos. Sin "
            "eso, VeraCrypt portátil no puede cargarlo.")
    escritos = sustituir(raiz, pares)
    arqs = arquitecturas(Path(raiz) / CARPETA)
    return Puesto(Path(raiz) / CARPETA, escritos, portatil=False, aviso=(
        f"No he podido bajar el VeraCrypt Portable ({motivo}). He copiado el "
        f"VeraCrypt de este equipo, que solo vale en Windows "
        f"{' y '.join(a.upper() for a in arqs)} y va sin sello. Cuando haya "
        f"conexión, «Añadir plataformas…» lo cambia por el portable, con x64 y "
        f"ARM64."))


def instalar(vc: dict | None, raiz: Path, progreso: Progreso | None = None,
             allow_download: bool = True) -> Puesto:
    """Pone, o pone al día, el VeraCrypt de `<raiz>/VeraCrypt/`.

    Es el portable oficial comprobado, de la caché o bajado; sin red, la copia
    del VeraCrypt de este equipo (`vc`). Ver el docstring del módulo.

    Raises:
        InstallError: Con lo que haya pasado; lo que había no se toca si falla.
    """
    if not IS_WIN:
        raise InstallError(
            "El traveler disk es cosa de Windows: en Linux y macOS VeraCrypt "
            "necesita instalarse (driver y FUSE), y no se puede llevar en el "
            "dispositivo.")
    raiz = Path(raiz)
    try:
        origen_vc = veracrypt_bin.ensure_veracrypt(progreso, allow_download)
    except veracrypt_bin.SinRed as e:
        return _copiar_instalacion(vc, raiz, e)
    return poner_portatil(raiz, origen_vc)


def lleva(raiz: Path) -> bool:
    r"""Indica si esa raíz lleva una carpeta `VeraCrypt\` con algo con que montar.

    La de antes cuenta: es justo la que hay que poner al día.
    """
    return bool(vestibulo.traveler_ejecutables(raiz))


def lo_que_hara(raiz: Path) -> str:
    """Dice qué va a pasar con el VeraCrypt de esa raíz física al volver a llevarlo.

    Es para quien va a pulsar «Añadir plataformas…»; vacío si no lleva.
    """
    if not lleva(raiz):
        return ""
    version = version_puesta(raiz)
    if not version:
        return ("Esta unidad lleva un VeraCrypt de antes —la copia de una "
                "instalación, de una sola arquitectura y sin sello—: se cambia por "
                f"el VeraCrypt Portable oficial {pins.VERACRYPT_VERSION}, con x64 y "
                "ARM64, a la vez que la entrada que lo abre.")
    if version != pins.VERACRYPT_VERSION:
        return (f"Su VeraCrypt ({version}) se cambia por el "
                f"{pins.VERACRYPT_VERSION}, con x64 y ARM64.")
    return (f"Su VeraCrypt ya es el {pins.VERACRYPT_VERSION}, con x64 y ARM64: "
            "se queda como está.")


def llevar(vc: dict | None, raiz: Path, progreso: Progreso | None = None) -> Puesto:
    """Hace `instalar()` y después `write_autorun()`.

    Es lo que hacen el paso del cifrado, el botón del último paso y «Añadir
    plataformas…». El `autorun.inf` va después porque su icono es un ejecutable
    de los que se acaban de dejar.
    """
    puesto = instalar(vc, raiz, progreso)
    write_autorun(raiz)
    return puesto


def _orden_de_antes(clave: str, valor: str) -> bool:
    r"""Indica si es una de las órdenes que escribían las versiones anteriores.

    Son `shell\montar…`, `shell\desmontar…` y su `action=`. Apuntaban a
    `VeraCrypt\VeraCrypt.exe`, que el portable no trae, y además no servían: en
    un Windows 11 real no aparecieron ni en «Mostrar más opciones» (M2 en
    `docs/superpowers/pruebas/2026-09-24-veracrypt-unidad-g-resultados.md`).
    Windows no procesa las órdenes del `autorun.inf` de una unidad extraíble
    desde Windows 7; `label` e `icon` sí. La entrada de la unidad es el
    vestíbulo («Abrir PRDRIVE»).
    """
    if clave.startswith(("shell\\montar", "shell\\desmontar")):
        return True
    return clave == "action" and valor.startswith("Montar el volumen")


def icono(raiz: Path) -> str:
    """Devuelve el `icon=` que le toca a esa raíz.

    Es el ejecutable de montar que lleva de verdad
    (`vestibulo.traveler_ejecutables()`) o, si no hay, el del portable x64.
    """
    hallados = vestibulo.traveler_ejecutables(raiz)
    return hallados[0] if hallados else autorun.ICONO_VERACRYPT


def autorun_texto(label: str = DEVICE_LABEL,
                  icono_vc: str = autorun.ICONO_VERACRYPT) -> str:
    r"""Devuelve el `autorun.inf` por defecto de la raíz: nombre e icono.

    Solo se deja si no hay ninguno.

    En Windows moderno esto NO ejecuta nada al conectar (AutoRun está
    desactivado para extraíbles desde Windows 7), pero el Explorador sigue
    leyendo `label` e `icon`: la unidad deja de llamarse «Disco extraíble» y
    lleva su icono (M1 en las pruebas). Las órdenes `shell\…` que escribe
    VeraCrypt (`Mount.c`, `TravelerDlgProc`) no van: ver `_orden_de_antes()`.
    """
    return autorun.con("", label, icono_vc)


def write_autorun(raiz: Path, label: str = DEVICE_LABEL) -> Path | None:
    """Pone al día el `autorun.inf` a mejor esfuerzo, como `deploy.write_guide()`.

    El fichero se EDITA, no se reescribe (`common/autorun.py`): si ya hay uno,
    su nombre y todo lo que no es de prdrive se quedan (pueden venir de
    «Ajustes» → «Nombre e icono de la unidad», `ui/volumen.py`, o de otro
    programa). Cambia lo nuestro: se retiran las órdenes de antes
    (`_orden_de_antes()`) y un icono de VeraCrypt pasa a ser el ejecutable que
    la unidad lleva ahora. Sin fichero, el nombre y el icono de VeraCrypt. Que
    no se pueda escribir no rompe nada (la unidad se seguirá llamando «Disco
    extraíble»), así que no se levanta.

    Returns:
        La ruta del fichero escrito, o `None` si no queda fichero o no se pudo
        escribir.
    """
    actual = autorun.leer(raiz)
    if actual.ruta is None:
        texto = autorun_texto(label, icono(raiz))
    else:
        nuevo_icono = (icono(raiz) if autorun.es_icono_veracrypt(actual.icono)
                       else actual.icono)
        texto = autorun.con(autorun.sin(actual.texto, _orden_de_antes),
                            actual.etiqueta, nuevo_icono)
    try:
        return autorun.escribir(raiz, texto)
    except OSError:
        return None


def exe_portatil(raiz: Path, nombre: str = IMPRESCINDIBLE) -> Path:
    """Devuelve la ruta de uno de los ficheros que viajan en el dispositivo."""
    return Path(raiz) / CARPETA / nombre


def instalado(raiz: Path) -> bool:
    """Indica si este volumen lleva un VeraCrypt utilizable.

    Exige un ejecutable de montar y un driver que VeraCrypt portátil cargue
    (`arquitecturas()`), no uno cualquiera: el `veracrypt.sys` que dejaban
    versiones anteriores está, pero no sirve.
    """
    try:
        return lleva(raiz) and bool(arquitecturas(Path(raiz) / CARPETA))
    except OSError:
        return False


def comprobar(raiz: Path) -> list[Check]:
    """Devuelve qué VeraCrypt lleva el dispositivo, para la verificación final.

    Dice la arquitectura y de dónde salió, no solo que esté: cada arquitectura
    vale SOLO en la suya (ver el docstring del módulo), y eso hay que leerlo
    aquí y no descubrirlo con el dispositivo en la mano.
    """
    raiz = Path(raiz)
    carpeta = raiz / CARPETA
    checks: list[Check] = []

    try:
        hay_exe = lleva(raiz)
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

    version = version_puesta(raiz)
    if version:
        checks.append(Check("Versión de VeraCrypt", True,
                            f"{version}, el VeraCrypt Portable oficial comprobado"))
    else:
        checks.append(Check("Versión de VeraCrypt", False,
                            "sin sello: es la copia de un VeraCrypt instalado, de "
                            "una sola arquitectura; «Añadir plataformas…» lo "
                            "cambia por el portable, con x64 y ARM64"))

    hay_expander = any(exe_portatil(raiz, n).is_file() for n in (
        *(veracrypt_bin.expander(a) for a in ARQUITECTURAS), "VeraCryptExpander.exe"))
    checks.append(Check("VeraCrypt Expander", hay_expander,
                        "sirve para agrandar el contenedor más adelante"
                        if hay_expander else
                        "no está: el contenedor no se podrá agrandar desde aquí"))
    return checks
