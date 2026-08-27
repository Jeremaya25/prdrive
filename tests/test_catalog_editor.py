#!/usr/bin/env python3
"""
El editor del catálogo (ui/catalog_editor.py).

Dos cosas que comprobar. La primera, que un plan del catálogo NO toca este dispositivo:
crear, editar o borrar allí deja el sync_config.toml exactamente igual, y es
justo la separación que da sentido a todo esto. La segunda, los vetos: no se
puede borrar la pareja con la que se siembra un dispositivo nuevo, ni escribir partiendo
de la copia local.
"""

import sys
import tomllib

from _harness import Checks, sandbox

from common import catalog, config_file, model
from common.model import ConfigError

from ui import catalog_editor

c = Checks("editor del catálogo (ui/catalog_editor.py)")

CAT = {"defaults": {"remote": "nas"},
       "pair": [{"name": "respaldo", "local": ".", "remote_path": "/prdrive",
                 "mode": "up-mirror"},
                {"name": "notas", "local": "sync-data/notas",
                 "remote_path": "/R/notas", "mode": "bisync"}]}
LOCAL = {"defaults": {"remote": "nas"},
         "pair": [dict(CAT["pair"][1])]}
NUEVA = {"name": "fotos", "local": "sync-data/fotos", "remote_path": "/R/fotos",
         "mode": "up", "include": [], "exclude": []}


def falso(source="remote", raw=None):
    datos = raw if raw is not None else CAT
    texto = config_file.dumps(datos)
    return catalog.Catalog(raw=tomllib.loads(texto), text=texto, source=source,
                           stamp="2026-01-01 00:00:00",
                           endpoint="nas:/prdrive-catalog/pairs.toml")


def rechaza(etiqueta, hacer, fragmento):
    try:
        hacer()
        c(etiqueta, "no lanzó", "ConfigError")
    except ConfigError as e:
        c(etiqueta, fragmento in str(e), True)


# --- alta ---------------------------------------------------------------------
cat = falso()
plan = catalog_editor.plan_catalog_save(cat, NUEVA, None)
c("el alta añade la pareja al catálogo",
  [p["name"] for p in plan.new_raw["pair"]], ["respaldo", "notas", "fotos"])
c("el catálogo leído no se ha tocado", [p["name"] for p in cat.raw["pair"]],
  ["respaldo", "notas"])
c("se escribe partiendo del texto que se leyó", plan.base_text, cat.text)
c("se avisa de que afecta a todos",
  any("TODOS" in x for x in plan.consequences), True)
c("y de que aquí todavía no se usa",
  any("Todavía no la usa ningún dispositivo" in x for x in plan.consequences), True)
c("y de que se pierden los comentarios",
  any("comentarios intercalados" in x for x in plan.consequences), True)

# --- edición ------------------------------------------------------------------
plan = catalog_editor.plan_catalog_save(
    cat, {**CAT["pair"][1], "mode": "down-mirror", "include": [], "exclude": []}, "notas")
c("editar cambia solo esa pareja",
  [p["mode"] for p in plan.new_raw["pair"]], ["up-mirror", "down-mirror"])
c("se dice qué cambia", any("mode" in x for x in plan.consequences), True)
c("se recuerda que los dispositivos no cambian solos",
  any("no cambian solos" in x for x in plan.consequences), True)
c("y un espejo se anuncia como espejo",
  any("BORRA en el dispositivo" in w for w in plan.warnings), True)

rechaza("editar sin cambiar nada no sube nada",
        lambda: catalog_editor.plan_catalog_save(
            cat, {**CAT["pair"][1], "include": [], "exclude": []}, "notas"),
        "exactamente igual")

# --- baja ---------------------------------------------------------------------
plan = catalog_editor.plan_catalog_remove(cat, "notas")
c("borrar quita la pareja del catálogo",
  [p["name"] for p in plan.new_raw["pair"]], ["respaldo"])
c("y se dice que los dispositivos que la usan no la pierden",
  any("huérfana" in x for x in plan.consequences), True)

# Ya no hay ninguna pareja intocable: cuando el código bajaba del remoto, la que
# describía ese espejo era imprescindible para instalar y el editor se negaba a
# borrarla. Ahora el instalador lleva el código dentro y todas valen lo mismo.
plan = catalog_editor.plan_catalog_remove(cat, "respaldo")
c("ninguna pareja es imprescindible ya",
  [p["name"] for p in plan.new_raw["pair"]], ["notas"])

rechaza("no se puede borrar una que no existe",
        lambda: catalog_editor.plan_catalog_remove(cat, "inventada"),
        "No hay ninguna pareja")

solo_una = falso(raw={"defaults": {"remote": "nas"}, "pair": [CAT["pair"][1]]})
rechaza("no se puede dejar el catálogo vacío",
        lambda: catalog_editor.plan_catalog_remove(solo_una, "notas"),
        "sin ninguna pareja")

# --- [defaults] ---------------------------------------------------------------
plan = catalog_editor.plan_catalog_defaults(cat, {"remote": "otro", "keep_logs": True})
c("los defaults del catálogo se sustituyen enteros",
  plan.new_raw["defaults"], {"remote": "otro", "keep_logs": True})
c("y se avisa del alcance que tienen",
  any("TODAS las parejas" in x for x in plan.consequences), True)
rechaza("defaults iguales no suben nada",
        lambda: catalog_editor.plan_catalog_defaults(cat, dict(CAT["defaults"])),
        "exactamente igual")

# --- vetos de escritura -------------------------------------------------------
rechaza("sin catálogo no se puede crear nada",
        lambda: catalog_editor.plan_catalog_save(None, NUEVA, None),
        "No hay catálogo")
rechaza("desde la copia local no se escribe",
        lambda: catalog_editor.plan_catalog_save(falso("cache"), NUEVA, None),
        "copia local del catálogo")
rechaza("la validación es la misma que en el dispositivo",
        lambda: catalog_editor.plan_catalog_save(
            cat, {**NUEVA, "name": "a/b"}, None),
        "state/")

# --- y lo importante: nada de esto toca este dispositivo ------------------------------
with sandbox():
    model.CONFIG_FILE.write_text(config_file.dumps(LOCAL), encoding="utf-8")
    antes = model.CONFIG_FILE.read_text(encoding="utf-8")
    subidos = []
    catalog.push = lambda new_raw, base_text, raw_local=None: (
        subidos.append(dict(new_raw)) or ["subido"])

    catalog_editor.plan_catalog_save(falso(), NUEVA, None).execute()
    catalog_editor.plan_catalog_remove(falso(), "notas").execute()
    c("dos cambios de catálogo, dos subidas", len(subidos), 2)
    c("y el config de este dispositivo intacto",
      model.CONFIG_FILE.read_text(encoding="utf-8"), antes)
    c("no ha aparecido ningún state/", list(model.STATE_DIR.iterdir()), [])

sys.exit(c.report())
