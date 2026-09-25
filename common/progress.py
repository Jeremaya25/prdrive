#!/usr/bin/env python3
"""
progress.py — Cómo va una pasada, leído de las estadísticas del log de rclone.

Una pareja grande tarda minutos, y hasta ahora la salida no decía nada entre el
`ejecutando:` y el `OK.`: parecía colgada. rclone ya sabe cuánto lleva; con
`--stats-one-line` y un `--stats` corto (la capa base de `model.BASE_FLAGS`) lo
escribe cada pocos segundos en su log, y `sync.py` lo va leyendo mientras la
pareja corre para contarlo por su salida.

Es puramente informativo, y de ahí las dos reglas de este módulo:

- **Cada línea del log es texto de otro programa.** Lo que no encaja entero en
  el formato no da progreso: ni un error, ni un número a medias. Una línea
  cortada —el log se lee mientras rclone lo escribe— es lo normal, no un caso raro.
- **No hay canal aparte.** Ni la API rc de rclone, ni puertos, ni procesos: el
  log temporal de la pareja es lo único que se lee. Si de ahí no sale nada, no
  hay progreso y la pasada va exactamente igual que antes.

Leer es cosa de este fichero y ejecutar de `sync.py`, para poder probar el
lector con logs grabados sin lanzar nada.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import NamedTuple

# Lo que abre la línea de progreso en la salida de sync.py. La ventana de salida
# la busca para reescribirla en su sitio en vez de apilar una por lectura. Va en
# una constante que importan los dos, no escrita dos veces como el resto del
# vocabulario de `ui.tk._tono`: si la ventana dejara de reconocer esta, no se
# quedaría sin color, se llenaría con cientos de líneas.
ETIQUETA = "progreso:"

# Ninguna línea de estadísticas mide esto. Un trozo sin saltos de línea más largo
# se tira en vez de guardarlo esperando un salto que puede no llegar nunca.
RESTO_MAX = 64 * 1024

# Cuánto se lee del final de un log terminado para encontrar su última
# estadística (ver `final_del_log()`).
COLA = 64 * 1024

_MULTIPLOS = {"": 1, "K": 2 ** 10, "M": 2 ** 20, "G": 2 ** 30, "T": 2 ** 40,
              "P": 2 ** 50, "E": 2 ** 60}

# fs.SizeSuffix.ByteUnit() de rclone: "0 B", "512 B", "1.086 MiB".
_TAMANO = r"(\d+(?:\.\d+)?) ?([KMGTPE]?)i?B"

# fs/accounting/stats.go, StatsInfo.String(): "%s%13s / %s, %s, %s, ETA %s%s"
# —lo transferido, el total, el porcentaje (o "-"), la velocidad y el tiempo que
# falta—. Es la misma línea con --stats-one-line que sin él (entonces va detrás
# de "Transferred:" en un bloque de varias), así que un `stats-one-line = false`
# en la pareja se sigue leyendo. Se busca, no se ancla: delante va la fecha del
# log, o la de --stats-one-line-date. Exigir la ETA es exigir que la velocidad
# esté entera; la cuenta de ficheros ("Transferred: 0 / 3, 0%") y la línea de
# cada fichero ("a.bin: 23% / 1.431 MiB, 0 B/s, -") no encajan.
_ESTADISTICA = re.compile(r"(?<![\w.])" + _TAMANO + r" / " + _TAMANO
                          + r", (\d+%|-), " + _TAMANO + r"/s, ETA \S")


def _octetos(numero: str, prefijo: str) -> float:
    return float(numero) * _MULTIPLOS[prefijo]


def _tamano(octetos: float) -> str:
    """«1,1 MB»: como enseña los tamaños el resto de la interfaz."""
    valor = float(octetos)
    for unidad in ("B", "KB", "MB", "GB", "TB"):
        if valor < 1024 or unidad == "TB":
            break
        valor /= 1024
    texto = f"{valor:.0f}" if unidad == "B" else f"{valor:.1f}".replace(".", ",")
    return f"{texto} {unidad}"


class Progreso(NamedTuple):
    hecho: int                  # bytes transferidos
    total: int                  # los que rclone sabe que tiene que mover, hasta ahora
    porcentaje: int | None      # el de rclone; None cuando él no lo sabe ("-")
    velocidad: float            # bytes por segundo

    def texto(self) -> str:
        """«2,1 MB de 3,4 MB · 61 % · 1,1 MB/s». Sin porcentaje si rclone no
        lo da: con el total a cero no hay porcentaje que valga."""
        partes = [f"{_tamano(self.hecho)} de {_tamano(self.total)}"]
        if self.porcentaje is not None:
            partes.append(f"{self.porcentaje} %")
        partes.append(f"{_tamano(self.velocidad)}/s")
        return " · ".join(partes)


def leer(linea: str) -> Progreso | None:
    """Una línea del log -> su Progreso, o None si no es una estadística entera."""
    m = _ESTADISTICA.search(linea)
    if m is None:
        return None
    hecho, pre_hecho, total, pre_total, pct, vel, pre_vel = m.groups()
    return Progreso(hecho=round(_octetos(hecho, pre_hecho)),
                    total=round(_octetos(total, pre_total)),
                    porcentaje=None if pct == "-" else int(pct[:-1]),
                    velocidad=_octetos(vel, pre_vel))


def ultimo(texto: str) -> Progreso | None:
    """La lectura más reciente de un trozo de log. Cada estadística cuenta desde
    el principio de la pasada, así que la última es la verdad, aunque diga menos
    que las de antes o llegue detrás de un error."""
    for linea in reversed(texto.splitlines()):
        progreso = leer(linea)
        if progreso is not None:
            return progreso
    return None


def final_del_log(ruta: Path) -> Progreso | None:
    """La última estadística de un log ya terminado: lo que movió la pasada.

    La pide `sync.run_pair()` justo antes de que `dispose_log()` tire el log, y
    va al diario de pasadas (`common/historial.py`). Solo los bytes: con
    `--stats-one-line`, la cuenta de ficheros (`xfr#N/M`) solo sale mientras
    queda algo en la cola (`StatsInfo.String()`, fs/accounting/stats.go), así
    que la línea final nunca la lleva, y los borrados solo están en el bloque de
    varias líneas («Deleted:»). Un número que unas veces está y otras no, no se
    guarda.

    Se lee la cola y no el log entero, que en una pareja grande con `-v` es de
    megas: rclone escribe su estadística de cierre al terminar (`Run()`, en
    cmd/cmd.go) y detrás solo quedan el error que lo tumbó y la consola que
    añade `sync.append_output()`. Si la lectura empieza a mitad del fichero, su
    primera línea se tira entera: «2.086 MiB» cortado en «086 MiB» sería una
    estadística perfectamente legible, y falsa.

    Como todo lo de este módulo, de más: sin log, sin estadísticas o con
    cualquier error al leerlo, None."""
    try:
        with ruta.open("rb") as f:
            tamano = f.seek(0, os.SEEK_END)
            f.seek(max(0, tamano - COLA))
            datos = f.read()
        if tamano > COLA:
            datos = datos.partition(b"\n")[2]
        return ultimo(datos.decode("utf-8", errors="replace"))
    except Exception:                                    # noqa: BLE001
        return None


class Seguidor:
    """Lee un log que alguien sigue escribiendo y dice qué contar, si hay algo.

    Recibe bytes tal como llegan —un trozo cualquiera: puede acabar a media
    línea o a media letra— y solo mira líneas completas. Devuelve la línea que
    sync.py tiene que escribir, o None si no hay nada nuevo que contar: sin
    estadísticas, o con la misma de la última vez."""

    def __init__(self) -> None:
        self._resto = b""
        self._contado: str | None = None

    def alimentar(self, datos: bytes) -> str | None:
        completas, _, self._resto = (self._resto + datos).rpartition(b"\n")
        if len(self._resto) > RESTO_MAX:
            self._resto = b""
        progreso = ultimo(completas.decode("utf-8", errors="replace"))
        if progreso is None:
            return None
        linea = f"  {ETIQUETA} {progreso.texto()}"
        if linea == self._contado:
            return None
        self._contado = linea
        return linea
