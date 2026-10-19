#!/usr/bin/env python3
"""«Desinstalar prdrive de este equipo»: la ventana del «Desinstalar» de Windows.

Solo dibuja. La abre `agente.py desinstalar`, que es lo que Windows ejecuta
desde «Aplicaciones instaladas»; qué se hará y el hacerlo son
`presencia.plan_desinstalar()` y su `execute()`. Va en tres pasos, colgados de
una raíz oculta (`tk.root_oculto()`):

1. qué va a pasar (lo que se quita, en una tarjeta; lo que se queda, en avisos
   ámbar), con «Desinstalar» y «Cancelar»;
2. `tk.working()` mientras para el agente y lo quita, con lo que espera (la
   pasada en curso) bajo la barra;
3. qué se ha hecho, o por qué no se ha podido, y «Cerrar».

Sin Tk o sin pantalla devuelve `SIN_VENTANA`, y quien la abrió pregunta por la
consola.
"""

from __future__ import annotations

from . import theme

HECHO, NO, SIN_VENTANA = 0, 1, 2
"""Los códigos de salida: desinstalado, cancelado o fallido, y sin ventana."""
TITULO = "Desinstalar"
"""El título de las ventanas, detrás de «prdrive —»."""


def _tarjeta(marco, lineas: list[str], fila: int) -> None:
    """Pone las líneas en una tarjeta, una por renglón, con su punto."""
    from tkinter import ttk

    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(theme.E4, theme.E1))
    tarjeta.grid(row=fila, column=0, sticky="ew", pady=(theme.E4, 0))
    tarjeta.columnconfigure(1, weight=1)
    for i, texto in enumerate(lineas):
        if i:
            ttk.Separator(tarjeta, orient="horizontal", style="Card.TSeparator").grid(
                row=i * 2 - 1, column=0, columnspan=2, sticky="ew")
        ttk.Label(tarjeta, text="•", style="Card.Apagado.TLabel").grid(
            row=i * 2, column=0, sticky="nw", pady=theme.E2)
        ttk.Label(tarjeta, text=texto, style="Card.TLabel", wraplength=theme.medida(470),
                  justify="left").grid(row=i * 2, column=1, sticky="w",
                                       padx=(theme.E2, 0), pady=theme.E2)


def confirmar(raiz, plan) -> bool:
    """Enseña lo que hará desinstalar y espera un sí; todavía no se ha tocado nada.

    Args:
        raiz: La raíz oculta de la que cuelga.
        plan: Lo que se confirma (`consequences`, `warnings`).

    Returns:
        `True` si la persona pulsa «Desinstalar».
    """
    from tkinter import ttk

    from .tk import cuerpo_visible, modal, mostrar

    dlg = modal(raiz, TITULO, suelto=True)
    respuesta = {"sigue": False}
    marco = cuerpo_visible(dlg, padding=(theme.E5, theme.E5, theme.E5, theme.E4))
    marco.columnconfigure(0, weight=1)
    ttk.Label(marco, text="Desinstalar prdrive de este equipo",
              style="Dialogo.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(marco, text="Esto es lo que va a pasar. Todavía no se ha tocado nada.",
              style="Pista.TLabel").grid(row=1, column=0, sticky="w", pady=(theme.E1, 0))
    _tarjeta(marco, plan.consequences, 2)
    fila = 3
    for texto in plan.warnings:
        theme.aviso(marco, "Se queda", texto, ancho=470).grid(
            row=fila, column=0, sticky="ew", pady=(theme.E3, 0))
        fila += 1
    ttk.Separator(marco, orient="horizontal").grid(row=fila, column=0, sticky="ew",
                                                   pady=(theme.E4, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=fila + 1, column=0, sticky="e", pady=(theme.E4, 0))

    def seguir() -> None:
        """Da el sí y cierra."""
        respuesta["sigue"] = True
        dlg.destroy()

    ttk.Button(pie, text="Cancelar", command=dlg.destroy).grid(row=0, column=0,
                                                               padx=(0, theme.E2))
    quitar = ttk.Button(pie, text="Desinstalar", style="Danger.TButton", command=seguir)
    theme.boton_icono(quitar, "trash", theme.PELIGRO, theme.SUPERFICIE)
    quitar.grid(row=0, column=1)
    mostrar(dlg)
    return respuesta["sigue"]


def informe(raiz, ok: bool, lineas: list[str], titulo_fallo: str = "") -> None:
    """Dice qué se ha hecho, o por qué no se ha podido, y espera a que se cierre.

    Args:
        raiz: La raíz oculta de la que cuelga.
        ok: Si se ha desinstalado.
        lineas: Lo hecho, o el motivo.
        titulo_fallo: El título del aviso rojo cuando no se ha podido.
    """
    from tkinter import ttk

    from .tk import cuerpo_visible, modal, mostrar

    dlg = modal(raiz, TITULO, suelto=True)
    marco = cuerpo_visible(dlg, padding=(theme.E5, theme.E5, theme.E5, theme.E4))
    marco.columnconfigure(0, weight=1)
    ttk.Label(marco, style="Dialogo.TLabel",
              text=("prdrive se ha desinstalado de este equipo" if ok
                    else "No se ha podido desinstalar")).grid(row=0, column=0, sticky="w")
    if ok:
        _tarjeta(marco, lineas, 1)
    else:
        theme.aviso(marco, titulo_fallo, " ".join(lineas), tono="Rojo.",
                    ancho=470).grid(row=1, column=0, sticky="ew", pady=(theme.E4, 0))
    ttk.Separator(marco, orient="horizontal").grid(row=2, column=0, sticky="ew",
                                                   pady=(theme.E4, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=3, column=0, sticky="e", pady=(theme.E4, 0))
    ttk.Button(pie, text="Cerrar", style="Primary.TButton",
               command=dlg.destroy).grid(row=0, column=0)
    mostrar(dlg)


def main(plan) -> int:
    """Pregunta, desinstala y dice cómo ha ido.

    Args:
        plan: El de `presencia.plan_desinstalar()`.

    Returns:
        `HECHO`, `NO` (cancelado o fallido) o `SIN_VENTANA` si no se ha podido
        abrir ninguna ventana; entonces no se ha tocado nada.
    """
    try:
        from .tk import root_oculto
        raiz = root_oculto()
    except Exception:                                   # noqa: BLE001 — sin Tk o sin pantalla
        return SIN_VENTANA
    try:
        if not confirmar(raiz, plan):
            return NO
        from common import presencia

        from .tk import working
        medida: dict = {"avance": None}

        def avance(fraccion: float, texto: str) -> None:
            """Apunta lo último que se espera, para la barra."""
            medida["avance"] = (fraccion, texto)

        ok, valor = working(raiz, TITULO, lambda: plan.execute(avance),
                            "Quitando prdrive de este equipo…",
                            lambda: medida["avance"], suelto=True)
        if ok:
            informe(raiz, True, list(valor))
            return HECHO
        if isinstance(valor, presencia.DesinstalacionError):
            informe(raiz, False, [str(valor)], "Algo de prdrive sigue abierto")
        else:
            informe(raiz, False, [f"{type(valor).__name__}: {valor}"],
                    "Se ha parado a medias")
        return NO
    finally:
        try:
            raiz.destroy()
        except Exception:                               # noqa: BLE001
            pass
