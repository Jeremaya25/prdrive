#!/usr/bin/env python3
"""La foto barata de una carpeta, para saber que algo ha cambiado en ella.

Es lo único que toca el disco en la detección de cambios de `watch = true`:
`planificador.py` decide con las fotos y no sabe de dónde salen. Se recorre la
carpeta con `os.scandir`, sin abrir un solo fichero, y se compara con la foto
anterior; no hay eventos del sistema (no los dan una exFAT, un contenedor de
VeraCrypt ni una carpeta de red) ni dependencias.

La firma suma un hash de cada entrada —ruta relativa, tamaño y mtime en
nanosegundos— y no usa el máximo de los mtime ni la suma de los tamaños:
renombrar un fichero, o cambiar uno por otro del mismo tamaño, deja quietos los
dos agregados, y renombrar es justo lo que bisync propaga. Las carpetas entran
por su nombre y nada más, porque el mtime de una carpeta cambia con cosas que
no son contenido (rclone dejando un temporal). Sumar hashes no depende del
orden en que `scandir` entrega las entradas, así que no hace falta ordenarlas
ni guardarlas.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
from pathlib import Path

from . import model
from .planificador import Huella

MASCARA = (1 << 64) - 1
"""La firma es una suma módulo 2**64."""

IGNORAR = (model.VERSIONS_DIR,)
"""Entradas de la raíz de la pareja que no se miran.

`.prversions/` la escribe rclone al guardar versiones (`versions = true`) y bisync
la excluye de lo que sincroniza: un cambio ahí no es un cambio de la pareja.
Cada entrada es un patrón de `fnmatch` y se compara en minúsculas con el nombre
de la carpeta o del fichero (`model.RUIDO_DEL_SISTEMA` es una lista así).
"""


HONDO = "**/"
"""Lo que lleva delante un patrón que vale a cualquier profundidad, y solo para ficheros.

Los demás patrones de `ignorar` son de la raíz de la pareja. Uno hondo no casa
nunca como patrón de la raíz (un nombre no lleva `/`), así que quien no los
aparte (`partir()`) simplemente no los aplica.
"""
RUIDO_DE_EDITOR = tuple(HONDO + p for p in (
    "~$*",                  # el fichero de bloqueo de Office, mientras el documento está abierto
    "~*.tmp",               # sus temporales de guardado (`~WRD0001.tmp`, `~WRL0002.tmp`)
    ".~lock.*#",            # el de LibreOffice
    ".*.sw?",               # el intercambio de vim
    ".goutputstream-*",     # el temporal de guardado de GLib (gedit, Nautilus)
    "thumbs.db", "desktop.ini", ".ds_store",    # lo que el sistema deja en las carpetas
))
"""Ficheros cuyo cambio no adelanta la pasada de una pareja con `watch`, estén donde estén.

No son de nadie: los deja el programa con el que se trabaja y se van solos. Sin
esto, abrir y cerrar un documento de Word costaba dos pasadas (el `~$` que
nace vive más que la calma, y luego muere). No se dejan de sincronizar: van con
la pasada siguiente, la del intervalo o la que adelante un cambio de verdad,
que sí se oye (guardar acaba renombrando sobre el documento, y ese nombre
cuenta). El precio: un fichero propio que se llame así espera al intervalo.
"""


def se_ignora(nombre: str, patrones: tuple[str, ...]) -> bool:
    """Indica si una entrada de la raíz casa con alguno de los patrones (en minúsculas)."""
    minusculas = nombre.lower()
    return any(fnmatch.fnmatchcase(minusculas, p) for p in patrones)


def partir(patrones: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Aparta los patrones hondos (`HONDO`) de los de la raíz.

    Returns:
        `(los de la raíz, los hondos sin su prefijo)`.
    """
    return (tuple(p for p in patrones if not p.startswith(HONDO)),
            tuple(p[len(HONDO):] for p in patrones if p.startswith(HONDO)))


def es_ruido(nombre: str, hondos: tuple[str, ...]) -> bool:
    """Indica si el nombre de un fichero (sin su carpeta) casa con algún patrón hondo."""
    return bool(hondos) and se_ignora(nombre, hondos)


def ruta_larga(ruta: str) -> str:
    """Devuelve la ruta con el prefijo que deja a Windows pasar de 260 caracteres.

    Sin él (`\\\\?\\`, o `\\\\?\\UNC\\` para una carpeta de red) y con las rutas largas
    apagadas en el sistema, `scandir` no entra en lo que queda a más de 260
    caracteres y la foto no ve lo que cambia ahí (medido el 11/10/2026: lo
    saltaba en silencio; `sync.py` y los avisos del sistema sí lo ven). Fuera
    de Windows, o si ya lo lleva, la devuelve igual.
    """
    if os.name != "nt" or ruta.startswith("\\\\?\\"):
        return ruta
    absoluta = os.path.abspath(ruta)
    if absoluta.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absoluta[2:]
    return "\\\\?\\" + absoluta


LARGA = 240
"""Caracteres de la ruta de una carpeta a partir de los que se abre con `ruta_larga()`.

Windows no lista una carpeta cuya ruta pasa de 248 (260 menos lo que ocupa un
nombre 8.3); las más cortas se abren como siempre, sin prefijo.
"""


def _abrible(carpeta: str) -> str:
    """Devuelve la ruta con la que abrir una carpeta: con prefijo solo si es larga."""
    return ruta_larga(carpeta) if os.name == "nt" and len(carpeta) >= LARGA else carpeta


def _es_union(entrada: os.DirEntry) -> bool:
    """Indica si una entrada es una unión de Windows (`mklink /J`, un punto de montaje).

    Para `scandir` es una carpeta y no un enlace, pero rclone la trata como un
    enlace: sin `--copy-links` no entra («Can't follow symlink without
    -L/--copy-links», visto con rclone 1.75.1). Entrar en ella sería ver
    cambios que la pasada no va a subir. `DirEntry.is_junction()` es de
    Python 3.12; sin él, ninguna lo es.
    """
    es = getattr(entrada, "is_junction", None)
    return bool(es and es())


def _hash(relativa: str, tamano: int, mtime_ns: int) -> int:
    """Devuelve el hash de 64 bits de una entrada."""
    datos = f"{relativa}\0{tamano}\0{mtime_ns}".encode("utf-8", "surrogatepass")
    return int.from_bytes(hashlib.blake2b(datos, digest_size=8).digest(), "little")


def de_carpeta(ruta: Path | str, tope: int | None = None,
               ignorar: tuple[str, ...] = IGNORAR) -> Huella | None:
    """Toma la foto de una carpeta.

    No sigue enlaces simbólicos: un enlace cuenta como una entrada más (su
    propio tamaño y mtime) y, aunque apunte a una carpeta, no se entra en él.
    Tampoco en una unión de Windows (`_es_union()`), que cuenta por su nombre
    como una carpeta. Así el recorrido no sale de la carpeta por mucho que
    haya enlaces dentro, ni da vueltas con uno que apunte hacia arriba.

    Un fichero o una carpeta que desaparece entre listarla y mirarla (lo normal
    mientras alguien trabaja) se salta: ya saldrá en la foto siguiente. Una
    subcarpeta que no se deja abrir (permiso denegado: el
    `System Volume Information` de Windows) también: cuenta por su nombre y no
    se mira dentro. Un error de otra clase (la unidad retirada a medias, un
    `EIO`) invalida la foto entera, igual que si es la propia carpeta la que no
    se deja abrir o ya no está al terminar.

    Args:
        ruta: La carpeta.
        tope: Cuántas entradas se cuentan como mucho. Pasado el tope se corta
            en el acto y se devuelve la cuenta hasta ahí, sin firma y con
            `cortada`: quien llama solo necesita saber que no cabe.
        ignorar: Patrones (`fnmatch`, en minúsculas) de las entradas de la raíz
            que no se miran, sean carpetas o ficheros. Los que llevan `HONDO`
            delante son de ficheros a cualquier profundidad
            (`RUIDO_DE_EDITOR`).

    Returns:
        La foto, o `None` si no se pudo tomar: ni un cambio ni una foto vacía.
    """
    raiz = os.fspath(ruta)
    patrones, hondos = partir(tuple(p.lower() for p in ignorar))
    pendientes: list[tuple[str, str]] = [(raiz, "")]
    entradas = 0
    firma = 0
    try:
        while pendientes:
            carpeta, prefijo = pendientes.pop()
            try:
                with os.scandir(_abrible(carpeta)) as it:
                    for e in it:
                        if not prefijo and se_ignora(e.name, patrones):
                            continue
                        relativa = prefijo + e.name
                        try:
                            if e.is_dir(follow_symlinks=False):
                                firma += _hash(relativa + "/", -1, 0)
                                if not _es_union(e):
                                    pendientes.append((e.path, relativa + "/"))
                            elif es_ruido(e.name, hondos):
                                continue
                            else:
                                st = e.stat(follow_symlinks=False)
                                firma += _hash(relativa, st.st_size, st.st_mtime_ns)
                        except (FileNotFoundError, PermissionError):
                            continue
                        entradas += 1
                        if tope is not None and entradas > tope:
                            return Huella(entradas, 0, cortada=True)
            except (FileNotFoundError, NotADirectoryError, PermissionError):
                if carpeta == raiz:
                    return None
        os.stat(_abrible(raiz))
    except OSError:
        return None
    return Huella(entradas, firma & MASCARA)
