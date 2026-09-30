#!/usr/bin/env python3
"""
El buzón de una raíz (`state/servicio.pide`, fase 5): lo que la ventana de esa
raíz le pide al agente que la atiende.

  * «Iniciar servicio» con el agente ya no arranca un servicio: guarda las
    parejas y el intervalo, como siempre, y deja un `reanudar`. El agente
    vuelve en cuanto se va la ventana, sin la `GRACIA`, y empieza con una
    pasada, como el servicio que se arrancaba.
  * Lo que llega por el buzón de una raíz es de ESA raíz, traiga el id que
    traiga, y solo lo que es de una raíz: un ajuste del equipo ahí se ignora.
  * El buzón de una unidad que no está en la lista ni se toca.
  * «Bloquear» de la ventana va por ese buzón.
  * Sin agente vivo, o con el agente en otro modo, «Iniciar servicio» arranca
    el servicio de siempre.
"""

import os
import sys

from _harness import Checks, mkcfg, sandbox

import _agente_falso as F
import agente
from common import equipo, model, store
from ui import cifrado, prefs, watch

c = Checks("el buzón de una raíz: la ventana le habla al agente")
F.preparar()

UID = "b" * 32
RAIZ = F.unidad(UID, nombre="PRDRIVE-3", daemon='[daemon]\ninterval_minutes = 10\n')
BUZON = RAIZ / ".prdrive" / "state" / equipo.BUZON_SERVICIO
equipo.guardar_ajustes(equipo.Ajustes().con_unidad(equipo.Unidad(UID, equipo.DAEMON)))
F.RAICES[:] = [RAIZ]

ag = F.nuevo()
F.vueltas(ag, 2)
primera = F.pasadas(RAIZ)
c("conectada y atendida: una pasada", len(primera), 1)
F.acabar(primera[0], 0, "OK\n")
F.vueltas(ag, 1)
F.acabar(F.pasadas(RAIZ)[-1], 0, "OK\n")
F.vueltas(ag, 1)
lanzadas = len(F.pasadas(RAIZ))
c("  las dos parejas, y a esperar el intervalo", lanzadas, 2)

# --- la ventana se abre: pausa ---------------------------------------------------------
F.stop(RAIZ).touch()
F.ventana_abierta(RAIZ)
F.vueltas(ag, 2)
c("con la ventana abierta, en pausa", F.lock(RAIZ), {})

# «Iniciar servicio»: el reanudar llega con la ventana todavía abierta.
equipo.pedir({"pide": equipo.PIDE_REANUDAR, "id": "otra-cosa"}, BUZON)
F.vueltas(ag, 1)
c("el buzón se recoge", BUZON.exists(), False)
c("  con la ventana todavía abierta, sigue en pausa", F.lock(RAIZ), {})
(RAIZ / ".prdrive" / "state" / "ui.lock.json").unlink()
F.vueltas(ag, 1)
c("  al irse la ventana vuelve YA, sin esperar la GRACIA",
  F.lock(RAIZ).get("pid"), os.getpid())
c("  y empieza con una pasada, como el servicio que se arrancaba",
  len(F.pasadas(RAIZ)), lanzadas + 1)
F.acabar(F.pasadas(RAIZ)[-1], 0, "OK\n")
F.vueltas(ag, 1)
F.acabar(F.pasadas(RAIZ)[-1], 0, "OK\n")
F.vueltas(ag, 1)

# Sin reanudar, la GRACIA de siempre.
F.stop(RAIZ).touch()
F.ventana_abierta(RAIZ)
F.vueltas(ag, 2)
(RAIZ / ".prdrive" / "state" / "ui.lock.json").unlink()
F.vueltas(ag, 1)
c("sin reanudar, al irse la ventana se espera la GRACIA", F.lock(RAIZ), {})
F.pasar(agente.GRACIA)
F.vueltas(ag, 1)
c("  y después vuelve", F.lock(RAIZ).get("pid"), os.getpid())

# --- lo que no es de una raíz ---------------------------------------------------------
antes = equipo.leer_ajustes().espera_unidad_nueva
equipo.pedir({"pide": equipo.PIDE_AJUSTE, "clave": "espera_unidad_nueva",
              "valor": 30}, BUZON)
F.vueltas(ag, 1)
c("un ajuste del equipo por el buzón de una raíz se ignora",
  equipo.leer_ajustes().espera_unidad_nueva, antes)
c("  y se dice", any("no es cosa de una raíz" in d for d in F.DIARIO), True)

# «Sincronizar ahora» por el buzón de la raíz, con otro id: es de esta.
equipo.pedir({"pide": equipo.PIDE_PASADA, "id": "z" * 32, "parejas": ["fotos"]}, BUZON)
F.vueltas(ag, 1)
c("una pasada pedida por el buzón de la raíz es de esa raíz",
  ag.pasada is not None and (ag.pasada.tarea.raiz, ag.pasada.tarea.pareja),
  (UID, "fotos"))
F.acabar(F.pasadas(RAIZ)[-1], 0, "OK\n")
F.vueltas(ag, 1)

# --- una unidad que no está en la lista: su buzón ni se mira --------------------------
AJENA = "c" * 32
RAIZ_AJENA = F.unidad(AJENA, nombre="AJENA")
F.RAICES[:] = [RAIZ, RAIZ_AJENA]
F.PANTALLA[0] = False                   # «Ahora no» al momento
buzon_ajeno = RAIZ_AJENA / ".prdrive" / "state" / equipo.BUZON_SERVICIO
equipo.pedir({"pide": equipo.PIDE_REANUDAR}, buzon_ajeno)
F.vueltas(ag, 3)
c("la unidad que no está en la lista está conectada", AJENA in ag.conexiones, True)
c("  y su buzón sigue ahí, sin tocar", buzon_ajeno.exists(), True)
c("  ni se ha lanzado nada suyo", F.pasadas(RAIZ_AJENA), [])
F.RAICES[:] = [RAIZ]
F.vueltas(ag, 1)

# --- la ventana: «Iniciar servicio» y «Bloquear» -----------------------------------------
import runsync  # noqa: E402

with sandbox():
    guardado: list = []
    prefs.save_prefs = lambda accion, parejas, minutos, todas: guardado.append(
        (accion, parejas, minutos))
    lanzados: list = []
    runsync.spawn_daemon = lambda pairs, mins: lanzados.append((pairs, mins)) or "ok"
    reanudar: list = []
    runsync.pedir_reanudar = lambda: reanudar.append(1) or True

    class Frontal:
        dicho: list = []

        def info(self, msg):
            self.dicho.append(msg)

    config = mkcfg(["docs", "fotos"])
    eleccion = __import__("ui").Choice("daemon", tuple(config.names[:1]), 7.0)
    runsync.ui.start = lambda cfg, msg: (eleccion, Frontal())

    watch.resumen = lambda: watch.Resumen("agente", "daemon", True, False)
    runsync._atender(config, None)
    c("«Iniciar servicio» con el agente vivo en daemon: reanudar, no un servicio",
      (reanudar, lanzados), ([1], []))
    c("  guarda las parejas y el intervalo, como siempre", guardado,
      [("daemon", ["docs"], 7.0)])
    c("  y lo dice", "El agente de este equipo vuelve" in Frontal.dicho[-1], True)

    for res, por in ((watch.Resumen("agente", "daemon", False, False), "sin agente vivo"),
                     (watch.Resumen("agente", "sync", True, False), "en modo sync"),
                     (watch.Resumen("agente", "ui", True, False), "en modo ui"),
                     (watch.Resumen("agente_nueva", "", True, False), "sin estar en la lista")):
        watch.resumen = (lambda r: lambda: r)(res)
        reanudar.clear()
        lanzados.clear()
        runsync._atender(config, None)
        c(f"  {por}: el servicio de siempre", (reanudar, len(lanzados)), ([], 1))

    # La orden de verdad escribe en el buzón de ESTA raíz.
    del runsync.pedir_reanudar
    import importlib
    importlib.reload(runsync)
    c("pedir_reanudar() deja «reanudar» en state/servicio.pide", runsync.pedir_reanudar(),
      True)
    c("  ahí", [p["pide"] for p in equipo.recoger(model.STATE_DIR / equipo.BUZON_SERVICIO)],
      [equipo.PIDE_REANUDAR])

    # «Bloquear»: con agente vivo, al buzón de la raíz.
    store.write_json(equipo.lock_json(), {"pid": os.getpid(), "host": equipo.HOST})
    c("«Bloquear» de la ventana, con agente vivo", cifrado.pedir_bloqueo("u" * 32), True)
    c("  va al buzón de la raíz, no al del agente",
      ([p["pide"] for p in equipo.recoger(model.STATE_DIR / equipo.BUZON_SERVICIO)],
       equipo.recoger()), ([equipo.PIDE_BLOQUEAR], []))
    equipo.lock_json().unlink()

sys.exit(c.report())
