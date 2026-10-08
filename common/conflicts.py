#!/usr/bin/env python3
"""Los ficheros en conflicto que deja bisync, vistos desde el dispositivo.

Cuando un mismo fichero cambia en los dos lados entre dos pasadas, bisync no
elige en silencio: con `--conflict-resolve newer` se queda con el más reciente,
renombra al otro con un sufijo y copia los dos a los dos lados. Solo queda una
línea en el log de rclone (que se borra si la pasada fue bien) y un fichero con
un nombre raro que nadie mira, mientras las dos versiones siguen separándose.

Este módulo encuentra esos ficheros y dice de qué lado viene cada uno. No
decide nada ni toca ninguno: resolver es cosa de `ui/conflict_editor.py`.

El estado es DERIVADO: `state/conflicts.json` solo guarda lo que encontró el
último recorrido, para pintar la ventana sin recorrer el árbol; al leerlo se
comprueba que cada fichero sigue ahí, así que el aviso desaparece cuando
desaparecen los ficheros, los borre quien los borre.

Réplica de rclone, como `bisync.py`: el nombre del perdedor lo decide
cmd/bisync/resolve.go (`setResolveDefaults`, `resolve`, `SuffixName`) y la
posición del sufijo lib/transform/transform.go (`SuffixKeepExtension`). Se lee
de los flags YA FUNDIDOS de la pareja, que es lo que recibe rclone.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterator, NamedTuple

from . import huella, model, store
from .model import Config, Pair

DISPOSITIVO = "dispositivo"
REMOTO = "remoto"

SUFIJO_RCLONE = "conflict"
"""Sufijo de conflicto que rclone pone por defecto (`setResolveDefaults`).

Se sigue reconociendo aunque la pareja lleve otros: son los de conflictos
anteriores al cambio, que siguen ahí hasta que alguien los resuelva.
"""
PERDEDOR_RCLONE = "num"
"""Valor por defecto de `--conflict-loser` (`setResolveDefaults`)."""


def ruta_estado() -> Path:
    """Devuelve la ruta de `state/conflicts.json`.

    Es función y no constante porque los tests cambian `model.STATE_DIR` al
    vuelo.
    """
    return model.STATE_DIR / "conflicts.json"


class Esquema(NamedTuple):
    """Cómo nombra rclone a los perdedores de una pareja concreta.

    Args:
        sufijo1: Sufijo de path1, ya con su punto delante.
        sufijo2: Sufijo de path2.
        perdedor: Valor de `--conflict-loser`: `num`, `pathname` o `delete`.
        mantener_extension: Valor de `--suffix-keep-extension`.
    """
    sufijo1: str
    sufijo2: str
    perdedor: str
    mantener_extension: bool


def _flag(pair: Pair, nombre: str):
    """Devuelve un flag de la pareja, con guiones o con guiones bajos.

    Los dos acaban siendo el mismo argumento (`model.flags_to_args`). Si están
    los dos (el modo trae `conflict-suffix` y la pareja escribe
    `conflict_suffix`), rclone recibe el flag dos veces y se queda con el
    último, que es el que va más tarde en el diccionario fundido.
    """
    valor = None
    for clave, v in pair.flags.items():
        if str(clave).replace("_", "-") == nombre:
            valor = v
    return valor


def esquema(pair: Pair) -> Esquema:
    """Calcula el esquema de nombres de conflicto de una pareja.

    Replica `setResolveDefaults()`: un sufijo vale para los dos lados; dos
    separados por coma son uno para cada uno; a los dos se les pone un punto
    delante. Los comodines de fecha (`{DateOnly}`…) no se pueden deshacer desde
    el nombre, así que una pareja que los use verá sus conflictos sin lado.

    Una pareja con `versions` lleva siempre `--suffix-keep-extension`: no está
    en sus flags, lo pone `sync.build_command()`. Importa en el llavero, cuyo
    perdedor se queda al lado (`conflict-loser = num`) como
    `personal.conflicto-remoto1.kdbx`.
    """
    crudo = str(_flag(pair, "conflict-suffix") or SUFIJO_RCLONE)
    partes = [p for p in crudo.split(",") if p] or [SUFIJO_RCLONE]
    s1, s2 = (partes[0], partes[0]) if len(partes) == 1 else (partes[0], partes[1])
    return Esquema(sufijo1="." + s1, sufijo2="." + s2,
                   perdedor=str(_flag(pair, "conflict-loser") or PERDEDOR_RCLONE),
                   mantener_extension=bool(_flag(pair, "suffix-keep-extension"))
                   or pair.versions)


def _patron(sufijo: str, mantener_extension: bool) -> re.Pattern:
    """Devuelve el patrón de nombre de un perdedor.

    `SuffixName` pone el sufijo al final (`plan.md.conflict1`) o, con
    `--suffix-keep-extension`, delante de la extensión (`plan.conflict1.md`).
    """
    extension = r"(?P<ext>(?:\.[^.]+)+)" if mantener_extension else r"(?P<ext>)"
    return re.compile(rf"^(?P<base>.+){re.escape(sufijo)}(?P<n>\d*){extension}$")


def leer_nombre(nombre: str, esq: Esquema) -> tuple[str, str | None, int] | None:
    """Interpreta el nombre de un fichero como el de un perdedor de conflicto.

    Qué significa el número depende del esquema, y es justo lo que hay que
    acertar (ver `resolve()`):
    - sufijos distintos: el sufijo es el lado y el número solo un orden;
    - un sufijo y `--conflict-loser pathname`: `1` es path1 y `2` es path2;
    - un sufijo y `--conflict-loser num`: el número es el primero que estaba
      libre (`numerate`), así que el lado no se sabe.

    Returns:
        `(nombre original, 'path1' | 'path2' | None, número)`, o `None` si no
        es un conflicto.
    """
    candidatos = [esq.sufijo1, esq.sufijo2, "." + SUFIJO_RCLONE]
    # Todo patrón exige su sufijo literal: sin ninguno no hay nada que compilar.
    if not any(sufijo in nombre for sufijo in candidatos):
        return None
    for sufijo in dict.fromkeys(candidatos):  # sin repetir, en orden
        m = _patron(sufijo, esq.mantener_extension).match(nombre)
        if m is None:
            continue
        original = m["base"] + m["ext"]
        numero = int(m["n"]) if m["n"] else 0
        if esq.sufijo1 != esq.sufijo2 and sufijo in (esq.sufijo1, esq.sufijo2):
            return original, ("path1" if sufijo == esq.sufijo1 else "path2"), numero
        if not m["n"]:
            continue  # un solo sufijo sin número no lo escribe rclone
        if sufijo == esq.sufijo1 and esq.perdedor == "pathname" and numero in (1, 2):
            return original, f"path{numero}", numero
        return original, None, numero
    return None


def lado(pair: Pair, camino: str | None) -> str | None:
    """Traduce `path1`/`path2` a este dispositivo o el remoto.

    En bisync path1 es el primer extremo de la orden (`sync.build_command` pone
    `pair.source` delante) y ese es el lado local según `model.MODES`.

    Returns:
        `DISPOSITIVO` o `REMOTO`; `None` si el camino se desconoce.
    """
    if camino is None:
        return None
    extremo = pair.mode.source if camino == "path1" else pair.mode.dest
    return DISPOSITIVO if extremo == "local" else REMOTO


class Version(NamedTuple):
    """Uno de los ficheros de un conflicto.

    Args:
        ruta: Dónde está el fichero.
        lado: `DISPOSITIVO`, `REMOTO` o `None` si no se sabe.
        es_original: Si tiene el nombre de verdad.
        numero: El número del sufijo, o 0 si no lleva.
    """
    ruta: Path
    lado: str | None
    es_original: bool
    numero: int = 0


class Conflicto(NamedTuple):
    """Un fichero con más de una versión en disco.

    Args:
        pareja: Nombre de la pareja.
        raiz: La carpeta local de la pareja.
        original: El nombre de verdad, que puede no existir.
        versiones: Todas las versiones, el original primero si existe.
    """
    pareja: str
    raiz: Path
    original: Path
    versiones: tuple[Version, ...]

    @property
    def relativa(self) -> str:
        """Devuelve la ruta que se enseña: dentro de la pareja y con barras normales."""
        try:
            return self.original.relative_to(self.raiz).as_posix()
        except ValueError:
            return self.original.as_posix()

    @property
    def copias(self) -> tuple[Path, ...]:
        """Devuelve los ficheros con sufijo, que son los que hay que quitar.

        Para resolver el conflicto tienen que desaparecer.
        """
        return tuple(v.ruta for v in self.versiones if not v.es_original)

    def version(self, cual: str) -> Version | None:
        """Devuelve LA versión de ese lado.

        Dos copias del mismo lado son dos conflictos seguidos sin resolver en
        medio: las dos son «de este dispositivo», de momentos distintos, y
        elegir una por su cuenta sería decidir por el usuario.

        Returns:
            La versión, o `None` si el lado tiene cero o más de una.
        """
        del_lado = [v for v in self.versiones if v.lado == cual]
        return del_lado[0] if len(del_lado) == 1 else None


def _agrupar(pair: Pair, copias: list[Path]) -> list[Conflicto]:
    """Junta las copias con su original.

    El lado del original se deduce: tras un conflicto con ganador, rclone deja
    el ganador con el nombre de verdad y renombra al perdedor (`resolve()`,
    caso winningPath 1 o 2), así que si hay UNA copia de un lado el original es
    la versión del otro. Con varias copias, o con alguna sin lado, ya no se
    puede afirmar y el original se queda sin lado: una etiqueta inventada es
    peor que ninguna.
    """
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
    """Indica si es un fichero, sin lanzar."""
    try:
        return ruta.is_file()
    except OSError:
        return False


def recorrer(raiz: Path, ignorar: tuple[str, ...] = ()) -> Iterator[Path]:
    """Recorre los ficheros bajo `raiz`, sin entrar en lo que se ignora de su primer nivel.

    Es de módulo para que un test la sustituya. Usa `os.walk` y no `Path.rglob`
    porque se salta sin ruido lo que no puede leer (una carpeta sin permiso, el
    dispositivo que desaparece a medias), que es lo que se quiere de un
    recorrido que solo busca avisos.

    Args:
        raiz: Carpeta que se recorre.
        ignorar: Patrones de `fnmatch` en minúsculas (`huella.se_ignora`). Solo
            se miran las entradas que cuelgan directamente de `raiz`, carpetas y
            ficheros: una carpeta ignorada no se abre, y lo que se llame igual
            más adentro es contenido de quien lo puso.

    Yields:
        La ruta de cada fichero.
    """
    en_la_raiz = True
    for carpeta, subcarpetas, ficheros in os.walk(raiz):
        if en_la_raiz and ignorar:
            subcarpetas[:] = [d for d in subcarpetas if not huella.se_ignora(d, ignorar)]
            ficheros = [f for f in ficheros if not huella.se_ignora(f, ignorar)]
        en_la_raiz = False
        for nombre in ficheros:
            yield Path(carpeta) / nombre


def _ignorados(pair: Pair) -> tuple[str, ...]:
    """Devuelve lo que cuelga de la carpeta de la pareja y no es suyo, en minúsculas.

    `.prversions/` guarda versiones, no conflictos. Si la pareja sincroniza la
    raíz entera del dispositivo, tampoco son suyos el programa (`.prdrive/`), el
    llavero (`.keychain/`, que tiene su propia pareja) ni el ruido que el sistema
    deja en un volumen (`model.RUIDO_DEL_SISTEMA`).
    """
    patrones = (model.VERSIONS_DIR,)
    if pair.es_raiz:
        patrones += (model.APP_DIR.name, model.LLAVERO_LOCAL) + model.RUIDO_DEL_SISTEMA
    return tuple(p.lower() for p in patrones)


def escanear(pair: Pair) -> list[Conflicto]:
    """Devuelve los conflictos de una pareja, recorriendo su carpeta local.

    Solo bisync deja conflictos: los demás modos copian en un sentido. No se
    entra en lo que la pareja no sincroniza (`_ignorados()`).
    """
    if not pair.is_bisync or not pair.local_abs.is_dir():
        return []
    esq = esquema(pair)
    copias = [ruta for ruta in recorrer(pair.local_abs, _ignorados(pair))
              if leer_nombre(ruta.name, esq) is not None]
    return _agrupar(pair, copias)


def _relativa(ruta: Path) -> str:
    """Devuelve la ruta relativa a la raíz del dispositivo.

    La letra de unidad cambia de un equipo a otro y el fichero viaja con el
    dispositivo.
    """
    try:
        return ruta.relative_to(model.DEVICE_ROOT).as_posix()
    except ValueError:
        return ruta.as_posix()


def _guardar(parejas: dict[str, list[Conflicto]], data: dict | None = None) -> None:
    """Escribe en `state/conflicts.json` las copias encontradas de esas parejas.

    Si lo que quedaría escrito es lo que ya hay en disco no escribe nada: cada
    pasada vuelve a apuntar su recorrido y casi siempre es el mismo.

    Args:
        parejas: Conflictos por pareja.
        data: Estado previo con el que mezclar; por defecto, el que hay en
            disco. Pasar `{}` descarta las parejas que no estén en `parejas`.
    """
    en_disco = store.read_json(ruta_estado()).get("parejas")
    en_disco = en_disco if isinstance(en_disco, dict) else {}
    if data is None:
        previas = en_disco
    else:
        previas = data.get("parejas") if isinstance(data.get("parejas"), dict) else {}
    guardadas = dict(previas)
    for nombre, encontrados in parejas.items():
        guardadas[nombre] = [_relativa(copia) for x in encontrados for copia in x.copias]
    if guardadas == en_disco:
        return
    store.write_json(ruta_estado(), {"cuando": store.stamp(), "parejas": guardadas})


def actualizar_pareja(pair: Pair) -> list[Conflicto]:
    """Escanea una pareja y apunta el resultado; lo llama `sync.py` tras cada pasada."""
    encontrados = escanear(pair)
    _guardar({pair.name: encontrados})
    return encontrados


def refrescar(config: Config) -> dict[str, list[Conflicto]]:
    """Escanea todas las parejas y rehace el estado entero.

    Lo reescribe solo si ha cambiado. Las que ya no están en el config se caen
    de él.
    """
    todos = {pair.name: escanear(pair) for pair in config.pairs if pair.is_bisync}
    _guardar(todos, data={})
    return todos


def cargar(config: Config) -> dict[str, list[Conflicto]]:
    """Devuelve lo del último escaneo, sin recorrer nada.

    Solo se mira que cada copia siga existiendo. Es lo que pinta la ventana
    nada más abrirse.
    """
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
    """Devuelve cuántos conflictos tiene cada pareja, solo las que tienen alguno."""
    return {nombre: len(lista) for nombre, lista in por_pareja.items() if lista}
