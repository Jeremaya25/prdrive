#!/usr/bin/env python3
"""
components.py — Poner al día el rclone y el Python que lleva un dispositivo.

El otro extremo de `common/components.py`: aquel LEE los sellos y dice qué está
anticuado —desde el propio dispositivo, al instante y sin red—; esto lo ARREGLA,
y para eso hay que bajar, comprobar y sustituir, que es justo lo que el
instalador ya sabe hacer (`rclone_bin`, `runtime_bin`, `deploy`).

Y por eso vive aquí y no en `common/`: `install/` no viaja al dispositivo a
propósito, así que esto se ejecuta desde el zip del código que `common/update.py`
acaba de descargar y verificar, igual que el aplicador de la actualización del
programa. **La versión que fija los componentes es la que los instala**, y no hay
una segunda copia de la maquinaria de descarga esperando a quedarse atrás.

**El intercambio es el de `deploy.install_runtime()`, también para rclone**: se
escribe al lado, se aparta el de antes y se coloca el nuevo de un renombrado, que
es atómico en los dos sistemas. Lo que NO se hace es copiar encima del binario
que hay: `shutil.copy2` trunca y luego escribe, y un corte a mitad dejaría el
dispositivo con un rclone roto, que es el único que tiene.

**Y lo que está en uso no se toca.** Un rclone sincronizando ahora mismo y el
Python desde el que está abierto este mismo programa se POSPONEN con su motivo;
lo demás se hace igual. Posponer es una decisión, no una limitación: en Windows
el renombrado colaría —un `.exe` en marcha se puede apartar, lo que no se puede
es borrar—, pero cambiarle el binario a una sincronización a media pasada no es
algo que deba ocurrir sin que nadie lo haya pedido.

Lo que aquí no pasa nunca: instalar una plataforma que el dispositivo no lleva
(eso es «Añadir plataformas…», y es una decisión con sitio en disco de por
medio), tocar el código, los lanzadores, la configuración o las claves.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# Los nombres sueltos y no el módulo: este fichero se llama igual que aquel, y
# un `components.pendientes(...)` dentro de `install/components.py` sería una
# adivinanza sobre cuál de los dos se está leyendo.
from common import pins
from common.components import RCLONE, Pendiente
from common.components import pendientes as sellos_pendientes

from . import IS_WIN, InstallError
from . import deploy, platforms, rclone_bin, runtime_bin

Progreso = Callable[[str], None]


@dataclass
class Resultado:
    """Qué se ha hecho, qué se ha dejado para luego y qué ha salido mal.

    Pospuesto y fallido son cosas distintas y se cuentan aparte: lo primero es
    normal —había una sincronización en marcha— y lo segundo no —una suma que no
    cuadra—. Quien llama decide con `fallidos` si esto fue un error; el recuadro
    ámbar se apaga solo, porque los sellos ya dicen la verdad."""
    hechos: list[str] = field(default_factory=list)
    pospuestos: list[str] = field(default_factory=list)
    fallidos: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.fallidos


# ---------------------------------------------------------------------------
# ¿Está en uso?
# ---------------------------------------------------------------------------
# Las dos son funciones de módulo a propósito, como `conflict_editor.mover()` o
# `runsync.notificar_fallo()`: los tests las sustituyen enteras, y así ninguno
# depende de tener un rclone corriendo ni de qué Python ejecuta la batería.

def rclone_en_uso(ruta: Path) -> bool:
    """¿Se está ejecutando ese rclone, o no se puede escribir donde está?

    Se pregunta abriendo el fichero para escritura, que contesta en los dos
    sistemas sin enumerar procesos: en Windows, un `.exe` cuya imagen está
    mapeada da ERROR_SHARING_VIOLATION; en Linux, `open(O_RDWR)` sobre un
    binario en ejecución da ETXTBSY. Un volumen de solo lectura también falla, y
    aquí significa lo mismo: ahora no.

    Que no exista no es «en uso»: no hay nada que sustituir y el intercambio se
    encargará de crearlo."""
    try:
        if not ruta.is_file():
            return False
        with open(ruta, "r+b"):
            return False
    except OSError:
        return True


def runtime_en_uso(carpeta: Path) -> bool:
    """¿Corre ESTE proceso desde ese runtime?

    Es el caso normal y no una rareza: en un dispositivo con Python propio, la
    ventana que ofrece la actualización arrancó desde `runtime/<clave>/`, y este
    proceso es hijo suyo y usa el mismo intérprete (`update.components_command()`
    pasa `sys.executable` a propósito). En Windows no se puede renombrar la
    carpeta de un `pythonw.exe` vivo, así que sin esto se bajarían 30 MB para
    fallar al final."""
    try:
        Path(sys.executable).resolve().relative_to(Path(carpeta).resolve())
        return True
    except (ValueError, OSError):
        return False


# ---------------------------------------------------------------------------
# El intercambio
# ---------------------------------------------------------------------------

def _limpiar_restos(carpeta: Path) -> None:
    """Barre lo que dejó un intercambio anterior. Silencioso y best-effort.

    Un `.rclone.exe.viejo-1234` solo aparece cuando no se pudo borrar el de
    antes —Windows no borra un `.exe` en marcha—, y entonces lo que procede es
    volver a intentarlo la próxima vez, no dar un error por algo que ya está
    resuelto."""
    try:
        for patron in (".*.viejo-*", ".*.nuevo-*"):
            for resto in carpeta.glob(patron):
                resto.unlink(missing_ok=True)
    except OSError:
        pass


def swap_rclone(destino: Path, origen: Path) -> None:
    """Sustituye el binario de `destino` por el de `origen`, sin pasar por medio.

    Tres pasos, los mismos de `deploy.install_runtime()`: se copia al lado, se
    aparta el de antes con un renombrado y se coloca el nuevo con otro. El
    renombrado es atómico en los dos sistemas, así que en ningún instante hay
    medio rclone en `bin/` — y medio rclone es un dispositivo que no sincroniza
    en ningún equipo. Si el último paso falla, el de antes vuelve a su sitio; y
    si ni eso se puede, el error dice que esa plataforma se ha quedado sin rclone
    y cómo volver a ponerlo.

    Borrar el apartado es lo único que puede fallar sin consecuencias, y se deja
    para la próxima pasada (`_limpiar_restos`)."""
    destino, origen = Path(destino), Path(origen)
    nuevo = destino.with_name(f".{destino.name}.nuevo-{os.getpid()}")
    viejo = destino.with_name(f".{destino.name}.viejo-{os.getpid()}")
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origen, nuevo)
        if not IS_WIN:
            nuevo.chmod(nuevo.stat().st_mode | 0o755)
    except OSError as e:
        nuevo.unlink(missing_ok=True)
        raise InstallError(f"No he podido dejar el rclone nuevo junto a "
                           f"{destino}: {e}\nEl que había sigue en su sitio.") from e

    apartado = False
    if destino.exists():
        try:
            os.replace(destino, viejo)
            apartado = True
        except OSError as e:
            nuevo.unlink(missing_ok=True)
            raise InstallError(f"No he podido apartar el rclone de {destino}: "
                               f"{e}\nEl que había sigue en su sitio.") from e
    try:
        os.replace(nuevo, destino)
    except OSError as e:
        # Esta es la única rama que puede dejar `bin/` SIN rclone, y por eso es
        # la única que no se puede permitir escaparse cruda: `aplicar()` solo
        # recoge InstallError, así que un OSError de aquí abortaría la pasada
        # entera y se perdería el parte de lo hecho justo cuando hay algo urgente
        # que contar. Y un dispositivo sin binario ni siquiera vuelve a salir
        # como pendiente —`rclone_pendiente()` no compara lo que no está—, o sea
        # que si no lo dice este mensaje no lo dice nadie.
        if apartado:
            try:
                os.replace(viejo, destino)
            except OSError as otro:
                nuevo.unlink(missing_ok=True)
                raise InstallError(
                    f"No he podido colocar el rclone en {destino} ({e}) y "
                    f"tampoco devolver a su sitio el que había ({otro}).\n\n"
                    f"Esta plataforma se ha quedado sin rclone. Vuelve a "
                    f"ejecutar el instalador de prdrive, elige este dispositivo "
                    f"y pulsa «Añadir plataformas…».") from otro
        nuevo.unlink(missing_ok=True)
        raise InstallError(f"No he podido colocar el rclone en {destino}: {e}\n"
                           f"El que había sigue en su sitio.") from e
    if apartado:
        try:
            viejo.unlink()
        except OSError:
            pass        # Windows con rclone en marcha: se barre la próxima vez


# ---------------------------------------------------------------------------
# El plan y su ejecución
# ---------------------------------------------------------------------------

def pendientes(device_root: Path | str) -> list[Pendiente]:
    """Lo que ese dispositivo tiene por poner al día. Sin red, como el del
    dispositivo: la diferencia es que aquí se parte de la raíz del volumen."""
    return sellos_pendientes(deploy.app_dir(device_root))


def _poner_rclone(raiz: Path, p: Pendiente, decir: Progreso) -> str | None:
    """Sustituye un rclone. Devuelve el motivo si se pospone, None si se hizo."""
    destino = platforms.rclone_path(raiz, p.plataforma)
    _limpiar_restos(destino.parent)
    if rclone_en_uso(destino):
        return ("está en uso o no se puede escribir ahora. Se queda como "
                "estaba; vuelve a intentarlo cuando no haya ninguna "
                "sincronización en marcha.")
    decir(f"{p.titulo}: consiguiendo la {p.deberia}")
    binario = rclone_bin.pinned_rclone(p.plataforma, decir)
    decir(f"{p.titulo}: sustituyendo {destino}")
    swap_rclone(destino, binario)
    deploy.write_rclone_stamp(destino, p.plataforma, pins.RCLONE_VERSION)
    return None


def _poner_python(raiz: Path, p: Pendiente, decir: Progreso) -> str | None:
    """Sustituye un runtime. Devuelve el motivo si se pospone, None si se hizo."""
    carpeta = platforms.runtime_dir(raiz, p.plataforma)
    if runtime_en_uso(carpeta):
        return ("es el Python con el que está corriendo prdrive ahora mismo, "
                "así que no se puede sustituir sin cerrarlo. Abre el programa "
                "con un Python instalado en este equipo —o desde otro equipo— y "
                "vuelve a intentarlo.")
    decir(f"{p.titulo}: consiguiendo la {p.deberia}")
    archivo = runtime_bin.ensure_runtime(p.plataforma, decir)
    decir(f"{p.titulo}: sustituyendo {carpeta}")
    deploy.install_runtime(raiz, p.plataforma, archivo)
    return None


def aplicar(device_root: Path | str, progreso: Progreso | None = None,
            pends: list[Pendiente] | None = None) -> Resultado:
    """Pone al día los componentes anticuados de ese dispositivo.

    Lo que se pueda: cada componente va por su cuenta, y uno que no se pueda
    tocar ahora no impide los demás. Nada queda a medias — lo que no se ha
    sustituido sigue exactamente como estaba, y su sello lo sigue diciendo, así
    que el aviso de la ventana se apaga solo en cuanto deja de haber motivo."""
    def decir(msg: str) -> None:
        if progreso:
            progreso(msg)

    raiz = Path(device_root)
    res = Resultado()
    if pends is None:
        pends = pendientes(raiz)

    for p in pends:
        poner = _poner_rclone if p.que == RCLONE else _poner_python
        try:
            motivo = poner(raiz, p, decir)
        except InstallError as e:
            res.fallidos.append(f"{p.titulo}: {e}")
            continue
        if motivo is not None:
            res.pospuestos.append(f"{p.titulo}: {motivo}")
        else:
            res.hechos.append(f"{p.titulo}: {p.lleva} → {p.deberia}")
    return res
