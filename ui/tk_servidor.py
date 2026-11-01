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

Arriba va la barra de direcciones (`ui/tk_direcciones.py`): atrás, adelante,
arriba, releer, las migas con el menú de servidores, la ruta escrita y la
búsqueda. El historial (`servidor.Historial`) se apunta cuando un listado llega,
nunca al pedirlo: una carpeta que falla no entra en él.

Buscar recorre las carpetas de debajo de la que se ve, `CONCURRENCIA_BUSQUEDA`
listados a la vez (`servidor.Busqueda` lleva la cuenta; cada listado, su
`Sondeo`), y la lista pasa a resultados según llegan, con la columna «Carpeta».
Lo leído se guarda: afinar el texto, o volver a los resultados con «Atrás», no
vuelve al servidor. En los resultados solo se abre o se va a la ubicación; lo
demás se hace en su carpeta.

Cerrar la ventana para el `rcd` también en segundo plano, una sola vez, sin
esperarlo.

La ventana se puede agrandar y encoger. El contenido pide su mínimo (la lista,
`FILAS_MINIMAS` filas) y estira: abre con el tamaño que tenía al cerrarse la
última vez (`state/ventana.json`) o, la primera, con `FILAS_VISIBLES` filas, y ya
enseñada no cambia de tamaño sola: el panel de un lote o la línea de lo cortado le
quitan sitio a la lista, como en el Explorador.

Bajar y subir (pieza 2): la lista admite varias filas; «Bajar…» va en el menú del
botón derecho de una fila y «Subir» (archivos o carpeta) en la botonera. Un lote es
UN `sync/copy` asíncrono del
`rcd` (`common/rcd.py`); qué se copia, los avisos por pareja y los textos los
decide `ui/transferencia.py` y el panel que lo enseña es `ui/tk_transferencia.py`.
Aquí se encadena el flujo: elegir → avisar/bloquear → contar choques en segundo
plano → preguntar → copiar → seguir el progreso cada `INTERVALO_PROGRESO_MS` →
resultado. Lo que espera a la red va en segundo plano con funciones de módulo;
el `Sondeo` del lote es distinto del de los listados para que navegar no pise a
la transferencia. Lanzar la copia, seguirla, cancelarla y cerrar con ella en
marcha lo hace `ui/tk_lote.Seguimiento`; aquí solo se cuenta antes y se dice
qué es un lote de copia. Copiar nunca borra.

Gestionar (pieza 3): «Nueva carpeta…» en la botonera, entre la línea del indicador
y la lista; «Renombrar…», «Cortar», «Pegar aquí» y «Borrar…» en el menú del botón
derecho y con teclas. Cada acción es un `Trabajo` de órdenes de
`rcd.lanzar_orden()` (una por elemento); qué se puede, qué se avisa y los textos
los decide `ui/gestion.py`, y el diálogo del nombre y la barra son de
`ui/tk_gestion.py`. El flujo: elegir → bloquear → mirar en segundo plano (los
nombres del destino, o lo que hay dentro de lo que se borra) → confirmar cuando
toca → lanzar → releer la carpeta que se ve y elegir lo nuevo. Un nombre nunca se
lanza sobre otro que ya existe: los del destino se releen justo antes, y otra vez tras
el «sí» de una confirmación. Un renombrado que solo cambia mayúsculas pasa por un
nombre temporal libre (`gestion.con_temporal`).

Mover es cortar, navegar y pegar: «Cortar» apunta `(remote, carpeta, elementos)` y
enseña una línea encima de la lista («3 elementos para mover desde /datos»); «Pegar
aquí» mueve lo cortado a la carpeta que se ve, en el mismo remote. Lo cortado no se
toca hasta pegar y se quita al pegar, con «Cancelar» o al cortar otra cosa; lo que un
borrado o un renombrado saca de su carpeta deja de estar cortado.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from functools import partial
from typing import NamedTuple

from common import config_file, model, rcd
from common.model import Config, ConfigError

from . import (gestion, icons, prefs, remote_picker, segundo_plano, servidor, theme,
               tk_direcciones, tk_gestion, tk_lote, tk_transferencia, transferencia)
from .tk import (Indicador, Sondeo, avisar, cuerpo_visible, modal, mostrar, pantalla_util,
                 preguntar)

COLUMNAS = [
    ("Nombre", 120, True),
    ("Tamaño", 90, False),
    ("Modificado", 140, False),
    ("Permisos", 90, False),
]
"""Las columnas de la lista: título, ancho en medidas del diseño y si estira.

La primera es la del árbol (`#0`), la única de una `Treeview` que lleva icono. Los
anchos son mínimos: lo que piden todas, también con `COLUMNA_CARPETA`, cabe en
`ANCHO_MINIMO`, porque la ventana no crece sola; el nombre se queda lo que sobra.
"""
COLUMNA_CARPETA = ("Carpeta", 120, True)
"""La columna de los resultados de una búsqueda: dónde está cada uno (oculta si no se busca)."""
FILAS_VISIBLES = 12
"""Cuántas filas enseña la lista la primera vez que se abre la ventana."""
FILAS_MINIMAS = 5
"""Cuántas filas pide la lista: el mínimo; con la ventana más grande, estira."""
ANCHO_INICIAL = 820
"""Ancho (px del diseño) del recuadro la primera vez que se abre la ventana."""
ANCHO_MINIMO = 640
"""Ancho mínimo (px del diseño) del recuadro: caben la barra y las líneas que cortan."""
ANCHO_INDICADOR = 440
"""Ancho (px del diseño) donde corta la frase del indicador: cabe en `ANCHO_MINIMO`."""

VACIA = "Esta carpeta está vacía."
NADA = "Nada coincide con «{}»."
"""Lo que dice la lista cuando una búsqueda acaba sin resultados; `{}` es el texto."""
ESPERA_BUSQUEDA_MS = 400
"""Milisegundos sin teclear tras los que se busca lo escrito (Intro busca en el acto)."""
CONCURRENCIA_BUSQUEDA = 4
"""Cuántos listados pide a la vez una búsqueda: como mucho, tantas conexiones SSH."""
_CON_CARPETA = ("carpeta", "tamano", "modificado", "permisos")
_SIN_CARPETA = ("tamano", "modificado", "permisos")
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


def _fila(e: servidor.Entrada, ruta: str, remote: str, iid: str, config: Config,
          sin_acceso: set[tuple[str, str]], mi_uid: int | None) -> FilaLista:
    """Devuelve la fila de una entrada: icono, nombre, tamaño, fecha y permisos.

    Una carpeta que es la de una pareja lleva su nombre; una en la que no se
    puede entrar (ya falló, o sus permisos lo dicen con seguridad) lleva
    candado y va apagada.

    Args:
        e: La entrada.
        ruta: Su ruta absoluta en el remote.
        remote: Su remote.
        iid: Cómo se llama su fila en la lista.
        config: El config, por las parejas.
        sin_acceso: Los `(remote, ruta)` en los que entrar ya falló por permiso.
        mi_uid: El uid del usuario en el servidor, o `None`.
    """
    nombre, tono, icono = e.nombre, "ok", "file"
    if e.es_carpeta:
        icono = "carpeta"
        pareja = servidor.marca(config, remote, ruta)
        if pareja:
            nombre += MARCA_PAREJA.format(pareja)
        if (remote, ruta) in sin_acceso or servidor.sin_acceso_previo(e, mi_uid):
            icono, tono = "candado", "apagado"
    return FilaLista(iid, nombre,
                     (servidor.tamano_legible(e.tamano), servidor.fecha_legible(e.fecha),
                      servidor.texto_permisos(e.modo)),
                     icono, tono)


def _filas(nav: servidor.Navegacion, config: Config, mi_uid: int | None) -> list[FilaLista]:
    """Devuelve las filas de lo que enseña `nav` (la iid de cada una es su nombre)."""
    return [_fila(e, nav.hijo(e.nombre), nav.remote, e.nombre, config, nav.sin_acceso, mi_uid)
            for e in nav.entradas]


def _listar(r: rcd.Rcd, remote: str, carpeta: str, permisos: bool) -> tuple[servidor.Entrada, ...]:
    """Lista una carpeta para una búsqueda; corre en un hilo.

    Raises:
        rcd.ErrorRc: Si rclone contesta con un error (sin permiso, ya no está…).
        rcd.RcdCaido: Si no se puede hablar con `rcd`.
    """
    return servidor.entradas_de(
        r.llamar("operations/list", servidor.params_listado(remote, carpeta, permisos)))


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

    Una carpeta se cuenta con un `operations/size` sobre su propio `fs`; un archivo vale
    `(1, su tamaño)` y no pregunta nada.

    Args:
        r: El `rcd` al que se habla.
        op: El borrado.
        tamanos: El tamaño de cada archivo elegido, por nombre, tal como lo dio el listado.

    Raises:
        rcd.ErrorRc: Si rclone contesta con un error.
        rcd.RcdCaido: Si no se puede hablar con `rcd`.
    """
    conteos: dict[str, tuple[int, int]] = {}
    for e in op.elementos:
        if e.es_carpeta:
            conteos[e.nombre] = rcd.tamano(r, gestion.fs_de_ruta(op.remote, op.carpeta, e.nombre))
        else:
            conteos[e.nombre] = (1, tamanos.get(e.nombre, 0))
    return conteos


def _fallo_al_mirar(r: rcd.Rcd, error: Exception) -> Exception:
    """Devuelve el error con el que acaba mirar el servidor antes de actuar.

    Un `RcdCaido` con el proceso vivo es una respuesta que no llegó (el tope de 60 s de
    una carpeta enorme, una conexión cortada): se dice como un fallo al mirar, con
    «Reintentar», y no como la conexión perdida. Con el proceso muerto, sí lo es.
    """
    if isinstance(error, rcd.RcdCaido) and r.vivo:
        return rcd.ErrorRc(str(error), 0)
    return error


def _resultado_de_mirar(estados: list[dict], _stats: dict, _cancelado: bool):
    """Dice por qué no se pudo mirar el servidor antes de actuar, y ofrece «Reintentar».

    Es el `resultado` de un `Trabajo` que falló antes de lanzar ninguna orden: el último
    estado trae el error de rclone.
    """
    error = rcd.ErrorRc(str((estados[-1].get("error") if estados else "")
                            or "no se ha podido mirar el servidor"), 0)
    return transferencia.Resultado(servidor.frase_error(error), "aviso", True)


def _clave_tamano(dlg) -> str:
    """La clave con la que se recuerda el tamaño: el sistema, el Tk y su escala."""
    import tkinter as tk

    return prefs.clave_ancho(str(tk.TkVersion), float(dlg.tk.call("tk", "scaling")))


def _fijar_tamanos(dlg, lista) -> None:
    """Pone a la ventana, aún sin enseñar, su tamaño de partida y su mínimo.

    El contenido pide su mínimo (`FILAS_MINIMAS` filas y `ANCHO_MINIMO`). La
    ventana abre con el tamaño recordado (`servidor_ancho`/`servidor_alto`) o,
    sin él, con `ANCHO_INICIAL` y sitio para `FILAS_VISIBLES` filas: es lo que se
    le da al `Visor` como tamaño de partida, y `encajar()` lo recorta a la
    pantalla. El mínimo de la ventana es el del contenido más las franjas de
    las barras del `Visor`, también recortado a la pantalla.
    """
    from tkinter import ttk

    visor = dlg.visor
    dlg.update_idletasks()
    # La tarjeta de la lista pide lo que pide ahora (cinco filas y las columnas a su
    # mínimo) y no lo que pida la lista después: una `Treeview` pide el ancho con el que
    # se configuraron sus columnas, y una columna de más (la de los resultados) o un
    # reparto ensancharían la ventana. Dentro, las columnas se ajustan a lo que haya.
    tarjeta = lista.master
    tarjeta.configure(width=tarjeta.winfo_reqwidth(), height=tarjeta.winfo_reqheight())
    tarjeta.grid_propagate(False)
    dlg.update_idletasks()
    minimo = (max(visor.interior.winfo_reqwidth(), icons.px(dlg, ANCHO_MINIMO)),
              visor.interior.winfo_reqheight())
    fila = int(ttk.Style(lista).lookup("Treeview", "rowheight") or icons.px(dlg, 28))
    clave = _clave_tamano(dlg)
    recordado = (prefs.recordado("servidor_ancho", clave), prefs.recordado("servidor_alto", clave))
    inicial = (max(minimo[0], icons.px(dlg, ANCHO_INICIAL)),
               minimo[1] + (FILAS_VISIBLES - FILAS_MINIMAS) * fila)
    if None not in recordado:
        inicial = recordado
    visor.base = (max(minimo[0], inicial[0]), max(minimo[1], inicial[1]))
    franjas = (visor.marco.winfo_reqwidth() - visor.lienzo.winfo_reqwidth(),
               visor.marco.winfo_reqheight() - visor.lienzo.winfo_reqheight())
    util = pantalla_util(dlg)
    dlg.minsize(min(minimo[0] + franjas[0], util[0]), min(minimo[1] + franjas[1], util[1]))


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
    historial = servidor.Historial()
    estado: dict = {"rcd": None, "ultima": ("ruta", servidor.RAIZ), "abierto": False,
                    "cerrado": False, "puerto_reintentado": False, "entradas": {},
                    "n_lote": 0, "tras": None, "corte": None,
                    "carpeta": os.path.expanduser("~"),
                    "busqueda": None, "texto": "", "resultados": {}, "en_resultados": False,
                    "espera": None, "siguiendo": False, "otra_vez": False}
    sondeos: dict[str, tuple[bool, int | None]] = {}
    # Un `Sondeo` espera un encargo cada vez: uno por listado en vuelo de una búsqueda.
    libres = [Sondeo(dlg) for _ in range(CONCURRENCIA_BUSQUEDA)]

    dlg.resizable(True, True)       # antes de enseñarla: la barra de título oscura (`ui.md`)
    marco = cuerpo_visible(dlg, redimensionable=True,
                           padding=(theme.E5, theme.E4, theme.E5, theme.E4))
    marco.columnconfigure(0, weight=1)
    marco.rowconfigure(4, weight=1)     # la lista se queda lo que sobra

    # La barra de direcciones: qué hace cada cosa se resuelve al pulsar (abajo).
    direcciones = tk_direcciones.Direcciones(marco, {
        "atras": lambda: atras(), "adelante": lambda: adelante(), "arriba": lambda: subir(),
        "releer": lambda: releer(), "ir": lambda r: ir_a(r),
        "servidor": lambda n: cambiar_remote(n), "escrita": lambda t: ir_a_escrita(t),
        "buscar": lambda t: al_escribir(t), "buscar_ya": lambda t: buscar_ahora(t, True),
        "vaciar": lambda: vaciar_busqueda()},
        mostrar_menu=lambda menu, x, y: _mostrar_menu(menu, x, y))
    direcciones.marco.grid(row=0, column=0, sticky="ew")
    direcciones.poner(nav.remote, nav.ruta, list(remotes))
    dlg.direcciones = direcciones

    linea = ttk.Frame(marco)
    linea.grid(row=1, column=0, sticky="ew", pady=(theme.E3, 0))
    linea.columnconfigure(0, weight=1)
    indicador = Indicador(linea, ancho=ANCHO_INDICADOR)
    indicador.marco.grid(row=0, column=0, sticky="ew")
    accion = ttk.Button(linea, text="", style="Quiet.TButton")
    accion.grid(row=0, column=1, sticky="e", padx=(theme.E3, 0))
    accion.grid_remove()
    dlg.indicador, dlg.sondeo = indicador, sondeo      # como en «Dispositivos»: los tests los miran

    # La botonera, entre la línea del indicador y la lista: «Subir» y «Nueva carpeta…».
    # Qué hace cada botón se resuelve al pulsar (las acciones se definen más abajo).
    barra_gestion = tk_gestion.Barra(marco, {"subir": lambda: desplegar_subir(),
                                             "nueva": lambda: nueva_carpeta()})
    barra_gestion.marco.grid(row=2, column=0, sticky="w", pady=(theme.E3, 0))
    dlg.barra = barra_gestion

    # La línea de lo cortado, entre la barra y la lista: sin corte no ocupa sitio.
    corte = tk_gestion.linea_corte(marco, lambda: pegar_aqui(), lambda: quitar_corte())
    corte.grid(row=3, column=0, sticky="ew", pady=(theme.E3, 0))
    corte.grid_remove()
    dlg.cortado = corte

    # La carpeta y el archivo llevan su icono en la columna del árbol (#0), la única
    # de una `Treeview` que lo admite; el árbol no se despliega: se entra.
    tarjeta = ttk.Frame(marco, style="Card.TFrame",
                        padding=(theme.E2, theme.E2, theme.E1, theme.E1))
    tarjeta.grid(row=4, column=0, sticky="nsew", pady=(theme.E4, 0))
    tarjeta.columnconfigure(0, weight=1)
    tarjeta.rowconfigure(0, weight=1)
    lista = ttk.Treeview(tarjeta, columns=_CON_CARPETA, displaycolumns=_SIN_CARPETA,
                         show=("tree", "headings"), height=FILAS_MINIMAS, selectmode="extended")
    for columna, (titulo, ancho, estira) in zip(("#0", "tamano", "modificado", "permisos"),
                                                COLUMNAS):
        lista.heading(columna, text=titulo, anchor="w")
        lista.column(columna, width=icons.px(lista, ancho), stretch=estira, anchor="w")
    titulo, ancho, estira = COLUMNA_CARPETA
    lista.heading("carpeta", text=titulo, anchor="w")
    lista.column("carpeta", width=icons.px(lista, ancho), stretch=estira, anchor="w")
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
    dlg.lista, dlg.vacia, dlg.accion = lista, vacia, accion

    # El panel de un lote, entre la lista y el pie: sin lote no ocupa sitio.
    panel = tk_transferencia.Panel(marco)
    panel.marco.grid(row=5, column=0, sticky="ew")
    panel.ocultar()
    panel.al_cancelar = lambda: seg.cancelar()
    panel.al_reintentar = lambda: reintentar_lote()

    # El pie, como la barra de estado del Explorador: solo la cuenta. Cierra la X.
    pie = ttk.Frame(marco)
    pie.grid(row=6, column=0, sticky="ew", pady=(theme.E3, 0))
    pie.columnconfigure(0, weight=1)
    cuenta = ttk.Label(pie, text="", style="MonoPista.TLabel")
    cuenta.grid(row=0, column=0, sticky="w")
    dlg.cuenta, dlg.panel, dlg.sondeo_lote = cuenta, panel, sondeo_lote

    # ------------------------------------------------------------- lo que se ve
    def decir(texto: str, tono: str = "Peligro.", boton: str | None = None) -> None:
        """Pone una frase en el indicador, sin barra, y con el botón de acción si toca."""
        indicador.poner(texto, False, tono)
        if boton is None:
            accion.grid_remove()
        else:
            accion.configure(text=boton, command={"Reconectar": reconectar,
                                                  "Reintentar": reintentar,
                                                  "Detener": detener_busqueda}[boton])
            accion.grid()

    def pintar_lista() -> None:
        """Pone en la lista las filas de lo que enseña `nav`."""
        mi_uid = sondeos.get(nav.remote, (False, None))[1]
        estado["entradas"] = {e.nombre: e for e in nav.entradas}
        if estado["en_resultados"]:
            estado["en_resultados"] = False
            columnas(_SIN_CARPETA)
        lista.delete(*lista.get_children())
        for f in _filas(nav, config, mi_uid):
            insertar(f, "")
        if estado["abierto"] and not nav.entradas:
            vacia.configure(text=VACIA)
            vacia.place(relx=0.5, rely=0.5, anchor="center")
        else:
            vacia.place_forget()
        actualizar_botones()

    def columnas(vistas: tuple[str, ...]) -> None:
        """Enseña esas columnas y reparte entre las que estiran el ancho que ocupaban todas.

        Una `Treeview` guarda como ancho de cada columna el que le dio al estirar, y lo
        pide; y solo reparte lo que cambia al redimensionarse, no el hueco que queda.
        Así que las que estiran vuelven a su mínimo y se llevan, a partes iguales, lo que
        sobra del ancho que ya ocupaban las de antes: la lista no pide más que la ventana
        y no queda hueco a la derecha.
        """
        antes = ("#0", *(str(c) for c in lista.tk.splitlist(lista.cget("displaycolumns"))))
        ocupado = sum(int(lista.column(c, "width")) for c in antes)
        lista.configure(displaycolumns=vistas)
        ahora = ("#0", *vistas)
        minimos = {"#0": COLUMNAS[0][1], "carpeta": COLUMNA_CARPETA[1]}
        estiran = [c for c in ahora if c in minimos]
        for c in estiran:
            lista.column(c, width=icons.px(lista, minimos[c]))
        sobra = ocupado - sum(int(lista.column(c, "width")) for c in ahora)
        if sobra > 0:
            for i, c in enumerate(estiran):
                parte = sobra // len(estiran) + (sobra % len(estiran) if i == 0 else 0)
                lista.column(c, width=int(lista.column(c, "width")) + parte)

    def insertar(f: FilaLista, carpeta: str) -> None:
        """Pone una fila al final de la lista; `carpeta` es su columna «Carpeta»."""
        foto = iconos[f.icono]
        lista.insert("", "end", iid=f.iid, text=f" {f.texto}", values=(carpeta, *f.valores),
                     tags=(f.tono,), **({"image": foto} if foto is not None else {}))

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
        """Repinta todo con la carpeta que acaba de llegar: lista, ruta, aviso de pareja y pie.

        Llegar una carpeta acaba la búsqueda que hubiera: el campo se vacía.
        """
        estado["abierto"] = True
        salir_de_busqueda(repintar=False)
        pintar_lista()
        direcciones.poner(nav.remote, nav.ruta, list(remotes))
        decir_lugar()
        tras, estado["tras"] = estado["tras"], None
        if tras is not None and tras[:2] == (nav.remote, nav.ruta):
            if tras[2]:
                decir(tras[2], "Pista.")
            elegir_nombres(tras[3])

    def decir_lugar() -> None:
        """La línea y el pie de la carpeta que se ve: el aviso si es de una pareja y la cuenta."""
        pareja = servidor.dentro_de(config, nav.remote, nav.ruta)
        if pareja:
            decir(f"Estás dentro de la pareja «{pareja}».", "Aviso.")
        else:
            decir("", "Pista.")
        cuenta.configure(text=servidor.cuantos(len(nav.entradas)))

    def libre() -> bool:
        """Si hay conexión con `rclone` y ningún lote ni cambio en marcha."""
        return estado["rcd"] is not None and seg.activo is None

    def puede_pegar() -> bool:
        """Si hay algo cortado, la ventana está libre y se ve el remote del que se cortó."""
        return (estado["corte"] is not None and libre()
                and estado["corte"][0] == nav.remote)

    def estados_menu() -> dict[str, bool]:
        """Qué acciones valen ahora: las de la botonera, los menús y las teclas.

        «Abrir» con una sola carpeta elegida y conexión (navegar no espera a un lote);
        «Bajar…», «Cortar» y «Borrar…» con una o más filas y la ventana libre;
        «Renombrar…» con exactamente una; subir y «Nueva carpeta…» con la ventana libre;
        «Pegar aquí» con algo cortado en este remote; «Releer» con conexión. En los
        resultados de una búsqueda, de lo elegido solo «Abrir» (una carpeta) y «Abrir la
        ubicación» (uno): lo demás se hace en su carpeta; la botonera sigue siendo la de
        la carpeta desde la que se busca.
        """
        filas = lista.selection()
        ok = libre()
        conectado = estado["rcd"] is not None
        if estado["en_resultados"]:
            r = estado["resultados"].get(str(filas[0])) if len(filas) == 1 else None
            return {"abrir": conectado and r is not None and r.entrada.es_carpeta,
                    "ubicacion": conectado and r is not None, "bajar": False,
                    "archivos": ok, "carpeta": ok, "nueva": ok, "renombrar": False,
                    "cortar": False, "borrar": False, "pegar": puede_pegar(),
                    "releer": conectado}
        una = estado["entradas"].get(str(filas[0])) if len(filas) == 1 else None
        return {"abrir": conectado and una is not None and una.es_carpeta, "ubicacion": False,
                "bajar": ok and bool(filas), "archivos": ok, "carpeta": ok, "nueva": ok,
                "renombrar": ok and una is not None, "cortar": ok and bool(filas),
                "borrar": ok and bool(filas), "pegar": puede_pegar(), "releer": conectado}

    def pintar_corte() -> None:
        """Enseña u oculta la línea de lo cortado y pone su texto y el estado de «Pegar aquí»."""
        hay = estado["corte"]
        if hay is None:
            corte.grid_remove()
            return
        remote, carpeta, elementos = hay
        corte.texto.configure(text=gestion.texto_corte(len(elementos), carpeta,
                                                       remote != nav.remote))
        corte.pegar.state(["!disabled" if puede_pegar() else "disabled"])
        corte.cancelar.state(["!disabled" if libre() else "disabled"])
        corte.grid()

    def actualizar_botones() -> None:
        """Enciende o apaga la barra de direcciones, la botonera y «Pegar aquí».

        Navegar solo pide conexión (no espera a un lote); subir y crear, la ventana libre.
        """
        ok = libre()
        conectado = estado["rcd"] is not None
        direcciones.encender(
            atras=conectado and historial.puede_atras,
            adelante=conectado and historial.puede_adelante,
            arriba=conectado and nav.ruta != servidor.RAIZ, releer=conectado,
            servidor=conectado and bool(remotes), buscar=conectado)
        barra_gestion.encender(subir=ok, nueva=ok)
        pintar_corte()

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

    def lanzar_peticion(pedida: tuple, esperar: bool | None = None) -> None:
        """Pide una carpeta, la raíz de otro remote o un lugar del historial.

        Args:
            pedida: Qué se pide: `("ruta", r)` o `("ruta", r, movimiento)` en el remote
                que se ve; `("remote", nombre)` para la raíz de otro; `("lugar", Lugar,
                movimiento)` para un paso del historial. Se guarda para repetirla tras
                «Reconectar»/«Reintentar».
            esperar: Si el hilo espera antes a que `rcd` conteste. Por defecto,
                mientras la ventana no haya enseñado nada todavía.
        """
        if estado["cerrado"]:
            return
        if estado["rcd"] is None:
            direcciones.poner(nav.remote, nav.ruta, list(remotes))  # sin rcd no cambia nada
            return
        estado["ultima"] = pedida
        clase, valor, *resto = pedida
        if clase == "ruta":
            p = nav.pedir(valor, *resto)
        elif clase == "remote":
            p = nav.cambiar_remote(valor)
        else:
            p = nav.ir(valor.remote, valor.ruta, resto[0], valor.busqueda)
        if p.movimiento != servidor.RELEER and estado["texto"]:
            # Se sale de una búsqueda: el lugar la guarda para volver a ella con «Atrás», y
            # se deja de recorrer. Los resultados se ven hasta que llegue la carpeta.
            historial.apuntar_busqueda(estado["texto"])
            detener_busqueda()
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
        historial.llegar(servidor.Lugar(p.remote, p.ruta, p.busqueda), p.movimiento)
        sondeos[p.remote] = (lectura.permisos, lectura.mi_uid)
        pintar()
        if p.busqueda:
            # se vuelve a un lugar desde el que se buscaba: a sus resultados
            direcciones.poner_busqueda(p.busqueda)
            buscar_ahora(p.busqueda, True)

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
        # la barra vuelve a la carpeta que se ve: un cambio de remote o una ruta
        # escrita que fallan no cambian nada
        direcciones.poner(nav.remote, nav.ruta, list(remotes))
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
        """Relanza `rcd` y repite la última petición; lo leído al buscar ya no vale."""
        estado["puerto_reintentado"] = False
        olvidar_busqueda()
        if conectar(forzar=True):
            lanzar_peticion(estado["ultima"], esperar=True)

    def reintentar() -> None:
        """Repite la última petición; relanza `rcd` solo si ya no está vivo."""
        estado["puerto_reintentado"] = False
        if conectar():
            lanzar_peticion(estado["ultima"], esperar=True)

    # ------------------------------------------------------------- navegar
    def entrar(_evento=None) -> str:
        """Entra en la carpeta elegida; un archivo, o varias filas, nada.

        En los resultados de una búsqueda, una carpeta se abre y un archivo lleva a su
        carpeta, con él elegido.
        """
        elegida = lista.selection()
        if estado["en_resultados"]:
            r = estado["resultados"].get(str(elegida[0])) if len(elegida) == 1 else None
            if r is not None and r.entrada.es_carpeta:
                lanzar_peticion(("ruta", r.ruta))
            elif r is not None:
                ubicacion()
            return "break"
        e = estado["entradas"].get(str(elegida[0])) if len(elegida) == 1 else None
        if e is not None and e.es_carpeta:
            lanzar_peticion(("ruta", nav.hijo(e.nombre)))
        return "break"

    def ubicacion() -> None:
        """«Abrir la ubicación»: va a la carpeta de un resultado y lo deja elegido."""
        elegida = lista.selection()
        r = estado["resultados"].get(str(elegida[0])) if len(elegida) == 1 else None
        if r is None or estado["rcd"] is None:
            return
        estado["tras"] = (nav.remote, r.carpeta, "", (r.entrada.nombre,))
        lanzar_peticion(("ruta", r.carpeta))

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
        """Vuelve a leer la carpeta que se enseña (no mueve el historial).

        Algo pudo cambiar en el servidor: lo leído al buscar ya no vale.
        """
        olvidar_busqueda()
        lanzar_peticion(("ruta", nav.ruta, servidor.RELEER))

    def releer() -> None:
        """«Releer» y F5: con una búsqueda, la recorre otra vez; si no, relee la carpeta."""
        if estado["en_resultados"] and estado["texto"]:
            olvidar_busqueda()
            buscar_ahora(estado["texto"], True)
        else:
            repetir()

    # ------------------------------------------------------------- buscar
    def al_escribir(_texto: str) -> None:
        """Cada cambio del campo de búsqueda: busca cuando se deja de teclear, o sale."""
        cancelar_espera()
        if not direcciones.texto_busqueda.get().strip():
            vaciar_busqueda()
            return
        estado["espera"] = dlg.after(
            ESPERA_BUSQUEDA_MS, lambda: buscar_ahora(direcciones.texto_busqueda.get()))

    def cancelar_espera() -> None:
        if estado["espera"] is not None:
            dlg.after_cancel(estado["espera"])
            estado["espera"] = None

    def buscar_ahora(texto: str, reanudar: bool = False) -> None:
        """Busca `texto` desde la carpeta que se ve, en todas las de debajo.

        Si ya hay un recorrido de esta carpeta, se filtra lo leído sin volver al
        servidor y se sigue donde iba (con `reanudar`, también si se había detenido).
        """
        cancelar_espera()
        texto = texto.strip()
        if not texto:
            vaciar_busqueda()
            return
        if estado["rcd"] is None or estado["cerrado"]:
            return
        b = estado["busqueda"]
        if b is None or (b.remote, b.raiz) != (nav.remote, nav.ruta):
            olvidar_busqueda()
            b = servidor.Busqueda(nav.remote, nav.ruta, sondeos.get(nav.remote, (False, None))[0],
                                  nav.entradas)
            estado["busqueda"] = b
        elif reanudar:
            b.reanudar()
        estado["texto"] = texto
        if not estado["en_resultados"]:
            estado["en_resultados"] = True
            columnas(_CON_CARPETA)
        lista.delete(*lista.get_children())
        estado["resultados"] = {}
        pintar_resultados(b.resultados(texto))
        seguir_buscando()

    def pintar_resultados(resultados) -> None:
        """Añade resultados al final de la lista (los que ya estaban no se repiten)."""
        b = estado["busqueda"]
        mi_uid = sondeos.get(b.remote, (False, None))[1]
        for r in resultados:
            if r.ruta in estado["resultados"]:
                continue
            estado["resultados"][r.ruta] = r
            insertar(_fila(r.entrada, r.ruta, b.remote, r.ruta, config, nav.sin_acceso, mi_uid),
                     r.carpeta)
        cuenta.configure(text=servidor.cuantos(len(estado["resultados"])))
        actualizar_botones()

    def seguir_buscando() -> None:
        """Pide las carpetas que faltan, hasta llenar los huecos libres, y dice cómo va.

        Un encargo que ya ha terminado se recoge en el acto (los tests lo hacen así), y
        su recogida vuelve aquí: entonces solo se apunta que hay que dar otra vuelta, para
        no anidar una llamada por carpeta.
        """
        if estado["siguiendo"]:
            estado["otra_vez"] = True
            return
        estado["siguiendo"] = True
        try:
            while True:
                estado["otra_vez"] = False
                b = estado["busqueda"]
                if (b is None or estado["cerrado"] or not estado["en_resultados"]
                        or estado["rcd"] is None):
                    break
                for carpeta in b.siguientes(len(libres)):
                    s = libres.pop()
                    encargo = segundo_plano.lanzar(partial(
                        _listar, estado["rcd"], b.remote, carpeta, b.permisos))
                    s.esperar(encargo, partial(llega_carpeta, s, b, b.numero, carpeta))
                if not estado["otra_vez"]:
                    break
        finally:
            estado["siguiendo"] = False
        decir_busqueda()

    def llega_carpeta(s, b: servidor.Busqueda, numero: int, carpeta: str, encargo) -> None:
        """Recoge el listado de una carpeta de la búsqueda: añade lo que coincide y sigue."""
        libres.append(s)
        if estado["cerrado"] or estado["busqueda"] is not b:
            return
        if encargo.error is not None:
            if not b.fallo(numero, carpeta):
                return
        elif not b.recibir(numero, carpeta, encargo.resultado):
            return
        elif estado["en_resultados"]:
            pintar_resultados(b.de_carpeta(estado["texto"], carpeta))
        seguir_buscando()

    def decir_busqueda() -> None:
        """La línea de la búsqueda: cómo va (con «Detener») o cómo acabó."""
        b, texto = estado["busqueda"], estado["texto"]
        if b is None or not estado["en_resultados"] or estado["cerrado"]:
            return
        encontrados = len(estado["resultados"])
        if b.acabada or b.detenida:
            decir(b.texto_final(texto, encontrados), "Pista.")
            if not encontrados:
                vacia.configure(text=NADA.format(texto))
                vacia.place(relx=0.5, rely=0.5, anchor="center")
            return
        vacia.place_forget()
        indicador.poner(b.texto_progreso(texto, encontrados), True)
        accion.configure(text="Detener", command=detener_busqueda)
        accion.grid()

    def detener_busqueda() -> None:
        """«Detener»: deja de pedir carpetas; lo leído se queda y se puede seguir con Intro."""
        b = estado["busqueda"]
        if b is not None and not b.acabada and not b.detenida:
            b.detener()
        decir_busqueda()

    def olvidar_busqueda() -> None:
        """Tira lo leído al buscar: algo pudo cambiar en el servidor."""
        b = estado["busqueda"]
        if b is not None and not b.detenida:
            b.detener()
        estado["busqueda"] = None

    def salir_de_busqueda(repintar: bool = True) -> None:
        """Deja de buscar: vacía el campo y, con `repintar`, vuelve a la carpeta que se ve.

        La carpeta no se vuelve a pedir: sus entradas siguen en `nav`. Lo leído se
        guarda para volver a ello.
        """
        cancelar_espera()
        b = estado["busqueda"]
        if b is not None and not b.acabada and not b.detenida:
            b.detener()
        estado["texto"] = ""
        direcciones.poner_busqueda("")
        if estado["en_resultados"] and repintar:
            pintar_lista()
            decir_lugar()

    def vaciar_busqueda() -> None:
        """Escape o el campo vacío: vuelve a la carpeta y su lugar ya no guarda búsqueda."""
        salir_de_busqueda()
        historial.apuntar_busqueda("")

    def cambiar_remote(nuevo: str) -> None:
        """Pasa a la raíz del remote elegido en el menú del servidor."""
        if nuevo and nuevo != nav.remote:
            lanzar_peticion(("remote", nuevo))

    def ir_a(ruta_: str) -> None:
        """Va a esa carpeta del remote que se ve (una miga)."""
        lanzar_peticion(("ruta", ruta_))

    def ir_a_escrita(texto: str) -> None:
        """Va a la ruta que se escribió en la barra (siempre desde la raíz del servidor)."""
        lanzar_peticion(("ruta", servidor.ruta_escrita(texto)))

    def atras(_evento=None) -> str:
        """Vuelve al lugar de antes del historial, si lo hay."""
        lugar = historial.anterior()
        if lugar is not None and estado["rcd"] is not None:
            lanzar_peticion(("lugar", lugar, servidor.ATRAS))
        return "break"

    def adelante(_evento=None) -> str:
        """Va al lugar de después del historial, si lo hay."""
        lugar = historial.siguiente()
        if lugar is not None and estado["rcd"] is not None:
            lanzar_peticion(("lugar", lugar, servidor.ADELANTE))
        return "break"

    def escribir_ruta(_evento=None) -> str:
        """Ctrl+L, Alt+D: la barra pasa a escribir la ruta."""
        direcciones.editar()
        return "break"

    def ir_a_busqueda(_evento=None) -> str:
        """Ctrl+F, Ctrl+E: el foco al campo de búsqueda."""
        direcciones.enfocar_busqueda()
        return "break"

    lista.bind("<<TreeviewSelect>>", lambda _e: actualizar_botones())
    lista.bind("<Double-Button-1>", doble_clic)
    lista.bind("<Return>", entrar)
    lista.bind("<KP_Enter>", entrar)
    lista.bind("<BackSpace>", subir)
    for secuencia, hacer in (("<Alt-Left>", atras), ("<Alt-Right>", adelante),
                             ("<Alt-Up>", subir), ("<Control-l>", escribir_ruta),
                             ("<Alt-d>", escribir_ruta), ("<Control-f>", ir_a_busqueda),
                             ("<Control-e>", ir_a_busqueda)):
        dlg.bind(secuencia, hacer)          # en toda la ventana, como en el Explorador


    # ------------------------------------------------------------- bajar y subir
    def cambio_de_lote() -> None:
        """Con el lote que cambia (o su panel): los botones según el lote.

        La ventana no cambia de tamaño: el panel le quita sitio a la lista.
        """
        actualizar_botones()

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

        Las órdenes, el progreso y qué dirá el resultado se vuelven a poner al lanzar
        (`lanzar_gestion`), con la operación ya comprobada contra el servidor: antes de
        eso lo único que puede fallar es mirar.
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
        nuevo, lo pegado) si sigue a la vista, y un resultado que fue a la línea de la ventana
        (el panel no llegó a salir) se vuelve a poner: leer la carpeta lo habría borrado.
        Lo cortado que un borrado o un renombrado sacó de su carpeta deja de estar cortado
        (`gestion.podar_corte`).
        """
        if op.tipo == gestion.MOVER:
            # Lo que se ve y se relee es el destino. Si salió alguna orden, lo cortado ya no
            # vale (algo se movió, o quedó a medias); si no (no se pudo ni mirar el destino),
            # sigue cortado para volver a intentarlo.
            carpeta, nuevos = op.destino or "", tuple(e.nombre for e in op.elementos)
            if t.jobid is not None:
                estado["corte"] = None
                pintar_corte()
        else:
            carpeta = op.carpeta
            nuevos = (op.nombre,) if op.tipo in (gestion.NUEVA, gestion.RENOMBRAR) and op.nombre else ()
            podado = gestion.podar_corte(estado["corte"], op, t.estados)
            if podado != estado["corte"]:
                estado["corte"] = podado
                pintar_corte()
        nota = resultado.texto if resultado.tono == "ok" and not t.panel_visto else ""
        estado["tras"] = (op.remote, carpeta, nota, nuevos)
        repetir()

    def lanzar_gestion(t: tk_lote.Trabajo, op: gestion.Operacion) -> None:
        """Lanza las órdenes de la operación una tras otra y las sigue.

        Las órdenes, el progreso, «Cancelando…», el resultado y lo que se hace al acabar
        salen de `op` tal como llega aquí: un renombrado lleva ya su nombre temporal, y
        entonces su segundo paso solo sale si el primero fue bien (`parar_si_falla`).
        """
        t.lanzadores = [partial(_lanzar_orden, o) for o in gestion.ordenes_de(op)]
        t.parar_si_falla = op.temporal is not None
        t.progreso = partial(gestion.progreso_de, op)
        t.cancelando = partial(gestion.cancelando_de, op)
        t.resultado = partial(gestion.resultado_de, op)
        t.al_acabar = partial(releer_tras_gestion, op, t)
        seg.lanzar(t)

    def confirmar_y_lanzar(t: tk_lote.Trabajo, op: gestion.Operacion, plan: gestion.Plan,
                           titulo: str, nota: str,
                           al_aceptar: Callable[[], None] | None = None) -> None:
        """Enseña lo que va a pasar y, con un «sí», sigue; con un «no» no lanza nada y libera la ventana.

        Args:
            t: El trabajo de la operación.
            op: La operación.
            plan: Lo que se enseña.
            titulo: El título de la confirmación.
            nota: La nota de la confirmación.
            al_aceptar: Lo que se hace con el «sí»; sin él, lanzar `op`.
        """
        from . import tk_pairs

        sigue = tk_pairs.confirmar_plan(dlg, plan, titulo, nota)
        if not seg.vigente(t):
            return
        if not sigue:
            seg.soltar()
        elif al_aceptar is not None:
            al_aceptar()
        else:
            lanzar_gestion(t, op)

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

    def mirar_destino(t: tk_lote.Trabajo, op: gestion.Operacion, actual: str | None,
                      confirmado: bool = False) -> None:
        """Relee en segundo plano los nombres de la carpeta del destino (al pegar, la de `destino`).

        Con `confirmado` es la segunda lectura, la de después del «sí»: si todo sigue
        libre se lanza sin volver a preguntar.
        """
        indicador.poner(MIRANDO, True)
        accion.grid_remove()
        carpeta = (op.destino or "") if op.tipo == gestion.MOVER else op.carpeta
        sondeo_lote.esperar(
            segundo_plano.lanzar(partial(_nombres_de, t.rcd, op.remote, carpeta)),
            partial(destino_mirado, t, op, actual, confirmado))

    def destino_mirado(t: tk_lote.Trabajo, op: gestion.Operacion, actual: str | None,
                       confirmado: bool, encargo) -> None:
        """Con los nombres de ahora: rechaza el que ya existe; si no, confirma (con avisos) y lanza.

        Al pegar se rechaza lo que `gestion.validar_pegado` no admite y, después, lo que
        bloquean las parejas y el catálogo (`gestion.bloqueo`): la persona sigue con lo
        cortado. Un renombrado que solo cambia mayúsculas toma aquí su nombre temporal,
        libre en este listado (`gestion.con_temporal`). La confirmación deja pasar el
        tiempo que tarde la persona, así que tras el «sí» se vuelve a mirar y a comprobar
        todo (`confirmado`) antes de lanzar.
        """
        if not seg.vigente(t):
            return
        decir("", "Pista.")
        if encargo.error is not None:
            seg.acabar_con_error(t, _fallo_al_mirar(t.rcd, encargo.error),
                                 partial(reintentar_nombre, op, actual))
            return
        if op.tipo == gestion.MOVER:
            motivo = (gestion.validar_pegado(op, encargo.resultado)
                      or gestion.bloqueo(op, config, catalogo))
        else:
            motivo = gestion.validar_nombre(op.nombre or "", encargo.resultado, actual)
        if motivo:
            seg.soltar()
            avisar(dlg, "No se puede", motivo, "Ambar.")
            return
        op = gestion.con_temporal(op, encargo.resultado)
        avisos = gestion.avisos(op, config)
        if avisos and not confirmado:
            confirmar_y_lanzar(t, op, gestion.plan_de(op, {}, avisos), "Carpeta de una pareja", "",
                               al_aceptar=partial(mirar_destino, t, op, actual, True))
        else:
            lanzar_gestion(t, op)

    def reintentar_nombre(op: gestion.Operacion, actual: str | None) -> None:
        """«Reintentar» tras no poder mirar el destino: vuelve a mirar.

        Un pegado solo se repite si lo cortado sigue siendo lo mismo: si la persona lo
        quitó o cortó otra cosa mientras tanto, no se lanza nada y el panel se quita.
        """
        if not libre():
            return
        if op.tipo == gestion.MOVER and estado["corte"] != (op.remote, op.carpeta, op.elementos):
            seg.reintento = None
            panel.ocultar()
            return
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
            seg.acabar_con_error(t, _fallo_al_mirar(t.rcd, encargo.error),
                                 partial(reintentar_borrado, op, tamanos))
            return
        plan = gestion.plan_de(op, encargo.resultado, gestion.avisos(op, config))
        confirmar_y_lanzar(t, op, plan, "Borrar del servidor", "El servidor no tiene papelera.")

    def reintentar_borrado(op: gestion.Operacion, tamanos: dict[str, int]) -> None:
        """«Reintentar» tras no poder contar: vuelve a contar desde el principio."""
        if libre():
            contar_borrado(nuevo_trabajo_gestion(op), op, tamanos)

    # -- cortar y pegar: lo cortado se queda en la ventana hasta pegar
    def cortar_elegidos() -> None:
        """«Cortar»: apunta lo elegido, con su carpeta y su remote, y enseña la línea del corte."""
        elementos = elementos_elegidos()
        if not libre() or not elementos:
            return
        estado["corte"] = (nav.remote, nav.ruta, elementos)
        actualizar_botones()

    def quitar_corte() -> None:
        """«Cancelar» de la línea: olvida lo cortado."""
        estado["corte"] = None
        actualizar_botones()

    def pegar_aqui() -> None:
        """«Pegar aquí»: mueve lo cortado a la carpeta que se ve, si es el mismo remote.

        Lee el destino antes de lanzar nada (`mirar_destino`); hasta que acaba el
        pegado, lo cortado sigue ahí.
        """
        if not puede_pegar():
            return
        remote, carpeta, elementos = estado["corte"]
        op = gestion.Operacion(gestion.MOVER, remote, carpeta, elementos, destino=nav.ruta)
        mirar_destino(nuevo_trabajo_gestion(op), op, None)

    # -- la botonera, las teclas y el botón derecho
    acciones = {"abrir": lambda: entrar(), "ubicacion": lambda: ubicacion(),
                "bajar": lambda: bajar_elegidos(),
                "archivos": lambda: subir_archivos(), "carpeta": lambda: subir_carpeta(),
                "nueva": lambda: nueva_carpeta(), "renombrar": lambda: renombrar_elegido(),
                "cortar": lambda: cortar_elegidos(), "pegar": lambda: pegar_aqui(),
                "borrar": lambda: borrar_elegidos(), "releer": lambda: releer()}
    dlg.acciones, dlg.estados_menu = acciones, estados_menu      # los tests las usan

    def con_tecla(clave: str):
        """Devuelve el manejador de una tecla: hace la acción solo si ahora se puede."""
        def al_pulsar(_evento=None) -> str:
            if estados_menu()[clave]:
                acciones[clave]()
            return "break"
        return al_pulsar

    def solo_este(menu):
        """Destruye el menú que se enseñó antes y apunta este: uno vivo por ventana.

        Windows tiene un tope de menús por proceso, y un menú que no se destruye vive
        hasta que se cierra la ventana.
        """
        import tkinter as tk

        viejo, estado["menu"] = estado.get("menu"), menu
        if viejo is not None:
            try:
                viejo.destroy()
            except tk.TclError:
                pass                        # ya no estaba
        return menu

    def desplegar_subir() -> None:
        """«Subir»: enseña su menú («Archivos…», «Carpeta…») justo debajo del botón."""
        boton = barra_gestion.subir
        menu = solo_este(tk_gestion.menu_subir(boton, acciones, estados_menu()))
        _mostrar_menu(menu, boton.winfo_rootx(), boton.winfo_rooty() + boton.winfo_height())

    def menu_derecho(evento) -> str:
        """Botón derecho: sobre una fila, el menú de lo elegido; en el hueco, el de la carpeta.

        Sobre una fila que no estaba elegida, la elige. En el hueco de la lista (sin fila
        debajo) quita la selección, como el Explorador. En la cabecera, nada.
        """
        if lista.identify_region(evento.x, evento.y) in ("heading", "separator"):
            return "break"
        fila = lista.identify_row(evento.y)
        lista.focus_set()
        if fila:
            if fila not in lista.selection():
                lista.selection_set(fila)
                lista.focus(fila)
            orden = (tk_gestion.ORDEN_MENU_RESULTADO if estado["en_resultados"]
                     else tk_gestion.ORDEN_MENU_FILA)
        else:
            lista.selection_remove(*lista.selection())
            orden = tk_gestion.ORDEN_MENU_HUECO
        menu = solo_este(tk_gestion.menu_contextual(lista, orden, acciones, estados_menu()))
        _mostrar_menu(menu, evento.x_root, evento.y_root)
        return "break"

    for secuencia, clave in (("<F2>", "renombrar"), ("<Delete>", "borrar"),
                             ("<Control-x>", "cortar"), ("<Control-v>", "pegar"),
                             ("<Control-N>", "nueva")):
        lista.bind(secuencia, con_tecla(clave))
    lista.bind("<Button-3>", menu_derecho)
    dlg.bind("<F5>", con_tecla("releer"))     # en toda la ventana: el foco puede no estar en la lista

    # ------------------------------------------------------------- cerrar
    def cerrar(evento=None) -> None:
        """Para el `rcd` en segundo plano, una vez, se cierre por donde se cierre."""
        if evento is not None and str(evento.widget) != str(dlg):
            return                          # se destruye un hijo, no la ventana
        if estado["cerrado"]:
            return
        estado["cerrado"] = True
        cancelar_espera()
        seg.parar()
        if estado["rcd"] is not None:
            segundo_plano.lanzar(partial(estado["rcd"].parar))
        recordar_tamano()

    def apuntar_tamano(evento) -> None:
        """Guarda el tamaño del recuadro cada vez que cambia con la ventana a la vista.

        Se guarda al cambiar y no al cerrar porque, al destruirse, sus hijos ya no
        están. Una ventana que no llegó a enseñarse no tiene un tamaño que recordar.
        """
        if dlg.winfo_ismapped() and evento.width > 1 and evento.height > 1:
            estado["tamano"] = (evento.width, evento.height)

    def recordar_tamano() -> None:
        """Recuerda en `state/ventana.json` el último tamaño del recuadro, si llegó a verse."""
        if estado.get("tamano") is None:
            return
        ancho, alto = estado["tamano"]
        clave = _clave_tamano(dlg)
        prefs.recordar("servidor_ancho", clave, ancho)
        prefs.recordar("servidor_alto", clave, alto)

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
        """Cierra la ventana: apunta su tamaño, para el `rcd` y la destruye."""
        if estado["cerrado"]:
            return
        lienzo = dlg.visor.lienzo
        if dlg.winfo_ismapped() and lienzo.winfo_width() > 1:
            estado["tamano"] = (lienzo.winfo_width(), lienzo.winfo_height())
        cerrar()
        dlg.destroy()

    dlg.protocol("WM_DELETE_WINDOW", cerrar_ventana)
    dlg.bind("<Destroy>", cerrar, add="+")

    # ------------------------------------------------------------- abrir
    _fijar_tamanos(dlg, lista)
    dlg.visor.lienzo.bind("<Configure>", apuntar_tamano, add="+")
    if not remotes:
        decir(SIN_REMOTES, "Pista.")
        actualizar_botones()
    else:
        indicador.poner(CONECTANDO, True)
        if conectar():
            lanzar_peticion(("ruta", servidor.RAIZ), esperar=True)
    mostrar(dlg, parent)
