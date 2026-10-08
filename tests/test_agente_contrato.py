#!/usr/bin/env python3
"""El agente como servicio de una unidad, por los ficheros de su `state/`.

Los ficheros son los que ya existen, escritos como los escribiría un runsync
viejo: `daemon.lock.json`, `daemon.stop` y `ui.lock.json`.

Se comprueba el contrato de la sección 3 del diseño: toma el lock, obedece el
stop acabando la pareja en curso, se queda en pausa con la ventana abierta y un
rato después, se aparta ante otro servicio vivo, vuelve cuando se va, y no
cuenta como fallo una unidad desenchufada a mitad de pasada. Y lo que el agente
hace con cada pasada: dónde la lanza, cuándo avisa, el «sin conexión», los
modos, el buzón y el vestíbulo de una unidad VeraCrypt cerrada.
"""

import os
import threading
import time

from _harness import Checks

import _agente_falso as F
import agente
import penwatch
from common import equipo, planificador as pl, store

c = Checks("agente: el contrato del servicio")
F.preparar()

UID = "a" * 32
RAIZ = F.unidad(UID, nombre="PRDRIVE-2",
                daemon='[daemon]\ninterval_minutes = 10\n')
equipo.guardar_ajustes(equipo.Ajustes().con_unidad(equipo.Unidad(UID, equipo.DAEMON)))
F.RAICES[:] = [RAIZ]

ag = F.nuevo()
F.vueltas(ag, 1)
c("una sola vista no basta para darla por conectada", UID in ag.conexiones, False)
F.vueltas(ag, 1)
c("a la segunda, sí", UID in ag.conexiones, True)
c("con su nombre de la flota", ag.conexiones[UID].nombre, "PRDRIVE-2")
c("y se apunta el nombre en agente.json", equipo.leer_ajustes().unidades[UID].nombre,
  "PRDRIVE-2")
info = F.lock(RAIZ)
c("toma el daemon.lock.json de la unidad con su pid y este equipo",
  (info.get("pid"), info.get("host"), info.get("agente")), (os.getpid(), penwatch.HOST, True))
c("  con las parejas y el intervalo del servicio de la unidad",
  (info.get("pairs"), info.get("interval_min")), (["docs", "fotos"], 10.0))

primera = F.pasadas(RAIZ)
c("lanza una pasada, y una sola", len(primera), 1)
p = primera[0]
c("  es el sync.py DE LA UNIDAD, con una pareja detrás de un «--»", p.args[1:],
  [str(RAIZ / ".prdrive" / "sync.py"), "--", "docs"])
c("  con el directorio de trabajo fuera de la unidad", p.kwargs.get("cwd"), str(equipo.DIR))
c("  y sin entrada: una pareja que pide --resync se salta",
  p.kwargs.get("stdin"), agente.subprocess.DEVNULL)

F.vueltas(ag, 3)
c("mientras corre no se lanza otra (una cola para todo el equipo)",
  len(F.pasadas(RAIZ)), 1)

# runsync abre su ventana: daemon.stop
F.stop(RAIZ).touch()
F.vueltas(ag, 1)
c("con un stop y una pareja en curso, la acaba: el lock sigue",
  F.lock(RAIZ).get("pid"), os.getpid())
c("  y el stop también, hasta que acabe", F.stop(RAIZ).exists(), True)
F.acabar(p, 0, "[docs] OK.\n")
F.vueltas(ag, 1)
c("acabada, suelta el lock", F.lock(RAIZ), {})
c("  borra el stop", F.stop(RAIZ).exists(), False)
c("  y no lanza la siguiente", len(F.pasadas(RAIZ)), 1)
c("  lo dice en el diario de la unidad",
  "en pausa" in (RAIZ / ".prdrive" / "state" / "daemon.log").read_text(encoding="utf-8"),
  True)
c("la pareja acabada cuenta como buena", ag.marcas[(UID, "docs")].fallos, 0)

F.ventana_abierta(RAIZ)
F.vueltas(ag, 20)
c("con la ventana abierta, en pausa: nada de lock", F.lock(RAIZ), {})
c("  ni de pasadas", len(F.pasadas(RAIZ)), 1)
c("  y se dice por qué", ag.conexiones[UID].motivo,
  "en pausa: hay una ventana de runsync abierta")

(RAIZ / penwatch.UI_LOCK_REL).unlink()
F.vueltas(ag, 2)
c("cerrada la ventana, un rato de gracia antes de volver", F.lock(RAIZ), {})
F.vueltas(ag, 1, cada=agente.GRACIA)
F.vueltas(ag, 1)
c("pasada la gracia, vuelve a tomar el lock", F.lock(RAIZ).get("pid"), os.getpid())
c("  y lo dice, en su diario y en el de la unidad (la otra mitad de «en pausa»)",
  (sum("vuelvo a atenderla" in x for x in F.DIARIO),
   "reanudado" in (RAIZ / ".prdrive" / "state" / "daemon.log").read_text(encoding="utf-8")),
  (1, True))
c("  y sigue con la pareja pendiente", F.pasadas(RAIZ)[-1].args[-1], "fotos")
F.acabar(F.pasadas(RAIZ)[-1])
F.vueltas(ag, 1)

# la ventana arranca su propio servicio: el agente se aparta
F.stop(RAIZ).touch()
F.vueltas(ag, 1)
F.otro_servicio(RAIZ)                  # runsync --daemon, vivo en este equipo
F.vueltas(ag, 1, cada=agente.GRACIA + 1)
F.vueltas(ag, 5)
c("otro servicio vivo con el lock: el agente se aparta",
  F.lock(RAIZ).get("pid"), os.getppid())
c("  sin lanzar nada", len(F.pasadas(RAIZ)), 2)
c("  y lo dice", ag.conexiones[UID].motivo, f"la atiende otro servicio (pid {os.getppid()})")

(RAIZ / penwatch.DAEMON_LOCK_REL).unlink()
F.vueltas(ag, 1, cada=agente.GRACIA + 1)
F.vueltas(ag, 1)
c("cuando ese servicio se va, vuelve", F.lock(RAIZ).get("pid"), os.getpid())

# Rastro de otro equipo (la unidad se desenchufó allí sin cerrar nada): no manda.
ag.conexiones[UID].lock = None
F.otro_servicio(RAIZ, host="otro-equipo")
F.vueltas(ag, 1)
c("un lock de otro equipo es rastro, y se sustituye", F.lock(RAIZ).get("pid"), os.getpid())
F.otro_servicio(RAIZ, pid=2 ** 22 + 12345)
ag.conexiones[UID].lock = None
F.vueltas(ag, 1)
c("un lock de un pid muerto, también", F.lock(RAIZ).get("pid"), os.getpid())

# el runsync de verdad: stop_previous_daemon() contra el agente
import runsync  # noqa: E402

for p in F.pasadas(RAIZ):
    if p.rc is None:
        F.acabar(p)
F.vueltas(ag, 1)
runsync.LOCK = RAIZ / penwatch.DAEMON_LOCK_REL
runsync.STOP = F.stop(RAIZ)
runsync.HOST = penwatch.HOST
c("antes de abrir runsync, el lock es del agente", F.lock(RAIZ).get("pid"), os.getpid())
dicho: list = []
hilo = threading.Thread(target=lambda: dicho.append(runsync.stop_previous_daemon()))
hilo.start()
limite = time.monotonic() + 10
while hilo.is_alive() and time.monotonic() < limite:
    F.vueltas(ag, 1)
    time.sleep(0.2)
hilo.join(1)
c("el runsync de siempre ve parar al servicio sin esperar a su plazo, y no dice nada",
  dicho, [None])
c("  y deja la unidad sin lock ni stop", (F.lock(RAIZ), F.stop(RAIZ).exists()), ({}, False))

# Con un servicio de runsync, en cambio, sí se dice que se ha detenido.
F.otro_servicio(RAIZ)


def servicio_que_para():
    """Hace de servicio clásico: espera el `daemon.stop` y suelta su lock."""
    limite = time.monotonic() + 5
    while time.monotonic() < limite and not runsync.STOP.exists():
        time.sleep(0.02)
    runsync.LOCK.unlink()
    runsync.STOP.unlink()


hilo = threading.Thread(target=servicio_que_para)
hilo.start()
detenido = runsync.stop_previous_daemon()
hilo.join()
c("un servicio de runsync que para, sí lo dice",
  detenido, f"Servicio anterior (pid {os.getppid()}) detenido.")

# desenchufada a mitad de pasada
F.vueltas(ag, 1, cada=agente.GRACIA + 1)
F.pasar(3600)
F.vueltas(ag, 1)
en_curso = [p for p in F.pasadas(RAIZ) if p.rc is None]
c("otra pasada en marcha", len(en_curso), 1)
marcas_antes = dict(ag.marcas)
avisos_antes = len(F.AVISOS)
F.RAICES[:] = []
(RAIZ / ".prdrive" / "PRDRIVE").rename(RAIZ / ".prdrive" / "PRDRIVE.fuera")
F.vueltas(ag, 1)
c("sin el fichero de control, desconectada en la misma vuelta", UID in ag.conexiones, False)
F.acabar(en_curso[0], 1, "Failed to copy: The device is not ready.\n")
F.vueltas(ag, 1)
c("la pasada cortada no cuenta como fallo", ag.marcas, marcas_antes)
c("  ni avisa de nada", len(F.AVISOS), avisos_antes)
(RAIZ / ".prdrive" / "PRDRIVE.fuera").rename(RAIZ / ".prdrive" / "PRDRIVE")
F.RAICES[:] = [RAIZ]


# fallos, avisos y el «sin conexión»

def fresco(uid, modo=equipo.DAEMON, **kw):
    """Un agente nuevo con una unidad nueva ya conectada y atendida."""
    raiz = F.unidad(uid, **kw)
    aj = equipo.leer_ajustes().con_unidad(equipo.Unidad(uid, modo, "U"))
    equipo.guardar_ajustes(aj)
    F.RAICES[:] = [raiz]
    a = F.nuevo()
    F.vueltas(a, 2)
    return a, raiz


B = "b" * 32
ag, RB = fresco(B, parejas=("docs",))
p = F.pasadas(RB)[-1]
F.AVISOS.clear()
F.acabar(p, 1, "ERROR : docs: Failed to copy: permission denied\n")
F.vueltas(ag, 1)
c("una pareja que empieza a fallar avisa", len(F.AVISOS), 1)
c("  con qué unidad y qué pareja", F.AVISOS[0][0], "U: falla docs")
c("  y apunta la salida en el diario de la unidad",
  "permission denied" in (RB / ".prdrive/state/daemon.log").read_text(encoding="utf-8"),
  True)
c("  y el resultado en el lock, como el servicio de runsync",
  F.lock(RB).get("last_results"), {"docs": "ERROR rc=1"})
F.vueltas(ag, 1)
c("tras un fallo, espera más que su intervalo", len(F.pasadas(RB)), 1)
F.pasar(2 * 30 * 60)
F.vueltas(ag, 1)
c("pasado el doble del intervalo, lo vuelve a intentar", len(F.pasadas(RB)), 2)
F.acabar(F.pasadas(RB)[-1], 1, "permission denied\n")
F.vueltas(ag, 1)
c("el segundo fallo seguido no vuelve a avisar", len(F.AVISOS), 1)

C = "c" * 32
RED = "Failed to create file system: couldn't connect SSH: dial tcp: lookup nas: no such host\n"
# Sin el rclone del agente no se ejecuta nada de la unidad: ni su sync.py, que
# usaría el suyo, ni una sonda.
agente.rclone_propio = lambda: None
F.AVISOS.clear()
ag, RC = fresco(C, parejas=("docs",))
F.vueltas(ag, 3)
c("sin el rclone del agente no se lanza nada de la unidad",
  (len(F.pasadas(RC)), [x for x in F.LANZADOS if "lsd" in x.args]), (0, []))
c("  y lo dice, una vez", ([a[0] for a in F.AVISOS], ag.conexiones[C].motivo),
  (["prdrive: el agente no tiene su rclone"], agente.SIN_RCLONE))
agente.rclone_propio = lambda: F.RCLONE[0]

ag, RC = fresco(C, parejas=("docs",))
F.AVISOS.clear()
F.acabar(F.pasadas(RC)[-1], 1, RED)
F.vueltas(ag, 1)
sondas = [x for x in F.LANZADOS if "lsd" in x.args and str(RC) in " ".join(x.args)]
c("con rclone, un fallo de red no avisa como fallo de la pareja", F.AVISOS, [])
c("  y lanza enseguida una sonda del remoto, no la pareja otra vez",
  (len(sondas), len(F.pasadas(RC))), (1, 1))
c("la sonda es un lsd del remoto de esa pareja", len(sondas), 1)
c("  con el rclone del agente, nunca el de la unidad", sondas[0].args[0], str(F.RCLONE[0]))
c("  y la pasada lleva el del agente para su sync.py",
  F.pasadas(RC)[-1].kwargs.get("env", {}).get(agente.model.RCLONE_DEL_AGENTE),
  str(F.RCLONE[0]))
c("  con el rclone.conf de la unidad", sondas[0].args[1:3],
  ["--config", str(RC / ".prdrive" / "rclone.conf")])
c("  y el remoto", sondas[0].args[-3:], ["nas:", "--max-depth", "1"])
c("  y con cwd en la carpeta del programa (rclone.conf resuelve contra ella)",
  sondas[0].kwargs.get("cwd"), str(RC / ".prdrive"))
F.acabar(sondas[0], 1, "dial tcp: lookup nas: no such host\n")
F.vueltas(ag, 1)
c("la sonda confirma que no hay red: un aviso de «sin conexión»", F.AVISOS[-1][0],
  "U: sin conexión con nas")
c("  y el remoto queda sin conexión", list(ag.entorno.sin_conexion), [(C, "nas")])
F.vueltas(ag, 5)
c("mientras tanto, ni pasadas ni sondas", len(F.pasadas(RC)) + len(sondas), 2)
F.pasar(ag.ajustes.politica.sondeo_sin_conexion)
F.vueltas(ag, 1)
sondas = [x for x in F.LANZADOS if "lsd" in x.args and str(RC) in " ".join(x.args)]
c("a los cinco minutos, otra sonda", len(sondas), 2)
F.acabar(sondas[-1], 0, "")
F.vueltas(ag, 1)
c("contesta: vuelve la conexión", ag.entorno.sin_conexion, {})
c("  y la pareja va la primera", F.pasadas(RC)[-1].args[-1], "docs")
c("  sin haber sumado fallos por la red", ag.marcas.get((C, "docs"), pl.Marca()).fallos, 0)
F.acabar(F.pasadas(RC)[-1], 1, RED)
F.vueltas(ag, 1)
sondas = [x for x in F.LANZADOS if "lsd" in x.args and str(RC) in " ".join(x.args)]
F.acabar(sondas[-1], 0, "")
avisos_antes = len(F.AVISOS)
F.vueltas(ag, 1)
c("si la sonda contesta en seguida, aquel «fallo de red» era de la pareja",
  ag.marcas[(C, "docs")].fallos, 1)
c("  y ahora sí avisa como fallo", F.AVISOS[avisos_antes:][0][0], "U: falla docs")

# La sospecha de red es de cada pareja, no del remoto: el fallo «de red» de una
# no se pierde porque otra pareja del mismo remoto falle detrás (un urgente va
# antes que la sonda), ni se anuncia el de una que ya ha funcionado.
C2 = "c" * 31 + "2"
ag, R2 = fresco(C2, parejas=("docs", "fotos"))
F.AVISOS.clear()


def sondas_de(raiz):
    """Las sondas lanzadas contra esa raíz."""
    return [x for x in F.LANZADOS if "lsd" in x.args and str(raiz) in " ".join(x.args)]


c("la unidad de dos parejas empieza por docs", F.pasadas(R2)[-1].args[-1], "docs")
equipo.pedir({"pide": equipo.PIDE_PASADA, "id": C2, "parejas": ["fotos"]})
F.acabar(F.pasadas(R2)[-1], 1, RED)
F.vueltas(ag, 1)
c("con otra pareja del mismo remoto pedida, va ella antes que la sonda",
  (F.pasadas(R2)[-1].args[-1], len(sondas_de(R2))), ("fotos", 0))
F.acabar(F.pasadas(R2)[-1], 1, RED)
F.vueltas(ag, 1)
c("las dos sospechas siguen en pie, una por pareja",
  sorted(k[1] for k in ag.sospechas), ["docs", "fotos"])
c("  y la sonda es una, del remoto", len(sondas_de(R2)), 1)
F.acabar(sondas_de(R2)[-1], 0, "")
F.vueltas(ag, 1)
c("el remoto contesta: el fallo de LAS DOS no era de la red",
  (ag.marcas[(C2, "docs")].fallos, ag.marcas[(C2, "fotos")].fallos), (1, 1))
c("  y se avisa de las dos", sorted(a[0] for a in F.AVISOS), ["U: falla docs", "U: falla fotos"])
c("  sin sospechas que sobren", ag.sospechas, {})

C3 = "c" * 31 + "3"
ag, R3 = fresco(C3, parejas=("docs",))
F.AVISOS.clear()
equipo.pedir({"pide": equipo.PIDE_PASADA, "id": C3, "parejas": ["docs"]})
F.acabar(F.pasadas(R3)[-1], 1, RED)
F.vueltas(ag, 1)
c("con otra pasada de la misma pareja pedida, va antes que la sonda",
  (len(F.pasadas(R3)), len(sondas_de(R3)), list(ag.sospechas)), (2, 0, [(C3, "docs")]))
F.acabar(F.pasadas(R3)[-1], 0, "")
F.vueltas(ag, 1)
c("si esa pasada sale bien, la sospecha de red de esa pareja se cierra",
  (ag.sospechas, ag.marcas[(C3, "docs")].fallos), ({}, 0))
sondas = sondas_de(R3)
if sondas:
    F.acabar(sondas[-1], 0, "")
    F.vueltas(ag, 1)
c("  y cuando el remoto contesta no se le apunta el fallo de antes",
  (ag.marcas[(C3, "docs")].fallos, [a[0] for a in F.AVISOS]), (0, []))

# Y si la marca cambió por otra vía mientras esperaba la sonda, no se pisa.
C4 = "c" * 31 + "4"
ag, R4 = fresco(C4, parejas=("docs",))
F.AVISOS.clear()
F.acabar(F.pasadas(R4)[-1], 1, RED)
F.vueltas(ag, 1)
ag.marcas[(C4, "docs")] = pl.Marca(F.reloj(), 0)       # otra vía: la pareja ya está al día
F.acabar(sondas_de(R4)[-1], 0, "")
F.vueltas(ag, 1)
c("una pareja que ya no está como la dejó el fallo de red no recibe el fallo",
  (ag.marcas[(C4, "docs")].fallos, [a[0] for a in F.AVISOS]), (0, []))

# los modos
D = "d" * 32
ag, RD = fresco(D, modo=equipo.SYNC, parejas=("docs",))
F.acabar(F.pasadas(RD)[-1])
F.vueltas(ag, 1)
F.pasar(24 * 3600)
F.vueltas(ag, 3)
c("modo sync: una pasada por conexión y ninguna más", len(F.pasadas(RD)), 1)

E = "e" * 32
ag, RE = fresco(E, modo=equipo.NADA)
F.vueltas(ag, 5)
c("modo nada: ni lock", F.lock(RE), {})
c("  ni pasadas", F.pasadas(RE), [])

G = "0" * 32
ag, RG = fresco(G, modo=equipo.UI)
ventanas = [x for x in F.LANZADOS if x.args[-1] == str(RG / ".prdrive" / "runsync.py")]
c("modo ui: abre la ventana de la unidad (su runsync.py) al conectarla", len(ventanas), 1)
c("  fuera de la unidad", ventanas[0].kwargs.get("cwd"), str(equipo.DIR))
if os.name != "nt":
    c("  y en su propia sesión: sobrevive al agente",
      ventanas[0].kwargs.get("start_new_session"), True)
F.vueltas(ag, 5)
ventanas = [x for x in F.LANZADOS if x.args[-1] == str(RG / ".prdrive" / "runsync.py")]
c("  una vez por conexión", len(ventanas), 1)
c("  y sin servicio del agente", F.lock(RG), {})

# Una ventana de antes de reiniciar: su pid lo tiene hoy otro proceso, y no puede
# dejar la raíz en pausa (ni sin su ventana) para siempre.
FIJO = 1_800_000_000.0
real_arranque = store.arranque_del_sistema
store.arranque_del_sistema = lambda: FIJO
try:
    ventana = {"pid": os.getppid(), "host": penwatch.HOST, "started": "x"}
    P6 = "6" * 32
    ag, RP = fresco(P6, parejas=("docs",))
    # El arranque que apuntó al tomar el lock se desvía en los días que vive: al apuntar
    # cada pareja lo vuelve a calcular.
    ag.conexiones[P6].lock["arranque"] = FIJO - 10_000
    F.acabar(F.pasadas(RP)[-1])
    F.vueltas(ag, 1)
    c("el agente refresca el arranque de su lock cada vez que lo reescribe",
      F.lock(RP).get("arranque"), FIJO)
    store.write_json(RP / penwatch.UI_LOCK_REL, {**ventana, "arranque": FIJO - 10_000})
    F.vueltas(ag, 5)
    c("una ventana de otro arranque, aunque su pid viva, no pone la raíz en pausa",
      (ag.conexiones[P6].motivo, F.lock(RP).get("pid")), ("", os.getpid()))
    store.write_json(RP / penwatch.UI_LOCK_REL, {**ventana, "arranque": FIJO})
    F.vueltas(ag, 5)
    c("una de este arranque, sí",
      (ag.conexiones[P6].motivo, F.lock(RP)),
      ("en pausa: hay una ventana de runsync abierta", {}))

    def abrir_con_ventana(uid: str, arranque: float | None):
        """Conecta una unidad en modo `ui` que ya trae su `ui.lock.json`."""
        raiz = F.unidad(uid, parejas=("docs",))
        store.write_json(raiz / penwatch.UI_LOCK_REL, {**ventana, "arranque": arranque})
        equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(
            equipo.Unidad(uid, equipo.UI, "U")))
        F.RAICES[:] = [raiz]
        F.vueltas(F.nuevo(), 2)
        return [x for x in F.LANZADOS if x.args[-1] == str(raiz / ".prdrive" / "runsync.py")]

    c("modo ui: una ventana de otro arranque no impide abrir la de la unidad",
      len(abrir_con_ventana("5" * 32, FIJO - 10_000)), 1)
    F.DIARIO.clear()
    c("  y una de este arranque, sí: no se abre otra",
      (len(abrir_con_ventana("4" * 32, FIJO)),
       any("no abro la ventana: la ventana de runsync ya está abierta" in x for x in F.DIARIO)),
      (0, True))
finally:
    store.arranque_del_sistema = real_arranque

# el buzón
H = "f" * 32
ag, RH = fresco(H, parejas=("docs", "fotos"))
F.acabar(F.pasadas(RH)[-1])
F.vueltas(ag, 1)
F.acabar(F.pasadas(RH)[-1])
F.vueltas(ag, 1)
equipo.pedir({"pide": equipo.PIDE_PAUSA})
F.pasar(3600)
F.vueltas(ag, 2)
c("en pausa no se lanza nada", len(F.pasadas(RH)), 2)
equipo.pedir({"pide": equipo.PIDE_PASADA, "id": H, "parejas": ["fotos"]})
F.vueltas(ag, 1)
c("«Sincronizar ahora» se salta la pausa", F.pasadas(RH)[-1].args[-1], "fotos")
F.acabar(F.pasadas(RH)[-1])
F.vueltas(ag, 2)
c("  y solo lo pedido", len(F.pasadas(RH)), 3)
equipo.pedir({"pide": equipo.PIDE_SIGUE})
F.vueltas(ag, 1)
c("al seguir, vuelve a lo suyo", len(F.pasadas(RH)), 4)

equipo.pedir({"pide": equipo.PIDE_MODO, "id": H, "modo": equipo.SYNC})
equipo.pedir({"pide": equipo.PIDE_AJUSTE, "clave": "espera_unidad_nueva", "valor": 45})
equipo.pedir({"pide": equipo.PIDE_AJUSTE, "clave": "pid", "valor": 1})
equipo.pedir({"pide": equipo.PIDE_MODO, "id": H, "modo": "borrarlo-todo"})
F.vueltas(ag, 1)
guardado = store.read_json(equipo.ajustes_json())
c("un modo pedido por el buzón lo escribe el agente en agente.json",
  guardado["unidades"][H]["modo"], equipo.SYNC)
c("  y un ajuste también", guardado["espera_unidad_nueva"], 45.0)
c("  lo que no es un ajuste pedible no entra", "pid" in guardado, False)
c("  ni un modo que no existe", equipo.leer_ajustes().unidades[H].modo, equipo.SYNC)
c("el buzón queda vacío", equipo.buzon().exists(), False)

# Un «parar» que el agente anterior no llegó a leer (el instalador lo terminó a
# la fuerza) no tumba al que arranca después.
equipo.buzon().write_text('{"pide": "parar", "cuando": %f}\n' % (ag.inicio - 60),
                          encoding="utf-8")
F.vueltas(ag, 1)
c("un «parar» de antes de arrancar no es para este agente", ag.terminar, False)
equipo.pedir({"pide": equipo.PIDE_PARAR})
F.vueltas(ag, 1)
c("uno de ahora, sí", ag.terminar, True)

# el vestíbulo de una unidad VeraCrypt cerrada
V = "9" * 32
FISICA = F.unidad("vestibulo")
for nombre in (".prdrive",):
    import shutil
    shutil.rmtree(FISICA / nombre)
(FISICA / penwatch.VESTIBULE_MARKER).write_text(f"id={V}\n", encoding="utf-8")
(FISICA / penwatch.CONTAINER_FILE).write_bytes(b"")
DENTRO = F.unidad(V)
F.ABIERTOS.clear()
equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(equipo.Unidad(V, equipo.DAEMON)))
F.RAICES[:] = [FISICA]
ag = F.nuevo()
F.vueltas(ag, 3)
c("una unidad de la lista, cifrada y cerrada: se le pide a VeraCrypt que la abra",
  F.ABIERTOS, [FISICA])
F.vueltas(ag, 3)
c("  una vez por conexión (si se cancela, no se insiste)", F.ABIERTOS, [FISICA])
F.RAICES[:] = [FISICA, DENTRO]
F.vueltas(ag, 2)
c("abierta, se atiende como cualquier otra", F.lock(DENTRO).get("pid"), os.getpid())
F.RAICES[:] = [FISICA]
F.vueltas(ag, 5)
c("cerrada con la unidad puesta («Expulsar»): no se vuelve a pedir", F.ABIERTOS, [FISICA])
F.RAICES[:] = []
F.vueltas(ag, 2)
F.RAICES[:] = [FISICA]
F.vueltas(ag, 3)
c("desenchufada y vuelta a enchufar: se pide otra vez", F.ABIERTOS, [FISICA, FISICA])

W = "8" * 32
F.ABIERTOS.clear()
(FISICA / penwatch.VESTIBULE_MARKER).write_text(f"id={W}\n", encoding="utf-8")
ag = F.nuevo()
F.vueltas(ag, 4)
c("una cifrada que no está en la lista: nunca se ejecuta nada suyo", F.ABIERTOS, [])

# Windows no deja borrar un fichero que otro tiene abierto
#
# runsync lee daemon.lock.json cada 0,3 s mientras espera a que el servicio
# pare, y Python abre sin FILE_SHARE_DELETE: si el agente lo borra justo
# entonces, WinError 32. La vuelta no puede caerse por eso, ni el lock quedarse
# en la unidad con el pid del agente: se reintenta en la siguiente. El fallo se
# provoca aquí a mano para que salga igual en Linux (H-2 de las pruebas en
# real).
import pathlib  # noqa: E402

L = "7" * 32
RL = F.unidad(L, parejas=("docs",))
equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(equipo.Unidad(L, equipo.DAEMON)))
F.RAICES[:] = [RL]
ag = F.nuevo()
F.vueltas(ag, 2)
for p in F.pasadas(RL):
    F.acabar(p)
F.vueltas(ag, 1)
c("(la unidad la atiende el agente, sin pasada en curso)",
  (F.lock(RL).get("pid"), ag.pasada), (os.getpid(), None))

unlink_real = pathlib.Path.unlink
en_uso = [3]                        # tres intentos seguidos con runsync leyéndolo


def unlink_en_uso(self, missing_ok=False):
    """`unlink` que falla como en Windows con runsync leyendo el lock."""
    if self.name == "daemon.lock.json" and en_uso[0]:
        en_uso[0] -= 1
        raise PermissionError(32, "El proceso no tiene acceso al archivo porque está "
                                  "siendo utilizado por otro proceso", str(self))
    return unlink_real(self, missing_ok=missing_ok)


pathlib.Path.unlink = unlink_en_uso
try:
    F.stop(RL).touch()
    F.pasar(3600)                   # la pareja ya tocaría: que se vea si se lanza
    antes = len(F.pasadas(RL))
    try:
        F.vueltas(ag, 1)
        cayo = None
    except OSError as e:
        cayo = e
    c("un lock que otro está leyendo no tumba la vuelta", cayo, None)
    c("  el servicio ya está soltado: no lanza la pareja que tocaba",
      len(F.pasadas(RL)), antes)
    F.vueltas(ag, 2)
    c("  y en las vueltas siguientes se borra: no se queda huérfano", F.lock(RL), {})
    c("  sin lanzar nada mientras", len(F.pasadas(RL)), antes)
finally:
    pathlib.Path.unlink = unlink_real

raise SystemExit(c.report())
