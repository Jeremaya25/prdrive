#!/usr/bin/env python3
"""
run_all.py — Ejecuta todos los tests.

    python tests/run_all.py

Cada test es un script independiente que devuelve 0 o 1; se lanzan en procesos
separados a propósito, porque varios sustituyen funciones del proyecto (el bucle
de Tk, print, las rutas del modelo) y no deben contaminarse entre sí.

Ninguno toca el pen: todos trabajan sobre directorios temporales.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent


def main() -> int:
    scripts = sorted(p for p in TESTS_DIR.glob("test_*.py"))
    if not scripts:
        print("No hay tests que ejecutar.")
        return 1

    fallos = []
    for script in scripts:
        proc = subprocess.run([sys.executable, str(script)], cwd=str(TESTS_DIR))
        if proc.returncode != 0:
            fallos.append(script.name)

    print("=" * 60)
    if fallos:
        print(f"FALLAN {len(fallos)} de {len(scripts)}: {', '.join(fallos)}")
        return 1
    print(f"Los {len(scripts)} ficheros de test pasan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
