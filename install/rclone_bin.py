#!/usr/bin/env python3
"""
rclone_bin.py — Conseguir un rclone con el que arrancar.

El instalador corre en un equipo cualquiera, que puede no tener rclone. Se busca
en este orden y solo se descarga si no queda otra:

    1. bin/<arch>/ junto al instalador   <- ejecutándolo desde un pen ya hecho
    2. junto al propio ejecutable        <- el .exe y el rclone.exe en la misma carpeta
    3. el PATH del equipo
    4. la caché de descargas de instalaciones anteriores
    5. descarga del zip portable de rclone.org

La descarga va a la caché del usuario, nunca al pen: en este punto puede que
todavía no haya pen, y aunque lo hubiera, el binario que va a usar el pen es el
que trae la siembra.
"""

from __future__ import annotations

import os
import platform
import shutil
import stat
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from common.model import arch_dir

from . import RCLONE_BASE_URL, InstallError, bundle_dir

DOWNLOAD_TIMEOUT = 60          # segundos por lectura, no en total
Progreso = Callable[[str], None]


def exe_name() -> str:
    return "rclone.exe" if os.name == "nt" else "rclone"


def os_arch() -> tuple[str, str]:
    """(so, arquitectura) con los nombres que usa rclone en sus zips."""
    sysname = {"windows": "windows", "darwin": "osx", "linux": "linux"}.get(
        platform.system().lower(), "linux")
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64", "x64"}:
        arch = "amd64"
    elif machine.startswith("arm") or machine in {"aarch64", "arm64"}:
        arch = "arm64"
    elif machine in {"i386", "i686", "x86"}:
        arch = "386"
    else:
        arch = "amd64"
    return sysname, arch


def bin_subdir() -> str:
    """El subdirectorio de bin/ del pen, que no usa los nombres de rclone.

    Se pregunta al modelo del proyecto en vez de repetir la tabla: es el mismo
    bin/ que va a usar sync.py luego, y si dejaran de coincidir el instalador
    verificaría un binario y el pen usaría otro."""
    return arch_dir()


def cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    d = Path(base) / "perepen-install"
    d.mkdir(parents=True, exist_ok=True)
    return d


def candidates() -> list[Path]:
    """Dónde se mira, en orden, antes de plantearse descargar nada."""
    exe = exe_name()
    aqui = bundle_dir()
    rutas = [aqui / "bin" / bin_subdir() / exe, aqui / exe]
    en_path = shutil.which("rclone")
    if en_path:
        rutas.append(Path(en_path))
    rutas.append(cache_dir() / exe)
    return rutas


def find_rclone() -> Path | None:
    """El primer rclone utilizable, sin descargar nada. None si no hay ninguno."""
    for ruta in candidates():
        try:
            if ruta.is_file():
                return ruta
        except OSError:
            continue
    return None


def download_url() -> str:
    sysname, arch = os_arch()
    return f"{RCLONE_BASE_URL}/rclone-current-{sysname}-{arch}.zip"


def download_rclone(progreso: Progreso | None = None) -> Path:
    """Baja el zip portable y deja el binario en la caché. Devuelve su ruta."""
    def decir(msg: str) -> None:
        if progreso:
            progreso(msg)

    url = download_url()
    destino = cache_dir() / exe_name()
    tmp_zip = cache_dir() / "rclone.zip"
    decir(f"Descargando {url}")
    try:
        with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as resp, \
                open(tmp_zip, "wb") as salida:
            shutil.copyfileobj(resp, salida)
    except (urllib.error.URLError, OSError) as e:
        tmp_zip.unlink(missing_ok=True)
        raise InstallError(
            f"No he podido descargar rclone de {url}: {e}\n"
            f"Con conexión limitada, copia un rclone a mano en {cache_dir()}.") from e

    try:
        with zipfile.ZipFile(tmp_zip) as zf:
            # El zip trae una carpeta con versión dentro; el binario es el único
            # miembro que se llama así, pero si rclone cambia el empaquetado hay
            # que decirlo, no reventar con un StopIteration sin contexto.
            miembros = [m for m in zf.namelist() if m.rsplit("/", 1)[-1] == exe_name()]
            if not miembros:
                raise InstallError(
                    f"El zip de rclone no contiene ningún {exe_name()}. "
                    f"¿Ha cambiado el empaquetado en {url}?")
            with zf.open(miembros[0]) as src, open(destino, "wb") as dst:
                shutil.copyfileobj(src, dst)
    except zipfile.BadZipFile as e:
        raise InstallError(f"El fichero descargado de {url} no es un zip válido: {e}") from e
    finally:
        tmp_zip.unlink(missing_ok=True)

    if os.name != "nt":
        destino.chmod(destino.stat().st_mode | stat.S_IXUSR | stat.S_IRUSR)
    decir(f"rclone listo: {destino}")
    return destino


def ensure_rclone(progreso: Progreso | None = None,
                  allow_download: bool = True) -> Path:
    """El rclone que se va a usar. Descarga solo si hace falta y se le permite."""
    encontrado = find_rclone()
    if encontrado:
        return encontrado
    if not allow_download:
        raise InstallError(
            "No hay rclone en este equipo y no se ha permitido descargarlo.")
    return download_rclone(progreso)
