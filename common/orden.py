#!/usr/bin/env python3
"""La orden de rclone de una pareja, en trozos que dicen quién pone cada uno.

`sync.build_command()` monta con esto la orden que ejecuta, y la vista previa
del editor de flags la monta con esto mismo: no hay una copia que pueda
desviarse. Vive en `common/` y no en `sync.py` por lo mismo que
`model.flags_to_args()`: la UI tiene que poder enseñar la orden sin importar el
motor, y no puede construirla por su cuenta.

Un trozo (`Tramo`) es un flag con su valor, una regla de filtrado, un argumento
extra o el comienzo de la orden, y lleva la capa de la que sale. Los de las
cuatro capas de flags vienen de `model.flags_efectivos()`; lo que añade el
programa en cada pasada y no se configura (`--config`, `--log-file`,
`--workdir`, `--resync`, el versionado…) sale como `model.ORIGEN_PRDRIVE`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, NamedTuple

from . import frenos, model
from .model import FlagEfectivo, Pair


class Tramo(NamedTuple):
    """Un trozo de la orden de rclone y quién lo pone.

    Args:
        args: Los argumentos que aporta, tal como van a la línea de comandos.
        origen: Quién lo pone (`model.ORIGEN_*`).
        nombre: El flag, sin guiones y como está escrito, si el trozo es uno de
            la cascada o de los que pone el programa; `None` en el resto.
    """
    args: tuple[str, ...]
    origen: str
    nombre: str | None = None


def tramos_de_filtrado(pair: Pair, ffile: Path | None) -> list[Tramo]:
    """Devuelve los trozos de filtrado de la pareja.

    Con fichero de filtros no se emiten `--include` ni `--exclude`: se
    duplicarían las reglas y bisync dejaría de poder detectar cambios de
    filtrado. Las reglas del código (`Pair.reglas`) las pone el programa; los
    patrones de la pareja son suyos.

    Args:
        pair: La pareja.
        ffile: Su fichero de filtros, o `None` si no lo usa.
    """
    if ffile is not None:
        return [Tramo(("--filters-file", str(ffile)), model.ORIGEN_PRDRIVE)]
    tramos: list[Tramo] = []
    # Las reglas del código (`Pair.reglas`) salen como `--include`/`--exclude`.
    # Aquí no pueden ir delante de las de la pareja: rclone añade siempre los
    # `--include` antes que los `--exclude` (`fs/filter/filter.go`, `NewFilter`).
    for regla in pair.reglas:
        signo, _, patron = regla.partition(" ")
        tramos.append(Tramo(("--include" if signo == "+" else "--exclude", patron),
                            model.ORIGEN_PRDRIVE))
    for pattern in pair.includes:
        tramos.append(Tramo(("--include", pattern), model.ORIGEN_PATRONES))
    for pattern in pair.excludes:
        tramos.append(Tramo(("--exclude", pattern), model.ORIGEN_PATRONES))
    return tramos


def filter_args(pair: Pair, ffile: Path | None) -> list[str]:
    """Devuelve los argumentos de filtrado de la pareja (`tramos_de_filtrado()`, aplanados)."""
    return [a for t in tramos_de_filtrado(pair, ffile) for a in t.args]


def _es_flag(nombre: str, flag: str) -> bool:
    """Indica si ese nombre de flag, tal como está escrito, es el `flag` de rclone.

    Args:
        nombre: El nombre con cualquier grafía (`max_delete`, `Max-Delete`), sin guiones delante.
        flag: El nombre normalizado que se busca (`max-delete`).
    """
    return model.normalizar_flag(nombre) == flag


def _sin_flag(extra: Iterable[str], flag: str) -> list[str]:
    """Devuelve `extra_flags` sin ese flag ni su valor.

    Vale `--flag V` (en dos argumentos) y `--flag=V`, con cualquier grafía del nombre.
    Otro flag que empieza igual (`--max-delete-size`) es otro y se queda.

    Args:
        extra: Los argumentos extra, en bruto.
        flag: El nombre normalizado del flag que se quita (`max-delete`).
    """
    salida: list[str] = []
    saltar_valor = False
    for arg in extra:
        texto = str(arg)
        if saltar_valor:
            saltar_valor = False
            if not texto.startswith("--"):
                continue
        nombre, igual, _ = texto.partition("=")
        if nombre.startswith("--") and _es_flag(nombre[2:], flag):
            saltar_valor = not igual
            continue
        salida.append(arg)
    return salida


def max_delete_efectivo(pair: Pair) -> int | None:
    """Devuelve el `--max-delete` que una pasada normal de la pareja le da a rclone.

    rclone se queda con el último que recibe: el de la cascada de flags (que guarda
    las claves como están escritas: `max_delete` y `max-delete` son dos, y gana la
    que se emite después) y, tras todos los flags, el de `extra_flags`.

    Returns:
        El valor, o `None` si ninguna capa lo pone o no es un número.
    """
    valor = None
    for nombre, v in pair.flags.items():
        if _es_flag(nombre, "max-delete"):
            valor = v
    extra = [str(a) for a in pair.extra_flags]
    for i, arg in enumerate(extra):
        nombre, igual, resto = arg.partition("=")
        if nombre.startswith("--") and _es_flag(nombre[2:], "max-delete"):
            valor = resto if igual else (extra[i + 1] if i + 1 < len(extra) else None)
    if isinstance(valor, bool):
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _salta_el_tope(pair: Pair, forzar: bool, resync: bool) -> bool:
    """Indica si la orden de esta pasada quita el `--max-delete` de un espejo (`forzar`).

    Solo un espejo (`sync`): bisync se salta el suyo con `--force`, que no quita nada, y un
    resync no pasa por el freno.
    """
    return forzar and not resync and frenos.se_puede_forzar(pair) and not pair.is_bisync


def flags_de_la_pasada(pair: Pair, *, config: str | Path, logfile: str | Path,
                       simulacro: bool = False, resync: bool = False,
                       sello: str = "", forzar: bool = False) -> list[FlagEfectivo]:
    """Devuelve los flags de una pasada: los de la pareja y los que añade el programa.

    Los de la pareja llegan ya fundidos (`Pair.flags`, con su capa en
    `Pair.origen_flags`); aquí se añaden los que dependen de ESTA ejecución y
    por eso no se configuran en el TOML. Para añadir un flag nuevo no se toca
    esta función: se escribe en el TOML.

    Args:
        pair: La pareja.
        config: El `rclone.conf` del dispositivo.
        logfile: Dónde escribe rclone esta pasada.
        simulacro: Si es un `--dry-run`.
        resync: Si la pasada es un `--resync`.
        sello: El sufijo de las versiones que guarda la pasada (`--suffix`).
        forzar: Si la pasada salta el freno de borrados: `--force` en bisync (que
            conserva su `--max-delete`, un %, y lo salta) y `--max-delete -1` en un
            espejo, en lugar de su tope (una cuenta), y se quita el que haya escrito la
            pareja con cualquier grafía (`max_delete`) o en `extra_flags`. En un `copy`,
            o en un resync, no cambia nada, ni en la pareja del llavero. Es de esta pasada y de ninguna otra:
            no se lee del TOML.
    """
    flags = {nombre: FlagEfectivo(nombre, valor,
                                  pair.origen_flags.get(nombre, model.ORIGEN_PAREJA))
             for nombre, valor in pair.flags.items()}

    def pone(nombre: str, valor) -> None:
        """Pone un flag que es del programa; si ya estaba, le quita el sitio a la pareja."""
        flags[nombre] = FlagEfectivo(nombre, valor, model.ORIGEN_PRDRIVE)

    pone("config", str(config))
    pone("log-file", str(logfile))
    if simulacro:
        pone("dry-run", True)
    if pair.is_bisync:
        pone("workdir", str(pair.workdir))
        if resync:
            pone("resync", True)
        else:
            # `--resync-mode` implica `--resync` (`setResyncDefaults()`,
            # `cmd/bisync/resync.go`: «either flag is sufficient without the
            # other»): dicho en una pasada normal, la convierte en un resync,
            # que no deja conflictos ni propaga borrados. Solo vale cuando
            # sync.py decide resincronizar. Se quita escrito como se escriba
            # (`resync_mode`): `flags_to_args()` lo emite igual, con guion.
            for nombre in [n for n in flags if _es_flag(n, "resync-mode")]:
                del flags[nombre]

    # Un resync no pasa por el freno de borrados (no compara contra el listado
    # anterior): no tiene nada que saltar, y juntos `--resync --force` no se piden.
    if forzar and frenos.se_puede_forzar(pair) and not resync:
        if pair.is_bisync:
            pone("force", True)
        else:
            # rclone se queda con el último `--max-delete`: se quitan todos los de la
            # cascada, escritos como se escriban, y `tramos()` los de `extra_flags`.
            for nombre in [n for n in flags if _es_flag(n, "max-delete")]:
                del flags[nombre]
            pone("max-delete", -1)

    if pair.versions:
        # El parseo ya garantiza que es bisync. El sello depende de la pasada,
        # por eso no va en el TOML.
        pone("backup-dir1", pair.versions_path1)
        pone("backup-dir2", pair.versions_path2)
        pone("suffix", sello)
        pone("suffix-keep-extension", True)
        # Con `delete`, el perdedor de un conflicto sale por el backup-dir
        # (`.prversions/`) en vez de quedarse como `<nombre>.conflicto-remoto1`
        # y viajar al otro lado. Un `[pair.flags]` sigue mandando, con la grafía
        # que use (`conflict_loser`).
        if not any(_es_flag(n, "conflict-loser") for n in flags):
            pone("conflict-loser", "delete")
    return list(flags.values())


def tramos(pair: Pair, *, binario: str, filtros: Path | None, config: str | Path,
           logfile: str | Path, simulacro: bool = False, resync: bool = False,
           sello: str = "", forzar: bool = False) -> list[Tramo]:
    """Devuelve la orden de rclone de la pareja en trozos, cada uno con su origen.

    Es el orden exacto de la línea de comandos: el subcomando con los dos
    extremos, el filtrado, los flags (los que se apagan con `false` no llegan a
    rclone y no salen) y los argumentos extra.

    Args:
        pair: La pareja.
        binario: El rclone.
        filtros: Su fichero de filtros, o `None` si no lo usa.
        config: El `rclone.conf` del dispositivo.
        logfile: Dónde escribe rclone esta pasada.
        simulacro: Si es un `--dry-run`.
        resync: Si la pasada es un `--resync`.
        sello: El sufijo de las versiones que guarda la pasada.
        forzar: Si la pasada salta el freno de borrados (`flags_de_la_pasada()`).
    """
    salida = [Tramo((binario, pair.mode.verb, pair.source, pair.dest), model.ORIGEN_PRDRIVE)]
    salida += tramos_de_filtrado(pair, filtros)
    for flag in flags_de_la_pasada(pair, config=config, logfile=logfile, simulacro=simulacro,
                                   resync=resync, sello=sello, forzar=forzar):
        args = model.flags_to_args({flag.nombre: flag.valor})
        if args:
            salida.append(Tramo(tuple(args), flag.origen, flag.nombre))
    extra = pair.extra_flags
    if _salta_el_tope(pair, forzar, resync):
        extra = _sin_flag(extra, "max-delete")
    if pair.is_bisync and not resync:
        # Por lo mismo que en `flags_de_la_pasada()`: rclone lo toma por un `--resync`.
        extra = _sin_flag(extra, "resync-mode")
    salida += [Tramo((arg,), model.ORIGEN_EXTRA) for arg in extra]
    return salida


def orden_rclone(pair: Pair, **kwargs) -> list[str]:
    """Devuelve la orden de rclone de la pareja, lista para ejecutar.

    Acepta lo mismo que `tramos()`.
    """
    return [a for t in tramos(pair, **kwargs) for a in t.args]
