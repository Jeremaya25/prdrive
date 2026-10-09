#!/usr/bin/env python3
"""La ventana de las versiones guardadas (`.prversions/`).

Solo dibuja. Qué hay guardado y qué se borraría lo sabe
`ui/versions_editor.py`, y confirmar el borrado es `tk_pairs.confirmar_plan()`,
la misma ventana que gobierna los demás borrados de la aplicación.

Cuelga de «Ajustes» y no de la principal porque mirar el histórico es de las
cosas que se hacen de tarde en tarde. La ventana enseña lo que ocupa cada lado,
deja abrir la carpeta de aquí y purgar lo anterior a una fecha; **restaurar no
está**, a propósito: con la carpeta abierta y el nombre
`nota~20260922-093000.md` delante, devolverle su nombre a una versión es copiar
y renombrar, y hacerlo desde aquí (escribiendo encima del fichero vivo, y
también en el remoto) sería otro mecanismo entero con sus propias formas de
salir mal.

Leer los dos lados (el del remoto es una llamada a rclone y el del dispositivo
recorre `.prversions/`) va en un hilo (`segundo_plano`): la pantalla se pinta
entera con una línea de espera y las cifras en «—», y con el remoto caído tarda
lo que tarden los tiempos de espera de `catalog.NET_FLAGS` sin dejar la ventana
en blanco. **Una lectura trae la pareja con sus dos lados juntos** y «Purgar» usa
ese trío, no la pareja que esté elegida en ese momento. Purgar sí va por
`tk.working()`, detrás de su plan y de su confirmación: borra en el remoto y no
se corta a medias.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import partial

from common import model
from common.model import Config, Pair

from . import abrir, segundo_plano, theme, versions_editor
from .tk import TITLE, Panel, cabecera, dialogo, mostrar, pie, separador_fila, working

ANTIGUEDADES = (
    ("Más de 30 días", 30),
    ("Más de 90 días", 90),
    ("Más de un año", 365),
)
"""Lo que se ofrece purgar: tres antigüedades y no fechas.

Tres botones con su antigüedad se entienden sin pensar; «anterior al
14/07/2026» hay que calcularlo mentalmente.
"""

SIN_VERSIONES = (
    "Ninguna pareja de este dispositivo guarda versiones. Se activa en la "
    "pantalla de parejas, editando una pareja bisync: «Guardar en .prversions/ "
    "lo que se sobrescriba o se borre»."
)
"""Lo que se dice si ninguna pareja guarda versiones."""

LEYENDO = "Mirando lo que hay guardado en los dos lados…"
"""Lo que dice la línea de espera mientras se leen los dos lados."""


def leer_pareja(pair: Pair) -> tuple[Pair, versions_editor.Lado, versions_editor.Lado]:
    """Lee los dos lados de la pareja y los devuelve juntos con ella.

    Corre en un hilo (`segundo_plano`). Devolver la pareja con sus lados es lo
    que deja a quien recoge la lectura saber de cuál es: purgar usa este trío y
    no la pareja que esté elegida cuando llegue.
    """
    local, remoto = versions_editor.lados(pair)
    return pair, local, remoto


def open_dialog(parent, config: Config) -> None:
    """Abre la ventana; no devuelve nada.

    Purgar no cambia nada que la ventana principal enseñe.
    """
    dialogo(parent, "Versiones", lambda p: construir(p, config), ensenar=mostrar)


def construir(panel: Panel, config: Config) -> None:
    """Dibuja «Versiones guardadas» en `panel` (su diálogo o «Ajustes»)."""
    from tkinter import StringVar, messagebox, ttk

    from . import tk_pairs

    parejas = [p for p in config.pairs if p.versions]
    dlg, marco = panel.ventana, panel.marco

    cabecera(marco, "Versiones guardadas",
             "Cada lado guarda en .prversions/, dentro de la propia pareja, lo que "
             "él pierde: lo que se sobrescribe, lo que se borra y el perdedor de un "
             "conflicto. Son dos históricos independientes, no una copia: bisync "
             "excluye esa carpeta, que es la condición para que pueda vivir dentro "
             "de la pareja.",
             ancho=620, estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")

    if not parejas:
        ttk.Label(marco, text=SIN_VERSIONES, style="Pista.TLabel", justify="left",
                  wraplength=theme.medida(560)).grid(row=1, column=0, sticky="w",
                                                     pady=(theme.E4, 0))
        if not panel.incrustado:
            ttk.Button(pie(marco, 2), text="Cerrar", command=panel.cerrar).grid(
                row=0, column=0, sticky="e")
        return

    sondeo = panel.sondeo()
    indicador = panel.indicador(marco, ancho=560)
    dlg.indicador, dlg.sondeo = indicador, sondeo   # como `visor`: los tests los miran
    indicador.marco.grid(row=1, column=0, sticky="w", pady=(theme.E3, 0))
    # `lectura` es el trío `(pareja, lado del dispositivo, lado del remoto)` de la
    # última lectura que ha llegado de la pareja elegida; `None` mientras se lee.
    estado: dict = {"pareja": parejas[0], "lectura": None}

    # Elegir pareja: un botón por pareja, como en el diseño.
    fila = 2
    elegida = StringVar(marco, value=parejas[0].name)
    if len(parejas) > 1:
        ttk.Label(marco, text="Pareja", style="Campo.TLabel").grid(
            row=fila, column=0, sticky="w", pady=(theme.E4, theme.E2))
        fila += 1
        theme.grupo_botones(marco, [(p.name, p.name) for p in parejas], elegida,
                            orden=lambda: refrescar()).grid(row=fila, column=0,
                                                            sticky="w")
        fila += 1

    # Lo que hay en cada lado.
    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(theme.E4, theme.E3))
    tarjeta.grid(row=fila, column=0, sticky="ew", pady=(theme.E4, 0))
    tarjeta.columnconfigure(1, weight=1)
    fila += 1

    lineas: dict[str, tuple] = {}
    for i, clave in enumerate((versions_editor.DISPOSITIVO, versions_editor.REMOTO)):
        if i:
            separador_fila(tarjeta, i * 3 - 1, 2)
        titulo = ttk.Label(tarjeta, text=versions_editor.TITULO_LADO[clave],
                           style="Card.Fuerte.TLabel")
        titulo.grid(row=i * 3, column=0, sticky="w", pady=(theme.E2 if i else 0, 0))
        cifra = ttk.Label(tarjeta, style="Card.TLabel", anchor="e")
        cifra.grid(row=i * 3, column=1, sticky="e", pady=(theme.E2 if i else 0, 0))
        ruta = ttk.Label(tarjeta, style="Card.Pista.TLabel", justify="left",
                         wraplength=theme.medida(520))
        ruta.grid(row=i * 3 + 1, column=0, columnspan=2, sticky="w", pady=(theme.E1, theme.E2))
        lineas[clave] = (cifra, ruta)

    # Purgar: la antigüedad, también en botones, y que se borra en los dos lados.
    ttk.Label(marco, text="Purgar", style="Campo.TLabel").grid(
        row=fila, column=0, sticky="w", pady=(theme.E4, theme.E2))
    fila += 1
    antiguedad = StringVar(marco, value=ANTIGUEDADES[0][0])
    theme.grupo_botones(marco, [(t, t) for t, _ in ANTIGUEDADES], antiguedad).grid(
        row=fila, column=0, sticky="w")
    fila += 1
    ttk.Label(marco, text="Se borran en los dos lados.", style="Pista.TLabel").grid(
        row=fila, column=0, sticky="w", pady=(theme.E2, 0))
    fila += 1

    def corte() -> date:
        """Devuelve el día anterior al cual se purga, según la antigüedad elegida."""
        dias = dict(ANTIGUEDADES)[antiguedad.get()]
        return date.today() - timedelta(days=dias)

    # Releer.

    def pareja_actual():
        """Devuelve la pareja elegida en el desplegable."""
        return next(p for p in parejas if p.name == elegida.get())

    def pintar_lados(local, remoto) -> None:
        """Pone en la tarjeta lo que dice cada lado."""
        for clave, lado in ((versions_editor.DISPOSITIVO, local),
                            (versions_editor.REMOTO, remoto)):
            cifra, ruta = lineas[clave]
            if not lado.disponible:
                cifra.configure(text="—", style="Card.TLabel")
            elif lado.total:
                cifra.configure(text=f"{lado.total} versiones · "
                                     f"{versions_editor.legible(lado.tamano)}",
                                style="Card.Fuerte.TLabel")
            else:
                cifra.configure(text="vacío", style="Card.TLabel")
            ruta.configure(text=lado.detalle or lado.endpoint,
                           style="Card.Aviso.TLabel" if not lado.disponible
                           else "Card.Pista.TLabel")

    def pintar_espera(pair) -> None:
        """Pone las cifras en «—» y, bajo ellas, dónde se va a mirar."""
        for clave, endpoint in ((versions_editor.DISPOSITIVO, pair.versions_path1),
                                (versions_editor.REMOTO, pair.versions_path2)):
            cifra, ruta = lineas[clave]
            cifra.configure(text="—", style="Card.TLabel")
            ruta.configure(text=endpoint, style="Card.Pista.TLabel")

    def llegada(pair, encargo) -> None:
        """Pinta los dos lados de la pareja que se pidió, si sigue siendo la elegida.

        Args:
            pair: La pareja que se pidió al lanzar esta lectura.
            encargo: Su lectura, ya terminada.
        """
        if pair.name != elegida.get():
            return                      # se eligió otra mientras tanto: viene la suya
        indicador.poner("", False)
        if encargo.error is not None:
            motivo = f"no se ha podido leer: {encargo.error}"
            local = versions_editor.Lado(versions_editor.DISPOSITIVO,
                                         pair.versions_path1, False, motivo)
            remoto = versions_editor.Lado(versions_editor.REMOTO,
                                          pair.versions_path2, False, motivo)
        else:
            pair, local, remoto = encargo.resultado
        estado["lectura"] = (pair, local, remoto)
        pintar_lados(local, remoto)
        purgar_btn.configure(
            state="normal" if (local.disponible and local.total)
            or (remoto.disponible and remoto.total) else "disabled")
        abrir_btn.configure(state="normal" if local.total else "disabled")

    def refrescar(*_) -> None:
        """Relee los dos lados de la pareja elegida; la pantalla ya está pintada.

        Mientras llega, las cifras dicen «—» y no se puede purgar ni abrir la
        carpeta: lo que se haría saldría de una lectura de otra pareja o de antes.
        """
        pair = pareja_actual()
        estado["pareja"], estado["lectura"] = pair, None
        pintar_espera(pair)
        purgar_btn.configure(state="disabled")
        abrir_btn.configure(state="disabled")
        indicador.poner(LEYENDO, True)
        sondeo.esperar(segundo_plano.lanzar_sin_repetir(
            ("versiones", pair.name), None, partial(leer_pareja, pair)),
            lambda encargo, p=pair: llegada(p, encargo))

    # Acciones.

    def abrir_carpeta() -> None:
        """Abre la carpeta de versiones de la pareja, en este dispositivo."""
        destino = estado["pareja"].local_abs / model.VERSIONS_DIR
        try:
            abrir(destino)
        except OSError as e:
            messagebox.showerror(TITLE, f"No se ha podido abrir {destino}:\n{e}",
                                 parent=dlg)

    def purgar() -> None:
        """Pide confirmación del plan de purga y lo ejecuta.

        El plan sale de la pareja y los lados de una misma lectura
        (`estado["lectura"]`), nunca de la pareja elegida ahora con lados de
        otra.
        """
        if estado["lectura"] is None:
            return
        pair, local, remoto = estado["lectura"]
        plan = versions_editor.plan_purgar(pair, local, remoto, corte())
        if plan.vacio:
            messagebox.showinfo(TITLE, plan.consequences[0], parent=dlg)
            return
        if not tk_pairs.confirmar_plan(
                dlg, plan, f"Purgar versiones de '{plan.pair_name}'",
                "Se borran en los dos lados"):
            return
        ok, hechos = working(dlg, "Versiones", plan.execute, "Purgando las versiones…")
        if not ok:
            messagebox.showerror(TITLE, str(hechos), parent=dlg)
            return
        refrescar()
        messagebox.showinfo(TITLE, "\n".join(hechos) or "No se ha borrado nada.",
                            parent=dlg)

    botones = pie(marco, fila)
    botones.columnconfigure(0, weight=1)
    abrir_btn = ttk.Button(botones, text="Abrir la carpeta", style="Quiet.TButton",
                           command=abrir_carpeta)
    theme.boton_icono(abrir_btn, "file", theme.ACENTO, theme.PAPEL)
    abrir_btn.grid(row=0, column=0, sticky="w")
    purgar_btn = ttk.Button(botones, text="Purgar…", style="Danger.TButton",
                            command=purgar)
    theme.boton_icono(purgar_btn, "trash", theme.PELIGRO, theme.SUPERFICIE)
    purgar_btn.grid(row=0, column=1, padx=(theme.E3, 0))
    if not panel.incrustado:
        ttk.Button(botones, text="Cerrar", command=panel.cerrar).grid(
            row=0, column=2, padx=(theme.E2, 0))

    refrescar()
