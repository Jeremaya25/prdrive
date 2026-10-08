#!/usr/bin/env python3
"""La pantalla de parejas.

Solo dibuja. Todo lo que decide y todo lo que toca el disco está en
`ui/pair_editor.py` (este dispositivo) y `ui/catalog_editor.py` (el catálogo
del remoto), y el guion es siempre el mismo: se pide un plan, se enseñan sus
consecuencias y solo si la persona confirma se ejecuta. Ninguna acción de esta
pantalla escribe nada sin haber enseñado antes lo que va a pasar.

Lo primero que se elige es QUÉ se edita: este dispositivo o el catálogo (y
por tanto TODOS los dispositivos). Es el asunto de la pantalla, así que va
arriba, y lo que hay debajo (la franja de `[defaults]`, la lista, el editor y
la barra de acciones) cambia con esa elección; mientras se edita el catálogo,
un aviso ámbar lo recuerda. Una pareja se crea o se borra en el catálogo y
después cada dispositivo elige si la usa.

La pareja elegida se edita en la propia pantalla (`EditorPareja`), no en un
formulario aparte: lo que se va a guardar está a la vista junto a la lista, y
pasar a otra pareja con algo sin guardar se pregunta antes.

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

from common import catalog, config_file, model
from common.model import ConfigError

from . import (catalog_editor, flags_editor, icons, pair_editor,
               remote_picker, segundo_plano, theme)
from .tk import (TITLE, CeldaChip, CeldaTexto, FilaTabla, Indicador, Sondeo, Tabla,
                 bloque_aviso, cabecera, centrar, cuerpo_visible, modal, mostrar, orden_sync,
                 output_window, separador_fila, working)

VISTAS = (("Este dispositivo", "dispositivo", "dispositivo"),
          ("Catálogo", "catalogo", "nas"))
"""Lo que se puede editar en la pantalla: rótulo, valor e icono de cada botón."""

ICONO_MODO = {"bisync": "both", "up": "up", "down": "down",
              "up-mirror": "up", "down-mirror": "down"}
"""El icono del chip de cada modo: hacia dónde van los ficheros."""

TONOS_FILA = {"ok": ("Card.", "Ok."), "aviso": ("NotaAmbar.", "Aviso."),
              "peligro": ("Rojo.", "Peligro."), "apagado": ("Card.", "Apagado.")}
"""La superficie de cada tono de fila y el tipo de su chip de estado."""

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


class ListaParejas:
    """La lista de parejas del diseño (`PairList`): una fila por pareja.

    No es una `ttk.Treeview` porque cada fila lleva chips (el modo y el estado)
    y una lista de Tk no sabe pintar nada dentro de una celda. Son etiquetas en
    una rejilla: la casilla de si se usa aquí, el nombre, «local ↔ remoto»,
    el modo y el estado. El color de la fila es el de lo que hay que mirar de
    ella (`pair_editor.row_status`) y la elegida va en el azul suave del
    acento. Se elige con un clic o con las flechas.

    Args:
        parent: Dónde va.
        puede_dejar: Se pregunta antes de cambiar de fila; si dice que no
            (quedan cambios sin guardar y la persona no los quiere perder), la
            elección no se hace.
        al_elegir: Lo que se llama después de elegir otra.
    """

    COLUMNAS = 5

    def __init__(self, parent, puede_dejar, al_elegir):
        from tkinter import ttk
        self.puede_dejar, self.al_elegir = puede_dejar, al_elegir
        self.marco = ttk.Frame(parent, style="Card.TFrame", takefocus=True,
                               padding=icons.px(parent, 1))   # su borde
        self.marco.columnconfigure(2, weight=1)
        self.filas: dict[str, dict] = {}
        self.orden: list[str] = []
        self.elegida: str | None = None
        cabeza = ttk.Frame(self.marco, style="Plano.TFrame")
        cabeza.grid(row=0, column=0, columnspan=self.COLUMNAS, sticky="nsew")
        cabeza.lower()
        self.cabecera = [cabeza]
        for col, texto in ((1, "Pareja"), (2, "Local ↔ remoto"), (3, "Modo"),
                           (4, "Estado")):
            rotulo = ttk.Label(self.marco, text=theme.rotulo(texto), style="Rotulo.TLabel")
            rotulo.grid(row=0, column=col, sticky="w", padx=self._lados(col),
                        pady=theme.E1)
            self.cabecera.append(rotulo)
        self.marco.rowconfigure(0, minsize=icons.px(self.marco, 28))
        self.marco.bind("<Up>", lambda _e: self._mover(-1))
        self.marco.bind("<Down>", lambda _e: self._mover(1))

    @staticmethod
    def _lados(col: int):
        """El hueco a los lados de una celda: el de la rejilla y el borde de la fila."""
        return (theme.E3 if col == 0 else theme.E2,
                theme.E3 if col == ListaParejas.COLUMNAS - 1 else 0)

    def poner(self, filas, del_catalogo: bool = False) -> None:
        """Pinta estas filas (`pair_editor.CatalogRow`) en lugar de las de antes."""
        from tkinter import ttk
        for hijo in self.marco.winfo_children():
            if hijo not in self.cabecera:
                hijo.destroy()
        for fila_tk in range(1, self.marco.grid_size()[1]):
            self.marco.rowconfigure(fila_tk, minsize=0)   # las de antes no ocupan
        self.filas, self.orden = {}, []
        ttk.Separator(self.marco, style="Card.TSeparator").grid(
            row=1, column=0, columnspan=self.COLUMNAS, sticky="ew")
        fila_tk = 2
        for i, fila in enumerate(filas):
            if i:
                separador_fila(self.marco, fila_tk, self.COLUMNAS)
                fila_tk += 1
            tono, nota = pair_editor.row_status(fila, del_catalogo)
            sup, tipo = TONOS_FILA[tono]
            if del_catalogo:
                tipo = "Ok."                      # el espejo lo dicen la fila y el modo
            fondo = ttk.Frame(self.marco, style=f"Plano.{sup}TFrame")
            fondo.grid(row=fila_tk, column=0, columnspan=self.COLUMNAS, sticky="nsew")
            fondo.lower()
            casilla = ttk.Label(self.marco)
            img = icons.casilla(self.marco, "marcada" if fila.en_pen else "vacia",
                                margen=0)
            if img is not None:
                casilla.configure(image=img)
                casilla.image = img
            apagada = tono == "apagado"
            nombre = ttk.Label(self.marco, text=fila.name)
            ruta = ttk.Label(self.marco, text=f"{fila.local} ↔ {fila.remote}")
            espejo = fila.mode in pair_editor.MIRROR_MODES
            modo = theme.chip(self.marco, fila.mode, "Peligro." if espejo else "",
                              ICONO_MODO.get(fila.mode))
            estado = theme.chip(self.marco, nota, tipo)
            celdas = (casilla, nombre, ruta, modo, estado)
            for col, celda in enumerate(celdas):
                celda.grid(row=fila_tk, column=col, sticky="w", padx=self._lados(col),
                           pady=theme.E2)
                celda.bind("<Button-1>", partial(self._clic, fila.name))
            fondo.bind("<Button-1>", partial(self._clic, fila.name))
            self.marco.rowconfigure(fila_tk, minsize=icons.px(self.marco, 36))
            self.filas[fila.name] = {"fila": fila, "sup": sup, "apagada": apagada,
                                     "fondo": fondo, "casilla": casilla,
                                     "nombre": nombre, "ruta": ruta}
            self.orden.append(fila.name)
            fila_tk += 1
        if not filas:
            ttk.Label(self.marco, text="No hay ninguna pareja.",
                      style="Card.Pista.TLabel").grid(
                row=2, column=0, columnspan=self.COLUMNAS, pady=theme.E3)
        if self.elegida not in self.filas:
            self.elegida = None
        self._pintar()

    def _pintar(self) -> None:
        """Pone a cada fila su superficie; la elegida, la del acento."""
        for name, f in self.filas.items():
            sup = "NotaAzul." if name == self.elegida else f["sup"]
            f["fondo"].configure(style=f"Plano.{sup}TFrame")
            f["casilla"].configure(style=f"{sup}TLabel")
            if f["apagada"]:
                f["nombre"].configure(style=f"{sup}Pista.TLabel")
                f["ruta"].configure(style=f"{sup}MonoPista.TLabel")
            else:
                f["nombre"].configure(style=f"{sup}Fuerte.TLabel")
                f["ruta"].configure(style=f"{sup}Mono.TLabel")

    def _clic(self, name: str, _evento=None) -> None:
        """Elige la fila pulsada y le da el foco a la lista, para las flechas."""
        self.marco.focus_set()
        self.elegir(name)

    def _mover(self, paso: int) -> str:
        """Elige la fila de arriba o la de abajo."""
        if self.orden:
            i = self.orden.index(self.elegida) + paso if self.elegida in self.orden else 0
            self.elegir(self.orden[max(0, min(len(self.orden) - 1, i))])
        return "break"

    def elegir(self, name: str | None, avisar: bool = True) -> bool:
        """Elige esa pareja (o ninguna) y lo cuenta, si `avisar`.

        Returns:
            Si la elección se ha hecho: `al_elegir` puede negarse.
        """
        if name is not None and name not in self.filas:
            name = None
        if name == self.elegida:
            return True
        if avisar and not self.puede_dejar():
            return False
        self.elegida = name
        self._pintar()
        if avisar:
            self.al_elegir()
        return True

    def fila(self):
        """Devuelve la `CatalogRow` elegida, o `None`."""
        return self.filas[self.elegida]["fila"] if self.elegida in self.filas else None


class EditorPareja:
    """Los campos de una pareja: el editor de la pantalla y el del alta.

    Solo dibuja: lo que se escribe lo decide `pair_editor` o `catalog_editor`
    con lo que devuelve `datos()`. En la pantalla de parejas va en una tarjeta
    a dos columnas (los campos a la izquierda, el modo y sus casillas a la
    derecha) con «Avanzado» plegado; en el alta, a una columna y desplegado.

    Junto a cada campo se dice para qué es y, si hay con qué comparar, lo que
    dice el catálogo, marcado con ✎ si difiere: es lo que convierte «guardar
    aquí» en una decisión informada.

    Args:
        parent: Dónde va.
        dlg: La ventana de la que cuelgan sus diálogos.
        sup: La superficie donde cae (`'Card.'` o `''`).
        dos_columnas: Los campos y el modo, lado a lado.
        plegable: «Avanzado» (incluir, excluir y flags) empieza plegado.
    """

    def __init__(self, parent, dlg, sup: str = "Card.", dos_columnas: bool = True,
                 plegable: bool = True):
        import tkinter as tk
        from tkinter import ttk
        self.dlg, self.sup = dlg, sup
        self.raw: dict = {}
        self.actual: dict = {}
        self.catalogo: dict | None = None
        self.original: str | None = None
        self.editable = True
        self.explorable = False
        self.ayuda_modo = ""
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

        # Avanzado: incluir, excluir y los flags. Casi nunca se tocan, así que
        # en la pantalla van plegados; los flags, además, en su propio diálogo,
        # porque lo que hay que ver de ellos (cuáles acaban valiendo) no cabe
        # al lado de un campo.
        abajo = ttk.Frame(self.marco, style=marco_sup)
        abajo.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(theme.E4, 0))
        abajo.columnconfigure(0, weight=1)
        self.plegado = tk.BooleanVar(abajo, value=plegable)
        self.resumen = None
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
        self.dentro = ttk.Frame(abajo, style=marco_sup)
        self.dentro.grid(row=2, column=0, sticky="ew",
                         pady=(theme.E3 if plegable else 0, 0))
        self.dentro.columnconfigure((0, 1), weight=1, uniform="patrones")
        self.textos: dict = {}
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
        if plegable:
            self.dentro.grid_remove()

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
        self.ayuda_modo = ayuda_modo
        por_defecto = (raw.get("defaults") or {}).get("remote", model.DEFAULT_REMOTE)
        ayuda = {"name": "Nombra también su carpeta en state/.",
                 "local": "Relativa a la raíz del dispositivo.",
                 "remote_path": "En el remoto, p. ej. /datos/notas.",
                 "remote": f"Vacío = el de [defaults] ({por_defecto})."}
        ayuda.update(ayudas or {})
        for clave, var in self.campos.items():
            var.set(str(actual.get(clave, "") or ""))
            self.pistas[clave].configure(text=self._pista(clave, ayuda[clave]))
            self.entradas[clave].configure(state="normal" if editable else "readonly")
        self.examinar["local"].configure(state="normal" if editable else "disabled")
        self.poner_explorable(explorable)
        self.modo.set(actual.get("mode", model.DEFAULT_MODE))
        for boton in self.grupo_modo.botones:
            boton.configure(state="normal" if editable else "disabled")
        self.versiones.set(bool(actual.get("versions", False)))
        self.vigilar.set(bool(actual.get("watch", False)))
        for clave, caja in self.textos.items():
            caja.configure(state="normal")
            caja.delete("1.0", "end")
            caja.insert("1.0", "\n".join(actual.get(clave, []) or []))
            caja.configure(state="normal" if editable else "disabled",
                           foreground=theme.TINTA if editable else theme.TINTA3)
        self.avanzado = {"flags": dict(actual.get("flags") or {}),
                         "extra_flags": list(model._as_tuple(actual.get("extra_flags")))}
        self.boton_flags.configure(state="normal" if editable else "disabled")
        self._resumir()
        self.modo_cambiado()

    def poner_explorable(self, explorable: bool) -> None:
        """Enciende o apaga «Examinar…» del remoto sin tocar lo escrito.

        El remoto solo se recorre con conexión; el disco de aquí, siempre. Es lo
        que cambia cuando llega el catálogo y el editor tiene cambios sin
        guardar, que no se recarga.
        """
        self.explorable = explorable
        self.examinar["remote_path"].configure(
            state="normal" if self.editable and explorable else "disabled")

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
        self.texto_flags.configure(text=f"Flags de rclone: {flags}"
                                   if self.resumen is not None else flags)
        if self.resumen is not None:
            patrones = sum(1 for caja in self.textos.values()
                           if caja.get("1.0", "end").strip())
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
            **{k: caja.get("1.0", "end").splitlines() for k, caja in self.textos.items()},
            "flags": dict(self.avanzado["flags"]),
            "extra_flags": list(self.avanzado["extra_flags"]),
        }

    # Lo que pasa al tocarlo.

    def plegar(self) -> None:
        """Pliega o despliega «Avanzado»."""
        if self.plegado.get():
            self.dentro.grid()
        else:
            self.dentro.grid_remove()
        self.plegado.set(not self.plegado.get())
        self.boton_plegar.configure(text="Mostrar" if self.plegado.get() else "Ocultar")
        self._resumir()

    def modo_cambiado(self) -> None:
        """Pone el aviso del modo y apaga las casillas que no valen en él.

        `versions` solo vale en bisync y `watch` donde el local es origen
        (`pair_editor.admite_watch`): el modelo rechaza las dos al parsear en
        los demás modos, así que la casilla se apaga y se desmarca en vez de
        dejar guardar algo que luego no arranca.
        """
        modo = self.modo.get()
        if self.espejo is not None:
            self.espejo.destroy()
            self.espejo = None
        aviso = pair_editor.aviso_espejo(modo)
        if aviso is not None:
            self.espejo = theme.aviso(self.hueco_espejo, *aviso, tono="Ambar.", ancho=380)
            self.espejo.grid(row=0, column=0, sticky="ew", pady=(theme.E3, 0))
        pista = self.ayuda_modo or self._pista("mode", "")
        self.pista_modo.configure(text=pista)
        self.pista_modo.grid() if pista else self.pista_modo.grid_remove()
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


def open_dialog(parent, config) -> bool:
    """Abre la pantalla y devuelve si se ha cambiado el config de este dispositivo.

    Se pinta con la copia local del catálogo (`catalog.cached()`) y el remoto
    se lee en segundo plano; al llegar, la pantalla se repinta con él.
    """
    import tkinter as tk
    from tkinter import messagebox, ttk

    dlg = modal(parent, "Parejas")
    raw = config_file.load_raw()
    estado = {"raw": raw, "config": config, "cat": catalog.cached(), "aviso": None,
              "leyendo": False, "cambiado": False, "cargado": None}
    sondeo = Sondeo(dlg)
    vista = tk.StringVar(dlg, value="dispositivo")

    marco = cuerpo_visible(dlg, padding=(theme.E5, theme.E5, theme.E5, theme.E4))
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
    chip_cat = {"widget": None}
    endpoint = ttk.Label(donde, style="MonoPista.TLabel")
    endpoint.grid(row=1, column=0, sticky="e", pady=(theme.E2, 0))
    # Lo que se enseña mientras se lee el remoto, o por qué se quedó sin él.
    indicador = Indicador(arriba, ancho=700)
    indicador.marco.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(theme.E3, 0))

    # Qué se edita: este dispositivo o el catálogo. Es la pregunta de toda la
    # pantalla, así que va arriba y lo que hay debajo cambia con ella.
    que = ttk.Frame(marco)
    que.grid(row=1, column=0, sticky="w", pady=(theme.E4, 0))
    ttk.Label(que, text=theme.rotulo("Qué estás editando"), style="Rotulo.TLabel").grid(
        row=0, column=0, sticky="w", pady=(0, theme.E1))
    interruptor = theme.grupo_botones(que, VISTAS, vista, orden=lambda: cambiar_vista())
    interruptor.grid(row=1, column=0, sticky="w")
    aviso_catalogo = theme.aviso(
        marco, "Estás editando el catálogo",
        "Afecta a TODOS los dispositivos. Cada uno tiene que volver al catálogo "
        "para recibir el cambio.", tono="Ambar.", ancho=700)
    aviso_catalogo.grid(row=2, column=0, sticky="ew", pady=(theme.E4, 0))

    # La franja de `[defaults]`: no es una pareja más, así que tiene su línea.
    fila_defaults = ttk.Frame(marco, style="Gris.TFrame", padding=(theme.E3, theme.E2))
    fila_defaults.grid(row=3, column=0, sticky="ew", pady=(theme.E4, 0))
    fila_defaults.columnconfigure(2, weight=1)
    ttk.Label(fila_defaults, text=theme.rotulo("[defaults]"),
              style="Gris.Rotulo.TLabel").grid(row=0, column=0, sticky="w")
    origen_defaults = {"widget": None}
    linea_defaults = ttk.Label(fila_defaults, style="Gris.Pista.TLabel",
                               wraplength=theme.medida(420), justify="left")
    linea_defaults.grid(row=0, column=2, sticky="w", padx=(theme.E2, 0))

    # La lista, con lo que se sabe de cada pareja.
    lista = ListaParejas(marco, lambda: seguir_sin_guardar(), lambda: cargar_editor())
    lista.marco.grid(row=4, column=0, sticky="ew", pady=(theme.E4, 0))
    dlg.indicador, dlg.sondeo, dlg.lista = indicador, sondeo, lista   # los tests

    # La pareja elegida, editable aquí mismo.
    titulo_eleg = ttk.Frame(marco)
    titulo_eleg.grid(row=5, column=0, sticky="ew", pady=(theme.E4, theme.E2))
    titulo_eleg.columnconfigure(0, weight=1)
    rotulo_eleg = ttk.Label(titulo_eleg, style="Rotulo.TLabel")
    rotulo_eleg.grid(row=0, column=0, sticky="w")
    chip_eleg = {"widget": None}
    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(theme.E5, theme.E4))
    tarjeta.grid(row=6, column=0, sticky="ew")
    tarjeta.columnconfigure(0, weight=1)
    editor = EditorPareja(tarjeta, dlg)
    editor.marco.grid(row=0, column=0, sticky="ew")
    dlg.editor = editor

    # Las acciones: unas por vista, porque no tocan lo mismo.
    acciones = {}
    for nombre in ("dispositivo", "catalogo"):
        barra = ttk.Frame(marco)
        barra.grid(row=7, column=0, sticky="ew", pady=(theme.E4, 0))
        barra.columnconfigure(10, weight=1)
        acciones[nombre] = barra

    cierre = ttk.Frame(marco)
    cierre.grid(row=8, column=0, sticky="ew", pady=(theme.E4, 0))
    cierre.columnconfigure(0, weight=1)
    ttk.Separator(cierre).grid(row=0, column=0, columnspan=3, sticky="ew",
                               pady=(0, theme.E4))
    pie_nota = ttk.Label(cierre, text="", style="MonoPista.TLabel",
                         wraplength=theme.medida(640), justify="left")
    pie_nota.grid(row=1, column=0, sticky="w")

    botones: dict[str, object] = {}

    def boton(barra, texto, accion, estilo="TButton", icono=None, col=0, clave=None):
        """Pone un botón de acción en su barra y lo apunta por su texto (o `clave`)."""
        b = ttk.Button(acciones[barra], text=texto, style=estilo, command=accion)
        if icono:
            theme.boton_icono(b, icono, {"Primary.TButton": theme.SOBRE_ACENTO,
                                         "Danger.TButton": theme.PELIGRO}.get(estilo,
                                                                              theme.TINTA2))
        b.grid(row=0, column=col, padx=(0, theme.E2) if col != 12 else 0)
        botones[clave or texto] = b
        return b

    def lectura() -> catalog_editor.Lectura:
        """Dice qué se enseña del catálogo ahora y si se puede escribir en él."""
        return catalog_editor.lectura(estado["cat"], estado["aviso"], estado["leyendo"])

    def del_catalogo() -> bool:
        """Si lo que se edita es el catálogo."""
        return vista.get() == "catalogo"

    def nota_inicial() -> str:
        """Lo que dice el pie mientras no haya pasado nada."""
        return f"{ANTES} {NOTA_CATALOGO if del_catalogo() else NOTA_PEN}"

    def filas():
        """Las filas de la vista de ahora."""
        if del_catalogo():
            return pair_editor.catalog_only_rows(estado["raw"], estado["cat"])
        # La ruta local como se escribe (relativa a la raíz), no adonde cae.
        locales = {p.get("name"): p.get("local") for p in estado["raw"].get("pair") or []}
        return [f._replace(local=locales.get(f.name) or f.local) for f in
                pair_editor.catalog_rows(estado["config"], estado["raw"], estado["cat"])]

    def entrada_de(name: str | None) -> tuple[dict, dict | None]:
        """La pareja que se edita y aquella con la que se compara.

        En este dispositivo se edita la suya, comparada con la del catálogo; si
        no la usa, se enseña la del catálogo. En el catálogo, la del catálogo.
        """
        del_cat = catalog.find_pair(estado["cat"], name) if name else None
        if del_catalogo():
            return dict(del_cat or {}), None
        local = next((p for p in estado["raw"].get("pair") or []
                      if p.get("name") == name), None)
        if local is None:
            return dict(del_cat or {}), None
        return dict(local), del_cat

    def cargar_editor() -> None:
        """Pone en el editor la pareja elegida, con lo que se puede hacer con ella."""
        fila = lista.fila()
        actual, comparar = entrada_de(fila.name if fila else None)
        lect = lectura()
        if del_catalogo():
            editable = fila is not None and lect.editable
            ayuda_modo = ("Cambiar el modo cambia la baseline: cada dispositivo la "
                          "aparta cuando vuelve al catálogo.")
            raw_de = estado["cat"].raw if estado["cat"] else {}
            ayudas = {"name": "Nombra también su carpeta en state/ de cada dispositivo.",
                      "local": "Relativa a la raíz de cada dispositivo."}
        else:
            editable = fila is not None and fila.en_pen
            ayuda_modo, raw_de, ayudas = "", estado["raw"], None
        editor.cargar(raw_de, actual, fila.name if fila else None, catalogo=comparar,
                      editable=editable, explorable=lect.editable,
                      ayuda_modo=ayuda_modo, ayudas=ayudas)
        estado["cargado"] = editor.datos()
        pintar_eleccion()

    def pintar_eleccion() -> None:
        """Pone el rótulo y el chip de la pareja elegida y enciende lo que vale para ella.

        Es lo de `cargar_editor()` que no son los campos: se repinta también
        cuando el editor conserva lo que se ha escrito en él.
        """
        fila = lista.fila()
        rotulo_eleg.configure(text=theme.rotulo(
            f"Pareja elegida · {fila.name}" if fila else "Ninguna pareja elegida"))
        if chip_eleg["widget"] is not None:
            chip_eleg["widget"].destroy()
            chip_eleg["widget"] = None
        if fila is not None and not del_catalogo():
            tono, nota = pair_editor.row_status(fila)
            if not fila.en_pen:
                chip_eleg["widget"] = theme.chip(titulo_eleg, "Úsala aquí para cambiarla",
                                                 "Apagado.")
            elif fila.difiere:
                chip_eleg["widget"] = theme.chip(titulo_eleg, "Modificada aquí", "Aviso.",
                                                 "warn")
            if chip_eleg["widget"] is not None:
                chip_eleg["widget"].grid(row=0, column=1, sticky="e")
        habilitar()

    def habilitar() -> None:
        """Enciende las acciones que valen para la pareja elegida."""
        fila = lista.fila()
        lect = lectura()
        en_pen = fila is not None and fila.en_pen

        def poner(texto, vale):
            botones[texto].configure(state="normal" if vale else "disabled")
        poner("Usar aquí", fila is not None and not en_pen)
        for texto in ("Simular", "Quitar…", "Descartar", "Guardar aquí…"):
            poner(texto, en_pen)
        poner("Volver al catálogo", en_pen and bool(fila.difiere))
        poner("Ajustes del catálogo…", lect.editable)
        poner("Nueva pareja…", lect.editable)
        for texto in ("Borrar del catálogo…", "Guardar en el catálogo…"):
            poner(texto, lect.editable and fila is not None)
        botones["Descartar del catálogo"].configure(state="normal" if fila else "disabled")
        botones["Releer"].configure(state="disabled" if lect.leyendo else "normal")

    def hay_cambios() -> bool:
        """Si el editor tiene algo que no se ha guardado."""
        return (estado["cargado"] is not None and editor.editable
                and editor.datos() != estado["cargado"])

    def seguir_sin_guardar() -> bool:
        """Pregunta antes de perder lo que se ha cambiado en el editor."""
        if not hay_cambios():
            return True
        return messagebox.askokcancel(
            TITLE, f"Hay cambios sin guardar en '{editor.original}'. "
                   f"¿Descartarlos?", parent=dlg)

    def cambiar_vista() -> None:
        """Pasa de este dispositivo al catálogo, o al revés."""
        if not seguir_sin_guardar():
            vista.set("catalogo" if vista.get() == "dispositivo" else "dispositivo")
            return
        estado["cargado"] = None              # lo escrito se ha descartado
        pie_nota.configure(text=nota_inicial())
        refrescar()

    def refrescar(nota: str | None = None) -> None:
        """Relee el config y repinta la lista, el chip, la franja y el editor.

        Args:
            nota: Lo que se pone en el pie; `None` lo deja como esté.
        """
        estado["raw"] = config_file.load_raw()
        estado["config"] = model.parse_config(estado["raw"], equipo=model.es_equipo())
        cat = estado["cat"]
        lect = lectura()
        catalogo = del_catalogo()

        sitio = cat.endpoint if cat else catalog.endpoint(estado["raw"])
        if chip_cat["widget"] is not None:
            chip_cat["widget"].destroy()
        chip_cat["widget"] = theme.chip(donde, lect.chip, lect.tipo, lect.icono)
        chip_cat["widget"].grid(row=0, column=0, sticky="e")
        endpoint.configure(text=sitio)
        indicador.poner(lect.linea, lect.leyendo, lect.tono)

        if catalogo:
            aviso_catalogo.grid()
            acciones["dispositivo"].grid_remove()
            acciones["catalogo"].grid()
        else:
            aviso_catalogo.grid_remove()
            acciones["catalogo"].grid_remove()
            acciones["dispositivo"].grid()
        for texto in ("Ajustes de este dispositivo…", "Volver a los del catálogo"):
            botones[texto].grid() if not catalogo else botones[texto].grid_remove()
        (botones["Ajustes del catálogo…"].grid() if catalogo
         else botones["Ajustes del catálogo…"].grid_remove())

        if catalogo:
            origen, difiere = "Catálogo", ()
            resumen = _resumen_defaults(cat.raw if cat else {}, ())
        else:
            origen, difiere = pair_editor.defaults_origin(estado["raw"], cat)
            resumen = _resumen_defaults(estado["raw"], difiere)
        if origen_defaults["widget"] is not None:
            origen_defaults["widget"].destroy()
        origen_defaults["widget"] = theme.chip(
            fila_defaults, origen,
            "Aviso." if difiere else ("Apagado." if origen == "—" else "Ok."))
        origen_defaults["widget"].grid(row=0, column=1, sticky="w", padx=(theme.E2, 0))
        linea_defaults.configure(text=resumen)

        # Lo elegido sobrevive al repintado: el catálogo del remoto puede llegar
        # con una fila ya elegida, y perderla sería editar luego otra.
        elegida = lista.elegida
        escrito = hay_cambios() and editor.original == elegida
        lista.poner(filas(), del_catalogo=catalogo)
        lista.elegir(elegida if elegida in lista.filas else
                     (lista.orden[0] if lista.orden else None), avisar=False)
        # Y lo escrito en el editor, también: el catálogo llega mientras se
        # teclea, y recargar el editor lo borraba y daba lo borrado por guardado.
        if escrito and lista.elegida == elegida:
            editor.poner_explorable(lect.editable)
            pintar_eleccion()
        else:
            cargar_editor()
        if nota is not None:
            pie_nota.configure(text=nota)
        # Lo que llega del remoto puede traer una explicación más larga que la
        # de la espera: entonces el recuadro crece, en vez de meterla tras una
        # barra, y la ventana se recoloca (como el asistente) para que lo que
        # ha crecido no quede por debajo del borde de la pantalla.
        if dlg.winfo_ismapped() and dlg.visor.crecer(dlg):
            centrar(dlg, parent)

    def leer_catalogo(nota: str | None = None) -> None:
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
        estado["leyendo"] = True
        refrescar()

        def llegado(encargo) -> None:
            """Se queda con lo que ha llegado y repinta."""
            estado["leyendo"] = False
            if encargo.error is not None:
                estado["cat"] = catalog.cached()
                estado["aviso"] = f"No se ha podido leer el catálogo: {encargo.error}"
            else:
                estado["cat"], estado["aviso"] = encargo.resultado
            contesto = estado["cat"] is not None and estado["cat"].editable
            refrescar(nota if contesto else None)

        # Sin repetir: un hilo de una pantalla cerrada, o de esta misma, puede
        # seguir vivo, y dos `pull()` a la vez se pisan la copia local.
        sondeo.esperar(segundo_plano.lanzar_sin_repetir(
            "catalogo", estado["raw"], partial(catalog.load, dict(estado["raw"]))),
            llegado)

    def fila_elegida():
        """Devuelve la fila elegida, o `None` (y lo dice)."""
        fila = lista.fila()
        if fila is None:
            messagebox.showinfo(TITLE, "Elige antes una pareja de la lista.", parent=dlg)
        return fila

    def aplicar(plan, en_catalogo: bool = False, titulo: str = "") -> None:
        """Confirma y ejecuta un plan; uno del catálogo no cambia este dispositivo.

        Uno del catálogo se sube por `working()`, que no se puede cortar a
        medias, y después se relee el remoto en segundo plano. Mientras llega
        se enseña lo recién subido, que `catalog.push()` deja en la copia
        local, con lo del catálogo apagado.
        """
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
            estado["cat"] = catalog.cached() or estado["cat"]
            estado["cargado"] = None              # lo editado ya está subido
            pie_nota.configure(text="  ·  ".join(valor))
            leer_catalogo()
            return
        try:
            hechos = plan.execute()
        except (ConfigError, OSError) as e:
            messagebox.showerror(TITLE, f"No se ha podido guardar:\n\n{e}", parent=dlg)
            return
        estado["cambiado"] = True
        estado["cargado"] = None
        refrescar("  ·  ".join(hechos))

    def plan_de(funcion, *args, en_catalogo=False, titulo=""):
        """Pide un plan y lo aplica; si no se puede ni pedir, dice por qué."""
        try:
            plan = funcion(*args)
        except ConfigError as e:
            messagebox.showerror(TITLE, str(e), parent=dlg)
            return
        aplicar(plan, en_catalogo, titulo)

    def descartar() -> None:
        """Devuelve el editor a lo que hay guardado."""
        cargar_editor()

    # Este dispositivo.

    def usar_aqui() -> None:
        """Empieza a usar aquí la pareja elegida, que ya existe en el catálogo."""
        fila = fila_elegida()
        if fila is not None:
            plan_de(pair_editor.plan_enable, estado["raw"], estado["cat"], fila.name,
                    titulo=f"Usar '{fila.name}' en este dispositivo")

    def quitar() -> None:
        """Quita de este dispositivo la pareja elegida, con o sin su estado."""
        fila = fila_elegida()
        if fila is None or not fila.en_pen:
            return
        limpiar = preguntar_limpieza(dlg, fila.name)
        if limpiar is not None:
            plan_de(partial(pair_editor.plan_remove, clean_state=limpiar),
                    estado["raw"], fila.name,
                    titulo=f"Quitar '{fila.name}' de este dispositivo")

    def simular() -> None:
        """Enseña lo que haría la pareja elegida, sin hacerlo.

        La ventana de salida va MODAL: mientras rclone mira los dos lados, esta
        pantalla no puede apartar un baseline ni reescribir el config. Al
        volver se le devuelve la captura a este diálogo, porque destruir la
        ventana hija se lleva la suya y sin esto la pantalla de parejas dejaría
        de ser modal.
        """
        fila = fila_elegida()
        if fila is None:
            return
        try:
            args = pair_editor.simular_args(estado["raw"], fila.name)
        except ConfigError as e:
            messagebox.showerror(TITLE, str(e), parent=dlg)
            return
        output_window(f"Simulación de '{fila.name}'", orden_sync(args), parent=dlg,
                      subtitulo=fila.name)
        try:
            dlg.grab_set()
        except Exception:                                # noqa: BLE001
            pass
        pie_nota.configure(text=f"Simulación de '{fila.name}' terminada: no se ha "
                                f"tocado nada.")

    def guardar_aqui() -> None:
        """Guarda lo del editor SOLO en este dispositivo."""
        fila = fila_elegida()
        if fila is not None and fila.en_pen:
            plan_de(pair_editor.plan_override, estado["raw"], estado["cat"], fila.name,
                    editor.datos(), titulo=f"Modificar '{fila.name}' en este dispositivo")

    def volver_al_catalogo() -> None:
        """Devuelve la pareja elegida a lo que dice el catálogo."""
        fila = fila_elegida()
        if fila is not None:
            plan_de(pair_editor.plan_revert, estado["raw"], estado["cat"], fila.name,
                    titulo=f"Devolver '{fila.name}' a lo que dice el catálogo")

    def defaults_del_pen() -> None:
        """Cambia los `[defaults]` de este dispositivo."""
        cat = estado["cat"]
        datos = defaults_form(dlg, dict(estado["raw"].get("defaults") or {}),
                              cat.defaults if cat else None,
                              "Ajustes generales de este dispositivo",
                              "Valen para todas las parejas de este dispositivo.",
                              marca="el catálogo no cambia")
        if datos is not None:
            plan_de(pair_editor.plan_defaults, estado["raw"], datos,
                    titulo="Cambiar los ajustes de este dispositivo")

    def volver_defaults() -> None:
        """Devuelve los `[defaults]` a los del catálogo."""
        plan_de(pair_editor.plan_revert_defaults, estado["raw"], estado["cat"],
                titulo="Devolver los ajustes a los del catálogo")

    # El catálogo.

    def catalogo_nueva() -> None:
        """Da de alta una pareja en el catálogo."""
        datos = formulario(dlg, (estado["cat"].raw if estado["cat"] else {}), None, {},
                           titulo="Nueva pareja en el catálogo",
                           marca="Afecta a todos los dispositivos",
                           explorable=lectura().editable)
        if datos is not None:
            plan_de(catalog_editor.plan_catalog_save, estado["cat"], datos, None,
                    estado["raw"], en_catalogo=True, titulo="Dar de alta en el catálogo")

    def catalogo_guardar() -> None:
        """Guarda en el catálogo lo del editor."""
        fila = fila_elegida()
        if fila is not None:
            plan_de(catalog_editor.plan_catalog_save, estado["cat"], editor.datos(),
                    fila.name, estado["raw"], en_catalogo=True,
                    titulo=f"Editar '{fila.name}' en el catálogo")

    def catalogo_borrar() -> None:
        """Borra del catálogo la pareja elegida."""
        fila = fila_elegida()
        if fila is not None:
            plan_de(catalog_editor.plan_catalog_remove, estado["cat"], fila.name,
                    estado["raw"], en_catalogo=True,
                    titulo=f"Borrar '{fila.name}' del catálogo")

    def catalogo_defaults() -> None:
        """Cambia los `[defaults]` del catálogo."""
        cat = estado["cat"]
        if cat is None:
            messagebox.showerror(TITLE, "No hay catálogo que editar.", parent=dlg)
            return
        datos = defaults_form(dlg, cat.defaults, None,
                              "Ajustes generales del catálogo",
                              "Los heredan todos los dispositivos que no tengan los suyos.",
                              marca="afecta a TODOS los dispositivos")
        if datos is not None:
            plan_de(catalog_editor.plan_catalog_defaults, cat, datos, estado["raw"],
                    en_catalogo=True, titulo="Cambiar los ajustes del catálogo")

    def ver_flota() -> None:
        """Abre la ventana de los dispositivos."""
        from . import tk_fleet
        tk_fleet.open_dialog(dlg, estado["config"], estado["raw"])

    # Los botones. La franja de `[defaults]` lleva los suyos, según la vista.
    for col, (texto, accion) in enumerate((
            ("Ajustes de este dispositivo…", defaults_del_pen),
            ("Volver a los del catálogo", volver_defaults),
            ("Ajustes del catálogo…", catalogo_defaults)), start=3):
        b = ttk.Button(fila_defaults, text=texto, style="GrisQuiet.TButton",
                       command=accion)
        b.grid(row=0, column=col, padx=(theme.E1, 0))
        botones[texto] = b

    boton("dispositivo", "Usar aquí", usar_aqui, icono="plus", col=0)
    boton("dispositivo", "Simular", simular, icono="eye", col=1)
    boton("dispositivo", "Volver al catálogo", volver_al_catalogo, icono="back", col=2)
    boton("dispositivo", "Quitar…", quitar, "Danger.TButton", "trash", col=3)
    boton("dispositivo", "Descartar", descartar, col=11)
    boton("dispositivo", "Guardar aquí…", guardar_aqui, "Primary.TButton", col=12)
    boton("catalogo", "Nueva pareja…", catalogo_nueva, "Tonal.TButton", "plus", col=0)
    boton("catalogo", "Borrar del catálogo…", catalogo_borrar, "Danger.TButton",
          "trash", col=1)
    boton("catalogo", "Releer", lambda: leer_catalogo("Catálogo releído."),
          "Quiet.TButton", "reload", col=2)
    boton("catalogo", "Descartar", descartar, col=11, clave="Descartar del catálogo")
    boton("catalogo", "Guardar en el catálogo…", catalogo_guardar, "Primary.TButton",
          col=12)

    # La flota cuelga de aquí y no de la ventana principal: es de la misma
    # familia que el catálogo (lo que comparten todos los dispositivos) y no
    # algo que haya que mirar cada vez que se sincroniza. No se apaga sin
    # conexión: sin ella la ventana sabe decir que no la hay.
    flota_btn = ttk.Button(cierre, text="Dispositivos…", style="Quiet.TButton",
                           command=lambda: ver_flota())
    theme.boton_icono(flota_btn, "dispositivo", theme.ACENTO)
    flota_btn.grid(row=1, column=1, padx=(theme.E3, theme.E2))
    ttk.Button(cierre, text="Cerrar", command=dlg.destroy).grid(row=1, column=2)

    pie_nota.configure(text=nota_inicial())
    leer_catalogo()
    try:
        mostrar(dlg, parent)
    finally:
        # Las variables del editor quedan en ciclos con la ventana: se sueltan
        # AQUÍ, en el hilo de Tk. Si las soltara el recolector desde el hilo
        # de una lectura en segundo plano, borrarlas sería hablarle a Tk desde
        # otro hilo (`aviso_fallo` hace lo mismo).
        import gc
        gc.collect()
    return estado["cambiado"]


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

    Es el alta de una pareja en el catálogo: los mismos campos que el editor
    de la pantalla de parejas (`EditorPareja`), a una columna y con todo a la
    vista.

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
    editor = EditorPareja(marco, dlg, sup="", dos_columnas=False, plegable=False)
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

    def avisar(error: ConfigError | None) -> None:
        """Enseña el motivo en el recuadro rojo, o lo vacía si no hay."""
        for hijo in problema.winfo_children():
            hijo.destroy()
        if error is not None:
            theme.aviso(problema, flags_editor.titulo_error(error), str(error),
                        tono="Rojo.", ancho=300).grid(row=0, column=0, sticky="ew")

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
    mostrar(dlg, parent)
    return resultado["datos"]
