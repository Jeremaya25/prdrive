#!/usr/bin/env python3
"""
El registro de la última pasada de cada pareja (common/results.py).

Es lo que hace que un fallo no se quede escondido en `logs/`: la ventana
principal lo lee al abrirse y el servicio al terminar un ciclo. Se comprueba lo
que se ve desde fuera: qué parejas cuentan como falladas y qué log se enseña.
"""

import sys

from _harness import Checks, mkcfg, sandbox

from common import model, results, store

c = Checks("última pasada de cada pareja (common/results.py)")

with sandbox():
    cfg = mkcfg(["notas", "fotos", "docs"])
    c("sin nada apuntado no hay fallos", results.fallos(cfg), [])

    model.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = model.LOG_DIR / "notas_20260911_101010.log"
    log.write_text("ERROR\n", encoding="utf-8")
    results.apuntar("notas", 1, log)
    results.apuntar("fotos", 0, None)

    fallos = results.fallos(cfg)
    c("una pasada fallida cuenta", [f.pareja for f in fallos], ["notas"])
    c("con su código", fallos[0].codigo, 1)
    c("y con su log", fallos[0].log, log)
    c("el log se guarda por nombre, no con la letra de unidad",
      results.ruta_estado().read_text(encoding="utf-8").count(str(model.LOG_DIR)), 0)

    log.unlink()
    c("si el log ya no está, el fallo sigue pero sin log", results.fallos(cfg)[0].log, None)

    results.apuntar("notas", 0, None)
    c("una pasada buena después lo borra", results.fallos(cfg), [])

    results.apuntar("docs", 2, None)
    c("un aborto antes de rclone también es un fallo",
      [f.pareja for f in results.fallos(cfg)], ["docs"])
    c("una pareja que ya no está en el config no cuenta",
      results.fallos(mkcfg(["notas"])), [])

    # Con el fallo viaja la última pasada buena de esa pareja: es lo que dice
    # desde cuándo falla (la ficha de la flota). `fotos` fue bien más arriba.
    buena_fotos = store.read_json(results.ruta_estado())["parejas"]["fotos"]["cuando"]
    results.apuntar("fotos", 1, None)
    por_pareja = {f.pareja: f for f in results.fallos(cfg)}
    c("el fallo recuerda la última pasada buena", por_pareja["fotos"].buena, buena_fotos)
    c("y de una que nunca fue bien no consta ninguna", por_pareja["docs"].buena, None)

    # Un registro escrito antes de que existiera la clave `buena`: de un fallo
    # así no se sabe cuándo fue bien, y no se inventa.
    store.write_json(results.ruta_estado(), {"parejas": {"notas": {
        "cuando": "2026-01-01 00:00:00", "codigo": 1, "log": None}}})
    c("un fallo de un registro antiguo no trae pasada buena",
      [f.buena for f in results.fallos(cfg)], [None])

    results.ruta_estado().write_text("no es json", encoding="utf-8")
    c("un registro ilegible no son fallos", results.fallos(cfg), [])

sys.exit(c.report())
