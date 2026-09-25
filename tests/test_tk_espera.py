#!/usr/bin/env python3
"""
La ventanita de espera (`ui.tk.working()`) con avance, conducida sin nadie delante.

Crear un contenedor fijo escribe el volumen entero, minutos u horas, y hasta
#46 esa espera era una barra que iba y venía con una estimación que no se movía.
Ahora `working()` acepta un `progreso` y, mientras diga algo, llena la barra y
pone la cifra debajo; cuando deja de decirlo, vuelve a la barra sin cifra. Lo
que se comprueba es ese ir y venir, y lo que no puede pasar nunca: que un
`progreso` que falla deje la ventanita abierta —no se puede cerrar a mano—.

No se entra en el bucle de eventos de verdad: se sustituye `mostrar()` por uno
que va dando vueltas a `update()` mientras cambia lo que dice el avance.
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
    sys.exit(0)

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
        soltar.wait(5)
        return funcion() if funcion else "hecho"

    def falso_mostrar(dlg, parent=None):
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
    return str(dlg.barra.cget("mode"))


# --- 1. sin progreso, la de siempre ------------------------------------------
ok, valor, visto = conducir(lambda dlg: esperar_a(lambda: False, 0.3))
c("sin progreso no hay hueco para la cifra", visto["dlg"].cifra, None)
c("y se cierra sola al terminar", visto["cerrada"], True)
c("devolviendo lo que dio la función", (ok, valor), (True, "hecho"))


# --- 2. con progreso: la barra va y viene, se llena, y vuelve ----------------
dice: dict = {"medida": None, "llamadas": 0}


def progreso():
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
    ronda()
    visto["al_abrir"] = (modo(dlg), str(dlg.cifra.cget("text")))

    dice["medida"] = (0.43, "43 % · quedan unos 25 min")
    ronda()
    visto["con_cifra"] = (modo(dlg), round(float(dlg.barra.cget("value"))),
                          str(dlg.cifra.cget("text")))

    dice["medida"] = None
    ronda()
    visto["sin_cifra"] = (modo(dlg), str(dlg.cifra.cget("text")))

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


# --- 3. un progreso que falla desde el principio no cuelga nada --------------
def roto():
    raise OSError("sin contador")


ok, valor, visto = conducir(lambda dlg: esperar_a(lambda: False, 0.4), progreso=roto)
c("con un progreso roto desde el principio, la barra de siempre",
  visto["cerrada"], True)
c("y el resultado llega igual", (ok, valor), (True, "hecho"))


# --- 4. si la función falla, se devuelve la excepción ------------------------
def falla():
    raise ValueError("no ha ido")


ok, valor, visto = conducir(lambda dlg: None, progreso=lambda: (0.1, "10 %"),
                            funcion=falla)
c("si falla el trabajo, (False, excepción)", (ok, type(valor).__name__),
  (False, "ValueError"))
c("y la ventanita también se cierra", visto["cerrada"], True)

raiz.destroy()
sys.exit(c.report())
