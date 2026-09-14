#!/usr/bin/env python3
"""
components.py — Qué lleva el dispositivo de fuera, y si sigue siendo lo fijado.

Dos cosas del dispositivo no son código de este proyecto: el binario de rclone y
el Python que lo ejecuta. `common/pins.py` dice cuáles TOCAN; aquí se lee cuáles
LLEVA, y se restan.

Vive en `common/` y no en `install/` porque quien tiene que preguntárselo es el
dispositivo: la ventana pinta ese aviso en su primer pintado, y ahí no hay ni
red ni instalador. Todo lo de este módulo es leer ficheros diminutos del propio
dispositivo, así que contesta al instante y no lanza nunca —la misma regla que
`update.pending()` y `store.read_json()`—.

Quien ARREGLA lo que aquí se detecta es `install/components.py`, que sí baja y
verifica, y que no viaja al dispositivo: se ejecuta desde el zip del código, como
el aplicador de la actualización del programa.

**Por qué hay sellos.** Un binario no dice su versión sin ejecutarlo, y el de
otra plataforma no se puede ejecutar aquí: un Windows no arranca el rclone de
Linux ni un x64 el de ARM. Así que cada componente deja escrito de dónde salió:

  * `runtime/<clave>/PRDRIVE-RUNTIME` — lo escribe `runtime_bin.extract()`, el
    último de todo, de modo que una extracción a medias no tiene sello.
  * `bin/<arch>/<rclone>.PRDRIVE-RCLONE` — lo escribe `deploy.copy_rclone()`. Va
    junto al binario y lleva su nombre porque `bin/x64/` es de dos plataformas a
    la vez: ahí conviven el `rclone.exe` de Windows y el `rclone` de Linux.

Un dispositivo aprovisionado antes de que existieran los sellos no tiene el de
rclone. Eso se lee como «no consta», y no consta **cuenta como pendiente**: es
la única respuesta honesta, y una actualización lo deja apuntado para siempre.

Aquí viven también las rutas de los dos componentes dentro de `.prdrive/`, y
viven aquí para que haya UNA copia: `install/platforms.py` las importa en vez de
repetirlas. Es lo que garantiza que el instalador escriba donde el dispositivo
lee.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import APP_NAME, model, pins
from .pins import PLATAFORMAS, Plataforma

# La carpeta y el sello del runtime. `install/runtime_bin.py` los reexporta y
# `penwatch.py` repite el nombre del sello —no puede importar nada del
# proyecto—, con un test que impide que las copias se separen.
RUNTIME_SUBDIR = "runtime"
RUNTIME_STAMP = "PRDRIVE-RUNTIME"

# El de rclone es un sufijo y no un nombre fijo porque el sello acompaña a un
# fichero, no a una carpeta: `bin/x64/rclone.exe.PRDRIVE-RCLONE` y
# `bin/x64/rclone.PRDRIVE-RCLONE` conviven en el mismo sitio sin pisarse.
RCLONE_STAMP_SUFIJO = ".PRDRIVE-RCLONE"

RCLONE = "rclone"
PYTHON = "python"

# Lo que se enseña cuando no hay sello. No es un error: es un dispositivo de
# antes de que esto existiera, y lo que le hace falta es justo una actualización.
DESCONOCIDA = "no consta"


# ---------------------------------------------------------------------------
# Dónde vive cada componente
# ---------------------------------------------------------------------------

def _base(app_dir: Path | str | None) -> Path:
    """La carpeta del código. Sin argumento, la de ESTE dispositivo.

    Se resuelve al llamar y no al importar por lo mismo que
    `update.installed_version()` admite un `root`: el instalador pregunta por un
    volumen que no es el suyo, y `tests/_harness.sandbox()` no reengancha
    `model.APP_DIR`."""
    return Path(app_dir) if app_dir is not None else model.APP_DIR


def runtime_dir(app_dir: Path | str | None, plat: Plataforma) -> Path:
    return _base(app_dir) / RUNTIME_SUBDIR / plat.clave


def rclone_path(app_dir: Path | str | None, plat: Plataforma) -> Path:
    return _base(app_dir) / "bin" / plat.bin_dir / plat.rclone_exe


def rclone_stamp_path(app_dir: Path | str | None, plat: Plataforma) -> Path:
    ruta = rclone_path(app_dir, plat)
    return ruta.with_name(ruta.name + RCLONE_STAMP_SUFIJO)


# ---------------------------------------------------------------------------
# Los sellos
# ---------------------------------------------------------------------------

def leer_sello(texto: str) -> dict[str, str]:
    """Un sello `clave = valor` como diccionario. Lo que no se entienda, fuera.

    Tolerante a propósito, igual que `store.read_json()`: esto lo lee la ventana
    al abrirse, y un fichero a medias —el dispositivo se extrajo a mitad de una
    escritura— tiene que significar «aquí no consta nada», no una excepción en
    el arranque."""
    datos: dict[str, str] = {}
    for linea in texto.splitlines():
        if linea.lstrip().startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        datos[clave.strip()] = valor.strip()
    return datos


def _texto(ruta: Path) -> str:
    try:
        return ruta.read_text(encoding="utf-8")
    except (OSError, ValueError):
        # ValueError además de OSError: un `.read_text` sobre un fichero a
        # medias —el dispositivo se extrajo a mitad de una escritura— no falla
        # con un error de E/S, falla con un `UnicodeDecodeError` (que ES un
        # ValueError), y es el mismo suceso que el resto de este módulo trata
        # como «no consta»: un fichero que no se puede leer como texto.
        return ""


def rclone_stamp_text(plat: Plataforma, version: str) -> str:
    """El sello de un rclone: qué versión se copió y para qué plataforma.

    Sin sha256, a diferencia del sello del runtime. Aquel lo lleva porque
    penwatch compara el TEXTO ENTERO para decidir si refresca su copia; aquí lo
    único que hay que poder contestar es «¿es la versión fijada?», y un resumen
    que nadie lee es un resumen que se queda sin comprobar."""
    return (f"# {APP_NAME} — el rclone de este dispositivo. Lo escribe el "
            f"instalador y lo lee la ventana. No lo toques.\n"
            f"rclone = {version}\n"
            f"plataforma = {plat.clave}\n")


def runtime_stamp(app_dir: Path | str | None, plat: Plataforma) -> str | None:
    """El sello del runtime de esa plataforma, o None si no hay uno completo.

    Sin sello no hay runtime: `runtime_bin.extract()` lo escribe el último, así
    que una extracción interrumpida no lo tiene. Y sin intérprete tampoco."""
    d = runtime_dir(app_dir, plat)
    try:
        if not (d / plat.interprete).is_file():
            return None
        return (d / RUNTIME_STAMP).read_text(encoding="utf-8")
    except (OSError, ValueError):
        # Mismo motivo que en `_texto()`: un sello a medio escribir se lee como
        # `UnicodeDecodeError`, no como `OSError`, y el contrato de este módulo
        # —nunca lanza, la ventana lo llama en su primer pintado— es el mismo
        # para los dos.
        return None


# ---------------------------------------------------------------------------
# Qué está anticuado
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Pendiente:
    """Un componente que el dispositivo lleva y que no es el que el programa fija."""
    plataforma: Plataforma
    que: str                  # RCLONE | PYTHON
    lleva: str                # lo que hay ahora, o DESCONOCIDA
    deberia: str              # lo que dice common/pins.py

    @property
    def titulo(self) -> str:
        nombre = "rclone" if self.que == RCLONE else "Python"
        return f"{nombre} de {self.plataforma.nombre}"

    def describe(self) -> str:
        return f"{self.titulo}: lleva {self.lleva}, toca {self.deberia}"


def _existe(ruta: Path) -> bool:
    try:
        return ruta.is_file()
    except OSError:
        return False        # bloqueado, desenchufado: no hay nada que decir


def rclone_pendiente(app_dir: Path | str | None,
                     plat: Plataforma) -> Pendiente | None:
    if not _existe(rclone_path(app_dir, plat)):
        return None
    sello = leer_sello(_texto(rclone_stamp_path(app_dir, plat)))
    lleva = sello.get(RCLONE) or DESCONOCIDA
    if lleva == pins.RCLONE_VERSION:
        return None
    return Pendiente(plat, RCLONE, lleva, pins.RCLONE_VERSION)


def python_pendiente(app_dir: Path | str | None,
                     plat: Plataforma) -> Pendiente | None:
    texto = runtime_stamp(app_dir, plat)
    if texto is None:
        return None
    sello = leer_sello(texto)
    version = sello.get("python") or DESCONOCIDA
    release = sello.get("release") or DESCONOCIDA
    if version == pins.PYTHON_VERSION and release == pins.PYTHON_RELEASE:
        return None
    return Pendiente(plat, PYTHON, f"{version} ({release})",
                     f"{pins.PYTHON_VERSION} ({pins.PYTHON_RELEASE})")


def pendientes(app_dir: Path | str | None = None) -> list[Pendiente]:
    """Los componentes del dispositivo que no son los que fija el programa.

    Solo mira lo que el dispositivo LLEVA. Una plataforma que no tiene no está
    anticuada: está sin instalar, y eso lo resuelve «Añadir plataformas…» del
    asistente, que es una decisión con sitio en disco de por medio y no cabe en
    un botón de un recuadro.

    Ni lanza ni toca la red: es lo que pregunta la ventana al pintarse, y lo
    mismo que `update.pending()` a su manera."""
    salida: list[Pendiente] = []
    for plat in PLATAFORMAS:
        # rclone primero: es el que sincroniza, y sin él el dispositivo no hace
        # nada en ningún equipo.
        for encontrar in (rclone_pendiente, python_pendiente):
            hallado = encontrar(app_dir, plat)
            if hallado is not None:
                salida.append(hallado)
    return salida


def resumen(pends: list[Pendiente]) -> str:
    """Una línea por componente, para el recuadro de la ventana y el menú."""
    return "\n".join(p.describe() for p in pends)
