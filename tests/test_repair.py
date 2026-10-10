#!/usr/bin/env python3
"""Las reparaciones de la pantalla «Reparación» (`ui/repair.py`).

Lo que se comprueba es lo mismo que en `pair_editor`: que un plan no toca nada
hasta que se ejecuta, que dice de antemano lo que va a pasar, y que se niega
cuando no puede hacerse. Lo delicado aquí es el borrado de bloqueos: solo vale
si no hay ninguna sincronización en marcha, y ante la duda no se hace.
"""

import hashlib
import os
import sys
from pathlib import Path

from _harness import Checks, mkcfg, sandbox

from common import bisync, model, revision, store
from ui import prefs, repair

c = Checks("reparaciones (ui/repair.py)")

MUERTO = 2 ** 22          # un pid que no existe


def listados(pair, prefijo=None):
    """Un baseline en disco, como lo deja un --resync."""
    prefijo = prefijo or bisync.expected_prefix(pair)
    pair.workdir.mkdir(parents=True, exist_ok=True)
    for sufijo in (bisync.PATH1_SUFFIX, bisync.PATH2_SUFFIX):
        (pair.workdir / f"{prefijo}{sufijo}").write_text("listado\n", encoding="utf-8")
    ffile = bisync.filters_file_for(pair)
    if ffile is not None:
        Path(str(ffile) + ".md5").write_text(
            hashlib.md5(ffile.read_bytes()).hexdigest(), encoding="utf-8")


def hallazgo(hallazgos, clave):
    """Devuelve el hallazgo con esa clave."""
    return next(h for h in hallazgos if h.clave == clave)


# ¿hay alguien sincronizando?
with sandbox():
    c("sin registro del servicio, no hay nada en marcha",
      repair.sincronizacion_en_curso(), None)

    store.write_json(model.daemon_lock(), {"pid": MUERTO, "host": prefs.HOST})
    c("un servicio con el pid muerto no cuenta",
      repair.sincronizacion_en_curso(), None)

    store.write_json(model.daemon_lock(), {"pid": os.getpid(), "host": prefs.HOST})
    c("uno vivo sí", "servicio periódico" in (repair.sincronizacion_en_curso() or ""), True)

    # De otro equipo no se puede saber si sigue vivo, así que se supone que sí:
    # equivocarse hacia «no borro el bloqueo» no rompe nada.
    store.write_json(model.daemon_lock(), {"pid": MUERTO, "host": "otro-equipo"})
    c("y el de otro equipo, ante la duda, también",
      "otro-equipo" in (repair.sincronizacion_en_curso() or ""), True)


# borrar bloqueos sueltos
with sandbox():
    cfg = mkcfg(["notas"])
    pair = cfg.pairs[0]
    pair.local_abs.mkdir(parents=True, exist_ok=True)
    listados(pair)
    lock = pair.workdir / "algo.lck"
    lock.write_text("", encoding="utf-8")

    store.write_json(model.daemon_lock(), {"pid": os.getpid(), "host": prefs.HOST})
    aviso = hallazgo(revision.revisar(cfg), "lock")
    try:
        repair.plan_locks(cfg, aviso)
        c("con el servicio en marcha, no se borra un bloqueo", "se ha planeado", "no")
    except repair.ReparacionImposible as e:
        c.contains("con el servicio en marcha, no se borra un bloqueo", str(e),
                   "no hay ninguna pasada en marcha")
    c("y el bloqueo sigue donde estaba", lock.exists(), True)

    model.daemon_lock().unlink()
    plan = repair.plan_locks(cfg, aviso)
    c("sin nadie sincronizando, el plan se puede pensar",
      bool(plan.consequences), True)
    c.contains("y dice cuántos ficheros borra", " ".join(plan.consequences), "1 fichero")
    c("pensar el plan no borra nada", lock.exists(), True)
    c("el plan avisa de lo que no puede comprobar", bool(plan.warnings), True)

    hechos = plan.execute()
    c("ejecutarlo borra el bloqueo", lock.exists(), False)
    c("y cuenta lo que ha hecho", any("algo.lck" in h for h in hechos), True)

    try:
        repair.plan_locks(cfg, aviso)
        c("un bloqueo que ya no está se dice, no se revienta", "plan", "excepción")
    except repair.ReparacionImposible as e:
        c.contains("un bloqueo que ya no está se dice, no se revienta",
                   str(e), "ya no están")

with sandbox():
    cfg = mkcfg(["notas"])
    pair = cfg.pairs[0]
    pair.local_abs.mkdir(parents=True, exist_ok=True)
    listados(pair)
    (pair.workdir / "algo.lck").write_text("", encoding="utf-8")
    aviso = hallazgo(revision.revisar(cfg), "lock")

    def falla(ruta):
        """Hace que borrar falle: el dispositivo dice que no."""
        raise OSError("el dispositivo dice que no")

    repair.borrar = falla
    try:
        repair.plan_locks(cfg, aviso).execute()
        c("si el borrado falla, se dice", "silencio", "excepción")
    except repair.ReparacionImposible as e:
        c.contains("si el borrado falla, se dice", str(e), "No se ha podido borrar")
    finally:
        repair.borrar = lambda ruta: ruta.unlink()


# apartar un baseline que no es de esta pareja
with sandbox():
    cfg = mkcfg(["notas"])
    pair = cfg.pairs[0]
    pair.local_abs.mkdir(parents=True, exist_ok=True)
    listados(pair, "otro-destino-cualquiera")

    aviso = hallazgo(revision.revisar(cfg), "prefijo")
    plan = repair.plan_apartar(cfg, aviso)
    c.contains("el plan dice adónde va el baseline", " ".join(plan.consequences),
               "state/notas.old-")
    c.contains("y que no se borra nada", " ".join(plan.consequences), "No se borra nada")
    c.contains("avisa de que la pareja se salta hasta el resync",
               " ".join(plan.warnings), "se salta")
    c("pensarlo no mueve nada", pair.workdir.is_dir(), True)

    hechos = plan.execute()
    c("ejecutarlo deja el workdir vacío de baseline", pair.workdir.is_dir(), False)
    apartados = list(model.STATE_DIR.glob("notas.old-*"))
    c("y lo aparta con fecha, sin borrarlo", len(apartados), 1)
    c("diciendo dónde ha quedado", any(apartados[0].name in h for h in hechos), True)
    c("la pareja queda como nueva", bisync.pair_state(pair).status, "fresh")

    try:
        repair.plan_apartar(cfg, aviso)
        c("apartar dos veces no se puede", "plan", "excepción")
    except repair.ReparacionImposible as e:
        c.contains("apartar dos veces no se puede", str(e), "ya no tiene baseline")


# lo que no es un plan, sino una pasada
with sandbox():
    cfg = mkcfg(["notas", "fotos"])
    aviso = revision.Hallazgo("resync", "x", "y", "notas")
    c("el resync se lanza con --yes: la pregunta ya se ha hecho antes",
      repair.args_resync(aviso), ["notas", "--resync", "--yes"])
    c("simular no lleva --yes: una pareja sin baseline debe volver «saltada»",
      repair.args_simular(["notas", "fotos"]), ["notas", "fotos", "--dry-run"])
    c("y se confirma como todo lo demás",
      bool(repair.aviso_resync(aviso).consequences), True)

    c("la carpeta local que falta no tiene reparación",
      repair.tiene_plan(revision.Hallazgo("local", "x", "y", "notas")), False)
    try:
        repair.plan_para(cfg, revision.Hallazgo("local", "x", "y", "notas"))
        c("y se dice en vez de ofrecer un botón que no existe", "plan", "excepción")
    except repair.ReparacionImposible as e:
        c.contains("y se dice en vez de ofrecer un botón que no existe",
                   str(e), "no se arregla desde aquí")

    # un resync de una pareja raíz que subió el programa: se dice ANTES, porque
    # después el listado nuevo ya no lo enseña
    subio = revision.Hallazgo("resync", "t", "d", "p", revision.AVISO, ("nas:R/p/.prdrive/",))
    avisos = " ".join(repair.aviso_resync(subio).warnings)
    c.contains("el aviso del resync nombra .prdrive", avisos, "nas:R/p/.prdrive/")
    c.contains("  y dice que la borre la persona", avisos, "bórrala")
    c.contains("  y que el resync no la borra", avisos, "no la borra")
    sin_dato = " ".join(repair.aviso_resync(
        revision.Hallazgo("resync", "t", "d", "p", revision.AVISO, ())).warnings)
    c("sin dato no hay tal aviso", "bórrala" in sin_dato or ".prdrive" in sin_dato, False)

    c("una pareja que ya no está en el config se dice",
      repair.tiene_plan(revision.Hallazgo("prefijo", "x", "y", "fantasma")), True)
    try:
        repair.plan_para(cfg, revision.Hallazgo("prefijo", "x", "y", "fantasma"))
        c("sin reventar", "plan", "excepción")
    except repair.ReparacionImposible as e:
        c.contains("sin reventar", str(e), "ya no está en la configuración")


# lo que ya no está: se vuelve a mirar antes de actuar
with sandbox():
    cfg = mkcfg(["notas", "fotos"])
    notas, fotos = cfg.pairs
    for pareja in (notas, fotos):
        pareja.local_abs.mkdir(parents=True, exist_ok=True)
        listados(pareja)
    suelto = notas.workdir / "algo.lck"
    suelto.write_text("", encoding="utf-8")
    visto = hallazgo(revision.revisar(cfg), "lock")

    ahora = repair.vigente(cfg, visto)
    c("un hallazgo que sigue ahí se devuelve",
      (ahora.clave, ahora.pareja), ("lock", "notas"))
    c("  recién leído, con lo que lleva ahora", ahora.dato, visto.dato)

    otro = notas.workdir / "otro.lck"
    otro.write_text("", encoding="utf-8")
    c("  y si ha cambiado lo que lleva, se devuelve el de ahora, no el que se vio",
      sorted(Path(r).name for r in repair.vigente(cfg, visto).dato),
      ["algo.lck", "otro.lck"])
    otro.unlink()

    suelto.unlink()
    c("un bloqueo que se soltó mientras tanto: ya no está", repair.vigente(cfg, visto), None)

    fantasma = revision.Hallazgo("lock", "x", "y", "no-existe")
    c("una pareja que no está en el config: ya no está", repair.vigente(cfg, fantasma), None)

    (fotos.workdir / "uno.lck").write_text("", encoding="utf-8")
    c("la misma avería en OTRA pareja no vale por la que se vio",
      repair.vigente(cfg, visto), None)

    llamadas: list = []
    real_revisar = revision.revisar
    revision.revisar = lambda config, **k: llamadas.append(config) or real_revisar(config, **k)
    try:
        repair.vigente(cfg, visto)
    finally:
        revision.revisar = real_revisar
    c("mirar de nuevo es leer el dispositivo, una vez", len(llamadas), 1)


# ejecutar un plan vuelve a mirar lo que lo hacía seguro
with sandbox():
    cfg = mkcfg(["notas"])
    pair = cfg.pairs[0]
    pair.local_abs.mkdir(parents=True, exist_ok=True)
    listados(pair)
    lock = pair.workdir / "algo.lck"
    lock.write_text("", encoding="utf-8")
    aviso = hallazgo(revision.revisar(cfg), "lock")

    plan = repair.plan_locks(cfg, aviso)
    store.write_json(model.daemon_lock(), {"pid": os.getpid(), "host": prefs.HOST})
    try:
        plan.execute()
        c("si empieza una pasada entre el plan y el sí, no se borra el bloqueo",
          "se ha ejecutado", "excepción")
    except repair.ReparacionImposible as e:
        c.contains("si empieza una pasada entre el plan y el sí, no se borra el bloqueo",
                   str(e), "Ahora mismo está sincronizando")
    c("  y el bloqueo sigue donde estaba", lock.exists(), True)
    model.daemon_lock().unlink()
    c("  sin nadie sincronizando, el mismo plan sí lo borra",
      (any("algo.lck" in h for h in plan.execute()), lock.exists()), (True, False))

with sandbox():
    cfg = mkcfg(["notas"])
    pair = cfg.pairs[0]
    pair.local_abs.mkdir(parents=True, exist_ok=True)
    listados(pair, "otro-destino-cualquiera")
    aviso = hallazgo(revision.revisar(cfg), "prefijo")

    plan = repair.plan_apartar(cfg, aviso)
    apartado = bisync.shelve_baseline(pair.name)       # lo aparta otra pantalla antes
    c("(el baseline se apartó por otro lado)", apartado is not None, True)
    llamadas = []
    real_apartar = repair.apartar
    repair.apartar = lambda nombre: llamadas.append(nombre) or real_apartar(nombre)
    try:
        plan.execute()
        c("si el baseline ya se apartó entre el plan y el sí, no se aparta otra vez",
          "se ha ejecutado", "excepción")
    except repair.ReparacionImposible as e:
        c.contains("si el baseline ya se apartó entre el plan y el sí, se dice",
                   str(e), "ya no tiene baseline")
    finally:
        repair.apartar = real_apartar
    c("  y no se toca nada más", llamadas, [])
    c("  ni queda un segundo baseline apartado",
      len(list(model.STATE_DIR.glob("notas.old-*"))), 1)

sys.exit(c.report())
