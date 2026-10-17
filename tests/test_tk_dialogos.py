#!/usr/bin/env python3
"""Los diálogos con el tema de la ventana principal (`ui.tk.preguntar()` y `ui.tk.avisar()`).

Sustituyen a los `messagebox` del sistema, que con Windows en oscuro salían claros
sobre la ventana oscura. Se montan de verdad (`modal()`, `cuerpo_visible()`) y
`mostrar()` se cambia por quien pulsa, en vez de esperar. Se comprueba que:
- Llevan el tema: título de la barra, primera línea, texto y botones con los
  estilos de prdrive, y el fondo del papel.
- `preguntar()` devuelve `True` con el botón principal y con Intro, y `False`
  con «Cancelar», con Escape y cerrando la ventana.
- Intro (y el Intro del teclado numérico) pulsa el botón que tiene el foco: con
  el foco en «Cancelar» o en «No» (a lo que se llega con Tab) cancela, y con el
  foco en el principal acepta.
- `avisar()` dice el texto en un aviso del tono pedido y se cierra con «Aceptar».
- Cuelga de su padre salvo que el padre no se enseñe (la raíz oculta).
- `preguntar_resync()` y las dos preguntas del llavero pasan por ellos.
- Nada del sistema: en `ui/tk.py` el único `messagebox` que queda es el de
  `TkFrontend.info()`, que sale sin ventana principal.
"""

import ast
import sys
from pathlib import Path

from _harness import REPO, Checks

c = Checks("diálogos del tema (preguntar y avisar)")

try:
    import tkinter as tk
    from tkinter import messagebox
    from ui import theme
    theme.nitidez()
    raiz = tk.Tk()
    raiz.withdraw()
    theme.apply(raiz)
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from ui import llavero_editor, tk_llavero  # noqa: E402
from ui import tk as uitk  # noqa: E402


def del_sistema(*_a, **_k):
    """Lo que no debe llamarse: un cuadro del sistema."""
    raise AssertionError("se ha abierto un cuadro del sistema")


for nombre in ("askokcancel", "askyesno", "showinfo", "showerror", "showwarning"):
    setattr(messagebox, nombre, del_sistema)


def hijos(w):
    """Recorre los widgets que cuelgan de `w`, en profundidad."""
    for hijo in w.winfo_children():
        yield hijo
        yield from hijos(hijo)


def boton(dlg, texto):
    """Devuelve el botón con ese texto."""
    return next(w for w in hijos(dlg) if w.winfo_class() == "TButton"
                and str(w.cget("text")) == texto)


def etiquetas(dlg):
    """Devuelve los textos de las etiquetas del diálogo."""
    return [str(w.cget("text")) for w in hijos(dlg) if w.winfo_class() == "TLabel"
            and str(w.cget("text"))]


real_mostrar = uitk.mostrar
vistos: dict = {}


def conducir(accion):
    """Sustituye `mostrar()` por quien mira el diálogo, hace `accion(dlg)` y lo cierra."""
    def mostrar(dlg, parent=None):
        """Apunta cómo es el diálogo, pulsa lo que toque y lo deja cerrado."""
        vistos.update(titulo=dlg.title(), etiquetas=etiquetas(dlg), fondo=str(dlg["background"]),
                      transitorio=str(dlg.wm_transient()),
                      botones=[str(w.cget("text")) for w in hijos(dlg)
                               if w.winfo_class() == "TButton"],
                      estilos={(w.winfo_class(), str(w.cget("text"))): str(w.cget("style"))
                               for w in hijos(dlg)
                               if w.winfo_class() in ("TButton", "TLabel") and str(w.cget("text"))})
        accion(dlg)
        try:
            dlg.destroy()
        except tk.TclError:
            pass
    uitk.mostrar = mostrar


def con_teclado(tecla, foco=None):
    """Devuelve una acción que manda esa tecla al diálogo, ya enseñado y con el foco.

    Con `foco`, antes de mandarla se lleva el foco al botón con ese texto (a lo
    que llega Tab); sin él, queda donde lo dejó el diálogo al abrirse.
    """
    def accion(dlg):
        dlg.deiconify()
        dlg.update()
        dlg.focus_force()
        dlg.update()
        if foco is not None and str(dlg.focus_get()).startswith(str(dlg)):
            destino = boton(dlg, foco)
            destino.focus_set()
            dlg.update()
            if dlg.focus_get() is not destino:
                vistos["sin_foco"] = True
                return
        if str(dlg.focus_get()).startswith(str(dlg)):
            dlg.event_generate(tecla)
            dlg.update()
        else:
            vistos["sin_foco"] = True
    return accion


def con_tecla_en(tecla, foco, *pregunta):
    """Pregunta con `preguntar()` mandando la tecla con el foco en `foco`; `None` si no hay foco."""
    vistos.pop("sin_foco", None)
    conducir(con_teclado(tecla, foco))
    r = uitk.preguntar(raiz, *pregunta)
    if vistos.pop("sin_foco", False):
        print(f"  (saltado) {tecla} con el foco en «{foco}»: "
              "este escritorio no da el foco a una ventana nueva")
        return None
    return r


try:
    # --- preguntar()
    conducir(lambda dlg: boton(dlg, "Expulsar").invoke())
    r = uitk.preguntar(raiz, "Expulsar", "Se cierra la ventana.\n¿Seguro?", "Expulsar")
    c("preguntar() devuelve True con el botón principal", r, True)
    c("  la barra lleva el título", vistos["titulo"], "prdrive — Expulsar")
    c("  y la primera línea y el texto, en el diálogo",
      vistos["etiquetas"], ["Expulsar", "Se cierra la ventana.\n¿Seguro?"])
    c("  con «Cancelar» y el botón dicho", sorted(vistos["botones"]), ["Cancelar", "Expulsar"])
    c("  con los estilos del tema: el título, el botón principal y el otro",
      (vistos["estilos"][("TLabel", "Expulsar")], vistos["estilos"][("TButton", "Expulsar")],
       vistos["estilos"][("TButton", "Cancelar")]), ("Dialogo.TLabel", "Primary.TButton", ""))
    c("  y el fondo es el del papel, no el del sistema", vistos["fondo"], theme.PAPEL)

    conducir(lambda dlg: boton(dlg, "Cancelar").invoke())
    c("«Cancelar» devuelve False", uitk.preguntar(raiz, "Expulsar", "¿Seguro?", "Expulsar"), False)
    conducir(lambda dlg: dlg.destroy())
    c("cerrar la ventana devuelve False", uitk.preguntar(raiz, "Expulsar", "¿Seguro?"), False)
    conducir(lambda dlg: boton(dlg, "Sí").invoke())
    c("con otros rótulos (el del resync), los suyos",
      (uitk.preguntar(raiz, "Resync", "¿Ahora?", "Sí", "No"), sorted(vistos["botones"])),
      (True, ["No", "Sí"]))

    vistos.pop("sin_foco", None)
    conducir(con_teclado("<Return>"))
    r = uitk.preguntar(raiz, "Expulsar", "¿Seguro?")
    if vistos.pop("sin_foco", False):
        print("  (saltado) Intro: este escritorio no da el foco a una ventana nueva")
    else:
        c("Intro acepta", r, True)
    conducir(con_teclado("<Escape>"))
    r = uitk.preguntar(raiz, "Expulsar", "¿Seguro?")
    if vistos.pop("sin_foco", False):
        print("  (saltado) Escape: este escritorio no da el foco a una ventana nueva")
    else:
        c("Escape cancela", r, False)

    # Intro pulsa el botón que tiene el foco, no siempre el principal.
    for tecla in ("<Return>", "<KP_Enter>"):
        r = con_tecla_en(tecla, "Aceptar", "Expulsar", "¿Seguro?")
        if r is not None:
            c(f"{tecla} con el foco en el principal acepta", r, True)
        r = con_tecla_en(tecla, "Cancelar", "Expulsar", "¿Seguro?")
        if r is not None:
            c(f"{tecla} con el foco en «Cancelar» cancela", r, False)
        r = con_tecla_en(tecla, "Sí", "Resync", "¿Ahora?", "Sí", "No")
        if r is not None:
            c(f"{tecla} con el foco en «Sí» (rótulos del resync) acepta", r, True)
        r = con_tecla_en(tecla, "No", "Resync", "¿Ahora?", "Sí", "No")
        if r is not None:
            c(f"{tecla} con el foco en «No» (rótulos del resync) cancela", r, False)

    # --- avisar()
    conducir(lambda dlg: boton(dlg, "Aceptar").invoke())
    c("avisar() no devuelve nada", uitk.avisar(raiz, "Expulsar", "Ya puedes quitarla.", "Verde."), None)
    c("  dice el texto bajo su título", vistos["etiquetas"], ["Expulsar", "Ya puedes quitarla."])
    c("  con un solo botón, «Aceptar»", vistos["botones"], ["Aceptar"])
    c("  y el título de la barra", vistos["titulo"], "prdrive — Expulsar")
    conducir(lambda dlg: None)
    uitk.avisar(raiz, "Guardar el log", "No se ha podido guardar:\n\nsin sitio", "Rojo.")
    c("  un error es un aviso rojo, con su texto", "No se ha podido guardar:\n\nsin sitio" in vistos["etiquetas"], True)

    # --- cuelga de su padre, salvo la raíz oculta
    padre = tk.Toplevel(raiz)
    padre.deiconify()
    padre.update()
    conducir(lambda dlg: None)
    uitk.preguntar(padre, "Expulsar", "¿Seguro?")
    c("de una ventana que se ve, el diálogo cuelga de ella", vistos["transitorio"], str(padre))
    c("  y `_suelto()` dice que no es una raíz oculta", uitk._suelto(padre), False)
    uitk.preguntar(raiz, "Expulsar", "¿Seguro?")
    c("de la raíz oculta no cuelga (un transitorio de uno oculto no se vería)",
      (vistos["transitorio"], uitk._suelto(raiz)), ("", True))
    padre.destroy()
finally:
    uitk.mostrar = real_mostrar

# --- quién pasa por ellos
reales = (uitk.preguntar, uitk.avisar)
llamadas: list = []
try:
    uitk.preguntar = lambda parent, titulo, texto, aceptar="Aceptar", cancelar="Cancelar": (
        llamadas.append(("preguntar", parent, titulo, texto, aceptar, cancelar)) or True)
    uitk.avisar = lambda parent, titulo, texto, tono="Azul.": llamadas.append(
        ("avisar", parent, titulo, texto, tono))
    c("«--resync» pregunta con el diálogo del tema, con sí y no",
      uitk.preguntar_resync(raiz, ["docs", "fotos"], None), True)
    _, padre_, titulo, texto, aceptar, cancelar = llamadas[0]
    c("  colgado de quien pregunta, con las parejas en el texto",
      (padre_ is raiz, titulo, "docs" in texto and "fotos" in texto, aceptar, cancelar),
      (True, "Resync", True, "Sí", "No"))
    llamadas.clear()
    c("el llavero pregunta con él, en su título",
      tk_llavero.preguntar(raiz, "¿Cerrarlo?"), True)
    c("  y avisa con el aviso ámbar",
      (llamadas[0][2:], tk_llavero.avisar(raiz, "Ojo"), llamadas[1][2:]),
      ((llavero_editor.TITULO, "¿Cerrarlo?", "Sí", "No"), None,
       (llavero_editor.TITULO, "Ojo", "Ambar.")))
finally:
    uitk.preguntar, uitk.avisar = reales

# --- en ui/tk.py, el único cuadro del sistema es el de `TkFrontend.info()`
arbol = ast.parse((Path(REPO) / "ui" / "tk.py").read_text(encoding="utf-8"))
con_cuadro = []
for nodo in ast.walk(arbol):
    if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
        propios = [n for n in ast.walk(nodo)
                   if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                       and n.value.id == "messagebox")
                   or (isinstance(n, ast.ImportFrom) and any(a.name == "messagebox" for a in n.names))]
        if propios:
            con_cuadro.append(nodo.name)
c("en ui/tk.py solo `info()` (sale sin ventana principal) usa un cuadro del sistema",
  sorted(set(con_cuadro)), ["info"])

raiz.destroy()
raise SystemExit(c.report())
