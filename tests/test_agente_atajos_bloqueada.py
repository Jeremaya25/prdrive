#!/usr/bin/env python3
"""Los atajos de abrir la carpeta o la ventana de una unidad bloqueada: primero se desbloquea.

Con un equipo de mentira (`_agente_falso`): el nombre de volumen y el estado de
BitLocker de cada raíz, la ventana de desbloqueo de Windows, el VeraCrypt de una
unidad cerrada (`agente.abrir_contenedor`) y el explorador están sustituidos.
Se comprueba:
- Una unidad de la lista bloqueada con BitLocker: el atajo de «Abrir su
  carpeta» pide la ventana de desbloqueo de Windows (una sola, aunque ya la
  hubiera pedido «Desbloquear…») y, al verla abierta, abre su carpeta; el de
  «Abrir su ventana», su ventana. Cuenta como usada. Si no se desbloquea en
  `ESPERA_ABRIR`, se olvida: abrirla después no abre nada.
- Una unidad de VeraCrypt de la lista con el contenedor cerrado: el atajo le
  pide a VeraCrypt que la abra (no otra vez si se acaba de pedir, también si
  lo pidió el agente al enchufarla) y, abierta, abre su carpeta. Sin VeraCrypt
  con que abrirla, se avisa. `resumen()["vestibulos"]` dice cuáles hay.
- Una que, desbloqueada, resulta tener otro código: no se abre nada suyo.
- La raíz cifrada de este equipo, cerrada: VeraCrypt pide su contraseña y,
  abierta, sale su carpeta (lo que ya hacía «Abrir en explorador…»).
- El de sincronizar no desbloquea nada.
"""

import shutil
import sys
from pathlib import Path

from _harness import Checks, tmpdir

import _agente_falso as F
import agente
import penwatch
from common import bitlocker, cifrada, equipo, store, vestibulo
from ui import atajos

c = Checks("atajos de teclado con la unidad bloqueada")
F.preparar()
EXPLORADAS: list = []
agente.explorar = lambda ruta: EXPLORADAS.append(Path(ruta)) or True

A, B = "a" * 32, "b" * 32
V1 = "\\\\?\\volume{11111111-1111-1111-1111-111111111111}\\"
VOLUMENES: dict[Path, str] = {}
"""El nombre de volumen de cada raíz; sin entrada, Windows no lo da."""
ESTADOS: dict[Path, int] = {}
"""El estado de BitLocker (`BDE_*`) de cada raíz; sin entrada, sin comprobar."""
DESBLOQUEOS: list[Path] = []
"""Las raíces para las que se ha pedido la ventana de desbloqueo de Windows."""
PROCESOS: list[F.Proc] = []
"""Los `bdeunlock.exe` de mentira, que siguen abiertos mientras su `rc` sea `None`."""


def bitlocker_falso(raiz) -> bitlocker.BitLockerStatus:
    """Contesta por Windows con lo que diga `ESTADOS`."""
    if Path(raiz) in ESTADOS:
        return bitlocker.BitLockerStatus(True, ESTADOS[Path(raiz)])
    return bitlocker.BitLockerStatus(False, detail="sin comprobar")


def desbloqueo_falso(raiz):
    """Hace de `agente.desbloquear_bitlocker()`: abre una ventana de mentira."""
    DESBLOQUEOS.append(Path(raiz))
    PROCESOS.append(F.Proc(["bdeunlock.exe", str(raiz)]))
    return PROCESOS[-1]


bitlocker.volumen_de = lambda raiz, es_win=True: VOLUMENES.get(Path(raiz), "")
cifrada.bitlocker_de = bitlocker_falso
agente.desbloquear_bitlocker = desbloqueo_falso


def pulsar(ag, accion, vueltas=1):
    """Pulsa un atajo y da las vueltas que se digan, sin recorrer en la primera."""
    ag.pedir({"pide": equipo.PIDE_ATAJO, "accion": accion})
    F.vueltas(ag, 1, recorrer=False)
    F.vueltas(ag, vueltas - 1)


def ventanas(raiz: Path) -> list:
    """Las ventanas de runsync lanzadas para esa raíz."""
    return [p for p in F.LANZADOS if p.args[1:] == [str(raiz / agente.APP_SUBDIR / "runsync.py")]]


def acabar_pasadas(raiz: Path) -> None:
    """Acaba las pasadas en marcha de esa raíz, para poder bloquearla con la unidad puesta."""
    for pasada in F.pasadas(raiz):
        if pasada.rc is None:
            F.acabar(pasada)


# --- BitLocker
RA = F.unidad(A, parejas=("docs",), nombre="Trabajo")
equipo.guardar_ajustes(equipo.Ajustes().con_unidad(
    equipo.Unidad(A, equipo.DAEMON, "Trabajo", codigo=agente.huella(RA) or "", volumen=V1)))
E = tmpdir("prdrive-letra-")            # su letra, bloqueada: dentro no se ve nada
VOLUMENES[E], ESTADOS[E] = V1, bitlocker.BDE_LOCKED
VOLUMENES[RA], ESTADOS[RA] = V1, bitlocker.BDE_ON


def bloquear(ag) -> None:
    """La unidad se ve bloqueada en su letra."""
    acabar_pasadas(RA)
    F.vueltas(ag, 1)
    F.RAICES[:] = [E]
    F.vueltas(ag, 1)


def desbloquear(ag) -> None:
    """Se teclea la contraseña: la unidad se lee y se conecta."""
    F.RAICES[:] = [RA]
    F.vueltas(ag, 4)


F.RAICES[:] = [E]
ag = F.nuevo()
F.vueltas(ag, 1)
F.DIARIO.clear()
F.AVISOS.clear()
pulsar(ag, atajos.CARPETA)
c("abrir su carpeta con ella bloqueada con BitLocker: Windows pide la contraseña",
  (DESBLOQUEOS, EXPLORADAS, F.AVISOS), ([E], [], []))
c("  el diario dice sobre cuál, y que está bloqueada",
  [d for d in F.DIARIO if d.startswith("atajo")], ["atajo «Abrir su carpeta»: Trabajo (bloqueada)"])
c("  y cuenta como usada", A in ag.usadas, True)
desbloquear(ag)
c("desbloqueada, se conecta y sale su carpeta, no su ventana",
  (A in ag.conexiones, EXPLORADAS, ventanas(RA)), (True, [RA], []))
c("  y no se queda nada pendiente", ag.al_abrirse, {})
F.vueltas(ag, 3)
c("  una vez", EXPLORADAS, [RA])

bloquear(ag)
c("(bloqueada otra vez con la unidad puesta)", A in ag.conexiones, False)
pulsar(ag, atajos.VENTANA)
desbloquear(ag)
c("abrir su ventana con ella bloqueada: la contraseña y, desbloqueada, su ventana",
  (DESBLOQUEOS, len(ventanas(RA)), EXPLORADAS), ([E, E], 1, [RA]))

bloquear(ag)
equipo.pedir({"pide": equipo.PIDE_DESBLOQUEAR, "id": A})   # «Desbloquear…» de la bandeja
F.vueltas(ag, 1, recorrer=False)
pulsar(ag, atajos.CARPETA)
c("con la ventana de Windows ya abierta no pide otra", DESBLOQUEOS, [E, E, E])
desbloquear(ag)
c("  pero desbloqueada sí abre su carpeta", EXPLORADAS, [RA, RA])

bloquear(ag)
pulsar(ag, atajos.CARPETA)
PROCESOS[-1].rc = 1                     # se cierra la ventana sin desbloquear
F.DIARIO.clear()
F.pasar(agente.ESPERA_ABRIR)
F.vueltas(ag, 1)
c("sin desbloquearla en el plazo, se olvida y se dice",
  (ag.al_abrirse, any("ya no abro" in d for d in F.DIARIO)), ({}, True))
desbloquear(ag)
c("  y desbloqueada después no abre nada", (A in ag.conexiones, EXPLORADAS), (True, [RA, RA]))

bloquear(ag)
pulsar(ag, atajos.CARPETA)
(RA / agente.APP_SUBDIR / "de_mas.py").write_text("# otro código\n", encoding="utf-8")
preguntas = len(F.preguntas())
desbloquear(ag)
c("desbloqueada con otro código: se pregunta y no se abre nada suyo",
  (ag.conexiones[A].cambiada, len(F.preguntas()) - preguntas, EXPLORADAS),
  (True, 1, [RA, RA]))
(RA / agente.APP_SUBDIR / "de_mas.py").unlink()
F.preguntas()[-1].rc = 0                # el sí: se sigue atendiendo
F.vueltas(ag, 2)

bloquear(ag)
avisos, pedidos = len(F.AVISOS), len(DESBLOQUEOS)
pulsar(ag, atajos.SINCRONIZAR)
c("sincronizar con ella bloqueada no desbloquea nada: lo dice",
  (len(DESBLOQUEOS) - pedidos, [t for t, _x in F.AVISOS[avisos:]]),
  (0, ["prdrive: no hay ninguna unidad a mano"]))

# --- VeraCrypt: una unidad de la lista con el contenedor cerrado
VU = "9" * 32
FIS = tmpdir("prdrive-fisica-")
(FIS / penwatch.VESTIBULE_MARKER).write_text(f"id={VU}\n", encoding="utf-8")
(FIS / penwatch.CONTAINER_FILE).write_bytes(b"")
DENTRO = F.unidad(VU, parejas=("docs",), nombre="Viaje")


def cerrada(**mas):
    """Devuelve un agente recién arrancado que ve la unidad de VeraCrypt cerrada."""
    equipo.guardar_ajustes(equipo.Ajustes().con_unidad(
        equipo.Unidad(VU, equipo.DAEMON, "Viaje", codigo=agente.huella(DENTRO) or "", **mas)))
    F.ABIERTOS.clear()
    EXPLORADAS.clear()
    F.RAICES[:] = [FIS]
    nuevo = F.nuevo()
    F.vueltas(nuevo, 4)
    return nuevo


ag = cerrada(pedir_al_conectar=False)
c("cerrada y sin abrirse sola: el resumen la cuenta, y VeraCrypt no ha pedido nada",
  (ag.resumen()["vestibulos"], F.ABIERTOS),
  ([{"id": VU, "nombre": "Viaje", "raiz": str(FIS)}], []))
pulsar(ag, atajos.CARPETA)
c("abrir su carpeta: VeraCrypt pide la contraseña de su contenedor", F.ABIERTOS, [FIS])
pulsar(ag, atajos.CARPETA)
c("  pulsado otra vez enseguida, no la vuelve a pedir", F.ABIERTOS, [FIS])
F.RAICES[:] = [FIS, DENTRO]
F.vueltas(ag, 4)
c("abierta, se conecta y sale su carpeta", (VU in ag.conexiones, EXPLORADAS), (True, [DENTRO]))
c("  y ya no sale como cerrada", ag.resumen()["vestibulos"], [])

ag = cerrada()
c("con «Pedir la contraseña al conectarla», VeraCrypt ya la pidió al enchufarla", F.ABIERTOS, [FIS])
pulsar(ag, atajos.CARPETA)
c("  el atajo enseguida no la vuelve a pedir", F.ABIERTOS, [FIS])
F.pasar(agente.GRACIA_ABRIR)
pulsar(ag, atajos.CARPETA)
c("  pasado un rato (se cerró sin abrirla), sí", F.ABIERTOS, [FIS, FIS])

ag = cerrada(pedir_al_conectar=False)
agente.abrir_contenedor = lambda raiz: False
F.AVISOS.clear()
pulsar(ag, atajos.CARPETA)
c("sin VeraCrypt con que abrirla: lo dice, y no queda nada pendiente",
  ([t for t, _x in F.AVISOS], ag.al_abrirse), (["Viaje: no puedo pedir su contraseña"], {}))
agente.abrir_contenedor = lambda raiz: F.ABIERTOS.append(Path(raiz)) or True

equipo.guardar_ajustes(equipo.Ajustes().con_unidad(
    equipo.Unidad(VU, equipo.NADA, "Viaje", codigo=agente.huella(DENTRO) or "")))
ag.ajustes = equipo.leer_ajustes()
F.ABIERTOS.clear()
pulsar(ag, atajos.CARPETA)
c("en modo `nada` no cuenta: ni sale en el resumen ni se abre",
  (ag.resumen()["vestibulos"], F.ABIERTOS), ([], []))

# --- la raíz cifrada de este equipo, cerrada (Linux fingido, como en test_agente_veracrypt.py)
penwatch.candidate_roots = lambda cfg: ([Path(r) for r in cfg.get("extra_roots", [])]
                                        + list(F.RAICES))
VC = "/opt/veracrypt/veracrypt"
penwatch.installed_veracrypt = lambda: VC
penwatch._con_escritorio = lambda: True
vestibulo.retenido = lambda hc: None
LINUX_FINGIDO = (penwatch.IS_WIN, agente.IS_WIN, equipo.Unidad.letra)
penwatch.IS_WIN = agente.IS_WIN = False
equipo.Unidad.letra = property(lambda self: "")
try:
    UID = "c" * 32
    HC = tmpdir("prdrive-cifrado-") / vestibulo.CONTENEDOR
    HC.write_bytes(b"\0" * 512)
    PUNTO = tmpdir("prdrive-punto-")
    equipo.guardar_ajustes(equipo.Ajustes(pedir_al_iniciar=False).con_unidad(
        equipo.Unidad(UID, equipo.DAEMON, "Mi portátil", str(PUNTO), str(HC))))
    F.RAICES[:] = []
    EXPLORADAS.clear()
    F.LANZADOS.clear()
    ag = F.nuevo()
    F.vueltas(ag, 3)
    pulsar(ag, atajos.CARPETA)
    c("la raíz cifrada cerrada: VeraCrypt pide su contraseña",
      [p.args for p in F.LANZADOS if p.args[0] == VC], [[VC, str(HC), str(PUNTO)]])
    app = PUNTO / penwatch.APP_SUBDIR
    (app / "state").mkdir(parents=True)
    (app / "PRDRIVE").write_text(f"id={UID}\ntipo=equipo\n", encoding="utf-8")
    (app / "VERSION").write_text(F.VERSION + "\n", encoding="utf-8")
    for py in ("runsync.py", "sync.py"):
        (app / py).write_text("# de mentira\n", encoding="utf-8")
    (app / "sync_config.toml").write_text(
        '[defaults]\nremote = "nas"\n\n[[pair]]\nname = "notas"\nlocal = "notas"\n'
        'remote_path = "/R/notas"\n', encoding="utf-8")
    store.write_json(app / "state" / "fleet.json", {"nombre": "Mi portátil"})
    F.vueltas(ag, 3)
    c("  abierta, sale su carpeta", (UID in ag.conexiones, EXPLORADAS), (True, [PUNTO]))
    shutil.rmtree(app)
finally:
    penwatch.IS_WIN, agente.IS_WIN, equipo.Unidad.letra = LINUX_FINGIDO

sys.exit(c.report())
