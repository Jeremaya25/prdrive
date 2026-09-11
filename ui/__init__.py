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

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, NamedTuple, Protocol

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


def manual_args(config: Config, pairs, approve: Callable[[list[str]], bool]) -> list[str]:
    """Los argumentos de sync.py para una pasada manual de esas parejas.

    Las que piden un --resync se le preguntan a quien ha elegido (`approve`),
    UNA vez para todas; si dice que sí va `--yes`, y si no, sync.py las salta.
    Lo comparten la ventana, que lanza la pasada sin cerrarse, y runsync para el
    menú de consola."""
    args = list(pairs)
    pending = [n for n in pair_status_notes(config) if n in args]
    if pending and approve(pending):
        args.append("--yes")
    return args


def abrir(ruta: Path) -> None:
    """Abre un fichero o una carpeta con lo que el sistema tenga para ello.

    `os.startfile` en Windows y no un `explorer.exe` lanzado a mano: lo abre el
    propio sistema, sin intérprete de órdenes de por medio (ver
    `install/crypto.py`, que hace lo mismo por el mismo motivo). En Linux es
    `xdg-open`, sin shell. Lanza OSError si no se puede, y es de módulo para que
    los tests lo sustituyan: ninguno abre nada de verdad."""
    if os.name == "nt":
        os.startfile(str(ruta))                    # type: ignore[attr-defined]
        return
    subprocess.Popen(["xdg-open", str(ruta)], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


_aviso_abierto: dict = {"hilo": None}


def avisar_fallo(nombres: list[str], espera: float = 10.0) -> bool:
    """La ventanita con la que el servicio dice que un ciclo ha fallado.

    Devuelve True si se ha podido enseñar, y False si no hay entorno gráfico,
    para que quien llama lo apunte en su diario —la misma caída que hace
    `start()` a la consola—.

    Va en un hilo propio con su propio intérprete de Tk, y no en el del
    servicio, porque el servicio tiene que seguir: una ventana que nadie cierra
    no puede parar la sincronización de las demás parejas, y bombearla desde el
    bucle del servicio la dejaría congelada mientras rclone trabaja. Todo lo de
    Tk ocurre dentro de ese hilo, que es lo que Tk exige. No se lanza ningún
    proceso: un servicio sin ventana que de repente arranca otro programa es
    justo lo que un antivirus mira mal (ver `install/`).

    Si ya hay una abierta no se abre otra: esa ya dice que falla."""
    import threading

    hilo = _aviso_abierto["hilo"]
    if hilo is not None and hilo.is_alive():
        return True

    from common import results
    fallos = results.fallos_de(nombres)
    abierta = threading.Event()
    hecho = threading.Event()

    def trabajar() -> None:
        try:
            from . import tk
            tk.aviso_fallo(fallos, al_abrir=abierta.set)
        except Exception:                            # noqa: BLE001
            pass                 # sin tkinter o sin display: lo dirá el diario
        finally:
            hecho.set()

    hilo = threading.Thread(target=trabajar, daemon=True, name="aviso-fallo")
    _aviso_abierto["hilo"] = hilo
    hilo.start()
    limite = espera
    while limite > 0 and not abierta.is_set() and not hecho.is_set():
        abierta.wait(0.05)
        limite -= 0.05
    return abierta.is_set()


def cuando_sello(sello: str) -> str:
    """`cuando()` para una fecha escrita con `store.stamp()`."""
    try:
        return cuando(datetime.strptime(sello, "%Y-%m-%d %H:%M:%S").timestamp())
    except (TypeError, ValueError):
        return ""


def cuando(marca: float | None) -> str:
    """Una fecha como la enseña la ventana: la hora si es de hoy, 'ayer' si es de
    ayer, y el día si es más vieja. Nadie necesita el año de la última pasada."""
    if not marca:
        return ""
    momento = datetime.fromtimestamp(marca)
    dias = (datetime.now().date() - momento.date()).days
    if dias <= 0:
        return momento.strftime("%H:%M")
    if dias == 1:
        return "ayer"
    return momento.strftime("%d/%m")


def pair_times(config: Config) -> dict[str, float | None]:
    """Cuándo se sincronizó bien cada pareja por última vez.

    Se devuelve la marca de tiempo y no el texto porque quien llama también
    necesita compararlas —«última pasada» de la cabecera es la más reciente de
    todas—, y ordenar por el texto pondría 'ayer' por delante de '08:20'. None
    para las que no dejan rastro (todo lo que no es bisync) y para las que aún no
    han corrido: ahí la ventana enseña un guion, que es la verdad."""
    marcas: dict[str, float | None] = {}
    for pair in config.pairs:
        try:
            marcas[pair.name] = bisync.last_run(pair)
        except Exception:
            marcas[pair.name] = None  # un estado ilegible no impide abrir la UI
    return marcas


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
            from tkinter import messagebox

            from . import tk as tk_
            root = tk_.root_oculto()
            messagebox.showerror(tk_.TITLE, msg)
            root.destroy()
        except Exception:
            pass
    return 1
