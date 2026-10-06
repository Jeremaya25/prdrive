#!/usr/bin/env python3
"""¿Está cifrado el dispositivo? (`common/cifrada.py`), lo que permite un llavero sin contraseña.

Lo que se sujeta:
- Una unidad dentro de un contenedor VeraCrypt (hay raíz física con su marca,
  distinta de donde corre) está cifrada; con BitLocker protegido, también.
- La raíz del equipo, si `agente.json` la lista con su contenedor.
- Lo que no se puede comprobar es «no cifrada», nunca al revés: una excepción, el
  estado de BitLocker desconocido, o una raíz física que es la misma carpeta.
- El lector de BitLocker de `common/bitlocker.py` es el mismo que el del
  instalador (`install/crypto.py` lo reexporta).

Sin tocar ningún dispositivo: los puntos de sustitución (`vestibulo.raiz_fisica`,
`equipo.leer_ajustes`, `cifrada.bitlocker_de`) se cambian a mano.
"""

import os
import sys
from pathlib import Path

from _harness import Checks, sandbox

from common import bitlocker, cifrada, equipo, model, vestibulo
from install import crypto

c = Checks("cifrado del dispositivo (common/cifrada.py)")

reales = (vestibulo.raiz_fisica, equipo.leer_ajustes, cifrada.bitlocker_de, model.APP_DIR)


def sin_bitlocker(raiz):
    """BitLocker sin comprobar, como fuera de Windows."""
    return bitlocker.BitLockerStatus(False, detail="BitLocker es solo de Windows.")


try:
    with sandbox() as root:
        app = root / ".prdrive"
        app.mkdir()
        model.APP_DIR = app
        (app / "PRDRIVE").write_text("id=abc123\n", encoding="utf-8")
        cifrada.bitlocker_de = sin_bitlocker

        # una unidad
        vestibulo.raiz_fisica = lambda ident: None
        r = cifrada.estado()
        c("una unidad sin contenedor ni BitLocker, no está cifrada", r.cifrada, False)
        c.contains("  y dice por qué", r.motivo, "no está dentro de un contenedor VeraCrypt")
        fisica = root.parent / "fisica"
        vistos = []
        vestibulo.raiz_fisica = lambda ident: vistos.append(ident) or fisica
        r = cifrada.estado()
        c("con raíz física (marca y contenedor), cifrada con VeraCrypt",
          (r.cifrada, r.como, r.motivo, vistos), (True, cifrada.VERACRYPT, "", ["abc123"]))
        vestibulo.raiz_fisica = lambda ident: root
        c("si la «raíz física» es donde corre, no es un contenedor: una marca vieja",
          cifrada.estado().cifrada, False)

        # BitLocker
        vestibulo.raiz_fisica = lambda ident: None
        cifrada.bitlocker_de = lambda raiz: bitlocker.BitLockerStatus(
            True, bitlocker.BDE_ON, "BitLockerProtection=1")
        r = cifrada.estado()
        c("con BitLocker protegido, cifrada", (r.cifrada, r.como), (True, cifrada.BITLOCKER))
        for estado_bl in (bitlocker.BDE_OFF, bitlocker.BDE_SUSPENDED, bitlocker.BDE_WAITING,
                          bitlocker.BDE_ENCRYPTING, bitlocker.BDE_LOCKED):
            cifrada.bitlocker_de = lambda raiz, e=estado_bl: bitlocker.BitLockerStatus(True, e)
            c(f"  BitLocker en el estado {estado_bl} no vale", cifrada.estado().cifrada, False)
        cifrada.bitlocker_de = lambda raiz: bitlocker.BitLockerStatus(
            False, detail="Windows no ha contestado")
        c("  sin poder comprobarlo, tampoco", cifrada.estado().cifrada, False)

        # fallar cerrado
        cifrada.bitlocker_de = sin_bitlocker

        def revienta(*a, **k):
            """Falla como un volumen que se retira a media lectura."""
            raise RuntimeError("el volumen se ha ido")

        vestibulo.raiz_fisica = revienta
        r = cifrada.estado()
        c("si algo falla al comprobar, se da por no cifrada", r.cifrada, False)
        c.contains("  diciendo qué pasó", r.motivo, "el volumen se ha ido")

        # la raíz del equipo
        (app / "PRDRIVE").write_text("id=abc123\ntipo=equipo\n", encoding="utf-8")
        vestibulo.raiz_fisica = revienta                  # una raíz del equipo no la mira
        equipo.leer_ajustes = lambda: equipo.Ajustes(unidades={})
        r = cifrada.estado()
        c("una raíz del equipo que el agente no lista, no está cifrada", r.cifrada, False)
        c.contains("  y lo dice de la raíz del equipo", r.motivo, "La raíz de este equipo")
        equipo.leer_ajustes = lambda: equipo.Ajustes(unidades={
            "abc123": equipo.Unidad("abc123", ruta=str(root), contenedor=str(root / "x.hc"))})
        r = cifrada.estado()
        c("  listada con su contenedor, cifrada", (r.cifrada, r.como), (True, cifrada.VERACRYPT))
        equipo.leer_ajustes = lambda: equipo.Ajustes(unidades={
            "abc123": equipo.Unidad("abc123", ruta=str(root))})
        c("  sin contenedor (una carpeta a secas), no", cifrada.estado().cifrada, False)
finally:
    vestibulo.raiz_fisica, equipo.leer_ajustes, cifrada.bitlocker_de, model.APP_DIR = reales

# el lector de BitLocker es uno, el de común
c("el instalador reexporta el de común",
  (crypto.BitLockerStatus is bitlocker.BitLockerStatus, crypto.BDE_ON == bitlocker.BDE_ON,
   crypto.BDE_TEXTOS is bitlocker.BDE_TEXTOS), (True, True, True))
leer_real = bitlocker._leer_estado_bitlocker
try:
    bitlocker._leer_estado_bitlocker = lambda ruta: bitlocker.BDE_ON
    c("y común lo pregunta con la letra", bitlocker.estado_de(
        "e:", lambda ruta: (ruta, bitlocker.BDE_ON)[1], True).protected, True)
    c("  fuera de Windows no se inventa nada",
      bitlocker.estado_de("E", lambda ruta: bitlocker.BDE_ON, False).known, False)
finally:
    bitlocker._leer_estado_bitlocker = leer_real
if os.name != "nt":
    c("fuera de Windows, `bitlocker_de` no sabe", cifrada.bitlocker_de(Path("/")).known, False)

sys.exit(c.report())
