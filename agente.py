#!/usr/bin/env python3
"""El agente residente de prdrive: un proceso por usuario que atiende las unidades.

Es el sucesor de `penwatch.py` en los equipos donde se instala: vive en el
equipo, FUERA de toda raíz (`common/equipo.py` dice dónde), arranca al iniciar
sesión con su propio Python y hace de servicio de cada unidad prdrive que se
enchufa y que tiene en su lista. Sin Tk: la ventana de una unidad y la pregunta
por una unidad nueva son procesos hijos.

Se usa como `python agente.py ORDEN`:
- `run`: el bucle (lo lanza el registro al iniciar sesión).
- `status`: qué atiende y cómo.
- `atender ID`: atiende la unidad conectada a la que se dijo «Ahora no».
- `modo ID MODO`: `ui`, `daemon`, `sync` o `nada`.
- `pasada ID [PAREJA…]`: «Sincronizar ahora», sin moderación.
- `pausa` y `sigue`: dejar de lanzar pasadas, y volver.
- `parar`: que termine (lo usa el instalador).
- `abrir [ID]`: la ventana de la raíz de este equipo (o de esa).
- `desbloquear [ID]` y `bloquear [ID]`: abrir y cerrar el contenedor de la raíz
  cifrada.
- `ajuste CLAVE VALOR`: `pedir_al_iniciar sí|no` o `espera_unidad_nueva SEG`.
- `actualizar`: baja la versión nueva y la pone (lo que hace la bandeja).

Las órdenes que no son `run` no hacen nada por sí mismas: dejan la petición en
el buzón del agente (`equipo.pedir()`), que es quien escribe su configuración.

Cómo trabaja, vuelta a vuelta (`Agente.vuelta()`):
- **Detecta** las unidades con el mismo recorrido de siempre,
  `penwatch.candidate_roots()`, pero no cada 5 s: en Linux se despierta cuando
  cambia `/proc/self/mountinfo` (`POLLPRI`) y de ahí una racha de sondeos,
  porque un volumen cifrado se lee bastante después de montarse. En Windows,
  con el `WM_DEVICECHANGE` que recibe la ventana de la bandeja; sin bandeja,
  sondea como penwatch. Una unidad cuenta cuando se ha visto dos veces
  seguidas.
- **Pregunta** por las unidades que no conoce («Una unidad nueva» del diseño):
  un aviso y una ventanita con cuenta atrás; sin respuesta es «Ahora no», solo
  para esta conexión. Antes del sí no se ejecuta NADA de la unidad: solo se
  leen su id y su nombre.
- **Hace de su servicio** con los ficheros que ya existen en su `state/`, así
  que funciona con unidades de código viejo: escribe `daemon.lock.json`,
  obedece `daemon.stop` (acaba la pareja en curso y suelta), se queda en pausa
  mientras haya una ventana de runsync abierta en este equipo y se aparta si
  otro servicio vivo tiene el lock. Un servicio por raíz: el que tenga el lock.
- **Planifica** con `common/planificador.py`, que es puro: una sola pasada a la
  vez en todo el equipo, espera creciente tras un fallo, batería, red de uso
  medido, remotos sin conexión, «Sincronizar ahora». Un remoto sin conexión se
  sondea cuando el sistema dice que vuelve a haber red (`common/red.py`), una
  vez por ráfaga de avisos, y si no, cada 5 min (cada 30 si hay avisos).
- **Mira los cambios locales** de las parejas con `watch = true`: una foto
  barata de su carpeta cada 10 s (`common/huella.py`, en un hilo: un pendrive
  tarda segundos), y si cambia y se calma, la pasada de esa pareja se adelanta
  a su intervalo. La modera todo lo demás (pausa, batería, red de uso medido,
  la pausa de la ventana de la raíz, su ventana abierta) y, al acabar, se
  vuelve a tomar la foto para que lo que escribió rclone no la dispare otra
  vez. No ve los cambios del remoto: esos esperan al intervalo.
- **Ejecuta** cada pasada como el `sync.py` de esa raíz, hijo, con el Python
  del agente y el directorio de trabajo fuera de la raíz: cada raíz ejecuta su
  propio código, un rclone colgado no tumba al agente y entre pasadas no queda
  nada abierto dentro de ninguna unidad, así que se puede expulsar.

La raíz de ESTE equipo (una carpeta del ordenador con `.prdrive/` dentro, que
pone el asistente «En este equipo») es una raíz más de la lista, con su `ruta`:
se busca ahí en vez de recorrer volúmenes y todo lo demás es igual. Si falta
(se ha movido o renombrado la carpeta) se avisa una vez y no se lanza nada: una
línea base sin su carpeta local es justo lo que `_bisync_preflight()` frena.

La raíz del equipo puede vivir en un contenedor VeraCrypt (fase 3). Entonces el
agente es quien lo abre y quien lo cierra, con el VeraCrypt INSTALADO y sin que
la contraseña pase nunca por él:
- **Desbloquear** lanza VeraCrypt con `/letter` fija (Windows) o el punto de
  montaje fijo (Linux) y sin `/password`: la pide su ventana. Abierta no es que
  VeraCrypt salga con 0, sino VER el id en la letra con el `.hc` retenido. Una
  letra con el id al lado de un `.hc` libre es el fantasma de las unidades
  (H-10): no se atiende y se dice «Bloquear y volver a desbloquear». Con la
  letra de otro, o un punto de montaje con cosas, no se lanza nada: se dice.
- **Al iniciar sesión**, con `pedir_al_iniciar`, se pide UNA vez; si se
  cancela, hasta que se pida «Desbloquear».
- **Bloquear** deja de encolar la raíz, espera a la pareja en curso y a que se
  cierre su ventana, suelta el lock y lanza el desmontaje SIN `/silent`: si un
  programa tiene algo abierto dentro, VeraCrypt pregunta si forzar, y eso lo
  decide la persona. Bloqueada es el `.hc` libre, no la letra ida.
- **Cerrada, simplemente no está**: no es un fallo, ni un aviso, ni una espera
  más larga. Una raíz cerrada no tiene carpeta ni línea base.

Avisa con los avisos del sistema (`common/avisos.py`), no con Tk, y solo cuando
una pareja EMPIEZA a fallar. Sin avisos, queda en su diario.

Tiene un icono en la bandeja: `ui/bandeja.py` decide qué enseña a partir de
`resumen()` y lo dibuja en su propio hilo `ui/bandeja_windows.py` en Windows
(fase 4) o `ui/bandeja_linux.py` en Linux (fase 6, StatusNotifierItem). Lo que
se elige en su menú llega como las peticiones del buzón (`Agente.pedir()`), por
el mismo camino. Donde el escritorio no tiene bandeja (GNOME sin la extensión
AppIndicator), hace sus veces el acceso «prdrive» del menú de aplicaciones:
`agente.py abrir` arranca el agente si no está, abre la ventana de la raíz o,
sin raíz, dice con un aviso cómo va.

La ventana de una raíz le habla por dos buzones (fase 5): lo del equipo por
`agente.pide` y lo de esa raíz («Pausar» (`pausar_raiz`), «Reanudar»
(`reanudar`), «Bloquear») por el `state/servicio.pide` de la propia raíz, que
solo se lee en las raíces de la lista. Una raíz pausada desde su ventana se
queda así en `agente.json` (`Unidad.pausada`) hasta «Reanudar», aunque el
agente se reinicie; la pausa de todo (`pausa`, la bandeja) no se guarda.

Cuando hay una versión nueva lo dice una vez; «Actualizar» (`agente.py
actualizar`) baja el código de la release y ejecuta SU instalador, que pone el
agente nuevo al lado de este, lo para y arranca el nuevo.

Depende de `penwatch.py` para detectar, leer los registros de runsync y abrir
VeraCrypt: el agente importa de penwatch, nunca al revés, y penwatch sigue sin
importar nada del proyecto.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, NamedTuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import penwatch  # noqa: E402
from common import (APP_NAME, avisos, catalog, components, equipo, model,  # noqa: E402
                    moderacion, store, update, vestibulo)
from common import huella as huellas  # noqa: E402  (`huella()` es la del código de una raíz)
from common import planificador as pl  # noqa: E402
from common.store import pid_alive  # noqa: E402
from ui import bandeja, prefs, volumen  # noqa: E402

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

IS_WIN = os.name == "nt"
HOST = equipo.HOST
APP_SUBDIR = penwatch.APP_SUBDIR

TICK = 2.0
"""Segundos entre las miradas a lo barato: stop, ventana, hijos."""
RECORRIDO_WINDOWS = penwatch.POLL_SECONDS
"""Segundos entre recorridos en Windows sin bandeja, como penwatch.

Sin bandeja no llega `WM_DEVICECHANGE`.
"""
RECORRIDO_RESPALDO = 30.0
"""Segundos entre recorridos aunque mountinfo o `WM_DEVICECHANGE` no digan nada."""
RAFAGA = 60.0
"""Segundos tras un cambio de montajes en que se recorre en cada vuelta."""
ESTABLE = penwatch.STABLE_CHECKS
"""Sondeos seguidos que hacen falta para que una unidad cuente."""
GRACIA = 15.0
"""Segundos tras ver la ventana o un stop, antes de volver."""
MIRAR_ENTORNO = 60.0
"""Segundos entre las lecturas de batería y red."""
DESPERTAR_DOBLE = 10.0
"""Segundos en que un segundo aviso de despertar se toma por el mismo.

Windows avisa dos veces de una vuelta de la suspensión.
"""
PARAR_ESPERA = 10.0
"""Segundos que `parar` espera a que el agente se vaya."""
ESPERA_VENTANA = 60.0
"""Segundos que «Bloquear» espera a que se cierre la ventana de la raíz."""
ESPERA_DESMONTAJE = 300.0
"""Segundos que se espera a que VeraCrypt cierre (puede estar preguntando)."""
GRACIA_DESMONTAJE = 5.0
"""Segundos tras salir VeraCrypt para que el `.hc` quede libre."""
ESPERA_ABRIR = 180.0
"""Segundos que `abrir` espera a que se desbloquee una raíz cerrada."""
GRACIA_ABRIR = 20.0
"""Segundos tras salir VeraCrypt para ver la raíz abierta.

Si no se ve, se da por cancelada.
"""
COLA_SALIDA = 64 * 1024
"""Bytes que se leen de la salida de una pasada."""
MIRAR_VERSION = 6 * 3600.0
"""Segundos entre comprobaciones de versión nueva (`update.check` guarda 24 h)."""
MIRAR_EMBLEMA = 60.0
"""Segundos entre lecturas del `autorun.inf` de una raíz para el icono de la bandeja.

Se lee al conectarla y luego como mucho una vez por minuto: así se ve un icono
cambiado desde su ventana sin leer la unidad en cada vuelta.
"""

IGNORAR_CAMBIOS = huellas.IGNORAR + (APP_SUBDIR,)
"""Carpetas de la raíz de una pareja vigilada que no se miran.

Además de `.prversions/`, el propio `.prdrive/`: una pareja con `local = "."`
lo tendría dentro, y lo que escribe cada pasada en su `state/` la dispararía
otra vez.
"""

OK, FALLO, RED, SALTADA = pl.OK, pl.FALLO, pl.RED, pl.SALTADA

VERSION_MINIMA = "0.5.0"
"""Primera versión cuyo `sync.py` usa el rclone del agente (`model.RCLONE_DEL_AGENTE`).

Las anteriores ejecutarían el de la unidad, que la huella no cubre: el agente
no las atiende hasta que se actualicen.
"""
SIN_VERACRYPT = ("No hay VeraCrypt en este equipo: ni instalado ni el del agente. "
                 "Vuelve a pasar el asistente, que se lo pone, o instala VeraCrypt.")
"""Lo que se dice cuando hay que abrir una raíz y no hay VeraCrypt."""
SIN_RCLONE = ("no encuentro el rclone del agente; sin él no ejecuto nada de las "
              "unidades. Reinstala el agente o actualízalo.")
"""Lo que se dice cuando el agente no tiene rclone propio."""
TEXTO_RESULTADO = {OK: "bien", FALLO: "FALLÓ", RED: "FALLÓ por la red",
                   SALTADA: "saltada: pide --resync"}
"""Cómo se dice, en el diario, el resultado de una pasada."""


def lanzar(args: list[str], **kwargs) -> Any:
    """Lanza un proceso hijo.

    Punto de indirección: los tests lo sustituyen.
    """
    return subprocess.Popen(args, **kwargs)


def hay_pantalla() -> bool:
    """Indica si hay dónde abrir una ventana; en Windows, la sesión del usuario."""
    return IS_WIN or bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def avisar(titulo: str, texto: str, urgente: bool = False) -> bool:
    """Avisa con las notificaciones del sistema y lo deja en el diario.

    Returns:
        `False` si no hay avisos del sistema y solo quedó en el diario.
    """
    ok = avisos.enviar(titulo, texto, urgente)
    diario(f"aviso{'' if ok else ' (sin avisos del sistema: solo aquí)'}: "
           f"{titulo} — {texto}")
    return ok


def abrir_contenedor(raiz: Path) -> bool:
    """Le pide a VeraCrypt que abra el contenedor de `raiz`.

    Lo lanza desde la carpeta del agente (`penwatch.open_container`).
    """
    return penwatch.open_container(raiz, cwd=equipo.DIR)


def orden_explorar(ruta: Path) -> list[str] | None:
    """Devuelve la orden que abre el explorador de archivos en `ruta`, o `None`.

    En Windows, `explorer.exe` con la carpeta, y no `os.startfile()`: abrir una
    raíz de unidad «como documento» pasa por los verbos del Shell para esa
    unidad, y explorer.exe con una ruta solo la enseña. En Linux, `xdg-open`,
    que la abre con el gestor de archivos del escritorio; sin él, `None`.
    """
    if IS_WIN:
        sistema = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
        return [str(Path(sistema) / "explorer.exe"), str(ruta)]
    xdg = shutil.which("xdg-open")
    return [xdg, str(ruta)] if xdg else None


def explorar(ruta: Path) -> bool:
    """Abre el explorador de archivos en `ruta`, sin esperar.

    Se lanza desde la carpeta del agente, fuera de toda raíz. Punto de
    indirección: los tests lo sustituyen o miran lo que pasa a `lanzar()`.

    Returns:
        `False` si este equipo no tiene con qué (Linux sin `xdg-open`).

    Raises:
        OSError: Si no se ha podido lanzar.
    """
    orden = orden_explorar(ruta)
    if orden is None:
        return False
    lanzar(orden, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
           stderr=subprocess.DEVNULL, cwd=str(equipo.DIR), close_fds=True)
    return True


def diario(msg: str) -> None:
    """Añade una línea al diario del agente (`penwatch.log`)."""
    penwatch.log(msg)


def hilo(funcion) -> None:
    """Corre `funcion` en un hilo aparte, para lo que puede tardar (la red o un disco).

    Punto de indirección: los tests la corren en el sitio.
    """
    threading.Thread(target=funcion, daemon=True).start()


def huella_local(ruta: Path, tope: int, ignorar: tuple[str, ...]) -> pl.Huella | None:
    """Toma la foto de la carpeta local de una pareja vigilada (`watch = true`).

    Es `huella.de_carpeta()`: recorre la carpeta sin abrir ningún fichero y sin
    seguir enlaces. Punto de indirección: los tests devuelven la foto que
    quieren, sin tocar el disco.

    Args:
        ruta: La carpeta.
        tope: Cuántas entradas se cuentan como mucho.
        ignorar: Carpetas de su raíz que no se miran.

    Returns:
        La foto, o `None` si no se pudo tomar.
    """
    return huellas.de_carpeta(ruta, tope, ignorar)


def cache_version() -> Path:
    """Devuelve dónde se guarda lo último que dijo GitHub sobre versiones.

    Vive en la carpeta del agente: no es de ninguna raíz y el `state/` de su
    código se va con cada versión.
    """
    return equipo.DIR / "update.json"


def buscar_version() -> "update.Release | None":
    """Devuelve la release más nueva que este agente, o `None`.

    Respeta la caché de `update.check()` (24 h), así que casi nunca sale a la
    red.
    """
    update.check(cache=cache_version())
    return update.pending(SCRIPT_DIR, cache=cache_version())


def ejecutar(args: list[str], **kwargs) -> Any:
    """Corre un proceso hasta que acaba.

    Punto de indirección: los tests la sustituyen.
    """
    return subprocess.run(args, **kwargs)


def python(ventana: bool = False) -> str:
    """Devuelve el Python del agente, para sus hijos: sin consola en Windows."""
    exe = sys.executable
    if IS_WIN:
        w = Path(exe).with_name("pythonw.exe")
        if w.is_file():
            return str(w)
    return exe


def rclone_propio() -> Path | None:
    """Devuelve el rclone del agente, o `None` si no está.

    Lo pone el instalador en `rclone/<versión fijada>/` y lo apunta
    `instalacion.json`. Es el que se pasa a las pasadas y a las ventanas, y con
    el que se sondea un remoto: el de una unidad no se ejecuta nunca. Punto de
    indirección: los tests lo sustituyen.
    """
    ruta = equipo.leer_instalacion().get("rclone")
    if not isinstance(ruta, str) or not ruta:
        return None
    try:
        return Path(ruta) if Path(ruta).is_file() else None
    except OSError:
        return None


def veracrypt_propio() -> str | None:
    """Devuelve el VeraCrypt del agente para ESTE equipo, comprobado, o `None`.

    Lo pone el instalador en `veracrypt/<versión fijada>/` solo cuando atiende
    una raíz cifrada y no hay VeraCrypt instalado
    (`install/agente.quiere_veracrypt()`), y lo apunta en `instalacion.json`,
    que se lee aquí cada vez: añadirlo no obliga a parar el agente. Se vuelve a
    resumir contra su sello antes de devolverlo, porque lo que se lanza pide
    administrador (UAC) y tiene que ser lo que se comprobó al instalar. En
    Windows, el ejecutable y el driver de la arquitectura NATIVA, como en el
    vestíbulo: VeraCrypt elige su driver por ella y un driver no se emula.
    Punto de indirección: los tests lo sustituyen.
    """
    carpeta = equipo.leer_instalacion().get("veracrypt")
    if not isinstance(carpeta, str) or not carpeta:
        return None
    if IS_WIN:
        arq = penwatch.native_arch()
        if arq not in penwatch.TRAVELER_ARCHS:
            return None
        exe = penwatch.TRAVELER_PORTABLE.format(arq=arq)
        necesarios = (exe, f"veracrypt-{arq}.sys")
    else:
        exe = "veracrypt"
        necesarios = (exe,)
    if not components.veracrypt_integro(carpeta, necesarios):
        diario(f"el VeraCrypt del agente en {carpeta} no cuadra con su sello: no lo "
               f"lanzo. Reinstala el agente.")
        return None
    return str(Path(carpeta) / exe)


def veracrypt_de_la_raiz() -> str | None:
    """Devuelve con qué VeraCrypt se abre y se cierra la raíz cifrada, o `None`.

    El instalado primero: con su driver cargado no pide administrador, y con
    otra versión menor cargada el portable fallaría con `ERR_DRIVER_VERSION`.
    Si no, el del agente.
    """
    return penwatch.installed_veracrypt() or veracrypt_propio()


def procesos(nombre: str) -> set[int]:
    """Devuelve los pid vivos con ese nombre de ejecutable (Windows; en POSIX, vacío).

    Punto de indirección: los tests lo sustituyen.
    """
    return store.procesos_llamados(nombre)


def _opciones_hijo(cwd: Path, separado: bool = False) -> dict:
    """Devuelve los argumentos de `Popen` para un hijo del agente.

    Sus `.pyc` van a la carpeta del agente: los `__pycache__` de una raíz no
    entran en su huella (`huella()`), así que Python no debe leerlos de ahí, y
    de paso no se escribe en la unidad. Y siempre con su rclone: sin él, una
    ruta que no existe, para que el `sync.py` de la raíz falle diciéndolo en
    vez de usar el de la unidad.

    Args:
        cwd: Directorio de trabajo, fuera de la raíz.
        separado: En su propio grupo de procesos (Windows) o sesión (POSIX),
            para poder cortar la pasada entera.
    """
    rclone = rclone_propio() or equipo.dir_rclone() / "falta" / model.rclone_name()
    kwargs: dict = {"stdin": subprocess.DEVNULL, "cwd": str(cwd), "close_fds": True,
                    "env": {**os.environ,
                            "PYTHONPYCACHEPREFIX": str(equipo.DIR / "pycache"),
                            model.RCLONE_DEL_AGENTE: str(rclone)}}
    if IS_WIN:
        kwargs["creationflags"] = penwatch.CREATE_NO_WINDOW | (
            penwatch.CREATE_NEW_PROCESS_GROUP if separado else 0)
    elif separado:
        kwargs["start_new_session"] = True
    return kwargs


def app(raiz: Path) -> Path:
    """Devuelve la carpeta del programa dentro de una raíz."""
    return raiz / APP_SUBDIR


HUELLA_SIN_CARPETAS = frozenset({"state", "logs", "filters", "keys", "runtime", "bin"})
"""Carpetas que la huella deja fuera: lo que cambia con el uso y no se ejecuta."""
HUELLA_SIN_FICHEROS = frozenset({"sync_config.toml", Path(penwatch.CONTROL_FILE).name})
"""Ficheros que la huella deja fuera: la configuración y el fichero de control."""
HUELLA_SIN_EXTENSIONES = frozenset({".ico"})
"""Extensiones que la huella deja fuera."""


def huella(raiz: Path) -> str | None:
    """Devuelve el sha256 de lo que el agente ejecutaría de esa raíz.

    Es `None` si no se puede leer. El id del fichero de control lo lleva
    escrito la unidad: copiarlo junto a un `.prdrive/` modificado bastaría para
    que el agente ejecutara ese código como si fuera el de la unidad que se
    atendió. Por eso al decir que sí se apunta esta huella
    (`equipo.Unidad.codigo`) y con otra se vuelve a preguntar. No hay firmas de
    las que fiarse: tras actualizar la unidad se pregunta una vez más, y es lo
    esperado.

    Entra todo `.prdrive/` menos lo que cambia con el uso: `state/`, `logs/`,
    `filters/`, `keys/`, `runtime/` (el agente usa su propio Python),
    `sync_config.toml` (lo edita la ventana), el fichero de control y los
    iconos. Todo lo demás cuenta, también lo desconocido: con la carpeta de la
    unidad en `sys.path`, un `json.py` suelto se importaría antes que el de
    verdad. Los `__pycache__` no, porque los hijos del agente los buscan en su
    carpeta (`PYTHONPYCACHEPREFIX`, `_opciones_hijo()`). `bin/` tampoco: el
    agente no ejecuta el rclone de la unidad, pasa el suyo
    (`model.RCLONE_DEL_AGENTE`), y por eso la huella cuesta milisegundos y no
    lo que tarda en leerse un binario de 60 MB. `rclone.conf` entra: la opción
    `ssh` de un remoto sftp es una orden.
    """
    base = app(raiz)
    rutas: list[Path] = []
    try:
        for carpeta, carpetas, ficheros in os.walk(base):
            rel = Path(carpeta).relative_to(base)
            arriba = rel == Path(".")
            carpetas[:] = [c for c in carpetas if c != "__pycache__"
                           and not (arriba and c in HUELLA_SIN_CARPETAS)]
            for f in ficheros:
                if arriba and f in HUELLA_SIN_FICHEROS:
                    continue
                if Path(f).suffix.lower() in HUELLA_SIN_EXTENSIONES:
                    continue
                rutas.append(rel / f)
        h = hashlib.sha256()
        for rel in sorted(set(rutas), key=lambda r: r.as_posix()):
            ruta = base / rel
            h.update(f"{rel.as_posix()}\0{ruta.stat().st_size}\0".encode("utf-8"))
            with ruta.open("rb") as f:
                for trozo in iter(lambda: f.read(1 << 20), b""):
                    h.update(trozo)
    except (OSError, ValueError):
        return None
    return h.hexdigest()


def version_vieja(raiz: Path) -> str | None:
    """Devuelve la versión de esa raíz si es anterior a `VERSION_MINIMA`.

    Es `None` si vale y `""` si no se sabe, que también cuenta como vieja. De
    una unidad de la lista la `VERSION` es de fiar: entra en la huella que se
    aceptó.
    """
    version = update.installed_version(app(raiz))
    if version and not update.is_newer(VERSION_MINIMA, version):
        return None
    return version


def estado_de(raiz: Path) -> Path:
    """Devuelve la carpeta `state/` de una raíz."""
    return app(raiz) / "state"


def nombre_de(raiz: Path, uid: str, recordado: str = "") -> str:
    """Devuelve el nombre de la unidad en la flota.

    Sale de su `state/fleet.json` (solo se lee); si no tiene, el que el agente
    recuerda de ella y, si no, el principio del id.
    """
    guardado = store.read_json(estado_de(raiz) / "fleet.json").get("nombre")
    if isinstance(guardado, str) and guardado.strip():
        return guardado.strip()
    return recordado or f"{APP_NAME.upper()} {uid[:8]}"


@dataclass(frozen=True)
class Servicio:
    """Lo que el servicio de una raíz sincroniza: sus parejas y cada cuánto.

    Args:
        parejas: Las parejas, con su remoto.
        minutos: El intervalo entre pasadas.
        locales: La carpeta local, tal como está escrita en el TOML, de cada
            pareja que pide vigilar sus cambios (`watch = true`), por nombre.
    """
    parejas: tuple[pl.Pareja, ...]
    minutos: float
    locales: Mapping[str, str] = field(default_factory=dict)


def leer_servicio(raiz: Path) -> Servicio:
    """Devuelve las parejas y el intervalo del servicio de esa raíz.

    Los elige como su propio runsync: `ui_prefs.json` > `[daemon]` > todas
    (`prefs.elegir()`). Se lee el TOML a pelo y no con `model.parse_config()`
    porque la raíz puede ir en otra versión que el agente: lo que valida es su
    `sync.py`, y un modo que este agente no conozca no puede dejarla sin
    servicio.

    Raises:
        ValueError: Con la frase que decir si no hay nada que atender.
    """
    try:
        crudo = tomllib.loads((app(raiz) / "sync_config.toml").read_text(encoding="utf-8"))
    except OSError as e:
        raise ValueError(f"no se puede leer sync_config.toml ({e})") from e
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"sync_config.toml no es TOML válido ({e})") from e
    defaults = crudo.get("defaults") if isinstance(crudo.get("defaults"), dict) else {}
    remotos: dict[str, str] = {}
    locales: dict[str, str] = {}
    for p in crudo.get("pair") if isinstance(crudo.get("pair"), list) else []:
        # El nombre va a la línea de órdenes de su `sync.py` y a sus carpetas
        # de `state/` y `filters/`: uno que su parser no admitiría (`--resync`,
        # `a/b`) no se lanza, aunque el `sync.py` de esa raíz sea de antes de
        # la regla.
        if isinstance(p, dict) and isinstance(p.get("name"), str) \
                and model.problema_nombre(p["name"]) is None:
            remotos[p["name"]] = str(p.get("remote", defaults.get("remote",
                                                                  model.DEFAULT_REMOTE)))
            # Se vigila solo lo que pide `watch = true` en un modo con el local
            # de origen (`model.pide_watch()`) y tiene dónde mirar.
            local = p.get("local")
            if model.pide_watch(p) and isinstance(local, str) and local.strip():
                locales[p["name"]] = local
            else:
                locales.pop(p["name"], None)
    if not remotos:
        raise ValueError("sync_config.toml no tiene ninguna pareja")
    daemon = crudo.get("daemon") if isinstance(crudo.get("daemon"), dict) else {}
    elegidas, minutos, _ = prefs.elegir(list(remotos), daemon,
                                        store.read_json(estado_de(raiz) / "ui_prefs.json"))
    return Servicio(tuple(pl.Pareja(n, remotos[n], vigila=n in locales) for n in elegidas),
                    minutos, {n: locales[n] for n in elegidas if n in locales})


def orden_sonda(raiz: Path, remoto: str) -> list[str] | None:
    """Devuelve la orden que pregunta a rclone por el remoto de esa raíz.

    Es `None` sin rclone. Es `lsd` del remoto con `catalog.NET_FLAGS`: lo
    mínimo que exige conectar y entrar, con plazos cortos para que un remoto
    caído no tenga la cola parada.
    """
    binario = rclone_propio()
    if binario is None:
        return None
    return [str(binario), "--config", str(app(raiz) / "rclone.conf"),
            *catalog.NET_FLAGS, "lsd", f"{remoto}:", "--max-depth", "1"]


def en_la_raiz(raiz: Path, ruta: Path) -> Path | None:
    """Devuelve `ruta` si, con los enlaces resueltos, sigue dentro de `raiz`.

    Si no, `None`. Lo que el agente escribe en una raíz (el diario y el lock de
    su servicio) va a donde diga ESA raíz, y una unidad es de quien la trae: un
    `state/daemon.log` que fuera un enlace a `~/.bashrc`, o un `state/` que
    llevara a la carpeta personal, haría que el agente escribiera en el equipo.
    Solo se escribe donde la ruta resuelta sigue dentro de la raíz resuelta.
    """
    try:
        real, base = os.path.realpath(ruta), os.path.realpath(raiz)
        if os.path.commonpath([os.path.normcase(real), os.path.normcase(base)]) \
                != os.path.normcase(base):
            return None
    except (OSError, ValueError):
        return None
    return ruta


_SIN_ENLACE = getattr(os, "O_NOFOLLOW", 0)
"""Abre para añadir sin seguir un enlace en el último tramo (POSIX).

Lo demás lo descarta `en_la_raiz()`.
"""


def dlog(raiz: Path, msg: str) -> None:
    """Añade una línea al diario del servicio de la raíz (`state/daemon.log`).

    Como el de runsync. Se abre y se cierra en cada línea: nada se queda
    abierto en la unidad.
    """
    ruta = en_la_raiz(raiz, estado_de(raiz) / "daemon.log")
    if ruta is None:
        return
    try:
        fd = os.open(ruta, os.O_WRONLY | os.O_APPEND | os.O_CREAT | _SIN_ENLACE, 0o666)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(f"{store.stamp()} {msg}\n")
    except OSError:
        pass


def presente(raiz: Path) -> bool:
    """Indica si la raíz tiene su fichero de control a la vista."""
    try:
        return (raiz / penwatch.CONTROL_FILE).is_file()
    except OSError:
        return False


def punto_ocupado(unidad: equipo.Unidad) -> str | None:
    r"""Devuelve por qué no se puede montar ahí la raíz cifrada, o `None` si se puede.

    El agente no se inventa otra letra ni otro sitio: los programas apuntan a
    la raíz, y un almacén de Obsidian en `P:\\obsidian` se rompería si mañana
    fuera `Q:`. En Linux, el punto de montaje vacío es una carpeta normal, y lo
    que se guarde ahí con el contenedor cerrado quedaría tapado al montarlo.
    """
    if unidad.letra:
        raiz = Path(f"{unidad.letra}:\\")
        try:
            existe = raiz.exists()
        except OSError:
            existe = True
        if not existe:
            return None
        try:
            suya = penwatch.control_id(raiz) == unidad.id
        except OSError:
            suya = False
        if suya:
            return (f"La letra {unidad.letra}: tiene su raíz, pero el contenedor está "
                    f"cerrado: es un volumen fantasma (se desconectó sin bloquear). "
                    f"Bloquéala y vuelve a desbloquearla.")
        return (f"La letra {unidad.letra}: está ocupada por otra unidad, y no se "
                f"cambia: los programas apuntan a {unidad.letra}:\\. Libérala y "
                f"vuelve a desbloquear.")
    punto = Path(unidad.ruta)
    try:
        if os.path.ismount(punto):
            return f"Ya hay algo montado en {punto}."
        if punto.is_dir() and any(punto.iterdir()):
            return (f"{punto} tiene cosas con el contenedor cerrado: no se monta "
                    f"encima, porque quedarían tapadas. Muévelas a otro sitio y "
                    f"vuelve a desbloquear.")
    except OSError as e:
        return f"No puedo mirar {punto}: {e}"
    return None


def bloqueada(unidad: equipo.Unidad) -> bool:
    """Indica si el contenedor de esa raíz ya está cerrado.

    En Windows, que la letra se vaya no basta: forzando el desmontaje con un
    fichero abierto dentro, la letra desaparece y el driver sigue reteniendo el
    `.hc`. Bloqueada es el `.hc` libre y la letra ida (la de un fantasma
    también tiene que irse). En Linux no hay esa prueba (`vestibulo.retenido()`
    no contesta): es el punto de montaje sin montar.
    """
    raiz = Path(unidad.ruta)
    if unidad.letra:
        return vestibulo.retenido(unidad.contenedor) is not True and not presente(raiz)
    try:
        return not os.path.ismount(raiz) and not presente(raiz)
    except OSError:
        return False


def orden_bloquear(unidad: equipo.Unidad) -> list[str] | None:
    """Devuelve el desmontaje de la raíz cifrada, o `None` sin VeraCrypt.

    SIN `/silent`, como `Expulsar PRDRIVE.bat`: con un fichero abierto dentro
    VeraCrypt pregunta si forzar, y esa decisión es de la persona. Sin
    VeraCrypt es que no hay ni el instalado ni el del agente.
    """
    exe = veracrypt_de_la_raiz()
    if exe is None:
        return None
    if IS_WIN:
        return [exe, "/dismount", unidad.letra or unidad.ruta[:1], "/quit"]
    if hay_pantalla():
        return [exe, "-d", unidad.contenedor]
    return [exe, "--text", "--non-interactive", "-d", unidad.contenedor]


def resultado(rc: int, texto: str) -> str:
    """Devuelve cómo acabó una pasada, con el criterio de `runsync.daemon_cycle()`.

    Args:
        rc: Código de salida de `sync.py`.
        texto: Su salida.
    """
    if rc != 0:
        return RED if moderacion.es_de_red(texto) else FALLO
    if "saltada" in texto.lower():
        return SALTADA
    return OK


@dataclass
class Conexion:
    """Lo que el agente recuerda de una unidad conectada.

    Args:
        id: El id de la unidad (el de su fichero de control).
        raiz: Dónde está montada.
        nombre: Su nombre en la flota.
        desde: Cuándo se la vio por primera vez.
        pregunta: Si no está en la lista, la pregunta en curso.
        hijo: La ventanita de la pregunta.
        respuesta: `AHORA_NO`, para esta conexión.
        lanzada: Modo `ui`: su ventana ya se ha abierto.
        pausa: La última vez que se vio una ventana o un stop.
        lock: El `daemon.lock.json` que tenemos escrito.
        soltando: Soltado, pero su fichero sigue sin borrar.
        servicio: Lo que sincroniza su servicio.
        error: Por qué no hay servicio que atender.
        avisado_error: Si ese error ya se ha dicho.
        firma: Los mtimes de lo que decide el servicio.
        motivo: Qué le pasa, para `status`.
        reanudar: «Iniciar servicio» en su ventana (`reanudar` en su buzón): al
            irse la ventana se vuelve enseguida, sin la `GRACIA` que se da a un
            servicio que la ventana arrancara por su cuenta.
        huella: Su huella al conectarla (`huella()`).
        cambiada: La huella no es la que se aceptó: una unidad de la lista con
            otro código se trata como una que no lo está hasta que se vuelva a
            decir que sí.
        vieja: Su versión (o «») si es anterior a `VERSION_MINIMA`: ejecutaría
            el rclone de la unidad, así que no se atiende ni se abre.
        fisica: Su raíz física, si va en un contenedor VeraCrypt: la del
            vestíbulo, donde está su `autorun.inf`.
        emblema: Su icono para la bandeja (`volumen.emblema()`), o `None` si
            todavía no se ha leído.
        emblema_leido: Cuándo se leyó.
    """
    id: str
    raiz: Path
    nombre: str
    desde: float
    pregunta: pl.Pregunta | None = None
    hijo: Any = None
    respuesta: str | None = None
    lanzada: bool = False
    pausa: float | None = None
    lock: dict | None = None
    soltando: bool = False
    servicio: Servicio | None = None
    error: str | None = None
    avisado_error: bool = False
    firma: tuple = ()
    motivo: str = ""
    reanudar: bool = False
    huella: str | None = None
    cambiada: bool = False
    vieja: str | None = None
    fisica: Path | None = None
    emblema: dict | None = None
    emblema_leido: float = -math.inf


@dataclass
class Desbloqueo:
    """«Desbloquear», lanzado: VeraCrypt está pidiendo la contraseña.

    Args:
        desde: Cuándo se lanzó.
        proc: El VeraCrypt que monta.
        salio: Cuándo se vio que había salido.
        abrir: Abrir su ventana en cuanto se vea abierta.
        copia: La copia elevada que puede seguir tras él.
        explorar: Abrirla en el explorador de archivos en cuanto se vea
            abierta.
    """
    desde: float
    proc: Any = None
    salio: float | None = None
    abrir: bool = False
    copia: Copia | None = None
    explorar: bool = False


@dataclass
class Bloqueo:
    """«Bloquear», pedido y todavía no hecho.

    Args:
        desde: Cuándo se pidió.
        proc: El VeraCrypt que desmonta, ya lanzado.
        lanzado: Cuándo se lanzó.
        copia: La copia elevada que puede seguir tras él.
    """
    desde: float
    proc: Any = None
    lanzado: float = 0.0
    copia: Copia | None = None


@dataclass(frozen=True)
class Copia:
    """Los VeraCrypt que ya había antes de lanzar el nuestro, por nombre.

    VeraCrypt sin su driver instalado y sin administrador (el portable del
    agente) se relanza elevado (`/q UAC`) y el proceso que lanzamos sale con 0
    a los dos segundos (`InitApp`, `LaunchElevatedProcess` en
    `Common/Dlgcode.c`), mientras la copia elevada sigue: pide la contraseña o
    pregunta si forzar el desmontaje. Esa copia es la misma imagen, así que se
    la reconoce por el nombre y por no estar antes, como hacen
    `crypto._esperar_copia_elevada()` y `:vc_pendiente` del vestíbulo. Sin
    esto, un «Desbloquear» se daría por cancelado con la persona todavía en el
    aviso de UAC, y un «Bloquear», por fallido mientras VeraCrypt pregunta.

    Args:
        imagen: Nombre del ejecutable.
        antes: Los pid con esa imagen antes de lanzar el nuestro.
    """
    imagen: str
    antes: frozenset[int]

    @staticmethod
    def antes_de(cmd: list[str]) -> Copia:
        """Anota los procesos que hay con la imagen de `cmd[0]` antes de lanzarlo.

        En Linux no hay copia (el que lanzamos es el que pregunta) y
        `procesos()` no ve nada: la copia no sigue nunca.
        """
        imagen = Path(cmd[0]).name
        return Copia(imagen, frozenset(procesos(imagen)))

    def sigue(self) -> bool:
        """Indica si hay un proceso nuevo con esa imagen."""
        return bool(procesos(self.imagen) - self.antes)


def _sigue_vivo(proc: Any, copia: Copia | None) -> bool:
    """Indica si VeraCrypt sigue en ello: el proceso lanzado o su copia elevada."""
    if proc is not None and proc.poll() is None:
        return True
    return copia is not None and copia.sigue()


@dataclass
class Pasada:
    """Una pasada en marcha: el `sync.py` hijo de una pareja.

    Args:
        proc: El proceso hijo.
        tarea: Lo que se está sincronizando.
        desde: Cuándo empezó.
        salida: Fichero temporal donde va su salida.
        nombre: Nombre de la unidad a la que pertenece.
    """
    proc: Any
    tarea: pl.Tarea
    desde: float
    salida: Path
    nombre: str


class Mirar(NamedTuple):
    """Una carpeta que toca mirar en un muestreo.

    Args:
        clave: `(raíz, pareja)`.
        con: La conexión de la raíz cuando se pidió: si al recoger la foto ya
            no es esa, la unidad se fue (o se fue y volvió) y la foto no vale.
        raiz: Dónde estaba montada la raíz.
        carpeta: La carpeta local de la pareja, sin resolver.
    """
    clave: tuple[str, str]
    con: Conexion
    raiz: Path
    carpeta: Path


class Muestreo:
    """Una vuelta a las carpetas vigiladas, corriendo en su propio hilo.

    Recorrer una carpeta de un pendrive o de la red puede llevar segundos, y la
    vuelta del agente (la cola, la bandeja, los buzones) no puede esperar a
    ella: el hilo toma las fotos y las deja aquí, y la vuelta siguiente las
    recoge. Solo hay un muestreo a la vez. El hilo escribe y el del agente lee;
    `hecho` se pone el último, así que quien lo ve a `True` ya tiene el resto.

    Args:
        trabajo: Las carpetas que hay que mirar.
        tope: Cuántas entradas se cuentan como mucho en cada una.
        ignorar: Carpetas de su raíz que no se miran.

    Attributes:
        fotos: La foto de cada pareja, o `None` si no se pudo tomar.
        fuera: Las parejas cuya carpeta, con los enlaces resueltos, queda fuera
            de su raíz: no se mira.
        descartar: Las parejas cuya pasada ha empezado o acabado mientras se
            miraba. Su foto es de antes o de a medias y no cuenta.
        hecho: Si ya ha terminado.
    """

    def __init__(self, trabajo: list[Mirar], tope: int, ignorar: tuple[str, ...]) -> None:
        """Prepara el muestreo sin correrlo."""
        self.trabajo = trabajo
        self.tope = tope
        self.ignorar = ignorar
        self.fotos: dict[tuple[str, str], pl.Huella | None] = {}
        self.fuera: set[tuple[str, str]] = set()
        self.descartar: set[tuple[str, str]] = set()
        self.hecho = False

    def correr(self) -> None:
        """Toma la foto de cada carpeta; es lo que corre el hilo.

        Una carpeta que no se deja mirar (cualquier error) queda sin foto: es
        «no sé», no un cambio, y el hilo no se cae.
        """
        try:
            for mirar in self.trabajo:
                if en_la_raiz(mirar.raiz, mirar.carpeta) is None:
                    self.fuera.add(mirar.clave)
                    continue
                try:
                    self.fotos[mirar.clave] = huella_local(mirar.carpeta, self.tope,
                                                           self.ignorar)
                except Exception:                   # noqa: BLE001
                    self.fotos[mirar.clave] = None
        finally:
            self.hecho = True


@dataclass
class Agente:
    """Lo que el agente recuerda y decide, vuelta a vuelta.

    Args:
        reloj: La hora, en segundos; los tests la sustituyen.
        ajustes: Su configuración (`agente.json`).
        conexiones: Las unidades conectadas y contadas, por id.
        vistas: Las unidades abiertas que se han visto y cuántas veces seguidas
            (hasta `ESTABLE`).
        cerradas: Lo mismo para las VeraCrypt cerradas, por la marca de su
            vestíbulo.
        vestibulos: Los vestíbulos ya tratados en esta conexión, por id: su
            raíz física, o `""` si ya se abrió y todavía no se ha visto la
            entrada.
        marcas: El estado de cada pareja para el planificador, por `(raíz,
            pareja)`.
        entorno: Batería, red de uso medido, remotos sin conexión y pausa, para
            el planificador.
        entorno_leido: Cuándo se leyó el entorno por última vez.
        pasada: La pasada en marcha, si la hay.
        heredada: La de un agente anterior que sigue viva al arrancar
            (`pasada.json`).
        cortada: La pasada que el instalador cortó al parar al agente anterior:
            su pareja espera a que caduque el `.lck` que dejó
            (`equipo.ESPERA_TRAS_CORTE`).
        urgentes: Las parejas pedidas con «Sincronizar ahora», como `(raíz,
            pareja)`.
        pausado: Si se ha pedido pausa.
        terminar: Si se ha pedido parar.
        sospechas: Los fallos que parecen de red y esperan a la sonda, por
            `(raíz, remoto)`: la pareja y su marca de antes.
        sin_red_avisado: Los `(raíz, remoto)` sin conexión ya avisados.
        retenido: Por qué no se lanza nada ahora, para no repetirlo en el
            diario.
        rafaga_hasta: Hasta cuándo se recorre en cada vuelta.
        despertado: La última vuelta de la suspensión apuntada.
        ultimo_estado: Lo último que se escribió en `estado.json`.
        ultima_vista: La última `bandeja.Vista` puesta.
        ultima_buena: Cuándo acabó bien la última pasada (el reloj).
        ausentes: Las raíces del equipo que no están donde dice su `ruta`, ya
            avisadas.
        desbloqueos: Los «Desbloquear» lanzados, por id de la raíz cifrada.
        pedidas: Las raíces cifradas cuya contraseña ya se pidió al iniciar
            sesión.
        bloqueos: Los «Bloquear» en marcha.
        fantasmas: Los volúmenes fantasma ya dichos.
        recorridos: Los recorridos hechos desde que arrancó.
        sin_rclone_avisado: Si ya se dijo que el agente no tiene rclone.
        peticiones: Lo que pide la bandeja, que corre en otro hilo: los mismos
            diccionarios que el buzón, sin pasar por disco.
        bandeja: La bandeja, si la hay (`poner(vista)`), para enseñarle el
            estado.
        inicio: Cuándo arrancó, en hora de verdad (`equipo.pedir()` sella con
            ella): un «parar» de antes iba para el agente anterior.
        version: La de este agente.
        nueva: La más nueva que se sabe (su tag), o `None`.
        version_mirada: Cuándo se miró.
        nueva_avisada: La que ya se avisó.
        actualizando: El `agente.py actualizar` en marcha.
        avisos_de_red: Lo que oye los cambios de red (`red.AvisosDeRed`), si
            lo hay: con él, un remoto sin conexión se sondea cuando vuelve la
            red y el temporizador es solo el respaldo largo.
        cambio_de_red: La ráfaga de avisos de red que todavía no se ha
            sondeado (`pl.CambioDeRed`).
        cambios: Las reglas de los cambios locales (`watch = true`).
        vigiladas: Lo que se recuerda de cada pareja que pide `watch`, por
            `(raíz, pareja)`; se olvida al irse la raíz.
        muestreo: El muestreo de carpetas en marcha, si lo hay.
    """
    reloj: Any = time.time
    ajustes: equipo.Ajustes = field(default_factory=equipo.leer_ajustes)
    conexiones: dict[str, Conexion] = field(default_factory=dict)
    vistas: dict[str, int] = field(default_factory=dict)
    cerradas: dict[str, int] = field(default_factory=dict)
    vestibulos: dict[str, str] = field(default_factory=dict)
    marcas: dict[tuple[str, str], pl.Marca] = field(default_factory=dict)
    entorno: pl.Entorno = field(default_factory=pl.Entorno)
    entorno_leido: float = -math.inf
    pasada: Pasada | None = None
    heredada: dict | None = field(default_factory=equipo.pasada_viva)
    cortada: dict | None = field(default_factory=equipo.pasada_cortada)
    urgentes: list[tuple[str, str]] = field(default_factory=list)
    pausado: bool = False
    terminar: bool = False
    sospechas: dict[tuple[str, str], tuple[str, pl.Marca]] = field(default_factory=dict)
    sin_red_avisado: set[tuple[str, str]] = field(default_factory=set)
    retenido: str | None = None
    rafaga_hasta: float = -math.inf
    despertado: float = -math.inf
    ultimo_estado: dict | None = None
    ultima_vista: Any = None
    ultima_buena: float | None = None
    ausentes: set[str] = field(default_factory=set)
    desbloqueos: dict[str, Desbloqueo] = field(default_factory=dict)
    pedidas: set[str] = field(default_factory=set)
    bloqueos: dict[str, Bloqueo] = field(default_factory=dict)
    fantasmas: set[str] = field(default_factory=set)
    recorridos: int = 0
    sin_rclone_avisado: bool = False
    peticiones: Any = field(default_factory=queue.SimpleQueue)
    bandeja: Any = None
    inicio: float = field(default_factory=time.time)
    version: str = field(default_factory=lambda: update.installed_version(SCRIPT_DIR))
    nueva: str | None = None
    version_mirada: float = -math.inf
    nueva_avisada: str | None = None
    actualizando: Any = None
    avisos_de_red: Any = None
    cambio_de_red: pl.CambioDeRed | None = None
    cambios: pl.PoliticaCambios = field(default_factory=pl.PoliticaCambios)
    vigiladas: dict[tuple[str, str], pl.Vigilada] = field(default_factory=dict)
    muestreo: Muestreo | None = None

    def vuelta(self, recorrer: bool = True) -> pl.Decision | None:
        """Hace una vuelta del agente y devuelve lo que decidió lanzar, si algo.

        Lee los buzones, recorre los volúmenes, gestiona las conexiones
        (preguntas, fin de pasada, bloqueos, el contrato con el servicio de
        cada raíz), lee el entorno, mira si hay versión nueva, mira los cambios
        locales de las parejas con `watch = true` y, si no hay una pasada en
        marcha, decide la siguiente. Termina escribiendo el estado.

        Args:
            recorrer: Si en esta vuelta toca recorrer los volúmenes.

        Returns:
            La decisión del planificador, o `None`.
        """
        ahora = self.reloj()
        self._buzon(ahora)
        if recorrer:
            self._recorrer(ahora)
            self._al_iniciar(ahora)
        self._seguir_desbloqueos(ahora)
        for con in list(self.conexiones.values()):
            if not presente(con.raiz):
                self._desconectar(con.id, ahora, {})
        self._preguntas(ahora)
        self._fin_de_pasada(ahora)
        self._cambios_de_red(ahora)
        self._buzones_de_raices(ahora)
        self._bloqueos(ahora)
        for con in self.conexiones.values():
            self._contrato(con, ahora)
        self._leer_entorno(ahora)
        self._mirar_version(ahora)
        self._vigilar(ahora)
        decision = None
        if self.pasada is None and not self.terminar and not self._heredada():
            decision = self._decidir(ahora)
        self._escribir_estado()
        return decision

    def _recorrer(self, ahora: float) -> None:
        """Recorre las unidades y pone al día conexiones, vestíbulos y raíces ausentes.

        Una unidad cuenta cuando se ha visto `ESTABLE` veces seguidas. Las
        abiertas se reconocen por su fichero de control y las de VeraCrypt
        cerradas por la marca de su vestíbulo.
        """
        abiertas: dict[str, Path] = {}
        cerradas: dict[str, Path] = {}
        # Las raíces del equipo, primero y por su ruta: son carpetas, no
        # volúmenes, y el recorrido no las vería. Van como las raíces extra de
        # penwatch: el recorrido sigue siendo uno.
        propias = [u.ruta for u in self.ajustes.raices.values()]
        for raiz in penwatch.candidate_roots(
                {"extra_roots": propias + list(self.ajustes.extra_roots)}):
            try:
                if (raiz / penwatch.CONTROL_FILE).is_file():
                    if not (raiz / penwatch.STRUCT_MARKER).is_file():
                        continue
                    uid = penwatch.control_id(raiz)
                    if uid:
                        abiertas.setdefault(uid, raiz)
                elif ((raiz / penwatch.VESTIBULE_MARKER).is_file()
                      and (raiz / penwatch.CONTAINER_FILE).is_file()):
                    uid = penwatch.vestibule_id(raiz)
                    if uid:
                        cerradas.setdefault(uid, raiz)
            except OSError:
                continue            # un volumen bloqueado contesta con error: ahora no
        self._fantasmas(abiertas)

        for uid in list(self.vistas):
            if uid not in abiertas:
                del self.vistas[uid]
        for uid, raiz in abiertas.items():
            con = self.conexiones.get(uid)
            if con is not None:
                con.raiz = raiz                 # remontada en otra letra
                continue
            self.vistas[uid] = self.vistas.get(uid, 0) + 1
            if self.vistas[uid] >= ESTABLE:
                del self.vistas[uid]
                self._conectar(uid, raiz, ahora)
            else:
                self.rafaga_hasta = max(self.rafaga_hasta, ahora + 3 * TICK)
        for uid in list(self.conexiones):
            if uid not in abiertas:
                self._desconectar(uid, ahora, cerradas)
        for uid, con in self.conexiones.items():
            con.fisica = cerradas.get(uid)      # su vestíbulo, con el contenedor abierto
        self._vestibulos(cerradas, ahora)
        self._raices_ausentes(abiertas)
        self.recorridos += 1

    def _fantasmas(self, abiertas: dict[str, Path]) -> None:
        """Quita de `abiertas` las raíces cifradas que son un volumen fantasma.

        Una raíz cifrada vista en su letra con el `.hc` LIBRE no está abierta:
        es lo que deja un volumen que se fue sin desmontar (suspender con el
        cierre automático de VeraCrypt, H-10), que sirve el fichero de control
        de la caché. No se atiende y se dice una vez cómo salir.
        """
        for uid, unidad in self.ajustes.cifradas.items():
            if uid not in abiertas:
                self.fantasmas.discard(uid)
                continue
            if vestibulo.retenido(unidad.contenedor) is not False:
                self.fantasmas.discard(uid)
                continue
            del abiertas[uid]
            if uid not in self.fantasmas:
                self.fantasmas.add(uid)
                avisar(f"{unidad.nombre or APP_NAME}: el volumen no responde",
                       f"{unidad.ruta} sigue ahí, pero su contenedor está cerrado. "
                       f"Bloquéala y vuelve a desbloquearla.", True)

    def _raices_ausentes(self, abiertas: dict[str, Path]) -> None:
        """Dice UNA vez que una raíz del equipo no está en su ruta.

        No se busca en otro sitio ni se recrea: mover la carpeta deja las
        líneas base apuntando a lo que ya no está, y eso se arregla
        reinstalando.
        """
        for uid, unidad in self.ajustes.raices.items():
            if uid in abiertas:
                if uid in self.ausentes:
                    self.ausentes.discard(uid)
                    diario(f"{unidad.nombre or uid[:8]}: la raíz vuelve a estar en "
                           f"{unidad.ruta}")
                continue
            if unidad.cifrada:
                # Cerrada no es ausente: es lo normal con el contenedor
                # bloqueado. Lo que falta es el contenedor mismo.
                try:
                    hay = Path(unidad.contenedor).is_file()
                except OSError:
                    hay = True
                if hay:
                    if uid in self.ausentes:
                        self.ausentes.discard(uid)
                        diario(f"{unidad.nombre or uid[:8]}: su contenedor vuelve a "
                               f"estar en {unidad.contenedor}")
                elif uid not in self.ausentes:
                    self.ausentes.add(uid)
                    avisar(f"{unidad.nombre or APP_NAME}: no encuentro su contenedor",
                           f"La raíz cifrada de este equipo tenía que estar en "
                           f"{unidad.contenedor}. Si lo has movido, vuelve a ponerlo "
                           f"ahí o reinstala.", True)
                continue
            if uid not in self.ausentes:
                self.ausentes.add(uid)
                avisar(f"{unidad.nombre or APP_NAME}: no encuentro su carpeta",
                       f"La raíz de este equipo tenía que estar en {unidad.ruta}. "
                       f"Si la has movido, vuelve a ponerla ahí o reinstala.", True)

    def _conectar(self, uid: str, raiz: Path, ahora: float) -> None:
        """Da por conectada una unidad que se ha visto `ESTABLE` veces.

        Una que no está en la lista se pregunta. De una de la lista con otro
        código, o de una versión anterior a `VERSION_MINIMA`, no se ejecuta
        nada suyo. Si no, se atiende según su modo.
        """
        unidad = self.ajustes.unidades.get(uid)
        nombre = nombre_de(raiz, uid, unidad.nombre if unidad else "")
        con = Conexion(uid, raiz, nombre, ahora)
        # Un lock con nuestro pid es de la conexión anterior (se desenchufó y
        # no se escribe en una unidad que no está): si no se la vuelve a servir
        # se borra (`_soltar`), si sí se reescribe (`_tomar`). De una que no
        # está en la lista no se lee más que su id y su nombre.
        con.soltando = unidad is not None and self._lock_es_nuestro(con)
        self.conexiones[uid] = con
        desbloqueo = self.desbloqueos.pop(uid, None)
        # Cada conexión empieza de cero, como el servicio que se arrancaba al
        # enchufar: se sincroniza enseguida y el modo `sync` vuelve a tocar.
        for clave in [k for k in self.marcas if k[0] == uid]:
            del self.marcas[clave]
        self._olvidar_vigiladas(uid)
        con.vieja = version_vieja(raiz)
        if con.vieja is not None:
            # Antes de preguntar y de la huella: no hay nada que decidir hasta
            # que se actualice.
            avisar(f"{nombre}: su programa es anterior a la {VERSION_MINIMA}",
                   f"Lleva la {con.vieja or 'versión desconocida'}. El agente no la "
                   f"atiende hasta que la actualices con el instalador («Actualizar»).",
                   True)
            diario(f"{nombre}: versión {con.vieja or 'desconocida'}, anterior a la "
                   f"{VERSION_MINIMA}; no se atiende")
            return
        if unidad is None:
            self._preguntar(con, ahora)
            return
        if not unidad.es_raiz:
            con.huella = huella(raiz)
            if not unidad.codigo and con.huella:
                # Atendida sin haberla visto (el asistente, `atender ID` con
                # ella fuera): la huella se apunta la primera vez que se
                # conecta.
                unidad = replace(unidad, codigo=con.huella)
                self._guardar(self.ajustes.con_unidad(unidad))
                diario(f"{nombre}: apuntada la huella de su código")
            elif con.huella != unidad.codigo:
                con.cambiada = True
                diario(f"{nombre}: su código no es el que tenía cuando se atendió; "
                       f"no se ejecuta nada suyo hasta que se vuelva a decir que sí")
                self._preguntar(con, ahora)
                return
        if unidad.nombre != nombre:
            self._guardar(self.ajustes.con_unidad(replace(unidad, nombre=nombre)))
        diario(f"{nombre}: " + ("raíz de este equipo" if unidad.es_raiz else "conectada")
               + f" en {raiz} (modo {unidad.modo})")
        if unidad.modo == equipo.UI:
            self._abrir_ventana(con)
        elif desbloqueo is not None and desbloqueo.abrir:
            self._lanzar_ventana(con)       # «Abrir» con ella bloqueada
        if desbloqueo is not None and desbloqueo.explorar:
            self._explorar(con)             # «Abrir en explorador» con ella bloqueada

    def _desconectar(self, uid: str, ahora: float, cerradas: dict[str, Path]) -> None:
        """Olvida la conexión de una unidad que ya no está.

        Args:
            uid: El id de la unidad.
            ahora: La hora del reloj del agente.
            cerradas: Los vestíbulos que se ven ahora.
        """
        con = self.conexiones.pop(uid, None)
        if con is None:
            return
        if con.hijo is not None and con.hijo.poll() is None:
            try:
                con.hijo.terminate()
            except OSError:
                pass
        # No se escribe en una unidad que ya no está. Si sigue ahí la entrada
        # del contenedor, se ha cerrado con la unidad puesta: es «Expulsar», no
        # una conexión nueva, y no se vuelve a pedir la contraseña. Se apunta
        # como ya pedida aunque no se sepa todavía: si en el siguiente
        # recorrido no hay entrada, `_vestibulos()` la rearma.
        self.vestibulos[uid] = str(cerradas.get(uid, ""))
        self.urgentes = [u for u in self.urgentes if u[0] != uid]
        self.entorno = replace(self.entorno, sin_conexion={
            k: v for k, v in self.entorno.sin_conexion.items() if k[0] != uid})
        self.sospechas = {k: v for k, v in self.sospechas.items() if k[0] != uid}
        self.sin_red_avisado = {k for k in self.sin_red_avisado if k[0] != uid}
        self._olvidar_vigiladas(uid)
        unidad = self.ajustes.unidades.get(uid)
        diario(f"{con.nombre} " + ("bloqueada: su contenedor se ha cerrado"
                                   if unidad is not None and unidad.cifrada else
                                   "ya no está en su carpeta"
                                   if unidad is not None and unidad.es_raiz
                                   else "desconectada"))

    def _vestibulos(self, cerradas: dict[str, Path], ahora: float) -> None:
        """Abre las unidades VeraCrypt de la lista que se ven cerradas.

        Se le pide a VeraCrypt una vez por conexión, como hace penwatch. Una
        que no está en la lista, nunca: no se ejecuta nada de una unidad que no
        se ha aceptado.
        """
        for uid in list(self.vestibulos):
            if uid not in cerradas:
                if self.vestibulos.pop(uid):
                    diario("entrada de una unidad cifrada retirada; apertura rearmada")
        for uid in list(self.cerradas):
            if uid not in cerradas:
                del self.cerradas[uid]
        for uid, raiz in cerradas.items():
            if uid in self.conexiones or uid in self.vestibulos:
                continue
            unidad = self.ajustes.unidades.get(uid)
            if unidad is None or unidad.modo == equipo.NADA:
                continue
            self.cerradas[uid] = self.cerradas.get(uid, 0) + 1
            if self.cerradas[uid] < ESTABLE:
                self.rafaga_hasta = max(self.rafaga_hasta, ahora + 3 * TICK)
                continue
            del self.cerradas[uid]
            self.vestibulos[uid] = str(raiz)
            diario(f"{unidad.nombre or uid[:8]}: cifrada y cerrada en {raiz}")
            abrir_contenedor(raiz)

    def _preguntar(self, con: Conexion, ahora: float) -> None:
        """Pregunta por una unidad que no está en la lista, o cuyo código ha cambiado.

        Avisa y abre la ventanita de la pregunta con cuenta atrás. Sin pantalla
        donde preguntar cuenta como «Ahora no».
        """
        espera = self.ajustes.espera_unidad_nueva
        if con.cambiada:
            avisar(f"{con.nombre}: su código ha cambiado",
                   "¿Seguir atendiéndola en este equipo? Hasta que contestes, no se "
                   "ejecuta nada suyo.", True)
        else:
            avisar(f"Se ha conectado {con.nombre}", "¿Atenderla en este equipo?")
        if not hay_pantalla():
            con.respuesta = pl.AHORA_NO
            diario(f"{con.nombre} ({con.id[:8]}) "
                   + ("tiene otro código" if con.cambiada else "no está en la lista")
                   + f" y no hay entorno gráfico donde preguntar: cuenta como «Ahora "
                     f"no». Para atenderla: agente.py atender {con.id}")
            return
        con.pregunta = pl.Pregunta(con.id, ahora, espera)
        try:
            con.hijo = lanzar([python(ventana=True), str(SCRIPT_DIR / "agente.py"),
                               "pregunta", "--nombre", con.nombre,
                               "--segundos", str(int(espera)),
                               *(["--cambiada"] if con.cambiada else [])],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              **_opciones_hijo(equipo.DIR))
        except OSError as e:
            diario(f"no he podido abrir la pregunta por {con.nombre}: {e}")
            con.hijo = None

    def _preguntas(self, ahora: float) -> None:
        """Recoge las respuestas de las preguntas en curso.

        El sí atiende la unidad; el no, o el tiempo, la deja sin atender
        mientras siga conectada.
        """
        for con in self.conexiones.values():
            if con.pregunta is None:
                continue
            rc = con.hijo.poll() if con.hijo is not None else 2
            respuesta = None if rc is None else (pl.ATENDER if rc == 0 else pl.AHORA_NO)
            final = pl.resolver(con.pregunta, respuesta, ahora)
            if final is None:
                continue
            if con.hijo is not None and con.hijo.poll() is None:
                try:
                    con.hijo.terminate()   # se cierra sola a cero; por si no
                except OSError:
                    pass
            con.pregunta, con.hijo = None, None
            if final == pl.ATENDER:
                self._atender(con)
            else:
                con.respuesta = pl.AHORA_NO
                diario(f"{con.nombre}: «Ahora no»; no se atiende mientras siga "
                       f"conectada. Para atenderla: agente.py atender {con.id}")

    def _atender(self, con: Conexion) -> None:
        """Es el sí: la unidad entra en la lista con la huella de su código de ahora.

        Si ya estaba (su código había cambiado), conserva su modo.
        """
        con.respuesta = None
        codigo = huella(con.raiz) or ""
        con.huella = codigo or None
        antes = self.ajustes.unidades.get(con.id)
        if antes is not None:
            con.cambiada = False
            self._guardar(self.ajustes.con_unidad(replace(antes, codigo=codigo)))
            diario(f"{con.nombre}: se sigue atendiendo, con su código de ahora")
            if antes.modo == equipo.UI:
                self._abrir_ventana(con)
            return
        self._guardar(self.ajustes.con_unidad(
            equipo.Unidad(con.id, equipo.MODO_AL_ATENDER, con.nombre, codigo=codigo)))
        diario(f"{con.nombre} añadida a la lista (modo {equipo.MODO_AL_ATENDER})")

    def _guardar(self, ajustes: equipo.Ajustes) -> None:
        """Guarda los ajustes.

        Si no se pueden escribir, el cambio vale hasta que se reinicie el
        agente.
        """
        self.ajustes = ajustes
        if not equipo.guardar_ajustes(ajustes):
            diario("no he podido escribir agente.json; el cambio vale hasta que "
                   "me reinicie")

    def _abrir_ventana(self, con: Conexion) -> None:
        """Hace el modo `ui`: abre la ventana al conectarla.

        No la abre si ya hay una ventana o un servicio en marcha.
        """
        con.lanzada = True
        ocupado = penwatch.aplicacion_en_marcha(con.raiz)
        if ocupado:
            diario(f"{con.nombre}: no abro la ventana: {ocupado}")
            return
        self._lanzar_ventana(con)

    def _lanzar_ventana(self, con: Conexion) -> None:
        """Abre la ventana de runsync de esa raíz.

        Se lanza con el Python del agente y desde fuera de la raíz. Nuestro
        servicio no estorba: la ventana lo pausa al abrirse (`daemon.stop`).
        Otra ventana sí, y runsync ya se negaría.
        """
        if con.vieja is not None or rclone_propio() is None:
            diario(f"{con.nombre}: no abro su ventana: "
                   + (self._motivo_sin_servicio(con) if con.vieja is not None
                      else SIN_RCLONE))
            return
        ventana = penwatch._vivo_aqui(con.raiz, penwatch.UI_LOCK_REL)
        if ventana is not None:
            diario(f"{con.nombre}: su ventana ya está abierta (pid {ventana.get('pid')})")
            return
        if not hay_pantalla():
            diario(f"{con.nombre}: sin entorno gráfico; no hay dónde abrir "
                   f"la ventana")
            return
        try:
            lanzar([python(ventana=True), str(app(con.raiz) / "runsync.py")],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   **_opciones_hijo(equipo.DIR, separado=True))
            diario(f"{con.nombre}: ventana abierta")
        except OSError as e:
            diario(f"{con.nombre}: no he podido abrir la ventana: {e}")

    def _sirve(self, con: Conexion) -> bool:
        """Indica si el agente tiene que servir esa conexión.

        Es una unidad de la lista, con su código aceptado, de una versión
        válida, en modo `daemon` o `sync` y sin el «Pausar» de su ventana.
        """
        unidad = self.ajustes.unidades.get(con.id)
        return unidad is not None and not con.cambiada and con.vieja is None \
            and unidad.modo in (equipo.DAEMON, equipo.SYNC) and not unidad.pausada

    def _cargar_servicio(self, con: Conexion) -> None:
        """Relee las parejas y el intervalo si cambió el TOML o la memoria del servicio.

        La ventana los edita mientras el agente sigue vivo.
        """
        firma = []
        for ruta in (app(con.raiz) / "sync_config.toml",
                     estado_de(con.raiz) / "ui_prefs.json"):
            try:
                firma.append(ruta.stat().st_mtime_ns)
            except OSError:
                firma.append(None)
        if tuple(firma) == con.firma and (con.servicio or con.error):
            return
        con.firma = tuple(firma)
        try:
            con.servicio, con.error = leer_servicio(con.raiz), None
        except ValueError as e:
            con.servicio, con.error = None, str(e)
            if not con.avisado_error:
                con.avisado_error = True
                avisar(f"{con.nombre}: nada que sincronizar", con.error)

    def _otro_servicio(self, con: Conexion) -> dict | None:
        """Devuelve el registro de otro servicio vivo de este equipo en esa raíz.

        Es `None` si no hay otro.
        """
        info = store.read_json(con.raiz / penwatch.DAEMON_LOCK_REL)
        if info.get("host") != HOST:
            return None
        try:
            pid = int(info.get("pid", -1))
        except (TypeError, ValueError):
            return None
        if pid == os.getpid() or not pid_alive(pid):
            return None
        return info

    def _contrato(self, con: Conexion, ahora: float) -> None:
        """Cumple el contrato de servicio de esa raíz con los ficheros de su `state/`.

        Toma o suelta el lock, obedece `daemon.stop`, se pone en pausa mientras
        haya una ventana de runsync abierta y se aparta si otro servicio vivo
        tiene el lock. Deja en `con.motivo` por qué no sirve, si no sirve.
        """
        ocupada = self.pasada is not None and self.pasada.tarea.raiz == con.id
        if con.id in self.bloqueos:
            # Se está bloqueando: ni se encola ni se vuelve a tomar el lock.
            if not ocupada:
                self._soltar(con)
            con.motivo = "bloqueándose"
            return
        if not self._sirve(con):
            if not ocupada:                 # el lock se suelta al acabar la pareja
                self._soltar(con)
            con.motivo = self._motivo_sin_servicio(con)
            return
        if rclone_propio() is None:
            if not ocupada:
                self._soltar(con)
            con.motivo = SIN_RCLONE
            if not self.sin_rclone_avisado:
                self.sin_rclone_avisado = True
                avisar(f"{APP_NAME}: el agente no tiene su rclone", SIN_RCLONE, True)
            return
        stop = estado_de(con.raiz) / "daemon.stop"
        try:
            parar = stop.exists()
        except OSError:
            parar = False
        otro = self._otro_servicio(con)
        if parar and not ocupada and otro is None:
            # Lo que hace runsync al abrir su ventana (o con `--auto`, o con
            # cualquier orden pasada a `sync.py`, o su servicio al arrancar):
            # acabada la pareja en curso se suelta el lock y se borra el stop.
            # No se sale: se hace pausa. Con otro servicio vivo en el lock, el
            # stop es para ESE: borrarlo lo dejaría corriendo.
            self._soltar(con)
            stop.unlink(missing_ok=True)
            con.pausa = ahora
            diario(f"{con.nombre}: runsync ha pedido parar el servicio; en pausa")
            dlog(con.raiz, "servicio (agente del equipo) en pausa: lo ha pedido runsync")
        ventana = penwatch._vivo_aqui(con.raiz, penwatch.UI_LOCK_REL) is not None
        if ventana:
            con.pausa = ahora
        if otro is not None and con.lock is not None:
            con.lock = None                 # el lock ya es de otro
        self._cargar_servicio(con)

        if con.pausa is not None and (ventana or (ahora - con.pausa < GRACIA
                                                  and not con.reanudar)):
            con.motivo = "en pausa: hay una ventana de runsync abierta"
        elif otro is not None:
            con.motivo = f"la atiende otro servicio (pid {otro.get('pid')})"
        elif con.servicio is None:
            con.motivo = f"sin servicio: {con.error}"
        else:
            if con.pausa is not None:
                # La otra mitad de «en pausa»: sin ella, el diario no decía
                # cuándo se volvía a atender tras cerrar la ventana (visto en
                # real).
                diario(f"{con.nombre}: sin ventana de runsync; vuelvo a atenderla")
                dlog(con.raiz, "servicio (agente del equipo) reanudado")
            con.pausa = None
            con.reanudar = False
            con.motivo = ""
            if con.lock is None:
                self._tomar(con)
            elif not self._lock_es_nuestro(con):
                con.lock = None             # lo borró runsync al cansarse de esperar
            return
        if not ocupada:
            self._soltar(con)

    def _motivo_sin_servicio(self, con: Conexion) -> str:
        """Devuelve por qué el agente no atiende esa conexión, para `status`."""
        if con.pregunta is not None:
            return "preguntando si atenderla"
        if con.respuesta == pl.AHORA_NO:
            return "«Ahora no» en esta conexión"
        if con.vieja is not None:
            return (f"su programa es de la {con.vieja or 'versión desconocida'}: el agente "
                    f"atiende desde la {VERSION_MINIMA}")
        if con.cambiada:
            return "su código ha cambiado desde que se atendió"
        unidad = self.ajustes.unidades.get(con.id)
        if unidad is None:
            return "sin atender"
        if unidad.pausada and unidad.modo in (equipo.DAEMON, equipo.SYNC):
            return "en pausa desde su ventana: no se sincroniza hasta «Reanudar»"
        return f"modo {unidad.modo}: {equipo.TEXTO_MODO[unidad.modo]}"

    def _lock_es_nuestro(self, con: Conexion) -> bool:
        """Indica si el `daemon.lock.json` de la raíz es de este agente."""
        info = store.read_json(con.raiz / penwatch.DAEMON_LOCK_REL)
        return info.get("pid") == os.getpid() and info.get("host") == HOST

    def _tomar(self, con: Conexion) -> None:
        """Se hace servicio de la raíz, si nadie vivo lo es.

        Mirar y escribir son UN paso (`store.tomar_registro()`, O_EXCL) y el
        servicio de runsync toma el mismo fichero igual
        (`runsync.tomar_lock()`): de los dos que llegan a la vez, solo uno lo
        crea y el otro se aparta. Mirar primero y escribir después dejaba que
        los dos se creyeran el servicio. Un runsync de antes todavía escribe
        sin mirar: lo que queda es la pareja en curso, y en la vuelta siguiente
        el agente ve su lock y se aparta (`_otro_servicio`).
        """
        unidad = self.ajustes.unidades[con.id]
        datos = {"pid": os.getpid(), "host": HOST, "started": store.stamp(),
                 "pairs": [p.nombre for p in con.servicio.parejas],
                 "interval_min": con.servicio.minutos, "agente": True,
                 "modo": unidad.modo}
        destino = en_la_raiz(con.raiz, con.raiz / penwatch.DAEMON_LOCK_REL)
        if destino is None:
            return
        tomado, otro = store.tomar_registro(destino, datos, equipo.vivo_aqui)
        if tomado is False and otro and otro.get("pid") == os.getpid() \
                and otro.get("host") == HOST:
            # El nuestro, que no se pudo borrar al soltarlo (`soltando`).
            tomado = store.write_json(destino, datos)
        if tomado:
            con.lock = datos
            con.soltando = False        # el fichero vuelve a ser uno vivo
            dlog(con.raiz, f"servicio (agente del equipo, pid {os.getpid()}) atendiendo: "
                           f"{', '.join(datos['pairs'])}"
                           + ("" if unidad.modo == equipo.SYNC
                              else f" cada {con.servicio.minutos:g} min"))

    def _soltar(self, con: Conexion) -> None:
        """Deja de atender la raíz y borra nuestro `daemon.lock.json`.

        En Windows no se borra un fichero que otro tiene abierto, y runsync lee
        este cada 0,3 s mientras espera a que el servicio pare (WinError 32,
        H-2 de las pruebas en real). Entonces se deja de atender igual
        (`con.lock` a `None`, que es lo que mira el planificador) y el fichero
        se reintenta en la vuelta siguiente (`soltando`): con el pid del agente
        dentro, runsync esperaría hasta rendirse.
        """
        if con.lock is None and not con.soltando:
            return
        con.lock = None
        if self._lock_es_nuestro(con):
            try:
                (con.raiz / penwatch.DAEMON_LOCK_REL).unlink(missing_ok=True)
            except OSError:
                con.soltando = True
                return
        con.soltando = False

    def _raices(self) -> list[pl.Raiz]:
        """Devuelve las raíces que el planificador puede atender.

        Las que tienen nuestro lock y su servicio y no se están bloqueando. De
        la raíz de la pasada cortada se quita su pareja mientras espera.
        """
        raices = []
        cortada = self._cortada()
        for con in self.conexiones.values():
            if con.lock is None or con.servicio is None or con.id in self.bloqueos:
                continue
            modo = self.ajustes.unidades[con.id].modo
            intervalo = math.inf if modo == equipo.SYNC else con.servicio.minutos * 60
            parejas = con.servicio.parejas
            if cortada is not None and cortada.get("raiz") == con.id:
                parejas = tuple(p for p in parejas if p.nombre != cortada.get("pareja"))
            raices.append(pl.Raiz(con.id, parejas, intervalo))
        return raices

    def _cortada(self) -> dict | None:
        """Devuelve la pasada que cortó el instalador, mientras su pareja espere.

        Lanzarla antes de que caduque el `.lck` que dejó falla con «prior lock
        file found» y se avisaría de un fallo que no es (H-15). Solo esa
        pareja: las demás siguen como siempre.
        """
        c = self.cortada
        if c is None:
            return None
        if self.reloj() >= c["cortada"] + equipo.ESPERA_TRAS_CORTE:
            diario(f"[{c.get('unidad')}] {c.get('pareja')}: ya ha caducado el bloqueo "
                   f"de la pasada cortada; vuelve a su turno")
            self.cortada = None
            return None
        if not c.get("avisada"):
            c["avisada"] = True
            diario(f"[{c.get('unidad')}] {c.get('pareja')}: su pasada se cortó al parar "
                   f"el agente anterior; espera a que caduque su bloqueo")
        return c

    def _heredada(self) -> bool:
        """Indica si sigue viva la pasada que dejó en marcha el agente anterior.

        Se fue con SIGTERM al cerrar sesión, o el instalador lo terminó a la
        fuerza: la pasada es otro proceso y sigue. Mientras viva no se lanza
        otra: serían dos a la vez, quizá sobre la misma pareja.
        """
        if self.heredada is None:
            return False
        viva = equipo.pasada_viva()
        if viva is not None:
            texto = (f"sigue la pasada de {viva.get('pareja')} en {viva.get('unidad')} "
                     f"que dejó en marcha el agente anterior (pid {viva.get('pid')})")
            if self.retenido != texto:
                diario(f"no se lanza nada: {texto}")
                self.retenido = texto
            return True
        diario("ha acabado la pasada que dejó en marcha el agente anterior")
        self.heredada = None
        self.retenido = None
        return False

    def _decidir(self, ahora: float) -> pl.Decision:
        """Pide al planificador la siguiente tarea y la lanza.

        Returns:
            La decisión, con la tarea o el motivo de no lanzar nada.
        """
        entorno = replace(self.entorno, pausado=self.pausado)
        decision = pl.decidir(self._raices(), self.marcas, entorno, ahora,
                              self.ajustes.politica, urgentes=self.urgentes,
                              vigiladas=self.vigiladas, cambios=self.cambios)
        if decision.retenido != self.retenido:
            diario(f"no se lanza nada: {decision.retenido}" if decision.retenido
                   else "se vuelve a sincronizar")
            self.retenido = decision.retenido
        if decision.tarea is not None:
            self._lanzar(decision.tarea, ahora)
        return decision

    def _olvidar_vigiladas(self, uid: str) -> None:
        """Olvida lo recordado de las parejas vigiladas de una raíz."""
        self.vigiladas = {k: v for k, v in self.vigiladas.items() if k[0] != uid}

    def _vigilar(self, ahora: float) -> None:
        """Mira los ficheros locales de las parejas con `watch = true`.

        Cada vuelta recoge el muestreo que haya terminado y, si no hay otro en
        marcha, pide el de las parejas a las que les toca (`pl.a_recorrer()`:
        cada `sondeo` segundos, y no mientras la moderación retenga las
        pasadas). Solo se mira donde el servicio de la raíz está en marcha: sin
        pausa de su ventana (`Unidad.pausada`), sin ventana de runsync abierta,
        sin otro servicio y sin estar bloqueándose. Lo recordado de una pareja
        que deja de estarlo se olvida: al volver, la primera foto es la de
        partida y los cambios de entretanto (hechos, por ejemplo, desde la
        ventana, que sincroniza por su cuenta) no disparan nada. Una pareja
        abandonada por grande no se vuelve a mirar en esta conexión.

        El recorrido va en un hilo (`hilo()`): en un pendrive tarda segundos y
        esta vuelta no espera.
        """
        raices = [r for r in self._raices() if not self.conexiones[r.clave].motivo]
        validas = {(r.clave, p.nombre) for r in raices for p in r.parejas if p.vigila}
        for clave in [k for k, v in self.vigiladas.items()
                      if k not in validas and not v.abandonada]:
            del self.vigiladas[clave]
        self._recoger_fotos(ahora, validas)
        if self.muestreo is not None or self.terminar or self.heredada is not None:
            return
        retenido = pl.moderacion(replace(self.entorno, pausado=self.pausado),
                                 self.ajustes.politica) is not None
        pasada = self.pasada
        ocupadas = [(pasada.tarea.raiz, pasada.tarea.pareja)] \
            if pasada is not None and pasada.tarea.tipo == pl.PASADA else []
        claves = pl.a_recorrer(raices, self.vigiladas, ahora, self.cambios, retenido,
                               ocupadas)
        if not claves:
            return
        trabajo = []
        for raiz, pareja in claves:
            con = self.conexiones[raiz]
            trabajo.append(Mirar((raiz, pareja), con, con.raiz,
                                 con.raiz / con.servicio.locales[pareja]))
        self.muestreo = Muestreo(trabajo, self.cambios.tope_entradas, IGNORAR_CAMBIOS)
        hilo(self.muestreo.correr)

    def _mirando(self, uid: str) -> bool:
        """Indica si hay una foto en marcha de alguna carpeta de esa raíz.

        Mientras dura, el hilo tiene la carpeta abierta: desmontar el
        contenedor en ese momento haría que VeraCrypt preguntara si forzar.
        """
        m = self.muestreo
        return m is not None and not m.hecho and any(x.clave[0] == uid for x in m.trabajo)

    def _recoger_fotos(self, ahora: float, validas: set[tuple[str, str]]) -> None:
        """Pone en lo recordado de cada pareja la foto del muestreo terminado.

        No cuenta la foto de una pareja que ya no se vigila, de una unidad que
        se fue (aunque volviera), ni de una cuya pasada está en marcha o ha
        empezado o acabado mientras se miraba: lo que ve ahí lo ha escrito
        rclone, no la persona. La pareja que supera el tope o cuya carpeta cae
        fuera de la raíz se abandona, y se dice una vez en el diario y en el de
        la raíz.

        Args:
            ahora: La hora del reloj del agente.
            validas: Las parejas que se vigilan ahora.
        """
        m = self.muestreo
        if m is None or not m.hecho:
            return
        self.muestreo = None
        pasada = self.pasada
        en_curso = (pasada.tarea.raiz, pasada.tarea.pareja) \
            if pasada is not None and pasada.tarea.tipo == pl.PASADA else None
        for mirar in m.trabajo:
            clave = mirar.clave
            con = self.conexiones.get(clave[0])
            if con is not mirar.con or clave not in validas or clave in m.descartar \
                    or clave == en_curso:
                continue
            antes = self.vigiladas.get(clave, pl.Vigilada())
            if clave in m.fuera:
                self.vigiladas[clave] = pl.Vigilada(None, None, ahora, abandonada=True)
                diario(f"[{con.nombre}] {clave[1]}: su carpeta cae fuera de la raíz; "
                       f"no se vigilan sus cambios")
                dlog(con.raiz, f"[{clave[1]}] watch: su carpeta cae fuera de la raíz; no se "
                               f"vigila")
                continue
            despues = pl.observar(antes, m.fotos.get(clave), ahora, self.cambios)
            self.vigiladas[clave] = despues
            if pl.se_abandona(antes, despues):
                diario(f"[{con.nombre}] {clave[1]}: más de {self.cambios.tope_entradas} "
                       f"entradas; deja de vigilarse y sigue por su intervalo")
                dlog(con.raiz, f"[{clave[1]}] watch: más de {self.cambios.tope_entradas} "
                               f"entradas; no se vigila, manda el intervalo")

    def _rehacer_foto(self, clave: tuple[str, str], ahora: float) -> None:
        """Deja una pareja lista para tomar su foto de después de una pasada.

        La pasada, buena o mala, ha escrito en su carpeta: la foto siguiente es
        la de partida y no dispara nada (`pl.tras_pasada()`), y se pide ya, sin
        esperar al sondeo. Si había un muestreo en marcha, lo que vea de esa
        pareja es de antes de acabar la pasada y no cuenta.

        Args:
            clave: `(raíz, pareja)` de la pasada que acaba de terminar.
            ahora: La hora del reloj del agente.
        """
        if self.muestreo is not None:
            self.muestreo.descartar.add(clave)
        antes = self.vigiladas.get(clave)
        if antes is not None:
            self.vigiladas[clave] = replace(pl.tras_pasada(antes, None, ahora),
                                            revisada=None)

    def _lanzar(self, tarea: pl.Tarea, ahora: float) -> None:
        """Lanza una tarea: una pasada (el `sync.py` de la raíz) o una sonda del remoto.

        Antes de una pasada se comprueba otra vez que el lock sigue siendo
        nuestro.
        """
        con = self.conexiones[tarea.raiz]
        if tarea.tipo == pl.PASADA and not self._lock_es_nuestro(con):
            # Justo antes de lanzar, otra vez: un runsync de antes escribe su
            # lock sin mirar, y el que haya ahí es el servicio.
            con.lock = None
            diario(f"[{con.nombre}] el lock ya no es mío; no lanzo {tarea.pareja}")
            return
        if tarea.urgente:
            self.urgentes = [u for u in self.urgentes if u != (tarea.raiz, tarea.pareja)]
        if tarea.tipo == pl.SONDA:
            args = orden_sonda(con.raiz, tarea.remoto)
            if args is None:
                # Sin rclone para este equipo no hay con qué preguntar: se hace
                # como si el remoto contestara. Así el fallo que se sospechaba
                # de red cuenta como fallo de la pareja y espera lo suyo;
                # tomarlo por red otra vez la relanzaría en cada vuelta.
                self._fin_de_sonda(con, tarea.remoto, 0, "", ahora)
                return
            cwd = app(con.raiz)             # rclone.conf resuelve contra aquí
            que = f"¿contesta {tarea.remoto}?"
        else:
            # `--`: lo que sigue es un nombre, nunca una opción de sync.py.
            args = [python(), str(app(con.raiz) / "sync.py"), "--", tarea.pareja]
            cwd = equipo.DIR
            que = tarea.pareja
        salida = equipo.DIR / "pasada.out"
        try:
            equipo.DIR.mkdir(parents=True, exist_ok=True)
            with salida.open("wb") as f:
                # En su propio grupo: si hay que cortarla
                # (`install/agente.parar_agente()`, pasado su plazo), se corta
                # con su rclone.
                proc = lanzar(args, stdout=f, stderr=subprocess.STDOUT,
                              **_opciones_hijo(cwd, separado=tarea.tipo == pl.PASADA))
        except OSError as e:
            diario(f"[{con.nombre}] no he podido lanzar {que}: {e}")
            if tarea.tipo == pl.PASADA:
                self.marcas[(tarea.raiz, tarea.pareja)] = pl.registrar(
                    self.marcas.get((tarea.raiz, tarea.pareja), pl.Marca()), FALLO, ahora)
            return
        self.pasada = Pasada(proc, tarea, ahora, salida, con.nombre)
        if tarea.tipo == pl.PASADA:
            equipo.apuntar_pasada({"pid": getattr(proc, "pid", None), "agente": os.getpid(),
                                   "raiz": tarea.raiz,
                                   "unidad": con.nombre, "pareja": tarea.pareja,
                                   "desde": store.stamp()})
        diario(f"[{con.nombre}] {que}" + (" (a petición)" if tarea.urgente
                                          else " (han cambiado sus ficheros)"
                                          if tarea.por_cambios else ""))

    def _fin_de_pasada(self, ahora: float) -> None:
        """Recoge el resultado de la pasada que haya acabado.

        Lo apunta en el planificador, en el diario de la raíz y en su lock, y
        avisa solo si la pareja EMPIEZA a fallar. Un fallo que parece de red
        dispara la sonda.
        """
        pasada = self.pasada
        if pasada is None:
            return
        rc = pasada.proc.poll()
        if rc is None:
            return
        self.pasada = None
        if store.read_json(equipo.pasada_json()).get("agente") == os.getpid():
            equipo.pasada_json().unlink(missing_ok=True)
        texto = ""
        try:
            with pasada.salida.open("rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - COLA_SALIDA))
                texto = f.read().decode("utf-8", errors="replace")
        except OSError:
            pass
        pasada.salida.unlink(missing_ok=True)
        tarea = pasada.tarea
        con = self.conexiones.get(tarea.raiz)
        if con is None or not presente(con.raiz):
            # Una unidad desenchufada a mitad de pasada no es un fallo de la
            # pareja y no se avisa de nada.
            diario(f"[{pasada.nombre}] la unidad se ha ido a mitad de "
                   f"{tarea.pareja or 'la comprobación'}; no cuenta")
            return
        segundos = ahora - pasada.desde
        if tarea.tipo == pl.SONDA:
            self._fin_de_sonda(con, tarea.remoto, rc, texto, ahora)
            return

        clave = (tarea.raiz, tarea.pareja)
        como = resultado(rc, texto)
        antes = self.marcas.get(clave, pl.Marca())
        despues = pl.registrar(antes, como, ahora)
        self.marcas[clave] = despues
        self._rehacer_foto(clave, ahora)
        if como == FALLO or como == RED:
            dlog(con.raiz, f"[{tarea.pareja}] FALLÓ (rc={rc}, {segundos:.0f}s); salida:")
            for linea in texto.splitlines()[-12:]:
                dlog(con.raiz, f"[{tarea.pareja}]   {linea}")
        elif como == SALTADA:
            dlog(con.raiz, f"[{tarea.pareja}] saltada: requiere --resync; ejecútalo a "
                           f"mano desde la ventana")
        else:
            dlog(con.raiz, f"[{tarea.pareja}] OK ({segundos:.0f}s)")
            if como == OK:
                self.ultima_buena = ahora
        diario(f"[{con.nombre}] {tarea.pareja}: {TEXTO_RESULTADO[como]} "
               f"(rc={rc}, {segundos:.0f}s)")
        self._apuntar_en_lock(con, tarea.pareja, como, rc, segundos)

        if como == RED:
            # ¿De verdad es la red? La sonda va ya: si el remoto contesta,
            # aquel fallo era de la pareja y se apunta como tal
            # (`_fin_de_sonda`).
            self.sospechas[(tarea.raiz, tarea.remoto)] = (tarea.pareja, antes)
            self.entorno = pl.sin_conexion(self.entorno, tarea.raiz, tarea.remoto, ahora)
        elif pl.empieza_a_fallar(antes, despues):
            avisar(f"{con.nombre}: falla {tarea.pareja}", self._donde_mirar(con), True)

    def _fin_de_sonda(self, con: Conexion, remoto: str, rc: int, texto: str,
                      ahora: float) -> None:
        """Recoge el resultado de una sonda al remoto.

        Si contesta, el fallo sospechado de red era de la pareja; si no, el
        remoto queda sin conexión hasta el próximo sondeo.
        """
        clave = (con.id, remoto)
        sospecha = self.sospechas.pop(clave, None)
        # Un error que no es de red (credenciales, una ruta) es un remoto que
        # contesta: no hay nada que esperar.
        if rc == 0 or not moderacion.es_de_red(texto):
            self.entorno = pl.con_conexion(self.entorno, con.id, remoto)
            if sospecha is not None:
                pareja, antes = sospecha
                despues = pl.registrar(antes, FALLO, ahora)
                self.marcas[(con.id, pareja)] = despues
                diario(f"[{con.nombre}] {remoto} contesta: el fallo de {pareja} no era "
                       f"de la red")
                if pl.empieza_a_fallar(antes, despues):
                    avisar(f"{con.nombre}: falla {pareja}", self._donde_mirar(con), True)
            elif clave in self.sin_red_avisado:
                self.sin_red_avisado.discard(clave)
                diario(f"[{con.nombre}] vuelve la conexión con {remoto}")
            return
        self.entorno = pl.sin_conexion(
            self.entorno, con.id, remoto,
            ahora + pl.sondeo(self.ajustes.politica, self.avisa_la_red()))
        if clave not in self.sin_red_avisado:
            self.sin_red_avisado.add(clave)
            avisar(f"{con.nombre}: sin conexión con {remoto}",
                   "Sus parejas esperan a que vuelva la red; no hace falta hacer nada.")

    def avisa_la_red(self) -> bool:
        """Indica si el sistema le dice ahora al agente cuándo vuelve la red."""
        return bool(self.avisos_de_red is not None
                    and getattr(self.avisos_de_red, "activa", False))

    def _cambios_de_red(self, ahora: float) -> None:
        """Sondea los remotos sin conexión cuando se calma una ráfaga de avisos de red.

        Una sonda por remoto y por ráfaga (`pl.red_asentada()`); con una tarea
        en marcha espera a que acabe. Si no hay ningún remoto sin conexión, la
        ráfaga se olvida sin más.
        """
        if not pl.red_asentada(self.cambio_de_red, ahora, self.pasada is not None):
            return
        self.cambio_de_red = None
        if self.entorno.sin_conexion:
            self.entorno = pl.sondear_ya(self.entorno, ahora)
            diario("la red ha cambiado: se prueban ya los remotos sin conexión")

    def _donde_mirar(self, con: Conexion) -> str:
        """Devuelve dónde mirar para ver qué ha pasado.

        Depende de si es la raíz del equipo o una unidad.
        """
        unidad = self.ajustes.unidades.get(con.id)
        if unidad is not None and unidad.es_raiz:
            return f"Abre la ventana de {APP_NAME} en este equipo para ver qué ha pasado."
        return f"Abre {APP_NAME} desde la unidad para ver qué ha pasado."

    def _apuntar_en_lock(self, con: Conexion, pareja: str, como: str, rc: int,
                         segundos: float) -> None:
        """Deja en el lock lo mismo que el servicio de runsync tras cada ciclo."""
        if con.lock is None or not self._lock_es_nuestro(con):
            return
        texto = {OK: f"OK ({segundos:.0f}s)", SALTADA: "saltada (requiere --resync manual)"
                 }.get(como, f"ERROR rc={rc}")
        con.lock.setdefault("last_results", {})[pareja] = texto
        con.lock["last_cycle"] = store.stamp()
        destino = en_la_raiz(con.raiz, con.raiz / penwatch.DAEMON_LOCK_REL)
        if destino is not None:
            store.write_json(destino, con.lock)

    def _cifrada(self, uid: str) -> equipo.Unidad | None:
        """Devuelve la raíz cifrada de ese id, o la única que haya si no se dice."""
        cifradas = self.ajustes.cifradas
        if uid:
            return cifradas.get(uid)
        return next(iter(cifradas.values())) if len(cifradas) == 1 else None

    def _al_iniciar(self, ahora: float) -> None:
        """Pide la contraseña de las raíces cifradas al iniciar sesión.

        Es `pedir_al_iniciar`, UNA vez por arranque del agente. Se espera a
        haber recorrido lo bastante para saber que no está ya abierta (una raíz
        cuenta al verla `ESTABLE` veces). Si se cancela, no se vuelve a pedir
        hasta «Desbloquear»: es la regla de «una vez por conexión» de las
        unidades cifradas.
        """
        if self.recorridos < ESTABLE:
            return
        for uid, unidad in self.ajustes.cifradas.items():
            if uid in self.pedidas:
                continue
            self.pedidas.add(uid)
            if (self.ajustes.pedir_al_iniciar and unidad.modo != equipo.NADA
                    and uid not in self.conexiones and uid not in self.vistas):
                self._desbloquear(unidad, ahora, "al iniciar sesión")

    def _desbloquear(self, unidad: equipo.Unidad, ahora: float, por: str = "",
                     abrir: bool = False, explorar: bool = False) -> bool:
        """Le pide a VeraCrypt que abra la raíz cifrada. No espera.

        Abierta es cuando el recorrido VE su id con el `.hc` retenido.

        Args:
            unidad: La raíz cifrada.
            ahora: La hora del reloj del agente.
            por: Por qué se desbloquea, para el diario.
            abrir: Abrir su ventana en cuanto se vea abierta («Configurar» en
                la bandeja).
            explorar: Abrirla en el explorador de archivos en cuanto se vea
                abierta («Abrir en explorador» en la bandeja).

        Returns:
            `True` si lanzó VeraCrypt.
        """
        nombre = unidad.nombre or APP_NAME
        if unidad.id in self.conexiones or unidad.id in self.vistas:
            diario(f"{nombre}: ya está abierta")
            return False
        if unidad.id in self.bloqueos:
            diario(f"{nombre}: se está bloqueando; desbloquear después")
            return False
        if unidad.id in self.desbloqueos:
            # VeraCrypt ya está pidiendo la contraseña: una segunda ventana
            # suya no ayuda.
            self.desbloqueos[unidad.id].abrir |= abrir
            self.desbloqueos[unidad.id].explorar |= explorar
            diario(f"{nombre}: ya se está desbloqueando")
            return False
        try:
            hay = Path(unidad.contenedor).is_file()
        except OSError:
            hay = False
        if not hay:
            avisar(f"{nombre}: no encuentro su contenedor",
                   f"Tenía que estar en {unidad.contenedor}.", True)
            return False
        ocupado = punto_ocupado(unidad)
        if ocupado:
            avisar(f"{nombre}: no la desbloqueo", ocupado, True)
            return False
        exe = veracrypt_de_la_raiz()
        cmd = penwatch.veracrypt_command(None, Path(unidad.contenedor),
                                         unidad.letra or unidad.ruta, respaldo=exe)
        if cmd is None:
            avisar(f"{nombre}: no la puedo desbloquear",
                   SIN_VERACRYPT if exe is None else
                   "No hay escritorio donde VeraCrypt pida la contraseña", True)
            return False
        if not unidad.letra:
            try:
                Path(unidad.ruta).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass                # que lo diga VeraCrypt
        copia = Copia.antes_de(cmd)
        try:
            proc = lanzar(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          **_opciones_hijo(equipo.DIR, separado=True))
        except OSError as e:
            avisar(f"{nombre}: no he podido lanzar VeraCrypt", str(e), True)
            return False
        self.desbloqueos[unidad.id] = Desbloqueo(ahora, proc, abrir=abrir, copia=copia,
                                                 explorar=explorar)
        diario(f"{nombre}: desbloqueando" + (f" ({por})" if por else "")
               + f" en {unidad.ruta}; la contraseña la pide VeraCrypt")
        return True

    def _seguir_desbloqueos(self, ahora: float) -> None:
        """Olvida los «Desbloquear» que no han acabado en la raíz abierta.

        Un «Desbloquear» así se ha cancelado (o la contraseña no era):
        VeraCrypt ha salido y, pasado un rato, no se ve. Se olvida para que la
        bandeja vuelva a ofrecerlo. Con un VeraCrypt que no sale (el de
        escritorio de Linux se queda abierto), al acabarse `ESPERA_ABRIR`.
        """
        for uid, d in list(self.desbloqueos.items()):
            if uid in self.conexiones or uid in self.vistas:
                continue
            if d.salio is None and not _sigue_vivo(d.proc, d.copia):
                d.salio = ahora
            if ((d.salio is not None and ahora - d.salio >= GRACIA_ABRIR)
                    or ahora - d.desde >= ESPERA_ABRIR):
                del self.desbloqueos[uid]
                unidad = self.ajustes.unidades.get(uid)
                diario(f"{(unidad.nombre if unidad else '') or uid[:8]}: no se ha "
                       f"desbloqueado (¿contraseña cancelada?); sigue bloqueada")

    def _bloqueos(self, ahora: float) -> None:
        """Lleva los «Bloquear» pedidos hasta ver la raíz cerrada de verdad.

        Primero se espera a que nada lo impida (la pareja en curso, la foto de
        una de sus carpetas durante `ESPERA_VENTANA` como mucho, su ventana);
        luego VeraCrypt desmonta y se espera a verlo cerrado.
        """
        for uid, b in list(self.bloqueos.items()):
            unidad = self.ajustes.unidades.get(uid)
            if unidad is None or not unidad.cifrada:
                del self.bloqueos[uid]
                continue
            nombre = unidad.nombre or APP_NAME
            con = self.conexiones.get(uid)
            if b.proc is None:
                if con is None and uid not in self.fantasmas:
                    del self.bloqueos[uid]
                    diario(f"{nombre}: ya estaba bloqueada")
                    continue
                if self.pasada is not None and self.pasada.tarea.raiz == uid:
                    continue                # acaba la pareja en curso
                if self._mirando(uid) and ahora - b.desde < ESPERA_VENTANA:
                    continue                # y la foto en curso: tiene la carpeta abierta
                if con is not None and penwatch._vivo_aqui(
                        con.raiz, penwatch.UI_LOCK_REL) is not None:
                    # Su ventana pide bloquear y se cierra; se le da un rato.
                    if ahora - b.desde >= ESPERA_VENTANA:
                        del self.bloqueos[uid]
                        avisar(f"{nombre}: no la bloqueo",
                               "Su ventana sigue abierta. Ciérrala y vuelve a pedirlo.",
                               True)
                    continue
                cmd = orden_bloquear(unidad)
                if cmd is None:
                    del self.bloqueos[uid]
                    avisar(f"{nombre}: no la puedo bloquear", SIN_VERACRYPT, True)
                    continue
                if con is not None:
                    self._soltar(con)
                b.copia = Copia.antes_de(cmd)
                try:
                    b.proc = lanzar(cmd, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    **_opciones_hijo(equipo.DIR, separado=True))
                except OSError as e:
                    del self.bloqueos[uid]
                    avisar(f"{nombre}: no he podido lanzar VeraCrypt", str(e), True)
                    continue
                b.lanzado = ahora
                diario(f"{nombre}: bloqueando; si algo tiene un fichero abierto "
                       f"dentro, VeraCrypt pregunta si forzar")
                continue
            if bloqueada(unidad):
                del self.bloqueos[uid]
                self.desbloqueos.pop(uid, None)
                self.fantasmas.discard(uid)
                if con is not None:
                    self._desconectar(uid, ahora, {})
                diario(f"{nombre}: bloqueada")
                continue
            salio = not _sigue_vivo(b.proc, b.copia)
            if (salio and ahora - b.lanzado >= GRACIA_DESMONTAJE) \
                    or ahora - b.lanzado >= ESPERA_DESMONTAJE:
                del self.bloqueos[uid]
                avisar(f"{nombre}: sigue abierta",
                       "VeraCrypt no la ha cerrado: si un programa tiene un fichero "
                       "abierto dentro, ciérralo y vuelve a bloquear.", True)

    def _leer_entorno(self, ahora: float) -> None:
        """Lee la batería y la red, como mucho cada `MIRAR_ENTORNO` segundos."""
        if ahora - self.entorno_leido < MIRAR_ENTORNO:
            return
        self.entorno_leido = ahora
        energia = moderacion.energia()
        self.entorno = replace(self.entorno, con_bateria=energia.con_bateria,
                               bateria=energia.porcentaje,
                               red_medida=moderacion.red_medida())

    def _mirar_version(self, ahora: float) -> None:
        """Mira, de tarde en tarde, si hay una versión más nueva que la de este agente.

        Va en un hilo, porque es la red. Cuando la hay se dice una vez, y la
        bandeja ofrece «Actualizar» (sección 8 del diseño).
        """
        if self.actualizando is not None and self.actualizando.poll() is not None:
            # Si el agente sigue siendo este, la actualización no ha llegado a
            # sustituirlo: lo cuenta su diario y se puede volver a pedir.
            self.actualizando = None
        if self.nueva and self.nueva != self.nueva_avisada:
            self.nueva_avisada = self.nueva
            avisar(f"Hay una versión nueva de {APP_NAME}: {self.nueva}",
                   f"Tienes la {self.version or 'desconocida'}. "
                   + ("Actualízala desde su icono de la bandeja." if self.con_bandeja()
                      else "Para ponerla: python agente.py actualizar"))
        if ahora - self.version_mirada < MIRAR_VERSION:
            return
        self.version_mirada = ahora

        def trabajo() -> None:
            """Busca la versión nueva y apunta su tag.

            Si falla, lo deja en el diario.
            """
            try:
                rel = buscar_version()
            except Exception as e:                  # noqa: BLE001
                diario(f"no he podido mirar si hay versión nueva: {e}")
                return
            self.nueva = rel.tag if rel is not None else None

        hilo(trabajo)

    def con_bandeja(self) -> bool:
        """Indica si hay un icono en la bandeja que ofrezca lo que dice un aviso."""
        return self.bandeja is not None and bool(getattr(self.bandeja, "puesta", True))

    def _actualizar(self) -> None:
        """Hace el «Actualizar»: lanza un hijo suelto (`agente.py actualizar`).

        Baja la versión nueva y la pone con su propio instalador, que para a
        este agente y arranca el nuevo. Aquí no se espera nada: la red y la
        copia no pueden tener parada la cola.
        """
        if self.actualizando is not None and self.actualizando.poll() is None:
            diario("ya se está actualizando")
            return
        try:
            self.actualizando = lanzar([python(), str(SCRIPT_DIR / "agente.py"),
                                        "actualizar"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       **_opciones_hijo(equipo.DIR, separado=True))
        except OSError as e:
            avisar(f"{APP_NAME}: no he podido actualizar", str(e), True)
            return
        diario(f"actualizando a la {self.nueva or 'última versión'}; lo que pase, "
               f"aquí mismo")

    def pedir(self, peticion: dict) -> None:
        """Deja una petición de la bandeja (otro hilo) para la próxima vuelta.

        Se atiende en el hilo del agente, igual que una del buzón.
        """
        self.peticiones.put(dict(peticion))

    def _buzon(self, ahora: float) -> None:
        """Atiende las peticiones del buzón de `agente.pide` y las de la bandeja."""
        pendientes = equipo.recoger()
        while True:
            try:
                pendientes.append(self.peticiones.get_nowait())
            except queue.Empty:
                break
        for p in pendientes:
            try:
                self._atender_peticion(p, ahora)
            except Exception as e:                      # noqa: BLE001
                diario(f"petición ilegible {p!r}: {e}")

    def _buzones_de_raices(self, ahora: float) -> None:
        """Atiende el buzón de cada raíz conectada y en la lista.

        Es `state/servicio.pide`: lo que su ventana le pide a su servicio. Lo
        que llega por ahí es de ESA raíz, sea cual sea el id que traiga, y solo
        lo que es de una raíz (`equipo.PIDE_SERVICIO`). El de una unidad que no
        está en la lista ni se mira: de ella solo se lee su id y su nombre.
        """
        for con in list(self.conexiones.values()):
            if con.id not in self.ajustes.unidades or con.cambiada or con.vieja is not None:
                continue
            for p in equipo.recoger(estado_de(con.raiz) / equipo.BUZON_SERVICIO):
                if p.get("pide") not in equipo.PIDE_SERVICIO:
                    diario(f"{con.nombre}: su buzón pide {p.get('pide')!r}, que no es "
                           f"cosa de una raíz; ignorado")
                    continue
                try:
                    self._atender_peticion({**p, "id": con.id}, ahora)
                except Exception as e:                  # noqa: BLE001
                    diario(f"petición ilegible {p!r}: {e}")

    def _atender_peticion(self, p: dict, ahora: float) -> None:
        """Atiende una petición del buzón o de la bandeja.

        Cada petición es un `equipo.PIDE_*`: pausar o reanudar el servicio de
        una raíz, atender o poner modo a una unidad, añadir una raíz,
        desbloquear o bloquear una raíz cifrada, abrir la ventana o la carpeta
        de una raíz, despertar, sondear, un cambio de red, cambiar un ajuste,
        una pasada urgente, actualizar, pausa, sigue y parar.

        Args:
            p: La petición.
            ahora: La hora del reloj del agente.
        """
        que = p.get("pide")
        uid = p.get("id") if isinstance(p.get("id"), str) else ""
        if que == equipo.PIDE_REANUDAR:
            # «Reanudar» (o «Iniciar servicio» desde la consola) en la ventana
            # de esa raíz: no arranca un servicio suyo, le quita su pausa y le
            # dice al agente que vuelva en cuanto se cierre. Como el servicio
            # que se arrancaba, empieza con una pasada.
            unidad = self.ajustes.unidades.get(uid)
            if unidad is not None and unidad.pausada:
                self._guardar(self.ajustes.con_unidad(replace(unidad, pausada=False)))
            con = self.conexiones.get(uid)
            if con is None:
                diario(f"reanudar {uid[:8]}: no está conectada")
                return
            con.reanudar = True
            for clave in [k for k in self.marcas if k[0] == uid]:
                del self.marcas[clave]
            diario(f"{con.nombre}: su ventana pide volver a sincronizarla")
            if unidad is not None and unidad.pausada:
                dlog(con.raiz, "servicio (agente del equipo): «Reanudar» desde su ventana")
        elif que == equipo.PIDE_PAUSAR_RAIZ:
            # «Pausar» en la ventana de esa raíz: que no vuelva al cerrarla. Se
            # guarda (`Unidad.pausada`) para que tampoco vuelva al reiniciarse
            # el agente; el lock se suelta en `_contrato`, acabada la pareja en
            # curso, porque `_sirve` ya no la cuenta.
            unidad = self.ajustes.unidades.get(uid)
            if unidad is None:
                diario(f"pausar {uid[:8]!r}: no está en la lista")
                return
            if not unidad.pausada:
                self._guardar(self.ajustes.con_unidad(replace(unidad, pausada=True)))
            self.urgentes = [u for u in self.urgentes if u[0] != uid]
            con = self.conexiones.get(uid)
            nombre = con.nombre if con is not None else (unidad.nombre or uid[:8])
            if con is not None:
                con.reanudar = False
                dlog(con.raiz, "servicio (agente del equipo) en pausa: «Pausar» desde su "
                               "ventana")
            diario(f"{nombre}: su ventana pide pausarla; no se sincroniza hasta «Reanudar»")
        elif que == equipo.PIDE_ATENDER:
            con = self.conexiones.get(uid)
            if con is None:
                diario(f"atender {uid[:8]}: no está conectada; se atiende enchufada")
            elif uid in self.ajustes.unidades and not con.cambiada:
                diario(f"atender {con.nombre}: ya estaba en la lista")
            else:
                if con.hijo is not None and con.hijo.poll() is None:
                    con.hijo.terminate()
                con.pregunta, con.hijo = None, None
                self._atender(con)
        elif que == equipo.PIDE_MODO:
            # Una que no está en la lista entra con ese modo: es lo que hace el
            # asistente vuelto a pasar con el agente ya instalado, que añade
            # las unidades elegidas en su paso «Unidades».
            modo = p.get("modo")
            if not uid.strip() or modo not in equipo.MODOS:
                diario(f"modo {modo!r} para {uid[:8]!r}: no es un id o no es un modo")
                return
            nombre = p.get("nombre") if isinstance(p.get("nombre"), str) else ""
            unidad = self.ajustes.unidades.get(uid) or equipo.Unidad(uid, modo, nombre)
            unidad = replace(unidad, modo=modo, nombre=unidad.nombre or nombre)
            con = self.conexiones.get(uid)
            if con is not None and (uid not in self.ajustes.unidades or con.cambiada):
                # Pedido a mano con ella enchufada: es el sí, con su código de ahora.
                if con.hijo is not None and con.hijo.poll() is None:
                    con.hijo.terminate()
                con.pregunta, con.hijo, con.respuesta = None, None, None
                con.huella = huella(con.raiz)
                con.cambiada = False
                unidad = replace(unidad, codigo=con.huella or "")
            self._guardar(self.ajustes.con_unidad(unidad))
            diario(f"{unidad.nombre or nombre or uid[:8]}: modo {modo}")
        elif que == equipo.PIDE_RAIZ:
            # Lo que pide el asistente vuelto a pasar con el agente instalado:
            # la raíz que acaba de poner en este equipo.
            ruta = p.get("ruta") if isinstance(p.get("ruta"), str) else ""
            if not uid.strip() or not ruta.strip():
                diario(f"añadir raíz {uid[:8]!r} en {ruta!r}: falta el id o la ruta")
                return
            nombre = p.get("nombre") if isinstance(p.get("nombre"), str) else ""
            modo = p.get("modo") if p.get("modo") in equipo.MODOS else equipo.DAEMON
            hc = p.get("contenedor") if isinstance(p.get("contenedor"), str) else ""
            self._guardar(self.ajustes.con_unidad(
                equipo.Unidad(uid, modo, nombre, ruta.strip(), hc.strip())))
            self.ausentes.discard(uid)
            self.pedidas.add(uid)           # la acaba de dejar abierta el asistente
            diario(f"raíz de este equipo añadida: {nombre or uid[:8]} en {ruta}"
                   + (f" (cifrada, contenedor {hc})" if hc else ""))
        elif que in (equipo.PIDE_DESBLOQUEAR, equipo.PIDE_BLOQUEAR):
            unidad = self._cifrada(uid)
            if unidad is None:
                diario(f"{que} {uid[:8]!r}: no hay esa raíz cifrada en este equipo")
            elif que == equipo.PIDE_DESBLOQUEAR:
                self._desbloquear(unidad, ahora, "pedido")
            elif unidad.id not in self.bloqueos:
                self.bloqueos[unidad.id] = Bloqueo(ahora)
                self.urgentes = [u for u in self.urgentes if u[0] != unidad.id]
        elif que == equipo.PIDE_ABRIR:
            self._abrir(uid, ahora)
        elif que == equipo.PIDE_EXPLORAR:
            self._abrir(uid, ahora, explorador=True)
        elif que == equipo.PIDE_DESPERTAR:
            # Vuelta de la suspensión: la batería y la red pueden ser otras y
            # un remoto «sin conexión» quizá ya contesta. Se mira todo ya.
            self.entorno_leido = -math.inf
            self.entorno = pl.sondear_ya(self.entorno, ahora)
            self.rafaga_hasta = max(self.rafaga_hasta, ahora + RAFAGA)
            # Windows manda dos eventos de reanudación seguidos (visto en real,
            # a 1 s): repetir lo de arriba no hace daño; el diario sí.
            if ahora - self.despertado >= DESPERTAR_DOBLE:
                diario("el equipo vuelve de la suspensión")
            self.despertado = ahora
        elif que == equipo.PIDE_SONDEAR:
            # «Probar ahora» en un aviso de «Sin conexión»: la sonda de cada
            # remoto sin conexión, ya, en vez de a su hora.
            self.entorno = pl.sondear_ya(self.entorno, ahora)
            diario("se prueban ya los remotos sin conexión")
        elif que == equipo.PIDE_CAMBIO_DE_RED:
            # El sistema dice que vuelve a haber red (`common/red.py`). No se
            # sondea ya: se agrupa la ráfaga y va una sonda por remoto cuando
            # se calma (`_cambios_de_red`).
            self.cambio_de_red = pl.cambia_la_red(self.cambio_de_red, ahora)
        elif que == equipo.PIDE_AJUSTE:
            clave, valor = p.get("clave"), p.get("valor")
            if clave not in equipo.AJUSTES_PEDIBLES:
                diario(f"ajuste desconocido: {clave!r}")
                return
            crudo = equipo.a_dict(self.ajustes)
            crudo[clave] = valor
            self._guardar(equipo.desde_dict(crudo))
            diario(f"ajuste {clave} = {getattr(self.ajustes, clave)}")
        elif que == equipo.PIDE_PASADA:
            con = self.conexiones.get(uid)
            if con is None or con.servicio is None:
                diario(f"pasada de {uid[:8]}: no está conectada o no tiene servicio")
                return
            pedidas = p.get("parejas") if isinstance(p.get("parejas"), list) else []
            nombres = [x.nombre for x in con.servicio.parejas
                       if not pedidas or x.nombre in pedidas]
            self.urgentes += [(uid, n) for n in nombres if (uid, n) not in self.urgentes]
        elif que == equipo.PIDE_ACTUALIZAR:
            self._actualizar()
        elif que == equipo.PIDE_PAUSA:
            self.pausado = True
        elif que == equipo.PIDE_SIGUE:
            self.pausado = False
        elif que == equipo.PIDE_PARAR:
            cuando = p.get("cuando")
            if isinstance(cuando, (int, float)) and cuando < self.inicio:
                # Se lo pidieron al agente anterior, que se fue sin leerlo (el
                # instalador lo terminó a la fuerza): no va con este.
                diario("un «parar» de antes de arrancar: no es para este agente")
                return
            self.terminar = True
            diario("parada pedida: termina en cuanto acabe lo que esté en marcha")

    def _abrir(self, uid: str, ahora: float, explorador: bool = False) -> None:
        """Hace el «Configurar» de la bandeja (la ventana de una raíz) o su «Abrir en explorador».

        Una unidad que no está en la lista no: sería ejecutar su código sin el
        sí, y tampoco se abre su carpeta (la misma regla, sin excepciones). Una
        raíz cifrada bloqueada se desbloquea antes, y su ventana o su carpeta
        salen al verla abierta.

        Args:
            uid: El id de la raíz.
            ahora: La hora del reloj del agente.
            explorador: Abrirla en el explorador de archivos en vez de su
                ventana.
        """
        que = "abrir en el explorador" if explorador else "abrir"
        unidad = self.ajustes.unidades.get(uid)
        con = self.conexiones.get(uid)
        if unidad is None or (con is not None and (con.cambiada or con.vieja is not None)):
            diario(f"{que} {uid[:8]!r}: no está en la lista, o su código ha cambiado; "
                   f"no se ejecuta nada suyo")
        elif con is not None:
            if explorador:
                self._explorar(con)
            else:
                self._lanzar_ventana(con)
        elif unidad.cifrada and uid not in self.ausentes:
            self._desbloquear(unidad, ahora, "para abrirla en el explorador" if explorador
                              else "para abrirla", abrir=not explorador, explorar=explorador)
        else:
            diario(f"{que} {unidad.nombre or uid[:8]}: no está aquí ahora")

    def _explorar(self, con: Conexion) -> None:
        """Abre esa raíz en el explorador de archivos (`explorar()`)."""
        if not hay_pantalla():
            diario(f"{con.nombre}: sin entorno gráfico; no hay dónde abrir su carpeta")
            return
        try:
            if explorar(con.raiz):
                diario(f"{con.nombre}: abierta en el explorador de archivos")
            else:
                diario(f"{con.nombre}: no hay con qué abrir su carpeta en este equipo "
                       f"(falta xdg-open)")
        except OSError as e:
            diario(f"{con.nombre}: no he podido abrir su carpeta: {e}")

    def _emblema(self, con: Conexion) -> dict:
        """Devuelve el icono de esa raíz para la bandeja (`volumen.emblema()`).

        Solo de una raíz de la lista, con su código aceptado y de una versión
        válida: de las demás no se lee nada más que su id y su nombre, y llevan
        la marca de prdrive (`{}`). Se lee su `autorun.inf` donde lo pone
        «Nombre e icono…»: en la raíz física de una unidad en un contenedor, en
        la carpeta del contenedor de una raíz cifrada del equipo y, si no, en
        la propia raíz. Como mucho una vez cada `MIRAR_EMBLEMA`.
        """
        unidad = self.ajustes.unidades.get(con.id)
        if unidad is None or con.cambiada or con.vieja is not None:
            return {}
        ahora = self.reloj()
        if con.emblema is None or ahora - con.emblema_leido >= MIRAR_EMBLEMA:
            if unidad.cifrada:
                donde = Path(unidad.contenedor).parent
            else:
                donde = con.fisica or con.raiz
            con.emblema = volumen.emblema(donde, APP_SUBDIR)
            con.emblema_leido = ahora
        return con.emblema

    def _estado_raiz(self, uid: str, unidad: equipo.Unidad) -> str:
        """Devuelve en qué está una raíz de este equipo, para la bandeja."""
        if uid in self.ausentes:
            return bandeja.AUSENTE
        if uid in self.fantasmas:
            return bandeja.FANTASMA
        if uid in self.bloqueos:
            return bandeja.BLOQUEANDO
        if uid in self.conexiones:
            return bandeja.ABIERTA
        if uid in self.desbloqueos:
            return bandeja.DESBLOQUEANDO
        return bandeja.BLOQUEADA if unidad.cifrada else bandeja.BUSCANDO

    def _vigilancia(self, con: Conexion) -> tuple[list[str], list[str]]:
        """Devuelve las parejas de una raíz que se vigilan y las que se abandonaron.

        Solo cuentan las del servicio del agente en modo `daemon` (en `sync` no
        hay intervalo que adelantar). Las abandonadas son las que pasaron del
        tope de entradas o cuya carpeta cae fuera de la raíz: siguen por su
        intervalo.
        """
        unidad = self.ajustes.unidades.get(con.id)
        if con.lock is None or con.servicio is None or unidad is None \
                or unidad.modo != equipo.DAEMON:
            return [], []
        pedidas = [p.nombre for p in con.servicio.parejas if p.vigila]
        dejadas = [n for n in pedidas
                   if self.vigiladas.get((con.id, n), pl.Vigilada()).abandonada]
        return sorted(set(pedidas) - set(dejadas)), sorted(dejadas)

    def resumen(self) -> dict:
        """Devuelve lo que el agente cuenta de sí mismo.

        Es lo que va a `estado.json` y lo que la bandeja convierte en su vista
        (`bandeja.vista()`).
        """
        unidades = []
        for con in self.conexiones.values():
            unidad = self.ajustes.unidades.get(con.id)
            vigila, abandonadas = self._vigilancia(con)
            unidades.append({"id": con.id, "nombre": con.nombre, "raiz": str(con.raiz),
                             "del_equipo": bool(unidad and unidad.es_raiz),
                             "cifrada": bool(unidad and unidad.cifrada),
                             "modo": unidad.modo if unidad else None,
                             "atendida": con.lock is not None,
                             "motivo": con.motivo,
                             "en_lista": unidad is not None and not con.cambiada
                             and con.vieja is None,
                             "cambiada": con.cambiada,
                             "vieja": con.vieja,
                             "ahora_no": con.respuesta == pl.AHORA_NO,
                             "preguntando": con.pregunta is not None,
                             "error": con.error,
                             "pausada": bool(unidad and unidad.pausada),
                             "fallando": sorted(p for (r, p), m in self.marcas.items()
                                                if r == con.id and m.fallos > 0),
                             "vigila": vigila,
                             "vigila_abandonada": abandonadas,
                             "emblema": self._emblema(con)})
        cerradas = [u.nombre or u.id[:8] for u in self.ajustes.cifradas.values()
                    if u.id not in self.conexiones and u.id not in self.ausentes]
        return {"pid": os.getpid(), "pausado": self.pausado, "retenido": self.retenido,
                "pasada": None if self.pasada is None else {
                    "unidad": self.pasada.nombre, "pareja": self.pasada.tarea.pareja,
                    "tipo": self.pasada.tarea.tipo},
                "sin_conexion": sorted(f"{self.conexiones[r].nombre}: {m}"
                                       for r, m in self.entorno.sin_conexion
                                       if r in self.conexiones),
                "cambios_de_red": self.avisos_de_red.fuente
                if self.avisa_la_red() else "",
                "unidades": unidades,
                "ausentes": sorted((self.ajustes.unidades[u].contenedor
                                    or self.ajustes.unidades[u].ruta)
                                   for u in self.ausentes if u in self.ajustes.unidades),
                "bloqueadas": sorted(cerradas),
                "desbloqueando": sorted(self.ajustes.unidades[u].nombre or u[:8]
                                        for u in self.desbloqueos
                                        if u in self.ajustes.unidades),
                "bloqueando": sorted(self.ajustes.unidades[u].nombre or u[:8]
                                     for u in self.bloqueos if u in self.ajustes.unidades),
                "fantasmas": sorted(self.ajustes.unidades[u].ruta for u in self.fantasmas
                                    if u in self.ajustes.unidades),
                # Las raíces de este equipo, con su estado: lo que pinta la bandeja.
                "equipo": [{"id": uid, "nombre": u.nombre or APP_NAME, "ruta": u.ruta,
                            "cifrada": u.cifrada, "estado": self._estado_raiz(uid, u)}
                           for uid, u in self.ajustes.raices.items()],
                "pedir_al_iniciar": self.ajustes.pedir_al_iniciar,
                "ultima_pasada": self.ultima_buena,
                "version": self.version, "nueva": self.nueva,
                "actualizando": self.actualizando is not None
                and self.actualizando.poll() is None}

    def _escribir_estado(self) -> None:
        """Escribe `estado.json` y le pasa la vista a la bandeja, si cambian."""
        resumen = self.resumen()
        if resumen != self.ultimo_estado:
            self.ultimo_estado = resumen
            store.write_json(equipo.estado_json(), {**resumen, "actualizado": store.stamp()})
        if self.bandeja is not None:
            # Se compara la vista y no el resumen: el texto del ratón dice
            # «sincronizado hace N min», que cambia sin que cambie nada más.
            try:
                vista = bandeja.vista(resumen, self.reloj())
                if vista != self.ultima_vista:
                    self.ultima_vista = vista
                    self.bandeja.poner(vista)
            except Exception as e:                  # noqa: BLE001
                diario(f"la bandeja no se ha podido poner al día: {e}")

    def cerrar(self) -> None:
        """Se despide: suelta los locks que sean nuestros.

        Una pasada en marcha sigue sola hasta acabar; nadie la mata desde aquí.
        """
        for con in self.conexiones.values():
            if presente(con.raiz):
                self._soltar(con)
        store.write_json(equipo.estado_json(), {"pid": None, "actualizado": store.stamp()})


MOUNTINFO = Path("/proc/self/mountinfo")
"""Tabla de montajes de Linux, que avisa con `POLLPRI` cuando cambia."""


class Vigia:
    """Espera el tic, o menos si cambian los montajes o alguien lo despierta.

    En Linux, `/proc/self/mountinfo` avisa con `POLLPRI` (y `POLLERR`) cuando
    cambia la tabla de montajes; hay que releerlo entero para rearmar el aviso.
    En Windows los montajes los dice la bandeja (`WM_DEVICECHANGE`), desde su
    hilo, con `despertar(montajes=True)`; y lo que se elige en su menú, con
    `despertar()`, para no esperar al tic. En Linux ese despertar va por un
    pipe que se vigila junto a mountinfo.
    """

    def __init__(self) -> None:
        """Prepara la espera.

        En Linux, mountinfo y el pipe; en Windows, solo el evento.
        """
        self._f = None
        self._poll = None
        self._evento = threading.Event()
        self._montajes = False
        self._pipe: tuple[int, int] | None = None
        if IS_WIN:
            return
        try:
            import select
            self._poll = select.poll()
            self._pipe = os.pipe()
            os.set_blocking(self._pipe[1], False)
            self._poll.register(self._pipe[0], select.POLLIN)
            self._f = MOUNTINFO.open("rb")
            self._f.read()
            self._poll.register(self._f.fileno(), select.POLLPRI | select.POLLERR)
        except (OSError, AttributeError, ImportError):
            if self._f is not None:
                self._f.close()
            self._f = None
            if self._pipe is None:
                self._poll = None

    def despertar(self, montajes: bool = False) -> None:
        """Hace que la espera acabe ya; se puede llamar desde cualquier hilo.

        Args:
            montajes: Avisa además de que han cambiado los montajes.
        """
        if montajes:
            self._montajes = True
        self._evento.set()
        if self._pipe is not None:
            try:
                os.write(self._pipe[1], b"!")
            except OSError:
                pass                # lleno: ya hay un despertar pendiente

    def _tomar_montajes(self) -> bool:
        """Devuelve si hubo aviso de montajes, y lo olvida."""
        montajes, self._montajes = self._montajes, False
        self._evento.clear()
        return montajes

    def esperar(self, segundos: float) -> bool:
        """Espera hasta `segundos`, o hasta que lo despierten o cambien los montajes.

        Returns:
            `True` si han cambiado los montajes (hay que recorrer en racha).
        """
        if self._poll is None:
            self._evento.wait(segundos)
            return self._tomar_montajes()
        montajes = False
        try:
            for fd, _ in self._poll.poll(int(segundos * 1000)):
                if self._pipe is not None and fd == self._pipe[0]:
                    os.read(fd, 4096)
                elif self._f is not None:
                    self._f.seek(0)
                    self._f.read()
                    montajes = True
        except OSError:
            time.sleep(segundos)
        return self._tomar_montajes() or montajes


def poner_bandeja(agente: Agente, vigia: Vigia) -> Any:
    """Devuelve la bandeja del agente, o `None` si no se ha podido poner.

    Punto de indirección: los tests no ponen ninguna.

    Windows (fase 4): `Shell_NotifyIconW`. Linux (fase 6): StatusNotifierItem
    en el bus de sesión; sin nadie que haga de `StatusNotifierWatcher`, la
    bandeja existe pero sin icono (`puesta` False), se dice en el diario y el
    icono se pone solo si el watcher aparece después. Mientras, el acceso
    «prdrive» del menú hace sus veces.
    """

    def pedir(peticion: dict) -> None:
        """Pasa al agente una petición de la bandeja y lo despierta."""
        agente.pedir(peticion)
        vigia.despertar()

    if not IS_WIN:
        from ui import bandeja_linux
        b = bandeja_linux.Bandeja(pedir)
        if not b.arrancar():
            diario("sin bus de sesión: sigo sin bandeja (el acceso del menú hace sus "
                   "veces)")
            return None
        if not b.puesta:
            diario(f"este escritorio no tiene bandeja (nadie es {bandeja_linux.WATCHER}): "
                   f"el acceso «{APP_NAME}» del menú hace sus veces; si aparece una, el "
                   f"icono se pone solo")
        return b
    from ui import bandeja_windows, icons
    try:
        icons.write_bandeja(SCRIPT_DIR, solo_si_faltan=True)
    except Exception as e:                              # noqa: BLE001
        diario(f"no he podido pintar los iconos de la bandeja: {e}")

    b = bandeja_windows.Bandeja(SCRIPT_DIR, pedir, lambda: vigia.despertar(montajes=True))
    if not b.arrancar():
        diario("no he podido poner la bandeja: sigo sin ella")
        return None
    return b


def poner_red(agente: Agente, vigia: Vigia) -> Any:
    """Devuelve lo que oye los cambios de red, o `None` si no se oye ninguno.

    Punto de indirección: los tests no ponen ninguno.

    Es `common/red.py`, independiente de la bandeja: el agente sin icono también
    se entera. Cada aviso es un `equipo.PIDE_CAMBIO_DE_RED` en la cola del
    agente, que lo despierta. Sin avisos, un remoto sin conexión se sigue
    sondeando cada `Politica.sondeo_sin_conexion`.
    """
    from common import red

    def avisar() -> None:
        """Pasa al agente el aviso de que vuelve a haber red y lo despierta."""
        agente.pedir({"pide": equipo.PIDE_CAMBIO_DE_RED})
        vigia.despertar()

    avisos_de_red = red.AvisosDeRed(avisar)
    respaldo = pl.sondeo(agente.ajustes.politica, True) / 60
    sin_avisos = pl.sondeo(agente.ajustes.politica, False) / 60
    if not avisos_de_red.arrancar():
        avisos_de_red.cerrar()
        diario(f"no oigo los cambios de red: un remoto sin conexión se prueba cada "
               f"{sin_avisos:g} min")
        return None
    if avisos_de_red.activa:
        diario(f"oigo los cambios de red ({avisos_de_red.fuente}): un remoto sin "
               f"conexión se prueba cuando vuelve la red, y si no, cada {respaldo:g} min")
    else:
        diario(f"todavía no oigo los cambios de red (sin NetworkManager): un remoto sin "
               f"conexión se prueba cada {sin_avisos:g} min")
    return avisos_de_red


def _enganchar_penwatch() -> None:
    """Lleva a penwatch al diario del agente.

    Lo que penwatch escribe en su diario va al del agente: el agente lo
    sustituye en este equipo y su carpeta ya no existe.
    """
    penwatch.HOST_DIR = equipo.DIR
    penwatch.LOG_FILE = equipo.diario_log()


def _terminar_con_finally(*_args) -> None:
    """Hace de SIGTERM una salida normal.

    Cerrar sesión, `systemctl stop` o `timeout` mandan SIGTERM: sin esto Python
    muere sin pasar por los `finally` y el lock de la unidad se queda escrito
    con un pid muerto.
    """
    raise SystemExit(0)


def cmd_run(_args: argparse.Namespace) -> int:
    """Es el bucle del agente: recorre, vuelve a vuelta y espera al tic.

    Returns:
        0 al terminar; 1 si no puede usar su carpeta.
    """
    _enganchar_penwatch()
    if not IS_WIN:
        import signal
        signal.signal(signal.SIGTERM, _terminar_con_finally)
        signal.signal(signal.SIGHUP, _terminar_con_finally)
    try:
        equipo.DIR.mkdir(parents=True, exist_ok=True)
        os.chdir(equipo.DIR)            # nunca dentro de una unidad
    except OSError as e:
        print(f"No puedo usar {equipo.DIR}: {e}", file=sys.stderr)
        return 1
    # Tomar el lock es mirar y escribir en un paso (`equipo.tomar_lock()`): dos
    # arranques a la vez no pueden ver los dos que no hay nadie.
    otro = equipo.tomar_lock({"pid": os.getpid(), "host": HOST, "started": store.stamp(),
                              "codigo": str(SCRIPT_DIR)})
    if otro is not None:
        print(f"Ya hay un agente en marcha (pid {otro.get('pid', '?')}).")
        return 0
    icono = SCRIPT_DIR / "runsync.ico"
    if icono.is_file():
        avisos.ICONO = icono
    agente = Agente()
    diario(f"agente iniciado (pid {os.getpid()}, {len(agente.ajustes.unidades)} "
           f"unidades en la lista)")
    vigia = Vigia()
    agente.bandeja = poner_bandeja(agente, vigia)
    agente.avisos_de_red = poner_red(agente, vigia)
    # Sin quien avise de los montajes (Windows sin bandeja) se recorre como
    # penwatch; con él, el recorrido de respaldo y las rachas tras cada aviso.
    cada = RECORRIDO_WINDOWS if IS_WIN and agente.bandeja is None else RECORRIDO_RESPALDO
    proximo = -math.inf
    try:
        while not (agente.terminar and agente.pasada is None):
            ahora = time.time()
            recorrer = ahora >= proximo or ahora < agente.rafaga_hasta
            if recorrer:
                proximo = ahora + cada
            try:
                agente.vuelta(recorrer)
            except Exception as e:                      # noqa: BLE001
                # Un fallo de una vuelta no puede tumbar al agente de todas las
                # unidades: se apunta y se sigue en la siguiente.
                diario(f"error en una vuelta: {type(e).__name__}: {e}")
            if vigia.esperar(TICK):
                agente.rafaga_hasta = time.time() + RAFAGA
    except KeyboardInterrupt:
        diario("interrumpido por teclado")
    finally:
        agente.cerrar()
        if agente.avisos_de_red is not None:
            agente.avisos_de_red.cerrar()
        if agente.bandeja is not None:
            agente.bandeja.cerrar()
        info = store.read_json(equipo.lock_json())
        if info.get("pid") == os.getpid() and info.get("host") == HOST:
            equipo.lock_json().unlink(missing_ok=True)
        diario("agente detenido")
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    """Imprime qué atiende el agente y cómo."""
    aj = equipo.leer_ajustes()
    vivo = equipo.agente_vivo()
    print(f"Agente:         {'vivo (pid ' + str(vivo.get('pid')) + ')' if vivo else 'parado'}")
    print(f"En el equipo:   {equipo.DIR}")
    nueva = update.pending(SCRIPT_DIR, cache=cache_version())
    print(f"Versión:        {update.installed_version(SCRIPT_DIR) or 'desconocida'}"
          + (f" (hay una nueva, {nueva.tag}: agente.py actualizar)" if nueva else ""))
    print(f"Unidad nueva:   se pregunta y se espera {aj.espera_unidad_nueva:g} s")
    pausa = " · en pausa desde su ventana («Reanudar» para volver)"
    for u in aj.raices.values():
        print(f"Raíz del equipo: {u.nombre or '(sin nombre)'} en {u.ruta} ({u.modo}: "
              f"{equipo.TEXTO_MODO[u.modo]})" + (pausa if u.pausada else ""))
        if u.cifrada:
            print(f"  cifrada: {u.contenedor}; al iniciar sesión "
                  + ("se pide la contraseña" if aj.pedir_al_iniciar
                     else "no se pide nada (agente.py desbloquear)"))
    unidades = [u for u in aj.unidades.values() if not u.es_raiz]
    print("Unidades en la lista:" if unidades else "Unidades en la lista: ninguna")
    for u in unidades:
        print(f"  {u.nombre or '(sin nombre)':<20} {u.id[:12]}…  {u.modo}: "
              f"{equipo.TEXTO_MODO[u.modo]}" + (pausa if u.pausada else ""))
    estado = equipo.leer_estado() if vivo else {}
    if estado.get("retenido"):
        print(f"No se lanza nada: {estado['retenido']}")
    if estado.get("pausado"):
        print("En pausa (agente.py sigue para volver).")
    if estado.get("pasada"):
        p = estado["pasada"]
        print(f"Ahora: {p.get('unidad')} · {p.get('pareja') or 'comprobando la conexión'}")
    for u in estado.get("unidades") or []:
        print(f"{'Raíz' if u.get('del_equipo') else 'Conectada'}: {u.get('nombre')} "
              f"en {u.get('raiz')}"
              + (f" — {u['motivo']}" if u.get("motivo") else " — atendida"))
        if u.get("vigila"):
            print(f"  Sincroniza al cambiar sus ficheros: {', '.join(u['vigila'])}")
        if u.get("vigila_abandonada"):
            print(f"  No vigila sus cambios (demasiado grande o fuera de la raíz; "
                  f"sigue por su intervalo): {', '.join(u['vigila_abandonada'])}")
    for ruta in estado.get("ausentes") or []:
        print(f"Falta la raíz del equipo: no está en {ruta}")
    for nombre in estado.get("bloqueadas") or []:
        print(f"Bloqueada: {nombre} (agente.py desbloquear)")
    for nombre in estado.get("desbloqueando") or []:
        print(f"Desbloqueando: {nombre}; la contraseña la pide VeraCrypt")
    for nombre in estado.get("bloqueando") or []:
        print(f"Bloqueando: {nombre}")
    for ruta in estado.get("fantasmas") or []:
        print(f"Volumen fantasma en {ruta}: bloquéala y vuelve a desbloquearla")
    for linea in estado.get("sin_conexion") or []:
        print(f"Sin conexión: {linea}")
    if vivo:
        oye = estado.get("cambios_de_red")
        if oye:
            print(f"Cambios de red: los oye ({oye}); un remoto sin conexión se prueba "
                  f"cuando vuelve la red, y si no, cada "
                  f"{pl.sondeo(aj.politica, True) / 60:g} min")
        else:
            print(f"Cambios de red: no los oye; un remoto sin conexión se prueba cada "
                  f"{pl.sondeo(aj.politica, False) / 60:g} min")
    return 0


def _pedir(peticion: dict) -> int:
    """Deja una petición en el buzón del agente y dice cuándo se atenderá.

    Returns:
        0 si se dejó; 1 si no se pudo.
    """
    if not equipo.pedir(peticion):
        print(f"No he podido dejar la petición en {equipo.buzon()}.", file=sys.stderr)
        return 1
    if equipo.agente_vivo() is None:
        print("Petición apuntada, pero el agente no está en marcha: la atenderá al "
              "arrancar.")
    else:
        print("Petición apuntada; el agente la atiende en unos segundos.")
    return 0


def cmd_parar(_args: argparse.Namespace) -> int:
    """Pide parar al agente y espera un rato a que se vaya."""
    vivo = equipo.agente_vivo()
    if vivo is None:
        print("El agente no está en marcha.")
        return 0
    equipo.pedir({"pide": equipo.PIDE_PARAR})
    limite = time.monotonic() + PARAR_ESPERA
    while time.monotonic() < limite and equipo.agente_vivo() is not None:
        time.sleep(0.3)
    print("Agente detenido." if equipo.agente_vivo() is None else
          "El agente sigue terminando una pasada; parará al acabarla.")
    return 0


def raiz_para_abrir(uid: str | None) -> tuple[Path | None, str]:
    """Devuelve qué raíz abre `agente.py abrir`, y por qué no hay ninguna.

    Es la de ese id (del equipo, o una unidad conectada según el estado del
    agente) o la única raíz del equipo.

    Returns:
        `(raíz, motivo)`; el motivo va vacío cuando hay raíz.
    """
    aj = equipo.leer_ajustes()
    if uid:
        unidad = aj.unidades.get(uid)
        if unidad is not None and unidad.es_raiz:
            return Path(unidad.ruta), ""
        for u in equipo.leer_estado().get("unidades") or []:
            if u.get("id") == uid and u.get("raiz"):
                return Path(u["raiz"]), ""
        return None, f"No conozco ninguna raíz conectada con el id {uid}."
    raices = list(aj.raices.values())
    if not raices:
        return None, ("Este equipo no tiene raíz propia: las unidades se abren desde "
                      "ellas.")
    if len(raices) > 1:
        return None, ("Hay más de una raíz en este equipo; di cuál: "
                      + ", ".join(f"{u.id} ({u.ruta})" for u in raices))
    return Path(raices[0].ruta), ""


def arrancar_agente() -> bool:
    """Arranca el agente desde `abrir` cuando no está en marcha.

    Se cerró con «Cerrar el agente» o la sesión no lo arrancó. Va suelto y
    fuera de toda raíz.
    """
    try:
        lanzar([python(), str(SCRIPT_DIR / "agente.py"), "run"],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
               **_opciones_hijo(equipo.DIR, separado=True))
    except OSError as e:
        print(f"No he podido arrancar el agente: {e}", file=sys.stderr)
        return False
    return True


def cmd_abrir(args: argparse.Namespace) -> int:
    """Hace el acceso «prdrive» del menú del sistema, que sin bandeja hace sus veces.

    Es la fase 6:
    - Con el agente parado, lo arranca.
    - Con una raíz en este equipo, abre su ventana de runsync, con el Python
      del agente y el directorio de trabajo fuera de ella (la raíz del equipo
      no lleva Python propio); bloqueada, pide antes desbloquearla.
    - Sin raíz («solo agente»), dice con un aviso cómo va el agente.
    """
    _enganchar_penwatch()
    vivo = equipo.agente_vivo() is not None
    arrancado = False if vivo else arrancar_agente()
    raiz, porque = raiz_para_abrir(args.id)
    if raiz is None:
        if args.id or equipo.leer_ajustes().raices:
            print(porque, file=sys.stderr)
            return 1
        if not vivo:
            if not arrancado:
                return 1
            print("Agente arrancado.")
            avisar(f"{APP_NAME}: agente arrancado",
                   "Atiende las unidades de su lista en cuanto se enchufen.")
            return 0
        titulo, texto = bandeja.aviso_de_estado(equipo.leer_estado())
        print(f"{titulo}\n{texto}")
        avisar(titulo, texto)
        return 0
    if not presente(raiz):
        unidad = equipo.leer_ajustes().unidades.get(args.id or "") \
            or next((u for u in equipo.leer_ajustes().raices.values()
                     if Path(u.ruta) == raiz), None)
        if unidad is None or not unidad.cifrada:
            print(f"No encuentro {APP_NAME} en {raiz}.", file=sys.stderr)
            return 1
        # Cerrada: se le pide al agente que la desbloquee (la contraseña la
        # pide VeraCrypt) y se abre la ventana en cuanto aparezca. Es lo que
        # hace el acceso «prdrive» del menú con la raíz bloqueada.
        if not (vivo or arrancado):
            print(f"{raiz} está bloqueada y el agente no está en marcha: no hay quien "
                  f"la desbloquee.", file=sys.stderr)
            return 1
        equipo.pedir({"pide": equipo.PIDE_DESBLOQUEAR, "id": unidad.id})
        print(f"{raiz} está bloqueada: VeraCrypt pedirá la contraseña.")
        limite = time.monotonic() + ESPERA_ABRIR
        while not presente(raiz):
            if time.monotonic() >= limite:
                print("No se ha desbloqueado a tiempo; vuelve a intentarlo.",
                      file=sys.stderr)
                return 1
            time.sleep(1.0)
    # El servicio no estorba (lo pausa la propia ventana al abrirse); otra
    # ventana sí, y runsync ya se negaría: se dice aquí, sin lanzar nada.
    ventana = penwatch._vivo_aqui(raiz, penwatch.UI_LOCK_REL)
    if ventana is not None:
        print(f"La ventana de {raiz} ya está abierta (pid {ventana.get('pid')}).")
        return 0
    try:
        lanzar([python(ventana=True), str(app(raiz) / "runsync.py")],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
               **_opciones_hijo(equipo.DIR, separado=True))
    except OSError as e:
        print(f"No he podido abrir la ventana: {e}", file=sys.stderr)
        return 1
    return 0


VERDAD = {"si": True, "sí": True, "s": True, "true": True, "1": True, "yes": True,
          "no": False, "n": False, "false": False, "0": False}
"""Cómo se escribe un sí o un no en la línea de órdenes."""


def valor_ajuste(clave: str, texto: str) -> Any:
    """Devuelve el valor de un ajuste escrito en la línea de órdenes, con su tipo.

    Un texto donde va un sí o un no volvería al valor de fábrica al leerlo, sin
    decir nada: por eso se rechaza aquí.

    Raises:
        ValueError: Si no es un sí o un no, o un número.
    """
    if clave == "pedir_al_iniciar":
        valor = VERDAD.get(texto.strip().lower())
        if valor is None:
            raise ValueError(f"{clave} es sí o no, no {texto!r}")
        return valor
    return float(texto)


def cmd_ajuste(args: argparse.Namespace) -> int:
    """Pide cambiar un ajuste del agente."""
    try:
        valor = valor_ajuste(args.clave, args.valor)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    return _pedir({"pide": equipo.PIDE_AJUSTE, "clave": args.clave, "valor": valor})


def cmd_actualizar(_args: argparse.Namespace) -> int:
    """Hace el «Actualizar» de la bandeja (o a mano).

    Baja el código de la última release, lo comprueba (`update.download()`) y
    ejecuta SU instalador con `--update-agente`, que pone el agente nuevo al
    lado, para a este, vuelve a registrarlo, pone al día las raíces abiertas y
    arranca el nuevo. Lo que dice va al diario del agente. Nunca se descarga
    dentro de ninguna raíz.
    """
    _enganchar_penwatch()

    def decir(msg: str) -> None:
        """Dice un mensaje por pantalla y en el diario."""
        print(msg)
        diario(f"actualizar: {msg}")

    rel, motivo = update.check(force=True, cache=cache_version())
    actual = update.installed_version(SCRIPT_DIR)
    if rel is None:
        decir(motivo or "no sé qué versión es la última")
        return 1
    if not update.is_newer(rel.version, actual):
        decir(f"ya está en la última versión ({actual or rel.version})")
        return 0
    trabajo = Path(tempfile.mkdtemp(prefix=f"{APP_NAME}-agente-"))
    try:
        try:
            update.download(rel.tag, trabajo / "codigo", progreso=decir)
        except update.UpdateError as e:
            decir(str(e))
            avisar(f"{APP_NAME}: no he podido actualizar", str(e).splitlines()[0], True)
            return 1
        kwargs = _opciones_hijo(equipo.DIR)
        proc = ejecutar(update.agent_command(trabajo / "codigo", sys.executable),
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", **kwargs)
        for linea in ((proc.stdout or "") + (proc.stderr or "")).splitlines():
            if linea.strip():
                decir(linea.rstrip())
        if proc.returncode != 0:
            avisar(f"{APP_NAME}: no he podido actualizar",
                   f"Lo que ha pasado está en {equipo.diario_log()}.", True)
            return proc.returncode
        avisar(f"{APP_NAME} actualizado a la {rel.tag}",
               "El agente se ha reiniciado con la versión nueva.")
        return 0
    finally:
        shutil.rmtree(trabajo, ignore_errors=True)


def cmd_pregunta(args: argparse.Namespace) -> int:
    """Abre la ventanita que pregunta por una unidad nueva (proceso hijo del agente)."""
    from ui import tk_agente
    return tk_agente.main(args.nombre, args.segundos, args.cambiada)


def main(argv: list[str] | None = None) -> int:
    """Atiende la línea de comandos del agente."""
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    ap = argparse.ArgumentParser(prog="agente.py",
                                 description=f"{APP_NAME} residente: atiende las "
                                             f"unidades que se enchufan en este equipo.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="El bucle del agente.").set_defaults(func=cmd_run)
    sub.add_parser("status", help="Qué atiende y cómo.").set_defaults(func=cmd_status)
    p = sub.add_parser("atender", help="Atender una unidad conectada.")
    p.add_argument("id")
    p.set_defaults(func=lambda a: _pedir({"pide": equipo.PIDE_ATENDER, "id": a.id}))
    p = sub.add_parser("modo", help="Qué hacer con una unidad al enchufarla.")
    p.add_argument("id")
    p.add_argument("modo", choices=equipo.MODOS)
    p.set_defaults(func=lambda a: _pedir({"pide": equipo.PIDE_MODO, "id": a.id,
                                          "modo": a.modo}))
    p = sub.add_parser("pasada", help="Sincronizar ahora, sin moderación.")
    p.add_argument("id")
    p.add_argument("parejas", nargs="*")
    p.set_defaults(func=lambda a: _pedir({"pide": equipo.PIDE_PASADA, "id": a.id,
                                          "parejas": a.parejas}))
    sub.add_parser("pausa", help="Dejar de lanzar pasadas.").set_defaults(
        func=lambda a: _pedir({"pide": equipo.PIDE_PAUSA}))
    sub.add_parser("sigue", help="Volver a lanzarlas.").set_defaults(
        func=lambda a: _pedir({"pide": equipo.PIDE_SIGUE}))
    sub.add_parser("parar", help="Que el agente termine.").set_defaults(func=cmd_parar)
    p = sub.add_parser("abrir", help="La ventana de la raíz de este equipo.")
    p.add_argument("id", nargs="?")
    p.set_defaults(func=cmd_abrir)
    p = sub.add_parser("desbloquear", help="Abrir el contenedor de la raíz cifrada.")
    p.add_argument("id", nargs="?", default="")
    p.set_defaults(func=lambda a: _pedir({"pide": equipo.PIDE_DESBLOQUEAR, "id": a.id}))
    p = sub.add_parser("bloquear", help="Cerrarlo.")
    p.add_argument("id", nargs="?", default="")
    p.set_defaults(func=lambda a: _pedir({"pide": equipo.PIDE_BLOQUEAR, "id": a.id}))
    sub.add_parser("actualizar", help="Bajar la versión nueva y ponerla.").set_defaults(
        func=cmd_actualizar)
    p = sub.add_parser("ajuste", help="Cambiar un ajuste del agente.")
    p.add_argument("clave", choices=equipo.AJUSTES_PEDIBLES)
    p.add_argument("valor")
    p.set_defaults(func=cmd_ajuste)
    p = sub.add_parser("pregunta", help=argparse.SUPPRESS)
    p.add_argument("--nombre", required=True)
    p.add_argument("--segundos", type=int, default=int(equipo.ESPERA_UNIDAD_NUEVA))
    p.add_argument("--cambiada", action="store_true")
    p.set_defaults(func=cmd_pregunta)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
