#!/usr/bin/env python3
"""«Atajos de teclado»: la ventana del agente que graba las combinaciones.

Solo dibuja. Qué dice cada fila, qué vale y qué se pide al guardar lo decide
`ui/atajos.py` (`Edicion`, `Teclas`); quién los pone es el agente. La lanza el
agente como proceso hijo (`pregunta.py --atajos`), desde «Atajos de teclado…»
de la bandeja o con `agente.py atajos`, para no cargar Tk en su proceso; y
mientras está abierta suelta los atajos (salvo con el portal), así que la
combinación que se pulsa llega aquí y no dispara su acción.

- Empieza con lo que cuenta el agente en `estado.json` (`resumen()["atajos"]`):
  los atajos guardados y, de cada uno que el sistema no dejó poner, por qué.
- «Grabar» en una fila y pulsar la combinación; Esc deja de grabar. Lo que no
  vale se dice en la fila; una combinación que ya tenía otra acción pasa a esta.
  «Quitar» la deja sin atajo.
- «Guardar» deja la petición en el buzón del agente (`PIDE_ATAJOS`, con una
  `vez` propia) y espera su respuesta en `estado.json`: el agente los pone de
  verdad y guarda solo los que el sistema deja. Si alguno no, su fila dice por
  qué y la ventana sigue abierta para elegir otra; si todos, se cierra.
- Con `motivo` (en este equipo no se pueden poner) solo dice por qué.

Sale con 0, o con `SIN_VENTANA` (2) si no se ha podido abrir.
"""

from __future__ import annotations

import os
import time
import uuid

from common import equipo

from . import atajos, icons, theme

SIN_VENTANA = 2
"""El código de salida cuando no se ha podido abrir la ventana."""
IS_WIN = os.name == "nt"
CADA_MS = 200
"""Cada cuánto se mira, tras «Guardar», si el agente ha contestado."""
ESPERA = 15.0
"""Segundos que se espera la respuesta del agente a un «Guardar»."""
ESPERA_PORTAL = 200.0
"""Lo mismo con el portal: contesta cuando se confirma en la ventana del escritorio."""
ANCHO = 460
"""El ancho del texto, en medidas del diseño."""
PISTA = ("Funcionan con cualquier programa delante y actúan sobre la última unidad que "
         "has usado: la última cuya ventana abriste o que elegiste en la bandeja; si no, "
         "la última que conectaste.")
PISTA_PORTAL = ("Al guardar, el escritorio te pedirá confirmarlos en su propia ventana, "
                "y puede dejarte elegir otra combinación.")


def leer_estado() -> dict:
    """Devuelve lo que cuenta el agente de los atajos (`estado.json`).

    Punto de indirección: los tests lo sustituyen.
    """
    datos = equipo.leer_estado().get("atajos")
    return datos if isinstance(datos, dict) else {}


def pedir(peticion: dict) -> bool:
    """Deja una petición en el buzón del agente.

    Punto de indirección: los tests lo sustituyen.
    """
    return equipo.pedir(peticion)


def construir(root, edicion: atajos.Edicion, motivo: str, portal: bool,
              acciones: dict) -> dict:
    """Pinta la ventana dentro de `root` y devuelve sus piezas vivas.

    Args:
        root: Donde se pinta.
        edicion: Los atajos con que empieza.
        motivo: Por qué no se pueden poner en este equipo; vacío si se puede.
        portal: Si se ponen con el portal (Wayland), que pide confirmarlos.
        acciones: `grabar(accion)`, `quitar(accion)`, `guardar()` y `cerrar()`.

    Returns:
        Las piezas: `marco`, `filas` (por acción: `combo`, `grabar`, `quitar`,
        `nota`), `resultado`, `guardar` y `cerrar`.
    """
    from tkinter import ttk

    from . import tk as tkui

    marco = tkui.cuerpo_visible(root, directo=True,
                                padding=(theme.E5, theme.E5, theme.E5, theme.E4))
    marco.columnconfigure(0, weight=1)
    tkui.cabecera(marco, "Atajos de teclado", PISTA, ancho=ANCHO,
                  estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")
    piezas: dict = {"marco": marco, "filas": {}, "guardar": None, "resultado": None}
    if motivo:
        tkui.bloque_aviso(marco, f"No se pueden usar en este equipo\n{motivo[:1].upper()}"
                                 f"{motivo[1:]}.", ancho=ANCHO).grid(
            row=1, column=0, sticky="ew", pady=(theme.E4, 0))
        botones = tkui.pie(marco, 2)
        botones.columnconfigure(0, weight=1)
        piezas["cerrar"] = ttk.Button(botones, text="Cerrar", style="Primary.TButton",
                                      command=acciones["cerrar"])
        piezas["cerrar"].grid(row=0, column=1)
        return piezas

    tarjeta = ttk.Frame(marco, style="Card.TFrame",
                        padding=(theme.E4, theme.E3, theme.E4, theme.E3))
    tarjeta.grid(row=1, column=0, sticky="ew", pady=(theme.E4, 0))
    # La columna de la combinación guarda sitio para lo más largo que puede decir:
    # si creciera al grabar, la ventana (que no cambia de tamaño) se cortaría.
    try:
        minimo = max(theme.fuente_tk(tarjeta, "texto").measure(atajos.GRABANDO),
                     theme.fuente_tk(tarjeta, "mono").measure(atajos.MAS_LARGA))
    except Exception:                                   # noqa: BLE001
        minimo = 0
    tarjeta.columnconfigure(1, weight=1, minsize=minimo)
    for n, fila in enumerate(edicion.filas()):
        r = 2 * n
        arriba = theme.E2 if n else 0
        ttk.Label(tarjeta, text=fila.nombre, style="Card.Campo.TLabel").grid(
            row=r, column=0, sticky="w", padx=(0, theme.E4), pady=(arriba, 0))
        combo = ttk.Label(tarjeta, text=fila.combinacion, style="Card.Mono.TLabel")
        combo.grid(row=r, column=1, sticky="w", pady=(arriba, 0))
        grabar = ttk.Button(tarjeta, text="Grabar", style="Pequeno.TButton",
                            command=lambda a=fila.accion: acciones["grabar"](a))
        grabar.grid(row=r, column=2, padx=(theme.E3, theme.E2), pady=(arriba, 0))
        quitar = ttk.Button(tarjeta, text="Quitar", style="CardQuiet.TButton",
                            command=lambda a=fila.accion: acciones["quitar"](a))
        quitar.grid(row=r, column=3, pady=(arriba, 0))
        nota = ttk.Label(tarjeta, text="", style="Card.Pista.TLabel", justify="left",
                         wraplength=theme.medida(ANCHO - 120))
        nota.grid(row=r + 1, column=1, columnspan=3, sticky="w", pady=(theme.E1, 0))
        piezas["filas"][fila.accion] = {"combo": combo, "grabar": grabar, "quitar": quitar,
                                        "nota": nota}
    fila_pista = 2
    if portal:
        ttk.Label(marco, text=PISTA_PORTAL, style="Pista.TLabel", justify="left",
                  wraplength=theme.medida(ANCHO)).grid(row=2, column=0, sticky="w",
                                                      pady=(theme.E3, 0))
        fila_pista = 3
    piezas["resultado"] = tkui.Resultado(marco, ancho=ANCHO).grid(
        row=fila_pista, column=0, sticky="ew", pady=(theme.E3, 0))
    botones = tkui.pie(marco, fila_pista + 1)
    botones.columnconfigure(0, weight=1)
    piezas["cerrar"] = ttk.Button(botones, text="Cancelar", command=acciones["cerrar"])
    piezas["cerrar"].grid(row=0, column=1, padx=(0, theme.E2))
    piezas["guardar"] = ttk.Button(botones, text="Guardar", style="Primary.TButton",
                                   command=acciones["guardar"])
    piezas["guardar"].grid(row=0, column=2)
    return piezas


def pintar(piezas: dict, edicion: atajos.Edicion, ocupada: bool = False) -> None:
    """Pone en las piezas lo que dice `edicion`, sin crear ninguna.

    Args:
        piezas: Las de `construir()`.
        edicion: Los atajos de ahora.
        ocupada: Si se está esperando la respuesta del agente: nada se puede
            tocar.
    """
    for fila in edicion.filas():
        p = piezas["filas"][fila.accion]
        p["combo"].configure(text=fila.combinacion,
                             style="Card.Acento.TLabel" if fila.grabando
                             else "Card.Mono.TLabel")
        p["grabar"].configure(text="Cambiar" if fila.borrable else "Grabar")
        p["grabar"].state(["disabled"] if ocupada or edicion.grabando else ["!disabled"])
        p["quitar"].state(["disabled"] if ocupada or not fila.borrable else ["!disabled"])
        p["nota"].configure(text=fila.nota)
        if fila.nota:
            p["nota"].grid()
        else:
            p["nota"].grid_remove()
    if piezas["guardar"] is not None:
        piezas["guardar"].state(["!disabled"] if edicion.cambiada and not ocupada
                                and not edicion.grabando else ["disabled"])


def abrir(motivo: str = "") -> int:
    """Abre la ventana, la atiende hasta que se cierra y devuelve el código de salida.

    Raises:
        Exception: Si no hay Tk o pantalla.
    """
    import gc
    import tkinter as tk

    from . import tk as tkui

    estado = leer_estado()
    portal = estado.get("mecanismo") == atajos.PORTAL
    teclas = atajos.Teclas(windows=IS_WIN)
    actual = [atajos.Edicion.desde(estado, windows=IS_WIN)]
    espera: dict = {"vez": "", "hasta": 0.0}

    theme.nitidez()
    root = tk.Tk()
    try:
        theme.apply(root)
        icons.poner_icono(root)
        root.title(f"{tkui.TITLE} — atajos de teclado")
        root.configure(background=theme.PAPEL)
        root.resizable(False, False)
        root.withdraw()

        def ajustar() -> None:
            """Agranda la ventana si lo que dice ahora no cabe (nunca la encoge)."""
            root.visor.crecer(root)

        def poner(edicion: atajos.Edicion, ocupada: bool = False) -> None:
            """Cambia los atajos de la ventana y lo pinta."""
            actual[0] = edicion
            if piezas["filas"]:
                pintar(piezas, edicion, ocupada)
                ajustar()

        def decir(texto: str, tono: str = "") -> None:
            """Pone el resultado bajo los atajos."""
            piezas["resultado"].poner(texto, tono)
            ajustar()

        def grabar(accion: str) -> None:
            """Empieza a grabar la combinación de esa acción."""
            teclas.soltar_todo()
            poner(actual[0].grabar(accion))
            root.focus_force()

        def quitar(accion: str) -> None:
            """Quita el atajo de esa acción."""
            poner(actual[0].borrar(accion))

        def tecla(evento) -> str | None:
            """Una tecla pulsada: si se está grabando, es para la combinación."""
            if not actual[0].grabando:
                return None
            if evento.keysym == "Escape" and not teclas.pulsados:
                poner(actual[0].grabar(""))
                return "break"
            c = teclas.pulsa(evento.keysym, evento.keycode, evento.state)
            if c is not None:
                poner(actual[0].pulsada(c))
            return "break"

        def suelta(evento) -> str | None:
            """Una tecla soltada: para saber qué modificadores siguen abajo."""
            teclas.suelta(evento.keysym)
            return "break" if actual[0].grabando else None

        def mirar() -> None:
            """Mira si el agente ha contestado al «Guardar», hasta el plazo."""
            respuesta = leer_estado().get("respuesta")
            if isinstance(respuesta, dict) and respuesta.get("vez") == espera["vez"]:
                rechazados = respuesta.get("rechazados")
                rechazados = rechazados if isinstance(rechazados, dict) else {}
                poner(actual[0].veredicto(rechazados))
                if not rechazados:
                    root.destroy()
                    return
                decir("No se han podido poner todos\nLos que el sistema no deja se quedan "
                      "sin atajo: elige otra combinación y vuelve a guardar.", "aviso")
                return
            if time.monotonic() >= espera["hasta"]:
                poner(actual[0])
                decir("El agente no ha contestado\nPuede que no esté en marcha. No se ha "
                      "cambiado nada que se sepa: vuelve a intentarlo.", "aviso")
                return
            root.after(CADA_MS, mirar)

        def guardar() -> None:
            """Le pide al agente los atajos de la ventana y espera su respuesta."""
            if not actual[0].cambiada:
                root.destroy()
                return
            espera["vez"] = uuid.uuid4().hex
            if not pedir({"pide": equipo.PIDE_ATAJOS, "vez": espera["vez"],
                          "atajos": actual[0].pedido()}):
                decir("No he podido dejarle el encargo al agente\nVuelve a intentarlo.",
                      "peligro")
                return
            espera["hasta"] = time.monotonic() + (ESPERA_PORTAL if portal else ESPERA)
            poner(actual[0], ocupada=True)
            decir("Confirma los atajos en la ventana del escritorio…" if portal
                  else "Comprobando con el sistema…")
            root.after(CADA_MS, mirar)

        piezas = construir(root, actual[0], motivo, portal,
                           {"grabar": grabar, "quitar": quitar, "guardar": guardar,
                            "cerrar": root.destroy})
        if piezas["filas"]:
            pintar(piezas, actual[0])
            root.bind("<KeyPress>", tecla)
            root.bind("<KeyRelease>", suelta)
            root.bind("<FocusOut>", lambda _e: teclas.soltar_todo())
        root.protocol("WM_DELETE_WINDOW", root.destroy)
        root.visor.encajar(root)
        tkui.centrar(root)
        tkui.ensenar(root)
        # Lanzada por un proceso sin ventana, Windows la dejaría debajo de todo.
        try:
            root.attributes("-topmost", True)
            root.after(1500, lambda: root.attributes("-topmost", False))
        except tk.TclError:
            pass
        root.mainloop()
    finally:
        interp = root.tk
        # Lo que quedara por correr (el «encima de todo», la espera del agente)
        # es de esta ventana, que ya no está.
        try:
            for ident in interp.splitlist(interp.call("after", "info")):
                interp.call("after", "cancel", ident)
        except tk.TclError:
            pass
        theme.olvidar(interp)
        icons.olvidar(interp)
        gc.collect()
    return 0


def main(motivo: str = "") -> int:
    """Abre la ventana y devuelve el código de salida; sin ventana, `SIN_VENTANA`."""
    try:
        return abrir(motivo)
    except Exception:                                   # noqa: BLE001
        return SIN_VENTANA
