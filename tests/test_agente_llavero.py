#!/usr/bin/env python3
"""El agente y el llavero de una raíz que atiende (fase 3 del llavero).

Con el reloj, los procesos y la foto de mentira de `_agente_falso.py`, y un
KeePassXC que está abierto o no según diga el test (`agente.keepassxc_abierto`).
Lo que se sujeta:
- El planificador: una pareja con su propio intervalo manda sobre el de su
  raíz, también para vigilarla, y en una raíz `sync` solo esa se recorre.
- Con KeePassXC abierto, el llavero se trae cada 5 min; cerrado, manda el
  intervalo de la raíz.
- Al abrirse y al cerrarse, una pasada del llavero enseguida; si ya hay una en
  marcha, el cambio espera a que acabe.
- En una raíz en modo `sync`, el llavero solo pasa mientras KeePassXC está
  abierto, y al abrirlo y cerrarlo.
- Se mira cada pocos segundos y solo en las raíces que sirve el agente y
  llevan llavero.
"""

import math
import sys
from pathlib import Path

from _harness import Checks

import _agente_falso as F
import agente
from common import equipo, llavero, model
from common import planificador as pl

c = Checks("agente: el llavero de una raíz")
F.preparar()

TICK = agente.TICK
CAMBIOS = pl.PoliticaCambios()
DAEMON = "[daemon]\ninterval_minutes = 600\n"
"""Un intervalo que nunca llega: lo que lance una pasada es el llavero."""
LLAVERO = '\n[keychain]\nbase = "personal.kdbx"\n'

# ---------------------------------------------------------------------------
# 1. El planificador: el intervalo de una pareja
# ---------------------------------------------------------------------------
corto = pl.Pareja("keychain", "nas", vigila=True, intervalo=300.0)
largo = pl.Pareja("docs", "nas", vigila=True)
raiz = pl.Raiz("r", (corto, largo), 3600.0)
c("una pareja con su intervalo manda sobre el de la raíz",
  (pl.intervalo_de(raiz, corto), pl.intervalo_de(raiz, largo)), (300.0, 3600.0))
marcas = {("r", "keychain"): pl.Marca(1000.0), ("r", "docs"): pl.Marca(1000.0)}
d = pl.decidir([raiz], marcas, pl.Entorno(), 1301.0)
c("  y le toca antes", (d.tarea.pareja if d.tarea else None), "keychain")
sync = pl.Raiz("s", (corto, largo), math.inf)
c("en una raíz sync solo se recorre la que trae su intervalo",
  pl.a_recorrer([sync], {}, 0.0), [("s", "keychain")])
c("  sin él, ninguna", pl.a_recorrer([pl.Raiz("s", (largo,), math.inf)], {}, 0.0), [])


# ---------------------------------------------------------------------------
# 2. Una raíz en modo daemon
# ---------------------------------------------------------------------------
ABIERTO = [False]
MIRADAS: list[Path] = []


def abierto(raiz) -> bool:
    """KeePassXC de mentira: abierto según `ABIERTO`, y apunta dónde se miró."""
    MIRADAS.append(Path(raiz))
    return ABIERTO[0]


agente.keepassxc_abierto = abierto
FIRMA = [1]
agente.huella_local = lambda ruta, tope, ignorar: pl.Huella(1, FIRMA[0])


def poner(uid: str, modo: str = equipo.DAEMON, con_llavero: bool = True) -> Path:
    """Una unidad con `docs` y, si se dice, llavero, en la lista con ese modo."""
    raiz = F.unidad(uid, parejas=("docs",), daemon=DAEMON)
    if con_llavero:
        config = raiz / ".prdrive" / "sync_config.toml"
        config.write_text(config.read_text(encoding="utf-8") + LLAVERO, encoding="utf-8")
    equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(equipo.Unidad(uid, modo)))
    return raiz


def del_llavero(raiz: Path) -> list:
    """Las pasadas del llavero lanzadas en esa raíz."""
    return [p for p in F.pasadas(raiz) if p.args[-1] == model.LLAVERO]


def terminar(ag, raiz: Path) -> None:
    """Termina bien las pasadas en marcha, y las que salgan detrás."""
    while ag.pasada is not None:
        F.acabar(F.pasadas(raiz)[-1], 0, "OK\n")
        F.vueltas(ag, 1)


def hasta(ag, raiz: Path, limite: float) -> float | None:
    """Da vueltas hasta que se lanza una pasada del llavero.

    Returns:
        Los segundos hasta el lanzamiento, o `None` si no se lanzó en `limite`.
    """
    n, desde = len(del_llavero(raiz)), F.reloj()
    for _ in range(int(limite / TICK)):
        F.vueltas(ag, 1)
        if len(del_llavero(raiz)) > n:
            return F.reloj() - TICK - desde
    return None


UID = "a" * 32
RAIZ = poner(UID)
F.RAICES[:] = [RAIZ]
ag = F.nuevo()
F.vueltas(ag, 2)
terminar(ag, RAIZ)
c("al conectarla, las dos pasadas de siempre, la del llavero la última",
  [p.args[-1] for p in F.pasadas(RAIZ)], ["docs", model.LLAVERO])
c("  el agente la sirve con el llavero entre sus parejas: el vigilante sobra",
  model.LLAVERO in F.lock(RAIZ).get("pairs", []), True)

MIRADAS.clear()
F.vueltas(ag, int(60 / TICK))
c("se mira si KeePassXC está abierto cada pocos segundos, no en cada vuelta",
  len(MIRADAS), int(60 / CAMBIOS.sondeo))
c("  en su raíz", set(MIRADAS), {RAIZ})
c("con KeePassXC cerrado, manda el intervalo de la raíz", hasta(ag, RAIZ, 400), None)

ABIERTO[0] = True
espera = hasta(ag, RAIZ, 30)
c("al abrirse KeePassXC, una pasada del llavero enseguida",
  espera is not None and espera <= CAMBIOS.sondeo + TICK, True)
c("  y el diario lo dice", any("KeePassXC abierto" in m for m in F.DIARIO), True)
terminar(ag, RAIZ)
fin = F.reloj()
espera = hasta(ag, RAIZ, 400)
c("abierto, lo de otro dispositivo se trae cada 5 min",
  espera is not None and abs(F.reloj() - TICK - fin - llavero.REMOTO_ABIERTO) <= 2 * TICK,
  True)
c("  y solo el llavero", [p.args[-1] for p in F.pasadas(RAIZ)][-1], model.LLAVERO)
terminar(ag, RAIZ)

ABIERTO[0] = False
espera = hasta(ag, RAIZ, 30)
c("al cerrarse, una pasada enseguida: sube lo que se guardó justo antes",
  espera is not None and espera <= CAMBIOS.sondeo + TICK, True)
c("  y el diario lo dice", any("KeePassXC cerrado" in m for m in F.DIARIO), True)
terminar(ag, RAIZ)
c("  después, otra vez el intervalo de la raíz", hasta(ag, RAIZ, 400), None)

# Con una pasada del llavero en marcha, el cambio espera a que acabe.
ag.marcas[(UID, model.LLAVERO)] = pl.Marca(None)
hasta(ag, RAIZ, 10)
c("(una pasada del llavero en marcha)", ag.pasada.tarea.pareja, model.LLAVERO)
ABIERTO[0] = True
F.vueltas(ag, int(20 / TICK))
c("abrirse durante una pasada del llavero no la cuenta todavía", UID in ag.keepassxc, False)
terminar(ag, RAIZ)
espera = hasta(ag, RAIZ, 30)
c("  acabada, se ve abierto y hay otra pasada: la de antes pudo empezar antes",
  (UID in ag.keepassxc, espera is not None), (True, True))
terminar(ag, RAIZ)

# Una raíz que el agente deja de servir no cuenta como «KeePassXC cerrado».
F.ventana_abierta(RAIZ)
dicho = len(F.DIARIO)
F.vueltas(ag, int(20 / TICK))
c("con su ventana abierta no se sirve, ni se mira KeePassXC",
  (UID in ag.keepassxc, any("KeePassXC cerrado" in m for m in F.DIARIO[dicho:])),
  (False, False))
(RAIZ / ".prdrive" / "state" / "ui.lock.json").unlink()
ABIERTO[0] = False

# ---------------------------------------------------------------------------
# 3. Una raíz en modo sync
# ---------------------------------------------------------------------------
F.RAICES[:] = []
F.vueltas(ag, 3)
UID_S = "b" * 32
SYNC = poner(UID_S, modo=equipo.SYNC)
F.RAICES[:] = [SYNC]
ag = F.nuevo()                           # lee la lista con la unidad nueva
F.vueltas(ag, 2)
terminar(ag, SYNC)
c("modo sync: una pasada por conexión, también del llavero",
  [p.args[-1] for p in F.pasadas(SYNC)], ["docs", model.LLAVERO])
c("  y con KeePassXC cerrado, nada más", hasta(ag, SYNC, 700), None)
c("  ni se recorre su carpeta", (UID_S, model.LLAVERO) in ag.vigiladas
  and ag.vigiladas[(UID_S, model.LLAVERO)].huella is not None, False)
ABIERTO[0] = True
c("al abrirse KeePassXC, el llavero pasa", hasta(ag, SYNC, 30) is not None, True)
terminar(ag, SYNC)
c("  y se trae cada 5 min mientras está abierto",
  hasta(ag, SYNC, llavero.REMOTO_ABIERTO + 20) is not None, True)
terminar(ag, SYNC)
F.vueltas(ag, 3)
FIRMA[0] += 1                            # un guardado en KeePassXC
espera = hasta(ag, SYNC, CAMBIOS.separacion + CAMBIOS.calma)
c("  y su carpeta se vigila: un guardado se sube, tras la calma",
  (espera is not None, ag.pasada is not None and ag.pasada.tarea.por_cambios), (True, True))
terminar(ag, SYNC)
c("  solo el llavero: docs no ha vuelto a pasar",
  [p.args[-1] for p in F.pasadas(SYNC)].count("docs"), 1)
ABIERTO[0] = False
c("al cerrarse, una última pasada", hasta(ag, SYNC, 30) is not None, True)
terminar(ag, SYNC)
c("  y vuelve a ser una por conexión", hasta(ag, SYNC, 700), None)

# ---------------------------------------------------------------------------
# 4. Sin llavero no se mira KeePassXC
# ---------------------------------------------------------------------------
F.RAICES[:] = []
F.vueltas(ag, 3)
UID_N = "c" * 32
SIN = poner(UID_N, con_llavero=False)
F.RAICES[:] = [SIN]
ag = F.nuevo()
F.vueltas(ag, 2)
terminar(ag, SIN)
MIRADAS.clear()
F.vueltas(ag, int(60 / TICK))
c("en una raíz sin llavero no se mira si KeePassXC está abierto", MIRADAS, [])
sys.exit(c.report())
