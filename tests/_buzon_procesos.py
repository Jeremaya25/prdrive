#!/usr/bin/env python3
"""Peticiones a un buzón desde procesos de verdad, mientras otro lo recoge.

Lo comparten `tests/test_buzon_carrera.py` y la fila F22 de máquina real
(`tests/maquina/f22_buzon_turno_linux.py`). No sustituye nada: cada proceso
importa `common.equipo` del árbol que se le dice y llama a `pedir()` o a
`recoger()` sin parar, que es como se ve si una petición dada por dejada se
pierde. No importa `_harness`: los buzones son rutas que da quien llama.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

ESCRITOR = ("import json, sys, time\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from common import equipo\n"
            "buzon, salida = Path(sys.argv[2]), Path(sys.argv[3])\n"
            "dichos, n, limite = [], int(sys.argv[5]), time.monotonic() + float(sys.argv[4])\n"
            "while time.monotonic() < limite:\n"
            "    n += 1\n"
            "    if equipo.pedir({'pide': 'x', 'n': n}, buzon):\n"
            "        dichos.append(n)\n"
            "salida.write_text(json.dumps(dichos))\n")
"""Pide sin parar durante unos segundos y apunta lo que `pedir()` dio por dejado.

Numera sus peticiones desde el número que se le da, para que las de dos
escritores de un mismo buzón no se confundan.
"""

LECTOR = ("import json, sys, time\n"
          "from pathlib import Path\n"
          "sys.path.insert(0, sys.argv[1])\n"
          "from common import equipo\n"
          "buzon, salida, fin = Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])\n"
          "vistos, limite = [], time.monotonic() + 120\n"
          "while not fin.exists() and time.monotonic() < limite:\n"
          "    vistos += [p['n'] for p in equipo.recoger(buzon)]\n"
          "for _ in range(3):\n"
          "    time.sleep(0.05)\n"
          "    vistos += [p['n'] for p in equipo.recoger(buzon)]\n"
          "salida.write_text(json.dumps(vistos))\n")
"""Recoge sin parar hasta que exista el fichero `fin`, y apunta lo que le llegó."""


class Recuento(NamedTuple):
    """Lo que dio una tanda de peticiones.

    Args:
        codigos: El código de salida de cada proceso, escritores primero.
        dichas: Peticiones que `pedir()` dio por dejadas.
        perdidas: Las de esas que `recoger()` no devolvió nunca.
        repetidas: Las que devolvió más de una vez.
    """

    codigos: list[int]
    dichas: int
    perdidas: int
    repetidas: int


def pedir_y_recoger(repo: Path, buzones: list[Path], trabajo: Path, escritores: int,
                    segundos: float) -> Recuento:
    """Pide a cada buzón desde `escritores` procesos mientras otro lo recoge, y cuenta.

    Args:
        repo: El árbol de código que importan los procesos.
        buzones: Los buzones; cada uno tiene sus escritores y su lector.
        trabajo: Una carpeta para lo que apunta cada proceso. Fuera del
            volumen de los buzones, si se va a desmontar.
        escritores: Cuántos procesos piden a la vez en cada buzón.
        segundos: Cuánto pide cada uno.
    """
    fin = trabajo / "fin"
    piden, recogen = [], []
    for i, buzon in enumerate(buzones):
        recogen.append(subprocess.Popen(
            [sys.executable, "-c", LECTOR, str(repo), str(buzon),
             str(trabajo / f"vistos{i}.json"), str(fin)]))
        for e in range(escritores):
            piden.append(subprocess.Popen(
                [sys.executable, "-c", ESCRITOR, str(repo), str(buzon),
                 str(trabajo / f"dichos{i}-{e}.json"), str(segundos), str(e * 10**9)]))
    codigos = [p.wait(120) for p in piden]
    fin.touch()
    codigos += [p.wait(120) for p in recogen]
    if any(codigos):
        return Recuento(codigos, 0, 0, 0)
    dichas = perdidas = repetidas = 0
    for i in range(len(buzones)):
        vistos = json.loads((trabajo / f"vistos{i}.json").read_text())
        dichos: set[int] = set()
        for e in range(escritores):
            dichos.update(json.loads((trabajo / f"dichos{i}-{e}.json").read_text()))
        dichas += len(dichos)
        perdidas += len(dichos - set(vistos))
        repetidas += len(vistos) - len(set(vistos))
    return Recuento(codigos, dichas, perdidas, repetidas)
