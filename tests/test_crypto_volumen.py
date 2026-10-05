#!/usr/bin/env python3
r"""Lo que se pregunta al sistema de ficheros de una CARPETA se pregunta a su volumen.

`crypto.soporta_dispersos()` y `crypto.sistema_de_ficheros()` se hicieron para
la raíz de una unidad (`G:\\`), que es lo que les pasan el asistente y el paso
«Cifrado» de una unidad. La raíz cifrada de un equipo les pasa una carpeta
(`~/PRDRIVE-cifrado`), y `GetVolumeInformationW` solo acepta la raíz de un
volumen: con una carpeta fallaba, el contenedor se creaba fijo en un NTFS y el
tope de FAT32 no se miraba (H-1 de las pruebas en real,
`docs/superpowers/pruebas/2026-09-25-equipo-pendiente-en-real-resultados.md`).

Este test sí le pregunta al sistema, y solo lee: el volumen de la carpeta
temporal, el que haya en el equipo donde se ejecute.
"""

import os
from pathlib import Path

from _harness import Checks, tmpdir

from install import crypto

c = Checks("VeraCrypt: el sistema de ficheros de una carpeta es el de su volumen")


def raiz_de(ruta: Path) -> Path:
    """Devuelve la raíz del volumen de una ruta.

    La calcula aquí y no con el código que se prueba: en Windows, la unidad de
    la ruta; en los demás, el primer punto de montaje subiendo.
    """
    ruta = Path(os.path.abspath(ruta))
    if crypto.IS_WIN:
        return Path(ruta.anchor)
    while not os.path.ismount(ruta):
        ruta = ruta.parent
    return ruta


def donde_probar(raiz: Path, ruta: Path) -> Path:
    """Devuelve dónde preguntar por los dispersos del volumen de `ruta`.

    La raíz, si se puede escribir en ella. En POSIX `soporta_dispersos()`
    prueba escribiendo, y sin ser root no se puede escribir en `/`: la raíz
    contestaría «no» por eso, no por su sistema de ficheros. Ahí se pregunta a
    la carpeta más cercana a la raíz, del mismo volumen, donde sí se pueda.
    """
    if crypto.IS_WIN or os.access(raiz, os.W_OK):
        return raiz
    ruta = Path(os.path.abspath(ruta))
    debajo = [p for p in (ruta, *ruta.parents) if raiz in p.parents]
    return next(p for p in reversed(debajo) if os.access(p, os.W_OK))


carpeta = tmpdir("prdrive-volumen-") / "PRDRIVE-cifrado"
carpeta.mkdir()
raiz = raiz_de(carpeta)
otra = donde_probar(raiz, carpeta)
if otra != raiz:
    print(f"  (en {raiz} no se puede escribir: los dispersos se preguntan en {otra})")

c("soporta_dispersos: una carpeta contesta lo mismo que la raíz de su volumen",
  crypto.soporta_dispersos(carpeta), crypto.soporta_dispersos(otra))
c("sistema_de_ficheros: una carpeta contesta lo mismo que la raíz de su volumen",
  crypto.sistema_de_ficheros(carpeta), crypto.sistema_de_ficheros(raiz))
if crypto.IS_WIN:
    # Que no sean iguales por no saber nada de ninguno de los dos.
    c("  y en Windows la raíz sí se sabe", bool(crypto.sistema_de_ficheros(raiz)), True)
c("una carpeta que todavía no existe, también (la del contenedor, antes de crearla)",
  crypto.sistema_de_ficheros(carpeta / "todavia-no"), crypto.sistema_de_ficheros(raiz))

raise SystemExit(c.report())
