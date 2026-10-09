#!/usr/bin/env python3
"""El `Visor` reserva el hueco de la barra horizontal, pero la crea solo si hace falta.

Cada ventana de la aplicación vive dentro de un `Visor` y la barra horizontal
casi nunca se ve; crearla con el `Visor` era un widget y un estilo de ttk de más
en todas las ventanas. Se comprueba que:
- Un `Visor` recién hecho no tiene barra horizontal (`horizontal is None`) y la
  franja que le corresponde sigue reservada, del grosor exacto de una barra
  horizontal de verdad, así que la ventana pide el mismo tamaño que antes.
- Contenido más ancho que la mirilla la crea y la pone; al menguar el contenido
  se quita (`grid_remove`) pero no se destruye.
- Desplazar el eje horizontal sin barra no falla, y con barra se lo dice.
- Crearla con la ventana ya enseñada no manda `<<ThemeChanged>>` ni crea
  estilos: ningún estilo de ttk se toca después del primer widget.
- `cuerpo_visible(directo=True)` dibuja en el `interior` mismo.

Las ventanas se crean sin entrar en el bucle de eventos.
"""

import sys

from _harness import Checks

c = Checks("el Visor crea su barra horizontal solo cuando hace falta")

try:
    import tkinter as tk
    from tkinter import ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(0)

from ui import icons, theme                              # noqa: E402
from ui import tk as uitk                                # noqa: E402

theme.apply(raiz)


def con_visor(padre, **opciones):
    """Devuelve un `Visor` puesto en `padre`, como lo deja `cuerpo_visible()`."""
    visor = uitk.Visor(padre, **opciones)
    visor.marco.grid(row=0, column=0, sticky="nsew")
    padre.columnconfigure(0, weight=1)
    padre.rowconfigure(0, weight=1)
    return visor


def descendientes(widget):
    """Devuelve cada widget que cuelga de `widget`, a cualquier profundidad."""
    for hijo in widget.winfo_children():
        yield hijo
        yield from descendientes(hijo)


def estilos(interprete) -> list:
    """Devuelve lo que se sabe de los estilos de ttk, para ver si cambian.

    `ttk::style theme styles` solo existe en Tk 9; en Tk 8.6 se compara lo que
    el tema dice de los estilos de las barras, que es lo que se podría tocar.
    """
    try:
        return sorted(interprete.splitlist(interprete.call("ttk::style", "theme", "styles")))
    except tk.TclError:
        return [str(interprete.call("ttk::style", orden, estilo))
                for estilo in ("Horizontal.TScrollbar", "Vertical.TScrollbar")
                for orden in ("layout", "configure")]


def relleno(marco) -> tuple[int, ...]:
    """Devuelve el `padding` de un marco como cuatro enteros."""
    return tuple(int(str(x)) for x in marco.tk.splitlist(marco.cget("padding")))


def minsize_fila(visor) -> int:
    """Devuelve el alto reservado para la fila de la barra horizontal."""
    return int(visor.marco.grid_rowconfigure(1)["minsize"])


# 1. Un Visor recién hecho: sin barra horizontal y con su franja reservada
top = tk.Toplevel(raiz)
top.withdraw()
visor = con_visor(top, ancho=300, alto=200)
c("un Visor nuevo no tiene barra horizontal", visor.horizontal, None)
c("  ni ha puesto ninguna barra", visor.barras(), (False, False))
horizontal = ttk.Scrollbar(top, orient="horizontal")
c("la franja reservada es del grosor de una barra horizontal (la ventana pide lo de siempre)",
  minsize_fila(visor), horizontal.winfo_reqheight())
c("  y es el ancho de la vertical, que es lo que se ha medido para no crear la otra",
  minsize_fila(visor), visor.vertical.winfo_reqwidth())
top.update_idletasks()
c("  el recuadro pide su mirilla y la franja debajo",
  visor.marco.winfo_reqheight(), visor.lienzo.winfo_reqheight() + minsize_fila(visor))
c("  y la columna de la vertical, a su derecha",
  visor.marco.winfo_reqwidth(),
  visor.lienzo.winfo_reqwidth() + int(visor.marco.grid_columnconfigure(1)["minsize"]))
horizontal.destroy()

# 2. Sin que sobre nada por el lado, no se crea ni se mueve nada
boton = ttk.Button(visor.interior, text="Botón")
boton.grid(row=0, column=0)
top.update_idletasks()
c("con el contenido dentro de la mirilla no hay barra horizontal", visor.horizontal, None)
c("  ni vertical", visor.barras(), (False, False))
visor._desplazar(0, "moveto", "0.5")
c("desplazar en horizontal sin barra no falla ni se mueve", visor.desplazado(), (0, 0))
visor._desplazar(0, "scroll", "1", "pages")
c("  tampoco con una página", visor.desplazado(), (0, 0))
visor.encajar(top)
c("encajar con el contenido pequeño tampoco la crea", visor.horizontal, None)

# 3. Contenido más ancho que la mirilla: se crea, se pone y habla con el Visor
ancho = ttk.Frame(visor.interior, width=700, height=20)
ancho.grid(row=1, column=0, sticky="w")
top.update_idletasks()
barra = visor.horizontal
c("contenido más ancho que la mirilla: la barra horizontal existe", barra is not None, True)
c("  es una barra horizontal", str(barra.cget("orient")), "horizontal")
c("  sin barra vertical, porque el alto cabe", visor.barras(), (False, True))
c("  puesta en la fila reservada, bajo la mirilla",
  (int(barra.grid_info()["row"]), int(barra.grid_info()["column"]),
   barra.grid_info()["sticky"]), (1, 0, "ew"))
c("  y ya sabe lo que se ve del contenido: no empieza llena",
  0.0 < float(barra.get()[1]) < 1.0, True)
c("  la franja sigue midiendo lo mismo", minsize_fila(visor), barra.winfo_reqheight())

visor._desplazar(0, "moveto", "0.5")
total, hueco = visor._puesto[0], visor._hueco()[0]
c("moveto 0.5 lleva el contenido a la mitad de su ancho (sin pasarse del final)",
  visor.desplazado()[0], min(round(total / 2), total - hueco))
c("  y mueve el contenido", int(visor.interior.place_info()["x"]), -visor.desplazado()[0])
c("  y lo dice a la barra", round(float(barra.get()[0]), 3),
  round(visor.desplazado()[0] / total, 3))
visor._desplazar(0, "moveto", "1.0")
c("no se pasa del final", visor.desplazado()[0], total - hueco)
visor._desplazar(0, "scroll", "-100", "pages")
c("ni del principio", visor.desplazado()[0], 0)

# 4. Al menguar el contenido, la barra se quita pero no se destruye
ancho.configure(width=20)
top.update_idletasks()
c("al menguar el contenido, la barra se quita", visor.barras(), (False, False))
c("  pero no se destruye: es la misma", visor.horizontal is barra, True)
c("  y sigue viva", bool(barra.winfo_exists()), True)
ancho.configure(width=900)
top.update_idletasks()
c("al volver a ensancharlo se vuelve a poner, la misma", (visor.barras(), visor.horizontal is barra),
  ((False, True), True))

# 5. La vertical sigue como antes
alto = ttk.Frame(visor.interior, width=20, height=600)
alto.grid(row=2, column=0, sticky="w")
top.update_idletasks()
c("con contenido alto y ancho, las dos barras", visor.barras(), (True, True))
alto.destroy()
ancho.destroy()
top.update_idletasks()
c("al quitar el contenido grande no queda ninguna", visor.barras(), (False, False))
top.destroy()

# 5b. Antes del primer ajuste la mirilla es un tamaño de partida: no se crea nada
top = tk.Toplevel(raiz)
top.withdraw()
visor = con_visor(top)                       # sin tamaño: la mirilla parte de 200x150
ttk.Frame(visor.interior, width=500, height=20).grid(row=0, column=0, sticky="w")
top.update_idletasks()
top.update_idletasks()
c("sin ajustar todavía, el contenido que desborda la mirilla de partida no crea la barra",
  (visor.horizontal, visor.barras()), (None, (False, False)))
visor.encajar(top)
top.update_idletasks()
c("  ajustado al contenido, tampoco: cabe", (visor.horizontal, visor.barras()),
  (None, (False, False)))
top.destroy()

# 5b2. El contenido crece y se encaja o se crece (lo que hace cada ventana al cambiar):
#      mientras se mide, la mirilla aún es la de antes y no hay que crear nada
for como in ("encajar", "crecer"):
    top = tk.Toplevel(raiz)
    top.withdraw()
    visor = con_visor(top)
    ttk.Frame(visor.interior, width=200, height=80).grid(row=0, column=0, sticky="w")
    visor.encajar(top)
    top.update_idletasks()
    ttk.Frame(visor.interior, width=600, height=80).grid(row=1, column=0, sticky="w")
    getattr(visor, como)(top)
    top.update_idletasks()
    top.update_idletasks()
    c(f"el contenido crece y se llama a {como}(): la mirilla se agranda y no se crea barra",
      (visor.horizontal, visor.barras(), visor._medida()[0] >= 600),
      (None, (False, False), True))
    top.destroy()

# 5c. Ni la pantalla da para el contenido: encajar la crea, y desplazar funciona
util_real = uitk.pantalla_util
uitk.pantalla_util = lambda win: (800, 600)
try:
    top = tk.Toplevel(raiz)
    top.withdraw()
    visor = con_visor(top)
    ttk.Frame(visor.interior, width=1500, height=20).grid(row=0, column=0, sticky="w")
    visor.encajar(top)
    top.update_idletasks()                   # el reposo en que la mirilla mide ya lo nuevo
    c("contenido más ancho que la pantalla: al encajar se crea la barra y se pone",
      visor.barras(), (False, True))
    visor._desplazar(0, "scroll", "1", "pages")
    c("  y se desplaza, con la barra al día",
      (visor.desplazado()[0] > 0, float(visor.horizontal.get()[0]) > 0.0), (True, True))
    top.destroy()
finally:
    uitk.pantalla_util = util_real

# 6. Crearla con la ventana ya enseñada: ni <<ThemeChanged>> ni estilos nuevos
top = tk.Toplevel(raiz)
visor = con_visor(top, ancho=300, alto=200)
ttk.Button(visor.interior, text="Botón").grid(row=0, column=0)
visor.encajar(top)
top.deiconify()
top.update()
cambios_de_tema: list = []
top.bind_all("<<ThemeChanged>>", lambda e: cambios_de_tema.append(str(e.widget)))
estilos_antes = estilos(raiz.tk)
ancho = ttk.Frame(visor.interior, width=700, height=20)
ancho.grid(row=1, column=0, sticky="w")
top.update()
top.update()
c("la barra se crea con la ventana enseñada", visor.barras(), (False, True))
c("  sin <<ThemeChanged>> para nadie", cambios_de_tema, [])
c("  y sin un estilo de ttk nuevo ni tocado", estilos(raiz.tk), estilos_antes)
c("  y con el estilo del tema, el de `Horizontal.TScrollbar`",
  visor.horizontal.winfo_class(), "TScrollbar")
top.unbind_all("<<ThemeChanged>>")
top.destroy()

# 7. El grosor reservado es el de una barra horizontal, a cada escala, en este Tk
valores: dict = {}
for escala in (1.0, 1.3333, 2.0):
    yo = tk.Tk()
    yo.withdraw()
    yo.tk.call("tk", "scaling", escala)
    theme.apply(yo)
    try:
        v = con_visor(yo, ancho=200, alto=150)
        h = ttk.Scrollbar(yo, orient="horizontal")
        valores[escala] = (minsize_fila(v), h.winfo_reqheight(), v.vertical.winfo_reqwidth())
    finally:
        interp = yo.tk
        yo.destroy()
        theme.olvidar(interp)
        icons.olvidar(interp)
c("a 100, 133 y 200 % la franja reservada es el grosor de la barra horizontal "
  f"(Tk {raiz.tk.call('info', 'patchlevel')})",
  {e: v[0] == v[1] == v[2] for e, v in valores.items()},
  {1.0: True, 1.3333: True, 2.0: True})

# 8. cuerpo_visible(directo=True): se dibuja en el interior, sin un marco más
top = tk.Toplevel(raiz)
top.withdraw()
marco = uitk.cuerpo_visible(top, padding=(7, 8, 9, 10))
c("por defecto, el marco es un hijo del interior (un marco más)",
  marco.master is top.visor.interior, True)
c("  que se estira: la columna y la fila del interior pesan",
  (top.visor.interior.grid_columnconfigure(0)["weight"],
   top.visor.interior.grid_rowconfigure(0)["weight"]), (1, 1))
c("  y lleva las opciones", relleno(marco),
  (7, 8, 9, 10))
top.destroy()

top = tk.Toplevel(raiz)
top.withdraw()
marco = uitk.cuerpo_visible(top, directo=True, padding=(7, 8, 9, 10))
c("con directo=True, el marco es el interior mismo", marco is top.visor.interior, True)
c("  con las opciones puestas", relleno(marco),
  (7, 8, 9, 10))
c("  sin tocar las columnas ni las filas del interior (las pone quien dibuja)",
  (marco.grid_columnconfigure(0)["weight"], marco.grid_rowconfigure(0)["weight"]), (0, 0))
c("  y el Visor es todo lo que se ha creado: marco, mirilla, barra vertical e interior",
  len(list(descendientes(top))), 4)
top.destroy()

# 9. Sin Visor.horizontal en ninguna ventana que no la necesite
top = tk.Toplevel(raiz)
top.withdraw()
uitk.cuerpo_visible(top)
top.visor.encajar(top)
c("una ventana con su `cuerpo_visible` no crea la barra horizontal", top.visor.horizontal, None)
top.destroy()
raiz.destroy()
sys.exit(c.report())
