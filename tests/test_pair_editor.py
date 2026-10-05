#!/usr/bin/env python3
"""El editor de parejas, que es lo que puede hacer daño.

La comprobación central es la primera: cambiar un extremo de una pareja bisync
tiene que APARTAR su baseline. Reaprovecharlo con el nombre nuevo le diría a
bisync que el listado del destino viejo describe el nuevo, y leería como
borrados todos los ficheros que solo estaban en el anterior.
"""

import hashlib
import sys
from pathlib import Path

from _harness import Checks, sandbox

import tomllib

from common import bisync, catalog, config_file, model
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
    """Escribe un config de mentira con esas parejas y devuelve el dict crudo."""
    raw = {"defaults": {"remote": "nas"},
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
    """Devuelve el estado del baseline y de los filtros de esa pareja."""
    pair = next(p for p in model.load_config().pairs if p.name == name)
    return bisync.pair_state(pair), bisync.filters_state(bisync.filters_file_for(pair))


# LO IMPORTANTE: cambiar un extremo aparta el baseline
with sandbox():
    raw = preparar()
    dar_baseline(raw, "notas")
    c("de partida el baseline es válido", estado_de("notas")[0].status, "ok")

    plan = pair_editor.plan_save(raw, {**BASE[0], "remote_path": "/R/otro"}, "notas")
    c("cambiar remote_path se planea apartando el baseline", plan.shelve, ["notas"])
    c("plan_save no ha tocado nada todavía", estado_de("notas")[0].status, "ok")
    c("y lo explica antes de confirmar",
      any("--resync" in x for x in plan.consequences), True)

    plan.execute()
    c("tras ejecutar, la pareja queda sin baseline", estado_de("notas")[0].status, "fresh")
    c("el baseline se ha apartado, no borrado",
      any(p.name.startswith("notas.old-") for p in model.STATE_DIR.iterdir()), True)
    c("el config apunta al destino nuevo",
      next(p.remote_path for p in model.load_config().pairs if p.name == "notas"), "/R/otro")

# renombrar es gratis: el baseline se conserva
with sandbox():
    raw = preparar()
    dar_baseline(raw, "notas")
    prefijo_antes = estado_de("notas")[0].prefix

    plan = pair_editor.plan_save(raw, {**BASE[0], "name": "apuntes"}, "notas")
    c("renombrar no aparta nada", plan.shelve, [])
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

# cambiar filtros: sin cirugía, pero avisa
with sandbox():
    raw = preparar()
    dar_baseline(raw, "notas")
    plan = pair_editor.plan_save(raw, {**BASE[0], "exclude": ["borrador/**"]}, "notas")
    c("cambiar filtros no aparta el baseline", (plan.shelve, plan.rename), ([], None))
    c("pero avisa del resync", any("--resync" in x for x in plan.consequences), True)
    plan.execute()
    c("y bisync efectivamente lo pide", estado_de("notas")[1].needs_resync, True)

# alta
with sandbox():
    raw = preparar()
    plan = pair_editor.plan_save(raw, {"name": "fotos", "local": "sync-data/fotos",
                                       "remote_path": "/R/fotos", "mode": "bisync"})
    plan.execute()
    c("la pareja nueva está en el config", "fotos" in model.load_config().names, True)
    c("las anteriores siguen", model.load_config().names, ["notas", "subida", "fotos"])

# baja
with sandbox():
    raw = preparar(daemon={"pairs": ["notas", "subida"], "interval_minutes": 10})
    dar_baseline(raw, "notas")

    plan = pair_editor.plan_remove(raw, "notas")
    c("sin limpiar: avisa de lo que queda suelto",
      any("sin usar" in x for x in plan.consequences), True)
    c("sin limpiar no aparta nada", plan.shelve, [])

    plan = pair_editor.plan_remove(raw, "notas", clean_state=True)
    c("limpiando sí aparta el baseline", plan.shelve, ["notas"])
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

# validación
with sandbox():
    raw = preparar()

    def rechaza(etiqueta, edited, original=None, fragmento=""):
        """Comprueba que `plan_save` lance `ConfigError` con ese fragmento."""
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

# el modo espejo se anuncia
with sandbox():
    raw = preparar()
    plan = pair_editor.plan_save(raw, {**BASE[1], "mode": "up-mirror"}, "subida")
    c("up-mirror avisa de que borra en el destino",
      any("BORRA en el remoto" in w for w in plan.warnings), True)

# si falla el guardado, el estado vuelve a su sitio
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

# renombrar Y cambiar un extremo a la vez
#
# Son dos operaciones que se suman, no ramas excluyentes: se aparta
# `state/notas/` y `filters/notas.txt` no puede quedar huérfano con el nombre
# viejo.
with sandbox():
    raw = preparar()
    dar_baseline(raw, "notas")
    plan = pair_editor.plan_save(
        raw, {**BASE[0], "name": "apuntes", "remote_path": "/R/otro"}, "notas")
    c("renombrar y mover el extremo hace las dos cosas",
      (plan.rename, plan.shelve), (("notas", "apuntes"), ["apuntes"]))
    plan.execute()
    c("el baseline se aparta ya con el nombre nuevo",
      any(p.name.startswith("apuntes.old-") for p in model.STATE_DIR.iterdir()), True)
    c("no queda nada con el nombre viejo",
      [p.name for p in model.STATE_DIR.iterdir() if p.name.startswith("notas")], [])
    c("ni filtros huérfanos", (model.FILTERS_DIR / "notas.txt").exists(), False)

# [defaults]: un cambio ahí invalida VARIOS baselines a la vez
with sandbox():
    raw = preparar(pairs=[BASE[0], {"name": "otra", "local": "sync-data/otra",
                                    "remote_path": "/R/otra", "mode": "bisync"}])
    dar_baseline(raw, "notas")
    dar_baseline(raw, "otra")

    plan = pair_editor.plan_defaults(raw, {"remote": "nas", "device_remote": "dispositivo"})
    c("device_remote cambia el extremo local de todas", sorted(plan.shelve),
      ["notas", "otra"])
    c("y se explica por qué",
      any("todas las parejas" in x for x in plan.consequences), True)
    plan.execute()
    c("las dos se quedan sin baseline",
      (estado_de("notas")[0].status, estado_de("otra")[0].status), ("fresh", "fresh"))

with sandbox():
    raw = preparar()
    dar_baseline(raw, "notas")
    plan = pair_editor.plan_defaults(raw, {"remote": "nas", "keep_logs": True})
    c("un cambio de [defaults] inocuo no aparta nada", plan.shelve, [])
    plan.execute()
    c("el baseline sigue valiendo", estado_de("notas")[0].status, "ok")
    c("y keep_logs ha quedado escrito",
      config_file.load_raw()["defaults"].get("keep_logs"), True)

# la ruta del catálogo: el fichero, no su carpeta (#48)
with sandbox():
    raw = preparar()
    try:
        pair_editor.plan_defaults(raw, {"remote": "nas",
                                        "catalog_path": "/prdrive-catalog"})
        c("una carpeta por ruta del catálogo se rechaza", "no lanzó", "ConfigError")
    except ConfigError as e:
        c.contains("una carpeta por ruta del catálogo se rechaza", str(e),
                   "«/prdrive-catalog/remote.toml»")
    antes = config_file.load_raw()
    c("y no se ha escrito nada", antes["defaults"].get("catalog_path"), None)

    # Una ruta que ya estaba —a mano, sin extensión— no impide guardar lo demás.
    raw["defaults"]["catalog_path"] = "/cat/pares"
    plan = pair_editor.plan_defaults(raw, {"remote": "nas", "keep_logs": True,
                                           "catalog_path": "/cat/pares"})
    c("una ruta que no cambia no se revisa", plan.shelve, [])

# este dispositivo frente al catálogo
CAT = {"defaults": {"remote": "nas"},
       "pair": [dict(BASE[0]), dict(BASE[1]),
                {"name": "fotos", "local": "sync-data/fotos",
                 "remote_path": "/R/fotos", "mode": "up"}]}


def falso_catalogo(raw=None):
    """Devuelve un catálogo de mentira con esos datos."""
    texto = config_file.dumps(raw if raw is not None else CAT)
    return catalog.Catalog(raw=tomllib.loads(texto), text=texto, source="remote",
                           stamp="2026-01-01 00:00:00", endpoint="nas:/x/pairs.toml")


with sandbox():
    raw = preparar()
    cat = falso_catalogo()

    plan = pair_editor.plan_enable(raw, cat, "fotos")
    c("usar una del catálogo la copia tal cual",
      plan.raw["pair"][-1], catalog.find_pair(cat, "fotos"))
    plan.execute()
    c("y aparece en el config", model.load_config().names, ["notas", "subida", "fotos"])

    raw = config_file.load_raw()
    try:
        pair_editor.plan_enable(raw, cat, "fotos")
        c("no se puede usar dos veces la misma", "no lanzó", "ConfigError")
    except ConfigError as e:
        c("no se puede usar dos veces la misma", "ya está en este dispositivo" in str(e), True)
    try:
        pair_editor.plan_enable(raw, cat, "inventada")
        c("ni una que no está en el catálogo", "no lanzó", "ConfigError")
    except ConfigError as e:
        c("ni una que no está en el catálogo", "Créala primero" in str(e), True)

with sandbox():
    raw = preparar()
    cat = falso_catalogo()
    filas = {f.name: f for f in pair_editor.catalog_rows(
        model.parse_config(raw), raw, cat)}
    c("la lista trae las del catálogo y las de aquí", sorted(filas),
      ["fotos", "notas", "subida"])
    c("las que coinciden salen como del catálogo", filas["notas"].origen,
      pair_editor.ORIGEN_CATALOGO)
    c("las que no se usan aquí salen sin marcar",
      (filas["fotos"].en_pen, filas["fotos"].origen),
      (False, pair_editor.ORIGEN_SIN_USAR))

    modificado = {**raw, "pair": [{**BASE[0], "remote_path": "/R/mio"}, dict(BASE[1])]}
    filas = {f.name: f for f in pair_editor.catalog_rows(
        model.parse_config(modificado), modificado, cat)}
    c("una pareja divergente se marca", filas["notas"].origen, pair_editor.ORIGEN_LOCAL)
    c("y se dice en qué difiere", filas["notas"].difiere, ("remote_path",))

    huerfana = {**raw, "pair": [dict(BASE[0]), dict(BASE[1]),
                                {"name": "vieja", "local": "sync-data/vieja",
                                 "remote_path": "/R/vieja", "mode": "up"}]}
    filas = {f.name: f for f in pair_editor.catalog_rows(
        model.parse_config(huerfana), huerfana, cat)}
    c("la que ya no está en el catálogo se marca huérfana",
      filas["vieja"].origen, pair_editor.ORIGEN_HUERFANA)

    c("sin catálogo no se inventa un origen",
      pair_editor.catalog_rows(model.parse_config(raw), raw, None)[0].origen,
      pair_editor.ORIGEN_DESCONOCIDO)

with sandbox():
    modificado = {"defaults": {"remote": "nas"},
                  "pair": [{**BASE[0], "remote_path": "/R/mio"}, dict(BASE[1])]}
    raw = preparar(pairs=modificado["pair"])
    cat = falso_catalogo()
    dar_baseline(raw, "notas")

    plan = pair_editor.plan_revert(raw, cat, "notas")
    c("volver al catálogo aparta el baseline (cambia el extremo)", plan.shelve, ["notas"])
    plan.execute()
    c("y la pareja vuelve a la del catálogo",
      next(p.remote_path for p in model.load_config().pairs if p.name == "notas"),
      "/R/notas")

    try:
        pair_editor.plan_revert(config_file.load_raw(), cat, "notas")
        c("volver cuando ya coincide se rechaza", "no lanzó", "ConfigError")
    except ConfigError as e:
        c("volver cuando ya coincide se rechaza", "ya es exactamente" in str(e), True)

with sandbox():
    raw = preparar()
    cat = falso_catalogo()
    c("los defaults iguales salen como del catálogo",
      pair_editor.defaults_origin(raw, cat), (pair_editor.ORIGEN_CATALOGO, ()))

    distintos = {**raw, "defaults": {"remote": "nas", "keep_logs": True}}
    c("y si difieren se dice en qué",
      pair_editor.defaults_origin(distintos, cat),
      (pair_editor.ORIGEN_LOCAL, ("keep_logs",)))

    model.CONFIG_FILE.write_text(config_file.dumps(distintos), encoding="utf-8")
    pair_editor.plan_revert_defaults(distintos, cat).execute()
    c("volver a los defaults del catálogo los deja igual",
      config_file.load_raw()["defaults"], cat.defaults)

# simular: ver lo que haría una pareja, sin hacerlo
#
# Lo que se comprueba es que la orden sea la de un simulacro y no la de una
# pasada: este botón está para poder VER los borrados antes de aprobarlos.
with sandbox():
    raw = preparar()
    c("simular es un --dry-run de esa pareja",
      pair_editor.simular_args(raw, "notas"), ["notas", "--dry-run"])
    c("y no lleva --yes: una pareja sin baseline tiene que salir saltada",
      "--yes" in pair_editor.simular_args(raw, "notas"), False)
    try:
        pair_editor.simular_args(raw, "fotos")
        c("simular una que este dispositivo no usa se rechaza", "no lanzó", "ConfigError")
    except ConfigError as e:
        c("simular una que este dispositivo no usa se rechaza",
          "no se usa en este dispositivo" in str(e), True)

# watch: el formulario la edita, y el cambio de modo la apaga en vez de fallar
#
# Solo vale donde el local es origen. Antes el formulario no la conocía, así que
# una pareja con `watch = true` a la que se le cambiaba el modo a `down` acababa
# en un ConfigError del parseo sin que el formulario pudiera quitar la clave.
with sandbox():
    c("watch es del formulario y opcional",
      ("watch" in pair_editor.FORM_KEYS, "watch" in pair_editor.OPTIONAL_KEYS),
      (True, True))
    c("se admite donde el local es origen",
      [pair_editor.admite_watch(m) for m in ("bisync", "up", "up-mirror")],
      [True, True, True])
    c("y no donde el origen es el remoto, ni en un modo que no existe",
      [pair_editor.admite_watch(m) for m in ("down", "down-mirror", "nada")],
      [False, False, False])

    raw = preparar()
    base = {"name": "diaria", "local": "sync-data/diaria", "remote_path": "/R/diaria",
            "mode": "up", "watch": True}
    plan = pair_editor.plan_save(raw, base)
    c("un alta con watch la guarda",
      next(p for p in plan.raw["pair"] if p["name"] == "diaria").get("watch"), True)
    c("y lo cuenta", any("agente residente" in x for x in plan.consequences), True)
    plan.execute()
    raw = config_file.load_raw()
    c("watch sobrevive a escribirse y leerse",
      next(p for p in model.load_config().pairs if p.name == "diaria").watch, True)

    # Apagarla desde la casilla: desaparece la clave, no queda un `false`.
    plan = pair_editor.plan_save(raw, {**base, "watch": False}, "diaria")
    c("desmarcar la casilla quita la clave",
      "watch" in next(p for p in plan.raw["pair"] if p["name"] == "diaria"), False)
    c("y lo cuenta", any("Se deja de vigilar" in x for x in plan.consequences), True)

    # Cambiar el modo a uno donde no vale, con la casilla aún marcada (un
    # formulario que no la desmarcara): no falla, la quita y lo dice.
    try:
        plan = pair_editor.plan_save(raw, {**base, "mode": "down"}, "diaria")
    except ConfigError as e:
        c("pasar a down con watch marcada no falla", str(e), "no lanzó")
    else:
        hecha = next(p for p in plan.raw["pair"] if p["name"] == "diaria")
        c("pasar a down con watch marcada la quita", ("watch" in hecha, hecha["mode"]),
          (False, "down"))
        c("y se dice por qué",
          any("Se deja de vigilar" in x and "'down'" in x for x in plan.consequences),
          True)
        plan.execute()
        c("el config resultante parsea",
          next(p for p in model.load_config().pairs if p.name == "diaria").watch, False)

    # Lo mismo con el formulario tal como lo devuelve la casilla ya desmarcada.
    c("clean_form no deja pasar watch en down",
      "watch" in pair_editor.clean_form({"name": "x", "mode": "down-mirror",
                                         "watch": True}), False)
    c("y en bisync sí",
      pair_editor.clean_form({"name": "x", "mode": "bisync", "watch": True})["watch"],
      True)
    c("una casilla apagada no escribe false",
      "watch" in pair_editor.clean_form({"name": "x", "mode": "up", "watch": False}),
      False)

sys.exit(c.report())
