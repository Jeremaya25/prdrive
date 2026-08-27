#!/usr/bin/env python3
"""
icons.py — Los iconos del rediseño, dibujados aquí mismo.

El diseño pide iconos de trazo sobre rejilla de 16 y dice explícitamente «sin
emoji»: un ✓ o un ⚠ salen con la fuente de emoji del sistema, en color, de un
tamaño que no controlamos y distinto en cada equipo. Como el proyecto no tiene
dependencias —nada de Pillow, nada de cairosvg—, la única salida es pintarlos, y
como Tk 8.6 no sabe leer SVG, se pintan a mano.

Cada icono es una lista de primitivas (segmentos, arcos, círculos, rectángulos)
en el sistema de coordenadas del artboard, y `_rasterizar()` las convierte en
píxeles midiendo, para cada píxel, la distancia a la tinta más cercana. Esa
distancia da el suavizado gratis y a cualquier tamaño: no hay que redibujar el
icono para 20 px, se pide con `size=20`.

**El fondo se pasa y no se elige**: `PhotoImage.put()` no admite transparencia,
así que el icono se compone contra el color sobre el que va a caer. No es una
limitación cara porque toda la paleta es plana —papel, superficie, acento— y ese
color se sabe siempre en el sitio donde se pone el icono.

Nada de aquí puede tumbar la interfaz: `get()` devuelve None si algo falla, y
quien lo llama pinta el texto sin icono. Un adorno no puede impedir que se abra
la ventana.
"""

from __future__ import annotations

import math

# Anchura de trazo del diseño, en unidades de la rejilla de 16.
TRAZO = 1.6

# ---------------------------------------------------------------------------
# Las primitivas
#
#   ("l",  x1, y1, x2, y2)          segmento
#   ("p",  [(x, y), ...])           polilínea
#   ("a",  cx, cy, r, a0, a1)       arco, grados que CRECEN de a0 a a1
#   ("c",  cx, cy, r)               círculo
#   ("r",  x, y, w, h)              rectángulo de trazo
#   ("fr", x, y, w, h)              rectángulo relleno
#   ("rr", x, y, w, h, radio)       rectángulo relleno de esquinas redondeadas
#
# Los ángulos van en el sentido de la pantalla (la y crece hacia abajo), que es
# el mismo en el que los escribe SVG: 0° a la derecha, 90° abajo.
# ---------------------------------------------------------------------------

GLIFOS: dict[str, list[tuple]] = {
    # Los dos sentidos de bisync, que es también la marca de la aplicación.
    "sync": [("a", 8, 8, 5, 180, 315), ("l", 11.5, 4.5, 13, 6),
             ("p", [(13, 2.5), (13, 6), (9.5, 6)]),
             ("a", 8, 8, 5, 0, 135), ("l", 4.5, 11.5, 3, 10),
             ("p", [(3, 13.5), (3, 10), (6.5, 10)])],
    "dispositivo": [("r", 5.5, 2.5, 5, 8), ("p", [(6.5, 10.5), (6.5, 13.5), (9.5, 13.5),
                                          (9.5, 10.5)]),
            ("l", 7, 2.5, 7, 1), ("l", 9, 2.5, 9, 1)],
    "nas": [("r", 2, 3, 12, 4), ("r", 2, 9, 12, 4), ("d", 4.5, 5), ("d", 4.5, 11)],
    # Los tres modos: los dos sentidos, y cada uno por su cuenta.
    "both": [("l", 5, 13.5, 5, 3), ("p", [(2.5, 5.5), (5, 3), (7.5, 5.5)]),
             ("l", 11, 2.5, 11, 13), ("p", [(8.5, 10.5), (11, 13), (13.5, 10.5)])],
    "up": [("l", 8, 13, 8, 3), ("p", [(4, 7), (8, 3), (12, 7)])],
    "down": [("l", 8, 3, 8, 13), ("p", [(4, 9), (8, 13), (12, 9)])],
    "ok": [("p", [(3, 8.5), (6.5, 12), (13, 4.5)])],
    "warn": [("p", [(8, 2.5), (14.5, 13.5), (1.5, 13.5), (8, 2.5)]),
             ("l", 8, 6.4, 8, 9.7), ("d", 8, 11.7)],
    "clock": [("c", 8, 8, 6), ("p", [(8, 4.5), (8, 8), (10.5, 9.5)])],
    "gear": [("c", 8, 8, 2.4),
             ("l", 8, 1.5, 8, 3.5), ("l", 8, 12.5, 8, 14.5),
             ("l", 14.5, 8, 12.5, 8), ("l", 3.5, 8, 1.5, 8),
             ("l", 12.6, 3.4, 11.2, 4.8), ("l", 4.8, 11.2, 3.4, 12.6),
             ("l", 12.6, 12.6, 11.2, 11.2), ("l", 4.8, 4.8, 3.4, 3.4)],
    "grid": [("r", 2.5, 2.5, 4.5, 4.5), ("r", 9, 2.5, 4.5, 4.5),
             ("r", 2.5, 9, 4.5, 4.5), ("r", 9, 9, 4.5, 4.5)],
    "plug": [("r", 4, 6, 8, 7), ("l", 6.5, 6, 6.5, 2.5), ("l", 9.5, 6, 9.5, 2.5)],
    "doctor": [("c", 8, 8, 6), ("l", 8, 5, 8, 11), ("l", 5, 8, 11, 8)],
    "flag": [("p", [(4, 14), (4, 2.5), (12, 2.5), (10, 5.5), (12, 8.5), (4, 8.5)])],
    # El ojo: dos arcos de una circunferencia grande que se cortan en las puntas.
    "eye": [("a", 8, 10.44, 6.94, 200.6, 339.4), ("a", 8, 5.56, 6.94, 20.6, 159.4),
            ("c", 8, 8, 1.7)],
    "reload": [("a", 8, 8, 5, 0, 315), ("p", [(13, 1.5), (13, 5), (9.5, 5)])],
    "edit": [("p", [(11.5, 2.5), (13.5, 4.5), (5.5, 12.5), (2.5, 13.5),
                    (3.5, 10.5), (11.5, 2.5)])],
    "trash": [("l", 3.5, 4.5, 12.5, 4.5),
              ("p", [(6.5, 4.5), (6.5, 2.5), (9.5, 2.5), (9.5, 4.5)]),
              ("p", [(5, 4.5), (5.7, 13.5), (10.3, 13.5), (11, 4.5)])],
    "plus": [("l", 8, 3, 8, 13), ("l", 3, 8, 13, 8)],
    "back": [("l", 13, 8, 3, 8), ("p", [(7, 4), (3, 8), (7, 12)])],
    "file": [("p", [(4, 1.5), (9, 1.5), (12, 4.5), (12, 14.5), (4, 14.5), (4, 1.5)]),
             ("p", [(9, 1.5), (9, 5), (12, 5)])],
}

# El icono de la aplicación: campo, los dos brazos del ciclo y el cuerpo del dispositivo.
# Rejilla de 64 y capas de colores distintos, por eso no cabe en GLIFOS.
CAMPO = "#2E4763"
MARCA = "#FAF9F7"
AMBAR = "#E0A34A"


def _capas_marca(size: int) -> list[tuple[str, float, list[tuple]]]:
    """Las capas del icono. A 16 px se simplifica, como manda el diseño: trazo
    más grueso, sin puntas de flecha y con el cuerpo entero. Lo que queda es un
    anillo partido, que sigue leyéndose como «sincroniza».

    El ORDEN es el del diseño y no es decorativo: las dos puntas van después de
    los dos arcos. Agrupadas por color —arco blanco y punta blanca juntos— el
    arco ámbar, que se pinta después, se come media punta blanca."""
    campo = [(CAMPO, 0.0, [("rr", 0, 0, 64, 64, 13)])]
    if size <= 20:
        return campo + [
            (MARCA, 7.0, [("a", 32, 32, 21, -90, 90)]),
            (AMBAR, 7.0, [("a", 32, 32, 21, 90, 270)]),
            (MARCA, 0.0, [("fr", 27, 22, 10, 20)]),
        ]
    return campo + [
        (MARCA, 5.5, [("a", 32, 32, 21, -90, 90)]),
        (AMBAR, 5.5, [("a", 32, 32, 21, 90, 270)]),
        (MARCA, 5.5, [("p", [(27, 6.5), (32, 11), (27, 15.5)])]),
        (AMBAR, 5.5, [("p", [(37, 57.5), (32, 53), (37, 48.5)])]),
        (MARCA, 0.0, [("fr", 27, 22, 10, 15), ("fr", 29.5, 37, 5, 5.5)]),
    ]


# ---------------------------------------------------------------------------
# El rasterizador
# ---------------------------------------------------------------------------

def _dist_segmento(x: float, y: float, x1: float, y1: float, x2: float, y2: float,
                   semi: float) -> float:
    """Distancia con signo a un segmento de trazo `2*semi`, con extremos planos.

    Un segmento con extremo plano es un rectángulo girado, así que se lleva el
    punto al sistema del propio segmento —cuánto avanza y cuánto se separa— y ahí
    ya es la distancia a una caja. Los extremos cuadrados y los ingletes NO se
    hacen aquí: los pone `_expandir()` antes de rasterizar, moviendo los puntos."""
    dx, dy = x2 - x1, y2 - y1
    largo = math.hypot(dx, dy)
    if largo == 0:                        # un punto es un cuadradito
        return max(abs(x - x1), abs(y - y1)) - semi
    ux, uy = dx / largo, dy / largo
    px, py = x - x1, y - y1
    a = abs((px * ux + py * uy) - largo / 2) - largo / 2
    b = abs(px * -uy + py * ux) - semi
    if a > 0 and b > 0:
        return math.hypot(a, b)
    return max(a, b)


def _dist_triangulo(x: float, y: float, p0, p1, p2) -> float:
    """Distancia con signo a un triángulo relleno: negativa dentro.

    Solo se usa para las cuñas de los ingletes, que son siempre triángulos."""
    lados = ((p0, p1), (p1, p2), (p2, p0))
    fuera = min(_dist_segmento(x, y, *a, *b, 0.0) for a, b in lados)
    signos = [(b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])
              for a, b in lados]
    dentro = all(s >= 0 for s in signos) or all(s <= 0 for s in signos)
    return -fuera if dentro else fuera


def _dist_arco(x: float, y: float, cx: float, cy: float, r: float,
               a0: float, a1: float) -> float:
    """Distancia al arco: al propio anillo si el punto cae dentro del sector, y
    si no, a la punta más cercana —que es lo que hace que un arco no se coma la
    pantalla entera—."""
    dx, dy = x - cx, y - cy
    rho = math.hypot(dx, dy)
    ang = math.degrees(math.atan2(dy, dx))
    while ang < a0:
        ang += 360
    if ang <= a1:
        return abs(rho - r)
    return min(math.hypot(x - (cx + r * math.cos(math.radians(a))),
                          y - (cy + r * math.sin(math.radians(a))))
               for a in (a0, a1))


def _sdf_caja(x: float, y: float, rx: float, ry: float,
              w: float, h: float) -> float:
    """Distancia con signo a un rectángulo: negativa dentro."""
    dx = max(rx - x, x - (rx + w))
    dy = max(ry - y, y - (ry + h))
    if dx > 0 and dy > 0:
        return math.hypot(dx, dy)
    return max(dx, dy)


def _sdf(prim: tuple, x: float, y: float, semi: float) -> float:
    """Distancia con signo a la tinta de una primitiva. `semi` es la mitad del
    trazo; los rellenos van con semi = 0 y su propia distancia con signo."""
    clase = prim[0]
    if clase == "s":                       # segmento ya alargado por _expandir()
        return _dist_segmento(x, y, *prim[1:], semi)
    if clase == "t":                       # cuña de inglete
        return _dist_triangulo(x, y, *prim[1:])
    if clase == "a":
        return _dist_arco(x, y, *prim[1:]) - semi
    if clase == "c":
        return abs(math.hypot(x - prim[1], y - prim[2]) - prim[3]) - semi
    if clase == "r":
        return abs(_sdf_caja(x, y, *prim[1:])) - semi
    if clase == "fr":
        return _sdf_caja(x, y, *prim[1:])
    if clase == "rr":
        _, rx, ry, w, h, rad = prim
        return _sdf_caja(x, y, rx + rad, ry + rad, w - 2 * rad, h - 2 * rad) - rad
    raise ValueError(f"primitiva desconocida: {clase}")


def _rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


# ---------------------------------------------------------------------------
# Extremos cuadrados e ingletes
#
# El diseño dibuja todo con `stroke-linecap="square"` y `stroke-linejoin="miter"`,
# y a trazo grueso eso no es un detalle: las puntas de flecha del icono son dos
# segmentos en ángulo recto, y sin inglete salen como un rombo en vez de como una
# punta. Se resuelve moviendo puntos —alargar las puntas libres, meter un
# triangulito en cada esquina— y se hace UNA vez por capa, no por píxel: son
# cuatro cuentas frente a los 65.536 puntos de un icono de 256.
# ---------------------------------------------------------------------------

# El mismo tope que trae SVG: sin él, una esquina muy cerrada dispara una aguja.
MITER_LIMITE = 4.0


def _unitario(dx: float, dy: float):
    largo = math.hypot(dx, dy)
    return None if largo == 0 else (dx / largo, dy / largo)


def _alargar(x1, y1, x2, y2, ini: float, fin: float):
    """El segmento con sus puntas corridas hacia fuera: el extremo cuadrado."""
    u = _unitario(x2 - x1, y2 - y1)
    if u is None:
        return x1, y1, x2, y2
    return (x1 - u[0] * ini, y1 - u[1] * ini, x2 + u[0] * fin, y2 + u[1] * fin)


def _inglete(a, b, c, semi: float) -> list[tuple]:
    """Las cuñas que rellenan la esquina de fuera en `b`. Vacío si no hace falta.

    `bis` sale de `u1 - u2` y apunta siempre al exterior del giro; la punta cae a
    `semi / sen(mitad del ángulo)`, que es la definición del inglete.

    Lo que hay que rellenar es el CUADRILÁTERO b-A-T-C, no el triángulo A-T-C:
    los dos rectángulos del trazo se cruzan en `b` y dejan sin cubrir también el
    trozo entre el vértice y la línea A-C. Con solo el triángulo, la punta de
    flecha salía separada del resto por una rendija."""
    u1 = _unitario(b[0] - a[0], b[1] - a[1])
    u2 = _unitario(c[0] - b[0], c[1] - b[1])
    if u1 is None or u2 is None:
        return []
    dx, dy = u1[0] - u2[0], u1[1] - u2[1]
    largo = math.hypot(dx, dy)
    if largo < 1e-9:                       # tramo recto: no hay esquina
        return []
    bis = (dx / largo, dy / largo)
    seno = math.sqrt(max(1e-9, 1 - (largo / 2) ** 2))
    punta = min(semi / seno, semi * MITER_LIMITE)

    def normal(u):
        """La perpendicular a `u` que mira al mismo lado que la bisectriz."""
        n = (-u[1], u[0])
        return n if n[0] * bis[0] + n[1] * bis[1] >= 0 else (u[1], -u[0])

    n1, n2 = normal(u1), normal(u2)
    esquina1 = (b[0] + n1[0] * semi, b[1] + n1[1] * semi)
    esquina2 = (b[0] + n2[0] * semi, b[1] + n2[1] * semi)
    vertice = (b[0] + bis[0] * punta, b[1] + bis[1] * punta)
    return [("t", b, esquina1, vertice), ("t", b, vertice, esquina2)]


def _expandir(prims, semi: float) -> list[tuple]:
    """Las primitivas de un glifo listas para rasterizar con este grosor."""
    salida: list[tuple] = []
    for prim in prims:
        clase = prim[0]
        if clase == "l":
            salida.append(("s", *_alargar(*prim[1:], semi, semi)))
        elif clase == "d":                 # un punto: un segmento de largo cero
            salida.append(("s", prim[1], prim[2], prim[1], prim[2]))
        elif clase == "p":
            puntos = prim[1]
            # Una polilínea cerrada no tiene puntas libres, pero sí una esquina
            # más: la del punto donde se cierra.
            cerrada = puntos[0] == puntos[-1]
            ultimo = len(puntos) - 2
            for i in range(len(puntos) - 1):
                ini = 0.0 if (i or cerrada) else semi
                fin = semi if (i == ultimo and not cerrada) else 0.0
                salida.append(("s", *_alargar(*puntos[i], *puntos[i + 1], ini, fin)))
            esquinas = list(range(1, len(puntos) - 1)) + ([0] if cerrada else [])
            for i in esquinas:
                salida += _inglete(puntos[i - 1] if i else puntos[-2], puntos[i],
                                   puntos[i + 1] if i else puntos[1], semi)
        else:
            salida.append(prim)
    return salida


def _capas_rgba(capas, caja: float, size: int) -> list[list[tuple]]:
    """Las capas compuestas entre sí sobre transparente: filas de (r, g, b, a).

    Se recorre píxel a píxel midiendo la distancia a la tinta: dentro del trazo
    la cobertura es 1, fuera 0, y en el borde el valor intermedio que suaviza el
    dibujo. Es caro por píxel y barato de verdad: 16×16 son 256 puntos.

    El alfa se conserva en vez de aplanarlo aquí porque hay dos destinos con
    necesidades distintas: `PhotoImage` no sabe de transparencia y quiere el
    dibujo ya compuesto contra un color, y un `.ico` la necesita —si no, las
    esquinas redondeadas del icono saldrían recortadas sobre un cuadrado—."""
    unidad = caja / size                   # cuánto mide un píxel en la rejilla
    colores = [(_rgb(color), ancho / 2, _expandir(prims, ancho / 2))
               for color, ancho, prims in capas]
    filas = []
    for py in range(size):
        y = (py + 0.5) * unidad
        fila = []
        for px in range(size):
            x = (px + 0.5) * unidad
            r = g = b = 0
            acumulado = 0.0
            for (cr, cg, cb), semi, prims in colores:
                sd = min(_sdf(p, x, y, semi) for p in prims)
                alfa = min(1.0, max(0.0, 0.5 - sd / unidad))
                if alfa <= 0:
                    continue
                # 'source over' con alfa sin premultiplicar.
                nuevo = alfa + acumulado * (1 - alfa)
                mezcla = acumulado * (1 - alfa) / nuevo
                r = round(cr * (1 - mezcla) + r * mezcla)
                g = round(cg * (1 - mezcla) + g * mezcla)
                b = round(cb * (1 - mezcla) + b * mezcla)
                acumulado = nuevo
            fila.append((r, g, b, acumulado))
        filas.append(fila)
    return filas


def _rasterizar(capas, caja: float, size: int, fondo: str) -> str:
    """Lo mismo, ya aplanado contra `fondo` y en el texto que entiende
    `PhotoImage.put()`."""
    fr, fg, fb = _rgb(fondo)
    salida = []
    for fila in _capas_rgba(capas, caja, size):
        celdas = []
        for r, g, b, a in fila:
            celdas.append(f"#{round(r * a + fr * (1 - a)):02x}"
                          f"{round(g * a + fg * (1 - a)):02x}"
                          f"{round(b * a + fb * (1 - a)):02x}")
        salida.append("{" + " ".join(celdas) + "}")
    return " ".join(salida)


# ---------------------------------------------------------------------------
# La cara pública
# ---------------------------------------------------------------------------

# Las imágenes hay que guardarlas: Tk no se queda con ellas y una PhotoImage sin
# referencias en Python desaparece del widget. La clave lleva el intérprete de Tk
# porque una imagen pertenece al suyo, y aquí se abren varios a lo largo de una
# sesión (la ventana principal, luego el asistente); guardar el intérprete en el
# valor evita además que `id()` se reutilice mientras la caché siga viva.
_CACHE: dict[tuple, tuple] = {}


def px(widget, medida: int) -> int:
    """Una medida del diseño llevada a los píxeles de esta pantalla.

    Los iconos son mapas de bits y Tk no los escala, pero sí escala las fuentes:
    en una pantalla densa un icono de 15 px fijos quedaría de juguete al lado de
    su texto. `tk scaling` son píxeles por punto, y 1,333 es el valor a 96 ppp,
    que es la densidad para la que están pensadas las medidas del diseño."""
    try:
        escala = float(widget.tk.call("tk", "scaling"))
    except Exception:
        escala = 1.3333
    return max(1, round(medida * escala / 1.3333))


def _dibujar(widget, clave: tuple, capas, caja: float, size: int, fondo: str):
    interp = widget.tk
    ficha = (id(interp), *clave)
    guardado = _CACHE.get(ficha)
    if guardado is not None and guardado[0] is interp:
        return guardado[1]
    import tkinter as tk
    img = tk.PhotoImage(master=widget, width=size, height=size)
    img.put(_rasterizar(capas, caja, size, fondo))
    _CACHE[ficha] = (interp, img)
    return img


def get(widget, nombre: str, size: int = 16, color: str = "#3B362F",
        fondo: str = "#FAF9F7"):
    """El icono `nombre` al tamaño del diseño, ya compuesto contra `fondo`.

    Devuelve None si no se puede pintar —un nombre que no existe, un Tk que se
    está cerrando—, y quien llama se queda sin icono pero con su texto."""
    try:
        real = px(widget, size)
        capas = [(color, TRAZO, GLIFOS[nombre])]
        return _dibujar(widget, (nombre, real, color, fondo), capas, 16.0, real, fondo)
    except Exception:
        return None


# La casilla de marcar del diseño: cuadrado de 15, azul con el visto en blanco
# cuando está marcada. Se pinta aquí porque el indicador de clam dibuja una
# especie de aspa, y el diseño pide un visto.
_CASILLAS = {
    #  estado  -> (relleno, borde, color del visto)
    "marcada": ("#3D5A80", "#3D5A80", "#FFFFFF"),
    "vacia": ("#FFFFFF", "#B9B2A6", None),
    "apagada": ("#F6F4F0", "#E4E0D8", None),
    "apagada-marcada": ("#C9C3B8", "#C9C3B8", "#F6F4F0"),
}
_VISTO = [("p", [(3.5, 8.5), (6.5, 11.5), (12.5, 4.5)])]


def casilla(widget, estado: str, size: int = 15, margen: int = 7):
    """La casilla de marcar, con `margen` píxeles en blanco a su derecha.

    Ese margen es lo que separa el cuadrado de su texto: el elemento de imagen de
    ttk no entiende de `indicatormargin`, así que el hueco se pinta —mejor dicho,
    NO se pinta— dentro de la propia imagen: una PhotoImage recién creada es
    transparente y solo se escribe el cuadrado, así que por el resto se ve el
    fondo que haya detrás, sea papel o tarjeta."""
    import tkinter as tk
    relleno, borde, visto = _CASILLAS[estado]
    lado, hueco = px(widget, size), px(widget, margen)
    ficha = (id(widget.tk), "@casilla", estado, lado, hueco)
    guardado = _CACHE.get(ficha)
    if guardado is not None and guardado[0] is widget.tk:
        return guardado[1]

    capas = [(borde, 1.0, [("r", 0.5, 0.5, 15, 15)])]
    if visto:
        capas.append((visto, 2.4, _VISTO))
    img = tk.PhotoImage(master=widget, width=lado + hueco, height=lado)
    img.put(_rasterizar(capas, 16.0, lado, relleno), to=(0, 0))
    _CACHE[ficha] = (widget.tk, img)
    return img


def app_icon(widget, size: int = 64):
    """La marca de la aplicación, para `iconphoto()`. None si no se puede."""
    try:
        return _dibujar(widget, ("@marca", size), _capas_marca(size), 64.0, size,
                        CAMPO)
    except Exception:
        return None


def poner_icono(ventana) -> None:
    """Le pone la marca a una ventana. Con `default=True` la heredan también los
    diálogos que cuelguen de ella, así que basta llamarlo en las raíces."""
    import tkinter as tk
    imgs = [i for i in (app_icon(ventana, 64), app_icon(ventana, 32),
                        app_icon(ventana, 16)) if i is not None]
    if not imgs:
        return
    try:
        ventana.iconphoto(True, *imgs)
    except tk.TclError:
        pass


# ---------------------------------------------------------------------------
# runsync.ico
#
# Lo que `iconphoto()` no cubre: el icono de un acceso directo, el de la barra de
# tareas anclada y el del ejecutable del instalador. Eso lo pide Windows en `.ico`
# y como fichero, así que hay que escribirlo.
#
# El formato se escribe a mano por lo mismo que el TOML de `config_file.py`: no
# hay dependencias, y un `.ico` es una cabecera de seis bytes, una entrada de
# dieciséis por tamaño y un DIB detrás. Los DIB van a 32 bits con alfa —el icono
# tiene las esquinas redondeadas y sin alfa saldrían recortadas sobre un cuadrado
# blanco— y de abajo arriba, que es como los quiere BMP.
#
# NADA de aquí toca Tkinter: `_capas_rgba` es Python puro, así que esto se puede
# generar en un equipo sin entorno gráfico y desde el script de compilación.
# ---------------------------------------------------------------------------

# Los tamaños que Windows busca dentro de un .ico: lista pequeña, escritorio,
# ventana, y los dos grandes de las vistas de iconos grandes.
ICO_TAMANOS = (16, 24, 32, 48, 64, 128, 256)

# De aquí arriba, la imagen va como PNG en vez de como DIB. Un `.ico` admite las
# dos cosas desde Vista, y para los tamaños grandes la comprimida es además la
# que Windows espera: un 256×256 en crudo son 270 KB, y en PNG unos 3, porque
# esto son dos colores planos. El fichero pasa de 364 KB a 40.
ICO_PNG_DESDE = 128


def _dib(rgba, size: int) -> bytes:
    """Una imagen del .ico: BITMAPINFOHEADER + píxeles BGRA + máscara AND."""
    import struct

    # El alto va DOBLE en la cabecera: el formato cuenta la máscara como si
    # fuera una segunda imagen pegada debajo, aunque no lo sea.
    cabecera = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0,
                           0, 0, 0, 0)

    pixeles = bytearray()
    for fila in reversed(rgba):                   # BMP se guarda de abajo arriba
        for r, g, b, a in fila:
            pixeles += bytes((b, g, r, round(a * 255)))

    # La máscara AND: un bit por píxel (1 = transparente), filas rellenadas hasta
    # múltiplo de 4 bytes. Windows moderno se guía por el alfa y la ignora, pero
    # el formato la exige y quien la mire tiene que ver lo mismo.
    ancho_bytes = ((size + 31) // 32) * 4
    mascara = bytearray()
    for fila in reversed(rgba):
        bits = bytearray(ancho_bytes)
        for x, (_r, _g, _b, a) in enumerate(fila):
            if a < 0.5:
                bits[x // 8] |= 0x80 >> (x % 8)
        mascara += bits

    return cabecera + bytes(pixeles) + bytes(mascara)


def _png(rgba, size: int) -> bytes:
    """La misma imagen como PNG de 8 bits con alfa, sin filtrar.

    Un PNG son cuatro trozos con su longitud, su nombre y su CRC, y los píxeles
    comprimidos con zlib, que está en la biblioteca estándar. Cada línea lleva
    delante un byte de filtro: 0, «ninguno». Filtrar mejoraría la compresión de
    una foto; de dos colores planos no tiene nada que sacar."""
    import struct
    import zlib

    crudo = bytearray()
    for fila in rgba:                             # PNG sí va de arriba abajo
        crudo.append(0)
        for r, g, b, a in fila:
            crudo += bytes((r, g, b, round(a * 255)))

    def trozo(nombre: bytes, datos: bytes) -> bytes:
        return (struct.pack(">I", len(datos)) + nombre + datos
                + struct.pack(">I", zlib.crc32(nombre + datos) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + trozo(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + trozo(b"IDAT", zlib.compress(bytes(crudo), 9))
            + trozo(b"IEND", b""))


def write_ico(destino, tamanos=ICO_TAMANOS):
    """Escribe la marca como `.ico` con todos sus tamaños. Devuelve la ruta."""
    import struct
    from pathlib import Path

    destino = Path(destino)
    imagenes = []
    for size in tamanos:
        rgba = _capas_rgba(_capas_marca(size), 64.0, size)
        imagenes.append((size, _png(rgba, size) if size >= ICO_PNG_DESDE
                         else _dib(rgba, size)))

    entradas, cuerpo = b"", b""
    desplazamiento = 6 + 16 * len(imagenes)
    for size, datos in imagenes:
        # 256 se anota como 0: en la entrada el tamaño ocupa un solo byte.
        entradas += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32,
                                len(datos), desplazamiento)
        desplazamiento += len(datos)
        cuerpo += datos

    destino.write_bytes(struct.pack("<HHH", 0, 1, len(imagenes)) + entradas + cuerpo)
    return destino


if __name__ == "__main__":                        # python -m ui.icons [destino]
    import sys

    # El .ico va DENTRO de la carpeta de la aplicación, junto al resto del
    # código, y no en la raíz del volumen: esa carpeta está oculta, así que un
    # icono suelto entre los datos del usuario sería el único resto visible.
    from common import model                      # solo aquí: APP_DIR vive ahí
    ruta = write_ico(sys.argv[1] if len(sys.argv) > 1
                     else model.APP_DIR / "runsync.ico")
    print(f"Escrito {ruta} ({ruta.stat().st_size / 1024:.0f} KB, "
          f"{len(ICO_TAMANOS)} tamaños)")
