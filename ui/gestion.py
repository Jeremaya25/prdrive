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

from common import catalog
from common.model import Config

from . import remote_picker, transferencia
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
        carpeta: La carpeta del catálogo (`model.carpeta_del_catalogo`): `""` si es la raíz
            del remote, donde solo cuentan los propios ficheros del catálogo.
    """
    if not carpeta:
        return ruta in {"/" + n for n in catalog.NOMBRES}
    catalogo = remote_picker.normalizar(carpeta)
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
