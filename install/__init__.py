#!/usr/bin/env python3
"""Lo que sabe el instalador de un dispositivo prdrive nuevo.

Aquí no se dibuja nada: el asistente vive en `ui/tk_install.py`. Es la misma
división que rige entre `ui/pair_editor.py` (decide y toca el disco) y
`ui/tk_pairs.py` (solo pinta), y permite probar sin pantalla y sin dispositivo
todo lo delicado: formatear órdenes de rclone, elegir dónde se instala, hablar
con VeraCrypt.
- `profile`: la conexión con el remoto, de dónde sale y cómo se escribe.
- `rclone_bin`: conseguir rclone, el de este equipo o el de otra plataforma.
- `runtime_bin`: conseguir el Python que viaja en el dispositivo y extraerlo.
- `descarga`: lo que comparten los dos: reintentar la red y leer un SHA256SUMS.
- `platforms`: para qué equipos va a funcionar; la lista del paso 5.
- `components`: poner al día el rclone y el Python que ya lleva un dispositivo.
- `remote`: el `rclone.conf` efímero y el catálogo de parejas.
- `device`: qué volúmenes hay, cuál es el dispositivo y si quedó bien montado.
- `crypto`: VeraCrypt y BitLocker.
- `deploy`: instalar el código, el config del dispositivo y el `--resync`.

No hay constantes del servidor: dónde está el remoto, cómo se llama y con qué
clave se entra vive en `profile.Profile`, que se teclea en el asistente, se
importa de un `rclone.conf` o llega incrustado en el `.exe`.

El código del dispositivo lo copia el instalador desde lo que lleva dentro
(`deploy.deploy_code`): el remoto guarda configuración, no programas.

A diferencia del resto del proyecto, esto NO corre desde el dispositivo sino
antes de que exista, y su forma final es un ejecutable de PyInstaller. De ahí
dos rarezas: `python_command()`, porque congelados `sys.executable` es el
instalador y no Python, y `bundle_dir()`, porque los ficheros que acompañan al
script están en otro sitio cuando van dentro del `.exe`.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from common import APP_NAME

DEVICE_LABEL = APP_NAME.upper()
"""Marca del producto en mayúsculas.

Es un identificador y no un adorno: da nombre al fichero de control del
volumen, al contenedor VeraCrypt y a la carpeta de código. Sale de `common`
para que no haya dos copias que puedan separarse.
"""
CONTAINER_NAME = f"{DEVICE_LABEL}.hc"   # contenedor VeraCrypt en la raíz del volumen
"""Nombre del contenedor VeraCrypt en la raíz del volumen."""
RCLONE_BASE_URL = "https://downloads.rclone.org"
"""URL base de las descargas de rclone."""

IS_WIN = os.name == "nt"
"""Si se ejecuta en Windows."""
CREATE_NO_WINDOW = 0x08000000
"""Flag de creación de procesos de Windows: no abrir consola."""


class InstallError(Exception):
    """Algo ha impedido seguir, pero el instalador sigue vivo.

    Se lanza en vez de llamar a `sys.exit` por lo mismo que
    `model.ConfigError`: con un asistente abierto, salir del proceso sería
    cerrarle la ventana al usuario en vez de enseñarle qué ha pasado y dejarle
    reintentar.
    """


def is_frozen() -> bool:
    """Indica si nos ejecuta PyInstaller y no el intérprete."""
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """Devuelve la carpeta desde la que leer lo que acompaña al instalador.

    Congelados es el directorio temporal donde PyInstaller extrae el paquete;
    ejecutando el `.py` es el padre de este paquete.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def version() -> str:
    """Devuelve la versión que lleva este instalador dentro.

    Sale del fichero `VERSION`, que es el mismo que se copia al dispositivo
    (`deploy.DEPLOY_FILES`), contra el que `common/update.py` compara la última
    release y contra el que el workflow comprueba el tag al publicar. Una
    constante aquí sería una cuarta copia del número, y la que se quedaría
    atrás.
    """
    from common.update import installed_version
    return installed_version(bundle_dir())


__version__ = version()
"""Versión del instalador, leída al importar el paquete."""


pintar_iconos = None
"""Función que pinta los iconos; la pone quien lanza la instalación.

Los iconos (`runsync.ico` y los cinco de la bandeja del agente) los pinta
`ui/icons.py` e `install/` no importa `ui/` (AGENTS.md). Quien sí conoce `ui/`
(`prdrive-install.py`, para el asistente y para las órdenes sin ventana) pone
aquí con qué: `pintar_iconos(carpeta, bandeja)` deja `runsync.ico` en `carpeta`
y, con `bandeja`, los de la bandeja. Sin ella no se pinta nada: el agente
repinta los de la bandeja al arrancar si faltan y la ventana dibuja el suyo.
"""


def pintar(carpeta: Path | str, bandeja: bool = False) -> None:
    """Pinta los iconos en esa carpeta, si hay quien los pinte.

    Nunca lanza: un icono no puede tumbar una instalación que va bien.
    """
    if pintar_iconos is None:
        return
    try:
        pintar_iconos(Path(carpeta), bandeja)
    except Exception:                                   # noqa: BLE001
        pass


def python_command(windowless: bool = False) -> list[str] | None:
    """Devuelve un Python DE VERDAD instalado en este equipo.

    Congelados, `sys.executable` es el propio instalador: usarlo relanzaría el
    asistente en vez de sincronizar. Por eso solo vale cuando NO estamos
    congelados; si lo estamos hay que salir a buscar un intérprete instalado.
    Para lanzar algo DEL dispositivo se pregunta antes por el suyo:
    `deploy.device_python()`.

    Returns:
        La orden, o `None` si en este equipo no hay ningún Python.
    """
    if not is_frozen():
        return [_windowless(sys.executable) if windowless else sys.executable]

    nombres = ("pythonw", "python") if (windowless and IS_WIN) else ("python", "python3")
    for nombre in nombres:
        found = shutil.which(nombre)
        if found:
            return [found]
    # El lanzador `py` de Windows sabe encontrar la instalación aunque no esté
    # en el `PATH`; necesita `-3` para no acabar en un Python 2 fosilizado.
    launcher = shutil.which("pyw" if windowless else "py")
    if launcher:
        return [launcher, "-3"]
    return None


def _windowless(exe: str) -> str:
    """Devuelve `pythonw` junto a `python`.

    Sin él, cada lanzamiento abre una consola.
    """
    if IS_WIN:
        w = Path(exe).with_name("pythonw.exe")
        if w.exists():
            return str(w)
    return exe


@dataclass
class InstallState:
    """Lo que se sabe hasta ahora: un paso lee lo que dejaron los anteriores.

    `device` es la raíz del volumen FÍSICO y `device_root` dónde va a vivir la
    estructura: sin cifrar o con BitLocker son la misma carpeta, pero con un
    contenedor VeraCrypt `device_root` es la unidad montada y `device` sigue
    siendo el dispositivo, que es donde está el `.hc`. El código y los
    lanzadores van SIEMPRE en `device_root`, o sea dentro de lo cifrado.

    Los campos del paso de cifrado viven aquí y no en la pantalla porque
    `repintar()` destruye el panel entero: sin esto la casilla se desmarcaría
    sola y la velocidad medida se volvería a medir, escribiendo en el
    dispositivo, cada vez que se repinta.

    Args:
        device: Raíz del volumen físico.
        device_root: Dónde vive la estructura.
        encryption: `none`, `veracrypt` o `bitlocker`.
        container: El contenedor VeraCrypt.
        veracrypt: Los ejecutables de VeraCrypt, `{'mount': ..., 'format':
            ...}`.
        mounted_by_us: Si el contenedor lo montó el instalador.
        dinamico: Si el contenedor es disperso (`/dynamic`). `None` es «todavía
            no se ha decidido», y por eso no es un bool: el valor por defecto
            de la casilla depende de si la unidad admite dispersos, que no se
            sabe hasta pintar el paso.
        traveler: Si se deja VeraCrypt en el volumen.
        velocidad_escritura: Bytes por segundo medidos (ver `crypto`).
        selected: Parejas elegidas.
        deployed: Si el código ya está copiado.
        config_written: Si el config del dispositivo ya está escrito.
        initialized: Si ya se hizo el `--resync` inicial.
    """
    device: Path | None = None
    device_root: Path | None = None

    encryption: str = "none"
    container: Path | None = None
    veracrypt: dict | None = None
    mounted_by_us: bool = False

    dinamico: bool | None = None
    traveler: bool = True
    velocidad_escritura: float | None = None

    selected: list[str] = field(default_factory=list)
    deployed: bool = False
    config_written: bool = False
    initialized: bool = False
