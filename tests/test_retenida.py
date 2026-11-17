#!/usr/bin/env python3
"""Un espejo que se para en su freno queda retenido (D2): la regla de `sync.py`.

`rclone sync --max-delete N` borra N ficheros por pasada y sale con 7: lanzado otra vez
por el servicio o el agente, vaciaría el lado de destino a plazos. Por eso `sync.py`
apunta el freno de un espejo en `last_run.json` y, al empezar, no lanza un espejo
retenido sin que una persona lo apruebe (`--resume`, `--force`, o un «sí» en una
terminal); lo salta con «Saltada», sin rclone y sin tocar lo apuntado. Una pasada
buena lo suelta. Spec: `docs/superpowers/specs/2026-11-06-espejo-retenido-tras-el-freno-design.md`.

Se mira: qué se apunta y qué no (bisync y `copy` nunca; un simulacro tampoco), la pasada
saltada y su parte, quién la lanza desde `main()` (una sola pregunta para todas), el
registro de un `sync.py` anterior y la pareja que deja de ser un espejo.
"""

import contextlib
import hashlib
import io
import sys
from pathlib import Path

from _harness import Checks, sandbox
from _logs_errores import RED_RECHAZADA
from _logs_frenos import BISYNC_BORRADOS, ESPEJO_UP

import sync
from common import bisync, model, parte, results, revision, store

c = Checks("espejo retenido tras el freno")

SUBIDA = {"name": "fotos", "mode": "up-mirror", "local": "sync-data/fotos", "remote_path": "/R/fotos"}
SUBIDA2 = {"name": "fotos2", "mode": "up-mirror", "local": "sync-data/fotos2",
           "remote_path": "/R/fotos2"}
NOTAS = {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas"}   # bisync
COPIA = {"name": "copia", "mode": "up", "local": "sync-data/copia", "remote_path": "/R/copia"}
FOTOS_BISYNC = {"name": "fotos", "local": "sync-data/fotos", "remote_path": "/R/fotos"}


def toml_de(*parejas):
    """Devuelve el TOML de esas parejas, con `remote = "nas"` por defecto."""
    texto = '[defaults]\nremote = "nas"\n'
    for pareja in parejas:
        texto += "\n[[pair]]\n" + "".join(f'{k} = "{v}"\n' for k, v in pareja.items())
    return texto


TOML = toml_de(SUBIDA, NOTAS, COPIA)
TOML_FOTOS_BISYNC = toml_de(FOTOS_BISYNC, NOTAS, COPIA)
TOML_DOS = toml_de(SUBIDA, SUBIDA2, COPIA)


def pareja(raw):
    """Devuelve la pareja ya parseada."""
    return model.parse_config({"defaults": {"remote": "nas"}, "pair": [raw]}).pairs[0]


@contextlib.contextmanager
def rclone_falso(rc=0, texto_log="simulado\n", ordenes=None):
    """Sustituye `sync.execute` por un rclone de mentira que escribe su log y apunta la orden."""
    ordenes = [] if ordenes is None else ordenes

    def execute_simulado(ctx, cmd, logfile=None):
        """Apunta la orden y escribe el log como rclone."""
        ordenes.append(cmd)
        Path(cmd[cmd.index("--log-file") + 1]).write_text(texto_log, encoding="utf-8")
        return rc

    original, sync.execute = sync.execute, execute_simulado
    try:
        yield ordenes
    finally:
        sync.execute = original


def correr(raw, *, con_baseline=True, rc=0, texto_log="simulado\n", **opciones):
    """Hace `run_pair()` con un rclone de mentira; devuelve `(rc, salida, órdenes)`."""
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
    buf = io.StringIO()
    with rclone_falso(rc, texto_log, ordenes), contextlib.redirect_stdout(buf):
        salida_rc = sync.run_pair(sync.RunContext(binary="RCLONE", env={}, **opciones), p)
    return salida_rc, buf.getvalue(), ordenes


def lanzar_main(argv, toml=TOML, *, tty=None, real=False):
    """Hace `sync.main()` con esos argumentos; devuelve `(ctx, salida, preguntas)`.

    Escribe el config y el `rclone.conf`. Sin `real`, `run_all` se sustituye y devuelve el
    `RunContext` que le habría llegado; con `real`, corre de verdad (con el rclone de
    mentira que haya puesto quien llama) y devuelve `(rc, salida, preguntas)`. Sin `tty`,
    stdin no es una terminal; con `tty` True o False, `ask_yes_no` contesta eso y apunta
    cada pregunta.
    """
    model.CONFIG_FILE.write_text(toml, encoding="utf-8")
    model.RCLONE_CONF.write_text("[nas]\ntype = local\n", encoding="utf-8")
    visto, preguntas = [], []
    originales = (sync.run_all, model.rclone_binary, sync.ask_yes_no, sys.stdin, sys.argv)
    if not real:
        sync.run_all = lambda ctx, selected: visto.append(ctx) or 0
    model.rclone_binary = lambda: "RCLONE"
    if tty is not None:
        sync.ask_yes_no = lambda pregunta, default=False: preguntas.append(pregunta) or tty
    sys.stdin = io.StringIO("")
    sys.argv = ["sync.py", *argv]
    salida = io.StringIO()
    try:
        with contextlib.redirect_stdout(salida):
            rc = sync.main()
    finally:
        sync.run_all, model.rclone_binary, sync.ask_yes_no, sys.stdin, sys.argv = originales
    return (rc if real else visto[0]), salida.getvalue(), preguntas


retenida = lambda: results.apuntes(["fotos"])["fotos"].retenida
preguntas_de_retenidas = lambda preguntas: [p for p in preguntas if "Lanzarlas" in p]

# ---- Apuntar ----------------------------------------------------------------------------

with sandbox():
    correr(SUBIDA, rc=7, texto_log=ESPEJO_UP)
    c("el freno de un espejo lo retiene", retenida() is not None, True)
    antes = retenida()
    correr(SUBIDA, rc=1, texto_log=RED_RECHAZADA)
    c("  un fallo que no es el freno no lo suelta", retenida(), antes)
    correr(SUBIDA, rc=0)
    c("  una pasada buena lo suelta", retenida(), None)

with sandbox():
    correr(NOTAS, rc=7, texto_log=BISYNC_BORRADOS)
    correr(COPIA, rc=7, texto_log=ESPEJO_UP)
    c("bisync y copy nunca se retienen",
      [results.apuntes([n])[n].retenida for n in ("notas", "copia")], [None, None])

with sandbox():
    correr(SUBIDA, rc=7, texto_log=ESPEJO_UP, dry_run=True)
    c("un simulacro no apunta nada", results.apuntes(["fotos"]), {})

with sandbox():
    log = model.LOG_DIR / "fotos.log"
    log.write_text(ESPEJO_UP, encoding="utf-8")
    c("paro_en_el_freno: el log de un freno de espejo", sync.paro_en_el_freno(pareja(SUBIDA), log), True)
    c("  no lo es de un bisync", sync.paro_en_el_freno(pareja(NOTAS), log), False)
    c("  ni de un copy", sync.paro_en_el_freno(pareja(COPIA), log), False)
    c("  ni sin log", sync.paro_en_el_freno(pareja(SUBIDA), None), False)
    c("  ni con un log que no se lee", sync.paro_en_el_freno(pareja(SUBIDA), model.LOG_DIR / "no.log"),
      False)
    log.write_text(RED_RECHAZADA, encoding="utf-8")
    c("  ni con un log que es otro fallo", sync.paro_en_el_freno(pareja(SUBIDA), log), False)

# ---- Saltar -----------------------------------------------------------------------------

with sandbox():
    correr(SUBIDA, rc=7, texto_log=ESPEJO_UP)
    r = revision.Retencion("fotos", "2026-11-05 18:20:00", None)
    antes = results.ruta_estado().read_bytes()
    rc, salida, ordenes = correr(SUBIDA, rc=0, retenidas={"fotos": r})
    c("sin aprobar, se salta sin rclone", (rc, ordenes), (sync.SKIPPED, []))
    c.contains("  diciendo por qué", salida, "[fotos] Saltada: está retenida")
    c("  sin tocar last_run.json", results.ruta_estado().read_bytes(), antes)
    c("  y su parte lo dice", parte.leer(salida)["fotos"], parte.Parte("fotos", -1, retenida=True))
    c("  sin una línea de pasada hecha", "OK." in salida or "FALLÓ" in salida, False)
    rc2, salida2, ordenes2 = correr(SUBIDA, rc=0)
    c("lo no retenido por esta ejecución corre y suelta la retención",
      (rc2, len(ordenes2), retenida()), (0, 1, None))
    c("  y su parte sigue siendo el de siempre", parte.leer(salida2)["fotos"].retenida, False)

# ---- Quién la lanza (main), con fotos retenida en last_run.json ---------------------------

with sandbox():
    correr(SUBIDA, rc=7, texto_log=ESPEJO_UP)
    c("sin terminal ni flag, no", sorted(lanzar_main(["fotos"])[0].retenidas), ["fotos"])
    ctx, salida, _ = lanzar_main(["fotos"])
    c.contains("  y lo dice", salida, "Espejos retenidos tras el freno de borrados:")
    c.contains("  con su texto", salida, "  - «fotos» se paró en el freno de borrados")
    c.contains("  y que se saltará", salida, "De acuerdo, se saltarán.")
    ctx, salida, _ = lanzar_main(["fotos", "--resume"])
    c("con --resume, sí", dict(ctx.retenidas), {})
    c.contains("  y lo dice", salida, "--resume: se lanzarán con su tope de borrados.")
    ctx, salida, _ = lanzar_main(["fotos", "--force"])
    c("con --force, sí", dict(ctx.retenidas), {})
    c.contains("  y dice que va sin tope", salida,
               "--force: se lanzarán SIN su tope de borrados (pasada forzada)")
    c("  no que lleva su tope", "con su tope de borrados." in salida, False)
    c.contains("  también con --resume a la vez: manda --force",
               lanzar_main(["fotos", "--resume", "--force"])[1], "SIN su tope de borrados")
    c("--yes no la aprueba", sorted(lanzar_main(["fotos", "--yes"])[0].retenidas), ["fotos"])
    c("  -y tampoco", sorted(lanzar_main(["fotos", "-y"])[0].retenidas), ["fotos"])
    c("  ni --resync", sorted(lanzar_main(["fotos", "--resync"])[0].retenidas), ["fotos"])
    ctx, _, preguntas = lanzar_main(["fotos"], tty=True)
    c("una terminal que dice que sí, sí", dict(ctx.retenidas), {})
    c("  preguntando una vez", len(preguntas_de_retenidas(preguntas)), 1)
    ctx, _, preguntas = lanzar_main(["fotos"], tty=False)
    c("una terminal que dice que no, no", sorted(ctx.retenidas), ["fotos"])
    ctx, salida, preguntas = lanzar_main(["fotos", "--dry-run"], tty=True)
    c("--dry-run no la mira", (dict(ctx.retenidas), preguntas, "retenidos" in salida), ({}, [], False))
    c("--resume es de la línea de órdenes", (sync.parse_args(["--resume"]).resume,
                                              sync.parse_args([]).resume), (True, False))
    ctx, salida, preguntas = lanzar_main(["copia"], tty=True)
    c("sin retenidas entre las elegidas no se pregunta ni se dice nada",
      (dict(ctx.retenidas), preguntas, "retenidos" in salida), ({}, [], False))

# Review Focus 1: «Saltarla» con otras marcadas. El run_all de verdad, con `copia` (modo `up`)
# sana: fotos sale «Saltada» y copia pasa; main() da 0 y cuenta la saltada.
with sandbox():
    correr(SUBIDA, rc=7, texto_log=ESPEJO_UP)
    ordenes = []
    with rclone_falso(0, "simulado\n", ordenes):
        rc, salida, _ = lanzar_main(["fotos", "copia"], real=True)
    c("«Saltarla» con otras marcadas: sale 0", rc, 0)
    c.contains("  fotos, saltada", salida, "[fotos] Saltada: está retenida")
    c("  y solo corre la sana, una vez", (len(ordenes), any("copia" in a for a in ordenes[0])),
      (1, True))
    c.contains("  el resumen la cuenta", salida, "1 saltada(s)")
    c("  fotos sigue retenida y copia consta", (retenida() is not None,
                                              results.apuntes(["copia"])["copia"].codigo),
      (True, 0))

# Review Focus 4: dos retenidas y una sana, una sola pregunta para las dos.
with sandbox():
    correr(SUBIDA, rc=7, texto_log=ESPEJO_UP)
    correr(SUBIDA2, rc=7, texto_log=ESPEJO_UP)
    correr(COPIA, rc=0)
    ctx, _, preguntas = lanzar_main(["fotos", "fotos2", "copia"], TOML_DOS, tty=False)
    c("dos retenidas, que no: una pregunta y las dos fuera, copia no",
      (len(preguntas_de_retenidas(preguntas)), sorted(ctx.retenidas)), (1, ["fotos", "fotos2"]))
    ctx, _, preguntas = lanzar_main(["fotos", "fotos2", "copia"], TOML_DOS, tty=True)
    c("  que sí: una pregunta y ninguna fuera",
      (len(preguntas_de_retenidas(preguntas)), dict(ctx.retenidas)), (1, {}))

# ---- Un registro de un sync.py anterior (§4) -----------------------------------------------

with sandbox():
    nombre = "fotos_20261105-182000.log"
    (model.LOG_DIR / nombre).write_text(ESPEJO_UP, encoding="utf-8")
    store.write_json(results.ruta_estado(), {"parejas": {"fotos": {
        "cuando": "2026-11-05 18:20:00", "codigo": 7, "log": nombre, "buena": None}}})
    ctx, _, _ = lanzar_main(["fotos", "--dry-run"])
    c("un simulacro no apunta la decisión", results.apuntes(["fotos"])["fotos"].sabida, False)
    ctx, _, _ = lanzar_main(["fotos"])
    c("una unidad que se actualiza a mitad de la racha queda retenida",
      sorted(ctx.retenidas), ["fotos"])
    c("  y la decisión queda apuntada", results.apuntes(["fotos"])["fotos"].sabida, True)
    c("  desde cuando falló", results.apuntes(["fotos"])["fotos"].retenida,
      "2026-11-05 18:20:00")

# Un registro sin la clave y sin un código que se lea: no consta como buena, así que manda el
# log. Si es el freno de un espejo, queda retenida (un código que falta no vale 0).
for raro in ({}, {"codigo": True}, {"codigo": "siete"}):
    with sandbox():
        nombre = "fotos_20261105-182000.log"
        (model.LOG_DIR / nombre).write_text(ESPEJO_UP, encoding="utf-8")
        store.write_json(results.ruta_estado(), {"parejas": {"fotos": {
            "cuando": "2026-11-05 18:20:00", "log": nombre, "buena": None, **raro}}})
        ctx, _, _ = lanzar_main(["fotos"])
        c(f"un registro antiguo con el log del freno y código {raro.get('codigo', 'ausente')!r} "
          "queda retenido", sorted(ctx.retenidas), ["fotos"])

with sandbox():
    nombre = "fotos_20261105-182000.log"
    (model.LOG_DIR / nombre).write_text(RED_RECHAZADA, encoding="utf-8")
    store.write_json(results.ruta_estado(), {"parejas": {"fotos": {
        "cuando": "2026-11-05 18:20:00", "codigo": 1, "log": nombre, "buena": None}}})
    ctx, _, _ = lanzar_main(["fotos"])
    c("un fallo antiguo que no era el freno no retiene", dict(ctx.retenidas), {})
    c("  y queda apuntado como no retenida", (results.apuntes(["fotos"])["fotos"].sabida,
                                              results.apuntes(["fotos"])["fotos"].retenida),
      (True, None))

with sandbox():
    results.ruta_estado().write_text("{roto", encoding="utf-8")
    c("un last_run.json ilegible no retiene a nadie",
      dict(lanzar_main(["fotos"])[0].retenidas), {})

# ---- Una pareja que deja de ser espejo ---------------------------------------------------------

with sandbox():
    correr(SUBIDA, rc=7, texto_log=ESPEJO_UP)
    c("deja de ser espejo y no arrastra la retención",
      dict(lanzar_main(["fotos"], toml=TOML_FOTOS_BISYNC)[0].retenidas), {})

# ---- La ventana y la consola --------------------------------------------------------------

import tomllib

import ui
from ui.console import ConsoleFrontend

with sandbox():
    cfg = model.parse_config(tomllib.loads(TOML))
    log_fotos = model.LOG_DIR / "fotos_20261105-182000.log"
    log_fotos.write_text(ESPEJO_UP, encoding="utf-8")
    results.apuntar("fotos", 7, log_fotos, freno=True)
    c("la lista dice cuál está retenida y cuál pide resync", ui.pair_status_notes(cfg),
      {"fotos": "retenida tras el freno", "notas": "requiere resync"})
    vistos = []
    c("«Lanzarla» añade --resume",
      ui.manual_args(cfg, ["fotos"], lambda *a: vistos.append("resync") or True,
                     lambda textos: vistos.append(textos) or True), ["fotos", "--resume"])
    c("  preguntando con el texto de revision, y sin preguntar por un resync que no hay", vistos,
      [[revision.texto_retencion(cfg.pairs[0], revision.retencion(cfg.pairs[0]))]])
    c("«Saltarla» deja los nombres (y sync.py la salta)",
      ui.manual_args(cfg, ["fotos", "copia"], lambda *a: True, lambda t: False),
      ["fotos", "copia"])
    c("aprobar el resync no aprueba borrados, ni al revés",
      (ui.manual_args(cfg, ["notas", "fotos"], lambda *a: True, lambda t: False),
       ui.manual_args(cfg, ["notas", "fotos"], lambda *a: False, lambda t: True)),
      (["notas", "fotos", "--yes"], ["notas", "fotos", "--resume"]))
    c("quien no sabe preguntar por las retenidas no lanza ninguna",
      ui.manual_args(cfg, ["fotos"], lambda *a: True), ["fotos"])
    c("la consola deja que pregunte sync.py", ConsoleFrontend().approve_held(["x"]), False)
    results.ruta_estado().write_text("{roto", encoding="utf-8")
    c("un registro ilegible no impide sincronizar",
      (ui.manual_args(cfg, ["fotos"], lambda *a: True, lambda t: True),
       "fotos" in ui.pair_status_notes(cfg)),
      (["fotos"], False))

raise SystemExit(c.report())
