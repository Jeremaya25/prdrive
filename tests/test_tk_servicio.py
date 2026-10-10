#!/usr/bin/env python3
"""La ventana principal y el servicio (#14): un servicio, dos maneras de arrancarlo.

Las casillas son las mismas para «Sincronizar ahora» y para «Iniciar servicio»,
salen marcadas con lo del servicio, y lo marcado se guarda al poco de marcarlo
(no en el mismo clic: `prefs.SeleccionPendiente`). El intervalo ya no está en la
ventana sino en «Ajustes → Configuración» (#65), que guarda solo el intervalo.
Aquí se comprueba lo que se ve y se toca en la ventana:
- El botón de marcar o desmarcar todas, y el «N de M» que sigue a las casillas.
- Que lo marcado se guarda, y que una pasada manual no escribe por su cuenta la
  configuración del servicio.
- Que «Configuración», desde el engranaje, guarda el intervalo sin las parejas,
  y que «Iniciar servicio» sale después con él.
- Que con el agente como servicio de la raíz el pie ofrece «Pausar» /
  «Reanudar» en vez de «Iniciar servicio» (#64), que cada uno deja su petición
  en el buzón que toca y que la ventana sigue abierta enseñando lo pedido.
- La línea que dice qué hace este equipo al enchufar, en cada estado, y que su
  botón lleva a la pantalla del vigilante y al volver se repinta.
- La línea del llavero: solo con llavero, «Abrir llavero» lo abre desde la
  ventana y al volver se repinta, y sin KeePassXC el botón está apagado.
- Que con lo más largo que puede salir (doce parejas, el botón de marcar, la
  línea en ámbar, la del llavero en ámbar y «Expulsar» en el pie) la ventana
  cabe o se desplaza, en la matriz de resolución y `tk scaling` de
  `test_tk_medidas`.

Nada se enseña ni se lanza: el bucle de eventos se sustituye por lo que se
quiere pulsar, y la salida de `sync.py` y la pantalla del vigilante por un
apunte. La lectura del dispositivo que la ventana hace tras pintarse se hace en
el sitio (`segundo_plano.en_el_acto`) y llega con el primer
`update_idletasks()`; se mira solo lo que está a la vista (`_vista.visibles`),
porque la ventana guarda escondidos los bloques que no enseña.
"""

import gc
import re
import sys
import time
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

from _vista import visibles  # noqa: E402

import ui.tk as uitk  # noqa: E402
from common import config_file, model, update  # noqa: E402
from ui import (cifrado, llavero_editor, prefs, segundo_plano, theme,  # noqa: E402
                tk_configuracion, tk_doctor, tk_llavero, tk_watch, watch)

# Nada de red ni del estado de quien ejecuta el test.
update.pending = lambda root=None: None
update.check = lambda force=False: (None, None)
uitk.pair_status_notes = lambda cfg: {}
uitk.preguntar_resync = lambda root, pendientes, carpetas=None: False
lanzadas: list = []
uitk.output_window = lambda titulo, cmd, **k: lanzadas.append(cmd)
# Ni contenedor VeraCrypt ni recorrido de unidades: «Expulsar» solo sale donde
# se pide, en la medida de más abajo. Los sustitutos aceptan las palabras clave
# que les pasa la lectura de la ventana (`fisica=`).
cifrado.expulsion = lambda **_k: None
segundo_plano.lanzar = segundo_plano.en_el_acto
prefs.PREFS = tmpdir("prdrive-tkservicio-") / "ui_prefs.json"

CUATRO = mkcfg(["upload", "claves", "docs", "prdrive"],
               {"pairs": ["docs"], "interval_minutes": 15})
UNA = mkcfg(["notas"])
INSTALADO = watch.Resumen("instalado", "daemon")


def recorrer(w):
    """Recorre los widgets de `w` que están a la vista, en profundidad."""
    return visibles(w)


def botones(w) -> dict:
    """Devuelve los botones a la vista de `w` por su texto."""
    return {b.cget("text"): b for b in recorrer(w) if isinstance(b, ttk.Button)}


def textos(w) -> list[str]:
    """Devuelve los textos de las etiquetas a la vista de `w`."""
    return [str(x.cget("text")) for x in recorrer(w) if isinstance(x, ttk.Label)]


def casillas(w) -> dict:
    """Devuelve las casillas a la vista de `w` por su texto."""
    return {b.cget("text"): b for b in recorrer(w) if isinstance(b, ttk.Checkbutton)}


def marcadas(w) -> list[str]:
    """Devuelve los textos de las casillas marcadas, ordenados."""
    return sorted(n for n, b in casillas(w).items() if b.instate(["selected"]))


def cuenta(w) -> str:
    """Devuelve el «N de M» de la ventana, o `""`."""
    return next((t for t in textos(w) if re.match(r"^\d+ de \d+", t)), "")


lecturas: list = []


def ventana(cfg, conducir, resumen=INSTALADO):
    """Abre la principal con ese arranque automático y la conduce.

    En vez de su bucle de eventos deja llegar la lectura del dispositivo,
    apunta qué no se pudo leer y ejecuta `conducir`. Devuelve la elección con
    que se cierra.

    Antes recoge la basura en este hilo: la principal arranca hilos de lectura,
    y una `tkinter.Variable` de una ventana anterior que el recolector suelte
    desde uno llamaría a Tk desde allí (sin `mainloop()`, 1 s por cada una).
    """
    gc.collect()
    watch.resumen = lambda: resumen

    def _mainloop(self):
        """Conduce la ventana y cancela lo que dejó programado."""
        self.update_idletasks()
        lecturas.append(dict(self.instantanea.resultado.fallos))
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


# las casillas se guardan al poco de marcarlas; la pasada manual no escribe por su cuenta
def hasta(root, condicion) -> bool:
    """Mueve el bucle de eventos hasta que se cumple `condicion`, como mucho 2 s."""
    limite = time.monotonic() + 2.0
    while not condicion() and time.monotonic() < limite:
        root.update()
        time.sleep(0.005)
    return bool(condicion())


with sandbox():
    prefs.PREFS.unlink(missing_ok=True)
    lanzadas.clear()
    visto = {}
    pedidas: list = []
    real_guardar = prefs.guardar_parejas

    def guardar_apuntando(config, pares) -> bool:
        """Apunta cada vez que la ventana vuelca lo marcado, y lo guarda."""
        pedidas.append(list(pares))
        return real_guardar(config, pares)

    def a_mano(root) -> None:
        """Marca parejas, mira qué queda guardado cada vez y pulsa «Sincronizar ahora»."""
        casillas(root)["claves"].invoke()
        hasta(root, lambda: len(pedidas) == 1)
        visto["al marcar"] = prefs.startup_defaults(CUATRO)[0]
        botones(root)["Marcar todas"].invoke()
        hasta(root, lambda: len(pedidas) == 2)
        visto["al marcar todas"] = prefs.startup_defaults(CUATRO)[0]
        botones(root)["Desmarcar todas"].invoke()
        hasta(root, lambda: len(pedidas) == 3)
        visto["al desmarcar todas"] = prefs.startup_defaults(CUATRO)[0]
        casillas(root)["upload"].invoke()
        casillas(root)["docs"].invoke()
        hasta(root, lambda: len(pedidas) == 4)
        visto["dos seguidas"] = pedidas[3:]
        prefs.PREFS.unlink()
        botones(root)["Sincronizar ahora"].invoke()
        hasta(root, lambda: lanzadas)
        visto["tras sincronizar"] = prefs.PREFS.exists()

    prefs.guardar_parejas = guardar_apuntando
    try:
        ventana(CUATRO, a_mano)
    finally:
        prefs.guardar_parejas = real_guardar
    c("al marcar una casilla queda guardada, sin pulsar nada más", visto["al marcar"],
      ["claves", "docs"])
    c("«Marcar todas» las guarda todas", visto["al marcar todas"],
      ["upload", "claves", "docs", "prdrive"])
    c("sin ninguna marcada se queda lo último guardado", visto["al desmarcar todas"],
      ["upload", "claves", "docs", "prdrive"])
    c("dos casillas seguidas se guardan de una vez", visto["dos seguidas"],
      [["upload", "docs"]])
    c("«Sincronizar ahora» lanza lo marcado", [cmd[2:] for cmd in lanzadas],
      [["upload", "docs"]])
    c("y por sí sola no escribe la configuración del servicio",
      visto["tras sincronizar"], False)

    # Se cierra la ventana con una casilla más marcada y se abre otra.
    prefs.save_prefs("daemon", ["upload", "prdrive"], 15.0, CUATRO.names)
    ventana(CUATRO, lambda root: casillas(root)["docs"].invoke())
    visto.clear()
    ventana(CUATRO, lambda root: visto.update(marcadas=marcadas(root)))
    c("la ventana siguiente sale con las casillas que se dejaron",
      visto["marcadas"], ["docs", "prdrive", "upload"])

    prefs.PREFS.unlink(missing_ok=True)      # sin lo que dejó la ventana de antes

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
        """Hace de «Ajustes»: apunta sus apartados y guarda 20 minutos en «Configuración»."""
        visto["entradas"] = [b.cget("text") for b in recorrer(dlg)
                             if isinstance(b, ttk.Button)
                             and str(b.cget("style")) in ("Nav.TButton", "NavSel.TButton")]
        visto["elegido"] = [b.cget("text") for b in recorrer(dlg)
                            if isinstance(b, ttk.Button)
                            and str(b.cget("style")) == "NavSel.TButton"]
        spin = next(w for w in recorrer(dlg) if isinstance(w, ttk.Spinbox))
        visto["al abrir"] = spin.get()
        visto["sin casilla"] = not casillas(dlg)
        spin.set("20")
        pulsar_en(dlg, "Guardar")
        visto["sigue abierta"] = bool(dlg.winfo_exists())
        visto["guardado dicho"] = "Guardado." in textos(dlg)
        dlg.destroy()

    tk_doctor.mostrar = en_ajustes
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
    c("«Ajustes» tiene «Configuración»", "Configuración" in visto["entradas"], True)
    c("  y abre por ella, dibujada en el sitio", visto["elegido"], ["Configuración"])
    c("  abre con el intervalo del servicio ([daemon] del TOML)", visto["al abrir"], "15")
    c("  y sin la casilla, que es de la raíz cifrada de un equipo", visto["sin casilla"],
      True)
    c("  «Guardar» deja «Ajustes» abierta y dice que se ha guardado",
      (visto["sigue abierta"], visto["guardado dicho"]), (True, True))
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
           watch.Resumen("agente_raiz", "daemon", True),
           # Pausada desde su ventana (#64), y con las dos pausas a la vez.
           watch.Resumen("agente", "daemon", True, False, True),
           watch.Resumen("agente_raiz", "daemon", True, True, True))
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
        frase = watch.pausa(res)
        c(f"{nombre}: la frase de la pausa, solo si vigila este dispositivo y nada "
          f"más lo tiene en pausa",
          [t for t in (watch.PAUSA, watch.PAUSA_AGENTE) if t in visto["textos"]],
          [frase] if frase else [])
        c(f"{nombre}: el botón del servicio es «{watch.boton_servicio(res).texto}»",
          watch.boton_servicio(res).texto in visto["botones"], True)
        c(f"{nombre}: «Iniciar servicio» solo si el servicio no es el agente",
          "Iniciar servicio" in visto["botones"],
          watch.boton_servicio(res).accion == watch.INICIAR)
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


# «Pausar» / «Reanudar» con el agente como servicio (#64): la petición va al
# buzón que toca, la ventana no se cierra y enseña lo pedido.
from common import equipo  # noqa: E402

with sandbox():
    buzon_raiz = model.STATE_DIR / equipo.BUZON_SERVICIO
    equipo.recoger()
    visto = {}

    def pausar_y_reanudar(root) -> None:
        """Pulsa «Pausar», apunta, y luego «Reanudar»."""
        visto["al abrir"] = sorted(b for b in botones(root)
                                   if b in ("Iniciar servicio", "Pausar", "Reanudar"))
        visto["frase al abrir"] = watch.PAUSA_AGENTE in textos(root)
        botones(root)["Pausar"].invoke()
        visto["buzón tras pausar"] = [p["pide"] for p in equipo.recoger(buzon_raiz)]
        visto["sigue abierta"] = root.winfo_exists()
        visto["tras pausar"] = ("Reanudar" in botones(root), "Pausar" in botones(root))
        visto["línea en pausa"] = any("no lo sincroniza hasta que pulses «Reanudar»" in t
                                      for t in textos(root))
        botones(root)["Reanudar"].invoke()
        visto["buzón tras reanudar"] = [p["pide"] for p in equipo.recoger(buzon_raiz)]
        visto["tras reanudar"] = "Pausar" in botones(root)

    eleccion = ventana(CUATRO, pausar_y_reanudar,
                       resumen=watch.Resumen("agente", "daemon", True))
    c("con el agente como servicio, el pie ofrece «Pausar» y no «Iniciar servicio»",
      visto["al abrir"], ["Pausar"])
    c("  y dice que al cerrar vuelve el agente, salvo «Pausar»", visto["frase al abrir"],
      True)
    c("«Pausar» deja pausar_raiz en el buzón de la raíz", visto["buzón tras pausar"],
      [equipo.PIDE_PAUSAR_RAIZ])
    c("  sin cerrar la ventana", visto["sigue abierta"], True)
    c("  el botón pasa a «Reanudar»", visto["tras pausar"], (True, False))
    c("  y la línea lo dice", visto["línea en pausa"], True)
    c("«Reanudar» deja reanudar en el mismo buzón", visto["buzón tras reanudar"],
      [equipo.PIDE_REANUDAR])
    c("  y el botón vuelve a «Pausar»", visto["tras reanudar"], True)
    c("  la ventana se cierra sin elección: no hay servicio que arrancar", eleccion, None)
    c("  y nada ha ido al buzón del agente", equipo.recoger(), [])

    visto = {}

    def reanudar_todo(root) -> None:
        """Pulsa «Reanudar todo» y apunta."""
        botones(root)["Reanudar todo"].invoke()
        visto["buzón"] = [p["pide"] for p in equipo.recoger()]
        visto["después"] = "Pausar" in botones(root)

    ventana(CUATRO, reanudar_todo, resumen=watch.Resumen("agente", "daemon", True, True))
    c("con la pausa de todo, «Reanudar todo» deja sigue en el buzón del agente",
      (visto["buzón"], equipo.recoger(buzon_raiz)), ([equipo.PIDE_SIGUE], []))
    c("  y el botón pasa a «Pausar»", visto["después"], True)

    visto = {}
    real_pedir = watch.pedir_a_la_raiz
    watch.pedir_a_la_raiz = lambda peticion: False
    errores_pie: list = []
    import tkinter.messagebox as mb  # noqa: E402
    real_showerror = mb.showerror
    mb.showerror = lambda titulo, texto=None, **k: errores_pie.append(texto)
    try:
        def pausar_sin_buzon(root) -> None:
            """Pulsa «Pausar» sin poder escribir el buzón."""
            botones(root)["Pausar"].invoke()
            visto["sigue"] = "Pausar" in botones(root)

        ventana(CUATRO, pausar_sin_buzon, resumen=watch.Resumen("agente", "daemon", True))
    finally:
        watch.pedir_a_la_raiz, mb.showerror = real_pedir, real_showerror
    c("sin poder dejar la petición, lo dice y el botón no cambia",
      (errores_pie, visto["sigue"]), (["No he podido dejarle la petición al agente."],
                                      True))


# la línea del llavero, y su botón
CON_LLAVERO = model.parse_config({
    "defaults": {"remote": "nas"},
    "pair": [{"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas"}],
    "keychain": {"base": "personal.kdbx"}})
REAL_LINEA, REAL_ABRIR = llavero_editor.linea, tk_llavero.abrir
REAL_AJUSTES, REAL_CERRAR = tk_llavero.construir_ajustes, tk_llavero.cerrar
with sandbox():
    estado = {"abierto": False, "boton": True}
    abiertos: list = []

    def linea_de_mentira(cfg):
        """La línea del llavero según `estado`; sin llavero, ninguna."""
        if cfg.llavero is None:
            return None
        texto = ("personal.kdbx, abierto en KeePassXC." if estado["abierto"]
                 else "personal.kdbx, al día.")
        return llavero_editor.Linea(texto, False, estado["boton"])

    def abrir_de_mentira(root, cfg, suelto=False):
        """Apunta que se ha abierto, y lo deja abierto."""
        abiertos.append((cfg.llavero["base"], suelto))
        estado["abierto"] = True
        return True

    llavero_editor.linea, tk_llavero.abrir = linea_de_mentira, abrir_de_mentira
    try:
        visto = {}

        def pulsar_llavero(root) -> None:
            """Mira la línea, pulsa «Abrir llavero» y la vuelve a mirar."""
            visto["antes"] = "personal.kdbx, al día." in textos(root)
            botones(root)["Abrir llavero"].invoke()
            visto["después"] = "personal.kdbx, abierto en KeePassXC." in textos(root)

        ventana(CON_LLAVERO, pulsar_llavero)
        c("con llavero, su línea", visto["antes"], True)
        c("  «Abrir llavero» lo abre desde la ventana, no suelto", abiertos,
          [("personal.kdbx", False)])
        c("  y al volver se repinta", visto["después"], True)
        estado["boton"] = False
        ventana(CON_LLAVERO, lambda root: visto.update(
            estado=str(botones(root)["Abrir llavero"].cget("state"))))
        c("  sin KeePassXC, el botón apagado", visto["estado"], "disabled")
        ventana(UNA, lambda root: visto.update(sin="Abrir llavero" in botones(root)))
        c("sin llavero, ni línea ni botón", visto["sin"], False)

        # «Expulsar» sin VeraCrypt: sale con llavero, lo cierra antes y dice que
        # ya se puede quitar. Si KeePassXC sigue abierto, no se cierra nada.
        from tkinter import messagebox
        reales_mb = (messagebox.askokcancel, messagebox.showinfo)
        dichos: list = []
        cerrados: list = []
        messagebox.askokcancel = lambda *a, **k: True
        messagebox.showinfo = lambda titulo, texto=None, **k: dichos.append(texto)
        estado["boton"] = True
        try:
            for listo in (False, True):
                tk_llavero.cerrar = lambda root, cfg, listo=listo: (
                    cerrados.append(cfg.llavero["base"]), listo)[1]
                ventana(CON_LLAVERO, lambda root: (
                    visto.update(expulsar="Expulsar" in botones(root)),
                    botones(root)["Expulsar"].invoke()))
                c(f"con llavero y sin VeraCrypt hay «Expulsar» (KeePassXC "
                  f"{'cerrado' if listo else 'abierto'})", visto["expulsar"], True)
            c("  cierra el llavero antes, las dos veces", cerrados,
              ["personal.kdbx", "personal.kdbx"])
            c("  y solo si quedó libre dice que ya se puede quitar", dichos,
              [f"Ya puedes quitarla {uitk.QUITAR_UNIDAD}."])
        finally:
            messagebox.askokcancel, messagebox.showinfo = reales_mb
            tk_llavero.cerrar = REAL_CERRAR

        # En una raíz de este equipo no se quita nada: sin «Expulsar». Y si es
        # cifrada, «Bloquear» cierra antes el llavero; si KeePassXC sigue
        # abierto, no se le pide nada al agente.
        reales_eq = (model.es_equipo, cifrado.bloqueo, cifrado.pedir_bloqueo,
                     messagebox.askokcancel)
        pedidos: list = []
        cerrados.clear()
        model.es_equipo = lambda app_dir=None: True
        messagebox.askokcancel = lambda *a, **k: True
        try:
            ventana(CON_LLAVERO, lambda root: visto.update(
                expulsar="Expulsar" in botones(root), bloquear="Bloquear" in botones(root)))
            c("en una raíz del equipo con llavero no hay «Expulsar»",
              (visto["expulsar"], visto["bloquear"]), (False, False))
            cifrado.bloqueo = lambda: "e" * 32
            cifrado.pedir_bloqueo = lambda uid: pedidos.append(uid) or True
            for listo in (False, True):
                tk_llavero.cerrar = lambda root, cfg, listo=listo: (
                    cerrados.append(cfg.llavero["base"]), listo)[1]
                ventana(CON_LLAVERO, lambda root: botones(root)["Bloquear"].invoke())
            c("cifrada, «Bloquear» cierra antes el llavero, las dos veces", cerrados,
              ["personal.kdbx", "personal.kdbx"])
            c("  y solo con KeePassXC cerrado se lo pide al agente", pedidos, ["e" * 32])
        finally:
            (model.es_equipo, cifrado.bloqueo, cifrado.pedir_bloqueo,
             messagebox.askokcancel) = reales_eq
            tk_llavero.cerrar = REAL_CERRAR

        # «Ajustes → Llavero…»: al activarlo, la principal relee el config y
        # lanza la primera pasada del llavero.
        model.CONFIG_FILE.write_text(config_file.dumps({
            "defaults": {"remote": "nas"},
            "pair": [{"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas"}],
            "keychain": {"base": "personal.kdbx"}}), encoding="utf-8")
        tk_llavero.construir_ajustes = lambda panel, raw=None: (
            panel.devolver(tk_llavero.ACTIVADO), panel.cerrar())
        tk_doctor.mostrar = lambda dlg, parent=None: next(
            b for b in recorrer(dlg) if isinstance(b, ttk.Button)
            and b.cget("text") == "Llavero").invoke()
        lanzadas.clear()
        ventana(UNA, lambda root: botones(root)["Ajustes…"].invoke())
        c("activar el llavero desde «Ajustes» lanza su primera pasada",
          [cmd[-1] for cmd in lanzadas], [model.LLAVERO])
    finally:
        llavero_editor.linea, tk_llavero.abrir = REAL_LINEA, REAL_ABRIR
        tk_llavero.construir_ajustes, tk_doctor.mostrar = REAL_AJUSTES, REAL_DOCTOR_MOSTRAR


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
LLAVERO_LARGO = llavero_editor.Linea(
    "contraseñas-de-toda-la-familia.kdbx: la última pasada falló (ayer). Se vuelve a "
    "intentar al abrirlo y en cada guardado.", True, True)
"""La línea del llavero más larga que sale, en ámbar."""
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
    vertical, horizontal = visor.barras()
    medida["recortado"] = ((visor.interior.winfo_reqheight() > alto and not vertical)
                           or (visor.interior.winfo_reqwidth() > ancho and not horizontal))


try:
    for nombre, ancho, alto, escala in PANTALLAS:
        uitk.pantalla_util = lambda win, a=ancho, h=alto: (a, h)

        def con_escala(widget, e=escala):
            """Pone la escala a Tk antes de aplicar el tema."""
            widget.tk.call("tk", "scaling", e)
            REAL_APPLY(widget)

        theme.apply = con_escala
        llavero_editor.linea = lambda cfg: LLAVERO_LARGO
        # Con «Expulsar» en el pie, el tercer botón: el de un dispositivo que
        # vive en un contenedor VeraCrypt. No se pulsa, solo se mide.
        cifrado.expulsion = lambda **_k: Path("E:/Expulsar PRDRIVE.bat")
        with sandbox():
            medida: dict = {}
            ventana(DOCE, medir, resumen=watch.Resumen("desfasado", "daemon"))
            c(f"{nombre}: con «Expulsar» en el pie", medida.get("expulsar"), True)
            c(f"{nombre}: la ventana principal cabe", medida.get("cabe"), True)
            c(f"{nombre}: y no queda recortada", medida.get("recortado"), False)
        # Y con el agente como servicio y las dos pausas a la vez: la línea más
        # larga del agente (cuatro renglones) y «Reanudar» en el pie (#64).
        with sandbox():
            medida = {}
            ventana(DOCE, medir, resumen=watch.Resumen("agente", "daemon", True, True, True))
            c(f"{nombre}: con el agente en pausa, cabe",
              (medida.get("expulsar"), medida.get("cabe")), (True, True))
            c(f"{nombre}:   y no queda recortada", medida.get("recortado"), False)
finally:
    uitk.pantalla_util, theme.apply = REAL_UTIL, REAL_APPLY
    cifrado.expulsion = lambda **_k: None
    llavero_editor.linea = REAL_LINEA

c("cada lectura de la ventana se hizo sin fallos", [f for f in lecturas if f], [])
sys.exit(c.report())
