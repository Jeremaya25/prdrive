#!/usr/bin/env python3
"""La ayuda al escribir un flag: autocompletado, tipo del valor y avisos (`ui/flags_ayuda.py`).

Todo sale de `common/flags_rclone.json` (los flags de la rclone fijada) y de unas
tablas a mano, sin red y sin Tk. Lo que se comprueba:

- Que el tipo de un valor se rechaza cuando rclone lo rechazaría y NO se rechaza
  cuando rclone lo acepta: una ayuda que bloquea un valor bueno es peor que no
  tenerla. Las listas de valores buenos y malos de abajo están MEDIDAS con la
  v1.75.2 (`rclone version --modify-window 1d`, etc.); no son suposiciones.
- Que un flag que no está en la lista se admite siempre (no hay lista blanca).
- Que los avisos no bloquean: son una lista, nunca una excepción.
"""

import json
import string
import sys
import tempfile
from pathlib import Path

from _harness import Checks

from common import model, pins
from ui import flags_ayuda as ayuda

c = Checks("ayuda al escribir un flag (ui/flags_ayuda.py)")


# Los datos: de la rclone fijada, y sin ellos el editor sigue valiendo.

datos = ayuda.datos()
c("los datos son de la rclone fijada (si falla: python generar_flags_rclone.py)",
  datos.rclone, pins.RCLONE_VERSION)
c("hay flags", len(datos.flags) > 150, True)
c("se busca por el nombre que ve rclone: `_` y `-` son lo mismo",
  ayuda.conocido("max_delete") is ayuda.conocido("max-delete"), True)
c("  y las mayúsculas no cuentan", ayuda.conocido("Max-Delete").nombre, "max-delete")
c("  y con los guiones de delante, como se escribe en la línea de comandos",
  ayuda.conocido("--max-delete").nombre, "max-delete")
c("un flag que no está, no está", ayuda.conocido("flag-que-no-existe"), None)
f = ayuda.conocido("transfers")
c("de cada flag: tipo, valor de fábrica y ayuda",
  (f.tipo, f.defecto, "parallel" in f.ayuda), ("int", "4", True))
c("un propio de bisync lo dice", (ayuda.conocido("resilient").propio,
                                  ayuda.conocido("resilient").comandos), (True, ("bisync",)))
c("un Duration de Go también", ayuda.conocido("timeout").go, True)
c("y uno de rclone no", ayuda.conocido("max-lock").go, False)

with tempfile.TemporaryDirectory() as tmp:
    roto = Path(tmp) / "roto.json"
    roto.write_text("{esto no es json", encoding="utf-8")
    c("un fichero roto no tumba el editor: sin datos", ayuda.cargar(roto).flags, {})
    c("  ni uno que falta", ayuda.cargar(Path(tmp) / "no-esta.json").flags, {})
    raro = Path(tmp) / "raro.json"
    raro.write_text(json.dumps({"rclone": "v1", "flags": {
        "ok": {"tipo": "int"}, "mal": 3, "peor": {"comandos": 5}, "raro": {"propio": "x",
                                                                           "comandos": None}}}),
                    encoding="utf-8")
    c("  ni uno con un flag a medias o con el tipo de un campo cambiado: se lee lo que se puede",
      sorted(ayuda.cargar(raro).flags), ["ok", "raro"])
    c("  y lo que falta se queda con su valor de siempre",
      (ayuda.cargar(raro).flags["ok"].comandos, ayuda.cargar(raro).flags["ok"].propio),
      (("bisync", "copy", "sync"), False))
    lista_en_vez_de_dict = Path(tmp) / "lista.json"
    lista_en_vez_de_dict.write_text("[1, 2, 3]", encoding="utf-8")
    c("  ni uno que no es un objeto", ayuda.cargar(lista_en_vez_de_dict).flags, {})
    binario = Path(tmp) / "binario.json"
    binario.write_bytes(b"\xff\xfe\x00\x01")
    c("  ni uno que no es texto", ayuda.cargar(binario).flags, {})

# Sin red: con los sockets cortados, todo sigue funcionando (el criterio de aceptación de #125).
import socket
import urllib.request


def sin_red(*_a, **_k):
    """Lo que haría cualquier intento de salir a la red durante este tramo."""
    raise AssertionError("la ayuda al escribir un flag ha intentado usar la red")


guardado = (socket.socket, socket.create_connection, socket.getaddrinfo, urllib.request.urlopen)
socket.socket = socket.create_connection = socket.getaddrinfo = sin_red
urllib.request.urlopen = sin_red
try:
    ayuda._CARGADOS.clear()                       # que vuelva a leer el fichero, con la red cortada
    sin = (ayuda.datos().rclone, [f.nombre for f in ayuda.sugerir("transf", "up")][:1],
           ayuda.problema_valor("transfers", "cuatro") is not None,
           [a.tipo for a in ayuda.avisos("up-mirror", None, {"delete-after": True})])
finally:
    socket.socket, socket.create_connection, socket.getaddrinfo, urllib.request.urlopen = guardado
c("con los sockets cortados cargar, sugerir, comprobar y avisar siguen funcionando", sin,
  (pins.RCLONE_VERSION, ["transfers"], True, ["borrado"]))

# Lo que prdrive pone por su cuenta tiene que estar en la lista, con un valor que valga:
# si no, «Sobrescribir» de un flag heredado se rechazaría a sí mismo.
heredados = dict(model.BASE_FLAGS)
for modo in model.MODES.values():
    heredados.update(modo.flags)
c("los flags de BASE_FLAGS y de los modos están en la lista",
  [n for n in heredados if ayuda.conocido(n) is None], [])
c("y el valor con el que vienen vale",
  {n: ayuda.problema_valor(n, v) for n, v in heredados.items()
   if ayuda.problema_valor(n, v)}, {})


# El tipo del valor.

def malo(nombre, valor):
    """¿Rechaza `problema_valor()` ese valor?"""
    return ayuda.problema_valor(nombre, valor) is not None


def tabla(nombre, buenos, malos, etiqueta):
    """Comprueba que se aceptan los valores buenos y se rechazan los malos."""
    c(f"{etiqueta}: lo que rclone acepta, se acepta",
      [v for v in buenos if malo(nombre, v)], [])
    c(f"{etiqueta}: lo que rclone rechaza, se rechaza",
      [v for v in malos if not malo(nombre, v)], [])


# Medido con rclone v1.75.2 sobre `--min-age` y `--max-lock` (la duración de rclone).
tabla("min-age",
      ["1d", "1w", "1M", "1y", "30", "1.5", "0", "off", "1h30m", "1m1s", "12h1µs", "-1d", "+1d",
       ".5d", "5.d", "1_0d", "1e1d", "5e0", "2006-01-02", "2006-01-02T15:04:05", 5, 120, 1.5, 0],
      ["abc", "", "1x", "1 s", "1S", "1H", "1D", "3d12h", "1d2h", " 1s", "1s ", "OFF", "Off",
       "never", "0x10", "d", "1dd"],
      "duración de rclone")
# Medido con `--modify-window` y `--timeout` (la de Go: lleva unidad, y `d` no existe).
tabla("timeout",
      ["30s", "2m", "1h30m", "1.5h", ".5h", "5.h", "-1h", "1ms", "1us", "1µs", "1ns", "0", "+0",
       "-0", "0m", "5s12s", 0],
      ["30", "120", "1.5", "1d", "1w", "1M", "off", "abc", "", "1x", "1 s", "1S", "1H", "OFF",
       "3d12h", " 1s", "1s ", "00", "1_0s", "1e3", 30, 1.5],
      "duración de Go")

# Medido con `--max-size` (sin sufijo son KiB: `1` es 1 KiB).
tabla("max-size",
      ["1", "1k", "1K", "1Ki", "1M", "1Mi", "1.5G", "off", "OFF", "Off", "1KiB", "1B", "1b", "1T",
       "1P", "1E", "0", "1.5", "1e3", "1e3k", ".5k", "+1k", "1_0", "1ki", "1KI", "1012.", "5E",
       "1.5Gi", "1Kib", 1000, 0, 1.5],
      ["-1", "off ", "1kb", "abc", "", "1 k", "1k ", "1,5k", "0x10", "10Mi5", "1KIB", "k", -1],
      "tamaño")

# Medido con `--transfers`: un entero de Go (`ParseInt` en base 0).
tabla("transfers",
      ["4", "-1", "0", "+3", "0x10", "1_000", " 4", "4 ", "004", "-0", 4, -1, 0],
      ["4.5", "abc", "", "1e3", "99999999999999999999", "٤", "08", "0x", "4,5", 4.5, 1e3,
       99999999999999999999],
      "entero")
# Medido con `--tpslimit`: un decimal de Go (`ParseFloat`).
tabla("tpslimit",
      ["0.5", "1", "1e2", ".5", "-1", "5.", "+1", "nan", "inf", "0x1p3", "1_0", 0.5, 2, 0],
      ["abc", "", "1,5", "1 2", "--1"],
      "decimal")
# Medido con `--log-level` (sin distinguir mayúsculas) y `--cutoff-mode`.
tabla("log-level",
      ["DEBUG", "INFO", "NOTICE", "ERROR", "debug", "Info", "WARNING", "CRITICAL", "ALERT",
       "EMERGENCY", "OFF"],
      ["", "x", "INFO ", "NONE", 3],
      "nivel del log")
tabla("cutoff-mode", ["HARD", "SOFT", "CAUTIOUS", "hard", "Soft"],
      ["other", "", "HARD ", 1], "una opción de una lista")
tabla("color", ["AUTO", "NEVER", "ALWAYS", "auto"], ["x", ""], "otra opción de una lista")

# Sí o no, un texto y una lista: la forma del valor.
c("un booleano acepta true y false", [malo("checksum", True), malo("checksum", False)],
  [False, False])
c("pero no un texto, que sería un argumento suelto de la orden",
  (malo("checksum", "true"), malo("checksum", 1), malo("checksum", "")), (True, True, True))
c("`false` se admite en cualquier flag: es quitarlo (`flags_to_args` no lo pasa)",
  [malo(n, False) for n in ("transfers", "max-lock", "min-age", "max-size", "log-level",
                            "conflict-resolve", "exclude-from", "verbose")], [False] * 8)
c("`true` en un flag con valor no vale: rclone se comería el siguiente argumento",
  [malo(n, True) for n in ("transfers", "max-lock", "max-size", "conflict-resolve",
                           "exclude-from", "bwlimit")], [True] * 6)
c("`verbose` es un contador pero se escribe `verbose = true`: un número no vale",
  (malo("verbose", True), malo("verbose", 2)), (False, True))
c("un texto es un texto, y un número se escribe como texto en la orden",
  (malo("conflict-resolve", "newer"), malo("conflict-resolve", 3)), (False, False))
c("una lista de textos, para los flags que se repiten",
  (malo("exclude-from", ["a", "b"]), malo("exclude-from", "a"), malo("exclude-from", [])),
  (False, False, False))
c("una lista de booleanos no es una lista de textos",
  malo("exclude-from", [True]), True)
c("una lista en un flag de un solo valor se comprueba valor a valor",
  (malo("transfers", [4, 8]), malo("transfers", [4, "x"])), (False, True))

# Los tipos que no se comprueban: mejor no opinar que bloquear un valor bueno.
c("un horario de ancho de banda no se comprueba más que sea un valor",
  (malo("bwlimit", "08:00,1M 18:00,off"), malo("bwlimit", "x"), malo("bwlimit", True)),
  (False, False, True))
c("ni un flag que no está en la lista", (malo("flag-que-no-existe", "lo-que-sea"),
                                         malo("flag-que-no-existe", 7)), (False, False))
c("ni las opciones del backend, que viven en rclone.conf",
  malo("s3-region", "eu-west-1"), False)

# El mensaje dice qué se esperaba, con un ejemplo, y es para la persona.
msg = ayuda.problema_valor("transfers", "cuatro")
c("el mensaje nombra el valor y el tipo", ("cuatro" in msg, "número entero" in msg),
  (True, True))
c("  y da un ejemplo", "transfers = 4" in msg, True)
msg = ayuda.problema_valor("timeout", 30)
c("una duración de Go dice que lleva unidad", ("unidad" in msg, '"30s"' in msg), (True, True))
msg = ayuda.problema_valor("min-age", "ayer")
c("una de rclone ofrece `1d` y `off`", ('"1d"' in msg, "off" in msg), (True, True))
msg = ayuda.problema_valor("max-size", "mucho")
c("un tamaño avisa de que sin sufijo son KiB", ("KiB" in msg, '"10M"' in msg), (True, True))
msg = ayuda.problema_valor("checksum", "true")
c("un sí o no pide true sin comillas", ("true" in msg and "comillas" in msg), True)
msg = ayuda.problema_valor("cutoff-mode", "other")
c("una opción de una lista dice cuáles hay", ("HARD" in msg and "SOFT" in msg), True)
msg = ayuda.problema_valor("transfers", True)
c("`true` en un flag con valor dice que necesita uno", "necesita un valor" in msg, True)


# Autocompletar.

def nombres(prefijo, modo=None, propios=None, **kw):
    """Los nombres que se sugieren, en orden."""
    return [f.nombre for f in ayuda.sugerir(prefijo, modo, propios, **kw)]


c("se sugiere por el principio del nombre", nombres("transf")[:1], ["transfers"])
c("con los guiones o sin ellos, igual", nombres("max_del"), nombres("max-del"))
c("lo que empieza por lo escrito va antes que lo que solo lo contiene",
  nombres("delete")[:3], ["delete-after", "delete-before", "delete-during"])
c("  y lo que lo contiene viene después", "max-delete" in nombres("delete", limite=20), True)
c("  (`max-transfer` contiene «transf» pero va detrás de `transfers`)",
  nombres("transf").index("transfers") < nombres("transf").index("max-transfer"), True)
c("sin nada escrito no se sugiere nada (no se tira el catálogo entero a la cara)",
  nombres(""), [])
c("hay un tope", len(nombres("s", limite=5)), 5)
c("lo que no existe no sugiere nada", nombres("zzz"), [])
sugeribles = [n for letra in string.ascii_lowercase for n in nombres(letra, limite=500)]
c("hay muchos que sugerir", len(sugeribles) > 100, True)
c("los reservados no se sugieren: el editor los rechazaría",
  [n for n in sugeribles if model.problema_flag(n)], [])
c("  en concreto, ni `workdir` ni `include` (sí `include-from`, que no es reservado)",
  ("workdir" in nombres("workdir"), "include" in nombres("include"),
   "include-from" in nombres("include")), (False, False, True))
c("lo que ya está escrito en el cuadro no se sugiere otra vez",
  "transfers" in nombres("transf", propios={"transfers": 8}), False)
c("  aunque esté escrito con la otra grafía",
  "transfers" in nombres("transf", propios={"Transfers": 8}), False)
c("un flag solo de bisync se sugiere en bisync", nombres("resil", "bisync"), ["resilient"])
c("  y no en los otros modos, donde rclone no lo conoce",
  [nombres("resil", m) for m in ("up", "down", "up-mirror", "down-mirror")], [[]] * 4)
c("  y sin modo (los flags comunes) tampoco: afectaría a todas",
  nombres("resil", None), [])
c("un flag de copy y sync no se sugiere en bisync", nombres("combin", "bisync"), [])
c("  pero sí en up", nombres("combin", "up"), ["combined"])
c("uno global sí, en cualquier modo",
  ["transfers" in nombres("transf", m) for m in ("bisync", "up", "down-mirror")], [True] * 3)


# La palabra que se está escribiendo.

def palabra(texto, indice=None):
    """`(prefijo, texto de la palabra entera)` en ese punto del cuadro, o None."""
    p = ayuda.palabra_en(texto, len(texto) if indice is None else indice)
    return None if p is None else (p.texto, texto[p.inicio:p.fin])


c("al final de una línea nueva", palabra("transf"), ("transf", "transf"))
c("en la segunda línea", palabra("transfers = 4\nmax-de"), ("max-de", "max-de"))
c("con sangría", palabra("   max-de"), ("max-de", "max-de"))
c("con guion bajo", palabra("max_de"), ("max_de", "max_de"))
c("en medio de la palabra se completa la palabra entera",
  palabra("transfers = 4", 4), ("tran", "transfers"))
c("pasado el igual ya es el valor, no el nombre", palabra("transfers = 4"), None)
c("un comentario no es un flag", palabra("# transf"), None)
c("una línea vacía no tiene palabra", palabra("a = 1\n"), None)
c("la segunda palabra de una línea no es un nombre", palabra("a b"), None)
c("sin nada delante del cursor, nada", palabra("transfers = 4\n"), None)

# Completar.
texto = "transfers = 4\nmax-de"
p = ayuda.palabra_en(texto, len(texto))
nuevo, cursor = ayuda.completar(texto, p, ayuda.conocido("max-delete"))
c("completar pone el nombre y el igual", nuevo, "transfers = 4\nmax-delete = ")
c("  con el cursor donde se escribe el valor", cursor, len(nuevo))
nuevo, cursor = ayuda.completar("checks", ayuda.palabra_en("checks", 6), ayuda.conocido("checksum"))
c("un booleano se completa con true", nuevo, "checksum = true")
nuevo, cursor = ayuda.completar("max-l", ayuda.palabra_en("max-l", 5), ayuda.conocido("max-lock"))
c("un texto o una duración, con las comillas puestas y el cursor dentro",
  (nuevo, nuevo[cursor - 1:cursor + 1]), ('max-lock = ""', '""'))
nuevo, cursor = ayuda.completar("exclude-f", ayuda.palabra_en("exclude-f", 9),
                                ayuda.conocido("exclude-from"))
c("una lista, con sus corchetes", (nuevo, nuevo[cursor - 2:cursor + 2]),
  ('exclude-from = [""]', '[""]'))
nuevo, cursor = ayuda.completar("transf", ayuda.palabra_en("transf", 6), ayuda.conocido("transfers"))
c("un número, sin comillas", nuevo, "transfers = ")
nuevo, cursor = ayuda.completar("tran = 4", ayuda.palabra_en("tran = 4", 4),
                                ayuda.conocido("transfers"))
c("si la línea ya tiene su igual y su valor, solo se cambia el nombre",
  (nuevo, cursor), ("transfers = 4", 9))


c("las líneas del cuadro en las que están esos flags (desde la 1), para marcarlas",
  ayuda.lineas_con("transfers = 4\n\ndelete-after = true\nMax_Delete=3\n# delete-after = 1",
                   {"delete-after", "max-delete"}), [3, 4])
c("  y ninguna si no hay nada que marcar", ayuda.lineas_con("a = 1", set()), [])

# Lo que el desplegable enseña de cada flag, y qué hay ya escrito.
c("los nombres que ya hay escritos, en la forma de rclone",
  ayuda.escritos("transfers = 4\nMax_Delete = 5\n# x = 1\nlo que escribo\n  checksum=true"),
  {"transfers", "max-delete", "checksum"})
c("sin contar la línea en la que está el cursor",
  ayuda.escritos("a = 1\nb = 2\nc = 3", sin_linea_en=7), {"a", "c"})
c("una línea con el cursor y sin igual no cuenta de todas formas",
  ayuda.escritos("a = 1\nb", sin_linea_en=7), {"a"})
c("el tipo, con las palabras de la persona",
  [ayuda.etiqueta_tipo(ayuda.conocido(n)) for n in (
      "checksum", "verbose", "transfers", "tpslimit", "max-lock", "max-size", "log-level",
      "conflict-resolve", "exclude-from", "cutoff-mode", "bwlimit")],
  ["sí o no", "sí o no", "entero", "número", "duración", "tamaño", "nivel", "texto", "lista",
   "opción", "ancho de banda"])
f = ayuda.conocido("transfers")
c("la descripción lleva la ayuda de rclone y el valor de fábrica",
  ("parallel" in ayuda.descripcion(f), "por defecto 4" in ayuda.descripcion(f)), (True, True))
c("  y sin valor de fábrica no inventa uno", "por defecto" in ayuda.descripcion(
    ayuda.conocido("checksum")), False)


# Los avisos: una lista, nunca una excepción.

def av(modo, propios, defaults=None, capa=model.ORIGEN_PAREJA):
    """`[(flag, tipo)]` de los avisos de esos flags, en orden."""
    return [(a.flag, a.tipo) for a in ayuda.avisos(modo, defaults, propios, capa)]


def texto_de(modo, propios, tipo, defaults=None, capa=model.ORIGEN_PAREJA):
    """El texto del primer aviso de ese tipo."""
    return next((a.texto for a in ayuda.avisos(modo, defaults, propios, capa)
                 if a.tipo == tipo), "")


c("sin nada raro, sin avisos", av("bisync", {"transfers": 8, "checksum": True}), [])
c("un flag desconocido no avisa de nada (rclone dirá)", av("up", {"flag-raro": 1}), [])
c("ni un flag quitado (`false` no se pasa)", av("up-mirror", {"delete-after": False}), [])

# Otro modo.
for modo in ("up", "down", "up-mirror", "down-mirror"):
    c(f"un flag de bisync en {modo}", av(modo, {"resilient": True}), [("resilient", "modo")])
t = texto_de("up-mirror", {"resilient": True}, "modo")
c("  dice que es de bisync y que la pasada fallaría",
  ("--resilient" in t, "bisync" in t, "fallaría" in t, "up-mirror" in t),
  (True, True, True, True))
c("un flag de copy y sync en bisync", av("bisync", {"combined": "informe.txt"}),
  [("combined", "modo")])
t = texto_de("bisync", {"combined": "x"}, "modo")
c("  dice que es de copy y sync", ("copy" in t and "sync" in t and "bisync" in t), True)
c("un flag de las tres órdenes no avisa", av("up", {"create-empty-src-dirs": True}), [])
c("uno de sincronizar en un modo que solo copia: no hace nada",
  [av(m, {"max-delete": 5}) for m in ("up", "down")],
  [[("max-delete", "modo")]] * 2)
t = texto_de("up", {"max-delete": 5}, "modo")
c("  y lo dice con las palabras de la persona", ("no hace nada" in t and "copia" in t), True)
c("en un modo que sincroniza, ese mismo, no", av("up-mirror", {"max-delete": 5}), [])
c("ni en bisync (ahí lo avisa el aviso del freno de siempre)", av("bisync", {"max-delete": 5}), [])
c("en [defaults] no hay modo: un flag de bisync afectaría a las que no lo son",
  av(None, {"resilient": True}, capa=model.ORIGEN_DEFAULTS), [("resilient", "modo")])
t = texto_de(None, {"resilient": True}, "modo", capa=model.ORIGEN_DEFAULTS)
c("  y se dice", "las demás parejas" in t or "otros modos" in t, True)
c("  uno de las tres órdenes, no", av(None, {"transfers": 4}, capa=model.ORIGEN_DEFAULTS), [])

# Borrado o reescritura.
c("un flag de borrado avisa", av("up-mirror", {"delete-excluded": True}),
  [("delete-excluded", "borrado")])
t = texto_de("up-mirror", {"delete-excluded": True}, "borrado")
c("  y manda a «Simular», que es --dry-run", ("Simular" in t, "--dry-run" in t), (True, True))
for flag, valor in (("delete-before", True), ("ignore-errors", True), ("inplace", True),
                    ("ignore-times", True), ("track-renames", True), ("fix-case", True),
                    ("no-check-dest", True), ("force", True), ("remove-empty-dirs", True),
                    ("conflict-loser", "delete"), ("resync-mode", "newer")):
    modo = "bisync" if flag in ("force", "remove-empty-dirs", "conflict-loser",
                                "resync-mode") else "up-mirror"
    c(f"  {flag} = {valor!r} es de borrado o reescritura",
      ("borrado" in [t for f, t in av(modo, {flag: valor}) if f == flag]), True)
c("pero conflict-loser = num no borra nada", av("bisync", {"conflict-loser": "num"}), [])
c("ni los que solo cambian cómo se compara", av("up", {"size-only": True}), [])

# Choques.
c("dos de borrado a la vez: rclone aborta",
  [x for x in av("up-mirror", {"delete-before": True, "delete-after": True}) if x[1] == "choque"],
  [("delete-before", "choque")])
t = texto_de("up-mirror", {"delete-before": True, "delete-after": True}, "choque")
c("  y se dice qué dos y qué pasa", ("--delete-before" in t and "--delete-after" in t
                                      and "solo uno" in t), True)
c("con uno propio y otro heredado de [defaults], también",
  [x for x in av("up-mirror", {"delete-before": True}, {"delete-after": True})
   if x[1] == "choque"], [("delete-before", "choque")])
c("pero entre dos heredados no es cosa de esta pareja",
  [x for x in av("up-mirror", {}, {"delete-before": True, "delete-after": True})], [])
c("--size-only pisa a --checksum: el aviso va con el primero de la tabla",
  [x for x in av("up", {"size-only": True, "checksum": True}) if x[1] == "choque"],
  [("size-only", "choque")])
c("  y con uno solo propio, con el propio",
  [x for x in av("up", {"checksum": True}, {"size-only": True}) if x[1] == "choque"],
  [("checksum", "choque")])
c("--ignore-existing pisa a --ignore-times",
  [x for x in av("down", {"ignore-existing": True, "ignore-times": True}) if x[1] == "choque"],
  [("ignore-existing", "choque")])
c("en bisync, --remove-empty-dirs choca con --create-empty-src-dirs, que ya trae prdrive",
  [x for x in av("bisync", {"remove-empty-dirs": True}) if x[1] == "choque"],
  [("remove-empty-dirs", "choque")])
t = texto_de("bisync", {"remove-empty-dirs": True}, "choque")
c("  y dice con qué", "--create-empty-src-dirs" in t, True)
c("--force se salta el --max-delete que trae el modo bisync",
  [x for x in av("bisync", {"force": True}) if x[1] == "choque"], [("force", "choque")])
c("un choque entre flags apagados no es un choque",
  [x for x in av("up", {"size-only": True, "checksum": False}) if x[1] == "choque"], [])
c("ni en un modo donde uno de los dos no existe",
  [x for x in av("up", {"force": True, "max-delete": 5}) if x[1] == "choque"], [])

# El orden es el de escritura, y un aviso por motivo.
juntos = av("up-mirror", {"delete-before": True, "transfers": 4, "delete-excluded": True})
c("los avisos siguen el orden en que se escribió cada flag",
  [f for f, _t in juntos], ["delete-before", "delete-excluded"])
propios = {"delete-before": True, "delete-after": True}
heredados_ = {"transfers": 2}
copia_p, copia_h = dict(propios), dict(heredados_)
ayuda.avisos("up-mirror", heredados_, propios)
c("avisos() no toca lo que recibe", (propios, heredados_), (copia_p, copia_h))

# La tabla a mano no se pudre: lo que cita existe en la lista de rclone, y lo que la lista
# dice que es solo de bisync está en la tabla (así un flag nuevo de rclone obliga a decidir).
c("todo lo que cita la tabla de borrado existe en rclone",
  [n for n in ayuda.BORRADO if ayuda.conocido(n) is None], [])
c("y lo de la tabla de choques",
  [n for ch in ayuda.CHOQUES for n in ch.flags if ayuda.conocido(n) is None], [])
c("y lo de sincronizar",
  [n for n in ayuda.SOLO_SINCRONIZA if ayuda.conocido(n) is None], [])
MODO_DE = {"bisync": "bisync", "copy": "up", "sync": "up-mirror"}
"""Un modo de prdrive por cada orden de rclone."""
fuera = []
for n, f in datos.flags.items():
    if not f.propio:
        continue
    for verbo, modo in MODO_DE.items():
        if verbo not in f.comandos and not any(
                a.tipo == "modo" for a in ayuda.avisos(modo, None, {n: True})):
            fuera.append((n, modo))
c("cada flag que rclone solo conoce en unas órdenes avisa en el modo de las otras", fuera, [])
dentro = []
for n, f in datos.flags.items():
    for verbo in f.comandos:
        if f.propio and any(a.tipo == "modo" for a in ayuda.avisos(MODO_DE[verbo], None, {n: True})):
            dentro.append((n, verbo))
c("y no avisa en las órdenes donde sí existe", dentro, [])

sys.exit(c.report())
