#!/usr/bin/env python3
"""
El nombre de los listados de bisync ya no depende de la máquina.

bisync guarda su baseline en ficheros cuyo nombre deduce de los dos extremos. Con
el lado local como ruta absoluta, ese nombre lleva dentro el punto de montaje
(`F__sync-data_notas..nas_datos_notas`), así que el mismo dispositivo en otra
letra de unidad —o en un Linux— ya no encontraba su baseline. Esa herida la
tapaba un renombrado automático de los listados, que era peligroso por
definición: renombrar es decirle a bisync que el listado del destino ANTERIOR
describe el NUEVO.

La cura es `device_remote`: el lado local va como un remote 'combine' propio y el
prefijo deja de saber dónde está montado nada. Esto comprueba las dos mitades —el
prefijo y las variables de entorno que definen ese remote— y que la venda ya no
está.
"""

import sys
from pathlib import Path

from _harness import Checks, sandbox

from common import bisync, model

c = Checks("bisync: prefijos independientes de la máquina")

PAREJAS = [{"name": "notas", "local": "sync-data/notas", "remote_path": "/datos/notas",
            "mode": "bisync"},
           {"name": "fotos", "local": "media/fotos", "remote_path": "/datos/fotos",
            "mode": "bisync"}]


def config(device_remote=None, raiz=None):
    """Una config con (o sin) device_remote, montada en la raíz que se diga."""
    defaults = {"remote": "nas"}
    if device_remote:
        defaults["device_remote"] = device_remote
    if raiz is not None:
        model.DEVICE_ROOT = Path(raiz)
    return model.parse_config({"defaults": defaults, "pair": PAREJAS})


with sandbox() as root:
    original = model.DEVICE_ROOT

    # --- sin device_remote: el punto de montaje está DENTRO del nombre --------
    suelto = config(raiz=root).pairs[0]
    prefijo_suelto = bisync.expected_prefix(suelto)
    # `resolve()`: en Windows la ruta del temporal llega en formato 8.3
    # (PCERQU~1) y el modelo la resuelve al nombre largo.
    marca = bisync.canonical_path(str(Path(root).resolve()))
    c("sin device_remote el prefijo lleva el punto de montaje",
      marca in prefijo_suelto, True)

    # --- con device_remote: el mismo nombre en cualquier equipo ---------------
    pareja = config("disp", raiz=root).pairs[0]
    prefijo = bisync.expected_prefix(pareja)
    c("con device_remote el prefijo sale del nombre del remote",
      prefijo, "disp_sync-data_notas..nas__datos_notas")
    c("y no lleva dentro el punto de montaje", marca in prefijo, False)

    # La prueba de verdad: el MISMO dispositivo montado en otro sitio. Es lo que
    # pasa al llevárselo a otro equipo, y lo que rompía antes.
    otra_raiz = root / "otro-punto-de-montaje"
    otra_raiz.mkdir()
    en_otro_sitio = config("disp", raiz=otra_raiz).pairs[0]
    c("el prefijo no cambia al montar el dispositivo en otro sitio",
      bisync.expected_prefix(en_otro_sitio), prefijo)
    c("sin device_remote sí cambiaba",
      bisync.expected_prefix(config(raiz=otra_raiz).pairs[0]) == prefijo_suelto, False)

    # --- las variables que definen el remote 'combine' ------------------------
    model.DEVICE_ROOT = root
    entorno = config("disp", raiz=root).pen_environment()
    c("el remote del dispositivo es un 'combine'",
      entorno["RCLONE_CONFIG_DISP_TYPE"], "combine")
    upstreams = entorno["RCLONE_CONFIG_DISP_UPSTREAMS"]
    # Un upstream por primer tramo de ruta local, de TODAS las parejas: el
    # remote tiene que ser idéntico se ejecute lo que se ejecute.
    c("un upstream por cada carpeta de primer nivel",
      upstreams, f'media="{(root / "media").resolve()}" '
                 f'sync-data="{(root / "sync-data").resolve()}"')
    c("sin device_remote no hay entorno que poner", config(raiz=root).pen_environment(), {})

    model.DEVICE_ROOT = original

# --- la venda, retirada ----------------------------------------------------------
# No es una comprobación de aspecto: renombrar los listados al prefijo nuevo es
# la operación que puede provocar borrados masivos (ver el docstring de
# `bisync.shelve_baseline`). Si alguien la reintroduce, que sea leyendo esto.
for nombre in ("normalize_prefix", "rename_prefix", "heal_listings"):
    c(f"bisync ya no renombra listados: sin {nombre}()", hasattr(bisync, nombre), False)

sys.exit(c.report())
