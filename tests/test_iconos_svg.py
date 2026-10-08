#!/usr/bin/env python3
"""Las imágenes de Tk salen igual con SVG que con el pintor de Python.

Con el Tk 9 del dispositivo cada glifo, casilla, disco, baldosa, marca y pieza
de los controles se describe en SVG a partir de las mismas primitivas que usa el
rasterizador (`icons._svg_capas()`, `icons._svg_caja()`) y la pinta Tk en C; sin
SVG (Tk 8.6) o con `icons.USAR_SVG = False` se pintan en Python. Aquí se comprueba:

- que la capacidad se prueba (no se mira la versión), se guarda por intérprete y
  se suelta con `icons.olvidar()`;
- que con SVG no se rasteriza nada en Python (`theme.apply()`, `poner_icono()`)
  y que sin él, o si una imagen no se sabe describir, se cae al rasterizador
  con las mismas medidas;
- que las dos imágenes coinciden en alfa y en color, con tolerancia, a 100, 150
  y 200 %: todos los glifos y una pieza de cada clase de control.

La tolerancia es la de dos rasterizadores distintos. nanosvg reparte cada fila en
cinco franjas, así que una arista horizontal que cae a media altura de un píxel
sale con un alfa múltiplo de 0,2 (±0,1 contra la cobertura exacta); y la
distancia mínima del rasterizador de Python, que mide la tinta más cercana,
cuenta como un solo tramo dos trazos que se tocan a menos de un píxel y se
equivoca por el otro lado en un vértice de inglete (el píxel de la punta del
lápiz sale a 0,5 con ella). Ninguna de las dos cosas se ve: se ve igual.
"""

from __future__ import annotations

import struct
import sys
import zlib

from _harness import Checks, tmpdir

c = Checks("iconos: SVG y pintor de Python")

from ui import icons, theme  # noqa: E402

theme.nitidez()

try:
    import tkinter as tk
    raiz = tk.Tk()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())
raiz.withdraw()

FORZADO = not icons.USAR_SVG
"""Si se ha forzado el pintor de Python con `PRDRIVE_SIN_SVG=1`."""


def lee_png(datos: bytes) -> tuple[int, int, bytes]:
    """Devuelve `(ancho, alto, RGBA)` de un PNG de 8 bits que escribe Tk.

    Tk escribe RGBA sin filtrar, o RGB si la imagen no tiene ningún píxel
    transparente; no hace falta más.
    """
    pos, idat = 8, b""
    while pos < len(datos):
        largo, = struct.unpack(">I", datos[pos:pos + 4])
        trozo = datos[pos + 4:pos + 8]
        if trozo == b"IHDR":
            ancho, alto, prof, tipo = struct.unpack(">IIBB", datos[pos + 8:pos + 18])
        elif trozo == b"IDAT":
            idat += datos[pos + 8:pos + 8 + largo]
        pos += 12 + largo
    crudo = zlib.decompress(idat)
    bytes_px = {6: 4, 2: 3}[tipo]
    paso = ancho * bytes_px + 1
    assert prof == 8 and all(crudo[i * paso] == 0 for i in range(alto)), \
        "Tk escribe un PNG de otra clase que de 8 bits sin filtrar"
    filas = [crudo[i * paso + 1:(i + 1) * paso] for i in range(alto)]
    if tipo == 2:                                 # sin alfa: todo opaco
        filas = [b"".join(fila[j:j + 3] + b"\xff" for j in range(0, len(fila), 3))
                 for fila in filas]
    return ancho, alto, b"".join(filas)


ESCRITORIO = tmpdir("prdrive-svg-")
"""Dónde se escriben los PNG con los que se lee lo que Tk ha pintado."""


def pixeles(img) -> tuple[int, int, bytes]:
    """Devuelve `(ancho, alto, RGBA)` de una imagen de Tk, con el alfa de verdad.

    `transparency_get()` solo dice si es del todo transparente: para el matiz
    hay que sacar la imagen a un PNG y leerlo.
    """
    ruta = ESCRITORIO / "img.png"
    img.write(str(ruta), format="png")
    return lee_png(ruta.read_bytes())


def en(rgba, fondo: tuple[int, int, int]) -> list[tuple[float, float, float]]:
    """Devuelve la imagen compuesta contra `fondo`, píxel a píxel."""
    salida = []
    for i in range(0, len(rgba), 4):
        a = rgba[i + 3] / 255
        salida.append(tuple(rgba[i + k] * a + fondo[k] * (1 - a) for k in range(3)))
    return salida


def hexa(color: str) -> tuple[int, int, int]:
    """Devuelve un `#rrggbb` como `(r, g, b)`."""
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def comparar(a, b, fondo: str = theme.PAPEL, zona=None) -> dict:
    """Mide en qué se diferencian dos imágenes `(ancho, alto, RGBA)` de la misma medida.

    Args:
        fondo: Contra qué se compone el color: el sitio donde caen de verdad.
        zona: Los índices de píxel que cuentan (por omisión, todos).

    Returns:
        `alfa` y `color`, cada uno con su diferencia media y máxima (0 a 1), y
        `opaco`: lo más que se separa el color de un píxel opaco en las dos.
    """
    assert a[:2] == b[:2], f"medidas distintas: {a[:2]} y {b[:2]}"
    indices = range(a[0] * a[1]) if zona is None else zona
    ca, cb = en(a[2], hexa(fondo)), en(b[2], hexa(fondo))
    sa = sc = ma = mc = 0.0
    opaco = 0
    for i in indices:
        da = abs(a[2][4 * i + 3] - b[2][4 * i + 3]) / 255
        dc = max(abs(x - y) for x, y in zip(ca[i], cb[i])) / 255
        sa, sc, ma, mc = sa + da, sc + dc, max(ma, da), max(mc, dc)
        if a[2][4 * i + 3] == b[2][4 * i + 3] == 255:
            opaco = max(opaco, max(abs(a[2][4 * i + k] - b[2][4 * i + k]) for k in range(3)))
    n = len(indices)
    return {"alfa": (sa / n, ma), "color": (sc / n, mc), "opaco": opaco}


CAIDAS: list = []
"""Las imágenes del lado SVG de `con_los_dos()` que no han salido del SVG.

Sin mirarlo, una imagen que se cae en silencio al pintor de Python (lo correcto
en producción) se compararía consigo misma y la comparación saldría siempre bien.
"""


def formato(img) -> str:
    """Devuelve con qué formato hizo Tk la imagen: «svg», o "" para el PNG de Python."""
    valor = img.cget("format")
    if isinstance(valor, tuple):
        valor = valor[0] if valor else ""
    return str(valor)


def con_los_dos(hacer):
    """Devuelve lo que `hacer()` da con SVG y lo que da con el pintor de Python.

    Con un Tk que lee SVG, apunta en `CAIDAS` lo que del lado SVG no salió de él.
    """
    icons.USAR_SVG = True
    con_svg = hacer()
    img = con_svg[0] if isinstance(con_svg, tuple) else con_svg
    if img is not None and icons.svg_disponible(raiz) and formato(img) != "svg":
        CAIDAS.append((img.width(), img.height()))
    icons.USAR_SVG = False
    try:
        con_python = hacer()
    finally:
        icons.USAR_SVG = not FORZADO
    return con_svg, con_python


# ---------------------------------------------------------------- 1. la capacidad
def sonda_directa() -> bool:
    """Lo que dice Tk de verdad: si da una imagen de un SVG."""
    try:
        tk.PhotoImage(master=raiz, data=icons._SVG_PRUEBA, format="svg")
        return True
    except tk.TclError:
        return False


icons.USAR_SVG = True                 # la capacidad se prueba aunque se haya forzado el pintor de Python
tiene_svg = sonda_directa()
if tk.TkVersion < 9:
    c("Tk 8.6 no lee SVG: la prueba lo dice y se cae al pintor de Python",
      (tiene_svg, icons.svg_disponible(raiz)), (False, False))
else:
    c("el Tk 9 del dispositivo lee SVG", tiene_svg, True)
    c("  y la prueba de capacidad lo dice", icons.svg_disponible(raiz), True)

# la respuesta se guarda por intérprete: la segunda vez no se le pide nada a Tk
icons._SVG.pop(id(raiz.tk), None)
creadas = []
real_foto = tk.PhotoImage


class FotoContada(real_foto):
    """Cuenta las imágenes que se crean."""

    def __init__(self, *a, **k):
        creadas.append(k.get("format"))
        super().__init__(*a, **k)


tk.PhotoImage = FotoContada
try:
    icons.svg_disponible(raiz)
    icons.svg_disponible(raiz)
    icons.svg_disponible(raiz)
finally:
    tk.PhotoImage = real_foto
c("la capacidad se prueba una vez por intérprete, con un SVG", creadas, ["svg"])
c("  y se queda guardada, con su intérprete", icons._SVG[id(raiz.tk)][0] is raiz.tk, True)

# se suelta con el intérprete
icons.olvidar(raiz.tk)
c("`olvidar()` suelta la respuesta del intérprete", id(raiz.tk) in icons._SVG, False)
icons.svg_disponible(raiz)

# no se decide por la versión: un Tk 9 que no sepa leer SVG cae al pintor de Python
icons._SVG.pop(id(raiz.tk), None)


class FotoSinSvg(real_foto):
    """Un Tk que no sabe leer SVG, sea cual sea su versión."""

    def __init__(self, *a, **k):
        if k.get("format") == "svg":
            self.name = None                  # `Image.__del__` lo mira aunque no se haya creado
            raise tk.TclError('image format "svg" is not supported')
        super().__init__(*a, **k)


tk.PhotoImage = FotoSinSvg
try:
    antes = dict(icons.PINTADAS)
    sin = icons.get(raiz, "plus", 16, "#112233")
    c("un intérprete que no lee SVG se reconoce por probarlo", icons.svg_disponible(raiz), False)
    c("  y la imagen sale del pintor de Python, entera",
      (icons.PINTADAS["svg"] - antes["svg"], icons.PINTADAS["python"] - antes["python"],
       (sin.width(), sin.height())), (0, 1, (icons.px(raiz, 16),) * 2))
finally:
    tk.PhotoImage = real_foto
    icons._SVG.pop(id(raiz.tk), None)

icons.USAR_SVG = not FORZADO

# ---------------------------------------------------------------- 2. nada se rasteriza en Python con SVG
llamadas = []
real_capas = icons._capas_rgba


def capas_contadas(*a, **k):
    """Cuenta cada vez que se rasteriza algo en Python."""
    llamadas.append(a[1:3] if len(a) > 2 else a)
    return real_capas(*a, **k)


icons._capas_rgba = capas_contadas
try:
    antes = dict(icons.PINTADAS)
    theme.apply(raiz)
    hechas = {k: icons.PINTADAS[k] - antes[k] for k in antes}
    if icons.svg_disponible(raiz):
        c("`theme.apply()` pinta todo con SVG", (hechas["python"], hechas["svg"] > 0), (0, True))
        c("  y no rasteriza ni una pieza en Python", llamadas, [])
    else:
        c("sin SVG `theme.apply()` lo pinta todo en Python",
          (hechas["svg"], hechas["python"] > 0, len(llamadas) > 0), (0, True, True))

    ventana = tk.Toplevel(raiz)
    ventana.withdraw()
    antes, llamadas[:] = dict(icons.PINTADAS), []
    icons.poner_icono(ventana)
    hechas = {k: icons.PINTADAS[k] - antes[k] for k in antes}
    if icons.svg_disponible(raiz):
        c("`poner_icono()` hace sus tres marcas (64, 32 y 16) con SVG",
          (hechas["svg"], hechas["python"], llamadas), (3, 0, []))
    else:
        c("sin SVG `poner_icono()` hace sus tres marcas en Python",
          (hechas["svg"], hechas["python"]), (0, 3))
    ventana.destroy()

    # lo que se pinta en cada pantalla: chips con y sin icono, avisos de cada tono e
    # iconos de botón (con su `bajar` fraccionario, `theme.icono_linea`)
    from tkinter import ttk
    antes, llamadas[:] = dict(icons.PINTADAS), []
    muestra = ttk.Frame(raiz)
    for tipo in ("", "Ok.", "Aviso.", "Peligro.", "Acento.", "Apagado."):
        theme.chip(muestra, "x", tipo, "sync")
        theme.chip(muestra, "x", tipo)
    for tono in ("Ambar.", "Rojo.", "Azul.", "Verde."):
        theme.aviso(muestra, "t", "c", tono)
    boton = ttk.Button(muestra, text="hola")
    for glifo in ("sync", "gear", "parejas", "edit", "file", "trash"):
        theme.boton_icono(boton, glifo, theme.TINTA2, theme.PAPEL)
    hechas = {k: icons.PINTADAS[k] - antes[k] for k in antes}
    if icons.svg_disponible(raiz):
        c("chips, avisos e iconos de botón también salen del SVG",
          (hechas["python"], hechas["svg"] > 0, llamadas), (0, True, []))
    muestra.destroy()

    # una imagen que no se sabe describir (la pastilla de la marca se recorta del
    # campo y sin el color de lo de detrás no hay con qué) sale del rasterizador
    llamadas[:] = []
    antes = dict(icons.PINTADAS)
    hueca = icons.marca_estado(raiz, 40, icons.AVISO)
    c("una imagen que no se sabe describir se pinta en Python, con su medida",
      (icons.PINTADAS["svg"] - antes["svg"], icons.PINTADAS["python"] - antes["python"],
       (hueca.width(), hueca.height()), len(llamadas) > 0),
      (0, 1, (icons.px(raiz, 40),) * 2, True))

    # …y una imagen que Tk saca de otro tamaño que el pedido, también
    real_svg = icons._svg_capas
    icons._svg_capas = lambda *a, **k: (real_svg(*a, **k)[0], 7, 7)
    try:
        antes = dict(icons.PINTADAS)
        torcida = icons.get(raiz, "pausa", 16, "#445566", alto=21)
        c("una imagen de otro tamaño que el esperado se descarta y se repinta en Python",
          (icons.PINTADAS["svg"] - antes["svg"], icons.PINTADAS["python"] - antes["python"],
           (torcida.width(), torcida.height())),
          (0, 1, (icons.px(raiz, 16), 21)))
    finally:
        icons._svg_capas = real_svg
finally:
    icons._capas_rgba = real_capas

# el interruptor: con `USAR_SVG` apagado se pinta en Python aunque Tk lea SVG, y la
# caché no mezcla los dos caminos
icons.USAR_SVG = False
c("con `USAR_SVG` apagado la capacidad se contesta que no", icons.svg_disponible(raiz), False)
antes = dict(icons.PINTADAS)
a = icons.get(raiz, "parejas", 15, "#778899")
c("  y la imagen sale del pintor de Python",
  (icons.PINTADAS["svg"] - antes["svg"], icons.PINTADAS["python"] - antes["python"]), (0, 1))
icons.USAR_SVG = not FORZADO
b = icons.get(raiz, "parejas", 15, "#778899")
c("  y al encenderlo no devuelve la del otro camino, y es de la misma medida",
  ((b is a) if icons.svg_disponible(raiz) else None, (a.width(), a.height()) == (b.width(), b.height())),
  (False if icons.svg_disponible(raiz) else None, True))

# ---------------------------------------------------------------- 3. el parecido
if not icons.svg_disponible(raiz):
    print("  (saltado) " + ("forzado el pintor de Python (PRDRIVE_SIN_SVG)" if FORZADO
                            else "sin SVG no hay con qué comparar el pintor de Python"))
    raiz.destroy()
    sys.exit(c.report())

ESCALAS = (("100 %", 1.3333), ("150 %", 2.0), ("200 %", 2.6667))
"""`tk scaling` de cada escala: 1,3333 son los 96 ppp para los que están pensadas las medidas."""

TOLERANCIA_GLIFOS = 0.02
"""La diferencia media de alfa de todos los glifos juntos, en cada escala."""
TOLERANCIA_GLIFO = 0.04
"""La de un glifo suelto: el que más se separa (`nas`, a 150 %) mide 0,033."""
TOLERANCIA_PUNTO = 0.55
"""Lo más que se separa un píxel: 0,50 en la punta del lápiz, donde el rasterizador de Python se equivoca."""

glifos_por_escala = {}
peores = {}
for etiqueta, escala in ESCALAS:
    raiz.tk.call("tk", "scaling", escala)
    medias, peor_punto, peor_media = [], ("", 0.0), ("", 0.0)
    colores = 0
    for nombre in sorted(icons.GLIFOS):
        con_svg, con_python = con_los_dos(lambda: icons.get(raiz, nombre, 16, theme.TINTA))
        m = comparar(pixeles(con_svg), pixeles(con_python))
        medias.append(m["alfa"][0])
        colores = max(colores, m["opaco"])
        peor_punto = max(peor_punto, (nombre, m["alfa"][1]), key=lambda x: x[1])
        peor_media = max(peor_media, (nombre, m["alfa"][0]), key=lambda x: x[1])
    glifos_por_escala[etiqueta] = sum(medias) / len(medias)
    peores[etiqueta] = (peor_media, peor_punto)
    c(f"glifos a {etiqueta}: la diferencia media de alfa es de {sum(medias) / len(medias):.2%}"
      f" (≤ {TOLERANCIA_GLIFOS:.0%})", sum(medias) / len(medias) <= TOLERANCIA_GLIFOS, True)
    c(f"  el que más se separa es «{peor_media[0]}», {peor_media[1]:.2%} (≤ {TOLERANCIA_GLIFO:.0%})",
      peor_media[1] <= TOLERANCIA_GLIFO, True)
    c(f"  y el píxel que más es «{peor_punto[0]}», {peor_punto[1]:.2f} (≤ {TOLERANCIA_PUNTO})",
      peor_punto[1] <= TOLERANCIA_PUNTO, True)
    c("  los píxeles opacos son del mismo color (±2 de redondeo)", colores <= 2, True)

# todos los glifos con las medidas de alineación que usa el tema: baja con decimales, más alto que ancho
raiz.tk.call("tk", "scaling", 1.3333)
for bajar, alto in ((2, 21), (1.5, 21), (0.25, None), (0, None)):
    con_svg, con_python = con_los_dos(lambda: icons.get(raiz, "parejas", 15, theme.ACENTO,
                                                         bajar=bajar, alto=alto))
    medida_esperada = (icons.px(raiz, 15), alto or (int(bajar) + icons.px(raiz, 15) + (1 if bajar % 1 else 0)))
    m = comparar(pixeles(con_svg), pixeles(con_python))
    c(f"bajar={bajar}, alto={alto}: misma medida {medida_esperada} y alfa a {m['alfa'][0]:.2%}",
      ((con_svg.width(), con_svg.height()) == (con_python.width(), con_python.height())
       == medida_esperada, m["alfa"][0] <= TOLERANCIA_GLIFO), (True, True))

# el resto de lo que se pinta con SVG: casillas, opciones, discos, baldosas, marcas
TOLERANCIA_FIGURA = 0.03
"""La diferencia media de alfa de una casilla, un disco, una baldosa o una marca: 0,023 es lo mayor."""
TOLERANCIA_COLOR = 0.03
"""La diferencia media de color, compuesto sobre el fondo de la figura."""
TOLERANCIA_PUNTO_FIGURA = 0.55
"""El píxel que más se separa en ellas: 0,50 en el borde de un disco a 150 %."""
for etiqueta, escala in ESCALAS:
    raiz.tk.call("tk", "scaling", escala)
    figuras = [(f"casilla {e}", lambda e=e: icons.casilla(raiz, e), theme.PAPEL)
               for e in ("marcada", "vacia", "apagada", "apagada-marcada")]
    figuras += [(f"opción {e}", lambda e=e: icons.opcion(raiz, e), theme.PAPEL)
                for e in ("marcada", "vacia", "apagada", "apagada-marcada")]
    figuras += [("disco ok", lambda: icons.disco(raiz, "ok", theme.OK, theme.SOBRE_OK,
                                                 theme.GRIS_FONDO), theme.GRIS_FONDO),
                ("disco hueco", lambda: icons.disco(raiz, "alert", theme.AVISO, theme.SOBRE_AVISO,
                                                    theme.GRIS_FONDO, hueco=True),
                 theme.GRIS_FONDO),
                ("baldosa", lambda: icons.baldosa(raiz, "alert", theme.AVISO, theme.SOBRE_AVISO,
                                                  theme.PAPEL), theme.PAPEL)]
    figuras += [(f"marca {lado} px", lambda lado=lado: icons.app_icon(raiz, lado), theme.PAPEL)
                for lado in (64, 32, 16)]
    figuras += [(f"marca {campo}", lambda campo=campo: icons.app_icon(raiz, 64, icons.CAMPOS[campo]),
                 theme.PAPEL) for campo in ("verde", "granate")]
    # la pastilla se recorta del campo: con SVG es del color del fondo, y en pantalla da lo mismo
    figuras += [(f"marca {estado} con su pastilla",
                 lambda estado=estado: icons.marca_estado(raiz, 40, estado, fondo=theme.PAPEL),
                 theme.PAPEL) for estado in icons.BANDEJA_ESTADOS]
    peor = ("", 0.0)
    peor_pixel = ("", 0.0)
    peor_color = ("", 0.0)
    for nombre, hacer, fondo in figuras:
        con_svg, con_python = con_los_dos(hacer)
        m = comparar(pixeles(con_svg), pixeles(con_python), fondo)
        # la pastilla de la bandeja se recorta: contra el fondo es la imagen que se ve
        medida = m["color"] if "pastilla" in nombre else m["alfa"]
        peor = max(peor, (nombre, medida[0]), key=lambda x: x[1])
        peor_pixel = max(peor_pixel, (nombre, medida[1]), key=lambda x: x[1])
        peor_color = max(peor_color, (nombre, m["color"][0]), key=lambda x: x[1])
    c(f"figuras a {etiqueta}: la que más se separa es «{peor[0]}», {peor[1]:.2%}"
      f" (≤ {TOLERANCIA_FIGURA:.0%})", peor[1] <= TOLERANCIA_FIGURA, True)
    c(f"  y el píxel que más es de «{peor_pixel[0]}», {peor_pixel[1]:.2f}"
      f" (≤ {TOLERANCIA_PUNTO_FIGURA})", peor_pixel[1] <= TOLERANCIA_PUNTO_FIGURA, True)
    c(f"  y la que más en color, compuesta sobre su fondo, es «{peor_color[0]}», {peor_color[1]:.2%}"
      f" (≤ {TOLERANCIA_COLOR:.0%})", peor_color[1] <= TOLERANCIA_COLOR, True)

# las piezas de los controles: una de cada clase de las que pinta `theme.apply()`
TONOS = [
    ("borde de 1 px", [(theme.BORDE, 0), (theme.SUPERFICIE, 1)], 4, "1111"),
    ("relleno", [(theme.ACENTO, 0)], 4, "1111"),
    ("foco por dentro", [(theme.ACENTO, 0), (theme.SUPERFICIE, 2)], 4, "1111"),
    ("foco con filete", [(theme.ACENTO, 0), (theme.SUPERFICIE, 1), (theme.ACENTO, 2)], 4, "1111"),
    ("aro hueco", [(theme.ACENTO, 0), (None, 2)], 4, "1111"),
    ("aro fino hueco", [(theme.ACENTO, 0), (None, 1)], 10, "1111"),
    ("todo transparente", [(None, 0)], 4, "1111"),
    ("filete y aro", [(None, 0), (theme.ACENTO, 1), (None, 2)], 4, "1111"),
    ("píldora", [(theme.OK, 0)], 10, "1111"),
    ("píldora con borde", [(theme.BORDE, 0), (theme.SUPERFICIE, 1)], 10, "1111"),
    ("radio fino", [(theme.BORDE, 0), (theme.SUPERFICIE, 1)], 2, "1111"),
    ("izquierda redonda", [(theme.BORDE, 0), (theme.SUPERFICIE, 1)], 4, "1001"),
    ("derecha redonda", [(theme.BORDE, 0), (theme.SUPERFICIE, (0, 1, 1, 1))], 4, "0110"),
    ("centro de un grupo", [(theme.BORDE, 0), (theme.SUPERFICIE, (0, 1, 1, 1))], 4, "0000"),
    ("sin esquinas", [(theme.BORDE, 0), (theme.SUPERFICIE, 2)], 4, "0000"),
    ("sin radio", [(theme.BORDE, 0), (theme.SUPERFICIE, 1)], 0, "1111"),
]
TOLERANCIA_PIEZA = 0.03
"""La diferencia media de alfa en las cuatro esquinas de una pieza (lo demás es plano).

La que más se separa es la de radio 2 a 100 %: 0,026, porque la curva de cinco
píxeles se reparte en cuatro y el píxel de la esquina sale a 0,24 con SVG (el
área de verdad) y a 0,38 con la distancia al borde.
"""
TOLERANCIA_PUNTO_PIEZA = 0.20
"""Lo más que se separa un píxel de una pieza: 0,18 en una esquina de 200 %."""
for etiqueta, escala in ESCALAS:
    raiz.tk.call("tk", "scaling", escala)
    peor = ("", 0.0)
    peor_pixel = ("", 0.0)
    medidas, centros, transparencias = [], [], []
    for nombre, tonos, radio, esquinas in TONOS:
        (img_svg, borde_svg), (img_py, borde_py) = con_los_dos(
            lambda: icons.caja(raiz, tonos, radio, esquinas))
        ancho, alto = img_svg.width(), img_svg.height()
        medidas.append(((ancho, alto, borde_svg) == (img_py.width(), img_py.height(), borde_py)
                        and ancho == 2 * borde_svg + icons.CENTRO_ANCHO
                        and alto == 2 * borde_svg + icons.CENTRO_ALTO))
        pa, pb = pixeles(img_svg), pixeles(img_py)
        # las cuatro esquinas de `borde` × `borde`: lo único que no es plano
        zona = [y * ancho + x for y in range(alto) for x in range(ancho)
                if (x < borde_svg or x >= ancho - borde_svg)
                and (y < borde_svg or y >= alto - borde_svg)]
        m = comparar(pa, pb, theme.PAPEL, zona)
        peor = max(peor, (nombre, m["alfa"][0]), key=lambda x: x[1])
        peor_pixel = max(peor_pixel, (nombre, m["alfa"][1]), key=lambda x: x[1])
        medio = (alto // 2) * ancho + ancho // 2
        centro_svg, centro_py = pa[2][4 * medio:4 * medio + 4], pb[2][4 * medio:4 * medio + 4]
        centros.append(centro_svg[3] == centro_py[3] and (centro_svg[3] == 0 or centro_svg == centro_py))
        esquinas_t = [(img_svg.transparency_get(x, y), img_py.transparency_get(x, y))
                      for x, y in ((0, 0), (ancho - 1, 0), (0, alto - 1), (ancho - 1, alto - 1),
                                   (ancho // 2, alto // 2))]
        if radio >= 4:
            transparencias.append(all(s == p for s, p in esquinas_t))
        else:
            # con un radio de 2 o 3 px el píxel de la esquina cae en la curva y SVG le da una
            # cobertura de milésimas que el rasterizador de Python redondea a cero
            alfas = [(pa[2][4 * (y * ancho + x) + 3], pb[2][4 * (y * ancho + x) + 3])
                     for x, y in ((0, 0), (ancho - 1, 0), (0, alto - 1), (ancho - 1, alto - 1))]
            transparencias.append(all(abs(s - p) <= 51 for s, p in alfas)
                                  and esquinas_t[-1][0] == esquinas_t[-1][1])
    c(f"piezas a {etiqueta}: la que más se separa es «{peor[0]}», {peor[1]:.2%}"
      f" en sus esquinas (≤ {TOLERANCIA_PIEZA:.0%})", peor[1] <= TOLERANCIA_PIEZA, True)
    c(f"  y el píxel que más es de «{peor_pixel[0]}», {peor_pixel[1]:.2f}"
      f" (≤ {TOLERANCIA_PUNTO_PIEZA})", peor_pixel[1] <= TOLERANCIA_PUNTO_PIEZA, True)
    c("  misma medida, mismo borde, y el centro ensanchado de 256×64", all(medidas), True)
    c("  el centro de la pieza es el mismo píxel exacto (color y alfa)", all(centros), True)
    c("  esquinas y centro transparentes o no como en el pintor de Python (con radio 2 o 3, a 0,2)",
      all(transparencias), True)

c("en el lado SVG de cada comparación, todas las imágenes salieron del SVG", CAIDAS, [])
raiz.destroy()
sys.exit(c.report())
