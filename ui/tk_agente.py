#!/usr/bin/env python3
"""
tk_agente.py — «Se ha conectado PRDRIVE-2. ¿Atenderla en este equipo?»

La ventanita con la que el agente pregunta por una unidad que no conoce. Solo
dibuja: el agente la lanza como proceso hijo (`agente.py pregunta`) para no
cargar Tk nunca en su propio proceso, y lee la respuesta en el código de salida:

    0  «Atender»
    1  «Ahora no», o cerrada sin contestar, o la cuenta atrás llegó a cero
    2  no se ha podido abrir (sin Tk o sin pantalla)

Quién lleva el reloj es el agente (`planificador.Pregunta`), no esta ventana: la
cuenta atrás es para que se vea, y al llegar a cero se cierra sola. Si alguien
contesta tarde, el agente no le hace caso; para eso está la entrada de la
bandeja.

Antes del sí no se ejecuta nada de la unidad, y esta ventana tampoco: el nombre
le llega por argumento, leído por el agente de `state/fleet.json`.
"""

from __future__ import annotations

from . import icons, theme

ATENDER, AHORA_NO, SIN_VENTANA = 0, 1, 2


def cuenta(segundos: int) -> str:
    """El texto de la cuenta atrás: «Se cierra sola en 1:45 …»."""
    segundos = max(0, int(segundos))
    return (f"Si no contestas, en {segundos // 60}:{segundos % 60:02d} se cierra "
            "sola y cuenta como «Ahora no».")


def construir(root, nombre: str, segundos: int, responder) -> dict:
    """Pinta la pregunta dentro de `root` y devuelve sus piezas vivas (para la
    cuenta atrás y para los tests). `responder(código)` cierra con esa
    respuesta."""
    from tkinter import ttk

    from . import tk as tkui

    marco = tkui.cuerpo_visible(root, padding=(22, 20, 22, 18))
    marco.columnconfigure(0, weight=1)
    tkui.cabecera(marco, f"Se ha conectado {nombre}",
                  "¿Atender esta unidad en este equipo? Si dices que sí, el agente "
                  "la sincroniza en segundo plano cada vez que la enchufes; el modo "
                  "se cambia después en sus ajustes.",
                  ancho=420, estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")

    nota = ttk.Label(marco, text=cuenta(segundos), style="Pista.TLabel",
                     wraplength=theme.medida(420), justify="left")
    nota.grid(row=1, column=0, sticky="w", pady=(12, 0))
    ttk.Label(marco, text="«Ahora no» vale para esta conexión: la próxima vez que la "
                          "enchufes se volverá a preguntar.",
              style="Pista.TLabel", wraplength=theme.medida(420),
              justify="left").grid(row=2, column=0, sticky="w", pady=(6, 0))

    pie = ttk.Frame(marco)
    pie.grid(row=3, column=0, sticky="ew", pady=(16, 0))
    pie.columnconfigure(0, weight=1)
    ahora_no = ttk.Button(pie, text="Ahora no", style="Quiet.TButton",
                          command=lambda: responder(AHORA_NO))
    ahora_no.grid(row=0, column=1, padx=(0, 8))
    atender = ttk.Button(pie, text="Atender", style="Primary.TButton",
                         command=lambda: responder(ATENDER))
    atender.grid(row=0, column=2)
    return {"marco": marco, "nota": nota, "atender": atender, "ahora_no": ahora_no}


def preguntar(nombre: str, segundos: int) -> int:
    """Abre la ventana y espera la respuesta. Lanza si no hay Tk o pantalla."""
    import gc
    import tkinter as tk

    from . import tk as tkui

    theme.nitidez()
    root = tk.Tk()
    respuesta = [AHORA_NO]
    try:
        theme.apply(root)
        icons.poner_icono(root)
        root.title(f"{tkui.TITLE} — unidad nueva")
        root.configure(background=theme.PAPEL)
        root.resizable(False, False)
        root.withdraw()

        def responder(codigo: int) -> None:
            respuesta[0] = codigo
            root.destroy()

        piezas = construir(root, nombre, segundos, responder)
        root.protocol("WM_DELETE_WINDOW", lambda: responder(AHORA_NO))
        quedan = [max(0, int(segundos))]

        def tic() -> None:
            quedan[0] -= 1
            if quedan[0] <= 0:
                responder(AHORA_NO)
                return
            piezas["nota"].configure(text=cuenta(quedan[0]))
            root.after(1000, tic)

        root.visor.encajar(root)
        tkui.centrar(root)
        root.deiconify()
        # Lanzada por un proceso sin ventana, Windows la dejaría debajo de todo.
        try:
            root.attributes("-topmost", True)
            root.after(1500, lambda: root.attributes("-topmost", False))
        except tk.TclError:
            pass
        piezas["atender"].focus_set()
        root.after(1000, tic)
        root.mainloop()
    finally:
        interp = root.tk
        theme.olvidar(interp)
        icons.olvidar(interp)
        gc.collect()
    return respuesta[0]


def main(nombre: str, segundos: int) -> int:
    try:
        return preguntar(nombre, segundos)
    except Exception:                                   # noqa: BLE001
        return SIN_VENTANA
