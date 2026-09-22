#!/usr/bin/env python3
"""
Una sola instancia: la ventana, el servicio y el vigilante no se pisan.

Abrir runsync detiene el servicio anterior, así que dos ventanas a la vez se lo
quitarían la una a la otra. Aquí se comprueban las tres mitades de
evitarlo: que la segunda ventana no se abre y no toca el servicio, que el
registro se suelta al cerrar, y que el vigilante del equipo no lanza nada
mientras haya ventana o servicio vivos.
"""

import os
import sys
from pathlib import Path

from _harness import Checks, mkcfg, sandbox

import penwatch
import runsync
from common import model, store
from ui import prefs

c = Checks("una sola instancia de runsync")

CFG = mkcfg(["notas"])
MUERTO = 2 ** 22          # un pid que no existe (por encima del máximo habitual)


def registro(fichero: Path, pid: int, host: str) -> None:
    store.write_json(fichero, {"pid": pid, "host": host, "started": "2026-09-22 08:00:00"})


# --- las dos copias de las rutas, que no pueden separarse -------------------
# Lo primero, antes de que el resto del test reapunte estas constantes: penwatch
# no importa nada del proyecto, así que sabe estas rutas de memoria y solo un
# test puede atarlas a las de runsync.
c("el vigilante busca el registro de la ventana donde runsync lo escribe",
  str(penwatch.UI_LOCK_REL).replace("\\", "/"),
  f"{penwatch.APP_SUBDIR}/state/{runsync.UI_LOCK.name}")
c("y el del servicio también",
  str(penwatch.DAEMON_LOCK_REL).replace("\\", "/"),
  f"{penwatch.APP_SUBDIR}/state/{runsync.LOCK.name}")
c("y sabe llamar a este equipo como lo llama la UI", penwatch.HOST, prefs.HOST)


# --- el cerrojo de la ventana ----------------------------------------------
with sandbox():
    runsync.UI_LOCK = model.STATE_DIR / "ui.lock.json"
    runsync.LOCK = model.STATE_DIR / "daemon.lock.json"
    c("sin registro no hay ventana abierta", runsync.ui_en_marcha(), None)

    runsync.tomar_ui()
    abierta = runsync.ui_en_marcha()
    c("la ventana que lo toma consta como abierta",
      (abierta or {}).get("pid"), os.getpid())

    runsync.soltar_ui()
    c("y al soltarlo deja de constar", runsync.ui_en_marcha(), None)
    c("sin dejar el fichero detrás", runsync.UI_LOCK.exists(), False)

    registro(runsync.UI_LOCK, MUERTO, runsync.HOST)
    c("un pid muerto no cuenta", runsync.ui_en_marcha(), None)
    c("y se limpia el rastro", runsync.UI_LOCK.exists(), False)

    registro(runsync.UI_LOCK, os.getpid(), "otro-equipo")
    c("un registro de otro equipo tampoco", runsync.ui_en_marcha(), None)

    # Lo que de verdad importa: la segunda no arranca Y no para el servicio de
    # la primera. Si llegara a llamar a stop_previous_daemon(), el registro del
    # servicio desaparecería.
    registro(runsync.UI_LOCK, os.getpid(), runsync.HOST)
    registro(runsync.LOCK, os.getpid(), runsync.HOST)
    preguntado: list = []
    runsync.ui.start = lambda cfg, msg: preguntado.append(msg) or (None, None)
    runsync.model.load_config = lambda: CFG
    dicho: list[str] = []
    runsync.ui.fatal = lambda msg: dicho.append(msg) or 1

    rc = runsync.ui_flow()
    c("la segunda ventana no se abre", preguntado, [])
    c("lo dice en vez de abrirse en silencio",
      any("ya hay una ventana" in m.lower() for m in dicho), True)
    c("y no le quita el servicio a la primera", runsync.LOCK.exists(), True)
    c("con código de salida distinto de cero", rc, 1)

    # --auto también: lo llaman el vigilante, un acceso directo o un cron, y
    # arrancar el servicio por detrás de una ventana abierta pondría dos cosas a
    # sincronizar las mismas parejas.
    import builtins
    lanzado: list = []
    runsync.spawn_daemon = lambda pairs, mins: lanzado.append(pairs) or "ok"
    runsync.dlog = lambda msg: None
    real_print, builtins.print = builtins.print, lambda *a, **k: None
    try:
        rc = runsync.auto_start([])
    finally:
        builtins.print = real_print
    c("--auto no arranca el servicio con la ventana abierta", lanzado, [])
    c("y no es un error: no había nada que hacer", rc, 0)


# --- el vigilante, en el equipo --------------------------------------------
with sandbox() as raiz:
    penwatch.UI_LOCK_REL = Path("state/ui.lock.json")
    penwatch.DAEMON_LOCK_REL = Path("state/daemon.lock.json")
    ui_lock = raiz / penwatch.UI_LOCK_REL
    daemon_lock = raiz / penwatch.DAEMON_LOCK_REL

    c("sin nada en marcha, el vigilante lanza",
      penwatch.aplicacion_en_marcha(raiz), None)

    registro(ui_lock, os.getpid(), penwatch.HOST)
    c("con la ventana abierta, no lanza",
      "ventana" in (penwatch.aplicacion_en_marcha(raiz) or ""), True)

    registro(ui_lock, MUERTO, penwatch.HOST)
    c("una ventana que ya no existe no frena nada",
      penwatch.aplicacion_en_marcha(raiz), None)

    registro(ui_lock, os.getpid(), "otro-equipo")
    c("ni la ventana abierta en otro equipo",
      penwatch.aplicacion_en_marcha(raiz), None)

    ui_lock.unlink()
    registro(daemon_lock, os.getpid(), penwatch.HOST)
    c("con el servicio en marcha, tampoco lanza",
      "servicio" in (penwatch.aplicacion_en_marcha(raiz) or ""), True)

    ui_lock.write_text("esto no es json", encoding="utf-8")
    c("un registro ilegible no frena el arranque automático",
      "servicio" in (penwatch.aplicacion_en_marcha(raiz) or ""), True)
    daemon_lock.unlink()
    c("ni por sí solo", penwatch.aplicacion_en_marcha(raiz), None)

    # El vigilante NO escribe en el dispositivo: eso bloquearía su extracción.
    antes = sorted(p.name for p in (raiz / "state").iterdir())
    penwatch.aplicacion_en_marcha(raiz)
    c("y mirar no deja nada escrito en el dispositivo",
      sorted(p.name for p in (raiz / "state").iterdir()), antes)

# --- la fila de estado del vigilante ---------------------------------------
c("un disparo que no lanzó nada no se cuenta como fallo",
  penwatch._disparo_row({"last_launch": "hoy", "last_launch_ok": None,
                         "last_skip": "la ventana de runsync ya está abierta"}),
  "hoy — sin lanzar: la ventana de runsync ya está abierta")
c("uno que falló sí", penwatch._disparo_row({"last_launch": "hoy",
                                             "last_launch_ok": False}),
  "hoy (FALLÓ)")
c("y uno bueno no dice nada", penwatch._disparo_row({"last_launch": "hoy",
                                                     "last_launch_ok": True}), "hoy")

sys.exit(c.report())
