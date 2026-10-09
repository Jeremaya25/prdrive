#!/usr/bin/env python3
"""Los imports perezosos: lo que carga cada punto de entrada y lo que se precarga después.

Los módulos pesados (`bisync`, `revision`, `update` con `urllib` y `zipfile`,
las pantallas que solo abre un clic, el llavero) se importan DENTRO de la
función que los usa, no arriba: arriba, cada ventana, la pregunta del agente y
el servicio los pagan aunque no los usen. Esto vigila que no vuelvan a subir:

- Qué módulos quedan cargados al importar `ui`, `ui.tk`, `runsync`,
  `common.update` y `pregunta`, en un proceso limpio cada uno.
- Que lo que `main_window()` (y la vista que dibuja, `ui/tk_principal.py`)
  importa tarde está en `PRECARGA`: la lista que se importa a ratos tras el
  primer pintado y, entera, antes de aplicar una actualización (a partir de ahí
  los ficheros cambian bajo el proceso, y un módulo importado por primera vez
  se leería nuevo junto a los viejos).
- Que el primer pintado de la ventana principal no carga lo que lee el
  dispositivo (averías, conflictos, componentes, penwatch): eso llega con la
  lectura que se lanza después, y entonces sí.
- Cómo se precarga: de uno en uno, con `after`, sin ventana, y en
  `tk_update` justo antes de aplicar (si hay entorno gráfico).
"""

import ast
import json
import subprocess
import sys
from types import SimpleNamespace

from _harness import REPO, Checks, sandbox

c = Checks("imports perezosos")


def cargados(*importaciones: str) -> set[str]:
    """Devuelve los módulos que quedan cargados tras esos `import`, en un proceso limpio."""
    codigo = "; ".join(f"import {m}" for m in importaciones) + (
        "; import sys, json; print(json.dumps(sorted(sys.modules)))")
    proc = subprocess.run([sys.executable, "-c", codigo], cwd=str(REPO), capture_output=True,
                          text=True, timeout=120)
    return set(json.loads(proc.stdout))


PESADOS = {"common.bisync", "common.results", "common.revision", "common.conflicts",
           "common.planificador", "common.historial", "common.huella", "common.update",
           "common.components", "common.llavero", "common.keepassxc",
           "common.fleet", "common.cifrada", "urllib.request", "zipfile"}
"""Lo que ninguno de estos puntos de entrada tiene por qué cargar al importarse."""

for entrada in ("ui", "ui.tk", "runsync", "common.update", "pregunta"):
    c(f"import {entrada}: no carga nada de lo pesado",
      sorted((PESADOS - {entrada}) & cargados(entrada)), [])
c("import ui.tk: ni una sola pantalla suelta",
  sorted(m for m in cargados("ui.tk") if m.startswith("ui.tk_")), [])
ENTRADA = cargados("pregunta")
c("import pregunta: llega a la ventanita, y no al agente ni a tkinter (que ha de ir después de `ui`)",
  ("ui.tk_agente" in ENTRADA, "agente" in ENTRADA, "common.equipo" in ENTRADA,
   "tkinter" in ENTRADA), (True, False, False, False))

# nada de eso sube otra vez a la cabecera de los módulos: se mira el árbol, no solo el proceso
ARRIBA = {"ui/__init__.py": {"bisync", "results", "revision"},
          "ui/tk.py": {"components", "conflicts", "revision", "update"},
          "common/update.py": {"urllib", "zipfile"},
          "runsync.py": {"keepassxc", "llavero", "update"}}


def importados_arriba(ruta: str) -> set[str]:
    """Devuelve los nombres que importa el cuerpo del módulo (no sus funciones)."""
    arbol = ast.parse((REPO / ruta).read_text(encoding="utf-8"))
    nombres: set[str] = set()
    for nodo in arbol.body:
        if isinstance(nodo, ast.Import):
            nombres |= {a.name.split(".")[0] for a in nodo.names}
        elif isinstance(nodo, ast.ImportFrom):
            nombres |= {a.name for a in nodo.names} | {(nodo.module or "").split(".")[0]}
    return nombres


for ruta, prohibidos in ARRIBA.items():
    c(f"{ruta}: no los importa arriba", sorted(prohibidos & importados_arriba(ruta)), [])

# PRECARGA no deja fuera nada de lo que se importa tarde
from ui import tk as uitk  # noqa: E402


def _importados_en(funcion: ast.AST, cabecera: set[int]) -> set[str]:
    """Devuelve lo que se importa de `ui` o `common` dentro de `funcion`, salvo esos nodos."""
    nombres: set[str] = set()
    for nodo in ast.walk(funcion):
        if not isinstance(nodo, ast.ImportFrom) or id(nodo) in cabecera:
            continue
        if nodo.level == 1 and not nodo.module:
            nombres |= {f"ui.{a.name}" for a in nodo.names}
        elif nodo.level == 1:
            nombres.add(f"ui.{nodo.module}")
        elif nodo.module == "common":
            nombres |= {f"common.{a.name}" for a in nodo.names}
    return nombres


def importados_tarde() -> set[str]:
    """Devuelve lo que la principal importa después de pintarse.

    Es lo de dentro de `main_window()` en `ui/tk.py`, salvo su cabecera (lo
    que se importa antes del primer pintado), y lo de dentro de cualquier
    función de `ui/tk_principal.py`, la vista que dibuja.
    """
    arbol = ast.parse((REPO / "ui" / "tk.py").read_text(encoding="utf-8"))
    nombres: set[str] = set()
    for funcion in arbol.body:
        if isinstance(funcion, ast.FunctionDef) and funcion.name == "main_window":
            nombres |= _importados_en(funcion, {id(n) for n in funcion.body})
    vista = ast.parse((REPO / "ui" / "tk_principal.py").read_text(encoding="utf-8"))
    for nodo in vista.body:
        if isinstance(nodo, (ast.FunctionDef, ast.ClassDef)):
            nombres |= _importados_en(nodo, set())
    return nombres


YA_CARGADOS = cargados("ui.tk")
"""Lo que `import ui.tk` ya trae: no hace falta precargarlo."""
TARDE = importados_tarde()
c("se ven los imports tardíos de la principal y de su vista",
  {"ui.instantanea", "ui.tk_pairs", "ui.watch"} <= TARDE, True)
c("PRECARGA y PRECARGA_LLAVERO cubren todo lo que la principal importa tarde",
  sorted(TARDE - YA_CARGADOS - set(uitk.PRECARGA) - set(uitk.PRECARGA_LLAVERO)), [])
c("  y todo lo que listan existe",
  sorted(n for n in uitk.PRECARGA + uitk.PRECARGA_LLAVERO
         if not (REPO / (n.replace(".", "/") + ".py")).is_file()), [])

# precarga_de: el llavero solo con [keychain]
from _harness import mkcfg  # noqa: E402
from common import model  # noqa: E402

c("precarga_de: sin [keychain], solo las pantallas", uitk.precarga_de(mkcfg(["a"])), uitk.PRECARGA)
con_llavero = model.parse_config({
    "defaults": {"remote": "nas"}, "keychain": {"base": "personal.kdbx"},
    "pair": [{"name": "a", "local": "sync-data/a", "remote_path": "/R/a"}]})
c("  con [keychain], también el llavero", uitk.precarga_de(con_llavero),
  uitk.PRECARGA + uitk.PRECARGA_LLAVERO)

# precargar: importa lo que falta y no cuenta lo que falla
c("precargar no lanza aunque el módulo no exista", uitk.precargar(("ui.no_existe",)), None)
uitk.precargar(("ui.tk_watch",))
c("  e importa lo que se le pide", "ui.tk_watch" in sys.modules, True)

# precargar_a_ratos: de uno en uno, por el bucle, sin ventana de por medio
importados: list = []
real_precargar = uitk.precargar
uitk.precargar = lambda nombres=(): importados.append(tuple(nombres))


class Raiz:
    """Una ventana de mentira: apunta lo que se le agenda con `after`, y no lo ejecuta."""

    def __init__(self) -> None:
        self.agendado: list = []

    def after(self, ms, funcion):
        self.agendado.append((ms, funcion))


raiz_falsa = Raiz()
try:
    uitk.precargar_a_ratos(raiz_falsa, ("a", "b", "c"))
    c("precargar_a_ratos: agenda el primero y no importa nada todavía",
      (len(raiz_falsa.agendado), raiz_falsa.agendado[0][0], importados),
      (1, uitk.PAUSA_PRECARGA_MS, []))
    turnos = []
    while raiz_falsa.agendado:
        raiz_falsa.agendado.pop(0)[1]()
        turnos.append((len(importados), len(raiz_falsa.agendado)))
    c("  un import por turno, y agenda el siguiente solo si queda alguno", turnos,
      [(1, 1), (2, 1), (3, 0)])
    c("  en el orden dado", importados, [("a",), ("b",), ("c",)])
    importados.clear()
    uitk.precargar_a_ratos(Raiz(), ())
    c("  sin nada que importar, no agenda nada", importados, [])
finally:
    uitk.precargar = real_precargar

# antes de aplicar una actualización, y con la ventana de verdad
try:
    import tkinter as tk
    from tkinter import messagebox
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from common import update  # noqa: E402
from ui import tk_update  # noqa: E402

NUEVA = update.Release("v9.9.9", "9.9.9", "9.9.9", "https://github.com/Jeremaya25/prdrive/releases/tag/v9.9.9",
                       "2026-10-08T00:00:00Z", "notas")
orden: list = []


def pulsar_actualizar(dlg, parent=None) -> None:
    """Sustituye a `mostrar()`: pulsa «Actualizar ahora» en vez de enseñar la ventana."""
    pila, botones = [dlg], []
    while pila:
        w = pila.pop()
        pila += list(w.winfo_children())
        if w.winfo_class() == "TButton" and w.cget("text") == "Actualizar ahora":
            botones.append(w)
    for b in botones:
        b.invoke()
    try:
        dlg.destroy()
    except tk.TclError:
        pass


def en_el_acto(parent, titulo, funcion, mensaje="", **_k):
    """Sustituye a `working()`: hace el trabajo en el sitio."""
    return True, funcion()


with sandbox():
    reales = (tk_update.mostrar, tk_update.working, tk_update.output_window, tk_update.precargar,
              update.download, update.apply_command, update.relaunch_command,
              messagebox.askokcancel, messagebox.showinfo, subprocess.Popen)
    tk_update.mostrar = pulsar_actualizar
    tk_update.working = en_el_acto
    tk_update.output_window = lambda titulo, orden_sync, **k: orden.append("aplicar") or 0
    tk_update.precargar = lambda nombres=(): orden.append(("precargar", tuple(nombres)))
    update.download = lambda tag, destino, progreso=None: orden.append("descargar") or destino
    update.apply_command = lambda staged, raiz_, python=None: ["aplicar"]
    update.relaunch_command = lambda: ["relanzar"]
    messagebox.askokcancel = lambda *a, **k: True
    messagebox.showinfo = lambda *a, **k: None
    popen_real = subprocess.Popen
    subprocess.Popen = lambda args, *a, **k: (orden.append("relanzar") if args == ["relanzar"]
                                              else popen_real(args, *a, **k))
    try:
        tk_update.open_dialog(raiz, NUEVA)
    finally:
        (tk_update.mostrar, tk_update.working, tk_update.output_window, tk_update.precargar,
         update.download, update.apply_command, update.relaunch_command,
         messagebox.askokcancel, messagebox.showinfo, subprocess.Popen) = reales
    c("actualizar: precarga justo antes de aplicar, con las pantallas y el llavero",
      orden, ["descargar", ("precargar", uitk.PRECARGA + uitk.PRECARGA_LLAVERO), "aplicar",
              "relanzar"])

raiz.destroy()

# el primer pintado de la principal no lee el dispositivo: eso llega después
#
# En un proceso limpio, como un arranque de verdad. La sonda que sustituye al
# bucle de eventos mira qué hay cargado ANTES de dejar que Tk haga lo que tiene
# pendiente (la lectura del dispositivo, que con `en_el_acto` llega ahí mismo) y
# DESPUÉS.
PRIMER_PINTADO = r"""
import json, shutil, sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import ui
import tkinter as tk
from common import model, update
from ui import prefs, segundo_plano
from ui import tk as uitk

# Sin `_harness`: importa el agente y el llavero, que traen lo que se vigila.
raiz = Path(tempfile.mkdtemp(prefix="prdrive-imports-"))
model.STATE_DIR, model.FILTERS_DIR, model.LOG_DIR = (raiz / "state", raiz / "filters",
                                                     raiz / "logs")
model.DEVICE_ROOT, model.CONFIG_FILE = raiz, raiz / "sync_config.toml"
model.RCLONE_CONF = raiz / "rclone.conf"
for carpeta in (model.STATE_DIR, model.FILTERS_DIR, model.LOG_DIR):
    carpeta.mkdir()
update.pending = lambda root=None: None
update.check = lambda force=False: (None, None)
prefs.PREFS = model.STATE_DIR / "ui_prefs.json"
segundo_plano.lanzar = segundo_plano.en_el_acto
VIGILADOS = ("common.revision", "common.conflicts", "common.components", "penwatch")
visto = {}


def sonda(self, *a, **k):
    visto["antes"] = [m for m in VIGILADOS if m in sys.modules]
    from common import equipo
    equipo.instalado = lambda: False      # sin agente: el arranque es cosa de penwatch
    self.update_idletasks()
    visto["despues"] = [m for m in VIGILADOS if m in sys.modules]
    visto["fallos"] = dict(self.instantanea.resultado.fallos)
    for pendiente in self.tk.splitlist(self.tk.call("after", "info")):
        self.after_cancel(pendiente)
    self.destroy()


tk.Tk.mainloop = sonda
parejas = [{"name": n, "local": f"sync-data/{n}", "remote_path": f"/R/{n}"} for n in "ab"]
try:
    uitk.main_window(model.parse_config({"defaults": {"remote": "nas"}, "pair": parejas}),
                     None)
finally:
    shutil.rmtree(raiz, ignore_errors=True)
print(json.dumps(visto))
"""
hijo = subprocess.run([sys.executable, "-c", PRIMER_PINTADO, str(REPO)], cwd=str(REPO),
                      capture_output=True, text=True, timeout=120)
try:
    pintado = json.loads(hijo.stdout.strip().splitlines()[-1])
except (IndexError, ValueError):
    pintado = {"error": hijo.stderr[-600:]}
c("main_window: el primer pintado no carga revision, conflicts, components ni penwatch",
  pintado.get("antes", pintado), [])
c("  y con la lectura, que llega después, sí",
  pintado.get("despues", pintado),
  ["common.revision", "common.conflicts", "common.components", "penwatch"])
c("  sin que fallara ningún lector", pintado.get("fallos", pintado), {})

sys.exit(c.report())
