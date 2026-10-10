#!/usr/bin/env python3
"""El agente y una unidad de su lista bloqueada con BitLocker.

Con un sistema de mentira (`_agente_falso`): el nombre de volumen de cada raíz
(`bitlocker.volumen_de`), su estado de BitLocker (`cifrada.bitlocker_de`) y la
ventana de desbloqueo de Windows (`agente.desbloquear_bitlocker`) están
sustituidos. Una «letra bloqueada» es una carpeta vacía con el nombre de volumen
de la unidad y el estado `BDE_LOCKED`. Se comprueba:
- `agente.json` recuerda el volumen de una unidad (`Unidad.volumen`), y lo que
  no tiene su forma se descarta sin perder la unidad.
"""

import sys

from _harness import Checks

import _agente_falso as F
from common import equipo

c = Checks("el agente y una unidad bloqueada con BitLocker")
F.preparar()

A, B = "a" * 32, "b" * 32
V1 = "\\\\?\\volume{11111111-1111-1111-1111-111111111111}\\"
V2 = "\\\\?\\volume{22222222-2222-2222-2222-222222222222}\\"


# --- agente.json
def ida_y_vuelta(u: equipo.Unidad) -> equipo.Unidad:
    """Devuelve la unidad tras escribirla en el dict de `agente.json` y leerla."""
    return equipo.desde_dict(equipo.a_dict(equipo.Ajustes(unidades={u.id: u}))).unidades[u.id]


def cruda(volumen, **mas) -> equipo.Unidad:
    """Devuelve la unidad que sale de un `agente.json` con ese `volumen` tal cual."""
    return equipo.desde_dict({"unidades": {A: {"volumen": volumen, **mas}}}).unidades[A]


c("agente.json: el volumen va y vuelve", ida_y_vuelta(equipo.Unidad(A, volumen=V1)).volumen, V1)
c("  sin volumen no se escribe la clave",
  "volumen" in equipo.a_dict(equipo.Ajustes(unidades={A: equipo.Unidad(A)}))["unidades"][A],
  False)
c("  en mayúsculas se guarda en minúsculas", cruda(V1.upper()).volumen, V1)
c("  lo que no tiene esa forma, o no es texto, se descarta y la unidad sigue",
  [cruda(v).volumen for v in ("E:\\", "volume{x}", 7, None, V1 + "x")], [""] * 5)
c("  una raíz de este equipo no lo lleva", cruda(V1, ruta="/algo").volumen, "")
c("  un agente.json de antes se lee igual",
  equipo.desde_dict({"unidades": {A: {"modo": "daemon"}}}).unidades[A].volumen, "")

sys.exit(c.report())
