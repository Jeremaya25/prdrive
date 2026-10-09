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

Nada se dibuja dos veces. La barra se dibuja al abrir y cambiar de apartado
restila dos botones (el que se deja y el que se elige). Cada apartado se
dibuja la primera vez que se elige, en un marco suyo, y al dejarlo se esconde
en vez de destruirse: volver a él es enseñar el mismo marco. Solo el código
QR se tira al dejarlo (`EFIMEROS`): lleva una clave privada y su marco al
destruirse levanta la protección contra capturas de pantalla. Un apartado que
da algo por terminado (`Panel.terminar()`) se rehace con su nota y se tiran los
demás, porque lo que enseñaban ha podido cambiar.

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

from . import catalog_editor, icons, perf_al_pintar, perf_empezar, theme, watch
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

EFIMEROS = ("qr",)
"""Los apartados que no se conservan al dejarlos: se destruyen y se dibujan de nuevo.

El código QR enseña una clave privada: su marco al destruirse levanta la
protección contra capturas de pantalla (`tk_qr`), y un código guardado
escondido seguiría existiendo.
"""

ANCHO_BARRA = 248
"""El ancho de la barra lateral, en medidas del diseño."""
ANCHO_APARTADO = 640
"""El ancho mínimo del apartado, en medidas del diseño."""
ALTO_APARTADO = 480
"""El alto mínimo del apartado: el de los más altos de uso corriente."""

AL_DIA = "Este dispositivo lleva la última versión que se conoce"
"""El título del apartado de actualizaciones cuando no hay nada nuevo."""

ESPERANDO = "Mirando si hay algo que poner al día…"
"""Lo que dice «Actualizaciones» mientras no ha llegado la lectura de la ventana principal."""


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


def chip_de(clave: str, cuenta: int, nueva, componentes) -> tuple[str, str, str] | None:
    """Devuelve `(texto, tipo, icono)` del chip de un apartado, o `None` si no lleva.

    Args:
        clave: El apartado.
        cuenta: Cuántas cosas hay que revisar (`revision.cuenta()`); es el
            número junto a «Reparación».
        nueva: La versión nueva pendiente (`update.pending()`), o `None`.
        componentes: Los componentes anticuados; vacío o `None` si no hay.
    """
    if clave == "reparacion":
        return (str(cuenta), "Aviso.", "warn") if cuenta else None
    if clave == "actualizaciones":
        if nueva is not None:
            return (nueva.version, "Acento.", "down")
        if componentes:
            return ("componentes", "Aviso.", "warn")
    return None


def open_dialog(parent, config: Config, lanzar, raw_local: dict | None = None,
                buscar_version=None, inicial: str | None = None, nueva=None,
                componentes=None, vigilante=None, hallazgos=None,
                marcadas=None, compartida=None) -> dict:
    """Abre «Ajustes» y devuelve lo que han dicho sus apartados.

    La ventana lleva, para los tests y para quien la vuelva a enseñar:
    `resultados`, `panel` (el `Panel` del apartado a la vista), `paneles`
    (`{clave: (marco, Panel)}` de los apartados dibujados), `chips` (`{clave:
    (texto, tipo, icono) o None}` de los chips de la barra) y `aplicar()`, que
    la deja como una apertura nueva.

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
            el agente residente, el apartado es «Qué hace el agente». Puede
            ser `None` si la ventana principal todavía no lo ha leído.
        hallazgos: Lo que ha encontrado `revision.revisar()`, para el número
            junto a «Reparación».
        marcadas: Las parejas marcadas en la ventana principal, que es lo que
            «Reparación» simula.
        compartida: La lectura compartida de la ventana principal
            (`ui.instantanea.Compartida`), o `None`. Si hay lectura, de ella
            salen los chips de la barra, el vigilante y los componentes, en
            vez de los parámetros `hallazgos`, `vigilante` y `componentes`
            (que valen mientras no llegue), y la ventana se suscribe para
            repintar lo suyo cuando llega otra. Una lectura vacía, o donde el
            campo falló, no cuenta. «Reparación» pinta su primera lista de ella.
            Sin lectura, un apartado que la necesita no cae a ninguna pantalla
            equivocada por falta de datos: «Arranque automático» lee el
            vigilante él mismo (solo ficheros) y «Actualizaciones» espera con un
            indicador y se rehace al llegar.

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

    def leida(campo: str):
        """Devuelve la lectura compartida si vale para ese campo, o `None`.

        No vale una vacía (`huella` ausente: el hilo falló y no leyó nada) ni
        una donde ese campo falló: tendría el valor por defecto, no el real.
        """
        inst = compartida.actual if compartida is not None else None
        if inst is None or inst.huella is None or campo in inst.fallos:
            return None
        return inst

    def pendientes_propios() -> list:
        """Lee aquí mismo los componentes anticuados; vacío si no se puede."""
        from common import components
        try:
            return list(components.pendientes())
        except Exception:                            # noqa: BLE001
            return []

    def lista_de_componentes() -> list | None:
        """Devuelve los componentes anticuados, o `None` si todavía no se saben.

        Sin lectura compartida es lo que dice el parámetro, como siempre. Con
        ella, de la lectura si vale; si no, del parámetro cuando trae alguno.
        Si ni uno ni otro y todavía no ha llegado ninguna lectura, no se saben:
        una lista vacía puede ser «no hay» o «aún no se ha mirado», y darla por
        buena diría «al día» sin haber mirado. Si ya llegó una pero sin ellos
        (el hilo falló), se miran aquí.
        """
        inst = leida("componentes")
        if inst is not None:
            return list(inst.componentes)
        if compartida is None or componentes:
            return list(componentes or [])
        if compartida.actual is not None:
            return pendientes_propios()
        return None

    # `componentes` es `None` mientras no se sepa; el resto, lo de siempre.
    estado: dict = {"clave": None, "nueva": nueva, "componentes": lista_de_componentes()}

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

    def chip_actual(clave: str):
        """Devuelve `(texto, tipo, icono)` del chip que le toca ahora a un apartado, o `None`.

        La cuenta de «Reparación» sale de la lectura compartida si la hay, y si
        no del parámetro `hallazgos`.
        """
        inst = leida("hallazgos")
        cuenta = inst.cuenta if inst is not None else revision.cuenta(hallazgos or [])
        return chip_de(clave, cuenta, estado["nueva"], estado["componentes"])

    # Los botones de la barra, por clave, y los rótulos de los grupos.
    entradas: dict = {}
    rotulos: list = []
    chips: dict = {}                               # lo dibujado: clave -> chip o None
    marcas: dict = {}                              # las etiquetas de los chips dibujados
    dlg.chips = chips                              # los tests lo miran

    def pintar_barra() -> None:
        """Dibuja la barra entera, una sola vez: grupos, apartados y la versión al pie."""
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
                entradas[apartado.clave] = (apartado, boton, fila)
                chips[apartado.clave] = None
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
        poner_chips()

    def poner_chips() -> None:
        """Recalcula el chip de cada apartado y cambia solo los que son otros.

        El chip que no cambia es el mismo widget: no se destruye ni se crea.
        """
        for clave, (_a, boton, _f) in entradas.items():
            nuevo = chip_actual(clave)
            if nuevo == chips.get(clave):
                continue
            viejo = marcas.pop(clave, None)
            if viejo is not None:
                viejo.destroy()
            chips[clave] = nuevo
            if nuevo is None:
                continue
            texto, tipo, icono = nuevo
            marca = theme.chip(boton, texto, tipo, icono)
            marca.place(relx=1.0, rely=0.5, x=-icons.px(boton, 8), anchor="e")
            marca.bind("<Button-1>", lambda _e, c=clave: elegir(c))
            marcas[clave] = marca

    def marcar(antes: str | None, ahora: str) -> None:
        """Pasa el botón elegido de `antes` a `ahora`; los demás ni se tocan.

        Un botón que cambia de cara deja a su chip con las esquinas de la cara
        de antes: se vuelve a asentar (`theme.reasentar()`).
        """
        if antes == ahora:
            return
        for clave, elegido in ((antes, False), (ahora, True)):
            if clave is None or clave not in entradas:
                continue
            apartado, boton, _f = entradas[clave]
            boton.configure(style="NavSel.TButton" if elegido else "Nav.TButton")
            theme.boton_icono(boton, apartado.icono, theme.TINTA2,
                              theme.ACENTO_SUAVE if elegido else theme.PAPEL)
            theme.reasentar(boton)

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
        dibujado["actualizaciones"] = forma_actualizaciones()
        if estado["nueva"] is not None:
            tk_update.construir(panel, estado["nueva"])
            return
        if estado["componentes"] is None:
            # La lectura de la ventana principal aún no ha llegado: se espera con
            # un indicador y el apartado se rehace al llegar (`al_llegar`).
            espera = panel.indicador(panel.marco, ancho=600)
            espera.marco.grid(row=0, column=0, sticky="ew")
            espera.poner(ESPERANDO, True)
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
                """Pone la respuesta en su apartado, esté a la vista o escondido."""
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
                    poner_chips()
                    if estado["clave"] == "actualizaciones":
                        rehacer(texto)
                    else:
                        tirar("actualizaciones")     # se dibuja con la novedad al volver
                    return
                respuesta.configure(text=texto)
                boton.state(["!disabled"])

            buscar_version(responder)

        boton = ttk.Button(marco, text="Buscar actualizaciones", command=buscar)
        theme.boton_icono(boton, "reload", theme.TINTA2, theme.SUPERFICIE)
        boton.grid(row=2, column=0, sticky="w", pady=(theme.E4, 0))
        dlg.boton_buscar = boton                   # los tests lo pulsan

    def forma_actualizaciones():
        """Devuelve qué enseñaría hoy «Actualizaciones», para saber si el dibujado ya no vale."""
        if estado["nueva"] is not None:
            return ("nueva", estado["nueva"].version)
        if estado["componentes"] is None:
            return ("esperando",)
        if estado["componentes"]:
            return ("componentes", tuple(estado["componentes"]))
        return ("al día",)

    def vigilante_ahora():
        """Devuelve qué hace este equipo al enchufar, sin caer nunca a falta de datos.

        La lectura compartida si vale; si no, el parámetro; si tampoco, se lee
        (`watch.resumen()` solo mira ficheros, como cuando la ventana principal
        lo leía al pintarse).
        """
        inst = leida("vigilante")
        if inst is not None:
            return inst.vigilante
        if vigilante is not None:
            return vigilante
        try:
            return watch.resumen()
        except Exception:                            # noqa: BLE001
            return watch.Resumen("no_disponible")

    def construir_arranque(panel: Panel) -> None:
        """El vigilante, o lo que hace el agente si este equipo lo tiene."""
        from . import tk_watch
        ahora = vigilante_ahora()
        if ahora.es_agente:
            modo = resultados.get("arranque")
            res = watch.pedido(ahora, modo) if isinstance(modo, str) else ahora
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
            "reparacion": lambda p: tk_repair.construir(p, config, lanzar, marcadas,
                                                        compartida=compartida),
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

    # Los apartados dibujados, a la vista o escondidos.
    paneles: dict = {}                             # clave -> (marco, Panel)
    con_nota: set = set()                          # los dibujados con una nota encima
    dibujado: dict = {}                            # qué forma tenía «Actualizaciones» al dibujarse
    dlg.paneles = paneles                          # los tests lo miran

    def ajustar(panel: Panel) -> None:
        """Hace sitio al apartado recién enseñado, si la ventana sigue ahí."""
        try:
            if dlg.winfo_exists():
                panel.ajustar()
        except Exception:                            # noqa: BLE001 — ya cerrada
            pass

    def dibujar(clave: str, nota: str = "") -> None:
        """Dibuja el apartado `clave` en un marco suyo, a la vista, con la nota si la hay."""
        hueco = ttk.Frame(contenido)
        hueco.grid(row=0, column=0, sticky="nsew")
        hueco.columnconfigure(0, weight=1)
        hueco.rowconfigure(1, weight=1)
        if nota:
            theme.aviso(hueco, "", nota, tono="Verde.", icono="ok",
                        ancho=ANCHO_APARTADO - 80).grid(row=0, column=0, sticky="ew",
                                                        pady=(0, theme.E4))
        marco = ttk.Frame(hueco)
        marco.grid(row=1, column=0, sticky="nsew")
        marco.columnconfigure(0, weight=1)
        panel = Panel(dlg, marco, incrustado=True, al_terminar=rehacer,
                      al_cerrar=dlg.destroy, resultados=resultados,
                      clave=clave_resultado(clave))
        dlg.panel = panel                          # los tests lo miran
        paneles[clave] = (hueco, panel)
        if nota:
            con_nota.add(clave)
        try:
            construir_de(clave)(panel)
        except BaseException:
            tirar(clave)                           # ni a medias ni escondido debajo
            raise
        ajustar(panel)

    def tirar(clave: str) -> None:
        """Destruye el apartado dibujado `clave`, si lo hay."""
        entrada = paneles.pop(clave, None)
        con_nota.discard(clave)
        dibujado.pop(clave, None)
        if entrada is not None:
            entrada[0].destroy()

    def dejar(clave: str) -> None:
        """Deja el apartado: lo esconde y lo guarda, o lo tira si no se conserva.

        Se tira el que no se conserva (`EFIMEROS`) y el que lleva una nota: al
        volver a él, como antes, se dibuja sin ella.
        """
        hueco, panel = paneles[clave]
        panel.ocultado()
        if clave in EFIMEROS or clave in con_nota:
            tirar(clave)
        else:
            hueco.grid_remove()

    def rehacer(nota: str = "") -> None:
        """Vuelve a dibujar el apartado a la vista, con una nota encima si la hay.

        Un apartado que da algo por terminado ha podido cambiar lo que enseñan
        los demás (el config que guardó, el nombre de la unidad...), así que se
        tiran los otros ya dibujados en vez de guardar lo que enseñaban.
        """
        clave = estado["clave"]
        if clave == "actualizaciones" and resultados.get("componentes") is True:
            # Ya puestos al día, lo que había que poner se ha quedado viejo.
            estado["componentes"] = pendientes_propios()
        for otra in [k for k in paneles if k != clave]:
            tirar(otra)
        tirar(clave)
        dibujar(clave, nota)
        poner_chips()

    def elegir(clave: str) -> None:
        """Pone a la vista el apartado `clave`: el ya dibujado, o uno nuevo la primera vez."""
        if clave not in entradas:
            clave = INICIAL
        antes = estado["clave"]
        if clave == antes:
            return
        momento = f"pane-{clave}"
        perf_empezar(momento)
        marcar(antes, clave)
        estado["clave"] = clave
        if antes in paneles:
            dejar(antes)
        if clave in paneles:
            hueco, panel = paneles[clave]
            hueco.grid()
            dlg.panel = panel
            panel.mostrado()
            ajustar(panel)
        else:
            dibujar(clave)
        perf_al_pintar(dlg, momento)

    def aplicar() -> None:
        """Deja la ventana como al abrirla: sin búsqueda, sin apartados guardados y en el inicial."""
        busqueda.set("")
        for clave in list(paneles):
            tirar(clave)
        estado["componentes"] = lista_de_componentes()
        poner_chips()
        antes, estado["clave"] = estado["clave"], None
        elegir_inicial(antes)

    def elegir_inicial(antes: str | None = None) -> None:
        """Elige el apartado con que se abre, restilando solo los botones que cambian."""
        clave = inicial if inicial in entradas else INICIAL
        marcar(antes, clave)
        estado["clave"] = clave
        dibujar(clave)

    dlg.aplicar = aplicar

    def al_llegar(inst) -> None:
        """Recoge una lectura nueva de la ventana principal y repinta lo que depende de ella."""
        try:
            if not dlg.winfo_exists():
                return
        except Exception:                            # noqa: BLE001 — Tk cerrado
            return
        if inst.huella is not None and "componentes" not in inst.fallos:
            estado["componentes"] = list(inst.componentes)
        elif estado["componentes"] is None:
            # La lectura llegó sin ellos (el hilo falló): «Actualizaciones» no se
            # queda esperando para siempre, los mira aquí como hacía la principal.
            estado["componentes"] = pendientes_propios()
        poner_chips()
        entrada = paneles.get("actualizaciones")
        if entrada is None or dibujado.get("actualizaciones") == forma_actualizaciones():
            return
        if estado["clave"] == "actualizaciones":
            tirar("actualizaciones")
            dibujar("actualizaciones")
        else:
            tirar("actualizaciones")                 # se dibuja al día cuando se vuelva a él

    pintar_barra()
    if compartida is not None:
        # Las lecturas que llegan con la ventana abierta. La baja es de la
        # ventana: `<Destroy>` también llega por cada hijo que muere (el marco de
        # un apartado, el código QR...).
        baja = compartida.suscribir(al_llegar)
        dlg.bind("<Destroy>", lambda evento: baja() if evento.widget is dlg else None,
                 add="+")
    elegir_inicial()
    try:
        vivo = bool(dlg.winfo_exists())
    except Exception:                                # noqa: BLE001
        vivo = False
    if vivo:
        dlg.perf_momento = "open-ajustes"              # lo cierra `mostrar`, al pintarse
        mostrar(dlg, parent)
    return resultados
