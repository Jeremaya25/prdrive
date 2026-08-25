#!/usr/bin/env python3
"""
_harness.py — Lo que comparten los tests.

No hay framework: son scripts que devuelven 0 o 1. El proyecto no admite
dependencias y esto tiene que poder ejecutarse desde el pen en cualquier equipo,
así que la raíz del proyecto se deduce de la ubicación de este fichero y nunca
de la letra de unidad.
"""

from __future__ import annotations

import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from common import model  # noqa: E402


class Checks:
    """Contador de comprobaciones. `checks.report()` es el código de salida."""

    def __init__(self, titulo: str) -> None:
        self.titulo = titulo
        self.total = 0
        self.fallos = 0
        print(f"=== {titulo} ===")

    def __call__(self, label: str, got, want) -> bool:
        self.total += 1
        if got == want:
            print(f"  OK     {label}")
            return True
        self.fallos += 1
        print(f"  FALLO  {label}")
        print(f"           obtenido: {got!r}")
        print(f"           esperado: {want!r}")
        return False

    def contains(self, label: str, haystack: str, needle: str) -> bool:
        return self(label, needle in haystack, True)

    def report(self) -> int:
        if self.fallos:
            print(f"--- {self.titulo}: {self.fallos} de {self.total} FALLAN\n")
            return 1
        print(f"--- {self.titulo}: {self.total} comprobaciones OK\n")
        return 0


def mkcfg(names, daemon=None, defaults=None, pairs=None) -> model.Config:
    """Una model.Config de mentira a partir de nombres, para no tocar el TOML real."""
    data = {
        "defaults": defaults or {"remote": "synology"},
        "pair": pairs or [{"name": n, "local": f"sync-data/{n}", "remote_path": f"/R/{n}"}
                          for n in names],
    }
    if daemon:
        data["daemon"] = daemon
    return model.parse_config(data)


@contextmanager
def sandbox():
    """Reapunta las rutas del modelo a un directorio temporal.

    Todo lo que escriben bisync, los filtros y los logs cuelga de estas cuatro
    rutas, así que moverlas basta para que ningún test toque el pen de verdad."""
    original = {name: getattr(model, name)
                for name in ("PEN_ROOT", "STATE_DIR", "FILTERS_DIR", "LOG_DIR", "CONFIG_FILE")}
    root = Path(tempfile.mkdtemp(prefix="perepen-test-"))
    try:
        model.PEN_ROOT = root
        model.STATE_DIR = root / "state"
        model.FILTERS_DIR = root / "filters"
        model.LOG_DIR = root / "logs"
        model.CONFIG_FILE = root / "sync_config.toml"
        for d in (model.STATE_DIR, model.FILTERS_DIR, model.LOG_DIR):
            d.mkdir(parents=True, exist_ok=True)
        yield root
    finally:
        for name, value in original.items():
            setattr(model, name, value)
        import shutil
        shutil.rmtree(root, ignore_errors=True)
