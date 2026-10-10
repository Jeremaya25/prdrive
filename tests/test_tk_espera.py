#!/usr/bin/env python3
"""La ventanita de espera (`ui.tk.working()`) con avance, conducida sin nadie delante.

Crear un contenedor fijo escribe el volumen entero, minutos u horas (#46).
`working()` acepta un `progreso` y, mientras diga algo, llena la barra y pone
la cifra debajo; cuando deja de decirlo, vuelve a la barra sin cifra. Lo que se
comprueba es ese ir y venir, y lo que no puede pasar nunca: que un `progreso`
que falla deje la ventanita abierta (no se puede cerrar a mano).

No se entra en el bucle de eventos de verdad: se sustituye `mostrar()` por uno
que va dando vueltas a `update()` mientras cambia lo que dice el avance.

También el ritmo de la barra sin cifra (`PASO_BARRA_MS`, `SALTO_BARRA`): pocos
pasos y grandes, que cuestan poco CPU, a la velocidad de siempre.
"""

import sys
import threading
import time

from _harness import Checks

c = Checks("la ventanita de espera con avance")

try:
    import tkinter as tk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from ui import tk as uitk  # noqa: E402

MOSTRAR_REAL = uitk.mostrar


def esperar_a(condicion, limite: float = 5.0) -> bool:
    """Da vueltas al bucle de Tk hasta que se cumpla `condicion` o pase el rato."""
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        raiz.update()
        if condicion():
            return True
        time.sleep(0.02)
    return False


def conducir(pasos, progreso=None, funcion=None):
    """Abre `working()` y, en vez de esperar sentado, ejecuta `pasos(dlg)`.

    Después suelta la función de trabajo y espera a que la ventanita se cierre
    sola, que es lo único que la cierra."""
    soltar = threading.Event()
    visto: dict = {}

    def trabajo():
        """Espera a que el test lo suelte y devuelve el resultado de la función."""
        soltar.wait(5)
        return funcion() if funcion else "hecho"

    def falso_mostrar(dlg, parent=None):
        """Apunta el diálogo, ejecuta los pasos del test y comprueba que se cierre."""
        visto["dlg"] = dlg
        pasos(dlg)
        soltar.set()
        visto["cerrada"] = esperar_a(lambda: not dlg.winfo_exists())

    uitk.mostrar = falso_mostrar
    try:
        ok, valor = uitk.working(raiz, "probando", trabajo, "Un mensaje.",
                                 progreso=progreso)
    finally:
        uitk.mostrar = MOSTRAR_REAL
    return ok, valor, visto


def modo(dlg) -> str:
    """Devuelve el modo de la barra: `determinate` o `indeterminate`."""
    return str(dlg.barra.cget("mode"))


def ritmo(barra) -> tuple[float, float] | None:
    """Devuelve `(intervalo, salto)` con que Tcl tiene en marcha la barra, o `None`.

    Lo lee del `after` que `ttk::progressbar::start` deja pendiente: así se ve
    lo que se pidió sin esperar a que la barra se mueva.
    """
    try:
        pendiente = barra.tk.eval(f"set ::ttk::progressbar::Timers({barra})")
    except tk.TclError:                                  # parada: no hay temporizador
        return None
    guion = barra.tk.splitlist(barra.tk.call("after", "info", pendiente)[0])
    return float(str(guion[-2])), float(str(guion[-1]))


# 1. sin progreso, la de siempre
ok, valor, visto = conducir(lambda dlg: esperar_a(lambda: False, 0.3))
c("sin progreso no hay hueco para la cifra", visto["dlg"].cifra, None)
c("y se cierra sola al terminar", visto["cerrada"], True)
c("devolviendo lo que dio la función", (ok, valor), (True, "hecho"))


# 2. con progreso: la barra va y viene, se llena, y vuelve
dice: dict = {"medida": None, "llamadas": 0}


def progreso():
    """Hace de `progreso`: cuenta la llamada y devuelve la medida o lanza."""
    dice["llamadas"] += 1
    medida = dice["medida"]
    if isinstance(medida, Exception):
        raise medida
    return medida


def ronda() -> None:
    """Espera a que el sondeo haya preguntado dos veces más."""
    hasta = dice["llamadas"] + 2
    esperar_a(lambda: dice["llamadas"] >= hasta)


def pasos(dlg) -> None:
    """Conduce la ventanita por los casos de avance, apuntando lo que ve."""
    ronda()
    visto["al_abrir"] = (modo(dlg), str(dlg.cifra.cget("text")))
    visto["ritmo_al_abrir"] = ritmo(dlg.barra)

    dice["medida"] = (0.43, "43 % · quedan unos 25 min")
    ronda()
    visto["con_cifra"] = (modo(dlg), round(float(dlg.barra.cget("value"))),
                          str(dlg.cifra.cget("text")))
    visto["ritmo_con_cifra"] = ritmo(dlg.barra)

    dice["medida"] = None
    ronda()
    visto["sin_cifra"] = (modo(dlg), str(dlg.cifra.cget("text")))
    visto["ritmo_sin_cifra"] = ritmo(dlg.barra)

    dice["medida"] = (0.5, "50 % · calculando cuánto queda")
    ronda()
    dice["medida"] = RuntimeError("el contador se ha caído")
    ronda()
    visto["tras_error"] = (modo(dlg), str(dlg.cifra.cget("text")))

    dice["medida"] = "esto no es una medida"
    ronda()
    visto["basura"] = modo(dlg)

    dice["medida"] = (7.0, "de más")
    ronda()
    visto["de_mas"] = round(float(dlg.barra.cget("value")))


visto = {}
ok, valor, ventana = conducir(pasos, progreso=progreso)
c("al abrir, sin cifra todavía: la barra va y viene y el hueco está vacío",
  visto["al_abrir"], ("indeterminate", ""))
c("con cifra, la barra se llena hasta ahí y el texto va debajo",
  visto["con_cifra"], ("determinate", 43, "43 % · quedan unos 25 min"))
c("si el avance deja de saberse, vuelve a ir y venir, sin número",
  visto["sin_cifra"], ("indeterminate", ""))
c("un progreso que lanza una excepción es «no se sabe», no un cuelgue",
  visto["tras_error"], ("indeterminate", ""))
c("y uno que devuelve cualquier cosa, también", visto["basura"], "indeterminate")
c("una fracción de más no pasa de la barra llena", visto["de_mas"], 100)
c("con todo eso, la ventanita se cierra sola al terminar", ventana["cerrada"], True)
c("y devuelve lo de la función", (ok, valor), (True, "hecho"))

# el ritmo de la barra sin cifra
RITMO = (uitk.PASO_BARRA_MS, uitk.SALTO_BARRA)
c("sin cifra, la barra da un paso cada 30-35 ms (era cada 12; a 48 iba a saltos)",
  30 <= uitk.PASO_BARRA_MS <= 35, True)
c("  y su salto es proporcional: la misma velocidad que de 1 en 1 cada 12 ms",
  abs(uitk.SALTO_BARRA / uitk.PASO_BARRA_MS - 1 / 12) < 1e-9, True)
c("al abrir, `working()` la pone a ese ritmo", visto["ritmo_al_abrir"], RITMO)
c("con cifra no hay temporizador: la barra se llena sola", visto["ritmo_con_cifra"], None)
c("cuando vuelve a ir y venir, al mismo ritmo", visto["ritmo_sin_cifra"], RITMO)

indicador = uitk.Indicador(raiz)
indicador.poner("leyendo…", True)
c("el `Indicador` que espera, también", ritmo(indicador.barra), RITMO)
indicador.poner("", False)
c("  y sin esperar, parado", ritmo(indicador.barra), None)
indicador.marco.destroy()


class BarraSinSalto:
    """Una barra de un Tk que solo acepta el intervalo en `start`."""

    class tk:
        """Su intérprete: rechaza el segundo argumento."""

        @staticmethod
        def call(*_args):
            """Falla como un `start` con un argumento de más."""
            raise tk.TclError('wrong # args: should be ".b start ?interval?"')

    def __init__(self) -> None:
        """Empieza sin pedidos."""
        self.pedidos: list = []

    def __str__(self) -> str:
        """Su ruta de widget."""
        return ".b"

    def start(self, intervalo=None) -> None:
        """Apunta el intervalo que se le pide."""
        self.pedidos.append(intervalo)


antigua = BarraSinSalto()
uitk._arrancar_barra(antigua)
c("con un Tk que no admite el salto, arranca igual, a saltos de 1", antigua.pedidos,
  [uitk.PASO_BARRA_MS])


# 3. un progreso que falla desde el principio no cuelga nada
def roto():
    """`progreso` que falla desde el principio."""
    raise OSError("sin contador")


ok, valor, visto = conducir(lambda dlg: esperar_a(lambda: False, 0.4), progreso=roto)
c("con un progreso roto desde el principio, la barra de siempre",
  visto["cerrada"], True)
c("y el resultado llega igual", (ok, valor), (True, "hecho"))


# 4. si la función falla, se devuelve la excepción
def falla():
    """Función de trabajo que falla."""
    raise ValueError("no ha ido")


ok, valor, visto = conducir(lambda dlg: None, progreso=lambda: (0.1, "10 %"),
                            funcion=falla)
c("si falla el trabajo, (False, excepción)", (ok, type(valor).__name__),
  (False, "ValueError"))
c("y la ventanita también se cierra", visto["cerrada"], True)


# 5. colgada de una raíz que no se enseña
#
# La del relevo cuelga de `root_oculto()`. Un `transient` hereda el estado de
# su padre, y en Windows la ventanita no llegaba a verse: el relevo trabajaba
# minutos sin nada en pantalla. Suelta no es transient de nadie.
def transitoria_de(suelto: bool) -> str:
    """Devuelve de quién cuelga la ventanita (su `transient`)."""
    dlg = uitk.modal(raiz, "probando", suelto=suelto)
    try:
        return str(dlg.wm_transient() or "")
    finally:
        dlg.destroy()


c("un diálogo normal es transient de su padre", transitoria_de(False), str(raiz))
c("uno suelto no lo es de nadie", transitoria_de(True), "")

visto = {}


def mirar_suelta(dlg) -> None:
    """Apunta de quién cuelga el diálogo mostrado."""
    visto["transient"] = str(dlg.wm_transient() or "")


uitk.mostrar = lambda dlg, parent=None: (mirar_suelta(dlg), dlg.destroy())
try:
    uitk.working(raiz, "probando", lambda: "hecho", "Un mensaje.", suelto=True)
finally:
    uitk.mostrar = MOSTRAR_REAL
c("y working(suelto=True) la crea así", visto["transient"], "")

raiz.destroy()
sys.exit(c.report())
