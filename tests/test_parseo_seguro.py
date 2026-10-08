#!/usr/bin/env python3
"""Lo que el parser del config se niega a pasarle a rclone.

El config viaja con el dispositivo y se edita a mano, así que `parse_config()`
es la única puerta por la que entra lo que acaba en la línea de órdenes de
rclone. Aquí se sujeta que no entre un flag que lance un programa en este
equipo, ni un `resync = true` que fuerce `--resync` en cada pasada, ni un
`extra_flags` que pise `--config`, ni un nombre de remote que sea una cadena de
conexión de rclone (`nas,ssh='sh -c id'`), ni un `local` que salga del
dispositivo o sea la carpeta del programa o la del llavero.
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
    nombre = extra[0][2:].split("=", 1)[0]
    c.contains(f"extra_flags {extra[0]} no se admite", rechaza(una(extra_flags=extra)), nombre)

# --- el valor de un flag no puede llevar otro flag ---------------------------
# `flags_to_args` emite `--checksum --sftp-ssh=sh -c id`: un flag booleano no
# se come el argumento siguiente.
CONTRABANDO = "--sftp-ssh=sh -c id"
for flags in ({"checksum": CONTRABANDO}, {"checksum": [CONTRABANDO]}):
    forma = "lista" if isinstance(flags["checksum"], list) else "texto"
    texto = rechaza(una(flags=flags))
    c.contains(f"[pair.flags] un valor ({forma}) con --sftp-ssh no se admite", texto, "sftp-ssh")
    c.contains("  y dice de qué clave y de qué pareja", texto, "[p] [pair.flags] 'checksum'")
c.contains("[defaults.flags] un valor con --sftp-ssh tampoco",
           rechaza({**una(), "defaults": {"remote": "nas", "flags": {"checksum": CONTRABANDO}}}),
           "[defaults] [defaults.flags] 'checksum'")
c("los valores de siempre pasan (8M, -1, newer, un patrón)",
  rechaza(una(flags={"bwlimit": "8M", "max-delete": -1, "conflict-resolve": "newer",
                     "exclude-if-present": [".nosync", "-x"]})), "")

# `extra_flags` llega a rclone como `_as_tuple()` lo emita: una tabla en línea
# da sus claves, y algo que no es una lista de textos no se puede ni leer.
TABLA = {"--sftp-ssh=sh -c id": 1}
c.contains("extra_flags como tabla en línea de una pareja: se miran sus claves",
           rechaza(una(extra_flags=TABLA)), "sftp-ssh")
c.contains("  y en [defaults]",
           rechaza({**una(), "defaults": {"remote": "nas", "extra_flags": TABLA}}), "sftp-ssh")
c.contains("  y dice de qué pareja", rechaza(una(extra_flags=TABLA)), "[p]")
for malo in (5, True, 1.5):
    texto = rechaza(una(extra_flags=malo))
    c.contains(f"extra_flags = {malo!r} no es una lista de textos", texto, "extra_flags")
    c.contains("  y dice de qué pareja", texto, "[p]")
c.contains("extra_flags = 5 en [defaults] tampoco",
           rechaza({**una(), "defaults": {"remote": "nas", "extra_flags": 5}}), "[defaults]")
c("un extra_flags que es un solo texto sigue valiendo",
  rechaza(una(extra_flags="--bwlimit=8M")), "")

# --- nombre del remote -------------------------------------------------------
for remoto in ("nas,ssh='sh -c id'", ":sftp,host=x", "nas:", "-nas", "a b "):
    c.contains(f"remote {remoto!r} no se admite", rechaza(una(remote=remoto)), "remote")
c.contains("[defaults] remote tampoco", rechaza({**una(), "defaults": {"remote": "nas,x=y"}}), "remote")
c.contains("[defaults] remote vacío tampoco: sin él la pareja caería en ':ruta'",
           rechaza({**una(), "defaults": {"remote": ""}}), "[defaults]")
c.contains("  y dice que es remote", rechaza({**una(), "defaults": {"remote": ""}}), "'remote'")
c.contains("  ni aunque la pareja lleve el suyo",
           rechaza({**una(remote="nas"), "defaults": {"remote": ""}}), "[defaults]")
c.contains("[defaults] catalog_remote vacío tampoco",
           rechaza({**una(), "defaults": {"remote": "nas", "catalog_remote": ""}}),
           "catalog_remote")
c.contains("el remote que sale de la cadena de fallbacks también se mira, pareja a pareja",
           _texto(lambda: model._build_pair(
               {"name": "p", "local": "sync-data/p", "remote_path": "sftp,ssh='sh -c id':/x"},
               {"remote": ""})), "[p]")
sin_remote = {"pair": [{"name": "p", "local": "sync-data/p", "remote_path": "R/p"}]}
c("sin remote en la pareja ni en [defaults], vale el de fábrica",
  (rechaza(sin_remote), model.parse_config(sin_remote).pairs[0].remote_name),
  ("", model.DEFAULT_REMOTE))
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

c.contains("el cuadro de flags también rechaza el valor con un flag dentro",
           _texto(lambda: flags_editor.parse(f'checksum = "{CONTRABANDO}"')), "sftp-ssh")
c.contains("  en forma de lista",
           _texto(lambda: flags_editor.parse(f'checksum = ["{CONTRABANDO}"]')), "sftp-ssh")
c("  y los valores de siempre los deja",
  _texto(lambda: flags_editor.parse('bwlimit = "8M"\nmax-delete = -1')), "")

# --- cada rechazo dice qué quitar y no lo repite ------------------------------
QUITALO = "Quítalo del config."
for etiqueta, texto in (
        ("un flag reservado", rechaza(una(flags={"resync": True}))),
        ("un flag que lanza un programa", rechaza(una(flags={"password-command": "x"}))),
        ("un valor con un flag", rechaza(una(flags={"checksum": CONTRABANDO}))),
        ("un extra_flags", rechaza(una(extra_flags=["--sftp-ssh", "x"]))),
        ("un extra_flags de [defaults]",
         rechaza({**una(), "defaults": {"remote": "nas", "extra_flags": ["--config"]}})),
        ("el cuadro de argumentos extra",
         _texto(lambda: flags_editor.parse_extra("--sftp-ssh\nx")))):
    c(f"{etiqueta}: acaba diciendo que se quite", texto.endswith(QUITALO), True)
    c(f"  y no repite 'no se admite'", texto.count("no se admite"), 1)
for etiqueta, texto in (
        ("un remote", rechaza(una(remote="nas,ssh='x'"))),
        ("un remote de [defaults]", rechaza({**una(), "defaults": {"remote": "nas,x=y"}}))):
    c(f"{etiqueta}: acaba diciendo qué hacer", texto.endswith("o quita la clave del config."), True)

# --- local: dentro de la raíz, y ni el programa ni el llavero -----------------
app = model.APP_DIR.name            # «.prdrive» en un dispositivo, el nombre del checkout aquí
for local in ("../../fuera", "a/../../b", "C:/Users/x", "C:\\Users\\x", "d:x",
              app, f"{app}/keys", model.LLAVERO_LOCAL, f"{model.LLAVERO_LOCAL.upper()}/x"):
    c.contains(f"local {local!r} no vale en una unidad", rechaza(una(local=local)), "[p]")
for local, queda in ((".", "."), ("sync-data/docs", "sync-data/docs"),
                     ("/sync-data/docs", "sync-data/docs")):   # la barra de antes se tolera
    c(f"local {local!r} vale", model.parse_config(una(local=local)).pairs[0].local, queda)

# lo que cuenta es el primer tramo, tal cual y con `\` por `/`, y un tramo entero
for local in ("/../x", "./../x", "sync-data\\..\\..\\x", f"/{model.LLAVERO_LOCAL}",
              f"./{app}", f"{model.LLAVERO_LOCAL}\\x", app.upper()):
    c.contains(f"local {local!r} tampoco", rechaza(una(local=local)), "[p]")
for local in ("a..b", "..x", "x..", f"sync-data/{app}", f"sync-data/{model.LLAVERO_LOCAL}",
              f"{model.LLAVERO_LOCAL}2", f"{app}-docs", "sync-data/d:x"):
    c(f"local {local!r} vale: ni es un '..' ni empieza por esa carpeta",
      rechaza(una(local=local)), "")

# cada motivo, con la clave y qué hacer
fuera = rechaza(una(local="../../fuera"))
c.contains("el motivo de salir dice la clave y el valor", fuera, "local = \"../../fuera\"")
c.contains("  y que sale del dispositivo", fuera, "sale del dispositivo")
c.contains("  y qué poner", fuera, "Pon una carpeta de dentro")
unidad_c = rechaza(una(local="C:/Users/x"))
c.contains("una letra de unidad dice lo mismo", unidad_c, "sale del dispositivo")
c.contains("la carpeta del programa dice quién es",
           rechaza(una(local=f"{app}/keys")), "es la carpeta del programa, con su clave")
c.contains("  y qué poner", rechaza(una(local=app)), "Pon otra carpeta")
c.contains("la del llavero dice quién es",
           rechaza(una(local=model.LLAVERO_LOCAL)),
           "es la del llavero, que tiene su propia pareja")
c.contains("  y qué poner", rechaza(una(local=model.LLAVERO_LOCAL)), "Pon otra carpeta")

# en una raíz del equipo vale lo mismo, y encima lo suyo con sus propias palabras
for local in (".", "", "../fuera", "/etc", "C:\\Users", "\\\\srv\\x"):
    c(f"en un equipo, local = {local!r}: el motivo es el de problema_local_equipo",
      model.problema_local(local, equipo=True), model.problema_local_equipo(local))
    c(f"  y el parser lo dice igual, con su pareja",
      rechaza(una(local=local), equipo=True),
      "[p] " + model.problema_local_equipo(local))
for local in (app, f"{app}/keys", model.LLAVERO_LOCAL):
    c.contains(f"en un equipo, local = {local!r} tampoco",
               rechaza(una(local=local), equipo=True), "[p]")
c("en un equipo, una carpeta de dentro vale",
  rechaza(una(local="Documentos/Obsidian"), equipo=True), "")
c("en una unidad, '.' no pasa por lo del equipo", model.problema_local("."), None)
c("problema_local: None si vale", model.problema_local("sync-data/docs"), None)

# la carpeta del programa puede venir de fuera: el agente corre en la suya, no en la de la unidad
c("carpeta_programa: por defecto, la del programa que corre",
  model.problema_local(app) is not None, True)
c.contains("  con otra, es esa la que no vale",
           model.problema_local(".prdrive/keys", carpeta_programa=".prdrive") or "",
           "es la carpeta del programa, con su clave")
c("  y sin distinguir mayúsculas",
  model.problema_local(".PRDRIVE", carpeta_programa=".prdrive") is not None, True)
c("  y la del programa que corre deja de contar",
  model.problema_local(app, carpeta_programa=".prdrive"), None)
c.contains("  comprobar_seguridad() se la pasa",
           _texto(lambda: model.comprobar_seguridad(
               una(local=".prdrive/keys"), carpeta_programa=".prdrive")), "[p] local")
c("  y la del llavero vale igual con cualquiera",
  model.problema_local(model.LLAVERO_LOCAL, carpeta_programa="otra") is not None, True)

# la puerta es comprobar_seguridad(), la del agente también, y no decide más
c.contains("comprobar_seguridad() mira el local de cada pareja con nombre",
           _texto(lambda: model.comprobar_seguridad(una(local="../x"))), "[p] local")
c.contains("  y con equipo, el de la raíz del equipo",
           _texto(lambda: model.comprobar_seguridad(una(local="."), equipo=True)), "raíz entera")
c("  pero '.' en una unidad lo deja", _texto(lambda: model.comprobar_seguridad(una(local="."))), "")
c("un local que no es un texto no es asunto suyo",
  (_texto(lambda: model.comprobar_seguridad(una(local=5))),
   _texto(lambda: model.comprobar_seguridad(una(local=["../x"]))),
   _texto(lambda: model.comprobar_seguridad({"pair": [{"name": "p"}, {"local": "../x"}, 7]}))),
  ("", "", ""))
sin_local = {"defaults": {"remote": "nas"}, "pair": [{"name": "p", "remote_path": "R/p"}]}
c.contains("sin local, lo dice _build_pair como siempre", rechaza(sin_local), "falta 'local'")

sys.exit(c.report())
