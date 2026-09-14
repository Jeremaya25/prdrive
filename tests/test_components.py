#!/usr/bin/env python3
"""
Qué lleva el dispositivo de fuera, y si sigue siendo lo fijado
(common/components.py).

Aquí no se descarga nada ni se sustituye nada: eso es `install/components.py` y
su propio test. Lo que se comprueba es la mitad que corre DENTRO del
dispositivo, que es la que pinta la ventana en su primer pintado: que leer
sellos no lance nunca, que un dispositivo sin sello de rclone se lea como «no
consta» —y no como «al día», que sería la mentira cómoda—, y que una plataforma
que el dispositivo no lleva no cuente como anticuada, porque no lo está: está
sin instalar.

Y una comprobación que no es de comportamiento sino de deriva: que las rutas que
usa el instalador para ESCRIBIR sean las mismas que usa el dispositivo para
LEER. El día que se separen, el instalador dejaría los componentes en un sitio y
la ventana los buscaría en otro.
"""

import sys
from pathlib import Path

from _harness import Checks, tmpdir

from common import components, pins
from install import platforms, runtime_bin

c = Checks("componentes del dispositivo (common/components.py)")

WIN = pins.plataforma("windows-x64")
LARM = pins.plataforma("linux-arm64")


def poner_rclone(app: Path, plat, version=None) -> None:
    """Un rclone de mentira, con o sin sello."""
    binario = components.rclone_path(app, plat)
    binario.parent.mkdir(parents=True, exist_ok=True)
    binario.write_bytes(b"soy rclone")
    if version is not None:
        components.rclone_stamp_path(app, plat).write_text(
            components.rclone_stamp_text(plat, version), encoding="utf-8")


def poner_runtime(app: Path, plat, version=None, release=None,
                  interprete=True) -> None:
    """Un runtime de mentira. Sin intérprete no cuenta, aunque tenga sello."""
    d = components.runtime_dir(app, plat)
    d.mkdir(parents=True, exist_ok=True)
    if interprete:
        (d / plat.interprete).parent.mkdir(parents=True, exist_ok=True)
        (d / plat.interprete).write_bytes(b"py")
    (d / components.RUNTIME_STAMP).write_text(
        f"# cabecera\npython = {version or pins.PYTHON_VERSION}\n"
        f"release = {release or pins.PYTHON_RELEASE}\n"
        f"triple = {plat.triple}\nsha256 = abc\n", encoding="utf-8")


# --- leer un sello: tolerante, como store.read_json --------------------------
sello = components.leer_sello("# comentario\nrclone = v1.75.1\n\nbasura\n"
                              "plataforma = windows-x64\n")
c("se leen las claves", sello.get("rclone"), "v1.75.1")
c("y las demás", sello.get("plataforma"), "windows-x64")
c("una línea sin '=' se ignora en vez de reventar", "basura" in sello, False)
c("un sello vacío es un diccionario vacío", components.leer_sello(""), {})

# --- un dispositivo que no existe no lanza ----------------------------------
c("un dispositivo inexistente no tiene nada pendiente",
  components.pendientes(Path("/no/existe/.prdrive")), [])

# --- rclone ------------------------------------------------------------------
app = tmpdir("prdrive-comp-") / ".prdrive"
c("sin rclone no hay nada anticuado: hay algo sin instalar",
  components.pendientes(app), [])

poner_rclone(app, WIN, pins.RCLONE_VERSION)
c("un rclone de la versión fijada está al día", components.pendientes(app), [])

poner_rclone(app, WIN, "v1.60.0")
pend = components.pendientes(app)
c("uno de otra versión sale pendiente", len(pend), 1)
c("con su plataforma", pend[0].plataforma, WIN)
c("y qué componente es", pend[0].que, components.RCLONE)
c("se dice qué lleva", pend[0].lleva, "v1.60.0")
c("y qué toca", pend[0].deberia, pins.RCLONE_VERSION)
c.contains("y se sabe contar", pend[0].describe(), "rclone de Windows x64")

# El caso que de verdad importa: un dispositivo anterior a que existieran los
# sellos. No se puede ejecutar el rclone de otra plataforma para preguntárselo,
# así que la única respuesta honesta es «no consta», y no consta es pendiente.
poner_rclone(app, WIN, version=None)
components.rclone_stamp_path(app, WIN).unlink(missing_ok=True)
pend = components.pendientes(app)
c("sin sello, no consta", [p.lleva for p in pend], [components.DESCONOCIDA])

# --- el Python ---------------------------------------------------------------
app2 = tmpdir("prdrive-comp2-") / ".prdrive"
poner_runtime(app2, WIN)
c("un runtime de la release fijada está al día", components.pendientes(app2), [])

poner_runtime(app2, WIN, version="3.13.1", release="20250101")
pend = components.pendientes(app2)
c("otra release sale pendiente", len(pend), 1)
c("y es el Python", pend[0].que, components.PYTHON)
c.contains("diciendo la release que lleva", pend[0].lleva, "20250101")
c.contains("y la que toca", pend[0].deberia, pins.PYTHON_RELEASE)

# Sin intérprete no hay runtime, aunque quede el sello: una extracción a medias
# no es un componente instalado, es basura, y la cura es reinstalar la
# plataforma, no «actualizarla».
app3 = tmpdir("prdrive-comp3-") / ".prdrive"
poner_runtime(app3, LARM, version="3.13.1", interprete=False)
c("un runtime sin intérprete no cuenta", components.pendientes(app3), [])

# --- el resumen que pinta la ventana ----------------------------------------
app4 = tmpdir("prdrive-comp4-") / ".prdrive"
poner_rclone(app4, WIN, "v1.60.0")
poner_runtime(app4, WIN, release="20250101")
pend = components.pendientes(app4)
c("se listan los dos componentes de la misma plataforma", len(pend), 2)
c("rclone primero, que es el que sincroniza",
  [p.que for p in pend], [components.RCLONE, components.PYTHON])
c("el resumen lleva una línea por componente",
  len(components.resumen(pend).splitlines()), 2)

# --- deriva: el instalador escribe donde el dispositivo lee -------------------
raiz = tmpdir("prdrive-deriva-")
app_r = raiz / ".prdrive"
c("la carpeta del runtime es la misma para los dos",
  platforms.runtime_dir(raiz, WIN), components.runtime_dir(app_r, WIN))
c("y el binario de rclone también",
  platforms.rclone_path(raiz, WIN), components.rclone_path(app_r, WIN))
poner_runtime(app_r, WIN)
c("y el sello se lee igual desde los dos lados",
  platforms.runtime_stamp(raiz, WIN), components.runtime_stamp(app_r, WIN))
c("el nombre del sello del runtime no se ha bifurcado",
  runtime_bin.STAMP, components.RUNTIME_STAMP)
c("ni el de su carpeta", runtime_bin.RUNTIME_SUBDIR, components.RUNTIME_SUBDIR)

sys.exit(c.report())
