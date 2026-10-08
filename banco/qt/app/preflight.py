"""Comprueba, SIN abortar el proceso, que Qt puede arrancar en este equipo.

Es del banco de la interfaz (temporal, ver `banco/LEEME.md`): port del prototipo Qt.

Dos fallos reales observados en una Ubuntu 24.04 minima (antes de instalar los paquetes):
  * falta libEGL.so.1 -> `import PySide6.QtGui` lanza ImportError (se puede capturar).
  * faltan libxcb-cursor0 & co -> QApplication() hace `qFatal` -> SIGABRT (exit 134), NO capturable.
Por eso, antes de crear la QApplication se hace `dlopen` del plugin de plataforma con ctypes: Qt va a cargar ese
mismo fichero un instante despues, asi que no cuesta nada, y un fallo es un OSError que nombra la biblioteca que falta.
"""
from __future__ import annotations

import ctypes
import os
import sys


def carpeta_plugins(base: str) -> str:
    """Dónde están los plugins de Qt dentro de `PySide6/` (`base`): `plugins/` en Windows, `Qt/plugins/` en Linux."""
    return os.path.join(base, "plugins") if sys.platform == "win32" else os.path.join(base, "Qt", "plugins")


def plugin_plataforma(base: str, nombre: str | None = None) -> str:
    if sys.platform == "win32":
        return os.path.join(carpeta_plugins(base), "platforms", "qwindows.dll")
    nombre = nombre or ("libqwayland.so" if os.environ.get("QT_QPA_PLATFORM") == "wayland" else "libqxcb.so")
    return os.path.join(carpeta_plugins(base), "platforms", nombre)


def comprobar(base: str, nombre: str | None = None) -> tuple[bool, str]:
    """Devuelve (True, "") o (False, «libxcb-cursor.so.0: cannot open shared object file…»)."""
    try:
        ctypes.CDLL(plugin_plataforma(base, nombre))
        return True, ""
    except OSError as e:
        return False, str(e)
