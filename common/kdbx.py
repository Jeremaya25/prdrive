#!/usr/bin/env python3
"""Mirar si una base de KeePassXC está entera, sin contraseña y sin descifrar nada.

Es la red que impide subir una base a medio guardar: KeePassXC escribe en un
temporal y lo renombra al final (`QSaveFile`), pero si la persona contestó
«Deshabilitar» a «¿Desactivar almacenajes seguros?» escribe encima del fichero,
y una pasada que lo lea en ese momento subiría media base (H-11). La otra red es
que rclone ya falla un fichero que cambia mientras lo sube.

Lo que se puede saber sin la clave sale del formato KDBX
(`src/format/KeePass2.h`, `Kdbx4Reader.cpp` y `Kdbx3Reader.cpp` de KeePassXC
2.7.12, y la especificación de KeePass 2.x):

- Las dos firmas al principio: `0x9AA2D903` y `0xB54BFB67` (little-endian).
  Después, la versión: menor y mayor, dos `uint16`.
- La cabecera: campos `id` (1 byte), tamaño y datos, hasta el de `id` 0
  (`EndOfHeader`). El tamaño es `uint16` en KDBX 3 y `uint32` en KDBX 4.
- KDBX 4, además: tras la cabecera, su SHA-256 (32 bytes), que se comprueba, y
  su HMAC (32 bytes), que necesita la clave. Luego los bloques HMAC
  (`HmacBlockStream`): 32 bytes de HMAC, un `int32` con el tamaño y los datos.
  El último bloque mide 0, y tiene que acabar justo al final del fichero.

En KDBX 3 el cuerpo cifrado no dice dónde acaba sin descifrarlo. Lo que sí se
sabe es que con AES o Twofish va en CBC con relleno PKCS#7, así que mide un
múltiplo de 16 bytes (campo 2, `CipherID`, `KeePass2::CIPHER_AES256` y
`CIPHER_TWOFISH`): un corte al azar se ve 15 veces de cada 16. Con otro cifrado
solo se comprueba la cabecera. Un formato que no se conoce no bloquea nada:
«no se sabe» (`None`) no es «está rota».

La semilla (`MasterSeed`, campo 4 de la cabecera, 32 bytes) cambia en cada
guardado: es lo que distingue dos guardados del mismo tamaño en el mismo tic de
reloj de exFAT. Para eso basta con leer el principio del fichero (`semilla()`).
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import NamedTuple

FIRMA_1 = 0x9AA2D903
"""Primera firma de un fichero de KeePass 2.x (`KeePass2::SIGNATURE_1`)."""
FIRMA_2 = 0xB54BFB67
"""Segunda firma de KDBX (`KeePass2::SIGNATURE_2`); la de KeePass 1.x es otra."""
FIN_CABECERA = 0
"""`id` del campo que cierra la cabecera (`EndOfHeader`)."""
CIFRADO = 2
"""`id` del campo del cifrado (`CipherID`), un UUID de 16 bytes."""
SEMILLA = 4
"""`id` del campo de la semilla (`MasterSeed`)."""
CIFRADOS_DE_BLOQUE = (bytes.fromhex("31c1f2e6bf714350be5805216afc5aff"),
                      bytes.fromhex("ad68f29f576f4bb9a36ad47af965346c"))
"""AES-256 y Twofish (`KeePass2::CIPHER_AES256`, `CIPHER_TWOFISH`): CBC, bloques de 16."""
BLOQUE = 16
TAM_SUMA = 32
"""Bytes del SHA-256 de la cabecera, y también los de su HMAC y los de cada bloque."""
LEER_CABECERA = 64 * 1024
"""Bytes que se leen para sacar la semilla: la cabecera cabe de sobra."""


class Estado(NamedTuple):
    """Lo que se sabe de una base sin abrirla.

    Args:
        entera: True si todo lo que se puede comprobar cuadra, False si algo
            no, y `None` si el formato no se conoce.
        version: `4.1`, `3.1`…, o vacío si no se lee.
        motivo: Qué falla, para decirlo; vacío si nada.
        semilla: La `MasterSeed` de la cabecera, o vacío si no se lee.
        cifrado: El `CipherID` de la cabecera, o vacío si no se lee.
    """
    entera: bool | None
    version: str = ""
    motivo: str = ""
    semilla: bytes = b""
    cifrado: bytes = b""


def _cabecera(datos: bytes) -> tuple[Estado, int]:
    """Lee las firmas y la cabecera.

    Returns:
        El estado (con `entera` a True si la cabecera llega entera) y dónde
        acaba la cabecera, o -1 si no se ha podido leer.
    """
    if len(datos) < 12:
        return Estado(False, motivo="es demasiado corta para ser una base"), -1
    firma_1, firma_2, menor, mayor = struct.unpack("<IIHH", datos[:12])
    if firma_1 != FIRMA_1 or firma_2 != FIRMA_2:
        return Estado(False, motivo="no empieza como una base de KeePassXC"), -1
    version = f"{mayor}.{menor}"
    if mayor not in (3, 4):
        return Estado(None, version, f"es una versión de KDBX que no se conoce ({version})"), -1
    ancho = "<H" if mayor == 3 else "<I"
    paso = struct.calcsize(ancho)
    pos = 12
    semilla = cifrado = b""
    while True:
        if pos + 1 + paso > len(datos):
            return Estado(False, version, "la cabecera está cortada"), -1
        campo = datos[pos]
        (largo,) = struct.unpack(ancho, datos[pos + 1:pos + 1 + paso])
        pos += 1 + paso
        if pos + largo > len(datos):
            return Estado(False, version, "la cabecera está cortada"), -1
        if campo == SEMILLA:
            semilla = datos[pos:pos + largo]
        elif campo == CIFRADO:
            cifrado = datos[pos:pos + largo]
        pos += largo
        if campo == FIN_CABECERA:
            return Estado(True, version, semilla=semilla, cifrado=cifrado), pos


def mirar(datos: bytes) -> Estado:
    """Comprueba una base entera en memoria (ver el docstring del módulo)."""
    estado, fin = _cabecera(datos)
    if fin < 0:
        return estado
    if estado.version.startswith("3."):
        cuerpo = len(datos) - fin
        if estado.cifrado in CIFRADOS_DE_BLOQUE and (cuerpo <= 0 or cuerpo % BLOQUE):
            return estado._replace(entera=False, motivo="está cortada")
        return estado
    if fin + 2 * TAM_SUMA > len(datos):
        return estado._replace(entera=False, motivo="falta la suma de la cabecera")
    if hashlib.sha256(datos[:fin]).digest() != datos[fin:fin + TAM_SUMA]:
        return estado._replace(entera=False,
                               motivo="la suma de la cabecera no cuadra")
    pos = fin + 2 * TAM_SUMA
    while True:
        if pos + TAM_SUMA + 4 > len(datos):
            return estado._replace(entera=False, motivo="está cortada")
        (largo,) = struct.unpack("<i", datos[pos + TAM_SUMA:pos + TAM_SUMA + 4])
        pos += TAM_SUMA + 4
        if largo < 0 or pos + largo > len(datos):
            return estado._replace(entera=False, motivo="está cortada")
        pos += largo
        if largo == 0:
            if pos != len(datos):
                return estado._replace(entera=False,
                                       motivo="lleva datos después del final")
            return estado


def comprobar(ruta: Path | str) -> Estado:
    """Comprueba la base de ese fichero.

    Una base son unos cientos de KB: se lee entera. Lo que no se puede leer
    cuenta como no entera, porque eso es lo que habría subido.
    """
    try:
        datos = Path(ruta).read_bytes()
    except OSError as e:
        return Estado(False, motivo=f"no se puede leer ({e})")
    return mirar(datos)


def semilla(ruta: Path | str) -> bytes:
    """Devuelve la semilla de la cabecera de esa base, o vacío si no se lee.

    Lee solo el principio del fichero. Nunca lanza: es lo que mira la
    vigilancia del llavero en cada vuelta.
    """
    try:
        with open(ruta, "rb") as f:
            datos = f.read(LEER_CABECERA)
    except OSError:
        return b""
    estado, _fin = _cabecera(datos)
    return estado.semilla
