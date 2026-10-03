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

import hashlib
import os
from pathlib import Path

from . import model
from .planificador import Huella

MASCARA = (1 << 64) - 1
"""La firma es una suma módulo 2**64."""

IGNORAR = (model.VERSIONS_DIR,)
"""Carpetas de la raíz de la pareja que no se miran.

`.prversions/` la escribe rclone al guardar versiones (`versions = true`) y bisync
la excluye de lo que sincroniza: un cambio ahí no es un cambio de la pareja.
"""


def _hash(relativa: str, tamano: int, mtime_ns: int) -> int:
    """Devuelve el hash de 64 bits de una entrada."""
    datos = f"{relativa}\0{tamano}\0{mtime_ns}".encode("utf-8", "surrogatepass")
    return int.from_bytes(hashlib.blake2b(datos, digest_size=8).digest(), "little")


def de_carpeta(ruta: Path | str, tope: int | None = None,
               ignorar: tuple[str, ...] = IGNORAR) -> Huella | None:
    """Toma la foto de una carpeta.

    No sigue enlaces simbólicos: un enlace cuenta como una entrada más (su
    propio tamaño y mtime) y, aunque apunte a una carpeta, no se entra en él.
    Así el recorrido no sale de la carpeta por mucho que haya enlaces dentro.

    Un fichero o una carpeta que desaparece entre listarla y mirarla (lo normal
    mientras alguien trabaja) se salta: ya saldrá en la foto siguiente. Un
    error de otra clase (la unidad retirada a medias, un `EIO`) invalida la
    foto entera, igual que si la propia carpeta ya no está al terminar.

    Args:
        ruta: La carpeta.
        tope: Cuántas entradas se cuentan como mucho. Pasado el tope se corta
            en el acto y se devuelve la cuenta hasta ahí, sin firma: quien
            llama solo necesita saber que no cabe.
        ignorar: Nombres de carpetas de la raíz que no se recorren.

    Returns:
        La foto, o `None` si no se pudo tomar: ni un cambio ni una foto vacía.
    """
    raiz = os.fspath(ruta)
    pendientes: list[tuple[str, str]] = [(raiz, "")]
    entradas = 0
    firma = 0
    try:
        while pendientes:
            carpeta, prefijo = pendientes.pop()
            try:
                with os.scandir(carpeta) as it:
                    for e in it:
                        relativa = prefijo + e.name
                        try:
                            if e.is_dir(follow_symlinks=False):
                                if not prefijo and e.name in ignorar:
                                    continue
                                firma += _hash(relativa + "/", -1, 0)
                                pendientes.append((e.path, relativa + "/"))
                            else:
                                st = e.stat(follow_symlinks=False)
                                firma += _hash(relativa, st.st_size, st.st_mtime_ns)
                        except FileNotFoundError:
                            continue
                        entradas += 1
                        if tope is not None and entradas > tope:
                            return Huella(entradas, 0)
            except (FileNotFoundError, NotADirectoryError):
                if carpeta == raiz:
                    return None
        os.stat(raiz)
    except OSError:
        return None
    return Huella(entradas, firma & MASCARA)
