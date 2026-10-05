#!/usr/bin/env python3
"""Cómo se le pregunta a la persona y cómo se le enseña el resultado.

Hay dos frontends con la misma interfaz (`Frontend`) y quién atiende se decide
probando: Tkinter si hay entorno gráfico y, si no, el menú de consola. Da igual
cuál sea: `start()` devuelve la elección junto con el frontend que la ha
atendido, porque quien ha preguntado es también quien sabe enseñar la respuesta
(una ventana no puede volcar su salida a una consola que no existe, ni al
revés).

    choice, frontend = ui.start(config, aviso)
    frontend.info("...")            # enseñar un mensaje
    frontend.approve_resync([...])  # preguntar sí/no
    frontend.run_sync(titulo, args) # lanzar sync.py y enseñar su salida

Tkinter se importa SIEMPRE dentro de las funciones, nunca arriba: este paquete
lo importan también los caminos sin interfaz (`--auto`, el servicio), donde
puede no haber tkinter instalado ni display al que conectarse.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, NamedTuple, Protocol

from common import bisync, results, store
from common.model import Config

HAS_TTY = bool(sys.stdout) and sys.stdout.isatty()
"""Si hay una consola de verdad detrás.

Bajo `pythonw`, `sys.stdout` es `None` y `print()` es un no-op silencioso, así
que los `print` sueltos no rompen nada.
"""


class Choice(NamedTuple):
    """Lo que se ha pedido en la UI; `doctor` no usa parejas ni intervalo.

    Args:
        action: `manual`, `daemon` o `doctor`.
        pairs: Las parejas elegidas.
        minutes: El intervalo del servicio.
    """
    action: str
    pairs: tuple[str, ...] = ()
    minutes: float = 0.0


class Frontend(Protocol):
    """Lo que sabe hacer una interfaz, sea ventana o consola."""

    def ask(self, config: Config, startup_msg: str | None) -> Choice | None:
        """Enseña el menú y devuelve la elección, o `None` si se cierra.

        Args:
            startup_msg: Aviso de arranque que se enseña con el menú.
        """

    def approve_resync(self, pending: list[str]) -> bool:
        """Pregunta si se aprueba el `--resync` de esas parejas."""

    def info(self, msg: str) -> None:
        """Enseña un mensaje."""

    def run_sync(self, title: str, args: list[str]) -> int:
        """Lanza `sync.py`, enseña su salida y devuelve su código."""


def pair_status_notes(config: Config) -> dict[str, str]:
    """Devuelve `requiere resync` junto a las parejas bisync sin baseline válido."""
    notes = {}
    for pair in config.pairs:
        try:
            if bisync.resync_reasons(pair):
                notes[pair.name] = "requiere resync"
        except Exception:
            pass  # un estado ilegible no puede impedir que se abra la UI
    return notes


def manual_args(config: Config, pairs, approve: Callable[[list[str]], bool]) -> list[str]:
    """Devuelve los argumentos de `sync.py` para una pasada manual de esas parejas.

    Las que piden un `--resync` se le preguntan a quien ha elegido (`approve`),
    UNA vez para todas: si dice que sí va `--yes` y, si no, `sync.py` las
    salta. Lo comparten la ventana, que lanza la pasada sin cerrarse, y
    `runsync` para el menú de consola.
    """
    args = list(pairs)
    pending = [n for n in pair_status_notes(config) if n in args]
    if pending and approve(pending):
        args.append("--yes")
    return args


def abrir(ruta: Path) -> None:
    """Abre un fichero o una carpeta con lo que el sistema tenga para ello.

    Es `os.startfile` en Windows y no un `explorer.exe` lanzado a mano: lo abre
    el propio sistema, sin intérprete de órdenes de por medio (ver
    `install/crypto.py`, que hace lo mismo por el mismo motivo). En Linux es
    `xdg-open`, sin shell. Es de módulo para que los tests lo sustituyan:
    ninguno abre nada de verdad.

    Raises:
        OSError: Si no se puede abrir.
    """
    if os.name == "nt":
        os.startfile(str(ruta))                    # type: ignore[attr-defined]
        return
    subprocess.Popen(["xdg-open", str(ruta)], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


_aviso_abierto: dict = {"hilo": None, "cola": None, "activo": False}
"""El hilo de las ventanitas de fallo, su cola de trabajos y si hay una en curso.

El hilo es uno por proceso y no acaba entre un aviso y el siguiente: espera en
su cola. Con Tcl/Tk 9 (los runtimes de Linux) crear un intérprete de Tk en un
hilo NUEVO después de que otro hilo hubiera creado el suyo y acabado hace
abortar el proceso (`Tcl_Panic: epoll_ctl: Invalid argument`, medido con
Tcl/Tk 9.0.4 en una prueba de cuatro líneas, sin código de prdrive). Crear y
destruir varios intérpretes seguidos en el MISMO hilo, o varios hilos a la vez,
va bien.
"""


def _hilo_de_avisos():
    """Devuelve la cola del hilo de las ventanitas, arrancándolo si no está vivo."""
    import queue
    import threading

    hilo = _aviso_abierto["hilo"]
    if hilo is not None and hilo.is_alive():
        return _aviso_abierto["cola"]
    cola: queue.SimpleQueue = queue.SimpleQueue()

    def servir() -> None:
        """Corre los trabajos de la cola, uno tras otro, sin acabar nunca."""
        while True:
            cola.get()()

    hilo = threading.Thread(target=servir, daemon=True, name="aviso-fallo")
    _aviso_abierto["hilo"], _aviso_abierto["cola"] = hilo, cola
    hilo.start()
    return cola


def avisar_fallo(nombres: list[str], espera: float = 10.0) -> bool:
    """Enseña la ventanita con la que el servicio dice que un ciclo ha fallado.

    Devuelve `False` si no hay entorno gráfico, para que quien llama lo apunte
    en su diario (la misma caída que hace `start()` a la consola).

    Va en un hilo propio con su propio intérprete de Tk y no en el del
    servicio, porque el servicio tiene que seguir: una ventana que nadie cierra
    no puede parar la sincronización de las demás parejas, y bombearla desde el
    bucle del servicio la dejaría congelada mientras rclone trabaja. Todo lo de
    Tk ocurre dentro de ese hilo, que es lo que Tk exige. Ese hilo es siempre el
    mismo (`_aviso_abierto`): uno nuevo por aviso hace abortar a Tk 9. No se
    lanza ningún proceso: un servicio sin ventana que de repente arranca otro
    programa es justo lo que un antivirus mira mal (ver `install/`).

    Si ya hay una abierta no se abre otra: esa ya dice que falla.

    Args:
        nombres: Las parejas que fallan.
        espera: Segundos que se espera a que la ventana llegue a abrirse.

    Returns:
        `True` si se ha podido enseñar.
    """
    import threading

    if _aviso_abierto["activo"]:
        return True

    from common import results
    fallos = results.fallos_de(nombres)
    abierta = threading.Event()
    hecho = threading.Event()

    def trabajar() -> None:
        """Abre la ventana en el hilo y avisa de si se abrió o acabó."""
        try:
            from . import tk
            tk.aviso_fallo(fallos, al_abrir=abierta.set)
        except Exception:                            # noqa: BLE001
            pass                 # sin tkinter o sin display: lo dirá el diario
        finally:
            _aviso_abierto["activo"] = False
            hecho.set()

    _aviso_abierto["activo"] = True
    try:
        _hilo_de_avisos().put(trabajar)
    except BaseException:
        _aviso_abierto["activo"] = False
        raise
    limite = espera
    while limite > 0 and not abierta.is_set() and not hecho.is_set():
        abierta.wait(0.05)
        limite -= 0.05
    return abierta.is_set()


def cuando_sello(sello: str) -> str:
    """Devuelve `cuando()` para una fecha escrita con `store.stamp()`."""
    return cuando(store.desde_sello(sello))


def cuando(marca: float | None) -> str:
    """Devuelve una fecha como la enseña la ventana.

    Es la hora si es de hoy, «ayer» si es de ayer y el día si es más vieja:
    nadie necesita el año de la última pasada.
    """
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
    """Devuelve cuándo se sincronizó bien cada pareja por última vez.

    Se devuelve la marca de tiempo y no el texto porque quien llama también
    necesita compararlas (la «última pasada» de la cabecera es la más reciente
    de todas), y ordenar por el texto pondría «ayer» por delante de «08:20».
    `None` para las que aún no han corrido: ahí la ventana enseña un guion, que
    es la verdad.

    Hacen falta dos fuentes. Los listados de bisync (`bisync.last_run`) son la
    fecha de la última pasada buena para las parejas que los tienen, incluidas
    las de un dispositivo que ya sincronizaba antes de que existiera el
    registro. Lo apuntado en `state/last_run.json` (`results.ultimas_buenas`)
    cubre a las demás (un `copy` o un `*-mirror` no deja estado ninguno) y lo
    hace sin importar quién lanzó la pasada: la ventana, una terminal, el
    servicio periódico o el vigilante. La más reciente de las dos es la
    respuesta.
    """
    try:
        apuntadas = results.ultimas_buenas(config.names)
    except Exception:
        apuntadas = {}            # un estado ilegible no impide abrir la UI
    marcas: dict[str, float | None] = {}
    for pair in config.pairs:
        try:
            listados = bisync.last_run(pair)
        except Exception:
            listados = None
        candidatas = [m for m in (listados, apuntadas.get(pair.name)) if m]
        marcas[pair.name] = max(candidatas) if candidatas else None
    return marcas


def start(config: Config, startup_msg: str | None) -> tuple[Choice | None, Frontend]:
    """Abre la interfaz que se pueda y devuelve `(elección, frontend)`.

    Cualquier fallo al montar la ventana (no hay tkinter, no hay display, el
    servidor X se cayó) es motivo suficiente para caer a la consola: el aviso
    de arranque se reimprime ahí, porque la ventana que iba a enseñarlo no
    existe.
    """
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


def abrir_llavero(config: Config) -> int:
    """Hace «Abrir llavero» sin la ventana de prdrive (`runsync.py --llavero`, `Llavero.bat`).

    Con entorno gráfico, con los diálogos de `ui/tk_llavero.py`, colgados de
    una raíz que no se enseña. Sin él, por la consola y sin preguntar nada: si
    la base pide fichero llave y no se sabe dónde está, KeePassXC lo pedirá, y
    las copias de conflicto no se combinan (se ofrece la próxima vez).
    Solo se cae a la consola si no se puede crear la raíz: un fallo a mitad de
    los pasos no los repite.

    Returns:
        0 si KeePassXC se ha abierto; 1 si no.
    """
    from . import llavero_editor
    try:
        from . import tk as tk_
        root = tk_.root_oculto()
    except Exception:                                # noqa: BLE001 — sin Tk o sin display
        root = None
    if root is None:
        def esperar(mensaje: str, funcion):
            """Corre `funcion()` aquí mismo, diciendo antes qué se hace."""
            print(mensaje)
            try:
                return True, funcion()
            except Exception as e:                   # noqa: BLE001 — se dice
                return False, e
        hecho = llavero_editor.abrir(config, print, esperar, lambda nombre: None,
                                     lambda plan, titulo, nota: False, decir_sin_traer=True)
        return 0 if hecho else 1
    from . import tk_llavero
    try:
        hecho = tk_llavero.abrir(root, config, suelto=True)
    except Exception as e:                           # noqa: BLE001 — se dice, no se repite
        error: Exception | None = e
    else:
        error = None
    finally:
        root.destroy()
    if error is not None:
        return fatal(f"No se ha podido abrir el llavero:\n\n{error}")
    return 0 if hecho else 1


def fatal(msg: str) -> int:
    """Enseña un error irrecuperable, visible aunque no haya consola.

    Devuelve 1 para poder escribir `return fatal(...)` en quien llama.
    """
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
