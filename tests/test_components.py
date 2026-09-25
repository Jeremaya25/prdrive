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

# --- un sello ilegible no lanza -----------------------------------------------
#
# `read_text(encoding="utf-8")` sobre un fichero a medias no falla con un
# OSError, falla con un UnicodeDecodeError (que ES un ValueError) — el caso
# real que describe el docstring de `leer_sello()`: el dispositivo se extrajo a
# mitad de una escritura. El contrato de este módulo es que nunca lanza, así
# que tiene que leerse igual que si no hubiera sello: «no consta», pendiente.
app5 = tmpdir("prdrive-comp5-") / ".prdrive"
poner_rclone(app5, WIN)
components.rclone_stamp_path(app5, WIN).write_bytes(b"rclone = v1.7\xff5.1\n")
pend = components.pendientes(app5)
c("un sello de rclone con bytes inválidos no lanza, sale pendiente",
  [p.lleva for p in pend], [components.DESCONOCIDA])

app6 = tmpdir("prdrive-comp6-") / ".prdrive"
poner_runtime(app6, WIN)
(components.runtime_dir(app6, WIN) / components.RUNTIME_STAMP).write_bytes(
    b"python = 3.1\xff3.1\n")
c("un sello de runtime con bytes inválidos no lanza, sale como no instalado",
  components.pendientes(app6), [])

# --- las claves del sello del runtime son las que escribe el productor --------
#
# Con fixtures escritas a mano, renombrar una clave en un lado y no en el otro
# no lo detecta ningún test: cada dispositivo saldría con su Python
# permanentemente pendiente. Esto usa el texto REAL de `runtime_bin.stamp_text`
# (ya importado arriba), no una fixture reescrita a mano como las de más arriba.
app7 = tmpdir("prdrive-comp7-") / ".prdrive"
d7 = components.runtime_dir(app7, WIN)
(d7 / WIN.interprete).parent.mkdir(parents=True, exist_ok=True)
(d7 / WIN.interprete).write_bytes(b"py")
(d7 / components.RUNTIME_STAMP).write_text(
    runtime_bin.stamp_text(WIN, "x"), encoding="utf-8")
c("el sello real del productor se lee como al día",
  components.pendientes(app7), [])

# --- el VeraCrypt de viaje (#50) ------------------------------------------------
#
# Vive en la raíz FÍSICA, junto al .hc, y su sello va dentro de su carpeta. Se
# le pasa la raíz física a `pendientes()`; sin pasarla se busca por el vestíbulo,
# y un dispositivo sin fichero de control (estos de mentira) no vive en ninguno.
from _harness import falso_portatil  # noqa: E402
from common import vestibulo  # noqa: E402

vacia = tmpdir("prdrive-comp-vc-") / ".prdrive"
fisica = tmpdir("prdrive-comp-fisica-")
c("sin carpeta VeraCrypt no lleva: nada pendiente",
  components.pendientes(vacia, fisica), [])
c("un dispositivo que no vive en un contenedor no mira ninguna raíz física",
  (components.raiz_fisica(vacia), components.pendientes(vacia)), (None, []))


def poner_veracrypt(raiz, version=None, sello=True):
    """La carpeta de la caché de mentira, copiada como la dejaría el traveler."""
    import shutil
    destino = components.veracrypt_dir(raiz)
    shutil.rmtree(destino, ignore_errors=True)
    shutil.copytree(falso_portatil(version), destino)
    if not sello:
        components.veracrypt_stamp_path(raiz).unlink()


poner_veracrypt(fisica)
c("el de la versión fijada está al día", components.pendientes(vacia, fisica), [])

poner_veracrypt(fisica, "1.26.7")
pend = components.pendientes(vacia, fisica)
c("uno con sello de otra versión sale pendiente",
  [(p.que, p.lleva, p.deberia, p.asistente) for p in pend],
  [(components.VERACRYPT, "1.26.7", pins.VERACRYPT_VERSION, False)])
c("sin plataforma: lleva las dos arquitecturas", pend[0].plataforma, None)
c("y dice dónde está su carpeta", pend[0].ruta, fisica / vestibulo.TRAVELER)
c.contains("y se sabe contar", pend[0].describe(), "VeraCrypt de la unidad: lleva 1.26.7")
c("se puede poner al día desde la ventana", components.actualizables(pend), pend)

# El de un dispositivo de antes: la copia de una instalación, sin sello. Su
# vestíbulo solo sabe abrir esa disposición, así que no se pone al día solo: se
# dice, y se remite a «Añadir plataformas…».
de_antes = tmpdir("prdrive-comp-fisica-")
(de_antes / vestibulo.TRAVELER).mkdir()
(de_antes / vestibulo.TRAVELER / vestibulo.TRAVELER_EXE).write_bytes(b"MZ")
(de_antes / vestibulo.TRAVELER / "veracrypt-x64.sys").write_bytes(b"MZ")
pend = components.pendientes(vacia, de_antes)
c("un VeraCrypt sin sello sale pendiente, como algo que no consta",
  [(p.que, p.lleva) for p in pend], [(components.VERACRYPT, components.DESCONOCIDA)])
c("marcado: no lo pone al día una actualización de componentes",
  (pend[0].asistente, components.actualizables(pend)), (True, []))
c.contains("y dice por dónde se sale", pend[0].describe(), "«Añadir plataformas…»")

poner_veracrypt(fisica, sello=False)
c("también el portable si le falta el sello: sin sello no se afirma nada",
  [p.asistente for p in components.pendientes(vacia, fisica)], [True])

# Sin pasar la raíz física se busca por el id: el fichero de control dentro, la
# marca del vestíbulo fuera (`vestibulo.raiz_fisica`, sustituida aquí).
real_raiz = vestibulo.raiz_fisica
try:
    poner_veracrypt(fisica, "1.26.7")
    vestibulo.raiz_fisica = lambda device_id: fisica if device_id == "abc" else None
    con_id = tmpdir("prdrive-comp-id-") / ".prdrive"
    con_id.mkdir()
    (con_id / "PRDRIVE").write_text("id=abc\n", encoding="utf-8")
    c("dentro de un contenedor, se encuentra su VeraCrypt por el id",
      [p.que for p in components.pendientes(con_id)], [components.VERACRYPT])
    vestibulo.raiz_fisica = lambda device_id: 1 / 0
    c("y si buscarlo falla, no lanza: no hay nada que decir",
      components.pendientes(con_id), [])
finally:
    vestibulo.raiz_fisica = real_raiz

sello_vc = components.veracrypt_stamp_text(
    "1.26.24", "f" * 64, {"VeraCrypt-x64.exe": "A" * 64, "../fuera.exe": "b" * 64,
                          "C:\\x.exe": "c" * 64})
c("un sello escrito a mano no saca a nadie de la carpeta",
  components.veracrypt_ficheros(sello_vc), {"VeraCrypt-x64.exe": "a" * 64})

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
