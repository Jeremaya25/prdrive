#!/usr/bin/env python3
"""
results.py — Cómo acabó la última pasada de cada pareja.

Existe para que un fallo no se quede escondido. El log de una pasada fallida se
guarda en `logs/`, pero nadie va a mirar ahí: el servicio puede pasarse días
fallando en cada ciclo mientras el usuario cree que el dispositivo está al día.
Con esto la ventana principal sabe, nada más abrirse, qué parejas fallaron la
última vez y qué log lo explica.

Lo escribe `sync.py`, que es quien sabe el resultado y dónde ha dejado el log, y
lo escribe pase lo que pase por encima: la ventana, el servicio o una terminal.
Una pareja SALTADA (pide --resync y nadie lo ha aprobado) no se apunta: no se
ha ejecutado, así que su último resultado de verdad sigue siendo el anterior, y
de que pide un resync ya avisa su propio chip.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from . import model, store
from .model import Config


def ruta_estado() -> Path:
    """Función y no constante: los tests cambian `model.STATE_DIR` al vuelo."""
    return model.STATE_DIR / "last_run.json"


class Fallo(NamedTuple):
    pareja: str
    cuando: str             # `store.stamp()` del final de la pasada
    codigo: int
    log: Path | None        # None si no quedó log o ya no está


def apuntar(nombre: str, codigo: int, log: Path | None) -> None:
    """Apunta el resultado de una pasada. Nunca falla: si el dispositivo no deja
    escribir, el aviso se pierde, pero la sincronización no puede caerse por él.

    El log se guarda por su nombre dentro de `logs/`, no con la ruta entera: la
    letra de unidad cambia de un equipo a otro."""
    data = store.read_json(ruta_estado())
    parejas = data.get("parejas") if isinstance(data.get("parejas"), dict) else {}
    parejas[nombre] = {"cuando": store.stamp(), "codigo": int(codigo),
                       "log": log.name if log is not None else None}
    store.write_json(ruta_estado(), {"parejas": parejas})


def fallos(config: Config) -> list[Fallo]:
    """Las parejas del config cuya última pasada falló, en el orden del config."""
    parejas = store.read_json(ruta_estado()).get("parejas")
    if not isinstance(parejas, dict):
        return []
    salida = []
    for nombre in config.names:
        dato = parejas.get(nombre)
        if not isinstance(dato, dict):
            continue
        try:
            codigo = int(dato.get("codigo", 0))
        except (TypeError, ValueError):
            continue
        if codigo == 0:
            continue
        log = None
        if isinstance(dato.get("log"), str):
            candidato = model.LOG_DIR / Path(dato["log"]).name
            try:
                log = candidato if candidato.is_file() else None
            except OSError:
                log = None
        salida.append(Fallo(nombre, str(dato.get("cuando", "")), codigo, log))
    return salida
