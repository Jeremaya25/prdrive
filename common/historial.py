#!/usr/bin/env python3
"""
historial.py — El diario de pasadas: cómo fueron las últimas de cada pareja.

`results.py` guarda UNA pasada por pareja, la última, y cada una pisa la
anterior. Con eso se sabe que una pareja falla, pero no desde cuándo, ni si
falló una vez o falla cada vez, ni cuántas veces ha corrido esta semana. Esto es
lo que falta: una línea por pasada en `state/historial.jsonl`, con las últimas
`POR_PAREJA` de cada pareja, que la pantalla de «Reparación» —y con ella
`sync.py --doctor`, que imprime el mismo diagnóstico— resume en una frase.

Lo escribe `sync.py` al lado de `results.apuntar()` y con su mismo criterio: ni
los simulacros ni las parejas saltadas son un resultado. Y con la misma regla
que todo lo de `state/`: leer nunca es un error —una línea a medio escribir por
un corte de corriente, o basura, se salta— y escribir nunca tumba una pasada.

Las fechas son `store.stamp()`, como en el resto de ficheros de `state/`.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections import Counter
from pathlib import Path
from typing import Iterable, NamedTuple

from . import model, store

# Cuántas pasadas de cada pareja se guardan. Con el servicio cada media hora
# son un día; con pasadas a mano o al enchufar, semanas. Lo que se pregunta es
# si una pareja falla de vez en cuando o cada vez, y desde cuándo, y para eso
# cincuenta bastan: una racha más larga se cuenta igual, con «al menos».
POR_PAREJA = 50

# Cuándo se recorta. Lo normal es AÑADIR una línea: `open("a")` escribe el final
# del fichero y nada más. Recortar es reescribirlo entero, y en una memoria
# flash lo que se paga es lo que se escribe —los ciclos de escritura son la
# razón por la que hoy no se guarda el log de una pasada buena (ver
# `sync.temp_log()`)—, así que no se recorta en cada pasada: se deja crecer
# hasta que alguna pareja tiene el DOBLE de las que se guardan, y entonces se
# deja cada una en `POR_PAREJA`. Hasta el siguiente recorte hacen falta otras
# `POR_PAREJA` pasadas de esa pareja: el fichero entero se reescribe una vez
# por cada cincuenta líneas añadidas, como mucho. Leer no gasta el dispositivo,
# y por eso contar sí se hace en cada pasada.
RECORTE = 2 * POR_PAREJA

# La red de seguridad de lo anterior, que solo cuenta parejas: las que ya no
# existen (renombradas, borradas) conservan sus `POR_PAREJA` para siempre, y
# una línea que no se entiende no es de ninguna. Si el fichero pasa de esto se
# recorta también, y hasta la mitad, para que el siguiente no llegue enseguida.
TOPE_BYTES = 1024 * 1024


def ruta() -> Path:
    """Función y no constante: los tests cambian `model.STATE_DIR` al vuelo."""
    return model.STATE_DIR / "historial.jsonl"


class Pasada(NamedTuple):
    pareja: str
    inicio: str                 # `store.stamp()` de cuando empezó
    codigo: int                 # lo que devolvió la pasada: 0 es bien
    segundos: float | None = None   # lo que duró; None si no consta
    # Los bytes que movió rclone según su última estadística
    # (`progress.final_del_log()`); None si no se sabe. Ficheros movidos o
    # borrados no hay: `--stats-one-line` no los cuenta en la línea final.
    transferido: int | None = None

    @property
    def ok(self) -> bool:
        return self.codigo == 0


class Reloj:
    """Cuándo empezó una pasada, para apuntar su inicio y lo que duró.

    El inicio es la hora de pared, como todo lo de `state/`; la duración sale de
    `time.monotonic()`, que no salta si el equipo cambia la hora a mitad de una
    pasada (el horario de verano, una sincronización de la hora)."""

    def __init__(self) -> None:
        self.inicio = store.stamp()
        self._t0 = time.monotonic()

    def pasada(self, pareja: str, codigo: int,
               transferido: int | None = None) -> Pasada:
        return Pasada(pareja, self.inicio, int(codigo),
                      round(time.monotonic() - self._t0, 1), transferido)


def pasada(pareja: str, codigo: int, reloj: Reloj | None = None,
           transferido: int | None = None) -> Pasada:
    """La pasada que se apunta, con su reloj si lo hay.

    Sin él —una pareja que se cortó antes de llegar a rclone, cuando el
    dispositivo desaparece a mitad de una pasada de varias (`sync.run_all()`)—
    consta con la hora de ahora y sin duración: un cero sería inventado, y la
    pareja tiene que constar igual, porque ese fallo también es de la racha."""
    if reloj is None:
        return Pasada(pareja, store.stamp(), int(codigo), None, transferido)
    return reloj.pasada(pareja, codigo, transferido)


# ---------------------------------------------------------------------------
# El fichero
# ---------------------------------------------------------------------------

def _linea(p: Pasada) -> str:
    return json.dumps({"pareja": p.pareja, "inicio": p.inicio, "codigo": p.codigo,
                       "segundos": p.segundos, "transferido": p.transferido},
                      ensure_ascii=False) + "\n"


def _entero(valor) -> bool:
    """Un entero de verdad: en JSON, `true` llega como un int de Python."""
    return isinstance(valor, int) and not isinstance(valor, bool)


def _segundos(valor) -> float | None:
    """Una duración legible, o None. `json` acepta `NaN` e `Infinity`, que no
    son una duración."""
    if not (_entero(valor) or isinstance(valor, float)):
        return None
    try:
        segundos = float(valor)
    except OverflowError:               # un entero de cuatrocientas cifras
        return None
    return segundos if math.isfinite(segundos) and segundos >= 0 else None


def _pasada(texto: str) -> Pasada | None:
    """Una línea del diario -> su Pasada, o None si no lo es entera.

    Lo mismo que no es JSON (la línea que un corte dejó a medias) se salta lo
    que lo es pero no trae lo que hace falta: sin pareja, sin una fecha legible
    o sin código, esa línea no dice nada de ninguna pasada. Lo accesorio
    (duración, bytes) que no encaje se lee como «no consta»."""
    try:
        dato = json.loads(texto)
    except (ValueError, RecursionError):    # RecursionError: «[[[[…» anidado sin fin
        return None
    if not isinstance(dato, dict):
        return None
    pareja, inicio, codigo = dato.get("pareja"), dato.get("inicio"), dato.get("codigo")
    if not isinstance(pareja, str) or not pareja:
        return None
    if not isinstance(inicio, str) or store.desde_sello(inicio) is None:
        return None
    if not _entero(codigo):
        return None
    transferido = dato.get("transferido")
    return Pasada(pareja, inicio, codigo, _segundos(dato.get("segundos")),
                  transferido if _entero(transferido) and transferido >= 0 else None)


def leer() -> list[Pasada]:
    """Todas las pasadas apuntadas, en el orden en que se apuntaron.

    Nunca falla: sin fichero no hay pasadas, y una línea que no se entiende se
    salta sin arrastrar a las demás. Se parte por `\\n` y no con `splitlines()`,
    que también corta por separadores de Unicode que un nombre podría llevar."""
    try:
        crudo = ruta().read_bytes()
    except OSError:
        return []
    return [p for linea in crudo.decode("utf-8", errors="replace").split("\n")
            if linea.strip() and (p := _pasada(linea)) is not None]


def apuntar(pasada: Pasada) -> bool:
    """Añade una pasada al diario. True si ha quedado escrita.

    Nunca lanza: si el dispositivo no deja escribir (lleno, de solo lectura, o
    ya no está), la línea se pierde, pero una sincronización no puede caerse
    por su propio diario.

    Si la última línea del fichero quedó a medias —un corte de corriente a
    mitad de escribirla—, la nueva empieza en una línea propia: pegada detrás,
    se perderían las dos."""
    try:
        with ruta().open("a+b") as f:
            f.seek(0, os.SEEK_END)
            prefijo = b""
            if f.tell() > 0:
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b"\n":
                    prefijo = b"\n"
            f.write(prefijo + _linea(pasada).encode("utf-8"))
    except OSError:
        return False
    recortar_si_toca()
    return True


def _recortadas(pasadas: list[Pasada]) -> list[str]:
    """Las líneas que quedan tras un recorte: las últimas `POR_PAREJA` de cada
    pareja, en su orden, y como mucho la mitad de `TOPE_BYTES`, quitando por lo
    más viejo."""
    vistas: Counter = Counter()
    quedan = []
    for p in reversed(pasadas):
        if vistas[p.pareja] < POR_PAREJA:
            vistas[p.pareja] += 1
            quedan.append(_linea(p))
    quedan.reverse()
    total = sum(len(linea.encode("utf-8")) for linea in quedan)
    inicio = 0
    while inicio < len(quedan) and total > TOPE_BYTES // 2:
        total -= len(quedan[inicio].encode("utf-8"))
        inicio += 1
    return quedan[inicio:]


def recortar_si_toca() -> bool:
    """Reescribe el diario si alguna pareja pasa de `RECORTE` o el fichero de
    `TOPE_BYTES` (ver `RECORTE`). Devuelve si lo ha reescrito.

    La reescritura es atómica (`store.write_text`): un corte a mitad deja el
    fichero de antes, no uno a medias. Lo que no protege es una pasada que
    apunte entre la lectura y la reescritura, desde otro proceso: esa línea se
    perdería. Es un diario, no el resultado —ese va en `results`—, y las
    pasadas de una misma pareja no se solapan."""
    try:
        tamano = ruta().stat().st_size
    except OSError:
        return False
    pasadas = leer()
    por_pareja = Counter(p.pareja for p in pasadas)
    if tamano <= TOPE_BYTES and all(n <= RECORTE for n in por_pareja.values()):
        return False
    return store.write_text(ruta(), "".join(_recortadas(pasadas)))


# ---------------------------------------------------------------------------
# Lo que se lee: desde cuándo falla una pareja
# ---------------------------------------------------------------------------

class Racha(NamedTuple):
    """La racha de fallos en la que está una pareja, según el diario."""
    desde: str          # el inicio de la primera pasada fallida de la racha
    # True si antes de esa pasada consta una buena: la racha empezó ahí. Si no,
    # empezó ahí O ANTES —el diario no llega más atrás, o se estrenó con la
    # pareja ya fallando—, y eso no se sabe.
    exacta: bool
    buenas: int         # de las `pasadas` últimas, cuántas fueron bien
    pasadas: int        # cuántas se cuentan: hasta `POR_PAREJA`


def racha(pasadas: list[Pasada]) -> Racha | None:
    """La racha de las pasadas de UNA pareja, en orden; None si la última que
    consta fue bien, o si no consta ninguna."""
    if not pasadas or pasadas[-1].ok:
        return None
    primera = len(pasadas) - 1
    while primera > 0 and not pasadas[primera - 1].ok:
        primera -= 1
    ultimas = pasadas[-POR_PAREJA:]
    return Racha(pasadas[primera].inicio, primera > 0,
                 sum(1 for p in ultimas if p.ok), len(ultimas))


def rachas(nombres: Iterable[str]) -> dict[str, Racha]:
    """Las rachas de esas parejas, leyendo el diario una sola vez: lo llama la
    ventana mientras se pinta. Las que no están fallando no salen."""
    buscadas = set(nombres)
    por_pareja: dict[str, list[Pasada]] = {}
    for p in leer():
        if p.pareja in buscadas:
            por_pareja.setdefault(p.pareja, []).append(p)
    salida = {}
    for nombre, pasadas in por_pareja.items():
        r = racha(pasadas)
        if r is not None:
            salida[nombre] = r
    return salida
