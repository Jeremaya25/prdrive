#!/usr/bin/env python3
"""«Ajustes»: lo que se hace de vez en cuando y no cada vez.

Era «Doctor», un botón que lanzaba `sync.py --doctor` y nada más. Se convirtió
en una pantalla por una razón concreta: la ventana principal ya está llena (sus
avisos, la lista de parejas, tres botones y dos acciones) y todo lo que se hace
una vez en la vida del dispositivo tiene que caber en algún sitio que no sea
esa ventana. Esta es ese sitio.

En la ventana se llama «Ajustes», detrás de un engranaje, y no «Doctor»: el
doctor es una de sus entradas, no la pantalla. El módulo conserva su nombre
porque el subcomando `sync.py --doctor` no cambia.

Es una ventana con una barra lateral y, a la derecha, el apartado elegido,
dibujado en el sitio: los apartados agrupados por de qué hablan (esta unidad,
este equipo, la conexión, el mantenimiento) y un campo arriba que filtra la
barra por lo que se escribe. Cada apartado es la pantalla de siempre, que se
dibuja con su `construir(panel, …)` (`tk.Panel`): la misma que se abre suelta
desde la ventana principal (la línea del arranque, la de «Reparación», el
aviso de versión nueva). Esta ventana solo dibuja la barra y cambia de
apartado; lo que pasa dentro lo hace el módulo de turno.

Lo que los apartados le tienen que decir a la ventana principal (activar el
llavero, reparar, actualizar, pedirle otro modo al agente) se apunta por
apartado y se devuelve al cerrar, porque es la principal quien relee el
config, lanza pasadas y se cierra para reabrirse. `lanzar` llega de ella por
lo mismo: la ventana de salida es hija suya, y un apartado que lanza una
pasada cierra antes esta ventana (`panel.cerrar`), porque dos modales no
pueden tener la captura a la vez.

Un apartado sale solo a veces: «Catálogo del remoto», mientras el remoto
conserve su `pairs.toml`, y eso lo dice `catalog_editor.ofrecer_renombrado()`
sin red (`OCASIONALES`).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from common import fleet, model, revision, update
from common.model import Config

from . import catalog_editor, icons, theme, watch
from .tk import Panel, cuerpo_visible, modal, mostrar


@dataclass(frozen=True)
class Apartado:
    """Una entrada de la barra lateral.

    Attributes:
        clave: Cómo se llama por dentro; es también la clave de lo que devuelve.
        rotulo: Lo que dice la barra.
        icono: El glifo de `icons`.
        palabras: Más cosas por las que se encuentra al buscar, además del
            rótulo: lo que hay dentro («intervalo» está en «Configuración»).
    """

    clave: str
    rotulo: str
    icono: str
    palabras: str = ""


GRUPOS = (
    ("Esta unidad", (
        Apartado("volumen", "Nombre e icono", "edit",
                 "nombre icono unidad explorador color autorun"),
        Apartado("configuracion", "Configuración", "gear",
                 "intervalo minutos servicio contraseña iniciar sesión"),
        Apartado("llavero", "Llavero", "llave",
                 "keepassxc contraseñas passkeys fichero llave base"),
        Apartado("versiones", "Versiones", "file",
                 "prversions purgar histórico copias"),
    )),
    ("Este equipo", (
        Apartado("arranque", "Arranque automático", "arranque",
                 "vigilante agente enchufar penwatch tarea"),
    )),
    ("Conexión", (
        Apartado("qr", "Emparejar un móvil", "dispositivo",
                 "qr código móvil clave conexión"),
        Apartado("renombrar", "Catálogo del remoto", "nas",
                 "pairs.toml remote.toml renombrar catálogo"),
    )),
    ("Mantenimiento", (
        Apartado("reparacion", "Reparación", "doctor",
                 "baseline bloqueos conflictos resync doctor simular informe"),
        Apartado("actualizaciones", "Actualizaciones", "reload",
                 "versión nueva buscar componentes rclone python veracrypt"),
    )),
)
"""Los apartados de la barra, por grupos y en el orden en que salen."""

OCASIONALES = {"renombrar": catalog_editor.ofrecer_renombrado}
"""Los apartados que solo salen a veces: su clave y quién dice, sin red, si sale."""

INICIAL = "configuracion"
"""El apartado con que se abre si no se pide otro."""

ANCHO_BARRA = 248
"""El ancho de la barra lateral, en medidas del diseño."""
ANCHO_APARTADO = 640
"""El ancho mínimo del apartado, en medidas del diseño."""
ALTO_APARTADO = 480
"""El alto mínimo del apartado: el de los más altos de uso corriente."""

AL_DIA = "Este dispositivo lleva la última versión que se conoce"
"""El título del apartado de actualizaciones cuando no hay nada nuevo."""


def normalizar(texto: str) -> str:
    """Devuelve el texto en minúsculas y sin tildes, para buscar."""
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower())
                   if unicodedata.category(c) != "Mn")


def coincide(apartado: Apartado, busqueda: str) -> bool:
    """Indica si un apartado sale con lo escrito en «Buscar un ajuste».

    Cada palabra de la búsqueda tiene que estar, al principio de alguna
    palabra del rótulo o de sus palabras clave, sin tildes ni mayúsculas.
    """
    dentro = normalizar(f"{apartado.rotulo} {apartado.palabras}").split()
    return all(any(d.startswith(p) for d in dentro)
               for p in normalizar(busqueda).split())


def open_dialog(parent, config: Config, lanzar, raw_local: dict | None = None,
                buscar_version=None, inicial: str | None = None, nueva=None,
                componentes=None, vigilante=None, hallazgos=None,
                marcadas=None, compartida=None) -> dict:
    """Abre «Ajustes» y devuelve lo que han dicho sus apartados.

    Args:
        config: La configuración, que se pasa a los apartados que la necesitan.
        lanzar: `lanzar(titulo, args)`, el de la ventana principal.
        raw_local: El `sync_config.toml` en crudo, para el emparejamiento.
        buscar_version: `buscar_version(responder)` de la ventana principal:
            pregunta a la red en un hilo y llama a `responder(texto)` desde el
            hilo de Tk con lo que hay que decir. Sin él no hay botón «Buscar
            actualizaciones».
        inicial: La clave del apartado con que se abre (`INICIAL` si no).
        nueva: La versión nueva pendiente (`update.pending()`), si la hay.
        componentes: Los componentes anticuados (`components.pendientes()`).
        vigilante: Qué hace este equipo al enchufar (`watch.resumen()`); con
            el agente residente, el apartado es «Qué hace el agente».
        hallazgos: Lo que ha encontrado `revision.revisar()`, para el número
            junto a «Reparación».
        marcadas: Las parejas marcadas en la ventana principal, que es lo que
            «Reparación» simula.
        compartida: La lectura compartida de la ventana principal
            (`ui.instantanea.Compartida`), o `None`. Todavía no se usa.

    Returns:
        Por clave de apartado, lo último que devolvió: `'llavero'` (`ACTIVADO`
        o `CAMBIADO`), `'reparacion'` (si cambió algo), `'actualizaciones'`
        (`True` si se ha actualizado el programa: hay que cerrar),
        `'componentes'` (`True` o `tk_update.CERRAR`), `'arranque'` (el modo
        pedido al agente, o `True` si se tocó el vigilante) y
        `'configuracion'`.
    """
    import tkinter as tk
    from tkinter import ttk

    from . import tk_update

    raw = catalog_editor.raw_del_dispositivo(raw_local)
    resultados: dict = {}
    estado: dict = {"clave": None, "nueva": nueva, "componentes": componentes or [],
                    "nota": ""}

    dlg = modal(parent, "Ajustes")
    dlg.resultados = resultados                    # los tests lo miran
    # Toda la ventana va en su visor, como cualquier diálogo: en una pantalla
    # baja la barra lateral sola ya no cabe, y entonces se desplaza todo junto.
    raiz = cuerpo_visible(dlg, padding=(theme.E5, theme.E5, theme.E5, theme.E5))
    raiz.columnconfigure(1, weight=1, minsize=icons.px(dlg, ANCHO_APARTADO))
    raiz.rowconfigure(1, weight=1, minsize=icons.px(dlg, ALTO_APARTADO))

    # Arriba: el título y el buscador.
    arriba = ttk.Frame(raiz)
    arriba.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, theme.E4))
    arriba.columnconfigure(0, weight=1)
    # Todo en una línea y centrado con el título; el rótulo del buscador va
    # dentro del campo, como pista, y se va al escribir o al entrar en él.
    ttk.Label(arriba, text="Ajustes", style="Titulo.TLabel").grid(
        row=0, column=0, sticky="w")
    busqueda = tk.StringVar(dlg)
    buscador = ttk.Entry(arriba, textvariable=busqueda, width=34)
    buscador.grid(row=0, column=1, sticky="e")
    buscador.pista = theme.pista_campo(buscador, "Buscar un ajuste…")

    # La barra lateral.
    barra = ttk.Frame(raiz)
    barra.grid(row=1, column=0, sticky="nsw", padx=(0, theme.E5))
    barra.columnconfigure(0, weight=1, minsize=theme.medida(ANCHO_BARRA))

    # El apartado, que ocupa al menos lo que piden los más altos: cambiar de
    # uno a otro no puede hacer bailar la ventana.
    contenido = ttk.Frame(raiz)
    contenido.grid(row=1, column=1, sticky="nsew")
    contenido.columnconfigure(0, weight=1)
    contenido.rowconfigure(0, weight=1)

    hay_renombrado = {c: f(raw) for c, f in OCASIONALES.items()}
    del_equipo = model.es_equipo()

    def sale(apartado: Apartado) -> bool:
        """Indica si el apartado sale en esta ventana, busque lo que se busque."""
        return hay_renombrado.get(apartado.clave, True)

    def chip_de(clave: str):
        """Devuelve `(texto, tipo, icono)` del chip de un apartado, o `None`."""
        if clave == "reparacion":
            cuenta = revision.cuenta(hallazgos or [])
            return (str(cuenta), "Aviso.", "warn") if cuenta else None
        if clave == "actualizaciones":
            if estado["nueva"] is not None:
                return (estado["nueva"].version, "Acento.", "down")
            if estado["componentes"]:
                return ("componentes", "Aviso.", "warn")
        return None

    # Los botones de la barra, por clave, y los rótulos de los grupos.
    entradas: dict = {}
    rotulos: list = []

    def pintar_barra() -> None:
        """Dibuja la barra entera: grupos, apartados y la versión al pie."""
        for hijo in barra.winfo_children():
            hijo.destroy()
        entradas.clear()
        rotulos.clear()
        fila = 0
        for grupo, apartados in GRUPOS:
            visibles = [a for a in apartados if sale(a)]
            if not visibles:
                continue
            if grupo == "Esta unidad" and del_equipo:
                grupo = "Esta carpeta"
            rotulo = ttk.Label(barra, text=theme.rotulo(grupo), style="Rotulo.TLabel")
            rotulo.grid(row=fila, column=0, sticky="w", padx=(theme.E3, 0),
                        pady=(theme.E3 if fila else 0, theme.E1))
            fila += 1
            miembros = []
            for apartado in visibles:
                boton = ttk.Button(barra, text=apartado.rotulo, style="Nav.TButton",
                                   command=lambda c=apartado.clave: elegir(c))
                theme.boton_icono(boton, apartado.icono, theme.TINTA2, theme.PAPEL)
                boton.grid(row=fila, column=0, sticky="ew", pady=(0, theme.E1))
                chip = chip_de(apartado.clave)
                if chip is not None:
                    texto, tipo, icono = chip
                    marca = theme.chip(boton, texto, tipo, icono)
                    marca.place(relx=1.0, rely=0.5, x=-icons.px(boton, 8), anchor="e")
                    marca.bind("<Button-1>", lambda _e, c=apartado.clave: elegir(c))
                entradas[apartado.clave] = (apartado, boton, fila)
                miembros.append(apartado.clave)
                fila += 1
            rotulos.append((rotulo, miembros))
        barra.rowconfigure(fila, weight=1)
        version = update.installed_version() or "desarrollo"
        try:
            nombre = fleet.nombre()
        except Exception:                            # noqa: BLE001 — solo es un rótulo
            nombre = ""
        ttk.Label(barra, text=f"prdrive {version}" + (f" · {nombre}" if nombre else ""),
                  style="Pista.TLabel", wraplength=theme.medida(ANCHO_BARRA - 12),
                  justify="left").grid(row=fila + 1, column=0, sticky="sw",
                                       padx=(theme.E3, 0), pady=(theme.E4, 0))
        marcar()

    def marcar() -> None:
        """Pinta elegido el botón del apartado a la vista y los demás no."""
        for clave, (_a, boton, _f) in entradas.items():
            boton.configure(style="NavSel.TButton" if clave == estado["clave"]
                            else "Nav.TButton")
            fondo = theme.ACENTO_SUAVE if clave == estado["clave"] else theme.PAPEL
            theme.boton_icono(boton, entradas[clave][0].icono, theme.TINTA2, fondo)

    def filtrar(*_) -> None:
        """Deja en la barra solo lo que coincide con lo escrito."""
        texto = busqueda.get()
        for clave, (apartado, boton, _f) in entradas.items():
            if coincide(apartado, texto):
                boton.grid()
            else:
                boton.grid_remove()
        for rotulo, miembros in rotulos:
            if any(entradas[c][1].grid_info() for c in miembros):
                rotulo.grid()
            else:
                rotulo.grid_remove()

    busqueda.trace_add("write", filtrar)

    def primero_visible(_evento=None) -> None:
        """Con Intro en el buscador, abre el primer apartado que queda."""
        for clave, (_a, boton, _f) in entradas.items():
            if boton.grid_info():
                elegir(clave)
                return

    buscador.bind("<Return>", primero_visible)

    # Los apartados.

    def construir_actualizaciones(panel: Panel) -> None:
        """Lo nuevo si lo hay; si no, los componentes; si no, buscar a mano."""
        if estado["nueva"] is not None:
            tk_update.construir(panel, estado["nueva"])
            return
        if estado["componentes"]:
            tk_update.construir_componentes(panel, estado["componentes"])
            return
        marco = panel.marco
        actual = update.installed_version() or "desconocida"
        ttk.Label(marco, text=AL_DIA, style="Dialogo.TLabel", wraplength=theme.medida(600),
                  justify="left").grid(row=0, column=0, sticky="w")
        ttk.Label(marco, text=f"Lleva la {actual}. Se comprueba sola cada 24 horas; "
                              "aquí se puede preguntar ahora.",
                  style="Pista.TLabel", wraplength=theme.medida(600),
                  justify="left").grid(row=1, column=0, sticky="w", pady=(theme.E1, 0))
        if buscar_version is None:
            return
        respuesta = ttk.Label(marco, text="", style="Pista.TLabel",
                              wraplength=theme.medida(600), justify="left")
        respuesta.grid(row=3, column=0, sticky="w", pady=(theme.E3, 0))

        def buscar() -> None:
            """Pregunta por una versión nueva y dice la respuesta debajo."""
            boton.state(["disabled"])
            respuesta.configure(text="Buscando…")

            def responder(texto: str) -> None:
                """Pone la respuesta, si el apartado sigue a la vista."""
                try:
                    if not respuesta.winfo_exists():
                        return
                except Exception:                    # noqa: BLE001 — Tk cerrado
                    return
                try:
                    estado["nueva"] = update.pending()
                except Exception:                    # noqa: BLE001
                    estado["nueva"] = None
                if estado["nueva"] is not None:
                    pintar_barra()
                    rehacer(texto)
                    return
                respuesta.configure(text=texto)
                boton.state(["!disabled"])

            buscar_version(responder)

        boton = ttk.Button(marco, text="Buscar actualizaciones", command=buscar)
        theme.boton_icono(boton, "reload", theme.TINTA2, theme.SUPERFICIE)
        boton.grid(row=2, column=0, sticky="w", pady=(theme.E4, 0))
        dlg.boton_buscar = boton                   # los tests lo pulsan

    def construir_arranque(panel: Panel) -> None:
        """El vigilante, o lo que hace el agente si este equipo lo tiene."""
        from . import tk_watch
        if vigilante is not None and vigilante.es_agente:
            modo = resultados.get("arranque")
            res = watch.pedido(vigilante, modo) if isinstance(modo, str) else vigilante
            tk_watch.construir_agente(panel, res)
            return
        panel.devolver(True)       # al volver, la principal relee el vigilante
        tk_watch.construir(panel)

    def construir_de(clave: str):
        """Devuelve la función que dibuja el apartado `clave` en un panel."""
        from . import (tk_configuracion, tk_llavero, tk_qr, tk_renombrar, tk_repair,
                       tk_versions, tk_volumen)
        return {
            "volumen": tk_volumen.construir,
            "configuracion": lambda p: tk_configuracion.construir(p, config),
            "llavero": lambda p: tk_llavero.construir_ajustes(p, raw_local),
            "versiones": lambda p: tk_versions.construir(p, config),
            "arranque": construir_arranque,
            "qr": lambda p: tk_qr.construir(p, raw_local),
            "renombrar": lambda p: tk_renombrar.construir(p, raw),
            "reparacion": lambda p: tk_repair.construir(p, config, lanzar, marcadas),
            "actualizaciones": construir_actualizaciones,
        }[clave]

    def clave_resultado(clave: str) -> str:
        """Bajo qué clave apunta lo suyo un apartado.

        El de actualizaciones dibuja dos pantallas distintas, y lo que
        devuelve cada una se le dice a la principal por separado.
        """
        if (clave == "actualizaciones" and estado["nueva"] is None
                and estado["componentes"]):
            return "componentes"
        return clave

    def rehacer(nota: str = "") -> None:
        """Vuelve a dibujar el apartado a la vista, con una nota encima si la hay."""
        estado["nota"] = nota
        if estado["clave"] == "actualizaciones" and resultados.get("componentes") is True:
            # Ya puestos al día, lo que había que poner se ha quedado viejo.
            from common import components
            try:
                estado["componentes"] = components.pendientes()
            except Exception:                        # noqa: BLE001
                estado["componentes"] = []
            pintar_barra()
        elegir(estado["clave"], forzar=True)

    def elegir(clave: str, forzar: bool = False) -> None:
        """Pone a la vista el apartado `clave`."""
        if clave == estado["clave"] and not forzar:
            return
        if clave not in entradas:
            clave = INICIAL
        if clave != estado["clave"]:
            estado["nota"] = ""
        estado["clave"] = clave
        marcar()
        for hijo in contenido.winfo_children():
            hijo.destroy()
        hueco = ttk.Frame(contenido)
        hueco.grid(row=0, column=0, sticky="nsew")
        hueco.columnconfigure(0, weight=1)
        hueco.rowconfigure(1, weight=1)
        if estado["nota"]:
            theme.aviso(hueco, "", estado["nota"], tono="Verde.", icono="ok",
                        ancho=ANCHO_APARTADO - 80).grid(row=0, column=0, sticky="ew",
                                                        pady=(0, theme.E4))
        marco = ttk.Frame(hueco)
        marco.grid(row=1, column=0, sticky="nsew")
        marco.columnconfigure(0, weight=1)
        panel = Panel(dlg, marco, incrustado=True, al_terminar=rehacer,
                      al_cerrar=dlg.destroy, resultados=resultados,
                      clave=clave_resultado(clave))
        dlg.panel = panel                          # los tests lo miran
        construir_de(clave)(panel)
        try:
            if dlg.winfo_exists():
                panel.ajustar()
        except Exception:                            # noqa: BLE001 — ya cerrada
            pass

    pintar_barra()
    elegir(inicial if inicial in entradas else INICIAL)
    try:
        vivo = bool(dlg.winfo_exists())
    except Exception:                                # noqa: BLE001
        vivo = False
    if vivo:
        mostrar(dlg, parent)
    return resultados
