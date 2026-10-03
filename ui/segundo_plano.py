#!/usr/bin/env python3
"""Lo que una pantalla espera de la red, en otro hilo y sin Tkinter.

Las pantallas que dependen del remoto (Parejas, «Dispositivos…») se abren con
lo que ya tienen a mano y piden lo del remoto aquí: la ventana se ve y responde
mientras rclone espera a un servidor que puede no estar. El hilo solo corre la
función y deja lo que devuelve en un `Encargo`; quien lo recoge es el hilo de
Tk, que lo sondea (`ui.tk.Sondeo`). Es la regla de `tk.working()` sin su
ventanita: a Tk solo se le habla desde su hilo.

La función que se encarga no puede llevar dentro ningún objeto de Tk, ni
siquiera en un cierre: si el hilo soltara la última referencia a una imagen o a
un widget, Tcl lo liberaría fuera de su hilo (`Tcl_AsyncDelete`). Por eso las
pantallas encargan `functools.partial(funcion, datos)` y no un `lambda` escrito
entre sus widgets.

`lanzar()` es de módulo a propósito: los tests la sustituyen por `en_el_acto()`
y el resultado ya está puesto cuando la pantalla se enseña.

Una lectura que escribe en disco (el catálogo deja su copia en `state/`) no
debe tener dos hilos vivos a la vez: cerrar la pantalla no mata al hilo, así
que abrirla otra vez, o releer con ella abierta, juntaba dos. `lanzar_sin_repetir()`
es el único paso por donde pasan esas pantallas.
"""

from __future__ import annotations

import copy
import threading
from typing import Any, Callable, Hashable


class Encargo:
    """Una función que corre aparte, con su resultado para quien la sondea.

    El hilo escribe y el de Tk lee: `hecho` se pone el último, así que quien lo
    ve a `True` tiene ya `resultado` o `error`.

    Args:
        funcion: El trabajo, sin argumentos y sin nada de Tk dentro.

    Attributes:
        hecho: Si ha terminado, bien o mal.
        resultado: Lo que devolvió la función.
        error: La excepción que lanzó, o `None` si acabó bien.
    """

    def __init__(self, funcion: Callable[[], Any]) -> None:
        """Prepara el encargo sin correrlo."""
        self._funcion: Callable[[], Any] | None = funcion
        self.hecho = False
        self.resultado: Any = None
        self.error: Exception | None = None

    def correr(self) -> None:
        """Corre la función y apunta lo que devuelva o lo que lance.

        Se suelta la función al acabar: el hilo no se queda con nada de quien
        hizo el encargo.
        """
        try:
            self.resultado = self._funcion() if self._funcion is not None else None
        except Exception as e:                       # se le enseña a quien sondea
            self.error = e
        finally:
            self._funcion = None
            self.hecho = True


def lanzar(funcion: Callable[[], Any]) -> Encargo:
    """Corre `funcion` en un hilo aparte y devuelve el encargo para sondearlo.

    El hilo es `daemon`: cerrar la aplicación no espera a un remoto que no
    contesta. Es un punto de indirección: los tests lo sustituyen por
    `en_el_acto()`.
    """
    encargo = Encargo(funcion)
    threading.Thread(target=encargo.correr, daemon=True).start()
    return encargo


def en_el_acto(funcion: Callable[[], Any]) -> Encargo:
    """Corre `funcion` aquí mismo y devuelve el encargo ya terminado.

    Es lo que ponen los tests en lugar de `lanzar()`: sin bucle de eventos, un
    resultado que llega por sondeo no llegaría nunca.
    """
    encargo = Encargo(funcion)
    encargo.correr()
    return encargo


_EN_VUELO: dict[Hashable, tuple[Any, Encargo]] = {}
"""La lectura viva de cada clave: `(firma, encargo)`, la última que se lanzó."""


def lanzar_sin_repetir(clave: Hashable, firma: Any,
                       funcion: Callable[[], Any]) -> Encargo:
    """Lanza `funcion`, o devuelve el encargo vivo de la misma lectura si lo hay.

    Mientras el hilo de una lectura no haya acabado, pedir la misma otra vez
    (la pantalla se cerró y se abrió, o se pulsó «Releer») no arranca otro: se
    devuelve el que corre y quien lo pida lo espera, con lo que lo recoge la
    última pantalla que lo pidió. Dos hilos del mismo catálogo se pisarían al
    dejar su copia local.

    «La misma» es misma clave y misma `firma`: con otra (el catálogo apunta a
    otro remoto desde que se lanzó el vivo) el resultado del vivo no sirve, y
    como a un hilo no se le puede cortar se lanza uno nuevo, que pasa a ser el
    que se reutiliza.

    Args:
        clave: Qué se lee, p. ej. `"catalogo"` o `"flota"`.
        firma: Los datos de los que depende la lectura (el config en bruto). Se
            copia: lo que cambie luego en quien llama no altera la comparación.
        funcion: El trabajo, con las mismas condiciones que en `lanzar()`.

    Returns:
        El encargo, nuevo o el que ya corría.
    """
    vivo = _EN_VUELO.get(clave)
    if vivo is not None and not vivo[1].hecho and vivo[0] == firma:
        return vivo[1]
    encargo = lanzar(funcion)
    _EN_VUELO[clave] = (copy.deepcopy(firma), encargo)
    return encargo
