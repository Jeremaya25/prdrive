#!/usr/bin/env python3
"""El llavero: la base de KeePassXC del dispositivo, que se sincroniza sola.

La base vive en `.keychain/`, en la raíz del dispositivo, y su pareja la
construye el código cuando hay `[keychain]` (`model.LLAVERO`): bisync con
versiones contra la subcarpeta `keychain/` de la carpeta del catálogo. Aquí van
las decisiones del llavero que no son de la pareja en sí: sin Tk, sin red y,
lo que toca el equipo, a través de funciones de módulo que los tests
sustituyen.

Quién lo atiende, una sola cosa a la vez (`Vigilancia`, sus reglas puras):
- El servicio del dispositivo o el agente del equipo, si alguno tiene el
  registro del servicio de esta raíz (`atiende_el_servicio()`). El agente lo
  trata como una pareja con `watch = true`; el servicio de runsync, con
  `Vigilancia` en su espera entre ciclos.
- Si no, el vigilante del llavero (`runsync.py --vigilar-llavero`), que arranca
  «Llavero» y vive lo mismo que el KeePassXC de la unidad. Un registro propio
  (`registro_vigilante()`) impide que haya dos.

Lo de antes de cada pasada (`preparar()`, lo llama `sync.py`):
- El compañero fijo, `LEEME.txt`: con una sola base, un guardado sería «han
  cambiado todos los ficheros» y bisync se pararía (H-12). Si falta, se pone;
  si la persona lo cambió, no se toca.
- Que cada base esté entera (`common/kdbx.py`): una a medio guardar no se sube.
  Se mira otra vez a los `ESPERA_ENTERA` segundos, por si el guardado estaba
  acabando.
"""

from __future__ import annotations

import calendar
import json
import re
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from . import bisync, components, kdbx, model, store
from .planificador import PoliticaCambios

LEEME = "LEEME.txt"
"""El compañero fijo de la base en `.keychain/` (H-12)."""
LEEME_TEXTO = (
    "Esta carpeta es el llavero de prdrive: la base de KeePassXC de este\n"
    "dispositivo. prdrive la sincroniza sola con la carpeta keychain/ del\n"
    "catálogo, en el remoto.\n"
    "\n"
    "No la toques a mano. Para abrir la base usa «Llavero», en la ventana de\n"
    "prdrive o en Llavero.bat: así KeePassXC se abre con la configuración que\n"
    "viaja en la unidad y lo que guardes sube solo.\n"
    "\n"
    "Este fichero no cambia nunca. Está aquí para que una base guardada no\n"
    "parezca «ha cambiado todo» a quien sincroniza.\n"
)
"""Lo que dice `LEEME.txt`. No se cambia: un cambio viajaría a todos los dispositivos."""
ESPERA_ENTERA = 2.0  # segundos
"""Lo que se espera antes de mirar otra vez una base que no está entera."""


def dormir(segundos: float) -> None:
    """Espera; es de módulo para que los tests no esperen de verdad."""
    time.sleep(segundos)


def carpeta() -> Path:
    """Devuelve la carpeta del llavero en este dispositivo (`.keychain/`).

    Es función y no constante porque los tests reenganchan `model.DEVICE_ROOT`.
    """
    return model.DEVICE_ROOT / model.LLAVERO_LOCAL


def bases(donde: Path) -> list[Path]:
    """Devuelve las bases de esa carpeta que viajan, también las de un conflicto.

    Son los `*.kdbx` de la carpeta y de sus subcarpetas, salvo `.prversions/` y
    las copias de antes de guardar (`*.old.kdbx`), que no viajan
    (`model.LLAVERO_REGLAS`).
    """
    try:
        candidatas = sorted(donde.rglob("*.kdbx"))
    except OSError:
        return []
    salida = []
    for ruta in candidatas:
        relativa = ruta.relative_to(donde).parts
        if model.VERSIONS_DIR in relativa or ruta.name.lower().endswith(".old.kdbx"):
            continue
        salida.append(ruta)
    return salida


class Rota(NamedTuple):
    """Una base que no está entera.

    Args:
        ruta: El fichero.
        motivo: Qué le pasa (`kdbx.Estado.motivo`).
    """
    ruta: Path
    motivo: str


def rotas(donde: Path) -> list[Rota]:
    """Devuelve las bases que no están enteras, mirándolas dos veces.

    Una que no está entera se vuelve a mirar a los `ESPERA_ENTERA` segundos:
    puede ser un guardado que estaba acabando. Un formato que no se conoce no
    cuenta como rota (`kdbx.mirar()`).
    """
    malas = [r for r in bases(donde) if kdbx.comprobar(r).entera is False]
    if not malas:
        return []
    dormir(ESPERA_ENTERA)
    salida = []
    for ruta in malas:
        estado = kdbx.comprobar(ruta)
        if estado.entera is False:
            salida.append(Rota(ruta, estado.motivo))
    return salida


def asegurar_leeme(donde: Path) -> bool:
    """Pone `LEEME.txt` si falta; si está, no lo toca aunque diga otra cosa.

    Se escriben los bytes tal cual, con `\\n` en todos los sistemas: dos
    dispositivos que lo pongan cada uno el suyo tienen que dejar el mismo
    fichero, o se pisarían en el remoto.

    Returns:
        True si lo ha escrito.
    """
    return store.crear_exclusivo(donde / LEEME, LEEME_TEXTO.encode("utf-8")) is True


def preparar(pair: model.Pair) -> str | None:
    """Prepara la pareja del llavero para una pasada y dice si no se puede subir.

    Pone el compañero fijo y comprueba las bases. No crea la carpeta: eso lo
    decide `sync.py` con sus reglas (nunca si hay baseline).

    Returns:
        El motivo para no hacer la pasada, o `None` si se puede.
    """
    donde = pair.local_abs
    try:
        if not donde.is_dir():
            return None
    except OSError:
        return None
    asegurar_leeme(donde)
    malas = rotas(donde)
    if not malas:
        return None
    lista = "; ".join(f"{r.ruta.name}: {r.motivo}" for r in malas)
    return (f"la base no está entera ({lista}). No se sube: puede que KeePassXC "
            f"la estuviera guardando. Se volverá a intentar en la próxima pasada.")


POLITICA = PoliticaCambios()
"""Las reglas de los cambios locales: las del agente (`planificador.PoliticaCambios`)."""
REMOTO_ABIERTO = 5 * 60.0  # segundos
"""Cada cuánto se trae lo de otro dispositivo mientras KeePassXC está abierto."""
TOPE_REINTENTO = 30 * 60.0  # segundos
"""Lo más que crece la espera entre pasadas que fallan (sin red, por ejemplo)."""


def huella(donde: Path) -> tuple:
    """Devuelve la foto de las bases de esa carpeta: ruta, tamaño, `mtime_ns` y semilla.

    La semilla (`kdbx.semilla()`) distingue dos guardados del mismo tamaño en el
    mismo tic de reloj (en exFAT, de 10 ms). Nunca lanza: lo que no se deja
    mirar sale sin datos, y eso también es un cambio si antes los tenía.
    """
    foto = []
    for ruta in bases(donde):
        try:
            st = ruta.stat()
            datos = (st.st_size, st.st_mtime_ns)
        except OSError:
            datos = (None, None)
        foto.append((ruta.relative_to(donde).as_posix(), *datos, kdbx.semilla(ruta)))
    return tuple(foto)


_LINEA = re.compile(r'^\S+\s+(-?\d+)\s+\S+\s+\S+\s+(\S+)\s+(".*")$')
"""Una línea de un listado de bisync: banderas, tamaño, hash, id, hora y nombre.

Es el `lineFormat` de `cmd/bisync/listing.go` («%s %8d %s %s %s %q»), visto con
rclone v1.75.1: `-        5 - - 2026-10-05T06:44:29.752645891+0000 "personal.kdbx"`.
"""
_HORA = re.compile(r"^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d{1,9}))?([+-])(\d\d):?(\d\d)$")
"""La hora de un listado: con los nanosegundos y la zona (`2006-01-02T15:04:05.000000000-0700`)."""


def _nanosegundos(texto: str) -> int | None:
    """Convierte la hora de un listado en nanosegundos desde 1970, o `None` si no se lee."""
    m = _HORA.match(texto)
    if m is None:
        return None
    ano, mes, dia, hh, mm, ss = (int(x) for x in m.groups()[:6])
    fraccion = int((m.group(7) or "0").ljust(9, "0"))
    signo = -1 if m.group(8) == "-" else 1
    zona = signo * (int(m.group(9)) * 3600 + int(m.group(10)) * 60)
    segundos = calendar.timegm((ano, mes, dia, hh, mm, ss)) - zona
    return segundos * 1_000_000_000 + fraccion


def listado_local(pair: model.Pair) -> dict[str, tuple[int, int]] | None:
    """Devuelve lo que dice el listado `path1` de la última pasada buena del lado local.

    Returns:
        `{ruta: (tamaño, mtime_ns)}`, o `None` si no hay listado o no se lee.
    """
    ruta = pair.workdir / f"{bisync.expected_prefix(pair)}{bisync.PATH1_SUFFIX}"
    try:
        lineas = ruta.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return None
    salida: dict[str, tuple[int, int]] = {}
    for linea in lineas:
        m = _LINEA.match(linea)
        if m is None:
            continue
        try:
            nombre = json.loads(m.group(3))
        except ValueError:
            continue
        hora = _nanosegundos(m.group(2))
        if isinstance(nombre, str) and hora is not None:
            salida[nombre] = (int(m.group(1)), hora)
    return salida


def pendiente(pair: model.Pair) -> bool:
    """Indica si hay algo del llavero sin subir.

    Es que alguna base no coincide, en tamaño y en `mtime`, con su línea del
    listado `path1` de la última pasada buena (`state/keychain/`). No hace falta
    otro registro, y pilla también lo que se guardó DURANTE una pasada. Sin
    listado (no ha habido pasada buena) cualquier base está pendiente.
    """
    donde = pair.local_abs
    lista = bases(donde)
    if not lista:
        return False
    listado = listado_local(pair)
    if listado is None:
        return True
    for ruta in lista:
        try:
            st = ruta.stat()
        except OSError:
            return True
        if listado.get(ruta.relative_to(donde).as_posix()) != (st.st_size, st.st_mtime_ns):
            return True
    return False


@dataclass
class Vigilancia:
    """Cuándo toca una pasada del llavero, con las reglas de `PoliticaCambios`.

    Pura: quien la usa le da la hora (`time.monotonic()`), la foto (`huella()`)
    y si hay algo pendiente, y hace la pasada cuando `motivo()` lo dice. Una
    ráfaga de guardados es una sola pasada (cada cambio mueve la calma), y
    entre dos pasadas adelantadas por cambios hay al menos `separacion`.

    Args:
        foto: La última foto, o `None` antes de la primera.
        cambio: Cuándo se vio el último cambio sin pasada, o `None`.
        ultima: Cuándo empezó la última pasada, o `None` si no ha habido.
        mirada: Cuándo se tomó la última foto.
        fallos: Cuántas pasadas seguidas han fallado: cada una dobla la
            separación, hasta `TOPE_REINTENTO`, para que un llavero sin red no
            lo intente cada dos minutos.
        abierto: Si en la última foto el KeePassXC de la unidad estaba
            abierto: se mira con ella, no en cada vuelta, porque en Windows
            es recorrer todos los procesos del equipo.
    """
    foto: tuple | None = None
    cambio: float | None = None
    ultima: float | None = None
    mirada: float | None = None
    fallos: int = 0
    abierto: bool = False

    @property
    def separacion(self) -> float:
        """Devuelve los segundos que tienen que pasar desde la última pasada."""
        return min(POLITICA.separacion * 2 ** self.fallos, TOPE_REINTENTO)

    def toca_mirar(self, ahora: float) -> bool:
        """Indica si ya toca otra foto (`PoliticaCambios.sondeo`)."""
        return self.mirada is None or ahora - self.mirada >= POLITICA.sondeo

    def observar(self, foto: tuple, ahora: float, sin_subir: bool = False) -> None:
        """Apunta una foto nueva.

        Args:
            foto: Lo que dice `huella()`.
            ahora: La hora.
            sin_subir: Si `pendiente()` dice que hay algo sin subir: en la
                primera foto, cuenta como un cambio (lo dejó otra sesión).
        """
        if self.foto is None:
            if sin_subir:
                self.cambio = ahora
        elif foto != self.foto:
            self.cambio = ahora
        self.foto, self.mirada = foto, ahora

    def motivo(self, ahora: float, abierto: bool) -> str | None:
        """Dice si toca una pasada y por qué.

        Args:
            ahora: La hora.
            abierto: Si KeePassXC corre desde la unidad: entonces lo de otro
                dispositivo se trae cada `REMOTO_ABIERTO`.

        Returns:
            `cambios`, `remoto` o `None`.
        """
        separado = self.ultima is None or ahora >= self.ultima + self.separacion
        if self.cambio is not None and ahora >= self.cambio + POLITICA.calma and separado:
            return "cambios"
        cada = max(REMOTO_ABIERTO, self.separacion if self.fallos else 0.0)
        if abierto and (self.ultima is None or ahora >= self.ultima + cada):
            return "remoto"
        return None

    def empieza_pasada(self, ahora: float) -> None:
        """Apunta que empieza una pasada: atiende el cambio que hubiera."""
        self.ultima, self.cambio = ahora, None

    def acaba_pasada(self, foto: tuple, ahora: float, sin_subir: bool, bien: bool) -> None:
        """Apunta cómo quedó la carpeta tras la pasada.

        Lo que se guardó mientras corría no se pierde: si `pendiente()` dice
        que hay algo sin subir, es un cambio nuevo.

        Args:
            foto: Lo que dice `huella()` ahora.
            ahora: La hora.
            sin_subir: Lo que dice `pendiente()` ahora.
            bien: Si la pasada acabó bien; si no, la siguiente espera más.
        """
        self.foto, self.mirada = foto, ahora
        self.fallos = 0 if bien else self.fallos + 1
        if sin_subir:
            self.cambio = ahora


def registro_vigilante() -> Path:
    """Devuelve el registro del vigilante del llavero (`state/llavero.lock.json`).

    Es función por lo mismo que `model.daemon_lock()`: los tests mueven
    `STATE_DIR`.
    """
    return model.STATE_DIR / "llavero.lock.json"


def equipo() -> str:
    """Devuelve el nombre de este equipo, como `prefs.HOST` (que es de `ui/`)."""
    return socket.gethostname()


def vivo_aqui(info: dict | None) -> bool:
    """Indica si un registro (`pid`, `host`) es de un proceso vivo de este equipo."""
    if not isinstance(info, dict) or info.get("host") != equipo():
        return False
    try:
        return store.pid_alive(int(info.get("pid", -1)))
    except (TypeError, ValueError):
        return False


def atiende_el_servicio() -> bool:
    """Indica si el servicio de esta raíz está vivo en este equipo.

    Es el registro del servicio (`model.daemon_lock()`), que escriben el de
    runsync y el agente del equipo cuando atienden la raíz: entonces el
    llavero es cosa suya y el vigilante sobra.
    """
    return vivo_aqui(store.read_json(model.daemon_lock()) or None)


def keepassxc_abierto(app_dir: Path | str | None = None) -> bool:
    """Indica si el KeePassXC de la unidad está abierto.

    Solo cuenta `KeePassXC.exe`: el proxy (`keepassxc-proxy.exe`) vive lo que
    el navegador, no lo que KeePassXC. `store.procesos_desde()` es el punto de
    sustitución de los tests.
    """
    for paquete in components.paquetes_keepassxc(app_dir):
        carpeta = components.keepassxc_dir(app_dir, paquete)
        for exe in store.procesos_desde(carpeta).values():
            if Path(exe).name.lower() == components.KEEPASSXC_EXE.lower():
                return True
    return False
