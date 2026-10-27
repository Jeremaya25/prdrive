"""Lo que decide gestionar el servidor desde el explorador «Servidor…», sin Tk, sin disco y sin red.

La ventana (`ui/tk_servidor.py`) solo dibuja. Aquí vive qué se puede hacer: si un nombre
vale, si un pegado cabe en su destino, qué rutas del servidor toca cada acción (las que
salen y las que llegan), qué se bloquea porque rompería una pareja o el catálogo y qué
dirá la próxima pasada de cada pareja alcanzada.

Las rutas son absolutas (`/datos/x`) y la raíz es `/`. Las parejas se comparan siempre
contra las del MISMO remote, por tramos de ruta y con la más honda por delante
(`transferencia.parejas_que_contienen`).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from common import rcd
from common.model import Config

from . import remote_picker, servidor, transferencia
from .transferencia import Elemento

BORRAR = "borrar"
"""Quitar para siempre elementos del servidor."""
RENOMBRAR = "renombrar"
"""Cambiar el nombre de un elemento dentro de su carpeta."""
MOVER = "mover"
"""Llevar elementos a otra carpeta del mismo servidor."""
NUEVA = "nueva"
"""Crear una carpeta vacía."""


@dataclass(frozen=True)
class Operacion:
    """Un cambio que el usuario pidió en el servidor.

    Args:
        tipo: `BORRAR`, `RENOMBRAR`, `MOVER` o `NUEVA`.
        remote: Nombre del remote de `rclone.conf`.
        carpeta: Ruta absoluta donde están los elementos, o donde se crea la carpeta nueva.
        elementos: Lo elegido dentro de `carpeta`. `RENOMBRAR` lleva uno; `NUEVA`, ninguno.
        destino: Ruta absoluta de la carpeta a la que se pega (solo `MOVER`).
        nombre: El nombre nuevo (`RENOMBRAR`) o el de la carpeta nueva (`NUEVA`).
    """

    tipo: str
    remote: str
    carpeta: str
    elementos: tuple[Elemento, ...] = ()
    destino: str | None = None
    nombre: str | None = None


def _unir(carpeta: str, nombre: str) -> str:
    """Devuelve la ruta de `nombre` dentro de `carpeta`; en la raíz es `/nombre`, nunca `//nombre`."""
    return remote_picker.normalizar(carpeta).rstrip("/") + "/" + nombre


def validar_nombre(nombre: str, existentes: Iterable[str], actual: str | None = None) -> str | None:
    """Dice por qué un nombre no vale para una carpeta del servidor.

    El nombre se conserva tal cual lo escribió el usuario (un espacio al final es parte
    del nombre). Los nombres que ya existen se comparan con `casefold()`: en SMB, WebDAV o
    un OpenSSH de Windows `Fotos` y `fotos` son la misma carpeta.

    Args:
        nombre: El nombre propuesto.
        existentes: Los nombres que ya hay en la carpeta, incluido el de `actual`.
        actual: El nombre que lleva ahora lo que se renombra; `None` al crear.

    Returns:
        El motivo del rechazo, o `None` si vale. También `None` si `nombre` es exactamente
        `actual`: no hay nada que cambiar y quien llama no hace nada. Cambiar solo las
        mayúsculas del propio nombre sí vale.
    """
    if nombre.strip() == "":
        return "Escribe un nombre."
    if "/" in nombre:
        return "Un nombre no puede llevar «/»."
    if nombre in (".", ".."):
        return "Ese nombre no vale."
    if nombre == actual:
        return None
    ocupados = {e.casefold() for e in existentes if e != actual}
    if nombre.casefold() in ocupados:
        return f"Ya hay algo que se llama «{nombre}» en esta carpeta."
    return None


def validar_pegado(op: Operacion, nombres_en_destino: Iterable[str]) -> str | None:
    """Dice por qué lo cortado no se puede pegar en el destino.

    Args:
        op: La operación `MOVER`: `carpeta` es el origen y `destino` donde se pega.
        nombres_en_destino: Los nombres que hay ahora en la carpeta de destino.

    Returns:
        El motivo del rechazo (la misma carpeta, una carpeta dentro de sí misma o nombres
        ya ocupados, comparados con `casefold()`), o `None` si cabe.
    """
    origen = remote_picker.normalizar(op.carpeta)
    destino = remote_picker.normalizar(op.destino or "")
    if origen == destino:
        return "Ya están en esta carpeta."
    for e in op.elementos:
        propia = _unir(origen, e.nombre)
        if e.es_carpeta and (destino == propia or destino.startswith(propia + "/")):
            return "No se puede mover una carpeta dentro de sí misma."
    ocupados = {n.casefold() for n in nombres_en_destino}
    chocan = [e.nombre for e in op.elementos if e.nombre.casefold() in ocupados]
    if len(chocan) == 1:
        return f"Ya hay «{chocan[0]}» en {destino}: renómbralo antes."
    if chocan:
        return f"Ya hay «{chocan[0]}» y {len(chocan) - 1} más en {destino}: renómbralos antes."
    return None


def rutas_tocadas(op: Operacion) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Devuelve las rutas del servidor que la operación hace salir y las que hace llegar.

    Args:
        op: La operación.

    Returns:
        `(salen, llegan)`. Borrar: cada elemento sale. Renombrar: sale el nombre viejo y
        llega el nuevo. Mover: cada elemento sale de su carpeta y llega a la de destino.
        Nueva carpeta: solo llega la carpeta nueva.
    """
    if op.tipo == BORRAR:
        return tuple(_unir(op.carpeta, e.nombre) for e in op.elementos), ()
    if op.tipo == RENOMBRAR:
        return (tuple(_unir(op.carpeta, e.nombre) for e in op.elementos),
                (_unir(op.carpeta, op.nombre or ""),))
    if op.tipo == MOVER:
        return (tuple(_unir(op.carpeta, e.nombre) for e in op.elementos),
                tuple(_unir(op.destino or "", e.nombre) for e in op.elementos))
    return (), (_unir(op.carpeta, op.nombre or ""),)


_BLOQUEO_RAIZ = "Ahí está la carpeta de la pareja «{p}»: tocarla desde aquí rompería la pareja."
_BLOQUEO_CATALOGO = ("Ahí está el catálogo de las parejas: tocarlo desde aquí dejaría a los "
                     "dispositivos sin él.")
_BLOQUEO_LLEGADA = ("«{p}» deja el servidor igual que el dispositivo: lo que pongas aquí lo "
                    "borraría su próxima pasada.")


def _toca_el_catalogo(ruta: str, carpeta: str) -> bool:
    """Dice si `ruta` es la carpeta del catálogo, la contiene o está dentro de ella.

    Args:
        ruta: Ruta normalizada del servidor.
        carpeta: La carpeta del catálogo (`model.carpeta_del_catalogo`). Es la raíz del
            remote tanto si viene `""` (`remote.toml`) como `"/"` (`/remote.toml`); ahí solo
            cuentan los propios ficheros del catálogo.
    """
    from common import catalog

    catalogo = remote_picker.normalizar(carpeta)
    if catalogo == "/":
        return ruta in {"/" + n for n in catalog.NOMBRES}
    return (ruta == catalogo or catalogo.startswith(ruta.rstrip("/") + "/")
            or ruta.startswith(catalogo + "/"))


def bloqueo(op: Operacion, config: Config, catalogo: tuple[str, str] | None) -> str | None:
    """Devuelve el texto que impide la operación, o `None` si nada la impide.

    Las reglas van en este orden y habla la primera que salta: 1) una ruta tocada, de las
    que salen o de las que llegan, es la raíz de una pareja o la contiene; 2) es la
    carpeta del catálogo, la contiene o está dentro; 3) llega estrictamente dentro de una
    pareja `up-mirror` (la más honda), cuya próxima pasada la borraría. Salir de una
    `up-mirror` no bloquea: es un aviso (`avisos`).

    Args:
        op: La operación.
        config: Configuración con las parejas (la del llavero incluida).
        catalogo: `(remote, carpeta)` de `model.carpeta_del_catalogo()`, o `None` si no se
            conoce; el catálogo solo se protege en su propio remote.

    Returns:
        El texto del bloqueo, o `None`.
    """
    salen, llegan = rutas_tocadas(op)
    tocadas = salen + llegan
    for ruta in tocadas:
        nombres = transferencia.parejas_bajo(config, op.remote, ruta)
        if nombres:
            primera = next(p.name for p in config.pairs if p.name in nombres)
            return _BLOQUEO_RAIZ.format(p=primera)
    if catalogo is not None and op.remote == catalogo[0]:
        if any(_toca_el_catalogo(remote_picker.normalizar(r), catalogo[1]) for r in tocadas):
            return _BLOQUEO_CATALOGO
    for ruta in llegan:
        # Si la ruta fuera la propia raíz de la pareja ya habría hablado la primera regla.
        nombres = transferencia.parejas_que_contienen(config, op.remote, ruta)
        for p in config.pairs:
            if p.name in nombres and p.mode.name == "up-mirror":
                return _BLOQUEO_LLEGADA.format(p=p.name)
    return None


_AVISO_SALE = {
    "bisync": "La próxima pasada de «{p}» lo quitará también del dispositivo.",
    "down-mirror": "La próxima pasada de «{p}» lo quitará también del dispositivo.",
    "down": "El dispositivo conserva su copia: «{p}» no borra.",
    "up": "La próxima pasada de «{p}» lo volverá a subir desde el dispositivo.",
    "up-mirror": "La próxima pasada de «{p}» lo volverá a subir desde el dispositivo.",
}
"""Qué pasa con lo que sale de una pareja, según su modo."""

_AVISO_LLEGA = {
    "bisync": "La próxima pasada de «{p}» lo copiará al dispositivo.",
    "down-mirror": "La próxima pasada de «{p}» lo copiará al dispositivo.",
    "down": "La próxima pasada de «{p}» lo copiará al dispositivo.",
    "up": "El dispositivo no lo recibirá: «{p}» solo sube.",
}
"""Qué pasa con lo que llega a una pareja, según su modo; `up-mirror` no tiene (se bloquea)."""


def avisos(op: Operacion, config: Config) -> tuple[str, ...]:
    """Devuelve lo que dirá la próxima pasada de cada pareja que la operación toca.

    Una línea por pareja y lado: primero las que salen, luego las que llegan. Cuenta las
    parejas más hondas que contienen cada ruta (todas las que comparten esa carpeta), en el
    orden de la configuración y sin repetir. No mira `bloqueo`.

    Args:
        op: La operación.
        config: Configuración con las parejas (la del llavero incluida).

    Returns:
        Los textos; vacío si ninguna ruta está dentro de una pareja.
    """
    salen, llegan = rutas_tocadas(op)
    textos: list[str] = []
    for rutas, tabla in ((salen, _AVISO_SALE), (llegan, _AVISO_LLEGA)):
        nombres: set[str] = set()
        for ruta in rutas:
            nombres |= transferencia.parejas_que_contienen(config, op.remote, ruta)
        for p in config.pairs:
            plantilla = tabla.get(p.mode.name)
            if p.name in nombres and plantilla is not None:
                texto = plantilla.format(p=p.name)
                if texto not in textos:
                    textos.append(texto)
    return tuple(textos)


def _remoto(carpeta: str, nombre: str = "") -> str:
    """Devuelve la ruta de `nombre` en `carpeta` sin la barra del principio: así se pasa un `remote` a rclone.

    Solo la carpeta se normaliza; el nombre se añade tal cual (`foo `, ` x` o `a\\b` son
    nombres válidos y `normalizar` los cambiaría por los de otro elemento). Sin nombre,
    es la carpeta (`""` en la raíz).
    """
    base = remote_picker.normalizar(carpeta).lstrip("/")
    if not nombre:
        return base
    return f"{base}/{nombre}" if base else nombre


def _fs(remote: str, ruta: str = "") -> str:
    """Devuelve el `fs` de rclone para una ruta ya sin barra inicial, siempre por la raíz absoluta."""
    return f"{remote}:/{ruta}"


def ordenes_de(op: Operacion) -> list[dict]:
    """Devuelve las órdenes de rclone de la operación, una por elemento y en su orden.

    Los nombres van tal cual, sin escapar: estas órdenes no llevan filtros. Todas salen
    por `rcd.lanzar_orden()`, que solo admite `rcd.ORDENES_PERMITIDAS`.

    Args:
        op: La operación. `NUEVA` produce una sola orden.

    Returns:
        Borrar: `operations/purge` (carpeta) u `operations/deletefile` (archivo).
        Renombrar y mover: `sync/move` (carpeta) u `operations/movefile` (archivo).
        Nueva carpeta: `operations/mkdir`.
    """
    if op.tipo == NUEVA:
        return [{"_path": "operations/mkdir", "fs": _fs(op.remote),
                 "remote": _remoto(op.carpeta, op.nombre or "")}]
    ordenes: list[dict] = []
    for e in op.elementos:
        origen = _remoto(op.carpeta, e.nombre)
        if op.tipo == BORRAR:
            camino = "operations/purge" if e.es_carpeta else "operations/deletefile"
            ordenes.append({"_path": camino, "fs": _fs(op.remote), "remote": origen})
            continue
        if op.tipo == RENOMBRAR:
            llegada = _remoto(op.carpeta, op.nombre or "")
        else:
            llegada = _remoto(op.destino or "", e.nombre)
        if e.es_carpeta:
            ordenes.append({"_path": "sync/move", "srcFs": _fs(op.remote, origen),
                            "dstFs": _fs(op.remote, llegada), "deleteEmptySrcDirs": True})
        else:
            ordenes.append({"_path": "operations/movefile", "srcFs": _fs(op.remote),
                            "srcRemote": origen, "dstFs": _fs(op.remote),
                            "dstRemote": llegada})
    return ordenes


@dataclass(frozen=True)
class Plan:
    """Lo que enseña `confirmar_plan()` antes de lanzar la operación.

    Args:
        consequences: Una línea por cosa que va a pasar.
        warnings: Lo que dirá la próxima pasada de cada pareja alcanzada (`avisos`).
    """

    consequences: tuple[str, ...]
    warnings: tuple[str, ...]


def _consecuencia_de_borrar(e: Elemento, conteo: tuple[int, int]) -> str:
    """Dice qué se pierde al borrar `e`, con lo que hay dentro si es una carpeta."""
    archivos, tamano = conteo
    if not e.es_carpeta:
        return f"Se borrará para siempre «{e.nombre}» ({servidor.tamano_legible(tamano)})."
    if archivos <= 0:
        return f"Se borrará para siempre «{e.nombre}», vacía."
    cuantos = "1 archivo" if archivos == 1 else f"{archivos} archivos"
    return f"Se borrará para siempre «{e.nombre}», con {cuantos} ({servidor.tamano_legible(tamano)})."


def plan_de(op: Operacion, conteos: dict[str, tuple[int, int]],
            avisos: tuple[str, ...]) -> Plan:
    """Devuelve lo que hay que enseñar para confirmar la operación.

    Args:
        op: La operación.
        conteos: Para `BORRAR`, de cada elemento por su nombre, `(archivos, bytes)`: una
            carpeta, lo que dice `rcd.tamano`; un archivo, `(1, su tamaño)`. Las demás
            acciones no lo usan.
        avisos: Lo que devuelve `avisos(op, config)`; pasa tal cual como `warnings`.

    Returns:
        Las consecuencias (al borrar, una línea por elemento y en su orden) y los avisos.
    """
    if op.tipo == BORRAR:
        lineas = tuple(_consecuencia_de_borrar(e, conteos.get(e.nombre, (0, 0)))
                       for e in op.elementos)
    elif op.tipo == RENOMBRAR:
        lineas = (f"«{op.elementos[0].nombre}» pasará a llamarse «{op.nombre}».",)
    elif op.tipo == MOVER:
        origen = remote_picker.normalizar(op.carpeta)
        destino = remote_picker.normalizar(op.destino or "")
        if len(op.elementos) == 1:
            lineas = (f"Se moverá «{op.elementos[0].nombre}» de {origen} a {destino}.",)
        else:
            lineas = (f"Se moverán {len(op.elementos)} elementos de {origen} a {destino}.",)
    else:
        lineas = (f"Se creará la carpeta «{op.nombre}» en {remote_picker.normalizar(op.carpeta)}.",)
    return Plan(lineas, tuple(avisos))


def _nombre_de(op: Operacion, indice: int) -> str:
    """Devuelve el nombre del elemento `indice`; en `NUEVA`, que no tiene elementos, el de la carpeta."""
    return op.elementos[indice].nombre if op.elementos else (op.nombre or "")


def titulo_de(op: Operacion) -> str:
    """Devuelve el título del panel de progreso de la operación."""
    if op.tipo == BORRAR:
        return f"Borrando en {remote_picker.normalizar(op.carpeta)}"
    if op.tipo == MOVER:
        return f"Moviendo a {remote_picker.normalizar(op.destino or '')}"
    if op.tipo == RENOMBRAR:
        return f"Renombrando «{_nombre_de(op, 0)}» a «{op.nombre}»"
    return f"Creando la carpeta «{op.nombre}»"


def progreso_de(op: Operacion, stats: dict, hechos: int, total: int) -> transferencia.Progreso:
    """Convierte la cuenta de elementos y el `core/stats` del lote en los textos del panel.

    Nunca lanza: `stats` puede estar vacío o traer campos nulos.

    Args:
        op: La operación en marcha.
        stats: La respuesta de `core/stats`; puede estar vacía.
        hechos: Elementos que ya acabaron.
        total: Elementos del lote (0 si aún no se sabe).

    Returns:
        El panel: sin archivo ni ritmo (rclone no los da en un borrado o un movimiento) y
        con la fracción `hechos / total`, o `None` (barra indeterminada) si `total` es 0.
    """
    cuenta = f"{hechos} de {total} elementos"
    borrados = stats.get("deletes")
    if isinstance(borrados, bool) or not isinstance(borrados, (int, float)):
        borrados = 0
    if op.tipo == BORRAR and borrados > 0:
        cuenta += f" · {int(borrados)} archivos borrados"
    fraccion = min(1.0, max(0.0, hechos / total)) if total > 0 else None
    return transferencia.Progreso(titulo_de(op), "", cuenta, fraccion, "")


def cancelando_de(op: Operacion, indice: int) -> str:
    """Devuelve la línea del panel mientras se cancela: el elemento `indice` es el que no se corta."""
    return f"Cancelando… se para al acabar «{_nombre_de(op, indice)}»."


_VERBO = {BORRAR: "borrar", MOVER: "mover", RENOMBRAR: "renombrar", NUEVA: "crear"}
"""El infinitivo de cada acción, para «No se pudo …» y «No tienes permiso para …»."""
_PARTICIPIO = {BORRAR: "borrados", MOVER: "movidos"}
"""El plural de lo hecho, para los resultados de varios elementos."""


def _frase_del_fallo(op: Operacion, estado: dict) -> str:
    """Dice por qué falló una orden: ya no estaba, falta permiso o lo que cuenta rclone."""
    verbo = _VERBO[op.tipo]
    error = rcd.ErrorRc(str(estado.get("error") or f"no se ha podido {verbo}"), 0)
    if servidor.no_existe(error):
        return "ya no estaba"
    if servidor.es_de_permiso(error):
        return f"No tienes permiso para {verbo} en {remote_picker.normalizar(op.carpeta)}."
    return servidor.frase_error(error)


def resultado_de(op: Operacion, estados: list[dict], stats: dict,
                 cancelado: bool) -> transferencia.Resultado:
    """Convierte el `job/status` de cada orden lanzada en el resultado de la operación.

    El resultado cuenta elementos, no archivos, y nunca ofrece `Reintentar`: el estado del
    servidor ha cambiado y se relee para volver a elegir.

    Args:
        op: La operación.
        estados: El `job/status` final de cada orden lanzada, en orden (las que no se
            lanzaron por cancelar no están). Una orden fue bien si su `success` es cierto.
        stats: El último `core/stats` del lote (no se usa: se cuenta por órdenes).
        cancelado: Si el usuario canceló. En `BORRAR` y `MOVER` manda sobre lo demás; un
            renombrado o una carpeta nueva son una sola orden y valen por cómo acabó.

    Returns:
        El texto, su tono (`"ok"` solo si todo fue bien) y `reintentar=False`.
    """
    total = len(op.elementos) if op.elementos else 1
    bien = [bool(e.get("success")) for e in estados]
    hechos = sum(bien)
    destino = remote_picker.normalizar(op.destino or "")
    if cancelado and op.tipo in _PARTICIPIO:
        texto = f"Cancelado: {_PARTICIPIO[op.tipo]} {hechos} de {total}"
        if estados and not bien[-1]:
            texto += f" · «{_nombre_de(op, len(estados) - 1)}» puede haber quedado a medias"
        return transferencia.Resultado(texto, "aviso", False)
    if hechos == total and len(estados) == total:
        if op.tipo == BORRAR:
            texto = f"Borrado «{op.elementos[0].nombre}»." if total == 1 else f"Borrados {total}."
        elif op.tipo == MOVER:
            texto = (f"Movido «{op.elementos[0].nombre}» a {destino}." if total == 1
                     else f"Movidos {total} a {destino}.")
        elif op.tipo == RENOMBRAR:
            texto = f"Renombrado a «{op.nombre}»."
        else:
            texto = f"Creada «{op.nombre}»."
        return transferencia.Resultado(texto, "ok", False)
    # La primera orden que falló; si ninguna lo hizo es que quedaron sin lanzar.
    falla = bien.index(False) if False in bien else len(estados)
    frase = (_frase_del_fallo(op, estados[falla]) if falla < len(estados)
             else "no se llegó a lanzar")
    nombre = _nombre_de(op, min(falla, total - 1))
    if total > 1 and op.tipo in _PARTICIPIO:
        texto = f"{_PARTICIPIO[op.tipo].capitalize()} {hechos} de {total}: «{nombre}» no se pudo: {frase}"
    else:
        texto = f"No se pudo {_VERBO[op.tipo]} «{nombre}»: {frase}"
    return transferencia.Resultado(texto, "aviso", False)
