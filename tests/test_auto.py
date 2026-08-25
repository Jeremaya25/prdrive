#!/usr/bin/env python3
"""--auto: precedencia de argumentos > recuerdo de la UI > [daemon] del TOML."""

import sys
import tempfile
from pathlib import Path

from _harness import Checks, mkcfg

import runsync
from ui import prefs

c = Checks("arranque sin UI (--auto)")
prefs.PREFS = Path(tempfile.mkdtemp(prefix="perepen-auto-")) / "ui_prefs.json"

CFG = mkcfg(["upload", "keepass", "obsidian", "perepen"],
            {"pairs": ["obsidian", "keepass"], "interval_minutes": 15})
ALL = CFG.names

# Nada de esto debe tocar el servicio real ni el diario del pen.
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
      (["obsidian", "keepass"], 15.0))

    prefs.save_prefs("daemon", ["keepass"], 8.0, ALL)
    lanzado.clear(); runsync.auto_start([])
    c("con recuerdo manda el recuerdo", (lanzado["pairs"], lanzado["mins"]), (["keepass"], 8.0))

    lanzado.clear(); runsync.auto_start(["--interval", "3", "obsidian"])
    c("los argumentos mandan sobre todo", (lanzado["pairs"], lanzado["mins"]),
      (["obsidian"], 3.0))

    lanzado.clear(); runsync.auto_start(["--interval", "3"])
    c("solo --interval: parejas del recuerdo", (lanzado["pairs"], lanzado["mins"]),
      (["keepass"], 3.0))

    # Un arranque automático nunca reescribe lo que se decidió a mano.
    antes = prefs.PREFS.read_text(encoding="utf-8")
    lanzado.clear(); runsync.auto_start(["upload"])
    c("--auto no reescribe el recuerdo", prefs.PREFS.read_text(encoding="utf-8"), antes)
finally:
    builtins.print = real_print

sys.exit(c.report())
