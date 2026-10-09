#!/usr/bin/env python3
"""El lector de lo que se ve (`tests/_vista.py`) lee lo que debe y nada más.

Las pantallas que se actualizan en su sitio (etapa 2) se prueban comparando lo
que enseñan con lo que enseñaría una pantalla recién dibujada con el mismo
estado. Esa comparación vale lo que vale el lector: si leyera los nombres de
los widgets, dos pantallas iguales saldrían distintas; si no leyera el texto,
dos distintas saldrían iguales. Aquí se fija qué cuenta y qué no:

- cuenta lo que ve la persona: qué hay, dónde, con qué texto, estilo, estado,
  imagen y valor, en el orden en que se lee;
- no cuenta el orden en que se construyó, el nombre de los widgets, ni lo que
  el ratón, el foco o el tema (`user1`–`user3`) hayan puesto en el estado;
- un widget quitado con `grid_remove`, y todo lo que cuelga de él, no está.
"""

import sys

from _harness import Checks

c = Checks("el lector de lo que se ve")

try:
    import tkinter as tk
    from tkinter import ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

import _vista  # noqa: E402
from _vista import a_la_vista, leer_vista, visibles  # noqa: E402

top = tk.Toplevel(raiz)
top.withdraw()


def marco_nuevo(padre=None):
    """Un marco colocado, dentro de `top` o de `padre`."""
    marco = ttk.Frame(padre or top)
    marco.grid()
    return marco


# 1. qué está a la vista
cuerpo = marco_nuevo()
interior = ttk.Frame(cuerpo)
interior.grid(row=0, column=0)
etiqueta = ttk.Label(interior, text="dentro")
etiqueta.grid(row=0, column=0)
c("un widget colocado, dentro de marcos colocados, está a la vista",
  (a_la_vista(etiqueta), a_la_vista(interior), a_la_vista(cuerpo)), (True, True, True))
c("  y la ventana, que no se coloca con ninguna geometría, también", a_la_vista(top), True)
interior.grid_remove()
c("con `grid_remove`, el marco ya no está",
  (a_la_vista(interior), a_la_vista(cuerpo)), (False, True))
c("  ni lo que cuelga de él, que sigue colocado en su marco",
  (a_la_vista(etiqueta), etiqueta.winfo_manager()), (False, "grid"))
interior.grid()
c("al volver a colocarlo, vuelve todo", (a_la_vista(interior), a_la_vista(etiqueta)),
  (True, True))
suelto = ttk.Label(cuerpo, text="sin colocar")
c("uno sin colocar no está", a_la_vista(suelto), False)
# Un mismo marco no mezcla `grid` y `pack`: cada geometría, el suyo.
para_pack = marco_nuevo()
con_pack = ttk.Label(para_pack, text="pack")
con_pack.pack()
para_place = marco_nuevo()
con_place = ttk.Label(para_place, text="place")
con_place.place(x=1, y=1)
c("con `pack` o con `place` también está",
  (a_la_vista(con_pack), a_la_vista(con_place)), (True, True))
c("la ventana sigue a la vista aunque esté oculta (`withdraw`): cuenta la geometría, no el mapa",
  (a_la_vista(etiqueta), top.winfo_viewable()), (True, False))
for w in (cuerpo, para_pack, para_place):
    w.destroy()


# 2. construidas en otro orden, iguales
def tarjeta(padre, orden, imagen=None):
    """Una tarjeta con tres filas; `orden` es el orden en que se crean las piezas."""
    marco = ttk.Frame(padre)
    marco.grid()
    marco.columnconfigure(0, weight=1)

    def titulo():
        """El título, arriba."""
        ttk.Label(marco, text="Título", style="Dialogo.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w")

    def nombre():
        """Un nombre y su botón, en la fila del medio."""
        ttk.Label(marco, text="Nombre", image=imagen, compound="left").grid(
            row=1, column=0, sticky="w")
        ttk.Button(marco, text="Guardar", style="Primary.TButton").grid(
            row=1, column=1, sticky="e")

    def pie():
        """La nota de abajo."""
        ttk.Label(marco, text="nota", wraplength=120).grid(
            row=2, column=0, columnspan=2, sticky="ew")

    piezas = {"titulo": titulo, "nombre": nombre, "pie": pie}
    for clave in orden:
        piezas[clave]()
    return marco


imagen = tk.PhotoImage(master=raiz, width=4, height=4)
una = tarjeta(top, ("titulo", "nombre", "pie"), imagen)
otra = tarjeta(top, ("pie", "titulo", "nombre"), imagen)
c("la misma pantalla construida en otro orden se lee igual",
  leer_vista(una) == leer_vista(otra), True)
c("  y se lee algo: el marco, tres etiquetas y un botón", len(leer_vista(una)), 5)
c("  sin que los nombres de los widgets cuenten", str(una) != str(otra), True)

nombrada = ttk.Frame(top, name="llamada_a_mano")
nombrada.grid()
ttk.Label(nombrada, text="x", name="uno").grid(row=0, column=0)
anonima = ttk.Frame(top)
anonima.grid()
ttk.Label(anonima, text="x").grid(row=0, column=0)
c("dos árboles iguales con nombres distintos se leen igual",
  leer_vista(nombrada) == leer_vista(anonima), True)
nombrada.destroy()
anonima.destroy()
una.destroy()
otra.destroy()


# 3. lo que cambia, cambia la lectura
def con_cambio(cambia):
    """Lee una tarjeta con tres cosas, aplicando `cambia(marco, cosas)` antes."""
    marco = ttk.Frame(top)
    marco.grid()
    cosas = {"etiqueta": ttk.Label(marco, text="uno", style="Pista.TLabel", wraplength=100),
             "boton": ttk.Button(marco, text="Aceptar", style="Primary.TButton"),
             "casilla": ttk.Checkbutton(marco, text="marca")}
    cosas["etiqueta"].grid(row=0, column=0, sticky="w")
    cosas["boton"].grid(row=1, column=0, sticky="ew")
    cosas["casilla"].grid(row=2, column=0)
    cambia(marco, cosas)
    lectura = leer_vista(marco)
    marco.destroy()
    return lectura


base = con_cambio(lambda marco, cosas: None)
c("sin cambios, dos lecturas de lo mismo son iguales",
  con_cambio(lambda marco, cosas: None) == base, True)


def distinto(etiqueta: str, cambia) -> None:
    """Comprueba que el cambio hace que la lectura sea otra."""
    c(etiqueta, con_cambio(cambia) != base, True)


distinto("otro texto se lee distinto",
         lambda m, k: k["etiqueta"].configure(text="otro"))
distinto("otro estilo se lee distinto",
         lambda m, k: k["boton"].configure(style="Quiet.TButton"))
distinto("un estado de verdad (`disabled`) se lee distinto",
         lambda m, k: k["boton"].state(["disabled"]))
distinto("`readonly` también", lambda m, k: k["casilla"].state(["readonly"]))
distinto("otra celda se lee distinta",
         lambda m, k: k["etiqueta"].grid_configure(column=1))
distinto("otra fila (con el mismo orden de lectura) se lee distinta",
         lambda m, k: k["casilla"].grid_configure(row=5))
distinto("otra extensión de celda se lee distinta",
         lambda m, k: k["boton"].grid_configure(columnspan=2))
distinto("otro `sticky` se lee distinto",
         lambda m, k: k["boton"].grid_configure(sticky="w"))
distinto("otro `wraplength` se lee distinto",
         lambda m, k: k["etiqueta"].configure(wraplength=240))
distinto("otra imagen se lee distinta",
         lambda m, k: k["etiqueta"].configure(image=imagen))
distinto("un widget de más se lee distinto", lambda m, k: ttk.Label(m, text="de más").grid())
distinto("uno de menos, también", lambda m, k: k["etiqueta"].destroy())
distinto("uno quitado con `grid_remove`, también",
         lambda m, k: k["etiqueta"].grid_remove())


def con_variable(valor_texto, valor_casilla):
    """Lee una etiqueta, un campo y una casilla ligados a variables con esos valores.

    La etiqueta y la casilla de ttk ya dicen su valor por otro lado (su texto,
    el estado `selected`): el campo y la casilla clásica solo lo dicen por la
    variable, que es lo que se mide.
    """
    marco = ttk.Frame(top)
    marco.grid()
    texto = tk.StringVar(raiz, value=valor_texto)
    marca = tk.StringVar(raiz, value=valor_casilla)
    ttk.Label(marco, textvariable=texto).grid(row=0, column=0)
    ttk.Entry(marco, textvariable=texto).grid(row=1, column=0)
    tk.Checkbutton(marco, text="marca", variable=marca, onvalue="si",
                   offvalue="no").grid(row=2, column=0)
    lectura = leer_vista(marco)
    marco.destroy()
    return lectura


c("lo que dice la variable de un campo cuenta",
  con_variable("a", "si") != con_variable("b", "si"), True)
c("  y el valor de la variable de una casilla",
  con_variable("a", "si") != con_variable("a", "no"), True)
c("  mientras que los mismos valores se leen igual",
  con_variable("a", "si") == con_variable("a", "si"), True)
c("  y el campo se lee con su valor",
  [f[12] for f in con_variable("hola", "no") if f[1] == "TEntry"], ["hola"])
c("  sin que el nombre de la variable se cuele como texto (ttk abrevia `-text`)",
  [f[2] for f in con_variable("hola", "no") if f[1] == "TEntry"], [""])
sin_poner = ttk.Entry(top, textvariable="NoExiste")
sin_poner.grid()
c("una variable que no existe se lee como `None`, no falla",
  [f[12] for f in leer_vista(top) if f[1] == "TEntry"], [None])
sin_poner.destroy()

lienzo = tk.Canvas(top)
lienzo.grid()
dentro_del_lienzo = ttk.Label(lienzo, text="en el lienzo")
lienzo.create_window(0, 0, window=dentro_del_lienzo)
c("un widget metido en un `Canvas` también se lee",
  [w.cget("text") for w in visibles(top, "TLabel")], ["en el lienzo"])
lienzo.destroy()


# 4. lo que no cuenta
def sin_efecto(etiqueta: str, cambia) -> None:
    """Comprueba que el cambio no altera la lectura."""
    c(etiqueta, con_cambio(cambia) == base, True)


for estado in ("user1", "user2", "user3", "active", "focus", "hover", "pressed",
               "alternate", "background"):
    sin_efecto(f"el estado `{estado}` no cuenta",
               lambda m, k, estado=estado: k["boton"].state([estado]))
sin_efecto("`SobreFFFFFF.Primary.TButton` se lee como `Primary.TButton`",
           lambda m, k: k["boton"].configure(style="SobreFFFFFF.Primary.TButton"))
sin_efecto("  con cualquier color", lambda m, k: k["boton"].configure(
    style="Sobre1A2B3C.Primary.TButton"))
sin_efecto("`padx` y `pady` no cuentan",
           lambda m, k: k["boton"].grid_configure(padx=9, pady=3))
sin_efecto("construir en otro orden y luego recolocar tampoco",
           lambda m, k: (k["casilla"].grid_forget(), k["casilla"].grid(row=2, column=0)))

lectura_boton = [f for f in base if f[1] == "TButton"][0]
c("el estilo se lee sin el prefijo `Sobre…`: `Primary.TButton`",
  lectura_boton[3], "Primary.TButton")
con_sobre = con_cambio(lambda m, k: k["boton"].configure(style="SobreFFFFFF.Primary.TButton"))
c("  también con el prefijo puesto", [f for f in con_sobre if f[1] == "TButton"][0][3],
  "Primary.TButton")
c("los estados que sí cuentan se leen ordenados, sin los ignorados",
  [f for f in con_cambio(lambda m, k: k["boton"].state(["pressed", "disabled", "user2"]))
   if f[1] == "TButton"][0][4], ("disabled",))


# 5. el orden en que se lee
def orden_de_lectura(lectura) -> list:
    """Los textos de la lectura, en el orden en que salen."""
    return [fila[2] for fila in lectura if fila[2]]


marco = ttk.Frame(top)
marco.grid()
for texto, fila, columna in (("d", 1, 1), ("b", 0, 1), ("c", 1, 0), ("a", 0, 0)):
    ttk.Label(marco, text=texto).grid(row=fila, column=columna)
c("con `grid`, se lee por (fila, columna), no por orden de creación",
  orden_de_lectura(leer_vista(marco)), ["a", "b", "c", "d"])
c("  y lo mismo dice `visibles()`",
  [w.cget("text") for w in visibles(marco, "TLabel")], ["a", "b", "c", "d"])
marco.destroy()

# Varias piezas en la misma celda (la fila de una lista: el fondo y su casilla
# comparten celda): el desempate no puede depender de cuál se creó primero.
def celda_compartida(orden):
    """Lee un marco con dos etiquetas en la misma celda, creadas en `orden`."""
    m = ttk.Frame(top)
    m.grid()
    for texto in orden:
        ttk.Label(m, text=texto).grid(row=0, column=0)
    lectura = leer_vista(m)
    m.destroy()
    return lectura


c("dos widgets en la misma celda se leen igual sea cual sea el orden de creación",
  celda_compartida(("fondo", "casilla")) == celda_compartida(("casilla", "fondo")), True)

marco = ttk.Frame(top)
marco.grid()
for texto in ("tercero", "primero", "segundo"):
    ttk.Label(marco, text=texto).pack()
primero = leer_vista(marco)
marco.destroy()
marco = ttk.Frame(top)
marco.grid()
for texto in ("primero", "segundo", "tercero"):
    ttk.Label(marco, text=texto).pack()
segundo = leer_vista(marco)
marco.destroy()
c("con `pack`, el orden de empaquetado es el de lectura",
  orden_de_lectura(primero), ["tercero", "primero", "segundo"])
c("  y dos órdenes de empaquetado distintos se leen distintos", primero != segundo, True)

marco = ttk.Frame(top)
marco.grid()
ttk.Label(marco, text="abajo").place(x=0, y=40)
ttk.Label(marco, text="arriba").place(x=0, y=0)
c("con `place`, por posición y no por orden de creación",
  orden_de_lectura(leer_vista(marco)), ["arriba", "abajo"])
marco.destroy()


# 6. profundidad, raíz y ventanas hijas
marco = ttk.Frame(top)
marco.grid()
dentro = ttk.Frame(marco)
dentro.grid()
ttk.Label(dentro, text="hondo").grid()
lectura = leer_vista(marco)
c("la profundidad es la del árbol: el marco 0, su marco 1, la etiqueta 2",
  [fila[0] for fila in lectura], [0, 1, 2])
c("  y se lee depth-first", [fila[1] for fila in lectura], ["TFrame", "TFrame", "TLabel"])
hija = tk.Toplevel(top)
hija.withdraw()
ttk.Label(hija, text="de otra ventana").grid()
c("una ventana hija no es parte de lo que se lee",
  [w.cget("text") for w in visibles(top, "TLabel")], ["hondo"])
c("  y leer la ventana hija es leer la hija",
  orden_de_lectura(leer_vista(hija)), ["de otra ventana"])
hija.destroy()
dentro.grid_remove()
c("`leer_vista` de un widget que no está a la vista no lee nada", leer_vista(dentro), [])
c("  y `visibles` tampoco", visibles(dentro), [])
c("  y los marcos escondidos dejan fuera lo suyo", [f[1] for f in leer_vista(top)
                                                      if f[2] == "hondo"], [])
marco.destroy()


# 7. `visibles` filtra
marco = ttk.Frame(top)
marco.grid()
ttk.Label(marco, text="uno").grid(row=0, column=0)
ttk.Button(marco, text="uno").grid(row=0, column=1)
ttk.Button(marco, text="dos").grid(row=1, column=0)
escondido = ttk.Button(marco, text="dos")
escondido.grid(row=1, column=1)
escondido.grid_remove()
c("`visibles` sin filtros da todo lo que hay a la vista, sin la raíz",
  [(w.winfo_class(), w.cget("text")) for w in visibles(marco)],
  [("TLabel", "uno"), ("TButton", "uno"), ("TButton", "dos")])
c("  filtrado por clase", [w.cget("text") for w in visibles(marco, "TButton")],
  ["uno", "dos"])
c("  por texto", [w.winfo_class() for w in visibles(marco, texto="uno")],
  ["TLabel", "TButton"])
c("  por las dos cosas", len(visibles(marco, "TButton", "dos")), 1)
c("  y sin coincidencias, vacío", visibles(marco, "TButton", "tres"), [])
c("el escondido no sale aunque coincida", escondido in visibles(marco, "TButton", "dos"), False)
marco.destroy()

c("el módulo declara los estados que no cuentan",
  sorted(_vista.ESTADOS_IGNORADOS),
  sorted(["active", "focus", "hover", "pressed", "alternate", "background",
          "user1", "user2", "user3"]))

sys.exit(c.report())
