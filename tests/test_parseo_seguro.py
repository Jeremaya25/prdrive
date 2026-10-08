#!/usr/bin/env python3
"""Lo que el parser del config se niega a pasarle a rclone.

El config viaja con el dispositivo y se edita a mano, así que `parse_config()`
es la única puerta por la que entra lo que acaba en la línea de órdenes de
rclone. Aquí se sujeta que no entre un flag que lance un programa en este
equipo, ni un `resync = true` que fuerce `--resync` en cada pasada, ni un
`extra_flags` que pise `--config`, ni un nombre de remote que sea una cadena de
conexión de rclone (`nas,ssh='sh -c id'`), ni un `local` que salga del
dispositivo o sea la carpeta del programa o la del llavero. Y que una pareja de
la raíz entera deje fuera la carpeta del programa (`REGLA_SIN_PROGRAMA`), con su
clave, y avise si alguna vez la subió.
"""

import hashlib
import sys
from dataclasses import replace
from pathlib import Path

from _harness import Checks, sandbox

import sync
from common import bisync, model
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

# --- include/exclude: una línea es una regla del fichero de filtros -----------
# Con `exclude = ["x\n!\n+ **"]` el fichero llevaría `- x`, `!` y `+ **`, y un `!`
# suelto borra las reglas de antes (la de la carpeta del programa, la del llavero).
for clave in ("include", "exclude"):
    for valor in (["x\n!\n+ **"], ["bien", "a\rb"], "x\ny", {"x\n!": 1}):
        texto = rechaza(una(**{clave: valor}))
        c.contains(f"{clave} = {valor!r} no se admite", texto, f"{clave} ")
        c.contains("  y dice de qué pareja", texto, "[p]")
        c.contains("  y qué hacer", texto, "Quita el salto de línea")
    c.contains(f"{clave} de [defaults] tampoco",
               rechaza({**una(), "defaults": {"remote": "nas", clave: ["x\n!"]}}), "[defaults]")
    c(f"{clave} de siempre vale",
      rechaza(una(**{clave: ["*.tmp", "Docs/**", "con espacios/*.md"]})), "")
raiz_normal = model.parse_config(una(local=".", mode="bisync", exclude=["*.tmp"])).pairs[0]
c("un patrón sin saltos de línea escribe una línea por regla",
  bisync.filters_content(raiz_normal).splitlines()[2:4], [model.REGLA_SIN_PROGRAMA, "- *.tmp"])

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

# rclone lee `C:ruta` como la unidad C: de Windows, no como el remote «C»
for remoto in ("C", "n", "Z"):
    texto = rechaza(una(remote=remoto))
    c.contains(f"remote {remoto!r}, una sola letra, no se admite", texto, "'remote' no vale")
    c.contains("  y dice que rclone lo lee como una unidad de Windows", texto, "unidad de Windows")
    c.contains("  y qué hacer", texto, "Renombra el remote")
    c.contains("  y de qué pareja", texto, "[p]")
c.contains("[defaults] remote de una letra tampoco",
           rechaza({**una(), "defaults": {"remote": "n"}}), "[defaults]")
c.contains("  ni el catalog_remote",
           rechaza({**una(), "defaults": {"remote": "nas", "catalog_remote": "x"}}),
           "catalog_remote")
for remoto in ("nas", "b2", "c1", "ab", "_", "ñ", "1"):
    c(f"remote {remoto!r} vale (no es una letra de unidad)", rechaza(una(remote=remoto)), "")
c("problema_remote: None si vale, y el motivo si es una letra",
  (model.problema_remote("nas"), model.problema_remote("C") is not None), (None, True))

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

# --- y el aviso de la ventana lleva el mismo título en las dos cajas ---------
def _titulo(f) -> str:
    """El título del aviso (`titulo_error`) del `ConfigError` que lanza `f()`."""
    try:
        f()
    except ConfigError as e:
        return flags_editor.titulo_error(e)
    return ""


c("un flag que lanza un programa, en el cuadro de flags: título de flag no admitido",
  _titulo(lambda: flags_editor.parse('password-command = "x"')), flags_editor.TITULO_RESERVADO)
c("  en el de argumentos extra, igual",
  _titulo(lambda: flags_editor.parse_extra("--sftp-ssh\nx")), flags_editor.TITULO_RESERVADO)
c("  y un reservado del programa en el de extra también",
  _titulo(lambda: flags_editor.parse_extra("--config\n/tmp/x")), flags_editor.TITULO_RESERVADO)
c("un valor con un flag dentro no es un flag reservado: título genérico",
  _titulo(lambda: flags_editor.parse(f'checksum = "{CONTRABANDO}"')), flags_editor.TITULO_NO_VALE)
c("  ni lo es un texto que no es TOML",
  _titulo(lambda: flags_editor.parse("esto no es toml")), flags_editor.TITULO_NO_VALE)

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
              f"{model.LLAVERO_LOCAL}2", f"{app}-docs", "sync-data/notas.v2", "a. b", ".a"):
    c(f"local {local!r} vale: ni es un '..' ni empieza por esa carpeta",
      rechaza(una(local=local)), "")

# Windows recorta los puntos y los espacios del final de cada tramo y entiende
# `nombre:flujo` como un flujo de datos de `nombre`: `.prdrive.`, `.prdrive ` y
# `.prdrive::$INDEX_ALLOCATION` son la carpeta del programa, y `...` o `. .`
# acaban en otra carpeta. Se rechazan en el texto, y `sync.py` mira además
# dónde cae de verdad (`problema_contencion()`).
for local in (f"{app}.", f"{app} ", f"{app.upper()} /x", f"{app}. .", f"{app}::$INDEX_ALLOCATION",
              f"{model.LLAVERO_LOCAL}.", f"{model.LLAVERO_LOCAL} /x", f"./{model.LLAVERO_LOCAL}..",
              f"{model.LLAVERO_LOCAL.upper()}. /x"):
    c.contains(f"local {local!r} es la carpeta del programa o la del llavero con otro nombre",
               rechaza(una(local=local)), "[p]")
for local, parte in ((f"{app}.", "carpeta del programa"), (f"{app} /x", "carpeta del programa"),
                     (f"{model.LLAVERO_LOCAL}.", "la del llavero")):
    c.contains(f"  y {local!r} dice quién es", rechaza(una(local=local)), parte)
for local in ("...", ".. ", ". .", "a/.. /b", "a/.../b", "a/ /b", "a\\...\\b", "x/. ."):
    texto = rechaza(una(local=local))
    c.contains(f"local {local!r}: un tramo de solo puntos y espacios no vale", texto,
               "solo puntos y espacios")
    c.contains("  y qué poner", texto, "Pon una carpeta de dentro")
for local in ("docs:stream", "a/b:c", f"{app}::$INDEX_ALLOCATION", "sync-data/d:x", "x/C:/y",
              "docs:$DATA"):
    texto = rechaza(una(local=local))
    c.contains(f"local {local!r}: un ':' en un tramo no vale", texto, "lleva ':'")
    c.contains("  y qué hacer", texto, "Quita el ':'")
c("  la letra de unidad del principio sigue con su motivo",
  "sale del dispositivo" in rechaza(una(local="d:x")), True)
for local in ("sync-data/notas.v2", "a..b", f"{model.LLAVERO_LOCAL}2", "x/. y/z", "Mis fotos.2024"):
    c(f"local {local!r} sigue valiendo", rechaza(una(local=local)), "")
c("en una raíz de equipo, un tramo con puntos o espacios de más también cuenta",
  all(rechaza(una(local=local), equipo=True) != ""
      for local in (f"{app}.", "docs/...", "docs:stream")), True)
c("  y lo de siempre sigue valiendo", rechaza(una(local="Documentos/Obsidian"), equipo=True), "")
c("  con las palabras de problema_local_equipo si es la raíz",
  rechaza(una(local=".. "), equipo=True) != "", True)

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
c("  recortados como Windows: '.prdrive.' y '.PRDRIVE /x' tampoco",
  (model.problema_local(".prdrive.", carpeta_programa=".prdrive") is not None,
   model.problema_local(".PRDRIVE /x", carpeta_programa=".prdrive") is not None,
   model.problema_local(".prdrive::$INDEX_ALLOCATION", carpeta_programa=".prdrive") is not None,
   model.problema_local(".prdrive2", carpeta_programa=".prdrive")), (True, True, True, None))
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
# `_build_pair()` lee el `local` con `str()`: uno que no es un texto (una lista
# con un `..` dentro) llegaría a `local_abs` sin que nadie lo mirase.
for local in (5, True, ["a/../../../etc"], {"a/../../x": 1}):
    texto = _texto(lambda: model.comprobar_seguridad(una(local=local)))
    c.contains(f"un local {local!r} que no es un texto se rechaza", texto, "'local' tiene que ser un texto")
    c.contains("  con su pareja", texto, "[p]")
    c.contains("  y qué hacer", texto, "entre comillas")
    c.contains(f"  y el parser lo rechaza igual", rechaza(una(local=local)), "'local' tiene que ser un texto")
c("lo que no es una pareja con nombre sigue sin ser asunto suyo",
  _texto(lambda: model.comprobar_seguridad({"pair": [{"name": "p"}, {"local": ["../x"]}, 7]})), "")
sin_local = {"defaults": {"remote": "nas"}, "pair": [{"name": "p", "remote_path": "R/p"}]}
c.contains("sin local, lo dice _build_pair como siempre", rechaza(sin_local), "falta 'local'")

# --- la raíz entera no lleva la carpeta del programa -------------------------
# Sin esta regla una pareja con `local = "."` subiría `.prdrive/` (su clave y
# su rclone.conf) al remoto, y un `down-mirror` de la raíz la borraría.
raiz = model.parse_config(una(local=".", mode="bisync")).pairs[0]
c("la raíz deja fuera el programa", raiz.reglas, (model.REGLA_SIN_PROGRAMA,))
c("  y es la carpeta de este programa", model.REGLA_SIN_PROGRAMA, f"- /{model.APP_DIR.name}/**")
c("  primera regla del fichero de filtros",
  bisync.filters_content(raiz).splitlines()[2], model.REGLA_SIN_PROGRAMA)
c("  y con versiones, detrás de .prversions",
  bisync.filters_content(replace(raiz, versions=True)).splitlines()[2:4],
  [f"- {model.VERSIONS_DIR}/**", model.REGLA_SIN_PROGRAMA])
espejo = model.parse_config(una(local=".", mode="up-mirror")).pairs[0]
c("fuera de bisync va como --exclude", sync.filter_args(espejo, None)[:2],
  ["--exclude", f"/{model.APP_DIR.name}/**"])
c("una pareja de carpeta no lleva reglas", model.parse_config(una()).pairs[0].reglas, ())
con_llavero = model.parse_config(
    {**una(local="."), "keychain": {"base": "personal.kdbx"}}).pairs
c("con [keychain], el programa va antes que el llavero",
  con_llavero[0].reglas, (model.REGLA_SIN_PROGRAMA, model.REGLA_SIN_LLAVERO))
c("  y la pareja del llavero no recibe la del programa",
  con_llavero[1].reglas, model.LLAVERO_REGLAS)
c("la regla de la raíz no la toca el TOML: un include no la adelanta",
  bisync.filters_content(model.parse_config(
      una(local=".", mode="bisync", include=["**/*.md"])).pairs[0]).splitlines()[2:4],
  [model.REGLA_SIN_PROGRAMA, "+ **/*.md"])
with sandbox():          # el fichero de filtros de antes, con su md5 de antes
    viejo = model.FILTERS_DIR / "p.txt"
    viejo.write_text(bisync.FILTERS_HEADER + "\n")
    Path(str(viejo) + ".md5").write_text(hashlib.md5(viejo.read_bytes()).hexdigest())
    c("una pareja raíz de antes pide un --resync",
      bisync.filters_state(bisync.filters_file_for(raiz)).status, "changed")
    c("sin listado, no se sabe que subiera el programa", bisync.programa_en_listado(raiz), False)
    # un listado path2 con la carpeta del programa dentro
    lst = raiz.workdir / (bisync.expected_prefix(raiz) + bisync.PATH2_SUFFIX)
    lst.parent.mkdir(parents=True)
    lst.write_text(f'- 10 - - 2026-01-01T00:00:00.000000000+0000 "{model.APP_DIR.name}/rclone.conf"\n')
    c("se ve que subió el programa", bisync.programa_en_listado(raiz), True)
    lst.write_text('- 10 - - 2026-01-01T00:00:00.000000000+0000 "notas/uno.md"\n'
                   f'- 10 - - 2026-01-01T00:00:00.000000000+0000 "x{model.APP_DIR.name}/a"\n')
    c("  y que no, si solo hay otras carpetas (ni una que acabe igual)",
      bisync.programa_en_listado(raiz), False)
    lst.write_bytes(b"\xff\xfe\x00 no es un listado")
    c("  un listado ilegible no rompe nada", bisync.programa_en_listado(raiz), False)

sys.exit(c.report())
