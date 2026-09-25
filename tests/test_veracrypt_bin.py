#!/usr/bin/env python3
"""
El VeraCrypt Portable oficial, abierto sin ejecutarlo (install/veracrypt_bin.py).

El paquete es un autoextraíble de VeraCrypt: el `.exe` del extractor y, detrás,
un bloque con su propio formato (`src/Setup/SelfExtract.c`, tag
VeraCrypt_1.26.24). Aquí se fabrica uno de mentira con ESE formato —el mismo
LZMA, los mismos marcadores, los mismos CRC— y se comprueba lo que puede hacer
daño:

  * que lo que sale es lo que había dentro, y solo lo que viaja;
  * que un fichero con su CRC mal, un paquete con el suyo mal o un SHA-256 que
    no es el fijado no escriben nada —y la caché queda como estaba—;
  * que un nombre que se sale de la carpeta tumba el paquete entero antes de
    escribir el primero;
  * y la trampa del formato: `VCINSTRT` aparece también en el código del
    extractor, y el bueno es el último.

Ninguno habla con la red: `fetch()` se sustituye, y la caché va a un
`LOCALAPPDATA` de mentira.
"""

import hashlib
import lzma
import os
import struct
import sys
import urllib.error
import zlib

from _harness import Checks, pe, tmpdir

from common import components, pins
from install import InstallError, veracrypt_bin

c = Checks("VeraCrypt Portable: abrirlo sin ejecutarlo (install/veracrypt_bin.py)")


def contenido_de(arq_o_nada, nombre):
    maquinas = {"x64": 0x8664, "arm64": 0xAA64}
    return pe(maquinas[arq_o_nada], nombre.encode()) if arq_o_nada else nombre.encode()


def ficheros_portable():
    """Los ficheros de un portable, con el orden de `szCompressedFiles`."""
    salida = [(n, contenido_de(None, n)) for n in veracrypt_bin.LICENCIAS]
    for arq in veracrypt_bin.ARQUITECTURAS:
        for n in (veracrypt_bin.montar(arq), veracrypt_bin.expander(arq),
                  veracrypt_bin.formatear(arq)):
            salida.append((n, contenido_de(arq, n)))
    salida.append(("veracrypt.inf", b"[Version]"))
    for arq in veracrypt_bin.ARQUITECTURAS:
        salida.append((f"veracrypt-{arq}.cat", b"catalogo " + arq.encode()))
        salida.append((veracrypt_bin.driver(arq), contenido_de(arq, "driver")))
    salida += [("Languages.zip", b"PK idiomas"), ("docs.zip", b"PK documentacion")]
    return salida


def paquete(ficheros, crc_malo=None, crc_paquete_malo=False, codigo=b"",
            firma_en_zona=b""):
    """Un `VeraCrypt Portable X.exe` de mentira, como lo escribe
    `MakeSelfExtractingPackage()`.

    `codigo` va en el «extractor», antes del bloque: ahí es donde el de verdad
    lleva otro `VCINSTRT`. `firma_en_zona` cambia bytes entre 0x130 y 0x1ff
    DESPUÉS de calcular el CRC, como hace firmar el `.exe`."""
    plano = b""
    for nombre, contenido in ficheros:
        crc = zlib.crc32(contenido)
        if nombre == crc_malo:
            crc ^= 1
        plano += (struct.pack(">H", len(nombre)) + nombre.encode("utf-16-le")
                  + struct.pack(">II", crc, len(contenido)) + contenido)
    # LzmaCompress escribe 5 bytes de propiedades y el flujo; el formato «alone»
    # lleva además el tamaño (8 bytes), que aquí sobra.
    alone = lzma.compress(plano, format=lzma.FORMAT_ALONE)
    bloque = alone[:5] + alone[13:]
    extractor = bytearray(b"MZ" + bytes(0x3FE))
    extractor[0x80:0x80 + len(codigo)] = codigo
    datos = (bytes(extractor) + codigo + b"VCINSTRT"
             + struct.pack(">II", len(plano), len(bloque)) + bloque + b"VCINSCRC")
    crc = veracrypt_bin.crc_paquete(datos, len(datos) - 8)
    if crc_paquete_malo:
        crc ^= 1
    datos = bytearray(datos + struct.pack(">I", crc) + b"firma Authenticode" * 40)
    if firma_en_zona:
        datos[0x150:0x150 + len(firma_en_zona)] = firma_en_zona
    return bytes(datos)


def fallo_de(funcion, *args):
    try:
        funcion(*args)
        return None
    except InstallError as e:
        return str(e)


# --- 1. abrirlo -------------------------------------------------------------------
bueno = paquete(ficheros_portable())
todos = veracrypt_bin.abrir_paquete(bueno)
c("salen todos los ficheros, en su orden",
  list(todos), [n for n, _ in ficheros_portable()])
c("con su contenido", todos["VeraCrypt-arm64.exe"],
  dict(ficheros_portable())["VeraCrypt-arm64.exe"])
viajan = veracrypt_bin.seleccionar(todos)
c("viajan ejecutables, drivers, catálogos, el .inf y las licencias",
  sorted(viajan), sorted(n for n, _ in ficheros_portable() if not n.endswith(".zip")))
c("la documentación y los idiomas no", "docs.zip" in viajan or "Languages.zip" in viajan,
  False)
c("lo imprescindible son montar, crear y el driver de las dos arquitecturas",
  sorted(veracrypt_bin.IMPRESCINDIBLES),
  sorted(["VeraCrypt-x64.exe", "VeraCrypt Format-x64.exe", "veracrypt-x64.sys",
          "VeraCrypt-arm64.exe", "VeraCrypt Format-arm64.exe", "veracrypt-arm64.sys"]))

# La firma Authenticode cambia bytes de la cabecera PE: VeraCrypt los pone a cero
# antes del CRC (`WipeSignatureAreas`), y aquí igual.
c("firmar el .exe no rompe el CRC del paquete",
  fallo_de(veracrypt_bin.abrir_paquete,
           paquete(ficheros_portable(), firma_en_zona=b"FIRMA" * 10)), None)

# --- 2. el VCINSTRT del extractor --------------------------------------------------
#
# En el paquete de verdad `VCINSTRT` sale dos veces: en el código del extractor
# (es una cadena suya) y delante del bloque. `FindStringInFile()` busca desde el
# final; tomar el primero es leer como cabecera un trozo de código.
repetido = paquete(ficheros_portable(), codigo=b"...VCINSTRT...codigo del extractor")
c("con VCINSTRT también en el código del extractor, se toma el último",
  list(veracrypt_bin.abrir_paquete(repetido)), [n for n, _ in ficheros_portable()])

# --- 3. lo que tiene que tumbarlo --------------------------------------------------
fallo = fallo_de(veracrypt_bin.abrir_paquete,
                 paquete(ficheros_portable(), crc_malo="VeraCrypt-x64.exe"))
c.contains("un fichero con su CRC-32 mal no pasa", fallo or "", "VeraCrypt-x64.exe")
fallo = fallo_de(veracrypt_bin.abrir_paquete,
                 paquete(ficheros_portable(), crc_paquete_malo=True))
c.contains("el paquete con su CRC mal tampoco (VerifyPackageIntegrity)",
           fallo or "", "VerifyPackageIntegrity")
cortado = bytearray(bueno)
cortado[bueno.rfind(b"VCINSTRT") + 8 + 8 + 20] ^= 0xFF    # dentro del bloque LZMA
c("un byte cambiado dentro del bloque, tampoco",
  fallo_de(veracrypt_bin.abrir_paquete, bytes(cortado)) is not None, True)
c.contains("algo que no es el paquete, tampoco",
           fallo_de(veracrypt_bin.abrir_paquete, b"MZ" + bytes(4096)) or "",
           "marcadores")

for malo in ("../fuera.exe", "..", "C:\\Windows\\x.exe", "sub/dir.exe",
             "sub\\dir.exe", "/etc/passwd"):
    fallo = fallo_de(veracrypt_bin.abrir_paquete,
                     paquete([("License.txt", b"ok"), (malo, b"malo")]))
    c(f"un nombre que se sale ({malo!r}) tumba el paquete",
      fallo is not None and "se sale" in fallo, True)

falta = [(n, x) for n, x in ficheros_portable() if n != "veracrypt-arm64.sys"]
c.contains("sin un imprescindible no se copia a medias",
           fallo_de(lambda: veracrypt_bin.seleccionar(
               veracrypt_bin.abrir_paquete(paquete(falta)))) or "",
           "veracrypt-arm64.sys")

# --- 4. bajarlo y dejarlo en la caché ---------------------------------------------
equipo = tmpdir("prdrive-localappdata-")
os.environ["LOCALAPPDATA"] = str(equipo)
real_fetch, real_sha = veracrypt_bin.fetch, pins.VERACRYPT_SHA256
pedidos: list[str] = []
try:
    c("la caché va por versión", veracrypt_bin.cache_dir(),
      equipo / "prdrive-install" / "veracrypt" / pins.VERACRYPT_VERSION)
    c("sin nada bajado no hay caché", veracrypt_bin.cached(), None)

    # Un SHA-256 que no es el fijado no escribe nada.
    veracrypt_bin.fetch = lambda url, timeout=0: pedidos.append(url) or bueno
    pins.VERACRYPT_SHA256 = "0" * 64
    fallo = fallo_de(veracrypt_bin.download_veracrypt)
    c.contains("un SHA-256 que no es el fijado se dice", fallo or "", "no es el paquete")
    c("se pide la URL con la versión", pedidos, [pins.VERACRYPT_URL])
    c("y no se ha escrito nada en la caché",
      sorted(p.name for p in veracrypt_bin.cache_dir().iterdir()), [])

    pins.VERACRYPT_SHA256 = hashlib.sha256(bueno).hexdigest()
    dicho: list[str] = []
    cache = veracrypt_bin.download_veracrypt(dicho.append)
    c("con el bueno, la caché", cache, veracrypt_bin.cache_dir())
    c("lleva lo que viaja y su sello",
      sorted(p.name for p in cache.iterdir()),
      sorted([*viajan, components.VERACRYPT_STAMP]))
    sello = (cache / components.VERACRYPT_STAMP).read_text(encoding="utf-8")
    c("el sello dice la versión", components.leer_sello(sello).get("veracrypt"),
      pins.VERACRYPT_VERSION)
    c("y el SHA-256 de cada fichero",
      components.veracrypt_ficheros(sello)["veracrypt-x64.sys"],
      hashlib.sha256(viajan["veracrypt-x64.sys"]).hexdigest())
    c.contains("y se va contando", "\n".join(dicho), "SHA-256 correcto")
    c("ya está en la caché", veracrypt_bin.cached(), cache)

    pedidos.clear()
    c("ensure no vuelve a bajar lo que ya tiene",
      (veracrypt_bin.ensure_veracrypt(), pedidos), (cache, []))

    # Una caché estropeada no llega a ninguna unidad: se vuelve a resumir.
    (cache / "VeraCrypt-x64.exe").write_bytes(b"estropeado")
    c("una caché estropeada no cuenta", veracrypt_bin.cached(), None)
    veracrypt_bin.ensure_veracrypt()
    c("y se vuelve a bajar", (len(pedidos), veracrypt_bin.cached()), (1, cache))

    # Un fichero con el CRC mal: InstallError, y la caché de antes intacta.
    antes = {p.name: p.read_bytes() for p in cache.iterdir()}
    malo = paquete(ficheros_portable(), crc_malo="veracrypt-arm64.sys")
    veracrypt_bin.fetch = lambda url, timeout=0: malo
    pins.VERACRYPT_SHA256 = hashlib.sha256(malo).hexdigest()
    c("un fichero con el CRC mal no escribe nada",
      fallo_de(veracrypt_bin.download_veracrypt) is not None, True)
    c("y la caché sigue como estaba",
      {p.name: p.read_bytes() for p in cache.iterdir()}, antes)

    # Un nombre que se sale: tampoco se escribe nada, ni el primero.
    fuera = paquete([*ficheros_portable(), ("..\\fuera.exe", b"x")])
    veracrypt_bin.fetch = lambda url, timeout=0: fuera
    pins.VERACRYPT_SHA256 = hashlib.sha256(fuera).hexdigest()
    c("un nombre con .. no escribe nada",
      fallo_de(veracrypt_bin.download_veracrypt) is not None, True)
    c("ni fuera de la caché", (equipo / "prdrive-install" / "fuera.exe").exists(), False)
    c("ni dentro", {p.name: p.read_bytes() for p in cache.iterdir()}, antes)

    # Sin red: `SinRed`, que es lo que deja a traveler copiar el instalado.
    def sin_red(url, timeout=0):
        raise urllib.error.URLError("getaddrinfo failed")

    veracrypt_bin.fetch = sin_red
    (cache / components.VERACRYPT_STAMP).unlink()
    try:
        veracrypt_bin.ensure_veracrypt()
        de_red = "no ha protestado"
    except veracrypt_bin.SinRed as e:
        de_red = str(e)
    except InstallError as e:
        de_red = "InstallError sin más: " + str(e)
    c.contains("sin red es SinRed, distinto de un paquete que no cuadra", de_red,
               "No he podido descargar")
    c.contains("y dice la URL exacta", de_red, pins.VERACRYPT_URL)
    try:
        veracrypt_bin.ensure_veracrypt(allow_download=False)
        de_red = "no ha protestado"
    except veracrypt_bin.SinRed:
        de_red = "SinRed"
    c("sin caché y sin permiso para bajar, también SinRed", de_red, "SinRed")
finally:
    veracrypt_bin.fetch, pins.VERACRYPT_SHA256 = real_fetch, real_sha

# --- 5. lo fijado, sin inventar -----------------------------------------------------
c("la URL lleva la versión, no un «último»",
  pins.VERACRYPT_VERSION in pins.VERACRYPT_URL, True)
c("y es del paquete portable", pins.VERACRYPT_URL.endswith(
  f"VeraCrypt%20Portable%20{pins.VERACRYPT_VERSION}.exe"), True)
c("el SHA-256 fijado tiene la forma de uno", len(pins.VERACRYPT_SHA256), 64)

sys.exit(c.report())
