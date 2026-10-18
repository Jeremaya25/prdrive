#!/usr/bin/env python3
"""Las reglas de Claude Code y el mapa de docs de AGENTS.md no se desvían.

Cada doc de `docs/agents/reference/` tiene su regla en `.claude/rules/`: Claude
Code inyecta su cuerpo (una línea que remite al doc) cuando lee o edita uno de
los ficheros de `paths`, en vez de cargar el doc en todas las sesiones. Esto
vigila lo que fallaría sin hacer ruido:

- Una cabecera que el YAML no puede leer deja la regla sin `paths`, y una regla
  sin `paths` se carga al arrancar en todas las sesiones, que es justo lo que se
  quiso evitar. Por eso la cabecera solo admite una forma.
- Un patrón que ya no encaja con ningún fichero (un módulo renombrado) deja la
  regla muerta, y un módulo nuevo sin regla no avisa a nadie de su doc.
- Un `@ruta` suelto en AGENTS.md se expande al arrancar y cargaría el doc entero.
- Un test que no está en los `paths` de ninguna regla no tiene área, y
  `run_all.py --cambios` no lo elegiría nunca.
"""

import re
import sys
from glob import glob
from pathlib import Path

from _harness import REPO, Checks
from _seleccion import areas, areas_de, fuentes, leer_regla

c = Checks("reglas de Claude Code y mapa de docs de AGENTS.md")

REGLAS = REPO / ".claude" / "rules"
DOCS = REPO / "docs" / "agents" / "reference"

SIN_REGLA = {"common/__init__.py"}
"""Módulos que no necesitan regla: el paquete `common` no tiene contenido."""

MAX_CUERPO = 800
"""Caracteres que puede tener el cuerpo de una regla.

Se inyecta entero cada vez que Claude Code toca uno de sus ficheros: es un
puntero al doc, no el doc.
"""


def ficheros(patron: str) -> list[str]:
    """Los ficheros del repositorio que encajan con `patron`, con `/` de separador."""
    return sorted(Path(f).as_posix() for f in glob(patron, root_dir=REPO, recursive=True))


docs = {p.stem for p in DOCS.glob("*.md")}
reglas = {p.stem: p for p in REGLAS.glob("*.md")}

c("cada doc de reference tiene su regla", sorted(docs - set(reglas)), [])
c("y cada regla tiene su doc (salvo la de la documentación)",
  sorted(set(reglas) - docs - {"docs-maintenance"}), [])

cubiertos: set[str] = set()
for nombre, ruta in sorted(reglas.items()):
    leida = leer_regla(ruta)
    if not c(f"{nombre}: la cabecera tiene la única forma admitida", leida is not None, True):
        continue
    patrones, cuerpo = leida
    c(f"{nombre}: todos sus patrones encajan con algún fichero",
      [p for p in patrones if not ficheros(p)], [])
    c(f"{nombre}: el cuerpo es un puntero corto", len(cuerpo) <= MAX_CUERPO, True)
    if nombre in docs:
        c(f"{nombre}: remite a su doc", f"docs/agents/reference/{nombre}.md" in cuerpo, True)
    cubiertos.update(f for p in patrones for f in ficheros(p))

fuente = set(fuentes())
c("todo módulo del proyecto está en alguna regla", sorted(fuente - cubiertos - SIN_REGLA), [])

mapa = areas()
c("todo test está en los paths de alguna regla (decide qué corre run_all.py --cambios)",
  sorted(p.name for p in (REPO / "tests").glob("test_*.py")
         if not areas_de(f"tests/{p.name}", mapa)), [])

agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
tabla = set(re.findall(r"^\| `([\w-]+)\.md` \|", agents, re.M))
c("AGENTS.md lista cada doc de reference", sorted(docs - tabla), [])
c("y no lista ninguno que no exista", sorted(tabla - docs), [])

sin_codigo = re.sub(r"`[^`\n]*`", "", re.sub(r"```.*?```", "", agents, flags=re.S))
c("AGENTS.md no importa nada con @ruta (se expandiría al arrancar)",
  re.findall(r"(?<![\w@`])@[\w./~-]+", sin_codigo), [])

sys.exit(c.report())
