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

Lo mismo pasa en vertical con lo que la lectura pone ENCIMA de la lista (la
línea de «Reparación…»): empuja hacia abajo el rótulo, la tarjeta y todas las
filas, y en Windows cada una es una ventana del sistema. Así que también
recuerda en `state/ventana.json` cuánto ocupa esa franja y lo reserva desde el
primer pintado hasta que llega la lectura:

- la primera vez la lista baja al llegar la línea, como siempre, y apunta el alto;
- la segunda, con el dispositivo como estaba, nada de lo que hay debajo se mueve
  al llegar, ni la ventana crece por ese lado, y no escribe nada;
- un alto recordado menor o mayor que el de ahora deja la lista donde estaría sin
  nada recordado, con un solo movimiento, y se reescribe; si no hay nada encima, 0;
- un bloque que ya estaba en el primer pintado (el aviso de arranque) tampoco se mueve;
- una lectura que falla entera no se recuerda; una posterior suelta la reserva.
"""

import dataclasses
import json
import sys
import time
from contextlib import contextmanager
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
from ui import (cifrado, instantanea, llavero_editor, prefs, segundo_plano,  # noqa: E402
                tk_principal, tk_watch, watch)
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
VIGILANTE = watch.Resumen("sin_instalar")
"""Lo que hace el arranque automático del equipo por defecto: nada, y la línea lo dice."""
LEIDO = {"script": Path("E:/Expulsar PRDRIVE.bat"), "cuenta": 0, "vigilante": VIGILANTE,
         "llavero": None}
"""Lo que trae la lectura: el script de «Expulsar», cuántas cosas hay que revisar, qué hace el
arranque automático (su línea, y con un vigilante que atiende este dispositivo, la frase de la
pausa) y la línea del llavero."""
cifrado.expulsion = lambda **_k: LEIDO["script"]
LEER_REAL = instantanea.leer


def leer_con_cuenta(config, **kw):
    """Lee de verdad y le pone lo que dice `LEIDO`: las cosas por revisar y la línea del llavero.

    La revisión de verdad de este dispositivo de muestra (cinco parejas sin sincronizar)
    encuentra cosas, y con alguna la lectura trae la línea de «Reparación…» encima de la
    lista: aquí lo decide cada caso, y por defecto no hay ninguna. El llavero, igual: este
    dispositivo no lo lleva.
    """
    return dataclasses.replace(LEER_REAL(config, **kw), cuenta=LEIDO["cuenta"],
                               llavero=LEIDO["llavero"])


instantanea.leer = leer_con_cuenta
watch.resumen = lambda: LEIDO["vigilante"]
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


def fila_de(root, nombre: str) -> list:
    """Los widgets que el marco de la principal tiene en la fila `nombre` de `FILAS`."""
    return contenido(root).grid_slaves(row=tk_principal.FILAS[nombre])


def sitio(root, widget) -> int:
    """Dónde empieza `widget` en vertical, contado desde lo alto del marco de la principal.

    Relativo y no de pantalla: de una apertura a otra la ventana puede salir centrada en
    otro sitio, y dentro de una, crecer.
    """
    return widget.winfo_rooty() - contenido(root).winfo_rooty()


def abajo(root) -> dict:
    """Dónde empieza todo lo que va debajo de lo que la lectura pone encima de la lista.

    El rótulo, la tarjeta, «Parejas…» y «Ajustes…», y lo que hay dentro de la tarjeta: las
    casillas, sus etiquetas y sus filetes. Es lo que se mueve entero si crece la franja de
    arriba.
    """
    sitios = {nombre: sitio(root, fila_de(root, nombre)[0])
              for nombre in ("rotulo", "tarjeta", "pantallas")}
    sitios.update({str(w): sitio(root, w) for w in todos(fila_de(root, "tarjeta")[0])
                   if w.winfo_ismapped()})
    return sitios


def movidos(antes: dict, despues: dict) -> list:
    """Los nombres de lo que está en los dos sitios y no en el mismo (`[]`: nada se movió)."""
    return sorted(k for k in antes if k in despues and antes[k] != despues[k])


def banda(root) -> int:
    """Lo que ocupan, con su margen, las filas de encima del rótulo (avisos y línea): píxeles."""
    marco = contenido(root)
    return marco.grid_bbox(0, tk_principal.FILAS["aviso"], 0,
                           tk_principal.FILAS["componentes"])[3]


def debajo(root) -> dict:
    """Dónde empieza todo lo que va debajo de la lista: «Parejas…», «Ajustes…» y el pie.

    Las dos filas y cada widget que cuelga de ellas (los botones de «Parejas…» y «Ajustes…»,
    «Sincronizar ahora», el del servicio, «Expulsar»). Es lo que se mueve si la franja de
    debajo crece o mengua.
    """
    sitios = {}
    for nombre in ("pantallas", "pie"):
        fila = fila_de(root, nombre)[0]
        sitios[nombre] = sitio(root, fila)
        sitios.update({str(w): sitio(root, w) for w in todos(fila) if w.winfo_ismapped()})
    return sitios


def banda_abajo(root) -> int:
    """Lo que ocupan, con su margen, las filas de debajo de la lista hasta el pie: píxeles.

    La línea del llavero, «Parejas…» y «Ajustes…» (que siempre están), la del arranque
    automático y la frase de la pausa.
    """
    marco = contenido(root)
    return marco.grid_bbox(0, tk_principal.FILAS["llavero"], 0,
                           tk_principal.FILAS["pausa"])[3]


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


def guardado(clave, ancho=None, arriba=None, abajo=None) -> dict:
    """Lo que debe haber en `state/ventana.json` con ese ancho y esos altos (los que se den)."""
    return {**({"ancho": {clave: ancho}} if ancho is not None else {}),
            **({"arriba": {clave: arriba}} if arriba is not None else {}),
            **({"abajo": {clave: abajo}} if abajo is not None else {})}


def abrir(cfg=CFG, aviso=None) -> dict:
    """Abre la principal, mira el primer pintado, deja llegar la lectura y la vuelve a mirar.

    La lectura no termina hasta que la sonda la acaba a mano, y lo que la
    ventana programa para después (mirar versión y conflictos, precargar) se
    cancela antes: nada llega fuera de su sitio.

    Returns:
        Lo visto: `ancho_antes`/`ancho_despues` y `alto_antes`/`alto_despues` (la
        ventana), `filas_antes`/`filas_despues`, `abajo_antes`/`abajo_despues` (dónde
        está lo que va debajo de la franja de arriba), `arriba_antes`/`arriba_despues`
        (lo que ocupa esa franja), `avisos_antes`/`avisos_despues`, `linea` (si la
        lectura puso la línea de «Reparación…»), `debajo_antes`/`debajo_despues` (dónde
        está lo que va debajo de la lista: «Parejas…» y el pie),
        `banda_abajo_antes`/`banda_abajo_despues` (lo que ocupa esa franja), `arranque`/
        `llavero` (si la lectura puso la línea del arranque automático o la del llavero),
        `geometria` (al final), `natural` (lo que pide el contenido al final), `clave`,
        `escrituras` (de `ventana.json`) y `lista`.
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
            visto["alto_antes"] = root.winfo_height()
            visto["filas_antes"] = filas(root)
            visto["abajo_antes"] = abajo(root)
            visto["arriba_antes"] = banda(root)
            visto["avisos_antes"] = [sitio(root, w) for w in fila_de(root, "aviso")]
            visto["debajo_antes"] = debajo(root)
            visto["banda_abajo_antes"] = banda_abajo(root)
            leida(root)
            visto["lista"] = root.instantanea_lista
            visto["ancho_despues"] = root.winfo_width()
            visto["alto_despues"] = root.winfo_height()
            visto["filas_despues"] = filas(root)
            visto["abajo_despues"] = abajo(root)
            visto["arriba_despues"] = banda(root)
            visto["avisos_despues"] = [sitio(root, w) for w in fila_de(root, "aviso")]
            visto["linea"] = bool(fila_de(root, "reparacion"))
            visto["debajo_despues"] = debajo(root)
            visto["banda_abajo_despues"] = banda_abajo(root)
            visto["arranque"] = bool(fila_de(root, "arranque"))
            visto["llavero"] = bool(fila_de(root, "llavero"))
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
    ABAJO = primera["banda_abajo_despues"]           # lo de debajo de la lista, ya con la línea
    c("  apunta el ancho que pide su contenido y lo que ocupa lo de debajo de la lista, una "
      "vez cada uno",
      (ancho_guardado(), primera["escrituras"]),
      (guardado(primera["clave"], primera["natural"], abajo=ABAJO), 2))

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
    c("  y no escribe nada: ni el ancho ni lo de debajo han cambiado",
      (segunda["escrituras"], ancho_guardado()),
      (0, guardado(primera["clave"], primera["natural"], abajo=ABAJO)))

# 3. un ancho recordado mayor que el de ahora: acaba en el de ahora, y se reescribe
with sandbox():
    prefs.recordar_ancho(primera["clave"], primera["natural"] + 120)
    ancha = abrir()
    c("un ancho recordado mayor se reserva en el primer pintado",
      ancha["ancho_antes"], primera["ancho_despues"] + 120)
    c("  al llegar la lectura la ventana queda a su ancho, como sin nada recordado",
      ancha["ancho_despues"], primera["ancho_despues"])
    c("  con todo en el mismo sitio que entonces", ancha["geometria"], primera["geometria"])
    c("  y el ancho se reescribe, una vez (y lo de debajo, que no estaba, se apunta)",
      (ancho_guardado(), ancha["escrituras"]),
      (guardado(primera["clave"], primera["natural"], abajo=ABAJO), 2))

# 3b. y uno menor: crece una vez hasta el suyo
with sandbox():
    prefs.recordar_ancho(primera["clave"], primera["natural"] - 60)
    estrecha = abrir()
    c("un ancho recordado menor: al llegar crece hasta el suyo",
      (estrecha["ancho_antes"] < primera["ancho_despues"], estrecha["ancho_despues"]),
      (True, primera["ancho_despues"]))
    c("  con todo en el mismo sitio que sin nada recordado",
      estrecha["geometria"], primera["geometria"])
    c("  y se reescribe (y lo de debajo, que no estaba, se apunta)",
      (ancho_guardado(), estrecha["escrituras"]),
      (guardado(primera["clave"], primera["natural"], abajo=ABAJO), 2))

# 4. el de otra clave (otra escala, otro sistema) no se usa ni se pierde
with sandbox():
    prefs.recordar_ancho("otro:9.9:2.000", primera["natural"] + 300)
    otra = abrir()
    c("el ancho de otra clave no se reserva", otra["ancho_antes"], primera["ancho_antes"])
    c("  y al apuntar el suyo se conserva",
      ancho_guardado(), {"ancho": {"otro:9.9:2.000": primera["natural"] + 300,
                                   primera["clave"]: primera["natural"]},
                         "abajo": {primera["clave"]: ABAJO}})

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
    prefs.recordar_abajo(primera["clave"], ABAJO)    # (que este caso trate solo del ancho)
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
      (guardado(primera["clave"], sin_expulsar["natural"], abajo=ABAJO), 1))

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

# 7b. lo que la lectura pone encima de la lista (la línea de «Reparación…») también se
# recuerda y se reserva desde el primer pintado: la lista no baja al llegar
@contextmanager
def revisando(cuantas: int):
    """Hace que la lectura traiga esas cosas por revisar (y su línea) mientras dure."""
    LEIDO["cuenta"] = cuantas
    try:
        yield
    finally:
        LEIDO["cuenta"] = 0


with sandbox():
    with revisando(3):
        nueva = abrir()
        # (la segunda, sin que lo que la primera apuntó haya cambiado)
        nueva_otra = abrir()
    clave, alto = nueva["clave"], nueva["arriba_despues"]
    c("la primera vez la lectura trae la línea de «Reparación…» encima de la lista",
      (nueva["linea"], nueva["arriba_antes"], alto > 0), (True, 0, True))
    c("  y la lista baja justo lo que ocupa, como siempre (nada recordado)",
      nueva["abajo_despues"]["rotulo"] - nueva["abajo_antes"]["rotulo"], alto)
    c("  y apunta lo que ocupa esa franja, junto al ancho y a lo de debajo de la lista",
      ancho_guardado(), guardado(clave, nueva["natural"], alto, ABAJO))
    c("la segunda vez, con el dispositivo como estaba, se pinta ya con esa franja reservada",
      (nueva_otra["arriba_antes"], nueva_otra["linea"]), (alto, True))
    c("  y la lista está desde el primer pintado donde estará con la línea",
      movidos(nueva_otra["abajo_antes"], nueva["abajo_despues"]), [])
    c("  al llegar la lectura no se mueve nada de lo que hay debajo: ni el rótulo, ni la "
      "tarjeta, ni una fila", movidos(nueva_otra["abajo_antes"], nueva_otra["abajo_despues"]),
      [])
    c("  el alto del primer pintado ya incluye esa franja (y la de debajo de la lista)",
      nueva_otra["alto_antes"] - nueva["alto_antes"],
      alto + ABAJO - primera["banda_abajo_antes"])
    c("  y la ventana no cambia de alto al llegar la lectura",
      (nueva_otra["alto_antes"], nueva_otra["alto_despues"]), (nueva["alto_despues"],) * 2)
    c("  y queda igual que la primera vez", nueva_otra["geometria"], nueva["geometria"])
    c("  y no escribe nada: ni el ancho ni los altos han cambiado",
      (nueva_otra["escrituras"], ancho_guardado()),
      (0, guardado(clave, nueva["natural"], alto, ABAJO)))

# La franja recordada y la lectura no trae nada encima: se suelta, y se recuerda 0
with sandbox():
    prefs.recordar_arriba(clave, alto)
    vacia = abrir()
    c("un alto recordado y una lectura sin nada encima: se reserva en el primer pintado",
      (vacia["arriba_antes"], vacia["linea"]), (alto, False))
    c("  al llegar se suelta: la lista queda donde estaría sin nada recordado",
      (vacia["arriba_despues"], movidos(vacia["abajo_despues"], primera["abajo_despues"])),
      (0, []))
    c("  con un solo movimiento: sube lo que se había reservado",
      vacia["abajo_antes"]["rotulo"] - vacia["abajo_despues"]["rotulo"], alto)
    c("  y lo recordado pasa a 0, que también es un valor",
      (prefs.arriba_recordado(clave), ancho_guardado()["arriba"]), (0, {clave: 0}))

# Un alto recordado menor que el de ahora: baja la diferencia, una vez, y lo reescribe
with sandbox():
    prefs.recordar_arriba(clave, 20)
    with revisando(3):
        corto = abrir()
    c("un alto recordado menor: se reserva lo que había", corto["arriba_antes"], 20)
    c("  al llegar la lista baja la diferencia y queda donde estaría sin nada recordado",
      (corto["abajo_despues"]["rotulo"] - corto["abajo_antes"]["rotulo"],
       movidos(corto["abajo_despues"], nueva["abajo_despues"])), (alto - 20, []))
    c("  y se reescribe", prefs.arriba_recordado(clave), alto)

# Uno mayor: sube la diferencia
with sandbox():
    prefs.recordar_arriba(clave, alto + 30)
    with revisando(3):
        largo = abrir()
    c("un alto recordado mayor: se reserva lo que había", largo["arriba_antes"], alto + 30)
    c("  al llegar la lista sube la diferencia y queda donde estaría sin nada recordado",
      (largo["abajo_antes"]["rotulo"] - largo["abajo_despues"]["rotulo"],
       movidos(largo["abajo_despues"], nueva["abajo_despues"])), (30, []))
    c("  y se reescribe", prefs.arriba_recordado(clave), alto)

# El de otra clave no se usa ni se pierde
with sandbox():
    prefs.recordar_arriba("otro:9.9:2.000", alto + 300)
    with revisando(3):
        otra_clave = abrir()
    c("el alto de otra clave no se reserva", otra_clave["arriba_antes"], 0)
    c("  y al apuntar el suyo se conserva",
      ancho_guardado()["arriba"], {"otro:9.9:2.000": alto + 300, clave: alto})

# Un bloque que ya estaba en el primer pintado (el aviso de arranque) tampoco se mueve: la
# reserva solo es lo que falta hasta el alto recordado, y va en una fila vacía
AVISO = "Servicio anterior (pid 4242) detenido."
with sandbox():
    with revisando(3):
        con_aviso = abrir(aviso=AVISO)
        con_aviso_otra = abrir(aviso=AVISO)
    c("con el aviso de arranque ya en el primer pintado, la franja lo incluye",
      (con_aviso["arriba_antes"] > 0, con_aviso["arriba_despues"] > con_aviso["arriba_antes"]),
      (True, True))
    c("  la segunda vez se reserva lo que falta y la franja no cambia al llegar la lectura",
      (con_aviso_otra["arriba_antes"], con_aviso_otra["arriba_despues"]),
      (con_aviso["arriba_despues"],) * 2)
    c("  ni el aviso ni nada de lo de debajo se mueven",
      (con_aviso_otra["avisos_despues"],
       movidos(con_aviso_otra["abajo_antes"], con_aviso_otra["abajo_despues"])),
      (con_aviso_otra["avisos_antes"], []))
    c("  y queda donde estaba la primera vez",
      (con_aviso_otra["avisos_despues"],
       movidos(con_aviso_otra["abajo_despues"], con_aviso["abajo_despues"])),
      (con_aviso["avisos_despues"], []))

# Una lectura que falla entera suelta la reserva, pero no se recuerda: sin nada leído no hay
# línea, y la vez siguiente la lista bajaría al llegar
with sandbox():
    prefs.recordar_ancho(clave, nueva["natural"])
    prefs.recordar_arriba(clave, alto)
    real_leer = instantanea.leer
    instantanea.leer = leer_roto
    try:
        rota = abrir()
    finally:
        instantanea.leer = real_leer
    c("una lectura que falla se aplica vacía y suelta la reserva",
      (rota["lista"], rota["arriba_antes"], rota["arriba_despues"]), (True, alto, 0))
    c("  y ese alto no se recuerda: queda el de antes, sin escribir nada",
      (ancho_guardado(), rota["escrituras"]), (guardado(clave, nueva["natural"], alto), 0))

# Una lectura posterior en la misma sesión sigue la misma regla, y no deja reserva detrás
with sandbox():
    visto = {}

    def releer_sin_revisar(root) -> None:
        """Quita lo que hay por revisar, vuelve a leer (botón del arranque) y mira."""
        LEIDO["cuenta"] = 0
        antes = ESCRITAS["n"]
        boton = next(w for w in todos(root) if w.winfo_class() == "TButton"
                     and str(w.cget("text")) == "Configurar…")
        boton.invoke()                               # al volver de esa pantalla, lee otra vez
        leida(root)
        visto.update(linea=bool(fila_de(root, "reparacion")), arriba=banda(root),
                     abajo=abajo(root), guardado=ancho_guardado(),
                     escrituras=ESCRITAS["n"] - antes, lista=root.instantanea_lista)

    prefs.recordar_ancho(clave, nueva["natural"])
    prefs.recordar_arriba(clave, alto)
    prefs.recordar_abajo(clave, ABAJO)               # (que este caso trate solo de lo de arriba)
    ABRIR["despues"] = releer_sin_revisar
    with revisando(3):
        despues = abrir()
    c("con el alto recordado, la primera lectura no mueve nada ni escribe",
      (movidos(despues["abajo_antes"], despues["abajo_despues"]), despues["escrituras"]),
      ([], 0))
    c("una lectura después, sin nada por revisar, se aplica y quita la línea",
      (visto["lista"], visto["linea"], visto["arriba"]), (True, False, 0))
    c("  y la lista queda donde estaría sin nada: no queda ninguna reserva",
      movidos(visto["abajo"], primera["abajo_despues"]), [])
    c("  y lo recordado pasa a 0, una vez",
      (visto["guardado"], visto["escrituras"]),
      (guardado(clave, nueva["natural"], 0, ABAJO), 1))

with sandbox():
    visto = {}

    def releer_con_revisar(root) -> None:
        """Pone cosas por revisar, vuelve a leer (botón del arranque) y mira."""
        visto["antes"] = ancho_guardado()
        LEIDO["cuenta"] = 3
        try:
            boton = next(w for w in todos(root) if w.winfo_class() == "TButton"
                         and str(w.cget("text")) == "Configurar…")
            boton.invoke()
            leida(root)
        finally:
            LEIDO["cuenta"] = 0                      # que no quede puesto para los demás casos
        visto.update(linea=bool(fila_de(root, "reparacion")), arriba=banda(root),
                     abajo=abajo(root), guardado=ancho_guardado())

    ABRIR["despues"] = releer_con_revisar
    sin_nada = abrir()
    c("sin nada recordado y sin nada encima, la primera lectura no apunta ningún alto",
      (sin_nada["arriba_despues"], "arriba" in visto["antes"]), (0, False))
    c("una lectura después trae la línea: la lista baja, como siempre",
      (visto["linea"], visto["arriba"]), (True, alto))
    c("  y queda donde la primera vez con la línea",
      movidos(visto["abajo"], nueva["abajo_despues"]), [])
    c("  y lo recordado es lo que ocupa", visto["guardado"].get("arriba"), {clave: alto})

# 7c. lo que la lectura pone DEBAJO de la lista (la línea del arranque automático, la del
# llavero, la frase de la pausa) también se recuerda y se reserva desde el primer pintado: el
# pie no baja ni la ventana crece al llegar la lectura, que en Windows repinta todo
@contextmanager
def leyendo(**cambios):
    """Cambia lo que trae la lectura (las claves de `LEIDO`) mientras dure."""
    antes = {k: LEIDO[k] for k in cambios}
    LEIDO.update(cambios)
    try:
        yield
    finally:
        LEIDO.update(antes)


with sandbox():
    inicial = abrir()                                # nada recordado
    repetida = abrir()                               # con lo que apuntó la primera
    clave, bajo = inicial["clave"], inicial["banda_abajo_despues"]
    solo_pantallas = inicial["banda_abajo_antes"]    # lo que hay debajo sin la lectura
    crece = bajo - solo_pantallas
    c("la primera vez la lectura trae la línea del arranque automático debajo de la lista",
      (inicial["arranque"], inicial["llavero"], crece > 0), (True, False, True))
    c("  y el pie baja justo lo que ocupa y la ventana crece lo mismo (nada recordado)",
      (inicial["debajo_despues"]["pie"] - inicial["debajo_antes"]["pie"],
       inicial["alto_despues"] - inicial["alto_antes"]), (crece, crece))
    c("  y apunta lo que ocupa esa franja, junto al ancho",
      (ancho_guardado(), inicial["escrituras"]),
      (guardado(clave, inicial["natural"], abajo=bajo), 2))
    c("la segunda vez, con el dispositivo como estaba, se pinta ya con esa franja reservada",
      (repetida["banda_abajo_antes"], repetida["arranque"]), (bajo, True))
    c("  y el pie está desde el primer pintado donde estará con la línea",
      (movidos(repetida["debajo_antes"], inicial["debajo_despues"]),
       repetida["debajo_antes"]["pie"] - inicial["debajo_antes"]["pie"]), ([], crece))
    c("  al llegar la lectura no se mueve nada de lo que hay debajo de la lista",
      movidos(repetida["debajo_antes"], repetida["debajo_despues"]), [])
    c("  ni la ventana cambia de tamaño: el del primer pintado ya es el de después",
      ((repetida["ancho_antes"], repetida["alto_antes"]),
       (repetida["ancho_despues"], repetida["alto_despues"])),
      ((inicial["ancho_despues"], inicial["alto_despues"]),) * 2)
    c("  y queda igual que la primera vez", repetida["geometria"], inicial["geometria"])
    c("  y no escribe nada: ni el ancho ni el alto de abajo han cambiado",
      (repetida["escrituras"], ancho_guardado()),
      (0, guardado(clave, inicial["natural"], abajo=bajo)))

# Un alto recordado menor que el de ahora: el pie baja la diferencia, una vez, y se reescribe
with sandbox():
    prefs.recordar_abajo(clave, bajo - 20)
    corta = abrir()
    c("un alto de abajo recordado menor: se reserva lo que había", corta["banda_abajo_antes"],
      bajo - 20)
    c("  al llegar el pie baja la diferencia y queda donde estaría sin nada recordado",
      (corta["debajo_despues"]["pie"] - corta["debajo_antes"]["pie"],
       corta["alto_despues"] - corta["alto_antes"],
       movidos(corta["debajo_despues"], inicial["debajo_despues"])), (20, 20, []))
    c("  y se reescribe", prefs.abajo_recordado(clave), bajo)

# Uno mayor: el pie sube la diferencia
with sandbox():
    prefs.recordar_abajo(clave, bajo + 30)
    larga = abrir()
    c("un alto de abajo recordado mayor: se reserva lo que había", larga["banda_abajo_antes"],
      bajo + 30)
    c("  al llegar el pie sube la diferencia y queda donde estaría sin nada recordado",
      (larga["debajo_antes"]["pie"] - larga["debajo_despues"]["pie"],
       larga["alto_antes"] - larga["alto_despues"],
       movidos(larga["debajo_despues"], inicial["debajo_despues"])), (30, 30, []))
    c("  y se reescribe", prefs.abajo_recordado(clave), bajo)

# El de otra clave no se usa ni se pierde
with sandbox():
    prefs.recordar_abajo("otro:9.9:2.000", bajo + 300)
    otra_clave_abajo = abrir()
    c("el alto de abajo de otra clave no se reserva",
      otra_clave_abajo["banda_abajo_antes"], solo_pantallas)
    c("  y al apuntar el suyo se conserva",
      ancho_guardado()["abajo"], {"otro:9.9:2.000": bajo + 300, clave: bajo})

# Un alto recordado y una lectura sin línea del arranque automático (el equipo ya no lo
# tiene): se suelta la reserva, se coloca una vez y se recuerda lo que hay, que sigue siendo
# «Parejas…» y «Ajustes…»
with sandbox():
    prefs.recordar_ancho(clave, inicial["natural"])
    prefs.recordar_abajo(clave, bajo)
    with leyendo(vigilante=watch.Resumen("no_disponible")):
        sin_linea = abrir()
    c("un alto de abajo recordado y una lectura sin línea del arranque: se reserva en el "
      "primer pintado", (sin_linea["banda_abajo_antes"], sin_linea["arranque"]), (bajo, False))
    c("  al llegar se suelta: el pie queda donde estaría sin nada recordado",
      (sin_linea["banda_abajo_despues"],
       movidos(sin_linea["debajo_despues"], inicial["debajo_antes"])), (solo_pantallas, []))
    c("  con un solo movimiento: sube lo que se había reservado, y la ventana mengua lo mismo",
      (sin_linea["debajo_antes"]["pie"] - sin_linea["debajo_despues"]["pie"],
       sin_linea["alto_antes"] - sin_linea["alto_despues"]), (crece, crece))
    c("  y lo recordado pasa a lo que hay ahora, una vez",
      (ancho_guardado(), sin_linea["escrituras"]),
      (guardado(clave, inicial["natural"], abajo=solo_pantallas), 1))

# Una lectura que falla entera suelta la reserva, pero no se recuerda: sin nada leído no hay
# línea, y la vez siguiente el pie bajaría al llegar
with sandbox():
    prefs.recordar_ancho(clave, inicial["natural"])
    prefs.recordar_abajo(clave, bajo)
    real_leer = instantanea.leer
    instantanea.leer = leer_roto
    try:
        rota_abajo = abrir()
    finally:
        instantanea.leer = real_leer
    c("una lectura que falla se aplica vacía y suelta la reserva de abajo",
      (rota_abajo["lista"], rota_abajo["banda_abajo_antes"], rota_abajo["banda_abajo_despues"]),
      (True, bajo, solo_pantallas))
    c("  y ese alto no se recuerda: queda el de antes, sin escribir nada",
      (ancho_guardado(), rota_abajo["escrituras"]),
      (guardado(clave, inicial["natural"], abajo=bajo), 0))
with sandbox():
    real_leer = instantanea.leer
    instantanea.leer = leer_roto
    try:
        rota_sola = abrir()
    finally:
        instantanea.leer = real_leer
    c("  y sin nada recordado, una lectura que falla no apunta ningún alto",
      (rota_sola["lista"], ancho_guardado(), rota_sola["escrituras"]), (True, {}, 0))

# Las dos franjas a la vez: lo de encima (la línea de «Reparación…») y lo de debajo (la del
# arranque) se recuerdan y se sueltan en la misma llegada, y no se mueve nada
with sandbox():
    with revisando(3):
        ambas = abrir()
        ambas_otra = abrir()
    c("la primera vez trae las dos franjas y las apunta, junto al ancho",
      (ambas["linea"], ambas["arranque"], ancho_guardado()),
      (True, True, guardado(clave, ambas["natural"], ambas["arriba_despues"],
                            ambas["banda_abajo_despues"])))
    c("la segunda vez se pinta ya con las dos reservadas",
      (ambas_otra["arriba_antes"], ambas_otra["banda_abajo_antes"]),
      (ambas["arriba_despues"], ambas["banda_abajo_despues"]))
    c("  al llegar la lectura no se mueve nada, ni encima de la lista ni debajo",
      (movidos(ambas_otra["abajo_antes"], ambas_otra["abajo_despues"]),
       movidos(ambas_otra["debajo_antes"], ambas_otra["debajo_despues"])), ([], []))
    c("  ni la ventana cambia de tamaño, y queda como la primera vez",
      ((ambas_otra["ancho_antes"], ambas_otra["alto_antes"]),
       (ambas_otra["ancho_despues"], ambas_otra["alto_despues"]),
       ambas_otra["geometria"] == ambas["geometria"]),
      ((ambas["ancho_despues"], ambas["alto_despues"]),) * 2 + (True,))
    c("  y no escribe nada", (ambas_otra["escrituras"], ancho_guardado()),
      (0, guardado(clave, ambas["natural"], ambas["arriba_despues"],
                   ambas["banda_abajo_despues"])))

# Con la línea del llavero (encima de «Parejas…») y la frase de la pausa (debajo de la del
# arranque): el pie y la ventana tampoco se mueven. Lo único que la reserva no puede guardar
# es «Parejas…», que tiene la línea del llavero encima y baja lo que esta mide.
LLAVERO = llavero_editor.Linea("personal.kdbx, al día.", False, True)
CON_TODO = dict(vigilante=watch.Resumen("instalado", modo="sync"), llavero=LLAVERO)
with sandbox():
    with leyendo(**CON_TODO):
        todo = abrir()
        todo_otra = abrir()
    c("la primera vez la lectura trae el llavero, el arranque y la pausa",
      (todo["llavero"], todo["arranque"], todo["banda_abajo_despues"] > bajo), (True, True, True))
    c("la segunda, con eso recordado, el pie y la ventana no se mueven al llegar",
      (todo_otra["banda_abajo_antes"], todo_otra["debajo_antes"]["pie"]
       - todo_otra["debajo_despues"]["pie"], todo_otra["alto_antes"], todo_otra["geometria"]),
      (todo["banda_abajo_despues"], 0, todo["alto_despues"], todo["geometria"]))
    c("  «Parejas…» baja lo que la primera vez, por la línea del llavero que va encima",
      (todo_otra["debajo_despues"]["pantallas"] - todo_otra["debajo_antes"]["pantallas"] > 0,
       todo_otra["debajo_despues"]["pantallas"] - todo_otra["debajo_antes"]["pantallas"]),
      (True, todo["debajo_despues"]["pantallas"] - todo["debajo_antes"]["pantallas"]))

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
