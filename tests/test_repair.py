#!/usr/bin/env python3
"""
Las reparaciones de la pantalla «Reparación» (ui/repair.py).

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
    return next(h for h in hallazgos if h.clave == clave)


# --- ¿hay alguien sincronizando? -------------------------------------------
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


# --- borrar bloqueos sueltos ------------------------------------------------
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
        raise OSError("el dispositivo dice que no")

    repair.borrar = falla
    try:
        repair.plan_locks(cfg, aviso).execute()
        c("si el borrado falla, se dice", "silencio", "excepción")
    except repair.ReparacionImposible as e:
        c.contains("si el borrado falla, se dice", str(e), "No se ha podido borrar")
    finally:
        repair.borrar = lambda ruta: ruta.unlink()


# --- apartar un baseline que no es de esta pareja ---------------------------
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


# --- lo que no es un plan, sino una pasada ----------------------------------
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

    c("una pareja que ya no está en el config se dice",
      repair.tiene_plan(revision.Hallazgo("prefijo", "x", "y", "fantasma")), True)
    try:
        repair.plan_para(cfg, revision.Hallazgo("prefijo", "x", "y", "fantasma"))
        c("sin reventar", "plan", "excepción")
    except repair.ReparacionImposible as e:
        c.contains("sin reventar", str(e), "ya no está en la configuración")

sys.exit(c.report())
