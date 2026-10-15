#!/usr/bin/env python3
"""La ventana de la guía de flags de rclone: solo dibuja.

Se abre desde el editor de flags de una pareja («Avanzado» → «Editar flags…» → «Guía de
flags…») y no desde la ventana principal, que se queda limpia. Es de consulta: no cambia
lo que hay escrito en el editor ni guarda nada.

Todo lo que decide sale de `ui/flags_guia.py`, que no usa Tk y se prueba aparte: qué
fichas hay, cómo se busca y se filtra (`buscar()`), qué se enseña de cada una (`detalle()`)
y si sirve en la pareja (`sirve_en()`). Aquí solo se pintan: un cuadro de búsqueda, tres
filtros, una tabla de un solo lienzo y un texto con la explicación de la fila elegida.

La tabla no enseña más de `MAX_FILAS` filas a la vez, aunque la guía tenga cientos de
flags: lo que se busca se afina escribiendo o filtrando, y «Ver más» abre el resto. Así la
ventana no crece con la guía ni se hace un lienzo de miles de elementos. Nada se hace a
destiempo (ningún reloj de Tk): cada tecla y cada filtro repintan al instante, porque
buscar entre cientos de fichas cuesta milisegundos.
"""

from __future__ import annotations

from common import model

from . import flags_guia, theme
from .tk import CeldaChip, CeldaTexto, FilaTabla, centrar, cuerpo_visible, modal, mostrar
from .tk_tabla import TablaLienzo

MAX_FILAS = 12
"""Cuántas filas enseña la tabla de golpe."""
PASO_VER_MAS = 24
"""Cuántas filas más abre cada «Ver más»."""

CUALQUIER_RIESGO = "Cualquier riesgo"
CUALQUIER_MODO = "Cualquier modo"
CUALQUIER_TEMA = "Cualquier tema"
"""Lo que dice cada filtro cuando no filtra."""

COLUMNAS = [("Flag", 190, False), ("Riesgo", 150, False), ("Lo pone", 150, False),
            ("Qué es", 260, True)]
"""Las columnas de la tabla: `(titulo, ancho, estira)`."""

TONO_RIESGO = {flags_guia.RIESGO_LEE: "Ok.", flags_guia.RIESGO_NOMBRES: "Aviso.",
               flags_guia.RIESGO_BORRA: "Peligro."}
"""El tono del chip de cada riesgo: lo que solo lee, en verde; lo que borra, en rojo."""


def fila_de(f: flags_guia.Ficha, modo: str | None) -> FilaTabla:
    """Devuelve la fila de la tabla para una ficha.

    Un flag que no sirve en el modo de la pareja sale apagado; uno sin explicación propia
    lleva la ayuda de rclone, marcada como inglesa.

    Args:
        f: La ficha.
        modo: El modo de la pareja, o `None` si no hay pareja.
    """
    riesgo = (CeldaChip(flags_guia.ETIQUETAS_RIESGO[f.riesgo], TONO_RIESGO[f.riesgo])
              if f.riesgo else CeldaChip("Sin clasificar", "Apagado."))
    lo_pone = {flags_guia.ESTADO_FIJO: CeldaChip("Lo pone prdrive", "Acento.", "candado"),
               flags_guia.ESTADO_VALOR: CeldaChip("Valor de prdrive"),
               flags_guia.ESTADO_NO_ADMITIDO: CeldaChip("No se admite", "Peligro.")
               }.get(f.estado, CeldaTexto(""))
    que_es = (CeldaTexto(f.titulo) if f.explicada
              else CeldaTexto(f"(en inglés) {f.ayuda}", "Pista."))
    return FilaTabla(f.nombre, (CeldaTexto(f"--{f.nombre}", "Mono."), riesgo, lo_pone, que_es),
                     "" if flags_guia.sirve_en(f, modo) else "apagado")


def cuenta_de(total: int, a_la_vista: int) -> str:
    """Devuelve lo que se dice de cuántos flags hay y cuántos se ven."""
    if total == 0:
        return "Ningún flag encaja con eso. Prueba con otras palabras o quita algún filtro."
    if total <= a_la_vista:
        return "1 flag." if total == 1 else f"{total} flags."
    return f"Enseño {a_la_vista} de {total} flags."


class VentanaGuia:
    """La guía de flags: la ventana y lo que enseña en cada momento.

    Args:
        parent: La ventana de la que cuelga (el editor de flags).
        modo: El modo de la pareja que se edita, o `None` en los flags comunes de
            `[defaults]`: sirve para apagar lo que no le sirve y decirlo en el detalle.
        consulta: Con lo que se abre la búsqueda (el flag de la línea del cursor).

    Attributes:
        ventana: El diálogo.
        modo_de_la_pareja: El `modo` del constructor.
        entrada: El cuadro de búsqueda.
        riesgo: El filtro de riesgo (`ttk.Combobox`).
        modo: El filtro de modo.
        tema: El filtro de tema.
        tabla: La tabla de resultados (`tk_tabla.TablaLienzo`).
        cuenta: Lo que dice cuántos flags hay.
        mas: El botón «Ver más», fuera de la rejilla si no hay más.
        detalle: El texto de solo lectura con la explicación de la fila elegida.
        resultados: Las fichas que encajan con la búsqueda y los filtros, todas.
        limite: Cuántas se enseñan ahora.
    """

    def __init__(self, parent, modo: str | None = None, consulta: str = "") -> None:
        from tkinter import ttk
        self.parent = parent
        self.modo_de_la_pareja = modo
        self.resultados: list[flags_guia.Ficha] = []
        self.limite = MAX_FILAS
        self._texto_buscado = ""
        self._claves_riesgo = {flags_guia.ETIQUETAS_RIESGO[r]: r for r in flags_guia.RIESGOS}
        self._claves_tema = {flags_guia.ETIQUETAS_TEMA[t]: t for t in flags_guia.TEMAS}

        dlg = self.ventana = modal(parent, "Guía de flags de rclone")
        dlg.guia = self                                  # los tests la miran
        marco = cuerpo_visible(dlg, padding=(theme.E5, theme.E4, theme.E5, theme.E4))
        marco.columnconfigure(0, weight=1)
        ttk.Label(marco, text="Guía de flags de rclone", style="Dialogo.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(marco, style="Pista.TLabel", wraplength=theme.medida(640), justify="left",
                  text=("Para consultar: no cambia nada de lo que escribes. Busca por el nombre "
                        "de un flag, por lo que hace («qué hace con los borrados») o por lo que "
                        "quieres conseguir («cómo ignoro ficheros temporales»).")).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(theme.E1, 0))

        self.entrada = ttk.Entry(marco, width=60)
        theme.pista_campo(self.entrada, "Buscar un flag o lo que quieres hacer…")
        self.entrada.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(theme.E4, 0))
        self.entrada.insert(0, consulta)

        filtros = ttk.Frame(marco)
        filtros.grid(row=3, column=0, columnspan=2, sticky="w", pady=(theme.E3, 0))
        self.riesgo = self._filtro(filtros, 0, CUALQUIER_RIESGO, list(self._claves_riesgo))
        self.modo = self._filtro(filtros, 1, CUALQUIER_MODO, list(model.MODES))
        self.tema = self._filtro(filtros, 2, CUALQUIER_TEMA, list(self._claves_tema))

        self.tabla = TablaLienzo(
            marco, COLUMNAS, al_elegir=self.pintar_detalle, rejilla=False, encima=False,
            alto_fila=30, vacio="Ningún flag encaja con eso.")
        self.tabla.marco.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(theme.E3, 0))

        pie = ttk.Frame(marco)
        pie.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(theme.E2, 0))
        pie.columnconfigure(0, weight=1)
        self.cuenta = ttk.Label(pie, style="Pista.TLabel")
        self.cuenta.grid(row=0, column=0, sticky="w")
        self.mas = ttk.Button(pie, text="Ver más", style="Quiet.TButton", command=self.ver_mas)
        self.mas.grid(row=0, column=1, sticky="e")

        self.detalle = theme.caja_texto(marco, width=76, height=15, wrap="word",
                                        font=theme.fuente("texto"), spacing1=theme.E2)
        self.detalle.grid(row=6, column=0, sticky="nsew", pady=(theme.E3, 0))
        barra = ttk.Scrollbar(marco, orient="vertical", command=self.detalle.yview)
        barra.grid(row=6, column=1, sticky="ns", pady=(theme.E3, 0))
        self.detalle.configure(yscrollcommand=barra.set, state="disabled")
        mono = theme.fuente("mono")
        self.detalle.tag_configure("nombre", font=(mono[0], mono[1] + 2, "bold"),
                                   foreground=theme.TINTA)
        self.detalle.tag_configure("titulo", font=theme.fuente("fuerte"), foreground=theme.TINTA)
        self.detalle.tag_configure("rotulo", font=theme.fuente("fuerte"),
                                   foreground=theme.TINTA2)
        self.detalle.tag_configure("marca", background=theme.AVISO_FONDO)

        ttk.Label(marco, style="Pista.TLabel", wraplength=theme.medida(640), justify="left",
                  text="\n".join(f"{flags_guia.ETIQUETAS_RIESGO[r]}: "
                                  f"{flags_guia.DESCRIPCION_RIESGO[r]}"
                                  for r in flags_guia.RIESGOS)).grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(theme.E3, 0))
        ttk.Button(marco, text="Cerrar", command=dlg.destroy).grid(
            row=8, column=0, columnspan=2, sticky="e", pady=(theme.E4, 0))

        self.entrada.bind("<KeyRelease>", self._al_teclear)
        self.entrada.bind("<ButtonRelease-2>", self._al_teclear)      # pegar con el ratón
        self.entrada.bind("<Down>", lambda e: self._mover(1))
        self.entrada.bind("<Up>", lambda e: self._mover(-1))
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        self.actualizar()
        self.entrada.focus_set()

    def _filtro(self, padre, columna: int, ninguno: str, valores: list[str]):
        """Hace un desplegable de filtro que empieza sin filtrar."""
        from tkinter import ttk
        combo = ttk.Combobox(padre, state="readonly", values=[ninguno, *valores], width=24)
        combo.set(ninguno)
        combo.grid(row=0, column=columna, padx=(0 if columna == 0 else theme.E2, 0))
        combo.bind("<<ComboboxSelected>>", lambda e: self.actualizar())
        return combo

    def _al_teclear(self, _evento=None) -> None:
        """Repinta si lo escrito ha cambiado; una tecla que no escribe no toca nada.

        Soltar una tecla también llega aquí: la flecha que acaba de mover la fila, Mayúsculas o
        Control no cambian el texto, y repintar desharía lo que hicieron (la fila elegida
        volvería a la primera y «Ver más» se cerraría).
        """
        if self.entrada.get() != self._texto_buscado:
            self.actualizar()

    def _valor(self, combo, ninguno: str, claves: dict[str, str] | None = None):
        """Devuelve lo que filtra un desplegable, o `None` si no filtra."""
        elegido = combo.get()
        if elegido == ninguno:
            return None
        return elegido if claves is None else claves.get(elegido, elegido)

    def actualizar(self, conservar: bool = False) -> None:
        """Busca con lo escrito y los filtros y repinta la tabla, la cuenta y el detalle.

        Args:
            conservar: Si se da, la fila elegida se queda donde estaba mientras siga
                saliendo; si no, se elige la primera, que es la que más encaja.
        """
        if not conservar:
            self.limite = MAX_FILAS
        self._texto_buscado = self.entrada.get()
        self.resultados = flags_guia.buscar(
            self._texto_buscado,
            riesgo=self._valor(self.riesgo, CUALQUIER_RIESGO, self._claves_riesgo),
            modo=self._valor(self.modo, CUALQUIER_MODO),
            tema=self._valor(self.tema, CUALQUIER_TEMA, self._claves_tema))
        a_la_vista = self.resultados[:self.limite]
        cambio = self.tabla.poner([fila_de(f, self.modo_de_la_pareja) for f in a_la_vista])
        elegida = self.tabla.elegida if conservar else None
        if elegida not in self.tabla.orden:
            elegida = self.tabla.orden[0] if self.tabla.orden else None
        self.tabla.elegir(elegida, False)
        self.cuenta.configure(text=cuenta_de(len(self.resultados), len(a_la_vista)))
        if len(self.resultados) > len(a_la_vista):
            self.mas.grid()
        else:
            self.mas.grid_remove()
        self.pintar_detalle()
        if cambio:
            self._crecer()

    def ver_mas(self) -> None:
        """Abre más filas de la tabla sin perder la que estaba elegida."""
        self.limite += PASO_VER_MAS
        self.actualizar(conservar=True)

    def _mover(self, paso: int) -> str:
        """Pasa a la fila de arriba o de abajo desde el cuadro de búsqueda, sin salir de él."""
        orden = self.tabla.orden
        if orden:
            actual = orden.index(self.tabla.elegida) if self.tabla.elegida in orden else -1
            self.tabla.elegir(orden[max(0, min(len(orden) - 1, actual + paso))], True)
        return "break"

    def pintar_detalle(self) -> None:
        """Escribe en el texto la explicación de la fila elegida, o lo deja vacío si no hay."""
        caja = self.detalle
        caja.configure(state="normal")
        caja.delete("1.0", "end")
        f = flags_guia.ficha(self.tabla.elegida) if self.tabla.elegida else None
        if f is not None:
            caja.insert("end", f"--{f.nombre}", "nombre")
            if f.titulo:
                caja.insert("end", f"\n{f.titulo}", "titulo")        # cada párrafo, su línea
            for rotulo, texto in flags_guia.detalle(f, self.modo_de_la_pareja):
                # Se sombrea lo que restringe (lo fija prdrive o el config lo rechaza) y el
                # «Ojo», no lo que solo trae un valor de partida.
                marca = (("marca",) if rotulo == flags_guia.R_CUIDADO or (
                    rotulo == flags_guia.R_ESTADO and f.estado in (
                        flags_guia.ESTADO_FIJO, flags_guia.ESTADO_NO_ADMITIDO)) else ())
                caja.insert("end", "\n")
                caja.insert("end", f"{rotulo}: ", ("rotulo", *marca))
                caja.insert("end", texto, marca)
        caja.configure(state="disabled")
        caja.yview_moveto(0)

    def _crecer(self) -> None:
        """Agranda la ventana si la tabla pide más sitio, y la recoloca."""
        if self.ventana.winfo_ismapped() and self.ventana.visor.crecer(self.ventana):
            centrar(self.ventana, self.parent)

    def abrir(self) -> None:
        """Enseña la guía y espera a que se cierre."""
        mostrar(self.ventana, self.parent)


def abrir(parent, modo: str | None = None, consulta: str = "") -> None:
    """Abre la guía de flags sobre `parent` y espera a que se cierre.

    Args:
        parent: La ventana de la que cuelga.
        modo: El modo de la pareja que se edita, o `None` si no hay pareja.
        consulta: Con lo que se abre la búsqueda, normalmente el flag de la línea del
            cursor del editor.
    """
    VentanaGuia(parent, modo, consulta).abrir()
