#!/usr/bin/env python3
"""El asistente de instalación de un dispositivo prdrive.

Solo dibuja. Lo que decide y lo que toca disco o red está en `install/`, igual
que `tk_pairs.py` no sabe nada de lo que hace `pair_editor.py`.

Es un asistente por pasos y no una ventana única como la de `runsync.py` porque
aquí el orden no es negociable: no se puede leer el catálogo antes de saber con
qué remoto se habla, ni elegir parejas antes de saber dónde va el dispositivo,
ni inicializarlas antes de que exista el `sync.py` que las inicializa. Cada
paso tiene una condición y «Siguiente» no se enciende hasta cumplirla; así la
ventana no deja avanzar a un sitio donde el siguiente botón fallaría.

Las órdenes largas de rclone van a `ui.tk.output_window`, la misma que enseña
las sincronizaciones, para que se vea exactamente lo que hace. Las de VeraCrypt
NO: su línea de órdenes lleva la contraseña, así que van por `ui.tk.working`,
que solo enseña una barra (ver `ui/tk_crypto.py`). La instalación del código
también va por `working()`: es una copia de ficheros (y descargas: rclone y
Python de cada plataforma elegida) que tarda y cuya salida no le dice nada a
nadie.

La lista de plataformas (`_lista_plataformas`) la pintan dos pasos:
«Instalación» y el «Plataformas» del recorrido corto que abre «Añadir
plataformas…». Lo que decide (qué se marca, qué se borra, cuánto ocupa) es
`install/platforms.Matriz`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from common import model, update
from install import InstallError, InstallState, __version__
from install import (crypto, deploy, device, platforms, profile, raiz_equipo,
                     rclone_bin, remote, traveler, vestibulo)

from . import icons, theme
from .tk import TITLE, Visor, centrar, output_window, working

VENTANA = f"{TITLE} — Instalador"
"""El título de la ventana del asistente."""

ANCHO_CUERPO, ALTO_CUERPO = 820, 430
"""El lienzo de los pasos, en las medidas del diseño.

`icons.px` las lleva a los píxeles de esta pantalla, porque el texto de dentro
también crece con ella.
"""


class Wizard:
    """La ventana y por qué paso va; los pasos solo pintan dentro de `cuerpo`.

    Args:
        root: La ventana.
        visor: El `Visor` donde se pintan los pasos.
        cabecera: La etiqueta con el número y el título del paso.
        boton_siguiente: El botón «Siguiente» (o «Terminar»).
        boton_atras: El botón «Atrás».

    Attributes:
        state: Lo que el asistente va sabiendo (`InstallState`).
        perfil: El perfil de partida: el incrustado en el .exe, el del checkout
            o uno vacío. Que esté vacío NO es un error: es el arranque normal
            de quien se acaba de bajar el proyecto.
        perfil_device: El perfil con el que habla el INSTALADOR es `perfil`; el
            que se escribe al dispositivo puede no ser el mismo: el catálogo
            manda sobre el nombre del remote, porque es el que usan sus
            `remote_path` (`profile.align_with_catalog`).
        notas_perfil: Lo que el catálogo ha cambiado del perfil, para decirlo.
        binario: El rclone con el que se trabaja.
        conf: El `rclone.conf` efímero de la conexión.
        rclone: El cliente de rclone sobre esa conexión.
        catalog: El catálogo leído del remoto.
        indice: El paso en el que se está.
        pasos: El recorrido que se está haciendo. Se decide en el primer paso:
            si la unidad elegida ya es un prdrive se puede cambiar a
            `PASOS_ACTUALIZACION`, que son dos pantallas en vez de ocho. Es un
            atributo y no un global para que quepan los dos recorridos.
        modo: `None` mientras no se haya elegido entre actualizar y reinstalar.
            Solo hay que elegir cuando la unidad YA es un prdrive; en una
            unidad nueva no hay nada que preguntar y se sigue de largo.
        ya_instalado: Si la unidad elegida ya es un prdrive.
        matriz: La lista de plataformas marcadas.
        matriz_de: De qué dispositivo es esa lista: cambiar de unidad la
            invalida, porque lo que «ya lleva» es de la otra.
        donde: Si se instala en una `unidad` o en este `equipo`
            (`ui/tk_equipo.py`). Sale `unidad`, que es lo de siempre, para que
            quien viene a preparar un pendrive no note nada.
        agente_prep: Lo que se ha preparado del agente.
        agente_reusado: Si el agente ya estaba, de esta misma versión: no se
            reinstala, se le pide lo nuevo por su buzón
            (`install.agente.anadir`).
        agente_unidades: Las unidades que atenderá, con su modo y su nombre.
        agente_origen: De dónde se sabe de cada una.
        agente_espera: El plazo para contestar a una unidad nueva.
        agente_hecho: Lo que se hizo al registrarlo.
        equipo_forma: La forma de la raíz de este equipo.
        equipo_ruta: Su carpeta. Sale la propia, que es lo recomendado.
        equipo_examen: Lo que dice el examen de esa carpeta.
        equipo_id: El id que le ha tocado al instalarla.
        equipo_locales: El `local` de cada pareja que se cambie aquí.
        equipo_cifrado: Si va sin cifrar o en VeraCrypt.
        equipo_fisica: Dónde va el contenedor.
        equipo_letra: La letra fija en la que se abre.
        equipo_tamano: El tamaño del contenedor.
        equipo_montada: Dónde quedó montado, que es la raíz de verdad.
        equipo_contenedor: El `.hc`.
        equipo_pedir: Si el agente pide la contraseña al iniciar sesión.
        llavero_eleccion: Qué se hace con el llavero: `no`, `propia` (una base
            que se da) o `remoto` (traer la del catálogo).
        llavero_base: La base que se da.
        llavero_pide: Si esa base pide fichero llave.
        llavero_llave: Dónde está el fichero llave en este equipo.
        llavero_hecho: Si el llavero ya se ha puesto en el dispositivo.
    """

    def __init__(self, root, visor, cabecera, boton_siguiente, boton_atras) -> None:
        """Crea el asistente con todo vacío, en el primer paso."""
        self.root = root
        self.visor = visor
        self.cuerpo = visor.interior
        self.cabecera = cabecera
        self.boton_siguiente = boton_siguiente
        self.boton_atras = boton_atras
        self.state = InstallState()
        self.perfil: profile.Profile = profile.load()
        self.perfil_device: profile.Profile | None = None
        self.notas_perfil: list[str] = []
        self.binario: str | None = None
        self.conf: remote.EphemeralConf | None = None
        self.rclone: remote.Rclone | None = None
        self.catalog: remote.Catalog | None = None
        self.indice = 0
        self.pasos = PASOS_INSTALACION
        self.modo: str | None = None
        self.ya_instalado = False
        self.matriz: platforms.Matriz | None = None
        self.matriz_de: Path | None = None
        self.donde = "unidad"
        self.agente_prep = None
        self.agente_reusado = False
        self.agente_unidades: dict | None = None
        self.agente_origen: dict = {}
        self.agente_espera = 120.0
        self.agente_hecho: list[str] | None = None
        self.equipo_forma = raiz_equipo.PROPIA
        self.equipo_ruta = str(raiz_equipo.carpeta_propia())
        self.equipo_examen: raiz_equipo.Examen | None = None
        self.equipo_id = ""
        self.equipo_locales: dict[str, str] = {}
        self.equipo_cifrado = raiz_equipo.SIN_CIFRAR
        self.equipo_fisica = ""
        self.equipo_letra = ""
        self.equipo_tamano = ""
        self.equipo_montada: Path | None = None
        self.equipo_contenedor = ""
        self.equipo_pedir = True
        self.llavero_eleccion = "no"
        self.llavero_base: Path | None = None
        self.llavero_pide = False
        self.llavero_llave: Path | None = None
        self.llavero_hecho = False

    def repintar(self) -> None:
        """Pinta el paso en el que se está."""
        for hijo in self.cuerpo.winfo_children():
            hijo.destroy()
        titulo, dibujar, _ = self.pasos[self.indice]
        self.cabecera.configure(
            text=f"Paso {self.indice + 1} de {len(self.pasos)}   ·   {titulo}")
        dibujar(self.cuerpo, self)
        self.revisar()

    def revisar(self) -> None:
        """Enciende o apaga «Siguiente» según la condición del paso, y reajusta.

        Las dos cosas van juntas porque las pide la misma gente: todo lo que
        cambia el cuerpo termina llamando aquí (el panel de «ya es un prdrive»
        al elegir unidad, la tabla de comprobaciones según va contestando el
        remoto, la de verificación). Cuando el ajuste vivía solo en
        `repintar()`, lo que cambiaba sin cambiar de paso se quedaba con el
        hueco de antes.
        """
        _, _, condicion = self.pasos[self.indice]
        ultimo = self.indice == len(self.pasos) - 1
        try:
            puede = bool(condicion(self))
        except Exception:
            puede = False
        self.boton_siguiente.configure(
            text="Terminar" if ultimo else "Siguiente >",
            state="normal" if (puede or ultimo) else "disabled")
        self.boton_atras.configure(state="disabled" if self.indice == 0 else "normal")
        self.reencajar()

    def reencajar(self) -> None:
        """Ajusta el hueco a lo que pide el cuerpo ahora, y recoloca si ha crecido.

        El visor no se entera por su cuenta: su interior es un item del lienzo
        con la altura fijada por `itemconfigure`, así que añadirle widgets
        cambia lo que PIDE pero no lo que MIDE, y el `<Configure>` del que
        cuelga la barra de desplazamiento no llega a dispararse. Sin esto, un
        panel que aparece con la pantalla ya dibujada queda recortado Y sin
        barra, que es el peor de los dos casos: nada indica que falte nada.

        Se recoloca solo si ha cambiado de tamaño. El asistente se centra una
        vez al abrirse y no debe pasearse por la pantalla, pero uno que crece
        sin recolocarse acaba con el pie por debajo del borde de abajo.
        """
        if self.visor.crecer(self.root):
            centrar(self.root)

    def ir(self, delta: int) -> None:
        """Avanza o retrocede `delta` pasos; al avanzar desde el último, cierra."""
        if self.indice == len(self.pasos) - 1 and delta > 0:
            self.root.destroy()
            return
        self.indice = max(0, min(len(self.pasos) - 1, self.indice + delta))
        self.repintar()

    @property
    def device_root(self) -> Path | None:
        """Devuelve la raíz del dispositivo."""
        return self.state.device_root

    @property
    def perfil_final(self) -> profile.Profile:
        """Devuelve el perfil que acaba dentro del dispositivo."""
        return self.perfil_device or self.perfil

    def soltar_conexion(self) -> None:
        """Tira el conf efímero y lo que colgaba de él.

        Se llama al cambiar el perfil: el `rclone.conf` temporal lleva dentro
        la conexión anterior, y quedarse con él significaría comprobar una cosa
        y conectarse a otra.
        """
        if self.conf is not None:
            self.conf.close()
        self.conf = self.rclone = self.catalog = None
        self.perfil_device, self.notas_perfil = None, []

    def matriz_para(self, raiz: Path) -> platforms.Matriz:
        """Devuelve la lista de plataformas de ese dispositivo.

        Es la misma entre repintados.
        """
        if self.matriz is None or self.matriz_de != Path(raiz):
            self.matriz = platforms.Matriz.para(raiz)
            self.matriz_de = Path(raiz)
        return self.matriz

    def rehacer_matriz(self, raiz: Path) -> None:
        """Rehace la lista de plataformas tras escribir en el dispositivo.

        Lo que «ya lleva» ha cambiado. Se conserva la elección de completa o
        ligera.
        """
        completa = self.matriz.completa if self.matriz else True
        self.matriz = platforms.Matriz.para(raiz)
        self.matriz.completa = completa
        self.matriz_de = Path(raiz)

    def error(self, msg: str) -> None:
        """Enseña un error."""
        from tkinter import messagebox
        messagebox.showerror(TITLE, msg, parent=self.root)

    def aviso(self, msg: str) -> None:
        """Enseña un aviso."""
        from tkinter import messagebox
        messagebox.showinfo(TITLE, msg, parent=self.root)


def build(root) -> Wizard:
    """Monta la ventana sobre `root` y devuelve el asistente, sin arrancar nada.

    Está separado de `run_wizard()` para que los tests puedan conducir el
    asistente de verdad (el mismo cableado de botones y condiciones) en vez de
    una reconstrucción a mano que se quedaría desfasada.
    """
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

    # El hueco de los pasos es un `Visor`: parte del tamaño del diseño, CRECE
    # hasta lo que pida el paso más grande (nunca encoge, para que la ventana
    # no baile de un paso a otro) y solo se desplaza cuando ya no cabe en la
    # pantalla.
    visor = Visor(marco, ancho=icons.px(root, ANCHO_CUERPO),
                  alto=icons.px(root, ALTO_CUERPO))
    visor.marco.grid(row=2, column=0, sticky="nsew")
    marco.columnconfigure(0, weight=1)
    marco.rowconfigure(2, weight=1)

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

    wiz = Wizard(root, visor, cabecera, siguiente, atras)
    atras.configure(command=lambda: wiz.ir(-1))
    siguiente.configure(command=lambda: wiz.ir(+1))
    wiz.repintar()
    return wiz


def run_wizard() -> int:
    """Abre el asistente y devuelve 0 siempre que se haya podido abrir."""
    import tkinter as tk

    theme.nitidez()
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


def _paso_conexion(cuerpo, wiz) -> None:
    """Pinta el paso de la conexión: con qué remoto se habla.

    Es lo primero porque de él sale todo lo demás. Hay dos caminos y los dos
    hacen falta: quien ya usa rclone tiene su remote montado y solo quiere
    señalarlo, y quien empieza de cero necesita el formulario. Las opciones del
    backend se escriben tal cual irán al `rclone.conf`, en vez de inventarse un
    campo por backend: rclone tiene decenas y este proyecto no interpreta
    ninguna.
    """
    import tkinter as tk
    from tkinter import filedialog, ttk

    ttk.Label(cuerpo, justify="left", wraplength=theme.medida(780), text=(
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

    # El formulario de remoto nuevo.
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

        Solo con la caja vacía: pisar lo que alguien acaba de escribir por
        haber rozado el desplegable sería justo lo que no se espera.
        """
        if opciones.get("1.0", "end").strip():
            wiz.aviso("Vacía primero la caja de opciones: no piso lo que ya has "
                      "escrito.")
            return
        opciones.insert("1.0", profile.PLANTILLAS.get(tipo.get(), ""))

    ttk.Button(nuevo, text="Rellenar con la plantilla", command=plantilla).grid(
        row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def _fichero(destino: tk.StringVar, titulo: str) -> None:
        """Deja elegir un fichero y lo pone en la variable."""
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
    ttk.Label(nuevo, style="Pista.TLabel", wraplength=theme.medida(520), justify="left", text=(
        "Los dos son opcionales: un backend con contraseña o con token no los "
        "usa. Sin known_hosts se acepta la clave del servidor a la primera.")
        ).grid(row=6, column=0, columnspan=4, sticky="w", pady=(4, 0))

    # Importar de un `rclone.conf`.
    importar = ttk.Frame(caja)
    ttk.Label(importar, text="Fichero rclone.conf:", style="Campo.TLabel").grid(
        row=0, column=0, sticky="w")
    ttk.Entry(importar, textvariable=conf_ajeno, width=52).grid(
        row=0, column=1, sticky="w", padx=(6, 6))

    combo_remoto = ttk.Combobox(importar, textvariable=remoto_ajeno, width=24,
                                state="readonly")

    def elegir_conf() -> None:
        """Deja elegir el `rclone.conf` y carga sus remotes."""
        elegido = filedialog.askopenfilename(
            parent=wiz.root, title="Tu rclone.conf",
            filetypes=[("rclone.conf", "*.conf"), ("Todos", "*.*")])
        if not elegido:
            return
        conf_ajeno.set(elegido)
        cargar_remotos()

    def cargar_remotos() -> None:
        """Lee los remotes del fichero elegido."""
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
    ttk.Label(importar, style="Pista.TLabel", wraplength=theme.medida(560),
              justify="left", text=(
        "Se copia la definición del remote y, si usa fichero de clave, también la "
        "clave: el dispositivo tiene que llevar la suya para funcionar en "
        "cualquier equipo.")).grid(row=2, column=0, columnspan=3, sticky="w",
                                   pady=(6, 0))

    def cambiar_modo(*_) -> None:
        """Enseña el formulario del modo elegido."""
        nuevo.grid_forget()
        importar.grid_forget()
        (nuevo if modo.get() == "nuevo" else importar).grid(row=0, column=0, sticky="w")
    modo.trace_add("write", cambiar_modo)
    cambiar_modo()

    # Lo común.
    comun = ttk.Frame(cuerpo)
    comun.grid(row=3, column=0, sticky="w", pady=(12, 0))
    ttk.Label(comun, text="Ruta del catálogo en el remoto:",
              style="Campo.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Entry(comun, textvariable=catalogo, width=46).grid(row=0, column=1,
                                                           sticky="w", padx=(6, 0))

    def cambiar_catalogo(*_) -> None:
        """Aplica sola la ruta del catálogo.

        Es el único campo de este paso que vale igual para una conexión recién
        tecleada que para una que ya venía dada (incrustada en el .exe o en el
        checkout), y en ese segundo caso «Usar esta conexión» no se pulsa
        nunca: sin esto, cambiarla aquí no llegaba a ningún sitio. Al cambiarla
        se suelta lo descargado, porque el catálogo que hubiera en memoria es
        el de la ruta anterior.
        """
        if not wiz.perfil.configured:
            return                      # aún no hay perfil: lo pone `usar()`
        nueva = catalogo.get().strip() or profile.DEFAULT_CATALOG_PATH
        if nueva == wiz.perfil.catalog_path:
            return
        wiz.soltar_conexion()
        wiz.perfil = profile.with_catalog_path(wiz.perfil, nueva)
        preparada(wiz.perfil)
        wiz.revisar()

    catalogo.trace_add("write", cambiar_catalogo)

    # Lo que se sabe de la conexión, y nada más (#47). «Usar esta conexión»
    # solo convierte el formulario en un perfil, con las comprobaciones de
    # `install/profile.py`, que no hablan con nadie: el remoto no se toca hasta
    # «Comprobaciones». Por eso aquí no hay ✔ ni verde, que se leían como
    # «conexión comprobada». Lo que falla sí se dice aquí, en rojo, y deja el
    # paso sin conexión: un error al lado de un «Siguiente» encendido invita a
    # seguir con la de antes creyendo que es la que se acaba de escribir.
    estado = ttk.Label(cuerpo, wraplength=theme.medida(780), justify="left")
    estado.grid(row=5, column=0, sticky="w", pady=(12, 0))
    # Lo que no impide seguir pero conviene saber (`profile.avisos`). Solo ocupa
    # sitio cuando dice algo.
    notas = ttk.Label(cuerpo, wraplength=theme.medida(780), justify="left",
                      style="Aviso.TLabel")

    def preparada(perfil: profile.Profile) -> None:
        """Dice que la conexión está preparada, sin probar, y sus avisos."""
        if perfil.problema_catalogo:
            # Una carpeta en vez del fichero (#48) se dice aquí, según se teclea
            # o al abrir el paso con un perfil incrustado que la trae, y la
            # condición del paso (`_ok_conexion`) no deja seguir con ella.
            estado.configure(text=f"✘ {perfil.problema_catalogo}",
                             style="Peligro.TLabel")
            notas.grid_remove()
            return
        estado.configure(style="TLabel", text=(
            "Conexión preparada, sin probar todavía: se comprobará en el paso "
            f"siguiente.\n{perfil.describe()}   ·   catálogo en "
            f"{perfil.endpoint_catalog}   ·   {perfil.origen}"))
        avisos = profile.avisos(perfil)
        notas.configure(text="\n".join(avisos))
        if avisos:
            notas.grid(row=6, column=0, sticky="w", pady=(8, 0))
        else:
            notas.grid_remove()

    def fallida(mensaje: str) -> None:
        """Dice por qué la conexión no vale y la deja sin perfil."""
        wiz.soltar_conexion()
        wiz.perfil = profile.empty()
        estado.configure(text=mensaje, style="Peligro.TLabel")
        notas.grid_remove()
        wiz.revisar()

    def usar() -> None:
        """Convierte el formulario en un perfil, sin hablar con nadie."""
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
                    raise InstallError(
                        "Elige cuál de los remotes de ese fichero quieres.")
                perfil = profile.from_rclone_conf(
                    conf_ajeno.get(), remoto_ajeno.get(),
                    catalog_path=catalogo.get().strip())
        except InstallError as e:
            fallida(str(e))
            return

        wiz.soltar_conexion()          # el conf efímero anterior ya no vale
        wiz.perfil = perfil
        preparada(perfil)
        wiz.revisar()

    ttk.Button(cuerpo, text="Usar esta conexión", command=usar).grid(
        row=4, column=0, sticky="w", pady=(12, 0))

    if wiz.perfil.configured:
        preparada(wiz.perfil)


def _paso_comprobaciones(cuerpo, wiz) -> None:
    """Pinta el paso de las comprobaciones: rclone, el remoto y el catálogo."""
    from tkinter import ttk

    ttk.Label(cuerpo, justify="left", wraplength=theme.medida(780), text=(
        "Antes de tocar nada: que haya un rclone con el que trabajar, que el "
        "remoto conteste y que su catálogo de parejas se entienda.")).grid(
        row=0, column=0, sticky="w", pady=(0, 10))

    tabla = ttk.Frame(cuerpo)
    tabla.grid(row=1, column=0, sticky="w")

    def pintar(filas: list[tuple[str, bool | None, str]]) -> None:
        """Pinta las filas de comprobaciones."""
        for hijo in tabla.winfo_children():
            hijo.destroy()
        for i, (etiqueta, ok, detalle) in enumerate(filas):
            marca = "…" if ok is None else ("✔" if ok else "✘")
            color = theme.TINTA3 if ok is None else (theme.OK if ok else theme.PELIGRO)
            ttk.Label(tabla, text=marca, foreground=color, width=3).grid(
                row=i, column=0, sticky="w")
            ttk.Label(tabla, text=etiqueta + ":").grid(row=i, column=1, sticky="w")
            ttk.Label(tabla, text=detalle, foreground=color, wraplength=theme.medida(560),
                      justify="left").grid(row=i, column=2, sticky="w", padx=(10, 0))

    def comprobar(descargar: bool = False) -> None:
        """Comprueba rclone, la conexión y el catálogo, en un hilo."""
        filas: list[tuple[str, bool | None, str]] = []
        perfil = wiz.perfil

        def trabajo():
            """Busca rclone, conecta al remoto y lee el catálogo."""
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
            *_filas_python(wiz),
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
            *_filas_python(wiz),
        ])
    else:
        pintar([("rclone", None, "sin comprobar"),
                ("Conexión", None, wiz.perfil.describe()),
                ("Catálogo", None, "sin comprobar")])


def _filas_python(wiz) -> list[tuple[str, bool, str]]:
    """Devuelve con qué Python arrancará lo instalado.

    En este equipo no se pregunta: la raíz la sincroniza el agente con el suyo,
    que se instala en «Instalación».
    """
    if wiz.donde == "equipo":
        return []
    chk = device.check_python()
    return [(chk.etiqueta, chk.ok, chk.detalle)]


def _paso_donde(cuerpo, wiz) -> None:
    """Pinta la primera pregunta: qué recorrido se hace.

    «En una unidad» es lo de siempre. «En este equipo» instala el agente
    residente (`install/agente.py`): prdrive se queda en el ordenador y atiende
    las unidades prdrive que se enchufan. Cambiar de respuesta cambia la lista
    de pasos y las dos empiezan por esta pantalla, así que «Atrás» siempre
    vuelve aquí.
    """
    import tkinter as tk
    from tkinter import ttk

    from common import equipo

    ttk.Label(cuerpo, justify="left", wraplength=theme.medida(780),
              text="¿Dónde quieres instalar prdrive?").grid(
        row=0, column=0, sticky="w", pady=(0, 12))
    eleccion = tk.StringVar(value=wiz.donde)

    def elegir() -> None:
        """Apunta dónde se instala y rehace la lista de pasos."""
        wiz.donde = eleccion.get()
        wiz.pasos = pasos_equipo(wiz) if wiz.donde == "equipo" else PASOS_INSTALACION
        wiz.repintar()

    instalado = equipo.leer_instalacion().get("version") if equipo.instalado() else None
    opciones = (
        ("unidad", "En una unidad",
         "Un pendrive o un disco que lleva prdrive y tus carpetas, y funciona en "
         "cualquier equipo donde lo enchufes. Lo de siempre."),
        ("equipo", "En este equipo",
         "prdrive se queda en el ordenador, en segundo plano: sincroniza una "
         "carpeta de este equipo con tu remoto, si quieres, y atiende las "
         "unidades prdrive que enchufes aquí, sin que tengas que abrir nada. "
         "Avisa si algo falla, y sustituye al arranque automático (penwatch)."
         + (f"\nYa está instalado (versión {instalado}): puedes ponerlo al día, "
            f"añadirle una carpeta o cambiar sus unidades." if instalado else "")))
    for i, (valor, titulo, texto) in enumerate(opciones):
        tarjeta = ttk.Frame(cuerpo, style="Card.TFrame", padding=(14, 10))
        tarjeta.grid(row=1 + i, column=0, sticky="ew", pady=(0, 10))
        tarjeta.columnconfigure(0, weight=1)
        ttk.Radiobutton(tarjeta, text=titulo, value=valor, variable=eleccion,
                        style="Card.Fuerte.TRadiobutton", command=elegir).grid(
            row=0, column=0, sticky="w")
        ttk.Label(tarjeta, text=texto, style="Card.Pista.TLabel", justify="left",
                  wraplength=theme.medida(720)).grid(row=1, column=0, sticky="w",
                                                     pady=(4, 0))


def _ok_donde(w) -> bool:
    """Indica si se puede seguir desde el paso «¿Dónde?»."""
    return w.donde in ("unidad", "equipo")


COLUMNAS = [("unidad", "Unidad", 80), ("etiqueta", "Etiqueta", 110),
            ("fs", "Formato", 70), ("tipo", "Tipo", 90),
            ("tam", "Tamaño", 80), ("libre", "Libre", 80),
            ("nota", "", 300)]
"""Las columnas de la lista de unidades: clave, título y ancho en medidas del diseño."""


def _paso_destino(cuerpo, wiz) -> None:
    """Pinta el paso del dispositivo: la lista de unidades o una ruta a mano."""
    import tkinter as tk
    from tkinter import ttk

    ttk.Label(cuerpo, justify="left", wraplength=theme.medida(780), text=(
        "Se listan TODAS las unidades, no solo las que Windows declara "
        "extraíbles: muchos pendrives (y casi todos los SSD por USB) se declaran "
        "fijos, y filtrarlos es la forma más rápida de que el tuyo no aparezca.")
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

    tree = ttk.Treeview(cuerpo, columns=[c[0] for c in COLUMNAS],
                        show="headings", height=8, selectmode="browse")
    for clave, titulo, ancho in COLUMNAS:
        tree.heading(clave, text=titulo)
        tree.column(clave, width=icons.px(tree, ancho), anchor="w")
    tree.grid(row=1, column=0, sticky="w")

    aviso = ttk.Label(cuerpo, wraplength=theme.medida(780), justify="left")
    aviso.grid(row=2, column=0, sticky="w", pady=(8, 0))

    volumenes: dict[str, device.Volume] = {}

    def refrescar() -> None:
        """Relee las unidades y las pinta."""
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
        """Devuelve la unidad elegida en la lista, o `None`."""
        sel = tree.selection()
        return volumenes.get(sel[0]) if sel else None

    def mostrar(*_) -> None:
        """Dice qué destino hay elegido y revisa el desvío."""
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
        revisar_desvio()

    def revisar_desvio() -> None:
        """Pone o quita el panel de «ya es un prdrive» según lo elegido.

        Cambiar de unidad tira la elección anterior: si se había dicho
        «actualizar» para un pen y ahora hay otro seleccionado, esa respuesta
        ya no vale para nada.
        """
        for hijo in desvio.winfo_children():
            hijo.destroy()
        wiz.modo = None
        wiz.pasos = PASOS_INSTALACION
        wiz.ya_instalado = _ya_es_prdrive(wiz.state.device)
        if wiz.ya_instalado:
            _panel_ya_instalado(desvio, wiz, wiz.state.device, 0)
        wiz.revisar()

    tree.bind("<<TreeviewSelect>>", mostrar)

    manual = ttk.Frame(cuerpo)
    manual.grid(row=3, column=0, sticky="w", pady=(12, 0))
    ttk.Label(manual, text="…o una ruta a mano:").grid(row=0, column=0, sticky="w")
    ruta = tk.StringVar()
    ttk.Entry(manual, textvariable=ruta, width=46).grid(row=0, column=1, padx=6)

    def usar_ruta() -> None:
        """Usa como destino la ruta escrita a mano."""
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
        revisar_desvio()

    ttk.Button(manual, text="Usar esta ruta", command=usar_ruta).grid(row=0, column=2)
    ttk.Button(manual, text="Actualizar lista", command=refrescar).grid(
        row=0, column=3, padx=(16, 0))

    # El hueco del desvío a actualizar. Va debajo de la ruta a mano porque solo
    # aparece a veces, y lo que no puede es empujar la lista hacia abajo cada vez
    # que se cambia de selección.
    desvio = ttk.Frame(cuerpo)
    desvio.grid(row=4, column=0, sticky="ew", pady=(0, 0))
    desvio.columnconfigure(0, weight=1)

    refrescar()


def _ya_es_prdrive(raiz) -> bool:
    """Indica si hay un prdrive completo en esa raíz; un volumen ilegible es que no."""
    if raiz is None:
        return False
    try:
        return device.install_target(raiz)[0] == device.YA_INSTALADO
    except InstallError:
        return False        # bloqueado o ilegible: ya se dirá en su momento


def _ir_a_actualizar(wiz) -> None:
    """Cambia al recorrido corto y se planta en su pantalla de actualizar.

    Se fija el índice en vez de avanzar uno, porque a este desvío se puede
    llegar desde el paso del dispositivo o desde el del cifrado (VeraCrypt no
    deja ver el `.prdrive/` hasta montar el contenedor) y desde sitios
    distintos «uno más» no cae en el mismo sitio.
    """
    wiz.modo = "actualizar"
    wiz.pasos = PASOS_ACTUALIZACION
    wiz.indice = len(PASOS_ACTUALIZACION) - 1
    wiz.repintar()


def _seguir_instalando(wiz) -> None:
    """Sigue con la instalación entera, sin desvío."""
    wiz.modo = "instalar"
    wiz.pasos = PASOS_INSTALACION
    wiz.ir(1)


def _ir_a_plataformas(wiz) -> None:
    """Cambia al otro recorrido corto: la lista de plataformas.

    Es sobre un dispositivo que ya existe, con el mismo criterio que
    `_ir_a_actualizar` para fijar el índice.
    """
    wiz.modo = "plataformas"
    wiz.pasos = PASOS_PLATAFORMAS
    wiz.indice = len(PASOS_PLATAFORMAS) - 1
    wiz.repintar()


def _panel_ya_instalado(cuerpo, wiz, raiz, fila: int) -> None:
    """Pinta el desvío: qué versión hay, cuál trae el instalador y los caminos.

    Actualizar y reinstalar se ofrecen los dos a propósito. Reconocer el
    dispositivo no puede quitarle a nadie la posibilidad de volver a
    aprovisionarlo: cambiar de remoto, recifrar el volumen o rehacer las
    parejas se hace con el asistente completo, y obligar a borrar `.prdrive/` a
    mano para llegar ahí sería una trampa. «Añadir plataformas…» es el tercero:
    llevar el dispositivo a otro sistema o a otra CPU sin rehacer nada de lo
    demás.
    """
    from tkinter import ttk

    caja = ttk.Frame(cuerpo, style="Card.TFrame", padding=(14, 12))
    caja.grid(row=fila, column=0, sticky="ew", pady=(14, 0))
    caja.columnconfigure(0, weight=1)

    puesta = update.installed_version(deploy.app_dir(raiz)) or "desconocida"
    ttk.Label(caja, text=f"{raiz} ya es un dispositivo prdrive",
              style="Card.Fuerte.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(caja, style="Card.Pista.TLabel", wraplength=theme.medida(700), justify="left",
              text=(f"Lleva la versión {puesta} y este instalador trae la "
                    f"{__version__ or 'desconocida'}. Puedes ponerle el programa "
                    f"nuevo sin tocar nada más, añadirle o quitarle plataformas "
                    f"(otro sistema, otra CPU), o repetir la instalación entera "
                    f"si lo que quieres es cambiar de remoto, de cifrado o de "
                    f"parejas.")).grid(row=1, column=0, sticky="w", pady=(5, 11))

    botones = ttk.Frame(caja, style="Card.TFrame")
    botones.grid(row=2, column=0, sticky="w")
    actualizar = ttk.Button(botones, text="Actualizar el programa",
                            style="Primary.TButton", padding=(12, 7),
                            command=lambda: _ir_a_actualizar(wiz))
    theme.boton_icono(actualizar, "down", theme.SOBRE_ACENTO, theme.ACENTO)
    actualizar.grid(row=0, column=0)
    ttk.Button(botones, text="Añadir plataformas…", style="CardQuiet.TButton",
               command=lambda: _ir_a_plataformas(wiz)).grid(row=0, column=1,
                                                            padx=(8, 0))
    ttk.Button(botones, text="Reinstalar desde cero", style="CardQuiet.TButton",
               command=lambda: _seguir_instalando(wiz)).grid(row=0, column=2,
                                                             padx=(8, 0))


def _paso_cifrado(cuerpo, wiz) -> None:
    """Pinta el paso de cifrado, que vive en `ui/tk_crypto.py`."""
    from . import tk_crypto
    tk_crypto.dibujar(cuerpo, wiz)
    # Con VeraCrypt el `.prdrive/` vive DENTRO del contenedor, así que hasta
    # montarlo la unidad no se distingue de una vacía: el desvío a actualizar no
    # se podía ofrecer en el paso anterior y se ofrece aquí.
    if wiz.modo is None and _ya_es_prdrive(wiz.device_root):
        _panel_ya_instalado(cuerpo, wiz, wiz.device_root, 90)


def _paso_actualizar(cuerpo, wiz) -> None:
    """Pinta el paso que le pone a un dispositivo el código del instalador.

    El dispositivo ya existe. El origen es el propio ejecutable y no GitHub: el
    .exe ya lleva el árbol dentro (es lo mismo que copia el paso
    «Instalación»), así que esto va sin red, sin conexión al remoto y sin
    catálogo. Quien quiera la última versión publicada la tiene en el aviso de
    la ventana principal, que sí baja de GitHub; aquí se instala lo que hay en
    la mano.
    """
    from tkinter import ttk

    # En el recorrido corto puede no haberse pasado por «Cifrado», que es quien
    # fija `device_root`; sin cifrado, la raíz del volumen es la del dispositivo.
    raiz = wiz.device_root or wiz.state.device
    app = deploy.app_dir(raiz)
    puesta = update.installed_version(app)
    mia = __version__

    ttk.Label(cuerpo, justify="left", wraplength=theme.medida(780), text=(
        f"Se sustituye el programa de:\n\n"
        f"    {app}\n\n"
        "Se conservan tu configuración, tus claves, el estado de bisync, los "
        "filtros, los diarios y el rclone que ya tiene. Tampoco se toca nada de "
        "lo que haya fuera de esa carpeta.")).grid(row=0, column=0, sticky="w")

    tabla = ttk.Frame(cuerpo, style="Card.TFrame", padding=(14, 12))
    tabla.grid(row=1, column=0, sticky="w", pady=(14, 0))
    for i, (etiqueta, valor) in enumerate((
            ("Tiene puesta", puesta or "una versión anterior a los avisos"),
            ("Se le pondrá", mia or "la que trae este instalador"))):
        ttk.Label(tabla, text=etiqueta, style="Card.Campo.TLabel").grid(
            row=i, column=0, sticky="w", padx=(0, 14), pady=(0, 3))
        ttk.Label(tabla, text=valor, style="Card.Mono.TLabel").grid(
            row=i, column=1, sticky="w", pady=(0, 3))

    fila = 2
    # Instalar hacia atrás no se prohíbe —puede ser justo lo que se quiere para
    # salir de una versión que va mal— pero no puede pasar por descuido.
    retroceso = bool(puesta and mia and update.is_newer(puesta, mia))
    if retroceso:
        aviso = ttk.Frame(cuerpo, style="Ambar.TFrame", padding=(11, 9))
        aviso.grid(row=fila, column=0, sticky="ew", pady=(14, 0))
        aviso.columnconfigure(0, weight=1)
        ttk.Label(aviso, style="Ambar.TLabel", wraplength=theme.medida(740), justify="left",
                  text=(f"Este instalador es MÁS VIEJO que el dispositivo: trae "
                        f"la {mia} y ahí está puesta la {puesta}. Seguir lo "
                        f"dejaría en la {mia}.")).grid(row=0, column=0, sticky="w")
        fila += 1

    estado_lbl = ttk.Label(cuerpo, wraplength=theme.medida(780), justify="left",
                           foreground=theme.TINTA3)
    estado_lbl.grid(row=fila + 1, column=0, sticky="w", pady=(12, 0))

    def actualizar() -> None:
        """Sustituye el programa del dispositivo, en un hilo."""
        if retroceso and not _confirmar_retroceso(wiz, mia, puesta):
            return

        def trabajo():
            """Copia el código y la guía, pinta el icono y conserva el id."""
            # Sin rclone ni Python: ya están puestos. Y sin lanzadores: se
            # escriben al aprovisionar, y actualizar el programa no los toca.
            escrito = deploy.deploy_code(raiz)
            guia = deploy.write_guide(raiz)
            if guia is not None:
                escrito.append(guia)
            icons.write_ico(app / "runsync.ico")
            # renew=False: es el MISMO dispositivo. Renovarle el id —que es lo
            # que hace la instalación— dejaría colgado a cualquier vigilante que
            # ya estuviera atado a él.
            ident = device.ensure_control_file(raiz, renew=False)
            return escrito, ident

        ok, res = working(wiz.root, "actualizando", trabajo,
                          "Sustituyendo el programa del dispositivo.")
        if not ok:
            estado_lbl.configure(text=f"No se ha podido actualizar: {res}",
                                 foreground=theme.PELIGRO)
            wiz.revisar()           # lo mismo que en «Instalación» (#49)
            wiz.visor.ver(estado_lbl)       # aquí el error va debajo del botón
            return
        escrito, ident = res
        wiz.state.deployed = True
        boton.configure(state="disabled")
        estado_lbl.configure(
            text=(f"Actualizado a la {mia}: {len(escrito)} elementos en {app}.\n"
                  f"El dispositivo sigue siendo el {ident[:8]}… y conserva todo "
                  f"lo suyo. Ya puedes cerrar."),
            foreground=theme.OK)
        wiz.revisar()

    boton = ttk.Button(cuerpo, text="Actualizar ahora", style="Primary.TButton",
                       padding=(14, 8), command=actualizar)
    theme.boton_icono(boton, "down", theme.SOBRE_ACENTO, theme.ACENTO)
    boton.grid(row=fila, column=0, sticky="w", pady=(16, 0))


def _confirmar_retroceso(wiz, mia: str, puesta: str) -> bool:
    """Pregunta si se quiere dejar el dispositivo en una versión anterior."""
    from tkinter import messagebox
    return bool(messagebox.askokcancel(TITLE, (
        f"Vas a dejar el dispositivo en la versión {mia}, que es anterior a la "
        f"{puesta} que tiene ahora.\n\n¿Seguro?"), parent=wiz.root, icon="warning"))


def _paso_instalar(cuerpo, wiz) -> None:
    """Pinta el paso que copia el programa al dispositivo.

    Aquí no se borra nada: se escribe una carpeta propia y nada más, así que no
    hace falta «simular y luego hacer» ni teclear la ruta a mano.
    """
    import tkinter as tk
    from tkinter import ttk

    raiz = wiz.device_root
    ttk.Label(cuerpo, justify="left", wraplength=theme.medida(780), text=(
        f"Se instalará el programa en:\n\n"
        f"    {deploy.app_dir(raiz)}\n\n"
        "Ahí van el código, rclone y Python para cada plataforma que marques, tu "
        "rclone.conf y su clave. La carpeta empieza por punto y se marca como "
        "oculta, para que no estorbe entre tus datos. En la raíz quedan los "
        "lanzadores runsync.bat y runsync.sh, y una guía rápida de uso."
        + (f"\n\nY fuera del contenedor, en {vestibulo.destino(wiz.state)}, la "
           f"entrada para abrirlo y cerrarlo en cualquier equipo: "
           f"«{vestibulo.NOMBRE_ABRIR}», «{vestibulo.NOMBRE_EXPULSAR}» y una guía "
           "corta."
           if vestibulo.destino(wiz.state) is not None else ""))).grid(
        row=0, column=0, sticky="w")

    try:
        situacion, explicacion = device.install_target(raiz)
    except InstallError as e:
        ttk.Label(cuerpo, foreground=theme.PELIGRO, justify="left",
                  wraplength=theme.medida(780), text=str(e)).grid(
                      row=1, column=0, sticky="w", pady=(10, 0))
        return

    colores = {device.VACIO: theme.OK, device.YA_INSTALADO: theme.OK,
               device.AJENO: theme.AVISO}
    ttk.Label(cuerpo, foreground=colores[situacion], justify="left",
              wraplength=theme.medida(780),
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
            """Comprueba que la ruta escrita es la del dispositivo."""
            confirmado["vale"] = (escrito.get().strip().rstrip("\\/")
                                  == str(raiz).rstrip("\\/"))
            boton_estado()
        escrito.trace_add("write", revisar_texto)

    lista, refrescar_lista = _lista_plataformas(cuerpo, wiz, raiz,
                                                al_cambiar=lambda: boton_estado())
    lista.grid(row=3, column=0, sticky="ew", pady=(14, 0))

    estado_lbl = ttk.Label(cuerpo, wraplength=theme.medida(780), justify="left",
                           foreground=theme.TINTA3)
    estado_lbl.grid(row=4, column=0, sticky="w", pady=(12, 0))

    def instalar() -> None:
        """Instala el programa en el dispositivo, en un hilo."""
        if not (confirmado["vale"] and wiz.matriz.listo):
            return
        plan = wiz.matriz.plan()

        def trabajo():
            """Descarga y copia programa, plataformas, lanzadores y conexión."""
            # Primero lo que viene de fuera, comprobado y a la caché de este
            # equipo: si falta algo (el rclone de otra plataforma que no
            # llega), el dispositivo sigue sin tocar y el reintento solo baja
            # lo que faltaba (#49).
            conseguido = deploy.conseguir_plataformas(plan)
            escrito_ = deploy.deploy_code(raiz)
            nuevos, borrados = deploy.apply_platforms(raiz, plan,
                                                      conseguido=conseguido)
            escrito_ += nuevos
            escrito_ += deploy.write_launchers(raiz, plan.completa)
            guia = deploy.write_guide(raiz)
            if guia is not None:
                escrito_.append(guia)
            escrito_ += deploy.write_device_remote(raiz, wiz.perfil_final)
            # El `.ico` se pinta aquí y no se copia: sale del mismo sitio que
            # los de la ventana (`ui/icons.py`), así que no hay dos versiones
            # que puedan separarse. Es lo que verán los accesos directos.
            icons.write_ico(deploy.app_dir(raiz) / "runsync.ico")
            ident = device.ensure_control_file(raiz, renew=True)
            # Con contenedor, la entrada de fuera: después del fichero de
            # control, que es de donde sale el id que las une.
            fisica = vestibulo.destino(wiz.state)
            if fisica is not None:
                escrito_ += vestibulo.escribir(fisica, ident)
            return escrito_, borrados, ident

        ok, res = working(wiz.root, "instalando", trabajo,
                          "Descargando y copiando el programa, rclone y Python.")
        if not ok:
            estado_lbl.configure(text=f"No se ha podido instalar: {res}",
                                 foreground=theme.PELIGRO)
            # El mensaje puede ocupar una docena de líneas (qué plataforma
            # falló y cómo ponerla a mano) y hace crecer el paso sin cambiar de
            # paso. Sin reencajar, «Instalar el programa» quedaba por debajo
            # del borde, fuera de la vista aunque sobrara sitio, justo cuando
            # hay que volver a pulsarlo (#49). Y si ni creciendo cabe, se
            # desplaza hasta él.
            wiz.revisar()
            wiz.visor.ver(boton)
            return
        escrito_, borrados, ident = res
        wiz.state.deployed = True
        wiz.rehacer_matriz(raiz)
        refrescar_lista()
        estado_lbl.configure(
            text=(f"Instalado: {len(escrito_)} elementos en {deploy.app_dir(raiz)}"
                  + (f", {len(borrados)} borrados" if borrados else "") + ".\n"
                  f"Identificador del dispositivo: {ident[:8]}…"),
            foreground=theme.OK)
        boton_estado()
        wiz.revisar()

    boton = ttk.Button(cuerpo, text="Instalar el programa", command=instalar,
                       style="Primary.TButton")
    boton.grid(row=5, column=0, sticky="w", pady=(14, 0))

    def boton_estado() -> None:
        """Habilita «Instalar el programa» si está confirmado y hay algo que hacer."""
        listo = confirmado["vale"] and wiz.matriz is not None and wiz.matriz.listo
        boton.configure(state="normal" if listo else "disabled")

    if deploy.sync_py(raiz).is_file():
        estado_lbl.configure(
            text="Este dispositivo ya lleva el programa: puedes reinstalarlo para "
                 "actualizarlo, o seguir al paso siguiente.", foreground=theme.OK)
    boton_estado()


def _preguntar_borrado(wiz, plat) -> bool:
    """Pregunta si se borra del dispositivo lo que lleva para esa plataforma.

    Es de módulo para que los tests contesten sin ventana, como `mostrar()`. Es
    la única pregunta destructiva de la lista y el «no» es la respuesta segura:
    los binarios se quedan donde están y simplemente no se reinstalan.
    """
    from tkinter import messagebox
    return bool(messagebox.askyesno(TITLE, (
        f"El dispositivo ya lleva rclone y Python para {plat.nombre} "
        f"(≈{plat.mb_rclone + plat.mb_python} MB).\n\n"
        f"¿Borrarlos al instalar? Si dices que no, se quedan donde están: "
        f"simplemente no se vuelven a instalar."), parent=wiz.root, icon="warning",
        default="no"))


def _lista_plataformas(padre, wiz, raiz, al_cambiar):
    """Devuelve el marco de la lista de plataformas y su función `refrescar`.

    La lista es completa o ligera, con una casilla por plataforma, lo que ocupa
    cada una y el total. Solo pinta: qué significa marcar o quitar (y quitar
    algo que el dispositivo ya lleva, que es borrar) lo decide `wiz.matriz`
    (`install/platforms.Matriz`). Los widgets se crean una vez y `refrescar()`
    los actualiza en su sitio: una casilla que se destruyera dentro de su
    propio `command` es la forma de pedir un error de Tcl.
    """
    import tkinter as tk
    from tkinter import ttk

    matriz = wiz.matriz_para(raiz)
    marco = ttk.Frame(padre)
    marco.columnconfigure(0, weight=1)

    modo = tk.StringVar(value="completa" if matriz.completa else "ligera")
    radios = ttk.Frame(marco)
    radios.grid(row=0, column=0, sticky="w")

    def cambiar_modo() -> None:
        """Cambia entre completa y ligera."""
        wiz.matriz.completa = modo.get() == "completa"
        refrescar()

    for i, (valor, texto) in enumerate((
            ("completa", "Completa: lleva su propio Python y funciona en equipos "
                         "sin nada instalado"),
            ("ligera", "Ligera: usa el Python de cada equipo (3.11+ con Tkinter)"))):
        ttk.Radiobutton(radios, text=texto, value=valor, variable=modo,
                        command=cambiar_modo).grid(row=i, column=0, sticky="w")

    tabla = ttk.Frame(marco)
    tabla.grid(row=1, column=0, sticky="w", pady=(10, 0))
    for col, rotulo in enumerate(("Plataforma", "rclone", "Python", "")):
        ttk.Label(tabla, text=rotulo, style="Rotulo.TLabel").grid(
            row=0, column=col, sticky="w", padx=(0, 18))

    filas: dict[str, tuple] = {}

    def cambiar(plat, var) -> None:
        """Marca o quita una plataforma, y pregunta antes de borrar."""
        if var.get():
            wiz.matriz.elegir(plat.clave)
        elif wiz.matriz.quitar(plat.clave):
            wiz.matriz.confirmar_borrado(plat.clave, _preguntar_borrado(wiz, plat))
        refrescar()

    for i, fila in enumerate(matriz.filas(), start=1):
        plat = fila.plataforma
        var = tk.BooleanVar(value=fila.elegida)
        texto = plat.nombre + ("  ·  este equipo" if fila.anfitrion else "")
        ttk.Checkbutton(tabla, text=texto, variable=var,
                        command=lambda p=plat, v=var: cambiar(p, v)).grid(
            row=i, column=0, sticky="w", padx=(0, 18))
        rclone_lbl = ttk.Label(tabla, style="Mono.TLabel")
        rclone_lbl.grid(row=i, column=1, sticky="w", padx=(0, 18))
        python_lbl = ttk.Label(tabla, style="Mono.TLabel")
        python_lbl.grid(row=i, column=2, sticky="w", padx=(0, 18))
        nota = ttk.Label(tabla, style="Pista.TLabel")
        nota.grid(row=i, column=3, sticky="w")
        filas[plat.clave] = (var, rclone_lbl, python_lbl, nota)

    total = ttk.Label(marco, style="Fuerte.TLabel")
    total.grid(row=2, column=0, sticky="w", pady=(10, 0))
    plan_lbl = ttk.Label(marco, style="Pista.TLabel", justify="left",
                         wraplength=theme.medida(760))
    plan_lbl.grid(row=3, column=0, sticky="w", pady=(4, 0))
    avisos = ttk.Frame(marco, style="Ambar.TFrame", padding=(11, 9))
    avisos.columnconfigure(0, weight=1)
    avisos_lbl = ttk.Label(avisos, style="Ambar.TLabel", justify="left",
                           wraplength=theme.medida(740))
    avisos_lbl.grid(row=0, column=0, sticky="w")

    def pintar() -> None:
        """Pinta el estado de cada fila, el total y los avisos."""
        m = wiz.matriz
        modo.set("completa" if m.completa else "ligera")
        for fila in m.filas():
            var, rclone_lbl, python_lbl, nota = filas[fila.plataforma.clave]
            var.set(fila.elegida)
            rclone_lbl.configure(text=f"≈{fila.mb_rclone} MB")
            python_lbl.configure(
                text=f"≈{fila.mb_python} MB" if m.completa else "—",
                style="Mono.TLabel" if m.completa else "Apagado.TLabel")
            if fila.se_borra:
                nota.configure(text="se borrará", style="Peligro.TLabel")
            elif fila.instalada and (fila.instalada.runtime or not m.completa):
                nota.configure(text="ya en el dispositivo", style="Ok.TLabel")
            elif fila.instalada:
                nota.configure(text="ya lleva rclone", style="Pista.TLabel")
            else:
                nota.configure(text="", style="Pista.TLabel")
        libre = platforms.free_bytes(raiz)
        total.configure(text=f"Total: ≈{m.total_mb()} MB"
                        + (f"   ·   libres en el dispositivo: {libre / 2 ** 30:.1f} GB"
                           if libre is not None else ""))
        plan_lbl.configure(text="\n".join(m.plan().consecuencias()))
        dichos = m.avisos(libre)
        if dichos:
            avisos_lbl.configure(text="\n".join(dichos))
            avisos.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        else:
            avisos.grid_remove()

    def refrescar() -> None:
        """Repinta y avisa a quien la usa."""
        # La primera vez se pinta sin avisar a nadie: quien llama todavía está
        # montando su paso, y su botón aún no existe.
        pintar()
        al_cambiar()
        wiz.revisar()

    pintar()
    return marco, refrescar


def _texto_fuera(fisica) -> str:
    """Devuelve lo que «Añadir plataformas…» rehace fuera del contenedor, si lo hay.

    Son la entrada y, si la unidad lleva VeraCrypt, el VeraCrypt
    (`traveler.lo_que_hara`).
    """
    if fisica is None:
        return ""
    return (f"\n\nFuera del contenedor, en {fisica}, se rehace la entrada "
            f"(«{vestibulo.NOMBRE_ABRIR}», «{vestibulo.NOMBRE_EXPULSAR}»)."
            + (f" {traveler.lo_que_hara(fisica)}" if traveler.lleva(fisica) else ""))


def _paso_plataformas(cuerpo, wiz) -> None:
    """Pinta la lista de plataformas sobre un dispositivo que ya existe.

    No se vuelve a aprovisionar nada: la conexión, las parejas, el estado de
    bisync y el programa se quedan como están. Lo que se marque se descarga
    (comprobado) y se copia; lo que se quite y se confirme, se borra. Los
    lanzadores sí se escriben (esto ES aprovisionar, a su escala): un
    dispositivo de antes solo tenía el `.pyw` y, con Python propio y sin
    `.bat`, ese Python no lo usaría nadie.
    """
    from tkinter import ttk

    raiz = wiz.device_root or wiz.state.device
    ttk.Label(cuerpo, justify="left", wraplength=theme.medida(780), text=(
        f"Qué rclone y qué Python lleva:\n\n"
        f"    {deploy.app_dir(raiz)}\n\n"
        "Se conserva todo lo demás: tu configuración, tus claves, el estado de "
        "bisync y el programa. Lo que marques se descarga —comprobando su "
        "SHA-256— y se copia; lo que quites y confirmes, se borra."
        + _texto_fuera(vestibulo.destino(wiz.state)))).grid(
        row=0, column=0, sticky="w")

    lista, refrescar_lista = _lista_plataformas(cuerpo, wiz, raiz,
                                                al_cambiar=lambda: boton_estado())
    lista.grid(row=1, column=0, sticky="ew", pady=(14, 0))

    estado_lbl = ttk.Label(cuerpo, wraplength=theme.medida(780), justify="left",
                           foreground=theme.TINTA3)
    estado_lbl.grid(row=2, column=0, sticky="w", pady=(12, 0))

    def aplicar() -> None:
        """Aplica la lista de plataformas, en un hilo."""
        if not wiz.matriz.listo:
            return
        plan = wiz.matriz.plan()

        def trabajo():
            """Pone y quita plataformas y rehace la entrada de fuera y VeraCrypt."""
            nuevos, borrados = deploy.apply_platforms(raiz, plan)
            lanzadores = deploy.write_launchers(raiz, plan.completa)
            # La entrada de fuera, por lo mismo que los lanzadores: un
            # dispositivo VeraCrypt de antes no la tiene, y este es el camino
            # que existe para ponérsela sin reinstalar.
            fisica = vestibulo.destino(wiz.state)
            ident = device.control_id(raiz) if fisica is not None else None
            entrada = vestibulo.escribir(fisica, ident) if ident else []
            # Y el VeraCrypt que viaja, si lleva uno: el vestíbulo que se acaba
            # de escribir sabe abrir el portable y la copia de antes, así que
            # primero él y después la carpeta, y los dos quedan coherentes pase
            # lo que pase con la segunda. Es el único camino de un VeraCrypt
            # SIN sello: `--update-components` no lo toca
            # (`install/components.py`).
            nota = ""
            viajero: list = []
            if fisica is not None and traveler.lleva(fisica):
                try:
                    puesto = traveler.llevar(wiz.state.veracrypt, fisica)
                    viajero = puesto.ficheros
                    nota = puesto.aviso
                except InstallError as e:
                    nota = f"El VeraCrypt de la unidad se queda como estaba: {e}"
            hecho = platforms.Hecho(puestos=len(nuevos), borrados=len(borrados),
                                    lanzadores=len(lanzadores), entrada=len(entrada),
                                    veracrypt=len(viajero))
            return hecho, nota

        ok, res = working(wiz.root, "plataformas", trabajo,
                          "Descargando y copiando rclone y Python.")
        if not ok:
            estado_lbl.configure(text=f"No se ha podido aplicar: {res}",
                                 foreground=theme.PELIGRO)
            wiz.revisar()           # lo mismo que en «Instalación» (#49)
            wiz.visor.ver(boton)
            return
        hecho, nota = res
        wiz.rehacer_matriz(raiz)
        refrescar_lista()
        estado_lbl.configure(
            text=(f"{hecho.texto()} Ya puedes cerrar." + (f"\n\n{nota}" if nota else "")),
            foreground=theme.AVISO if nota else theme.OK)
        wiz.revisar()

    boton = ttk.Button(cuerpo, text="Aplicar", style="Primary.TButton",
                       padding=(14, 8), command=aplicar)
    boton.grid(row=3, column=0, sticky="w", pady=(14, 0))

    def boton_estado() -> None:
        """Habilita «Aplicar» si la lista está lista."""
        listo = wiz.matriz is not None and wiz.matriz.listo
        boton.configure(state="normal" if listo else "disabled")

    boton_estado()


def _paso_parejas(cuerpo, wiz) -> None:
    """Pinta el paso de las parejas que va a sincronizar ESTE dispositivo."""
    import tkinter as tk
    from tkinter import ttk

    ttk.Label(cuerpo, justify="left", wraplength=theme.medida(780), text=(
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
            ttk.Label(marco, foreground=theme.PELIGRO, justify="left",
                      wraplength=theme.medida(260),
                      text=f"espejo: borra en {destino} lo que no esté en el origen"
                      ).grid(row=i, column=2, sticky="w", padx=(12, 0))

    resultado = ttk.Label(cuerpo, wraplength=theme.medida(780), justify="left",
                          foreground=theme.TINTA3)
    resultado.grid(row=2, column=0, sticky="w", pady=(14, 0))

    def guardar() -> None:
        """Escribe el config con las parejas elegidas y crea sus carpetas."""
        seleccion = [n for n, v in elegidas.items() if v.get()]
        try:
            destino = deploy.write_device_config(
                wiz.device_root, wiz.catalog, seleccion,
                endpoint=wiz.perfil.endpoint_catalog,
                catalog_path=wiz.perfil.catalog_path)
            creadas = deploy.make_local_dirs(wiz.device_root, wiz.catalog, seleccion)
        except InstallError as e:
            wiz.error(str(e))
            return
        except Exception as e:                       # noqa: BLE001
            wiz.error(f"{type(e).__name__}: {e}")
            return
        wiz.state.selected = seleccion
        wiz.state.config_written = True
        # Y queda apuntado en el registro de la flota, que es lo que permite ver
        # desde cualquier dispositivo cuántos hay y cómo están. Mejor esfuerzo:
        # si el remoto no acepta la nota, la instalación ya está hecha igual y la
        # primera sincronización volverá a intentarlo.
        nota = deploy.publish_fleet_note(wiz.rclone, wiz.device_root,
                                         wiz.perfil.endpoint_catalog)
        detalle = f"Escrito {destino} con {len(seleccion)} pareja(s)."
        if creadas:
            detalle += "\nCarpetas creadas: " + ", ".join(p.name for p in creadas)
        detalle += ("\nApuntado en la flota: " + nota if nota else
                    "\n(no se ha podido apuntar en la flota; se hará al sincronizar)")
        resultado.configure(text=detalle, foreground=theme.OK)
        wiz.revisar()

    ttk.Button(cuerpo, text="Guardar el config y crear las carpetas",
               command=guardar).grid(row=3, column=0, sticky="w", pady=(12, 0))


def _paso_llavero(cuerpo, wiz) -> None:
    """Pinta el paso del llavero: sin él, con una base propia o con la del remoto.

    Lo que se decide es de `install/llavero.py`; aquí se elige, se enseña qué
    va a pasar y se pone con un botón, como el config en el paso anterior. Se
    puede seguir sin llavero: se activa después en «Ajustes → Llavero».
    """
    import tkinter as tk
    from tkinter import filedialog, ttk

    from install import llavero as llavero_install

    remota = llavero_install.tabla_remota(wiz.catalog)
    ttk.Label(cuerpo, justify="left", wraplength=theme.medida(780), text=(
        "El llavero es una base de KeePassXC (contraseñas y passkeys) que viaja en el "
        "dispositivo y se sincroniza sola con la carpeta del catálogo. Es opcional: se "
        "puede activar después, en «Ajustes → Llavero» de la ventana de prdrive.")
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

    eleccion = tk.StringVar(value=wiz.llavero_eleccion)
    pide = tk.BooleanVar(value=wiz.llavero_pide)
    opciones = ttk.Frame(cuerpo)
    opciones.grid(row=1, column=0, sticky="w")
    textos = [("no", "Sin llavero"), ("propia", "Usar una base propia")]
    if remota is not None:
        textos.append(("remoto", f"Traer el del remoto ({remota.get('base')})"))
    radios = []
    for i, (valor, texto) in enumerate(textos):
        radio = ttk.Radiobutton(opciones, text=texto, value=valor, variable=eleccion,
                                command=lambda: cambiar())
        radio.grid(row=i, column=0, sticky="w", pady=2)
        radios.append(radio)

    detalle = ttk.Frame(cuerpo)
    detalle.grid(row=2, column=0, sticky="w", pady=(10, 0))
    base_lbl = ttk.Label(detalle, style="MonoPista.TLabel")
    elegir_base = ttk.Button(detalle, text="Elegir la base…", style="Quiet.TButton",
                             command=lambda: escoger_base())
    con_llave = ttk.Checkbutton(detalle, text="La base usa un fichero llave", variable=pide,
                                command=lambda: cambiar())
    llave_lbl = ttk.Label(detalle, style="MonoPista.TLabel")
    elegir_llave = ttk.Button(
        detalle, text=("Elegir el fichero llave…" if (remota or {}).get("llave_interna")
                       else "Dónde está en este equipo…"),
        style="Quiet.TButton", command=lambda: escoger_llave())

    resultado = ttk.Label(cuerpo, wraplength=theme.medida(780), justify="left",
                          foreground=theme.TINTA3)
    resultado.grid(row=3, column=0, sticky="w", pady=(12, 0))
    boton = ttk.Button(cuerpo, text="Poner el llavero", style="Primary.TButton",
                       command=lambda: poner())
    boton.grid(row=4, column=0, sticky="w", pady=(12, 0))

    def pide_llave() -> bool:
        """Indica si la base que va a ir pide fichero llave."""
        if eleccion.get() == "propia" and remota is None:
            return pide.get()
        return eleccion.get() != "no" and bool((remota or {}).get("fichero_llave"))

    def pensar():
        """Devuelve el plan de lo elegido, o `None` si falta algo o no se pone nada."""
        que = eleccion.get()
        if que == "no" or (que == "propia" and wiz.llavero_base is None):
            return None
        llave = wiz.llavero_llave if pide_llave() else None
        return llavero_install.pensar(
            wiz.device_root, wiz.catalog, wiz.llavero_base if que == "propia" else None,
            pide.get(), llave.name if llave is not None else "", llave,
            cifrado=_cifrado_del_dispositivo(wiz))

    def cambiar() -> None:
        """Repinta lo que depende de lo elegido, y lo que va a pasar."""
        wiz.llavero_eleccion, wiz.llavero_pide = eleccion.get(), pide.get()
        for widget in (base_lbl, elegir_base, con_llave, llave_lbl, elegir_llave):
            widget.grid_remove()
        que = eleccion.get()
        if que == "propia":
            base_lbl.configure(text=str(wiz.llavero_base or "(sin elegir)"))
            base_lbl.grid(row=0, column=0, sticky="w")
            elegir_base.grid(row=0, column=1, sticky="w", padx=(10, 0))
            if remota is None:
                con_llave.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        if pide_llave():
            llave_lbl.configure(text=str(wiz.llavero_llave or "(sin decir)"))
            llave_lbl.grid(row=2, column=0, sticky="w", pady=(6, 0))
            elegir_llave.grid(row=2, column=1, sticky="w", padx=(10, 0), pady=(6, 0))
        if wiz.llavero_hecho:
            boton.configure(state="disabled")
            for radio in radios:
                radio.configure(state="disabled")
            wiz.revisar()
            return
        try:
            plan = pensar()
        except InstallError as e:
            resultado.configure(text=str(e), foreground=theme.PELIGRO)
            boton.configure(state="disabled")
            wiz.revisar()
            return
        if plan is None:
            resultado.configure(text=("Se sigue sin llavero." if que == "no" else
                                      "Elige la base."), foreground=theme.TINTA3)
            boton.configure(state="disabled")
        else:
            resultado.configure(text="\n".join(plan.lineas + plan.avisos),
                                foreground=theme.TINTA3)
            boton.configure(state="normal")
        wiz.revisar()

    def escoger_base() -> None:
        """Pregunta qué base de KeePassXC lleva el llavero."""
        elegida = filedialog.askopenfilename(
            parent=wiz.root, title="¿Qué base de KeePassXC lleva el llavero?",
            filetypes=[("Bases de KeePassXC", "*.kdbx"), ("Todos los ficheros", "*.*")])
        if elegida:
            wiz.llavero_base = Path(elegida)
        cambiar()

    def escoger_llave() -> None:
        """Pregunta dónde está el fichero llave en este equipo: solo la ruta."""
        elegida = filedialog.askopenfilename(
            parent=wiz.root, title="¿Dónde está el fichero llave en este equipo?")
        if elegida:
            wiz.llavero_llave = Path(elegida)
        cambiar()

    def poner() -> None:
        """Pone el llavero en el dispositivo: KeePassXC, el catálogo y lo de dentro."""
        try:
            plan = pensar()
        except InstallError as e:
            resultado.configure(text=str(e), foreground=theme.PELIGRO)
            return
        if plan is None:
            return
        pedido = wiz.catalog.endpoint or wiz.perfil.endpoint_catalog
        ok, res = working(wiz.root, "llavero",
                          lambda: llavero_install.aplicar(plan, wiz.device_root, wiz.rclone,
                                                          pedido),
                          "Descargando KeePassXC y poniendo el llavero en el dispositivo.")
        if not ok:
            resultado.configure(text=f"No se ha podido poner el llavero: {res}",
                                foreground=theme.PELIGRO)
            wiz.revisar()
            wiz.visor.ver(boton)
            return
        wiz.llavero_hecho = True
        cambiar()
        resultado.configure(text="Llavero puesto. La primera pasada, en «Inicialización», "
                                 "sube la base o trae la del remoto.", foreground=theme.OK)

    cambiar()


def _cifrado_del_dispositivo(wiz):
    """Devuelve si el dispositivo que se prepara va cifrado, según lo elegido en «Cifrado».

    `cifrada.estado()` miraría el equipo del asistente, no el dispositivo.
    """
    from common import cifrada
    como = wiz.state.encryption
    if como in (cifrada.VERACRYPT, cifrada.BITLOCKER):
        return cifrada.Cifrado(True, como)
    return cifrada.Cifrado(False, "", "El dispositivo no se ha cifrado (paso «Cifrado»).")


def _ok_llavero(w) -> bool:
    """Indica si se puede seguir desde el paso del llavero: sin él, o ya puesto."""
    return w.llavero_eleccion == "no" or w.llavero_hecho


def _paso_inicializar(cuerpo, wiz) -> None:
    """Pinta el paso que hace el `--resync` de las parejas bisync."""
    from tkinter import ttk

    bisync = deploy.resync_targets(wiz.catalog, wiz.state.selected)
    if wiz.llavero_hecho:
        bisync.append(model.LLAVERO)          # su primera pasada sube o trae la base
    espejos = deploy.mirror_pairs(wiz.catalog, wiz.state.selected)

    ttk.Label(cuerpo, justify="left", wraplength=theme.medida(780), text=(
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
        ttk.Label(cuerpo, foreground=theme.PELIGRO, justify="left",
                  wraplength=theme.medida(780), text=(
            "No se inicializan aquí: " + ", ".join(espejos) + ".\n"
            "Son espejos: borran en el otro lado lo que no esté en el origen, y "
            "lanzarlos con las carpetas locales recién creadas propagaría ese "
            "vacío. Cuando el dispositivo esté como quieres, pruébalos a mano con "
            "--dry-run.")).grid(row=2, column=0, sticky="w", pady=(12, 0))

    resultado = ttk.Label(cuerpo, wraplength=theme.medida(780), justify="left",
                          foreground=theme.TINTA3)
    resultado.grid(row=3, column=0, sticky="w", pady=(12, 0))

    def inicializar() -> None:
        """Lanza el resync en la ventana de salida."""
        # La raíz de un equipo no lleva Python: la inicializa el del agente, el
        # mismo que la sincronizará.
        python = (raiz_equipo.python_consola(wiz.agente_prep.python)
                  if wiz.donde == "equipo" and wiz.agente_prep is not None else None)
        try:
            cmd = deploy.resync_command(wiz.device_root, bisync, python)
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


def _paso_final(cuerpo, wiz) -> None:
    """Pinta el paso de verificación y cierre."""
    from tkinter import ttk

    ttk.Label(cuerpo, justify="left", wraplength=theme.medida(780), text=(
        "Lo que de verdad hace falta para que este dispositivo arranque en "
        "cualquier equipo. Lo que falte aquí es lo que fallaría luego sin que se "
        "entienda por qué.")).grid(row=0, column=0, sticky="w", pady=(0, 10))

    tabla = ttk.Frame(cuerpo)
    tabla.grid(row=1, column=0, sticky="w")

    def revisar_dispositivo() -> None:
        """Repinta las comprobaciones del dispositivo."""
        for hijo in tabla.winfo_children():
            hijo.destroy()
        perfil = wiz.perfil_final
        clave = perfil.key_name if perfil.needs_key else None
        checks = device.verify_device(wiz.device_root, wiz.state.selected, clave)
        # Solo con contenedor: sin él no hay nada que montar en el otro equipo, y
        # una fila roja diciendo que falta VeraCrypt sería mentira. Lo mismo
        # con la instalación en claro que quedó fuera: solo es un resto cuando
        # la de verdad está dentro de un contenedor.
        if wiz.state.encryption == "veracrypt" and wiz.state.device:
            checks += vestibulo.comprobar(wiz.state.device,
                                          device.control_id(wiz.device_root))
            checks += traveler.comprobar(wiz.state.device)
            checks += crypto.comprobar_restos(wiz.state.device)
        for i, chk in enumerate(checks):
            color = theme.OK if chk.ok else theme.PELIGRO
            ttk.Label(tabla, text="✔" if chk.ok else "✘", foreground=color,
                      width=3).grid(row=i, column=0, sticky="w")
            ttk.Label(tabla, text=chk.etiqueta + ":").grid(row=i, column=1, sticky="w")
            ttk.Label(tabla, text=chk.detalle, foreground=color, wraplength=theme.medida(520),
                      justify="left").grid(row=i, column=2, sticky="w", padx=(10, 0))

    revisar_dispositivo()

    extras = ttk.LabelFrame(cuerpo, text="Y ya que estamos", padding=10)
    extras.grid(row=2, column=0, sticky="w", pady=(14, 0))

    from common import equipo
    agente = equipo.instalado()

    def instalar_vigilante() -> None:
        """Pide que atienda el dispositivo el agente, o instala penwatch."""
        if agente:
            # Con el agente residente en este equipo, penwatch sobra: se le pide
            # a él que atienda este dispositivo (lo escribe él, en su lista).
            uid = device.control_id(wiz.device_root)
            if not uid or not equipo.pedir({"pide": equipo.PIDE_MODO, "id": uid,
                                            "modo": equipo.MODO_AL_ATENDER}):
                wiz.error("No he podido pedírselo al agente de este equipo.")
                return
            wiz.aviso("El agente de este equipo sincronizará este dispositivo en "
                      "segundo plano cada vez que lo enchufes.")
            return
        try:
            cmd = deploy.penwatch_install_command(wiz.device_root)
        except InstallError as e:
            wiz.error(str(e))
            return
        output_window("instalar el vigilante", cmd, parent=wiz.root)

    def guardar_en_catalogo() -> None:
        """Enseña la conexión que habría que dejar en el catálogo.

        Es lo que hace que esto se teclee una sola vez: el siguiente
        dispositivo la hereda de ahí en vez de volver a preguntarla. La clave
        NO viaja: solo las opciones del backend.
        """
        wiz.aviso(
            "La conexión se guarda en el catálogo desde la ventana de parejas del "
            "propio dispositivo (Catálogo → [defaults]), que es la que sabe "
            "releerlo y negarse si otro dispositivo lo ha tocado mientras tanto.\n\n"
            f"Lo que hay que guardar es:\n\n"
            f"[remote]\n" + "\n".join(
                f"{k} = {v}" for k, v in
                profile.to_catalog_remote(wiz.perfil_final).items()))

    def llevar_veracrypt() -> None:
        """Deja, o pone al día, el VeraCrypt que viaja en el dispositivo.

        Es el VeraCrypt Portable oficial, comprobado, con x64 y ARM64; sin red,
        la copia del de este equipo (`traveler.instalar()`). Nunca se copia
        encima: la carpeta se sustituye entera y, si no cabe, no se toca.
        """
        if wiz.state.encryption != "veracrypt" or not wiz.state.device:
            wiz.error("Esto solo tiene sentido con un contenedor VeraCrypt.")
            return
        ok, puesto = working(
            wiz.root, "llevando VeraCrypt",
            lambda: traveler.llevar(wiz.state.veracrypt, wiz.state.device),
            "Dejando VeraCrypt en la unidad, fuera del contenedor.")
        if not ok:
            wiz.error(str(puesto))
            return
        arcs = traveler.arquitecturas(puesto.carpeta)
        wiz.aviso(
            (f"{puesto.carpeta} ya llevaba este VeraCrypt: no se ha tocado."
             if puesto.al_dia else
             f"{len(puesto.ficheros)} ficheros en {puesto.carpeta}.")
            + f"\n\nArquitecturas: {', '.join(arcs) or 'ninguna (falta el driver)'}. "
            "Cada una solo vale en la suya: un driver no se emula.\n\n"
            + (f"{puesto.aviso}\n\n" if puesto.aviso else "")
            + "En el equipo donde se enchufe seguirá haciendo falta aceptar el "
            "aviso de administrador: cargar el driver no se puede hacer de otra "
            "forma.")
        revisar_dispositivo()

    def desmontar() -> None:
        """Desmonta el contenedor que montó este instalador."""
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
            ("Que lo atienda el agente de este equipo" if agente else
             "Instalar el arranque automático (penwatch)", instalar_vigilante),
            ("Compartir esta conexión con otros dispositivos", guardar_en_catalogo),
            ("Llevar VeraCrypt en el dispositivo", llevar_veracrypt),
            ("Desmontar el contenedor", desmontar),
            ("Volver a comprobar", revisar_dispositivo))):
        ttk.Button(extras, text=texto, command=accion).grid(
            row=i // 2, column=i % 2, sticky="w", padx=(0, 8), pady=2)


def _ok_conexion(w) -> bool:
    """Indica si se puede seguir desde el paso de la conexión."""
    return w.perfil.configured and not w.perfil.problema_catalogo


def _ok_comprobaciones(w) -> bool:
    """Indica si se puede seguir desde el paso de las comprobaciones."""
    return w.rclone is not None and w.catalog is not None


def _ok_destino(w) -> bool:
    """Indica si se puede seguir desde el paso del dispositivo.

    Con una unidad que ya es un prdrive hay que decir antes qué se va a hacer:
    dejar «Siguiente» encendido junto a los dos botones del desvío daría tres
    formas de avanzar y dos destinos distintos; apagarlo hasta que se elija es
    el mismo criterio que sigue el resto del asistente.
    """
    if w.state.device is None:
        return False
    return not w.ya_instalado or w.modo is not None


def _ok_cifrado(w) -> bool:
    """Indica si se puede seguir desde el paso de cifrado."""
    return w.state.device_root is not None


def _ok_instalacion(w) -> bool:
    """Indica si se puede seguir desde el paso de la instalación.

    Para pasar de aquí hay que haber instalado EN ESTA pasada. Si bastara con
    que `sync.py` ya existiese en la unidad, sobre un dispositivo ya instalado
    «Siguiente» llegaría activado y se podría pasar de largo sin copiar nada;
    el paso siguiente sí escribe un `sync_config.toml` recién generado, y el
    resultado sería un dispositivo con config nuevo sobre código viejo: pide
    cosas que su código no sabe hacer (como `device_remote` en los
    `[defaults]`) y no se nota hasta que falla la primera pasada. Reinstalar es
    esta lista de pasos; para poner el código al día sin repetir conexión ni
    parejas está el recorrido corto («Actualizar»), que sí copia.
    """
    return w.state.deployed


def _ok_parejas(w) -> bool:
    """Indica si se puede seguir desde el paso de las parejas."""
    return w.state.config_written


PASOS_INSTALACION = [
    ("¿Dónde?", _paso_donde, _ok_donde),
    ("Dispositivo", _paso_destino, _ok_destino),
    ("Cifrado", _paso_cifrado, _ok_cifrado),
    ("Conexión", _paso_conexion, _ok_conexion),
    ("Comprobaciones", _paso_comprobaciones, _ok_comprobaciones),
    ("Instalación", _paso_instalar, _ok_instalacion),
    ("Parejas y configuración", _paso_parejas, _ok_parejas),
    ("Llavero", _paso_llavero, _ok_llavero),
    ("Inicialización", _paso_inicializar, lambda w: True),
    ("Verificación", _paso_final, lambda w: True),
]
"""El recorrido de instalar una unidad: título, pintor y condición de cada paso.

El dispositivo va PRIMERO, y no es cosmético: es lo que permite reconocer una
unidad que ya es un prdrive y ofrecer actualizarla en dos pantallas en vez de
repetir el aprovisionamiento entero. El orden de los demás lo manda lo que
necesita cada uno: «Cifrado» va pegado a «Dispositivo» porque es quien fija
`state.device_root`, que es donde escribe «Instalación»; y «Conexión» y
«Comprobaciones» pueden ir después porque el catálogo no hace falta hasta
«Parejas».
"""

PASOS_ACTUALIZACION = [
    ("¿Dónde?", _paso_donde, _ok_donde),
    ("Dispositivo", _paso_destino, _ok_destino),
    ("Actualización", _paso_actualizar, lambda w: True),
]
"""El recorrido corto de actualizar una unidad que ya es un prdrive.

Solo hay que ponerle el código del instalador. Ni conexión, ni catálogo, ni
parejas: nada de eso cambia al actualizar y pedirlo otra vez sería pedirlo para
nada.
"""

PASOS_PLATAFORMAS = [
    ("¿Dónde?", _paso_donde, _ok_donde),
    ("Dispositivo", _paso_destino, _ok_destino),
    ("Plataformas", _paso_plataformas, lambda w: True),
]
"""El otro recorrido corto: «Añadir plataformas…».

Es la misma lista que el paso «Instalación», sobre un dispositivo que ya existe
y sin tocar nada más.
"""


def _paso_equipo(nombre: str):
    """Devuelve el pintor de un paso de `ui/tk_equipo.py`, importado al pintarlo.

    Así este módulo no arrastra `install/agente` (y con él penwatch) a quien
    solo prepara unidades.
    """
    def dibujar(cuerpo, wiz) -> None:
        """Pinta el paso importando `tk_equipo` en ese momento."""
        from . import tk_equipo
        getattr(tk_equipo, nombre)(cuerpo, wiz)
    return dibujar


def _ok_equipo(nombre: str):
    """Devuelve la condición de un paso de `ui/tk_equipo.py`."""
    def condicion(wiz) -> bool:
        """Pregunta a `tk_equipo` si se puede seguir."""
        from . import tk_equipo
        return getattr(tk_equipo, nombre)(wiz)
    return condicion


PASOS_EQUIPO = [
    ("¿Dónde?", _paso_donde, _ok_donde),
    ("Raíz", _paso_equipo("paso_raiz"), lambda w: True),
    ("Cifrado", _paso_equipo("paso_cifrado"), _ok_equipo("ok_cifrado")),
    ("Carpeta", _paso_equipo("paso_carpeta"), _ok_equipo("ok_carpeta")),
    ("Conexión", _paso_conexion, _ok_conexion),
    ("Comprobaciones", _paso_comprobaciones, _ok_comprobaciones),
    ("Instalación", _paso_equipo("paso_instalar"), _ok_equipo("ok_instalar")),
    ("Parejas y configuración", _paso_equipo("paso_parejas"), _ok_equipo("ok_parejas")),
    ("Inicialización", _paso_inicializar, lambda w: True),
    ("Unidades", _paso_equipo("paso_unidades"), lambda w: True),
    ("Arranque", _paso_equipo("paso_arranque"), _ok_equipo("ok_arranque")),
    ("Verificación", _paso_equipo("paso_final"), lambda w: True),
]
"""El recorrido «En este equipo», con una raíz en una carpeta del ordenador.

Es el recorrido de una unidad con otra cabeza y otra cola: «Raíz» dice qué
forma tiene, «Cifrado» si va en un contenedor y «Carpeta» la carpeta exacta (la
raíz, o dónde va el contenedor y dónde se abre), por ese orden, porque cifrar
cambia qué carpeta se pide. «Carpeta» fija `state.device_root` (la carpeta, o
el volumen montado del contenedor) y va antes de «Conexión» por lo mismo que en
una unidad: fija dónde escribe «Instalación». Detrás de «Inicialización» van
los del agente. «Instalación» va antes de «Parejas» por lo mismo que en una
unidad y además porque deja el Python del agente con el que se inicializa.
"""

PASOS_EQUIPO_SOLO = [
    ("¿Dónde?", _paso_donde, _ok_donde),
    ("Raíz", _paso_equipo("paso_raiz"), lambda w: True),
    ("Instalación", _paso_equipo("paso_instalar"), _ok_equipo("ok_instalar")),
    ("Unidades", _paso_equipo("paso_unidades"), lambda w: True),
    ("Arranque", _paso_equipo("paso_arranque"), _ok_equipo("ok_arranque")),
    ("Verificación", _paso_equipo("paso_final"), lambda w: True),
]
"""El recorrido «Ninguna: solo atender unidades», la instalación «solo agente».

Sin conexión, ni catálogo, ni clave: cada unidad trae las suyas. «Raíz» sigue
en el índice 1 para que cambiar de respuesta no mueva a la persona de paso.
"""


def pasos_equipo(wiz) -> list:
    """Devuelve la lista de «En este equipo» que toca según lo elegido en «Raíz»."""
    return (PASOS_EQUIPO_SOLO if wiz.equipo_forma == raiz_equipo.NINGUNA
            else PASOS_EQUIPO)


if __name__ == "__main__":          # pragma: no cover - atajo para probar a mano
    sys.exit(run_wizard())
