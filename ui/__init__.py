#!/usr/bin/env python3
"""
ui — Cómo se le pregunta al usuario y cómo se le enseña el resultado.

Hay dos frontends con la misma interfaz, y quién atiende se decide probando:
Tkinter si hay entorno gráfico, y si no, el menú de consola. Da igual cuál sea:
`start()` devuelve la elección junto con el frontend que la ha atendido, porque
quien ha preguntado es también quien sabe enseñar la respuesta —una ventana no
puede volcar su salida a una consola que no existe, y al revés—.

    choice, frontend = ui.start(config, aviso)
    frontend.info("...")            enseñar un mensaje
    frontend.approve_resync([...])  preguntar sí/no
    frontend.run_sync(titulo, args) lanzar sync.py y enseñar su salida

Tkinter se importa SIEMPRE dentro de las funciones, nunca arriba: este paquete
lo importan también los caminos sin interfaz (--auto, el servicio), y ahí puede
no haber tkinter instalado ni display al que conectarse.
"""

from __future__ import annotations

import sys
from typing import NamedTuple, Protocol

from common import bisync
from common.model import Config

# ¿Hay una consola de verdad detrás? Bajo pythonw, sys.stdout es None (y print()
# se convierte en un no-op silencioso, así que los print sueltos no rompen nada).
HAS_TTY = bool(sys.stdout) and sys.stdout.isatty()


class Choice(NamedTuple):
    """Lo que se ha pedido en la UI. 'doctor' no usa parejas ni intervalo."""
    action: str                        # 'manual' | 'daemon' | 'doctor'
    pairs: tuple[str, ...] = ()
    minutes: float = 0.0


class Frontend(Protocol):
    """Lo que sabe hacer una interfaz, sea ventana o consola."""

    def ask(self, config: Config, startup_msg: str | None) -> Choice | None: ...

    def approve_resync(self, pending: list[str]) -> bool: ...

    def info(self, msg: str) -> None: ...

    def run_sync(self, title: str, args: list[str]) -> int: ...


def pair_status_notes(config: Config) -> dict[str, str]:
    """'requiere resync' junto a las parejas bisync sin baseline válido."""
    notes = {}
    for pair in config.pairs:
        try:
            if bisync.resync_reasons(pair):
                notes[pair.name] = "requiere resync"
        except Exception:
            pass  # un estado ilegible no puede impedir que se abra la UI
    return notes


def start(config: Config, startup_msg: str | None) -> tuple[Choice | None, Frontend]:
    """Abre la interfaz que se pueda y devuelve (elección, frontend).

    Cualquier fallo al montar la ventana —no hay tkinter, no hay display, el
    servidor X se cayó— es motivo suficiente para caer a la consola: el aviso de
    arranque se reimprime ahí, porque la ventana que iba a enseñarlo no existe."""
    try:
        from . import tk
        frontend: Frontend = tk.TkFrontend()
        return frontend.ask(config, startup_msg), frontend
    except Exception:
        from . import console
        if startup_msg:
            print(startup_msg)
        frontend = console.ConsoleFrontend()
        return frontend.ask(config, startup_msg=None), frontend


def fatal(msg: str) -> int:
    """Error irrecuperable, visible aunque no haya consola. Devuelve 1 para
    poder escribir `return fatal(...)` en quien llama."""
    if sys.stderr:
        try:
            print(msg, file=sys.stderr)
        except OSError:
            pass
    if not HAS_TTY:
        try:
            import tkinter as tkinter_
            from tkinter import messagebox
            root = tkinter_.Tk()
            root.withdraw()
            messagebox.showerror("PerePen Sync", msg)
            root.destroy()
        except Exception:
            pass
    return 1
