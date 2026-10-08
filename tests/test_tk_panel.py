#!/usr/bin/env python3
"""Lo que una pantalla que no se ve deja de gastar: pausar `Sondeo` e `Indicador`.

«Ajustes» conserva los apartados ya dibujados y esconde el que se deja; un
apartado escondido no puede seguir mirando un encargo cada 120 ms ni animando
su barra a 31 pasos por segundo. `Panel.ocultado()` los para y
`Panel.mostrado()` los reanuda, sin perder el encargo que esperaban.

Se comprueba, con Tk de verdad y hilos de verdad:

- un `Sondeo` pausado no deja ningún `after` pendiente, conserva el encargo y,
  al seguir, llama en el acto si terminó o vuelve a mirar si no;
- `cada` es lo que se pide a `after` (se envuelve `after`: no se cuentan
  miradas, que dependerían del reloj);
- un `Indicador` pausado tiene la barra parada y la frase intacta, y no se
  arranca sola si se le habla mientras está pausado;
- `Panel.sondeo()`/`indicador()` quedan registrados, `ocultado()`/`mostrado()`
  los pausan y reanudan antes de llamar a los `al_ocultar`/`al_mostrar`;
- destruir el marco sigue cancelando sus esperas;
- las pantallas que reciben la lectura compartida aceptan `compartida=None`
  (la parte sin Tk va primero y corre aunque no haya pantalla).
"""

import inspect
import sys
import threading
import time

from _harness import Checks

c = Checks("pausar lo que espera una pantalla que no se ve")


# 0. la lectura compartida: el parámetro existe, al final y a `None`
from ui import tk_doctor, tk_pairs, tk_repair  # noqa: E402


def ultimo_parametro(funcion):
    """Devuelve `(nombre, defecto)` del último parámetro de `funcion`."""
    parametros = list(inspect.signature(funcion).parameters.values())
    return parametros[-1].name, parametros[-1].default


for nombre, funcion in (("tk_pairs.open_dialog", tk_pairs.open_dialog),
                        ("tk_doctor.open_dialog", tk_doctor.open_dialog),
                        ("tk_repair.open_dialog", tk_repair.open_dialog),
                        ("tk_repair.construir", tk_repair.construir)):
    c(f"{nombre} acepta `compartida=None` como último parámetro",
      ultimo_parametro(funcion), ("compartida", None))
c("  y `tk_doctor.open_dialog` sigue teniendo `marcadas` justo antes",
  list(inspect.signature(tk_doctor.open_dialog).parameters)[-2:],
  ["marcadas", "compartida"])
c("  igual que `tk_repair.open_dialog`",
  list(inspect.signature(tk_repair.open_dialog).parameters)[-2:],
  ["marcadas", "compartida"])

try:
    import tkinter as tk
    from tkinter import ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from ui import segundo_plano  # noqa: E402
from ui import tk as uitk  # noqa: E402

errores: list[str] = []
raiz.report_callback_exception = (
    lambda tipo, valor, _tb: errores.append(f"{tipo.__name__}: {valor}"))

RITMO = (uitk.PASO_BARRA_MS, uitk.SALTO_BARRA)
"""Con lo que arranca la barra de un `Indicador` que espera."""


def dar_vueltas(condicion, limite: float = 2.0) -> bool:
    """Mueve el bucle de Tk hasta que se cumpla la condición o pase el límite."""
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        raiz.update()
        if condicion():
            return True
        time.sleep(0.01)
    return False


def pendientes() -> tuple:
    """Los `after` que Tk tiene pendientes."""
    return raiz.tk.splitlist(raiz.tk.call("after", "info"))


def ritmo(barra):
    """Devuelve `(intervalo, salto)` con que Tcl tiene en marcha la barra, o `None`."""
    try:
        pendiente = barra.tk.eval(f"set ::ttk::progressbar::Timers({barra})")
    except tk.TclError:                                  # parada: no hay temporizador
        return None
    guion = barra.tk.splitlist(barra.tk.call("after", "info", pendiente)[0])
    return float(str(guion[-2])), float(str(guion[-1]))


def vigilar_after(ventana) -> list:
    """Envuelve `ventana.after` y devuelve la lista de retardos que se le piden."""
    pedidos: list = []
    original = ventana.after

    def after(ms, *args):
        """Apunta el retardo y llama al `after` de verdad."""
        pedidos.append(ms)
        return original(ms, *args)

    ventana.after = after
    return pedidos


def pendiente():
    """Un encargo que no termina hasta que se suelte el `Event` que devuelve."""
    soltar = threading.Event()
    return segundo_plano.lanzar(lambda: soltar.wait(5)), soltar


# 1. el sondeo, pausado
top = tk.Toplevel(raiz)
top.withdraw()
sondeo = uitk.Sondeo(top)
llegados: list = []

encargo, soltar = pendiente()
sondeo.esperar(encargo, llegados.append)
espera = sondeo._id
c("esperando un encargo, su `after` está pendiente", espera in pendientes(), True)
sondeo.pausar()
c("pausado, su `after` ya no está pendiente", espera in pendientes(), False)
c("  ni programa otro", sondeo._id, None)
c("  pero sigue esperando: guarda el encargo y la llamada",
  (sondeo.esperando, sondeo._encargo is encargo), (True, True))
soltar.set()
dar_vueltas(lambda: encargo.hecho)
raiz.update()
c("terminado el encargo con el sondeo pausado, nadie llama", llegados, [])
c("  y sigue sin `after`", sondeo._id, None)
sondeo.seguir()
c("al seguir, con el encargo ya hecho, llama en el acto", llegados, [encargo])
c("  y ya no espera nada", (sondeo.esperando, sondeo._id), (False, None))
sondeo.seguir()
c("`seguir()` sin nada que esperar no hace nada", (llegados, sondeo._id), ([encargo], None))

encargo, soltar = pendiente()
sondeo.esperar(encargo, llegados.append)
sondeo.pausar()
sondeo.pausar()
c("pausar dos veces es lo mismo que una", (sondeo.esperando, sondeo._id), (True, None))
sondeo.seguir()
nuevo = sondeo._id
c("al seguir con el encargo sin terminar, vuelve a mirar luego",
  (nuevo is not None and nuevo in pendientes(), len(llegados)), (True, 1))
sondeo.seguir()
c("  y seguir otra vez no programa otro `after`", sondeo._id, nuevo)
soltar.set()
c("  y lo recoge, desde el hilo de Tk, cuando termina",
  dar_vueltas(lambda: len(llegados) == 2), True)
c("  que era el suyo", llegados[-1], encargo)

# Hablarle a un sondeo pausado: el encargo queda guardado, sin `after`.
sondeo.pausar()
encargo, soltar = pendiente()
sondeo.esperar(encargo, llegados.append)
c("un encargo nuevo con el sondeo pausado queda guardado, sin `after`",
  (sondeo.esperando, sondeo._id), (True, None))
listo = segundo_plano.en_el_acto(lambda: "ya")
sondeo.esperar(listo, llegados.append)
c("  y uno que ya terminó se recoge en el acto, que no cuesta ninguna mirada",
  (llegados[-1], sondeo.esperando), (listo, False))
encargo, soltar = pendiente()
sondeo.esperar(encargo, llegados.append)
sondeo.seguir()
c("  y al seguir, el que esperaba se mira de nuevo",
  sondeo._id in pendientes(), True)
sondeo.cancelar()
soltar.set()

# Cancelar pausado no deja rastro, y destruir la ventana también.
sondeo.pausar()
encargo, soltar = pendiente()
sondeo.esperar(encargo, llegados.append)
sondeo.cancelar()
sondeo.seguir()
c("cancelar un sondeo pausado olvida el encargo: seguir no llama a nadie",
  (sondeo.esperando, sondeo._id), (False, None))
soltar.set()

encargo, soltar = pendiente()
sondeo.esperar(encargo, llegados.append)
sondeo.pausar()
cuantos = len(llegados)
top.destroy()
c("destruir la ventana de un sondeo pausado cancela la espera",
  sondeo.esperando, False)
sondeo.seguir()
sondeo.pausar()
c("  y pausar o seguir después no falla", (errores, len(llegados)), ([], cuantos))
soltar.set()

# 2. `cada`: lo que se pide a `after`
top = tk.Toplevel(raiz)
top.withdraw()
retardos = vigilar_after(top)
por_defecto = uitk.Sondeo(top)
encargo, soltar = pendiente()
por_defecto.esperar(encargo, llegados.append)
c("sin `cada`, mira cada `SONDEO_MS`", retardos, [uitk.SONDEO_MS])
c("  que es lo de siempre", uitk.SONDEO_MS, 120)
por_defecto.cancelar()

rapido = uitk.Sondeo(top, cada=20)
del retardos[:]
rapido.esperar(encargo, llegados.append)
c("con `cada=20`, la primera mirada se pide a 20 ms", retardos, [20])
rapido._mirar()
c("  y al mirar sin que haya terminado, la siguiente también", retardos, [20, 20])
rapido.pausar()
rapido.seguir()
c("  y al seguir tras una pausa, también", retardos, [20, 20, 20])
rapido.cancelar()
soltar.set()
top.destroy()


# 3. el indicador, pausado
top = tk.Toplevel(raiz)
top.withdraw()
indicador = uitk.Indicador(top)
indicador.marco.grid()
indicador.poner("leyendo…", True)
c("el indicador que espera tiene la barra en marcha", ritmo(indicador.barra), RITMO)
indicador.pausar()
c("pausado, la barra está parada", ritmo(indicador.barra), None)
c("  la frase sigue, y la barra sigue puesta",
  (indicador.texto.cget("text"), indicador.esperando), ("leyendo…", True))
indicador.pausar()
c("  pausar otra vez no cambia nada", ritmo(indicador.barra), None)
indicador.seguir()
c("al seguir, la barra vuelve a ir y venir, al mismo ritmo",
  ritmo(indicador.barra), RITMO)
indicador.seguir()
c("  y seguir otra vez tampoco cambia nada", ritmo(indicador.barra), RITMO)

indicador.pausar()
indicador.poner("otra frase", True)
c("hablarle a un indicador pausado cambia la frase pero no arranca la barra",
  (indicador.texto.cget("text"), ritmo(indicador.barra), indicador.esperando),
  ("otra frase", None, True))
indicador.seguir()
c("  y al seguir arranca", ritmo(indicador.barra), RITMO)

indicador.pausar()
indicador.poner("por qué no hay red", False)
indicador.seguir()
c("si dejó de esperar mientras estaba pausado, seguir no arranca la barra",
  (ritmo(indicador.barra), indicador.esperando, indicador.texto.cget("text")),
  (None, False, "por qué no hay red"))

indicador.poner("", False)
indicador.pausar()
indicador.seguir()
c("uno sin nada que decir sigue sin línea", bool(indicador.marco.grid_info()), False)

indicador.poner("leyendo…", True)
top.destroy()
indicador.pausar()
indicador.seguir()
c("pausar o seguir un indicador cuya ventana se destruyó no falla", errores, [])


# 4. el panel
dlg = tk.Toplevel(raiz)
dlg.withdraw()
marco = ttk.Frame(dlg)
marco.grid()
panel = uitk.Panel(dlg, marco, incrustado=True)
mi_sondeo = panel.sondeo()
otro_sondeo = panel.sondeo()
mi_indicador = panel.indicador(marco, 300)
mi_indicador.marco.grid()
c("`panel.sondeo()` cuelga del marco del panel, y cada llamada es uno nuevo",
  (isinstance(mi_sondeo, uitk.Sondeo), mi_sondeo.ventana is marco,
   mi_sondeo is not otro_sondeo), (True, True, True))
c("`panel.indicador(padre, ancho)` dibuja un `Indicador` en `padre`",
  (isinstance(mi_indicador, uitk.Indicador), str(mi_indicador.marco.master) == str(marco)),
  (True, True))

llegados.clear()
encargo, soltar = pendiente()
mi_sondeo.esperar(encargo, llegados.append)
mi_indicador.poner("leyendo…", True)
espera = mi_sondeo._id

visto: list = []


def al_ocultar_1() -> None:
    """Apunta qué había parado cuando se la llamó."""
    visto.append(("ocultar 1", mi_sondeo._id is None, ritmo(mi_indicador.barra)))


def al_ocultar_2() -> None:
    """La segunda, para ver el orden."""
    visto.append(("ocultar 2",))


def al_mostrar_1() -> None:
    """Apunta qué había en marcha cuando se la llamó."""
    visto.append(("mostrar 1", mi_sondeo._id is not None, ritmo(mi_indicador.barra)))


panel.al_ocultar(al_ocultar_1)
panel.al_ocultar(al_ocultar_2)
panel.al_mostrar(al_mostrar_1)
c("registrar los `al_mostrar`/`al_ocultar` no llama a ninguno", visto, [])
c("  ni para nada de lo que espera",
  (mi_sondeo._id, ritmo(mi_indicador.barra)), (espera, RITMO))

panel.ocultado()
c("`ocultado()` para el sondeo, que sigue esperando, y el indicador",
  (espera in pendientes(), mi_sondeo.esperando, ritmo(mi_indicador.barra)),
  (False, True, None))
c("  y llama a cada `al_ocultar`, una vez y en orden, con todo ya parado",
  visto, [("ocultar 1", True, None), ("ocultar 2",)])

soltar.set()
dar_vueltas(lambda: encargo.hecho)
raiz.update()
c("lo que termina mientras está oculto no se recoge", llegados, [])

del visto[:]
panel.mostrado()
c("`mostrado()` recoge lo que terminó mientras tanto", llegados, [encargo])
c("  reanuda el indicador y llama a `al_mostrar` con todo ya en marcha",
  (ritmo(mi_indicador.barra), visto), (RITMO, [("mostrar 1", False, RITMO)]))

# Sin haberse ocultado nunca, `mostrado()` no cambia nada.
encargo, soltar = pendiente()
mi_sondeo.esperar(encargo, llegados.append)
espera = mi_sondeo._id
panel.mostrado()
c("`mostrado()` con todo en marcha no reprograma nada",
  (mi_sondeo._id, ritmo(mi_indicador.barra)), (espera, RITMO))

# Destruir el marco sigue cancelando sus esperas, y el panel lo soporta.
marco.destroy()
c("destruir el marco cancela los sondeos del panel (la regla de siempre)",
  (mi_sondeo.esperando, espera in pendientes()), (False, False))
panel.ocultado()
panel.mostrado()
c("  y ocultar o mostrar después un panel sin marco no falla", errores, [])
soltar.set()
dlg.destroy()

# Un panel suelto, sin nada registrado, no cambia de comportamiento.
dlg = tk.Toplevel(raiz)
dlg.withdraw()
marco = ttk.Frame(dlg)
marco.grid()
solo = uitk.Panel(dlg, marco)
solo.ocultado()
solo.mostrado()
c("un panel sin sondeos ni callbacks se oculta y se muestra sin hacer nada", errores, [])
dlg.destroy()

sys.exit(c.report())
