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
"""

from __future__ import annotations

import threading
from typing import Any, Callable


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
