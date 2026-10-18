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

`cambiados()` se prueba con un git de verdad en un repositorio temporal: lo de la
rama, lo preparado, lo modificado y lo nuevo, un renombrado por sus dos nombres,
un nombre con tildes y espacios, `origin/main` antes que `main`, y `None` fuera de
un repositorio, se llame desde donde se llame.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
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
    "pruebas": ["tests/run_all.py", "tests/_*.py", "tests/test_run_all.py", "tests/test_reglas_claude.py"],
}
"""Las reglas del repositorio de mentira: cada área con sus patrones."""

FICHEROS = {
    "common/__init__.py": "",
    "common/motor.py": "",
    "common/llave.py": "def f():\n    from common import motor\n",
    "common/lejos.py": "from . import llave\n",
    "common/nuevo.py": "",
    "config.example.toml": "",
    "tests/_runtime.py": "",
    "sync.py": "from common import motor\n",
    "runsync.py": 'SYNC = "sync.py"\n',
    "tests/_harness.py": "",
    "tests/_falso.py": "",
    "tests/run_all.py": "",
    "tests/test_motor.py": 'CI = "_runtime.py"\n',
    "tests/test_servicio.py": "",
    "tests/test_tk_servicio.py": "",
    "tests/test_run_all.py": "",
    "tests/test_reglas_claude.py": "",
    "tests/test_suelto.py": "import sync\n",
    "tests/test_llave.py": ('"""Cita config.example.toml en su docstring."""\n'
                            "from _falso import x  # y en un comentario: config.example.toml\n"
                            'NOTA = 1\n"""Y en el de una variable: config.example.toml."""\n'),
    "tests/test_lejos.py": 'import _falso as f\nEJEMPLO = "config.example.toml"\n',
}
"""Los fuentes y los tests del repositorio de mentira, con su contenido."""

GUI = {"test_tk_servicio.py"}
"""Los tests de ventanas del repositorio de mentira."""

SIN_VENTANA = ["test_lejos.py", "test_llave.py", "test_motor.py", "test_reglas_claude.py",
               "test_run_all.py", "test_servicio.py", "test_suelto.py"]
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
    c("sync.py: las áreas de quien lo lanza, y el test que lo importa; la ventana, fuera",
      (sel.tests, sel.fuera),
      (["test_motor.py", "test_servicio.py", "test_suelto.py"], ["test_tk_servicio.py"]))
    c("sync.py: dice quién lo lanza", "servicio ← runsync.py lanza sync.py" in sel.motivos, True)
    c("sync.py: dice qué test lo importa", "test_suelto.py ← importa sync.py" in sel.motivos, True)
    sel = e(["sync.py"], True)
    c("con ventanas: la ventana entra",
      (sel.tests, sel.fuera),
      (["test_motor.py", "test_servicio.py", "test_suelto.py", "test_tk_servicio.py"], []))

    c("un fichero borrado cuenta por el patrón de su regla, y elige la guarda de reglas "
      "(puede dejar un patrón muerto)",
      e(["common/motor_viejo.py"]).tests, ["test_motor.py", "test_reglas_claude.py"])
    c("un test cambiado: ese test", e(["tests/test_lejos.py"]).tests, ["test_lejos.py"])
    sel = e(["tests/test_suelto.py"])
    c("un test que no está en ninguna regla: él y la guarda de reglas",
      sel.tests, ["test_reglas_claude.py", "test_suelto.py"])
    c("un test que no está en ninguna regla: lo dice",
      "test_reglas_claude.py ← tests/test_suelto.py no está en ninguna regla" in sel.motivos, True)
    sel = e(["common/nuevo.py"])
    c("un fuente que no está en ninguna regla: la guarda de reglas, y no «sin tests»",
      (sel.tests, sel.sin_tests), (["test_reglas_claude.py"], []))
    c("un ayudante: los que lo importan, de las dos formas, y no su área",
      e(["tests/_falso.py"]).tests, ["test_lejos.py", "test_llave.py"])

    sel = e(["tests/_harness.py"])
    c("_harness: todo lo que no abre ventana",
      (sel.tests, sel.motivos),
      (SIN_VENTANA, ["todo lo que no abre ventana ← tests/_harness.py lo importan todos"]))
    c("common/__init__.py: todo", e(["common/__init__.py"]).tests, SIN_VENTANA)

    sel = e(["LICENSE"])
    c("un fichero sin regla: ningún test, y se dice", (sel.tests, sel.sin_tests), ([], ["LICENSE"]))
    sel = e(["config.example.toml"])
    c("un fichero sin regla que un test nombra en su código: ese test, y no «sin tests» "
      "(citarlo en un comentario o un docstring no cuenta)",
      (sel.tests, sel.sin_tests), (["test_lejos.py"], []))
    c("un ayudante que un test lanza por su nombre: ese test",
      e(["tests/_runtime.py"]).tests, ["test_motor.py"])
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
sel = _seleccion.elegir(["sync.py"], gui=set(run_all.GUI), ventanas=False)
c("de verdad: sync.py elige los tests de los frenos, que lo importan aunque sean de otra área",
  sorted({"test_forzar.py", "test_frenos.py"} - set(sel.tests)), [])
NOMBRADOS = {".github/workflows/maquina-real.yml": "test_maquina_real_yml.py",
             "sync_config.example.toml": "test_flags_editor.py",
             "tests/_runtime_ci.py": "test_build_installer.py"}
"""Ficheros que un test lee o lanza por su nombre, y ese test."""
c("de verdad: un fichero que un test nombra elige ese test",
  sorted(ruta for ruta, test in NOMBRADOS.items()
         if test not in _seleccion.elegir([ruta], gui=set(run_all.GUI), ventanas=False).tests), [])

CONSTANTE = {"sync.py": "model.SYNC_PY", "runsync.py": "model.RUNSYNC_PY",
             "penwatch.py": "model.PENWATCH_PY"}
"""La constante de `model` con la que se lanza cada script, si la tiene."""


def texto(rel: str) -> str:
    """El contenido de un fichero del repositorio de verdad."""
    return (REPO / rel).read_text(encoding="utf-8")


def borrar_repo(raiz: Path) -> None:
    """Borra un repositorio git temporal.

    Git deja los ficheros de `.git/objects` de solo lectura, y en Windows `rmtree()`
    no puede borrarlos: sin quitarles la marca, el temporal se quedaría para siempre.
    """
    for ruta in raiz.rglob("*"):
        try:
            if ruta.is_file():  # una carpeta sin S_IEXEC no se podría recorrer en POSIX
                os.chmod(ruta, stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            pass
    shutil.rmtree(raiz, ignore_errors=True)


c("LANZADO_POR: cada script y cada lanzador existen",
  sorted(r for s, gs in _seleccion.LANZADO_POR.items() for r in (s, *gs) if not (REPO / r).is_file()), [])
c("LANZADO_POR: cada lanzador nombra el script (entre comillas o por su constante de model)",
  [(s, g) for s, gs in _seleccion.LANZADO_POR.items() for g in gs
   if f'"{s}"' not in texto(g) and (s not in CONSTANTE or CONSTANTE[s] not in texto(g))], [])

# cambiados(), con un git de verdad sobre un repositorio temporal.
if shutil.which("git") is None:
    print("  (saltado) sin git en este equipo")
else:
    G = tmpdir("prdrive-git-")

    def git(*args: str) -> None:
        """Una orden de git en el repositorio temporal, con autor de mentira."""
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=G,
                       check=True, capture_output=True, stdin=subprocess.DEVNULL)

    def escribir(nombre: str, texto: str) -> None:
        """Escribe un fichero del repositorio temporal."""
        (G / nombre).write_text(texto, encoding="utf-8")

    git("init", "-q", "-b", "main")
    for nombre in ("a.txt", "b.py", "c.py"):
        escribir(nombre, nombre)
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    git("checkout", "-q", "-b", "rama")
    escribir("b.py", "cambiado")
    git("mv", "c.py", "d.py")
    git("commit", "-q", "-am", "rama")
    escribir("a.txt", "sin preparar")
    escribir("e.txt", "preparado")
    git("add", "e.txt")
    escribir("ñandú x.txt", "nuevo")
    otra = tmpdir("prdrive-cwd-")
    antes = os.getcwd()
    os.chdir(otra)  # cambiados() no depende de dónde se esté
    try:
        c("cambiados: lo de la rama, lo preparado, lo modificado y lo nuevo; un renombrado por sus "
          "dos nombres; con tildes y espacios",
          _seleccion.cambiados(G), ["a.txt", "b.py", "c.py", "d.py", "e.txt", "ñandú x.txt"])
        git("update-ref", "refs/remotes/origin/main", "HEAD")
        c("cambiados: origin/main manda sobre main",
          _seleccion.cambiados(G), ["a.txt", "e.txt", "ñandú x.txt"])
        c("cambiados: fuera de un repositorio, None", _seleccion.cambiados(otra), None)
    finally:
        os.chdir(antes)
        borrar_repo(G)
    c("el repositorio temporal se borra entero (git deja sus objetos de solo lectura)", G.exists(), False)

sys.exit(c.report())
