#!/usr/bin/env python3
"""Lo que el parser del config se niega a pasarle a rclone.

El config viaja con el dispositivo y se edita a mano, así que `parse_config()`
es la única puerta por la que entra lo que acaba en la línea de órdenes de
rclone. Aquí se sujeta que no entre un flag que lance un programa en este
equipo, ni un `resync = true` que fuerce `--resync` en cada pasada, ni un
`extra_flags` que pise `--config`, ni un nombre de remote que sea una cadena de
conexión de rclone (`nas,ssh='sh -c id'`).
"""

import sys

from _harness import Checks

from common import model
from common.model import ConfigError
from ui import flags_editor

c = Checks("el parser rechaza lo que rclone no debe recibir (common/model.py)")


def una(**pareja) -> dict:
    """Un config con una pareja `p`; las claves que se pasen pisan las de ella."""
    return {"defaults": {"remote": "nas"},
            "pair": [{"name": "p", "local": "sync-data/p", "remote_path": "R/p",
                      **pareja}]}


def _texto(f) -> str:
    """El texto del `ConfigError` que lanza `f()`; '' si no lanza ninguno."""
    try:
        f()
        return ""
    except ConfigError as e:
        return str(e)


def rechaza(data, equipo=False) -> str:
    """El texto del `ConfigError` de parsear `data`; '' si se parsea."""
    return _texto(lambda: model.parse_config(data, equipo=equipo))


# --- flags de [pair.flags] y [defaults.flags] --------------------------------
for flags in ({"resync": True}, {"workdir": "/tmp/w"}, {"filters-file": "x"},
              {"password-command": "x"}, {"metadata-mapper": "x"},
              {"rc": True}, {"rc-addr": ":5572"}, {"sftp-ssh": "sh"}):
    clave = next(iter(flags))
    c.contains(f"[pair.flags] {clave} no se admite", rechaza(una(flags=flags)), clave)
    c.contains(f"  y dice de qué pareja", rechaza(una(flags=flags)), "[p]")
c.contains("una clave con '=' se mira por lo que hay antes del '='",
           rechaza(una(flags={"sftp-ssh=sh -c id": True})), "sftp-ssh")
c.contains("[defaults.flags] config no se admite",
           rechaza({**una(), "defaults": {"remote": "nas", "flags": {"config": "x"}}}), "[defaults]")

# --- extra_flags -------------------------------------------------------------
for extra in (["--sftp-ssh", "sh -c id"], ["--sftp-ssh=sh -c id"], ["--config", "/tmp/x"],
              ["--webdav-bearer-token-command", "x"], ["--log-file=/tmp/l"], ["--Resync"]):
    c(f"extra_flags {extra[0]} no se admite", bool(rechaza(una(extra_flags=extra))), True)

# --- nombre del remote -------------------------------------------------------
for remoto in ("nas,ssh='sh -c id'", ":sftp,host=x", "nas:", "-nas", "a b "):
    c.contains(f"remote {remoto!r} no se admite", rechaza(una(remote=remoto)), "remote")
c.contains("[defaults] remote tampoco", rechaza({**una(), "defaults": {"remote": "nas,x=y"}}), "remote")
c.contains("[defaults] catalog_remote no admite opciones",
           rechaza({**una(), "defaults": {"remote": "nas", "catalog_remote": "nas,ssh='x'"}}),
           "[defaults]")
c.contains("  y dice que es catalog_remote",
           rechaza({**una(), "defaults": {"remote": "nas", "catalog_remote": "nas,ssh='x'"}}),
           "catalog_remote")
c.contains("[defaults] remote se mira aunque las parejas lleven el suyo",
           rechaza({**una(remote="nas"), "defaults": {"remote": "nas,x=y"}}), "[defaults]")
c("catalog_remote normal vale",
  rechaza({**una(), "defaults": {"remote": "nas", "catalog_remote": "cat"}}), "")

# lo de siempre sigue valiendo
cfg = model.parse_config(una(flags={"transfers": 4, "checksum": True, "max-delete": 25,
                                    "conflict-resolve": "newer"},
                             extra_flags=["--bwlimit=8M", "-v", "--exclude-if-present", ".nosync"]))
c("lo de siempre sigue valiendo", cfg.pairs[0].extra_flags[0], "--bwlimit=8M")
for remoto in ("nas", "mi nas", "nas.casa", "Nube_2", "año"):
    c(f"remote {remoto!r} vale", rechaza(una(remote=remoto)), "")

# --- el cuadro de flags dice lo mismo ----------------------------------------
c.contains("el cuadro de flags dice lo mismo", _texto(lambda: flags_editor.parse(
    'password-command = "x"')), "password-command")
c.contains("y el de argumentos extra también", _texto(lambda: flags_editor.parse_extra(
    "--sftp-ssh\nsh -c id")), "sftp-ssh")

sys.exit(c.report())
