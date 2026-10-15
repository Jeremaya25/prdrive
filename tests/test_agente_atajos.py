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
import os
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

    Attributes:
        respuestas: Lo que contestan las llamadas siguientes, una cada una, antes
            que lo de siempre: los rechazados por acción, o `None` para no contestar.
    """
    nombre = "MotorFalso"

    def __init__(self, ag, rechazar=(), suspende=True, contesta=True):
        """Prepara el motor."""
        self.ag, self.rechazar, self.suspende, self.contesta = ag, set(rechazar), suspende, contesta
        self.pedidos: list[dict] = []
        self.respuestas: list = []
        self.cerrado = False

    def poner(self, combos):
        """Apunta lo pedido y contesta lo que el «sistema» deja."""
        self.pedidos.append(dict(combos))
        if self.respuestas:
            hecho = self.respuestas.pop(0)
            if hecho is not None:
                self.ag.atajos_hechos.put((dict(combos), hecho(combos)))
            return
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
    "atajos": {atajos.SINCRONIZAR: "ctrl+shift+s", atajos.VENTANA: "ctrl+shift+v"}}))
ag = F.nuevo()
motor = Motor(ag, rechazar={"ctrl+shift+v"})
creados = con_motor(ag, motor)
F.AVISOS.clear()
F.vueltas(ag, 3)
c("con atajos guardados, el motor se crea y los pone", (len(creados), motor.pedidos[:1]),
  (1, [{atajos.SINCRONIZAR: "ctrl+shift+s", atajos.VENTANA: "ctrl+shift+v"}]))
c("  y no los vuelve a pedir en cada vuelta", len(motor.pedidos), 1)
c("  el que el sistema no deja se avisa, una vez",
  len(avisos("No he podido poner el atajo Ctrl+Mayús+V")), 1)
c("  sigue guardado (quien lo tiene puede soltarlo) y el resumen dice por qué",
  (equipo.leer_ajustes().atajos.get(atajos.VENTANA),
   ag.resumen()["atajos"]["acciones"][atajos.VENTANA]),
  ("ctrl+shift+v", {"combo": "ctrl+shift+v", "error": atajos.YA_LA_USA}))

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
motor.rechazar = {"ctrl+shift+p"}
equipo.pedir({"pide": equipo.PIDE_ATAJOS, "vez": "v1",
              "atajos": {atajos.SINCRONIZAR: "Ctrl+Mayús+S", atajos.PAUSAR: "ctrl+shift+p",
                         atajos.CARPETA: "shift+c"}})
F.vueltas(ag, 2)
c("«Guardar»: se prueban de verdad con el sistema",
  {atajos.SINCRONIZAR: "ctrl+shift+s", atajos.PAUSAR: "ctrl+shift+p"} in motor.pedidos, True)
c("  se guarda lo que el sistema deja; el resto queda sin asignar",
  dict(equipo.leer_ajustes().atajos), {atajos.SINCRONIZAR: "ctrl+shift+s"})
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
  motor.pedidos[-1], {atajos.SINCRONIZAR: "ctrl+shift+s"})
c("  y la bandeja vuelve a ofrecerla",
  next(e for e in bandeja.vista(ag.resumen()).menu
       if e.texto.startswith("Atajos")).activa, True)
equipo.pedir({"pide": equipo.PIDE_ATAJOS, "vez": "v2",
              "atajos": {atajos.SINCRONIZAR: "ctrl+shift+s", atajos.PAUSAR: "ctrl+shift+p"}})
F.vueltas(ag, 2)
c("un «Guardar» con la ventana ya cerrada dice con un aviso lo que no se ha podido",
  [t for t, _x in avisos("Ctrl+Mayús+P")], ["No he podido poner el atajo Ctrl+Mayús+P"])
equipo.pedir({"pide": equipo.PIDE_ATAJOS, "vez": "v3", "atajos": {}})
F.vueltas(ag, 2)
c("guardar ninguno los quita todos", (dict(equipo.leer_ajustes().atajos), motor.pedidos[-1],
                                      ag.resumen()["atajos"]["respuesta"]),
  ({}, {}, {"vez": "v3", "rechazados": {}, "guardados": {}}))
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
  ({"vez": "w", "rechazados": {atajos.SINCRONIZAR: atajos.SIN_PORTAL}, "guardados": {}},
   {}))
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
      atajos.CARPETA: atajos.SIN_RESPUESTA}, "guardados": {}})

# --- un «Guardar» que nadie decide no cambia nada
def guardados(**atajos_):
    """Guarda esos atajos en agente.json, como si vinieran de antes."""
    equipo.guardar_ajustes(equipo.leer_ajustes().__class__(**{
        **equipo.leer_ajustes().__dict__, "atajos": atajos_}))


guardados(sincronizar="ctrl+shift+s")
ag6 = F.nuevo()
motor6 = Motor(ag6, suspende=False)
con_motor(ag6, motor6)
F.vueltas(ag6, 2)
motor6.respuestas = [lambda combos: {a: atajos.CANCELADA_PORTAL for a in combos}]
F.AVISOS.clear()
equipo.pedir({"pide": equipo.PIDE_ATAJOS, "vez": "c",
              "atajos": {atajos.SINCRONIZAR: "ctrl+shift+s", atajos.CARPETA: "super+f9"}})
F.vueltas(ag6, 3)
c("cancelado en la ventana del escritorio: agente.json no cambia",
  dict(equipo.leer_ajustes().atajos), {atajos.SINCRONIZAR: "ctrl+shift+s"})
c("  la ventana lee que nadie ha decidido, y lo que sigue guardado",
  ag6.resumen()["atajos"]["respuesta"],
  {"vez": "c", "rechazados": {atajos.SINCRONIZAR: atajos.CANCELADA_PORTAL,
                              atajos.CARPETA: atajos.CANCELADA_PORTAL},
   "guardados": {atajos.SINCRONIZAR: "ctrl+shift+s"}})
c("  y se vuelven a poner los de antes", motor6.pedidos[-1], {atajos.SINCRONIZAR: "ctrl+shift+s"})
c("  sin la ventana, un aviso dice que siguen los de antes, y no que se quedan sin atajo",
  ([t for t, _x in F.AVISOS], avisos("Se queda sin atajo")),
  (["No he cambiado los atajos de teclado"], []))
c("  sin errores de los guardados por ello",
  ag6.resumen()["atajos"]["acciones"][atajos.SINCRONIZAR]["error"], "")
motor6.respuestas = [None]
equipo.pedir({"pide": equipo.PIDE_ATAJOS, "vez": "t",
              "atajos": {atajos.SINCRONIZAR: "ctrl+shift+s", atajos.CARPETA: "super+f9"}})
F.vueltas(ag6, 2)
F.vueltas(ag6, 1, cada=agente.ESPERA_ATAJOS)
F.vueltas(ag6, 2)
c("el sistema no contesta en el plazo: tampoco cambia nada, y vuelven los de antes",
  (dict(equipo.leer_ajustes().atajos), ag6.resumen()["atajos"]["respuesta"]["guardados"],
   motor6.pedidos[-1]),
  ({atajos.SINCRONIZAR: "ctrl+shift+s"}, {atajos.SINCRONIZAR: "ctrl+shift+s"},
   {atajos.SINCRONIZAR: "ctrl+shift+s"}))

# --- los guardados que no valen (agente.json escrito a mano o por otra versión)
guardados(sincronizar="shift+a", carpeta="ctrl+shift+c", ventana="ctrl+shift+c")
ag7 = F.nuevo()
motor7 = Motor(ag7)
con_motor(ag7, motor7)
F.AVISOS.clear()
F.vueltas(ag7, 3)
c("un atajo guardado que no vale no se pone, ni el repetido en otra acción",
  motor7.pedidos, [{atajos.CARPETA: "ctrl+shift+c"}])
acciones7 = ag7.resumen()["atajos"]["acciones"]
c("  el resumen dice por qué (la ventana y `status` lo enseñan)",
  ("Ctrl, Alt" in acciones7[atajos.SINCRONIZAR]["error"],
   "«Abrir su carpeta»" in acciones7[atajos.VENTANA]["error"],
   acciones7[atajos.CARPETA]["error"]), (True, True, ""))
c("  y se avisa una vez de cada uno", sorted(t for t, _x in F.AVISOS),
  ["No he podido poner el atajo Ctrl+Mayús+C", "No he podido poner el atajo Mayús+A"])
F.vueltas(ag7, 3)
c("  una vez", len(F.AVISOS), 2)
try:
    agente.IS_WIN = True
    guardados(sincronizar="ctrl+alt+s", carpeta="ctrl+alt+f5")
    ag7.ajustes = equipo.leer_ajustes()
    c("en Windows, Ctrl+Alt con una letra guardado no se pone (es AltGr)",
      ag7._atajos_guardados(), ({atajos.CARPETA: "ctrl+alt+f5"},
                                {atajos.SINCRONIZAR: atajos.ALTGR.rstrip(".")}))
    agente.IS_WIN = False
    c("  en Linux sí", ag7._atajos_guardados(),
      ({atajos.SINCRONIZAR: "ctrl+alt+s", atajos.CARPETA: "ctrl+alt+f5"}, {}))
finally:
    agente.IS_WIN = os.name == "nt"
guardados()

# --- un motor que no se ha podido crear se vuelve a intentar
guardados(sincronizar="ctrl+shift+s")
ag8 = F.nuevo()
motor8 = Motor(ag8)
intentos: list = []


def tarda_en_llegar():
    """El portal (o la bandeja) de un escritorio que acaba de arrancar: no está a la primera."""
    intentos.append(ag8.reloj())
    if len(intentos) < 3:
        return None, "no hay bus de sesión (no contesta)"
    return motor8, ""


ag8.poner_motor = tarda_en_llegar
F.vueltas(ag8, 3)
c("no se ha podido crear: se dice por qué y no se reintenta en cada vuelta",
  (len(intentos), ag8.resumen()["atajos"]["motivo"]), (1, "no hay bus de sesión (no contesta)"))
F.vueltas(ag8, 1, cada=agente.REINTENTO_ATAJOS)
F.vueltas(ag8, 1)
c("  pasado el plazo se reintenta, y el plazo siguiente es el doble",
  (len(intentos), ag8.atajos_reintento - intentos[-1]), (2, 2 * agente.REINTENTO_ATAJOS))
F.vueltas(ag8, 1, cada=2 * agente.REINTENTO_ATAJOS)
F.vueltas(ag8, 1)
c("  cuando ya se puede, los pone y deja de decir por qué",
  (len(intentos), motor8.pedidos, ag8.atajos_motivo),
  (3, [{atajos.SINCRONIZAR: "ctrl+shift+s"}], ""))
ag9 = F.nuevo()
intentos9: list = []
ag9.poner_motor = lambda: intentos9.append(1) or (None, "no hay bus de sesión (no contesta)")
F.vueltas(ag9, 1)
ag9.pedir({"pide": equipo.PIDE_GRABAR_ATAJOS})
F.vueltas(ag9, 1)
c("  abrir la ventana lo intenta en el acto, aunque no toque", len(intentos9), 2)
ventanas_de_atajos()[-1].rc = 0
F.vueltas(ag9, 1)
ag10 = F.nuevo()
intentos10: list = []
ag10.poner_motor = lambda: intentos10.append(1) or (None, atajos.SIN_ESCRITORIO)
F.vueltas(ag10, 1)
F.vueltas(ag10, 3, cada=agente.REINTENTO_ATAJOS_MAX)
c("sin escritorio no se reintenta: no cambia sin reiniciar el agente", len(intentos10), 1)
F.vueltas(ag10, 1)
guardados()

# --- poner_atajos(): qué motor hay en cada sistema
class Vigia:
    """Un vigía de mentira: cuenta las veces que lo despiertan."""
    despertado = 0

    def despertar(self, montajes=False):
        """Lo apunta."""
        Vigia.despertado += 1


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
    motor5.poner({atajos.SINCRONIZAR: "ctrl+shift+s"})
    c("  si no se le puede pedir, lo pedido vuelve como no puesto, y despierta al agente",
      (ag5.atajos_hechos.get_nowait(), Vigia.despertado),
      (({atajos.SINCRONIZAR: "ctrl+shift+s"}, {atajos.SINCRONIZAR: atajos.SIN_BANDEJA}), 1))
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
    **equipo.leer_ajustes().__dict__, "atajos": {atajos.SINCRONIZAR: "ctrl+shift+s"}}))
salida = io.StringIO()
with contextlib.redirect_stdout(salida):
    agente.cmd_status(None)
c("`status` enseña los atajos guardados",
  "Sincronizar ahora" in salida.getvalue() and "Mayús+S" in salida.getvalue(), True)

sys.exit(c.report())
