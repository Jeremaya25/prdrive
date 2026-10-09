#!/usr/bin/env python3
"""Los momentos de la ventana principal y de la de la pasada, con `PRDRIVE_PERF=1`.

Con las ventanas de verdad (`ui.tk.main_window` y la de salida de una pasada, con
el bucle de eventos sustituido por una sonda, como `tests/test_tk_principal_ancho.py`)
cada acción deja en `logs/perf.log` una línea por momento:

- `start-main`, `llega-instantanea`, `marcar`, `volver-ajustes`,
  `sincronizar-ventana` y `volver-pasada`, una vez cada uno por acción;
- `log-10k` solo cuando la pasada imprime 1000 líneas o más, con `lineas=N`;
- con la medida apagada no se crea `perf.log`; con `logs/` como fichero la
  ventana sigue igual y ninguna escritura de JSON va a `logs/`;
- `start-main` se anota después de que `ensenar()` descubra la ventana (en
  Windows, después de quitarle el velo de DWM), y sin edad del proceso no se anota;
- «Sincronizar ahora» sin nada marcado sigue activo, no abre pasada y no deja
  abierto el inicio de `sincronizar-ventana`.

`open-ajustes` y `open-parejas` solo tienen aquí su inicio: sus diálogos están
sustituidos, así que se comprueba que el inicio está anotado al abrirse cada uno
y que queda abierto; su final lo pone `mostrar()` y lo comprueban los tests de
«Ajustes» y de «Parejas».
"""

import sys
import time
from contextlib import contextmanager
from pathlib import Path

from _harness import Checks, mkcfg, sandbox, tmpdir

c = Checks("momentos de PRDRIVE_PERF en la ventana principal y la de la pasada")

import ui  # noqa: E402  — antes que tkinter: en Linux trae su Tk con Xft
from ui import theme  # noqa: E402

try:
    import tkinter as tk
    theme.nitidez()
    tk.Tk().destroy()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

import _perf  # noqa: E402
from common import model, store, update  # noqa: E402
from ui import instantanea, prefs, segundo_plano, tk_doctor, tk_pairs, watch  # noqa: E402
from ui import tk as uitk  # noqa: E402

CFG = mkcfg([f"pareja{i:02d}" for i in range(5)], {"pairs": ["pareja00"]})
HOLA = [sys.executable, "-c", "print('hola')"]
"""Una orden que escribe una línea y acaba."""
MUCHAS = [sys.executable, "-c", "for i in range(1100): print('linea', i)"]
"""Una orden que imprime más de 1000 líneas: el momento `log-10k`."""
ORDEN = {"cmd": HOLA}
"""La orden que lanza la pasada de la prueba (la sustituye `uitk.orden_sync`)."""

# Lo que la ventana lee del dispositivo no se toca: la lectura vacía basta, y las
# parejas y el arranque no salen del equipo de la prueba.
update.pending = lambda root=None: None
update.check = lambda force=False: (None, None)
ui.pair_status_notes = lambda cfg: {}
uitk.pair_status_notes = lambda cfg: {}
instantanea.leer = lambda config, **_k: instantanea.vacia(config)
watch.resumen = lambda: watch.Resumen("sin_instalar")
prefs.PREFS = tmpdir("prdrive-perf-principal-") / "ui_prefs.json"
uitk.orden_sync = lambda args: ORDEN["cmd"]
INICIO_AL_ABRIR: dict[str, bool] = {}
"""Si cada diálogo sustituido encontró su inicio ya anotado al abrirse (`ui._INICIOS`)."""


def parejas_sin_abrir(*_a, **_k) -> bool:
    """«Parejas…» sustituido: no cambia nada, y anota si su inicio estaba ya abierto."""
    INICIO_AL_ABRIR["open-parejas"] = "open-parejas" in ui._INICIOS
    return False


def ajustes_sin_abrir(*_a, **_k) -> dict:
    """«Ajustes…» sustituido: sin cambios al cerrar, y anota si su inicio estaba ya abierto."""
    INICIO_AL_ABRIR["open-ajustes"] = "open-ajustes" in ui._INICIOS
    return {}


tk_pairs.open_dialog = parejas_sin_abrir                 # «Parejas…»: solo su inicio aquí
tk_doctor.open_dialog = ajustes_sin_abrir                # «Ajustes…»: solo su inicio aquí


def todos(w):
    """Recorre los widgets que cuelgan de `w`, en profundidad."""
    for hijo in w.winfo_children():
        yield hijo
        yield from todos(hijo)


def cancelar_esperas(root) -> None:
    """Cancela los `after` pendientes (los sondeos de la lectura), como hace la otra prueba."""
    for pendiente in root.tk.splitlist(root.tk.call("after", "info")):
        try:
            root.after_cancel(pendiente)
        except tk.TclError:
            pass


def asentar(root, segundos: float = 0.05) -> None:
    """Deja correr el bucle de Tk un rato: los `after_idle` y los temporizadores vencidos."""
    fin = time.monotonic() + segundos
    while True:
        root.update()
        if time.monotonic() >= fin:
            return
        time.sleep(0.005)


def esperar(root, cumple, limite: float = 20.0) -> bool:
    """Mueve el bucle hasta que `cumple()` sea cierto, como mucho `limite` segundos."""
    fin = time.monotonic() + limite
    while not cumple():
        if time.monotonic() > fin:
            return False
        root.update()
        time.sleep(0.01)
    return True


def pulsar_casilla(root) -> None:
    """Cambia la primera casilla de la lista: es «al_marcar» (el «N de M» y la selección)."""
    next(w for w in todos(root) if w.winfo_class() == "TCheckbutton").invoke()


def marcar_primera(root) -> None:
    """Deja marcada la primera casilla (la pareja de la prueba), si no lo está ya."""
    casilla = next(w for w in todos(root) if w.winfo_class() == "TCheckbutton")
    if not casilla.instate(["selected"]):
        casilla.invoke()


def pulsar_boton(root, prefijo: str) -> None:
    """Pulsa el primer botón cuyo texto empieza por `prefijo`."""
    next(w for w in todos(root) if w.winfo_class() == "TButton"
         and str(w.cget("text")).startswith(prefijo)).invoke()


def pasadas(root) -> list:
    """Las ventanas de salida que cuelgan de la principal (las pasadas abiertas)."""
    return [w for w in root.winfo_children() if w.winfo_class() == "Toplevel"]


def texto_de(ventana) -> str:
    """Lo que la ventana de salida tiene escrito."""
    return next(w for w in todos(ventana) if w.winfo_class() == "Text").get("1.0", "end")


def abrir(accion) -> None:
    """Abre la principal de verdad, deja llegar su primera lectura y hace `accion(root)`.

    La sonda sustituye al bucle de eventos: un rato del bucle pinta y procesa lo
    pendiente (`start-main`, que vence al instante), se cancelan los sondeos y la lectura
    se entrega a mano, como la reparte el sondeo. Al final la ventana se destruye
    aunque la acción falle.
    """
    def conducir(root, n=0) -> None:
        """La sonda que sustituye al bucle de eventos."""
        try:
            asentar(root, 0.01)
            cancelar_esperas(root)
            root.instantanea.correr()
            root.sondeo_instantanea._mirar()
            asentar(root)
            accion(root)
            asentar(root)
        finally:
            try:
                cancelar_esperas(root)
                root.destroy()
            except tk.TclError:
                pass

    previo = (tk.Tk.mainloop, segundo_plano.lanzar)
    tk.Tk.mainloop = conducir
    segundo_plano.lanzar = segundo_plano.Encargo
    try:
        uitk.main_window(CFG, None)
    finally:
        tk.Tk.mainloop, segundo_plano.lanzar = previo


def marcar_y_ajustes(root) -> None:
    """Acción de la principal: marcar una pareja, «Parejas…» y «Ajustes…»."""
    pulsar_casilla(root)
    pulsar_boton(root, "Parejas")
    pulsar_boton(root, "Ajustes")


def pasada(root) -> None:
    """Acción de la principal: marcar, sincronizar, esperar a que acabe la salida y cerrarla."""
    marcar_primera(root)
    pulsar_boton(root, "Sincronizar")
    esperar(root, lambda: bool(pasadas(root)))
    ventana = pasadas(root)[0]
    esperar(root, lambda: "=== Terminado" in texto_de(ventana))
    ventana.destroy()
    asentar(root, 0.2)                    # «al_cerrar» llega como `after_idle` de la principal


@contextmanager
def entorno(activo: bool = True, logs_es_fichero: bool = False):
    """Rutas del modelo en un temporal y la medida encendida (o apagada) dentro de él.

    Args:
        activo: Si `PRDRIVE_PERF` está en `1` durante la prueba.
        logs_es_fichero: Si `logs/` es un fichero y no una carpeta (no se puede escribir).

    Yields:
        La carpeta de la prueba, la que `_perf.lineas()` lee.
    """
    with sandbox():
        tmp = Path(tmpdir("prdrive-perf-sitio-"))
        if logs_es_fichero:
            (tmp / "logs").write_text("no es una carpeta", encoding="utf-8")
        with _perf.con_perf(tmp, activo=activo) as t:
            try:
                yield t
            finally:
                # Los inicios que no se cerraron (los de los diálogos sustituidos) no pasan
                # a la prueba siguiente.
                ui._INICIOS.clear()


# 1. la principal: el primer pintado, la primera lectura, una casilla y «Ajustes…»
with entorno() as tmp:
    abrir(marcar_y_ajustes)
    _perf.vaciar()
    c("start-main se anota una vez", len(_perf.lineas(tmp, "start-main")), 1)
    c("llega-instantanea se anota una vez", len(_perf.lineas(tmp, "llega-instantanea")), 1)
    c("marcar se anota una vez", len(_perf.lineas(tmp, "marcar")), 1)
    c("volver-ajustes se anota una vez", len(_perf.lineas(tmp, "volver-ajustes")), 1)
    c("la línea acaba en «ms vez=1»", (_perf.lineas(tmp, "marcar") or [""])[0].split()[-2:],
      ["ms", "vez=1"])
    c("«Parejas…» anota su inicio antes de abrir el diálogo",
      INICIO_AL_ABRIR.get("open-parejas"), True)
    c("«Parejas…» deja abierto open-parejas (el diálogo sustituido no lo cierra)",
      "open-parejas" in ui._INICIOS, True)
    c("«Ajustes…» anota su inicio antes de abrir el diálogo",
      INICIO_AL_ABRIR.get("open-ajustes"), True)
    c("«Ajustes…» deja abierto open-ajustes (el diálogo sustituido no lo cierra)",
      "open-ajustes" in ui._INICIOS, True)

# 2. una pasada corta: la ventana sale antes que el proceso, y al cerrarla vuelve la principal
ORDEN["cmd"] = HOLA
with entorno() as tmp:
    abrir(pasada)
    _perf.vaciar()
    c("sincronizar-ventana se anota una vez", len(_perf.lineas(tmp, "sincronizar-ventana")), 1)
    c("volver-pasada se anota una vez", len(_perf.lineas(tmp, "volver-pasada")), 1)
    c("una pasada de una línea no anota log-10k", len(_perf.lineas(tmp, "log-10k")), 0)

# 3. una pasada de más de mil líneas: log-10k con el número de líneas que imprimió
ORDEN["cmd"] = MUCHAS
with entorno() as tmp:
    abrir(pasada)
    _perf.vaciar()
    c("log-10k se anota una vez con sus líneas", [
        linea.split()[-1] for linea in _perf.lineas(tmp, "log-10k")], ["lineas=1100"])
ORDEN["cmd"] = HOLA

# 4. apagada: ningún diario, ni siquiera un fichero vacío
with entorno(activo=False) as tmp:
    abrir(marcar_y_ajustes)
    _perf.vaciar()
    c("apagada: no se crea perf.log", (tmp / "logs" / "perf.log").exists(), False)

# 5. `logs/` como fichero: la ventana se abre, marca y cierra; nada escribe JSON en `logs/`
with entorno(logs_es_fichero=True) as tmp:
    escritas: list[Path] = []
    escribir_real = store.write_json

    def contar(ruta, *args, **kwargs):
        """Apunta cada escritura de JSON, durante toda la ventana, y deja pasar cada una."""
        escritas.append(Path(ruta))
        return escribir_real(ruta, *args, **kwargs)

    store.write_json = contar
    try:
        abrir(marcar_y_ajustes)
        _perf.vaciar()
    finally:
        store.write_json = escribir_real
    # Solo lo que cuelga de `logs/`: las preferencias y el estado van a otros sitios.
    en_logs = [r for r in escritas if model.LOG_DIR in r.parents or r.name == "perf.log"]
    c("logs/ como fichero: ninguna escritura de JSON va a logs/ (ni una marca)", en_logs, [])
    c("logs/ como fichero: no hay diario de tiempos", _perf.lineas(tmp, "marcar"), [])

# 6. el orden: start-main se anota después de que ensenar() quite el velo de DWM
with entorno() as tmp:
    orden: list = []
    previo = (uitk.IS_WIN, uitk._encubrir, uitk._poner_barra, ui.perf_marca, tk.Tk.wm_frame)
    hwnd = 0x1234

    def encubrir(h, encubierta):
        """Apunta la petición de DWM y contesta que sí."""
        orden.append(("encubrir", h, encubierta))
        return True

    def marca(momento, ms, **_k):
        """Apunta la marca en la misma lista que el velo."""
        orden.append(("marca", momento))

    uitk.IS_WIN, uitk._encubrir, uitk._poner_barra = True, encubrir, lambda h: None
    ui.perf_marca = marca
    tk.Tk.wm_frame = lambda self: hex(hwnd)
    try:
        abrir(lambda root: None)
    finally:
        uitk.IS_WIN, uitk._encubrir, uitk._poner_barra, ui.perf_marca = previo[:4]
        tk.Tk.wm_frame = previo[4]
    descubierta = orden.index(("encubrir", hwnd, False)) if ("encubrir", hwnd, False) in orden else -1
    marcada = orden.index(("marca", "start-main")) if ("marca", "start-main") in orden else -1
    c("start-main llega después de descubrir la ventana", marcada > descubierta >= 0, True)

# 7. sin edad del proceso no hay start-main, y la ventana abre igual
with entorno() as tmp:
    previo_edad = getattr(uitk, "perf_desde_inicio", None)
    uitk.perf_desde_inicio = lambda: None
    try:
        abrir(marcar_y_ajustes)
    finally:
        uitk.perf_desde_inicio = previo_edad
    _perf.vaciar()
    c("sin edad del proceso: no hay start-main", _perf.lineas(tmp, "start-main"), [])

# 8. «Sincronizar ahora» sin nada marcado: el botón responde, no hay pasada y no queda un
#    inicio de `sincronizar-ventana` abierto (si quedara, la próxima pasada lo cerraría tarde)
with entorno() as tmp:
    visto: dict = {}

    def casillas_marcadas(root) -> int:
        """Cuántas casillas de pareja están marcadas ahora mismo."""
        return sum(1 for w in todos(root) if w.winfo_class() == "TCheckbutton"
                   and w.instate(["selected"]))

    def sin_marcar(root) -> None:
        """Desmarca las casillas (la pareja por defecto sale marcada) y pulsa «Sincronizar».

        Anota si el botón sigue activo, si queda abierto el inicio de la pasada y
        si se abre alguna pasada.
        """
        for casilla in (w for w in todos(root) if w.winfo_class() == "TCheckbutton"):
            if casilla.instate(["selected"]):
                casilla.invoke()
        visto["marcadas"] = casillas_marcadas(root)
        boton = next(w for w in todos(root) if w.winfo_class() == "TButton"
                     and str(w.cget("text")).startswith("Sincronizar"))
        visto["activo"] = not boton.instate(["disabled"])
        boton.invoke()
        visto["inicio"] = "sincronizar-ventana" in ui._INICIOS
        visto["pasadas"] = len(pasadas(root))

    abrir(sin_marcar)
    _perf.vaciar()
    c("la prueba parte de nada marcado", visto.get("marcadas"), 0)
    c("sin marcar nada, «Sincronizar ahora» sigue activo (el clic llega al handler)",
      visto.get("activo"), True)
    c("sin marcar nada no queda inicio de sincronizar-ventana", visto.get("inicio"), False)
    c("sin marcar nada no se abre ninguna pasada", visto.get("pasadas"), 0)
    c("sin marcar nada no hay línea sincronizar-ventana",
      _perf.lineas(tmp, "sincronizar-ventana"), [])

# Termina sin esperar al intérprete: el hilo de marcas y las imágenes de Tk no ensucian la salida.
_perf.salir(c.report())
