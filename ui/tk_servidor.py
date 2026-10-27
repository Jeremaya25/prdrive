#!/usr/bin/env python3
"""La ventana «Servidor»: recorre el remoto sin tocarlo.

Solo dibuja. Qué se enseña y cómo se navega lo decide `ui/servidor.py`, que no
importa Tk; el `rclone rcd` que contesta es `common/rcd.py`. Aquí se conecta
una cosa con la otra: la barra (remote, ruta, «↑», «Releer»), la línea del
indicador, la lista y el pie.

La lista es una `ttk.Treeview`, como la de «Carpetas del remoto»
(`tk_pairs.explorador_remoto`): solo pinta las filas que se ven, así que una
carpeta con miles de entradas cuesta lo mismo que una con diez. La tabla de un
solo lienzo (`tk.Tabla`) pide su alto entero y, pasadas unas 850 filas, el
servidor X mata el proceso con `BadAlloc`.

La ventana se abre en el acto y lee después (regla #66 de `ui.md`). El `Popen`
del `rcd` va en el hilo de Tk (`rcd.arrancar()`: en Linux el hijo muere cuando
muere el hilo que lo lanzó); lo que espera a la red (`esperar()`, el
`operations/fsinfo` del remote y el listado) va en segundo plano y lo recoge el
`Sondeo` de la ventana. Cada petición nueva sustituye a la anterior: gana la
última, y una respuesta tardía no pinta nada.

Cerrar la ventana para el `rcd` también en segundo plano, una sola vez, sin
esperarlo. Nada de lo que hay aquí escribe en el remoto.
"""

from __future__ import annotations

from functools import partial
from typing import NamedTuple

from common import config_file, model, rcd
from common.model import Config, ConfigError

from . import icons, remote_picker, segundo_plano, servidor, theme
from .tk import Indicador, Sondeo, centrar, cuerpo_visible, modal, mostrar

COLUMNAS = [
    ("Nombre", 260, True),
    ("Tamaño", 90, False),
    ("Modificado", 140, False),
    ("Permisos", 90, False),
]
"""Las columnas de la lista: título, ancho en medidas del diseño y si estira.

La primera es la del árbol (`#0`), la única de una `Treeview` que lleva icono.
"""
FILAS_VISIBLES = 12
"""Cuántas filas enseña la lista sin desplazarse."""

VACIA = "Esta carpeta está vacía."
CONECTANDO = "Conectando con el servidor…"
SIN_REMOTES = "Este dispositivo no tiene conexión con ningún servidor."
MARCA_PAREJA = "  ⇄ "
"""Lo que se añade al nombre de una carpeta que es la de una pareja, antes del nombre de la pareja."""


class Lectura(NamedTuple):
    """Lo que trae una petición de listado.

    Args:
        permisos: Si los listados de este remote piden también los metadatos.
        mi_uid: El uid del usuario en el servidor, o `None` si no se sabe.
        entradas: Lo que hay en la carpeta pedida.
    """

    permisos: bool
    mi_uid: int | None
    entradas: tuple[servidor.Entrada, ...]


def _leer(r: rcd.Rcd, p: servidor.Peticion, tipo: str,
          sondeado: tuple[bool, int | None] | None, esperar: bool) -> Lectura:
    """Pide al `rcd` lo que hace falta para pintar la carpeta de `p`; corre en un hilo.

    Es lo que se encarga a `segundo_plano.lanzar()`: no lleva dentro nada de Tk.

    Args:
        r: El `rcd` al que se habla.
        p: La petición, con su remote y su carpeta.
        tipo: El `type =` del remote en `rclone.conf`.
        sondeado: `(permisos, mi_uid)` si ya se preguntó por este remote; con
            `None` se pregunta (`operations/fsinfo` y, si procede, el `stat`
            de la carpeta de inicio) antes de listar.
        esperar: Si hay que esperar antes a que `rcd` conteste (recién lanzado).

    Raises:
        ConfigError: Si `rcd` no arranca (`PuertoOcupado` entre ellos).
        rcd.ErrorRc: Si rclone contesta con un error.
        rcd.RcdCaido: Si no se puede hablar con `rcd`.
    """
    if esperar:
        r.esperar()
    if sondeado is None:
        # Mismo `fs` que los listados: rclone guarda un objeto (y una conexión SSH) por cadena.
        fsinfo = r.llamar("operations/fsinfo", {"fs": f"{p.remote}:/"})
        permisos = servidor.pide_permisos(fsinfo, tipo)
        mi_uid = None
        if permisos:
            try:
                mi_uid = servidor.mi_uid_de(r.llamar(
                    "operations/stat",
                    {"fs": f"{p.remote}:", "remote": "", "opt": {"metadata": True}}))
            except rcd.ErrorRc:
                pass        # sin saber quién soy, solo se pierde el candado previo
    else:
        permisos, mi_uid = sondeado
    respuesta = r.llamar("operations/list", servidor.params_listado(p.remote, p.ruta, permisos))
    return Lectura(permisos, mi_uid, servidor.entradas_de(respuesta))


class FilaLista(NamedTuple):
    """Una fila de la lista, lista para insertar en la `Treeview`.

    Args:
        iid: El nombre de la entrada (único dentro de una carpeta).
        texto: Lo que se lee en la columna del árbol: el nombre y, si la carpeta
            es la de una pareja, su marca.
        valores: Tamaño, fecha y permisos.
        icono: `carpeta`, `file` o `candado`.
        tono: `apagado` para lo que no se puede abrir; si no, `ok`.
    """

    iid: str
    texto: str
    valores: tuple[str, str, str]
    icono: str
    tono: str


def _filas(nav: servidor.Navegacion, config: Config, mi_uid: int | None) -> list[FilaLista]:
    """Devuelve las filas de lo que enseña `nav`: icono, nombre, tamaño, fecha y permisos.

    Una carpeta que es la de una pareja lleva su nombre; una en la que no se
    puede entrar (ya falló, o sus permisos lo dicen con seguridad) lleva
    candado y va apagada.
    """
    filas = []
    for e in nav.entradas:
        nombre, tono, icono = e.nombre, "ok", "file"
        if e.es_carpeta:
            icono = "carpeta"
            hija = nav.hijo(e.nombre)
            pareja = servidor.marca(config, nav.remote, hija)
            if pareja:
                nombre += f"{MARCA_PAREJA}{pareja}"
            if (nav.remote, hija) in nav.sin_acceso or servidor.sin_acceso_previo(e, mi_uid):
                icono, tono = "candado", "apagado"
        filas.append(FilaLista(
            e.nombre, nombre,
            (servidor.tamano_legible(e.tamano), servidor.fecha_legible(e.fecha),
             servidor.texto_permisos(e.modo)),
            icono, tono))
    return filas


def _leer_conf() -> str:
    """Devuelve el `rclone.conf` del dispositivo, o nada si no se puede leer."""
    try:
        return model.RCLONE_CONF.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def open_dialog(parent, config: Config) -> None:
    """Abre la ventana «Servidor»; no devuelve nada.

    Lanza `rclone rcd` (en el hilo de Tk) y lo para al cerrar. Solo lee del
    remoto: no hay nada que repintar en la ventana que la abre.

    Args:
        parent: La ventana de la que cuelga.
        config: El config de este dispositivo: de él salen las parejas que se
            marcan en la lista y el remote interno que no se ofrece.
    """
    from tkinter import ttk

    dlg = modal(parent, "Servidor")
    sondeo = Sondeo(dlg)
    try:
        raw = config_file.load_raw()
    except ConfigError:
        raw = {}
    remotes = servidor.remotes_de(_leer_conf(), remote_picker.remote_de(raw),
                                  config.device_remote)
    nav = servidor.Navegacion(next(iter(remotes), ""))
    estado: dict = {"rcd": None, "ultima": ("ruta", servidor.RAIZ), "abierto": False,
                    "cerrado": False, "puerto_reintentado": False, "entradas": {}}
    sondeos: dict[str, tuple[bool, int | None]] = {}

    marco = cuerpo_visible(dlg, padding=(theme.E5, theme.E4, theme.E5, theme.E4))
    marco.columnconfigure(0, weight=1)

    barra = ttk.Frame(marco)
    barra.grid(row=0, column=0, sticky="ew")
    barra.columnconfigure(1, weight=1)
    elegido = ttk.Combobox(barra, state="readonly", values=list(remotes),
                           width=max([len(n) for n in remotes] + [8]) + 2)
    elegido.grid(row=0, column=0, sticky="w")
    ruta = ttk.Label(barra, style="MonoPista.TLabel", wraplength=theme.medida(420),
                     justify="left")
    ruta.grid(row=0, column=1, sticky="w", padx=(theme.E3, theme.E3))
    arriba = ttk.Button(barra, text="↑", style="Quiet.TButton", command=lambda: subir())
    theme.boton_icono(arriba, "arriba", theme.ACENTO, theme.PAPEL)
    arriba.configure(compound="image")      # el texto queda como nombre; sin icono, se ve él
    arriba.grid(row=0, column=2, sticky="e")
    releer = ttk.Button(barra, text="Releer", style="Quiet.TButton", command=lambda: repetir())
    theme.boton_icono(releer, "reload", theme.ACENTO, theme.PAPEL)
    releer.grid(row=0, column=3, sticky="e", padx=(theme.E2, 0))

    linea = ttk.Frame(marco)
    linea.grid(row=1, column=0, sticky="ew", pady=(theme.E3, 0))
    linea.columnconfigure(0, weight=1)
    indicador = Indicador(linea, ancho=520)
    indicador.marco.grid(row=0, column=0, sticky="ew")
    accion = ttk.Button(linea, text="", style="Quiet.TButton")
    accion.grid(row=0, column=1, sticky="e", padx=(theme.E3, 0))
    accion.grid_remove()
    dlg.indicador, dlg.sondeo = indicador, sondeo      # como en «Dispositivos»: los tests los miran

    # La carpeta y el archivo llevan su icono en la columna del árbol (#0), la única
    # de una `Treeview` que lo admite; el árbol no se despliega: se entra.
    tarjeta = ttk.Frame(marco, style="Card.TFrame",
                        padding=(theme.E2, theme.E2, theme.E1, theme.E1))
    tarjeta.grid(row=2, column=0, sticky="ew", pady=(theme.E4, 0))
    tarjeta.columnconfigure(0, weight=1)
    lista = ttk.Treeview(tarjeta, columns=("tamano", "modificado", "permisos"),
                         show=("tree", "headings"), height=FILAS_VISIBLES, selectmode="browse")
    for columna, (titulo, ancho, estira) in zip(("#0", "tamano", "modificado", "permisos"),
                                                COLUMNAS):
        lista.heading(columna, text=titulo, anchor="w")
        lista.column(columna, width=icons.px(lista, ancho), stretch=estira, anchor="w")
    lista.grid(row=0, column=0, sticky="nsew")
    theme.marcar_lista(lista)
    desplazar = ttk.Scrollbar(tarjeta, orient="vertical", command=lista.yview)
    lista.configure(yscrollcommand=desplazar.set)
    desplazar.grid(row=0, column=1, sticky="ns")
    # «Vacía» se dice con una etiqueta encima de la lista sin filas, y solo cuando
    # ha llegado un listado: una ventana que aún conecta no sabe si está vacía.
    vacia = ttk.Label(tarjeta, text=VACIA, style="Pista.TLabel")
    iconos = {nombre: icons.get(lista, nombre, 16, theme.TINTA3, theme.SUPERFICIE)
              for nombre in ("carpeta", "file", "candado")}
    dlg.lista, dlg.vacia, dlg.accion, dlg.elegido = lista, vacia, accion, elegido
    dlg.ruta, dlg.arriba = ruta, arriba

    pie = ttk.Frame(marco)
    pie.grid(row=3, column=0, sticky="ew", pady=(theme.E3, 0))
    pie.columnconfigure(0, weight=1)
    cuenta = ttk.Label(pie, text="", style="MonoPista.TLabel")
    cuenta.grid(row=0, column=0, sticky="w")
    ttk.Button(pie, text="Cerrar", command=lambda: cerrar_ventana()).grid(row=0, column=1)
    dlg.cuenta = cuenta

    # ------------------------------------------------------------- lo que se ve
    def decir(texto: str, tono: str = "Peligro.", boton: str | None = None) -> None:
        """Pone una frase en el indicador, sin barra, y con el botón de acción si toca."""
        indicador.poner(texto, False, tono)
        if boton is None:
            accion.grid_remove()
        else:
            accion.configure(text=boton, command={"Reconectar": reconectar,
                                                  "Reintentar": reintentar}[boton])
            accion.grid()

    def pintar_lista() -> None:
        """Pone en la lista las filas de lo que enseña `nav`."""
        mi_uid = sondeos.get(nav.remote, (False, None))[1]
        estado["entradas"] = {e.nombre: e for e in nav.entradas}
        lista.delete(*lista.get_children())
        for f in _filas(nav, config, mi_uid):
            foto = iconos[f.icono]
            lista.insert("", "end", iid=f.iid, text=f" {f.texto}", values=f.valores,
                         tags=(f.tono,), **({"image": foto} if foto is not None else {}))
        if estado["abierto"] and not nav.entradas:
            vacia.place(relx=0.5, rely=0.5, anchor="center")
        else:
            vacia.place_forget()

    def retocar() -> None:
        """Cambia el icono y el tono de las filas que ya están, sin rehacer la lista.

        Es lo que hace falta tras un permiso denegado: un candado nuevo, y que la
        lista no vuelva arriba ni pierda la fila elegida.
        """
        mi_uid = sondeos.get(nav.remote, (False, None))[1]
        for f in _filas(nav, config, mi_uid):
            if lista.exists(f.iid):
                foto = iconos[f.icono]
                lista.item(f.iid, tags=(f.tono,), **({"image": foto} if foto is not None else {}))

    def pintar() -> None:
        """Repinta todo con la carpeta que acaba de llegar: lista, ruta, aviso de pareja y pie."""
        estado["abierto"] = True
        pintar_lista()
        ruta.configure(text=nav.ruta)
        elegido.set(nav.remote)
        pareja = servidor.dentro_de(config, nav.remote, nav.ruta)
        if pareja:
            decir(f"Estás dentro de la pareja «{pareja}».", "Aviso.")
        else:
            decir("", "Pista.")
        cuenta.configure(text=servidor.cuantos(len(nav.entradas)))
        # La ventana nace con la lista vacía: al llegar el listado puede crecer (nunca mengua).
        if dlg.winfo_ismapped() and dlg.visor.crecer(dlg):
            centrar(dlg, parent)

    # ------------------------------------------------------------- el rcd
    def conectar(forzar: bool = False) -> bool:
        """Lanza `rclone rcd` en el hilo de Tk si no hay uno vivo (o siempre, con `forzar`).

        El que se deja se para en segundo plano: ya sea uno muerto o uno que
        no contesta, sigue apuntado en `store` hasta que se para.
        """
        viejo = estado["rcd"]
        if viejo is not None and viejo.vivo and not forzar:
            return True
        if viejo is not None:
            segundo_plano.lanzar(partial(viejo.parar))
        estado["rcd"] = None
        try:
            estado["rcd"] = rcd.arrancar()
        except ConfigError as e:
            decir(str(e), boton="Reintentar")
            return False
        return True

    def lanzar_peticion(pedida: tuple[str, str], esperar: bool | None = None) -> None:
        """Pide una carpeta (`("ruta", r)`) o la raíz de otro remote (`("remote", nombre)`).

        Args:
            pedida: Qué se pide; se guarda para repetirla tras «Reconectar»/«Reintentar».
            esperar: Si el hilo espera antes a que `rcd` conteste. Por defecto,
                mientras la ventana no haya enseñado nada todavía.
        """
        if estado["cerrado"]:
            return
        if estado["rcd"] is None:
            elegido.set(nav.remote)         # sin rcd no hay a quién pedir: no cambia nada
            return
        estado["ultima"] = pedida
        clase, valor = pedida
        p = nav.pedir(valor) if clase == "ruta" else nav.cambiar_remote(valor)
        esperar = (not estado["abierto"]) if esperar is None else esperar
        decir("", "Pista.")
        indicador.poner(CONECTANDO if esperar else f"Leyendo {p.ruta}…", True)
        encargo = segundo_plano.lanzar(partial(
            _leer, estado["rcd"], p, remotes[p.remote], sondeos.get(p.remote), esperar))
        sondeo.esperar(encargo, partial(llega, p))

    def llega(p: servidor.Peticion, encargo) -> None:
        """Recoge la respuesta de `p`: pinta la carpeta o dice por qué no."""
        if estado["cerrado"]:
            return
        if encargo.error is not None:
            fallo(p, encargo.error)
            return
        lectura = encargo.resultado
        if not nav.recibir(p, lectura.entradas):
            return
        sondeos[p.remote] = (lectura.permisos, lectura.mi_uid)
        pintar()

    def fallo(p: servidor.Peticion, error: Exception) -> None:
        """Dice por qué no llegó el listado `p`; la lista se queda como estaba."""
        frase = nav.fallo(p, error)
        if frase is None:
            return
        if isinstance(error, rcd.PuertoOcupado) and not estado["puerto_reintentado"]:
            # El puerto se ocupó entre elegirlo y abrirlo: otra vez, con otro, una sola vez.
            estado["puerto_reintentado"] = True
            if conectar(forzar=True):
                lanzar_peticion(estado["ultima"], esperar=True)
            return
        elegido.set(nav.remote)             # un cambio de remote que falla no cambia nada
        if isinstance(error, rcd.RcdCaido):
            decir(frase, boton="Reconectar")
        elif isinstance(error, ConfigError):
            decir(str(error), boton="Reintentar")
        elif not estado["abierto"] and servidor.es_sin_red(error):
            decir(frase, boton="Reintentar")
        else:
            decir(frase)
        retocar()                           # un fallo de permiso deja un candado

    def reconectar() -> None:
        """Relanza `rcd` y repite la última petición."""
        estado["puerto_reintentado"] = False
        if conectar(forzar=True):
            lanzar_peticion(estado["ultima"], esperar=True)

    def reintentar() -> None:
        """Repite la última petición; relanza `rcd` solo si ya no está vivo."""
        estado["puerto_reintentado"] = False
        if conectar():
            lanzar_peticion(estado["ultima"], esperar=True)

    # ------------------------------------------------------------- navegar
    def entrar(_evento=None) -> str:
        """Entra en la carpeta elegida; un archivo, nada."""
        elegida = lista.selection()
        e = estado["entradas"].get(str(elegida[0])) if elegida else None
        if e is not None and e.es_carpeta:
            lanzar_peticion(("ruta", nav.hijo(e.nombre)))
        return "break"

    def doble_clic(evento) -> str | None:
        """Entra en la fila sobre la que se hace doble clic; en la cabecera, nada."""
        if lista.identify_region(evento.x, evento.y) not in ("tree", "cell"):
            return None
        fila = lista.identify_row(evento.y)
        if not fila:
            return None
        lista.selection_set(fila)
        return entrar()

    def subir(_evento=None) -> str:
        """Sube a la carpeta que contiene a la actual; la raíz es el techo."""
        if nav.ruta != servidor.RAIZ:
            lanzar_peticion(("ruta", nav.padre()))
        return "break"

    def repetir() -> None:
        """Vuelve a leer la carpeta que se enseña."""
        lanzar_peticion(("ruta", nav.ruta))

    def cambiar_remote(_evento=None) -> None:
        """Pasa a la raíz del remote elegido en el desplegable."""
        nuevo = elegido.get()
        if nuevo and nuevo != nav.remote:
            lanzar_peticion(("remote", nuevo))

    lista.bind("<Double-Button-1>", doble_clic)
    lista.bind("<Return>", entrar)
    lista.bind("<KP_Enter>", entrar)
    lista.bind("<BackSpace>", subir)
    elegido.bind("<<ComboboxSelected>>", cambiar_remote)

    # ------------------------------------------------------------- cerrar
    def cerrar(evento=None) -> None:
        """Para el `rcd` en segundo plano, una vez, se cierre por donde se cierre."""
        if evento is not None and str(evento.widget) != str(dlg):
            return                          # se destruye un hijo, no la ventana
        if estado["cerrado"]:
            return
        estado["cerrado"] = True
        if estado["rcd"] is not None:
            segundo_plano.lanzar(partial(estado["rcd"].parar))

    def cerrar_ventana() -> None:
        cerrar()
        dlg.destroy()

    dlg.protocol("WM_DELETE_WINDOW", cerrar_ventana)
    dlg.bind("<Destroy>", cerrar, add="+")

    # ------------------------------------------------------------- abrir
    if not remotes:
        decir(SIN_REMOTES, "Pista.")
        for control in (elegido, arriba, releer):
            control.configure(state="disabled")
    else:
        elegido.set(nav.remote)
        indicador.poner(CONECTANDO, True)
        if conectar():
            lanzar_peticion(("ruta", servidor.RAIZ), esperar=True)
    mostrar(dlg, parent)
