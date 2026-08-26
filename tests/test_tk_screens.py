#!/usr/bin/env python3
"""
Las dos pantallas nuevas, conducidas sin nadie delante.

No se comprueba el aspecto: se comprueba el cableado. Que pulsar un botón acabe
llamando al editor que toca con lo que dice el formulario, que un cambio se
refleje donde debe, y que la pantalla de penwatch sepa pintar sus filas.

El catálogo se sustituye entero (`catalog.load` / `catalog.push`): aquí no se
toca la red, y así se puede comprobar lo que de verdad importa de esta pantalla,
que es que un botón del bloque «Catálogo» NO cambie el config de este pen y uno
del bloque «Este pen» NO cambie el catálogo.

Las ventanas se crean ocultas y no se entra nunca en el bucle de eventos.
"""

import sys

from _harness import Checks, sandbox

import tomllib

from common import catalog, config_file, model

c = Checks("pantallas Tk (cableado)")

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(0)

from ui import tk_pairs, tk_watch

# El de verdad: más abajo hay tramos que lo sustituyen por un formulario de
# mentira, y el último los necesita a los dos.
FORMULARIO = tk_pairs.formulario


def ocultar(modulo):
    """Los diálogos se crean pero no se enseñan: esto no es una demo.

    `modal()` ya los devuelve ocultos; quien los centra y los enseña es
    `mostrar()`, así que basta con quedarse solo con su espera."""
    modulo.mostrar = lambda dlg, parent=None: dlg.wait_window()


def pulsar(texto):
    """Un wait_window que, en vez de esperar, pulsa un botón y vuelve."""
    def _wait(self, *_a, **_k):
        pila = [self]
        while pila:
            w = pila.pop()
            pila += list(w.winfo_children())
            if isinstance(w, ttk.Button) and w.cget("text") == texto:
                w.invoke()
                return
    return _wait


def elegir_y_pulsar(texto, pareja=None):
    """Como pulsar(), pero seleccionando antes una fila de la lista."""
    def _wait(self, *_a, **_k):
        pila, arbol, boton = [self], None, None
        while pila:
            w = pila.pop()
            pila += list(w.winfo_children())
            if isinstance(w, ttk.Treeview):
                arbol = w
            elif isinstance(w, ttk.Button) and w.cget("text") == texto:
                boton = w
        if arbol is not None and arbol.get_children():
            hijos = arbol.get_children()
            arbol.selection_set(pareja if pareja in hijos else hijos[0])
        if boton is not None:
            boton.invoke()
    return _wait


ocultar(tk_pairs)
ocultar(tk_watch)
# Las consecuencias de un plan se enseñan en su propia ventana (`confirmar_plan`),
# no en un messagebox: aquí se responde que sí y ya está. Lo que se comprueba de
# esta pantalla es el cableado, no el diálogo.
tk_pairs.confirmar_plan = lambda *a, **k: True
messagebox.askokcancel = lambda *a, **k: True            # el resto de sí/no
messagebox.showinfo = lambda *a, **k: None
errores: list[str] = []
messagebox.showerror = lambda titulo, texto=None, **k: errores.append(str(texto))

BASE = {"defaults": {"remote": "synology"},
        "pair": [{"name": "notas", "local": "sync-data/notas",
                  "remote_path": "/R/notas", "mode": "bisync"},
                 {"name": "subida", "local": "sync-data/subida",
                  "remote_path": "/R/subida", "mode": "up"}]}

# El catálogo tiene las dos del pen más una que aquí no se usa.
CAT = {"defaults": {"remote": "synology"},
       "pair": [dict(BASE["pair"][0]), dict(BASE["pair"][1]),
                {"name": "fotos", "local": "sync-data/fotos",
                 "remote_path": "/R/fotos", "mode": "up"}]}

subidos: list[dict] = []


def falso_catalogo(raw=None):
    texto = config_file.dumps(CAT)
    return catalog.Catalog(raw=tomllib.loads(texto), text=texto,
                           source="remote", stamp="2026-01-01 00:00:00",
                           endpoint="synology:/PJ/Perepen-catalog/pairs.toml"), None


def falso_push(new_raw, base_text, raw_local=None):
    subidos.append(dict(new_raw))
    return ["Catálogo actualizado (de mentira)"]


catalog.load = falso_catalogo
catalog.push = falso_push
catalog.run = lambda args: (_ for _ in ()).throw(
    AssertionError("ningún test puede hablar con el NAS"))


def preparar():
    model.CONFIG_FILE.write_text(config_file.dumps(BASE), encoding="utf-8")
    return model.parse_config(BASE)


def dar_baseline(cfg, name):
    from common import bisync
    pareja = next(p for p in cfg.pairs if p.name == name)
    pareja.workdir.mkdir(parents=True, exist_ok=True)
    prefijo = bisync.expected_prefix(pareja)
    for sufijo in (bisync.PATH1_SUFFIX, bisync.PATH2_SUFFIX):
        (pareja.workdir / f"{prefijo}{sufijo}").write_text("x", encoding="utf-8")


# --- la lista une el catálogo y el pen ---------------------------------------
with sandbox():
    cfg = preparar()
    filas = {}

    def mirar(self, *_a, **_k):
        pila = [self]
        while pila:
            w = pila.pop()
            pila += list(w.winfo_children())
            if isinstance(w, ttk.Treeview):
                for iid in w.get_children():
                    filas[iid] = w.item(iid)["values"]
                return

    tk.Toplevel.wait_window = mirar
    tk_pairs.open_dialog(raiz, cfg)
    c("la lista trae las tres del catálogo", sorted(filas), ["fotos", "notas", "subida"])
    c("'fotos' sale como no usada aquí", filas["fotos"][0], "")
    c("y con origen 'sin usar'", filas["fotos"][5], "sin usar")
    c("'notas' sale marcada y viniendo del catálogo",
      (filas["notas"][0], filas["notas"][5]), ("✓", "catálogo"))

# --- 'Usar aquí' trae una pareja del catálogo a este pen ---------------------
with sandbox():
    cfg = preparar()
    tk.Toplevel.wait_window = elegir_y_pulsar("Usar aquí", "fotos")
    cambiado = tk_pairs.open_dialog(raiz, cfg)
    c("usar aquí informa de que hubo cambios", cambiado, True)
    c("la pareja del catálogo está en el config", model.load_config().names,
      ["notas", "subida", "fotos"])
    c("y no se ha tocado el catálogo", subidos, [])

# --- 'Modificar aquí' aparta el baseline, como manda el editor ---------------
with sandbox():
    cfg = preparar()
    dar_baseline(cfg, "notas")
    tk_pairs.formulario = lambda parent, raw, original, actual, **k: {
        **actual, "remote_path": "/R/otro", "include": [], "exclude": []}

    tk.Toplevel.wait_window = pulsar("Modificar aquí…")
    c("modificar sin seleccionar no cambia nada", tk_pairs.open_dialog(raiz, cfg), False)

    tk.Toplevel.wait_window = elegir_y_pulsar("Modificar aquí…", "notas")
    c("modificar el extremo informa del cambio", tk_pairs.open_dialog(raiz, cfg), True)
    c("el config apunta al destino nuevo",
      next(p.remote_path for p in model.load_config().pairs if p.name == "notas"),
      "/R/otro")
    c("y el baseline se ha apartado",
      any(p.name.startswith("notas.old-") for p in model.STATE_DIR.iterdir()), True)
    c("el catálogo sigue sin tocarse", subidos, [])

# --- 'Volver al catálogo' deshace la modificación local ----------------------
with sandbox():
    cfg = preparar()
    tk.Toplevel.wait_window = elegir_y_pulsar("Volver al catálogo", "notas")
    tk_pairs.open_dialog(raiz, cfg)   # ya coincide: no hay nada que deshacer
    c("volver cuando ya coincide no cambia nada",
      next(p.remote_path for p in model.load_config().pairs if p.name == "notas"),
      "/R/notas")

with sandbox():
    distinto = {**BASE, "pair": [{**BASE["pair"][0], "remote_path": "/R/mio"},
                                 dict(BASE["pair"][1])]}
    model.CONFIG_FILE.write_text(config_file.dumps(distinto), encoding="utf-8")
    cfg = model.parse_config(distinto)
    tk.Toplevel.wait_window = elegir_y_pulsar("Volver al catálogo", "notas")
    c("volver informa de que hubo cambios", tk_pairs.open_dialog(raiz, cfg), True)
    c("y la pareja vuelve a la del catálogo",
      next(p.remote_path for p in model.load_config().pairs if p.name == "notas"),
      "/R/notas")

# --- el bloque del catálogo escribe en el catálogo, no en el pen -------------
with sandbox():
    subidos.clear()
    cfg = preparar()
    tk_pairs.formulario = lambda parent, raw, original, actual, **k: {
        "name": "musica", "local": "sync-data/musica", "remote_path": "/R/musica",
        "mode": "down", "include": [], "exclude": []}
    tk.Toplevel.wait_window = pulsar("Nueva…")

    cambiado = tk_pairs.open_dialog(raiz, cfg)
    c("crear en el catálogo NO cambia el config de este pen", cambiado, False)
    c("este pen sigue con sus dos parejas", model.load_config().names,
      ["notas", "subida"])
    c("y la pareja nueva ha ido al catálogo",
      [p["name"] for p in subidos[-1]["pair"]], ["notas", "subida", "fotos", "musica"])

with sandbox():
    subidos.clear()
    cfg = preparar()
    tk.Toplevel.wait_window = elegir_y_pulsar("Borrar…", "fotos")
    tk_pairs.open_dialog(raiz, cfg)
    c("borrar del catálogo quita solo del catálogo",
      [p["name"] for p in subidos[-1]["pair"]], ["notas", "subida"])
    c("este pen no se entera", model.load_config().names, ["notas", "subida"])

# --- sin red: el bloque del catálogo se deshabilita --------------------------
with sandbox():
    cfg = preparar()
    texto = config_file.dumps(CAT)
    catalog.load = lambda raw=None: (
        catalog.Catalog(raw=tomllib.loads(texto), text=texto, source="cache",
                        stamp="2026-01-01 00:00:00", endpoint="synology:/x/pairs.toml"),
        "Sin conexión con el catálogo.")

    estados = {}

    def mirar_botones(self, *_a, **_k):
        pila = [self]
        while pila:
            w = pila.pop()
            pila += list(w.winfo_children())
            if isinstance(w, ttk.Button):
                estados[w.cget("text")] = str(w.cget("state"))

    tk.Toplevel.wait_window = mirar_botones
    tk_pairs.open_dialog(raiz, cfg)
    c("desde la copia, el catálogo no se puede tocar",
      sorted(t for t, e in estados.items() if e == "disabled"),
      ["Ajustes del catálogo…", "Borrar…", "Editar…", "Nueva…"])
    c("pero lo de este pen sigue disponible", estados["Usar aquí"], "normal")

    catalog.load = falso_catalogo

# --- la pantalla de penwatch pinta su estado ---------------------------------
with sandbox():
    cfg = preparar()
    tk.Toplevel.wait_window = pulsar("Cerrar")
    try:
        tk_watch.open_dialog(raiz, cfg)
        c("la pantalla de penwatch se abre y se cierra", True, True)
    except Exception as e:
        c("la pantalla de penwatch se abre y se cierra", f"{type(e).__name__}: {e}", True)

    tk.Toplevel.wait_window = pulsar("Detectar el pen")
    try:
        tk_watch.open_dialog(raiz, cfg)
        c("'Detectar el pen' no revienta", True, True)
    except Exception as e:
        c("'Detectar el pen' no revienta", f"{type(e).__name__}: {e}", True)



# --- el editor de flags: se escribe TOML y sale lo que recibirá rclone -------
#
# Lo que se comprueba es la parte peligrosa: que lo que no se puede escribir en
# el TOML no salga del diálogo. Si saliera, el fallo aparecería al guardar, con
# el formulario ya cerrado y lo escrito perdido.

def flags_escritos(texto, extra="", boton="Aceptar"):
    """Escribe en los dos cuadros del diálogo de flags y pulsa un botón.

    Devuelve además lo que quede escrito en el diálogo, porque ahí es donde se
    queja ahora de lo que no vale."""
    filas, quejas = [], []

    def _wait(self, *_a, **_k):
        cajas, botones, tabla = {}, {}, None
        pila = [self]
        while pila:
            w = pila.pop()
            pila += list(w.winfo_children())
            if isinstance(w, tk.Text):
                cajas[int(w.grid_info()["row"])] = w
            elif isinstance(w, ttk.Button):
                botones[w.cget("text")] = w
            elif isinstance(w, ttk.Treeview):
                tabla = w
        caja, caja_extra = [cajas[k] for k in sorted(cajas)]
        caja.delete("1.0", "end")
        caja.insert("1.0", texto)
        caja_extra.delete("1.0", "end")
        caja_extra.insert("1.0", extra)
        botones["Ver el efecto"].invoke()
        if tabla is not None:
            filas[:] = [tabla.item(i)["values"] for i in tabla.get_children()]
        pila = [self]
        while pila:
            w = pila.pop()
            pila += list(w.winfo_children())
            if isinstance(w, ttk.Label):
                quejas.append(str(w.cget("text")))
        botones[boton].invoke()

    tk.Toplevel.wait_window = _wait
    datos = tk_pairs.flags_form(raiz, "Flags", "de prueba", {"transfers": 4}, [],
                                mode_name="bisync", defaults_flags=None)
    return datos, filas, quejas


datos, filas, _ = flags_escritos('transfers = 8\nchecksum = true', "--bwlimit\n8M")
c("lo escrito vuelve ya parseado", datos["flags"], {"transfers": 8, "checksum": True})
c("y los extra tal cual", datos["extra_flags"], ["--bwlimit", "8M"])
c("la tabla enseña de dónde sale cada flag",
  ["--max-delete 25", "modo bisync"] in [list(f) for f in filas], True)
c("y los argumentos extra también salen",
  ["--bwlimit", "extra"] in [list(f) for f in filas], True)

datos, _, quejas = flags_escritos("--transfers 8")
c("la sintaxis de la línea de comandos no sale del diálogo", datos, None)
c("y se explica por qué, dentro del propio diálogo",
  any("guiones" in q or "clave = valor" in q for q in quejas), True)

datos, _, quejas = flags_escritos('workdir = "otro"')
c("un flag que pone sync.py tampoco sale", datos, None)
c("con su motivo", any("no se configura aquí" in q for q in quejas), True)

datos, _, _ = flags_escritos("transfers = 8", boton="Cancelar")
c("cancelar no devuelve nada", datos, None)


# --- y el formulario de la pareja recoge lo que diga ese diálogo -------------

tk_pairs.flags_form = lambda *a, **k: {"flags": {"transfers": 8},
                                       "extra_flags": ["--stats", "10s"]}


def _abrir_y_guardar(self, *_a, **_k):
    botones = {}
    pila = [self]
    while pila:
        w = pila.pop()
        pila += list(w.winfo_children())
        if isinstance(w, ttk.Button):
            botones[w.cget("text")] = w
    botones["Editar flags…"].invoke()
    botones["Guardar…"].invoke()


tk.Toplevel.wait_window = _abrir_y_guardar
datos = FORMULARIO(raiz, BASE, "notas", dict(BASE["pair"][0]))
c("el formulario devuelve los flags del diálogo", datos["flags"], {"transfers": 8})
c("y sus argumentos extra", datos["extra_flags"], ["--stats", "10s"])


sys.exit(c.report())
