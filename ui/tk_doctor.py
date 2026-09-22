#!/usr/bin/env python3
"""
tk_doctor.py — Doctor: lo que se hace de vez en cuando y no cada vez.

Hasta aquí «Doctor» era un botón que lanzaba `sync.py --doctor` y nada más. Se
convierte en una pantalla por una razón concreta: la ventana principal ya está
llena —sus avisos, la lista de parejas, el intervalo, tres botones y dos
acciones— y todo lo que se hace una vez en la vida del dispositivo tiene que
caber en algún sitio que no sea esa ventana. Doctor es ese sitio.

Solo dibuja, y menos que ninguna otra: no lee estado, no escribe nada y no
decide nada. Cada entrada es un botón y una frase que dice qué pasa al pulsarlo;
lo que pasa lo hace el módulo de turno.

`lanzar` llega desde la ventana principal en vez de importarse: la comprobación
se enseña en su ventana de salida, que es hija de la principal y no de esta, y
que además se apaga sola mientras hay otra pasada en curso. Doctor no tiene por
qué saber nada de eso.
"""

from __future__ import annotations

from common.model import Config

from . import theme
from .tk import cabecera, cuerpo_visible, modal, mostrar, separador_fila

# rótulo del botón, icono, frase, clave de la acción
ENTRADAS = (
    ("Ejecutar comprobación", "doctor",
     "Repasa el estado de bisync de cada pareja: el prefijo de su baseline, los "
     "filtros, los bloqueos que hayan quedado sueltos. No toca nada.",
     "doctor"),
    ("Emparejar un móvil…", "dispositivo",
     "Enseña la conexión con el remoto como código QR para que la lea otro "
     "aparato. Lleva la clave privada dentro: el código avisa.",
     "qr"),
    ("Versiones…", "file",
     "Lo guardado en .prversions/ por las parejas que versionan: cuánto ocupa "
     "en cada lado, abrir la carpeta de aquí y purgar lo anterior a una fecha.",
     "versiones"),
)


def open_dialog(parent, config: Config, lanzar, raw_local: dict | None = None) -> None:
    """Abre Doctor. `lanzar(titulo, args)` es el de la ventana principal.

    No devuelve nada: de aquí no sale ninguna decisión que quien llama tenga que
    repintar. Lo que cambia estado —si algún día algo lo hace— abrirá su propia
    ventana y se encargará él."""
    from tkinter import ttk

    dlg = modal(parent, "Doctor")
    marco = cuerpo_visible(dlg, padding=(22, 20, 22, 18))
    marco.columnconfigure(0, weight=1)

    cabecera(marco, "Doctor",
             "Lo que se mira o se hace de tarde en tarde, para que la ventana "
             "principal se quede con lo de todos los días.",
             ancho=560, estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")

    def comprobacion() -> None:
        """La comprobación se enseña en la ventana de salida de la principal, y
        por eso esta se cierra antes: son dos modales y la de salida es hija de
        la otra, así que dejarlas abiertas a la vez pondría la captura del ratón
        en la ventana equivocada."""
        dlg.destroy()
        lanzar("Doctor", ["--doctor"])

    def emparejar() -> None:
        from . import tk_qr
        tk_qr.open_dialog(dlg, raw_local)

    def versiones() -> None:
        from . import tk_versions
        tk_versions.open_dialog(dlg, config)

    acciones = {"doctor": comprobacion, "qr": emparejar, "versiones": versiones}

    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(14, 12, 14, 12))
    tarjeta.grid(row=1, column=0, sticky="ew", pady=(16, 0))
    tarjeta.columnconfigure(0, weight=1)

    fila = 0
    for rotulo, icono, frase, clave in ENTRADAS:
        if fila:
            separador_fila(tarjeta, fila, 1)
            fila += 1
        boton = ttk.Button(tarjeta, text=rotulo, style="CardQuiet.TButton",
                           command=acciones[clave])
        theme.boton_icono(boton, icono, theme.ACENTO, theme.SUPERFICIE)
        boton.grid(row=fila, column=0, sticky="w", pady=(8, 0))
        fila += 1
        ttk.Label(tarjeta, text=frase, style="CardPista.TLabel", justify="left",
                  wraplength=theme.medida(540)).grid(row=fila, column=0,
                                                     sticky="w", pady=(3, 10))
        fila += 1

    ttk.Separator(marco, orient="horizontal").grid(row=2, column=0, sticky="ew",
                                                   pady=(16, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=3, column=0, sticky="e", pady=(14, 0))
    ttk.Button(pie, text="Cerrar", command=dlg.destroy).grid(row=0, column=0)

    mostrar(dlg, parent)
