#!/usr/bin/env python3
"""
tk_install.py — El asistente de instalación de un pen PEREPEN.

Solo dibuja. Lo que decide y lo que toca disco o red está en `install/`, igual
que `tk_pairs.py` no sabe nada de lo que hace `pair_editor.py`.

Es un asistente por pasos y no una ventana única como la de `runsync.py` porque
aquí el orden no es negociable: no se puede elegir parejas antes de saber dónde
va el pen, ni inicializarlas antes de que exista el `sync.py` que las inicializa.
Cada paso tiene una condición, y «Siguiente» no se enciende hasta cumplirla; así
la ventana no deja avanzar a un sitio donde el siguiente botón fallaría.

Las órdenes largas de rclone van a `ui.tk.output_window`, la misma que enseña las
sincronizaciones, para que se vea exactamente lo que hace. Las de VeraCrypt NO:
su línea de órdenes lleva la contraseña, así que van por `ui.tk.working`, que
solo enseña una barra (ver `ui/tk_crypto.py`).
"""

from __future__ import annotations

import sys
from pathlib import Path

from install import CATALOG_PATH, MASTER_PATH, InstallError, InstallState
from install import crypto, device, rclone_bin, remote, seed

from .tk import TITLE, centrar, output_window, working

VENTANA = f"{TITLE} — Instalador"


# ---------------------------------------------------------------------------
# El armazón
# ---------------------------------------------------------------------------

class Wizard:
    """La ventana y por qué paso va. Los pasos solo pintan dentro de `cuerpo`."""

    def __init__(self, root, cuerpo, cabecera, boton_siguiente, boton_atras) -> None:
        self.root = root
        self.cuerpo = cuerpo
        self.cabecera = cabecera
        self.boton_siguiente = boton_siguiente
        self.boton_atras = boton_atras
        self.state = InstallState()
        self.binario: str | None = None
        self.creds: remote.Credentials | None = None
        self.conf: remote.EphemeralConf | None = None
        self.rclone: remote.Rclone | None = None
        self.catalog: remote.Catalog | None = None
        self.indice = 0

    # --- navegación ---------------------------------------------------------

    def repintar(self) -> None:
        for hijo in self.cuerpo.winfo_children():
            hijo.destroy()
        titulo, dibujar, _ = PASOS[self.indice]
        self.cabecera.configure(
            text=f"Paso {self.indice + 1} de {len(PASOS)}   ·   {titulo}")
        dibujar(self.cuerpo, self)
        self.revisar()

    def revisar(self) -> None:
        """Enciende o apaga «Siguiente» según la condición del paso actual."""
        _, _, condicion = PASOS[self.indice]
        ultimo = self.indice == len(PASOS) - 1
        try:
            puede = bool(condicion(self))
        except Exception:
            puede = False
        self.boton_siguiente.configure(
            text="Terminar" if ultimo else "Siguiente >",
            state="normal" if (puede or ultimo) else "disabled")
        self.boton_atras.configure(state="disabled" if self.indice == 0 else "normal")

    def ir(self, delta: int) -> None:
        if self.indice == len(PASOS) - 1 and delta > 0:
            self.root.destroy()
            return
        self.indice = max(0, min(len(PASOS) - 1, self.indice + delta))
        self.repintar()

    # --- atajos que usan varios pasos ---------------------------------------

    @property
    def pen_root(self) -> Path | None:
        return self.state.pen_root

    def error(self, msg: str) -> None:
        from tkinter import messagebox
        messagebox.showerror(TITLE, msg, parent=self.root)

    def aviso(self, msg: str) -> None:
        from tkinter import messagebox
        messagebox.showinfo(TITLE, msg, parent=self.root)


def build(root) -> Wizard:
    """Monta la ventana sobre `root` y devuelve el asistente, sin arrancar nada.

    Está separado de `run_wizard()` para que los tests puedan conducir el
    asistente de verdad —el mismo cableado de botones y condiciones— en vez de
    una reconstrucción a mano que se quedaría desfasada."""
    from tkinter import ttk

    root.title(VENTANA)
    root.resizable(False, False)

    marco = ttk.Frame(root, padding=14)
    marco.grid(sticky="nsew")

    cabecera = ttk.Label(marco, font=("", 11, "bold"))
    cabecera.grid(row=0, column=0, sticky="w")
    ttk.Separator(marco, orient="horizontal").grid(
        row=1, column=0, sticky="ew", pady=(6, 12))

    cuerpo = ttk.Frame(marco, width=820, height=430)
    cuerpo.grid(row=2, column=0, sticky="nw")
    cuerpo.grid_propagate(False)

    ttk.Separator(marco, orient="horizontal").grid(
        row=3, column=0, sticky="ew", pady=(12, 8))
    pie = ttk.Frame(marco)
    pie.grid(row=4, column=0, sticky="ew")

    atras = ttk.Button(pie, text="< Atrás")
    siguiente = ttk.Button(pie, text="Siguiente >")
    atras.grid(row=0, column=0)
    siguiente.grid(row=0, column=1, padx=6)
    ttk.Button(pie, text="Salir", command=root.destroy).grid(row=0, column=3, padx=(20, 0))
    pie.columnconfigure(2, weight=1)

    wiz = Wizard(root, cuerpo, cabecera, siguiente, atras)
    atras.configure(command=lambda: wiz.ir(-1))
    siguiente.configure(command=lambda: wiz.ir(+1))
    wiz.repintar()
    return wiz


def run_wizard() -> int:
    """Abre el asistente. Devuelve 0 siempre que se haya podido abrir."""
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()          # se enseña ya centrada, igual que la ventana principal
    wiz = build(root)
    centrar(root)
    root.deiconify()
    root.mainloop()

    # La clave temporal se borra al cerrar la ventana, no al morir el proceso:
    # el asistente puede estar abierto mucho rato y no hace falta que siga ahí.
    if wiz.conf is not None:
        wiz.conf.close()
    return 0


# ---------------------------------------------------------------------------
# Paso 1 — Comprobaciones
# ---------------------------------------------------------------------------

def _paso_comprobaciones(cuerpo, wiz) -> None:
    from tkinter import ttk

    ttk.Label(cuerpo, justify="left", wraplength=780, text=(
        "Antes de tocar nada: que haya un rclone con el que trabajar, que la "
        "clave del NAS esté disponible, que el NAS conteste y que su catálogo de "
        "parejas se entienda.")).grid(row=0, column=0, sticky="w", pady=(0, 10))

    tabla = ttk.Frame(cuerpo)
    tabla.grid(row=1, column=0, sticky="w")

    def pintar(filas: list[tuple[str, bool | None, str]]) -> None:
        for hijo in tabla.winfo_children():
            hijo.destroy()
        for i, (etiqueta, ok, detalle) in enumerate(filas):
            marca = "…" if ok is None else ("✔" if ok else "✘")
            color = "#666666" if ok is None else ("#116611" if ok else "#993333")
            ttk.Label(tabla, text=marca, foreground=color, width=3).grid(
                row=i, column=0, sticky="w")
            ttk.Label(tabla, text=etiqueta + ":").grid(row=i, column=1, sticky="w")
            ttk.Label(tabla, text=detalle, foreground=color, wraplength=560,
                      justify="left").grid(row=i, column=2, sticky="w", padx=(10, 0))

    def comprobar(descargar: bool = False) -> None:
        filas: list[tuple[str, bool | None, str]] = []

        def trabajo():
            binario = rclone_bin.ensure_rclone(allow_download=descargar)
            creds = remote.load_credentials()
            remote.sweep_stale()
            conf = wiz.conf or remote.EphemeralConf(creds)
            rc = remote.Rclone(str(binario), conf.path)
            rc.check_connection()
            catalogo = remote.pull_catalog(rc)
            return binario, creds, conf, rc, catalogo

        ok, res = working(wiz.root, "comprobando", trabajo,
                          ("Descargando rclone y comprobando el NAS."
                           if descargar else "Comprobando rclone, la clave y el NAS."))
        if not ok:
            binario = rclone_bin.find_rclone()
            filas.append(("rclone", bool(binario), str(binario) if binario else
                          "no hay ninguno en este equipo"))
            filas.append(("Conexión / catálogo", False, str(res)))
            pintar(filas)
            wiz.revisar()
            return

        binario, creds, conf, rc, catalogo = res
        wiz.binario, wiz.creds = str(binario), creds
        wiz.conf, wiz.rclone, wiz.catalog = conf, rc, catalogo

        pintar([
            ("rclone", True, str(binario)),
            ("Clave del NAS", True, creds.origen),
            ("Conexión", True, f"{MASTER_PATH} accesible"),
            ("Catálogo", True, f"{CATALOG_PATH} — {len(catalogo.names)} parejas: "
                               + ", ".join(catalogo.names)),
            _fila_python(),
        ])
        wiz.revisar()

    botones = ttk.Frame(cuerpo)
    botones.grid(row=2, column=0, sticky="w", pady=(14, 0))
    ttk.Button(botones, text="Comprobar", command=lambda: comprobar(False)).grid(
        row=0, column=0)
    ttk.Button(botones, text="Comprobar y descargar rclone si falta",
               command=lambda: comprobar(True)).grid(row=0, column=1, padx=6)

    if wiz.catalog is not None:
        pintar([
            ("rclone", True, str(wiz.binario)),
            ("Clave del NAS", True, wiz.creds.origen if wiz.creds else ""),
            ("Conexión", True, "comprobada"),
            ("Catálogo", True, ", ".join(wiz.catalog.names)),
            _fila_python(),
        ])
    else:
        pintar([("rclone", None, "sin comprobar"),
                ("Clave del NAS", None, "sin comprobar"),
                ("Conexión", None, "sin comprobar"),
                ("Catálogo", None, "sin comprobar")])


def _fila_python() -> tuple[str, bool, str]:
    chk = device.check_python()
    return (chk.etiqueta, chk.ok, chk.detalle)


# ---------------------------------------------------------------------------
# Paso 2 — Destino
# ---------------------------------------------------------------------------

COLUMNAS = [("unidad", "Unidad", 80), ("etiqueta", "Etiqueta", 110),
            ("fs", "Formato", 70), ("tipo", "Tipo", 90),
            ("tam", "Tamaño", 80), ("libre", "Libre", 80),
            ("nota", "", 300)]


def _paso_destino(cuerpo, wiz) -> None:
    import tkinter as tk
    from tkinter import ttk

    ttk.Label(cuerpo, justify="left", wraplength=780, text=(
        "Se listan TODAS las unidades, no solo las que Windows declara "
        "extraíbles: muchos pendrives (y casi todos los SSD por USB) se declaran "
        "fijos, y filtrarlos es la forma más rápida de que el tuyo no aparezca.")
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

    tree = ttk.Treeview(cuerpo, columns=[c[0] for c in COLUMNAS],
                        show="headings", height=8, selectmode="browse")
    for clave, titulo, ancho in COLUMNAS:
        tree.heading(clave, text=titulo)
        tree.column(clave, width=ancho, anchor="w")
    tree.grid(row=1, column=0, sticky="w")

    aviso = ttk.Label(cuerpo, wraplength=780, justify="left")
    aviso.grid(row=2, column=0, sticky="w", pady=(8, 0))

    volumenes: dict[str, device.Volume] = {}

    def refrescar() -> None:
        tree.delete(*tree.get_children())
        volumenes.clear()
        for vol in device.list_volumes():
            clave = str(vol.root)
            volumenes[clave] = vol
            tree.insert("", "end", iid=clave, values=(
                clave, vol.label, vol.filesystem, vol.drive_type,
                f"{vol.size_gb:g} GB", f"{vol.free_gb:g} GB", vol.nota))
        if wiz.state.device and str(wiz.state.device) in volumenes:
            tree.selection_set(str(wiz.state.device))
        mostrar()

    def elegido() -> device.Volume | None:
        sel = tree.selection()
        return volumenes.get(sel[0]) if sel else None

    def mostrar(*_) -> None:
        vol = elegido()
        if vol is None:
            aviso.configure(text="Elige una unidad de la lista, o escribe una ruta "
                                 "abajo.", foreground="#666666")
            wiz.state.device = None
        elif vol.is_system:
            aviso.configure(text="✘ Esa es la unidad del SISTEMA. No.",
                            foreground="#993333")
            wiz.state.device = None
        else:
            wiz.state.device = vol.root
            aviso.configure(
                text=f"✔ Destino: {vol.root}" + (f"  ({vol.nota})" if vol.nota else ""),
                foreground="#116611")
        wiz.revisar()

    tree.bind("<<TreeviewSelect>>", mostrar)

    manual = ttk.Frame(cuerpo)
    manual.grid(row=3, column=0, sticky="w", pady=(12, 0))
    ttk.Label(manual, text="…o una ruta a mano:").grid(row=0, column=0, sticky="w")
    ruta = tk.StringVar()
    ttk.Entry(manual, textvariable=ruta, width=46).grid(row=0, column=1, padx=6)

    def usar_ruta() -> None:
        texto = ruta.get().strip()
        if not texto:
            return
        destino = Path(texto)
        if not destino.is_dir():
            wiz.error(f"No existe la carpeta {destino}.")
            return
        vol = device.volume_for(destino)
        if vol.is_system:
            wiz.error("Esa es la unidad del sistema.")
            return
        wiz.state.device = destino
        aviso.configure(text=f"✔ Destino: {destino}", foreground="#116611")
        tree.selection_remove(*tree.selection())
        wiz.revisar()

    ttk.Button(manual, text="Usar esta ruta", command=usar_ruta).grid(row=0, column=2)
    ttk.Button(manual, text="Actualizar lista", command=refrescar).grid(
        row=0, column=3, padx=(16, 0))

    refrescar()


# ---------------------------------------------------------------------------
# Paso 3 — Cifrado (vive en ui/tk_crypto.py)
# ---------------------------------------------------------------------------

def _paso_cifrado(cuerpo, wiz) -> None:
    from . import tk_crypto
    tk_crypto.dibujar(cuerpo, wiz)


# ---------------------------------------------------------------------------
# Paso 4 — Siembra
# ---------------------------------------------------------------------------

def _paso_siembra(cuerpo, wiz) -> None:
    import tkinter as tk
    from tkinter import ttk

    raiz = wiz.pen_root
    ttk.Label(cuerpo, justify="left", wraplength=780, text=(
        f"Se copiará el pen maestro del NAS a tu pen:\n\n"
        f"    {MASTER_PATH}   →   {raiz}\n\n"
        "Esto es lo que trae rclone-sync/ entero: el código, el binario de "
        "rclone, la clave del NAS y su rclone.conf.")).grid(
        row=0, column=0, sticky="w")

    try:
        situacion, explicacion = device.seed_target(raiz)
    except InstallError as e:
        ttk.Label(cuerpo, foreground="#993333", wraplength=780, justify="left",
                  text=str(e)).grid(row=1, column=0, sticky="w", pady=(10, 0))
        return

    colores = {device.VACIO: "#116611", device.PEREPEN_YA: "#116611",
               device.AJENO: "#993333"}
    ttk.Label(cuerpo, foreground=colores[situacion], wraplength=780, justify="left",
              text=explicacion).grid(row=1, column=0, sticky="w", pady=(10, 0))

    ttk.Label(cuerpo, foreground="#775500", wraplength=780, justify="left", text=(
        "La siembra es un ESPEJO (rclone sync): borra en el destino lo que no "
        f"esté en el NAS, con --max-delete como único freno. Por eso primero se "
        "simula.")).grid(row=2, column=0, sticky="w", pady=(10, 0))

    confirmado = {"vale": situacion != device.AJENO}
    if situacion == device.AJENO:
        marco = ttk.Frame(cuerpo)
        marco.grid(row=3, column=0, sticky="w", pady=(10, 0))
        ttk.Label(marco, text=f"Para seguir, escribe la ruta «{raiz}»:").grid(
            row=0, column=0, sticky="w")
        escrito = tk.StringVar()
        ttk.Entry(marco, textvariable=escrito, width=44).grid(row=0, column=1, padx=6)

        def revisar_texto(*_):
            confirmado["vale"] = escrito.get().strip().rstrip("\\/") == \
                str(raiz).rstrip("\\/")
            botones_estado()
        escrito.trace_add("write", revisar_texto)

    estado_lbl = ttk.Label(cuerpo, wraplength=780, justify="left", foreground="#666666")
    estado_lbl.grid(row=4, column=0, sticky="w", pady=(12, 0))

    def sembrar(dry: bool) -> None:
        if not dry and not confirmado["vale"]:
            return
        if not dry and not wiz.state.seed_simulated:
            wiz.aviso("Simula primero: el dry-run es lo que te dice qué se va a "
                      "borrar antes de que se borre.")
            return
        cmd = seed.seed_command(wiz.rclone, wiz.catalog, raiz, dry_run=dry)
        rc = output_window("siembra (simulación)" if dry else "siembra",
                           cmd, parent=wiz.root)
        if rc != 0:
            estado_lbl.configure(text=f"La siembra terminó con código {rc}. "
                                      "Revisa la salida.", foreground="#993333")
            return
        if dry:
            wiz.state.seed_simulated = True
            estado_lbl.configure(text="Simulación correcta. Ya se puede sembrar "
                                      "de verdad.", foreground="#116611")
        else:
            wiz.state.seeded = True
            # El PEREPEN que llega con la siembra trae el id del pen de origen:
            # sin renovarlo, dos pens distintos dirían ser el mismo.
            try:
                nuevo = device.ensure_control_file(raiz, renew=True)
                extra = f" Identificador del pen renovado ({nuevo[:8]}…)."
            except InstallError as e:
                extra = f" Aviso: no he podido renovar el fichero PEREPEN ({e})."
            estado_lbl.configure(text="Pen sembrado." + extra, foreground="#116611")
        botones_estado()
        wiz.revisar()

    botones = ttk.Frame(cuerpo)
    botones.grid(row=5, column=0, sticky="w", pady=(14, 0))
    b_dry = ttk.Button(botones, text="Simular (--dry-run)",
                       command=lambda: sembrar(True))
    b_real = ttk.Button(botones, text="Sembrar de verdad",
                        command=lambda: sembrar(False))
    b_dry.grid(row=0, column=0)
    b_real.grid(row=0, column=1, padx=6)

    def botones_estado() -> None:
        b_real.configure(state="normal" if (confirmado["vale"] and
                                            wiz.state.seed_simulated) else "disabled")

    if seed.sync_py(raiz).is_file():
        estado_lbl.configure(
            text="Este pen ya tiene rclone-sync/: puedes sembrar para "
                 "actualizarlo, o seguir al paso siguiente.", foreground="#116611")
    botones_estado()


# ---------------------------------------------------------------------------
# Paso 5 — Parejas y config
# ---------------------------------------------------------------------------

def _paso_parejas(cuerpo, wiz) -> None:
    import tkinter as tk
    from tkinter import ttk

    ttk.Label(cuerpo, justify="left", wraplength=780, text=(
        "Qué carpetas va a sincronizar ESTE pen. El catálogo es global; el "
        "sync_config.toml que se escribe aquí es solo de este dispositivo.")).grid(
        row=0, column=0, sticky="w", pady=(0, 10))

    marco = ttk.Frame(cuerpo)
    marco.grid(row=1, column=0, sticky="w")
    elegidas: dict[str, tk.BooleanVar] = {}
    for i, pareja in enumerate(wiz.catalog.pairs):
        nombre = pareja.get("name", "")
        modo = pareja.get("mode", "bisync")
        var = tk.BooleanVar(value=nombre in wiz.state.selected or not wiz.state.selected)
        elegidas[nombre] = var
        ttk.Checkbutton(marco, variable=var, text=f"{nombre}   [{modo}]").grid(
            row=i, column=0, sticky="w")
        ttk.Label(marco, foreground="#666666",
                  text=f"{pareja.get('local', '?')}  ↔  {pareja.get('remote_path', '?')}"
                  ).grid(row=i, column=1, sticky="w", padx=(16, 0))
        if modo in ("up-mirror", "down-mirror"):
            destino = "el NAS" if modo == "up-mirror" else "el pen"
            ttk.Label(marco, foreground="#993333", wraplength=260, justify="left",
                      text=f"espejo: borra en {destino} lo que no esté en el origen"
                      ).grid(row=i, column=2, sticky="w", padx=(12, 0))

    resultado = ttk.Label(cuerpo, wraplength=780, justify="left", foreground="#666666")
    resultado.grid(row=2, column=0, sticky="w", pady=(14, 0))

    def guardar() -> None:
        seleccion = [n for n, v in elegidas.items() if v.get()]
        try:
            destino = seed.write_device_config(wiz.pen_root, wiz.catalog, seleccion)
            creadas = seed.make_local_dirs(wiz.pen_root, wiz.catalog, seleccion)
        except InstallError as e:
            wiz.error(str(e))
            return
        except Exception as e:                       # noqa: BLE001
            wiz.error(f"{type(e).__name__}: {e}")
            return
        wiz.state.selected = seleccion
        wiz.state.config_written = True
        detalle = f"Escrito {destino} con {len(seleccion)} pareja(s)."
        if creadas:
            detalle += "\nCarpetas creadas: " + ", ".join(p.name for p in creadas)
        resultado.configure(text=detalle, foreground="#116611")
        wiz.revisar()

    ttk.Button(cuerpo, text="Guardar el config y crear las carpetas",
               command=guardar).grid(row=3, column=0, sticky="w", pady=(12, 0))


# ---------------------------------------------------------------------------
# Paso 6 — Inicialización
# ---------------------------------------------------------------------------

def _paso_inicializar(cuerpo, wiz) -> None:
    from tkinter import ttk

    bisync = seed.resync_targets(wiz.catalog, wiz.state.selected)
    espejos = seed.mirror_pairs(wiz.catalog, wiz.state.selected)

    ttk.Label(cuerpo, justify="left", wraplength=780, text=(
        "Una pareja bisync necesita un --resync la primera vez: es lo que compara "
        "los dos lados y fija la referencia. No borra por diferencias.")).grid(
        row=0, column=0, sticky="w", pady=(0, 10))

    tabla = ttk.Frame(cuerpo)
    tabla.grid(row=1, column=0, sticky="w")
    for i, (izq, der) in enumerate(seed.summary(wiz.catalog, wiz.state.selected)):
        ttk.Label(tabla, text=izq).grid(row=i, column=0, sticky="w")
        ttk.Label(tabla, text=der, foreground="#666666").grid(
            row=i, column=1, sticky="w", padx=(14, 0))

    if espejos:
        ttk.Label(cuerpo, foreground="#993333", wraplength=780, justify="left", text=(
            "No se inicializan aquí: " + ", ".join(espejos) + ".\n"
            "Son espejos, y 'perepen' lo es del pen ENTERO hacia el NAS: lanzarla "
            "con el pen a medio hacer propagaría eso al maestro. Cuando el pen "
            "esté como quieres, pruébala a mano con --dry-run.")).grid(
            row=2, column=0, sticky="w", pady=(12, 0))

    resultado = ttk.Label(cuerpo, wraplength=780, justify="left", foreground="#666666")
    resultado.grid(row=3, column=0, sticky="w", pady=(12, 0))

    def inicializar() -> None:
        try:
            cmd = seed.resync_command(wiz.pen_root, bisync)
        except InstallError as e:
            wiz.error(str(e))
            return
        rc = output_window("inicializar las parejas", cmd, parent=wiz.root)
        wiz.state.initialized = rc == 0
        resultado.configure(
            text="Parejas inicializadas." if rc == 0 else
                 f"Terminó con código {rc}: mira la salida. Se puede reintentar, "
                 "o hacerlo luego desde el pen.",
            foreground="#116611" if rc == 0 else "#993333")

    boton = ttk.Button(cuerpo, text="Inicializar ahora", command=inicializar)
    boton.grid(row=4, column=0, sticky="w", pady=(12, 0))
    if not bisync:
        boton.configure(state="disabled")
        resultado.configure(text="Ninguna de las parejas elegidas necesita "
                                 "inicialización.")


# ---------------------------------------------------------------------------
# Paso 7 — Verificación y cierre
# ---------------------------------------------------------------------------

def _paso_final(cuerpo, wiz) -> None:
    from tkinter import ttk

    ttk.Label(cuerpo, justify="left", wraplength=780, text=(
        "Lo que de verdad hace falta para que este pen arranque en cualquier "
        "equipo. Lo que falte aquí es lo que fallaría luego sin que se entienda "
        "por qué.")).grid(row=0, column=0, sticky="w", pady=(0, 10))

    tabla = ttk.Frame(cuerpo)
    tabla.grid(row=1, column=0, sticky="w")

    def revisar_pen() -> None:
        for hijo in tabla.winfo_children():
            hijo.destroy()
        for i, chk in enumerate(device.verify_pen(wiz.pen_root, wiz.state.selected)):
            color = "#116611" if chk.ok else "#993333"
            ttk.Label(tabla, text="✔" if chk.ok else "✘", foreground=color,
                      width=3).grid(row=i, column=0, sticky="w")
            ttk.Label(tabla, text=chk.etiqueta + ":").grid(row=i, column=1, sticky="w")
            ttk.Label(tabla, text=chk.detalle, foreground=color, wraplength=520,
                      justify="left").grid(row=i, column=2, sticky="w", padx=(10, 0))

    revisar_pen()

    extras = ttk.LabelFrame(cuerpo, text="Y ya que estamos", padding=10)
    extras.grid(row=2, column=0, sticky="w", pady=(14, 0))

    def instalar_vigilante() -> None:
        try:
            cmd = seed.penwatch_install_command(wiz.pen_root)
        except InstallError as e:
            wiz.error(str(e))
            return
        output_window("instalar el vigilante", cmd, parent=wiz.root)

    def registrar_favorito() -> None:
        if wiz.state.encryption != "veracrypt" or not wiz.state.container:
            wiz.error("Esto solo tiene sentido con un contenedor VeraCrypt.")
            return
        letra = str(wiz.pen_root)[0] if wiz.pen_root else ""
        try:
            hechos = crypto.write_favorite(wiz.state.container, letra)
        except InstallError as e:
            wiz.error(str(e))
            return
        wiz.aviso("\n".join(hechos) + (
            "\n\nConfírmalo en VeraCrypt > Favoritos > Organizar volúmenes "
            "favoritos: es la configuración de otra aplicación y su formato "
            "cambia entre versiones.\n\nY ojo con lo que avisa su propia "
            f"documentación: si la letra {letra}: está ocupada cuando conectes el "
            "pen, VeraCrypt NO monta y NO dice nada."))

    def desmontar() -> None:
        if not (wiz.state.mounted_by_us and wiz.state.veracrypt and wiz.pen_root):
            wiz.error("Este instalador no ha montado ningún contenedor.")
            return
        try:
            crypto.dismount(wiz.state.veracrypt, wiz.pen_root)
        except InstallError as e:
            wiz.error(str(e))
            return
        wiz.state.mounted_by_us = False
        wiz.aviso("Contenedor desmontado. Ya puedes extraer el pen.")

    for i, (texto, accion) in enumerate((
            ("Instalar el arranque automático (penwatch)", instalar_vigilante),
            ("Que VeraCrypt monte al conectar", registrar_favorito),
            ("Desmontar el contenedor", desmontar),
            ("Volver a comprobar", revisar_pen))):
        ttk.Button(extras, text=texto, command=accion).grid(
            row=i // 2, column=i % 2, sticky="w", padx=(0, 8), pady=2)


# ---------------------------------------------------------------------------
# Los pasos, en orden, con la condición para poder salir de cada uno
# ---------------------------------------------------------------------------

def _ok_comprobaciones(w) -> bool:
    return w.rclone is not None and w.catalog is not None


def _ok_destino(w) -> bool:
    return w.state.device is not None


def _ok_cifrado(w) -> bool:
    return w.state.pen_root is not None


def _ok_siembra(w) -> bool:
    return w.state.seeded or seed.sync_py(w.pen_root).is_file()


def _ok_parejas(w) -> bool:
    return w.state.config_written


PASOS = [
    ("Comprobaciones", _paso_comprobaciones, _ok_comprobaciones),
    ("Destino", _paso_destino, _ok_destino),
    ("Cifrado", _paso_cifrado, _ok_cifrado),
    ("Siembra", _paso_siembra, _ok_siembra),
    ("Parejas y configuración", _paso_parejas, _ok_parejas),
    ("Inicialización", _paso_inicializar, lambda w: True),
    ("Verificación", _paso_final, lambda w: True),
]


if __name__ == "__main__":          # pragma: no cover - atajo para probar a mano
    sys.exit(run_wizard())
