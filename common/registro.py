#!/usr/bin/env python3
"""El registro de Windows de la persona (`HKEY_CURRENT_USER`), lo poco que toca prdrive.

Lo usa el llavero para las claves del navegador de KeePassXC
(`common/keepassxc.py`). Solo `HKEY_CURRENT_USER`: nada de esto pide un
administrador. Las claves se dan sin la colmena y con `\\`
(`Software\\Mozilla\\NativeMessagingHosts\\…`), y el valor que se lee y se
escribe es el predeterminado de la clave: el «Default» de QSettings con el que
lo escribe KeePassXC, y el que lee el navegador.

Las cuatro funciones son de módulo para que los tests las sustituyan: aquí no
se decide nada. Fuera de Windows no hay registro: leer da `None` y escribir o
borrar lanza `OSError`.
"""

from __future__ import annotations

import os


def _winreg():
    """Devuelve el módulo `winreg`, o lanza `OSError` fuera de Windows."""
    if os.name != "nt":
        raise OSError("fuera de Windows no hay registro")
    import winreg
    return winreg


def leer(clave: str) -> str | None:
    """Devuelve el valor predeterminado de esa clave, o `None` si no hay (o no es texto)."""
    try:
        winreg = _winreg()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, clave) as k:
            valor, tipo = winreg.QueryValueEx(k, "")
    except OSError:
        return None
    if tipo not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) or not isinstance(valor, str):
        return None
    return valor


def escribir(clave: str, valor: str) -> None:
    """Pone el valor predeterminado de esa clave, creándola si falta.

    Raises:
        OSError: Si no se ha podido.
    """
    winreg = _winreg()
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, clave, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, valor)


def borrar(clave: str) -> bool:
    """Borra esa clave, que no puede tener subclaves.

    Returns:
        False si no estaba.

    Raises:
        OSError: Si está y no se ha podido (por ejemplo, porque tiene subclaves).
    """
    winreg = _winreg()
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, clave)
    except FileNotFoundError:
        return False
    return True


def vacia(clave: str) -> bool | None:
    """Indica si esa clave no tiene ni subclaves ni valores, o `None` si no está."""
    try:
        winreg = _winreg()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, clave) as k:
            subclaves, valores, _ = winreg.QueryInfoKey(k)
    except OSError:
        return None
    return subclaves == 0 and valores == 0
