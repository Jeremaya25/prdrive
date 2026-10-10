#!/usr/bin/env python3
"""El asistente cambia de paso sin pasearse por la pantalla.

Un cambio de paso ajusta el hueco una sola vez: `reencajar()` se llama una vez
por cambio, no las tres veces que hacía el dibujo (el paso se pintaba y cada
`revisar()` que hacía volvía a encajar). La ventana crece en su sitio, sin
volver a centrarse, y solo se mueve lo justo para que su borde de abajo no se
salga de la pantalla útil, que es cuando crece por abajo cerca del borde.

Con Tk de verdad, en una pantalla de 1920x1080 con la pantalla útil fijada a
1920x1040 (como en los demás tests de medidas), se comprueba:

- que «¿Dónde?» → «Dispositivo» cambia a lo sumo de tamaño una vez y no
  mueve la ventana, cuando cabe;
- que cada cambio de paso y cada panel que aparece sin cambiar de paso llama a
  `reencajar()` una vez;
- que una ventana pegada al borde de abajo que crece sube lo justo, hasta que
  su borde de abajo coincide con el de la pantalla útil;
- que un panel que aparece sin cambiar de paso («ya es un prdrive») sigue
  encajándose sin recortar nada;
- y los casos de `_sitio_en_pantalla()`: qué se mueve y qué no, con varios
  monitores.

Las ventanas se crean ocultas; el bucle de eventos se mueve a mano
(`bombear()`), que es lo que entrega los `<Configure>` y las llamadas
pendientes.
"""

import sys
import time
from pathlib import Path

from _harness import Checks, tmpdir

c = Checks("asistente: el cambio de paso se ajusta una vez y no pasea la ventana")

try:
    import tkinter as tk
    from tkinter import ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from install import device, profile  # noqa: E402
from ui import segundo_plano, tk_install  # noqa: E402
from ui import tk as uitk  # noqa: E402

# Los encargos corren en el sitio: la lista de unidades llega mientras se
# pinta el paso, como en los demás tests del asistente.
segundo_plano.lanzar = segundo_plano.en_el_acto

# La pantalla útil de la prueba: 1920x1040 (el monitor 1080p menos la barra).
PANTALLA_REAL = uitk.pantalla_util
UTIL = (1920, 1040)
uitk.pantalla_util = lambda win: UTIL

PERFIL = profile.from_form("nas", {"type": "sftp", "host": "nas.example", "user": "u"})
UNIDAD = tmpdir("prdrive-reencaje-")
VOLUMEN = device.Volume(root=UNIDAD, label="PEN", filesystem="exFAT",
                        drive_type="Removable", size=8 * 2 ** 30, free=7 * 2 ** 30)
VOLUMENES: list = []                   # lo que «Dispositivo» lista (cambia por prueba)
device.list_volumes = lambda: list(VOLUMENES)

# Una unidad con prdrive: el panel «ya es un dispositivo prdrive» aparece al
# elegirla, sin cambiar de paso.
tk_install._ya_es_prdrive = lambda raiz_: raiz_ is not None


def bombear(segundos: float = 0.3) -> None:
    """Mueve el bucle de Tk un rato, para que lleguen los `<Configure>` y las ideas pendientes."""
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        raiz.update()
        time.sleep(0.01)


def widgets(w, tipo=object) -> list:
    """Devuelve los widgets de ese tipo que cuelgan de `w`, sin contar `w`."""
    pila, salida = list(w.winfo_children()), []
    while pila:
        actual = pila.pop()
        pila += list(actual.winfo_children())
        if isinstance(actual, tipo):
            salida.append(actual)
    return salida


def estado(ventana) -> tuple[int, int, int, int]:
    """Devuelve `(ancho, alto, x, y)` de la ventana, tal como la ve Tk ahora."""
    return (ventana.winfo_width(), ventana.winfo_height(),
            ventana.winfo_x(), ventana.winfo_y())


class Configures:
    """Anota cada `<Configure>` de la ventana: su tamaño y su posición.

    Attributes:
        ventana: La ventana vigilada.
        eventos: Una tupla `(ancho, alto, x, y)` por evento, en orden.
    """

    def __init__(self, ventana) -> None:
        """Empieza a anotar; los eventos de los hijos no cuentan."""
        self.ventana = ventana
        self.eventos: list[tuple[int, int, int, int]] = []
        ventana.bind("<Configure>", self._al, add="+")

    def _al(self, evento) -> None:
        """Anota el evento si es de la ventana misma."""
        if evento.widget is not self.ventana:
            return
        self.eventos.append(estado(self.ventana))

    def cambios(self, antes: tuple[int, int, int, int]) -> tuple[int, int]:
        """Cuenta los cambios de tamaño y de posición desde `antes`.

        Args:
            antes: `(ancho, alto, x, y)` de la ventana antes de lo que se mide.

        Returns:
            `(cambios de tamaño, cambios de posición)`.
        """
        tamano, sitio = antes[:2], antes[2:]
        n_tamano = n_sitio = 0
        for ancho, alto, x, y in self.eventos:
            if (ancho, alto) != tamano:
                n_tamano += 1
                tamano = (ancho, alto)
            if (x, y) != sitio:
                n_sitio += 1
                sitio = (x, y)
        return n_tamano, n_sitio


def asistente(volumenes=()):
    """Devuelve `(ventana, asistente)` ya enseñados y centrados, en «¿Dónde?».

    Args:
        volumenes: Las unidades que lista «Dispositivo».
    """
    VOLUMENES[:] = list(volumenes)
    ventana = tk.Toplevel(raiz)
    ventana.withdraw()
    wiz = tk_install.build(ventana)
    wiz.perfil = PERFIL
    uitk.centrar(ventana)
    ventana.deiconify()
    bombear()
    return ventana, wiz


def arbol(wiz):
    """Devuelve la lista de unidades del paso «Dispositivo», o `None`."""
    return next(iter(widgets(wiz.cuerpo, ttk.Treeview)), None)


def centrado(alto: int) -> int:
    """Devuelve la `y` a la que `centrar()` pondría una ventana de ese alto."""
    return max(0, (raiz.winfo_screenheight() - alto) // 2 - alto // 8)


# ---------------------------------------------------------------------------
# (a) «¿Dónde?» → «Dispositivo»: a lo sumo un cambio de tamaño, ningún movimiento.
# ---------------------------------------------------------------------------
ventana, wiz = asistente()
antes = estado(ventana)
c("(a) parte de «¿Dónde?»", wiz.pasos[wiz.indice][0], "¿Dónde?")
registro = Configures(ventana)
wiz.ir(+1)
bombear()
tamano, sitio = registro.cambios(antes)
creci = estado(ventana)[:2] != antes[:2]
c("(a) «Dispositivo» llega (precondición)", wiz.pasos[wiz.indice][0], "Dispositivo")
c("(a) la ventana crece (precondición)", creci, True)
c("(a) un solo cambio de tamaño, como mucho", tamano <= 1, True)
c("(a) y ningún cambio de posición: cabe, así que no se mueve", sitio, 0)
ventana.destroy()

# ---------------------------------------------------------------------------
# (b) reencajar() se llama una vez por cambio de paso, y una vez por panel
#     que aparece sin cambiar de paso.
# ---------------------------------------------------------------------------
ventana, wiz = asistente([VOLUMEN])
llamadas = {"n": 0}
reencajar_real = wiz.reencajar


def contar() -> None:
    """Cuenta la llamada y hace la real."""
    llamadas["n"] += 1
    reencajar_real()


wiz.reencajar = contar
llamadas["n"] = 0
wiz.ir(+1)
bombear()
c("(b) un cambio de paso llama a reencajar() una vez", llamadas["n"], 1)

# Elegir la unidad (un prdrive) hace aparecer el panel sin cambiar de paso.
llamadas["n"] = 0
arbol(wiz).selection_set(arbol(wiz).get_children()[0])
raiz.update()
bombear()
c("(b) el panel de «ya es un prdrive» llama a reencajar() una vez", llamadas["n"], 1)

# Un paso que falla al pintarse no deja la marca puesta: si no, nada volvería a encajar.
wiz.pasos = [("Roto", lambda cuerpo, w: 1 / 0, lambda w: True)]
wiz.indice = 0
try:
    wiz.repintar()
except ZeroDivisionError:
    pass
c("(b) un paso que falla al pintarse no deja el ajuste en pausa",
  getattr(wiz, "_pintando", None), False)
ventana.destroy()

# ---------------------------------------------------------------------------
# (c) Una ventana pegada al borde de abajo que crece sube lo justo, no se centra.
# ---------------------------------------------------------------------------
ventana, wiz = asistente([VOLUMEN])
wiz.ir(+1)
bombear()
ancho, alto, x0, _ = estado(ventana)
# Justo cabe ahora, con 6 px de margen por abajo: crecer lo saca de la pantalla útil.
y0 = UTIL[1] - alto - 6
ventana.geometry(f"+{x0}+{y0}")
bombear()
antes = estado(ventana)
registro = Configures(ventana)
arbol(wiz).selection_set(arbol(wiz).get_children()[0])
raiz.update()
bombear()
ancho_d, alto_d, x_d, y_d = estado(ventana)
c("(c) precondición: la ventana crece por abajo", alto_d > alto, True)
c("(c) precondición: sin moverla, se saldría", y0 + alto_d > UTIL[1], True)
c("(c) su borde de abajo queda en el de la pantalla útil", y_d + alto_d, UTIL[1])
c("(c) no se centra: la y no es la de centrar()", y_d == centrado(alto_d), False)
c("(c) la x no cambia", x_d, x0)
ventana.destroy()

# ---------------------------------------------------------------------------
# (d) Un panel que aparece sin cambiar de paso sigue encajándose entero.
# ---------------------------------------------------------------------------
ventana, wiz = asistente([VOLUMEN])
wiz.ir(+1)
bombear()
antes_alto = estado(ventana)[1]
arbol(wiz).selection_set(arbol(wiz).get_children()[0])
raiz.update()
bombear()
visor = wiz.visor
visor.interior.update_idletasks()
pide = visor.interior.winfo_reqheight()
c("(d) el panel de «ya es un prdrive» se pinta",
  any("ya es un dispositivo prdrive" in str(w.cget("text"))
      for w in widgets(wiz.cuerpo, ttk.Label)), True)
c("(d) la ventana ha crecido para él", estado(ventana)[1] > antes_alto, True)
c("(d) el contenido cabe en el hueco: no lo recorta", pide <= visor._medida()[1], True)
c("(d) y no aparece barra de desplazamiento", visor.barras()[0], False)
ventana.destroy()

# ---------------------------------------------------------------------------
# (e) _sitio_en_pantalla(): se mueve lo justo y solo en la pantalla principal.
# ---------------------------------------------------------------------------
PANTALLA = (1920, 1080)


def sitio(*args):
    """Llama a `tk_install._sitio_en_pantalla()`, o devuelve `None` si aún no existe."""
    funcion = getattr(tk_install, "_sitio_en_pantalla", None)
    return funcion(*args) if funcion is not None else None


c("(e) lo que cabe no se mueve", sitio(100, 100, 800, 600, UTIL, PANTALLA), (100, 100))
c("(e) un borde de abajo que se sale sube lo justo",
  sitio(100, 500, 800, 600, UTIL, PANTALLA), (100, 440))
c("(e) un borde de la derecha que se sale va a la izquierda lo justo",
  sitio(1500, 100, 800, 600, UTIL, PANTALLA), (1120, 100))
c("(e) una ventana más alta que la pantalla útil va arriba del todo",
  sitio(100, 300, 800, 1200, UTIL, PANTALLA), (100, 0))
c("(e) una ventana en otro monitor a la derecha no se trae a la principal",
  sitio(2000, 500, 800, 600, UTIL, PANTALLA), (2000, 440))
c("(e) ni una en otro monitor más abajo",
  sitio(100, 1200, 800, 600, UTIL, PANTALLA), (100, 1200))
c("(e) ni una con coordenadas negativas (un monitor a la izquierda)",
  sitio(-1500, 500, 800, 600, UTIL, PANTALLA), (-1500, 440))

raiz.destroy()
sys.exit(c.report())
