#!/usr/bin/env python3
"""«Servidor»: el diálogo de nombre, la barra de gestión y el menú contextual (`ui/tk_gestion.py`).

Solo dibujan; qué vale como nombre lo decide quien llama (`validar`). Se monta de
verdad y el diálogo se maneja con callbacks de `after()`, que corren dentro de su
`wait_window()`. Se comprueba que:
- `pedir_nombre` abre con el título, el texto inicial y los botones dichos; con el
  inicial vacío no dice nada y «Aceptar» está apagado hasta que algo vale;
- con un inicial que vale, «Aceptar» está encendido; el motivo que da `validar`
  sale bajo el campo y apaga «Aceptar», y entonces Intro no hace nada;
- arreglado el nombre, Intro y «Aceptar» devuelven el texto tal cual se escribió
  (sin recortar); Escape, «Cancelar» y la X devuelven `None`;
- con `es_archivo`, la selección cubre el nombre hasta el último punto (salvo que
  el punto sea el primer carácter); sin él, todo el texto;
- `Barra` lleva sus cuatro botones con su rótulo (`Quiet.TButton`), avisa de cada
  pulsación a su acción y `encender()` los enciende y apaga;
- `menu_contextual` es un `Menu` sin asa con sus cinco entradas, las apagadas por
  su estado, y cada una llama a su acción;
- ningún valor de color ni distancia suelta en el módulo.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from _harness import Checks

c = Checks("«Servidor»: el diálogo de nombre y la barra de gestión")

try:
    import tkinter as tk
    from tkinter import ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from ui import theme, tk_gestion  # noqa: E402

theme.apply(raiz)
errores: list[str] = []
raiz.report_callback_exception = (
    lambda tipo, valor, _tb: errores.append(f"{tipo.__name__}: {valor}"))


def hijos(w):
    """Recorre los widgets que cuelgan de `w`, en profundidad."""
    for hijo in w.winfo_children():
        yield hijo
        yield from hijos(hijo)


def boton(w, texto):
    """El `ttk.Button` con ese rótulo."""
    return next(b for b in hijos(w) if b.winfo_class() == "TButton"
                and str(b.cget("text")) == texto)


def estado(b) -> str:
    """`"normal"` o `"disabled"` de un botón ttk."""
    return "disabled" if b.instate(["disabled"]) else "normal"


def escribir(dlg, texto: str) -> None:
    """Escribe en el campo como lo haría quien teclea (cambia lo que hay)."""
    dlg.entrada.delete(0, "end")
    dlg.entrada.insert(0, texto)
    dlg.update()


def tecla(dlg, nombre: str) -> None:
    """Pulsa una tecla con el foco en el campo."""
    dlg.update()
    dlg.entrada.focus_force()
    dlg.update()
    dlg.entrada.event_generate(nombre)
    dlg.update()


def conducir(accion):
    """Hace `accion(dlg)` con el diálogo ya a la vista, en vez de esperar a que se cierre.

    Corre el `mostrar()` de verdad (centrar, enseñar, captura) y sustituye solo su
    `wait_window()`, como `test_tk_flags_guia`: así lo que se mira es lo que ve la
    persona al abrirse, también el foco en Windows, y no hay carrera con un
    temporizador (el `update()` de `ensenar()` lo dejaría correr antes de esperar).
    """
    def esperar(dlg, *_a, **_k):
        dlg.update()
        accion(dlg)
        if dlg.winfo_exists():
            dlg.destroy()
    tk.Toplevel.wait_window = esperar


def vale(texto: str) -> str | None:
    """Un `validar` de prueba: vacío, con «/» y «Ya» existente."""
    if not texto:
        return "Escribe un nombre."
    if "/" in texto:
        return "Un nombre no puede llevar «/»."
    if texto == "existe":
        return "Ya hay algo que se llama «existe» en esta carpeta."
    return None


try:
    # --- el diálogo: carpeta nueva (inicial vacío)
    visto: dict = {}

    def nueva(d):
        visto["titulo"] = d.title()
        visto["botones"] = sorted(str(b.cget("text")) for b in hijos(d)
                                  if b.winfo_class() == "TButton")
        visto["fondo"] = d.cget("background")
        visto["campo"] = d.entrada.winfo_class()
        visto["texto0"] = d.entrada.get()
        visto["motivo0"] = str(d.motivo.cget("text"))
        visto["estilo_motivo"] = str(d.motivo.cget("style"))
        visto["aceptar0"] = estado(d.aceptar)
        escribir(d, "a/b")
        visto["motivo1"] = str(d.motivo.cget("text"))
        visto["aceptar1"] = estado(d.aceptar)
        tecla(d, "<Return>")
        visto["sigue_tras_intro"] = d.winfo_exists()
        d.aceptar.invoke()
        visto["sigue_tras_boton"] = d.winfo_exists()
        escribir(d, "")
        visto["motivo_vacio"] = str(d.motivo.cget("text"))
        escribir(d, "existe")
        visto["motivo_existe"] = str(d.motivo.cget("text"))
        escribir(d, "  Fotos 2 ")
        visto["motivo2"] = str(d.motivo.cget("text"))
        visto["aceptar2"] = estado(d.aceptar)
        tecla(d, "<Return>")

    conducir(nueva)
    r = tk_gestion.pedir_nombre(raiz, "Nueva carpeta", "", vale)
    c("Intro con un nombre que vale devuelve el texto tal cual (sin recortar)", r, "  Fotos 2 ")
    c("  título y botones dichos", (visto["titulo"], visto["botones"]),
      ("prdrive — Nueva carpeta", ["Aceptar", "Cancelar"]))
    c("  el fondo es el del tema", visto["fondo"], theme.PAPEL)
    c("  un solo campo `ttk.Entry`, vacío", (visto["campo"], visto["texto0"]), ("TEntry", ""))
    c("  el motivo va en una etiqueta de pista", visto["estilo_motivo"], "Pista.TLabel")
    c("  sin escribir, no dice nada y «Aceptar» está apagado",
      (visto["motivo0"], visto["aceptar0"]), ("", "disabled"))
    c("  «a/b» da su motivo y apaga «Aceptar»",
      (visto["motivo1"], visto["aceptar1"]),
      ("Un nombre no puede llevar «/».", "disabled"))
    c("  con «Aceptar» apagado, Intro y el botón no cierran",
      (visto["sigue_tras_intro"], visto["sigue_tras_boton"]), (True, True))
    c("  borrar lo escrito vuelve a pedir un nombre", visto["motivo_vacio"], "Escribe un nombre.")
    c("  un nombre que ya hay lo dice", visto["motivo_existe"],
      "Ya hay algo que se llama «existe» en esta carpeta.")
    c("  arreglado, el motivo se va y «Aceptar» se enciende",
      (visto["motivo2"], visto["aceptar2"]), ("", "normal"))

    # --- «Aceptar» con el ratón, Cancelar, Escape y la X
    conducir(lambda d: (escribir(d, "datos"), d.aceptar.invoke()))
    c("«Aceptar» devuelve el texto", tk_gestion.pedir_nombre(raiz, "Nueva carpeta", "", vale),
      "datos")
    conducir(lambda d: (escribir(d, "datos"), d.cancelar.invoke()))
    c("«Cancelar» devuelve None", tk_gestion.pedir_nombre(raiz, "Nueva carpeta", "", vale), None)
    conducir(lambda d: d.destroy())
    c("cerrar con la X devuelve None",
      tk_gestion.pedir_nombre(raiz, "Nueva carpeta", "", vale), None)

    def con_escape(d):
        escribir(d, "datos")
        tecla(d, "<Escape>")
        if d.winfo_exists():
            visto["escape_no_cerro"] = True
    visto.pop("escape_no_cerro", None)
    conducir(con_escape)
    r = tk_gestion.pedir_nombre(raiz, "Nueva carpeta", "", vale)
    if visto.get("escape_no_cerro"):
        print("  (saltado) Escape: este escritorio no da el foco a una ventana nueva")
    else:
        c("Escape devuelve None", r, None)

    # --- el foco al abrir. Va después de Escape, como en `test_tk_transferencia`: en
    # Windows una aplicación que aún no ha tenido el foco del escritorio no apunta el de
    # sus ventanas, y `tecla()` (con `focus_force`) es lo que se lo ha dado. Al abrirlo de
    # verdad, la aplicación ya lo tiene: se ha pulsado un botón de su ventana.
    def foco(d):
        d.deiconify()
        d.update()
        # `-lastfor`: dónde queda el foco del diálogo aunque el escritorio no se lo dé
        visto["foco"] = str(d.tk.call("focus", "-lastfor", str(d)))
        visto["entrada"] = str(d.entrada)
    conducir(foco)
    tk_gestion.pedir_nombre(raiz, "Nueva carpeta", "", vale)
    c("el foco inicial está en el campo", visto["foco"], visto["entrada"])

    # --- renombrar: el inicial cuenta
    def renombrar(d):
        visto["titulo_r"] = d.title()
        visto["texto_r"] = d.entrada.get()
        visto["aceptar_r"] = estado(d.aceptar)
        visto["motivo_r"] = str(d.motivo.cget("text"))
        d.aceptar.invoke()

    conducir(renombrar)
    r = tk_gestion.pedir_nombre(raiz, "Renombrar", "foto.jpg", vale)
    c("renombrar: con un inicial que vale, «Aceptar» está encendido y lo devuelve",
      (visto["titulo_r"], visto["texto_r"], visto["aceptar_r"], visto["motivo_r"], r),
      ("prdrive — Renombrar", "foto.jpg", "normal", "", "foto.jpg"))

    def inicial_malo(d):
        visto["aceptar_m"] = estado(d.aceptar)
        visto["motivo_m"] = str(d.motivo.cget("text"))
    conducir(inicial_malo)
    tk_gestion.pedir_nombre(raiz, "Renombrar", "a/b", vale)
    c("  un inicial que no vale apaga «Aceptar» y dice por qué",
      (visto["aceptar_m"], visto["motivo_m"]), ("disabled", "Un nombre no puede llevar «/»."))

    # --- la selección
    def seleccion(inicial: str, es_archivo: bool):
        """(texto seleccionado) del campo recién abierto."""
        def mira(d):
            try:
                visto["sel"] = (d.entrada.index("sel.first"), d.entrada.index("sel.last"))
            except tk.TclError:
                visto["sel"] = None
        visto.pop("sel", None)
        conducir(mira)
        tk_gestion.pedir_nombre(raiz, "Renombrar", inicial, lambda _t: None,
                                es_archivo=es_archivo)
        return visto["sel"]

    c("es_archivo: «foto.jpg» selecciona «foto»", seleccion("foto.jpg", True), (0, 4))
    c("  «.bashrc» lo selecciona entero", seleccion(".bashrc", True), (0, 7))
    c("  «a.tar.gz» llega al último punto", seleccion("a.tar.gz", True), (0, 5))
    c("  «carpeta» (sin punto) lo selecciona entero", seleccion("carpeta", True), (0, 7))
    c("  sin es_archivo, «foto.jpg» entero", seleccion("foto.jpg", False), (0, 8))

    # --- la barra
    llamadas: list[str] = []
    acciones = {k: (lambda k=k: llamadas.append(k))
                for k in ("nueva", "renombrar", "cortar", "borrar")}
    barra = tk_gestion.Barra(raiz, acciones)
    rotulos = {"nueva": "Nueva carpeta…", "renombrar": "Renombrar…", "cortar": "Cortar",
               "borrar": "Borrar…"}
    c("la barra tiene sus cuatro botones con su rótulo",
      {k: str(getattr(barra, k).cget("text")) for k in rotulos}, rotulos)
    c("  con el estilo discreto",
      {str(getattr(barra, k).cget("style")) for k in rotulos}, {"Quiet.TButton"})
    c("  cuelgan del marco", {getattr(barra, k).master is barra.marco for k in rotulos}, {True})
    barra.encender(True, False, True, False)
    c("encender(True, False, True, False)",
      {k: estado(getattr(barra, k)) for k in rotulos},
      {"nueva": "normal", "renombrar": "disabled", "cortar": "normal", "borrar": "disabled"})
    barra.encender(False, True, False, True)
    c("encender(False, True, False, True)",
      {k: estado(getattr(barra, k)) for k in rotulos},
      {"nueva": "disabled", "renombrar": "normal", "cortar": "disabled", "borrar": "normal"})
    barra.encender(True, True, True, True)
    for k in rotulos:
        getattr(barra, k).invoke()
    c("cada botón llama a su acción", llamadas, ["nueva", "renombrar", "cortar", "borrar"])

    # --- el menú contextual
    llamadas.clear()
    acciones_menu = {k: (lambda k=k: llamadas.append(k))
                     for k in ("nueva", "renombrar", "cortar", "pegar", "borrar")}
    estados = {"nueva": True, "renombrar": False, "cortar": True, "pegar": False,
               "borrar": True}
    menu = tk_gestion.menu_contextual(raiz, acciones_menu, estados)
    c("el menú es un `Menu` sin asa", (isinstance(menu, tk.Menu), str(menu.cget("tearoff"))),
      (True, "0"))
    ultimo = menu.index("end")
    entradas = [(menu.entrycget(i, "label"), str(menu.entrycget(i, "state")))
                for i in range(ultimo + 1) if menu.type(i) == "command"]
    c("  entradas en orden, las de estado falso apagadas", entradas,
      [("Nueva carpeta…", "normal"), ("Renombrar…", "disabled"), ("Cortar", "normal"),
       ("Pegar aquí", "disabled"), ("Borrar…", "normal")])
    for i in range(ultimo + 1):
        if menu.type(i) == "command" and menu.entrycget(i, "state") == "normal":
            menu.invoke(i)
    c("  las encendidas llaman a su acción", llamadas, ["nueva", "cortar", "borrar"])

    # --- nada de colores ni distancias sueltas
    fuente = Path(tk_gestion.__file__).read_text(encoding="utf-8")
    c("el módulo no escribe ningún color", re.findall(r"#[0-9a-fA-F]{3,8}\b", fuente), [])
    c("ni deja una distancia suelta (padding/pady/padx/wraplength con un número distinto de 0)",
      re.findall(r"(?:pad[xy]?|wraplength)\s*=\s*\(?\s*[1-9]", fuente), [])
    c("ningún error de Tk", errores, [])
finally:
    raiz.destroy()

sys.exit(c.report())
