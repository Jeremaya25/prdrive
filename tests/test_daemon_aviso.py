#!/usr/bin/env python3
"""El servicio avisa cuando falla un ciclo, y solo entonces.

Un servicio que falla en silencio es peor que no tener servicio: el usuario
cree que el dispositivo está al día. Lo que se comprueba es cuándo abre su
ventanita (un ciclo que falla, no uno que va bien ni el mismo fallo repetido
cada media hora), qué hace si no hay pantalla (lo apunta en el diario), y que
sigue sin preguntar nada: stdin cerrado, así que una pareja que pide `--resync`
se salta.
"""

import sys
import threading
import time

from _harness import Checks, sandbox

import runsync
import ui
from common import model, results, update
from ui import theme

c = Checks("el servicio avisa de los ciclos que fallan")

diario: list[str] = []
runsync.dlog = diario.append
runsync.pen_present = lambda: True
runsync.stop_requested = lambda: False
runsync.write_lock = lambda data: None
update.check = lambda force=False: (None, None)
update.pending = lambda root=None: None

avisos: list[list[str]] = []
NOTIFICAR_REAL = runsync.notificar_fallo
runsync.notificar_fallo = lambda nombres: avisos.append(list(nombres))

codigos: dict[str, int] = {}
CORRER_REAL = runsync.run_pair_quiet
runsync.run_pair_quiet = lambda name: (codigos.get(name, 0), "salida")


def ciclo(lock: dict, **rc) -> None:
    """Hace un ciclo del servicio con esos códigos de salida por pareja."""
    codigos.clear()
    codigos.update(rc)
    runsync.daemon_cycle(["notas", "fotos"], lock)


lock: dict = {}
ciclo(lock)
c("un ciclo bueno no enseña nada", avisos, [])

ciclo(lock, notas=1)
c("un ciclo con un fallo avisa, con las parejas que fallaron", avisos, [["notas"]])

ciclo(lock, notas=1)
c("el mismo fallo en el ciclo siguiente no vuelve a saltar", len(avisos), 1)

ciclo(lock, notas=1, fotos=1)
c("una pareja que empieza a fallar sí avisa, con todas las que fallan",
  avisos[-1], ["notas", "fotos"])

ciclo(lock)
ciclo(lock, notas=1)
c("tras un ciclo bueno, volver a fallar vuelve a avisar", avisos[-1], ["notas"])


# lo que hace el aviso de verdad, con y sin pantalla
import ui.tk  # noqa: E402

rs = runsync

with sandbox():
    real = ui.tk.aviso_fallo
    ui.tk.aviso_fallo = lambda fallos, al_abrir=None: (_ for _ in ()).throw(
        RuntimeError("no hay display"))
    diario.clear()
    try:
        inicio = time.monotonic()
        NOTIFICAR_REAL(["notas"])
        c("sin pantalla no se queda esperando", time.monotonic() - inicio < 5, True)
        c("y lo deja dicho en el diario", any("solo en este diario" in l for l in diario),
          True)
    finally:
        ui.tk.aviso_fallo = real

with sandbox():
    model.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = model.LOG_DIR / "notas_1.log"
    log.write_text("x", encoding="utf-8")
    results.apuntar("notas", 1, log)
    recibidos = []

    def ventana_falsa(fallos, al_abrir=None):
        """Ventana de aviso de mentira: apunta los fallos y llama a `al_abrir`."""
        recibidos.append([(f.pareja, f.log) for f in fallos])
        if al_abrir:
            al_abrir()

    real = ui.tk.aviso_fallo
    ui.tk.aviso_fallo = ventana_falsa
    diario.clear()
    try:
        c("con pantalla dice que lo ha enseñado", ui.avisar_fallo(["notas"]), True)
        limite = time.monotonic() + 5
        while not recibidos and time.monotonic() < limite:
            time.sleep(0.02)
        c("la ventana recibe el fallo con su log", recibidos, [[("notas", log)]])
    finally:
        ui.tk.aviso_fallo = real


# la ventanita de verdad, en su hilo
#
# Tk en un hilo que no es el principal es lo delicado: todo lo suyo tiene que
# nacer y morir ahí. Se abre de verdad (sin enseñarla) y se cierra sola.
try:
    import tkinter as tk
    tk.Tk().destroy()
    hay_pantalla = True
except Exception as e:                                   # noqa: BLE001
    print(f"  (saltado) la ventanita: no hay entorno gráfico: {e}")
    hay_pantalla = False

def esperar_a(condicion, limite=10.0) -> bool:
    """Espera (sin Tk) a que se cumpla la condición, o a que pase el límite."""
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(0.02)
    return False


if hay_pantalla:
    with sandbox():
        results.apuntar("notas", 1, None)
        visto: dict = {}
        real_deiconify, real_mainloop = tk.Tk.deiconify, tk.Tk.mainloop

        def mainloop_breve(self):
            """Bucle de Tk de mentira: mira los botones de la ventana y la cierra."""
            def mirar():
                """Apunta el texto de los botones y destruye la ventana."""
                pila = [self]
                while pila:
                    w = pila.pop()
                    pila += list(w.winfo_children())
                    if isinstance(w, tk.ttk.Button):
                        visto.setdefault("botones", []).append(w.cget("text"))
                self.destroy()
            self.after(100, mirar)
            tk.Misc.mainloop(self)

        tk.Tk.deiconify = lambda self: None
        tk.Tk.mainloop = mainloop_breve
        try:
            import tkinter.ttk  # noqa: F401
            c("en un hilo propio, la ventanita se abre", ui.avisar_fallo(["notas"]), True)
            primero = ui._aviso_abierto["hilo"]
            c("  y no es el hilo del servicio",
              primero is not threading.current_thread(), True)
            c("y se cierra: el aviso acaba", esperar_a(lambda: not ui._aviso_abierto["activo"]),
              True)
            c("sin log conservado, solo ofrece cerrar", visto.get("botones"), ["Cerrar"])
            c("el hilo no acaba con el aviso: espera al siguiente", primero.is_alive(), True)
            c("se puede volver a abrir en el ciclo siguiente", ui.avisar_fallo(["notas"]),
              True)
            c("  en el mismo hilo (Tk 9 aborta con uno nuevo tras acabar el anterior)",
              ui._aviso_abierto["hilo"] is primero, True)
            c("  y también acaba", esperar_a(lambda: not ui._aviso_abierto["activo"]), True)
            c("  y las dos sueltan su letra en su hilo: no queda ficha de ningún intérprete",
              theme._LETRA, {})
            c("  y con una ventana en curso no se abre otra",
              (ui._aviso_abierto.__setitem__("activo", True),
               ui.avisar_fallo(["notas"]))[1], True)
            ui._aviso_abierto["activo"] = False
            c("  y las dos ventanas que se abrieron llevaban el botón de cerrar",
              visto["botones"], ["Cerrar", "Cerrar"])
        finally:
            tk.Tk.deiconify, tk.Tk.mainloop = real_deiconify, real_mainloop


# el servicio no pregunta nunca
llamadas = []


class _Resultado:
    """Resultado de un proceso que acaba bien y sin salida."""
    returncode = 0
    stdout = ""
    stderr = ""


real_run = rs.subprocess.run
rs.subprocess.run = lambda cmd, **kw: llamadas.append(kw) or _Resultado()
try:
    CORRER_REAL("notas")
finally:
    rs.subprocess.run = real_run
c("cada pareja corre con stdin cerrado: sync.py no puede preguntar, y un resync "
  "pendiente se salta", llamadas[0].get("stdin"), rs.subprocess.DEVNULL)

sys.exit(c.report())
