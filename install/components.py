#!/usr/bin/env python3
"""Poner al día el rclone, el Python, el VeraCrypt y el KeePassXC de un dispositivo.

Es el otro extremo de `common/components.py`: aquel LEE los sellos y dice qué
está anticuado (desde el propio dispositivo, al instante y sin red); esto lo
ARREGLA, y para eso hay que bajar, comprobar y sustituir, que es lo que el
instalador ya sabe hacer (`rclone_bin`, `runtime_bin`, `deploy`). Por eso vive
aquí y no en `common/`: `install/` no viaja al dispositivo a propósito, así que
esto se ejecuta desde el zip del código que `common/update.py` acaba de
descargar y verificar, como el aplicador de la actualización del programa. La
versión que fija los componentes es la que los instala, y no hay una segunda
copia de la maquinaria de descarga esperando a quedarse atrás.

El intercambio es el de `deploy.install_runtime()`, también para rclone: se
escribe al lado, se aparta el de antes y se coloca el nuevo de un renombrado,
que es atómico en los dos sistemas. NO se copia encima del binario que hay:
`shutil.copy2` trunca y luego escribe, y un corte a mitad dejaría el
dispositivo con un rclone roto, que es el único que tiene.

Lo que está en uso no se toca: un rclone sincronizando ahora mismo y el Python
desde el que está abierto este mismo programa se POSPONEN con su motivo; lo
demás se hace igual. Posponer es una decisión y no una limitación: en Windows
el renombrado colaría (un `.exe` en marcha se puede apartar; lo que no se puede
es borrar), pero cambiarle el binario a una sincronización a media pasada no
debe ocurrir sin que nadie lo haya pedido. El Python de la ventana es la
excepción que sí se termina: con `--relevo` lo cambia, con la ventana ya
cerrada, un proceso que corre desde el temporal del equipo (ver «El relevo»
abajo).

El VeraCrypt de viaje va por el mismo camino, con la carpeta entera en vez de
un binario: `traveler.poner_portatil()` la sustituye con el mismo intercambio
tras mirar el sitio libre de la raíz física. Si está en uso
(`veracrypt_en_uso()`) se pospone. Uno SIN sello (la copia de una instalación
que dejaban versiones anteriores) no se toca nunca desde aquí: su vestíbulo
solo sabe abrir esa disposición y el vestíbulo no es cosa de una actualización
de componentes. Se pospone diciendo que eso es de «Añadir plataformas…», que
cambia las dos cosas a la vez.

El relevo: en una instalación completa la ventana arranca desde
`runtime/<clave>/` de este equipo y este proceso es hijo suyo con el mismo
intérprete. Esa carpeta no se cambia con un intérprete corriendo desde ella,
así que sin relevo el runtime de esta plataforma no se pondría al día NUNCA
desde la ventana. No es que Windows lo impida: el renombrado de
`runtime/windows-x64/` salió bien con un `pythonw.exe` vivo dentro; lo que no
se pudo fue BORRAR la carpeta apartada, que se quedó con los 21 ficheros que
ese proceso tenía cargados mientras el resto (su biblioteca estándar) se
borraba debajo de él. Por eso el relevo espera además a que NADA corra desde
`runtime/` (`procesos_desde()`), y el aplicador lo mira antes de cerrar la
ventana. El relevo no necesita nada instalado: se extrae en el temporal de ESTE
equipo el runtime que se va a poner (el mismo archivo ya comprobado, que se
queda en la caché), se copia al lado este código (el zip descargado se borra en
cuanto la ventana recupera el control) y se lanza desde ahí, suelto,
`--update-components` con `--esperar` los pids de la ventana y de este proceso.
Cuando los dos han salido ningún proceso usa ya el runtime del dispositivo: se
sustituye con el intercambio de siempre y se reabre la ventana con él. Si algo
sale mal, lo dice en una ventana con su registro.

KeePassXC, el del llavero, también va por aquí, y es el único componente que se
pone aunque falte: con el llavero activo, uno que no está sale como pendiente
(`common.components.keepassxc_pendiente()`). Así es como «Ajustes → Llavero…»
lo trae, con el «Actualizar…» de siempre. Si corre algo desde su carpeta (él o
el proxy del navegador) se pospone.

Lo que aquí no pasa nunca: instalar una plataforma que el dispositivo no lleva
(eso es «Añadir plataformas…», una decisión con espacio en disco de por medio)
ni tocar el código, los lanzadores, el vestíbulo, la configuración o las
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

# Se importan los nombres sueltos y no el módulo: este fichero se llama igual
# que aquel y un `components.pendientes(...)` aquí sería una adivinanza sobre
# cuál de los dos se lee.
from common import pins
from common.components import KEEPASSXC, PYTHON, RCLONE, VERACRYPT, Pendiente, corre_desde
from common.components import pendientes as sellos_pendientes
from common.store import pid_alive, procesos_desde  # noqa: F401  (los tests lo sustituyen aquí)

from . import IS_WIN, InstallError
from . import deploy, keepassxc_bin, platforms, rclone_bin, runtime_bin, traveler, veracrypt_bin

Progreso = Callable[[str], None]
"""Función que recibe cada mensaje de avance."""

RELEVO_PREFIJO = "prdrive-relevo-"
"""Prefijo de la carpeta de relevo en el temporal de ESTE equipo.

Lleva un Python y una copia de este código, desde la que se termina el trabajo
con la ventana cerrada.
"""
RELEVO_DUENNO = "owner.pid"
"""Fichero de la carpeta de relevo con el pid de su dueño."""
RELEVO_DISPOSITIVO = "dispositivo"
"""Fichero de la carpeta de relevo con el dispositivo al que sirve."""
RELEVO_LOG = "relevo.log"
"""Fichero de la carpeta de relevo con su registro."""
ESPERA_MAXIMA = 30 * 60
"""Segundos que espera el relevo a que se cierre la ventana: media hora.

La ventana se cierra sola en cuanto se cierra la de salida, pero eso lo decide
quien mira; si sigue abierta, el relevo se rinde sin tocar nada.
"""


@dataclass
class Resultado:
    """Qué se ha hecho, qué se ha dejado para luego y qué ha salido mal.

    Pospuesto y fallido se cuentan aparte: lo primero es normal (había una
    sincronización en marcha) y lo segundo no (una suma que no cuadra). Quien
    llama decide con `fallidos` si fue un error; el recuadro ámbar se apaga
    solo porque los sellos ya dicen la verdad.

    Args:
        hechos: Lo puesto al día.
        pospuestos: Lo dejado para luego, con su motivo.
        fallidos: Lo que ha salido mal.
    """
    hechos: list[str] = field(default_factory=list)
    pospuestos: list[str] = field(default_factory=list)
    fallidos: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Indica si no ha fallado nada."""
        return not self.fallidos


def rclone_en_uso(ruta: Path) -> bool:
    """Indica si ese rclone se está ejecutando o no se puede escribir donde está.

    Es función de módulo a propósito, como `conflict_editor.mover()` o
    `runsync.notificar_fallo()`: los tests la sustituyen entera y así ninguno
    depende de tener un rclone corriendo. Se pregunta abriendo el fichero para
    escritura, que contesta en los dos sistemas sin enumerar procesos: en
    Windows un `.exe` cuya imagen está mapeada da `ERROR_SHARING_VIOLATION` y
    en Linux `open(O_RDWR)` sobre un binario en ejecución da `ETXTBSY`. Un
    volumen de solo lectura también falla y aquí significa lo mismo: ahora no.
    Que no exista no es «en uso»: no hay nada que sustituir y el intercambio se
    encargará de crearlo.
    """
    try:
        if not ruta.is_file():
            return False
        with open(ruta, "r+b"):
            return False
    except OSError:
        return True


def runtime_en_uso(carpeta: Path) -> bool:
    """Indica si ESTE proceso corre desde ese runtime.

    Es el caso normal y no una rareza: en un dispositivo con Python propio, la
    ventana que ofrece la actualización arrancó desde `runtime/<clave>/` y este
    proceso es hijo suyo con el mismo intérprete (`update.components_command()`
    pasa `sys.executable` a propósito). En Windows no se puede renombrar la
    carpeta de un `pythonw.exe` vivo, así que sin esto se bajarían 30 MB para
    fallar al final. Ese caso lo termina el relevo (`preparar_relevo()`).
    """
    return corre_desde(carpeta)


def veracrypt_en_uso(carpeta: Path) -> bool:
    """Indica si está en uso el VeraCrypt de esa carpeta.

    Es el truco de `rclone_en_uso()`, fichero a fichero: un `VeraCrypt-x64.exe`
    en marcha no se deja abrir para escribir. Es el caso normal más que una
    rareza: si el contenedor se abrió con el VeraCrypt que viaja, la copia
    elevada puede seguir viva y apartar la carpeta con ella dentro fallaría.
    Que no exista no es «en uso»: no hay nada que apartar.
    """
    try:
        ficheros = [p for p in Path(carpeta).iterdir() if p.is_file()]
    except OSError:
        return False
    return any(rclone_en_uso(p) for p in ficheros)


def _limpiar_restos(carpeta: Path) -> None:
    """Barre lo que dejó un intercambio anterior, sin ruido y a mejor esfuerzo.

    Un `.rclone.exe.viejo-1234` solo aparece cuando no se pudo borrar el de
    antes (Windows no borra un `.exe` en marcha) y entonces lo que procede es
    volver a intentarlo la próxima vez, no dar un error por algo que ya está
    resuelto. Uno atascado no para el barrido de los demás: el que falla es
    justo el caso esperado y, como los `.viejo-*` van primero, abortar ahí
    dejaría los `.nuevo-*` sin barrer para siempre, acumulándose en un volumen
    extraíble.
    """
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

    Son los tres pasos de `deploy.install_runtime()`: se copia al lado, se
    aparta el de antes con un renombrado y se coloca el nuevo con otro. El
    renombrado es atómico en los dos sistemas, así que en ningún instante hay
    medio rclone en `bin/` (y medio rclone es un dispositivo que no sincroniza
    en ningún equipo). Si el último paso falla, el de antes vuelve a su sitio;
    y si ni eso se puede, el error dice que esa plataforma se ha quedado sin
    rclone y cómo volver a ponerlo. Borrar el apartado es lo único que puede
    fallar sin consecuencias y se deja para la próxima pasada
    (`_limpiar_restos`).

    Raises:
        InstallError: Si no se puede copiar, apartar o colocar el binario.
    """
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
        # Esta es la única rama que puede dejar `bin/` SIN rclone y por eso no
        # puede escaparse cruda: `aplicar()` solo recoge `InstallError`, así
        # que un `OSError` de aquí abortaría la pasada y se perdería el parte
        # de lo hecho justo cuando hay algo urgente que contar. Y un
        # dispositivo sin binario ni siquiera vuelve a salir como pendiente
        # (`rclone_pendiente()` no compara lo que no está): si no lo dice este
        # mensaje, no lo dice nadie.
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


def pendientes(device_root: Path | str) -> list[Pendiente]:
    """Devuelve lo que ese dispositivo tiene por poner al día, sin red.

    Es lo mismo que pregunta el propio dispositivo, pero partiendo de la raíz
    del volumen.
    """
    return sellos_pendientes(deploy.app_dir(device_root))


def _poner_rclone(raiz: Path, p: Pendiente, decir: Progreso) -> str | None:
    """Sustituye un rclone.

    Returns:
        El motivo si se pospone, o `None` si se hizo.
    """
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
    """Sustituye un runtime.

    Returns:
        El motivo si se pospone, o `None` si se hizo.
    """
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
"""Motivo de posponer el VeraCrypt sin sello: es de «Añadir plataformas…»."""


def _poner_veracrypt(raiz: Path, p: Pendiente, decir: Progreso) -> str | None:
    """Sustituye el VeraCrypt de viaje.

    Args:
        raiz: La del dispositivo (el contenedor montado); la carpeta que se
            sustituye es la de la raíz FÍSICA, que viene en `p.ruta`.

    Returns:
        El motivo si se pospone, o `None` si se hizo.
    """
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


KEEPASSXC_EN_USO = "Cierra KeePassXC y el navegador para poner al día el llavero"
"""Lo que se dice al posponer KeePassXC porque algo corre desde su carpeta."""


def _poner_keepassxc(raiz: Path, p: Pendiente, decir: Progreso) -> str | None:
    """Pone, o sustituye, el KeePassXC del llavero.

    Algo que corra desde su carpeta lo pospone: KeePassXC abierto o el proxy
    que lanza el navegador (`keepassxc-proxy.exe`), que vive mientras el
    navegador esté conectado (K6, H-16). Apartar la carpeta con ellos dentro
    fallaría en Windows, o les quitaría el programa de debajo.

    Returns:
        El motivo si se pospone, o `None` si se hizo.
    """
    carpeta = p.ruta
    if carpeta is None:
        return "no sé dónde va su carpeta: pasa el instalador por encima."
    retienen = procesos_desde(carpeta)
    if retienen:
        return (f"está en uso: {KEEPASSXC_EN_USO}.\n"
                + describir_retenedores(retienen))
    decir(f"{p.titulo}: consiguiendo la versión {p.deberia}")
    keepassxc_bin.instalar(deploy.app_dir(raiz), carpeta.name, decir)
    return None


PONER = {RCLONE: _poner_rclone, PYTHON: _poner_python, VERACRYPT: _poner_veracrypt,
         KEEPASSXC: _poner_keepassxc}
"""Qué función pone al día cada tipo de componente."""


def aplicar(device_root: Path | str, progreso: Progreso | None = None,
            pends: list[Pendiente] | None = None) -> Resultado:
    """Pone al día los componentes anticuados de ese dispositivo.

    Lo que se pueda: cada componente va por su cuenta y uno que no se pueda
    tocar ahora no impide los demás. Nada queda a medias: lo que no se ha
    sustituido sigue exactamente como estaba y su sello lo sigue diciendo, así
    que el aviso de la ventana se apaga solo en cuanto deja de haber motivo.

    Args:
        pends: Lo pendiente; por defecto, lo que diga `pendientes()`.
    """
    def decir(msg: str) -> None:
        """Pasa un mensaje a `progreso`, si lo hay."""
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
            # El `OSError` es tan normal como el `InstallError`:
            # `urllib.error.URLError` ES un `OSError`, así que quedarse sin
            # red, un proxy o un tiempo de espera salen por aquí en cuanto se
            # lee el SHA256SUMS, y también un volumen que se retira a media
            # pasada. Nada de eso es asunto de las demás plataformas: si se
            # escapara se perdería el parte entero de una pasada que quizá ya
            # había puesto al día media docena de componentes.
            res.fallidos.append(f"{p.titulo}: {e}")
            continue
        if motivo is not None:
            res.pospuestos.append(f"{p.titulo}: {motivo}")
        else:
            res.hechos.append(f"{p.titulo}: {p.lleva} → {p.deberia}")
    return res


def runtime_propio(device_root: Path | str,
                   pends: list[Pendiente]) -> Pendiente | None:
    """Devuelve el Python pendiente desde el que corre este proceso, o `None`.

    Pregunta por `runtime_en_uso()`, la misma pregunta que hace
    `_poner_python()`, para que los tests la contesten en un solo sitio.
    """
    for p in pends:
        if (p.que == PYTHON and p.plataforma is not None
                and runtime_en_uso(platforms.runtime_dir(device_root, p.plataforma))):
            return p
    return None


def barrer_relevos(base: Path | None = None) -> int:
    """Borra las carpetas de relevo de procesos que ya no viven, y devuelve cuántas.

    El relevo no puede borrar la suya (corre desde ella), así que la barre el
    siguiente, como `remote.sweep_stale()` con las claves. Cada una dice de qué
    pid es; la de uno vivo no se toca.
    """
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


def _clave_dispositivo(device_root: Path | str) -> str:
    """Devuelve la clave de un dispositivo en las carpetas de relevo."""
    try:
        return str(deploy.app_dir(device_root).resolve()).lower()
    except OSError:
        return str(deploy.app_dir(device_root)).lower()


def relevo_en_marcha(device_root: Path | str, base: Path | None = None) -> Path | None:
    """Devuelve la carpeta de un relevo vivo para ESE dispositivo, o `None`.

    Hay uno por dispositivo: al pulsar «Actualizar…» dos veces (la ventana
    tardaba en volver y se abrió otra), dos relevos extraían a la vez 48 MB
    cada uno en el mismo USB, cambiaban el runtime uno detrás del otro y
    reabrían dos ventanas.
    """
    base = base or Path(tempfile.gettempdir())
    clave = _clave_dispositivo(device_root)
    for carpeta in base.glob(RELEVO_PREFIJO + "*"):
        try:
            duenno = int((carpeta / RELEVO_DUENNO).read_text(encoding="utf-8").strip())
            suyo = (carpeta / RELEVO_DISPOSITIVO).read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            continue
        if suyo == clave and duenno != os.getpid() and pid_alive(duenno):
            return carpeta
    return None


def preparar_relevo(device_root: Path | str, p: Pendiente, esperar: list[int],
                    reabrir: str | None, decir: Progreso,
                    codigo: Path | None = None,
                    base: Path | None = None) -> tuple[list[str], Path]:
    """Deja listo el relevo de ese Python y devuelve la orden y su carpeta.

    Nada de esto toca el dispositivo: todo va al temporal de este equipo.

    Args:
        esperar: Pids que el relevo espera antes de actuar (la ventana y este
            proceso).
        reabrir: Qué reabrir al terminar, o `None`.
        codigo: Carpeta del código a copiar; por defecto, la de este paquete.
        base: Dónde crear la carpeta de relevo; por defecto, el temporal del
            sistema.

    Raises:
        InstallError: Si ya hay un relevo en marcha o algo falla; la carpeta se
            borra.
    """
    barrer_relevos(base)
    otro = relevo_en_marcha(device_root, base)
    if otro is not None:
        raise InstallError(
            f"Ya hay un cambio de este Python en marcha ({otro}). Espera a que "
            f"prdrive se vuelva a abrir solo; no hace falta pulsar otra vez.")
    codigo = Path(codigo) if codigo else Path(__file__).resolve().parent.parent
    carpeta = Path(tempfile.mkdtemp(prefix=RELEVO_PREFIJO, dir=base))
    try:
        (carpeta / RELEVO_DUENNO).write_text(str(os.getpid()), encoding="utf-8")
        (carpeta / RELEVO_DISPOSITIVO).write_text(_clave_dispositivo(device_root),
                                                  encoding="utf-8")
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
    """Lanza `orden` desligada de este proceso, sin consola, y devuelve su pid.

    El cwd es el temporal y no el dispositivo: un proceso con el cwd dentro de
    `runtime/<clave>/` impediría justo el renombrado que se busca y uno dentro
    del volumen impediría expulsarlo. No hereda nada de la salida: la ventana
    de salida lee la tubería de este proceso hasta que se cierra y un hijo que
    la heredara la tendría esperando al relevo entero. Es función de módulo
    para que los tests la sustituyan: ninguno lanza procesos sueltos de verdad.
    """
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


def quien_retiene(device_root: Path | str, p: Pendiente,
                  aparte: list[int]) -> dict[int, str]:
    """Devuelve los procesos que corren desde el runtime de `p`, menos los de `aparte`.

    Args:
        aparte: Pids que ya se sabe que van a salir: la ventana y el aplicador.
    """
    carpeta = platforms.runtime_dir(device_root, p.plataforma)
    return {pid: exe for pid, exe in procesos_desde(carpeta).items()
            if pid not in aparte}


def _tamanno(carpeta: Path) -> int:
    """Devuelve lo que ocupa una carpeta, en bytes."""
    total = 0
    for raiz, _, ficheros in os.walk(carpeta):
        for nombre in ficheros:
            try:
                total += os.path.getsize(os.path.join(raiz, nombre))
            except OSError:
                pass
    return total


class AvanceRelevo:
    """Lo que enseña la ventanita del relevo mientras trabaja.

    Hace falta porque el relevo tarda: extraer 48 MB en un USB son minutos y,
    sin nada en pantalla, se volvió a abrir prdrive (que corre justo desde la
    carpeta que hay que cambiar) y se pulsó «Actualizar…» otra vez. La cifra no
    es una estimación: es lo que ya hay en la carpeta `.<clave>.nuevo-<pid>`
    del dispositivo frente a lo que ocupa el mismo runtime ya extraído en el
    temporal, que es idéntico. Lo escriben el hilo que trabaja y uno que mide
    cada segundo; el de Tk solo llama a `progreso()`, que no toca el disco
    (`ui.tk.working()`).

    Args:
        device_root: Raíz del dispositivo.
        referencia: El runtime ya extraído en el temporal, con el que se
            compara lo copiado.

    Attributes:
        texto: Lo que se enseña.
        fraccion: Avance, de 0 a 1.
    """

    ESPERANDO = "Esperando a que se cierre la ventana de prdrive…"

    def __init__(self, device_root: Path | str, referencia: Path | None = None):
        """Prepara el seguimiento, todavía sin medir."""
        self._base = platforms.runtime_dir(device_root, pins.PLATAFORMAS[0]).parent
        self._referencia = referencia
        self._total = 0
        self.texto = self.ESPERANDO
        self.fraccion = 0.0
        self._midiendo = False

    def esperando(self, retienen: dict[int, str]) -> None:
        """Actualiza el texto con quién sigue corriendo desde el runtime.

        Es para `esperar_a(avisar=…)`.
        """
        if not retienen:
            self.texto = "Preparando el cambio…"
            return
        self.texto = ("Esperando a que se cierre lo que usa ese Python:\n"
                      + describir_retenedores(retienen)
                      + "\nPuede ser un aviso de prdrive que se ha quedado abierto.")

    def medir(self) -> None:
        """Empieza a medir lo copiado, en un hilo suyo, hasta `fin()`."""
        import threading
        if self._referencia is not None:
            self._total = _tamanno(self._referencia)
        self._midiendo = True
        self.texto = "Preparando el cambio…"
        threading.Thread(target=self._bucle, daemon=True).start()

    def _bucle(self) -> None:
        """Mide cada segundo lo copiado y actualiza avance y texto."""
        visto = False
        while self._midiendo:
            try:
                nuevos = list(self._base.glob(f".*.nuevo-{os.getpid()}"))
                copiado = sum(_tamanno(d) for d in nuevos)
            except OSError:
                nuevos, copiado = [], 0
            if nuevos and self._total:
                visto = True
                self.fraccion = min(0.99, copiado / self._total)
                self.texto = f"Copiando al dispositivo: {int(self.fraccion * 100)} %"
            elif visto:
                self.fraccion, self.texto = 0.99, "Colocándolo en su sitio…"
            time.sleep(1)

    def fin(self) -> None:
        """Marca el final: el relevo ya ha terminado y vuelve a abrir prdrive."""
        self._midiendo = False
        self.fraccion, self.texto = 1.0, "Volviendo a abrir prdrive…"

    def progreso(self) -> tuple[float, str]:
        """Devuelve `(fracción, texto)` para la ventana de espera.

        No toca el disco.
        """
        return self.fraccion, self.texto


def describir_retenedores(retienen: dict[int, str]) -> str:
    """Devuelve una línea por proceso, para el mensaje de quien tiene que cerrarlo."""
    return "\n".join(f"    pid {pid}: {exe}" for pid, exe in sorted(retienen.items()))


def esperar_a(pids: list[int], limite: float = ESPERA_MAXIMA,
              libre: Path | None = None,
              avisar: Callable[[dict[int, str]], None] | None = None) -> bool:
    """Espera a que salgan esos procesos y, con `libre`.

    A que nadie corra de esa carpeta.

    Es función de módulo por lo mismo que `descarga.esperar()`: los tests no
    esperan de verdad.

    Args:
        pids: Procesos a esperar.
        limite: Segundos máximos.
        libre: Carpeta desde la que no debe correr nada.
        avisar: Recibe, cada vez que cambia, quién sigue corriendo desde
            `libre` (`{}` cuando ya nadie): es lo que la ventanita del relevo
            enseña para que se pueda cerrar.

    Returns:
        False si pasa el límite.
    """
    fin = time.monotonic() + limite
    antes: dict[int, str] | None = None
    while True:
        quedan = {pid: "" for pid in pids if pid_alive(pid)}
        if libre is not None and not quedan:
            quedan = procesos_desde(libre)
            if avisar is not None and quedan != antes:
                avisar(quedan)
            antes = quedan
        if not quedan:
            return True
        if time.monotonic() > fin:
            return False
        time.sleep(0.5)
