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
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Mapping, NamedTuple, Protocol

from common import store

if TYPE_CHECKING:
    from common.model import Config


TK_CON_XFT = Path("lib") / "tk-xft" / "libtcl9tk9.0.so"
"""El Tk con Xft dentro de un runtime de Linux (`install.runtime_bin.TK_DIR`)."""


def tk_con_xft(prefijo: str | os.PathLike | None = None) -> bool:
    """Carga el Tk con Xft del runtime antes que el de serie, si se puede, y dice si lo hizo.

    El Tk que trae el Python del dispositivo en Linux está compilado sin Xft:
    solo ve las fuentes de mapa de bits de X11 y la letra sale sin suavizar. El
    instalador deja al lado uno compilado con Xft (`pins.TK_XFT_VERSION`), con
    el mismo nombre y SONAME, y cargarlo aquí con `RTLD_GLOBAL` hace que
    `_tkinter`, al pedir `libtcl9tk9.0.so`, se quede con este y no cargue el
    otro.

    Tiene que correr antes del primer `import tkinter`, y por eso va al cargar
    este paquete, que es por donde entra toda ventana. No hace nada si tkinter
    ya está cargado, fuera de Linux o si no hay tal biblioteca (el Python de un
    equipo, una instalación sin ella). Si no carga (el equipo no tiene
    `libXft`, un servidor sin escritorio), se calla: queda el de serie, que es
    el que había.

    Args:
        prefijo: La raíz del runtime; por defecto, la del Python que corre.
    """
    if "_tkinter" in sys.modules or not sys.platform.startswith("linux"):
        return False
    ruta = Path(prefijo or sys.prefix) / TK_CON_XFT
    if not ruta.is_file():
        return False
    try:
        import ctypes
        ctypes.CDLL(str(ruta), mode=ctypes.RTLD_GLOBAL)
    except OSError:
        return False
    return True


tk_con_xft()

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

    def approve_resync(self, pending: list[str],
                       carpetas: Mapping[str, str] | None = None) -> bool:
        """Pregunta si se aprueba el `--resync` de esas parejas.

        Args:
            pending: Las parejas que lo piden.
            carpetas: Por pareja, dónde está en el remoto la copia del programa
                que subió (`carpetas_del_programa()`), para decirlo antes de que
                el resync borre el rastro. Vacío si no hay ninguna.
        """

    def info(self, msg: str) -> None:
        """Enseña un mensaje."""

    def run_sync(self, title: str, args: list[str]) -> int:
        """Lanza `sync.py`, enseña su salida y devuelve su código."""


def pair_status_notes(config: Config) -> dict[str, str]:
    """Devuelve `requiere resync` junto a las parejas bisync sin baseline válido.

    El llavero no sale: se resincroniza solo.
    """
    from common import bisync

    notes = {}
    for pair in config.pairs:
        if pair.llavero:
            continue
        try:
            if bisync.resync_reasons(pair):
                notes[pair.name] = "requiere resync"
        except Exception:
            pass  # un estado ilegible no puede impedir que se abra la UI
    return notes


def carpetas_del_programa(config: Config, nombres) -> dict[str, str]:
    """Devuelve, de esas parejas, dónde está en el remoto el programa que subieron.

    Es lo que `revision.carpeta_programa_en_remoto()` dice de cada una: solo
    salen las que subieron la carpeta del programa. Un listado ilegible no
    impide preguntar por el resync, igual que en `pair_status_notes()`.
    """
    from common import revision

    carpetas = {}
    for pair in config.pairs:
        if pair.name not in nombres:
            continue
        try:
            carpeta = revision.carpeta_programa_en_remoto(pair)
        except Exception:
            continue
        if carpeta is not None:
            carpetas[pair.name] = carpeta
    return carpetas


def avisos_de_resync(carpetas: Mapping[str, str]) -> list[str]:
    """Devuelve, por pareja, la frase que dice dónde borrar a mano la copia del programa."""
    from common import revision

    return [f"{nombre}: {revision.aviso_carpeta_programa(carpeta)}"
            for nombre, carpeta in carpetas.items()]


def manual_args(config: Config, pairs,
                approve: Callable[[list[str], Mapping[str, str]], bool]) -> list[str]:
    """Devuelve los argumentos de `sync.py` para una pasada manual de esas parejas.

    Las que piden un `--resync` se le preguntan a quien ha elegido (`approve`),
    UNA vez para todas y con las carpetas del programa que alguna subió
    (`carpetas_del_programa()`): si dice que sí va `--yes` y, si no, `sync.py`
    las salta. Lo comparten la ventana, que lanza la pasada sin cerrarse, y
    `runsync` para el menú de consola.
    """
    args = list(pairs)
    pending = [n for n in pair_status_notes(config) if n in args]
    if pending and approve(pending, carpetas_del_programa(config, pending)):
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
    from common import bisync, results

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


perf_quien = "main"
"""Quién mide el `apply-*` de este proceso: `main`, `wizard` o `agente`.

Lo fijan el asistente y la pregunta del agente antes de su primer `apply()`.
"""

_INICIOS: dict[str, float] = {}
"""Cuándo empezó cada momento medido, por nombre (`perf_empezar()`)."""

_PERF_COLA: list[tuple[bool, str]] = []
"""Las líneas que esperan a escribirse, como `(host, línea)`."""

_PERF_CUENTA: dict[str, int] = {}
"""Cuántas veces ha marcado este proceso cada momento (el `vez=`)."""

_PERF_LOCK = threading.Lock()
"""Protege la cola y el contador: lo tocan el hilo de Tk y el volcado."""

_PERF_VOLCADO = threading.Lock()
"""Un solo volcado a la vez, y las rutas se resuelven dentro de él."""

_PERF_HILO: threading.Thread | None = None
"""El hilo que vuelca la cola cada segundo; nace con la primera marca."""


def perf_activo() -> bool:
    """Dice si se apuntan los tiempos de las ventanas (`PRDRIVE_PERF`).

    Se lee en cada llamada, como `theme.elegir_tema()`. Vacía, `0` o sin definir
    es apagada: entonces cada `perf_*` sale enseguida, sin fichero ni hilo.
    """
    return os.environ.get("PRDRIVE_PERF", "") not in ("", "0")


def perf_empezar(momento: str) -> None:
    """Anota ahora como inicio de `momento`, para que `perf_al_pintar()` lo cierre.

    Args:
        momento: El nombre del momento, como sale en `perf.log`.
    """
    if perf_activo():
        _INICIOS[momento] = time.perf_counter()


def perf_al_pintar(widget, momento: str, t0: float | None = None, *,
                   host: bool = False, **detalle) -> None:
    """Cierra un momento cuando la ventana acaba de pintarse y anota cuánto ha tardado.

    La callback va en un temporizador (`after(0)`) de la raíz de Tk, la que sobrevive
    a los diálogos. No es una callback de inactividad: esa también corre dentro de
    `update_idletasks()`, mientras otro código todavía coloca una ventana que no se
    ha enseñado, y el `update()` del cierre procesaría ahí eventos y temporizadores
    a medio colocar. Los temporizadores solo corren en el bucle de eventos
    (`mainloop`, `wait_window`) o en un `update()` completo. Vence al instante
    (`after(0)`, no `after(1)`): un plazo de 1 ms espera al tic del reloj, de unos
    15 ms en Windows, y un temporizador que aún no ha vencido se pierde si se
    cancelan las esperas pendientes de la raíz.

    Antes de medir hace `update()`: así el final cae donde acaba la medida del chequeo
    de tiempos, después de los redibujados que provoca el cambio. Sin ese `update()`
    un cambio que mueve 400 widgets se medía en 1 ms, y en realidad tarda 47.

    Args:
        widget: Cualquier widget de la ventana; de él se saca la raíz.
        momento: El nombre del momento. Si no se da `t0`, se usa el de `perf_empezar()`.
        t0: El instante de inicio (`time.perf_counter()`); `None` para usar el de `perf_empezar()`.
        host: Si la marca va al diario del equipo y no al del dispositivo.
        **detalle: Datos extra de la línea: números o palabras fijas, nunca nombres ni rutas.

    No hace nada si la medida está apagada o si no hay inicio que cerrar. Un fallo
    de Tk no llega a quien pinta.
    """
    if not perf_activo():
        return
    if t0 is None:
        t0 = _INICIOS.pop(momento, None)
    if t0 is None:
        return
    try:
        raiz = widget.nametowidget(".")

        def al_pintar() -> None:
            """Drena lo que el cambio dejó pendiente y anota la duración."""
            try:
                raiz.update()
                perf_marca(momento, (time.perf_counter() - t0) * 1000, host=host, **detalle)
            except Exception:                        # noqa: BLE001 — la medida no tumba la ventana
                pass

        raiz.after(0, al_pintar)                 # vence ya: sin esperar un tic del reloj
    except Exception:                                # noqa: BLE001 — la ventana ya no existe
        pass


def perf_marca(momento: str, ms: float | None, *, host: bool = False, **detalle) -> None:
    """Anota una duración en el diario de tiempos, sin escribirla todavía.

    Cada línea es `<fecha> <momento> <ms> ms vez=<N> <dato=valor …>`, donde `vez`
    cuenta las veces que este proceso ha marcado ese momento, desde 1. La línea
    queda en memoria: la escribe `perf_volcar()`, que el hilo llama cada segundo,
    así que nunca toca el disco en el hilo de Tk.

    Args:
        momento: El nombre del momento (`start-main`, `open-parejas`…).
        ms: La duración en milisegundos; `None` no anota nada.
        host: Si va a `equipo/perf.log` (el agente o el asistente) y no a `logs/perf.log`.
        **detalle: Datos de la línea: números o palabras fijas.
    """
    if ms is None or not perf_activo():
        return
    with _PERF_LOCK:
        vez = _PERF_CUENTA[momento] = _PERF_CUENTA.get(momento, 0) + 1
        datos = "".join(f" {k}={v}" for k, v in detalle.items())
        _PERF_COLA.append((host, f"{store.stamp()} {momento} {ms:.1f} ms vez={vez}{datos}\n"))
    _arrancar_hilo_perf()


def _arrancar_hilo_perf() -> None:
    """Arranca, una sola vez por proceso, el hilo que vuelca la cola cada segundo.

    También registra el volcado final al salir del proceso.
    """
    global _PERF_HILO
    if _PERF_HILO is not None:
        return
    with _PERF_LOCK:
        if _PERF_HILO is not None:
            return

        def bucle() -> None:
            """Vuelca cada segundo; un fallo no para el hilo."""
            while True:
                time.sleep(1.0)
                try:
                    perf_volcar()
                except Exception:                    # noqa: BLE001
                    pass

        import atexit
        _PERF_HILO = threading.Thread(target=bucle, daemon=True, name="perf-marcas")
        _PERF_HILO.start()
        atexit.register(_volcar_al_salir)


def _volcar_al_salir() -> None:
    """Vuelca lo pendiente al cerrar el proceso, sin lanzar nada.

    `atexit` imprimiría cualquier excepción como traceback; el diario no es vital.
    """
    try:
        perf_volcar()
    except Exception:                                # noqa: BLE001
        pass


def perf_volcar() -> None:
    """Escribe ya las marcas pendientes en sus diarios.

    Lo llaman el hilo cada segundo, el cierre del proceso y los tests. Cada lote
    recorta antes el diario si ha pasado de `store.DIARIO_TOPE`. Un fallo de
    escritura (solo lectura, disco lleno o extraído) se calla: el diario no es vital,
    y un lote que no puede resolver su ruta no hace perder los demás.
    """
    with _PERF_VOLCADO:
        with _PERF_LOCK:
            pendientes = _PERF_COLA[:]
            _PERF_COLA.clear()
        lotes: dict[bool, list[str]] = {}
        for host, linea in pendientes:
            lotes.setdefault(host, []).append(linea)
        for host, lineas in lotes.items():
            try:
                _escribir_perf(_ruta_perf(host), lineas)
            except Exception:                        # noqa: BLE001 — un lote fallido no para los demás
                pass


def _ruta_perf(host: bool) -> Path:
    """Devuelve el diario de tiempos del dispositivo o del equipo, tal como está ahora."""
    from common import model

    if host:
        from common import equipo
        return equipo.DIR / "perf.log"
    return model.LOG_DIR / "perf.log"


def _escribir_perf(ruta: Path, lineas: list[str]) -> None:
    """Añade un lote a un diario de tiempos, creando su carpeta si hace falta."""
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        store.recortar_diario(ruta)
        with open(ruta, "a", encoding="utf-8", errors="replace") as f:
            f.writelines(lineas)
    except (OSError, ValueError):
        pass


def perf_desde_inicio() -> float | None:
    """Devuelve cuántos milisegundos lleva vivo este proceso, o `None` si no se sabe.

    Es el inicio de los momentos `start-*`, medido desde que el sistema creó el
    proceso y no desde que empieza `ui`: el mismo punto de partida que el
    cronómetro del chequeo de tiempos, que arranca antes de lanzar el proceso.

    Windows: `GetProcessTimes`, la hora de creación contra la de ahora. Linux: el
    campo 22 de `/proc/self/stat` (el inicio, en ticks) contra `/proc/uptime`,
    los dos desde el arranque del sistema, así que no hace falta pasar a la hora
    de pared. `btime` de `/proc/stat` solo tiene segundos y se desfasaría hasta
    uno. Otros sistemas: `None`.
    """
    try:
        if os.name == "nt":
            return _edad_windows()
        if sys.platform.startswith("linux"):
            return _edad_linux()
    except (OSError, ValueError, IndexError):
        pass
    return None


def _edad_windows() -> float:
    """Milisegundos desde la creación del proceso, con `GetProcessTimes` de kernel32.

    Los tipos siguen a `common/model.py`: el HANDLE va como `c_void_p`, así que el
    pseudo-handle `-1` de `GetCurrentProcess` no pasa por un `c_int`.
    """
    import ctypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.argtypes = []
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(ctypes.c_uint64)] * 4
    k32.GetProcessTimes.restype = ctypes.c_int
    creacion, salida, nucleo, usuario = (ctypes.c_uint64() for _ in range(4))
    if not k32.GetProcessTimes(k32.GetCurrentProcess(), ctypes.byref(creacion),
                               ctypes.byref(salida), ctypes.byref(nucleo),
                               ctypes.byref(usuario)):
        raise OSError("GetProcessTimes")
    # FILETIME: unidades de 100 ns desde 1601-01-01; hasta la época Unix hay 11644473600 s.
    inicio = creacion.value / 1e7 - 11644473600
    return (time.time() - inicio) * 1000


def _edad_linux() -> float:
    """Milisegundos desde la creación del proceso, con `/proc/self/stat` y `/proc/uptime`."""
    with open("/proc/self/stat", encoding="ascii") as f:
        datos = f.read()
    # El nombre del comando (campo 2) va entre paréntesis y puede llevar espacios:
    # se cuenta desde el último paréntesis, y el primer campo que queda es el 3.
    campos = datos[datos.rindex(")") + 2:].split()
    inicio_ticks = int(campos[22 - 3])               # campo 22: starttime
    with open("/proc/uptime", encoding="ascii") as f:
        ahora = float(f.read().split()[0])
    return (ahora - inicio_ticks / os.sysconf("SC_CLK_TCK")) * 1000
