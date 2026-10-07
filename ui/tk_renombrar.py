#!/usr/bin/env python3
"""«Ajustes → Catálogo del remoto»: pasar `pairs.toml` a `remote.toml`.

Solo dibuja. Qué hay en la carpeta del catálogo, quién de la flota impide
renombrarla y qué hace el botón lo decide `catalog_editor.renombrado()`; lo
que se hace en el remoto, `catalog.renombrar()` y `catalog.apartar_sobrante()`.

La ventana se abre en el acto y lee el remoto en segundo plano
(`ui.segundo_plano`): la carpeta del catálogo y, si hace falta para decidir,
las notas de la flota. El botón está apagado hasta que llega la respuesta, y
sigue apagado si algún dispositivo no consta que sepa leer el nombre nuevo:
la lista dice cuáles, con su versión y cuándo se vio. Lo que se hace pasa por
`confirmar_plan()` y por `working()`, como cualquier escritura en el remoto.
"""

from __future__ import annotations

from functools import partial

from common import catalog, fleet
from common.model import ConfigError

from . import catalog_editor, segundo_plano, theme
from .tk import (TITLE, Indicador, Panel, Sondeo, cabecera, dialogo, mostrar, pie,
                 separador_fila, working)
from .tk_fleet import fecha

TITULO = "Renombrar el catálogo"
"""El título de la ventana y de su confirmación."""
BOTON = {catalog_editor.RENOMBRAR: f"Renombrar a {catalog.FICHERO}…",
         catalog_editor.APARTAR: f"Apartar {catalog.FICHERO_ANTERIOR}…"}
"""El rótulo del botón según lo que haga."""
NOTA = "Se hace en el remoto, para todos los dispositivos"
"""La nota de la confirmación."""


def open_dialog(parent, raw: dict | None = None) -> None:
    """Abre la ventana; no devuelve nada.

    Lo que cambia es el remoto, y nada local que la ventana de quien llama
    tenga que repintar: la copia del catálogo apunta sola de qué fichero sale.

    Args:
        parent: La ventana de la que cuelga («Ajustes»).
        raw: El `sync_config.toml` en crudo, para saber dónde está el catálogo;
            sin él se lee del disco.
    """
    dialogo(parent, TITULO, lambda p: construir(p, raw), ensenar=mostrar)


def construir(panel: Panel, raw: dict | None = None) -> None:
    """Dibuja «Renombrar el catálogo» en `panel` (su diálogo o «Ajustes»).

    La espera de la red cuelga del marco y no de la ventana: dentro de
    «Ajustes», pasar a otro apartado destruye el marco y con él la espera.
    """
    from tkinter import messagebox, ttk

    raw = catalog_editor.raw_del_dispositivo(raw)
    dlg, marco = panel.ventana, panel.marco
    sondeo = Sondeo(marco)
    yo = fleet.device_id()
    sitio = catalog.sin_renombrar(raw)
    estado: dict = {"renombrado": None}

    cabecera(marco, TITULO, catalog_editor.EXPLICACION, ancho=600,
             estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")
    if sitio is not None:
        ttk.Label(marco, text=sitio.carpeta, style="MonoPista.TLabel").grid(
            row=1, column=0, sticky="w", pady=(8, 0))
    indicador = Indicador(marco, ancho=560)
    indicador.marco.grid(row=2, column=0, sticky="ew", pady=(12, 0))
    dlg.indicador, dlg.sondeo = indicador, sondeo   # como `visor`: los tests los miran

    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(14, 10, 14, 12))
    tarjeta.grid(row=3, column=0, sticky="ew", pady=(14, 0))
    tarjeta.columnconfigure(0, weight=1)
    tarjeta.columnconfigure(1, weight=1)

    ttk.Label(marco, text=catalog_editor.SIN_NOTA, style="Pista.TLabel",
              wraplength=theme.medida(600), justify="left").grid(
        row=4, column=0, sticky="w", pady=(10, 0))
    pie_nota = ttk.Label(marco, text="", style="MonoPista.TLabel",
                         wraplength=theme.medida(600), justify="left")
    pie_nota.grid(row=5, column=0, sticky="w", pady=(8, 0))

    def pintar_tarjeta(ren: catalog_editor.Renombrado | None) -> None:
        """Pinta lo que hay: la frase y, si los hay, quién impide renombrar."""
        for widget in tarjeta.winfo_children():
            widget.destroy()
        if ren is None:
            ttk.Label(tarjeta, text="—", style="Card.Pista.TLabel").grid(
                row=0, column=0, sticky="w")
            return
        estilo = "Card.TLabel" if ren.tono == "Pista." else f"Card.{ren.tono}TLabel"
        ttk.Label(tarjeta, text=ren.linea, style=estilo, wraplength=theme.medida(560),
                  justify="left").grid(row=0, column=0, columnspan=3, sticky="w")
        fila = 1
        for bloqueo in ren.bloquean:
            separador_fila(tarjeta, fila, 3)
            ttk.Label(tarjeta, text=bloqueo.nombre, style="Card.Fuerte.TLabel",
                      wraplength=theme.medida(220), justify="left").grid(
                row=fila + 1, column=0, sticky="w", pady=6)
            ttk.Label(tarjeta, text=bloqueo.motivo, style="Card.Pista.TLabel",
                      wraplength=theme.medida(260), justify="left").grid(
                row=fila + 1, column=1, sticky="w", padx=(12, 0), pady=6)
            ttk.Label(tarjeta, text=fecha(bloqueo.visto), style="Card.MonoPista.TLabel").grid(
                row=fila + 1, column=2, sticky="e", padx=(12, 0), pady=6)
            fila += 2

    def refrescar(nota: str = "") -> None:
        """Relee el remoto en segundo plano y repinta al llegar.

        Mientras tanto el botón está apagado: lo que deja hacer depende de lo
        que llegue.
        """
        accion.configure(state="disabled", text=BOTON[catalog_editor.RENOMBRAR])
        releer.configure(state="disabled")
        indicador.poner(catalog_editor.LEYENDO_NOMBRE, True)

        def llegada(encargo) -> None:
            """Pinta lo que ha llegado; si el hilo falló, lo dice."""
            if encargo.error is not None:
                pintar(catalog_editor.Renombrado(
                    f"No se ha podido mirar el remoto: {encargo.error}", "Aviso."), nota)
                return
            nombres, flota, aviso = encargo.resultado
            pintar(catalog_editor.renombrado(sitio, nombres, flota, aviso, yo), nota)

        sondeo.esperar(segundo_plano.lanzar_sin_repetir(
            "renombrado", raw, partial(catalog_editor.leer_renombrado, raw)), llegada)

    def pintar(ren: catalog_editor.Renombrado, nota: str = "") -> None:
        """Repinta la tarjeta y el botón con lo que se ha leído."""
        estado["renombrado"] = ren
        indicador.poner("", False)
        releer.configure(state="normal")
        pintar_tarjeta(ren)
        if ren.accion:
            accion.configure(state="normal", text=BOTON[ren.accion])
        pie_nota.configure(text=nota)
        if nota:
            pie_nota.grid()
        else:
            pie_nota.grid_remove()
        panel.ajustar()

    def hacer() -> None:
        """Confirma el plan del botón y lo hace en el remoto."""
        from .tk_pairs import confirmar_plan
        ren = estado["renombrado"]
        if ren is None:
            return
        try:
            plan = catalog_editor.plan_renombrar(ren, raw)
        except ConfigError as e:
            messagebox.showerror(TITLE, str(e), parent=dlg)
            return
        if not confirmar_plan(dlg, plan, TITULO, NOTA):
            return
        ok, resultado = working(dlg, TITULO, plan.execute,
                                "Cambiando el nombre en la carpeta del catálogo…")
        if not ok:
            refrescar(str(resultado))
            return
        refrescar("\n".join(resultado))

    botones = pie(marco, 6)
    botones.columnconfigure(1, weight=1)
    releer = ttk.Button(botones, text="Releer", style="Quiet.TButton",
                        command=lambda: refrescar())
    theme.boton_icono(releer, "reload", theme.ACENTO, theme.PAPEL)
    releer.grid(row=0, column=0, sticky="w")
    accion = ttk.Button(botones, text=BOTON[catalog_editor.RENOMBRAR],
                        style="Primary.TButton", command=hacer, state="disabled")
    accion.grid(row=0, column=2, sticky="e")
    if not panel.incrustado:
        ttk.Button(botones, text="Cerrar", command=panel.cerrar).grid(
            row=0, column=3, sticky="e", padx=(8, 0))

    if sitio is None:
        indicador.poner("", False)
        pintar(catalog_editor.renombrado(None, None, [], None, yo))
    else:
        pintar_tarjeta(None)
        refrescar()
