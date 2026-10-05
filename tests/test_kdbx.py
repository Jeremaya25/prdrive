#!/usr/bin/env python3
"""Mirar si una base de KeePassXC está entera, sin clave (`common/kdbx.py`).

Las bases se fabrican aquí con la forma del formato (las firmas, la cabecera
con sus campos, la suma de KDBX 4 y su cadena de bloques), así que no hace
falta ninguna base de verdad. El módulo se probó además a mano contra bases
reales: una KDBX 4.0 y dos 3.x de los datos de prueba de KeePassXC 2.7.12, y
dos 3.1 creadas con `keepassxc-cli` 2.7.6. En la 4.0, ningún corte pasó por
entera; en las 3.x con AES, uno de cada 16, que es lo que permite el formato
sin la clave.

Lo que importa: una base cortada en cualquier byte no pasa por entera (KDBX 4),
una con el cuerpo de un largo imposible tampoco (KDBX 3 con AES o Twofish), y
un formato que no se conoce no se da por roto.
"""

import hashlib
import struct
import sys

from _harness import Checks, tmpdir

from common import kdbx

c = Checks("bases de KeePassXC enteras (common/kdbx.py)")

AES = bytes.fromhex("31c1f2e6bf714350be5805216afc5aff")
CHACHA = bytes.fromhex("d6038a2b8b6f4cb5a524339a31dbb59a")
SEMILLA = bytes(range(32))


def cabecera(mayor: int, campos: list[tuple[int, bytes]], menor: int = 1) -> bytes:
    """Devuelve las firmas, la versión y los campos, con su `EndOfHeader`."""
    ancho = "<BH" if mayor == 3 else "<BI"
    datos = struct.pack("<IIHH", kdbx.FIRMA_1, kdbx.FIRMA_2, menor, mayor)
    for campo, valor in campos + [(0, b"\r\n\r\n")]:
        datos += struct.pack(ancho, campo, len(valor)) + valor
    return datos


def kdbx4(bloques: list[bytes], semilla: bytes = SEMILLA) -> bytes:
    """Devuelve una base KDBX 4 de mentira con esos bloques de datos."""
    cab = cabecera(4, [(2, AES), (4, semilla), (7, b"\x05" * 16)])
    datos = cab + hashlib.sha256(cab).digest() + b"\x01" * 32
    for bloque in bloques + [b""]:
        datos += b"\x02" * 32 + struct.pack("<i", len(bloque)) + bloque
    return datos


def kdbx3(cifrado: bytes, cuerpo: int) -> bytes:
    """Devuelve una base KDBX 3.1 de mentira con un cuerpo de ese largo."""
    return cabecera(3, [(2, cifrado), (4, SEMILLA)]) + b"\xaa" * cuerpo


# KDBX 4: entera, y cortada en cualquier byte
BASE = kdbx4([b"x" * 300, b"y" * 40])
estado = kdbx.mirar(BASE)
c("una KDBX 4 entera está entera", (estado.entera, estado.version), (True, "4.1"))
c("  y se lee su semilla", estado.semilla, SEMILLA)
cortadas = [n for n in range(len(BASE)) if kdbx.mirar(BASE[:n]).entera is not False]
c("cortada en cualquier byte, nunca pasa por entera", cortadas, [])
c.contains("con un byte de más tampoco", kdbx.mirar(BASE + b"x").motivo,
           "después del final")
mala = bytearray(BASE)
mala[20] ^= 1                                    # dentro de la cabecera
c.contains("con la cabecera tocada, su suma no cuadra", kdbx.mirar(bytes(mala)).motivo,
           "suma de la cabecera")
c("sin bloques de datos, la del final basta", kdbx.mirar(kdbx4([])).entera, True)

# lo que no es una base
c("algo que no empieza como una base no está entera",
  kdbx.mirar(b"PK\x03\x04" + b"\0" * 40).entera, False)
c("ni algo vacío", kdbx.mirar(b"").entera, False)
otra = struct.pack("<IIHH", kdbx.FIRMA_1, kdbx.FIRMA_2, 0, 5) + b"\0" * 50
c("una versión que no se conoce no se da por rota", kdbx.mirar(otra).entera, None)

# KDBX 3.1: la cabecera y, con AES o Twofish, el largo del cuerpo
c("una 3.1 con AES y el cuerpo en bloques de 16 está entera",
  (kdbx.mirar(kdbx3(AES, 1184)).entera, kdbx.mirar(kdbx3(AES, 1184)).version),
  (True, "3.1"))
c("  cortada a mitad de un bloque, no", kdbx.mirar(kdbx3(AES, 1183)).entera, False)
c("  sin cuerpo, tampoco", kdbx.mirar(kdbx3(AES, 0)).entera, False)
c("con otro cifrado solo se mira la cabecera", kdbx.mirar(kdbx3(CHACHA, 1183)).entera, True)
cab3 = kdbx3(AES, 0)
c("una 3.1 cortada dentro de la cabecera no está entera",
  [n for n in range(len(cab3)) if kdbx.mirar(cab3[:n]).entera is not False], [])

# desde el disco
d = tmpdir("prdrive-kdbx-")
(d / "buena.kdbx").write_bytes(BASE)
(d / "cortada.kdbx").write_bytes(BASE[:-10])
c("comprobar() lee el fichero", kdbx.comprobar(d / "buena.kdbx").entera, True)
c("  y una cortada no está entera", kdbx.comprobar(d / "cortada.kdbx").entera, False)
c.contains("  y uno que no se lee tampoco", kdbx.comprobar(d / "no-existe.kdbx").motivo,
           "no se puede leer")
c("semilla() lee solo la cabecera", kdbx.semilla(d / "cortada.kdbx"), SEMILLA)
(d / "otra.kdbx").write_bytes(kdbx4([b"x" * 300, b"y" * 40], semilla=b"\x09" * 32))
c("  y distingue dos guardados del mismo tamaño",
  kdbx.semilla(d / "otra.kdbx") != kdbx.semilla(d / "buena.kdbx"), True)
c("  sin base, nada", kdbx.semilla(d / "no-existe.kdbx"), b"")

sys.exit(c.report())
