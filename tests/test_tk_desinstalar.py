#!/usr/bin/env python3
"""La ventana del «Desinstalar» de Windows (`ui/tk_desinstalar.py`), conducida sin nadie delante.

Lo que se comprueba es lo que ve y lo que pasa con cada botón: antes de nada
enseña qué se quita y qué se queda; «Cancelar» no toca nada; «Desinstalar»
lo hace con la ventanita de espera delante y luego dice qué ha hecho; si algo
de prdrive sigue abierto, lo dice en rojo. No se entra en el bucle de eventos
de verdad: `mostrar()` se sustituye por uno que lee la ventana y pulsa.
"""

import sys
import time

from _harness import Checks

c = Checks("la ventana de desinstalar")

try:
    import tkinter as tk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from tkinter import ttk  # noqa: E402

from common import presencia  # noqa: E402
from ui import theme, tk_desinstalar  # noqa: E402
from ui import tk as uitk  # noqa: E402

theme.apply(raiz)
MOSTRAR_REAL, ROOT_OCULTO_REAL = uitk.mostrar, uitk.root_oculto


def esperar_a(condicion, limite: float = 10.0) -> bool:
    """Da vueltas al bucle de Tk hasta que se cumpla `condicion` o pase el rato."""
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        raiz.update()
        if condicion():
            return True
        time.sleep(0.02)
    return False


def widgets(w):
    """Recorre `w` y todo lo que cuelga de él."""
    yield w
    for hijo in w.winfo_children():
        yield from widgets(hijo)


def textos(dlg) -> list[str]:
    """Devuelve los textos de las etiquetas y botones del diálogo."""
    salida = []
    for w in widgets(dlg):
        if isinstance(w, (ttk.Label, ttk.Button)):
            texto = str(w.cget("text"))
            if texto:
                salida.append(texto)
    return salida


def boton(dlg, texto: str):
    """Devuelve el botón con ese texto."""
    return next(w for w in widgets(dlg) if isinstance(w, ttk.Button)
                and str(w.cget("text")) == texto)


class Plan:
    """Un plan de desinstalar de mentira: apunta si se ejecuta."""

    def __init__(self, fallo: Exception | None = None) -> None:
        self.consequences = ["Se para el agente.", "Se borra su carpeta, C:\\x\\prdrive."]
        self.warnings = ["La raíz de este equipo se queda en C:\\PRDRIVE."]
        self.fallo = fallo
        self.ejecutado = False

    def execute(self, avance=None) -> list[str]:
        self.ejecutado = True
        if avance is not None:
            avance(0.5, "Esperando a que acabe la pasada de «docs».")
        if self.fallo is not None:
            raise self.fallo
        return ["Ya no arranca al iniciar sesión.", "Las unidades no se han tocado."]


def conducir(plan, acciones: list[str | None]) -> tuple[int, list[list[str]]]:
    """Abre la ventana con `plan` y va pulsando `acciones` (`None`: esperar a que se cierre sola).

    Returns:
        El código de salida y los textos de cada ventana que se ha enseñado.
    """
    vistas: list[list[str]] = []

    def falso_mostrar(dlg, parent=None):
        """Lee el diálogo y pulsa lo que toque, o espera a que se cierre."""
        dlg.deiconify()
        raiz.update()
        vistas.append(textos(dlg))
        accion = acciones.pop(0)
        if accion is None:
            esperar_a(lambda: not dlg.winfo_exists())
        else:
            boton(dlg, accion).invoke()

    def falso_oculto():
        """Una raíz oculta que no es un segundo `Tk()`."""
        oculta = tk.Toplevel(raiz)
        oculta.withdraw()
        return oculta

    uitk.mostrar, uitk.root_oculto = falso_mostrar, falso_oculto
    try:
        rc = tk_desinstalar.main(plan)
    finally:
        uitk.mostrar, uitk.root_oculto = MOSTRAR_REAL, ROOT_OCULTO_REAL
    return rc, vistas


plan = Plan()
rc, vistas = conducir(plan, ["Cancelar"])
c("antes de nada, qué se quita y qué se queda",
  ("Desinstalar prdrive de este equipo" in vistas[0],
   "Se borra su carpeta, C:\\x\\prdrive." in vistas[0],
   "La raíz de este equipo se queda en C:\\PRDRIVE." in vistas[0]), (True, True, True))
c("  con «Desinstalar» y «Cancelar»", ("Desinstalar" in vistas[0], "Cancelar" in vistas[0]),
  (True, True))
c("«Cancelar» no toca nada", (rc, plan.ejecutado, len(vistas)), (tk_desinstalar.NO, False, 1))

plan = Plan()
rc, vistas = conducir(plan, ["Desinstalar", None, "Cerrar"])
c("«Desinstalar»: lo hace con la ventanita de espera delante",
  (plan.ejecutado, "Quitando prdrive de este equipo…" in vistas[1]), (True, True))
c("  y después dice qué ha hecho", ("prdrive se ha desinstalado de este equipo" in vistas[2],
                                    "Las unidades no se han tocado." in vistas[2]), (True, True))
c("  y sale bien", rc, tk_desinstalar.HECHO)

plan = Plan(presencia.DesinstalacionError("Cierra la ventana de prdrive (pid 4321)."))
rc, vistas = conducir(plan, ["Desinstalar", None, "Cerrar"])
c("con algo de prdrive abierto: lo dice, y sale sin desinstalar",
  ("No se ha podido desinstalar" in vistas[2],
   "Cierra la ventana de prdrive (pid 4321)." in vistas[2], rc),
  (True, True, tk_desinstalar.NO))

uitk.root_oculto = lambda: (_ for _ in ()).throw(tk.TclError("no display"))
try:
    c("sin pantalla: SIN_VENTANA, y quien la abrió pregunta por la consola",
      tk_desinstalar.main(Plan()), tk_desinstalar.SIN_VENTANA)
finally:
    uitk.root_oculto = ROOT_OCULTO_REAL

raiz.destroy()
raise SystemExit(c.report())
