#!/usr/bin/env python3
"""
tk_doctor.py — «Ajustes»: lo que se hace de vez en cuando y no cada vez.

Hasta aquí «Doctor» era un botón que lanzaba `sync.py --doctor` y nada más. Se
convirtió en una pantalla por una razón concreta: la ventana principal ya está
llena —sus avisos, la lista de parejas, el intervalo, tres botones y dos
acciones— y todo lo que se hace una vez en la vida del dispositivo tiene que
caber en algún sitio que no sea esa ventana. Esta es ese sitio.

En la ventana se llama «Ajustes», detrás de un engranaje, y no «Doctor»: el
doctor es una de sus entradas —la primera—, no la pantalla, y aquí es donde irá
también lo que se configure. El módulo conserva su nombre porque el subcomando
`sync.py --doctor` no cambia y porque es a esta pantalla a la que apunta el
rediseño de la pantalla de reparación.

Solo dibuja, y menos que ninguna otra: no lee estado, no escribe nada y no
decide nada. Cada entrada es un botón y una frase que dice qué pasa al pulsarlo;
lo que pasa lo hace el módulo de turno. La única casilla, «Pedir la contraseña
al iniciar sesión» de la raíz cifrada de un equipo, también: lo que vale y cómo
se le pide al agente es de `ui/watch.py`.

`lanzar` llega desde la ventana principal en vez de importarse: la comprobación
se enseña en su ventana de salida, que es hija de la principal y no de esta, y
que además se apaga sola mientras hay otra pasada en curso. Esta pantalla no
tiene por qué saber nada de eso.
"""

from __future__ import annotations

from common.model import Config

from . import theme, watch
from .tk import TITLE, cabecera, cuerpo_visible, modal, mostrar, separador_fila

# rótulo del botón, icono, frase, clave de la acción
ENTRADAS = (
    ("Reparación…", "doctor",
     "Lo que está mal en este dispositivo y qué hacer con ello: baselines que no "
     "son de su pareja, bloqueos sueltos, ficheros en conflicto. Nada se toca "
     "sin confirmarlo.",
     "reparacion"),
    ("Emparejar un móvil…", "dispositivo",
     "Enseña la conexión con el remoto como código QR para que la lea otro "
     "aparato. Lleva la clave privada dentro: el código avisa.",
     "qr"),
    ("Versiones…", "file",
     "Lo guardado en .prversions/ por las parejas que versionan: cuánto ocupa "
     "en cada lado, abrir la carpeta de aquí y purgar lo anterior a una fecha.",
     "versiones"),
    ("Nombre e icono de la unidad…", "edit",
     "Cómo la enseña el Explorador de Windows al conectarla. Útil para "
     "distinguir un dispositivo de otro a simple vista.",
     "volumen"),
)


def open_dialog(parent, config: Config, lanzar, raw_local: dict | None = None,
                abrir_reparacion=None) -> None:
    """Abre «Ajustes». `lanzar(titulo, args)` es el de la ventana principal.

    No devuelve nada: de aquí no sale ninguna decisión que quien llama tenga que
    repintar. Lo que cambia estado —si algún día algo lo hace— abrirá su propia
    ventana y se encargará él.

    `abrir_reparacion` llega de la ventana principal por lo mismo que `lanzar`:
    «Reparación» puede acabar lanzando una pasada, y su ventana de salida es
    hija de la principal, no de esta. Además esta se cierra antes de abrirla,
    para no tener dos modales disputándose la captura del ratón."""
    from tkinter import ttk

    dlg = modal(parent, "Ajustes")
    marco = cuerpo_visible(dlg, padding=(22, 20, 22, 18))
    marco.columnconfigure(0, weight=1)

    cabecera(marco, "Ajustes",
             "Lo que se mira o se hace de tarde en tarde, para que la ventana "
             "principal se quede con lo de todos los días.",
             ancho=560, estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")

    def reparacion() -> None:
        """«Reparación» se abre desde la principal y por eso esta se cierra
        antes: son dos modales, y la de allí puede abrir a su vez la ventana de
        salida, que es hija de la principal."""
        dlg.destroy()
        if abrir_reparacion is not None:
            abrir_reparacion()

    def emparejar() -> None:
        from . import tk_qr
        tk_qr.open_dialog(dlg, raw_local)

    def versiones() -> None:
        from . import tk_versions
        tk_versions.open_dialog(dlg, config)

    def nombre_e_icono() -> None:
        from . import tk_volumen
        tk_volumen.open_dialog(dlg)

    acciones = {"reparacion": reparacion, "qr": emparejar, "versiones": versiones,
                "volumen": nombre_e_icono}

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

    # La raíz cifrada de este equipo: si el agente pide su contraseña al
    # iniciar sesión. Es un ajuste del EQUIPO y no de la raíz, así que no se
    # escribe aquí: se le pide al agente por su buzón. Así lo tiene también
    # quien no tiene bandeja (Linux, hasta la fase 6).
    pedir = watch.pedir_al_iniciar()
    fila_pie = 2
    if pedir is not None:
        import tkinter as tk
        from tkinter import messagebox

        cifrada = ttk.Frame(marco, style="Card.TFrame", padding=(14, 12, 14, 12))
        cifrada.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        cifrada.columnconfigure(0, weight=1)
        marcada = tk.BooleanVar(value=pedir)

        def cambiar() -> None:
            if not watch.pedir_ajuste("pedir_al_iniciar", bool(marcada.get())):
                marcada.set(not marcada.get())
                messagebox.showerror(TITLE, "No he podido dejarle la petición al "
                                     "agente.", parent=dlg)

        ttk.Checkbutton(cifrada, text="Pedir la contraseña al iniciar sesión",
                        variable=marcada, command=cambiar,
                        style="Card.Fuerte.TCheckbutton").grid(row=0, column=0,
                                                              sticky="w")
        ttk.Label(cifrada, style="CardPista.TLabel", justify="left",
                  wraplength=theme.medida(540),
                  text="Al iniciar sesión, el agente le pide a VeraCrypt que abra "
                       "esta carpeta cifrada, una vez. Sin marcar, se queda "
                       "bloqueada hasta que pidas «Desbloquear». Lo guarda el agente "
                       "de este equipo, no la carpeta.").grid(
            row=1, column=0, sticky="w", pady=(3, 0))
        fila_pie = 3

    ttk.Separator(marco, orient="horizontal").grid(row=fila_pie, column=0, sticky="ew",
                                                   pady=(16, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=fila_pie + 1, column=0, sticky="e", pady=(14, 0))
    ttk.Button(pie, text="Cerrar", command=dlg.destroy).grid(row=0, column=0)

    mostrar(dlg, parent)
