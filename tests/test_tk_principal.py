#!/usr/bin/env python3
"""La ventana principal: el aviso de arranque se puede descartar, y solo ese.

`main_window()` acaba en `mainloop()`, así que para conducirla se sustituye el
bucle por una sonda: cuando Tk le cede el control, la sonda deja que llegue la
lectura del dispositivo (que aquí se hace en el sitio, `segundo_plano.en_el_acto`,
y la aplica el primer `update_idletasks()`), mira la ventana ya pintada, pulsa
lo que tenga que pulsar y la cierra. Los `after(300, …)` que consultan GitHub y
recorren carpetas quedan encolados y no llegan a ejecutarse nunca, que es justo
lo que se quiere: aquí no se toca la red ni se recorre nada. Se mira solo lo que
está a la vista (`_vista.visibles`): la ventana guarda escondidos los bloques
que no enseña.

Lo que se comprueba es la diferencia entre un aviso y un estado. El aviso de
arranque («se ha parado el servicio que había») es algo que pasó y se lee una
vez. Los otros recuadros ámbar describen cómo está el dispositivo, y descartar
uno de esos sería esconder trabajo pendiente: por eso ninguno lleva
«Descartar».
"""

import sys

from _harness import Checks, sandbox

from common import components, config_file, conflicts, model, results, update

c = Checks("ventana principal: descartar el aviso de arranque")

try:
    import tkinter as tk
    from tkinter import ttk
    _probe = tk.Tk()
    _probe.withdraw()
    _probe.destroy()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(0)

from _vista import visibles  # noqa: E402

from ui import segundo_plano  # noqa: E402
from ui import tk as uitk  # noqa: E402

BASE = {"defaults": {"remote": "nas"},
        "pair": [{"name": "notas", "local": "sync-data/notas",
                  "remote_path": "/R/notas", "mode": "bisync"}]}

AVISO = "Servicio anterior (pid 4242) detenido."

# Nada de red ni de recorrer el dispositivo: la lectura de la ventana pregunta por
# estas cuatro, y aquí se contesta lo mismo siempre. Los sustitutos aceptan las
# palabras clave que les pasa la lectura (`fisica=`).
update.pending = lambda: None
results.fallos = lambda cfg: []
conflicts.cargar = lambda cfg: {}
conflicts.contar = lambda cargados: {}
components.pendientes = lambda **_k: []


def botones(ventana, texto):
    """Devuelve los botones a la vista de la ventana con ese texto."""
    return [w for w in visibles(ventana, texto=texto) if isinstance(w, ttk.Button)]


def textos(ventana):
    """Todo lo que la ventana tiene escrito a la vista, para buscar el aviso dentro."""
    return [str(w.cget("text")) for w in visibles(ventana) if "text" in w.keys()]


lecturas: list = []


def conducir(sonda, aviso=AVISO):
    """Abre la ventana principal con `sonda` en lugar del bucle de eventos.

    Antes de la sonda llega la lectura del dispositivo, y se apunta lo que no
    se pudo leer: un sustituto que no acepta una palabra clave nueva fallaría
    ahí sin ruido, y el campo se quedaría vacío.
    """
    real, real_lanzar = tk.Tk.mainloop, segundo_plano.lanzar

    def con_lectura(self, *a, **k):
        """Deja llegar la lectura y pasa a la sonda."""
        self.update_idletasks()
        lecturas.append(dict(self.instantanea.resultado.fallos))
        sonda(self, *a, **k)

    tk.Tk.mainloop = con_lectura
    segundo_plano.lanzar = segundo_plano.en_el_acto
    try:
        model.CONFIG_FILE.write_text(config_file.dumps(BASE), encoding="utf-8")
        return uitk.main_window(model.parse_config(BASE), aviso)
    finally:
        tk.Tk.mainloop, segundo_plano.lanzar = real, real_lanzar


# el aviso sale con su botón, y al pulsarlo se va
with sandbox():
    visto = {}

    def sonda(self, *_a, **_k):
        """Sonda: mira el aviso, pulsa «Descartar» y mira de nuevo."""
        visto["antes"] = any(AVISO in t for t in textos(self))
        visto["boton"] = len(botones(self, "Descartar"))
        visto["alto_antes"] = self.winfo_reqheight()
        for b in botones(self, "Descartar"):
            b.invoke()
        visto["despues"] = any(AVISO in t for t in textos(self))
        visto["sigue"] = len(botones(self, "Descartar"))
        visto["alto_despues"] = self.winfo_reqheight()
        self.destroy()

    conducir(sonda)
    c("el aviso de arranque se pinta", visto["antes"], True)
    c("con un botón para descartarlo", visto["boton"], 1)
    c("al pulsarlo el aviso desaparece", visto["despues"], False)
    c("y el botón con él", visto["sigue"], 0)
    c("la ventana encoge, que es la señal de que el bloque se ha ido",
      visto["alto_despues"] < visto["alto_antes"], True)

# sin aviso no hay nada que descartar
with sandbox():
    sin = {}

    def sonda_sin(self, *_a, **_k):
        """Sonda: cuenta los botones «Descartar» de una ventana sin aviso."""
        sin["boton"] = len(botones(self, "Descartar"))
        self.destroy()

    conducir(sonda_sin, aviso=None)
    c("sin aviso de arranque no aparece ningún «Descartar»", sin["boton"], 0)

# un estado NO se descarta
#
# Una pareja que falló es estado del dispositivo: se va cuando haya una pasada
# buena, no cuando alguien cierre el aviso. Ya no tiene recuadro propio —lo
# cuenta la línea que lleva a «Reparación»—, pero la regla es la misma: si
# algún día esa línea estrena un «Descartar», que sea leyendo esto.
with sandbox():
    estado = {}
    results.fallos = lambda cfg: [results.Fallo(
        pareja="notas", cuando="2026-01-01 00:00:00", codigo=1, log=None)]

    def sonda_fallo(self, *_a, **_k):
        """Sonda: mira si el fallo es un estado sin «Descartar»."""
        estado["falla"] = any("que revisar" in t for t in textos(self))
        estado["descartables"] = len(botones(self, "Descartar"))
        self.destroy()

    conducir(sonda_fallo, aviso=None)
    c("el fallo de la última pasada se cuenta", estado["falla"], True)
    c("y no se puede descartar", estado["descartables"], 0)
results.fallos = lambda cfg: []

# «Expulsar»: solo dentro de un contenedor VeraCrypt
#
# Cerrar la ventana no cierra el contenedor, y con él abierto no se puede
# quitar la unidad. El botón no desmonta nada él mismo —este proceso corre
# desde dentro del contenedor—: lanza el script del vestíbulo y se cierra.
from pathlib import Path  # noqa: E402
from tkinter import messagebox  # noqa: E402

from ui import cifrado  # noqa: E402

reales = (cifrado.expulsion, cifrado.lanzar_expulsion, messagebox.askokcancel)
reales_expulsion = cifrado.expulsion
SCRIPT = Path("E:/Expulsar PRDRIVE.bat")
lanzados: list = []
try:
    with sandbox():
        sin_boton = {}

        def sonda_sin_contenedor(self, *_a, **_k):
            """Sonda: cuenta los botones «Expulsar» fuera de un contenedor."""
            sin_boton["n"] = len(botones(self, "Expulsar"))
            self.destroy()

        cifrado.expulsion = lambda **_k: None
        conducir(sonda_sin_contenedor, aviso=None)
        c("sin contenedor no hay «Expulsar»", sin_boton["n"], 0)

    cifrado.expulsion = lambda **_k: SCRIPT
    cifrado.lanzar_expulsion = lambda script: lanzados.append(script)

    with sandbox():
        cancelado = {}
        messagebox.askokcancel = lambda *a, **k: False

        def sonda_cancelar(self, *_a, **_k):
            """Sonda: pulsa «Expulsar» y comprueba que cancelar no cierra la ventana."""
            cancelado["n"] = len(botones(self, "Expulsar"))
            botones(self, "Expulsar")[0].invoke()
            cancelado["viva"] = bool(self.winfo_exists())
            self.destroy()

        conducir(sonda_cancelar, aviso=None)
        c("dentro de un contenedor, «Expulsar» está", cancelado["n"], 1)
        c("si no se confirma, no se lanza nada", lanzados, [])
        c("y la ventana sigue abierta", cancelado["viva"], True)

    with sandbox():
        hecho = {}
        messagebox.askokcancel = lambda *a, **k: True

        def sonda_expulsar(self, *_a, **_k):
            """Sonda: pulsa «Expulsar» y mira si la ventana se cierra."""
            botones(self, "Expulsar")[0].invoke()
            try:
                hecho["viva"] = bool(self.winfo_exists())
                self.destroy()
            except tk.TclError:
                hecho["viva"] = False

        eleccion = conducir(sonda_expulsar, aviso=None)
        c("al confirmar, se lanza el script del vestíbulo", lanzados, [SCRIPT])
        c("y la ventana se cierra, para que el contenedor se pueda desmontar",
          hecho["viva"], False)
        c("sin devolverle nada a runsync: no hay servicio que arrancar", eleccion, None)
finally:
    cifrado.expulsion, cifrado.lanzar_expulsion, messagebox.askokcancel = reales

# «Bloquear»: la raíz cifrada de un equipo
#
# No hay script del vestíbulo: el contenedor lo cierra el agente residente. El
# botón se lo pide por su buzón y cierra la ventana.
reales = (cifrado.bloqueo, cifrado.pedir_bloqueo, messagebox.askokcancel,
          messagebox.showerror)
pedidos: list = []
errores: list = []
UID = "c" * 32
try:
    cifrado.bloqueo = lambda: UID
    cifrado.expulsion = lambda **_k: None
    messagebox.askokcancel = lambda *a, **k: True
    messagebox.showerror = lambda *a, **k: errores.append(a)

    with sandbox():
        sin_agente = {}
        cifrado.pedir_bloqueo = lambda uid: False

        def sonda_sin_agente(self, *_a, **_k):
            """Sonda: pulsa «Bloquear» sin agente vivo y mira qué botones hay."""
            sin_agente["botones"] = (len(botones(self, "Bloquear")),
                                     len(botones(self, "Expulsar")))
            botones(self, "Bloquear")[0].invoke()
            sin_agente["viva"] = bool(self.winfo_exists())
            self.destroy()

        conducir(sonda_sin_agente, aviso=None)
        c("en la raíz cifrada de un equipo, «Bloquear» y no «Expulsar»",
          sin_agente["botones"], (1, 0))
        c("sin agente que lo haga, lo dice y la ventana sigue",
          (len(errores), sin_agente["viva"]), (1, True))

    with sandbox():
        hecho = {}
        cifrado.pedir_bloqueo = lambda uid: pedidos.append(uid) or True

        def sonda_bloquear(self, *_a, **_k):
            """Sonda: pulsa «Bloquear» y mira si la ventana se cierra."""
            botones(self, "Bloquear")[0].invoke()
            try:
                hecho["viva"] = bool(self.winfo_exists())
                self.destroy()
            except tk.TclError:
                hecho["viva"] = False

        eleccion = conducir(sonda_bloquear, aviso=None)
        c("al confirmar, se lo pide al agente con el id de la raíz", pedidos, [UID])
        c("y la ventana se cierra, para que el agente pueda desmontar",
          (hecho["viva"], eleccion), (False, None))
finally:
    (cifrado.bloqueo, cifrado.pedir_bloqueo, messagebox.askokcancel,
     messagebox.showerror) = reales
    cifrado.expulsion = reales_expulsion

c("cada lectura de la ventana se hizo sin fallos", [f for f in lecturas if f], [])
sys.exit(c.report())
