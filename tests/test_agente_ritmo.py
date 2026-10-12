#!/usr/bin/env python3
"""El agente pasa menos una pareja que lleva un rato sin nada que hacer.

Lo que dice el parte de `sync.py` (`common/parte.py`) llega al planificador: el
intervalo se estira, se dice en los diarios y en el estado, y vuelve al de
fábrica cuando algo cambia, cuando se pide a mano, cuando el agente retoma la
raíz y con el ajuste `estirar_intervalo` apagado. Una pareja que se salta no se
relanza en cada intervalo.
"""

from _harness import Checks

import _agente_falso as F
import agente
from common import equipo, parte
from common import planificador as pl

c = Checks("agente: el intervalo que se estira")

F.preparar()
UID = "ritmo-0001"
MIN = 60.0
raiz = F.unidad(UID, parejas=("docs",),
                daemon='[daemon]\npairs = ["docs"]\ninterval_minutes = 5\n')
equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(
    equipo.Unidad(UID, equipo.DAEMON, "U", codigo=agente.huella(raiz) or "")))
F.RAICES[:] = [raiz]
ag = F.nuevo()
F.vueltas(ag, 3)

VACIA = "[docs] OK.\n" + parte.linea(parte.Parte("docs", 0, False, 1, 100)) + "\n"
MOVIO = "[docs] OK.\n" + parte.linea(parte.Parte("docs", 0, True, 1, 100)) + "\n"
SALTADA = ("[docs] Saltada: requiere --resync y no está aprobado.\n"
           + parte.linea(parte.Parte("docs", -1)) + "\n")


def una(salida: str, rc: int = 0) -> None:
    """Acaba la pasada en marcha con esa salida."""
    F.acabar(ag.pasada.proc, rc, salida)
    F.vueltas(ag, 1)


def hasta_la_siguiente(tope: float = 2 * 3600.0) -> float:
    """Avanza el reloj hasta que el agente lanza otra pasada; devuelve los segundos que tardó."""
    desde = F.reloj()
    while ag.pasada is None and F.reloj() - desde < tope:
        F.vueltas(ag, 1)
    return F.reloj() - desde


def marca() -> pl.Marca:
    return ag.marcas.get((UID, "docs"), pl.Marca())


def minutos(segundos: float) -> int:
    return round(segundos / MIN)


c("(la unidad se atiende y sale su primera pasada)", ag.pasada is not None, True)
una(VACIA)
c("una pasada sin nada que hacer se apunta", marca().vacias, 1)
c("  y la siguiente sale a su intervalo", minutos(hasta_la_siguiente()), 5)
una(VACIA)
hasta_la_siguiente()
F.DIARIO.clear()
una(VACIA)
c("a la tercera vacía, el intervalo se dobla", (marca().vacias, minutos(hasta_la_siguiente())),
  (3, 10))
c("  y se dice en el diario, una vez",
  [d for d in F.DIARIO if "sin nada que hacer" in d],
  ["[U] docs: lleva 3 pasadas sin nada que hacer; ahora cada 10 min (hasta que algo cambie)"])
c("  y en el estado: la bandeja y `status` lo enseñan",
  next(u for u in ag.resumen()["unidades"] if u["id"] == UID)["estiradas"], {"docs": 10.0})
F.DIARIO.clear()
una(VACIA)
c("  la cuarta no lo vuelve a decir", [d for d in F.DIARIO if "sin nada que hacer" in d], [])
hasta_la_siguiente()
una(VACIA)
hasta_la_siguiente()
una(VACIA)
c("a la sexta, cuatro veces el intervalo, y de ahí no pasa",
  (marca().vacias, minutos(hasta_la_siguiente())), (6, 20))
for _ in range(4):
    una(VACIA)
    tardo = hasta_la_siguiente()
c("  ni con diez", (marca().vacias, minutos(tardo)), (10, 20))

F.DIARIO.clear()
una(MOVIO)
c("una pasada que mueve algo lo devuelve al de fábrica",
  (marca().vacias, minutos(hasta_la_siguiente())), (0, 5))
c("  y se dice", [d for d in F.DIARIO if "vuelve a sincronizarse" in d],
  ["[U] docs: vuelve a sincronizarse cada 5 min"])
c("  y el estado ya no la cuenta",
  next(u for u in ag.resumen()["unidades"] if u["id"] == UID)["estiradas"], {})

# Un `sync.py` de antes no dice si movió algo: nunca se estira.
for _ in range(5):
    una("[docs] OK.\n\nHecho. 1/1 parejas OK.\n")
    tardo = hasta_la_siguiente()
c("sin parte (un sync.py de antes) no se estira nunca", (marca().vacias, minutos(tardo)), (0, 5))

# «Sincronizar ahora» sobre una pareja estirada.
for _ in range(3):
    una(VACIA)
    hasta_la_siguiente()
una(VACIA)
c("(estirada otra vez)", marca().vacias >= 3, True)
equipo.pedir({"pide": equipo.PIDE_PASADA, "id": UID, "parejas": ["docs"]})
F.vueltas(ag, 2)
c("«Sincronizar ahora» no espera al intervalo estirado",
  (ag.pasada is not None, ag.pasada is not None and ag.pasada.tarea.urgente), (True, True))
una(VACIA)
c("  y aunque no mueva nada, la devuelve al de fábrica",
  (marca().vacias, minutos(hasta_la_siguiente())), (0, 5))

# El agente retoma la raíz (su ventana se abrió y se cerró).
for _ in range(3):
    una(VACIA)
    hasta_la_siguiente()
una(VACIA)
c("(estirada otra vez)", marca().vacias >= 3, True)
con = ag.conexiones[UID]
ag._soltar(con)
ag._tomar(con)
c("al retomar la raíz, sus parejas vuelven al intervalo de fábrica", marca().vacias, 0)

# El ajuste.
hasta_la_siguiente()
for _ in range(3):
    una(VACIA)
    hasta_la_siguiente()
c("(estirada otra vez)", marca().vacias >= 3, True)
equipo.pedir({"pide": equipo.PIDE_AJUSTE, "clave": "estirar_intervalo", "valor": False})
una(VACIA)
c("con `estirar_intervalo` apagado va a su intervalo, lleve las vacías que lleve",
  (ag.ajustes.politica.estirar, minutos(hasta_la_siguiente())), (False, 5))
c("  y queda guardado en agente.json", equipo.leer_ajustes().estirar_intervalo, False)
c("  la orden lo valida como un sí o un no",
  (agente.valor_ajuste("estirar_intervalo", "no"), agente.valor_ajuste("estirar_intervalo", "Sí")),
  (False, True))
equipo.pedir({"pide": equipo.PIDE_AJUSTE, "clave": "estirar_intervalo", "valor": True})
una(MOVIO)

# Una pareja que se salta.
hasta_la_siguiente()
una(SALTADA)
c("una pareja saltada queda apuntada", marca().saltada, True)
c("  y no se relanza a su intervalo, sino pasada una hora",
  minutos(hasta_la_siguiente()), minutos(pl.Politica().espera_saltada))
una(SALTADA)
ag._soltar(con)
ag._tomar(con)
c("  salvo que el agente retome la raíz (se aprobó el --resync en su ventana)",
  (marca().saltada, minutos(hasta_la_siguiente()) <= 5), (False, True))
una(MOVIO)
c("  una pasada buena la saca", marca().saltada, False)

raise SystemExit(c.report())
