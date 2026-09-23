#!/usr/bin/env python3
"""
La fecha de «última pasada» de la ventana principal (ui.pair_times).

Sale de dos sitios, y por eso tiene test propio: los listados de bisync solo
existen para las parejas bisync, así que todo lo demás —un `up`, un
`down-mirror`— se quedaba sin fecha para siempre. Lo que llena ese hueco es
`state/last_run.json`, que apunta cualquier pasada real la lance quien la lance:
la ventana, una terminal, el servicio periódico o el vigilante al enchufar.

Solo cuentan las pasadas buenas: la columna dice cuándo quedó esa pareja al día,
y de un fallo ya avisa el banner ámbar.
"""

import os
import sys

from _harness import Checks, mkcfg, sandbox

import ui
from common import bisync, results, store

c = Checks("la fecha de la última pasada")

CFG = mkcfg([], pairs=[
    {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas"},
    {"name": "fotos", "local": "sync-data/fotos", "remote_path": "/R/fotos",
     "mode": "up"},
])
NOTAS, FOTOS = CFG.pairs


def apuntar(nombre: str, codigo: int, sello: str) -> None:
    """`results.apuntar()` con la fecha puesta a mano: un test no espera."""
    real, store.stamp = store.stamp, lambda: sello
    try:
        results.apuntar(nombre, codigo, None)
    finally:
        store.stamp = real


def listado(pair, sello: str) -> None:
    """Un listado de bisync con la fecha de esa pasada, como lo deja rclone."""
    pair.workdir.mkdir(parents=True, exist_ok=True)
    fichero = pair.workdir / ("x" + bisync.PATH1_SUFFIX)
    fichero.write_text("listado\n", encoding="utf-8")
    marca = store.desde_sello(sello)
    os.utime(fichero, (marca, marca))


with sandbox():
    c("sin nada, ninguna pareja tiene fecha", ui.pair_times(CFG),
      {"notas": None, "fotos": None})

    listado(NOTAS, "2026-09-20 08:00:00")
    c("una pareja bisync, por la fecha de sus listados",
      ui.pair_times(CFG)["notas"], store.desde_sello("2026-09-20 08:00:00"))

    # Lo que motiva el cambio: esta pareja no es bisync y no deja listados, así
    # que su única huella es lo que apuntó sync.py.
    apuntar("fotos", 0, "2026-09-21 09:30:00")
    c("una pareja que no es bisync, por lo apuntado",
      ui.pair_times(CFG)["fotos"], store.desde_sello("2026-09-21 09:30:00"))

    # El servicio periódico lanza un sync.py por pareja: lo que deja apuntado es
    # tan válido como lo que dejaría la ventana, y es más nuevo.
    apuntar("notas", 0, "2026-09-22 07:15:00")
    c("de las dos fuentes manda la más reciente",
      ui.pair_times(CFG)["notas"], store.desde_sello("2026-09-22 07:15:00"))

    # Un fallo no adelanta la fecha y, sobre todo, no borra la de la última
    # buena: aquí solo cabe un resultado por pareja, así que si no se guardara
    # aparte, un `up` que falla hoy perdería el «ayer a las 09:30» de golpe.
    apuntar("notas", 1, "2026-09-22 19:00:00")
    c("una pasada fallida no mueve la fecha",
      ui.pair_times(CFG)["notas"], store.desde_sello("2026-09-22 07:15:00"))
    apuntar("fotos", 1, "2026-09-22 19:00:00")
    c("ni borra la de la última buena",
      ui.pair_times(CFG)["fotos"], store.desde_sello("2026-09-21 09:30:00"))
    c("pero sí cuenta como fallo", [f.pareja for f in results.fallos(CFG)],
      ["notas", "fotos"])

    c("del registro solo salen las fechas buenas",
      results.ultimas_buenas(["notas", "fotos"]),
      {"notas": store.desde_sello("2026-09-22 07:15:00"),
       "fotos": store.desde_sello("2026-09-21 09:30:00")})
    c("una pareja que no está en el registro no aparece",
      results.ultimas_buenas(["ni-idea"]), {})

    results.ruta_estado().write_text("no es json", encoding="utf-8")
    c("un registro ilegible no borra lo que dicen los listados",
      ui.pair_times(CFG)["notas"], store.desde_sello("2026-09-20 08:00:00"))
    c("ni impide abrir la ventana", ui.pair_times(CFG)["fotos"], None)

    # Un registro escrito antes de que existiera la clave `buena`: si la última
    # pasada apuntada fue buena, su fecha es la que vale.
    results.ruta_estado().write_text(
        '{"parejas": {"fotos": {"cuando": "2026-09-19 10:00:00", "codigo": 0}}}',
        encoding="utf-8")
    c("un registro viejo, sin la clave nueva, sigue valiendo",
      ui.pair_times(CFG)["fotos"], store.desde_sello("2026-09-19 10:00:00"))

sys.exit(c.report())
