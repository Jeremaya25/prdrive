#!/usr/bin/env python3
"""El icono de un botón cae a la altura de su texto.

ttk centra la imagen en la caja de la línea (ascenso + descenso), pero el texto
no ocupa esa caja: sus mayúsculas empiezan bastante por debajo del ascenso, que
reserva sitio para las tildes. Ese hueco de arriba deja la masa del texto más
baja que el centro de la caja, y el icono se vería flotando por encima (1 px a
96 ppp, medido sobre la ventana de verdad).

Por eso la imagen se da ya con la altura de la línea y el dibujo bajado, en vez
de dejar que ttk la centre. Aquí se comprueban las dos cosas que lo hacen
funcionar: que el dibujo cae donde se pide, y que la imagen NO es más alta que
la línea: si creciera, crecería el botón, se movería el texto con él y no se
llegaría nunca.
"""

from __future__ import annotations

import sys

from _harness import Checks

c = Checks("iconos: alineados con su texto")

from ui import icons, theme  # noqa: E402

theme.nitidez()

import tkinter as tk  # noqa: E402
from tkinter import font as tkfont, ttk  # noqa: E402

raiz = tk.Tk()
raiz.withdraw()
theme.apply(raiz)
# `icons.px()` escala con `tk scaling`, así que un 15 del diseño solo son 15
# píxeles a 96 ppp. Se fija aquí —1,3333 es esa densidad— porque lo que se
# comprueba abajo es el dibujo, no la densidad de la pantalla de quien ejecute
# el test: sin esto fallaría en un portátil al 150 % igual que en un X virtual.
raiz.tk.call("tk", "scaling", 1.3333)

FONDO = theme.PAPEL


def filas_con_tinta(img):
    """Las filas de la imagen donde hay algo pintado: lo que no es transparente."""
    ancho, alto = img.width(), img.height()
    return [y for y in range(alto)
            if any(not img.transparency_get(x, y) for x in range(ancho))]


# el dibujo cae donde se le dice
suelto = icons.get(raiz, "parejas", 15, theme.ACENTO, FONDO)
c("sin pedir nada, la imagen es cuadrada", (suelto.width(), suelto.height()), (15, 15))
arriba = filas_con_tinta(suelto)[0]

bajado = icons.get(raiz, "parejas", 15, theme.ACENTO, FONDO, bajar=2, alto=17)
c("con altura dada, la imagen la respeta", (bajado.width(), bajado.height()), (15, 17))
c("y el dibujo baja justo lo pedido", filas_con_tinta(bajado)[0], arriba + 2)
c("las filas de encima son transparentes", filas_con_tinta(bajado)[0] >= 2, True)

# lo que monta `boton_icono` sobre un botón de verdad
m = tkfont.Font(root=raiz, font=theme.fuente("normal")).metrics()
real = icons.px(raiz, 15)

boton = ttk.Button(raiz, text="PAREJAS", style="Quiet.TButton")
theme.boton_icono(boton, "parejas", theme.ACENTO, FONDO)
img = boton.image

c("la imagen es tan alta como la línea del texto", img.height(), max(m["linespace"], real))
c("y nunca más alta: el botón no crece", img.height() <= max(m["linespace"], real), True)
c("el dibujo se baja, pero sin salirse", 0 <= filas_con_tinta(img)[0], True)
c("y cabe entero", filas_con_tinta(img)[-1] < img.height(), True)

# …y su centro cae en el de las mayúsculas, no en el de la caja de la línea:
# esa caja reserva arriba sitio para las tildes y abajo para las colas.
letra = tkfont.Font(root=raiz, font=theme.fuente("texto"))
em = letra.actual("size") * 1.3333
centro = letra.metrics("ascent") - theme.ALTURA_MAYUSCULAS * em / 2
filas = filas_con_tinta(img)
c("el icono se centra en las mayúsculas, a medio píxel",
  abs((filas[0] + filas[-1] + 1) / 2 - centro) <= 1.5, True)

# El botón tiene que medir lo mismo que medía sin tocar nada: si el ajuste lo
# hiciera crecer, movería el texto con él y no habría alineación que valga.
crudo = ttk.Button(raiz, text="PAREJAS", style="Quiet.TButton")
plano = icons.get(crudo, "parejas", 15, theme.ACENTO, FONDO)
crudo.configure(image=plano, compound="left")
crudo.image = plano
raiz.update_idletasks()
c("el botón mide lo mismo que antes del ajuste",
  (boton.winfo_reqwidth(), boton.winfo_reqheight()),
  (crudo.winfo_reqwidth(), crudo.winfo_reqheight()))

# ningún glifo toca el borde de su mapa de bits
#
# Un trazo sale media anchura por fuera de su punto (`_expandir`), así que un
# glifo dibujado hasta el borde de la rejilla se recorta al rasterizar y se ve
# partido. Pasaba con el electrocardiograma del doctor.
for nombre in sorted(icons.GLIFOS):
    r = icons._capas_rgba([(theme.ACENTO, icons.TRAZO, icons.GLIFOS[nombre])], 16.0, 15)
    filas = [y for y in range(15) if any(p[3] > 0.02 for p in r[y])]
    cols = [x for x in range(15) if any(r[y][x][3] > 0.02 for y in range(15))]
    c(f"el glifo '{nombre}' no toca el borde",
      (filas[0], filas[-1], cols[0], cols[-1]) != ()
      and filas[0] > 0 and filas[-1] < 14 and cols[0] > 0 and cols[-1] < 14, True)

raiz.destroy()
sys.exit(c.report())
