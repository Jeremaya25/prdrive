#!/usr/bin/env python3
"""
El agente residente con la raíz de ESTE equipo (fase 2).

La raíz del equipo es una raíz más de su lista, con `ruta`: se busca ahí y no
recorriendo volúmenes, y lo demás es el mismo contrato que con una unidad
(`test_agente_contrato.py`). Se comprueba lo que cambia:

  * se atiende sin preguntar (está en la lista), con su ruta como raíz extra;
  * si la carpeta no está, se avisa UNA vez y no se lanza nada; al volver, se
    dice y se sigue;
  * `añadir_raiz` por el buzón la mete en la lista (es el asistente vuelto a
    pasar con el agente instalado);
  * los avisos de fallo mandan a la ventana del equipo, no «desde la unidad»;
  * `agente.py abrir` lanza el `runsync.py` de la raíz con el Python del agente.
"""

import os
import shutil
import sys
from pathlib import Path

from _harness import Checks

import _agente_falso as F
import agente
import penwatch
from common import equipo, store
from ui import bandeja

c = Checks("agente: la raíz de este equipo")

F.preparar()
# El recorrido de verdad mira también las raíces extra: la de mentira, igual.
penwatch.candidate_roots = lambda cfg: ([Path(r) for r in cfg.get("extra_roots", [])]
                                        + list(F.RAICES))

UID = "e" * 32
RAIZ = F.unidad(UID, parejas=("notas",), nombre="Mi portátil")
(RAIZ / penwatch.APP_SUBDIR / "PRDRIVE").write_text(f"id={UID}\ntipo=equipo\n",
                                                    encoding="utf-8")
equipo.guardar_ajustes(equipo.Ajustes().con_unidad(
    equipo.Unidad(UID, equipo.DAEMON, "Mi portátil", str(RAIZ))))

ag = F.nuevo()
F.vueltas(ag, 3)
c("la raíz del equipo se encuentra por su ruta, sin recorrer volúmenes",
  UID in ag.conexiones, True)
c("  sin preguntar: está en la lista", [a for a in F.AVISOS if "Se ha conectado" in a[0]],
  [])
c("  y se hace su servicio: lock del agente", F.lock(RAIZ).get("agente"), True)
c("  con una pasada de su sync.py", len(F.pasadas(RAIZ)), 1)
c("  el diario dice que es la raíz del equipo",
  any("raíz de este equipo" in d for d in F.DIARIO), True)
c("  y el estado lo marca", ag.resumen()["unidades"][0]["del_equipo"], True)

# Un fallo manda a la ventana del equipo.
F.acabar(F.pasadas(RAIZ)[0], rc=1, salida="ERROR : algo raro\n")
F.vueltas(ag, 1)
c("un fallo avisa sin decir «desde la unidad»",
  [x for t, x in F.AVISOS if "falla notas" in t],
  ["Abre la ventana de prdrive en este equipo para ver qué ha pasado."])

# La carpeta desaparece: se avisa una vez y no se lanza nada.
aparte = RAIZ.with_name(RAIZ.name + "-movida")
shutil.move(str(RAIZ), str(aparte))
F.AVISOS.clear()
F.pasar(3600)
F.vueltas(ag, 5)
c("sin su carpeta, deja de atenderla", UID in ag.conexiones, False)
c("  y avisa una sola vez, diciendo dónde tenía que estar",
  [(t, str(RAIZ) in x) for t, x in F.AVISOS], [("Mi portátil: no encuentro su carpeta",
                                                 True)])
c("  el estado lo cuenta", ag.resumen()["ausentes"], [str(RAIZ)])
antes = len(F.pasadas())
F.pasar(3600)
F.vueltas(ag, 5)
c("  sin lanzar nada mientras falta", len(F.pasadas()), antes)
shutil.move(str(aparte), str(RAIZ))
F.vueltas(ag, 3)
c("al volver, se atiende otra vez", UID in ag.conexiones, True)
c("  y lo dice en el diario", any("vuelve a estar" in d for d in F.DIARIO), True)
c("  sin volver a avisar", len(F.AVISOS), 1)

# añadir_raiz por el buzón
OTRA = "f" * 32
equipo.pedir({"pide": equipo.PIDE_RAIZ, "id": OTRA, "ruta": "/home/x/PRDRIVE",
              "nombre": "Otra"})
equipo.pedir({"pide": equipo.PIDE_RAIZ, "id": "", "ruta": "/x"})
F.vueltas(ag, 1)
aj = equipo.leer_ajustes()
c("añadir_raiz la escribe el agente, en modo daemon y con su ruta",
  aj.unidades[OTRA], equipo.Unidad(OTRA, equipo.DAEMON, "Otra", "/home/x/PRDRIVE"))
c("  una sin id no entra", len(aj.unidades), 2)

# agente.py abrir
equipo.guardar_ajustes(equipo.Ajustes().con_unidad(
    equipo.Unidad(UID, equipo.DAEMON, "Mi portátil", str(RAIZ))))
store.write_json(equipo.lock_json(), {"pid": os.getpid(), "host": equipo.HOST})
F.LANZADOS.clear()
c("abrir sin id: la única raíz del equipo", agente.main(["abrir"]), 0)
c("  lanza su runsync.py con el Python del agente, fuera de la raíz",
  [(p.args[0], p.args[1], p.kwargs.get("cwd")) for p in F.LANZADOS],
  [(agente.python(ventana=True), str(RAIZ / ".prdrive" / "runsync.py"),
    str(equipo.DIR))])
F.ventana_abierta(RAIZ)
F.LANZADOS.clear()
c("  con su ventana ya abierta no lanza otra",
  (agente.main(["abrir", UID]), F.LANZADOS), (0, []))
(RAIZ / penwatch.UI_LOCK_REL).unlink()
equipo.lock_json().unlink()
F.LANZADOS.clear()
c("con el agente parado, abrir lo arranca y abre la ventana (el acceso del menú "
  "donde no hay bandeja)", (agente.main(["abrir"]), [p.args[1:] for p in F.LANZADOS]),
  (0, [[str(agente.SCRIPT_DIR / "agente.py"), "run"],
       [str(RAIZ / ".prdrive" / "runsync.py")]]))
c("  el agente, suelto y fuera de toda raíz",
  (F.LANZADOS[0].kwargs.get("cwd"), F.LANZADOS[0].kwargs.get("start_new_session")),
  (str(equipo.DIR), True))

equipo.guardar_ajustes(equipo.Ajustes())
F.LANZADOS.clear()
F.AVISOS.clear()
c("sin raíz en el equipo y el agente parado: abrir lo arranca",
  (agente.main(["abrir"]), [p.args[-1] for p in F.LANZADOS], [t for t, _ in F.AVISOS]),
  (0, ["run"], ["prdrive: agente arrancado"]))
store.write_json(equipo.lock_json(), {"pid": os.getpid(), "host": equipo.HOST})
store.write_json(equipo.estado_json(), {"unidades": [
    {"id": "u" * 32, "nombre": "Azul", "raiz": str(RAIZ), "atendida": True,
     "fallando": ["fotos"]}]})
F.LANZADOS.clear()
F.AVISOS.clear()
c("  y en marcha, dice con un aviso cómo va, como diría su icono",
  (agente.main(["abrir"]), F.LANZADOS, F.AVISOS),
  (0, [], [("prdrive: Azul: falla fotos", "Azul: falla fotos")]))
c("  un id que no conoce: lo dice y sale con 1", agente.main(["abrir", "z" * 32]), 1)
F.LANZADOS.clear()
c("  una unidad conectada se abre por su id (del estado del agente)",
  (agente.main(["abrir", "u" * 32]), len(F.LANZADOS)), (0, 1))
c("aviso_de_estado sin avisos: lo que atiende",
  bandeja.aviso_de_estado({"unidades": [{"nombre": "Azul", "atendida": True}]}),
  ("prdrive: al día", "Atiende: Azul."))
c("  en pausa, cómo seguir",
  bandeja.aviso_de_estado({"pausado": True})[1].splitlines()[-1],
  "Para que siga: python agente.py sigue")

sys.exit(c.report())
