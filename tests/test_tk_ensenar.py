#!/usr/bin/env python3
"""Las ventanas aparecen ya pintadas, y no se pintan antes de verse.

Dos cosas que hacían lenta la interfaz, comprobadas sin enseñar nada:

- `tk.ensenar()` enseña una ventana encubierta por DWM (`DWMWA_CLOAK`), deja
  que se pinte entera y solo entonces la descubre; si no puede encubrirla, la
  enseña sin más. Se conduce con una ventana y un DWM de mentira, y la llamada
  real a dwmapi contra un `ctypes.WinDLL` de mentira.
- el `Visor` no mapea su contenido mientras la ventana está retirada (con un
  `Canvas` se colocaba y se pintaba todo a escondidas y otra vez al
  enseñarse), pero lo tiene ya de su tamaño, y se desplaza.

Lo que solo se ve en Windows de verdad (que la ventana no se vea rellenarse)
está en `docs/superpowers/pruebas/2026-10-08-pintado-pendiente-en-real.md`.
"""

import ctypes
import sys

from _harness import Checks

from ui import theme
from ui import tk as uitk

c = Checks("las ventanas aparecen ya pintadas")

HIJA = 0x1000
ENVOLTORIO = 0x2000


class VentanaFalsa:
    """Un `Toplevel` de Tk en Windows, de mentira: apunta lo que se le pide.

    Attributes:
        llamadas: Lo que se le ha pedido, en orden.
        envoltorio: Si `wm frame` da ya el envoltorio (y no la ventana propia).
        update_lanza: Si `update()` lanza, como una ventana cerrada a medias.
    """

    def __init__(self, envoltorio: bool = True, update_lanza: bool = False):
        """Prepara la ventana."""
        self.llamadas: list = []
        self.envoltorio = envoltorio
        self.update_lanza = update_lanza

    def update_idletasks(self):
        """Corre el reposo."""
        self.llamadas.append("update_idletasks")

    def wm_frame(self):
        """Devuelve el manejador como lo escribe Tk: «0x…»."""
        return hex(ENVOLTORIO if self.envoltorio else HIJA)

    def winfo_id(self):
        """Devuelve la ventana propia de Tk."""
        return HIJA

    def deiconify(self):
        """Enseña la ventana."""
        self.llamadas.append("deiconify")

    def update(self):
        """Procesa lo pendiente: aquí se pinta todo."""
        self.llamadas.append("update")
        if self.update_lanza:
            raise RuntimeError("cerrada mientras se pintaba")


def ensenar(ventana, acepta: bool = True, es_win: bool = True, lanza: bool = False,
            tema: str = "claro", barra_lanza: bool = False):
    """Llama a `ensenar()` con un DWM de mentira y devuelve lo que se le pidió encubrir.

    Lo que se pide para la barra de título va solo a `ventana.llamadas`, como
    `("barra", hwnd, atributo, valor)`.
    """
    pedidas: list = []

    def encubrir(hwnd, encubierta):
        """Apunta la petición, en la misma lista que la ventana, y contesta."""
        ventana.llamadas.append(("encubrir", hwnd, encubierta))
        pedidas.append((hwnd, encubierta))
        if lanza:
            raise OSError("dwmapi no responde")
        return acepta

    def atributo(hwnd, cual, valor):
        """Apunta un atributo de la barra y contesta."""
        ventana.llamadas.append(("barra", hwnd, cual, valor))
        if barra_lanza:
            raise OSError("dwmapi no responde")
        return True

    previo = (uitk.IS_WIN, uitk._encubrir, uitk._atributo_dwm,
              theme.TEMA, theme._tema_elegido)
    uitk.IS_WIN, uitk._encubrir, uitk._atributo_dwm = es_win, encubrir, atributo
    theme.usar(tema)
    try:
        uitk.ensenar(ventana)
    finally:
        uitk.IS_WIN, uitk._encubrir, uitk._atributo_dwm = previo[:3]
        theme.usar(previo[3])
        theme._tema_elegido = previo[4]
    return pedidas


# 1. encubierta, enseñada, pintada y descubierta, en ese orden
v = VentanaFalsa()
ensenar(v)
c("se encubre el envoltorio, se enseña, se pinta y se descubre",
  [x for x in v.llamadas if x != "update_idletasks"],
  [("encubrir", ENVOLTORIO, True), "deiconify", "update",
   ("encubrir", ENVOLTORIO, False)])

# 2. sin envoltorio todavía no se encubre nada: se enseña sin más
v = VentanaFalsa(envoltorio=False)
c("sin envoltorio no se pide nada a DWM", ensenar(v), [])
c("  y se enseña igual", "deiconify" in v.llamadas, True)
c("  sin el update de más", "update" in v.llamadas, False)

# 3. DWM no lo acepta (Windows 7) o falla: se enseña sin más y no se descubre
for nombre, opciones in (("no lo acepta", {"acepta": False}),
                         ("lanza", {"lanza": True})):
    v = VentanaFalsa()
    pedidas = ensenar(v, **opciones)
    c(f"si DWM {nombre}, solo se pidió encubrir", pedidas, [(ENVOLTORIO, True)])
    c("  y la ventana se enseña igual", v.llamadas[-1], "deiconify")

# 4. si algo falla mientras se pinta, la ventana se descubre igual
v = VentanaFalsa(update_lanza=True)
pedidas = ensenar(v)
c("aunque falle el pintado, se descubre: nunca se queda invisible",
  pedidas[-1], (ENVOLTORIO, False))

# 5. fuera de Windows es un deiconify y nada más
v = VentanaFalsa()
c("fuera de Windows no se pide nada a DWM", ensenar(v, es_win=False), [])
c("  y es un deiconify", v.llamadas, ["deiconify"])

# 6. con el tema oscuro, la barra de título oscura, puesta en el envoltorio
#    que se va a enseñar y antes de enseñarlo
c("el tema claro no toca la barra", theme.barra_titulo(), ())
theme.usar("oscuro")
PAPEL_OSCURO = int(theme.PAPEL[5:7] + theme.PAPEL[3:5] + theme.PAPEL[1:3], 16)
c("el oscuro la pide oscura (atributo 20) y del color del papel (35, COLORREF "
  "0x00BBGGRR)", theme.barra_titulo(), ((20, 1), (35, PAPEL_OSCURO)))
theme.usar("claro")
theme._tema_elegido = False

v = VentanaFalsa()
ensenar(v, tema="oscuro")
c("con el tema oscuro, la barra se pide en el envoltorio antes de enseñarlo",
  [x for x in v.llamadas if x != "update_idletasks"][:3],
  [("barra", ENVOLTORIO, 20, 1), ("barra", ENVOLTORIO, 35, PAPEL_OSCURO),
   ("encubrir", ENVOLTORIO, True)])
v = VentanaFalsa()
ensenar(v, tema="claro")
c("  con el claro no se pide nada para la barra",
  [x for x in v.llamadas if x[0] == "barra"], [])
v = VentanaFalsa(envoltorio=False)
ensenar(v, tema="oscuro")
c("  sin envoltorio tampoco: se perdería al crearlo",
  [x for x in v.llamadas if x[0] == "barra"], [])
v = VentanaFalsa()
ensenar(v, tema="oscuro", es_win=False)
c("  ni fuera de Windows", v.llamadas, ["deiconify"])
v = VentanaFalsa()
pedidas = ensenar(v, tema="oscuro", barra_lanza=True)
c("si DWM falla con la barra, la ventana se encubre, se enseña y se descubre igual",
  pedidas, [(ENVOLTORIO, True), (ENVOLTORIO, False)])


# 7. la llamada de verdad a dwmapi, contra un ctypes.WinDLL de mentira
class FuncionFalsa:
    """`DwmSetWindowAttribute` de mentira: apunta lo recibido y devuelve un HRESULT."""

    def __init__(self, devuelve):
        """Prepara el HRESULT que devolverá."""
        self.devuelve = devuelve
        self.recibido: list = []
        self.argtypes = None
        self.restype = None

    def __call__(self, hwnd, atributo, valor, tamano):
        """Apunta el valor apuntado por `valor` y contesta."""
        self.recibido.append((hwnd, atributo, valor._obj.value, tamano))
        return self.devuelve


class DllFalsa:
    """Lo que devuelve `ctypes.WinDLL("dwmapi")`."""

    abiertas: list = []
    funcion: FuncionFalsa = FuncionFalsa(0)

    def __init__(self, nombre, **opciones):
        """Apunta qué biblioteca se abrió y con qué opciones."""
        DllFalsa.abiertas.append((nombre, opciones))

    @property
    def DwmSetWindowAttribute(self):                            # noqa: N802
        """La función de dwmapi, con sus tipos por declarar."""
        return DllFalsa.funcion


windll_real = getattr(ctypes, "WinDLL", None)
ctypes.WinDLL = DllFalsa
try:
    from ctypes import wintypes

    for devuelve, esperado in ((0, True), (-2147024809, False)):    # S_OK, E_INVALIDARG
        DllFalsa.abiertas, DllFalsa.funcion = [], FuncionFalsa(devuelve)
        c(f"dwmapi contesta {devuelve}: la llamada real dice {esperado}",
          uitk._encubrir(0xABCDEF, True), esperado)
    c("abre dwmapi", [n for n, _ in DllFalsa.abiertas], ["dwmapi"])
    c("  pide DWMWA_CLOAK (13) con TRUE, 4 bytes",
      DllFalsa.funcion.recibido, [(0xABCDEF, 13, 1, 4)])
    uitk._encubrir(0xABCDEF, False)
    c("  y FALSE para descubrir", DllFalsa.funcion.recibido[-1], (0xABCDEF, 13, 0, 4))
    c("declara HWND, DWORD, BOOL* (int*), DWORD -> HRESULT: sin eso un manejador "
      "de 64 bits se trunca", (DllFalsa.funcion.argtypes, DllFalsa.funcion.restype),
      ([wintypes.HWND, wintypes.DWORD, ctypes.POINTER(ctypes.c_int), wintypes.DWORD],
       ctypes.c_long))
finally:
    if windll_real is None:
        del ctypes.WinDLL
    else:
        ctypes.WinDLL = windll_real


try:
    import tkinter as tk
    from tkinter import ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

theme.apply(raiz)

# 8. con un Tk de verdad: `transient()` y `resizable()` rehacen el envoltorio
#    (`UpdateWrapper`, otro manejador), así que la barra puesta al crear el
#    diálogo se perdía. Tiene que acabar en el envoltorio que se enseña.
if uitk.IS_WIN:
    pedidos: list = []
    previo = (uitk._atributo_dwm, theme.TEMA, theme._tema_elegido)
    uitk._atributo_dwm = lambda hwnd, cual, valor: pedidos.append(hwnd) or True
    theme.usar("oscuro")
    try:
        # Como una raíz de verdad: `resizable()` y después enseñarla. Visible,
        # además, porque el `transient` de una oculta no llega a mapearse.
        padre = tk.Toplevel(raiz)
        padre.withdraw()
        padre.resizable(False, False)
        ttk.Label(padre, text="padre").grid()
        uitk.ensenar(padre)
        c("Tk de verdad: la barra se pide en el envoltorio con el que se enseña "
          "la ventana", sorted(set(pedidos)), [int(padre.wm_frame(), 16)])
        pedidos.clear()
        dlg = uitk.modal(padre, "barra")
        ttk.Label(dlg, text="barra").grid()
        uitk.ensenar(dlg)
        c("  y la de un diálogo (`transient` y `resizable` rehacen el envoltorio)",
          sorted(set(pedidos)), [int(dlg.wm_frame(), 16)])
        dlg.destroy()
        padre.destroy()
    finally:
        uitk._atributo_dwm = previo[0]
        theme.usar(previo[1])
        theme._tema_elegido = previo[2]
else:
    print("  (saltado) el envoltorio de Tk solo existe en Windows")

# 9. el Visor: de su tamaño, pero sin mapear, mientras la ventana está retirada
top = tk.Toplevel(raiz)
top.withdraw()
visor = uitk.Visor(top, ancho=300, alto=200)
visor.marco.grid(row=0, column=0, sticky="nsew")
visor.interior.columnconfigure(0, weight=1)
filas = [ttk.Button(visor.interior, text=f"Fila {i}") for i in range(30)]
for i, b in enumerate(filas):
    b.grid(row=i, column=0, sticky="ew")
top.update_idletasks()
pide = visor.interior.winfo_reqheight()
c("con la ventana retirada, el contenido no se mapea (ni se pinta)",
  [visor.interior.winfo_ismapped(), filas[0].winfo_ismapped()], [False, False])
c("  pero ya tiene su tamaño: lo que miden los tests y Visor.ver()",
  (visor.interior.winfo_height(), visor.interior.winfo_width() >= 300), (pide, True))
c("  y su sitio: la última fila, abajo del todo",
  filas[-1].winfo_y() + filas[-1].winfo_reqheight() <= pide
  and filas[-1].winfo_y() > pide // 2, True)
c("como no cabe, la barra vertical está puesta", bool(visor.vertical.grid_info()), True)

# desplazar es mover el contenido dentro de la mirilla
visor._desplazar(1, "moveto", "0.5")
c("moveto 0.5 baja hasta la mitad", visor.desplazado()[1], round(pide / 2))
c("  y mueve el contenido", int(visor.interior.place_info()["y"]), -visor.desplazado()[1])
c("  y lo dice a la barra", round(float(visor.vertical.get()[0]), 2), 0.5)
visor._desplazar(1, "moveto", "1.0")
c("no se pasa del final", visor.desplazado()[1], pide - 200)
visor._desplazar(1, "scroll", "-1", "units")
c("una unidad es una décima de lo que se ve", visor.desplazado()[1], pide - 200 - 20)
visor._desplazar(1, "scroll", "-100", "pages")
c("ni del principio", visor.desplazado()[1], 0)
visor.ver(filas[-1])
c("ver() baja hasta enseñar entera la última fila",
  visor.desplazado()[1], pide - 200)

top.destroy()
raiz.destroy()
sys.exit(c.report())
