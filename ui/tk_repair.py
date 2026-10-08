#!/usr/bin/env python3
"""«Reparación»: lo que está mal y qué hacer con ello.

Solo dibuja. Qué está mal lo dice `common/revision.py` y qué se puede hacer con
ello lo decide `ui/repair.py`; aquí se pinta una fila por avería con su botón
al lado y se pide confirmación con `tk_pairs.confirmar_plan()`, que es la misma
ventana que gobierna todos los borrados de la aplicación.

Esta pantalla sustituye a tres recuadros ámbar de la ventana principal (los
fallos, los conflictos y el aviso de resync), que apilados dejaban de ser
jerarquía para ser ruido. Allí queda una línea que dice cuántas cosas hay y
trae aquí.

Hay dos cosas que no puede hacer, a propósito:
- **No repara sola.** Ni al abrirse ni al pulsar: todo plan enseña sus
  consecuencias y espera un sí. Apartar un baseline es la operación que puede
  acabar en un borrado masivo, y por eso se quitó el renombrado automático de
  listados.
- **No repara mientras se sincroniza.** Mover ficheros o apartar un baseline
  bajo los pies de rclone es exactamente lo que no puede pasar, así que la
  ventana principal no deja abrir esto durante una pasada y `repair` vuelve a
  mirarlo antes de borrar un bloqueo.

`lanzar` llega de la ventana principal, como en «Ajustes»: la salida de una
pasada se enseña en la ventana de salida, que es hija de la principal y se
apaga sola mientras hay otra en curso. Esta pantalla se cierra antes de ceder
el paso, porque dos modales no pueden tener la captura a la vez.
"""

from __future__ import annotations

from common import revision
from common.model import Config

from . import abrir, repair, theme
from .tk import TITLE, Panel, cabecera, dialogo, mostrar, pie, separador_fila

SEMAFORO = {
    revision.GRAVE: ("warn", "Peligro.", "grave"),
    revision.AVISO: ("warn", "Aviso.", "hay que hacer algo"),
    revision.NOTA: ("clock", "Apagado.", "se arregla sola"),
}
"""Por gravedad: el icono, el estilo del chip y el rótulo del chip."""

TODO_BIEN = ("No hay nada que revisar: las parejas tienen su baseline, no hay "
             "conflictos y la última pasada de cada una fue bien.")
"""Lo que se dice cuando no hay nada que revisar."""

BOTONES = {
    "prefijo": "Apartar el baseline…",
    "lock": "Borrar los bloqueos…",
    "resync": "Resincronizar…",
    "fallo": "Ver el log",
}
"""Qué botón lleva cada avería.

Lo que no está aquí no tiene botón, y eso también es una respuesta: la carpeta
local que falta no se arregla creándola.
"""


def open_dialog(parent, config: Config, lanzar, marcadas=None, compartida=None) -> bool:
    """Abre «Reparación» y devuelve si se ha cambiado algo del dispositivo.

    Es `True` para que quien llama vuelva a leer `state/` y repinte.

    Args:
        config: La configuración del dispositivo.
        lanzar: `lanzar(titulo, args)`, el de la ventana principal.
        marcadas: Las parejas elegidas en la ventana principal; es lo que se
            simula si se pide una pasada de prueba. Sin ellas, todas.
        compartida: La lectura compartida de la ventana principal
            (`ui.instantanea.Compartida`), o `None`. Todavía no se usa.
    """
    return dialogo(parent, "Reparación",
                   lambda p: construir(p, config, lanzar, marcadas),
                   defecto=False, ensenar=mostrar)


def construir(panel: Panel, config: Config, lanzar, marcadas=None, compartida=None) -> None:
    """Dibuja «Reparación» en `panel` (su diálogo o «Ajustes»).

    Devuelve `True` por el panel si cambia algo del dispositivo. Lo que lanza
    una pasada cierra antes la ventana entera (`panel.cerrar`): la de salida es
    hija de la principal.

    Args:
        panel: Dónde se dibuja.
        config: La configuración del dispositivo.
        lanzar: `lanzar(titulo, args)`, el de la ventana principal.
        marcadas: Las parejas elegidas en la ventana principal, para la
            pasada de prueba.
        compartida: La lectura compartida de la ventana principal
            (`ui.instantanea.Compartida`), o `None`. Todavía no se usa.
    """
    from tkinter import messagebox, ttk

    from . import tk_conflicts, tk_pairs

    dlg, marco = panel.ventana, panel.marco
    estado: dict = {"hallazgos": []}

    cabecera(marco, "Reparación",
             "Lo que está mal en este dispositivo, y lo que se puede hacer con "
             "ello. Nada se toca sin que lo confirmes antes.",
             ancho=600, estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")

    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(theme.E4, theme.E3, theme.E4, theme.E3))
    tarjeta.grid(row=1, column=0, sticky="ew", pady=(theme.E4, 0))
    tarjeta.columnconfigure(0, weight=1)

    # Las acciones.

    def aplicar(hallazgo) -> None:
        """Hace un plan de disco: se piensa, se enseña y solo entonces se ejecuta."""
        try:
            plan = repair.plan_para(config, hallazgo)
        except repair.ReparacionImposible as e:
            messagebox.showerror(TITLE, str(e), parent=dlg)
            repintar()
            return
        if not tk_pairs.confirmar_plan(dlg, plan, plan.titulo, ""):
            return
        try:
            hechos = plan.execute()
        except repair.ReparacionImposible as e:
            messagebox.showerror(TITLE, str(e), parent=dlg)
            repintar()
            return
        panel.devolver(True)
        repintar()
        messagebox.showinfo(TITLE, "\n".join(hechos) or "Hecho.", parent=dlg)

    def resincronizar(hallazgo) -> None:
        """Pide confirmación y lanza el resync en la ventana de salida.

        No es un plan de disco sino una pasada de rclone, con su log y su
        registro, así que se lanza como cualquier otra. La confirmación se hace
        igual, que un resync compara los dos lados enteros.
        """
        if not tk_pairs.confirmar_plan(dlg, repair.aviso_resync(hallazgo),
                                       f"Resincronizar «{hallazgo.pareja}»", ""):
            return
        panel.devolver(True)
        panel.cerrar(lambda: lanzar(f"Resincronizar «{hallazgo.pareja}»",
                                    repair.args_resync(hallazgo)))

    def ver_log(hallazgo) -> None:
        """Abre el log de la pasada que falló, si quedó."""
        ruta = hallazgo.dato[0] if hallazgo.dato else None
        if ruta is None:
            messagebox.showinfo(TITLE, "De aquella pasada no quedó log: solo se "
                                       "guardan los de las que fallan, y este ya "
                                       "no está.", parent=dlg)
            return
        try:
            abrir(ruta)
        except OSError as e:
            messagebox.showerror(TITLE, f"No se ha podido abrir:\n\n{ruta}\n\n{e}",
                                 parent=dlg)

    ACCIONES = {"prefijo": aplicar, "lock": aplicar,
                "resync": resincronizar, "fallo": ver_log}

    # La lista de averías.

    def fila(padre, hallazgo, linea: int) -> int:
        """Pinta una avería con su detalle y devuelve la siguiente fila libre."""
        icono, chip, rotulo = SEMAFORO.get(hallazgo.gravedad, SEMAFORO[revision.AVISO])
        cabeza = ttk.Frame(padre, style="Plano.Card.TFrame")
        cabeza.grid(row=linea, column=0, sticky="ew", pady=(theme.E2, 0))
        cabeza.columnconfigure(1, weight=1)
        linea += 1

        marca = theme.etiqueta_icono(
            cabeza, icono, theme.AVISO if hallazgo.gravedad != revision.NOTA
            else theme.TINTA3, "fuerte", 16, superficie="Card.")
        marca.grid(row=0, column=0, sticky="w", padx=(0, theme.E2))
        ttk.Label(cabeza, text=hallazgo.titulo, style="Card.Fuerte.TLabel",
                  wraplength=theme.medida(420), justify="left").grid(
            row=0, column=1, sticky="w")
        theme.chip(cabeza, rotulo, chip).grid(row=0, column=2, sticky="e", padx=(theme.E3, 0))

        texto = BOTONES.get(hallazgo.clave)
        if texto is not None:
            boton = ttk.Button(cabeza, text=texto, style="CardQuiet.TButton",
                               command=lambda h=hallazgo: ACCIONES[h.clave](h))
            boton.grid(row=0, column=3, sticky="e", padx=(theme.E3, 0))

        ttk.Label(padre, text=hallazgo.detalle, style="Card.Pista.TLabel",
                  justify="left", wraplength=theme.medida(560)).grid(
            row=linea, column=0, sticky="w", pady=(theme.E1, theme.E2))
        return linea + 1

    def repintar() -> None:
        """Vuelve a mirar el dispositivo y redibuja la lista.

        Se relee entero en vez de tachar la fila que se acaba de arreglar: una
        reparación cambia el estado y lo que había antes en la pantalla es de
        antes. Que la lista encoja es la señal de que ha funcionado.
        """
        for hijo in tarjeta.winfo_children():
            hijo.destroy()
        try:
            estado["hallazgos"] = revision.revisar(config)
        except Exception as e:                                  # noqa: BLE001
            estado["hallazgos"] = []
            ttk.Label(tarjeta, text=f"No he podido mirar el estado: {e}",
                      style="Card.Aviso.TLabel").grid(row=0, column=0, sticky="w")
            return

        # Los conflictos no salen aquí: tienen su propio bloque debajo, con la
        # lista de ficheros y sus versiones, que es lo que hace falta para
        # elegir. Una fila que dijera «hay 3» y no dejara hacer nada sobraría.
        lista = [h for h in estado["hallazgos"] if h.clave != "conflicto"]
        if not lista:
            ttk.Label(tarjeta, text=TODO_BIEN, style="Card.Pista.TLabel",
                      justify="left", wraplength=theme.medida(560)).grid(
                row=0, column=0, sticky="w", pady=(theme.E1, theme.E1))
        linea = 0
        for i, hallazgo in enumerate(lista):
            if i:
                separador_fila(tarjeta, linea, 1)
                linea += 1
            linea = fila(tarjeta, hallazgo, linea)

        conflictos.grid_remove()
        if any(h.clave == "conflicto" for h in estado["hallazgos"]):
            conflictos.grid()
        if panel.incrustado:
            panel.ajustar()
            return
        visor = getattr(dlg, "visor", None)
        if visor is not None:
            visor.encajar(dlg)

    def al_resolver() -> None:
        """Anota el cambio y repinta tras resolver un conflicto."""
        panel.devolver(True)
        repintar()

    conflictos = tk_conflicts.seccion(marco, dlg, config, al_resolver)
    conflictos.grid(row=2, column=0, sticky="ew", pady=(theme.E4, 0))

    # El pie.

    def simular() -> None:
        """Cierra y lanza una pasada de mentira de las parejas marcadas."""
        nombres = list(marcadas or [p.name for p in config.pairs])
        if not nombres:
            return
        panel.cerrar(lambda: lanzar("Simulación", repair.args_simular(nombres)))

    def informe() -> None:
        """Cierra y lanza el informe completo del estado (`--doctor`)."""
        panel.cerrar(lambda: lanzar("Informe del estado", ["--doctor"]))

    botones = pie(marco, 3)
    botones.columnconfigure(2, weight=1)
    # «Simular» vive aquí y no en la ventana principal: es lo que se hace ANTES
    # de sincronizar cuando algo no cuadra, y esta es la pantalla de «a ver qué
    # hay». No escribe nada, así que no necesita ceremonia.
    simula = ttk.Button(botones, text="Simular una pasada…", style="Quiet.TButton",
                        command=simular)
    theme.boton_icono(simula, "eye", theme.ACENTO, theme.PAPEL)
    simula.grid(row=0, column=0, sticky="w")
    ver = ttk.Button(botones, text="Ver el informe completo", style="Quiet.TButton",
                     command=informe)
    theme.boton_icono(ver, "doctor", theme.ACENTO, theme.PAPEL)
    ver.grid(row=0, column=1, sticky="w", padx=(theme.E2, 0))
    ttk.Button(botones, text="Cerrar", command=panel.cerrar).grid(row=0, column=3,
                                                                  sticky="e")

    repintar()
