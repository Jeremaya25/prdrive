#!/usr/bin/env python3
"""La memoria de la UI: qué recuerda, qué olvida y qué no llega a escribir."""

import json
import sys
import time
from pathlib import Path

from _harness import Checks, mkcfg, tmpdir

from ui import prefs

c = Checks("memoria de la UI (ui/prefs.py)")
prefs.PREFS = tmpdir("prdrive-prefs-") / "ui_prefs.json"

CFG = mkcfg(["upload", "claves", "docs", "prdrive"],
            {"pairs": ["docs", "claves"], "interval_minutes": 15})
ALL = CFG.names

# Sin recuerdo manda [daemon] del TOML.
c("sin recuerdo", prefs.startup_defaults(CFG), (["docs", "claves"], 15.0, None))

# Una elección de la UI manda sobre el TOML.
prefs.save_prefs("daemon", ["docs"], 7.0, ALL)
pairs, interval, memo = prefs.startup_defaults(CFG)
c("tras elegir docs/7min", (pairs, interval), (["docs"], 7.0))
c("y se anuncia", memo is not None and memo.startswith("Precargado"), True)

# Repetir la misma elección no gasta un ciclo de escritura del dispositivo.
mtime = prefs.PREFS.stat().st_mtime_ns
time.sleep(0.05)
prefs.save_prefs("daemon", ["docs"], 7.0, ALL)
c("elección idéntica no reescribe", prefs.PREFS.stat().st_mtime_ns, mtime)

# Una pareja añadida al TOML después entra marcada: nadie la desmarcó nunca.
CFG2 = mkcfg(["upload", "claves", "docs", "prdrive", "fotos"],
             {"pairs": ["docs", "claves"], "interval_minutes": 15})
c("pareja nueva se marca sola", prefs.startup_defaults(CFG2)[0], ["docs", "fotos"])

# El orden es el del TOML, no el del guardado.
prefs.save_prefs("manual", ["prdrive", "upload"], 7.0, ALL)
c("orden del TOML", prefs.startup_defaults(CFG)[0], ["upload", "prdrive"])

# TOML regenerado con otros nombres: todas cuentan como nuevas.
c("TOML regenerado: todas nuevas",
  prefs.startup_defaults(mkcfg(["nuevo-a", "nuevo-b"]))[:2], (["nuevo-a", "nuevo-b"], 7.0))

# Lo elegido ya no existe y no hay parejas nuevas: se vuelve al TOML sin
# presumir de un recuerdo que ya no aplica (nota None).
prefs.save_prefs("manual", ["upload"], 9.0, ALL)
c("elegida borrada del TOML",
  prefs.startup_defaults(mkcfg(["claves", "docs", "prdrive"],
                               {"pairs": ["claves"], "interval_minutes": 20})),
  (["claves"], 20.0, None))

# Ficheros rotos: nunca son un error, solo "no hay nada escrito".
prefs.PREFS.write_text("{ esto no es json", encoding="utf-8")
c("json corrupto", prefs.startup_defaults(CFG), (["docs", "claves"], 15.0, None))

prefs.PREFS.write_text(json.dumps({"pairs": [1, {"x": 2}, "docs"], "known": "no-lista",
                                   "interval_min": "abc", "saved": "2026-01-01 00:00:00"}),
                       encoding="utf-8")
c("tipos inválidos dentro del json", prefs.startup_defaults(CFG)[:2], (["docs"], 15.0))

prefs.PREFS.write_text(json.dumps({"pairs": ["upload"], "known": ALL, "interval_min": 0}),
                       encoding="utf-8")
c("intervalo 0 -> mínimo 1 min", prefs.startup_defaults(CFG)[1], 1.0)

sys.exit(c.report())
