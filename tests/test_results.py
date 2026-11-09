#!/usr/bin/env python3
"""El registro de la última pasada de cada pareja (`common/results.py`).

Es lo que hace que un fallo no se quede escondido en `logs/`: la ventana
principal lo lee al abrirse y el servicio al terminar un ciclo. Se comprueba lo
que se ve desde fuera: qué parejas cuentan como falladas y qué log se enseña.
"""

import json
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

# ---- La retención de un espejo parado en su freno (D2) -------------------------------------
real_stamp = store.stamp
with sandbox():
    log = model.LOG_DIR / "fotos_20261105_182000.log"
    log.write_text("x\n", encoding="utf-8")
    try:
        store.stamp = lambda: "2026-11-05 18:20:00"
        results.apuntar("fotos", 7, log, freno=True)
        a = results.apuntes(["fotos"])["fotos"]
        c("el freno de un espejo la retiene desde esa pasada",
          (a.retenida, a.sabida, a.codigo, a.log), ("2026-11-05 18:20:00", True, 7, log))
        store.stamp = lambda: "2026-11-05 19:00:00"
        results.apuntar("fotos", 1, log)
        c("  otro fallo no la suelta", results.apuntes(["fotos"])["fotos"].retenida,
          "2026-11-05 18:20:00")
        store.stamp = lambda: "2026-11-06 09:00:00"
        results.apuntar("fotos", 7, log, freno=True)
        c("  otra parada la renueva", results.apuntes(["fotos"])["fotos"].retenida,
          "2026-11-06 09:00:00")
        results.apuntar("fotos", 0, None)
        c("  una pasada buena la suelta", results.apuntes(["fotos"])["fotos"].retenida, None)
        crudo = json.loads(results.ruta_estado().read_text(encoding="utf-8"))["parejas"]
        c("  y la clave queda escrita, `null`", ("retenida" in crudo["fotos"],
                                                 crudo["fotos"]["retenida"]), (True, None))
        results.apuntar("nueva", 1, None)
        c("una pareja sin nada antes que falla por otra cosa no queda retenida",
          results.apuntes(["nueva"])["nueva"][3:], (None, True))
        results.apuntar("cero", 0, None, freno=True)
        c("  con código 0 manda el código", results.apuntes(["cero"])["cero"].retenida, None)
    finally:
        store.stamp = real_stamp

with sandbox():
    # Lo que escribió un sync.py de antes (sin la clave) y basura en ella.
    store.write_json(results.ruta_estado(), {"parejas": {
        "fotos": {"cuando": "2026-11-01 10:00:00", "codigo": 7, "log": None, "buena": None},
        "raro1": {"cuando": "x", "codigo": 7, "retenida": 5},
        "raro2": {"cuando": "x", "codigo": 7, "retenida": ""},
        "raro3": {"cuando": "x", "codigo": 7, "retenida": ["a"]},
        "sincodigo": {"cuando": "x", "retenida": "2026-11-01 10:00:00"},
        "texto": {"cuando": "x", "codigo": "siete", "retenida": "2026-11-01 10:00:00"},
        "verdad": {"cuando": "x", "codigo": True}}})
    a = results.apuntes(["fotos", "raro1", "raro2", "raro3", "sincodigo", "texto", "verdad",
                         "nadie"])
    c("sin la clave, no se sabe", (a["fotos"].sabida, a["fotos"].retenida), (False, None))
    c("  lo que no es un texto con algo no retiene",
      [a[n].retenida for n in ("raro1", "raro2", "raro3")], [None, None, None])
    c("  y lo que no consta no sale", "nadie" in a, False)
    c("un código que falta o no es un entero no tira la entrada: su retenida sigue mandando",
      [(a[n].codigo, a[n].retenida) for n in ("sincodigo", "texto")],
      [(None, "2026-11-01 10:00:00")] * 2)
    c("  y un booleano no es un código", a["verdad"].codigo, None)
    results.fijar_retenciones({"fotos": "2026-11-01 10:00:00", "nadie": None})
    datos = json.loads(results.ruta_estado().read_text(encoding="utf-8"))["parejas"]
    c("fijar apunta la decisión donde falta", datos["fotos"]["retenida"], "2026-11-01 10:00:00")
    c("  sin crear parejas que no constan", "nadie" in datos, False)
    results.fijar_retenciones({"fotos": None})
    c("  y no pisa lo que ya está",
      results.apuntes(["fotos"])["fotos"].retenida, "2026-11-01 10:00:00")
    c("fallos_de() no cambia con la clave nueva",
      [f.pareja for f in results.fallos_de(["fotos"])], ["fotos"])

with sandbox():
    results.ruta_estado().write_text("{roto", encoding="utf-8")
    c("un registro ilegible no da retenciones", results.apuntes(["fotos"]), {})
    results.fijar_retenciones({"fotos": "2026-11-01 10:00:00"})
    c("  y fijar no lanza ni escribe nada", results.ruta_estado().read_text(encoding="utf-8"),
      "{roto")

sys.exit(c.report())
