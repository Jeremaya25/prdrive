#!/usr/bin/env python3
"""El agente lleva la cuenta de lo que gasta en cada unidad (`common/consumo.py`).

Cada pasada que termina suma en la carpeta del equipo, con lo que cuenta el propio
`sync.py` en su parte (`common/parte.py`): si movió algo, cuántas veces lanzó
rclone y cuánto reescribió. `agente.py status` lo enseña.
"""

import contextlib
import io

from _harness import Checks

import _agente_falso as F
import agente
from common import consumo, equipo, parte

c = Checks("agente: la cuenta de lo gastado")

F.preparar()
agente.LOTE = 1                         # de una en una: aquí se cuenta cada pasada por separado
UID = "cuenta-0001"
raiz = F.unidad(UID, parejas=("docs", "fotos"),
                daemon='[daemon]\npairs = ["docs", "fotos"]\ninterval_minutes = 5\n')
equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(
    equipo.Unidad(UID, equipo.DAEMON, "U", codigo=agente.huella(raiz) or "")))
F.RAICES[:] = [raiz]
ag = F.nuevo()
F.vueltas(ag, 3)
c("la unidad se atiende y sale su primera pasada", len(F.pasadas(raiz)), 1)
c("sin pasadas acabadas no hay nada apuntado", consumo.del_dia(UID), consumo.Cuenta())


DURO = [0.0]
"""Lo que duró la última pasada acabada, según el reloj de mentira."""


def acabar(texto: str, rc: int = 0) -> str:
    """Termina la pasada en marcha con esa salida y devuelve su pareja."""
    pareja, desde = ag.pasada.tarea.pareja, ag.pasada.desde
    F.pasar(3.0)
    F.acabar(ag.pasada.proc, rc, texto.replace("PAREJA", pareja))
    DURO[0] = F.reloj() - desde
    F.vueltas(ag, 1)
    return pareja


primera = acabar("[PAREJA] OK.\n" + parte.linea(parte.Parte("PAREJA", 0, False, 1, 30000)) + "\n")
hoy = consumo.del_dia(UID)
c("una pasada sin nada que hacer: una pasada, vacía", (hoy.pasadas, hoy.vacias), (1, 1))
c("  dos procesos: sync.py y su rclone", hoy.procesos, 2)
c("  lo que reescribió en la unidad", hoy.escrito, 30000)
c("  y lo que duró", hoy.segundos, round(DURO[0], 1))

F.vueltas(ag, 2)
segunda = acabar("[PAREJA] OK.\n" + parte.linea(parte.Parte("PAREJA", 0, True, 2, 500)) + "\n")
hoy = consumo.del_dia(UID)
c("la otra pareja movió algo: dos pasadas, una vacía", (segunda != primera, hoy.pasadas, hoy.vacias),
  (True, 2, 1))
c("  con sus tres procesos más", hoy.procesos, 5)
c("  y se suma lo reescrito", hoy.escrito, 30500)

# Un `sync.py` de antes (el de una unidad sin actualizar) no escribe parte.
F.pasar(5 * 60)
F.vueltas(ag, 2)
acabar("[PAREJA] OK.\n\nHecho. 1/1 parejas OK.\n")
hoy = consumo.del_dia(UID)
c("sin parte la pasada cuenta, pero no como vacía", (hoy.pasadas, hoy.vacias), (3, 1))
c("  y se le suponen dos procesos", hoy.procesos, 7)

F.vueltas(ag, 2)
acabar("[PAREJA] Saltada: requiere --resync y no está aprobado.\n"
       + parte.linea(parte.Parte("PAREJA", -1)) + "\n")
hoy = consumo.del_dia(UID)
c("una saltada no lanza rclone: un proceso", (hoy.pasadas, hoy.procesos), (4, 8))

# `agente.py status`: lo de hoy, bajo la unidad conectada.
equipo.agente_vivo = lambda: {"pid": 1}
equipo.leer_estado = lambda: {"unidades": [{"id": UID, "nombre": "U", "raiz": str(raiz)}]}
agente.update.pending = lambda *a, **k: None
salida = io.StringIO()
with contextlib.redirect_stdout(salida):
    agente.cmd_status(None)
c("status dice lo gastado hoy en la unidad conectada",
  [linea.strip() for linea in salida.getvalue().splitlines() if "Hoy:" in linea],
  ["Hoy: " + consumo.texto(hoy)])

raise SystemExit(c.report())
