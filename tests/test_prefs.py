#!/usr/bin/env python3
"""La configuración del servicio (`ui/prefs.py`).

Qué recuerda, qué olvida y qué no llega a escribir.
"""

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
c("y se anuncia", memo is not None and memo.startswith("Parejas e intervalo del servicio"),
  True)

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
prefs.save_prefs("daemon", ["prdrive", "upload"], 7.0, ALL)
c("orden del TOML", prefs.startup_defaults(CFG)[0], ["upload", "prdrive"])

# TOML regenerado con otros nombres: todas cuentan como nuevas.
c("TOML regenerado: todas nuevas",
  prefs.startup_defaults(mkcfg(["nuevo-a", "nuevo-b"]))[:2], (["nuevo-a", "nuevo-b"], 7.0))

# Lo elegido ya no existe y no hay parejas nuevas: se vuelve al TOML sin
# presumir de un recuerdo que ya no aplica (nota None).
prefs.save_prefs("daemon", ["upload"], 9.0, ALL)
c("elegida borrada del TOML",
  prefs.startup_defaults(mkcfg(["claves", "docs", "prdrive"],
                               {"pairs": ["claves"], "interval_minutes": 20})),
  (["claves"], 20.0, None))

# Un registro 'manual' es de antes de que las pasadas manuales dejaran de
# escribir aquí: el recuerdo de una pasada suelta no decide el servicio.
prefs.PREFS.write_text(json.dumps({"action": "manual", "pairs": ["upload"], "known": ALL,
                                   "interval_min": 5, "saved": "2026-01-01 00:00:00"}),
                       encoding="utf-8")
c("un registro 'manual' no cuenta", prefs.startup_defaults(CFG),
  (["docs", "claves"], 15.0, None))

# Uno sin `action` (escrito a mano) sí.
prefs.PREFS.write_text(json.dumps({"pairs": ["upload"], "known": ALL, "interval_min": 5}),
                       encoding="utf-8")
c("un registro sin 'action' vale", prefs.startup_defaults(CFG)[:2], (["upload"], 5.0))

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


# «Ajustes → Configuración» guarda SOLO el intervalo (#65).
#
# Sin parejas elegidas, el registro queda sin `pairs`: las parejas siguen
# saliendo del TOML, y un `[daemon]` cambiado a mano después sigue mandando.
prefs.PREFS.unlink()
c("guardar el intervalo sin recuerdo", prefs.guardar_intervalo(CFG, 12.0), True)
guardado = json.loads(prefs.PREFS.read_text(encoding="utf-8"))
c("  no escribe parejas", ("pairs" in guardado, "known" in guardado, guardado["interval_min"]),
  (False, False, 12.0))
pairs, interval, memo = prefs.startup_defaults(CFG)
c("  las parejas siguen siendo las del TOML, con el intervalo guardado",
  (pairs, interval), (["docs", "claves"], 12.0))
c("  y se anuncia como intervalo", memo.startswith("Intervalo del servicio"), True)
c("  un [daemon] cambiado después sigue mandando en las parejas",
  prefs.startup_defaults(mkcfg(ALL, {"pairs": ["upload"], "interval_minutes": 15}))[:2],
  (["upload"], 12.0))
mtime = prefs.PREFS.stat().st_mtime_ns
time.sleep(0.05)
c("  el mismo intervalo otra vez no reescribe",
  (prefs.guardar_intervalo(CFG, 12.0), prefs.PREFS.stat().st_mtime_ns), (True, mtime))

# Con parejas elegidas al arrancar el servicio, se conservan tal cual.
prefs.save_prefs("daemon", ["prdrive"], 7.0, ALL)
prefs.guardar_intervalo(CFG, 45.0)
guardado = json.loads(prefs.PREFS.read_text(encoding="utf-8"))
c("con parejas elegidas, guardar el intervalo las conserva",
  (guardado["action"], guardado["pairs"], guardado["known"], guardado["interval_min"]),
  ("daemon", ["prdrive"], ALL, 45.0))
c("  y el servicio sale con ellas y el intervalo nuevo",
  prefs.startup_defaults(CFG)[:2], (["prdrive"], 45.0))
# «Iniciar servicio» después escribe las parejas con el intervalo guardado.
prefs.save_prefs("daemon", ["docs"], prefs.startup_defaults(CFG)[1], ALL)
c("«Iniciar servicio» después: sus parejas y el intervalo de Configuración",
  prefs.startup_defaults(CFG)[:2], (["docs"], 45.0))

# Un registro `manual` de antes no cuenta: se cambia por uno de solo intervalo.
prefs.PREFS.write_text(json.dumps({"action": "manual", "pairs": ["upload"], "known": ALL,
                                   "interval_min": 5}), encoding="utf-8")
prefs.guardar_intervalo(CFG, 20.0)
c("sobre un registro 'manual': queda solo el intervalo",
  ("pairs" in json.loads(prefs.PREFS.read_text(encoding="utf-8")),
   prefs.startup_defaults(CFG)[:2]), (False, (["docs", "claves"], 20.0)))

# Un registro sin parejas y con un intervalo roto: como si no hubiera nada.
prefs.PREFS.write_text(json.dumps({"interval_min": "abc"}), encoding="utf-8")
c("solo intervalo, pero ilegible: el del TOML", prefs.startup_defaults(CFG),
  (["docs", "claves"], 15.0, None))
prefs.PREFS.write_text('{"interval_min": Infinity}', encoding="utf-8")
c("  infinito tampoco vale", prefs.startup_defaults(CFG)[1], 15.0)

# Lo que se escribe en la pantalla.
for texto, minutos in (("12", 12.0), (" 2,5 ", 2.5), ("1", 1.0), ("1440", 1440.0)):
    c(f"revisar_intervalo({texto!r})", prefs.revisar_intervalo(texto), minutos)
for texto in ("", "abc", "0", "0,5", "-3", "nan", "inf"):
    try:
        prefs.revisar_intervalo(texto)
        malo = None
    except ValueError as e:
        malo = str(e)
    c(f"revisar_intervalo({texto!r}) no vale, y dice por qué",
      malo, "El intervalo tiene que ser un número de minutos: 1 o más.")

sys.exit(c.report())
