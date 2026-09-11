#!/usr/bin/env python3
"""
El Python que viaja en el dispositivo: qué se descarga, qué se comprueba y qué
acaba escrito.

Es el mismo contrato que `test_rclone_bin.py` —si el SHA-256 no es el que
publica python-build-standalone, no se escribe nada— más lo que es propio de un
runtime entero y no de un binario suelto:

  * el archivo trae miles de ficheros, y uno solo que pretenda salirse del
    destino tumba la extracción ANTES de escribir nada;
  * exFAT no tiene enlaces simbólicos, así que el `bin/python3` de Linux —que en
    el archivo es un enlace— tiene que acabar siendo un fichero de verdad;
  * lo que no hace falta para ejecutar prdrive (pip, idle, los tests, las
    cabeceras de C) no viaja;
  * y el sello de versión se escribe el ÚLTIMO: un runtime a medias no lo tiene,
    y sin sello no cuenta como instalado.

`runtime_bin.fetch()` y `cache_dir()` se sustituyen enteros: ningún test habla
con GitHub ni ensucia el %LOCALAPPDATA% de nadie.
"""

import hashlib
import io
import os
import tarfile

from _harness import Checks, tmpdir

from common import pins
from install import InstallError, runtime_bin

c = Checks("instalador: el runtime de Python del dispositivo")

WIN = pins.plataforma("windows-x64")
LIN = pins.plataforma("linux-x64")
MM = ".".join(pins.PYTHON_VERSION.split(".")[:2])       # '3.13'


# --- las versiones fijadas y las plataformas ----------------------------------
c("los cuatro destinos de python-build-standalone",
  sorted(p.triple for p in pins.PLATAFORMAS),
  sorted(["x86_64-pc-windows-msvc", "aarch64-pc-windows-msvc",
          "x86_64-unknown-linux-gnu", "aarch64-unknown-linux-gnu"]))
c("una clave por plataforma, sin repetir",
  len({p.clave for p in pins.PLATAFORMAS}), len(pins.PLATAFORMAS))
c("macOS no está: no hay equipo con el que probarlo",
  any("darwin" in p.triple for p in pins.PLATAFORMAS), False)
c("rclone se fija a una versión, no a «la última»",
  pins.RCLONE_VERSION.startswith("v") and pins.RCLONE_VERSION[1].isdigit(), True)
try:
    pins.plataforma("haiku-mips")
    c("una plataforma desconocida se rechaza", "siguió", "KeyError")
except KeyError:
    c("una plataforma desconocida se rechaza", "KeyError", "KeyError")

# El bin/ de rclone y la carpeta del runtime salen de la misma tabla: un x64 de
# Windows y uno de Linux comparten bin/x64 (rclone.exe y rclone no chocan), pero
# cada uno tiene su runtime.
c("Windows x64 y Linux x64 comparten bin/x64", (WIN.bin_dir, LIN.bin_dir), ("x64", "x64"))
c("pero no el nombre del binario", (WIN.rclone_exe, LIN.rclone_exe),
  ("rclone.exe", "rclone"))
c("el intérprete sin ventana de Windows", WIN.interprete, "pythonw.exe")
c("y el de consola", WIN.interprete_consola, "python.exe")
c("en Linux es bin/python3 en los dos casos",
  (LIN.interprete, LIN.interprete_consola), ("bin/python3", "bin/python3"))

# --- los nombres y las URL -----------------------------------------------------
NOMBRE_WIN = (f"cpython-{pins.PYTHON_VERSION}+{pins.PYTHON_RELEASE}-"
              f"x86_64-pc-windows-msvc-install_only_stripped.tar.gz")
c("el nombre del archivo, con versión, release y destino",
  runtime_bin.archive_name(WIN), NOMBRE_WIN)
# El '+' del nombre va escapado en la URL: GitHub lo sirve igual, pero un '+' en
# una ruta es un espacio para más de un proxy.
c("la URL es la de la release FIJADA, con el '+' escapado",
  runtime_bin.download_url(WIN),
  f"{pins.PBS_BASE_URL}/{pins.PYTHON_RELEASE}/"
  + NOMBRE_WIN.replace("+", "%2B"))
c("las sumas se leen de la misma release",
  runtime_bin.SUMS_URL, f"{pins.PBS_BASE_URL}/{pins.PYTHON_RELEASE}/SHA256SUMS")


# --- archivos de mentira con la forma de los de verdad -------------------------
def tar_gz(miembros) -> bytes:
    """miembros: (nombre, bytes | ('link', destino) | None=directorio, modo)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for nombre, dato, *resto in miembros:
            info = tarfile.TarInfo(nombre)
            info.mode = resto[0] if resto else 0o644
            if dato is None:
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tf.addfile(info)
            elif isinstance(dato, tuple):
                info.type = tarfile.SYMTYPE
                info.linkname = dato[1]
                tf.addfile(info)
            else:
                info.size = len(dato)
                tf.addfile(info, io.BytesIO(dato))
    return buf.getvalue()


ARCHIVO_WIN = tar_gz([
    ("python", None),
    ("python/python.exe", b"MZ consola"),
    ("python/pythonw.exe", b"MZ sin ventana"),
    ("python/DLLs/_tkinter.pyd", b"tk"),
    ("python/Lib/os.py", b"# os"),
    ("python/Lib/tkinter/__init__.py", b"# tkinter"),
    # Lo que se poda: nada de esto hace falta para ejecutar prdrive.
    ("python/Lib/site-packages/pip/__init__.py", b"# pip"),
    ("python/Lib/ensurepip/__init__.py", b"# ensurepip"),
    ("python/Lib/idlelib/idle.py", b"# idle"),
    ("python/Lib/test/test_os.py", b"# test"),
    ("python/include/Python.h", b"/* h */"),
    ("python/libs/python313.lib", b"lib"),
])

ARCHIVO_LIN = tar_gz([
    ("python/bin/python" + MM, b"\x7fELF interprete", 0o755),
    ("python/bin/python3", ("link", "python" + MM)),
    ("python/bin/python", ("link", "python" + MM)),
    ("python/bin/pip", b"#!/bin/sh pip", 0o755),
    (f"python/lib/python{MM}/os.py", b"# os"),
    (f"python/lib/python{MM}/lib-dynload/_tkinter.so", b"\x7fELF tk"),
    (f"python/lib/python{MM}/site-packages/pip/__init__.py", b"# pip"),
    (f"python/lib/libpython{MM}.so.1.0", b"\x7fELF libpython"),
    (f"python/lib/libpython{MM}.so", ("link", f"libpython{MM}.so.1.0")),
    ("python/lib/libtcl8.6.so", b"\x7fELF tcl"),
    ("python/share/terminfo/x/xterm", b"terminfo"),
    ("python/include/python3.13/Python.h", b"/* h */"),
])


# --- extraer: Windows -----------------------------------------------------------
def archivo_en_disco(datos: bytes) -> "os.PathLike":
    ruta = tmpdir() / "archivo.tar.gz"
    ruta.write_bytes(datos)
    return ruta


destino = tmpdir() / "windows-x64"
escritos = runtime_bin.extract(archivo_en_disco(ARCHIVO_WIN), destino, WIN,
                               sha256="abc123")
c("el directorio raíz 'python/' del archivo desaparece",
  (destino / "pythonw.exe").read_bytes(), b"MZ sin ventana")
c("llega el intérprete de consola", (destino / "python.exe").is_file(), True)
c("y tkinter, que es la razón de usar esta distribución",
  (destino / "Lib" / "tkinter" / "__init__.py").is_file(), True)
for podado in ("Lib/site-packages", "Lib/ensurepip", "Lib/idlelib", "Lib/test",
               "include", "libs"):
    c(f"{podado} no viaja", (destino / podado).exists(), False)
c("se cuenta lo escrito", escritos, 6)

sello = (destino / runtime_bin.STAMP).read_text(encoding="utf-8")
c.contains("el sello dice la versión de Python", sello, pins.PYTHON_VERSION)
c.contains("la release", sello, pins.PYTHON_RELEASE)
c.contains("el destino", sello, WIN.triple)
c.contains("y la suma del archivo del que salió", sello, "abc123")
c("el sello es el que describe el runtime_bin",
  sello, runtime_bin.stamp_text(WIN, "abc123"))

# --- extraer: Linux, con sus enlaces -----------------------------------------------
destino = tmpdir() / "linux-x64"
runtime_bin.extract(archivo_en_disco(ARCHIVO_LIN), destino, LIN, sha256="def")
python3 = destino / "bin" / "python3"
# El caso de exFAT: no hay enlaces simbólicos. El intérprete se escribe con el
# nombre estable que usan los lanzadores, y no dos veces.
c("bin/python3 es un fichero de verdad, no un enlace",
  python3.is_file() and not python3.is_symlink(), True)
c("con el contenido del intérprete", python3.read_bytes(), b"\x7fELF interprete")
c("y no se duplica con su nombre versionado",
  (destino / "bin" / ("python" + MM)).exists(), False)
c("los demás enlaces no se crean", (destino / "bin" / "python").exists(), False)
c("ni lo demás de bin/", (destino / "bin" / "pip").exists(), False)
if os.name != "nt":
    c("el intérprete conserva el bit de ejecución",
      bool(python3.stat().st_mode & 0o100), True)
c("la biblioteca estándar llega", (destino / "lib" / f"python{MM}" / "os.py").is_file(), True)
c("y el tkinter de Linux",
  (destino / "lib" / f"python{MM}" / "lib-dynload" / "_tkinter.so").is_file(), True)
c("Tcl/Tk se queda", (destino / "lib" / "libtcl8.6.so").is_file(), True)
# El intérprete de python-build-standalone lleva libpython enlazado estático: la
# .so es para quien lo incrusta, y son 30 MB.
c("libpython.so no viaja", sorted(p.name for p in (destino / "lib").glob("libpython*")), [])
c("ni share/ (terminfo, man)", (destino / "share").exists(), False)
c("el sello está", (destino / runtime_bin.STAMP).is_file(), True)

# --- un archivo que pretende salirse no escribe NADA -----------------------------
malo = tar_gz([("python/python.exe", b"MZ"), ("python/../../fuera.txt", b"x")])
destino = tmpdir() / "malo"
try:
    runtime_bin.extract(archivo_en_disco(malo), destino, WIN, sha256="x")
    c("un miembro que se escapa se rechaza", "siguió", "InstallError")
except InstallError as e:
    c("un miembro que se escapa se rechaza", "InstallError", "InstallError")
    c.contains("diciendo cuál", str(e), "fuera.txt")
c("y no se ha escrito nada, ni lo que venía antes", destino.exists(), False)

enlace_fuera = tar_gz([("python/bin/python3", ("link", "/usr/bin/python3"))])
try:
    runtime_bin.extract(archivo_en_disco(enlace_fuera), tmpdir() / "e", LIN, sha256="x")
    c("un intérprete que es un enlace hacia fuera se rechaza", "siguió", "InstallError")
except InstallError:
    c("un intérprete que es un enlace hacia fuera se rechaza", "InstallError", "InstallError")

sin_interprete = tar_gz([("python/Lib/os.py", b"# os")])
try:
    runtime_bin.extract(archivo_en_disco(sin_interprete), tmpdir() / "s", WIN, sha256="x")
    c("un archivo sin el intérprete no se da por bueno", "siguió", "InstallError")
except InstallError as e:
    c("un archivo sin el intérprete no se da por bueno", "InstallError", "InstallError")
    c.contains("y se dice qué falta", str(e), "pythonw.exe")


# --- descargar, comprobar y guardar en la caché -------------------------------------
def red(respuestas: dict):
    pedidas: list[str] = []

    def falso(url, timeout=None):
        pedidas.append(url)
        if url not in respuestas:
            raise AssertionError(f"el código ha pedido una URL que no esperaba: {url}")
        valor = respuestas[url]
        if isinstance(valor, Exception):
            raise valor
        return valor

    runtime_bin.fetch = falso
    return pedidas


SUMA_WIN = hashlib.sha256(ARCHIVO_WIN).hexdigest()
SUMS = (f"{'0' * 64}  cpython-{pins.PYTHON_VERSION}+{pins.PYTHON_RELEASE}-"
        f"aarch64-apple-darwin-install_only_stripped.tar.gz\n"
        f"{SUMA_WIN}  {NOMBRE_WIN}\n").encode()
URL_WIN = runtime_bin.download_url(WIN)

fetch_real, cache_real = runtime_bin.fetch, runtime_bin.cache_dir
try:
    red({runtime_bin.SUMS_URL: SUMS})
    c("se encuentra la suma del destino que toca",
      runtime_bin.published_sha256(WIN), SUMA_WIN)
    red({runtime_bin.SUMS_URL: SUMS})
    try:
        runtime_bin.published_sha256(LIN)
        c("sin suma para nuestro destino no se sigue", "siguió", "InstallError")
    except InstallError as e:
        c("sin suma para nuestro destino no se sigue", "InstallError", "InstallError")
        c.contains("y se dice cuál falta", str(e), LIN.triple)

    cache = tmpdir("prdrive-runtime-")
    runtime_bin.cache_dir = lambda: cache
    pedidas = red({runtime_bin.SUMS_URL: SUMS, URL_WIN: ARCHIVO_WIN})
    dicho: list[str] = []
    archivo = runtime_bin.ensure_runtime(WIN, progreso=dicho.append)
    c("el archivo comprobado acaba en la caché", archivo, cache / NOMBRE_WIN)
    c("tal cual se descargó", archivo.read_bytes(), ARCHIVO_WIN)
    c("se pidieron las sumas y luego el archivo", pedidas, [runtime_bin.SUMS_URL, URL_WIN])
    c.contains("y se cuenta que la suma cuadró", " ".join(dicho), SUMA_WIN)
    c("la suma queda apuntada al lado, para el sello",
      runtime_bin.recorded_sha256(archivo), SUMA_WIN)

    # Segunda vez: de la caché, sin red.
    pedidas = red({})
    c("la segunda vez sale de la caché", runtime_bin.ensure_runtime(WIN), archivo)
    c("sin pedir nada", pedidas, [])

    # Una caché estropeada (una descarga anterior truncada a mano, un disco que
    # falla) no se da por buena: su suma ya no es la que se apuntó.
    archivo.write_bytes(ARCHIVO_WIN[:100])
    pedidas = red({runtime_bin.SUMS_URL: SUMS, URL_WIN: ARCHIVO_WIN})
    runtime_bin.ensure_runtime(WIN)
    c("una caché que no cuadra se vuelve a descargar", pedidas,
      [runtime_bin.SUMS_URL, URL_WIN])
    c("y queda bien", archivo.read_bytes(), ARCHIVO_WIN)

    archivo.write_bytes(b"roto")
    try:
        runtime_bin.ensure_runtime(WIN, allow_download=False)
        c("sin permiso para descargar, una caché rota no vale", "siguió", "InstallError")
    except InstallError:
        c("sin permiso para descargar, una caché rota no vale", "InstallError", "InstallError")

    # --- y cuando la descarga NO cuadra: no se guarda nada ----------------------
    limpio = tmpdir("prdrive-runtime-malo-")
    runtime_bin.cache_dir = lambda: limpio
    red({runtime_bin.SUMS_URL: SUMS, URL_WIN: ARCHIVO_WIN + b"basura"})
    try:
        runtime_bin.ensure_runtime(WIN)
        c("un archivo que no cuadra con su suma se rechaza", "siguió", "InstallError")
    except InstallError as e:
        c("un archivo que no cuadra con su suma se rechaza", "InstallError", "InstallError")
        c.contains("enseñando la suma esperada", str(e), SUMA_WIN)
        c.contains("y diciendo que no ha guardado nada", str(e), "No se ha guardado nada")
    c("la caché se queda como estaba", list(limpio.iterdir()), [])
finally:
    runtime_bin.fetch = fetch_real
    runtime_bin.cache_dir = cache_real

raise SystemExit(c.report())
