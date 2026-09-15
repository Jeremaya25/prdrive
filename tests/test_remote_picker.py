#!/usr/bin/env python3
"""
El explorador del remoto: leer `rclone lsd`, navegar y crear una carpeta.

Antes, `remote_path` se tecleaba de memoria y el error aparecía en la primera
sincronización —o no aparecía, y la pareja acababa apuntando a una carpeta con
una errata dentro—. Lo que se comprueba aquí es lo que hace que eso deje de
pasar: que la salida de rclone se lee bien (incluidos los nombres con espacios),
que navegar no se sale nunca de la raíz, y que crear una carpeta no puede colar
una ruta entera disfrazada de nombre.

`catalog.run` se sustituye entero: ningún test toca la red.
"""

import subprocess
import sys

from _harness import Checks

from common import catalog, model
from common.model import ConfigError
from ui import pair_editor, remote_picker

c = Checks("explorador del remoto")

# Salida real de `rclone lsd`: tamaño, fecha, hora, número de entradas y nombre.
LSD = """\
          -1 2026-01-01 12:00:00        -1 documentos
          -1 2026-02-03 09:30:11        -1 fotos de verano
          -1 2026-02-03 09:30:11        -1 .oculta
"""

# --- leer lo que dice rclone ---------------------------------------------------
c("se leen los nombres de carpeta", remote_picker.parse_lsd(LSD),
  [".oculta", "documentos", "fotos de verano"])
c("un nombre con espacios llega entero",
  "fotos de verano" in remote_picker.parse_lsd(LSD), True)
c("una salida vacía es una carpeta vacía, no un error",
  remote_picker.parse_lsd(""), [])
c("una línea que no cuadra se ignora",
  remote_picker.parse_lsd("esto no es una línea de lsd\n"), [])

# --- navegar -------------------------------------------------------------------
c("las rutas se normalizan como las escribe el proyecto",
  [remote_picker.normalizar(x) for x in ("datos/notas/", "/datos//notas", "", "/")],
  ["/datos/notas", "/datos/notas", "/", "/"])
c("subir quita el último tramo", remote_picker.subir("/datos/notas"), "/datos")
c("y desde la raíz no se sube más", remote_picker.subir("/"), "/")
c("entrar añade uno", remote_picker.entrar("/datos", "notas"), "/datos/notas")
c("el explorador abre en la carpeta que contiene a la pareja",
  remote_picker.carpeta_de("/datos/notas"), "/datos")
c("y en la raíz si no hay nada escrito", remote_picker.carpeta_de(""), "/")
c("el endpoint es el de siempre", remote_picker.endpoint("nas", "/datos"), "nas:/datos")

# --- contra qué remote se navega ------------------------------------------------
RAW = {"defaults": {"remote": "nas"}}
c("sin remote propio, el de [defaults]", remote_picker.remote_de(RAW), "nas")
c("con uno propio, el suyo", remote_picker.remote_de(RAW, " otro "), "otro")
c("y sin defaults, el de fábrica", remote_picker.remote_de({}), model.DEFAULT_REMOTE)

# --- las órdenes que se lanzan ---------------------------------------------------
ordenes: list[list[str]] = []


def responder(rc=0, stdout="", stderr=""):
    def _run(args):
        ordenes.append(list(args))
        return subprocess.CompletedProcess(args, rc, stdout=stdout, stderr=stderr)
    return _run


real_run = catalog.run
try:
    catalog.run = responder(stdout=LSD)
    c("listar es un lsd de esa carpeta", remote_picker.listar("nas", "/datos"),
      [".oculta", "documentos", "fotos de verano"])
    c("con el endpoint completo", ordenes[-1], ["lsd", "nas:/datos"])

    catalog.run = responder(rc=3, stderr="directory not found")
    try:
        remote_picker.listar("nas", "/no-existe")
        c("una carpeta que no está se cuenta", "no lanzó", "ConfigError")
    except ConfigError as e:
        c("una carpeta que no está se cuenta", "directory not found" in str(e), True)

    def reventar(args):
        raise OSError("no hay rclone")
    catalog.run = reventar
    try:
        remote_picker.listar("nas", "/datos")
        c("y un rclone que no arranca también", "no lanzó", "ConfigError")
    except ConfigError:
        c("y un rclone que no arranca también", True, True)

    # --- crear ------------------------------------------------------------------
    ordenes.clear()
    catalog.run = responder()
    c("crear devuelve la ruta nueva",
      remote_picker.crear("nas", "/datos", " notas "), "/datos/notas")
    c("y es un mkdir, que no toca lo que ya hay",
      ordenes[-1], ["mkdir", "nas:/datos/notas"])

    ordenes.clear()
    for malo in ("sub/carpeta", "..", ".", "  ", "otra\\cosa"):
        try:
            remote_picker.crear("nas", "/datos", malo)
            c(f"'{malo}' no puede ser el nombre de una carpeta", "no lanzó", "ConfigError")
        except ConfigError:
            c(f"'{malo}' no puede ser el nombre de una carpeta", True, True)
    c("y ninguno ha llegado a rclone", ordenes, [])
finally:
    catalog.run = real_run

# --- la otra mitad: la carpeta local ---------------------------------------------
# `local` es siempre relativa a la raíz del dispositivo, que es lo que hace que la
# misma pareja valga en cualquier equipo y con cualquier letra de unidad.
raiz = model.DEVICE_ROOT.resolve()
c("una carpeta del dispositivo se guarda relativa",
  pair_editor.ruta_local_relativa(raiz / "sync-data" / "notas"), "sync-data/notas")
c("la raíz del dispositivo es '.'", pair_editor.ruta_local_relativa(raiz), ".")
try:
    pair_editor.ruta_local_relativa(raiz.anchor)
    c("una carpeta de fuera del dispositivo se rechaza", "no lanzó", "ConfigError")
except ConfigError as e:
    c("una carpeta de fuera del dispositivo se rechaza",
      "dentro del dispositivo" in str(e), True)

sys.exit(c.report())
