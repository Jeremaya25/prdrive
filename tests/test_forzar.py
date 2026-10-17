#!/usr/bin/env python3
"""Forzar UNA pasada: `sync.py PAREJA --force` y todo lo que la rodea.

El freno de bisync se salta con `--force` y el de un espejo con `--max-delete -1`
(rclone v1.75.2: `cmd/bisync/operations.go`, `fs/accounting/stats.go`). Es un
argumento del script y no un flag del TOML, para que no pueda quedar fijo en el
config; vale solo para la pasada que lo lleva, y solo con parejas nombradas.
Quién lo lanza, y que ninguna ruta desatendida pueda, está en
`test_forzar_desatendido.py`.
"""

import contextlib
import hashlib
import io
import sys
from pathlib import Path

from _harness import Checks, sandbox
from _logs_frenos import BISYNC_BORRADOS, SIMULACION_BISYNC, SIMULACION_BISYNC_VERSIONES, SIMULACION_ESPEJO

import sync
from common import bisync, frenos, model, orden, results
from common.model import ConfigError

c = Checks("forzar una pasada")

DEF = {"remote": "nas"}
BISYNC = {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas"}
SUBIDA = {"name": "espejo", "mode": "up-mirror", "local": "sync-data/espejo",
          "remote_path": "/R/espejo"}
BAJADA = {"name": "bajada", "mode": "down-mirror", "local": "sync-data/bajada",
          "remote_path": "/R/bajada"}
COPIA = {"name": "copia", "mode": "up", "local": "sync-data/copia", "remote_path": "/R/copia"}


def pareja(raw, defaults=DEF):
    """Devuelve la pareja ya parseada."""
    return model.parse_config({"defaults": defaults, "pair": [raw]}).pairs[0]


def valores(cmd, flag):
    """Devuelve lo que sigue a cada `flag` en la orden."""
    return [cmd[i + 1] for i, a in enumerate(cmd[:-1]) if a == flag]


def orden_de(raw, **ctx):
    """Devuelve la orden de rclone que monta `sync.build_command()`, sin el log temporal."""
    p = pareja(raw)
    cmd, log = sync.build_command(sync.RunContext(binary="RCLONE", env={}, **ctx), p,
                                  bisync.filters_file_for(p), False)
    log.unlink(missing_ok=True)
    return ["LOG" if a == str(log) else a for a in cmd]


# ---- La orden: cada freno se salta a su manera, y solo si se pide ------------------------

with sandbox():
    normal, forzada = orden_de(BISYNC), orden_de(BISYNC, force=True)
    c("bisync: una pasada normal no lleva --force", "--force" in normal, False)
    c("bisync forzado: lleva --force", "--force" in forzada, True)
    c("  y sigue con su --max-delete en %, que el --force salta pero no quita",
      (valores(normal, "--max-delete"), valores(forzada, "--max-delete")), (["25"], ["25"]))

    c("espejo: una pasada normal lleva el tope de siempre, una cuenta",
      valores(orden_de(SUBIDA), "--max-delete"), ["50"])
    c("espejo forzado: --max-delete -1 y solo uno, sin el 50",
      valores(orden_de(SUBIDA, force=True), "--max-delete"), ["-1"])
    c("  hacia abajo, igual", valores(orden_de(BAJADA, force=True), "--max-delete"), ["-1"])
    c("  y no lleva --force, que es de bisync", "--force" in orden_de(SUBIDA, force=True), False)
    propio = dict(SUBIDA, flags={"max-delete": 7})
    c("  el tope que la pareja se haya puesto tampoco cuenta en esa pasada",
      (valores(orden_de(propio), "--max-delete"), valores(orden_de(propio, force=True),
                                                        "--max-delete")), (["7"], ["-1"]))

    # rclone se queda con el ÚLTIMO `--max-delete` que recibe, y la cascada guarda las claves
    # como están escritas (`max_delete` y `max-delete` son dos): forzar ha de quitarlas todas,
    # y también las de `extra_flags`, que van detrás de todo. Si no, «sin tope» frena igual.
    def sin_tope(raw, **ctx):
        """Devuelve los `--max-delete` (con su valor) que lleva la orden de una pasada de ese espejo."""
        cmd = orden_de(raw, **ctx)
        return ([cmd[i + 1] for i, a in enumerate(cmd[:-1]) if a == "--max-delete"]
                + [a for a in cmd if a.startswith("--max-delete=")])

    for que, raw in (("`max_delete` en la pareja", dict(SUBIDA, flags={"max_delete": 5})),
                     ("`max-delete` en la pareja", dict(SUBIDA, flags={"max-delete": 5})),
                     ("`--max-delete N` en extra_flags", dict(SUBIDA, extra_flags=["--max-delete", "7"])),
                     ("`--max-delete=N` en extra_flags", dict(SUBIDA, extra_flags=["--max-delete=7"])),
                     ("las dos cosas a la vez", dict(SUBIDA, flags={"max_delete": 5},
                                                     extra_flags=["--max-delete", "7"]))):
        c(f"espejo forzado con {que}: llega a rclone un solo --max-delete, el -1",
          sin_tope(raw, force=True), ["-1"])
    c("  y sin forzar no se toca nada de lo escrito (rclone se queda con lo último)",
      (sin_tope(dict(SUBIDA, flags={"max_delete": 5})),
       sin_tope(dict(SUBIDA, extra_flags=["--max-delete=7"]))), (["50", "5"], ["50", "--max-delete=7"]))
    con_otros = dict(SUBIDA, extra_flags=["--checksum", "--max-delete", "7", "--fast-list"])
    c("  y de extra_flags solo se va el --max-delete y su valor, el resto se queda",
      [a for a in orden_de(con_otros, force=True) if a in ("--checksum", "--fast-list", "7")],
      ["--checksum", "--fast-list"])
    tamano = dict(SUBIDA, extra_flags=["--max-delete-size", "5M"])
    c("  `--max-delete-size` es otro freno y no se quita: forzar `max-delete` no lo salta",
      ("--max-delete-size" in orden_de(tamano, force=True), "5M" in orden_de(tamano, force=True)),
      (True, True))
    c("  y la vista previa del editor de flags dice lo mismo que la orden",
      [t.args for t in orden.tramos(pareja(dict(SUBIDA, flags={"max_delete": 5})), binario="R",
                                    filtros=None, config="c", logfile="l", forzar=True)
       if t.args[0] == "--max-delete"], [("--max-delete", "-1")])
    en_bisync = dict(BISYNC, flags={"max_delete": 40})
    c("bisync forzado no toca el tope que se haya puesto: lo salta el --force",
      ("--force" in orden_de(en_bisync, force=True),
       valores(orden_de(en_bisync, force=True), "--max-delete")), (True, ["25", "40"]))

    c("un copy no borra y no tiene freno: forzarlo no cambia la orden",
      orden_de(COPIA, force=True), orden_de(COPIA))
    simulada = orden_de(BISYNC, force=True, dry_run=True)
    c("forzado y simulado: lleva los dos, que es como se ve qué borraría",
      ("--force" in simulada, "--dry-run" in simulada), (True, True))
    c("  y el espejo, igual",
      (valores(orden_de(SUBIDA, force=True, dry_run=True), "--max-delete"),
       "--dry-run" in orden_de(SUBIDA, force=True, dry_run=True)), (["-1"], True))

    # Un resync (también el que `_bisync_preflight()` decide solo con la referencia vacía,
    # #113) no pasa por el freno de borrados: no tiene nada que saltar y no lleva --force.
    p = pareja(BISYNC)
    resincronizada = orden.orden_rclone(p, binario="R", filtros=None, config="c", logfile="l",
                                        resync=True, forzar=True)
    c("una pasada que es un --resync no lleva --force, aunque se pida forzar",
      ("--resync" in resincronizada, "--force" in resincronizada), (True, False))
    vista = orden.tramos(p, binario="R", filtros=None, config="c", logfile="l", forzar=True)
    forzado = [t for t in vista if t.nombre == "force"]
    c("la vista previa del editor de flags sabe quién pone el --force: el programa",
      [(t.args, t.origen) for t in forzado], [(("--force",), model.ORIGEN_PRDRIVE)])
    c("  y por defecto no hay ninguno",
      [t for t in orden.tramos(p, binario="R", filtros=None, config="c", logfile="l")
       if t.nombre == "force"], [])
    p = pareja(SUBIDA)
    c("  el espejo: el -1 también es del programa",
      [(t.args, t.origen) for t in orden.tramos(
          p, binario="R", filtros=None, config="c", logfile="l", forzar=True)
       if t.nombre == "max-delete"], [(("--max-delete", "-1"), model.ORIGEN_PRDRIVE)])

# ---- La línea de órdenes ----------------------------------------------------------------


def rechazado(*argv):
    """Devuelve `(código, mensaje)` si `parse_args` rechaza esos argumentos, o `None`."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        try:
            sync.parse_args(list(argv))
        except SystemExit as e:
            return e.code, err.getvalue()
    return None


c("--force se pide con una pareja nombrada", sync.parse_args(["notas", "--force"]).force, True)
c("  y por defecto no", sync.parse_args(["notas"]).force, False)
c("  se puede simular antes", sync.parse_args(["notas", "--force", "--dry-run"]).dry_run, True)
sin_nombre = rechazado("--force")
c("sin nombrar pareja se rechaza: forzaría todas", sin_nombre is not None and sin_nombre[0], 2)
c.contains("  y dice por qué", sin_nombre[1], "nombres la pareja")
c("  aunque sea una simulación", (rechazado("--force", "--dry-run") or (0,))[0], 2)
junto = rechazado("notas", "--force", "--resync")
c("con --resync tampoco: son dos remedios distintos", junto is not None and junto[0], 2)

# `main()` le da el --force a ESA ejecución y a nada más.
with sandbox():
    model.CONFIG_FILE.write_text(
        '[defaults]\nremote = "nas"\n\n[[pair]]\nname = "notas"\nlocal = "sync-data/notas"\n'
        'remote_path = "/R/notas"\n', encoding="utf-8")
    model.RCLONE_CONF.write_text("[nas]\ntype = local\n", encoding="utf-8")
    visto = []
    run_all, binario = sync.run_all, model.rclone_binary
    sync.run_all = lambda ctx, selected: visto.append((ctx.force, [p.name for p in selected])) or 0
    model.rclone_binary = lambda: "RCLONE"
    argv, sys.argv = sys.argv, ["sync.py"]
    try:
        for args in (["notas", "--force"], ["notas"]):
            sys.argv = ["sync.py", *args]
            with contextlib.redirect_stdout(io.StringIO()):
                sync.main()
    finally:
        sync.run_all, model.rclone_binary, sys.argv = run_all, binario, argv
    c("main(): la pasada pedida con --force va forzada y la siguiente, normal",
      visto, [(True, ["notas"]), (False, ["notas"])])

# ---- Una pasada entera -------------------------------------------------------------------


def correr(raw, *, con_baseline=True, rc=0, texto_log="simulado\n", **opciones):
    """Hace `run_pair()` con un rclone de mentira; devuelve `(rc, salida, órdenes, pareja)`."""
    p = pareja(raw)
    p.local_abs.mkdir(parents=True, exist_ok=True)
    if con_baseline and p.is_bisync:
        p.workdir.mkdir(parents=True, exist_ok=True)
        for sufijo in (bisync.PATH1_SUFFIX, bisync.PATH2_SUFFIX):
            (p.workdir / f"{bisync.expected_prefix(p)}{sufijo}").write_text("x", encoding="utf-8")
        ffile = bisync.filters_file_for(p)
        if ffile:
            Path(str(ffile) + ".md5").write_text(
                hashlib.md5(ffile.read_bytes()).hexdigest(), encoding="utf-8")
    ordenes = []

    def execute_simulado(ctx, cmd, logfile=None):
        """Apunta la orden y escribe el log como rclone."""
        ordenes.append(cmd)
        Path(cmd[cmd.index("--log-file") + 1]).write_text(texto_log, encoding="utf-8")
        return rc

    original, sync.execute = sync.execute, execute_simulado
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            salida_rc = sync.run_pair(sync.RunContext(binary="RCLONE", env={}, **opciones), p)
        return salida_rc, buf.getvalue(), ordenes, p
    finally:
        sync.execute = original


with sandbox():
    rc, salida, ordenes, p = correr(BISYNC, force=True)
    c("una pasada forzada de bisync corre con --force", (rc, "--force" in ordenes[0]), (0, True))
    c.contains("  y lo dice, que no pase por una normal", salida, "FORZADA")
    rc2, salida2, ordenes2, _ = correr(BISYNC)
    c("la siguiente, sin pedirlo, vuelve a llevar el freno",
      ("--force" in ordenes2[0], "FORZADA" in salida2), (False, False))

with sandbox():
    rc, salida, ordenes, p = correr(SUBIDA, force=True)
    c("una pasada forzada de un espejo corre con --max-delete -1",
      (rc, valores(ordenes[0], "--max-delete")), (0, ["-1"]))
    c.contains("  y lo dice", salida, "FORZADA")
    _, _, ordenes2, _ = correr(SUBIDA)
    c("la siguiente vuelve a llevar su tope", valores(ordenes2[0], "--max-delete"), ["50"])

with sandbox():
    rc, salida, ordenes, p = correr(COPIA, force=True)
    c("forzar un copy no cambia nada, y lo dice en vez de callarse",
      (rc, "--force" in ordenes[0], valores(ordenes[0], "--max-delete")), (0, False, []))
    c.contains("  no tiene freno", salida, "no tiene freno")

# La simulación forzada es la que enseña lo que borraría: sin eso, "OK" no dice nada.
with sandbox():
    rc, salida, _, _ = correr(SUBIDA, force=True, dry_run=True, texto_log=SIMULACION_ESPEJO)
    c("una simulación forzada de un espejo dice cuántos ficheros borraría, y dónde",
      (rc, "se borrarían 5 ficheros en el remoto" in salida), (0, True))
    c("  y los nombra", all(f"nota{n:02d}.md" in salida for n in (7, 9, 24, 39, 41)), True)
    c.contains("  y que no ha tocado nada", salida, "no se ha tocado nada")
with sandbox():
    rc, salida, _, _ = correr(BISYNC, force=True, dry_run=True, texto_log=SIMULACION_BISYNC)
    c("  la de bisync, lo mismo, sin decir en qué lado: el log no lo sabe",
      ("se borrarían 8 ficheros" in salida, "en el remoto" in salida, "nota08.md" in salida),
      (True, False, True))
with sandbox():
    # Con versiones, lo que se borra va a `.prversions/` y rclone lo apunta como «move into backup
    # dir»; lo que se sobrescribe, como «move to <nombre>~…» y «copy»: solo lo primero es un borrado.
    rc, salida, _, _ = correr(dict(BISYNC, versions=True), force=True, dry_run=True,
                              texto_log=SIMULACION_BISYNC_VERSIONES)
    c("una simulación forzada de un bisync con versiones cuenta lo que va a .prversions/",
      (rc, "se borrarían 8 ficheros" in salida,
       all(f"nota{n:02d}.md" in salida for n in range(1, 9))), (0, True, True))
    c("  y no cuenta como borrados los dos que solo se sobrescriben",
      ("nota09.md" in salida, "nota10.md" in salida), (False, False))

with sandbox():
    # Un espejo cuya carpeta se ha desmontado: cien mil ficheros. El número es el que la persona
    # mira antes de forzar, así que se lee el log entero (pesa más que lo que se lee al pintar).
    cien_mil = "".join(f"2026/10/15 09:44:06 NOTICE: dato{i:06d}.md: Skipped delete as --dry-run is set "
                       "(size 8)\n" for i in range(100_000))
    c("la simulación lee el log entero: el log de prueba pasa del tope de lectura",
      len(cien_mil) > frenos.TOPE_LECTURA, True)
    rc, salida, _, _ = correr(SUBIDA, force=True, dry_run=True, texto_log=cien_mil)
    c("  y dice el número exacto, no el de la última parte",
      "se borrarían 100000 ficheros en el remoto" in salida, True)
    c.contains("  del resto, que son muchos, dice cuántos faltan por nombrar", salida, "y 99980 más")

with sandbox():
    muchos = "".join(f"2026/10/15 09:44:06 NOTICE: n{i:03d}.md: Skipped delete as --dry-run is "
                     f"set (size 1)\n" for i in range(30))
    rc, salida, _, _ = correr(SUBIDA, force=True, dry_run=True, texto_log=muchos)
    c("con muchos, nombra los primeros y cuenta el resto",
      ("n019.md" in salida, "n020.md" in salida, "y 10 más" in salida), (True, False, True))
with sandbox():
    rc, salida, _, _ = correr(SUBIDA, force=True, dry_run=True)
    c.contains("si el log no apunta borrados, lo dice sin afirmar más de lo que sabe", salida,
               "no ha apuntado ningún borrado")
    c("  y no asegura que no se borre nada", "no se borraría" in salida, False)
with sandbox():
    rc, salida, _, _ = correr(SUBIDA, dry_run=True, texto_log=SIMULACION_ESPEJO)
    c("una simulación normal no cambia: no lista nada", "se borrarían" in salida, False)
    rc, salida, _, _ = correr(SUBIDA, force=True, texto_log=SIMULACION_ESPEJO)
    c("  ni una pasada forzada de verdad, que ya borra", "se borrarían" in salida, False)

with sandbox():
    # Una pasada forzada se apunta como cualquier otra: si va bien, el fallo del freno se va.
    cfg = model.parse_config({"defaults": DEF, "pair": [BISYNC]})
    results.apuntar("notas", 1, None)
    c("antes, la última pasada de la pareja falló", [f.pareja for f in results.fallos(cfg)],
      ["notas"])
    correr(BISYNC, force=True)
    c("una forzada que va bien lo deja apuntado y el fallo se va", results.fallos(cfg), [])
    correr(BISYNC, force=True, rc=1)
    c("  y una forzada que falla también se apunta",
      [f.pareja for f in results.fallos(cfg)], ["notas"])

with sandbox():
    rc, salida, ordenes, p = correr(BISYNC, con_baseline=False, force=True)
    c("sin baseline sigue pidiendo --resync: forzar no es resincronizar",
      (rc, ordenes), (sync.SKIPPED, []))

with sandbox():
    # `_bisync_preflight()` sigue mandando: con baseline y sin carpeta local no se corre,
    # ni forzando (un lado local vacío se lee como «se ha borrado todo»).
    p = pareja(BISYNC)
    p.workdir.mkdir(parents=True, exist_ok=True)
    for sufijo in (bisync.PATH1_SUFFIX, bisync.PATH2_SUFFIX):
        (p.workdir / f"{bisync.expected_prefix(p)}{sufijo}").write_text("x", encoding="utf-8")
    ffile = bisync.filters_file_for(p)
    Path(str(ffile) + ".md5").write_text(hashlib.md5(ffile.read_bytes()).hexdigest(),
                                         encoding="utf-8")
    ordenes = []
    original, sync.execute = sync.execute, lambda *a, **k: ordenes.append(a) or 0
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rc = sync.run_pair(sync.RunContext(binary="RCLONE", env={}, force=True), p)
    finally:
        sync.execute = original
    c("INVARIANTE: baseline sin carpeta local aborta con 2 aunque se fuerce",
      (rc, ordenes), (2, []))


def pasada_sin_carpeta(raw, **opciones):
    """Hace `run_pair()` sin crear la carpeta local; devuelve `(rc, órdenes, existe_la_carpeta)`."""
    p = pareja(raw)
    ordenes = []
    original, sync.execute = sync.execute, lambda *a, **k: ordenes.append(a) or 0
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rc = sync.run_pair(sync.RunContext(binary="RCLONE", env={}, **opciones), p)
    finally:
        sync.execute = original
    return rc, ordenes, p.local_abs.exists()


with sandbox():
    # INVARIANTE (#151): la carpeta local de un espejo de subida es su ORIGEN. Creada vacía, el
    # `--max-delete -1` de una pasada forzada (o el 50 de la normal) vaciaría el remoto; sin
    # ella, rclone se niega. `sync.py NOMBRE --force` pasa por el mismo `_pasar_pareja()`.
    c("INVARIANTE: espejo de subida sin carpeta local aborta con 2, no crea la carpeta y no corre",
      pasada_sin_carpeta(SUBIDA, force=True), (2, [], False))
    c("  y tampoco en una simulación forzada",
      pasada_sin_carpeta(SUBIDA, force=True, dry_run=True), (2, [], False))
    c("  ni sin forzar, que es de donde viene el riesgo",
      pasada_sin_carpeta(SUBIDA), (2, [], False))
    c("  y el aborto queda apuntado, forzado o no",
      [(f.pareja, f.codigo) for f in results.fallos(model.parse_config(
          {"defaults": DEF, "pair": [SUBIDA]}))], [("espejo", 2)])
    rc, ordenes, existe = pasada_sin_carpeta(BAJADA, force=True)
    c("una bajada forzada sigue creando su carpeta: es el destino",
      (rc, len(ordenes), existe), (0, 1, True))
    rc, ordenes, existe = pasada_sin_carpeta(COPIA, force=True)
    c("  y un copy, igual", (rc, len(ordenes), existe), (0, 1, True))

# ---- El llavero no se fuerza: sus bases son contraseñas ---------------------------------

CON_LLAVERO = {"defaults": DEF, "pair": [BISYNC],
               "keychain": {"base": "personal.kdbx", "fichero_llave": True,
                            "nombre_llave": "personal.keyx"}}
cfg_llavero = model.parse_config(CON_LLAVERO)
llavero_pair = cfg_llavero.select([model.LLAVERO])[0]
c("la pareja del llavero se elige por su nombre (por eso hay que cerrarle la puerta aquí)",
  llavero_pair.llavero, True)
c("la orden del llavero no lleva --force aunque se pida forzar",
  "--force" in orden.orden_rclone(llavero_pair, binario="R", filtros=None, config="c",
                                  logfile="l", forzar=True), False)
c("  ni la de una pareja normal deja de llevarlo",
  "--force" in orden.orden_rclone(cfg_llavero.pairs[0], binario="R", filtros=None, config="c",
                                  logfile="l", forzar=True), True)
c("  la línea de aviso dice que al llavero no se le fuerza",
  "llavero" in sync.avisar_forzada(llavero_pair), True)

with sandbox():
    model.CONFIG_FILE.write_text(
        '[defaults]\nremote = "nas"\n\n[[pair]]\nname = "notas"\nlocal = "sync-data/notas"\n'
        'remote_path = "/R/notas"\n\n[keychain]\nbase = "personal.kdbx"\nfichero_llave = true\n'
        'nombre_llave = "personal.keyx"\n', encoding="utf-8")
    model.RCLONE_CONF.write_text("[nas]\ntype = local\n", encoding="utf-8")
    lanzado = []
    run_all, binario = sync.run_all, model.rclone_binary
    sync.run_all = lambda ctx, selected: lanzado.append(ctx.force) or 0
    model.rclone_binary = lambda: "RCLONE"
    argv, sys.argv = sys.argv, ["sync.py", model.LLAVERO, "--force"]
    try:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                sync.main()
            dicho = "no salió"
        except SystemExit as e:
            dicho = str(e.code)
    finally:
        sync.run_all, model.rclone_binary, sys.argv = run_all, binario, argv
    c("`sync.py keychain --force` se rechaza antes de lanzar nada y dice por qué",
      (lanzado, "llavero" in dicho, "Combinar" in dicho), ([], True, True))

    # Y sin forzar el llavero sigue yéndose por su nombre como siempre.
    sys.argv = ["sync.py", model.LLAVERO]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            sync.run_all, model.rclone_binary = (lambda ctx, selected: lanzado.append(
                [p.name for p in selected]) or 0), (lambda: "RCLONE")
            sync.main()
    finally:
        sync.run_all, model.rclone_binary, sys.argv = run_all, binario, argv
    c("  sin --force, el llavero se sincroniza como siempre", lanzado[-1], [model.LLAVERO])


def explicar(pareja, texto):
    """Devuelve lo que `sync.explain_failure()` dice de ese log para esa pareja."""
    log = sync.temp_log("explicar")
    log.write_text(texto, encoding="utf-8")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        sync.explain_failure(log, pareja)
    log.unlink(missing_ok=True)
    return buf.getvalue()


with sandbox():
    del_llavero = explicar(llavero_pair, BISYNC_BORRADOS)
    c("la consola no manda forzar el freno del llavero: dice que no se salta y lo suyo",
      ("--force" in del_llavero, "Reparación" in del_llavero, "Combinar" in del_llavero),
      (False, False, True))
    de_notas = explicar(cfg_llavero.pairs[0], BISYNC_BORRADOS)
    c("  y la de una pareja normal sigue diciendo cómo forzar",
      ("--force" in de_notas, "Combinar" in de_notas), (True, False))

# ---- El TOML no puede fijarlo -----------------------------------------------------------


def motivo(data):
    """Devuelve lo que dice `ConfigError` al parsear ese config, o `None` si lo acepta."""
    try:
        model.parse_config(data)
    except ConfigError as e:
        return str(e)
    return None


def con(**trozos):
    """Un config con una pareja bisync y esos trozos añadidos a `[defaults]` o a la pareja."""
    defaults = dict(DEF, **trozos.get("defaults", {}))
    return {"defaults": defaults, "pair": [dict(BISYNC, **trozos.get("pair", {}))]}


c("el flag se reserva: es del script", model.problema_flag("force") is not None, True)
c("  con cualquier grafía", model.problema_flag("FORCE") is not None, True)
for donde, trozos in (
        ("[defaults.flags]", {"defaults": {"flags": {"force": True}}}),
        ("[pair.flags]", {"pair": {"flags": {"force": True}}}),
        ("una grafía distinta", {"pair": {"flags": {"Force": True}}}),
        ("extra_flags", {"pair": {"extra_flags": ["--force"]}}),
        ("el valor de otro flag", {"pair": {"flags": {"checksum": "--force"}}})):
    dicho = motivo(con(**trozos))
    c(f"--force no se acepta desde el TOML ({donde})", dicho is not None, True)
c.contains("  y el mensaje dice cuál y qué hacer", motivo(con(pair={"flags": {"force": True}})),
           "Quítalo del config")
# Antes de esto `force = true` era la ÚNICA forma de pasarle el --force de rclone (que él mismo
# anuncia en sus abortos): quien lo tenga puesto ve este mensaje con la ventana cerrada, así que
# dice cómo se consigue ahora lo que buscaba.
for donde, trozos in (("[pair.flags]", {"pair": {"flags": {"force": True}}}),
                      ("extra_flags", {"pair": {"extra_flags": ["--force"]}})):
    dicho = motivo(con(**trozos))
    c(f"  y a quien ya lo tenía ({donde}) le dice cómo forzar una pasada ahora",
      ("Reparación" in dicho, "sync.py PAREJA --force" in dicho), (True, True))

# Decisión: `max-delete = -1` SIGUE valiendo. En un espejo es el «sin tope» de rclone y en bisync
# vuelve al 50 % de fábrica (`applyContext()` solo atiende un valor >= 0): una elección
# permanente de quien lo escribe, como lo sería un 1000000, y un dispositivo en uso puede
# llevarlo. Rechazar solo el -1 sería rechazar una cifra y romper la lectura de ese config.
espejo_sin_tope = con(pair={"mode": "up-mirror", "flags": {"max-delete": -1}})
c("max-delete = -1 en el TOML se admite: es la decisión de quien lo escribe, fija",
  motivo(espejo_sin_tope), None)
c("  y llega a la pareja tal cual",
  model.parse_config(espejo_sin_tope).pairs[0].flags["max-delete"], -1)

sys.exit(c.report())
