#!/usr/bin/env python3
"""El agente y una unidad de su lista bloqueada con BitLocker.

Con un sistema de mentira (`_agente_falso`): el nombre de volumen de cada raíz
(`bitlocker.volumen_de`), su estado de BitLocker (`cifrada.bitlocker_de`) y la
ventana de desbloqueo de Windows (`agente.desbloquear_bitlocker`) están
sustituidos. Una «letra bloqueada» es una carpeta vacía con el nombre de volumen
de la unidad y el estado `BDE_LOCKED`. Se comprueba:
- `agente.json` recuerda el volumen de una unidad (`Unidad.volumen`), y lo que
  no tiene su forma se descarta sin perder la unidad.
- El agente apunta el volumen de una unidad de la lista con BitLocker cada vez
  que la atiende (al conectarla y con el sí de «Atender»), lo olvida cuando ya
  no lo lleva y no toca nada si Windows no contesta. Nunca el de una raíz de
  este equipo, ni el de una unidad con otro código, por actualizar o que no
  está en la lista. Un volumen no nombra a dos unidades.
- Una letra que no da ni fichero de control ni vestíbulo (o que contesta con un
  error), con el volumen apuntado de una unidad de la lista y en `BDE_LOCKED`,
  sale en `resumen()["bitlocker"]`, en `estado.json` y en `status`, con una
  línea en el diario por conexión. Nada más cuenta: otro estado, otro volumen,
  el modo `nada`, una unidad que ya no está en la lista. De ella no se lee ni
  se lanza nada, y sin volúmenes apuntados no se pregunta nada de ninguna letra.
- Con una bloqueada se recorre cada `RECORRIDO_WINDOWS` aunque haya bandeja.
- Desbloqueada, se conecta por el camino de siempre, huella incluida.
- «Desbloquear…» (`PIDE_DESBLOQUEAR` con su id, `agente.py desbloquear ID`) pide
  a Windows su ventana, una sola mientras siga abierta, y recorre en cada
  vuelta un rato. Cancelada, se puede volver a pedir; si Windows no la abre,
  se avisa. Desenchufada con la ventana abierta, se olvida sin cerrarla. Sin
  id, con el de una raíz cifrada, con el de una unidad que no está bloqueada o
  recién puesta en modo `nada`, no se pide nada a BitLocker.
"""

import contextlib
import io
import os
import sys
from pathlib import Path

from _harness import Checks, tmpdir

import _agente_falso as F
import agente
import penwatch
from common import bitlocker, cifrada, equipo, store

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


# --- el sistema de mentira
VOLUMENES: dict[Path, str] = {}
"""El nombre de volumen de cada raíz; sin entrada, Windows no lo da."""
ESTADOS: dict[Path, int] = {}
"""El estado de BitLocker (`BDE_*`) de cada raíz; sin entrada, sin comprobar."""
ESCRITURAS = [0]
"""Las veces que se ha escrito `agente.json`."""


PREGUNTADAS: list[Path] = []
"""Las raíces de las que se ha preguntado el estado de BitLocker."""


def bitlocker_falso(raiz) -> bitlocker.BitLockerStatus:
    """Contesta por Windows con lo que diga `ESTADOS`."""
    PREGUNTADAS.append(Path(raiz))
    if Path(raiz) in ESTADOS:
        return bitlocker.BitLockerStatus(True, ESTADOS[Path(raiz)])
    return bitlocker.BitLockerStatus(False, detail="sin comprobar")


guardar_de_verdad = equipo.guardar_ajustes


def guardar_contando(ajustes: equipo.Ajustes) -> bool:
    """Escribe `agente.json` y lo cuenta."""
    ESCRITURAS[0] += 1
    return guardar_de_verdad(ajustes)


NOMBRADAS: list[Path] = []
"""Las raíces de las que se ha pedido el nombre de volumen."""


def volumen_falso(raiz, es_win: bool = True) -> str:
    """Contesta por Windows con lo que diga `VOLUMENES`."""
    NOMBRADAS.append(Path(raiz))
    return VOLUMENES.get(Path(raiz), "")


bitlocker.volumen_de = volumen_falso
cifrada.bitlocker_de = bitlocker_falso
equipo.guardar_ajustes = guardar_contando


def lista(uid: str, raiz: Path, nombre: str, **mas) -> None:
    """Pone la unidad en la lista con la huella de su código de ahora."""
    guardar_de_verdad(equipo.leer_ajustes().con_unidad(
        equipo.Unidad(uid, equipo.DAEMON, nombre, codigo=agente.huella(raiz) or "", **mas)))


def volumen(uid: str) -> str:
    """Devuelve el volumen que `agente.json` recuerda de esa unidad."""
    return equipo.leer_ajustes().unidades[uid].volumen


def enchufado(*raices: Path):
    """Devuelve un agente recién arrancado que ya ha visto esas raíces."""
    F.RAICES[:] = list(raices)
    nuevo = F.nuevo()
    F.vueltas(nuevo, 3)
    return nuevo


# --- se apunta el volumen de la unidad que se atiende
RA = F.unidad(A, parejas=("docs",), nombre="Trabajo")
lista(A, RA, "Trabajo")
ESTADOS[RA], VOLUMENES[RA] = bitlocker.BDE_ON, V1
ag = enchufado(RA)
c("una unidad de la lista con BitLocker: se apunta su volumen",
  (A in ag.conexiones, volumen(A), ag.ajustes.unidades[A].volumen), (True, V1, V1))
c("  y se dice en el diario, una vez", sum("su volumen" in d for d in F.DIARIO), 1)
antes = ESCRITURAS[0]
F.RAICES[:] = []
F.vueltas(ag, 1)
F.RAICES[:] = [RA]
F.vueltas(ag, 3)
c("al volver a enchufarla en el mismo volumen no se escribe nada",
  (A in ag.conexiones, ESCRITURAS[0] - antes, volumen(A)), (True, 0, V1))
del ESTADOS[RA]
enchufado(RA)
c("si Windows no dice su estado, lo apuntado se queda", volumen(A), V1)
ESTADOS[RA] = bitlocker.BDE_ON
del VOLUMENES[RA]
enchufado(RA)
c("  y si no da el nombre del volumen, también", volumen(A), V1)
VOLUMENES[RA] = V2
enchufado(RA)
c("en otro volumen, se apunta el nuevo", volumen(A), V2)
for apagado in (bitlocker.BDE_OFF, bitlocker.BDE_NOT_ENCRYPTABLE):
    lista(A, RA, "Trabajo", volumen=V2)
    ESTADOS[RA] = apagado
    enchufado(RA)
    c(f"sin BitLocker (estado {apagado}) se olvida", volumen(A), "")
for puesto in (bitlocker.BDE_SUSPENDED, bitlocker.BDE_ENCRYPTING, bitlocker.BDE_WAITING):
    lista(A, RA, "Trabajo")
    ESTADOS[RA], VOLUMENES[RA] = puesto, V1
    enchufado(RA)
    c(f"con BitLocker en el estado {puesto} también se apunta", volumen(A), V1)

# un volumen no nombra a dos unidades
RB = F.unidad(B, parejas=("docs",), nombre="Vieja")
lista(B, RB, "Vieja", volumen=V1)
lista(A, RA, "Trabajo")
ESTADOS[RA], VOLUMENES[RA] = bitlocker.BDE_ON, V1
enchufado(RA)
c("apuntarlo a una se lo quita a la que lo tenía", (volumen(A), volumen(B)), (V1, ""))
lista(A, RA, "Trabajo")
del VOLUMENES[RA]
PREGUNTADAS.clear()
ag = enchufado(RA)
c("sin nombre de volumen y sin nada apuntado, ni se pregunta por BitLocker",
  (A in ag.conexiones, PREGUNTADAS), (True, []))

# solo de lo que se atiende
C_, N, Q, W = "c" * 32, "n" * 32, "q" * 32, "w" * 32
RC = F.unidad(C_, parejas=("docs",), nombre="Cambiada")
guardar_de_verdad(equipo.leer_ajustes().con_unidad(
    equipo.Unidad(C_, equipo.DAEMON, "Cambiada", codigo="0" * 64)))
RN = F.unidad(N, parejas=("docs",), nombre="Nueva")
RW = F.unidad(W, parejas=("docs",), nombre="Antigua")
(RW / penwatch.APP_SUBDIR / "VERSION").write_text("0.4.0\n", encoding="utf-8")
lista(W, RW, "Antigua")
V3 = "\\\\?\\volume{33333333-3333-3333-3333-333333333333}\\"
V4 = "\\\\?\\volume{44444444-4444-4444-4444-444444444444}\\"
V5 = "\\\\?\\volume{55555555-5555-5555-5555-555555555555}\\"
for raiz, nombre_volumen in ((RC, V3), (RN, V4), (RW, V5)):
    ESTADOS[raiz], VOLUMENES[raiz] = bitlocker.BDE_ON, nombre_volumen
ag = enchufado(RC, RN, RW)
c("con otro código, sin estar en la lista o por actualizar, no se apunta nada",
  (volumen(C_), N in equipo.leer_ajustes().unidades, volumen(W)), ("", False, ""))
for pregunta in F.preguntas()[-2:]:
    pregunta.rc = 0                     # el sí a las dos preguntas
F.vueltas(ag, 2)
c("el sí de «Atender» lo apunta: a la que cambió y a la nueva",
  (volumen(C_), volumen(N)), (V3, V4))

RQ = tmpdir("prdrive-raiz-equipo-")
(RQ / ".prdrive" / "state").mkdir(parents=True)
(RQ / ".prdrive" / "PRDRIVE").write_text(f"id={Q}\ntipo=equipo\n", encoding="utf-8")
(RQ / ".prdrive" / "VERSION").write_text(F.VERSION + "\n", encoding="utf-8")
for py in ("runsync.py", "sync.py"):
    (RQ / ".prdrive" / py).write_text("# de mentira\n", encoding="utf-8")
(RQ / ".prdrive" / "sync_config.toml").write_text(
    '[defaults]\nremote = "nas"\n\n[[pair]]\nname = "d"\nlocal = "d"\nremote_path = "/R/d"\n',
    encoding="utf-8")
guardar_de_verdad(equipo.leer_ajustes().con_unidad(
    equipo.Unidad(Q, equipo.DAEMON, "Mi portátil", str(RQ))))
ESTADOS[RQ], VOLUMENES[RQ] = bitlocker.BDE_ON, "\\\\?\\volume{66666666-6666-6666-6666-666666666666}\\"
ag = enchufado(RQ)
c("la raíz de este equipo, aunque su disco lleve BitLocker, no apunta volumen",
  (Q in ag.conexiones, volumen(Q)), (True, ""))


# --- enchufada y bloqueada
class Rota(type(Path())):
    """Una raíz que contesta con un error a cualquier lectura, como un volumen bloqueado."""

    def is_file(self, *args, **kwargs):
        """Falla como Windows al mirar dentro de un volumen bloqueado."""
        raise PermissionError(5, "Acceso denegado")


class BandejaMuda:
    """Una bandeja que no enseña nada: solo está, para la cadencia del recorrido."""

    def poner(self, vista) -> None:
        """No hace nada con la vista."""


def bloqueadas(agente_) -> list[str]:
    """Devuelve los ids de las unidades que el resumen da por bloqueadas con BitLocker."""
    return [b["id"] for b in agente_.resumen()["bitlocker"]]


def recorrido(agente_) -> list[str]:
    """Da una vuelta con recorrido y devuelve las bloqueadas que quedan en el resumen."""
    F.vueltas(agente_, 1)
    return bloqueadas(agente_)


def cada(agente_, windows: bool, bandeja_) -> float:
    """Devuelve cada cuánto recorrería ese agente, en Windows o no, con esa bandeja."""
    era, tenia = agente.IS_WIN, agente_.bandeja
    agente.IS_WIN, agente_.bandeja = windows, bandeja_
    try:
        return agente_.cada_recorrido()
    finally:
        agente.IS_WIN, agente_.bandeja = era, tenia


def dichas() -> list[str]:
    """Devuelve las líneas del diario que dicen que una unidad está bloqueada."""
    return [d for d in F.DIARIO if "bloqueada con BitLocker" in d]


guardar_de_verdad(equipo.Ajustes())
lista(A, RA, "Trabajo", volumen=V1)
VOLUMENES.clear()
ESTADOS.clear()
E = tmpdir("prdrive-letra-")            # su letra, bloqueada: dentro no se ve nada
VOLUMENES[E], ESTADOS[E] = V1, bitlocker.BDE_LOCKED
F.RAICES[:] = [E]
F.DIARIO.clear()
F.LANZADOS.clear()
ag = F.nuevo()
F.vueltas(ag, 1)
c("bloqueada y conocida: sale en el resumen a la primera",
  ag.resumen()["bitlocker"],
  [{"id": A, "nombre": "Trabajo", "raiz": str(E), "desbloqueando": False}])
c("  no es una conexión ni se lanza nada", (A in ag.conexiones, F.LANZADOS), (False, []))
c("  y el diario lo dice una vez", dichas(), [f"Trabajo: bloqueada con BitLocker en {E}"])
F.vueltas(ag, 3)
c("  mientras siga así no se repite", len(dichas()), 1)
c("  y llega a estado.json", [b["id"] for b in equipo.leer_estado()["bitlocker"]], [A])
store.write_json(equipo.lock_json(), {"pid": os.getpid(), "host": agente.HOST})
salida = io.StringIO()
with contextlib.redirect_stdout(salida):
    agente.cmd_status(None)
c.contains("  y `status` lo cuenta, con cómo desbloquearla", salida.getvalue(),
           f"Bloqueada con BitLocker: Trabajo en {E} (agente.py desbloquear {A})")
equipo.lock_json().unlink()
c("con una bloqueada se recorre cada pocos segundos, también con bandeja",
  (cada(ag, True, BandejaMuda()), cada(ag, True, None)),
  (agente.RECORRIDO_WINDOWS, agente.RECORRIDO_WINDOWS))
c("  fuera de Windows, el recorrido de respaldo de siempre",
  cada(ag, False, BandejaMuda()), agente.RECORRIDO_RESPALDO)

for estado_bl in (bitlocker.BDE_ON, bitlocker.BDE_OFF, bitlocker.BDE_SUSPENDED):
    ESTADOS[E] = estado_bl
    c(f"con el volumen en el estado {estado_bl} no está bloqueada", recorrido(ag), [])
c("sin ninguna bloqueada, con bandeja se recorre de tarde en tarde y sin ella como siempre",
  (cada(ag, True, BandejaMuda()), cada(ag, True, None)),
  (agente.RECORRIDO_RESPALDO, agente.RECORRIDO_WINDOWS))
del ESTADOS[E]
c("sin poder comprobar su estado, tampoco", recorrido(ag), [])
ESTADOS[E] = bitlocker.BDE_LOCKED
c("bloqueada otra vez, vuelve", recorrido(ag), [A])
c("  y se dice otra vez: es otra conexión", len(dichas()), 2)
VOLUMENES[E] = V2
c("un volumen bloqueado que no es el de ninguna unidad de la lista no se enseña",
  recorrido(ag), [])
VOLUMENES[E] = V1
otra = tmpdir("prdrive-otra-letra-")    # Windows no da su nombre de volumen
F.RAICES[:] = [otra, E]
c("una letra sin nombre de volumen no tapa a las demás", recorrido(ag), [A])
F.RAICES[:] = [E]

equipo.pedir({"pide": equipo.PIDE_MODO, "id": A, "modo": equipo.NADA})
c("en modo `nada` no se enseña", recorrido(ag), [])
equipo.pedir({"pide": equipo.PIDE_MODO, "id": A, "modo": equipo.DAEMON})
c("  y de vuelta a otro modo, sí", recorrido(ag), [A])
en_la_lista = ag.ajustes
ag._guardar(equipo.Ajustes())
c("fuera de la lista, deja de enseñarse sin esperar al recorrido", bloqueadas(ag), [])
c("  y el recorrido tampoco la ve", recorrido(ag), [])
ag._guardar(en_la_lista)
c("  de vuelta en la lista, sí", recorrido(ag), [A])

rota = Rota(str(tmpdir("prdrive-letra-rota-")))
VOLUMENES[Path(rota)], ESTADOS[Path(rota)] = V1, bitlocker.BDE_LOCKED
F.RAICES[:] = [rota]
F.vueltas(ag, 1)
c("una letra que contesta con un error a toda lectura se reconoce igual",
  [(b["id"], b["raiz"]) for b in ag.resumen()["bitlocker"]], [(A, str(rota))])
F.RAICES[:] = [E]

lista(B, RB, "Vieja")                   # ninguna de la lista con volumen apuntado
VOLUMENES[RB], ESTADOS[RB] = V2, bitlocker.BDE_LOCKED
guardar_de_verdad(equipo.Ajustes().con_unidad(equipo.leer_ajustes().unidades[B]))
sin_volumen = F.nuevo()
NOMBRADAS.clear()
PREGUNTADAS.clear()
F.vueltas(sin_volumen, 2)
c("sin ninguna unidad con volumen apuntado, no se pregunta nada de ninguna letra",
  (bloqueadas(sin_volumen), NOMBRADAS, PREGUNTADAS), ([], [], []))
guardar_de_verdad(en_la_lista)

# desbloqueada: su letra ya se lee
F.RAICES[:] = [RA]
VOLUMENES[RA], ESTADOS[RA] = V1, bitlocker.BDE_ON
F.vueltas(ag, 4)
c("desbloqueada, se conecta y se atiende como siempre",
  (A in ag.conexiones, ag.resumen()["bitlocker"], F.lock(RA).get("agente")), (True, [], True))
for pasada in F.pasadas(RA):            # que no quede una pasada a medias
    F.acabar(pasada)
F.vueltas(ag, 1)
F.RAICES[:] = [E]
F.vueltas(ag, 1)
c("bloqueada de nuevo con la unidad puesta: deja de ser conexión y vuelve a enseñarse",
  (A in ag.conexiones, bloqueadas(ag)), (False, [A]))
(RA / penwatch.APP_SUBDIR / "de_mas.py").write_text("# otro código\n", encoding="utf-8")
preguntadas_antes = len(F.preguntas())
F.RAICES[:] = [RA]
F.vueltas(ag, 4)
c("desbloqueada con otro código: no se atiende y se pregunta, como siempre",
  (ag.conexiones[A].cambiada, len(F.preguntas()) - preguntadas_antes, F.lock(RA)),
  (True, 1, {}))
(RA / penwatch.APP_SUBDIR / "de_mas.py").unlink()


# --- «Desbloquear…»
DESBLOQUEOS: list[Path] = []
"""Las raíces para las que se ha pedido la ventana de desbloqueo de Windows."""
PROCESOS: list[F.Proc] = []
"""Los `bdeunlock.exe` de mentira que siguen (o no) abiertos."""
RESPUESTA = ["ventana"]
"""Qué pasa al pedirla: `ventana`, `nada` (no hay con qué) o `error` (no arranca)."""
SIN_VENTANA = ("Trabajo: no he podido abrir el desbloqueo de Windows",
               "Desbloquéala desde el Explorador.")


def desbloqueo_falso(raiz):
    """Hace de `agente.desbloquear_bitlocker()` sin lanzar nada."""
    DESBLOQUEOS.append(Path(raiz))
    if RESPUESTA[0] == "nada":
        return None
    if RESPUESTA[0] == "error":
        raise OSError("no arranca")
    PROCESOS.append(F.Proc(["bdeunlock.exe", str(raiz)]))
    return PROCESOS[-1]


def pedir_desbloqueo(agente_, uid: str, recorrer: bool = False) -> None:
    """Deja «Desbloquear…» de ese id en el buzón y da una vuelta."""
    equipo.pedir({"pide": equipo.PIDE_DESBLOQUEAR, "id": uid})
    F.vueltas(agente_, 1, recorrer=recorrer)


def desbloqueando(agente_) -> list[bool]:
    """Devuelve, de cada bloqueada del resumen, si su ventana de Windows está abierta."""
    return [b["desbloqueando"] for b in agente_.resumen()["bitlocker"]]


lanzador_de_verdad = getattr(agente, "desbloquear_bitlocker", None)
agente.desbloquear_bitlocker = desbloqueo_falso
guardar_de_verdad(equipo.Ajustes())
lista(A, RA, "Trabajo", volumen=V1)
F.RAICES[:] = [E]
for apuntado in (F.DIARIO, F.AVISOS, F.LANZADOS):
    apuntado.clear()
ag = F.nuevo()
F.vueltas(ag, 1)
pedir_desbloqueo(ag, A)
c("«Desbloquear…» de una bloqueada pide a Windows su ventana, para su letra",
  DESBLOQUEOS, [E])
c("  el resumen dice que se está desbloqueando", desbloqueando(ag), [True])
c("  y se recorre en cada vuelta un rato, para verla en cuanto se abra",
  ag.rafaga_hasta, F.reloj() - agente.TICK + agente.RAFAGA)
pedir_desbloqueo(ag, A)
c("pedirlo otra vez con la ventana abierta no abre otra", len(DESBLOQUEOS), 1)
PROCESOS[-1].rc = 1                     # se cierra la ventana sin desbloquear
F.vueltas(ag, 1)
c("si se cancela, sigue bloqueada y se puede volver a pedir",
  (bloqueadas(ag), desbloqueando(ag)), ([A], [False]))
pedir_desbloqueo(ag, A)
c("  y entonces sí abre otra", (len(DESBLOQUEOS), desbloqueando(ag)), (2, [True]))
PROCESOS[-1].rc = 1
for sin in ("nada", "error"):
    RESPUESTA[0] = sin
    F.AVISOS.clear()
    pedir_desbloqueo(ag, A)
    c(f"si Windows no abre la ventana ({sin}), se avisa de cómo hacerlo a mano",
      (F.AVISOS, ag.desbloqueos_bitlocker, desbloqueando(ag)), ([SIN_VENTANA], {}, [False]))
RESPUESTA[0] = "ventana"

# se desenchufa con la ventana abierta
pedir_desbloqueo(ag, A)
F.RAICES[:] = []
F.vueltas(ag, 1)
c("desenchufada con la ventana abierta: deja de enseñarse y se olvida su ventana",
  (ag.resumen()["bitlocker"], ag.desbloqueos_bitlocker, PROCESOS[-1].terminado),
  ([], {}, False))
F.RAICES[:] = [E]
F.vueltas(ag, 1)
c("  y al volver se ofrece desbloquearla otra vez", (bloqueadas(ag), desbloqueando(ag)),
  ([A], [False]))

# lo que no es de una unidad bloqueada sigue su camino
cofre = tmpdir("prdrive-cofre-")
equipo.pedir({"pide": equipo.PIDE_RAIZ, "id": Q, "ruta": str(cofre / "punto"),
              "nombre": "Cofre", "contenedor": str(cofre / "PRDRIVE.hc")})
F.vueltas(ag, 1)
antes = len(DESBLOQUEOS)
F.AVISOS.clear()
pedir_desbloqueo(ag, "")
pedir_desbloqueo(ag, Q)
c("«desbloquear» sin id, o con el de una raíz cifrada, va a su contenedor y no a BitLocker",
  ([t for t, x in F.AVISOS if x.startswith("Tenía que estar en")], len(DESBLOQUEOS) - antes),
  (["Cofre: no encuentro su contenedor"] * 2, 0))
ag._guardar(equipo.Ajustes().con_unidad(ag.ajustes.unidades[A]).con_unidad(
    equipo.Unidad(B, equipo.DAEMON, "Vieja", volumen=V2)))
F.DIARIO.clear()
pedir_desbloqueo(ag, B)
pedir_desbloqueo(ag, "z" * 32)
c("el de una unidad que ahora no está bloqueada, o que no existe, no abre nada",
  (len(DESBLOQUEOS) - antes, [d for d in F.DIARIO if "BitLocker" in d]),
  (0, ["Vieja: no está bloqueada con BitLocker ahora"]))
equipo.pedir({"pide": equipo.PIDE_MODO, "id": A, "modo": equipo.NADA})
pedir_desbloqueo(ag, A)                 # en el mismo buzón, antes de que se recorra
c("puesta en modo `nada` en el mismo buzón, ya no se desbloquea",
  (len(DESBLOQUEOS) - antes, ag.desbloqueos_bitlocker), (0, {}))
equipo.pedir({"pide": equipo.PIDE_MODO, "id": A, "modo": equipo.DAEMON})
F.vueltas(ag, 1)

# se desbloquea de verdad
pedir_desbloqueo(ag, A)
c("(pedida otra vez, con su ventana abierta)", desbloqueando(ag), [True])
F.RAICES[:] = [RA]
F.vueltas(ag, 4)
c("al teclear la contraseña la unidad se lee, se conecta y la ventana se olvida",
  (A in ag.conexiones, ag.resumen()["bitlocker"], ag.desbloqueos_bitlocker),
  (True, [], {}))

# la orden y el lanzador de verdad
equipo.buzon().unlink(missing_ok=True)
sys.argv = ["agente.py", "desbloquear", A]
agente.main()
c("`agente.py desbloquear ID` deja la petición en el buzón",
  [(p["pide"], p["id"]) for p in equipo.recoger()], [(equipo.PIDE_DESBLOQUEAR, A)])
orden_de_verdad = bitlocker.orden_desbloquear
F.LANZADOS.clear()
try:
    bitlocker.orden_desbloquear = lambda raiz: ["bdeunlock.exe", "E:\\"]
    proceso = lanzador_de_verdad(E)
    c("el lanzador de verdad: la orden de Windows tal cual, desde la carpeta del agente",
      ([p.args for p in F.LANZADOS], proceso in F.LANZADOS, proceso.kwargs.get("cwd")),
      ([["bdeunlock.exe", "E:\\"]], True, str(equipo.DIR)))
    bitlocker.orden_desbloquear = lambda raiz: None
    c("  sin orden (no es Windows, o no trae bdeunlock.exe), ni proceso ni lanzamiento",
      (lanzador_de_verdad(E), len(F.LANZADOS)), (None, 1))
finally:
    bitlocker.orden_desbloquear = orden_de_verdad

sys.exit(c.report())
