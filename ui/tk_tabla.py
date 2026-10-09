#!/usr/bin/env python3
"""Una tabla dibujada en un solo lienzo: la `Table` del diseño sin un widget por celda.

Solo dibuja. Lo que enseña cada fila lo decide quien la llama, con las filas de
`tk.Tabla` (`FilaTabla` con celdas de texto, chip o icono, más `CeldaCasilla`).
Todo son elementos de un `tk.Canvas` (rectángulos, textos e imágenes) y no un
widget por celda: en Windows cada widget es una ventana del sistema que se
crea, se coloca y se pinta por su cuenta. Cincuenta parejas son un widget y no
más de cuatrocientos. «Parejas» la usa tal cual y `tk.Tabla` («Dispositivos», el
editor de flags) la envuelve con las reglas de una rejilla de etiquetas
(`rejilla=True`, `alto_fila`, `encima=False`).

Se ve como una rejilla de etiquetas de ttk:

- la tarjeta es la pieza de `Card.TFrame` (sus cuatro esquinas se recortan de la
  misma imagen de `icons.caja()`), con la cabecera en el papel, sus rótulos en
  la letra del tema y una línea de 1 px (`LINEA_SUAVE`) entre fila y fila;
- cada columna mide lo que su contenido más ancho, como en `grid`, con los
  mismos huecos (`theme.E2`, `theme.E3`) y el margen que una `ttk.Label` deja
  alrededor de su texto (`HOLGURA`). La que estira se queda con lo que sobre.
  En una rejilla (`rejilla=True`) ninguna celda se corta; en una lista de
  «Parejas» (`rejilla=False`) la que estira mide solo su mínimo o su rótulo, y
  su texto, si no cabe, se corta con «…» y no ensancha la ventana;
- un chip es su píldora (la pieza del estilo de chip del tema, estirada a su
  ancho como la estira ttk), su disco o su icono (`icons.disco()`,
  `icons.get()`) y su palabra, con las medidas del chip de ttk. Va pintado sobre
  el rectángulo de su fila, así que lo que asoma por sus esquinas es siempre el
  color de la fila: normal, elegida, ámbar o roja;
- el texto lleva la fuente del tema tal como la reciben los estilos
  (`theme.fuente_tcl()`), no la `Font` de `theme.fuente_tk()`: con Xft esa
  `Font` con nombre abre la Noto Sans en negrita donde la etiqueta abre la
  seminegrita, y los nombres saldrían más gruesos y las columnas mal medidas.

Cambia solo lo que cambia. `poner()` compara por `iid`: una fila igual no se
toca; una que cambia se dibuja de nuevo, y solo ella; una que se va se borra y
una que llega se dibuja. Si una fila cambia de alto, las de debajo se desplazan;
si cambia de sitio, se mueve. Si una columna cambia de anchura, sus elementos se
desplazan de una vez (`move` por la etiqueta de la columna). Elegir otra fila
repinta dos; pasar el ratón, una.
Una anchura nueva del lienzo (`<Configure>`) solo desplaza las columnas de la
derecha y, en una lista, vuelve a cortar los textos de la que estira.

Cada fila mide lo que la más alta de sus celdas, en la lista y en la rejilla: un
chip más bajo que el de otra fila deja su fila más baja, como en una rejilla de
etiquetas.

Se usa sin ratón: Tab le da el foco; con ↑/↓, Inicio/Fin o RePág/AvPág se cambia
de fila y el anillo del foco (2 px del acento dentro de la fila elegida) se
enseña. Un clic elige la fila y da el foco, pero no enseña el anillo. Intro no
hace nada: la fila elegida ya lo está. La rueda no es suya: la pasa al marco de
debajo, para que la recoja el `Visor` de la pantalla.
"""

from __future__ import annotations

from typing import NamedTuple

from . import icons, theme
from .tk import CeldaChip, CeldaIcono, CeldaTexto, FilaTabla

HOLGURA = 2
"""Lo que una `ttk.Label` de clam pide alrededor de su texto o su imagen, en píxeles.

Es lo mismo a cualquier escala (no es una medida del diseño, es de ttk), y con
ello cada columna empieza y mide lo que mediría con etiquetas de ttk.
`tests/test_tk_tabla.py` lo compara con una etiqueta de verdad.
"""
ESPACIO_CHIP = 4
"""El hueco entre la imagen y la palabra de un chip: el de una `ttk.Label` con imagen, en píxeles."""
ALTO_CABECERA = 28
"""El alto mínimo de la cabecera, en medidas del diseño."""
ALTO_FILA = 36
"""El alto mínimo de una fila, en medidas del diseño (el de `tk.Tabla`)."""
ALTO_CHIP = 24
"""El alto de un chip en el diseño: de él sale el relleno de su palabra (`theme.chip`)."""
GROSOR_ANILLO = 2
"""El anillo del foco del teclado, en medidas del diseño: el de los controles del tema."""
MEZCLA_ENCIMA = 0.045
"""Cuánto se lleva hacia la tinta el fondo de la fila que tiene el ratón encima."""
PAGINA = 10
"""Las filas que salta RePág o AvPág."""

SUPERFICIE_FILA = {"": "Card.", "apagado": "Card.", "aviso": "NotaAmbar.",
                   "peligro": "Rojo.", "propio": "NotaAzul."}
"""La superficie de cada tono de fila: su fondo y, en la roja, el color de su texto."""
ELEGIDA = "NotaAzul."
"""La superficie de la fila elegida: el azul suave del acento."""


class CeldaCasilla(NamedTuple):
    """Una celda con la casilla de marcar del tema (`icons.casilla`); dice, no se pulsa.

    Args:
        marcada: Si va marcada.
        texto: Lo que dice para quien no la ve (`leer()`); sin él, «☑» o «☐».
    """
    marcada: bool
    texto: str = ""


def _pieza_chip(widget, tipo: str):
    """Devuelve la pieza de nueve trozos del chip de ese tipo, la del estilo del tema: `(imagen, borde)`.

    Son los mismos tonos que pone `theme` en el estilo `{tipo}Chip.TLabel`: el
    borde y, dentro, el relleno, o solo el aro si el relleno es el papel (el
    chip apagado). Con los mismos tonos `icons.caja()` devuelve la imagen que
    ya tiene hecha, y la píldora sale con los mismos píxeles.
    """
    fondo, borde, *_ = theme.colores_chip(tipo)
    tonos = [(borde, 0), (None if fondo == theme.PAPEL else fondo, 1)]
    return icons.caja(widget, tonos, theme.RADIO_PILDORA)


def _tramos(lado: int, borde: int, destino: int) -> list[tuple[int, int, int, int]]:
    """Los tramos de nueve trozos en un eje: `(desde, hasta, a_desde, a_hasta)`.

    Los dos extremos se copian tal cual y el del medio se repite hasta llenar
    el destino, como hace ttk con una pieza de imagen.
    """
    tramos = ((0, borde, 0, borde), (borde, lado - borde, borde, destino - borde),
              (lado - borde, lado, destino - borde, destino))
    return [t for t in tramos if t[3] > t[2]]


def _estirada(widget, pieza, borde: int, ancho: int, alto: int):
    """Devuelve la pieza estirada a `ancho` x `alto` píxeles, como la estira ttk.

    Se guarda en la caché de `icons`, por intérprete: `icons.olvidar()` la suelta.
    """
    import tkinter as tk

    def hacer():
        """Copia las esquinas y repite los bordes y el centro (`photo copy`, en C)."""
        img = tk.PhotoImage(master=widget, width=ancho, height=alto)
        for de_x, a_x, x0, x1 in _tramos(pieza.width(), borde, ancho):
            for de_y, a_y, y0, y1 in _tramos(pieza.height(), borde, alto):
                widget.tk.call(str(img), "copy", str(pieza), "-from", de_x, de_y, a_x, a_y,
                               "-to", x0, y0, x1, y1, "-compositingrule", "set")
        return img

    return icons.guardada(widget, (str(pieza), "estirada", ancho, alto), hacer)


def _recorte(widget, pieza, x0: int, y0: int, lado: int):
    """Devuelve el cuadrado de `lado` píxeles de la pieza que empieza en `(x0, y0)`."""
    import tkinter as tk

    def hacer():
        """Copia ese trozo en una imagen suya."""
        img = tk.PhotoImage(master=widget, width=lado, height=lado)
        widget.tk.call(str(img), "copy", str(pieza), "-from", x0, y0, x0 + lado, y0 + lado,
                       "-to", 0, 0, "-compositingrule", "set")
        return img

    return icons.guardada(widget, (str(pieza), "recorte", x0, y0, lado), hacer)


class _Chip(NamedTuple):
    """Cómo se dibuja un chip, en píxeles desde su esquina de arriba a la izquierda."""
    pildora: object
    ancho: int
    alto: int
    adorno: object
    x_adorno: int
    y_adorno: int
    x_texto: int
    y_texto: int
    letra: str


class _Fila:
    """Lo que la tabla sabe de una fila: lo que se le dio, dónde está y qué dibujó.

    Args:
        fila: La `FilaTabla`.
        clave: La etiqueta del lienzo de todos sus elementos (`r<n>`).

    Attributes:
        pos: Su posición, de arriba abajo.
        anchos: Lo que pide cada celda, en píxeles.
        alto: Lo que pide la más alta de sus celdas.
        fondo: El rectángulo de su fondo, o `None` si aún no se dibujó.
        textos: Los textos de la fila, que cambian de color con ella y se
            cortan si su columna estira: `(elemento, columna, texto entero, rol
            del estilo, rol de la letra)`.
        leidos: Por columna, `(elemento de texto, lo que dice si es una imagen)`.
        y: Dónde empieza (de arriba) la fila dibujada, en píxeles del lienzo.
        h: Lo que mide la fila dibujada, en píxeles.
    """

    __slots__ = ("fila", "clave", "pos", "anchos", "alto", "fondo", "textos", "leidos", "y", "h")

    def __init__(self, fila: FilaTabla, clave: str) -> None:
        self.fila, self.clave = fila, clave
        self.pos = -1
        self.anchos: list[int] = []
        self.alto = 0
        self.fondo: int | None = None
        self.textos: list[tuple[int, int, str, str, str]] = []
        self.leidos: list[tuple[int | None, str]] = []
        self.y = self.h = 0


class TablaLienzo:
    """Una tabla dibujada en un `tk.Canvas`: cabecera en rótulos y una fila por elemento.

    Args:
        parent: Dónde va.
        columnas: `(titulo, ancho, estira)` por columna, como en `tk.Tabla`: el
            ancho es el mínimo, en medidas del diseño, y la que estira se queda
            con lo que sobre (en una lista su texto se corta con «…» si no cabe;
            en una rejilla no se corta nada).
        al_elegir: Lo que se llama después de elegir otra fila con el ratón o
            el teclado; sin él, las filas no se eligen a mano.
        puede_dejar: Se pregunta antes de cambiar de fila; si dice que no, no se
            hace. Sin él, siempre se puede.
        vacio: Lo que se dice cuando no hay ninguna fila.
        superficie: La superficie sobre la que va la tabla (`''`, el papel):
            es lo que asoma por fuera de sus esquinas redondeadas.
        alto_fila: El alto mínimo de cada fila, en medidas del diseño: 36 la de
            una lista y 30 la de una tabla larga que solo se lee (con 30 el
            relleno de arriba y abajo es `theme.E1` y no `theme.E2`).
        rejilla: Si la tabla se reparte como una rejilla de etiquetas de ttk
            (`tk.Tabla`) y no como una lista de «Parejas». Con `True`: ninguna
            celda se corta (la columna que estira mide lo que su contenido más
            ancho y se queda con lo que sobra), el ancho mínimo de una columna
            cuenta los huecos de sus lados (el `minsize` de `grid`). Con `False`
            la columna que estira corta con «…» lo que no le cabe y su mínimo es
            el del contenido. En los dos casos cada fila mide lo que la más alta
            de sus celdas.
        encima: Si la fila que tiene el ratón encima se tiñe hacia la tinta.
            Solo cuenta con `al_elegir`: sin él, la tabla no mira el ratón.

    Attributes:
        marco: El `tk.Canvas`: lo que se coloca (`grid`), lo que recibe el foco y
            donde se dibuja todo.
        al_elegir: El del constructor; se puede cambiar.
        puede_dejar: El del constructor; se puede cambiar.
        filas: Por `iid`, la `FilaTabla` que se dibuja.
        orden: Los `iid`, de arriba abajo.
        elegida: El `iid` de la fila elegida, o `None`.
        cabeceras: Los títulos de las columnas.
    """

    def __init__(self, parent, columnas, al_elegir=None, puede_dejar=None,
                 vacio: str = "", superficie: str = "", alto_fila: int = ALTO_FILA,
                 rejilla: bool = False, encima: bool = True) -> None:
        import tkinter as tk
        self.al_elegir, self.puede_dejar, self._vacio = al_elegir, puede_dejar, vacio
        self._rejilla = rejilla
        self._columnas = [(titulo, ancho, bool(estira)) for titulo, ancho, estira in columnas]
        self.cabeceras = [titulo for titulo, _ancho, _estira in self._columnas]
        self._elegible = al_elegir is not None
        self.marco = tk.Canvas(
            parent, highlightthickness=0, borderwidth=0, takefocus=1 if self._elegible else 0,
            background=theme.fondo_de(superficie), width=1, height=1)
        self.filas: dict[str, FilaTabla] = {}
        self.orden: list[str] = []
        self.elegida: str | None = None
        self._filas: dict[str, _Fila] = {}
        self._creadas = 0
        self._encima: str | None = None
        self._raton_y: int | None = None        # dónde está el ratón sobre el lienzo
        self._con_foco = False
        self._sin_anillo = False                # un clic dio el foco: no se enseña el anillo
        self._chips: dict[CeldaChip, _Chip] = {}
        self._medidas: dict[tuple[str, str], int] = {}
        self._lineas: dict[str, int] = {}
        cv = self.marco
        self._uno = icons.px(cv, 1)
        self._e1, self._e2, self._e3 = (cv.winfo_pixels(e) for e in (theme.E1, theme.E2,
                                                                      theme.E3))
        self._alto_cabecera = max(icons.px(cv, ALTO_CABECERA),
                                  self._linea("rotulo") + 2 * HOLGURA + 2 * self._e1)
        self._min_fila = icons.px(cv, alto_fila)
        self._relleno = self._e2 if alto_fila >= ALTO_FILA else self._e1
        self._alturas: list[int] = []
        self._tops: list[int] = []
        self._cuerpo = 0
        n = len(self._columnas)
        self._x = [0] * n
        self._anchos = [0] * n
        self._ancho = self._alto = 0
        self._pedido = (0, 0)
        self._cabecera()
        self._tarjeta_hecha: tuple = ()
        self._ajustar(self._maquetar())
        cv.bind("<Configure>", self._configurar)
        for rueda in ("<MouseWheel>", "<Button-4>", "<Button-5>"):     # Windows / X11
            cv.bind(rueda, lambda e, rueda=rueda: self._rueda(rueda, e))
        if self._elegible:
            for tecla, paso in (("<Up>", -1), ("<Down>", 1), ("<Prior>", -PAGINA),
                                ("<Next>", PAGINA), ("<Home>", None), ("<End>", None)):
                cv.bind(tecla, lambda _e, paso=paso, tecla=tecla: self._tecla(tecla, paso))
            cv.bind("<Return>", self._intro)
            cv.bind("<KP_Enter>", self._intro)
            cv.bind("<Button-1>", self._clic)
            if encima:
                cv.bind("<Motion>", self._mover)
                cv.bind("<Leave>", lambda _e: self._salir())
            cv.bind("<FocusIn>", lambda _e: self._foco(True))
            cv.bind("<FocusOut>", lambda _e: self._foco(False))

    # ------------------------------------------------------------- la letra
    def _fuente(self, letra: str) -> str:
        """Devuelve la fuente de ese rol de letra tal como la reciben los estilos, y la deja sujeta.

        Un texto oculto del propio lienzo la sujeta: medir con Xft una fuente
        que nadie tiene puesta reabre la cara en cada medida (`theme`, «la
        letra se mide una vez»).
        """
        fuente = theme.fuente_tcl(letra)
        if letra not in self._lineas:
            self.marco.create_text(-100, -100, text="", font=fuente, state="hidden",
                                    tags=("letra",))
            self._lineas[letra] = int(self.marco.tk.call("font", "metrics", fuente,
                                                        "-linespace"))
        return fuente

    def _linea(self, letra: str) -> int:
        """Devuelve el alto de una línea de ese rol de letra, en píxeles."""
        self._fuente(letra)
        return self._lineas[letra]

    def _medir(self, letra: str, texto: str) -> int:
        """Devuelve lo que ocupa `texto` en ese rol de letra, en píxeles."""
        clave = (letra, texto)
        ancho = self._medidas.get(clave)
        if ancho is None:
            ancho = self._medidas[clave] = int(self.marco.tk.call(
                "font", "measure", self._fuente(letra), texto))
        return ancho

    def _cortar(self, letra: str, texto: str, cabe: int) -> str:
        """Devuelve `texto`, o su principio con «…» si no cabe en `cabe` píxeles."""
        if self._medir(letra, texto) <= cabe:
            return texto
        bajo, alto = 0, len(texto)
        while bajo < alto:
            medio = (bajo + alto + 1) // 2
            if self._medir(letra, texto[:medio] + "…") <= cabe:
                bajo = medio
            else:
                alto = medio - 1
        return texto[:bajo] + "…"

    # --------------------------------------------------------------- celdas
    @staticmethod
    def _rol(celda, tono: str) -> str:
        """El rol de un texto: el suyo, o el apagado si la fila lo está."""
        rol = celda.rol if isinstance(celda, CeldaTexto) else ""
        if tono == "apagado":
            return "MonoPista." if rol.startswith("Mono") else "Pista."
        return rol

    def _chip(self, celda: CeldaChip) -> _Chip:
        """Devuelve cómo se dibuja un chip, con las medidas de `theme.chip()`, hecho una vez.

        La etiqueta de ttk es su pieza (con un relleno de 1 px de diseño), dentro
        el relleno del estilo (o el del chip con disco) y en él, centrada, la
        caja de la imagen y la palabra, cada una centrada en la caja.
        """
        hecho = self._chips.get(celda)
        if hecho is not None:
            return hecho
        cv = self.marco
        fondo, _borde, letra, disco, tinta, glifo = theme.colores_chip(celda.tipo, celda.icono)
        pieza, borde = _pieza_chip(cv, celda.tipo)
        adorno = None
        if disco is not None and glifo:
            adorno = icons.disco(cv, glifo, disco, tinta, fondo, hueco=celda.tipo == "Apagado.")
        elif glifo:
            adorno = icons.get(cv, glifo, 12, tinta, fondo)
        if adorno is not None and disco is not None:
            izq = arriba = icons.px(cv, 2)
        else:
            izq, arriba = self._e2, theme.relleno_control(cv, ALTO_CHIP, "pista")[1]
        uno = icons.px(cv, 1)
        ancho_adorno, alto_adorno = ((adorno.width(), adorno.height()) if adorno is not None
                                     else (0, 0))
        palabra, linea = self._medir("pista", celda.texto), self._linea("pista")
        contenido = ancho_adorno + ESPACIO_CHIP + palabra if adorno is not None else palabra
        ancho = max(2 * borde, 2 * uno + izq + self._e2 + contenido)
        alto = max(2 * borde, 2 * uno + 2 * arriba + max(alto_adorno, linea))
        caja = max(alto_adorno, linea)
        y = uno + arriba + (alto - 2 * uno - 2 * arriba - caja) // 2
        pildora = (_estirada(cv, pieza, borde, ancho, alto) if pieza is not None else None)
        x = uno + izq
        hecho = self._chips[celda] = _Chip(
            pildora, ancho, alto, adorno, x, y + (caja - alto_adorno) // 2,
            x + ancho_adorno + ESPACIO_CHIP if adorno is not None else x,
            y + (caja - linea) // 2, letra)
        return hecho

    def _imagen(self, celda, superficie: str):
        """La imagen de una celda de casilla o de icono, o `None` si no se puede pintar."""
        if isinstance(celda, CeldaCasilla):
            return icons.casilla(self.marco, "marcada" if celda.marcada else "vacia", margen=0)
        return icons.get(self.marco, celda.nombre, 16, theme.OK, theme.fondo_de(superficie))

    def _celda(self, celda, tono: str) -> tuple[int, int]:
        """Lo que pide una celda: `(ancho, alto)` en píxeles, con lo que ttk pondría alrededor."""
        if isinstance(celda, CeldaChip):
            chip = self._chip(celda)
            return chip.ancho, chip.alto
        if isinstance(celda, (CeldaCasilla, CeldaIcono)):
            img = self._imagen(celda, SUPERFICIE_FILA.get(tono, "Card."))
            lados = (img.width(), img.height()) if img is not None else (0, 0)
            return lados[0] + 2 * HOLGURA, lados[1] + 2 * HOLGURA
        texto = celda.texto if isinstance(celda, CeldaTexto) else str(celda)
        letra = theme.rol_texto(self._rol(celda, tono))[1]
        return (self._medir(letra, texto) + 2 * HOLGURA, self._linea(letra) + 2 * HOLGURA)

    def _medir_fila(self, f: _Fila, fila: FilaTabla) -> None:
        """Le pone a `f` la fila nueva y lo que piden sus celdas."""
        f.fila = fila
        medidas = [self._celda(celda, fila.tono) for celda in fila.celdas]
        f.anchos = [ancho for ancho, _alto in medidas]
        f.alto = max((alto for _ancho, alto in medidas), default=0)

    # --------------------------------------------------------------- maqueta
    def _lados(self, col: int) -> tuple[int, int]:
        """El hueco a los lados de una celda, en píxeles: el de la rejilla y el borde de la fila."""
        return (self._e3 if col == 0 else self._e2,
                self._e3 if col == len(self._columnas) - 1 else 0)

    def _maquetar(self, orden: list[str] | None = None) -> tuple[list[int], list[int], int, int]:
        """Calcula lo que pide la tabla con las filas que tiene.

        Args:
            orden: Los `iid` de arriba abajo; sin él, los de ahora.

        Returns:
            `(anchos, alturas, ancho pedido, alto pedido)`: el ancho de cada
            columna sin repartir lo que sobre (la que estira, solo su mínimo y su
            rótulo; en una rejilla, también lo que pida su contenido), lo que
            mide cada fila (la más alta de sus celdas, con su hueco) y los
            tamaños, en píxeles.
        """
        cv = self.marco
        orden = self.orden if orden is None else orden
        anchos = []
        for col, (titulo, minimo, estira) in enumerate(self._columnas):
            minimo = icons.px(cv, minimo) if minimo else 0
            if self._rejilla:       # el `minsize` de una rejilla cuenta los huecos de los lados
                minimo = max(0, minimo - sum(self._lados(col)))
            ancho = max(minimo, self._medir("rotulo", theme.rotulo(titulo)) + 2 * HOLGURA
                        if titulo else 0)
            if not estira or self._rejilla:
                ancho = max([ancho] + [f.anchos[col] for f in self._filas.values()
                                       if col < len(f.anchos)])
            anchos.append(ancho)
        alturas = [max(self._min_fila, self._filas[iid].alto + 2 * self._relleno)
                   for iid in orden]
        ancho = 2 * self._uno + sum(a + sum(self._lados(c)) for c, a in enumerate(anchos))
        if orden:
            cuerpo = sum(alturas) + len(orden) - 1
        elif self._vacio:
            cuerpo = self._linea("pista") + 2 * HOLGURA + 2 * self._e3
            ancho = max(ancho, 2 * self._uno + self._medir("pista", self._vacio) + 2 * HOLGURA)
        else:
            cuerpo = 0
        alto = 2 * self._uno + self._alto_cabecera + 1 + cuerpo
        return anchos, alturas, ancho, alto

    def _repartir(self, anchos: list[int], pedido: int, ancho: int) -> list[int]:
        """Reparte entre las columnas que estiran lo que el lienzo tiene de más (o de menos)."""
        estiran = [c for c, (_t, _m, estira) in enumerate(self._columnas) if estira]
        sobra = ancho - pedido
        if not estiran or not sobra:
            return list(anchos)
        anchos = list(anchos)
        parte, resto = divmod(sobra, len(estiran))
        for i, col in enumerate(estiran):
            anchos[col] = max(0, anchos[col] + parte + (resto if i == len(estiran) - 1 else 0))
        return anchos

    def _ajustar(self, maqueta, ancho: int | None = None) -> None:
        """Lleva lo dibujado a esa maqueta y a ese ancho de lienzo.

        Desplaza las columnas que cambian de sitio, vuelve a cortar los textos
        de las que cambian de ancho (solo en una lista), pone el fondo de cada
        fila a lo ancho y rehace la tarjeta si cambió de tamaño.
        """
        cv = self.marco
        anchos, _alturas, pedido, alto = maqueta
        if ancho is None:
            real = cv.winfo_width()
            ancho = real if real > 1 else pedido
        anchos = self._repartir(anchos, pedido, ancho)
        x, sitio = [], self._uno
        for col, a in enumerate(anchos):
            izq, der = self._lados(col)
            x.append(sitio + izq)
            sitio += izq + a + der
        for col in range(len(self._columnas)):
            if x[col] != self._x[col]:
                cv.move(f"c{col}", x[col] - self._x[col], 0)
            if (anchos[col] != self._anchos[col] and self._columnas[col][2]
                    and not self._rejilla):
                self._recortar(col, anchos[col])
        self._x, self._anchos = x, anchos
        if ancho != self._ancho:
            for f in self._filas.values():
                if f.fondo is not None:
                    cv.coords(f.fondo, self._uno, f.y, ancho - self._uno, f.y + f.h)
        if (ancho, alto, bool(self.orden)) != self._tarjeta_hecha:
            self._ancho, self._alto = ancho, alto
            self._tarjeta()

    def _recortar(self, col: int, ancho: int) -> None:
        """Vuelve a cortar los textos de esa columna a su ancho nuevo."""
        cabe = ancho - 2 * HOLGURA
        for f in self._filas.values():
            for elemento, columna, entero, _rol, letra in f.textos:
                if columna == col:
                    visto = self._cortar(letra, entero, cabe)
                    if visto != self.marco.itemcget(elemento, "text"):
                        self.marco.itemconfigure(elemento, text=visto)

    # --------------------------------------------------------------- dibujo
    def _cabecera(self) -> None:
        """Los rótulos de las columnas; los coloca `_ajustar()` con el resto de su columna."""
        cv = self.marco
        color, letra = theme.rol_texto("Rotulo.")
        y = self._uno + (self._alto_cabecera - self._linea(letra) - 2 * HOLGURA) // 2 + HOLGURA
        for col, titulo in enumerate(self.cabeceras):
            if titulo:
                cv.create_text(HOLGURA, y, text=theme.rotulo(titulo), anchor="nw",
                               font=self._fuente(letra), fill=color,
                               tags=("cabecera", f"c{col}"))

    def _tarjeta(self) -> None:
        """La tarjeta: esquinas, bordes y relleno, la cabecera en el papel y las líneas.

        Va debajo de todo: las filas se dibujan encima, dentro de su borde, como
        las celdas de la rejilla dentro del relleno de la tarjeta.
        """
        cv = self.marco
        cv.delete("tarjeta")
        ancho, alto, uno = self._ancho, self._alto, self._uno
        self._tarjeta_hecha = (ancho, alto, bool(self.orden))
        pieza, borde = icons.caja(cv, [(theme.LINEA, 0), (theme.SUPERFICIE, 1)], theme.RADIO)
        if pieza is None:
            borde = 0
        etiqueta = ("tarjeta",)
        rect = {"outline": "", "tags": etiqueta}
        cv.create_rectangle(borde, uno, ancho - borde, alto - uno, fill=theme.SUPERFICIE, **rect)
        cv.create_rectangle(uno, borde, ancho - uno, alto - borde, fill=theme.SUPERFICIE, **rect)
        for x0, y0, x1, y1 in ((borde, 0, ancho - borde, uno), (borde, alto - uno, ancho - borde,
                                                                  alto),
                               (0, borde, uno, alto - borde),
                               (ancho - uno, borde, ancho, alto - borde)):
            cv.create_rectangle(x0, y0, x1, y1, fill=theme.LINEA, **rect)
        if pieza is not None:
            ancho_p, alto_p = pieza.width(), pieza.height()
            for de_x, de_y, x, y in ((0, 0, 0, 0), (ancho_p - borde, 0, ancho - borde, 0),
                                     (0, alto_p - borde, 0, alto - borde),
                                     (ancho_p - borde, alto_p - borde, ancho - borde,
                                      alto - borde)):
                cv.create_image(x, y, image=_recorte(cv, pieza, de_x, de_y, borde), anchor="nw",
                                tags=etiqueta)
        abajo = uno + self._alto_cabecera
        cv.create_rectangle(uno, uno, ancho - uno, abajo, fill=theme.PAPEL, **rect)
        cuerpo = self._cuerpo if self.orden else 0
        cv.create_rectangle(uno, abajo, ancho - uno, abajo + 1 + max(0, cuerpo),
                            fill=theme.LINEA_SUAVE, **rect)
        if not self.orden and self._vacio:
            color, letra = theme.rol_texto("Pista.", "Card.")
            cv.create_text(ancho // 2, abajo + 1 + self._e3 + HOLGURA, text=self._vacio,
                           anchor="n", font=self._fuente(letra), fill=color, tags=etiqueta)
        cv.tag_lower("tarjeta")

    def _superficie(self, iid: str) -> str:
        """La superficie de la fila ahora: la del acento si está elegida."""
        if iid == self.elegida:
            return ELEGIDA
        return SUPERFICIE_FILA.get(self._filas[iid].fila.tono, "Card.")

    def _fondo(self, iid: str) -> str:
        """El color del fondo de la fila ahora, con el ratón encima o sin él."""
        superficie = self._superficie(iid)
        fondo = theme.fondo_de(superficie)
        if iid == self._encima and superficie != ELEGIDA:
            return theme.mezcla(fondo, theme.TINTA, MEZCLA_ENCIMA)
        return fondo

    def _dibujar(self, iid: str) -> None:
        """Dibuja una fila en su sitio: su fondo y cada celda."""
        cv, f = self.marco, self._filas[iid]
        y0, alto = f.y, f.h = self._tops[f.pos], self._alturas[f.pos]
        superficie = self._superficie(iid)
        fila = ("fila", f.clave)
        f.fondo = cv.create_rectangle(self._uno, y0, self._ancho - self._uno, y0 + alto,
                                      fill=self._fondo(iid), outline="", tags=(*fila, "fondo"))
        f.textos, f.leidos = [], []
        for col, celda in enumerate(f.fila.celdas):
            x, etiquetas = self._x[col], (*fila, f"c{col}")
            if isinstance(celda, CeldaChip):
                chip = self._chip(celda)
                y = y0 + (alto - chip.alto) // 2
                if chip.pildora is not None:
                    cv.create_image(x, y, image=chip.pildora, anchor="nw",
                                    tags=(*etiquetas, "pildora"))
                else:
                    cv.create_rectangle(x, y, x + chip.ancho, y + chip.alto,
                                        fill=theme.GRIS_FONDO, outline=theme.LINEA,
                                        tags=(*etiquetas, "pildora"))
                if chip.adorno is not None:
                    cv.create_image(x + chip.x_adorno, y + chip.y_adorno, image=chip.adorno,
                                    anchor="nw", tags=(*etiquetas, "adorno"))
                texto = cv.create_text(x + chip.x_texto, y + chip.y_texto, text=celda.texto,
                                       anchor="nw", font=self._fuente("pista"), fill=chip.letra,
                                       tags=(*etiquetas, "texto"))
                f.leidos.append((texto, ""))
            elif isinstance(celda, (CeldaCasilla, CeldaIcono)):
                img = self._imagen(celda, superficie)
                if img is not None:
                    cv.create_image(x + HOLGURA, y0 + (alto - img.height()) // 2, image=img,
                                    anchor="nw", tags=(*etiquetas, "imagen"))
                dice = celda.texto
                if not dice and isinstance(celda, CeldaCasilla):
                    dice = "☑" if celda.marcada else "☐"
                f.leidos.append((None, dice))
            else:
                entero = celda.texto if isinstance(celda, CeldaTexto) else str(celda)
                rol = self._rol(celda, f.fila.tono)
                color, letra = theme.rol_texto(rol, superficie)
                linea = self._linea(letra)
                visto = (self._cortar(letra, entero, self._anchos[col] - 2 * HOLGURA)
                         if self._columnas[col][2] and not self._rejilla else entero)
                texto = cv.create_text(x + HOLGURA, y0 + (alto - linea) // 2, text=visto,
                                       anchor="nw", font=self._fuente(letra), fill=color,
                                       tags=(*etiquetas, "texto"))
                f.textos.append((texto, col, entero, rol, letra))
                f.leidos.append((texto, ""))

    def _pintar(self, iid: str) -> None:
        """Pone a una fila ya dibujada los colores que le tocan ahora (elegida, encima)."""
        f = self._filas.get(iid)
        if f is None or f.fondo is None:
            return
        cv = self.marco
        cv.itemconfigure(f.fondo, fill=self._fondo(iid))
        superficie = self._superficie(iid)
        for elemento, _col, _entero, rol, _letra in f.textos:
            cv.itemconfigure(elemento, fill=theme.rol_texto(rol, superficie)[0])

    def _anillo(self) -> None:
        """El anillo del foco: 2 px del acento dentro de la fila elegida, o de la tabla."""
        cv = self.marco
        cv.delete("anillo")
        if not self._con_foco or self._sin_anillo:
            return
        if self.elegida in self._filas:
            f = self._filas[self.elegida]
            caja = (self._uno, f.y, self._ancho - self._uno, f.y + f.h)
        else:
            caja = (self._uno, self._uno, self._ancho - self._uno, self._alto - self._uno)
        x0, y0, x1, y1 = caja
        g = icons.px(cv, GROSOR_ANILLO)
        for lado in ((x0, y0, x1, y0 + g), (x0, y1 - g, x1, y1), (x0, y0 + g, x0 + g, y1 - g),
                     (x1 - g, y0 + g, x1, y1 - g)):
            cv.create_rectangle(*lado, fill=theme.ACENTO, outline="", tags=("anillo",))

    # --------------------------------------------------------------- lo público
    def poner(self, filas) -> bool:
        """Pone estas filas (`FilaTabla`), dibujando solo las que cambian.

        Las que siguen igual no se tocan; una que cambia se borra y se dibuja de
        nuevo; una que se va se borra; una que llega se dibuja; las que cambian
        de sitio se desplazan. Si una columna cambia de ancho, sus elementos se
        desplazan y, en una lista, los textos de la que estira se vuelven a cortar.

        Args:
            filas: Las filas, de arriba abajo; cada `iid` una vez.

        Returns:
            Si lo que la tabla pide (su ancho y su alto) ha cambiado: llega o se
            va una fila, o una columna que no estira cambia de ancho.
        """
        cv = self.marco
        nuevas = {fila.iid: fila for fila in filas}
        for iid in [i for i in self._filas if i not in nuevas]:
            cv.delete(self._filas.pop(iid).clave)
        por_dibujar = []
        for fila in filas:
            f = self._filas.get(fila.iid)
            if f is None:
                self._creadas += 1
                f = self._filas[fila.iid] = _Fila(fila, f"r{self._creadas}")
            elif f.fila == fila:
                continue
            else:
                cv.delete(f.clave)
                f.fondo = None
            self._medir_fila(f, fila)
            por_dibujar.append(fila.iid)
        self.filas = nuevas
        if self.elegida not in nuevas:
            self.elegida = None
        orden = [fila.iid for fila in filas]
        maqueta = self._maquetar(orden)
        alturas, tops, y = maqueta[1], [], self._uno + self._alto_cabecera + 1
        for alto in alturas:
            tops.append(y)
            y += alto + 1
        for pos, iid in enumerate(orden):
            f = self._filas[iid]
            if f.fondo is not None:
                if alturas[pos] != f.h:         # otra altura: se dibuja de nuevo
                    cv.delete(f.clave)
                    f.fondo = None
                    por_dibujar.append(iid)
                elif tops[pos] != f.y:          # la misma, en otro sitio: se desplaza
                    cv.move(f.clave, 0, tops[pos] - f.y)
                    f.y = tops[pos]
            f.pos = pos
        self.orden, self._alturas, self._tops = orden, alturas, tops
        self._cuerpo = sum(alturas) + len(alturas) - 1 if alturas else 0
        antes_encima = self._encima     # bajo el ratón puede quedar ahora otra fila
        self._encima = self._fila_en(self._raton_y) if self._raton_y is not None else None
        self._ajustar(maqueta)
        for iid in por_dibujar:
            self._dibujar(iid)
        self._anillo()
        for cual in {antes_encima, self._encima}:
            if cual is not None:
                self._pintar(cual)
        pedido = (maqueta[2], maqueta[3])
        cambio = pedido != self._pedido
        if cambio:
            self._pedido = pedido
            cv.configure(width=pedido[0], height=pedido[1])
        return cambio

    def elegir(self, iid: str | None, avisar: bool = True) -> bool:
        """Elige esa fila (o ninguna) y lo cuenta, si `avisar`; repinta dos filas.

        Returns:
            Si la elección se ha hecho: `puede_dejar` puede negarse.
        """
        if iid is not None and iid not in self._filas:
            iid = None
        if iid == self.elegida:
            return True
        if avisar and self.puede_dejar is not None and not self.puede_dejar():
            return False
        antes, self.elegida = self.elegida, iid
        for cual in (antes, iid):
            if cual is not None:
                self._pintar(cual)
        self._anillo()
        if avisar and self.al_elegir is not None:
            self.al_elegir()
        return True

    def leer(self) -> list[tuple[str, ...]]:
        """Devuelve lo que se dibuja, fila a fila: el texto de cada celda.

        Lee los textos de los elementos del lienzo (un texto cortado sale
        cortado); de una casilla o un icono, lo que dicen para quien no los ve.
        """
        cv = self.marco
        return [tuple(str(cv.itemcget(elemento, "text")) if elemento is not None else dice
                      for elemento, dice in self._filas[iid].leidos)
                for iid in self.orden]

    def caja(self, iid: str) -> tuple[int, int, int, int] | None:
        """Devuelve dónde está la fila en el lienzo, `(x0, y0, x1, y1)`, o `None` si no está."""
        f = self._filas.get(iid)
        if f is None:
            return None
        y = self._tops[f.pos]
        return self._uno, y, self._ancho - self._uno, y + self._alturas[f.pos]

    def elementos(self, iid: str) -> tuple[int, ...]:
        """Devuelve los elementos del lienzo de esa fila (vacío si no está)."""
        f = self._filas.get(iid)
        return tuple(self.marco.find_withtag(f.clave)) if f is not None else ()

    # ---------------------------------------------------- ratón, teclado, foco
    def _configurar(self, evento) -> None:
        """El lienzo tiene otro ancho: lo de la derecha se desplaza y la columna que estira cambia."""
        if evento.width > 1 and evento.width != self._ancho:
            self._ajustar(self._maquetar(), evento.width)
            self._anillo()

    def _fila_en(self, y: int) -> str | None:
        """La fila que hay a esa altura del lienzo (la línea de debajo cuenta como suya)."""
        if not self.orden or y < self._tops[0]:
            return None
        pos = sum(1 for arriba in self._tops if arriba <= y) - 1      # la última que empieza antes
        return self.orden[pos] if y < self._tops[pos] + self._alturas[pos] + 1 else None

    def _fila_bajo(self, x: int, y: int) -> str | None:
        """La fila que hay bajo ese punto del lienzo, o `None` si no hay ninguna.

        Cuentan el cuerpo de la fila y no el borde de la tarjeta, la cabecera ni
        la línea entre dos filas (eso no es de ninguna).
        """
        if not self.orden or not self._uno <= x < self._ancho - self._uno:
            return None
        for pos, iid in enumerate(self.orden):
            if self._tops[pos] <= y < self._tops[pos] + self._alturas[pos]:
                return iid
        return None

    def _clic(self, evento) -> None:
        """Un clic en una fila la elige y le da el foco, sin enseñar el anillo.

        Un clic fuera de las filas no hace nada: ni toma el foco ni elige.
        """
        iid = self._fila_bajo(evento.x, evento.y)
        if iid is None:
            return
        self._sin_anillo = True
        self.marco.focus_set()
        self.elegir(iid)
        self._anillo()

    def _mover(self, evento) -> None:
        """El ratón se mueve sobre el lienzo: se tiñe la fila que hay bajo él."""
        self._raton_y = evento.y
        self._pasar(self._fila_en(evento.y))

    def _salir(self) -> None:
        """El ratón sale del lienzo, o la rueda cambia lo que hay debajo: ninguna fila se tiñe.

        Hasta el próximo movimiento no se sabe qué fila queda bajo el ratón.
        """
        self._raton_y = None
        self._pasar(None)

    def _pasar(self, iid: str | None) -> None:
        """El ratón pasa a estar encima de esa fila (o de ninguna)."""
        if iid == self._encima:
            return
        antes, self._encima = self._encima, iid
        for cual in (antes, iid):
            if cual is not None:
                self._pintar(cual)

    def _tecla(self, tecla: str, paso: int | None) -> str:
        """Elige la fila de arriba, la de abajo, una página más allá, la primera o la última.

        Con el teclado el anillo del foco se enseña, aunque la fila no cambie.
        """
        self._sin_anillo = False
        if self.orden:
            if tecla == "<Home>":
                pos = 0
            elif tecla == "<End>":
                pos = len(self.orden) - 1
            elif self.elegida in self.orden:
                pos = self.orden.index(self.elegida) + paso
            else:
                pos = 0
            self.elegir(self.orden[max(0, min(len(self.orden) - 1, pos))])
        self._anillo()
        return "break"

    def _intro(self, _evento=None) -> str:
        """Intro no cambia nada: la fila elegida ya lo está.

        Volver a llamar a `al_elegir` no vale: en «Parejas» recarga el editor y
        descartaría lo escrito sin preguntar. Por eso tampoco pregunta
        `puede_dejar`. Solo impide que el evento llegue a la ventana.
        """
        return "break"

    def _foco(self, tiene: bool) -> None:
        """La tabla gana o pierde el foco: el anillo aparece o se va.

        Al perderlo, la próxima vez que llega el foco (con Tab) el anillo vuelve a
        enseñarse, aunque antes lo hubiera escondido un clic.
        """
        self._con_foco = tiene
        if not tiene:
            self._sin_anillo = False
        self._anillo()

    def _rueda(self, patron: str, evento) -> str:
        """Pasa la rueda al marco de debajo: la tabla no se desplaza, la pantalla sí.

        El `Visor` de la pantalla deja la rueda a lo que se desplaza solo, y un
        lienzo sabe hacerlo; así que el mismo evento (el mismo patrón, y su
        `delta`) se repite en el padre, que no, y el `Visor` hace lo que haría
        con el ratón sobre él. Tras la rueda ninguna fila se tiñe hasta que el
        ratón se mueva: lo que queda bajo él ha cambiado.
        """
        self._salir()
        if patron == "<MouseWheel>":
            self.marco.master.event_generate(patron, delta=evento.delta)
        else:
            self.marco.master.event_generate(patron)
        return "break"
