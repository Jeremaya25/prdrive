"""Lo común de los hijos que manejan la ventana principal de verdad (etapa 2).

TEMPORAL, como todo `etapa2_*`: lo borra la tarea 15 de la etapa 2.

`etapa2_reabrir.py` y `etapa2_perfil.py` hacen lo que `driver.py`: corren el
`runsync.py` del dispositivo de muestra (`ui_flow()`, la ventana principal real)
con unas pocas sustituciones que se ponen cuando la aplicación importa el módulo y
no antes, así este fichero no importa nada de lo suyo:

- `tkinter.Tk.mainloop`: una sonda (la función que da cada hijo) que maneja las
  pantallas y cierra;
- `tkinter.Misc.wait_window`: `update()`a el diálogo enseñado, avisa al gancho
  `HOOK["al_mostrar"]` con la hora y, si el gancho no se hace cargo de él (devuelve
  `True`), lo destruye;
- `common.catalog.load`: espera a `ESTADO["catalogo"]` (un `threading.Event`) y
  contesta con la copia local. Con el evento sin poner es un remoto que no
  contesta, y la pantalla no repinta con él en mitad de una medida (M7 de la
  revisión del plan); poniéndolo llega el catálogo;
- `common.update.check`: sin red;
- `ui.tk.orden_sync`: una orden que no hace nada, para que ninguna pasada real corra.

A diferencia del driver, la sonda no empieza hasta que los hilos que arranca la
ventana principal (la versión nueva, los conflictos) han acabado (`esperar_quietud`):
con 50 parejas corren un segundo entero y, concurrentes con la medida, la alargan y
meten sus llamadas en el `cProfile` (que desde Python 3.12 mira todos los hilos).
Lo que mide cada hijo es una ventana quieta, que es de lo que se trata.

Variables: `BENCH_DEVICE` (el dispositivo de muestra, una copia nueva), `BENCH_APP`
(el código, si no es el del dispositivo) y `BENCH_OUT` (donde van las medidas).
"""

from __future__ import annotations

import os
import sys
import threading
import time
import traceback

import utiles  # solo `os` y `sys`: no cuenta como módulo de la aplicación

DEVICE = os.path.realpath(os.environ["BENCH_DEVICE"]) if os.environ.get("BENCH_DEVICE") else ""
APP = os.path.realpath(os.environ.get("BENCH_APP") or os.path.join(DEVICE, ".prdrive"))

NOTES: dict = {}
"""Lo que el hijo cuenta de sí mismo al acabar (`_notes`): errores y datos del entorno."""
ESTADO: dict = {"catalogo": None, "sonda": None}
"""`catalogo`: el `Event` de `common.catalog.load`; `sonda`: lo que hace el hijo en `mainloop`."""
HOOK: dict = {}
"""`al_mostrar(dialogo, hora)`: lo llama el próximo `wait_window` y, si da `True`, no destruye."""


def ms(a: float, b: float) -> float:
    return round((b - a) * 1000, 1)


def record(escenario: str, valor_ms: float, **detalle) -> None:
    """Deja una línea de medida para el orquestador."""
    utiles.escribir(escenario, valor_ms, detalle)


# -------------------------------------------------------------------- sustituciones
def _wait_window(self, window=None) -> None:
    w = window if window is not None else self
    w.update()
    hora = time.perf_counter()
    gancho = HOOK.pop("al_mostrar", None)
    cargo = False
    if gancho is not None:
        cargo = gancho(w, hora)
    if cargo:
        return
    try:
        if w.winfo_exists():
            w.destroy()
    except Exception:                                    # noqa: BLE001
        pass


def _mainloop(self, n=0) -> None:
    """La sonda del hijo en lugar del bucle de eventos; luego cierra la ventana principal."""
    raiz = self
    try:
        NOTES["tk"] = str(raiz.tk.call("info", "patchlevel"))
        raiz.update()                          # el primer pintado, como `driver.probe()`
        cancel_afters(raiz)                    # nada de precargas a ratos mientras se mide
        if not esperar_quietud():
            NOTES["no_quieto"] = threading.active_count() - 1
        ESTADO["sonda"](raiz)
    except Exception:                                    # noqa: BLE001
        NOTES["error"] = traceback.format_exc()[-1800:]
    cancel_afters(raiz)
    try:
        raiz.destroy()
    except Exception:                                    # noqa: BLE001
        pass


def _parche_tkinter(m) -> None:
    m.Misc.wait_window = _wait_window
    m.Tk.mainloop = _mainloop
    m.Misc.mainloop = _mainloop


def _parche_update(m) -> None:
    m.check = lambda force=False: (None, None)


def _parche_catalog(m) -> None:
    evento = threading.Event()
    ESTADO["catalogo"] = evento
    real = m.cached

    def load(raw_local=None):
        """Un remoto que contesta cuando el hijo lo dice, con el mismo catálogo."""
        evento.wait(60)
        c = real()
        if c is None:
            return None, "sin copia"
        try:
            return c._replace(source="remote"), None
        except Exception:                                # noqa: BLE001
            return c, None
    m.load = load


def _parche_ui_tk(m) -> None:
    m.orden_sync = lambda args: [sys.executable, "-c", "pass"]


PARCHES = {"tkinter": _parche_tkinter, "common.update": _parche_update,
           "common.catalog": _parche_catalog, "ui.tk": _parche_ui_tk}


class _Interceptor:
    """Un buscador de importaciones que, tras cargar un módulo de `PARCHES`, le aplica su parche."""

    def find_spec(self, nombre, ruta=None, destino=None):
        parche = PARCHES.get(nombre)
        if parche is None:
            return None
        import _frozen_importlib_external as externo      # ya cargado: no suma módulos
        spec = externo.PathFinder.find_spec(nombre, ruta)
        if spec is None or spec.loader is None:
            return None
        cargador = spec.loader
        ejecutar = cargador.exec_module

        def exec_module(modulo):
            ejecutar(modulo)
            try:
                parche(modulo)
            except Exception as e:                       # noqa: BLE001
                NOTES.setdefault("errores_parche", []).append(f"{nombre}: {e!r}")
        cargador.exec_module = exec_module
        return spec


# ------------------------------------------------------------------------- ayudas
def walk(w):
    """Recorre `w` y todos sus descendientes."""
    pila = [w]
    while pila:
        actual = pila.pop()
        yield actual
        try:
            pila += list(actual.winfo_children())
        except Exception:                                # noqa: BLE001
            pass


def contar(w) -> int:
    """Devuelve los widgets bajo `w`, sin contarlo a él."""
    return sum(1 for _ in walk(w)) - 1


def find_button(w, *textos):
    """Devuelve el primer botón de `w` cuyo texto sea uno de `textos`, o `None`."""
    import tkinter as tk
    from tkinter import ttk
    for x in walk(w):
        if isinstance(x, (ttk.Button, tk.Button)):
            try:
                t = str(x.cget("text"))
            except Exception:                            # noqa: BLE001
                continue
            if t in textos:
                return x
    return None


def cancel_afters(root) -> None:
    """Cancela lo que la ventana tiene pendiente en `after`."""
    try:
        for p in root.tk.splitlist(root.tk.call("after", "info")):
            root.after_cancel(p)
    except Exception:                                    # noqa: BLE001
        pass


def esperar_quietud(limite: float = 20.0) -> bool:
    """Espera a que no quede ningún hilo más que el principal; dice si lo consiguió."""
    fin = time.time() + limite
    while threading.active_count() > 1 and time.time() < fin:
        time.sleep(0.01)
    return threading.active_count() <= 1


def retener_catalogo() -> None:
    """El remoto deja de contestar: lo que lo lea se queda esperando."""
    if ESTADO["catalogo"] is not None:
        ESTADO["catalogo"].clear()


def soltar_catalogo(limite: float = 5.0) -> None:
    """El remoto contesta, y se espera a que las lecturas que esperaban acaben.

    Hay que esperarlas: `ui.segundo_plano.lanzar_sin_repetir()` devuelve la lectura
    del catálogo que aún corre en lugar de lanzar otra, y una ventana que se abre
    con el hilo anterior a medio terminar recibiría la llegada dentro de su medida.
    """
    if ESTADO["catalogo"] is None:
        return
    ESTADO["catalogo"].set()
    modulo = sys.modules.get("ui.segundo_plano")
    fin = time.time() + limite
    while time.time() < fin:
        vivas = [e for _firma, e, _t in list(getattr(modulo, "_EN_VUELO", {}).values())
                 if not e.hecho]
        if not vivas:
            return
        time.sleep(0.002)


def correr(sonda) -> None:
    """Corre la ventana principal del dispositivo y le da el mando a `sonda(raiz)`.

    No vuelve: apunta lo que cuenta de sí el hijo (`_notes`) y sale con
    `os._exit(0)`, sin esperar a hilos de la aplicación que quedaran vivos.
    """
    ESTADO["sonda"] = sonda
    sys.path.insert(0, APP)
    os.chdir(APP)
    sys.meta_path.insert(0, _Interceptor())
    sys.argv = [os.path.join(APP, "runsync.py")]
    try:
        import runsync  # noqa: E402  -- el código de módulo es lo que corre el script al arrancar
        NOTES["exit"] = runsync.main()
    except SystemExit as e:
        NOTES["exit"] = e.code
    except Exception:                                    # noqa: BLE001
        NOTES["error"] = traceback.format_exc()[-1800:]
    soltar_catalogo()
    NOTES["python"] = sys.version.split()[0]
    utiles.escribir("_notes", 0, NOTES)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
