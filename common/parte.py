#!/usr/bin/env python3
"""El parte de una pareja: cómo le fue en una pasada, en una línea que lee el agente.

`sync.py` escribe una línea por pareja al acabarla (`linea()`), detrás de lo que
lee una persona, y el agente residente la busca en la salida (`leer()`). Dice lo
que el código de salida no dice: si la pasada MOVIÓ algo, cuántas veces lanzó
rclone y cuántos bytes de su base reescribió en la unidad. Con eso el agente
lleva la cuenta de lo que gasta (`common/consumo.py`) y sabe cuándo una pareja
lleva tiempo sin nada que hacer.

Que una pasada bisync no movió nada se sabe por sus listados: rclone los
reescribe enteros en cada pasada, pero si no cambió nada en ningún lado solo
cambia la primera línea, que lleva la fecha (medido el 11/10/2026 con rclone
1.75.1; `docs/superpowers/pruebas/2026-10-11-watch-energia-windows-medidas.md`).
Se compara el resto, antes y después. No depende de lo que rclone escriba en su
log. En las parejas que no son bisync no hay listados y se mira el log
(`sin_actividad()`); ante la duda, no se sabe (`None`), que nunca cuenta como
«no movió nada».
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import NamedTuple

MARCA = "@prdrive "
"""Cómo empieza la línea del parte; el resto es un objeto JSON."""
SALTADA = -1
"""El `rc` del parte de una pareja que se saltó (pedía `--resync`): es `sync.SKIPPED`."""
TOPE_LOG = 256 * 1024
"""Bytes de log que se leen como mucho para saber si una pasada movió algo."""
NADA_QUE_MOVER = "There was nothing to transfer"
"""Lo que escribe rclone (`fs/sync/sync.go`) cuando `copy` o `sync` no transfieren nada."""
_ACTIVIDAD = re.compile(
    r": (?:Copied|Deleted|Moved|Renamed|Updated|Made directory|Removed directory|"
    r"Removing directory|Set directory modification time)\b")
"""Lo que escribe rclone con `-v` por cada cosa que hace en un lado."""


class Parte(NamedTuple):
    """Cómo le fue a una pareja en una pasada.

    Args:
        pareja: Su nombre.
        rc: El código con que acabó; -1 es que se saltó (pedía `--resync`).
        movio: Si la pasada cambió algo en algún lado; `None` si no se sabe.
        ordenes: Cuántas veces se lanzó rclone.
        escrito: Bytes de la base de bisync que la pasada reescribió.
    """
    pareja: str
    rc: int
    movio: bool | None = None
    ordenes: int = 0
    escrito: int = 0

    @property
    def vacia(self) -> bool:
        """Indica si la pasada fue bien y se sabe que no movió nada."""
        return self.rc == 0 and self.movio is False


def linea(parte: Parte) -> str:
    """Devuelve la línea que `sync.py` escribe para el agente."""
    return MARCA + json.dumps(parte._asdict(), ensure_ascii=False)


def leer(texto: str) -> dict[str, Parte]:
    """Devuelve los partes que hay en la salida de un `sync.py`, por pareja.

    Lo que no se entiende se ignora: la salida de un `sync.py` de antes no lleva
    ninguno, y entonces de esa pasada solo se sabe su código.
    """
    partes: dict[str, Parte] = {}
    for renglon in texto.splitlines():
        if not renglon.startswith(MARCA):
            continue
        try:
            d = json.loads(renglon[len(MARCA):])
            movio = d.get("movio")
            parte = Parte(str(d["pareja"]), int(d["rc"]),
                          movio if isinstance(movio, bool) else None,
                          int(d.get("ordenes") or 0), int(d.get("escrito") or 0))
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
        partes[parte.pareja] = parte
    return partes


def trozos(texto: str) -> dict[str, str]:
    """Devuelve la salida de cada pareja de un `sync.py` que pasó varias.

    El trozo de una pareja es lo que hay desde el parte de la anterior (o
    desde el principio) hasta su propio parte, sin él. Lo que va detrás del
    último parte (el resumen «Hecho. …») no es de ninguna. Así un fallo de
    red, o un «Saltada», se le apunta a la pareja que lo dijo y no a todas.
    """
    salida: dict[str, str] = {}
    actual: list[str] = []
    for renglon in texto.splitlines():
        if renglon.startswith(MARCA):
            try:
                pareja = str(json.loads(renglon[len(MARCA):])["pareja"])
            except (ValueError, TypeError, KeyError):
                continue
            salida[pareja] = "\n".join(actual)
            actual = []
        else:
            actual.append(renglon)
    return salida


def _cuerpo(ruta: str) -> bytes:
    """Devuelve la firma de un listado sin su primera línea, que lleva la fecha."""
    firma = hashlib.blake2b(digest_size=16)
    with open(ruta, "rb") as f:
        f.readline()
        for trozo in iter(lambda: f.read(1 << 16), b""):
            firma.update(trozo)
    return firma.digest()


def base(pair) -> dict[str, tuple[int, int, bytes]]:
    """Devuelve la foto de la base de bisync de una pareja.

    Los listados se buscan por lo que hay en su workdir, no por el nombre que
    se esperaría (`bisync.expected_prefix()`): rclone resuelve un remote de tipo
    `alias` y nombra la base con la ruta de verdad (visto el 11/10/2026), y
    aquí no hace falta saber cómo se llama, solo si cambia. Con más de una
    base en el workdir (una vieja sin aparcar) no se sabe cuál es la buena:
    ninguno lleva firma, y la pasada cuenta como que movió.

    Returns:
        `{nombre: (tamaño, mtime en ns, firma del cuerpo)}` de los ficheros de
        su workdir. La firma solo la tienen los dos listados (`.path1.lst`,
        `.path2.lst`) de su única base; `{}` si no se puede leer.
    """
    from common import bisync

    foto: dict[str, tuple[int, int, bytes]] = {}
    rutas: dict[str, str] = {}
    try:
        with os.scandir(pair.workdir) as entradas:
            for e in entradas:
                if not e.is_file():
                    continue
                st = e.stat()
                foto[e.name] = (st.st_size, st.st_mtime_ns, b"")
                rutas[e.name] = e.path
        unos = [n for n in foto if n.endswith(bisync.PATH1_SUFFIX)]
        otros = [n for n in foto if n.endswith(bisync.PATH2_SUFFIX)]
        if len(unos) == 1 and len(otros) == 1 \
                and unos[0][:-len(bisync.PATH1_SUFFIX)] == otros[0][:-len(bisync.PATH2_SUFFIX)]:
            for nombre in (unos[0], otros[0]):
                foto[nombre] = (*foto[nombre][:2], _cuerpo(rutas[nombre]))
    except OSError:
        return {}
    return foto


def _cuerpos(foto: dict[str, tuple[int, int, bytes]]) -> dict[str, bytes]:
    return {nombre: firma for nombre, (_t, _f, firma) in foto.items() if firma}


def sin_actividad(log: Path | None) -> bool | None:
    """Indica si el log de un `copy` o un `sync` de rclone dice que no movió nada.

    Returns:
        `True` si rclone dice que no había nada que transferir y no hay una sola
        línea de algo hecho; `False` si hay alguna; `None` si no se sabe (sin
        log, demasiado largo o sin ninguna de las dos cosas).
    """
    if log is None:
        return None
    try:
        if log.stat().st_size > TOPE_LOG:
            return None
        texto = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if _ACTIVIDAD.search(texto):
        return False
    return True if NADA_QUE_MOVER in texto else None


class Medida:
    """Lo que `sync.py` mide de una pareja mientras la pasa.

    Args:
        pair: La pareja.
        ordenes: Cuántas veces se había lanzado rclone antes de empezarla.
        medir: Si se mide; un simulacro no escribe nada y no se mide.
    """

    def __init__(self, pair, ordenes: int, medir: bool = True) -> None:
        self.pair = pair
        self.ordenes = ordenes
        self.medir = medir
        self.antes = None
        if medir and pair.is_bisync:
            try:
                self.antes = base(pair)
            except Exception:                   # noqa: BLE001 — medir no puede tumbar una pasada
                self.medir = False
        self.resync = False
        """Si la pasada es un `--resync`: rehace la base, así que siempre «mueve»."""
        self.quieta: bool | None = None
        """Lo que diga el log en una pareja que no es bisync (`sin_actividad()`)."""
        self.parte: Parte | None = None
        """El parte ya cerrado (`cerrar()`), si `sync.py` lo necesitó antes de acabar."""

    def cerrar(self, rc: int, ordenes: int) -> Parte:
        """Calcula el parte ahora y lo guarda en `parte`: lo que venga después no cuenta."""
        self.parte = self.acabar(rc, ordenes)
        return self.parte

    def acabar(self, rc: int, ordenes: int) -> Parte:
        """Devuelve el parte de la pareja al terminar.

        Args:
            rc: Su código de salida (-1 si se saltó).
            ordenes: Cuántas veces se ha lanzado rclone hasta ahora.
        """
        movio: bool | None = None
        escrito = 0
        if self.antes is not None:
            try:
                despues = base(self.pair)
            except Exception:                   # noqa: BLE001
                despues = {}
            escrito = sum(tam for nombre, (tam, fecha, _f) in despues.items()
                          if self.antes.get(nombre, (None, None))[:2] != (tam, fecha))
            antes, ahora = _cuerpos(self.antes), _cuerpos(despues)
            movio = self.resync or len(ahora) != 2 or antes != ahora
        elif self.medir and self.quieta is not None:
            movio = not self.quieta
        if rc != 0:
            movio = None            # una pasada que falla o se salta no dice si había algo
        return Parte(self.pair.name, rc, movio, ordenes - self.ordenes, escrito)
