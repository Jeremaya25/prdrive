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
- `encajar()` llega al tamaño final sin dar nunca al recuadro uno que no se
  queda cuando puede saberlo sin probar (en Windows cada cambio de tamaño de la
  ventana repinta todos sus widgets), y el tamaño final es el de siempre.
- La barra horizontal no existe mientras el contenido cabe; al aparecer y al
  quitarse no mueve lo que se ve ni cambia el tamaño de la ventana, y el mismo
  widget vuelve a ponerse.

Las ventanas se crean sin entrar en el bucle de eventos.
"""

import sys

from _harness import Checks
from _vista import estilos

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

# 10. encajar() llega al tamaño final sin dar nunca al recuadro uno que no se queda.
#     En Windows cada cambio de tamaño de la ventana repinta todos sus widgets
#     (cada uno es una ventana del sistema): estirar el recuadro hasta lo que
#     pide el contenido entero —más que la pantalla— para medir lo que sobra y
#     encogerlo después repintaba la ventana dos veces sin cambiar nada.
ANCHO_PANTALLA, ALTO_PANTALLA = 800, 600
ALTO_CABECERA, ALTO_PIE = 24, 36
PANTALLA_ANTERIOR = uitk.pantalla_util
uitk.pantalla_util = lambda win: (ANCHO_PANTALLA, ALTO_PANTALLA)


def ventana_visor(ancho, alto, pie=10):
    """Devuelve `(ventana, visor, contenido)`: una ventana como las de la aplicación.

    Cabecera arriba, el `Visor` en medio y el pie debajo, con las medidas
    puestas a mano para saber cuánto vale "el resto de la ventana". El contenido
    es un marco del tamaño pedido. `pie` es el ancho que pide el pie: si es
    mayor que el recuadro, la ventana no se ensancha al ensancharse este.
    """
    top = tk.Toplevel(raiz)
    top.withdraw()
    ttk.Frame(top, width=10, height=ALTO_CABECERA).grid(row=0, column=0, sticky="ew")
    visor = uitk.Visor(top)
    visor.marco.grid(row=1, column=0, sticky="nsew")
    ttk.Frame(top, width=pie, height=ALTO_PIE).grid(row=2, column=0, sticky="ew")
    top.columnconfigure(0, weight=1)
    top.rowconfigure(1, weight=1)
    contenido = ttk.Frame(visor.interior, width=ancho, height=alto)
    contenido.grid(row=0, column=0)
    return top, visor, contenido


def seguir(top, visor):
    """Empieza a anotar lo que le pasa a la ventana y al recuadro.

    Returns:
        `(visto, dado)`, dos listas que se van llenando: `visto` con el
        `(ancho, alto)` de la ventana en cada `<Configure>` que recibe, y `dado`
        con el `(ancho, alto)` de cada vez que se le cambia el tamaño al recuadro.
    """
    visto, dado = [], []
    top.bind("<Configure>",
             lambda e: visto.append((e.width, e.height)) if e.widget is top else None)
    original = visor.lienzo.configure

    def configurar(*a, **kw):
        if "width" in kw and "height" in kw:
            dado.append((int(kw["width"]), int(kw["height"])))
        return original(*a, **kw)

    visor.lienzo.configure = configurar
    return visto, dado


def referencia(visor, ventana):
    """Devuelve el tamaño que dejaba `encajar()` al medir con el recuadro estirado.

    Es el algoritmo de dos pasos —estirar el recuadro hasta lo que pide el
    contenido, medir lo que sobra de la ventana y recortar—, exacto pero con la
    ventana más allá de la pantalla durante la medida. Aquí es la referencia del
    tamaño final y deja el recuadro como lo encontró.
    """
    dejado = visor._medida()
    visor._ajustando += 1
    try:
        ancho, alto = visor._natural()
        visor._fijar(ancho, alto)
        tope_x, tope_y = visor._tope(ventana)
    finally:
        visor._ajustando -= 1
    visor._fijar(*dejado)
    return (min(ancho, tope_x), min(alto, tope_y))


try:
    # 10a. Contenido más alto que la pantalla, encajado dos veces sin cambiar nada
    top, visor, contenido = ventana_visor(300, 2000)
    franja = minsize_fila(visor)
    vertical = int(visor.marco.grid_columnconfigure(1)["minsize"])
    resto_y = ALTO_CABECERA + franja + ALTO_PIE
    visto, dado = seguir(top, visor)
    visor.encajar(top)
    top.deiconify()
    top.update()
    final = (top.winfo_width(), top.winfo_height())
    medida = visor._medida()
    c("contenido más alto que la pantalla: el recuadro llena lo que queda de ella",
      medida, (300, ALTO_PANTALLA - resto_y))
    c("  y la ventana pide justo la pantalla útil de alto", top.winfo_reqheight(), ALTO_PANTALLA)
    del visto[:], dado[:]
    cambio = visor.encajar(top)
    top.update()
    c("encajar otra vez sin cambiar nada: no dice que haya cambiado", cambio, False)
    c("  la ventana no toma ningún tamaño que no sea el final (ningún <Configure> de más)",
      [t for t in visto if t != final], [])
    c("  el recuadro no toma ningún tamaño que no se quede", [t for t in dado if t != medida], [])
    c("  y el tamaño del recuadro es el mismo", visor._medida(), medida)
    c("  y la ventana también", (top.winfo_width(), top.winfo_height()), final)

    # 10b. El contenido sigue sin caber y crece un poco más
    contenido.configure(height=2058)
    del visto[:], dado[:]
    cambio = visor.encajar(top)
    top.update()
    c("el contenido crece 58 px y sigue sin caber: la ventana no pasa nunca de su altura",
      [t for t in visto if t[1] > final[1] or t[0] > final[0]], [])
    c("  ni la del recuadro, que no toma ningún tamaño que no se quede",
      [t for t in dado if t != medida], [])
    c("  el recuadro queda en lo de siempre: lo que deja libre la ventana",
      visor._medida(), (300, ALTO_PANTALLA - resto_y))
    c("  sin decir que cambió", cambio, False)
    c("  y la ventana, en el tamaño de antes", (top.winfo_width(), top.winfo_height()), final)
    contenido.configure(height=1500)
    del visto[:], dado[:]
    visor.encajar(top)
    top.update()
    c("  si el contenido mengua y aún no cabe, tampoco se mueve nada",
      ([t for t in visto if t != final], [t for t in dado if t != medida]), ([], []))
    top.destroy()

    # 10c. Contenido que cabe y crece: un solo cambio de tamaño, al natural
    top, visor, contenido = ventana_visor(300, 200)
    visto, dado = seguir(top, visor)
    visor.encajar(top)
    top.deiconify()
    top.update()
    antes = (top.winfo_width(), top.winfo_height())
    c("contenido que cabe: la ventana mide lo que pide (cabecera, recuadro y pie)",
      antes, (300 + vertical, ALTO_CABECERA + 200 + franja + ALTO_PIE))
    contenido.configure(height=260)
    del visto[:], dado[:]
    cambio = visor.encajar(top)
    top.update()
    c("  el contenido crece 60 px y aún cabe: el recuadro cambia y lo dice", cambio, True)
    c("  una sola vez, a lo que pide el contenido", dado, [(300, 260)])
    c("  la ventana toma un solo tamaño, el final",
      set(visto), {(antes[0], antes[1] + 60)})
    top.destroy()

    # 10d. Primer desbordamiento, con la ventana sin enseñar: lo de siempre
    top, visor, contenido = ventana_visor(1500, 2000)
    visto, dado = seguir(top, visor)
    cambio = visor.encajar(top)
    top.update_idletasks()                   # el reposo en que la ventana pide ya lo nuevo
    c("contenido mayor que la pantalla en las dos direcciones, con la ventana oculta: "
      "el recuadro llena lo que queda de ella",
      visor._medida(), (ANCHO_PANTALLA - vertical, ALTO_PANTALLA - resto_y))
    c("  y lo dice", cambio, True)
    c("  la ventana pide justo la pantalla útil", (top.winfo_reqwidth(), top.winfo_reqheight()),
      (ANCHO_PANTALLA, ALTO_PANTALLA))
    c("  con las dos barras", visor.barras(), (True, True))
    del visto[:], dado[:]
    visor.encajar(top)
    c("  y encajar otra vez no toca el recuadro", [t for t in dado if t != visor._medida()], [])
    top.destroy()

    # 10e. Un recuadro que `crecer()` dejó recortado también se vuelve a encajar sin rebote
    top, visor, contenido = ventana_visor(300, 2000)
    visto, dado = seguir(top, visor)
    visor.crecer(top)
    top.deiconify()
    top.update()
    medida = visor._medida()
    final = (top.winfo_width(), top.winfo_height())
    c("crecer() con el contenido más alto que la pantalla da un solo tamaño al recuadro",
      dado, [medida])
    c("  que es lo que deja libre la ventana", medida, (300, ALTO_PANTALLA - resto_y))
    del visto[:], dado[:]
    visor.encajar(top)
    top.update()
    c("  y encajar después no estira el recuadro ni la ventana",
      ([t for t in visto if t != final], [t for t in dado if t != medida]), ([], []))
    top.destroy()

    # 10f. Lo que queda de la ventana no es una cifra fija: el algoritmo de siempre da el mismo
    #      tamaño final, con el pie estrecho (el recuadro manda en el ancho) y con uno más ancho
    #      que el recuadro (la ventana no crece al ensancharse este hasta alcanzarlo), con la
    #      ventana sin enseñar y enseñada.
    #      (qué pasa, ancho, alto, ¿puede rebotar?): rebota solo el primer desbordamiento
    #      por un lado, porque entonces no se sabe cuánto resta la ventana sin probar.
    PASOS_ESTRECHO = (
        ("cabe", 300, 200, False),
        ("desborda por abajo por primera vez", 300, 2000, True),
        ("crece un poco más", 300, 2058, False),
        ("mengua sin caber", 300, 1500, False),
        ("vuelve a crecer", 300, 2058, False),
        ("mengua hasta caber", 300, 400, False),
        ("crece sin dejar de caber", 300, 500, False),
        ("desborda por la derecha por primera vez", 1500, 500, True),
        ("desborda por los dos lados (el alto por primera vez)", 1500, 2000, True),
        ("crece por los dos lados", 1600, 2100, False),
        ("el ancho vuelve a caber", 400, 2100, False),
        ("el alto vuelve a caber", 400, 300, False),
    )
    PASOS_ANCHO = (
        ("cabe", 300, 200, False),
        ("crece, y el pie ancho sigue mandando en la ventana", 450, 200, False),
        ("crece, ya cerca del pie", 560, 200, False),
        ("crece pasando del pie", 700, 200, False),
        ("desborda la pantalla por primera vez", 900, 200, True),
        ("crece un poco más", 950, 200, False),
        ("mengua hasta caber, bajo el pie", 500, 200, False),
    )
    for nombre, pasos, pie in (("pie estrecho", PASOS_ESTRECHO, 10),
                               ("pie ancho", PASOS_ANCHO, 600)):
        for mapeada in (False, True):
            etiqueta = f"{nombre}, ventana {'enseñada' if mapeada else 'oculta'}"
            top, visor, contenido = ventana_visor(pasos[0][1], pasos[0][2], pie)
            visto, dado = seguir(top, visor)
            for i, (que, ancho, alto, rebota) in enumerate(pasos):
                contenido.configure(width=ancho, height=alto)
                antes = (top.winfo_width(), top.winfo_height())
                del visto[:], dado[:]
                visor.encajar(top)
                if mapeada:
                    if i == 0:
                        top.deiconify()
                    top.update()
                final = visor._medida()
                despues = (top.winfo_width(), top.winfo_height())
                # La referencia estira el recuadro: se anota lo de `encajar` antes de llamarla.
                vistos, dados = list(visto), list(dado)
                c(f"{etiqueta}, {que}: el mismo tamaño que daba estirar antes de medir",
                  final, referencia(visor, top))
                if i and not rebota:
                    c("  el recuadro solo toma el tamaño que se queda", set(dados) <= {final}, True)
                    if mapeada:
                        c("  y la ventana no pasa de ningún lado del mayor de sus dos tamaños",
                          [t for t in vistos if t[0] > max(antes[0], despues[0])
                           or t[1] > max(antes[1], despues[1])], [])
                if mapeada:
                    top.update()
            top.destroy()

    # 10g. Si la pantalla útil cambia (otro monitor, otra escala), el tamaño recortado de antes
    #      no vale: se vuelve a medir
    top, visor, contenido = ventana_visor(300, 2058)
    visor.encajar(top)
    top.deiconify()
    top.update()
    for pantalla_util in ((1000, 700), (700, 500), (1000, 700)):
        uitk.pantalla_util = lambda win, p=pantalla_util: p
        visor.encajar(top)
        top.update()
        c(f"la pantalla útil pasa a {pantalla_util[0]}x{pantalla_util[1]}: "
          "el recuadro sigue lo que queda",
          visor._medida(), (300, pantalla_util[1] - resto_y))
        c("  y es lo que daba estirar antes de medir", visor._medida(), referencia(visor, top))
        top.update()
    top.destroy()
finally:
    uitk.pantalla_util = PANTALLA_ANTERIOR

# 11. La barra horizontal se crea al desbordar y, al aparecer o quitarse, no mueve lo que se ve
#     ni cambia el tamaño de la ventana (sin barra, la franja ya está reservada en la ventana).
def barras_horizontales(ventana) -> list:
    """Devuelve las barras horizontales que cuelgan de `ventana`, estén puestas o no."""
    return [w for w in descendientes(ventana)
            if isinstance(w, ttk.Scrollbar) and str(w.cget("orient")) == "horizontal"]


def mapa(ventana, visor, hoja) -> tuple:
    """Devuelve dónde está lo que se ve y lo que pide la ventana, para ver si algo se movió."""
    return ((hoja.winfo_rootx(), hoja.winfo_rooty()),
            (visor.lienzo.winfo_rootx(), visor.lienzo.winfo_rooty()),
            (ventana.winfo_width(), ventana.winfo_height()),
            (ventana.winfo_reqwidth(), ventana.winfo_reqheight()))


top = tk.Toplevel(raiz)
top.withdraw()
visor = con_visor(top, ancho=300, alto=200)
hoja = ttk.Button(visor.interior, text="Hoja")
hoja.grid(row=0, column=0, sticky="nw")
ancho = ttk.Frame(visor.interior, width=20, height=20)
ancho.grid(row=1, column=0, sticky="w")
visor.encajar(top)                    # como `mostrar()`: la barra solo nace ya encajado
top.deiconify()
top.update()
c("con el contenido dentro de la mirilla, no existe ningún widget de barra horizontal",
  barras_horizontales(top), [])
reposo = mapa(top, visor, hoja)
ancho.configure(width=700)
top.update()
top.update()
barra = visor.horizontal
c("al desbordar por la derecha aparece la barra: una sola, y la del Visor",
  (len(barras_horizontales(top)), barra is not None and barra in barras_horizontales(top)),
  (1, True))
c("  puesta, y la barra vertical no", visor.barras(), (False, True))
c("  lo que se ve no se mueve ni cambia el tamaño de la ventana (ni lo que pide)",
  mapa(top, visor, hoja), reposo)
ancho.configure(width=20)
top.update()
top.update()
c("al menguar el contenido, la barra se quita sin moverse nada",
  (visor.barras(), mapa(top, visor, hoja)), ((False, False), reposo))
c("  y el widget sigue ahí, como el que se reutiliza al volver a desbordar",
  barras_horizontales(top) == [barra], True)
ancho.configure(width=700)
top.update()
top.update()
c("al volver a desbordar, la misma barra se pone otra vez sin moverse nada",
  (visor.barras(), visor.horizontal is barra, mapa(top, visor, hoja)),
  ((False, True), True, reposo))
top.destroy()
raiz.destroy()
sys.exit(c.report())
