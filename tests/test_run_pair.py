#!/usr/bin/env python3
"""
Los caminos de run_pair(), con la ejecución de rclone simulada.

Aquí viven los invariantes de seguridad del proyecto: que una pareja sin baseline
aprobado se SALTA en vez de resincronizarse sola, y que un baseline con la carpeta
local ausente ABORTA en vez de crearla vacía (una carpeta vacía se lee como "han
borrado todo").
"""

import contextlib
import hashlib
import io
import sys
from pathlib import Path

from _harness import Checks, sandbox

import sync
from common import bisync, model

c = Checks("run_pair(): control de flujo e invariantes")

DEF = {"remote": "nas", "exclude": ["**/.git/**"]}
BI = {"name": "bi", "local": "sync-data/bi", "remote_path": "/R/bi", "mode": "bisync"}
UP = {"name": "up", "local": "sync-data/up", "remote_path": "/R/up", "mode": "up"}
MIR = {"name": "mir", "local": "sync-data/mir", "remote_path": "/R/mir", "mode": "up-mirror"}
PREFIJO = "prefijo-de-prueba"


def correr(raw, *, listings=False, make_local=True, rc_seq=(0,), **opciones):
    """Ejecuta run_pair sobre una pareja en un sandbox. Devuelve (rc, salida, ordenes)."""
    pair = model.parse_config({"defaults": DEF, "pair": [raw]}).pairs[0]
    if make_local:
        pair.local_abs.mkdir(parents=True, exist_ok=True)
    if listings:
        pair.workdir.mkdir(parents=True, exist_ok=True)
        for sufijo in (bisync.PATH1_SUFFIX, bisync.PATH2_SUFFIX):
            (pair.workdir / f"{PREFIJO}{sufijo}").write_text("x", encoding="utf-8")
        # El .md5 que habría dejado un --resync previo: sin él, los filtros
        # cuentan como "nuevos" y la pareja se saltaría antes de llegar al caso.
        ffile = bisync.filters_file_for(pair)
        if ffile:
            Path(str(ffile) + ".md5").write_text(
                hashlib.md5(ffile.read_bytes()).hexdigest(), encoding="utf-8")

    ordenes: list[list[str]] = []
    codigos = iter(rc_seq)

    def execute_simulado(ctx, cmd, logfile=None):
        ordenes.append(cmd)
        rc = next(codigos, rc_seq[-1])
        for i, arg in enumerate(cmd):          # rclone escribe su log; se emula
            if arg == "--log-file":
                Path(cmd[i + 1]).write_text("simulado\n", encoding="utf-8")
        return rc

    original, sync.execute = sync.execute, execute_simulado
    try:
        ctx = sync.RunContext(binary="RCLONE", env={}, **opciones)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = sync.run_pair(ctx, pair)
        return rc, buf.getvalue(), ordenes
    finally:
        sync.execute = original


with sandbox():
    rc, salida, ordenes = correr(BI)
    c("sin baseline y sin aprobar: se salta", rc, sync.SKIPPED)
    c("sin baseline y sin aprobar: no ejecuta rclone", ordenes, [])
    c.contains("sin baseline y sin aprobar: lo dice", salida, "Saltada")

with sandbox():
    rc, salida, ordenes = correr(BI, resync_approved=True)
    c("sin baseline y aprobado: ejecuta", rc, 0)
    c("sin baseline y aprobado: con --resync", "--resync" in ordenes[0], True)

with sandbox():
    rc, salida, ordenes = correr(BI, listings=True)
    c("con baseline: ejecuta", rc, 0)
    c("con baseline: sin --resync", "--resync" in ordenes[0], False)

with sandbox():
    # INVARIANTE: baseline presente y carpeta local ausente. Crearla vacía haría
    # que bisync viese "han borrado todo".
    rc, salida, ordenes = correr(BI, listings=True, make_local=False)
    c("INVARIANTE baseline sin carpeta local: aborta con rc=2", rc, 2)
    c("INVARIANTE baseline sin carpeta local: no ejecuta rclone", ordenes, [])
    c.contains("INVARIANTE baseline sin carpeta local: lo explica", salida,
               "no se crea vacía a propósito")

with sandbox():
    rc, _, ordenes = correr(BI, listings=True, force_resync=True, resync_approved=True)
    c("--resync forzado", (rc, "--resync" in ordenes[0]), (0, True))

with sandbox():
    rc, _, ordenes = correr(BI, resync_approved=True, dry_run=True)
    c("dry-run: se lo pasa a rclone", "--dry-run" in ordenes[0], True)

with sandbox():
    rc, salida, _ = correr(BI, listings=True, rc_seq=(1,))
    c("fallo de rclone: propaga el código", rc, 1)
    c.contains("fallo de rclone: conserva el log", salida, "Log: ")

with sandbox() as root:
    rc, salida, _ = correr(UP, make_local=False)
    c("up: crea la carpeta local que falta", rc, 0)
    c("up: la carpeta existe ya", (root / "sync-data" / "up").is_dir(), True)

with sandbox():
    rc, _, ordenes = correr(MIR)
    c("up-mirror: usa el subcomando sync", ordenes[0][1], "sync")
    c("up-mirror: trae su tope de borrados", "--max-delete" in ordenes[0], True)

with sandbox():
    rc, salida, _ = correr(UP, keep_logs=True)
    c("keep_logs conserva el log de una pasada correcta", "Log: " in salida, True)

with sandbox():
    rc, _, ordenes = correr({**BI, "include": ["*.md"], "exclude": ["tmp/**"]}, listings=True)
    c("bisync usa fichero de filtros", "--filters-file" in ordenes[0], True)
    c("bisync no duplica reglas con --include", "--include" in ordenes[0], False)

# --- la consola de rclone acaba dentro del log ------------------------------------
# Aquí NO se simula execute(): se ejecuta un proceso de verdad, porque lo que se
# comprueba es justamente el trozo que el simulador se salta. El caso real es un
# flag que rclone rechaza antes de instalar el --log-file (conflict-resolve =
# "new" en vez de "newer"): el log quedaba de 0 bytes y el único mensaje útil se
# perdía.
ESCUPIR = ("import sys; "
           "sys.stderr.write('Error: invalid argument \\\"new\\\" for "
           "\\\"--conflict-resolve\\\" flag: invalid choice \\\"new\\\"\\n'); "
           "sys.exit(2)")

with sandbox():
    log = sync.temp_log("arranque")
    ctx = sync.RunContext(binary=sys.executable, env={})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = sync.execute(ctx, [sys.executable, "-c", ESCUPIR], log)
    texto = log.read_text(encoding="utf-8")
    c("capturar la consola no cambia el código de salida", rc, 2)
    c.contains("lo que rclone saca por consola acaba en el log", texto,
               'invalid argument "new"')
    c.contains("y marcado como lo que es", texto, sync.DIRECT_OUTPUT_HEADER)
    c("y explain_failure ya tiene algo que reconocer",
      any(aguja in texto for aguja, _ in sync.KNOWN_ERRORS), True)
    log.unlink(missing_ok=True)

with sandbox():
    # Lo que rclone sí registró va primero y no se pisa.
    log = sync.temp_log("mezcla")
    log.write_text("2026/01/01 00:00:00 INFO  : linea de rclone\n", encoding="utf-8")
    sync.append_output(log, "Error: unknown flag: --inventado\n")
    texto = log.read_text(encoding="utf-8")
    c("el log de rclone se conserva al añadir su consola",
      texto.startswith("2026/01/01"), True)
    c.contains("y la consola se añade detrás", texto, "--inventado")
    log.unlink(missing_ok=True)

with sandbox():
    log = sync.temp_log("vacio")
    sync.append_output(log, "   \n")
    c("una consola vacía no ensucia el log", log.stat().st_size, 0)
    log.unlink(missing_ok=True)

# --- la ayuda de rclone no puede colarse en el log -------------------------------
# Ante un flag malo rclone escribe el error y detrás la ayuda entera (12 KB). Si
# entrara tal cual, `explain_failure` encontraría ahí dentro '--max-delete' y
# explicaría un fallo que no ha ocurrido: un diagnóstico falso es peor que
# ninguno. Este es el trozo de ayuda real, recortado.
AYUDA = """Error: invalid argument "new" for "--conflict-resolve" flag: invalid choice "new"
Usage:
  rclone bisync remote1:path1 remote2:path2 [flags]

Flags:
      --check-access             Ensure expected RCLONE_TEST files are found
      --max-delete PERCENT       Safety check on maximum files deleted
      --resync                   Performs the resync run

Use "rclone [command] --help" for more information about a command.

2026/01/01 00:00:00 NOTICE: Fatal error: invalid argument "new" for "--conflict-resolve" flag
"""

with sandbox():
    log = sync.temp_log("ayuda")
    sync.append_output(log, AYUDA)
    texto = log.read_text(encoding="utf-8")
    c("el error se conserva", 'invalid argument "new"' in texto, True)
    c("y el 'Fatal error' de rclone también", "Fatal error" in texto, True)
    c("pero el volcado de ayuda no entra", "--max-delete" in texto, False)
    c("ni la cabecera de uso", "Usage:" in texto, False)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        sync.explain_failure(log)
    c.contains("y se explica por el flag, no por los borrados",
               buf.getvalue(), "rechaza el VALOR de un flag")
    c("no se explica como un exceso de borrados",
      "borrados permitidos" in buf.getvalue(), False)
    log.unlink(missing_ok=True)

c("sin ayuda que quitar, el texto se respeta entero",
  sync.strip_usage("Error: unknown flag: --x\n"), "Error: unknown flag: --x\n")

sys.exit(c.report())
