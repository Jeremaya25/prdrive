#!/usr/bin/env python3
"""Los flags efectivos de una pareja con su capa de origen, y la orden de rclone que salen de ellos.

Lo que hay que sujetar aquí:
- **Una sola cascada.** `Pair.flags` (lo que lee `sync.py`) y la tabla del
  editor salen de `model.flags_efectivos()`: base < modo < `[defaults.flags]` <
  `[pair.flags]`. Si la tabla tuviera su propia fusión, enseñaría unos flags y
  rclone recibiría otros.
- **Una sola orden.** `sync.build_command()` y la vista previa montan la orden
  con `orden.tramos()`; lo que pone el programa en cada pasada (`--config`,
  `--log-file`, `--workdir`, `--resync`…) sale marcado como suyo.
- **Nada se mueve sin querer.** Las órdenes de abajo fijan `build_command()`
  argumento por argumento: el reparto en tramos no puede mover ni uno, y lo
  que entra en la capa base (`modify-window`) sale en todas.
"""

import sys
from pathlib import Path

from _harness import Checks, sandbox

from common import model, orden
import sync

c = Checks("flags efectivos y orden de rclone (common/model.py, common/orden.py)")

FILTROS = Path("FILTROS/pareja.txt")
FILTROS_TXT = str(FILTROS)
"""Cómo llega ese fichero a la orden: con la barra del sistema (`\\` en Windows)."""

PROGRAMA = model.REGLA_SIN_PROGRAMA.partition(" ")[2]
"""El patrón con el que una pareja de la raíz deja fuera la carpeta del programa."""

BISYNC = {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas",
          "mode": "bisync"}


def pareja(raw, defaults=None):
    """La pareja ya resuelta, con el remote `nas` y el `combine` `disp`."""
    data = {"defaults": {"remote": "nas", "device_remote": "disp", **(defaults or {})},
            "pair": [raw]}
    return model.parse_config(data).pairs[0]


# 1. la cascada, con su origen

efectivos = model.flags_efectivos(
    model.MODES["bisync"], {"transfers": 4, "max-delete": 50},
    {"max-delete": 10, "checksum": True})
por_nombre = {f.nombre: (f.valor, f.origen) for f in efectivos}
c("lo de siempre viene de la base", por_nombre["verbose"], (True, model.ORIGEN_BASE))
c("lo del modo, del modo", por_nombre["conflict-resolve"], ("newer", model.ORIGEN_MODO))
c("[defaults] se ve como tal", por_nombre["transfers"], (4, model.ORIGEN_DEFAULTS))
c("lo propio de la pareja, como suyo", por_nombre["checksum"], (True, model.ORIGEN_PAREJA))
c("y la pareja gana a [defaults] y al modo",
  por_nombre["max-delete"], (10, model.ORIGEN_PAREJA))
c("cada flag sale una vez", len(efectivos), len(por_nombre))
c("un modo sin flags propios solo trae la base",
  {f.origen for f in model.flags_efectivos(model.MODES["up"], None, None)},
  {model.ORIGEN_BASE})
c("y sin modo tampoco hay capa de modo",
  {f.origen for f in model.flags_efectivos(None, {"transfers": 4}, None)},
  {model.ORIGEN_BASE, model.ORIGEN_DEFAULTS})

# Lo que lee sync.py es exactamente esa cascada, con las claves como están escritas.
for nombre_modo in model.MODES:
    raw = {**BISYNC, "mode": nombre_modo, "flags": {"max_delete": 5, "stats": "10s"}}
    p = pareja(raw, {"flags": {"transfers": 4}})
    esperados = model.flags_efectivos(model.MODES[nombre_modo], {"transfers": 4},
                                      raw["flags"])
    c(f"Pair.flags es la cascada ({nombre_modo})",
      dict(p.flags), {f.nombre: f.valor for f in esperados})
    c(f"y Pair.origen_flags dice de dónde sale cada uno ({nombre_modo})",
      dict(p.origen_flags), {f.nombre: f.origen for f in esperados})

# Un flag escrito de dos maneras (`max_delete` y `max-delete`) llega a rclone dos
# veces, como siempre, y gana el último. La cascada no lo funde por nombre normalizado
# porque eso cambiaría lo que ya recibe rclone; la tabla del editor es quien lo junta.
doble = pareja({**BISYNC, "mode": "up-mirror", "flags": {"max_delete": 5}})
c("las dos grafías se conservan en Pair.flags",
  [k for k in doble.flags if k.replace("_", "-") == "max-delete"],
  ["max-delete", "max_delete"])


# 2. la orden: lo que producía build_command antes de partirlo

CONF, LOG, TRABAJO = "<conf>", "<log>", "<workdir>"
"""Los tres sitios que cambian de un equipo a otro, para comparar con la misma orden."""

CASOS = {
    "bisync": (
        BISYNC, {}, dict(resync=False),
        ['rclone', 'bisync', 'disp:sync-data/notas', 'nas:/R/notas', '--filters-file',
         FILTROS_TXT, '--verbose', '--create-empty-src-dirs', '--stats', '2s',
         '--stats-one-line', '--modify-window', '2s', '--conflict-resolve', 'newer', '--conflict-suffix',
         'conflicto-dispositivo,conflicto-remoto', '--max-delete', '25', '--resilient',
         '--recover', '--max-lock', '2m', '--config', CONF, '--log-file', LOG, '--workdir',
         TRABAJO]),
    "bisync-resync-mode": (
        {**BISYNC, "flags": {"resync-mode": "newer", "transfers": 8}}, {},
        dict(resync=False),
        ['rclone', 'bisync', 'disp:sync-data/notas', 'nas:/R/notas', '--filters-file',
         FILTROS_TXT, '--verbose', '--create-empty-src-dirs', '--stats', '2s',
         '--stats-one-line', '--modify-window', '2s', '--conflict-resolve', 'newer', '--conflict-suffix',
         'conflicto-dispositivo,conflicto-remoto', '--max-delete', '25', '--resilient',
         '--recover', '--max-lock', '2m', '--transfers', '8', '--config', CONF,
         '--log-file', LOG, '--workdir', TRABAJO]),
    "bisync-resync": (
        {**BISYNC, "flags": {"resync-mode": "newer"}}, {}, dict(resync=True),
        ['rclone', 'bisync', 'disp:sync-data/notas', 'nas:/R/notas', '--filters-file',
         FILTROS_TXT, '--verbose', '--create-empty-src-dirs', '--stats', '2s',
         '--stats-one-line', '--modify-window', '2s', '--conflict-resolve', 'newer', '--conflict-suffix',
         'conflicto-dispositivo,conflicto-remoto', '--max-delete', '25', '--resilient',
         '--recover', '--max-lock', '2m', '--resync-mode', 'newer', '--config', CONF,
         '--log-file', LOG, '--workdir', TRABAJO, '--resync']),
    "bisync-versiones": (
        {**BISYNC, "versions": True}, {}, dict(resync=False),
        ['rclone', 'bisync', 'disp:sync-data/notas', 'nas:/R/notas', '--filters-file',
         FILTROS_TXT, '--verbose', '--create-empty-src-dirs', '--stats', '2s',
         '--stats-one-line', '--modify-window', '2s', '--conflict-resolve', 'newer', '--conflict-suffix',
         'conflicto-dispositivo,conflicto-remoto', '--max-delete', '25', '--resilient',
         '--recover', '--max-lock', '2m', '--config', CONF, '--log-file', LOG, '--workdir',
         TRABAJO, '--backup-dir1', 'disp:sync-data/notas/.prversions', '--backup-dir2',
         'nas:/R/notas/.prversions', '--suffix', '~SELLO', '--suffix-keep-extension',
         '--conflict-loser', 'delete']),
    "bisync-versiones-propio": (
        {**BISYNC, "versions": True, "flags": {"conflict-loser": "num"}}, {},
        dict(resync=False),
        ['rclone', 'bisync', 'disp:sync-data/notas', 'nas:/R/notas', '--filters-file',
         FILTROS_TXT, '--verbose', '--create-empty-src-dirs', '--stats', '2s',
         '--stats-one-line', '--modify-window', '2s', '--conflict-resolve', 'newer', '--conflict-suffix',
         'conflicto-dispositivo,conflicto-remoto', '--max-delete', '25', '--resilient',
         '--recover', '--max-lock', '2m', '--conflict-loser', 'num', '--config', CONF,
         '--log-file', LOG, '--workdir', TRABAJO, '--backup-dir1',
         'disp:sync-data/notas/.prversions', '--backup-dir2', 'nas:/R/notas/.prversions',
         '--suffix', '~SELLO', '--suffix-keep-extension']),
    "up-filtros-extra": (
        {"name": "subida", "local": "sync-data/subida", "remote_path": "/R/subida",
         "mode": "up", "include": ["*.md"], "exclude": ["tmp/**"],
         "extra_flags": ["--bwlimit", "8M"]},
        {"flags": {"transfers": 4}, "exclude": ["*.bak"]}, dict(resync=False),
        ['rclone', 'copy', 'disp:sync-data/subida', 'nas:/R/subida', '--include', '*.md',
         '--exclude', '*.bak', '--exclude', 'tmp/**', '--verbose', '--create-empty-src-dirs',
         '--stats', '2s', '--stats-one-line', '--modify-window', '2s', '--transfers', '4', '--config', CONF,
         '--log-file', LOG, '--bwlimit', '8M']),
    "down-mirror-simulacro": (
        {"name": "espejo", "local": "sync-data/espejo", "remote_path": "/R/espejo",
         "mode": "down-mirror", "flags": {"max_delete": 5, "verbose": False}},
        {"flags": {"transfers": 4}}, dict(resync=False, dry=True),
        ['rclone', 'sync', 'nas:/R/espejo', 'disp:sync-data/espejo',
         '--create-empty-src-dirs', '--stats', '2s', '--stats-one-line', '--modify-window', '2s', '--max-delete', '50',
         '--transfers', '4', '--max-delete', '5', '--config', CONF, '--log-file', LOG,
         '--dry-run']),
    "raiz": (
        {"name": "todo", "local": ".", "remote_path": "/R/todo", "mode": "up-mirror"}, {},
        dict(resync=False),
        ['rclone', 'sync', 'disp:raiz', 'nas:/R/todo', '--exclude', PROGRAMA,
         '--verbose', '--create-empty-src-dirs', '--stats', '2s', '--stats-one-line', '--modify-window', '2s',
         '--max-delete', '50', '--config', CONF, '--log-file', LOG]),
}
"""Por caso: la pareja, sus `[defaults]`, cómo se lanza y la orden de siempre."""


def normalizada(cmd, p, log):
    """La orden con los tres sitios que dependen del equipo cambiados por su nombre."""
    cambios = {str(log): LOG, str(model.RCLONE_CONF): CONF, str(p.workdir): TRABAJO}
    return [cambios.get(t, t) for t in cmd]


with sandbox():
    for nombre, (raw, defaults, opts, esperada) in CASOS.items():
        p = pareja(raw, defaults)
        ctx = sync.RunContext(binary="rclone", env={}, sello="~SELLO",
                              dry_run=opts.get("dry", False))
        ffile = FILTROS if p.wants_filters_file else None
        cmd, log = sync.build_command(ctx, p, ffile, opts["resync"])
        c(f"build_command no cambia ({nombre})", normalizada(cmd, p, log), esperada)

        # La vista previa monta la misma orden con el mismo constructor.
        tramos = orden.tramos(p, binario="rclone", filtros=ffile, config=model.RCLONE_CONF,
                              logfile=LOG, simulacro=ctx.dry_run, resync=opts["resync"],
                              sello="~SELLO")
        plana = [a for t in tramos for a in t.args]
        c(f"los tramos, juntos, son la orden ({nombre})",
          [{str(model.RCLONE_CONF): CONF, str(p.workdir): TRABAJO}.get(t, t) for t in plana],
          esperada)
        c(f"y orden_rclone() también ({nombre})",
          orden.orden_rclone(p, binario="rclone", filtros=ffile, config=model.RCLONE_CONF,
                             logfile=LOG, simulacro=ctx.dry_run, resync=opts["resync"],
                             sello="~SELLO"), plana)

    # 3. quién pone cada trozo
    p = pareja({**BISYNC, "versions": True, "flags": {"transfers": 8}},
               {"flags": {"checksum": True}})
    tramos = orden.tramos(p, binario="rclone", filtros=FILTROS, config=model.RCLONE_CONF,
                          logfile=LOG, simulacro=True, resync=True, sello="~SELLO")
    origen_de = {t.nombre: t.origen for t in tramos if t.nombre}
    c("la orden misma la pone el programa",
      tramos[0], orden.Tramo(("rclone", "bisync", "disp:sync-data/notas", "nas:/R/notas"),
                             model.ORIGEN_PRDRIVE))
    c("el fichero de filtros, también",
      [t.args for t in tramos if t.origen == model.ORIGEN_PRDRIVE and not t.nombre][1],
      ("--filters-file", FILTROS_TXT))
    for flag in ("config", "log-file", "workdir", "dry-run", "resync", "backup-dir1",
                 "backup-dir2", "suffix", "suffix-keep-extension", "conflict-loser"):
        c(f"--{flag} lo pone el programa", origen_de.get(flag), model.ORIGEN_PRDRIVE)
    c("lo de la base sigue siendo de la base", origen_de["verbose"], model.ORIGEN_BASE)
    c("lo del modo, del modo", origen_de["max-lock"], model.ORIGEN_MODO)
    c("lo de [defaults], de [defaults]", origen_de["checksum"], model.ORIGEN_DEFAULTS)
    c("lo de la pareja, de la pareja", origen_de["transfers"], model.ORIGEN_PAREJA)

    # Un conflict-loser propio gana al que pone el versionado: entonces no lo pone el programa.
    propio = pareja({**BISYNC, "versions": True, "flags": {"conflict-loser": "num"}})
    tramos = orden.tramos(propio, binario="rclone", filtros=FILTROS,
                          config=model.RCLONE_CONF, logfile=LOG, simulacro=False,
                          resync=False, sello="~SELLO")
    c("un conflict-loser propio sigue siendo de la pareja",
      [t.origen for t in tramos if t.nombre == "conflict-loser"], [model.ORIGEN_PAREJA])

    # Sin fichero de filtros, los patrones salen como --include/--exclude, de la pareja;
    # lo que añade el código (la raíz) lo pone el programa.
    raiz = pareja({"name": "todo", "local": ".", "remote_path": "/R/todo", "mode": "up",
                   "include": ["*.md"], "extra_flags": ["--bwlimit", "8M"]})
    tramos = orden.tramos(raiz, binario="rclone", filtros=None, config=model.RCLONE_CONF,
                          logfile=LOG)
    c("las reglas del código las pone el programa",
      [(t.args, t.origen) for t in tramos if t.args[:1] == ("--exclude",)],
      [(("--exclude", PROGRAMA), model.ORIGEN_PRDRIVE)])
    c("los patrones de la pareja, de sus patrones",
      [(t.args, t.origen) for t in tramos if t.args[:1] == ("--include",)],
      [(("--include", "*.md"), model.ORIGEN_PATRONES)])
    c("y los argumentos extra, extra",
      [(t.args, t.origen) for t in tramos if t.origen == model.ORIGEN_EXTRA],
      [(("--bwlimit",), model.ORIGEN_EXTRA), (("8M",), model.ORIGEN_EXTRA)])

sys.exit(c.report())
