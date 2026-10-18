"""Qué tests corre una pasada según lo que ha cambiado.

El mapa de áreas es el de `.claude/rules/*.md`: los `paths` de cada regla nombran
los fuentes de su área y sus tests. `run_all.py --cambios` y `--area` lo usan para
elegir; `tests/test_reglas_claude.py` vigila que todo fuente y todo test estén en
alguna regla.

Es puro: no importa `_harness` ni el proyecto ni Tk, e importarlo no hace nada.
Todo el trabajo (leer reglas, preguntar a git) ocurre al llamar a sus funciones.
"""

from __future__ import annotations

import fnmatch
import re
from glob import glob
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
"""La raíz del repositorio: la carpeta de `tests/`."""

CABECERA = re.compile(r'\A---\npaths:\n((?:  - "[^"\n]+"\n)+)---\n(\S.*)\Z', re.S)
"""La única cabecera admitida: `paths` como lista, cada patrón entre comillas."""

FUENTES = ("*.py", "common/*.py", "ui/*.py", "install/*.py")
"""Los patrones de los fuentes del proyecto, relativos a la raíz."""


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
