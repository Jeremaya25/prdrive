#!/usr/bin/env python3
"""La configuración del servicio (`ui/prefs.py`).

Qué recuerda, qué olvida y qué no llega a escribir.
"""

import json
import sys
import time
from pathlib import Path

from _harness import Checks, mkcfg, tmpdir

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

sys.exit(c.report())
