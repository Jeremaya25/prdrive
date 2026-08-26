#!/usr/bin/env python3
"""
flags_editor.py — Los flags de rclone de una pareja (o de [defaults]). Sin Tkinter.

Aquí se traduce entre lo que el usuario escribe en un cuadro de texto y lo que
acaba en el TOML, en los dos sentidos, y se comprueba que lo escrito se puede
escribir de verdad. Dibujar es cosa de `ui/tk_pairs.py`.

Dos decisiones que conviene no deshacer:

**El texto se parsea con `tomllib`, no a mano.** El destino de estas líneas es
una tabla `[pair.flags]` del TOML, así que la única forma de que el formulario y
el fichero entiendan lo mismo es usar el mismo parser. Un mini-parser propio
acabaría aceptando `max-delete = 1_000` o `"true"` y guardando algo distinto de
lo que se lee en pantalla.

**No se admite cualquier flag.** `sync.py` pone los suyos en cada ejecución
(`--config`, `--log-file`, `--dry-run`, `--workdir`, `--resync`) y los de
filtrado salen de los patrones incluir/excluir (`filter_args`). Repetirlos aquí
no los sustituye: rclone recibiría el flag dos veces, y en el caso de `--workdir`
o `--filters-file` eso es apuntar a bisync a un baseline que no es el suyo. Por
eso `RESERVED` se rechaza al parsear, no al ejecutar.

Lo demás se admite sin lista blanca: quién sabe qué flags existen es rclone, y la
regla del proyecto es que un flag nuevo se añade escribiéndolo, no tocando código.
"""

from __future__ import annotations

import re
import tomllib
from typing import Any, Mapping, NamedTuple

from common import config_file, model
from common.model import ConfigError

# Los que pone sync.py por su cuenta: build_command() y filter_args().
RESERVED = {
    "config": "lo pone sync.py: es el rclone.conf del pen",
    "log-file": "lo pone sync.py: cada pasada escribe en su propio log",
    "dry-run": "es --dry-run de sync.py, para que valga en todas las parejas",
    "workdir": "lo pone sync.py: state/<pareja>/, y cambiarlo mueve el baseline",
    "resync": "es --resync de sync.py, que además pregunta antes",
    "filters-file": "sale de los patrones incluir/excluir de la pareja",
    "filter": "usa los patrones incluir/excluir; mezclarlos rompe el filtrado",
    "filter-from": "usa los patrones incluir/excluir; mezclarlos rompe el filtrado",
    "include": "usa el cuadro «Incluir»",
    "exclude": "usa el cuadro «Excluir»",
}

# El nombre es lo que va detrás de `--`, y flags_to_args() convierte _ en -.
_NOMBRE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")

ESCALARES = (bool, int, float, str)

# Flags cuyo valor es un freno de mano, no una preferencia: cambiarlos se avisa.
FRENOS = ("max-delete", "max-delete-size")


class Row(NamedTuple):
    """Una línea de la tabla de flags efectivos."""
    flag: str            # tal cual se le pasa a rclone: --transfers 4
    origen: str          # la capa que ha ganado


# ---------------------------------------------------------------------------
# Texto <-> tabla
# ---------------------------------------------------------------------------

def normalize(key: str) -> str:
    """El nombre con el que rclone lo verá: `_` es `-` y no distingue mayúsculas."""
    return str(key).strip().replace("_", "-").lower()


def dump(flags: Mapping[str, Any] | None) -> str:
    """La tabla como texto editable: exactamente lo que escribiría el TOML."""
    return config_file.dumps_table(dict(flags or {}))


def parse(text: str) -> dict:
    """El texto del cuadro como tabla de flags. ConfigError si no vale.

    Solo se acepta lo que `common/config_file.py` sabe volver a escribir
    —escalares y arrays de escalares—, porque `save()` se niega a escribir un
    config que no se relea igual y ese "no" llegaría demasiado tarde: con el
    diálogo ya cerrado y el plan ya confirmado."""
    lineas = [l for l in text.splitlines() if l.strip()]
    for linea in lineas:
        if linea.lstrip().startswith("-"):
            raise ConfigError(
                f"'{linea.strip()}' es como se escribe en la línea de comandos. Aquí "
                f"va una línea por flag y sin los guiones: transfers = 4, o "
                f"checksum = true.")
    try:
        tabla = tomllib.loads("\n".join(lineas))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Eso no es TOML válido ({e}).\n\nUna línea por flag, "
                          f"'clave = valor': transfers = 4, max-delete = 25, "
                          f'conflict-resolve = "newer", checksum = true.') from e

    for key, value in tabla.items():
        _validar(key, value)
    return tabla


def _validar(key: str, value: Any) -> None:
    if not _NOMBRE.fullmatch(key):
        raise ConfigError(f"'{key}' no puede ser el nombre de un flag: es lo que va "
                          f"detrás de '--', o sea letras, números, '-' y '_'.")
    motivo = RESERVED.get(normalize(key))
    if motivo:
        raise ConfigError(f"'{key}' no se configura aquí: {motivo}.")
    if isinstance(value, dict):
        raise ConfigError(f"'{key}': aquí no caben tablas, solo 'clave = valor'.")
    if isinstance(value, (list, tuple)):
        for item in value:
            if not isinstance(item, ESCALARES):
                raise ConfigError(f"'{key}': una lista solo admite textos, números "
                                  f"o true/false.")
        return
    if not isinstance(value, ESCALARES):
        raise ConfigError(f"'{key}': valor no admitido ({type(value).__name__}). "
                          f"Textos entre comillas, números, o true/false.")


def dump_extra(extra: Any) -> str:
    """`extra_flags` como texto: un argumento por línea."""
    return "\n".join(model._as_tuple(extra))


def parse_extra(text: str) -> list[str]:
    """El cuadro de `extra_flags`: un argumento de rclone por línea, tal cual.

    Es la salida de emergencia para lo que `clave = valor` no sabe expresar, y va
    sin tocar a la línea de comandos: por eso el valor de un flag ocupa su propia
    línea (`--bwlimit` y `8M` son dos argumentos, no uno)."""
    return [l.strip() for l in text.splitlines() if l.strip()]


# ---------------------------------------------------------------------------
# Qué flags acaban valiendo
# ---------------------------------------------------------------------------

def merge(mode_name: str | None, defaults_flags: Mapping[str, Any] | None,
          pair_flags: Mapping[str, Any] | None) -> dict:
    """Las capas fundidas igual que en `model._build_pair`: base < modo <
    [defaults.flags] < [pair.flags]."""
    modo = model.MODES.get(mode_name or "")
    return {**model.BASE_FLAGS,
            **(modo.flags if modo else {}),
            **dict(defaults_flags or {}),
            **dict(pair_flags or {})}


def effective(mode_name: str | None, defaults_flags: Mapping[str, Any] | None,
              pair_flags: Mapping[str, Any] | None) -> list[Row]:
    """Los flags que recibiría rclone y de qué capa sale cada uno.

    Es el sentido de todo esto: se escriben en cuatro sitios y hasta ahora solo
    se veían juntos en la línea de comandos, o sea cuando ya se está ejecutando."""
    modo = model.MODES.get(mode_name or "")
    capas = [(model.BASE_FLAGS, "siempre"),
             (modo.flags if modo else {}, f"modo {mode_name}"),
             (dict(defaults_flags or {}), "[defaults]"),
             (dict(pair_flags or {}), "esta pareja")]

    origen: dict[str, str] = {}
    for tabla, nombre in capas:
        for key in tabla:
            origen[normalize(key)] = nombre

    salida = []
    for key, value in merge(mode_name, defaults_flags, pair_flags).items():
        args = model.flags_to_args({key: value})
        if not args:                       # false o None: no llega a rclone
            args = [f"(--{normalize(key)}: desactivado)"]
        salida.append(Row(" ".join(args), origen.get(normalize(key), "?")))
    return sorted(salida)


def summary(flags: Mapping[str, Any] | None, extra: Any = None) -> str:
    """Lo que dice el botón: cuántos propios hay sin tener que abrirlos."""
    n, m = len(dict(flags or {})), len(model._as_tuple(extra))
    if not n and not m:
        return "ninguno propio"
    partes = []
    if n:
        partes.append(f"{n} flag{'s' if n != 1 else ''}")
    if m:
        partes.append(f"{m} extra")
    return " + ".join(partes)


# ---------------------------------------------------------------------------
# Qué cambia
# ---------------------------------------------------------------------------

def changes(antes: Mapping[str, Any] | None,
            despues: Mapping[str, Any] | None) -> list[str]:
    """Flag a flag, qué se ha tocado. Alimenta las consecuencias del plan."""
    uno, otro = dict(antes or {}), dict(despues or {})
    salida = []
    for key in sorted(set(uno) | set(otro)):
        if uno.get(key) == otro.get(key):
            continue
        if key not in otro:
            salida.append(f"quita {key} (vuelve a valer el de la capa de debajo)")
        elif key not in uno:
            salida.append(f"añade {key} = {otro[key]!r}")
        else:
            salida.append(f"{key}: {uno[key]!r} -> {otro[key]!r}")
    return salida


def warnings(antes: Mapping[str, Any] | None,
             despues: Mapping[str, Any] | None) -> list[str]:
    """Los avisos que merecen leerse dos veces antes de guardar.

    Recibe los flags YA FUNDIDOS (los de `merge()`), no los de una capa suelta, y
    es lo único que hace bien esta comprobación: quitar un flag de la pareja lo
    sube o lo baja según lo que diga la capa de debajo, y cambiar de modo lo
    cambia sin que nadie haya tocado ningún flag.

    `--max-delete` es el freno que impide que un lado vacío —una ruta que no está
    montada, un baseline que se ha quedado viejo— arrase el otro. Subirlo o
    quitarlo no es una preferencia de rendimiento."""
    avisos = []
    efectivos_antes = dict(antes or {})
    efectivos = dict(despues or {})
    for freno in FRENOS:
        viejo, nuevo = efectivos_antes.get(freno), efectivos.get(freno)
        if viejo == nuevo:
            continue
        if nuevo in (None, False):
            avisos.append(
                f"Sin '{freno}' desaparece el freno que impide que un lado vacío o "
                f"desmontado borre el otro entero.")
        elif isinstance(nuevo, int) and isinstance(viejo, int) and nuevo > viejo:
            avisos.append(
                f"'{freno}' pasa de {viejo} a {nuevo}: se permiten más borrados de "
                f"golpe antes de que rclone aborte.")
    return avisos
