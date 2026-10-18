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
- El nombre que el agente recuerda (`Unidad.nombre`) lo calculó él, no lo puso
  nadie: en `fleet.json` sin `nombre` no se toma por propio y se recalcula al
  conectarse (otra etiqueta, lo que guardaba la 0.7.4, una unidad que se quita,
  el nombre del ordenador repetido en dos). Uno de `fleet.json` que no es de un
  equipo sigue siendo propio.
- Uno de `fleet.json` que se llama como el ordenador también es propio si es
  el `label=` de su `autorun.inf` (lo puso «Nombre e icono»), también en una
  raíz del equipo.
"""

from dataclasses import replace
from pathlib import Path

from _harness import Checks

import _agente_falso as F
import agente
from common import autorun, equipo, nombres
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

# --- lo que el agente recuerda no es un nombre propio: sin `nombre` en fleet.json
# (nunca se ha publicado la nota de la flota) se recalcula al conectarse
F.ETIQUETAS.clear()
equipo.guardar_ajustes(equipo.Ajustes())
RE = F.unidad("e" * 32)                                   # sin `nombre` ni equipos
lista("e" * 32, RE)
F.ETIQUETAS[RE] = "SANDISK"
ag = poner(RE)
c("sin nombre en fleet.json, la etiqueta", ag.conexiones["e" * 32].nombre, "SANDISK")
c("  y el agente la recuerda", equipo.leer_ajustes().unidades["e" * 32].nombre, "SANDISK")
F.ETIQUETAS[RE] = "KINGSTON"
ag = poner(RE)
c("  la etiqueta cambia: la de ahora, no la que recordaba",
  ag.conexiones["e" * 32].nombre, "KINGSTON")
c("  y recuerda la nueva", equipo.leer_ajustes().unidades["e" * 32].nombre, "KINGSTON")

F.ETIQUETAS.clear()
RF = F.unidad("f" * 32)
lista("f" * 32, RF, "PRDRIVE ffffffff")                     # lo que guardaban los agentes de la 0.7.4
ag = poner(RF)
c("lo que guardaba la 0.7.4 recibe el nombre por defecto de ahora",
  ag.conexiones["f" * 32].nombre, "prdrive · ffff")
c("  y lo que recuerda es lo nuevo", equipo.leer_ajustes().unidades["f" * 32].nombre,
  "prdrive · ffff")

RA2, RB2 = F.unidad(A), F.unidad(B)                       # sin `nombre` ni equipos
equipo.guardar_ajustes(equipo.Ajustes())
lista(A, RA2)
lista(B, RB2)
F.ETIQUETAS[RA2] = F.ETIQUETAS[RB2] = "USB DISK"
F.RAICES[:] = [RA2]
ag = F.nuevo()
F.vueltas(ag, 3)
F.RAICES[:] = [RA2, RB2]
F.vueltas(ag, 3)
c("dos con la misma etiqueta y sin equipos: la segunda lleva el principio de su id",
  (ag.conexiones[A].nombre, ag.conexiones[B].nombre), ("USB DISK", "USB DISK · bbbbbbbb"))
c("  y el agente recuerda las dos",
  (equipo.leer_ajustes().unidades[A].nombre, equipo.leer_ajustes().unidades[B].nombre),
  ("USB DISK", "USB DISK · bbbbbbbb"))
ajustes = equipo.leer_ajustes()                           # se quita la primera
equipo.guardar_ajustes(replace(ajustes, unidades={B: ajustes.unidades[B]}))
ag = poner(RB2)
c("  se quita la primera: la otra deja de distinguirse de una que ya no está",
  ag.conexiones[B].nombre, "USB DISK")

F.ETIQUETAS.clear()
RG, RH = F.unidad("1" * 32), F.unidad("2" * 32)           # sin `nombre` ni equipos
equipo.guardar_ajustes(equipo.Ajustes())
lista("1" * 32, RG, PC)                                   # lo que escribe el asistente sin publicar
lista("2" * 32, RH, PC)
ag = poner(RG, RH)
c("dos recordadas con el nombre del ordenador no salen iguales",
  sorted(con.nombre for con in ag.conexiones.values()), ["prdrive · 1111", "prdrive · 2222"])

F.ETIQUETAS.clear()
RI = F.unidad("3" * 32, nombre="Pen de Ana")               # un nombre de fleet.json que no es un equipo
equipo.guardar_ajustes(equipo.Ajustes())
lista("3" * 32, RI, "prdrive · 3333")                     # y lo que el agente recordaba, otro
F.ETIQUETAS[RI] = "SANDISK"
ag = poner(RI)
c("un nombre de fleet.json que no es de un equipo sigue siendo propio",
  ag.conexiones["3" * 32].nombre, "Pen de Ana")
c("  y es lo que el agente recuerda ahora", equipo.leer_ajustes().unidades["3" * 32].nombre,
  "Pen de Ana")

# --- llamada como el ordenador a propósito: «Nombre e icono» lo deja también en el
# `label=` de su autorun.inf, y eso dice que lo puso alguien
F.ETIQUETAS.clear()
RJ = F.unidad("4" * 32, nombre=PC.upper(), equipos=(PC.title(),))
autorun.escribir(RJ, autorun.con("", PC.upper(), ""))
equipo.guardar_ajustes(equipo.Ajustes())
lista("4" * 32, RJ, "prdrive · 4444")                     # lo que el agente guardó antes
F.ETIQUETAS[RJ] = "PRDRIVE"
ag = poner(RJ)
c("un nombre como el del ordenador que también está en su autorun.inf es propio",
  ag.conexiones["4" * 32].nombre, PC.upper())
c("  y es lo que el agente recuerda ahora", equipo.leer_ajustes().unidades["4" * 32].nombre,
  PC.upper())
c("  también en una raíz del equipo (sin etiqueta de volumen)",
  agente.nombre_de(RJ, "4" * 32, con_etiqueta=False), PC.upper())
autorun.escribir(RJ, autorun.con("", "Otro nombre", ""))
c("  pero si el autorun.inf dice otro, el del ordenador no es propio",
  agente.nombre_de(RJ, "4" * 32, con_etiqueta=False), "prdrive · 4444")

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
