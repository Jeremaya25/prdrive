#!/usr/bin/env python3
"""El panel de progreso de «Servidor» y el aviso de choques, que solo dibujan.

Sin red ni rclone: se le dan `Progreso` y `Resultado` ya hechos. Lo que se comprueba:

- el panel enseña cada texto en su etiqueta; con fracción conocida la barra es
  determinada y vale `fraccion * 100`, sin ella va y viene (indeterminada);
- «Cancelar» avisa una vez a `al_cancelar`, y «Cancelando…» lo deja sin efecto;
- el resultado esconde el progreso y enseña su texto; «Reintentar» solo sale si
  el resultado lo pide, y avisa a `al_reintentar`; `ocultar()` lo quita todo;
- `preguntar_choques` devuelve `"sobrescribir"`, `"omitir"` o `None` (Cancelar,
  Escape, la X), con el título y los botones dichos y el foco en «Cancelar»;
- ningún valor de color ni distancia suelta en el módulo.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from _harness import Checks

c = Checks("«Servidor»: el panel de transferencia")

try:
    import tkinter as tk
    from tkinter import ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from ui import tk_transferencia  # noqa: E402
from ui.transferencia import Progreso, Resultado  # noqa: E402

errores: list[str] = []
raiz.report_callback_exception = (
    lambda tipo, valor, _tb: errores.append(f"{tipo.__name__}: {valor}"))


def visible(w) -> bool:
    """Si el widget está puesto en su rejilla (no quitado con `grid_remove`)."""
    return bool(w.winfo_manager())


def botones(dlg) -> dict:
    """Los `ttk.Button` del diálogo por su rótulo."""
    hallados = {}

    def rec(w):
        for h in w.winfo_children():
            if h.winfo_class() == "TButton":
                hallados[str(h.cget("text"))] = h
            rec(h)
    rec(dlg)
    return hallados


def _etiquetas(dlg) -> list[str]:
    """Los textos de las etiquetas del widget, a cualquier profundidad."""
    salida = []

    def rec(w):
        for h in w.winfo_children():
            if str(h.cget("text")) if h.winfo_class() in ("TLabel", "Label") else "":
                salida.append(str(h.cget("text")))
            rec(h)
    rec(dlg)
    return salida


try:
    # --- el panel
    marco = ttk.Frame(raiz)
    panel = tk_transferencia.Panel(marco)
    panel.marco.grid(row=0, column=0)
    c("el panel nace sin nada a la vista",
      [visible(w) for w in (panel.titulo, panel.barra, panel.cancelar, panel.resultado,
                            panel.reintentar)], [False] * 5)

    panel.mostrar_progreso(Progreso("Subiendo a /datos", "a.txt", "1 de 4 archivos · 1 KiB de 8 KiB",
                                    0.15, "2 KiB/s · quedan 3 s"))
    raiz.update_idletasks()
    c("  se ve", visible(panel.marco), True)
    c("  título, archivo, cuenta y ritmo, en su etiqueta",
      (panel.titulo.cget("text"), panel.archivo.cget("text"), panel.cuenta.cget("text"),
       panel.ritmo.cget("text")),
      ("Subiendo a /datos", "a.txt", "1 de 4 archivos · 1 KiB de 8 KiB", "2 KiB/s · quedan 3 s"))
    c("  con fracción, la barra es determinada", str(panel.barra.cget("mode")), "determinate")
    c("  y vale el 15 %", round(float(panel.barra.cget("value"))), 15)
    c("  el botón es «Cancelar» y se ve", (panel.cancelar.cget("text"), visible(panel.cancelar)),
      ("Cancelar", True))
    c("  sin resultado ni «Reintentar»", (visible(panel.resultado), visible(panel.reintentar)),
      (False, False))

    panel.mostrar_progreso(Progreso("Subiendo a /datos", "", "0 de 0 archivos", None, ""))
    c("sin fracción, la barra es indeterminada", str(panel.barra.cget("mode")), "indeterminate")
    panel.mostrar_progreso(Progreso("Subiendo a /datos", "b", "1 de 2", 0.5, ""))
    c("  y al saberse vuelve a determinada", (str(panel.barra.cget("mode")),
                                              round(float(panel.barra.cget("value")))),
      ("determinate", 50))

    llamadas: list[str] = []
    panel.al_cancelar = lambda: llamadas.append("cancelar")
    panel.cancelar.invoke()
    c("«Cancelar» avisa una vez", llamadas, ["cancelar"])

    panel.mostrar_cancelando()
    c("«Cancelando…» lo dice y deja el botón sin efecto",
      (panel.archivo.cget("text"), str(panel.cancelar.cget("state"))),
      ("Cancelando…", "disabled"))
    panel.mostrar_progreso(Progreso("Subiendo a /datos", "c", "2 de 2", 1.0, ""))
    c("  un progreso nuevo vuelve a activarlo", str(panel.cancelar.cget("state")), "normal")

    # --- el resultado
    panel.mostrar_resultado(Resultado("Copiados 3 · omitidos 1", "ok", False))
    raiz.update_idletasks()
    c("el resultado esconde el progreso",
      [visible(w) for w in (panel.titulo, panel.archivo, panel.cuenta, panel.barra,
                            panel.ritmo, panel.cancelar)], [False] * 6)
    c("  y enseña su texto", (visible(panel.resultado), "Copiados 3 · omitidos 1" in _etiquetas(panel.resultado)),
      (True, True))
    c("  sin «Reintentar» si no lo pide", visible(panel.reintentar), False)

    panel.mostrar_resultado(Resultado("No tienes permiso para escribir en /datos.", "aviso", True))
    c("con «reintentar», «Reintentar» sale", (visible(panel.reintentar),
                                              panel.reintentar.cget("text")), (True, "Reintentar"))
    otra: list[str] = []
    panel.al_reintentar = lambda: otra.append("r")
    panel.reintentar.invoke()
    c("  y avisa a `al_reintentar`", otra, ["r"])
    panel.mostrar_resultado(Resultado("Copiados 1", "ok", False))
    c("  un resultado sin reintentar lo quita", visible(panel.reintentar), False)

    panel.mostrar_progreso(Progreso("Bajando a /x", "z", "1 de 1", 0.2, ""))
    c("un progreso tras el resultado lo esconde y enseña el progreso",
      (visible(panel.resultado), visible(panel.barra), visible(panel.reintentar)),
      (False, True, False))
    panel.ocultar()
    c("ocultar() lo quita todo", visible(panel.marco), False)

    # --- el aviso de choques
    originales = tk_transferencia.mostrar
    vistos: dict = {}

    def conducir(accion):
        """Sustituye `mostrar` por algo que mira el diálogo y hace `accion` sobre él."""
        def falso(dlg, parent=None):
            vistos["titulo"] = dlg.title()
            vistos["botones"] = sorted(botones(dlg))
            vistos["fondo"] = dlg.cget("background")
            vistos["foco"] = [t for t, b in botones(dlg).items()
                              if str(b.cget("default")) == "active"]
            vistos["etiquetas"] = _etiquetas(dlg)
            accion(dlg)
        tk_transferencia.mostrar = falso

    texto = "2 elementos ya existen en /datos. ¿Sobrescribirlos u omitirlos?"
    conducir(lambda d: botones(d)["Sobrescribir"].invoke())
    c("«Sobrescribir» devuelve «sobrescribir»", tk_transferencia.preguntar_choques(raiz, texto),
      "sobrescribir")
    c("  título y botones dichos",
      (vistos["titulo"], vistos["botones"]),
      ("prdrive — Ya existen", ["Cancelar", "Omitir", "Sobrescribir"]))
    c("  el texto está en el diálogo", texto in vistos["etiquetas"], True)
    c("  el fondo es el del tema", vistos["fondo"], tk_transferencia.theme.PAPEL)
    conducir(lambda d: botones(d)["Omitir"].invoke())
    c("«Omitir» devuelve «omitir»", tk_transferencia.preguntar_choques(raiz, texto), "omitir")
    conducir(lambda d: botones(d)["Cancelar"].invoke())
    c("«Cancelar» devuelve None", tk_transferencia.preguntar_choques(raiz, texto), None)
    conducir(lambda d: d.destroy())
    c("cerrar con la X devuelve None", tk_transferencia.preguntar_choques(raiz, texto), None)

    def con_escape(d):
        d.deiconify()
        d.update()
        d.focus_force()
        d.update()
        d.event_generate("<Escape>")
        d.update()
        if d.winfo_exists():
            d.destroy()
            vistos["escape_no_cerro"] = True
    vistos.pop("escape_no_cerro", None)
    conducir(con_escape)
    r = tk_transferencia.preguntar_choques(raiz, texto)
    if vistos.get("escape_no_cerro"):
        print("  (saltado) Escape: este escritorio no da el foco a una ventana nueva")
    else:
        c("Escape devuelve None", r, None)

    def foco(d):
        d.deiconify()
        d.update()
        # `-lastfor`: dónde queda el foco del diálogo aunque el escritorio no se lo dé
        vistos["foco_en"] = str(d.nametowidget(d.tk.call("focus", "-lastfor", str(d))).cget("text"))
        d.destroy()
    conducir(foco)
    tk_transferencia.preguntar_choques(raiz, texto)
    c("el foco inicial está en «Cancelar»", vistos["foco_en"], "Cancelar")

    if sys.platform != "win32":
        def intro(d):
            d.deiconify()
            d.update()
            d.focus_force()
            d.update()
            vistos["intro_foco"] = d.focus_get() is not None
            botones(d)["Cancelar"].focus_set()
            d.update()
            d.event_generate("<KP_Enter>")
            d.update()
            if d.winfo_exists():
                d.destroy()
        conducir(intro)
        r = tk_transferencia.preguntar_choques(raiz, texto)
        if vistos.get("intro_foco"):
            c("Intro con el foco en «Cancelar» cancela", r, None)

    tk_transferencia.mostrar = originales

    # --- nada de colores ni distancias sueltas
    fuente = Path(tk_transferencia.__file__).read_text(encoding="utf-8")
    c("el módulo no escribe ningún color", re.findall(r"#[0-9a-fA-F]{3,8}\b", fuente), [])
    c("ni deja una distancia suelta (padding/pady/padx/wraplength con un número distinto de 0)",
      re.findall(r"(?:pad[xy]?|wraplength)\s*=\s*\(?\s*[1-9]", fuente), [])
    c("ningún error de Tk", errores, [])
finally:
    raiz.destroy()

sys.exit(c.report())
