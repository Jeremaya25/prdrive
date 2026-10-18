#!/usr/bin/env python3
"""`_seleccion`: de los ficheros cambiados a los tests que corre `run_all.py --cambios`.

Sobre un repositorio de mentira (cinco reglas y unos pocos fuentes y tests):

- un fuente elige su área y la de quien lo importa, a un salto y no a dos, con
  los imports dentro de funciones y los relativos;
- un script que se lanza como proceso elige el área de quien lo lanza (`LANZADO_POR`);
- un test cambiado se elige a sí mismo; un ayudante, a los tests que lo importan;
  `_harness.py` y `common/__init__.py`, a todos;
- un fichero borrado sigue en su área por el patrón; uno sin regla no da tests;
- sin git, todo lo que no abre ventana; sin cambios, nada;
- los tests de ventanas se quedan fuera salvo con `ventanas`;
- `por_areas()` expande igual y rechaza un área que no existe.

Y sobre el repositorio de verdad: `common/bisync.py` elige `engine` y ninguna
ventana, y `LANZADO_POR` dice la verdad sobre quién lanza qué.
"""

from __future__ import annotations

import sys
from pathlib import Path

from _harness import REPO, Checks, tmpdir

import _seleccion
import run_all

c = Checks("_seleccion: qué tests corre cada cambio")

REGLAS = {
    "motor": ["sync.py", "common/mot*.py", "tests/test_motor.py"],
    "llave": ["common/llave.py", "tests/test_llave.py"],
    "lejos": ["common/lejos.py", "tests/test_lejos.py"],
    "servicio": ["runsync.py", "tests/test_servicio.py", "tests/test_tk_servicio.py"],
    "pruebas": ["tests/run_all.py", "tests/_*.py", "tests/test_run_all.py"],
}
"""Las reglas del repositorio de mentira: cada área con sus patrones."""

FICHEROS = {
    "common/__init__.py": "",
    "common/motor.py": "",
    "common/llave.py": "def f():\n    from common import motor\n",
    "common/lejos.py": "from . import llave\n",
    "sync.py": "from common import motor\n",
    "runsync.py": 'SYNC = "sync.py"\n',
    "tests/_harness.py": "",
    "tests/_falso.py": "",
    "tests/run_all.py": "",
    "tests/test_motor.py": "",
    "tests/test_servicio.py": "",
    "tests/test_tk_servicio.py": "",
    "tests/test_run_all.py": "",
    "tests/test_suelto.py": "",
    "tests/test_llave.py": "from _falso import x\n",
    "tests/test_lejos.py": "import _falso as f\n",
}
"""Los fuentes y los tests del repositorio de mentira, con su contenido."""

GUI = {"test_tk_servicio.py"}
"""Los tests de ventanas del repositorio de mentira."""

SIN_VENTANA = ["test_lejos.py", "test_llave.py", "test_motor.py", "test_run_all.py",
               "test_servicio.py", "test_suelto.py"]
"""Todos sus tests menos el de ventanas: lo que da «todo»."""


def repo_falso() -> Path:
    """Crea el repositorio de mentira en un temporal y devuelve su raíz."""
    raiz = tmpdir("prdrive-seleccion-")
    for nombre, patrones in REGLAS.items():
        ruta = raiz / ".claude" / "rules" / f"{nombre}.md"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        lineas = "".join(f'  - "{p}"\n' for p in patrones)
        ruta.write_text(f"---\npaths:\n{lineas}---\nCuerpo.\n", encoding="utf-8")
    for rel, texto in FICHEROS.items():
        ruta = raiz / rel
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(texto, encoding="utf-8")
    return raiz


R = repo_falso()
lanzado_por = _seleccion.LANZADO_POR
_seleccion.LANZADO_POR = {"sync.py": ("runsync.py",)}
try:
    def e(cambios, ventanas=False):
        """`elegir()` sobre el repositorio de mentira."""
        return _seleccion.elegir(cambios, gui=GUI, ventanas=ventanas, repo=R)

    imp = _seleccion.importadores(R)
    c("importadores: un import dentro de una función cuenta",
      imp.get("common/motor.py"), {"common/llave.py", "sync.py"})
    c("importadores: un import relativo cuenta", imp.get("common/llave.py"), {"common/lejos.py"})

    sel = e(["common/motor.py"])
    c("motor: su área y la de quien lo importa, a un salto (lejos no)",
      sel.tests, ["test_llave.py", "test_motor.py"])
    c("motor: dice por qué entra llave",
      "llave ← common/llave.py importa common/motor.py" in sel.motivos, True)

    sel = e(["sync.py"])
    c("sync.py: las áreas de quien lo lanza; la ventana, fuera",
      (sel.tests, sel.fuera), (["test_motor.py", "test_servicio.py"], ["test_tk_servicio.py"]))
    c("sync.py: dice quién lo lanza", "servicio ← runsync.py lanza sync.py" in sel.motivos, True)
    sel = e(["sync.py"], True)
    c("con ventanas: la ventana entra",
      (sel.tests, sel.fuera), (["test_motor.py", "test_servicio.py", "test_tk_servicio.py"], []))

    c("un fichero borrado cuenta por el patrón de su regla",
      e(["common/motor_viejo.py"]).tests, ["test_motor.py"])
    c("un test cambiado: ese test", e(["tests/test_lejos.py"]).tests, ["test_lejos.py"])
    c("un ayudante: los que lo importan, de las dos formas, y no su área",
      e(["tests/_falso.py"]).tests, ["test_lejos.py", "test_llave.py"])

    sel = e(["tests/_harness.py"])
    c("_harness: todo lo que no abre ventana",
      (sel.tests, sel.motivos),
      (SIN_VENTANA, ["todo lo que no abre ventana ← tests/_harness.py lo importan todos"]))
    c("common/__init__.py: todo", e(["common/__init__.py"]).tests, SIN_VENTANA)

    sel = e(["LICENSE"])
    c("un fichero sin regla: ningún test, y se dice", (sel.tests, sel.sin_tests), ([], ["LICENSE"]))
    sel = e([])
    c("sin cambios: nada, y nada sin tests",
      (sel.tests, sel.motivos, sel.sin_tests, sel.fuera), ([], [], [], []))
    sel = e(None)
    c("sin git: todo lo que no abre ventana, y lo dice",
      (sel.tests, sel.motivos),
      (SIN_VENTANA, ["todo lo que no abre ventana ← no se sabe qué cambió (sin git o sin base común con main)"]))
    sel = e(["tests/test_tk_servicio.py"])
    c("un test de ventana cambiado: fuera", (sel.tests, sel.fuera), ([], ["test_tk_servicio.py"]))

    sel = _seleccion.por_areas(["llave"], gui=GUI, ventanas=False, repo=R)
    c("--area llave: su área y la de quien importa sus fuentes",
      sel.tests, ["test_lejos.py", "test_llave.py"])
    c("--area llave: lo primero es el área pedida", sel.motivos[:1], ["llave ← pedida"])
    try:
        _seleccion.por_areas(["nada", "llave"], gui=GUI, ventanas=False, repo=R)
        desconocidas = None
    except ValueError as error:
        desconocidas = error.args[0]
    c("--area con un nombre que no es una regla: ValueError con los desconocidos",
      desconocidas, ["nada"])
finally:
    _seleccion.LANZADO_POR = lanzado_por

# Sobre el repositorio de verdad.
sel = _seleccion.elegir(["common/bisync.py"], gui=set(run_all.GUI), ventanas=False)
c("de verdad: bisync elige engine", any(m.startswith("engine ← ") for m in sel.motivos), True)
c("de verdad: y ningún test de ventana", sorted(set(sel.tests) & run_all.GUI), [])
c("de verdad: test_bisync_prefijo.py entra", "test_bisync_prefijo.py" in sel.tests, True)

CONSTANTE = {"sync.py": "model.SYNC_PY", "runsync.py": "model.RUNSYNC_PY",
             "penwatch.py": "model.PENWATCH_PY"}
"""La constante de `model` con la que se lanza cada script, si la tiene."""


def texto(rel: str) -> str:
    """El contenido de un fichero del repositorio de verdad."""
    return (REPO / rel).read_text(encoding="utf-8")


c("LANZADO_POR: cada script y cada lanzador existen",
  sorted(r for s, gs in _seleccion.LANZADO_POR.items() for r in (s, *gs) if not (REPO / r).is_file()), [])
c("LANZADO_POR: cada lanzador nombra el script (entre comillas o por su constante de model)",
  [(s, g) for s, gs in _seleccion.LANZADO_POR.items() for g in gs
   if f'"{s}"' not in texto(g) and (s not in CONSTANTE or CONSTANTE[s] not in texto(g))], [])

sys.exit(c.report())
