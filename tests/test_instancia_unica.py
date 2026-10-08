#!/usr/bin/env python3
"""Una sola instancia: la ventana, el servicio y el vigilante no se pisan.

Abrir runsync detiene el servicio anterior, así que dos ventanas a la vez se lo
quitarían la una a la otra. Aquí se comprueban las tres mitades de evitarlo:
que la segunda ventana no se abre y no toca el servicio, que el registro se
suelta al cerrar, y que el vigilante del equipo no lanza nada mientras haya
ventana o servicio vivos.
"""

import os
import sys
from pathlib import Path

from _harness import Checks, mkcfg, sandbox

import penwatch
import runsync
from common import llavero, model, store
from ui import prefs, repair, tk_update

c = Checks("una sola instancia de runsync")

CFG = mkcfg(["notas"])
MUERTO = 2 ** 22          # un pid que no existe (por encima del máximo habitual)
ARRANQUE = 1_800_000_000.0  # el arranque del sistema de las pruebas, fijo


def registro(fichero: Path, pid: int, host: str, arranque: float | None = None) -> None:
    """Escribe un registro de ventana o servicio con ese pid y ese equipo.

    Sin `arranque` es el de una versión de antes, que no lo apuntaba.
    """
    datos = {"pid": pid, "host": host, "started": "2026-09-22 08:00:00"}
    if arranque is not None:
        datos["arranque"] = arranque
    store.write_json(fichero, datos)


# las dos copias de las rutas, que no pueden separarse
#
# Lo primero, antes de que el resto del test reapunte estas constantes:
# penwatch no importa nada del proyecto, así que sabe estas rutas de memoria y
# solo un test puede atarlas a las de runsync.
c("el vigilante busca el registro de la ventana donde runsync lo escribe",
  str(penwatch.UI_LOCK_REL).replace("\\", "/"),
  f"{penwatch.APP_SUBDIR}/state/{runsync.UI_LOCK.name}")
c("y el del servicio también",
  str(penwatch.DAEMON_LOCK_REL).replace("\\", "/"),
  f"{penwatch.APP_SUBDIR}/state/{runsync.LOCK.name}")
c("y sabe llamar a este equipo como lo llama la UI", penwatch.HOST, prefs.HOST)


# el cerrojo de la ventana
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

    # tomarlo es atómico
    #
    # Lo que pasó el 28/09/2026: dos runsync con 6 s de diferencia miraron los
    # dos, no vieron a nadie y abrieron dos ventanas, porque mirar y escribir
    # eran dos pasos. Tomar ES mirar: la segunda toma sin soltar la primera
    # tiene que perder.
    runsync.UI_LOCK.unlink(missing_ok=True)
    c("la primera toma se la queda", runsync.tomar_ui(), None)
    segunda = runsync.tomar_ui()
    c("la segunda, sin soltar la primera, pierde", segunda is not None, True)
    c("y sabe quién la tiene", (segunda or {}).get("pid"), os.getpid())
    runsync.soltar_ui()
    c("soltada, se puede volver a tomar", runsync.tomar_ui(), None)
    runsync.soltar_ui()

    registro(runsync.UI_LOCK, MUERTO, runsync.HOST)
    c("un resto de una ventana muerta no impide tomarla", runsync.tomar_ui(), None)
    c("y el registro pasa a ser el nuestro",
      store.read_json(runsync.UI_LOCK).get("pid"), os.getpid())
    runsync.soltar_ui()

    registro(runsync.UI_LOCK, os.getpid(), "otro-equipo")
    c("ni uno de otro equipo", runsync.tomar_ui(), None)
    runsync.soltar_ui()

    # Limpiar un resto no puede llevarse por delante un registro recién tomado:
    # si entre leer el resto y retirarlo otra ventana lo ha sustituido por el
    # suyo, retirar tiene que dejarlo donde estaba.
    resto = {"pid": MUERTO, "host": runsync.HOST, "started": "2026-09-22 08:00:00"}
    registro(runsync.UI_LOCK, os.getpid(), runsync.HOST)
    vivo = store.read_json(runsync.UI_LOCK)
    c("retirar un resto que ya no está no retira nada",
      runsync._retirar_ui(resto), False)
    c("y el registro vivo sigue en su sitio", store.read_json(runsync.UI_LOCK), vivo)
    c("sin dejar ficheros de paso", sorted(p.name for p in model.STATE_DIR.iterdir()
                                           if p.name.startswith("ui.lock")),
      ["ui.lock.json"])
    runsync.UI_LOCK.unlink()

    # Un registro a medio escribir (creado y aún vacío) es de alguien que lo
    # está tomando, no un resto; si sigue vacío pasado el margen, sí lo es.
    runsync.UI_LOCK.write_bytes(b"")
    runsync.ESPERA_REGISTRO = 0.05
    c("un registro vacío que no llega a escribirse es un resto",
      runsync.tomar_ui(), None)
    runsync.soltar_ui()

    # Retirar un resto pide antes su propio cerrojo; si quien lo tenía murió
    # con él puesto, pasado un rato se da por abandonado y no bloquea nada.
    romper = runsync.UI_LOCK.with_name(runsync.UI_LOCK.name + ".romper")
    romper.write_text(str(MUERTO), encoding="ascii")
    viejo = romper.stat().st_mtime - runsync.ROMPER_ABANDONADO - 60
    os.utime(romper, (viejo, viejo))
    registro(runsync.UI_LOCK, MUERTO, runsync.HOST)
    c("un «romper» abandonado no impide retirar el resto", runsync.tomar_ui(), None)
    c("y no se queda detrás", romper.exists(), False)
    runsync.soltar_ui()

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


# el arranque del sistema
#
# Un pid apuntado solo vale en el arranque en que se apuntó: tras reiniciar los
# números se reutilizan, y el de un registro de antes puede ser ahora otro
# proceso cualquiera. Si no se mirara, la ventana o el servicio de antes de
# apagar bloquearía el de ahora hasta que alguien borrara el fichero a mano.
arranque_real = store.arranque_del_sistema
store.arranque_del_sistema = lambda: ARRANQUE
try:
    OTRO_ARRANQUE = ARRANQUE - 10_000
    yo = {"pid": os.getpid(), "host": runsync.HOST}

    c("sin registro no hay nadie", store.vivo_en_este_arranque(None, runsync.HOST), False)
    c("uno ilegible tampoco", store.vivo_en_este_arranque({}, runsync.HOST), False)
    c("el de un proceso vivo de este equipo, sin arranque, va por el pid",
      store.vivo_en_este_arranque(yo, runsync.HOST), True)
    c("el de otro equipo no", store.vivo_en_este_arranque({**yo, "host": "otro"}, runsync.HOST),
      False)
    c("con el pid muerto no", store.vivo_en_este_arranque({**yo, "pid": MUERTO}, runsync.HOST),
      False)
    c("con un pid que no es un número, tampoco",
      store.vivo_en_este_arranque({**yo, "pid": "nada"}, runsync.HOST), False)
    c("con un pid que no es de nadie (cero), tampoco",
      store.vivo_en_este_arranque({**yo, "pid": 0}, runsync.HOST), False)
    c("de este arranque, dentro de la holgura, sí (el calculado en Windows baila)",
      store.vivo_en_este_arranque({**yo, "arranque": ARRANQUE + store.HOLGURA_ARRANQUE - 1},
                                  runsync.HOST), True)
    c("de otro arranque, no",
      store.vivo_en_este_arranque({**yo, "arranque": OTRO_ARRANQUE}, runsync.HOST), False)
    c("un arranque que no es un número se ignora",
      store.vivo_en_este_arranque({**yo, "arranque": "ayer"}, runsync.HOST), True)
    store.arranque_del_sistema = lambda: None
    c("si no se sabe el arranque de ahora, va por el pid",
      store.vivo_en_este_arranque({**yo, "arranque": OTRO_ARRANQUE}, runsync.HOST), True)
    store.arranque_del_sistema = lambda: ARRANQUE

    with sandbox():
        runsync.UI_LOCK = model.STATE_DIR / "ui.lock.json"
        runsync.LOCK = model.STATE_DIR / "daemon.lock.json"
        runsync.STOP = model.STATE_DIR / "daemon.stop"

        # la ventana
        registro(runsync.UI_LOCK, os.getpid(), runsync.HOST, OTRO_ARRANQUE)
        c("un registro de otro arranque no cuenta aunque su pid viva",
          runsync.ui_en_marcha(), None)
        c("  y se limpia el rastro", runsync.UI_LOCK.exists(), False)
        registro(runsync.UI_LOCK, os.getpid(), runsync.HOST, ARRANQUE)
        c("uno de este arranque sí", (runsync.ui_en_marcha() or {}).get("pid"), os.getpid())
        registro(runsync.UI_LOCK, os.getpid(), runsync.HOST)
        c("uno sin arranque, de antes, va por el pid",
          (runsync.ui_en_marcha() or {}).get("pid"), os.getpid())

        registro(runsync.UI_LOCK, os.getpid(), runsync.HOST, OTRO_ARRANQUE)
        c("la ventana de antes de reiniciar no impide abrir otra", runsync.tomar_ui(), None)
        escrito = store.read_json(runsync.UI_LOCK)
        c("  y la nueva apunta en qué arranque está",
          (escrito.get("pid"), escrito.get("arranque")), (os.getpid(), ARRANQUE))
        runsync.soltar_ui()

        # el servicio
        registro(runsync.LOCK, os.getpid(), runsync.HOST, OTRO_ARRANQUE)
        c("el servicio de otro arranque no cuenta como uno en marcha",
          runsync.servicio_en_marcha(), None)
        runsync.STOP_WAIT_SECONDS = 0.3
        dicho = runsync.stop_previous_daemon()
        c("  el lanzador lo limpia sin pedirle que pare ni esperarlo",
          ("ya inexistente" in (dicho or ""), runsync.LOCK.exists(), runsync.STOP.exists()),
          (True, False, False))
        registro(runsync.LOCK, os.getpid(), runsync.HOST, ARRANQUE)
        c("el de este arranque sí", (runsync.servicio_en_marcha() or {}).get("pid"), os.getpid())
        registro(runsync.LOCK, os.getpid(), runsync.HOST)
        c("el de antes, sin arranque, va por el pid",
          (runsync.servicio_en_marcha() or {}).get("pid"), os.getpid())

        # quien escribe el registro del servicio, qué arranque apunta
        runsync.LOCK.unlink()
        tomados: list[dict] = []
        reales = (runsync.tomar_lock, runsync.pen_present, runsync.pareja_llavero,
                  runsync.prioridad.bajar, runsync.dlog, os.getcwd())
        real_tomar = runsync.tomar_lock
        runsync.tomar_lock = lambda datos: tomados.append(dict(datos)) or real_tomar(datos)
        runsync.pen_present = lambda: False
        runsync.pareja_llavero = lambda: None
        runsync.prioridad.bajar = lambda pid=None: True
        runsync.dlog = lambda msg: None
        try:
            runsync.daemon_main(["notas"], 30)
        finally:
            (runsync.tomar_lock, runsync.pen_present, runsync.pareja_llavero,
             runsync.prioridad.bajar, runsync.dlog) = reales[:5]
            os.chdir(reales[5])
        c("el servicio apunta en qué arranque está",
          [t.get("arranque") for t in tomados], [ARRANQUE])

        # el vigilante del llavero y el registro del servicio, vistos desde el llavero
        c("llavero: un registro de otro arranque no cuenta aunque su pid viva",
          llavero.vivo_aqui({**yo, "host": llavero.equipo(), "arranque": OTRO_ARRANQUE}), False)
        c("  uno de este arranque sí",
          llavero.vivo_aqui({**yo, "host": llavero.equipo(), "arranque": ARRANQUE}), True)
        c("  y uno de antes, sin arranque, va por el pid",
          llavero.vivo_aqui({**yo, "host": llavero.equipo()}), True)
        registro(model.daemon_lock(), os.getpid(), llavero.equipo(), OTRO_ARRANQUE)
        c("un servicio de otro arranque no atiende el llavero",
          llavero.atiende_el_servicio(), False)
        registro(model.daemon_lock(), os.getpid(), llavero.equipo(), ARRANQUE)
        c("  y uno de este arranque sí", llavero.atiende_el_servicio(), True)
        registro(llavero.registro_vigilante(), os.getpid(), llavero.equipo(), OTRO_ARRANQUE)
        c("un vigilante de otro arranque no es un vigilante vivo",
          llavero.vigilante_vivo(), False)

        # la pantalla de reparación y la de actualizar miran el mismo registro
        registro(model.daemon_lock(), os.getpid(), prefs.HOST, OTRO_ARRANQUE)
        c("reparar: un servicio de otro arranque no está sincronizando",
          repair.sincronizacion_en_curso(), None)
        c("actualizar: ni hay un servicio que avisar", tk_update.servicio_vivo(), False)
        registro(model.daemon_lock(), os.getpid(), prefs.HOST, ARRANQUE)
        c("  uno de este arranque sí, en las dos",
          ("servicio periódico" in (repair.sincronizacion_en_curso() or ""),
           tk_update.servicio_vivo()), (True, True))
        registro(model.daemon_lock(), os.getpid(), prefs.HOST)
        c("  y uno de antes, sin arranque, también",
          ("servicio periódico" in (repair.sincronizacion_en_curso() or ""),
           tk_update.servicio_vivo()), (True, True))
        registro(model.daemon_lock(), MUERTO, "otro-equipo", OTRO_ARRANQUE)
        c("reparar, ante la duda: el de otro equipo no se puede comprobar, aunque diga otro arranque",
          "otro-equipo" in (repair.sincronizacion_en_curso() or ""), True)
finally:
    store.arranque_del_sistema = arranque_real


# el vigilante, en el equipo
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

# la fila de estado del vigilante
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
