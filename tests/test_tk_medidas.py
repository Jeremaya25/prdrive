#!/usr/bin/env python3
"""
Que las pantallas quepan en la pantalla.

Lo que se comprueba no es el aspecto sino una sola cosa medible: **ninguna
ventana pide más de lo que hay**, y **nada queda recortado sin barra que lo
avise**. Es el fallo que tuvo el asistente: el hueco de los pasos era un marco de
820x430 px con `grid_propagate(False)`, el paso 1 pedía 486 px de alto en una
pantalla normal y el último campo simplemente no se dibujaba, sin ningún aviso.

Cada pantalla de la lista son **dos** cosas y las dos importan: los píxeles que
dice tener y el `tk scaling` con el que se dibuja. `tk scaling` son píxeles por
punto —1,3333 es 96 ppp, o sea el zoom del sistema al 100 %; 2,0 es el 150 % y
2,6667 el 200 %—, y es lo que de verdad rompe las medidas, porque las fuentes van
en puntos y crecen con él mientras que un recuadro en píxeles no. Una 4K sola no
prueba gran cosa (sobra sitio por todos lados); una 4K al 200 %, o peor, una
1080p al 200 %, es donde el contenido deja de caber.

Las medidas dependen de las fuentes del equipo, así que aquí no se fijan cifras:
se compara lo que pide cada ventana con lo que dice `tk.pantalla_util`, que es
justo lo que mira el código. Para probar una pantalla que no se tiene se
sustituye esa función, que por eso es de módulo, y se le cambia la escala al
intérprete de Tk: es reversible y la cogen los widgets que se creen después.

Las ventanas se crean ocultas y no se entra nunca en el bucle de eventos.
"""

import sys

from _harness import Checks, sandbox

import tomllib

from common import catalog, config_file, model

c = Checks("medidas de las pantallas")

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(0)

from ui import tk as uitk
from ui import tk_install, tk_pairs

messagebox.showinfo = lambda *a, **k: None
messagebox.showerror = lambda *a, **k: None

BASE = {"defaults": {"remote": "nas"},
        "pair": [{"name": f"pareja{i}", "local": f"sync-data/p{i}",
                  "remote_path": f"/R/p{i}", "mode": "bisync"} for i in range(12)]}

catalog.load = lambda raw=None: (catalog.Catalog(
    raw=tomllib.loads(config_file.dumps(BASE)), text=config_file.dumps(BASE),
    source="remote", stamp="2026-01-01 00:00:00",
    endpoint="nas:/prdrive-catalog/pairs.toml"), None)
catalog.push = lambda *a, **k: []
catalog.run = lambda args: (_ for _ in ()).throw(
    AssertionError("ningún test puede hablar con el remoto"))

# nombre, ancho, alto, tk scaling
PANTALLAS = (
    ("1080p", 1920, 1080, 1.3333),
    ("1080p al 150 %", 1920, 1080, 2.0),
    ("1080p al 200 %", 1920, 1080, 2.6667),
    ("2K", 2560, 1440, 1.3333),
    ("2K al 150 %", 2560, 1440, 2.0),
    ("4K al 150 %", 3840, 2160, 2.0),
    ("4K al 200 %", 3840, 2160, 2.6667),
    ("portátil 1366x768", 1366, 768, 1.3333),
    ("1280x720", 1280, 720, 1.3333),
    ("1024x600", 1024, 600, 1.3333),
)

PANTALLA_REAL = uitk.pantalla_util
ESCALA_REAL = float(raiz.tk.call("tk", "scaling"))


def pantalla(ancho, alto, escala):
    """Hace creer al código que la pantalla es esa, y con ese zoom."""
    uitk.pantalla_util = lambda win: (ancho, alto)
    raiz.tk.call("tk", "scaling", escala)


def cabe(ventana) -> bool:
    ventana.update_idletasks()
    util_x, util_y = uitk.pantalla_util(ventana)
    return (ventana.winfo_reqwidth() <= util_x
            and ventana.winfo_reqheight() <= util_y)


def recortado(visor) -> bool:
    """Contenido fuera del recuadro sin barra que lo enseñe: lo que no puede pasar."""
    visor.interior.update_idletasks()
    ancho, alto = visor._medida()
    return ((visor.interior.winfo_reqheight() > alto
             and not visor.vertical.grid_info())
            or (visor.interior.winfo_reqwidth() > ancho
                and not visor.horizontal.grid_info()))


def medir_dialogo(fabricar, ancho, alto, escala) -> tuple[bool, bool]:
    """Abre un diálogo sin enseñarlo y devuelve (cabe, recortado)."""
    pantalla(ancho, alto, escala)
    medida: dict = {}

    def falso_mostrar(dlg, parent=None):
        dlg.visor.encajar(dlg)
        medida["cabe"] = cabe(dlg)
        medida["recortado"] = recortado(dlg.visor)

    tk_pairs.mostrar = falso_mostrar
    tk.Toplevel.wait_window = lambda self, *a, **k: None
    fabricar()
    return medida.get("cabe", False), medida.get("recortado", True)


try:
    # --- el asistente, paso a paso ---------------------------------------------------
    # Los pasos 5, 6 y 8 necesitan un dispositivo elegido; los que se pueden pintar
    # sin nada montado son los que llevan formulario, que son los que se salían.
    DIBUJABLES = (0, 1, 2, 3, 6)

    for nombre, ancho, alto, escala in PANTALLAS:
        pantalla(ancho, alto, escala)
        top = tk.Toplevel(raiz)
        top.withdraw()
        wiz = tk_install.build(top)
        for i in DIBUJABLES:
            wiz.indice = i
            wiz.repintar()
            paso = tk_install.PASOS[i][0]
            c(f"{nombre}: el paso «{paso}» cabe en la ventana", cabe(top), True)
            c(f"{nombre}: el paso «{paso}» no queda recortado",
              recortado(wiz.visor), False)
        top.destroy()

    # El caso que se reportó: en una pantalla normal el paso 1 tiene que verse
    # entero, no desplazarse. Una barra ahí sería tapar el fallo, no arreglarlo.
    # En una 4K, donde sobra sitio, igual.
    for nombre, ancho, alto, escala in (("1080p", 1920, 1080, 1.3333),
                                        ("4K al 150 %", 3840, 2160, 2.0)):
        pantalla(ancho, alto, escala)
        top = tk.Toplevel(raiz)
        top.withdraw()
        wiz = tk_install.build(top)
        top.update_idletasks()          # sin esto la barra aún no está puesta
        c(f"{nombre}: el paso 1 se ve entero, sin barra",
          bool(wiz.visor.vertical.grid_info()), False)
        c(f"{nombre}: el hueco de los pasos llega a lo que pide el paso 1",
          wiz.visor._medida()[1] >= wiz.visor.interior.winfo_reqheight(), True)
        # ...y el hueco crece con el paso más grande, pero no encoge con el más
        # pequeño: el asistente no puede cambiar de tamaño a cada paso.
        alto_paso1 = wiz.visor._medida()[1]
        wiz.indice = 1
        wiz.repintar()
        c(f"{nombre}: un paso corto no encoge el hueco",
          wiz.visor._medida()[1], alto_paso1)
        top.destroy()

    # En una 1080p al 200 % no cabe por mucho que se estire, y entonces la barra es
    # obligatoria: es la comprobación de que un recorte nunca es silencioso.
    pantalla(1920, 1080, 2.6667)
    top = tk.Toplevel(raiz)
    top.withdraw()
    wiz = tk_install.build(top)
    top.update_idletasks()
    c("1080p al 200 %: lo que no cabe se desplaza, con su barra",
      bool(wiz.visor.vertical.grid_info()), True)
    top.destroy()

    # --- los diálogos -----------------------------------------------------------------
    REAL_MOSTRAR, REAL_WAIT = tk_pairs.mostrar, tk.Toplevel.wait_window
    try:
        for nombre, ancho, alto, escala in PANTALLAS:
            with sandbox():
                model.CONFIG_FILE.write_text(config_file.dumps(BASE), encoding="utf-8")
                cfg = model.parse_config(BASE)
                for que, fabricar in (
                        ("la pantalla de parejas",
                         lambda: tk_pairs.open_dialog(raiz, cfg)),
                        ("el formulario de una pareja",
                         lambda: tk_pairs.formulario(raiz, dict(BASE), "pareja0",
                                                     dict(BASE["pair"][0]))),
                        ("el editor de flags",
                         lambda: tk_pairs.flags_form(raiz, "Flags", "pareja0", {},
                                                     [], "bisync", {}))):
                    entra, corta = medir_dialogo(fabricar, ancho, alto, escala)
                    c(f"{nombre}: {que} cabe", entra, True)
                    c(f"{nombre}: {que} no queda recortado", corta, False)
    finally:
        tk_pairs.mostrar, tk.Toplevel.wait_window = REAL_MOSTRAR, REAL_WAIT
finally:
    uitk.pantalla_util = PANTALLA_REAL
    raiz.tk.call("tk", "scaling", ESCALA_REAL)

raiz.destroy()
sys.exit(c.report())
