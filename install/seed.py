#!/usr/bin/env python3
"""
seed.py — Sembrar el pen, dejarle su config y arrancar las parejas.

Tres cosas, en este orden, y el orden importa:

  1. **Siembra.** Un espejo `NAS -> pen` del maestro `/PJ/Perepen`, con los
     filtros de la pareja `perepen` del catálogo. Es la que trae `rclone-sync/`
     entero: código, `bin/`, `keys/` y `rclone.conf`. Sin esto el pen no tiene con
     qué sincronizar.
  2. **Config del dispositivo.** El `sync_config.toml` con las parejas elegidas,
     escrito con `common/config_file.py` —el mismo serializador que usa la
     ventana de parejas, que vuelve a parsear lo que genera y se niega a escribir
     si no cuadra—. Va DESPUÉS de la siembra a propósito: la siembra excluye el
     `sync_config.toml`, pero si el maestro trajera uno viejo, lo nuestro manda.
  3. **Inicialización.** Un `--resync` de las parejas bisync elegidas, lanzando el
     `sync.py` que acaba de aterrizar en el pen.

Lo que NO hace, y es deliberado: no inicializa parejas `*-mirror`. `perepen` es
un `up-mirror` del pen ENTERO al NAS; ejecutarla sin mirar, recién sembrado el
pen y con la selección a medias, es la forma más rápida de vaciar el maestro.

La siembra es un `rclone sync`: BORRA en destino lo que no esté en origen. Quien
llame tiene que haber pasado antes por `device.seed_target()`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Mapping

from common import config_file, model

from . import (BITLOCKER_PATH, MASTER_PATH, REMOTE_NAME, InstallError,
               python_command)
from .remote import Catalog, Rclone

MASTER_PAIR = "perepen"          # la pareja del catálogo que describe el pen entero
APP_SUBDIR = "rclone-sync"

# El .git del repo no está excluido en el catálogo (allí la pareja va pen -> NAS,
# donde sí interesa respaldarlo), pero sembrar el historial entero en un pen nuevo
# son cientos de megas que nadie ha pedido.
SEED_EXTRA_EXCLUDES = ("**/.git/**", ".git/**")


# ---------------------------------------------------------------------------
# La siembra
# ---------------------------------------------------------------------------

def seed_flags(catalog: Catalog, dry_run: bool = False) -> dict:
    """Los flags de la siembra, con la misma precedencia que usa sync.py:
    base < modo < [defaults.flags] < [pair.flags]."""
    defaults = catalog.raw.get("defaults", {})
    maestra = catalog.pair(MASTER_PAIR) or {}
    flags: dict = {}
    flags.update(model.BASE_FLAGS)
    flags.update(model.MODES["down-mirror"].flags)      # incluye el max-delete
    flags.update(defaults.get("flags", {}))
    flags.update(maestra.get("flags", {}))
    if dry_run:
        flags["dry-run"] = True
    return flags


def seed_filters(catalog: Catalog) -> list[str]:
    """--include/--exclude de la siembra.

    Se reaprovechan los del `perepen` del catálogo aunque allí describan el
    sentido contrario (pen -> NAS): lo que excluyen —`sync-data/`, el estado, los
    logs, las claves de BitLocker, el propio sync_config.toml— es justo lo que
    tampoco queremos traernos."""
    if not catalog.pair(MASTER_PAIR):
        raise InstallError(
            f"El catálogo del NAS no tiene la pareja '{MASTER_PAIR}', que es la "
            "que describe qué se copia al sembrar un pen.")
    defaults = catalog.raw.get("defaults", {})
    maestra = catalog.pair(MASTER_PAIR) or {}

    args: list[str] = []
    for patron in list(defaults.get("include", [])) + list(maestra.get("include", [])):
        args += ["--include", str(patron)]
    for patron in list(defaults.get("exclude", [])) + list(maestra.get("exclude", [])):
        args += ["--exclude", str(patron)]
    for patron in SEED_EXTRA_EXCLUDES:
        args += ["--exclude", patron]
    return args


def seed_command(rclone: Rclone, catalog: Catalog, pen_root: Path,
                 dry_run: bool = False) -> list[str]:
    """La orden completa de la siembra, para lanzarla y enseñar su salida."""
    return rclone.command(
        "sync", f"{REMOTE_NAME}:{MASTER_PATH}", str(pen_root),
        *seed_filters(catalog),
        *model.flags_to_args(seed_flags(catalog, dry_run)),
    )


# ---------------------------------------------------------------------------
# El sync_config.toml del dispositivo
# ---------------------------------------------------------------------------

def device_config(catalog: Catalog, selected: list[str]) -> dict:
    """El dict crudo del config de ESTE pen: los defaults del catálogo, su
    [daemon] si lo trae, y solo las parejas elegidas.

    Crudo y no `model.Config` porque las `Pair` del modelo llegan con los
    `[defaults]` ya fundidos: volcarlas duplicaría los defaults dentro de cada
    pareja."""
    faltan = [n for n in selected if catalog.pair(n) is None]
    if faltan:
        raise InstallError(
            f"El catálogo no tiene estas parejas: {', '.join(faltan)}.")
    if not selected:
        raise InstallError(
            "Hay que elegir al menos una pareja: un sync_config.toml sin ninguna "
            "no lo acepta sync.py.")

    raw: dict = {}
    if catalog.raw.get("defaults"):
        raw["defaults"] = dict(catalog.raw["defaults"])
    daemon = _daemon_section(catalog, selected)
    if daemon:
        raw["daemon"] = daemon
    raw["pair"] = [dict(catalog.pair(n)) for n in selected]      # type: ignore[arg-type]
    model.parse_config(raw)                                      # red final
    return raw


def _daemon_section(catalog: Catalog, selected: list[str]) -> dict:
    """El [daemon] del catálogo, recortado a lo que existe en este pen.

    Si nombrara una pareja que este dispositivo no lleva, el servicio fallaría en
    cada ciclo intentando sincronizar algo que no está en su config."""
    daemon = catalog.raw.get("daemon")
    if not isinstance(daemon, dict) or not daemon:
        return {}
    salida = dict(daemon)
    if "pairs" in salida:
        quedan = [n for n in salida["pairs"] if n in selected]
        if quedan:
            salida["pairs"] = quedan
        else:
            salida.pop("pairs")     # sin parejas válidas, mejor el valor por defecto
    return salida


def device_header(catalog: Catalog) -> str:
    """La cabecera del config generado: de dónde sale y cuándo."""
    propia = (
        f"# Generado por perepen-install.py el {datetime.now():%Y-%m-%d %H:%M}.\n"
        "# Es el config de ESTE dispositivo: el catálogo global vive en el NAS\n"
        "# (/PJ/Perepen-catalog/pairs.toml). Se puede editar a mano o desde la\n"
        "# ventana de parejas de runsync.\n"
    )
    return propia + (("#\n" + catalog.head) if catalog.head else "")


def config_path(pen_root: Path) -> Path:
    return Path(pen_root) / APP_SUBDIR / "sync_config.toml"


def write_device_config(pen_root: Path, catalog: Catalog,
                        selected: list[str]) -> Path:
    """Escribe el sync_config.toml del pen. Devuelve su ruta."""
    destino = config_path(pen_root)
    destino.parent.mkdir(parents=True, exist_ok=True)
    config_file.save(device_config(catalog, selected), path=destino,
                     head=device_header(catalog))
    return destino


# ---------------------------------------------------------------------------
# Carpetas locales
# ---------------------------------------------------------------------------

def local_dirs(catalog: Catalog, selected: list[str]) -> list[Path]:
    """Las carpetas del pen que necesitan las parejas elegidas, relativas.

    La de `perepen` (`local = "."`) no cuenta: es la raíz del pen, que ya existe."""
    salida = []
    for nombre in selected:
        pareja = catalog.pair(nombre) or {}
        local = str(pareja.get("local", "")).replace("\\", "/").strip("/")
        if local and local != ".":
            salida.append(Path(local))
    return salida


def make_local_dirs(pen_root: Path, catalog: Catalog,
                    selected: list[str]) -> list[Path]:
    """Crea esas carpetas. Devuelve las que se han creado ahora."""
    creadas = []
    for rel in local_dirs(catalog, selected):
        destino = Path(pen_root) / rel
        if destino.is_dir():
            continue
        try:
            destino.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise InstallError(f"No he podido crear {destino}: {e}") from e
        creadas.append(destino)
    return creadas


# ---------------------------------------------------------------------------
# Inicialización de las parejas
# ---------------------------------------------------------------------------

def resync_targets(catalog: Catalog, selected: list[str]) -> list[str]:
    """Las parejas elegidas que hay que inicializar: solo las bisync.

    Las `*-mirror` se quedan fuera a propósito. `perepen` es un `up-mirror` del
    pen ENTERO al NAS: lanzarla desde aquí, recién sembrado el pen, propagaría al
    maestro un pen a medio hacer. Esas se ejecutan a mano y con --dry-run."""
    return [n for n in selected
            if (catalog.pair(n) or {}).get("mode", model.DEFAULT_MODE) == "bisync"]


def mirror_pairs(catalog: Catalog, selected: list[str]) -> list[str]:
    """Las elegidas que son espejo, para poder avisar de ellas."""
    return [n for n in selected
            if (catalog.pair(n) or {}).get("mode", "") in ("up-mirror", "down-mirror")]


def sync_py(pen_root: Path) -> Path:
    return Path(pen_root) / APP_SUBDIR / "sync.py"


def resync_command(pen_root: Path, names: list[str]) -> list[str]:
    """La orden que inicializa las parejas bisync del pen.

    Aquí está la trampa que hace fracasar al instalador compilado: `sys.executable`
    es el propio .exe, no Python, así que usarlo relanzaría el instalador en vez de
    sincronizar. Hay que buscar un intérprete de verdad.

    Va con --yes porque se lanza sin terminal: sin él, la pregunta del resync
    tomaría el valor por defecto (no) y las parejas se saltarían en silencio, que
    es justo lo contrario de lo que se ha pedido."""
    destino = sync_py(pen_root)
    if not destino.is_file():
        raise InstallError(
            f"No encuentro {destino}. ¿Se ha sembrado el pen?")
    if not names:
        raise InstallError("No hay ninguna pareja bisync que inicializar.")
    python = python_command()
    if not python:
        raise InstallError(
            "No encuentro ningún Python instalado en este equipo, y hace falta "
            "para inicializar las parejas.\n\nInstala Python 3.11+ y vuelve a este "
            "paso; el pen ya sembrado no se pierde.")
    return [*python, str(destino), *names, "--resync", "--yes"]


# ---------------------------------------------------------------------------
# La clave de recuperación de BitLocker
# ---------------------------------------------------------------------------

def upload_recovery_key(rclone: Rclone, texto: str, etiqueta: str) -> str:
    """Sube la clave de recuperación de BitLocker al NAS y devuelve su ruta.

    Va al NAS y NO al pen a propósito: una clave de recuperación guardada dentro
    del volumen que descifra no sirve de nada. El catálogo excluye `_bitlockers/`
    de la pareja `perepen`, así que no vuelve al pen en la siguiente pasada."""
    if not texto.strip():
        raise InstallError("No hay ninguna clave de recuperación que subir.")
    import tempfile
    nombre = f"BitLocker-{etiqueta}-{datetime.now():%Y%m%d-%H%M}.txt"
    tmpdir = Path(tempfile.mkdtemp(prefix="perepen-bde-"))
    local = tmpdir / nombre
    try:
        local.write_text(texto, encoding="utf-8")
        destino = f"{REMOTE_NAME}:{BITLOCKER_PATH}/{nombre}"
        res = rclone.run("copyto", str(local), destino, capture=True, timeout=120)
        if res.returncode != 0:
            raise InstallError(
                f"No he podido subir la clave al NAS:\n\n{(res.stderr or '').strip()}")
        return destino
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# penwatch, desde el pen ya sembrado
# ---------------------------------------------------------------------------

def penwatch_install_command(pen_root: Path, mode: str = "ui") -> list[str]:
    """Instala el vigilante EN ESTE EQUIPO usando el penwatch del pen nuevo.

    Se usa el del pen y no el que lleve el instalador dentro porque es el que va a
    quedarse: así lo que se registra apunta al pen recién hecho."""
    destino = Path(pen_root) / APP_SUBDIR / "penwatch.py"
    if not destino.is_file():
        raise InstallError(f"No encuentro {destino}. ¿Se ha sembrado el pen?")
    python = python_command()
    if not python:
        raise InstallError("No encuentro ningún Python instalado en este equipo.")
    return [*python, str(destino), "install", "--mode", mode]


def summary(catalog: Catalog, selected: list[str]) -> list[tuple[str, str]]:
    """Filas «pareja -> qué le va a pasar», para enseñar antes de tocar nada."""
    filas = []
    for nombre in selected:
        pareja: Mapping = catalog.pair(nombre) or {}
        modo = pareja.get("mode", model.DEFAULT_MODE)
        destino = f"{pareja.get('local', '?')}  <->  {pareja.get('remote_path', '?')}"
        if modo == "bisync":
            nota = "se inicializará con --resync"
        elif modo in ("up-mirror", "down-mirror"):
            nota = "ESPEJO: no se inicializa aquí, pruébala con --dry-run"
        else:
            nota = "no necesita inicialización"
        filas.append((f"{nombre} [{modo}]", f"{destino} — {nota}"))
    return filas
