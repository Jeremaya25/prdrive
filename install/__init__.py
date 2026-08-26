#!/usr/bin/env python3
"""
install — Lo que sabe el instalador de un pen PEREPEN nuevo.

Aquí no se dibuja nada. El asistente vive en `ui/tk_install.py` y esta es la
misma división que ya rige en el proyecto entre `ui/pair_editor.py` (decide y
toca el disco) y `ui/tk_pairs.py` (solo pinta): así todo lo delicado —formatear
órdenes de rclone, elegir dónde se siembra, hablar con VeraCrypt— se puede
probar sin pantalla y sin pen.

    rclone_bin  conseguir un binario de rclone con el que arrancar
    remote      la clave embebida, el rclone.conf efímero y el catálogo del NAS
    device      qué volúmenes hay, cuál es el pen, y si quedó bien montado
    crypto      VeraCrypt y BitLocker
    seed        la siembra, el sync_config.toml del dispositivo y el --resync

A diferencia del resto del proyecto, esto NO corre desde el pen: corre antes de
que el pen exista, y su forma final es un ejecutable de PyInstaller. De ahí las
dos rarezas de este módulo: `python_command()`, porque congelados
`sys.executable` es el instalador y no Python; y `bundle_dir()`, porque los
ficheros que acompañan al script están en otro sitio cuando van dentro del .exe.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

__version__ = "2.0"

# --- El NAS. No es secreto: son rutas y un usuario SFTP dedicado. -------------
NAS_HOST = "tictactoe.synology.me"
NAS_PORT = 22
NAS_USER = "Pereftp"
REMOTE_NAME = "synology"

MASTER_PATH = "/PJ/Perepen"                       # espejo maestro del pen
CATALOG_PATH = "/PJ/Perepen-catalog/pairs.toml"   # catálogo global de parejas
BITLOCKER_PATH = "/PJ/Perepen/_bitlockers"        # claves de recuperación

PEN_LABEL = "PEREPEN"
CONTAINER_NAME = "PEREPEN.hc"      # contenedor VeraCrypt en la raíz del pen físico
RCLONE_BASE_URL = "https://downloads.rclone.org"

IS_WIN = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000


class InstallError(Exception):
    """Algo ha impedido seguir, pero el instalador sigue vivo.

    Se lanza en vez de hacer sys.exit por la misma razón que `model.ConfigError`:
    con un asistente abierto, salir del proceso es cerrarle la ventana al usuario
    en las narices en vez de enseñarle qué ha pasado y dejarle reintentar."""


# ---------------------------------------------------------------------------
# Dónde estamos y con qué Python contamos
# ---------------------------------------------------------------------------

def is_frozen() -> bool:
    """¿Nos está ejecutando PyInstaller y no el intérprete?"""
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """La carpeta desde la que leer lo que acompaña al instalador.

    Congelados es el directorio temporal donde PyInstaller extrae el paquete;
    ejecutando el .py es `rclone-sync/`, el padre de este paquete."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def python_command(windowless: bool = False) -> list[str] | None:
    """Un Python DE VERDAD con el que lanzar el sync.py ya sembrado en el pen.

    Congelados, `sys.executable` es el propio instalador: usarlo relanzaría el
    asistente en vez de sincronizar. Por eso solo vale cuando NO estamos
    congelados, y si lo estamos hay que salir a buscar un intérprete instalado.
    Devuelve None si en este equipo no hay ninguno, que es información útil: el
    pen resultante tampoco funcionaría."""
    if not is_frozen():
        return [_windowless(sys.executable) if windowless else sys.executable]

    nombres = ("pythonw", "python") if (windowless and IS_WIN) else ("python", "python3")
    for nombre in nombres:
        found = shutil.which(nombre)
        if found:
            return [found]
    # El lanzador 'py' de Windows sabe encontrar la instalación aunque no esté
    # en el PATH; necesita el -3 para no acabar en un Python 2 fosilizado.
    launcher = shutil.which("pyw" if windowless else "py")
    if launcher:
        return [launcher, "-3"]
    return None


def _windowless(exe: str) -> str:
    """pythonw junto a python: sin él, cada lanzamiento abre una consola."""
    if IS_WIN:
        w = Path(exe).with_name("pythonw.exe")
        if w.exists():
            return str(w)
    return exe


# ---------------------------------------------------------------------------
# Lo que el asistente va acumulando
# ---------------------------------------------------------------------------

@dataclass
class InstallState:
    """Lo que se sabe hasta ahora. Un paso lee lo que dejaron los anteriores.

    `device` es la raíz del pen FÍSICO y `pen_root` dónde va a vivir la
    estructura: sin cifrar o con BitLocker son la misma carpeta, pero con un
    contenedor VeraCrypt `pen_root` es la unidad montada y `device` sigue siendo
    el pen, que es donde está el .hc."""
    device: Path | None = None
    pen_root: Path | None = None

    encryption: str = "none"                    # none | veracrypt | bitlocker
    container: Path | None = None
    veracrypt: dict | None = None               # {'mount': ..., 'format': ...}
    mounted_by_us: bool = False

    selected: list[str] = field(default_factory=list)
    seed_simulated: bool = False
    seeded: bool = False
    config_written: bool = False
    initialized: bool = False
