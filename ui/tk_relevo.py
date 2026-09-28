#!/usr/bin/env python3
"""
tk_relevo.py — La ventanita del relevo, mientras cambia el Python de la ventana.

Solo dibuja. El relevo (`cmd_relevo()` en `prdrive-install.py`) corre sin
consola y con la ventana principal ya cerrada, y tarda: esperar a que salga,
extraer 48 MB en un USB, colocarlos. Sin nada en pantalla, lo natural es volver
a abrir prdrive —que corre justo desde la carpeta que hay que cambiar— y
pulsar «Actualizar…» otra vez, que es lo que pasó en G:. Esto lo enseña.

Es `tk.working()` colgado de una raíz oculta (`tk.root_oculto()`), que se
destruye al terminar, antes de que el relevo reabra prdrive o enseñe su
informe. Lo que dice la barra lo mide `install.components.AvanceRelevo`.
"""

from __future__ import annotations

from .tk import root_oculto, working


def mientras(mensaje: str, funcion, progreso) -> tuple[bool, object]:
    """Ejecuta `funcion()` con la ventanita delante. Lanza si no hay Tk o
    pantalla: quien llama hace entonces el trabajo sin ella."""
    raiz = root_oculto()
    try:
        return working(raiz, "Actualizando", funcion, mensaje, progreso, suelto=True)
    finally:
        raiz.destroy()
