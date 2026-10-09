#!/usr/bin/env python3
"""La configuración del servicio (`ui/prefs.py`).

Qué recuerda, qué olvida y qué no llega a escribir. Y, aparte, el ancho y lo
que ocupan lo que va encima y lo que va debajo de la lista que recuerda la
ventana principal (`state/ventana.json`).
"""

import json
import sys
import time
from pathlib import Path

from _harness import Checks, mkcfg, sandbox, tmpdir

from ui import prefs

c = Checks("memoria de la UI (ui/prefs.py)")
prefs.PREFS = tmpdir("prdrive-prefs-") / "ui_prefs.json"

CFG = mkcfg(["upload", "claves", "docs", "prdrive"],
            {"pairs": ["docs", "claves"], "interval_minutes": 15})
ALL = CFG.names

# Sin recuerdo manda [daemon] del TOML.
c("sin recuerdo", prefs.startup_defaults(CFG), (["docs", "claves"], 15.0, None))

# Una elección de la UI manda sobre el TOML.
prefs.save_prefs("daemon", ["docs"], 7.0, ALL)
pairs, interval, memo = prefs.startup_defaults(CFG)
c("tras elegir docs/7min", (pairs, interval), (["docs"], 7.0))
c("y se anuncia", memo is not None and memo.startswith("Parejas e intervalo del servicio"),
  True)

# Repetir la misma elección no gasta un ciclo de escritura del dispositivo.
mtime = prefs.PREFS.stat().st_mtime_ns
time.sleep(0.05)
prefs.save_prefs("daemon", ["docs"], 7.0, ALL)
c("elección idéntica no reescribe", prefs.PREFS.stat().st_mtime_ns, mtime)

# Una pareja añadida al TOML después entra marcada: nadie la desmarcó nunca.
CFG2 = mkcfg(["upload", "claves", "docs", "prdrive", "fotos"],
             {"pairs": ["docs", "claves"], "interval_minutes": 15})
c("pareja nueva se marca sola", prefs.startup_defaults(CFG2)[0], ["docs", "fotos"])

# El orden es el del TOML, no el del guardado.
prefs.save_prefs("daemon", ["prdrive", "upload"], 7.0, ALL)
c("orden del TOML", prefs.startup_defaults(CFG)[0], ["upload", "prdrive"])

# TOML regenerado con otros nombres: todas cuentan como nuevas.
c("TOML regenerado: todas nuevas",
  prefs.startup_defaults(mkcfg(["nuevo-a", "nuevo-b"]))[:2], (["nuevo-a", "nuevo-b"], 7.0))

# Lo elegido ya no existe y no hay parejas nuevas: se vuelve al TOML sin
# presumir de un recuerdo que ya no aplica (nota None).
prefs.save_prefs("daemon", ["upload"], 9.0, ALL)
c("elegida borrada del TOML",
  prefs.startup_defaults(mkcfg(["claves", "docs", "prdrive"],
                               {"pairs": ["claves"], "interval_minutes": 20})),
  (["claves"], 20.0, None))

# Un registro 'manual' es de antes de que las pasadas manuales dejaran de
# escribir aquí: el recuerdo de una pasada suelta no decide el servicio.
prefs.PREFS.write_text(json.dumps({"action": "manual", "pairs": ["upload"], "known": ALL,
                                   "interval_min": 5, "saved": "2026-01-01 00:00:00"}),
                       encoding="utf-8")
c("un registro 'manual' no cuenta", prefs.startup_defaults(CFG),
  (["docs", "claves"], 15.0, None))

# Uno sin `action` (escrito a mano) sí.
prefs.PREFS.write_text(json.dumps({"pairs": ["upload"], "known": ALL, "interval_min": 5}),
                       encoding="utf-8")
c("un registro sin 'action' vale", prefs.startup_defaults(CFG)[:2], (["upload"], 5.0))

# Ficheros rotos: nunca son un error, solo "no hay nada escrito".
prefs.PREFS.write_text("{ esto no es json", encoding="utf-8")
c("json corrupto", prefs.startup_defaults(CFG), (["docs", "claves"], 15.0, None))

prefs.PREFS.write_text(json.dumps({"pairs": [1, {"x": 2}, "docs"], "known": "no-lista",
                                   "interval_min": "abc", "saved": "2026-01-01 00:00:00"}),
                       encoding="utf-8")
c("tipos inválidos dentro del json", prefs.startup_defaults(CFG)[:2], (["docs"], 15.0))

prefs.PREFS.write_text(json.dumps({"pairs": ["upload"], "known": ALL, "interval_min": 0}),
                       encoding="utf-8")
c("intervalo 0 -> mínimo 1 min", prefs.startup_defaults(CFG)[1], 1.0)


# «Ajustes → Configuración» guarda SOLO el intervalo (#65).
#
# Sin parejas elegidas, el registro queda sin `pairs`: las parejas siguen
# saliendo del TOML, y un `[daemon]` cambiado a mano después sigue mandando.
prefs.PREFS.unlink()
c("guardar el intervalo sin recuerdo", prefs.guardar_intervalo(CFG, 12.0), True)
guardado = json.loads(prefs.PREFS.read_text(encoding="utf-8"))
c("  no escribe parejas", ("pairs" in guardado, "known" in guardado, guardado["interval_min"]),
  (False, False, 12.0))
pairs, interval, memo = prefs.startup_defaults(CFG)
c("  las parejas siguen siendo las del TOML, con el intervalo guardado",
  (pairs, interval), (["docs", "claves"], 12.0))
c("  y se anuncia como intervalo", memo.startswith("Intervalo del servicio"), True)
c("  un [daemon] cambiado después sigue mandando en las parejas",
  prefs.startup_defaults(mkcfg(ALL, {"pairs": ["upload"], "interval_minutes": 15}))[:2],
  (["upload"], 12.0))
mtime = prefs.PREFS.stat().st_mtime_ns
time.sleep(0.05)
c("  el mismo intervalo otra vez no reescribe",
  (prefs.guardar_intervalo(CFG, 12.0), prefs.PREFS.stat().st_mtime_ns), (True, mtime))

# Con parejas elegidas al arrancar el servicio, se conservan tal cual.
prefs.save_prefs("daemon", ["prdrive"], 7.0, ALL)
prefs.guardar_intervalo(CFG, 45.0)
guardado = json.loads(prefs.PREFS.read_text(encoding="utf-8"))
c("con parejas elegidas, guardar el intervalo las conserva",
  (guardado["action"], guardado["pairs"], guardado["known"], guardado["interval_min"]),
  ("daemon", ["prdrive"], ALL, 45.0))
c("  y el servicio sale con ellas y el intervalo nuevo",
  prefs.startup_defaults(CFG)[:2], (["prdrive"], 45.0))
# «Iniciar servicio» después escribe las parejas con el intervalo guardado.
prefs.save_prefs("daemon", ["docs"], prefs.startup_defaults(CFG)[1], ALL)
c("«Iniciar servicio» después: sus parejas y el intervalo de Configuración",
  prefs.startup_defaults(CFG)[:2], (["docs"], 45.0))

# Un registro `manual` de antes no cuenta: se cambia por uno de solo intervalo.
prefs.PREFS.write_text(json.dumps({"action": "manual", "pairs": ["upload"], "known": ALL,
                                   "interval_min": 5}), encoding="utf-8")
prefs.guardar_intervalo(CFG, 20.0)
c("sobre un registro 'manual': queda solo el intervalo",
  ("pairs" in json.loads(prefs.PREFS.read_text(encoding="utf-8")),
   prefs.startup_defaults(CFG)[:2]), (False, (["docs", "claves"], 20.0)))

# Un registro sin parejas y con un intervalo roto: como si no hubiera nada.
prefs.PREFS.write_text(json.dumps({"interval_min": "abc"}), encoding="utf-8")
c("solo intervalo, pero ilegible: el del TOML", prefs.startup_defaults(CFG),
  (["docs", "claves"], 15.0, None))
prefs.PREFS.write_text('{"interval_min": Infinity}', encoding="utf-8")
c("  infinito tampoco vale", prefs.startup_defaults(CFG)[1], 15.0)

# Marcar o desmarcar una casilla de la ventana guarda SOLO las parejas.
#
# Sin recuerdo no se fija el intervalo: sigue saliendo de `[daemon]`.
prefs.PREFS.unlink()
c("guardar parejas sin recuerdo", prefs.guardar_parejas(CFG, ["prdrive", "upload"]), True)
guardado = json.loads(prefs.PREFS.read_text(encoding="utf-8"))
c("  escribe las parejas en el orden del TOML y las conocidas, sin intervalo",
  (guardado["action"], guardado["pairs"], guardado["known"], "interval_min" in guardado),
  ("daemon", ["upload", "prdrive"], ALL, False))
c("  el servicio sale con ellas y el intervalo del TOML",
  prefs.startup_defaults(CFG)[:2], (["upload", "prdrive"], 15.0))
mtime = prefs.PREFS.stat().st_mtime_ns
time.sleep(0.05)
c("  la misma selección otra vez no reescribe",
  (prefs.guardar_parejas(CFG, ["upload", "prdrive"]), prefs.PREFS.stat().st_mtime_ns),
  (True, mtime))

# Con un intervalo guardado («Configuración»), se conserva.
prefs.guardar_intervalo(CFG, 45.0)
prefs.guardar_parejas(CFG, ["docs"])
c("con un intervalo guardado, guardar las parejas lo conserva",
  prefs.startup_defaults(CFG)[:2], (["docs"], 45.0))

# Una selección vacía no se guarda: `elegir` la leería como si no hubiera
# recuerdo. Tampoco entra lo que no es una pareja de la configuración.
mtime = prefs.PREFS.stat().st_mtime_ns
c("una selección vacía no se guarda", prefs.guardar_parejas(CFG, []), False)
c("  ni nombres que no existen", prefs.guardar_parejas(CFG, ["fantasma"]), False)
c("  y lo anterior sigue como estaba",
  (prefs.PREFS.stat().st_mtime_ns, prefs.startup_defaults(CFG)[0]), (mtime, ["docs"]))

# Sobre un registro `manual` de antes, lo reemplaza.
prefs.PREFS.write_text(json.dumps({"action": "manual", "pairs": ["upload"], "known": ALL,
                                   "interval_min": 5}), encoding="utf-8")
prefs.guardar_parejas(CFG, ["claves"])
c("sobre un registro 'manual': vale la selección nueva",
  prefs.startup_defaults(CFG)[:2], (["claves"], 5.0))

# Lo que se escribe en la pantalla.
for texto, minutos in (("12", 12.0), (" 2,5 ", 2.5), ("1", 1.0), ("1440", 1440.0)):
    c(f"revisar_intervalo({texto!r})", prefs.revisar_intervalo(texto), minutos)
for texto in ("", "abc", "0", "0,5", "-3", "nan", "inf"):
    try:
        prefs.revisar_intervalo(texto)
        malo = None
    except ValueError as e:
        malo = str(e)
    c(f"revisar_intervalo({texto!r}) no vale, y dice por qué",
      malo, "El intervalo tiene que ser un número de minutos: 1 o más.")

# El clic en una casilla no escribe: la selección se recuerda y se vuelca después.
#
# `poner()` solo apunta; `volcar()` escribe una vez, con la última, antes de una
# pasada, del servicio o de cerrar. Es el fichero de coordinación con el
# servicio y el agente: lo que escribe sigue siendo lo mismo que `guardar_parejas`.
from common import store  # noqa: E402

c("ESPERA_MS: lo que se espera a más clics antes de escribir", prefs.ESPERA_MS, 250)

prefs.PREFS.unlink()
sel = prefs.SeleccionPendiente()
c("sin nada apuntado: no hay pendiente y volcar no hace nada",
  (sel.pendiente, sel.volcar(), prefs.PREFS.exists()), (False, None, False))

escrituras = []
escribir_real = store.write_json


def contar_escrituras(ruta, datos):
    """Escribe de verdad y apunta que lo ha hecho."""
    escrituras.append(datos)
    return escribir_real(ruta, datos)


store.write_json = contar_escrituras
try:
    sel.poner(CFG, ["upload"])
    sel.poner(CFG, ["upload", "docs"])
    sel.poner(CFG, ["claves"])
    c("poner() no escribe, solo apunta",
      (sel.pendiente, escrituras, prefs.PREFS.exists()), (True, [], False))
    c("volcar() escribe la última selección, una sola vez",
      (sel.volcar(), len(escrituras), prefs.startup_defaults(CFG)[0]), (True, 1, ["claves"]))
    c("  y se olvida de ella", (sel.pendiente, sel.volcar(), len(escrituras)), (False, None, 1))

    # Volcar sin que haya nada pendiente no toca el fichero.
    mtime = prefs.PREFS.stat().st_mtime_ns
    time.sleep(0.05)
    c("volcar() sin nada pendiente deja el fichero como está",
      (sel.volcar(), prefs.PREFS.stat().st_mtime_ns), (None, mtime))

    # La misma selección que ya está guardada es True y no gasta escritura.
    sel.poner(CFG, ["claves"])
    c("volcar() de lo que ya estaba guardado dice que sí y no escribe",
      (sel.volcar(), len(escrituras)), (True, 1))

    # Una selección vacía no se escribe (como `guardar_parejas`), y tampoco queda pendiente.
    sel.poner(CFG, [])
    c("una selección vacía no se escribe",
      (sel.pendiente, sel.volcar(), sel.pendiente, len(escrituras),
       prefs.startup_defaults(CFG)[0]), (True, False, False, 1, ["claves"]))

    # Lo apuntado lleva su config: manda el de la última vez.
    sel.poner(mkcfg(["a", "b"]), ["a"])
    sel.poner(CFG, ["docs"])
    c("manda el config de la última selección",
      (sel.volcar(), prefs.startup_defaults(CFG)[0]), (True, ["docs"]))

    # Un dispositivo de solo lectura (o ya extraído) devuelve False y se olvida igual.
    store.write_json = lambda ruta, datos: False
    sel.poner(CFG, ["upload"])
    c("un dispositivo que no se deja escribir: False, y no queda pendiente",
      (sel.volcar(), sel.pendiente), (False, False))
    c("  y lo guardado no ha cambiado", prefs.startup_defaults(CFG)[0], ["docs"])
finally:
    store.write_json = escribir_real

# Volcar nunca lanza, pase lo que pase al escribir.
guardar_real = prefs.guardar_parejas


def guardar_roto(config, pairs):
    """Falla como no debería fallar `guardar_parejas`."""
    raise RuntimeError("no debería pasar")


prefs.guardar_parejas = guardar_roto
try:
    sel.poner(CFG, ["upload"])
    c("volcar() no lanza aunque guardar falle: False, y se olvida",
      (sel.volcar(), sel.pendiente), (False, False))
finally:
    prefs.guardar_parejas = guardar_real

# Se busca `guardar_parejas` al volcar, no al crear: lo que lo sustituya lo ve.
llamadas = []
prefs.guardar_parejas = lambda config, pairs: llamadas.append((config, list(pairs))) or True
try:
    sel.poner(CFG, ["upload", "docs"])
    c("volcar() llama a guardar_parejas con el config y la selección",
      (sel.volcar(), llamadas), (True, [(CFG, ["upload", "docs"])]))
finally:
    prefs.guardar_parejas = guardar_real

# Lo apuntado es una copia: cambiar la lista después no cambia lo que se vuelca.
lista = ["upload"]
sel.poner(CFG, lista)
lista.append("docs")
sel.volcar()
c("la selección apuntada es una copia", prefs.startup_defaults(CFG)[0], ["upload"])

# Desmarcarlas todas seguidas deja escrita la última selección que tenía alguna,
# como cuando cada clic escribía: [upload, docs] y [docs] se escribían y la vacía
# no. Sin nada pendiente, una vacía no se escribe y queda lo guardado.
llamadas = []
prefs.guardar_parejas = lambda config, pairs: llamadas.append(list(pairs)) or True
try:
    sel.poner(CFG, ["upload", "docs"])
    sel.poner(CFG, ["docs"])
    sel.poner(CFG, [])
    c("desmarcar todas seguidas vuelca la última con alguna marcada",
      (sel.pendiente, sel.volcar(), llamadas), (True, True, [["docs"]]))
    sel.poner(CFG, ["upload"])
    sel.poner(CFG, [])
    sel.poner(CFG, ["claves"])
    c("  y volver a marcar después manda", (sel.volcar(), llamadas[-1]), (True, ["claves"]))
finally:
    prefs.guardar_parejas = guardar_real
sel.poner(CFG, [])
c("  sin nada pendiente, la vacía no escribe y queda lo de antes",
  (sel.volcar(), prefs.startup_defaults(CFG)[0]), (False, ["upload"]))

# El ancho de la ventana principal va en `state/ventana.json`, no en `ui_prefs.json`:
# el agente recarga su servicio con cualquier cambio de ese fichero. La ruta se mira
# al llamar, porque los tests (y `sandbox()`) mueven `STATE_DIR`.
from common import model  # noqa: E402

with sandbox():
    ruta = model.STATE_DIR / "ventana.json"
    c("el ancho va en state/ventana.json, mirado al llamar", prefs.ruta_ventana(), ruta)
    clave = prefs.clave_ancho("9.0", 4 / 3)
    otra = prefs.clave_ancho("9.0", 2.0)
    c("la clave: el sistema, la versión de Tk y la escala de Tk",
      (clave, otra), (f"{sys.platform}:9.0:1.333", f"{sys.platform}:9.0:2.000"))
    c("  y otra versión de Tk es otra clave", prefs.clave_ancho("8.6", 4 / 3) != clave, True)
    c("sin fichero no hay ancho recordado", prefs.recordado("ancho", clave), None)

    anotadas = []

    def anotar_escritura(destino, datos):
        """Escribe de verdad y apunta qué fichero."""
        anotadas.append(Path(destino).name)
        return escribir_real(destino, datos)

    store.write_json = anotar_escritura
    try:
        c("recordar un ancho lo escribe", (prefs.recordar("ancho", clave, 587), anotadas),
          (True, ["ventana.json"]))
        c("  y se lee con su clave", prefs.recordado("ancho", clave), 587)
        c("  con otra no", prefs.recordado("ancho", otra), None)
        c("  en la forma {\"ancho\": {clave: px}}",
          json.loads(ruta.read_text(encoding="utf-8")), {"ancho": {clave: 587}})
        c("el mismo ancho otra vez no escribe nada",
          (prefs.recordar("ancho", clave, 587), len(anotadas)), (True, 1))
        prefs.recordar("ancho", otra, 900)
        prefs.recordar("ancho", clave, 560)
        c("cada clave guarda el suyo, y cambiar uno conserva los otros",
          (json.loads(ruta.read_text(encoding="utf-8")), len(anotadas)),
          ({"ancho": {clave: 560, otra: 900}}, 3))
        c("ui_prefs.json no se toca", "ui_prefs.json" in anotadas, False)

        # Lo que no es un ancho no se reserva: un fichero a medias, tocado a mano o
        # de otra versión vale como si no hubiera nada.
        for contenido in ('{"ancho": {"%s": true}}' % clave, '{"ancho": {"%s": "587"}}' % clave,
                          '{"ancho": {"%s": 0}}' % clave, '{"ancho": {"%s": -5}}' % clave,
                          '{"ancho": {"%s": 5.5}}' % clave, '{"ancho": [587]}', '[587]',
                          '{"ancho": ', ''):
            ruta.write_text(contenido, encoding="utf-8")
            c(f"  {contenido!r} no es un ancho", prefs.recordado("ancho", clave), None)
        c("  y recordar sobre uno así lo rehace entero",
          (prefs.recordar("ancho", clave, 587), json.loads(ruta.read_text(encoding="utf-8"))),
          (True, {"ancho": {clave: 587}}))

        # Un dispositivo de solo lectura (o ya extraído) no recuerda, y no pasa nada.
        store.write_json = lambda destino, datos: False
        c("si no se puede escribir: False, sin lanzar", prefs.recordar("ancho", clave, 600), False)
        c("  y queda lo que había", prefs.recordado("ancho", clave), 587)
    finally:
        store.write_json = escribir_real

# Lo que ocupa lo que va encima de la lista ("arriba") se recuerda en el mismo fichero, con la
# misma clave y la misma regla que el ancho; 0 es un valor (la última vez no había nada).
with sandbox():
    ruta = model.STATE_DIR / "ventana.json"
    clave = prefs.clave_ancho("9.0", 4 / 3)
    otra = prefs.clave_ancho("9.0", 2.0)
    c("sin fichero no hay alto recordado", prefs.recordado("arriba", clave), None)
    anotadas = []

    def anotar_escritura(destino, datos):
        """Escribe de verdad y apunta qué fichero."""
        anotadas.append(Path(destino).name)
        return escribir_real(destino, datos)

    store.write_json = anotar_escritura
    try:
        c("recordar un alto lo escribe", (prefs.recordar("arriba", clave, 51), anotadas),
          (True, ["ventana.json"]))
        c("  y se lee con su clave, no con otra",
          (prefs.recordado("arriba", clave), prefs.recordado("arriba", otra)), (51, None))
        c("  en la forma {\"arriba\": {clave: px}}",
          json.loads(ruta.read_text(encoding="utf-8")), {"arriba": {clave: 51}})
        c("el mismo alto otra vez no escribe nada",
          (prefs.recordar("arriba", clave, 51), len(anotadas)), (True, 1))
        c("0 es un valor: se escribe, se lee y no es 'nada recordado'",
          (prefs.recordar("arriba", clave, 0), prefs.recordado("arriba", clave), len(anotadas)),
          (True, 0, 2))
        c("  y 0 otra vez tampoco escribe", (prefs.recordar("arriba", clave, 0), len(anotadas)),
          (True, 2))

        # Comparte fichero con el ancho: cada uno conserva el del otro y las demás claves.
        prefs.recordar("ancho", clave, 587)
        prefs.recordar("arriba", otra, 90)
        prefs.recordar("arriba", clave, 51)
        c("el alto conserva el ancho y las otras claves, y el ancho el alto",
          json.loads(ruta.read_text(encoding="utf-8")),
          {"arriba": {clave: 51, otra: 90}, "ancho": {clave: 587}})
        c("  cada uno se lee con lo suyo",
          (prefs.recordado("ancho", clave), prefs.recordado("arriba", clave)), (587, 51))
        prefs.recordar("ancho", clave, 600)
        c("  cambiar el ancho no toca el alto",
          json.loads(ruta.read_text(encoding="utf-8"))["arriba"], {clave: 51, otra: 90})

        # Un fichero de antes (solo "ancho") sigue valiendo: no hay alto recordado.
        ruta.write_text(json.dumps({"ancho": {clave: 587}}), encoding="utf-8")
        c("un fichero de antes, sin \"arriba\": ancho sí, alto no",
          (prefs.recordado("ancho", clave), prefs.recordado("arriba", clave)), (587, None))
        n = len(anotadas)
        c("  y apuntar el alto conserva el ancho",
          (prefs.recordar("arriba", clave, 51), json.loads(ruta.read_text(encoding="utf-8")),
           len(anotadas) - n),
          (True, {"ancho": {clave: 587}, "arriba": {clave: 51}}, 1))

        # Lo que no es un alto no se reserva (un negativo, un texto, un booleano, un
        # decimal, un fichero a medias o de otra versión).
        for contenido in ('{"arriba": {"%s": true}}' % clave, '{"arriba": {"%s": "51"}}' % clave,
                          '{"arriba": {"%s": -5}}' % clave, '{"arriba": {"%s": 5.5}}' % clave,
                          '{"arriba": [51]}', '[51]', '{"arriba": ', ''):
            ruta.write_text(contenido, encoding="utf-8")
            c(f"  {contenido!r} no es un alto", prefs.recordado("arriba", clave), None)
        c("  y recordar sobre uno así lo rehace entero",
          (prefs.recordar("arriba", clave, 51), json.loads(ruta.read_text(encoding="utf-8"))),
          (True, {"arriba": {clave: 51}}))

        # Un dispositivo de solo lectura (o ya extraído) no recuerda, y no pasa nada.
        store.write_json = lambda destino, datos: False
        c("si no se puede escribir: False, sin lanzar", prefs.recordar("arriba", clave, 77), False)
        c("  y queda lo que había", prefs.recordado("arriba", clave), 51)
    finally:
        store.write_json = escribir_real

# Lo mismo con lo que va DEBAJO de la lista ("abajo"): su propio campo del mismo fichero, con la
# misma clave y la misma regla; ninguno de los tres pisa a los otros.
with sandbox():
    ruta = model.STATE_DIR / "ventana.json"
    clave = prefs.clave_ancho("9.0", 4 / 3)
    otra = prefs.clave_ancho("9.0", 2.0)
    c("sin fichero no hay alto de abajo recordado", prefs.recordado("abajo", clave), None)
    anotadas = []

    def anotar_escritura_abajo(destino, datos):
        """Escribe de verdad y apunta qué fichero."""
        anotadas.append(Path(destino).name)
        return escribir_real(destino, datos)

    store.write_json = anotar_escritura_abajo
    try:
        c("recordar el alto de abajo lo escribe", (prefs.recordar("abajo", clave, 112), anotadas),
          (True, ["ventana.json"]))
        c("  y se lee con su clave, no con otra",
          (prefs.recordado("abajo", clave), prefs.recordado("abajo", otra)), (112, None))
        c("  en la forma {\"abajo\": {clave: px}}",
          json.loads(ruta.read_text(encoding="utf-8")), {"abajo": {clave: 112}})
        c("el mismo alto otra vez no escribe nada",
          (prefs.recordar("abajo", clave, 112), len(anotadas)), (True, 1))
        c("0 es un valor: se escribe, se lee y no es 'nada recordado'",
          (prefs.recordar("abajo", clave, 0), prefs.recordado("abajo", clave), len(anotadas)),
          (True, 0, 2))

        # Comparte fichero con el ancho y con "arriba": cada campo conserva los de los demás.
        prefs.recordar("ancho", clave, 587)
        prefs.recordar("arriba", clave, 51)
        prefs.recordar("abajo", otra, 90)
        prefs.recordar("abajo", clave, 112)
        c("el alto de abajo conserva el ancho, el de arriba y las otras claves",
          json.loads(ruta.read_text(encoding="utf-8")),
          {"abajo": {clave: 112, otra: 90}, "ancho": {clave: 587}, "arriba": {clave: 51}})
        c("  cada uno se lee con lo suyo",
          (prefs.recordado("ancho", clave), prefs.recordado("arriba", clave),
           prefs.recordado("abajo", clave)), (587, 51, 112))
        prefs.recordar("arriba", clave, 60)
        prefs.recordar("ancho", clave, 600)
        c("  y cambiar el ancho o el de arriba no toca el de abajo",
          json.loads(ruta.read_text(encoding="utf-8"))["abajo"], {clave: 112, otra: 90})

        # Un fichero de antes (sin "abajo") sigue valiendo: no hay alto de abajo recordado.
        ruta.write_text(json.dumps({"ancho": {clave: 587}, "arriba": {clave: 51}}),
                        encoding="utf-8")
        c("un fichero de antes, sin \"abajo\": los otros dos sí, ese no",
          (prefs.recordado("ancho", clave), prefs.recordado("arriba", clave),
           prefs.recordado("abajo", clave)), (587, 51, None))
        n = len(anotadas)
        c("  y apuntar el de abajo conserva los otros dos",
          (prefs.recordar("abajo", clave, 112), json.loads(ruta.read_text(encoding="utf-8")),
           len(anotadas) - n),
          (True, {"ancho": {clave: 587}, "arriba": {clave: 51}, "abajo": {clave: 112}}, 1))

        # Lo que no es un alto no se reserva (un negativo, un texto, un booleano, un
        # decimal, un fichero a medias o de otra versión).
        for contenido in ('{"abajo": {"%s": true}}' % clave, '{"abajo": {"%s": "112"}}' % clave,
                          '{"abajo": {"%s": -5}}' % clave, '{"abajo": {"%s": 5.5}}' % clave,
                          '{"abajo": [112]}', '[112]', '{"abajo": ', ''):
            ruta.write_text(contenido, encoding="utf-8")
            c(f"  {contenido!r} no es un alto", prefs.recordado("abajo", clave), None)
        c("  y recordar sobre uno así lo rehace entero",
          (prefs.recordar("abajo", clave, 112), json.loads(ruta.read_text(encoding="utf-8"))),
          (True, {"abajo": {clave: 112}}))

        # Un dispositivo de solo lectura (o ya extraído) no recuerda, y no pasa nada.
        store.write_json = lambda destino, datos: False
        c("si no se puede escribir: False, sin lanzar", prefs.recordar("abajo", clave, 77), False)
        c("  y queda lo que había", prefs.recordado("abajo", clave), 112)
    finally:
        store.write_json = escribir_real

# Sin poder ni crear la carpeta de state/ (ocupada por un fichero) tampoco lanza.
with sandbox():
    model.STATE_DIR.rmdir()
    model.STATE_DIR.write_text("no soy una carpeta", encoding="utf-8")
    clave = prefs.clave_ancho("9.0", 4 / 3)
    c("con state/ imposible: leer es None y recordar False, sin lanzar",
      (prefs.recordado("arriba", clave), prefs.recordar("arriba", clave, 51),
       prefs.recordar("ancho", clave, 587), prefs.recordado("abajo", clave),
       prefs.recordar("abajo", clave, 112)), (None, False, False, None, False))

# Un campo que no está en CAMPOS_VENTANA es un error de quien llama: no se lee ni se escribe.
with sandbox():
    clave = prefs.clave_ancho("9.0", 4 / 3)

    def lanza(llamada) -> bool:
        """Si la llamada lanza `ValueError`."""
        try:
            llamada()
        except ValueError:
            return True
        return False

    c("un campo que no está en CAMPOS_VENTANA lanza ValueError, al leer y al escribir",
      (lanza(lambda: prefs.recordado("alto", clave)),
       lanza(lambda: prefs.recordar("alto", clave, 5)),
       prefs.ruta_ventana().exists()), (True, True, False))

sys.exit(c.report())
