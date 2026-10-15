#!/usr/bin/env python3
"""Cómo se llama una unidad sin nombre propio, en la bandeja, los avisos y el diario.

Con el equipo de mentira de `_agente_falso` (la etiqueta del volumen la pone el
test). Se comprueba que:
- Dos unidades aprovisionadas desde el mismo ordenador, sin nombre propio, no
  se llaman como él: la etiqueta de su volumen si la tienen y, si no,
  «prdrive · <4 del id>». Lo ven la bandeja, el aviso y el diario.
- Lo que alguien puso no se toca, ni con otra de la misma etiqueta.
- Con la misma etiqueta las dos, la segunda lleva detrás el equipo que la
  aprovisionó; la primera no cambia.
- Una unidad que el agente recordaba con el nombre del ordenador deja de
  llamarse así al conectarse, y lo que recuerda se actualiza.
- Las que no se ven (la lista, un desbloqueo pendiente) usan el mismo nombre
  por defecto, sin etiqueta.
"""

from pathlib import Path

from _harness import Checks

import _agente_falso as F
import agente
from common import equipo, nombres
from ui import bandeja

c = Checks("nombre por defecto de las unidades del agente")
F.preparar()

PC = "DESKTOP-PERE"
A, B, N = "a" * 32, "b" * 32, "c" * 32


def lista(uid: str, raiz: Path, nombre: str = "") -> None:
    """Pone la unidad en la lista con la huella de su código de ahora."""
    equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(
        equipo.Unidad(uid, equipo.DAEMON, nombre, codigo=agente.huella(raiz) or "")))


def rotulos(ag) -> list[str]:
    """Los rótulos de los desplegables de la bandeja."""
    return [e.texto for e in bandeja.vista(ag.resumen()).menu if e.hijos]


def poner(*raices) -> "agente.Agente":
    """Un agente que ve esas raíces, ya con su conexión hecha."""
    F.RAICES[:] = list(raices)
    ag = F.nuevo()
    F.vueltas(ag, 3)
    return ag


# --- dos unidades del mismo ordenador, sin etiqueta: se distinguen por el id
RA = F.unidad(A, nombre=PC, equipos=(PC,))
RB = F.unidad(B, nombre=PC, equipos=(PC,))
lista(A, RA, PC)
lista(B, RB, PC)
ag = poner(RA, RB)
c("sin nombre propio ni etiqueta, no se llaman como el ordenador",
  sorted(con.nombre for con in ag.conexiones.values()), ["prdrive · aaaa", "prdrive · bbbb"])
c("  en la bandeja, cada una la suya",
  sorted(r for r in rotulos(ag) if r.startswith("prdrive")), ["prdrive · aaaa", "prdrive · bbbb"])
c("  y el agente recuerda el nuevo, no el del ordenador",
  sorted(u.nombre for u in equipo.leer_ajustes().unidades.values()),
  ["prdrive · aaaa", "prdrive · bbbb"])
c("  el diario habla de ella por él",
  any(linea.startswith("prdrive · aaaa: conectada") for linea in F.DIARIO), True)

# --- con etiqueta, la etiqueta
F.ETIQUETAS[RA], F.ETIQUETAS[RB] = "SANDISK", "KINGSTON"
ag = poner(RA, RB)
c("con etiqueta, la etiqueta", sorted(con.nombre for con in ag.conexiones.values()),
  ["KINGSTON", "SANDISK"])

# --- la misma etiqueta las dos: la segunda lleva el equipo; la primera, lo de siempre
F.ETIQUETAS[RA] = F.ETIQUETAS[RB] = "USB DISK"
equipo.guardar_ajustes(equipo.Ajustes())
F.RAICES[:] = [RA]
ag = F.nuevo()
F.vueltas(ag, 3)
F.RAICES[:] = [RA, RB]
F.vueltas(ag, 3)
c("la primera que llega, con su etiqueta", ag.conexiones[A].nombre, "USB DISK")
c("  la segunda, con el equipo detrás para que no se confundan",
  ag.conexiones[B].nombre, f"USB DISK ({PC})")
c("  y las dos se ven distintas en la bandeja",
  sorted(r.split(" (sin atender)")[0] for r in rotulos(ag) if "USB DISK" in r),
  ["USB DISK", f"USB DISK ({PC})"])

# --- lo que alguien puso, no se toca (ni choca con otra etiqueta igual)
F.ETIQUETAS[RA], F.ETIQUETAS[RB] = "USB DISK", "USB DISK"
RC = F.unidad(N, nombre="USB DISK", equipos=(PC,))        # con ese nombre, pero uno propio
F.ETIQUETAS[RC] = "OTRA"
equipo.guardar_ajustes(equipo.Ajustes())
ag = poner(RC, RA)
c("un nombre propio se queda como está, aunque la etiqueta de otra sea la misma",
  ag.conexiones[N].nombre, "USB DISK")
c("  y es la que no lo es la que se distingue",
  ag.conexiones[A].nombre, f"USB DISK ({PC})")

# --- el nombre recordado del ordenador se renueva al conectarse
F.ETIQUETAS.clear()
RD = F.unidad("d" * 32, nombre=PC, equipos=(PC, "LAPTOP-ANA"))
lista("d" * 32, RD, PC)
ag = poner(RD)
c("lo que el agente recordaba con el nombre del ordenador, ya no",
  ag.conexiones["d" * 32].nombre, "prdrive · dddd")
c("  y lo que recuerda es lo nuevo", equipo.leer_ajustes().unidades["d" * 32].nombre,
  "prdrive · dddd")

# --- una unidad que no se ve: el mismo nombre por defecto, sin etiqueta
c("sin nombre recordado, el del id (lo que llevan los avisos de una raíz que no está)",
  agente.nombre_guardado(None, A), "prdrive · aaaa")
c("  con nombre recordado, ese", agente.nombre_guardado(equipo.Unidad(A, nombre="Pen de Ana"), A),
  "Pen de Ana")
c("  y una unidad de la lista sin nombre, también por el id",
  agente.nombre_guardado(equipo.Unidad(A), A), "prdrive · aaaa")

# --- un aviso de la unidad nueva sale con el nombre de ahora
F.AVISOS.clear()
equipo.guardar_ajustes(equipo.Ajustes())
F.ETIQUETAS[RA] = "SANDISK"
poner(RA)
c("«Se ha conectado …» (la pregunta de una unidad nueva) lleva su nombre",
  any(t == "Se ha conectado SANDISK" for t, _ in F.AVISOS), True)

# --- nombres.etiqueta_de() sustituido: el agente no pregunta al sistema de verdad
c("(el arnés sustituye la etiqueta del sistema)", nombres.etiqueta_de(Path("/no/existe")), "")

raise SystemExit(c.report())
