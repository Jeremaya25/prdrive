#!/usr/bin/env python3
"""
pins.py — Las versiones exactas de lo que el dispositivo lleva de fuera, y las
plataformas para las que puede llevarlo.

Dos cosas del dispositivo no son código de este proyecto: el binario de rclone y
el intérprete de Python. Las dos se descargan de su publicador —nunca se compilan
aquí— y las dos se fijan a una versión CONCRETA en este fichero. Moverlas es un
commit, no algo que pase solo porque alguien publicó otra cosa por la noche:

  * lo que se comprueba es lo que se ha probado, y no «lo último» que haya
    salido entre dos instalaciones;
  * los dispositivos de una misma tanda llevan lo mismo;
  * y el día que algo se rompa se sabe con qué versión, porque está escrita.

Es la fuente única que consultan el instalador (`install/rclone_bin.py`,
`install/runtime_bin.py`) y el despliegue. `penwatch.py` no la importa —no puede
importar nada del proyecto— y repite solo el nombre del sello y de la carpeta del
runtime, que un test mantiene a raya.

**Por qué python-build-standalone y no el «embeddable» oficial de CPython.** El
zip embebible de python.org no trae tkinter, y sin tkinter no hay ventana. Los de
astral-sh sí, son reubicables (se descomprimen donde sea y funcionan) y publican
un `SHA256SUMS` por release con la misma forma que el de rclone.

**Por qué 3.13 y no 3.14.** Los 3.14 de python-build-standalone ya traen Tcl/Tk
9.0, y la interfaz se ha hecho y medido con Tk 8.6 (el tema de ttk, los iconos
rasterizados a mano, `tk scaling`): 3.13 sigue en Tk 8.6. Subir a 3.14 es probar
esas pantallas con Tk 9 primero, no cambiar un número.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- rclone -------------------------------------------------------------------
# La que se descarga para cada plataforma elegida. El `version.txt` de rclone.org
# ya no manda: decía «la última», y la última puede ser una que nadie ha probado.
RCLONE_VERSION = "v1.75.1"

# --- Python (python-build-standalone, de astral-sh) ---------------------------
PYTHON_RELEASE = "20260901"          # el tag de la release en GitHub
PYTHON_VERSION = "3.13.15"
PBS_BASE_URL = ("https://github.com/astral-sh/python-build-standalone/"
                "releases/download")


@dataclass(frozen=True)
class Plataforma:
    """Un sistema y una CPU donde el dispositivo puede funcionar solo.

    `clave` es a la vez el nombre de la carpeta `runtime/<clave>/` y lo que
    comprueban los lanzadores, así que no se cambia a la ligera: un dispositivo
    ya aprovisionado la lleva escrita en disco.

    `bin_dir` es el vocabulario de `model.arch_dir()` —'x64' o 'arm'—, que es
    donde busca rclone el dispositivo. Un Windows y un Linux de la misma CPU
    comparten esa carpeta sin chocar: uno deja `rclone.exe` y el otro `rclone`.

    Los tamaños son lo que ocupa cada cosa YA en el dispositivo (descomprimida y
    podada), redondeados: sirven para decidir si cabe, no para cuadrar bytes."""
    clave: str
    nombre: str
    so: str             # 'windows' | 'linux': también el nombre de rclone en sus zips
    bin_dir: str        # 'x64' | 'arm'
    rclone_arch: str    # 'amd64' | 'arm64': el de los zips de rclone
    triple: str         # el destino de python-build-standalone
    mb_rclone: int
    mb_python: int

    @property
    def es_windows(self) -> bool:
        return self.so == "windows"

    @property
    def rclone_exe(self) -> str:
        return "rclone.exe" if self.es_windows else "rclone"

    @property
    def interprete(self) -> str:
        """El intérprete SIN consola, relativo a `runtime/<clave>/`.

        En Windows es `pythonw.exe`: con `python.exe` cada arranque abriría una
        consola negra detrás de la ventana. En Linux no hay tal distinción."""
        return "pythonw.exe" if self.es_windows else "bin/python3"

    @property
    def interprete_consola(self) -> str:
        """El que se usa cuando alguien lee la salida (inicializar parejas)."""
        return "python.exe" if self.es_windows else "bin/python3"


# Tamaños medidos con las versiones de arriba: rclone.exe 1.75.1 de amd64 son 81
# MB descomprimido; los runtimes, lo que deja `runtime_bin.extract()` ya podado.
PLATAFORMAS: tuple[Plataforma, ...] = (
    Plataforma("windows-x64", "Windows x64", "windows", "x64", "amd64",
               "x86_64-pc-windows-msvc", 82, 45),
    Plataforma("windows-arm64", "Windows ARM64", "windows", "arm", "arm64",
               "aarch64-pc-windows-msvc", 77, 45),
    Plataforma("linux-x64", "Linux x64", "linux", "x64", "amd64",
               "x86_64-unknown-linux-gnu", 82, 51),
    Plataforma("linux-arm64", "Linux ARM64", "linux", "arm", "arm64",
               "aarch64-unknown-linux-gnu", 77, 42),
)


def plataforma(clave: str) -> Plataforma:
    """La plataforma de esa clave. KeyError si no es ninguna de las conocidas."""
    for p in PLATAFORMAS:
        if p.clave == clave:
            return p
    raise KeyError(clave)


def plataforma_para(so: str, bin_dir: str) -> Plataforma | None:
    """La plataforma de un sistema ('windows'|'linux') y un `arch_dir()`.

    None si no hay ninguna: macOS, por ejemplo, ya no es una plataforma que el
    dispositivo pueda llevar (no hay equipo con el que probarla)."""
    for p in PLATAFORMAS:
        if p.so == so and p.bin_dir == bin_dir:
            return p
    return None
