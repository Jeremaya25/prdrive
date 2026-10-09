#!/usr/bin/env python3
"""Las dos pantallas nuevas, conducidas sin nadie delante.

No se comprueba el aspecto: se comprueba el cableado. Que pulsar un botón acabe
llamando al editor que toca con lo que dice el formulario, que un cambio se
refleje donde debe, y que la pantalla de penwatch sepa pintar sus filas.

El catálogo se sustituye entero (`catalog.load` / `catalog.push`): aquí no se
toca la red, y así se puede comprobar lo que de verdad importa de esta
pantalla, que es que un botón del bloque «Catálogo» NO cambie el config de este
dispositivo y uno del bloque «Este dispositivo» NO cambie el catálogo.

Las ventanas se crean ocultas y no se entra nunca en el bucle de eventos.
"""

import subprocess
import sys
from datetime import datetime, timedelta

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

from ui import flags_editor, segundo_plano, tk_fleet, tk_pairs, tk_versions, tk_watch, versions_editor, watch

# El de verdad: más abajo hay tramos que lo sustituyen por un formulario de
# mentira, y el último los necesita a los dos.
FORMULARIO = tk_pairs.formulario

# Lo que esas pantallas leen del remoto llega por sondeo, y aquí no se entra
# nunca en el bucle de eventos: se lee en el sitio, y la pantalla está entera
# antes de enseñarse. Lo que pasa con un remoto lento o caído, con hilos de
# verdad, es de test_tk_segundo_plano.py.
segundo_plano.lanzar = segundo_plano.en_el_acto


def working_en_el_acto(parent, title, funcion, mensaje="", **_k):
    """Sustituye a `working()`: hace el trabajo en el sitio, sin ventanita."""
    try:
        return True, funcion()
    except Exception as e:                               # noqa: BLE001 — como working()
        return False, e


tk_pairs.working = working_en_el_acto
tk_fleet.working = working_en_el_acto


def ocultar(modulo):
    """Los diálogos se crean pero no se enseñan: esto no es una demo.

    `modal()` ya los devuelve ocultos; quien los centra y los enseña es
    `mostrar()`, así que basta con quedarse solo con su espera."""
    modulo.mostrar = lambda dlg, parent=None: dlg.wait_window()


def pulsar(texto):
    """Un wait_window que, en vez de esperar, pulsa un botón y vuelve."""
    def _wait(self, *_a, **_k):
        """Recorre la ventana, pulsa el botón y vuelve."""
        pila = [self]
        while pila:
            w = pila.pop()
            pila += list(w.winfo_children())
            if isinstance(w, ttk.Button) and w.cget("text") == texto:
                w.invoke()
                return
    return _wait


def ver_catalogo(ventana) -> None:
    """Pasa la pantalla de parejas a editar el catálogo, con su botón."""
    pila = [ventana]
    while pila:
        w = pila.pop()
        pila += list(w.winfo_children())
        if isinstance(w, ttk.Radiobutton) and str(w.cget("text")) == "Catálogo":
            w.invoke()
            return


def ver_dispositivo(ventana) -> None:
    """Vuelve la pantalla de parejas a este dispositivo, con su botón."""
    pila = [ventana]
    while pila:
        w = pila.pop()
        pila += list(w.winfo_children())
        if isinstance(w, ttk.Radiobutton) and str(w.cget("text")) == "Este dispositivo":
            w.invoke()
            return


def montar_catalogo(ventana) -> None:
    """Deja creado el bloque del catálogo (se crea al verlo) y vuelve a este dispositivo."""
    ver_catalogo(ventana)
    ver_dispositivo(ventana)


def elegir_y_pulsar(texto, pareja=None, catalogo=False, cambiar=None):
    """Como pulsar(), pero eligiendo antes una fila de la lista.

    Args:
        catalogo: Pasar antes a editar el catálogo.
        cambiar: Lo que se escribe en el editor de la pareja antes de pulsar:
            `{campo: valor}`.
    """
    def _wait(self, *_a, **_k):
        """Elige la fila de la lista, pulsa el botón y vuelve."""
        if catalogo:
            ver_catalogo(self)
        if pareja is not None:
            self.lista.elegir(pareja)
        for campo, valor in (cambiar or {}).items():
            self.editor.campos[campo].set(valor)
        for boton in botones_de_todos(self):
            if boton.cget("text") == texto:
                boton.invoke()
                return
    return _wait


def botones_de_todos(ventana) -> list:
    """Todos los botones de una ventana, en orden."""
    pila, salida = [ventana], []
    while pila:
        w = pila.pop(0)
        pila += list(w.winfo_children())
        if isinstance(w, ttk.Button):
            salida.append(w)
    return salida


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
    """Devuelve un catálogo de mentira, sin error."""
    texto = config_file.dumps(CAT)
    return catalog.Catalog(raw=tomllib.loads(texto), text=texto,
                           source="remote", stamp="2026-01-01 00:00:00",
                           endpoint="nas:/prdrive-catalog/pairs.toml"), None


def falso_push(new_raw, base_text, raw_local=None):
    """`push` de mentira: apunta lo subido."""
    subidos.append(dict(new_raw))
    return ["Catálogo actualizado (de mentira)"]


catalog.load = falso_catalogo
catalog.push = falso_push
catalog.run = lambda args: (_ for _ in ()).throw(
    AssertionError("ningún test puede hablar con el remoto"))


def preparar():
    """Escribe el config de prueba y lo devuelve ya parseado."""
    model.CONFIG_FILE.write_text(config_file.dumps(BASE), encoding="utf-8")
    return model.parse_config(BASE)


def dar_baseline(cfg, name):
    """Deja a esa pareja con un baseline válido."""
    from common import bisync
    pareja = next(p for p in cfg.pairs if p.name == name)
    pareja.workdir.mkdir(parents=True, exist_ok=True)
    prefijo = bisync.expected_prefix(pareja)
    for sufijo in (bisync.PATH1_SUFFIX, bisync.PATH2_SUFFIX):
        (pareja.workdir / f"{prefijo}{sufijo}").write_text("x", encoding="utf-8")


# la lista une el catálogo y el dispositivo
with sandbox():
    cfg = preparar()
    filas = {}

    def mirar(self, *_a, **_k):
        """Apunta las filas de la lista."""
        filas.update({n: f["fila"] for n, f in self.lista.filas.items()})

    tk.Toplevel.wait_window = mirar
    tk_pairs.open_dialog(raiz, cfg)
    c("la lista trae las tres del catálogo", sorted(filas), ["fotos", "notas", "subida"])
    c("'fotos' sale como no usada aquí", filas["fotos"].en_pen, False)
    c("y con origen 'sin usar'", filas["fotos"].origen, "sin usar")
    c("'notas' sale usada y viniendo del catálogo",
      (filas["notas"].en_pen, filas["notas"].origen), (True, "catálogo"))
    c("la ruta local sale como se escribe, no adonde cae",
      filas["notas"].local, "sync-data/notas")

# 'Usar aquí' trae una pareja del catálogo a este dispositivo
with sandbox():
    cfg = preparar()
    tk.Toplevel.wait_window = elegir_y_pulsar("Usar aquí", "fotos")
    cambiado = tk_pairs.open_dialog(raiz, cfg)
    c("usar aquí informa de que hubo cambios", cambiado, True)
    c("la pareja del catálogo está en el config", model.load_config().names,
      ["notas", "subida", "fotos"])
    c("y no se ha tocado el catálogo", subidos, [])

# Lo que se puede hacer depende de la pareja elegida
with sandbox():
    cfg = preparar()
    estados = {}

    def mirar_fotos(self, *_a, **_k):
        """Elige una pareja que aquí no se usa y apunta qué queda encendido."""
        self.lista.elegir("fotos")
        estados.update({b.cget("text"): str(b.cget("state"))
                        for b in botones_de_todos(self)})
        estados["campo"] = str(self.editor.entradas["remote_path"].cget("state"))

    tk.Toplevel.wait_window = mirar_fotos
    tk_pairs.open_dialog(raiz, cfg)
    c("una pareja que no se usa aquí se puede usar", estados["Usar aquí"], "normal")
    c("pero no guardar ni simular", (estados["Guardar aquí…"], estados["Simular"]),
      ("disabled", "disabled"))
    c("y el editor la enseña sin dejarla cambiar", estados["campo"], "readonly")

# «Guardar aquí…» guarda lo del editor y aparta el baseline, como manda el editor
with sandbox():
    cfg = preparar()
    dar_baseline(cfg, "notas")
    tk.Toplevel.wait_window = elegir_y_pulsar("Guardar aquí…", "notas",
                                              cambiar={"remote_path": "/R/otro"})
    c("guardar aquí informa del cambio", tk_pairs.open_dialog(raiz, cfg), True)
    c("el config apunta al destino nuevo",
      next(p.remote_path for p in model.load_config().pairs if p.name == "notas"),
      "/R/otro")
    c("y el baseline se ha apartado",
      any(p.name.startswith("notas.old-") for p in model.STATE_DIR.iterdir()), True)
    c("el catálogo sigue sin tocarse", subidos, [])

# Cambiar de pareja con algo sin guardar lo pregunta, y «no» se queda donde estaba
with sandbox():
    cfg = preparar()
    visto = {}

    def cambiar_y_dejar(self, *_a, **_k):
        """Cambia un campo, intenta pasar a otra pareja diciendo que no, y luego que sí."""
        self.lista.elegir("notas")
        self.editor.campos["remote_path"].set("/R/a-medias")
        messagebox.askokcancel = lambda *a, **k: False
        visto["no"] = (self.lista.elegir("subida"), self.lista.elegida,
                       self.editor.campos["remote_path"].get())
        messagebox.askokcancel = lambda *a, **k: True
        visto["si"] = (self.lista.elegir("subida"), self.lista.elegida,
                       self.editor.campos["remote_path"].get())

    tk.Toplevel.wait_window = cambiar_y_dejar
    c("con cambios sin guardar, «no» no cambia de pareja",
      tk_pairs.open_dialog(raiz, cfg) or visto["no"], (False, "notas", "/R/a-medias"))
    c("y «sí» pasa a la otra, con lo suyo", visto["si"], (True, "subida", "/R/subida"))

# El catálogo que llega (aquí, el de «Releer», que contesta en el acto) no borra lo
# escrito en el editor: se queda con ello y con su marca de «sin guardar»
with sandbox():
    cfg = preparar()
    visto = {}

    def escribir_y_releer(self, *_a, **_k):
        """Escribe en el editor, pide el catálogo otra vez y mira lo que queda."""
        montar_catalogo(self)          # «Releer» es del bloque del catálogo, que se crea al verlo
        self.lista.elegir("notas")
        self.editor.campos["remote_path"].set("/R/a-medias")
        next(b for b in botones_de_todos(self) if b.cget("text") == "Releer").invoke()
        visto["campo"] = self.editor.campos["remote_path"].get()
        messagebox.askokcancel = lambda *a, **k: False
        visto["sigue_sucio"] = (self.lista.elegir("subida"), self.lista.elegida)
        messagebox.askokcancel = lambda *a, **k: True
        next(b for b in botones_de_todos(self) if b.cget("text") == "Descartar").invoke()
        visto["descartado"] = self.editor.campos["remote_path"].get()

    tk.Toplevel.wait_window = escribir_y_releer
    tk_pairs.open_dialog(raiz, cfg)
    c("al llegar el catálogo, lo escrito en el editor sigue ahí",
      visto["campo"], "/R/a-medias")
    c("y sigue contando como sin guardar: cambiar de pareja pregunta",
      visto["sigue_sucio"], (False, "notas"))
    c("«Descartar» lo devuelve a lo guardado", visto["descartado"], "/R/notas")

# 'Volver al catálogo' deshace la modificación local
with sandbox():
    cfg = preparar()
    estados = {}

    def mirar_volver(self, *_a, **_k):
        """Apunta si «Volver al catálogo» está encendido para 'notas'."""
        self.lista.elegir("notas")
        estados.update({b.cget("text"): str(b.cget("state"))
                        for b in botones_de_todos(self)})

    tk.Toplevel.wait_window = mirar_volver
    tk_pairs.open_dialog(raiz, cfg)
    c("si ya coincide con el catálogo, no hay a qué volver",
      estados["Volver al catálogo"], "disabled")

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

# lo del catálogo escribe en el catálogo, no en el dispositivo
with sandbox():
    subidos.clear()
    cfg = preparar()
    tk_pairs.formulario = lambda parent, raw, original, actual, **k: {
        "name": "musica", "local": "sync-data/musica", "remote_path": "/R/musica",
        "mode": "down", "include": [], "exclude": []}
    tk.Toplevel.wait_window = elegir_y_pulsar("Nueva pareja…", catalogo=True)

    cambiado = tk_pairs.open_dialog(raiz, cfg)
    c("crear en el catálogo NO cambia el config de este dispositivo", cambiado, False)
    c("este dispositivo sigue con sus dos parejas", model.load_config().names,
      ["notas", "subida"])
    c("y la pareja nueva ha ido al catálogo",
      [p["name"] for p in subidos[-1]["pair"]], ["notas", "subida", "fotos", "musica"])

with sandbox():
    subidos.clear()
    cfg = preparar()
    tk.Toplevel.wait_window = elegir_y_pulsar("Guardar en el catálogo…", "fotos",
                                              catalogo=True,
                                              cambiar={"remote_path": "/R/fotos-2026"})
    c("guardar en el catálogo NO cambia este dispositivo", tk_pairs.open_dialog(raiz, cfg),
      False)
    c("y sube lo del editor",
      next(p["remote_path"] for p in subidos[-1]["pair"] if p["name"] == "fotos"),
      "/R/fotos-2026")
    c("y nada más que eso", [p["name"] for p in subidos[-1]["pair"]],
      ["notas", "subida", "fotos"])

with sandbox():
    subidos.clear()
    cfg = preparar()
    tk.Toplevel.wait_window = elegir_y_pulsar("Borrar del catálogo…", "fotos", catalogo=True)
    tk_pairs.open_dialog(raiz, cfg)
    c("borrar del catálogo quita solo del catálogo",
      [p["name"] for p in subidos[-1]["pair"]], ["notas", "subida"])
    c("este dispositivo no se entera", model.load_config().names, ["notas", "subida"])

# sin red: lo del catálogo se apaga
with sandbox():
    cfg = preparar()
    texto = config_file.dumps(CAT)
    catalog.load = lambda raw=None: (
        catalog.Catalog(raw=tomllib.loads(texto), text=texto, source="cache",
                        stamp="2026-01-01 00:00:00", endpoint="nas:/x/pairs.toml"),
        "Sin conexión con el catálogo.")

    estados = {}

    def mirar_botones(self, *_a, **_k):
        """Pasa al catálogo y apunta los botones y si el editor se deja tocar."""
        ver_catalogo(self)
        estados.update({b.cget("text"): str(b.cget("state"))
                        for b in botones_de_todos(self)})
        estados["campo"] = str(self.editor.entradas["remote_path"].cget("state"))

    tk.Toplevel.wait_window = mirar_botones
    tk_pairs.open_dialog(raiz, cfg)
    c("desde la copia, el catálogo no se puede tocar",
      [estados[t] for t in ("Ajustes del catálogo…", "Nueva pareja…",
                            "Borrar del catálogo…", "Guardar en el catálogo…")],
      ["disabled"] * 4)
    c("  ni su editor", estados["campo"], "readonly")
    c("pero sí se puede releer", estados["Releer"], "normal")

    catalog.load = falso_catalogo

# el explorador del remoto
#
# El remoto se sustituye entero: lo que se comprueba es que navegar y elegir
# devuelvan la ruta que se está mirando, y que sin conexión el botón esté
# apagado en vez de abrir un explorador que no puede listar nada.
LSD = "          -1 2026-01-01 12:00:00        -1 documentos\n"


def falso_lsd(args):
    """Devuelve un `rclone lsd` de mentira."""
    return subprocess.CompletedProcess(args, 0, stdout=LSD, stderr="")


def navegar_y_elegir(entrar_veces=1):
    """Entra en la primera carpeta N veces y pulsa «Elegir esta carpeta»."""
    def _wait(self, *_a, **_k):
        """Entra en las carpetas y pulsa «Elegir esta carpeta»."""
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
        """`rclone lsd` que solo conoce la raíz del remoto."""
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
        """Apunta si «Examinar…» está activo en el formulario."""
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


# «Simular» lanza un dry-run, no una pasada
#
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

        # Una pareja que este dispositivo no usa no se puede simular aquí: el
        # botón está apagado.
        lanzadas.clear()
        tk.Toplevel.wait_window = elegir_y_pulsar("Simular", "fotos")
        tk_pairs.open_dialog(raiz, cfg)
        c("simular una que no se usa aquí no lanza nada", lanzadas, [])
    finally:
        tk_pairs.output_window = real_salida


# la flota: se abre desde parejas, y solo toca la nota de ESTE dispositivo
#
# La lista la sirve `common/fleet.py`, que aquí se sustituye entera: lo que se
# comprueba es el cableado de la ventana, no el remoto.
FLOTA = [fleet.Dispositivo(id="yo", nombre="este", version="0.1.4",
                           plataformas=("windows-x64",),
                           last_seen="2026-01-01 00:00:00", last_result="ok"),
         fleet.Dispositivo(id="otro", nombre="el del trabajo", version="0.1.2",
                           plataformas=("linux-x64",),
                           last_seen="2026-01-02 00:00:00", last_result="ok",
                           equipos=(fleet.Equipo("OFICINA-07", "2026-01-02 00:00:00"),))]
publicadas: list[tuple] = []
guardados: list[str] = []

fleet.leer = lambda raw=None: (list(FLOTA), None)
fleet.device_id = lambda app_dir=None: "yo"
fleet.equipo_actual = lambda: "PORTATIL"
fleet.nombre = lambda state_dir=None: "este"
fleet.guardar_nombre = lambda texto, state_dir=None: bool(guardados.append(texto)) or True
fleet.publicar = lambda cfg=None, raw=None, forzar=False: bool(
    publicadas.append((cfg, forzar))) or True

with sandbox():
    cfg = preparar()
    filas = {}
    titulos = []

    def mirar_flota(self, *_a, **_k):
        """Apunta lo que dice la tabla de la flota."""
        titulos.extend(self.tabla.cabeceras)
        filas.update(self.tabla.filas)

    tk.Toplevel.wait_window = mirar_flota
    c("«Dispositivos…» no devuelve nada: ya no cambia nada de este dispositivo",
      tk_fleet.open_dialog(raiz, cfg, dict(BASE)), None)
    c("la flota enseña un dispositivo por nota", sorted(filas), ["otro", "yo"])
    c("y marca cuál es este", (filas["yo"][0], filas["otro"][0]), ("✓", ""))
    c("la tabla: cuándo se le vio, desde qué equipo y cómo acabó (lo demás, a la ficha)",
      titulos, ["Este", "Dispositivo", "Visto", "Último equipo", "Última pasada"])
    c("cada fila lleva una celda por columna", {len(f) for f in filas.values()}, {5})
    c("«Último equipo» es el desde el que publicó por última vez",
      filas["otro"][3], "OFICINA-07")
    c("y de una nota que no lo apunta, una raya", filas["yo"][3], tk_fleet.SIN_DATO)
    c("la última pasada sigue al final, y un «ok» se dice «bien»",
      (filas["otro"][4], filas["yo"][4]), (tk_fleet.BIEN, tk_fleet.BIEN))

# la columna «Último equipo»: solo el más reciente, la lista entera es de la ficha
Recientes = fleet.Dispositivo(
    id="r", nombre="el del trabajo", version="0.2.1", plataformas=(),
    last_seen="2026-09-02 09:12:40", last_result="ok",
    equipos=(fleet.Equipo("OFICINA-07", "2026-09-02 09:12:40"),
             fleet.Equipo("PORTATIL", "2026-09-01 10:00:00")))
c("el último equipo es el más reciente de la nota",
  tk_fleet.ultimo_equipo(Recientes), "OFICINA-07")
c("sin equipos en la nota, una raya",
  tk_fleet.ultimo_equipo(Recientes._replace(equipos=())), tk_fleet.SIN_DATO)
c("la columna está en la tabla", [k for k, *_ in tk_fleet.COLUMNAS],
  ["aqui", "nombre", "visto", "equipo", "estado"])

# la ficha: qué dice, sin dibujarla
Linea = tk_fleet.Linea
AYER = f"{datetime.now() - timedelta(days=1):%Y-%m-%d %H:%M:%S}"
COMPLETA = fleet.Dispositivo(
    id="3f9c1a2b77", nombre="el del trabajo", version="0.2.1",
    plataformas=("windows-x64", "linux-x64"), last_seen=AYER,
    last_result="fallo en fotos",
    equipos=(fleet.Equipo("PORTATIL", AYER),
             fleet.Equipo("OFICINA-07", "2026-09-02 09:12:40")),
    ultima_buena="2026-09-01 08:00:00")
apartados = {f.rotulo: f for f in tk_fleet.ficha(COMPLETA, "OFICINA-07")}
c("la ficha tiene sus cuatro apartados, en orden", list(apartados),
  list(tk_fleet.ROTULOS_FICHA))
c("con la versión y las plataformas",
  (apartados["Versión"].lineas, apartados["Para"].lineas),
  ((Linea("0.2.1"),), (Linea("windows-x64, linux-x64"),)))
c("el estado dice desde cuándo falla, en pista", apartados["Estado"].lineas,
  (Linea("fallo en fotos"), Linea("Última pasada buena: 2026-09-01", pista=True)))
c("los equipos, el más reciente primero, y marcado el de aquí",
  [ln.texto for ln in apartados["Equipos"].lineas],
  ["PORTATIL", "OFICINA-07 · este equipo"])
c("con la fecha de la columna «Visto»: relativa, o entera si es vieja",
  [ln.fecha for ln in apartados["Equipos"].lineas], ["ayer", "2026-09-02"])
c("y el sitio de todos los que caben, aunque haya menos",
  apartados["Equipos"].reserva, fleet.MAX_EQUIPOS)
c("sin saber el equipo de aquí no se marca ninguno",
  [ln.texto for ln in tk_fleet.ficha(COMPLETA, "")[3].lineas],
  ["PORTATIL", "OFICINA-07"])

ninguna = {f.rotulo: f for f in tk_fleet.ficha(
    COMPLETA._replace(ultima_buena=fleet.SIN_BUENA), "")}
c("de una pareja sin pasada buena que conste, se dice eso",
  ninguna["Estado"].lineas[1], Linea(tk_fleet.SIN_BUENA, pista=True))

vieja = {f.rotulo: f for f in tk_fleet.ficha(fleet.Dispositivo(
    id="v", nombre="de la 0.2.3", version="0.2.3", plataformas=(),
    last_seen=AYER, last_result="ok"), "PORTATIL")}
c("una nota vieja: sin equipos, y se dice por qué", vieja["Equipos"].lineas,
  (Linea(tk_fleet.SIN_EQUIPOS, pista=True),))
c("un estado bueno no habla de pasadas buenas", vieja["Estado"].lineas,
  (Linea(tk_fleet.BIEN),))
c("y sin plataformas, una raya", vieja["Para"].lineas, (Linea("—"),))

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


def elegir(ventana, iid):
    """Elige una fila de la tabla de la flota, como un clic."""
    ventana.tabla.elegir(iid)
    ventana.update()


with sandbox():
    cfg = preparar()

    def quitar_otro(self, *_a, **_k):
        """Elige la nota de otro dispositivo y pulsa «Quitar de la lista…»."""
        elegir(self, "otro")
        buscar(self, ttk.Button, "Quitar de la lista…").invoke()

    tk.Toplevel.wait_window = quitar_otro
    tk_fleet.open_dialog(raiz, cfg, dict(BASE))
    c("quitar de la lista pide olvidar el elegido", olvidados, ["otro"])

with sandbox():
    cfg = preparar()
    apagados = {}

    def mirar_boton(self, *_a, **_k):
        """Elige cada fila y anota si el botón de quitar se enciende."""
        boton = buscar(self, ttk.Button, "Quitar de la lista…")
        for iid in ("yo", "otro"):
            elegir(self, iid)
            apagados[iid] = str(boton.cget("state"))

    tk.Toplevel.wait_window = mirar_boton
    tk_fleet.open_dialog(raiz, cfg, dict(BASE))
    c("sobre este dispositivo el botón de quitar está apagado", apagados["yo"],
      "disabled")
    c("y sobre otro, encendido", apagados["otro"], "normal")
    c("elegir una fila no quita nada por su cuenta", olvidados, ["otro"])


def etiquetas(ventana):
    """Cada etiqueta que hay ahora en la ventana, con su texto."""
    salida, pila = [], [ventana]
    while pila:
        w = pila.pop()
        pila += list(w.winfo_children())
        if isinstance(w, ttk.Label):
            salida.append((w, str(w.cget("text"))))
    return salida


def textos(ventana):
    """El texto de todas las etiquetas que hay ahora en la ventana."""
    salida, pila = [], [ventana]
    while pila:
        w = pila.pop()
        pila += list(w.winfo_children())
        if isinstance(w, ttk.Label):
            salida.append(str(w.cget("text")))
    return salida


with sandbox():
    cfg = preparar()
    fichas = {}

    def mirar_fichas(self, *_a, **_k):
        """Elige cada fila y apunta lo que dice la ficha."""
        for iid in ("otro", "yo"):
            elegir(self, iid)
            fichas[iid] = [t for _w, t in etiquetas(self)]       # la tabla es un lienzo

    tk.Toplevel.wait_window = mirar_fichas
    tk_fleet.open_dialog(raiz, cfg, dict(BASE))
    c("la ficha es la del elegido",
      ("id otro" in fichas["otro"], "id otro" in fichas["yo"]), (True, False))
    c("elegir otra fila la repinta",
      ("OFICINA-07" in fichas["otro"], "OFICINA-07" in fichas["yo"]), (True, False))
    c("y de una nota vieja dice que no consta",
      tk_fleet.SIN_EQUIPOS in fichas["yo"], True)

# Sin nadie en la lista no hay nada elegido, y la ficha no se enseña: en su
# sitio va el aviso de que todavía no ha dejado nota nadie.
with sandbox():
    cfg = preparar()
    vacia: dict = {}

    def mirar_vacia(self, *_a, **_k):
        """Apunta el aviso y la fila de la flota vacía."""
        aviso = buscar(self, ttk.Label, tk_fleet.SIN_NOTA)
        vacia["aviso"], vacia["fila"] = aviso, aviso.master.grid_slaves(row=2)

    fleet.leer = lambda raw=None: ([], None)
    tk.Toplevel.wait_window = mirar_vacia
    try:
        tk_fleet.open_dialog(raiz, cfg, dict(BASE))
    finally:
        fleet.leer = lambda raw=None: (list(FLOTA), None)
    c("con la flota vacía la ficha no se enseña, solo el aviso",
      vacia["fila"], [vacia["aviso"]])

# El nombre de este dispositivo se cambia en «Ajustes» → «Nombre e icono»: aquí
# solo se lee. La ventana no ofrece cambiarlo, no guarda ni publica ninguno, y
# dice dónde se hace.
with sandbox():
    cfg = preparar()
    lo_que_hay: dict = {}

    def mirar_acciones(self, *_a, **_k):
        """Apunta qué botones tiene la ventana de la flota y qué dice."""
        botones, pila = [], [self]
        while pila:
            w = pila.pop()
            pila += list(w.winfo_children())
            if isinstance(w, ttk.Button):
                botones.append(str(w.cget("text")))
        lo_que_hay["botones"] = sorted(botones)
        lo_que_hay["textos"] = textos(self)

    tk.Toplevel.wait_window = mirar_acciones
    tk_fleet.open_dialog(raiz, cfg, dict(BASE))
    c("no hay botón para cambiar el nombre",
      [b for b in lo_que_hay["botones"] if "nombre" in b.lower()], [])
    c("solo quitar de la lista, releer y cerrar", lo_que_hay["botones"],
      ["Cerrar", "Quitar de la lista…", "Releer"])
    c("y la ventana ya no sabe pedir un nombre", hasattr(tk_fleet, "pedir_nombre"),
      False)
    c("abrirla no guarda ni publica ningún nombre", (guardados, publicadas), ([], []))
    c("dice dónde se cambia",
      any("«Nombre e icono»" in t for t in lo_que_hay["textos"]), True)

with sandbox():
    cfg = preparar()
    abiertas = []
    tk_fleet.open_dialog = lambda parent, config, raw=None: abiertas.append(config) or False
    tk.Toplevel.wait_window = pulsar("Dispositivos…")
    tk_pairs.open_dialog(raiz, cfg)
    c("la flota se abre desde la pantalla de parejas", len(abiertas), 1)
    c("y no cuenta como un cambio del config", model.load_config().names,
      ["notas", "subida"])


# la pantalla de penwatch pinta su estado
with sandbox():
    cfg = preparar()
    tk.Toplevel.wait_window = pulsar("Cerrar")
    try:
        tk_watch.open_dialog(raiz)
        c("la pantalla de penwatch se abre y se cierra", True, True)
    except Exception as e:
        c("la pantalla de penwatch se abre y se cierra", f"{type(e).__name__}: {e}", True)

    tk.Toplevel.wait_window = pulsar("Detectar el dispositivo")
    try:
        tk_watch.open_dialog(raiz)
        c("'Detectar el dispositivo' no revienta", True, True)
    except Exception as e:
        c("'Detectar el dispositivo' no revienta", f"{type(e).__name__}: {e}", True)

# «Qué hace el agente»: se le pide por su buzón, no se escribe
pedidos_modo: list = []
watch.pedir_modo = lambda modo: pedidos_modo.append(modo) or True


def elegir_modo(texto_radio, boton):
    """Devuelve un `wait_window` que elige ese modo y pulsa el botón."""
    def _wait(self, *_a, **_k):
        """Elige el radiobutton, pulsa el botón y vuelve."""
        pila = [self]
        while pila:
            w = pila.pop()
            pila += list(w.winfo_children())
            if isinstance(w, ttk.Radiobutton) and w.cget("text") == texto_radio:
                w.invoke()
        pulsar(boton)(self)
    return _wait


tk.Toplevel.wait_window = elegir_modo(watch.ETIQUETA_AGENTE["sync"], "Aplicar")
c("«Qué hace el agente»: devuelve el modo elegido",
  tk_watch.open_agente(raiz, watch.Resumen("agente", "daemon", True)), "sync")
c("  y se lo pide al agente", pedidos_modo, ["sync"])
tk.Toplevel.wait_window = pulsar("Cancelar")
c("  cancelar no pide nada", (tk_watch.open_agente(
    raiz, watch.Resumen("agente", "daemon", True)), pedidos_modo), (None, ["sync"]))
tk.Toplevel.wait_window = pulsar("Atender")
c("  sin estar en su lista, «Atender» lo añade en daemon",
  tk_watch.open_agente(raiz, watch.Resumen("agente_nueva", "", True)), "daemon")

# «Ajustes → Configuración» de la raíz cifrada de un equipo: la casilla de
# pedir_al_iniciar, que se pide al agente al «Guardar» y solo si ha cambiado.
from ui import prefs, tk_configuracion  # noqa: E402

ajustes_pedidos: list = []
watch.pedir_al_iniciar = lambda: True
watch.pedir_ajuste = lambda clave, valor: ajustes_pedidos.append((clave, valor)) or True


def desmarcar_y(boton):
    """Devuelve un `wait_window` que desmarca la casilla y pulsa `boton`."""
    def _wait(self, *_a, **_k):
        """Desmarca la casilla de la contraseña y pulsa el botón."""
        pila = [self]
        while pila:
            w = pila.pop()
            pila += list(w.winfo_children())
            if isinstance(w, ttk.Checkbutton) and "contraseña" in str(w.cget("text")):
                w.invoke()
        pulsar(boton)(self)
    return _wait


REAL_PREFS = prefs.PREFS
with sandbox():
    cfg = preparar()
    prefs.PREFS = model.STATE_DIR / "ui_prefs.json"
    tk.Toplevel.wait_window = desmarcar_y("Cancelar")
    c("«Configuración» de la raíz cifrada: «Cancelar» no pide nada",
      (tk_configuracion.open_dialog(raiz, cfg), ajustes_pedidos), (False, []))
    tk.Toplevel.wait_window = desmarcar_y("Guardar")
    c("  «Guardar» con la casilla cambiada se lo pide al agente",
      (tk_configuracion.open_dialog(raiz, cfg), ajustes_pedidos),
      (True, [("pedir_al_iniciar", False)]))
    c("  y no escribe el intervalo, que no ha cambiado", prefs.PREFS.exists(), False)
    watch.pedir_al_iniciar = lambda: None
    ajustes_pedidos.clear()
    tk.Toplevel.wait_window = desmarcar_y("Guardar")
    c("  en cualquier otra raíz no está",
      (tk_configuracion.open_dialog(raiz, cfg), ajustes_pedidos), (False, []))

    def escribir_y_guardar(minutos):
        """Devuelve un `wait_window` que escribe esos minutos y pulsa «Guardar»."""
        def _wait(self, *_a, **_k):
            """Escribe en la casilla del intervalo y pulsa «Guardar»."""
            pila = [self]
            while pila:
                w = pila.pop()
                pila += list(w.winfo_children())
                if isinstance(w, ttk.Spinbox):
                    w.set(minutos)
            pulsar("Guardar")(self)
            if self.winfo_exists():
                pulsar("Cancelar")(self)
        return _wait

    errores.clear()
    tk.Toplevel.wait_window = escribir_y_guardar("0")
    c("un intervalo de 0 minutos no se guarda, y se dice por qué",
      (tk_configuracion.open_dialog(raiz, cfg), prefs.PREFS.exists(), errores),
      (False, False, ["El intervalo tiene que ser un número de minutos: 1 o más."]))
    tk.Toplevel.wait_window = escribir_y_guardar("7,5")
    c("  uno con coma decimal sí, y solo el intervalo",
      (tk_configuracion.open_dialog(raiz, cfg), prefs.read_prefs().get("interval_min"),
       "pairs" in prefs.read_prefs()), (True, 7.5, False))
    errores.clear()
prefs.PREFS = REAL_PREFS

# El formulario de instalación ya no pregunta parejas ni intervalo: son los del
# servicio, que viven en el dispositivo. Lo que queda es del equipo: qué hacer al
# enchufar —tres opciones a la vista, no un desplegable—, el sondeo y las raíces.
visto_form: dict = {}


def inspeccionar_y_aceptar(self, *_a, **_k):
    """Apunta los textos y los radios del diálogo y lo acepta."""
    pila, textos, radios = [self], [], []
    while pila:
        w = pila.pop()
        pila += list(w.winfo_children())
        if isinstance(w, ttk.Radiobutton):
            radios.append(str(w.cget("text")))
        elif isinstance(w, ttk.Label):
            textos.append(str(w.cget("text")))
    visto_form.update(textos=textos, radios=sorted(radios))
    pulsar("Instalar")(self)


tk.Toplevel.wait_window = inspeccionar_y_aceptar
opciones = tk_watch.formulario_instalacion(raiz)
c("el vigilante: ni parejas ni intervalo en el formulario",
  [t for t in visto_form["textos"] if t in ("Parejas", "Intervalo del servicio")], [])
c("el vigilante: y dice de dónde salen",
  any("son los del servicio" in t for t in visto_form["textos"]), True)
c("el vigilante: los tres modos, en palabras", visto_form["radios"],
  sorted(watch.MODE_LABELS.values()))
c("el vigilante: lo que devuelve es lo del equipo",
  sorted(opciones), ["extra_roots", "mode", "poll", "start"])


# el editor de flags: se escribe TOML y sale lo que recibirá rclone
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
        """Escribe en los cuadros, pulsa el botón y vuelve."""
        cajas, botones = {}, {}
        pila = [self]
        while pila:
            w = pila.pop()
            pila += list(w.winfo_children())
            if isinstance(w, tk.Text):
                cajas[int(w.grid_info()["row"])] = w
            elif isinstance(w, ttk.Button):
                botones[w.cget("text")] = w
        caja, caja_extra = [cajas[k] for k in sorted(cajas)]
        caja.delete("1.0", "end")
        caja.insert("1.0", texto)
        caja_extra.delete("1.0", "end")
        caja_extra.insert("1.0", extra)
        botones["Ver el efecto"].invoke()
        filas[:] = [self.tabla.filas[i] for i in self.tabla.orden]
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
c("  bajo su título", flags_editor.TITULO_RESERVADO in quejas, True)

datos, _, _ = flags_escritos("transfers = 8", boton="Cancelar")
c("cancelar no devuelve nada", datos, None)

# La tabla del editor es un lienzo y el recuadro rojo se hace una sola vez: los
# widgets del diálogo no dependen de cuántos flags lleve la pareja ni de cuántas
# veces se queje, y quejarse no destruye ni rehace nada.
UNOS_DIEZ = {"transfers": 4, "checksum": True, "fast-list": True, "checkers": 8,
             "order-by": "size", "tpslimit": 5, "retries": 3, "low-level-retries": 5,
             "buffer-size": "32M", "stats": "10s"}


def contar_flags(propios: dict, textos=()):
    """Abre el editor con esos flags, escribe cada texto pulsando «Ver el efecto» y cuenta.

    Returns:
        `(cuentas, conjuntos, recuadros)`: los widgets del diálogo al abrir y tras
        cada texto, el conjunto de nombres de Tk tras cada texto y, tras cada
        uno, los recuadros rojos que hay con si están en la rejilla y las
        etiquetas de cada uno.
    """
    cuentas, conjuntos, recuadros = [], [], []

    def descendientes(raiz_):
        """El widget y todo lo que cuelga de él."""
        pila, salida = [raiz_], []
        while pila:
            w = pila.pop()
            pila += list(w.winfo_children())
            salida.append(w)
        return salida

    def _wait(self, *_a, **_k):
        """Escribe cada texto en el cuadro de flags, pulsa «Ver el efecto» y mira."""
        cajas = {int(w.grid_info()["row"]): w for w in descendientes(self)
                 if isinstance(w, tk.Text)}
        caja = cajas[min(cajas)]
        botones = {w.cget("text"): w for w in descendientes(self) if isinstance(w, ttk.Button)}
        self.update()
        cuentas.append(len(descendientes(self)))
        for texto in textos:
            caja.delete("1.0", "end")
            caja.insert("1.0", texto)
            botones["Ver el efecto"].invoke()
            self.update()
            todos_ = descendientes(self)
            cuentas.append(len(todos_))
            conjuntos.append({str(w) for w in todos_})
            recuadros.append([(bool(w.winfo_manager()),
                               [str(e.cget("text")) for e in descendientes(w)
                                if isinstance(e, ttk.Label) and str(e.cget("text"))])
                              for w in todos_
                              if isinstance(w, ttk.Frame)
                              and str(w.cget("style")) == "NotaRojo.TFrame"])
        botones["Cancelar"].invoke()

    tk.Toplevel.wait_window = _wait
    tk_pairs.flags_form(raiz, "Flags", "de prueba", propios, [], mode_name="bisync",
                        defaults_flags=None)
    return cuentas, conjuntos, recuadros


abiertas = {n: contar_flags(dict(list(UNOS_DIEZ.items())[:n]))[0][0] for n in (0, 3, 10)}
print(f"  (cuenta) widgets del editor de flags con 0, 3 y 10 flags: {abiertas}")
c("el editor de flags tiene los mismos widgets con 0, 3 y 10 flags",
  len(set(abiertas.values())), 1)
c("  y son 34 o menos, tabla incluida", max(abiertas.values()) <= 34, True)
cuentas, conjuntos, recuadros = contar_flags(
    dict(list(UNOS_DIEZ.items())[:3]),
    ["--transfers 8", 'workdir = "otro"', "transfers = 8", "--transfers 8"])
print(f"  (cuenta) con el recuadro rojo: {cuentas}")
c("el recuadro rojo se hace la primera vez que lo escrito no vale",
  ([len(r) for r in recuadros], cuentas[0] < cuentas[1]), ([1, 1, 1, 1], True))
c("  y desde entonces no se crea ni se destruye ningún widget, valga o no lo escrito",
  conjuntos[1] == conjuntos[2] == conjuntos[3] and conjuntos[0] <= conjuntos[1], True)
c("  con el recuadro, el editor sigue en 34 widgets o menos", max(cuentas) <= 34, True)
c("  se ve mientras no vale y se quita cuando vale",
  [r[0][0] for r in recuadros], [True, True, False, True])
c("  y cambia su título y su motivo, no el recuadro",
  (flags_editor.TITULO_NO_VALE in recuadros[0][0][1],
   flags_editor.TITULO_RESERVADO in recuadros[1][0][1],
   flags_editor.TITULO_RESERVADO in recuadros[1][0][1]
   and flags_editor.TITULO_NO_VALE not in recuadros[1][0][1],
   any("no se configura aquí" in t for t in recuadros[1][0][1])),
  (True, True, True, True))


# y el formulario de la pareja recoge lo que diga ese diálogo

tk_pairs.flags_form = lambda *a, **k: {"flags": {"transfers": 8},
                                       "extra_flags": ["--stats", "10s"]}


def _abrir_y_guardar(self, *_a, **_k):
    """Abre el editor de flags de la pareja y guarda."""
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

# el formulario de la pareja: «Vigilar» sigue al modo, como «Versiones»
#
# Solo vale donde el local es origen: al pasar a down la casilla se apaga y se
# desmarca, y lo guardado ya no lleva `watch` (si no, el parseo lo rechazaría).


def _form_vigilar(modo_elegido):
    """Devuelve un `wait_window` que cambia el modo, mira la casilla y guarda."""
    visto: dict = {}

    def _wait(self, *_a, **_k):
        """Pulsa el botón del modo, anota la casilla y pulsa «Guardar…»."""
        pila, botones, modos, casilla = [self], {}, {}, None
        while pila:
            w = pila.pop()
            pila += list(w.winfo_children())
            if isinstance(w, ttk.Button):
                botones[w.cget("text")] = w
            elif isinstance(w, ttk.Radiobutton) and str(w.cget("text")) in model.MODES:
                modos[str(w.cget("text"))] = w
            elif isinstance(w, ttk.Checkbutton) and "ficheros locales" in w.cget("text"):
                casilla = w
        visto["antes"] = (str(casilla.cget("state")), casilla.instate(["selected"]))
        if modo_elegido:
            modos[modo_elegido].invoke()
        visto["despues"] = (str(casilla.cget("state")), casilla.instate(["selected"]))
        botones["Guardar…"].invoke()
    return _wait, visto


vigilada = {"name": "diaria", "local": "sync-data/diaria", "remote_path": "/R/diaria",
            "mode": "up", "watch": True}
espera, visto = _form_vigilar(None)
tk.Toplevel.wait_window = espera
datos = FORMULARIO(raiz, BASE, "notas", dict(vigilada))
c("«Vigilar» abre marcada si la pareja vigila", visto["antes"], ("normal", True))
c("y se guarda marcada", datos["watch"], True)

espera, visto = _form_vigilar("down")
tk.Toplevel.wait_window = espera
datos = FORMULARIO(raiz, BASE, "notas", dict(vigilada))
c("pasar a down apaga y desmarca «Vigilar»", visto["despues"], ("disabled", False))
c("y lo guardado ya no la pide", datos["watch"], False)

espera, visto = _form_vigilar("bisync")
tk.Toplevel.wait_window = espera
datos = FORMULARIO(raiz, BASE, "notas", dict(BASE["pair"][1]))
c("en un modo donde el local es origen la casilla está activa",
  visto["despues"][0], "normal")
c("y apagada por defecto", datos["watch"], False)

# «Versiones»: elegir otra pareja en el desplegable relee esa
#
# Los dos lados se leen aparte (`segundo_plano`, aquí `en_el_acto`) y no por
# `working()`, que solo queda para purgar: este test no purga, así que si
# leer volviera a pasar por ahí, falla en vez de abrir una ventanita.
# El desplegable avisa por `<<ComboboxSelected>>` (un trace sobre la variable
# sobreviviría al widget); lo que se mira es qué pareja lee el diálogo.
leidas: list = []
versions_editor.leer_local = lambda pair: (
    leidas.append(pair.name) or versions_editor.Lado(
        versions_editor.DISPOSITIVO, str(pair.local_abs), True, "", ()))
versions_editor.leer_remoto = lambda pair: versions_editor.Lado(
    versions_editor.REMOTO, pair.versions_path2, True, "", ())


def working_prohibido(*_a, **_k):
    """Un `working()` que no debe llamarse: leer las versiones ya no pasa por él."""
    raise AssertionError("«Versiones» no lee por working()")


tk_versions.working = working_prohibido
ocultar(tk_versions)


def _elegir_pareja(nombre):
    """Devuelve un `wait_window` que pulsa el botón de esa pareja."""
    def _wait(self, *_a, **_k):
        """Pulsa el botón de la pareja, como lo hace quien lo usa."""
        pila = [self]
        while pila:
            w = pila.pop()
            pila += list(w.winfo_children())
            if isinstance(w, ttk.Radiobutton) and str(w.cget("text")) == nombre:
                w.invoke()
                return
    return _wait


with sandbox():
    dos = {"defaults": {"remote": "nas"},
           "pair": [{"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas",
                     "mode": "bisync", "versions": True},
                    {"name": "fotos", "local": "sync-data/fotos", "remote_path": "/R/fotos",
                     "mode": "bisync", "versions": True}]}
    tk.Toplevel.wait_window = _elegir_pareja("fotos")
    tk_versions.open_dialog(raiz, model.parse_config(dos))
    c("«Versiones» lee la primera pareja al abrir y la que se elige después",
      leidas, ["notas", "fotos"])


# «Renombrar el catálogo…», de punta a punta con un remoto de mentira: el botón
# solo renombra si la flota lo permite, y lo que hace se ve en el remoto.
from ui import tk_renombrar  # noqa: E402
import json  # noqa: E402

tk_renombrar.working = working_en_el_acto
ocultar(tk_renombrar)
VIEJO_RAW = {"defaults": {"remote": "nas", "catalog_path": "/prdrive-catalog/pairs.toml"}}
EN_EL_REMOTO: dict = {}


def remoto_de_mentira(args):
    """Lo justo de rclone para renombrar: listar la carpeta y mover."""
    if args[:2] == ["lsjson", "--files-only"]:
        return subprocess.CompletedProcess(args, 0, json.dumps(
            [{"Name": k.rsplit("/", 1)[1], "IsDir": False} for k in EN_EL_REMOTO]), "")
    if args[0] == "moveto" and args[1] in EN_EL_REMOTO:
        EN_EL_REMOTO[args[2]] = EN_EL_REMOTO.pop(args[1])
        return subprocess.CompletedProcess(args, 0, "", "")
    return subprocess.CompletedProcess(args, 1, "", "no esperado")


def pulsar_y_cerrar(texto, vistos):
    """Apunta el estado del botón, lo pulsa y cierra la ventana."""
    def _wait(self, *_a, **_k):
        pila = [self]
        while pila:
            w = pila.pop()
            pila += list(w.winfo_children())
            if isinstance(w, ttk.Button) and w.cget("text") == texto:
                vistos.append(str(w.cget("state")))
                w.invoke()
        self.destroy()
    return _wait


real_run = catalog.run
catalog.run = remoto_de_mentira
try:
    with sandbox():
        EN_EL_REMOTO.clear()
        EN_EL_REMOTO["nas:/prdrive-catalog/pairs.toml"] = "x = 1\n"
        fleet.leer = lambda raw=None: ([fleet.Dispositivo(
            "otro", "el del cajón", "0.5.3", (), "2026-05-01 10:00:00", "ok")], None)
        estados: list[str] = []
        tk.Toplevel.wait_window = pulsar_y_cerrar("Renombrar a remote.toml…", estados)
        tk_renombrar.open_dialog(raiz, dict(VIEJO_RAW))
        c("con un dispositivo de antes en la flota, el botón está apagado", estados,
          ["disabled"])
        c("  y no se ha renombrado nada", sorted(EN_EL_REMOTO),
          ["nas:/prdrive-catalog/pairs.toml"])

        fleet.leer = lambda raw=None: ([fleet.Dispositivo(
            "otro", "el azul", "0.5.4", (), "2026-10-01 10:00:00", "ok",
            entiende=fleet.ENTIENDE)], None)
        estados.clear()
        from common import store  # noqa: E402
        store.write_json(catalog.cache_meta(), {"endpoint": "nas:/prdrive-catalog/pairs.toml"})
        tk_renombrar.open_dialog(raiz, dict(VIEJO_RAW))
        c("con la flota al día, el botón se puede pulsar", estados, ["normal"])
        c("  y renombra en el remoto", sorted(EN_EL_REMOTO),
          ["nas:/prdrive-catalog/remote.toml"])
        c("  y la copia local dice ya que el catálogo es remote.toml",
          catalog.ultimo_leido(), "nas:/prdrive-catalog/remote.toml")
finally:
    catalog.run = real_run
    fleet.leer = lambda raw=None: (list(FLOTA), None)


sys.exit(c.report())
