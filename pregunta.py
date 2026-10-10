#!/usr/bin/env python3
"""La ventanita «¿Atender esta unidad?» del agente, sin cargar el agente.

Hace lo que `agente.py pregunta` (`cmd_pregunta()`), pero en un guion de verdad
pequeño: `agente.py` es un script de miles de líneas que Python recompila en
cada uso y que arrastra todo el agente, y esta ventana es un proceso hijo que
se abre cada vez que se enchufa una unidad desconocida.

    pregunta.py --nombre NOMBRE --segundos N [--cambiada]

Sale con el código de `ui.tk_agente.main()`: 0 «Atender», 1 «Ahora no» (también
si se cierra o se acaba la cuenta atrás) y 2 si no se ha podido abrir (sin Tk,
sin pantalla, o argumentos que no son esos). Cualquier otro fallo sale con 1,
que el agente cuenta como «Ahora no»: nunca como un sí.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# `ui` antes que `tkinter`: su `__init__` carga el Tk con Xft del runtime, que ha de ir primero.
import ui  # noqa: E402
from ui import tk_agente  # noqa: E402


def leer(argv: list[str]) -> tuple[str, int, bool] | None:
    """Devuelve `(nombre, segundos, cambiada)` de la línea de órdenes, o `None` si no cuadra."""
    try:
        return (argv[argv.index("--nombre") + 1], int(argv[argv.index("--segundos") + 1]),
                "--cambiada" in argv)
    except (IndexError, ValueError):
        return None


if __name__ == "__main__":
    # La medida (`PRDRIVE_PERF`) la anota en el diario del equipo, como `apply-agente`.
    ui.perf_quien = "agente"
    datos = leer(sys.argv[1:])
    raise SystemExit(tk_agente.SIN_VENTANA if datos is None else tk_agente.main(*datos))
