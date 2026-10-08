#!/usr/bin/env python3
"""Las pantallas que esperan a la red se pintan antes de que conteste (#66).

Parejas se abre con la copia local del catálogo y lo lee del remoto en segundo
plano; «Dispositivos…», que no tiene copia, se abre en el acto y lee la flota
igual. Aquí va todo de verdad —el hilo, `catalog.load()`, `fleet.leer()`, el
sondeo desde el hilo de Tk— menos el remoto: `catalog.run()` se sustituye por
uno que no contesta hasta que el test lo suelta, o que contesta que no.

Lo que se comprueba es lo que ve la persona en cada momento: la copia local y
el indicador mientras se espera, el bloque del catálogo apagado hasta que llega
la respuesta de verdad, la pantalla repintada cuando llega, la copia y el aviso
cuando el remoto está caído, y que cerrar antes de tiempo no deja a nadie
pintando en widgets que ya no existen.

Las ventanas se crean ocultas; el bucle de eventos se mueve a mano
(`dar_vueltas`), que es lo que hace llegar el resultado.
"""

import subprocess
import sys
import threading
import time
from pathlib import Path

from _harness import Checks, sandbox

from common import catalog, config_file, fleet, model, store
from common.model import ConfigError

from ui import catalog_editor, segundo_plano

c = Checks("pantallas que esperan a la red (#66)")


# 1. el encargo, sin Tk
hecho = segundo_plano.en_el_acto(lambda: 41 + 1)
c("en el acto: vuelve ya terminado, con su resultado",
  (hecho.hecho, hecho.resultado, hecho.error), (True, 42, None))


def revienta():
    """Una función que lanza."""
    raise ConfigError("no hay remoto")


roto = segundo_plano.en_el_acto(revienta)
c("lo que lanza la función se apunta, no se escapa",
  (roto.hecho, type(roto.error).__name__, str(roto.error)),
  (True, "ConfigError", "no hay remoto"))

soltar = threading.Event()
lento = segundo_plano.lanzar(lambda: soltar.wait(5) and "listo")
c("lanzar vuelve en el acto, sin esperar al trabajo", lento.hecho, False)
soltar.set()
fin = time.monotonic() + 5
while not lento.hecho and time.monotonic() < fin:
    time.sleep(0.01)
c("y el resultado llega cuando el hilo acaba", (lento.hecho, lento.resultado),
  (True, "listo"))
c("el hilo no se queda con la función de quien encargó", lento._funcion, None)

# Sin repetir: una lectura viva se reutiliza, una acabada o distinta no.
soltar = threading.Event()
lanzadas: list = []


def trabajo():
    """Un trabajo que espera, y apunta cada vez que arranca."""
    lanzadas.append(1)
    soltar.wait(5)
    return "leído"


primero = segundo_plano.lanzar_sin_repetir("prueba", {"remote": "nas"}, trabajo)
segundo = segundo_plano.lanzar_sin_repetir("prueba", {"remote": "nas"}, trabajo)
c("sin repetir: con el hilo vivo, la misma lectura es el mismo encargo",
  (segundo is primero, len(lanzadas)), (True, 1))
otra_clave = segundo_plano.lanzar_sin_repetir("otra", {"remote": "nas"}, trabajo)
c("  otra clave es otra lectura", otra_clave is primero, False)
distinta = segundo_plano.lanzar_sin_repetir("prueba", {"remote": "otro"}, trabajo)
c("  y con otra firma el vivo no sirve: se lanza uno nuevo",
  (distinta is primero, len(lanzadas)), (False, 3))
tras = segundo_plano.lanzar_sin_repetir("prueba", {"remote": "otro"}, trabajo)
c("  que pasa a ser el que se reutiliza", tras is distinta, True)
soltar.set()
fin = time.monotonic() + 5
while not (primero.hecho and distinta.hecho and otra_clave.hecho) \
        and time.monotonic() < fin:
    time.sleep(0.01)
nuevo = segundo_plano.lanzar_sin_repetir("prueba", {"remote": "otro"}, trabajo)
c("  acabado el hilo, la siguiente lectura sí lanza otro",
  (nuevo is distinta, len(lanzadas)), (False, 4))

# Un hilo que lleva demasiado vivo se da por perdido: no se espera a uno colgado.
soltar = threading.Event()
colgado = segundo_plano.lanzar_sin_repetir("colgada", {}, trabajo)
vida_real = segundo_plano.VIDA_MAXIMA
segundo_plano.VIDA_MAXIMA = 0.0
try:
    relevo = segundo_plano.lanzar_sin_repetir("colgada", {}, trabajo)
finally:
    segundo_plano.VIDA_MAXIMA = vida_real
c("  y uno que lleva más de VIDA_MAXIMA vivo no se espera: se lanza otro",
  relevo is colgado, False)
soltar.set()

# Olvidar las lecturas vivas hace que la siguiente pase por `lanzar()`.
soltar = threading.Event()
viva = segundo_plano.lanzar_sin_repetir("olvidada", {}, trabajo)
segundo_plano.olvidar_lecturas()
c("  y tras olvidar_lecturas() tampoco se reutiliza el vivo",
  segundo_plano.lanzar_sin_repetir("olvidada", {}, trabajo) is viva, False)
soltar.set()


# 2. con Tk
try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from ui import tk as uitk  # noqa: E402
from ui import tk_fleet, tk_pairs  # noqa: E402

# Una excepción dentro de un callback de Tk no revienta el test: Tkinter la
# imprime y sigue. Aquí se apunta, porque pintar en una pantalla cerrada es
# justo eso.
errores: list[str] = []
raiz.report_callback_exception = (
    lambda tipo, valor, _tb: errores.append(f"{tipo.__name__}: {valor}"))
messagebox.showerror = lambda titulo, texto=None, **k: errores.append(str(texto))
messagebox.showinfo = lambda *a, **k: None
messagebox.askokcancel = lambda *a, **k: True

for modulo in (tk_pairs, tk_fleet):
    modulo.mostrar = lambda dlg, parent=None: dlg.wait_window()


def working_en_el_acto(parent, title, funcion, mensaje="", **_k):
    """Sustituye a `working()`: hace el trabajo en el sitio, sin ventanita."""
    try:
        return True, funcion()
    except Exception as e:                               # noqa: BLE001 — como working()
        return False, e


tk_pairs.working = working_en_el_acto
tk_fleet.working = working_en_el_acto


def dar_vueltas(condicion, limite=5.0) -> bool:
    """Mueve el bucle de eventos hasta que se cumpla la condición o pase el límite."""
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        raiz.update()
        if condicion():
            return True
        time.sleep(0.02)
    return False


def pendientes() -> tuple:
    """Los `after` que Tk tiene pendientes."""
    return raiz.tk.splitlist(raiz.tk.call("after", "info"))


# El sondeo, solo: en el acto si ya terminó, por `after` si no, y nada si la
# ventana se cierra antes.
top = tk.Toplevel(raiz)
top.withdraw()
sondeo = uitk.Sondeo(top)
llegados: list = []
ya = segundo_plano.en_el_acto(lambda: "ya")
sondeo.esperar(ya, llegados.append)
c("un encargo ya terminado se recoge en el acto", (llegados, sondeo.esperando),
  ([ya], False))

soltar = threading.Event()
luego = segundo_plano.lanzar(lambda: soltar.wait(5))
sondeo.esperar(luego, llegados.append)
c("uno pendiente se queda esperando", (sondeo.esperando, len(llegados)), (True, 1))
soltar.set()
c("y se recoge, desde el hilo de Tk, cuando termina",
  dar_vueltas(lambda: len(llegados) == 2), True)

soltar = threading.Event()
tarde = segundo_plano.lanzar(lambda: soltar.wait(5))
sondeo.esperar(tarde, llegados.append)
espera = sondeo._id
top.destroy()
c("cerrar la ventana cancela la espera", sondeo.esperando, False)
c("y no deja su `after` pendiente", espera in pendientes(), False)
soltar.set()
dar_vueltas(lambda: tarde.hecho)
dar_vueltas(lambda: False, 0.3)
c("lo que llega después no se recoge", len(llegados), 2)


# 3. la pantalla de parejas
BASE = {"defaults": {"remote": "nas"},
        "pair": [{"name": "notas", "local": "sync-data/notas",
                  "remote_path": "/R/notas", "mode": "bisync"},
                 {"name": "subida", "local": "sync-data/subida",
                  "remote_path": "/R/subida", "mode": "up"}]}
# La copia local es la de hace unos días; el remoto ya tiene una pareja más.
CAT_LOCAL = {"defaults": {"remote": "nas"},
             "pair": [dict(p) for p in BASE["pair"]]}
CAT_REMOTO = {"defaults": {"remote": "nas"},
              "pair": [*(dict(p) for p in BASE["pair"]),
                       {"name": "fotos", "local": "sync-data/fotos",
                        "remote_path": "/R/fotos", "mode": "up"}]}
CUANDO = "2026-09-30 08:00:00"
ENDPOINT = "nas:/prdrive-catalog/remote.toml"
BOTONES_CATALOGO = ("Nueva pareja…", "Borrar del catálogo…", "Guardar en el catálogo…",
                    "Ajustes del catálogo…")


class RemotoLento:
    """Un `catalog.run()` que no contesta hasta que se le suelta.

    Args:
        texto: Lo que contesta un `cat` cuando va bien.
        rc: Su código de salida; distinto de 0 es un remoto caído.
        stderr: Lo que dice rclone cuando falla.
    """

    def __init__(self, texto: str = "", rc: int = 0, stderr: str = "") -> None:
        """Prepara el remoto, todavía sin soltar."""
        self.texto, self.rc, self.stderr = texto, rc, stderr
        self.soltar = threading.Event()
        self.pedidos: list[list[str]] = []

    def __call__(self, args):
        """Apunta la orden, espera a que lo suelten y contesta."""
        self.pedidos.append(list(args))
        self.soltar.wait(10)
        return subprocess.CompletedProcess(args, self.rc,
                                           stdout=self.texto if self.rc == 0 else "",
                                           stderr=self.stderr)


def nadie(args):
    """El `catalog.run()` de fondo: ningún test habla con un remoto que no ha puesto."""
    raise AssertionError(f"nadie debería hablar con el remoto: {args}")


catalog.run = nadie


def preparar():
    """Escribe el config de prueba y lo devuelve ya parseado."""
    model.CONFIG_FILE.write_text(config_file.dumps(BASE), encoding="utf-8")
    return model.parse_config(BASE)


def dejar_copia(datos: dict) -> None:
    """Deja en `state/` una copia local del catálogo, de `CUANDO`."""
    catalog.cache_toml().parent.mkdir(parents=True, exist_ok=True)
    catalog.cache_toml().write_text(config_file.dumps(datos), encoding="utf-8")
    store.write_json(catalog.cache_meta(), {"pulled_at": CUANDO, "endpoint": ENDPOINT})


def buscar(ventana, clase, texto=None):
    """El primer widget de esa clase (y con ese texto, si se dice)."""
    pila = [ventana]
    while pila:
        w = pila.pop()
        pila += list(w.winfo_children())
        if isinstance(w, clase) and (texto is None or w.cget("text") == texto):
            return w
    return None


def foto(dlg) -> dict:
    """Lo que enseña la pantalla ahora: filas, botones, textos a la vista e indicador."""
    pila, filas, seleccion, botones, textos = [dlg], [], (), {}, []
    while pila:
        w = pila.pop()
        pila += list(w.winfo_children())
        if isinstance(w, ttk.Treeview):
            filas, seleccion = list(w.get_children()), tuple(w.selection())
        elif isinstance(w, ttk.Button):
            botones[str(w.cget("text"))] = str(w.cget("state"))
        elif isinstance(w, ttk.Label) and w.winfo_manager():
            textos.append(str(w.cget("text")))
    lista = getattr(dlg, "lista", None) or getattr(dlg, "tabla", None)
    if lista is not None:                       # parejas y flota no son una Treeview
        filas = list(lista.filas)
        seleccion = (lista.elegida,) if lista.elegida is not None else ()
    ind = dlg.indicador
    return {"filas": sorted(filas), "seleccion": seleccion, "botones": botones,
            "textos": textos, "esperando": ind.esperando,
            "linea": str(ind.texto.cget("text")) if ind.marco.grid_info() else "",
            "tono": str(ind.texto.cget("style"))}


explorables: list = []


def modificar(dlg, pareja: str) -> None:
    """Elige una pareja y apunta si su editor deja recorrer el remoto."""
    dlg.lista.elegir(pareja)
    explorables.append(dlg.editor.explorable)


# Remoto lento con copia local: se pinta la copia antes de que conteste.
with sandbox():
    cfg = preparar()
    dejar_copia(CAT_LOCAL)
    remoto = RemotoLento(config_file.dumps(CAT_REMOTO))
    catalog.run = remoto
    vista: dict = {}

    def mirar(self, *_a, **_k):
        """Mira la pantalla con el remoto callado, lo suelta y la vuelve a mirar."""
        vista["antes"] = foto(self)
        modificar(self, "notas")
        remoto.soltar.set()
        vista["llego"] = dar_vueltas(lambda: not self.sondeo.esperando)
        vista["despues"] = foto(self)
        modificar(self, "notas")

    tk.Toplevel.wait_window = mirar
    tk_pairs.open_dialog(raiz, cfg)
    catalog.run = nadie
    antes, despues = vista["antes"], vista["despues"]

    c("lento: la pantalla se pinta con la copia local antes de que conteste",
      antes["filas"], ["notas", "subida"])
    c("  el chip dice que es la copia, y de cuándo",
      f"copia local · {CUANDO}" in antes["textos"], True)
    c("  el indicador va, y la línea dice que se está leyendo",
      (antes["esperando"], f"copia local del {CUANDO}" in antes["linea"]), (True, True))
    c("  el bloque del catálogo, apagado mientras",
      [antes["botones"][b] for b in BOTONES_CATALOGO], ["disabled"] * 4)
    c("  y «Releer», también", antes["botones"]["Releer"], "disabled")
    c("  lo de este dispositivo sigue disponible", antes["botones"]["Guardar aquí…"],
      "normal")
    c("  «Examinar…» del remoto no se ofrece mientras", explorables[0], False)

    c("lento: al soltarlo, la respuesta llega", vista["llego"], True)
    c("  el remoto oyó un solo `cat` del catálogo", remoto.pedidos, [["cat", ENDPOINT]])
    c("  la pantalla se repinta con el del remoto",
      despues["filas"], ["fotos", "notas", "subida"])
    c("  el chip dice que está leído",
      any(t.startswith("catálogo leído · ") for t in despues["textos"]), True)
    c("  el indicador se va", (despues["esperando"], despues["linea"]), (False, ""))
    c("  el bloque del catálogo se enciende",
      [despues["botones"][b] for b in BOTONES_CATALOGO + ("Releer",)], ["normal"] * 5)
    c("  la fila elegida sigue elegida", despues["seleccion"], ("notas",))
    c("  «Examinar…» del remoto ya se ofrece", explorables[1], True)
    c("  y la copia local es ya la del remoto",
      catalog.cache_toml().read_text(encoding="utf-8"), config_file.dumps(CAT_REMOTO))
    c("  nada ha reventado por el camino", errores, [])
    explorables.clear()

# Remoto caído: la pantalla se queda con la copia y lo dice.
with sandbox():
    cfg = preparar()
    dejar_copia(CAT_LOCAL)
    remoto = RemotoLento(rc=1, stderr="Failed to cat: connection refused")
    catalog.run = remoto
    vista = {}

    def mirar_caido(self, *_a, **_k):
        """Suelta un remoto que contesta que no y mira la pantalla."""
        remoto.soltar.set()
        vista["llego"] = dar_vueltas(lambda: not self.sondeo.esperando)
        vista["foto"] = foto(self)
        modificar(self, "notas")

    tk.Toplevel.wait_window = mirar_caido
    tk_pairs.open_dialog(raiz, cfg)
    catalog.run = nadie
    caido = vista["foto"]
    c("caído: la espera termina", vista["llego"], True)
    c("  la pantalla se queda con la copia local", caido["filas"], ["notas", "subida"])
    c("  el chip sigue diciendo que es la copia",
      f"copia local · {CUANDO}" in caido["textos"], True)
    c("  y la línea dice por qué, en ámbar, con lo que dijo rclone",
      ("Sin conexión con el catálogo" in caido["linea"],
       "connection refused" in caido["linea"], caido["tono"]),
      (True, True, "Aviso.TLabel"))
    c("  sin indicador: ya no se espera nada", caido["esperando"], False)
    c("  el catálogo no se puede editar desde la copia",
      [caido["botones"][b] for b in BOTONES_CATALOGO], ["disabled"] * 4)
    c("  pero se puede volver a intentar", caido["botones"]["Releer"], "normal")
    c("  ni recorrer el remoto", explorables, [False])
    c("  y la copia local no se ha tocado",
      catalog.cache_toml().read_text(encoding="utf-8"), config_file.dumps(CAT_LOCAL))
    explorables.clear()

# Sin copia local (un dispositivo recién hecho): lo de este dispositivo y el aviso.
with sandbox():
    cfg = preparar()
    remoto = RemotoLento(config_file.dumps(CAT_REMOTO))
    catalog.run = remoto
    vista = {}

    def mirar_sin_copia(self, *_a, **_k):
        """Mira la pantalla sin copia, suelta el remoto y la vuelve a mirar."""
        vista["antes"] = foto(self)
        remoto.soltar.set()
        dar_vueltas(lambda: not self.sondeo.esperando)
        vista["despues"] = foto(self)

    tk.Toplevel.wait_window = mirar_sin_copia
    tk_pairs.open_dialog(raiz, cfg)
    catalog.run = nadie
    c("sin copia: se ven las parejas de este dispositivo",
      vista["antes"]["filas"], ["notas", "subida"])
    c("  el chip dice que se está leyendo, y la línea por qué solo esas",
      ("leyendo el catálogo…" in vista["antes"]["textos"], vista["antes"]["linea"]),
      (True, catalog_editor.LEYENDO_SIN_COPIA))
    c("  y al llegar, el catálogo entero", vista["despues"]["filas"],
      ["fotos", "notas", "subida"])

# «Releer» y subir un cambio también leen en segundo plano.
with sandbox():
    cfg = preparar()
    dejar_copia(CAT_LOCAL)
    remoto = RemotoLento(config_file.dumps(CAT_REMOTO))
    remoto.soltar.set()
    catalog.run = remoto
    CON_MUSICA = {**CAT_REMOTO, "pair": [*CAT_REMOTO["pair"],
                                         {"name": "musica", "local": "sync-data/musica",
                                          "remote_path": "/R/musica", "mode": "down"}]}
    subidos: list = []

    def falso_push(new_raw, base_text, raw_local=None):
        """Sube de mentira y deja la copia local, como el de verdad."""
        subidos.append(dict(new_raw))
        texto = config_file.dumps(new_raw)
        catalog._write_cache(catalog.Catalog(raw=dict(new_raw), text=texto,
                                             source="remote", stamp=store.stamp(),
                                             endpoint=ENDPOINT))
        return ["Catálogo actualizado (de mentira)"]

    real_push = catalog.push
    catalog.push = falso_push
    tk_pairs.confirmar_plan = lambda *a, **k: True
    vista = {}

    def releer_y_subir(self, *_a, **_k):
        """Relee con el remoto callado, y luego sube una pareja nueva."""
        dar_vueltas(lambda: not self.sondeo.esperando)
        remoto.soltar = threading.Event()
        buscar(self, ttk.Button, "Releer").invoke()
        vista["releyendo"] = foto(self)
        remoto.soltar.set()
        dar_vueltas(lambda: not self.sondeo.esperando)
        vista["releido"] = foto(self)

        remoto.texto = config_file.dumps(CON_MUSICA)
        remoto.soltar = threading.Event()
        tk_pairs.formulario = lambda parent, raw, original, actual, **k: {
            "name": "musica", "local": "sync-data/musica", "remote_path": "/R/musica",
            "mode": "down", "include": [], "exclude": []}
        buscar(self, ttk.Button, "Nueva pareja…").invoke()
        vista["subiendo"] = foto(self)
        remoto.soltar.set()
        dar_vueltas(lambda: not self.sondeo.esperando)
        vista["subido"] = foto(self)

    tk.Toplevel.wait_window = releer_y_subir
    try:
        tk_pairs.open_dialog(raiz, cfg)
    finally:
        catalog.push, catalog.run = real_push, nadie
    rel, sub = vista["releyendo"], vista["subiendo"]
    c("releer: el indicador vuelve y el catálogo se apaga mientras",
      (rel["esperando"], rel["linea"], [rel["botones"][b] for b in BOTONES_CATALOGO]),
      (True, catalog_editor.RELEYENDO, ["disabled"] * 4))
    c("  y al llegar lo dice en el pie", "Catálogo releído." in vista["releido"]["textos"],
      True)
    c("subir: va por working() y se sube una vez", len(subidos), 1)
    c("  mientras se relee, se enseña lo recién subido (la copia local)",
      ("musica" in sub["filas"], any(t.startswith("copia local · ")
                                     for t in sub["textos"])), (True, True))
    c("  con el catálogo apagado hasta que contesta el remoto",
      [sub["botones"][b] for b in BOTONES_CATALOGO], ["disabled"] * 4)
    c("  y lo hecho, en el pie", "Catálogo actualizado (de mentira)" in sub["textos"],
      True)
    c("  al llegar, otra vez editable y la nota sigue",
      ([vista["subido"]["botones"][b] for b in BOTONES_CATALOGO],
       "Catálogo actualizado (de mentira)" in vista["subido"]["textos"]),
      (["normal"] * 4, True))
    c("  nada ha reventado por el camino", errores, [])

# Cerrar antes de que conteste: el hilo acaba, y nadie pinta en widgets muertos.
with sandbox():
    cfg = preparar()
    dejar_copia(CAT_LOCAL)
    remoto = RemotoLento(config_file.dumps(CAT_REMOTO))
    catalog.run = remoto
    vista = {}

    def cerrar_antes(self, *_a, **_k):
        """Cierra la pantalla con el remoto callado, y luego lo suelta."""
        vista["espera"] = self.sondeo._id
        self.destroy()
        vista["cancelada"] = not self.sondeo.esperando
        remoto.soltar.set()
        vista["acabo"] = dar_vueltas(
            lambda: catalog.cache_toml().read_text(encoding="utf-8")
            == config_file.dumps(CAT_REMOTO))
        dar_vueltas(lambda: False, 0.4)

    tk.Toplevel.wait_window = cerrar_antes
    tk_pairs.open_dialog(raiz, cfg)
    catalog.run = nadie
    c("cerrar antes: la espera se cancela con la pantalla", vista["cancelada"], True)
    c("  sin dejar su `after` pendiente", vista["espera"] in pendientes(), False)
    c("  el hilo termina su lectura (y deja la copia al día)", vista["acabo"], True)
    c("  y nadie ha pintado en la pantalla cerrada", errores, [])


# Cerrar y volver a abrir con el hilo aún vivo: la segunda pantalla espera al
# mismo hilo en vez de lanzar otro (dos `pull()` se pisarían la copia local).
with sandbox():
    cfg = preparar()
    dejar_copia(CAT_LOCAL)
    remoto = RemotoLento(config_file.dumps(CAT_REMOTO))
    catalog.run = remoto
    vista = {}

    def cerrar_y_reabrir(self, *_a, **_k):
        """Cierra la pantalla con el remoto callado: el hilo sigue vivo."""
        self.destroy()

    def reabierta(self, *_a, **_k):
        """Mira la segunda pantalla con el mismo remoto callado, y lo suelta."""
        vista["antes"] = foto(self)
        vista["pedidos_antes"] = len(remoto.pedidos)
        remoto.soltar.set()
        vista["llego"] = dar_vueltas(lambda: not self.sondeo.esperando)
        vista["despues"] = foto(self)

    tk.Toplevel.wait_window = cerrar_y_reabrir
    tk_pairs.open_dialog(raiz, cfg)
    leido_uno = dar_vueltas(lambda: len(remoto.pedidos) == 1)
    tk.Toplevel.wait_window = reabierta
    tk_pairs.open_dialog(raiz, cfg)
    catalog.run = nadie
    c("reabrir con el hilo vivo: el remoto oyó un solo `cat`",
      (leido_uno, vista["pedidos_antes"], remoto.pedidos), (True, 1, [["cat", ENDPOINT]]))
    c("  la segunda pantalla enseña que espera",
      (vista["antes"]["esperando"], vista["antes"]["botones"]["Releer"]),
      (True, "disabled"))
    c("  y recoge lo que lee el hilo de la primera",
      (vista["llego"], vista["despues"]["filas"]),
      (True, ["fotos", "notas", "subida"]))
    c("  nada ha reventado por el camino", errores, [])

# «Releer» con una lectura en marcha (forzando el botón, que la pantalla apaga):
# no lanza otra, y lo que llega lleva la nota de la última petición.
with sandbox():
    cfg = preparar()
    dejar_copia(CAT_LOCAL)
    remoto = RemotoLento(config_file.dumps(CAT_REMOTO))
    catalog.run = remoto
    vista = {}

    def releer_forzado(self, *_a, **_k):
        """Pulsa «Releer» con la primera lectura todavía en el aire."""
        boton = buscar(self, ttk.Button, "Releer")
        boton.configure(state="normal")
        boton.invoke()
        vista["pedidos_antes"] = len(remoto.pedidos)
        remoto.soltar.set()
        vista["llego"] = dar_vueltas(lambda: not self.sondeo.esperando)
        vista["despues"] = foto(self)

    tk.Toplevel.wait_window = releer_forzado
    tk_pairs.open_dialog(raiz, cfg)
    catalog.run = nadie
    c("releer con una lectura viva: no hay un segundo `cat`",
      (vista["llego"], len(remoto.pedidos)), (True, 1))
    c("  y la nota de esa petición sale al llegar",
      "Catálogo releído." in vista["despues"]["textos"], True)
    c("  nada ha reventado por el camino", errores, [])

# Lo que llega puede ser más largo que lo que había: la ventana crece y se
# recoloca (como el asistente); si no ha crecido, se queda donde está.
LARGO = ("Failed to cat: couldn't connect SSH: dial tcp 192.168.100.200:22: "
         "i/o timeout " * 12)
colocadas: list = []
PANTALLA_REAL = uitk.pantalla_util
uitk.pantalla_util = lambda win: (3000, 3000)         # sitio de sobra para crecer
tk_pairs.centrar = lambda win, parent=None: colocadas.append((win, parent))
tk_fleet.centrar = tk_pairs.centrar


def enseñada(self) -> None:
    """Deja la pantalla puesta y visible, como la deja `mostrar()` antes de esperar.

    Con su padre también a la vista: la pantalla es `transient` y, en Windows,
    colgada de uno oculto no llega a verse aunque se le haga `deiconify()`
    (`tk.modal()`). Sin verse no crece (`winfo_ismapped()`), y el test medía
    eso en vez de lo que dice.
    """
    raiz.deiconify()
    self.visor.encajar(self)
    self.deiconify()
    self.update()


with sandbox():
    cfg = preparar()
    dejar_copia(CAT_LOCAL)
    remoto = RemotoLento(rc=1, stderr=LARGO)
    catalog.run = remoto
    vista = {}

    def crece_parejas(self, *_a, **_k):
        """Enseña la pantalla, y suelta un remoto caído con una explicación larga."""
        enseñada(self)
        vista["a_la_vista"] = bool(self.winfo_ismapped())
        vista["alto_antes"] = self.visor._medida()[1]
        remoto.soltar.set()
        dar_vueltas(lambda: not self.sondeo.esperando)
        vista["alto_despues"] = self.visor._medida()[1]
        vista["raiz"] = self

    tk.Toplevel.wait_window = crece_parejas
    tk_pairs.open_dialog(raiz, cfg)
    catalog.run = nadie
    c("parejas: una explicación larga hace crecer el recuadro",
      (vista["a_la_vista"], vista["alto_despues"] > vista["alto_antes"]), (True, True))
    c("  y la ventana se recoloca, sobre su padre, una sola vez",
      [(w is vista["raiz"], p is raiz) for w, p in colocadas], [(True, True)])
    colocadas.clear()

with sandbox():
    cfg = preparar()
    dejar_copia(CAT_LOCAL)
    # El mismo catálogo que la copia: la lista crece una línea por pareja, y
    # una pareja más sí haría crecer la ventana.
    remoto = RemotoLento(config_file.dumps(CAT_LOCAL))
    catalog.run = remoto

    def no_crece_parejas(self, *_a, **_k):
        """Enseña la pantalla y suelta un remoto que contesta sin nada que explicar."""
        enseñada(self)
        remoto.soltar.set()
        dar_vueltas(lambda: not self.sondeo.esperando)

    tk.Toplevel.wait_window = no_crece_parejas
    tk_pairs.open_dialog(raiz, cfg)
    catalog.run = nadie
    c("parejas: si no ha crecido, la ventana no se mueve", colocadas, [])

uitk.pantalla_util = PANTALLA_REAL
raiz.withdraw()


# 4. «Dispositivos…»
FLOTA = [fleet.Dispositivo(id="aaa", nombre="el azul", version="0.5.0",
                           plataformas=("linux-x64",), last_seen="2026-09-30 08:00:00",
                           last_result="ok"),
         fleet.Dispositivo(id="bbb", nombre="el del trabajo", version="0.5.0",
                           plataformas=("windows-x64",),
                           last_seen="2026-09-29 08:00:00", last_result="ok")]


class FlotaLenta(RemotoLento):
    """Un `catalog.run()` cuyo `copy` de `devices/` no llega hasta que se le suelta."""

    def __call__(self, args):
        """Espera, y deja las notas de `FLOTA` donde `fleet.leer()` las busca."""
        res = super().__call__(args)
        if self.rc == 0 and args[0] == "copy":
            for disp in FLOTA:
                (Path(args[2]) / f"{disp.id}{fleet.SUFIJO}").write_text(
                    fleet.dumps(disp), encoding="utf-8")
        return res


with sandbox():
    cfg = preparar()
    remoto = FlotaLenta()
    catalog.run = remoto
    vista = {}

    def mirar_flota(self, *_a, **_k):
        """Mira la flota sin notas, la suelta, relee y elige mientras."""
        vista["antes"] = foto(self)
        remoto.soltar.set()
        vista["llego"] = dar_vueltas(lambda: not self.sondeo.esperando)
        vista["despues"] = foto(self)
        remoto.soltar = threading.Event()
        buscar(self, ttk.Button, "Releer").invoke()
        self.tabla.elegir("bbb")
        self.update()
        vista["quitar_releyendo"] = str(buscar(self, ttk.Button,
                                               "Quitar de la lista…").cget("state"))
        remoto.soltar.set()
        dar_vueltas(lambda: not self.sondeo.esperando)
        self.tabla.elegir("bbb")
        self.update()
        vista["quitar_leida"] = str(buscar(self, ttk.Button,
                                           "Quitar de la lista…").cget("state"))

    tk.Toplevel.wait_window = mirar_flota
    tk_fleet.open_dialog(raiz, cfg, dict(BASE))
    catalog.run = nadie
    antes, despues = vista["antes"], vista["despues"]
    c("flota lenta: la ventana se abre antes de que lleguen las notas", antes["filas"], [])
    c("  con el indicador y su frase",
      (antes["esperando"], antes["linea"]), (True, tk_fleet.LEYENDO))
    c("  el chip dice que está leyendo", "leyendo la flota…" in antes["textos"], True)
    c("  y no dice que no haya nadie: todavía no se sabe",
      tk_fleet.SIN_NOTA in antes["textos"], False)
    c("  sus dos botones de remoto, apagados",
      (antes["botones"]["Quitar de la lista…"], antes["botones"]["Releer"]),
      ("disabled", "disabled"))
    c("flota lenta: al soltarla, las notas llegan", vista["llego"], True)
    c("  la tabla se llena", despues["filas"], ["aaa", "bbb"])
    c("  el chip las cuenta y el indicador se va",
      ("2 dispositivo(s)" in despues["textos"], despues["esperando"], despues["linea"]),
      (True, False, ""))
    c("  «Releer» vuelve", despues["botones"]["Releer"], "normal")
    c("  mientras se relee, quitar una nota no se enciende al elegirla",
      vista["quitar_releyendo"], "disabled")
    c("  y leída, sí", vista["quitar_leida"], "normal")
    c("  nada ha reventado por el camino", errores, [])

with sandbox():
    cfg = preparar()
    remoto = FlotaLenta(rc=1, stderr="Failed to copy: connection refused")
    remoto.soltar.set()
    catalog.run = remoto
    vista = {}

    def mirar_flota_caida(self, *_a, **_k):
        """Deja contestar a un remoto caído y mira la ventana."""
        dar_vueltas(lambda: not self.sondeo.esperando)
        vista["foto"] = foto(self)

    tk.Toplevel.wait_window = mirar_flota_caida
    tk_fleet.open_dialog(raiz, cfg, dict(BASE))
    catalog.run = nadie
    caida = vista["foto"]
    c("flota caída: lo dice el chip y el pie",
      ("sin conexión" in caida["textos"],
       any("No se ha podido leer la flota" in t and "connection refused" in t
           for t in caida["textos"])), (True, True))
    c("  sin indicador, y se puede volver a intentar",
      (caida["esperando"], caida["botones"]["Releer"]), (False, "normal"))

with sandbox():
    cfg = preparar()
    remoto = FlotaLenta()
    catalog.run = remoto
    vista = {}

    def cerrar_y_reabrir_flota(self, *_a, **_k):
        """Cierra la flota con el remoto callado: el hilo sigue vivo."""
        self.destroy()

    def reabierta_flota(self, *_a, **_k):
        """Mira la segunda ventana, suelta el remoto y recoge la flota."""
        vista["pedidos_antes"] = len(remoto.pedidos)
        remoto.soltar.set()
        vista["llego"] = dar_vueltas(lambda: not self.sondeo.esperando)
        vista["filas"] = foto(self)["filas"]

    tk.Toplevel.wait_window = cerrar_y_reabrir_flota
    tk_fleet.open_dialog(raiz, cfg, dict(BASE))
    dar_vueltas(lambda: len(remoto.pedidos) == 1)
    tk.Toplevel.wait_window = reabierta_flota
    tk_fleet.open_dialog(raiz, cfg, dict(BASE))
    catalog.run = nadie
    c("flota reabierta con el hilo vivo: una sola lectura del remoto",
      (vista["pedidos_antes"], len([p for p in remoto.pedidos if p[0] == "copy"])),
      (1, 1))
    c("  y la segunda ventana recoge lo que lee el hilo de la primera",
      (vista["llego"], vista["filas"]), (True, ["aaa", "bbb"]))
    c("  sin que nada reviente", errores, [])

with sandbox():
    cfg = preparar()
    remoto = FlotaLenta()
    catalog.run = remoto
    vista = {}

    def cerrar_flota(self, *_a, **_k):
        """Cierra la flota antes de que lleguen las notas."""
        vista["espera"] = self.sondeo._id
        self.destroy()
        remoto.soltar.set()
        dar_vueltas(lambda: False, 0.4)

    tk.Toplevel.wait_window = cerrar_flota
    tk_fleet.open_dialog(raiz, cfg, dict(BASE))
    catalog.run = nadie
    c("flota cerrada antes: sin `after` pendiente ni nadie pintando",
      (vista["espera"] in pendientes(), errores), (False, []))

# Lo mismo en «Dispositivos…».
uitk.pantalla_util = lambda win: (3000, 3000)
tk_fleet.centrar = tk_pairs.centrar

with sandbox():
    cfg = preparar()
    remoto = FlotaLenta(rc=1, stderr=LARGO)
    catalog.run = remoto
    vista = {}

    def crece_flota(self, *_a, **_k):
        """Enseña la flota, y suelta un remoto caído con una explicación larga."""
        enseñada(self)
        vista["a_la_vista"] = bool(self.winfo_ismapped())
        vista["alto_antes"] = self.visor._medida()[1]
        remoto.soltar.set()
        dar_vueltas(lambda: not self.sondeo.esperando)
        vista["alto_despues"] = self.visor._medida()[1]
        vista["raiz"] = self

    tk.Toplevel.wait_window = crece_flota
    tk_fleet.open_dialog(raiz, cfg, dict(BASE))
    catalog.run = nadie
    c("flota: una explicación larga hace crecer el recuadro",
      (vista["a_la_vista"], vista["alto_despues"] > vista["alto_antes"]), (True, True))
    c("  y la ventana se recoloca, sobre su padre, una sola vez",
      [(w is vista["raiz"], p is raiz) for w, p in colocadas], [(True, True)])
    colocadas.clear()

with sandbox():
    cfg = preparar()
    remoto = FlotaLenta()
    catalog.run = remoto

    def no_crece_flota(self, *_a, **_k):
        """Enseña la flota, deja que lleguen las notas y las vuelve a leer."""
        enseñada(self)
        remoto.soltar.set()
        dar_vueltas(lambda: not self.sondeo.esperando)
        colocadas.clear()               # llegar la primera vez sí hizo sitio a la tabla
        remoto.soltar = threading.Event()
        buscar(self, ttk.Button, "Releer").invoke()
        remoto.soltar.set()
        dar_vueltas(lambda: not self.sondeo.esperando)

    tk.Toplevel.wait_window = no_crece_flota
    tk_fleet.open_dialog(raiz, cfg, dict(BASE))
    catalog.run = nadie
    c("flota: releer lo mismo no hace crecer nada, y la ventana no se mueve",
      colocadas, [])
c("  nada ha reventado por el camino", errores, [])
uitk.pantalla_util = PANTALLA_REAL
raiz.withdraw()

raiz.destroy()
sys.exit(c.report())
