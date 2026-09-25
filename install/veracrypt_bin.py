#!/usr/bin/env python3
"""
veracrypt_bin.py — Conseguir el VeraCrypt Portable oficial, comprobado, sin ejecutarlo.

El hermano de `rclone_bin.py` y `runtime_bin.py`, con el mismo contrato: lo que se
descarga se COMPRUEBA antes de escribir nada, y si no cuadra no se guarda nada.
Sirve para dos cosas: crear y montar el contenedor en un equipo que no tiene
VeraCrypt instalado, y dejar en la carpeta `VeraCrypt\\` de la unidad un
VeraCrypt que funcione en Windows x64 y en Windows ARM64
(`install/traveler.py`).

**Qué se baja.** El paquete «VeraCrypt Portable <versión>.exe» de IDRIX, de la
versión y con el SHA-256 fijados en `common/pins.py`. A diferencia de rclone y de
python-build-standalone, IDRIX no publica un fichero de sumas: el número está
escrito en `pins.py` por quien movió la versión después de comprobar a mano la
firma Authenticode y la PGP del paquete (en Python puro no se puede). La
comprobación de aquí, por tanto, es contra ESE número: ataja una descarga
truncada, un proxy que devuelve otra cosa o una caché vieja, y además cualquier
paquete que no sea exactamente el que alguien comprobó. Como en los otros dos,
un corte de red se reintenta (`descarga.con_reintentos()`) y un paquete que no
cuadra no; y el paquete bajado a mano y dejado en la caché con su nombre se
comprueba igual que una descarga, sin red (`adoptar()`).

**Por qué no se ejecuta.** El paquete es un autoextraíble: el `.exe` del
extractor con un bloque añadido detrás. Su formato está en `src/Setup/SelfExtract.c`
(tag VeraCrypt_1.26.24, `MakeSelfExtractingPackage()` lo escribe y
`SelfExtractInMemory()` lo lee), y se lee con la biblioteca estándar:

    VCINSTRT · tamaño sin comprimir (u32 BE) · tamaño comprimido (u32 BE) ·
    un bloque LZMA (5 bytes de propiedades + el flujo, sin marca de fin:
    `LzmaUncompress`) · VCINSCRC · CRC-32 del paquete (u32 BE)

y dentro del bloque, por fichero: longitud del nombre en `wchar_t` (u16 BE) ·
el nombre en UTF-16LE · CRC-32 (u32 BE) · longitud (u32 BE) · el contenido. Los
enteros son big-endian porque son `mputWord`/`mputLong` (`Common/Endian.h`).

Ejecutarlo sería lanzar un instalador con su interfaz y su UAC para sacar unos
ficheros que ya se pueden sacar leyendo; y un `.exe` sin firmar en `%TEMP%` que
lanza otro es justo la forma que no se quiere tener (ver «Nothing in the wizard
spawns a shell» en AGENTS.md).

**Las tres comprobaciones, además del SHA-256.** Las mismas que hace VeraCrypt
antes de extraer, para que un paquete que él rechazaría tampoco pase aquí:

  * `VerifyPackageIntegrity()`: el CRC-32 del fichero desde el principio hasta
    el marcador final incluido, con los bytes `0x130`–`0x1ff` puestos a cero
    (`WipeSignatureAreas()`: es lo que cambia al firmar el `.exe`), contra el
    que va guardado justo detrás del marcador;
  * `SelfExtractInMemory()`: el tamaño comprimido tiene que llegar exactamente
    hasta el marcador final, y lo descomprimido medir lo que dice la cabecera;
  * y el CRC-32 de cada fichero, fichero a fichero.

Los dos marcadores se buscan desde el FINAL, como `FindStringInFile()`
(`Common/Dlgcode.c`: «Searches the file from its end for the LAST occurrence»):
`VCINSTRT` aparece también dentro del código del propio extractor, y el bueno es
el último. `VCINSCRC` no aparece más que una vez porque en el código va ofuscado
(`MAG_END_MARKER_OBFUSCATED`, «V/C/I/N/S/C/R/C»).

**Qué se escribe.** Solo lo que hace falta para montar, crear, agrandar y cargar
el driver —ejecutables, drivers, sus `.cat`, el `.inf`— y las licencias, porque
es su programa lo que se copia. `docs.zip` y `Languages.zip` (20 MB) no. Todo
nombre se valida ANTES de escribir el primero: nada con `/`, `\\`, `..` ni
unidad. Va a la caché del usuario, una carpeta por versión, con el sello
(`components.VERACRYPT_STAMP`) escrito el ÚLTIMO: lleva el SHA-256 de cada
fichero, y es a la vez el manifiesto contra el que se vuelve a resumir la caché
en cada uso y el sello que acaba en la unidad.
"""

from __future__ import annotations

import hashlib
import lzma
import os
import struct
import tempfile
import urllib.request
import zlib
from pathlib import Path
from typing import Callable

from common import components, pins, vestibulo

from . import APP_NAME, InstallError, descarga
from .runtime_bin import file_sha256     # el mismo resumen a trozos, una copia

DOWNLOAD_TIMEOUT = 60          # segundos por lectura, no en total
USER_AGENT = f"{APP_NAME}-install"
Progreso = Callable[[str], None]

# Los marcadores de `src/Setup/SelfExtract.c` (tag VeraCrypt_1.26.24):
# `MAG_START_MARKER`, y `MAG_END_MARKER_OBFUSCATED` ya desofuscado.
MARCA_INICIO = b"VCINSTRT"
MARCA_FIN = b"VCINSCRC"
# `WipeSignatureAreas()`: «Clear bytes 0x130-0x1ff».
FIRMA_DESDE, FIRMA_HASTA = 0x130, 0x200

ARQUITECTURAS = vestibulo.TRAVELER_ARQUITECTURAS
SELLO = components.VERACRYPT_STAMP

# Lo que viaja además de los ejecutables y los drivers: su licencia, porque es su
# programa lo que se copia.
LICENCIAS = ("License.txt", "LICENSE", "NOTICE")
EXTENSIONES = (".exe", ".sys", ".cat", ".inf")


class SinRed(InstallError):
    """No se ha podido BAJAR el paquete (sin red, un proxy, un tiempo de espera).

    Es distinto de que lo bajado no cuadre, y quien llama lo distingue: sin red,
    `install/traveler.py` puede copiar el VeraCrypt instalado en este equipo; un
    paquete que no es el fijado no se esconde detrás de otra cosa."""


# ---------------------------------------------------------------------------
# Los nombres del paquete
# ---------------------------------------------------------------------------

def montar(arq: str) -> str:
    return vestibulo.traveler_portatil(arq)


def formatear(arq: str) -> str:
    return f"VeraCrypt Format-{arq}.exe"


def expander(arq: str) -> str:
    return f"VeraCryptExpander-{arq}.exe"


def driver(arq: str) -> str:
    return f"veracrypt-{arq}.sys"


# Sin estos no hay VeraCrypt portable que valga en esa arquitectura: montar,
# crear el contenedor y el driver que carga `DriverLoad()`.
IMPRESCINDIBLES = tuple(nombre for arq in ARQUITECTURAS
                        for nombre in (montar(arq), formatear(arq), driver(arq)))


def viaja(nombre: str) -> bool:
    """¿Se extrae este fichero del paquete?"""
    return nombre in LICENCIAS or nombre.lower().endswith(EXTENSIONES)


def nombre_seguro(nombre: str) -> bool:
    """Un nombre suelto: ni carpetas, ni `..`, ni unidad, ni vacío."""
    return bool(nombre) and nombre not in (".", "..") and not any(
        c in nombre for c in ("/", "\\", ":", "\0"))


# ---------------------------------------------------------------------------
# Abrir el paquete
# ---------------------------------------------------------------------------

def _corrupto(detalle: str) -> InstallError:
    return InstallError(
        f"El paquete de VeraCrypt no es válido: {detalle}. No se ha escrito nada.")


def crc_paquete(datos: bytes, fin: int) -> int:
    """El CRC-32 que calcula `VerifyPackageIntegrity()`: desde el principio hasta
    el marcador final incluido, con la zona de la firma a cero."""
    cabeza = bytearray(datos[:min(FIRMA_HASTA, fin + len(MARCA_FIN))])
    if len(cabeza) > FIRMA_DESDE:
        cabeza[FIRMA_DESDE:] = bytes(len(cabeza) - FIRMA_DESDE)
    crc = zlib.crc32(bytes(cabeza))
    if fin + len(MARCA_FIN) > FIRMA_HASTA:
        crc = zlib.crc32(datos[FIRMA_HASTA:fin + len(MARCA_FIN)], crc)
    return crc & 0xFFFFFFFF


def _descomprimir(bloque: bytes, sin_comprimir: int) -> bytes:
    """El bloque LZMA del paquete, descomprimido.

    LZMA «alone» es lo mismo que escribe `LzmaCompress` —5 bytes de propiedades
    y el flujo— con el tamaño sin comprimir (u64 LE) en medio; con él se
    descomprime como `LzmaUncompress`, que sabe cuánto espera. `LzmaCompress`
    no escribe marca de fin (`src/Common/lzma/LzmaLib.c`: llama a `LzmaEncode`
    con `writeEndMark` a 0), pero un flujo
    LZMA puede llevarla, y la liblzma de algunos Python (la 5.2) rechaza la
    marca cuando el tamaño es conocido. Entonces se descomprime sin tamaño y solo
    vale si llega a la marca: de todas formas se exige luego que mida lo que
    dice la cabecera y que cada fichero cuadre con su CRC."""
    if len(bloque) <= 5:
        raise _corrupto("el bloque comprimido está vacío")
    try:
        return lzma.decompress(bloque[:5] + struct.pack("<Q", sin_comprimir)
                               + bloque[5:], format=lzma.FORMAT_ALONE)
    except lzma.LZMAError as e:
        primero = e
    try:
        d = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
        plano = d.decompress(bloque[:5] + b"\xff" * 8 + bloque[5:])
    except lzma.LZMAError:
        plano, d = b"", None
    if d is None or not d.eof:
        raise _corrupto(f"no se descomprime ({primero})") from primero
    return plano


def abrir_paquete(datos: bytes) -> dict[str, bytes]:
    """Todos los ficheros del paquete, {nombre: contenido}, en su orden.

    Comprueba todo lo que comprueba VeraCrypt (ver el docstring del módulo) y
    que ningún nombre se salga de la carpeta; si algo falla, InstallError y no se
    devuelve nada. No escribe."""
    fin = datos.rfind(MARCA_FIN)
    inicio = datos.rfind(MARCA_INICIO)
    if fin < 0 or inicio < 0 or inicio > fin:
        raise _corrupto("no encuentro sus marcadores (¿es el portable de VeraCrypt?)")
    if fin + len(MARCA_FIN) + 4 > len(datos):
        raise _corrupto("le falta el CRC del final")
    guardado = struct.unpack(">I", datos[fin + len(MARCA_FIN):fin + len(MARCA_FIN) + 4])[0]
    if crc_paquete(datos, fin) != guardado:
        raise _corrupto("su CRC-32 no cuadra (VerifyPackageIntegrity)")

    pos = inicio + len(MARCA_INICIO)
    if pos + 8 > fin:
        raise _corrupto("la cabecera no llega entera")
    sin_comprimir, comprimido = struct.unpack(">II", datos[pos:pos + 8])
    pos += 8
    # `SelfExtractInMemory()`: el bloque comprimido llega justo hasta el marcador.
    if comprimido != fin - pos or comprimido <= 5:
        raise _corrupto("el tamaño comprimido no llega hasta el final")
    plano = _descomprimir(datos[pos:fin], sin_comprimir)
    if len(plano) != sin_comprimir:
        raise _corrupto("descomprimido no mide lo que dice su cabecera")

    ficheros: dict[str, bytes] = {}
    p = 0
    while p < len(plano):
        if p + 2 > len(plano):
            raise _corrupto("un fichero sin nombre al final")
        largo_nombre = struct.unpack(">H", plano[p:p + 2])[0]
        p += 2
        crudo = plano[p:p + 2 * largo_nombre]
        p += 2 * largo_nombre
        if len(crudo) != 2 * largo_nombre or p + 8 > len(plano):
            raise _corrupto("un fichero cortado a medias")
        try:
            nombre = crudo.decode("utf-16-le")
        except UnicodeDecodeError as e:
            raise _corrupto("un nombre que no se lee") from e
        if not nombre_seguro(nombre):
            raise _corrupto(f"trae un fichero que se sale de su carpeta: {nombre!r}")
        crc, largo = struct.unpack(">II", plano[p:p + 8])
        p += 8
        contenido = plano[p:p + largo]
        p += largo
        if len(contenido) != largo:
            raise _corrupto(f"{nombre} está cortado")
        if zlib.crc32(contenido) & 0xFFFFFFFF != crc:
            raise _corrupto(f"el CRC-32 de {nombre} no cuadra")
        if nombre in ficheros:
            raise _corrupto(f"{nombre} viene dos veces")
        ficheros[nombre] = contenido
    return ficheros


def seleccionar(ficheros: dict[str, bytes]) -> dict[str, bytes]:
    """Lo que viaja de todo lo que trae el paquete. InstallError si falta algo
    imprescindible: un cambio de empaquetado se dice, no se copia a medias."""
    faltan = [n for n in IMPRESCINDIBLES if n not in ficheros]
    if faltan:
        raise InstallError(
            f"El paquete de VeraCrypt no trae {', '.join(faltan)}. ¿Ha cambiado "
            f"el empaquetado? La versión fijada está en common/pins.py. No se ha "
            f"escrito nada.")
    return {n: c for n, c in ficheros.items() if viaja(n)}


# ---------------------------------------------------------------------------
# La caché
# ---------------------------------------------------------------------------

def cache_dir() -> Path:
    """La caché: una carpeta por VERSIÓN, como `rclone_bin.cache_dir()`. Mover
    `pins.VERACRYPT_VERSION` no serviría de nada si se encontrara antes la de la
    versión anterior; con la versión en la ruta, esa simplemente no existe."""
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    d = Path(base) / f"{APP_NAME}-install" / "veracrypt" / pins.VERACRYPT_VERSION
    d.mkdir(parents=True, exist_ok=True)
    return d


def ficheros_de(carpeta: Path) -> dict[str, str]:
    """{nombre: sha256} según el sello de esa carpeta. Vacío sin sello."""
    try:
        texto = (Path(carpeta) / SELLO).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return {}
    return components.veracrypt_ficheros(texto)


def verificada(carpeta: Path, version: str = pins.VERACRYPT_VERSION) -> bool:
    """¿Esa carpeta tiene un sello de esa versión y cada fichero es el que dice?

    Se vuelve a resumir todo en cada uso (son ~28 MB, una fracción de segundo):
    la carpeta ya garantiza la versión; lo que queda por garantizar son los
    bytes, y una caché estropeada no puede llegar a una unidad."""
    try:
        texto = (Path(carpeta) / SELLO).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return False
    if components.leer_sello(texto).get(components.VERACRYPT) != version:
        return False
    ficheros = components.veracrypt_ficheros(texto)
    if not all(n in ficheros for n in IMPRESCINDIBLES):
        return False
    try:
        return all(file_sha256(Path(carpeta) / n) == s for n, s in ficheros.items())
    except OSError:
        return False


def cached() -> Path | None:
    """La carpeta de la caché, si está completa y sigue siendo la que se comprobó."""
    d = cache_dir()
    return d if verificada(d) else None


# ---------------------------------------------------------------------------
# La descarga
# ---------------------------------------------------------------------------

def fetch(url: str, timeout: float = DOWNLOAD_TIMEOUT) -> bytes:
    """La única puerta de salida a la red de este módulo.

    De módulo a propósito, igual que `rclone_bin.fetch()`: los tests la
    sustituyen entera y ninguno habla con Launchpad. Devuelve bytes porque lo
    que baja hay que resumirlo entero antes de escribir nada."""
    peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(peticion, timeout=timeout) as resp:
        return resp.read()


def paquete_a_mano() -> Path:
    """Dónde dejar el paquete bajado con el navegador: en la caché, con su nombre
    exacto. Se comprueba igual que una descarga (`adoptar()`), sin red."""
    return cache_dir() / pins.VERACRYPT_PAQUETE


def a_mano() -> str:
    """Cómo ponerlo a mano cuando la descarga no sale, con los datos exactos."""
    return (f"Sin conexión, instala VeraCrypt en este equipo, o baja a mano el "
            f"paquete oficial:\n  {pins.VERACRYPT_URL}\ncon el SHA-256\n  "
            f"{pins.VERACRYPT_SHA256}\ny déjalo, con ese nombre "
            f"({pins.VERACRYPT_PAQUETE}), en:\n  {cache_dir()}\nAl volver a "
            f"intentarlo se comprueba igual que una descarga.")


def download_veracrypt(progreso: Progreso | None = None) -> Path:
    """Baja el paquete, lo COMPRUEBA entero y deja lo que viaja en la caché.

    Todo en memoria hasta el final: el SHA-256 contra `pins.py`, los CRC del
    paquete y de cada fichero, los nombres. Si algo no cuadra, InstallError y la
    caché queda como estaba. Un corte de red se reintenta
    (`descarga.con_reintentos()`); un paquete que no cuadra, no —ver
    `descarga.py`—. Sin red al final, `SinRed`."""
    def decir(msg: str) -> None:
        if progreso:
            progreso(msg)

    url = pins.VERACRYPT_URL
    decir(f"Descargando VeraCrypt Portable {pins.VERACRYPT_VERSION}: {url}")
    try:
        datos = descarga.con_reintentos(lambda: fetch(url),
                                        f"Descargar {pins.VERACRYPT_PAQUETE}",
                                        progreso)
    except descarga.FALLOS_DE_RED as e:
        raise SinRed(f"No he podido descargar VeraCrypt de {url}: "
                     f"{descarga.describir(e)}\n\n{a_mano()}") from e
    return _guardar(datos, url, decir)


def adoptar(progreso: Progreso | None = None) -> Path | None:
    """El paquete dejado a mano en la caché, comprobado y abierto como una
    descarga; None si no hay ninguno. Uno que no cuadra se dice (InstallError)."""
    ruta = paquete_a_mano()
    try:
        if not ruta.is_file():
            return None
        datos = ruta.read_bytes()
    except OSError:
        return None
    return _guardar(datos, str(ruta),
                    (lambda msg: progreso(msg)) if progreso else (lambda msg: None))


def _guardar(datos: bytes, origen: str, decir: Progreso) -> Path:
    """Comprueba el paquete entero y deja en la caché lo que viaja, con su sello
    el último. Si algo no cuadra, InstallError y no se escribe nada."""
    obtenido = hashlib.sha256(datos).hexdigest()
    if obtenido != pins.VERACRYPT_SHA256:
        raise InstallError(
            f"{origen} no es el paquete de VeraCrypt fijado.\n\n"
            f"  esperado: {pins.VERACRYPT_SHA256}\n  obtenido: {obtenido}\n\n"
            f"No se ha guardado nada. Vuelve a intentarlo.")
    decir(f"SHA-256 correcto: {obtenido}")
    viajan = seleccionar(abrir_paquete(datos))
    decir(f"Paquete íntegro: {len(viajan)} ficheros con su CRC-32 correcto")

    destino = cache_dir()
    try:
        # El sello fuera primero: con él, lo que quede a medias parecería una
        # caché buena hasta resumirla. Y el nuevo, el último.
        (destino / SELLO).unlink(missing_ok=True)
        resumenes = {}
        for nombre, contenido in viajan.items():
            parcial = destino / f"{nombre}.part"
            parcial.write_bytes(contenido)
            os.replace(parcial, destino / nombre)
            resumenes[nombre] = hashlib.sha256(contenido).hexdigest()
        (destino / SELLO).write_text(
            components.veracrypt_stamp_text(pins.VERACRYPT_VERSION, obtenido,
                                            resumenes),
            encoding="utf-8", newline="\n")
    except OSError as e:
        raise InstallError(f"No he podido guardar VeraCrypt en {destino}: {e}") from e
    decir(f"VeraCrypt listo en {destino}")
    return destino


def ensure_veracrypt(progreso: Progreso | None = None,
                     allow_download: bool = True) -> Path:
    """La carpeta con el VeraCrypt Portable fijado, comprobado: la caché, el
    paquete dejado a mano en ella (`adoptar()`) o la descarga.

    Sin nada de eso y sin permiso para descargar, `SinRed`: para quien llama es
    lo mismo que no tener conexión."""
    encontrado = cached()
    if encontrado is not None:
        return encontrado
    adoptado = adoptar(progreso)
    if adoptado is not None:
        return adoptado
    if not allow_download:
        raise SinRed("No hay VeraCrypt Portable en la caché y no se ha permitido "
                     "descargarlo.")
    return download_veracrypt(progreso)
