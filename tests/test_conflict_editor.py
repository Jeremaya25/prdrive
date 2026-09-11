#!/usr/bin/env python3
"""
Resolver un conflicto (ui/conflict_editor.py): qué fichero se queda, cuáles se
borran, y qué pasa cuando algo falla a medias.

Todo sobre ficheros de verdad en un sandbox: lo que importa aquí es el
contenido que queda con el nombre bueno, no a qué funciones se llama.
"""

import os
import sys
import time
from pathlib import Path

from _harness import Checks, sandbox

from common import conflicts, model
from ui import conflict_editor as ed

c = Checks("resolver conflictos (ui/conflict_editor.py)")


def pareja():
    return model.parse_config({"defaults": {"remote": "nas"}, "pair": [
        {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas"}]}).pairs[0]


def escribir(ruta: Path, texto: str, hace: float = 0) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8")
    if hace:
        marca = time.time() - hace
        os.utime(ruta, (marca, marca))
    return ruta


def unico(p) -> conflicts.Conflicto:
    encontrados = conflicts.escanear(p)
    assert len(encontrados) == 1, encontrados
    return encontrados[0]


def leer(ruta: Path) -> str:
    return ruta.read_text(encoding="utf-8")


def en_disco(p) -> list[str]:
    return sorted(x.relative_to(p.local_abs).as_posix()
                  for x in p.local_abs.rglob("*") if x.is_file())


# --- perdió este dispositivo: su versión es la copia ------------------------------
with sandbox():
    p = pareja()
    escribir(p.local_abs / "plan.md", "del remoto", hace=60)
    escribir(p.local_abs / "plan.md.conflicto-dispositivo1", "de aquí", hace=120)
    plan = ed.plan_lado(unico(p), conflicts.DISPOSITIVO)
    texto = "\n".join(plan.consequences)
    c.contains("las consecuencias hablan de la versión de este dispositivo", texto,
               "versión de este dispositivo")
    c.contains("y de la del remoto", texto, "versión del remoto")
    c("pensar el plan no toca nada", en_disco(p),
      ["plan.md", "plan.md.conflicto-dispositivo1"])
    plan.execute()
    c("quedarse con la de este dispositivo la pone con su nombre", leer(p.local_abs / "plan.md"),
      "de aquí")
    c("y la copia desaparece", en_disco(p), ["plan.md"])
    c("sin conflictos después", conflicts.escanear(p), [])

with sandbox():
    p = pareja()
    escribir(p.local_abs / "plan.md", "del remoto")
    escribir(p.local_abs / "plan.md.conflicto-dispositivo1", "de aquí")
    ed.plan_lado(unico(p), conflicts.REMOTO).execute()
    c("quedarse con la del remoto borra la copia", en_disco(p), ["plan.md"])
    c("y el original sigue como estaba", leer(p.local_abs / "plan.md"), "del remoto")

# --- perdió el remoto: su versión es la copia ----------------------------------
with sandbox():
    p = pareja()
    escribir(p.local_abs / "a.txt", "de aquí")
    escribir(p.local_abs / "a.txt.conflicto-remoto1", "del remoto")
    ed.plan_lado(unico(p), conflicts.DISPOSITIVO).execute()
    c("quedarse con la de aquí cuando ganó aquí: borra la copia",
      (en_disco(p), leer(p.local_abs / "a.txt")), (["a.txt"], "de aquí"))

with sandbox():
    p = pareja()
    escribir(p.local_abs / "a.txt", "de aquí")
    escribir(p.local_abs / "a.txt.conflicto-remoto1", "del remoto")
    ed.plan_lado(unico(p), conflicts.REMOTO).execute()
    c("quedarse con la del remoto cuando perdió: la copia sustituye al original",
      (en_disco(p), leer(p.local_abs / "a.txt")), (["a.txt"], "del remoto"))

# --- sin ganador: rclone renombró las dos ----------------------------------------
with sandbox():
    p = pareja()
    escribir(p.local_abs / "b.txt.conflicto-dispositivo1", "de aquí")
    escribir(p.local_abs / "b.txt.conflicto-remoto1", "del remoto")
    ed.plan_lado(unico(p), conflicts.REMOTO).execute()
    c("sin ganador: la elegida recupera el nombre y la otra se borra",
      (en_disco(p), leer(p.local_abs / "b.txt")), (["b.txt"], "del remoto"))

# --- conflictos viejos, sin lado ---------------------------------------------------
with sandbox():
    p = pareja()
    escribir(p.local_abs / "v.md", "actual")
    escribir(p.local_abs / "v.md.conflict1", "otra")
    viejo = unico(p)
    c("sin lado no hay «la de este dispositivo»",
      ed.puede(viejo, conflicts.DISPOSITIVO), False)
    try:
        ed.plan_lado(viejo, conflicts.DISPOSITIVO)
        c("pedir un lado que no se sabe se rechaza", "sin error", "error")
    except ed.ResolucionImposible:
        c("pedir un lado que no se sabe se rechaza", True, True)
    etiquetas = [e for _v, e in ed.etiquetas(viejo)]
    c("las etiquetas no enseñan el sufijo", any("conflict" in e for e in etiquetas), False)
    copia = next(v for v in viejo.versiones if not v.es_original)
    ed.plan_conservar(viejo, copia).execute()
    c("pero se puede elegir una versión concreta",
      (en_disco(p), leer(p.local_abs / "v.md")), (["v.md"], "otra"))

with sandbox():
    p = pareja()
    escribir(p.local_abs / "d.md", "actual")
    escribir(p.local_abs / "d.md.conflicto-dispositivo1", "primera")
    escribir(p.local_abs / "d.md.conflicto-dispositivo2", "segunda")
    etiquetas = [e for _v, e in ed.etiquetas(unico(p))]
    c("dos versiones del mismo lado se distinguen por número",
      etiquetas[1:], ["versión de este dispositivo (1)", "versión de este dispositivo (2)"])

# --- avisos -----------------------------------------------------------------------
with sandbox():
    p = pareja()
    escribir(p.local_abs / "plan.md", "del remoto", hace=3600)
    escribir(p.local_abs / "plan.md.conflicto-dispositivo1", "de aquí", hace=10)
    plan = ed.plan_lado(unico(p), conflicts.REMOTO)
    c("descartar la versión más reciente se avisa",
      any("más reciente" in a for a in plan.warnings), True)
    plan2 = ed.plan_lado(unico(p), conflicts.DISPOSITIVO)
    c("quedarse con la más reciente no", plan2.warnings, [])
    c.contains("siempre se dice que solo se toca este dispositivo",
               "\n".join(plan.consequences), "Solo se tocan ficheros de este dispositivo")

# --- lo que puede salir mal ---------------------------------------------------------
with sandbox():
    p = pareja()
    escribir(p.local_abs / "plan.md", "del remoto")
    escribir(p.local_abs / "plan.md.conflicto-dispositivo1", "de aquí")
    plan = ed.plan_lado(unico(p), conflicts.DISPOSITIVO)
    escribir(p.local_abs / "plan.md.conflicto-dispositivo1", "cambiada mientras tanto",
             hace=-5)
    try:
        plan.execute()
        c("si un fichero cambió desde el plan, no se ejecuta", "ejecutado", "rechazado")
    except ed.ResolucionImposible:
        c("si un fichero cambió desde el plan, no se ejecuta", True, True)
    c("y no se ha tocado nada", (en_disco(p), leer(p.local_abs / "plan.md")),
      (["plan.md", "plan.md.conflicto-dispositivo1"], "del remoto"))

with sandbox():
    p = pareja()
    escribir(p.local_abs / "plan.md", "del remoto")
    copia = escribir(p.local_abs / "plan.md.conflicto-dispositivo1", "de aquí")
    conflicto = unico(p)
    copia.unlink()
    try:
        ed.plan_lado(conflicto, conflicts.DISPOSITIVO)
        c("no se puede conservar una versión que ya no está", "plan", "error")
    except ed.ResolucionImposible:
        c("no se puede conservar una versión que ya no está", True, True)

with sandbox():
    p = pareja()
    escribir(p.local_abs / "plan.md", "del remoto")
    escribir(p.local_abs / "plan.md.conflicto-dispositivo1", "de aquí")
    plan = ed.plan_lado(unico(p), conflicts.DISPOSITIVO)
    real = ed.mover
    ed.mover = lambda origen, destino: (_ for _ in ()).throw(OSError("bloqueado"))
    try:
        plan.execute()
        c("si no se puede poner la versión elegida, falla", "sin error", "error")
    except ed.ResolucionImposible as e:
        c.contains("si no se puede poner la versión elegida, falla y lo dice", str(e),
                   "bloqueado")
    finally:
        ed.mover = real
    c("y no se ha borrado nada", (en_disco(p), leer(p.local_abs / "plan.md")),
      (["plan.md", "plan.md.conflicto-dispositivo1"], "del remoto"))

with sandbox():
    p = pareja()
    escribir(p.local_abs / "b.txt.conflicto-dispositivo1", "de aquí")
    escribir(p.local_abs / "b.txt.conflicto-remoto1", "del remoto")
    plan = ed.plan_lado(unico(p), conflicts.DISPOSITIVO)
    real = ed.borrar
    ed.borrar = lambda ruta: (_ for _ in ()).throw(OSError("en uso"))
    try:
        plan.execute()
        c("si no se puede borrar la descartada, falla", "sin error", "error")
    except ed.ResolucionImposible as e:
        c.contains("diciendo que la elegida ya está en su sitio", str(e), "b.txt")
        c.contains("y qué no se ha podido borrar", str(e), "en uso")
    finally:
        ed.borrar = real
    c("la versión elegida ya tiene su nombre", leer(p.local_abs / "b.txt"), "de aquí")
    c("y lo que queda sigue saliendo como conflicto",
      [v.ruta.name for v in unico(p).versiones], ["b.txt", "b.txt.conflicto-remoto1"])

# --- nunca fuera de la carpeta de la pareja -------------------------------------------
with sandbox():
    p = pareja()
    escribir(p.local_abs / "x" / "plan.md", "del remoto")
    escribir(p.local_abs / "x" / "plan.md.conflicto-dispositivo1", "de aquí")
    plan = ed.plan_lado(unico(p), conflicts.DISPOSITIVO)
    tocados = [plan.conserva.ruta, plan.conflicto.original, *plan.descartar]
    c("todo lo que toca un plan está dentro de la carpeta local de la pareja",
      all(p.local_abs in t.parents for t in tocados), True)

sys.exit(c.report())
