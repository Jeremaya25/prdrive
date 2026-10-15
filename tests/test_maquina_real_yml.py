#!/usr/bin/env python3
"""`maquina-real.yml`: F21 no falla tarde y confuso, y F3 no tumba lo demás.

El trabajo `pyc-windows` baja el artefacto `f21-arbol` que sube `pyc-linux`. Si el
paso que lo sube no encuentra nada (la prueba sale `saltada` con rc 0),
`upload-artifact` solo avisa por defecto, y el fallo aparece después, en la
descarga de `pyc-windows`, sin decir por qué. Por eso ese paso tiene
`if-no-files-found: error`.

El paso que baja el rclone fijado para F3 es el contrario: si la descarga falla
no puede tumbar la matriz entera (ninguna otra fila lo necesita), así que lleva
`continue-on-error: true` y F3 sale «saltada»; y solo se baja si se pide F3 o
«todas». El aviso es de F3, no del trabajo.

No hay YAML en la biblioteca estándar: se mira el texto de cada paso. Un paso
empieza en `      - ` (seis espacios y un guion).
"""

from __future__ import annotations

import sys

from _harness import Checks, REPO

ARCHIVO = REPO / ".github" / "workflows" / "maquina-real.yml"
ARTEFACTO = "f21-arbol"
PASO_RCLONE = "- name: El rclone fijado"


def pasos(lineas: list[str]) -> list[list[str]]:
    """Cada paso del fichero, como sus líneas sin la sangría."""
    inicios = [i for i, linea in enumerate(lineas) if linea.startswith("      - ")]
    fines = inicios[1:] + [len(lineas)]
    return [[linea.strip() for linea in lineas[i:fin]] for i, fin in zip(inicios, fines)]


def main() -> int:
    """Comprueba el paso que sube `f21-arbol` y el que baja el rclone de F3."""
    checks = Checks("maquina-real.yml: F21 falla donde se rompe, y F3 no tumba lo demás")
    lineas = ARCHIVO.read_text(encoding="utf-8").splitlines()
    subidas = [p for p in pasos(lineas)
               if any(linea.startswith("- uses: actions/upload-artifact@") for linea in p)
               and f"name: {ARTEFACTO}" in p]
    checks(f"el artefacto {ARTEFACTO} lo sube un paso upload-artifact", len(subidas), 1)
    if subidas:
        checks("ese paso falla si no encuentra ficheros (y no solo avisa)",
               "if-no-files-found: error" in subidas[0], True)

    rclone = [p for p in pasos(lineas) if PASO_RCLONE in p]
    checks("F3: un solo paso baja el rclone fijado", len(rclone), 1)
    if rclone:
        checks("  una descarga fallida no tumba las demás filas (F3 sale «saltada»)",
               "continue-on-error: true" in rclone[0], True)
        condicion = [linea for linea in rclone[0] if linea.startswith("if:")]
        checks("  y solo se baja si se pide F3 o «todas»",
               len(condicion) == 1 and "F3" in condicion[0] and "todas" in condicion[0], True)
    return checks.report()


if __name__ == "__main__":
    sys.exit(main())
