"""El nombre que se enseña de una unidad cuando nadie le ha puesto uno.

Es el ÚNICO sitio que lo decide: la bandeja, los avisos y el diario del agente
(`agente.nombre_de()`) lo piden aquí. Antes salía del equipo donde se había
aprovisionado la unidad (el instalador guarda su nombre de red en
`state/fleet.json`), y dos unidades aprovisionadas desde el mismo ordenador se
llamaban igual en todas partes.

La regla, sin nombre propio:
1. La etiqueta del volumen, si tiene una que distinga (`etiqueta_de()`).
2. Si no, «prdrive · <4 primeros del id>».
3. Solo si aun así dos se llaman igual (`distinguir()`), el nombre del equipo
   que la aprovisionó detrás, entre paréntesis; y el id si ni así.

Lo que alguien puso en «Nombre e icono» (`drive-name-icon.md`) no se toca. No se
guarda marca de que un nombre sea el de un equipo: se reconoce porque coincide
con uno de los equipos desde los que la unidad ha publicado su nota
(`state/fleet.json`, `publicado.equipos`), que es lo que ya hay en las unidades
de siempre. Salvo si es también el `label=` del `autorun.inf` de su raíz: ese
solo lo escribe «Nombre e icono», así que quien la llamó como su ordenador lo
hizo a propósito. Nada de esto cambia lo que se publica en el remoto.

Todo es puro salvo `etiqueta_de()`, que lee del sistema y es un punto de
indirección que los tests sustituyen. El `autorun.inf` lo lee quien llama
(`agente.nombre_de()`).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from . import APP_NAME

IS_WIN = os.name == "nt"

POR_ETIQUETA = Path("/dev/disk/by-label")
"""Los dispositivos de bloque por su etiqueta (Linux); los tests apuntan a uno de mentira."""

LARGO_ETIQUETA = 261  # MAX_PATH + 1, lo que pide `GetVolumeInformationW`


@dataclass(frozen=True)
class Nombre:
    """El nombre que corresponde a una unidad y de dónde sale.

    Args:
        texto: Lo que se enseña, sin distinguirlo todavía de otras unidades.
        propio: Si lo puso alguien. Un nombre propio no se cambia nunca.
        equipo: El equipo que aprovisionó la unidad, cuando se sabe y el nombre
            no es propio; con él se distingue de otra que se llame igual.
    """
    texto: str
    propio: bool
    equipo: str = ""


def etiqueta_util(etiqueta: str) -> str:
    """Devuelve la etiqueta de un volumen si distingue algo, y si no una cadena vacía.

    No distingue la que está en blanco ni la que prdrive mismo escribe al dar
    formato o montar (`PRDRIVE`): la llevan todas las unidades.
    """
    etiqueta = etiqueta.strip()
    return "" if etiqueta.casefold() == APP_NAME.casefold() else etiqueta


def por_defecto(uid: str, etiqueta: str = "") -> str:
    """Devuelve el nombre de una unidad sin nombre propio.

    Args:
        uid: El id de su fichero de control.
        etiqueta: La del volumen (`etiqueta_de()`), si se conoce.

    Returns:
        La etiqueta si distingue algo (`etiqueta_util()`) y, si no, «prdrive ·»
        y los 4 primeros caracteres del id.
    """
    return etiqueta_util(etiqueta) or f"{APP_NAME} · {uid[:4]}"


def es_del_equipo(guardado: str, equipos: Iterable[str]) -> bool:
    """Indica si un nombre guardado es el de un equipo y no uno que alguien puso.

    Args:
        guardado: El `nombre` de `state/fleet.json`.
        equipos: Los equipos desde los que la unidad ha publicado su nota
            (`fleet.Dispositivo.equipos`).

    Returns:
        Si coincide con uno, sin distinguir mayúsculas. Un nombre en blanco no
        es de ningún equipo.
    """
    guardado = guardado.strip().casefold()
    return bool(guardado) and any(guardado == e.strip().casefold() for e in equipos)


def elegir(uid: str, guardado: str = "", etiqueta: str = "",
           equipos: Iterable[str] = (), rotulo: str = "") -> Nombre:
    """Decide el nombre de una unidad a partir de lo que se sabe de ella.

    Args:
        uid: El id de su fichero de control.
        guardado: Su nombre en `state/fleet.json`, vacío si no tiene.
        etiqueta: La etiqueta de su volumen, si se conoce.
        equipos: Los equipos desde los que ha publicado (`es_del_equipo()`).
        rotulo: El `label=` del `autorun.inf` de su raíz, si tiene. Solo lo
            escribe «Nombre e icono», con el mismo nombre que deja en
            `state/fleet.json`: si coincide con `guardado`, ese nombre lo puso
            alguien aunque se llame como un equipo.

    Returns:
        Un nombre propio si `guardado` lo es, y si no el de `por_defecto()` con
        el equipo que había guardado como dato para `distinguir()`.
    """
    guardado = guardado.strip()
    puesto = guardado.casefold() == rotulo.strip().casefold()
    if guardado and (puesto or not es_del_equipo(guardado, equipos)):
        return Nombre(guardado, True)
    return Nombre(por_defecto(uid, etiqueta), False, guardado)


def distinguir(nombre: Nombre, uid: str, otros: Iterable[str]) -> str:
    """Devuelve el nombre que se enseña, sin que se confunda con el de otra unidad.

    Args:
        nombre: Lo que `elegir()` decidió de esta unidad.
        uid: Su id; solo se usa si hace falta como último recurso.
        otros: Los nombres que ya tienen las otras unidades.

    Returns:
        El nombre tal cual si nadie se llama igual (sin distinguir mayúsculas) o
        si es propio. Si no, con el equipo que la aprovisionó detrás y, si
        tampoco así se distingue, con el principio del id.
    """
    if nombre.propio:
        return nombre.texto
    usados = {o.casefold() for o in otros}
    if nombre.texto.casefold() not in usados:
        return nombre.texto
    con_equipo = f"{nombre.texto} ({nombre.equipo})" if nombre.equipo else nombre.texto
    if con_equipo.casefold() not in usados:
        return con_equipo
    return f"{con_equipo} · {uid[:8]}"


# --- La etiqueta del volumen ----------------------------------------------

def _origen(raiz: Path) -> str | None:
    """Devuelve el dispositivo de bloque (`/dev/sdb1`) montado en `raiz`, o `None`."""
    from . import expulsar
    return expulsar._origen(raiz)


def _desescapar(nombre: str) -> str:
    r"""Deshace lo que udev escapa en los nombres de `by-label` (`\x20` es un espacio)."""
    crudo = nombre.encode("utf-8", "surrogateescape")
    crudo = re.sub(rb"\\x([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]), crudo)
    return crudo.decode("utf-8", "replace")


def _etiqueta_linux(raiz: Path) -> str:
    """Devuelve la etiqueta del dispositivo montado en `raiz`, vacía si no tiene.

    Mira en `/dev/disk/by-label` qué enlace apunta al dispositivo de la raíz: la
    carpeta de montaje no sirve, que a veces es la etiqueta y a veces
    `veracrypt1`.
    """
    origen = _origen(raiz)
    if origen is None or not POR_ETIQUETA.is_dir():
        return ""
    buscado = Path(os.path.realpath(origen)).name
    for entrada in POR_ETIQUETA.iterdir():
        if Path(os.readlink(entrada)).name == buscado:
            return _desescapar(entrada.name)
    return ""


def _etiqueta_windows(raiz: Path) -> str:
    """Devuelve la etiqueta del volumen que está en `raiz` (`GetVolumeInformationW`).

    Se le da la raíz entera, con su barra final, y no solo la letra: una raíz
    que es una carpeta donde se monta un volumen es el de esa carpeta, y su letra
    sería la de otro disco. Una carpeta que no es raíz de volumen no contesta,
    que es lo que se quiere.

    Con el modo de error del hilo en `SEM_FAILCRITICALERRORS`, para que una
    unidad sin medio no abra el cuadro de «Insertar un disco».
    """
    import ctypes
    from ctypes import byref, create_unicode_buffer, wintypes
    k32 = ctypes.windll.kernel32
    anterior = wintypes.DWORD()
    k32.SetThreadErrorMode(0x0001, byref(anterior))
    try:
        etiqueta = create_unicode_buffer(LARGO_ETIQUETA)
        raiz_windows = str(raiz) if str(raiz).endswith("\\") else f"{raiz}\\"
        ok = k32.GetVolumeInformationW(raiz_windows, etiqueta, LARGO_ETIQUETA,
                                       None, None, None, None, 0)
        return etiqueta.value if ok else ""
    finally:
        k32.SetThreadErrorMode(anterior, byref(wintypes.DWORD()))


def etiqueta_de(raiz: Path) -> str:
    """Devuelve la etiqueta del volumen montado en `raiz`, vacía si no se sabe.

    Es un punto de indirección: los tests la sustituyen. Pregunta al sistema, así
    que se llama al conectar la unidad y no en cada vuelta. No lanza nunca: una
    unidad que no deja leerse es una unidad sin etiqueta.
    """
    try:
        texto = _etiqueta_windows(raiz) if IS_WIN else _etiqueta_linux(raiz)
    except Exception:                                    # noqa: BLE001
        return ""
    return texto.strip()
