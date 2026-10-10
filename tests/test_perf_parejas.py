#!/usr/bin/env python3
"""«Parejas» apunta sus tiempos con `PRDRIVE_PERF=1`: cada momento, una línea por vez.

Con la medida encendida, cada momento de «Parejas» deja su línea en `logs/perf.log`
(`ui/__init__.py`: los `perf_*`); apagada, no se escribe nada. Aquí se prueba con la
ventana real y `mostrar()` real:

- `open-parejas`: su final es el `mostrar()` de `open_dialog()`. El inicio lo pondrá
  `abrir_parejas` (Tarea 2); aquí se pone a mano;
- `catalogo-llega`: lo que llega del remoto repinta y cierra su momento;
- `elegir-pareja`: un clic en una fila de la lista (no `ListaParejas.elegir`), y que
  elegir la misma fila no anota nada;
- `open-pareja`: «Modificar…», hasta que la ventana de la pareja está pintada;
- `open-flags`: el editor de flags de una pareja, con su `flags_form()` real; un
  `flags_form()` sin inicio (el de «Ajustes de este dispositivo») no anota nada;
- `open-dispositivos`: solo su inicio, en `ver_flota()`. Su final es de la ventana de
  «Dispositivos», que lo anota en su propio `mostrar()`: aquí no se puede comprobar;
- con la variable apagada, ni fichero.

Los diálogos se manejan sustituyendo `Toplevel.wait_window`: `mostrar()` corre
entero (enseña la ventana y programa el momento) y lo que iba a esperar lo hace la
prueba, mientras la ventana está enseñada. La parte de Tk se salta sin pantalla o
sin `tkinter`.
"""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from pathlib import Path
from subprocess import CompletedProcess

from _harness import Checks, sandbox

import _perf

c = Checks("«Parejas» apunta sus tiempos con PRDRIVE_PERF")

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

import ui  # noqa: E402
from common import catalog, config_file, model  # noqa: E402
from ui import segundo_plano, tk_fleet, tk_pairs  # noqa: E402
from ui import tk as uitk  # noqa: E402

errores: list[str] = []
raiz.report_callback_exception = (
    lambda tipo, valor, _tb: errores.append(f"{tipo.__name__}: {valor}"))
messagebox.showerror = lambda titulo, texto=None, **k: errores.append(str(texto))
messagebox.showinfo = lambda *a, **k: None
messagebox.showwarning = lambda *a, **k: None
messagebox.askyesno = lambda *a, **k: True
messagebox.askokcancel = lambda *a, **k: True

BASE = {"defaults": {"remote": "nas"},
        "pair": [{"name": "notas", "local": "sync-data/notas",
                  "remote_path": "/R/notas", "mode": "bisync"},
                 {"name": "subida", "local": "sync-data/subida",
                  "remote_path": "/R/subida", "mode": "up"}]}
CATALOGO = {"defaults": {"remote": "nas"}, "pair": [dict(p) for p in BASE["pair"]]}
RAW_EDITOR = {"defaults": {"remote": "nas"}}
PAREJA = {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas",
          "mode": "bisync", "flags": {"transfers": 4}}


class RemotoRapido:
    """Un `catalog.run()` que contesta enseguida con el catálogo de `CATALOGO`."""

    def __call__(self, args):
        return CompletedProcess(args, 0, stdout=config_file.dumps(CATALOGO), stderr="")


catalog.run = RemotoRapido()
segundo_plano.olvidar_lecturas()


def preparar() -> model.Config:
    """Escribe el config de prueba y lo devuelve ya parseado."""
    model.CONFIG_FILE.write_text(config_file.dumps(BASE), encoding="utf-8")
    return model.parse_config(BASE)


def buscar(ventana, clase, texto: str):
    """El primer widget de esa clase con ese texto, o `None`."""
    pila = [ventana]
    while pila:
        w = pila.pop()
        if isinstance(w, clase) and str(w.cget("text")) == texto:
            return w
        pila += list(w.winfo_children())
    return None


def pulsar_fila(dlg, nombre: str, a_lo_ancho: float = 0.5) -> int:
    """Hace un clic en la fila de esa pareja, sobre el lienzo de «Parejas» (como el ratón).

    Args:
        a_lo_ancho: En qué punto de la fila, de 0 (izquierda) a 1. Dos clics
            seguidos en el mismo punto son para Tk un doble clic, que abre la
            ventana de la pareja: un segundo clic suelto va en otro punto.

    Returns:
        Si la ventana estaba a la vista justo antes del clic (`winfo_viewable()`).
    """
    dlg.update()
    _perf.a_la_vista(dlg)
    x0, y0, x1, y1 = dlg.lista.tabla.caja(nombre)
    vista = dlg.winfo_viewable()
    dlg.lista.marco.event_generate("<Button-1>", x=x0 + int((x1 - x0) * a_lo_ancho),
                                   y=(y0 + y1) // 2)
    return vista


@contextmanager
def esperando_con(conducir):
    """Mientras dura el bloque, cada `Toplevel.wait_window()` llama a `conducir(ventana)`.

    `mostrar()` ya ha enseñado la ventana y programado su momento cuando esto
    corre; al volver, la ventana se destruye (lo que espera `mostrar()`).
    """
    original = tk.Toplevel.wait_window

    def espera(self, *_a, **_k):
        """Conduce la ventana y la cierra."""
        try:
            conducir(self)
        finally:
            if self.winfo_exists():
                self.destroy()

    tk.Toplevel.wait_window = espera
    try:
        yield
    finally:
        tk.Toplevel.wait_window = original


def esperar_linea(dlg, t: Path, momento: str, limite: float = 5.0) -> None:
    """Mueve el bucle de Tk hasta que `momento` aparezca en el diario de `t`, o pase el límite."""
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        dlg.update()
        _perf.vaciar()
        if _perf.lineas(t, momento):
            return
        time.sleep(0.01)


def abrir_parejas(conducir) -> bool:
    """Abre «Parejas» con `open_dialog()` real y deja que `conducir(dlg)` la maneje.

    Args:
        conducir: Lo que hace la prueba con la ventana enseñada.

    Returns:
        Lo que devuelve `open_dialog()`.
    """
    cfg = preparar()
    with esperando_con(conducir):
        return tk_pairs.open_dialog(raiz, cfg)


def editor_de_flags():
    """Un `EditorPareja` ya cargado, con sus flags a la vista (sin plegar)."""
    dlg = uitk.modal(raiz, "Editor")
    marco = ttk.Frame(dlg)
    marco.grid()
    editor = tk_pairs.EditorPareja(marco, dlg, sup="", dos_columnas=False, plegable=False)
    editor.marco.grid()
    editor.cargar(RAW_EDITOR, PAREJA, "notas")
    return dlg, editor


def probar_con_perf() -> None:
    """Cada momento de «Parejas» deja su línea, una vez, con la medida encendida."""
    with sandbox() as raiz_prueba:
        tmp = Path(raiz_prueba)

        # open-parejas y catalogo-llega: abrir la pantalla, con el catálogo que llega.
        with _perf.con_perf(tmp / "abrir") as t:
            # Lo pondrá `abrir_parejas` (Tarea 2); aquí se pone a mano.
            ui.perf_empezar("open-parejas")

            def esperar_catalogo(dlg):
                """Deja que llegue el catálogo: su momento cierra en ese repintado."""
                esperar_linea(dlg, t, "catalogo-llega")
                dlg.update()

            abrir_parejas(esperar_catalogo)
            _perf.vaciar()
            c("open-parejas: una línea al mostrarse la pantalla",
              len(_perf.lineas(t, "open-parejas")), 1)
            c("catalogo-llega: una línea cuando llega el catálogo",
              len(_perf.lineas(t, "catalogo-llega")), 1)

        # elegir-pareja: un clic en una fila la elige; otro clic en la misma no anota nada.
        with _perf.con_perf(tmp / "elegir") as t:
            ui.perf_empezar("open-parejas")
            elegida: list[str | None] = []
            vistas: list[int] = []
            abiertas_al_elegir: list = []

            def clicar(dlg):
                """Espera el catálogo, pulsa «subida» dos veces y mira qué queda elegido."""
                esperar_linea(dlg, t, "catalogo-llega")
                vistas.append(pulsar_fila(dlg, "subida"))
                dlg.update()
                _perf.vaciar()
                elegida.append(dlg.lista.elegida)
                vistas.append(pulsar_fila(dlg, "subida", a_lo_ancho=0.25))
                dlg.update()
                _perf.vaciar()
                abiertas_al_elegir.append(dlg.pantalla.ventana)

            abrir_parejas(clicar)
            # La raíz vuelve a estar retirada, como al empezar el test.
            raiz.withdraw()
            c("la ventana está a la vista para el clic", vistas, [1, 1])
            c("elegir-pareja: el clic elige la fila",
              elegida, ["subida"])
            c("elegir-pareja: una línea por elección; elegir la misma fila no anota nada",
              len(_perf.lineas(t, "elegir-pareja")), 1)
            c("  y dos clics sueltos en una fila no abren la ventana de la pareja",
              abiertas_al_elegir, [None])

        # open-pareja: «Modificar…» abre la ventana de la pareja elegida, con su `mostrar()` real.
        with _perf.con_perf(tmp / "pareja") as t:
            abiertas: list[str] = []

            def modificar(ventana):
                """En «Parejas», pulsa «Modificar…»; en la ventana de la pareja, la deja pintarse."""
                if hasattr(ventana, "ventana"):
                    abiertas.append(ventana.ventana.nombre)
                    esperar_linea(ventana, t, "open-pareja")
                    return
                esperar_linea(ventana, t, "catalogo-llega")
                buscar(ventana, ttk.Button, "Modificar…").invoke()

            abrir_parejas(modificar)
            raiz.withdraw()
            _perf.vaciar()
            c("open-pareja: «Modificar…» abre la ventana de la pareja elegida",
              abiertas, ["notas"])
            c("open-pareja: una línea al mostrarse la ventana de la pareja",
              len(_perf.lineas(t, "open-pareja")), 1)

        # open-flags: el editor de la pareja abre sus flags con `flags_form()` real.
        with _perf.con_perf(tmp / "flags") as t:
            dlg, editor = editor_de_flags()

            def cerrar_flags(ventana):
                """Deja que la ventana de los flags se pinte, y la cierra sin cambiar nada."""
                ventana.update()

            with esperando_con(cerrar_flags):
                editor.boton_flags.invoke()
            _perf.vaciar()
            c("open-flags: una línea al mostrarse el editor de flags",
              len(_perf.lineas(t, "open-flags")), 1)

            # Sin inicio (el editor de flags de «Ajustes de este dispositivo»), nada.
            with esperando_con(cerrar_flags):
                tk_pairs.flags_form(dlg, "Flags", "de prueba", {"transfers": 8}, [],
                                    mode_name="bisync", defaults_flags=None)
            _perf.vaciar()
            c("open-flags: un flags_form() sin inicio no anota nada",
              len(_perf.lineas(t, "open-flags")), 1)
            dlg.destroy()

        # open-dispositivos: solo su inicio, en `ver_flota()`.
        with _perf.con_perf(tmp / "flota") as t:
            llamadas: list[str] = []
            inicio_original = tk_pairs.perf_empezar
            flota_original = tk_fleet.open_dialog
            tk_pairs.perf_empezar = lambda momento: (llamadas.append(momento),
                                                     inicio_original(momento))
            tk_fleet.open_dialog = lambda *a, **k: None
            try:
                def abrir_flota(dlg):
                    """Pulsa «Dispositivos…» con la pantalla enseñada."""
                    esperar_linea(dlg, t, "catalogo-llega")
                    buscar(dlg, ttk.Button, "Dispositivos…").invoke()

                abrir_parejas(abrir_flota)
            finally:
                tk_pairs.perf_empezar = inicio_original
                tk_fleet.open_dialog = flota_original
            c("open-dispositivos: ver_flota() empieza el momento",
              llamadas.count("open-dispositivos"), 1)

        # Apagada: ni fichero ni línea, con los mismos caminos.
        with _perf.con_perf(tmp / "apagada", activo=False) as t:
            ui.perf_empezar("open-parejas")
            abrir_parejas(lambda dlg: esperar_linea(dlg, t, "catalogo-llega"))
            dlg, editor = editor_de_flags()
            with esperando_con(lambda ventana: ventana.update()):
                editor.boton_flags.invoke()
            dlg.destroy()
        c("con PRDRIVE_PERF apagada no se escribe ningún diario de tiempos",
          (t / "logs" / "perf.log").exists(), False)
        c("y ningún error de Tk en ninguna de las pruebas", errores, [])


probar_con_perf()
sys.exit(c.report())
