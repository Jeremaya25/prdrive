#!/usr/bin/env python3
"""--auto: precedencia de argumentos > recuerdo de la UI > [daemon] del TOML."""

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
finally:
    builtins.print = real_print

sys.exit(c.report())
