#!/usr/bin/env python3
"""Para qué equipos va a funcionar el dispositivo. Sin Tkinter.

Un dispositivo prdrive lleva, por cada plataforma que se le elija, dos cosas
que no son código del proyecto: el binario de rclone (`bin/<arch>/`) y, en la
instalación completa, un Python propio (`runtime/<clave>/`). Con las dos
arranca en un equipo sin nada instalado: es la promesa de «nada que instalar».

Aquí se decide, sin dibujar nada, lo que enseña la lista del paso
«Instalación»:
- `host()`: qué plataforma es ESTE equipo (la que viene marcada).
- `provisioned()`: qué lleva ya el dispositivo.
- `Matriz`: lo marcado, completa o ligera, cuánto ocupa y lo que hay que
  BORRAR, que solo entra en el plan si se ha confirmado.
- `candidates()` y `device_interpreter()`: qué Python usaría este equipo, en el
  mismo orden que el `runsync.bat`.

`ui/tk_install.py` pinta la `Matriz` y `deploy.apply_platforms()` ejecuta su
`Plan`: la misma división que `pair_editor` y `tk_pairs`.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from common import components, model, pins
from common.pins import PLATAFORMAS, Plataforma

from . import IS_WIN
from .device import APP_SUBDIR

MB = 2 ** 20
"""Bytes de un megabyte."""


def _so() -> str:
    """Devuelve el sistema de este equipo: `windows`, `linux` o el de `sys.platform`."""
    if IS_WIN:
        return "windows"
    return "linux" if sys.platform.startswith("linux") else sys.platform


def host() -> Plataforma | None:
    """Devuelve la plataforma de este equipo.

    La arquitectura sale de `model.arch_dir()` y no de `platform.machine()`: el
    instalador es un `.exe` x64 y en un Windows ARM64 se creería x64. Es la
    misma respuesta que usa el dispositivo para su `bin/`.

    Returns:
        La plataforma, o `None` si no es ninguna de las que el dispositivo
        puede llevar (macOS).
    """
    return pins.plataforma_para(_so(), model.arch_dir())


def candidates(plat: Plataforma | None) -> list[Plataforma]:
    """Devuelve los runtimes que puede usar esa plataforma, en orden de preferencia.

    Un Windows ARM64 ejecuta los x64 emulados, así que si el dispositivo no
    lleva el suyo le vale el de x64; al revés no. Es exactamente la cadena del
    `runsync.bat`: si dejaran de coincidir, el instalador inicializaría las
    parejas con un Python y el dispositivo arrancaría con otro.
    """
    if plat is None:
        return []
    if plat.clave == "windows-arm64":
        return [plat, pins.plataforma("windows-x64")]
    return [plat]


@dataclass(frozen=True)
class Instalada:
    """Lo que el dispositivo lleva ya de una plataforma.

    Args:
        rclone: Si lleva su rclone.
        runtime: Si lleva su Python.
    """
    rclone: bool
    runtime: bool


def _app(device_root: Path | str) -> Path:
    """Devuelve la carpeta del código del dispositivo a partir de la raíz del volumen.

    Las rutas de los componentes las define `common/components.py` y no este
    módulo: el instalador ESCRIBE ahí y el dispositivo LEE de ahí, y son dos
    paquetes distintos. Con una copia en cada lado, el día que una cambiase el
    instalador dejaría rclone en un sitio y la ventana lo buscaría en otro. Lo
    único que se añade aquí es la traducción de «raíz del volumen» a «carpeta
    del código».
    """
    return Path(device_root) / APP_SUBDIR


def runtime_dir(device_root: Path | str, plat: Plataforma) -> Path:
    """Devuelve la carpeta del runtime de esa plataforma en el dispositivo."""
    return components.runtime_dir(_app(device_root), plat)


def rclone_path(device_root: Path | str, plat: Plataforma) -> Path:
    """Devuelve la ruta del rclone de esa plataforma en el dispositivo."""
    return components.rclone_path(_app(device_root), plat)


def runtime_stamp(device_root: Path | str, plat: Plataforma) -> str | None:
    """Devuelve el sello del runtime de esa plataforma.

    O `None` si no hay uno completo.
    """
    return components.runtime_stamp(_app(device_root), plat)


def provisioned(device_root: Path | str | None) -> dict[str, Instalada]:
    """Devuelve lo que el dispositivo ya lleva, por clave.

    Solo las plataformas que tienen algo.
    """
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
    """Devuelve el hueco libre del volumen.

    Está aquí y no en la ventana porque `tk_install` no toca el disco.

    Returns:
        Los bytes libres, o `None` si no se puede saber (bloqueado,
        desenchufado).
    """
    if device_root is None:
        return None
    try:
        return shutil.disk_usage(str(device_root)).free
    except OSError:
        return None


def device_interpreter(device_root: Path | str, anfitrion: Plataforma | None,
                       consola: bool = False) -> Path | None:
    """Devuelve el Python del dispositivo que usaría `anfitrion`.

    Args:
        consola: Si se quiere el intérprete con consola.

    Returns:
        La ruta, o `None` si el dispositivo no lleva ninguno.
    """
    for plat in candidates(anfitrion):
        if runtime_stamp(device_root, plat) is not None:
            d = runtime_dir(device_root, plat)
            return d / (plat.interprete_consola if consola else plat.interprete)
    return None


@dataclass(frozen=True)
class Fila:
    """Una fila de la lista del paso «Instalación».

    Args:
        plataforma: La plataforma.
        elegida: Si está marcada.
        instalada: Lo que el dispositivo lleva ya de ella, o `None`.
        mb_rclone: Lo que ocupa su rclone.
        mb_python: Lo que ocupa su Python; 0 en la instalación ligera, donde
            esa columna no cuenta.
        anfitrion: Si es la de este equipo.
        se_borra: Si se ha confirmado borrarla del dispositivo.
    """
    plataforma: Plataforma
    elegida: bool
    instalada: Instalada | None
    mb_rclone: int
    mb_python: int
    anfitrion: bool
    se_borra: bool


@dataclass(frozen=True)
class Plan:
    """Lo que va a pasar al pulsar «Instalar»; se enseña ANTES de hacerlo.

    Args:
        rclone: Plataformas cuyo rclone se instala.
        runtime: Plataformas cuyo Python se instala.
        borrar: Plataformas que se borran del dispositivo.
        completa: Si es la instalación completa (con Python propio).
    """
    rclone: list[Plataforma]
    runtime: list[Plataforma]
    borrar: list[Plataforma]
    completa: bool

    def consecuencias(self) -> list[str]:
        """Devuelve una frase por cada consecuencia del plan."""
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


def _cuenta(n: int, uno: str, varios: str) -> str:
    """Devuelve `n` con su sustantivo en singular o plural: «1 lanzador», «2 lanzadores»."""
    return f"{n} {uno if n == 1 else varios}"


def _lista(partes: list[str]) -> str:
    """Une las partes como en español: «a, b y c»."""
    if len(partes) < 2:
        return "".join(partes)
    return ", ".join(partes[:-1]) + " y " + partes[-1]


@dataclass(frozen=True)
class Hecho:
    """Lo que ha escrito y borrado «Añadir plataformas…», contado por partes.

    Esa pantalla no solo pone y quita plataformas: también rehace los
    lanzadores, la entrada de fuera del contenedor y el VeraCrypt que viaja.
    Cada cosa se cuenta aparte para que lo hecho no se reduzca a las piezas de
    rclone y Python.

    Args:
        puestos: Piezas de rclone y de Python copiadas al dispositivo.
        borrados: Elementos quitados de las plataformas desmarcadas.
        lanzadores: Lanzadores de dentro reescritos.
        entrada: Ficheros de la entrada de fuera del contenedor reescritos.
        veracrypt: Ficheros del VeraCrypt que viaja puestos en la unidad.
    """
    puestos: int = 0
    borrados: int = 0
    lanzadores: int = 0
    entrada: int = 0
    veracrypt: int = 0

    def texto(self) -> str:
        """Devuelve la frase que cuenta lo hecho, con cada cosa en su plural.

        Returns:
            «Hecho. Puesto: …» con lo escrito y, si se quitó algo, «Borrado: …».
            Sin nada que contar, «Hecho. No había nada que cambiar.».
        """
        puesto = []
        if self.puestos:
            puesto.append(_cuenta(self.puestos, "pieza de rclone o Python",
                                  "piezas de rclone o Python"))
        if self.veracrypt:
            puesto.append("VeraCrypt (" + _cuenta(self.veracrypt, "fichero", "ficheros")
                          + ")")
        if self.lanzadores:
            puesto.append(_cuenta(self.lanzadores, "lanzador", "lanzadores"))
        if self.entrada:
            puesto.append("la entrada de fuera del contenedor ("
                          + _cuenta(self.entrada, "fichero", "ficheros") + ")")
        frases = ["Hecho."]
        if puesto:
            frases.append(f"Puesto: {_lista(puesto)}.")
        if self.borrados:
            frases.append("Borrado: " + _cuenta(self.borrados, "elemento", "elementos") + ".")
        if len(frases) == 1:
            frases.append("No había nada que cambiar.")
        return " ".join(frases)


@dataclass
class Matriz:
    """Lo marcado en la lista y lo que el dispositivo ya lleva.

    Quitar de la lista una plataforma que el dispositivo YA lleva no la borra:
    la deja pendiente de confirmar (`quitar()` devuelve True para que la
    ventana pregunte). Si se confirma entra en `borrar`; si no, sus binarios se
    quedan donde están y simplemente no se reinstalan. Borrar es lo único
    destructivo de este paso y no puede pasar por haber rozado una casilla.

    Args:
        instaladas: Lo que el dispositivo lleva, por clave.
        elegidas: Claves marcadas.
        anfitrion: La plataforma de este equipo.
        completa: Si es la instalación completa; si no, ligera.
        borrar: Claves cuyo borrado se ha confirmado.
    """
    instaladas: dict[str, Instalada]
    elegidas: set[str]
    anfitrion: Plataforma | None
    completa: bool = True
    borrar: set[str] = field(default_factory=set)

    @classmethod
    def para(cls, device_root: Path | str | None,
             anfitrion: Plataforma | None = None) -> "Matriz":
        """Devuelve la matriz de partida.

        Este equipo marcado y lo que el dispositivo ya lleva.
        """
        if anfitrion is None:
            anfitrion = host()
        instaladas = provisioned(device_root)
        elegidas = set(instaladas)
        if anfitrion is not None:
            elegidas.add(anfitrion.clave)
        return cls(instaladas, elegidas, anfitrion)

    def elegir(self, clave: str) -> None:
        """Marca una plataforma y cancela su borrado.

        Raises:
            KeyError: Si la clave no existe.
        """
        pins.plataforma(clave)                  # KeyError si no existe
        self.elegidas.add(clave)
        self.borrar.discard(clave)

    def quitar(self, clave: str) -> bool:
        """Desmarca una plataforma.

        Returns:
            True si el dispositivo la lleva y hay que preguntar si se borra.
        """
        self.elegidas.discard(clave)
        return clave in self.instaladas

    def confirmar_borrado(self, clave: str, borrar: bool) -> None:
        """Confirma o cancela el borrado de una plataforma desmarcada."""
        if borrar and clave in self.instaladas and clave not in self.elegidas:
            self.borrar.add(clave)
        else:
            self.borrar.discard(clave)

    def _elegidas(self) -> list[Plataforma]:
        """Devuelve las plataformas marcadas, en el orden de `PLATAFORMAS`."""
        return [p for p in PLATAFORMAS if p.clave in self.elegidas]

    def filas(self) -> list[Fila]:
        """Devuelve las filas de la lista, una por plataforma."""
        return [Fila(p, p.clave in self.elegidas, self.instaladas.get(p.clave),
                     p.mb_rclone, p.mb_python if self.completa else 0,
                     self.anfitrion is not None and p.clave == self.anfitrion.clave,
                     p.clave in self.borrar)
                for p in PLATAFORMAS]

    def total_mb(self) -> int:
        """Devuelve lo que ocupará en el dispositivo lo marcado."""
        return sum(p.mb_rclone + (p.mb_python if self.completa else 0)
                   for p in self._elegidas())

    def nuevo_mb(self) -> int:
        """Devuelve lo que hace falta de sitio.

        Lo marcado que el dispositivo no lleva ya.
        """
        total = 0
        for p in self._elegidas():
            ya = self.instaladas.get(p.clave) or Instalada(False, False)
            total += 0 if ya.rclone else p.mb_rclone
            if self.completa and not ya.runtime:
                total += p.mb_python
        return total

    @property
    def listo(self) -> bool:
        """Indica si hay algo marcado."""
        return bool(self.elegidas)

    def avisos(self, libre: int | None = None) -> list[str]:
        """Devuelve lo que conviene saber antes de instalar.

        No bloquea salvo `listo`.

        Args:
            libre: Bytes libres en el volumen, si se saben.
        """
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
        """Devuelve el plan que sale de lo marcado."""
        elegidas = self._elegidas()
        return Plan(rclone=elegidas,
                    runtime=elegidas if self.completa else [],
                    borrar=[p for p in PLATAFORMAS if p.clave in self.borrar],
                    completa=self.completa)
