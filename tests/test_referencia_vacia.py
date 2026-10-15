#!/usr/bin/env python3
"""Una pareja bisync que se inicializó con los dos lados vacíos (#113).

`checkListing()` de rclone (`cmd/bisync/listing.go`, v1.75.1) aborta toda pasada
que no sea un `--resync` si el listado anterior de un lado no tiene ni un
fichero ni una carpeta: «Empty prior Path1 listing». Una pareja inicializada
sobre dos carpetas vacías dejaba así los dos listados, y fallaba para siempre.

`sync._bisync_preflight()` la rehace con un `--resync` también desatendido,
porque no queda nada en la referencia que proteger; pero solo si los DOS
listados están vacíos y la carpeta local existe: si falta la carpeta, o si solo
uno está vacío, sigue mandando lo de siempre (abortar con 2, o dejar que rclone
pare la pasada).
"""

import contextlib
import hashlib
import io
from pathlib import Path

from _harness import Checks, sandbox

import sync
from common import bisync, model, parte, revision

c = Checks("pareja inicializada vacía: la referencia vacía se rehace sola")

DEF = {"remote": "nas", "exclude": ["**/.git/**"]}
BI = {"name": "bi", "local": "sync-data/bi", "remote_path": "/R/bi", "mode": "bisync"}

CABECERA = "# bisync listing v1 from 2026-10-12T10:00:00.000000000+0200\n"
FICHERO = '-       12 - - 2026-10-12T10:00:00.000000000+0200 "primero.txt"\n'
CARPETA = 'd        0 - - 2026-10-12T10:00:00.000000000+0200 "subcarpeta"\n'
"""Las líneas tal como las escribe rclone (`lineFormat`, `cmd/bisync/listing.go`)."""


def pareja():
    """Devuelve la pareja `bi` del sandbox, con su carpeta local creada."""
    par = model.parse_config({"defaults": DEF, "pair": [BI]}).pairs[0]
    par.local_abs.mkdir(parents=True, exist_ok=True)
    return par


def listado(par, sufijo, prefijo=None):
    """Devuelve la ruta de un listado del baseline, con el nombre que rclone espera.

    Con `prefijo`, el de un baseline que guardó otra pareja o este mismo con otros extremos.
    """
    return par.workdir / ((prefijo or bisync.expected_prefix(par)) + sufijo)


def claves(hallazgos):
    """Devuelve las claves de los hallazgos, sin repetir y ordenadas."""
    return sorted({h.clave for h in hallazgos})


def con_resync(ordenes):
    """Indica si la primera orden de rclone lleva `--resync` (`False` si no hubo ninguna)."""
    return bool(ordenes) and "--resync" in ordenes[0]


def baseline(par, uno=CABECERA, otro=CABECERA, prefijo=None):
    """Deja en el workdir los dos listados con ese contenido, y el `.md5` de los filtros.

    Sin el `.md5` de un `--resync` previo, los filtros cuentan como nuevos y la
    pareja pediría un resync por ellos antes de llegar al caso.
    """
    par.workdir.mkdir(parents=True, exist_ok=True)
    listado(par, bisync.PATH1_SUFFIX, prefijo).write_text(uno, encoding="utf-8")
    listado(par, bisync.PATH2_SUFFIX, prefijo).write_text(otro, encoding="utf-8")
    ffile = bisync.filters_file_for(par)
    if ffile:
        Path(str(ffile) + ".md5").write_text(
            hashlib.md5(ffile.read_bytes()).hexdigest(), encoding="utf-8")


def pasar(par, al_ejecutar=None, **opciones):
    """Ejecuta `run_pair` con rclone simulado. Devuelve (rc, salida, órdenes, parte)."""
    ordenes: list[list[str]] = []

    def execute_simulado(ctx, cmd, logfile=None):
        ordenes.append(cmd)
        for i, arg in enumerate(cmd):
            if arg == "--log-file":
                Path(cmd[i + 1]).write_text("simulado\n", encoding="utf-8")
        if al_ejecutar is not None:
            al_ejecutar()
        return 0

    original, sync.execute = sync.execute, execute_simulado
    try:
        ctx = sync.RunContext(binary="RCLONE", env={}, **opciones)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = sync.run_pair(ctx, par)
        return rc, buf.getvalue(), ordenes, parte.leer(buf.getvalue()).get(par.name)
    finally:
        sync.execute = original


# --- bisync.referencia_vacia(): lo que rclone cuenta como listado vacío -------------

with sandbox():
    par = pareja()
    c("sin workdir (nunca sincronizada): no hay referencia", bisync.referencia_vacia(par), False)

    baseline(par)
    c("los dos con solo la cabecera: vacía", bisync.referencia_vacia(par), True)

    baseline(par, "", "")
    c("los dos de cero bytes: vacía (rclone también los lee sin una línea)",
      bisync.referencia_vacia(par), True)

    baseline(par, CABECERA + "\n", CABECERA + "# otro comentario\n")
    c("líneas en blanco y comentarios `#` no cuentan", bisync.referencia_vacia(par), True)

    baseline(par, CABECERA + FICHERO, CABECERA + FICHERO)
    c("con un fichero en los dos: no está vacía", bisync.referencia_vacia(par), False)

    baseline(par, CABECERA + CARPETA, CABECERA + CARPETA)
    c("con solo una carpeta (create-empty-src-dirs): no está vacía",
      bisync.referencia_vacia(par), False)

    baseline(par, CABECERA + FICHERO, CABECERA)
    c("solo el path2 vacío: no se toca", bisync.referencia_vacia(par), False)

    baseline(par, CABECERA, CABECERA + CARPETA)
    c("solo el path1 vacío: no se toca", bisync.referencia_vacia(par), False)

    baseline(par, CABECERA + "esto no es un listado\n", CABECERA)
    c("una línea que rclone ignoraría por rota cuenta como contenido: no se adivina",
      bisync.referencia_vacia(par), False)

    baseline(par, CABECERA.rstrip("\n"), CABECERA)
    c("solo una cabecera sin salto de línea sigue siendo solo una cabecera",
      bisync.referencia_vacia(par), True)

    baseline(par)
    listado(par, bisync.PATH2_SUFFIX).unlink()
    c("falta un listado: no hay baseline, no hay referencia vacía",
      bisync.referencia_vacia(par), False)

    baseline(par)
    listado(par, bisync.PATH2_SUFFIX).unlink()
    listado(par, bisync.PATH2_SUFFIX).mkdir()
    c("un listado que no se puede leer: no se adivina", bisync.referencia_vacia(par), False)


# --- la pasada --------------------------------------------------------------------

with sandbox():
    par = pareja()
    baseline(par)
    rc, salida, ordenes, _ = pasar(par)
    c("dos listados vacíos y carpeta local: la pasada sale bien", rc, 0)
    c("dos listados vacíos, sin aprobar: rclone va con --resync",
      con_resync(ordenes), True)
    c("dos listados vacíos: solo se lanza rclone una vez", len(ordenes), 1)
    c.contains("la pasada dice por qué rehace la referencia", salida,
               "la referencia está vacía: se rehace")
    c("no se dice que se salte", "Saltada" in salida, False)

with sandbox():
    par = pareja()
    baseline(par)
    rc, _, ordenes, _ = pasar(par, resync_approved=False, force_resync=False)
    c("sin aprobación ni --resync pedido (agente, --auto): también se rehace",
      (rc, con_resync(ordenes)), (0, True))

with sandbox():
    par = pareja()
    baseline(par)
    rc, _, ordenes, _ = pasar(par, dry_run=True)
    c("simulacro: rclone lleva --resync y --dry-run",
      (con_resync(ordenes), "--dry-run" in ordenes[0]), (True, True))

with sandbox():
    par = pareja()
    baseline(par, CABECERA + FICHERO, CABECERA + FICHERO)
    rc, salida, ordenes, _ = pasar(par)
    c("con un fichero en la referencia: sin cambios, sin --resync",
      (rc, con_resync(ordenes)), (0, False))
    c("con un fichero en la referencia: no dice nada de referencia vacía",
      "referencia está vacía" in salida, False)

with sandbox():
    par = pareja()
    baseline(par, CABECERA + CARPETA, CABECERA + CARPETA)
    rc, _, ordenes, _ = pasar(par)
    c("con una carpeta en la referencia: sin cambios, sin --resync",
      (rc, con_resync(ordenes)), (0, False))

with sandbox():
    par = pareja()
    baseline(par, CABECERA, CABECERA + FICHERO)
    rc, _, ordenes, _ = pasar(par)
    c("solo el path1 vacío: sin cambios, sin --resync", (rc, con_resync(ordenes)), (0, False))

with sandbox():
    par = pareja()
    baseline(par, CABECERA + FICHERO, CABECERA)
    rc, _, ordenes, _ = pasar(par)
    c("solo el path2 vacío: sin cambios, sin --resync", (rc, con_resync(ordenes)), (0, False))

with sandbox():
    # INVARIANTE: lo de «hay baseline y falta la carpeta local» sigue mandando
    # aunque la referencia esté vacía. Un lado local que no está se lee como
    # «han borrado todo», y la excepción de la referencia vacía no puede
    # servir para crearlo vacío y resincronizar.
    par = pareja()
    baseline(par)
    par.local_abs.rmdir()
    rc, salida, ordenes, _ = pasar(par)
    c("INVARIANTE referencia vacía y sin carpeta local: aborta con rc=2", rc, 2)
    c("INVARIANTE referencia vacía y sin carpeta local: no ejecuta rclone", ordenes, [])
    c("INVARIANTE referencia vacía y sin carpeta local: no la crea",
      par.local_abs.exists(), False)
    c.contains("INVARIANTE referencia vacía y sin carpeta local: lo explica", salida,
               "no se crea vacía a propósito")

with sandbox():
    # Con los filtros cambiados la pareja ya pedía un resync que nadie aprobaba;
    # con la referencia vacía no hay nada que proteger, y se rehace igual.
    par = pareja()
    baseline(par)
    Path(str(bisync.filters_file_for(par)) + ".md5").write_text("0" * 32, encoding="utf-8")
    rc, _, ordenes, _ = pasar(par)
    c("referencia vacía y filtros cambiados, sin aprobar: se rehace",
      (rc, con_resync(ordenes)), (0, True))

with sandbox():
    par = pareja()
    baseline(par, CABECERA + FICHERO, CABECERA + FICHERO)
    Path(str(bisync.filters_file_for(par)) + ".md5").write_text("0" * 32, encoding="utf-8")
    rc, salida, ordenes, _ = pasar(par)
    c("filtros cambiados con referencia llena, sin aprobar: se salta como siempre",
      (rc, ordenes), (sync.SKIPPED, []))


# --- lo que el agente lee del parte ------------------------------------------------

with sandbox():
    par = pareja()
    baseline(par)
    rc, _, _, dicho = pasar(par)
    c("seguía vacía tras el resync: el parte dice que no movió nada",
      (dicho.rc, dicho.movio), (0, False))

with sandbox():
    par = pareja()
    baseline(par)

    def llega_un_fichero():
        """Simula el resync que baja lo que otro dispositivo dejó en el remoto."""
        baseline(par, CABECERA + FICHERO, CABECERA + FICHERO)

    rc, _, _, dicho = pasar(par, al_ejecutar=llega_un_fichero)
    c("el resync trae algo: el parte dice que movió", (dicho.rc, dicho.movio), (0, True))

with sandbox():
    par = pareja()
    baseline(par, CABECERA + FICHERO, CABECERA + FICHERO)
    rc, _, _, dicho = pasar(par, force_resync=True, resync_approved=True)
    c("un --resync pedido sobre una referencia llena sigue contando como que movió",
      (dicho.rc, dicho.movio), (0, True))


# --- --doctor ---------------------------------------------------------------------

with sandbox():
    par = pareja()
    cfg = model.parse_config({"defaults": DEF, "pair": [BI]})
    baseline(par)
    texto = "\n".join(revision.informe(cfg))
    c.contains("--doctor dice que la referencia está vacía", texto, "referencia: vacía")
    c.contains("--doctor dice que la próxima pasada la rehace", texto, "la próxima pasada la rehace")
    c("la referencia vacía no es una avería de «Reparación»",
      [h.clave for h in revision.revisar(cfg, fisica=None)], [])

    baseline(par, CABECERA + FICHERO, CABECERA + FICHERO)
    c("--doctor no lo dice si hay algo en la referencia",
      "referencia: vacía" in "\n".join(revision.informe(cfg)), False)

# --- el baseline tiene que ser de ESTA pareja ---------------------------------------

OTRO_PREFIJO = "disp_sync-data_docs..nas__otro_destino"
"""Lo que quedaría guardado si el extremo cambió sin apartar el baseline (TOML a mano, un alias)."""

with sandbox():
    par = pareja()
    cfg = model.parse_config({"defaults": DEF, "pair": [BI]})
    baseline(par, prefijo=OTRO_PREFIJO)
    c("un baseline vacío con el prefijo de OTRO destino no es de esta pareja",
      bisync.referencia_vacia(par), False)
    rc, salida, ordenes, _ = pasar(par)
    c("y la pasada no lo rehace sola: sin --resync, como hasta ahora",
      (rc, con_resync(ordenes)), (0, False))
    c("ni dice que lo rehace", "referencia está vacía" in salida, False)
    c("--doctor no promete rehacerlo",
      "referencia: vacía" in "\n".join(revision.informe(cfg)), False)
    c("y «Reparación» sigue diciendo que el baseline no es de esta pareja",
      "prefijo" in claves(revision.revisar(cfg, fisica=None)), True)


# --- un prefijo que no se puede comprobar no prueba que el baseline sea de esta pareja ---

with sandbox():
    # Un alias que no se puede seguir (aquí, un ciclo): `expected_prefix()` es una
    # estimación, y que un baseline lleve ese mismo nombre no dice nada.
    model.RCLONE_CONF.write_text(
        "[ciclo_a]\ntype = alias\nremote = ciclo_b:x\n\n"
        "[ciclo_b]\ntype = alias\nremote = ciclo_a:x\n", encoding="utf-8")
    par = model.parse_config({"defaults": {**DEF, "remote": "ciclo_a"}, "pair": [BI]}).pairs[0]
    par.local_abs.mkdir(parents=True, exist_ok=True)
    baseline(par)
    c("el prefijo de un alias sin resolver no se puede comprobar",
      bisync.prefijo_comprobable(par), False)
    c("un baseline vacío con ese mismo nombre no se rehace sola",
      bisync.referencia_vacia(par), False)
    rc, salida, ordenes, _ = pasar(par)
    c("y la pasada va como siempre, sin --resync", (rc, con_resync(ordenes)), (0, False))


# --- sin carpeta local, la pasada no la rehace: --doctor no puede decir que sí ---------

with sandbox():
    par = pareja()
    cfg = model.parse_config({"defaults": DEF, "pair": [BI]})
    baseline(par)
    par.local_abs.rmdir()
    c("referencia vacía y sin carpeta local: la pasada no la rehace",
      bisync.referencia_vacia(par), False)
    texto = "\n".join(revision.informe(cfg))
    c("--doctor no promete que la próxima pasada la rehace",
      "la próxima pasada la rehace" in texto, False)
    c("y sí avisa de que falta la carpeta local",
      "local" in claves(revision.revisar(cfg, fisica=None)), True)


# --- la decisión se toma una vez, en el preflight ----------------------------------------

with sandbox():
    ctx = sync.RunContext(binary="RCLONE", env={})
    par = pareja()
    baseline(par)
    with contextlib.redirect_stdout(io.StringIO()):
        c("preflight de una referencia vacía: resync, vacía, sin abortar",
          sync._bisync_preflight(ctx, par), (True, True, None))
        baseline(par, CABECERA + FICHERO, CABECERA + FICHERO)
        c("preflight de una referencia llena: ni resync ni vacía",
          sync._bisync_preflight(ctx, par), (False, False, None))
        baseline(par)
        par.local_abs.rmdir()
        c("preflight de una referencia vacía sin carpeta local: aborta con 2",
          sync._bisync_preflight(ctx, par), (False, False, 2))

with sandbox():
    par = pareja()
    baseline(par)
    llamadas = []
    original = bisync.referencia_vacia

    def contada(*args, **kwargs):
        llamadas.append(args)
        return original(*args, **kwargs)

    bisync.referencia_vacia = contada
    try:
        pasar(par)
    finally:
        bisync.referencia_vacia = original
    c("una pasada pregunta una sola vez si la referencia está vacía", len(llamadas), 1)

raise SystemExit(c.report())
