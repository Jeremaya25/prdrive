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


def header(path: Path | None = None) -> str:
    """El bloque de comentarios del principio del fichero, tal cual.

    Dice de dónde sale el fichero (lo genera perepen-install.py desde el
    catálogo del NAS), así que sobrevive a que lo reescribamos."""
    target = _config_path(path)
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    cabecera = []
    for line in lines:
        if line.strip() and not line.lstrip().startswith("#"):
            break
        cabecera.append(line)
    return "\n".join(cabecera).rstrip() + "\n" if any(l.strip() for l in cabecera) else ""


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


def dumps(raw: Mapping[str, Any], head: str = "") -> str:
    """El dict crudo como texto TOML."""
    out: list[str] = []
    if head:
        out.append(head.rstrip() + "\n")

    defaults = raw.get("defaults") or {}
    if defaults:
        out.append("[defaults]")
        out += _table_body(defaults, ["remote", "pen_remote", "keep_logs"])
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


def save(raw: Mapping[str, Any], path: Path | None = None) -> Path:
    """Valida, deja copia .bak y escribe. Devuelve la ruta del .bak (o None)."""
    model.parse_config(raw)                      # ¿tiene sentido lo que se pide?

    head = header(path)
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

    target = _config_path(path)
    backup = None
    if target.exists():
        backup = target.with_suffix(target.suffix + BAK_SUFFIX)
        shutil.copy2(target, backup)

    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, target)
    return backup
