#!/usr/bin/env python3
"""Abrir la ventana o el llavero de una unidad que está a mitad de una pasada.

Con un equipo de mentira (`_agente_falso`): el atajo, la bandeja y
`agente.py atajo` llegan al agente con la misma petición (`PIDE_ABRIR`,
`PIDE_LLAVERO`), y es él quien decide. Se comprueba:
- Sin pasada en curso, se abre al momento y sin aviso, como siempre. Lanzada
  la ventana, el agente suelta la unidad ya (no espera al `daemon.stop`), así
  que no empieza otra pareja suya mientras arranca.
- Con una pasada suya en curso, su ventana no se abre todavía: un aviso dice
  que se abrirá al terminar. Pulsar otra vez no avisa ni abre otra. Acabada la
  pasada (bien o con un fallo) se abre una vez, antes de que el agente lance
  la pareja siguiente de esa unidad.
- Si la pasada dura más de `ESPERA_TRAS_PASADA`, se abre igual a ese plazo,
  contado desde la primera pulsación: pulsar otra vez no lo alarga.
- Una sonda del remoto no es una sincronización: no se espera.
- El llavero espera solo si el llavero va en la pasada en curso, y no con su
  KeePassXC ya abierto (abrirlo solo lo trae delante).
- Lo pendiente se descarta, con su línea en el diario, si la unidad se
  desconecta, se pide expulsarla o actualizarla.
"""

import sys

from _harness import Checks

import _agente_falso as F
import agente
from common import equipo, model
from ui import atajos

c = Checks("abrir con una pasada en curso")
F.preparar()
agente.ABRE_LLAVERO = True
agente.keepassxc_abierto = lambda raiz: False

A = "a" * 32
RA = F.unidad(A, parejas=("docs",), nombre="PEN")
CONFIG = RA / agente.APP_SUBDIR / "sync_config.toml"
CONFIG.write_text(CONFIG.read_text(encoding="utf-8")
                  + '\n[keychain]\nbase = "personal.kdbx"\n', encoding="utf-8")
RUNSYNC = str(RA / agente.APP_SUBDIR / "runsync.py")
equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(
    equipo.Unidad(A, equipo.DAEMON, "PEN", codigo=agente.huella(RA) or "")))
F.RAICES[:] = [RA]
F.COMPATIBLES.add(RA)


def ventanas() -> list:
    """Las ventanas de runsync de la unidad lanzadas."""
    return [p for p in F.LANZADOS if p.args[1:] == [RUNSYNC]]


def llaveros() -> list:
    """Los `runsync.py --llavero` de la unidad lanzados."""
    return [p for p in F.LANZADOS if p.args[1:] == [RUNSYNC, "--llavero"]]


def pulsar(ag, accion: str, vueltas: int = 1) -> None:
    """Pulsa un atajo y da una vuelta al agente."""
    ag.pedir({"pide": equipo.PIDE_ATAJO, "accion": accion})
    F.vueltas(ag, vueltas)


def calmar(ag) -> None:
    """Acaba bien lo que esté en marcha hasta que no se lance nada más."""
    for _ in range(20):
        if ag.pasada is not None:
            F.acabar(ag.pasada.proc)
        F.vueltas(ag, 1)
        if ag.pasada is None:
            F.vueltas(ag, 1)
            if ag.pasada is None:
                return


def atendida(ag) -> None:
    """Deja pasar la `GRACIA` de la ventana lanzada y todo lo que se lance tras ella."""
    F.vueltas(ag, int(agente.GRACIA / agente.TICK) + 2)
    calmar(ag)


def pasar_pareja(ag, pareja: str) -> F.Proc:
    """Pide una pasada de esa pareja y devuelve su `sync.py`, en marcha."""
    ag.pedir({"pide": equipo.PIDE_PASADA, "id": A, "parejas": [pareja]})
    F.vueltas(ag, 1)
    return ag.pasada.proc


def pendiente(ag) -> dict:
    """Lo que la unidad tiene pendiente de abrir al acabar su pasada."""
    return dict(ag.conexiones[A].tras_pasada)


ag = F.nuevo()
F.vueltas(ag, 3)
calmar(ag)
c("de partida, la unidad atendida y sin nada en marcha",
  (ag.pasada, ag.conexiones[A].lock is not None), (None, True))

# --- sin pasada en curso: como siempre
F.AVISOS.clear()
pulsar(ag, atajos.VENTANA)
c("sin pasada en curso, su ventana se abre al momento, sin aviso",
  (len(ventanas()), F.AVISOS), (1, []))
c("  y el agente la suelta ya, sin esperar al daemon.stop de la ventana",
  (ag.conexiones[A].lock, F.lock(RA)), (None, {}))
ag.pedir({"pide": equipo.PIDE_PASADA, "id": A, "parejas": []})
F.vueltas(ag, 2)
c("  así que no lanza ninguna pareja suya mientras la ventana arranca, ni pedida",
  ag.pasada, None)
atendida(ag)
c("  sin ventana a la vista, pasada su GRACIA, vuelve a atenderla",
  ag.conexiones[A].lock is not None, True)
pulsar(ag, atajos.LLAVERO)
c("sin pasada en curso, su llavero se abre al momento, sin aviso",
  (len(llaveros()), F.AVISOS), (1, []))

# --- con una pasada suya en curso: aviso y se abre al terminar
proc = pasar_pareja(ag, "docs")
antes = len(ventanas())
pulsar(ag, atajos.VENTANA)
c("con una pasada suya en curso, su ventana no se abre todavía", len(ventanas()), antes)
c("  un aviso dice que se abrirá cuando termine",
  F.AVISOS, [("PEN: sincronizando",
              "Hay una sincronización en curso; se abrirá su ventana cuando termine.")])
c("  y queda apuntado en la unidad", list(pendiente(ag)), [agente.TRAS_VENTANA])
pulsar(ag, atajos.VENTANA)
ag.pedir({"pide": equipo.PIDE_ABRIR, "id": A})          # «Configurar» de la bandeja
F.vueltas(ag, 1)
c("pulsar otra vez (o la bandeja) no repite el aviso ni abre otra",
  (len(F.AVISOS), len(ventanas())), (1, antes))
ag.pedir({"pide": equipo.PIDE_PASADA, "id": A, "parejas": [model.LLAVERO]})
F.vueltas(ag, 1)
F.acabar(proc)
F.vueltas(ag, 1)
c("acabada la pasada, se abre su ventana, una vez", len(ventanas()), antes + 1)
c("  antes de que el agente lance la pareja siguiente de esa unidad",
  (ag.pasada, (A, model.LLAVERO) in ag.urgentes), (None, True))
c("  y no queda nada pendiente", pendiente(ag), {})
atendida(ag)

# --- una pasada que falla: se abre igual
F.AVISOS.clear()
proc = pasar_pareja(ag, "docs")
antes = len(ventanas())
pulsar(ag, atajos.VENTANA)
F.acabar(proc, 1, "ERROR : docs: ha fallado\n")
F.vueltas(ag, 1)
c("si la pasada acaba con un fallo, su ventana se abre igual (es donde se ve)",
  len(ventanas()), antes + 1)
atendida(ag)

# --- una pasada larga: a los ESPERA_TRAS_PASADA de la primera pulsación
proc = pasar_pareja(ag, "docs")
antes = len(ventanas())
F.AVISOS.clear()
pulsar(ag, atajos.VENTANA)
F.pasar(agente.ESPERA_TRAS_PASADA / 2)
pulsar(ag, atajos.VENTANA)
F.pasar(agente.ESPERA_TRAS_PASADA / 2 - 3 * agente.TICK)
F.vueltas(ag, 1)
c("una pasada larga: justo antes del plazo, todavía no", len(ventanas()), antes)
F.vueltas(ag, 3)
c("  a los ESPERA_TRAS_PASADA de la primera pulsación (la segunda no lo alarga), se abre",
  (len(ventanas()), ag.pasada is not None and ag.pasada.proc is proc), (antes + 1, True))
c("  con un solo aviso", len(F.AVISOS), 1)
F.acabar(proc)
F.vueltas(ag, 1)
c("  y al acabar la pasada no se abre otra", len(ventanas()), antes + 1)
atendida(ag)

# --- una sonda del remoto no es una sincronización
proc = pasar_pareja(ag, "docs")
F.acabar(proc, 1, "ERROR : dial tcp 10.0.0.1:22: connection refused\n")
F.vueltas(ag, 1)
c("una pasada que falla por la red lanza la sonda de su remoto",
  ag.pasada is not None and ag.pasada.tarea.tipo == agente.pl.SONDA, True)
F.AVISOS.clear()
antes = len(ventanas())
pulsar(ag, atajos.VENTANA)
c("  con la sonda en marcha, su ventana se abre al momento, sin aviso",
  (len(ventanas()), F.AVISOS), (antes + 1, []))
F.acabar(ag.pasada.proc)
atendida(ag)

# --- el llavero: solo si pasa el llavero
proc = pasar_pareja(ag, "docs")
antes = len(llaveros())
F.AVISOS.clear()
pulsar(ag, atajos.LLAVERO)
c("el llavero, con otra pareja en curso: se abre al momento, sin aviso",
  (len(llaveros()), F.AVISOS), (antes + 1, []))
F.acabar(proc)
F.vueltas(ag, 1)
c("  y al acabar no se abre otra vez", len(llaveros()), antes + 1)
calmar(ag)
proc = pasar_pareja(ag, model.LLAVERO)
antes = len(llaveros())
pulsar(ag, atajos.LLAVERO)
c("con el llavero en la pasada en curso, no se abre todavía", len(llaveros()), antes)
c("  un aviso dice que se abrirá cuando termine",
  F.AVISOS, [("PEN: sincronizando",
              "Hay una sincronización en curso; se abrirá su llavero cuando termine.")])
pulsar(ag, atajos.LLAVERO)
c("  pulsar otra vez no repite el aviso", len(F.AVISOS), 1)
F.acabar(proc)
F.vueltas(ag, 1)
c("  acabada, se abre, una vez", len(llaveros()), antes + 1)
calmar(ag)
ag.keepassxc.add(A)
proc = pasar_pareja(ag, model.LLAVERO)
antes = len(llaveros())
F.AVISOS.clear()
pulsar(ag, atajos.LLAVERO)
c("con su KeePassXC ya abierto no se espera: abrirlo solo lo trae delante",
  (len(llaveros()), F.AVISOS), (antes + 1, []))
ag.keepassxc.discard(A)
F.acabar(proc)
calmar(ag)

# --- se descarta si la unidad se va, se expulsa o se actualiza
proc = pasar_pareja(ag, "docs")
antes = len(ventanas())
pulsar(ag, atajos.VENTANA)
F.DIARIO.clear()
F.RAICES[:] = []
F.vueltas(ag, 3)
c("si la unidad se desconecta mientras espera, se descarta, con su línea en el diario",
  [d for d in F.DIARIO if "no abro su ventana" in d], ["PEN: no abro su ventana: se ha ido"])
F.RAICES[:] = [RA]
F.vueltas(ag, 3)
calmar(ag)
c("  y al volver a conectarla no se abre", len(ventanas()), antes)

proc = pasar_pareja(ag, "docs")
pulsar(ag, atajos.VENTANA)
F.DIARIO.clear()
ag.pedir({"pide": equipo.PIDE_EXPULSAR, "id": A})
F.vueltas(ag, 1)
c("si se pide expulsarla mientras espera, se descarta, con su línea en el diario",
  ([d for d in F.DIARIO if "no abro su ventana" in d], pendiente(ag)),
  (["PEN: no abro su ventana: se está expulsando"], {}))
F.acabar(proc)
F.vueltas(ag, 3)
c("  y al acabar la pasada no se abre", len(ventanas()), antes)
F.RAICES[:] = []
F.vueltas(ag, 3)
ag.expulsiones.clear()
F.RAICES[:] = [RA]
F.vueltas(ag, 3)
calmar(ag)

proc = pasar_pareja(ag, "docs")
pulsar(ag, atajos.VENTANA)
F.DIARIO.clear()
# Lo que deja `_pedir_actualizacion()` de una unidad con otra versión que la del agente.
ag.conexiones[A].actualizacion = agente.Actualizacion(F.reloj())
F.vueltas(ag, 1)
c("si se pide actualizarla mientras espera, se descarta, con su línea en el diario",
  ([d for d in F.DIARIO if "no abro su ventana" in d], pendiente(ag)),
  (["PEN: no abro su ventana: se está actualizando"], {}))
c("  y no se abre", len(ventanas()), antes)

sys.exit(c.report())
