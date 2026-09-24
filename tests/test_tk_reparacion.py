#!/usr/bin/env python3
"""
La pantalla de «Reparación» y la ventana principal, conducidas sin nadie delante.

Como en test_tk_screens: no se mira el aspecto sino el cableado. Que un botón de
la sección de conflictos acabe dejando en disco la versión que dice, que una
avería se arregle desde su fila, que la ventana principal cuente lo que hay que
revisar en una línea —y no en tres recuadros ámbar— y que siga viva, y al día,
después de cerrar la ventana de salida de una sincronización.

Las ventanas se crean ocultas y no se entra nunca en el bucle de eventos.
"""

import hashlib
import sys
import time
from pathlib import Path

from _harness import Checks, sandbox, tmpdir

from common import bisync, conflicts, model, results, update

c = Checks("«Reparación» y la ventana principal (cableado)")

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(0)

import ui
from ui import prefs, tk_conflicts, tk_doctor, tk_pairs, tk_repair
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

tk_doctor.mostrar = lambda dlg, parent=None: dlg.destroy()
confirmaciones: list[str] = []


def confirmar(respuesta):
    def _confirmar(parent, plan, titulo, nota):
        confirmaciones.append(titulo)
        return respuesta
    return _confirmar


tk_pairs.confirmar_plan = confirmar(True)
abiertos: list = []
tk_conflicts.abrir = abiertos.append
tk_repair.abrir = abiertos.append
uitk.abrir = abiertos.append

RAW = {"defaults": {"remote": "nas"},
       "pair": [{"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas"}]}


def preparar(sana: bool = True):
    """El config del test y su pareja, con el baseline ya hecho.

    Con `sana`, la pareja queda como después de un --resync: carpeta local, los
    dos listados con el prefijo que le toca y el md5 de los filtros. Si no, cada
    bloque de aquí abajo encontraría además «falta el resync» y «aún no hay
    carpeta», y estaría contando averías que no ha puesto él."""
    cfg = model.parse_config(RAW)
    pair = cfg.pairs[0]
    if sana:
        pair.local_abs.mkdir(parents=True, exist_ok=True)
        pair.workdir.mkdir(parents=True, exist_ok=True)
        prefijo = bisync.expected_prefix(pair)
        for sufijo in (bisync.PATH1_SUFFIX, bisync.PATH2_SUFFIX):
            (pair.workdir / f"{prefijo}{sufijo}").write_text("x", encoding="utf-8")
        ffile = bisync.filters_file_for(pair)
        if ffile is not None:
            Path(str(ffile) + ".md5").write_text(
                hashlib.md5(ffile.read_bytes()).hexdigest(), encoding="utf-8")
    return cfg, pair


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


desde_reparacion: list[tuple] = []


def lanzar_falso(titulo, args):
    """El `lanzar` de la ventana principal: «Reparación» no abre la salida, la
    pide. Aquí solo se apunta lo que habría lanzado."""
    desde_reparacion.append((titulo, args))


def reparacion(cfg, conducir, marcadas=None):
    """Abre «Reparación» y, en vez de enseñarla, ejecuta `conducir(dlg)`.

    Se sustituye `mostrar` y no `modal`, como en el resto de los tests de
    pantallas: la ventana se monta de verdad, con sus botones y su árbol, y lo
    único que no pasa es que se vea."""
    tk_repair.mostrar = lambda dlg, parent=None: conducir(dlg)
    return tk_repair.open_dialog(raiz, cfg, lanzar_falso, marcadas)


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

    cambiado = reparacion(cfg, mirar_y_pulsar)
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
    c("cancelar la confirmación no cambia nada",
      reparacion(cfg, lambda dlg: botones(dlg)["Quedarme con la del remoto"].invoke()),
      False)
    c("los dos ficheros siguen ahí", sorted(x.name for x in p.local_abs.iterdir()),
      ["plan.md", "plan.md.conflicto-dispositivo1"])
    tk_pairs.confirmar_plan = confirmar(True)

    abiertos.clear()
    reparacion(cfg, lambda dlg: (botones(dlg)["Abrir la carpeta"].invoke(),
                                 botones(dlg)["Abrir las versiones"].invoke()))
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

    reparacion(cfg, elegir_la_copia)
    c("sin lado conocido, el botón de lado se apaga", estados["lado"], "disabled")
    c("y al elegir una versión se enciende «la elegida»", estados["elegida"], "normal")
    c("la versión elegida queda con su nombre",
      (p.local_abs / "v.md").read_text(encoding="utf-8"), "otra")

with sandbox():
    cfg, _p = preparar()
    vistos = []
    puesta = []

    def mirar(dlg):
        vistos.extend(textos(dlg))
        # La sección de conflictos se monta siempre y se quita de la rejilla
        # cuando no hay ninguno, así que lo que dice si se ve o no es su
        # `grid_info`, no que sus etiquetas existan. Se llega a ella por su
        # árbol: sección -> tarjeta -> árbol.
        arbol = next(w for w in recorrer(dlg) if isinstance(w, ttk.Treeview))
        puesta.append(bool(arbol.master.master.grid_info()))

    reparacion(cfg, mirar)
    c("sin nada roto, la pantalla lo dice",
      any("No hay nada que revisar" in x for x in vistos), True)
    c("y la sección de conflictos no se enseña", puesta, [False])


# --- las reparaciones de la pantalla ------------------------------------------------
with sandbox():
    # Un baseline guardado con el prefijo de otro destino: la avería que de
    # verdad puede acabar en un borrado masivo si se reaprovecha. Se aparta.
    cfg, p = preparar()
    for viejo in p.workdir.glob("*.lst"):
        viejo.unlink()
    for sufijo in (bisync.PATH1_SUFFIX, bisync.PATH2_SUFFIX):
        (p.workdir / f"otro-destino{sufijo}").write_text("x", encoding="utf-8")
    confirmaciones.clear()

    visto = {}

    def apartar(dlg):
        visto["antes"] = [x for x in textos(dlg) if "baseline no es" in x]
        botones(dlg)["Apartar el baseline…"].invoke()
        visto["despues"] = [x for x in textos(dlg) if "baseline no es" in x]
        visto["botones"] = sorted(botones(dlg))

    cambiado = reparacion(cfg, apartar)
    c("la avería del prefijo sale con su fila", len(visto["antes"]), 1)
    c("apartar pasa por la confirmación de siempre",
      confirmaciones[-1:], ["Apartar el baseline de «notas»"])
    c("y el baseline se aparta con fecha, sin borrarse",
      len(list(model.STATE_DIR.glob("notas.old-*"))), 1)
    c("la pantalla se repinta: la avería ya no está", visto["despues"], [])
    c("y la pareja pasa a pedir un resync", "Resincronizar…" in visto["botones"], True)
    c("se avisa a quien abrió la pantalla de que algo ha cambiado", cambiado, True)

with sandbox():
    # Un bloqueo suelto, sin nadie sincronizando: se puede borrar.
    cfg, p = preparar()
    lock = escribir(p.workdir / "suelto.lck", "")
    confirmaciones.clear()
    reparacion(cfg, lambda dlg: botones(dlg)["Borrar los bloqueos…"].invoke())
    c("borrar bloqueos también se confirma",
      confirmaciones[-1:], ["Borrar los bloqueos de «notas»"])
    c("y el bloqueo se va", lock.exists(), False)

with sandbox():
    # El resync no es un plan de disco: se confirma y se lanza como pasada, con
    # la pantalla ya cerrada para no dejar dos modales a la vez.
    cfg, p = preparar()
    for viejo in p.workdir.glob("*.lst"):
        viejo.unlink()
    desde_reparacion.clear()
    vivas = []

    def resincronizar(dlg):
        botones(dlg)["Resincronizar…"].invoke()
        vivas.append(bool(dlg.winfo_exists()))

    reparacion(cfg, resincronizar)
    c("el resync se lanza como una pasada más", desde_reparacion,
      [("Resincronizar «notas»", ["notas", "--resync", "--yes"])])
    c("y la pantalla se cierra antes de ceder el paso", vivas, [False])

with sandbox():
    cfg, _p = preparar()
    desde_reparacion.clear()
    reparacion(cfg, lambda dlg: botones(dlg)["Simular una pasada…"].invoke(),
               marcadas=["notas"])
    c("simular lanza un --dry-run de lo que está marcado", desde_reparacion,
      [("Simulación", ["notas", "--dry-run"])])

    desde_reparacion.clear()
    reparacion(cfg, lambda dlg: botones(dlg)["Ver el informe completo"].invoke())
    c("y el informe completo sigue siendo --doctor", desde_reparacion,
      [("Informe del estado", ["--doctor"])])


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
    # El fallo de la última pasada ya no tiene recuadro propio: la ventana
    # principal dice cuántas cosas hay que revisar y lleva a «Reparación», que
    # es donde está el log y todo lo demás.
    cfg, _p = preparar()
    model.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = escribir(model.LOG_DIR / "notas_20260911_101010.log", "ERROR\n")
    results.apuntar("notas", 1, log)
    vistos = {}
    abiertas = []

    def mirar_fallo(root):
        vistos["textos"] = textos(root)
        vistos["botones"] = sorted(botones(root))
        botones(root)["Reparación…"].invoke()

    real_reparacion = tk_repair.open_dialog
    tk_repair.open_dialog = (lambda parent, config, lanzar, marcadas=None:
                             abiertas.append(marcadas) or False)
    try:
        ventana_principal(cfg, mirar_fallo)
    finally:
        tk_repair.open_dialog = real_reparacion

    c("un fallo apuntado se cuenta en una línea, sin recuadro",
      any("Hay 1 cosa que revisar." == x for x in vistos["textos"]), True)
    c("y el ámbar de «La última pasada falló en» ya no está",
      any("La última pasada falló en" in x for x in vistos["textos"]), False)
    c("la cabecera cuenta lo mismo", "1 que revisar" in vistos["textos"], True)
    c("y su botón abre «Reparación», con las parejas marcadas",
      abiertas, [["notas"]])

with sandbox():
    # Y dentro de «Reparación», el log se abre desde la fila del fallo.
    cfg, _p = preparar()
    model.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = escribir(model.LOG_DIR / "notas_20260911_101010.log", "ERROR\n")
    results.apuntar("notas", 1, log)
    abiertos.clear()
    reparacion(cfg, lambda dlg: botones(dlg)["Ver el log"].invoke())
    c("«Ver el log» abre el log que se conservó", abiertos, [log])

with sandbox():
    cfg, p = preparar()
    escribir(p.local_abs / "plan.md", "del remoto")
    escribir(p.local_abs / "plan.md.conflicto-dispositivo1", "de aquí")
    conflicts.actualizar_pareja(p)
    abiertas = []
    real_reparacion = tk_repair.open_dialog
    tk_repair.open_dialog = (lambda parent, config, lanzar, marcadas=None:
                             abiertas.append(config) or False)
    vistos = {}

    def mirar_conflicto(root):
        vistos["textos"] = textos(root)
        botones(root)["Reparación…"].invoke()

    try:
        ventana_principal(cfg, mirar_conflicto)
    finally:
        tk_repair.open_dialog = real_reparacion
    c("la pareja con conflictos sigue llevando su chip",
      "1 conflicto" in vistos["textos"], True)
    c("la cabecera lo cuenta como una cosa que revisar",
      "1 que revisar" in vistos["textos"], True)
    c("el recuadro ámbar de los conflictos ya no está",
      any("en conflicto en notas" in x for x in vistos["textos"]), False)
    c("y la línea lleva a «Reparación»", len(abiertas), 1)

with sandbox():
    # El fallo de siempre: «Sincronizar ahora» cerraba la ventana principal y al
    # terminar no había a dónde volver.
    cfg, p = preparar()
    lanzadas.clear()
    vistos = {}
    servicio_antes = prefs.read_prefs()

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
       vistos["durante"]["Ajustes…"], vistos["durante"]["Parejas…"]),
      ("disabled", "disabled", "disabled", "disabled"))
    c("la cabecera dice que está sincronizando", vistos["chip durante"], True)
    c("al cerrar la salida, la principal sigue ahí", vistos["viva después"], True)
    c("con los botones otra vez disponibles", vistos["despues"]["Sincronizar ahora"],
      "normal")
    c("y con los chips al día (el conflicto que dejó la pasada)",
      "1 conflicto" in vistos["textos"], True)
    c("sincronizar ya no es una elección que salga de la ventana", eleccion, None)
    # Lo que se guarda es la configuración del servicio, y una pasada suelta no
    # decide qué sincroniza el servicio al enchufar la próxima vez.
    c("una pasada manual no toca la configuración del servicio",
      prefs.read_prefs(), servicio_antes)

# El engranaje abre «Ajustes», y «Reparación» es su primera entrada. Se prueban
# las dos mitades —que el botón abre la pantalla, y que la entrada lleva a
# «Reparación»— porque el cableado entre ellas es lo único que ha cambiado.
with sandbox():
    cfg, _p = preparar()
    lanzadas.clear()
    visto: dict = {}
    abiertas = []

    def dentro_de_ajustes(dlg) -> None:
        botones_ajustes = botones(dlg)
        visto["entradas"] = sorted(botones_ajustes)
        botones_ajustes["Reparación…"].invoke()

    real_reparacion = tk_repair.open_dialog
    tk_repair.open_dialog = (lambda parent, config, lanzar, marcadas=None:
                             abiertas.append(config) or False)
    tk_doctor.mostrar = lambda dlg, parent=None: dentro_de_ajustes(dlg)
    try:
        ventana_principal(cfg, lambda root: botones(root)["Ajustes…"].invoke())
    finally:
        tk_repair.open_dialog = real_reparacion
    # La lista va entera y no «contiene»: «Ajustes» es donde aterriza todo lo que
    # no cabe en la principal, así que lo que hay que ver de un vistazo al añadir
    # una entrada es la lista completa de lo que esa pantalla ofrece.
    c("el engranaje abre «Ajustes» con sus entradas",
      visto.get("entradas"),
      ["Cerrar", "Emparejar un móvil…", "Nombre e icono de la unidad…",
       "Reparación…", "Versiones…"])
    c("y su primera entrada abre «Reparación», con «Ajustes» ya cerrada",
      len(abiertas), 1)

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
