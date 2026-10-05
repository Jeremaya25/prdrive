#!/usr/bin/env python3
"""Leer y escribir `sync_config.toml`.

`tomllib` solo lee y el proyecto no admite dependencias, así que el
serializador es propio. Cubre lo que el esquema usa de verdad: escalares,
arrays de cadenas y una tabla `flags` anidada, tanto en `[defaults]` como en
cada `[[pair]]`.

Se trabaja siempre con el dict crudo de `tomllib`, nunca con `model.Config`:
sus `Pair` llegan con los flags ya fusionados con los `[defaults]`, y volcarlos
duplicaría los defaults dentro de cada pareja.

`save()` no se fía del serializador: antes de tocar el fichero valida con
`model.parse_config` y vuelve a parsear lo que acaba de generar para comprobar
que reproduce el mismo dict. Un fallo aquí escribe un config que gobierna
borrados, así que más vale negarse que escribir algo que no se relee.
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

PAIR_KEY_ORDER = ["name", "local", "remote_path", "remote", "mode"]
"""Orden en que se escriben las claves de una pareja.

Primero lo que la identifica, luego lo que la matiza; el resto va detrás, en
orden alfabético.
"""
LIST_KEYS = ["include", "exclude", "extra_flags"]
TABLAS_CONOCIDAS = ("remote", "defaults", "daemon", "pair")
"""Las tablas que `dumps()` escribe en su sitio; cualquier otra va al final, tal cual."""

_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")


def _config_path(path: Path | None) -> Path:
    """Devuelve la ruta dada o, sin ella, la del config de este dispositivo."""
    return Path(path) if path is not None else model.CONFIG_FILE


def load_raw(path: Path | None = None) -> dict:
    """Lee el TOML tal cual, sin resolver capas.

    Raises:
        ConfigError: Si el fichero no existe o no es TOML válido.
    """
    target = _config_path(path)
    if not target.exists():
        raise ConfigError(f"No existe el fichero de configuración: {target}")
    try:
        with target.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{target.name} no es TOML válido: {e}") from e


def header_of(text: str) -> str:
    """Devuelve el bloque de comentarios del principio de un TOML, tal cual.

    Está separada de `header()` porque hay cabeceras que nunca tocan el disco:
    la del catálogo del remoto (el manual del esquema) llega como texto en
    memoria y el instalador se la aplica al config que crea. En ambos casos
    tiene que sobrevivir a la reescritura del fichero.
    """
    cabecera = []
    for line in text.splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            break
        cabecera.append(line)
    return "\n".join(cabecera).rstrip() + "\n" if any(l.strip() for l in cabecera) else ""


def header(path: Path | None = None) -> str:
    """Devuelve la cabecera del fichero de configuración de este dispositivo.

    Dice de dónde sale el fichero (lo genera el instalador desde el catálogo
    del remoto), así que sobrevive a que lo reescribamos. Sin fichero, cadena
    vacía.
    """
    target = _config_path(path)
    try:
        return header_of(target.read_text(encoding="utf-8"))
    except OSError:
        return ""


def _key(name: str) -> str:
    """Devuelve una clave TOML, entre comillas si no es una clave simple."""
    return name if _BARE_KEY.fullmatch(name) else _string(name)


def _string(value: str) -> str:
    """Devuelve un string TOML escapado."""
    escaped = (str(value)
               .replace("\\", "\\\\")
               .replace('"', '\\"')
               .replace("\n", "\\n")
               .replace("\r", "\\r")
               .replace("\t", "\\t"))
    return f'"{escaped}"'


def _scalar(value: Any) -> str:
    """Devuelve un escalar TOML (bool, número o string)."""
    if isinstance(value, bool):      # antes que int: bool ES int en Python
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return _string(value)


def _array(values) -> str:
    """Devuelve un array TOML de escalares.

    En una línea con 0 o 1 elementos; con más, uno por línea.
    """
    items = list(values)
    if not items:
        return "[]"
    if len(items) == 1:
        return f"[{_scalar(items[0])}]"
    cuerpo = "".join(f"    {_scalar(v)},\n" for v in items)
    return f"[\n{cuerpo}]"


def _table_body(table: Mapping[str, Any], key_order: list[str] | None = None) -> list[str]:
    """Devuelve las líneas de claves escalares y de array de una tabla, sin su cabecera.

    Args:
        key_order: Claves que van primero, en ese orden; el resto sigue
            alfabéticamente. La subtabla `flags` nunca se emite aquí.
    """
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
    """Devuelve una tabla suelta como texto TOML, una clave por línea.

    Existe para el editor de flags de la UI: lo que se enseña al usuario tiene
    que ser exactamente lo que este fichero escribiría, o el formulario diría
    una cosa y el TOML acabaría con otra.
    """
    return "\n".join(_table_body(table))


def dumps(raw: Mapping[str, Any], head: str = "") -> str:
    """Devuelve el dict crudo como texto TOML.

    Args:
        head: Bloque de comentarios que abre el fichero.
    """
    out: list[str] = []
    if head:
        out.append(head.rstrip() + "\n")

    # `[remote]` solo aparece en el catálogo: define el remote en el
    # `rclone.conf` de cada dispositivo y hace que la conexión se teclee una
    # sola vez. Va arriba porque es lo primero que se lee a ojo, y es seguro:
    # lo que no puede moverse es `[pair.flags]`.
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
            # `[pair.flags]` se engancha a la ÚLTIMA `[[pair]]` escrita: por
            # eso va pegado a la suya y nunca al final del fichero.
            out.append("[pair.flags]")
            out += _table_body(pair["flags"])
            out.append("")

    # Una tabla que este código no conoce (la de una versión más nueva) se
    # escribe tal cual al final: el modelo la ignora al leer, y perderla al
    # reescribir haría que `dumps_checked()` se negara a escribir el fichero
    # entero. Lo que no se sepa escribir (una subtabla) lo sigue parando él.
    for nombre in sorted(k for k, v in raw.items()
                         if k not in TABLAS_CONOCIDAS and isinstance(v, Mapping)):
        out.append(f"[{_key(nombre)}]")
        out += _table_body(raw[nombre])
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def dumps_checked(raw: Mapping[str, Any], head: str = "") -> str:
    """Devuelve el TOML generado, ya validado y releído.

    Es la parte de `save()` que no depende de escribir en disco: el catálogo
    del remoto pasa por aquí antes de subirse, y allí un fichero que no se
    relee igual es peor, porque gobierna borrados en TODOS los dispositivos.

    Raises:
        ConfigError: Si el dict no tiene sentido como config, el texto no es
            TOML válido o no reproduce el dict pedido.
    """
    model.parse_config(raw)  # ¿tiene sentido lo que se pide?

    text = dumps(raw, head)

    # ¿Se relee igual que se ha escrito? Si el serializador se deja algo, es
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
    """Valida, deja una copia `.bak` y escribe el config de forma atómica.

    Args:
        path: Fichero destino; por defecto, el de este dispositivo.
        head: Bloque de comentarios del principio. Por defecto se conserva el
            que ya tuviera el destino, que es lo que hace falta al editar
            parejas; el instalador pasa el del catálogo porque en un
            dispositivo nuevo el fichero aún no existe y su cabecera se
            perdería.

    Returns:
        La ruta del `.bak`, o `None` si no había fichero previo.

    Raises:
        ConfigError: Si `dumps_checked` rechaza el config.
    """
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
