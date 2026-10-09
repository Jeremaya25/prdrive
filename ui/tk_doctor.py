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


def _pendientes_propios() -> list:
    """Lee aquí mismo los componentes anticuados; vacío si no se puede."""
    from common import components
    try:
        return list(components.pendientes())
    except Exception:                                # noqa: BLE001
        return []


class VentanaAjustes:
    """La ventana «Ajustes»: la barra lateral y, a su derecha, el apartado elegido.

    La barra se dibuja una vez (`pintar_barra()`). Cada apartado se dibuja la
    primera vez que se elige, en un marco suyo dentro de `contenido`; al
    dejarlo se esconde (`dejar()`) y volver a él es enseñar el mismo marco. Lo
    que dicen los apartados se apunta en `resultados`, que es lo que devuelve
    `abrir()`.

    El `Toplevel` lleva, para los tests y para quien la vuelva a enseñar, los
    mismos objetos que esta clase: `dlg.resultados`, `dlg.panel`,
    `dlg.paneles`, `dlg.chips`, `dlg.aplicar` y, con «Actualizaciones» al día,
    `dlg.boton_buscar`.

    Args:
        parent: La ventana de la que cuelga.
        config: La configuración, que se pasa a los apartados que la necesitan.
        lanzar: `lanzar(titulo, args)`, el de la ventana principal.
        raw_local: El `sync_config.toml` en crudo, para el emparejamiento.
        buscar_version: `buscar_version(responder)` de la ventana principal, o
            `None` (sin botón «Buscar actualizaciones»).
        inicial: La clave del apartado con que se abre (`INICIAL` si no).
        nueva: La versión nueva pendiente (`update.pending()`), si la hay.
        componentes: Los componentes anticuados que da la ventana principal.
        vigilante: Qué hace este equipo al enchufar (`watch.resumen()`), o
            `None` si la ventana principal todavía no lo ha leído.
        hallazgos: Lo que ha encontrado `revision.revisar()`.
        marcadas: Las parejas marcadas en la ventana principal.
        compartida: La lectura compartida de la ventana principal, o `None`.

    Attributes:
        dlg: El `Toplevel`, retirado hasta `abrir()`.
        resultados: Por clave de apartado, lo último que devolvió.
        clave: El apartado a la vista, o `None` antes del primero.
        nueva: La versión nueva pendiente que enseña la ventana, o `None`.
        componentes: Los componentes anticuados, o `None` mientras no se sepan.
        entradas: Por clave, `(Apartado, botón, fila)` de la barra.
        rotulos: `(etiqueta, claves)` de cada grupo de la barra.
        chips: Por clave, el `(texto, tipo, icono)` del chip dibujado, o `None`.
        marcas: Por clave, la etiqueta del chip dibujado.
        paneles: Por clave, `(marco, Panel)` de los apartados dibujados, a la
            vista o escondidos.
        con_nota: Las claves de los apartados dibujados con una nota encima.
        forma_dibujada: Qué enseñaba «Actualizaciones» al dibujarse
            (`forma_actualizaciones()`), o `None` si no está dibujado.
    """

    def __init__(self, parent, config: Config, lanzar, raw_local: dict | None = None,
                 buscar_version=None, inicial: str | None = None, nueva=None,
                 componentes=None, vigilante=None, hallazgos=None,
                 marcadas=None, compartida=None) -> None:
        """Construye la ventana retirada, con el título, el buscador y los dos huecos."""
        import tkinter as tk
        from tkinter import ttk

        self.parent = parent
        self.config = config
        self.lanzar = lanzar
        self.raw_local = raw_local
        self.buscar_version = buscar_version
        self.inicial = inicial
        self.componentes_dados = componentes
        self.vigilante_dado = vigilante
        self.hallazgos = hallazgos
        self.marcadas = marcadas
        self.compartida = compartida
        self._baja = None

        self.raw = catalog_editor.raw_del_dispositivo(raw_local)
        self.resultados: dict = {}
        self.clave: str | None = None
        self.nueva = nueva
        self.componentes: list | None = self.lista_de_componentes()

        dlg = self.dlg = modal(parent, "Ajustes")
        dlg.resultados = self.resultados               # los tests lo miran
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
        self.busqueda = tk.StringVar(dlg)
        buscador = ttk.Entry(arriba, textvariable=self.busqueda, width=34)
        buscador.grid(row=0, column=1, sticky="e")
        buscador.pista = theme.pista_campo(buscador, "Buscar un ajuste…")

        # La barra lateral.
        self.barra = ttk.Frame(raiz)
        self.barra.grid(row=1, column=0, sticky="nsw", padx=(0, theme.E5))
        self.barra.columnconfigure(0, weight=1, minsize=theme.medida(ANCHO_BARRA))

        # El apartado, que ocupa al menos lo que piden los más altos: cambiar de
        # uno a otro no puede hacer bailar la ventana.
        self.contenido = ttk.Frame(raiz)
        self.contenido.grid(row=1, column=1, sticky="nsew")
        self.contenido.columnconfigure(0, weight=1)
        self.contenido.rowconfigure(0, weight=1)

        self.hay_renombrado = {c: f(self.raw) for c, f in OCASIONALES.items()}
        self.del_equipo = model.es_equipo()

        self.entradas: dict = {}
        self.rotulos: list = []
        self.chips: dict = {}
        self.marcas: dict = {}
        dlg.chips = self.chips                         # los tests lo miran

        self.busqueda.trace_add("write", self.filtrar)
        buscador.bind("<Return>", self.primero_visible)

        self.paneles: dict = {}
        self.con_nota: set = set()
        self.forma_dibujada = None
        dlg.paneles = self.paneles                     # los tests lo miran
        dlg.aplicar = self.aplicar

    def abrir(self) -> dict:
        """Dibuja la barra y el apartado inicial, enseña la ventana y espera a que se cierre.

        Returns:
            `resultados`, con lo que han dicho los apartados.
        """
        dlg = self.dlg
        self.pintar_barra()
        if self.compartida is not None:
            # Las lecturas que llegan con la ventana abierta. La baja es de la
            # ventana: `<Destroy>` también llega por cada hijo que muere (el marco de
            # un apartado, el código QR...).
            self._baja = self.compartida.suscribir(self.al_llegar)
            dlg.bind("<Destroy>", self._al_destruir, add="+")
        self.elegir_inicial()
        try:
            vivo = bool(dlg.winfo_exists())
        except Exception:                            # noqa: BLE001
            vivo = False
        if vivo:
            dlg.perf_momento = "open-ajustes"          # lo cierra `mostrar`, al pintarse
            mostrar(dlg, self.parent)
        return self.resultados

    def _al_destruir(self, evento) -> None:
        """Se da de baja de la lectura compartida cuando se destruye la ventana, no un hijo."""
        if evento.widget is self.dlg:
            self._baja()

    # La lectura compartida.

    def leida(self, campo: str):
        """Devuelve la lectura compartida si vale para ese campo, o `None`.

        No vale una vacía (`huella` ausente: el hilo falló y no leyó nada) ni
        una donde ese campo falló: tendría el valor por defecto, no el real.
        """
        inst = self.compartida.actual if self.compartida is not None else None
        if inst is None or inst.huella is None or campo in inst.fallos:
            return None
        return inst

    def lista_de_componentes(self) -> list | None:
        """Devuelve los componentes anticuados, o `None` si todavía no se saben.

        Sin lectura compartida es lo que dice el parámetro, como siempre. Con
        ella, de la lectura si vale; si no, del parámetro cuando trae alguno.
        Si ni uno ni otro y todavía no ha llegado ninguna lectura, no se saben:
        una lista vacía puede ser «no hay» o «aún no se ha mirado», y darla por
        buena diría «al día» sin haber mirado. Si ya llegó una pero sin ellos
        (el hilo falló), se miran aquí.
        """
        inst = self.leida("componentes")
        if inst is not None:
            return list(inst.componentes)
        if self.compartida is None or self.componentes_dados:
            return list(self.componentes_dados or [])
        if self.compartida.actual is not None:
            return _pendientes_propios()
        return None

    def al_llegar(self, inst) -> None:
        """Recoge una lectura nueva de la ventana principal y repinta lo que depende de ella."""
        try:
            if not self.dlg.winfo_exists():
                return
        except Exception:                            # noqa: BLE001 — Tk cerrado
            return
        if inst.huella is not None and "componentes" not in inst.fallos:
            self.componentes = list(inst.componentes)
        elif self.componentes is None:
            # La lectura llegó sin ellos (el hilo falló): «Actualizaciones» no se
            # queda esperando para siempre, los mira aquí como hacía la principal.
            self.componentes = _pendientes_propios()
        self.poner_chips()
        if ("actualizaciones" not in self.paneles
                or self.forma_dibujada == self.forma_actualizaciones()):
            return
        if self.clave == "actualizaciones":
            self.tirar("actualizaciones")
            self.dibujar("actualizaciones")
        else:
            self.tirar("actualizaciones")            # se dibuja al día cuando se vuelva a él

    # La barra.

    def sale(self, apartado: Apartado) -> bool:
        """Indica si el apartado sale en esta ventana, busque lo que se busque."""
        return self.hay_renombrado.get(apartado.clave, True)

    def chip_actual(self, clave: str):
        """Devuelve `(texto, tipo, icono)` del chip que le toca ahora a un apartado, o `None`.

        La cuenta de «Reparación» sale de la lectura compartida si la hay, y si
        no del parámetro `hallazgos`.
        """
        inst = self.leida("hallazgos")
        cuenta = inst.cuenta if inst is not None else revision.cuenta(self.hallazgos or [])
        return chip_de(clave, cuenta, self.nueva, self.componentes)

    def pintar_barra(self) -> None:
        """Dibuja la barra entera, una sola vez: grupos, apartados y la versión al pie."""
        from tkinter import ttk

        barra = self.barra
        fila = 0
        for grupo, apartados in GRUPOS:
            visibles = [a for a in apartados if self.sale(a)]
            if not visibles:
                continue
            if grupo == "Esta unidad" and self.del_equipo:
                grupo = "Esta carpeta"
            rotulo = ttk.Label(barra, text=theme.rotulo(grupo), style="Rotulo.TLabel")
            rotulo.grid(row=fila, column=0, sticky="w", padx=(theme.E3, 0),
                        pady=(theme.E3 if fila else 0, theme.E1))
            fila += 1
            miembros = []
            for apartado in visibles:
                boton = ttk.Button(barra, text=apartado.rotulo, style="Nav.TButton",
                                   command=lambda c=apartado.clave: self.elegir(c))
                theme.boton_icono(boton, apartado.icono, theme.TINTA2, theme.PAPEL)
                boton.grid(row=fila, column=0, sticky="ew", pady=(0, theme.E1))
                self.entradas[apartado.clave] = (apartado, boton, fila)
                self.chips[apartado.clave] = None
                miembros.append(apartado.clave)
                fila += 1
            self.rotulos.append((rotulo, miembros))
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
        self.poner_chips()

    def poner_chips(self) -> None:
        """Recalcula el chip de cada apartado y cambia solo los que son otros.

        El chip que no cambia es el mismo widget: no se destruye ni se crea.
        """
        for clave, (_a, boton, _f) in self.entradas.items():
            nuevo = self.chip_actual(clave)
            if nuevo == self.chips.get(clave):
                continue
            viejo = self.marcas.pop(clave, None)
            if viejo is not None:
                viejo.destroy()
            self.chips[clave] = nuevo
            if nuevo is None:
                continue
            texto, tipo, icono = nuevo
            marca = theme.chip(boton, texto, tipo, icono)
            marca.place(relx=1.0, rely=0.5, x=-icons.px(boton, 8), anchor="e")
            marca.bind("<Button-1>", lambda _e, c=clave: self.elegir(c))
            self.marcas[clave] = marca

    def marcar(self, antes: str | None, ahora: str) -> None:
        """Pasa el botón elegido de `antes` a `ahora`; los demás ni se tocan.

        Un botón que cambia de cara deja a su chip con las esquinas de la cara
        de antes: se vuelve a asentar (`theme.reasentar()`).
        """
        if antes == ahora:
            return
        for clave, elegido in ((antes, False), (ahora, True)):
            if clave is None or clave not in self.entradas:
                continue
            apartado, boton, _f = self.entradas[clave]
            boton.configure(style="NavSel.TButton" if elegido else "Nav.TButton")
            theme.boton_icono(boton, apartado.icono, theme.TINTA2,
                              theme.ACENTO_SUAVE if elegido else theme.PAPEL)
            theme.reasentar(boton)

    def filtrar(self, *_) -> None:
        """Deja en la barra solo lo que coincide con lo escrito."""
        texto = self.busqueda.get()
        for apartado, boton, _f in self.entradas.values():
            if coincide(apartado, texto):
                boton.grid()
            else:
                boton.grid_remove()
        for rotulo, miembros in self.rotulos:
            if any(self.entradas[c][1].grid_info() for c in miembros):
                rotulo.grid()
            else:
                rotulo.grid_remove()

    def primero_visible(self, _evento=None) -> None:
        """Con Intro en el buscador, abre el primer apartado que queda."""
        for clave, (_a, boton, _f) in self.entradas.items():
            if boton.grid_info():
                self.elegir(clave)
                return

    # Los apartados.

    def construir_actualizaciones(self, panel: Panel) -> None:
        """Lo nuevo si lo hay; si no, los componentes; si no, buscar a mano."""
        from tkinter import ttk

        from . import tk_update

        self.forma_dibujada = self.forma_actualizaciones()
        if self.nueva is not None:
            tk_update.construir(panel, self.nueva)
            return
        if self.componentes is None:
            # La lectura de la ventana principal aún no ha llegado: se espera con
            # un indicador y el apartado se rehace al llegar (`al_llegar`).
            espera = panel.indicador(panel.marco, ancho=600)
            espera.marco.grid(row=0, column=0, sticky="ew")
            espera.poner(ESPERANDO, True)
            return
        if self.componentes:
            tk_update.construir_componentes(panel, self.componentes)
            return
        marco = panel.marco
        actual = update.installed_version() or "desconocida"
        ttk.Label(marco, text=AL_DIA, style="Dialogo.TLabel", wraplength=theme.medida(600),
                  justify="left").grid(row=0, column=0, sticky="w")
        ttk.Label(marco, text=f"Lleva la {actual}. Se comprueba sola cada 24 horas; "
                              "aquí se puede preguntar ahora.",
                  style="Pista.TLabel", wraplength=theme.medida(600),
                  justify="left").grid(row=1, column=0, sticky="w", pady=(theme.E1, 0))
        if self.buscar_version is None:
            return
        respuesta = ttk.Label(marco, text="", style="Pista.TLabel",
                              wraplength=theme.medida(600), justify="left")
        respuesta.grid(row=3, column=0, sticky="w", pady=(theme.E3, 0))
        boton = ttk.Button(marco, text="Buscar actualizaciones",
                           command=lambda: self.buscar(boton, respuesta))
        theme.boton_icono(boton, "reload", theme.TINTA2, theme.SUPERFICIE)
        boton.grid(row=2, column=0, sticky="w", pady=(theme.E4, 0))
        self.dlg.boton_buscar = boton                  # los tests lo pulsan

    def buscar(self, boton, respuesta) -> None:
        """Pregunta por una versión nueva y dice la respuesta debajo del botón."""
        boton.state(["disabled"])
        respuesta.configure(text="Buscando…")
        self.buscar_version(lambda texto: self.responder(boton, respuesta, texto))

    def responder(self, boton, respuesta, texto: str) -> None:
        """Pone la respuesta en su apartado, esté a la vista o escondido.

        Args:
            boton: El «Buscar actualizaciones» que se pulsó.
            respuesta: La etiqueta de debajo; si ya no existe, no se hace nada.
            texto: Lo que hay que decir.
        """
        try:
            if not respuesta.winfo_exists():
                return
        except Exception:                            # noqa: BLE001 — Tk cerrado
            return
        try:
            self.nueva = update.pending()
        except Exception:                            # noqa: BLE001
            self.nueva = None
        if self.nueva is not None:
            self.poner_chips()
            if self.clave == "actualizaciones":
                self.rehacer(texto)
            else:
                self.tirar("actualizaciones")        # se dibuja con la novedad al volver
            return
        respuesta.configure(text=texto)
        boton.state(["!disabled"])

    def forma_actualizaciones(self):
        """Devuelve qué enseñaría hoy «Actualizaciones», para saber si el dibujado ya no vale."""
        if self.nueva is not None:
            return ("nueva", self.nueva.version)
        if self.componentes is None:
            return ("esperando",)
        if self.componentes:
            return ("componentes", tuple(self.componentes))
        return ("al día",)

    def vigilante_ahora(self):
        """Devuelve qué hace este equipo al enchufar, sin caer nunca a falta de datos.

        La lectura compartida si vale; si no, el parámetro; si tampoco, se lee
        (`watch.resumen()` solo mira ficheros, como cuando la ventana principal
        lo leía al pintarse).
        """
        inst = self.leida("vigilante")
        if inst is not None:
            return inst.vigilante
        if self.vigilante_dado is not None:
            return self.vigilante_dado
        try:
            return watch.resumen()
        except Exception:                            # noqa: BLE001
            return watch.Resumen("no_disponible")

    def construir_arranque(self, panel: Panel) -> None:
        """El vigilante, o lo que hace el agente si este equipo lo tiene."""
        from . import tk_watch
        ahora = self.vigilante_ahora()
        if ahora.es_agente:
            modo = self.resultados.get("arranque")
            res = watch.pedido(ahora, modo) if isinstance(modo, str) else ahora
            tk_watch.construir_agente(panel, res)
            return
        panel.devolver(True)       # al volver, la principal relee el vigilante
        tk_watch.construir(panel)

    def construir_de(self, clave: str):
        """Devuelve la función que dibuja el apartado `clave` en un panel."""
        from . import (tk_configuracion, tk_llavero, tk_qr, tk_renombrar, tk_repair,
                       tk_versions, tk_volumen)
        return {
            "volumen": tk_volumen.construir,
            "configuracion": lambda p: tk_configuracion.construir(p, self.config),
            "llavero": lambda p: tk_llavero.construir_ajustes(p, self.raw_local),
            "versiones": lambda p: tk_versions.construir(p, self.config),
            "arranque": self.construir_arranque,
            "qr": lambda p: tk_qr.construir(p, self.raw_local),
            "renombrar": lambda p: tk_renombrar.construir(p, self.raw),
            "reparacion": lambda p: tk_repair.construir(p, self.config, self.lanzar,
                                                        self.marcadas,
                                                        compartida=self.compartida),
            "actualizaciones": self.construir_actualizaciones,
        }[clave]

    def clave_resultado(self, clave: str) -> str:
        """Bajo qué clave apunta lo suyo un apartado.

        El de actualizaciones dibuja dos pantallas distintas, y lo que
        devuelve cada una se le dice a la principal por separado.
        """
        if clave == "actualizaciones" and self.nueva is None and self.componentes:
            return "componentes"
        return clave

    # Los apartados dibujados, a la vista o escondidos.

    def ajustar(self, panel: Panel) -> None:
        """Hace sitio al apartado recién enseñado, si la ventana sigue ahí."""
        try:
            if self.dlg.winfo_exists():
                panel.ajustar()
        except Exception:                            # noqa: BLE001 — ya cerrada
            pass

    def dibujar(self, clave: str, nota: str = "") -> None:
        """Dibuja el apartado `clave` en un marco suyo, a la vista, con la nota si la hay."""
        from tkinter import ttk

        hueco = ttk.Frame(self.contenido)
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
        panel = Panel(self.dlg, marco, incrustado=True, al_terminar=self.rehacer,
                      al_cerrar=self.dlg.destroy, resultados=self.resultados,
                      clave=self.clave_resultado(clave))
        self.dlg.panel = panel                         # los tests lo miran
        self.paneles[clave] = (hueco, panel)
        if nota:
            self.con_nota.add(clave)
        try:
            self.construir_de(clave)(panel)
        except BaseException:
            self.tirar(clave)                          # ni a medias ni escondido debajo
            raise
        self.ajustar(panel)

    def tirar(self, clave: str) -> None:
        """Destruye el apartado dibujado `clave`, si lo hay."""
        entrada = self.paneles.pop(clave, None)
        self.con_nota.discard(clave)
        if clave == "actualizaciones":
            self.forma_dibujada = None
        if entrada is not None:
            entrada[0].destroy()

    def dejar(self, clave: str) -> None:
        """Deja el apartado: lo esconde y lo guarda, o lo tira si no se conserva.

        Se tira el que no se conserva (`EFIMEROS`) y el que lleva una nota: al
        volver a él, como antes, se dibuja sin ella.
        """
        hueco, panel = self.paneles[clave]
        panel.ocultado()
        if clave in EFIMEROS or clave in self.con_nota:
            self.tirar(clave)
        else:
            hueco.grid_remove()

    def rehacer(self, nota: str = "") -> None:
        """Vuelve a dibujar el apartado a la vista, con una nota encima si la hay.

        Un apartado que da algo por terminado ha podido cambiar lo que enseñan
        los demás (el config que guardó, el nombre de la unidad...), así que se
        tiran los otros ya dibujados en vez de guardar lo que enseñaban.
        """
        clave = self.clave
        if clave == "actualizaciones" and self.resultados.get("componentes") is True:
            # Ya puestos al día, lo que había que poner se ha quedado viejo.
            self.componentes = _pendientes_propios()
        for otra in [k for k in self.paneles if k != clave]:
            self.tirar(otra)
        self.tirar(clave)
        self.dibujar(clave, nota)
        self.poner_chips()

    def elegir(self, clave: str) -> None:
        """Pone a la vista el apartado `clave`: el ya dibujado, o uno nuevo la primera vez."""
        if clave not in self.entradas:
            clave = INICIAL
        antes = self.clave
        if clave == antes:
            return
        momento = f"pane-{clave}"
        perf_empezar(momento)
        self.marcar(antes, clave)
        self.clave = clave
        if antes in self.paneles:
            self.dejar(antes)
        if clave in self.paneles:
            hueco, panel = self.paneles[clave]
            hueco.grid()
            self.dlg.panel = panel
            panel.mostrado()
            self.ajustar(panel)
        else:
            self.dibujar(clave)
        perf_al_pintar(self.dlg, momento)

    def aplicar(self) -> None:
        """Deja la ventana como al abrirla: sin búsqueda, sin apartados guardados y en el inicial."""
        self.busqueda.set("")
        for clave in list(self.paneles):
            self.tirar(clave)
        self.componentes = self.lista_de_componentes()
        self.poner_chips()
        antes, self.clave = self.clave, None
        self.elegir_inicial(antes)

    def elegir_inicial(self, antes: str | None = None) -> None:
        """Elige el apartado con que se abre, restilando solo los botones que cambian."""
        clave = self.inicial if self.inicial in self.entradas else INICIAL
        self.marcar(antes, clave)
        self.clave = clave
        self.dibujar(clave)


def open_dialog(parent, config: Config, lanzar, raw_local: dict | None = None,
                buscar_version=None, inicial: str | None = None, nueva=None,
                componentes=None, vigilante=None, hallazgos=None,
                marcadas=None, compartida=None) -> dict:
    """Abre «Ajustes» y devuelve lo que han dicho sus apartados.

    La ventana lleva, para los tests y para quien la vuelva a enseñar:
    `resultados`, `panel` (el `Panel` del apartado a la vista), `paneles`
    (`{clave: (marco, Panel)}` de los apartados dibujados), `chips` (`{clave:
    (texto, tipo, icono) o None}` de los chips de la barra) y `aplicar()`, que
    la deja como una apertura nueva (`VentanaAjustes`).

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
    return VentanaAjustes(parent, config, lanzar, raw_local, buscar_version, inicial,
                          nueva, componentes, vigilante, hallazgos, marcadas,
                          compartida).abrir()
