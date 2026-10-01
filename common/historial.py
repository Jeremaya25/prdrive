#!/usr/bin/env python3
"""El diario de pasadas: cómo fueron las últimas de cada pareja.

`results.py` guarda UNA pasada por pareja, la última, y cada una pisa a la
anterior: se sabe que una pareja falla, pero no desde cuándo ni si falló una
vez o falla siempre. Esto añade una línea por pasada en
`state/historial.jsonl`, con las últimas `POR_PAREJA` de cada pareja, que la
pantalla de «Reparación» (y con ella `sync.py --doctor`, que imprime el mismo
diagnóstico) resume en una frase.

Lo escribe `sync.py` junto a `results.apuntar()` y con su mismo criterio: ni
los simulacros ni las parejas saltadas son un resultado. Y con la regla de todo
lo de `state/`: leer nunca es un error (una línea a medias por un corte de
corriente, o basura, se salta) y escribir nunca tumba una pasada.

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

POR_PAREJA = 50
"""Cuántas pasadas de cada pareja se guardan.

Con el servicio cada media hora son un día; con pasadas a mano o al enchufar,
semanas. Lo que se pregunta es si una pareja falla de vez en cuando o cada vez,
y desde cuándo; para eso cincuenta bastan, y una racha más larga se cuenta
igual con «al menos».
"""

RECORTE = 2 * POR_PAREJA
"""Pasadas de una pareja a partir de las cuales se recorta el diario.

Lo normal es AÑADIR una línea (`open("a")` escribe al final y nada más).
Recortar es reescribirlo entero, y en una memoria flash lo que se paga es lo
que se escribe (los ciclos de escritura son la razón por la que no se guarda el
log de una pasada buena; ver `sync.temp_log()`). Por eso no se recorta en cada
pasada: se deja crecer hasta que alguna pareja tiene el DOBLE de las que se
guardan y entonces cada una se deja en `POR_PAREJA`. El fichero se reescribe
como mucho una vez por cada `POR_PAREJA` líneas añadidas. Leer no gasta el
dispositivo, y por eso contar sí se hace en cada pasada.
"""

TOPE_BYTES = 1024 * 1024
"""Tamaño del fichero a partir del cual se recorta, y se deja en la mitad.

Es la red de seguridad de `RECORTE`, que solo cuenta parejas: las que ya no
existen (renombradas, borradas) conservan sus `POR_PAREJA` para siempre y una
línea que no se entiende no es de ninguna. Recortar hasta la mitad evita que el
siguiente recorte llegue enseguida.
"""


def ruta() -> Path:
    """Devuelve la ruta de `state/historial.jsonl`.

    Es función y no constante: los tests cambian `model.STATE_DIR` al vuelo.
    """
    return model.STATE_DIR / "historial.jsonl"


class Pasada(NamedTuple):
    """Una pasada apuntada en el diario.

    Args:
        pareja: Nombre de la pareja.
        inicio: `store.stamp()` de cuando empezó.
        codigo: Lo que devolvió la pasada; 0 es bien.
        segundos: Lo que duró, o `None` si no consta.
        transferido: Bytes que movió rclone según su última estadística
            (`progress.final_del_log()`), o `None` si no se sabe. No hay
            ficheros movidos ni borrados: `--stats-one-line` no los cuenta en
            la línea final.
    """
    pareja: str
    inicio: str
    codigo: int
    segundos: float | None = None
    transferido: int | None = None

    @property
    def ok(self) -> bool:
        """Indica si la pasada acabó bien."""
        return self.codigo == 0


class Reloj:
    """Mide cuándo empezó una pasada, para apuntar su inicio y su duración.

    El inicio es la hora de pared, como todo lo de `state/`; la duración sale
    de `time.monotonic()`, que no salta si el equipo cambia la hora a mitad de
    una pasada (horario de verano, sincronización de la hora).
    """

    def __init__(self) -> None:
        """Anota el inicio de la pasada."""
        self.inicio = store.stamp()
        self._t0 = time.monotonic()

    def pasada(self, pareja: str, codigo: int,
               transferido: int | None = None) -> Pasada:
        """Devuelve la `Pasada` de esa pareja con la duración medida hasta ahora."""
        return Pasada(pareja, self.inicio, int(codigo),
                      round(time.monotonic() - self._t0, 1), transferido)


def pasada(pareja: str, codigo: int, reloj: Reloj | None = None,
           transferido: int | None = None) -> Pasada:
    """Devuelve la pasada que se apunta, con su reloj si lo hay.

    Sin reloj (una pareja que se cortó antes de llegar a rclone, cuando el
    dispositivo desaparece a mitad de una pasada de varias: `sync.run_all()`)
    consta con la hora de ahora y sin duración: un cero sería inventado, y la
    pareja tiene que constar igual porque ese fallo también es de la racha.
    """
    if reloj is None:
        return Pasada(pareja, store.stamp(), int(codigo), None, transferido)
    return reloj.pasada(pareja, codigo, transferido)


def _linea(p: Pasada) -> str:
    """Devuelve la línea JSON de una pasada, con su salto de línea."""
    return json.dumps({"pareja": p.pareja, "inicio": p.inicio, "codigo": p.codigo,
                       "segundos": p.segundos, "transferido": p.transferido},
                      ensure_ascii=False) + "\n"


def _entero(valor) -> bool:
    """Indica si es un entero de verdad.

    En JSON `true` llega como un `int` de Python.
    """
    return isinstance(valor, int) and not isinstance(valor, bool)


def _segundos(valor) -> float | None:
    """Devuelve una duración legible, o `None`.

    `json` acepta `NaN` e `Infinity`, que no son una duración.
    """
    if not (_entero(valor) or isinstance(valor, float)):
        return None
    try:
        segundos = float(valor)
    except OverflowError:               # un entero de cuatrocientas cifras
        return None
    return segundos if math.isfinite(segundos) and segundos >= 0 else None


def _pasada(texto: str) -> Pasada | None:
    """Convierte una línea del diario en su `Pasada`.

    Se salta lo que no es JSON (la línea que un corte dejó a medias) y lo que
    lo es pero no trae lo que hace falta: sin pareja, sin fecha legible o sin
    código no dice nada de ninguna pasada. Lo accesorio (duración, bytes) que
    no encaje se lee como «no consta».

    Returns:
        La pasada, o `None` si la línea no lo es entera.
    """
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
    r"""Devuelve todas las pasadas apuntadas, en el orden en que se apuntaron.

    Nunca falla: sin fichero no hay pasadas y una línea que no se entiende se
    salta sin arrastrar a las demás. Se parte por `\n` y no con `splitlines()`,
    que también corta por separadores de Unicode que un nombre podría llevar.
    """
    try:
        crudo = ruta().read_bytes()
    except OSError:
        return []
    return [p for linea in crudo.decode("utf-8", errors="replace").split("\n")
            if linea.strip() and (p := _pasada(linea)) is not None]


def apuntar(pasada: Pasada) -> bool:
    """Añade una pasada al diario.

    Nunca lanza: si el dispositivo no deja escribir (lleno, de solo lectura o
    ausente) la línea se pierde, pero una sincronización no puede caerse por su
    propio diario. Si la última línea quedó a medias (un corte de corriente a
    mitad de escribirla), la nueva empieza en una línea propia: pegada detrás
    se perderían las dos.

    Returns:
        True si ha quedado escrita.
    """
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
    """Devuelve las líneas que quedan tras un recorte.

    Son las últimas `POR_PAREJA` de cada pareja, en su orden, y como mucho la
    mitad de `TOPE_BYTES`, quitando por lo más viejo.
    """
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
    """Reescribe el diario si una pareja o el fichero pasan de su tope.

    La reescritura es atómica (`store.write_text`): un corte a mitad deja el
    fichero de antes, no uno a medias. No protege una pasada que apunte entre
    la lectura y la reescritura desde otro proceso: esa línea se perdería. Es
    un diario, no el resultado (ese va en `results`), y las pasadas de una
    misma pareja no se solapan.

    Returns:
        True si lo ha reescrito.
    """
    try:
        tamano = ruta().stat().st_size
    except OSError:
        return False
    pasadas = leer()
    por_pareja = Counter(p.pareja for p in pasadas)
    if tamano <= TOPE_BYTES and all(n <= RECORTE for n in por_pareja.values()):
        return False
    return store.write_text(ruta(), "".join(_recortadas(pasadas)))


class Racha(NamedTuple):
    """La racha de fallos en la que está una pareja, según el diario.

    Args:
        desde: Inicio de la primera pasada fallida de la racha.
        exacta: True si antes de esa pasada consta una buena: la racha empezó
            ahí. Si no, empezó ahí O ANTES (el diario no llega más atrás, o se
            estrenó con la pareja ya fallando) y eso no se sabe.
        buenas: De las `pasadas` últimas, cuántas fueron bien.
        pasadas: Cuántas se cuentan, hasta `POR_PAREJA`.
    """
    desde: str
    exacta: bool
    buenas: int
    pasadas: int


def racha(pasadas: list[Pasada]) -> Racha | None:
    """Devuelve la racha de las pasadas de UNA pareja, en orden.

    Returns:
        La racha, o `None` si la última pasada que consta fue bien o no consta
        ninguna.
    """
    if not pasadas or pasadas[-1].ok:
        return None
    primera = len(pasadas) - 1
    while primera > 0 and not pasadas[primera - 1].ok:
        primera -= 1
    ultimas = pasadas[-POR_PAREJA:]
    return Racha(pasadas[primera].inicio, primera > 0,
                 sum(1 for p in ultimas if p.ok), len(ultimas))


def rachas(nombres: Iterable[str]) -> dict[str, Racha]:
    """Devuelve las rachas de esas parejas, leyendo el diario una sola vez.

    Lo llama la ventana mientras se pinta. Las parejas que no están fallando no
    salen.
    """
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
