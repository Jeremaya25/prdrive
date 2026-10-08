#!/usr/bin/env python3
"""Cortar una pasada se lleva también a sus hijos.

`sync.py` lanza rclone, y matar solo a `sync.py` dejaría a rclone vivo con
ficheros del volumen abiertos: el caso de cerrar la ventana de salida a media
pasada y el del tope de la pasada del llavero. `store.matar_arbol()` corta el
proceso y todo lo que cuelga de él.

Se prueba con procesos de verdad (un hijo que lanza un nieto dormilón) y no con
fakes: lo que importa es que el nieto muera de verdad, en cada sistema.
"""

import os
import signal
import subprocess
import sys
import time

from _harness import Checks, tmpdir

from common import llavero, store

c = Checks("matar un proceso con todo su árbol")

MUERTO = 2 ** 22          # un pid que no existe (por encima del máximo habitual)
ESPERA = 5.0              # segundos que se le dan al sistema para retirar un proceso

HIJO = ("import pathlib, subprocess, sys\n"
        "nieto = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "pathlib.Path(sys.argv[1]).write_text(str(nieto.pid))\n"
        "nieto.wait()\n")
"""El hijo de la prueba: lanza un nieto que duerme 60 s y apunta su pid."""


def leer_pid(fichero) -> int | None:
    """Devuelve el pid que apunta el hijo, o `None` si aún no lo ha escrito entero."""
    try:
        return int(fichero.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def esperar_a(condicion, espera: float = ESPERA) -> bool:
    """Sondea `condicion()` hasta que se cumple o se acaba `espera`.

    Returns:
        Si se cumplió.
    """
    limite = time.monotonic() + espera
    while not condicion():
        if time.monotonic() >= limite:
            return False
        time.sleep(0.05)
    return True


def liberar(pid: int) -> None:
    """Mata un proceso a las malas, para que una prueba que falla no lo deje dormido."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        else:
            os.kill(pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass


# el nieto muere con su abuelo
#
# El hijo se lanza como lo hace `ui/tk.py`: jefe de su sesión (POSIX), que es lo
# que permite señalar a todo el grupo, o en su propio grupo de procesos (Windows).
fichero = tmpdir() / "nieto.pid"
if os.name == "nt":
    aparte = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
else:
    aparte = {"start_new_session": True}
hijo = subprocess.Popen([sys.executable, "-c", HIJO, str(fichero)],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, **aparte)
nieto = None
try:
    esperar_a(lambda: leer_pid(fichero) is not None, 15.0)
    nieto = leer_pid(fichero)
    c("el nieto arrancó y está vivo antes de cortar",
      nieto is not None and store.pid_alive(nieto), True)

    store.matar_arbol(hijo.pid)

    if nieto is not None:
        esperar_a(lambda: not store.pid_alive(nieto))
        c("el nieto también muere", store.pid_alive(nieto), False)
    try:
        hijo.wait(timeout=ESPERA)
    except subprocess.TimeoutExpired:
        pass
    c("y el hijo, al que se señalaba", hijo.poll() is not None, True)
finally:
    if hijo.poll() is None:
        liberar(hijo.pid)
        hijo.wait()
    if nieto is not None and store.pid_alive(nieto):
        liberar(nieto)


# no lanza nunca
#
# Cortar es lo último que se hace al cerrar una ventana o pasarse de tope: un
# proceso que ya no está, o un sistema sin `taskkill`, no puede romper eso.
def intentar(pid: int) -> Exception | None:
    """Corta `pid` y devuelve lo que se haya lanzado, si algo."""
    try:
        store.matar_arbol(pid)
    except Exception as e:                                   # noqa: BLE001
        return e
    return None


c("un pid que ya no existe no lanza", intentar(MUERTO), None)

if os.name == "nt":
    corriente = subprocess.run

    def sin_taskkill(*args, **kwargs):
        """Hace como si `taskkill` no estuviera en el equipo."""
        raise FileNotFoundError("taskkill")

    subprocess.run = sin_taskkill
    try:
        c("sin taskkill tampoco lanza", intentar(MUERTO), None)
    finally:
        subprocess.run = corriente
else:
    corriente = os.killpg

    def sin_permiso(*args, **kwargs):
        """Hace como si el sistema negara la señal (un grupo de otro usuario)."""
        raise PermissionError(1, "Operation not permitted")

    os.killpg = sin_permiso
    try:
        c("un grupo que no se deja señalar tampoco lanza", intentar(MUERTO), None)
    finally:
        os.killpg = corriente


# el llavero sigue teniendo su punto de sustitución
#
# `llavero.matar_arbol` es de módulo para que los tests de la pasada no maten
# nada, y por dentro corta con la de `store`.
vistos: list[int] = []
verdadera = store.matar_arbol
store.matar_arbol = vistos.append
try:
    llavero.matar_arbol(4321)
finally:
    store.matar_arbol = verdadera
c("llavero.matar_arbol corta con la de store", vistos, [4321])


# cerrar la ventana de salida a media pasada
#
# Es el caso que motiva todo esto: la pasada de `output_window` lanza un rclone, y
# cerrar la ventana con la X tiene que cortarlo también a él. Con la ventana de
# verdad, oculta y colgada de una raíz que tampoco se enseña.
try:
    import tkinter as tk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                       # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from ui import tk as uitk  # noqa: E402

fichero = tmpdir() / "nieto-ventana.pid"
deiconify = tk.Toplevel.deiconify
tk.Toplevel.deiconify = lambda self: None                    # nada se enseña en un test
nieto = None
try:
    antes = set(raiz.winfo_children())
    uitk.output_window("Prueba", [sys.executable, "-c", HIJO, str(fichero)],
                       parent=raiz, modal=False)
    ventana = next(w for w in raiz.winfo_children() if w not in antes)

    def esperar_viva(condicion, espera: float = ESPERA) -> bool:
        """Como `esperar_a`, pero dejando que la ventana siga viva mientras tanto."""
        return esperar_a(lambda: raiz.update() is None and condicion(), espera)

    esperar_viva(lambda: leer_pid(fichero) is not None, 15.0)
    nieto = leer_pid(fichero)
    c("con la ventana abierta, el nieto está vivo",
      nieto is not None and store.pid_alive(nieto), True)

    # La X de la ventana: lo que Tk ejecuta con `WM_DELETE_WINDOW`.
    ventana.tk.eval(ventana.protocol("WM_DELETE_WINDOW"))
    if nieto is not None:
        esperar_viva(lambda: not store.pid_alive(nieto))
        c("cerrar la ventana a media pasada mata también al nieto",
          store.pid_alive(nieto), False)
finally:
    tk.Toplevel.deiconify = deiconify
    if nieto is not None and store.pid_alive(nieto):
        liberar(nieto)
    raiz.destroy()

sys.exit(c.report())
