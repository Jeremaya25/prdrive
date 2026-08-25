#!/usr/bin/env python3
"""
El editor de parejas, que es lo que puede hacer daño.

La comprobación central es la primera: cambiar un extremo de una pareja bisync
tiene que APARTAR su baseline. Si no se apartara, normalize_prefix() renombraría
los listados del destino viejo al nombre del nuevo y bisync leería como borrados
todos los ficheros que solo estaban en el anterior.
"""

import hashlib
import sys
from pathlib import Path

from _harness import Checks, sandbox

from common import bisync, config_file, model
from common.model import ConfigError
from ui import pair_editor

c = Checks("editor de parejas (ui/pair_editor.py)")

BASE = [
    {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas",
     "mode": "bisync", "flags": {"conflict-resolve": "path2"}},
    {"name": "subida", "local": "sync-data/subida", "remote_path": "/R/subida",
     "mode": "up"},
]


def preparar(pairs=None, daemon=None) -> dict:
    raw = {"defaults": {"remote": "synology"},
           "pair": [dict(p) for p in (pairs or BASE)]}
    if daemon:
        raw["daemon"] = daemon
    model.CONFIG_FILE.write_text(config_file.dumps(raw), encoding="utf-8")
    return raw


def dar_baseline(raw, name):
    """Deja a esa pareja con un baseline válido, como tras un --resync."""
    pair = next(p for p in model.parse_config(raw).pairs if p.name == name)
    pair.workdir.mkdir(parents=True, exist_ok=True)
    prefijo = bisync.expected_prefix(pair)
    for sufijo in (bisync.PATH1_SUFFIX, bisync.PATH2_SUFFIX):
        (pair.workdir / f"{prefijo}{sufijo}").write_text("x", encoding="utf-8")
    ffile = bisync.filters_file_for(pair)
    if ffile:
        Path(str(ffile) + ".md5").write_text(
            hashlib.md5(ffile.read_bytes()).hexdigest(), encoding="utf-8")
    return pair


def estado_de(name):
    pair = next(p for p in model.load_config().pairs if p.name == name)
    return bisync.pair_state(pair), bisync.filters_state(bisync.filters_file_for(pair))


# --- LO IMPORTANTE: cambiar un extremo aparta el baseline --------------------
with sandbox():
    raw = preparar()
    dar_baseline(raw, "notas")
    c("de partida el baseline es válido", estado_de("notas")[0].status, "ok")

    plan = pair_editor.plan_save(raw, {**BASE[0], "remote_path": "/R/otro"}, "notas")
    c("cambiar remote_path se planea apartando el baseline", plan.shelve, "notas")
    c("plan_save no ha tocado nada todavía", estado_de("notas")[0].status, "ok")
    c("y lo explica antes de confirmar",
      any("--resync" in x for x in plan.consequences), True)

    plan.execute()
    c("tras ejecutar, la pareja queda sin baseline", estado_de("notas")[0].status, "fresh")
    c("el baseline se ha apartado, no borrado",
      any(p.name.startswith("notas.old-") for p in model.STATE_DIR.iterdir()), True)
    c("el config apunta al destino nuevo",
      next(p.remote_path for p in model.load_config().pairs if p.name == "notas"), "/R/otro")

# --- renombrar es gratis: el baseline se conserva ----------------------------
with sandbox():
    raw = preparar()
    dar_baseline(raw, "notas")
    prefijo_antes = estado_de("notas")[0].prefix

    plan = pair_editor.plan_save(raw, {**BASE[0], "name": "apuntes"}, "notas")
    c("renombrar no aparta nada", plan.shelve, None)
    c("renombrar mueve el estado", plan.rename, ("notas", "apuntes"))
    plan.execute()

    estado, filtros = estado_de("apuntes")
    c("el baseline sobrevive al renombrado", estado.status, "ok")
    c("y con el mismo prefijo", estado.prefix, prefijo_antes)
    c("los filtros siguen cuadrando (se movió su .md5)", filtros.status, "ok")
    c("no queda estado con el nombre viejo", (model.STATE_DIR / "notas").exists(), False)
    c("no hace falta resync",
      bisync.resync_reasons(next(p for p in model.load_config().pairs
                                 if p.name == "apuntes")), [])

# --- cambiar filtros: sin cirugía, pero avisa -------------------------------
with sandbox():
    raw = preparar()
    dar_baseline(raw, "notas")
    plan = pair_editor.plan_save(raw, {**BASE[0], "exclude": ["borrador/**"]}, "notas")
    c("cambiar filtros no aparta el baseline", (plan.shelve, plan.rename), (None, None))
    c("pero avisa del resync", any("--resync" in x for x in plan.consequences), True)
    plan.execute()
    c("y bisync efectivamente lo pide", estado_de("notas")[1].needs_resync, True)

# --- alta --------------------------------------------------------------------
with sandbox():
    raw = preparar()
    plan = pair_editor.plan_save(raw, {"name": "fotos", "local": "sync-data/fotos",
                                       "remote_path": "/R/fotos", "mode": "bisync"})
    plan.execute()
    c("la pareja nueva está en el config", "fotos" in model.load_config().names, True)
    c("las anteriores siguen", model.load_config().names, ["notas", "subida", "fotos"])

# --- baja ---------------------------------------------------------------------
with sandbox():
    raw = preparar(daemon={"pairs": ["notas", "subida"], "interval_minutes": 10})
    dar_baseline(raw, "notas")

    plan = pair_editor.plan_remove(raw, "notas")
    c("sin limpiar: avisa de lo que queda suelto",
      any("sin usar" in x for x in plan.consequences), True)
    c("sin limpiar no aparta nada", plan.shelve, None)

    plan = pair_editor.plan_remove(raw, "notas", clean_state=True)
    c("limpiando sí aparta el baseline", plan.shelve, "notas")
    plan.execute()
    c("la pareja ya no está", model.load_config().names, ["subida"])
    c("y se ha caído también de [daemon].pairs",
      config_file.load_raw().get("daemon", {}).get("pairs"), ["subida"])
    c("sus filtros generados se han borrado",
      (model.FILTERS_DIR / "notas.txt").exists(), False)

with sandbox():
    raw = preparar(pairs=[BASE[0]])
    try:
        pair_editor.plan_remove(raw, "notas")
        c("no se puede quitar la última pareja", "no lanzó", "ConfigError")
    except ConfigError as e:
        c("no se puede quitar la última pareja", "última pareja" in str(e), True)

# --- validación ---------------------------------------------------------------
with sandbox():
    raw = preparar()

    def rechaza(etiqueta, edited, original=None, fragmento=""):
        try:
            pair_editor.plan_save(raw, edited, original)
            c(etiqueta, "no lanzó", "ConfigError")
        except ConfigError as e:
            c(etiqueta, fragmento in str(e), True)

    rechaza("nombre duplicado", {**BASE[0], "name": "subida"}, "notas", "Ya hay otra")
    rechaza("nombre con separador", {**BASE[0], "name": "a/b"}, "notas", "state/")
    rechaza("nombre vacío", {**BASE[0], "name": "  "}, "notas", "vacío")
    rechaza("sin ruta local", {"name": "x", "local": "", "remote_path": "/r",
                               "mode": "up"}, None, "ruta local")
    rechaza("sin ruta remota", {"name": "x", "local": "a", "remote_path": "",
                                "mode": "up"}, None, "remoto")
    rechaza("modo inventado", {"name": "x", "local": "a", "remote_path": "/r",
                               "mode": "espejito"}, None, "Modo inválido")
    c("el config no se ha tocado en ningún rechazo", config_file.load_raw(), raw)

# --- el modo espejo se anuncia ------------------------------------------------
with sandbox():
    raw = preparar()
    plan = pair_editor.plan_save(raw, {**BASE[1], "mode": "up-mirror"}, "subida")
    c("up-mirror avisa de que borra en el destino",
      any("BORRA en el NAS" in w for w in plan.warnings), True)

# --- si falla el guardado, el estado vuelve a su sitio -------------------------
with sandbox():
    raw = preparar()
    dar_baseline(raw, "notas")
    plan = pair_editor.plan_save(raw, {**BASE[0], "remote_path": "/R/otro"}, "notas")

    original = config_file.save
    config_file.save = lambda *a, **k: (_ for _ in ()).throw(OSError("disco lleno"))
    try:
        plan.execute()
        c("un fallo al guardar se propaga", "no lanzó", "OSError")
    except OSError:
        c("un fallo al guardar se propaga", True, True)
    finally:
        config_file.save = original

    c("y el baseline vuelve a su sitio", estado_de("notas")[0].status, "ok")
    c("sin dejar restos apartados",
      [p.name for p in model.STATE_DIR.iterdir() if ".old-" in p.name], [])

sys.exit(c.report())
