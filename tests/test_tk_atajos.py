#!/usr/bin/env python3
"""La ventana que graba los atajos de teclado (`ui/tk_atajos.py`), con Tk de verdad.

Se abre como la abre el agente (`abrir()`), con lo que cuenta su `estado.json`
y su buzón sustituidos, y se maneja con eventos de teclado generados:
- empieza con los atajos guardados, y el que no se pudo poner dice por qué;
- «Grabar» y la combinación la pone; sin Ctrl, Alt ni el logotipo se dice y
  sigue grabando; Esc lo deja como estaba; «Quitar» la deja sin atajo;
- grabando, la columna de la combinación no hace crecer la ventana a lo ancho
  (que no cambia de tamaño) y nada sale con barra;
- «Guardar» pide al agente lo de la ventana con su `vez` y espera: si rechaza
  alguno, su fila dice por qué y la ventana sigue; si no, se cierra; si se
  cancela en el escritorio, no se ha guardado nada y la ventana sigue con lo
  suyo; si tarda, lo dice y sigue esperando (y la respuesta que llega tarde
  vale); si no se puede pedir, también lo dice;
- con `motivo`, solo dice por qué no se puede, y «Cerrar».

Sin Tk o sin pantalla se salta.
"""

from __future__ import annotations

import sys

from _harness import Checks

c = Checks("la ventana que graba los atajos de teclado")

try:
    import ui  # noqa: F401  (antes que tkinter: el Tk con Xft del runtime)
    import tkinter as tk
    prueba = tk.Tk()
    prueba.destroy()
except Exception as e:                                   # sin Tk o sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from ui import atajos, tk_atajos  # noqa: E402

YA = atajos.YA_LA_USA
ESTADO: dict = {}
PEDIDAS: list = []
CONTESTAR: list = []
"""Lo que contesta el «agente» a cada «Guardar» (`rechazados`, `guardados`), o `None` para no contestar."""
PUEDE_PEDIR = [True]


def pedir(p):
    """El buzón de mentira: apunta la petición y deja la respuesta en el estado."""
    if not PUEDE_PEDIR[0]:
        return False
    PEDIDAS.append(p)
    respuesta = CONTESTAR.pop(0) if CONTESTAR else {"rechazados": {}}
    if respuesta is not None:
        ESTADO["respuesta"] = {"vez": p["vez"], **respuesta}
    return True


atajos.leer_estado = lambda: ESTADO
atajos.pedir = pedir
ORIGINAL = tk.Tk.mainloop


def todos(w):
    """Todos los widgets que cuelgan de `w`."""
    salida = []
    for h in w.winfo_children():
        salida.append(h)
        salida += todos(h)
    return salida


def con_texto(root, texto, clase=None):
    """Los widgets que dicen `texto` (y son de esa clase de Tk, si se da)."""
    salida = []
    for w in todos(root):
        try:
            if str(w.cget("text")) == texto and (clase is None or w.winfo_class() == clase):
                salida.append(w)
        except tk.TclError:
            pass
    return salida


def textos(root):
    """Lo que dicen las etiquetas visibles, en orden."""
    salida = []
    for w in todos(root):
        if w.winfo_class() == "TLabel" and w.winfo_manager() and str(w.cget("text")):
            salida.append(str(w.cget("text")))
    return salida


def teclas(root, *pulsadas):
    """Genera las teclas como si se pulsaran: `(keysym, keycode, state)`, y las suelta."""
    for keysym, codigo, estado in pulsadas:
        root.event_generate("<KeyPress>", keysym=keysym, keycode=codigo, state=estado,
                            when="now")
    for keysym, codigo, _estado in reversed(pulsadas):
        root.event_generate("<KeyRelease>", keysym=keysym, keycode=codigo, when="now")
    root.update()


def abrir(guion, motivo="", espera_s=None):
    """Abre la ventana y corre `guion(root, apunta)` en su bucle; devuelve lo apuntado."""
    apuntado: dict = {}

    def bucle(root):
        """El bucle de la ventana, con el guion al empezar."""
        def correr():
            try:
                guion(root, apuntado)
            except Exception as e:                       # noqa: BLE001
                apuntado["error"] = repr(e)
                root.destroy()
        root.after(200, correr)
        ORIGINAL(root)

    tk.Tk.mainloop = bucle
    if espera_s is not None:
        antes = atajos.ESPERA
        atajos.ESPERA = espera_s
    try:
        apuntado["rc"] = tk_atajos.abrir(motivo)
    finally:
        tk.Tk.mainloop = ORIGINAL
        if espera_s is not None:
            atajos.ESPERA = antes
    return apuntado


CTRL, SHIFT = ("Control_L", 37, 0), ("Shift_L", 50, 0)
WIN = tk_atajos.IS_WIN
S = ("S", 0x53, 0x4 | 0x1) if WIN else ("S", 39, 0x4 | 0x1)
P = ("P", 0x50, 0x4 | 0x1) if WIN else ("P", 33, 0x4 | 0x1)
SOLO_SHIFT_P = ("P", 0x50, 0x1) if WIN else ("P", 33, 0x1)


# --- empezar, grabar, quitar
ESTADO.clear()
ESTADO.update({"mecanismo": atajos.X11, "acciones": {
    atajos.SINCRONIZAR: {"combo": "ctrl+alt+s", "error": ""},
    atajos.VENTANA: {"combo": "", "error": YA}}})


def grabar_y_guardar(root, apunta):
    """Mira lo de entrada, graba, se equivoca, cancela, quita y guarda."""
    apunta["inicio"] = textos(root)
    apunta["guardar_inicio"] = con_texto(root, "Guardar", "TButton")[0].instate(["disabled"])
    ancho = root.winfo_width()
    con_texto(root, "Grabar", "TButton")[1].invoke()                # «Pausar o reanudar»
    root.update()
    apunta["grabando"] = textos(root)
    apunta["botones_grabando"] = [b.instate(["disabled"])
                                  for b in con_texto(root, "Grabar", "TButton")]
    apunta["ancho_igual"] = root.winfo_width() == ancho
    apunta["sin_barras"] = root.visor.barras() == (False, False)
    teclas(root, SHIFT, SOLO_SHIFT_P)
    apunta["mal"] = textos(root)
    teclas(root, ("Escape", 9 if not WIN else 0x1B, 0))
    apunta["tras_esc"] = textos(root)
    con_texto(root, "Grabar", "TButton")[1].invoke()
    root.update()
    teclas(root, CTRL, SHIFT, P)
    apunta["grabada"] = textos(root)
    con_texto(root, "Quitar", "TButton")[0].invoke()                # «Sincronizar ahora»
    root.update()
    apunta["quitada"] = textos(root)
    CONTESTAR[:] = [{"rechazados": {atajos.PAUSAR: YA}}]
    con_texto(root, "Guardar", "TButton")[0].invoke()

    def despues():
        apunta["veredicto"] = textos(root)
        apunta["sigue_abierta"] = True
        apunta["sin_barras_tras"] = root.visor.barras() == (False, False)
        con_texto(root, "Grabar", "TButton")[0].invoke()            # «Sincronizar ahora»
        root.update()
        teclas(root, CTRL, SHIFT, S)
        CONTESTAR[:] = [{"rechazados": {}}]
        con_texto(root, "Guardar", "TButton")[0].invoke()
    root.after(600, despues)


r = abrir(grabar_y_guardar)
c("se abre y se maneja sin errores", r.get("error"), None)
c("empieza con lo guardado, y el que no se pudo poner dice por qué",
  ("Ctrl+Alt+S" in r["inicio"], any(YA in t for t in r["inicio"])), (True, True))
c("  sin cambios, «Guardar» está apagado", r["guardar_inicio"], True)
c("grabando: la fila lo dice, y cómo dejarlo",
  ("Pulsa la combinación…" in r["grabando"], atajos.ESC in r["grabando"]), (True, True))
c("  los demás «Grabar» se apagan", set(r["botones_grabando"]), {True})
c("  y la ventana no cambia de ancho ni sale con barras", (r["ancho_igual"], r["sin_barras"]),
  (True, True))
c("Mayús+P no vale: se dice y sigue grabando",
  (any("Ctrl, Alt" in t for t in r["mal"]), "Pulsa la combinación…" in r["mal"]),
  (True, True))
c("Esc lo deja como estaba (solo una acción tiene atajo)",
  ("Pulsa la combinación…" in r["tras_esc"], r["tras_esc"].count(atajos.SIN_ATAJO)),
  (False, len(atajos.ACCIONES) - 1))
c("Ctrl+Mayús+P la pone", "Ctrl+Mayús+P" in r["grabada"], True)
c("«Quitar» la deja sin atajo", "Ctrl+Alt+S" in r["quitada"], False)
c("«Guardar» pide lo de la ventana, con su vez",
  (PEDIDAS[0]["pide"], PEDIDAS[0]["atajos"], bool(PEDIDAS[0]["vez"])),
  ("atajos", {atajos.PAUSAR: "ctrl+shift+p"}, True))
c("  el rechazado se queda sin atajo y su fila dice por qué; la ventana sigue",
  ("Ctrl+Mayús+P" in r["veredicto"], any("Ctrl+Mayús+P no se ha podido poner" in t
                                         for t in r["veredicto"]),
   "No se han podido poner todos" in r["veredicto"], r["sigue_abierta"]),
  (False, True, True, True))
c("  y sin barras", r["sin_barras_tras"], True)
c("otro «Guardar» que el agente acepta entero cierra la ventana",
  (len(PEDIDAS), PEDIDAS[-1]["atajos"], r["rc"]),
  (2, {atajos.SINCRONIZAR: "ctrl+shift+s"}, 0))

# --- el agente que tarda, el escritorio que cancela y el buzón que no se deja
PEDIDAS.clear()
ESTADO.pop("respuesta", None)


def tarda(root, apunta):
    """Graba, guarda y espera a un agente que tarda en contestar, y al final contesta."""
    con_texto(root, "Grabar", "TButton")[0].invoke()
    root.update()
    teclas(root, CTRL, SHIFT, S)
    CONTESTAR[:] = [None]
    con_texto(root, "Guardar", "TButton")[0].invoke()
    apunta["esperando"] = textos(root)

    def despues():
        apunta["tarde"] = textos(root)
        apunta["cerrar"] = bool(con_texto(root, "Cerrar", "TButton"))
        apunta["guardar_apagado"] = con_texto(root, "Guardar", "TButton")[0].instate(
            ["disabled"])
        ESTADO["respuesta"] = {"vez": PEDIDAS[-1]["vez"], "rechazados": {}}
    root.after(1200, despues)


r = abrir(tarda, espera_s=0.5)
c("mientras espera, lo dice", "Comprobando con el sistema…" in r["esperando"], True)
c("  si tarda, dice que el agente ya tiene el encargo, y sigue esperando",
  (atajos.TARDA.split("\n")[0] in r["tarde"], r["cerrar"], r["guardar_apagado"]),
  (True, True, True))
c("  y la respuesta que llega tarde vale: todo puesto, se cierra", (r.get("error"), r["rc"]),
  (None, 0))

PEDIDAS.clear()
ESTADO.pop("respuesta", None)


def cancelada(root, apunta):
    """Graba y guarda; el escritorio lo cancela; y luego el buzón no se deja."""
    con_texto(root, "Grabar", "TButton")[0].invoke()
    root.update()
    teclas(root, CTRL, SHIFT, S)
    CONTESTAR[:] = [{"rechazados": {atajos.SINCRONIZAR: atajos.CANCELADA_PORTAL},
                     "guardados": {atajos.SINCRONIZAR: "ctrl+alt+s"}}]
    con_texto(root, "Guardar", "TButton")[0].invoke()

    def despues():
        apunta["cancelada"] = textos(root)
        apunta["guardar_encendido"] = not con_texto(root, "Guardar", "TButton")[0].instate(
            ["disabled"])
        PUEDE_PEDIR[0] = False
        con_texto(root, "Guardar", "TButton")[0].invoke()
        apunta["sin_buzon"] = textos(root)
        PUEDE_PEDIR[0] = True
        root.destroy()
    root.after(600, despues)


r = abrir(cancelada)
c("cancelado en el escritorio: dice que no se ha guardado nada y sigue con lo suyo",
  (any("No se ha guardado nada" in t for t in r["cancelada"]), "Ctrl+Mayús+S" in r["cancelada"],
   r["guardar_encendido"]), (True, True, True))
c("  si no se puede dejar la petición, también lo dice",
  atajos.SIN_ENCARGO.split("\n")[0] in "\n".join(r["sin_buzon"]), True)

# --- con el portal, avisa de su ventana
ESTADO["mecanismo"] = atajos.PORTAL
r = abrir(lambda root, apunta: (apunta.update(t=textos(root)), root.destroy()))
c("con el portal, dice que el escritorio pedirá confirmarlos",
  tk_atajos.PISTA_PORTAL in r["t"], True)

# --- sin forma de ponerlos
r = abrir(lambda root, apunta: (apunta.update(t=textos(root), cerrar=bool(
    con_texto(root, "Cerrar", "TButton")), grabar=bool(con_texto(root, "Grabar", "TButton"))),
    con_texto(root, "Cerrar", "TButton")[0].invoke()), motivo=atajos.SIN_PORTAL)
c("con motivo, solo dice por qué y se cierra", (
    "No se pueden usar en este equipo" in r["t"],
    any("GlobalShortcuts" in t for t in r["t"]), r["grabar"], r["cerrar"], r["rc"]),
  (True, True, False, True, 0))

sys.exit(c.report())
