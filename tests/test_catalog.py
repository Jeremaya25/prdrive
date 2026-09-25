#!/usr/bin/env python3
"""
El catálogo del remoto (common/catalog.py).

`catalog.run` se sustituye entera: aquí no se habla con ningún remoto. Lo que se
comprueba es lo que puede hacer daño de verdad —que escribir se niegue cuando el
remoto ha cambiado bajo nuestros pies, y que la copia de seguridad se suba ANTES
que el fichero nuevo— y lo que sostiene la pantalla cuando no hay red.
"""

import subprocess
import sys
import tomllib

from _harness import Checks, sandbox

from common import catalog, config_file, model
from install import profile
from common.model import ConfigError

c = Checks("catálogo del remoto (common/catalog.py)")

CAT = {"defaults": {"remote": "nas", "exclude": ["**/.stfolder/**"]},
       "pair": [{"name": "prdrive", "local": ".", "remote_path": "/prdrive",
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
c("el endpoint por defecto sale de las constantes compartidas", catalog.endpoint(),
  f"{model.DEFAULT_REMOTE}:{catalog.DEFAULT_CATALOG_PATH}")
# El instalador lee el catálogo cuando todavía no hay dispositivo, así que tiene
# que buscarlo en el mismo sitio. Antes eran dos cadenas iguales en dos módulos
# que no se importaban; ahora hay una sola y esto lo vigila.
c("y el instalador usa exactamente esa", profile.empty().catalog_path,
  catalog.DEFAULT_CATALOG_PATH)
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
    cat = catalog.pull(CAT)
    c("leer usa 'cat' contra el endpoint", llamadas[0],
      ["cat", "nas:/prdrive-catalog/pairs.toml"])
    # El diagnóstico de la carpeta (#48) solo pregunta cuando algo huele mal:
    # abrir la ventana de parejas no puede costar una ida y vuelta más.
    c("y en el camino bueno no pregunta nada más", len(llamadas), 1)
    c("y trae las parejas", [p["name"] for p in cat.raw["pair"]], ["prdrive", "notas"])
    c("viene del remoto y por tanto es editable", (cat.source, cat.editable),
      ("remote", True))
    c("ha quedado copia local", catalog.cache_toml().read_text(encoding="utf-8"), TEXTO)

    responder(falla())
    cat, aviso = catalog.load()
    c("sin red se cae a la copia", cat.source, "cache")
    c("y la copia NO se puede editar", cat.editable, False)
    c("con las mismas parejas", [p["name"] for p in cat.raw["pair"]],
      ["prdrive", "notas"])
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
    hechos = catalog.push(nuevo, TEXTO, CAT)

    c("primero se relee el remoto", llamadas[0][0], "cat")
    c("después se copia el .bak, ANTES de escribir", llamadas[1],
      ["copyto", "nas:/prdrive-catalog/pairs.toml",
       "nas:/prdrive-catalog/pairs.toml.bak"])
    c("y por último se sube el fichero nuevo",
      llamadas[2][0] == "copyto" and llamadas[2][-1].endswith("pairs.toml"), True)
    c("se cuenta lo que se ha hecho", len(hechos), 2)

    subido = tomllib.loads(catalog.cache_toml().read_text(encoding="utf-8"))
    c("la copia local queda al día", [p["name"] for p in subido["pair"]],
      ["prdrive", "notas", "fotos"])
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

# --- una carpeta no es un catálogo (#48) ---------------------------------------
# `rclone cat` de una carpeta no falla: junta todo lo que hay dentro. Con el
# pairs.toml y el .bak que deja push(), son dos copias seguidas del catálogo, y
# eso es exactamente el error que se veía. Las respuestas de `lsjson --stat` son
# las de rclone v1.75.1 contra una carpeta y un fichero de verdad.
DOS_COPIAS = TEXTO + TEXTO
try:
    tomllib.loads(DOS_COPIAS)
    c("dos copias seguidas no son TOML", "se leyó", "TOMLDecodeError")
except tomllib.TOMLDecodeError as e:
    c.contains("dos copias seguidas dan el error del issue", str(e),
               "Cannot declare ('defaults',) twice")

STAT_CARPETA = ('{\n\t"Path": "",\n\t"Name": "",\n\t"Size": -1,\n'
                '\t"MimeType": "inode/directory",\n'
                '\t"ModTime": "2026-09-25T11:38:30.975365128Z",\n\t"IsDir": true\n}\n')
STAT_FICHERO = ('{\n\t"Path": "pairs.toml",\n\t"Name": "pairs.toml",\n\t"Size": 94,\n'
                '\t"MimeType": "application/toml",\n'
                '\t"ModTime": "2026-09-25T11:38:30.643855347Z",\n\t"IsDir": false\n}\n')
NO_EXISTE = (3, "", "NOTICE: Failed to lsjson: directory not found")
EN_CARPETA = {"defaults": {"remote": "nas", "catalog_path": "/prdrive-catalog"}}


def lee(raw_local=None):
    """pull() y lo que dijo, o None si no lanzó."""
    try:
        catalog.pull(raw_local)
        return None
    except ConfigError as e:
        return str(e)


with sandbox():
    responder(ok(DOS_COPIAS), ok(STAT_CARPETA), ok(STAT_FICHERO))
    motivo = lee(EN_CARPETA) or ""
    c.contains("una carpeta se dice como carpeta", motivo, "es una carpeta")
    c.contains("y se sugiere el pairs.toml que hay dentro", motivo,
               "«/prdrive-catalog/pairs.toml»")
    c("y no se habla de TOML, que no es la causa", "TOML" in motivo, False)
    c("se pregunta qué es la ruta, y si dentro hay un pairs.toml", llamadas,
      [["cat", "nas:/prdrive-catalog"],
       ["lsjson", "--stat", "nas:/prdrive-catalog"],
       ["lsjson", "--stat", "nas:/prdrive-catalog/pairs.toml"]])
    c("lo que trajo el cat no se cachea", catalog.cache_toml().exists(), False)

    responder(ok(DOS_COPIAS), ok(STAT_CARPETA), ok(STAT_FICHERO))
    cat, aviso = catalog.load(EN_CARPETA)
    c("load() sigue sin lanzar", cat, None)
    c.contains("y el aviso lleva el diagnóstico", aviso or "", "es una carpeta")

with sandbox():
    responder(ok(DOS_COPIAS), ok(STAT_CARPETA), NO_EXISTE)
    motivo = lee(EN_CARPETA) or ""
    c.contains("sin pairs.toml dentro se da un ejemplo", motivo,
               "Por ejemplo «/prdrive-catalog/pairs.toml»")
    c("sin afirmar que esté", "Dentro hay" in motivo, False)

with sandbox():
    # Una carpeta con un solo pairs.toml se lee SIN error: es la ruta que no
    # termina en .toml lo que hace preguntar.
    responder(ok(TEXTO), ok(STAT_CARPETA), ok(STAT_FICHERO))
    c.contains("una carpeta que se lee bien por casualidad también se dice",
               lee(EN_CARPETA) or "", "es una carpeta")

with sandbox():
    # Una carpeta vacía: `cat` sale con 0 y no trae nada.
    responder(ok(""), ok(STAT_CARPETA), NO_EXISTE)
    c.contains("una carpeta vacía también", lee(EN_CARPETA) or "", "es una carpeta")

    responder(ok(""))
    c("un pairs.toml vacío de verdad se sigue leyendo", lee(CAT), None)
    c("sin preguntar nada más", len(llamadas), 1)

with sandbox():
    # Un diagnóstico falso es peor que ninguno.
    responder(ok("esto ] no [ es toml"), ok(STAT_FICHERO))
    c.contains("un fichero que no es TOML sigue diciendo eso", lee(CAT) or "",
               "no es TOML válido")
    responder(ok(DOS_COPIAS), (0, "esto no es json", ""))
    c.contains("una respuesta que no se entiende no diagnostica nada",
               lee(EN_CARPETA) or "", "no es TOML válido")
    responder(ok(DOS_COPIAS), NO_EXISTE)
    c.contains("ni un lsjson que falla", lee(EN_CARPETA) or "", "no es TOML válido")

with sandbox():
    responder(falla())
    lee(EN_CARPETA)
    c("si falla el propio cat no se pregunta nada más: sin red tardaría lo mismo",
      len(llamadas), 1)

with sandbox():
    sin_extension = {"defaults": {"remote": "nas", "catalog_path": "/cat/pares"}}
    responder(ok(TEXTO), ok(STAT_FICHERO))
    c("un catálogo sin .toml que es un fichero se sigue leyendo",
      lee(sin_extension), None)
    c("a costa de una sola pregunta", len(llamadas), 2)

# --- la ruta tecleada ----------------------------------------------------------
c.contains("una carpeta tecleada se rechaza sin red",
           catalog.problema_de_ruta("/prdrive-catalog") or "",
           "«/prdrive-catalog/pairs.toml»")
c.contains("con la barra del final, sin barra doble",
           catalog.problema_de_ruta("/prdrive-catalog/") or "",
           "«/prdrive-catalog/pairs.toml»")
c("un fichero .toml vale", catalog.problema_de_ruta("/x/pairs.toml"), None)
c("en mayúsculas también", catalog.problema_de_ruta("/x/PAIRS.TOML"), None)
c("vacía vale: se cae a la de fábrica", catalog.problema_de_ruta("  "), None)

catalog.validar_ruta_editada({"catalog_path": "/cat/pares"},
                             {"catalog_path": "/cat/pares", "keep_logs": True})
c("una ruta que ya estaba no se revisa al guardar otra cosa", True, True)
try:
    catalog.validar_ruta_editada({}, {"catalog_path": "/prdrive-catalog"})
    c("cambiarla a una carpeta se rechaza", "no lanzó", "ConfigError")
except ConfigError as e:
    c.contains("cambiarla a una carpeta se rechaza", str(e), "no termina en .toml")

sys.exit(c.report())
