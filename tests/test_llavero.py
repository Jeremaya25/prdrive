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
"""

import contextlib
import hashlib
import io
import struct
import sys
from pathlib import Path

from _harness import Checks, sandbox

import sync
import ui
from common import bisync, catalog, config_file, kdbx, llavero, model, revision
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
    c("  ni regla en la de la raíz", sin.pairs[0].reglas, ())

    # las parejas de la raíz entera no se llevan el llavero
    c("la pareja de la raíz recibe la regla, la primera",
      cfg.pairs[0].reglas, (model.REGLA_SIN_LLAVERO,))
    c("  como --exclude en un espejo", sync.filter_args(cfg.pairs[0], None)[:2],
      ["--exclude", "/.keychain/**"])
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
