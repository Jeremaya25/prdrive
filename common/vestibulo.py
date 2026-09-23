#!/usr/bin/env python3
"""
vestibulo.py — Lo que queda FUERA del contenedor de VeraCrypt. Sin Tkinter.

Con VeraCrypt, todo prdrive vive dentro de `PRDRIVE.hc`: el programa, los
lanzadores, la guía, el fichero de control. Hasta abrir el contenedor, un equipo
solo ve un fichero opaco. El vestíbulo es lo mínimo que se deja a la vista, en la
raíz FÍSICA del volumen, para abrirlo y cerrarlo en cualquier equipo:

    PRDRIVE.hc               el contenedor
    VeraCrypt/               el traveler (install/traveler.py), si se pidió
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
