#!/usr/bin/env python3
"""La autoprueba del instalador (`prdrive-install.py --autoprueba RUTA`).

Es lo que la CI ejecuta sobre el `.exe` recién compilado antes de publicarlo
(`.github/actions/compilar-instalador`): sin ventana a la vista y sin
`report()` (compilado con `--windowed` no hay consola, y `--check`/`--probe`
abren una ventana y se quedan en `mainloop()`), escribe en RUTA un JSON con lo
que el `.exe` necesita para abrir el asistente y acaba con 0 solo si todo está.

Aquí se ejecuta el `.py`, con el Python del test, en un proceso aparte:
- Con Tk 9 (la pata del runtime fijado) acaba con 0: SVG, el tema, el
  asistente, cada módulo que se importa tarde y cada fichero que despliega.
- Con Tk 8.6 acaba con 1 por `tk9` y `svg`, y todo lo demás está bien.
- `MODULOS_ASISTENTE` no se queda atrás: lleva todo lo que `ui/tk_install.py`,
  `ui/tk_crypto.py` y `ui/tk_equipo.py` importan dentro de funciones.
- `--autoprueba` no sale en `--help`, y un fallo inesperado también escribe
  el fichero, con `error`.

`PRDRIVE_SIN_SVG` se quita del entorno del proceso: la autoprueba dice lo que
sabe hacer el intérprete, no lo que se fuerza en una pasada de la suite.
"""

import ast
import importlib.util
import json
import os
import platform
import subprocess
import sys
import time

from _harness import REPO, Checks, tmpdir

c = Checks("instalador: la autoprueba del .exe (--autoprueba)")

ENTRADA = REPO / "prdrive-install.py"
spec = importlib.util.spec_from_file_location("instalador_autoprueba", ENTRADA)
instalador = importlib.util.module_from_spec(spec)
spec.loader.exec_module(instalador)

# MODULOS_ASISTENTE cubre los imports de dentro de funciones del asistente.
FICHEROS = ("ui/tk_install.py", "ui/tk_crypto.py", "ui/tk_equipo.py")


def es_modulo(nombre: str) -> bool:
    """Indica si `nombre` es un módulo importable (y no un nombre de dentro de uno)."""
    raiz = nombre.split(".")[0]
    if raiz in ("ui", "common", "install"):
        ruta = REPO.joinpath(*nombre.split("."))
        return ruta.with_suffix(".py").is_file() or (ruta / "__init__.py").is_file()
    try:
        return importlib.util.find_spec(nombre) is not None
    except (ImportError, ValueError):
        return False


def importados_dentro(rel: str) -> set[str]:
    """Devuelve los módulos que `rel` importa dentro de funciones o clases."""
    arbol = ast.parse((REPO / rel).read_text(encoding="utf-8"))
    paquete = rel.split("/")[0]
    arriba = {id(n) for n in arbol.body if isinstance(n, (ast.Import, ast.ImportFrom))}
    nombres: set[str] = set()
    for nodo in ast.walk(arbol):
        if id(nodo) in arriba:
            continue
        if isinstance(nodo, ast.Import):
            nombres |= {a.name for a in nodo.names}
        elif isinstance(nodo, ast.ImportFrom):
            base = nodo.module or ""
            if nodo.level:
                base = paquete + (f".{base}" if base else "")
            for alias in nodo.names:
                candidato = f"{base}.{alias.name}"
                nombres.add(candidato if es_modulo(candidato) else base)
    return nombres


DENTRO = set().union(*(importados_dentro(f) for f in FICHEROS))
c("se ven los imports tardíos del asistente",
  {"ui.tk_crypto", "ui.tk_equipo", "install.agente", "penwatch"} <= DENTRO, True)
c("MODULOS_ASISTENTE lleva todo lo que el asistente importa dentro de funciones",
  sorted(DENTRO - set(instalador.MODULOS_ASISTENTE)), [])

# Escondida de --help: es de la CI, no de quien teclea.
ayuda = subprocess.run([sys.executable, str(ENTRADA), "--help"], capture_output=True,
                       text=True, stdin=subprocess.DEVNULL, timeout=60)
c("--help funciona", ayuda.returncode, 0)
c("  y no enseña --autoprueba", "--autoprueba" in ayuda.stdout, False)

# Un fallo inesperado también deja el fichero, con `error`.
roto = tmpdir() / "roto.json"
real = instalador._autoprueba


def revienta(informe):
    informe["python"] = "3.x"
    raise RuntimeError("se ha roto algo")


instalador._autoprueba = revienta
try:
    rc_roto = instalador.cmd_autoprueba(str(roto))
finally:
    instalador._autoprueba = real
leido_roto = json.loads(roto.read_text(encoding="utf-8")) if roto.is_file() else {}
c("un fallo inesperado acaba con 1", rc_roto, 1)
c.contains("  y queda en el fichero, con lo que se llegó a ver", leido_roto.get("error", ""),
           "RuntimeError: se ha roto algo")
c("  lo de antes del fallo también", leido_roto.get("python"), "3.x")

# Lo de verdad: el .py con el Python de este test, en otro proceso.
try:
    import ui  # noqa: F401  (antes que tkinter, como toda ventana)
    import tkinter as tk
    raiz = tk.Tk()
    raiz.destroy()
    TK9 = tk.TkVersion >= 9
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

informe_ruta = tmpdir() / "salida" / "autoprueba.json"
entorno = {k: v for k, v in os.environ.items() if k != "PRDRIVE_SIN_SVG"}
inicio = time.monotonic()
try:
    proc = subprocess.run([sys.executable, str(ENTRADA), "--autoprueba", str(informe_ruta)],
                          cwd=str(tmpdir()), env=entorno, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=60)
    rc, salida = proc.returncode, proc.stdout + proc.stderr
except subprocess.TimeoutExpired as e:
    rc, salida = None, f"más de 60 s: {e}"
segundos = time.monotonic() - inicio
c("acaba en menos de 60 s (no se queda en ninguna ventana)", rc is not None, True)
print(f"  ({segundos:.1f} s; código {rc})")
if salida.strip():
    print("  lo que ha escrito por consola:\n    " + salida.strip().replace("\n", "\n    "))

informe = (json.loads(informe_ruta.read_text(encoding="utf-8"))
           if informe_ruta.is_file() else {})
CLAVES = {"python", "congelado", "tk", "tk9", "svg", "tema", "letra", "pintadas_python",
          "asistente", "modulos", "datos", "python_equipo", "unidades"}
c("escribe el fichero con todas sus claves", sorted(CLAVES - set(informe)), [])
c("  sin ningún error inesperado", "error" in informe, False)
c("dice el Python con el que corre", informe.get("python"), platform.python_version())
c("  y que no está congelado (es el .py)", informe.get("congelado"), False)
c("el tema se aplica", informe.get("tema"), True)
c("el asistente se construye", informe.get("asistente"), True)
c("dice qué letra ha elegido el tema", isinstance(informe.get("letra"), str)
  and bool(informe.get("letra")), True)
modulos = informe.get("modulos", {})
c("cada módulo que el asistente importa tarde se importa",
  {k: v for k, v in modulos.items() if v != "ok"}, {})
c("  y son todos los de MODULOS_ASISTENTE", sorted(modulos), sorted(instalador.MODULOS_ASISTENTE))
datos = informe.get("datos", {})
c("cada fichero que el instalador despliega está", {k: v for k, v in datos.items() if v != "ok"},
  {})
c("  empezando por lo que va al dispositivo y al equipo",
  {"sync.py", "runsync.py", "penwatch.py", "VERSION", "common", "ui", "agente.py",
   "pregunta.py", "device-readme.md"} <= set(datos), True)
c("el Python del equipo es solo informativo, pero se dice",
  isinstance(informe.get("python_equipo"), str), True)
c("y cuántas unidades ve, también", isinstance(informe.get("unidades"), int), True)

if TK9:
    c("con Tk 9 acaba con 0", rc, 0)
    c("  con Tk 9 y SVG", (informe.get("tk9"), informe.get("svg")), (True, True))
    c("  sin pintar nada con el pintor de Python", informe.get("pintadas_python"), 0)
    c("  y da la versión de Tk", str(informe.get("tk", "")).startswith("9."), True)
else:
    c("con Tk 8.6 acaba con 1", rc, 1)
    c("  porque ni es Tk 9 ni pinta SVG", (informe.get("tk9"), informe.get("svg")),
      (False, False))
    c("  y pinta con el pintor de Python", (informe.get("pintadas_python") or 0) > 0, True)
    c("  y da la versión de Tk", str(informe.get("tk", "")).startswith("8.6"), True)

sys.exit(c.report())
