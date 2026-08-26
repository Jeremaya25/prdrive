#!/usr/bin/env python3
"""
El catálogo del NAS (common/catalog.py).

`catalog.run` se sustituye entera: aquí no se habla con ningún NAS. Lo que se
comprueba es lo que puede hacer daño de verdad —que escribir se niegue cuando el
remoto ha cambiado bajo nuestros pies, y que la copia de seguridad se suba ANTES
que el fichero nuevo— y lo que sostiene la pantalla cuando no hay red.
"""

import subprocess
import sys
import tomllib

from _harness import Checks, sandbox

from common import catalog, config_file, model
from common.model import ConfigError

c = Checks("catálogo del NAS (common/catalog.py)")

CAT = {"defaults": {"remote": "synology", "exclude": ["**/.stfolder/**"]},
       "pair": [{"name": "perepen", "local": ".", "remote_path": "/PJ/Perepen",
                 "mode": "up-mirror"},
                {"name": "notas", "local": "sync-data/notas",
                 "remote_path": "/R/notas", "mode": "bisync"}]}
CABECERA = "# El catálogo global de parejas.\n# Una línea más de cabecera.\n"
TEXTO = config_file.dumps(CAT, CABECERA)

llamadas: list[list[str]] = []


def responder(*respuestas):
    """Sustituye catalog.run por una cola de respuestas, apuntando cada orden."""
    cola = list(respuestas)
    llamadas.clear()

    def _run(args):
        llamadas.append(list(args))
        rc, salida, error = cola.pop(0) if cola else (0, "", "")
        return subprocess.CompletedProcess(args, rc, salida, error)
    catalog.run = _run


def ok(salida=TEXTO):
    return (0, salida, "")


def falla(error="no route to host"):
    return (1, "", error)


# --- de dónde se lee ---------------------------------------------------------
c("el endpoint por defecto es el del instalador", catalog.endpoint(),
  "synology:/PJ/Perepen-catalog/pairs.toml")
c("[defaults] puede moverlo",
  catalog.endpoint({"defaults": {"remote": "otro", "catalog_path": "/x/y.toml"}}),
  "otro:/x/y.toml")

c("diff_keys ve altas, bajas y cambios",
  catalog.diff_keys({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 4}), ("b", "c"))
c("y dice que no hay diferencia cuando no la hay",
  catalog.diff_keys({"a": 1}, {"a": 1}), ())

# --- leer deja copia, y la copia salva la pantalla sin red -------------------
with sandbox():
    responder(ok())
    cat = catalog.pull()
    c("leer usa 'cat' contra el endpoint", llamadas[0],
      ["cat", "synology:/PJ/Perepen-catalog/pairs.toml"])
    c("y trae las parejas", [p["name"] for p in cat.raw["pair"]], ["perepen", "notas"])
    c("viene del remoto y por tanto es editable", (cat.source, cat.editable),
      ("remote", True))
    c("ha quedado copia local", catalog.cache_toml().read_text(encoding="utf-8"), TEXTO)

    responder(falla())
    cat, aviso = catalog.load()
    c("sin red se cae a la copia", cat.source, "cache")
    c("y la copia NO se puede editar", cat.editable, False)
    c("con las mismas parejas", [p["name"] for p in cat.raw["pair"]],
      ["perepen", "notas"])
    c("y se dice por qué", "Sin conexión" in aviso, True)

with sandbox():
    responder(falla())
    cat, aviso = catalog.load()
    c("sin red y sin copia no hay catálogo", cat, None)
    c("pero se explica, no se revienta", "No hay catálogo" in aviso, True)

with sandbox():
    responder((0, "esto ] no [ es toml", ""))
    cat, aviso = catalog.load()
    c("un catálogo ilegible tampoco revienta", cat, None)
    c("y dice que no es TOML válido", "TOML" in aviso, True)

# --- escribir: lo peligroso ---------------------------------------------------
with sandbox():
    nuevo = {**CAT, "pair": CAT["pair"] + [{"name": "fotos", "local": "sync-data/fotos",
                                            "remote_path": "/R/fotos", "mode": "up"}]}
    responder(ok(), ok(""), ok(""))
    hechos = catalog.push(nuevo, TEXTO)

    c("primero se relee el remoto", llamadas[0][0], "cat")
    c("después se copia el .bak, ANTES de escribir", llamadas[1],
      ["copyto", "synology:/PJ/Perepen-catalog/pairs.toml",
       "synology:/PJ/Perepen-catalog/pairs.toml.bak"])
    c("y por último se sube el fichero nuevo",
      llamadas[2][0] == "copyto" and llamadas[2][-1].endswith("pairs.toml"), True)
    c("se cuenta lo que se ha hecho", len(hechos), 2)

    subido = tomllib.loads(catalog.cache_toml().read_text(encoding="utf-8"))
    c("la copia local queda al día", [p["name"] for p in subido["pair"]],
      ["perepen", "notas", "fotos"])
    c("y la cabecera del catálogo sobrevive",
      catalog.cache_toml().read_text(encoding="utf-8").startswith(CABECERA.rstrip()), True)

with sandbox():
    responder(ok("otra cosa distinta"))
    try:
        catalog.push(CAT, TEXTO)
        c("no se escribe encima de un catálogo cambiado", "no lanzó", "ConfigError")
    except ConfigError as e:
        c("no se escribe encima de un catálogo cambiado", "ha cambiado" in str(e), True)
    c("y no se ha llegado a copiar nada", len(llamadas), 1)

with sandbox():
    responder(ok(), falla("permiso denegado"))
    try:
        catalog.push({**CAT, "pair": [CAT["pair"][0]]}, TEXTO)
        c("si falla el .bak no se escribe", "no lanzó", "ConfigError")
    except ConfigError as e:
        c("si falla el .bak no se escribe", "No se ha escrito nada" in str(e), True)
    c("y no se ha subido nada", len(llamadas), 2)

with sandbox():
    responder(ok())
    try:
        catalog.push({"defaults": {}, "pair": []}, TEXTO)
        c("un catálogo sin parejas se rechaza antes de tocar la red",
          "no lanzó", "ConfigError")
    except ConfigError as e:
        c("un catálogo sin parejas se rechaza antes de tocar la red",
          "ninguna [[pair]]" in str(e), True)
    c("ni siquiera se ha releído el remoto", llamadas, [])

sys.exit(c.report())
