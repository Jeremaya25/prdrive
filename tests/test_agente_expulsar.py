#!/usr/bin/env python3
"""«Expulsar» en el desplegable de una unidad de la bandeja.

Con un sistema de mentira (`_agente_falso`): `expulsar.compatible()` y
`expulsar.expulsar()` están sustituidos y lo que se «expulsa» se apunta. Se
comprueba:
- Solo una unidad de la lista cuyo volumen es compatible lleva «Expulsar» en su
  desplegable; una que no lo es, una que no está en la lista y la raíz de este
  equipo, no (ni apagada).
- Pedido con una pasada en curso, espera a que acabe; luego suelta el lock, no
  lanza nada más de esa unidad y expulsa UNA vez. Mientras, la bandeja dice
  «Expulsando…» y no deja abrir su ventana.
- Al ir bien avisa «ya puedes quitarla». Si la unidad sigue a la vista pasado
  `GRACIA_EXPULSION`, vuelve a atenderse.
- Al ir mal avisa del motivo y sigue atendiéndola como antes.
- Con su ventana abierta no expulsa y lo dice pasado `ESPERA_VENTANA`.
- Lo que no es expulsable se pide y no pasa nada.
- `agente.py expulsar ID` deja la petición en el buzón.
"""

import sys
from pathlib import Path

from _harness import Checks, tmpdir

import _agente_falso as F
import agente
import penwatch
from common import equipo, expulsar
from ui import bandeja

c = Checks("«Expulsar» desde la bandeja")
F.preparar()


def lista(uid: str, raiz: Path, nombre: str) -> None:
    """Pone la unidad en la lista con la huella de su código de ahora."""
    equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(
        equipo.Unidad(uid, equipo.DAEMON, nombre, codigo=agente.huella(raiz) or "")))


def desplegable(ag, nombre: str):
    """Devuelve el desplegable de la bandeja cuyo rótulo empieza por `nombre`."""
    return next(e for e in bandeja.vista(ag.resumen()).menu
                if e.hijos and e.texto.startswith(nombre))


def hijo(ag, nombre: str, texto: str):
    """Devuelve la entrada `texto` del desplegable `nombre`, o `None`."""
    return next((e for e in desplegable(ag, nombre).hijos if e.texto == texto), None)


def avisos(texto: str) -> list[str]:
    """Los títulos de los avisos que dicen `texto`."""
    return [t for t, x in F.AVISOS if texto in t or texto in x]


# --- quién lleva «Expulsar»
A, B, N = "a" * 32, "b" * 32, "n" * 32
RA, RB, RN = (F.unidad(A, parejas=("docs",), nombre="PEN-A"),
              F.unidad(B, parejas=("docs",), nombre="PEN-B"),
              F.unidad(N, parejas=("docs",), nombre="PEN-N"))
lista(A, RA, "PEN-A")
lista(B, RB, "PEN-B")                   # en la lista, pero un disco interno
F.RAICES[:] = [RA, RB, RN]
F.COMPATIBLES.update({RA, RN})          # N es compatible, pero no está en la lista
ag = F.nuevo()
F.vueltas(ag, 3)
filas = {u["id"]: u for u in ag.resumen()["unidades"]}
c("expulsable: la de la lista y compatible, sí",
  (filas[A]["expulsable"], filas[A]["expulsando"]), (True, False))
c("  la que no es compatible, no", filas[B]["expulsable"], False)
c("  la que no está en la lista, aunque sea compatible, no", filas[N]["expulsable"], False)
e = hijo(ag, "PEN-A", "Expulsar")
c("el desplegable de la compatible lleva «Expulsar», con su id y su icono",
  (e is not None and e.pide, e is not None and e.icono, e is not None and e.activa),
  (({"pide": equipo.PIDE_EXPULSAR, "id": A},), bandeja.I_EXPULSAR, True))
c("  tras un separador, y antes de la versión",
  [x.texto for x in desplegable(ag, "PEN-A").hijos],
  ["Configurar", "Abrir en explorador", "Sincronizar ahora", "", "Expulsar", "",
   f"Versión {F.VERSION}"])
c("la que no es compatible no lo lleva, ni apagado", hijo(ag, "PEN-B", "Expulsar"), None)
c("la que no está en la lista solo lleva «Atender…»",
  [x.texto for x in desplegable(ag, "PEN-N").hijos if x.texto],
  ["Atender…", f"Versión {F.VERSION}"])

# --- una pasada en curso
F.pasar(60)
decision = F.vueltas(ag, 2)
pasada = F.pasadas(RA)
c("(la unidad se atiende como siempre: tiene su lock y una pasada)",
  (F.lock(RA).get("agente"), len(pasada)), (True, 1))
equipo.pedir({"pide": equipo.PIDE_EXPULSAR, "id": A})
F.vueltas(ag, 2)
c("con una pasada en curso, espera: no expulsa todavía", F.EXPULSADAS, [])
c("  pero el estado ya dice que se está expulsando",
  next(u for u in ag.resumen()["unidades"] if u["id"] == A)["expulsando"], True)
c("  y el desplegable, «Expulsando…» apagado, sin Expulsar ni abrir su ventana",
  ([(x.texto, x.activa) for x in desplegable(ag, "PEN-A").hijos
    if x.texto in ("Expulsar", "Expulsando…", "Configurar", "Abrir en explorador")]),
  [("Configurar", False), ("Abrir en explorador", False), ("Expulsando…", False)])
F.acabar(pasada[0], rc=0)
antes = len(F.pasadas(RA))
F.vueltas(ag, 1)
c("acabada la pareja, expulsa UNA vez esa raíz", F.EXPULSADAS, [RA])
c("  soltando antes su lock", (RA / penwatch.DAEMON_LOCK_REL).exists(), False)
F.vueltas(ag, 1)
c("  y a la vuelta siguiente, con el resultado, avisa de que ya se puede quitar",
  avisos("ya puedes quitarla"), ["PEN-A: ya puedes quitarla"])
F.vueltas(ag, 5)
c("  mientras sigue a la vista no vuelve a lanzar nada suyo",
  (len(F.pasadas(RA)), (RA / penwatch.DAEMON_LOCK_REL).exists(), len(F.EXPULSADAS)),
  (antes, False, 1))
c("  y no se pide otra expulsión ni se avisa dos veces",
  len(avisos("ya puedes quitarla")), 1)
F.pasar(agente.GRACIA_EXPULSION)
F.vueltas(ag, 3)
c("si pasada la gracia la unidad sigue ahí, vuelve a atenderse",
  A in ag.conexiones and (RA / penwatch.DAEMON_LOCK_REL).exists(), True)
c("  y su desplegable vuelve a ofrecer «Expulsar»", hijo(ag, "PEN-A", "Expulsar") is not None,
  True)

# --- se va de verdad
F.EXPULSADAS.clear()
F.AVISOS.clear()
equipo.pedir({"pide": equipo.PIDE_EXPULSAR, "id": A})
F.vueltas(ag, 1)
F.RAICES[:] = [RB, RN]                  # el sistema la retira
F.vueltas(ag, 3)
c("al desaparecer la unidad, ya no cuenta como conexión ni queda nada pedido",
  (A in ag.conexiones, A in ag.expulsiones), (False, False))
F.RAICES[:] = [RA, RB, RN]              # se vuelve a enchufar
F.vueltas(ag, 4)
c("al volver, se atiende como una unidad nueva y se puede expulsar otra vez",
  (A in ag.conexiones, hijo(ag, "PEN-A", "Expulsar") is not None), (True, True))

# --- sale mal
F.EXPULSADAS.clear()
F.AVISOS.clear()
F.RESULTADO_EXPULSAR[0] = expulsar.Resultado(False, "Algo la está usando.")
F.pasar(60)
F.vueltas(ag, 2)
for p in F.pasadas(RA):                 # que no haya pasadas en curso
    p.rc = 0
equipo.pedir({"pide": equipo.PIDE_EXPULSAR, "id": A})
F.vueltas(ag, 2)
c("si el sistema no la suelta, se dice con su motivo",
  (F.EXPULSADAS, [(t, x) for t, x in F.AVISOS if "no la expulso" in t]),
  ([RA], [("PEN-A: no la expulso", "Algo la está usando.")]))
F.vueltas(ag, 3)
c("  y se sigue atendiendo como antes (lock, y otra vez expulsable)",
  (A in ag.expulsiones, (RA / penwatch.DAEMON_LOCK_REL).exists(),
   hijo(ag, "PEN-A", "Expulsar") is not None), (False, True, True))
F.RESULTADO_EXPULSAR[0] = expulsar.Resultado(True, "Ya puedes quitarla.")

# --- con su ventana abierta
F.EXPULSADAS.clear()
F.AVISOS.clear()
F.ventana_abierta(RA)
equipo.pedir({"pide": equipo.PIDE_EXPULSAR, "id": A})
F.vueltas(ag, 3)
c("con su ventana abierta no expulsa", F.EXPULSADAS, [])
F.pasar(agente.ESPERA_VENTANA)
F.vueltas(ag, 1)
c("  y pasado un rato lo dice y lo deja",
  ([t for t, _ in F.AVISOS], A in ag.expulsiones), (["PEN-A: no la expulso"], False))
(RA / penwatch.UI_LOCK_REL).unlink()

# --- lo que no es expulsable, o no está
F.EXPULSADAS.clear()
F.DIARIO.clear()
for uid in (B, N, "z" * 32):
    equipo.pedir({"pide": equipo.PIDE_EXPULSAR, "id": uid})
F.vueltas(ag, 2)
c("pedirlo de una no compatible, no listada o ausente no expulsa nada",
  (F.EXPULSADAS, ag.expulsiones), ([], {}))
c("  y queda dicho en el diario", sum("expuls" in d for d in F.DIARIO) >= 3, True)

# --- la raíz de este equipo es una carpeta
RQ = tmpdir("prdrive-raiz-equipo-")
Q = "q" * 32
(RQ / ".prdrive" / "state").mkdir(parents=True)
(RQ / ".prdrive" / "PRDRIVE").write_text(f"id={Q}\ntipo=equipo\n", encoding="utf-8")
(RQ / ".prdrive" / "VERSION").write_text(F.VERSION + "\n", encoding="utf-8")
for py in ("runsync.py", "sync.py"):
    (RQ / ".prdrive" / py).write_text("# de mentira\n", encoding="utf-8")
(RQ / ".prdrive" / "sync_config.toml").write_text(
    '[defaults]\nremote = "nas"\n\n[[pair]]\nname = "d"\nlocal = "d"\nremote_path = "/R/d"\n',
    encoding="utf-8")
equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(
    equipo.Unidad(Q, equipo.DAEMON, "Mi portátil", str(RQ))))
F.RAICES[:] = [RA, RB, RN, RQ]
F.COMPATIBLES.add(RQ)
F.vueltas(ag, 4)
fila = next((u for u in ag.resumen()["unidades"] if u["id"] == Q), None)
c("la raíz de este equipo, aunque su carpeta «sea compatible», no es expulsable",
  fila is not None and fila["expulsable"], False)

# --- la orden de la línea de órdenes
equipo.buzon().unlink(missing_ok=True)
sys.argv = ["agente.py", "expulsar", A]
agente.main()
pedidas = equipo.recoger()
c("`agente.py expulsar ID` deja la petición en el buzón",
  [(p["pide"], p["id"]) for p in pedidas], [(equipo.PIDE_EXPULSAR, A)])

sys.exit(c.report())
