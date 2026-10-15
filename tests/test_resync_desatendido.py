#!/usr/bin/env python3
"""«Resincronizar…» de la ficha de una pareja no se lanza nunca sin una persona (#97).

El `--resync` lo pide una persona desde la ventana: lee el plan
(`pair_editor.plan_resync()`, que sale de `repair.aviso_resync()`), lo confirma en
`tk_pairs.confirmar_plan()` y la orden es la de `repair.args_resync()`. El
servicio, `--auto`, el agente y el vigilante no la pasan nunca: sus hijos llevan
la entrada cerrada y se saltan lo que pide confirmación. Aquí se mira lo que de
verdad lanzan, y un recorrido por las fuentes obliga a decidir cada vez que un
módulo nuevo construye el plan o la orden.
"""

import ast
import re
import subprocess
import sys
from glob import glob
from pathlib import Path

from _harness import REPO, Checks, sandbox

import runsync
from common import model

c = Checks("«Resincronizar…» no se lanza sin una persona")

# ---- El servicio periódico y `--auto --once` -----------------------------------------------

llamadas: list[list] = []
real_run = subprocess.run


def run_falso(cmd, **kwargs):
    """Apunta lo que se lanza y contesta que fue bien."""
    llamadas.append(list(cmd))
    return subprocess.CompletedProcess(cmd, 0, "", "")


with sandbox():
    subprocess.run = run_falso
    real = (runsync.servicio_en_marcha, runsync.pareja_llavero, runsync.dlog,
            runsync.prioridad.bajar)
    try:
        runsync.run_pair_quiet("notas")
        runsync.servicio_en_marcha = lambda: None
        runsync.pareja_llavero = lambda: None
        runsync.dlog = lambda *_a, **_k: None
        runsync.prioridad.bajar = lambda: None
        runsync.una_pasada(["notas", "fotos"])
    finally:
        subprocess.run = real_run
        (runsync.servicio_en_marcha, runsync.pareja_llavero, runsync.dlog,
         runsync.prioridad.bajar) = real

c("el servicio y `--auto --once` lanzaron sync.py", len(llamadas) >= 2, True)
c("  y ninguno lleva --resync ni --yes (que aprobaría uno)",
  [cmd for cmd in llamadas if {"--resync", "--yes"} & set(cmd)], [])
c("  solo el nombre de las parejas, tras sync.py",
  [cmd[1:] for cmd in llamadas],
  [[str(model.SYNC_PY), "notas"], [str(model.SYNC_PY), "notas", "fotos"]])

# ---- Las fuentes: quién arma el plan y la orden del resync ---------------------------------

PERMITIDOS = {
    "ui/repair.py": "arma el plan y la orden (`aviso_resync()`, `args_resync()`)",
    "ui/pair_editor.py": "`plan_resync()`: el mismo plan de «Reparación» más apartar la referencia",
    "ui/tk_repair.py": "el botón «Resincronizar…» de «Reparación»",
    "ui/tk_pairs.py": "el botón «Resincronizar…» de la ficha de una pareja",
}
"""Los únicos módulos que piden el plan o la orden de un resync, y por qué.

Un módulo que lance `sync.py` y no esté aquí no puede pasar `--resync`: si necesita
hacerlo, que quien lo escriba lo piense y lo añada con su motivo, junto a un test que
fije que solo lo pide una persona.
"""

FUNCIONES = {"args_resync", "aviso_resync", "plan_resync"}


def nombra(ruta: str) -> bool:
    """Dice si el módulo define, importa o usa alguna de esas funciones (no si la cita un texto)."""
    for nodo in ast.walk(ast.parse((REPO / ruta).read_text(encoding="utf-8"))):
        nombre = (nodo.name if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef))
                  else nodo.attr if isinstance(nodo, ast.Attribute)
                  else nodo.id if isinstance(nodo, ast.Name)
                  else nodo.name if isinstance(nodo, ast.alias) else None)
        if nombre in FUNCIONES:
            return True
    return False


fuentes = sorted({Path(f).as_posix() for g in ("*.py", "common/*.py", "ui/*.py", "install/*.py")
                  for f in glob(g, root_dir=REPO)})
nombran = {f for f in fuentes if nombra(f)}
c("solo piden el plan o la orden del resync los módulos previstos",
  sorted(nombran - set(PERMITIDOS)), [])
c("  y no queda ninguno previsto que ya no lo pida (la lista no se pudre)",
  sorted(set(PERMITIDOS) - nombran), [])
lanzadores = {"runsync.py", "agente.py", "penwatch.py", "prdrive-install.py", "ui/__init__.py",
              "ui/tk.py", "ui/console.py", "common/llavero.py", "common/keepassxc.py", "sync.py"}
c("  y ninguno de los que lanzan sync.py (el servicio, el vigilante, el agente, las ventanas "
  "principal y de consola) está entre ellos", sorted(lanzadores & nombran), [])

# La orden se arma en un solo sitio: las pantallas piden la de `repair`, no escriben la suya.
LITERAL = re.compile(r"""["']--resync["']""")
c("la ficha de la pareja no escribe su propia orden: no hay un \"--resync\" en tk_pairs ni en "
  "pair_editor",
  sorted(f for f in ("ui/tk_pairs.py", "ui/pair_editor.py")
         if LITERAL.search((REPO / f).read_text(encoding="utf-8"))), [])
c("  y entre todo `ui/` solo `repair.args_resync()` lo escribe",
  sorted(f for f in fuentes if f.startswith("ui/")
         and LITERAL.search((REPO / f).read_text(encoding="utf-8"))), ["ui/repair.py"])

sys.exit(c.report())
