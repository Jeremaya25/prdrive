#!/usr/bin/env python3
"""La copia ejecutable de rclone (`model.ejecutable()`): privada y con nombre por contenido.

En exFAT no hay bit de ejecución, así que en POSIX el rclone del dispositivo se
copia a un sitio donde sí se puede poner. Ese sitio es la caché del usuario
(`<XDG_CACHE_HOME o ~/.cache>/prdrive/`), no un nombre fijo en `/tmp`:
- La carpeta es solo del usuario (0o700), y se rechaza una que sea de otro, un
  enlace o un fichero.
- La copia se llama `rclone-<tamaño>-<mtime_ns>`: dos rclone distintos (el
  agente atiende raíces con builds distintos) no se pisan, y si ya está no se
  copia otra vez.
- Se escribe en un temporal de esa carpeta y se coloca con `os.replace`: lo que
  alguien haya plantado en su sitio (un enlace) se sustituye, nunca se sigue.
- Las copias de otras versiones y los temporales de un copiado interrumpido se
  barren solo si llevan más de un día sin tocarse; la copia que se reutiliza
  renueva su fecha, para que otra raíz no barra la que un sync.py largo sigue
  usando.

Todo va a temporales (la caché con `XDG_CACHE_HOME`, el rclone de mentira en
otra carpeta). Es de POSIX: en Windows se ejecuta donde está.
"""

import os
import shutil
import stat
import time
from pathlib import Path

from _harness import Checks, tmpdir

from common import model

c = Checks("rclone portable: la copia ejecutable es privada y se nombra por su contenido")

DIA = 24 * 3600
"""Un día en segundos."""


def falso_rclone(contenido: bytes, modo: int = 0o644) -> Path:
    """Un `rclone` de mentira, en su propia carpeta y sin bit de ejecución."""
    ruta = tmpdir("prdrive-rclone-origen-") / "rclone"
    ruta.write_bytes(contenido)
    ruta.chmod(modo)
    return ruta


if os.name == "nt":
    # En Windows se ejecuta donde está: no hay copia que probar.
    binario = falso_rclone(b"MZ falso")
    c("en Windows se ejecuta donde está", model.ejecutable(binario), str(binario))
    print("  (saltado) la copia ejecutable de rclone: solo en POSIX")
    raise SystemExit(c.report())


def cache_nueva() -> Path:
    """Apunta `XDG_CACHE_HOME` a una carpeta nueva y la devuelve."""
    cache = tmpdir("prdrive-cache-")
    os.environ["XDG_CACHE_HOME"] = str(cache)
    return cache


def contenido(carpeta: Path) -> list[str] | None:
    """Los nombres que hay en la carpeta, o `None` si ni existe."""
    return sorted(p.name for p in carpeta.iterdir()) if carpeta.is_dir() else None


def envejecer(ruta: Path, dias: float) -> None:
    """Pone la fecha de la ruta (sin seguir un enlace) `dias` días atrás."""
    cuando = time.time() - dias * DIA
    os.utime(ruta, (cuando, cuando), follow_symlinks=False)


FUENTE = b"#!/bin/sh\necho rclone de mentira\n" * 20
"""Lo que contiene el rclone de mentira."""

# --- Dónde va la copia y cómo queda
cache = cache_nueva()
binario = falso_rclone(FUENTE)
origen = binario.stat()
copia = Path(model.ejecutable(binario))
nombre = f"rclone-{origen.st_size}-{origen.st_mtime_ns}"

c("la copia va a la caché del usuario", copia, cache / "prdrive" / nombre)
c("con bit de ejecución", os.access(copia, os.X_OK), True)
c("la copia es solo del usuario (0o700)", stat.S_IMODE(copia.stat().st_mode), 0o700)
c("su carpeta es solo del usuario (0o700)",
  stat.S_IMODE(copia.parent.stat().st_mode), 0o700)
c("el contenido de la copia es el del rclone original", copia.read_bytes(), FUENTE)
c("no queda ningún temporal", contenido(copia.parent), [nombre])
c("el original sigue sin bit de ejecución", os.access(binario, os.X_OK), False)

# --- La segunda vez no copia
envejecer(copia, 1 / 24)  # si volviera a copiar, su fecha sería la de ahora
antes = copia.stat()
otra = Path(model.ejecutable(binario))
c("la segunda vez no copia otra vez",
  (otra, otra.stat().st_mtime_ns), (copia, antes.st_mtime_ns))
c("  ni cambia de fichero", otra.stat().st_ino, antes.st_ino)

# --- Un rclone distinto tiene su propia copia
distinto = falso_rclone(FUENTE + b"# otro build\n")
copia2 = Path(model.ejecutable(distinto))
c("un rclone distinto tiene otra copia", copia2 != copia and copia2.is_file(), True)
c("  y la primera sigue ahí", copia.is_file(), True)

# --- Uno que ya se puede ejecutar se devuelve tal cual
cache = cache_nueva()
ejecutable = falso_rclone(FUENTE, 0o755)
c("un rclone ejecutable se devuelve donde está y sin copiar",
  (model.ejecutable(ejecutable), (cache / "prdrive").exists()), (str(ejecutable), False))

# --- Lo plantado en su sitio se sustituye, no se sigue
cache = cache_nueva()
binario = falso_rclone(FUENTE)
origen = binario.stat()
sitio = cache / "prdrive" / f"rclone-{origen.st_size}-{origen.st_mtime_ns}"
sitio.parent.mkdir(mode=0o700)
victima = tmpdir("prdrive-victima-") / "ajeno"
# Del mismo tamaño que la copia: una comprobación que siguiera el enlace la daría por buena.
intocable = b"X" * len(FUENTE)
victima.write_bytes(intocable)
victima.chmod(0o600)
os.symlink(victima, sitio)
copia = Path(model.ejecutable(binario))
c("un enlace plantado en su sitio se sustituye, no se sigue",
  (copia, copia.is_symlink(), victima.read_bytes() == intocable,
   stat.S_IMODE(victima.stat().st_mode)),
  (sitio, False, True, 0o600))
c("  y en su sitio queda la copia de verdad", (copia.read_bytes(), os.access(copia, os.X_OK)),
  (FUENTE, True))

# Un enlace roto en su sitio tampoco se sigue.
cache = cache_nueva()
binario = falso_rclone(FUENTE)
origen = binario.stat()
sitio = cache / "prdrive" / f"rclone-{origen.st_size}-{origen.st_mtime_ns}"
sitio.parent.mkdir(mode=0o700)
roto = tmpdir("prdrive-victima-") / "no-existe"
os.symlink(roto, sitio)
copia = Path(model.ejecutable(binario))
c("un enlace roto en su sitio se sustituye, y su destino no se crea",
  (copia.is_symlink(), copia.read_bytes(), roto.exists()), (False, FUENTE, False))

# Un fichero del tamaño justo pero que no es regular (aquí, una carpeta) tampoco vale.
cache = cache_nueva()
binario = falso_rclone(FUENTE)
origen = binario.stat()
sitio = cache / "prdrive" / f"rclone-{origen.st_size}-{origen.st_mtime_ns}"
sitio.mkdir(parents=True, mode=0o700)
try:
    model.ejecutable(binario)
    lanzo = False
except OSError:
    lanzo = True
c("una carpeta en el sitio de la copia no se da por buena: falla, no la devuelve",
  (lanzo, contenido(sitio.parent)), (True, [sitio.name]))

# --- La carpeta de la caché
cache = cache_nueva()
binario = falso_rclone(FUENTE)
carpeta = cache / "prdrive"
carpeta.mkdir(mode=0o755)
carpeta.chmod(0o755)  # el umask de quien corre el test podría haberla cerrado
copia = Path(model.ejecutable(binario))
c("una carpeta con permisos de más se aprieta a 0o700",
  stat.S_IMODE(carpeta.stat().st_mode), 0o700)

cache = cache_nueva()
binario = falso_rclone(FUENTE)
(cache / "prdrive").mkdir(mode=0o700)
getuid_real = os.getuid
os.getuid = lambda: getuid_real() + 1  # la carpeta pasa a ser «de otro»
try:
    try:
        model.ejecutable(binario)
        msg = None
    except OSError as e:
        msg = str(e)
finally:
    os.getuid = getuid_real
c("una carpeta de otro usuario se rechaza", msg is not None, True)
c("  con un mensaje en español", "no es una carpeta de este usuario" in (msg or ""), True)
c("  y no se copia nada en ella", contenido(cache / "prdrive"), [])

cache = cache_nueva()
binario = falso_rclone(FUENTE)
ajena = tmpdir("prdrive-ajena-")
os.symlink(ajena, cache / "prdrive")
try:
    model.ejecutable(binario)
    msg = None
except OSError as e:
    msg = str(e)
c("una carpeta que es un enlace se rechaza, y no se copia a donde apunta",
  (msg is not None, contenido(ajena)), (True, []))

cache = cache_nueva()
binario = falso_rclone(FUENTE)
(cache / "prdrive").write_bytes(b"un fichero")
try:
    model.ejecutable(binario)
    msg = None
except OSError as e:
    msg = str(e)
c("una caché que es un fichero se rechaza", msg is not None, True)

# --- Si el copiado falla no queda un temporal
cache = cache_nueva()
binario = falso_rclone(FUENTE)
copiar_real = shutil.copyfileobj


def copiar_y_fallar(entrada, salida, *args, **kwargs):
    """Sustituye a `shutil.copyfileobj`: escribe un trozo y falla, como un disco lleno."""
    salida.write(b"un trozo")
    raise OSError(28, "No space left on device")


shutil.copyfileobj = copiar_y_fallar
try:
    try:
        model.ejecutable(binario)
        lanzo = False
    except OSError:
        lanzo = True
finally:
    shutil.copyfileobj = copiar_real
c("un copiado que falla da el error", lanzo, True)
c("  y no deja ni copia ni temporal", contenido(cache / "prdrive"), [])

# --- Las copias de otras versiones
cache = cache_nueva()
binario = falso_rclone(FUENTE)
carpeta = cache / "prdrive"
carpeta.mkdir(mode=0o700)
victima = tmpdir("prdrive-victima-") / "ajeno"
victima.write_bytes(b"no me toques")
viejo, tmp_viejo, fresco, enlace, nota, carpeta_vieja = (
    carpeta / "rclone-1-1", carpeta / ".rclone-interrumpido", carpeta / "rclone-2-2",
    carpeta / "rclone-3-3", carpeta / "notas.txt", carpeta / "rclone-4-4")
for ruta in (viejo, tmp_viejo, fresco, nota):
    ruta.write_bytes(b"x")
os.symlink(victima, enlace)
carpeta_vieja.mkdir()
for ruta in (viejo, tmp_viejo, enlace, nota, carpeta_vieja):
    envejecer(ruta, 3)
envejecer(victima, 3)  # el enlace es viejo y su destino también: solo debe irse el enlace

copia = Path(model.ejecutable(binario))
c("una copia vieja de otra versión se barre", viejo.exists(), False)
c("el resto de un copiado interrumpido, viejo, se barre", tmp_viejo.exists(), False)
c("una copia reciente de otra versión se respeta: puede estar en uso", fresco.exists(), True)
c("un enlace viejo se quita sin seguirlo", (os.path.lexists(enlace), victima.read_bytes()),
  (False, b"no me toques"))
c("lo que no es una copia no se toca", nota.exists(), True)
c("una carpeta con nombre de copia no estorba ni se toca", carpeta_vieja.is_dir(), True)
c("la copia nueva sigue ahí tras el barrido", copia.is_file(), True)

# --- Lo que se sigue usando no parece abandonado
# La fecha de una copia es la de cuando se hizo: sin renovarla, la copia de la
# que un sync.py largo saca su rclone parecería vieja y otra raíz la barrería.
cache = cache_nueva()
binario_a = falso_rclone(FUENTE)
copia_a = Path(model.ejecutable(binario_a))

envejecer(copia_a, 6 / 24)  # dentro de las 12 horas
antes = copia_a.stat().st_mtime_ns
Path(model.ejecutable(binario_a))
c("una copia que se reutiliza dentro de las 12 horas no se toca",
  copia_a.stat().st_mtime_ns, antes)

envejecer(copia_a, 3)  # hecha hace tres días y todavía en uso
c("una copia vieja que se reutiliza es la misma", Path(model.ejecutable(binario_a)), copia_a)
c("  y renueva su fecha", time.time() - copia_a.stat().st_mtime < 60, True)

# Otra raíz con otro build copia el suyo y barre: la que se usa se queda.
binario_b = falso_rclone(FUENTE + b"# otro build\n")
copia_b = Path(model.ejecutable(binario_b))
c("la copia que se sigue usando sobrevive a la que hace otra raíz",
  (copia_a.is_file(), copia_b.is_file()), (True, True))

# La misma edad sin que nadie la use sí se barre.
binario_c = falso_rclone(FUENTE + b"# un tercero\n")
copia_c = Path(model.ejecutable(binario_c))
envejecer(copia_c, 3)
Path(model.ejecutable(falso_rclone(FUENTE + b"# un cuarto\n")))
c("  en cambio la que nadie reutiliza, igual de vieja, sí se barre",
  (copia_a.is_file(), copia_c.exists()), (True, False))

# Si no se puede renovar la fecha, se devuelve la copia igualmente.
envejecer(copia_a, 3)
utime_real = os.utime


def utime_sin_permiso(*args, **kwargs):
    """Sustituye a `os.utime`: no deja cambiar la fecha."""
    raise PermissionError(1, "Operation not permitted")


os.utime = utime_sin_permiso
try:
    try:
        devuelta = Path(model.ejecutable(binario_a))
        error = None
    except OSError as e:
        devuelta, error = None, e
finally:
    os.utime = utime_real
c("si no puede renovar la fecha, no falla y devuelve la copia", (devuelta, error), (copia_a, None))

raise SystemExit(c.report())
