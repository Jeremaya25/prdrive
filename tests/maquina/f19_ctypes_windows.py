"""F19: las comprobaciones de Windows de verdad de tests/test_avisos_carpeta.py."""

import sys

import comun

CODIGO = "F19"
SISTEMA = "W"
QUE = "tests/test_avisos_carpeta.py en Windows, con su parte de ReadDirectoryChangesW de verdad"


def probar(p: comun.Prueba) -> None:
    """Corre el script de tests y mira que la parte de Windows de verdad no se salte."""
    r = comun.ejecutar([sys.executable, str(comun.REPO / "tests" / "test_avisos_carpeta.py")],
                       timeout=600)
    p.ver("tests/test_avisos_carpeta.py pasa", r.returncode, 0)
    p.ver("  con su parte de Windows de verdad (no saltada)",
          "(saltado) ReadDirectoryChangesW de verdad" in (r.stdout or ""), False)
