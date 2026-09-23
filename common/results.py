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
from typing import Iterable, NamedTuple

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
    # La última pasada buena de esa pareja (`_buena()`), o None si no consta
    # ninguna. Es lo que dice desde cuándo falla. Va con valor por defecto
    # porque quien construye un Fallo a mano no tiene por qué saberla.
    buena: str | None = None


def _buena(dato: dict) -> str | None:
    """La fecha de la última pasada buena que conste en lo apuntado de una pareja.

    Aquí solo cabe un resultado por pareja, así que sin esto un fallo borraría la
    fecha de cuando esa pareja sí quedó al día — y para todo lo que no es bisync
    este es el único sitio donde consta, porque los listados solo existen ahí.

    El segundo camino es por los registros escritos antes de que existiera la
    clave: si la última pasada apuntada fue buena, su fecha es la que se busca."""
    if isinstance(dato.get("buena"), str):
        return dato["buena"]
    try:
        if int(dato.get("codigo", 1)) != 0:
            return None
    except (TypeError, ValueError):
        return None
    return dato["cuando"] if isinstance(dato.get("cuando"), str) else None


def apuntar(nombre: str, codigo: int, log: Path | None) -> None:
    """Apunta el resultado de una pasada. Nunca falla: si el dispositivo no deja
    escribir, el aviso se pierde, pero la sincronización no puede caerse por él.

    El log se guarda por su nombre dentro de `logs/`, no con la ruta entera: la
    letra de unidad cambia de un equipo a otro."""
    data = store.read_json(ruta_estado())
    parejas = data.get("parejas") if isinstance(data.get("parejas"), dict) else {}
    anterior = parejas.get(nombre)
    ahora = store.stamp()
    parejas[nombre] = {"cuando": ahora, "codigo": int(codigo),
                       "log": log.name if log is not None else None,
                       "buena": ahora if int(codigo) == 0 else
                                _buena(anterior if isinstance(anterior, dict) else {})}
    store.write_json(ruta_estado(), {"parejas": parejas})


def ultimas_buenas(nombres: Iterable[str]) -> dict[str, float]:
    """Cuándo terminó BIEN por última vez cada una de esas parejas.

    Lo de aquí es la única huella que deja una pasada cualquiera: la apunta
    `sync.run_pair()` la lance quien la lance —la ventana, una terminal, el
    servicio periódico o el vigilante al enchufar el dispositivo—, así que es lo
    que le falta a `bisync.last_run()`, que solo sabe de la fecha de los listados
    y por tanto solo de las parejas bisync.

    Solo las buenas: la ventana enseña esta fecha como la última vez que esa
    pareja quedó al día, y una pasada fallida no deja nada al día —ni borra la
    anterior, para eso está `_buena()`—. De que falló avisan `fallos()` y su
    banner, que es donde eso se cuenta."""
    parejas = store.read_json(ruta_estado()).get("parejas")
    if not isinstance(parejas, dict):
        return {}
    marcas: dict[str, float] = {}
    for nombre in nombres:
        dato = parejas.get(nombre)
        if not isinstance(dato, dict):
            continue
        cuando = store.desde_sello(str(_buena(dato) or ""))
        if cuando is not None:
            marcas[nombre] = cuando
    return marcas


def fallos(config: Config) -> list[Fallo]:
    """Las parejas del config cuya última pasada falló, en el orden del config."""
    return fallos_de(config.names)


def fallos_de(nombres: Iterable[str]) -> list[Fallo]:
    """Lo mismo para una lista de nombres: el servicio solo sabe los suyos."""
    parejas = store.read_json(ruta_estado()).get("parejas")
    if not isinstance(parejas, dict):
        return []
    salida = []
    for nombre in nombres:
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
        salida.append(Fallo(nombre, str(dato.get("cuando", "")), codigo, log,
                            _buena(dato)))
    return salida
