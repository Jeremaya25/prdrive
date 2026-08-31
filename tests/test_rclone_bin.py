#!/usr/bin/env python3
"""
Conseguir rclone: qué se descarga y qué se comprueba antes de guardarlo.

Lo que baja este módulo se ejecuta y acaba copiado dentro del dispositivo, así
que la parte interesante no es la descarga sino la negativa: si el SHA-256 no es
el que publica rclone, no se escribe nada. Antes no se comprobaba nada y
cualquier cosa que contestara en esa URL acababa ejecutándose.

`rclone_bin.fetch()` es de módulo justo para esto y aquí se sustituye entera:
ningún test de este proyecto habla con la red. `cache_dir()` también, para no
ensuciar el %LOCALAPPDATA% de quien corra los tests.
"""

import hashlib
import io
import zipfile

from _harness import Checks, tmpdir

from install import InstallError, rclone_bin

c = Checks("instalador: descarga y comprobación de rclone")

VERSION = "v1.75.0"
SYS, ARCH = rclone_bin.os_arch()
NOMBRE_ZIP = f"rclone-{VERSION}-{SYS}-{ARCH}.zip"
EXE = rclone_bin.exe_name()


def zip_de_mentira(contenido: bytes = b"soy rclone") -> bytes:
    """Un zip con la misma forma que el de rclone: carpeta con versión dentro."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"rclone-{VERSION}-{SYS}-{ARCH}/README.txt", "hola")
        zf.writestr(f"rclone-{VERSION}-{SYS}-{ARCH}/{EXE}", contenido)
    return buf.getvalue()


ZIP = zip_de_mentira()
SUMA = hashlib.sha256(ZIP).hexdigest()

SUMS = (f"# generado por rclone\n"
        f"{'0' * 64}  rclone-{VERSION}-otro-sistema.zip\n"
        f"{SUMA}  {NOMBRE_ZIP}\n")


def red(respuestas: dict):
    """Sustituye `fetch` por un diccionario de URL -> bytes. Cuenta lo pedido."""
    pedidas: list[str] = []

    def falso(url, timeout=None):
        pedidas.append(url)
        if url not in respuestas:
            raise AssertionError(f"el código ha pedido una URL que no esperaba: {url}")
        valor = respuestas[url]
        if isinstance(valor, Exception):
            raise valor
        return valor

    rclone_bin.fetch = falso
    return pedidas


URL_VERSION = f"{rclone_bin.RCLONE_BASE_URL}/version.txt"
URL_SUMS = f"{rclone_bin.RCLONE_BASE_URL}/{VERSION}/SHA256SUMS"
URL_ZIP = f"{rclone_bin.RCLONE_BASE_URL}/{VERSION}/{NOMBRE_ZIP}"

fetch_real = rclone_bin.fetch
cache_real = rclone_bin.cache_dir
try:
    # --- leer la versión publicada -------------------------------------------
    red({URL_VERSION: b"rclone v1.75.0\n"})
    c("version.txt se lee y se queda con la versión",
      rclone_bin.latest_version(), "v1.75.0")

    red({URL_VERSION: b"no me apetece contestar\n"})
    try:
        rclone_bin.latest_version()
        c("una version.txt ilegible se rechaza", "siguió adelante", "InstallError")
    except InstallError as e:
        c("una version.txt ilegible se rechaza", "InstallError", "InstallError")
        c.contains("diciendo qué URL era", str(e), "version.txt")

    # --- la URL es la VERSIONADA, no el alias 'current' -----------------------
    #
    # Importa: entre leer version.txt y bajar el zip puede publicarse otra
    # versión, y con `current` la suma sería de un fichero y el fichero otro.
    c("la URL del zip lleva la versión dentro",
      rclone_bin.download_url(VERSION), URL_ZIP)
    c("y no es el alias 'current'",
      "current" in rclone_bin.download_url(VERSION), False)

    # --- sacar la suma del SHA256SUMS ----------------------------------------
    red({URL_SUMS: SUMS.encode()})
    c("se encuentra la línea del zip que toca",
      rclone_bin.published_sha256(VERSION, NOMBRE_ZIP), SUMA)

    red({URL_SUMS: SUMS.encode()})
    try:
        rclone_bin.published_sha256(VERSION, "rclone-v1.75.0-nosuch-arch.zip")
        c("sin suma para nuestro zip no se sigue", "siguió", "InstallError")
    except InstallError as e:
        c("sin suma para nuestro zip no se sigue", "InstallError", "InstallError")
        c.contains("y se dice cuál falta", str(e), "nosuch-arch")

    # --- la descarga completa, cuando todo cuadra ----------------------------
    destino = tmpdir("prdrive-rclone-")
    rclone_bin.cache_dir = lambda: destino
    pedidas = red({URL_VERSION: b"rclone v1.75.0\n",
                   URL_SUMS: SUMS.encode(), URL_ZIP: ZIP})
    dicho: list[str] = []
    binario = rclone_bin.download_rclone(progreso=dicho.append)
    c("el binario acaba en la caché", binario, destino / EXE)
    c("y es el que venía dentro del zip", binario.read_bytes(), b"soy rclone")
    c("se pidió la versión, las sumas y el zip, en ese orden",
      pedidas, [URL_VERSION, URL_SUMS, URL_ZIP])
    c.contains("y se cuenta que la suma cuadró", " ".join(dicho), SUMA)
    c("el zip no se queda por ahí", (destino / "rclone.zip").exists(), False)

    # --- y cuando NO cuadra --------------------------------------------------
    #
    # Ésta es la comprobación por la que existe el fichero. No basta con que
    # falle: no puede haber dejado nada escrito.
    limpio = tmpdir("prdrive-rclone-malo-")
    rclone_bin.cache_dir = lambda: limpio
    red({URL_VERSION: b"rclone v1.75.0\n", URL_SUMS: SUMS.encode(),
         URL_ZIP: zip_de_mentira(b"esto NO es rclone")})
    try:
        rclone_bin.download_rclone()
        c("un zip que no cuadra con su suma se rechaza", "siguió", "InstallError")
    except InstallError as e:
        c("un zip que no cuadra con su suma se rechaza", "InstallError", "InstallError")
        c.contains("enseñando la suma esperada", str(e), SUMA)
        c.contains("y diciendo que no ha guardado nada", str(e), "No se ha guardado nada")
    c("y NO deja el binario escrito", (limpio / EXE).exists(), False)
    c("ni el zip", (limpio / "rclone.zip").exists(), False)
    c("la caché se queda como estaba", list(limpio.iterdir()), [])
finally:
    rclone_bin.fetch = fetch_real
    rclone_bin.cache_dir = cache_real

raise SystemExit(c.report())
