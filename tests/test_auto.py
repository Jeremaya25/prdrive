#!/usr/bin/env python3
"""--auto: precedencia de argumentos > configuración del servicio > [daemon]
del TOML; y --auto --once, una sola pasada de esas parejas."""

import sys
from pathlib import Path

from _harness import Checks, mkcfg, tmpdir

import runsync
from ui import prefs

c = Checks("arranque sin UI (--auto)")
prefs.PREFS = tmpdir("prdrive-auto-") / "ui_prefs.json"

CFG = mkcfg(["upload", "claves", "docs", "prdrive"],
            {"pairs": ["docs", "claves"], "interval_minutes": 15})
ALL = CFG.names

# Nada de esto debe tocar el servicio real ni el diario del dispositivo.
runsync.stop_previous_daemon = lambda: None
runsync.dlog = lambda msg: None
runsync.model.load_config = lambda: CFG
lanzado: dict = {}
runsync.spawn_daemon = lambda pairs, mins: lanzado.update(pairs=pairs, mins=mins) or "ok"
real_print = print
import builtins
builtins.print = lambda *a, **k: None
try:
    runsync.auto_start([])
    c("sin recuerdo manda [daemon]", (lanzado["pairs"], lanzado["mins"]),
      (["docs", "claves"], 15.0))

    prefs.save_prefs("daemon", ["claves"], 8.0, ALL)
    lanzado.clear(); runsync.auto_start([])
    c("con recuerdo manda el recuerdo", (lanzado["pairs"], lanzado["mins"]), (["claves"], 8.0))

    lanzado.clear(); runsync.auto_start(["--interval", "3", "docs"])
    c("los argumentos mandan sobre todo", (lanzado["pairs"], lanzado["mins"]),
      (["docs"], 3.0))

    lanzado.clear(); runsync.auto_start(["--interval", "3"])
    c("solo --interval: parejas del recuerdo", (lanzado["pairs"], lanzado["mins"]),
      (["claves"], 3.0))

    # Un arranque automático nunca reescribe lo que se decidió a mano.
    antes = prefs.PREFS.read_text(encoding="utf-8")
    lanzado.clear(); runsync.auto_start(["upload"])
    c("--auto no reescribe el recuerdo", prefs.PREFS.read_text(encoding="utf-8"), antes)

    # --- --once: una pasada de las parejas del servicio, sin servicio -------
    # Es el modo `sync` del vigilante. Ni arranca el servicio ni para el que
    # hubiera: si hay uno vivo en este equipo, no hace nada.
    pasadas: list = []
    paradas: list = []
    runsync.run_interactive = lambda args: pasadas.append(list(args)) or 0
    runsync.stop_previous_daemon = lambda: paradas.append(1)
    runsync.servicio_en_marcha = lambda: None

    lanzado.clear(); runsync.auto_start(["--once"])
    c("--once: una pasada de las parejas del servicio", pasadas, [["claves"]])
    c("--once: sin servicio detrás", lanzado, {})
    c("--once: y sin parar nada", paradas, [])

    pasadas.clear(); runsync.auto_start(["--once", "--interval", "3", "docs"])
    c("--once antes de --interval", pasadas, [["docs"]])
    pasadas.clear(); runsync.auto_start(["--interval", "3", "--once"])
    c("--interval antes de --once", pasadas, [["claves"]])

    runsync.servicio_en_marcha = lambda: {"pid": 4321, "host": runsync.HOST}
    pasadas.clear(); lanzado.clear(); runsync.auto_start(["--once"])
    c("--once con un servicio vivo aquí no lanza nada",
      (pasadas, lanzado, paradas), ([], {}, []))

    # Un registro de antes, de una pasada manual, no decide lo que hace --auto.
    runsync.servicio_en_marcha = lambda: None
    prefs.save_prefs("manual", ["upload"], 4.0, ALL)
    lanzado.clear(); runsync.auto_start([])
    c("un recuerdo 'manual' no decide el servicio", (lanzado["pairs"], lanzado["mins"]),
      (["docs", "claves"], 15.0))
finally:
    builtins.print = real_print

sys.exit(c.report())
