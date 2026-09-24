#!/usr/bin/env python3
"""
La ventana principal y el servicio (#14): un servicio, dos maneras de arrancarlo.

Las casillas son las mismas para «Sincronizar ahora» y para «Iniciar servicio»,
salen marcadas con lo del servicio, y solo «Iniciar servicio» lo guarda. Aquí se
comprueba lo que se ve y se toca en la ventana:

  * el botón de marcar o desmarcar todas, y el «N de M» que sigue a las casillas;
  * que una pasada manual no escribe la configuración del servicio;
  * la línea que dice qué hace este equipo al enchufar, en cada estado, y que
    su botón lleva a la pantalla del vigilante y al volver se repinta;
  * que con lo más largo que puede salir —doce parejas, el botón de marcar y la
    línea en ámbar— la ventana cabe o se desplaza, en la matriz de resolución y
    `tk scaling` de `test_tk_medidas`.

Nada se enseña ni se lanza: el bucle de eventos se sustituye por lo que se quiere
pulsar, y la salida de sync.py y la pantalla del vigilante por un apunte.
"""

import re
import sys

from _harness import Checks, mkcfg, sandbox, tmpdir

c = Checks("ventana principal: el servicio y el arranque automático")

try:
    import tkinter as tk
    from tkinter import ttk
    tk.Tk().destroy()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

import ui.tk as uitk  # noqa: E402
from common import update  # noqa: E402
from ui import prefs, theme, tk_watch, watch  # noqa: E402

# Nada de red ni del estado de quien ejecuta el test.
update.pending = lambda root=None: None
update.check = lambda force=False: (None, None)
uitk.pair_status_notes = lambda cfg: {}
uitk.preguntar_resync = lambda root, pendientes: False
lanzadas: list = []
uitk.output_window = lambda titulo, cmd, **k: lanzadas.append(cmd)
prefs.PREFS = tmpdir("prdrive-tkservicio-") / "ui_prefs.json"

CUATRO = mkcfg(["upload", "claves", "docs", "prdrive"],
               {"pairs": ["docs"], "interval_minutes": 15})
UNA = mkcfg(["notas"])
INSTALADO = watch.Resumen("instalado", "daemon")


def recorrer(w):
    pila = [w]
    while pila:
        actual = pila.pop()
        yield actual
        pila += list(actual.winfo_children())


def botones(w) -> dict:
    return {b.cget("text"): b for b in recorrer(w) if isinstance(b, ttk.Button)}


def textos(w) -> list[str]:
    return [str(x.cget("text")) for x in recorrer(w) if isinstance(x, ttk.Label)]


def casillas(w) -> dict:
    return {b.cget("text"): b for b in recorrer(w) if isinstance(b, ttk.Checkbutton)}


def marcadas(w) -> list[str]:
    return sorted(n for n, b in casillas(w).items() if b.instate(["selected"]))


def cuenta(w) -> str:
    return next((t for t in textos(w) if re.match(r"^\d+ de \d+", t)), "")


def ventana(cfg, conducir, resumen=INSTALADO):
    """Abre la principal con ese arranque automático y, en vez de su bucle de
    eventos, ejecuta `conducir`. Devuelve la elección con que se cierra."""
    watch.resumen = lambda: resumen

    def _mainloop(self):
        conducir(self)
        try:
            for pendiente in self.tk.splitlist(self.tk.call("after", "info")):
                self.after_cancel(pendiente)
            self.destroy()
        except tk.TclError:
            pass             # ya la cerró el propio botón (el del servicio)
    tk.Tk.mainloop = _mainloop
    return uitk.main_window(cfg, None)


# --- marcar o desmarcar todas ---------------------------------------------------
with sandbox():
    prefs.PREFS.unlink(missing_ok=True)
    visto: dict = {}

    def todas(root) -> None:
        visto["al abrir"] = (marcadas(root), cuenta(root), "Marcar todas" in botones(root))
        botones(root)["Marcar todas"].invoke()
        visto["todas"] = (marcadas(root), cuenta(root),
                          "Desmarcar todas" in botones(root))
        botones(root)["Desmarcar todas"].invoke()
        visto["ninguna"] = (marcadas(root), cuenta(root), "Marcar todas" in botones(root))
        casillas(root)["claves"].invoke()
        visto["una a mano"] = (marcadas(root), cuenta(root))
        for nombre in ("upload", "docs", "prdrive"):
            casillas(root)[nombre].invoke()
        visto["todas a mano"] = "Desmarcar todas" in botones(root)

    ventana(CUATRO, todas)
    c("abre con lo del servicio ([daemon] sin recuerdo)", visto["al abrir"],
      (["docs"], "1 de 4", True))
    c("«Marcar todas» las marca y pasa a decir «Desmarcar todas»", visto["todas"],
      (["claves", "docs", "prdrive", "upload"], "4 de 4", True))
    c("«Desmarcar todas» las quita y vuelve a «Marcar todas»", visto["ninguna"],
      ([], "0 de 4", True))
    c("el «N de M» sigue a una casilla tocada a mano", visto["una a mano"],
      (["claves"], "1 de 4"))
    c("marcadas a mano una a una, el botón también cambia", visto["todas a mano"], True)

with sandbox():
    nombres: dict = {}
    ventana(UNA, lambda root: nombres.update(botones(root)))
    c("con una sola pareja no hay botón de marcar",
      ("Marcar todas" in nombres, "Desmarcar todas" in nombres), (False, False))


# --- una pasada manual no toca el servicio; arrancarlo sí lleva lo elegido -------
with sandbox():
    prefs.PREFS.unlink(missing_ok=True)
    lanzadas.clear()

    def a_mano(root) -> None:
        casillas(root)["claves"].invoke()
        botones(root)["Sincronizar ahora"].invoke()

    ventana(CUATRO, a_mano)
    c("«Sincronizar ahora» lanza lo marcado", [cmd[2:] for cmd in lanzadas],
      [["claves", "docs"]])
    c("y no escribe la configuración del servicio", prefs.PREFS.exists(), False)

    def servicio(root) -> None:
        casillas(root)["upload"].invoke()
        spin = next(w for w in recorrer(root) if isinstance(w, ttk.Spinbox))
        spin.set("12")
        botones(root)["Iniciar servicio"].invoke()

    eleccion = ventana(CUATRO, servicio)
    c("«Iniciar servicio» sale con lo marcado y el intervalo",
      (eleccion.action, eleccion.pairs, eleccion.minutes),
      ("daemon", ("upload", "docs"), 12.0))


# --- la línea del arranque automático -------------------------------------------
ESTADOS = (watch.Resumen("sin_instalar"), watch.Resumen("otro_dispositivo"),
           watch.Resumen("desfasado", "daemon"), watch.Resumen("instalado", "ui"),
           watch.Resumen("instalado", "daemon"), watch.Resumen("instalado", "sync"))
for res in ESTADOS:
    with sandbox():
        visto = {}
        ventana(CUATRO, lambda root: visto.update(textos=textos(root),
                                                  botones=list(botones(root))),
                resumen=res)
        dicho = watch.linea(res)
        nombre = res.estado + (f" ({res.modo})" if res.modo else "")
        c(f"{nombre}: la línea lo dice", dicho.texto in visto["textos"], True)
        c(f"{nombre}: con su botón", dicho.boton in visto["botones"], True)
        c(f"{nombre}: la pausa solo si vigila este dispositivo",
          watch.PAUSA in visto["textos"], res.vigila_este)
        c(f"{nombre}: ya no hay botón «Arranque automático…»",
          "Arranque automático…" in visto["botones"], False)
        c(f"{nombre}: el intervalo es del servicio",
          "El servicio repite cada" in visto["textos"], True)

with sandbox():
    visto = {}
    ventana(CUATRO, lambda root: visto.update(botones=list(botones(root)),
                                              textos=textos(root)),
            resumen=watch.Resumen("no_disponible"))
    c("sin penwatch no hay línea",
      [b for b in ("Configurar…", "Cambiar…", "Revisar…") if b in visto["botones"]], [])
    c("ni pausa", watch.PAUSA in visto["textos"], False)

# El botón lleva a la pantalla del vigilante y, al volver, la línea se relee: se
# puede haber instalado, cambiado de modo o quitado.
with sandbox():
    abiertas: list = []
    visto = {}
    real_open = tk_watch.open_dialog

    def instalar_desde_la_pantalla(parent) -> None:
        abiertas.append(parent)
        watch.resumen = lambda: watch.Resumen("instalado", "sync")

    tk_watch.open_dialog = instalar_desde_la_pantalla
    try:
        def cambiar(root) -> None:
            botones(root)["Configurar…"].invoke()
            visto["textos"] = textos(root)

        ventana(CUATRO, cambiar, resumen=watch.Resumen("sin_instalar"))
    finally:
        tk_watch.open_dialog = real_open
    c("«Configurar…» abre la pantalla del vigilante", len(abiertas), 1)
    c("y al volver la línea dice lo nuevo",
      "Al enchufarlo en este equipo: una pasada de estas parejas." in visto["textos"], True)



# --- que quepa ---------------------------------------------------------------------
# La ventana principal abre su propio intérprete de Tk, así que la escala no se le
# puede cambiar desde fuera como en `test_tk_medidas`: se pone en el momento en
# que se le aplica el tema, que es lo primero que hace con su `Tk()` y antes de
# crear ningún widget. La pantalla, igual que allí: sustituyendo `pantalla_util`.
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
DOCE = mkcfg([f"pareja-con-nombre-largo-{i}" for i in range(12)])
REAL_UTIL, REAL_APPLY = uitk.pantalla_util, theme.apply


def medir(root) -> None:
    """(cabe, recortado), como `cabe()` y `recortado()` de test_tk_medidas."""
    root.update_idletasks()
    util_x, util_y = uitk.pantalla_util(root)
    visor = root.visor
    visor.interior.update_idletasks()
    ancho, alto = visor._medida()
    medida["cabe"] = (root.winfo_reqwidth() <= util_x
                      and root.winfo_reqheight() <= util_y)
    medida["recortado"] = ((visor.interior.winfo_reqheight() > alto
                            and not visor.vertical.grid_info())
                           or (visor.interior.winfo_reqwidth() > ancho
                               and not visor.horizontal.grid_info()))


try:
    for nombre, ancho, alto, escala in PANTALLAS:
        uitk.pantalla_util = lambda win, a=ancho, h=alto: (a, h)

        def con_escala(widget, e=escala):
            widget.tk.call("tk", "scaling", e)
            REAL_APPLY(widget)

        theme.apply = con_escala
        with sandbox():
            medida: dict = {}
            ventana(DOCE, medir, resumen=watch.Resumen("desfasado", "daemon"))
            c(f"{nombre}: la ventana principal cabe", medida.get("cabe"), True)
            c(f"{nombre}: y no queda recortada", medida.get("recortado"), False)
finally:
    uitk.pantalla_util, theme.apply = REAL_UTIL, REAL_APPLY


# --- que quepa ---------------------------------------------------------------------
# La ventana principal abre su propio intérprete de Tk, así que la escala no se le
# puede cambiar desde fuera como en `test_tk_medidas`: se pone en el momento en
# que se le aplica el tema, que es lo primero que hace con su `Tk()` y antes de
# crear ningún widget. La pantalla, igual que allí: sustituyendo `pantalla_util`.
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
DOCE = mkcfg([f"pareja-con-nombre-largo-{i}" for i in range(12)])
REAL_UTIL, REAL_APPLY = uitk.pantalla_util, theme.apply


def medir(root) -> None:
    """(cabe, recortado), como `cabe()` y `recortado()` de test_tk_medidas."""
    root.update_idletasks()
    util_x, util_y = uitk.pantalla_util(root)
    visor = root.visor
    visor.interior.update_idletasks()
    ancho, alto = visor._medida()
    medida["cabe"] = (root.winfo_reqwidth() <= util_x
                      and root.winfo_reqheight() <= util_y)
    medida["recortado"] = ((visor.interior.winfo_reqheight() > alto
                            and not visor.vertical.grid_info())
                           or (visor.interior.winfo_reqwidth() > ancho
                               and not visor.horizontal.grid_info()))


try:
    for nombre, ancho, alto, escala in PANTALLAS:
        uitk.pantalla_util = lambda win, a=ancho, h=alto: (a, h)

        def con_escala(widget, e=escala):
            widget.tk.call("tk", "scaling", e)
            REAL_APPLY(widget)

        theme.apply = con_escala
        with sandbox():
            medida: dict = {}
            ventana(DOCE, medir, resumen=watch.Resumen("desfasado", "daemon"))
            c(f"{nombre}: la ventana principal cabe", medida.get("cabe"), True)
            c(f"{nombre}: y no queda recortada", medida.get("recortado"), False)
finally:
    uitk.pantalla_util, theme.apply = REAL_UTIL, REAL_APPLY

sys.exit(c.report())
