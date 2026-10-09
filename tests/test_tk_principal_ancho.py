#!/usr/bin/env python3
"""La ventana principal no se ensancha al llegar su lectura: recuerda su ancho.

La principal se pinta antes de leer el dispositivo y la lectura trae líneas más
anchas que el primer pintado (la del arranque automático, «Expulsar»…). En
Windows cada widget es una ventana del sistema: ensancharse al llegar movía
cada fila de la lista, cientos de milisegundos con 50 parejas. Así que la
ventana recuerda en `state/ventana.json` el ancho que tuvo con la lectura y lo
reserva desde el primer pintado. Aquí, con la ventana de verdad
(`ui.tk.main_window`, con el bucle de eventos sustituido por una sonda):

- la primera vez se ensancha al llegar, como siempre, y lo apunta una vez;
- la segunda ya se pinta con ese ancho y al llegar la lectura no se mueve ni
  cambia de ancho ninguna fila, y no escribe nada;
- un ancho recordado mayor que el de ahora acaba en el de ahora (como si no
  hubiera nada recordado), y se reescribe;
- el de otra clave (otra escala, otro sistema) no se usa ni se borra;
- si no se puede escribir, la ventana sigue igual; una lectura que falla
  entera no se recuerda;
- una lectura posterior en la misma sesión sigue la misma regla.

Y lo que la ventana hace cuando cambia de tamaño sin lectura (quitar el aviso
de arranque): `Visor.encajar()` dice si ha cambiado, quepa o no en la
pantalla, y entonces la ventana se vuelve a centrar.
"""

import json
import sys
import time
from pathlib import Path

from _harness import Checks, mkcfg, sandbox, tmpdir

c = Checks("ancho recordado de la ventana principal")

import ui  # noqa: E402  — antes que tkinter: en Linux trae su Tk con Xft
from ui import theme  # noqa: E402

try:
    import tkinter as tk
    theme.nitidez()
    tk.Tk().destroy()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from common import store, update  # noqa: E402
from ui import cifrado, instantanea, prefs, segundo_plano, tk_watch, watch  # noqa: E402
from ui import tk as uitk  # noqa: E402

REAL_MAINLOOP, REAL_LANZAR = tk.Tk.mainloop, segundo_plano.lanzar
ESCRIBIR = {"real": store.write_json}
"""Lo que escribe de verdad: un caso lo cambia por un dispositivo que no se deja."""
ESCRITAS = {"n": 0}
"""Cuántas veces se ha intentado escribir `state/ventana.json` en todo el test."""


def escribir_contando(ruta, datos):
    """Escribe con `ESCRIBIR["real"]` y cuenta las de `ventana.json`."""
    if Path(ruta).name == "ventana.json":
        ESCRITAS["n"] += 1
    return ESCRIBIR["real"](ruta, datos)


store.write_json = escribir_contando
update.pending = lambda root=None: None
update.check = lambda force=False: (None, None)
for _m in (ui, uitk):
    _m.pair_status_notes = lambda cfg: {}
# Lo que trae la lectura y no el primer pintado: «Expulsar» en el pie (lo más
# ancho) y la línea del arranque automático.
LEIDO = {"script": Path("E:/Expulsar PRDRIVE.bat")}
cifrado.expulsion = lambda **_k: LEIDO["script"]
watch.resumen = lambda: watch.Resumen("sin_instalar")
tk_watch.open_dialog = lambda root: None
prefs.PREFS = tmpdir("prdrive-principal-ancho-") / "ui_prefs.json"
uitk.output_window = lambda titulo, cmd, **k: None
CFG = mkcfg([f"pareja{i:02d}" for i in range(5)], {"pairs": ["pareja00"]})
FILAS = ("TCheckbutton", "TLabel", "TSeparator")
"""Las clases de lo que hay en cada fila de la lista: casilla, modo, hora y filete."""


def todos(w):
    """Recorre los widgets que cuelgan de `w`, en profundidad."""
    for hijo in w.winfo_children():
        yield hijo
        yield from todos(hijo)


def geometria(root) -> dict:
    """La geometría `(x, y, ancho, alto)` de cada widget a la vista, por nombre.

    Solo los mapeados: uno quitado (una barra del `Visor` que ya no hace
    falta) conserva la geometría de la última vez que se colocó.
    """
    return {str(w): (w.winfo_x(), w.winfo_y(), w.winfo_width(), w.winfo_height())
            for w in todos(root) if w.winfo_ismapped()}


def filas(root) -> dict:
    """`(x, ancho)` de cada widget de las filas de la lista, por nombre."""
    casilla = next(w for w in todos(root) if w.winfo_class() == "TCheckbutton")
    return {str(w): (w.winfo_x(), w.winfo_width()) for w in casilla.master.winfo_children()
            if w.winfo_class() in FILAS}


def contenido(root):
    """El marco donde se dibuja la principal (`cuerpo_visible`)."""
    return root.visor.interior.winfo_children()[0]


def quieta(root) -> None:
    """Mueve el bucle hasta que la ventana mide lo que pide (como mucho 2 s).

    El tamaño de verdad de una ventana de arriba llega con un evento del
    servidor gráfico, no en `update_idletasks()`.
    """
    limite = time.monotonic() + 2.0
    while True:
        root.update()
        if root.winfo_width() == root.winfo_reqwidth() or time.monotonic() > limite:
            return
        time.sleep(0.005)


def leida(root) -> None:
    """Acaba la lectura que espera la ventana y la deja aplicarse, como el sondeo."""
    root.instantanea.correr()
    root.sondeo_instantanea._mirar()
    quieta(root)


def ancho_guardado() -> dict:
    """Lo que hay en `state/ventana.json`, `{}` si nada."""
    try:
        return json.loads(prefs.ruta_ventana().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def abrir(cfg=CFG, aviso=None) -> dict:
    """Abre la principal, mira el primer pintado, deja llegar la lectura y la vuelve a mirar.

    La lectura no termina hasta que la sonda la acaba a mano, y lo que la
    ventana programa para después (mirar versión y conflictos, precargar) se
    cancela antes: nada llega fuera de su sitio.

    Returns:
        Lo visto: `ancho_antes`/`ancho_despues` (la ventana), `filas_antes`/
        `filas_despues`, `geometria` (al final), `natural` (lo que pide el
        contenido al final), `clave`, `escrituras` (de `ventana.json`) y `lista`.
    """
    visto: dict = {}
    escritas = ESCRITAS["n"]

    def conducir(root, n=0) -> None:
        """La sonda que sustituye al bucle de eventos."""
        try:
            root.update_idletasks()                  # lanza la lectura (after_idle)
            for pendiente in root.tk.splitlist(root.tk.call("after", "info")):
                root.after_cancel(pendiente)
            quieta(root)
            visto["clave"] = prefs.clave_ancho(str(tk.TkVersion),
                                               float(root.tk.call("tk", "scaling")))
            visto["ancho_antes"] = root.winfo_width()
            visto["filas_antes"] = filas(root)
            leida(root)
            visto["lista"] = root.instantanea_lista
            visto["ancho_despues"] = root.winfo_width()
            visto["filas_despues"] = filas(root)
            visto["geometria"] = geometria(root)
            visto["natural"] = contenido(root).winfo_reqwidth()
            visto["expulsar"] = any(str(w.cget("text")) == "Expulsar" for w in todos(root)
                                    if w.winfo_class() == "TButton" and w.winfo_manager())
            visto["escrituras"] = ESCRITAS["n"] - escritas
            if visto.get("despues"):
                visto["despues"](root)
        finally:
            try:
                for pendiente in root.tk.splitlist(root.tk.call("after", "info")):
                    root.after_cancel(pendiente)
                root.destroy()
            except tk.TclError:
                pass

    visto["despues"] = ABRIR.pop("despues", None)
    segundo_plano.lanzar = segundo_plano.Encargo
    tk.Tk.mainloop = conducir
    try:
        uitk.main_window(cfg, aviso)
    finally:
        tk.Tk.mainloop, segundo_plano.lanzar = REAL_MAINLOOP, REAL_LANZAR
    return visto


ABRIR: dict = {}
"""Lo que `abrir()` hace además con la ventana ya leída (`despues`), una vez."""


# 1. la primera vez: se ensancha al llegar, como siempre, y apunta el ancho
with sandbox():
    primera = abrir()
    segunda = abrir()
    c("la primera vez se aplica la lectura", primera["lista"], True)
    c("  con «Expulsar» en el pie, que es lo que la ensancha", primera["expulsar"], True)
    c("  y se ensancha al llegar, como siempre (sin nada recordado)",
      primera["ancho_despues"] > primera["ancho_antes"], True)
    c("  apunta el ancho que pide su contenido, una sola vez",
      (ancho_guardado(), primera["escrituras"]),
      ({"ancho": {primera["clave"]: primera["natural"]}}, 1))

    # 2. la segunda vez ya se pinta con ese ancho, y la lectura no lo cambia
    c("la segunda vez se pinta ya con el ancho de la primera, antes de leer",
      segunda["ancho_antes"], primera["ancho_despues"])
    c("  al llegar la lectura la ventana no cambia de ancho",
      segunda["ancho_despues"], segunda["ancho_antes"])
    c("  ninguna casilla, modo, hora ni filete de las filas se mueve ni cambia de ancho",
      {k: v for k, v in segunda["filas_despues"].items() if k in segunda["filas_antes"]},
      segunda["filas_antes"])
    c("  (las filas están: cinco casillas, sus etiquetas y cuatro filetes)",
      len(segunda["filas_antes"]), 5 * 3 + 4)
    c("  y queda igual que la primera vez", segunda["geometria"], primera["geometria"])
    c("  y no escribe nada: el ancho no ha cambiado",
      (segunda["escrituras"], ancho_guardado()), (0, {"ancho": {primera["clave"]: primera["natural"]}}))

# 3. un ancho recordado mayor que el de ahora: acaba en el de ahora, y se reescribe
with sandbox():
    prefs.recordar_ancho(primera["clave"], primera["natural"] + 120)
    ancha = abrir()
    c("un ancho recordado mayor se reserva en el primer pintado",
      ancha["ancho_antes"], primera["ancho_despues"] + 120)
    c("  al llegar la lectura la ventana queda a su ancho, como sin nada recordado",
      ancha["ancho_despues"], primera["ancho_despues"])
    c("  con todo en el mismo sitio que entonces", ancha["geometria"], primera["geometria"])
    c("  y el ancho se reescribe, una vez",
      (ancho_guardado(), ancha["escrituras"]),
      ({"ancho": {primera["clave"]: primera["natural"]}}, 1))

# 3b. y uno menor: crece una vez hasta el suyo
with sandbox():
    prefs.recordar_ancho(primera["clave"], primera["natural"] - 60)
    estrecha = abrir()
    c("un ancho recordado menor: al llegar crece hasta el suyo",
      (estrecha["ancho_antes"] < primera["ancho_despues"], estrecha["ancho_despues"]),
      (True, primera["ancho_despues"]))
    c("  con todo en el mismo sitio que sin nada recordado",
      estrecha["geometria"], primera["geometria"])
    c("  y se reescribe", (ancho_guardado(), estrecha["escrituras"]),
      ({"ancho": {primera["clave"]: primera["natural"]}}, 1))

# 4. el de otra clave (otra escala, otro sistema) no se usa ni se pierde
with sandbox():
    prefs.recordar_ancho("otro:9.9:2.000", primera["natural"] + 300)
    otra = abrir()
    c("el ancho de otra clave no se reserva", otra["ancho_antes"], primera["ancho_antes"])
    c("  y al apuntar el suyo se conserva",
      ancho_guardado(), {"ancho": {"otro:9.9:2.000": primera["natural"] + 300,
                                   primera["clave"]: primera["natural"]}})

# 5. si el dispositivo no se deja escribir, no pasa nada
with sandbox():
    real = ESCRIBIR["real"]
    ESCRIBIR["real"] = lambda ruta, datos: (False if Path(ruta).name == "ventana.json"
                                            else real(ruta, datos))
    try:
        sin_escribir = abrir()
        otra_vez = abrir()
    finally:
        ESCRIBIR["real"] = real
    c("sin poder escribir el ancho, la lectura se aplica igual",
      (sin_escribir["lista"], sin_escribir["ancho_despues"]),
      (True, primera["ancho_despues"]))
    c("  no queda nada recordado", prefs.ruta_ventana().exists(), False)
    c("  y la vez siguiente se ensancha al llegar, como la primera",
      (otra_vez["ancho_antes"], otra_vez["ancho_despues"]),
      (primera["ancho_antes"], primera["ancho_despues"]))

# 5b. una lectura que falla entera no se recuerda: sin nada leído la ventana es más
# estrecha que la de siempre, y la vez siguiente se ensancharía al llegar
with sandbox():
    prefs.recordar_ancho(primera["clave"], primera["natural"])
    real_leer = instantanea.leer

    def leer_roto(config, **_k):
        """Hace de una lectura cuyo hilo falla."""
        raise OSError("la unidad no contesta")

    instantanea.leer = leer_roto
    try:
        fallida = abrir()
    finally:
        instantanea.leer = real_leer
    c("una lectura que falla se aplica vacía y la ventana queda a su ancho, más estrecha",
      (fallida["lista"], fallida["expulsar"],
       fallida["ancho_despues"] < primera["ancho_despues"]), (True, False, True))
    c("  y ese ancho no se recuerda", (ancho_guardado(), fallida["escrituras"]),
      ({"ancho": {primera["clave"]: primera["natural"]}}, 0))

# 6. una lectura posterior en la misma sesión sigue la misma regla
with sandbox():
    LEIDO["script"] = None
    try:
        sin_expulsar = abrir()                       # lo que sería abrirla sin «Expulsar»
    finally:
        LEIDO["script"] = Path("E:/Expulsar PRDRIVE.bat")
with sandbox():
    visto: dict = {}

    def releer_sin_expulsar(root) -> None:
        """Quita «Expulsar» de lo que se lee, vuelve a leer (botón del arranque) y mira."""
        LEIDO["script"] = None
        antes = ESCRITAS["n"]
        try:
            boton = next(w for w in todos(root) if w.winfo_class() == "TButton"
                         and str(w.cget("text")) == "Configurar…")
            boton.invoke()                           # al volver de esa pantalla, lee otra vez
            leida(root)
        finally:
            LEIDO["script"] = Path("E:/Expulsar PRDRIVE.bat")
        visto["lista"] = root.instantanea_lista
        visto["ancho"] = root.winfo_width()
        visto["guardado"] = ancho_guardado()
        visto["escrituras"] = ESCRITAS["n"] - antes
        visto["geometria"] = geometria(root)

    prefs.recordar_ancho(primera["clave"], primera["natural"])
    ABRIR["despues"] = releer_sin_expulsar
    tras = abrir()
    c("con el ancho recordado, la primera lectura no lo cambia ni lo escribe",
      (tras["ancho_antes"], tras["ancho_despues"], tras["escrituras"]),
      (primera["ancho_despues"], primera["ancho_despues"], 0))
    c("una lectura después, que pide menos ancho, se aplica", visto["lista"], True)
    c("  y la ventana queda a su ancho", visto["ancho"], sin_expulsar["ancho_despues"])
    c("  (que es otro: sin «Expulsar» el pie es más estrecho)",
      sin_expulsar["natural"] < primera["natural"], True)
    c("  con todo en el mismo sitio que si se hubiera abierto así",
      {k: v for k, v in visto["geometria"].items() if k in sin_expulsar["geometria"]},
      sin_expulsar["geometria"])
    c("  y ese ancho se recuerda, una vez",
      (visto["guardado"], visto["escrituras"]),
      ({"ancho": {primera["clave"]: sin_expulsar["natural"]}}, 1))

# 7. quitar el aviso de arranque la achica, y entonces se vuelve a centrar
with sandbox():
    centrados: list = []
    real_centrar = uitk.centrar
    visto = {}

    def centrar_apuntando(win, parent=None) -> None:
        """Apunta cada vez que se centra la principal."""
        centrados.append(win.winfo_reqheight())
        real_centrar(win, parent)

    def descartar(root) -> None:
        """Pulsa «Descartar» con la lectura ya aplicada y mira si se centra."""
        centrados.clear()
        boton = next(w for w in todos(root) if w.winfo_class() == "TButton"
                     and str(w.cget("text")) == "Descartar")
        alto = root.winfo_reqheight()
        boton.invoke()
        visto["achica"] = root.winfo_reqheight() < alto
        visto["centrados"] = list(centrados)
        visto["alto"] = root.winfo_reqheight()

    ABRIR["despues"] = descartar
    uitk.centrar = centrar_apuntando
    try:
        abrir(aviso="Servicio anterior (pid 4242) detenido.")
    finally:
        uitk.centrar = real_centrar
    c("quitar el aviso de arranque achica la ventana", visto["achica"], True)
    c("  y la vuelve a centrar, una vez, con su tamaño nuevo",
      visto["centrados"], [visto["alto"]])

# 8. `Visor.encajar()` dice si el recuadro ha cambiado de tamaño, quepa o no
raiz = tk.Tk()
raiz.withdraw()
theme.apply(raiz)
top = tk.Toplevel(raiz)
top.withdraw()
visor = uitk.Visor(top)
visor.marco.grid(row=0, column=0, sticky="nsew")
caja = tk.Frame(visor.interior, width=200, height=100)
caja.grid(row=0, column=0)
c("encajar un contenido nuevo dice que el recuadro ha cambiado", visor.encajar(top), True)
c("  y encajarlo otra vez, que no", visor.encajar(top), False)
caja.configure(width=260)
c("un contenido más ancho que cabe en la pantalla: ha cambiado", visor.encajar(top), True)
caja.configure(height=60)
c("  uno más bajo, también", visor.encajar(top), True)
caja.configure(height=100000)
c("  y uno que no cabe, también (el recuadro crece hasta el tope)",
  visor.encajar(top), True)
c("  y otra vez el mismo, que no", visor.encajar(top), False)
raiz.destroy()

sys.exit(c.report())
