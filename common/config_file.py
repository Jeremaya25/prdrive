#!/usr/bin/env python3
"""
config_file.py — Leer y escribir sync_config.toml.

`tomllib` solo lee, y el proyecto no admite dependencias, así que el serializador
es propio. Cubre lo que el esquema usa de verdad: escalares, arrays de cadenas y
una tabla `flags` anidada, tanto en `[defaults]` como en cada `[[pair]]`.

Se trabaja siempre con el **dict crudo** de tomllib, nunca con `model.Config`:
sus `Pair` llegan con los flags ya fusionados con los `[defaults]`, así que
volcarlos duplicaría los defaults dentro de cada pareja.

`save()` no se fía del serializador: antes de tocar el fichero valida con
`model.parse_config` y además vuelve a parsear lo que acaba de generar para
comprobar que reproduce el mismo dict. Un fallo aquí escribe un config que
gobierna borrados, así que más vale negarse que escribir algo que no se relee.
"""

from __future__ import annotations

import os
import re
import shutil
import tomllib
from pathlib import Path
from typing import Any, Mapping

from . import model
from .model import ConfigError

BAK_SUFFIX = ".bak"

# Orden con el que se escriben las claves de una pareja: primero lo que
# identifica la pareja, luego lo que la matiza. El resto va detrás, alfabético.
PAIR_KEY_ORDER = ["name", "local", "remote_path", "remote", "mode"]
LIST_KEYS = ["include", "exclude", "extra_flags"]

_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")


def _config_path(path: Path | None) -> Path:
    return Path(path) if path is not None else model.CONFIG_FILE


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

def load_raw(path: Path | None = None) -> dict:
    """El TOML tal cual, sin resolver capas."""
    target = _config_path(path)
    if not target.exists():
        raise ConfigError(f"No existe el fichero de configuración: {target}")
    try:
        with target.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{target.name} no es TOML válido: {e}") from e


def header_of(text: str) -> str:
    """El bloque de comentarios del principio de un TOML, tal cual.

    Se separa de `header()` porque hay cabeceras que nunca llegan a tocar el
    disco: la del catálogo del remoto —que es el manual del esquema— llega como
    texto en memoria, y el instalador se la aplica al config que está creando.
    En los dos casos tiene que sobrevivir a que reescribamos el fichero."""
    cabecera = []
    for line in text.splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            break
        cabecera.append(line)
    return "\n".join(cabecera).rstrip() + "\n" if any(l.strip() for l in cabecera) else ""


def header(path: Path | None = None) -> str:
    """La cabecera del fichero de configuración de este dispositivo.

    Dice de dónde sale el fichero (lo genera el instalador desde el catálogo
    del remoto), así que sobrevive a que lo reescribamos."""
    target = _config_path(path)
    try:
        return header_of(target.read_text(encoding="utf-8"))
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------

def _key(name: str) -> str:
    return name if _BARE_KEY.fullmatch(name) else _string(name)


def _string(value: str) -> str:
    escaped = (str(value)
               .replace("\\", "\\\\")
               .replace('"', '\\"')
               .replace("\n", "\\n")
               .replace("\r", "\\r")
               .replace("\t", "\\t"))
    return f'"{escaped}"'


def _scalar(value: Any) -> str:
    if isinstance(value, bool):      # antes que int: bool ES int en Python
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return _string(value)


def _array(values) -> str:
    items = list(values)
    if not items:
        return "[]"
    if len(items) == 1:
        return f"[{_scalar(items[0])}]"
    cuerpo = "".join(f"    {_scalar(v)},\n" for v in items)
    return f"[\n{cuerpo}]"


def _table_body(table: Mapping[str, Any], key_order: list[str] | None = None) -> list[str]:
    """Las claves escalares y de array de una tabla, sin su cabecera."""
    keys = list(key_order or [])
    keys += sorted(k for k in table if k not in keys and k != "flags")
    lines = []
    for key in keys:
        if key not in table:
            continue
        value = table[key]
        if isinstance(value, dict):
            continue                     # las subtablas van aparte
        if isinstance(value, (list, tuple)):
            lines.append(f"{_key(key)} = {_array(value)}")
        else:
            lines.append(f"{_key(key)} = {_scalar(value)}")
    return lines


def dumps_table(table: Mapping[str, Any]) -> str:
    """Una tabla suelta como texto TOML, una clave por línea.

    Existe para el editor de flags de la UI: lo que se le enseña al usuario tiene
    que ser exactamente lo que este fichero escribiría, o el formulario diría una
    cosa y el TOML acabaría con otra."""
    return "\n".join(_table_body(table))


def dumps(raw: Mapping[str, Any], head: str = "") -> str:
    """El dict crudo como texto TOML."""
    out: list[str] = []
    if head:
        out.append(head.rstrip() + "\n")

    # [remote] solo aparece en el catálogo: es cómo se define el remote en el
    # rclone.conf de cada dispositivo, y es lo que hace que la conexión se teclee
    # una sola vez. Va arriba porque es lo primero que se lee a ojo, y arriba es
    # seguro: la que no puede moverse es [pair.flags], que se engancha a la
    # ÚLTIMA [[pair]] escrita.
    remoto = raw.get("remote") or {}
    if remoto:
        out.append("[remote]")
        out += _table_body(remoto, ["name", "type", "host", "port", "user"])
        out.append("")

    defaults = raw.get("defaults") or {}
    if defaults:
        out.append("[defaults]")
        out += _table_body(defaults, ["remote", "device_remote", "catalog_path",
                                      "keep_logs"])
        out.append("")
        if defaults.get("flags"):
            out.append("[defaults.flags]")
            out += _table_body(defaults["flags"])
            out.append("")

    daemon = raw.get("daemon") or {}
    if daemon:
        out.append("[daemon]")
        out += _table_body(daemon, ["pairs", "interval_minutes"])
        out.append("")

    for pair in raw.get("pair") or []:
        out.append("[[pair]]")
        out += _table_body(pair, PAIR_KEY_ORDER)
        out.append("")
        if pair.get("flags"):
            # OJO: [pair.flags] se engancha a la ÚLTIMA [[pair]] escrita. Por eso
            # va aquí, pegado a la suya, y nunca al final del fichero.
            out.append("[pair.flags]")
            out += _table_body(pair["flags"])
            out.append("")

    return "\n".join(out).rstrip() + "\n"


def dumps_checked(raw: Mapping[str, Any], head: str = "") -> str:
    """El TOML generado, ya validado y releído. ConfigError si algo no cuadra.

    Es la parte de `save()` que no depende de escribir en disco, y por eso vive
    aparte: el catálogo del remoto pasa por aquí antes de subirse, y allí un fichero
    que no se relee igual es todavía peor, porque gobierna borrados en TODOS los
    dispositivos y no solo en este dispositivo."""
    model.parse_config(raw)                      # ¿tiene sentido lo que se pide?

    text = dumps(raw, head)

    # ¿Y se relee igual que se ha escrito? Si el serializador se deja algo, es
    # preferible negarse a escribir que dejar un config distinto del pedido.
    try:
        releido = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"El config generado no es TOML válido ({e}). No se ha escrito.") from e
    if releido != dict(raw):
        raise ConfigError(
            "El config generado no reproduce lo que se pidió. No se ha escrito.\n"
            "Es un fallo del serializador, no de tu configuración.")
    return text


def save(raw: Mapping[str, Any], path: Path | None = None,
         head: str | None = None) -> Path | None:
    """Valida, deja copia .bak y escribe. Devuelve la ruta del .bak (o None).

    `head` es el bloque de comentarios del principio. Por defecto se conserva el
    que ya tuviera el fichero destino, que es lo que hace falta al editar
    parejas; el instalador pasa el del catálogo, porque en un dispositivo nuevo ese
    fichero todavía no existe y su cabecera se perdería."""
    text = dumps_checked(raw, header(path) if head is None else head)

    target = _config_path(path)
    backup = None
    if target.exists():
        backup = target.with_suffix(target.suffix + BAK_SUFFIX)
        shutil.copy2(target, backup)

    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, target)
    return backup
