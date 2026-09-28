#!/usr/bin/env python3
"""
components.py — Poner al día el rclone, el Python y el VeraCrypt que lleva un dispositivo.

El otro extremo de `common/components.py`: aquel LEE los sellos y dice qué está
anticuado —desde el propio dispositivo, al instante y sin red—; esto lo ARREGLA,
y para eso hay que bajar, comprobar y sustituir, que es justo lo que el
instalador ya sabe hacer (`rclone_bin`, `runtime_bin`, `deploy`).

Y por eso vive aquí y no en `common/`: `install/` no viaja al dispositivo a
propósito, así que esto se ejecuta desde el zip del código que `common/update.py`
acaba de descargar y verificar, igual que el aplicador de la actualización del
programa. **La versión que fija los componentes es la que los instala**, y no hay
una segunda copia de la maquinaria de descarga esperando a quedarse atrás.

**El intercambio es el de `deploy.install_runtime()`, también para rclone**: se
escribe al lado, se aparta el de antes y se coloca el nuevo de un renombrado, que
es atómico en los dos sistemas. Lo que NO se hace es copiar encima del binario
que hay: `shutil.copy2` trunca y luego escribe, y un corte a mitad dejaría el
dispositivo con un rclone roto, que es el único que tiene.

**Y lo que está en uso no se toca.** Un rclone sincronizando ahora mismo y el
Python desde el que está abierto este mismo programa se POSPONEN con su motivo;
lo demás se hace igual. Posponer es una decisión, no una limitación: en Windows
el renombrado colaría —un `.exe` en marcha se puede apartar, lo que no se puede
es borrar—, pero cambiarle el binario a una sincronización a media pasada no es
algo que deba ocurrir sin que nadie lo haya pedido. El Python de la ventana es
la excepción que sí se termina: con `--relevo` lo cambia, con la ventana ya
cerrada, un proceso que corre desde el temporal del equipo (ver «El relevo»).

**El VeraCrypt de viaje va por el mismo camino**, con la carpeta entera en vez
de un binario: `traveler.poner_portatil()` la sustituye con el mismo intercambio,
después de mirar el sitio libre de la raíz física. Si está en uso
(`veracrypt_en_uso()`) se pospone. Y uno SIN sello —la copia de una instalación
que dejaban las versiones anteriores— no se toca nunca desde aquí: su vestíbulo
solo sabe abrir esa disposición, y el vestíbulo no es cosa de una actualización
de componentes. Se pospone diciendo que eso es de «Añadir plataformas…», que
cambia las dos cosas a la vez.

Lo que aquí no pasa nunca: instalar una plataforma que el dispositivo no lleva
(eso es «Añadir plataformas…», y es una decisión con sitio en disco de por
medio), tocar el código, los lanzadores, el vestíbulo, la configuración o las
claves.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# Los nombres sueltos y no el módulo: este fichero se llama igual que aquel, y
# un `components.pendientes(...)` dentro de `install/components.py` sería una
# adivinanza sobre cuál de los dos se está leyendo.
from common import pins
from common.components import PYTHON, RCLONE, VERACRYPT, Pendiente, corre_desde
from common.components import pendientes as sellos_pendientes
from common.store import pid_alive

from . import IS_WIN, InstallError
from . import deploy, platforms, rclone_bin, runtime_bin, traveler, veracrypt_bin

Progreso = Callable[[str], None]

# El relevo: una carpeta en el temporal de ESTE equipo con un Python y una copia
# de este código, desde la que se termina el trabajo con la ventana cerrada.
RELEVO_PREFIJO = "prdrive-relevo-"
RELEVO_DUENNO = "owner.pid"
RELEVO_LOG = "relevo.log"
# Cuánto espera el relevo a que se cierre la ventana. La ventana se cierra sola
# en cuanto se cierra la de salida, pero eso lo decide quien mira: media hora y,
# si sigue abierta, se rinde sin tocar nada.
ESPERA_MAXIMA = 30 * 60


@dataclass
class Resultado:
    """Qué se ha hecho, qué se ha dejado para luego y qué ha salido mal.

    Pospuesto y fallido son cosas distintas y se cuentan aparte: lo primero es
    normal —había una sincronización en marcha— y lo segundo no —una suma que no
    cuadra—. Quien llama decide con `fallidos` si esto fue un error; el recuadro
    ámbar se apaga solo, porque los sellos ya dicen la verdad."""
    hechos: list[str] = field(default_factory=list)
    pospuestos: list[str] = field(default_factory=list)
    fallidos: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.fallidos


# ---------------------------------------------------------------------------
# ¿Está en uso?
# ---------------------------------------------------------------------------
# Las dos son funciones de módulo a propósito, como `conflict_editor.mover()` o
# `runsync.notificar_fallo()`: los tests las sustituyen enteras, y así ninguno
# depende de tener un rclone corriendo ni de qué Python ejecuta la batería.

def rclone_en_uso(ruta: Path) -> bool:
    """¿Se está ejecutando ese rclone, o no se puede escribir donde está?

    Se pregunta abriendo el fichero para escritura, que contesta en los dos
    sistemas sin enumerar procesos: en Windows, un `.exe` cuya imagen está
    mapeada da ERROR_SHARING_VIOLATION; en Linux, `open(O_RDWR)` sobre un
    binario en ejecución da ETXTBSY. Un volumen de solo lectura también falla, y
    aquí significa lo mismo: ahora no.

    Que no exista no es «en uso»: no hay nada que sustituir y el intercambio se
    encargará de crearlo."""
    try:
        if not ruta.is_file():
            return False
        with open(ruta, "r+b"):
            return False
    except OSError:
        return True


def runtime_en_uso(carpeta: Path) -> bool:
    """¿Corre ESTE proceso desde ese runtime?

    Es el caso normal y no una rareza: en un dispositivo con Python propio, la
    ventana que ofrece la actualización arrancó desde `runtime/<clave>/`, y este
    proceso es hijo suyo y usa el mismo intérprete (`update.components_command()`
    pasa `sys.executable` a propósito). En Windows no se puede renombrar la
    carpeta de un `pythonw.exe` vivo, así que sin esto se bajarían 30 MB para
    fallar al final. Ese caso lo termina el relevo (`preparar_relevo()`)."""
    return corre_desde(carpeta)


def veracrypt_en_uso(carpeta: Path) -> bool:
    """¿Está en uso el VeraCrypt de esa carpeta?

    El mismo truco que `rclone_en_uso()`, fichero a fichero: un `VeraCrypt-x64.exe`
    en marcha no se deja abrir para escribir. Es el caso normal más que una
    rareza: si el contenedor se abrió con el VeraCrypt que viaja, la copia
    elevada puede seguir viva, y apartar la carpeta con ella dentro fallaría.
    Que no exista no es «en uso»: no hay nada que apartar."""
    try:
        ficheros = [p for p in Path(carpeta).iterdir() if p.is_file()]
    except OSError:
        return False
    return any(rclone_en_uso(p) for p in ficheros)


# ---------------------------------------------------------------------------
# El intercambio
# ---------------------------------------------------------------------------

def _limpiar_restos(carpeta: Path) -> None:
    """Barre lo que dejó un intercambio anterior. Silencioso y best-effort.

    Un `.rclone.exe.viejo-1234` solo aparece cuando no se pudo borrar el de
    antes —Windows no borra un `.exe` en marcha—, y entonces lo que procede es
    volver a intentarlo la próxima vez, no dar un error por algo que ya está
    resuelto.

    Uno atascado no para el barrido de los demás: el que falla es justo el caso
    esperado —un `.viejo` que sujeta un rclone en marcha—, y como los `.viejo-*`
    van primero, abortar ahí dejaría los `.nuevo-*` sin barrer para siempre,
    acumulándose en un volumen extraíble."""
    for patron in (".*.viejo-*", ".*.nuevo-*"):
        try:
            restos = list(carpeta.glob(patron))
        except OSError:
            continue
        for resto in restos:
            try:
                resto.unlink(missing_ok=True)
            except OSError:
                pass


def swap_rclone(destino: Path, origen: Path) -> None:
    """Sustituye el binario de `destino` por el de `origen`, sin pasar por medio.

    Tres pasos, los mismos de `deploy.install_runtime()`: se copia al lado, se
    aparta el de antes con un renombrado y se coloca el nuevo con otro. El
    renombrado es atómico en los dos sistemas, así que en ningún instante hay
    medio rclone en `bin/` — y medio rclone es un dispositivo que no sincroniza
    en ningún equipo. Si el último paso falla, el de antes vuelve a su sitio; y
    si ni eso se puede, el error dice que esa plataforma se ha quedado sin rclone
    y cómo volver a ponerlo.

    Borrar el apartado es lo único que puede fallar sin consecuencias, y se deja
    para la próxima pasada (`_limpiar_restos`)."""
    destino, origen = Path(destino), Path(origen)
    nuevo = destino.with_name(f".{destino.name}.nuevo-{os.getpid()}")
    viejo = destino.with_name(f".{destino.name}.viejo-{os.getpid()}")
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origen, nuevo)
        if not IS_WIN:
            nuevo.chmod(nuevo.stat().st_mode | 0o755)
    except OSError as e:
        nuevo.unlink(missing_ok=True)
        raise InstallError(f"No he podido dejar el rclone nuevo junto a "
                           f"{destino}: {e}\nEl que había sigue en su sitio.") from e

    apartado = False
    if destino.exists():
        try:
            os.replace(destino, viejo)
            apartado = True
        except OSError as e:
            nuevo.unlink(missing_ok=True)
            raise InstallError(f"No he podido apartar el rclone de {destino}: "
                               f"{e}\nEl que había sigue en su sitio.") from e
    try:
        os.replace(nuevo, destino)
    except OSError as e:
        # Esta es la única rama que puede dejar `bin/` SIN rclone, y por eso es
        # la única que no se puede permitir escaparse cruda: `aplicar()` solo
        # recoge InstallError, así que un OSError de aquí abortaría la pasada
        # entera y se perdería el parte de lo hecho justo cuando hay algo urgente
        # que contar. Y un dispositivo sin binario ni siquiera vuelve a salir
        # como pendiente —`rclone_pendiente()` no compara lo que no está—, o sea
        # que si no lo dice este mensaje no lo dice nadie.
        if apartado:
            try:
                os.replace(viejo, destino)
            except OSError as otro:
                nuevo.unlink(missing_ok=True)
                raise InstallError(
                    f"No he podido colocar el rclone en {destino} ({e}) y "
                    f"tampoco devolver a su sitio el que había ({otro}).\n\n"
                    f"Esta plataforma se ha quedado sin rclone. Vuelve a "
                    f"ejecutar el instalador de prdrive, elige este dispositivo "
                    f"y pulsa «Añadir plataformas…».") from otro
        nuevo.unlink(missing_ok=True)
        raise InstallError(f"No he podido colocar el rclone en {destino}: {e}\n"
                           f"El que había sigue en su sitio.") from e
    if apartado:
        try:
            viejo.unlink()
        except OSError:
            pass        # Windows con rclone en marcha: se barre la próxima vez


# ---------------------------------------------------------------------------
# El plan y su ejecución
# ---------------------------------------------------------------------------

def pendientes(device_root: Path | str) -> list[Pendiente]:
    """Lo que ese dispositivo tiene por poner al día. Sin red, como el del
    dispositivo: la diferencia es que aquí se parte de la raíz del volumen."""
    return sellos_pendientes(deploy.app_dir(device_root))


def _poner_rclone(raiz: Path, p: Pendiente, decir: Progreso) -> str | None:
    """Sustituye un rclone. Devuelve el motivo si se pospone, None si se hizo."""
    destino = platforms.rclone_path(raiz, p.plataforma)
    _limpiar_restos(destino.parent)
    if rclone_en_uso(destino):
        return ("está en uso o no se puede escribir ahora. Se queda como "
                "estaba; vuelve a intentarlo cuando no haya ninguna "
                "sincronización en marcha.")
    decir(f"{p.titulo}: consiguiendo la versión {p.deberia}")
    binario = rclone_bin.pinned_rclone(p.plataforma, decir)
    decir(f"{p.titulo}: sustituyendo {destino}")
    swap_rclone(destino, binario)
    deploy.write_rclone_stamp(destino, p.plataforma, pins.RCLONE_VERSION)
    return None


def _poner_python(raiz: Path, p: Pendiente, decir: Progreso) -> str | None:
    """Sustituye un runtime. Devuelve el motivo si se pospone, None si se hizo."""
    carpeta = platforms.runtime_dir(raiz, p.plataforma)
    if runtime_en_uso(carpeta):
        return ("es el Python con el que está corriendo prdrive ahora mismo, "
                "así que no se puede sustituir mientras siga abierto. Desde la "
                "ventana, «Actualizar…» lo cambia cerrándola y volviéndola a "
                "abrir.")
    decir(f"{p.titulo}: consiguiendo la versión {p.deberia}")
    archivo = runtime_bin.ensure_runtime(p.plataforma, decir)
    decir(f"{p.titulo}: sustituyendo {carpeta}")
    deploy.install_runtime(raiz, p.plataforma, archivo)
    return None


SIN_SELLO = ("es una copia de antes, sin sello, y el vestíbulo de esta unidad solo "
             "sabe abrir esa. Se queda como está: ponlo al día con «Añadir "
             "plataformas…» del instalador, que cambia a la vez el VeraCrypt de la "
             "unidad (por el portable oficial, con x64 y ARM64) y el vestíbulo que "
             "lo abre.")


def _poner_veracrypt(raiz: Path, p: Pendiente, decir: Progreso) -> str | None:
    """Sustituye el VeraCrypt de viaje. Devuelve el motivo si se pospone.

    `raiz` es la del dispositivo (el contenedor montado); la carpeta que se
    sustituye es la de la raíz FÍSICA, que viene en `p.ruta`."""
    if p.asistente:
        return SIN_SELLO
    carpeta = p.ruta
    if carpeta is None:
        return "no sé dónde está su carpeta: pasa el instalador por encima."
    if veracrypt_en_uso(carpeta):
        return ("está en uso: VeraCrypt se está ejecutando desde esa carpeta. Se "
                "queda como estaba; vuelve a intentarlo cuando no lo esté.")
    decir(f"{p.titulo}: consiguiendo la versión {p.deberia}")
    origen = veracrypt_bin.ensure_veracrypt(decir)
    decir(f"{p.titulo}: sustituyendo {carpeta}")
    traveler.poner_portatil(carpeta.parent, origen)
    return None


PONER = {RCLONE: _poner_rclone, PYTHON: _poner_python, VERACRYPT: _poner_veracrypt}


def aplicar(device_root: Path | str, progreso: Progreso | None = None,
            pends: list[Pendiente] | None = None) -> Resultado:
    """Pone al día los componentes anticuados de ese dispositivo.

    Lo que se pueda: cada componente va por su cuenta, y uno que no se pueda
    tocar ahora no impide los demás. Nada queda a medias — lo que no se ha
    sustituido sigue exactamente como estaba, y su sello lo sigue diciendo, así
    que el aviso de la ventana se apaga solo en cuanto deja de haber motivo."""
    def decir(msg: str) -> None:
        if progreso:
            progreso(msg)

    raiz = Path(device_root)
    res = Resultado()
    if pends is None:
        pends = pendientes(raiz)

    for p in pends:
        poner = PONER[p.que]
        try:
            motivo = poner(raiz, p, decir)
        except (InstallError, OSError) as e:
            # El OSError es tan normal como el InstallError, y el camino más
            # corto hasta aquí es el más probable de todos: `urllib.error.URLError`
            # ES un OSError, así que quedarse sin red —o un proxy, o un tiempo de
            # espera— sale por aquí en cuanto se va a leer el SHA256SUMS. También
            # un volumen que se retira a media pasada. Ninguna de las dos cosas
            # es asunto de las demás plataformas: si se escapara, se perdería el
            # parte entero de una pasada que quizá ya había puesto al día media
            # docena de componentes, y esta función promete justo lo contrario.
            res.fallidos.append(f"{p.titulo}: {e}")
            continue
        if motivo is not None:
            res.pospuestos.append(f"{p.titulo}: {motivo}")
        else:
            res.hechos.append(f"{p.titulo}: {p.lleva} → {p.deberia}")
    return res


# ---------------------------------------------------------------------------
# El relevo: cambiar el Python con el que está abierta la ventana
# ---------------------------------------------------------------------------
# En un dispositivo con instalación completa, la ventana arranca desde
# `runtime/<clave>/` de este equipo, y este proceso es hijo suyo con el mismo
# intérprete. Esa carpeta no se puede apartar mientras la ventana siga abierta,
# así que desde ella el runtime de esta plataforma no se ponía al día NUNCA: el
# recuadro ámbar volvía cada vez, y lo que decía que hiciera (lanzar runsync con
# un Python instalado) es justo lo que un dispositivo que lleva el suyo no tiene.
#
# El relevo lo resuelve sin nada instalado. Se extrae en el temporal de ESTE
# equipo el runtime que se va a poner —el mismo archivo ya comprobado, que se
# queda en la caché—, se copia al lado este código (el zip descargado se borra
# en cuanto la ventana recupera el control) y se lanza desde ahí, suelto,
# `--update-components` con `--esperar` los pids de la ventana y de este
# proceso. Cuando los dos han salido, ningún proceso usa ya el runtime del
# dispositivo: se sustituye con el intercambio de siempre y se vuelve a abrir
# la ventana con él. Si algo sale mal, lo dice en una ventana con su registro.

def runtime_propio(device_root: Path | str,
                   pends: list[Pendiente]) -> Pendiente | None:
    """El Python pendiente desde el que corre este proceso, o None.

    Por `runtime_en_uso()`, la misma pregunta que hace `_poner_python()`, para
    que los tests la contesten en un solo sitio."""
    for p in pends:
        if (p.que == PYTHON and p.plataforma is not None
                and runtime_en_uso(platforms.runtime_dir(device_root, p.plataforma))):
            return p
    return None


def barrer_relevos(base: Path | None = None) -> int:
    """Borra las carpetas de relevo de procesos que ya no viven. Cuántas.

    El relevo no puede borrar la suya —está corriendo desde ella—, así que la
    barre el siguiente, como `remote.sweep_stale()` con las claves. Cada una
    dice de qué pid es; la de uno vivo no se toca."""
    base = base or Path(tempfile.gettempdir())
    borradas = 0
    for carpeta in base.glob(RELEVO_PREFIJO + "*"):
        try:
            duenno = int((carpeta / RELEVO_DUENNO).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            duenno = None
        if duenno is not None and pid_alive(duenno):
            continue
        shutil.rmtree(carpeta, ignore_errors=True)
        borradas += 1
    return borradas


def preparar_relevo(device_root: Path | str, p: Pendiente, esperar: list[int],
                    reabrir: str | None, decir: Progreso,
                    codigo: Path | None = None,
                    base: Path | None = None) -> tuple[list[str], Path]:
    """Deja listo el relevo de ese Python. Devuelve la orden y su carpeta.

    Nada de esto toca el dispositivo: todo va al temporal de este equipo. Si
    algo falla, la carpeta se borra y sale un InstallError."""
    barrer_relevos(base)
    codigo = Path(codigo) if codigo else Path(__file__).resolve().parent.parent
    carpeta = Path(tempfile.mkdtemp(prefix=RELEVO_PREFIJO, dir=base))
    try:
        (carpeta / RELEVO_DUENNO).write_text(str(os.getpid()), encoding="utf-8")
        decir(f"{p.titulo}: consiguiendo la versión {p.deberia}")
        archivo = runtime_bin.ensure_runtime(p.plataforma, decir)
        sha = runtime_bin.recorded_sha256(archivo) or runtime_bin.file_sha256(archivo)
        decir(f"{p.titulo}: preparando en {carpeta} el Python que lo cambiará")
        runtime_bin.extract(archivo, carpeta / "python", p.plataforma, sha)
        shutil.copytree(codigo, carpeta / "codigo",
                        ignore=shutil.ignore_patterns("__pycache__", ".git"))
    except (InstallError, OSError) as e:
        shutil.rmtree(carpeta, ignore_errors=True)
        if isinstance(e, InstallError):
            raise
        raise InstallError(f"No he podido preparar {carpeta}: {e}") from e

    orden = [str(carpeta / "python" / p.plataforma.interprete), "-u",
             str(carpeta / "codigo" / "prdrive-install.py"),
             "--update-components", str(Path(device_root))]
    for pid in esperar:
        orden += ["--esperar", str(pid)]
    if reabrir:
        orden += ["--reabrir", reabrir]
    return orden, carpeta


def lanzar_suelto(orden: list[str]) -> int:
    """Lanza `orden` desligada de este proceso, sin consola. Devuelve su pid.

    El cwd es el temporal y no el dispositivo: un proceso con el cwd dentro de
    `runtime/<clave>/` impediría justo el renombrado que se busca, y uno dentro
    del volumen impediría expulsarlo. Sin heredar nada de la salida: la ventana
    de salida lee la tubería de este proceso hasta que se cierra, y un hijo que
    la heredara la tendría esperando al relevo entero. Función de módulo para
    que los tests la sustituyan: ningún test lanza procesos sueltos de verdad."""
    extra: dict = {}
    if IS_WIN:
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        extra["creationflags"] = 0x00000008 | 0x00000200
    else:
        extra["start_new_session"] = True
    proc = subprocess.Popen(orden, cwd=tempfile.gettempdir(),
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, close_fds=True, **extra)
    return proc.pid


def lanzar_relevo(orden: list[str], carpeta: Path) -> int:
    """Lanza el relevo y apunta su pid como dueño de la carpeta."""
    pid = lanzar_suelto(orden)
    try:
        (carpeta / RELEVO_DUENNO).write_text(str(pid), encoding="utf-8")
    except OSError:
        pass        # a lo sumo, otro relevo la barrería antes de tiempo
    return pid


def esperar_a(pids: list[int], limite: float = ESPERA_MAXIMA) -> bool:
    """Espera a que salgan todos esos procesos. False si pasa el límite.

    Función de módulo por lo mismo que `descarga.esperar()`: los tests no
    esperan de verdad."""
    fin = time.monotonic() + limite
    while any(pid_alive(pid) for pid in pids):
        if time.monotonic() > fin:
            return False
        time.sleep(0.5)
    return True
