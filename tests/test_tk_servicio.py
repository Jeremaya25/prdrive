#!/usr/bin/env python3
"""La ventana principal y el servicio (#14): un servicio, dos maneras de arrancarlo.

Las casillas son las mismas para «Sincronizar ahora» y para «Iniciar servicio»,
salen marcadas con lo del servicio, y solo «Iniciar servicio» las guarda. El
intervalo ya no está en la ventana sino en «Ajustes → Configuración» (#65), que
guarda solo el intervalo. Aquí se comprueba lo que se ve y se toca en la
ventana:
- El botón de marcar o desmarcar todas, y el «N de M» que sigue a las casillas.
- Que una pasada manual no escribe la configuración del servicio.
- Que «Configuración», desde el engranaje, guarda el intervalo sin las parejas,
  y que «Iniciar servicio» sale después con él.
- La línea que dice qué hace este equipo al enchufar, en cada estado, y que su
  botón lleva a la pantalla del vigilante y al volver se repinta.
- Que con lo más largo que puede salir (doce parejas, el botón de marcar, la
  línea en ámbar y «Expulsar» en el pie) la ventana cabe o se desplaza, en la
  matriz de resolución y `tk scaling` de `test_tk_medidas`.

Nada se enseña ni se lanza: el bucle de eventos se sustituye por lo que se
quiere pulsar, y la salida de `sync.py` y la pantalla del vigilante por un
apunte.
"""

import re
import sys
from pathlib import Path

from _harness import Checks, mkcfg, sandbox, tmpdir

c = Checks("ventana principal: el servicio y el arranque automático")

try:
    import tkinter as tk
    from tkinter import ttk
    tk.Tk().destroy()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

import json  # noqa: E402

import ui.tk as uitk  # noqa: E402
from common import update  # noqa: E402
from ui import (cifrado, prefs, theme, tk_configuracion, tk_doctor,  # noqa: E402
                tk_watch, watch)

# Nada de red ni del estado de quien ejecuta el test.
update.pending = lambda root=None: None
update.check = lambda force=False: (None, None)
uitk.pair_status_notes = lambda cfg: {}
uitk.preguntar_resync = lambda root, pendientes: False
lanzadas: list = []
uitk.output_window = lambda titulo, cmd, **k: lanzadas.append(cmd)
# Ni contenedor VeraCrypt ni recorrido de unidades: «Expulsar» solo sale donde
# se pide, en la medida de más abajo.
cifrado.expulsion = lambda: None
prefs.PREFS = tmpdir("prdrive-tkservicio-") / "ui_prefs.json"

CUATRO = mkcfg(["upload", "claves", "docs", "prdrive"],
               {"pairs": ["docs"], "interval_minutes": 15})
UNA = mkcfg(["notas"])
INSTALADO = watch.Resumen("instalado", "daemon")


def recorrer(w):
    """Recorre los widgets que cuelgan de `w`, en profundidad."""
    pila = [w]
    while pila:
        actual = pila.pop()
        yield actual
        pila += list(actual.winfo_children())


def botones(w) -> dict:
    """Devuelve los botones de `w` por su texto."""
    return {b.cget("text"): b for b in recorrer(w) if isinstance(b, ttk.Button)}


def textos(w) -> list[str]:
    """Devuelve los textos de las etiquetas de `w`."""
    return [str(x.cget("text")) for x in recorrer(w) if isinstance(x, ttk.Label)]


def casillas(w) -> dict:
    """Devuelve las casillas de `w` por su texto."""
    return {b.cget("text"): b for b in recorrer(w) if isinstance(b, ttk.Checkbutton)}


def marcadas(w) -> list[str]:
    """Devuelve los textos de las casillas marcadas, ordenados."""
    return sorted(n for n, b in casillas(w).items() if b.instate(["selected"]))


def cuenta(w) -> str:
    """Devuelve el «N de M» de la ventana, o `""`."""
    return next((t for t in textos(w) if re.match(r"^\d+ de \d+", t)), "")


def ventana(cfg, conducir, resumen=INSTALADO):
    """Abre la principal con ese arranque automático y la conduce.

    En vez de su bucle de eventos ejecuta `conducir`. Devuelve la elección con
    que se cierra.
    """
    watch.resumen = lambda: resumen

    def _mainloop(self):
        """Conduce la ventana y cancela lo que dejó programado."""
        conducir(self)
        try:
            for pendiente in self.tk.splitlist(self.tk.call("after", "info")):
                self.after_cancel(pendiente)
            self.destroy()
        except tk.TclError:
            pass             # ya la cerró el propio botón (el del servicio)
    tk.Tk.mainloop = _mainloop
    return uitk.main_window(cfg, None)


# marcar o desmarcar todas
with sandbox():
    prefs.PREFS.unlink(missing_ok=True)
    visto: dict = {}

    def todas(root) -> None:
        """Apunta las casillas y pulsa «Marcar todas»."""
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


# una pasada manual no toca el servicio; arrancarlo sí lleva lo elegido
with sandbox():
    prefs.PREFS.unlink(missing_ok=True)
    lanzadas.clear()

    def a_mano(root) -> None:
        """Desmarca una pareja y pulsa «Sincronizar ahora»."""
        casillas(root)["claves"].invoke()
        botones(root)["Sincronizar ahora"].invoke()

    ventana(CUATRO, a_mano)
    c("«Sincronizar ahora» lanza lo marcado", [cmd[2:] for cmd in lanzadas],
      [["claves", "docs"]])
    c("y no escribe la configuración del servicio", prefs.PREFS.exists(), False)

    def servicio(root) -> None:
        """Cambia las parejas y pulsa «Iniciar servicio»."""
        visto["spinbox"] = any(isinstance(w, ttk.Spinbox) for w in recorrer(root))
        casillas(root)["upload"].invoke()
        botones(root)["Iniciar servicio"].invoke()

    visto = {}
    eleccion = ventana(CUATRO, servicio)
    c("el intervalo ya no está en la ventana principal", visto["spinbox"], False)
    c("«Iniciar servicio» sale con lo marcado y el intervalo del servicio",
      (eleccion.action, eleccion.pairs, eleccion.minutes),
      ("daemon", ("upload", "docs"), 15.0))


# «Ajustes → Configuración»: el intervalo, guardado sin las parejas (#65)
REAL_DOCTOR_MOSTRAR, REAL_CONF_MOSTRAR = tk_doctor.mostrar, tk_configuracion.mostrar


def pulsar_en(dlg, texto) -> None:
    """Pulsa el botón de `dlg` que dice `texto`."""
    botones(dlg)[texto].invoke()


with sandbox():
    prefs.PREFS.unlink(missing_ok=True)
    visto = {}

    def en_ajustes(dlg, parent=None) -> None:
        """Hace de «Ajustes»: apunta sus entradas y abre «Configuración…»."""
        visto["entradas"] = [b for b in botones(dlg) if b.endswith("…")]
        visto["casilla en ajustes"] = any("contraseña" in t for t in casillas(dlg))
        pulsar_en(dlg, "Configuración…")
        if dlg.winfo_exists():
            pulsar_en(dlg, "Cerrar")

    def en_configuracion(dlg, parent=None) -> None:
        """Hace de «Configuración»: escribe 20 minutos y guarda."""
        spin = next(w for w in recorrer(dlg) if isinstance(w, ttk.Spinbox))
        visto["al abrir"] = spin.get()
        visto["sin casilla"] = not casillas(dlg)
        spin.set("20")
        pulsar_en(dlg, "Guardar")

    tk_doctor.mostrar, tk_configuracion.mostrar = en_ajustes, en_configuracion
    try:
        def configurar_y_arrancar(root) -> None:
            """Abre Ajustes → Configuración y luego pulsa «Iniciar servicio»."""
            botones(root)["Ajustes…"].invoke()
            visto["guardado"] = json.loads(prefs.PREFS.read_text(encoding="utf-8"))
            visto["marcadas"] = marcadas(root)
            botones(root)["Iniciar servicio"].invoke()

        eleccion = ventana(CUATRO, configurar_y_arrancar)
    finally:
        tk_doctor.mostrar, tk_configuracion.mostrar = REAL_DOCTOR_MOSTRAR, REAL_CONF_MOSTRAR
    c("«Ajustes» tiene «Configuración…»", "Configuración…" in visto["entradas"], True)
    c("  como segunda entrada, tras «Reparación…»",
      [rotulo for rotulo, *_ in tk_doctor.ENTRADAS][:2], ["Reparación…", "Configuración…"])
    c("  la casilla de la contraseña ya no está en «Ajustes»",
      visto["casilla en ajustes"], False)
    c("  abre con el intervalo del servicio ([daemon] del TOML)", visto["al abrir"], "15")
    c("  y sin la casilla, que es de la raíz cifrada de un equipo", visto["sin casilla"],
      True)
    c("«Guardar» escribe el intervalo y no las parejas",
      ("pairs" in visto["guardado"], visto["guardado"]["interval_min"]), (False, 20.0))
    c("  las casillas siguen con las del servicio", visto["marcadas"], ["docs"])
    c("«Iniciar servicio» después sale con el intervalo guardado",
      (eleccion.pairs, eleccion.minutes), (("docs",), 20.0))


# la línea del arranque automático
ESTADOS = (watch.Resumen("sin_instalar"), watch.Resumen("otro_dispositivo"),
           watch.Resumen("desfasado", "daemon"), watch.Resumen("instalado", "ui"),
           watch.Resumen("instalado", "daemon"), watch.Resumen("instalado", "sync"),
           # La línea del agente (fase 5): en marcha, parado, en pausa, la raíz.
           watch.Resumen("agente", "daemon", True), watch.Resumen("agente", "ui", False),
           watch.Resumen("agente", "sync", True, True),
           watch.Resumen("agente_nueva", "", True),
           watch.Resumen("agente_raiz", "daemon", True))
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
        c(f"{nombre}: el intervalo no está en la ventana, está en «Configuración»",
          "El servicio repite cada" in visto["textos"], False)

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
        """Hace de pantalla del vigilante: deja el arranque automático instalado."""
        abiertas.append(parent)
        watch.resumen = lambda: watch.Resumen("instalado", "sync")

    tk_watch.open_dialog = instalar_desde_la_pantalla
    try:
        def cambiar(root) -> None:
            """Pulsa «Configurar…» y apunta los textos al volver."""
            botones(root)["Configurar…"].invoke()
            visto["textos"] = textos(root)

        ventana(CUATRO, cambiar, resumen=watch.Resumen("sin_instalar"))
    finally:
        tk_watch.open_dialog = real_open
    c("«Configurar…» abre la pantalla del vigilante", len(abiertas), 1)
    c("y al volver la línea dice lo nuevo",
      "Al enchufarlo en este equipo: una pasada de estas parejas." in visto["textos"], True)


# Con el agente, el botón abre «Qué hace el agente», y la línea enseña lo pedido.
with sandbox():
    pedidos: list = []
    visto = {}
    real_agente = tk_watch.open_agente
    tk_watch.open_agente = lambda parent, res: pedidos.append(res) or "nada"
    try:
        def cambiar_agente(root) -> None:
            """Pulsa «Cambiar…» y apunta los textos al volver."""
            botones(root)["Cambiar…"].invoke()
            visto["textos"] = textos(root)

        ventana(CUATRO, cambiar_agente, resumen=watch.Resumen("agente", "daemon", True))
    finally:
        tk_watch.open_agente = real_agente
    c("con agente, «Cambiar…» abre «Qué hace el agente»",
      [r.estado for r in pedidos], ["agente"])
    c("  y la línea dice lo pedido",
      "El agente de este equipo no hace nada con él." in visto["textos"], True)


# que quepa
#
# La ventana principal abre su propio intérprete de Tk, así que la escala no se
# le puede cambiar desde fuera como en `test_tk_medidas`: se pone en el momento
# en que se le aplica el tema, que es lo primero que hace con su `Tk()` y antes
# de crear ningún widget. La pantalla, igual que allí: sustituyendo
# `pantalla_util`.
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
    """Devuelve si la ventana cabe y si queda recortada, como en `test_tk_medidas`."""
    root.update_idletasks()
    util_x, util_y = uitk.pantalla_util(root)
    visor = root.visor
    visor.interior.update_idletasks()
    ancho, alto = visor._medida()
    medida["cabe"] = (root.winfo_reqwidth() <= util_x
                      and root.winfo_reqheight() <= util_y)
    medida["expulsar"] = "Expulsar" in botones(root)
    medida["recortado"] = ((visor.interior.winfo_reqheight() > alto
                            and not visor.vertical.grid_info())
                           or (visor.interior.winfo_reqwidth() > ancho
                               and not visor.horizontal.grid_info()))


try:
    for nombre, ancho, alto, escala in PANTALLAS:
        uitk.pantalla_util = lambda win, a=ancho, h=alto: (a, h)

        def con_escala(widget, e=escala):
            """Pone la escala a Tk antes de aplicar el tema."""
            widget.tk.call("tk", "scaling", e)
            REAL_APPLY(widget)

        theme.apply = con_escala
        # Con «Expulsar» en el pie, el tercer botón: el de un dispositivo que
        # vive en un contenedor VeraCrypt. No se pulsa, solo se mide.
        cifrado.expulsion = lambda: Path("E:/Expulsar PRDRIVE.bat")
        with sandbox():
            medida: dict = {}
            ventana(DOCE, medir, resumen=watch.Resumen("desfasado", "daemon"))
            c(f"{nombre}: con «Expulsar» en el pie", medida.get("expulsar"), True)
            c(f"{nombre}: la ventana principal cabe", medida.get("cabe"), True)
            c(f"{nombre}: y no queda recortada", medida.get("recortado"), False)
finally:
    uitk.pantalla_util, theme.apply = REAL_UTIL, REAL_APPLY
    cifrado.expulsion = lambda: None

sys.exit(c.report())
