"""¿Está cifrado el dispositivo? Lo que hace falta para un llavero sin contraseña.

Un llavero solo con fichero llave (`[keychain] llave_interna`) deja el cifrado
del dispositivo como la única otra barrera: sin él, quien tenga la unidad tiene
la llave junto a la base. Por eso la pregunta se hace **en ejecución** y con un
solo criterio, para la ventana, el asistente y cada pasada:

- **Una unidad**: vive dentro de un contenedor VeraCrypt (hay una raíz física
  con su marca y su `PRDRIVE.hc`, `vestibulo.raiz_fisica()`), o su volumen está
  cifrado y protegido con BitLocker (Windows).
- **La raíz de este equipo**: está en un contenedor VeraCrypt de `agente.json`
  (`Unidad.cifrada`), o su volumen lleva BitLocker.

Se falla hacia el lado seguro: lo que no se puede comprobar es «no cifrado».
Sin Tk y sin red; `estado()`, `bitlocker_de()` son de módulo para que los
tests las sustituyan.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import NamedTuple

from . import bitlocker, equipo, fleet, model, vestibulo

VERACRYPT = "veracrypt"
BITLOCKER = "bitlocker"


class Cifrado(NamedTuple):
    """Lo que se sabe del cifrado de este dispositivo.

    Args:
        cifrada: Si se ha comprobado que está cifrado.
        como: `VERACRYPT` o `BITLOCKER` si lo está; vacío si no.
        motivo: Por qué no (para decírselo a la persona); vacío si lo está.
    """
    cifrada: bool
    como: str = ""
    motivo: str = ""


def bitlocker_de(raiz: Path) -> bitlocker.BitLockerStatus:
    """Devuelve el estado de BitLocker del volumen de esa raíz.

    Es de módulo para que los tests la sustituyan. Fuera de Windows, o sin letra
    de unidad, no se sabe (`known=False`).
    """
    letra = raiz.drive.rstrip(":") if os.name == "nt" else ""
    if not letra:
        return bitlocker.BitLockerStatus(False, detail="BitLocker es solo de Windows.")
    return bitlocker.bitlocker_status(letra)


def _misma_carpeta(a: Path, b: Path) -> bool:
    """Indica si dos rutas son la misma carpeta, sin lanzar."""
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return a == b


def estado(app_dir: Path | str | None = None) -> Cifrado:
    """Devuelve si el dispositivo de esa carpeta de programa está cifrado.

    Args:
        app_dir: La carpeta del programa (`.prdrive/`); por defecto, la que corre.

    Returns:
        `Cifrado(True, como)`, o `Cifrado(False, "", motivo)` si no lo está o
        no se ha podido comprobar. No lanza.
    """
    app = Path(app_dir or model.APP_DIR)
    raiz = app.parent
    try:
        ident = fleet.device_id(app)
        if model.es_equipo(app):
            unidad = equipo.leer_ajustes().unidades.get(ident)
            if unidad is not None and unidad.cifrada:
                return Cifrado(True, VERACRYPT)
            donde = ("La raíz de este equipo no está en un contenedor VeraCrypt de "
                     "prdrive")
        else:
            fisica = vestibulo.raiz_fisica(ident)
            if fisica is not None and not _misma_carpeta(fisica, raiz):
                return Cifrado(True, VERACRYPT)
            donde = "Esta unidad no está dentro de un contenedor VeraCrypt de prdrive"
        bl = bitlocker_de(raiz)
    except Exception as e:                          # noqa: BLE001 — fallar cerrado
        return Cifrado(False, "", f"No se ha podido comprobar el cifrado ({e}).")
    if bl.known and bl.protected:
        return Cifrado(True, BITLOCKER)
    if os.name == "nt":
        extra = (f"; y BitLocker: {bl.resumen}" if bl.known or bl.detail
                 else "")
        return Cifrado(False, "", f"{donde}{extra}.")
    return Cifrado(False, "", f"{donde}.")
