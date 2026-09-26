#!/usr/bin/env python3
"""
_harness.py — Lo que comparten los tests.

No hay framework: son scripts que devuelven 0 o 1. El proyecto no admite
dependencias y esto tiene que poder ejecutarse desde el dispositivo en cualquier equipo,
así que la raíz del proyecto se deduce de la ubicación de este fichero y nunca
de la letra de unidad.
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

# Los tests escriben en castellano, y sus mensajes de fallo enseñan lo que se
# obtuvo — que puede llevar cualquier cosa, incluido el carácter de reemplazo.
# Lanzados por run_all.py o con la salida redirigida, Python codifica con la del
# sistema (cp1252 en Windows) y el propio arnés petaba al imprimir el fallo, que
# es justo cuando hace falta leerlo. Mismo criterio que `sync.preparar_salida`.
for _flujo in (sys.stdout, sys.stderr):
    _reconfigurar = getattr(_flujo, "reconfigure", None)
    if _reconfigurar is not None:
        _reconfigurar(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from common import model  # noqa: E402


class Checks:
    """Contador de comprobaciones. `checks.report()` es el código de salida."""

    def __init__(self, titulo: str) -> None:
        self.titulo = titulo
        self.total = 0
        self.fallos = 0
        print(f"=== {titulo} ===")

    def __call__(self, label: str, got, want) -> bool:
        self.total += 1
        if got == want:
            print(f"  OK     {label}")
            return True
        self.fallos += 1
        print(f"  FALLO  {label}")
        print(f"           obtenido: {got!r}")
        print(f"           esperado: {want!r}")
        return False

    def contains(self, label: str, haystack: str, needle: str) -> bool:
        return self(label, needle in haystack, True)

    def report(self) -> int:
        if self.fallos:
            print(f"--- {self.titulo}: {self.fallos} de {self.total} FALLAN\n")
            return 1
        print(f"--- {self.titulo}: {self.total} comprobaciones OK\n")
        return 0


def mkcfg(names, daemon=None, defaults=None, pairs=None) -> model.Config:
    """Una model.Config de mentira a partir de nombres, para no tocar el TOML real."""
    data = {
        "defaults": defaults or {"remote": "nas"},
        "pair": pairs or [{"name": n, "local": f"sync-data/{n}", "remote_path": f"/R/{n}"}
                          for n in names],
    }
    if daemon:
        data["daemon"] = daemon
    return model.parse_config(data)


_TEMPORALES: list[Path] = []


def tmpdir(prefix: str = "prdrive-test-") -> Path:
    """Un directorio temporal que se borra al terminar el test.

    `tempfile.mkdtemp()` a secas deja rastro: cada pasada de la batería dejaría
    una carpeta más en el temp del usuario, y en Windows nadie las recoge. Aquí
    se apuntan y se barren al salir, igual que hace `sandbox()` con las suyas."""
    destino = Path(tempfile.mkdtemp(prefix=prefix))
    _TEMPORALES.append(destino)
    return destino


MAQUINAS_PE = {"x64": 0x8664, "arm64": 0xAA64, "x86": 0x014C}


def pe(maquina: int | None, relleno: bytes = b"") -> bytes:
    """Lo justo de un binario de Windows para que se lea su CPU.

    Cabecera DOS con `e_lfanew` = 0x40, la firma `PE\\0\\0` ahí, y detrás el
    `Machine` de `IMAGE_FILE_HEADER`. None da algo que no es un PE. `relleno` va
    al final, para que dos ficheros de la misma CPU no sean idénticos."""
    if maquina is None:
        return b"esto no es un ejecutable" + relleno
    cabecera = bytearray(0x40)
    cabecera[0:2] = b"MZ"
    cabecera[0x3C:0x40] = (0x40).to_bytes(4, "little")
    return bytes(cabecera) + b"PE\0\0" + maquina.to_bytes(2, "little") + bytes(16) + relleno


def falso_portatil(version: str | None = None, sin: tuple[str, ...] = ()) -> Path:
    """Una carpeta con la pinta de la caché del VeraCrypt Portable ya comprobado.

    Los ficheros del portable —los de montar, formatear y agrandar de las dos
    arquitecturas, los dos drivers, con la CPU en su cabecera, y las licencias—
    y su sello con el SHA-256 de cada uno, como lo deja `veracrypt_bin`. Es lo
    que devolvería `veracrypt_bin.ensure_veracrypt()`: los tests lo sustituyen
    por esto y ninguno baja nada. `sin` son ficheros que no se ponen."""
    import hashlib

    from common import components, pins
    from install import veracrypt_bin

    carpeta = tmpdir("prdrive-vc-portatil-")
    resumenes = {}
    nombres = [(n, MAQUINAS_PE[arq]) for arq in veracrypt_bin.ARQUITECTURAS
               for n in (veracrypt_bin.montar(arq), veracrypt_bin.formatear(arq),
                         veracrypt_bin.expander(arq), veracrypt_bin.driver(arq))]
    nombres += [(n, None) for n in veracrypt_bin.LICENCIAS]
    for nombre, maquina in nombres:
        if nombre in sin:
            continue
        contenido = pe(maquina, nombre.encode()) if maquina else nombre.encode()
        (carpeta / nombre).write_bytes(contenido)
        resumenes[nombre] = hashlib.sha256(contenido).hexdigest()
    (carpeta / components.VERACRYPT_STAMP).write_text(
        components.veracrypt_stamp_text(version or pins.VERACRYPT_VERSION,
                                        "0" * 64, resumenes),
        encoding="utf-8", newline="\n")
    return carpeta


# La carpeta del agente residente en el equipo (`common/equipo.py`), en un
# temporal para TODOS los tests: en el equipo de quien los ejecuta puede haber
# un agente instalado de verdad, y ni su configuración puede cambiar lo que ve
# un test ni un test puede escribirle en el buzón.
from common import equipo  # noqa: E402

equipo.DIR = tmpdir("prdrive-equipo-harness-")
# Y lo que el instalador del agente escribe en el escritorio (el acceso del
# menú, el autostart), también en temporales: un test que se olvide de
# sustituirlo no puede dejarle un «prdrive» en el menú a quien los ejecuta.
os.environ["XDG_DATA_HOME"] = str(tmpdir("prdrive-xdg-data-"))
os.environ["XDG_CONFIG_HOME"] = str(tmpdir("prdrive-xdg-config-"))


@atexit.register
def _limpiar_temporales() -> None:
    for destino in _TEMPORALES:
        shutil.rmtree(destino, ignore_errors=True)


@contextmanager
def sandbox():
    """Reapunta las rutas del modelo a un directorio temporal.

    Todo lo que escriben bisync, los filtros y los logs cuelga de estas cuatro
    rutas, así que moverlas basta para que ningún test toque el dispositivo de verdad."""
    original = {name: getattr(model, name)
                for name in ("DEVICE_ROOT", "STATE_DIR", "FILTERS_DIR", "LOG_DIR", "CONFIG_FILE")}
    root = Path(tempfile.mkdtemp(prefix="prdrive-test-"))
    try:
        model.DEVICE_ROOT = root
        model.STATE_DIR = root / "state"
        model.FILTERS_DIR = root / "filters"
        model.LOG_DIR = root / "logs"
        model.CONFIG_FILE = root / "sync_config.toml"
        for d in (model.STATE_DIR, model.FILTERS_DIR, model.LOG_DIR):
            d.mkdir(parents=True, exist_ok=True)
        yield root
    finally:
        for name, value in original.items():
            setattr(model, name, value)
        shutil.rmtree(root, ignore_errors=True)
