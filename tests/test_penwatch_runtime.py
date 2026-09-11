#!/usr/bin/env python3
"""
El Python del vigilante: una copia propia en el equipo, no el del sistema.

Antes penwatch apuntaba la tarea programada al `sys.executable` con el que se
instaló, y eso se rompía en silencio el día que alguien actualizaba o
desinstalaba su Python. Ahora copia el Python del dispositivo a su carpeta del
equipo y arranca con esa copia, así que:

  * la copia va en una carpeta por versión (`runtime/<id>/`), y cambiar de
    versión es copiar al lado y cambiar el puntero de `watch.json` —de golpe—,
    porque en Windows no se puede sustituir la carpeta de un `pythonw.exe` que
    está corriendo, y el vigilante corre justo desde ahí;
  * en cada detección compara el sello del dispositivo con el de su copia, y si
    difieren la refresca y vuelve a registrar la tarea;
  * si el dispositivo no lleva Python para este equipo, usa el del sistema y lo
    dice en `status`.

Nada de esto registra una tarea de verdad ni toca el dispositivo real: las rutas
del equipo se apuntan a un temporal y el registro se sustituye.
"""

import sys
from pathlib import Path

from _harness import Checks, tmpdir

import penwatch
from common import pins
from install import platforms, runtime_bin

c = Checks("penwatch: su propio Python en el equipo")

# --- las constantes que penwatch repite ------------------------------------------
c("el nombre del sello es el mismo que escribe el instalador",
  penwatch.RUNTIME_STAMP, runtime_bin.STAMP)
c("y la carpeta del runtime en el dispositivo",
  str(penwatch.RUNTIME_SUBDIR),
  str(Path(penwatch.APP_SUBDIR) / runtime_bin.RUNTIME_SUBDIR))
# El orden en que prueba los runtimes es el del .bat y el del instalador: si no,
# el vigilante arrancaría con un Python y el lanzador con otro.
for so, arch in (("windows", "arm64"), ("windows", "x64"), ("linux", "x64"),
                 ("linux", "arm64")):
    claves = penwatch.runtime_keys_for(so, arch)
    anfitrion = pins.plataforma_para(so, "arm" if arch == "arm64" else "x64")
    c(f"{so} {arch}: mismo orden que el instalador", claves,
      [p.clave for p in platforms.candidates(anfitrion)])
c("macOS no tiene runtime", penwatch.runtime_keys_for("darwin", "arm64"), [])
c("el intérprete de Windows", penwatch.interpreter_rel("windows-x64"), "python.exe")
c("y el de Linux", penwatch.interpreter_rel("linux-arm64"), "bin/python3")

# --- un equipo de mentira -----------------------------------------------------------
equipo = tmpdir("prdrive-equipo-")
for nombre in ("HOST_DIR", "RUNTIMES_DIR", "CONFIG_FILE", "STATE_FILE", "LOG_FILE",
               "STOP_FILE"):
    setattr(penwatch, nombre, {
        "HOST_DIR": equipo, "RUNTIMES_DIR": equipo / "runtime",
        "CONFIG_FILE": equipo / "watch.json", "STATE_FILE": equipo / "state.json",
        "LOG_FILE": equipo / "penwatch.log", "STOP_FILE": equipo / "stop"}[nombre])
penwatch.host_runtime_keys = lambda: ["windows-x64"]
registradas: list[dict] = []
penwatch.register = lambda cfg: registradas.append(dict(cfg)) or "registrado"


def dispositivo_con_python(clave="windows-x64", sello="release = 1\n") -> Path:
    raiz = tmpdir("prdrive-dispositivo-")
    d = raiz / penwatch.RUNTIME_SUBDIR / clave
    (d / "Lib").mkdir(parents=True)
    for exe in ("python.exe", "pythonw.exe"):
        (d / exe).write_bytes(b"MZ " + sello.encode())
    (d / "Lib" / "os.py").write_text("# os\n", encoding="utf-8")
    (d / penwatch.RUNTIME_STAMP).write_text(sello, encoding="utf-8")
    return raiz


pen = dispositivo_con_python()
encontrado = penwatch.device_runtime(pen)
c("encuentra el Python del dispositivo para este equipo",
  (encontrado[0], encontrado[2]) if encontrado else None, ("windows-x64", "release = 1\n"))

penwatch.host_runtime_keys = lambda: ["windows-arm64", "windows-x64"]
c("un ARM64 sin el suyo se queda con el x64", penwatch.device_runtime(pen)[0],
  "windows-x64")
penwatch.host_runtime_keys = lambda: ["windows-x64"]

a_medias = dispositivo_con_python()
(a_medias / penwatch.RUNTIME_SUBDIR / "windows-x64" / "python.exe").unlink()
c("sin intérprete no hay runtime", penwatch.device_runtime(a_medias), None)

# --- instalar: copiar y apuntar a la copia -----------------------------------------
python, runtime, nota = penwatch.choose_python(pen)
copia = penwatch.RUNTIMES_DIR / penwatch.stamp_id("release = 1\n")
c("se copia al equipo, en una carpeta por versión", Path(python), copia / "python.exe")
c("con todo lo suyo", (copia / "Lib" / "os.py").is_file(), True)
c("y su sello", (copia / penwatch.RUNTIME_STAMP).read_text(encoding="utf-8"),
  "release = 1\n")
c("se apunta qué runtime es", (runtime["key"], runtime["stamp"]),
  ("windows-x64", "release = 1\n"))
c("sin nota: no hace falta ninguna", nota, "")
c("sin carpetas de trabajo olvidadas", [p.name for p in penwatch.RUNTIMES_DIR.iterdir()],
  [copia.name])
c("copiar otra vez lo mismo no cambia nada", penwatch.choose_python(pen)[0], python)

cfg = {"mode": "ui", "python_exe": python, "runtime": runtime, "task_python": python}
penwatch.write_json(penwatch.CONFIG_FILE, cfg)

# --- en cada detección: mismo sello, nada que hacer ---------------------------------
registradas.clear()
c("con el mismo sello no se refresca nada", penwatch.refresh_runtime(pen, cfg), cfg)
c("ni se vuelve a registrar la tarea", registradas, [])

# --- el dispositivo trae otra versión: copia al lado y cambio de puntero -------------
nuevo_pen = dispositivo_con_python(sello="release = 2\n")
nuevo = penwatch.refresh_runtime(nuevo_pen, cfg)
copia2 = penwatch.RUNTIMES_DIR / penwatch.stamp_id("release = 2\n")
c("otra versión se copia a su propia carpeta", Path(nuevo["python_exe"]),
  copia2 / "python.exe")
c("con el sello nuevo", nuevo["runtime"]["stamp"], "release = 2\n")
c("el puntero queda guardado en watch.json",
  penwatch.read_json(penwatch.CONFIG_FILE)["python_exe"], nuevo["python_exe"])
c("la tarea se vuelve a registrar con el Python nuevo",
  [r["python_exe"] for r in registradas], [nuevo["python_exe"]])
c("y se apunta que la tarea ya usa ese", nuevo["task_python"], nuevo["python_exe"])
c("la copia vieja se recoge: nadie la usa ya",
  sorted(p.name for p in penwatch.RUNTIMES_DIR.iterdir()), [copia2.name])

# Si no se puede volver a registrar, la tarea sigue apuntando a la copia vieja: esa
# NO se puede recoger, o el próximo inicio de sesión no arrancaría nada.
def registro_roto(_cfg):
    raise RuntimeError("schtasks dice que no")


penwatch.register = registro_roto
tercero = penwatch.refresh_runtime(dispositivo_con_python(sello="release = 3\n"), nuevo)
c("sin registro, el vigilante usa igual la copia nueva para lanzar",
  Path(tercero["python_exe"]).parent.name, penwatch.stamp_id("release = 3\n"))
c("pero la tarea sigue con la de antes", tercero["task_python"], nuevo["python_exe"])
c("y esa no se borra",
  sorted(p.name for p in penwatch.RUNTIMES_DIR.iterdir()),
  sorted([copia2.name, penwatch.stamp_id("release = 3\n")]))
c.contains("y queda dicho en el diario",
           penwatch.LOG_FILE.read_text(encoding="utf-8"), "schtasks dice que no")
penwatch.register = lambda cfg: registradas.append(dict(cfg)) or "registrado"

# --- la detección lo hace antes de lanzar -------------------------------------------
penwatch.write_json(penwatch.CONFIG_FILE, tercero)
penwatch.write_json(penwatch.STATE_FILE, {})
cuarto_pen = dispositivo_con_python(sello="release = 4\n")
lanzados: list[str] = []
reales = (penwatch.find_pen, penwatch.launch)
penwatch.find_pen = lambda cfg: cuarto_pen
penwatch.launch = lambda root, cfg: lanzados.append(cfg["python_exe"]) or True
try:
    penwatch.watch_loop(once=True)
finally:
    penwatch.find_pen, penwatch.launch = reales
c("al detectar el dispositivo se refresca ANTES de lanzar runsync",
  [Path(p).parent.name for p in lanzados], [penwatch.stamp_id("release = 4\n")])

# --- un dispositivo sin Python para este equipo: el del sistema, y se dice ------------
ligero = tmpdir("prdrive-ligero-")
python, runtime, nota = penwatch.choose_python(ligero)
c("sin runtime propio se usa el Python del equipo", python, sys.executable)
c("sin runtime apuntado", runtime, None)
c.contains("y la nota dice por qué", nota, "no lleva Python")

penwatch.write_json(penwatch.CONFIG_FILE, {"mode": "ui", "python_exe": python,
                                           "runtime": None, "runtime_note": nota})
reales = (penwatch.find_pen, penwatch.registered_state)
penwatch.find_pen = lambda cfg: None
penwatch.registered_state = lambda: "tarea: de mentira"
try:
    filas = dict(penwatch.status_rows())
finally:
    penwatch.find_pen, penwatch.registered_state = reales
c.contains("status enseña con qué Python arranca", filas.get("Python del vigilante", ""),
           python)
c.contains("y que es el del equipo, con la nota", filas.get("Python del vigilante", ""),
           "no lleva Python")

# Un Python que vive DENTRO del dispositivo no vale: al desenchufarlo la tarea
# se quedaría sin intérprete.
penwatch.host_python = lambda root: None
try:
    penwatch.choose_python(ligero)
    c("sin runtime y sin Python en el equipo no se instala", "siguió", "RuntimeError")
except RuntimeError as e:
    c("sin runtime y sin Python en el equipo no se instala", "RuntimeError", "RuntimeError")
    c.contains("y se dice cómo se arregla", str(e), "Añadir plataformas")

sys.exit(c.report())
