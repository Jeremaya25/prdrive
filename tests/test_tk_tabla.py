#!/usr/bin/env python3
"""La tabla de un lienzo (`ui/tk_tabla.py`): lo que dibuja, cómo se elige y qué toca al cambiar.

La lista de «Parejas» es una `TablaLienzo`: un `tk.Canvas` con rectángulos,
textos e imágenes en lugar de nueve widgets por fila. Aquí se prueba la tabla
sola:

- lo que dibuja (`leer()`), con la ruta que no cabe cortada con «…» y vuelta a
  cortar cuando el lienzo cambia de ancho;
- que cambia en su sitio: las mismas filas no tocan ningún elemento, un chip que
  cambia solo toca su fila, elegir repinta dos filas, y tras cualquier serie de
  `poner()` se dibuja lo mismo que en una tabla nueva;
- el teclado (↑/↓, Inicio/Fin, RePág/AvPág, Intro, `puede_dejar`), el clic, el
  ratón encima, el anillo del foco y la rueda, que es del `Visor`;
- que un chip y una etiqueta miden lo que miden en ttk, a varias escalas, y que
  lo que asoma por las esquinas de un chip es el color de su fila: normal,
  elegida, ámbar y roja (el fallo de las esquinas de 0.7.0 no puede volver);
- los dos temas.

Los ayudantes nuevos de `theme` (`mezcla`, `colores_chip`, `rol_texto`) se prueban
sin pantalla; el resto se salta sin ella.
"""

from __future__ import annotations

import random
import shutil
import subprocess
import sys

from _harness import Checks

c = Checks("tabla de un lienzo: dibujo, cambios en su sitio, teclado y ratón")

from ui import theme  # noqa: E402

# ---------------------------------------------------------------------------
# 1. Los ayudantes del tema, sin pantalla
# ---------------------------------------------------------------------------
c("mezcla: con 0 es el primero", theme.mezcla("#102030", "#FFFFFF", 0), "#102030")
c("  con 1 el segundo", theme.mezcla("#102030", "#FFFFFF", 1), "#FFFFFF")
c("  en medio, canal a canal y redondeado", theme.mezcla("#000000", "#FF8001", 0.5), "#804000")
c("  en mayúsculas", theme.mezcla("#ffffff", "#ffffff", 0.3), "#FFFFFF")
malos = []
for args in (("#FFF", "#000000", 0.5), ("#000000", "000000", 0.5), ("#000000", "#FFFFFF", 1.2),
             ("#000000", "#FFFFFF", -0.1)):
    try:
        theme.mezcla(*args)
    except ValueError:
        malos.append(args[2])
c("  un color que no es #RRGGBB o una fracción fuera de [0, 1] es un ValueError",
  malos, [0.5, 0.5, 1.2, -0.1])

for tema in ("claro", "oscuro"):
    theme.usar(tema)
    p = f"{tema}: "
    c(p + "colores_chip de un estado: su disco, la letra de encima y su glifo",
      theme.colores_chip("Ok."),
      (theme.GRIS_FONDO, theme.LINEA, theme.TINTA, theme.OK, theme.SOBRE_OK, "ok"))
    c(p + "  «warn» se dibuja como «alert»", theme.colores_chip("Aviso.", "warn")[3:],
      (theme.AVISO, theme.SOBRE_AVISO, "alert"))
    c(p + "  el apagado es un aro sobre el papel, con el reloj",
      theme.colores_chip("Apagado."),
      (theme.PAPEL, theme.BORDE, theme.TINTA3, theme.TINTA3, theme.SUPERFICIE, "clock"))
    c(p + "  uno neutro no lleva disco: su icono en tinta suave, o nada",
      (theme.colores_chip("", "both")[3:], theme.colores_chip("")[3:]),
      ((None, theme.TINTA2, "both"), (None, theme.TINTA2, None)))
    c(p + "  un tipo que no existe es el neutro", theme.colores_chip("Raro.", "up"),
      theme.colores_chip("", "up"))
    c(p + "rol_texto: el del rol sobre una superficie que no manda",
      (theme.rol_texto("Fuerte.", "Card."), theme.rol_texto("MonoPista.", "NotaAzul.")),
      ((theme.TINTA, "fuerte"), (theme.TINTA3, "mono_pequena")))
    c(p + "  sobre el rojo todo es PELIGRO", theme.rol_texto("Mono.", "Rojo."),
      (theme.PELIGRO, "mono"))
    c(p + "  y un rol que no existe es el texto corriente", theme.rol_texto("Raro."),
      (theme.TINTA, "texto"))
theme.usar("claro")

try:
    import tkinter as tk
    from tkinter import ttk
    raiz = tk.Tk()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from ui import icons, tk_tabla  # noqa: E402
from ui import tk as uitk  # noqa: E402
from ui.tk import CeldaChip, CeldaIcono, CeldaTexto, FilaTabla  # noqa: E402
from ui.tk_tabla import CeldaCasilla, TablaLienzo  # noqa: E402

errores: list[str] = []


def anotar_errores(r) -> None:
    """Apunta las excepciones de los manejadores de Tk de `r` en vez de imprimirlas."""
    r.report_callback_exception = (
        lambda tipo, valor, _tb: errores.append(f"{tipo.__name__}: {valor}"))


COLUMNAS = (("", 0, False), ("Pareja", 0, False), ("Local ↔ remoto", 200, True),
            ("Modo", 0, False), ("Estado", 0, False))


def fila(nombre: str, ruta: str | None = None, modo=("bisync", "", "both"),
         estado=("ok", "Ok.", None), tono: str = "", marcada: bool = True) -> FilaTabla:
    """Una fila como las de «Parejas»."""
    return FilaTabla(nombre, (CeldaCasilla(marcada), CeldaTexto(nombre, "Fuerte."),
                              CeldaTexto(ruta or f"sync-data/{nombre} ↔ nas:/R/{nombre}", "Mono."),
                              CeldaChip(*modo), CeldaChip(*estado)), tono)


LARGA = "sync-data/" + "una-carpeta/" * 30 + "fin ↔ nas:/R/larga"
FILAS = [fila("documentos"),
         fila("larga", LARGA, estado=("pide resync", "Aviso.", None), tono="aviso"),
         fila("copias", modo=("up-mirror", "Peligro.", "up"), estado=("espejo", "Peligro.", None),
              tono="peligro"),
         fila("videos", marcada=False, estado=("no se usa aquí", "Apagado.", None),
              modo=("up", "", "up"), tono="apagado")]


def ventana(r, ancho: int = 700):
    """Un diálogo enseñado con un marco de `ancho` medidas de diseño para la tabla.

    Returns:
        `(diálogo, marco)`: la tabla va en la fila 1 del marco, estirada.
    """
    dlg = uitk.modal(r, "Tabla")
    marco = ttk.Frame(dlg, padding=theme.E4)
    marco.grid(row=0, column=0, sticky="nsew")
    marco.columnconfigure(0, weight=1)
    marco.relleno = ttk.Frame(marco, width=icons.px(marco, ancho), height=1)
    marco.relleno.grid(row=0, column=0)
    return dlg, marco


def enseñar(r, dlg) -> None:
    """Enseña el diálogo y deja que se coloque y se pinte."""
    r.deiconify()
    uitk.ensenar(dlg)
    dlg.update()


def tabla_en(marco, **k) -> TablaLienzo:
    """Una tabla de «Parejas» colocada en el marco."""
    t = TablaLienzo(marco, COLUMNAS, **k)
    t.marco.grid(row=1, column=0, sticky="ew")
    return t


def opciones(cv, item) -> tuple:
    """Lo que se ve de un elemento: tipo, sitio y aspecto (sin las etiquetas internas)."""
    tipo = cv.type(item)
    claves = {"rectangle": ("fill", "outline", "state"),
              "text": ("text", "fill", "font", "anchor", "state"),
              "image": ("image", "anchor", "state")}.get(tipo, ())
    etiquetas = tuple(sorted(t for t in cv.gettags(item)
                             if not (t[:1] == "r" and t[1:].isdigit()) and t != "current"))
    return (tipo, tuple(round(float(x)) for x in cv.coords(item)),
            tuple(str(cv.itemcget(item, k)) for k in claves), etiquetas)


def a_la_vista(cv) -> list[int]:
    """Los elementos del lienzo menos los textos ocultos que sujetan las letras."""
    return [i for i in cv.find_all() if "letra" not in cv.gettags(i)]


def dibujo(t: TablaLienzo) -> list:
    """Todo lo que hay dibujado, como una lista ordenada (el orden de creación no cuenta)."""
    cv = t.marco
    return sorted(opciones(cv, i) for i in a_la_vista(cv))


def estado_elementos(t: TablaLienzo) -> dict:
    """Cada elemento a la vista del lienzo por su número, con lo que se ve de él."""
    cv = t.marco
    return {i: opciones(cv, i) for i in a_la_vista(cv)}


def apilado_bien(t: TablaLienzo) -> bool:
    """La tarjeta va debajo de todo y el anillo encima de todo."""
    cv = t.marco
    capas = []
    for i in cv.find_all():
        etiquetas = cv.gettags(i)
        capas.append(0 if "tarjeta" in etiquetas else 2 if "anillo" in etiquetas else 1)
    return capas == sorted(capas)


def de_la_columna(t: TablaLienzo, iid: str, col: int, clase: str) -> list[int]:
    """Los elementos de esa fila, columna y clase (`texto`, `pildora`, `adorno`, `imagen`)."""
    cv = t.marco
    return [i for i in t.elementos(iid) if {f"c{col}", clase} <= set(cv.gettags(i))]


anotar_errores(raiz)
raiz.withdraw()
theme.apply(raiz)

# ---------------------------------------------------------------------------
# 2. Lo que dibuja
# ---------------------------------------------------------------------------
dlg, marco = ventana(raiz)
elegidas: list[str] = []
t = tabla_en(marco, al_elegir=lambda: elegidas.append(t.elegida))
cambio = t.poner(FILAS)
c("poner() dice que la tabla pide otro tamaño", cambio, True)
c("la cabecera: los títulos de las columnas", t.cabeceras, [col[0] for col in COLUMNAS])
c("antes de enseñarla ya se dibuja, al ancho que pide", len(t.leer()), 4)
enseñar(raiz, dlg)
cv = t.marco
leido = t.leer()
c("leer(): casilla, nombre, ruta, modo y estado",
  leido[0], ("☑", "documentos", "sync-data/documentos ↔ nas:/R/documentos", "bisync", "ok"))
c("  una casilla vacía y un chip apagado", (leido[3][0], leido[3][4]), ("☐", "no se usa aquí"))
c("  la ruta larga sale cortada con «…»",
  (leido[1][2].endswith("…"), LARGA.startswith(leido[1][2][:-1]), len(leido[1][2]) < len(LARGA)),
  (True, True, True))


def cabe_la_ruta(iid: str) -> bool:
    """El texto de la ruta acaba antes de que empiece la columna del modo."""
    texto = de_la_columna(t, iid, 2, "texto")[0]
    chip = de_la_columna(t, iid, 3, "pildora")[0]
    return cv.bbox(texto)[2] <= cv.coords(chip)[0]


c("  y enseñada cabe en su columna", cabe_la_ruta("larga"), True)
c("  la tabla ocupa el ancho que le da la pantalla, no el de la ruta",
  cv.winfo_width(), marco.relleno.winfo_width())
antes = t.leer()[1][2]
marco.relleno.configure(width=icons.px(marco, 1100))
dlg.update()
despues = t.leer()[1][2]
c("con la pantalla más ancha se ve más de la ruta, y sigue cabiendo",
  (len(despues) > len(antes), despues.endswith("…"), cabe_la_ruta("larga")), (True, True, True))
x_modo = cv.coords(de_la_columna(t, "documentos", 3, "pildora")[0])[0]
marco.relleno.configure(width=icons.px(marco, 700))
dlg.update()
c("  y al estrecharla vuelve a lo de antes (lo de la derecha se desplaza con ella)",
  (t.leer()[1][2], cv.coords(de_la_columna(t, "documentos", 3, "pildora")[0])[0] < x_modo),
  (antes, True))
c("  una ruta que cabe no se corta", t.leer()[0][2], "sync-data/documentos ↔ nas:/R/documentos")
c("la tarjeta debajo, el anillo encima", apilado_bien(t), True)

# ---------------------------------------------------------------------------
# 3. Cambia en su sitio
# ---------------------------------------------------------------------------
antes = estado_elementos(t)
cambio = t.poner(list(FILAS))
c("poner() de las mismas filas no toca ningún elemento", estado_elementos(t), antes)
c("  ni dice que cambie el tamaño", cambio, False)

otro = FILAS[0]._replace(celdas=FILAS[0].celdas[:4] + (CeldaChip("broken", "Peligro."),))
cambio = t.poner([otro, *FILAS[1:]])
despues = estado_elementos(t)
tocados = {i for i in set(antes) | set(despues) if antes.get(i) != despues.get(i)}
de_otras = [i for i in tocados if i in despues and i not in t.elementos("documentos")]
c("un chip que cambia solo toca elementos de su fila", de_otras, [])
c("  y los de las demás siguen siendo los mismos, en su sitio",
  all(antes[i] == despues[i] for iid in t.orden[1:] for i in t.elementos(iid)), True)
c("  un chip más estrecho que el más ancho de su columna no cambia el tamaño", cambio, False)
c("  y se lee el chip nuevo", t.leer()[0][4], "broken")

t.poner(FILAS)
antes = estado_elementos(t)
t.poner(list(reversed(FILAS)))
c("reordenar desplaza las filas: ni crea ni borra elementos",
  sorted(estado_elementos(t)), sorted(antes))
c("  y se lee en el orden nuevo", [x[1] for x in t.leer()], [f.iid for f in reversed(FILAS)])
t.poner(FILAS[:2])
c("una fila que se va se lleva sus elementos",
  (t.elementos("copias"), [x[1] for x in t.leer()]), ((), ["documentos", "larga"]))
cambio = t.poner(FILAS)
c("  y al volver se dibuja, y la tabla pide más alto", (len(t.leer()), cambio), (4, True))

t.elegir("documentos", avisar=False)
dlg.update()
antes = estado_elementos(t)
t.elegir("copias", avisar=False)
despues = estado_elementos(t)
filas_tocadas = sorted({iid for iid in t.orden for i in t.elementos(iid)
                        if antes.get(i) != despues.get(i)})
c("elegir otra fila repinta dos filas, la que deja y la que toma",
  filas_tocadas, ["copias", "documentos"])
caja = t.caja("copias")
fondo = [i for i in t.elementos("copias") if "fondo" in cv.gettags(i)][0]
c("  la elegida va en el azul suave", cv.itemcget(fondo, "fill"), theme.ACENTO_SUAVE)
nombre = de_la_columna(t, "copias", 1, "texto")[0]
c("  y una fila roja elegida deja el rojo de su letra",
  cv.itemcget(nombre, "fill"), theme.TINTA)
t.elegir("documentos", avisar=False)
c("  al dejarla vuelve el rojo", cv.itemcget(nombre, "fill"), theme.PELIGRO)
c("  sin avisar no se llama a al_elegir", elegidas, [])

# Lo mismo que una tabla nueva, tras series de poner() y elegir() al azar
rng = random.Random(11)
NOMBRES = [f"p{i}" for i in range(8)]
MODOS = (("bisync", "", "both"), ("up", "", "up"), ("down-mirror", "Peligro.", "down"))
ESTADOS = (("ok", "Ok.", None), ("pide resync", "Aviso.", None), ("no se usa aquí", "Apagado.", None),
           ("broken", "Peligro.", None), ("en uso", "Ok.", None))


def al_azar(nombre: str) -> FilaTabla:
    """Una fila cualquiera con ese nombre."""
    return fila(nombre, rng.choice((None, LARGA, "x ↔ y")), rng.choice(MODOS),
                rng.choice(ESTADOS), rng.choice(("", "aviso", "peligro", "apagado")),
                rng.random() < 0.6)


distintas, comparadas = [], 0
sitio = ttk.Frame(marco)
sitio.grid(row=2, column=0, sticky="ew")
sitio.columnconfigure(0, weight=1)
for serie in range(30):
    actuales: dict[str, FilaTabla] = {}
    for _ in range(5):
        siguientes = {}
        for n in rng.sample(NOMBRES, rng.randint(0, 7)):
            previa = actuales.get(n)
            siguientes[n] = previa if previa is not None and rng.random() < 0.6 else al_azar(n)
        actuales = siguientes
        t.poner(list(actuales.values()))
        if t.orden and rng.random() < 0.6:
            t.elegir(rng.choice(t.orden), avisar=False)
        nueva = TablaLienzo(sitio, COLUMNAS, al_elegir=lambda: None)
        nueva.marco.grid(row=0, column=0, sticky="ew")
        nueva.poner(list(actuales.values()))
        nueva.elegir(t.elegida, avisar=False)
        dlg.update()
        comparadas += 1
        if (dibujo(t), t.leer()) != (dibujo(nueva), nueva.leer()) or not apilado_bien(t):
            distintas.append((serie, list(actuales)))
        nueva.marco.destroy()
c(f"tras 30 series de poner() y elegir() ({comparadas} tablas) se dibuja lo de una tabla nueva",
  distintas[:2], [])
sitio.destroy()
t.poner(FILAS)
t.elegir(None, avisar=False)
dlg.update()

# ---------------------------------------------------------------------------
# 4. El teclado, el clic, el ratón encima y el foco
# ---------------------------------------------------------------------------
dejar = {"si": True, "preguntas": 0}


def puede_dejar() -> bool:
    """Lo que contesta la pantalla cuando hay algo sin guardar."""
    dejar["preguntas"] += 1
    return dejar["si"]


t.puede_dejar = puede_dejar
cv.focus_force()
dlg.update()


def tecla(nombre: str) -> None:
    """Pulsa una tecla con la tabla enfocada."""
    cv.event_generate(f"<{nombre}>")
    dlg.update()


anillo = cv.find_withtag("anillo")
c("con el foco y nada elegido, el anillo rodea la tabla",
  (len(anillo), {cv.itemcget(i, "fill") for i in anillo}), (4, {theme.ACENTO}))
recorrido = []
for nombre in ("Down", "Down", "End", "Up", "Home", "Next", "Prior"):
    tecla(nombre)
    recorrido.append(t.elegida)
c("↓ elige la primera y la siguiente, Fin la última, ↑ la de arriba, Inicio la primera",
  recorrido[:5], ["documentos", "larga", "videos", "copias", "documentos"])
c("  AvPág salta una página (o hasta la última) y RePág vuelve", recorrido[5:],
  ["videos", "documentos"])
c("  y cada cambio llama a al_elegir", elegidas,
  ["documentos", "larga", "videos", "copias", "documentos", "videos", "documentos"])
anillo = cv.find_withtag("anillo")
y0, y1 = t.caja("documentos")[1], t.caja("documentos")[3]
c("el anillo está dentro de la fila elegida",
  all(y0 <= cv.coords(i)[1] and cv.coords(i)[3] <= y1 for i in anillo), True)
dejar["si"] = False
elegidas.clear()
tecla("Down")
c("si puede_dejar dice que no, la flecha no cambia de fila ni avisa",
  (t.elegida, elegidas), ("documentos", []))
tecla("Return")
c("  Intro tampoco", elegidas, [])
dejar["si"] = True
tecla("Return")
c("Intro vuelve a llamar a al_elegir con la misma fila", elegidas, ["documentos"])
otro_foco = ttk.Button(marco, text="otro")
otro_foco.grid(row=3, column=0)
otro_foco.focus_force()
dlg.update()
c("sin el foco no hay anillo", cv.find_withtag("anillo"), ())

elegidas.clear()
caja = t.caja("copias")
cv.event_generate("<Button-1>", x=(caja[0] + caja[2]) // 2, y=(caja[1] + caja[3]) // 2)
dlg.update()
c("un clic a la altura de una fila la elige y avisa", (t.elegida, elegidas),
  ("copias", ["copias"]))
c("  y le da el foco a la tabla (con el anillo)",
  (str(dlg.focus_get()), len(cv.find_withtag("anillo"))), (str(cv), 4))
cv.event_generate("<Button-1>", x=caja[2] // 2, y=2)
dlg.update()
c("un clic en la cabecera no elige nada", (t.elegida, elegidas), ("copias", ["copias"]))

caja = t.caja("larga")
fondo = [i for i in t.elementos("larga") if "fondo" in cv.gettags(i)][0]
cv.event_generate("<Motion>", x=10, y=(caja[1] + caja[3]) // 2)
c("con el ratón encima, el fondo de la fila va un poco hacia la tinta",
  cv.itemcget(fondo, "fill"),
  theme.mezcla(theme.AVISO_FONDO, theme.TINTA, tk_tabla.MEZCLA_ENCIMA))
cv.event_generate("<Leave>")
c("  y al irse vuelve", cv.itemcget(fondo, "fill"), theme.AVISO_FONDO)
caja = t.caja("copias")
cv.event_generate("<Motion>", x=10, y=(caja[1] + caja[3]) // 2)
fondo = [i for i in t.elementos("copias") if "fondo" in cv.gettags(i)][0]
c("  la elegida se queda en su azul", cv.itemcget(fondo, "fill"), theme.ACENTO_SUAVE)
cv.event_generate("<Leave>")

sola = TablaLienzo(marco, COLUMNAS)
c("sin al_elegir la tabla no toma el foco con Tab", str(sola.marco.cget("takefocus")), "0")
sola.poner(FILAS)
sola.marco.grid(row=4, column=0)
dlg.update()
caja = sola.caja("copias")
sola.marco.event_generate("<Button-1>", x=10, y=(caja[1] + caja[3]) // 2)
c("  ni un clic elige", sola.elegida, None)
sola.marco.destroy()
vacia = TablaLienzo(marco, COLUMNAS, vacio="No hay ninguna pareja.")
vacia.poner([])
textos = [vacia.marco.itemcget(i, "text") for i in vacia.marco.find_withtag("tarjeta")
          if vacia.marco.type(i) == "text"]
c("una tabla sin filas dice lo que se le dio", (vacia.leer(), textos),
  ([], ["No hay ninguna pareja."]))
vacia.marco.destroy()
suelta = TablaLienzo(marco, (("", 0, False), ("Nombre", 0, False)))
suelta.poner([FilaTabla("a", (CeldaIcono("ok", "bien"), "texto suelto"))])
c("una celda de icono se lee por lo que dice, y un texto suelto tal cual", suelta.leer(),
  [("bien", "texto suelto")])
suelta.marco.destroy()
c("nada ha reventado", errores, [])
dlg.destroy()

# ---------------------------------------------------------------------------
# 5. La rueda es del Visor
# ---------------------------------------------------------------------------
PANTALLA = uitk.pantalla_util
uitk.pantalla_util = lambda _w: (1200, 420)
try:
    dlg = uitk.modal(raiz, "Rueda")
    cuerpo = uitk.cuerpo_visible(dlg)
    cuerpo.columnconfigure(0, weight=1)
    larga = TablaLienzo(cuerpo, COLUMNAS, al_elegir=lambda: None)
    larga.marco.grid(row=0, column=0, sticky="ew")
    larga.poner([fila(f"p{i:02}") for i in range(50)])
    suelto = tk.Canvas(cuerpo, width=200, height=60)      # un lienzo cualquiera, para comparar
    suelto.grid(row=1, column=0)
    enseñar(raiz, dlg)
    dlg.visor.encajar(dlg)
    dlg.update()
    visor = dlg.visor
    visor.lienzo.event_generate("<Enter>")
    c("con 50 filas la pantalla no cabe y el Visor se desplaza",
      visor.vertical.winfo_ismapped(), 1)

    def mueve(widget, patron: str, **k) -> int:
        """Cuánto desplaza la pantalla ese evento sobre ese widget, desde a media altura."""
        visor._mover(1, 200)
        dlg.update()
        widget.event_generate(patron, **k)
        dlg.update()
        return visor.desplazado()[1] - 200

    larga.marco.event_generate("<MouseWheel>", delta=-120)
    dlg.update()
    c("la rueda hacia abajo sobre la tabla desplaza la pantalla", visor.desplazado()[1] > 0,
      True)
    ruedas = (("<MouseWheel>", {"delta": -120}), ("<MouseWheel>", {"delta": 120}),
              ("<Button-4>", {}), ("<Button-5>", {}))
    c("cada evento de rueda sobre la tabla hace lo mismo que sobre el marco de debajo",
      [mueve(larga.marco, patron, **k) for patron, k in ruedas],
      [mueve(cuerpo, patron, **k) for patron, k in ruedas])
    c("  que sí se mueve con la rueda", mueve(cuerpo, "<MouseWheel>", delta=-120) > 0, True)
    c("un lienzo cualquiera se queda la rueda (por eso la tabla la pasa)",
      mueve(suelto, "<MouseWheel>", delta=-120), 0)
    dlg.destroy()
finally:
    uitk.pantalla_util = PANTALLA
c("nada ha reventado", errores, [])


# ---------------------------------------------------------------------------
# 6. Lo que asoma por las esquinas de un chip es el color de su fila
# ---------------------------------------------------------------------------
def captura(ventana_):
    """Los píxeles de la ventana con ImageMagick (`import`), o `None` y por qué no."""
    if not sys.platform.startswith("linux") or not shutil.which("import"):
        return None, "solo se captura en X11 con ImageMagick"
    if ventana_.winfo_screendepth() < 24:
        return None, "la pantalla no es de 24 bits"
    ventana_.update()
    x, y = ventana_.winfo_rootx(), ventana_.winfo_rooty()
    ancho, alto = ventana_.winfo_width(), ventana_.winfo_height()
    r = subprocess.run(["import", "-window", "root", "-crop", f"{ancho}x{alto}+{x}+{y}",
                        "+repage", "-depth", "8", "rgb:-"], capture_output=True, timeout=60)
    if r.returncode != 0 or len(r.stdout) != 3 * ancho * alto:
        return None, f"no se ha podido capturar: {r.stderr[:120]!r}"

    def en(px: int, py: int) -> str:
        """El píxel de la ventana en (px, py), «#RRGGBB»."""
        i = 3 * (py * ancho + px)
        return "#%02X%02X%02X" % tuple(r.stdout[i:i + 3])
    return en, ""


def _por_debajo(cv_, item) -> set:
    """Los elementos que están debajo de `item` en el orden de dibujo."""
    todos = list(cv_.find_all())
    return set(todos[:todos.index(item)])


def esquinas_de_chips(r, tema: str) -> None:
    """Las esquinas de los chips de una fila normal, elegida, ámbar y roja, en un tema."""
    theme.usar(tema)
    r2 = tk.Tk()
    anotar_errores(r2)
    r2.geometry("+0+0")
    theme.apply(r2)
    r2.configure(background=theme.PAPEL)
    marco2 = ttk.Frame(r2, padding=theme.E4)
    marco2.grid(sticky="nsew")
    marco2.columnconfigure(0, weight=1)
    t2 = TablaLienzo(marco2, COLUMNAS, al_elegir=lambda: None)
    t2.marco.grid(row=0, column=0, sticky="ew")
    t2.poner([fila("normal"), fila("elegida"), fila("ambar", tono="aviso",
                                                    estado=("pide resync", "Aviso.", None)),
              fila("roja", tono="peligro", modo=("up-mirror", "Peligro.", "up"),
                   estado=("espejo", "Peligro.", None))])
    t2.elegir("elegida", avisar=False)
    r2.update()
    cv2 = t2.marco
    previsto = {"normal": theme.SUPERFICIE, "elegida": theme.ACENTO_SUAVE,
                "ambar": theme.AVISO_FONDO, "roja": theme.PELIGRO_FONDO}
    debajo, transparentes = {}, []
    for iid in t2.orden:
        colores = set()
        for chip in [i for i in t2.elementos(iid) if "pildora" in cv2.gettags(i)]:
            img = cv2.itemcget(chip, "image")
            x0, y0 = (round(float(v)) for v in cv2.coords(chip))
            ancho = int(r2.tk.call("image", "width", img))
            alto = int(r2.tk.call("image", "height", img))
            for dx, dy in ((0, 0), (ancho - 1, 0), (0, alto - 1), (ancho - 1, alto - 1)):
                transparentes.append(bool(r2.tk.call(img, "transparency", "get", dx, dy)))
                debajo_del_chip = _por_debajo(cv2, chip)
                bajo = [i for i in cv2.find_overlapping(x0 + dx, y0 + dy, x0 + dx, y0 + dy)
                        if i in debajo_del_chip]
                rellenos = [i for i in bajo if cv2.type(i) == "rectangle"]
                colores.add(cv2.itemcget(rellenos[-1], "fill") if rellenos else None)
        debajo[iid] = colores
    p = f"{tema}: "
    c(p + "las esquinas de cada píldora son transparentes", set(transparentes), {True})
    c(p + "  y lo que tienen debajo es el fondo de su fila: normal, elegida, ámbar y roja",
      debajo, {iid: {color} for iid, color in previsto.items()})
    en, motivo = captura(r2)
    if en is None:
        print(f"  (saltado) los píxeles de las esquinas: {motivo}")
    else:
        vistos = {}
        for iid in t2.orden:
            pixeles = set()
            for chip in [i for i in t2.elementos(iid) if "pildora" in cv2.gettags(i)]:
                img = cv2.itemcget(chip, "image")
                x0, y0 = (round(float(v)) for v in cv2.coords(chip))
                ancho = int(r2.tk.call("image", "width", img))
                alto = int(r2.tk.call("image", "height", img))
                ox, oy = cv2.winfo_rootx() - r2.winfo_rootx(), cv2.winfo_rooty() - r2.winfo_rooty()
                for dx, dy in ((0, 0), (ancho - 1, 0), (0, alto - 1), (ancho - 1, alto - 1)):
                    pixeles.add(en(ox + x0 + dx, oy + y0 + dy))
            vistos[iid] = pixeles
        c(p + "  en pantalla, el píxel de cada esquina de cada chip es el de su fila",
          vistos, {iid: {color} for iid, color in previsto.items()})
    theme.olvidar(r2.tk)
    icons.olvidar(r2.tk)
    r2.destroy()


for tema in ("claro", "oscuro"):
    esquinas_de_chips(raiz, tema)
theme.usar("claro")

# ---------------------------------------------------------------------------
# 7. Las medidas de ttk, a varias escalas; los dos pintores
# ---------------------------------------------------------------------------
CHIPS = (CeldaChip("ok", "Ok."), CeldaChip("bisync", "", "both"), CeldaChip("up", "", "up"),
         CeldaChip("no se usa aquí", "Apagado."), CeldaChip("up-mirror", "Peligro.", "up"),
         CeldaChip("x"), CeldaChip("pide resync", "Aviso.", "warn"))
for escala in (1.3333, 1.6667, 2.0, 2.6667):
    r3 = tk.Tk()
    anotar_errores(r3)
    r3.withdraw()
    r3.tk.call("tk", "scaling", escala)
    theme.apply(r3)
    t3 = TablaLienzo(r3, COLUMNAS, al_elegir=lambda: None)
    medidas = {}
    for celda in CHIPS:
        chip = theme.chip(r3, *celda)
        hecho = t3._chip(celda)
        medidas[celda.texto] = ((hecho.ancho, hecho.alto),
                                (chip.winfo_reqwidth(), chip.winfo_reqheight()))
        chip.destroy()
    p = f"al {round(escala / 1.3333 * 100)} %: "
    c(p + "cada chip mide lo que el de ttk", {k: v[0] for k, v in medidas.items()},
      {k: v[1] for k, v in medidas.items()})
    piezas = {str(img) for img in theme._imagenes.get(id(r3.tk), [])}
    c(p + "  y su píldora sale de la pieza del estilo del tema",
      {celda.tipo: str(tk_tabla._pieza_chip(r3, celda.tipo)[0]) in piezas for celda in CHIPS},
      {celda.tipo: True for celda in CHIPS})
    etiqueta = ttk.Label(r3, text="documentos", style="Card.Fuerte.TLabel")
    casilla = ttk.Label(r3, image=icons.casilla(r3, "marcada", margen=0), style="Card.TLabel")
    c(p + "una etiqueta de ttk pide HOLGURA a cada lado de su texto y de su imagen",
      (etiqueta.winfo_reqwidth() - t3._medir("fuerte", "documentos"),
       etiqueta.winfo_reqheight() - t3._linea("fuerte"),
       casilla.winfo_reqwidth() - icons.casilla(r3, "marcada", margen=0).width()),
      (2 * tk_tabla.HOLGURA,) * 3)
    t3.poner(FILAS)
    caja = t3.caja("documentos")
    c(p + "la fila mide lo que la más alta de sus celdas más el hueco de la rejilla",
      caja[3] - caja[1],
      max(icons.px(r3, tk_tabla.ALTO_FILA),
          max(t3._chip(cel).alto for f in FILAS for cel in f.celdas if isinstance(cel, CeldaChip))
          + 2 * r3.winfo_pixels(theme.E2)))
    theme.olvidar(r3.tk)
    icons.olvidar(r3.tk)
    r3.destroy()

# Con el pintor de Python (el de Tk 8.6) la tabla se dibuja igual de bien
if icons.svg_disponible(raiz):
    icons.USAR_SVG = False
    try:
        r4 = tk.Tk()
        anotar_errores(r4)
        r4.withdraw()
        theme.apply(r4)
        t4 = TablaLienzo(r4, COLUMNAS, al_elegir=lambda: None)
        t4.poner(FILAS)
        formatos = {str(r4.tk.call(cv_img, "cget", "-format")) for cv_img in
                    {t4.marco.itemcget(i, "image") for i in t4.marco.find_all()
                     if t4.marco.type(i) == "image" and "adorno" in t4.marco.gettags(i)}}
        c("sin SVG, los discos los pinta el pintor de Python y la tabla se dibuja",
          (len(t4.leer()), "svg" in formatos), (4, False))
        theme.olvidar(r4.tk)
        icons.olvidar(r4.tk)
        r4.destroy()
    finally:
        icons.USAR_SVG = True
else:
    print("  (saltado) este Tk no lee SVG: todo lo de arriba ya va con el pintor de Python")

c("nada ha reventado", errores, [])
sys.exit(c.report())
