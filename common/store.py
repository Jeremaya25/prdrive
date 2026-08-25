#!/usr/bin/env python3
"""
store.py — Los ficheros de estado en JSON que viajan dentro del pen.

Dos reglas, y las dos vienen del medio: el pen puede desaparecer a media frase y
puede estar leyéndolo otra máquina.

  * Leer nunca es un error. Un fichero que no está, que está a medias o que trae
    basura significa "aquí no hay nada escrito", no una excepción que propagar.
  * Escribir es atómico (fichero temporal + os.replace), y si falla, se dice que
    ha fallado en vez de reventar: ninguno de estos ficheros es imprescindible.

Los comparten el registro del servicio (daemon.lock.json) y la memoria de la UI
(ui_prefs.json).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


def stamp() -> str:
    """El formato de fecha de todos estos ficheros y del diario del servicio."""
    return f"{datetime.now():%Y-%m-%d %H:%M:%S}"


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: dict) -> bool:
    """True si se ha escrito. False = pen de solo lectura o ya extraído."""
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        return False
