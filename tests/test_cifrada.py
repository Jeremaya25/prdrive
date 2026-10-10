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
- Lo que el agente le pregunta a `common/bitlocker.py` de una unidad: si está
  bloqueada (`locked`), si lleva BitLocker (`present`), el nombre de su volumen
  (`volumen_de()`, que nunca lanza) y la orden que la desbloquea
  (`orden_desbloquear()`).

Sin tocar ningún dispositivo: los puntos de sustitución (`vestibulo.raiz_fisica`,
`equipo.leer_ajustes`, `cifrada.bitlocker_de`, `bitlocker._leer_volumen`) se
cambian a mano.
"""

import os
import sys
from pathlib import Path

from _harness import Checks, sandbox, tmpdir

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

# lo que pregunta el agente: bloqueado, con BitLocker, qué volumen es y cómo se desbloquea
S = bitlocker.BitLockerStatus
c("locked: solo el estado bloqueado y comprobado",
  [S(True, e).locked for e in (bitlocker.BDE_LOCKED, bitlocker.BDE_ON)]
  + [S(False, bitlocker.BDE_LOCKED).locked], [True, False, False])
c("present: cualquier estado conocido menos apagado y no cifrable",
  {e: S(True, e).present for e in bitlocker.BDE_TEXTOS},
  {e: e not in (bitlocker.BDE_OFF, bitlocker.BDE_NOT_ENCRYPTABLE)
   for e in bitlocker.BDE_TEXTOS})
c("  sin comprobar, no", S(False).present, False)
leer_volumen = bitlocker._leer_volumen
try:
    pedidas = []
    bitlocker._leer_volumen = lambda r: pedidas.append(r) or "\\\\?\\Volume{ABCD-12}\\"
    c("volumen_de: el nombre, en minúsculas, pedido con la raíz de la letra",
      (bitlocker.volumen_de("e:", True), bitlocker.volumen_de(Path("E:\\"), True), pedidas),
      ("\\\\?\\volume{abcd-12}\\",) * 2 + (["E:\\", "E:\\"],))
    c("  fuera de Windows, de una carpeta o de una ruta que no es de una letra, nada",
      [bitlocker.volumen_de("E:\\", False), bitlocker.volumen_de("E:\\datos", True),
       bitlocker.volumen_de("datos", True), bitlocker.volumen_de("/media/x", True),
       bitlocker.volumen_de("\\\\nas\\cosas\\", True)], [""] * 5)
    for fallo in (OSError("retirada"), RuntimeError("COM")):
        def revienta(r, e=fallo):
            """Falla como Windows con un volumen que se va a media pregunta."""
            raise e
        bitlocker._leer_volumen = revienta
        c(f"  si Windows falla ({type(fallo).__name__}), nada y sin lanzar",
          bitlocker.volumen_de("E:\\", True), "")
finally:
    bitlocker._leer_volumen = leer_volumen
entorno = {k: os.environ.get(k) for k in ("SystemRoot", "WINDIR")}
try:
    sistema = tmpdir("prdrive-windows-")
    os.environ["SystemRoot"] = str(sistema)
    c("orden_desbloquear: sin bdeunlock.exe en este Windows, no hay orden",
      bitlocker.orden_desbloquear("e:", True), None)
    exe = sistema / "System32" / "bdeunlock.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    c("  con él, su ruta completa y la raíz de la letra",
      bitlocker.orden_desbloquear("e:", True), [str(exe), "E:\\"])
    c("  fuera de Windows o de una carpeta, no",
      [bitlocker.orden_desbloquear("E:\\", False),
       bitlocker.orden_desbloquear("E:\\datos", True)], [None, None])
    del os.environ["SystemRoot"]
    os.environ["WINDIR"] = str(sistema)
    c("  sin SystemRoot, la carpeta de Windows sale de WINDIR",
      bitlocker.orden_desbloquear(Path("E:\\"), True), [str(exe), "E:\\"])
finally:
    for clave, valor in entorno.items():
        if valor is None:
            os.environ.pop(clave, None)
        else:
            os.environ[clave] = valor

sys.exit(c.report())
