"""La lista de parejas sobre un único lienzo: una de las tres que mide la etapa 2 (R3).

TEMPORAL, como todo `etapa2_*`: lo borra la tarea 15 de la etapa 2.

Es el prototipo de la tabla de un lienzo (`diseno/notas-tabla.md`), con la API de
`ui.tk_pairs.ListaParejas` (`poner`, `elegir`, `fila`, `filas`, `orden`,
`elegida`). Son elementos de un `tk.Canvas` y ningún widget por fila: el fondo
de cada fila es un rectángulo sobre un lienzo del color de la línea (el píxel
que queda entre dos filas es el separador), la casilla es la imagen de
`icons.casilla()`, el nombre y la ruta son textos con las fuentes del tema
(`theme.fuente_tk()`) y cada chip es una imagen (la píldora, el disco y el
glifo, en SVG) con su palabra encima como texto. Elegir otra fila repinta dos
filas; una anchura nueva y `poner()` repintan todas.

Solo va en un Tk que lee SVG (el 9 del dispositivo): sin él las píldoras no se
dibujan, y `disponible()` lo dice. No es una pantalla: no tiene el hueco mínimo
de las columnas ni celdas que se ajustan a varias líneas, que el prototipo no
necesitó.
"""

from __future__ import annotations

import time

from ui import icons, pair_editor, theme
from ui.tk_pairs import ICONO_MODO, TONOS_FILA

BORDE, CABEZA, FILA, SEP = 1, 28, 40, 1
"""El borde de la tarjeta, la cabecera, una fila y la línea entre filas, en píxeles de diseño."""
PASO = FILA + SEP
IZQ, CASILLA, HUECO = 12, 15, 8
"""El hueco a la izquierda, el lado de la casilla y el hueco entre celdas."""
ALTO_CHIP = 24
ANCHO_INICIAL = 600
"""La anchura que pide el lienzo antes de que la rejilla le dé la suya."""

CHIPS = {  # tipo: (relleno, borde, color del disco), nombres de `theme`
    "": ("GRIS_FONDO", "LINEA", None),
    "Ok.": ("GRIS_FONDO", "LINEA", "OK"),
    "Aviso.": ("GRIS_FONDO", "LINEA", "AVISO"),
    "Peligro.": ("GRIS_FONDO", "LINEA", "PELIGRO"),
    "Acento.": ("GRIS_FONDO", "LINEA", "ACENTO"),
    "Apagado.": ("PAPEL", "BORDE", "TINTA3"),
}
"""Cada tipo de chip: el relleno, el borde y el disco, por el nombre del color del tema."""
SOBRE = {"OK": "SOBRE_OK", "AVISO": "SOBRE_AVISO", "PELIGRO": "SOBRE_PELIGRO",
         "ACENTO": "SOBRE_ACENTO", "TINTA3": "SUPERFICIE"}
"""El color de la tinta que va sobre cada disco."""
GLIFO_TIPO = {"Ok.": "ok", "Aviso.": "alert", "Peligro.": "close", "Acento.": "sync",
              "Apagado.": "clock"}
"""El glifo del disco de cada tipo de chip."""


def disponible(raiz) -> bool:
    """Dice si el intérprete de `raiz` pinta SVG: sin él esta lista no se dibuja."""
    return icons.svg_disponible(raiz)


# --------------------------------------------------------------------- piezas SVG
def _num(x: float) -> str:
    """Un número para un SVG, con tres decimales como mucho."""
    return f"{x:.3f}".rstrip("0").rstrip(".")


def glifo_svg(nombre: str, color: str, ancho: float = 1.6) -> str:
    """Devuelve el glifo de `icons.GLIFOS` como SVG sobre su rejilla de 16."""
    import math
    partes = []
    estilo = (f'fill="none" stroke="{color}" stroke-width="{_num(ancho)}" '
              f'stroke-linecap="square" stroke-linejoin="miter"')
    for p in icons.GLIFOS[nombre]:
        c = p[0]
        if c == "l":
            partes.append(f'<line x1="{p[1]}" y1="{p[2]}" x2="{p[3]}" y2="{p[4]}" {estilo}/>')
        elif c == "p":
            pts = " ".join(f"{x},{y}" for x, y in p[1])
            partes.append(f'<polyline points="{pts}" {estilo}/>')
        elif c == "a":
            _, cx, cy, r, a0, a1 = p
            x0, y0 = cx + r * math.cos(math.radians(a0)), cy + r * math.sin(math.radians(a0))
            x1, y1 = cx + r * math.cos(math.radians(a1)), cy + r * math.sin(math.radians(a1))
            grande = 1 if (a1 - a0) % 360 > 180 else 0
            partes.append(f'<path d="M{_num(x0)} {_num(y0)} A{r} {r} 0 {grande} 1 '
                          f'{_num(x1)} {_num(y1)}" {estilo}/>')
        elif c == "c":
            partes.append(f'<circle cx="{p[1]}" cy="{p[2]}" r="{p[3]}" {estilo}/>')
        elif c == "d":
            partes.append(f'<circle cx="{p[1]}" cy="{p[2]}" r="{_num(ancho / 2)}" '
                          f'fill="{color}"/>')
        elif c == "r":
            partes.append(f'<rect x="{p[1]}" y="{p[2]}" width="{p[3]}" height="{p[4]}" '
                          f'{estilo}/>')
        else:
            raise ValueError(f"primitiva sin SVG en el prototipo: {c}")
    return "".join(partes)


def svg_doc(ancho: float, alto: float, cuerpo: str, k: float) -> str:
    """Devuelve un `<svg>` de `ancho` x `alto` píxeles de diseño, rasterizado a `k` px por px."""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{round(ancho * k)}" '
            f'height="{round(alto * k)}" viewBox="0 0 {_num(ancho)} {_num(alto)}">'
            f'{cuerpo}</svg>')


class Fotos:
    """Las imágenes hechas de SVG de un intérprete, y las medidas de texto que se guardan con ellas.

    Attributes:
        pintadas: Cuántas imágenes distintas se han pedido a Tk.
        ms: Lo que han costado, en milisegundos.
        medidas: Caché de medidas de texto de quien use estas imágenes.
    """

    def __init__(self, raiz, k: float):
        self.raiz, self.k = raiz, k
        self._cache: dict = {}
        self.pintadas = 0
        self.ms = 0.0
        self.medidas: dict = {}

    def get(self, cuerpo: str, ancho: float, alto: float):
        """Devuelve la imagen de ese cuerpo SVG, pintándola solo la primera vez."""
        import tkinter as tk
        doc = svg_doc(ancho, alto, cuerpo, self.k)
        img = self._cache.get(doc)
        if img is None:
            t = time.perf_counter()
            img = tk.PhotoImage(master=self.raiz, data=doc, format="svg")
            self.ms += (time.perf_counter() - t) * 1000
            self.pintadas += 1
            self._cache[doc] = img
        return img


_FOTOS: dict = {}
"""Una caché de imágenes por intérprete: lo que una aplicación real conserva entre pantallas."""


def fotos_de(raiz, k: float) -> Fotos:
    """Devuelve la caché de imágenes del intérprete de `raiz`."""
    f = _FOTOS.get(id(raiz.tk))
    if f is None or f.k != k:
        f = _FOTOS[id(raiz.tk)] = Fotos(raiz, k)
    return f


def chip_svg(ancho_texto: float, tipo: str, icono: str | None, alto: int = ALTO_CHIP):
    """Devuelve el chip SIN su palabra: la píldora y el disco o el icono.

    Returns:
        `(cuerpo SVG, ancho total, x donde empieza el texto)`, todo en píxeles de
        diseño: quien llama pone la palabra en esa `x`.
    """
    relleno, borde, disco = CHIPS.get(tipo, CHIPS[""])
    relleno, borde = getattr(theme, relleno), getattr(theme, borde)
    if disco is not None:
        izq, lado_adorno, hueco, der = 3, 18, 4, 8
    elif icono:
        izq, lado_adorno, hueco, der = 8, 12, 4, 8
    else:
        izq, lado_adorno, hueco, der = 8, 0, 0, 8
    ancho = round(izq + lado_adorno + hueco + ancho_texto + der)
    r = alto / 2
    cuerpo = (f'<rect x="0.5" y="0.5" width="{ancho - 1}" height="{alto - 1}" '
              f'rx="{_num(r - 0.5)}" fill="{relleno}" stroke="{borde}" stroke-width="1"/>')
    y0 = (alto - lado_adorno) / 2
    if disco is not None:
        color = getattr(theme, disco)
        tinta = getattr(theme, SOBRE[disco])
        glifo = "alert" if icono == "warn" else icono or GLIFO_TIPO[tipo]
        cx, cy = izq + 9, alto / 2
        if tipo == "Apagado.":          # solo el aro, con el glifo del color del aro
            cuerpo += (f'<circle cx="{cx}" cy="{cy}" r="8.5" fill="none" stroke="{color}" '
                       f'stroke-width="1"/>')
            tinta_g = color
        else:
            cuerpo += f'<circle cx="{cx}" cy="{cy}" r="9" fill="{color}"/>'
            tinta_g = tinta
        # El glifo mide dos tercios del disco (12 de 18) con el trazo en 2.
        k = 18 / 24
        cuerpo += (f'<g transform="translate({_num(izq + 3)} {_num(cy - 9 + 3)}) '
                   f'scale({_num(k)})">{glifo_svg(glifo, tinta_g, 2.0)}</g>')
        x_texto = izq + lado_adorno + hueco
    elif icono:
        cuerpo += (f'<g transform="translate({izq} {_num(y0)}) scale({_num(12 / 16)})">'
                   f'{glifo_svg(icono, theme.TINTA2, 1.6)}</g>')
        x_texto = izq + lado_adorno + hueco
    else:
        x_texto = izq
    return cuerpo, ancho, x_texto


def mezcla(a: str, b: str, t: float) -> str:
    """Devuelve `a` llevado una fracción `t` hacia `b` (colores hexadecimales)."""
    ra = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    rb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(ra, rb))


# --------------------------------------------------------------------------- la lista
class ListaLienzo:
    """La lista de parejas dibujada sobre un `tk.Canvas`.

    Args:
        parent: Dónde va.
        puede_dejar: Se pregunta antes de cambiar de fila; si dice que no, la
            elección no se hace.
        al_elegir: Lo que se llama después de elegir otra.
    """

    def __init__(self, parent, puede_dejar, al_elegir):
        import tkinter as tk
        self.puede_dejar, self.al_elegir = puede_dejar, al_elegir
        self.raiz = parent.winfo_toplevel()
        self.k = float(self.raiz.tk.call("tk", "scaling")) / 1.3333
        self.fotos = fotos_de(self.raiz, self.k)
        self.filas: dict[str, dict] = {}
        self.orden: list[str] = []
        self.elegida: str | None = None
        self._datos: list = []
        self._ancho = 0
        self._dibujos = 0
        self._sobre: int | None = None
        self._geom: list[tuple[int, int]] = []
        self.cv = tk.Canvas(parent, highlightthickness=0, bd=0, takefocus=True,
                            bg=theme.LINEA, cursor="")
        self.marco = self.cv
        self.f_nombre = theme.fuente_tk(self.cv, "fuerte")
        self.f_apag = theme.fuente_tk(self.cv, "pista")
        self.f_ruta = theme.fuente_tk(self.cv, "mono")
        self.f_ruta_apag = theme.fuente_tk(self.cv, "mono_pequena")
        self.f_chip = theme.fuente_tk(self.cv, "pista")
        self.f_rot = theme.fuente_tk(self.cv, "rotulo")
        self.cv.bind("<Configure>", self._configurar)
        self.cv.bind("<Button-1>", self._clic)
        self.cv.bind("<Motion>", self._mover_raton)
        self.cv.bind("<Leave>", lambda e: self._sobrevolar(None))
        self.cv.bind("<Up>", lambda e: self._flecha(-1))
        self.cv.bind("<Down>", lambda e: self._flecha(1))
        self.cv.bind("<FocusIn>", lambda e: self._anillo())
        self.cv.bind("<FocusOut>", lambda e: self._anillo())

    # ------------------------------------------------------------------ geometría
    def S(self, x: float) -> int:
        """Lleva una medida de diseño a píxeles de pantalla."""
        return round(x * self.k)

    def alto_total(self, n: int) -> int:
        """El alto de la tarjeta con `n` filas, en píxeles de diseño."""
        cuerpo = n * PASO - SEP if n else FILA
        return BORDE + CABEZA + SEP + cuerpo + BORDE

    # ---------------------------------------------------------------------- datos
    def poner(self, filas, del_catalogo: bool = False) -> None:
        """Pone estas filas (`pair_editor.CatalogRow`) en lugar de las de antes."""
        self._datos = list(filas)
        self.filas, self.orden = {}, []
        self._descr = {}
        for f in self._datos:
            tono, nota = pair_editor.row_status(f, del_catalogo)
            sup, tipo = TONOS_FILA[tono]
            if del_catalogo:
                tipo = "Ok."
            self._descr[f.name] = (tono, nota, tipo, f.mode in pair_editor.MIRROR_MODES)
            self.filas[f.name] = {"fila": f, "sup": sup, "apagada": tono == "apagado"}
            self.orden.append(f.name)
        if self.elegida not in self.filas:
            self.elegida = None
        self.cv.configure(height=self.S(self.alto_total(len(self._datos))),
                          width=self.S(ANCHO_INICIAL))
        if self.cv.winfo_width() > 1:
            self._dibujar()
        # si no, el primer <Configure> dibuja, una vez, a la anchura de verdad

    def _configurar(self, ev) -> None:
        if ev.width > 1 and ev.width != self._ancho and self._datos:
            self._dibujar()

    # ---------------------------------------------------------------------- dibujo
    def _fondo_fila(self, iid: str, i: int) -> str:
        tono = self._descr[iid][0]
        if iid == self.elegida:
            return theme.ACENTO_SUAVE
        base = {"aviso": theme.AVISO_FONDO, "peligro": theme.PELIGRO_FONDO}.get(
            tono, theme.SUPERFICIE)
        return mezcla(base, theme.TINTA, 0.045) if i == self._sobre else base

    def _tinta(self, iid: str, que: str) -> str:
        tono = self._descr[iid][0]
        if tono == "apagado":
            return theme.TINTA3
        if tono == "peligro" and iid != self.elegida:
            return theme.PELIGRO
        return theme.TINTA if que == "nombre" else theme.TINTA2

    def _medir(self, fuente, texto: str) -> int:
        clave = (str(fuente), texto)
        v = self.fotos.medidas.get(clave)
        if v is None:
            v = self.fotos.medidas[clave] = fuente.measure(texto)
        return v

    def _chip_pieza(self, texto: str, tipo: str, icono: str | None):
        """Devuelve `(imagen, x del texto, ancho)` de un chip, en píxeles, hecha una vez."""
        clave = ("chip", texto, tipo, icono)
        v = self.fotos.medidas.get(clave)
        if v is None:
            cuerpo, ancho, x_t = chip_svg(self._medir(self.f_chip, texto) / self.k, tipo,
                                          icono, ALTO_CHIP)
            v = self.fotos.medidas[clave] = (self.fotos.get(cuerpo, ancho, ALTO_CHIP),
                                             self.S(x_t), self.S(ancho))
        return v

    def _chip(self, texto: str, tipo: str, icono: str | None, x: int, yc: int, tag: str) -> int:
        """Pone un chip: la imagen de la píldora y encima su palabra."""
        cv = self.cv
        img, x_t, ancho = self._chip_pieza(texto, tipo, icono)
        cv.create_image(x, yc, image=img, anchor="w", tags=(tag, "d"))
        color = theme.TINTA3 if tipo == "Apagado." else theme.TINTA
        cv.create_text(x + x_t, yc, text=texto, anchor="w", font=self.f_chip, fill=color,
                       tags=(tag, "d"))
        return ancho

    def _elidir(self, texto: str, fuente, ancho_px: int) -> str:
        if fuente.measure(texto) <= ancho_px:
            return texto
        lo, hi = 0, len(texto)
        while lo < hi:
            m = (lo + hi + 1) // 2
            if fuente.measure(texto[:m] + "…") <= ancho_px:
                lo = m
            else:
                hi = m - 1
        return texto[:lo] + "…"

    def _dibujar(self) -> None:
        """Dibuja la tarjeta entera a la anchura que tiene el lienzo ahora."""
        cv, S = self.cv, self.S
        W = cv.winfo_width() if cv.winfo_width() > 1 else S(ANCHO_INICIAL)
        self._ancho = W
        self._dibujos += 1
        cv.delete("d")
        ancho_nombre = max([self._medir(self.f_nombre, f.name) for f in self._datos] or [0])
        chips_modo = chips_estado = 0
        for f in self._datos:
            tono, nota, tipo, espejo = self._descr[f.name]
            chips_modo = max(chips_modo, self._chip_pieza(
                f.mode, "Peligro." if espejo else "", ICONO_MODO.get(f.mode))[2] / self.k)
            chips_estado = max(chips_estado, self._chip_pieza(nota, tipo, None)[2] / self.k)
        x_chk = S(BORDE + IZQ)
        x_nombre = x_chk + S(CASILLA + HUECO + HUECO)
        x_ruta = x_nombre + ancho_nombre + S(HUECO + 4)
        x_estado = W - S(BORDE + IZQ) - S(chips_estado)
        x_modo = x_estado - S(HUECO) - S(chips_modo) - S(HUECO)
        self._cols = {"chk": x_chk, "nombre": x_nombre, "ruta": x_ruta, "modo": x_modo,
                      "estado": x_estado}
        cv.create_rectangle(0, 0, W, S(BORDE + CABEZA), fill=theme.PAPEL, outline="",
                            tags=("d",))
        yh = S(BORDE + CABEZA / 2)
        for x, titulo in ((x_nombre, "Pareja"), (x_ruta, "Local ↔ remoto"),
                          (x_modo, "Modo"), (x_estado, "Estado")):
            cv.create_text(x, yh, text=theme.rotulo(titulo), anchor="w", font=self.f_rot,
                           fill=theme.TINTA3, tags=("d",))
        y = S(BORDE + CABEZA)
        cv.create_line(0, y, W, y, fill=theme.LINEA, tags=("d",))
        self._geom = []
        casillas = {en_pen: icons.casilla(cv, "marcada" if en_pen else "vacia", margen=0)
                    for en_pen in (True, False)}
        for i, f in enumerate(self._datos):
            tono, nota, tipo, espejo = self._descr[f.name]
            y0 = S(BORDE + CABEZA + SEP + i * PASO)
            y1 = y0 + S(FILA)
            yc = (y0 + y1) // 2
            tag = f"f{i}"
            cv.create_rectangle(0, y0, W, y1, fill=self._fondo_fila(f.name, i), outline="",
                                tags=(tag, f"bg{i}", "d"))
            cv.create_image(x_chk, yc, image=casillas[f.en_pen], anchor="w",
                            tags=(tag, f"chk{i}", "d"))
            apag = tono == "apagado"
            cv.create_text(x_nombre, yc, text=f.name, anchor="w",
                           font=self.f_apag if apag else self.f_nombre,
                           fill=self._tinta(f.name, "nombre"), tags=(tag, f"nom{i}", "d"))
            fr = self.f_ruta_apag if apag else self.f_ruta
            hueco = x_modo - S(HUECO) - x_ruta
            cv.create_text(x_ruta, yc, text=self._elidir(f"{f.local} ↔ {f.remote}", fr, hueco),
                           anchor="w", font=fr, fill=self._tinta(f.name, "ruta"),
                           tags=(tag, f"rut{i}", "d"))
            self._chip(f.mode, "Peligro." if espejo else "", ICONO_MODO.get(f.mode),
                       x_modo, yc, tag)
            self._chip(nota, tipo, None, x_estado, yc, tag)
            self._geom.append((y0, y1))
        yb = S(self.alto_total(len(self._datos)))
        cv.create_rectangle(0, 0, W - 1, yb - 1, outline=theme.LINEA, width=1,
                            tags=("borde", "d"))
        self._esquinas(W, yb)
        self._anillo()

    def _esquinas(self, W: int, H: int) -> None:
        """Las cuatro esquinas redondeadas de la tarjeta, como cuatro imágenes pequeñas."""
        cv, r = self.cv, 4
        fuera, borde = theme.PAPEL, theme.LINEA      # fuera de la tarjeta: el papel
        base = (f'<path d="M0 0 H{r} A{r} {r} 0 0 0 0 {r} Z" fill="{fuera}"/>'
                f'<path d="M{r} 0.5 A{r - 0.5} {r - 0.5} 0 0 0 0.5 {r}" fill="none" '
                f'stroke="{borde}" stroke-width="1"/>')
        for dx, dy, giro in ((0, 0, 0), (1, 0, 90), (1, 1, 180), (0, 1, 270)):
            cuerpo = f'<g transform="rotate({giro} {r / 2} {r / 2})">{base}</g>'
            img = self.fotos.get(cuerpo, r, r)
            cv.create_image(dx * (W - self.S(r)), dy * (H - self.S(r)), image=img,
                            anchor="nw", tags=("esquina", "d"))

    # ------------------------------------------------- elegir, sobrevolar y el foco
    def _pintar_fila(self, i: int) -> None:
        iid = self.orden[i]
        cv = self.cv
        cv.itemconfigure(f"bg{i}", fill=self._fondo_fila(iid, i))
        cv.itemconfigure(f"nom{i}", fill=self._tinta(iid, "nombre"))
        cv.itemconfigure(f"rut{i}", fill=self._tinta(iid, "ruta"))

    def _anillo(self) -> None:
        """El anillo del foco: un marco del acento dentro de la fila elegida."""
        cv = self.cv
        cv.delete("anillo")
        try:
            con_foco = cv.focus_get() is cv
        except Exception:                               # noqa: BLE001
            con_foco = False
        if self.elegida is None or not con_foco or not self._ancho or not self._geom:
            return
        y0, y1 = self._geom[self.orden.index(self.elegida)]
        cv.create_rectangle(1, y0, self._ancho - 2, y1 - 1, outline=theme.ACENTO, width=2,
                            tags=("anillo", "d"))
        cv.tag_raise("esquina")

    def elegir(self, name: str | None, avisar: bool = True) -> bool:
        """Elige esa pareja (o ninguna) y lo cuenta, si `avisar`; repinta dos filas.

        Returns:
            Si la elección se ha hecho: `puede_dejar` puede negarse.
        """
        if name is not None and name not in self.filas:
            name = None
        if name == self.elegida:
            return True
        if avisar and not self.puede_dejar():
            return False
        antes, self.elegida = self.elegida, name
        for x in (antes, name):
            if x in self.filas and self._geom:
                self._pintar_fila(self.orden.index(x))
        self._anillo()
        if avisar:
            self.al_elegir()
        return True

    def fila(self):
        """Devuelve la `CatalogRow` elegida, o `None`."""
        return self.filas[self.elegida]["fila"] if self.elegida in self.filas else None

    def _fila_en(self, y: int) -> int | None:
        if not self._geom:
            return None
        y0 = self.S(BORDE + CABEZA + SEP)
        if y < y0:
            return None
        i = int((y - y0) // self.S(PASO))
        return i if 0 <= i < len(self.orden) else None

    def _clic(self, ev) -> None:
        self.cv.focus_set()
        i = self._fila_en(ev.y)
        if i is not None:
            self.elegir(self.orden[i])

    def _flecha(self, paso: int) -> str:
        if self.orden:
            i = self.orden.index(self.elegida) + paso if self.elegida in self.orden else 0
            self.elegir(self.orden[max(0, min(len(self.orden) - 1, i))])
        return "break"

    def _mover_raton(self, ev) -> None:
        self._sobrevolar(self._fila_en(ev.y))

    def _sobrevolar(self, i: int | None) -> None:
        if i == self._sobre:
            return
        antes, self._sobre = self._sobre, i
        for x in (antes, i):
            if x is not None and x < len(self.orden) and self._geom:
                self._pintar_fila(x)

    # -------------------------------------------------------------------- lo que se ve
    def leer(self) -> list[tuple[str, str, str, str]]:
        """Devuelve lo que se DIBUJA, fila a fila: nombre, ruta, modo y estado.

        Lee los textos de los elementos del lienzo, no el modelo.
        """
        salida = []
        for i in range(len(self.orden)):
            cv = self.cv
            textos = [cv.itemcget(it, "text") for it in cv.find_withtag(f"f{i}")
                      if cv.type(it) == "text"]
            salida.append(tuple(str(t) for t in textos))
        return salida

    def detalle(self) -> dict:
        """Cuentas propias de esta lista, para el informe."""
        return {"elementos": len(self.cv.find_all()), "imagenes_svg": self.fotos.pintadas,
                "svg_ms": round(self.fotos.ms, 2), "dibujos": self._dibujos}
