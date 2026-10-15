#!/usr/bin/env python3
"""«Pedir la contraseña al conectarla»: un ajuste por unidad de la lista (#123).

Con un sistema de mentira (`_agente_falso`): las unidades de VeraCrypt son una
raíz física con su marca de vestíbulo y su `.hc` al lado, y la ventana de
desbloqueo de Windows (`agente.desbloquear_bitlocker`), el nombre de volumen de
cada raíz y su estado de BitLocker están sustituidos. Se comprueba:
- `agente.json` guarda `Unidad.pedir_al_conectar` (verdadero, falso o «lo de
  siempre»), uno de antes carga igual y lo que no es un booleano se descarta.
  Lo de siempre depende del tipo: VeraCrypt sí, BitLocker no.
- El ajuste se pide por el buzón (`PIDE_AJUSTE_UNIDAD`), solo de una unidad de
  la lista que no sea una raíz del equipo, con un booleano o `None`; sobrevive
  a reiniciar el agente.
- VeraCrypt: sin decir nada, o en verdadero, se abre sola una vez por conexión
  como siempre; en falso no se le pide nada a VeraCrypt, pero se apunta como
  tratada: no se reintenta en esa conexión.
- BitLocker: sin decir nada, o en falso, no sale nada (como siempre); en
  verdadero, la primera vez que se ve enchufada y bloqueada, también al
  arrancar el agente, sale la ventana de Windows, una sola vez por conexión. Si
  se cancela no se insiste; desenchufada y vuelta a enchufar, sí.
- `resumen()` dice de cada unidad su tipo de cifrado y el valor que de verdad
  tiene el ajuste, y la bandeja dibuja su casilla.
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
from ui import bandeja

c = Checks("pedir la contraseña al conectar una unidad cifrada")
F.preparar()

A, B, Q = "a" * 32, "b" * 32, "q" * 32
V, BL = equipo.CIFRADO_VERACRYPT, equipo.CIFRADO_BITLOCKER


# --- agente.json
def ida_y_vuelta(u: equipo.Unidad) -> equipo.Unidad:
    """Devuelve la unidad tras escribirla en el dict de `agente.json` y leerla."""
    return equipo.desde_dict(equipo.a_dict(equipo.Ajustes(unidades={u.id: u}))).unidades[u.id]


def cruda(valor, **mas):
    """Devuelve el `pedir_al_conectar` que sale de un `agente.json` con ese valor tal cual."""
    return equipo.desde_dict(
        {"unidades": {A: {"pedir_al_conectar": valor, **mas}}}).unidades[A].pedir_al_conectar


def escrita(u: equipo.Unidad) -> dict:
    """Devuelve cómo queda esa unidad en el dict de `agente.json`."""
    return equipo.a_dict(equipo.Ajustes(unidades={u.id: u}))["unidades"][u.id]


c("sin decir nada, la unidad se queda con «lo de siempre»",
  equipo.Unidad(A).pedir_al_conectar, None)
c("agente.json: verdadero y falso van y vuelven",
  [ida_y_vuelta(equipo.Unidad(A, pedir_al_conectar=v)).pedir_al_conectar for v in (True, False)],
  [True, False])
c("  sin valor no se escribe la clave", "pedir_al_conectar" in escrita(equipo.Unidad(A)), False)
c("  y falso sí: no se confunde con «sin valor»",
  escrita(equipo.Unidad(A, pedir_al_conectar=False)).get("pedir_al_conectar"), False)
c("  un agente.json de antes se lee igual",
  equipo.desde_dict({"unidades": {A: {"modo": "daemon"}}}).unidades[A].pedir_al_conectar, None)
c("  lo que no es un booleano se descarta y la unidad sigue",
  [cruda(v) for v in ("sí", "true", 1, 0, [], {}, None)], [None] * 7)
c("  una raíz de este equipo no lo lleva", cruda(True, ruta="/algo"), None)
c("  lo demás de la unidad no cambia",
  ida_y_vuelta(equipo.Unidad(A, equipo.SYNC, "Trabajo", volumen="", pedir_al_conectar=True)),
  equipo.Unidad(A, equipo.SYNC, "Trabajo", pedir_al_conectar=True))

# Lo de siempre depende del tipo: VeraCrypt se abre sola, BitLocker no.
combinaciones = [(valor, tipo) for valor in (None, True, False) for tipo in (V, BL)]
c("el valor que de verdad tiene: lo dicho, y sin decir nada VeraCrypt sí y BitLocker no",
  {k: equipo.Unidad(A, pedir_al_conectar=k[0]).pide_al_conectar(k[1]) for k in combinaciones},
  {(None, V): True, (None, BL): False, (True, V): True, (True, BL): True,
   (False, V): False, (False, BL): False})


# --- el buzón: un ajuste de UNA unidad
def en_disco(uid: str) -> bool | None:
    """Devuelve el `pedir_al_conectar` que `agente.json` tiene de esa unidad."""
    return equipo.leer_ajustes().unidades[uid].pedir_al_conectar


def pedir_ajuste(ag, uid, valor, clave: str = "pedir_al_conectar") -> None:
    """Deja un ajuste de unidad en el buzón del agente y da una vuelta."""
    equipo.pedir({"pide": equipo.PIDE_AJUSTE_UNIDAD, "id": uid, "clave": clave, "valor": valor})
    F.vueltas(ag, 1, recorrer=False)


c("es una petición del agente, no del buzón de una raíz",
  (equipo.PIDE_AJUSTE_UNIDAD in equipo.PIDE_SERVICIO, equipo.PIDE_AJUSTE_UNIDAD
   == "ajuste_unidad"), (False, True))
c("  y su ajuste no es de los globales (`PIDE_AJUSTE`)",
  ("pedir_al_conectar" in equipo.AJUSTES_PEDIBLES, equipo.AJUSTES_DE_UNIDAD),
  (False, ("pedir_al_conectar",)))

RAIZ_Q = tmpdir("prdrive-raiz-equipo-")
equipo.guardar_ajustes(equipo.Ajustes()
                       .con_unidad(equipo.Unidad(A, equipo.DAEMON, "Uno"))
                       .con_unidad(equipo.Unidad(B, equipo.DAEMON, "Dos",
                                                 pedir_al_conectar=True))
                       .con_unidad(equipo.Unidad(Q, equipo.DAEMON, "Mi portátil", str(RAIZ_Q))))
ag = F.nuevo()
F.DIARIO.clear()
pedir_ajuste(ag, A, False)
c("el agente guarda el ajuste de esa unidad y de ninguna otra",
  (en_disco(A), en_disco(B), en_disco(Q)), (False, True, None))
c("  y lo dice en el diario", F.DIARIO, ["Uno: ajuste pedir_al_conectar = False"])
c("  sobrevive a reiniciar el agente", F.nuevo().ajustes.unidades[A].pedir_al_conectar, False)
pedir_ajuste(ag, A, True)
c("  se puede cambiar", en_disco(A), True)
pedir_ajuste(ag, A, None)
c("  y volver a lo de siempre: la clave se va de agente.json",
  (en_disco(A), "pedir_al_conectar" in store.read_json(equipo.ajustes_json())["unidades"][A]),
  (None, False))

antes = store.read_json(equipo.ajustes_json())
F.DIARIO.clear()
rechazadas = [(A, "sync", "modo"), (A, "sí", "pedir_al_conectar"), (A, 1, "pedir_al_conectar"),
              (A, "false", "pedir_al_conectar"), ("z" * 32, True, "pedir_al_conectar"),
              (Q, False, "pedir_al_conectar"), ("", True, "pedir_al_conectar")]
for uid, valor, clave in rechazadas:
    pedir_ajuste(ag, uid, valor, clave)
equipo.pedir({"pide": equipo.PIDE_AJUSTE, "clave": "pedir_al_conectar", "valor": False})
F.vueltas(ag, 1, recorrer=False)
c("lo que no vale no toca nada: otra clave, algo que no es sí/no/lo de siempre, una unidad "
  "que no está o una raíz del equipo, ni por el ajuste global",
  store.read_json(equipo.ajustes_json()), antes)
c("  y cada petición rechazada deja su línea en el diario", len(F.DIARIO), len(rechazadas) + 1)


# --- VeraCrypt: se abre sola, una vez por conexión, salvo que se diga que no
def vestibulo_de(uid: str):
    """Devuelve una unidad de VeraCrypt de mentira: su raíz física y el volumen de dentro.

    La física lleva la marca del vestíbulo y el `.hc` al lado, y está a la vista
    abierta o cerrada; el volumen de dentro es el que se monta al abrirla.
    """
    fisica = tmpdir("prdrive-fisica-")
    (fisica / penwatch.VESTIBULE_MARKER).write_text(f"id={uid}\n", encoding="utf-8")
    (fisica / penwatch.CONTAINER_FILE).write_bytes(b"")
    return fisica, F.unidad(uid, parejas=("docs",), nombre="Cifrada")


VU = "9" * 32
FIS, DENTRO = vestibulo_de(VU)


def con_vestibulo(vueltas: int = 4, **mas):
    """Devuelve un agente recién arrancado que ve la unidad de VeraCrypt cerrada.

    Args:
        vueltas: Las que se le dan nada más arrancar.
        **mas: Campos de la unidad en `agente.json`.
    """
    equipo.guardar_ajustes(equipo.Ajustes().con_unidad(
        equipo.Unidad(VU, equipo.DAEMON, "Cifrada", **mas)))
    F.ABIERTOS.clear()
    F.DIARIO.clear()
    F.RAICES[:] = [FIS]
    ag = F.nuevo()
    F.vueltas(ag, vueltas)
    return ag


def sin_abrir_sola() -> int:
    """Devuelve las veces que el diario ha dicho que no se abre sola."""
    return len([d for d in F.DIARIO if "no se abre sola" in d])


for como, mas in (("sin decir nada", {}), ("en verdadero", {"pedir_al_conectar": True})):
    ag = con_vestibulo(**mas)
    c(f"VeraCrypt {como}: se le pide que la abra, como siempre", F.ABIERTOS, [FIS])
    F.vueltas(ag, 4)
    c("  una vez por conexión (si se cancela, no se insiste)", F.ABIERTOS, [FIS])

ag = con_vestibulo(pedir_al_conectar=False)
c("VeraCrypt en falso: no se le pide nada", F.ABIERTOS, [])
c("  pero la conexión queda tratada: no se reintenta ni se vuelve a contar",
  ag.vestibulos, {VU: str(FIS)})
F.vueltas(ag, 5)
c("  por muchas vueltas que pasen, y el diario lo dice una vez",
  (F.ABIERTOS, sin_abrir_sola()), ([], 1))
F.RAICES[:] = [FIS, DENTRO]
F.vueltas(ag, 4)
c("  abierta a mano (con «Abrir PRDRIVE» de la unidad), se atiende como cualquier otra",
  (VU in ag.conexiones, F.lock(DENTRO).get("pid"), F.ABIERTOS), (True, os.getpid(), []))
F.RAICES[:] = [FIS]
F.vueltas(ag, 5)
c("  cerrada con la unidad puesta («Expulsar»): sigue sin abrirse", F.ABIERTOS, [])
F.RAICES[:] = []
F.vueltas(ag, 2)
F.RAICES[:] = [FIS]
F.vueltas(ag, 4)
c("  y desenchufada y vuelta a enchufar, también: el ajuste es del equipo",
  (F.ABIERTOS, sin_abrir_sola()), ([], 2))

# El valor que cuenta es el de cuando le toca: tras verla estable.
ag = con_vestibulo(vueltas=1)
pedir_ajuste(ag, VU, False)
F.vueltas(ag, 4)
c("apagarlo antes de que la dé por estable: no se abre", F.ABIERTOS, [])
ag = con_vestibulo(pedir_al_conectar=False)
pedir_ajuste(ag, VU, True)
F.vueltas(ag, 4)
c("encenderlo con la unidad ya tratada: en esa conexión no se abre", F.ABIERTOS, [])
F.RAICES[:] = []
F.vueltas(ag, 2)
F.RAICES[:] = [FIS]
F.vueltas(ag, 4)
c("  desenchufada y vuelta a enchufar, sí", F.ABIERTOS, [FIS])


# --- BitLocker: la ventana de Windows al verla enchufada y bloqueada, una vez por conexión
V1 = "\\\\?\\volume{11111111-1111-1111-1111-111111111111}\\"
V2 = "\\\\?\\volume{22222222-2222-2222-2222-222222222222}\\"
VOLUMENES: dict[Path, str] = {}
"""El nombre de volumen de cada raíz; sin entrada, Windows no lo da."""
ESTADOS: dict[Path, int] = {}
"""El estado de BitLocker (`BDE_*`) de cada raíz; sin entrada, sin comprobar."""
VENTANAS: list[Path] = []
"""Las raíces para las que se ha pedido la ventana de desbloqueo de Windows."""
PROCESOS: list[F.Proc] = []
"""Los `bdeunlock.exe` de mentira, abiertos hasta que el test les ponga un código."""
RESPUESTA = ["ventana"]
"""Qué pasa al pedirla: `ventana`, `nada` (no hay con qué) o `error` (no arranca)."""
SIN_VENTANA = ("Trabajo: no he podido abrir el desbloqueo de Windows",
               "Desbloquéala desde el Explorador.")


def desbloqueo_falso(raiz):
    """Hace de `agente.desbloquear_bitlocker()` sin lanzar nada."""
    VENTANAS.append(Path(raiz))
    if RESPUESTA[0] == "nada":
        return None
    if RESPUESTA[0] == "error":
        raise OSError("no arranca")
    PROCESOS.append(F.Proc(["bdeunlock.exe", str(raiz)]))
    return PROCESOS[-1]


bitlocker.volumen_de = lambda raiz, es_win=True: VOLUMENES.get(Path(raiz), "")
cifrada.bitlocker_de = lambda raiz: (
    bitlocker.BitLockerStatus(True, ESTADOS[Path(raiz)]) if Path(raiz) in ESTADOS
    else bitlocker.BitLockerStatus(False, detail="sin comprobar"))
agente.desbloquear_bitlocker = desbloqueo_falso

RA = F.unidad(A, parejas=("docs",), nombre="Trabajo")       # su letra, desbloqueada
RB = F.unidad(B, parejas=("docs",), nombre="Otra")
E = tmpdir("prdrive-letra-")                                # su letra, bloqueada
E2 = tmpdir("prdrive-letra-otra-")
VOLUMENES.update({RA: V1, E: V1, RB: V2, E2: V2})
ESTADOS.update({RA: bitlocker.BDE_ON, E: bitlocker.BDE_LOCKED,
                RB: bitlocker.BDE_ON, E2: bitlocker.BDE_LOCKED})


def unidades_bitlocker(*, modo: str = equipo.DAEMON, **mas) -> equipo.Ajustes:
    """Devuelve unos ajustes con «Trabajo» (BitLocker, volumen apuntado) y esos campos."""
    return equipo.Ajustes().con_unidad(equipo.Unidad(
        A, modo, "Trabajo", codigo=agente.huella(RA) or "", volumen=V1, **mas))


def con_bitlocker(*raices: Path, ajustes: equipo.Ajustes | None = None, **mas):
    """Devuelve un agente recién arrancado que ve esas raíces, tras su primera vuelta.

    Args:
        *raices: Lo que «encuentra» el recorrido.
        ajustes: Los ajustes del equipo; por defecto, solo «Trabajo».
        **mas: Campos de «Trabajo» (`modo`, `pedir_al_conectar`).
    """
    equipo.guardar_ajustes(ajustes or unidades_bitlocker(**mas))
    for apuntado in (VENTANAS, PROCESOS, F.AVISOS, F.DIARIO, F.LANZADOS):
        apuntado.clear()
    RESPUESTA[0] = "ventana"
    F.RAICES[:] = list(raices)
    ag = F.nuevo()
    F.vueltas(ag, 1)
    return ag


def desenchufar_y_enchufar(ag, *raices: Path) -> None:
    """Quita todas las unidades un recorrido y vuelve a poner esas."""
    F.RAICES[:] = []
    F.vueltas(ag, 2)
    F.RAICES[:] = list(raices)
    F.vueltas(ag, 2)


def bloqueadas(ag) -> list[str]:
    """Devuelve los ids que el resumen da por bloqueadas con BitLocker."""
    return [b["id"] for b in ag.resumen()["bitlocker"]]


for como, mas in (("sin decir nada", {}), ("en falso", {"pedir_al_conectar": False})):
    ag = con_bitlocker(E, **mas)
    F.vueltas(ag, 6)
    c(f"BitLocker {como}: enchufada y bloqueada, no sale ninguna ventana, como siempre",
      (bloqueadas(ag), VENTANAS), ([A], []))

ag = con_bitlocker(E, pedir_al_conectar=True)
c("BitLocker en verdadero, con el agente recién arrancado (iniciar sesión con ella puesta): "
  "sale la ventana de Windows de su letra", VENTANAS, [E])
c("  y el resumen dice que se está desbloqueando",
  [b["desbloqueando"] for b in ag.resumen()["bitlocker"]], [True])
F.vueltas(ag, 6)
c("  mientras siga abierta no sale otra", VENTANAS, [E])
PROCESOS[-1].rc = 1                     # se cierra la ventana sin desbloquear
F.vueltas(ag, 8)
c("  si se cancela, sigue bloqueada y no se insiste", (bloqueadas(ag), VENTANAS), ([A], [E]))
equipo.pedir({"pide": equipo.PIDE_DESBLOQUEAR, "id": A})
F.vueltas(ag, 1)
c("  pero «Desbloquear…» a mano sigue pudiendo", VENTANAS, [E, E])
PROCESOS[-1].rc = 1
desenchufar_y_enchufar(ag, E)
c("  desenchufada y vuelta a enchufar, sale otra vez, y una sola", VENTANAS, [E, E, E])

# Es una ventana de Windows y no un aviso: no se pregunta a la moderación.
ag = con_bitlocker(E, pedir_al_conectar=True)
ag.pausado = True
F.vueltas(ag, 2)
c("  la pausa del agente no la frena (no es un aviso, es una ventana del sistema)",
  VENTANAS, [E])

# Desbloqueada y vuelta a bloquear con la unidad puesta (por ejemplo, tras «Expulsar»).
ag = con_bitlocker(RA, pedir_al_conectar=True)
F.vueltas(ag, 4)
for pasada in F.pasadas(RA):            # que no quede una pasada a medias
    F.acabar(pasada)
F.RAICES[:] = [E]
F.vueltas(ag, 4)
c("conectada y luego bloqueada con la unidad puesta: la ventana no vuelve sola",
  (A in ag.conexiones, bloqueadas(ag), VENTANAS), (False, [A], []))
desenchufar_y_enchufar(ag, E)
c("  desenchufada y vuelta a enchufar, sí", VENTANAS, [E])

# El valor que cuenta es el del primer recorrido de la conexión.
ag = con_bitlocker(E)
pedir_ajuste(ag, A, True)
F.vueltas(ag, 4)
c("encenderlo con la unidad ya vista bloqueada: en esa conexión no sale", VENTANAS, [])
desenchufar_y_enchufar(ag, E)
c("  desenchufada y vuelta a enchufar, sí", VENTANAS, [E])

# Si Windows no abre la ventana, se avisa una vez y no se reintenta cada recorrido.
RESPUESTA[0] = "nada"
equipo.guardar_ajustes(unidades_bitlocker(pedir_al_conectar=True))
for apuntado in (VENTANAS, F.AVISOS):
    apuntado.clear()
F.RAICES[:] = [E]
ag = F.nuevo()
F.vueltas(ag, 8)
c("si Windows no la abre: un intento, un aviso de cómo hacerlo a mano",
  (VENTANAS, F.AVISOS), ([E], [SIN_VENTANA]))
RESPUESTA[0] = "ventana"

# Por unidad, y solo de las que se atienden.
dos = unidades_bitlocker(pedir_al_conectar=True).con_unidad(
    equipo.Unidad(B, equipo.DAEMON, "Otra", codigo=agente.huella(RB) or "", volumen=V2))
ag = con_bitlocker(E, E2, ajustes=dos)
F.vueltas(ag, 3)
c("con dos bloqueadas, la ventana sale solo para la que lo pide",
  (sorted(bloqueadas(ag)), VENTANAS), ([A, B], [E]))
ag = con_bitlocker(E, modo=equipo.NADA, pedir_al_conectar=True)
F.vueltas(ag, 4)
c("en modo `nada` no sale, aunque lo pida", (bloqueadas(ag), VENTANAS), ([], []))


# --- lo que el agente cuenta de cada unidad, y la casilla de la bandeja
CASILLA = "Pedir la contraseña al conectarla"


def fila_de(ag, uid: str) -> dict:
    """Devuelve la fila de esa unidad conectada en el resumen del agente."""
    return next(u for u in ag.resumen()["unidades"] if u["id"] == uid)


def desplegable(vista, rotulo: str):
    """Devuelve el desplegable de un dispositivo por su rótulo, o `None`."""
    return next((e for e in vista.menu if e.texto == rotulo and e.hijos), None)


def casilla_de(vista, rotulo: str):
    """Devuelve la casilla de «Pedir la contraseña al conectarla» de ese desplegable, o `None`."""
    return next((e for e in desplegable(vista, rotulo).hijos if e.texto == CASILLA), None)


def elegir(ag, entrada) -> None:
    """Lo que hace la bandeja al elegir una entrada: sus peticiones, al agente."""
    for peticion in entrada.pide:
        ag.pedir(dict(peticion))
    F.vueltas(ag, 1, recorrer=False)


C_ = "c" * 32
RC = F.unidad(C_, parejas=("docs",), nombre="Normal")

# VeraCrypt abierta: la física sigue a la vista con su marca, y eso la delata.
equipo.guardar_ajustes(equipo.Ajustes().con_unidad(
    equipo.Unidad(VU, equipo.DAEMON, "Cifrada")).con_unidad(
    equipo.Unidad(C_, equipo.DAEMON, "Normal")))
F.RAICES[:] = [FIS, DENTRO, RC]
ag = F.nuevo()
F.vueltas(ag, 5)
c("el resumen dice de una unidad conectada en un contenedor VeraCrypt cómo va cifrada y "
  "el valor que de verdad tiene su ajuste (sin decir nada, que sí)",
  (fila_de(ag, VU)["cifrado"], fila_de(ag, VU)["pedir_al_conectar"]), (V, True))
c("  y de una normal, que no lleva contraseña que pedir",
  (fila_de(ag, C_)["cifrado"], fila_de(ag, C_)["pedir_al_conectar"]), ("", False))
v = bandeja.vista(ag.resumen())
casilla = casilla_de(v, "Cifrada")
c("la bandeja le pone su casilla a la de VeraCrypt, marcada porque se abre sola, y pide lo "
  "contrario", (casilla.marcada, casilla.pide),
  (True, ({"pide": equipo.PIDE_AJUSTE_UNIDAD, "id": VU, "clave": "pedir_al_conectar",
           "valor": False},)))
c("  y no a la normal", [e.texto for e in desplegable(v, "Normal").hijos if e.texto == CASILLA], [])
elegir(ag, casilla)
c("  elegirla lo guarda el agente, y la casilla se desmarca",
  (en_disco(VU), casilla_de(bandeja.vista(ag.resumen()), "Cifrada").marcada), (False, False))
c("  y el resumen dice lo que de verdad hará",
  fila_de(ag, VU)["pedir_al_conectar"], False)
elegir(ag, casilla_de(bandeja.vista(ag.resumen()), "Cifrada"))
c("  volver a elegirla la vuelve a marcar", (en_disco(VU), fila_de(ag, VU)["pedir_al_conectar"]),
  (True, True))

# BitLocker conectada: sin decir nada, no se pide.
ag = con_bitlocker(RA)
F.vueltas(ag, 4)
c("una unidad con BitLocker conectada: cifrada con BitLocker y, sin decir nada, sin pedir",
  (fila_de(ag, A)["cifrado"], fila_de(ag, A)["pedir_al_conectar"]), (BL, False))
c("  y su casilla, desmarcada",
  casilla_de(bandeja.vista(ag.resumen()), "Trabajo").marcada, False)
for pasada in F.pasadas(RA):
    F.acabar(pasada)
ag = con_bitlocker(RA, pedir_al_conectar=True)
F.vueltas(ag, 4)
c("  y en verdadero, marcada y en el resumen",
  (casilla_de(bandeja.vista(ag.resumen()), "Trabajo").marcada,
   fila_de(ag, A)["pedir_al_conectar"]), (True, True))
for pasada in F.pasadas(RA):
    F.acabar(pasada)

# BitLocker bloqueada: su desplegable lleva «Desbloquear…» y la casilla.
ag = con_bitlocker(E)
c("la bloqueada con BitLocker dice en el resumen el valor del ajuste",
  [b["pedir_al_conectar"] for b in ag.resumen()["bitlocker"]], [False])
v = bandeja.vista(ag.resumen())
c("  y su desplegable lleva «Desbloquear…», que sigue siendo la entrada por defecto, y la casilla",
  ([e.texto for e in desplegable(v, "Trabajo (bloqueada)").hijos],
   desplegable(v, "Trabajo (bloqueada)").hijos[0].defecto),
  (["Desbloquear…", "", CASILLA], True))
elegir(ag, casilla_de(v, "Trabajo (bloqueada)"))
c("  elegir la casilla desde ahí la guarda también",
  (en_disco(A), casilla_de(bandeja.vista(ag.resumen()), "Trabajo (bloqueada)").marcada),
  (True, True))
c("  y en esa conexión no saca ninguna ventana", VENTANAS, [])

# Lo que no tiene contraseña que pedir, o no es de la lista, no lleva casilla.
resumen = {"unidades": [
    {"id": A, "nombre": "Lista", "en_lista": True, "atendida": True, "cifrado": V,
     "pedir_al_conectar": True},
    {"id": B, "nombre": "Normal", "en_lista": True, "atendida": True, "cifrado": "",
     "pedir_al_conectar": False},
    {"id": C_, "nombre": "Antigua", "en_lista": True, "atendida": True},
    {"id": "d" * 32, "nombre": "Sin atender", "en_lista": False, "ahora_no": True,
     "cifrado": V, "pedir_al_conectar": True},
    {"id": "e" * 32, "nombre": "Vieja", "en_lista": True, "a_medias": True, "cifrado": V,
     "pedir_al_conectar": True}]}
v = bandeja.vista(resumen)
c("la casilla va solo en las unidades cifradas de la lista: no en las normales, ni en un "
  "resumen sin el dato, ni en las que no se atienden (sin atender, por actualizar)",
  {e.texto: any(h.texto == CASILLA for h in e.hijos) for e in v.menu if e.hijos
   and e.texto in ("Lista", "Normal", "Antigua", "Sin atender (sin atender)",
                   "Vieja (por actualizar)")},
  {"Lista": True, "Normal": False, "Antigua": False, "Sin atender (sin atender)": False,
   "Vieja (por actualizar)": False})
c("  dentro del desplegable va tras sus acciones y antes de la versión",
  [e.texto for e in desplegable(v, "Lista").hijos],
  ["Configurar", "Abrir en explorador", "Sincronizar ahora", "", CASILLA])
v = bandeja.vista({"bitlocker": [
    {"id": A, "nombre": "Con dato", "raiz": "E:\\", "desbloqueando": False,
     "pedir_al_conectar": True},
    {"id": B, "nombre": "Sin dato", "raiz": "F:\\", "desbloqueando": False}]})
c("  y la bloqueada con BitLocker, igual: sin el dato del agente, solo «Desbloquear…»",
  {e.texto: [h.texto for h in e.hijos] for e in v.menu if e.hijos},
  {"Con dato (bloqueada)": ["Desbloquear…", "", CASILLA],
   "Sin dato (bloqueada)": ["Desbloquear…"]})


# --- `agente.py status`
def status() -> str:
    """Devuelve lo que imprime `agente.py status`, con el agente dado por vivo."""
    store.write_json(equipo.lock_json(), {"pid": os.getpid(), "host": agente.HOST})
    salida = io.StringIO()
    try:
        with contextlib.redirect_stdout(salida):
            agente.cmd_status(None)
    finally:
        equipo.lock_json().unlink()
    return salida.getvalue()


equipo.guardar_ajustes(equipo.Ajustes()
                       .con_unidad(equipo.Unidad(A, equipo.DAEMON, "Trabajo",
                                                 pedir_al_conectar=False))
                       .con_unidad(equipo.Unidad(B, equipo.DAEMON, "Otra")))
dicho = status()
c.contains("`status` dice, de la unidad a la que se le ha tocado el ajuste, qué hace",
           dicho, "al conectarla no se pide la contraseña")
c("  y de la que no, nada: sus equipos siguen viendo lo mismo", dicho.count("al conectarla"), 1)
equipo.guardar_ajustes(equipo.Ajustes().con_unidad(
    equipo.Unidad(VU, equipo.DAEMON, "Cifrada", pedir_al_conectar=True)))
F.RAICES[:] = [FIS, DENTRO]
ag = F.nuevo()
F.vueltas(ag, 5)
c.contains("  conectada, dice cómo va cifrada y si se pide al conectarla",
           status(), "Cifrada con VeraCrypt: al conectarla se pide la contraseña")

sys.exit(c.report())
