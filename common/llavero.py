#!/usr/bin/env python3
"""El llavero: la base de KeePassXC del dispositivo, que se sincroniza sola.

La base vive en `.keychain/`, en la raíz del dispositivo, y su pareja la
construye el código cuando hay `[keychain]` (`model.LLAVERO`): bisync con
versiones contra la subcarpeta `keychain/` de la carpeta del catálogo. Aquí van
las decisiones del llavero que no son de la pareja en sí: sin Tk, sin red y,
lo que toca el equipo, a través de funciones de módulo que los tests
sustituyen.

Lo de antes de cada pasada (`preparar()`, lo llama `sync.py`):
- El compañero fijo, `LEEME.txt`: con una sola base, un guardado sería «han
  cambiado todos los ficheros» y bisync se pararía (H-12). Si falta, se pone;
  si la persona lo cambió, no se toca.
- Que cada base esté entera (`common/kdbx.py`): una a medio guardar no se sube.
  Se mira otra vez a los `ESPERA_ENTERA` segundos, por si el guardado estaba
  acabando.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import NamedTuple

from . import kdbx, model, store

LEEME = "LEEME.txt"
"""El compañero fijo de la base en `.keychain/` (H-12)."""
LEEME_TEXTO = (
    "Esta carpeta es el llavero de prdrive: la base de KeePassXC de este\n"
    "dispositivo. prdrive la sincroniza sola con la carpeta keychain/ del\n"
    "catálogo, en el remoto.\n"
    "\n"
    "No la toques a mano. Para abrir la base usa «Llavero», en la ventana de\n"
    "prdrive o en Llavero.bat: así KeePassXC se abre con la configuración que\n"
    "viaja en la unidad y lo que guardes sube solo.\n"
    "\n"
    "Este fichero no cambia nunca. Está aquí para que una base guardada no\n"
    "parezca «ha cambiado todo» a quien sincroniza.\n"
)
"""Lo que dice `LEEME.txt`. No se cambia: un cambio viajaría a todos los dispositivos."""
ESPERA_ENTERA = 2.0  # segundos
"""Lo que se espera antes de mirar otra vez una base que no está entera."""


def dormir(segundos: float) -> None:
    """Espera; es de módulo para que los tests no esperen de verdad."""
    time.sleep(segundos)


def carpeta() -> Path:
    """Devuelve la carpeta del llavero en este dispositivo (`.keychain/`).

    Es función y no constante porque los tests reenganchan `model.DEVICE_ROOT`.
    """
    return model.DEVICE_ROOT / model.LLAVERO_LOCAL


def bases(donde: Path) -> list[Path]:
    """Devuelve las bases de esa carpeta que viajan, también las de un conflicto.

    Son los `*.kdbx` de la carpeta y de sus subcarpetas, salvo `.prversions/` y
    las copias de antes de guardar (`*.old.kdbx`), que no viajan
    (`model.LLAVERO_REGLAS`).
    """
    try:
        candidatas = sorted(donde.rglob("*.kdbx"))
    except OSError:
        return []
    salida = []
    for ruta in candidatas:
        relativa = ruta.relative_to(donde).parts
        if model.VERSIONS_DIR in relativa or ruta.name.lower().endswith(".old.kdbx"):
            continue
        salida.append(ruta)
    return salida


class Rota(NamedTuple):
    """Una base que no está entera.

    Args:
        ruta: El fichero.
        motivo: Qué le pasa (`kdbx.Estado.motivo`).
    """
    ruta: Path
    motivo: str


def rotas(donde: Path) -> list[Rota]:
    """Devuelve las bases que no están enteras, mirándolas dos veces.

    Una que no está entera se vuelve a mirar a los `ESPERA_ENTERA` segundos:
    puede ser un guardado que estaba acabando. Un formato que no se conoce no
    cuenta como rota (`kdbx.mirar()`).
    """
    malas = [r for r in bases(donde) if kdbx.comprobar(r).entera is False]
    if not malas:
        return []
    dormir(ESPERA_ENTERA)
    salida = []
    for ruta in malas:
        estado = kdbx.comprobar(ruta)
        if estado.entera is False:
            salida.append(Rota(ruta, estado.motivo))
    return salida


def asegurar_leeme(donde: Path) -> bool:
    """Pone `LEEME.txt` si falta; si está, no lo toca aunque diga otra cosa.

    Se escriben los bytes tal cual, con `\\n` en todos los sistemas: dos
    dispositivos que lo pongan cada uno el suyo tienen que dejar el mismo
    fichero, o se pisarían en el remoto.

    Returns:
        True si lo ha escrito.
    """
    return store.crear_exclusivo(donde / LEEME, LEEME_TEXTO.encode("utf-8")) is True


def preparar(pair: model.Pair) -> str | None:
    """Prepara la pareja del llavero para una pasada y dice si no se puede subir.

    Pone el compañero fijo y comprueba las bases. No crea la carpeta: eso lo
    decide `sync.py` con sus reglas (nunca si hay baseline).

    Returns:
        El motivo para no hacer la pasada, o `None` si se puede.
    """
    donde = pair.local_abs
    try:
        if not donde.is_dir():
            return None
    except OSError:
        return None
    asegurar_leeme(donde)
    malas = rotas(donde)
    if not malas:
        return None
    lista = "; ".join(f"{r.ruta.name}: {r.motivo}" for r in malas)
    return (f"la base no está entera ({lista}). No se sube: puede que KeePassXC "
            f"la estuviera guardando. Se volverá a intentar en la próxima pasada.")
