#!/usr/bin/env python3
"""
Conflictos y fallos en las ventanas, conducidos sin nadie delante.

Como en test_tk_screens: no se mira el aspecto sino el cableado. Que un botón
de la ventana de conflictos acabe dejando en disco la versión que dice, que la
ventana principal enseñe el fallo y el conflicto que hay en state/, y que siga
viva —y al día— después de cerrar la ventana de salida de una sincronización.

Las ventanas se crean ocultas y no se entra nunca en el bucle de eventos.
"""

import sys
import time

from _harness import Checks, sandbox, tmpdir

from common import conflicts, model, results, update

c = Checks("conflictos y fallos en las ventanas (cableado)")

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(0)

import ui
from ui import prefs, tk_conflicts, tk_pairs
from ui import tk as uitk

prefs.PREFS = tmpdir("prdrive-tkconf-") / "ui_prefs.json"
update.pending = lambda root=None: None
update.check = lambda force=False: (None, None)
update.fetch = lambda url, timeout: c("ningún test toca la red", "fetch", "nada")
# Sin baseline, la pareja pediría un resync y su chip taparía el de conflictos.
for _m in (ui, uitk):
    _m.pair_status_notes = lambda cfg: {}

errores: list[str] = []
messagebox.showerror = lambda titulo, texto=None, **k: errores.append(str(texto))
messagebox.showinfo = lambda *a, **k: None
messagebox.askyesno = lambda *a, **k: False

tk_conflicts.mostrar = lambda dlg, parent=None: dlg.wait_window()
confirmaciones: list[str] = []


def confirmar(respuesta):
    def _confirmar(parent, plan, titulo, nota):
        confirmaciones.append(titulo)
        return respuesta
    return _confirmar


tk_pairs.confirmar_plan = confirmar(True)
abiertos: list = []
tk_conflicts.abrir = abiertos.append
uitk.abrir = abiertos.append

RAW = {"defaults": {"remote": "nas"},
       "pair": [{"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas"}]}


def preparar():
    cfg = model.parse_config(RAW)
    return cfg, cfg.pairs[0]


def escribir(ruta, texto):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8")
    return ruta


def recorrer(w):
    for hijo in w.winfo_children():
        yield hijo
        yield from recorrer(hijo)


def botones(w) -> dict:
    return {b.cget("text"): b for b in recorrer(w) if isinstance(b, ttk.Button)}


def textos(w) -> list[str]:
    return [str(l.cget("text")) for l in recorrer(w) if isinstance(l, ttk.Label)]


def en_la_ventana(accion):
    """Un wait_window que, en vez de esperar, hace algo con el diálogo."""
    def _wait(self, *_a, **_k):
        accion(self)
    return _wait


def elegir(dlg, iid):
    arbol = next(w for w in recorrer(dlg) if isinstance(w, ttk.Treeview))
    arbol.selection_set(iid)
    arbol.event_generate("<<TreeviewSelect>>")


# --- la ventana de conflictos -----------------------------------------------------
with sandbox():
    cfg, p = preparar()
    escribir(p.local_abs / "plan.md", "del remoto")
    escribir(p.local_abs / "plan.md.conflicto-dispositivo1", "de aquí")
    conflicts.actualizar_pareja(p)
    estados = {}

    def mirar_y_pulsar(dlg):
        b = botones(dlg)
        estados.update({t: str(b[t].cget("state")) for t in b})
        b["Quedarme con la de este dispositivo"].invoke()

    tk.Toplevel.wait_window = en_la_ventana(mirar_y_pulsar)
    cambiado = tk_conflicts.open_dialog(raiz, cfg)
    c("con el fichero elegido, los dos lados se pueden conservar",
      (estados["Quedarme con la de este dispositivo"], estados["Quedarme con la del remoto"]),
      ("normal", "normal"))
    c("«la elegida» pide elegir una versión, no el fichero",
      estados["Quedarme con la elegida"], "disabled")
    c("pasa por la confirmación de siempre", confirmaciones[-1:],
      ["Quedarse con la versión de este dispositivo"])
    c("la versión de este dispositivo queda con su nombre",
      (p.local_abs / "plan.md").read_text(encoding="utf-8"), "de aquí")
    c("la copia desaparece", (p.local_abs / "plan.md.conflicto-dispositivo1").exists(), False)
    c("informa de que ha cambiado algo", cambiado, True)
    c("y el estado ya no tiene el conflicto", conflicts.contar(conflicts.cargar(cfg)), {})

with sandbox():
    cfg, p = preparar()
    escribir(p.local_abs / "plan.md", "del remoto")
    escribir(p.local_abs / "plan.md.conflicto-dispositivo1", "de aquí")
    conflicts.actualizar_pareja(p)
    tk_pairs.confirmar_plan = confirmar(False)
    tk.Toplevel.wait_window = en_la_ventana(
        lambda dlg: botones(dlg)["Quedarme con la del remoto"].invoke())
    c("cancelar la confirmación no cambia nada", tk_conflicts.open_dialog(raiz, cfg), False)
    c("los dos ficheros siguen ahí", sorted(x.name for x in p.local_abs.iterdir()),
      ["plan.md", "plan.md.conflicto-dispositivo1"])
    tk_pairs.confirmar_plan = confirmar(True)

    abiertos.clear()
    tk.Toplevel.wait_window = en_la_ventana(lambda dlg: (
        botones(dlg)["Abrir la carpeta"].invoke(),
        botones(dlg)["Abrir las versiones"].invoke()))
    tk_conflicts.open_dialog(raiz, cfg)
    c("«Abrir la carpeta» abre la carpeta del fichero, y «las versiones» las dos",
      [x.name for x in abiertos], ["notas", "plan.md", "plan.md.conflicto-dispositivo1"])

with sandbox():
    # Un conflicto de antes de los sufijos por lado: no se sabe de quién es cada
    # versión, así que los botones de lado se apagan y hay que elegir una.
    cfg, p = preparar()
    escribir(p.local_abs / "v.md", "actual")
    escribir(p.local_abs / "v.md.conflict1", "otra")
    conflicts.actualizar_pareja(p)
    estados = {}

    def elegir_la_copia(dlg):
        b = botones(dlg)
        estados["lado"] = str(b["Quedarme con la de este dispositivo"].cget("state"))
        elegir(dlg, "c0v1")
        estados["elegida"] = str(b["Quedarme con la elegida"].cget("state"))
        b["Quedarme con la elegida"].invoke()

    tk.Toplevel.wait_window = en_la_ventana(elegir_la_copia)
    tk_conflicts.open_dialog(raiz, cfg)
    c("sin lado conocido, el botón de lado se apaga", estados["lado"], "disabled")
    c("y al elegir una versión se enciende «la elegida»", estados["elegida"], "normal")
    c("la versión elegida queda con su nombre",
      (p.local_abs / "v.md").read_text(encoding="utf-8"), "otra")

with sandbox():
    cfg, _p = preparar()
    vistos = []
    tk.Toplevel.wait_window = en_la_ventana(lambda dlg: vistos.extend(textos(dlg)))
    tk_conflicts.open_dialog(raiz, cfg)
    c("sin conflictos lo dice", "No queda ningún fichero en conflicto." in vistos, True)


# --- la ventana principal ------------------------------------------------------------
lanzadas: list[dict] = []


def salida_falsa(titulo, cmd, parent=None, subtitulo="", modal=True, al_cerrar=None):
    lanzadas.append({"titulo": titulo, "cmd": cmd, "parent": parent, "modal": modal,
                     "al_cerrar": al_cerrar})
    return None


SALIDA_REAL = uitk.output_window
uitk.output_window = salida_falsa


def ventana_principal(cfg, conducir):
    """Abre la principal y, en vez de su bucle de eventos, ejecuta `conducir`."""
    def _mainloop(self):
        conducir(self)
        try:
            # Lo que la ventana dejó programado (la versión, el escaneo) no se
            # llega a ejecutar: el último tramo sí mueve el bucle de eventos, y
            # ahí saltaría contra una ventana que ya no existe.
            for pendiente in self.tk.splitlist(self.tk.call("after", "info")):
                self.after_cancel(pendiente)
            self.destroy()
        except tk.TclError:
            pass             # ya la cerró el propio botón (el del servicio)
    tk.Tk.mainloop = _mainloop
    return uitk.main_window(cfg, None)


with sandbox():
    cfg, _p = preparar()
    model.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = escribir(model.LOG_DIR / "notas_20260911_101010.log", "ERROR\n")
    results.apuntar("notas", 1, log)
    vistos = {}

    def mirar_fallo(root):
        vistos["textos"] = textos(root)
        abiertos.clear()
        botones(root)["Ver el log"].invoke()

    ventana_principal(cfg, mirar_fallo)
    c("un fallo de la última pasada sale en ámbar al abrir",
      any("La última pasada falló en" in t and "notas" in t for t in vistos["textos"]), True)
    c("y su botón abre el log que se conservó", abiertos, [log])

with sandbox():
    cfg, p = preparar()
    escribir(p.local_abs / "plan.md", "del remoto")
    escribir(p.local_abs / "plan.md.conflicto-dispositivo1", "de aquí")
    conflicts.actualizar_pareja(p)
    abiertas = []
    real_dialogo = tk_conflicts.open_dialog
    tk_conflicts.open_dialog = lambda parent, config: abiertas.append(config) or False
    vistos = {}

    def mirar_conflicto(root):
        vistos["textos"] = textos(root)
        botones(root)["Revisar…"].invoke()

    try:
        ventana_principal(cfg, mirar_conflicto)
    finally:
        tk_conflicts.open_dialog = real_dialogo
    c("la pareja con conflictos lleva su chip", "1 conflicto" in vistos["textos"], True)
    c("y la cabecera lo cuenta", "1 en conflicto" in vistos["textos"], True)
    c("hay un bloque que lleva a resolverlos",
      any("en conflicto en notas" in t for t in vistos["textos"]), True)
    c("su botón abre la ventana de conflictos", len(abiertas), 1)

with sandbox():
    # El fallo de siempre: «Sincronizar ahora» cerraba la ventana principal y al
    # terminar no había a dónde volver.
    cfg, p = preparar()
    lanzadas.clear()
    vistos = {}

    def sincronizar_y_volver(root):
        b = botones(root)
        b["Sincronizar ahora"].invoke()
        vistos["viva"] = bool(root.winfo_exists())
        vistos["durante"] = {t: str(w.cget("state")) for t, w in botones(root).items()}
        vistos["chip durante"] = "sincronizando…" in textos(root)
        # Lo que habría hecho sync.py: dejar un conflicto apuntado en state/.
        escribir(p.local_abs / "plan.md", "del remoto")
        escribir(p.local_abs / "plan.md.conflicto-dispositivo1", "de aquí")
        conflicts.actualizar_pareja(p)
        lanzadas[-1]["al_cerrar"](0)
        vistos["despues"] = {t: str(w.cget("state")) for t, w in botones(root).items()}
        vistos["textos"] = textos(root)
        vistos["viva después"] = bool(root.winfo_exists())

    eleccion = ventana_principal(cfg, sincronizar_y_volver)
    c("sincronizar abre la salida colgada de la principal, sin bloquearla",
      (lanzadas[0]["parent"] is not None, lanzadas[0]["modal"]), (True, False))
    c("con la orden de sync.py y la pareja elegida",
      lanzadas[0]["cmd"][1:], [str(model.SYNC_PY), "notas"])
    c("la principal sigue abierta mientras sincroniza", vistos["viva"], True)
    c("y no deja lanzar otra pasada a la vez",
      (vistos["durante"]["Sincronizar ahora"], vistos["durante"]["Iniciar servicio"],
       vistos["durante"]["Doctor"], vistos["durante"]["Parejas…"]),
      ("disabled", "disabled", "disabled", "disabled"))
    c("la cabecera dice que está sincronizando", vistos["chip durante"], True)
    c("al cerrar la salida, la principal sigue ahí", vistos["viva después"], True)
    c("con los botones otra vez disponibles", vistos["despues"]["Sincronizar ahora"],
      "normal")
    c("y con los chips al día (el conflicto que dejó la pasada)",
      "1 conflicto" in vistos["textos"], True)
    c("sincronizar ya no es una elección que salga de la ventana", eleccion, None)
    c("lo elegido se recuerda para la próxima vez", prefs.read_prefs().get("pairs"),
      ["notas"])

with sandbox():
    cfg, _p = preparar()
    lanzadas.clear()
    ventana_principal(cfg, lambda root: botones(root)["Doctor"].invoke())
    c("el doctor también corre sin cerrar la principal",
      (lanzadas[0]["cmd"][-1], lanzadas[0]["modal"]), ("--doctor", False))

with sandbox():
    cfg, _p = preparar()
    eleccion = ventana_principal(cfg, lambda root: botones(root)["Iniciar servicio"].invoke())
    c("el servicio sí sale de la ventana: lo arranca runsync",
      (eleccion.action, eleccion.pairs), ("daemon", ("notas",)))


# --- la ventana de salida sin bloquear, con un proceso de verdad -----------------------
real_deiconify = tk.Toplevel.deiconify
tk.Toplevel.deiconify = lambda self: None               # nada se enseña en un test
recibido: list = []
try:
    antes = set(raiz.winfo_children())
    vuelta = SALIDA_REAL(
        "Prueba", [sys.executable, "-c", "print('hola')"], parent=raiz,
        modal=False, al_cerrar=recibido.append)
    c("sin bloquear vuelve enseguida", vuelta, None)
    salida = next(w for w in raiz.winfo_children() if w not in antes)
    limite = time.monotonic() + 20
    while time.monotonic() < limite and "Terminado" not in \
            next(w for w in recorrer(salida) if isinstance(w, tk.Text)).get("1.0", "end"):
        raiz.update()
        time.sleep(0.05)
    botones(salida)["Cerrar"].invoke()
    raiz.update()
    c("al cerrarla avisa una vez, con el código de salida", recibido, [0])
    c("y la ventana de debajo sigue viva", bool(raiz.winfo_exists()), True)
finally:
    tk.Toplevel.deiconify = real_deiconify

raiz.destroy()
sys.exit(c.report())
