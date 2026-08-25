#!/usr/bin/env python3
"""
Las dos pantallas nuevas, conducidas sin nadie delante.

No se comprueba el aspecto: se comprueba el cableado. Que pulsar "Añadir" acabe
llamando al editor con lo que dice el formulario, que un cambio se refleje en el
config, y que la pantalla de penwatch sepa pintar sus filas.

Las ventanas se crean ocultas y no se entra nunca en el bucle de eventos.
"""

import sys

from _harness import Checks, sandbox

from common import config_file, model

c = Checks("pantallas Tk (cableado)")

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(0)

from ui import tk_pairs, tk_watch


def ocultar(modulo):
    """Los diálogos se crean pero no se enseñan: esto no es una demo."""
    original = modulo.modal

    def _modal(parent, title):
        dlg = original(parent, title)
        dlg.withdraw()
        return dlg
    modulo.modal = _modal


def pulsar(texto):
    """Un wait_window que, en vez de esperar, pulsa un botón y vuelve."""
    def _wait(self, *_a, **_k):
        pila = [self]
        while pila:
            w = pila.pop()
            pila += list(w.winfo_children())
            if isinstance(w, ttk.Button) and w.cget("text") == texto:
                w.invoke()
                return
    return _wait


ocultar(tk_pairs)
ocultar(tk_watch)
messagebox.askokcancel = lambda *a, **k: True            # se confirma todo
messagebox.showinfo = lambda *a, **k: None
messagebox.showerror = lambda *a, **k: None

BASE = {"defaults": {"remote": "synology"},
        "pair": [{"name": "notas", "local": "sync-data/notas",
                  "remote_path": "/R/notas", "mode": "bisync"},
                 {"name": "subida", "local": "sync-data/subida",
                  "remote_path": "/R/subida", "mode": "up"}]}


def preparar():
    model.CONFIG_FILE.write_text(config_file.dumps(BASE), encoding="utf-8")
    return model.parse_config(BASE)


# --- añadir una pareja desde la pantalla -------------------------------------
with sandbox():
    cfg = preparar()
    tk_pairs.formulario = lambda parent, raw, original, actual: {
        "name": "fotos", "local": "sync-data/fotos", "remote_path": "/R/fotos",
        "mode": "up", "include": [], "exclude": []}
    tk.Toplevel.wait_window = pulsar("Añadir…")

    cambiado = tk_pairs.open_dialog(raiz, cfg)
    c("añadir informa de que hubo cambios", cambiado, True)
    c("la pareja está en el config", model.load_config().names,
      ["notas", "subida", "fotos"])

# --- editar un extremo: la pantalla aparta el baseline ------------------------
with sandbox():
    cfg = preparar()
    pareja = next(p for p in cfg.pairs if p.name == "notas")
    pareja.workdir.mkdir(parents=True, exist_ok=True)
    from common import bisync
    prefijo = bisync.expected_prefix(pareja)
    for sufijo in (bisync.PATH1_SUFFIX, bisync.PATH2_SUFFIX):
        (pareja.workdir / f"{prefijo}{sufijo}").write_text("x", encoding="utf-8")

    tk_pairs.formulario = lambda parent, raw, original, actual: {
        **actual, "remote_path": "/R/otro", "include": [], "exclude": []}
    tk.Toplevel.wait_window = pulsar("Editar…")

    # sin selección, la pantalla no hace nada y lo dice
    cambiado = tk_pairs.open_dialog(raiz, cfg)
    c("editar sin seleccionar no cambia nada", cambiado, False)

    # con selección: se elige la primera fila antes de pulsar
    def elegir_y_pulsar(texto):
        def _wait(self, *_a, **_k):
            pila, arbol, boton = [self], None, None
            while pila:
                w = pila.pop()
                pila += list(w.winfo_children())
                if isinstance(w, ttk.Treeview):
                    arbol = w
                elif isinstance(w, ttk.Button) and w.cget("text") == texto:
                    boton = w
            if arbol is not None and arbol.get_children():
                arbol.selection_set(arbol.get_children()[0])
            if boton is not None:
                boton.invoke()
        return _wait

    tk.Toplevel.wait_window = elegir_y_pulsar("Editar…")
    cambiado = tk_pairs.open_dialog(raiz, cfg)
    c("editar el extremo informa del cambio", cambiado, True)
    c("el config apunta al destino nuevo",
      next(p.remote_path for p in model.load_config().pairs if p.name == "notas"),
      "/R/otro")
    c("y el baseline se ha apartado, como manda el editor",
      any(p.name.startswith("notas.old-") for p in model.STATE_DIR.iterdir()), True)

# --- la pantalla de penwatch pinta su estado ---------------------------------
with sandbox():
    cfg = preparar()
    tk.Toplevel.wait_window = pulsar("Cerrar")
    try:
        tk_watch.open_dialog(raiz, cfg)
        c("la pantalla de penwatch se abre y se cierra", True, True)
    except Exception as e:
        c("la pantalla de penwatch se abre y se cierra", f"{type(e).__name__}: {e}", True)

    tk.Toplevel.wait_window = pulsar("Detectar el pen")
    try:
        tk_watch.open_dialog(raiz, cfg)
        c("'Detectar el pen' no revienta", True, True)
    except Exception as e:
        c("'Detectar el pen' no revienta", f"{type(e).__name__}: {e}", True)

sys.exit(c.report())
