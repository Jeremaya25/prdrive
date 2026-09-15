#!/usr/bin/env python3
"""
Las dos pantallas nuevas, conducidas sin nadie delante.

No se comprueba el aspecto: se comprueba el cableado. Que pulsar un botón acabe
llamando al editor que toca con lo que dice el formulario, que un cambio se
refleje donde debe, y que la pantalla de penwatch sepa pintar sus filas.

El catálogo se sustituye entero (`catalog.load` / `catalog.push`): aquí no se
toca la red, y así se puede comprobar lo que de verdad importa de esta pantalla,
que es que un botón del bloque «Catálogo» NO cambie el config de este dispositivo y uno
del bloque «Este dispositivo» NO cambie el catálogo.

Las ventanas se crean ocultas y no se entra nunca en el bucle de eventos.
"""

import subprocess
import sys

from _harness import Checks, sandbox

import tomllib

from common import catalog, config_file, fleet, model

c = Checks("pantallas Tk (cableado)")

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(0)

from ui import tk_fleet, tk_pairs, tk_watch

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
ocultar(tk_fleet)
# Las consecuencias de un plan se enseñan en su propia ventana (`confirmar_plan`),
# no en un messagebox: aquí se responde que sí y ya está. Lo que se comprueba de
# esta pantalla es el cableado, no el diálogo.
tk_pairs.confirmar_plan = lambda *a, **k: True
messagebox.askokcancel = lambda *a, **k: True            # el resto de sí/no
messagebox.showinfo = lambda *a, **k: None
errores: list[str] = []
messagebox.showerror = lambda titulo, texto=None, **k: errores.append(str(texto))

BASE = {"defaults": {"remote": "nas"},
        "pair": [{"name": "notas", "local": "sync-data/notas",
                  "remote_path": "/R/notas", "mode": "bisync"},
                 {"name": "subida", "local": "sync-data/subida",
                  "remote_path": "/R/subida", "mode": "up"}]}

# El catálogo tiene las dos del dispositivo más una que aquí no se usa.
CAT = {"defaults": {"remote": "nas"},
       "pair": [dict(BASE["pair"][0]), dict(BASE["pair"][1]),
                {"name": "fotos", "local": "sync-data/fotos",
                 "remote_path": "/R/fotos", "mode": "up"}]}

subidos: list[dict] = []


def falso_catalogo(raw=None):
    texto = config_file.dumps(CAT)
    return catalog.Catalog(raw=tomllib.loads(texto), text=texto,
                           source="remote", stamp="2026-01-01 00:00:00",
                           endpoint="nas:/prdrive-catalog/pairs.toml"), None


def falso_push(new_raw, base_text, raw_local=None):
    subidos.append(dict(new_raw))
    return ["Catálogo actualizado (de mentira)"]


catalog.load = falso_catalogo
catalog.push = falso_push
catalog.run = lambda args: (_ for _ in ()).throw(
    AssertionError("ningún test puede hablar con el remoto"))


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


# --- la lista une el catálogo y el dispositivo ---------------------------------------
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

# --- 'Usar aquí' trae una pareja del catálogo a este dispositivo ---------------------
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

# --- el bloque del catálogo escribe en el catálogo, no en el dispositivo -------------
with sandbox():
    subidos.clear()
    cfg = preparar()
    tk_pairs.formulario = lambda parent, raw, original, actual, **k: {
        "name": "musica", "local": "sync-data/musica", "remote_path": "/R/musica",
        "mode": "down", "include": [], "exclude": []}
    tk.Toplevel.wait_window = pulsar("Nueva…")

    cambiado = tk_pairs.open_dialog(raiz, cfg)
    c("crear en el catálogo NO cambia el config de este dispositivo", cambiado, False)
    c("este dispositivo sigue con sus dos parejas", model.load_config().names,
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
    c("este dispositivo no se entera", model.load_config().names, ["notas", "subida"])

# --- sin red: el bloque del catálogo se deshabilita --------------------------
with sandbox():
    cfg = preparar()
    texto = config_file.dumps(CAT)
    catalog.load = lambda raw=None: (
        catalog.Catalog(raw=tomllib.loads(texto), text=texto, source="cache",
                        stamp="2026-01-01 00:00:00", endpoint="nas:/x/pairs.toml"),
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
    c("pero lo de este dispositivo sigue disponible", estados["Usar aquí"], "normal")

    catalog.load = falso_catalogo

# --- el explorador del remoto -------------------------------------------------
# El remoto se sustituye entero: lo que se comprueba es que navegar y elegir
# devuelvan la ruta que se está mirando, y que sin conexión el botón esté
# apagado en vez de abrir un explorador que no puede listar nada.
LSD = "          -1 2026-01-01 12:00:00        -1 documentos\n"


def falso_lsd(args):
    return subprocess.CompletedProcess(args, 0, stdout=LSD, stderr="")


def navegar_y_elegir(entrar_veces=1):
    """Entra en la primera carpeta N veces y pulsa «Elegir esta carpeta»."""
    def _wait(self, *_a, **_k):
        for _ in range(entrar_veces):
            arbol, boton = None, None
            pila = [self]
            while pila:
                w = pila.pop()
                pila += list(w.winfo_children())
                if isinstance(w, ttk.Treeview):
                    arbol = w
                elif isinstance(w, ttk.Button) and w.cget("text") == "Entrar":
                    boton = w
            if arbol is None or not arbol.get_children():
                break
            arbol.selection_set(arbol.get_children()[0])
            boton.invoke()
        pila = [self]
        while pila:
            w = pila.pop()
            pila += list(w.winfo_children())
            if isinstance(w, ttk.Button) and w.cget("text") == "Elegir esta carpeta":
                w.invoke()
                return
    return _wait


real_run = catalog.run
try:
    catalog.run = falso_lsd
    tk.Toplevel.wait_window = navegar_y_elegir(0)
    c("elegir sin moverse devuelve la carpeta que contiene a la pareja",
      tk_pairs.explorador_remoto(raiz, "nas", "/datos/notas"), "/datos")
    tk.Toplevel.wait_window = navegar_y_elegir(1)
    c("y entrar en una baja un nivel",
      tk_pairs.explorador_remoto(raiz, "nas", "/datos/notas"), "/datos/documentos")
    tk.Toplevel.wait_window = pulsar("Cancelar")
    c("cancelar no devuelve ninguna ruta",
      tk_pairs.explorador_remoto(raiz, "nas", "/datos"), None)

    # La pareja apuntaba a una carpeta que ya no está: se empieza por la raíz en
    # vez de abrir un diálogo vacío del que no se puede ir a ningún sitio.
    def solo_la_raiz(args):
        if args[-1] == "nas:/":
            return subprocess.CompletedProcess(args, 0, stdout=LSD, stderr="")
        return subprocess.CompletedProcess(args, 3, stdout="",
                                           stderr="directory not found")

    catalog.run = solo_la_raiz
    tk.Toplevel.wait_window = navegar_y_elegir(0)
    c("una carpeta que ya no existe abre en la raíz",
      tk_pairs.explorador_remoto(raiz, "nas", "/se/ha/borrado"), "/")
finally:
    catalog.run = real_run


def examinar_remoto_activo(explorable):
    """El estado del botón «Examinar…» de la ruta remota del formulario.

    Hay dos con ese texto —la ruta local también tiene el suyo—, y el del disco
    está siempre disponible: el que puede quedarse apagado es el segundo."""
    estados = []

    def _wait(self, *_a, **_k):
        pila = [self]
        while pila:
            w = pila.pop(0)
            pila += list(w.winfo_children())
            if isinstance(w, ttk.Button) and w.cget("text") == "Examinar…":
                estados.append(str(w.cget("state")))

    tk.Toplevel.wait_window = _wait
    FORMULARIO(raiz, BASE, "notas", dict(BASE["pair"][0]), explorable=explorable)
    return estados


c("con el catálogo recién leído se puede recorrer el remoto",
  examinar_remoto_activo(True), ["normal", "normal"])
c("desde la copia local, no; el disco de aquí sí",
  sorted(examinar_remoto_activo(False)), ["disabled", "normal"])


# --- «Simular» lanza un dry-run, no una pasada --------------------------------
# La ventana de salida se sustituye: lo que importa es QUÉ orden se lanza, y
# ningún test ejecuta sync.py de verdad.
with sandbox():
    cfg = preparar()
    lanzadas: list[list[str]] = []
    real_salida = tk_pairs.output_window
    tk_pairs.output_window = lambda titulo, cmd, **k: lanzadas.append(list(cmd))
    try:
        tk.Toplevel.wait_window = elegir_y_pulsar("Simular", "notas")
        c("simular no cuenta como un cambio del config",
          tk_pairs.open_dialog(raiz, cfg), False)
        c("se lanza sync.py con la pareja elegida", lanzadas[-1][-2:],
          ["notas", "--dry-run"])
        c("y nada más: un simulacro no escribe en el config",
          model.load_config().names, ["notas", "subida"])

        # Una pareja que este dispositivo no usa no se puede simular aquí.
        lanzadas.clear()
        errores.clear()
        tk.Toplevel.wait_window = elegir_y_pulsar("Simular", "fotos")
        tk_pairs.open_dialog(raiz, cfg)
        c("simular una que no se usa aquí no lanza nada", lanzadas, [])
        c("y lo dice", any("no se usa en este dispositivo" in e for e in errores), True)
    finally:
        tk_pairs.output_window = real_salida


# --- la flota: se abre desde parejas, y solo toca la nota de ESTE dispositivo ---
#
# La lista la sirve `common/fleet.py`, que aquí se sustituye entera: lo que se
# comprueba es el cableado de la ventana, no el remoto.
FLOTA = [fleet.Dispositivo(id="yo", nombre="este", version="0.1.4",
                           plataformas=("windows-x64",),
                           last_seen="2026-01-01 00:00:00", last_result="ok"),
         fleet.Dispositivo(id="otro", nombre="el del trabajo", version="0.1.2",
                           plataformas=("linux-x64",),
                           last_seen="2026-01-02 00:00:00", last_result="ok")]
publicadas: list[tuple] = []
guardados: list[str] = []

fleet.leer = lambda raw=None: (list(FLOTA), None)
fleet.device_id = lambda app_dir=None: "yo"
fleet.nombre = lambda state_dir=None: "este"
fleet.guardar_nombre = lambda texto, state_dir=None: bool(guardados.append(texto)) or True
fleet.publicar = lambda cfg=None, raw=None, forzar=False: bool(
    publicadas.append((cfg, forzar))) or True

with sandbox():
    cfg = preparar()
    filas = {}

    def mirar_flota(self, *_a, **_k):
        pila = [self]
        while pila:
            w = pila.pop()
            pila += list(w.winfo_children())
            if isinstance(w, ttk.Treeview):
                for iid in w.get_children():
                    filas[iid] = w.item(iid)["values"]

    tk.Toplevel.wait_window = mirar_flota
    tk_fleet.open_dialog(raiz, cfg, dict(BASE))
    c("la flota enseña un dispositivo por nota", sorted(filas), ["otro", "yo"])
    c("y marca cuál es este", (filas["yo"][0], filas["otro"][0]), ("✓", ""))
    c("con su versión y sus plataformas", filas["otro"][2:4], ["0.1.2", "linux-x64"])

# Quitar de la lista la nota de OTRO: lo que se comprueba aquí es que la ventana
# pide quitar el que está elegido, y que sobre este mismo dispositivo el botón ni
# siquiera se enciende. Que `fleet` se plante es cosa de test_fleet.py.
olvidados: list[str] = []
fleet.olvidar = lambda quien, raw=None: bool(olvidados.append(quien)) or None

def buscar(raiz_widget, clase, texto=None):
    """El primer widget de esa clase (y con ese texto, si se dice)."""
    pila = [raiz_widget]
    while pila:
        w = pila.pop()
        pila += list(w.winfo_children())
        if isinstance(w, clase) and (texto is None or w.cget("text") == texto):
            return w
    return None


def elegir(ventana, arbol, iid):
    """Selecciona una fila y deja que Tk reparta el <<TreeviewSelect>>.

    `update_idletasks()` no vale: el evento virtual va a la cola normal, no a la
    de tareas ociosas, así que sin esto el botón que cuelga de la selección se
    mira antes de que nadie lo haya repasado."""
    arbol.selection_set(iid)
    ventana.update()


with sandbox():
    cfg = preparar()

    def quitar_otro(self, *_a, **_k):
        elegir(self, buscar(self, ttk.Treeview), "otro")
        buscar(self, ttk.Button, "Quitar de la lista…").invoke()

    tk.Toplevel.wait_window = quitar_otro
    tk_fleet.open_dialog(raiz, cfg, dict(BASE))
    c("quitar de la lista pide olvidar el elegido", olvidados, ["otro"])

with sandbox():
    cfg = preparar()
    apagados = {}

    def mirar_boton(self, *_a, **_k):
        """Elige cada fila y anota si el botón de quitar se enciende."""
        arbol = buscar(self, ttk.Treeview)
        boton = buscar(self, ttk.Button, "Quitar de la lista…")
        for iid in ("yo", "otro"):
            elegir(self, arbol, iid)
            apagados[iid] = str(boton.cget("state"))

    tk.Toplevel.wait_window = mirar_boton
    tk_fleet.open_dialog(raiz, cfg, dict(BASE))
    c("sobre este dispositivo el botón de quitar está apagado", apagados["yo"],
      "disabled")
    c("y sobre otro, encendido", apagados["otro"], "normal")
    c("elegir una fila no quita nada por su cuenta", olvidados, ["otro"])

with sandbox():
    cfg = preparar()
    tk_fleet.pedir_nombre = lambda parent, actual: "el pendrive azul"
    tk.Toplevel.wait_window = pulsar("Cambiar el nombre de este…")
    c("cambiar el nombre lo informa", tk_fleet.open_dialog(raiz, cfg, dict(BASE)), True)
    c("se guarda en el dispositivo", guardados, ["el pendrive azul"])
    c("y se publica en el acto, sin esperar a la siguiente pasada",
      [forzar for _cfg, forzar in publicadas], [True])

with sandbox():
    cfg = preparar()
    abiertas = []
    tk_fleet.open_dialog = lambda parent, config, raw=None: abiertas.append(config) or False
    tk.Toplevel.wait_window = pulsar("Dispositivos…")
    tk_pairs.open_dialog(raiz, cfg)
    c("la flota se abre desde la pantalla de parejas", len(abiertas), 1)
    c("y no cuenta como un cambio del config", model.load_config().names,
      ["notas", "subida"])


# --- la pantalla de penwatch pinta su estado ---------------------------------
with sandbox():
    cfg = preparar()
    tk.Toplevel.wait_window = pulsar("Cerrar")
    try:
        tk_watch.open_dialog(raiz, cfg)
        c("la pantalla de penwatch se abre y se cierra", True, True)
    except Exception as e:
        c("la pantalla de penwatch se abre y se cierra", f"{type(e).__name__}: {e}", True)

    tk.Toplevel.wait_window = pulsar("Detectar el dispositivo")
    try:
        tk_watch.open_dialog(raiz, cfg)
        c("'Detectar el dispositivo' no revienta", True, True)
    except Exception as e:
        c("'Detectar el dispositivo' no revienta", f"{type(e).__name__}: {e}", True)



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
