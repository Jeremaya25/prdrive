#!/usr/bin/env python3
"""Lo que comparten los tests.

No hay framework: son scripts que devuelven 0 o 1. El proyecto no admite
dependencias y esto tiene que poder ejecutarse desde el dispositivo en
cualquier equipo, así que la raíz del proyecto se deduce de la ubicación de
este fichero y nunca de la letra de unidad.
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

# La salida va en UTF-8: los mensajes de fallo enseñan lo obtenido, que puede
# llevar cualquier cosa, y con la codificación del sistema (cp1252 en Windows)
# el propio arnés petaba al imprimir el fallo, que es cuando hace falta leerlo.
# Mismo criterio que `sync.preparar_salida`.
for _flujo in (sys.stdout, sys.stderr):
    _reconfigurar = getattr(_flujo, "reconfigure", None)
    if _reconfigurar is not None:
        _reconfigurar(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from common import model  # noqa: E402


class Checks:
    """Contador de comprobaciones. `checks.report()` es el código de salida.

    Attributes:
        titulo: El título de la batería.
        total: Cuántas comprobaciones lleva.
        fallos: Cuántas han fallado.
    """

    def __init__(self, titulo: str) -> None:
        """Empieza una batería y escribe su título."""
        self.titulo = titulo
        self.total = 0
        self.fallos = 0
        print(f"=== {titulo} ===")

    def __call__(self, label: str, got, want) -> bool:
        """Comprueba que `got` sea `want`, lo cuenta y lo imprime.

        Returns:
            `True` si coinciden.
        """
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
        """Comprueba que `needle` esté en `haystack`."""
        return self(label, needle in haystack, True)

    def report(self) -> int:
        """Imprime el resumen y devuelve el código de salida.

        Es 0 si todo está bien y 1 si algo falló.
        """
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
"""Los directorios temporales que se barren al salir."""


def tmpdir(prefix: str = "prdrive-test-") -> Path:
    """Un directorio temporal que se borra al terminar el test.

    `tempfile.mkdtemp()` a secas deja rastro: cada pasada de la batería dejaría
    una carpeta más en el temp del usuario, y en Windows nadie las recoge. Aquí
    se apuntan y se barren al salir, igual que hace `sandbox()` con las suyas."""
    destino = Path(tempfile.mkdtemp(prefix=prefix))
    _TEMPORALES.append(destino)
    return destino


def en_exec(ruta) -> str:
    r"""Devuelve cómo queda una ruta dentro de las comillas del `Exec=` de un .desktop.

    Según la *Desktop Entry Specification*: la barra invertida se escapa para
    las comillas y, encima, la regla de las cadenas la dobla. Cada `\\` de una
    ruta de Windows son cuatro; una de Linux no lleva ninguna.
    """
    return str(ruta).replace("\\", "\\" * 4)


MAQUINAS_PE ={"x64": 0x8664, "arm64": 0xAA64, "x86": 0x014C}
"""Código de máquina de la cabecera PE de cada CPU."""


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


# La carpeta del agente residente en un temporal para TODOS los tests: en el
# equipo de quien los ejecuta puede haber un agente instalado de verdad, y ni
# su configuración puede cambiar lo que ve un test ni un test puede escribirle
# en el buzón.
from common import equipo  # noqa: E402

equipo.DIR = tmpdir("prdrive-equipo-harness-")
# Lo mismo con lo que el instalador del agente escribe en el escritorio (el
# acceso del menú, el autostart): un test que se olvide de sustituirlo no puede
# dejarle un «prdrive» en el menú a quien los ejecuta.
os.environ["XDG_DATA_HOME"] = str(tmpdir("prdrive-xdg-data-"))
os.environ["XDG_CONFIG_HOME"] = str(tmpdir("prdrive-xdg-config-"))
# Y lo del llavero en un equipo Linux: dónde se extrae el AppImage
# (`XDG_CACHE_HOME`) y las carpetas de los navegadores, de las que «Expulsar»
# quita los manifiestos que son de prdrive. La de Firefox cuelga de la carpeta
# personal, así que esa también se cambia aquí, y no en el entorno.
os.environ["XDG_CACHE_HOME"] = str(tmpdir("prdrive-xdg-cache-"))
from common import keepassxc as _keepassxc  # noqa: E402

_casa = tmpdir("prdrive-casa-")
_keepassxc.bases_navegador = lambda: {"config": Path(os.environ["XDG_CONFIG_HOME"]),
                                      "data": Path(os.environ["XDG_DATA_HOME"]),
                                      "home": _casa}

# Ni los procesos de verdad que no se dejan mirar (`store.sin_exe()`): un
# KeePassXC abierto en el equipo de quien corre los tests se colaría en los
# suyos. El test que la prueba guarda la de verdad (`REAL_SIN_EXE`).
from common import store as _store  # noqa: E402

REAL_SIN_EXE = _store.sin_exe
_store.sin_exe = lambda: {}

# Varios tests fuerzan `IS_WIN = False` para pasar por la rama de Linux, y ahí
# «¿vive este pid?» es `os.kill(pid, 0)`. En Windows eso NO pregunta: 0 es
# CTRL_C_EVENT y le manda un Ctrl+C a toda la consola (el test, run_all y el
# terminal de quien la lanzó). Aquí la señal 0 hace lo mismo que en POSIX: nada
# si el proceso existe, `ProcessLookupError` si no.
if os.name == "nt":
    _kill_real = os.kill

    def _kill_de_prueba(pid: int, sig: int) -> None:
        """Sustituye a `os.kill` en Windows.

        La señal 0 se comporta como en POSIX.
        """
        if sig == 0:
            from common.store import pid_alive
            if not pid_alive(pid):
                raise ProcessLookupError(3, "No such process", pid)
            return None
        return _kill_real(pid, sig)

    os.kill = _kill_de_prueba


@atexit.register
def _limpiar_temporales() -> None:
    """Borra los directorios temporales al salir."""
    for destino in _TEMPORALES:
        shutil.rmtree(destino, ignore_errors=True)


@contextmanager
def sandbox():
    """Reapunta las rutas del modelo a un directorio temporal.

    Todo lo que escriben bisync, los filtros y los logs cuelga de estas cuatro
    rutas, así que moverlas basta para que ningún test toque el dispositivo de verdad.
    El `rclone.conf` también: el prefijo de los listados mira el tipo de cada
    remote (`bisync.tipos_de_remote()`), y no puede depender del que haya en
    la copia de quien corre los tests (en un dispositivo, el de verdad)."""
    original = {name: getattr(model, name)
                for name in ("DEVICE_ROOT", "STATE_DIR", "FILTERS_DIR", "LOG_DIR", "CONFIG_FILE",
                             "RCLONE_CONF")}
    root = Path(tempfile.mkdtemp(prefix="prdrive-test-"))
    try:
        model.DEVICE_ROOT = root
        model.STATE_DIR = root / "state"
        model.FILTERS_DIR = root / "filters"
        model.LOG_DIR = root / "logs"
        model.CONFIG_FILE = root / "sync_config.toml"
        model.RCLONE_CONF = root / "rclone.conf"
        for d in (model.STATE_DIR, model.FILTERS_DIR, model.LOG_DIR):
            d.mkdir(parents=True, exist_ok=True)
        yield root
    finally:
        for name, value in original.items():
            setattr(model, name, value)
        shutil.rmtree(root, ignore_errors=True)
