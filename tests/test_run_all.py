#!/usr/bin/env python3
"""`run_all.py` en paralelo: el orden, los límites, los tiempos y la salida.

Corre una copia de `run_all.py` sobre una carpeta de tests falsos: unos solo
duermen, otros fallan y uno se cuelga con un nieto que sigue escribiendo.
Así se comprueba lo que la suite promete sin tocar el dispositivo ni la red:

- por defecto, en orden alfabético, con la última línea de siempre;
- con `-j 4`, ocho tests de un segundo tardan unos dos, no ocho;
- `SERIE` nunca se solapa con otro test, y `--gui-jobs 1` no deja abrir dos
  ventanas a la vez;
- `--timeout` mata el test colgado con todo su árbol de procesos;
- cada test tiene su HOME y su TMPDIR, y con `--display xvfb`, su pantalla;
- un test que pasa y deja un nieto con la salida heredada no se da por colgado;
- Ctrl-C o SIGTERM paran la pasada: no arranca nada más, mata lo que corre con su
  árbol, espera a sus hilos antes de borrar los temporales y sale con 130;
- un test que la suite no puede correr (una excepción, o un hilo que muere) es un
  fallo, nunca un pasado, y la cola sigue;
- un test que muere por señal es un fallo, y un Xvfb que muere durante la pasada
  da fallo a su test y deja sin correr el resto de la cola de su trabajador;
- un segundo Ctrl-C a mitad de matar los tests no deja nada vivo: la pasada se
  vuelve a parar hasta que sus hilos acaban;
- el hilo principal espera con `join(plazo)`, para que Ctrl-C llegue en Windows;
- un nombre que no es un test sale con error;
- con GitHub Actions, la salida va en grupos plegables y los fallos se repiten
  con `::error::`.

Los casos que dependen de la suite y no del sistema usan un `correr()` falso en
un `lanzador.py` que importa la copia de `run_all.py`: nada depende del tiempo
que tarde Python en arrancar.

Y, sobre los tests de verdad, que `GUI` y `GUI_NO` cubren todo fichero que
abre ventanas: el que importa `tkinter` o `ui.tk*` a nivel de módulo o crea un
`Tk()` en cualquier sitio.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from _harness import Checks, tmpdir

import run_all

c = Checks("run_all: la suite en paralelo")

RUN_ALL = Path(run_all.__file__)
TESTS_DIR = run_all.TESTS_DIR
IS_WIN = os.name == "nt"

DUERME = """\
import json, sys, time
from pathlib import Path

marcas = Path(__file__).resolve().parent / "marcas"
marcas.mkdir(exist_ok=True)
inicio = time.time()
time.sleep({segundos})
(marcas / "{nombre}.json").write_text(json.dumps([inicio, time.time()]))
print("salida de {nombre}")
sys.exit({rc})
"""
"""Un test falso: duerme, anota cuándo empezó y acabó, y sale con `rc`."""

ENTORNO = """\
import json, os, time
from pathlib import Path

aqui = Path(__file__).resolve().parent
(aqui / "entornos").mkdir(exist_ok=True)
datos = {k: os.environ.get(k) for k in ("DISPLAY", "HOME", "TMPDIR", "TEMP", "TMP")}
(aqui / "entornos" / (Path(__file__).stem + ".json")).write_text(json.dumps(datos))
time.sleep(0.5)  # dos trabajadores coinciden en el tiempo: cada uno con su pantalla
"""
"""Un test falso que anota las variables de entorno con las que corre."""

ENTRADA = """\
import json, os, sys
from pathlib import Path

aqui = Path(__file__).resolve().parent
(aqui / "entradas").mkdir(exist_ok=True)
tmp = os.environ["TMPDIR"]
dato = sys.stdin.read()
datos = {"stdin": dato, "tmpdir": tmp, "existia": os.path.isdir(tmp)}
(aqui / "entradas" / (Path(__file__).stem + ".json")).write_text(json.dumps(datos))
"""
"""Un test falso que lee la entrada estándar hasta el final y anota si su TMPDIR existe mientras corre."""

TMP_USADO = """\
import os
from pathlib import Path

aqui = Path(__file__).resolve().parent
(aqui / "usados").mkdir(exist_ok=True)
tmp = Path(os.environ["TMPDIR"])
(tmp / "rastro.txt").write_text("x")
(aqui / "usados" / (Path(__file__).stem + ".txt")).write_text(str(tmp))
"""
"""Un test falso que deja un fichero en su TMPDIR y anota dónde está."""

TMP_SIGUIENTE = """\
import json
from pathlib import Path

aqui = Path(__file__).resolve().parent
(aqui / "sigue").mkdir(exist_ok=True)
restos = {p.name: Path(p.read_text()).exists() for p in (aqui / "usados").glob("*.txt")}
(aqui / "sigue" / (Path(__file__).stem + ".json")).write_text(json.dumps(restos))
"""
"""Un test falso que mira si las carpetas de los tests anteriores siguen existiendo."""

LATE = """\
import time
from pathlib import Path

aqui = Path(__file__).resolve().parent
nombre = Path(__file__).stem
(aqui / "arranques").mkdir(exist_ok=True)
(aqui / "arranques" / nombre).write_text("x")
(aqui / "latidos").mkdir(exist_ok=True)
for _ in range(120):
    with (aqui / "latidos" / nombre).open("a") as f:
        f.write(".")
    time.sleep(0.1)
"""
"""Un test que tarda 12 s: anota que arrancó y escribe un punto cada décima mientras vive."""

SALE_CON_NIETO = """\
import subprocess, sys
subprocess.Popen([sys.executable, "-c", "import time; time.sleep(8)"], start_new_session=True)
print("el test acaba bien y deja un nieto con la salida heredada")
"""
"""Un test que pasa, pero deja un proceso que sigue con su salida durante 8 s."""

COLGADO = """\
import subprocess, sys, time
from pathlib import Path

aqui = Path(__file__).resolve().parent
(aqui / "marcas").mkdir(exist_ok=True)
subprocess.Popen([sys.executable, str(aqui / "nieto.py")])
time.sleep(60)
"""
"""Un test que no acaba nunca y deja un proceso hijo escribiendo."""

NIETO = """\
import time
from pathlib import Path

latido = Path(__file__).resolve().parent / "marcas" / "latido"
while True:
    with latido.open("a") as f:
        f.write(".")
    time.sleep(0.1)
"""
"""El proceso que `test_colgado.py` deja atrás: escribe un punto cada décima."""

LANZADOR_FALLOS = """\
import builtins, sys
import run_all

FALLOS = __PLAN__  # nombre del test -> excepción que la suite lanza al correrlo
original = run_all.correr


def correr(script, entorno, timeout):
    clase = FALLOS.get(script.name)
    if clase is not None:
        raise getattr(builtins, clase)(f"fallo forzado en {script.name}")
    return original(script, entorno, timeout)


run_all.correr = correr
raise SystemExit(run_all.main(sys.argv[1:]))
"""
"""Corre `run_all.py` con un `correr()` que lanza la excepción de `FALLOS` en vez de correr el test."""

LANZADOR_SEGUNDOS = """\
import sys
import run_all

SEGUNDOS = __PLAN__  # nombre del test -> segundos que anota la suite, sin correrlo


def correr(script, entorno, timeout):
    return run_all.Resultado(script.name, 0, SEGUNDOS[script.name], b"")


run_all.correr = correr
raise SystemExit(run_all.main(sys.argv[1:]))
"""
"""Corre `run_all.py` con un `correr()` que da a cada test los segundos de `SEGUNDOS`."""

LANZADOR_INTERRUPCION = """\
import _thread, json, sys, time
from pathlib import Path

import run_all

aqui = Path(__file__).resolve().parent
(aqui / "arranques").mkdir(exist_ok=True)
(aqui / "acabados").mkdir(exist_ok=True)


def esperar(condicion, limite=20.0):
    fin = time.monotonic() + limite
    while not condicion() and time.monotonic() < fin:
        time.sleep(0.01)


def correr(script, entorno, timeout):
    nombre = script.stem
    (aqui / "arranques" / nombre).write_text("x")
    base = Path(entorno["TMPDIR"]).parent.parent  # TMPDIR es base/<índice>/t
    if nombre == "test_f0":
        # El primero espera a que el segundo también haya arrancado, y pulsa Ctrl-C.
        esperar(lambda: (aqui / "arranques" / "test_f1").exists())
        _thread.interrupt_main()
    esperar(run_all._interrumpida.is_set)
    time.sleep(0.3)  # matar el árbol de un test no es inmediato
    (aqui / "acabados" / nombre).write_text(json.dumps({"base_viva": base.exists()}))
    return run_all.Resultado(script.name, 137, 0.3, b"")


run_all.correr = correr
raise SystemExit(run_all.main(sys.argv[1:]))
"""
"""Corre `run_all.py` con un `correr()` que pulsa Ctrl-C, en el hilo principal, cuando arranca el segundo test."""

LANZADOR_INTERRUPCION_DOBLE = """\
import _thread, json, os, subprocess, sys, threading, time
from pathlib import Path

import run_all

aqui = Path(__file__).resolve().parent
(aqui / "arranques").mkdir(exist_ok=True)
(aqui / "acabados").mkdir(exist_ok=True)
KW = {} if os.name == "nt" else {"start_new_session": True}  # como correr(): cada test, su grupo
original_matar = run_all.matar_arbol


def esperar(condicion, limite=20.0):
    fin = time.monotonic() + limite
    while not condicion() and time.monotonic() < fin:
        time.sleep(0.01)


def matar_arbol(proc):
    # La primera vez que la pasada mata desde su hilo principal, llega otro Ctrl-C a medio camino.
    if not (aqui / "segunda").exists() and threading.current_thread() is threading.main_thread():
        (aqui / "segunda").write_text("x")
        time.sleep(0.3)
        _thread.interrupt_main()
    original_matar(proc)


def correr(script, entorno, timeout):
    nombre = script.stem
    base = Path(entorno["TMPDIR"]).parent.parent  # TMPDIR es base/<índice>/t
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], **KW)
    run_all._registrar(proc)  # el test queda en la lista de vivos, como con el correr() real
    (aqui / "arranques" / nombre).write_text("x")
    try:
        if nombre == "test_f0":
            # El primero espera a que el segundo también esté vivo, y pulsa Ctrl-C.
            esperar(lambda: (aqui / "arranques" / "test_f1").exists())
            _thread.interrupt_main()
        esperar(run_all._interrumpida.is_set)
        try:
            proc.wait(10)
            muerto = True
        except subprocess.TimeoutExpired:
            muerto = False
        (aqui / "acabados" / nombre).write_text(json.dumps({"base_viva": base.exists(), "muerto": muerto}))
    finally:
        run_all._dar_de_baja(proc)
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    return run_all.Resultado(script.name, 137, 0.3, b"")


run_all.matar_arbol = matar_arbol
run_all.correr = correr
raise SystemExit(run_all.main(sys.argv[1:]))
"""
"""Corre `run_all.py` con Ctrl-C en el hilo principal y un segundo Ctrl-C a mitad de `matar_arbol()`, como si lo pulsaran dos veces."""

LANZADOR_SALIDA = """\
import sys, time
import run_all

original = run_all._volcar


def volcar(salida):
    time.sleep(0.02)  # sin el cerrojo, las cabeceras de otros tests se colarían aquí
    original(salida)


def correr(script, entorno, timeout):
    lineas = "".join(f"linea {i} de {script.stem}\\n" for i in range(5))
    return run_all.Resultado(script.name, 0, 0.0, lineas.encode())


run_all._volcar = volcar
run_all.correr = correr
raise SystemExit(run_all.main(sys.argv[1:]))
"""
"""Corre `run_all.py` con un `correr()` que da cinco líneas propias a cada test, y un `_volcar()` lento."""

MATA = """\
import os, signal

os.kill(os.getpid(), signal.SIGKILL)
"""
"""Un test que se mata a sí mismo con SIGKILL: su código de salida es -9, no un número de error."""

XVFB_FALSO = """\
#!__PYTHON__
import os, sys, time

fd = int(sys.argv[sys.argv.index("-displayfd") + 1])
os.write(fd, b":99\\n")
time.sleep(0.3)  # da su número de pantalla y muere enseguida, como un Xvfb que cae a mitad de la pasada
"""
"""Un `Xvfb` falso: da su número de pantalla y muere a los 0,3 s."""


def preparar(tests: dict[str, tuple[float, int]], otros: dict[str, str] | None = None) -> Path:
    """Crea una carpeta de tests con una copia de `run_all.py` y los tests falsos.

    Args:
        tests: Para cada `test_*.py`, los segundos que duerme y el código con
            que sale.
        otros: Ficheros que no son tests, por nombre y con su contenido tal cual.

    Returns:
        La carpeta, que hace de `tests/` para la copia de `run_all.py`.
    """
    carpeta = tmpdir("prdrive-runall-")
    shutil.copy(RUN_ALL, carpeta / "run_all.py")
    for nombre, (segundos, rc) in tests.items():
        (carpeta / nombre).write_text(
            DUERME.format(segundos=segundos, nombre=nombre[:-3], rc=rc), encoding="utf-8")
    for nombre, texto in (otros or {}).items():
        (carpeta / nombre).write_text(texto, encoding="utf-8")
    return carpeta


def lanzar(carpeta: Path, *args: str, gha: bool = False,
           extra: dict[str, str] | None = None,
           programa: str = "run_all.py") -> tuple[int, str, float]:
    """Corre la copia de `run_all.py` de `carpeta` y devuelve su código, su salida y su tiempo.

    Args:
        carpeta: La carpeta de tests preparada por `preparar()`.
        *args: Los argumentos de `run_all.py`.
        gha: Si se simula GitHub Actions (`GITHUB_ACTIONS=true`).
        extra: Variables que sustituyen a las del proceso.
        programa: El script de `carpeta` que se corre: `run_all.py`, o un lanzador.

    Returns:
        El código de salida, la salida (UTF-8) y los segundos que tardó.
    """
    entorno = {k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"}
    if gha:
        entorno["GITHUB_ACTIONS"] = "true"
    entorno.update(extra or {})
    inicio = time.monotonic()
    proc = subprocess.run([sys.executable, str(carpeta / programa), *args],
                          cwd=str(carpeta), env=entorno, stdin=subprocess.DEVNULL,
                          capture_output=True, timeout=300)
    return proc.returncode, proc.stdout.decode("utf-8", "replace"), time.monotonic() - inicio


def lanzar_falso(carpeta: Path, plantilla: str, plan: dict, *args: str,
                 extra: dict[str, str] | None = None) -> tuple[int, str, float]:
    """Corre `run_all.py` con un `correr()` falso, escrito en `lanzador.py` a partir de `plantilla`.

    Args:
        carpeta: La carpeta de tests, con la copia de `run_all.py`.
        plantilla: Uno de los `LANZADOR_*`; `__PLAN__` recibe `plan` como literal.
        plan: Lo que el falso necesita saber de cada test (ver la plantilla).
        *args: Los argumentos de `run_all.py`.
        extra: Variables que sustituyen a las del proceso.

    Returns:
        Lo mismo que `lanzar()`.
    """
    (carpeta / "lanzador.py").write_text(plantilla.replace("__PLAN__", json.dumps(plan)), encoding="utf-8")
    return lanzar(carpeta, *args, extra=extra, programa="lanzador.py")


def lanzar_con_entrada_abierta(carpeta: Path, *args: str) -> tuple[int, str]:
    """Como `lanzar()`, pero la entrada estándar de `run_all.py` no tiene EOF hasta el final.

    Así se ve si los tests la heredan: uno que la leyera se quedaría esperando.

    Returns:
        El código de salida y la salida (UTF-8).
    """
    entorno = {k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"}
    salida = tmpdir("prdrive-runall-salida-") / "salida.txt"
    with salida.open("wb") as f:
        proc = subprocess.Popen([sys.executable, str(carpeta / "run_all.py"), *args],
                                cwd=str(carpeta), env=entorno, stdin=subprocess.PIPE,
                                stdout=f, stderr=subprocess.STDOUT)
        try:
            rc = proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise
        finally:
            proc.stdin.close()
    return rc, salida.read_text(encoding="utf-8", errors="replace")


def _arrancados(carpeta: Path) -> list[str]:
    """Los tests de `LATE` que llegaron a arrancar, por nombre sin extensión."""
    aqui = carpeta / "arranques"
    return sorted(p.name for p in aqui.glob("*")) if aqui.exists() else []


def _latidos(carpeta: Path) -> dict[str, int]:
    """El tamaño de cada fichero de latido de `LATE`: si crece, el test sigue vivo."""
    aqui = carpeta / "latidos"
    return {p.name: p.stat().st_size for p in aqui.glob("*")} if aqui.exists() else {}


def marcas(carpeta: Path) -> dict[str, tuple[float, float]]:
    """Cuándo empezó y cuándo acabó cada test falso, por nombre de fichero."""
    return {p.stem + ".py": tuple(json.loads(p.read_text())) for p in (carpeta / "marcas").glob("*.json")}


def solapan(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """Si dos intervalos de tiempo tienen algún instante en común."""
    return a[0] < b[1] and b[0] < a[1]


def cabeceras(salida: str) -> list[str]:
    """Los nombres de los tests, en el orden en que se imprimieron sus cabeceras."""
    return [linea[len("##### "):].split(":")[0] for linea in salida.splitlines()
            if linea.startswith("##### ")]


def ultima(salida: str) -> str:
    """La última línea no vacía de la salida."""
    return [linea for linea in salida.splitlines() if linea.strip()][-1]


# 1. Por defecto: como siempre, en orden alfabético.
carpeta = preparar({"test_b.py": (0, 0), "test_a.py": (0, 0), "test_c.py": (0, 0)})
rc, salida, _ = lanzar(carpeta)
c("-j 1 (por defecto): la última línea es la de siempre", ultima(salida), "Los 3 ficheros de test pasan.")
c("-j 1 (por defecto): código 0", rc, 0)
c("-j 1 (por defecto): corre en orden alfabético", cabeceras(salida), ["test_a.py", "test_b.py", "test_c.py"])
c.contains("la salida de cada test va entera, debajo de su cabecera", salida, "salida de test_a")
c.contains("se imprime la lista de los más lentos", salida, "Los más lentos:")

# 2. Un fallo: la última línea lo nombra y el código es 1, con y sin paralelo.
carpeta = preparar({"test_ok.py": (0, 0), "test_falla.py": (0, 1), "test_otro.py": (0, 0)})
rc, salida, _ = lanzar(carpeta)
c("un fallo (-j 1): última línea FALLAN 1 de 3: test_falla.py",
  ultima(salida), "FALLAN 1 de 3: test_falla.py")
c("un fallo (-j 1): código 1", rc, 1)
c.contains("un fallo: la cabecera dice FALLA rc=1", salida, "##### test_falla.py: FALLA rc=1")
rc, salida, _ = lanzar(carpeta, "-j", "4")
c("un fallo (-j 4): la misma última línea", ultima(salida), "FALLAN 1 de 3: test_falla.py")
c("un fallo (-j 4): código 1", rc, 1)

# 2b. Un test que muere por señal (rc -9) también es un fallo, y se nombra.
if IS_WIN:
    print("  (saltado) una señal que mata el test es de POSIX")
else:
    carpeta = preparar({"test_ok.py": (0, 0)}, otros={"test_mata.py": MATA})
    rc, salida, _ = lanzar(carpeta, "-j", "2")
    c.contains("muere por señal: la cabecera dice FALLA rc=-9", salida, "##### test_mata.py: FALLA rc=-9")
    c("muere por señal: la última línea lo nombra", ultima(salida), "FALLAN 1 de 2: test_mata.py")
    c("muere por señal: código 1", rc, 1)

# 3. Paralelo: ocho tests de un segundo no tardan ocho.
carpeta = preparar({f"test_t{i}.py": (1.0, 0) for i in range(8)})
rc, salida, dt = lanzar(carpeta, "-j", "4")
m = marcas(carpeta)
pico = max(sum(1 for b in m.values() if b[0] <= t < b[1]) for t, _ in m.values())
c("-j 4: los 8 de un segundo tardan unos dos, no ocho (en serie serían 8 s o más)", dt < 7.5, True)
c("-j 4: a la vez corren al menos dos", pico >= 2, True)
c("-j 4: todos pasan y la última línea es la de siempre",
  (rc, ultima(salida)), (0, "Los 8 ficheros de test pasan."))

# 4. SERIE: test_avisos_carpeta.py no se solapa con ningún otro.
tests = {f"test_p{i}.py": (0.5, 0) for i in range(6)}
tests["test_avisos_carpeta.py"] = (0.5, 0)
carpeta = preparar(tests)
lanzar(carpeta, "-j", "4")
m = marcas(carpeta)
c("SERIE: ningún otro test corre a la vez que test_avisos_carpeta.py",
  sorted(n for n, iv in m.items() if n != "test_avisos_carpeta.py" and solapan(iv, m["test_avisos_carpeta.py"])),
  [])

# 5. --gui-jobs 1: dos ventanas nunca a la vez; sin el flag, con pantalla compartida, tampoco.
tests = {"test_tk_servicio.py": (1.0, 0), "test_tk_medidas.py": (1.0, 0)}
tests.update({f"test_p{i}.py": (0.3, 0) for i in range(4)})
carpeta = preparar(tests)
lanzar(carpeta, "-j", "4", "--gui-jobs", "1")
m = marcas(carpeta)
c("--gui-jobs 1: dos ventanas nunca a la vez",
  solapan(m["test_tk_servicio.py"], m["test_tk_medidas.py"]), False)
lanzar(carpeta, "-j", "4")
m = marcas(carpeta)
c("con pantalla compartida y sin el flag: también una a la vez",
  solapan(m["test_tk_servicio.py"], m["test_tk_medidas.py"]), False)

# 5b. Con pantalla compartida, --gui-jobs 2 deja solapar dos ventanas. Con un Xvfb propio y sin el
# flag, el límite es -j y se solapan; con --display xvfb --gui-jobs 1, no.
lanzar(carpeta, "-j", "4", "--gui-jobs", "2")
m = marcas(carpeta)
c("--gui-jobs 2 con pantalla compartida: dos ventanas se solapan",
  solapan(m["test_tk_servicio.py"], m["test_tk_medidas.py"]), True)
if shutil.which("Xvfb") and not IS_WIN:
    lanzar(carpeta, "-j", "4", "--display", "xvfb")
    m = marcas(carpeta)
    c("--display xvfb sin --gui-jobs: el límite es -j, y dos ventanas se solapan",
      solapan(m["test_tk_servicio.py"], m["test_tk_medidas.py"]), True)
    lanzar(carpeta, "-j", "4", "--display", "xvfb", "--gui-jobs", "1")
    m = marcas(carpeta)
    c("--display xvfb --gui-jobs 1: dos ventanas nunca a la vez",
      solapan(m["test_tk_servicio.py"], m["test_tk_medidas.py"]), False)
else:
    print("  (saltado) no hay Xvfb en este equipo")

# 6. --timeout: el test colgado sale con rc 124 y se mata con su nieto.
carpeta = preparar({"test_ok.py": (0, 0)}, otros={"test_colgado.py": COLGADO, "nieto.py": NIETO})
rc, salida, dt = lanzar(carpeta, "-j", "2", "--timeout", "5")
c("--timeout: el test colgado se da por fallido y lo dice", "TIMEOUT" in salida, True)
c("--timeout: la última línea nombra al colgado", ultima(salida), "FALLAN 1 de 2: test_colgado.py")
c("--timeout: código 1", rc, 1)
c("--timeout: no espera lo que el test iba a dormir", dt < 30, True)
latido = carpeta / "marcas" / "latido"
antes = latido.stat().st_size if latido.exists() else -1
c("--timeout: el nieto llegó a escribir", antes > 0, True)
time.sleep(1.0)
c("--timeout: el nieto murió con su padre (su latido no crece)",
  latido.stat().st_size if latido.exists() else -1, antes)

# 6b. Un test de SERIE colgado también se corta con --timeout: no espera sus 60 s.
carpeta = preparar({"test_ok.py": (0, 0)}, otros={"test_avisos_carpeta.py": "import time\ntime.sleep(60)\n"})
rc, salida, dt = lanzar(carpeta, "-j", "2", "--timeout", "3")
c("SERIE colgado: se corta y lo dice", "TIMEOUT" in salida, True)
c("SERIE colgado: la última línea lo nombra", ultima(salida), "FALLAN 1 de 2: test_avisos_carpeta.py")
c("SERIE colgado: código 1", rc, 1)
c("SERIE colgado: no espera lo que el test iba a dormir", dt < 30, True)

# 6c. La salida de cada test va entera debajo de su cabecera, aunque acaben a la vez: `_volcar()`
# tarda 0,02 s, así que sin el cerrojo las cabeceras y los cuerpos se mezclarían. Uno de los siete
# sale por el hilo de SERIE.
carpeta = preparar({f"test_s{i}.py": (0, 0) for i in range(6)},
                   otros={"test_avisos_carpeta.py": "print('ok')\n"})
rc, salida, _ = lanzar_falso(carpeta, LANZADOR_SALIDA, {}, "-j", "6")
lineas = salida.splitlines()
nombres = [f"test_s{i}.py" for i in range(6)] + ["test_avisos_carpeta.py"]


def bloque_intacto(nombre: str) -> bool:
    """Si la cabecera de `nombre` va seguida de sus cinco líneas, sin nada en medio."""
    donde = [i for i, linea in enumerate(lineas) if linea.startswith(f"##### {nombre}:")]
    if not donde:
        return False
    i = donde[0]
    return lineas[i + 1:i + 6] == [f"linea {j} de {nombre[:-3]}" for j in range(5)]


c("-j 6: cada cabecera va seguida de sus propias cinco líneas",
  [n for n in nombres if not bloque_intacto(n)], [])
c("-j 6: la última línea sigue siendo la de siempre", (rc, ultima(salida)), (0, "Los 7 ficheros de test pasan."))

# 7. Cada test tiene su HOME y su TMPDIR; con --display xvfb, su pantalla.
carpeta = preparar({}, otros={"test_entorno_a.py": ENTORNO, "test_entorno_b.py": ENTORNO})
rc, salida, _ = lanzar(carpeta, "-j", "2")
ent = {p.stem: json.loads(p.read_text()) for p in (carpeta / "entornos").glob("*.json")}
c("aislamiento: cada test tiene su HOME", ent["test_entorno_a"]["HOME"] != ent["test_entorno_b"]["HOME"], True)
c("aislamiento: su HOME no es el del proceso que lo lanza",
  ent["test_entorno_a"]["HOME"] != os.environ.get("HOME"), True)
c("aislamiento: su TMPDIR es el suyo y no el del proceso",
  ent["test_entorno_a"]["TMPDIR"] not in (None, os.environ.get("TMPDIR")), True)

if shutil.which("Xvfb") and not IS_WIN:
    carpeta = preparar({}, otros={"test_entorno_a.py": ENTORNO, "test_entorno_b.py": ENTORNO})
    rc, salida, _ = lanzar(carpeta, "-j", "2", "--display", "xvfb")
    ent = {p.stem: json.loads(p.read_text()) for p in (carpeta / "entornos").glob("*.json")}
    propio = os.environ.get("DISPLAY")
    c("--display xvfb: cada test ve un servidor X propio (:N)",
      all(re.fullmatch(r":\d+", ent[n]["DISPLAY"] or "") for n in ent), True)
    c("--display xvfb: ninguno hereda el DISPLAY de la suite (el de su trabajador)",
      [n for n in ent if ent[n]["DISPLAY"] == propio], [])
    c("--display xvfb: dos tests a la vez tienen servidores distintos",
      ent["test_entorno_a"]["DISPLAY"] != ent["test_entorno_b"]["DISPLAY"], True)
    c("--display xvfb: la última línea sigue siendo la de siempre",
      ultima(salida), "Los 2 ficheros de test pasan.")
else:
    print("  (saltado) no hay Xvfb en este equipo")

# 8. --display xvfb sin Xvfb: avisa y sigue con la pantalla que haya.
vacio = tmpdir("prdrive-sin-xvfb-")
carpeta = preparar({"test_ok.py": (0, 0)})
rc, salida, _ = lanzar(carpeta, "--display", "xvfb", extra={"PATH": str(vacio)})
c.contains("sin Xvfb: lo dice", salida, "sin Xvfb")
c("sin Xvfb: sigue y pasa", (rc, ultima(salida)), (0, "Los 1 ficheros de test pasan."))

# 8b. Un Xvfb que muere durante la pasada: el test que corría falla (un test de Tk sin pantalla
# sale con 0), su trabajador deja la cola y el resto de tests se da por sin resultado.
if IS_WIN:
    print("  (saltado) un Xvfb falso es de POSIX")
else:
    falso = tmpdir("prdrive-xvfb-falso-")
    ejecutable = falso / "Xvfb"
    ejecutable.write_text(XVFB_FALSO.replace("__PYTHON__", sys.executable), encoding="utf-8")
    ejecutable.chmod(0o755)
    carpeta = preparar({"test_a.py": (1.0, 0), "test_b.py": (0, 0)})
    rc, salida, _ = lanzar(carpeta, "--display", "xvfb",
                           extra={"PATH": str(falso) + os.pathsep + os.environ.get("PATH", "")})
    c.contains("Xvfb muere: el test que corría falla y lo dice", salida, "##### test_a.py: FALLA rc=1")
    c.contains("Xvfb muere: la nota lo explica", salida, "Xvfb murió durante el test")
    c("Xvfb muere: el trabajador deja la cola (el siguiente no llega a correr)",
      (carpeta / "marcas" / "test_b.json").exists(), False)
    c("Xvfb muere: el resto cuenta como fallo y la última línea lo nombra",
      (rc, ultima(salida)), (1, "FALLAN 2 de 2: test_a.py, test_b.py"))

# 9. Los nombres filtran y los argumentos malos se rechazan.
carpeta = preparar({"test_a.py": (0, 0), "test_b.py": (0, 0)})
rc, salida, _ = lanzar(carpeta, "test_b.py")
c("nombres: solo corre el pedido", cabeceras(salida), ["test_b.py"])
rc, salida, _ = lanzar(carpeta, "tests/test_b.py")
c("nombres: una ruta vale por su nombre de fichero", (rc, cabeceras(salida)), (0, ["test_b.py"]))
rc, salida, _ = lanzar(carpeta, "test_typo.py", "test_a.py")
c("nombres: uno que no existe sale con error (2)", rc, 2)
c.contains("nombres: el que no existe se nombra", salida, "test_typo.py")
c("nombres: con un nombre que no existe no corre nada", cabeceras(salida), [])
rc, salida, _ = lanzar(carpeta, "-j", "0")
c("-j 0 se rechaza (código 2)", rc, 2)
rc, salida, _ = lanzar(carpeta, "-j", "auto")
c("-j auto corre todo", (rc, ultima(salida)), (0, "Los 2 ficheros de test pasan."))
carpeta_vacia = tmpdir("prdrive-vacia-")
shutil.copy(RUN_ALL, carpeta_vacia / "run_all.py")
rc, salida, _ = lanzar(carpeta_vacia)
c("sin tests: lo dice y sale con 1", (rc, ultima(salida)), (1, "No hay tests que ejecutar."))

# 10. GitHub Actions: grupos plegables y fallos repetidos con ::error::.
carpeta = preparar({"test_ok.py": (0, 0), "test_falla.py": (0, 1)})
rc, salida, _ = lanzar(carpeta, gha=True)
c.contains("GHA: cada test va en un grupo plegable", salida, "::group::##### test_ok.py: OK")
c.contains("GHA: el grupo se cierra", salida, "::endgroup::")
c.contains("GHA: el fallo se repite con ::error::", salida, "::error::test_falla.py")
c("GHA: la última línea sigue siendo la de siempre",
  ultima(salida), "FALLAN 1 de 2: test_falla.py")


# 11. Un test que pasa y deja un nieto con la salida heredada no es un timeout: se espera
# al test, no a que se cierre su salida.
carpeta = preparar({}, otros={"test_nieto.py": SALE_CON_NIETO})
rc, salida, dt = lanzar(carpeta, "--timeout", "3")
c("nieto con la salida heredada: el test que pasa sigue pasando",
  (rc, ultima(salida)), (0, "Los 1 ficheros de test pasan."))
c("nieto con la salida heredada: no se espera a que el nieto acabe", dt < 6.0, True)

# 12. Cada test tiene su TMPDIR, que existe mientras corre y se borra al acabar; no hereda
# la entrada estándar de la suite; y la carpeta de los temporales queda corta (AF_UNIX).
carpeta = preparar({}, otros={"test_entrada.py": ENTRADA})
rc, salida = lanzar_con_entrada_abierta(carpeta, "--timeout", "5")
ruta = carpeta / "entradas" / "test_entrada.json"
ent = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}
c("entrada: el test la lee hasta el final (vacía, sin heredar la de la suite)", ent.get("stdin"), "")
c("TMPDIR: existe mientras el test corre", ent.get("existia"), True)
c("TMPDIR: se borra al acabar el test", bool(ent) and not Path(ent["tmpdir"]).exists(), True)
carpeta = preparar({}, otros={"test_a.py": TMP_USADO, "test_b.py": TMP_SIGUIENTE})
lanzar(carpeta, "-j", "1")
ruta = carpeta / "sigue" / "test_b.json"
c("TMPDIR: al acabar un test, su carpeta ya no existe cuando corre el siguiente",
  json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None,
  {"test_a.txt": False})
if IS_WIN:
    print("  (saltado) la carpeta corta de los temporales es de POSIX")
else:
    carpeta = preparar({}, otros={"test_entrada.py": ENTRADA})
    largo = tmpdir("prdrive-tmp-largo-") / ("x" * 120)
    largo.mkdir()
    rc, salida, _ = lanzar(carpeta, extra={"TMPDIR": str(largo)})
    ruta = carpeta / "entradas" / "test_entrada.json"
    ent = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}
    c("TMPDIR largo: la suite pasa", (rc, ultima(salida)), (0, "Los 1 ficheros de test pasan."))
    c("TMPDIR largo: la carpeta de cada test queda corta (60 caracteres o menos)",
      bool(ent) and len(ent["tmpdir"]) <= 60, True)
    raiz = Path(tempfile.mkdtemp(prefix="prdrive-base-", dir="/tmp"))
    try:
        rc, salida, _ = lanzar(carpeta, extra={"TMPDIR": str(raiz)})
        c("base: al acabar la pasada no queda ninguna carpeta prt-* suya",
          sorted(p.name for p in raiz.glob("prt-*")), [])
    finally:
        shutil.rmtree(raiz, ignore_errors=True)

# 13. PESO fija el orden con -j 2: los pesados arrancan antes; sin -j, alfabético.
carpeta = preparar({"test_a.py": (0.2, 0), "test_keepassxc.py": (0.5, 0),
                    "test_llavero_combinar.py": (0.5, 0)})
lanzar(carpeta, "-j", "2")
m = marcas(carpeta)
c("PESO con -j 2: keepassxc y llavero arrancan antes que test_a",
  m["test_a.py"][0] > max(m["test_keepassxc.py"][0], m["test_llavero_combinar.py"][0]), True)
rc, salida, _ = lanzar(carpeta, "-j", "1")
c("sin -j (1): orden alfabético, sin PESO", cabeceras(salida),
  ["test_a.py", "test_keepassxc.py", "test_llavero_combinar.py"])

# 14. Pantalla compartida (sin --display): test_superficie y test_tk_tabla no se solapan
# con ningún otro test.
tests = {"test_superficie.py": (0.4, 0), "test_tk_tabla.py": (0.4, 0)}
tests.update({f"test_p{i}.py": (0.4, 0) for i in range(6)})
carpeta = preparar(tests)
lanzar(carpeta, "-j", "4")
m = marcas(carpeta)
for pantalla in ("test_superficie.py", "test_tk_tabla.py"):
    c(f"pantalla compartida: {pantalla} no se solapa con ningún otro",
      sorted(n for n in m if n != pantalla and solapan(m[n], m[pantalla])), [])

# 15. Los más lentos: diez filas, del más lento al menos lento. Los segundos los da un
# `correr()` falso, así que no dependen de lo que Python tarde en arrancar.
segundos = {f"test_v{i:02d}.py": round(0.5 + 1.1 * i, 1) for i in range(12)}
carpeta = preparar({n: (0, 0) for n in segundos})
rc, salida, _ = lanzar_falso(carpeta, LANZADOR_SEGUNDOS, segundos, "-j", "12")
bloque = salida.partition("Los más lentos:")[2].partition("Tiempo:")[0]
filas = re.findall(r"^\s+([\d.]+) s\s+(\S+)\s*$", bloque, re.M)
printed = [float(s) for s, _ in filas]
c("los más lentos: diez filas", len(filas), 10)
c("los más lentos: los segundos impresos no crecen", printed, sorted(printed, reverse=True))
c("los más lentos: el más largo, primero", filas[0][1] if filas else None, "test_v11.py")
c("los más lentos: los dos más cortos no salen",
  sorted(n for _, n in filas if n in ("test_v00.py", "test_v01.py")), [])
c("los más lentos: la última línea sigue siendo la de siempre",
  (rc, ultima(salida)), (0, "Los 12 ficheros de test pasan."))

# 16a. Lo que la interrupción da por hecho, sin lanzar nada: la cola no da más tras parar(),
# y un test que arranca con la pasada ya interrumpida muere al momento (arranque en carrera).
rp = run_all.Reparto(["test_a.py", "test_b.py"], 1)
c("Reparto: antes de parar() da los tests en orden", rp.tomar(), "test_a.py")
rp.parar()
c("Reparto: tras parar() ya no da ninguno", rp.tomar(), None)
lento = tmpdir("prdrive-interrumpido-") / "test_lento.py"
lento.write_text("import time\ntime.sleep(20)\n", encoding="utf-8")
run_all._interrumpida.set()
try:
    inicio = time.monotonic()
    r = run_all.correr(lento, dict(os.environ), 600.0)
    c("un test que arranca con la pasada interrumpida muere al momento",
      (time.monotonic() - inicio < 10, r.rc != 0), (True, True))
finally:
    run_all._interrumpida.clear()

# 16. Ctrl-C o SIGTERM (POSIX): para la cola, mata lo que corre con su árbol y no arranca
# ningún otro. La señal va solo a run_all, como el terminal la manda a su grupo sin los tests.
if IS_WIN:
    print("  (saltado) la interrupción se prueba en POSIX")
else:
    for senal in (signal.SIGINT, signal.SIGTERM):
        etiqueta = signal.Signals(senal).name
        carpeta = preparar({}, otros={f"test_l{i}.py": LATE for i in range(6)})
        corta = Path(tempfile.mkdtemp(prefix="prdrive-int-", dir="/tmp"))
        entorno = {k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"}
        entorno["TMPDIR"] = str(corta)
        salida_ruta = corta / "salida.txt"
        proc = None
        try:
            with salida_ruta.open("wb") as f:
                proc = subprocess.Popen(
                    [sys.executable, str(carpeta / "run_all.py"), "-j", "2"], cwd=str(carpeta),
                    env=entorno, stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT)
                limite = time.monotonic() + 15
                while len(_arrancados(carpeta)) < 2 and time.monotonic() < limite:
                    time.sleep(0.05)
                time.sleep(0.5)
                t0 = time.monotonic()
                proc.send_signal(senal)
                try:
                    rc = proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    rc = None
                dt = time.monotonic() - t0
                time.sleep(0.5)
                antes = _latidos(carpeta)
                time.sleep(1.0)
                despues = _latidos(carpeta)
            texto = salida_ruta.read_text(encoding="utf-8", errors="replace")
            c(f"{etiqueta}: la suite termina enseguida, sin esperar a los tests en curso",
              dt < 10.0, True)
            c(f"{etiqueta}: sale con 130, el código de la interrupción (documentado)", rc, 130)
            c(f"{etiqueta}: no arranca ningún test más", _arrancados(carpeta), ["test_l0", "test_l1"])
            c(f"{etiqueta}: los tests en curso mueren con su árbol (sus latidos se paran)",
              bool(antes) and antes == despues, True)
            c.contains(f"{etiqueta}: lo dice", texto, "INTERRUMPIDO")
            c(f"{etiqueta}: no queda ningún temporal de la suite",
              sorted(p.name for p in corta.glob("prt-*")), [])
        finally:
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait()
            shutil.rmtree(corta, ignore_errors=True)


# 16b. parar() despierta a quien espera un hueco de ventana y no le da test: tras una
# interrupción, la cola no arranca nada, tampoco un test de GUI que espera a otro.
rp = run_all.Reparto(["test_tk_servicio.py", "test_tk_medidas.py"], 1)
c("Reparto: el primer test de GUI se da", rp.tomar(), "test_tk_servicio.py")
dados: list = []
espera = threading.Thread(target=lambda: dados.append(rp.tomar()), daemon=True)  # si parar() fallara, no colgaría la prueba
espera.start()
time.sleep(0.2)  # si aún no espera, al llegar tras parar() tampoco recibe nada
rp.parar()
espera.join(10)
c("Reparto: parar() despierta al que espera una ventana y no le da test",
  (espera.is_alive(), dados), (False, [None]))

# 16c. Ctrl-C a mitad de pasada, con `correr()` falso y sin procesos. El primer test espera a que
# el segundo arranque y entonces pulsa Ctrl-C en el hilo principal. Tras la interrupción no
# arranca ningún test más, y los dos que estaban en marcha acaban con su carpeta base todavía
# en pie: la pasada espera a sus hilos antes de borrar los temporales.
carpeta = preparar({f"test_f{i}.py": (0, 0) for i in range(6)})
raiz = Path(tempfile.mkdtemp(prefix="pi-", dir=None if IS_WIN else "/tmp"))  # corta: AF_UNIX
try:
    rc, salida, _ = lanzar_falso(carpeta, LANZADOR_INTERRUPCION, {}, "-j", "2",
                                 extra={"TMPDIR": str(raiz), "TEMP": str(raiz), "TMP": str(raiz)})
    acabados = {p.name: json.loads(p.read_text()) for p in (carpeta / "acabados").glob("*")} \
        if (carpeta / "acabados").exists() else {}
    c("Ctrl-C con -j 2: sale con 130", rc, 130)
    c.contains("Ctrl-C con -j 2: lo dice", salida, "INTERRUMPIDO")
    c("Ctrl-C con -j 2: no arranca ningún test tras la interrupción (solo los dos en marcha)",
      _arrancados(carpeta), ["test_f0", "test_f1"])
    c("Ctrl-C con -j 2: los que acaban lo hacen con su carpeta base en pie (se espera antes de borrar)",
      {n: v["base_viva"] for n, v in acabados.items()}, {"test_f0": True, "test_f1": True})
    c("Ctrl-C con -j 2: no queda ninguna carpeta prt-* de la pasada",
      sorted(p.name for p in raiz.glob("prt-*")), [])
finally:
    shutil.rmtree(raiz, ignore_errors=True)

# 16d. El hilo principal espera en trozos con plazo: un `join()` sin plazo no deja llegar Ctrl-C
# en Windows (`run_all._esperar()`).
def _joins_sin_plazo(ruta: Path) -> list[int]:
    """Las líneas de las llamadas `.join()` sin argumentos en `ruta`."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    return sorted(n.lineno for n in ast.walk(arbol)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                  and n.func.attr == "join" and not n.args and not n.keywords)


class Espia(threading.Thread):
    """Un hilo que anota con qué plazo lo esperan."""

    def __init__(self) -> None:
        super().__init__(target=time.sleep, args=(0.6,))
        self.plazos: list = []

    def join(self, timeout=None) -> None:
        self.plazos.append(timeout)
        super().join(timeout)


c("run_all.py: ningún join() sin plazo", _joins_sin_plazo(RUN_ALL), [])
espia = Espia()
espia.start()
run_all._esperar([espia])
c("_esperar: espera a que el hilo acabe", espia.is_alive(), False)
c("_esperar: lo espera en trozos con plazo", (len(espia.plazos) >= 2, None in espia.plazos), (True, False))

# 16e. Un test que la suite no puede correr no se pierde: una excepción da FALLA con su rastro,
# y un hilo que muere da «sin resultado»; en los dos casos la cola sigue y la última línea lo nombra.
carpeta = preparar({"test_ok0.py": (0, 0), "test_roto.py": (0, 0), "test_ok1.py": (0, 0)})
rc, salida, _ = lanzar_falso(carpeta, LANZADOR_FALLOS, {"test_roto.py": "ValueError"}, "-j", "2")
c("excepción de la suite (-j 2): la última línea nombra al que revienta",
  ultima(salida), "FALLAN 1 de 3: test_roto.py")
c("excepción de la suite: código 1", rc, 1)
c.contains("excepción de la suite: su cabecera dice FALLA", salida, "##### test_roto.py: FALLA rc=1")
c.contains("excepción de la suite: su salida lleva el rastro", salida, "ValueError")
c("excepción de la suite: los demás siguen corriendo y pasan",
  [n for n in ("test_ok0.py", "test_ok1.py") if f"##### {n}: OK" in salida], ["test_ok0.py", "test_ok1.py"])

carpeta = preparar({"test_ok0.py": (0, 0), "test_mudo.py": (0, 0), "test_ok1.py": (0, 0)})
rc, salida, _ = lanzar_falso(carpeta, LANZADOR_FALLOS, {"test_mudo.py": "SystemExit"}, "-j", "2")
c("hilo que muere (-j 2): la última línea nombra al que se perdió",
  ultima(salida), "FALLAN 1 de 3: test_mudo.py")
c("hilo que muere: código 1", rc, 1)
c.contains("hilo que muere: su salida dice «sin resultado»", salida, "sin resultado")
c("hilo que muere: los demás siguen corriendo y pasan",
  [n for n in ("test_ok0.py", "test_ok1.py") if f"##### {n}: OK" in salida], ["test_ok0.py", "test_ok1.py"])

carpeta = preparar({"test_p0.py": (0, 0), "test_p1.py": (0, 0)},
                   otros={"test_avisos_carpeta.py": "print('ok')\n"})
rc, salida, _ = lanzar_falso(carpeta, LANZADOR_FALLOS, {"test_avisos_carpeta.py": "ValueError"}, "-j", "2")
c("excepción en SERIE: la última línea nombra al que revienta",
  ultima(salida), "FALLAN 1 de 3: test_avisos_carpeta.py")
c("excepción en SERIE: código 1", rc, 1)

# 16f. Un segundo Ctrl-C a mitad de matar los tests no corta la pasada: se vuelve a parar y a matar,
# y ningún test queda vivo ni se borra la carpeta base mientras alguno sigue corriendo.
carpeta = preparar({f"test_f{i}.py": (0, 0) for i in range(6)})
raiz = Path(tempfile.mkdtemp(prefix="pi-", dir=None if IS_WIN else "/tmp"))  # corta: AF_UNIX
try:
    rc, salida, _ = lanzar_falso(carpeta, LANZADOR_INTERRUPCION_DOBLE, {}, "-j", "2",
                                 extra={"TMPDIR": str(raiz), "TEMP": str(raiz), "TMP": str(raiz)})
    acabados = {p.name: json.loads(p.read_text()) for p in (carpeta / "acabados").glob("*")} \
        if (carpeta / "acabados").exists() else {}
    c("Ctrl-C doble: la segunda interrupción sí llegó a mitad de matar", (carpeta / "segunda").exists(), True)
    c("Ctrl-C doble: sale con 130", rc, 130)
    c("Ctrl-C doble: no arranca ningún test más", _arrancados(carpeta), ["test_f0", "test_f1"])
    c("Ctrl-C doble: los dos tests en curso mueren con su proceso",
      {n: v["muerto"] for n, v in acabados.items()}, {"test_f0": True, "test_f1": True})
    c("Ctrl-C doble: la carpeta base sigue en pie mientras acaban (se espera antes de borrar)",
      {n: v["base_viva"] for n, v in acabados.items()}, {"test_f0": True, "test_f1": True})
    c("Ctrl-C doble: no queda ninguna carpeta prt-* de la pasada",
      sorted(p.name for p in raiz.glob("prt-*")), [])
finally:
    shutil.rmtree(raiz, ignore_errors=True)

# 17. Lo que los tests de verdad declaran: GUI, GUI_NO, SERIE y PESO.
def _es_tk(modulo: str) -> bool:
    """Si el nombre de un módulo es tkinter o un módulo de `ui.tk*`."""
    return modulo == "tkinter" or modulo.startswith("tkinter.") or modulo.startswith("ui.tk")


def _importa_tk(nodo: ast.AST) -> bool:
    """Si un `import` o `from ... import` trae tkinter o un módulo `ui.tk*`."""
    if isinstance(nodo, ast.Import):
        return any(_es_tk(a.name) for a in nodo.names)
    if isinstance(nodo, ast.ImportFrom):
        if nodo.module == "ui":
            return any(a.name.startswith("tk") for a in nodo.names)
        return _es_tk(nodo.module or "")
    return False


def _a_nivel_de_modulo(arbol: ast.Module):
    """Los nodos que se ejecutan al importar el fichero: no los de dentro de una función."""
    pila = list(arbol.body)
    while pila:
        nodo = pila.pop()
        yield nodo
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            pila.extend(ast.iter_child_nodes(nodo))


def _crea_tk(arbol: ast.Module) -> bool:
    """Si el fichero crea un `Tk()` en cualquier sitio."""
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call):
            f = nodo.func
            if (isinstance(f, ast.Attribute) and f.attr == "Tk") or (isinstance(f, ast.Name) and f.id == "Tk"):
                return True
    return False


abren: set[str] = set()
tocan_tk: set[str] = set()
for ruta in sorted(TESTS_DIR.glob("test_*.py")):
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    if any(_importa_tk(n) for n in _a_nivel_de_modulo(arbol)) or _crea_tk(arbol):
        abren.add(ruta.name)
    if any(_importa_tk(n) for n in ast.walk(arbol)):
        tocan_tk.add(ruta.name)

c("GUI y GUI_NO no se solapan", sorted(set(run_all.GUI) & set(run_all.GUI_NO)), [])
c("todo fichero que abre ventanas está en GUI o en GUI_NO",
  sorted(n for n in abren if n not in run_all.GUI and n not in run_all.GUI_NO), [])
c("GUI solo lleva ficheros que tocan tkinter o ui.tk*",
  sorted(n for n in run_all.GUI if n not in tocan_tk), [])
c("cada excepción de GUI_NO explica por qué",
  sorted(n for n, razon in run_all.GUI_NO.items() if not razon.strip()), [])
existen = {p.name for p in TESTS_DIR.glob("test_*.py")}
c("GUI, GUI_NO, SERIE y PESO solo nombran ficheros que existen",
  sorted(set(run_all.GUI) - existen) + sorted(set(run_all.GUI_NO) - existen)
  + sorted(set(run_all.SERIE) - existen) + sorted(set(run_all.PESO) - existen), [])

previo = run_all.IS_WIN
run_all.IS_WIN = False
try:
    sin_compartido = sorted(run_all.serie_para(False))
    con_compartido = sorted(run_all.serie_para(True))
finally:
    run_all.IS_WIN = previo
c("SERIE fuera de Windows, sin escritorio compartido: solo test_avisos_carpeta.py",
  sin_compartido, ["test_avisos_carpeta.py"])
c("SERIE fuera de Windows, con escritorio compartido: también píxeles y foco",
  con_compartido, ["test_avisos_carpeta.py", "test_superficie.py", "test_tk_tabla.py"])
previo = run_all.IS_WIN
run_all.IS_WIN = True
try:
    en_windows = sorted(run_all.serie_para(False))
finally:
    run_all.IS_WIN = previo
c("SERIE en Windows: también test_vestibulo.py", en_windows,
  ["test_avisos_carpeta.py", "test_vestibulo.py"])

sys.exit(c.report())
