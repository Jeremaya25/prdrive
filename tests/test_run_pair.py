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

DEF = {"remote": "synology", "exclude": ["**/.git/**"]}
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

    def execute_simulado(ctx, cmd):
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

sys.exit(c.report())
