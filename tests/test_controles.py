#!/usr/bin/env python3
"""Los controles dibujados: piezas redondeadas, su asiento, la letra y la escala.

El tema deja de pintar con clam los controles que el diseño redondea y los
pinta con piezas de imagen (`theme._controles`, `icons.caja`). Aquí se
comprueba lo que, si falla, no se ve en una prueba de pantallas:

- que la pieza es de verdad transparente por fuera de la forma (si no, las
  esquinas saldrían cuadradas de otro color);
- que un control que cae sobre una tarjeta toma el fondo de la tarjeta
  (`_asentar`), y uno sobre el papel se queda con su estilo;
- que la letra propia se carga y es la que eligen los roles;
- que un botón mide el alto del diseño;
- y que en `ui/tk*.py` no queda ningún espaciado fuera de la escala `E1…E7`.
"""

from __future__ import annotations

import re
import sys

from _harness import REPO, Checks

c = Checks("controles: piezas redondeadas, asiento, letra y escala")

from ui import icons, theme  # noqa: E402

theme.nitidez()

# 1. ningún espaciado fuera de la escala
#
# Va antes que nada que necesite pantalla: es lo que más fácil se rompe (un
# `padx=10` nuevo) y no hace falta Tk para verlo.
SUELTO = re.compile(r"\b(?:padx|pady|padding|ipadx|ipady)=\(?\s*(-?\d+)\s*(?:,\s*(-?\d+)\s*)*\)?")
fuera = []
for ruta in sorted((REPO / "ui").glob("tk*.py")):
    for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
        for m in SUELTO.finditer(linea):
            numeros = re.findall(r"-?\d+", m.group(0))
            if any(x != "0" for x in numeros):
                fuera.append(f"{ruta.name}:{n}: {m.group(0)}")
c("ningún espaciado de ui/tk*.py se sale de la escala E1…E7", fuera, [])

try:
    import tkinter as tk
    from tkinter import ttk
    raiz = tk.Tk()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

raiz.tk.call("tk", "scaling", 1.3333)
theme.apply(raiz)
raiz.configure(background=theme.PAPEL)     # como toda ventana de la aplicación
style = ttk.Style(raiz)

# 2. la pieza es transparente por fuera y opaca por dentro
img, borde = icons.caja(raiz, [(theme.BORDE, 0), (theme.SUPERFICIE, 1)])
c("la pieza se pinta", img is not None, True)
c("con un borde de nueve trozos mayor que el radio", borde > icons.px(raiz, theme.RADIO), True)
c("la esquina es transparente", img.transparency_get(0, 0), True)
c("el centro no", img.transparency_get(img.width() // 2, img.height() // 2), False)
aro, _ = icons.caja(raiz, [(theme.ACENTO, 0), (None, 2)])
c("un tono None recorta: el aro es hueco",
  aro.transparency_get(aro.width() // 2, aro.height() // 2), True)

# 3. los estilos usan las piezas, no los elementos de clam
for estilo in ("TButton", "Primary.TButton", "Quiet.TButton", "TEntry",
               "TCombobox", "TSpinbox", "Card.TFrame", "Ok.Chip.TLabel",
               "Primero.Segmento.Toolbutton"):
    c(f"{estilo} lleva su pieza", "Prdrive." in str(style.layout(estilo)), True)
c("las flechas se llaman como las de clam: los bindings deciden por el nombre",
  "downarrow" in str(style.layout("TCombobox")), True)

# 4. el asiento: sobre la tarjeta toma su fondo, sobre el papel se queda
raiz.geometry("+0+0")
tarjeta = ttk.Frame(raiz, style="Card.TFrame", padding=theme.E4)
tarjeta.pack()
en_tarjeta = ttk.Button(tarjeta, text="Guardar", style="Primary.TButton")
en_tarjeta.pack()
en_papel = ttk.Button(raiz, text="Cancelar")
en_papel.pack()
plano = ttk.Frame(tarjeta, style="Plano.Card.TFrame")
plano.pack()
grupo = theme.grupo_botones(raiz, [("Uno", "1"), ("Dos", "2"), ("Tres", "3")],
                            tk.StringVar(raiz, "1"))
grupo.pack()
raiz.update()

blanco = theme._hex(raiz, theme.SUPERFICIE)
estilo = str(en_tarjeta.cget("style"))
c("el botón de la tarjeta pasa a su variante de ese fondo", estilo,
  f"Sobre{blanco[1:]}.Primary.TButton")
c("que tiene el fondo de la tarjeta",
  theme._hex(raiz, style.lookup(estilo, "background")), blanco)
c("y la misma pieza que el original", style.layout(estilo),
  style.layout("Primary.TButton"))
c("el del papel se queda con su estilo", str(en_papel.cget("style")), "")
c("un marco plano no se asienta", str(plano.cget("style")), "Plano.Card.TFrame")
c("el grupo redondea solo por fuera",
  [str(b.cget("style")) for b in grupo.botones],
  ["Primero.Segmento.Toolbutton", "Medio.Segmento.Toolbutton",
   "Ultimo.Segmento.Toolbutton"])

# 5. un botón mide el alto del diseño
c("un botón mide 34 px, a uno", abs(en_papel.winfo_reqheight() - 34) <= 1, True)

# 6. la letra propia
if sys.platform == "win32" or sys.platform.startswith("linux"):
    c("la letra de ui/fuentes/ se carga", theme.cargar_fuentes(), True)
    c("y es la del texto", theme.familia("texto"), "Noto Sans")
    c("la seminegrita es su propia familia", theme.familia("fuerte"),
      "Noto Sans SemiBold")
    c("y la monoespaciada", theme.familia("mono"), "Noto Sans Mono")
else:
    print("  (saltado) la letra propia solo se carga en Windows y Linux")
c("la licencia viaja con la letra", (theme.FUENTES / "OFL.txt").is_file(), True)

raiz.destroy()
sys.exit(c.report())
