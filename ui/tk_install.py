#!/usr/bin/env python3
"""
tk_install.py — El asistente de instalación de un dispositivo prdrive.

Solo dibuja. Lo que decide y lo que toca disco o red está en `install/`, igual
que `tk_pairs.py` no sabe nada de lo que hace `pair_editor.py`.

Es un asistente por pasos y no una ventana única como la de `runsync.py` porque
aquí el orden no es negociable: no se puede leer el catálogo antes de saber con
qué remoto se habla, ni elegir parejas antes de saber dónde va el dispositivo, ni
inicializarlas antes de que exista el `sync.py` que las inicializa. Cada paso
tiene una condición, y «Siguiente» no se enciende hasta cumplirla; así la ventana
no deja avanzar a un sitio donde el siguiente botón fallaría.

Las órdenes largas de rclone van a `ui.tk.output_window`, la misma que enseña las
sincronizaciones, para que se vea exactamente lo que hace. Las de VeraCrypt NO:
su línea de órdenes lleva la contraseña, así que van por `ui.tk.working`, que
solo enseña una barra (ver `ui/tk_crypto.py`). La instalación del código también
va por `working()`: es una copia de ficheros que tarda —el binario de rclone son
decenas de megas— y cuya salida no le dice nada a nadie.
"""

from __future__ import annotations

import sys
from pathlib import Path

from install import InstallError, InstallState
from install import crypto, deploy, device, profile, rclone_bin, remote

from . import icons, theme
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
        # El perfil de partida: el incrustado en el .exe, el del checkout, o uno
        # vacío. Que esté vacío NO es un error, es el arranque normal de quien se
        # acaba de bajar el proyecto.
        self.perfil: profile.Profile = profile.load()
        # El perfil de arriba es con el que habla el INSTALADOR. El que se le
        # escribe al dispositivo puede no ser el mismo: el catálogo manda sobre
        # el nombre del remote, porque es el que usan sus remote_path. Ver
        # `profile.align_with_catalog`.
        self.perfil_device: profile.Profile | None = None
        self.notas_perfil: list[str] = []
        self.binario: str | None = None
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
    def device_root(self) -> Path | None:
        return self.state.device_root

    @property
    def perfil_final(self) -> profile.Profile:
        """El que acaba dentro del dispositivo."""
        return self.perfil_device or self.perfil

    def soltar_conexion(self) -> None:
        """Tira el conf efímero y lo que colgaba de él.

        Se llama al cambiar el perfil: el `rclone.conf` temporal lleva dentro la
        conexión anterior, y quedarse con él significaría comprobar una cosa y
        conectarse a otra."""
        if self.conf is not None:
            self.conf.close()
        self.conf = self.rclone = self.catalog = None
        self.perfil_device, self.notas_perfil = None, []

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

    theme.apply(root)
    icons.poner_icono(root)
    root.title(VENTANA)
    root.configure(background=theme.PAPEL)
    root.resizable(False, False)

    marco = ttk.Frame(root, padding=(20, 18, 20, 16))
    marco.grid(sticky="nsew")

    cabecera = ttk.Label(marco, style="Dialogo.TLabel")
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
    siguiente = ttk.Button(pie, text="Siguiente >", style="Primary.TButton")
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
# Paso 1 — Conexión
# ---------------------------------------------------------------------------

def _paso_conexion(cuerpo, wiz) -> None:
    """Con qué remoto se habla. Es lo primero porque de él sale todo lo demás.

    Dos caminos, y los dos hacen falta: quien ya usa rclone tiene su remote
    montado y solo quiere señalarlo, y quien empieza de cero necesita el
    formulario. Las opciones del backend se escriben tal cual irán al
    rclone.conf, en vez de inventarse un campo por backend: rclone tiene decenas
    y este proyecto no interpreta ninguna."""
    import tkinter as tk
    from tkinter import filedialog, ttk

    ttk.Label(cuerpo, justify="left", wraplength=780, text=(
        "Dónde guardas tu configuración y tus datos. prdrive no sabe de ningún "
        "servidor concreto: vale cualquier remote de rclone.")).grid(
        row=0, column=0, sticky="w", pady=(0, 10))

    modo = tk.StringVar(value="nuevo")
    nombre = tk.StringVar(value=wiz.perfil.remote_name or profile.DEFAULT_REMOTE_NAME)
    tipo = tk.StringVar(value=wiz.perfil.options.get("type", "sftp"))
    clave = tk.StringVar()
    conocidos = tk.StringVar()
    conf_ajeno = tk.StringVar()
    remoto_ajeno = tk.StringVar()
    catalogo = tk.StringVar(value=wiz.perfil.catalog_path)

    elector = ttk.Frame(cuerpo)
    elector.grid(row=1, column=0, sticky="w")
    ttk.Radiobutton(elector, text="Configurar un remoto nuevo", value="nuevo",
                    variable=modo).grid(row=0, column=0, sticky="w")
    ttk.Radiobutton(elector, text="Importar de un rclone.conf que ya tengo",
                    value="importar", variable=modo).grid(row=0, column=1,
                                                          sticky="w", padx=(24, 0))

    caja = ttk.Frame(cuerpo)
    caja.grid(row=2, column=0, sticky="w", pady=(10, 0))

    # --- formulario de remoto nuevo ---
    nuevo = ttk.Frame(caja)
    ttk.Label(nuevo, text="Nombre del remote:", style="Campo.TLabel").grid(
        row=0, column=0, sticky="w")
    ttk.Entry(nuevo, textvariable=nombre, width=18).grid(row=0, column=1, sticky="w",
                                                         padx=(6, 16))
    ttk.Label(nuevo, text="Tipo:", style="Campo.TLabel").grid(row=0, column=2, sticky="w")
    combo_tipo = ttk.Combobox(nuevo, textvariable=tipo, width=12,
                              values=sorted(profile.PLANTILLAS))
    combo_tipo.grid(row=0, column=3, sticky="w", padx=(6, 6))

    ttk.Label(nuevo, text="Opciones (una por línea, como en rclone.conf):",
              style="Campo.TLabel").grid(row=1, column=0, columnspan=4,
                                         sticky="w", pady=(10, 2))
    opciones = tk.Text(nuevo, width=62, height=6, font=theme.fuente("mono"),
                       background=theme.SUPERFICIE, foreground=theme.TINTA,
                       relief="solid", borderwidth=1, highlightthickness=0)
    opciones.grid(row=2, column=0, columnspan=4, sticky="w")
    inicial = (profile.dump_options(wiz.perfil).replace(f"type = {tipo.get()}\n", "")
               if wiz.perfil.options else profile.PLANTILLAS.get(tipo.get(), ""))
    opciones.insert("1.0", inicial)

    def plantilla() -> None:
        """Rellena la caja con los campos típicos del backend elegido.

        Solo con la caja vacía: pisar lo que alguien acaba de escribir por haber
        rozado el desplegable sería justo lo que no se espera."""
        if opciones.get("1.0", "end").strip():
            wiz.aviso("Vacía primero la caja de opciones: no piso lo que ya has "
                      "escrito.")
            return
        opciones.insert("1.0", profile.PLANTILLAS.get(tipo.get(), ""))

    ttk.Button(nuevo, text="Rellenar con la plantilla", command=plantilla).grid(
        row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def _fichero(destino: tk.StringVar, titulo: str) -> None:
        elegido = filedialog.askopenfilename(parent=wiz.root, title=titulo)
        if elegido:
            destino.set(elegido)

    ttk.Label(nuevo, text="Clave privada:", style="Campo.TLabel").grid(
        row=4, column=0, sticky="w", pady=(10, 0))
    ttk.Entry(nuevo, textvariable=clave, width=44).grid(row=4, column=1, columnspan=2,
                                                        sticky="w", padx=(6, 6),
                                                        pady=(10, 0))
    ttk.Button(nuevo, text="Examinar…",
               command=lambda: _fichero(clave, "La clave privada")).grid(
        row=4, column=3, sticky="w", pady=(10, 0))

    ttk.Label(nuevo, text="known_hosts:", style="Campo.TLabel").grid(
        row=5, column=0, sticky="w", pady=(4, 0))
    ttk.Entry(nuevo, textvariable=conocidos, width=44).grid(
        row=5, column=1, columnspan=2, sticky="w", padx=(6, 6), pady=(4, 0))
    ttk.Button(nuevo, text="Examinar…",
               command=lambda: _fichero(conocidos, "El known_hosts")).grid(
        row=5, column=3, sticky="w", pady=(4, 0))
    ttk.Label(nuevo, style="Pista.TLabel", wraplength=520, justify="left", text=(
        "Los dos son opcionales: un backend con contraseña o con token no los "
        "usa. Sin known_hosts se acepta la clave del servidor a la primera.")
        ).grid(row=6, column=0, columnspan=4, sticky="w", pady=(4, 0))

    # --- importar de un rclone.conf ---
    importar = ttk.Frame(caja)
    ttk.Label(importar, text="Fichero rclone.conf:", style="Campo.TLabel").grid(
        row=0, column=0, sticky="w")
    ttk.Entry(importar, textvariable=conf_ajeno, width=52).grid(
        row=0, column=1, sticky="w", padx=(6, 6))

    combo_remoto = ttk.Combobox(importar, textvariable=remoto_ajeno, width=24,
                                state="readonly")

    def elegir_conf() -> None:
        elegido = filedialog.askopenfilename(
            parent=wiz.root, title="Tu rclone.conf",
            filetypes=[("rclone.conf", "*.conf"), ("Todos", "*.*")])
        if not elegido:
            return
        conf_ajeno.set(elegido)
        cargar_remotos()

    def cargar_remotos() -> None:
        try:
            nombres = profile.remotes_in(conf_ajeno.get())
        except InstallError as e:
            wiz.error(str(e))
            return
        if not nombres:
            wiz.error("Ese fichero no define ningún remote.")
            return
        combo_remoto.configure(values=nombres)
        remoto_ajeno.set(nombres[0])

    ttk.Button(importar, text="Examinar…", command=elegir_conf).grid(
        row=0, column=2, sticky="w")
    ttk.Label(importar, text="Remote:", style="Campo.TLabel").grid(
        row=1, column=0, sticky="w", pady=(10, 0))
    combo_remoto.grid(row=1, column=1, sticky="w", padx=(6, 6), pady=(10, 0))
    ttk.Label(importar, style="Pista.TLabel", wraplength=560, justify="left", text=(
        "Se copia la definición del remote y, si usa fichero de clave, también la "
        "clave: el dispositivo tiene que llevar la suya para funcionar en "
        "cualquier equipo.")).grid(row=2, column=0, columnspan=3, sticky="w",
                                   pady=(6, 0))

    def cambiar_modo(*_) -> None:
        nuevo.grid_forget()
        importar.grid_forget()
        (nuevo if modo.get() == "nuevo" else importar).grid(row=0, column=0, sticky="w")
    modo.trace_add("write", cambiar_modo)
    cambiar_modo()

    # --- común ---
    comun = ttk.Frame(cuerpo)
    comun.grid(row=3, column=0, sticky="w", pady=(12, 0))
    ttk.Label(comun, text="Ruta del catálogo en el remoto:",
              style="Campo.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Entry(comun, textvariable=catalogo, width=46).grid(row=0, column=1,
                                                           sticky="w", padx=(6, 0))

    estado = ttk.Label(cuerpo, wraplength=780, justify="left", style="Pista.TLabel")
    estado.grid(row=5, column=0, sticky="w", pady=(12, 0))

    def usar() -> None:
        try:
            if modo.get() == "nuevo":
                texto = opciones.get("1.0", "end")
                opts = profile.parse_options(texto)
                opts["type"] = tipo.get().strip()
                perfil = profile.from_form(
                    nombre.get(), opts,
                    key_path=clave.get().strip() or None,
                    known_path=conocidos.get().strip() or None,
                    catalog_path=catalogo.get().strip())
            else:
                if not remoto_ajeno.get():
                    wiz.error("Elige cuál de los remotes de ese fichero quieres.")
                    return
                perfil = profile.from_rclone_conf(
                    conf_ajeno.get(), remoto_ajeno.get(),
                    catalog_path=catalogo.get().strip())
        except InstallError as e:
            wiz.error(str(e))
            return

        wiz.soltar_conexion()          # el conf efímero anterior ya no vale
        wiz.perfil = perfil
        estado.configure(text=f"✔ {perfil.describe()}   ·   catálogo en "
                              f"{perfil.endpoint_catalog}", style="Ok.TLabel")
        wiz.revisar()

    ttk.Button(cuerpo, text="Usar esta conexión", command=usar).grid(
        row=4, column=0, sticky="w", pady=(12, 0))

    if wiz.perfil.configured:
        estado.configure(
            text=f"✔ {wiz.perfil.describe()}   ·   catálogo en "
                 f"{wiz.perfil.endpoint_catalog}\n{wiz.perfil.origen}",
            style="Ok.TLabel")


# ---------------------------------------------------------------------------
# Paso 2 — Comprobaciones
# ---------------------------------------------------------------------------

def _paso_comprobaciones(cuerpo, wiz) -> None:
    from tkinter import ttk

    ttk.Label(cuerpo, justify="left", wraplength=780, text=(
        "Antes de tocar nada: que haya un rclone con el que trabajar, que el "
        "remoto conteste y que su catálogo de parejas se entienda.")).grid(
        row=0, column=0, sticky="w", pady=(0, 10))

    tabla = ttk.Frame(cuerpo)
    tabla.grid(row=1, column=0, sticky="w")

    def pintar(filas: list[tuple[str, bool | None, str]]) -> None:
        for hijo in tabla.winfo_children():
            hijo.destroy()
        for i, (etiqueta, ok, detalle) in enumerate(filas):
            marca = "…" if ok is None else ("✔" if ok else "✘")
            color = theme.TINTA3 if ok is None else (theme.OK if ok else theme.PELIGRO)
            ttk.Label(tabla, text=marca, foreground=color, width=3).grid(
                row=i, column=0, sticky="w")
            ttk.Label(tabla, text=etiqueta + ":").grid(row=i, column=1, sticky="w")
            ttk.Label(tabla, text=detalle, foreground=color, wraplength=560,
                      justify="left").grid(row=i, column=2, sticky="w", padx=(10, 0))

    def comprobar(descargar: bool = False) -> None:
        filas: list[tuple[str, bool | None, str]] = []
        perfil = wiz.perfil

        def trabajo():
            binario = rclone_bin.ensure_rclone(allow_download=descargar)
            remote.sweep_stale()
            conf = wiz.conf or remote.EphemeralConf(perfil)
            rc = remote.Rclone(str(binario), conf.path,
                               remote_name=perfil.remote_name)
            rc.check_connection()
            catalogo = remote.pull_catalog(rc, perfil.catalog_path)
            return binario, conf, rc, catalogo

        ok, res = working(wiz.root, "comprobando", trabajo,
                          ("Descargando rclone y comprobando el remoto."
                           if descargar else "Comprobando rclone y el remoto."))
        if not ok:
            binario = rclone_bin.find_rclone()
            filas.append(("rclone", bool(binario), str(binario) if binario else
                          "no hay ninguno en este equipo"))
            filas.append(("Conexión / catálogo", False, str(res)))
            pintar(filas)
            wiz.revisar()
            return

        binario, conf, rc, catalogo = res
        wiz.binario = str(binario)
        wiz.conf, wiz.rclone, wiz.catalog = conf, rc, catalogo
        wiz.perfil_device, wiz.notas_perfil = profile.align_with_catalog(
            perfil, catalogo.raw)

        filas = [
            ("rclone", True, str(binario)),
            ("Conexión", True, f"{perfil.describe()} — {perfil.origen}"),
            ("Catálogo", True, f"{perfil.endpoint_catalog} — "
                               f"{len(catalogo.names)} parejas: "
                               + ", ".join(catalogo.names)),
            _fila_python(),
        ]
        # Si el catálogo manda otra cosa, se dice aquí y no al final: es el
        # momento en que todavía se puede volver atrás y cambiarlo.
        for nota in wiz.notas_perfil:
            filas.append(("Según el catálogo", True, nota))
        pintar(filas)
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
            ("Conexión", True, wiz.perfil.describe()),
            ("Catálogo", True, ", ".join(wiz.catalog.names)),
            _fila_python(),
        ])
    else:
        pintar([("rclone", None, "sin comprobar"),
                ("Conexión", None, wiz.perfil.describe()),
                ("Catálogo", None, "sin comprobar")])


def _fila_python() -> tuple[str, bool, str]:
    chk = device.check_python()
    return (chk.etiqueta, chk.ok, chk.detalle)


# ---------------------------------------------------------------------------
# Paso 3 — Destino
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
                                 "abajo.", foreground=theme.TINTA3)
            wiz.state.device = None
        elif vol.is_system:
            aviso.configure(text="✘ Esa es la unidad del SISTEMA. No.",
                            foreground=theme.PELIGRO)
            wiz.state.device = None
        else:
            wiz.state.device = vol.root
            aviso.configure(
                text=f"✔ Destino: {vol.root}" + (f"  ({vol.nota})" if vol.nota else ""),
                foreground=theme.OK)
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
        aviso.configure(text=f"✔ Destino: {destino}", foreground=theme.OK)
        tree.selection_remove(*tree.selection())
        wiz.revisar()

    ttk.Button(manual, text="Usar esta ruta", command=usar_ruta).grid(row=0, column=2)
    ttk.Button(manual, text="Actualizar lista", command=refrescar).grid(
        row=0, column=3, padx=(16, 0))

    refrescar()


# ---------------------------------------------------------------------------
# Paso 4 — Cifrado (vive en ui/tk_crypto.py)
# ---------------------------------------------------------------------------

def _paso_cifrado(cuerpo, wiz) -> None:
    from . import tk_crypto
    tk_crypto.dibujar(cuerpo, wiz)


# ---------------------------------------------------------------------------
# Paso 5 — Instalación del código
# ---------------------------------------------------------------------------

def _paso_instalar(cuerpo, wiz) -> None:
    """Copiar el programa al dispositivo.

    Ya no hay «simular y luego hacer»: aquí no se borra nada. Antes esto era un
    `rclone sync` del espejo maestro, o sea un espejo que arrasaba en destino lo
    que no estuviera en el origen, y por eso exigía un `--dry-run` previo y
    teclear la ruta a mano. Ahora se escribe una carpeta propia y nada más."""
    import tkinter as tk
    from tkinter import ttk

    raiz = wiz.device_root
    ttk.Label(cuerpo, justify="left", wraplength=780, text=(
        f"Se instalará el programa en:\n\n"
        f"    {deploy.app_dir(raiz)}\n\n"
        "Ahí van el código, el binario de rclone, tu rclone.conf y su clave. La "
        "carpeta empieza por punto y se marca como oculta, para que no estorbe "
        "entre tus datos. En la raíz quedan los lanzadores runsync.pyw y "
        "runsync.sh, y una guía rápida de uso.")).grid(
        row=0, column=0, sticky="w")

    try:
        situacion, explicacion = device.install_target(raiz)
    except InstallError as e:
        ttk.Label(cuerpo, foreground=theme.PELIGRO, wraplength=780, justify="left",
                  text=str(e)).grid(row=1, column=0, sticky="w", pady=(10, 0))
        return

    colores = {device.VACIO: theme.OK, device.YA_INSTALADO: theme.OK,
               device.AJENO: theme.AVISO}
    ttk.Label(cuerpo, foreground=colores[situacion], wraplength=780, justify="left",
              text=explicacion).grid(row=1, column=0, sticky="w", pady=(10, 0))

    confirmado = {"vale": situacion != device.AJENO}
    if situacion == device.AJENO:
        marco = ttk.Frame(cuerpo)
        marco.grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Label(marco, text=f"Para seguir, escribe la ruta «{raiz}»:").grid(
            row=0, column=0, sticky="w")
        escrito = tk.StringVar()
        ttk.Entry(marco, textvariable=escrito, width=44).grid(row=0, column=1, padx=6)

        def revisar_texto(*_):
            confirmado["vale"] = (escrito.get().strip().rstrip("\\/")
                                  == str(raiz).rstrip("\\/"))
            boton_estado()
        escrito.trace_add("write", revisar_texto)

    estado_lbl = ttk.Label(cuerpo, wraplength=780, justify="left",
                           foreground=theme.TINTA3)
    estado_lbl.grid(row=3, column=0, sticky="w", pady=(12, 0))

    def instalar() -> None:
        if not confirmado["vale"]:
            return

        def trabajo():
            escrito_ = deploy.deploy_code(raiz, wiz.binario)
            escrito_ += deploy.write_launchers(raiz)
            guia = deploy.write_guide(raiz)
            if guia is not None:
                escrito_.append(guia)
            escrito_ += deploy.write_device_remote(raiz, wiz.perfil_final)
            # El .ico se pinta aquí y no se copia: sale del mismo sitio que los
            # de la ventana (`ui/icons.py`), así que no hay dos versiones que
            # puedan separarse. Es lo que verán los accesos directos.
            icons.write_ico(deploy.app_dir(raiz) / "runsync.ico")
            ident = device.ensure_control_file(raiz, renew=True)
            return escrito_, ident

        ok, res = working(wiz.root, "instalando", trabajo,
                          "Copiando el programa y el binario de rclone.")
        if not ok:
            estado_lbl.configure(text=f"No se ha podido instalar: {res}",
                                 foreground=theme.PELIGRO)
            return
        escrito_, ident = res
        wiz.state.deployed = True
        estado_lbl.configure(
            text=(f"Instalado: {len(escrito_)} elementos en {deploy.app_dir(raiz)}.\n"
                  f"Identificador del dispositivo: {ident[:8]}…"),
            foreground=theme.OK)
        boton_estado()
        wiz.revisar()

    boton = ttk.Button(cuerpo, text="Instalar el programa", command=instalar,
                       style="Primary.TButton")
    boton.grid(row=4, column=0, sticky="w", pady=(14, 0))

    def boton_estado() -> None:
        boton.configure(state="normal" if confirmado["vale"] else "disabled")

    if deploy.sync_py(raiz).is_file():
        estado_lbl.configure(
            text="Este dispositivo ya lleva el programa: puedes reinstalarlo para "
                 "actualizarlo, o seguir al paso siguiente.", foreground=theme.OK)
    boton_estado()


# ---------------------------------------------------------------------------
# Paso 6 — Parejas y config
# ---------------------------------------------------------------------------

def _paso_parejas(cuerpo, wiz) -> None:
    import tkinter as tk
    from tkinter import ttk

    ttk.Label(cuerpo, justify="left", wraplength=780, text=(
        "Qué carpetas va a sincronizar ESTE dispositivo. El catálogo es global; "
        "el sync_config.toml que se escribe aquí es solo de este dispositivo.")
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

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
        ttk.Label(marco, foreground=theme.TINTA3,
                  text=f"{pareja.get('local', '?')}  ↔  {pareja.get('remote_path', '?')}"
                  ).grid(row=i, column=1, sticky="w", padx=(16, 0))
        if modo in ("up-mirror", "down-mirror"):
            destino = "el remoto" if modo == "up-mirror" else "el dispositivo"
            ttk.Label(marco, foreground=theme.PELIGRO, wraplength=260, justify="left",
                      text=f"espejo: borra en {destino} lo que no esté en el origen"
                      ).grid(row=i, column=2, sticky="w", padx=(12, 0))

    resultado = ttk.Label(cuerpo, wraplength=780, justify="left", foreground=theme.TINTA3)
    resultado.grid(row=2, column=0, sticky="w", pady=(14, 0))

    def guardar() -> None:
        seleccion = [n for n, v in elegidas.items() if v.get()]
        try:
            destino = deploy.write_device_config(
                wiz.device_root, wiz.catalog, seleccion,
                endpoint=wiz.perfil.endpoint_catalog)
            creadas = deploy.make_local_dirs(wiz.device_root, wiz.catalog, seleccion)
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
        resultado.configure(text=detalle, foreground=theme.OK)
        wiz.revisar()

    ttk.Button(cuerpo, text="Guardar el config y crear las carpetas",
               command=guardar).grid(row=3, column=0, sticky="w", pady=(12, 0))


# ---------------------------------------------------------------------------
# Paso 7 — Inicialización
# ---------------------------------------------------------------------------

def _paso_inicializar(cuerpo, wiz) -> None:
    from tkinter import ttk

    bisync = deploy.resync_targets(wiz.catalog, wiz.state.selected)
    espejos = deploy.mirror_pairs(wiz.catalog, wiz.state.selected)

    ttk.Label(cuerpo, justify="left", wraplength=780, text=(
        "Una pareja bisync necesita un --resync la primera vez: es lo que compara "
        "los dos lados y fija la referencia. No borra por diferencias.")).grid(
        row=0, column=0, sticky="w", pady=(0, 10))

    tabla = ttk.Frame(cuerpo)
    tabla.grid(row=1, column=0, sticky="w")
    for i, (izq, der) in enumerate(deploy.summary(wiz.catalog, wiz.state.selected)):
        ttk.Label(tabla, text=izq).grid(row=i, column=0, sticky="w")
        ttk.Label(tabla, text=der, foreground=theme.TINTA3).grid(
            row=i, column=1, sticky="w", padx=(14, 0))

    if espejos:
        ttk.Label(cuerpo, foreground=theme.PELIGRO, wraplength=780, justify="left", text=(
            "No se inicializan aquí: " + ", ".join(espejos) + ".\n"
            "Son espejos: borran en el otro lado lo que no esté en el origen, y "
            "lanzarlos con las carpetas locales recién creadas propagaría ese "
            "vacío. Cuando el dispositivo esté como quieres, pruébalos a mano con "
            "--dry-run.")).grid(row=2, column=0, sticky="w", pady=(12, 0))

    resultado = ttk.Label(cuerpo, wraplength=780, justify="left", foreground=theme.TINTA3)
    resultado.grid(row=3, column=0, sticky="w", pady=(12, 0))

    def inicializar() -> None:
        try:
            cmd = deploy.resync_command(wiz.device_root, bisync)
        except InstallError as e:
            wiz.error(str(e))
            return
        rc = output_window("inicializar las parejas", cmd, parent=wiz.root)
        wiz.state.initialized = rc == 0
        resultado.configure(
            text="Parejas inicializadas." if rc == 0 else
                 f"Terminó con código {rc}: mira la salida. Se puede reintentar, "
                 "o hacerlo luego desde el dispositivo.",
            foreground=theme.OK if rc == 0 else theme.PELIGRO)

    boton = ttk.Button(cuerpo, text="Inicializar ahora", command=inicializar)
    boton.grid(row=4, column=0, sticky="w", pady=(12, 0))
    if not bisync:
        boton.configure(state="disabled")
        resultado.configure(text="Ninguna de las parejas elegidas necesita "
                                 "inicialización.")


# ---------------------------------------------------------------------------
# Paso 8 — Verificación y cierre
# ---------------------------------------------------------------------------

def _paso_final(cuerpo, wiz) -> None:
    from tkinter import ttk

    ttk.Label(cuerpo, justify="left", wraplength=780, text=(
        "Lo que de verdad hace falta para que este dispositivo arranque en "
        "cualquier equipo. Lo que falte aquí es lo que fallaría luego sin que se "
        "entienda por qué.")).grid(row=0, column=0, sticky="w", pady=(0, 10))

    tabla = ttk.Frame(cuerpo)
    tabla.grid(row=1, column=0, sticky="w")

    def revisar_dispositivo() -> None:
        for hijo in tabla.winfo_children():
            hijo.destroy()
        perfil = wiz.perfil_final
        clave = perfil.key_name if perfil.needs_key else None
        for i, chk in enumerate(device.verify_device(wiz.device_root,
                                                     wiz.state.selected, clave)):
            color = theme.OK if chk.ok else theme.PELIGRO
            ttk.Label(tabla, text="✔" if chk.ok else "✘", foreground=color,
                      width=3).grid(row=i, column=0, sticky="w")
            ttk.Label(tabla, text=chk.etiqueta + ":").grid(row=i, column=1, sticky="w")
            ttk.Label(tabla, text=chk.detalle, foreground=color, wraplength=520,
                      justify="left").grid(row=i, column=2, sticky="w", padx=(10, 0))

    revisar_dispositivo()

    extras = ttk.LabelFrame(cuerpo, text="Y ya que estamos", padding=10)
    extras.grid(row=2, column=0, sticky="w", pady=(14, 0))

    def instalar_vigilante() -> None:
        try:
            cmd = deploy.penwatch_install_command(wiz.device_root)
        except InstallError as e:
            wiz.error(str(e))
            return
        output_window("instalar el vigilante", cmd, parent=wiz.root)

    def guardar_en_catalogo() -> None:
        """Deja la conexión en el catálogo para los demás dispositivos.

        Es lo que hace que esto se teclee una sola vez: el siguiente dispositivo
        la hereda de ahí en vez de volver a preguntarla. La clave NO viaja: solo
        las opciones del backend."""
        wiz.aviso(
            "La conexión se guarda en el catálogo desde la ventana de parejas del "
            "propio dispositivo (Catálogo → [defaults]), que es la que sabe "
            "releerlo y negarse si otro dispositivo lo ha tocado mientras tanto.\n\n"
            f"Lo que hay que guardar es:\n\n"
            f"[remote]\n" + "\n".join(
                f"{k} = {v}" for k, v in
                profile.to_catalog_remote(wiz.perfil_final).items()))

    def registrar_favorito() -> None:
        if wiz.state.encryption != "veracrypt" or not wiz.state.container:
            wiz.error("Esto solo tiene sentido con un contenedor VeraCrypt.")
            return
        letra = str(wiz.device_root)[0] if wiz.device_root else ""
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
            "dispositivo, VeraCrypt NO monta y NO dice nada."))

    def desmontar() -> None:
        if not (wiz.state.mounted_by_us and wiz.state.veracrypt and wiz.device_root):
            wiz.error("Este instalador no ha montado ningún contenedor.")
            return
        try:
            crypto.dismount(wiz.state.veracrypt, wiz.device_root)
        except InstallError as e:
            wiz.error(str(e))
            return
        wiz.state.mounted_by_us = False
        wiz.aviso("Contenedor desmontado. Ya puedes extraer el dispositivo.")

    for i, (texto, accion) in enumerate((
            ("Instalar el arranque automático (penwatch)", instalar_vigilante),
            ("Compartir esta conexión con otros dispositivos", guardar_en_catalogo),
            ("Que VeraCrypt monte al conectar", registrar_favorito),
            ("Desmontar el contenedor", desmontar),
            ("Volver a comprobar", revisar_dispositivo))):
        ttk.Button(extras, text=texto, command=accion).grid(
            row=i // 2, column=i % 2, sticky="w", padx=(0, 8), pady=2)


# ---------------------------------------------------------------------------
# Los pasos, en orden, con la condición para poder salir de cada uno
# ---------------------------------------------------------------------------

def _ok_conexion(w) -> bool:
    return w.perfil.configured


def _ok_comprobaciones(w) -> bool:
    return w.rclone is not None and w.catalog is not None


def _ok_destino(w) -> bool:
    return w.state.device is not None


def _ok_cifrado(w) -> bool:
    return w.state.device_root is not None


def _ok_instalacion(w) -> bool:
    return w.state.deployed or deploy.sync_py(w.device_root).is_file()


def _ok_parejas(w) -> bool:
    return w.state.config_written


PASOS = [
    ("Conexión", _paso_conexion, _ok_conexion),
    ("Comprobaciones", _paso_comprobaciones, _ok_comprobaciones),
    ("Destino", _paso_destino, _ok_destino),
    ("Cifrado", _paso_cifrado, _ok_cifrado),
    ("Instalación", _paso_instalar, _ok_instalacion),
    ("Parejas y configuración", _paso_parejas, _ok_parejas),
    ("Inicialización", _paso_inicializar, lambda w: True),
    ("Verificación", _paso_final, lambda w: True),
]


if __name__ == "__main__":          # pragma: no cover - atajo para probar a mano
    sys.exit(run_wizard())
