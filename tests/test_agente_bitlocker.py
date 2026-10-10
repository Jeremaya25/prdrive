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
"""

import sys
from pathlib import Path

from _harness import Checks, tmpdir

import _agente_falso as F
import agente
import penwatch
from common import bitlocker, cifrada, equipo

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


bitlocker.volumen_de = lambda raiz, es_win=True: VOLUMENES.get(Path(raiz), "")
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

sys.exit(c.report())
