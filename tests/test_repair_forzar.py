#!/usr/bin/env python3
"""«Forzar sincronización…» de «Reparación» (`ui/repair.py`), sin Tk.

Forzar salta el freno de borrados de UNA pasada, y lo que salta es justo lo que
protege de perder datos: por eso aquí se comprueba, más que nada, lo que NO se
ofrece, lo que el plan dice antes de que nadie pulse «Seguir adelante» y que
nada de esto escribe en el dispositivo. La decisión de qué botón sale en cada
avería es de `ui/repair.py` y la ventana solo la dibuja (`test_tk_reparacion.py`).
"""

import hashlib
import sys
from pathlib import Path

from _harness import Checks, mkcfg, sandbox
from _logs_frenos import BISYNC_BORRADOS, BISYNC_CAMBIADOS, ESPEJO_DOWN, ESPEJO_UP

from common import bisync, frenos, model, results, revision
from ui import repair

c = Checks("forzar desde «Reparación» (ui/repair.py)")

BISYNC = {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas"}
CON_VERSIONES = dict(BISYNC, versions=True)
SUBIDA = {"name": "espejo", "mode": "up-mirror", "local": "sync-data/espejo",
          "remote_path": "/R/espejo"}
BAJADA = {"name": "bajada", "mode": "down-mirror", "local": "sync-data/bajada",
          "remote_path": "/R/bajada"}
COPIA = {"name": "copia", "mode": "up", "local": "sync-data/copia", "remote_path": "/R/copia"}


def listados(pair):
    """Un baseline en disco, como lo deja un --resync."""
    pair.workdir.mkdir(parents=True, exist_ok=True)
    for sufijo in (bisync.PATH1_SUFFIX, bisync.PATH2_SUFFIX):
        (pair.workdir / f"{bisync.expected_prefix(pair)}{sufijo}").write_text(
            "listado\n", encoding="utf-8")
    ffile = bisync.filters_file_for(pair)
    if ffile is not None:
        Path(str(ffile) + ".md5").write_text(
            hashlib.md5(ffile.read_bytes()).hexdigest(), encoding="utf-8")


def con_freno(raw, texto, *, rc=1, carpeta=True, llenar=True, baseline=True):
    """Deja una pareja cuya última pasada paró ese freno; devuelve `(config, pareja, hallazgo)`."""
    cfg = mkcfg(None, pairs=[raw])
    pair = cfg.pairs[0]
    if carpeta:
        pair.local_abs.mkdir(parents=True, exist_ok=True)
        if llenar:
            (pair.local_abs / "nota.md").write_text("x\n", encoding="utf-8")
    if baseline and pair.is_bisync:
        listados(pair)
    log = model.LOG_DIR / f"{pair.name}_20261015_093535.log"
    log.write_text(texto, encoding="utf-8")
    results.apuntar(pair.name, rc, log)
    h = next((x for x in revision.revisar(cfg) if x.clave == "freno"), None)
    return cfg, pair, h


def texto_del(plan):
    """Devuelve todo lo que el plan le dice a la persona, junto."""
    return " ".join([plan.titulo, *plan.consequences, *plan.warnings])


def imposible(cfg, h):
    """Devuelve el mensaje con el que `aviso_forzar` se niega, o `None` si hace el plan."""
    try:
        repair.aviso_forzar(cfg, h)
    except repair.ReparacionImposible as e:
        return str(e)
    return None


# ---- Qué botones tiene cada avería --------------------------------------------------------

with sandbox():
    _, _, borrados = con_freno(BISYNC, BISYNC_BORRADOS)
    _, _, cambiados = con_freno(BISYNC, BISYNC_CAMBIADOS)
with sandbox():
    _, _, espejo = con_freno(SUBIDA, ESPEJO_UP, rc=7)
    fallo = None
    cfg = mkcfg(None, pairs=[COPIA])
    (model.LOG_DIR / "copia_x.log").write_text("fallo cualquiera\n", encoding="utf-8")
    results.apuntar("copia", 1, model.LOG_DIR / "copia_x.log")
    fallo = next(h for h in revision.revisar(cfg) if h.clave == "fallo")

c("forzar se ofrece en un freno de bisync por borrados, en el de 'todos cambiaron' y en el de un espejo",
  [repair.puede_forzar(h) for h in (borrados, cambiados, espejo)], [True, True, True])
c("  y en un fallo cualquiera, no", repair.puede_forzar(fallo), False)
c("ver qué se borraría se ofrece donde hay borrados, y no donde lo que pasa es otra cosa",
  [repair.puede_simular_forzado(h) for h in (borrados, cambiados, espejo, fallo)],
  [True, False, True, False])

# La pareja del llavero la pone el código y su freno no se salta desde aquí. Hoy sus fallos
# ni siquiera llegan a «Reparación» (`Config.names` no la lleva), así que el hallazgo se
# construye a mano: lo que se prueba es la puerta, que se cierra aunque algún día llegue.
llave = model.parse_config({"defaults": {"remote": "nas"}, "pair": [BISYNC],
                            "keychain": {"base": "personal.kdbx", "fichero_llave": True,
                                         "nombre_llave": "personal.keyx"}})
del_llavero = revision.Hallazgo("freno", "El llavero: el freno", "d", model.LLAVERO,
                                revision.AVISO, (None, frenos.Freno(frenos.BORRADOS)))
c("el freno del llavero no se ofrece forzar",
  (repair.puede_forzar(del_llavero), repair.puede_simular_forzado(del_llavero)), (False, False))
c("  y aviso_forzar se niega aunque se le pida, diciendo qué hacer",
  "Combinar" in (imposible(llave, del_llavero) or ""), True)
with sandbox():
    log = model.LOG_DIR / "keychain_x.log"
    log.write_text(BISYNC_BORRADOS, encoding="utf-8")
    results.apuntar(model.LLAVERO, 1, log)
    c("el llavero sigue sin hallazgo de freno: se resuelve solo (`repetir_sin_freno`) o en «Combinar»",
      [h.clave for h in revision.revisar(llave)
       if h.pareja == model.LLAVERO and h.clave in ("freno", "fallo")], [])

# ---- Los argumentos: lo que se lanza ------------------------------------------------------

c("forzar lanza sync.py sobre ESA pareja, con --force",
  repair.args_forzar(borrados), ["notas", "--force"])
c("  la simulación, el mismo argumento más --dry-run",
  repair.args_forzar(borrados, simular=True), ["notas", "--force", "--dry-run"])
c("  sin --yes ni --resync: forzar no aprueba ni rehace nada más",
  {a for h in (borrados, espejo) for s in (False, True)
   for a in repair.args_forzar(h, simular=s)} & {"--yes", "-y", "--resync"}, set())

# ---- El plan: lo que se lee antes de decir que sí ---------------------------------------

with sandbox():
    cfg, pair, h = con_freno(BISYNC, BISYNC_BORRADOS)
    antes = sorted(p.relative_to(model.DEVICE_ROOT).as_posix()
                   for p in model.DEVICE_ROOT.rglob("*"))
    plan = repair.aviso_forzar(cfg, h)
    c("el plan lo hace sin tocar el dispositivo y no tiene nada que ejecutar",
      (sorted(p.relative_to(model.DEVICE_ROOT).as_posix() for p in model.DEVICE_ROOT.rglob("*"))
       == antes, plan.execute()), (True, []))
    todo, consecuencias, avisos = texto_del(plan), " ".join(plan.consequences), " ".join(
        plan.warnings)
    c.contains("bisync: el título nombra la pareja", plan.titulo, "«notas»")
    c.contains("  dice que es UNA pasada", consecuencias, "UNA pasada")
    c.contains("  y que el borrado se copiará al otro lado, con la cifra", consecuencias,
               "8 ficheros que faltan en el dispositivo se borrarán también en el remoto")
    c.contains("  que sólo vale para esta pasada y la siguiente vuelve a frenar, en %",
               consecuencias, "la siguiente vuelve a llevar el freno (25 %)")
    c.contains("  que si el lado vacío está desmontado o es el equivocado se pierden datos",
               avisos, "desmontado")
    c.contains("  recomienda la simulación, con el nombre del botón", avisos,
               repair.ETIQUETA_SIMULAR)
    c.contains("  recuerda la salida menos peligrosa de revisar ese lado", avisos,
               "revisa primero el dispositivo")
    c.contains("  y la de bisync: un --resync, que junta y no borra", avisos, "--resync")
    c.contains("  sin versiones, dice que lo borrado no vuelve", avisos, "no guarda versiones")
    c("  sin mezclar unidades: nada de cuentas de ficheros", "cuenta de" in todo, False)
    c("  ni --max-delete", "--max-delete" in todo, False)
    c("  la carpeta local tiene algo: no avisa de que esté vacía", "vacía" in avisos, False)

with sandbox():
    cfg, pair, h = con_freno(CON_VERSIONES, BISYNC_BORRADOS)
    avisos = " ".join(repair.aviso_forzar(cfg, h).warnings)
    c.contains("con versiones, dice dónde queda lo que se borre", avisos, ".prversions")
    c("  y no dice que no se guarde", "no guarda versiones" in avisos, False)

with sandbox():
    cfg, pair, h = con_freno(BISYNC, BISYNC_BORRADOS, llenar=False)
    c.contains("con la carpeta local vacía, avisa de que parece desmontada",
               " ".join(repair.aviso_forzar(cfg, h).warnings), "vacía")

with sandbox():
    cfg, pair, h = con_freno(BISYNC, BISYNC_BORRADOS.replace('on Path1 "', 'on Path2 "'))
    plan = repair.aviso_forzar(cfg, h)
    c.contains("un borrado en el remoto se copiaría al dispositivo",
               " ".join(plan.consequences),
               "8 ficheros que faltan en el remoto se borrarán también en el dispositivo")
    c.contains("  y el aviso es del remoto", " ".join(plan.warnings), "revisa primero el remoto")

with sandbox():
    cfg, pair, h = con_freno(SUBIDA, ESPEJO_UP, rc=7)
    plan = repair.aviso_forzar(cfg, h)
    consecuencias, avisos = " ".join(plan.consequences), " ".join(plan.warnings)
    c.contains("espejo: dice que se quita el tope en esta pasada", consecuencias,
               "sin tope de borrados")
    c.contains("  cuántos faltan, en el remoto", consecuencias,
               "al menos 5 ficheros por borrar en el remoto")
    c.contains("  y que la siguiente vuelve a su tope, una cuenta de ficheros",
               consecuencias, "su tope de 50 ficheros")
    c.contains("  que si el origen está mal, el destino se vacía", avisos, "vaciará")
    c.contains("  y que lo borrado no se guarda", avisos, "no se guarda")
    c.contains("  recomienda la simulación", avisos, repair.ETIQUETA_SIMULAR)
    c.contains("  y la salida menos peligrosa: arreglar el origen", avisos, "arregla el origen")
    c("  sin una sola unidad de porcentaje, ni --resync",
      ("%" in consecuencias + avisos, "--resync" in avisos), (False, False))

with sandbox():
    cfg, pair, h = con_freno(BAJADA, ESPEJO_DOWN, rc=7)
    c.contains("hacia el dispositivo, el destino es el dispositivo",
               " ".join(repair.aviso_forzar(cfg, h).consequences),
               "ficheros por borrar en el dispositivo")

with sandbox():
    cfg, pair, h = con_freno(BISYNC, BISYNC_CAMBIADOS)
    plan = repair.aviso_forzar(cfg, h)
    c.contains("todos cambiados: dice que se copiará todo al otro lado",
               " ".join(plan.consequences), "copiará")
    c("  y no aconseja una simulación de borrados que no aplica",
      repair.ETIQUETA_SIMULAR in " ".join(plan.warnings), False)

# ---- Cuándo se niega -----------------------------------------------------------------------

with sandbox():
    cfg, pair, h = con_freno(BISYNC, BISYNC_BORRADOS, carpeta=False)
    dicho = imposible(cfg, h)
    c("sin carpeta local no se ofrece forzar: se leería como «se ha borrado todo»",
      dicho is not None and "carpeta local" in dicho, True)
with sandbox():
    cfg, pair, h = con_freno(SUBIDA, ESPEJO_UP, rc=7, carpeta=False)
    c("  tampoco en un espejo", imposible(cfg, h) is not None, True)
with sandbox():
    cfg, pair, h = con_freno(BISYNC, BISYNC_BORRADOS, baseline=False)
    c("sin baseline, forzar no tiene sentido: lo que hace falta es un --resync",
      "--resync" in (imposible(cfg, h) or ""), True)
with sandbox():
    cfg, pair, h = con_freno(BISYNC, BISYNC_BORRADOS)
    otra = mkcfg(["otra"])
    c("si la pareja ya no está en la configuración, lo dice",
      "ya no está" in (imposible(otra, h) or ""), True)
    c("un hallazgo que no es de un freno no se fuerza",
      imposible(cfg, fallo) is not None, True)
    sin_cifras = revision.Hallazgo("freno", "t", "d", "notas", revision.AVISO, (None,))
    c("  ni uno al que le falta el freno que lo explica", imposible(cfg, sin_cifras) is not None,
      True)

# ---- Es una pasada, no un plan de disco ------------------------------------------------------

with sandbox():
    cfg, pair, h = con_freno(BISYNC, BISYNC_BORRADOS)
    c("forzar no está entre los planes que tocan el disco (los de PLANES se ejecutan aquí)",
      ("freno" in repair.PLANES, repair.tiene_plan(h)), (False, False))
    c("  pero sí es algo reparable, con su botón", h in repair.hallazgos_reparables([h]), True)
    try:
        repair.plan_para(cfg, h)
        dicho = "no se negó"
    except repair.ReparacionImposible:
        dicho = "se negó"
    c("  y plan_para no lo fabrica", dicho, "se negó")

sys.exit(c.report())
