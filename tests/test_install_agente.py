#!/usr/bin/env python3
"""
Instalar el agente residente en el equipo (`install/agente.py`), y quitarlo.

Se comprueba, sin tocar el equipo de verdad: que el código y el Python van cada
uno a su carpeta por versión y no se vuelven a extraer si ya están; qué unidades
se ofrecen (la de penwatch, las enchufadas, las de la lista); que `agente.json`
lo escribe el instalador solo la primera vez y después se le pide al agente; que
penwatch se desinstala y se dice; el texto del registro (la tarea de Windows y el
autostart de Linux); la poda de versiones viejas; y que desinstalar no deja nada
del agente. Y dos reglas de dependencias: penwatch sigue sin importar nada del
proyecto, y el agente no carga Tk.
"""

import ast
import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path

from _harness import REPO, Checks, tmpdir

import penwatch
from common import equipo, store
from install import agente as ia
from install import platforms, runtime_bin, version

c = Checks("instalar el agente en el equipo")

equipo.DIR = tmpdir("prdrive-equipo-")
PW = tmpdir("prdrive-pw-")
penwatch.HOST_DIR = PW / "prdriveWatch"
penwatch.CONFIG_FILE = penwatch.HOST_DIR / "watch.json"
AUTOSTART = tmpdir("prdrive-autostart-") / "autostart" / "prdrive.desktop"
ia.autostart_file = lambda: AUTOSTART
ia.IS_WIN = False
ia.PARAR_ESPERA = 0.5
penwatch.candidate_roots = lambda cfg: list(RAICES)
RAICES: list[Path] = []


def archivo_runtime() -> Path:
    """Un python-build-standalone de mentira, con los intérpretes de las dos
    familias (así sirve en el equipo que ejecute el test)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for nombre in ("python/bin/python3", "python/python.exe", "python/pythonw.exe",
                       "python/lib/python3.13/os.py", "python/Lib/os.py"):
            datos = b"#!/bin/sh\n" if nombre.endswith("python3") else b"x"
            info = tarfile.TarInfo(nombre)
            info.size = len(datos)
            info.mode = 0o755
            tf.addfile(info, io.BytesIO(datos))
    ruta = tmpdir("prdrive-pbs-") / "cpython.tar.gz"
    ruta.write_bytes(buf.getvalue())
    return ruta


ARCHIVO = archivo_runtime()
pedidos_runtime = []
ia.conseguir_runtime = lambda plat, progreso=None: pedidos_runtime.append(plat) or ARCHIVO

# --- preparar: código y Python ---------------------------------------------------
prep = ia.preparar()
c("el código va a agente/<versión>/", prep.codigo, equipo.dir_codigo() / version())
for nombre in ("agente.py", "penwatch.py", "VERSION", "common/planificador.py",
               "common/equipo.py", "ui/tk_agente.py", "ui/prefs.py"):
    c(f"  con {nombre}", (prep.codigo / nombre).is_file(), True)
c("  sin lo del instalador", (prep.codigo / "install").exists(), False)
c("  ni cachés de bytecode", list(prep.codigo.rglob("__pycache__")), [])
plat = platforms.host()
c("el Python va a runtime/<id del sello>/",
  prep.python.relative_to(equipo.dir_runtimes()).parts[0], penwatch.stamp_id(prep.sello))
c("  y es el intérprete sin consola", prep.python.name,
  Path(plat.interprete).name)
c("  con su sello, escrito el último",
  (prep.python.parent / runtime_bin.STAMP).is_file()
  or (prep.python.parent.parent / runtime_bin.STAMP).is_file(), True)
antes = prep.python.stat().st_mtime_ns
otra = ia.preparar()
c("prepararlo otra vez no vuelve a extraer el mismo Python",
  (otra.python, otra.python.stat().st_mtime_ns), (prep.python, antes))
c("  ni deja carpetas de trabajo",
  [p.name for p in equipo.dir_codigo().iterdir()] +
  [p.name for p in equipo.dir_runtimes().iterdir()],
  [version(), penwatch.stamp_id(prep.sello)])

# --- las unidades que se ofrecen ----------------------------------------------------
penwatch.HOST_DIR.mkdir(parents=True)
store.write_json(penwatch.CONFIG_FILE, {"device_id": "p" * 32, "mode": "sync"})
ENCH = tmpdir("prdrive-ench-")
(ENCH / ".prdrive" / "state").mkdir(parents=True)
(ENCH / ".prdrive" / "PRDRIVE").write_text("id=" + "e" * 32 + "\n", encoding="utf-8")
(ENCH / ".prdrive" / "runsync.py").write_text("", encoding="utf-8")
store.write_json(ENCH / ".prdrive" / "state" / "fleet.json", {"nombre": "Azul"})
RAICES[:] = [ENCH]
ofrecidas = {x.id: x for x in ia.candidatas()}
c("se ofrece la que vigilaba penwatch, con su modo",
  (ofrecidas["p" * 32].modo, ofrecidas["p" * 32].origen), ("sync", "la vigilaba penwatch"))
c("y la enchufada, con su nombre, en modo daemon",
  (ofrecidas["e" * 32].nombre, ofrecidas["e" * 32].modo), ("Azul", equipo.DAEMON))

# --- agente.json: el instalador lo escribe una vez ------------------------------------
elegidas = {x.id: (x.modo, x.nombre) for x in ofrecidas.values()}
print("   ", ia.aplicar_unidades(elegidas, 90))
aj = equipo.leer_ajustes()
c("la primera vez, agente.json lo escribe el instalador",
  ({u: (x.modo, x.nombre) for u, x in aj.unidades.items()}, aj.espera_unidad_nueva),
  (elegidas, 90.0))
c("  y el buzón no se usa", equipo.buzon().exists(), False)
c("después, se ofrece también lo que ya está en la lista",
  ia.candidatas()[0].origen, "ya en la lista del agente")
contenido = equipo.ajustes_json().read_bytes()
ia.aplicar_unidades({"e" * 32: (equipo.UI, "Azul"), "n" * 32: (equipo.DAEMON, "Nueva")},
                    60)
c("con agente.json ya escrito, el instalador no lo toca",
  equipo.ajustes_json().read_bytes(), contenido)
peticiones = equipo.recoger()
c("  se lo pide al agente: los modos que cambian y las nuevas, y el plazo",
  [(p["pide"], p.get("id", p.get("clave"))[:1], p.get("modo", p.get("valor")))
   for p in peticiones],
  [("modo", "e", "ui"), ("modo", "n", "daemon"), ("ajuste", "e", 60)])

# --- penwatch fuera --------------------------------------------------------------
llamado = []
penwatch.unregister = lambda: llamado.append("unregister") or ["Tarea eliminada."]
penwatch.stop_running_watcher = lambda: llamado.append("stop") or None
msgs = ia.quitar_penwatch()
c("penwatch se desregistra y se para", llamado, ["unregister", "stop"])
c("  su carpeta del equipo desaparece", penwatch.HOST_DIR.exists(), False)
c("  y se dice que el agente lo sustituye",
  any("sustituye a penwatch" in m for m in msgs), True)
c("sin penwatch, no hay nada que decir", ia.quitar_penwatch(), [])

# --- el registro -------------------------------------------------------------------
print("   ", ia.registrar(prep))
texto = AUTOSTART.read_text(encoding="utf-8")
c("Linux: autostart XDG que arranca el agente con su Python",
  f'Exec="{prep.python}" "{prep.codigo / "agente.py"}" "run"' in texto, True)
c("  oculto del menú", "NoDisplay=true" in texto, True)
xml = penwatch.task_xml("EQUIPO\\ana", r"C:\Users\ana\AppData\Local\prdrive\runtime\x\pythonw.exe",
                        r'"C:\Users\ana\AppData\Local\prdrive\agente\0.4.0\agente.py" run',
                        r"C:\Users\ana\AppData\Local\prdrive", ia.DESCRIPCION)
c("Windows: la tarea arranca el pythonw del agente",
  r"<Command>C:\Users\ana\AppData\Local\prdrive\runtime\x\pythonw.exe</Command>" in xml, True)
c("  con agente.py run", "agente.py&quot; run</Arguments>" in xml
  or 'agente.py" run</Arguments>' in xml, True)
c("  a batería también", "<DisallowStartIfOnBatteries>false" in xml, True)
c("  y sin límite de tiempo", "<ExecutionTimeLimit>PT0S" in xml, True)
c("  con su descripción", ia.DESCRIPCION in xml, True)
c("  y la de penwatch sigue siendo la suya",
  penwatch.TASK_DESCRIPTION in penwatch.task_xml("u", "c", "a", "w",
                                                 penwatch.TASK_DESCRIPTION), True)
c("Exec cita cada argumento (una ruta con espacios no se parte)",
  penwatch.desktop_exec(["/home/ana maría/py", "run"]), '"/home/ana maría/py" "run"')
c("  y escapa lo especial dos veces, como pide la especificación",
  penwatch.desktop_exec(['a"$b\\c', "50%"]), '"a\\\\"\\\\$b\\\\\\\\c" "50%%"')

# --- activar: todo junto -------------------------------------------------------------
(equipo.dir_codigo() / "0.0.1").mkdir()
(equipo.dir_runtimes() / "viejo").mkdir()
lanzados = []
ia.lanzar = lambda args, **kw: lanzados.append((args, kw))
msgs = ia.activar(prep, {"e" * 32: (equipo.DAEMON, "Azul")}, 120)
inst = equipo.leer_instalacion()
c("instalacion.json dice dónde está todo",
  (inst.get("version"), inst.get("codigo"), inst.get("python")),
  (version(), str(prep.codigo), str(prep.python)))
c("el agente cuenta como instalado", equipo.instalado(), True)
c("las versiones viejas del código se recogen",
  sorted(p.name for p in equipo.dir_codigo().iterdir()), [version()])
c("  y las del Python", sorted(p.name for p in equipo.dir_runtimes().iterdir()),
  [penwatch.stamp_id(prep.sello)])
c("y se arranca con su orden, fuera de toda unidad",
  (lanzados[-1][0], lanzados[-1][1].get("cwd")),
  (ia.orden(prep.python, prep.codigo), str(equipo.DIR)))

# --- la línea de órdenes del instalador -------------------------------------------------
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("instalador", REPO / "prdrive-install.py")
instalador = importlib.util.module_from_spec(spec)
spec.loader.exec_module(instalador)
c("--instalar-agente se entiende", instalador.parse_args(["--instalar-agente"]).instalar_agente,
  True)
c("--desinstalar-agente también",
  instalador.parse_args(["--desinstalar-agente"]).desinstalar_agente, True)

# --- desinstalar ------------------------------------------------------------------------
msgs = ia.desinstalar()
c("desinstalar quita el autostart", AUTOSTART.exists(), False)
c("  y la carpeta del agente entera", equipo.DIR.exists(), False)
c("  y dice que las unidades no se han tocado", msgs[-1], "Las unidades no se han tocado.")
c("la unidad enchufada sigue como estaba",
  (ENCH / ".prdrive" / "PRDRIVE").read_text(encoding="utf-8"), "id=" + "e" * 32 + "\n")
c("ya no cuenta como instalado", equipo.instalado(), False)

# --- las reglas de dependencias ------------------------------------------------------------
importados = set()
for nodo in ast.walk(ast.parse((REPO / "penwatch.py").read_text(encoding="utf-8"))):
    if isinstance(nodo, ast.Import):
        importados |= {a.name.split(".")[0] for a in nodo.names}
    elif isinstance(nodo, ast.ImportFrom) and nodo.module:
        importados.add(nodo.module.split(".")[0])
c("penwatch sigue sin importar nada del proyecto",
  sorted(importados & {"common", "ui", "install", "agente", "sync", "runsync"}), [])

res = subprocess.run(
    [sys.executable, "-c",
     "import sys; sys.path.insert(0, sys.argv[1]); import agente; "
     "from common import planificador, avisos, dbus, moderacion, equipo; "
     "print('tkinter' in sys.modules)", str(REPO)],
    capture_output=True, text=True, cwd=str(REPO))
c("el agente, el planificador, los avisos y el D-Bus no cargan Tk",
  res.stdout.strip() or res.stderr.strip()[-200:], "False")

raise SystemExit(c.report())
