#!/usr/bin/env python3
"""
vestibulo.py — Lo que queda FUERA del contenedor de VeraCrypt. Sin Tkinter.

Con VeraCrypt, todo prdrive vive dentro de `PRDRIVE.hc`: el programa, los
lanzadores, la guía, el fichero de control. Hasta abrir el contenedor, un equipo
solo ve un fichero opaco. El vestíbulo es lo mínimo que se deja a la vista, en la
raíz FÍSICA del volumen, para abrirlo y cerrarlo en cualquier equipo:

    PRDRIVE.hc               el contenedor
    VeraCrypt/               el traveler (install/traveler.py), si se pidió:
                             el VeraCrypt Portable oficial, x64 y ARM64
    Abrir PRDRIVE.bat        Windows: abre el contenedor y lanza prdrive
    Expulsar PRDRIVE.bat     Windows: lo cierra
    abrir-prdrive.sh         Linux: lo mismo
    expulsar-prdrive.sh
    LEEME-PRDRIVE.txt        qué es esto y cómo se abre
    .prdrive-vestibulo       la marca: el id del dispositivo

La marca lleva el MISMO id que `.prdrive/PRDRIVE` dentro del contenedor. Es lo
que une las dos mitades: desde fuera se reconoce el dispositivo cerrado, y desde
dentro se encuentra su raíz física.

Vive en `common/` y no en `install/` porque el dispositivo la usa: `install/` no
viaja a él. Quien ESCRIBE el vestíbulo es `install/vestibulo.py`; aquí están los
nombres y la lectura. `penwatch.py` repite los nombres (no importa nada del
proyecto) y un test comprueba que no se separan.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from . import APP_NAME

ETIQUETA = APP_NAME.upper()                       # PRDRIVE
CONTENEDOR = f"{ETIQUETA}.hc"
MARCA = f".{APP_NAME}-vestibulo"
ABRIR_BAT = f"Abrir {ETIQUETA}.bat"
EXPULSAR_BAT = f"Expulsar {ETIQUETA}.bat"
ABRIR_SH = f"abrir-{APP_NAME}.sh"
EXPULSAR_SH = f"expulsar-{APP_NAME}.sh"
LEEME = f"LEEME-{ETIQUETA}.txt"

# Lo que escribe el instalador en la raíz física, para `install/device.RUIDO`:
# si se olvida alguno, un dispositivo recién hecho se lee como ajeno la vez
# siguiente.
TODOS = (MARCA, ABRIR_BAT, EXPULSAR_BAT, ABRIR_SH, EXPULSAR_SH, LEEME)

# El VeraCrypt que viaja en la raíz física, si se pidió. Lo copia
# `install/traveler.py`; los nombres están aquí porque el dispositivo también
# los necesita: su ejecutable es el icono que el traveler le pone a la unidad, y
# la ventana del nombre y el icono (`ui/volumen.py`) lo ofrece si está.
TRAVELER = "VeraCrypt"
TRAVELER_EXE = "VeraCrypt.exe"

# Lo que viaja ahora es el paquete «VeraCrypt Portable» oficial, con sus nombres:
# un ejecutable por arquitectura, con ella en el nombre, y los dos drivers al
# lado (`szCompressedFiles` en `Setup/Setup.h` para PORTABLE, tag
# VeraCrypt_1.26.24; el propio diálogo del traveler de VeraCrypt los copia así,
# `Mount/Mount.c`, `TravelerDlgProc`). No lleva ningún `VeraCrypt.exe`: ese
# `TRAVELER_EXE` es la disposición de una INSTALACIÓN, la que dejaban las
# versiones anteriores de prdrive, y quien abre el contenedor la sigue aceptando
# detrás de la del portable. `penwatch.py` repite estos nombres —no importa nada
# del proyecto— con un test que no los deja separarse.
TRAVELER_ARQUITECTURAS = ("x64", "arm64")
TRAVELER_PORTATIL = "VeraCrypt-{arq}.exe"


def traveler_portatil(arq: str) -> str:
    """El ejecutable de montar del portable para esa arquitectura."""
    return TRAVELER_PORTATIL.format(arq=arq)


def traveler_ejecutables(raiz: Path | str) -> list[str]:
    """Los ejecutables de montar que lleva la carpeta `VeraCrypt\\` de esa raíz,
    relativos a ella y con la barra de Windows (`VeraCrypt\\VeraCrypt-x64.exe`).

    Primero los del portable, x64 delante, y detrás el de una instalación. Es el
    orden en que se escogen como icono: el de un ejecutable se lee sin ejecutarlo,
    así que el x64 le vale al Explorador de un Windows ARM igual que al de uno
    x64. Lista vacía si no hay ninguno o no se puede mirar."""
    carpeta = Path(raiz) / TRAVELER
    nombres = [*(traveler_portatil(a) for a in TRAVELER_ARQUITECTURAS), TRAVELER_EXE]
    hallados = []
    for nombre in nombres:
        try:
            if (carpeta / nombre).is_file():
                hallados.append(f"{TRAVELER}\\{nombre}")
        except OSError:
            continue
    return hallados


def es_resto_traveler(nombre: str) -> bool:
    """¿Es lo que deja a medias un intercambio de la carpeta `VeraCrypt\\`?

    `install/traveler.py` la sustituye copiando al lado (`.VeraCrypt.nuevo-<pid>`)
    y apartando la de antes (`.VeraCrypt.viejo-<pid>`); si algo no se pudo borrar
    se queda para la próxima vez. No es contenido de nadie: `device.es_ruido()`."""
    bajo = nombre.lower()
    prefijo = f".{TRAVELER.lower()}."
    return bajo.startswith(prefijo) and bajo[len(prefijo):].startswith(
        ("nuevo-", "viejo-"))


def leer_id(raiz: Path | str) -> str | None:
    """El `id=` de la marca de esa raíz, o None si no hay marca o no se lee.

    No lanza: un volumen bloqueado o retirado a media lectura responde con
    error, y aquí eso significa «no es un vestíbulo que se pueda leer»."""
    try:
        texto = (Path(raiz) / MARCA).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for linea in texto.splitlines():
        linea = linea.strip()
        if linea.lower().startswith("id="):
            return linea[3:].strip() or None
    return None


# ---------------------------------------------------------------------------
# Desde dentro: dónde está la raíz física de este dispositivo
# ---------------------------------------------------------------------------

def raiz_fisica(device_id: str) -> Path | None:
    """La raíz física del contenedor en el que vive este dispositivo, o None.

    La que tiene una marca con este id y el contenedor al lado. Las unidades se
    recorren con `penwatch.candidate_roots()`, importado aquí dentro como hace
    `ui/watch.py`: así hay UN recorrido de unidades en todo el proyecto, el que
    ya sabe no sacar el diálogo de «no hay disco» con un lector de tarjetas
    vacío. Cualquier fallo es None: esto adorna una ventana, no la sostiene.

    Función de módulo para que los tests la sustituyan."""
    if not device_id:
        return None
    try:
        import penwatch
        raices = penwatch.candidate_roots({})
    except Exception:                                # noqa: BLE001
        return None
    for raiz in raices:
        try:
            if leer_id(raiz) == device_id and (raiz / CONTENEDOR).is_file():
                return raiz
        except OSError:
            continue
    return None


FILE_ATTRIBUTE_SPARSE_FILE = 0x200      # winnt.h
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF


def disperso(contenedor: Path | str) -> bool:
    """¿Es un fichero disperso? Es lo que hace un contenedor «dinámico».

    Uno disperso ocupa lo que se ha escrito y crece al escribir, así que el sitio
    que le queda fuera es el que le queda dentro. En Windows se pregunta por el
    atributo; en POSIX, si ocupa en disco menos de lo que mide. False si no se
    puede saber: un aviso que no se sabe dar no se da."""
    ruta = str(contenedor)
    if os.name == "nt":
        try:
            import ctypes
            # Sin `restype`, ctypes lo devuelve como int CON signo y el
            # INVALID_FILE_ATTRIBUTES de un fichero que no está llega como -1,
            # que tiene todos los bits puestos, el de disperso también.
            attrs = ctypes.windll.kernel32.GetFileAttributesW(ruta) & 0xFFFFFFFF
        except (OSError, AttributeError):
            return False
        return (attrs != INVALID_FILE_ATTRIBUTES
                and bool(attrs & FILE_ATTRIBUTE_SPARSE_FILE))
    try:
        st = os.stat(ruta)
    except OSError:
        return False
    return getattr(st, "st_blocks", st.st_size // 512 + 1) * 512 < st.st_size


# Por debajo de esto, un contenedor disperso está a una tanda de fotos de dar
# errores de escritura por dentro.
UMBRAL_LIBRE = 1024 ** 3


def sin_sitio_fuera(device_id: str) -> tuple[Path, int] | None:
    """(raíz física, bytes libres) si el contenedor es disperso y fuera queda
    menos de `UMBRAL_LIBRE`; None si no hay nada que avisar."""
    fisica = raiz_fisica(device_id)
    if fisica is None or not disperso(fisica / CONTENEDOR):
        return None
    try:
        libre = shutil.disk_usage(str(fisica)).free
    except OSError:
        return None
    return (fisica, libre) if libre < UMBRAL_LIBRE else None
