#!/usr/bin/env python3
"""
tk_repair.py — «Reparación»: lo que está mal y qué hacer con ello.

Solo dibuja. Qué está mal lo dice `common/revision.py` y qué se puede hacer con
ello lo decide `ui/repair.py`; aquí se pinta una fila por avería con su botón al
lado, y se pide confirmación con `tk_pairs.confirmar_plan()`, que es la misma
ventana que gobierna todos los borrados de la aplicación.

Esta pantalla sustituye a tres recuadros ámbar de la ventana principal —los
fallos, los conflictos y el aviso de resync—, que apilados dejaban de ser
jerarquía para ser ruido. Allí queda una línea que dice cuántas cosas hay y trae
aquí.

Dos cosas que no puede hacer y son a propósito:

  * **No repara sola.** Ni al abrirse ni al pulsar: todo plan enseña sus
    consecuencias y espera un sí. Apartar un baseline es la operación que puede
    acabar en un borrado masivo, y por eso se quitó el renombrado automático de
    listados.
  * **No repara mientras se sincroniza.** Mover ficheros o apartar un baseline
    bajo los pies de rclone es exactamente lo que no puede pasar, así que la
    ventana principal no deja abrir esto durante una pasada y `repair` vuelve a
    mirarlo antes de borrar un bloqueo.

`lanzar` llega de la ventana principal, como en «Ajustes»: la salida de una
pasada se enseña en la ventana de salida, que es hija de la principal y se apaga
sola mientras hay otra en curso. Esta pantalla se cierra antes de ceder el paso,
porque dos modales no pueden tener la captura a la vez.
"""

from __future__ import annotations

from common import revision
from common.model import Config

from . import abrir, icons, repair, theme
from .tk import TITLE, cabecera, cuerpo_visible, modal, mostrar, separador_fila

# gravedad -> (icono, estilo del chip, rótulo del chip)
SEMAFORO = {
    revision.GRAVE: ("warn", "Peligro.", "grave"),
    revision.AVISO: ("warn", "Aviso.", "hay que hacer algo"),
    revision.NOTA: ("clock", "Apagado.", "se arregla sola"),
}

TODO_BIEN = ("No hay nada que revisar: las parejas tienen su baseline, no hay "
             "conflictos y la última pasada de cada una fue bien.")

# Qué botón lleva cada avería. Lo que no está aquí no tiene botón, y eso también
# es una respuesta: la carpeta local que falta no se arregla creándola.
BOTONES = {
    "prefijo": "Apartar el baseline…",
    "lock": "Borrar los bloqueos…",
    "resync": "Resincronizar…",
    "fallo": "Ver el log",
}


def open_dialog(parent, config: Config, lanzar, marcadas=None) -> bool:
    """Abre «Reparación». Devuelve True si se ha cambiado algo del dispositivo,
    para que quien llama vuelva a leer `state/` y repinte.

    `marcadas` son las parejas elegidas en la ventana principal: es lo que se
    simula si se pide una pasada de prueba. Sin ellas, todas."""
    from tkinter import messagebox, ttk

    from . import tk_conflicts, tk_pairs

    dlg = modal(parent, "Reparación")
    estado: dict = {"cambiado": False, "hallazgos": []}

    marco = cuerpo_visible(dlg, padding=(22, 20, 22, 18))
    marco.columnconfigure(0, weight=1)

    cabecera(marco, "Reparación",
             "Lo que está mal en este dispositivo, y lo que se puede hacer con "
             "ello. Nada se toca sin que lo confirmes antes.",
             ancho=600, estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")

    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(14, 10, 14, 12))
    tarjeta.grid(row=1, column=0, sticky="ew", pady=(16, 0))
    tarjeta.columnconfigure(0, weight=1)

    # --- las acciones ------------------------------------------------------------

    def aplicar(hallazgo) -> None:
        """Un plan de disco: se piensa, se enseña y solo entonces se ejecuta."""
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
        estado["cambiado"] = True
        repintar()
        messagebox.showinfo(TITLE, "\n".join(hechos) or "Hecho.", parent=dlg)

    def resincronizar(hallazgo) -> None:
        """Esto no es un plan de disco: es una pasada de rclone, con su log y su
        registro, así que se lanza en la ventana de salida como cualquier otra.
        La confirmación se hace igual, que un resync compara los dos lados
        enteros."""
        if not tk_pairs.confirmar_plan(dlg, repair.aviso_resync(hallazgo),
                                       f"Resincronizar «{hallazgo.pareja}»", ""):
            return
        estado["cambiado"] = True
        dlg.destroy()
        lanzar(f"Resincronizar «{hallazgo.pareja}»", repair.args_resync(hallazgo))

    def ver_log(hallazgo) -> None:
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

    # --- la lista de averías ------------------------------------------------------

    def fila(padre, hallazgo, linea: int) -> int:
        icono, chip, rotulo = SEMAFORO.get(hallazgo.gravedad, SEMAFORO[revision.AVISO])
        cabeza = ttk.Frame(padre, style="Plano.Card.TFrame")
        cabeza.grid(row=linea, column=0, sticky="ew", pady=(8, 0))
        cabeza.columnconfigure(1, weight=1)
        linea += 1

        img = icons.get(cabeza, icono, 14, theme.AVISO if hallazgo.gravedad
                        != revision.NOTA else theme.TINTA3, theme.SUPERFICIE)
        marca = ttk.Label(cabeza, style="Card.TLabel")
        if img is not None:
            marca.configure(image=img)
            marca.image = img
        marca.grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(cabeza, text=hallazgo.titulo, style="Card.Fuerte.TLabel",
                  wraplength=theme.medida(420), justify="left").grid(
            row=0, column=1, sticky="w")
        theme.chip(cabeza, rotulo, chip).grid(row=0, column=2, sticky="e", padx=(10, 0))

        texto = BOTONES.get(hallazgo.clave)
        if texto is not None:
            boton = ttk.Button(cabeza, text=texto, style="CardQuiet.TButton",
                               command=lambda h=hallazgo: ACCIONES[h.clave](h))
            boton.grid(row=0, column=3, sticky="e", padx=(10, 0))

        ttk.Label(padre, text=hallazgo.detalle, style="Card.Pista.TLabel",
                  justify="left", wraplength=theme.medida(560)).grid(
            row=linea, column=0, sticky="w", pady=(3, 8))
        return linea + 1

    def repintar() -> None:
        """Vuelve a mirar el dispositivo y redibuja la lista.

        Se relee entero en vez de tachar la fila que se acaba de arreglar: una
        reparación cambia el estado, y lo que había antes en la pantalla es de
        antes. Que la lista encoja es la señal de que ha funcionado."""
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
                row=0, column=0, sticky="w", pady=(4, 4))
        linea = 0
        for i, hallazgo in enumerate(lista):
            if i:
                separador_fila(tarjeta, linea, 1)
                linea += 1
            linea = fila(tarjeta, hallazgo, linea)

        conflictos.grid_remove()
        if any(h.clave == "conflicto" for h in estado["hallazgos"]):
            conflictos.grid()
        visor = getattr(dlg, "visor", None)
        if visor is not None:
            visor.encajar(dlg)

    def al_resolver() -> None:
        estado["cambiado"] = True
        repintar()

    conflictos = tk_conflicts.seccion(marco, dlg, config, al_resolver)
    conflictos.grid(row=2, column=0, sticky="ew", pady=(18, 0))

    # --- el pie ------------------------------------------------------------------

    def simular() -> None:
        nombres = list(marcadas or [p.name for p in config.pairs])
        if not nombres:
            return
        dlg.destroy()
        lanzar("Simulación", repair.args_simular(nombres))

    def informe() -> None:
        dlg.destroy()
        lanzar("Informe del estado", ["--doctor"])

    ttk.Separator(marco, orient="horizontal").grid(row=3, column=0, sticky="ew",
                                                   pady=(18, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=4, column=0, sticky="ew", pady=(14, 0))
    pie.columnconfigure(2, weight=1)
    # «Simular» vive aquí y no en la ventana principal: es lo que se hace ANTES
    # de sincronizar cuando algo no cuadra, y esta es la pantalla de «a ver qué
    # hay». No escribe nada, así que no necesita ceremonia.
    simula = ttk.Button(pie, text="Simular una pasada…", style="Quiet.TButton",
                        command=simular)
    theme.boton_icono(simula, "eye", theme.ACENTO, theme.PAPEL)
    simula.grid(row=0, column=0, sticky="w")
    ver = ttk.Button(pie, text="Ver el informe completo", style="Quiet.TButton",
                     command=informe)
    theme.boton_icono(ver, "doctor", theme.ACENTO, theme.PAPEL)
    ver.grid(row=0, column=1, sticky="w", padx=(6, 0))
    ttk.Button(pie, text="Cerrar", command=dlg.destroy).grid(row=0, column=3, sticky="e")

    repintar()
    mostrar(dlg, parent)
    return estado["cambiado"]
