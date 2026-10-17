#!/usr/bin/env python3
"""El editor de flags: lo que se escribe en el cuadro y lo que acaba en el TOML.

Lo que importa aquí es que no se cuele nada que luego no se pueda escribir
(`config_file.save()` se niega a escribir lo que no se relee igual, y ese «no»
llegaría con el diálogo ya cerrado) y que los frenos de rclone no cambien en
silencio: `--max-delete` es lo que impide que un lado vacío arrase el otro.
"""

import sys

from _harness import Checks, sandbox

import tomllib

from common import bisync, config_file, model
from common.model import ConfigError
import sync
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


def _error_de(texto: str) -> ConfigError:
    """El error con el que se rechaza ese texto; falla si no se rechaza."""
    try:
        fe.parse(texto)
    except ConfigError as e:
        return e
    raise AssertionError(f"{texto!r} no se ha rechazado")


def _error_o_nada(hacer):
    """El mensaje con el que `hacer()` lanza un `ConfigError`, o `''` si no lanza."""
    try:
        hacer()
        return ""
    except ConfigError as e:
        return str(e)


# texto <-> tabla

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


# qué acaba recibiendo rclone

def por_flag(filas):
    """`{flag tal cual va a rclone: de dónde sale}` de las filas de la tabla."""
    return {f.flag: f.etiqueta for f in filas}


def fila(filas, nombre):
    """La fila de ese flag."""
    return next(f for f in filas if f.nombre == nombre)


filas = por_flag(fe.effective("bisync", {"transfers": 4}, {"max-delete": 50}))
c("los flags de siempre están", filas.get("--verbose"), "siempre")
c("el modo pone los suyos", filas.get("--conflict-resolve newer"), "modo bisync")
c("[defaults] se ve como tal", filas.get("--transfers 4"), "[defaults]")
c("y la pareja gana a la capa de debajo", filas.get("--max-delete 50"), "esta pareja")
c("y el que ha perdido no sale", "--max-delete 25" in filas, False)
apagado = fila(fe.effective("up", None, {"verbose": False}), "verbose")
c("un flag apagado se enseña, no desaparece",
  (apagado.flag, apagado.valor, apagado.activo, apagado.etiqueta),
  ("--verbose", "desactivado", False, "esta pareja"))

# Las estadísticas de las que sale el progreso son flags como los demás: se ven
# con su capa, y la pareja las cambia sin tocar código.
filas = por_flag(fe.effective("up", None, None))
c("las estadísticas del progreso van en la capa de siempre",
  (filas.get("--stats 2s"), filas.get("--stats-one-line")), ("siempre", "siempre"))
propias = fe.parse('stats = "10s"\nstats-one-line = false')
filas = fe.effective("up", None, propias)
c("y la pareja las cambia", (por_flag(filas).get("--stats 10s"),
                             fila(filas, "stats-one-line").activo, fila(filas, "stats-one-line").etiqueta),
  ("esta pareja", False, "esta pareja"))

# La tabla enseña cada flag con su nombre, su valor y su origen por separado.
filas = fe.effective("bisync", {"transfers": 4, "exclude-from": ["a", "b"]}, {"checksum": True})
c("el nombre, sin guiones de más", fila(filas, "transfers").nombre, "transfers")
c("el valor, aparte", fila(filas, "transfers").valor, "4")
c("un flag que se enciende solo se enseña activado", fila(filas, "checksum").valor, "activado")
c("una lista, con sus elementos", fila(filas, "exclude-from").valor, "a, b")
c("el valor con su tipo del TOML se conserva para sobrescribir",
  (fila(filas, "transfers").crudo, fila(filas, "exclude-from").crudo), (4, ["a", "b"]))
c("quién es de la pareja y quién no", [f.propio for f in filas if f.nombre in
                                      ("checksum", "transfers", "max-delete")],
  [True, False, False])
c("el origen, para quien no lee la etiqueta", fila(filas, "transfers").origen,
  model.ORIGEN_DEFAULTS)

# Dos grafías del mismo flag son un solo flag para rclone: la tabla los junta y manda el último.
junto = [f for f in fe.effective("up-mirror", None, {"max_delete": 5})
         if fe.normalize(f.nombre) == "max-delete"]
c("max_delete y max-delete salen una vez, con el valor que gana",
  [(f.flag, f.etiqueta) for f in junto], [("--max-delete 5", "esta pareja")])

# [defaults] se edita como capa propia: sin modo ni nada por encima.
filas = fe.effective(None, None, {"transfers": 4}, capa=model.ORIGEN_DEFAULTS)
c("en [defaults], lo suyo se llama [defaults]", fila(filas, "transfers").etiqueta, "[defaults]")
c("  y es lo que se puede quitar",
  (fila(filas, "transfers").propio, fila(filas, "verbose").propio), (True, False))

# Lo que dice la tabla de cada fila: qué pasa si se toca.
filas = fe.effective("bisync", None, {"max-delete": 50, "checksum": True})
c("quitar uno de la pareja dice a qué vuelve", fila(filas, "max-delete").nota,
  "Si lo quitas, vuelve a valer 25 (modo bisync).")
c("y si no hay nada debajo, que rclone deja de recibirlo", fila(filas, "checksum").nota,
  "Si lo quitas, rclone deja de recibirlo.")
c("uno heredado dice que se puede sobrescribir", "sobrescribir" in fila(filas, "resilient").nota.lower(),
  True)

# La misma fusión que hace model._build_pair: si esto se separara, el editor
# enseñaría unos flags y rclone recibiría otros.
pair = model.parse_config({"defaults": {"remote": "nas", "flags": {"transfers": 4}},
                           "pair": [{**BASE[0]}]}).pairs[0]
c("se funde igual que en el modelo",
  fe.merge("bisync", {"transfers": 4}, BASE[0]["flags"]), dict(pair.flags))

c("el botón resume lo propio", fe.summary({"a": 1, "b": 2}, ["--x"]), "2 flags + 1 extra")
c("y dice cuándo no hay nada propio", fe.summary(None, None), "ninguno propio")


# avisos: el freno de los borrados

def avisos(antes, despues, mode_antes="bisync", mode_despues="bisync", comunes=None):
    """Devuelve los avisos de pasar de unos flags a otros, ya fusionados con el modo."""
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


# y de ahí al TOML

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


# sobrescribir un flag heredado y volver a heredarlo

c("sobrescribir añade el flag a los de la pareja, con su valor",
  fe.sobrescribir({"conflict-resolve": "path2"}, "max-delete", 25),
  {"conflict-resolve": "path2", "max-delete": 25})
c("con su tipo: una lista sigue siendo una lista",
  fe.sobrescribir({}, "exclude-from", ["a", "b"]), {"exclude-from": ["a", "b"]})
c("sin tocar lo que ya había", fe.sobrescribir({"a": 1}, "b", 2), {"a": 1, "b": 2})
original = {"max-delete": 10}
fe.sobrescribir(original, "transfers", 4)
fe.heredar(original, "max-delete")
c("y la tabla de la que se parte no se toca", original, {"max-delete": 10})
c("sobrescribir uno que ya es de la pareja cambia su valor",
  fe.sobrescribir({"max-delete": 10}, "max-delete", 5), {"max-delete": 5})
c("la grafía con guion bajo es el mismo flag: no queda repetido",
  fe.sobrescribir({"max_delete": 10}, "max-delete", 5), {"max-delete": 5})

c("volver a heredar quita el flag de la pareja",
  fe.heredar({"conflict-resolve": "path2", "max-delete": 25}, "max-delete"),
  {"conflict-resolve": "path2"})
c("con cualquiera de sus grafías", fe.heredar({"max_delete": 25}, "max-delete"), {})
c("y si no era suyo no hace nada", fe.heredar({"a": 1}, "b"), {"a": 1})

c("sobrescribir se ofrece en lo heredado, y volver a heredar en lo propio",
  {f.nombre: fe.acciones(f) for f in fe.effective("bisync", None, {"checksum": True})
   if f.nombre in ("resilient", "checksum")},
  {"resilient": (True, False), "checksum": (False, True)})
c("y sin nada elegido no se ofrece nada", fe.acciones(None), (False, False))

c("la cascada dice el orden de las capas",
  fe.cascada(), "Se funden en este orden: siempre → modo → [defaults] → esta pareja.")
c("y en [defaults] no hay modo ni pareja",
  fe.cascada(model.ORIGEN_DEFAULTS), "Se funden en este orden: siempre → [defaults].")
c("cuando no hay orden se dice por qué", fe.sin_orden(ConfigError("falta 'local'")),
  "Todavía no se puede componer la orden: falta 'local'")

# Los reservados siguen rechazados: la tabla no es una puerta lateral.
for reservado in ("workdir", "config", "log-file", "resync", "filters-file", "include",
                  "suffix", "backup-dir1"):
    try:
        fe.sobrescribir({}, reservado, "x")
        rechazado = False
    except fe.FlagReservado:
        rechazado = True
    c(f"sobrescribir rechaza el reservado '{reservado}'", rechazado, True)
    c("  y model.problema_flag() sigue diciendo por qué", bool(model.problema_flag(reservado)),
      True)
try:
    fe.sobrescribir({}, "sftp-ssh", "sh -c id")
    rechazado = False
except fe.FlagReservado:
    rechazado = True
c("ni uno que lance un programa de este equipo", rechazado, True)
try:
    fe.sobrescribir({}, "checksum", "--sftp-ssh=sh -c id")
    rechazado = False
except ConfigError:
    rechazado = True
c("ni lo que se cuela dentro de un valor", rechazado, True)
c("las filas de la tabla nunca traen un reservado",
  [f.nombre for f in fe.effective("bisync", {"transfers": 4}, {"max-delete": 5})
   if model.problema_flag(f.nombre)], [])


# ida y vuelta: lo que se enseña, lo que se guarda y lo que lee sync.py

with sandbox():
    raw = {"defaults": {"remote": "nas"}, "pair": [dict(p) for p in BASE]}
    model.CONFIG_FILE.write_text(config_file.dumps(raw), encoding="utf-8")

    def lee_sync(nombre="notas"):
        """La pareja como la lee `sync.py`: el config del disco, resuelto."""
        return next(p for p in model.load_config().pairs if p.name == nombre)

    def guarda(propios, nombre="notas"):
        """Guarda esos flags por el plan de siempre y devuelve el TOML escrito."""
        actual = tomllib.loads(model.CONFIG_FILE.read_text(encoding="utf-8"))
        entrada = next(p for p in actual["pair"] if p["name"] == nombre)
        plan = pair_editor.plan_save(actual, {**entrada, "flags": propios}, nombre)
        c("  cambiar flags no aparta ningún baseline", plan.shelve, [])
        plan.execute()
        return tomllib.loads(model.CONFIG_FILE.read_text(encoding="utf-8"))

    antes = {f.nombre: f for f in fe.effective("bisync", None, BASE[0]["flags"])}
    c("max-delete se hereda del modo", (antes["max-delete"].etiqueta, antes["max-delete"].propio),
      ("modo bisync", False))

    nuevos = fe.sobrescribir(BASE[0]["flags"], "max-delete", antes["max-delete"].crudo)
    escrito = guarda(nuevos)
    c("sobrescribirlo escribe su [pair.flags]", escrito["pair"][0]["flags"],
      {"conflict-resolve": "path2", "max-delete": 25})
    leida = lee_sync()
    c("sync.py lo lee con el origen de la pareja",
      (leida.flags["max-delete"], leida.origen_flags["max-delete"]), (25, model.ORIGEN_PAREJA))
    c("y la tabla dice lo mismo que lee sync.py",
      {f.nombre: f.crudo for f in fe.effective("bisync", None, nuevos)},
      {fe.normalize(k): v for k, v in leida.flags.items()})
    c("con el mismo origen para cada flag",
      {f.nombre: f.origen for f in fe.effective("bisync", None, nuevos)},
      {fe.normalize(k): v for k, v in leida.origen_flags.items()})

    escrito = guarda(fe.heredar(nuevos, "max-delete"))
    c("volver a heredarlo deja el TOML como estaba", escrito["pair"][0]["flags"],
      BASE[0]["flags"])
    leida = lee_sync()
    c("y sync.py vuelve a leer el del modo",
      (leida.flags["max-delete"], leida.origen_flags["max-delete"]), (25, model.ORIGEN_MODO))

    escrito = guarda(fe.heredar(BASE[0]["flags"], "conflict-resolve"))
    c("quitar el último flag propio quita la tabla entera", "flags" in escrito["pair"][0], False)
    c("y rige lo que decía el modo",
      lee_sync().flags["conflict-resolve"], "newer")

    # En [defaults] es lo mismo, una capa más arriba.
    comunes = fe.sobrescribir({}, "transfers", 4)
    plan = pair_editor.plan_defaults(escrito, {**escrito["defaults"], "flags": comunes})
    plan.execute()
    c("sobrescribir en [defaults] llega a [defaults.flags]",
      tomllib.loads(model.CONFIG_FILE.read_text(encoding="utf-8"))["defaults"]["flags"], comunes)
    c("y las parejas lo leen como de [defaults]",
      (lee_sync().flags["transfers"], lee_sync().origen_flags["transfers"]),
      (4, model.ORIGEN_DEFAULTS))


# la vista previa de la orden es la de sync.py

PAREJAS = {
    "bisync": ({**BASE[0], "flags": {}}, {}),
    "bisync con versiones, filtros y flags": (
        {**BASE[0], "versions": True, "include": ["*.md"], "exclude": ["tmp/**"],
         "flags": {"transfers": 8, "max-delete": 10}}, {"flags": {"checksum": True}}),
    "bisync con un resync-mode propio": (
        {**BASE[0], "flags": {"resync-mode": "newer"}}, {}),
    "bisync con resync_mode, tal como se teclea": (
        {**BASE[0], "flags": fe.parse('resync_mode = "newer"')}, {}),
    "bisync con resync-mode en extra_flags": (
        {**BASE[0], "extra_flags": ["--resync-mode=newer", "--bwlimit", "8M"]}, {}),
    "bisync con versiones y conflict_loser": (
        {**BASE[0], "versions": True, "flags": fe.parse('conflict_loser = "num"')}, {}),
    "up": ({**BASE[1], "extra_flags": ["--bwlimit", "8M"]}, {}),
    "down con filtros de [defaults]": (
        {**BASE[1], "mode": "down", "include": ["*.pdf"]}, {"exclude": ["*.bak"]}),
    "up-mirror con dos grafías": (
        {**BASE[1], "mode": "up-mirror", "flags": {"max_delete": 5}}, {}),
    "down-mirror": ({**BASE[1], "mode": "down-mirror", "flags": {"verbose": False}}, {}),
    "la raíz entera": (
        {"name": "todo", "local": ".", "remote_path": "/R/todo", "mode": "up-mirror"}, {}),
}


def vista(entrada, defaults):
    """`(raw, líneas de la vista previa, orden de sync.py)` de esa pareja."""
    raw_ = {"defaults": {"remote": "nas", "device_remote": "disp", **defaults},
            "pair": [entrada]}
    pair = model.parse_config(raw_).pairs[0]
    ctx = sync.RunContext(binary="rclone", env={}, sello="~SELLO")
    cmd, log = sync.build_command(ctx, pair, bisync.filters_file_for(pair), False)
    cambios = {str(log): fe.LOG_PREVIO, "~SELLO": fe.SELLO_PREVIO}
    return (raw_, pair_editor.orden_previa(raw_, entrada), [cambios.get(t, t) for t in cmd])


with sandbox():
    for nombre, (entrada, defaults) in PAREJAS.items():
        _, lineas, de_sync = vista(entrada, defaults)
        c(f"la vista previa es la orden de sync.py ({nombre})",
          [a for l in lineas for a in l.args], de_sync)

    # Ninguna grafía de resync-mode llega a la vista previa de una pasada normal, y el
    # conflict-loser del usuario no lleva detrás el `delete` del versionado.
    for nombre in ("bisync con un resync-mode propio", "bisync con resync_mode, tal como se teclea",
                   "bisync con resync-mode en extra_flags"):
        c(f"la vista previa no lleva --resync-mode ({nombre})",
          [a for l in vista(*PAREJAS[nombre])[1] for a in l.args if a.startswith("--resync")],
          [])
    lineas_loser = vista(*PAREJAS["bisync con versiones y conflict_loser"])[1]
    c("y el conflict_loser del usuario sale una vez, con su valor",
      [l.args for l in lineas_loser if l.args[0] == "--conflict-loser"],
      [("--conflict-loser", "num")])

    _, lineas, _ = vista(*PAREJAS["bisync con versiones, filtros y flags"])
    puestas = {l.args[0] for l in lineas if l.lo_pone_prdrive}
    c("lo que pone prdrive va marcado",
      puestas, {"rclone", "--filters-file", "--config", "--log-file", "--workdir",
                "--backup-dir1", "--backup-dir2", "--suffix", "--suffix-keep-extension",
                "--conflict-loser"})
    c("lo que es de las capas, no",
      {l.args[0] for l in lineas if not l.lo_pone_prdrive} >= {"--verbose", "--max-lock",
                                                              "--transfers", "--checksum"},
      True)
    c("cada línea dice de dónde sale",
      {l.args[0]: l.etiqueta for l in lineas}["--transfers"], "esta pareja")
    c("y las del programa lo dicen", {l.args[0]: l.etiqueta for l in lineas}["--config"],
      fe.ETIQUETA_PRDRIVE)
    c("la línea es el texto de la orden", [l.texto for l in lineas][0].startswith("rclone bisync "),
      True)

    # La vista previa sigue los flags que se están escribiendo, no los guardados.
    raw_, _, _ = vista(*PAREJAS["bisync"])
    editada = {**PAREJAS["bisync"][0], "flags": {"transfers": 3}}
    c("con lo que se está escribiendo",
      "--transfers 3" in [l.texto for l in pair_editor.orden_previa(raw_, editada)], True)

    # Lo que se dibuja: la orden de corrido, en rachas de quien pone cada trozo.
    rachas = fe.trozos(vista(*PAREJAS["bisync con versiones, filtros y flags"])[1])
    c("las rachas alternan lo del programa y lo demás", [puesto for _t, puesto in rachas],
      [True, False, True])
    c("la primera es la orden con su fichero de filtros",
      rachas[0][0].startswith("rclone bisync ") and rachas[0][0].endswith("notas.txt"), True)
    c("y juntas, las rachas son la orden entera",
      " ".join(t for t, _p in rachas),
      " ".join(l.texto for l in vista(*PAREJAS["bisync con versiones, filtros y flags"])[1]))
    c("sin nada que agrupar no hay rachas", fe.trozos([]), [])

    # Una pareja a medio rellenar no tiene orden: se dice por qué, no se inventa.
    try:
        pair_editor.orden_previa({"defaults": {"remote": "nas"}, "pair": []},
                                 {"name": "nueva", "mode": "bisync"})
        dicho = ""
    except ConfigError as e:
        dicho = str(e)
    c("sin ruta local no hay orden, y se dice qué falta", "local" in dicho, True)


# el tipo del valor: la misma puerta que lo reservado (ui/flags_ayuda.py)

c("un entero que no lo es se rechaza al escribirlo, antes de guardar",
  "número entero" in falla('transfers = "cuatro"'), True)
c("  con el nombre del flag y un ejemplo", "transfers = 4" in falla('transfers = "cuatro"'), True)
c("  y con el título de un texto que no vale, no con el de un reservado",
  fe.titulo_error(_error_de('transfers = "cuatro"')), fe.TITULO_NO_VALE)
c("un sí o no entre comillas llegaría a rclone como un argumento suelto",
  "sin comillas" in falla('checksum = "true"'), True)
c("`true` en un flag con valor se comería el argumento siguiente",
  "necesita un valor" in falla("max-lock = true"), True)
c("una duración de Go sin unidad", "unidad" in falla("timeout = 30"), True)
c("  y con ella vale", fe.parse('timeout = "30s"'), {"timeout": "30s"})
c("un tamaño que no lo es", "tamaño" in falla('max-size = "mucho"'), True)
c("un valor bueno de cada tipo pasa",
  fe.parse('transfers = 8\nmax-lock = "2m"\nstats = "0"\nmax-size = "10M"\n'
           'tpslimit = 0.5\nlog-level = "DEBUG"\nexclude-from = ["a", "b"]\nverbose = true'),
  {"transfers": 8, "max-lock": "2m", "stats": "0", "max-size": "10M", "tpslimit": 0.5,
   "log-level": "DEBUG", "exclude-from": ["a", "b"], "verbose": True})
c("`false` vale en cualquier flag: es quitarlo", fe.parse("transfers = false\nmax-lock = false"),
  {"transfers": False, "max-lock": False})
c("un flag que no está en la lista se admite, con el valor que sea (no hay lista blanca)",
  fe.parse('flag-nuevo-de-rclone = "lo-que-sea"\notro_mas = 3\ns3-region = "eu-west-1"'),
  {"flag-nuevo-de-rclone": "lo-que-sea", "otro_mas": 3, "s3-region": "eu-west-1"})
c("un flag cuyo tipo no se comprueba, tampoco: bwlimit lleva horarios",
  fe.parse('bwlimit = "08:00,1M 18:00,off"'), {"bwlimit": "08:00,1M 18:00,off"})

# Sobrescribir un heredado copia su valor: no puede rechazarse a sí mismo.
c("todo lo que viene de siempre o del modo se puede sobrescribir tal cual",
  [(f.nombre, e) for modo in ("bisync", "up", "down", "up-mirror", "down-mirror")
   for f in fe.effective(modo, None, None)
   for e in [_error_o_nada(lambda: fe.sobrescribir({}, f.nombre, f.crudo))] if e], [])
try:
    fe.sobrescribir({}, "timeout", 30)
    rechazado = False
except ConfigError:
    rechazado = True
c("sobrescribir pasa por la misma puerta que el cuadro", rechazado, True)

# Lo que prdrive propone en su ejemplo (sync_config.example.toml) vale.
ejemplo = tomllib.loads(open(model.APP_DIR / "sync_config.example.toml", encoding="utf-8").read())
propuestos = [ejemplo.get("defaults", {}).get("flags", {})] + [
    p.get("flags", {}) for p in ejemplo.get("pair", [])]
c("los flags del ejemplo valen para el editor",
  [(t, _error_o_nada(lambda t=t: fe.parse(fe.dump(t)))) for t in propuestos
   if _error_o_nada(lambda t=t: fe.parse(fe.dump(t)))], [])


sys.exit(c.report())
