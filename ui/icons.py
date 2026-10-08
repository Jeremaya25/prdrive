#!/usr/bin/env python3
"""Los iconos del rediseño, dibujados aquí mismo.

El diseño pide iconos de trazo sobre rejilla de 16 y dice explícitamente «sin
emoji»: un ✓ o un ⚠ salen con la fuente de emoji del sistema, en color, de un
tamaño que no controlamos y distinto en cada equipo. Como el proyecto no tiene
dependencias (nada de Pillow, nada de cairosvg), la única salida es pintarlos,
y como Tk 8.6 no sabe leer SVG, se pintan a mano.

Cada icono es una lista de primitivas (segmentos, arcos, círculos, rectángulos)
en el sistema de coordenadas del artboard, y `_capas_rgba()` las convierte en
píxeles midiendo, para cada píxel, la distancia a la tinta más cercana. Esa
distancia da el suavizado gratis y a cualquier tamaño: no hay que redibujar el
icono para 20 px, se pide con `size=20`.

**Todo lleva su alfa**: la imagen se le da a Tk como PNG (`_foto()`), que es
la única forma de pasarle transparencia con matices, y Tk la compone contra lo
que haya debajo. Así el mismo icono vale sobre el papel, sobre una tarjeta y
sobre el gris de un botón al pasar por encima. Es también lo que hace posibles
los controles redondeados del tema: sus piezas (`caja()`) son transparentes
por fuera de la forma.

Nada de aquí puede tumbar la interfaz: `get()` devuelve `None` si algo falla y
quien lo llama pinta el texto sin icono. Un adorno no puede impedir que se abra
la ventana.
"""

from __future__ import annotations

import math

TRAZO = 1.6
"""Anchura de trazo del diseño, en unidades de la rejilla de 16."""


GLIFOS: dict[str, list[tuple]] = {
    # Los dos sentidos de bisync, que es también la marca de la aplicación.
    "sync": [("a", 8, 8, 5, 180, 315), ("l", 11.5, 4.5, 13, 6),
             ("p", [(13, 2.5), (13, 6), (9.5, 6)]),
             ("a", 8, 8, 5, 0, 135), ("l", 4.5, 11.5, 3, 10),
             ("p", [(3, 13.5), (3, 10), (6.5, 10)])],
    # Una unidad USB: el conector y el cuerpo.
    "dispositivo": [("p", [(6.25, 5.5), (6.25, 2.5), (9.75, 2.5), (9.75, 5.5)]),
                    ("r", 4.5, 5.5, 7, 8)],
    "nas": [("r", 2.5, 3, 11, 4), ("r", 2.5, 9, 11, 4), ("d", 5, 5), ("d", 5, 11)],
    # Los tres modos: los dos sentidos, y cada uno por su cuenta.
    "both": [("l", 5, 13.5, 5, 3), ("p", [(2.5, 5.5), (5, 3), (7.5, 5.5)]),
             ("l", 11, 2.5, 11, 13), ("p", [(8.5, 10.5), (11, 13), (13.5, 10.5)])],
    "up": [("l", 8, 13, 8, 3), ("p", [(4, 7), (8, 3), (12, 7)])],
    "down": [("l", 8, 3, 8, 13), ("p", [(4, 9), (8, 13), (12, 9)])],
    "ok": [("p", [(3, 8.5), (6.5, 12), (13, 4.5)])],
    # La admiración sola: el glifo de aviso dentro de un disco o una baldosa,
    # donde el triángulo de «warn» no cabe.
    "alert": [("l", 8, 3.25, 8, 9.5), ("d", 8, 12.5)],
    "close": [("l", 4, 4, 12, 12), ("l", 12, 4, 4, 12)],
    "warn": [("p", [(8, 3.9), (13.2, 12.8), (2.8, 12.8), (8, 3.9)]),
             ("l", 8, 7, 8, 9.8), ("d", 8, 11.6)],
    "clock": [("c", 8, 8, 6), ("p", [(8, 4.5), (8, 8), (10.5, 9.5)])],
    # Los ajustes: dos deslizadores, cada uno con su tirador relleno.
    "gear": [("l", 2.5, 4.5, 13.5, 4.5), ("l", 2.5, 11.5, 13.5, 11.5),
             ("c", 10.5, 4.5, 1.7), ("c", 10.5, 4.5, 0.45),
             ("c", 5.5, 11.5, 1.7), ("c", 5.5, 11.5, 0.45)],
    # Una pareja es un ida y vuelta entre dos sitios: dos flechas opuestas.
    "parejas": [("l", 2.6, 5.4, 12.9, 5.4), ("p", [(10.4, 2.9), (12.9, 5.4), (10.4, 7.9)]),
                ("l", 13.4, 10.6, 3.1, 10.6), ("p", [(5.6, 8.1), (3.1, 10.6), (5.6, 13.1)])],
    # El símbolo de encendido, que es lo que se está activando.
    "arranque": [("a", 8, 8.4, 5.2, -55, 235), ("l", 8, 2.2, 8, 7.6)],
    # Un electrocardiograma: mirar cómo está algo.
    "doctor": [("p", [(2.2, 8), (5.0, 8), (6.4, 4.0), (9.0, 12.0), (10.4, 8), (13.8, 8)])],
    "flag": [("p", [(4, 14), (4, 2.5), (12, 2.5), (10, 5.5), (12, 8.5), (4, 8.5)])],
    # El ojo: dos arcos de una circunferencia grande que se cortan en las puntas.
    "eye": [("a", 8, 10.27, 6.46, 200.6, 339.4), ("a", 8, 5.73, 6.46, 20.6, 159.4),
            ("c", 8, 8, 1.6)],
    "reload": [("a", 8, 8, 5, 0, 315), ("p", [(13, 2), (13, 5.2), (9.8, 5.2)])],
    "edit": [("p", [(11.5, 2.5), (13.5, 4.5), (5.5, 12.5), (2.5, 13.5),
                    (3.5, 10.5), (11.5, 2.5)])],
    "trash": [("l", 3.5, 4.5, 12.5, 4.5),
              ("p", [(6.5, 4.5), (6.5, 2.5), (9.5, 2.5), (9.5, 4.5)]),
              ("p", [(5, 4.5), (5.7, 13.5), (10.3, 13.5), (11, 4.5)])],
    "plus": [("l", 8, 3, 8, 13), ("l", 3, 8, 13, 8)],
    # Los galones de un desplegable y de las flechas de un campo numérico.
    "abajo": [("p", [(4, 6.5), (8, 10.5), (12, 6.5)])],
    "arriba": [("p", [(4, 9.5), (8, 5.5), (12, 9.5)])],
    "derecha": [("p", [(6.5, 4), (10.5, 8), (6.5, 12)])],
    "back": [("l", 13, 8, 3, 8), ("p", [(7, 4), (3, 8), (7, 12)])],
    "file": [("p", [(4, 2), (9, 2), (12, 5), (12, 14), (4, 14), (4, 2)]),
             ("p", [(9, 2), (9, 5.4), (12, 5.4)])],
    # El de expulsar de siempre: un triángulo sobre una barra. Cierra el
    # contenedor cifrado para poder quitar la unidad.
    "expulsar": [("p", [(3.2, 9.6), (8, 4.2), (12.8, 9.6), (3.2, 9.6)]),
                 ("l", 3.2, 12.6, 12.8, 12.6)],
    # Los del menú de la bandeja (`ui/bandeja.py`, `I_*`): abrir una raíz, la
    # pausa y su vuelta, y el candado de la raíz cifrada, cerrado y abierto.
    "carpeta": [("p", [(2.2, 4), (6.2, 4), (7.7, 5.6), (13.8, 5.6), (13.8, 12.8),
                       (2.2, 12.8), (2.2, 4)])],
    "pausa": [("l", 5.5, 3.5, 5.5, 12.5), ("l", 10.5, 3.5, 10.5, 12.5)],
    "play": [("p", [(5, 3.2), (12.8, 8), (5, 12.8), (5, 3.2)])],
    "candado": [("r", 3.5, 8.2, 9, 5.6), ("a", 8, 6.2, 2.8, 180, 360),
                ("l", 5.2, 6.2, 5.2, 8.2), ("l", 10.8, 6.2, 10.8, 8.2)],
    "candado_abierto": [("r", 3.5, 8.2, 9, 5.6), ("a", 8, 5.2, 2.8, 180, 360),
                        ("l", 5.2, 5.2, 5.2, 8.2)],
    # Una llave: el ojo, la caña y dos dientes. Es el llavero de KeePassXC.
    "llave": [("c", 4.8, 8, 2.8), ("l", 7.6, 8, 14, 8),
              ("l", 11.2, 8, 11.2, 10.8), ("l", 13.6, 8, 13.6, 10.2)],
}
"""Los glifos de la interfaz, por nombre: listas de primitivas sobre una rejilla de 16.

Cada primitiva es una tupla:

    ("l",  x1, y1, x2, y2)          segmento
    ("p",  [(x, y), ...])           polilínea
    ("a",  cx, cy, r, a0, a1)       arco, grados que CRECEN de a0 a a1
    ("c",  cx, cy, r)               círculo
    ("d",  x, y)                    punto
    ("r",  x, y, w, h)              rectángulo de trazo
    ("fr", x, y, w, h)              rectángulo relleno
    ("rr", x, y, w, h, radio)       rectángulo relleno de esquinas redondeadas

Los ángulos van en el sentido de la pantalla (la y crece hacia abajo), que es
el mismo en el que los escribe SVG: 0° a la derecha, 90° abajo.
"""

CAMPO = "#2E4763"
"""El color del campo (el fondo) de la marca de la aplicación.

La marca es una rejilla de 64 con capas de colores distintos, por eso no cabe
en `GLIFOS`.
"""
MARCA = "#FAF9F7"
"""El blanco de la marca: uno de sus brazos y el cuerpo del dispositivo."""
AMBAR = "#E0A34A"
"""El ámbar del otro brazo de la marca."""

CAMPOS = {
    "azul": CAMPO,
    "verde": "#2F5A48",
    "granate": "#6B2C34",
    "morado": "#4B3D6E",
    "grafito": "#3B362F",
}
"""Los campos con los que se puede pintar la marca como icono de la UNIDAD.

Es lo que usa `ui/volumen.py` para distinguir un dispositivo de otro a simple
vista. El primero es el de la aplicación. Todos son oscuros y apagados, como
él: encima van el blanco y el ámbar de siempre y tienen que seguir leyéndose.
"""


def _capas_marca(size: int, campo: str = CAMPO) -> list[tuple[str, float, list[tuple]]]:
    """Devuelve las capas del icono de la marca.

    Es la marca mínima del sistema de diseño: dos arcos gruesos de extremos
    redondos, blanco a la derecha y ámbar a la izquierda, alrededor de una
    unidad de una sola pieza (el conector y el cuerpo). Sin puntas de flecha
    ni detalles finos: a 16 px no se leían y a 64 sobraban. A 20 px o menos la
    unidad es un rectángulo liso.
    """
    capas = [(campo, 0.0, [("rr", 0, 0, 64, 64, 14)]),
             (MARCA, 7.0, [("a", 32, 32, 21, -78, 78)]),
             (AMBAR, 7.0, [("a", 32, 32, 21, 102, 258)])]
    if size <= 20:
        return capas + [(MARCA, 0.0, [("rr", 27, 21, 10, 22, 2)])]
    return capas + [(MARCA, 0.0, [("fr", 29, 20, 6, 6.5),
                                  ("rr", 25, 26, 14, 18, 1.75)])]


def _dist_segmento(x: float, y: float, x1: float, y1: float, x2: float, y2: float,
                   semi: float) -> float:
    """Devuelve la distancia con signo a un segmento de trazo `2*semi`.

    Tiene los extremos planos. Un segmento con extremo plano es un rectángulo
    girado, así que se lleva el punto al sistema del propio segmento (cuánto
    avanza y cuánto se separa) y ahí ya es la distancia a una caja. Los
    extremos cuadrados y los ingletes NO se hacen aquí: los pone `_expandir()`
    antes de rasterizar, moviendo los puntos.
    """
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
    """Devuelve la distancia con signo a un triángulo relleno: negativa dentro.

    Solo se usa para las cuñas de los ingletes, que son siempre triángulos.
    """
    lados = ((p0, p1), (p1, p2), (p2, p0))
    fuera = min(_dist_segmento(x, y, *a, *b, 0.0) for a, b in lados)
    signos = [(b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])
              for a, b in lados]
    dentro = all(s >= 0 for s in signos) or all(s <= 0 for s in signos)
    return -fuera if dentro else fuera


def _dist_arco(x: float, y: float, cx: float, cy: float, r: float,
               a0: float, a1: float) -> float:
    """Devuelve la distancia a un arco.

    Es la del propio anillo si el punto cae dentro del sector y, si no, la de
    la punta más cercana, que es lo que hace que un arco no se coma la pantalla
    entera.
    """
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
    """Devuelve la distancia con signo a un rectángulo: negativa dentro."""
    dx = max(rx - x, x - (rx + w))
    dy = max(ry - y, y - (ry + h))
    if dx > 0 and dy > 0:
        return math.hypot(dx, dy)
    return max(dx, dy)


def _sdf(prim: tuple, x: float, y: float, semi: float) -> float:
    """Devuelve la distancia con signo a la tinta de una primitiva.

    `semi` es la mitad del trazo; los rellenos van con `semi = 0` y su propia
    distancia con signo.
    """
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
    """Devuelve las componentes de un color `#rrggbb`."""
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


MITER_LIMITE = 4.0
"""Tope del inglete, el mismo que trae SVG.

Sin él, una esquina muy cerrada dispara una aguja.
"""


def _unitario(dx: float, dy: float):
    """Devuelve el vector unitario de `(dx, dy)`, o `None` si es nulo."""
    largo = math.hypot(dx, dy)
    return None if largo == 0 else (dx / largo, dy / largo)


def _alargar(x1, y1, x2, y2, ini: float, fin: float):
    """Devuelve el segmento con sus puntas corridas hacia fuera: el extremo cuadrado."""
    u = _unitario(x2 - x1, y2 - y1)
    if u is None:
        return x1, y1, x2, y2
    return (x1 - u[0] * ini, y1 - u[1] * ini, x2 + u[0] * fin, y2 + u[1] * fin)


def _inglete(a, b, c, semi: float) -> list[tuple]:
    """Devuelve las cuñas que rellenan la esquina de fuera en `b`.

    Es vacío si no hace falta. `bis` sale de `u1 - u2` y apunta siempre al
    exterior del giro; la punta cae a `semi / sen(mitad del ángulo)`, que es la
    definición del inglete.

    Lo que hay que rellenar es el CUADRILÁTERO b-A-T-C y no el triángulo A-T-C:
    los dos rectángulos del trazo se cruzan en `b` y dejan sin cubrir también
    el trozo entre el vértice y la línea A-C. Con solo el triángulo, la punta
    de flecha salía separada del resto por una rendija.
    """
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
        """Devuelve la perpendicular a `u` que mira al mismo lado que la bisectriz."""
        n = (-u[1], u[0])
        return n if n[0] * bis[0] + n[1] * bis[1] >= 0 else (u[1], -u[0])

    n1, n2 = normal(u1), normal(u2)
    esquina1 = (b[0] + n1[0] * semi, b[1] + n1[1] * semi)
    esquina2 = (b[0] + n2[0] * semi, b[1] + n2[1] * semi)
    vertice = (b[0] + bis[0] * punta, b[1] + bis[1] * punta)
    return [("t", b, esquina1, vertice), ("t", b, vertice, esquina2)]


def _expandir(prims, semi: float) -> list[tuple]:
    """Devuelve las primitivas de un glifo listas para rasterizar con este grosor.

    Los extremos cuadrados y los ingletes se resuelven moviendo puntos (alargar
    las puntas libres, meter un triangulito en cada esquina) y se hacen UNA vez
    por capa y no por píxel: son cuatro cuentas frente a los 65.536 puntos de
    un icono de 256. El diseño dibuja todo con `stroke-linecap="square"` y
    `stroke-linejoin="miter"`, y a trazo grueso eso no es un detalle: las
    puntas de flecha del icono son dos segmentos en ángulo recto y sin inglete
    salen como un rombo en vez de como una punta.
    """
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


def _capas_rgba(capas, caja: float, size: int,
                alto: int | None = None) -> list[list[tuple]]:
    """Devuelve las capas compuestas entre sí sobre transparente.

    `caja` es lo que mide el lado ANCHO del dibujo en su rejilla y `size` los
    píxeles que le tocan; `alto` son las filas, si no es cuadrado (las piezas
    de `caja()`).

    Son filas de `(r, g, b, a)`. Se recorre píxel a píxel midiendo la distancia
    a la tinta: dentro del trazo la cobertura es 1, fuera 0 y en el borde el
    valor intermedio que suaviza el dibujo. Es caro por píxel y barato de
    verdad: 16×16 son 256 puntos.

    El alfa se conserva en vez de aplanarlo aquí porque hay dos destinos con
    necesidades distintas: `PhotoImage` no sabe de transparencia y quiere el
    dibujo ya compuesto contra un color, y un `.ico` la necesita (si no, las
    esquinas redondeadas del icono saldrían recortadas sobre un cuadrado).

    Una capa de color `None` no pinta: recorta lo que haya debajo (la
    pastilla de la bandeja se recorta del campo, sin halo).
    """
    unidad = caja / size                   # cuánto mide un píxel en la rejilla
    colores = [(None if color is None else _rgb(color), ancho / 2,
                _expandir(prims, ancho / 2))
               for color, ancho, prims in capas]
    filas = []
    for py in range(size if alto is None else alto):
        y = (py + 0.5) * unidad
        fila = []
        for px in range(size):
            x = (px + 0.5) * unidad
            r = g = b = 0
            acumulado = 0.0
            for rgb, semi, prims in colores:
                sd = min(_sdf(p, x, y, semi) for p in prims)
                alfa = min(1.0, max(0.0, 0.5 - sd / unidad))
                if alfa <= 0:
                    continue
                if rgb is None:            # una capa que recorta lo de debajo
                    acumulado *= 1 - alfa
                    continue
                cr, cg, cb = rgb
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


_VACIO = (0, 0, 0, 0.0)
"""Un píxel transparente, en el formato de `_capas_rgba`."""


def _con_hueco(filas, ancho: int, bajar: int = 0, alto: int | None = None,
               derecha: int = 0) -> list[list[tuple]]:
    """Devuelve las filas metidas en una imagen mayor, con lo de alrededor transparente.

    El dibujo empieza en la fila `bajar` de una imagen de `alto` filas y lleva
    `derecha` columnas vacías a su derecha. Es la única forma de mover un
    icono dentro de un botón: ttk lo centra en la caja de la línea y no hay
    ningún hueco que tocar.

    Se da la altura ENTERA y no solo cuántas filas poner encima porque ttk
    centra la imagen: añadir filas arriba y dejar que crezca la mueve solo
    media fila por cada una, y encima crece el botón, que vuelve a mover el
    texto. Con la altura fija el sitio del dibujo se decide aquí y no se mueve
    nada más.
    """
    total = ancho + derecha
    vacia = [_VACIO] * total
    salida = [vacia] * bajar + [fila + [_VACIO] * derecha for fila in filas]
    alto = len(salida) if alto is None else alto
    salida += [vacia] * max(0, alto - len(salida))
    return salida[:alto]


_PNGS: dict[tuple, str] = {}
"""Lo ya pintado, como PNG en base64 y sin Tk: vale para todos los intérpretes.

El asistente abre su intérprete después de que la ventana principal cierre el
suyo, y las piezas de los controles (`caja()`) son casi un centenar: así se
rasterizan una vez por proceso, no una por ventana.
"""

_CACHE: dict[tuple, tuple] = {}
"""Las imágenes ya pintadas.

Hay que guardarlas: Tk no se queda con ellas y una `PhotoImage` sin referencias
en Python desaparece del widget. La clave lleva el intérprete de Tk porque una
imagen pertenece al suyo y aquí se abren varios a lo largo de una sesión (la
ventana principal, luego el asistente); guardar el intérprete en el valor evita
además que `id()` se reutilice mientras la caché siga viva.
"""


def olvidar(interp) -> None:
    """Suelta las imágenes de un intérprete de Tk que ya se ha cerrado.

    La caché las guarda por intérprete y no se vacía nunca, lo que no importa
    en el hilo principal. Sí importa en la ventanita del servicio, que vive en
    un hilo propio (`ui.avisar_fallo`): si sus imágenes siguieran aquí, las
    borraría el hilo principal al salir, y a Tk solo se le habla desde el suyo.
    """
    for ficha in [f for f, (dueno, _img) in _CACHE.items() if dueno is interp]:
        del _CACHE[ficha]


def px(widget, medida: int) -> int:
    """Devuelve una medida del diseño llevada a los píxeles de esta pantalla.

    Los iconos son mapas de bits y Tk no los escala, pero sí escala las
    fuentes: en una pantalla densa un icono de 15 px fijos quedaría de juguete
    al lado de su texto. `tk scaling` son píxeles por punto y 1,333 es el valor
    a 96 ppp, que es la densidad para la que están pensadas las medidas del
    diseño.
    """
    try:
        escala = float(widget.tk.call("tk", "scaling"))
    except Exception:
        escala = 1.3333
    return max(1, round(medida * escala / 1.3333))


def _foto(widget, clave: tuple, filas):
    """Devuelve la imagen de clave `clave`, haciéndola con `filas()` solo si hace falta.

    `filas` es una función que devuelve las filas `(r, g, b, a)`: solo se llama
    si la imagen no está pintada ya en este proceso. La imagen se le da a Tk
    como PNG porque es la única manera de pasarle un alfa con matices:
    `PhotoImage.put()` escribe colores opacos y nada más.
    """
    interp = widget.tk
    ficha = (id(interp), *clave)
    guardado = _CACHE.get(ficha)
    if guardado is not None and guardado[0] is interp:
        return guardado[1]
    datos = _PNGS.get(clave)
    if datos is None:
        import base64
        datos = base64.b64encode(_png(filas())).decode("ascii")
        _PNGS[clave] = datos
    import tkinter as tk
    img = tk.PhotoImage(master=widget, data=datos)
    _CACHE[ficha] = (interp, img)
    return img


def _dibujar(widget, clave: tuple, capas, caja: float, size: int, fondo: str = "",
             bajar: int = 0, alto: int | None = None):
    """Devuelve la imagen de esas capas sobre transparente, pintándola solo si hace falta.

    `fondo` ya no se usa: se acepta por las llamadas de antes, cuando el icono
    se aplanaba contra el color del sitio donde caía. Ahora lleva su alfa y Tk
    lo compone contra lo que haya debajo, sea papel, tarjeta o el gris de un
    botón al pasar por encima.
    """
    return _foto(widget, (*clave, "@alfa"),
                 lambda: _con_hueco(_capas_rgba(capas, caja, size), size,
                                    bajar, alto))


def get(widget, nombre: str, size: int = 16, color: str = "#3B362F",
        fondo: str = "#FAF9F7", bajar: float = 0, alto: int | None = None):
    """Devuelve el icono `nombre` al tamaño del diseño, sobre transparente.

    `fondo` no cambia el dibujo (lleva su alfa); se sigue aceptando porque lo
    dan todas las llamadas.

    Devuelve `None` si no se puede pintar (un nombre que no existe, un Tk que
    se está cerrando) y quien llama se queda sin icono pero con su texto.

    Args:
        bajar: Lo mueve hacia abajo esos píxeles dentro de su propia imagen; lo
            usa `theme.icono_linea` para alinearlo con el texto de al lado.
            Puede llevar decimales: la parte entera son filas vacías encima y
            la fraccionaria se dibuja (el rasterizador mide distancias, así
            que medio píxel más abajo es otro suavizado, no un redondeo).
    """
    try:
        real = px(widget, size)
        entero = int(bajar)
        fraccion = round(bajar - entero, 2)
        prims = GLIFOS[nombre]
        filas = real
        if fraccion:
            prims = _mover(prims, 0, fraccion * 16.0 / real)
            filas = real + 1
        capas = [(color, TRAZO, prims)]
        return _foto(widget, (nombre, real, color, entero, fraccion, alto, "@alfa"),
                     lambda: _con_hueco(_capas_rgba(capas, 16.0, real, filas), real,
                                        entero, alto))
    except Exception:
        return None


def _casillas() -> dict[str, tuple[str, str, str | None]]:
    """Devuelve las casillas de marcar por estado: relleno, borde y color del visto.

    Son un cuadrado de 15, del acento con el visto encima cuando está marcada.
    Se pintan aquí porque el indicador de clam dibuja una especie de aspa y el
    diseño pide un visto. Los colores son los del tema puesto.
    """
    from . import theme
    return {
        "marcada": (theme.ACENTO, theme.ACENTO, theme.SOBRE_ACENTO),
        "vacia": (theme.SUPERFICIE, theme.BORDE, None),
        "apagada": (theme.APAGADO_FONDO, theme.LINEA, None),
        "apagada-marcada": (theme.APAGADO, theme.APAGADO, theme.APAGADO_FONDO),
    }
_VISTO = [("p", [(3.5, 8.5), (6.5, 11.5), (12.5, 4.5)])]
"""El trazo del visto de la casilla marcada."""


def casilla(widget, estado: str, size: int = 15, margen: int = 7):
    """Devuelve la casilla de marcar, con `margen` píxeles transparentes a su derecha.

    Ese margen es lo que separa el cuadrado de su texto: el elemento de imagen
    de ttk no entiende de `indicatormargin`, así que el hueco va dentro de la
    propia imagen, transparente, y por él se ve el fondo que haya detrás, sea
    papel o tarjeta. Las esquinas van apenas redondeadas (2 px, `radius-sm`).
    """
    relleno, borde, visto = _casillas()[estado]
    lado, hueco = px(widget, size), px(widget, margen)
    uno = 16 / lado                     # un píxel en la rejilla de 16

    def filas():
        """El cuadrado con su borde y, si va marcada, el visto."""
        fino, radio = uno * px(widget, 1), uno * px(widget, 2)
        capas = [(borde, 0.0, [("rr", 0, 0, 16, 16, radio)]),
                 (relleno, 0.0, [("rr", fino, fino, 16 - 2 * fino, 16 - 2 * fino,
                                  max(0.0, radio - fino))])]
        if visto:
            capas.append((visto, 2.4, _VISTO))
        return _con_hueco(_capas_rgba(capas, 16.0, lado), lado, derecha=hueco)

    return _foto(widget, ("@casilla", estado, lado, hueco, relleno, borde, visto),
                 filas)


def _radios() -> dict[str, tuple[str, str, str | None]]:
    """Devuelve los botones de opción por estado: relleno, aro y color del punto."""
    from . import theme
    return {
        "marcada": (theme.SUPERFICIE, theme.ACENTO, theme.ACENTO),
        "vacia": (theme.SUPERFICIE, theme.BORDE, None),
        "apagada": (theme.APAGADO_FONDO, theme.LINEA, None),
        "apagada-marcada": (theme.APAGADO_FONDO, theme.APAGADO, theme.APAGADO),
    }


def opcion(widget, estado: str, size: int = 16, margen: int = 7):
    """Devuelve el botón de opción: un aro con el punto del acento si está elegido.

    Es el `dotbtn` del diseño (16 de lado, punto de 8) y se pinta por lo mismo
    que la casilla: el de clam es otro dibujo. Lleva el mismo margen a la
    derecha.
    """
    relleno, aro, punto = _radios()[estado]
    lado, hueco = px(widget, size), px(widget, margen)
    fino = 16 / lado * px(widget, 1)

    def filas():
        """El aro, su relleno y el punto."""
        capas = [(aro, 0.0, [("rr", 0, 0, 16, 16, 8)]),
                 (relleno, 0.0, [("rr", fino, fino, 16 - 2 * fino, 16 - 2 * fino,
                                  8 - fino)])]
        if punto:
            capas.append((punto, 0.0, [("rr", 4, 4, 8, 8, 4)]))
        return _con_hueco(_capas_rgba(capas, 16.0, lado), lado, derecha=hueco)

    return _foto(widget, ("@opcion", estado, lado, hueco, relleno, aro, punto),
                 filas)


def _forma(x: float, y: float, w: float, h: float, radio: float,
           esquinas: str) -> list[tuple]:
    """Devuelve un rectángulo con solo las esquinas de `esquinas` redondeadas.

    `esquinas` son cuatro «1» o «0»: arriba a la izquierda, arriba a la
    derecha, abajo a la derecha y abajo a la izquierda, como en CSS. Una
    esquina recta es un cuarto relleno encima del redondeado: la unión de
    primitivas de una capa ya es la distancia mínima.
    """
    prims = [("rr", x, y, w, h, radio)]
    cuartos = ((x, y), (x + w / 2, y), (x + w / 2, y + h / 2), (x, y + h / 2))
    for marca, (cx, cy) in zip(esquinas, cuartos):
        if marca == "0":
            prims.append(("fr", cx, cy, w / 2, h / 2))
    return prims


CENTRO_ANCHO, CENTRO_ALTO = 256, 64
"""Lo que mide el centro estirable de una pieza de `caja()`, en píxeles.

ttk no ESTIRA el centro de una pieza de nueve trozos: lo repite como un
azulejo hasta llenar el control, una llamada de dibujo por copia. Con un
centro de 2×2 eso eran cientos de copias por botón, y en X11 cada copia de una
imagen con transparencia le pide los píxeles de debajo al servidor para
mezclarlos: 300 controles tardaban 36 s en pintarse. Con un centro de este
tamaño un control normal es una sola copia (o unas pocas, si es muy grande).
Se hace repitiendo la fila y la columna del medio (`_ensanchar`), sin
rasterizar más: el centro es de un color.
"""


def _ensanchar(filas, borde: int, ancho: int, alto: int) -> list[list[tuple]]:
    """Devuelve la pieza con su centro (fila y columna del medio) repetido hasta ese tamaño."""
    medio_x = len(filas[0]) // 2
    anchas = [fila[:borde] + [fila[medio_x]] * ancho + fila[-borde:] for fila in filas]
    medio_y = len(anchas) // 2
    return anchas[:borde] + [anchas[medio_y]] * alto + anchas[-borde:]


def caja(widget, tonos, radio: float = 4, esquinas: str = "1111"):
    """Devuelve la pieza de un control y cuánto mide su borde: `(imagen, borde)`.

    Es lo que dibuja los controles con esquinas redondeadas (`theme`): una
    imagen pequeña que ttk parte en nueve trozos (`-border`), deja las cuatro
    esquinas como están y estira el resto hasta el tamaño del control. Por eso
    vale para un botón de cualquier ancho con una sola imagen.

    Fuera de la forma es transparente, y Tk compone ahí lo que haya debajo: el
    `background` del estilo, que es el color de la superficie donde cae el
    control (`theme`, «asiento»).

    Args:
        tonos: `(color, margen)` de fuera adentro: cada uno es la forma rellena
            de ese color, metida `margen` píxeles del diseño (un número, o
            cuatro: izquierda, arriba, derecha, abajo). El borde de un botón
            es `[(BORDE, 0), (SUPERFICIE, 1)]`. Un color `None` recorta lo de
            debajo: `[(ACENTO, 0), (None, 2)]` es un aro sin relleno.
        radio: El radio de las esquinas, en píxeles del diseño.
        esquinas: Cuáles van redondeadas (ver `_forma`).

    Returns:
        La imagen y el borde de nueve trozos en píxeles de la pantalla, o
        `(None, 0)` si no se puede pintar.
    """
    try:
        r = px(widget, radio) if radio else 0
        reales = []
        for color, margen in tonos:
            m = (margen,) * 4 if isinstance(margen, (int, float)) else tuple(margen)
            reales.append((color, tuple(px(widget, v) if v else 0 for v in m)))
        hondo = max((max(m) for _c, m in reales), default=0)
        borde = r + hondo + 1
        lado = 2 * borde + 2

        def filas():
            """Las formas, una capa por tono."""
            capas = []
            for color, (iz, ar, de, ab) in reales:
                capas.append((color, 0.0, _forma(iz, ar, lado - iz - de,
                                                 lado - ar - ab,
                                                 max(0, r - max(iz, ar, de, ab)),
                                                 esquinas)))
            return _ensanchar(_capas_rgba(capas, float(lado), lado), borde,
                              CENTRO_ANCHO, CENTRO_ALTO)

        return _foto(widget, ("@caja", tuple(reales), r, esquinas, lado,
                              CENTRO_ANCHO, CENTRO_ALTO), filas), borde
    except Exception:
        return None, 0


def _mover(prims: list[tuple], dx: float, dy: float) -> list[tuple]:
    """Devuelve las mismas primitivas desplazadas (dx, dy) en la rejilla."""
    movidas = []
    for prim in prims:
        clase = prim[0]
        if clase == "p":
            movidas.append(("p", [(x + dx, y + dy) for x, y in prim[1]]))
        elif clase == "l":
            _, x1, y1, x2, y2 = prim
            movidas.append(("l", x1 + dx, y1 + dy, x2 + dx, y2 + dy))
        else:                       # a, c, d, r, fr, rr: lo primero es el sitio
            movidas.append((clase, prim[1] + dx, prim[2] + dy, *prim[3:]))
    return movidas


def disco(widget, nombre: str, color: str, tinta: str, fondo: str,
          hueco: bool = False, size: int = 18):
    """Devuelve el disco de un chip: un círculo del color del estado con su glifo.

    Es el mismo disco que la pastilla de la bandeja: el color del estado va
    ahí, sólido, y no en la letra. El glifo mide dos tercios del disco (12 de
    18) con el trazo más grueso, 2, porque a ese tamaño el de 1,6 se pierde.

    Args:
        tinta: El color del glifo, el `SOBRE_*` del color del disco.
        fondo: Contra qué se componen los bordes (el fondo del chip).
        hueco: Solo el aro, con el glifo del color del aro: el chip apagado.

    Returns:
        La imagen, o `None` si no se puede pintar.
    """
    try:
        real = px(widget, size)
        caja = 16 * size / 12           # la rejilla del glifo, ampliada
        c = caja / 2
        if hueco:
            capas = [(color, caja / size, [("c", c, c, c - caja / size / 2)]),
                     (color, 2.0, _mover(GLIFOS[nombre], (caja - 16) / 2,
                                         (caja - 16) / 2))]
        else:
            capas = [(color, c, [("c", c, c, c / 2)]),
                     (tinta, 2.0, _mover(GLIFOS[nombre], (caja - 16) / 2,
                                         (caja - 16) / 2))]
        return _dibujar(widget, ("@disco", nombre, real, color, tinta, fondo, hueco),
                        capas, caja, real, fondo)
    except Exception:
        return None


def baldosa(widget, nombre: str, color: str, tinta: str, fondo: str,
            size: int = 32):
    """Devuelve la baldosa de un aviso: un cuadrado redondeado de color con su glifo.

    Es la baldosa de la marca (el mismo campo redondeado), del color del tono
    del aviso, con el glifo a 18 de 32 y trazo 1,8.

    Returns:
        La imagen, o `None` si no se puede pintar.
    """
    try:
        real = px(widget, size)
        caja = 16 * size / 18
        capas = [(color, 0.0, [("rr", 0, 0, caja, caja, 4 * caja / size)]),
                 (tinta, 1.8, _mover(GLIFOS[nombre], (caja - 16) / 2,
                                     (caja - 16) / 2))]
        return _dibujar(widget, ("@baldosa", nombre, real, color, tinta, fondo),
                        capas, caja, real, fondo)
    except Exception:
        return None


QR_TINTA = "#000000"
"""El color de los módulos oscuros del QR: negro puro.

No es el de la paleta porque lo lee una cámara. El QR no se pinta con el
rasterizador de arriba, a propósito: ese mide distancias a un trazo para
suavizar los bordes y un QR es justo lo contrario, una rejilla de cuadrados que
tiene que salir con el canto duro. Un módulo medio gris es lo que hace que un
lector dude. Por eso `matriz()` compone la cadena de `put()` directamente,
repitiendo cada módulo `escala` veces.
"""
QR_PAPEL = "#FFFFFF"
"""El color de los módulos claros del QR: blanco puro."""
QR_SILENCIO = 4
"""Los módulos de margen que exige ISO/IEC 18004."""


def matriz(widget, modulos, escala: int = 4, silencio: int = QR_SILENCIO):
    """Devuelve una matriz de módulos (`True` es oscuro) como `PhotoImage` cuadrada.

    `escala` son los píxeles de lado de cada módulo: entero y nunca
    fraccionario, porque un módulo de 3,5 px reparte el medio píxel entre sus
    vecinos y el resultado ya no es una rejilla. `silencio` es la zona de
    silencio, que se pone aquí y no en `qr.py` porque es parte de cómo se
    dibuja y no del código.

    Devuelve `None` si algo falla, como el resto del módulo: quien llama enseña
    entonces el texto y no se queda sin ventana.

    **La imagen se la guarda quien llama.** Aquí no entra en `_CACHE` (cada
    código es distinto y guardarlos todos sería acumular basura) y una
    `PhotoImage` sin referencias en Python desaparece del widget.
    """
    try:
        import tkinter as tk
        lado = len(modulos)
        total = (lado + silencio * 2) * escala
        blanca = " ".join([QR_PAPEL] * total)
        filas = ["{" + blanca + "}"] * (silencio * escala)
        for fila in modulos:
            celdas = [QR_PAPEL] * (silencio * escala)
            for modulo in fila:
                celdas += [QR_TINTA if modulo else QR_PAPEL] * escala
            celdas += [QR_PAPEL] * (silencio * escala)
            filas += ["{" + " ".join(celdas) + "}"] * escala
        filas += ["{" + blanca + "}"] * (silencio * escala)

        img = tk.PhotoImage(master=widget, width=total, height=total)
        img.put(" ".join(filas))
        return img
    except Exception:
        return None


def app_icon(widget, size: int = 64, campo: str = CAMPO, fondo: str | None = None):
    """Devuelve la marca de la aplicación para `iconphoto()`, o `None` si no se puede.

    `campo` la pinta en otro color (`CAMPOS`) y `fondo` es contra qué se
    componen las esquinas redondeadas: para una ventana da igual (se aplana
    contra el propio campo, como siempre), pero una muestra sobre el papel de
    un formulario tiene que llevar las esquinas del color del papel.
    """
    try:
        return _dibujar(widget, ("@marca", size, campo, fondo),
                        _capas_marca(size, campo), 64.0, size, fondo or campo)
    except Exception:
        return None


def poner_icono(ventana) -> None:
    """Le pone la marca a una ventana, y la barra de título del tema.

    Con `default=True` la heredan también los diálogos que cuelguen de ella,
    así que basta llamarlo en las raíces.
    """
    import tkinter as tk

    from . import theme
    theme.barra_titulo(ventana)
    imgs = [i for i in (app_icon(ventana, 64), app_icon(ventana, 32),
                        app_icon(ventana, 16)) if i is not None]
    if not imgs:
        return
    try:
        ventana.iconphoto(True, *imgs)
    except tk.TclError:
        pass


ICO_TAMANOS = (16, 24, 32, 48, 64, 128, 256)
"""Los tamaños que Windows busca dentro de un `.ico`.

Son la lista pequeña, el escritorio, la ventana y los dos grandes de las vistas
de iconos grandes.
"""

ICO_PNG_DESDE = 128
"""Desde este tamaño la imagen del `.ico` va como PNG en vez de como DIB.

Un `.ico` admite las dos cosas desde Vista y para los tamaños grandes la
comprimida es además la que Windows espera: un 256×256 en crudo son 270 KB y en
PNG unos 3, porque son dos colores planos. El fichero pasa de 364 KB a 40.
"""


def _dib(rgba, size: int) -> bytes:
    """Devuelve una imagen del `.ico`: BITMAPINFOHEADER + píxeles BGRA + máscara AND."""
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


def _png(rgba, size: int | None = None) -> bytes:
    """Devuelve la misma imagen como PNG de 8 bits con alfa, sin filtrar.

    Las medidas salen de las propias filas: `size` sobra y se acepta por las
    llamadas de antes, que daban el lado de un cuadrado.

    Un PNG son cuatro trozos con su longitud, su nombre y su CRC, y los píxeles
    comprimidos con zlib, que está en la biblioteca estándar. Cada línea lleva
    delante un byte de filtro: 0, «ninguno». Filtrar mejoraría la compresión de
    una foto; de dos colores planos no tiene nada que sacar.
    """
    import struct
    import zlib

    crudo = bytearray()
    for fila in rgba:                             # PNG sí va de arriba abajo
        crudo.append(0)
        for r, g, b, a in fila:
            crudo += bytes((r, g, b, round(a * 255)))

    def trozo(nombre: bytes, datos: bytes) -> bytes:
        """Devuelve un trozo del PNG con su longitud, su nombre y su CRC."""
        return (struct.pack(">I", len(datos)) + nombre + datos
                + struct.pack(">I", zlib.crc32(nombre + datos) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + trozo(b"IHDR", struct.pack(">IIBBBBB", len(rgba[0]), len(rgba),
                                         8, 6, 0, 0, 0))
            + trozo(b"IDAT", zlib.compress(bytes(crudo), 9))
            + trozo(b"IEND", b""))


def ico(tamanos=ICO_TAMANOS, campo: str = CAMPO) -> bytes:
    """Devuelve la marca como `.ico` con todos sus tamaños, en bytes.

    Es lo que `iconphoto()` no cubre: el icono de un acceso directo, el de la
    barra de tareas anclada y el del ejecutable del instalador. Windows lo pide
    en `.ico` y como fichero, así que hay que escribirlo. El formato se escribe
    a mano por lo mismo que el TOML de `config_file.py`: no hay dependencias, y
    un `.ico` es una cabecera de seis bytes, una entrada de dieciséis por
    tamaño y un DIB detrás. Los DIB van a 32 bits con alfa (el icono tiene las
    esquinas redondeadas y sin alfa saldrían recortadas sobre un cuadrado
    blanco) y de abajo arriba, que es como los quiere BMP. Nada de aquí toca
    Tkinter: `_capas_rgba` es Python puro, así que se puede generar en un
    equipo sin entorno gráfico y desde el script de compilación.

    Tarda unos dos segundos, casi todos del de 256 px: quien lo pida desde una
    ventana, que lo haga en `tk.working()`.
    """
    return _ico_de(tamanos, lambda size: _capas_marca(size, campo))


def _ico_de(tamanos, capas_de) -> bytes:
    """Devuelve un `.ico` con esos tamaños, cada uno pintado con `capas_de(size)`."""
    import struct

    imagenes = []
    for size in tamanos:
        rgba = _capas_rgba(capas_de(size), 64.0, size)
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

    return struct.pack("<HHH", 0, 1, len(imagenes)) + entradas + cuerpo


def write_ico(destino, tamanos=ICO_TAMANOS, campo: str = CAMPO):
    """Escribe la marca como `.ico` con todos sus tamaños y devuelve la ruta."""
    from pathlib import Path

    destino = Path(destino)
    destino.write_bytes(ico(tamanos, campo))
    return destino


BIEN, SINCRONIZANDO, AVISO, PAUSA, BLOQUEADO = (
    "bien", "sincronizando", "aviso", "pausa", "bloqueado")
"""Los cinco estados del icono de la bandeja (`ui/bandeja.py` decide cuál).

Son la marca de siempre y, en la esquina de abajo a la derecha, una pastilla
que lo dice. A 16 px lo que se lee es el COLOR de la pastilla (azul, ámbar,
oscura) y el campo gris de la pausa; el dibujo de dentro (la admiración, las
dos barras, el candado) solo aparece desde 24 px, que es la bandeja al 150 %.
Todo va en `.ico` porque Windows carga el icono de la bandeja con `LoadImageW`
desde un fichero, y se REPINTA en la carpeta del agente, como `runsync.ico`:
nunca se copia.
"""
BANDEJA_ESTADOS = (BIEN, SINCRONIZANDO, AVISO, PAUSA, BLOQUEADO)
"""Los cinco estados, en orden."""
BANDEJA_TAMANOS = (16, 20, 24, 32, 48)
"""Los tamaños del icono pequeño de Windows a 100, 125, 150, 200 y 300 %."""

TINTA_PASTILLA = "#1C1A17"
"""La tinta de `theme.TINTA`."""
_PASTILLA = {SINCRONIZANDO: "#6F9BD1", AVISO: AMBAR, PAUSA: MARCA,
             BLOQUEADO: TINTA_PASTILLA}
"""El color de la pastilla de cada estado; `BIEN` no lleva."""
_PASTILLA_CENTRO, _PASTILLA_RADIO = 47.0, 16.0
"""El centro y el radio de la pastilla, en la rejilla de 64."""
_PASTILLA_RECORTE = 4.0
"""Lo que se recorta del campo alrededor de la pastilla."""


def _disco(color: str | None, radio: float) -> tuple:
    """Devuelve la capa de un círculo relleno (o recortado, con `None`).

    Un anillo de radio r/2 y trazo r cubre de 0 a r.
    """
    return (color, radio, [("c", _PASTILLA_CENTRO, _PASTILLA_CENTRO, radio / 2)])


def capas_bandeja(size: int, estado: str) -> list[tuple[str, float, list[tuple]]]:
    """Devuelve las capas del icono de la bandeja en ese estado.

    La pastilla se RECORTA del campo, sin aro alrededor, así que se separa de
    la marca sobre cualquier fondo de barra de tareas.

    Raises:
        ValueError: Si no es uno de `BANDEJA_ESTADOS`.
    """
    if estado not in BANDEJA_ESTADOS:
        raise ValueError(f"estado de la bandeja desconocido: {estado}")
    capas = _capas_marca(size, CAMPOS["grafito"] if estado == PAUSA else CAMPO)
    if estado == BIEN:
        return capas
    capas = capas + [_disco(None, _PASTILLA_RADIO + _PASTILLA_RECORTE),
                     _disco(_PASTILLA[estado], _PASTILLA_RADIO)]
    if size < 24:
        return capas
    tinta = TINTA_PASTILLA
    if estado == AVISO:
        capas.append((tinta, 0.0, [("rr", 45, 38, 4, 11.5, 2), ("rr", 45, 52, 4, 4, 2)]))
    elif estado == PAUSA:
        capas.append((tinta, 0.0, [("rr", 41.8, 40, 4.2, 14, 1.5),
                                   ("rr", 49, 40, 4.2, 14, 1.5)]))
    elif estado == BLOQUEADO:
        capas += [(MARCA, 2.6, [("l", 43.5, 46, 43.5, 43.7),
                                ("a", 47, 43.7, 3.5, 180, 360),
                                ("l", 50.5, 43.7, 50.5, 46)]),
                  (MARCA, 0.0, [("rr", 40.5, 46, 13, 9.5, 2.5)])]
    elif estado == SINCRONIZANDO:
        capas.append((tinta, 2.6, [("l", 44.5, 53, 44.5, 41.5),
                                   ("p", [(41, 45), (44.5, 41.5), (48, 45)]),
                                   ("l", 49.5, 41, 49.5, 52.5),
                                   ("p", [(46, 49), (49.5, 52.5), (53, 49)])]))
    return capas


def marca_estado(widget, size: int, estado: str = BIEN, campo: str = CAMPO,
                 fondo: str | None = None):
    """Devuelve la marca a `size` px con la pastilla de un estado, o `None`.

    Es la marca que encabeza un aviso (la ventanita del fallo del servicio, la
    de «se ha conectado una unidad»): la misma del icono de la bandeja, con su
    pastilla, compuesta contra el `fondo` de la ventana.

    Args:
        campo: El color del campo (`CAMPOS`), el de la unidad de la que se habla.
    """
    try:
        capas = capas_bandeja(size, estado) if estado != BIEN else _capas_marca(size, campo)
        if estado != BIEN and campo != CAMPO and estado != PAUSA:
            capas = [(campo if i == 0 else color, ancho, prims)
                     for i, (color, ancho, prims) in enumerate(capas)]
        real = px(widget, size)
        return _dibujar(widget, ("@marca-estado", real, estado, campo, fondo),
                        capas, 64.0, real, fondo or campo)
    except Exception:
        return None


def ico_bandeja(estado: str, tamanos=BANDEJA_TAMANOS) -> bytes:
    """Devuelve el icono de la bandeja en ese estado, como `.ico`."""
    return _ico_de(tamanos, lambda size: capas_bandeja(size, estado))


def _premultiplicado(rgba) -> bytes:
    """Devuelve filas de `(r, g, b, a)` como BGRA de arriba abajo, con el alfa premultiplicado."""
    datos = bytearray()
    for fila in rgba:
        for r, g, b, a in fila:
            datos += bytes((round(b * a), round(g * a), round(r * a), round(a * 255)))
    return bytes(datos)


def pixeles_menu(nombre: str, size: int, color: str) -> bytes:
    """Devuelve un glifo como imagen de una entrada de menú de Windows.

    Son los píxeles de un DIB de 32 bits de arriba abajo (alto negativo en su
    cabecera), BGRA con el alfa PREMULTIPLICADO, que es como Windows compone la
    `hbmpItem` de un `MENUITEMINFOW` con transparencia (`AlphaBlend` con
    `AC_SRC_ALPHA`). Van del color que se pida: el del texto del menú, para que
    siga al tema.
    """
    return _premultiplicado(_capas_rgba([(color, TRAZO, GLIFOS[nombre])], 16.0, size))


def pixeles_marca(size: int, campo: str = CAMPO) -> bytes:
    """Devuelve la marca como imagen de una entrada de menú de Windows.

    Es el icono de un dispositivo en el menú de la bandeja cuando no lleva un
    `.ico` propio que se pueda leer: el formato de `pixeles_menu()`, pero a
    color, con `campo` de fondo (uno de `CAMPOS`).
    """
    return _premultiplicado(_capas_rgba(_capas_marca(size, campo), 64.0, size))


def png_marca(size: int, campo: str = CAMPO) -> bytes:
    """Devuelve la marca como PNG, con `campo` de fondo.

    Es el `icon-data` de dbusmenu (bandeja de Linux) para un dispositivo sin
    `.ico` propio que se pueda leer.
    """
    return _png(_capas_rgba(_capas_marca(size, campo), 64.0, size), size)


MAX_ICO = 4 * 1024 * 1024
"""Bytes que puede ocupar el `.ico` propio de una unidad.

Es lo que `ui/volumen.py` deja poner y lo que se lee, como mucho, para
pintarlo en la bandeja del agente. Uno de verdad cabe de sobra: el de la
marca, con siete tamaños, son 43 KB, y uno con el de 256 px sin comprimir anda
por los 400.
"""
MAX_IMAGENES_ICO = 64
"""Imágenes que se miran, como mucho, en el directorio de un `.ico` ajeno."""
FIRMA_PNG = b"\x89PNG\r\n\x1a\n"
"""Los ocho bytes con que empieza todo PNG (sección 5.2 de la especificación PNG)."""


def _imagenes_ico(datos: bytes) -> list[tuple[int, bytes]]:
    """Devuelve las imágenes cuadradas de un `.ico` como `(lado, bytes)`, sin fiarse de él.

    Lee el ICONDIR (reservado 0, tipo 1 de icono, cuántas imágenes) y una
    ICONDIRENTRY de dieciséis bytes por imagen (ancho y alto, donde 0 es 256;
    colores, reservado, planos, bits, tamaño y desplazamiento), que es lo que
    escribe `_ico_de()`. Se descarta la imagen que no es cuadrada o no cabe en
    el fichero. Un fichero que no es un icono, que pasa de `MAX_ICO` o que dice
    tener más de `MAX_IMAGENES_ICO` imágenes no da ninguna.
    """
    import struct

    if len(datos) < 6 or len(datos) > MAX_ICO:
        return []
    reservado, tipo, cuantas = struct.unpack_from("<HHH", datos, 0)
    if reservado != 0 or tipo != 1 or not 0 < cuantas <= MAX_IMAGENES_ICO:
        return []
    inicio = 6 + 16 * cuantas
    if inicio > len(datos):
        return []
    imagenes = []
    for i in range(cuantas):
        ancho, alto, _colores, _res, _planos, _bits, tam, desde = struct.unpack_from(
            "<BBBBHHII", datos, 6 + 16 * i)
        ancho, alto = ancho or 256, alto or 256
        if ancho != alto or tam == 0 or desde < inicio or desde + tam > len(datos):
            continue
        imagenes.append((ancho, datos[desde:desde + tam]))
    return imagenes


def _png_de_lado(img: bytes, lado: int) -> bool:
    """Indica si una imagen de un `.ico` es un PNG de `lado` × `lado` px.

    Se mira la firma y la cabecera IHDR, que va primero y mide 13 bytes
    (sección 11.2.2 de la especificación PNG). El resto lo decodifica quien lo
    pinte.
    """
    import struct

    if len(img) < 33 or not img.startswith(FIRMA_PNG) or img[8:16] != b"\0\0\0\x0dIHDR":
        return False
    ancho, alto = struct.unpack_from(">II", img, 16)
    return ancho == alto == lado


def _rgba_de_dib(img: bytes, lado: int) -> list[list[tuple]] | None:
    """Devuelve una imagen DIB de 32 bits de un `.ico` como filas de `(r, g, b, a)`.

    Solo entiende la que escribe `_dib()`: BITMAPINFOHEADER de 40 bytes, el
    alto doble (el dibujo y la máscara AND), un plano, 32 bits sin comprimir
    (BI_RGB), BGRA de abajo arriba y el alfa sin premultiplicar. Si ningún
    píxel trae alfa (iconos guardados a 32 bits sin él), la transparencia sale
    de la máscara AND, si está entera.

    Returns:
        Las filas de arriba abajo, o `None` si la imagen es de otra clase.
    """
    import struct

    if len(img) < 40:
        return None
    tam, ancho, alto, planos, bits, compresion = struct.unpack_from("<IiiHHI", img, 0)
    if (tam, ancho, alto, planos, bits, compresion) != (40, lado, 2 * lado, 1, 32, 0):
        return None
    n = lado * lado * 4
    if 40 + n > len(img):
        return None
    pixeles = img[40:40 + n]
    fila_mascara = ((lado + 31) // 32) * 4
    mascara = img[40 + n:40 + n + fila_mascara * lado]
    con_alfa = any(pixeles[3::4])
    con_mascara = len(mascara) == fila_mascara * lado
    filas = []
    for y in range(lado):
        fuente = lado - 1 - y
        fila = []
        for x in range(lado):
            i = (fuente * lado + x) * 4
            b, g, r, a = pixeles[i:i + 4]
            if con_alfa:
                alfa = a / 255
            elif con_mascara:
                alfa = 0.0 if mascara[fuente * fila_mascara + x // 8] & (0x80 >> (x % 8)) \
                    else 1.0
            else:
                alfa = 1.0
            fila.append((r, g, b, alfa))
        filas.append(fila)
    return filas


def png_de_ico(datos: bytes, lado: int) -> bytes | None:
    """Devuelve la imagen de un `.ico` que mejor sirve a `lado` px, como PNG.

    Es el `icon-data` de dbusmenu para el `.ico` propio de una unidad. El
    fichero viene de la unidad y no se da por bueno: se lee con límites
    (`MAX_ICO`, `MAX_IMAGENES_ICO`, cada imagen dentro del fichero, a lo sumo
    256 px, que es lo que cabe en su directorio) y cualquier cosa rara es «no
    hay imagen», nunca una excepción. Se prueba primero la más pequeña de al
    menos `lado` px y luego las demás por cercanía. Un PNG va tal cual tras
    mirar su firma y su IHDR; un DIB de 32 bits se convierte (`_rgba_de_dib()`);
    los de 8 o 24 bits no se entienden.

    Returns:
        Los bytes del PNG, o `None` si ninguna imagen sirve.
    """
    try:
        imagenes = _imagenes_ico(datos)
        for tam, img in sorted(imagenes, key=lambda i: (i[0] < lado, abs(i[0] - lado))):
            if img.startswith(FIRMA_PNG):
                if _png_de_lado(img, tam):
                    return img
                continue
            rgba = _rgba_de_dib(img, tam)
            if rgba is not None:
                return _png(rgba, tam)
    except Exception:                                   # noqa: BLE001
        return None
    return None


def pixmap_bandeja(estado: str, size: int) -> bytes:
    """Devuelve el icono de la bandeja en ese estado para Linux.

    Es el `IconPixmap` de un StatusNotifierItem, que es «ARGB32 … in network
    byte order»: cada píxel A, R, G, B (sin premultiplicar, como el
    `QImage::Format_ARGB32` de KDE) y las filas de arriba abajo. Sin `.ico` de
    por medio: se pinta aquí.
    """
    datos = bytearray()
    for fila in _capas_rgba(capas_bandeja(size, estado), 64.0, size):
        for r, g, b, a in fila:
            datos += bytes((round(a * 255), r, g, b))
    return bytes(datos)


def fichero_bandeja(carpeta, estado: str):
    """Devuelve dónde va el `.ico` de ese estado dentro de la carpeta del agente."""
    from pathlib import Path
    return Path(carpeta) / f"bandeja-{estado}.ico"


def write_bandeja(carpeta, solo_si_faltan: bool = False) -> list:
    """Pinta los cinco iconos de la bandeja en `carpeta` y devuelve las rutas.

    Con `solo_si_faltan`, los que ya están se dejan: es lo que hace el agente
    al arrancar, por si lo instaló una versión que no los pintaba.
    """
    rutas = []
    for estado in BANDEJA_ESTADOS:
        ruta = fichero_bandeja(carpeta, estado)
        if not (solo_si_faltan and ruta.is_file()):
            ruta.write_bytes(ico_bandeja(estado))
        rutas.append(ruta)
    return rutas


def pintar(carpeta, bandeja: bool = False) -> None:
    """Pinta `runsync.ico` en `carpeta` y, con `bandeja`, los cinco de la bandeja.

    Es lo que pinta una instalación (`install.pintar_iconos`).
    """
    from pathlib import Path
    write_ico(Path(carpeta) / "runsync.ico")
    if bandeja:
        write_bandeja(carpeta)


if __name__ == "__main__":                        # python -m ui.icons [destino]
    import sys

    # El `.ico` va DENTRO de la carpeta de la aplicación, junto al código, y no
    # en la raíz del volumen: esa carpeta está oculta, así que un icono suelto
    # entre los datos de la persona sería el único resto visible.
    from common import model                      # solo aquí: APP_DIR vive ahí
    ruta = write_ico(sys.argv[1] if len(sys.argv) > 1
                     else model.APP_DIR / "runsync.ico")
    print(f"Escrito {ruta} ({ruta.stat().st_size / 1024:.0f} KB, "
          f"{len(ICO_TAMANOS)} tamaños)")
