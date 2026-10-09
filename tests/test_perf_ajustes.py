#!/usr/bin/env python3
"""«Ajustes» apunta sus tiempos con `PRDRIVE_PERF=1` (los `ui.perf_*` de `ui/__init__.py`).

Lo que se comprueba, con Tk de verdad:

- `open-ajustes`: la ventana se abre con la `mostrar` real, la que espera a que
  se cierre, y su línea sale una sola vez, al pintarse. El inicio lo pone aquí
  el test, como lo pondría `abrir_ajustes()` de la ventana principal;
- `pane-<clave>`: cada apartado al que se pasa desde otro deja una línea; pulsar
  el que ya está a la vista no deja ninguna (el retorno temprano);
- con `PRDRIVE_PERF` sin definir no se escribe ningún diario.

Los apartados se recorren con una `mostrar` de prueba, como en
`test_tk_ajustes_vista.py`, que los pulsa y cierra la ventana en vez de esperar.
Solo la apertura usa la de verdad.
"""

import sys
import time

from _harness import Checks, sandbox

import _perf

c = Checks("«Ajustes» apunta sus tiempos con PRDRIVE_PERF=1")

try:
    import tkinter as tk
    from tkinter import ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from common import catalog, model, update  # noqa: E402
from ui import segundo_plano, tk_doctor, tk_versions, versions_editor, watch  # noqa: E402
import ui  # noqa: E402

# Lo que los apartados leen del remoto o del equipo llega en el acto, como en
# `test_tk_ajustes_vista.py`: aquí no se entra nunca en el bucle de eventos.
segundo_plano.lanzar = segundo_plano.en_el_acto
tk_versions.working = lambda parent, title, funcion, mensaje="", **_k: (True, funcion())
versions_editor.leer_local = lambda pair: versions_editor.Lado(
    versions_editor.DISPOSITIVO, str(pair.local_abs), True, "", ())
versions_editor.leer_remoto = lambda pair: versions_editor.Lado(
    versions_editor.REMOTO, pair.versions_path2, True, "", ())
catalog.load = lambda raw_local=None: (None, "sin red")
update.pending = lambda root=None: None

errores: list[str] = []
raiz.report_callback_exception = (
    lambda tipo, valor, _tb: errores.append(f"{tipo.__name__}: {valor}"))

RAW = {"defaults": {"remote": "nas"},
       "pair": [{"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas",
                 "mode": "bisync", "versions": True},
                {"name": "fotos", "local": "sync-data/fotos", "remote_path": "/R/fotos",
                 "mode": "bisync", "versions": True}]}
ROTULOS = {a.clave: a.rotulo for _g, aps in tk_doctor.GRUPOS for a in aps}
"""El rótulo de cada apartado en la barra."""
ORDEN = ("volumen", "configuracion", "llavero", "versiones", "arranque", "qr",
         "reparacion", "actualizaciones")
"""Los apartados que se pulsan, en orden: cada uno se llega desde otro y marca una vez."""
AGENTE = watch.Resumen("agente", "ui", True)
"""Un vigilante que no lee nada del equipo: el apartado «Arranque» es el del agente."""
MOSTRAR_REAL = tk_doctor.mostrar
"""La `mostrar` de `ui.tk`, para restaurarla tras cada prueba que la sustituya."""


def recorrer(w):
    """Recorre los widgets que cuelgan de `w`, en profundidad."""
    for hijo in w.winfo_children():
        yield hijo
        yield from recorrer(hijo)


def asentar(dlg, segundos: float = 0.02) -> None:
    """Deja correr el bucle de Tk un rato, para que se ejecuten los cierres pendientes de `perf_al_pintar`.

    Un `update()` corre los temporizadores vencidos; un cierre que se programa mientras
    corre el bucle puede quedar para la vuelta siguiente, y el rato lo recoge.

    Args:
        dlg: La ventana de «Ajustes».
        segundos: Cuánto tiempo dejar correr el bucle.
    """
    fin = time.monotonic() + segundos
    while True:
        dlg.update()
        if time.monotonic() >= fin:
            return
        time.sleep(0.002)


def pulsar(dlg, clave: str) -> None:
    """Pulsa el botón de la barra lateral del apartado, como quien lo usa."""
    for b in recorrer(dlg):
        if (isinstance(b, ttk.Button)
                and str(b.cget("style")) in ("Nav.TButton", "NavSel.TButton")
                and b.cget("text") == ROTULOS[clave]):
            b.invoke()
            return
    raise AssertionError(f"no hay botón de la barra para {clave!r}")


def abrir(conducir) -> None:
    """Abre «Ajustes» con una `mostrar` de prueba que ejecuta `conducir(dlg)` y cierra la ventana."""
    def mostrar(dlg, parent=None):
        """Hace lo que toque con la ventana ya montada, y la cierra."""
        try:
            conducir(dlg)
        finally:
            if dlg.winfo_exists():
                dlg.destroy()

    tk_doctor.mostrar = mostrar
    try:
        tk_doctor.open_dialog(raiz, model.parse_config(RAW), lambda *a: None, vigilante=AGENTE)
    finally:
        tk_doctor.mostrar = MOSTRAR_REAL


def cerrar_ajustes() -> None:
    """Destruye las ventanas hijas de la raíz de la prueba que sigan vivas: la de «Ajustes»."""
    for hijo in raiz.winfo_children():
        if isinstance(hijo, tk.Toplevel) and hijo.winfo_exists():
            hijo.destroy()


# 1. La apertura con la `mostrar` real: una línea open-ajustes, al pintarse.
with sandbox() as tmp, _perf.con_perf(tmp) as t:
    # Lo pone `abrir_ajustes()` de la ventana principal; aquí se hace a mano.
    ui.perf_empezar("open-ajustes")
    raiz.after(200, cerrar_ajustes)                   # la `mostrar` real espera a que se cierre
    tk_doctor.open_dialog(raiz, model.parse_config(RAW), lambda *a: None, vigilante=AGENTE)
    raiz.update()
    _perf.vaciar()
    c("«Ajustes» abierta con la `mostrar` de verdad deja una línea open-ajustes al pintarse",
      len(_perf.lineas(t, "open-ajustes")), 1)


# 2. Cada apartado pulsado desde otro deja una línea; el ya a la vista no deja ninguna.
with sandbox() as tmp, _perf.con_perf(tmp) as t:
    visto: dict = {}

    def recorrer_apartados(dlg):
        """Pulsa cada apartado, uno tras otro, y apunta cuántas líneas deja cada uno."""
        for clave in ORDEN:
            pulsar(dlg, clave)
            asentar(dlg)                              # el pintado, que cierra la medida
        _perf.vaciar()
        visto["tras recorrer"] = {k: len(_perf.lineas(t, f"pane-{k}")) for k in ORDEN}
        pulsar(dlg, "actualizaciones")                # ya a la vista: retorno temprano
        asentar(dlg)
        _perf.vaciar()
        visto["tras repetir"] = len(_perf.lineas(t, "pane-actualizaciones"))

    abrir(recorrer_apartados)
    c("cada apartado pulsado desde otro deja una línea pane-<clave>",
      visto["tras recorrer"], {k: 1 for k in ORDEN})
    c("pulsar el apartado ya a la vista no deja línea (retorno temprano)",
      visto["tras repetir"], 1)


# 3. Con PRDRIVE_PERF sin definir no se escribe ningún diario, ni al abrir ni al pulsar.
with sandbox() as tmp, _perf.con_perf(tmp, activo=False) as t:
    ui.perf_empezar("open-ajustes")
    raiz.after(200, cerrar_ajustes)
    tk_doctor.open_dialog(raiz, model.parse_config(RAW), lambda *a: None, vigilante=AGENTE)
    raiz.update()

    def recorrer_sin_medir(dlg):
        """Pulsa cada apartado con la medida apagada."""
        for clave in ORDEN:
            pulsar(dlg, clave)
            dlg.update()

    abrir(recorrer_sin_medir)
    _perf.vaciar()
    c("sin PRDRIVE_PERF no hay diario del dispositivo",
      (t / "logs" / "perf.log").exists(), False)
    c("  ni del equipo", (t / "equipo" / "perf.log").exists(), False)


c("sin errores en los manejadores de Tk", errores, [])
sys.exit(c.report())
