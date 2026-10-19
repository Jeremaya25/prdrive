#!/usr/bin/env python3
"""El registro de Windows de la persona (`HKEY_CURRENT_USER`), lo poco que toca prdrive.

Lo usan el llavero, para las claves del navegador de KeePassXC
(`common/keepassxc.py`), el nombre y el icono de la letra de un volumen
VeraCrypt (`common/explorador.py`), y el agente para arrancar al iniciar sesión
y estar en «Aplicaciones instaladas» (`common/presencia.py`). Solo `HKEY_CURRENT_USER`: nada de esto pide
un administrador. Las claves se dan sin la colmena y con `\\`
(`Software\\Mozilla\\NativeMessagingHosts\\…`). El valor que se lee y se
escribe es, si no se nombra otro, el predeterminado de la clave: el «Default»
de QSettings con el que lo escribe KeePassXC, y el que leen el navegador y el
Explorador.

Las funciones son de módulo para que los tests las sustituyan: aquí no se
decide nada. Fuera de Windows no hay registro: leer da `None`, no hay
subclaves y escribir o borrar lanza `OSError`.
"""

from __future__ import annotations

import os


def _winreg():
    """Devuelve el módulo `winreg`, o lanza `OSError` fuera de Windows."""
    if os.name != "nt":
        raise OSError("fuera de Windows no hay registro")
    import winreg
    return winreg


def leer(clave: str, nombre: str = "") -> str | None:
    """Devuelve un valor de texto de esa clave, o `None` si no hay (o no es texto).

    Args:
        clave: La clave, sin la colmena.
        nombre: El nombre del valor; vacío, el predeterminado.
    """
    try:
        winreg = _winreg()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, clave) as k:
            valor, tipo = winreg.QueryValueEx(k, nombre)
    except OSError:
        return None
    if tipo not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) or not isinstance(valor, str):
        return None
    return valor


def escribir(clave: str, valor: str, nombre: str = "") -> None:
    """Pone un valor de texto en esa clave, creándola si falta.

    Args:
        clave: La clave, sin la colmena.
        valor: Lo que se escribe.
        nombre: El nombre del valor; vacío, el predeterminado.

    Raises:
        OSError: Si no se ha podido.
    """
    winreg = _winreg()
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, clave, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, nombre, 0, winreg.REG_SZ, valor)


def escribir_numero(clave: str, numero: int, nombre: str) -> None:
    """Pone un valor numérico (`REG_DWORD`) en esa clave, creándola si falta.

    Args:
        clave: La clave, sin la colmena.
        numero: Lo que se escribe, de 0 a 2³²−1.
        nombre: El nombre del valor.

    Raises:
        OSError: Si no se ha podido.
    """
    winreg = _winreg()
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, clave, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, nombre, 0, winreg.REG_DWORD, int(numero))


def borrar_valor(clave: str, nombre: str) -> bool:
    """Borra un valor de esa clave, sea del tipo que sea; la clave se queda.

    Returns:
        False si no estaba (ni la clave ni el valor).

    Raises:
        OSError: Si está y no se ha podido.
    """
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, clave, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, nombre)
    except FileNotFoundError:
        return False
    return True


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


def subclaves(clave: str) -> list[str]:
    """Devuelve los nombres de las subclaves de esa clave; ninguna si no está."""
    nombres: list[str] = []
    try:
        winreg = _winreg()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, clave) as k:
            while True:
                try:
                    nombres.append(winreg.EnumKey(k, len(nombres)))
                except OSError:
                    break
    except OSError:
        return []
    return nombres
