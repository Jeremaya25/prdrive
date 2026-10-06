#!/usr/bin/env python3
"""Corre en ESTE sistema las pruebas en máquina real que se le piden, y las resume.

Uso:
    python tests/maquina/correr.py --lista          # qué filas tienen prueba aquí
    python tests/maquina/correr.py F14 F9 ...       # esas (las del otro sistema, no)
    python tests/maquina/correr.py todas

Toca el sistema (discos virtuales, montajes, VeraCrypt, carpetas compartidas):
es para las máquinas de usar y tirar de `.github/workflows/maquina-real.yml`, con
permisos de administrador; en un equipo propio solo con `--de-verdad`.

Lo último que escribe es el resumen, una línea por prueba, para leer solo la
cola del registro:

    RESULTADO F14 W ok 12/12 · <notas>
    RESULTADO F18 W saltada · <motivo>
    RESULTADO F15 W fallo 3/5 · <la primera que falla>

y lo mismo en el resumen del trabajo de GitHub (`$GITHUB_STEP_SUMMARY`). Sale con
1 si alguna falla; una saltada no es un fallo.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun  # noqa: E402

AQUI = Path(__file__).resolve().parent


def pruebas() -> list:
    """Carga los módulos de prueba (`f*.py`), ordenados por su código."""
    salida = []
    for ruta in sorted(AQUI.glob("f*.py")):
        spec = importlib.util.spec_from_file_location(ruta.stem, ruta)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        salida.append(modulo)
    return sorted(salida, key=lambda m: int(m.CODIGO[1:]))


def resumen(m, p: comun.Prueba, saltada: str | None) -> str:
    """La línea de resultado de una prueba."""
    if saltada is not None:
        return f"RESULTADO {m.CODIGO} {m.SISTEMA} saltada · {saltada}"
    total = p.bien + len(p.mal)
    if p.mal:
        return f"RESULTADO {m.CODIGO} {m.SISTEMA} fallo {p.bien}/{total} · {p.mal[0]}"
    return f"RESULTADO {m.CODIGO} {m.SISTEMA} ok {p.bien}/{total}" + (
        " · " + "; ".join(p.notas) if p.notas else "")


def main(argv: list[str]) -> int:
    """Corre lo pedido y devuelve 1 si algo falla."""
    todas = pruebas()
    if "--lista" in argv:
        for m in todas:
            print(f"{m.CODIGO:4} {m.SISTEMA}  {m.QUE}")
        return 0
    if not os.environ.get("GITHUB_ACTIONS") and "--de-verdad" not in argv:
        print("Toca el sistema: es para GitHub Actions. En un equipo propio, con --de-verdad.")
        return 2
    pedidas = {a.upper() for a in argv if not a.startswith("--")}
    elegidas = [m for m in todas if "TODAS" in pedidas or m.CODIGO in pedidas]
    lineas = [f"RESULTADO {c} - no hay prueba en la nube"
              for c in sorted(pedidas - {m.CODIGO for m in todas} - {"TODAS"})]
    for m in elegidas:
        if m.SISTEMA != comun.SISTEMA:
            continue
        print(f"\n=== {m.CODIGO} ({m.SISTEMA}) {m.QUE} ===", flush=True)
        p, saltada, t = comun.Prueba(m.CODIGO), None, time.monotonic()
        try:
            m.probar(p)
        except comun.Saltada as e:
            saltada = str(e)
            print(f"  SALTADA {saltada}", flush=True)
        except Exception as e:                          # noqa: BLE001
            traceback.print_exc()
            p.mal.append(f"error: {type(e).__name__}: {e}")
        print(f"  ({time.monotonic() - t:.0f} s)", flush=True)
        lineas.append(resumen(m, p, saltada))
    print(f"\n==== RESULTADOS ({comun.SISTEMA}) ====")
    for linea in lineas:
        print(linea)
    destino = os.environ.get("GITHUB_STEP_SUMMARY")
    if destino:
        with open(destino, "a", encoding="utf-8") as f:
            f.write("".join(f"- `{linea}`\n" for linea in lineas))
    return 1 if any(" fallo " in linea for linea in lineas) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
