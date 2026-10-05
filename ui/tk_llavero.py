#!/usr/bin/env python3
"""«Abrir llavero» con diálogos de Tk, desde la ventana de prdrive o suelto.

Solo dibuja: los pasos y lo que dicen son de `ui/llavero_editor.abrir()`, y lo
que se hace, de `common/keepassxc.py`. Aquí están los tres diálogos que le
hacen falta: un aviso, la espera (`tk.working()`) y la pregunta por el fichero
llave, que solo pide la ruta: el fichero ni se abre. Suelto es
`runsync.py --llavero` (`Llavero.bat`), colgado de una raíz que no se enseña.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

from common.model import Config

from . import llavero_editor
from .tk import working


def avisar(parent, texto: str) -> None:
    """Enseña un aviso con «Aceptar». Es de módulo para que los tests lo sustituyan."""
    from tkinter import messagebox
    messagebox.showwarning(llavero_editor.TITULO, texto, parent=parent)


def elegir_llave(parent, nombre: str) -> Path | None:
    """Pregunta dónde está el fichero llave en este equipo; `None` si no se elige ninguno.

    Es de módulo para que los tests lo sustituyan.
    """
    from tkinter import filedialog
    elegido = filedialog.askopenfilename(parent=parent,
                                         title=llavero_editor.pregunta_llave(nombre))
    return Path(elegido) if elegido else None


def abrir(parent, config: Config, suelto: bool = False) -> bool:
    """Hace «Abrir llavero» con diálogos que cuelgan de `parent`.

    Args:
        parent: La ventana de prdrive, o la raíz oculta de `abrir_suelto()`.
        config: El del dispositivo.
        suelto: Sin la ventana de prdrive: una pasada que falla se dice con un
            aviso, porque no hay línea del llavero que lo diga.

    Returns:
        True si KeePassXC se ha abierto.
    """
    def esperar(mensaje: str, funcion):
        """Corre `funcion()` con la ventanita de espera."""
        return working(parent, llavero_editor.TITULO, funcion, mensaje, suelto=suelto)

    return llavero_editor.abrir(config, partial(avisar, parent), esperar,
                                partial(elegir_llave, parent), decir_sin_traer=suelto)
