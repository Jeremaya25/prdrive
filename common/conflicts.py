#!/usr/bin/env python3
"""
conflicts.py — Los ficheros en conflicto que deja bisync, vistos desde el dispositivo.

Cuando un mismo fichero cambia en los dos lados entre dos pasadas, bisync no
elige en silencio: con `--conflict-resolve newer` se queda con el más reciente y
al otro le cambia el nombre (le añade un sufijo), y copia los dos a los dos
lados. Eso es todo lo que queda: una línea en el log de rclone, que se borra si
la pasada fue bien, y un fichero con un nombre raro que nadie mira. Mientras
tanto las dos versiones siguen separándose.

Este módulo encuentra esos ficheros y dice de qué lado viene cada uno. No
decide nada ni toca ninguno: resolver es cosa de `ui/conflict_editor.py`.

El estado es DERIVADO. Lo que se guarda en `state/conflicts.json` es solo lo
que encontró el último recorrido, para poder pintar la ventana sin recorrer el
árbol entero; al leerlo se comprueba que cada fichero sigue ahí, así que en
cuanto desaparecen los ficheros desaparece el aviso, lo borre quien lo borre.

Réplica de rclone, como `bisync.py`: el nombre del perdedor lo decide
cmd/bisync/resolve.go (`setResolveDefaults`, `resolve`, `SuffixName`) y la
posición del sufijo lib/transform/transform.go (`SuffixKeepExtension`). Se lee
de los flags YA FUNDIDOS de la pareja, que es exactamente lo que recibe rclone.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterator, NamedTuple

from . import model, store
from .model import Config, Pair

DISPOSITIVO = "dispositivo"
REMOTO = "remoto"

# Lo que rclone pone si no se le dice nada (setResolveDefaults). Aunque la
# pareja lleve otros sufijos, estos se siguen reconociendo: son los de los
# conflictos que ya había antes de cambiarlos, y siguen ahí hasta que alguien
# los resuelva.
SUFIJO_RCLONE = "conflict"
PERDEDOR_RCLONE = "num"


def ruta_estado() -> Path:
    """Función y no constante: los tests cambian `model.STATE_DIR` al vuelo."""
    return model.STATE_DIR / "conflicts.json"


# ---------------------------------------------------------------------------
# El nombre del perdedor
# ---------------------------------------------------------------------------

class Esquema(NamedTuple):
    """Cómo nombra rclone a los perdedores de una pareja concreta."""
    sufijo1: str             # el de path1, ya con su punto delante
    sufijo2: str             # el de path2
    perdedor: str            # --conflict-loser: 'num' | 'pathname' | 'delete'
    mantener_extension: bool  # --suffix-keep-extension


def _flag(pair: Pair, nombre: str):
    """Un flag de la pareja escrito con guiones o con guiones bajos: los dos
    acaban siendo el mismo argumento (`model.flags_to_args`). Si están los dos
    —el modo trae `conflict-suffix` y la pareja escribe `conflict_suffix`—,
    rclone recibe el flag dos veces y se queda con el último, que es el que va
    más tarde en el diccionario fundido."""
    valor = None
    for clave, v in pair.flags.items():
        if str(clave).replace("_", "-") == nombre:
            valor = v
    return valor


def esquema(pair: Pair) -> Esquema:
    """Lo que hace `setResolveDefaults()`: un sufijo vale para los dos lados, dos
    separados por coma son uno para cada uno, y a los dos se les pone un punto
    delante. Los comodines de fecha (`{DateOnly}`…) no se pueden deshacer desde
    el nombre, así que una pareja que los use verá sus conflictos sin lado."""
    crudo = str(_flag(pair, "conflict-suffix") or SUFIJO_RCLONE)
    partes = [p for p in crudo.split(",") if p] or [SUFIJO_RCLONE]
    s1, s2 = (partes[0], partes[0]) if len(partes) == 1 else (partes[0], partes[1])
    return Esquema(sufijo1="." + s1, sufijo2="." + s2,
                   perdedor=str(_flag(pair, "conflict-loser") or PERDEDOR_RCLONE),
                   mantener_extension=bool(_flag(pair, "suffix-keep-extension")))


def _patron(sufijo: str, mantener_extension: bool) -> re.Pattern:
    """`SuffixName` pone el sufijo al final (`plan.md.conflict1`) o, con
    --suffix-keep-extension, delante de la extensión (`plan.conflict1.md`)."""
    extension = r"(?P<ext>(?:\.[^.]+)+)" if mantener_extension else r"(?P<ext>)"
    return re.compile(rf"^(?P<base>.+){re.escape(sufijo)}(?P<n>\d*){extension}$")


def leer_nombre(nombre: str, esq: Esquema) -> tuple[str, str | None, int] | None:
    """(nombre original, 'path1'|'path2'|None, número) o None si no es un conflicto.

    Qué significa el número depende del esquema, y es justo lo que hay que
    acertar (ver `resolve()`):

      * sufijos distintos: el sufijo es el lado, el número solo un orden;
      * un sufijo y --conflict-loser pathname: `1` es path1 y `2` es path2;
      * un sufijo y --conflict-loser num: el número es el primero que estaba
        libre (`numerate`), así que el lado no se sabe.
    """
    candidatos = [esq.sufijo1, esq.sufijo2, "." + SUFIJO_RCLONE]
    for sufijo in dict.fromkeys(candidatos):          # sin repetir, en orden
        m = _patron(sufijo, esq.mantener_extension).match(nombre)
        if m is None:
            continue
        original = m["base"] + m["ext"]
        numero = int(m["n"]) if m["n"] else 0
        if esq.sufijo1 != esq.sufijo2 and sufijo in (esq.sufijo1, esq.sufijo2):
            return original, ("path1" if sufijo == esq.sufijo1 else "path2"), numero
        if not m["n"]:
            continue              # un solo sufijo sin número no lo escribe rclone
        if sufijo == esq.sufijo1 and esq.perdedor == "pathname" and numero in (1, 2):
            return original, f"path{numero}", numero
        return original, None, numero
    return None


def lado(pair: Pair, camino: str | None) -> str | None:
    """'path1'/'path2' traducido a este dispositivo / el remoto.

    En bisync path1 es el primer extremo de la orden (`sync.build_command` pone
    `pair.source` delante), y ese es el lado local según `model.MODES`."""
    if camino is None:
        return None
    extremo = pair.mode.source if camino == "path1" else pair.mode.dest
    return DISPOSITIVO if extremo == "local" else REMOTO


# ---------------------------------------------------------------------------
# Los conflictos
# ---------------------------------------------------------------------------

class Version(NamedTuple):
    """Uno de los ficheros de un conflicto."""
    ruta: Path
    lado: str | None          # DISPOSITIVO | REMOTO | None = no se sabe
    es_original: bool         # el que tiene el nombre de verdad
    numero: int = 0


class Conflicto(NamedTuple):
    """Un fichero con más de una versión en disco."""
    pareja: str
    raiz: Path                # la carpeta local de la pareja
    original: Path            # el nombre de verdad (puede no existir)
    versiones: tuple[Version, ...]

    @property
    def relativa(self) -> str:
        """La ruta que se enseña: dentro de la pareja y con barras normales."""
        try:
            return self.original.relative_to(self.raiz).as_posix()
        except ValueError:
            return self.original.as_posix()

    @property
    def copias(self) -> tuple[Path, ...]:
        """Los ficheros con sufijo: lo que tiene que desaparecer para resolverlo."""
        return tuple(v.ruta for v in self.versiones if not v.es_original)

    def version(self, cual: str) -> Version | None:
        """LA versión de ese lado, o None si no hay una sola.

        Dos copias del mismo lado son dos conflictos seguidos sin resolver en
        medio: las dos son «de este dispositivo», de momentos distintos, y
        elegir una por su cuenta sería decidir por el usuario."""
        del_lado = [v for v in self.versiones if v.lado == cual]
        return del_lado[0] if len(del_lado) == 1 else None


def _agrupar(pair: Pair, copias: list[Path]) -> list[Conflicto]:
    """Las copias, juntadas con su original.

    El lado del original se deduce: tras un conflicto con ganador, rclone deja
    el ganador con el nombre de verdad y renombra al perdedor (`resolve()`, caso
    winningPath 1 o 2), así que si hay UNA copia de un lado, el original es la
    versión del otro. Con varias copias, o con alguna sin lado, eso ya no se
    puede afirmar y el original se queda sin lado: una etiqueta inventada es
    peor que ninguna."""
    esq = esquema(pair)
    grupos: dict[Path, list[Version]] = {}
    for ruta in copias:
        leido = leer_nombre(ruta.name, esq)
        if leido is None:
            continue
        nombre, camino, numero = leido
        grupos.setdefault(ruta.with_name(nombre), []).append(
            Version(ruta, lado(pair, camino), False, numero))

    salida = []
    for original, versiones in sorted(grupos.items()):
        versiones.sort(key=lambda v: (v.lado or "~", v.numero, v.ruta.name))
        if _existe(original):
            lados = {v.lado for v in versiones}
            deducido = None
            if len(versiones) == 1 and None not in lados:
                deducido = REMOTO if versiones[0].lado == DISPOSITIVO else DISPOSITIVO
            versiones.insert(0, Version(original, deducido, True))
        salida.append(Conflicto(pair.name, pair.local_abs, original, tuple(versiones)))
    return salida


def _existe(ruta: Path) -> bool:
    try:
        return ruta.is_file()
    except OSError:
        return False


def recorrer(raiz: Path) -> Iterator[Path]:
    """Todos los ficheros bajo `raiz`. De módulo para que un test la sustituya.

    `os.walk` y no `Path.rglob`: se salta sin ruido lo que no puede leer (una
    carpeta sin permiso, el dispositivo que desaparece a medias), y eso es lo
    que se quiere de un recorrido que solo busca avisos."""
    for carpeta, _subcarpetas, ficheros in os.walk(raiz):
        for nombre in ficheros:
            yield Path(carpeta) / nombre


def escanear(pair: Pair) -> list[Conflicto]:
    """Los conflictos de una pareja, recorriendo su carpeta local.

    Solo bisync deja conflictos: los demás modos copian en un sentido."""
    if not pair.is_bisync or not pair.local_abs.is_dir():
        return []
    esq = esquema(pair)
    copias = [ruta for ruta in recorrer(pair.local_abs)
              if leer_nombre(ruta.name, esq) is not None]
    return _agrupar(pair, copias)


# ---------------------------------------------------------------------------
# Lo que se recuerda entre una ventana y la siguiente
# ---------------------------------------------------------------------------

def _relativa(ruta: Path) -> str:
    """Relativa a la raíz del dispositivo: la letra de unidad cambia de un equipo
    a otro y el fichero viaja con el dispositivo."""
    try:
        return ruta.relative_to(model.DEVICE_ROOT).as_posix()
    except ValueError:
        return ruta.as_posix()


def _guardar(parejas: dict[str, list[Conflicto]], data: dict | None = None) -> None:
    data = data if data is not None else store.read_json(ruta_estado())
    guardadas = data.get("parejas") if isinstance(data.get("parejas"), dict) else {}
    for nombre, encontrados in parejas.items():
        guardadas[nombre] = [_relativa(copia) for x in encontrados for copia in x.copias]
    store.write_json(ruta_estado(), {"cuando": store.stamp(), "parejas": guardadas})


def actualizar_pareja(pair: Pair) -> list[Conflicto]:
    """Escanea una pareja y apunta el resultado. Lo llama sync.py tras cada pasada."""
    encontrados = escanear(pair)
    _guardar({pair.name: encontrados})
    return encontrados


def refrescar(config: Config) -> dict[str, list[Conflicto]]:
    """Escanea todas las parejas y reescribe el estado entero: las que ya no
    están en el config se caen de él."""
    todos = {pair.name: escanear(pair) for pair in config.pairs if pair.is_bisync}
    _guardar(todos, data={})
    return todos


def cargar(config: Config) -> dict[str, list[Conflicto]]:
    """Lo del último escaneo, sin recorrer nada: solo se mira que cada copia
    siga existiendo. Es lo que pinta la ventana nada más abrirse."""
    guardadas = store.read_json(ruta_estado()).get("parejas")
    if not isinstance(guardadas, dict):
        guardadas = {}
    salida: dict[str, list[Conflicto]] = {}
    for pair in config.pairs:
        if not pair.is_bisync:
            continue
        rutas = guardadas.get(pair.name)
        copias = [model.DEVICE_ROOT / r for r in rutas if isinstance(r, str)] \
            if isinstance(rutas, list) else []
        salida[pair.name] = _agrupar(pair, [p for p in copias if _existe(p)])
    return salida


def contar(por_pareja: dict[str, list[Conflicto]]) -> dict[str, int]:
    """Cuántos conflictos tiene cada pareja, solo las que tienen alguno."""
    return {nombre: len(lista) for nombre, lista in por_pareja.items() if lista}
