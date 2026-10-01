#!/usr/bin/env python3
r"""Conseguir el VeraCrypt Portable oficial, comprobado, sin ejecutarlo.

Es el hermano de `rclone_bin.py` y `runtime_bin.py`, con el mismo contrato: lo
que se descarga se COMPRUEBA antes de escribir nada y, si no cuadra, no se
guarda nada. Sirve para crear y montar el contenedor en un equipo sin VeraCrypt
instalado y para dejar en la carpeta `VeraCrypt\` de la unidad un VeraCrypt que
funcione en Windows x64 y ARM64 (`install/traveler.py`).

Qué se baja: el paquete «VeraCrypt Portable <versión>.exe» de IDRIX, de la
versión y con el SHA-256 fijados en `common/pins.py`. A diferencia de rclone y
python-build-standalone, IDRIX no publica un fichero de sumas: el número lo
escribe en `pins.py` quien movió la versión tras comprobar a mano las firmas
Authenticode y PGP del paquete (en Python puro no se puede). La comprobación de
aquí es contra ESE número: ataja una descarga truncada, un proxy que devuelve
otra cosa o una caché vieja, y cualquier paquete que no sea exactamente el que
alguien comprobó. Como en los otros dos, un corte de red se reintenta
(`descarga.con_reintentos()`) y un paquete que no cuadra no; y el paquete
bajado a mano y dejado en la caché con su nombre se comprueba igual que una
descarga, sin red (`adoptar()`).

Por qué no se ejecuta: el paquete es un autoextraíble, el `.exe` del extractor
con un bloque añadido detrás. Su formato está en `src/Setup/SelfExtract.c` (tag
VeraCrypt_1.26.24; `MakeSelfExtractingPackage()` lo escribe y
`SelfExtractInMemory()` lo lee) y se lee con la biblioteca estándar:

    VCINSTRT · tamaño sin comprimir (u32 BE) · tamaño comprimido (u32 BE) ·
    un bloque LZMA (5 bytes de propiedades + el flujo, sin marca de fin:
    `LzmaUncompress`) · VCINSCRC · CRC-32 del paquete (u32 BE)

Dentro del bloque, por fichero: longitud del nombre en `wchar_t` (u16 BE), el
nombre en UTF-16LE, CRC-32 (u32 BE), longitud (u32 BE) y el contenido. Los
enteros son big-endian porque son `mputWord`/`mputLong` (`Common/Endian.h`).
Ejecutarlo sería lanzar un instalador con su interfaz y su UAC para sacar unos
ficheros que ya se pueden sacar leyendo, y un `.exe` sin firmar en `%TEMP%` que
lanza otro es justo la forma que no se quiere tener (ver «Nothing in the wizard
spawns a shell» en AGENTS.md).

Las tres comprobaciones, además del SHA-256, son las mismas que hace VeraCrypt
antes de extraer, para que un paquete que él rechazaría tampoco pase aquí:
- `VerifyPackageIntegrity()`: el CRC-32 del fichero desde el principio hasta el
  marcador final incluido, con los bytes `0x130`–`0x1ff` a cero
  (`WipeSignatureAreas()`: es lo que cambia al firmar el `.exe`), contra el que
  va guardado justo detrás del marcador.
- `SelfExtractInMemory()`: el tamaño comprimido tiene que llegar exactamente
  hasta el marcador final y lo descomprimido medir lo que dice la cabecera.
- El CRC-32 de cada fichero, fichero a fichero.

Los dos marcadores se buscan desde el FINAL, como `FindStringInFile()`
(`Common/Dlgcode.c`: «Searches the file from its end for the LAST occurrence»):
`VCINSTRT` aparece también dentro del código del propio extractor y el bueno es
el último. `VCINSCRC` solo aparece una vez porque en el código va ofuscado
(`MAG_END_MARKER_OBFUSCATED`, «V/C/I/N/S/C/R/C»).

Qué se escribe: solo lo que hace falta para montar, crear, agrandar y cargar el
driver (ejecutables, drivers, sus `.cat`, el `.inf`) y las licencias, porque es
su programa lo que se copia; `docs.zip` y `Languages.zip` (20 MB) no. Todo
nombre se valida ANTES de escribir el primero: nada con `/`, `\`, `..` ni
unidad. Va a la caché del usuario, una carpeta por versión, con el sello
(`components.VERACRYPT_STAMP`) escrito el ÚLTIMO: lleva el SHA-256 de cada
fichero y es a la vez el manifiesto contra el que se vuelve a resumir la caché
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

DOWNLOAD_TIMEOUT = 60  # segundos por lectura, no en total
USER_AGENT = f"{APP_NAME}-install"
"""`User-Agent` de las peticiones de descarga."""
Progreso = Callable[[str], None]
"""Función que recibe cada mensaje de avance."""

MARCA_INICIO = b"VCINSTRT"
"""Marcador de inicio del bloque comprimido.

Es `MAG_START_MARKER` de `src/Setup/SelfExtract.c` (tag VeraCrypt_1.26.24).
"""
MARCA_FIN = b"VCINSCRC"
"""Marcador de fin del bloque (`MAG_END_MARKER_OBFUSCATED` ya desofuscado)."""
# `WipeSignatureAreas()` pone a cero los bytes `0x130`–`0x1ff`, que es lo que
# cambia al firmar el `.exe`: `[FIRMA_DESDE, FIRMA_HASTA)`.
FIRMA_DESDE, FIRMA_HASTA = 0x130, 0x200

ARQUITECTURAS = vestibulo.TRAVELER_ARQUITECTURAS
"""Arquitecturas de Windows que lleva el portable."""
SELLO = components.VERACRYPT_STAMP
"""Nombre del sello de la carpeta del VeraCrypt de viaje."""

LICENCIAS = ("License.txt", "LICENSE", "NOTICE")
"""Ficheros de licencia que viajan: es su programa lo que se copia."""
EXTENSIONES = (".exe", ".sys", ".cat", ".inf")
"""Extensiones de los ficheros que viajan: ejecutables, drivers, catálogos e `.inf`."""


class SinRed(InstallError):
    """No se ha podido BAJAR el paquete (sin red, un proxy, un tiempo de espera).

    Es distinto de que lo bajado no cuadre, y quien llama lo distingue: sin
    red, `install/traveler.py` puede copiar el VeraCrypt instalado en este
    equipo; un paquete que no es el fijado no se esconde detrás de otra cosa.
    """


def montar(arq: str) -> str:
    """Devuelve el nombre del ejecutable de montar para esa arquitectura."""
    return vestibulo.traveler_portatil(arq)


def formatear(arq: str) -> str:
    """Devuelve el nombre del ejecutable que crea contenedores para esa arquitectura."""
    return f"VeraCrypt Format-{arq}.exe"


def expander(arq: str) -> str:
    """Devuelve el ejecutable que agranda contenedores para esa arquitectura."""
    return f"VeraCryptExpander-{arq}.exe"


def driver(arq: str) -> str:
    """Devuelve el nombre del driver para esa arquitectura."""
    return f"veracrypt-{arq}.sys"


IMPRESCINDIBLES = tuple(nombre for arq in ARQUITECTURAS
                        for nombre in (montar(arq), formatear(arq), driver(arq)))
"""Ficheros sin los que no hay VeraCrypt portable que valga en una arquitectura.

Son montar, crear el contenedor y el driver que carga `DriverLoad()`.
"""


def viaja(nombre: str) -> bool:
    """Indica si ese fichero del paquete se extrae."""
    return nombre in LICENCIAS or nombre.lower().endswith(EXTENSIONES)


def nombre_seguro(nombre: str) -> bool:
    """Indica si es un nombre suelto: ni carpetas, ni `..`, ni unidad, ni vacío."""
    return bool(nombre) and nombre not in (".", "..") and not any(
        c in nombre for c in ("/", "\\", ":", "\0"))


def _corrupto(detalle: str) -> InstallError:
    """Devuelve el error de un paquete que no es válido."""
    return InstallError(
        f"El paquete de VeraCrypt no es válido: {detalle}. No se ha escrito nada.")


def crc_paquete(datos: bytes, fin: int) -> int:
    """Calcula el CRC-32 de `VerifyPackageIntegrity()`.

    Va desde el principio hasta el marcador final incluido, con la zona de la
    firma a cero.
    """
    cabeza = bytearray(datos[:min(FIRMA_HASTA, fin + len(MARCA_FIN))])
    if len(cabeza) > FIRMA_DESDE:
        cabeza[FIRMA_DESDE:] = bytes(len(cabeza) - FIRMA_DESDE)
    crc = zlib.crc32(bytes(cabeza))
    if fin + len(MARCA_FIN) > FIRMA_HASTA:
        crc = zlib.crc32(datos[FIRMA_HASTA:fin + len(MARCA_FIN)], crc)
    return crc & 0xFFFFFFFF


def _descomprimir(bloque: bytes, sin_comprimir: int) -> bytes:
    """Descomprime el bloque LZMA del paquete.

    LZMA «alone» es lo mismo que escribe `LzmaCompress` (5 bytes de propiedades
    y el flujo) con el tamaño sin comprimir (u64 LE) en medio; con él se
    descomprime como `LzmaUncompress`, que sabe cuánto espera. `LzmaCompress`
    no escribe marca de fin (`src/Common/lzma/LzmaLib.c`: llama a `LzmaEncode`
    con `writeEndMark` a 0), pero un flujo LZMA puede llevarla y la liblzma de
    algunos Python (la 5.2) rechaza la marca cuando el tamaño es conocido.
    Entonces se descomprime sin tamaño y solo vale si llega a la marca; de
    todas formas se exige luego que mida lo que dice la cabecera y que cada
    fichero cuadre con su CRC.
    """
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
    """Devuelve todos los ficheros del paquete, `{nombre: contenido}`, en su orden.

    Comprueba todo lo que comprueba VeraCrypt (ver el docstring del módulo) y
    que ningún nombre se salga de la carpeta. No escribe nada.

    Raises:
        InstallError: Si algo falla; no se devuelve nada.
    """
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
    # `SelfExtractInMemory()`: el bloque comprimido llega justo hasta el
    # marcador.
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
    """Devuelve de todo lo que trae el paquete lo que viaja.

    Raises:
        InstallError: Si falta algo imprescindible: un cambio de empaquetado se
            dice, no se copia a medias.
    """
    faltan = [n for n in IMPRESCINDIBLES if n not in ficheros]
    if faltan:
        raise InstallError(
            f"El paquete de VeraCrypt no trae {', '.join(faltan)}. ¿Ha cambiado "
            f"el empaquetado? La versión fijada está en common/pins.py. No se ha "
            f"escrito nada.")
    return {n: c for n, c in ficheros.items() if viaja(n)}


def cache_dir() -> Path:
    """Devuelve la caché: una carpeta por VERSIÓN, como `rclone_bin.cache_dir()`.

    Mover `pins.VERACRYPT_VERSION` no serviría de nada si se encontrara antes
    la de la versión anterior; con la versión en la ruta, esa simplemente no
    existe.
    """
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    d = Path(base) / f"{APP_NAME}-install" / "veracrypt" / pins.VERACRYPT_VERSION
    d.mkdir(parents=True, exist_ok=True)
    return d


def ficheros_de(carpeta: Path) -> dict[str, str]:
    """Devuelve `{nombre: sha256}` según el sello de esa carpeta; vacío sin sello."""
    try:
        texto = (Path(carpeta) / SELLO).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return {}
    return components.veracrypt_ficheros(texto)


def verificada(carpeta: Path, version: str = pins.VERACRYPT_VERSION) -> bool:
    """Indica si la carpeta tiene un sello de esa versión y cada fichero es el que dice.

    Se vuelve a resumir todo en cada uso (son ~34 MB, una fracción de segundo):
    la carpeta ya garantiza la versión y lo que queda por garantizar son los
    bytes, porque una caché estropeada no puede llegar a una unidad. Es
    `components.veracrypt_integro()`, la misma comprobación que hace el agente
    con el suyo.
    """
    return components.veracrypt_integro(carpeta, IMPRESCINDIBLES, version)


def cached() -> Path | None:
    """Devuelve la carpeta de la caché si está completa y es la comprobada."""
    d = cache_dir()
    return d if verificada(d) else None


def fetch(url: str, timeout: float = DOWNLOAD_TIMEOUT) -> bytes:
    """Descarga una URL; es la única puerta de salida a la red de este módulo.

    Es de módulo a propósito, como `rclone_bin.fetch()`: los tests la
    sustituyen entera y ninguno habla con Launchpad. Devuelve bytes porque lo
    que baja hay que resumirlo entero antes de escribir nada.
    """
    peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(peticion, timeout=timeout) as resp:
        return resp.read()


def paquete_a_mano() -> Path:
    """Devuelve dónde dejar el paquete bajado con el navegador.

    Es la caché, con su nombre exacto. Se comprueba igual que una descarga
    (`adoptar()`), sin red.
    """
    return cache_dir() / pins.VERACRYPT_PAQUETE


def a_mano() -> str:
    """Devuelve cómo ponerlo a mano cuando la descarga no sale.

    Lleva los datos exactos.
    """
    return (f"Sin conexión, instala VeraCrypt en este equipo, o baja a mano el "
            f"paquete oficial:\n  {pins.VERACRYPT_URL}\ncon el SHA-256\n  "
            f"{pins.VERACRYPT_SHA256}\ny déjalo, con ese nombre "
            f"({pins.VERACRYPT_PAQUETE}), en:\n  {cache_dir()}\nAl volver a "
            f"intentarlo se comprueba igual que una descarga.")


def download_veracrypt(progreso: Progreso | None = None) -> Path:
    """Baja el paquete, lo COMPRUEBA entero y deja lo que viaja en la caché.

    Todo en memoria hasta el final: el SHA-256 contra `pins.py`, los CRC del
    paquete y de cada fichero y los nombres. Un corte de red se reintenta
    (`descarga.con_reintentos()`); un paquete que no cuadra, no (ver
    `descarga.py`).

    Raises:
        SinRed: Si no se puede descargar.
        InstallError: Si algo no cuadra; la caché queda como estaba.
    """
    def decir(msg: str) -> None:
        """Pasa un mensaje a `progreso`, si lo hay."""
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
    """Devuelve el paquete dejado a mano en la caché, ya comprobado.

    Se abre como una descarga.

    Returns:
        La carpeta de la caché, o `None` si no hay paquete.

    Raises:
        InstallError: Si el paquete no cuadra.
    """
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
    """Comprueba el paquete entero y deja en la caché lo que viaja.

    El sello se escribe el último.

    Raises:
        InstallError: Si algo no cuadra o no se puede escribir; si no cuadra,
            no se escribe nada.
    """
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
    """Devuelve la carpeta con el VeraCrypt Portable fijado, comprobado.

    Sale de la caché, del paquete dejado a mano en ella (`adoptar()`) o de la
    descarga.

    Raises:
        SinRed: Si no hay nada de eso y no se permite descargar; para quien
            llama es lo mismo que no tener conexión.
    """
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


APPIMAGE_EXE = "veracrypt"
"""Nombre del AppImage ya en la caché, ejecutable.

En Linux no hay Portable pero sí un AppImage oficial desde la 1.26.24: un solo
ejecutable, sin instalar nada (`pins.VERACRYPT_APPIMAGE`). Se baja, se
comprueba EN MEMORIA contra el SHA-256 fijado y se deja en su propia caché (no
en la del Portable: un Linux también baja el Portable cuando pone al día el
VeraCrypt de viaje de una unidad) como `veracrypt`, con un sello como el del
Portable: el mismo `components.veracrypt_integro()` lo comprueba en cada uso,
aquí y en el agente. No se abre ni se extrae: el fichero ES el programa. Montar
y crear un exFAT siguen pidiendo la contraseña de administrador (VeraCrypt
llama a `sudo` para el loop, dm-crypt y `mkfs.exfat`), igual que con el
instalado.
"""


def appimage(clave: str) -> tuple[str, str]:
    """Devuelve el nombre publicado y el SHA-256 fijado de esa plataforma de Linux.

    Raises:
        KeyError: Si no la hay.
    """
    return pins.VERACRYPT_APPIMAGE[clave]


def appimage_url(clave: str) -> str:
    """Devuelve la URL del AppImage de esa plataforma."""
    return pins.VERACRYPT_APPIMAGE_URL.format(nombre=appimage(clave)[0])


def cache_appimage(clave: str) -> Path:
    """Devuelve la caché del AppImage: una carpeta por versión y plataforma."""
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    d = (Path(base) / f"{APP_NAME}-install" / "veracrypt-appimage"
         / pins.VERACRYPT_VERSION / clave)
    d.mkdir(parents=True, exist_ok=True)
    return d


def appimage_en_cache(clave: str) -> Path | None:
    """Devuelve la carpeta de la caché si tiene el AppImage fijado y íntegro."""
    d = cache_appimage(clave)
    return d if components.veracrypt_integro(d, (APPIMAGE_EXE,),
                                             pins.VERACRYPT_VERSION) else None


def appimage_a_mano(clave: str) -> Path:
    """Devuelve dónde dejar el AppImage bajado con el navegador.

    Es su caché, con su nombre exacto. Se comprueba igual que una descarga, sin
    red.
    """
    return cache_appimage(clave) / appimage(clave)[0]


def _guardar_appimage(datos: bytes, clave: str, origen: str, decir: Progreso) -> Path:
    """Comprueba el AppImage en memoria y lo deja en la caché.

    Queda ejecutable y con su sello.

    Raises:
        InstallError: Si no es el fijado o no se puede guardar.
    """
    nombre, esperado = appimage(clave)
    obtenido = hashlib.sha256(datos).hexdigest()
    if obtenido != esperado:
        raise InstallError(
            f"{origen} no es el AppImage de VeraCrypt fijado.\n\n"
            f"  esperado: {esperado}\n  obtenido: {obtenido}\n\n"
            f"No se ha guardado nada. Vuelve a intentarlo.")
    decir(f"SHA-256 correcto: {obtenido}")
    destino = cache_appimage(clave)
    try:
        (destino / SELLO).unlink(missing_ok=True)
        parcial = destino / f"{APPIMAGE_EXE}.part"
        parcial.write_bytes(datos)
        parcial.chmod(0o755)
        os.replace(parcial, destino / APPIMAGE_EXE)
        (destino / SELLO).write_text(
            components.veracrypt_stamp_text(pins.VERACRYPT_VERSION, obtenido,
                                            {APPIMAGE_EXE: obtenido}, paquete=nombre),
            encoding="utf-8", newline="\n")
    except OSError as e:
        raise InstallError(f"No he podido guardar VeraCrypt en {destino}: {e}") from e
    decir(f"VeraCrypt listo en {destino}")
    return destino


def download_appimage(clave: str, progreso: Progreso | None = None) -> Path:
    """Baja el AppImage, lo comprueba en memoria y lo deja en la caché.

    Es el mismo contrato que `download_veracrypt()`: un corte se reintenta, uno
    que no cuadra no.

    Raises:
        SinRed: Si no se puede descargar.
    """
    def decir(msg: str) -> None:
        """Pasa un mensaje a `progreso`, si lo hay."""
        if progreso:
            progreso(msg)

    nombre, esperado = appimage(clave)
    url = appimage_url(clave)
    decir(f"Descargando VeraCrypt {pins.VERACRYPT_VERSION} (AppImage): {url}")
    try:
        datos = descarga.con_reintentos(lambda: fetch(url), f"Descargar {nombre}",
                                        progreso)
    except descarga.FALLOS_DE_RED as e:
        raise SinRed(
            f"No he podido descargar VeraCrypt de {url}: {descarga.describir(e)}\n\n"
            f"Sin conexión, instala VeraCrypt en este equipo, o baja a mano\n  {url}\n"
            f"con el SHA-256\n  {esperado}\ny déjalo, con ese nombre ({nombre}), "
            f"en:\n  {cache_appimage(clave)}\nAl volver a intentarlo se comprueba "
            f"igual que una descarga.") from e
    return _guardar_appimage(datos, clave, url, decir)


def ensure_appimage(clave: str, progreso: Progreso | None = None,
                    allow_download: bool = True) -> Path:
    """Devuelve la carpeta con el AppImage fijado de esa plataforma, comprobado.

    Sale de la caché, del dejado a mano o de la descarga.
    """
    encontrado = appimage_en_cache(clave)
    if encontrado is not None:
        return encontrado
    ruta = appimage_a_mano(clave)
    try:
        datos = ruta.read_bytes() if ruta.is_file() else None
    except OSError:
        datos = None
    if datos is not None:
        return _guardar_appimage(datos, clave, str(ruta),
                                 (lambda m: progreso(m)) if progreso else (lambda m: None))
    if not allow_download:
        raise SinRed("No hay VeraCrypt (AppImage) en la caché y no se ha permitido "
                     "descargarlo.")
    return download_appimage(clave, progreso)


def para_este_equipo(progreso: Progreso | None = None) -> Path:
    """Devuelve el VeraCrypt sin instalar que sirve en ESTE equipo.

    Es el Portable en Windows y el AppImage de su CPU en Linux.

    Raises:
        InstallError: En otro sistema.
    """
    from . import platforms
    plat = platforms.host()
    if plat is not None and plat.es_windows:
        return ensure_veracrypt(progreso)
    if plat is None or plat.clave not in pins.VERACRYPT_APPIMAGE:
        raise InstallError("No hay un VeraCrypt sin instalar para este sistema: "
                           "instálalo desde veracrypt.jp/en/Downloads.html.")
    return ensure_appimage(plat.clave, progreso)


def en_cache_para_este_equipo() -> Path | None:
    """Devuelve lo mismo que `para_este_equipo`, sin red y sin descargar.

    Returns:
        La caché, si está y cuadra; si no, `None`.
    """
    from . import platforms
    plat = platforms.host()
    if plat is None:
        return None
    if plat.es_windows:
        return cached()
    if plat.clave not in pins.VERACRYPT_APPIMAGE:
        return None
    return appimage_en_cache(plat.clave)
