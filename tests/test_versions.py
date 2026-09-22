#!/usr/bin/env python3
"""
Versionado por pareja: `.prversions/` dentro de la raíz del pair.

Lo que hay que sujetar aquí no es el formato del nombre —eso lo pone rclone con
`--suffix`— sino las dos cosas que pueden costar caro:

* **La regla de exclusión tiene que salir, y tiene que salir la primera.** No es
  una preferencia de filtrado: rclone rechaza un `--backup-dir` que solape con el
  destino («destination and parameter to --backup-dir mustn't overlap») y aborta
  la pareja con error crítico. Excluirla es la condición para que la carpeta
  pueda vivir dentro del pair. Y va la primera porque rclone aplica las reglas en
  orden y gana la que casa antes: detrás de un `+ **/*.md` no serviría de nada.

* **Encender o apagar `versions` no puede mover `expected_prefix()`.** Si lo
  moviera, un baseline se reaprovecharía bajo un nombre nuevo, que es la
  operación que provoca borrados masivos (ver el docstring de
  `bisync.shelve_baseline`).
"""

import sys
import tomllib
from datetime import date, datetime
from pathlib import Path

from _harness import Checks, sandbox

from common import bisync, catalog, config_file, model
from common.model import ConfigError

import sync
from ui import flags_editor, pair_editor, versions_editor

c = Checks("versionado: .prversions por pareja")


def pareja(extra=None, defaults=None, nombre="obsidian"):
    """Una pareja bisync con lo que se le añada encima."""
    raw = {"name": nombre, "local": "sync-data/obsidian",
           "remote_path": "/PJ/Obsidian", "mode": "bisync"}
    raw.update(extra or {})
    data = {"defaults": defaults or {"remote": "synology"}, "pair": [raw]}
    return model.parse_config(data).pairs[0]


with sandbox() as root:
    # --- 1. los dos extremos ---------------------------------------------------
    suelta = pareja({"versions": True})
    c("sin device_remote, path1 cuelga de la ruta local",
      suelta.versions_path1,
      f"{suelta.local_endpoint}/{model.VERSIONS_DIR}")
    c("path2 cuelga del remoto",
      suelta.versions_path2, f"synology:/PJ/Obsidian/{model.VERSIONS_DIR}")

    combinada = pareja({"versions": True},
                       defaults={"remote": "synology", "device_remote": "disp"})
    c("con device_remote, path1 va por el combine",
      combinada.versions_path1, f"disp:sync-data/obsidian/{model.VERSIONS_DIR}")
    c("path2 no cambia por llevar device_remote",
      combinada.versions_path2, f"synology:/PJ/Obsidian/{model.VERSIONS_DIR}")

    c("una pareja sin la clave no tiene versionado", pareja().versions, False)

    # --- 2. solo tiene sentido en bisync ---------------------------------------
    for modo in ("up", "down", "up-mirror", "down-mirror"):
        try:
            pareja({"versions": True, "mode": modo})
            salta = False
        except ConfigError as e:
            salta = modo in str(e) or "bisync" in str(e)
        c(f"versions=true en modo '{modo}' se rechaza al parsear", salta, True)

    # --- 3. la regla de exclusión, y la primera ---------------------------------
    texto = bisync.filters_content(pareja({"versions": True}))
    reglas = [l for l in texto.splitlines() if not l.startswith("#")]
    c("con versiones se emite la regla de exclusión",
      f"- {model.VERSIONS_DIR}/**" in reglas, True)
    c("y es la PRIMERA regla del fichero",
      reglas[0], f"- {model.VERSIONS_DIR}/**")

    con_incluir = pareja({"versions": True, "include": ["**/*.md"],
                          "exclude": ["basura/**"]})
    reglas = [l for l in bisync.filters_content(con_incluir).splitlines()
              if not l.startswith("#")]
    c("va por delante de los + de include, que si no ganarían ellos",
      reglas[0], f"- {model.VERSIONS_DIR}/**")
    c("los include siguen estando", "+ **/*.md" in reglas, True)
    c("y los exclude del usuario también", "- basura/**" in reglas, True)

    # --- 4. sin versiones, ni rastro -------------------------------------------
    texto = bisync.filters_content(pareja({"exclude": ["basura/**"]}))
    c("sin versiones no se emite la regla",
      model.VERSIONS_DIR in texto, False)

    # --- 5. los flags que pone sync.py ------------------------------------------
    ctx = sync.RunContext(binary="rclone", env={}, sello="~20260922-093000")
    versionada = pareja({"versions": True})
    cmd, _log = sync.build_command(ctx, versionada, None, False)
    orden = " ".join(cmd)

    def sigue_a(bandera):
        """El valor que va detrás de la bandera en la orden, o None."""
        return cmd[cmd.index(bandera) + 1] if bandera in cmd else None

    c("build_command pone --backup-dir1 con el extremo del lado local",
      sigue_a("--backup-dir1"), versionada.versions_path1)
    c("y --backup-dir2 con el del remoto",
      sigue_a("--backup-dir2"), versionada.versions_path2)
    c("el sello va en --suffix", sigue_a("--suffix"), "~20260922-093000")
    c("build_command pone --suffix-keep-extension",
      "--suffix-keep-extension" in cmd, True)
    c("y conflict-loser delete, para que el perdedor caiga ahí",
      "--conflict-loser delete" in orden, True)

    # El sello es uno por invocación: la misma marca para todas las parejas.
    cmd_b, _ = sync.build_command(ctx, pareja({"versions": True}, nombre="otra"),
                                  None, False)
    c("el sello es el mismo para otra pareja de la misma pasada",
      cmd.count("~20260922-093000"), cmd_b.count("~20260922-093000"))

    # --- 6. el [pair.flags] del usuario sigue mandando --------------------------
    mia = pareja({"versions": True, "flags": {"conflict-loser": "num"}})
    orden = " ".join(sync.build_command(ctx, mia, None, False)[0])
    c("un conflict-loser propio gana al que pone el versionado",
      "--conflict-loser num" in orden, True)
    c("y entonces no se cuela también el 'delete'",
      "--conflict-loser delete" in orden, False)

    # --- 7. sin versiones no aparece ninguno de los cinco -----------------------
    cmd, _ = sync.build_command(ctx, pareja(), None, False)
    for flag in ("--backup-dir1", "--backup-dir2", "--suffix",
                 "--suffix-keep-extension", "--conflict-loser"):
        c(f"sin versiones no se emite {flag}", flag in cmd, False)

    # --- 8. LO QUE NO PUEDE MOVERSE: el prefijo ---------------------------------
    # Si `versions` moviera el prefijo, encenderla reaprovecharía el baseline
    # bajo un nombre nuevo y bisync leería como borrado todo lo que no estuviera
    # en el destino anterior.
    base = pareja(defaults={"remote": "synology", "device_remote": "disp"})
    con = pareja({"versions": True},
                 defaults={"remote": "synology", "device_remote": "disp"})
    c("encender versions NO mueve expected_prefix()",
      bisync.expected_prefix(con), bisync.expected_prefix(base))
    c("ni el workdir de la pareja", con.workdir, base.workdir)

    # --- 9. el TOML aguanta el ida y vuelta -------------------------------------
    raw = {"defaults": {"remote": "synology"},
           "pair": [{"name": "obsidian", "local": "sync-data/obsidian",
                     "remote_path": "/PJ/Obsidian", "mode": "bisync",
                     "versions": True}]}
    texto = config_file.dumps_checked(raw)
    c("dumps_checked escribe la clave nueva", "versions = true" in texto, True)
    c("y se relee idéntica", tomllib.loads(texto), raw)

    # --- 10. los flags que ya no se dejan escribir a mano ------------------------
    for flag in ("backup-dir", "backup-dir1", "backup-dir2", "suffix",
                 "suffix-keep-extension"):
        c(f"'{flag}' está reservado en el editor de flags",
          flag in flags_editor.RESERVED, True)
    c("'conflict-loser' NO se reserva: es un setdefault y se puede cambiar",
      "conflict-loser" in flags_editor.RESERVED, False)

    # --- 11. el formulario y los booleanos ---------------------------------------
    # str(False) es "False", una cadena no vacía: sin una rama para bool, apagar
    # la casilla guardaría la clave como texto en el TOML.
    c("clean_form conserva versions=True",
      pair_editor.clean_form({"name": "x", "versions": True}).get("versions"), True)
    c("clean_form quita versions=False en vez de guardar 'False'",
      "versions" in pair_editor.clean_form({"name": "x", "versions": False}), False)
    c("merge_form borra la clave cuando el formulario la apaga",
      "versions" in pair_editor.merge_form({"name": "x", "versions": True},
                                           {"name": "x"}), False)

    # --- 12. leer el nombre: la fecha sale de ahí, no del mtime -----------------
    c("un nombre con sello se lee entero",
      versions_editor.leer_nombre("nota~20260922-093000.md"),
      ("nota.md", datetime(2026, 9, 22, 9, 30)))
    c("sin sello no es una versión",
      versions_editor.leer_nombre("nota.md"), None)
    c("un sello imposible tampoco",
      versions_editor.leer_nombre("nota~20261345-990000.md"), None)
    c("y sin extensión también vale",
      versions_editor.leer_nombre("Makefile~20260101-000000"),
      ("Makefile", datetime(2026, 1, 1, 0, 0)))

    # --- 13. leer el lado de aquí -----------------------------------------------
    pair = pareja({"versions": True})
    raiz_v = pair.local_abs / model.VERSIONS_DIR
    (raiz_v / "sub").mkdir(parents=True, exist_ok=True)
    (raiz_v / "vieja~20260101-120000.md").write_text("aaa", encoding="utf-8")
    (raiz_v / "sub" / "nueva~20260920-120000.md").write_text("bb", encoding="utf-8")
    (raiz_v / "esto-no-es-una-version.md").write_text("x", encoding="utf-8")

    local = versions_editor.leer_local(pair)
    c("lee las versiones de las dos carpetas", local.total, 2)
    c("y suma sus tamaños", local.tamano, 5)
    c("un fichero sin sello no cuenta como versión",
      [v.original for v in local.versiones], ["nueva.md", "vieja.md"])

    # --- 14. leer el lado remoto, con rclone sustituido --------------------------
    # `--csv`, no el separador de fábrica: un nombre con ';' partiría la línea.
    class Salida:
        returncode = 0
        stdout = 'con;punto~20260101-130000.md,7\n"con,coma~20260101-140000.md",9\n'
        stderr = ""

    visto = {}
    catalog.run = lambda args: visto.setdefault("args", args) and None or Salida()
    remoto = versions_editor.leer_remoto(pair)
    c("pregunta por la carpeta de versiones del remoto",
      pair.versions_path2 in visto["args"], True)
    c("un nombre con ';' sobrevive",
      "con;punto~20260101-130000.md" in [v.ruta for v in remoto.versiones], True)
    c("y uno con ',' también, porque va entrecomillado",
      "con,coma~20260101-140000.md" in [v.ruta for v in remoto.versiones], True)

    catalog.run = lambda args: type("S", (), {
        "returncode": 3, "stdout": "",
        "stderr": "ERROR : directory not found"})()
    c("una carpeta que aún no existe no es un fallo",
      versions_editor.leer_remoto(pair).disponible, True)
    catalog.run = lambda args: type("S", (), {
        "returncode": 1, "stdout": "", "stderr": "no route to host"})()
    c("un remoto caído sí, y se dice",
      versions_editor.leer_remoto(pair).disponible, False)

    # --- 15. purgar: primero el plan, y solo después el disco --------------------
    remoto = versions_editor.Lado(
        versions_editor.REMOTO, pair.versions_path2, True, "",
        (versions_editor.Version("r/vieja~20260101-120000.md", "vieja.md",
                                 datetime(2026, 1, 1, 12, 0), 100),))
    plan = versions_editor.plan_purgar(pair, local, remoto, date(2026, 6, 1))
    c("el plan coge solo lo anterior al corte, aquí",
      [v.original for v in plan.local], ["vieja.md"])
    c("y también allí", len(plan.remoto), 1)
    c("y lo dice antes de tocar nada", len(plan.consequences) >= 2, True)
    c("con su aviso de que no se recupera", bool(plan.warnings), True)
    c("nada se ha borrado todavía",
      (raiz_v / "vieja~20260101-120000.md").exists(), True)

    vacio = versions_editor.plan_purgar(pair, local, remoto, date(2020, 1, 1))
    c("un corte sin nada detrás da un plan vacío", vacio.vacio, True)

    borrados = []
    versions_editor.borrar_remoto = lambda raiz, rutas: (borrados.extend(rutas), (True, ""))[1]
    hechos = plan.execute()
    c("la versión vieja de aquí ya no está",
      (raiz_v / "vieja~20260101-120000.md").exists(), False)
    c("la nueva sigue", (raiz_v / "sub" / "nueva~20260920-120000.md").exists(), True)
    c("al remoto se le pasa la lista exacta", borrados, ["r/vieja~20260101-120000.md"])
    c("y cuenta lo hecho por lados", len(hechos), 2)

    # --- 16. un lado ilegible no se purga a ciegas -------------------------------
    caido = versions_editor.Lado(versions_editor.REMOTO, pair.versions_path2,
                                 False, "no route to host")
    plan = versions_editor.plan_purgar(pair, local, caido, date(2026, 6, 1))
    c("de un lado que no se ha podido leer no se borra nada", plan.remoto, ())
    c("y se avisa en vez de callarlo",
      any("no se ha podido leer" in a for a in plan.warnings), True)

sys.exit(c.report())
