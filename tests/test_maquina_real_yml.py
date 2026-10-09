#!/usr/bin/env python3
"""`maquina-real.yml`: F21 no falla tarde y confuso.

El trabajo `pyc-windows` baja el artefacto `f21-arbol` que sube `pyc-linux`. Si el
paso que lo sube no encuentra nada (la prueba sale `saltada` con rc 0),
`upload-artifact` solo avisa por defecto, y el fallo aparece después, en la
descarga de `pyc-windows`, sin decir por qué. Por eso ese paso tiene
`if-no-files-found: error`.

No hay YAML en la biblioteca estándar: se mira el texto de cada paso. Un paso
empieza en `      - ` (seis espacios y un guion).
"""

from __future__ import annotations

import sys

from _harness import Checks, REPO

ARCHIVO = REPO / ".github" / "workflows" / "maquina-real.yml"
ARTEFACTO = "f21-arbol"


def pasos(lineas: list[str]) -> list[list[str]]:
    """Cada paso del fichero, como sus líneas sin la sangría."""
    inicios = [i for i, linea in enumerate(lineas) if linea.startswith("      - ")]
    fines = inicios[1:] + [len(lineas)]
    return [[linea.strip() for linea in lineas[i:fin]] for i, fin in zip(inicios, fines)]


def main() -> int:
    """Comprueba que el paso que sube `f21-arbol` falla si no encuentra ficheros."""
    checks = Checks("maquina-real.yml: el artefacto de F21 falla donde se rompe")
    lineas = ARCHIVO.read_text(encoding="utf-8").splitlines()
    subidas = [p for p in pasos(lineas)
               if "- uses: actions/upload-artifact@v4" in p and f"name: {ARTEFACTO}" in p]
    checks(f"el artefacto {ARTEFACTO} lo sube un paso upload-artifact", len(subidas), 1)
    if subidas:
        checks("ese paso falla si no encuentra ficheros (y no solo avisa)",
               "if-no-files-found: error" in subidas[0], True)
    return checks.report()


if __name__ == "__main__":
    sys.exit(main())
