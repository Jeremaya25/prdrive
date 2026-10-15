#!/usr/bin/env python3
"""Los atajos de teclado globales en el agente: del atajo pulsado a la petición del buzón.

Con un equipo de mentira (`_agente_falso`) y un motor de atajos de mentira (lo
que en un sistema de verdad es `RegisterHotKey`, `XGrabKey` o el portal):
- Sin atajos guardados el motor ni se crea: los equipos de hoy no cambian.
  Con alguno, se crea y se ponen; uno que el sistema no deja se avisa una vez.
- Un atajo pulsado llega como una petición (`atajo`), por `Agente.pedir()`
  igual que el menú de la bandeja, y se convierte en las peticiones de siempre
  sobre la última unidad usada: su ventana se abrió o se le pidió algo desde la
  bandeja o desde su ventana; si no, la última conectada.
- Sincronizar encola sus parejas y avisa; pausar la pausa o la reanuda y avisa;
  abrir su carpeta y su ventana no avisan; sin unidad, un aviso lo dice.
- La ventana que graba: se abre una (`pregunta.py --atajos`); mientras está
  abierta los atajos se sueltan para que la combinación le llegue a ella, y un
  atajo pulsado no hace nada. «Guardar» los prueba con el sistema: se guarda
  lo que deja, lo demás queda sin asignar y se le contesta a la ventana (y, si
  ya no está, con un aviso). Al cerrarse, vuelven los guardados.
- Sin forma de ponerlos en este equipo, la ventana se abre diciendo por qué y
  un «Guardar» se rechaza entero; un sistema que no contesta se da por «no».
- `agente.py atajo ACCION` y `agente.py atajos` dejan la petición en el buzón,
  y `status` los enseña.
"""

import contextlib
import io
import sys

from _harness import Checks

import _agente_falso as F
import agente
from common import equipo
from ui import atajos, bandeja

c = Checks("atajos de teclado en el agente")
F.preparar()
EXPLORADAS: list = []
agente.explorar = lambda ruta: EXPLORADAS.append(ruta) or True


class Motor:
    """Un motor de atajos de mentira: apunta lo que se le pide y contesta en el acto.

    Args:
        ag: El agente al que contesta (por `atajos_hechos`, como desde su hilo).
        rechazar: Las combinaciones que «tiene otro programa».
        suspende: Si se sueltan mientras se graba (todos menos el portal).
        contesta: Si contesta; sin contestar, el agente se cansa de esperar.
    """
    nombre = "MotorFalso"

    def __init__(self, ag, rechazar=(), suspende=True, contesta=True):
        """Prepara el motor."""
        self.ag, self.rechazar, self.suspende, self.contesta = ag, set(rechazar), suspende, contesta
        self.pedidos: list[dict] = []
        self.cerrado = False

    def poner(self, combos):
        """Apunta lo pedido y contesta lo que el «sistema» deja."""
        self.pedidos.append(dict(combos))
        if self.contesta:
            self.ag.atajos_hechos.put((dict(combos), {a: atajos.YA_LA_USA
                                                      for a, k in combos.items()
                                                      if k in self.rechazar}))

    def cerrar(self):
        """Lo cierra."""
        self.cerrado = True


def con_motor(ag, motor=None, motivo=""):
    """Le da al agente su fábrica de motores; devuelve la lista de los creados."""
    creados: list = []

    def fabricar():
        """Crea el motor, o dice por qué no se puede."""
        creados.append(motor)
        return motor, ("" if motor is not None else motivo)

    ag.poner_motor = fabricar
    return creados


def lista(uid, raiz, nombre):
    """Pone la unidad en la lista con la huella de su código de ahora."""
    equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(
        equipo.Unidad(uid, equipo.DAEMON, nombre, codigo=agente.huella(raiz) or "")))


def avisos(texto):
    """Los avisos (título y texto) que dicen `texto`."""
    return [(t, x) for t, x in F.AVISOS if texto in t or texto in x]


def pulsar(ag, accion, vueltas=1):
    """Pulsa un atajo: lo que hace el hilo del motor, y una vuelta del agente."""
    ag.pedir({"pide": equipo.PIDE_ATAJO, "accion": accion})
    F.vueltas(ag, vueltas)


def ventanas_de_atajos():
    """Las ventanas de los atajos lanzadas."""
    return [p for p in F.LANZADOS if "--atajos" in p.args]


# --- sin atajos, nada
A, B, N = "a" * 32, "b" * 32, "n" * 32
RA = F.unidad(A, parejas=("docs",), nombre="PEN-A")
RB = F.unidad(B, parejas=("docs",), nombre="PEN-B")
RN = F.unidad(N, parejas=("docs",), nombre="PEN-N")
lista(A, RA, "PEN-A")
F.RAICES[:] = [RA]
ag = F.nuevo()
creados = con_motor(ag, Motor(ag))
F.vueltas(ag, 3)
c("sin atajos guardados, el motor ni se crea", creados, [])
c("  y el resumen lo dice, sin ninguno",
  {k: ag.resumen()["atajos"][k] for k in ("acciones", "grabando", "respuesta")},
  {"acciones": {}, "grabando": False, "respuesta": None})
entrada = next(e for e in bandeja.vista(ag.resumen()).menu if e.texto.startswith("Atajos"))
c("  la bandeja ofrece «Atajos de teclado…», que pide abrir su ventana",
  (entrada.texto, entrada.pide), ("Atajos de teclado…", ({"pide":
                                                           equipo.PIDE_GRABAR_ATAJOS},)))
c("  y sin atajos nada de ellos le quita el reposo al agente",
  (ag.atajos_en_vuelo, ag.ventana_atajos, ag.atajos_prueba, ag.atajos_hechos.empty()),
  (None, None, None, True))

# --- con atajos guardados, se ponen al arrancar
equipo.guardar_ajustes(equipo.leer_ajustes().__class__(**{
    **equipo.leer_ajustes().__dict__,
    "atajos": {atajos.SINCRONIZAR: "ctrl+alt+s", atajos.VENTANA: "ctrl+alt+v"}}))
ag = F.nuevo()
motor = Motor(ag, rechazar={"ctrl+alt+v"})
creados = con_motor(ag, motor)
F.AVISOS.clear()
F.vueltas(ag, 3)
c("con atajos guardados, el motor se crea y los pone", (len(creados), motor.pedidos[:1]),
  (1, [{atajos.SINCRONIZAR: "ctrl+alt+s", atajos.VENTANA: "ctrl+alt+v"}]))
c("  y no los vuelve a pedir en cada vuelta", len(motor.pedidos), 1)
c("  el que el sistema no deja se avisa, una vez",
  len(avisos("No he podido poner el atajo Ctrl+Alt+V")), 1)
c("  sigue guardado (quien lo tiene puede soltarlo) y el resumen dice por qué",
  (equipo.leer_ajustes().atajos.get(atajos.VENTANA),
   ag.resumen()["atajos"]["acciones"][atajos.VENTANA]),
  ("ctrl+alt+v", {"combo": "ctrl+alt+v", "error": atajos.YA_LA_USA}))

# --- pulsar: la última unidad usada
F.AVISOS.clear()
pulsar(ag, atajos.SINCRONIZAR)
c("sincronizar: sus parejas, la misma petición que «Sincronizar ahora»",
  (bool(F.pasadas(RA)) or (A, "docs") in ag.urgentes), True)
c("  con un aviso corto con su nombre", [t for t, _x in avisos("PEN-A")],
  ["PEN-A: sincronizando"])
F.AVISOS.clear()
pulsar(ag, atajos.CARPETA)
c("abrir su carpeta: el explorador en su raíz, sin aviso", (EXPLORADAS[-1:], F.AVISOS),
  ([RA], []))
antes = len(F.LANZADOS)
pulsar(ag, atajos.VENTANA)
c("abrir su ventana: su runsync, sin aviso",
  ([p.args[1] for p in F.LANZADOS[antes:]], F.AVISOS),
  ([str(RA / agente.APP_SUBDIR / "runsync.py")], []))
pulsar(ag, atajos.PAUSAR)
c("pausar: la pausa de esa unidad, guardada, y un aviso",
  (equipo.leer_ajustes().unidades[A].pausada, [t for t, _x in F.AVISOS]),
  (True, ["PEN-A: en pausa"]))
pulsar(ag, atajos.PAUSAR)
c("  otra vez: la reanuda", (equipo.leer_ajustes().unidades[A].pausada, F.AVISOS[-1][0]),
  (False, "PEN-A: reanudada"))

lista(B, RB, "PEN-B")
ag.ajustes = equipo.leer_ajustes()
F.RAICES[:] = [RA, RB]
F.vueltas(ag, 3)
ag.usadas.clear()
F.pasar(5)
EXPLORADAS.clear()
pulsar(ag, atajos.CARPETA)
c("dos unidades sin usar ninguna: la última que se conectó", EXPLORADAS, [RB])
ag.pedir({"pide": equipo.PIDE_ABRIR, "id": A})          # «Configurar» de A en la bandeja
F.vueltas(ag, 1)
EXPLORADAS.clear()
pulsar(ag, atajos.CARPETA)
c("  usada A desde la bandeja: A", EXPLORADAS, [RA])
equipo.pedir({"pide": equipo.PIDE_PASADA, "parejas": []},
             buzon_de=agente.estado_de(RB) / equipo.BUZON_SERVICIO)
F.vueltas(ag, 1)
EXPLORADAS.clear()
pulsar(ag, atajos.CARPETA)
c("  pedida una pasada desde la ventana de B: B", EXPLORADAS, [RB])
ag.pedir({"pide": equipo.PIDE_PASADA, "id": A, "parejas": [], "todas": True})
ag.pedir({"pide": equipo.PIDE_PASADA, "id": B, "parejas": [], "todas": True})
F.vueltas(ag, 1)
ag.pedir({"pide": equipo.PIDE_EXPLORAR, "id": A})
ag.pedir({"pide": equipo.PIDE_PASADA, "id": B, "parejas": [], "todas": True})
F.vueltas(ag, 1)
EXPLORADAS.clear()
pulsar(ag, atajos.CARPETA)
c("  «Sincronizar todo ahora» no cuenta como usar ninguna", EXPLORADAS[-1:], [RA])
F.ventana_abierta(RB)
F.vueltas(ag, 2)
EXPLORADAS.clear()
pulsar(ag, atajos.CARPETA)
c("  se ve abrirse la ventana de B (desde su propio acceso): B", EXPLORADAS, [RB])
(RB / agente.APP_SUBDIR / "state" / "ui.lock.json").unlink()
F.vueltas(ag, 2)

F.RAICES[:] = []
F.vueltas(ag, 3)
F.AVISOS.clear()
pulsar(ag, atajos.SINCRONIZAR)
c("sin ninguna unidad conectada: un aviso que lo dice y nada más",
  [t for t, _x in F.AVISOS], ["prdrive: no hay ninguna unidad a mano"])
pulsar(ag, "formatear")
c("una acción que no existe se queda en el diario", any("atajo desconocido" in d
                                                         for d in F.DIARIO), True)

# --- la ventana que graba
F.RAICES[:] = [RA]
F.vueltas(ag, 3)
motor.pedidos.clear()
ag.pedir({"pide": equipo.PIDE_GRABAR_ATAJOS})
F.vueltas(ag, 1)
c("«Atajos de teclado…» abre la ventana: pregunta.py --atajos",
  [p.args[1:] for p in ventanas_de_atajos()],
  [[str(agente.SCRIPT_DIR / "pregunta.py"), "--atajos"]])
c("  mientras está abierta, los atajos se sueltan (para que la combinación le llegue)",
  motor.pedidos[-1:], [{}])
c("  la bandeja lo dice y no deja abrir otra",
  next(e for e in bandeja.vista(ag.resumen()).menu
       if e.texto.startswith("Atajos")).activa, False)
ag.pedir({"pide": equipo.PIDE_GRABAR_ATAJOS})
F.vueltas(ag, 1)
c("  pedirla otra vez no abre otra", len(ventanas_de_atajos()), 1)
c("  y el agente no descansa mientras", ag.en_reposo(), False)
antes = len(F.LANZADOS)
pulsar(ag, atajos.VENTANA)
c("  un atajo que llegue (el portal no los suelta) no hace nada",
  len(F.LANZADOS), antes)
F.AVISOS.clear()
motor.rechazar = {"ctrl+alt+p"}
equipo.pedir({"pide": equipo.PIDE_ATAJOS, "vez": "v1",
              "atajos": {atajos.SINCRONIZAR: "Ctrl+Alt+S", atajos.PAUSAR: "ctrl+alt+p",
                         atajos.CARPETA: "shift+c"}})
F.vueltas(ag, 2)
c("«Guardar»: se prueban de verdad con el sistema",
  {atajos.SINCRONIZAR: "ctrl+alt+s", atajos.PAUSAR: "ctrl+alt+p"} in motor.pedidos, True)
c("  se guarda lo que el sistema deja; el resto queda sin asignar",
  dict(equipo.leer_ajustes().atajos), {atajos.SINCRONIZAR: "ctrl+alt+s"})
respuesta = ag.resumen()["atajos"]["respuesta"]
c("  la ventana lee la respuesta a su «Guardar», con el motivo de cada rechazo",
  (respuesta["vez"], sorted(respuesta["rechazados"]),
   respuesta["rechazados"][atajos.PAUSAR]),
  ("v1", [atajos.CARPETA, atajos.PAUSAR], atajos.YA_LA_USA))
c("  y con la ventana abierta no hace falta aviso", F.AVISOS, [])
c("  y se vuelven a soltar mientras siga abierta", motor.pedidos[-1], {})
ventanas_de_atajos()[0].rc = 0
F.vueltas(ag, 2)
c("al cerrarse la ventana vuelven los guardados",
  motor.pedidos[-1], {atajos.SINCRONIZAR: "ctrl+alt+s"})
c("  y la bandeja vuelve a ofrecerla",
  next(e for e in bandeja.vista(ag.resumen()).menu
       if e.texto.startswith("Atajos")).activa, True)
equipo.pedir({"pide": equipo.PIDE_ATAJOS, "vez": "v2",
              "atajos": {atajos.SINCRONIZAR: "ctrl+alt+s", atajos.PAUSAR: "ctrl+alt+p"}})
F.vueltas(ag, 2)
c("un «Guardar» con la ventana ya cerrada dice con un aviso lo que no se ha podido",
  [t for t, _x in avisos("Ctrl+Alt+P")], ["No he podido poner el atajo Ctrl+Alt+P"])
equipo.pedir({"pide": equipo.PIDE_ATAJOS, "vez": "v3", "atajos": {}})
F.vueltas(ag, 2)
c("guardar ninguno los quita todos", (dict(equipo.leer_ajustes().atajos), motor.pedidos[-1],
                                      ag.resumen()["atajos"]["respuesta"]),
  ({}, {}, {"vez": "v3", "rechazados": {}}))
c("  y agente.json vuelve a no llevarlos",
  "atajos" in agente.store.read_json(equipo.ajustes_json()), False)

# --- el portal no los suelta mientras se graba
ag2 = F.nuevo()
portal = Motor(ag2, suspende=False)
con_motor(ag2, portal)
ag2.pedir({"pide": equipo.PIDE_GRABAR_ATAJOS})
F.vueltas(ag2, 2)
c("con el portal, abrir la ventana no los suelta (habría que confirmarlos otra vez)",
  portal.pedidos, [])

# --- sin forma de ponerlos
ag3 = F.nuevo()
con_motor(ag3, None, atajos.SIN_PORTAL)
ag3.pedir({"pide": equipo.PIDE_GRABAR_ATAJOS})
F.vueltas(ag3, 1)
c("sin forma de ponerlos, la ventana se abre diciendo por qué",
  ventanas_de_atajos()[-1].args[2:], ["--atajos", "--motivo", atajos.SIN_PORTAL])
c("  y el resumen lo dice", ag3.resumen()["atajos"]["motivo"], atajos.SIN_PORTAL)
equipo.pedir({"pide": equipo.PIDE_ATAJOS, "vez": "w", "atajos": {atajos.SINCRONIZAR: "ctrl+s"}})
F.vueltas(ag3, 1)
c("  un «Guardar» se rechaza con ese motivo y no guarda nada",
  (ag3.resumen()["atajos"]["respuesta"],
   dict(equipo.leer_ajustes().atajos)),
  ({"vez": "w", "rechazados": {atajos.SINCRONIZAR: atajos.SIN_PORTAL}}, {}))
ventanas_de_atajos()[-1].rc = 0

# --- un sistema que no contesta
ag4 = F.nuevo()
mudo = Motor(ag4, contesta=False)
con_motor(ag4, mudo)
equipo.pedir({"pide": equipo.PIDE_ATAJOS, "vez": "m", "atajos": {atajos.CARPETA: "super+f9"}})
F.vueltas(ag4, 2)
c("un sistema que no contesta: se espera", (ag4.atajos_prueba is not None,
                                            ag4.en_reposo()), (True, False))
F.vueltas(ag4, 1, cada=agente.ESPERA_ATAJOS)
F.vueltas(ag4, 1)
c("  y pasado el plazo se da por no puesto",
  ag4.resumen()["atajos"]["respuesta"], {"vez": "m", "rechazados": {
      atajos.CARPETA: atajos.SIN_RESPUESTA}})

# --- poner_atajos(): qué motor hay en cada sistema
class Vigia:
    """Un vigía de mentira: cuenta las veces que lo despiertan."""
    despertado = 0

    def despertar(self, montajes=False):
        """Lo apunta."""
        Vigia.despertado += 1


import os  # noqa: E402

from ui import atajos_linux  # noqa: E402

entorno = dict(os.environ)
ag5 = F.nuevo()
try:
    agente.IS_WIN = False
    for v in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE"):
        os.environ.pop(v, None)
    c("Linux sin escritorio: ninguno, y por qué", agente.poner_atajos(ag5, Vigia()),
      (None, atajos.SIN_ESCRITORIO))
    os.environ["DISPLAY"] = ":5"
    creado: list = []

    class Falso:
        """Un motor de Linux que no arranca."""
        motivo = "no se puede hablar con X: sin pantalla"

        def arrancar(self):
            """No arranca."""
            return False

        def cerrar(self):
            """Lo cierra."""
            creado.append("cerrado")

    real = atajos_linux.poner
    atajos_linux.poner = lambda mec, pulsado, puestos: creado.append(mec) or Falso()
    c("X11 que no arranca: ninguno, cerrado y con su motivo",
      (agente.poner_atajos(ag5, Vigia()), creado),
      ((None, Falso.motivo), [atajos.X11, "cerrado"]))
    atajos_linux.poner = real
    agente.IS_WIN = True
    ag5.bandeja = None
    c("Windows sin bandeja: ninguno (sin hilo con bucle de mensajes)",
      agente.poner_atajos(ag5, Vigia()), (None, atajos.SIN_BANDEJA))

    class BandejaFalsa:
        """La bandeja de Windows, sin ventana todavía."""
        hwnd = 777
        atajos_puestos = None

        def poner_atajos(self, combos):
            """No hay a quién pedírselo."""
            return False

    ag5.bandeja = BandejaFalsa()
    motor5, motivo5 = agente.poner_atajos(ag5, Vigia())
    c("Windows con bandeja: la bandeja es el motor", (type(motor5).__name__, motivo5,
                                                      motor5.suspende), ("MotorDeBandeja", "",
                                                                         True))
    motor5.poner({atajos.SINCRONIZAR: "ctrl+alt+s"})
    c("  si no se le puede pedir, lo pedido vuelve como no puesto, y despierta al agente",
      (ag5.atajos_hechos.get_nowait(), Vigia.despertado),
      (({atajos.SINCRONIZAR: "ctrl+alt+s"}, {atajos.SINCRONIZAR: atajos.SIN_BANDEJA}), 1))
finally:
    agente.IS_WIN = os.name == "nt"
    os.environ.clear()
    os.environ.update(entorno)

# --- la línea de órdenes
equipo.recoger()
with contextlib.redirect_stdout(io.StringIO()):
    agente.main(["atajo", "pausar"])
    agente.main(["atajos"])
c("`agente.py atajo ACCION` y `agente.py atajos` dejan su petición en el buzón",
  [{k: v for k, v in p.items() if k in ("pide", "accion")} for p in equipo.recoger()],
  [{"pide": equipo.PIDE_ATAJO, "accion": atajos.PAUSAR}, {"pide": equipo.PIDE_GRABAR_ATAJOS}])
equipo.guardar_ajustes(equipo.leer_ajustes().__class__(**{
    **equipo.leer_ajustes().__dict__, "atajos": {atajos.SINCRONIZAR: "ctrl+alt+s"}}))
salida = io.StringIO()
with contextlib.redirect_stdout(salida):
    agente.cmd_status(None)
c("`status` enseña los atajos guardados",
  "Sincronizar ahora" in salida.getvalue() and "Alt+S" in salida.getvalue(), True)

sys.exit(c.report())
