#!/usr/bin/env python3
"""El Tk con Xft del runtime de Linux: bajarlo, comprobarlo, ponerlo y elegirlo.

El Tk que trae el Python de python-build-standalone para Linux está compilado
sin Xft (solo fuentes de mapa de bits de X11, sin suavizar). Uno compilado con
Xft (`.github/workflows/tk-xft.yml`) viaja al lado, en `lib/tk-xft/`, y `ui`
lo precarga antes de tkinter. Aquí se comprueba el contrato:

- solo lo llevan los runtimes de Linux, y su paquete se comprueba contra el
  SHA-256 de `common/pins.py`, no contra nada que venga con él;
- uno que no se puede bajar o no cuadra NO para una instalación: el runtime va
  con el de serie y su sello no lo anota;
- `extract()` lo pone en `lib/tk-xft/` y anota `tk = <tag>` en el sello, y el
  sello que se espera (`stamp_text`) es el mismo que se escribe;
- de su paquete no se acepta nada que no sea lo suyo;
- un runtime de Linux sin él sale como componente pendiente;
- y `ui.tk_con_xft()` no hace nada, ni falla, donde no toca.

`runtime_bin.fetch()` y `cache_dir()` se sustituyen: ningún test habla con
GitHub ni ensucia la caché de nadie.
"""

from __future__ import annotations

import hashlib
import io
import sys
import tarfile

from _harness import Checks, tmpdir

from common import components, pins
from install import InstallError, descarga, runtime_bin

c = Checks("el Tk con Xft del runtime de Linux")

WIN = pins.plataforma("windows-x64")
LIN = pins.plataforma("linux-x64")
ARM = pins.plataforma("linux-arm64")
MM = ".".join(pins.PYTHON_VERSION.split(".")[:2])


def tar_gz(miembros) -> bytes:
    """Devuelve un tar.gz con esos miembros: `(nombre, bytes)`."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for nombre, dato in miembros:
            info = tarfile.TarInfo(nombre)
            info.size = len(dato)
            tf.addfile(info, io.BytesIO(dato))
    return buf.getvalue()


PAQUETE = tar_gz([("./libtcl9tk9.0.so", b"\x7fELF tk con xft"),
                  ("./LICENSE-tk.txt", b"licencia")])
SUMA = hashlib.sha256(PAQUETE).hexdigest()
# `bin/python3` es un enlace en el de verdad; aquí basta un fichero con ese
# nombre, que es lo que `extract()` exige.
RUNTIME = tar_gz([("python/bin/python3", b"\x7fELF interprete"),
                  (f"python/lib/python{MM}/os.py", b"# os"),
                  ("python/lib/libtcl9tk9.0.so", b"\x7fELF tk de serie")])

# 1. qué plataformas lo llevan y de dónde sale
c("lo llevan los de Linux", (runtime_bin.lleva_tk(LIN), runtime_bin.lleva_tk(ARM)),
  (True, True))
c("y no el de Windows, que dibuja la letra con GDI", runtime_bin.lleva_tk(WIN), False)
c("el paquete se llama por su tag y su arquitectura",
  (runtime_bin.tk_archive_name(LIN), runtime_bin.tk_archive_name(ARM)),
  (f"{pins.TK_XFT_TAG}-x86_64-linux.tar.gz", f"{pins.TK_XFT_TAG}-aarch64-linux.tar.gz"))
c("y se baja de su release, la del tag fijado",
  runtime_bin.tk_url(LIN),
  f"{pins.TK_XFT_BASE_URL}/{pins.TK_XFT_TAG}/{pins.TK_XFT_TAG}-x86_64-linux.tar.gz")
c("las dos arquitecturas tienen su SHA-256 fijado",
  all(len(pins.TK_XFT_SHA256.get(a, "")) == 64 for a in ("x86_64", "aarch64")), True)
c("y Windows no pide ninguno", runtime_bin.ensure_tk(WIN), None)

# 2. bajarlo: se comprueba contra pins, y lo que falla no para nada
sumas_reales = dict(pins.TK_XFT_SHA256)
fetch_real, cache_real = runtime_bin.fetch, runtime_bin.cache_dir
esperar_real = descarga.esperar
descarga.esperar = lambda _s: None
try:
    pins.TK_XFT_SHA256["x86_64"] = SUMA
    cache = tmpdir("prdrive-tk-cache-")
    runtime_bin.cache_dir = lambda: cache
    pedidas: list[str] = []
    runtime_bin.fetch = lambda url, timeout=None: pedidas.append(url) or PAQUETE
    dicho: list[str] = []
    c("sin nada en la caché no hay Tk con Xft", runtime_bin.tk_xft(LIN), None)
    bajado = runtime_bin.ensure_tk(LIN, dicho.append)
    c("se baja de su URL", pedidas, [runtime_bin.tk_url(LIN)])
    c("y queda en la caché, comprobado", runtime_bin.tk_xft(LIN), bajado)
    pedidas.clear()
    runtime_bin.ensure_tk(LIN)
    c("la segunda vez no se baja", pedidas, [])

    # Lo que no cuadra no se guarda, y no revienta.
    otra = tmpdir("prdrive-tk-otra-")
    runtime_bin.cache_dir = lambda: otra
    runtime_bin.fetch = lambda url, timeout=None: PAQUETE + b"cambiado"
    dicho.clear()
    c("uno que no es el fijado no se usa", runtime_bin.ensure_tk(LIN, dicho.append), None)
    c("  ni se guarda", list(otra.iterdir()), [])
    c("  y se dice con qué se queda", any("Tk de serie" in d for d in dicho), True)

    def sin_red(url, timeout=None):
        """Una red caída."""
        raise OSError("sin red")
    runtime_bin.fetch = sin_red
    dicho.clear()
    c("sin red tampoco revienta", runtime_bin.ensure_tk(LIN, dicho.append), None)
    c("  y lo dice", any("No he podido descargar" in d for d in dicho), True)
    c("sin permiso para bajar, no se baja", runtime_bin.ensure_tk(LIN, allow_download=False),
      None)

    # 3. extraer: con él en la caché, va a lib/tk-xft/ y el sello lo anota
    runtime_bin.cache_dir = lambda: cache
    archivo = tmpdir() / "runtime.tar.gz"
    archivo.write_bytes(RUNTIME)
    destino = tmpdir() / "linux-x64"
    runtime_bin.extract(archivo, destino, LIN, sha256="abc")
    c("el Tk con Xft queda en lib/tk-xft/",
      (destino / "lib" / "tk-xft" / "libtcl9tk9.0.so").read_bytes(), b"\x7fELF tk con xft")
    c("  con su licencia", (destino / "lib" / "tk-xft" / "LICENSE-tk.txt").is_file(), True)
    c("el de serie sigue en su sitio: es el de un equipo sin libXft",
      (destino / "lib" / "libtcl9tk9.0.so").read_bytes(), b"\x7fELF tk de serie")
    sello = (destino / runtime_bin.STAMP).read_text(encoding="utf-8")
    c("el sello lo anota", f"tk = {pins.TK_XFT_TAG}" in sello, True)
    c("y es el que se espera", sello, runtime_bin.stamp_text(LIN, "abc"))

    # Sin él en la caché, el runtime se pone igual, con el de serie.
    runtime_bin.cache_dir = lambda: otra
    sin = tmpdir() / "linux-x64"
    runtime_bin.extract(archivo, sin, LIN, sha256="abc")
    c("sin él, el runtime se pone igual", (sin / "bin" / "python3").is_file(), True)
    c("  sin lib/tk-xft/", (sin / "lib" / "tk-xft").exists(), False)
    sello = (sin / runtime_bin.STAMP).read_text(encoding="utf-8")
    c("  y sin anotarlo", "tk =" in sello, False)
    c("  y también es el que se espera", sello, runtime_bin.stamp_text(LIN, "abc"))

    # De su paquete no se acepta nada más que lo suyo.
    malo = tar_gz([("./libtcl9tk9.0.so", b"x"), ("../../fuera", b"x")])
    pins.TK_XFT_SHA256["x86_64"] = hashlib.sha256(malo).hexdigest()
    (otra / runtime_bin.tk_archive_name(LIN)).write_bytes(malo)
    roto = tmpdir() / "linux-x64"
    try:
        runtime_bin.extract(archivo, roto, LIN, sha256="abc")
        c("un paquete con algo de más se rechaza", "siguió", "InstallError")
    except InstallError:
        c("un paquete con algo de más se rechaza", "InstallError", "InstallError")
    c("  sin escribir nada suyo", (roto / "lib" / "tk-xft" / "libtcl9tk9.0.so").exists(),
      False)
    c("  ni el sello: sin sello no cuenta como instalado",
      (roto / runtime_bin.STAMP).exists(), False)
finally:
    pins.TK_XFT_SHA256.clear()
    pins.TK_XFT_SHA256.update(sumas_reales)
    runtime_bin.fetch, runtime_bin.cache_dir = fetch_real, cache_real
    descarga.esperar = esperar_real

# 4. un runtime de Linux sin él es un componente pendiente
app = tmpdir("prdrive-tk-app-")


def poner(plat, sello: str) -> None:
    """Deja un runtime con ese sello en el dispositivo de mentira."""
    d = components.runtime_dir(app, plat)
    (d / plat.interprete).parent.mkdir(parents=True, exist_ok=True)
    (d / plat.interprete).write_bytes(b"x")        # sin intérprete no hay runtime
    (d / components.RUNTIME_STAMP).write_text(sello, encoding="utf-8")


poner(LIN, runtime_bin.stamp_text(LIN, "s", con_tk=False))
pendiente = components.python_pendiente(app, LIN)
c("Linux sin el Tk con Xft está pendiente", pendiente is not None, True)
c("  y dice qué le falta", "Tk con Xft" in (pendiente.deberia if pendiente else ""), True)
poner(LIN, runtime_bin.stamp_text(LIN, "s", con_tk=True))
c("con él, al día", components.python_pendiente(app, LIN), None)
poner(WIN, runtime_bin.stamp_text(WIN, "s"))
c("Windows no lo necesita para estar al día", components.python_pendiente(app, WIN), None)

# 5. elegirlo al arrancar: no hace nada, ni falla, donde no toca
import ui  # noqa: E402

c("sin la biblioteca no carga nada", ui.tk_con_xft(tmpdir("prdrive-tk-sin-")), False)
basura = tmpdir("prdrive-tk-basura-")
(basura / ui.TK_CON_XFT).parent.mkdir(parents=True)
(basura / ui.TK_CON_XFT).write_bytes(b"no es una biblioteca")
c("una que no carga (sin libXft) se calla y queda la de serie",
  ui.tk_con_xft(basura), False)
try:
    import tkinter  # noqa: F401
    c("con tkinter ya cargado no se toca", ui.tk_con_xft(basura), False)
except ImportError:
    print("  (saltado) este Python no tiene tkinter")
if not sys.platform.startswith("linux"):
    print("  (saltado) la precarga solo es de Linux")

sys.exit(c.report())
