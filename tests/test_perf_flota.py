#!/usr/bin/env python3
"""«Dispositivos» apunta sus tiempos con `PRDRIVE_PERF=1` (`ui/tk_fleet.py`).

Los tres momentos de la ventana:

- `open-dispositivos`: lo cierra `ui.tk.mostrar()` cuando el diálogo se pinta. Su
  inicio lo pone `ui/tk_pairs.py` (`ver_flota`); aquí se pone a mano, como lo
  pondría ella.
- `llega-flota`: cada vez que llega una lectura de la flota (al abrir, con
  «Releer» y con una lectura que falla), desde el principio de `llegada` hasta
  después de su pintado.
- `elegir-dispositivo`: la tabla de la ventana lo declara (`Tabla.momento_elegir`);
  lo anota `TablaLienzo.elegir` en `ui/tk_tabla.py` cuando se elige otra fila con
  el ratón o el teclado, y no al abrir.

La ventana se abre de verdad: `tk_fleet.open_dialog()` y `ui.tk.mostrar()` sin
sustituir nada. La flota llega en el sitio, como en `tests/test_tk_flota_vista.py`,
del que se copian solo los datos mínimos. Con la medida apagada no queda ningún
diario.
"""

from __future__ import annotations

import re
import sys
import time
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

    El inicio de `open-dispositivos` lo pone `tk_pairs.ver_flota`; este test abre el
    diálogo directamente, así que lo pone aquí. `accion(dlg)`, si se da, corre dentro
    del bucle de `mostrar()`, con la ventana ya a la vista; la ventana se cierra después.
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

    fin = time.monotonic() + 5.0

    def cuando_se_vea() -> None:
        """Corre `dentro` en cuanto `mostrar()` ha enseñado la ventana.

        Un temporizador fijo puede vencer antes: `Visor.encajar()` hace un
        `update_idletasks()` que ejecuta el `after_idle` que anota el pintado de
        la medida, y ese hace un `update()`; así el temporizador vence antes de
        que `mostrar()` enseñe la ventana. Con un límite, para que una ventana
        que nunca llega no deje la prueba colgada.
        """
        dlgs = [w for w in raiz.winfo_children() if isinstance(w, tk.Toplevel)]
        if (dlgs and dlgs[-1].winfo_viewable()) or time.monotonic() > fin:
            dentro()
        else:
            raiz.after(10, cuando_se_vea)

    raiz.after(10, cuando_se_vea)
    tk_fleet.open_dialog(raiz, None, dict(RAW))
    # El pintado de cada momento se anota en un after_idle: se procesa aquí, dentro de
    # la sección que lo genera, y no en el diario de la siguiente.
    raiz.update()


with sandbox() as raiz_tk:
    tmp = Path(raiz_tk)

    # 1. Al abrir: el momento del diálogo y la primera llegada, una vez cada uno. Abrir
    #    no elige nada; un clic en otra fila sí, y se anota una vez.
    LEIDA[:] = [dispositivo(i) for i in range(3)]
    antes_del_clic: list[int] = []
    vista_al_clic: list[int] = []
    elegida_tras_clic: list = []

    def pulsar_otra(dlg) -> None:
        """Mira que abrir no anotó ninguna elección y luego hace un clic en otra fila."""
        _perf.vaciar()
        antes_del_clic.append(len(_perf.lineas(t, "elegir-dispositivo")))
        dlg.update()
        _perf.a_la_vista(dlg)
        x0, y0, x1, y1 = dlg.tabla._lienzo.caja("disp0001xxxxxxxx")
        vista_al_clic.append(dlg.winfo_viewable())
        dlg.tabla.marco.event_generate("<Button-1>", x=(x0 + x1) // 2, y=(y0 + y1) // 2)
        dlg.update()
        elegida_tras_clic.append(dlg.tabla.elegida)

    with _perf.con_perf(tmp / "abrir") as t:
        abrir(accion=pulsar_otra)
        # La raíz vuelve a estar retirada, como al empezar el test.
        raiz.withdraw()
        _perf.vaciar()
        c("al abrir: open-dispositivos y llega-flota, una línea cada uno",
          (len(_perf.lineas(t, "open-dispositivos")), len(_perf.lineas(t, "llega-flota"))),
          (1, 1))
        c("al abrir no se anota «elegir-dispositivo»", antes_del_clic, [0])
        c("la ventana está a la vista para el clic", vista_al_clic, [1])
        c("el clic elige la otra fila", elegida_tras_clic, ["disp0001xxxxxxxx"])
        c("un clic en otra fila anota «elegir-dispositivo» una vez",
          len(_perf.lineas(t, "elegir-dispositivo")), 1)

    # 1b. El intervalo abarca el pintado.
    reservar = tk_fleet.Ficha.reservar
    tk_fleet.Ficha.reservar = lambda self, *a, **k: (time.sleep(0.06), reservar(self, *a, **k))[1]
    try:
        with _perf.con_perf(tmp / "lento") as t:
            abrir()
            _perf.vaciar()
            ms = float(_perf.lineas(t, "llega-flota")[0].split()[3])
            c("llega-flota abarca el pintado", ms >= 50, True)
    finally:
        tk_fleet.Ficha.reservar = reservar

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
