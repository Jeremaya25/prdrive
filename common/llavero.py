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
  `Vigilancia` en su espera entre ciclos. Un agente de antes del llavero
  tiene el registro pero no lo atiende: no cuenta.
- Si no, el vigilante del llavero (`runsync.py --vigilar-llavero`), que arranca
  «Abrir llavero» (`lanzar_vigilante()`) y vive lo mismo que el KeePassXC de la
  unidad. Un registro propio (`registro_vigilante()`) impide que haya dos.

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
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from . import bisync, components, conflicts, kdbx, model, store
from .planificador import PoliticaCambios

LEEME = "LEEME.txt"
"""El compañero fijo de la base en `.keychain/` (H-12)."""
LEEME_TEXTO = (
    "Esta carpeta es el llavero de prdrive: la base de KeePassXC de este\n"
    "dispositivo. prdrive la sincroniza sola con la carpeta keychain/ del\n"
    "catálogo, en el remoto.\n"
    "\n"
    "No la toques a mano. Para abrir la base usa «Abrir llavero», en la ventana\n"
    "de prdrive, o Llavero.bat: así KeePassXC se abre con la configuración que\n"
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


def sin_listar(pair: model.Pair) -> list[str]:
    """Devuelve las bases de la unidad que no están en el listado de la última pasada buena.

    Es por un fallo de rclone (v1.75.1, y sigue en `master`): tras un conflicto
    que gana el remoto, `modifyListing()` (`cmd/bisync/listing.go`) apunta el
    renombrado del perdedor de este lado quitando el nombre de la base de los
    dos listados, aunque la copia del ganador ya está con ese nombre. La pasada
    siguiente la ve «nueva en los dos lados»: si son iguales no pasa nada, pero
    si la base ha cambiado aquí entretanto (es lo que hace «Combinar») sale
    otro conflicto, con una copia que no trae nada nuevo. Una pasada justo
    después, con las dos iguales, la vuelve a apuntar («Files are equal!»).
    Sin listado, nada: no ha habido pasada buena.
    """
    listado = listado_local(pair)
    if listado is None:
        return []
    donde = pair.local_abs
    nombres = [r.relative_to(donde).as_posix() for r in bases(donde)]
    return [n for n in nombres if n not in listado]


FRENO_SIN_COPIAS = 100
"""El `--max-delete` (un %) de la pasada que se repite cuando lo borrado son solo copias."""
_BORRADO = re.compile(r": - (Path[12]) +File was deleted +- (.*)$")
"""Una línea de bisync que dice que algo del listado anterior ya no está en ese lado.

Es `b.indent(msg, file, "File was deleted")` de `findDeltas()`
(`cmd/bisync/deltas.go`) con el formato «- %-18s%-43s - %s» de `indent()`
(`cmd/bisync/log.go`); el nombre va entre comillas si tiene algo no imprimible
(`escapePath()`). Visto con rclone v1.75.1: `INFO  : - Path1             File was
deleted                            - Personal.conflicto-dispositivo1.kdbx`.
"""


def solo_copias_borradas(log: str, pair: model.Pair) -> list[str] | None:
    """Devuelve lo que bisync ve borrado, si son solo copias de conflicto de una base.

    Es para el freno de borrados (`--max-delete`, un % del listado anterior que
    vale para los dos lados): el llavero tiene tres o cuatro ficheros, así que
    quitar una copia de conflicto ya pasa del 25 % y la pasada aborta con «too
    many deletes» una y otra vez. Pasa al combinar: «Combinar» aparta la copia a
    `.prversions/`, y en los demás dispositivos la ven irse del remoto. Esas
    copias se pueden borrar, porque el backup-dir guarda la de cada lado. Una
    base o `LEEME.txt` no: si están entre lo borrado, el freno sigue mandando.

    Args:
        log: El log de la pasada que ha abortado.
        pair: La pareja del llavero.

    Returns:
        Los nombres, si todo lo borrado es copia de conflicto de una base, o
        `None` si no hay nada borrado o algo no lo es.
    """
    nombres = [m.group(2) for m in map(_BORRADO.search, log.splitlines()) if m]
    if not nombres:
        return None
    esq = conflicts.esquema(pair)
    for nombre in nombres:
        leido = None if nombre.startswith('"') or "/" in nombre \
            else conflicts.leer_nombre(nombre, esq)
        if leido is None or not leido[0].endswith(".kdbx"):
            return None
    return nombres


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
    """Indica si el servicio de esta raíz está vivo en este equipo y lleva el llavero.

    Es el registro del servicio (`model.daemon_lock()`), que escriben el de
    runsync y el agente del equipo cuando atienden la raíz: entonces el
    llavero es cosa suya y el vigilante sobra. Salvo un agente cuyas parejas
    (`pairs`) no lo traen: es uno de antes del llavero, o uno que leyó el
    config antes de activarlo, y no lo atiende. El servicio de runsync es el
    código de esta misma unidad, así que siempre lo lleva.
    """
    info = store.read_json(model.daemon_lock()) or None
    if not vivo_aqui(info):
        return False
    parejas = info.get("pairs")
    return not info.get("agente") or (isinstance(parejas, list) and model.LLAVERO in parejas)


KEEPASSXC_LINUX = "keepassxc"
"""El nombre del programa de KeePassXC en Linux: extraído, de Flathub o de la distribución."""
MIRAR_ORDENES = os.name != "nt"
"""Si se mira la línea de órdenes de los procesos para saber de qué unidad son.

Es lo de Linux (`store.orden_de()`); en Windows basta con el ejecutable, y
recorrer los procesos dos veces cuesta. Los tests lo encienden en cualquier
sistema.
"""


def _nombra_la_unidad(orden: list[str], app_dir: Path) -> bool:
    """Indica si una línea de órdenes nombra algo de esa unidad: su KeePassXC o su llavero.

    Es como se sabe de qué unidad es un KeePassXC de Linux, que no corre desde
    ella: «Abrir llavero» le pasa `--config` dentro de
    `.prdrive/keepassxc/config/linux/` y la base de `.keychain/`
    (`keepassxc.orden()`). Las rutas se comparan resueltas.
    """
    dentro = [os.path.realpath(app_dir / components.KEEPASSXC_SUBDIR),
              os.path.realpath(app_dir.parent / model.LLAVERO_LOCAL)]
    for arg in orden[1:]:
        ruta = os.path.realpath(arg) if os.path.isabs(arg) else None
        if ruta and any(ruta.startswith(d + os.sep) for d in dentro):
            return True
    return False


def pids_keepassxc(app_dir: Path | str | None = None) -> list[int]:
    """Devuelve los pids del KeePassXC de esa unidad (sin su proxy).

    En Windows, un `KeePassXC.exe` que corre desde la carpeta de un paquete de
    la unidad. En Linux corre fuera de ella (extraído en el equipo, o el del
    equipo en Linux ARM64), así que cuenta un `keepassxc` cuya línea de órdenes
    nombra algo de la unidad (`_nombra_la_unidad()`). El proxy no cuenta: vive
    lo que el navegador, no lo que KeePassXC. `store.procesos_desde()`,
    `store.procesos()` y `store.orden_de()` son los puntos de sustitución de
    los tests.
    """
    app = Path(app_dir) if app_dir is not None else model.APP_DIR
    salida: list[int] = []
    for paquete in components.paquetes_keepassxc(app):
        if components.keepassxc_programa(paquete) != components.KEEPASSXC_EXE:
            continue
        carpeta = components.keepassxc_dir(app, paquete)
        for pid, exe in store.procesos_desde(carpeta).items():
            if Path(exe).name.lower() == components.KEEPASSXC_EXE.lower():
                salida.append(pid)
    if MIRAR_ORDENES:
        for pid, exe in store.procesos().items():
            if (pid not in salida and Path(exe).name == KEEPASSXC_LINUX
                    and _nombra_la_unidad(store.orden_de(pid), app)):
                salida.append(pid)
    return salida


def keepassxc_abierto(app_dir: Path | str | None = None) -> bool:
    """Indica si el KeePassXC de la unidad está abierto (`pids_keepassxc()`)."""
    return bool(pids_keepassxc(app_dir))


def parada_vigilante() -> Path:
    """Devuelve el fichero que pide al vigilante del llavero que pare (`state/llavero.stop`)."""
    return model.STATE_DIR / "llavero.stop"


def vigilante_vivo() -> bool:
    """Indica si hay un vigilante del llavero vivo en este equipo."""
    return vivo_aqui(store.read_json(registro_vigilante()) or None)


def lanzar_vigilante() -> int | None:
    """Arranca el vigilante del llavero, suelto y sin ventana, si hace falta.

    No hace falta si el servicio o el agente atienden la raíz, o si ya hay uno.
    Lo llama «Abrir llavero», desde la ventana o desde `runsync.py --llavero`.
    Es función de módulo para que los tests la sustituyan.

    Returns:
        El pid del vigilante lanzado, o `None` si no se ha lanzado.
    """
    if atiende_el_servicio() or vigilante_vivo():
        return None
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL, "close_fds": True,
                    "cwd": tempfile.gettempdir()}
    if os.name == "nt":
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        exe = str(pythonw) if pythonw.exists() else sys.executable
        kwargs["creationflags"] = model.CREATE_NO_WINDOW | model.CREATE_NEW_PROCESS_GROUP
    else:
        exe = sys.executable
        kwargs["start_new_session"] = True
    return subprocess.Popen([exe, str(model.RUNSYNC_PY), "--vigilar-llavero"], **kwargs).pid


SIN_TIEMPO = 124
"""El código de `pasada()` cuando se acaba su tope, como el de `timeout(1)`."""


def matar_arbol(pid: int) -> None:
    """Termina un proceso y todos sus hijos; de módulo para que los tests no maten nada.

    Para una pasada que se pasa de su tope: matar solo `sync.py` dejaría su
    rclone vivo, con ficheros del volumen abiertos.
    """
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True,
                       creationflags=model.CREATE_NO_WINDOW)
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        pass                                  # ya no estaba


def pasada(tope: float | None = None) -> tuple[int, str]:
    """Hace una pasada del llavero sin terminal (`sync.py keychain`).

    Es «traer lo último» al abrir y «subir lo pendiente» al expulsar. Si hace
    falta un `--resync`, lo hace sola (`sync._bisync_preflight()`). Es función
    de módulo para que los tests no lancen nada.

    Args:
        tope: Segundos como mucho; pasados, se termina con sus hijos y sale
            `SIN_TIEMPO`.

    Returns:
        `(código de sync.py, su salida)`.
    """
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = model.CREATE_NO_WINDOW | model.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen([sys.executable, str(model.SYNC_PY), model.LLAVERO],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", **kwargs)
    try:
        salida, _ = proc.communicate(timeout=tope)
    except subprocess.TimeoutExpired:
        matar_arbol(proc.pid)
        salida, _ = proc.communicate()
        return SIN_TIEMPO, salida or ""
    return proc.returncode, salida or ""


# --- activarlo y desactivarlo: lo que se pone en el dispositivo

LANZADOR = "Llavero.bat"
"""El lanzador de «Abrir llavero» en la raíz del volumen, junto a `runsync.bat`."""
LANZADOR_BAT = (
    "@echo off\r\n"
    "rem Llavero.bat - Abre el llavero de prdrive: KeePassXC con la base de este\r\n"
    "rem dispositivo. Es runsync.bat --llavero: el mismo Python, buscado igual.\r\n"
    "rem Lo pone prdrive al activar el llavero y lo quita al desactivarlo.\r\n"
    'call "%~dp0runsync.bat" --llavero\r\n'
)
"""Lo que dice `Llavero.bat`: llama a `runsync.bat`, que ya sabe qué Python usar."""
LANZADOR_LINUX = "llavero.sh"
"""El de Linux, junto a `runsync.sh`. Van los dos: la unidad va de un sistema a otro."""
LANZADOR_SH = (
    "#!/bin/sh\n"
    "# llavero.sh - Abre el llavero de prdrive: KeePassXC con la base de este\n"
    "# dispositivo. Es runsync.sh --llavero: el mismo Python, buscado igual.\n"
    "# Lo pone prdrive al activar el llavero y lo quita al desactivarlo.\n"
    'exec sh "$(dirname "$0")/runsync.sh" --llavero "$@"\n'
)
"""Lo que dice `llavero.sh`: `sh runsync.sh`, que no necesita el bit de ejecución (exFAT)."""
LANZADORES = ((LANZADOR, LANZADOR_BAT), (LANZADOR_LINUX, LANZADOR_SH))
"""Los dos lanzadores de la raíz y lo que dice cada uno."""
COPIA_PROPIA = "conflicto-dispositivo"
"""El sufijo de una base que entra como copia de conflicto de este lado (path1)."""


def escribir_lanzador(raiz: Path | None = None) -> list[Path]:
    """Pone `Llavero.bat` y `llavero.sh` en la raíz del volumen.

    `llavero.sh` con el bit de ejecución donde el sistema de ficheros lo
    guarda (en exFAT no hay; `sh llavero.sh` va igual).

    Returns:
        Los dos.

    Raises:
        OSError: Si no se puede escribir.
    """
    raiz = model.DEVICE_ROOT if raiz is None else Path(raiz)
    escritos = []
    for nombre, texto in LANZADORES:
        ruta = raiz / nombre
        ruta.write_bytes(texto.encode("ascii"))
        escritos.append(ruta)
    try:
        (raiz / LANZADOR_LINUX).chmod(0o755)
    except OSError:
        pass
    return escritos


def lanzadores_puestos(raiz: Path | None = None) -> list[str]:
    """Devuelve cuáles de los dos lanzadores están en la raíz del volumen."""
    raiz = model.DEVICE_ROOT if raiz is None else Path(raiz)
    return [nombre for nombre, _ in LANZADORES if (raiz / nombre).is_file()]


def quitar_lanzador(raiz: Path | None = None) -> list[str]:
    """Quita `Llavero.bat` y `llavero.sh` de la raíz del volumen, cada uno si es el nuestro.

    Uno que alguien cambió no es nuestro, y se queda.

    Returns:
        Los que ha quitado.
    """
    raiz = model.DEVICE_ROOT if raiz is None else Path(raiz)
    quitados = []
    for nombre, texto in LANZADORES:
        ruta = raiz / nombre
        try:
            if ruta.read_bytes() != texto.encode("ascii"):
                continue
            ruta.unlink()
        except OSError:
            continue
        quitados.append(nombre)
    return quitados


def nombre_de_base(nombre: str) -> str:
    """Devuelve el nombre con el que una base entra en el llavero.

    La extensión va en minúsculas, porque el filtro `+ *.kdbx` distingue.

    Raises:
        ValueError: Si no es una `.kdbx` con nombre (o empieza por punto).
    """
    ruta = Path(nombre)
    if ruta.suffix.lower() != ".kdbx" or not ruta.stem or ruta.name.startswith("."):
        raise ValueError(f"«{nombre}» no es una base de KeePassXC (.kdbx) con nombre.")
    return ruta.stem + ".kdbx"


def copia_propia(donde: Path, base: str) -> Path:
    """Devuelve dónde entra una base de este dispositivo como copia de conflicto.

    Es el nombre que le pondría rclone al perdedor de este lado
    (`personal.conflicto-dispositivo1.kdbx`), con el primer número libre, así
    que «Abrir llavero» la encuentra y ofrece combinarla.
    """
    stem, ext = Path(base).stem, Path(base).suffix
    n = 1
    while (donde / f"{stem}.{COPIA_PROPIA}{n}{ext}").exists():
        n += 1
    return donde / f"{stem}.{COPIA_PROPIA}{n}{ext}"


def poner_base(origen: Path, destino: Path) -> None:
    """Copia una base al llavero sin tocar la original, y de una vez.

    Se copia a un temporal al lado y se renombra: una copia cortada no queda
    con el nombre de la base. Se comprueba entera antes del renombrado.

    Raises:
        OSError: Si no se puede copiar, o la copia no ha quedado entera.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".copiando")
    shutil.copyfile(origen, tmp)
    if tmp.read_bytes() != Path(origen).read_bytes():
        tmp.unlink(missing_ok=True)
        raise OSError(f"la copia de «{Path(origen).name}» no ha quedado igual")
    os.replace(tmp, destino)


def preparar_carpeta(raiz: Path | None = None) -> Path:
    """Crea `.keychain/` si falta, oculta y con su compañero fijo; devuelve la carpeta.

    Args:
        raiz: La raíz del volumen; sin ella, la de este dispositivo. El
            instalador da la del que está preparando.
    """
    donde = carpeta() if raiz is None else Path(raiz) / model.LLAVERO_LOCAL
    donde.mkdir(parents=True, exist_ok=True)
    store.hide(donde)
    asegurar_leeme(donde)
    return donde


class Alta(NamedTuple):
    """Cómo entra el llavero en un dispositivo (`decidir_alta()`).

    Args:
        tabla: El `[keychain]` que lleva el dispositivo desde ahora.
        destino: Dónde se copia la base que se ha dado, o `None` si no se copia
            ninguna (se trae la del remoto, o ya está igual).
        copia: Si `destino` es una copia de conflicto de la base que vale.
        subir: Si el catálogo del remoto todavía no tiene llavero y hay que
            escribirle el `[keychain]`.
        aviso_formato: Lo que hay que decir del formato de la base, o "".
    """
    tabla: dict
    destino: Path | None
    copia: bool
    subir: bool
    aviso_formato: str = ""


def decidir_alta(donde: Path, remota: dict | None, origen: Path | None,
                 pide: bool = False, nombre_llave: str = "") -> Alta:
    """Decide cómo entra el llavero: con qué `[keychain]` y dónde va la base.

    Es la regla de «Ajustes → Llavero…» y del asistente:
    - Si el remoto ya tiene llavero, la base es la suya: el `[keychain]` es el
      del remoto y una base propia entra como copia de conflicto, para
      combinarla al abrir.
    - Si no, la propia es la base y el catálogo se queda con su `[keychain]`.
      Si en el llavero ya hay otro fichero con ese nombre, la propia entra
      como copia de conflicto de él; si es el mismo, no se copia.

    Args:
        donde: La carpeta del llavero (`.keychain/`) del dispositivo.
        remota: El `[keychain]` del catálogo, o `None`.
        origen: La base que se da, o `None` para traer la del remoto.
        pide: Si la base que se da pide fichero llave.
        nombre_llave: Su nombre, como pista.

    Raises:
        ValueError: Con lo que hay que decir: no hay nada que traer, o lo que se
            da no es una base de KeePassXC entera.
    """
    if origen is None:
        if remota is None:
            raise ValueError("El remoto no tiene llavero que traer: activa el llavero "
                             "con una base.")
        return Alta(dict(remota), None, False, False)
    nombre = nombre_de_base(origen.name)
    estado = kdbx.comprobar(origen)
    if estado.entera is False:
        raise ValueError(f"«{origen.name}» no es una base de KeePassXC entera: "
                         f"{estado.motivo}.")
    aviso = ""
    if estado.version and estado.version.startswith("3"):
        aviso = (f"Es una base KDBX {estado.version}: KeePassXC la pasa a KDBX 4 la primera "
                 "vez que se guarda. No se pierde nada, pero un KeePassXC de antes de la 2.5 "
                 "ya no la abriría.")
    elif estado.entera is None:
        aviso = (f"prdrive no conoce este formato de base ({estado.motivo}): no podrá "
                 "comprobar que está entera antes de subirla.")
    if remota is not None:
        return Alta(dict(remota), copia_propia(donde, str(remota.get("base"))), True, False,
                    aviso)
    tabla = {"base": nombre, "fichero_llave": bool(pide)}
    if pide and nombre_llave:
        tabla["nombre_llave"] = nombre_llave
    destino = donde / nombre
    if destino.exists():
        if destino.read_bytes() == Path(origen).read_bytes():
            return Alta(tabla, None, False, True, aviso)
        return Alta(tabla, copia_propia(donde, nombre), True, True, aviso)
    return Alta(tabla, destino, False, True, aviso)
