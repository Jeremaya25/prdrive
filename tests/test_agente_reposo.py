#!/usr/bin/env python3
"""El agente gasta poco cuando no tiene nada que hacer, y poco disco con una unidad quieta.

Sin nada a la vista y con el buzón avisando, el bucle espera medio minuto en vez
de dos segundos (`agente.cuanto_esperar()`), no lee la batería ni la red, y el
recorrido de respaldo es de dos minutos. Con una unidad atendida, lo que mira de
su `state/` en cada vuelta es una sola lectura de la carpeta
(`agente.mirar_estado()`), y sus registros se releen solo si cambian. Y el
oyente del buzón (`common/avisos_buzon.py`), de verdad.
"""

import os
import threading
import time

from _harness import Checks, tmpdir

import _agente_falso as F
import agente
import penwatch
from common import avisos_buzon, equipo, moderacion, store
from common import planificador as pl

c = Checks("agente: en reposo y con una unidad quieta")

F.preparar()
agente.letras_de_unidad = lambda: LETRAS[0]
LETRAS = [0b100]
ENTORNO = [0]


def energia():
    ENTORNO[0] += 1
    return moderacion.Energia()


moderacion.energia = energia

# --- cuánto espera el bucle
ag = F.nuevo()
F.vueltas(ag, 3)
c("sin oír el buzón, el tic de siempre aunque no haya nada", agente.cuanto_esperar(ag), agente.TICK)
ag.oye_buzon = True
ag.proximo_recorrido = F.reloj() + 500
c("oyendo el buzón y sin nada a la vista, espera el reposo",
  (ag.en_reposo(), agente.cuanto_esperar(ag)), (True, agente.REPOSO))
ag.proximo_recorrido = F.reloj() + 7
c("  o hasta el recorrido de respaldo, si toca antes", agente.cuanto_esperar(ag), 7.0)
ag.proximo_recorrido = F.reloj() - 50
c("  nunca menos que un tic", agente.cuanto_esperar(ag), agente.TICK)
ag.proximo_recorrido = F.reloj() + 500
ag.rafaga_hasta = F.reloj() + 10
c("en una racha de montajes, el tic", agente.cuanto_esperar(ag), agente.TICK)
ag.rafaga_hasta = F.reloj() - 1
ag.peticiones.put({"pide": equipo.PIDE_PAUSA})
c("con algo pedido desde la bandeja, el tic", agente.cuanto_esperar(ag), agente.TICK)
ag.peticiones.get()
ag.terminar = True
c("terminando, el tic", agente.cuanto_esperar(ag), agente.TICK)
ag.terminar = False
c("sin unidades no se pregunta por la batería ni por la red", ENTORNO[0], 0)
c("el recorrido de respaldo es de minutos, no de segundos",
  agente.RECORRIDO_RESPALDO >= 120, True)

# --- una letra que aparece o se va es como un aviso de montajes
ag2 = F.nuevo()
ag2.bandeja = object()
F.vueltas(ag2, 1)
ag2.rafaga_hasta = F.reloj() - 1
ag2.proximo_recorrido = F.reloj() + 100
c("con las letras de siempre no toca recorrer", ag2.toca_recorrer(F.reloj()), False)
LETRAS[0] = 0b1100
c("aparece una letra: toca recorrer ya, y en racha",
  (ag2.toca_recorrer(F.reloj()), ag2.rafaga_hasta > F.reloj()), (True, True))
ag2.rafaga_hasta = F.reloj() - 1
c("  y con las mismas otra vez, no", ag2.toca_recorrer(F.reloj()), False)
LETRAS[0] = None
ag3 = F.nuevo()
ag3.proximo_recorrido = F.reloj() + 100
c("fuera de Windows (sin letras) no cambia nada", ag3.toca_recorrer(F.reloj()), False)

# --- con una unidad a la vista
UID = "reposo-0001"
raiz = F.unidad(UID, parejas=("docs",), daemon='[daemon]\npairs = ["docs"]\ninterval_minutes = 5\n')
equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(
    equipo.Unidad(UID, equipo.DAEMON, "U", codigo=agente.huella(raiz) or "")))
F.RAICES[:] = [raiz]
ag = F.nuevo()
ag.oye_buzon = True
F.vueltas(ag, 3)
F.acabar(ag.pasada.proc, 0, "[docs] OK.\n")
F.vueltas(ag, 2)
con = ag.conexiones[UID]
c("con una unidad a la vista, el tic: su contrato se mira de cerca",
  (ag.en_reposo(), agente.cuanto_esperar(ag)), (False, agente.TICK))
c("  y entonces sí se lee el entorno", ENTORNO[0] > 0, True)
estado = raiz / ".prdrive" / "state"
c("la mirada dice lo que hay del contrato, con su fecha y su tamaño",
  (sorted(agente.mirar_estado(raiz)), agente.mirar_estado(raiz)[agente.NOMBRE_LOCK][1]),
  ([agente.NOMBRE_LOCK], (estado / agente.NOMBRE_LOCK).stat().st_size))
(estado / "otra-cosa.json").write_text("{}", encoding="utf-8")
c("  y nada que no sea del contrato", sorted(agente.mirar_estado(raiz)), [agente.NOMBRE_LOCK])
vacia = tmpdir("prdrive-sin-state-")
(vacia / ".prdrive").mkdir()
(vacia / ".prdrive" / "PRDRIVE").write_text("id=x\n", encoding="utf-8")
c("  una raíz sin `state/` todavía sigue a la vista", agente.mirar_estado(vacia), {})
c("  y una que ya no está, no", agente.mirar_estado(vacia / "no-esta"), None)

# Lo que toca de la unidad en cada vuelta: se cuentan las aperturas de sus ficheros.
ABIERTOS: list[str] = []
leer_json = store.read_json


def read_json_contado(ruta):
    if str(ruta).startswith(str(raiz)):
        ABIERTOS.append(os.path.basename(str(ruta)))
    return leer_json(ruta)


store.read_json = read_json_contado
RECOGIDOS: list = []
recoger = equipo.recoger


def recoger_contado(buzon_de=None):
    if buzon_de is not None:
        RECOGIDOS.append(buzon_de)
    return recoger(buzon_de)


equipo.recoger = recoger_contado
F.vueltas(ag, 5, recorrer=False)
c("con la unidad quieta, cinco vueltas no abren ni un registro suyo", ABIERTOS, [])
c("  ni intentan recoger un buzón que no está", RECOGIDOS, [])
F.pasar(agente.RELEER_REGISTROS)
F.vueltas(ag, 1, recorrer=False)
c("pasado un rato se relee el lock aunque su fecha no haya cambiado", ABIERTOS,
  [agente.NOMBRE_LOCK])
ABIERTOS.clear()
F.ventana_abierta(raiz)
F.vueltas(ag, 1, recorrer=False)
c("al abrirse su ventana, se lee su registro en esa misma vuelta y la raíz queda en pausa",
  (agente.NOMBRE_VENTANA in ABIERTOS, "ventana" in con.motivo), (True, True))
ABIERTOS.clear()
F.vueltas(ag, 3, recorrer=False)
c("  y mientras no cambie no se vuelve a abrir", agente.NOMBRE_VENTANA in ABIERTOS, False)
(raiz / penwatch.UI_LOCK_REL).unlink()
F.pasar(agente.GRACIA + 1)
F.vueltas(ag, 2, recorrer=False)
c("al cerrarse, se nota sin abrir nada (el fichero ya no está) y vuelve a atenderla",
  (con.motivo, con.lock is not None), ("", True))
equipo.pedir({"pide": equipo.PIDE_PAUSAR_RAIZ}, estado / equipo.BUZON_SERVICIO)
F.vueltas(ag, 1, recorrer=False)
c("una petición en el buzón de la raíz se recoge en la vuelta en que aparece",
  (len(RECOGIDOS), equipo.leer_ajustes().unidades[UID].pausada), (1, True))
equipo.pedir({"pide": equipo.PIDE_REANUDAR}, estado / equipo.BUZON_SERVICIO)
F.vueltas(ag, 2, recorrer=False)
if ag.pasada is not None:               # «Reanudar» vuelve ya: su pasada acaba antes de seguir
    F.acabar(ag.pasada.proc, 0, "[docs] OK." + chr(10))
    F.vueltas(ag, 2, recorrer=False)
(estado / agente.NOMBRE_STOP).write_text("", encoding="utf-8")
F.vueltas(ag, 1, recorrer=False)
c("un `daemon.stop` se ve en la mirada: se suelta el lock y se borra",
  (con.lock, (estado / agente.NOMBRE_STOP).exists()), (None, False))
store.read_json, equipo.recoger = leer_json, recoger

# El TOML se mira de tarde en tarde; lo editado se acaba viendo.
F.pasar(agente.GRACIA + 1)
F.vueltas(ag, 2, recorrer=False)
toml = raiz / ".prdrive" / "sync_config.toml"
toml.write_text(toml.read_text(encoding="utf-8").replace("interval_minutes = 5",
                                                         "interval_minutes = 9"), encoding="utf-8")
os.utime(toml, (time.time() + 5, time.time() + 5))
F.vueltas(ag, 1, recorrer=False)
antes = con.servicio.minutos
F.pasar(agente.MIRAR_CONFIG)
F.vueltas(ag, 1, recorrer=False)
c("el config editado se ve en la mirada siguiente a su fecha, no en cada vuelta",
  (antes, con.servicio.minutos), (5, 9))

# --- al irse la unidad
F.RAICES[:] = []
import shutil  # noqa: E402
shutil.rmtree(raiz, ignore_errors=True)
F.vueltas(ag, 1, recorrer=False)
c("una unidad que desaparece se nota en la mirada, sin esperar al recorrido",
  UID in ag.conexiones, False)

# --- el oyente del buzón, de verdad
carpeta = tmpdir("prdrive-buzon-")
AVISADO = threading.Event()
oyente = avisos_buzon.abrir(carpeta, "agente.pide", AVISADO.set)
if oyente is None:
    print("  (saltado) aquí no se puede oír el buzón (ni inotify ni Windows)")
else:
    def avisa(segundos: float = 2.0) -> bool:
        """Espera a que el oyente diga que el buzón ha cambiado."""
        fin = time.monotonic() + segundos
        while time.monotonic() < fin:
            if AVISADO.is_set() or (oyente.fd is not None and oyente.leer()):
                AVISADO.clear()
                return True
            time.sleep(0.02)
        return False

    (carpeta / "estado.json").write_text("{}", encoding="utf-8")
    (carpeta / "agente.log").write_text("x", encoding="utf-8")
    c("lo demás que se escribe en la carpeta del agente no avisa", avisa(0.6), False)
    equipo.pedir({"pide": equipo.PIDE_PAUSA}, carpeta / "agente.pide")
    c("una petición en el buzón avisa", avisa(), True)
    equipo.pedir({"pide": equipo.PIDE_SIGUE}, carpeta / "agente.pide")
    c("  y otra, añadida al mismo fichero, también", avisa(), True)
    c("  lo pedido está entero para quien lo recoja",
      [p["pide"] for p in equipo.recoger(carpeta / "agente.pide")],
      [equipo.PIDE_PAUSA, equipo.PIDE_SIGUE])
    oyente.cerrar()
    c("cerrado, la carpeta se puede borrar", shutil.rmtree(carpeta) is None
      and not carpeta.exists(), True)
c("los nombres de un búfer de inotify y de uno de Windows",
  (avisos_buzon.nombres_de_inotify(avisos_buzon.CABECERA.pack(1, 8, 0, 16) + b"agente.pide\0\0\0\0\0"),
   avisos_buzon.nombres_de_windows((0).to_bytes(4, "little") + (3).to_bytes(4, "little")
                                   + (22).to_bytes(4, "little") + "agente.pide".encode("utf-16-le"))),
  (["agente.pide"], ["agente.pide"]))

# --- el vigía despierta con el buzón (Linux: por su descriptor)
vigia = agente.Vigia()
if vigia._poll is None:
    print("  (saltado) sin poll (Windows): al vigía lo despierta el hilo del oyente")
else:
    carpeta = tmpdir("prdrive-buzon-")
    oyente = avisos_buzon.abrir(carpeta, "agente.pide", vigia.despertar)
    c("el vigía oye el descriptor del buzón", vigia.oir_buzon(oyente.fd, oyente.leer), True)
    t0 = time.monotonic()
    vigia.esperar(0.3)
    c("sin nada, la espera dura lo suyo", time.monotonic() - t0 >= 0.25, True)
    (carpeta / "otro.json").write_text("{}", encoding="utf-8")
    t0 = time.monotonic()
    vigia.esperar(0.3)
    c("  lo que no es el buzón no la acorta", time.monotonic() - t0 >= 0.25, True)
    threading.Timer(0.1, lambda: equipo.pedir({"pide": equipo.PIDE_PAUSA},
                                               carpeta / "agente.pide")).start()
    t0 = time.monotonic()
    vigia.esperar(5.0)
    c("  una petición en el buzón la acaba enseguida", time.monotonic() - t0 < 2.0, True)
    oyente.cerrar()

raise SystemExit(c.report())
