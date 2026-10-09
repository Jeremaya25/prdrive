#!/usr/bin/env python3
"""«Dispositivos» apunta sus tiempos con `PRDRIVE_PERF=1` (`ui/tk_fleet.py`).

Los tres momentos de la ventana, según la tabla de la etapa 4 (Wave 2):

- `open-dispositivos`: lo cierra `ui.tk.mostrar()` cuando el diálogo se pinta. Su
  inicio lo pone `tk_pairs.ver_flota` (tarea 3); aquí se pone a mano, como lo
  pondría ella.
- `llega-flota`: cada vez que llega una lectura de la flota (al abrir, con
  «Releer» y con una lectura que falla), desde el principio de `llegada` hasta
  después de su pintado.
- `elegir-dispositivo`: la tabla de la ventana lo declara en su lienzo
  (`TablaLienzo.momento_elegir`); la marca la pone `TablaLienzo.elegir` (tarea 3),
  así que aquí solo se comprueba la declaración.

La ventana se abre de verdad: `tk_fleet.open_dialog()` y `ui.tk.mostrar()` sin
sustituir nada. La flota llega en el sitio, como en `tests/test_tk_flota_vista.py`,
del que se copian solo los datos mínimos. Con la medida apagada no queda ningún
diario.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from _harness import Checks, sandbox

import _perf

from common import fleet

c = Checks("«Dispositivos» apunta sus tiempos (PRDRIVE_PERF)")

try:
    import tkinter as tk
    from tkinter import ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

import ui  # noqa: E402
from ui import segundo_plano, tk_fleet  # noqa: E402

errores: list[str] = []
raiz.report_callback_exception = (
    lambda tipo, valor, _tb: errores.append(f"{tipo.__name__}: {valor}"))
# La flota llega en el sitio: aquí no hay bucle que sondee. Con hilos de verdad se
# prueba en tests/test_tk_segundo_plano.py.
segundo_plano.lanzar = segundo_plano.en_el_acto
fleet.device_id = lambda app_dir=None: "disp0000xxxxxxxx"
fleet.equipo_actual = lambda: "PORTATIL"
LEIDA: list = []
fleet.leer = lambda raw=None: (list(LEIDA), None)
RAW = {"defaults": {"remote": "nas"}, "pair": []}
VENTANAS: list = []
"""Las ventanas de «Dispositivos» que se han abierto, la última al final."""


def dispositivo(i: int) -> fleet.Dispositivo:
    """Un dispositivo con su nota completa y fechas fijas (lo que enseña no depende de la hora)."""
    return fleet.Dispositivo(
        id=f"disp{i:04d}xxxxxxxx", nombre=f"el {i}", version="0.7.1",
        plataformas=("windows-x64",), last_seen="2026-01-01 08:00:00",
        last_result="ok" if i % 2 else "fallo en fotos",
        ultima_buena="2025-12-01 08:00:00",
        equipos=(fleet.Equipo("PORTATIL", "2026-01-01 09:00:00"),))


def todos(widget) -> list:
    """El widget y todo lo que cuelga de él."""
    salida = [widget]
    for hijo in widget.winfo_children():
        salida += todos(hijo)
    return salida


def boton(dlg, texto: str):
    """El botón de ese texto dentro de la ventana."""
    return next(w for w in todos(dlg) if isinstance(w, ttk.Button) and w.cget("text") == texto)


def abrir(accion=None) -> None:
    """Abre «Dispositivos» como lo hace la pantalla de parejas, y la cierra al terminar.

    El inicio de `open-dispositivos` se pone aquí (lo pone `tk_pairs.ver_flota`, que
    aún no está en esta rama). `accion(dlg)`, si se da, corre dentro del bucle de
    `mostrar()`, con la ventana ya a la vista; la ventana se cierra después.
    """
    ui.perf_empezar("open-dispositivos")

    def dentro() -> None:
        """Corre lo que toca dentro de `mostrar()` y cierra la ventana."""
        dlg = [w for w in raiz.winfo_children() if isinstance(w, tk.Toplevel)][-1]
        VENTANAS.append(dlg)
        if accion is not None:
            accion(dlg)
            raiz.after(200, dlg.destroy)
        else:
            dlg.destroy()

    raiz.after(300, dentro)
    tk_fleet.open_dialog(raiz, None, dict(RAW))


with sandbox() as raiz_tk:
    tmp = Path(raiz_tk)

    # 1. Al abrir: el momento del diálogo y la primera llegada, una vez cada uno; la
    #    tabla declara su momento de elegir.
    LEIDA[:] = [dispositivo(i) for i in range(3)]
    with _perf.con_perf(tmp / "abrir") as t:
        abrir()
        _perf.vaciar()
        c("al abrir: open-dispositivos y llega-flota, una línea cada uno",
          (len(_perf.lineas(t, "open-dispositivos")), len(_perf.lineas(t, "llega-flota"))),
          (1, 1))
        c("la tabla declara «elegir-dispositivo» como su momento de elegir",
          getattr(VENTANAS[-1].tabla._lienzo, "momento_elegir", None), "elegir-dispositivo")

    # 2. «Releer» es otra llegada: la segunda vez de llega-flota; el diálogo sigue
    #    marcándose una sola vez.
    with _perf.con_perf(tmp / "releer") as t:
        abrir(accion=lambda dlg: boton(dlg, "Releer").invoke())
        _perf.vaciar()
        llegadas = _perf.lineas(t, "llega-flota")
        # `vez` cuenta por proceso y no por bloque de prueba: se mira que la segunda
        # llegada sea la siguiente de la primera.
        numeros = [int(re.search(r" vez=(\d+)", linea).group(1)) for linea in llegadas]
        c("«Releer»: una llegada más, con el vez siguiente; el diálogo se marca una sola vez",
          (len(_perf.lineas(t, "open-dispositivos")), len(numeros),
           numeros[-1] - numeros[0] if numeros else None), (1, 2, 1))

    # 3. Una lectura que falla también llega a pintarse: el mismo momento, por la otra rama.
    def leer_que_falla(raw=None):
        """Sustituye a `fleet.leer()` por una lectura que falla."""
        raise OSError("lectura de prueba")

    previo = fleet.leer
    fleet.leer = leer_que_falla
    try:
        with _perf.con_perf(tmp / "fallo") as t:
            abrir()
            _perf.vaciar()
            c("una lectura que falla también marca llega-flota",
              len(_perf.lineas(t, "llega-flota")), 1)
    finally:
        fleet.leer = previo

    # 4. Apagada: la ventana funciona igual y no queda ningún diario.
    with _perf.con_perf(tmp / "apagado", activo=False) as t:
        abrir()
        _perf.vaciar()
        c("PRDRIVE_PERF sin definir: ni perf.log ni marcas",
          (t / "logs" / "perf.log").exists(), False)

    c("ninguna excepción de Tk en las aperturas", errores, [])

raiz.destroy()
sys.exit(c.report())
