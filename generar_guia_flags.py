#!/usr/bin/env python3
"""Regenera `docs/guia/flags-de-rclone.md`: la guía de flags de rclone para quien no abre el programa.

La página es `ui.flags_guia.a_markdown()`, la misma información que enseña la ventana
«Guía de flags…» del editor de flags de una pareja. Hay que volver a correrlo cada vez que
cambia el catálogo explicado (`ui/flags_catalogo.py`), el modelo de los flags (`common/model.py`)
o los datos de la rclone fijada (`common/flags_rclone.json`, que se regenera con
`generar_flags_rclone.py`); `tests/test_flags_guia.py` falla mientras la página no sea
exactamente lo que genera el catálogo:

    python generar_guia_flags.py                # escribe la página
    python generar_guia_flags.py --comprobar    # no escribe: sale con 1 si está desfasada

Solo biblioteca estándar y sin red.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
SALIDA = REPO / "docs" / "guia" / "flags-de-rclone.md"
"""La página que se escribe."""


def main(argv: list[str] | None = None) -> int:
    """Escribe la página, o con `--comprobar` dice si está al día. Devuelve el código de salida."""
    sys.path.insert(0, str(REPO))
    from ui import flags_guia

    parser = argparse.ArgumentParser(description="Regenera docs/guia/flags-de-rclone.md "
                                                 "desde el catálogo de la guía de flags.")
    parser.add_argument("--comprobar", action="store_true",
                        help="no escribe nada: sale con 1 si la página no está al día")
    parser.add_argument("--salida", type=Path, default=SALIDA, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    texto = flags_guia.a_markdown()
    try:
        antes = args.salida.read_text(encoding="utf-8")
    except OSError:
        antes = None
    if args.comprobar:
        if antes == texto:
            print(f"{args.salida}: al día")
            return 0
        print(f"{args.salida}: desfasada; corre python generar_guia_flags.py", file=sys.stderr)
        return 1
    if antes != texto:
        args.salida.write_text(texto, encoding="utf-8", newline="\n")
    print(f"{args.salida}: {len(texto.splitlines())} líneas"
          + ("" if antes != texto else " (sin cambios)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
