#!/usr/bin/env python3
"""
tk_versions.py — La ventana de las versiones guardadas (`.prversions/`).

Solo dibuja. Qué hay guardado y qué se borraría lo sabe `ui/versions_editor.py`,
y confirmar el borrado es `tk_pairs.confirmar_plan()`, la misma ventana que
gobierna los demás borrados de la aplicación.

Cuelga de Doctor y no de la principal porque mirar el histórico es de las cosas
que se hacen de tarde en tarde. La ventana enseña lo que ocupa cada lado, deja
abrir la carpeta de aquí y purgar lo anterior a una fecha; **restaurar no está**,
a propósito: con la carpeta abierta y el nombre `nota~20260922-093000.md`
delante, devolverle su nombre a una versión es copiar y renombrar, y hacerlo
desde aquí —escribiendo encima del fichero vivo, y también en el remoto— sería
otro mecanismo entero con sus propias formas de salir mal.

Leer el lado remoto es una llamada a rclone, así que va por `tk.working()`: con
el remoto caído tarda lo que tarden los tiempos de espera de `catalog.NET_FLAGS`,
y mientras tanto la ventana no puede quedarse en blanco.
"""

from __future__ import annotations

from datetime import date, timedelta

from common import model
from common.model import Config

from . import abrir, theme, versions_editor
from .tk import TITLE, cabecera, cuerpo_visible, modal, mostrar, separador_fila, working

# Lo que se ofrece purgar. Fechas no: un desplegable con tres antigüedades se
# entiende sin pensar, y «anterior al 14/07/2026» hay que calcularlo mentalmente.
ANTIGUEDADES = (
    ("Más de 30 días", 30),
    ("Más de 90 días", 90),
    ("Más de un año", 365),
)

SIN_VERSIONES = (
    "Ninguna pareja de este dispositivo guarda versiones. Se activa en la "
    "pantalla de parejas, editando una pareja bisync: «Guardar en .prversions/ "
    "lo que se sobrescriba o se borre»."
)


def open_dialog(parent, config: Config) -> None:
    """Abre la ventana. No devuelve nada: purgar no cambia nada que la ventana
    principal enseñe."""
    from tkinter import StringVar, messagebox, ttk

    from . import tk_pairs

    parejas = [p for p in config.pairs if p.versions]

    dlg = modal(parent, "Versiones")
    marco = cuerpo_visible(dlg, padding=(22, 20, 22, 18))
    marco.columnconfigure(0, weight=1)

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
                                                     pady=(16, 0))
        _pie(marco, dlg, fila=2)
        mostrar(dlg, parent)
        return

    estado: dict = {"pareja": parejas[0], "local": None, "remoto": None}

    # --- elegir pareja ----------------------------------------------------------
    fila = 1
    if len(parejas) > 1:
        barra = ttk.Frame(marco)
        barra.grid(row=fila, column=0, sticky="w", pady=(16, 0))
        ttk.Label(barra, text="Pareja", style="Campo.TLabel").grid(row=0, column=0,
                                                                   padx=(0, 10))
        elegida = StringVar(value=parejas[0].name)
        ttk.Combobox(barra, textvariable=elegida, state="readonly", width=24,
                     values=[p.name for p in parejas]).grid(row=0, column=1)
        fila += 1
    else:
        elegida = StringVar(value=parejas[0].name)

    # --- lo que hay en cada lado ------------------------------------------------
    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(14, 12))
    tarjeta.grid(row=fila, column=0, sticky="ew", pady=(14, 0))
    tarjeta.columnconfigure(1, weight=1)
    fila += 1

    lineas: dict[str, tuple] = {}
    for i, clave in enumerate((versions_editor.DISPOSITIVO, versions_editor.REMOTO)):
        if i:
            separador_fila(tarjeta, i * 3 - 1, 2)
        titulo = ttk.Label(tarjeta, text=versions_editor.TITULO_LADO[clave],
                           style="Card.Fuerte.TLabel")
        titulo.grid(row=i * 3, column=0, sticky="w", pady=(8 if i else 0, 0))
        cifra = ttk.Label(tarjeta, style="Card.TLabel", anchor="e")
        cifra.grid(row=i * 3, column=1, sticky="e", pady=(8 if i else 0, 0))
        ruta = ttk.Label(tarjeta, style="Card.Pista.TLabel", justify="left",
                         wraplength=theme.medida(520))
        ruta.grid(row=i * 3 + 1, column=0, columnspan=2, sticky="w", pady=(2, 8))
        lineas[clave] = (cifra, ruta)

    # --- purgar ------------------------------------------------------------------
    caja = ttk.Frame(marco)
    caja.grid(row=fila, column=0, sticky="ew", pady=(16, 0))
    caja.columnconfigure(2, weight=1)
    ttk.Label(caja, text="Purgar", style="Campo.TLabel").grid(row=0, column=0,
                                                              padx=(0, 10))
    antiguedad = StringVar(value=ANTIGUEDADES[0][0])
    ttk.Combobox(caja, textvariable=antiguedad, state="readonly", width=18,
                 values=[t for t, _ in ANTIGUEDADES]).grid(row=0, column=1)
    fila += 1

    def corte() -> date:
        dias = dict(ANTIGUEDADES)[antiguedad.get()]
        return date.today() - timedelta(days=dias)

    # --- releer ------------------------------------------------------------------

    def pareja_actual():
        return next(p for p in parejas if p.name == elegida.get())

    def refrescar(*_) -> None:
        """Relee los dos lados. El remoto va por `working()`: es red."""
        pair = pareja_actual()
        estado["pareja"] = pair
        estado["local"] = versions_editor.leer_local(pair)
        ok, resultado = working(dlg, "Versiones",
                                lambda: versions_editor.leer_remoto(pair),
                                "Preguntando al remoto…")
        estado["remoto"] = resultado if ok else versions_editor.Lado(
            versions_editor.REMOTO, pair.versions_path2, False,
            "no se ha podido preguntar")
        for clave, lado in ((versions_editor.DISPOSITIVO, estado["local"]),
                            (versions_editor.REMOTO, estado["remoto"])):
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
        purgar_btn.configure(
            state="normal" if (estado["local"].disponible and estado["local"].total)
            or (estado["remoto"].disponible and estado["remoto"].total) else "disabled")
        abrir_btn.configure(state="normal" if estado["local"].total else "disabled")

    elegida.trace_add("write", refrescar)

    # --- acciones ----------------------------------------------------------------

    def abrir_carpeta() -> None:
        destino = estado["pareja"].local_abs / model.VERSIONS_DIR
        try:
            abrir(destino)
        except OSError as e:
            messagebox.showerror(TITLE, f"No se ha podido abrir {destino}:\n{e}",
                                 parent=dlg)

    def purgar() -> None:
        plan = versions_editor.plan_purgar(estado["pareja"], estado["local"],
                                           estado["remoto"], corte())
        if plan.vacio:
            messagebox.showinfo(TITLE, plan.consequences[0], parent=dlg)
            return
        if not tk_pairs.confirmar_plan(
                dlg, plan, f"Purgar versiones de '{plan.pair_name}'",
                "Se borran en los dos lados"):
            return
        try:
            hechos = plan.execute()
        except Exception as e:                                    # noqa: BLE001
            messagebox.showerror(TITLE, str(e), parent=dlg)
            return
        refrescar()
        messagebox.showinfo(TITLE, "\n".join(hechos) or "No se ha borrado nada.",
                            parent=dlg)

    ttk.Separator(marco, orient="horizontal").grid(row=fila, column=0, sticky="ew",
                                                   pady=(16, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=fila + 1, column=0, sticky="ew", pady=(14, 0))
    pie.columnconfigure(0, weight=1)
    abrir_btn = ttk.Button(pie, text="Abrir la carpeta", style="Quiet.TButton",
                           command=abrir_carpeta)
    theme.boton_icono(abrir_btn, "file", theme.ACENTO, theme.PAPEL)
    abrir_btn.grid(row=0, column=0, sticky="w")
    purgar_btn = ttk.Button(pie, text="Purgar…", command=purgar)
    purgar_btn.grid(row=0, column=1, padx=(10, 6))
    ttk.Button(pie, text="Cerrar", command=dlg.destroy).grid(row=0, column=2)

    refrescar()
    mostrar(dlg, parent)


def _pie(marco, dlg, fila: int) -> None:
    from tkinter import ttk
    ttk.Separator(marco, orient="horizontal").grid(row=fila, column=0, sticky="ew",
                                                   pady=(16, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=fila + 1, column=0, sticky="e", pady=(14, 0))
    ttk.Button(pie, text="Cerrar", command=dlg.destroy).grid(row=0, column=0)
