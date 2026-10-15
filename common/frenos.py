#!/usr/bin/env python3
"""Los frenos de borrado de rclone, reconocidos en el log de una pasada.

rclone tiene dos y no se miden en lo mismo (AGENTS.md, «Safety invariants»):

- **bisync** compara lo borrado con el listado de la pasada anterior y para si
  pasa de un PORCENTAJE (`excessDeletes()`, `cmd/bisync/deltas.go`). No ha
  propagado nada cuando para. Tiene otro freno parecido: si ningún fichero de un
  lado sigue igual, para antes de copiarlo todo (`cmd/bisync/operations.go`).
  `--force` salta los dos.
- **`up-mirror` y `down-mirror`** (`rclone sync`) usan el `--max-delete` corriente:
  una CUENTA de ficheros (`StatsInfo.DeleteFile()`, `fs/accounting/stats.go`).
  Borra exactamente hasta el tope, falla con «--max-delete threshold reached» y
  deja el resto sin borrar: lo ya borrado no vuelve. Se salta con `--max-delete -1`.

Aquí viven las dos cosas que tienen que dar la misma respuesta en `sync.py` (la
explicación de la consola, `KNOWN_ERRORS`) y en `common/revision.py` (el hallazgo
de «Reparación» y de `--doctor`): qué agujas reconocen cada freno y qué cifras
trae el log. `sync.py` no importa `ui/` y la ventana no importa `sync.py`; por eso
está en `common/`. Una entrada nueva de esta clase se añade a `ENTRADAS`.

No hace nada con lo que lee: reconocer el freno no autoriza a saltarlo. Eso lo
decide una persona, desde la ventana, para una sola pasada (`ui/repair.py`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

from .model import Pair

BORRADOS = "borrados"
"""bisync paró porque se había borrado más del porcentaje permitido de un lado."""
CAMBIADOS = "cambiados"
"""bisync paró porque ningún fichero de un lado seguía igual que en el listado anterior."""
ESPEJO = "espejo"
"""Un `*-mirror` llegó a su `--max-delete` (una cuenta de ficheros) y rclone paró el resto."""

TOPE_LECTURA = 4 * 1024 * 1024
"""Bytes del final de un log que se leen para reconocer un freno.

El aborto está al final, y un log de miles de ficheros no debe leerse entero cada
vez que la ventana pinta «Reparación».
"""

_BORRADOS = re.compile(
    r"Safety abort: too many deletes \(>(\d+)%, (\d+) of (\d+)\) on (Path[12])\b")
"""La línea de `excessDeletes()`: el tope en %, lo borrado, el listado anterior y el lado."""
_CAMBIADOS = re.compile(r"Safety abort: all files were changed on (Path[12])\b")
"""La línea de `operations.go`; sale una por cada lado en el que cambió todo."""
_FIN_BORRADOS = "Failed to bisync: too many deletes"
"""Lo que rclone devuelve al abortar por borrados, aunque cambie la frase que lo explica."""
_FIN_CAMBIADOS = "Failed to bisync: all files were changed"
"""Lo que rclone devuelve al abortar porque cambiaron todos los ficheros."""
_ESPEJO = "--max-delete threshold reached"
"""El error fatal de `DeleteFile()`. No casa con `--max-delete-size threshold reached`."""
_BORRADO_ESPEJO = re.compile(r": Deleted$", re.M)
"""Una línea `INFO` de un fichero borrado en el destino (con el `--verbose` de fábrica)."""
_PENDIENTES = re.compile(r"failed to delete (\d+) files?\b")
"""Cuántos ficheros se quedaron sin borrar, según rclone."""
_SIMULADO = re.compile(
    r"NOTICE: (.*?): Skipped (?:delete|move into backup dir) as --dry-run is set", re.M)
"""Lo que rclone apunta de cada fichero que una simulación habría borrado.

Con `versions = true` (`--backup-dir1/2`) lo que se borra va al directorio de
versiones y rclone lo apunta como `Skipped move into backup dir` en vez de
`Skipped delete` (`DeleteFileWithBackupDir()`). Lo que solo se sobrescribe es
otra cosa (`Skipped move to <nombre>~<marca>` y `Skipped copy`): no entra.
"""

TOPE_BISYNC_DE_FABRICA = 50
"""El `--max-delete` (un %) que bisync usa cuando no se le da uno válido.

`Options.applyContext()` (`cmd/bisync/cmd.go`) solo atiende un valor `>= 0`: con
`-1` bisync no deja de frenar, vuelve a su `DefaultMaxDelete`.
"""

COMO_FORZAR = "fuerza UNA pasada desde «Reparación» o con `python sync.py <pareja> --force`"
"""Cómo se salta el freno, tal como lo dicen las explicaciones de la consola."""

EXPLICACION_BORRADOS = (
    "Se han borrado más ficheros de un lado de los que permite el freno de bisync, "
    "que es un porcentaje del listado anterior: no se ha propagado nada. Comprueba "
    f"que la ruta local NO esté vacía ni desmontada; si es lo que querías, {COMO_FORZAR}.")
"""Lo que se dice en la consola del freno de bisync por borrados."""
EXPLICACION_CAMBIADOS = (
    "Han cambiado todos los ficheros de un lado desde la última pasada (pasa con un "
    "cambio de hora o al tocar toda la carpeta) y bisync se ha parado para no copiarlo "
    f"todo de nuevo. Si es lo esperado, {COMO_FORZAR}.")
"""Lo que se dice en la consola del freno de bisync por «todos han cambiado»."""
EXPLICACION_ESPEJO = (
    "Un espejo solo puede borrar hasta el tope de su freno (--max-delete, una cuenta "
    "de ficheros) y ha llegado a él: rclone ha parado el resto. Lo ya borrado no vuelve. "
    "Comprueba que la ruta de origen NO esté vacía ni desmontada; si es lo que querías, "
    f"{COMO_FORZAR}.")
"""Lo que se dice en la consola del freno de un espejo."""

LADOS = {"local": "el dispositivo", "remote": "el remoto"}
"""Cómo se nombra cada extremo de una pareja en un texto para la persona."""
HACIA = {"local": "al dispositivo", "remote": "al remoto"}
"""Lo mismo con la preposición, para «copiar eso al remoto»."""


@dataclass(frozen=True)
class Freno:
    """Qué freno paró una pasada y con qué cifras.

    Las cifras que rclone no dio (otra versión, un log sin `--verbose`) quedan en
    `None`: se dice lo que se sabe y nada más.

    Args:
        tipo: `BORRADOS`, `CAMBIADOS` o `ESPEJO`.
        lados: Los extremos afectados (`local` o `remote`, como `Mode.source`).
            En bisync, aquel en el que se borró o cambió todo; en un espejo, su
            destino, que es donde se borra.
        borrados: En bisync, los ficheros borrados en ese lado; en un espejo, los
            que ya se habían borrado cuando rclone paró.
        total: Los ficheros del listado anterior (solo bisync).
        tope: El freno de bisync, en tanto por ciento (solo `BORRADOS`).
        pendientes: Los ficheros que el espejo se quedó sin borrar.
    """
    tipo: str
    lados: tuple[str, ...] = ()
    borrados: int | None = None
    total: int | None = None
    tope: int | None = None
    pendientes: int | None = None

    @property
    def porcentaje(self) -> int | None:
        """Devuelve qué tanto por ciento del listado anterior es lo borrado.

        Redondeado, pero nunca 100 si queda algún fichero: «100 %» dice que ha
        desaparecido todo. `None` si no es un freno de bisync por borrados o
        rclone no dio las cifras.
        """
        if self.tipo != BORRADOS or not self.total or self.borrados is None:
            return None
        pct = round(100 * self.borrados / self.total)
        return pct if self.borrados >= self.total else min(pct, 99)


def es_borrados_bisync(texto: str) -> bool:
    """Indica si el log es el de un aborto de bisync por demasiados borrados."""
    return _BORRADOS.search(texto) is not None or _FIN_BORRADOS in texto


def es_cambiados_bisync(texto: str) -> bool:
    """Indica si el log es el de un aborto de bisync porque cambiaron todos los ficheros."""
    return _CAMBIADOS.search(texto) is not None or _FIN_CAMBIADOS in texto


def es_espejo(texto: str) -> bool:
    """Indica si el log es el de un `sync` que paró en su `--max-delete`."""
    return _ESPEJO in texto


EXPLICACION_LLAVERO = (
    "El freno de borrados del llavero no se salta: sus bases son tus contraseñas. Comprueba "
    "que no falte ninguna en un lado y, si hay copias de conflicto, usa «Combinar» al abrir "
    "el llavero.")
"""Lo que se dice en la consola cuando es el llavero el que ha topado con un freno de borrados."""
SALIDA_LLAVERO_CAMBIADOS = (
    "prdrive ya ha repetido la pasada una vez con --force (lo que pisa cada lado queda en "
    ".prversions/) y ha vuelto a pararse. Lo que guardes en el llavero no sube mientras tanto. "
    "Desde aquí no se fuerza: `python sync.py keychain --resync` rehace la referencia y se queda "
    "con la base más nueva, y la otra queda en .prversions/.")
"""Qué pasa y qué hacer cuando al llavero lo para «han cambiado todos» aun después de repetirlo."""
EXPLICACION_LLAVERO_CAMBIADOS = (
    "Han cambiado todos los ficheros de un lado del llavero (suele ser la hora de un dispositivo "
    f"nuevo o de otra versión) y bisync se ha parado. {SALIDA_LLAVERO_CAMBIADOS}")
"""Lo que se dice en la consola cuando es el llavero el que ha topado con «han cambiado todos»."""


def explicacion_llavero(explicacion: str) -> str:
    """Devuelve lo que se le dice del llavero en lugar de `explicacion`, la de un freno.

    Las de `EXPLICACIONES` dicen cómo forzar la pasada, y al llavero no se le fuerza desde
    fuera (`se_puede_forzar()`). Cada freno tiene la suya; el de borrados es la general.
    """
    return (EXPLICACION_LLAVERO_CAMBIADOS if explicacion == EXPLICACION_CAMBIADOS
            else EXPLICACION_LLAVERO)


def salida_llavero(tipo: str) -> str:
    """Devuelve lo que `revision` dice que se haga cuando el freno `tipo` ha parado al llavero.

    Es lo mismo que la consola, sin la frase de qué ha pasado: el hallazgo ya la lleva
    (`revision._frase_freno()`).
    """
    return SALIDA_LLAVERO_CAMBIADOS if tipo == CAMBIADOS else EXPLICACION_LLAVERO

ENTRADAS = [
    (es_borrados_bisync, EXPLICACION_BORRADOS),
    (es_cambiados_bisync, EXPLICACION_CAMBIADOS),
    (es_espejo, EXPLICACION_ESPEJO),
]
"""Las entradas que `sync.KNOWN_ERRORS` toma de aquí: una aguja y su explicación."""
EXPLICACIONES = tuple(explicacion for _, explicacion in ENTRADAS)
"""Las explicaciones de `ENTRADAS`: las que dicen cómo forzar y no valen para el llavero."""


def tiene_freno(pair: Pair) -> bool:
    """Indica si el modo de esa pareja tiene un freno de borrados que se pueda saltar.

    bisync y los espejos (`sync`); un `copy` no borra y no tiene nada que forzar.
    """
    return pair.is_bisync or pair.mode.verb == "sync"


def se_puede_forzar(pair: Pair) -> bool:
    """Indica si a esa pareja se le puede saltar el freno de borrados en una pasada.

    Si tiene freno (`tiene_freno()`) y no es la del llavero: sus bases son
    contraseñas, y su salida cuando algo se borra es «Combinar», no `--force`.
    Es la única regla: la orden de rclone, el aviso de `sync.py`, su línea de
    órdenes y «Reparación» la comparten.
    """
    return tiene_freno(pair) and not pair.llavero


def _lado(pair: Pair, camino: str) -> str:
    """Devuelve a qué extremo de la pareja llama bisync `Path1` o `Path2`.

    bisync recibe los extremos en el orden de la orden de rclone: origen del modo
    (`local`) y destino (`remote`).
    """
    return pair.mode.source if camino == "Path1" else pair.mode.dest


def _de_bisync(texto: str, pair: Pair) -> Freno | None:
    """Devuelve el freno de bisync que paró la pasada, o `None`."""
    m = _BORRADOS.search(texto)
    if m is not None:
        return Freno(BORRADOS, (_lado(pair, m[4]),), int(m[2]), int(m[3]), int(m[1]))
    if _FIN_BORRADOS in texto:
        return Freno(BORRADOS)
    lados = tuple(dict.fromkeys(_lado(pair, m[1]) for m in _CAMBIADOS.finditer(texto)))
    if lados or _FIN_CAMBIADOS in texto:
        return Freno(CAMBIADOS, lados)
    return None


def _de_espejo(texto: str, pair: Pair) -> Freno | None:
    """Devuelve el freno del espejo que paró la pasada, o `None`."""
    if not es_espejo(texto):
        return None
    pendientes = _PENDIENTES.findall(texto)
    return Freno(ESPEJO, (pair.mode.dest,),
                 borrados=len(_BORRADO_ESPEJO.findall(texto)) or None,
                 pendientes=int(pendientes[-1]) if pendientes else None)


def detectar(texto: str, pair: Pair) -> Freno | None:
    """Devuelve el freno de borrados que paró esa pasada, o `None` si falló por otra cosa.

    Cada freno es de su modo: el de bisync solo se busca en una pareja bisync y el
    de un espejo solo en un `up-mirror` o `down-mirror`. Un `copy` no borra y no
    tiene freno que reconocer. Un log de bisync en una pareja que no lo es (o al
    revés) no se reconoce: sería un diagnóstico sobre algo que esa pareja no hizo.

    Args:
        texto: El log de la pasada.
        pair: La pareja que lo escribió.
    """
    if pair.is_bisync:
        return _de_bisync(texto, pair)
    if tiene_freno(pair):
        return _de_espejo(texto, pair)
    return None


def borrarian(texto: str) -> list[str]:
    """Devuelve los ficheros que una simulación (`--dry-run`) habría borrado.

    Sin repetir y en orden alfabético: rclone los apunta en el orden en que sus
    hilos llegan a ellos, que cambia de una vez a otra.

    Args:
        texto: El log de la simulación.
    """
    return sorted(set(_SIMULADO.findall(texto)))


def leer(log: Path, *, completo: bool = False) -> str:
    """Lee un log: el final (`TOPE_LECTURA` bytes como mucho) o, con `completo`, entero.

    Lo que se mira al pintar una ventana se lee por el final; lo que una persona va
    a usar para decidir (cuántos ficheros borraría una simulación) se lee entero.

    Args:
        log: El log.
        completo: Si se lee entero, pese a lo que pese.

    Raises:
        OSError: Si no se puede abrir o leer (el dispositivo ha desaparecido).
    """
    with log.open("rb") as f:
        tam = f.seek(0, 2)
        f.seek(0 if completo else max(0, tam - TOPE_LECTURA))
        datos = f.read()
    return datos.decode("utf-8", errors="replace").replace("\r\n", "\n")


def detectar_en(log: Path, pair: Pair) -> Freno | None:
    """Devuelve el freno que paró la pasada de ese log, leyendo solo su final.

    Lo que el final del log dice entero (el aborto de bisync con sus cifras, los
    ficheros que un espejo se dejó sin borrar) se reconoce igual. Lo que sale de
    contar líneas de todo el log, cuántos ficheros había borrado ya un espejo, no
    se puede decir si el log pesa más de lo que se leyó: queda en `None` y no se
    da un número que sea solo el de la última parte.

    Raises:
        OSError: Si no se puede leer el log.
    """
    freno = detectar(leer(log), pair)
    if freno is not None and freno.tipo == ESPEJO and log.stat().st_size > TOPE_LECTURA:
        return replace(freno, borrados=None)
    return freno


def nombre_lado(lado: str) -> str:
    """Devuelve cómo se nombra ese extremo en un texto: «el dispositivo» o «el remoto»."""
    return LADOS.get(lado, "el otro lado")


def hacia(lado: str) -> str:
    """Devuelve ese extremo como destino de algo: «al dispositivo» o «al remoto»."""
    return HACIA.get(lado, "al otro lado")


def otro_lado(lado: str) -> str:
    """Devuelve el extremo contrario: `local` ↔ `remote`."""
    return "remote" if lado == "local" else "local"
