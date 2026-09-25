#!/usr/bin/env python3
"""
El log de un fallo cuando el dispositivo ya no está (#36).

Desenchufar la unidad a mitad de pasada hace fallar a rclone, como debe; lo que
fallaba después era `sync.py`, al guardar el log en `.prdrive/logs/` de un
dispositivo que ya no estaba: `PermissionError: [WinError 21] El dispositivo no
está listo` sin capturar, y la ventana enseñaba el traceback en vez de la cola
del log y su explicación.

Aquí el dispositivo «desaparece» de las dos maneras en que puede hacerlo a esas
alturas: logs/ que no se deja crear, y un movimiento que falla a medias. Y
detrás, las parejas que quedaban por pasar: tampoco pueden acabar en un
traceback.
"""

import contextlib
import errno
import hashlib
import io
import shutil
import sys
from pathlib import Path

from _harness import Checks, sandbox

import sync
from common import bisync, historial, model, results, store

c = Checks("sync.py: el log de un fallo sin dispositivo (#36)")

DEF = {"remote": "nas"}
BI = {"name": "bi", "local": "sync-data/bi", "remote_path": "/R/bi", "mode": "bisync"}
UP = {"name": "up", "local": "otra/up", "remote_path": "/R/up", "mode": "up"}

# Lo que escribió rclone en la prueba H3, con una línea más al final: la de un
# `KNOWN_ERRORS` cualquiera, para ver que la explicación sigue saliendo. Qué
# explicación sea da igual aquí; lo que se comprueba es de qué fichero se lee.
LOG = """\
2026/09/24 10:12:01 INFO  : Synching Path1 "F:\\sync-data\\prueba\\" with Path2 "nas:/datos/prueba/"
2026/09/24 10:12:03 ERROR : grande.bin: Failed to copy: The device is not ready.
2026/09/24 10:12:03 ERROR : Bisync critical error: The device is not ready.
2026/09/24 10:12:03 ERROR : Bisync aborted. Must run --resync to recover.
2026/09/24 10:12:03 ERROR : Failed to create file system for "disp:sync-data/prueba": The device is not ready.
"""
EXPLICACION = dict(sync.KNOWN_ERRORS)["Failed to create file system"]


def sin_carpeta_de_logs(root: Path) -> None:
    """logs/ cuelga de un FICHERO: su mkdir lanza OSError, como con la unidad
    fuera (en Linux NotADirectoryError; en Windows era [WinError 21])."""
    (root / "fuera").write_text("no soy una carpeta", encoding="utf-8")
    model.LOG_DIR = root / "fuera" / "logs"


def capturar(funcion, *args):
    """(lo que devuelve o la excepción que lanza, lo que ha impreso)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            devuelto = funcion(*args)
        except OSError as e:
            devuelto = e
    return devuelto, buf.getvalue()


def temporal_con(texto: str) -> Path:
    tmp = sync.temp_log("bi")
    tmp.write_text(texto, encoding="utf-8")
    return tmp


# --- logs/ no se deja crear --------------------------------------------------------
with sandbox() as root:
    sin_carpeta_de_logs(root)
    tmp = temporal_con(LOG)
    saved, salida = capturar(sync.dispose_log, "bi", tmp, 7, False)
    c("sin logs/, dispose_log no lanza", isinstance(saved, OSError), False)
    c("y devuelve el temporal, que es donde está el log", saved, tmp)
    c("el temporal sigue ahí, entero", tmp.read_text(encoding="utf-8"), LOG)
    c.contains("lo dice en una línea", salida,
               "[bi] AVISO: no he podido guardar el log en el dispositivo")
    c.contains("con la ruta del temporal", salida, f"está en {tmp}")
    c("una sola línea", salida.count("\n"), 1)

    if isinstance(saved, Path):
        _, salida = capturar(sync.print_log_tail, saved)
        c.contains("la cola se lee del temporal", salida, "Must run --resync to recover")
        _, salida = capturar(sync.explain_failure, saved)
        c.contains("y la explicación también", salida, EXPLICACION)
    tmp.unlink(missing_ok=True)

# Con --keep-logs y una pasada buena, lo mismo: el log que se pedía guardar se
# queda en el temporal y se dice, en vez de tumbar una pasada que ha ido bien.
with sandbox() as root:
    sin_carpeta_de_logs(root)
    tmp = temporal_con("todo bien\n")
    saved, salida = capturar(sync.dispose_log, "bi", tmp, 0, True)
    c("keep_logs sin logs/: tampoco lanza, y queda en el temporal",
      (saved, tmp.exists()), (tmp, True))
    tmp.unlink(missing_ok=True)

# --- logs/ se crea, pero el movimiento falla a medias ---------------------------------
# Entre dos unidades, shutil.move copia y borra el origen al final. Aquí la copia
# se corta a la mitad, que es lo que pasa si la unidad se va mientras tanto.
MITAD = len(LOG) // 2


def mover_a_medias(origen, destino, *args, **kwargs):
    Path(destino).write_text(Path(origen).read_text(encoding="utf-8")[:MITAD],
                             encoding="utf-8")
    raise OSError(errno.EIO, "El dispositivo no está listo")


with sandbox():
    tmp = temporal_con(LOG)
    original, shutil.move = shutil.move, mover_a_medias
    try:
        saved, salida = capturar(sync.dispose_log, "bi", tmp, 7, False)
    finally:
        shutil.move = original
    c("movimiento a medias: no lanza", isinstance(saved, OSError), False)
    c("devuelve el temporal", saved, tmp)
    c("que sigue entero", tmp.read_text(encoding="utf-8"), LOG)
    c("y en logs/ no queda el log cortado", sorted(model.LOG_DIR.iterdir()), [])
    c.contains("la línea da la ruta real", salida, f"está en {tmp}")
    c.contains("y el motivo", salida, "El dispositivo no está listo")
    if isinstance(saved, Path):
        _, salida = capturar(sync.explain_failure, saved)
        c.contains("la explicación sale del temporal", salida, EXPLICACION)
    tmp.unlink(missing_ok=True)

# --- con el dispositivo en su sitio, nada cambia ------------------------------------
with sandbox():
    tmp = temporal_con(LOG)
    saved, salida = capturar(sync.dispose_log, "bi", tmp, 7, False)
    c("un fallo normal deja el log en logs/",
      isinstance(saved, Path) and saved.parent == model.LOG_DIR, True)
    c("y se lo lleva del temporal", tmp.exists(), False)
    c("sin aviso de ninguna clase", salida, "")

with sandbox():
    tmp = temporal_con("todo bien\n")
    saved, _ = capturar(sync.dispose_log, "bi", tmp, 0, True)
    c("keep_logs sigue guardando en logs/",
      isinstance(saved, Path) and saved.parent == model.LOG_DIR, True)

with sandbox():
    tmp = temporal_con("todo bien\n")
    saved, _ = capturar(sync.dispose_log, "bi", tmp, 0, False)
    c("sin keep_logs, una pasada buena no deja log", (saved, tmp.exists()), (None, False))

# --- un log que no se deja leer ----------------------------------------------------
# Guardado en el dispositivo, que se va justo después: un volumen de VeraCrypt
# desenchufado sin expulsar acepta escrituras en caché y luego no deja leer. Una
# carpeta en su lugar da el mismo OSError al leer.
with sandbox() as root:
    ilegible = root / "ilegible.log"
    ilegible.mkdir()
    devuelto, salida = capturar(sync.print_log_tail, ilegible)
    c("un log ilegible no tumba la cola", isinstance(devuelto, OSError), False)
    c.contains("y lo dice", salida, "no he podido leer")
    devuelto, salida = capturar(sync.explain_failure, ilegible)
    c("ni la explicación, que calla", (isinstance(devuelto, OSError), salida), (False, ""))


# --- la pasada entera: la pareja que falla y las de detrás ----------------------------
def correr_todas(pares, rc_seq):
    """run_all con rclone simulado. Devuelve (config, rc, salida, órdenes, logs)."""
    config = model.parse_config({"defaults": DEF, "pair": pares})
    ordenes, logs = [], []
    codigos = iter(rc_seq)

    def execute_simulado(ctx, cmd, logfile=None):
        ordenes.append(cmd)
        logs.append(logfile)
        logfile.write_text(LOG, encoding="utf-8")
        return next(codigos, rc_seq[-1])

    original, sync.execute = sync.execute, execute_simulado
    try:
        ctx = sync.RunContext(binary="RCLONE", env={})
        devuelto, salida = capturar(sync.run_all, ctx, list(config.pairs))
        return config, devuelto, salida, ordenes, logs
    finally:
        sync.execute = original


def con_baseline(config):
    """La pareja bisync con su baseline, para que no se salte por --resync."""
    pair = config.pairs[0]
    pair.local_abs.mkdir(parents=True, exist_ok=True)
    pair.workdir.mkdir(parents=True, exist_ok=True)
    for sufijo in (bisync.PATH1_SUFFIX, bisync.PATH2_SUFFIX):
        (pair.workdir / f"prefijo{sufijo}").write_text("x", encoding="utf-8")
    ffile = bisync.filters_file_for(pair)
    if ffile:
        Path(str(ffile) + ".md5").write_text(
            hashlib.md5(ffile.read_bytes()).hexdigest(), encoding="utf-8")


with sandbox() as root:
    con_baseline(model.parse_config({"defaults": DEF, "pair": [BI]}))
    sin_carpeta_de_logs(root)
    # La carpeta local de la segunda no se puede crear: cuelga de un fichero,
    # como cualquier ruta de una unidad que ya no está.
    (root / "otra").write_text("no soy una carpeta", encoding="utf-8")
    config, rc, salida, ordenes, logs = correr_todas([BI, UP], rc_seq=(7,))

    c("la pasada no lanza", isinstance(rc, OSError), False)
    c("y acaba como un fallo", rc, 1)
    tmp = logs[0]
    c.contains("la pareja que falla dice dónde ha quedado su log", salida,
               "[bi] AVISO: no he podido guardar el log en el dispositivo")
    c.contains("su línea de fallo apunta al temporal", salida,
               f"[bi] FALLÓ (código 7). Log: {tmp}")
    c.contains("la cola sale igual", salida, "Must run --resync to recover")
    c.contains("y la explicación también", salida, EXPLICACION)
    c("el temporal sigue ahí", tmp.exists(), True)

    c("la de detrás no llega a lanzar rclone", len(ordenes), 1)
    c.contains("y falla con una línea", salida, "[up] FALLÓ: ")
    c.contains("el resumen se escribe", salida, "Hecho. 0/2 parejas OK, 2 con errores.")

    fallos = {f.pareja: f for f in results.fallos(config)}
    c("las dos quedan apuntadas como fallo",
      sorted((n, f.codigo) for n, f in fallos.items()), [("bi", 7), ("up", 1)])
    # Y en el diario de pasadas (#20), que es lo que dice desde cuándo falla: la
    # de detrás no llegó a tener reloj, así que consta sin duración.
    c("las dos entran en el diario, la de detrás sin duración",
      [(p.pareja, p.codigo, p.segundos is None) for p in historial.leer()],
      [("bi", 7, False), ("up", 1, True)])
    apuntado = store.read_json(results.ruta_estado()).get("parejas", {}).get("bi", {})
    c("sin apuntar como log uno que no está en logs/",
      apuntado.get("log", "(sin apuntar)"), None)
    tmp.unlink(missing_ok=True)

sys.exit(c.report())
