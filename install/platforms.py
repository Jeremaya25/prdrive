#!/usr/bin/env python3
"""
platforms.py — Para qué equipos va a funcionar el dispositivo. Sin Tkinter.

Un dispositivo prdrive lleva, por cada plataforma que se le elija, dos cosas que
no son código del proyecto: el binario de rclone (`bin/<arch>/`) y —en la
instalación completa— un Python propio (`runtime/<clave>/`). Con las dos, el
dispositivo arranca en un equipo sin nada instalado; es la promesa de «nada que
instalar», y hasta ahora no se cumplía: hacía falta Python en cada equipo.

Aquí se decide, sin dibujar nada, lo que la lista del paso «Instalación» enseña:

  * `host()` — qué plataforma es ESTE equipo (la que viene marcada);
  * `provisioned()` — qué lleva ya el dispositivo;
  * `Matriz` — lo marcado, completa o ligera, cuánto ocupa, y lo que hay que
    BORRAR, que solo entra en el plan si se ha confirmado;
  * `candidates()` / `device_interpreter()` — qué Python usaría este equipo, en
    el mismo orden que el `runsync.bat`.

`ui/tk_install.py` pinta la `Matriz` y `deploy.apply_platforms()` ejecuta su
`Plan`, la misma división que `pair_editor` / `tk_pairs`.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from common import model, pins
from common.pins import PLATAFORMAS, Plataforma

from . import IS_WIN
from .device import APP_SUBDIR
from .runtime_bin import RUNTIME_SUBDIR, STAMP

MB = 2 ** 20


def _so() -> str:
    if IS_WIN:
        return "windows"
    return "linux" if sys.platform.startswith("linux") else sys.platform


def host() -> Plataforma | None:
    """La plataforma de este equipo, o None si no es ninguna de las que el
    dispositivo puede llevar (macOS).

    La arquitectura sale de `model.arch_dir()` y no de `platform.machine()`, por
    lo de siempre: el instalador es un .exe x64 y en un Windows ARM64 se creería
    en un x64. Es la misma respuesta que usa el dispositivo para su `bin/`."""
    return pins.plataforma_para(_so(), model.arch_dir())


def candidates(plat: Plataforma | None) -> list[Plataforma]:
    """Los runtimes que puede usar esa plataforma, en orden de preferencia.

    Un Windows ARM64 ejecuta los binarios x64 emulados, así que si el
    dispositivo no lleva el suyo le vale el de x64; al revés no. Es exactamente
    la cadena del `runsync.bat`, y si dejaran de coincidir el instalador
    inicializaría las parejas con un Python y el dispositivo arrancaría con otro."""
    if plat is None:
        return []
    if plat.clave == "windows-arm64":
        return [plat, pins.plataforma("windows-x64")]
    return [plat]


# ---------------------------------------------------------------------------
# Qué lleva ya el dispositivo
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Instalada:
    rclone: bool
    runtime: bool


def runtime_dir(device_root: Path | str, plat: Plataforma) -> Path:
    return Path(device_root) / APP_SUBDIR / RUNTIME_SUBDIR / plat.clave


def rclone_path(device_root: Path | str, plat: Plataforma) -> Path:
    return Path(device_root) / APP_SUBDIR / "bin" / plat.bin_dir / plat.rclone_exe


def runtime_stamp(device_root: Path | str, plat: Plataforma) -> str | None:
    """El sello del runtime de esa plataforma, o None si no hay uno completo.

    Sin sello no hay runtime: `runtime_bin.extract()` lo escribe el último, así
    que una extracción interrumpida no lo tiene. Y sin intérprete tampoco."""
    d = runtime_dir(device_root, plat)
    try:
        if not (d / plat.interprete).is_file():
            return None
        return (d / STAMP).read_text(encoding="utf-8")
    except OSError:
        return None


def provisioned(device_root: Path | str | None) -> dict[str, Instalada]:
    """Lo que el dispositivo ya lleva, por clave. Solo las que tienen algo."""
    if device_root is None:
        return {}
    salida = {}
    for plat in PLATAFORMAS:
        try:
            tiene_rclone = rclone_path(device_root, plat).is_file()
        except OSError:
            tiene_rclone = False
        tiene_runtime = runtime_stamp(device_root, plat) is not None
        if tiene_rclone or tiene_runtime:
            salida[plat.clave] = Instalada(tiene_rclone, tiene_runtime)
    return salida


def free_bytes(device_root: Path | str | None) -> int | None:
    """El hueco libre del volumen, o None si no se puede saber (bloqueado,
    desenchufado). Aquí y no en la ventana: `tk_install` no toca el disco."""
    if device_root is None:
        return None
    try:
        return shutil.disk_usage(str(device_root)).free
    except OSError:
        return None


def device_interpreter(device_root: Path | str, anfitrion: Plataforma | None,
                       consola: bool = False) -> Path | None:
    """El Python del dispositivo que usaría `anfitrion`, o None si no lleva ninguno."""
    for plat in candidates(anfitrion):
        if runtime_stamp(device_root, plat) is not None:
            d = runtime_dir(device_root, plat)
            return d / (plat.interprete_consola if consola else plat.interprete)
    return None


# ---------------------------------------------------------------------------
# La lista del paso «Instalación»
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Fila:
    plataforma: Plataforma
    elegida: bool
    instalada: Instalada | None
    mb_rclone: int
    mb_python: int            # 0 en la ligera: esa columna no cuenta
    anfitrion: bool
    se_borra: bool


@dataclass(frozen=True)
class Plan:
    """Lo que va a pasar al pulsar «Instalar». Se enseña ANTES de hacerlo."""
    rclone: list[Plataforma]
    runtime: list[Plataforma]
    borrar: list[Plataforma]
    completa: bool

    def consecuencias(self) -> list[str]:
        nombres = lambda ps: ", ".join(p.nombre for p in ps)      # noqa: E731
        lineas = []
        if self.rclone:
            lineas.append(f"rclone {pins.RCLONE_VERSION} para {nombres(self.rclone)} "
                          f"(≈{sum(p.mb_rclone for p in self.rclone)} MB).")
        if self.completa and self.runtime:
            lineas.append(f"Python {pins.PYTHON_VERSION} propio para "
                          f"{nombres(self.runtime)} (≈"
                          f"{sum(p.mb_python for p in self.runtime)} MB): en esos "
                          f"equipos no hace falta instalar nada.")
        elif not self.completa:
            lineas.append("Instalación ligera: sin Python propio. Cada equipo "
                          "necesitará Python 3.11+ con Tkinter instalado.")
        if self.borrar:
            lineas.append(f"Se BORRARÁN del dispositivo rclone y Python de "
                          f"{nombres(self.borrar)}.")
        return lineas


@dataclass
class Matriz:
    """Lo marcado en la lista, y lo que el dispositivo ya lleva.

    Quitar de la lista una plataforma que el dispositivo YA lleva no la borra: la
    deja pendiente de confirmar (`quitar()` devuelve True para que la ventana
    pregunte). Si se confirma entra en `borrar`; si no, sus binarios se quedan
    donde están y simplemente no se reinstalan. Borrar es lo único destructivo de
    este paso, y no puede pasar por haber rozado una casilla."""
    instaladas: dict[str, Instalada]
    elegidas: set[str]
    anfitrion: Plataforma | None
    completa: bool = True
    borrar: set[str] = field(default_factory=set)

    @classmethod
    def para(cls, device_root: Path | str | None,
             anfitrion: Plataforma | None = None) -> "Matriz":
        """La de partida: este equipo marcado, y lo que el dispositivo ya lleva."""
        if anfitrion is None:
            anfitrion = host()
        instaladas = provisioned(device_root)
        elegidas = set(instaladas)
        if anfitrion is not None:
            elegidas.add(anfitrion.clave)
        return cls(instaladas, elegidas, anfitrion)

    # --- marcar y desmarcar --------------------------------------------------

    def elegir(self, clave: str) -> None:
        pins.plataforma(clave)                  # KeyError si no existe
        self.elegidas.add(clave)
        self.borrar.discard(clave)

    def quitar(self, clave: str) -> bool:
        """Desmarca. True si el dispositivo la lleva y hay que preguntar si se borra."""
        self.elegidas.discard(clave)
        return clave in self.instaladas

    def confirmar_borrado(self, clave: str, borrar: bool) -> None:
        if borrar and clave in self.instaladas and clave not in self.elegidas:
            self.borrar.add(clave)
        else:
            self.borrar.discard(clave)

    # --- lo que enseña la ventana --------------------------------------------

    def _elegidas(self) -> list[Plataforma]:
        return [p for p in PLATAFORMAS if p.clave in self.elegidas]

    def filas(self) -> list[Fila]:
        return [Fila(p, p.clave in self.elegidas, self.instaladas.get(p.clave),
                     p.mb_rclone, p.mb_python if self.completa else 0,
                     self.anfitrion is not None and p.clave == self.anfitrion.clave,
                     p.clave in self.borrar)
                for p in PLATAFORMAS]

    def total_mb(self) -> int:
        """Lo que ocupará en el dispositivo lo marcado."""
        return sum(p.mb_rclone + (p.mb_python if self.completa else 0)
                   for p in self._elegidas())

    def nuevo_mb(self) -> int:
        """Lo que hace falta de sitio: lo marcado que el dispositivo no lleva ya."""
        total = 0
        for p in self._elegidas():
            ya = self.instaladas.get(p.clave) or Instalada(False, False)
            total += 0 if ya.rclone else p.mb_rclone
            if self.completa and not ya.runtime:
                total += p.mb_python
        return total

    @property
    def listo(self) -> bool:
        return bool(self.elegidas)

    def avisos(self, libre: int | None = None) -> list[str]:
        """Lo que conviene saber antes de instalar. No bloquea salvo `listo`."""
        salida = []
        if not self.elegidas:
            salida.append("Elige al menos una plataforma: sin rclone el "
                          "dispositivo no sincroniza en ningún sitio.")
        elif self.anfitrion is not None and self.anfitrion.clave not in self.elegidas:
            salida.append(f"No has marcado {self.anfitrion.nombre}: en ESTE equipo "
                          f"el dispositivo no funcionará, y las parejas no se "
                          f"podrán inicializar desde aquí.")
        if libre is not None and self.nuevo_mb() * MB > libre:
            salida.append(f"Puede que no quepa: hacen falta ≈{self.nuevo_mb()} MB "
                          f"y en el dispositivo quedan {libre // MB} MB libres.")
        return salida

    def plan(self) -> Plan:
        elegidas = self._elegidas()
        return Plan(rclone=elegidas,
                    runtime=elegidas if self.completa else [],
                    borrar=[p for p in PLATAFORMAS if p.clave in self.borrar],
                    completa=self.completa)
