#!/usr/bin/env python3
"""Ejecuta todos los tests.

Se usa como `python tests/run_all.py`. Cada test es un script independiente que
devuelve 0 o 1; se lanzan en procesos separados a propósito, porque varios
sustituyen funciones del proyecto (el bucle de Tk, print, las rutas del modelo)
y no deben contaminarse entre sí. Ninguno toca el dispositivo: todos trabajan
sobre directorios temporales.

Con `-j N` corren varios a la vez. Cada test tiene su propio TMPDIR y su propio
HOME, que se borran al acabar. Con `--display xvfb` cada trabajador tiene su
propio servidor X. Los tests de `GUI` (los que abren ventanas) no pasan de
`--gui-jobs` a la vez, y los de `SERIE` (los que miran algo compartido del
equipo) corren al final, de uno en uno.

Ctrl-C (o SIGTERM) para la pasada: no arranca más tests, mata los que corren con
todo su árbol de procesos, espera a que sus trabajadores acaben y sale con 130.

Un test que no da resultado (la suite misma falla al correrlo, o su hilo muere)
cuenta como fallo, nunca como pasado: cada fichero tiene exactamente un resultado.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
"""Carpeta de los tests."""

IS_WIN = os.name == "nt"
"""Si corre en Windows: el árbol de un test se mata con `taskkill`."""

GUI = {
    "test_autoprueba.py", "test_captura_pantalla.py", "test_controles.py",
    "test_daemon_aviso.py", "test_iconos.py", "test_iconos_svg.py",
    "test_imports_perezosos.py", "test_install_catalogo.py", "test_install_wizard.py",
    "test_matar_arbol.py", "test_start.py", "test_superficie.py", "test_tema.py",
    "test_theme_combobox.py", "test_tk_ajustes_vista.py", "test_tk_apartados_lectura.py",
    "test_tk_asistente.py", "test_tk_asistente_reencaje.py", "test_tk_densidad.py",
    "test_tk_ensenar.py", "test_tk_equipo_lecturas.py", "test_tk_espera.py",
    "test_tk_flota_vista.py", "test_tk_letra.py", "test_tk_llavero.py", "test_tk_medidas.py",
    "test_tk_panel.py", "test_tk_parejas_vista.py", "test_tk_pasada.py", "test_tk_principal.py",
    "test_tk_principal_ancho.py", "test_tk_principal_vista.py", "test_tk_reparacion.py",
    "test_tk_salida.py", "test_tk_screens.py", "test_tk_segundo_plano.py", "test_tk_servicio.py",
    "test_tk_tabla.py", "test_tk_visor.py", "test_tk_vista.py", "test_ui.py",
    "test_unidad_nueva.py", "test_volumen.py",
}
"""Los tests que abren una ventana de Tk. Dos a la vez en un mismo escritorio se pisan
(el foco, los píxeles), así que `--gui-jobs` los limita.

`tests/test_run_all.py` comprueba que todo fichero que importa `tkinter` o `ui.tk*`
a nivel de módulo, o que crea un `Tk()`, está aquí o en `GUI_NO`.
"""

GUI_NO = {
    "test_build_installer.py": "importa tkinter a nivel de módulo solo para leer la versión de Tcl",
    "test_install_components.py": "importa `ui.tk_relevo` y sustituye su ventanita: ningún test la abre",
    "test_instancia_unica.py": "importa `ui.tk_update`, pero no abre ventanas",
    "test_keepassxc.py": "importa `ui.tk` para sus constantes, pero no abre ventanas",
    "test_raiz_equipo.py": "importa `ui.tk_fleet` para la ficha de texto, pero no abre ventanas",
    "test_tk_xft.py": "importa tkinter solo para comprobar que ya está cargado; no abre ventanas",
}
"""Tests que importan tkinter o `ui.tk*` a nivel de módulo sin abrir ventanas, con la razón."""

SERIE = {
    "test_avisos_carpeta.py": "vigila los montajes del equipo: un montaje ajeno le hace fallar",
}
"""Tests que no corren a la vez que ningún otro: van después del grupo, de uno en uno.

`serie_para()` añade los que dependen de un escritorio o un proceso compartidos.
"""

PESO = {
    "test_tk_servicio.py": 32.0,
    "test_keepassxc.py": 23.0,
    "test_install_wizard.py": 18.0,
    "test_tk_principal_ancho.py": 17.7,
    "test_tk_medidas.py": 14.9,
    "test_tk_principal_vista.py": 12.2,
    "test_run_all.py": 33.0,
    "test_llavero_combinar.py": 9.2,
    "test_tk_parejas_vista.py": 8.8,
    "test_keepassxc_linux.py": 8.7,
    "test_tk_apartados_lectura.py": 7.8,
    "test_superficie.py": 7.4,
    "test_agente_endurecido.py": 6.9,
    "test_tk_segundo_plano.py": 6.8,
    "test_tk_tabla.py": 13.0,
    "test_tk_flota_vista.py": 5.4,
    "test_iconos_svg.py": 4.6,
}
"""Segundos medidos de los tests más lentos, para empezar por los largos y que la cola
no acabe con uno solo. En CI, el mayor de Linux y Windows; `test_run_all.py` y
`test_tk_tabla.py`, medidos a mano (con `-j 4` y la carga de la suite). Los demás pesan 1.
"""


def serie_para(compartido: bool) -> dict[str, str]:
    """Qué tests corren al final, de uno en uno, según el escritorio.

    Args:
        compartido: Si los trabajadores comparten escritorio o pantalla: Windows
            (una sola sesión gráfica) o `--display inherit`. Con un servidor X
            propio por trabajador, los de píxeles y foco no se estorban.

    Returns:
        `SERIE`, más `test_vestibulo.py` en Windows (busca `VeraCrypt.exe` por
        nombre en todo el sistema) y, con escritorio compartido, los que miran
        píxeles o el foco de la ventana.
    """
    serie = dict(SERIE)
    if IS_WIN:
        serie["test_vestibulo.py"] = "busca VeraCrypt.exe por nombre en todo el sistema"
    if compartido:
        serie["test_superficie.py"] = "lee píxeles de la pantalla"
        serie["test_tk_tabla.py"] = "necesita el foco de la ventana"
    return serie


@dataclass
class Resultado:
    """Lo que dio un test al acabar.

    Args:
        nombre: El fichero, por ejemplo `test_x.py`.
        rc: El código de salida. Es 124 si se mató por `--timeout`.
        segundos: El tiempo de pared que tardó.
        salida: Lo que escribió (stdout y stderr juntos), en bytes.
    """

    nombre: str
    rc: int
    segundos: float
    salida: bytes


class Reparto:
    """La cola de tests pendientes, con el límite de ventanas a la vez.

    Args:
        pendientes: Los nombres de fichero, en el orden en que deben salir.
        gui_jobs: Cuántos tests de `GUI` pueden correr a la vez (al menos 1).
    """

    def __init__(self, pendientes: list[str], gui_jobs: int) -> None:
        self._cola = list(pendientes)
        self._gui_jobs = gui_jobs
        self._gui_activos = 0
        self._parado = False
        self._cond = threading.Condition()

    def tomar(self) -> str | None:
        """Espera y devuelve el siguiente test que puede empezar.

        Un test de `GUI` no empieza mientras haya `gui_jobs` corriendo; los
        demás no esperan por él. Tras `parar()` ya no se da ninguno.

        Returns:
            El nombre del fichero, o `None` cuando no queda ninguno o se paró.
        """
        with self._cond:
            while self._cola and not self._parado:
                for i, nombre in enumerate(self._cola):
                    if nombre in GUI and self._gui_activos >= self._gui_jobs:
                        continue
                    del self._cola[i]
                    if nombre in GUI:
                        self._gui_activos += 1
                    return nombre
                self._cond.wait()
            return None

    def soltar(self, nombre: str) -> None:
        """Anota que `nombre` acabó y despierta a los que esperan."""
        with self._cond:
            if nombre in GUI:
                self._gui_activos -= 1
            self._cond.notify_all()

    def parar(self) -> None:
        """Deja de dar tests: los que esperan en `tomar()` devuelven `None`."""
        with self._cond:
            self._parado = True
            self._cond.notify_all()


def arrancar_xvfb() -> tuple[subprocess.Popen, str]:
    """Arranca un servidor X propio para un trabajador.

    Con `-displayfd`, Xvfb elige un número de pantalla libre y lo escribe en
    el descriptor, así que dos trabajadores no chocan.

    Returns:
        El proceso de Xvfb y su DISPLAY (por ejemplo `:99`).

    Raises:
        RuntimeError: Si Xvfb termina sin dar su número de pantalla.
    """
    lectura, escritura = os.pipe()
    try:
        proc = subprocess.Popen(
            ["Xvfb", "-displayfd", str(escritura), "-screen", "0", "1920x1080x24", "-nolisten", "tcp"],
            pass_fds=(escritura,), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        os.close(escritura)
    datos = b""
    try:
        while not datos.endswith(b"\n"):
            trozo = os.read(lectura, 16)
            if not trozo:
                break
            datos += trozo
    finally:
        os.close(lectura)
    if not datos.strip():
        proc.kill()
        proc.wait()
        raise RuntimeError("Xvfb terminó sin dar su número de pantalla")
    return proc, ":" + datos.decode().strip()


def matar_arbol(proc: subprocess.Popen) -> None:
    """Mata un test y los procesos que haya lanzado, sin tocar los ajenos.

    En POSIX el test corre en su propia sesión (`start_new_session`), así que
    matar su grupo alcanza a sus hijos. En Windows se usa `taskkill /T`.
    """
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        proc.kill()
    except OSError:
        pass


_vivos: set[subprocess.Popen] = set()
"""Los tests que corren ahora, para matarlos si se interrumpe la pasada."""

_vivos_cerrojo = threading.Lock()
_interrumpida = threading.Event()
"""Se marca al interrumpir la pasada: lo que arranque después muere enseguida."""


def _registrar(proc: subprocess.Popen) -> None:
    """Anota un test en curso; si la pasada ya se interrumpió, lo mata sin esperar."""
    with _vivos_cerrojo:
        _vivos.add(proc)
        interrumpida = _interrumpida.is_set()
    if interrumpida:
        matar_arbol(proc)


def _dar_de_baja(proc: subprocess.Popen) -> None:
    """Quita de la lista de tests en curso a uno que ya acabó."""
    with _vivos_cerrojo:
        _vivos.discard(proc)


def parar_todo() -> None:
    """Interrumpe la pasada: mata los tests en curso con su árbol de procesos.

    Lo que arranque después de esta llamada también muere al momento
    (`_registrar()`). Los hilos que los corren aún deben acabar; quien llama
    espera a que lo hagan antes de borrar los temporales.
    """
    with _vivos_cerrojo:
        _interrumpida.set()
        vivos = list(_vivos)
    for proc in vivos:
        matar_arbol(proc)


def _matar_y_esperar(proc: subprocess.Popen) -> None:
    """Mata el árbol de un test y espera a su proceso directo, sin pasar de 30 s."""
    matar_arbol(proc)
    try:
        proc.wait(30)
    except subprocess.TimeoutExpired:
        pass


def correr(script: Path, entorno: dict[str, str], timeout: float) -> Resultado:
    """Corre un test en su propio proceso y devuelve lo que dio.

    La salida va a un fichero temporal y no a una tubería: se espera al proceso
    del test, no a que se cierre su salida. Un nieto que la hereda y sigue
    vivo no retrasa ni cambia el resultado.

    Args:
        script: El `test_*.py`. Se ejecuta con `tests/` como carpeta de trabajo.
        entorno: Las variables del proceso (DISPLAY, TMPDIR, HOME…).
        timeout: Segundos como máximo. Pasados, se mata el árbol del test.

    Returns:
        El resultado. Si se agotó el tiempo, `rc` es 124 y la salida acaba en
        una línea `TIMEOUT`. Si la pasada se interrumpe mientras espera, el
        árbol del test se mata antes de salir de aquí.
    """
    if IS_WIN:
        kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        kw = {"start_new_session": True}
    inicio = time.monotonic()
    with tempfile.TemporaryFile() as fichero:
        proc = subprocess.Popen(
            [sys.executable, str(script)], cwd=str(TESTS_DIR), env=entorno,
            stdin=subprocess.DEVNULL, stdout=fichero, stderr=subprocess.STDOUT, **kw)
        _registrar(proc)
        try:
            proc.wait(timeout=timeout)
            rc = proc.returncode
            fin = b""
        except subprocess.TimeoutExpired:
            _matar_y_esperar(proc)
            rc = 124
            fin = f"\nTIMEOUT: más de {timeout:g} s; se mata el árbol del test\n".encode()
        except BaseException:
            # Ctrl-C mientras espera: el test no sobrevive a la pasada.
            _matar_y_esperar(proc)
            raise
        finally:
            _dar_de_baja(proc)
        fichero.seek(0)
        salida = fichero.read() + fin
    return Resultado(script.name, rc, time.monotonic() - inicio, salida)


def ejecutar_aislado(script: Path, indice: int, base: Path, display: str | None,
                     timeout: float) -> Resultado:
    """Corre un test con su propio TMPDIR y su propio HOME, que se borran al acabar.

    Args:
        script: El test.
        indice: Su posición en la lista de tests; nombra su carpeta dentro de
            `base`, corta a propósito (los sockets de AF_UNIX tienen un límite).
        base: La carpeta común de los temporales, ya creada.
        display: El DISPLAY de su trabajador, o `None` para heredar el del proceso.
        timeout: Ver `correr()`.

    Returns:
        El resultado de `correr()`. Si no se pudo lanzar, `rc` es 1 y la salida lo dice.
    """
    propia = base / str(indice)
    temporal = propia / "t"
    casa = propia / "h"
    try:
        temporal.mkdir(parents=True)
        casa.mkdir()
        entorno = dict(os.environ)
        entorno.update(TMPDIR=str(temporal), TEMP=str(temporal), TMP=str(temporal),
                       HOME=str(casa), USERPROFILE=str(casa))
        if display is not None:
            entorno["DISPLAY"] = display
        return correr(script, entorno, timeout)
    except OSError as e:
        return Resultado(script.name, 1, 0.0, f"No se pudo lanzar: {e}\n".encode())
    finally:
        shutil.rmtree(propia, ignore_errors=True)


def ejecutar_protegido(script: Path, indice: int, base: Path, display: str | None,
                       timeout: float) -> Resultado:
    """Como `ejecutar_aislado()`, pero un fallo de la propia suite es un fallo del test.

    Una excepción al correr el test (no un fallo del test) da FALLA con el rastro
    en su salida. Así el hilo sigue con la cola y el test no se pierde.

    Args:
        script: El test.
        indice: Ver `ejecutar_aislado()`.
        base: Ver `ejecutar_aislado()`.
        display: Ver `ejecutar_aislado()`.
        timeout: Ver `correr()`.

    Returns:
        El resultado del test, o uno con `rc` 1 y el rastro del error de la suite.
    """
    try:
        return ejecutar_aislado(script, indice, base, display, timeout)
    except Exception:
        rastro = traceback.format_exc()
        return Resultado(script.name, 1, 0.0,
                         f"La suite no pudo correr este test; cuenta como fallo:\n{rastro}".encode())


def _estado(r: Resultado) -> str:
    """`OK`, o `FALLA rc=N` con el código de salida."""
    return "OK" if r.rc == 0 else f"FALLA rc={r.rc}"


def _escribir(texto: str) -> None:
    """Escribe una línea en la salida de la suite (quien llama tiene el cerrojo)."""
    sys.stdout.write(texto + "\n")
    sys.stdout.flush()


def _volcar(salida: bytes) -> None:
    """Escribe lo que dio un test tal cual, en bytes, terminado en salto de línea."""
    sys.stdout.flush()
    sys.stdout.buffer.write(salida if salida.endswith(b"\n") else salida + b"\n")
    sys.stdout.buffer.flush()


def _mostrar(r: Resultado, gha: bool) -> None:
    """Imprime un test entero, con su cabecera.

    Args:
        r: El resultado del test.
        gha: Si corre en GitHub Actions: la salida va en un grupo plegable.
    """
    cabecera = f"##### {r.nombre}: {_estado(r)} ({r.segundos:.1f} s)"
    if gha:
        _escribir(f"::group::{cabecera}")
        _volcar(r.salida)
        _escribir("::endgroup::")
    else:
        _escribir(cabecera)
        _volcar(r.salida)


def _entero_positivo(valor: str) -> int:
    """Un número entero de al menos 1, o error de argumentos."""
    try:
        n = int(valor)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError(f"se espera un número de al menos 1: {valor!r}")
    return n


def _trabajadores(valor: str) -> int:
    """El valor de `-j`: un número de trabajadores, o `auto` (los núcleos del equipo)."""
    if valor == "auto":
        return os.cpu_count() or 1
    return _entero_positivo(valor)


def _segundos(valor: str) -> float:
    """Un número de segundos mayor que 0, o error de argumentos."""
    try:
        s = float(valor)
    except ValueError:
        s = 0.0
    if s <= 0:
        raise argparse.ArgumentTypeError(f"se espera un número de segundos mayor que 0: {valor!r}")
    return s


def _analizar(argv: list[str] | None) -> argparse.Namespace:
    """Lee la línea de órdenes de `run_all.py`."""
    ap = argparse.ArgumentParser(description="Ejecuta los tests: cada `test_*.py` en su proceso.")
    ap.add_argument("-j", "--jobs", type=_trabajadores, default=1, metavar="N|auto",
                    help="cuántos tests a la vez; auto = los núcleos. Por defecto 1, en orden alfabético")
    ap.add_argument("--display", choices=("inherit", "xvfb"), default="inherit",
                    help="inherit: la pantalla de este proceso; xvfb: un servidor X propio por "
                         "trabajador (sin Xvfb, la pantalla que haya)")
    ap.add_argument("--gui-jobs", type=_entero_positivo, default=None, metavar="K",
                    help="cuántos tests de la lista GUI a la vez. Por defecto 1 con pantalla "
                         "compartida, y sin límite con un servidor X propio")
    ap.add_argument("--timeout", type=_segundos, default=600.0, metavar="S",
                    help="segundos máximos por test; pasados, se mata su árbol de procesos")
    ap.add_argument("nombres", nargs="*", help="solo estos tests (por defecto, todos)")
    return ap.parse_args(argv)


def _esperar(hilos: list[threading.Thread]) -> None:
    """Espera a que acaben los hilos, en trozos de 0,2 s, para que Ctrl-C llegue.

    `join()` sin plazo no deja llegar la interrupción en Windows: el hilo principal
    queda parado hasta que acaba el hilo. Un hilo que no se arrancó no espera.

    Args:
        hilos: Los hilos a esperar.
    """
    for hilo in hilos:
        while hilo.is_alive():
            hilo.join(0.2)


def arrancar_pantallas(n: int) -> list[tuple[subprocess.Popen, str]]:
    """Arranca `n` servidores X, uno por trabajador.

    Si uno falla, o llega una interrupción, los que ya arrancaron se paran antes
    de propagar el error.

    Args:
        n: Cuántos servidores hacen falta.

    Returns:
        Los procesos de Xvfb y su DISPLAY, en el mismo orden.

    Raises:
        RuntimeError: Si alguno no arranca.
    """
    pantallas: list[tuple[subprocess.Popen, str]] = []
    try:
        for _ in range(n):
            pantallas.append(arrancar_xvfb())
    except BaseException:
        parar_pantallas(pantallas)
        raise
    return pantallas


def parar_pantallas(pantallas: list[tuple[subprocess.Popen, str]]) -> None:
    """Para los servidores X de `arrancar_pantallas()`."""
    for proc, _ in pantallas:
        proc.terminate()
    for proc, _ in pantallas:
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _xvfb_murio(proc: subprocess.Popen | None) -> bool:
    """Si el servidor X de un trabajador ya terminó.

    Args:
        proc: El Xvfb del trabajador, o `None` si no tiene servidor propio.

    Returns:
        `True` solo si había servidor y ya no corre.
    """
    return proc is not None and proc.poll() is not None


def _fallo_xvfb(r: Resultado) -> Resultado:
    """El resultado de un test cuyo servidor X murió mientras corría, como fallo.

    Un test de Tk sin pantalla imprime «(saltado)» y sale con 0: sin esta
    corrección pasaría como bueno.

    Args:
        r: Lo que dio el test.

    Returns:
        Un fallo con el mismo nombre, tiempo y salida, y una línea que lo explica.
    """
    return Resultado(r.nombre, 1, r.segundos, r.salida + "\nXvfb murió durante el test\n".encode())


TMP_CORTO = 30
"""Largo máximo, en caracteres, de la carpeta de temporales de la suite en POSIX.

Los sockets de AF_UNIX (`test_dbus`) no admiten más de unos 108 bytes de ruta.
"""


def carpeta_base() -> Path:
    """Crea la carpeta común de los temporales de una pasada.

    En POSIX, si el temporal del sistema (TMPDIR) pasa de `TMP_CORTO` caracteres
    se usa `/tmp`, para que la ruta de cada test quepa en un socket AF_UNIX.

    Returns:
        La carpeta, recién creada. Quien llama la borra al acabar.
    """
    raiz = tempfile.gettempdir()
    if not IS_WIN and len(raiz) > TMP_CORTO:
        raiz = "/tmp"
    return Path(tempfile.mkdtemp(prefix="prt-", dir=raiz))


def _al_interrumpir(_signum: int, _marco: object) -> None:
    """Convierte SIGTERM en una interrupción como Ctrl-C, para que `main()` la recoja."""
    raise KeyboardInterrupt


def _instalar_senales() -> dict[int, object]:
    """Pone Ctrl-C y SIGTERM en manos de `main()`.

    Returns:
        Los manejadores anteriores, para `_restaurar_senales()`. Vacío fuera del
        hilo principal, que es el único donde se pueden instalar.
    """
    if threading.current_thread() is not threading.main_thread():
        return {}
    anteriores: dict[int, object] = {}
    for senal in (signal.SIGINT, signal.SIGTERM):
        anteriores[senal] = signal.signal(senal, _al_interrumpir)
    return anteriores


def _restaurar_senales(anteriores: dict[int, object]) -> None:
    """Devuelve a Ctrl-C y SIGTERM los manejadores que tenían antes de `main()`."""
    for senal, manejador in anteriores.items():
        signal.signal(senal, manejador if manejador is not None else signal.SIG_DFL)


def main(argv: list[str] | None = None) -> int:
    """Lanza los tests y devuelve 1 si alguno falla.

    Args:
        argv: Los argumentos de la línea de órdenes; `None` toma los de verdad.

    Returns:
        0 si todos pasan; 1 si alguno falla, no hay tests o no se pudo arrancar
        Xvfb; 2 si se pide un nombre que no es un test; 130 si se interrumpe la
        pasada (Ctrl-C o SIGTERM), sin resultado.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = _analizar(argv)
    todos = sorted(TESTS_DIR.glob("test_*.py"))
    scripts = todos
    if a.nombres:
        pedidos = [Path(n).name for n in a.nombres]
        existentes = {p.name for p in todos}
        desconocidos = [n for n in pedidos if n not in existentes]
        if desconocidos:
            print(f"No hay ningún test que se llame: {', '.join(desconocidos)}")
            return 2
        scripts = [p for p in todos if p.name in pedidos]
    if not scripts:
        print("No hay tests que ejecutar.")
        return 1

    xvfb = a.display == "xvfb" and not IS_WIN and shutil.which("Xvfb") is not None
    if a.display == "xvfb" and not xvfb:
        print("(sin Xvfb en este equipo: los tests usan la pantalla que haya)")
    compartido = not xvfb
    gui_jobs = a.gui_jobs if a.gui_jobs is not None else (1 if compartido else a.jobs)

    indices = {p.name: i for i, p in enumerate(scripts)}
    if a.jobs == 1:
        pool = [p.name for p in scripts]
        en_serie: list[str] = []
    else:
        serie = serie_para(compartido)
        pool = sorted((p.name for p in scripts if p.name not in serie),
                      key=lambda n: (-PESO.get(n, 1.0), n))
        en_serie = [p.name for p in scripts if p.name in serie]

    gha = os.environ.get("GITHUB_ACTIONS") == "true"
    trabajadores = max(1, min(a.jobs, len(pool)))
    resultados: list[Resultado] = []
    cerrojo = threading.Lock()
    base = carpeta_base()
    pantallas: list[tuple[subprocess.Popen, str]] = []
    reparto = Reparto(pool, gui_jobs)
    hilos: list[threading.Thread] = []
    _interrumpida.clear()
    inicio = time.monotonic()
    anteriores = _instalar_senales()
    try:
        try:
            if xvfb:
                pantallas = arrancar_pantallas(trabajadores)
            # Cada trabajador con su servidor X (None sin Xvfb) y su DISPLAY.
            pares: list[tuple[subprocess.Popen | None, str | None]] = (
                list(pantallas) or [(None, None)] * trabajadores)

            def anotar(r: Resultado) -> None:
                """Guarda un resultado y lo imprime entero, con el cerrojo de la salida."""
                with cerrojo:
                    resultados.append(r)
                    _mostrar(r, gha)

            def trabajar(proc: subprocess.Popen | None, display: str | None) -> None:
                """Toma tests del reparto hasta que no quede ninguno o se interrumpa la pasada.

                Un fallo de la suite al correr un test lo deja como FALLA de ese test
                (`ejecutar_protegido()`), y el hilo sigue con la cola. Si el Xvfb del
                trabajador murió durante un test, ese test falla y el trabajador deja la
                cola: el resto de tests quedan sin resultado.
                """
                while True:
                    nombre = reparto.tomar()
                    if nombre is None:
                        return
                    try:
                        r = ejecutar_protegido(TESTS_DIR / nombre, indices[nombre], base, display, a.timeout)
                    finally:
                        reparto.soltar(nombre)
                    if _interrumpida.is_set():
                        return  # lo que quedó a medias no es un resultado
                    if _xvfb_murio(proc):
                        anotar(_fallo_xvfb(r))
                        return
                    anotar(r)

            def correr_serie() -> None:
                """Corre los de SERIE, uno a uno, con la cola ya parada."""
                proc, display = pares[0]
                for nombre in en_serie:
                    r = ejecutar_protegido(TESTS_DIR / nombre, indices[nombre], base, display, a.timeout)
                    if _interrumpida.is_set():
                        return
                    if _xvfb_murio(proc):
                        anotar(_fallo_xvfb(r))
                        return
                    anotar(r)

            hilos = [threading.Thread(target=trabajar, args=par) for par in pares]
            for hilo in hilos:
                hilo.start()
            _esperar(hilos)

            # SERIE va en su propio hilo: esperando un proceso con plazo, el principal no
            # recibiría Ctrl-C en Windows.
            if en_serie:
                hilo_serie = threading.Thread(target=correr_serie)
                hilos.append(hilo_serie)
                hilo_serie.start()
                _esperar([hilo_serie])
        except KeyboardInterrupt:
            # Ctrl-C o SIGTERM: no arranca nada más, los que corren mueren, y sus hilos
            # acaban antes de que se borren los temporales. Otra interrupción mientras se
            # mata no corta esto: se vuelve a parar y a matar, y se espera de nuevo.
            while True:
                try:
                    reparto.parar()
                    parar_todo()
                    _esperar(hilos)
                    break
                except KeyboardInterrupt:
                    pass
    except RuntimeError as e:
        _escribir(f"No se pudo arrancar Xvfb: {e}")
        return 1
    finally:
        _restaurar_senales(anteriores)
        parar_pantallas(pantallas)
        shutil.rmtree(base, ignore_errors=True)

    if _interrumpida.is_set():
        _escribir("INTERRUMPIDO: la pasada se paró antes de acabar; no hay resultado.")
        return 130

    total = time.monotonic() - inicio
    # Cada fichero tiene exactamente un resultado: uno que falte (su hilo murió sin darlo)
    # cuenta como fallo, nunca como pasado.
    con_resultado = {r.nombre for r in resultados}
    for script in scripts:
        if script.name not in con_resultado:
            r = Resultado(script.name, 1, 0.0,
                          "sin resultado: la pasada acabó sin que este test diera ninguno; "
                          "cuenta como fallo\n".encode())
            resultados.append(r)
            _mostrar(r, gha)
    fallidos = sorted((r for r in resultados if r.rc != 0), key=lambda r: r.nombre)
    if gha:
        for r in fallidos:
            _escribir(f"::error::{r.nombre}: {_estado(r)}")
            _volcar(r.salida)
    _escribir("Los más lentos:")
    for r in sorted(resultados, key=lambda r: -r.segundos)[:10]:
        _escribir(f"  {r.segundos:7.1f} s  {r.nombre}")
    modo = "Xvfb propio" if xvfb else "pantalla compartida"
    _escribir(f"Tiempo: {total:.1f} s (-j {a.jobs}, ventanas a la vez: {gui_jobs}, {modo})")
    _escribir("=" * 60)
    if fallidos:
        _escribir(f"FALLAN {len(fallidos)} de {len(scripts)}: {', '.join(r.nombre for r in fallidos)}")
        return 1
    _escribir(f"Los {len(scripts)} ficheros de test pasan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
