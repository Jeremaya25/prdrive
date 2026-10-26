#!/usr/bin/env python3
"""El llavero (`common/llavero.py`, y su pareja en `common/model.py`).

Sin equipo y sin red: rclone se simula como en `test_run_pair.py`, y lo que toca
el equipo se sustituye. Lo que se sujeta:
- La pareja que sale de `[keychain]`: dónde va, con qué flags, que el TOML no la
  cambia, que su nombre queda reservado y que las parejas de la raíz entera no
  se llevan `.keychain/`.
- Sus filtros, en su orden: solo viajan las bases y el compañero fijo.
- Antes de cada pasada: el compañero fijo se pone si falta, siempre con los
  mismos bytes, y una base que no está entera no se sube.
- El llavero se resincroniza solo, sin que nadie lo apruebe; las demás
  parejas, no.
- El compañero fijo lleva siempre la misma hora, la de `llavero.LEEME_HORA` (#115).
- Un freno de «han cambiado todos los ficheros» se repite una vez con `--force`,
  solo en el llavero, y nunca dos veces en la misma pasada (#115).
- Con el remoto vacío (su carpeta borrada a mano) se vuelve a crear la carpeta y
  se repite una vez con `--resync`, también solo en el llavero.
"""

import contextlib
import hashlib
import io
import os
import struct
import sys
import time
from pathlib import Path

from _harness import Checks, sandbox

import sync
import ui
from common import bisync, catalog, config_file, frenos, kdbx, llavero, model, orden, revision
from common.model import ConfigError

c = Checks("el llavero")

DEF = {"remote": "nas", "device_remote": "disp",
       "catalog_path": "/prdrive-catalog/pairs.toml",
       "flags": {"conflict-resolve": "larger", "checkers": 2},
       "exclude": ["**/.git/**"]}
TODO = {"name": "todo", "local": ".", "remote_path": "/copia", "mode": "up-mirror"}
NOTAS = {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas"}
LLAVE = {"base": "personal.kdbx", "fichero_llave": True, "nombre_llave": "personal.keyx"}


def config(llave=LLAVE, pares=(TODO, NOTAS), defaults=DEF):
    """Devuelve el config con esas parejas y ese `[keychain]` (o ninguno)."""
    data = {"defaults": dict(defaults), "pair": [dict(p) for p in pares]}
    if llave is not None:
        data["keychain"] = dict(llave)
    return model.parse_config(data)


def rechaza(etiqueta, hacer, fragmento):
    """Comprueba que `hacer()` lance `ConfigError` con ese fragmento."""
    try:
        hacer()
        c(etiqueta, "no lanzó", "ConfigError")
    except ConfigError as e:
        c.contains(etiqueta, str(e), fragmento)


def base_kdbx4() -> bytes:
    """Una base KDBX 4 de mentira, entera (la forma de `test_kdbx.py`)."""
    cab = struct.pack("<IIHH", kdbx.FIRMA_1, kdbx.FIRMA_2, 1, 4)
    for campo, valor in ((4, b"\x07" * 32), (0, b"\r\n\r\n")):
        cab += struct.pack("<BI", campo, len(valor)) + valor
    datos = cab + hashlib.sha256(cab).digest() + b"\x01" * 32
    for bloque in (b"x" * 100, b""):
        datos += b"\x02" * 32 + struct.pack("<i", len(bloque)) + bloque
    return datos


# la pareja que sale de [keychain]
with sandbox():
    cfg = config()
    pareja = cfg.pareja_llavero
    c("con [keychain] hay pareja del llavero, la última", (cfg.pairs[-1].name, pareja.llavero),
      (model.LLAVERO, True))
    c("  en .keychain/ del dispositivo", pareja.local, ".keychain")
    c("  y en keychain/ de la carpeta del catálogo, en su remote",
      pareja.remote_endpoint, "nas:/prdrive-catalog/keychain")
    c("  bisync con versiones", (pareja.mode.name, pareja.versions), ("bisync", True))
    c("  el perdedor de un conflicto se queda al lado, numerado (H-14)",
      pareja.flags["conflict-loser"], "num")
    c("  y un --resync se queda con la más nueva (H-13)", pareja.flags["resync-mode"], "newer")
    c("  sin los flags ni los filtros de [defaults]",
      ("checkers" in pareja.flags, pareja.flags["conflict-resolve"], pareja.excludes),
      (False, "newer", ()))
    c("  con el device_remote del dispositivo", pareja.device_remote, "disp")
    c("no sale entre las parejas que se eligen", cfg.names, ["todo", "notas"])
    c("  ni en del_usuario", [p.name for p in cfg.del_usuario], ["todo", "notas"])
    c("  pero sync.py la encuentra por su nombre", cfg.select([model.LLAVERO])[0].llavero, True)
    c("el combine lleva su carpeta",
      ".keychain=" in cfg.pen_environment()["RCLONE_CONFIG_DISP_UPSTREAMS"], True)
    c("la tabla llega al config", cfg.llavero["nombre_llave"], "personal.keyx")

    c("pairs.toml y remote.toml son la misma carpeta, y el mismo remoto",
      config(defaults={**DEF, "catalog_path": "/prdrive-catalog/remote.toml"})
      .pareja_llavero.remote_endpoint, "nas:/prdrive-catalog/keychain")
    c("con catalog_remote, ese", config(defaults={**DEF, "catalog_remote": "cat"})
      .pareja_llavero.remote_endpoint, "cat:/prdrive-catalog/keychain")
    c("un catálogo en la raíz del remote", config(defaults={"remote": "nas",
                                                             "catalog_path": "remote.toml"})
      .pareja_llavero.remote_endpoint, "nas:keychain")
    c("sin catalog_path, el de fábrica", config(defaults={"remote": "nas"})
      .pareja_llavero.remote_endpoint,
      "nas:" + catalog.partir(model.DEFAULT_CATALOG_PATH)[0] + "keychain")

    sin = config(llave=None)
    c("sin [keychain] no hay pareja del llavero", (sin.pareja_llavero, sin.llavero), (None, None))
    c("  ni la regla del llavero en la de la raíz (solo la del programa)",
      sin.pairs[0].reglas, (model.REGLA_SIN_PROGRAMA,))

    # las parejas de la raíz entera no se llevan el llavero
    c("la pareja de la raíz recibe la regla, detrás de la del programa",
      cfg.pairs[0].reglas, (model.REGLA_SIN_PROGRAMA, model.REGLA_SIN_LLAVERO))
    c("  como --exclude en un espejo", orden.filter_args(cfg.pairs[0], None)[:4],
      ["--exclude", f"/{model.APP_DIR.name}/**", "--exclude", "/.keychain/**"])
    c("  y una pareja de una carpeta no", cfg.pairs[1].reglas, ())
    raiz_bi = config(pares=({"name": "raiz", "local": ".", "remote_path": "/r",
                             "include": ["**/*.md"]},)).pairs[0]
    reglas = bisync.filters_content(raiz_bi).splitlines()
    c("  y en bisync va delante de los + de la pareja",
      reglas.index("- /.keychain/**") < reglas.index("+ **/*.md"), True)

    # lo que no vale
    rechaza("una pareja del usuario no puede llamarse como la del llavero",
            lambda: config(pares=({**NOTAS, "name": model.LLAVERO},)), "Renómbrala")
    c("  sin llavero sí puede", config(llave=None, pares=({**NOTAS, "name": model.LLAVERO},))
      .names, [model.LLAVERO])
    for mala in ("", "personal", "../fuera.kdbx", "sub/personal.kdbx", ".oculta.kdbx", 3,
                 "Personal.KDBX", ".kdbx"):
        rechaza(f"una base que no es un nombre suelto .kdbx no vale ({mala!r})",
                lambda m=mala: config(llave={"base": m}), "nombre suelto")
    rechaza("[keychain] tiene que ser una tabla", lambda: model.parse_config(
        {"pair": [NOTAS], "keychain": "personal.kdbx"}), "tabla")

# sus filtros, en su orden
with sandbox():
    contenido = bisync.filters_content(config().pareja_llavero).splitlines()
    c("los filtros del llavero, en su orden: versiones, copia de antes de guardar, "
      "bases, compañero y nada más",
      [l for l in contenido if not l.startswith("#")],
      ["- .prversions/**", "- *.old.kdbx", "+ *.kdbx", "+ LEEME.txt", "- **"])

# el TOML conserva [keychain] al reescribirse
with sandbox():
    raw = {"defaults": DEF, "pair": [TODO, NOTAS], "keychain": LLAVE}
    c("config_file conserva [keychain] al guardar",
      config_file.load_raw(config_file.save(raw)).get("keychain"), LLAVE)

# antes de cada pasada


def correr(pareja, rc=0, aprobado=True):
    """Ejecuta run_pair con rclone simulado. Devuelve (rc, salida, órdenes)."""
    ordenes = []

    def execute_simulado(ctx, cmd, logfile=None):
        """Apunta la orden y escribe el log como rclone."""
        ordenes.append(cmd)
        for i, arg in enumerate(cmd):
            if arg == "--log-file":
                Path(cmd[i + 1]).write_text("simulado\n", encoding="utf-8")
        return rc

    original, sync.execute = sync.execute, execute_simulado
    try:
        ctx = sync.RunContext(binary="RCLONE", env={}, resync_approved=aprobado)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            salida = sync.run_pair(ctx, pareja)
        return salida, buf.getvalue(), ordenes
    finally:
        sync.execute = original


esperas: list[float] = []
llavero.dormir = esperas.append

with sandbox() as root:
    pareja = config().pareja_llavero
    rc, salida, ordenes = correr(pareja)
    carpeta = root / ".keychain"
    c("la primera pasada crea .keychain/ y corre", (rc, carpeta.is_dir(), len(ordenes)),
      (0, True, 2))
    c("  y antes crea su carpeta en el remoto, que nadie más crea (bisync --resync la exige)",
      ordenes[0][:3], ["RCLONE", "mkdir", pareja.dest])
    c("  con su compañero fijo", (carpeta / llavero.LEEME).read_bytes(),
      llavero.LEEME_TEXTO.encode("utf-8"))
    c("  con \\n en todos los sistemas, para que dos dispositivos dejen el mismo",
      b"\r\n" in (carpeta / llavero.LEEME).read_bytes(), False)
    c("  y su conflicto se queda al lado", "--conflict-loser" in ordenes[-1]
      and ordenes[-1][ordenes[-1].index("--conflict-loser") + 1], "num")
    c("  ese primer --resync se queda con la más nueva (H-13)",
      ("--resync" in ordenes[-1], "--resync-mode" in ordenes[-1]
       and ordenes[-1][ordenes[-1].index("--resync-mode") + 1]), (True, "newer"))

    # Con baseline, una pasada normal: sin --resync-mode, que rclone toma por
    # --resync (y entonces no deja copia de conflicto: gana la más nueva y la
    # otra cae en .prversions/ sin que nadie la combine). Salió con rclone de
    # verdad.
    pareja.workdir.mkdir(parents=True, exist_ok=True)
    for sufijo in (bisync.PATH1_SUFFIX, bisync.PATH2_SUFFIX):
        (pareja.workdir / f"{bisync.expected_prefix(pareja)}{sufijo}").write_text(
            "listado\n", encoding="utf-8")
    ffile = bisync.filters_file_for(pareja)
    Path(str(ffile) + ".md5").write_text(hashlib.md5(ffile.read_bytes()).hexdigest(),
                                         encoding="utf-8")
    rc, salida, ordenes = correr(pareja, aprobado=False)
    c("con baseline, la pasada es un bisync normal: ni mkdir, ni --resync, ni --resync-mode",
      (rc, len(ordenes), "--resync" in ordenes[-1], "--resync-mode" in ordenes[-1]),
      (0, 1, False, False))
    c("  y su conflicto sigue quedándose al lado",
      ordenes[-1][ordenes[-1].index("--conflict-loser") + 1], "num")

    # Tras «Combinar», el freno de borrados (25 % del listado anterior) lo
    # pisa quitar una sola copia: el llavero tiene tres o cuatro ficheros.
    # Las líneas son las de rclone v1.75.1 (`indent()`, cmd/bisync/log.go).
    def borrado(lado, nombre):
        """Una línea de bisync que dice que `nombre` ya no está en ese lado."""
        return (f"2026/10/05 17:38:16 INFO  : - {lado}             File was deleted"
                f"                            - {nombre}")
    ABORTO = ("2026/10/05 17:38:16 ERROR : Safety abort: too many deletes (>25%, 2 of 4) on "
              "Path1 \"disp{uR5dC}:.keychain/\". Run with --force if desired.")
    copia1, copia2 = "personal.conflicto-dispositivo1.kdbx", "personal.conflicto-remoto2.kdbx"
    c("lo borrado, si son solo copias de conflicto de una base (de los dos lados)",
      llavero.solo_copias_borradas("\n".join([borrado("Path1", copia1),
                                               borrado("Path2", copia2), ABORTO]), pareja),
      [copia1, copia2])
    for que, lineas in (("la base", [borrado("Path1", copia1), borrado("Path2", "personal.kdbx")]),
                        ("el compañero fijo", [borrado("Path1", llavero.LEEME)]),
                        ("un nombre entre comillas", [borrado("Path1", '"personal.conflicto-remoto1\\x01.kdbx"')]),
                        ("nada", [])):
        c(f"  con {que} entre lo borrado, nada", llavero.solo_copias_borradas(
            "\n".join([*lineas, ABORTO]), pareja), None)

    def correr_abortando(lineas):
        """run_pair con una primera pasada que aborta por el freno y una segunda que va bien."""
        ordenes = []

        def execute_simulado(ctx, cmd, logfile=None):
            ordenes.append(cmd)
            texto = "\n".join([*lineas, ABORTO]) if len(ordenes) == 1 else "bien"
            Path(cmd[cmd.index("--log-file") + 1]).write_text(texto + "\n", encoding="utf-8")
            return 7 if len(ordenes) == 1 else 0

        original, sync.execute = sync.execute, execute_simulado
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = sync.run_pair(sync.RunContext(binary="RCLONE", env={}), pareja)
            return rc, buf.getvalue(), ordenes
        finally:
            sync.execute = original

    def freno(cmd):
        return cmd[cmd.index("--max-delete") + 1]
    rc, salida, ordenes = correr_abortando([borrado("Path1", copia1), borrado("Path2", copia2)])
    c("si solo pisan el freno copias de conflicto, la pasada se repite sin él, una vez",
      (rc, len(ordenes), freno(ordenes[0]), freno(ordenes[1]), "--resync" in ordenes[1]),
      (0, 2, "25", str(llavero.FRENO_SIN_COPIAS), False))
    c.contains("  y lo dice", salida, "se repite la pasada sin el freno de borrados")
    rc, salida, ordenes = correr_abortando([borrado("Path1", copia1), borrado("Path1", "personal.kdbx")])
    c("con la base entre lo borrado, el freno manda: no se repite", (rc, len(ordenes)), (7, 1))

    # «Han cambiado todos los ficheros» (#115): lo de LL-6 de las pruebas del 12/10, con el
    # log tal como sale (Pruebas.kdbx y LEEME.txt, los dos ficheros del llavero, con otra
    # hora en el remoto). rclone se para en `operations.go` y `--force` lo salta; el llavero
    # guarda al perdedor en `.prversions/`, así que se repite UNA vez.
    TODOS = (
        "2026/10/12 17:38:16 INFO  : - Path2             File changed: time (newer)          - LEEME.txt\n"
        "2026/10/12 17:38:16 INFO  : - Path2             File changed: time (newer)          - Pruebas.kdbx\n"
        "2026/10/12 17:38:16 INFO  : Path2:    2 changes:    0 new,    2 modified,    0 deleted\n"
        "2026/10/12 17:38:16 ERROR : Safety abort: all files were changed on Path2 "
        "\"nas:prdrive-catalog/keychain/\". Run with --force if desired.\n"
        "2026/10/12 17:38:16 NOTICE: Bisync aborted. Please try again.\n"
        "2026/10/12 17:38:16 NOTICE: Failed to bisync: all files were changed")

    def correr_pasadas(par, *pasadas, aprobado=False, dry_run=False, keep_logs=False):
        """run_pair con rclone simulado: la pasada N-ésima acaba con `(rc, texto del log)`."""
        ordenes = []

        def execute_simulado(ctx, cmd, logfile=None):
            hechas = sum(1 for o in ordenes if o[1] == "bisync")
            ordenes.append(cmd)
            if cmd[1] != "bisync":                      # el mkdir de la carpeta del remoto
                return 0
            rc_, texto = pasadas[min(hechas, len(pasadas) - 1)]
            Path(cmd[cmd.index("--log-file") + 1]).write_text(texto + "\n", encoding="utf-8")
            return rc_

        original, sync.execute = sync.execute, execute_simulado
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc_ = sync.run_pair(sync.RunContext(binary="RCLONE", env={},
                                                    resync_approved=aprobado, dry_run=dry_run,
                                                    keep_logs=keep_logs), par)
            return rc_, buf.getvalue(), ordenes
        finally:
            sync.execute = original

    # Lo que dice rclone de una simulación (`--dry-run`): lo que copiaría y, si los hay, los borrados.
    SIMULADA = ("2026/10/15 10:00:00 NOTICE: Pruebas.kdbx: Skipped copy as --dry-run is set (size 100)\n"
                "2026/10/15 10:00:00 NOTICE: LEEME.txt: Skipped copy as --dry-run is set (size 200)")
    SIMULADA_BORRA = (SIMULADA + "\n2026/10/15 10:00:00 NOTICE: Pruebas.kdbx: "
                      "Skipped move into backup dir as --dry-run is set")

    def bisyncs(ordenes):
        """Las órdenes de bisync, como `(simulada, con --force)`, en el orden en que corrieron."""
        return [("--dry-run" in o, "--force" in o) for o in ordenes if o[1] == "bisync"]

    rc, salida, ordenes = correr_pasadas(pareja, (1, TODOS), (0, SIMULADA), (0, "bien"))
    c("«han cambiado todos» en el llavero: se simula con --force y, si no borra nada, se repite una vez",
      (rc, bisyncs(ordenes)), (0, [(False, False), (True, True), (False, True)]))
    real = [o for o in ordenes if o[1] == "bisync"][2]
    c("  sin --resync, que no lo necesita, y con el freno de borrados que tenía",
      ("--resync" in real, freno(real)), (False, "25"))
    c.contains("  y lo dice, con qué hace y por qué es seguro", salida,
               "se repite la pasada una vez con --force")
    c.contains("  (cada lado guarda lo que pierda en las versiones)", salida, model.VERSIONS_DIR)
    c("  el log de la pasada parada se queda, que es la prueba de por qué se forzó",
      any("all files were changed" in p.read_text(encoding="utf-8")
          for p in model.LOG_DIR.glob("keychain*")), True)

    # `--force` salta también el freno de borrados y la repetición es otra ejecución de rclone: lo
    # que borrara, no frenaría. Antes de forzar se simula, y si borrara algo no se fuerza.
    rc, salida, ordenes = correr_pasadas(pareja, (1, TODOS), (0, SIMULADA_BORRA), (0, "bien"))
    c("  si forzarla borraría algo, no se fuerza: el freno manda y queda el fallo",
      (rc, bisyncs(ordenes)), (1, [(False, False), (True, True)]))
    c.contains("  y lo dice, con lo que borraría", salida, "Pruebas.kdbx")
    rc, salida, ordenes = correr_pasadas(pareja, (1, TODOS), (7, "Failed to bisync: no sé"), (0, "bien"))
    c("  si la simulación falla, no se fuerza lo que no se ha podido comprobar",
      (rc, bisyncs(ordenes)), (1, [(False, False), (True, True)]))

    rc, salida, ordenes = correr_pasadas(pareja, (1, TODOS), (0, SIMULADA), (1, TODOS))
    c("  si la repetida vuelve a pararse, no hay otra: una vez por pasada, nunca dos seguidas",
      (rc, len(bisyncs(ordenes))), (1, 3))
    explicacion = [linea for linea in salida.splitlines() if linea.strip().startswith(">>")]
    c("  y el fallo no queda mudo: lo explica, con el llavero por su nombre y sin ofrecer forzar",
      (len(explicacion), "llavero" in " ".join(explicacion),
       frenos.COMO_FORZAR in " ".join(explicacion), "--resync" in " ".join(explicacion)),
      (1, True, False, True))
    c("  sin dar por hecho que ya se repitió con --force (a veces no se pudo o no tocaba)",
      "ya ha repetido" in " ".join(explicacion), False)

    rc, salida, ordenes = correr_pasadas(pareja, (1, TODOS.replace("Path2", "Path1")),
                                         (0, SIMULADA), (0, "bien"))
    c("  se repite igual si los que han cambiado son los de este lado",
      (rc, len(bisyncs(ordenes))), (0, 3))

    # En un `--dry-run` (que bisync para igual con ese error) no hay repetición de verdad: la
    # simulación con --force ES la repetición, sin una tercera ejecución, sin dejar un log en `logs/`
    # que cuente para los 20 de la pareja y diciendo lo que se haría en una pasada de verdad.
    for p in model.LOG_DIR.glob("keychain*"):
        p.unlink()
    rc, salida, ordenes = correr_pasadas(pareja, (1, TODOS), (0, SIMULADA), (0, "bien"), dry_run=True)
    c("simulacro de «han cambiado todos»: bisync corre dos veces, no tres, las dos simuladas",
      (rc, bisyncs(ordenes)), (0, [(True, False), (True, True)]))
    c("  la segunda, la simulación, es la repetición: lleva --force y no --resync",
      ("--force" in ordenes[1], "--resync" in ordenes[1]), (True, False))
    c.contains("  y lo dice en condicional, que no ocurre", salida,
               "en una pasada de verdad se repetiría una vez con --force (no borraría nada)")
    c("  sin anunciar una repetición que no ocurre", "se repite la pasada" in salida, False)
    c.contains("  (cada lado guarda lo que pierda en las versiones)", salida, model.VERSIONS_DIR)
    c("  una simulación que acaba bien no deja log en logs/", list(model.LOG_DIR.glob("keychain*")), [])
    c.contains("  y acaba bien", salida, f"[{model.LLAVERO}] OK.")

    rc, salida, ordenes = correr_pasadas(pareja, (1, TODOS), (0, SIMULADA), (0, "bien"),
                                         dry_run=True, keep_logs=True)
    guardados = list(model.LOG_DIR.glob("keychain*"))
    c("  con --keep-logs el log de la pasada parada sí se guarda (y solo ese), y se dice",
      (rc, len(bisyncs(ordenes)), len(guardados),
       any("all files were changed" in g.read_text(encoding="utf-8") for g in guardados),
       any(g.name in salida for g in guardados)), (0, 2, 1, True, True))
    for g in guardados:
        g.unlink()

    rc, salida, ordenes = correr_pasadas(pareja, (1, TODOS), (0, SIMULADA_BORRA), (0, "bien"),
                                         dry_run=True)
    c("  si forzarla borraría algo, el simulacro dice que el freno manda y el fallo se queda",
      (rc, bisyncs(ordenes), "no se fuerza, el freno manda" in salida),
      (1, [(True, False), (True, True)], True))
    c("  (ese fallo sí deja su log: es una pasada que ha fallado)",
      len(list(model.LOG_DIR.glob("keychain*"))), 1)
    for g in model.LOG_DIR.glob("keychain*"):
        g.unlink()

    rc, salida, ordenes = correr_pasadas(
        pareja, (7, "\n".join([borrado("Path1", copia1), borrado("Path2", copia2), ABORTO])),
        (0, "bien"), dry_run=True)
    c("simulacro de un freno de borrados que solo pisan copias de conflicto: también en condicional",
      (rc, bisyncs(ordenes), "se repite la pasada sin el freno" in salida,
       "en una pasada de verdad se repetiría una vez sin el freno de borrados" in salida),
      (0, [(True, False), (True, False)], False, True))
    c("  la repetición simulada lleva el freno de las copias y la pasada no deja log",
      (freno(ordenes[1]), list(model.LOG_DIR.glob("keychain*"))), (str(llavero.FRENO_SIN_COPIAS), []))

    # Con el freno de copias de conflicto ya se ha repetido: una sola repetición en toda la pasada.
    rc, salida, ordenes = correr_pasadas(
        pareja, (7, "\n".join([borrado("Path1", copia1), ABORTO])), (1, TODOS), (0, "bien"))
    c("  tras repetir sin el freno de borrados no se repite otra vez con --force, ni se simula",
      (rc, bisyncs(ordenes)), (1, [(False, False), (False, False)]))

    rc, salida, ordenes = correr_pasadas(pareja, (1, "Failed to bisync: lo que sea"), (0, "bien"))
    c("  otro fallo cualquiera del llavero no se repite", (rc, len(ordenes)), (1, 1))

    # La carpeta del llavero se borró a mano en el remoto: con baseline, la pasada es normal, nadie
    # vuelve a crear `keychain/`, y rclone no sincroniza contra un lado vacío (`checkListing()`).
    # Con `--resilient` el error es «reintentable»: no aparta los listados y la pasada siguiente
    # falla igual, para siempre. El log, tal como sale con rclone v1.75.2 y dos carpetas locales.
    VACIO = (
        "2026/10/16 08:52:39 ERROR : Empty current Path2 listing. Cannot sync to an empty directory: "
        "C:\\prdrive\\.prdrive\\state\\keychain\\disp_.keychain..nas_prdrive-catalog_keychain.path2.lst-new\n"
        "2026/10/16 08:52:39 ERROR : Bisync critical error: empty current Path2 listing: "
        "C:\\prdrive\\.prdrive\\state\\keychain\\disp_.keychain..nas_prdrive-catalog_keychain.path2.lst-new\n"
        "2026/10/16 08:52:39 ERROR : Bisync aborted. Error is retryable without --resync due to "
        "--resilient mode.\n"
        "2026/10/16 08:52:39 NOTICE: Failed to bisync: bisync aborted")
    c("un remoto vacío se reconoce en el log", llavero.remoto_vacio(VACIO), True)
    c("  y solo el remoto: el lado del dispositivo nunca está vacío (LEEME.txt)",
      llavero.remoto_vacio(VACIO.replace("Path2", "Path1")), False)
    for p in model.LOG_DIR.glob("keychain*"):
        p.unlink()
    rc, salida, ordenes = correr_pasadas(pareja, (7, VACIO), (0, "bien"))
    c("con el remoto vacío, se vuelve a crear su carpeta y se repite la pasada una vez con --resync",
      (rc, [o[1] for o in ordenes], "--resync" in ordenes[-1]), (0, ["bisync", "mkdir", "bisync"], True))
    c("  que se queda con la más nueva, como cualquier resync del llavero, y no fuerza nada",
      (ordenes[-1][ordenes[-1].index("--resync-mode") + 1], "--force" in ordenes[-1]),
      ("newer", False))
    c("  la carpeta, la del remoto del llavero", ordenes[1][:3], ["RCLONE", "mkdir", pareja.dest])
    c.contains("  y lo dice, con qué hace", salida, "se repite la pasada una vez con --resync")
    c.contains("  (lo que pise queda en las versiones)", salida, model.VERSIONS_DIR)
    c("  el log de la pasada parada se queda: dice por qué se rehízo el remoto",
      any("Empty current Path2 listing" in p.read_text(encoding="utf-8")
          for p in model.LOG_DIR.glob("keychain*")), True)
    rc, salida, ordenes = correr_pasadas(pareja, (7, VACIO), (7, VACIO))
    c("  si la repetida vuelve a fallar, no hay otra", (rc, len(bisyncs(ordenes))), (7, 2))
    rc, salida, ordenes = correr_pasadas(pareja, (7, VACIO.replace("Path2", "Path1")), (0, "bien"))
    c("  con el lado del dispositivo vacío, no se repite", (rc, len(ordenes)), (7, 1))
    rc, salida, ordenes = correr_pasadas(
        pareja, (7, "\n".join([borrado("Path1", copia1), ABORTO])), (7, VACIO), (0, "bien"))
    c("  tras repetir sin el freno de borrados no se repite otra vez con --resync",
      (rc, [o[1] for o in ordenes]), (7, ["bisync", "bisync"]))

    # Ni en un resync: ahí no hay listado anterior con el que comparar, y `--force` no se pide con él.
    sin_listados = [p for p in pareja.workdir.iterdir()]
    for p in sin_listados:
        p.rename(p.with_name(p.name + ".guardado"))
    rc, salida, ordenes = correr_pasadas(pareja, (1, TODOS), (0, "bien"))
    c("  un --resync no se repite con --force", (rc, [o[1] for o in ordenes],
                                                 any("--force" in o for o in ordenes)),
      (1, ["mkdir", "bisync"], False))
    rc, salida, ordenes = correr_pasadas(pareja, (7, VACIO), (0, "bien"))
    c("  ni con otro --resync si el remoto sigue vacío", (rc, [o[1] for o in ordenes]),
      (7, ["mkdir", "bisync"]))
    for p in sin_listados:
        p.with_name(p.name + ".guardado").rename(p)

    # Solo el llavero: otra pareja bisync con el mismo log no se fuerza nunca.
    otra = config().pairs[1]
    otra.workdir.mkdir(parents=True, exist_ok=True)
    for sufijo in (bisync.PATH1_SUFFIX, bisync.PATH2_SUFFIX):
        (otra.workdir / f"{bisync.expected_prefix(otra)}{sufijo}").write_text(
            "listado\n", encoding="utf-8")
    otro_filtro = bisync.filters_file_for(otra)
    Path(str(otro_filtro) + ".md5").write_text(
        hashlib.md5(otro_filtro.read_bytes()).hexdigest(), encoding="utf-8")
    (otra.local_abs).mkdir(parents=True, exist_ok=True)
    rc, salida, ordenes = correr_pasadas(otra, (1, TODOS), (0, "bien"))
    c("  otra pareja con ese log no se repite ni se fuerza", (rc, len(ordenes),
                                                              any("--force" in o for o in ordenes)),
      (1, 1, False))
    rc, salida, ordenes = correr_pasadas(otra, (7, VACIO), (0, "bien"))
    c("  ni se resincroniza sola con el remoto vacío: eso lo decide una persona",
      (rc, [o[1] for o in ordenes]), (7, ["bisync"]))

    # `--force` es de rclone; la comprobación de la carpeta local es de `_bisync_preflight()`, que
    # va antes de la primera orden: con baseline y sin carpeta, ni se llega a repetir.
    oculta = carpeta.with_name(".keychain-fuera")
    carpeta.rename(oculta)
    try:
        rc, salida, ordenes = correr_pasadas(pareja, (1, TODOS), (0, "bien"))
    finally:
        oculta.rename(carpeta)
    c("  con baseline y sin la carpeta local, el aborto con 2 sigue mandando: ni rclone, ni --force",
      (rc, ordenes), (2, []))

    # Tras un conflicto que gana el remoto, rclone (v1.75.1) deja la base fuera
    # de los dos listados (`modifyListing()`): se vuelve a pasar en seguida,
    # con las dos iguales, para que la apunte. Líneas como las de rclone.
    def listar(*nombres):
        """Deja el listado path1 con esos ficheros, como lo escribe bisync."""
        lineas = ["# bisync listing v1 from 2026-10-05T17:59:22.695758764+0000"] + [
            f'-     1790 - - 2026-10-05T17:59:20.865286426+0000 "{n}"' for n in nombres]
        (pareja.workdir / f"{bisync.expected_prefix(pareja)}{bisync.PATH1_SUFFIX}").write_text(
            "\n".join(lineas) + "\n", encoding="utf-8")
    (carpeta / "personal.kdbx").write_bytes(base_kdbx4())
    (carpeta / copia1).write_bytes(base_kdbx4())
    listar(llavero.LEEME, copia1)
    c("una base de la unidad que rclone ha dejado fuera del listado",
      llavero.sin_listar(pareja), ["personal.kdbx"])
    rc, salida, ordenes = correr(pareja, aprobado=False)
    c("  se vuelve a pasar en seguida, sin --resync, para que la apunte",
      (rc, [o[1] for o in ordenes], "--resync" in ordenes[-1]), (0, ["bisync", "bisync"], False))
    c.contains("  y lo dice", salida, "otra pasada, ahora que están iguales")
    listar(llavero.LEEME, copia1, "personal.kdbx")
    rc, salida, ordenes = correr(pareja, aprobado=False)
    c("  con todas en el listado, una pasada", (llavero.sin_listar(pareja), len(ordenes)), ([], 1))
    listar(llavero.LEEME)
    ordenes.clear()
    real_execute = sync.execute
    sync.execute = lambda ctx, cmd, logfile=None: ordenes.append(cmd) or 0
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            sync.run_pair(sync.RunContext(binary="RCLONE", env={}, dry_run=True), pareja)
    finally:
        sync.execute = real_execute
    c("  con --dry-run, no (el listado de verdad no lo toca)", len(ordenes), 1)
    (carpeta / "personal.kdbx").unlink()
    (carpeta / copia1).unlink()
    for p in pareja.workdir.iterdir():
        p.unlink()

    (carpeta / llavero.LEEME).write_text("lo cambió alguien\n", encoding="utf-8")
    correr(pareja)
    c("un compañero cambiado no se toca", (carpeta / llavero.LEEME).read_text(encoding="utf-8"),
      "lo cambió alguien\n")

    (carpeta / "personal.kdbx").write_bytes(base_kdbx4())
    esperas.clear()
    rc, salida, ordenes = correr(pareja)
    c("con la base entera, se sube sin esperar", (rc, len(ordenes), esperas), (0, 2, []))

    (carpeta / "personal.kdbx").write_bytes(base_kdbx4()[:-20])
    rc, salida, ordenes = correr(pareja)
    c("con la base cortada, la pasada no corre", (rc, ordenes), (sync.LLAVERO_ROTO, []))
    c("  tras mirarla otra vez", esperas, [llavero.ESPERA_ENTERA])
    c.contains("  y se dice", salida, "la base no está entera")

    esperas.clear()
    llavero.dormir = lambda s: (esperas.append(s),
                                (carpeta / "personal.kdbx").write_bytes(base_kdbx4()))
    rc, salida, ordenes = correr(pareja)
    c("si el guardado acaba mientras se espera, se sube", (rc, len(ordenes)), (0, 2))
    llavero.dormir = esperas.append

    (carpeta / "personal.old.kdbx").write_bytes(b"cortada")
    (carpeta / ".prversions").mkdir()
    (carpeta / ".prversions" / "personal~20260101.kdbx").write_bytes(b"cortada")
    c("la copia de antes de guardar y las versiones no se miran",
      [r.name for r in llavero.bases(carpeta)], ["personal.kdbx"])
    (carpeta / "personal.conflicto-remoto1.kdbx").write_bytes(base_kdbx4())
    c("las de un conflicto sí", [r.name for r in llavero.bases(carpeta)],
      ["personal.conflicto-remoto1.kdbx", "personal.kdbx"])

# Las mayúsculas cuentan en todos los sistemas, como en los filtros de rclone (#174): en
# Windows `rglob("*.kdbx")` también devuelve `A.KDBX`, que no viaja nunca.
with sandbox() as root:
    carpeta = root / ".keychain"
    carpeta.mkdir()
    (carpeta / "A.KDBX").write_bytes(b"x")
    (carpeta / "b.kdbx").write_bytes(b"x")
    (carpeta / "c.OLD.kdbx").write_bytes(b"x")
    (carpeta / "d.old.kdbx").write_bytes(b"x")
    c("una `.KDBX` en mayúsculas no es base, y `.OLD.kdbx` sí viaja, como en rclone",
      [r.name for r in llavero.bases(carpeta)], ["b.kdbx", "c.OLD.kdbx"])

# El compañero fijo lleva la misma hora en todos los dispositivos (#115). Lo crea cada uno, y
# con la hora de ese momento el segundo en llegar parecía «más nuevo»: su primer --resync
# (resync-mode = newer) le cambiaba la hora al del remoto y el primer dispositivo veía sus dos
# ficheros cambiados («all files were changed»).
HORA_NS = llavero.LEEME_HORA * 1_000_000_000
c("la hora fija no cambia nunca (dos versiones con otra se pisarían la hora entre sí): 2000-01-01",
  llavero.LEEME_HORA, 946684800)
c("  es de un segundo entero y par, que FAT y exFAT guardan de 2 s en 2 s sin redondear",
  (isinstance(llavero.LEEME_HORA, int), llavero.LEEME_HORA % 2), (True, 0))
c("  y cae dentro de lo que guarda un FAT (de 1980 a 2107) y en el pasado",
  315532800 <= llavero.LEEME_HORA < 4354819200 and llavero.LEEME_HORA < time.time(), True)

with sandbox() as root:
    carpeta = root / ".keychain"
    rc, salida, ordenes = correr(config().pareja_llavero)
    leeme = carpeta / llavero.LEEME
    c("el que crea la primera pasada queda con la hora fija",
      (leeme.read_bytes(), leeme.stat().st_mtime_ns),
      (llavero.LEEME_TEXTO.encode("utf-8"), HORA_NS))

    ahora = time.time_ns()
    os.utime(leeme, ns=(ahora, ahora))
    llavero.preparar(config().pareja_llavero)
    c("uno que ya existía con el mismo texto y otra hora se corrige (es nuestro y no cambia)",
      (leeme.read_bytes(), leeme.stat().st_mtime_ns),
      (llavero.LEEME_TEXTO.encode("utf-8"), HORA_NS))

    # Una simulación no escribe en el dispositivo: no le corrige la hora a uno que ya existe.
    antigua = 1_700_000_000_000_000_000
    os.utime(leeme, ns=(antigua, antigua))
    llavero.preparar(config().pareja_llavero, simulacro=True)
    c("en una simulación no se le toca la hora a uno que ya existe",
      leeme.stat().st_mtime_ns, antigua)
    real_execute = sync.execute
    sync.execute = lambda ctx, cmd, logfile=None: 0
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            sync.run_pair(sync.RunContext(binary="RCLONE", env={}, dry_run=True,
                                          resync_approved=True), config().pareja_llavero)
    finally:
        sync.execute = real_execute
    c("  ni `sync.py keychain --dry-run`", leeme.stat().st_mtime_ns, antigua)
    llavero.preparar(config().pareja_llavero)
    c("  y la pasada de verdad sí, antes de pasar", leeme.stat().st_mtime_ns, HORA_NS)

    cerca = HORA_NS + 1_000_000_000          # a menos de la ventana de rclone (2 s): iguales
    os.utime(leeme, ns=(cerca, cerca))
    llavero.preparar(config().pareja_llavero)
    c("  con una hora que rclone ya da por igual (menos de 2 s), no se reescribe",
      leeme.stat().st_mtime_ns, cerca)

    leeme.write_text("lo cambió alguien\n", encoding="utf-8")
    otra = 1_700_000_000_000_000_000
    os.utime(leeme, ns=(otra, otra))
    llavero.preparar(config().pareja_llavero)
    c("con otro texto no se toca, ni el texto ni la hora",
      (leeme.read_text(encoding="utf-8"), leeme.stat().st_mtime_ns),
      ("lo cambió alguien\n", otra))

    leeme.unlink()
    real_utime = os.utime

    def utime_que_falla(*args, **kwargs):
        raise OSError("sin permiso")
    os.utime = utime_que_falla
    try:
        creado = llavero.asegurar_leeme(carpeta)
    finally:
        os.utime = real_utime
    c("si el sistema de ficheros no deja ponerle la hora, no tumba la pasada y el fichero se crea",
      (creado, leeme.read_bytes()), (True, llavero.LEEME_TEXTO.encode("utf-8")))

with sandbox():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        sync.list_pairs(config())
    c.contains("--list la enseña marcada", out.getvalue(), "el llavero, lo pone prdrive")

# el llavero se resincroniza solo; las demás parejas siguen esperando a que se apruebe
with sandbox():
    cfg = config()
    rc, salida, ordenes = correr(cfg.pareja_llavero, aprobado=False)
    c("sin baseline y sin nadie que lo apruebe, el llavero hace su --resync",
      (rc, [o[1] for o in ordenes], "--resync" in (ordenes or [[]])[-1]),
      (0, ["mkdir", "bisync"], True))
    c.contains("  y lo dice", salida, "se resincroniza solo")
    pedidas: list = []
    real_execute = sync.execute
    sync.execute = lambda ctx, cmd, logfile=None: pedidas.append(cmd) or 3
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = sync.crear_carpeta_remota(
                sync.RunContext(binary="RCLONE", env={}, dry_run=True), cfg.pareja_llavero)
    finally:
        sync.execute = real_execute
    c("  con --dry-run, crear la carpeta del remoto también es simulado",
      (rc, pedidas[0][-1]), (3, "--dry-run"))
    c.contains("  y un fallo solo se dice (la pasada lo dirá con su log)", buf.getvalue(),
               "No se ha podido crear")
    notas = cfg.pairs[1]
    rc, salida, ordenes = correr(notas, aprobado=False)
    c("una pareja del usuario, no: se salta", (rc, ordenes), (sync.SKIPPED, []))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        pregunta = sync.resolve_resync_approval([cfg.pareja_llavero], assume_yes=False)
    c("  ni se pregunta por el llavero", (pregunta, out.getvalue()), (False, ""))
    c("  ni sale como avería ni como «requiere resync»",
      ([h.pareja for h in revision.revisar(cfg) if h.clave == "resync"],
       model.LLAVERO in ui.pair_status_notes(cfg)), (["notas"], False))

sys.exit(c.report())
