#!/usr/bin/env python3
"""El editor del catálogo (`ui/catalog_editor.py`).

Dos cosas que comprobar. La primera, que un plan del catálogo NO toca este
dispositivo: crear, editar o borrar allí deja el `sync_config.toml` exactamente
igual, y es justo la separación que da sentido a todo esto. La segunda, los
vetos: no se puede borrar la pareja con la que se siembra un dispositivo nuevo,
ni escribir partiendo de la copia local.
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
    """Devuelve un catálogo de mentira con esos datos."""
    datos = raw if raw is not None else CAT
    texto = config_file.dumps(datos)
    return catalog.Catalog(raw=tomllib.loads(texto), text=texto, source=source,
                           stamp="2026-01-01 00:00:00",
                           endpoint="nas:/prdrive-catalog/pairs.toml")


def rechaza(etiqueta, hacer, fragmento):
    """Comprueba que `hacer()` lance `ConfigError` con ese fragmento en el mensaje."""
    try:
        hacer()
        c(etiqueta, "no lanzó", "ConfigError")
    except ConfigError as e:
        c(etiqueta, fragmento in str(e), True)


# alta
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

# edición
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

# baja
plan = catalog_editor.plan_catalog_remove(cat, "notas")
c("borrar quita la pareja del catálogo",
  [p["name"] for p in plan.new_raw["pair"]], ["respaldo"])
c("y se dice que los dispositivos que la usan no la pierden",
  any("huérfana" in x for x in plan.consequences), True)

# No hay ninguna pareja intocable: el instalador lleva el código dentro y todas
# valen lo mismo.
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

# [defaults]
plan = catalog_editor.plan_catalog_defaults(cat, {"remote": "otro", "keep_logs": True})
c("los defaults del catálogo se sustituyen enteros",
  plan.new_raw["defaults"], {"remote": "otro", "keep_logs": True})
c("y se avisa del alcance que tienen",
  any("TODAS las parejas" in x for x in plan.consequences), True)
rechaza("defaults iguales no suben nada",
        lambda: catalog_editor.plan_catalog_defaults(cat, dict(CAT["defaults"])),
        "exactamente igual")
# El mismo formulario que el del dispositivo, y la misma regla (#48).
rechaza("una carpeta por ruta del catálogo no sube",
        lambda: catalog_editor.plan_catalog_defaults(
            cat, {**CAT["defaults"], "catalog_path": "/prdrive-catalog"}),
        "no termina en .toml")

# vetos de escritura
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

# y lo importante: nada de esto toca este dispositivo
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

# lo que dice la pantalla del catálogo que enseña (#66)
#
# Se abre con la copia local y lee el remoto en segundo plano. Lo que se comprueba
# es la regla: solo se edita lo recién leído del remoto, y nunca mientras se lee.
lectura = catalog_editor.lectura
copia, remoto = falso("cache"), falso("remote")

leyendo = lectura(copia, None, True)
c("leyendo con copia: el chip dice que es la copia, y de cuándo",
  leyendo.chip, "copia local · 2026-01-01 00:00:00")
c("  la línea lo explica y la barra va", (leyendo.leyendo, "copia local del 2026-01-01"
                                          in leyendo.linea), (True, True))
c("  y no se puede editar", leyendo.editable, False)

sin_copia = lectura(None, None, True)
c("leyendo sin copia: se dice que se está leyendo",
  (sin_copia.chip, sin_copia.linea, sin_copia.editable),
  ("leyendo el catálogo…", catalog_editor.LEYENDO_SIN_COPIA, False))

releyendo = lectura(remoto, None, True)
c("releyendo lo ya leído: tampoco se edita mientras", (releyendo.editable,
                                                         releyendo.linea),
  (False, catalog_editor.RELEYENDO))

leido = lectura(remoto, None, False)
c("leído del remoto: se edita y no hay nada que explicar",
  (leido.chip, leido.linea, leido.leyendo, leido.editable),
  ("catálogo leído · 2026-01-01 00:00:00", "", False, True))

caido = lectura(copia, "Sin conexión con el catálogo. motivo", False)
c("remoto caído: se queda la copia, en ámbar, con el aviso de catalog.load()",
  (caido.chip, caido.tipo, caido.tono, caido.linea, caido.editable),
  ("copia local · 2026-01-01 00:00:00", "Aviso.", "Aviso.",
   "Sin conexión con el catálogo. motivo", False))

nada = lectura(None, None, False)
c("sin catálogo ni aviso: en rojo, y dice qué queda",
  (nada.chip, nada.tipo, nada.linea), ("sin catálogo", "Peligro.",
                                       catalog_editor.SIN_CATALOGO))

sin_fecha = lectura(falso("cache")._replace(stamp=catalog.SIN_FECHA), None, True)
c("una copia sin fecha no dice «del fecha desconocida»",
  ("del fecha" in sin_fecha.linea, "no consta de cuándo es" in sin_fecha.linea),
  (False, True))

# «Renombrar el catálogo…»: qué se puede hacer, con lo leído del remoto
import subprocess  # noqa: E402
import json  # noqa: E402

from common import fleet, store  # noqa: E402

VIEJO_CFG = {"defaults": {"remote": "nas", "catalog_path": "/prdrive-catalog/pairs.toml"}}
SITIO = catalog.sin_renombrar(VIEJO_CFG)
c("los dos nombres del catálogo de este dispositivo", SITIO,
  catalog.SinRenombrar("nas:/prdrive-catalog/remote.toml",
                       "nas:/prdrive-catalog/pairs.toml", "nas:/prdrive-catalog/"))
c("  con un nombre propio no hay nada que renombrar",
  catalog.sin_renombrar({"defaults": {"catalog_path": "/c/mio.toml"}}), None)

SABE = fleet.ENTIENDE
YO = fleet.Dispositivo("yo", "este", "0.5.3", (), "2026-10-01 10:00:00", "ok")
AL_DIA = fleet.Dispositivo("b", "el azul", "0.5.4", (), "2026-10-02 10:00:00", "ok",
                           entiende=SABE)
VIEJO = fleet.Dispositivo("v", "el del cajón", "0.5.3", (), "2026-05-02 10:00:00", "ok")
SIN_VERSION = fleet.Dispositivo("s", "el de casa", "desconocida", (), "", "ok")
SOLO_VIEJO = frozenset({"pairs.toml", "pairs.toml.bak"})
renombrado = catalog_editor.renombrado

bien = renombrado(SITIO, SOLO_VIEJO, [YO, AL_DIA], None, "yo")
c("con toda la flota al día se puede renombrar", (bien.accion, bien.bloquean),
  (catalog_editor.RENOMBRAR, ()))
c("  y este dispositivo no cuenta aunque su nota sea de antes de actualizarse",
  bien.linea, "El otro dispositivo de la flota ya sabe leer el nombre nuevo.")
solo = renombrado(SITIO, SOLO_VIEJO, [], None, "yo")
c("sin flota también: no hay nadie a quien dejar atrás", solo.accion,
  catalog_editor.RENOMBRAR)

parado = renombrado(SITIO, SOLO_VIEJO, [YO, AL_DIA, VIEJO, SIN_VERSION], None, "yo")
c("con uno de antes no se puede", parado.accion, "")
c("  y se dice quiénes", [b.nombre for b in parado.bloquean], ["el del cajón", "el de casa"])
c("  con su versión", parado.bloquean[0].motivo, "lleva la 0.5.3, de antes del nombre nuevo")
c("  o que no la dice", parado.bloquean[1].motivo, "su nota no dice qué versión lleva")
c("  y cuándo se le vio", parado.bloquean[0].visto, "2026-05-02 10:00:00")
c.contains("  y cómo se desbloquea", parado.linea, "«Dispositivos…»")
c("  en ámbar", parado.tono, "Aviso.")

c("sin poder leer la flota no se decide",
  renombrado(SITIO, SOLO_VIEJO, [], "sin red", "yo").accion, "")
c("sin poder mirar la carpeta tampoco", renombrado(SITIO, None, [], None, "yo").accion, "")
ya = renombrado(SITIO, frozenset({"remote.toml"}), [], None, "yo")
c("renombrado ya, no hay nada que hacer", (ya.accion, ya.tono), ("", "Pista."))
dos = renombrado(SITIO, frozenset({"remote.toml", "pairs.toml"}), [VIEJO], None, "yo")
c("con los dos, se ofrece apartar el que sobra", dos.accion, catalog_editor.APARTAR)
c("sin ninguno, nada", renombrado(SITIO, frozenset(), [], None, "yo").accion, "")
c("con un nombre propio, nada", renombrado(None, None, [], None, "yo").accion, "")

plan = catalog_editor.plan_renombrar(bien, VIEJO_CFG)
c.contains("el plan dice qué pasa a llamarse cómo", plan.consequences[0],
           "nas:/prdrive-catalog/pairs.toml pasa a llamarse remote.toml")
c("  que afecta a todos", catalog_editor.ALCANCE in plan.consequences, True)
c.contains("  y avisa de los instaladores de antes", " ".join(plan.warnings),
           "instalador de una versión anterior")
c.contains("apartar tiene su propio plan",
           catalog_editor.plan_renombrar(dos, VIEJO_CFG).consequences[0], ".apartado-")
rechaza("sin nada que hacer no hay plan",
        lambda: catalog_editor.plan_renombrar(parado, VIEJO_CFG), "Todavía no")


def lsjson(nombres, flota_rc=0):
    """`catalog.run` que contesta el listado de la carpeta y la copia de la flota."""
    vistas: list[list[str]] = []

    def _run(args):
        vistas.append(list(args))
        if args[:2] == ["lsjson", "--files-only"]:
            return subprocess.CompletedProcess(
                args, 0, json.dumps([{"Name": n, "IsDir": False} for n in nombres]), "")
        return subprocess.CompletedProcess(args, flota_rc, "", "")
    catalog.run = _run
    return vistas


with sandbox():
    vistas = lsjson(["pairs.toml"])
    nombres, flota, aviso = catalog_editor.leer_renombrado(VIEJO_CFG)
    c("leer mira la carpeta del catálogo", vistas[0],
      ["lsjson", "--files-only", "nas:/prdrive-catalog/"])
    c("  y, si hace falta para decidir, la flota", [v[0] for v in vistas], ["lsjson", "copy"])
    c("  y lo devuelve", (nombres, flota, aviso), (frozenset({"pairs.toml"}), [], None))

    vistas = lsjson(["remote.toml"])
    catalog_editor.leer_renombrado(VIEJO_CFG)
    c("si ya está renombrado no lee la flota", len(vistas), 1)

    vistas = lsjson(["remote.toml", "pairs.toml"])
    catalog_editor.leer_renombrado(VIEJO_CFG)
    c("si están los dos, lo apunta para «Reparación»", catalog.duplicado()[0],
      "nas:/prdrive-catalog/pairs.toml")
    lsjson(["remote.toml"])
    catalog_editor.leer_renombrado(VIEJO_CFG)
    c("  y lo borra cuando ya no", catalog.duplicado(), None)

# «Ajustes» ofrece la entrada solo si lo último leído fue pairs.toml
ofrece = catalog_editor.ofrecer_renombrado
with sandbox():
    c("sin ninguna lectura no se ofrece", ofrece(VIEJO_CFG), False)
    store.write_json(catalog.cache_meta(), {"endpoint": "nas:/prdrive-catalog/pairs.toml"})
    c("si lo último leído fue pairs.toml, sí", ofrece(VIEJO_CFG), True)
    c("  diga lo que diga el dispositivo",
      ofrece({"defaults": {"remote": "nas", "catalog_path": "/prdrive-catalog/remote.toml"}}),
      True)
    store.write_json(catalog.cache_meta(), {"endpoint": "nas:/prdrive-catalog/remote.toml"})
    c("si fue remote.toml, no", ofrece(VIEJO_CFG), False)
    catalog.apuntar_duplicado("nas:/prdrive-catalog/pairs.toml")
    c("  salvo que consten los dos", ofrece(VIEJO_CFG), True)
    c("con un nombre propio, nunca", ofrece({"defaults": {"catalog_path": "/c/mio.toml"}}),
      False)

sys.exit(c.report())
