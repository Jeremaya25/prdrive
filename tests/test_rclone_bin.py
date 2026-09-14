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

La versión ya no es «la que diga version.txt»: está fijada en `common/pins.py`,
y lo que se descarga es esa. Y ya no es solo la de este equipo: el dispositivo
puede llevar rclone para varias plataformas, cada una con su zip.
"""

import hashlib
import io
import zipfile

from _harness import Checks, tmpdir

from common import pins
from install import InstallError, rclone_bin

c = Checks("instalador: descarga y comprobación de rclone")

VERSION = pins.RCLONE_VERSION
SYS, ARCH = rclone_bin.os_arch()
NOMBRE_ZIP = f"rclone-{VERSION}-{SYS}-{ARCH}.zip"
EXE = rclone_bin.exe_name()
LINUX_ARM = pins.plataforma("linux-arm64")


def zip_de_mentira(contenido: bytes = b"soy rclone", sysname: str = SYS,
                   arch: str = ARCH, exe: str = EXE) -> bytes:
    """Un zip con la misma forma que el de rclone: carpeta con versión dentro."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"rclone-{VERSION}-{sysname}-{arch}/README.txt", "hola")
        zf.writestr(f"rclone-{VERSION}-{sysname}-{arch}/{exe}", contenido)
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


URL_SUMS = f"{rclone_bin.RCLONE_BASE_URL}/{VERSION}/SHA256SUMS"
URL_ZIP = f"{rclone_bin.RCLONE_BASE_URL}/{VERSION}/{NOMBRE_ZIP}"

fetch_real = rclone_bin.fetch
cache_real = rclone_bin.cache_dir
try:
    # --- la URL es la VERSIONADA, no el alias 'current' -----------------------
    #
    # Importa: `current` se mueve con cada publicación, y la suma que se tiene
    # en la mano es la de la versión fijada, no la de lo que haya salido hoy.
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
        rclone_bin.published_sha256(VERSION, f"rclone-{VERSION}-nosuch-arch.zip")
        c("sin suma para nuestro zip no se sigue", "siguió", "InstallError")
    except InstallError as e:
        c("sin suma para nuestro zip no se sigue", "InstallError", "InstallError")
        c.contains("y se dice cuál falta", str(e), "nosuch-arch")

    # --- la descarga completa, cuando todo cuadra ----------------------------
    destino = tmpdir("prdrive-rclone-")
    rclone_bin.cache_dir = lambda plat=None: destino
    pedidas = red({URL_SUMS: SUMS.encode(), URL_ZIP: ZIP})
    dicho: list[str] = []
    binario = rclone_bin.download_rclone(progreso=dicho.append)
    c("el binario acaba en la caché", binario, destino / EXE)
    c("y es el que venía dentro del zip", binario.read_bytes(), b"soy rclone")
    # La versión FIJADA: ni se pregunta a version.txt cuál es la última.
    c("se pidieron las sumas y el zip de la versión fijada, nada más",
      pedidas, [URL_SUMS, URL_ZIP])
    c.contains("y se cuenta que la suma cuadró", " ".join(dicho), SUMA)
    c("el zip no se queda por ahí", (destino / "rclone.zip").exists(), False)

    # --- otra plataforma: su zip, su binario, su caché ------------------------
    c("el zip de otra plataforma se nombra con la suya",
      rclone_bin.zip_name(VERSION, LINUX_ARM), f"rclone-{VERSION}-linux-arm64.zip")
    zip_arm = zip_de_mentira(b"rclone de linux arm", "linux", "arm64", "rclone")
    url_arm = f"{rclone_bin.RCLONE_BASE_URL}/{VERSION}/rclone-{VERSION}-linux-arm64.zip"
    sums_arm = f"{hashlib.sha256(zip_arm).hexdigest()}  rclone-{VERSION}-linux-arm64.zip\n"
    otra = tmpdir("prdrive-rclone-otra-")

    def cache_por_arch(plat=None):
        d = otra / (plat.bin_dir if plat else "host")
        d.mkdir(exist_ok=True)
        return d
    rclone_bin.cache_dir = cache_por_arch
    red({URL_SUMS: sums_arm.encode(), url_arm: zip_arm})
    arm = rclone_bin.download_rclone(plat=LINUX_ARM)
    c("se guarda con el nombre de ESA plataforma", arm, otra / "arm" / "rclone")
    c("y es el binario de su zip", arm.read_bytes(), b"rclone de linux arm")

    # Pedirlo otra vez sale de la caché, sin red.
    red({})
    c("rclone_for() lo encuentra en la caché sin descargar",
      rclone_bin.rclone_for(LINUX_ARM), arm)

    # La plataforma de ESTE equipo sigue la cadena de siempre (checkout, junto al
    # .exe, PATH, caché): así se puede aprovisionar sin red con un rclone a mano.
    buscado = rclone_bin.find_rclone
    rclone_bin.find_rclone = lambda: destino / EXE
    try:
        from install import platforms
        c("la de este equipo usa lo que encuentre find_rclone()",
          rclone_bin.rclone_for(platforms.host()), destino / EXE)
    finally:
        rclone_bin.find_rclone = buscado

    # Un macOS no es «Linux» por no ser Windows: su rclone es de otro sistema,
    # y copiarlo como el de Linux dejaría un binario que no arranca en ninguno.
    # Se usa el Linux de la MISMA CPU que este equipo: es el único que podría
    # confundirse con él.
    linux_aqui = pins.plataforma_para("linux", rclone_bin.bin_subdir())
    zip_aqui = zip_de_mentira(b"rclone de linux", "linux", linux_aqui.rclone_arch,
                              "rclone")
    nombre_aqui = rclone_bin.zip_name(VERSION, linux_aqui)
    plataforma_real = rclone_bin.sys.platform
    es_win_real = rclone_bin.IS_WIN
    rclone_bin.find_rclone = lambda: destino / EXE
    rclone_bin.sys.platform, rclone_bin.IS_WIN = "darwin", False
    try:
        red({URL_SUMS: f"{hashlib.sha256(zip_aqui).hexdigest()}  {nombre_aqui}\n".encode(),
             rclone_bin.download_url(VERSION, linux_aqui): zip_aqui})
        c("en un Mac, el rclone del equipo no pasa por el de Linux",
          rclone_bin.rclone_for(linux_aqui).read_bytes(), b"rclone de linux")
    finally:
        rclone_bin.sys.platform, rclone_bin.IS_WIN = plataforma_real, es_win_real
        rclone_bin.find_rclone = buscado

    red({})
    try:
        rclone_bin.rclone_for(pins.plataforma("windows-arm64"), allow_download=False)
        c("sin caché y sin permiso para descargar se dice", "siguió", "InstallError")
    except InstallError as e:
        c("sin caché y sin permiso para descargar se dice", "InstallError", "InstallError")
        c.contains("nombrando la plataforma", str(e), "Windows ARM64")
    rclone_bin.cache_dir = lambda plat=None: destino

    # --- y cuando NO cuadra --------------------------------------------------
    #
    # Ésta es la comprobación por la que existe el fichero. No basta con que
    # falle: no puede haber dejado nada escrito.
    limpio = tmpdir("prdrive-rclone-malo-")
    rclone_bin.cache_dir = lambda plat=None: limpio
    red({URL_SUMS: SUMS.encode(), URL_ZIP: zip_de_mentira(b"esto NO es rclone")})
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

    # --- la caché va por versión fijada --------------------------------------
    #
    # Sin este tramo, mover `pins.RCLONE_VERSION` no servía de nada mientras la
    # caché del equipo tuviera el binario de antes: `rclone_for()` lo encuentra
    # antes de plantearse descargar, así que la versión nueva no llegaba nunca a
    # un dispositivo. Y desde R4 eso además le mentiría al sello.
    rclone_bin.cache_dir = cache_real
    version_real = rclone_bin.pins.RCLONE_VERSION
    try:
        rclone_bin.pins.RCLONE_VERSION = "v9.9.9"
        cache_nueva = rclone_bin.cache_dir()
        rclone_bin.pins.RCLONE_VERSION = "v0.0.1"
        cache_vieja = rclone_bin.cache_dir()
        c("la caché no mezcla versiones", cache_nueva != cache_vieja, True)
        c("y la arquitectura sigue siendo el último tramo",
          cache_nueva.name, rclone_bin.bin_subdir())
    finally:
        rclone_bin.pins.RCLONE_VERSION = version_real

    # --- la caché se vuelve a resumir cada vez que se usa ---------------------
    #
    # Igual que la de los runtimes: la carpeta ya garantiza la VERSIÓN, lo que
    # queda por garantizar son los bytes. Esto va a acabar ejecutándose en cada
    # equipo donde se enchufe el dispositivo.
    sano = tmpdir("prdrive-rclone-sano-")
    rclone_bin.cache_dir = lambda plat=None: sano
    red({URL_SUMS: SUMS.encode(), URL_ZIP: ZIP})
    guardado = rclone_bin.download_rclone()
    c("al descargar se apunta la suma al lado",
      (sano / (EXE + ".sha256")).is_file(), True)
    red({})
    c("y volver a pedirlo sale de la caché sin red",
      rclone_bin.pinned_rclone(platforms.host()) if platforms.host() else guardado,
      guardado)

    guardado.write_bytes(b"esto ya no es el que se comprobo")
    c("una caché estropeada deja de valer", rclone_bin.cached(), None)
    red({URL_SUMS: SUMS.encode(), URL_ZIP: ZIP})
    c("y se vuelve a descargar entera",
      rclone_bin.pinned_rclone(platforms.host()).read_bytes()
      if platforms.host() else b"soy rclone", b"soy rclone")

    # --- de qué binario se puede AFIRMAR la versión --------------------------
    #
    # Solo del que salió de la caché, que va por versión. De uno encontrado en
    # el PATH o dejado a mano junto al instalador no se sabe nada, y el sello
    # del dispositivo tiene que decir «no consta» en vez de mentir: ejecutarlo
    # para preguntárselo no vale, el de otra plataforma no arranca aquí.
    c("del de la caché sí", rclone_bin.pinned_version(sano / EXE), VERSION)
    ajeno = tmpdir("prdrive-rclone-ajeno-") / EXE
    ajeno.write_bytes(b"vete tu a saber")
    c("de uno de fuera, no", rclone_bin.pinned_version(ajeno), "")
finally:
    rclone_bin.fetch = fetch_real
    rclone_bin.cache_dir = cache_real

raise SystemExit(c.report())
