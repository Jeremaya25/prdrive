#!/usr/bin/env python3
"""Los flags de rclone de una pareja (o de `[defaults]`), sin Tkinter.

Aquí se traduce entre lo que la persona escribe en un cuadro de texto y lo que
acaba en el TOML, en los dos sentidos, y se comprueba que lo escrito se puede
escribir de verdad. Dibujar es cosa de `ui/tk_pairs.py`.

Hay dos decisiones que conviene no deshacer:
- **El texto se parsea con `tomllib`, no a mano.** El destino de estas líneas
  es una tabla `[pair.flags]` del TOML, así que la única forma de que el
  formulario y el fichero entiendan lo mismo es usar el mismo parser. Un
  mini-parser propio acabaría aceptando `max-delete = 1_000` o `"true"` y
  guardando algo distinto de lo que se lee en pantalla.
- **No se admite cualquier flag.** `sync.py` pone los suyos en cada ejecución
  (`--config`, `--log-file`, `--dry-run`, `--workdir`, `--resync`) y los de
  filtrado salen de los patrones incluir/excluir (`filter_args`). Repetirlos
  aquí no los sustituye: rclone recibiría el flag dos veces y, en el caso de
  `--workdir` o `--filters-file`, eso es apuntar a bisync a un baseline que no
  es el suyo. Por eso `RESERVED` (`model.FLAGS_RESERVADOS`) se rechaza al
  parsear y no al ejecutar. Tampoco se admite un flag que haga que rclone
  lance un programa de este equipo (`--sftp-ssh`, `--password-command`…): el
  config viaja con el dispositivo. Ambas reglas son de `model.problema_flag()`,
  la puerta del parser del config; aquí solo se avisa al escribir.

Lo demás se admite sin lista blanca: quién sabe qué flags existen es rclone, y
la regla del proyecto es que un flag nuevo se añade escribiéndolo, no tocando
código.
"""

from __future__ import annotations

import re
import tomllib
from typing import Any, Mapping, NamedTuple

from common import config_file, model
from common.model import ConfigError


class FlagReservado(ConfigError):
    """Un flag que no se admite aquí: lo pone el programa o lanza un programa.

    Es lo que rechaza `model.problema_flag()`: los de `RESERVED` y los que hacen
    que rclone ejecute una orden de este equipo. Lo es tanto el del cuadro de
    flags como el del de argumentos extra, para que el aviso lleve el mismo
    título (`titulo_error()`) escriba donde escriba la persona.
    """


TITULO_RESERVADO = "Este flag no se puede poner aquí"
"""El título del aviso de un flag reservado."""
TITULO_NO_VALE = "Esto no se puede guardar así"
"""El título del aviso de cualquier otro texto que no vale."""


def titulo_error(error: ConfigError) -> str:
    """Devuelve el título del aviso rojo que explica por qué no vale lo escrito."""
    return TITULO_RESERVADO if isinstance(error, FlagReservado) else TITULO_NO_VALE


RESERVED = model.FLAGS_RESERVADOS
"""Flags que `sync.py` pone por su cuenta, con el motivo de cada uno."""

_NOMBRE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
"""Un nombre de flag válido: lo que va detrás de `--`.

`flags_to_args()` convierte `_` en `-`.
"""

ESCALARES = (bool, int, float, str)
"""Tipos de valor que admite un flag, solo o dentro de una lista."""

FRENOS = ("max-delete", "max-delete-size")
"""Flags cuyo valor es un freno de mano y no una preferencia: cambiarlos se avisa."""


class Row(NamedTuple):
    """Una línea de la tabla de flags efectivos.

    Args:
        flag: El flag tal cual se le pasa a rclone (`--transfers 4`).
        origen: La capa que ha ganado.
    """
    flag: str
    origen: str


normalize = model.normalizar_flag


def dump(flags: Mapping[str, Any] | None) -> str:
    """Devuelve la tabla como texto editable: exactamente lo que escribiría el TOML."""
    return config_file.dumps_table(dict(flags or {}))


def parse(text: str) -> dict:
    """Devuelve el texto del cuadro como tabla de flags.

    Solo se acepta lo que `common/config_file.py` sabe volver a escribir
    (escalares y arrays de escalares), porque `save()` se niega a escribir un
    config que no se relea igual y ese «no» llegaría demasiado tarde: con el
    diálogo ya cerrado y el plan ya confirmado.

    Raises:
        ConfigError: Si el texto no vale.
    """
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
    """Comprueba un flag del cuadro y lanza `ConfigError` si no vale."""
    if not _NOMBRE.fullmatch(key):
        raise ConfigError(f"'{key}' no puede ser el nombre de un flag: es lo que va "
                          f"detrás de '--', o sea letras, números, '-' y '_'.")
    motivo = model.problema_flag(key)
    if motivo:
        raise FlagReservado(f"'{key}' no se configura aquí: {motivo}.")
    if isinstance(value, dict):
        raise ConfigError(f"'{key}': aquí no caben tablas, solo 'clave = valor'.")
    if isinstance(value, (list, tuple)):
        for item in value:
            if not isinstance(item, ESCALARES):
                raise ConfigError(f"'{key}': una lista solo admite textos, números "
                                  f"o true/false.")
    elif not isinstance(value, ESCALARES):
        raise ConfigError(f"'{key}': valor no admitido ({type(value).__name__}). "
                          f"Textos entre comillas, números, o true/false.")
    motivo = model.problema_valor_flag(value)
    if motivo:
        raise ConfigError(f"'{key}': en su valor, {motivo}")


def dump_extra(extra: Any) -> str:
    """Devuelve `extra_flags` como texto: un argumento por línea."""
    return "\n".join(model._as_tuple(extra))


def parse_extra(text: str) -> list[str]:
    """Devuelve el cuadro de `extra_flags`: un argumento de rclone por línea, tal cual.

    Es la salida de emergencia para lo que `clave = valor` no sabe expresar y
    va sin tocar a la línea de comandos: por eso el valor de un flag ocupa su
    propia línea (`--bwlimit` y `8M` son dos argumentos, no uno). Lo que el
    config no admite (`model.problema_extra()`) se rechaza aquí, para que el
    diálogo lo diga al escribirlo y no más tarde, al guardar el plan.

    Raises:
        FlagReservado: Si algún argumento lanza un programa o es de los que pone
            `sync.py` (es un `ConfigError`).
    """
    args = [l.strip() for l in text.splitlines() if l.strip()]
    motivo = model.problema_extra(args)
    if motivo:
        raise FlagReservado(motivo)
    return args


def merge(mode_name: str | None, defaults_flags: Mapping[str, Any] | None,
          pair_flags: Mapping[str, Any] | None) -> dict:
    """Devuelve las capas fundidas igual que en `model._build_pair`.

    El orden es base < modo < `[defaults.flags]` < `[pair.flags]`.
    """
    modo = model.MODES.get(mode_name or "")
    return {**model.BASE_FLAGS,
            **(modo.flags if modo else {}),
            **dict(defaults_flags or {}),
            **dict(pair_flags or {})}


def effective(mode_name: str | None, defaults_flags: Mapping[str, Any] | None,
              pair_flags: Mapping[str, Any] | None) -> list[Row]:
    """Devuelve los flags que recibiría rclone y de qué capa sale cada uno.

    Es el sentido de todo esto: se escriben en cuatro sitios y hasta ahora solo
    se veían juntos en la línea de comandos, o sea cuando ya se está
    ejecutando.
    """
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
    """Devuelve lo que dice el botón: cuántos propios hay sin tener que abrirlos."""
    n, m = len(dict(flags or {})), len(model._as_tuple(extra))
    if not n and not m:
        return "ninguno propio"
    partes = []
    if n:
        partes.append(f"{n} flag{'s' if n != 1 else ''}")
    if m:
        partes.append(f"{m} extra")
    return " + ".join(partes)


def changes(antes: Mapping[str, Any] | None,
            despues: Mapping[str, Any] | None) -> list[str]:
    """Devuelve, flag a flag, qué se ha tocado; alimenta las consecuencias del plan."""
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
             despues: Mapping[str, Any] | None,
             mode_name: str | None = None) -> list[str]:
    """Devuelve los avisos que merecen leerse dos veces antes de guardar.

    Recibe los flags YA FUNDIDOS (los de `merge()`) y no los de una capa
    suelta, que es lo único que hace bien esta comprobación: quitar un flag de
    la pareja lo sube o lo baja según lo que diga la capa de debajo, y cambiar
    de modo lo cambia sin que nadie haya tocado ningún flag.

    `--max-delete` es el freno que impide que un lado vacío (una ruta que no
    está montada, un baseline que se ha quedado viejo) arrase el otro: subirlo
    o quitarlo no es una preferencia de rendimiento. En bisync, además, NO es
    una cuenta de ficheros: `Options.applyContext()` (cmd/bisync/cmd.go) lo
    reduce a un porcentaje de 0 a 100 y `excessDeletes()`
    (cmd/bisync/deltas.go) lo compara contra `borrados /
    ficheros_del_listado_anterior`, así que `mode_name` decide la unidad del
    aviso. En copy/mirror sí es la cuenta corriente de `sync`.
    """
    avisos = []
    efectivos_antes = dict(antes or {})
    efectivos = dict(despues or {})
    modo = model.MODES.get(mode_name or "")
    es_bisync = bool(modo and modo.is_bisync)
    for freno in FRENOS:
        viejo, nuevo = efectivos_antes.get(freno), efectivos.get(freno)
        if viejo == nuevo:
            continue
        if nuevo in (None, False):
            avisos.append(
                f"Sin '{freno}' desaparece el freno que impide que un lado vacío o "
                f"desmontado borre el otro entero.")
        elif isinstance(nuevo, int) and isinstance(viejo, int) and nuevo > viejo:
            if freno == "max-delete" and es_bisync:
                avisos.append(
                    f"'{freno}' pasa de {viejo} a {nuevo}: en bisync es un "
                    f"porcentaje del listado anterior, no una cuenta de ficheros, "
                    f"así que se permite borrar de golpe una porción mayor antes "
                    f"de que rclone aborte.")
            else:
                avisos.append(
                    f"'{freno}' pasa de {viejo} a {nuevo}: se permiten más "
                    f"borrados de golpe antes de que rclone aborte.")
    return avisos
