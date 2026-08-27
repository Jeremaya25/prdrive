#!/usr/bin/env python3
"""
El editor de flags: lo que se escribe en el cuadro y lo que acaba en el TOML.

Lo que importa aquí es que no se cuele nada que luego no se pueda escribir
—`config_file.save()` se niega a escribir lo que no se relee igual, y ese "no"
llegaría con el diálogo ya cerrado— y que los frenos de rclone no cambien en
silencio: `--max-delete` es lo que impide que un lado vacío arrase el otro.
"""

import sys

from _harness import Checks, sandbox

import tomllib

from common import config_file, model
from common.model import ConfigError
from ui import flags_editor as fe
from ui import pair_editor

c = Checks("editor de flags (ui/flags_editor.py)")

BASE = [
    {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas",
     "mode": "bisync", "flags": {"conflict-resolve": "path2"}},
    {"name": "subida", "local": "sync-data/subida", "remote_path": "/R/subida",
     "mode": "up"},
]


def falla(texto: str) -> str:
    """El mensaje con el que se rechaza lo escrito. '' = no se ha rechazado."""
    try:
        fe.parse(texto)
        return ""
    except ConfigError as e:
        return str(e)


# --- texto <-> tabla ---------------------------------------------------------

c("clave = valor, con su tipo", fe.parse('transfers = 4\nchecksum = true\n'
                                         'conflict-resolve = "newer"'),
  {"transfers": 4, "checksum": True, "conflict-resolve": "newer"})
c("las listas se admiten (el flag se repite)", fe.parse('exclude-from = ["a", "b"]'),
  {"exclude-from": ["a", "b"]})
c("un cuadro vacío son cero flags", fe.parse("   \n\n"), {})

# Lo que se enseña tiene que ser lo que se escribiría: si no, el formulario dice
# una cosa y el TOML acaba con otra.
tabla = {"max-delete": 25, "resilient": True, "conflict-resolve": "newer"}
c("ida y vuelta por el texto", fe.parse(fe.dump(tabla)), tabla)
c("y el texto es el del serializador", fe.dump(tabla),
  config_file.dumps_table(tabla))

c("la sintaxis de la línea de comandos se rechaza con su explicación",
  "sin los guiones" in falla("--transfers 4"), True)
c("y el TOML roto también", falla("transfers =") != "", True)
c("un flag de sync.py no se puede pisar", "no se configura aquí" in falla('workdir = "x"'),
  True)
c("ni con guion bajo, que rclone ve igual",
  "no se configura aquí" in falla("filters_file = 'x'"), True)
c("ni los filtros, que salen de incluir/excluir",
  "no se configura aquí" in falla('include = ["*.md"]'), True)
c("una tabla anidada no cabe", "no caben tablas" in falla("[sub]\nx = 1"), True)
c("ni un valor que el serializador no sabe escribir",
  "no admitido" in falla("cuando = 1979-05-27"), True)

c("los argumentos extra van uno por línea y tal cual",
  fe.parse_extra("--bwlimit\n8M\n\n  --stats 10s  "), ["--bwlimit", "8M", "--stats 10s"])
c("y vuelven igual", fe.dump_extra(["--bwlimit", "8M"]), "--bwlimit\n8M")


# --- qué acaba recibiendo rclone ---------------------------------------------

filas = dict(fe.effective("bisync", {"transfers": 4}, {"max-delete": 50}))
c("los flags de siempre están", filas.get("--verbose"), "siempre")
c("el modo pone los suyos", filas.get("--conflict-resolve newer"), "modo bisync")
c("[defaults] se ve como tal", filas.get("--transfers 4"), "[defaults]")
c("y la pareja gana a la capa de debajo", filas.get("--max-delete 50"), "esta pareja")
c("un flag apagado se enseña, no desaparece",
  dict(fe.effective("up", None, {"verbose": False})).get("(--verbose: desactivado)"),
  "esta pareja")

# La misma fusión que hace model._build_pair: si esto se separara, el editor
# enseñaría unos flags y rclone recibiría otros.
pair = model.parse_config({"defaults": {"remote": "nas", "flags": {"transfers": 4}},
                           "pair": [{**BASE[0]}]}).pairs[0]
c("se funde igual que en el modelo",
  fe.merge("bisync", {"transfers": 4}, BASE[0]["flags"]), dict(pair.flags))

c("el botón resume lo propio", fe.summary({"a": 1, "b": 2}, ["--x"]), "2 flags + 1 extra")
c("y dice cuándo no hay nada propio", fe.summary(None, None), "ninguno propio")


# --- avisos: el freno de los borrados ----------------------------------------

def avisos(antes, despues, mode_antes="bisync", mode_despues="bisync", comunes=None):
    return fe.warnings(fe.merge(mode_antes, comunes, antes),
                       fe.merge(mode_despues, comunes, despues))


c("subir max-delete se avisa", bool(avisos({}, {"max-delete": 500})), True)
c("bajarlo no", avisos({}, {"max-delete": 5}), [])
c("quitar el freno se avisa", bool(avisos({}, {"max-delete": False})), True)
c("quitarlo de la pareja avisa si la capa de debajo permite más",
  bool(avisos({"max-delete": 10}, {})), True)
c("cambiar de modo también sube el freno sin tocar ningún flag",
  bool(avisos({}, {}, mode_despues="up-mirror")), True)
c("lo que no es un freno no molesta", avisos({}, {"transfers": 8}), [])

c("los cambios se cuentan flag a flag",
  fe.changes({"max-delete": 25}, {"transfers": 4}),
  ["quita max-delete (vuelve a valer el de la capa de debajo)", "añade transfers = 4"])


# --- y de ahí al TOML --------------------------------------------------------

with sandbox():
    raw = {"defaults": {"remote": "nas"}, "pair": [dict(p) for p in BASE]}
    model.CONFIG_FILE.write_text(config_file.dumps(raw), encoding="utf-8")

    plan = pair_editor.plan_save(raw, {**BASE[0], "flags": {"transfers": 8},
                                       "extra_flags": ["--bwlimit", "8M"]}, "notas")
    c("cambiar flags no aparta ningún baseline", plan.shelve, [])
    c("pero se cuenta lo que cambia",
      any("Flags de la pareja" in x for x in plan.consequences), True)
    c("y los extra también",
      any("Argumentos extra: --bwlimit 8M" in x for x in plan.consequences), True)
    plan.execute()

    escrito = tomllib.loads(model.CONFIG_FILE.read_text(encoding="utf-8"))
    c("los flags llegan a su [pair.flags]", escrito["pair"][0].get("flags"),
      {"transfers": 8})
    c("y los extra a su pareja", escrito["pair"][0].get("extra_flags"),
      ["--bwlimit", "8M"])
    c("sin tocar la pareja de al lado", escrito["pair"][1].get("flags"), None)

    # Vaciar el cuadro es quitar el flag: si no, no habría forma de volver a lo
    # que digan el modo y [defaults].
    plan = pair_editor.plan_save(escrito, {**escrito["pair"][0], "flags": {},
                                           "extra_flags": []}, "notas")
    plan.execute()
    escrito = tomllib.loads(model.CONFIG_FILE.read_text(encoding="utf-8"))
    c("vaciarlos los borra del TOML", "flags" in escrito["pair"][0], False)
    c("y a los extra igual", "extra_flags" in escrito["pair"][0], False)

    # [defaults.flags] alimenta a todas las parejas, así que el aviso tiene que
    # mirar pareja a pareja: el mismo valor puede ser inocuo en una y no en otra.
    plan = pair_editor.plan_defaults(escrito, {**escrito["defaults"],
                                               "flags": {"max-delete": 900}})
    # 'subida' es modo up (copy): no borra, así que no tenía freno ni lo echa de
    # menos. El aviso es de 'notas', que pasa de los 25 de bisync a 900.
    c("un freno flojo en [defaults] se avisa pareja a pareja",
      [w.split("]")[0] + "]" for w in plan.warnings], ["[notas]"])
    c("y se dice qué flag común cambia",
      any("Flags comunes" in x for x in plan.consequences), True)
    plan.execute()
    escrito = tomllib.loads(model.CONFIG_FILE.read_text(encoding="utf-8"))
    c("[defaults.flags] se escribe donde toca", escrito["defaults"]["flags"],
      {"max-delete": 900})

sys.exit(c.report())
