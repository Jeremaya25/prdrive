#!/usr/bin/env python3
"""«Servidor»: la barra de direcciones, como la del Explorador (`ui/tk_direcciones.py`).

Solo dibuja; qué se hace al pulsar lo decide quien la usa (las acciones que le da).
Se monta de verdad en una ventana enseñada y se comprueba que:
- lleva atrás, adelante, arriba y releer como botones de icono solo, y `encender()`
  los enciende y apaga;
- las migas son las de la ruta (el remote primero) y, en un hueco estrecho, las
  primeras de en medio se recogen en «…» sin perder la primera ni la última;
- pulsar una miga pide su ruta; pulsar «…» enseña un menú con las recogidas; el
  icono del servidor enseña un menú con todos los servidores, el que se ve marcado;
- un clic en el hueco la pasa a modo texto con la ruta seleccionada entera; Intro
  dice lo escrito y vuelve a las migas; Escape vuelve sin decir nada;
- el campo de búsqueda lleva la pista «Buscar en ‹carpeta›», avisa de lo que se
  escribe, de Intro y de Escape, y `poner_busqueda()` no avisa;
- ningún valor de color ni distancia suelta en el módulo.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from _harness import Checks

c = Checks("«Servidor»: la barra de direcciones")

try:
    import tkinter as tk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from ui import servidor, theme, tk_direcciones  # noqa: E402

theme.apply(raiz)
errores: list[str] = []
raiz.report_callback_exception = (
    lambda tipo, valor, _tb: errores.append(f"{tipo.__name__}: {valor}"))

llamadas: list[tuple] = []
menus: list = []


def apuntar(nombre):
    return lambda *a: llamadas.append((nombre, *a))


ACCIONES = {k: apuntar(k) for k in ("atras", "adelante", "arriba", "releer", "ir", "servidor",
                                    "escrita", "buscar", "buscar_ya", "vaciar")}


def estado(b) -> str:
    return "disabled" if b.instate(["disabled"]) else "normal"


def pasar(w) -> None:
    for _ in range(3):
        w.update()


def tecla(campo, secuencia: str) -> None:
    """Pulsa una tecla con el foco en ese campo (sin el foco, Tk no se la da)."""
    campo.focus_force()
    campo.update()
    campo.event_generate(secuencia)
    campo.update()


try:
    ventana = tk.Toplevel(raiz)
    theme.apply(ventana)
    ventana.columnconfigure(0, weight=1)
    barra = tk_direcciones.Direcciones(ventana, ACCIONES,
                                       mostrar_menu=lambda m, x, y: menus.append((m, x, y)))
    barra.marco.grid(row=0, column=0, sticky="ew")
    ventana.geometry("900x80")
    ventana.deiconify()
    barra.poner("nas", "/d/CargaDatos/plantillas", ["nas", "otro"])
    pasar(ventana)

    # --- los botones de navegación
    botones = (barra.atras, barra.adelante, barra.arriba, barra.releer)
    c("cuatro botones de icono: atrás, adelante, arriba y releer",
      [str(b.cget("text")) for b in botones], ["Atrás", "Adelante", "Arriba", "Releer"])
    c("  discretos", {str(b.cget("style")) for b in botones}, {"Quiet.TButton"})
    if all(str(b.cget("image")) for b in botones):
        c("  que enseñan solo el icono", {str(b.cget("compound")) for b in botones}, {"image"})
    else:
        print("  (saltado) solo icono: los iconos no se pintan aquí")
    barra.encender(atras=False, adelante=True, arriba=True, releer=False, servidor=True,
                   buscar=True)
    c("encender() enciende y apaga cada uno", [estado(b) for b in botones],
      ["disabled", "normal", "normal", "disabled"])
    for b in botones:
        b.state(["!disabled"])
        b.invoke()
    c("  y cada uno avisa a su acción", [n for n, *_ in llamadas],
      ["atras", "adelante", "arriba", "releer"])

    # --- las migas
    c("las migas son las de la ruta, con el remote primero",
      barra.tramos(), [("nas", "/"), ("d", "/d"), ("CargaDatos", "/d/CargaDatos"),
                       ("plantillas", "/d/CargaDatos/plantillas")])
    c("  y la barra sabe qué enseña", (barra.remote, barra.ruta),
      ("nas", "/d/CargaDatos/plantillas"))
    llamadas.clear()
    barra.pulsar(1)
    c("pulsar una miga pide su ruta", llamadas, [("ir", "/d")])

    # estrecha: se recoge en «…»
    ventana.geometry("640x80")
    barra.poner("nas", "/una carpeta larga/otra carpeta larga/la tercera/y la última", ["nas"])
    pasar(ventana)
    vistas = barra.tramos()
    c("en un hueco estrecho, las primeras de en medio van a «…»",
      (vistas[0], vistas[1][0], vistas[-1]),
      (("nas", "/"), "…", ("y la última", "/una carpeta larga/otra carpeta larga/la tercera/y la última")))
    c("  y lo que queda no se sale del lienzo",
      barra.lienzo.bbox("all")[2] <= barra.lienzo.winfo_width(), True)
    menus.clear()
    barra.pulsar(1)
    menu = menus[-1][0]
    recogidas = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)]
    c("pulsar «…» enseña las recogidas, de la raíz hacia dentro",
      recogidas[0], "una carpeta larga")
    llamadas.clear()
    menu.invoke(0)
    c("  y elegir una pide su ruta", llamadas, [("ir", "/una carpeta larga")])
    ventana.geometry("1400x80")
    pasar(ventana)
    c("al ensanchar, vuelven todas", [t for t, _r in barra.tramos()],
      ["nas", "una carpeta larga", "otra carpeta larga", "la tercera", "y la última"])

    # --- el menú de servidores
    barra.poner("nas", "/d", ["nas", "otro"])
    pasar(ventana)
    menus.clear()
    barra.pulsar_servidor()
    menu = menus[-1][0]
    c("el icono del servidor enseña todos los servidores",
      [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)], ["nas", "otro"])
    c("  con el que se ve marcado",
      [(menu.type(i), str(menu.entrycget(i, "value"))) for i in range(2)]
      + [str(barra.lienzo.getvar(str(menu.entrycget(0, "variable"))))],
      [("radiobutton", "nas"), ("radiobutton", "otro"), "nas"])
    llamadas.clear()
    menu.invoke(1)
    c("  y elegir otro avisa", llamadas, [("servidor", "otro")])
    for _ in range(5):
        barra.pulsar_servidor()
        barra.menu_recogidas()
    c("abrir los menús muchas veces deja uno vivo de cada (Windows tiene un tope de menús)",
      sum(1 for w in barra.lienzo.winfo_children() if w.winfo_class() == "Menu"), 2)
    barra.encender(atras=True, adelante=True, arriba=True, releer=True, servidor=False,
                   buscar=True)
    menus.clear()
    barra.pulsar_servidor()
    c("con el servidor apagado no sale el menú", menus, [])
    barra.encender(atras=True, adelante=True, arriba=True, releer=True, servidor=True,
                   buscar=True)

    # --- escribir la ruta
    barra.editar()
    pasar(ventana)
    try:
        seleccion = (barra.campo.index("sel.first"), barra.campo.index("sel.last"))
    except tk.TclError:
        seleccion = None
    c("editar() cambia las migas por un campo con la ruta, seleccionada entera",
      (barra.editando, bool(barra.lienzo.winfo_manager()), bool(barra.campo.winfo_manager()),
       barra.campo.get(), seleccion), (True, False, True, "/d", (0, 2)))
    barra.campo.delete(0, "end")
    barra.campo.insert(0, "datos\\notas")
    llamadas.clear()
    tecla(barra.campo, "<Return>")
    pasar(ventana)
    c("Intro dice lo escrito y vuelve a las migas",
      (llamadas, barra.editando, bool(barra.lienzo.winfo_manager())),
      ([("escrita", "datos\\notas")], False, True))
    barra.editar()
    pasar(ventana)
    llamadas.clear()
    tecla(barra.campo, "<Escape>")
    pasar(ventana)
    c("Escape vuelve sin decir nada", (llamadas, barra.editando), ([], False))
    llamadas.clear()
    x = barra.lienzo.winfo_width() - 10
    barra.lienzo.event_generate("<Button-1>", x=x, y=5)
    pasar(ventana)
    c("un clic en el hueco de las migas pasa a escribir", barra.editando, True)
    tecla(barra.campo, "<Escape>")
    pasar(ventana)

    # --- la búsqueda
    barra.poner("nas", "/d/CargaDatos/plantillas", ["nas"])
    pista = barra.pista()
    c("la búsqueda lleva la pista «Buscar en ‹carpeta›»", pista, "Buscar en plantillas")
    barra.poner("nas", "/", ["nas"])
    c("  en la raíz, el nombre del servidor", barra.pista(), "Buscar en nas")
    llamadas.clear()
    barra.busqueda.insert("end", "f")
    barra.busqueda.insert("end", "o")
    pasar(ventana)
    tecla(barra.busqueda, "<Return>")
    tecla(barra.busqueda, "<Escape>")
    pasar(ventana)
    c("escribir, Intro y Escape avisan a su acción",
      [n for n, *_ in llamadas], ["buscar", "buscar", "buscar_ya", "vaciar"])
    c("  con el texto de cada momento", [a for _n, *a in llamadas],
      [["f"], ["fo"], ["fo"], []])
    llamadas.clear()
    barra.poner_busqueda("otra cosa")
    c("poner_busqueda() cambia el texto sin avisar", (barra.texto_busqueda.get(), llamadas),
      ("otra cosa", []))
    barra.encender(atras=True, adelante=True, arriba=True, releer=True, servidor=True,
                   buscar=False)
    c("con la búsqueda apagada el campo no se puede usar", estado(barra.busqueda), "disabled")

    ventana.destroy()

    # --- nada de colores ni distancias sueltas
    fuente = Path(tk_direcciones.__file__).read_text(encoding="utf-8")
    c("el módulo no escribe ningún color", re.findall(r"#[0-9a-fA-F]{3,8}\b", fuente), [])
    c("ni deja una distancia suelta (padding/pady/padx/wraplength con un número distinto de 0)",
      re.findall(r"(?:pad[xy]?|wraplength)\s*=\s*\(?\s*[1-9]", fuente), [])
    c("  y las migas son las de `servidor.migas`", servidor.migas("nas", "/d")[1], ("d", "/d"))
    c("ningún error de Tk", errores, [])
finally:
    raiz.destroy()

sys.exit(c.report())
