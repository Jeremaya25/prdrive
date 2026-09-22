#!/usr/bin/env python3
"""
versions_editor.py — Qué hay guardado en `.prversions/` y cómo se purga. Sin Tkinter.

Mismo guion que `pair_editor` y `conflict_editor`: la ventana
(`ui/tk_versions.py`) pide un plan, enseña sus consecuencias en
`tk_pairs.confirmar_plan()` y solo lo ejecuta si el usuario dice que sí. Aquí no
se dibuja nada.

**La fecha sale del NOMBRE, no del mtime.** Es la única parte de esto que podría
haberse hecho de dos maneras, así que conviene decir por qué. rclone bautiza cada
versión con la marca de la pasada que la apartó (`--suffix`), y ese nombre no
vuelve a cambiar nunca. El mtime sí: copiar la carpeta a otro disco, restaurar un
backup o cualquier herramienta que la toque lo reescribe, y entonces una purga
«anterior al 1 de septiembre» borraría cosas de agosto que parecen de hoy, o al
revés. El nombre es el dato que el propio formato existe para llevar.

**Y se purga en los dos lados a la vez.** Las dos carpetas son independientes
—`bisync` las excluye, así que no se replican— y cada una guarda lo que perdió su
lado, de modo que purgar solo una deja la mitad del histórico. El lado remoto se
borra con una sola invocación de `rclone delete --files-from`: la lista exacta de
ficheros, ni una edad ni un patrón, para que lo que se borra sea exactamente lo
que se ha enseñado.
"""

from __future__ import annotations

import csv
import io
import re
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, NamedTuple

from common import catalog, model
from common.model import Pair

# `<lo que sea>~YYYYMMDD-HHMMSS` con su extensión detrás, que es lo que produce
# `--suffix ~%Y%m%d-%H%M%S --suffix-keep-extension`. Un fichero que no case con
# esto no lo ha puesto el versionado y no se toca.
SELLO = re.compile(r"^(?P<base>.+)~(?P<fecha>\d{8}-\d{6})(?P<ext>\.[^.]*)?$")

DISPOSITIVO = "dispositivo"
REMOTO = "remoto"
TITULO_LADO = {DISPOSITIVO: "En este dispositivo", REMOTO: "En el remoto"}


# ---------------------------------------------------------------------------
# Puntos de indirección: todo lo que toca el disco o la red, sustituible
# ---------------------------------------------------------------------------

def borrar_local(ruta: Path) -> None:
    ruta.unlink()


def borrar_remoto(raiz: str, rutas: Iterable[str]) -> tuple[bool, str]:
    """Borra del remoto exactamente esas rutas, relativas a `raiz`.

    Una sola invocación con `--files-from`: sobre SFTP, una por fichero serían
    cientos de conexiones, y una purga por edad borraría lo que rclone decida y
    no lo que se ha enseñado."""
    lista = Path(tempfile.mkstemp(prefix="prdrive-purga-", suffix=".txt")[1])
    try:
        lista.write_text("\n".join(rutas) + "\n", encoding="utf-8", newline="\n")
        salida = catalog.run(["delete", raiz, "--files-from", str(lista)])
        if salida.returncode != 0:
            return False, (salida.stderr or salida.stdout or "").strip()
        return True, ""
    except OSError as e:
        return False, str(e)
    finally:
        lista.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Lo que hay guardado
# ---------------------------------------------------------------------------

class Version(NamedTuple):
    ruta: str          # relativa a la raíz de .prversions, con /
    original: str      # el nombre que tenía el fichero, sin el sello
    cuando: datetime
    tamano: int


@dataclass(frozen=True)
class Lado:
    """Lo guardado en un lado, o por qué no se ha podido saber."""
    clave: str
    endpoint: str
    disponible: bool
    detalle: str
    versiones: tuple[Version, ...] = ()

    @property
    def titulo(self) -> str:
        return TITULO_LADO[self.clave]

    @property
    def total(self) -> int:
        return len(self.versiones)

    @property
    def tamano(self) -> int:
        return sum(v.tamano for v in self.versiones)

    def anteriores_a(self, corte: date) -> tuple[Version, ...]:
        return tuple(v for v in self.versiones if v.cuando.date() < corte)


def leer_nombre(nombre: str) -> tuple[str, datetime] | None:
    """`nota~20260922-093000.md` → ('nota.md', 2026-09-22 09:30:00)."""
    m = SELLO.match(nombre)
    if not m:
        return None
    try:
        cuando = datetime.strptime(m.group("fecha"), "%Y%m%d-%H%M%S")
    except ValueError:                      # 20261345-990000 y cosas así
        return None
    return m.group("base") + (m.group("ext") or ""), cuando


def _version(ruta: str, tamano: int) -> Version | None:
    leido = leer_nombre(ruta.rsplit("/", 1)[-1])
    if leido is None:
        return None
    original, cuando = leido
    return Version(ruta=ruta, original=original, cuando=cuando, tamano=tamano)


def leer_local(pair: Pair) -> Lado:
    raiz = pair.local_abs / model.VERSIONS_DIR
    endpoint = pair.versions_path1
    if not raiz.exists():
        return Lado(DISPOSITIVO, endpoint, True, "todavía no se ha guardado nada")
    encontradas = []
    try:
        for fichero in sorted(raiz.rglob("*")):
            if not fichero.is_file():
                continue
            relativa = fichero.relative_to(raiz).as_posix()
            v = _version(relativa, fichero.stat().st_size)
            if v is not None:
                encontradas.append(v)
    except OSError as e:
        # El dispositivo puede desaparecer a media lectura: es un pen.
        return Lado(DISPOSITIVO, endpoint, False, f"no se ha podido leer: {e}")
    return Lado(DISPOSITIVO, endpoint, True, "", tuple(encontradas))


def leer_remoto(pair: Pair) -> Lado:
    """Lo guardado en el otro lado, con `rclone lsf`.

    `--csv` y no el separador de fábrica: el de `lsf` es ';', y un fichero con un
    ';' en el nombre partiría la línea en dos. Con CSV, quien escribe la línea y
    quien la lee usan las mismas reglas."""
    endpoint = pair.versions_path2
    try:
        salida = catalog.run(["lsf", "-R", "--files-only", "--csv",
                              "--format", "ps", endpoint])
    except Exception as e:                                    # noqa: BLE001
        return Lado(REMOTO, endpoint, False, f"no se ha podido preguntar: {e}")
    if salida.returncode != 0:
        texto = (salida.stderr or "").strip()
        if "directory not found" in texto:
            return Lado(REMOTO, endpoint, True, "todavía no se ha guardado nada")
        return Lado(REMOTO, endpoint, False, texto.splitlines()[-1] if texto else
                    "el remoto no ha contestado")

    encontradas = []
    for campos in csv.reader(io.StringIO(salida.stdout)):
        if len(campos) < 2:
            continue
        try:
            tamano = int(campos[1])
        except ValueError:
            continue
        v = _version(campos[0], tamano)
        if v is not None:
            encontradas.append(v)
    return Lado(REMOTO, endpoint, True, "", tuple(encontradas))


def lados(pair: Pair) -> tuple[Lado, Lado]:
    return leer_local(pair), leer_remoto(pair)


def legible(octetos: int) -> str:
    for unidad in ("B", "KiB", "MiB", "GiB"):
        if octetos < 1024 or unidad == "GiB":
            entero = unidad == "B" or octetos >= 100
            return f"{octetos:.0f} {unidad}" if entero else f"{octetos:.1f} {unidad}"
        octetos /= 1024
    return f"{octetos:.1f} GiB"


# ---------------------------------------------------------------------------
# Purgar
# ---------------------------------------------------------------------------

@dataclass
class PurgaPlan:
    """Qué se va a borrar, antes de borrarlo."""
    pair_name: str
    corte: date
    local: tuple[Version, ...] = ()
    remoto: tuple[Version, ...] = ()
    raiz_local: Path | None = None
    raiz_remota: str = ""
    consequences: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def vacio(self) -> bool:
        return not (self.local or self.remoto)

    def execute(self) -> list[str]:
        """Primero el dispositivo, después el remoto.

        En ese orden porque el de aquí se puede deshacer mirando la papelera del
        sistema y el del remoto no; y porque si el remoto falla, lo que queda es
        «purgado aquí, pendiente allí», que se arregla repitiendo. Al revés
        quedaría el remoto vacío y el dispositivo lleno, y la siguiente pasada de
        bisync no lo corregiría: la carpeta está excluida."""
        hechos: list[str] = []
        fallos = 0
        if self.local and self.raiz_local is not None:
            for v in self.local:
                try:
                    borrar_local(self.raiz_local / Path(v.ruta))
                except OSError:
                    fallos += 1
            hechos.append(f"Dispositivo: {len(self.local) - fallos} versiones borradas")
            if fallos:
                hechos.append(f"Dispositivo: {fallos} no se han podido borrar")
            _podar(self.raiz_local)

        if self.remoto:
            bien, error = borrar_remoto(self.raiz_remota, [v.ruta for v in self.remoto])
            hechos.append(f"Remoto: {len(self.remoto)} versiones borradas" if bien
                          else f"Remoto: NO se ha podido borrar ({error})")
        return hechos


def _podar(raiz: Path) -> None:
    """Quita las carpetas que se hayan quedado sin nada dentro.

    Best-effort: una carpeta vacía de más no rompe nada, y aquí ya se ha borrado
    lo que importaba."""
    try:
        for carpeta in sorted(raiz.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if carpeta.is_dir() and not any(carpeta.iterdir()):
                carpeta.rmdir()
    except OSError:
        pass


def plan_purgar(pair: Pair, local: Lado, remoto: Lado, corte: date) -> PurgaPlan:
    """Lo que se borraría al purgar lo anterior a `corte`. No toca nada."""
    plan = PurgaPlan(
        pair_name=pair.name,
        corte=corte,
        local=local.anteriores_a(corte) if local.disponible else (),
        remoto=remoto.anteriores_a(corte) if remoto.disponible else (),
        raiz_local=pair.local_abs / model.VERSIONS_DIR,
        raiz_remota=pair.versions_path2,
    )
    dia = corte.strftime("%d/%m/%Y")
    if plan.vacio:
        plan.consequences.append(f"No hay ninguna versión anterior al {dia}.")
        return plan

    for lado, cuales in ((local, plan.local), (remoto, plan.remoto)):
        if not lado.disponible:
            plan.warnings.append(
                f"{lado.titulo}: no se ha podido leer ({lado.detalle}), así que "
                "no se purga. Lo de allí se queda como está.")
        elif cuales:
            plan.consequences.append(
                f"{lado.titulo}: se borran {len(cuales)} versiones "
                f"({legible(sum(v.tamano for v in cuales))}), anteriores al {dia}.")
        else:
            plan.consequences.append(f"{lado.titulo}: nada anterior al {dia}.")

    plan.warnings.append(
        "Las versiones borradas no van a la papelera y no se recuperan. Lo que "
        "haya guardado cada lado es distinto: son dos históricos, no una copia.")
    return plan
