#!/usr/bin/env python3
"""
Lo que se le pregunta al sistema de ficheros de una CARPETA se pregunta a su volumen.

`crypto.soporta_dispersos()` y `crypto.sistema_de_ficheros()` nacieron para la
raíz de una unidad (`G:\\`), que es lo que les pasan el asistente y el paso
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
    """La raíz del volumen, calculada aquí y no con el código que se prueba: en
    Windows, la unidad de la ruta; en los demás, el primer punto de montaje
    subiendo."""
    ruta = Path(os.path.abspath(ruta))
    if crypto.IS_WIN:
        return Path(ruta.anchor)
    while not os.path.ismount(ruta):
        ruta = ruta.parent
    return ruta


carpeta = tmpdir("prdrive-volumen-") / "PRDRIVE-cifrado"
carpeta.mkdir()
raiz = raiz_de(carpeta)

c("soporta_dispersos: una carpeta contesta lo mismo que la raíz de su volumen",
  crypto.soporta_dispersos(carpeta), crypto.soporta_dispersos(raiz))
c("sistema_de_ficheros: una carpeta contesta lo mismo que la raíz de su volumen",
  crypto.sistema_de_ficheros(carpeta), crypto.sistema_de_ficheros(raiz))
if crypto.IS_WIN:
    # Que no sean iguales por no saber nada de ninguno de los dos.
    c("  y en Windows la raíz sí se sabe", bool(crypto.sistema_de_ficheros(raiz)), True)
c("una carpeta que todavía no existe, también (la del contenedor, antes de crearla)",
  crypto.sistema_de_ficheros(carpeta / "todavia-no"), crypto.sistema_de_ficheros(raiz))

raise SystemExit(c.report())
