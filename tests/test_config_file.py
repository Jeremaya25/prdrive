#!/usr/bin/env python3
"""
El serializador de TOML: lo que escribe tiene que releerse exactamente igual.

Este fichero gobierna qué se sincroniza y qué se borra, así que la prueba que
importa es la ida y vuelta, y se hace también contra el sync_config.toml real
del pen (en memoria: no se escribe nada sobre él).
"""

import sys
import tomllib

from _harness import Checks, sandbox

from common import config_file, model

c = Checks("serializador de sync_config.toml")


def ida_y_vuelta(raw, etiqueta):
    texto = config_file.dumps(raw)
    try:
        vuelta = tomllib.loads(texto)
    except tomllib.TOMLDecodeError as e:
        c(f"{etiqueta}: genera TOML válido", f"error: {e}", "sin error")
        return None
    c(f"{etiqueta}: ida y vuelta", vuelta, dict(raw))
    return vuelta


# --- el config real del pen -------------------------------------------------
real = config_file.load_raw()
vuelta = ida_y_vuelta(real, "config real")
if vuelta is not None:
    c("config real: misma Config resuelta",
      model.parse_config(vuelta), model.parse_config(real))
c("config real: se conserva la cabecera",
  config_file.header().startswith("#"), True)

# --- casos que el esquema permite -------------------------------------------
ida_y_vuelta({
    "defaults": {"remote": "nas", "pen_remote": "pen", "keep_logs": True,
                 "exclude": ["a/**"], "include": [],
                 "flags": {"transfers": 4, "checkers": 8, "resilient": True}},
    "daemon": {"pairs": ["uno"], "interval_minutes": 12.5},
    "pair": [{"name": "uno", "local": "sync-data/uno", "remote_path": "/R/uno",
              "mode": "bisync", "include": ["*.md"],
              "flags": {"conflict-resolve": "newer", "max-delete": 25}}],
}, "todos los tipos")

# Caracteres que hay que escapar: barras invertidas (rutas de Windows) y comillas.
ida_y_vuelta({
    "defaults": {"remote": "nas"},
    "pair": [{"name": "raro", "local": "sync-data/raro", "remote_path": "/R/raro",
              "mode": "up", "exclude": ["con\\barra/**", 'con"comilla/**',
                                        "con'apostrofo/**", "$RECYCLE.BIN/**"]}],
}, "escapado")

# EL caso delicado: [pair.flags] se engancha a la ÚLTIMA [[pair]] escrita, así que
# unos flags mal colocados se los quedaría la pareja equivocada.
tres = {
    "defaults": {"remote": "nas"},
    "pair": [
        {"name": "primera", "local": "sync-data/a", "remote_path": "/R/a", "mode": "up"},
        {"name": "segunda", "local": "sync-data/b", "remote_path": "/R/b", "mode": "bisync",
         "flags": {"conflict-resolve": "path2"}},
        {"name": "tercera", "local": "sync-data/c", "remote_path": "/R/c", "mode": "down"},
    ],
}
vuelta = ida_y_vuelta(tres, "flags en la pareja de en medio")
if vuelta:
    c("los flags caen en la pareja correcta",
      [p.get("flags") for p in vuelta["pair"]],
      [None, {"conflict-resolve": "path2"}, None])

# --- save(): valida antes de escribir, y deja copia --------------------------
with sandbox() as root:
    destino = root / "sync_config.toml"
    destino.write_text("# cabecera que debe sobrevivir\n\n[defaults]\nremote = \"viejo\"\n",
                       encoding="utf-8")

    bueno = {"defaults": {"remote": "nas"},
             "pair": [{"name": "uno", "local": "sync-data/uno",
                       "remote_path": "/R/uno", "mode": "up"}]}
    backup = config_file.save(bueno, destino)
    c("save deja copia .bak", backup.exists(), True)
    c("save escribe lo pedido", config_file.load_raw(destino), bueno)
    c.contains("save conserva la cabecera", destino.read_text(encoding="utf-8"),
               "# cabecera que debe sobrevivir")

    antes = destino.read_text(encoding="utf-8")
    malo = {"pair": [{"name": "x", "local": "a", "remote_path": "/b", "mode": "inventado"}]}
    try:
        config_file.save(malo, destino)
        c("save rechaza un modo inválido", "no lanzó", "ConfigError")
    except model.ConfigError as e:
        c("save rechaza un modo inválido", "modo inválido" in str(e), True)
    c("save no ha tocado el fichero al rechazar",
      destino.read_text(encoding="utf-8"), antes)

    try:
        config_file.save({"defaults": {"remote": "n"}, "pair": []}, destino)
        c("save rechaza un config sin parejas", "no lanzó", "ConfigError")
    except model.ConfigError:
        c("save rechaza un config sin parejas", True, True)

sys.exit(c.report())
