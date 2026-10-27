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
resultado. Lo que espera a la red (contar, lanzar, sondear, cancelar) va en
segundo plano con funciones de módulo; el `Sondeo` del lote es distinto del de
los listados para que navegar no pise a la transferencia. Copiar nunca borra.
"""

from __future__ import annotations

import os
import time
from functools import partial
from typing import NamedTuple

from common import config_file, model, rcd
from common.model import Config, ConfigError

from . import (icons, remote_picker, segundo_plano, servidor, theme, tk_transferencia,
               transferencia)
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
PERDIDA = "Se perdió la conexión con rclone."
SIN_RESPUESTA = "Sin respuesta de rclone… la copia sigue en marcha; se vuelve a intentar."
FALLOS_PARA_AVISAR = 3
"""Cuántos seguimientos seguidos sin respuesta hacen falta para decirlo en la ventana."""
TITULO_CIERRE = "Transferencia en marcha"
TEXTO_CIERRE = "Hay una transferencia en marcha. ¿Cancelarla y cerrar?"
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


def _lanzar_copia(r: rcd.Rcd, lote: transferencia.Lote, omitir: bool, grupo: str) -> int:
    """Lanza el `sync/copy` del lote y devuelve su `jobid`; corre en un hilo."""
    origen, destino = transferencia.fs_de(lote)
    return rcd.copiar(r, origen, destino, transferencia.reglas_de(lote.elementos), omitir, grupo)


def _sondear(r: rcd.Rcd, jobid: int, grupo: str) -> tuple[dict, dict]:
    """Pide `(core/stats, job/status)` de un lote; corre en un hilo.

    El estado va primero: si dice `finished`, las estadísticas que se piden
    después ya son las finales.
    """
    st = rcd.estado(r, jobid)
    return rcd.progreso(r, grupo), st


def _cancelar_y_esperar(r: rcd.Rcd, jobid: int) -> None:
    """Cancela el trabajo y espera a que acabe, hasta `rcd.ESPERA_QUIT`; corre en un hilo."""
    rcd.cancelar(r, jobid)
    limite = time.monotonic() + rcd.ESPERA_QUIT
    while time.monotonic() < limite:
        try:
            if rcd.estado(r, jobid).get("finished"):
                return
        except (rcd.ErrorRc, rcd.RcdCaido):
            return
        time.sleep(0.1)


def _destino_visible(lote: transferencia.Lote) -> str:
    """Devuelve el destino tal como lo ve la persona: la carpeta del servidor al subir, la del equipo al bajar."""
    return lote.ruta_remota if lote.sentido == transferencia.SUBIR else lote.carpeta_local


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
    nav = servidor.Navegacion(next(iter(remotes), ""))
    estado: dict = {"rcd": None, "ultima": ("ruta", servidor.RAIZ), "abierto": False,
                    "cerrado": False, "puerto_reintentado": False, "entradas": {},
                    "lote": None, "n_lote": 0, "reintento": None, "tras": None,
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

    # La carpeta y el archivo llevan su icono en la columna del árbol (#0), la única
    # de una `Treeview` que lo admite; el árbol no se despliega: se entra.
    tarjeta = ttk.Frame(marco, style="Card.TFrame",
                        padding=(theme.E2, theme.E2, theme.E1, theme.E1))
    tarjeta.grid(row=2, column=0, sticky="ew", pady=(theme.E4, 0))
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
    panel.marco.grid(row=3, column=0, sticky="ew")
    panel.ocultar()
    panel.al_cancelar = lambda: cancelar_lote()
    panel.al_reintentar = lambda: reintentar_lote()

    pie = ttk.Frame(marco)
    pie.grid(row=4, column=0, sticky="ew", pady=(theme.E3, 0))
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
        reajustar()

    def reajustar() -> None:
        """Agranda la ventana si lo que se ve ahora pide más (nunca mengua) y la recoloca.

        La ventana nace con la lista vacía: al llegar el listado, o al salir el
        panel de un lote, puede crecer.
        """
        if dlg.winfo_ismapped() and dlg.visor.crecer(dlg):
            centrar(dlg, parent)

    def actualizar_botones() -> None:
        """Enciende o apaga «Bajar…» y las dos «Subir…» según la selección, el `rcd` y el lote."""
        libre = estado["rcd"] is not None and estado["lote"] is None
        hay = bool(lista.selection())
        boton_bajar.configure(state="normal" if libre and hay else "disabled")
        for b in (boton_archivos, boton_carpeta):
            b.configure(state="normal" if libre else "disabled")

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
    def nuevo_activo(lote: transferencia.Lote) -> dict:
        """Abre el lote en marcha: lo que lo sigue hasta que acaba. Apaga los tres botones."""
        estado["n_lote"] += 1
        estado["reintento"] = None
        activo = {"lote": lote, "destino": _destino_visible(lote), "rcd": estado["rcd"],
                  "grupo": f"lote-{estado['n_lote']}", "jobid": None, "cancelado": False,
                  "cerrando": False, "fallos": 0, "omitidos": 0}
        estado["lote"] = activo
        panel.ocultar()
        actualizar_botones()
        return activo

    def quitar_espera() -> None:
        """Deja de esperar la siguiente petición de progreso."""
        sondeo_lote.cancelar()
        if estado["tras"] is not None:
            try:
                dlg.after_cancel(estado["tras"])
            except Exception:                # noqa: BLE001 — ya no está
                pass
            estado["tras"] = None

    def vigente(activo: dict) -> bool:
        """Si `activo` sigue siendo el lote que se sigue y la ventana lo puede pintar."""
        return not estado["cerrado"] and estado["lote"] is activo and not activo["cerrando"]

    def elementos_elegidos() -> tuple[transferencia.Elemento, ...]:
        """Devuelve las filas elegidas como elementos de un lote."""
        elegidas = (estado["entradas"].get(str(iid)) for iid in lista.selection())
        return tuple(transferencia.Elemento(e.nombre, e.es_carpeta) for e in elegidas if e)

    def bajar_elegidos() -> None:
        """«Bajar…»: pide la carpeta del equipo y baja lo elegido, con su estructura."""
        elementos = elementos_elegidos()
        if estado["lote"] is not None or estado["rcd"] is None or not elementos:
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
        if estado["lote"] is not None or estado["rcd"] is None:
            return
        remote, ruta_remota = nav.remote, nav.ruta      # antes del diálogo, como en «Bajar…»
        rutas = elegir_archivos(dlg, estado["carpeta"])
        if rutas:
            nombres = dict.fromkeys(os.path.basename(r) for r in rutas)
            subir_a(remote, ruta_remota, os.path.dirname(rutas[0]),
                    tuple(transferencia.Elemento(n, False) for n in nombres))

    def subir_carpeta() -> None:
        """«Subir carpeta…»: pide una carpeta del equipo y la sube, entera, a la que se ve."""
        if estado["lote"] is not None or estado["rcd"] is None:
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
        if estado["cerrado"] or estado["lote"] is not None or estado["rcd"] is None:
            return
        contar(nuevo_activo(lote))

    def contar(activo: dict) -> None:
        """Cuenta en segundo plano los archivos del lote que ya están en el destino."""
        indicador.poner(MIRANDO, True)
        accion.grid_remove()
        sondeo_lote.esperar(
            segundo_plano.lanzar(partial(_contar_choques, activo["rcd"], activo["lote"])),
            partial(choques_contados, activo))

    def choques_contados(activo: dict, encargo) -> None:
        """Con la cuenta hecha, pregunta qué hacer con los choques (si los hay) y copia."""
        if not vigente(activo):
            return
        decir("", "Pista.")
        if encargo.error is not None:
            acabar_con_error(activo, encargo.error, partial(reintentar_conteo, activo["lote"]))
            return
        omitir = False
        if encargo.resultado > 0:
            respuesta = tk_transferencia.preguntar_choques(
                dlg, transferencia.texto_choques(encargo.resultado, activo["destino"]))
            if not vigente(activo):
                return
            if respuesta is None:
                soltar_lote()
                return
            omitir = respuesta == "omitir"
        copiar(activo, omitir, encargo.resultado if omitir else 0)

    def copiar(activo: dict, omitir: bool, omitidos: int = 0) -> None:
        """Lanza el `sync/copy` del lote en segundo plano.

        Args:
            activo: El lote en marcha.
            omitir: Si los archivos que ya existen se dejan como están.
            omitidos: Cuántos son (los choques contados); es lo que dirá el resultado.
        """
        estado["reintento"] = None
        activo["omitidos"] = omitidos
        sondeo_lote.esperar(
            segundo_plano.lanzar(partial(_lanzar_copia, activo["rcd"], activo["lote"], omitir,
                                         activo["grupo"])),
            partial(copia_lanzada, activo, omitir))

    def copia_lanzada(activo: dict, omitir: bool, encargo) -> None:
        """Con el `jobid` en la mano, enseña el panel y empieza a seguir el trabajo."""
        if not vigente(activo):
            return
        if encargo.error is not None:
            acabar_con_error(activo, encargo.error,
                             partial(reintentar_copia, activo["lote"], omitir, activo["omitidos"]))
            return
        activo["jobid"] = encargo.resultado
        activo["omitir"] = omitir
        panel.mostrar_progreso(transferencia.progreso_de({}, activo["lote"], activo["destino"]))
        reajustar()
        sondear(activo)

    def sondear(activo: dict) -> None:
        """Pide en segundo plano el progreso y el estado del trabajo."""
        estado["tras"] = None
        if not vigente(activo):
            return
        sondeo_lote.esperar(
            segundo_plano.lanzar(partial(_sondear, activo["rcd"], activo["jobid"],
                                         activo["grupo"])),
            partial(progreso_llega, activo))

    def progreso_llega(activo: dict, encargo) -> None:
        """Pinta el progreso que llegó, o el resultado si el trabajo acabó."""
        if not vigente(activo):
            return
        if encargo.error is not None:
            sin_respuesta(activo, encargo.error)
            return
        if activo["fallos"]:
            if activo["fallos"] >= FALLOS_PARA_AVISAR:
                decir("", "Pista.")
            activo["fallos"] = 0
        stats, st = encargo.resultado
        if st.get("finished"):
            cancelado = activo["cancelado"] and not st.get("success")
            acabar(activo, transferencia.resultado_de(
                st, stats, cancelado, activo["destino"], activo["omitidos"]))
            return
        if activo["cancelado"]:
            panel.mostrar_cancelando()
        else:
            panel.mostrar_progreso(
                transferencia.progreso_de(stats, activo["lote"], activo["destino"]))
        estado["tras"] = dlg.after(INTERVALO_PROGRESO_MS, partial(sondear, activo))

    def sin_respuesta(activo: dict, error: Exception) -> None:
        """Un seguimiento falló: con el `rcd` vivo se sigue intentando; si murió, el lote acabó.

        Mientras el proceso vive, la copia puede seguir corriendo aunque rclone no
        conteste (una petición perdida, un tiempo de espera), así que el lote
        sigue activo y los botones apagados: solo acaba cuando `job/status` dice
        `finished`, cuando el proceso muere o cuando se cierra. Nunca se ofrece
        «Reintentar» con una copia que puede estar en marcha.
        """
        if not activo["rcd"].vivo:
            acabar_con_error(activo, rcd.RcdCaido(str(error)), None)
            return
        activo["fallos"] += 1
        if activo["fallos"] == FALLOS_PARA_AVISAR:
            decir(SIN_RESPUESTA, "Aviso.")
        estado["tras"] = dlg.after(INTERVALO_PROGRESO_MS, partial(sondear, activo))

    def soltar_lote() -> None:
        """Da el lote por acabado: vuelven los botones."""
        estado["lote"] = None
        actualizar_botones()

    def acabar(activo: dict, resultado: transferencia.Resultado, releer: bool = True) -> None:
        """Enseña cómo acabó el lote; si se subió a la carpeta que se ve, la relee."""
        lote = activo["lote"]
        panel.mostrar_resultado(resultado)
        if resultado.reintentar:
            estado["reintento"] = partial(reintentar_copia, lote, activo.get("omitir", False),
                                          activo["omitidos"])
        soltar_lote()
        reajustar()
        if (releer and lote.sentido == transferencia.SUBIR and lote.remote == nav.remote
                and lote.ruta_remota == nav.ruta):
            repetir()                       # también tras un fallo o una cancelación: algo subió

    def acabar_con_error(activo: dict, error: Exception, reintento) -> None:
        """Dice por qué no pudo seguir el lote; con la conexión perdida, ofrece «Reconectar»."""
        if isinstance(error, rcd.RcdCaido):
            decir(servidor.frase_error(error), boton="Reconectar")
            acabar(activo, transferencia.Resultado(PERDIDA, "aviso", False), releer=False)
            return
        if isinstance(error, rcd.ErrorRc):
            resultado = transferencia.resultado_de(
                {"success": False, "error": error.mensaje}, {}, False, activo["destino"])
        else:
            resultado = transferencia.Resultado(servidor.frase_error(error), "aviso", True)
        acabar(activo, resultado)
        estado["reintento"] = reintento if resultado.reintentar else None

    def cancelar_lote() -> None:
        """«Cancelar»: pide parar el trabajo, una sola vez, y dice «Cancelando…» en el acto."""
        activo = estado["lote"]
        if activo is None or activo["jobid"] is None or activo["cancelado"]:
            return
        activo["cancelado"] = True
        panel.mostrar_cancelando()
        segundo_plano.lanzar(partial(rcd.cancelar, activo["rcd"], activo["jobid"]))

    def reintentar_copia(lote: transferencia.Lote, omitir: bool, omitidos: int) -> None:
        """Repite el lote con la misma decisión de choques: lo ya copiado e idéntico se salta."""
        copiar(nuevo_activo(lote), omitir, omitidos)

    def reintentar_conteo(lote: transferencia.Lote) -> None:
        """Repite el lote desde el principio (no llegó a copiar nada)."""
        contar(nuevo_activo(lote))

    def reintentar_lote() -> None:
        """«Reintentar» del panel: repite el último lote que falló."""
        if estado["lote"] is None and estado["rcd"] is not None and estado["reintento"]:
            estado["reintento"]()

    # ------------------------------------------------------------- cerrar
    def cerrar(evento=None) -> None:
        """Para el `rcd` en segundo plano, una vez, se cierre por donde se cierre."""
        if evento is not None and str(evento.widget) != str(dlg):
            return                          # se destruye un hijo, no la ventana
        if estado["cerrado"]:
            return
        estado["cerrado"] = True
        if estado["tras"] is not None:
            try:
                dlg.after_cancel(estado["tras"])
            except Exception:                # noqa: BLE001 — ya no está
                pass
            estado["tras"] = None
        if estado["rcd"] is not None:
            segundo_plano.lanzar(partial(estado["rcd"].parar))

    def cerrar_ventana() -> None:
        """Cierra; con un lote en marcha pregunta y, si se acepta, lo cancela antes.

        Se espera a que rclone acabe el trabajo (hasta `rcd.ESPERA_QUIT`, en
        segundo plano) y solo entonces se cierra como siempre, parando el `rcd`.
        """
        activo = estado["lote"]
        if activo is not None and activo["jobid"] is not None:
            if activo["cerrando"]:
                return                      # ya se está cancelando para cerrar
            if not preguntar(dlg, TITULO_CIERRE, TEXTO_CIERRE, "Cancelar y cerrar", "Seguir"):
                return
            if estado["cerrado"]:
                return
            if estado["lote"] is activo:    # el trabajo pudo acabar mientras se preguntaba
                activo["cerrando"] = activo["cancelado"] = True
                quitar_espera()
                panel.mostrar_cancelando()
                sondeo_lote.esperar(
                    segundo_plano.lanzar(partial(_cancelar_y_esperar, activo["rcd"],
                                                 activo["jobid"])),
                    lambda _encargo: cierre_final())
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
