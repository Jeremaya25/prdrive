"""Qué tests corre una pasada según lo que ha cambiado.

El mapa de áreas es el de `.claude/rules/*.md`: los `paths` de cada regla nombran
los fuentes de su área y sus tests. `run_all.py --cambios` y `--area` lo usan para
elegir; `tests/test_reglas_claude.py` vigila que todo fuente y todo test estén en
alguna regla.

Es puro: no importa `_harness` ni el proyecto ni Tk, e importarlo no hace nada.
Todo el trabajo (leer reglas, preguntar a git) ocurre al llamar a sus funciones.
"""

from __future__ import annotations

import ast
import fnmatch
import re
import subprocess
from dataclasses import dataclass
from glob import glob
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
"""La raíz del repositorio: la carpeta de `tests/`."""

CABECERA = re.compile(r'\A---\npaths:\n((?:  - "[^"\n]+"\n)+)---\n(\S.*)\Z', re.S)
"""La única cabecera admitida: `paths` como lista, cada patrón entre comillas."""

FUENTES = ("*.py", "common/*.py", "ui/*.py", "install/*.py")
"""Los patrones de los fuentes del proyecto, relativos a la raíz."""

LANZADO_POR: dict[str, tuple[str, ...]] = {
    "sync.py": ("runsync.py", "ui/tk.py", "ui/console.py", "common/llavero.py", "agente.py"),
    "runsync.py": ("penwatch.py", "agente.py", "common/keepassxc.py", "common/llavero.py",
                   "common/update.py"),
    "penwatch.py": ("ui/watch.py",),
    "pregunta.py": ("agente.py",),
    "agente.py": ("install/agente.py",),
}
"""Los scripts que se lanzan como proceso, y los fuentes que los lanzan.

Nadie los importa, así que el grafo de imports no ve a quien depende de ellos.
`tests/test_seleccion.py` comprueba que cada lanzador nombra de verdad su script.
"""

TODOS = frozenset({"common/__init__.py", "tests/_harness.py"})
"""Lo que importan todos los tests: cambiarlo elige todo lo que no abre ventana."""

_TEST = re.compile(r"tests/test_[^/]+\.py")
_AYUDANTE = re.compile(r"tests/_[^/]+\.py")


@dataclass
class Seleccion:
    """Los tests que corre una pasada, y por qué.

    Args:
        tests: Los ficheros (`test_x.py`) que se corren, ordenados.
        motivos: Una línea por área o por test elegido, «quién ← por qué», en el
            orden en que aparecieron.
        fuera: Los tests de ventanas que se eligieron pero no se corren, ordenados.
        sin_tests: Los ficheros cambiados que no aportan ningún test, en su orden.
    """

    tests: list[str]
    motivos: list[str]
    fuera: list[str]
    sin_tests: list[str]


def leer_regla(regla: Path) -> tuple[list[str], str] | None:
    """Lee una regla.

    Returns:
        `(patrones, cuerpo)`, o `None` si la cabecera no tiene la forma admitida.
    """
    m = CABECERA.match(regla.read_text(encoding="utf-8"))
    if m is None:
        return None
    return re.findall(r'"([^"\n]+)"', m.group(1)), m.group(2)


def areas(repo: Path = REPO) -> dict[str, list[str]]:
    """Las áreas del repositorio: cada regla con sus patrones.

    Args:
        repo: La raíz del repositorio.

    Returns:
        El nombre de cada regla (su fichero sin `.md`) y sus patrones. Una regla
        cuya cabecera no se puede leer no está: `test_reglas_claude.py` la señala.
    """
    mapa: dict[str, list[str]] = {}
    for regla in sorted((repo / ".claude" / "rules").glob("*.md")):
        leida = leer_regla(regla)
        if leida is not None:
            mapa[regla.stem] = leida[0]
    return mapa


def areas_de(ruta: str, mapa: dict[str, list[str]]) -> set[str]:
    """Las áreas que cubren una ruta.

    Se compara con `fnmatch`, no con lo que hay en disco: un fichero borrado en la
    rama sigue perteneciendo al área de su patrón.

    Args:
        ruta: Relativa a la raíz, con `/`.
        mapa: Lo que devuelve `areas()`.
    """
    return {area for area, patrones in mapa.items()
            if any(fnmatch.fnmatchcase(ruta, p) for p in patrones)}


def fuentes(repo: Path = REPO) -> list[str]:
    """Los fuentes del proyecto (`FUENTES`), ordenados, relativos a la raíz y con `/`."""
    return sorted({Path(f).as_posix() for patron in FUENTES for f in glob(patron, root_dir=repo)})


def _git(repo: Path, *args: str) -> str | None:
    """La salida de una orden de git en `repo`, o `None` si git no está o la orden falla."""
    try:
        r = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=repo,
                           stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8",
                           errors="replace")
    except OSError:
        return None
    return r.stdout if r.returncode == 0 else None


def cambiados(repo: Path = REPO) -> list[str] | None:
    """Los ficheros que esta rama cambia respecto a `main`, según git.

    Punto de sustitución: los tests lo cambian por una lista fija. La base es la
    común con `origin/main` o, sin ella, con `main`. Cuenta lo confirmado en la
    rama, lo preparado, lo modificado sin preparar y lo nuevo sin seguimiento; un
    renombrado, por sus dos nombres. Git corre siempre en `repo`, se llame desde
    donde se llame.

    Args:
        repo: La raíz del repositorio.

    Returns:
        Las rutas relativas a la raíz, con `/`, ordenadas y sin repetir; o `None`
        si no hay git, no es un repositorio o no hay base común con ninguna de las
        dos ramas.
    """
    base = None
    for rama in ("origin/main", "main"):
        salida = _git(repo, "merge-base", "HEAD", rama)
        if salida is not None and salida.strip():
            base = salida.strip()
            break
    if base is None:
        return None
    diferencias = _git(repo, "diff", "--name-only", "--no-renames", base)
    nuevos = _git(repo, "ls-files", "--others", "--exclude-standard")
    if diferencias is None or nuevos is None:
        return None
    return sorted({linea for linea in (diferencias + nuevos).splitlines() if linea})


def _modulo(rel: str) -> str:
    """El nombre de módulo de un fuente: `common/x.py` es `common.x`; `common/__init__.py`, `common`."""
    partes = rel[:-len(".py")].split("/")
    if partes[-1] == "__init__":
        partes.pop()
    return ".".join(partes)


def _importados(nodo: ast.AST, paquete: str, modulos: dict[str, str]) -> list[str]:
    """Los módulos del proyecto que trae un `import` o un `from … import`.

    Args:
        nodo: Cualquier nodo; los que no son un import no traen nada.
        paquete: El paquete del fichero que importa, para los imports relativos.
        modulos: Nombre de módulo → fuente, de todo el proyecto.

    Returns:
        Los nombres de módulo que están en `modulos`. `from a import b` trae
        `a.b` si es un módulo, y si no `a` (un nombre de su `__init__.py`).
    """
    if isinstance(nodo, ast.Import):
        return [a.name for a in nodo.names if a.name in modulos]
    if not isinstance(nodo, ast.ImportFrom):
        return []
    if nodo.level:
        partes = paquete.split(".") if paquete else []
        partes = partes[:len(partes) - (nodo.level - 1)]
        base = ".".join(partes + ([nodo.module] if nodo.module else []))
    else:
        base = nodo.module or ""
    traidos = []
    for alias in nodo.names:
        completo = f"{base}.{alias.name}" if base else alias.name
        nombre = completo if completo in modulos else base
        if nombre in modulos:
            traidos.append(nombre)
    return traidos


def importadores(repo: Path = REPO) -> dict[str, set[str]]:
    """Quién importa a quién entre los fuentes del proyecto, a un salto.

    Cuenta todo import del fichero, también los de dentro de una función (aquí lo
    normal: los módulos pesados se importan donde se usan) y los relativos.

    Args:
        repo: La raíz del repositorio.

    Returns:
        Para cada fuente importado, los fuentes que lo importan directamente.
        Un fuente que no se puede leer o compilar no importa nada.
    """
    lista = fuentes(repo)
    modulos = {_modulo(f): f for f in lista}
    inversa: dict[str, set[str]] = {}
    for fichero in lista:
        try:
            arbol = ast.parse((repo / fichero).read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            continue
        modulo = _modulo(fichero)
        paquete = modulo if fichero.endswith("__init__.py") else modulo.rpartition(".")[0]
        for nodo in ast.walk(arbol):
            for nombre in _importados(nodo, paquete, modulos):
                destino = modulos[nombre]
                if destino != fichero:
                    inversa.setdefault(destino, set()).add(fichero)
    return inversa


class _Eleccion:
    """Lo que se va eligiendo: áreas y tests sueltos, cada uno con su primer motivo."""

    def __init__(self, mapa: dict[str, list[str]]) -> None:
        self.mapa = mapa
        self.areas: set[str] = set()
        self.tests: set[str] = set()
        self.motivos: list[str] = []
        self._inversa: dict[str, set[str]] | None = None

    def area(self, area: str, porque: str) -> None:
        """Elige un área, si no lo estaba, con su motivo."""
        if area not in self.areas:
            self.areas.add(area)
            self.motivos.append(f"{area} ← {porque}")

    def test(self, nombre: str, porque: str) -> None:
        """Elige un test por su nombre, si no lo estaba, con su motivo."""
        if nombre not in self.tests:
            self.tests.add(nombre)
            self.motivos.append(f"{nombre} ← {porque}")

    def dependientes(self, ruta: str, repo: Path) -> bool:
        """Elige las áreas de quien importa o lanza `ruta`, a un salto.

        Returns:
            Si había alguna.
        """
        if self._inversa is None:
            self._inversa = importadores(repo)
        hay = False
        for quien, verbo in ([(g, "importa") for g in sorted(self._inversa.get(ruta, ()))]
                             + [(g, "lanza") for g in LANZADO_POR.get(ruta, ())]):
            for area in sorted(areas_de(quien, self.mapa)):
                self.area(area, f"{quien} {verbo} {ruta}")
                hay = True
        return hay


def _tests(repo: Path) -> list[str]:
    """Los `tests/test_*.py` que existen, por nombre de fichero, ordenados."""
    return sorted(p.name for p in (repo / "tests").glob("test_*.py"))


def _resultado(eleccion: _Eleccion, sin_tests: list[str], *, gui: set[str], ventanas: bool,
               repo: Path) -> Seleccion:
    """Convierte lo elegido en la `Seleccion`: los tests de sus áreas y los sueltos."""
    elegidos = set(eleccion.tests) | {t for t in _tests(repo)
                                      if areas_de(f"tests/{t}", eleccion.mapa) & eleccion.areas}
    fuera = [] if ventanas else sorted(elegidos & gui)
    return Seleccion(sorted(elegidos - set(fuera)), eleccion.motivos, fuera, sin_tests)


def _todo(razon: str, *, gui: set[str], ventanas: bool, repo: Path) -> Seleccion:
    """Todos los tests (los de ventanas, solo con `ventanas`), con una sola línea de motivo."""
    todos = set(_tests(repo))
    fuera = [] if ventanas else sorted(todos & gui)
    que = "todo" if ventanas else "todo lo que no abre ventana"
    return Seleccion(sorted(todos - set(fuera)), [f"{que} ← {razon}"], fuera, [])


def elegir(cambios: list[str] | None, *, gui: set[str], ventanas: bool,
           repo: Path = REPO) -> Seleccion:
    """Los tests que corren por unos cambios.

    Cada fichero cambiado elige, según lo que es:

    - un `tests/test_*.py` que existe: ese test;
    - un ayudante `tests/_*.py`: los tests que lo importan (no su área: la regla
      que lo cubre decide su doc, no sus tests);
    - `TODOS`: todos los tests;
    - cualquier otro: sus áreas, más las de los fuentes que lo importan o lo lanzan
      (`LANZADO_POR`), a un salto. Un test borrado cae aquí, por su patrón.

    Args:
        cambios: Las rutas cambiadas, relativas a la raíz y con `/`; `None` si no
            se sabe qué cambió (`cambiados()` sin git).
        gui: Los tests que abren ventanas (`run_all.GUI`).
        ventanas: Si los de `gui` también se corren.
        repo: La raíz del repositorio.

    Returns:
        La selección. Sin saber qué cambió, todos los tests. Sin cambios, una vacía.
    """
    if cambios is None:
        return _todo("no se sabe qué cambió (sin git o sin base común con main)",
                     gui=gui, ventanas=ventanas, repo=repo)
    eleccion = _Eleccion(areas(repo))
    existentes = set(_tests(repo))
    sin_tests: list[str] = []
    for ruta in cambios:
        if ruta in TODOS:
            return _todo(f"{ruta} lo importan todos", gui=gui, ventanas=ventanas, repo=repo)
        nombre = ruta.rpartition("/")[2]
        if _TEST.fullmatch(ruta) and nombre in existentes:
            eleccion.test(nombre, ruta)
            continue
        if _AYUDANTE.fullmatch(ruta):
            importan = _importan(Path(nombre).stem, sorted(existentes), repo)
            for test in importan:
                eleccion.test(test, f"importa {ruta}")
            if not importan:
                sin_tests.append(ruta)
            continue
        directas = sorted(areas_de(ruta, eleccion.mapa))
        for area in directas:
            eleccion.area(area, ruta)
        if not eleccion.dependientes(ruta, repo) and not directas:
            sin_tests.append(ruta)
    return _resultado(eleccion, sin_tests, gui=gui, ventanas=ventanas, repo=repo)


def _importan(modulo: str, tests: list[str], repo: Path) -> list[str]:
    """Los tests que importan el ayudante `modulo` (`import _x` o `from _x import …`)."""
    patron = re.compile(rf"^\s*(?:import|from)\s+{re.escape(modulo)}\b", re.M)
    return [t for t in tests
            if patron.search((repo / "tests" / t).read_text(encoding="utf-8", errors="replace"))]


def por_areas(nombres: list[str], *, gui: set[str], ventanas: bool,
              repo: Path = REPO) -> Seleccion:
    """Los tests de unas áreas pedidas por su nombre, y de las que dependen de ellas.

    Dependen las áreas de los fuentes que importan o lanzan algún fuente de las
    pedidas, a un salto: la misma expansión que `elegir()`.

    Args:
        nombres: Los nombres de área (de regla), como `engine`.
        gui: Ver `elegir()`.
        ventanas: Ver `elegir()`.
        repo: La raíz del repositorio.

    Raises:
        ValueError: Si algún nombre no es una regla; su argumento es la lista de
            los que no lo son.
    """
    mapa = areas(repo)
    desconocidas = [n for n in nombres if n not in mapa]
    if desconocidas:
        raise ValueError(desconocidas)
    eleccion = _Eleccion(mapa)
    for nombre in nombres:
        eleccion.area(nombre, "pedida")
    pedidas = set(nombres)
    for fuente in fuentes(repo):
        if areas_de(fuente, mapa) & pedidas:
            eleccion.dependientes(fuente, repo)
    return _resultado(eleccion, [], gui=gui, ventanas=ventanas, repo=repo)
