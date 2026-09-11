#!/usr/bin/env python3
"""
El progreso en vivo: leer las estadísticas del log de rclone y contarlas.

Los logs de aquí son de verdad: grabados con rclone v1.75 entre carpetas locales
(`--stats 1s --stats-one-line -v --bwlimit 1M`, para que durasen unos segundos),
con las rutas cambiadas y sin la línea del rclone.conf, que en una pasada de
prdrive no sale porque `--config` va siempre. Cada línea se trata como lo que
es, texto de otro programa: lo que no se entiende no da progreso, y nunca un
error.
"""

import contextlib
import io
import os
import sys
import time
from pathlib import Path

from _harness import Checks, sandbox

import sync
from common import model, progress

c = Checks("progreso en vivo: lector de estadísticas y sync.py")

MiB = 2 ** 20

# --- los logs grabados -----------------------------------------------------------

COPIA = """\
2026/09/11 12:44:36 INFO  : Starting bandwidth limiter at 1Mi Byte/s
2026/09/11 12:44:36 INFO  : sub: Made directory with metadata (mtime=2026-09-11T12:44:35.501766+02:00)
2026/09/11 12:44:37 INFO  :     1.086 MiB / 3.433 MiB, 32%, 0 B/s, ETA -
2026/09/11 12:44:38 INFO  :     2.086 MiB / 3.433 MiB, 61%, 1.086 MiB/s, ETA 1s
2026/09/11 12:44:38 INFO  : b.bin: Copied (new)
2026/09/11 12:44:39 INFO  :     3.069 MiB / 3.433 MiB, 89%, 1.043 MiB/s, ETA 0s
2026/09/11 12:44:39 INFO  : sub/c.bin: Copied (new)
2026/09/11 12:44:39 INFO  : a.bin: Copied (new)
2026/09/11 12:44:39 INFO  : sub: Set directory modification time (using SetModTime)
2026/09/11 12:44:39 INFO  :     3.433 MiB / 3.433 MiB, 100%, 1.023 MiB/s, ETA 0s
"""

# La misma copia otra vez: no queda nada que mover.
NADA = """\
2026/09/11 12:44:39 INFO  : sub: Set directory modification time (using SetModTime)
2026/09/11 12:44:39 INFO  : There was nothing to transfer
2026/09/11 12:44:39 INFO  :           0 B / 0 B, -, 0 B/s, ETA -
"""

BISYNC = """\
2026/09/11 12:45:29 INFO  : Setting --ignore-listing-checksum as neither --checksum nor --compare checksum are set.
2026/09/11 12:45:29 INFO  : Bisyncing with Comparison Settings:
{
	"Modtime": true,
	"Size": true,
	"Checksum": false,
	"SlowHashDetected": true,
	"DownloadHash": false
}
2026/09/11 12:45:29 INFO  : Synching Path1 "E:\\sync-data\\notas\\" with Path2 "nas:/datos/notas/"
2026/09/11 12:45:29 INFO  : Building Path1 and Path2 listings
2026/09/11 12:45:29 INFO  : Path1 checking for diffs
2026/09/11 12:45:29 INFO  : - Path1             File changed: size (larger), time (newer)   - a.bin
2026/09/11 12:45:29 INFO  : Path1:    1 changes:    0 new,    1 modified,    0 deleted
2026/09/11 12:45:29 INFO  : (Modified:    1 newer,    0 older,    1 larger,    0 smaller)
2026/09/11 12:45:29 INFO  : Path2 checking for diffs
2026/09/11 12:45:29 INFO  : Applying changes
2026/09/11 12:45:29 INFO  : - Path1             Queue copy to Path2                         - nas:/datos/notas/a.bin
2026/09/11 12:45:29 INFO  : - Path1             Do queued copies to                         - Path2
2026/09/11 12:45:30 INFO  :     1.027 MiB / 2.384 MiB, 43%, 0 B/s, ETA -
2026/09/11 12:45:31 INFO  :     2.027 MiB / 2.384 MiB, 85%, 1.059 MiB/s, ETA 0s
2026/09/11 12:45:31 INFO  : a.bin: Copied (replaced existing)
2026/09/11 12:45:31 INFO  : Updating listings
2026/09/11 12:45:31 INFO  : Validating listings for Path1 "E:\\sync-data\\notas\\" vs Path2 "nas:/datos/notas/"
2026/09/11 12:45:31 INFO  : Bisync successful
2026/09/11 12:45:31 INFO  :     2.384 MiB / 2.384 MiB, 100%, 1.029 MiB/s, ETA 0s
"""

# Una pasada que aborta: la última estadística llega DESPUÉS del error.
TOPE_BORRADOS = """\
2026/09/11 12:45:32 INFO  : Path1 checking for diffs
2026/09/11 12:45:32 INFO  : - Path1             File was deleted                            - n0.md
2026/09/11 12:45:32 INFO  : - Path1             File was deleted                            - n1.md
2026/09/11 12:45:32 INFO  : Path1:    4 changes:    0 new,    0 modified,    4 deleted
2026/09/11 12:45:32 INFO  : Path2 checking for diffs
2026/09/11 12:45:32 ERROR : Safety abort: too many deletes (>25%, 4 of 8) on Path1 "E:\\sync-data\\notas\\". Run with --force if desired.
2026/09/11 12:45:32 NOTICE: Bisync aborted. Please try again.
2026/09/11 12:45:32 INFO  :           0 B / 0 B, -, 0 B/s, ETA -
2026/09/11 12:45:32 NOTICE: Failed to bisync: too many deletes
"""

# Con `stats-one-line = false` en la pareja: el bloque de varias líneas de
# siempre. Los flags de estadísticas se pueden cambiar, así que esto también se
# lee; y las líneas de cada fichero, que se le parecen, no cuentan.
MULTILINEA = """\
2026/09/11 12:44:45 INFO  :
Transferred:   \t    1.086 MiB / 3.433 MiB, 32%, 0 B/s, ETA -
Checks:                 3 / 3, 100%, Listed 8
Transferred:            0 / 3, 0%
Elapsed time:         0.9s
Transferring:
 *                                         a.bin: 23% / 1.431 MiB, 0 B/s, -
 *                                     sub/c.bin: 29% / 1.144 MiB, 0 B/s, -

2026/09/11 12:44:47 INFO  :
Transferred:   \t    3.433 MiB / 3.433 MiB, 100%, 1.023 MiB/s, ETA 0s
Checks:                 3 / 3, 100%, Listed 8
Transferred:            3 / 3, 100%
Elapsed time:         3.0s
"""

# --- una línea -----------------------------------------------------------------------

p = progress.leer("2026/09/11 12:44:38 INFO  :     2.086 MiB / 3.433 MiB, 61%, "
                  "1.086 MiB/s, ETA 1s")
c("una línea de estadísticas se lee: lo transferido", p.hecho, round(2.086 * MiB))
c("el total", p.total, round(3.433 * MiB))
c("el porcentaje, el de rclone", p.porcentaje, 61)
c("la velocidad, en bytes por segundo", round(p.velocidad), round(1.086 * MiB))
c("y se cuenta en el formato de la ventana", p.texto(),
  "2,1 MB de 3,4 MB · 61 % · 1,1 MB/s")

cero = progress.leer("2026/09/11 12:44:39 INFO  :           0 B / 0 B, -, 0 B/s, ETA -")
c("sin nada que transferir también es una lectura",
  (cero.hecho, cero.total, cero.porcentaje, cero.velocidad), (0, 0, None, 0.0))
c("y sin porcentaje, porque rclone no lo sabe", cero.texto(), "0 B de 0 B · 0 B/s")

c("bytes sueltos, sin prefijo",
  progress.leer("INFO  :   512 B / 2.500 KiB, 20%, 100 B/s, ETA 20s").texto(),
  "512 B de 2,5 KB · 20 % · 100 B/s")
c("y los GB",
  progress.leer("INFO  :   1.500 GiB / 3 GiB, 50%, 10 MiB/s, ETA 2m33s").texto(),
  "1,5 GB de 3,0 GB · 50 % · 10,0 MB/s")

# --- lo que no es una línea de estadísticas -------------------------------------------
for etiqueta, linea in (
        ("línea vacía", ""),
        ("un fichero copiado", "2026/09/11 12:44:38 INFO  : b.bin: Copied (new)"),
        ("un error", "2026/09/11 12:45:32 ERROR : Safety abort: too many deletes "
                     "(>25%, 4 of 8)"),
        ("el JSON de bisync", '\t"Size": true,'),
        ("la cuenta de ficheros", "Transferred:            0 / 3, 0%"),
        ("la de comprobaciones", "Checks:                 3 / 3, 100%, Listed 8"),
        ("la línea de un fichero", " *              a.bin: 23% / 1.431 MiB, 0 B/s, -"),
        ("cortada antes de la velocidad",
         "2026/09/11 12:44:38 INFO  :     2.086 MiB / 3.433 MiB, 61%, 1.08"),
        ("cortada en el porcentaje",
         "2026/09/11 12:44:38 INFO  :     2.086 MiB / 3.433 MiB, 6"),
        ("cortada en el total", "2026/09/11 12:44:38 INFO  :     2.086 MiB / 3.4"),
        ("basura", "\x00\xff MiB / / , %, B/s, ETA"),
):
    c(f"no da progreso: {etiqueta}", progress.leer(linea), None)

# --- un log entero: manda la última ---------------------------------------------------
fin = progress.ultimo(COPIA)
c("copia: la última lectura es la del final", (fin.hecho, fin.total, fin.porcentaje),
  (round(3.433 * MiB), round(3.433 * MiB), 100))
c("bisync: igual", progress.ultimo(BISYNC).texto(), "2,4 MB de 2,4 MB · 100 % · 1,0 MB/s")
c("sin nada que mover: la de cero", progress.ultimo(NADA).texto(), "0 B de 0 B · 0 B/s")
c("un fallo: la última aunque venga después del error y a cero",
  progress.ultimo(TOPE_BORRADOS).texto(), "0 B de 0 B · 0 B/s")
c("el bloque de varias líneas se lee igual", progress.ultimo(MULTILINEA).texto(),
  "3,4 MB de 3,4 MB · 100 % · 1,0 MB/s")
c("un log sin estadísticas no da progreso",
  progress.ultimo("2026/09/11 12:44:39 INFO  : There was nothing to transfer\n"), None)
c("uno vacío tampoco", progress.ultimo(""), None)

# --- el log mientras se escribe -------------------------------------------------------
# rclone escribe y sync.py lee a la vez, así que lo que llega en cada lectura es
# un trozo cualquiera: puede acabar a media línea, o a media letra.
ESPERADAS = [f"  {progress.ETIQUETA} {t}" for t in (
    "1,1 MB de 3,4 MB · 32 % · 0 B/s",
    "2,1 MB de 3,4 MB · 61 % · 1,1 MB/s",
    "3,1 MB de 3,4 MB · 89 % · 1,0 MB/s",
    "3,4 MB de 3,4 MB · 100 % · 1,0 MB/s")]

s = progress.Seguidor()
datos = COPIA.encode("utf-8")
contadas = [linea for i in range(0, len(datos), 7)
            if (linea := s.alimentar(datos[i:i + 7])) is not None]
c("a trozos de 7 bytes, una línea por lectura nueva, en orden", contadas, ESPERADAS)

s = progress.Seguidor()
c("sin nada nuevo, nada", s.alimentar(b""), None)
c("media línea no cuenta todavía",
  s.alimentar(b"2026/09/11 12:44:38 INFO  :     2.086 MiB / 3.433"), None)
c("cuenta al completarse", s.alimentar(b" MiB, 61%, 1.086 MiB/s, ETA 1s\n"), ESPERADAS[1])
c("la misma lectura otra vez no se repite",
  s.alimentar(b"2026/09/11 12:44:39 INFO  :     2.086 MiB / 3.433 MiB, 61%, "
              b"1.086 MiB/s, ETA 1s\n"), None)
c("de varias que llegan juntas, solo la última",
  s.alimentar(COPIA.encode("utf-8")), ESPERADAS[3])

s = progress.Seguidor()
letra = "2026/09/11 12:44:38 INFO  : año/señal.md: Copied (new)\n".encode("utf-8")
corte = letra.index("ñ".encode("utf-8")) + 1          # entre los dos bytes de la ñ
s.alimentar(letra[:corte])
s.alimentar(letra[corte:])
c("una letra partida entre dos lecturas no rompe nada",
  s.alimentar(b"INFO  :     2.086 MiB / 3.433 MiB, 61%, 1.086 MiB/s, ETA 1s\n"),
  ESPERADAS[1])

s = progress.Seguidor()
s.alimentar(b"x" * 200_000)                          # ni un salto de línea
c("un trozo enorme sin saltos no se queda para siempre", len(s._resto) <= 64 * 1024, True)
c("y lo siguiente se lee",
  s.alimentar(b"\nINFO  :     2.086 MiB / 3.433 MiB, 61%, 1.086 MiB/s, ETA 1s\n"),
  ESPERADAS[1])

s = progress.Seguidor()
ruido = os.urandom(50_000)
try:
    for i in range(0, len(ruido), 333):
        s.alimentar(ruido[i:i + 333])
    c("bytes al azar no lanzan nada", True, True)
except Exception as e:                                   # noqa: BLE001
    c("bytes al azar no lanzan nada", repr(e), "nada")


# --- sync.py -------------------------------------------------------------------------
# Los flags: en la capa base, para todos los modos, y se pueden cambiar.
for modo in model.MODES:
    pair = model.parse_config({"defaults": {"remote": "nas"}, "pair": [
        {"name": "x", "local": "sync-data/x", "remote_path": "/R/x", "mode": modo}]}).pairs[0]
    with sandbox():
        cmd, log = sync.build_command(sync.RunContext(binary="RCLONE", env={}),
                                      pair, None, False)
        log.unlink(missing_ok=True)
    c(f"{modo}: rclone escribe las estadísticas en una línea",
      "--stats-one-line" in cmd, True)
    c(f"{modo}: y a menudo", cmd[cmd.index("--stats") + 1] if "--stats" in cmd else None,
      model.BASE_FLAGS["stats"])

pair = model.parse_config({"defaults": {"remote": "nas"}, "pair": [
    {"name": "x", "local": "sync-data/x", "remote_path": "/R/x",
     "flags": {"stats": "10s", "stats-one-line": False}}]}).pairs[0]
with sandbox():
    cmd, log = sync.build_command(sync.RunContext(binary="RCLONE", env={}), pair, None, False)
    log.unlink(missing_ok=True)
c("la pareja puede cambiar el intervalo (y va una sola vez)",
  (cmd.count("--stats"), cmd[cmd.index("--stats") + 1]), (1, "10s"))
c("y quitar la línea única", "--stats-one-line" in cmd, False)


# Un rclone de mentira que escribe su log poco a poco, como el de verdad.
FALSO_RCLONE = r"""
import sys, time
log = sys.argv[sys.argv.index("--log-file") + 1]
lineas = sys.argv[1].split("|")
for linea in lineas:
    with open(log, "a", encoding="utf-8") as f:
        f.write(linea + "\n")
    time.sleep(float(sys.argv[2]))
sys.exit(int(sys.argv[3]))
"""


def ejecutar(lineas, pausa=0.0, rc=0, logfile=None):
    """sync.execute() con el rclone de mentira. Devuelve (rc, salida).

    Con `logfile`, sync.py sigue ese y el rclone de mentira escribe en otro."""
    escrito = sync.temp_log("progreso")
    seguido = logfile or escrito
    cmd = [sys.executable, "-c", FALSO_RCLONE, "|".join(lineas), str(pausa), str(rc),
           "--log-file", str(escrito)]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        codigo = sync.execute(sync.RunContext(binary=sys.executable, env={}), cmd, seguido)
    escrito.unlink(missing_ok=True)
    return codigo, buf.getvalue()


def progresos(salida):
    return [l for l in salida.splitlines() if l.strip().startswith(progress.ETIQUETA)]


sync.PROGRESS_POLL_S = 0.1
ESTADISTICAS = [l for l in COPIA.splitlines() if progress.leer(l)]

with sandbox():
    rc, salida = ejecutar(ESTADISTICAS, pausa=0.6)
    c("mientras rclone corre, cada lectura sale en la salida", progresos(salida), ESPERADAS)
    c("sin cambiar el código de salida", rc, 0)

with sandbox():
    # Todo de golpe y fuera: solo la lectura final, que es la que vale.
    rc, salida = ejecutar(ESTADISTICAS, pausa=0.0)
    c("si acaba antes de mirar, sale la última", progresos(salida)[-1:], ESPERADAS[-1:])

with sandbox():
    rc, salida = ejecutar(["2026/09/11 12:44:39 INFO  : There was nothing to transfer"],
                          rc=3)
    c("sin estadísticas no hay progreso", progresos(salida), [])
    c("y la pasada sigue igual", rc, 3)

with sandbox() as root:
    # Un log que no se puede abrir (aquí, porque es una carpeta): sin progreso,
    # y la pasada ni se entera.
    (root / "carpeta.log").mkdir()
    rc, salida = ejecutar(ESTADISTICAS, logfile=root / "carpeta.log")
    c("sin log legible no hay progreso", progresos(salida), [])
    c("ni se cae la pasada", rc, 0)
    c("ni se escupe un traceback", "Traceback" in salida, False)


class LectorRoto:
    def alimentar(self, datos):
        raise RuntimeError("un fallo del lector")


with sandbox():
    # Un fallo del propio lector es un fallo del progreso, no de la pasada: ni
    # la corta ni llena la ventana con un traceback.
    real, progress.Seguidor = progress.Seguidor, LectorRoto
    try:
        rc, salida = ejecutar(ESTADISTICAS, pausa=0.3)
    finally:
        progress.Seguidor = real
    c("si el lector falla, la pasada sigue", rc, 0)
    c("sin traceback en la salida", "Traceback" in salida, False)


# Al fallar se enseña la cola del log. Con una estadística cada pocos segundos,
# una pasada que se queda pensando llenaría esas 15 líneas de números y el error
# quedaría fuera: la cola se enseña sin ellas.
with sandbox() as root:
    log = root / "fallo.log"
    log.write_text(
        "2026/09/11 12:45:32 ERROR : Safety abort: too many deletes (>25%, 4 of 8)\n"
        + "".join(f"2026/09/11 12:45:{i:02d} INFO  :     0 B / 0 B, -, 0 B/s, ETA -\n"
                  for i in range(30))
        + "2026/09/11 12:45:59 NOTICE: Failed to bisync: too many deletes\n",
        encoding="utf-8")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        sync.print_log_tail(log)
    c.contains("la cola del log conserva el error aunque detrás haya estadísticas",
               buf.getvalue(), "Safety abort")
    c.contains("y el final", buf.getvalue(), "Failed to bisync")
    c("pero no las estadísticas", "0 B / 0 B" in buf.getvalue(), False)


# sync.py escribe a una tubería cuando lo lanza la ventana, y Python la llena por
# bloques: sin esto el progreso llegaría todo junto al final.
with sandbox():
    model.CONFIG_FILE.write_text(
        '[defaults]\nremote = "nas"\n\n[[pair]]\nname = "x"\nlocal = "sync-data/x"\n'
        'remote_path = "/R/x"\n', encoding="utf-8")
    tuberia = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    argv, sys.argv = sys.argv, ["sync.py", "--list"]
    original, sys.stdout = sys.stdout, tuberia
    try:
        sync.main()
        linea_a_linea = tuberia.line_buffering
    finally:
        sys.stdout, sys.argv = original, argv
    c("sync.py escribe su salida línea a línea aunque sea a una tubería",
      linea_a_linea, True)

sys.exit(c.report())
