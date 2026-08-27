#!/usr/bin/env python3
"""
Del catálogo del remoto al sync_config.toml de un dispositivo.

Lo que se comprueba es que el instalador escribe un config que sync.py sabe leer,
que no se inventa nada y que no pierde nada por el camino: los flags de cada
pareja pegados a SU pareja, el [daemon] recortado a lo que existe, y los
[defaults] SIN duplicar dentro de cada [[pair]] —que es justo lo que pasaría si
se volcara un model.Config en vez del dict crudo—.

No toca la red: el catálogo es un texto de aquí.
"""

import sys
import tomllib
from pathlib import Path

from _harness import Checks, tmpdir

from common import model
from install import InstallError, deploy, remote

c = Checks("instalador: catálogo -> sync_config.toml")

CATALOGO = """\
# Catálogo global de parejas — vive en el remoto.
# Segunda línea de la cabecera.

[defaults]
remote = "nas"
exclude = ["**/.stfolder/**", "**/.stignore"]

[defaults.flags]
transfers = 4
checkers = 8

[daemon]
pairs = ["docs", "claves"]
interval_minutes = 15

[[pair]]
name = "docs"
local = "sync-data/docs"
remote_path = "/datos/docs"
mode = "bisync"

[pair.flags]
conflict-resolve = "path2"

[[pair]]
name = "prdrive"
local = "."
remote_path = "/prdrive"
mode = "up-mirror"
exclude = ["sync-data/**"]

[[pair]]
name = "upload"
local = "sync-data/upload"
remote_path = "/datos/varios"
mode = "up"
"""

cat = remote.parse_catalog(CATALOGO)

# --- lo que se ha leído -------------------------------------------------------
c("las parejas del catálogo", cat.names, ["docs", "prdrive", "upload"])
c("la cabecera de comentarios se conserva",
  cat.head.splitlines()[0], "# Catálogo global de parejas — vive en el remoto.")
c("la cabecera se corta donde empieza el TOML", "[defaults]" in cat.head, False)
c("pair() encuentra por nombre", (cat.pair("upload") or {}).get("mode"), "up")
c("pair() de una que no está", cat.pair("fantasma"), None)

# --- un catálogo inválido se rechaza AL LEERLO, no al usarlo -------------------
try:
    remote.parse_catalog('[[pair]]\nname="x"\nlocal="a"\nremote_path="/b"\nmode="raro"\n')
    c("un modo inválido en el catálogo se rechaza", "no lanzó", "InstallError")
except InstallError as e:
    c("un modo inválido en el catálogo se rechaza", "modo inválido" in str(e), True)

try:
    remote.parse_catalog("esto no es { toml")
    c("un catálogo que no es TOML se rechaza", "no lanzó", "InstallError")
except InstallError:
    c("un catálogo que no es TOML se rechaza", True, True)

# --- el dict del dispositivo --------------------------------------------------
raw = deploy.device_config(cat, ["docs", "upload"])
c("solo las parejas elegidas", [p["name"] for p in raw["pair"]], ["docs", "upload"])
c("los defaults viajan enteros", raw["defaults"]["flags"], {"transfers": 4, "checkers": 8})
c("los defaults NO se duplican dentro de la pareja",
  raw["pair"][1].get("flags"), None)
c("los flags propios de la pareja sí",
  raw["pair"][0]["flags"], {"conflict-resolve": "path2"})

# [daemon] nombraba 'claves', que este dispositivo no lleva: si sobreviviera, el
# servicio fallaría en cada ciclo intentando sincronizar algo que no está.
c("el [daemon] se recorta a lo que existe", raw["daemon"]["pairs"], ["docs"])
c("y el resto del [daemon] se respeta", raw["daemon"]["interval_minutes"], 15)

sin_daemon = deploy.device_config(remote.parse_catalog(
    CATALOGO.replace('pairs = ["docs", "claves"]', 'pairs = ["claves"]')),
    ["upload"])
c("un [daemon] que se queda sin parejas válidas pierde la clave",
  "pairs" in sin_daemon.get("daemon", {}), False)

# --- lo que no se permite -----------------------------------------------------
for etiqueta, seleccion in (("ninguna pareja", []), ("una que no existe", ["fantasma"])):
    try:
        deploy.device_config(cat, seleccion)
        c(f"se rechaza {etiqueta}", "no lanzó", "InstallError")
    except InstallError:
        c(f"se rechaza {etiqueta}", True, True)

# --- el fichero escrito de verdad --------------------------------------------
dispositivo = tmpdir() / "dispositivo"
destino = deploy.write_device_config(dispositivo, cat, ["docs", "prdrive"])
c("se escribe donde toca", destino, dispositivo / deploy.APP_SUBDIR / "sync_config.toml")

texto = destino.read_text(encoding="utf-8")
c.contains("dice quién lo ha generado", texto, "Generado por prdrive-install")
c.contains("y conserva la cabecera del catálogo", texto, "Catálogo global de parejas")

# La prueba de fuego: que el modelo del proyecto lo lea igual que el suyo propio.
with destino.open("rb") as f:
    cfg = model.parse_config(tomllib.load(f))
c("model.parse_config lo lee", cfg.names, ["docs", "prdrive"])
c("la pareja bisync conserva su conflict-resolve",
  cfg.pairs[0].flags["conflict-resolve"], "path2")
c("y hereda los [defaults.flags]", cfg.pairs[0].flags["transfers"], 4)
c("el espejo conserva su exclude propio",
  "sync-data/**" in cfg.pairs[1].excludes, True)
c("y también los excludes de [defaults]",
  "**/.stfolder/**" in cfg.pairs[1].excludes, True)

sys.exit(c.report())
