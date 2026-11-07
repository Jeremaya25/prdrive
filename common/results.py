#!/usr/bin/env python3
"""Cómo acabó la última pasada de cada pareja.

Existe para que un fallo no se quede escondido: el log de una pasada fallida se
guarda en `logs/`, pero nadie mira ahí, y el servicio puede pasarse días
fallando en cada ciclo mientras el usuario cree que el dispositivo está al día.
Con esto la ventana principal sabe, al abrirse, qué parejas fallaron la última
vez y qué log lo explica.

Lo escribe `sync.py`, que es quien sabe el resultado y dónde ha dejado el log,
pase lo que pase por encima (la ventana, el servicio o una terminal). Una
pareja SALTADA (pide `--resync` y nadie lo ha aprobado) no se apunta: no se ha
ejecutado, así que su último resultado de verdad sigue siendo el anterior, y de
que pide un resync ya avisa su propio chip.

Cada entrada lleva además `retenida`: el sello de la pasada en que un espejo
(`*-mirror`) se paró en su freno `--max-delete`, o `null`. Lo apunta `apuntar()`
con `freno=True`, sobrevive a otros fallos y lo suelta una pasada buena; la
entrada de un `sync.py` de antes no tiene la clave (`Apunte.sabida`) y
`fijar_retenciones()` la rellena. Qué hace `revision` con ello, en la spec
`docs/superpowers/specs/2026-11-06-espejo-retenido-tras-el-freno-design.md`
(§1 y §4).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping, NamedTuple

from . import model, store
from .model import Config


def ruta_estado() -> Path:
    """Devuelve la ruta de `state/last_run.json`.

    Es función y no constante: los tests cambian `model.STATE_DIR` al vuelo.
    """
    return model.STATE_DIR / "last_run.json"


class Fallo(NamedTuple):
    """Una pareja cuya última pasada falló.

    Args:
        pareja: Nombre de la pareja.
        cuando: `store.stamp()` del final de la pasada.
        codigo: Código de salida de la pasada.
        log: El log que lo explica, o `None` si no quedó o ya no está.
        buena: La última pasada buena de esa pareja (`_buena()`), o `None` si
            no consta ninguna; dice desde cuándo falla. Tiene valor por defecto
            porque quien construye un `Fallo` a mano no tiene por qué saberla.
    """
    pareja: str
    cuando: str
    codigo: int
    log: Path | None
    buena: str | None = None


def _buena(dato: dict) -> str | None:
    """Devuelve la fecha de la última pasada buena que conste de una pareja.

    Solo cabe un resultado por pareja, así que sin esto un fallo borraría la
    fecha de cuando esa pareja sí quedó al día; y para todo lo que no es bisync
    este es el único sitio donde consta, porque los listados solo existen ahí.
    El segundo camino es por los registros escritos antes de que existiera la
    clave: si la última pasada apuntada fue buena, su fecha es la que se busca.

    Args:
        dato: Lo apuntado de esa pareja.
    """
    if isinstance(dato.get("buena"), str):
        return dato["buena"]
    try:
        if int(dato.get("codigo", 1)) != 0:
            return None
    except (TypeError, ValueError):
        return None
    return dato["cuando"] if isinstance(dato.get("cuando"), str) else None


def _log(dato: dict) -> Path | None:
    """Devuelve el log de una pasada apuntada si sigue en `logs/`, o `None`.

    Args:
        dato: Lo apuntado de esa pareja.
    """
    if not isinstance(dato.get("log"), str):
        return None
    candidato = model.LOG_DIR / Path(dato["log"]).name
    try:
        return candidato if candidato.is_file() else None
    except OSError:
        return None


def _retenida(dato: dict) -> str | None:
    """Devuelve el sello de retención de lo apuntado, o `None` si no hay uno válido."""
    valor = dato.get("retenida")
    return valor if isinstance(valor, str) and valor else None


def apuntar(nombre: str, codigo: int, log: Path | None, *, freno: bool = False) -> None:
    """Apunta el resultado de una pasada.

    Nunca falla: si el dispositivo no deja escribir, el aviso se pierde, pero
    la sincronización no puede caerse por él. El log se guarda por su nombre
    dentro de `logs/` y no con la ruta entera, porque la letra de unidad cambia
    de un equipo a otro. La clave `retenida` queda escrita siempre: con
    `freno`, el sello de esta pasada; con un código 0, `None`; si no, la que ya
    tenía la entrada anterior.

    Args:
        nombre: La pareja.
        codigo: Código de salida de la pasada.
        log: El log de la pasada, si lo hay.
        freno: Si la pasada de un espejo se paró en su freno `--max-delete`.
            Con un código distinto de 0 la retiene desde ese sello; con 0 no
            cuenta.
    """
    data = store.read_json(ruta_estado())
    parejas = data.get("parejas") if isinstance(data.get("parejas"), dict) else {}
    anterior = parejas.get(nombre)
    anterior = anterior if isinstance(anterior, dict) else {}
    ahora = store.stamp()
    if int(codigo) == 0:
        retenida = None
    elif freno:
        retenida = ahora
    else:
        retenida = _retenida(anterior)
    parejas[nombre] = {"cuando": ahora, "codigo": int(codigo),
                       "log": log.name if log is not None else None,
                       "buena": ahora if int(codigo) == 0 else _buena(anterior),
                       "retenida": retenida}
    store.write_json(ruta_estado(), {"parejas": parejas})


class Apunte(NamedTuple):
    """Lo apuntado de la última pasada de una pareja, entero.

    Args:
        cuando: `store.stamp()` del final de la pasada.
        codigo: Código de salida de la pasada.
        log: El log que lo explica, o `None` si no quedó o ya no está.
        retenida: El sello desde el que un espejo está retenido tras su freno,
            o `None` si no lo está (o si la clave no es un texto con algo).
        sabida: Si la entrada trae la clave `retenida`; sin ella la escribió un
            `sync.py` de antes y no se sabe si estaba retenida.
    """
    cuando: str
    codigo: int
    log: Path | None
    retenida: str | None
    sabida: bool


def apuntes(nombres: Iterable[str]) -> dict[str, Apunte]:
    """Devuelve lo apuntado de esas parejas con una sola lectura de `last_run.json`.

    Returns:
        Un `Apunte` por pareja; no salen las que no constan, las que no son un
        dict ni las que tienen un `codigo` que no es un número. Con el fichero
        ilegible, `{}`.
    """
    parejas = store.read_json(ruta_estado()).get("parejas")
    if not isinstance(parejas, dict):
        return {}
    salida: dict[str, Apunte] = {}
    for nombre in nombres:
        dato = parejas.get(nombre)
        if not isinstance(dato, dict):
            continue
        try:
            codigo = int(dato.get("codigo", 0))
        except (TypeError, ValueError):
            continue
        salida[nombre] = Apunte(str(dato.get("cuando", "")), codigo, _log(dato),
                                _retenida(dato), "retenida" in dato)
    return salida


def fijar_retenciones(valores: Mapping[str, str | None]) -> None:
    """Apunta la retención de las entradas que se escribieron sin la clave.

    Solo toca las entradas que existen y no tienen `retenida`: nunca crea una
    pareja ni pisa una decisión ya apuntada. Escribe una vez, y solo si cambia
    algo. Nunca falla (un fichero ilegible se queda como está).

    Args:
        valores: Por pareja, el sello de retención que le toca, o `None`.
    """
    parejas = store.read_json(ruta_estado()).get("parejas")
    if not isinstance(parejas, dict):
        return
    cambiado = False
    for nombre, valor in valores.items():
        dato = parejas.get(nombre)
        if isinstance(dato, dict) and "retenida" not in dato:
            dato["retenida"] = valor
            cambiado = True
    if cambiado:
        store.write_json(ruta_estado(), {"parejas": parejas})


def ultimas_buenas(nombres: Iterable[str]) -> dict[str, float]:
    """Devuelve cuándo terminó BIEN por última vez cada una de esas parejas.

    Es la única huella que deja una pasada cualquiera: la apunta
    `sync.run_pair()` la lance quien la lance (la ventana, una terminal, el
    servicio periódico o el vigilante), así que es lo que le falta a
    `bisync.last_run()`, que solo sabe de los listados y por tanto solo de las
    parejas bisync. Solo las buenas: la ventana enseña esta fecha como la
    última vez que esa pareja quedó al día, y una pasada fallida no deja nada
    al día ni borra la anterior (para eso está `_buena()`). De que falló avisan
    `fallos()` y su banner.

    Returns:
        Marca de tiempo por pareja; las que no constan no salen.
    """
    parejas = store.read_json(ruta_estado()).get("parejas")
    if not isinstance(parejas, dict):
        return {}
    marcas: dict[str, float] = {}
    for nombre in nombres:
        dato = parejas.get(nombre)
        if not isinstance(dato, dict):
            continue
        cuando = store.desde_sello(str(_buena(dato) or ""))
        if cuando is not None:
            marcas[nombre] = cuando
    return marcas


def fallos(config: Config) -> list[Fallo]:
    """Devuelve las parejas del config cuya última pasada falló.

    En el orden del config.
    """
    return fallos_de(config.names)


def fallos_de(nombres: Iterable[str]) -> list[Fallo]:
    """Devuelve los fallos de una lista de nombres: el servicio solo sabe los suyos."""
    parejas = store.read_json(ruta_estado()).get("parejas")
    if not isinstance(parejas, dict):
        return []
    salida = []
    for nombre in nombres:
        dato = parejas.get(nombre)
        if not isinstance(dato, dict):
            continue
        try:
            codigo = int(dato.get("codigo", 0))
        except (TypeError, ValueError):
            continue
        if codigo == 0:
            continue
        salida.append(Fallo(nombre, str(dato.get("cuando", "")), codigo, _log(dato),
                            _buena(dato)))
    return salida
