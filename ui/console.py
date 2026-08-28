#!/usr/bin/env python3
"""
console.py — La interfaz de consola.

Se usa cuando no hay entorno gráfico (Linux sin escritorio, sesión SSH) o cuando
Tkinter falla. Al haber terminal de verdad, este frontend tiene menos trabajo que
el gráfico: la salida de sync.py va directa a la consola heredando los
descriptores, y las preguntas las hace el propio sync.py.
"""

from __future__ import annotations

import subprocess
import sys

from common import APP_NAME, model, update
from common.model import Config

from . import Choice, pair_status_notes, prefs


class ConsoleFrontend:
    """El frontend de consola. Ver el protocolo `ui.Frontend`."""

    def ask(self, config: Config, startup_msg: str | None) -> Choice | None:
        return main_menu(config, startup_msg)

    def approve_resync(self, pending: list[str]) -> bool:
        """Siempre False, y no es un "no": es un "aquí no hace falta preguntar".
        Con consola, sync.py hereda stdin y plantea él mismo la pregunta, con más
        contexto del que se puede meter en un cuadro de diálogo. Devolver True
        aquí añadiría --yes y le quitaría al usuario esa conversación."""
        return False

    def info(self, msg: str) -> None:
        print(msg)

    def run_sync(self, title: str, args: list[str]) -> int:
        """sync.py en la consola actual, heredando stdin/stdout (preguntas
        incluidas). El título no se usa: la consola ya enseña lo que pasa."""
        return subprocess.run([sys.executable, str(model.SYNC_PY), *args]).returncode


def main_menu(config: Config, startup_msg: str | None) -> Choice | None:
    names = config.names
    notes = pair_status_notes(config)
    d_pairs, d_interval, memo = prefs.startup_defaults(config)

    print(f"\n=== {APP_NAME} ===")
    if startup_msg:
        print(startup_msg)
    for n in names:
        extra = f"   [{notes[n]}]" if n in notes else ""
        print(f"   - {n}{extra}")
    if memo:
        print(f"\n{memo}: {' '.join(d_pairs)}, cada {d_interval:g} min.")

    # El aviso de versión nueva se pinta aquí y no llega por `startup_msg`,
    # porque ese canal lo comparten los dos frontends y la ventana ya se lo
    # dibuja ella sola en ámbar: pasarlo por ahí lo enseñaría dos veces.
    # `pending()` y no `check()`: solo caché, cero red. Nadie va a esperar a
    # GitHub para ver un menú de texto, y la caché ya la refrescan la ventana y
    # el servicio periódico.
    nueva = update.pending()
    if nueva is not None:
        print(f"\nHay una actualización disponible: {nueva.tag} "
              f"(tienes la {update.installed_version() or 'desconocida'}).")
        print(f"Actualiza desde la ventana, o pasa el instalador: {nueva.url}")
    print("\n 1) Sincronizar todo ahora"
          "\n 2) Sincronizar parejas concretas"
          "\n 3) Iniciar servicio periódico"
          "\n 4) Doctor"
          "\n 0) Salir")
    try:
        option = input("Opción: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if option == "1":
        return Choice("manual", tuple(names), d_interval)
    if option == "2":
        raw = input(f"Parejas (separadas por espacio) [{' '.join(d_pairs)}]: ").strip()
        sel = [n for n in raw.split() if n in names] or d_pairs
        return Choice("manual", tuple(sel), d_interval)
    if option == "3":
        raw = input(f"Parejas del servicio [{' '.join(d_pairs)}]: ").strip()
        sel = [n for n in raw.split() if n in names] or d_pairs
        raw = input(f"Intervalo en minutos [{d_interval:g}]: ").strip()
        try:
            minutes = max(1.0, float(raw.replace(",", "."))) if raw else d_interval
        except ValueError:
            minutes = d_interval
        return Choice("daemon", tuple(sel), minutes)
    if option == "4":
        return Choice("doctor")
    return None
