#!/usr/bin/env python3
"""El fantasma de una unidad extraíble cifrada, en el agente (#41).

Desenchufar sin expulsar deja la letra de dentro sirviendo el fichero de control
desde la caché. Al volver a enchufar, el id está a la vez entre las abiertas (esa
letra) y entre las cerradas (el vestíbulo de la raíz física). Con
`vestibulo.retenido` sustituido se comprueba:
- `.hc` libre: es el fantasma. No se atiende, ni se pasa nada, ni se pide abrir
  el contenedor; un solo aviso por conexión.
- `.hc` retenido: se atiende como hasta ahora.
- `retenido` da `None` (Linux, o sin `.hc` que mirar): sin cambios.
- Tras «Expulsar» (la letra se va) el aviso se rearma para la conexión siguiente.
- Las raíces del equipo siguen con `_fantasmas()` (`test_agente_veracrypt.py`).
"""

from pathlib import Path

from _harness import Checks, tmpdir

import _agente_falso as F
import agente
import penwatch
from common import equipo, vestibulo

c = Checks("agente: fantasma de una unidad extraíble cifrada")
F.preparar()

UID = "8" * 32
FIS = tmpdir("prdrive-fisica-")
(FIS / penwatch.VESTIBULE_MARKER).write_text(f"id={UID}\n", encoding="utf-8")
(FIS / penwatch.CONTAINER_FILE).write_bytes(b"")
DENTRO = F.unidad(UID, parejas=("docs",), nombre="Cifrada")

vistos: list[str] = []
respuesta = {"valor": False}


def retenido(contenedor):
    """Sustituye `vestibulo.retenido`: apunta qué se mira y contesta lo pedido."""
    vistos.append(str(contenedor))
    return respuesta["valor"]


original = vestibulo.retenido
vestibulo.retenido = retenido


def arrancar(valor):
    """Devuelve un agente que ve la letra de dentro y la raíz física, ya estable."""
    respuesta["valor"] = valor
    equipo.guardar_ajustes(equipo.Ajustes().con_unidad(
        equipo.Unidad(UID, equipo.DAEMON, "Cifrada")))
    F.ABIERTOS.clear()
    F.DIARIO.clear()
    F.AVISOS.clear()
    vistos.clear()
    F.RAICES[:] = [FIS, DENTRO]
    ag = F.nuevo()
    F.vueltas(ag, 5)
    return ag


try:
    ag = arrancar(False)
    c("`.hc` libre: no se atiende, no hay conexión ni pasada",
      (UID in ag.conexiones, F.lock(DENTRO).get("pid")), (False, None))
    c("  se mira el `.hc` de la raíz física", set(vistos),
      {str(FIS / penwatch.CONTAINER_FILE)})
    c("  un solo aviso, por muchas vueltas que pasen",
      len([a for a in F.AVISOS if "no responde" in a[0]]), 1)
    c("  y dice cómo salir", "Expulsar PRDRIVE" in F.AVISOS[0][1], True)
    c("  no se pide abrir el contenedor (dejaría dos letras con el mismo id)",
      F.ABIERTOS, [])

    F.RAICES[:] = [FIS]          # «Expulsar»: la letra de dentro se va
    F.vueltas(ag, 3)
    c("  tras expulsar, el fantasma se olvida", ag.fantasmas_extraibles, set())
    F.RAICES[:] = [FIS, DENTRO]
    F.vueltas(ag, 5)
    c("  otra conexión con fantasma avisa otra vez",
      len([a for a in F.AVISOS if "no responde" in a[0]]), 2)

    ag = arrancar(True)
    c("`.hc` retenido: se atiende como hasta ahora",
      (UID in ag.conexiones, F.lock(DENTRO).get("pid") is not None,
       len(F.AVISOS)), (True, True, 0))

    ag = arrancar(None)
    c("`retenido` da `None`: sin cambios, se atiende",
      (UID in ag.conexiones, len(F.AVISOS)), (True, 0))
finally:
    vestibulo.retenido = original

raise SystemExit(c.report())
