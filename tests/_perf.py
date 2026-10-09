#!/usr/bin/env python3
"""Ayudantes de los tests de `PRDRIVE_PERF` (los `ui.perf_*` de `ui/__init__.py`).

`con_perf(tmp)` enciende la medida con los diarios del dispositivo y del equipo
dentro de `tmp`, y `lineas(tmp, momento)` lee lo que quedó escrito. Ningún test
toca el `logs/` ni el `%LOCALAPPDATA%` de quien lo corre.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

from _harness import REPO  # noqa: F401 — deja la raíz del proyecto en sys.path


@contextmanager
def con_perf(tmp: Path, activo: bool = True):
    """Enciende (o apaga, con `activo=False`) la medida y reapunta sus diarios dentro de `tmp`.

    Al salir vuelca lo que quede en la cola y restaura la variable de entorno y las
    rutas, como estaban. El diario del dispositivo va a `tmp/logs` y el del equipo a
    `tmp/equipo`; ninguna de las dos carpetas se crea por adelantado.

    Args:
        tmp: La carpeta de la prueba.
        activo: Si `PRDRIVE_PERF` queda en `1` (si no, se quita del entorno).
    """
    from common import equipo, model

    import ui

    tmp = Path(tmp)
    antes = (model.LOG_DIR, model.STATE_DIR, equipo.DIR, os.environ.get("PRDRIVE_PERF"))
    model.LOG_DIR = tmp / "logs"
    model.STATE_DIR = tmp / "state"
    equipo.DIR = tmp / "equipo"
    if activo:
        os.environ["PRDRIVE_PERF"] = "1"
    else:
        os.environ.pop("PRDRIVE_PERF", None)
    try:
        yield tmp
    finally:
        try:
            ui.perf_volcar()
        finally:
            # Se restaura aunque el volcado lance: no deben quedar las rutas de la prueba.
            model.LOG_DIR, model.STATE_DIR, equipo.DIR, previo = antes
            if previo is None:
                os.environ.pop("PRDRIVE_PERF", None)
            else:
                os.environ["PRDRIVE_PERF"] = previo


def lineas(tmp: Path, momento: str, host: bool = False) -> list[str]:
    """Devuelve las líneas de un diario de tiempos cuyo momento es `momento`.

    Args:
        tmp: La carpeta que se le dio a `con_perf()`.
        momento: El nombre del momento; se compara con el campo que sigue a la fecha.
        host: Si se lee el diario del equipo y no el del dispositivo.

    Returns:
        Las líneas tal cual, o una lista vacía si no hay diario.
    """
    ruta = Path(tmp) / ("equipo" if host else "logs") / "perf.log"
    if not ruta.is_file():
        return []
    salida = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        partes = linea.split(" ", 3)            # fecha, hora, momento, resto
        if len(partes) > 2 and partes[2] == momento:
            salida.append(linea)
    return salida


def vaciar() -> None:
    """Escribe ya lo que haya en la cola de marcas, sin esperar al hilo."""
    import ui

    ui.perf_volcar()


def salir(codigo: int) -> None:
    """Termina el test con `codigo` sin pasar por la limpieza del intérprete.

    Con la medida encendida sigue vivo el hilo que vuelca las marcas, y al cerrarse
    el intérprete las imágenes de Tk que aún existen se liberan cuando Tkinter ya no
    tiene sus clases: cada una imprime un «Exception ignored» (cientos de líneas con
    rc 0). Lo que se tenía que escribir ya está escrito al salir de `con_perf()`.

    Args:
        codigo: El código de salida del proceso.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(codigo)
