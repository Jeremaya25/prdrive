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
esperarlo.

Bajar y subir (pieza 2): la lista admite varias filas y el pie lleva «Bajar…»,
«Subir archivos…» y «Subir carpeta…». Un lote es UN `sync/copy` asíncrono del
`rcd` (`common/rcd.py`); qué se copia, los avisos por pareja y los textos los
decide `ui/transferencia.py` y el panel que lo enseña es `ui/tk_transferencia.py`.
Aquí se encadena el flujo: elegir → avisar/bloquear → contar choques en segundo
plano → preguntar → copiar → seguir el progreso cada `INTERVALO_PROGRESO_MS` →
resultado. Lo que espera a la red va en segundo plano con funciones de módulo;
el `Sondeo` del lote es distinto del de los listados para que navegar no pise a
la transferencia. Lanzar la copia, seguirla, cancelarla y cerrar con ella en
marcha lo hace `ui/tk_lote.Seguimiento`; aquí solo se cuenta antes y se dice
qué es un lote de copia. Copiar nunca borra.

Gestionar (pieza 3): una barra entre la línea del indicador y la lista («Nueva
carpeta…», «Renombrar…», «Cortar», «Borrar…»), las mismas acciones en el menú del
botón derecho y con teclas. Cada acción es un `Trabajo` de órdenes de
`rcd.lanzar_orden()` (una por elemento); qué se puede, qué se avisa y los textos
los decide `ui/gestion.py`, y el diálogo del nombre y la barra son de
`ui/tk_gestion.py`. El flujo: elegir → bloquear → mirar en segundo plano (los
nombres del destino, o lo que hay dentro de lo que se borra) → confirmar cuando
toca → lanzar → releer la carpeta que se ve y elegir lo nuevo. Un nombre nunca se
lanza sobre otro que ya existe: los del destino se releen justo antes.
"""

from __future__ import annotations

import os
from functools import partial
from typing import NamedTuple

from common import config_file, model, rcd
from common.model import Config, ConfigError

from . import (gestion, icons, remote_picker, segundo_plano, servidor, theme, tk_gestion, tk_lote,
               tk_transferencia, transferencia)
from .tk import Indicador, Sondeo, avisar, centrar, cuerpo_visible, modal, mostrar, preguntar

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
INTERVALO_PROGRESO_MS = 500
"""Milisegundos entre dos peticiones de `core/stats` y `job/status` de un lote."""
MIRANDO = "Mirando el destino…"
MIRANDO_DENTRO = "Mirando qué hay dentro…"
PERDIDA = "Se perdió la conexión con rclone."
SIN_RESPUESTA = "Sin respuesta de rclone… la copia sigue en marcha; se vuelve a intentar."
FALLOS_PARA_AVISAR = 3
"""Cuántos seguimientos seguidos sin respuesta hacen falta para decirlo en la ventana."""
TITULO_CIERRE = tk_lote.TITULO_CIERRE
TEXTO_CIERRE = tk_lote.TEXTO_CIERRE
SIN_RESPUESTA_GESTION = (
    "Sin respuesta de rclone… el cambio sigue en marcha; se vuelve a intentar.")
TITULO_CIERRE_GESTION = "Cambio en marcha"
TEXTO_CIERRE_GESTION = "Hay un cambio en marcha en el servidor. ¿Cancelarlo y cerrar?"
SIN_RAIZ = "Elige una carpeta, no la raíz de una unidad."
MARCA_PAREJA = "  · pareja «{}»"
"""Lo que se añade al nombre de una carpeta que es la de una pareja; `{}` es el nombre de la pareja.

Solo con glifos que traen las fuentes del programa (ui/fuentes)."""


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
            de la carpeta de inicio, que solo se pide fuera de `local`) antes de listar.
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
            stat = None
            if servidor.uid_se_pregunta_al_servidor(tipo):
                try:
                    stat = r.llamar("operations/stat",
                                    {"fs": f"{p.remote}:", "remote": "", "opt": {"metadata": True}})
                except rcd.ErrorRc:
                    pass    # sin saber quién soy, solo se pierde el candado previo
            mi_uid = servidor.mi_uid(tipo, stat)
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
                nombre += MARCA_PAREJA.format(pareja)
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


def elegir_destino(parent, inicial: str) -> str | None:
    """Pide al sistema la carpeta del equipo donde guardar lo que se baja.

    Es de módulo para que los tests lo sustituyan.

    Args:
        parent: La ventana de la que cuelga.
        inicial: La carpeta en la que empieza el diálogo.

    Returns:
        La carpeta elegida, o `None` si se cancela.
    """
    from tkinter import filedialog

    ruta = filedialog.askdirectory(parent=parent, title="Elige dónde guardar",
                                   initialdir=inicial or None)
    return str(ruta) if ruta else None


def elegir_archivos(parent, inicial: str) -> list[str]:
    """Pide al sistema los archivos del equipo que se suben; vacío si se cancela."""
    from tkinter import filedialog

    rutas = filedialog.askopenfilenames(parent=parent, title="Elige los archivos que subir",
                                        initialdir=inicial or None)
    return [str(r) for r in rutas] if rutas else []


def elegir_carpeta(parent, inicial: str) -> str | None:
    """Pide al sistema la carpeta del equipo que se sube; `None` si se cancela."""
    from tkinter import filedialog

    ruta = filedialog.askdirectory(parent=parent, title="Elige la carpeta que subir",
                                   initialdir=inicial or None)
    return str(ruta) if ruta else None


def _no_esta(error: rcd.ErrorRc) -> bool:
    """Si rclone contesta que lo pedido no existe (no es un fallo: es «no está»)."""
    return error.estado == 404 or "not found" in error.mensaje.lower()


def _rutas_remotas(r: rcd.Rcd, remote: str, base: str, elementos) -> set[str]:
    """Devuelve las rutas de los ARCHIVOS que hay en el servidor para esos elementos; corre en un hilo.

    Una carpeta se lista entera (`operations/list` recursivo, solo de ella y no de
    `base`, que puede ser enorme); un archivo se mira con `operations/stat`. Lo que
    no existe no cuenta. Las rutas son relativas a `base`, con `/`.

    Args:
        r: El `rcd` al que se habla.
        remote: El remote de `rclone.conf`.
        base: La carpeta del servidor en la que están (o estarían) los elementos.
        elementos: Los `transferencia.Elemento` elegidos.

    Raises:
        rcd.ErrorRc: Si rclone contesta con un error que no es «no existe».
        rcd.RcdCaido: Si no se puede hablar con `rcd`.
    """
    raiz = remote_picker.normalizar(base).lstrip("/")
    fs = f"{remote}:/"
    rutas: set[str] = set()
    for e in elementos:
        ruta = f"{raiz}/{e.nombre}" if raiz else e.nombre
        try:
            if e.es_carpeta:
                respuesta = r.llamar("operations/list", {
                    "fs": fs, "remote": ruta, "opt": {"recurse": True, "noMimeType": True}})
                for item in respuesta.get("list") or []:
                    if isinstance(item, dict) and not item.get("IsDir"):
                        rutas.add(f"{e.nombre}/{item.get('Path') or item.get('Name')}")
            else:
                item = r.llamar("operations/stat", {"fs": fs, "remote": ruta}).get("item")
                if isinstance(item, dict) and not item.get("IsDir"):
                    rutas.add(e.nombre)
        except rcd.ErrorRc as error:
            if not _no_esta(error):
                raise
    return rutas


def _rutas_locales(carpeta: str, elementos) -> set[str]:
    """Devuelve las rutas de los ARCHIVOS que hay en el equipo para esos elementos.

    Lo mismo que `_rutas_remotas` con `os.walk` y `os.path.isfile`: relativas a
    `carpeta`, con `/`, solo de lo elegido y sin contar las carpetas.
    """
    rutas: set[str] = set()
    for e in elementos:
        base = os.path.join(carpeta, e.nombre)
        if e.es_carpeta:
            for dirpath, _carpetas, ficheros in os.walk(base):
                rel = os.path.relpath(dirpath, base)
                tramos = [] if rel == os.curdir else rel.split(os.sep)
                rutas.update("/".join([e.nombre, *tramos, f]) for f in ficheros)
        elif os.path.isfile(base):
            rutas.add(e.nombre)
    return rutas


def _contar_choques(r: rcd.Rcd, lote: transferencia.Lote) -> int:
    """Cuenta los archivos del lote que ya están en el destino; corre en un hilo."""
    if lote.sentido == transferencia.SUBIR:
        origen = _rutas_locales(lote.carpeta_local, lote.elementos)
        destino = _rutas_remotas(r, lote.remote, lote.ruta_remota, lote.elementos)
    else:
        origen = _rutas_remotas(r, lote.remote, lote.ruta_remota, lote.elementos)
        destino = _rutas_locales(lote.carpeta_local, lote.elementos)
    return transferencia.choques(origen, destino)


def _lanzar_copia(lote: transferencia.Lote, omitir: bool, r: rcd.Rcd, grupo: str) -> int:
    """Lanza el `sync/copy` del lote y devuelve su `jobid`; corre en un hilo."""
    origen, destino = transferencia.fs_de(lote)
    return rcd.copiar(r, origen, destino, transferencia.reglas_de(lote.elementos), omitir, grupo)


def _destino_visible(lote: transferencia.Lote) -> str:
    """Devuelve el destino tal como lo ve la persona: la carpeta del servidor al subir, la del equipo al bajar."""
    return lote.ruta_remota if lote.sentido == transferencia.SUBIR else lote.carpeta_local


def _lanzar_orden(orden: dict, r: rcd.Rcd, grupo: str) -> int:
    """Lanza una orden de gestión del `rcd` y devuelve su `jobid`; corre en un hilo.

    Es el único camino por el que sale un borrado, un movimiento o una carpeta
    nueva: `rcd.lanzar_orden()` solo admite `rcd.ORDENES_PERMITIDAS`.
    """
    return rcd.lanzar_orden(r, orden, grupo)


def _nombres_de(r: rcd.Rcd, remote: str, carpeta: str) -> tuple[str, ...]:
    """Devuelve los nombres que hay AHORA en una carpeta del servidor; corre en un hilo.

    Un `operations/list` no recursivo y sin metadatos: la lista de la pantalla puede
    ser vieja y nada se lanza sobre un nombre que ya existe.

    Raises:
        rcd.ErrorRc: Si rclone contesta con un error.
        rcd.RcdCaido: Si no se puede hablar con `rcd`.
    """
    respuesta = r.llamar("operations/list", servidor.params_listado(remote, carpeta, False))
    return tuple(e.nombre for e in servidor.entradas_de(respuesta))


def _contar_borrado(r: rcd.Rcd, op: gestion.Operacion,
                    tamanos: dict[str, int]) -> dict[str, tuple[int, int]]:
    """Cuenta lo que se llevaría el borrado, por elemento: `(archivos, bytes)`; corre en un hilo.

    Una carpeta se cuenta con un `operations/size`; un archivo vale `(1, su tamaño)` y no
    pregunta nada.

    Args:
        r: El `rcd` al que se habla.
        op: El borrado.
        tamanos: El tamaño de cada archivo elegido, por nombre, tal como lo dio el listado.

    Raises:
        rcd.ErrorRc: Si rclone contesta con un error.
        rcd.RcdCaido: Si no se puede hablar con `rcd`.
    """
    conteos: dict[str, tuple[int, int]] = {}
    for e, orden in zip(op.elementos, gestion.ordenes_de(op)):
        if e.es_carpeta:
            conteos[e.nombre] = rcd.tamano(r, orden["fs"], orden["remote"])
        else:
            conteos[e.nombre] = (1, tamanos.get(e.nombre, 0))
    return conteos


def _resultado_de_mirar(estados: list[dict], _stats: dict, _cancelado: bool):
    """Dice por qué no se pudo mirar el servidor antes de actuar, y ofrece «Reintentar».

    Es el `resultado` de un `Trabajo` que falló antes de lanzar ninguna orden: el último
    estado trae el error de rclone.
    """
    error = rcd.ErrorRc(str((estados[-1].get("error") if estados else "")
                            or "no se ha podido mirar el servidor"), 0)
    return transferencia.Resultado(servidor.frase_error(error), "aviso", True)


def _mostrar_menu(menu, x: int, y: int) -> None:
    """Enseña el menú del botón derecho en esa posición de la pantalla.

    Es de módulo para que los tests lo sustituyan: `tk_popup` toma el ratón.
    """
    try:
        menu.tk_popup(x, y)
    finally:
        menu.grab_release()


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
    sondeo_lote = Sondeo(dlg)       # el del lote: navegar no pisa a la transferencia
    try:
        raw = config_file.load_raw()
    except ConfigError:
        raw = {}
    remotes = servidor.remotes_de(_leer_conf(), remote_picker.remote_de(raw),
                                  config.device_remote)
    catalogo = model.carpeta_del_catalogo(raw.get("defaults") or {})
    nav = servidor.Navegacion(next(iter(remotes), ""))
    estado: dict = {"rcd": None, "ultima": ("ruta", servidor.RAIZ), "abierto": False,
                    "cerrado": False, "puerto_reintentado": False, "entradas": {},
                    "n_lote": 0, "tras": None,
                    "carpeta": os.path.expanduser("~")}
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

    # La barra de gestión, entre la línea del indicador y la lista. Qué hace cada botón
    # se resuelve al pulsar (las acciones se definen más abajo).
    barra_gestion = tk_gestion.Barra(marco, {
        "nueva": lambda: nueva_carpeta(), "renombrar": lambda: renombrar_elegido(),
        "cortar": lambda: cortar_elegidos(), "borrar": lambda: borrar_elegidos()})
    barra_gestion.marco.grid(row=2, column=0, sticky="w", pady=(theme.E3, 0))
    dlg.barra = barra_gestion

    # La carpeta y el archivo llevan su icono en la columna del árbol (#0), la única
    # de una `Treeview` que lo admite; el árbol no se despliega: se entra.
    tarjeta = ttk.Frame(marco, style="Card.TFrame",
                        padding=(theme.E2, theme.E2, theme.E1, theme.E1))
    tarjeta.grid(row=3, column=0, sticky="ew", pady=(theme.E4, 0))
    tarjeta.columnconfigure(0, weight=1)
    lista = ttk.Treeview(tarjeta, columns=("tamano", "modificado", "permisos"),
                         show=("tree", "headings"), height=FILAS_VISIBLES, selectmode="extended")
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
    vacia = ttk.Label(tarjeta, text=VACIA, style="Card.Pista.TLabel")
    iconos = {nombre: icons.get(lista, nombre, 16, theme.TINTA3, theme.SUPERFICIE)
              for nombre in ("carpeta", "file", "candado")}
    dlg.lista, dlg.vacia, dlg.accion, dlg.elegido = lista, vacia, accion, elegido
    dlg.ruta, dlg.arriba = ruta, arriba

    # El panel de un lote, entre la lista y el pie: sin lote no ocupa sitio.
    panel = tk_transferencia.Panel(marco)
    panel.marco.grid(row=4, column=0, sticky="ew")
    panel.ocultar()
    panel.al_cancelar = lambda: seg.cancelar()
    panel.al_reintentar = lambda: reintentar_lote()

    pie = ttk.Frame(marco)
    pie.grid(row=5, column=0, sticky="ew", pady=(theme.E3, 0))
    pie.columnconfigure(0, weight=1)
    cuenta = ttk.Label(pie, text="", style="MonoPista.TLabel")
    cuenta.grid(row=0, column=0, sticky="w")
    boton_bajar = ttk.Button(pie, text="Bajar…", state="disabled",
                             command=lambda: bajar_elegidos())
    boton_bajar.grid(row=0, column=1, padx=(theme.E3, 0))
    boton_archivos = ttk.Button(pie, text="Subir archivos…", state="disabled",
                                command=lambda: subir_archivos())
    boton_archivos.grid(row=0, column=2, padx=(theme.E2, 0))
    boton_carpeta = ttk.Button(pie, text="Subir carpeta…", state="disabled",
                               command=lambda: subir_carpeta())
    boton_carpeta.grid(row=0, column=3, padx=(theme.E2, 0))
    ttk.Button(pie, text="Cerrar", command=lambda: cerrar_ventana()).grid(
        row=0, column=4, padx=(theme.E4, 0))
    dlg.cuenta, dlg.panel, dlg.sondeo_lote = cuenta, panel, sondeo_lote
    dlg.bajar, dlg.subir_archivos, dlg.subir_carpeta = boton_bajar, boton_archivos, boton_carpeta

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
        actualizar_botones()

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
        tras, estado["tras"] = estado["tras"], None
        if tras is not None and tras[:2] == (nav.remote, nav.ruta):
            if tras[2]:
                decir(tras[2], "Pista.")
            elegir_nombres(tras[3])
        reajustar()

    def reajustar() -> None:
        """Agranda la ventana si lo que se ve ahora pide más (nunca mengua) y la recoloca.

        La ventana nace con la lista vacía: al llegar el listado, o al salir el
        panel de un lote, puede crecer.
        """
        if dlg.winfo_ismapped() and dlg.visor.crecer(dlg):
            centrar(dlg, parent)

    def libre() -> bool:
        """Si hay conexión con `rclone` y ningún lote ni cambio en marcha."""
        return estado["rcd"] is not None and seg.activo is None

    def estados_gestion() -> dict[str, bool]:
        """Qué acciones de gestión se pueden ahora.

        «Nueva carpeta…» con la ventana libre, «Renombrar…» con exactamente una fila
        elegida, «Cortar» y «Borrar…» con una o más.
        """
        filas = len(lista.selection())
        ok = libre()
        return {"nueva": ok, "renombrar": ok and filas == 1, "cortar": ok and filas >= 1,
                "borrar": ok and filas >= 1}

    def actualizar_botones() -> None:
        """Enciende o apaga los botones de gestión, «Bajar…» y las dos «Subir…» según la selección, el `rcd` y el lote."""
        ok = libre()
        hay = bool(lista.selection())
        boton_bajar.configure(state="normal" if ok and hay else "disabled")
        for b in (boton_archivos, boton_carpeta):
            b.configure(state="normal" if ok else "disabled")
        barra_gestion.encender(**estados_gestion())

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
            actualizar_botones()
            return False
        actualizar_botones()
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
        if estado["tras"] is not None and estado["tras"][:2] != (p.remote, p.ruta):
            estado["tras"] = None           # se navega a otra carpeta: lo de la anterior ya no vale
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
        estado["tras"] = None
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
        """Entra en la carpeta elegida; un archivo, o varias filas, nada."""
        elegida = lista.selection()
        e = estado["entradas"].get(str(elegida[0])) if len(elegida) == 1 else None
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

    lista.bind("<<TreeviewSelect>>", lambda _e: actualizar_botones())
    lista.bind("<Double-Button-1>", doble_clic)
    lista.bind("<Return>", entrar)
    lista.bind("<KP_Enter>", entrar)
    lista.bind("<BackSpace>", subir)
    elegido.bind("<<ComboboxSelected>>", cambiar_remote)


    # ------------------------------------------------------------- bajar y subir
    def cambio_de_lote() -> None:
        """Con el lote que cambia (o su panel): botones según el lote y ventana al tamaño del panel."""
        actualizar_botones()
        reajustar()

    seg = tk_lote.Seguimiento(
        dlg, panel, sondeo_lote, decir=decir, intervalo_ms=lambda: INTERVALO_PROGRESO_MS,
        fallos_para_avisar=lambda: FALLOS_PARA_AVISAR, perdida=PERDIDA, al_cambiar=cambio_de_lote)

    def resultado_de(destino: str, omitidos: int):
        """Devuelve cómo se convierte el estado final de la copia en su resultado."""
        return lambda estados, stats, cancelado: transferencia.resultado_de(
            estados[-1] if estados else {}, stats, cancelado, destino, omitidos)

    def releer_si_subida(lote: transferencia.Lote, _resultado) -> None:
        """Tras subir a la carpeta que se ve, la relee (también tras un fallo o una cancelación: algo subió)."""
        if (lote.sentido == transferencia.SUBIR and lote.remote == nav.remote
                and lote.ruta_remota == nav.ruta):
            repetir()

    def nuevo_trabajo(lote: transferencia.Lote) -> tk_lote.Trabajo:
        """Abre el trabajo de un lote: lo que lo sigue hasta que acaba. Apaga los tres botones.

        Aún sin orden que lanzar: `copiar()` pone la copia cuando se sabe qué hacer con los choques.
        """
        estado["n_lote"] += 1
        destino = _destino_visible(lote)
        return seg.abrir(tk_lote.Trabajo(
            rcd=estado["rcd"], grupo=f"lote-{estado['n_lote']}", lanzadores=[],
            progreso=lambda stats, _hechos, _total: transferencia.progreso_de(
                stats, lote, destino),
            resultado=resultado_de(destino, 0), al_acabar=partial(releer_si_subida, lote),
            sin_respuesta=SIN_RESPUESTA, titulo_cierre=TITULO_CIERRE, texto_cierre=TEXTO_CIERRE))

    def elementos_elegidos() -> tuple[transferencia.Elemento, ...]:
        """Devuelve las filas elegidas como elementos de un lote."""
        elegidas = (estado["entradas"].get(str(iid)) for iid in lista.selection())
        return tuple(transferencia.Elemento(e.nombre, e.es_carpeta) for e in elegidas if e)

    def bajar_elegidos() -> None:
        """«Bajar…»: pide la carpeta del equipo y baja lo elegido, con su estructura."""
        elementos = elementos_elegidos()
        if seg.activo is not None or estado["rcd"] is None or not elementos:
            return
        # Lo que se ve ahora se apunta antes del diálogo: su bucle de eventos deja
        # llegar un listado que cambiaría `nav` y los nombres elegidos ya no serían de esa carpeta.
        remote, ruta_remota = nav.remote, nav.ruta
        destino = elegir_destino(dlg, estado["carpeta"])
        if not destino:
            return
        estado["carpeta"] = destino
        empezar(transferencia.Lote(transferencia.BAJAR, remote, ruta_remota, destino, elementos))

    def subir_a(remote: str, ruta_remota: str, carpeta: str,
                elementos: tuple[transferencia.Elemento, ...]) -> None:
        """Sube esos elementos de `carpeta` (del equipo) a esa carpeta del servidor."""
        estado["carpeta"] = carpeta
        empezar(transferencia.Lote(transferencia.SUBIR, remote, ruta_remota, carpeta, elementos))

    def subir_archivos() -> None:
        """«Subir archivos…»: pide archivos del equipo y los sube a la carpeta que se ve."""
        if seg.activo is not None or estado["rcd"] is None:
            return
        remote, ruta_remota = nav.remote, nav.ruta      # antes del diálogo, como en «Bajar…»
        rutas = elegir_archivos(dlg, estado["carpeta"])
        if rutas:
            nombres = dict.fromkeys(os.path.basename(r) for r in rutas)
            subir_a(remote, ruta_remota, os.path.dirname(rutas[0]),
                    tuple(transferencia.Elemento(n, False) for n in nombres))

    def subir_carpeta() -> None:
        """«Subir carpeta…»: pide una carpeta del equipo y la sube, entera, a la que se ve."""
        if seg.activo is not None or estado["rcd"] is None:
            return
        remote, ruta_remota = nav.remote, nav.ruta      # antes del diálogo, como en «Bajar…»
        ruta = elegir_carpeta(dlg, estado["carpeta"])
        if not ruta:
            return
        padre, nombre = os.path.split(ruta.rstrip("/\\") or ruta)
        if not nombre:
            avisar(dlg, "No se puede", SIN_RAIZ, "Ambar.")
            return
        subir_a(remote, ruta_remota, padre, (transferencia.Elemento(nombre, True),))

    def empezar(lote: transferencia.Lote) -> None:
        """Avisa o bloquea según las parejas alcanzadas y, si sigue, empieza a contar choques."""
        if lote.sentido == transferencia.SUBIR:
            afectadas = transferencia.afectadas_subida(
                config, lote.remote, lote.ruta_remota, lote.elementos)
        else:
            afectadas = transferencia.afectadas_bajada(
                config, lote.carpeta_local, lote.elementos)
        texto = transferencia.bloqueo(lote.sentido, afectadas)
        if texto:
            avisar(dlg, "No se puede", texto, "Ambar.")
            return
        texto = transferencia.aviso(lote.sentido, afectadas)
        if texto and not preguntar(dlg, "Carpeta de una pareja", texto, "Seguir", "Cancelar"):
            return
        if estado["cerrado"] or seg.activo is not None or estado["rcd"] is None:
            return
        contar(nuevo_trabajo(lote), lote)

    def contar(t: tk_lote.Trabajo, lote: transferencia.Lote) -> None:
        """Cuenta en segundo plano los archivos del lote que ya están en el destino."""
        indicador.poner(MIRANDO, True)
        accion.grid_remove()
        sondeo_lote.esperar(
            segundo_plano.lanzar(partial(_contar_choques, t.rcd, lote)),
            partial(choques_contados, t, lote))

    def choques_contados(t: tk_lote.Trabajo, lote: transferencia.Lote, encargo) -> None:
        """Con la cuenta hecha, pregunta qué hacer con los choques (si los hay) y copia."""
        if not seg.vigente(t):
            return
        decir("", "Pista.")
        if encargo.error is not None:
            seg.acabar_con_error(t, encargo.error, partial(reintentar_conteo, lote))
            return
        omitir = False
        if encargo.resultado > 0:
            respuesta = tk_transferencia.preguntar_choques(
                dlg, transferencia.texto_choques(encargo.resultado, _destino_visible(lote)))
            if not seg.vigente(t):
                return
            if respuesta is None:
                seg.soltar()
                return
            omitir = respuesta == "omitir"
        copiar(t, lote, omitir, encargo.resultado if omitir else 0)

    def copiar(t: tk_lote.Trabajo, lote: transferencia.Lote, omitir: bool,
               omitidos: int = 0) -> None:
        """Lanza el `sync/copy` del lote en segundo plano y lo sigue.

        Args:
            t: El trabajo abierto del lote.
            lote: Lo que se copia.
            omitir: Si los archivos que ya existen se dejan como están.
            omitidos: Cuántos son (los choques contados); es lo que dirá el resultado.
        """
        t.lanzadores = [partial(_lanzar_copia, lote, omitir)]
        t.resultado = resultado_de(_destino_visible(lote), omitidos)
        t.reintento = partial(reintentar_copia, lote, omitir, omitidos)
        seg.lanzar(t)

    def reintentar_copia(lote: transferencia.Lote, omitir: bool, omitidos: int) -> None:
        """Repite el lote con la misma decisión de choques: lo ya copiado e idéntico se salta."""
        copiar(nuevo_trabajo(lote), lote, omitir, omitidos)

    def reintentar_conteo(lote: transferencia.Lote) -> None:
        """Repite el lote desde el principio (no llegó a copiar nada)."""
        contar(nuevo_trabajo(lote), lote)

    def reintentar_lote() -> None:
        """«Reintentar» del panel: repite el último lote que falló."""
        if estado["rcd"] is not None:
            seg.reintentar()

    # ------------------------------------------------------------- gestionar
    def nuevo_trabajo_gestion(op: gestion.Operacion) -> tk_lote.Trabajo:
        """Abre el trabajo de una operación: apaga los botones mientras se prepara y se sigue.

        Las órdenes ya están listas; qué dirá el resultado se pone al lanzar
        (`lanzar_gestion`), porque antes de eso lo único que puede fallar es mirar.
        """
        estado["n_lote"] += 1
        t = seg.abrir(tk_lote.Trabajo(
            rcd=estado["rcd"], grupo=f"gestion-{estado['n_lote']}",
            lanzadores=[partial(_lanzar_orden, o) for o in gestion.ordenes_de(op)],
            progreso=partial(gestion.progreso_de, op), resultado=_resultado_de_mirar,
            sin_respuesta=SIN_RESPUESTA_GESTION, cancelando=partial(gestion.cancelando_de, op),
            panel_tardio=True, titulo_cierre=TITULO_CIERRE_GESTION,
            texto_cierre=TEXTO_CIERRE_GESTION))
        t.al_acabar = partial(releer_tras_gestion, op, t)
        return t

    def elegir_nombres(nombres: tuple[str, ...]) -> None:
        """Elige en la lista los nombres que estén a la vista (y deja ver el primero)."""
        presentes = [n for n in nombres if lista.exists(n)]
        if presentes:
            lista.selection_set(*presentes)
            lista.focus(presentes[0])
            lista.see(presentes[0])
            actualizar_botones()

    def releer_tras_gestion(op: gestion.Operacion, t: tk_lote.Trabajo,
                            resultado: transferencia.Resultado) -> None:
        """Al acabar un cambio (bien, mal o cancelado) relee la carpeta que se ve.

        Cuando llega el listado queda elegido lo nuevo (la carpeta creada, el nombre
        nuevo) si sigue a la vista, y un resultado que fue a la línea de la ventana
        (el panel no llegó a salir) se vuelve a poner: leer la carpeta lo habría borrado.
        """
        nuevos = (op.nombre,) if op.tipo in (gestion.NUEVA, gestion.RENOMBRAR) and op.nombre else ()
        nota = resultado.texto if resultado.tono == "ok" and not t.panel_visto else ""
        estado["tras"] = (op.remote, op.carpeta, nota, nuevos)
        repetir()

    def lanzar_gestion(t: tk_lote.Trabajo, op: gestion.Operacion) -> None:
        """Lanza las órdenes de la operación una tras otra y las sigue."""
        t.resultado = partial(gestion.resultado_de, op)
        seg.lanzar(t)

    def confirmar_y_lanzar(t: tk_lote.Trabajo, op: gestion.Operacion, plan: gestion.Plan,
                           titulo: str, nota: str) -> None:
        """Enseña lo que va a pasar y, con un «sí», lanza; con un «no» no lanza nada y libera la ventana."""
        from . import tk_pairs

        sigue = tk_pairs.confirmar_plan(dlg, plan, titulo, nota)
        if not seg.vigente(t):
            return
        if sigue:
            lanzar_gestion(t, op)
        else:
            seg.soltar()

    def libre_tras_dialogo() -> bool:
        """Si, vuelta del diálogo, la ventana sigue abierta, conectada y sin otro cambio en marcha."""
        return not estado["cerrado"] and libre()

    # -- nueva carpeta y renombrar: comprobar el destino y lanzar
    def nueva_carpeta() -> None:
        """«Nueva carpeta…»: pide el nombre y crea la carpeta en la que se ve."""
        if not libre():
            return
        remote, carpeta = nav.remote, nav.ruta          # antes del diálogo, como en «Bajar…»
        existentes = tuple(estado["entradas"])
        nombre = tk_gestion.pedir_nombre(
            dlg, "Nueva carpeta", "", partial(gestion.validar_nombre, existentes=existentes))
        if nombre is None or not libre_tras_dialogo():
            return
        empezar_nombre(gestion.Operacion(gestion.NUEVA, remote, carpeta, nombre=nombre), None)

    def renombrar_elegido() -> None:
        """«Renombrar…»: pide el nombre nuevo de la fila elegida; el mismo nombre no hace nada."""
        elementos = elementos_elegidos()
        if not libre() or len(elementos) != 1:
            return
        remote, carpeta = nav.remote, nav.ruta
        existentes = tuple(estado["entradas"])
        e = elementos[0]
        nombre = tk_gestion.pedir_nombre(
            dlg, "Renombrar", e.nombre,
            partial(gestion.validar_nombre, existentes=existentes, actual=e.nombre),
            es_archivo=not e.es_carpeta)
        if nombre is None or nombre == e.nombre or not libre_tras_dialogo():
            return
        empezar_nombre(gestion.Operacion(gestion.RENOMBRAR, remote, carpeta, elementos,
                                         nombre=nombre), e.nombre)

    def empezar_nombre(op: gestion.Operacion, actual: str | None) -> None:
        """Bloquea si toca una pareja o el catálogo y, si no, mira el destino antes de lanzar."""
        texto = gestion.bloqueo(op, config, catalogo)
        if texto:
            avisar(dlg, "No se puede", texto, "Ambar.")
            return
        mirar_destino(nuevo_trabajo_gestion(op), op, actual)

    def mirar_destino(t: tk_lote.Trabajo, op: gestion.Operacion, actual: str | None) -> None:
        """Relee en segundo plano los nombres de la carpeta del destino."""
        indicador.poner(MIRANDO, True)
        accion.grid_remove()
        sondeo_lote.esperar(
            segundo_plano.lanzar(partial(_nombres_de, t.rcd, op.remote, op.carpeta)),
            partial(destino_mirado, t, op, actual))

    def destino_mirado(t: tk_lote.Trabajo, op: gestion.Operacion, actual: str | None,
                       encargo) -> None:
        """Con los nombres de ahora: rechaza el que ya existe; si no, confirma (con avisos) y lanza."""
        if not seg.vigente(t):
            return
        decir("", "Pista.")
        if encargo.error is not None:
            seg.acabar_con_error(t, encargo.error, partial(reintentar_nombre, op, actual))
            return
        motivo = gestion.validar_nombre(op.nombre or "", encargo.resultado, actual)
        if motivo:
            seg.soltar()
            avisar(dlg, "No se puede", motivo, "Ambar.")
            return
        avisos = gestion.avisos(op, config)
        if avisos:
            confirmar_y_lanzar(t, op, gestion.plan_de(op, {}, avisos), "Carpeta de una pareja", "")
        else:
            lanzar_gestion(t, op)

    def reintentar_nombre(op: gestion.Operacion, actual: str | None) -> None:
        """«Reintentar» tras no poder mirar el destino: vuelve a mirar."""
        if libre():
            mirar_destino(nuevo_trabajo_gestion(op), op, actual)

    # -- borrar: contar lo de dentro, confirmar y lanzar
    def borrar_elegidos() -> None:
        """«Borrar…»: cuenta lo que hay dentro de lo elegido, lo enseña y, con un «sí», lo borra."""
        elementos = elementos_elegidos()
        if not libre() or not elementos:
            return
        op = gestion.Operacion(gestion.BORRAR, nav.remote, nav.ruta, elementos)
        tamanos = {e.nombre: estado["entradas"][e.nombre].tamano or 0
                   for e in elementos if not e.es_carpeta}
        texto = gestion.bloqueo(op, config, catalogo)
        if texto:
            avisar(dlg, "No se puede", texto, "Ambar.")
            return
        contar_borrado(nuevo_trabajo_gestion(op), op, tamanos)

    def contar_borrado(t: tk_lote.Trabajo, op: gestion.Operacion, tamanos: dict[str, int]) -> None:
        """Cuenta en segundo plano lo que hay dentro de cada carpeta elegida."""
        indicador.poner(MIRANDO_DENTRO, True)
        accion.grid_remove()
        sondeo_lote.esperar(
            segundo_plano.lanzar(partial(_contar_borrado, t.rcd, op, tamanos)),
            partial(borrado_contado, t, op, tamanos))

    def borrado_contado(t: tk_lote.Trabajo, op: gestion.Operacion, tamanos: dict[str, int],
                        encargo) -> None:
        """Con la cuenta hecha, pide confirmación (el servidor no tiene papelera) y borra."""
        if not seg.vigente(t):
            return
        decir("", "Pista.")
        if encargo.error is not None:
            seg.acabar_con_error(t, encargo.error, partial(reintentar_borrado, op, tamanos))
            return
        plan = gestion.plan_de(op, encargo.resultado, gestion.avisos(op, config))
        confirmar_y_lanzar(t, op, plan, "Borrar del servidor", "El servidor no tiene papelera.")

    def reintentar_borrado(op: gestion.Operacion, tamanos: dict[str, int]) -> None:
        """«Reintentar» tras no poder contar: vuelve a contar desde el principio."""
        if libre():
            contar_borrado(nuevo_trabajo_gestion(op), op, tamanos)

    # -- cortar y pegar: aún sin hacer
    def cortar_elegidos() -> None:
        """«Cortar»: lo que se corta se pega con «Pegar aquí». Todavía no hace nada."""

    def pegar_aqui() -> None:
        """«Pegar aquí»: mueve lo cortado a la carpeta que se ve. Todavía no hace nada."""

    # -- teclas y botón derecho
    acciones_gestion = {"nueva": lambda: nueva_carpeta(), "renombrar": lambda: renombrar_elegido(),
                        "cortar": lambda: cortar_elegidos(), "pegar": lambda: pegar_aqui(),
                        "borrar": lambda: borrar_elegidos()}

    def con_tecla(clave: str):
        """Devuelve el manejador de una tecla: hace la acción solo si ahora se puede."""
        def al_pulsar(_evento=None) -> str:
            if {**estados_gestion(), "pegar": False}[clave]:
                acciones_gestion[clave]()
            return "break"
        return al_pulsar

    def menu_derecho(evento) -> str:
        """Botón derecho: elige la fila de debajo si no lo estaba y enseña el menú de gestión."""
        fila = lista.identify_row(evento.y)
        lista.focus_set()
        if fila and fila not in lista.selection():
            lista.selection_set(fila)
            lista.focus(fila)
        menu = tk_gestion.menu_contextual(lista, acciones_gestion,
                                          {**estados_gestion(), "pegar": False})
        _mostrar_menu(menu, evento.x_root, evento.y_root)
        return "break"

    for secuencia, clave in (("<F2>", "renombrar"), ("<Delete>", "borrar"),
                             ("<Control-x>", "cortar"), ("<Control-v>", "pegar"),
                             ("<Control-N>", "nueva")):
        lista.bind(secuencia, con_tecla(clave))
    lista.bind("<Button-3>", menu_derecho)

    # ------------------------------------------------------------- cerrar
    def cerrar(evento=None) -> None:
        """Para el `rcd` en segundo plano, una vez, se cierre por donde se cierre."""
        if evento is not None and str(evento.widget) != str(dlg):
            return                          # se destruye un hijo, no la ventana
        if estado["cerrado"]:
            return
        estado["cerrado"] = True
        seg.parar()
        if estado["rcd"] is not None:
            segundo_plano.lanzar(partial(estado["rcd"].parar))

    def cerrar_ventana() -> None:
        """Cierra; con un lote en marcha pregunta y, si se acepta, lo cancela antes.

        Se espera a que rclone acabe el trabajo (hasta `rcd.ESPERA_QUIT`, en
        segundo plano) y solo entonces se cierra como siempre, parando el `rcd`.
        """
        t = seg.activo
        if t is not None and t.jobid is not None:
            if t.cerrando:
                return                      # ya se está cancelando para cerrar
            if not preguntar(dlg, t.titulo_cierre, t.texto_cierre, "Cancelar y cerrar", "Seguir"):
                return
            if estado["cerrado"]:
                return
            # El trabajo pudo acabar mientras se preguntaba: entonces no hay nada que esperar.
            if seg.activo is t and seg.cerrar_cancelando(cierre_final):
                return
        cierre_final()

    def cierre_final() -> None:
        """Cierra la ventana: para el `rcd` y la destruye."""
        if estado["cerrado"]:
            return
        cerrar()
        dlg.destroy()

    dlg.protocol("WM_DELETE_WINDOW", cerrar_ventana)
    dlg.bind("<Destroy>", cerrar, add="+")

    # ------------------------------------------------------------- abrir
    if not remotes:
        decir(SIN_REMOTES, "Pista.")
        for control in (elegido, arriba, releer):
            control.configure(state="disabled")
        actualizar_botones()
    else:
        elegido.set(nav.remote)
        indicador.poner(CONECTANDO, True)
        if conectar():
            lanzar_peticion(("ruta", servidor.RAIZ), esperar=True)
    mostrar(dlg, parent)
