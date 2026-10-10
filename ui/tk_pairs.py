#!/usr/bin/env python3
"""La pantalla de parejas.

Solo dibuja. Todo lo que decide y todo lo que toca el disco está en
`ui/pair_editor.py` (este dispositivo) y `ui/catalog_editor.py` (el catálogo
del remoto), y el guion es siempre el mismo: se pide un plan, se enseñan sus
consecuencias y solo si la persona confirma se ejecuta. Ninguna acción de esta
pantalla escribe nada sin haber enseñado antes lo que va a pasar.

Lo primero que se elige es QUÉ se edita: este dispositivo o el catálogo (y
por tanto TODOS los dispositivos). Es el asunto de la pantalla, así que va
arriba, y lo que hay debajo (la franja de `[defaults]`, la lista y la barra de
acciones) cambia con esa elección; mientras se edita el catálogo, un aviso
ámbar lo recuerda. Una pareja se crea o se borra en el catálogo y después cada
dispositivo elige si la usa.

La pantalla es para elegir y actuar. Los campos de la pareja elegida se cambian
en su propia ventana (`VentanaPareja`, con el mismo `EditorPareja` del alta),
que se abre con «Modificar…» o abriendo la fila y va modal sobre la pantalla:
mientras está abierta no se elige otra pareja ni se cambia de vista, y cerrarla
con algo sin guardar se pregunta antes.

Las consecuencias no se enseñan en un `messagebox`: `confirmar_plan()` es una
ventana de verdad, con las consecuencias como lista y los avisos en su recuadro
ámbar. Un `askokcancel` con seis líneas de texto corrido es justo lo que nadie
lee, y esto gobierna borrados.

Nada de lo que espera a la red congela la pantalla. Se abre con la copia local
del catálogo y lo lee del remoto en segundo plano (`ui.segundo_plano`), con el
indicador puesto y lo que toca el catálogo apagado hasta que llega. Subir un
cambio al catálogo y recorrer las carpetas del remoto van por `working()`: son
cosas que se esperan con la ventana quieta.
"""

from __future__ import annotations

from functools import partial

from common import catalog, model
from common.model import ConfigError

from . import (catalog_editor, flags_editor, icons, pair_editor, perf_al_pintar,
               perf_empezar, remote_picker, segundo_plano, theme)
from .tk import (TITLE, CeldaChip, CeldaTexto, FilaTabla, Indicador, Sondeo, Tabla,
                 bloque_aviso, cabecera, centrar, cuerpo_visible, modal, mostrar, orden_sync,
                 output_window, working)
from .tk_tabla import CeldaCasilla, TablaLienzo

VISTAS = (("Este dispositivo", "dispositivo", "dispositivo"),
          ("Catálogo", "catalogo", "nas"))
"""Lo que se puede editar en la pantalla: rótulo, valor e icono de cada botón."""

ICONO_MODO = {"bisync": "both", "up": "up", "down": "down",
              "up-mirror": "up", "down-mirror": "down"}
"""El icono del chip de cada modo: hacia dónde van los ficheros."""

TONOS_FILA = {"ok": "Ok.", "aviso": "Aviso.", "peligro": "Peligro.", "apagado": "Apagado."}
"""El tipo del chip de estado de cada tono de fila."""

ANCHO_RUTA = 240
"""El ancho mínimo de «Local ↔ remoto» en la lista, en medidas del diseño.

El resto del ancho de la pantalla también es suyo; lo que no quepa se corta con
«…» (la ventana de la pareja enseña la ruta entera), así que una ruta larga no
ensancha la pantalla.
"""

DEFAULTS_KEYS = ("remote", "device_remote", "catalog_path")
"""Los campos de texto del formulario de `[defaults]`.

Los flags tienen su propio diálogo y lo que no sale por ningún sitio
(`use_filters_file`…) se conserva tal cual, igual que en las parejas.
"""

NOTA_PEN = "Se guardará copia en sync_config.toml.bak"
"""Lo que se dice al confirmar un cambio de este dispositivo."""
NOTA_CATALOGO = "Se guardará una copia del catálogo (.bak) en el remoto"
"""Lo que se dice al confirmar un cambio del catálogo."""
ANTES = "Antes de guardar se enseña qué va a pasar."
"""La frase del pie: nada se escribe sin enseñarlo antes."""
AVISO_CAMBIADO = ("sync_config.toml ha cambiado fuera de esta pantalla: se ha vuelto a "
                  "leer. Revisa y vuelve a guardar.")
"""Lo que dice el pie cuando el config se ha editado por fuera y no se ha hecho lo pedido."""
CAMPOS_DEL_EDITOR = ("actual", "editable")
"""Lo que, al cambiar, obliga a recargar los campos de la ventana de una pareja.

El resto de `VentanaPareja.que_cargar()` solo los rodea. Con algo escrito en
ellos solo cuenta `actual`: lo escrito se guardaría encima de la pareja entera.
"""
ALCANCE_PEN = "Lo que cambies se queda en este dispositivo: el catálogo no cambia."
"""Lo que dice la ventana de una pareja de este dispositivo, bajo su título."""
ALCANCE_CATALOGO = ("Lo que cambies lo verán todos los dispositivos: cada uno tiene que "
                    "volver al catálogo para recibirlo.")
"""Lo que dice la ventana de una pareja del catálogo, bajo su título."""


class ListaParejas:
    """La lista de parejas del diseño (`PairList`): una fila por pareja, en un solo lienzo.

    Cada fila lleva la casilla de si se usa aquí, el nombre, «local ↔ remoto»,
    el modo y el estado. La casilla solo dice: la cambian «Usar aquí» y
    «Quitar…», no elegir la fila. El color de la fila es el de lo que hay que
    mirar de ella (`pair_editor.row_status`) y la elegida va en el azul suave del
    acento. Se elige con un clic o con el teclado (`tk_tabla`).

    La dibuja una `tk_tabla.TablaLienzo`: un widget para toda la lista en lugar
    de nueve por fila, que con 50 parejas eran más de 450 ventanas que Windows
    crea, coloca y pinta una a una. Por eso abrir la pantalla ya no crece con
    las parejas. La tabla compara por nombre: una fila que sigue igual no se
    toca y elegir repinta dos. Una ruta que no cabe se corta con «…»: la lista
    no ensancha la pantalla, y la ventana de la pareja la enseña entera.

    Args:
        parent: Dónde va.
        al_elegir: Lo que se llama después de elegir otra.
        al_activar: Lo que se llama al abrir la fila elegida (un doble clic
            sobre ella, o Intro); sin él no se abre nada.

    Attributes:
        marco: El lienzo de la lista: lo que se coloca.
        tabla: La `TablaLienzo` que la dibuja.
        filas: Por nombre, lo que se sabe de cada pareja: `fila` (la
            `CatalogRow`) y `tono` (`pair_editor.row_status`).
    """

    COLUMNAS = (("", 0, False), ("Pareja", 0, False), ("Local ↔ remoto", ANCHO_RUTA, True),
                ("Modo", 0, False), ("Estado", 0, False))
    """Las columnas de la tabla: la casilla, el nombre, la ruta (la que estira), el modo y el estado."""

    def __init__(self, parent, al_elegir, al_activar=None):
        self.tabla = TablaLienzo(parent, self.COLUMNAS, al_elegir=al_elegir,
                                 al_activar=al_activar, vacio="No hay ninguna pareja.")
        self.tabla.momento_elegir = "elegir-pareja"
        self.marco = self.tabla.marco
        self.filas: dict[str, dict] = {}

    @property
    def orden(self) -> list[str]:
        """Los nombres, de arriba abajo."""
        return self.tabla.orden

    @property
    def elegida(self) -> str | None:
        """El nombre de la fila elegida, o `None`."""
        return self.tabla.elegida

    @staticmethod
    def fila_tabla(fila, tono: str, nota: str, del_catalogo: bool) -> FilaTabla:
        """Dice cómo se dibuja una pareja: su `FilaTabla`.

        Args:
            fila: La `pair_editor.CatalogRow`.
            tono: Su tono y `nota` lo que dice su chip de estado
                (`pair_editor.row_status`).
            del_catalogo: Si es la vista del catálogo: el chip de estado no
                lleva el color de la fila (el espejo lo dicen la fila y el modo).
        """
        tipo = "Ok." if del_catalogo else TONOS_FILA[tono]
        espejo = fila.mode in pair_editor.MIRROR_MODES
        return FilaTabla(fila.name, (
            CeldaCasilla(fila.en_pen),
            CeldaTexto(fila.name, "Fuerte."),
            CeldaTexto(f"{fila.local} ↔ {fila.remote}", "Mono."),
            CeldaChip(fila.mode, "Peligro." if espejo else "", ICONO_MODO.get(fila.mode)),
            CeldaChip(nota, tipo)), "" if tono == "ok" else tono)

    def poner(self, filas, del_catalogo: bool = False) -> bool:
        """Pone estas filas (`pair_editor.CatalogRow`); la tabla dibuja solo las que cambian.

        Args:
            filas: Las filas, de arriba abajo.
            del_catalogo: Si es la vista del catálogo (el tono y el chip de
                estado de cada fila cambian, `pair_editor.row_status`).

        Returns:
            Si lo que pide la lista ha cambiado de tamaño: llega o se va una
            fila, o un nombre o un chip más ancho cambia una columna.
        """
        self.filas, dibujo = {}, []
        for fila in filas:
            tono, nota = pair_editor.row_status(fila, del_catalogo)
            self.filas[fila.name] = {"fila": fila, "tono": tono}
            dibujo.append(self.fila_tabla(fila, tono, nota, del_catalogo))
        return self.tabla.poner(dibujo)

    def elegir(self, name: str | None, avisar: bool = True) -> bool:
        """Elige esa pareja (o ninguna) y lo cuenta, si `avisar`; se repintan dos filas.

        Returns:
            Si la elección se ha hecho.
        """
        return self.tabla.elegir(name, avisar)

    def fila(self):
        """Devuelve la `CatalogRow` elegida, o `None`."""
        return self.filas[self.elegida]["fila"] if self.elegida in self.filas else None

    def leer(self) -> list[tuple[str, ...]]:
        """Devuelve lo que dibuja la lista, fila a fila: casilla, nombre, ruta, modo y estado.

        La casilla es «☑» o «☐» y la ruta sale como se ve, cortada si no cabe
        (`TablaLienzo.leer`).
        """
        return self.tabla.leer()


class EditorPareja:
    """Los campos de una pareja: el editor de la ventana de una pareja y el del alta.

    Solo dibuja: lo que se escribe lo decide `pair_editor` o `catalog_editor`
    con lo que devuelve `datos()`. En la ventana de una pareja va a dos
    columnas (los campos a la izquierda, el modo y sus casillas a la derecha)
    con «Avanzado» plegado; en el alta, a una columna y desplegado.

    Junto a cada campo se dice para qué es y, si hay con qué comparar, lo que
    dice el catálogo, marcado con ✎ si difiere: es lo que convierte «guardar
    aquí» en una decisión informada.

    «Avanzado» plegado no tiene widgets: el bloque (las dos cajas de patrones y la
    línea de los flags) se construye la primera vez que se despliega, y hasta
    entonces `cargar()` guarda los patrones y `datos()` los devuelve como los
    devolvería la caja.

    Args:
        parent: Dónde va.
        dlg: La ventana de la que cuelgan sus diálogos.
        sup: La superficie donde cae (`''`, el papel, o `'Card.'`).
        dos_columnas: Los campos y el modo, lado a lado.
        plegable: «Avanzado» (incluir, excluir y flags) empieza plegado y se
            construye al desplegarlo; sin ello se construye de entrada.
        al_crecer: Lo que se llama, sin argumentos, cuando el editor puede pedir
            más sitio del que tenía: al desplegar «Avanzado» y al cambiar el
            aviso del modo. Es de quien lo tiene en su ventana, que la agranda.
    """

    def __init__(self, parent, dlg, sup: str = "", dos_columnas: bool = True,
                 plegable: bool = True, al_crecer=None):
        import tkinter as tk
        from tkinter import ttk
        self.dlg, self.sup = dlg, sup
        self.al_crecer = al_crecer
        self.raw: dict = {}
        self.actual: dict = {}
        self.catalogo: dict | None = None
        self.original: str | None = None
        self.editable = True
        self.explorable = False
        self.ayuda_modo = ""
        self.ayudas: dict | None = None
        self.avanzado = {"flags": {}, "extra_flags": []}
        self.marco = ttk.Frame(parent, style=f"Plano.{sup}TFrame" if sup else "TFrame")
        self.marco.columnconfigure(0, weight=1)
        marco_sup = f"Plano.{sup}TFrame" if sup else "TFrame"
        izquierda = ttk.Frame(self.marco, style=marco_sup)
        derecha = ttk.Frame(self.marco, style=marco_sup)
        izquierda.columnconfigure(0, weight=1)
        derecha.columnconfigure(0, weight=1)
        if dos_columnas:
            self.marco.columnconfigure(1, weight=1)
            izquierda.grid(row=0, column=0, sticky="new", padx=(0, theme.E5))
            derecha.grid(row=0, column=1, sticky="new")
        else:
            izquierda.grid(row=0, column=0, sticky="ew")
            derecha.grid(row=1, column=0, sticky="ew", pady=(theme.E4, 0))

        self.campos: dict[str, tk.StringVar] = {}
        self.entradas: dict = {}
        self.pistas: dict = {}
        self.examinar: dict = {}
        for i, (clave, titulo, mono, explorar, icono) in enumerate((
                ("name", "Nombre", False, None, None),
                ("local", "Ruta local", True, self.examinar_local, "carpeta"),
                ("remote_path", "Ruta remota", True, self.examinar_remoto, "nas"),
                ("remote", "Remoto", True, None, None))):
            celda = ttk.Frame(izquierda, style=marco_sup)
            celda.grid(row=i, column=0, sticky="ew", pady=(theme.E4 if i else 0, 0))
            celda.columnconfigure(0, weight=1)
            ttk.Label(celda, text=titulo, style=f"{sup}Fuerte.TLabel").grid(
                row=0, column=0, sticky="w", pady=(0, theme.E1))
            var = tk.StringVar(celda)
            self.campos[clave] = var
            entrada = ttk.Entry(celda, textvariable=var, width=32,
                                style="Mono.TEntry" if mono else "TEntry")
            entrada.grid(row=1, column=0, sticky="ew")
            self.entradas[clave] = entrada
            if explorar is not None:
                boton = ttk.Button(celda, text="Examinar…", style="Quiet.TButton",
                                   command=explorar)
                theme.boton_icono(boton, icono, theme.ACENTO)
                boton.grid(row=1, column=1, padx=(theme.E2, 0))
                self.examinar[clave] = boton
            pista = ttk.Label(celda, style=f"{sup}Pista.TLabel",
                              wraplength=theme.medida(400), justify="left")
            pista.grid(row=2, column=0, columnspan=2, sticky="w", pady=(theme.E1, 0))
            self.pistas[clave] = pista
        self.vacio_remoto = theme.pista_campo(self.entradas["remote"],
                                              "vacío = el de [defaults]")

        ttk.Label(derecha, text="Modo", style=f"{sup}Fuerte.TLabel").grid(
            row=0, column=0, sticky="w")
        self.modo = tk.StringVar(derecha, value=model.DEFAULT_MODE)
        self.grupo_modo = theme.grupo_botones(
            derecha, [(m, m, ICONO_MODO.get(m)) for m in model.MODES], self.modo,
            orden=self.modo_cambiado, superficie=sup)
        self.grupo_modo.grid(row=1, column=0, sticky="w", pady=(theme.E2, 0))
        self.pista_modo = ttk.Label(derecha, style=f"{sup}Pista.TLabel",
                                    wraplength=theme.medida(440), justify="left")
        self.pista_modo.grid(row=2, column=0, sticky="w", pady=(theme.E2, 0))
        self.hueco_espejo = ttk.Frame(derecha, style=marco_sup)
        self.hueco_espejo.grid(row=3, column=0, sticky="ew")
        self.hueco_espejo.columnconfigure(0, weight=1)
        self.espejo = None

        self.versiones = tk.BooleanVar(derecha, value=False)
        self.casilla_versiones = ttk.Checkbutton(
            derecha, variable=self.versiones, style=f"{sup}TCheckbutton",
            text=f"Guardar en {model.VERSIONS_DIR}/ lo que se sobrescriba o se borre")
        self.casilla_versiones.grid(row=4, column=0, sticky="w", pady=(theme.E3, 0))
        self.pista_versiones = ttk.Label(derecha, style=f"{sup}Pista.TLabel",
                                         wraplength=theme.medida(440), justify="left")
        self.pista_versiones.grid(row=5, column=0, sticky="w", padx=(theme.E5, 0))
        self.vigilar = tk.BooleanVar(derecha, value=False)
        self.casilla_vigilar = ttk.Checkbutton(
            derecha, variable=self.vigilar, style=f"{sup}TCheckbutton",
            text="Sincronizar cuando cambien los ficheros locales")
        self.casilla_vigilar.grid(row=6, column=0, sticky="w", pady=(theme.E3, 0))
        self.pista_vigilar = ttk.Label(derecha, style=f"{sup}Pista.TLabel",
                                       wraplength=theme.medida(440), justify="left")
        self.pista_vigilar.grid(row=7, column=0, sticky="w", padx=(theme.E5, 0))

        # Avanzado: incluir, excluir y los flags. Casi nunca se tocan, así que en
        # la ventana de una pareja van plegados; los flags, además, en su propio diálogo,
        # porque lo que hay que ver de ellos (cuáles acaban valiendo) no cabe
        # al lado de un campo.
        abajo = ttk.Frame(self.marco, style=marco_sup)
        abajo.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(theme.E4, 0))
        abajo.columnconfigure(0, weight=1)
        self.plegado = tk.BooleanVar(abajo, value=plegable)
        self.resumen = None
        self._abajo, self._marco_sup, self._sup = abajo, marco_sup, sup
        self._plegable = plegable
        if plegable:
            ttk.Separator(abajo, style=f"{sup}TSeparator" if sup == "Card." else
                          "TSeparator").grid(row=0, column=0, sticky="ew",
                                             pady=(0, theme.E3))
            cabeza = ttk.Frame(abajo, style=marco_sup)
            cabeza.grid(row=1, column=0, sticky="ew")
            cabeza.columnconfigure(1, weight=1)
            theme.etiqueta_icono(cabeza, "flag", theme.TINTA2, "fuerte",
                                 superficie=sup).grid(row=0, column=0, sticky="nw",
                                                      padx=(0, theme.E3))
            ttk.Label(cabeza, text="Avanzado", style=f"{sup}Fuerte.TLabel").grid(
                row=0, column=1, sticky="w")
            self.resumen = ttk.Label(cabeza, style=f"{sup}Pista.TLabel")
            self.resumen.grid(row=1, column=1, sticky="w")
            self.boton_plegar = ttk.Button(cabeza, text="Mostrar", style="Quiet.TButton",
                                           command=self.plegar)
            self.boton_plegar.grid(row=0, column=2, rowspan=2, sticky="e")
        # Lo que dicen los patrones mientras no hay cajas donde leerlo.
        self.patrones: dict[str, list[str]] = {"include": [], "exclude": []}
        self.dentro = None
        self.textos: dict = {}
        self.texto_flags = None
        self.boton_flags = None
        self._espejo_puesto: tuple[str, str] | None = None
        if not plegable:
            self._construir_avanzado()

    def _construir_avanzado(self) -> None:
        """Construye el bloque de «Avanzado»: incluir, excluir y los flags.

        Se llama una sola vez: al crear el editor del alta, o al desplegar por
        primera vez el de la ventana de una pareja. Las cajas salen con lo que dicen
        `patrones` y el botón de los flags, con el estado del editor.
        """
        from tkinter import ttk
        sup, marco_sup, plegable = self._sup, self._marco_sup, self._plegable
        self.dentro = ttk.Frame(self._abajo, style=marco_sup)
        self.dentro.grid(row=2, column=0, sticky="ew",
                         pady=(theme.E3 if plegable else 0, 0))
        self.dentro.columnconfigure((0, 1), weight=1, uniform="patrones")
        for col, (clave, titulo) in enumerate((("include", "Incluir"),
                                               ("exclude", "Excluir"))):
            ttk.Label(self.dentro, text=titulo, style=f"{sup}Fuerte.TLabel").grid(
                row=0, column=col, sticky="w", padx=(theme.E4 if col else 0, 0),
                pady=(0, theme.E1))
            caja = theme.caja_texto(self.dentro, width=30, height=4)
            caja.grid(row=1, column=col, sticky="ew", padx=(theme.E4 if col else 0, 0))
            self.textos[clave] = caja
        ttk.Label(self.dentro, text="Un patrón por línea. Vacío = todo.",
                  style=f"{sup}Pista.TLabel").grid(row=2, column=0, columnspan=2,
                                                  sticky="w", pady=(theme.E1, 0))
        flags = ttk.Frame(self.dentro, style="Card.TFrame" if not sup else marco_sup,
                          padding=(theme.E3, theme.E3) if not sup else 0)
        flags.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(theme.E3, 0))
        flags.columnconfigure(1, weight=1)
        sup_flags = "Card."
        if not plegable:
            theme.etiqueta_icono(flags, "flag", theme.TINTA2, "fuerte",
                                 superficie=sup_flags).grid(row=0, column=0, sticky="nw",
                                                            padx=(0, theme.E3))
            ttk.Label(flags, text="Flags de rclone", style=f"{sup_flags}Fuerte.TLabel").grid(
                row=0, column=1, sticky="w")
        self.texto_flags = ttk.Label(flags, style=f"{sup_flags}Pista.TLabel",
                                     wraplength=theme.medida(440), justify="left")
        self.texto_flags.grid(row=1, column=1, sticky="w")
        self.boton_flags = ttk.Button(flags, text="Editar flags…", command=self.editar_flags)
        self.boton_flags.grid(row=0, column=2, rowspan=2, sticky="e", padx=(theme.E3, 0))
        self._poner_cajas()
        self.boton_flags.configure(state="normal" if self.editable else "disabled")
        self._resumir()

    def _poner_cajas(self) -> None:
        """Escribe los patrones cargados en las cajas, apagadas si no se puede editar."""
        for clave, caja in self.textos.items():
            caja.configure(state="normal")
            caja.delete("1.0", "end")
            caja.insert("1.0", "\n".join(self.patrones[clave]))
            caja.configure(state="normal" if self.editable else "disabled",
                           foreground=theme.TINTA if self.editable else theme.TINTA3)

    def _patrones(self, clave: str) -> list[str]:
        """Devuelve las líneas de una caja de patrones, tal como las daría la caja.

        Tk acaba el texto de una caja con un salto de línea que no es de nadie,
        así que una caja vacía da `['']`; con el bloque sin construir se
        reproduce, para que desplegar «Avanzado» no cambie lo que devuelve
        `datos()` (y no cuente como «cambios sin guardar»).
        """
        if clave in self.textos:
            return self.textos[clave].get("1.0", "end").splitlines()
        return ("\n".join(self.patrones[clave]) + "\n").splitlines()

    # Cargar y leer.

    def cargar(self, raw: dict, actual: dict, original: str | None,
               catalogo: dict | None = None, editable: bool = True,
               explorable: bool = False, ayuda_modo: str = "",
               ayudas: dict | None = None) -> None:
        """Pone en los campos esta pareja.

        Args:
            raw: El config del que es (el de este dispositivo o el del catálogo):
                de ahí salen el remoto por defecto y los flags de `[defaults]`.
            actual: La entrada de la pareja; `{}` para una nueva.
            original: Su nombre de ahora; `None` para una nueva.
            catalogo: La entrada del catálogo con la que comparar, o `None`.
            editable: Si se puede cambiar; si no, todo queda apagado.
            explorable: Si se puede recorrer el remoto (hay conexión: lo decide
                quien llama, con el criterio del bloque del catálogo).
            ayuda_modo: Lo que se dice debajo del modo si no es un espejo.
            ayudas: Lo que se dice debajo de cada campo, si no lo de siempre.
        """
        self.raw, self.actual, self.original = raw, dict(actual), original
        self.catalogo, self.editable, self.explorable = catalogo, editable, explorable
        self.ayuda_modo, self.ayudas = ayuda_modo, ayudas
        for clave, var in self.campos.items():
            var.set(str(actual.get(clave, "") or ""))
            self.entradas[clave].configure(state="normal" if editable else "readonly")
        self._poner_pistas()
        self.examinar["local"].configure(state="normal" if editable else "disabled")
        self.poner_explorable(explorable)
        self.modo.set(actual.get("mode", model.DEFAULT_MODE))
        for boton in self.grupo_modo.botones:
            boton.configure(state="normal" if editable else "disabled")
        self.versiones.set(bool(actual.get("versions", False)))
        self.vigilar.set(bool(actual.get("watch", False)))
        self.patrones = {clave: list(actual.get(clave, []) or []) for clave in self.patrones}
        if self.dentro is not None:
            self._poner_cajas()
            self.boton_flags.configure(state="normal" if editable else "disabled")
        self.avanzado = {"flags": dict(actual.get("flags") or {}),
                         "extra_flags": list(model._as_tuple(actual.get("extra_flags")))}
        self._resumir()
        self.modo_cambiado()

    def poner_explorable(self, explorable: bool) -> None:
        """Enciende o apaga «Examinar…» del remoto sin tocar lo escrito.

        El remoto solo se recorre con conexión; el disco de aquí, siempre.
        """
        self.explorable = explorable
        self.examinar["remote_path"].configure(
            state="normal" if self.editable and explorable else "disabled")

    def poner_alrededor(self, raw: dict, catalogo: dict | None, explorable: bool) -> None:
        """Pone al día lo que rodea a los campos sin tocar lo escrito en ellos.

        Es lo que cambia cuando llega el catálogo y el editor tiene cambios sin
        guardar sobre una pareja que sigue igual: el remoto por defecto, la
        pareja del catálogo con la que se compara (las pistas de debajo de cada
        campo y del modo) y si se puede recorrer el remoto.
        """
        self.raw, self.catalogo = raw, catalogo
        self._poner_pistas()
        self._poner_pista_modo()
        self.poner_explorable(explorable)

    def _poner_pistas(self) -> None:
        """Pone debajo de cada campo para qué es y lo que dice el catálogo."""
        por_defecto = (self.raw.get("defaults") or {}).get("remote", model.DEFAULT_REMOTE)
        ayuda = {"name": "Nombra también su carpeta en state/.",
                 "local": "Relativa a la raíz del dispositivo.",
                 "remote_path": "En el remoto, p. ej. /datos/notas.",
                 "remote": f"Vacío = el de [defaults] ({por_defecto})."}
        ayuda.update(self.ayudas or {})
        for clave in self.campos:
            self.pistas[clave].configure(text=self._pista(clave, ayuda[clave]))

    def _poner_pista_modo(self) -> None:
        """Pone lo que se dice debajo del modo, si se dice algo."""
        pista = self.ayuda_modo or self._pista("mode", "")
        self.pista_modo.configure(text=pista)
        self.pista_modo.grid() if pista else self.pista_modo.grid_remove()

    def _pista(self, clave: str, ayuda: str) -> str:
        """Lo que va debajo de un campo: para qué es y lo que dice el catálogo."""
        if self.catalogo is None:
            return ayuda
        suyo = self.catalogo.get(clave)
        difiere = str(self.actual.get(clave, "") or "") != str(suyo or "")
        return (f"{ayuda} {'✎ ' if difiere else ''}Catálogo: "
                f"{suyo if suyo not in (None, '') else '—'}")

    def _resumir(self) -> None:
        """Pone el resumen de los flags, y el de «Avanzado» si está plegado."""
        flags = flags_editor.summary(self.avanzado["flags"], self.avanzado["extra_flags"])
        # Plegado, la línea de los flags no tiene título encima: lo lleva ella.
        if self.texto_flags is not None:
            self.texto_flags.configure(text=f"Flags de rclone: {flags}"
                                       if self.resumen is not None else flags)
        if self.resumen is not None:
            patrones = sum(1 for clave in self.patrones
                           if "\n".join(self._patrones(clave)).strip())
            self.resumen.configure(text=(
                "Incluir, excluir y flags de rclone"
                + (f" · {patrones} con patrones" if patrones else "")
                + f" · {flags}"))

    def datos(self) -> dict:
        """Devuelve los campos tal como están ahora."""
        return {
            **{k: v.get() for k, v in self.campos.items()},
            "mode": self.modo.get(),
            "versions": bool(self.versiones.get()),
            "watch": bool(self.vigilar.get()),
            **{clave: self._patrones(clave) for clave in self.patrones},
            "flags": dict(self.avanzado["flags"]),
            "extra_flags": list(self.avanzado["extra_flags"]),
        }

    # Lo que pasa al tocarlo.

    def plegar(self) -> None:
        """Pliega o despliega «Avanzado»; la primera vez que se despliega, lo construye."""
        if self.plegado.get():
            if self.dentro is None:
                self._construir_avanzado()
            self.dentro.grid()
        else:
            self.dentro.grid_remove()
        self.plegado.set(not self.plegado.get())
        self.boton_plegar.configure(text="Mostrar" if self.plegado.get() else "Ocultar")
        self._resumir()
        if not self.plegado.get() and self.al_crecer is not None:
            self.al_crecer()

    def modo_cambiado(self) -> None:
        """Pone el aviso del modo y apaga las casillas que no valen en él.

        `versions` solo vale en bisync y `watch` donde el local es origen
        (`pair_editor.admite_watch`): el modelo rechaza las dos al parsear en
        los demás modos, así que la casilla se apaga y se desmarca en vez de
        dejar guardar algo que luego no arranca.
        """
        modo = self.modo.get()
        aviso = pair_editor.aviso_espejo(modo)
        otro_aviso = aviso != self._espejo_puesto
        if otro_aviso:
            if self.espejo is not None:
                self.espejo.destroy()
                self.espejo = None
            if aviso is not None:
                self.espejo = theme.aviso(self.hueco_espejo, *aviso, tono="Ambar.",
                                          ancho=380)
                self.espejo.grid(row=0, column=0, sticky="ew", pady=(theme.E3, 0))
            self._espejo_puesto = aviso
        self._poner_pista_modo()
        es_bisync = modo == "bisync"
        self.casilla_versiones.configure(
            state="normal" if es_bisync and self.editable else "disabled")
        if not es_bisync:
            self.versiones.set(False)
        self.pista_versiones.configure(text=(
            "Dentro de la pareja, en los dos lados. También el perdedor de un "
            "conflicto, en vez de dejarlo suelto." if es_bisync else
            "Solo en bisync: en copy/sync no hay dos lados que guardar."))
        vale_vigilar = pair_editor.admite_watch(modo)
        self.casilla_vigilar.configure(
            state="normal" if vale_vigilar and self.editable else "disabled")
        if not vale_vigilar:
            self.vigilar.set(False)
        self.pista_vigilar.configure(text=(
            "Solo con el agente residente. Lo del remoto espera al intervalo."
            if vale_vigilar else
            "Solo donde el origen es el dispositivo (no en down ni down-mirror)."))
        if otro_aviso and aviso is not None and self.al_crecer is not None:
            self.al_crecer()

    def examinar_local(self) -> None:
        """Deja elegir la carpeta local con el diálogo de carpetas del sistema.

        Es el del sistema y no uno propio: recorrer un disco ya lo sabe hacer
        el escritorio, y mejor. Lo que sí es asunto nuestro es lo que se
        escribe después, que tiene que ser relativo a la raíz del dispositivo.
        """
        from tkinter import filedialog, messagebox
        elegida = filedialog.askdirectory(
            parent=self.dlg, title="Carpeta del dispositivo",
            initialdir=str(model.DEVICE_ROOT), mustexist=True)
        if not elegida:
            return
        try:
            self.campos["local"].set(pair_editor.ruta_local_relativa(elegida))
        except ConfigError as e:
            messagebox.showerror(TITLE, str(e), parent=self.dlg)

    def examinar_remoto(self) -> None:
        """Deja elegir la ruta remota recorriendo el remoto."""
        remote = remote_picker.remote_de(self.raw, self.campos["remote"].get())
        elegida = explorador_remoto(self.dlg, remote, self.campos["remote_path"].get())
        if elegida is not None:
            self.campos["remote_path"].set(elegida)

    def editar_flags(self) -> None:
        """Abre el editor de flags y se queda con lo que devuelva."""
        perf_empezar("open-flags")
        nombre = self.campos["name"].get().strip() or self.original or "la pareja nueva"
        datos = flags_form(self.dlg, f"Flags de rclone de '{nombre}'",
                           "Se guardan en [pair.flags].",
                           self.avanzado["flags"], self.avanzado["extra_flags"],
                           mode_name=self.modo.get(),
                           defaults_flags=(self.raw.get("defaults") or {}).get("flags"),
                           catalogo_flags=(self.catalogo or {}).get("flags")
                           if self.catalogo else None)
        if datos is None:
            return
        self.avanzado.update(datos)
        self._resumir()


def _pide_sitio(antes: tuple[str, ...] | None, ahora: tuple[str, ...]) -> bool:
    """Dice si algún texto que se parte en líneas ha cambiado a uno que no es más corto.

    Es la forma lógica de saber si la pantalla puede necesitar más sitio sin
    pedírselo a Tk (que lo mediría con un `update_idletasks()` de toda la
    ventana): un texto que mengua no pide nada, porque el recuadro de la
    ventana solo crece.

    Args:
        antes: Los textos la última vez, o `None` si es la primera.
        ahora: Los textos de ahora, en el mismo orden.
    """
    return antes is None or any(a != b and len(b) >= len(a) for a, b in zip(antes, ahora))


class HuecoChip:
    """El sitio de un chip que solo se rehace cuando cambia lo que dice.

    Args:
        padre: Donde va el chip.
        **sitio: Cómo se coloca en la rejilla de `padre`.

    Attributes:
        widget: El chip dibujado, o `None`.
        spec: Su `(texto, tipo, icono)`, o `None` si no hay chip.
    """

    def __init__(self, padre, **sitio) -> None:
        self.padre = padre
        self.sitio = sitio
        self.widget = None
        self.spec: tuple | None = None

    def poner(self, spec: tuple | None) -> bool:
        """Pone ese chip, `(texto, tipo, icono)`, sustituyendo el de antes solo si es otro.

        Returns:
            Si ha habido que cambiarlo.
        """
        if self.spec == spec:
            return False
        if self.widget is not None:
            self.widget.destroy()
        self.widget = None if spec is None else theme.chip(self.padre, *spec)
        if self.widget is not None:
            self.widget.grid(**self.sitio)
        self.spec = spec
        return True


class VentanaPareja:
    """La ventana donde se cambia una pareja: sus campos y el botón que los guarda.

    Se abre desde la pantalla de parejas para la pareja elegida y la vista de
    entonces, y va modal sobre ella: mientras está abierta no se elige otra
    pareja ni se cambia de vista. Guarda en este dispositivo o en el catálogo
    según esa vista, siempre por el plan y su confirmación
    (`PantallaParejas.plan_de`): la pantalla la cierra cuando el plan se ha
    ejecutado, y si no se llega a guardar se queda con lo escrito. Cerrarla con
    algo sin guardar se pregunta antes.

    Una pareja que no se puede cambiar (este dispositivo no la usa, o el
    catálogo no se ha leído del remoto) se enseña igual, con todo apagado.

    El catálogo puede llegar del remoto con la ventana abierta: la pantalla la
    pone entonces al día (`poner_al_dia()`), sin perder lo escrito mientras la
    pareja siga siendo la misma.

    El `Toplevel` lleva, para los tests, `dlg.ventana` (esta ventana) y
    `dlg.editor`.

    Args:
        pantalla: La `PantallaParejas` de la que cuelga: de ella salen el
            config, el catálogo y los planes.
        nombre: La pareja que se abre.
        del_catalogo: Si se abre la del catálogo, y se guarda en él, o la de
            este dispositivo.

    Attributes:
        dlg: El `Toplevel`, retirado hasta `abrir()`.
        editor: El `EditorPareja` con los campos.
        chip: El hueco del chip de la cabecera (`HuecoChip`): a quién afecta lo
            que se guarde, o por qué no se puede cambiar.
        nota: La línea del pie: lo que pasa al guardar, o lo que ha pasado con
            la pareja mientras la ventana estaba abierta.
        boton_guardar: «Guardar aquí…» o «Guardar en el catálogo…».
        boton_cerrar: «Cancelar», o «Cerrar» si los campos no se pueden cambiar.
        base: Los argumentos con que se cargó el editor (`que_cargar()`).
        cargado: Lo que dio `editor.datos()` al cargarlo: con qué se compara
            para saber si hay algo sin guardar.
    """

    def __init__(self, pantalla, nombre: str, del_catalogo: bool) -> None:
        """Construye la ventana retirada, con la pareja ya en sus campos."""
        from tkinter import ttk

        self.pantalla, self.nombre, self.del_catalogo = pantalla, nombre, del_catalogo
        self.base: dict = {}
        self.cargado: dict = {}
        titulo = f"Modificar '{nombre}'"
        dlg = self.dlg = modal(pantalla.dlg, titulo)
        marco = cuerpo_visible(dlg, padding=(theme.E5, theme.E5, theme.E5, theme.E4))
        marco.columnconfigure(0, weight=1)

        arriba = ttk.Frame(marco)
        arriba.grid(row=0, column=0, sticky="ew")
        arriba.columnconfigure(0, weight=1)
        ttk.Label(arriba, text=titulo, style="Dialogo.TLabel").grid(row=0, column=0,
                                                                    sticky="w")
        self.chip = HuecoChip(arriba, row=0, column=1, sticky="e", padx=(theme.E3, 0))
        ttk.Label(marco, text=ALCANCE_CATALOGO if del_catalogo else ALCANCE_PEN,
                  style="Pista.TLabel", wraplength=theme.medida(640), justify="left").grid(
            row=1, column=0, sticky="w", pady=(theme.E1, 0))

        self.editor = EditorPareja(marco, dlg, al_crecer=self.crecer)
        self.editor.marco.grid(row=2, column=0, sticky="ew", pady=(theme.E4, 0))

        ttk.Separator(marco, orient="horizontal").grid(row=3, column=0, sticky="ew",
                                                       pady=(theme.E4, 0))
        pie = ttk.Frame(marco)
        pie.grid(row=4, column=0, sticky="ew", pady=(theme.E4, 0))
        pie.columnconfigure(0, weight=1)
        self.nota = ttk.Label(
            pie, text=f"{ANTES} {NOTA_CATALOGO if del_catalogo else NOTA_PEN}",
            style="Pista.TLabel", wraplength=theme.medida(520), justify="left")
        self.nota.grid(row=0, column=0, sticky="w")
        self.boton_cerrar = ttk.Button(pie, text="Cancelar", command=self.cerrar)
        self.boton_cerrar.grid(row=0, column=1, padx=(theme.E3, theme.E2))
        self.boton_guardar = ttk.Button(
            pie, text="Guardar en el catálogo…" if del_catalogo else "Guardar aquí…",
            style="Primary.TButton", command=self.guardar)
        self.boton_guardar.grid(row=0, column=2)
        dlg.protocol("WM_DELETE_WINDOW", self.cerrar)
        dlg.ventana, dlg.editor = self, self.editor      # los tests
        self.cargar()

    def abrir(self) -> None:
        """Enseña la ventana sobre la pantalla de parejas y espera a que se cierre."""
        self.dlg.perf_momento = "open-pareja"
        mostrar(self.dlg, self.pantalla.dlg)

    def que_cargar(self) -> dict:
        """Lo que `editor.cargar()` pone para esta pareja ahora, como argumentos.

        En este dispositivo se edita la suya, comparada con la del catálogo; si
        no la usa, se enseña la del catálogo sin dejar cambiarla. En el
        catálogo, la del catálogo, que solo se cambia recién leído del remoto.
        De una pareja que ya no está, `actual` sale vacío.
        """
        pantalla = self.pantalla
        lect = pantalla.lectura()
        del_cat = catalog.find_pair(pantalla.cat, self.nombre)
        if self.del_catalogo:
            actual, comparar = dict(del_cat or {}), None
            editable = del_cat is not None and lect.editable
            ayuda_modo = ("Cambiar el modo cambia la baseline: cada dispositivo la "
                          "aparta cuando vuelve al catálogo.")
            raw_de = pantalla.cat.raw if pantalla.cat else {}
            ayudas = {"name": "Nombra también su carpeta en state/ de cada dispositivo.",
                      "local": "Relativa a la raíz de cada dispositivo."}
        else:
            local = next((p for p in pantalla.raw.get("pair") or []
                          if p.get("name") == self.nombre), None)
            editable = local is not None
            actual, comparar = (dict(local), del_cat) if editable else (dict(del_cat or {}),
                                                                         None)
            ayuda_modo, raw_de, ayudas = "", pantalla.raw, None
        return {"raw": raw_de, "actual": actual, "original": self.nombre,
                "catalogo": comparar, "editable": editable, "explorable": lect.editable,
                "ayuda_modo": ayuda_modo, "ayudas": ayudas}

    def cargar(self, args: dict | None = None) -> None:
        """Pone en los campos la pareja como está ahora; lo escrito en ellos se pierde."""
        self.base = args if args is not None else self.que_cargar()
        self.editor.cargar(**self.base)
        self.cargado = self.editor.datos()
        self.pintar()

    def poner_al_dia(self) -> None:
        """Pone la ventana al día con el config y el catálogo que la pantalla acaba de leer.

        Con algo escrito, lo escrito se queda si la pareja sigue igual: se
        guarda luego entero, campo a campo, y si mientras tanto la pareja ha
        cambiado (en el catálogo, otro dispositivo; aquí, el config) conservarlo
        desharía ese cambio sin decirlo. Entonces los campos se recargan y la
        nota lo dice. Sin nada escrito se recargan cuando cambia la pareja o si
        se puede cambiar. Lo que solo rodea a los campos (el catálogo con el que
        se compara, si se puede recorrer el remoto) se pone al día sin tocarlos.
        """
        nueva, antes = self.que_cargar(), self.base
        escrito = self.hay_cambios()
        if any(nueva[k] != antes[k] for k in (("actual",) if escrito else CAMPOS_DEL_EDITOR)):
            self.cargar(nueva)
            if escrito:
                self.decir(f"'{self.nombre}' ha cambiado mientras se editaba: se ha "
                           f"cargado como está ahora y lo escrito se ha descartado.")
            else:
                self.crecer()
            return
        if nueva != antes:
            self.base = nueva
            self.editor.poner_alrededor(nueva["raw"], nueva["catalogo"], nueva["explorable"])
            self.pintar()
            self.crecer()

    def pintar(self) -> None:
        """Pone el chip de la cabecera y enciende lo que vale para la pareja como está ahora."""
        base = self.base
        if not base["actual"]:
            spec = ("Ya no existe", "Apagado.", None)
        elif self.del_catalogo:
            spec = ("Afecta a todos los dispositivos", "Aviso.", "warn")
        elif not base["editable"]:
            spec = ("Úsala aquí para cambiarla", "Apagado.", None)
        elif base["catalogo"] is not None and catalog.diff_keys(base["actual"],
                                                                base["catalogo"]):
            spec = ("Modificada aquí", "Aviso.", "warn")
        else:
            spec = None
        self.chip.poner(spec)
        quiero = "normal" if base["editable"] else "disabled"
        if str(self.boton_guardar.cget("state")) != quiero:
            self.boton_guardar.configure(state=quiero)
        PantallaParejas.poner_texto(self.boton_cerrar,
                                    "Cancelar" if self.editor.editable else "Cerrar")

    def decir(self, texto: str) -> None:
        """Pone ese texto en la nota del pie; la ventana crece si le hace falta."""
        self.nota.configure(text=texto)
        self.crecer()

    def crecer(self) -> None:
        """Agranda la ventana si lo de ahora pide más sitio, y la recoloca si ha crecido."""
        dlg = self.dlg
        if dlg.winfo_ismapped() and dlg.visor.crecer(dlg):
            centrar(dlg, self.pantalla.dlg)

    def hay_cambios(self) -> bool:
        """Si en los campos hay algo que no se ha guardado."""
        return self.editor.editable and self.editor.datos() != self.cargado

    def cerrar(self) -> None:
        """Cierra la ventana; con algo sin guardar, pregunta antes de perderlo."""
        from tkinter import messagebox

        if self.hay_cambios() and not messagebox.askokcancel(
                TITLE, f"Hay cambios sin guardar en '{self.nombre}'. ¿Descartarlos?",
                parent=self.dlg):
            return
        self.dlg.destroy()

    def guardar(self) -> None:
        """Pide el plan de guardar lo escrito, en este dispositivo o en el catálogo.

        Guarda la pareja que enseña la ventana, sea cual sea la fila elegida en
        la lista. La pantalla cierra la ventana si el plan llega a ejecutarse.
        """
        pantalla, nombre = self.pantalla, self.nombre
        if self.del_catalogo:
            pantalla.plan_de(catalog_editor.plan_catalog_save, pantalla.cat,
                             self.editor.datos(), nombre, pantalla.raw, en_catalogo=True,
                             titulo=f"Editar '{nombre}' en el catálogo")
        else:
            pantalla.plan_de(pair_editor.plan_override, pantalla.raw, pantalla.cat, nombre,
                             self.editor.datos(),
                             titulo=f"Modificar '{nombre}' en este dispositivo")


class PantallaParejas:
    """La pantalla de parejas: lo que sabe, sus widgets y lo que hace cada botón.

    Se construye retirada, con todo lo de la vista de este dispositivo; lo que
    solo hace falta para editar el catálogo (su lista, su barra de acciones, su
    aviso) se crea la primera vez que se pasa a esa vista (`montar_catalogo()`).
    `abrir()` la pinta con la copia local del catálogo, lee el remoto en segundo
    plano, la enseña y espera a que se cierre.

    Los campos de una pareja no están aquí: `modificar()` abre su ventana
    (`VentanaPareja`), modal sobre esta, y mientras está abierta la pantalla la
    pone al día en cada repintado y le pasa lo que haya que decir.

    El `Toplevel` lleva, para los tests: `dlg.pantalla` (esta pantalla),
    `dlg.lista` (siempre la que se ve), `dlg.indicador` y `dlg.sondeo`.

    Args:
        parent: La ventana de la que cuelga.
        compartida: La lectura compartida de la ventana principal
            (`ui.instantanea.Compartida`), o `None`.

    Attributes:
        dlg: El `Toplevel`, retirado hasta `abrir()`.
        lector: El `pair_editor.LecturaConfig` con que se relee el config.
        raw: El `sync_config.toml` en crudo, tal como lo enseña la pantalla.
        config: El config parseado de `raw`.
        cat: El catálogo que se enseña (`catalog.Catalogo`), o `None`.
        aviso: Por qué el catálogo es la copia local, o `None`.
        leyendo: Si se está leyendo el catálogo del remoto.
        cambiado: Si se ha cambiado el config de este dispositivo: lo que
            devuelve `abrir()`.
        ventana: La `VentanaPareja` abierta, o `None`.
        compartida: La lectura compartida si aún no se ha usado, o `None`.
        estados: El baseline y los filtros de cada pareja bisync, por nombre.
        estados_de: El config del que salen `estados`, o `None`.
        vista_puesta: Si se ve el catálogo (`True`) o este dispositivo
            (`False`); `None` antes del primer repintado.
        envolventes_antes: Los textos que se parten en líneas en el último
            repintado (`envolventes()`), o `None`.
        indicador_puesto: El `(línea, esperando, tono)` del indicador, o `None`.
        vista: La variable del interruptor: `'dispositivo'` o `'catalogo'`.
        lista: La lista que se ve; `lista_d` es la de este dispositivo y
            `lista_c` la del catálogo, `None` hasta montarla.
        botones: Los botones de acción, por su texto (o su clave).
    """

    def __init__(self, parent, compartida=None) -> None:
        """Construye la pantalla retirada, con la vista de este dispositivo."""
        import tkinter as tk
        from tkinter import ttk

        self.parent = parent
        dlg = self.dlg = modal(parent, "Parejas")
        self.lector = pair_editor.LecturaConfig()
        self.raw, self.config = self.lector.leer()
        self.cat = catalog.cached()
        self.aviso: str | None = None
        self.leyendo = False
        self.cambiado = False
        self.ventana: VentanaPareja | None = None
        self.compartida = compartida
        self.estados: dict = {}
        self.estados_de = None
        self.vista_puesta: bool | None = None
        self.envolventes_antes: tuple[str, ...] | None = None
        self.indicador_puesto: tuple | None = None
        self.sondeo = Sondeo(dlg)
        self.vista = tk.StringVar(dlg, value="dispositivo")

        marco = self.marco = cuerpo_visible(dlg, padding=(theme.E5, theme.E5, theme.E5,
                                                          theme.E4))
        marco.columnconfigure(0, weight=1)

        # De qué va esta pantalla, y de dónde sale el catálogo.
        arriba = ttk.Frame(marco)
        arriba.grid(row=0, column=0, sticky="ew")
        arriba.columnconfigure(0, weight=1)
        cabecera(arriba, "Parejas",
                 "Una pareja se crea o se borra en el catálogo; cada dispositivo elige "
                 "cuáles usa.", ancho=640).grid(row=0, column=0, sticky="nw")
        donde = ttk.Frame(arriba)
        donde.grid(row=0, column=1, sticky="ne", padx=(theme.E4, 0))
        donde.columnconfigure(0, weight=1)
        self.chip_cat = HuecoChip(donde, row=0, column=0, sticky="e")
        self.endpoint = ttk.Label(donde, style="MonoPista.TLabel")
        self.endpoint.grid(row=1, column=0, sticky="e", pady=(theme.E2, 0))
        # Lo que se enseña mientras se lee el remoto, o por qué se quedó sin él.
        self.indicador = Indicador(arriba, ancho=700)
        self.indicador.marco.grid(row=1, column=0, columnspan=2, sticky="ew",
                                  pady=(theme.E3, 0))

        # Qué se edita: este dispositivo o el catálogo. Es la pregunta de toda la
        # pantalla, así que va arriba y lo que hay debajo cambia con ella.
        que = ttk.Frame(marco)
        que.grid(row=1, column=0, sticky="w", pady=(theme.E4, 0))
        ttk.Label(que, text=theme.rotulo("Qué estás editando"), style="Rotulo.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, theme.E1))
        interruptor = theme.grupo_botones(que, VISTAS, self.vista, orden=self.cambiar_vista)
        interruptor.grid(row=1, column=0, sticky="w")

        # La franja de `[defaults]`: no es una pareja más, así que tiene su línea.
        self.fila_defaults = ttk.Frame(marco, style="Gris.TFrame",
                                       padding=(theme.E3, theme.E2))
        self.fila_defaults.grid(row=3, column=0, sticky="ew", pady=(theme.E4, 0))
        self.fila_defaults.columnconfigure(2, weight=1)
        ttk.Label(self.fila_defaults, text=theme.rotulo("[defaults]"),
                  style="Gris.Rotulo.TLabel").grid(row=0, column=0, sticky="w")
        self.origen_defaults = HuecoChip(self.fila_defaults, row=0, column=1, sticky="w",
                                         padx=(theme.E2, 0))
        self.linea_defaults = ttk.Label(self.fila_defaults, style="Gris.Pista.TLabel",
                                        wraplength=theme.medida(420), justify="left")
        self.linea_defaults.grid(row=0, column=2, sticky="w", padx=(theme.E2, 0))

        # La lista de este dispositivo, con lo que se sabe de cada pareja. La del
        # catálogo es otra y se crea al verla (`montar_catalogo`).
        self.lista_d = ListaParejas(marco, self.habilitar, self.modificar)
        self.lista_d.marco.grid(row=4, column=0, sticky="ew", pady=(theme.E4, 0))
        self.lista_c: ListaParejas | None = None
        self.lista = self.lista_d
        dlg.indicador, dlg.sondeo, dlg.lista = self.indicador, self.sondeo, self.lista
        dlg.pantalla = self                            # los tests

        # Las acciones: unas por vista, porque no tocan lo mismo.
        self.barra_d = ttk.Frame(marco)
        self.barra_d.grid(row=5, column=0, sticky="ew", pady=(theme.E4, 0))
        self.barra_d.columnconfigure(10, weight=1)
        self.barra_c = None
        self.aviso_catalogo = None

        cierre = ttk.Frame(marco)
        cierre.grid(row=6, column=0, sticky="ew", pady=(theme.E4, 0))
        cierre.columnconfigure(0, weight=1)
        ttk.Separator(cierre).grid(row=0, column=0, columnspan=3, sticky="ew",
                                   pady=(0, theme.E4))
        self.pie_nota = ttk.Label(cierre, text="", style="MonoPista.TLabel",
                                  wraplength=theme.medida(640), justify="left")
        self.pie_nota.grid(row=1, column=0, sticky="w")

        self.botones: dict[str, object] = {}

        # Los botones de este dispositivo. La franja de `[defaults]` lleva los suyos,
        # según la vista; los del catálogo se crean al verlo (`montar_catalogo`).
        for col, (texto, accion) in enumerate((
                ("Ajustes de este dispositivo…", self.defaults_del_pen),
                ("Volver a los del catálogo", self.volver_defaults)), start=3):
            b = ttk.Button(self.fila_defaults, text=texto, style="GrisQuiet.TButton",
                           command=accion)
            b.grid(row=0, column=col, padx=(theme.E1, 0))
            self.botones[texto] = b

        barra = self.barra_d
        self.boton(barra, "Usar aquí", self.usar_aqui, icono="plus", col=0)
        self.boton(barra, "Simular", self.simular, icono="eye", col=1)
        self.boton(barra, "Volver al catálogo", self.volver_al_catalogo, icono="back", col=2)
        self.boton(barra, "Quitar…", self.quitar, "Danger.TButton", "trash", col=3)
        self.boton(barra, "Modificar…", self.modificar, "Primary.TButton", "edit", col=12)

        # La flota cuelga de aquí y no de la ventana principal: es de la misma
        # familia que el catálogo (lo que comparten todos los dispositivos) y no
        # algo que haya que mirar cada vez que se sincroniza. No se apaga sin
        # conexión: sin ella la ventana sabe decir que no la hay.
        flota_btn = ttk.Button(cierre, text="Dispositivos…", style="Quiet.TButton",
                               command=self.ver_flota)
        theme.boton_icono(flota_btn, "dispositivo", theme.ACENTO)
        flota_btn.grid(row=1, column=1, padx=(theme.E3, theme.E2))
        ttk.Button(cierre, text="Cerrar", command=dlg.destroy).grid(row=1, column=2)

    def abrir(self) -> bool:
        """Pinta la pantalla, pide el catálogo al remoto, la enseña y espera a que se cierre.

        Returns:
            Si se ha cambiado el config de este dispositivo.
        """
        dlg = self.dlg
        self.pie_nota.configure(text=self.nota_inicial())
        self.leer_catalogo()
        dlg.perf_momento = "open-parejas"
        try:
            mostrar(dlg, self.parent)
        finally:
            # Las variables de Tk de la pantalla quedan en ciclos con ella: se
            # sueltan AQUÍ, en el hilo de Tk. Si las soltara el recolector desde
            # el hilo de una lectura en segundo plano, borrarlas sería hablarle a
            # Tk desde otro hilo (`aviso_fallo` hace lo mismo).
            import gc
            gc.collect()
        return self.cambiado

    def boton(self, barra, texto, accion, estilo="TButton", icono=None, col=0, clave=None):
        """Pone un botón de acción en su barra y lo apunta por su texto (o `clave`)."""
        from tkinter import ttk

        b = ttk.Button(barra, text=texto, style=estilo, command=accion)
        if icono:
            theme.boton_icono(b, icono, {"Primary.TButton": theme.SOBRE_ACENTO,
                                         "Danger.TButton": theme.PELIGRO}.get(estilo,
                                                                              theme.TINTA2))
        b.grid(row=0, column=col, padx=(0, theme.E2) if col != 12 else 0)
        self.botones[clave or texto] = b
        return b

    def lectura(self) -> catalog_editor.Lectura:
        """Dice qué se enseña del catálogo ahora y si se puede escribir en él."""
        return catalog_editor.lectura(self.cat, self.aviso, self.leyendo)

    def del_catalogo(self) -> bool:
        """Si lo que se edita es el catálogo."""
        return self.vista.get() == "catalogo"

    def nota_inicial(self) -> str:
        """Lo que dice el pie mientras no haya pasado nada."""
        return f"{ANTES} {NOTA_CATALOGO if self.del_catalogo() else NOTA_PEN}"

    def estados_actuales(self) -> dict:
        """Devuelve el baseline y los filtros de las parejas bisync, leyéndolos una sola vez.

        Al abrir se toman de la lectura compartida si vale para el config que se
        acaba de leer. Después se guardan mientras la pantalla viva y solo se
        leen las parejas que falten; si cambia el config (o se ejecuta un plan
        de este dispositivo) se vuelve a empezar, ya sin la lectura compartida.
        """
        if self.estados_de is not self.config:
            inst = self.compartida
            inst = inst.para(self.config) if inst is not None else None
            self.estados = dict(inst.estados) if inst is not None else {}
            self.estados_de = self.config
            self.compartida = None
        self.estados = pair_editor.estados_de(self.config, self.estados)
        return self.estados

    def filas(self):
        """Las filas de la vista de ahora."""
        if self.del_catalogo():
            return pair_editor.catalog_only_rows(self.raw, self.cat)
        # La ruta local como se escribe (relativa a la raíz), no adonde cae.
        locales = {p.get("name"): p.get("local") for p in self.raw.get("pair") or []}
        return [f._replace(local=locales.get(f.name) or f.local) for f in
                pair_editor.catalog_rows(self.config, self.raw, self.cat,
                                         self.estados_actuales())]

    def habilitar(self) -> None:
        """Enciende las acciones que valen para la pareja elegida."""
        for texto, vale in pair_editor.botones(self.lista.fila(), self.lectura()).items():
            b = self.botones.get(texto)
            quiero = "normal" if vale else "disabled"
            if b is not None and str(b.cget("state")) != quiero:
                b.configure(state=quiero)

    def delante(self):
        """La ventana que tiene la persona delante: la de la pareja si está abierta, o esta."""
        return self.ventana.dlg if self.ventana is not None else self.dlg

    def decir(self, nota: str) -> None:
        """Pone la nota en el pie y, si la ventana de una pareja está abierta, en el suyo.

        Con esa ventana delante, el pie de la pantalla no se ve.
        """
        self.pie_nota.configure(text=nota)
        if self.ventana is not None:
            self.ventana.decir(nota)

    def modificar(self) -> None:
        """Abre la ventana de la pareja elegida, para la vista de ahora, y espera a que se cierre."""
        fila = self.fila_elegida()
        if fila is None or self.ventana is not None:
            return
        perf_empezar("open-pareja")
        ventana = self.ventana = VentanaPareja(self, fila.name, self.del_catalogo())
        try:
            ventana.abrir()
        finally:
            self.ventana = None
            # Las variables de sus campos quedan en ciclos con la ventana: se
            # sueltan aquí, en el hilo de Tk, como al cerrar la pantalla (`abrir()`).
            import gc
            gc.collect()

    def cerrar_ventana(self) -> None:
        """Cierra la ventana de la pareja, si está abierta: lo que tenía ya se ha guardado."""
        ventana, self.ventana = self.ventana, None
        if ventana is not None:
            ventana.dlg.destroy()

    def cambiar_vista(self) -> None:
        """Pasa de este dispositivo al catálogo, o al revés."""
        self.pie_nota.configure(text=self.nota_inicial())
        self.refrescar()

    @staticmethod
    def poner_texto(etiqueta, texto: str) -> None:
        """Pone el texto de una etiqueta si es otro."""
        if str(etiqueta.cget("text")) != texto:
            etiqueta.configure(text=texto)

    def montar_catalogo(self) -> None:
        """Crea lo que solo hace falta para editar el catálogo, la primera vez que se ve.

        Su aviso ámbar, su lista, su barra de acciones y el botón de sus
        `[defaults]`. Nace a la vista: quien lo llama es `poner_vista()`.

        Tk recorre con el Tab los hijos de un marco en su orden de apilado, que
        es el de creación: hecho tarde, todo esto iría detrás de «Cerrar». Por
        eso cada pieza se pone junto a la que ocupa su sitio en la otra vista
        (`lift()`/`lower()`), y el Tab va de arriba abajo como se ve.
        """
        import tkinter as tk
        from tkinter import ttk

        marco = self.marco
        aviso = theme.aviso(
            marco, "Estás editando el catálogo",
            "Afecta a TODOS los dispositivos. Cada uno tiene que volver al catálogo "
            "para recibir el cambio.", tono="Ambar.", ancho=700)
        aviso.grid(row=2, column=0, sticky="ew", pady=(theme.E4, 0))
        aviso.lower(self.fila_defaults)
        self.aviso_catalogo = aviso
        lista_c = ListaParejas(marco, self.habilitar, self.modificar)
        lista_c.marco.grid(row=4, column=0, sticky="ew", pady=(theme.E4, 0))
        tk.Misc.lift(lista_c.marco, self.lista_d.marco)   # el `lift` de un lienzo sube elementos
        self.lista_c = lista_c
        barra = ttk.Frame(marco)
        barra.grid(row=5, column=0, sticky="ew", pady=(theme.E4, 0))
        barra.lift(self.barra_d)
        barra.columnconfigure(10, weight=1)
        self.barra_c = barra
        self.boton(barra, "Nueva pareja…", self.catalogo_nueva, "Tonal.TButton", "plus",
                   col=0)
        self.boton(barra, "Borrar del catálogo…", self.catalogo_borrar, "Danger.TButton",
                   "trash", col=1)
        self.boton(barra, "Releer", lambda: self.leer_catalogo("Catálogo releído."),
                   "Quiet.TButton", "reload", col=2)
        self.boton(barra, "Modificar…", self.modificar, "Primary.TButton", "edit", col=12,
                   clave="Modificar… del catálogo")
        b = ttk.Button(self.fila_defaults, text="Ajustes del catálogo…",
                       style="GrisQuiet.TButton", command=self.catalogo_defaults)
        b.grid(row=0, column=5, padx=(theme.E1, 0))
        self.botones["Ajustes del catálogo…"] = b

    def poner_vista(self, catalogo: bool) -> tuple[bool, ListaParejas]:
        """Enseña lo de la vista que toca y esconde lo de la otra.

        Es esconder y volver a poner: nada se destruye ni se rehace al pasar de
        una vista a la otra. La lista de la vista que se deja queda como estaba
        hasta que se vuelva a ver, y entonces `refrescar()` la pone al día.

        Returns:
            Si ha cambiado de vista, y la lista que se veía antes de llamar.
        """
        anterior = self.lista
        if self.vista_puesta == catalogo:
            return False, anterior
        if catalogo and self.lista_c is None:
            self.montar_catalogo()
        nueva = self.lista_c if catalogo else self.lista_d
        if nueva is not anterior:
            anterior.marco.grid_remove()
            nueva.marco.grid()
            self.lista = self.dlg.lista = nueva
        aviso, barra = self.aviso_catalogo, self.barra_c
        a_dispositivo = ("Ajustes de este dispositivo…", "Volver a los del catálogo")
        if catalogo:
            aviso.grid()
            self.barra_d.grid_remove()
            barra.grid()
            for texto in a_dispositivo:
                self.botones[texto].grid_remove()
            self.botones["Ajustes del catálogo…"].grid()
        else:
            if aviso is not None:
                aviso.grid_remove()
                barra.grid_remove()
                self.botones["Ajustes del catálogo…"].grid_remove()
            self.barra_d.grid()
            for texto in a_dispositivo:
                self.botones[texto].grid()
        self.vista_puesta = catalogo
        return True, anterior

    def envolventes(self) -> tuple[str, ...]:
        """Los textos de la pantalla que se parten en líneas, que son los que la hacen más alta."""
        return (str(self.indicador.texto.cget("text")), str(self.linea_defaults.cget("text")),
                str(self.pie_nota.cget("text")))

    def refrescar(self, nota: str | None = None) -> None:
        """Pone la pantalla al día con el config y el catálogo, tocando solo lo que cambia.

        Relee el config (solo se parsea si el fichero ha cambiado) y repinta la
        lista, el chip y la franja; si la ventana de una pareja está abierta, la
        pone al día también (`VentanaPareja.poner_al_dia`). La pantalla solo se
        agranda y se recoloca si ha llegado o se ha ido una fila, o algún texto
        de los que se parten en líneas es otro y no más corto.

        Args:
            nota: Lo que se pone en el pie (y en el de la ventana de la pareja,
                si está abierta); `None` lo deja como esté.
        """
        dlg = self.dlg
        self.raw, self.config = self.lector.leer()
        raw, cat = self.raw, self.cat
        lect = self.lectura()
        catalogo = self.del_catalogo()
        cambio_vista, anterior = self.poner_vista(catalogo)

        sitio = cat.endpoint if cat else catalog.endpoint(raw)
        self.chip_cat.poner((lect.chip, lect.tipo, lect.icono))
        self.poner_texto(self.endpoint, sitio)
        if self.indicador_puesto != (lect.linea, lect.leyendo, lect.tono):
            self.indicador_puesto = (lect.linea, lect.leyendo, lect.tono)
            self.indicador.poner(lect.linea, lect.leyendo, lect.tono)

        if catalogo:
            origen, difiere = "Catálogo", ()
            resumen = _resumen_defaults(cat.raw if cat else {}, ())
        else:
            origen, difiere = pair_editor.defaults_origin(raw, cat)
            resumen = _resumen_defaults(raw, difiere)
        self.origen_defaults.poner(
            (origen, "Aviso." if difiere else ("Apagado." if origen == "—" else "Ok."), None))
        self.poner_texto(self.linea_defaults, resumen)

        # Lo elegido sobrevive al repintado: el catálogo del remoto puede llegar
        # con una fila ya elegida, y perderla sería abrir luego otra.
        lista = self.lista
        elegida = anterior.elegida
        cambio = lista.poner(self.filas(), del_catalogo=catalogo)
        lista.elegir(elegida if elegida in lista.filas else
                     (lista.orden[0] if lista.orden else None), avisar=False)
        self.habilitar()
        if nota is not None:
            self.decir(nota)
        # Y lo escrito en la ventana de una pareja, también: el catálogo llega
        # mientras se teclea. Va detrás de la nota: si la pareja ha cambiado, lo
        # que dice la ventana es eso.
        if self.ventana is not None:
            self.ventana.poner_al_dia()
        # Lo que llega del remoto puede traer una explicación más larga que la
        # de la espera: entonces el recuadro crece, en vez de meterla tras una
        # barra, y la ventana se recoloca (como el asistente) para que lo que
        # ha crecido no quede por debajo del borde de la pantalla. Medirlo
        # cuesta un `update_idletasks()` de toda la ventana, así que solo se
        # hace cuando algo ha podido pedir más sitio.
        textos = self.envolventes()
        pide = cambio or cambio_vista or _pide_sitio(self.envolventes_antes, textos)
        self.envolventes_antes = textos
        if pide and dlg.winfo_ismapped() and dlg.visor.crecer(dlg):
            centrar(dlg, self.parent)

    def leer_catalogo(self, nota: str | None = None) -> None:
        """Pide el catálogo al remoto en segundo plano y repinta cuando llega.

        Mientras tanto se enseña lo que ya había (la copia local, o lo que se
        acaba de subir) con el indicador puesto y lo del catálogo apagado.
        `catalog.load()` nunca lanza; si el hilo lanzara igualmente, se queda
        la copia local y se dice por qué. Si ya hay una lectura viva del mismo
        catálogo no se lanza otra: se espera a esa.

        Args:
            nota: Lo que se pone en el pie si contesta el remoto; `None` deja
                el pie como esté.
        """
        self.leyendo = True
        self.refrescar()
        # Sin repetir: un hilo de una pantalla cerrada, o de esta misma, puede
        # seguir vivo, y dos `pull()` a la vez se pisan la copia local.
        self.sondeo.esperar(segundo_plano.lanzar_sin_repetir(
            "catalogo", self.raw, partial(catalog.load, dict(self.raw))),
            lambda encargo: self.catalogo_llegado(encargo, nota))

    def catalogo_llegado(self, encargo, nota: str | None) -> None:
        """Se queda con el catálogo que ha llegado y repinta.

        Args:
            encargo: El `segundo_plano.Encargo` de `catalog.load()`.
            nota: Lo que se pone en el pie si ha contestado el remoto.
        """
        perf_empezar("catalogo-llega")
        self.leyendo = False
        if encargo.error is not None:
            self.cat = catalog.cached()
            self.aviso = f"No se ha podido leer el catálogo: {encargo.error}"
        else:
            self.cat, self.aviso = encargo.resultado
        contesto = self.cat is not None and self.cat.editable
        self.refrescar(nota if contesto else None)
        perf_al_pintar(self.dlg, "catalogo-llega")

    def fila_elegida(self):
        """Devuelve la fila elegida, o `None` (y lo dice)."""
        from tkinter import messagebox

        fila = self.lista.fila()
        if fila is None:
            messagebox.showinfo(TITLE, "Elige antes una pareja de la lista.", parent=self.dlg)
        return fila

    def releer_config_cambiado(self) -> bool:
        """Dice si el config se ha cambiado por fuera desde que la pantalla lo enseñó.

        Si es así lo vuelve a leer, lo dice en el pie y la pantalla se queda
        como el config: quien llama no sigue con lo que iba a hacer. Si ya no
        se puede ni leer (desapareció, o ya no es TOML), lo dice y para igual.
        """
        from tkinter import messagebox

        try:
            self.lector.leer()
        except ConfigError as e:
            messagebox.showerror(TITLE, str(e), parent=self.delante())
            return True
        if not self.lector.cambio:
            return False
        self.refrescar(AVISO_CAMBIADO)
        return True

    def aplicar_plan(self, plan, en_catalogo: bool = False, titulo: str = "", base=None) -> None:
        """Confirma y ejecuta un plan; uno del catálogo no cambia este dispositivo.

        Uno del catálogo se sube por `working()`, que no se puede cortar a
        medias, y después se relee el remoto en segundo plano. Mientras llega
        se enseña lo recién subido, que `catalog.push()` deja en la copia
        local, con lo del catálogo apagado.

        Uno de este dispositivo reescribe `sync_config.toml` a partir del config
        con el que se hizo el plan (`base`): la confirmación puede tardar, y si
        mientras tanto alguien lo ha editado a mano, ejecutarlo lo pisaría. Se
        mira otra vez justo antes y, si ha cambiado, no se ejecuta nada.

        Lo que se pregunta y lo que falla se enseña sobre la ventana que haya
        delante (`delante()`). Un plan ejecutado cierra la ventana de la pareja,
        si de ella venía; uno que no llega a ejecutarse la deja con lo escrito.

        Args:
            base: El `raw` del que sale el plan, tal como lo enseñaba la pantalla.
        """
        from tkinter import messagebox

        dlg = self.delante()
        if not confirmar_plan(dlg, plan, titulo or "Confirmar el cambio",
                              NOTA_CATALOGO if en_catalogo else NOTA_PEN):
            return
        if en_catalogo:
            ok, valor = working(dlg, "Catálogo", plan.execute,
                                "Subiendo el catálogo al remoto…")
            if not ok:
                messagebox.showerror(TITLE, f"No se ha podido guardar:\n\n{valor}",
                                     parent=dlg)
                return
            self.cat = catalog.cached() or self.cat
            self.cerrar_ventana()
            self.pie_nota.configure(text="  ·  ".join(valor))
            self.leer_catalogo()
            return
        try:
            actual, _ = self.lector.leer()
        except ConfigError as e:
            messagebox.showerror(TITLE, str(e), parent=dlg)
            return
        if actual is not base:
            self.refrescar(AVISO_CAMBIADO)
            return
        try:
            hechos = plan.execute()
        except (ConfigError, OSError) as e:
            messagebox.showerror(TITLE, f"No se ha podido guardar:\n\n{e}", parent=dlg)
            return
        self.cambiado = True
        # Lo que se sabía del baseline y los filtros puede haber cambiado con el plan.
        self.estados_de, self.compartida = None, None
        self.cerrar_ventana()
        self.refrescar("  ·  ".join(hechos))

    def plan_de(self, funcion, *args, en_catalogo=False, titulo=""):
        """Pide un plan y lo aplica; si no se puede ni pedir, dice por qué."""
        from tkinter import messagebox

        if self.releer_config_cambiado():
            return
        try:
            plan = funcion(*args)
        except ConfigError as e:
            messagebox.showerror(TITLE, str(e), parent=self.delante())
            return
        self.aplicar_plan(plan, en_catalogo, titulo, base=self.raw)

    # Este dispositivo.

    def usar_aqui(self) -> None:
        """Empieza a usar aquí la pareja elegida, que ya existe en el catálogo."""
        fila = self.fila_elegida()
        if fila is not None:
            self.plan_de(pair_editor.plan_enable, self.raw, self.cat, fila.name,
                         titulo=f"Usar '{fila.name}' en este dispositivo")

    def quitar(self) -> None:
        """Quita de este dispositivo la pareja elegida, con o sin su estado."""
        fila = self.fila_elegida()
        if fila is None or not fila.en_pen:
            return
        limpiar = preguntar_limpieza(self.dlg, fila.name)
        if limpiar is not None:
            self.plan_de(partial(pair_editor.plan_remove, clean_state=limpiar),
                         self.raw, fila.name,
                         titulo=f"Quitar '{fila.name}' de este dispositivo")

    def simular(self) -> None:
        """Enseña lo que haría la pareja elegida, sin hacerlo.

        La ventana de salida va MODAL: mientras rclone mira los dos lados, esta
        pantalla no puede apartar un baseline ni reescribir el config. Al
        volver se le devuelve la captura a este diálogo, porque destruir la
        ventana hija se lleva la suya y sin esto la pantalla de parejas dejaría
        de ser modal.
        """
        from tkinter import messagebox

        dlg = self.dlg
        fila = self.fila_elegida()
        if fila is None:
            return
        try:
            args = pair_editor.simular_args(self.raw, fila.name)
        except ConfigError as e:
            messagebox.showerror(TITLE, str(e), parent=dlg)
            return
        output_window(f"Simulación de '{fila.name}'", orden_sync(args), parent=dlg,
                      subtitulo=fila.name)
        try:
            dlg.grab_set()
        except Exception:                                # noqa: BLE001
            pass
        self.pie_nota.configure(text=f"Simulación de '{fila.name}' terminada: no se ha "
                                     f"tocado nada.")

    def volver_al_catalogo(self) -> None:
        """Devuelve la pareja elegida a lo que dice el catálogo."""
        fila = self.fila_elegida()
        if fila is not None:
            self.plan_de(pair_editor.plan_revert, self.raw, self.cat, fila.name,
                         titulo=f"Devolver '{fila.name}' a lo que dice el catálogo")

    def defaults_del_pen(self) -> None:
        """Cambia los `[defaults]` de este dispositivo."""
        cat = self.cat
        datos = defaults_form(self.dlg, dict(self.raw.get("defaults") or {}),
                              cat.defaults if cat else None,
                              "Ajustes generales de este dispositivo",
                              "Valen para todas las parejas de este dispositivo.",
                              marca="el catálogo no cambia")
        if datos is not None:
            self.plan_de(pair_editor.plan_defaults, self.raw, datos,
                         titulo="Cambiar los ajustes de este dispositivo")

    def volver_defaults(self) -> None:
        """Devuelve los `[defaults]` a los del catálogo."""
        self.plan_de(pair_editor.plan_revert_defaults, self.raw, self.cat,
                     titulo="Devolver los ajustes a los del catálogo")

    # El catálogo.

    def catalogo_nueva(self) -> None:
        """Da de alta una pareja en el catálogo."""
        datos = formulario(self.dlg, (self.cat.raw if self.cat else {}), None, {},
                           titulo="Nueva pareja en el catálogo",
                           marca="Afecta a todos los dispositivos",
                           explorable=self.lectura().editable)
        if datos is not None:
            self.plan_de(catalog_editor.plan_catalog_save, self.cat, datos, None,
                         self.raw, en_catalogo=True, titulo="Dar de alta en el catálogo")

    def catalogo_borrar(self) -> None:
        """Borra del catálogo la pareja elegida."""
        fila = self.fila_elegida()
        if fila is not None:
            self.plan_de(catalog_editor.plan_catalog_remove, self.cat, fila.name,
                         self.raw, en_catalogo=True,
                         titulo=f"Borrar '{fila.name}' del catálogo")

    def catalogo_defaults(self) -> None:
        """Cambia los `[defaults]` del catálogo."""
        from tkinter import messagebox

        cat = self.cat
        if cat is None:
            messagebox.showerror(TITLE, "No hay catálogo que editar.", parent=self.dlg)
            return
        datos = defaults_form(self.dlg, cat.defaults, None,
                              "Ajustes generales del catálogo",
                              "Los heredan todos los dispositivos que no tengan los suyos.",
                              marca="afecta a TODOS los dispositivos")
        if datos is not None:
            self.plan_de(catalog_editor.plan_catalog_defaults, cat, datos, self.raw,
                         en_catalogo=True, titulo="Cambiar los ajustes del catálogo")

    def ver_flota(self) -> None:
        """Abre la ventana de los dispositivos."""
        perf_empezar("open-dispositivos")
        from . import tk_fleet
        tk_fleet.open_dialog(self.dlg, self.config, self.raw)


def open_dialog(parent, config, compartida=None) -> bool:
    """Abre la pantalla y devuelve si se ha cambiado el config de este dispositivo.

    Se pinta con la copia local del catálogo (`catalog.cached()`) y el remoto
    se lee en segundo plano; al llegar, la pantalla cambia solo lo que cambia:
    ni la lista ni la cabecera se rehacen para enseñar lo mismo. Lo que solo
    hace falta para editar el catálogo (su lista, su barra de acciones, su
    aviso) se crea la primera vez que se pasa a esa vista, y los campos de una
    pareja, en su ventana (`VentanaPareja`), cuando se pide modificarla.

    El config se relee en cada repintado (`pair_editor.LecturaConfig`: solo se
    parsea si ha cambiado) y otra vez antes de cada plan y justo antes de
    ejecutar uno de este dispositivo: si alguien lo ha editado a mano mientras
    la pantalla estaba abierta, no se hace el plan, la pantalla se vuelve a
    leer y el pie lo dice.

    La pantalla es una `PantallaParejas`, y trae `dlg.pantalla` (ella misma,
    con lo que sabe), `dlg.lista` (siempre la que se ve), `dlg.indicador` y
    `dlg.sondeo`.

    Args:
        parent: La ventana de la que cuelga.
        config: La configuración del dispositivo. La pantalla lee la de disco.
        compartida: La lectura compartida de la ventana principal
            (`ui.instantanea.Compartida`), o `None`. Al abrir, si vale para el
            config que hay en disco, de ella salen el baseline y los filtros de
            cada pareja; si no, se leen del disco una vez y se guardan mientras
            la pantalla viva.
    """
    return PantallaParejas(parent, compartida).abrir()


def _resumen_defaults(raw, difiere) -> str:
    """Devuelve la frase que resume los `[defaults]` de este dispositivo."""
    d = raw.get("defaults") or {}
    trozos = [f"remote {d.get('remote', model.DEFAULT_REMOTE)}"]
    trozos.append(f"device_remote {d['device_remote']}" if d.get("device_remote")
                  else "sin device_remote")
    flags = len(d.get("flags") or {})
    trozos.append(f"{flags} flags comunes" if flags else "sin flags comunes")
    if difiere:
        trozos.append("difiere en " + ", ".join(difiere))
    return " · ".join(trozos)


def confirmar_plan(parent, plan, titulo: str, nota: str, suelto: bool = False) -> bool:
    """Enseña lo que va a pasar y espera un sí; todavía no se ha escrito nada.

    Cada consecuencia es una línea con su punto y cada aviso su recuadro ámbar:
    lo que se está confirmando aquí puede apartar un baseline o subir un cambio
    al remoto y en un `askokcancel` todo eso queda en un párrafo que se
    despacha con un clic sin leerlo.

    Args:
        parent: De quién cuelga.
        plan: Lo que se confirma (`consequences`, `warnings`).
        titulo: El título del diálogo.
        nota: La pista del pie, junto a los botones.
        suelto: Como en `modal()`: para colgarlo de una raíz que no se enseña.

    Returns:
        `True` si la persona sigue adelante.
    """
    from tkinter import ttk

    dlg = modal(parent, titulo, suelto=suelto)
    respuesta = {"sigue": False}
    marco = cuerpo_visible(dlg, padding=(theme.E5, theme.E5, theme.E5, theme.E4))
    marco.columnconfigure(0, weight=1)

    ttk.Label(marco, text=titulo, style="Dialogo.TLabel").grid(
        row=0, column=0, sticky="w")
    ttk.Label(marco, text="Esto es lo que va a pasar. Nada se ha escrito todavía.",
              style="Pista.TLabel").grid(row=1, column=0, sticky="w", pady=(theme.E1, 0))

    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(theme.E4, theme.E1))
    tarjeta.grid(row=2, column=0, sticky="ew", pady=(theme.E4, 0))
    tarjeta.columnconfigure(1, weight=1)
    for i, texto in enumerate(plan.consequences or ["(sin cambios)"]):
        if i:
            ttk.Separator(tarjeta, orient="horizontal", style="Card.TSeparator").grid(
                row=i * 2 - 1, column=0, columnspan=2, sticky="ew")
        ttk.Label(tarjeta, text="•", style="Card.Apagado.TLabel").grid(
            row=i * 2, column=0, sticky="nw", pady=theme.E2)
        ttk.Label(tarjeta, text=texto, style="Card.TLabel", wraplength=theme.medida(470),
                  justify="left").grid(row=i * 2, column=1, sticky="w",
                                       padx=(theme.E2, 0), pady=theme.E2)

    fila = 3
    for texto in plan.warnings:
        theme.aviso(marco, *pair_editor.partir_aviso(texto), ancho=470).grid(
            row=fila, column=0, sticky="ew", pady=(theme.E3, 0))
        fila += 1

    ttk.Separator(marco, orient="horizontal").grid(row=fila, column=0, sticky="ew",
                                                   pady=(theme.E4, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=fila + 1, column=0, sticky="ew", pady=(theme.E4, 0))
    pie.columnconfigure(0, weight=1)
    ttk.Label(pie, text=nota, style="Pista.TLabel").grid(row=0, column=0, sticky="w")

    def seguir():
        """Da el sí y cierra."""
        respuesta["sigue"] = True
        dlg.destroy()

    ttk.Button(pie, text="Cancelar", command=dlg.destroy).grid(row=0, column=1,
                                                               padx=(theme.E3, theme.E2))
    ttk.Button(pie, text="Seguir adelante", style="Primary.TButton",
               command=seguir).grid(row=0, column=2)

    mostrar(dlg, parent)
    return respuesta["sigue"]


def preguntar_limpieza(parent, name: str) -> bool | None:
    """Pregunta si se aparta también el estado; `None` es cancelar."""
    import tkinter as tk
    from tkinter import ttk

    dlg = modal(parent, f"Quitar '{name}'")
    marco = cuerpo_visible(dlg, padding=(theme.E5, theme.E5, theme.E5, theme.E4))
    marco.columnconfigure(0, weight=1)
    respuesta = {"valor": None}

    ttk.Label(marco, text=f"Quitar '{name}' de este dispositivo",
              style="Dialogo.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(marco, justify="left", wraplength=theme.medida(440), style="Pista.TLabel",
              text="Los datos NO se tocan y la pareja sigue en el catálogo.").grid(row=1, column=0, sticky="w", pady=(theme.E1, 0))

    limpiar = tk.BooleanVar(value=False)
    caja = ttk.Frame(marco, style="Card.TFrame", padding=(theme.E4, theme.E3))
    caja.grid(row=2, column=0, sticky="ew", pady=(theme.E4, 0))
    ttk.Checkbutton(caja, variable=limpiar, style="Card.TCheckbutton", text=(
        "Apartar también su baseline y borrar sus filtros generados")).grid(
        row=0, column=0, sticky="w")
    ttk.Label(caja, style="Card.Pista.TLabel", wraplength=theme.medida(430), justify="left",
              text="El baseline se aparta en state/<pareja>.old-<fecha>/; no se borra.").grid(
        row=1, column=0, sticky="w", padx=(theme.E5, 0), pady=(theme.E1, 0))

    def aceptar():
        """Guarda lo marcado y cierra."""
        respuesta["valor"] = bool(limpiar.get())
        dlg.destroy()

    ttk.Separator(marco, orient="horizontal").grid(row=3, column=0, sticky="ew",
                                                   pady=(theme.E4, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=4, column=0, sticky="e", pady=(theme.E4, 0))
    ttk.Button(pie, text="Cancelar", command=dlg.destroy).grid(row=0, column=0,
                                                               padx=(0, theme.E2))
    quitar = ttk.Button(pie, text="Quitar", style="Danger.TButton", command=aceptar)
    theme.boton_icono(quitar, "trash", theme.PELIGRO, theme.SUPERFICIE)
    quitar.grid(row=0, column=1)

    mostrar(dlg, parent)
    return respuesta["valor"]


def _cabecera_form(marco, titulo: str, marca: str | None, subtitulo: str | None,
                   fila: int) -> int:
    """Pinta el título, el chip de alcance y la frase, y devuelve la fila siguiente.

    El chip es lo que contesta de un vistazo a la única pregunta que importa
    antes de tocar nada: si esto se queda aquí o lo van a ver todos los
    dispositivos.
    """
    from tkinter import ttk
    arriba = ttk.Frame(marco)
    arriba.grid(row=fila, column=0, columnspan=3, sticky="ew")
    arriba.columnconfigure(0, weight=1)
    ttk.Label(arriba, text=titulo, style="Dialogo.TLabel").grid(row=0, column=0,
                                                                sticky="w")
    if marca:
        theme.chip(arriba, marca, "Aviso.", "warn").grid(row=0, column=1, sticky="e",
                                                         padx=(theme.E3, 0))
    fila += 1
    if subtitulo:
        ttk.Label(marco, text=subtitulo, style="Pista.TLabel",
                  wraplength=theme.medida(520), justify="left").grid(
            row=fila, column=0, columnspan=3, sticky="w", pady=(theme.E1, 0))
        fila += 1
    return fila


def formulario(parent, raw: dict, original_name: str | None, actual: dict,
               catalogo: dict | None = None, titulo: str | None = None,
               subtitulo: str | None = None, marca: str | None = None,
               explorable: bool = False) -> dict | None:
    """Abre el formulario de una pareja y devuelve sus campos, o `None` si se cancela.

    Es el alta de una pareja en el catálogo: los mismos campos que la ventana
    de una pareja (`EditorPareja`), a una columna y con todo a la vista.

    Args:
        catalogo: La entrada del catálogo con la que comparar: junto a cada
            campo se enseña lo que dice el catálogo y se marca con ✎ el que
            difiere.
        explorable: Si se puede recorrer el remoto desde aquí. Lo decide quien
            abre el formulario con el mismo criterio que gobierna el catálogo:
            se acaba de leer del remoto, o sea que hay conexión. Sin ella el
            botón se apaga en vez de abrir un explorador que no va a poder
            listar nada.
    """
    from tkinter import ttk

    dlg = modal(parent, titulo or (f"Editar '{original_name}'" if original_name
                                   else "Nueva pareja"))
    marco = cuerpo_visible(dlg, padding=(theme.E5, theme.E5, theme.E5, theme.E4))
    marco.columnconfigure(0, weight=1)
    resultado: dict = {"datos": None}

    fila = _cabecera_form(marco, titulo or "Pareja", marca, subtitulo, 0)
    editor = EditorPareja(marco, dlg, dos_columnas=False, plegable=False)
    editor.marco.grid(row=fila, column=0, columnspan=3, sticky="ew", pady=(theme.E4, 0))
    editor.cargar(raw, actual, original_name, catalogo=catalogo, explorable=explorable)

    def aceptar():
        """Recoge los campos del formulario y cierra."""
        resultado["datos"] = editor.datos()
        dlg.destroy()

    ttk.Separator(marco, orient="horizontal").grid(row=fila + 1, column=0, columnspan=3,
                                                   sticky="ew", pady=(theme.E4, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=fila + 2, column=0, columnspan=3, sticky="ew", pady=(theme.E4, 0))
    pie.columnconfigure(0, weight=1)
    ttk.Label(pie, text=ANTES, style="Pista.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Button(pie, text="Cancelar", command=dlg.destroy).grid(row=0, column=1,
                                                               padx=(theme.E3, theme.E2))
    ttk.Button(pie, text="Guardar…", style="Primary.TButton",
               command=aceptar).grid(row=0, column=2)

    mostrar(dlg, parent)
    return resultado["datos"]


def explorador_remoto(parent, remote: str, inicial: str = "") -> str | None:
    """Recorre el remoto y devuelve la ruta elegida, o `None` si se cancela.

    Solo dibuja: leer una carpeta, subir, entrar y crear son de
    `ui/remote_picker.py`. Lo que hace este diálogo es que elegir una ruta deje
    de ser teclearla de memoria, que es de donde salían las parejas apuntando a
    una carpeta con una errata dentro.

    Listar y crear van por `working()`: son red, y su ventanita es modal, así
    que mientras rclone contesta no se puede pedir otra carpeta y la ruta que
    se está mirando y lo que hay dentro nunca pueden contradecirse a media
    navegación. `catalog.run` lleva tiempos de espera cortos (unos segundos
    contra un remoto caído, no los cinco minutos de fábrica).
    """
    import tkinter as tk
    from tkinter import messagebox, ttk

    dlg = modal(parent, "Carpetas del remoto")
    marco = cuerpo_visible(dlg, padding=(theme.E5, theme.E4, theme.E5, theme.E4))
    marco.columnconfigure(0, weight=1)
    estado = {"ruta": remote_picker.carpeta_de(inicial), "elegida": None}

    cabecera(marco, "Elegir una carpeta del remoto",
             "Doble clic para entrar. Se elige la carpeta que estás mirando.",
             ancho=520, estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")

    barra = ttk.Frame(marco, style="Gris.TFrame", padding=(theme.E3, theme.E2))
    barra.grid(row=1, column=0, sticky="ew", pady=(theme.E4, 0))
    barra.columnconfigure(1, weight=1)
    subir_btn = ttk.Button(barra, text="Subir", style="GrisQuiet.TButton",
                           command=lambda: ir(remote_picker.subir(estado["ruta"])))
    theme.boton_icono(subir_btn, "up", theme.TINTA2, theme.GRIS_FONDO)
    subir_btn.grid(row=0, column=0, padx=(0, theme.E3))
    ruta_lbl = ttk.Label(barra, style="Gris.Mono.TLabel", anchor="w")
    ruta_lbl.grid(row=0, column=1, sticky="ew")

    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(theme.E2, theme.E2, theme.E1, theme.E1))
    tarjeta.grid(row=2, column=0, sticky="nsew", pady=(theme.E3, 0))
    tarjeta.columnconfigure(0, weight=1)
    tarjeta.rowconfigure(0, weight=1)
    marco.rowconfigure(2, weight=1)
    # La carpeta va en la columna del árbol (#0) porque es la única de una
    # `Treeview` que lleva icono; el árbol no se despliega: se entra.
    lista = ttk.Treeview(tarjeta, columns=(), show=("tree", "headings"), height=8,
                         selectmode="browse")
    lista.heading("#0", text=theme.rotulo("Carpetas"), anchor="w")
    lista.column("#0", width=icons.px(lista, 420), anchor="w")
    carpeta = icons.get(lista, "carpeta", 16, theme.TINTA3, theme.SUPERFICIE)
    lista.grid(row=0, column=0, sticky="nsew")
    theme.marcar_lista(lista)
    scroll = ttk.Scrollbar(tarjeta, orient="vertical", command=lista.yview)
    lista.configure(yscrollcommand=scroll.set)
    scroll.grid(row=0, column=1, sticky="ns")

    nota = ttk.Label(marco, style="Pista.TLabel", wraplength=theme.medida(520),
                     justify="left")
    nota.grid(row=3, column=0, sticky="w", pady=(theme.E2, 0))

    def ir(ruta: str, sobre=None) -> bool:
        """Enseña esa carpeta; si no se puede leer, se queda donde estaba.

        Args:
            ruta: La carpeta del remoto.
            sobre: De qué ventana cuelga la espera; por defecto, este diálogo.
                Al abrir es la de quien lo llama: este todavía no se ve, y la
                ventanita de un padre oculto tampoco se vería.
        """
        ok, valor = working(sobre or dlg, "Carpetas del remoto",
                            partial(remote_picker.listar, remote, ruta),
                            f"Leyendo {remote_picker.endpoint(remote, ruta)}…")
        if not ok:
            nota.configure(text=str(valor), style="Peligro.TLabel")
            return False
        nombres = valor
        estado["ruta"] = remote_picker.normalizar(ruta)
        ruta_lbl.configure(text=f"{remote}:{estado['ruta']}")
        lista.delete(*lista.get_children())
        for nombre in nombres:
            lista.insert("", "end", iid=nombre, text=f" {nombre}", tags=("ok",),
                         **({"image": carpeta} if carpeta is not None else {}))
        subir_btn.configure(state="disabled" if estado["ruta"] == remote_picker.RAIZ
                            else "normal")
        nota.configure(text=("Aquí no hay ninguna carpeta." if not nombres else
                             f"{len(nombres)} carpeta(s)."), style="Pista.TLabel")
        return True

    def entrar(_evento=None) -> None:
        """Entra en la carpeta elegida de la lista."""
        elegido = lista.selection()
        if elegido:
            ir(remote_picker.entrar(estado["ruta"], elegido[0]))

    def nueva() -> None:
        """Crea una carpeta nueva dentro de la que se está mirando y entra en ella."""
        nombre = pedir_texto(dlg, "Nueva carpeta",
                             f"Se creará dentro de {remote}:{estado['ruta']}.")
        if nombre is None:
            return
        ok, valor = working(dlg, "Carpetas del remoto",
                            partial(remote_picker.crear, remote, estado["ruta"], nombre),
                            f"Creando la carpeta en {remote}:{estado['ruta']}…")
        if not ok:
            messagebox.showerror(TITLE, str(valor), parent=dlg)
            return
        ir(valor)

    def elegir() -> None:
        """Elige la carpeta que se está mirando y cierra."""
        estado["elegida"] = estado["ruta"]
        dlg.destroy()

    lista.bind("<Double-Button-1>", entrar)
    lista.bind("<Return>", entrar)

    acciones = ttk.Frame(marco)
    acciones.grid(row=4, column=0, sticky="ew", pady=(theme.E3, 0))
    entrar_btn = ttk.Button(acciones, text="Entrar", command=entrar)
    entrar_btn.grid(row=0, column=0, sticky="w")
    nueva_btn = ttk.Button(acciones, text="Nueva carpeta…", style="Quiet.TButton",
                           command=nueva)
    theme.boton_icono(nueva_btn, "plus", theme.ACENTO, theme.PAPEL)
    nueva_btn.grid(row=0, column=1, sticky="w", padx=(theme.E2, 0))

    ttk.Separator(marco, orient="horizontal").grid(row=5, column=0, sticky="ew",
                                                   pady=(theme.E4, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=6, column=0, sticky="ew", pady=(theme.E3, 0))
    pie.columnconfigure(0, weight=1)
    ttk.Label(pie, text="Se escribe en «Ruta remota»; nada se sincroniza todavía.",
              style="Pista.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Button(pie, text="Cancelar", command=dlg.destroy).grid(row=0, column=1,
                                                               padx=(theme.E3, theme.E2))
    ttk.Button(pie, text="Elegir esta carpeta", style="Primary.TButton",
               command=elegir).grid(row=0, column=2)

    # Si la carpeta de la que se venía ya no existe —la pareja apuntaba a una
    # ruta borrada, o con una errata— se empieza por la raíz en vez de abrir un
    # diálogo vacío del que no se puede salir a ningún sitio.
    if not ir(estado["ruta"], parent) and estado["ruta"] != remote_picker.RAIZ:
        ir(remote_picker.RAIZ, parent)
    mostrar(dlg, parent)
    return estado["elegida"]


def pedir_texto(parent, titulo: str, explicacion: str) -> str | None:
    """Pide una línea de texto; `None` si se cancela o se deja en blanco."""
    import tkinter as tk
    from tkinter import ttk

    dlg = modal(parent, titulo)
    marco = cuerpo_visible(dlg, padding=(theme.E5, theme.E5, theme.E5, theme.E4))
    marco.columnconfigure(0, weight=1)
    resultado: dict = {"texto": None}

    ttk.Label(marco, text=titulo, style="Dialogo.TLabel").grid(row=0, column=0,
                                                               sticky="w")
    ttk.Label(marco, text=explicacion, style="Pista.TLabel", justify="left",
              wraplength=theme.medida(400)).grid(row=1, column=0, sticky="w",
                                                 pady=(theme.E1, 0))
    var = tk.StringVar()
    entrada = ttk.Entry(marco, textvariable=var, width=34, style="Mono.TEntry")
    entrada.grid(row=2, column=0, sticky="w", pady=(theme.E4, 0))

    def aceptar() -> None:
        """Guarda el texto escrito y cierra; en blanco no hace nada."""
        if not var.get().strip():
            return
        resultado["texto"] = var.get().strip()
        dlg.destroy()

    entrada.bind("<Return>", lambda _e: aceptar())
    ttk.Separator(marco, orient="horizontal").grid(row=3, column=0, sticky="ew",
                                                   pady=(theme.E4, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=4, column=0, sticky="e", pady=(theme.E4, 0))
    ttk.Button(pie, text="Cancelar", command=dlg.destroy).grid(row=0, column=0,
                                                               padx=(0, theme.E2))
    ttk.Button(pie, text="Crear", style="Primary.TButton",
               command=aceptar).grid(row=0, column=1)

    mostrar(dlg, parent)
    return resultado["texto"]


def defaults_form(parent, actual: dict, catalogo: dict | None,
                  titulo: str, subtitulo: str, marca: str | None = None) -> dict | None:
    """Abre el formulario de `[defaults]` y devuelve el bloque entero, o `None`.

    Lo que no se edita aquí (`use_filters_file`…) viaja tal cual: este
    formulario devuelve los `[defaults]` completos y no un parche.
    """
    import tkinter as tk
    from tkinter import ttk

    dlg = modal(parent, titulo)
    marco = cuerpo_visible(dlg, padding=(theme.E5, theme.E5, theme.E5, theme.E4))
    marco.columnconfigure(0, weight=1)
    resultado: dict = {"datos": None}

    fila = _cabecera_form(marco, titulo, marca, subtitulo, 0)

    def pista(clave: str, ayuda: str, separador: str = " ") -> str:
        """Lo que va debajo de un campo: para qué es y lo que dice el catálogo."""
        if catalogo is None:
            return ayuda
        suyo = catalogo.get(clave)
        if isinstance(suyo, list):
            suyo = ", ".join(suyo)
        mio = actual.get(clave)
        mio = ", ".join(mio) if isinstance(mio, list) else mio
        dif = "✎ " if str(mio or "") != str(suyo or "") else ""
        return f"{ayuda}{separador}{dif}Catálogo: {suyo if suyo not in (None, '') else '—'}"

    campos: dict[str, tk.StringVar] = {}
    for clave, titulo_campo, ayuda in (
            ("remote", "Remoto", "El nombre del remote en rclone.conf."),
            ("device_remote", "Remote del dispositivo",
             "Vacío = desactivado; cambiarlo invalida los baselines."),
            ("catalog_path", "Ruta del catálogo",
             f"Vacío = {catalog.DEFAULT_CATALOG_PATH}.")):
        celda = ttk.Frame(marco)
        celda.grid(row=fila, column=0, sticky="ew", pady=(theme.E3, 0))
        celda.columnconfigure(0, weight=1)
        ttk.Label(celda, text=titulo_campo, style="Fuerte.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, theme.E1))
        var = tk.StringVar(value=str(actual.get(clave, "") or ""))
        campos[clave] = var
        ttk.Entry(celda, textvariable=var, width=48, style="Mono.TEntry").grid(
            row=1, column=0, sticky="ew")
        ttk.Label(celda, text=pista(clave, ayuda), style="Pista.TLabel",
                  wraplength=theme.medida(620), justify="left").grid(
            row=2, column=0, sticky="w", pady=(theme.E1, 0))
        fila += 1

    guardar_logs = tk.BooleanVar(value=bool(actual.get("keep_logs", False)))
    ttk.Checkbutton(marco, variable=guardar_logs,
                    text="Guardar también los logs de las pasadas que van bien").grid(
        row=fila, column=0, sticky="w", pady=(theme.E4, 0))
    fila += 1

    patrones = ttk.Frame(marco)
    patrones.grid(row=fila, column=0, sticky="ew", pady=(theme.E4, 0))
    patrones.columnconfigure((0, 1), weight=1, uniform="patrones")
    textos: dict[str, tk.Text] = {}
    for col, (clave, titulo_campo) in enumerate((("include", "Incluir en todas"),
                                                 ("exclude", "Excluir en todas"))):
        ttk.Label(patrones, text=titulo_campo, style="Fuerte.TLabel").grid(
            row=0, column=col, sticky="w", pady=(0, theme.E1),
            padx=(0, theme.E4) if col == 0 else 0)
        caja = theme.caja_texto(patrones, width=28, height=4)
        caja.insert("1.0", "\n".join(actual.get(clave, []) or []))
        caja.grid(row=1, column=col, sticky="ew", padx=(0, theme.E4) if col == 0 else 0)
        textos[clave] = caja
        ttk.Label(patrones, style="Pista.TLabel", wraplength=theme.medida(290),
                  justify="left",
                  text=pista(clave, "Un patrón por línea. Vale para todas las parejas.",
                             "\n")).grid(row=2, column=col, sticky="nw",
                                         pady=(theme.E1, 0))
    fila += 1

    avanzado = {"flags": dict(actual.get("flags") or {}),
                "extra_flags": list(model._as_tuple(actual.get("extra_flags")))}

    caja_flags = ttk.Frame(marco, style="Card.TFrame", padding=(theme.E4, theme.E3))
    caja_flags.grid(row=fila, column=0, sticky="ew", pady=(theme.E4, 0))
    caja_flags.columnconfigure(1, weight=1)
    img = icons.get(caja_flags, "flag", 18, theme.TINTA2, theme.SUPERFICIE)
    marca_flags = ttk.Label(caja_flags, style="Card.TLabel")
    if img is not None:
        marca_flags.configure(image=img)
        marca_flags.image = img
    marca_flags.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, theme.E3))
    ttk.Label(caja_flags, text="Flags de rclone comunes",
              style="Card.Fuerte.TLabel").grid(row=0, column=1, sticky="w")
    resumen = ttk.Label(caja_flags, style="Card.Pista.TLabel", wraplength=theme.medida(420),
                        justify="left")
    resumen.grid(row=1, column=1, sticky="w")

    def editar_flags():
        """Abre el editor de flags comunes y guarda lo que devuelva."""
        datos = flags_form(dlg, "Flags de rclone comunes",
                           "Se guardan en [defaults.flags] y valen para todas las "
                           "parejas que no lleven el suyo.",
                           avanzado["flags"], avanzado["extra_flags"],
                           mode_name=None,
                           defaults_flags=None,
                           catalogo_flags=(catalogo or {}).get("flags") if catalogo else None)
        if datos is None:
            return
        avanzado.update(datos)
        resumen.configure(text=flags_editor.summary(avanzado["flags"],
                                                    avanzado["extra_flags"]))

    resumen.configure(text=flags_editor.summary(avanzado["flags"],
                                                avanzado["extra_flags"]))
    ttk.Button(caja_flags, text="Editar flags…", command=editar_flags).grid(
        row=0, column=2, rowspan=2, sticky="e")
    fila += 1

    theme.aviso(marco, "Ojo con «Remote del dispositivo» y «Remoto»",
                "Alimentan los extremos de todas las parejas: cambiarlos aparta "
                "sus baselines.", ancho=560).grid(
        row=fila, column=0, sticky="ew", pady=(theme.E4, 0))
    fila += 1

    def aceptar():
        """Compone el bloque de `[defaults]` con lo escrito y cierra."""
        datos = {k: v for k, v in actual.items() if k not in DEFAULTS_KEYS
                 and k not in ("keep_logs", "include", "exclude",
                               "flags", "extra_flags")}
        if avanzado["flags"]:
            datos["flags"] = dict(avanzado["flags"])
        if avanzado["extra_flags"]:
            datos["extra_flags"] = list(avanzado["extra_flags"])
        for clave, var in campos.items():
            valor = var.get().strip()
            if valor:
                datos[clave] = valor
        if guardar_logs.get():
            datos["keep_logs"] = True
        for clave, caja in textos.items():
            patrones = [x.strip() for x in caja.get("1.0", "end").splitlines() if x.strip()]
            if patrones:
                datos[clave] = patrones
        resultado["datos"] = datos
        dlg.destroy()

    ttk.Separator(marco, orient="horizontal").grid(row=fila, column=0, sticky="ew",
                                                   pady=(theme.E4, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=fila + 1, column=0, sticky="ew", pady=(theme.E4, 0))
    pie.columnconfigure(0, weight=1)
    ttk.Label(pie, text="Antes de guardar se enseña qué va a pasar.",
              style="Pista.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Button(pie, text="Cancelar", command=dlg.destroy).grid(row=0, column=1,
                                                               padx=(theme.E3, theme.E2))
    ttk.Button(pie, text="Guardar…", style="Primary.TButton",
               command=aceptar).grid(row=0, column=2)

    mostrar(dlg, parent)
    return resultado["datos"]


def flags_form(parent, titulo: str, subtitulo: str, flags: dict, extra: list,
               mode_name: str | None, defaults_flags: dict | None,
               catalogo_flags: dict | None = None) -> dict | None:
    """Abre el editor de flags y devuelve lo editado, o `None` si se cancela.

    Es `{"flags", "extra_flags"}`. Se edita como texto TOML y no con una fila
    por flag a propósito: los flags de rclone son cientos, cambian con cada
    versión y ninguna lista que pusiéramos aquí estaría al día. Lo que sí se
    puede dar es lo que no se ve escribiéndolos en el TOML (qué queda valiendo
    al fundir base, modo, `[defaults]` y pareja) y eso es la tabla de la
    derecha.

    El diálogo NO se cierra si lo escrito no vale y el motivo se enseña DENTRO,
    en un recuadro rojo bajo el texto y no en un `messagebox`: el aviso tiene
    que poder leerse mientras se corrige lo escrito. Cerrar y perderlo, o peor,
    guardar solo lo que se entendió, es exactamente lo que no puede pasar con
    un fichero que gobierna borrados.
    """
    from tkinter import ttk

    dlg = modal(parent, titulo)
    marco = cuerpo_visible(dlg, padding=(theme.E5, theme.E4, theme.E5, theme.E4))
    marco.columnconfigure(1, weight=1)
    resultado: dict = {"datos": None}

    ttk.Label(marco, text=titulo, style="Dialogo.TLabel").grid(
        row=0, column=0, columnspan=2, sticky="w")
    ttk.Label(marco, text=subtitulo, style="Pista.TLabel", wraplength=theme.medida(600),
              justify="left").grid(row=1, column=0, columnspan=2, sticky="w",
                                   pady=(theme.E1, 0))

    # Lo que se escribe.
    izquierda = ttk.Frame(marco)
    izquierda.grid(row=2, column=0, sticky="nsew", pady=(theme.E4, 0))

    ttk.Label(izquierda, text=theme.rotulo("Lo que escribes"),
              style="Rotulo.TLabel").grid(row=0, column=0, sticky="w", pady=(0, theme.E2))
    caja = theme.caja_texto(izquierda, width=40, height=8)
    caja.insert("1.0", flags_editor.dump(flags))
    caja.grid(row=1, column=0, sticky="ew")
    ttk.Label(izquierda, style="Pista.TLabel", wraplength=theme.medida(330), justify="left",
              text=("Tal cual se escriben en el TOML: transfers = 4, "
                    'conflict-resolve = "newer", checksum = true. Sin los guiones '
                    "de delante.")).grid(row=2, column=0, sticky="w", pady=(theme.E2, 0))

    problema = ttk.Frame(izquierda)      # el recuadro rojo, vacío mientras todo vale
    problema.grid(row=3, column=0, sticky="ew", pady=(theme.E2, 0))
    problema.columnconfigure(0, weight=1)

    ttk.Label(izquierda, text=theme.rotulo("Argumentos extra"),
              style="Rotulo.TLabel").grid(row=4, column=0, sticky="w", pady=(theme.E4, theme.E2))
    caja_extra = theme.caja_texto(izquierda, width=40, height=3)
    caja_extra.insert("1.0", flags_editor.dump_extra(extra))
    caja_extra.grid(row=5, column=0, sticky="ew")
    ttk.Label(izquierda, style="Pista.TLabel", wraplength=theme.medida(330), justify="left",
              text=("Van a la línea de comandos sin tocar: --bwlimit y 8M son DOS "
                    "líneas.")).grid(row=6, column=0, sticky="w", pady=(theme.E2, 0))

    if catalogo_flags is not None:
        ttk.Label(izquierda, style="MonoPista.TLabel", wraplength=theme.medida(330),
                  justify="left",
                  text="Catálogo: " + (flags_editor.dump(catalogo_flags).replace(
                      "\n", "  ·  ") or "ninguno")).grid(row=7, column=0,
                                                         sticky="w", pady=(theme.E2, 0))

    # Lo que acabaría recibiendo rclone.
    derecha = ttk.Frame(marco)
    derecha.grid(row=2, column=1, sticky="nsew", pady=(theme.E4, 0), padx=(theme.E4, 0))
    derecha.columnconfigure(0, weight=1)
    derecha.rowconfigure(1, weight=1)

    titulo_tabla = ttk.Frame(derecha)
    titulo_tabla.grid(row=0, column=0, sticky="ew", pady=(0, theme.E2))
    titulo_tabla.columnconfigure(0, weight=1)
    ttk.Label(titulo_tabla, text=theme.rotulo("Lo que acabaría recibiendo rclone"),
              style="Rotulo.TLabel").grid(row=0, column=0, sticky="w")

    tabla = Tabla(derecha, [("Flag", 260, True), ("Sale de", 120, False)], alto_fila=30,
                  vacio="Cuando lo escrito valga, aquí se verá el efecto.")
    tabla.grid(row=1, column=0, sticky="new")
    dlg.tabla = tabla                                  # los tests la miran

    ttk.Label(derecha, style="Pista.TLabel", wraplength=theme.medida(380), justify="left",
              text="Se funden en este orden: siempre → modo → [defaults] → esta "
                   "pareja.").grid(row=2, column=0, sticky="w", pady=(theme.E2, 0))

    recuadro: dict = {}          # el aviso rojo: se hace la primera vez que hace falta

    def avisar(error: ConfigError | None) -> None:
        """Enseña el motivo en el recuadro rojo, o lo esconde si no hay.

        El recuadro se hace la primera vez que lo escrito no vale y desde
        entonces solo cambia su texto y se quita o se pone en la rejilla: ni se
        destruye ni se rehace con cada error.
        """
        if error is None:
            if "marco" in recuadro:
                recuadro["marco"].grid_remove()
            return
        titulo_error, cuerpo = flags_editor.titulo_error(error), str(error)
        if "marco" not in recuadro:
            marco_aviso = theme.aviso(problema, titulo_error, cuerpo or " ", tono="Rojo.",
                                      ancho=300)
            recuadro.update(marco=marco_aviso, titulo=marco_aviso.titulo,
                            cuerpo=marco_aviso.cuerpo)
        else:
            recuadro["titulo"].configure(text=titulo_error)
        recuadro["cuerpo"].configure(text=cuerpo)
        recuadro["marco"].grid(row=0, column=0, sticky="ew")

    def leer() -> dict | None:
        """Devuelve lo escrito, ya validado; `None` si no vale (y ya se ha avisado)."""
        try:
            datos = {"flags": flags_editor.parse(caja.get("1.0", "end")),
                     "extra_flags": flags_editor.parse_extra(caja_extra.get("1.0", "end"))}
        except ConfigError as e:
            avisar(e)
            return None
        avisar(None)
        return datos

    def repasar():
        """Repinta la tabla con lo que acabaría recibiendo rclone."""
        datos = leer()
        if datos is None:
            if not tabla.orden:
                tabla.poner([])               # al abrir: que no quede una tabla muda
            return
        filas = []
        for i, fila in enumerate(flags_editor.effective(mode_name, defaults_flags,
                                                        datos["flags"])):
            propio = fila.origen == "esta pareja"
            filas.append(FilaTabla(str(i), (
                CeldaTexto(fila.flag, "Mono."),
                CeldaChip(fila.origen, "Acento." if propio else "",
                          "edit" if propio else None)), "propio" if propio else ""))
        for j, arg in enumerate(datos["extra_flags"]):
            filas.append(FilaTabla(f"extra{j}", (CeldaTexto(arg, "Mono."),
                                                 CeldaChip("extra"))))
        tabla.poner(filas)

    def aceptar():
        """Valida lo escrito y cierra; si no vale, el diálogo se queda abierto."""
        datos = leer()
        if datos is None:
            return                       # el diálogo se queda abierto, con el texto
        resultado["datos"] = datos
        dlg.destroy()

    ver = ttk.Button(titulo_tabla, text="Ver el efecto", style="Quiet.TButton",
                     command=repasar)
    theme.boton_icono(ver, "eye", theme.ACENTO, theme.PAPEL, 14)
    ver.grid(row=0, column=1, sticky="e")

    ttk.Separator(marco, orient="horizontal").grid(row=3, column=0, columnspan=2,
                                                   sticky="ew", pady=(theme.E4, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(theme.E4, 0))
    pie.columnconfigure(0, weight=1)
    ttk.Label(pie, text="Si algo no vale, el diálogo no se cierra: lo escrito se "
                        "queda.", style="Pista.TLabel").grid(row=0, column=0,
                                                             sticky="w")
    ttk.Button(pie, text="Cancelar", command=dlg.destroy).grid(row=0, column=1,
                                                               padx=(theme.E3, theme.E2))
    ttk.Button(pie, text="Aceptar", style="Primary.TButton",
               command=aceptar).grid(row=0, column=2)

    repasar()
    dlg.perf_momento = "open-flags"
    mostrar(dlg, parent)
    return resultado["datos"]
