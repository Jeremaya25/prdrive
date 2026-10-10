#!/usr/bin/env python3
"""La compilación del instalador: el PyInstaller fijado y el Tk del `.exe`.

El `.exe` lleva el Python (y el Tk) de quien lo compila, y Tk 9 es el único Tk
que se admite. Por eso la compilación es estricta en todas partes (decisión del
dueño, 09/10/2026): las releases se compilan con el Python fijado del
dispositivo (3.14.8, Tk 9: el pintor SVG) y un PyInstaller fijado, y quien
compile en local tiene que hacer lo mismo. Lo que se prueba aquí:

- `comprobar_tk()` y `comprobar_pyinstaller()` paran la compilación con
  `SystemExit`, y el error dice qué hay, qué se quiere y cómo conseguirlo.
- Que `main()` los mire antes de escribir el perfil, sin ninguna forma de
  saltárselos (ni una opción, ni estar fuera de GitHub Actions).
- Que `DATOS_FICHEROS` sigue llevando lo que el instalador copia.
- Que `tests/_runtime_ci.py compilador` no prepara un Python que no sea de
  Windows: el `.exe` de las releases solo es de Windows.

No compila nada ni toca la red. `comprobar_tk()` mira el Tk del intérprete que
corre el test: el 9 en la pata de la CI y, si alguien lo corre con otro, el 8.6.
"""

import contextlib
import io
import os
import subprocess
import sys
import types

from _harness import REPO, Checks, tmpdir

import build_installer as b
from common import pins
from install import agente, deploy

c = Checks("compilar el instalador: PyInstaller fijado y Tk 9")


def salida_de(funcion, *args):
    """Llama a `funcion` y devuelve `(resultado, lo impreso, mensaje del SystemExit)`."""
    impreso = io.StringIO()
    resultado, parada = None, None
    with contextlib.redirect_stdout(impreso):
        try:
            resultado = funcion(*args)
        except SystemExit as e:
            parada = str(e.code)
    return resultado, impreso.getvalue(), parada


# El pin
partes = b.PYINSTALLER.split(".")
c("PYINSTALLER es una versión exacta X.Y.Z",
  len(partes) == 3 and all(p.isdigit() for p in partes), True)
c("  y al menos 6.22 (la que pide la especificación)",
  tuple(int(p) for p in partes) >= (6, 22, 0), True)
c("TK_MINIMO es Tk 9.0", b.TK_MINIMO, (9, 0))

# comprobar_pyinstaller(), con un PyInstaller de mentira en sys.modules
REAL = sys.modules.get("PyInstaller")


def con_pyinstaller(version):
    """Pone un módulo `PyInstaller` de esa versión, o ninguno con `None`."""
    if version is None:
        sys.modules["PyInstaller"] = None            # el import falla
        return
    falso = types.ModuleType("PyInstaller")
    falso.__version__ = version
    sys.modules["PyInstaller"] = falso


try:
    con_pyinstaller(b.PYINSTALLER)
    version, impreso, parada = salida_de(b.comprobar_pyinstaller)
    c("el fijado pasa y da su versión", (version, parada), (b.PYINSTALLER, None))
    c("  sin avisar de nada", impreso, "")

    con_pyinstaller("6.11.1")
    version, impreso, parada = salida_de(b.comprobar_pyinstaller)
    c("otro para la compilación", (version, parada is not None), (None, True))
    c.contains("  diciendo cuál hay", parada or "", "6.11.1")
    c.contains("  y cuál se quiere", parada or "", b.PYINSTALLER)
    c.contains("  y cómo ponerlo", parada or "",
               f"python -m pip install pyinstaller=={b.PYINSTALLER}")

    con_pyinstaller(None)
    _, _, parada = salida_de(b.comprobar_pyinstaller)
    c("sin PyInstaller también para", parada is not None, True)
    c.contains("  y dice cómo ponerlo", parada or "",
               f"python -m pip install pyinstaller=={b.PYINSTALLER}")
finally:
    if REAL is None:
        sys.modules.pop("PyInstaller", None)
    else:
        sys.modules["PyInstaller"] = REAL

# comprobar_tk(): el Tk del intérprete que compila es el que lleva el .exe
try:
    import tkinter
    TK9 = tkinter.TkVersion >= 9
    NIVEL = tkinter.Tcl().eval("info patchlevel")
except Exception as e:                                   # noqa: BLE001
    TK9, NIVEL = None, ""
    print(f"  (saltado) este Python no carga Tcl/Tk: {e}")

if TK9:
    nivel, impreso, parada = salida_de(b.comprobar_tk)
    c("con Tk 9 pasa y da su versión", (nivel, parada), (pins.TK_XFT_VERSION, None))
    c("  sin avisar de nada", impreso, "")


def con_tk(version: float, nivel: str):
    """Pone un `tkinter` de mentira con esa `TkVersion` y ese `info patchlevel`."""
    falso = types.ModuleType("tkinter")
    falso.TkVersion = version
    falso.Tcl = lambda: types.SimpleNamespace(eval=lambda _orden: nivel)
    sys.modules["tkinter"] = falso


tk_real = sys.modules.get("tkinter", False)
try:
    # El Tk 8.6 de otro Python: no hace falta tenerlo, y así se prueba en la pata de Tk 9.
    con_tk(8.6, "8.6.13")
    nivel, impreso, parada = salida_de(b.comprobar_tk)
    c("con Tk 8.6 para la compilación", (nivel, parada is not None), (None, True))
    c.contains("  diciendo que hace falta Tk 9", parada or "", "Tk 9")
    c.contains("  y qué Tk hay", parada or "", "8.6.13")
    c.contains("  y con qué Python se compila", parada or "", pins.PYTHON_VERSION)
    c.contains("  y la receta que lo consigue", parada or "",
               "tests/_runtime_ci.py compilador windows-x64")
    con_tk(9.0, "9.0.4")
    nivel, impreso, parada = salida_de(b.comprobar_tk)
    c("con un Tk 9 pasa", (nivel, parada), ("9.0.4", None))
finally:
    if tk_real is False:
        sys.modules.pop("tkinter", None)
    else:
        sys.modules["tkinter"] = tk_real

# Un Python sin tkinter tampoco compila: el .exe no abriría el asistente.
tk_real = sys.modules.get("tkinter", False)
sys.modules["tkinter"] = None                              # el import falla
try:
    nivel, impreso, parada = salida_de(b.comprobar_tk)
finally:
    if tk_real is False:
        sys.modules.pop("tkinter", None)
    else:
        sys.modules["tkinter"] = tk_real
c("sin tkinter para la compilación", (nivel, parada is not None), (None, True))
c.contains("  y dice que no carga Tk", parada or "", "no carga Tk")
c.contains("  y la receta", parada or "", pins.PYTHON_VERSION)

# main(): las dos comprobaciones, antes de escribir el perfil y de compilar, y
# sin forma de saltárselas: ni fuera de GitHub Actions ni con una opción.
orden: list = []
reales = (b.comprobar_pyinstaller, b.comprobar_tk, b.escribir_secreto, b.compilar, b.RAIZ)
b.comprobar_pyinstaller = lambda: orden.append("pyinstaller") or "6.22.3"
b.comprobar_tk = lambda: orden.append("tk") or "9.0.4"
b.escribir_secreto = lambda: orden.append("secreto") or None
b.RAIZ = tmpdir()                     # lo que `main()` limpia al acabar no es el checkout
b.compilar = lambda consola, carpeta: orden.append("compilar") or b.RAIZ / "dist" / "x"
antes = os.environ.pop("GITHUB_ACTIONS", None)
try:
    rc, impreso, _ = salida_de(b.main, [])
    hechos = list(orden)
    ayuda_main = io.StringIO()
    try:
        with contextlib.redirect_stderr(ayuda_main):
            b.main(["--estricto"])
    except SystemExit as e:
        sin_opcion = e.code
finally:
    (b.comprobar_pyinstaller, b.comprobar_tk, b.escribir_secreto, b.compilar,
     b.RAIZ) = reales
    if antes is not None:
        os.environ["GITHUB_ACTIONS"] = antes
c("main() comprueba PyInstaller y Tk antes del perfil y de compilar, también fuera de Actions",
  hechos, ["pyinstaller", "tk", "secreto", "compilar"])
c.contains("  diciendo con qué Python y qué Tk compila", impreso, "Tk 9.0.4")
c.contains("  y con qué PyInstaller", impreso, "PyInstaller 6.22.3")
c("  y acaba bien", rc, 0)
c("ya no hay un --estricto con el que pedirlo: es siempre", sin_opcion, 2)

# main() para cuando una comprobación para, y no llega a escribir el perfil.
orden2: list = []
b.comprobar_pyinstaller = lambda: orden2.append("pyinstaller") or "6.22.3"


def sin_tk_9():
    raise SystemExit("Este Python trae Tk 8.6")


b.comprobar_tk = sin_tk_9
b.escribir_secreto = lambda: orden2.append("secreto") or None
b.compilar = lambda consola, carpeta: orden2.append("compilar") or None
try:
    _, _, parada_main = salida_de(b.main, [])
finally:
    (b.comprobar_pyinstaller, b.comprobar_tk, b.escribir_secreto, b.compilar,
     b.RAIZ) = reales
c("main() con un Tk anterior a 9 para antes de escribir el perfil",
  (parada_main, orden2), ("Este Python trae Tk 8.6", ["pyinstaller"]))

# Lo que el instalador despliega viaja dentro.
c("DATOS_FICHEROS lleva lo que se copia al dispositivo",
  sorted(set(deploy.DEPLOY_FILES) - set(b.DATOS_FICHEROS)), [])
c("  y lo que se copia al equipo con el agente",
  sorted(set(agente.CODIGO_FICHEROS) - set(b.DATOS_FICHEROS)), [])
c("  y la guía", deploy.GUIDE_SOURCE in b.DATOS_FICHEROS, True)
c("DATOS_ARBOLES son los paquetes que se despliegan",
  sorted(deploy.DEPLOY_TREES), sorted(b.DATOS_ARBOLES))

# El Python de compilar es de Windows: con otro se niega sin bajar nada.
destino = tmpdir() / "py"
cache = tmpdir()
proc = subprocess.run([sys.executable, str(REPO / "tests" / "_runtime_ci.py"), "compilador",
                       "linux-x64", str(destino), str(cache)],
                      capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
c("_runtime_ci compilador no prepara un Python de Linux", proc.returncode != 0, True)
c.contains("  y dice por qué", proc.stderr, "solo de Windows")
c("  sin bajar ni escribir nada", (destino.exists(), any(cache.iterdir())), (False, False))

sys.exit(c.report())
