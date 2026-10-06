#!/usr/bin/env python3
"""Los avisos del sistema de que la carpeta de una pareja vigilada ha cambiado.

Una pareja con `watch = true` se sincroniza poco después de que cambien sus
ficheros locales. Recorrerla cada pocos segundos (`common/huella.py`) cuesta lo
mismo cambie algo o no; esto le pide al sistema que avise, y en reposo no
cuesta nada. Dice SI una carpeta ha cambiado, no qué fichero: bisync necesita
su listado entero de todos modos, y agrupar la ráfaga y decidir la pasada es
cosa de `common/planificador.py` (`avisado()`).

Linux, con inotify(7) por `ctypes` (la biblioteca estándar no lo trae):
- Un descriptor para todo el agente y una vigilancia por carpeta. Ponerlas
  recorre solo las carpetas (`scandir`, sin `stat` de cada fichero), una vez
  por pareja; quien llama lo hace en un hilo: en un pendrive en frío tarda.
- Cada vigilancia pide `IN_CLOSE_WRITE | IN_ATTRIB | IN_CREATE | IN_DELETE |
  IN_MOVED_FROM | IN_MOVED_TO | IN_DELETE_SELF | IN_MOVE_SELF`, y se pone con
  `IN_ONLYDIR | IN_DONT_FOLLOW` (nunca a través de un enlace) e
  `IN_EXCL_UNLINK`. No `IN_MODIFY`: llega con cada `write()` y basta el cierre.
  El precio: un fichero que se escribe sin cerrarse nunca (el disco de una
  máquina virtual) no avisa hasta que se cierra.
- Una carpeta nueva (`IN_CREATE` con `IN_ISDIR`) recibe su vigilancia en el
  acto, con lo que ya traiga dentro; una que entra o sale moviéndose
  (`IN_MOVED_FROM`/`IN_MOVED_TO` con `IN_ISDIR`) y una cola desbordada
  (`IN_Q_OVERFLOW`, que puede haberse tragado una carpeta nueva) son
  `DESBORDADO`: cuenta como cambio y quien llama vuelve a `vigilar()`, que
  rehace lo que falte y quita lo que ya no es de la pareja.
- `IN_ATTRIB` de una carpeta no es un cambio: la foto tampoco mira las
  carpetas más que por su nombre.
- La carpeta de la pareja borrada o movida (`IN_DELETE_SELF`, `IN_MOVE_SELF`,
  `IN_IGNORED`) o su unidad desmontada (`IN_UNMOUNT`) es `PERDIDA`: la pareja
  se deja aquí y quien llama la recorre. Desmontar con vigilancias puestas
  funciona: el núcleo las quita y avisa (medido, `umount` no protesta).
- Dos parejas que se solapan (`local = "."` y `sync-data/docs`) comparten las
  vigilancias de lo común: `inotify_add_watch` sobre una carpeta ya vigilada
  por el mismo descriptor devuelve la misma. Lo que se ignora en la raíz de
  una pareja (`.prversions/`, `.prdrive/`, el ruido del sistema) se ignora
  solo para ella, y a esas carpetas ni se les pone vigilancia.
- Lo que no es local (`DE_RED`: NFS, SMB, sshfs, una carpeta compartida con
  una máquina virtual…) no se vigila con avisos: inotify ve lo que se cambia
  desde este equipo, no desde el otro lado.
- El tope es de carpetas y lo pone el sistema, `fs.inotify.max_user_watches`,
  que es POR USUARIO y compartido con sus otros programas (un editor que vigila
  su proyecto). El agente no se queda con más de `PRESUPUESTO` de él; lo que
  no cabe, o un `ENOSPC`, deja la pareja sin avisos (se recorre).

Windows, con `ReadDirectoryChangesW` (`ReadDirectoryChanges`):
- Un handle por pareja (`CreateFileW` con `FILE_LIST_DIRECTORY`, compartido para
  leer, escribir y borrar, `FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OVERLAPPED`)
  y `bWatchSubtree`: el sistema sigue solo las carpetas nuevas y las movidas,
  así que no hay nada que rehacer. Pide `FILE_NOTIFY_CHANGE_FILE_NAME |
  DIR_NAME | SIZE | LAST_WRITE`, no los accesos.
- Un hilo propio lanza TODAS las lecturas y espera sus eventos
  (`WaitForMultipleObjects`, hasta 64 con el de control: `MAX_PAREJAS_WINDOWS`);
  `vigilar()` se lo pide y espera la respuesta. Así ninguna lectura es de un
  hilo que acaba. Cada lectura se vuelve a lanzar en cuanto acaba: el búfer
  del sistema no se llena entre dos vueltas del agente, y no hay que
  despertarlo.
- Un búfer desbordado (la lectura acaba bien con 0 bytes, o con
  `ERROR_NOTIFY_ENUM_DIR`) es `DESBORDADO`; otro error de la lectura (la
  carpeta borrada, la unidad arrancada) es `PERDIDA`.
- **Ese handle abierto impediría expulsar la unidad.** Cada uno se registra con
  `RegisterDeviceNotificationW` (`DBT_DEVTYP_HANDLE`) en la ventana de la
  bandeja, que pasa los avisos a `dispositivo()`: con
  `DBT_DEVICEQUERYREMOVE` se cierra en el acto (Windows espera a que se cierre
  para contestar a quien pide la unidad) y la pareja queda callada, sin avisos
  ni recorridos; con `DBT_DEVICEQUERYREMOVEFAILED` (al final no se extrae) se
  vuelve a abrir; `DBT_DEVICEREMOVEPENDING`/`REMOVECOMPLETE` es `PERDIDA`. Sin
  ese registro no se deja ningún handle abierto (la pareja se recorre), y sin
  bandeja no hay motor (`abrir()` es `None`).
- Ni una carpeta de red (`GetDriveTypeW`, `DRIVE_REMOTE`) ni un volumen de
  VeraCrypt (`QueryDosDeviceW` de su letra, `\\Device\\VeraCryptVolume…`) se
  vigilan con avisos. Del segundo, visto con VeraCrypt 1.26.29
  (`tests/maquina/f18_veracrypt_windows.py`): Windows no deja registrar el
  aviso de extracción de un handle de su volumen (error 1066), no llega
  ningún aviso al desmontarlo, y con un handle abierto dentro no se desmonta
  sin forzar. Se dice antes de intentarlo, con su motivo.
- Todas las llamadas a Windows están en `Win32`; los tests ponen una de
  mentira. Lo que solo se ve en un Windows de verdad está en la lista de
  pruebas en equipos reales.

Nada de esto lanza a quien llama salvo `abrir()`: un aviso que no se puede
poner es una pareja que se recorre, no un agente caído.
"""

from __future__ import annotations

import ctypes
import errno
import ntpath
import os
import re
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Any, NamedTuple

from .huella import se_ignora

ES_LINUX = sys.platform.startswith("linux")
ES_WINDOWS = os.name == "nt"

# inotify(7), <sys/inotify.h>.
IN_ATTRIB = 0x00000004
IN_CLOSE_WRITE = 0x00000008
IN_MOVED_FROM = 0x00000040
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_DELETE = 0x00000200
IN_DELETE_SELF = 0x00000400
IN_MOVE_SELF = 0x00000800
IN_UNMOUNT = 0x00002000
IN_Q_OVERFLOW = 0x00004000
IN_IGNORED = 0x00008000
IN_ONLYDIR = 0x01000000
IN_DONT_FOLLOW = 0x02000000
IN_EXCL_UNLINK = 0x04000000
IN_ISDIR = 0x40000000

MASCARA = (IN_CLOSE_WRITE | IN_ATTRIB | IN_CREATE | IN_DELETE | IN_MOVED_FROM
           | IN_MOVED_TO | IN_DELETE_SELF | IN_MOVE_SELF)
"""Lo que se pide a cada vigilancia."""
AL_PONER = MASCARA | IN_ONLYDIR | IN_DONT_FOLLOW | IN_EXCL_UNLINK
"""La máscara con la que se pone cada vigilancia."""

CABECERA = struct.Struct("iIII")
"""`struct inotify_event` sin el nombre: `wd`, `mask`, `cookie` y `len`."""
LEER = 64 * 1024  # bytes por lectura del descriptor

CAMBIO = "cambio"
DESBORDADO = "desbordado"
PERDIDA = "perdida"
GRAVEDAD = {CAMBIO: 0, DESBORDADO: 1, PERDIDA: 2}
"""Lo que llega a la vez para una pareja se queda con lo más grave."""

DEJADA = "dejada"
"""Lo que devuelve `vigilar()` si la pareja se dejó mientras se ponía."""
MOTIVO_SIN_SITIO = ("el sistema no da más vigilancias de carpetas "
                    "(fs.inotify.max_user_watches)")
MOTIVO_SE_FUE = "su carpeta ya no está donde estaba (se borró o se movió)"
MOTIVO_DESMONTADA = "se ha desmontado su unidad"

DE_RED = frozenset({
    "nfs", "nfs4", "cifs", "smb3", "smbfs", "ncpfs", "afs", "ceph", "glusterfs",
    "lustre", "9p", "virtiofs", "vboxsf", "davfs", "fuse.davfs2", "fuse.sshfs",
    "fuse.rclone", "fuse.gvfsd-fuse", "fuse.s3fs", "fuse.curlftpfs",
    "fuse.vmhgfs-fuse",
})
"""Sistemas de ficheros cuyos cambios hechos desde otro equipo no avisan.

Los de red y los que una máquina virtual comparte con su anfitrión: inotify ve
lo que pasa por el núcleo de ESTE equipo. Los nombres son los de
`/proc/self/mountinfo`; un FUSE local (`fuseblk`, el exFAT o el NTFS de un
pendrive en un Linux viejo) avisa bien y no está.
"""

PRESUPUESTO = 0.5
"""Parte de `fs.inotify.max_user_watches` que el agente se permite usar.

El límite es de todo el usuario: lo que se lleve el agente se lo quita al
editor que vigila un proyecto, que entonces falla con «ENOSPC».
"""
LIMITE_POR_DEFECTO = 8192
"""El `max_user_watches` de un Linux anterior a la 5.11, si no se puede leer."""
MAX_USER_WATCHES = Path("/proc/sys/fs/inotify/max_user_watches")
MOUNTINFO = Path("/proc/self/mountinfo")

_ESCAPE = re.compile(r"\\([0-7]{3})")


class Aviso(NamedTuple):
    """Lo que ha pasado en la carpeta de una pareja desde la última recogida.

    Args:
        tipo: `CAMBIO`; `DESBORDADO`, que cuenta como cambio y pide volver a
            `vigilar()` la pareja; o `PERDIDA`: la pareja se ha dejado y se
            recorre.
        motivo: En una `PERDIDA`, por qué, para el diario.
    """
    tipo: str
    motivo: str = ""


def limite_de_vigilancias() -> int:
    """Devuelve `fs.inotify.max_user_watches`, o `LIMITE_POR_DEFECTO` si no se lee.

    Punto de indirección: los tests ponen uno pequeño.
    """
    try:
        return int(MAX_USER_WATCHES.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return LIMITE_POR_DEFECTO


def tipo_en_mountinfo(ruta: str, texto: str) -> str:
    """Devuelve el sistema de ficheros de `ruta` según un texto de mountinfo.

    Manda el punto de montaje más largo que la contiene y, si hay varios
    montajes apilados en el mismo punto, el último (el de encima). Los puntos
    de montaje vienen con el espacio y compañía en octal (`\\040`).

    Args:
        ruta: Una ruta absoluta y resuelta.
        texto: El contenido de `/proc/self/mountinfo` (proc(5)).

    Returns:
        El tipo (`ext4`, `nfs4`, `fuse.sshfs`…), o `""` si ninguno la contiene.
    """
    mejor, largo = "", -1
    for linea in texto.splitlines():
        antes, guion, despues = linea.partition(" - ")
        campos = antes.split()
        if not guion or len(campos) < 5 or not despues:
            continue
        punto = _ESCAPE.sub(lambda m: chr(int(m.group(1), 8)), campos[4])
        dentro = ruta == punto or ruta.startswith(punto.rstrip("/") + "/")
        if dentro and len(punto) >= largo:
            mejor, largo = despues.split()[0], len(punto)
    return mejor


def sistema_de(carpeta: Path | str) -> str:
    """Devuelve el sistema de ficheros de una carpeta, o `""` si no se sabe.

    Lee `/proc/self/mountinfo`; los enlaces de la ruta se resuelven antes.
    Punto de indirección: los tests dicen que es una carpeta de red.
    """
    try:
        texto = os.fsdecode(MOUNTINFO.read_bytes())
        return tipo_en_mountinfo(os.path.realpath(carpeta), texto)
    except (OSError, ValueError):
        return ""


def abrir(hwnd: Any = None) -> Inotify | ReadDirectoryChanges | None:
    """Abre el motor de avisos de este sistema.

    Args:
        hwnd: En Windows, la ventana de la bandeja: recibe los avisos de
            extracción de cada handle abierto. Sin ella no hay motor.

    Returns:
        El motor, o `None` donde no lo hay (Windows sin bandeja, otro sistema).

    Raises:
        OSError: Si el sistema no deja abrir un descriptor de inotify (se han
            acabado los de este usuario, `fs.inotify.max_user_instances`).
    """
    if ES_WINDOWS:
        return ReadDirectoryChanges(Win32(), hwnd) if hwnd else None
    if not ES_LINUX:
        return None
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.inotify_init1.argtypes = [ctypes.c_int]
        libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        libc.inotify_rm_watch.argtypes = [ctypes.c_int, ctypes.c_int]
    except AttributeError as e:
        raise OSError(errno.ENOSYS, f"sin inotify: {e}") from e
    fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
    if fd < 0:
        n = ctypes.get_errno()
        raise OSError(n, os.strerror(n))
    return Inotify(fd, libc)


class _SinSitio(Exception):
    """No caben más vigilancias: ni en el presupuesto del agente ni en el sistema."""

    def __init__(self, motivo: str) -> None:
        """Guarda el motivo, que acaba en el diario."""
        super().__init__(motivo)
        self.motivo = motivo


class _Dejada(Exception):
    """La pareja se dejó mientras se le ponía la vigilancia."""


class Inotify:
    """El motor de inotify de un agente: un descriptor y las vigilancias de sus parejas.

    `vigilar()` puede correr en otro hilo que lo demás: los mapas van con un
    cerrojo que se toma por cada vigilancia que se pone, nunca durante un
    `scandir`. `dejar()` mientras `vigilar()` está a medias lo para: deshace
    lo puesto y devuelve `DEJADA`. Cada pareja se identifica con su clave
    `(raíz, pareja)`.

    Args:
        fd: El descriptor de `inotify_init1()`, no bloqueante.
        libc: La libc de `ctypes` con las tres funciones de inotify.

    Attributes:
        fd: El descriptor, para esperar en él (`agente.Vigia.oir()`).
    """

    def __init__(self, fd: int, libc) -> None:
        """Empieza sin ninguna vigilancia."""
        self.fd = fd
        self._libc = libc
        self._cerrojo = threading.RLock()
        self._ruta: dict[int, str] = {}
        self._de: dict[int, set[tuple[str, str]]] = {}
        self._wds: dict[tuple[str, str], set[int]] = {}
        self._raiz: dict[tuple[str, str], int] = {}
        self._parejas: dict[tuple[str, str], tuple[str, tuple[str, ...]]] = {}
        self._pendientes: dict[tuple[str, str], Aviso] = {}

    # -- las llamadas al sistema (los tests las sustituyen en la instancia) --

    def _add_watch(self, ruta: str) -> int:
        """Pone (o reutiliza) la vigilancia de una carpeta y devuelve su `wd`.

        Raises:
            OSError: Con el `errno` de `inotify_add_watch()`.
        """
        wd = self._libc.inotify_add_watch(self.fd, os.fsencode(ruta), AL_PONER)
        if wd < 0:
            n = ctypes.get_errno()
            raise OSError(n, os.strerror(n), ruta)
        return wd

    def _rm_watch(self, wd: int) -> None:
        """Quita una vigilancia; si el núcleo ya la quitó, no pasa nada."""
        self._libc.inotify_rm_watch(self.fd, wd)

    # -- lo que usa el agente --

    def vigilancias(self) -> int:
        """Devuelve cuántas vigilancias (carpetas) tiene puestas."""
        with self._cerrojo:
            return len(self._ruta)

    def vigilar(self, clave: tuple[str, str], carpeta: Path | str,
                ignorar: tuple[str, ...]) -> str | None:
        """Pone (o rehace) la vigilancia de la carpeta de una pareja.

        Recorre las carpetas del árbol, sin seguir enlaces, y pone una
        vigilancia en cada una ANTES de listarla: lo que se crea mientras se
        ve. Una subcarpeta que no se deja abrir o que desaparece se salta,
        como en la foto. Rehacer la de una pareja que ya se vigilaba pone lo
        que falte y quita lo que ya no está en su árbol.

        Args:
            clave: `(raíz, pareja)`.
            carpeta: La carpeta local de la pareja.
            ignorar: Patrones (`fnmatch`, en minúsculas) de las entradas de su
                raíz que no se miran: ni avisan ni se vigilan.

        Returns:
            `None` si se vigila; si no, el motivo para el diario (y entonces no
            queda nada suyo puesto), o `DEJADA` si se dejó mientras tanto.
        """
        ruta = os.fspath(carpeta)
        tipo = sistema_de(ruta)
        if tipo in DE_RED:
            return (f"es una carpeta de red o compartida ({tipo}): no avisa de lo que se "
                    f"cambia desde el otro lado")
        patrones = tuple(p.lower() for p in ignorar)
        with self._cerrojo:
            self._parejas[clave] = (ruta, patrones)
            self._wds.setdefault(clave, set())
        vistas: set[int] = set()
        try:
            self._armar(ruta, {clave}, vistas, raiz_de=clave)
        except _Dejada:
            return DEJADA
        except _SinSitio as e:
            with self._cerrojo:
                self._quitar(clave)
            return e.motivo
        except OSError as e:
            with self._cerrojo:
                self._quitar(clave)
            if e.errno == errno.ENOSPC:
                return MOTIVO_SIN_SITIO
            return f"no se puede vigilar su carpeta: {e.strerror or e}"
        with self._cerrojo:
            if clave not in self._parejas:
                return DEJADA
            for wd in self._wds.get(clave, set()) - vistas:
                self._soltar(clave, wd)
        return None

    def dejar(self, clave: tuple[str, str]) -> None:
        """Quita la vigilancia de una pareja (las carpetas que comparte con otra, no)."""
        with self._cerrojo:
            self._quitar(clave)

    def dejar_raiz(self, uid: str) -> None:
        """Quita las vigilancias de todas las parejas de una raíz."""
        with self._cerrojo:
            for clave in [k for k in set(self._parejas) | set(self._wds) if k[0] == uid]:
                self._quitar(clave)

    def leer(self) -> None:
        """Lee lo que haya en el descriptor y lo apunta, sin esperar.

        Es lo que hace el vigía del agente en cuanto el descriptor tiene algo,
        para que la cola del núcleo no se llene entre dos vueltas.
        """
        with self._cerrojo:
            while self.fd >= 0:
                try:
                    datos = os.read(self.fd, LEER)
                except InterruptedError:
                    continue
                except OSError:
                    return                  # vacío (`EAGAIN`) o cerrado
                if not datos:
                    return
                self._procesar_bloque(datos)

    def recoger(self) -> dict[tuple[str, str], Aviso]:
        """Devuelve lo que ha llegado desde la última vez, por pareja, y lo olvida."""
        self.leer()
        with self._cerrojo:
            avisos, self._pendientes = self._pendientes, {}
        return avisos

    def descartar(self, clave: tuple[str, str]) -> Aviso | None:
        """Tira lo que ha llegado de una pareja: lo escribió su propia pasada.

        Una `PERDIDA` no se tira: la pareja ya no se vigila y quien llama tiene
        que enterarse en `recoger()`.

        Returns:
            Lo que se ha tirado, o `None`. Si es un `DESBORDADO` la pasada no
            cuenta como cambio, pero la vigilancia hay que rehacerla igual.
        """
        self.leer()
        with self._cerrojo:
            aviso = self._pendientes.get(clave)
            if aviso is None or aviso.tipo == PERDIDA:
                return None
            del self._pendientes[clave]
            return aviso

    def cerrar(self) -> None:
        """Cierra el descriptor; con él se van todas las vigilancias."""
        with self._cerrojo:
            if self.fd >= 0:
                try:
                    os.close(self.fd)
                except OSError:
                    pass
            self.fd = -1
            for mapa in (self._ruta, self._de, self._wds, self._raiz, self._parejas,
                         self._pendientes):
                mapa.clear()

    # -- por dentro --

    def _armar(self, ruta: str, claves: set[tuple[str, str]], vistas: set[int],
               raiz_de: tuple[str, str] | None = None) -> None:
        """Pone las vigilancias de un árbol de carpetas para esas parejas.

        Args:
            ruta: La carpeta de arriba del árbol.
            claves: Las parejas a las que avisa lo que pase en él.
            vistas: Donde se apunta cada `wd` puesto o reutilizado.
            raiz_de: La pareja de la que `ruta` es la raíz, si lo es: entonces
                se aplican sus patrones a lo que cuelga de ella, se puede
                parar con `dejar()` y un fallo en la propia `ruta` se propaga.

        Raises:
            _Dejada: Si `raiz_de` se dejó mientras tanto.
            _SinSitio: Si no caben más vigilancias.
            OSError: Si la raíz no se deja vigilar, o `ENOSPC` en cualquiera.
        """
        presupuesto = max(1, int(limite_de_vigilancias() * PRESUPUESTO))
        patrones = self._parejas.get(raiz_de, ("", ()))[1] if raiz_de else ()
        pendientes = [(ruta, raiz_de is not None)]
        while pendientes:
            carpeta, es_raiz = pendientes.pop()
            try:
                wd = self._poner(carpeta, claves, presupuesto, raiz_de, es_raiz)
                vistas.add(wd)
                with os.scandir(carpeta) as it:
                    for e in it:
                        if es_raiz and se_ignora(e.name, patrones):
                            continue
                        try:
                            if e.is_dir(follow_symlinks=False):
                                pendientes.append((e.path, False))
                        except OSError:
                            continue
            except (FileNotFoundError, NotADirectoryError, PermissionError):
                if es_raiz:
                    raise

    def _poner(self, ruta: str, claves: set[tuple[str, str]], presupuesto: int,
               raiz_de: tuple[str, str] | None, es_raiz: bool) -> int:
        """Pone la vigilancia de una carpeta y la apunta para esas parejas.

        Raises:
            _Dejada: Si `raiz_de` se dejó antes o durante la llamada.
            _SinSitio: Si es una vigilancia nueva y el agente ya tiene las
                que le caben.
        """
        with self._cerrojo:
            if raiz_de is not None and raiz_de not in self._parejas:
                raise _Dejada
            wd = self._add_watch(ruta)
            nueva = wd not in self._ruta
            if raiz_de is not None and raiz_de not in self._parejas:
                if nueva:
                    self._rm_watch(wd)
                raise _Dejada
            if nueva and len(self._ruta) >= presupuesto:
                self._rm_watch(wd)
                raise _SinSitio(f"tiene más carpetas de las que caben en los avisos del "
                                f"sistema (el agente usa como mucho {presupuesto}, la "
                                f"mitad de fs.inotify.max_user_watches)")
            self._ruta[wd] = ruta
            self._de.setdefault(wd, set()).update(claves)
            for k in claves:
                self._wds.setdefault(k, set()).add(wd)
            if es_raiz and raiz_de is not None:
                self._raiz[raiz_de] = wd
            return wd

    def _soltar(self, clave: tuple[str, str], wd: int) -> None:
        """Quita una pareja de una vigilancia, y la vigilancia si ya no es de nadie."""
        self._wds.get(clave, set()).discard(wd)
        de = self._de.get(wd)
        if de is None:
            return
        de.discard(clave)
        if not de:
            self._rm_watch(wd)
            self._olvidar_wd(wd)

    def _olvidar_wd(self, wd: int) -> None:
        """Olvida una vigilancia que ya no está (la quitó el núcleo o este motor)."""
        for k in self._de.pop(wd, set()):
            self._wds.get(k, set()).discard(wd)
        self._ruta.pop(wd, None)

    def _quitar(self, clave: tuple[str, str]) -> None:
        """Deja una pareja: sus vigilancias, lo pendiente y lo que se sabía de ella."""
        for wd in list(self._wds.get(clave, ())):
            self._soltar(clave, wd)
        self._wds.pop(clave, None)
        self._raiz.pop(clave, None)
        self._parejas.pop(clave, None)
        self._pendientes.pop(clave, None)

    def _marcar(self, clave: tuple[str, str], aviso: Aviso) -> None:
        """Apunta un aviso de una pareja, quedándose con lo más grave."""
        antes = self._pendientes.get(clave)
        if antes is None or GRAVEDAD[aviso.tipo] > GRAVEDAD[antes.tipo]:
            self._pendientes[clave] = aviso

    def _perder(self, clave: tuple[str, str], motivo: str) -> None:
        """Deja una pareja y apunta que se ha perdido, con el motivo."""
        self._quitar(clave)
        self._pendientes[clave] = Aviso(PERDIDA, motivo)

    def _procesar_bloque(self, datos: bytes) -> None:
        """Reparte los `struct inotify_event` de una lectura del descriptor."""
        i = 0
        while i + CABECERA.size <= len(datos):
            wd, mask, cookie, largo = CABECERA.unpack_from(datos, i)
            i += CABECERA.size
            nombre = os.fsdecode(datos[i:i + largo].split(b"\0", 1)[0])
            i += largo
            self._procesar(wd, mask, cookie, nombre)

    def _procesar(self, wd: int, mask: int, cookie: int, nombre: str) -> None:
        """Convierte un evento de inotify en el aviso de cada pareja a la que toca.

        Args:
            wd: La vigilancia (-1 en `IN_Q_OVERFLOW`).
            mask: Lo que ha pasado.
            cookie: Empareja un `IN_MOVED_FROM` con su `IN_MOVED_TO`; no se usa.
            nombre: La entrada de la carpeta vigilada, o `""` si es ella misma.
        """
        with self._cerrojo:
            if mask & IN_Q_OVERFLOW:
                for k in self._parejas:
                    self._marcar(k, Aviso(DESBORDADO))
                return
            claves = set(self._de.get(wd, ()))
            if not claves:
                return
            raices = {k for k in claves if self._raiz.get(k) == wd}
            if mask & (IN_IGNORED | IN_UNMOUNT | IN_DELETE_SELF | IN_MOVE_SELF):
                perdidas = claves if mask & IN_UNMOUNT else raices
                if mask & IN_IGNORED:
                    self._olvidar_wd(wd)
                for k in perdidas:
                    self._perder(k, MOTIVO_DESMONTADA if mask & IN_UNMOUNT else MOTIVO_SE_FUE)
                return
            if not nombre:
                return
            carpeta = bool(mask & IN_ISDIR)
            nuevas: set[tuple[str, str]] = set()
            for k in claves:
                if k in raices and se_ignora(nombre, self._parejas.get(k, ("", ()))[1]):
                    continue
                if carpeta and mask & IN_ATTRIB:
                    continue
                if carpeta and mask & (IN_MOVED_FROM | IN_MOVED_TO):
                    self._marcar(k, Aviso(DESBORDADO))
                    continue
                self._marcar(k, Aviso(CAMBIO))
                if carpeta and mask & IN_CREATE:
                    nuevas.add(k)
            if nuevas:
                try:
                    self._armar(os.path.join(self._ruta[wd], nombre), nuevas, set())
                except _SinSitio as e:
                    for k in nuevas:
                        self._perder(k, e.motivo)
                except OSError as e:
                    if e.errno == errno.ENOSPC:
                        for k in nuevas:
                            self._perder(k, MOTIVO_SIN_SITIO)


# ---------------------------------------------------------------------------
# Windows: ReadDirectoryChangesW
# ---------------------------------------------------------------------------

# fileapi.h, winbase.h, winnt.h.
FILE_LIST_DIRECTORY = 0x0001
FILE_SHARE_TODO = 0x1 | 0x2 | 0x4          # FILE_SHARE_READ | WRITE | DELETE
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OVERLAPPED = 0x40000000
FILE_NOTIFY_CHANGE_FILE_NAME = 0x01
FILE_NOTIFY_CHANGE_DIR_NAME = 0x02
FILE_NOTIFY_CHANGE_SIZE = 0x08
FILE_NOTIFY_CHANGE_LAST_WRITE = 0x10
FILTRO_WINDOWS = (FILE_NOTIFY_CHANGE_FILE_NAME | FILE_NOTIFY_CHANGE_DIR_NAME
                  | FILE_NOTIFY_CHANGE_SIZE | FILE_NOTIFY_CHANGE_LAST_WRITE)
"""Lo que se pide a `ReadDirectoryChangesW`: nombres, tamaño y escritura, no los accesos."""
FILE_ACTION_ADDED = 1
FILE_ACTION_REMOVED = 2
FILE_ACTION_MODIFIED = 3
FILE_ACTION_RENAMED_OLD_NAME = 4
FILE_ACTION_RENAMED_NEW_NAME = 5
DRIVE_REMOTE = 4
ERROR_ACCESS_DENIED = 5
ERROR_OPERATION_ABORTED = 995
ERROR_NOTIFY_ENUM_DIR = 1022
INFINITO = 0xFFFFFFFF
# dbt.h: lo que la bandeja pasa a `dispositivo()`.
DBT_DEVICEQUERYREMOVE = 0x8001
DBT_DEVICEQUERYREMOVEFAILED = 0x8002
DBT_DEVICEREMOVEPENDING = 0x8003
DBT_DEVICEREMOVECOMPLETE = 0x8004
DBT_DEVTYP_HANDLE = 6

MAX_PAREJAS_WINDOWS = 63
"""Las que caben en un `WaitForMultipleObjects` (64) junto al evento de control."""
TAM_BUFER = 64 * 1024
"""Bytes del búfer de cada lectura: el máximo que admite una carpeta de red, y de sobra."""
ESPERA_HILO = 10.0
"""Segundos que `vigilar()` y `cerrar()` esperan al hilo del motor."""
DISPOSITIVOS_VERACRYPT = ("\\Device\\VeraCryptVolume", "\\Device\\TrueCryptVolume")
"""Cómo empieza el dispositivo de una letra que es un volumen de VeraCrypt.

Es el `NT_MOUNT_PREFIX` de su controlador (`Common/Tcdefs.h`), lo que devuelve
`QueryDosDeviceW("P:")`; el de TrueCrypt, para los volúmenes que VeraCrypt
monta en ese modo.
"""
MOTIVO_RED_WINDOWS = ("es una carpeta de red: no avisa de lo que se cambia desde el otro "
                      "lado")
MOTIVO_VERACRYPT = ("es un volumen de VeraCrypt: Windows no avisa al desmontarlo, y una "
                    "carpeta abierta impediría desmontarlo sin forzar")
MOTIVO_SIN_REGISTRO = ("Windows no avisaría al pedir la unidad para expulsarla: no se deja "
                       "su carpeta abierta")
MOTIVO_SIN_RESPUESTA = "el vigilante de avisos de Windows no contesta"


def avisos_de_windows(datos: bytes) -> list[tuple[int, str]]:
    """Lee un búfer de `FILE_NOTIFY_INFORMATION` (winnt.h).

    Cada entrada: `NextEntryOffset`, `Action` y `FileNameLength` (DWORD) y el
    nombre en UTF-16, relativo a la carpeta vigilada y con `\\`.

    Returns:
        `(acción, nombre)` de cada entrada, por orden.
    """
    salida: list[tuple[int, str]] = []
    i = 0
    while i + 12 <= len(datos):
        siguiente, accion, largo = struct.unpack_from("<III", datos, i)
        nombre = datos[i + 12:i + 12 + largo].decode("utf-16-le", "surrogatepass")
        salida.append((accion, nombre))
        if not siguiente:
            break
        i += siguiente
    return salida


def _winerror(e: OSError) -> int | None:
    """El código de Windows de un error (`winerror`), si lo lleva."""
    return getattr(e, "winerror", None)


class Win32:
    """Las llamadas a kernel32 y user32 que hace el motor de Windows.

    Los tests ponen una de mentira con los mismos métodos. Lo que falla lanza
    `OSError` con su `winerror` (`ctypes.WinError()`).
    """

    def __init__(self) -> None:
        """Carga las bibliotecas y declara las firmas de lo que se usa."""
        import ctypes
        from ctypes import wintypes as wt

        self.ct = ctypes
        k = self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        u = self.user32 = ctypes.WinDLL("user32", use_last_error=True)

        class OVERLAPPED(ctypes.Structure):
            """`OVERLAPPED` de minwinbase.h (la unión `Offset`/`Pointer`, como dos DWORD)."""
            _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                        ("Offset", wt.DWORD), ("OffsetHigh", wt.DWORD),
                        ("hEvent", wt.HANDLE)]

        class DEV_BROADCAST_HANDLE(ctypes.Structure):
            """`DEV_BROADCAST_HANDLE` de dbt.h."""
            _fields_ = [("dbch_size", wt.DWORD), ("dbch_devicetype", wt.DWORD),
                        ("dbch_reserved", wt.DWORD), ("dbch_handle", wt.HANDLE),
                        ("dbch_hdevnotify", wt.HANDLE), ("dbch_eventguid", ctypes.c_byte * 16),
                        ("dbch_nameoffset", wt.LONG), ("dbch_data", ctypes.c_byte * 1)]

        self.OVERLAPPED, self.DEV_BROADCAST_HANDLE = OVERLAPPED, DEV_BROADCAST_HANDLE
        self.INVALIDO = ctypes.c_void_p(-1).value
        k.CreateFileW.restype = wt.HANDLE
        k.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID, wt.DWORD,
                                  wt.DWORD, wt.HANDLE]
        k.ReadDirectoryChangesW.restype = wt.BOOL
        k.ReadDirectoryChangesW.argtypes = [wt.HANDLE, wt.LPVOID, wt.DWORD, wt.BOOL,
                                            wt.DWORD, wt.LPDWORD,
                                            ctypes.POINTER(OVERLAPPED), wt.LPVOID]
        k.GetOverlappedResult.restype = wt.BOOL
        k.GetOverlappedResult.argtypes = [wt.HANDLE, ctypes.POINTER(OVERLAPPED),
                                          wt.LPDWORD, wt.BOOL]
        k.CancelIoEx.restype = wt.BOOL
        k.CancelIoEx.argtypes = [wt.HANDLE, ctypes.POINTER(OVERLAPPED)]
        k.CloseHandle.restype = wt.BOOL
        k.CloseHandle.argtypes = [wt.HANDLE]
        k.CreateEventW.restype = wt.HANDLE
        k.CreateEventW.argtypes = [wt.LPVOID, wt.BOOL, wt.BOOL, wt.LPCWSTR]
        k.SetEvent.argtypes = [wt.HANDLE]
        k.ResetEvent.argtypes = [wt.HANDLE]
        k.WaitForMultipleObjects.restype = wt.DWORD
        k.WaitForMultipleObjects.argtypes = [wt.DWORD, ctypes.POINTER(wt.HANDLE), wt.BOOL,
                                             wt.DWORD]
        k.WaitForSingleObject.restype = wt.DWORD
        k.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
        k.GetDriveTypeW.restype = wt.UINT
        k.GetDriveTypeW.argtypes = [wt.LPCWSTR]
        k.QueryDosDeviceW.restype = wt.DWORD
        k.QueryDosDeviceW.argtypes = [wt.LPCWSTR, wt.LPWSTR, wt.DWORD]
        u.RegisterDeviceNotificationW.restype = wt.HANDLE
        u.RegisterDeviceNotificationW.argtypes = [wt.HANDLE, wt.LPVOID, wt.DWORD]
        u.UnregisterDeviceNotification.restype = wt.BOOL
        u.UnregisterDeviceNotification.argtypes = [wt.HANDLE]

    def _error(self) -> OSError:
        """El último error de Windows de este hilo, como `OSError`."""
        return self.ct.WinError(self.ct.get_last_error())

    def tipo_de_unidad(self, raiz: str) -> int:
        """`GetDriveTypeW` de la raíz de una unidad (`E:\\`, `\\\\nas\\c\\`)."""
        return int(self.kernel32.GetDriveTypeW(raiz))

    def dispositivo_de(self, unidad: str) -> str:
        """`QueryDosDeviceW` de una letra (`P:`), o `""` si no se sabe."""
        bufer = self.ct.create_unicode_buffer(1024)
        if not self.kernel32.QueryDosDeviceW(unidad, bufer, len(bufer)):
            return ""
        return bufer.value

    def abrir_carpeta(self, ruta: str) -> int:
        """Abre una carpeta para leer sus cambios, sin impedir a nadie tocarla."""
        h = self.kernel32.CreateFileW(ruta, FILE_LIST_DIRECTORY, FILE_SHARE_TODO, None,
                                      OPEN_EXISTING,
                                      FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OVERLAPPED, None)
        if h is None or h == self.INVALIDO:
            raise self._error()
        return h

    def cerrar(self, h: int) -> None:
        """`CloseHandle`; la lectura pendiente de ese handle acaba cancelada."""
        self.kernel32.CloseHandle(h)

    def registrar(self, hwnd: Any, h: int) -> int:
        """Registra el aviso de extracción de un handle en una ventana; 0 si no se puede."""
        filtro = self.DEV_BROADCAST_HANDLE()
        filtro.dbch_size = self.ct.sizeof(filtro)
        filtro.dbch_devicetype = DBT_DEVTYP_HANDLE
        filtro.dbch_handle = h
        return self.user32.RegisterDeviceNotificationW(hwnd, self.ct.byref(filtro), 0) or 0

    def desregistrar(self, aviso: int) -> None:
        """`UnregisterDeviceNotification`."""
        self.user32.UnregisterDeviceNotification(aviso)

    def evento(self) -> int:
        """Un evento de reinicio manual, sin señalar."""
        ev = self.kernel32.CreateEventW(None, True, False, None)
        if not ev:
            raise self._error()
        return ev

    def cerrar_evento(self, ev: int) -> None:
        """Cierra un evento."""
        self.kernel32.CloseHandle(ev)

    def poner(self, ev: int) -> None:
        """`SetEvent`."""
        self.kernel32.SetEvent(ev)

    def quitar(self, ev: int) -> None:
        """`ResetEvent`."""
        self.kernel32.ResetEvent(ev)

    def overlapped(self, ev: int):
        """Un `OVERLAPPED` con ese evento."""
        ov = self.OVERLAPPED()
        ov.hEvent = ev
        return ov

    def bufer(self, n: int):
        """Un búfer alineado a DWORD, como pide `ReadDirectoryChangesW`."""
        return (self.ct.c_uint32 * max(1, n // 4))()

    def bytes_de(self, bufer, n: int) -> bytes:
        """Los primeros `n` bytes de un búfer."""
        return self.ct.string_at(self.ct.addressof(bufer), n)

    def leer_cambios(self, h: int, bufer, ov, tam: int) -> None:
        """Lanza una lectura superpuesta de los cambios de la carpeta y su árbol."""
        if not self.kernel32.ReadDirectoryChangesW(h, bufer, tam, True, FILTRO_WINDOWS, None,
                                                   self.ct.byref(ov), None):
            raise self._error()

    def resultado(self, h: int, ov) -> int:
        """Cuántos bytes dejó una lectura acabada (`GetOverlappedResult` sin esperar)."""
        n = self.ct.c_ulong(0)
        if not self.kernel32.GetOverlappedResult(h, self.ct.byref(ov), self.ct.byref(n),
                                                 False):
            raise self._error()
        return n.value

    def cancelar(self, h: int, ov) -> None:
        """`CancelIoEx` de una lectura."""
        self.kernel32.CancelIoEx(h, self.ct.byref(ov))

    def esperar(self, eventos: list, ms: int) -> int:
        """`WaitForMultipleObjects` de cualquiera; devuelve el índice del que se señaló."""
        lista = (self.ct.c_void_p * len(eventos))(*eventos)
        r = self.kernel32.WaitForMultipleObjects(len(eventos), lista, False, ms)
        if r == 0xFFFFFFFF:
            raise self._error()
        return int(r)

    def senalado(self, ev: int) -> bool:
        """Indica si un evento está señalado, sin esperar."""
        return self.kernel32.WaitForSingleObject(ev, 0) == 0


class _Vigilancia:
    """La vigilancia de Windows de una pareja: su handle, su lectura y su aviso de extracción.

    El evento, el `OVERLAPPED` y el búfer viven hasta que su lectura acaba,
    aunque el handle ya esté cerrado: Windows escribe en ellos hasta entonces.

    Args:
        clave: `(raíz, pareja)`.
        ruta: La carpeta.
        patrones: Lo que no se mira de su raíz.
    """

    def __init__(self, clave: tuple[str, str], ruta: str, patrones: tuple[str, ...]) -> None:
        """Una vigilancia todavía sin abrir."""
        self.clave, self.ruta, self.patrones = clave, ruta, patrones
        self.handle: int | None = None
        self.aviso = 0
        self.evento: Any = None
        self.ov: Any = None
        self.bufer: Any = None
        self.leyendo = False


class ReadDirectoryChanges:
    """El motor de avisos de Windows: un handle por pareja y un hilo que los espera.

    Tiene los mismos métodos que `Inotify` (sin descriptor: `fd` es `None` y
    `leer()` no hace nada) y `dispositivo()`, que la bandeja llama con los
    avisos de extracción de cada handle.

    Args:
        api: Las llamadas a Windows (`Win32`, o una de mentira).
        hwnd: La ventana de la bandeja, que recibe los avisos de extracción.
        tam_bufer: Bytes del búfer de cada lectura.

    Attributes:
        fd: `None`: no hay nada que el vigía del agente tenga que oír.
    """

    def __init__(self, api: Any, hwnd: Any, tam_bufer: int = TAM_BUFER) -> None:
        """Arranca el hilo que espera las lecturas."""
        self.fd = None
        self._api = api
        self._hwnd = hwnd
        self._tam = tam_bufer
        self._cerrojo = threading.RLock()
        self._queridas: dict[tuple[str, str], tuple[str, tuple[str, ...]]] = {}
        self._activas: dict[tuple[str, str], _Vigilancia] = {}
        self._calladas: dict[int, _Vigilancia] = {}
        self._acabando: list[_Vigilancia] = []
        self._pendientes: dict[tuple[str, str], Aviso] = {}
        self._peticiones: list[tuple[tuple[str, str], threading.Event | None, list]] = []
        self._parar = False
        self._control = api.evento()
        self._hilo = threading.Thread(target=self._correr, name="avisos-carpeta", daemon=True)
        self._hilo.start()

    # -- lo que usa el agente --

    def vigilancias(self) -> int:
        """Devuelve cuántas carpetas tiene abiertas."""
        with self._cerrojo:
            return len(self._activas)

    def vigilar(self, clave: tuple[str, str], carpeta: Path | str,
                ignorar: tuple[str, ...]) -> str | None:
        """Abre la carpeta de una pareja y empieza a leer sus cambios.

        Volver a pedir una que ya se vigila no hace nada: `bWatchSubtree` sigue
        solo las carpetas nuevas y las movidas.

        Returns:
            `None` si se vigila; si no, el motivo para el diario (y entonces no
            queda nada suyo abierto), o `DEJADA` si se dejó mientras tanto.
        """
        ruta = ntpath.abspath(os.fspath(carpeta))
        unidad = ntpath.splitdrive(ruta)[0]
        if self._api.tipo_de_unidad(unidad.rstrip("\\") + "\\") == DRIVE_REMOTE:
            return MOTIVO_RED_WINDOWS
        if len(unidad) == 2 and self._api.dispositivo_de(unidad).startswith(
                DISPOSITIVOS_VERACRYPT):
            return MOTIVO_VERACRYPT
        patrones = tuple(p.lower() for p in ignorar)
        with self._cerrojo:
            if clave in self._activas:
                return None
            self._queridas[clave] = (ruta, patrones)
        return self._pedir_armar(clave, ruta, patrones)

    def dejar(self, clave: tuple[str, str]) -> None:
        """Cierra la carpeta de una pareja en el acto, y su aviso de extracción."""
        with self._cerrojo:
            self._queridas.pop(clave, None)
            self._pendientes.pop(clave, None)
            v = self._activas.pop(clave, None)
            if v is not None:
                self._cerrar(v)
            for h, callada in list(self._calladas.items()):
                if callada.clave == clave:
                    del self._calladas[h]
                    self._desregistrar(callada)

    def dejar_raiz(self, uid: str) -> None:
        """Cierra las carpetas de todas las parejas de una raíz."""
        with self._cerrojo:
            claves = {k for k in self._queridas if k[0] == uid}
            claves |= {k for k in self._activas if k[0] == uid}
            claves |= {v.clave for v in self._calladas.values() if v.clave[0] == uid}
        for clave in claves:
            self.dejar(clave)

    def leer(self) -> None:
        """No hace nada: el hilo del motor lee él solo."""

    def recoger(self) -> dict[tuple[str, str], Aviso]:
        """Devuelve lo que ha llegado desde la última vez, por pareja, y lo olvida."""
        with self._cerrojo:
            avisos, self._pendientes = self._pendientes, {}
        return avisos

    def descartar(self, clave: tuple[str, str]) -> Aviso | None:
        """Tira lo que ha llegado de una pareja (lo escribió su pasada); como `Inotify.descartar()`."""
        with self._cerrojo:
            aviso = self._pendientes.get(clave)
            if aviso is None or aviso.tipo == PERDIDA:
                return None
            del self._pendientes[clave]
            return aviso

    def dispositivo(self, evento: int, handle: int) -> None:
        """Atiende un aviso de extracción de un handle; lo llama la bandeja, desde su hilo.

        Args:
            evento: `DBT_DEVICEQUERYREMOVE`, `…QUERYREMOVEFAILED`,
                `…REMOVEPENDING` o `…REMOVECOMPLETE`.
            handle: El handle del aviso (`dbch_handle`).
        """
        with self._cerrojo:
            if evento == DBT_DEVICEQUERYREMOVE:
                v = next((x for x in self._activas.values() if x.handle == handle), None)
                if v is not None:
                    del self._activas[v.clave]
                    self._cerrar(v, desregistrar=False)
                    self._calladas[handle] = v
            elif evento == DBT_DEVICEQUERYREMOVEFAILED:
                v = self._calladas.pop(handle, None)
                if v is not None:
                    self._desregistrar(v)
                    if v.clave in self._queridas:
                        self._peticiones.append((v.clave, None, []))
                        self._api.poner(self._control)
            elif evento in (DBT_DEVICEREMOVEPENDING, DBT_DEVICEREMOVECOMPLETE):
                v = self._calladas.pop(handle, None)
                if v is None:
                    v = next((x for x in self._activas.values() if x.handle == handle), None)
                    if v is not None:
                        del self._activas[v.clave]
                        self._cerrar(v, desregistrar=False)
                if v is not None:
                    self._desregistrar(v)
                    self._perder(v.clave, MOTIVO_DESMONTADA)

    def cerrar(self) -> None:
        """Para el hilo y cierra todo lo abierto."""
        with self._cerrojo:
            self._parar = True
            self._api.poner(self._control)
        if self._hilo is not threading.current_thread():
            self._hilo.join(ESPERA_HILO)
        with self._cerrojo:
            for clave in list(self._activas):
                self._cerrar(self._activas.pop(clave))
            for v in self._calladas.values():
                self._desregistrar(v)
            self._calladas.clear()
            self._queridas.clear()

    # -- por dentro --

    def _pedir_armar(self, clave: tuple[str, str], ruta: str,
                     patrones: tuple[str, ...]) -> str | None:
        """Pide al hilo del motor que abra la carpeta de la pareja, y espera su respuesta."""
        hecho, respuesta = threading.Event(), []
        with self._cerrojo:
            self._peticiones.append((clave, hecho, respuesta))
            self._api.poner(self._control)
        if not hecho.wait(ESPERA_HILO):
            with self._cerrojo:
                if not respuesta:
                    self._queridas.pop(clave, None)
                    return MOTIVO_SIN_RESPUESTA
        return respuesta[0]

    def _armar(self, clave: tuple[str, str]) -> str | None:
        """Abre la carpeta de una pareja y lanza su primera lectura; lo hace el hilo del motor."""
        if clave not in self._queridas:
            return DEJADA
        if clave in self._activas:
            return None
        if len(self._activas) + len(self._acabando) >= MAX_PAREJAS_WINDOWS:
            return (f"ya hay {MAX_PAREJAS_WINDOWS} parejas vigiladas con avisos en este "
                    f"equipo")
        ruta, patrones = self._queridas[clave]
        v = _Vigilancia(clave, ruta, patrones)
        try:
            v.handle = self._api.abrir_carpeta(ruta)
        except OSError as e:
            return f"no se puede vigilar su carpeta: {e.strerror or e}"
        v.aviso = self._api.registrar(self._hwnd, v.handle)
        if not v.aviso:
            self._api.cerrar(v.handle)
            return MOTIVO_SIN_REGISTRO
        v.evento = self._api.evento()
        v.ov = self._api.overlapped(v.evento)
        v.bufer = self._api.bufer(self._tam)
        try:
            self._api.leer_cambios(v.handle, v.bufer, v.ov, self._tam)
        except OSError as e:
            self._api.cerrar(v.handle)
            self._desregistrar(v)
            self._api.cerrar_evento(v.evento)
            return f"su carpeta no da avisos: {e.strerror or e}"
        v.leyendo = True
        self._activas[clave] = v
        return None

    def _correr(self) -> None:
        """Es el hilo del motor: atiende las peticiones y las lecturas que acaban."""
        while True:
            with self._cerrojo:
                if self._parar:
                    break
                vivas = list(self._activas.values()) + self._acabando
                eventos = [self._control] + [v.evento for v in vivas]
            try:
                self._api.esperar(eventos, INFINITO)
            except OSError:
                time.sleep(1.0)
                continue
            with self._cerrojo:
                self._api.quitar(self._control)
                peticiones, self._peticiones = self._peticiones, []
                for clave, hecho, respuesta in peticiones:
                    motivo = self._armar(clave)
                    if hecho is not None:
                        respuesta.append(motivo)
                        hecho.set()
                    elif motivo is not None and clave in self._queridas:
                        self._perder(clave, motivo)
                for v in vivas:
                    if v.leyendo and self._api.senalado(v.evento):
                        self._acabada(v)

    def _acabada(self, v: _Vigilancia) -> None:
        """Recoge una lectura que ha acabado y lanza la siguiente."""
        v.leyendo = False
        if v.handle is None:
            # Su handle ya se cerró: la lectura acaba cancelada y ya se puede soltar todo.
            if v in self._acabando:
                self._acabando.remove(v)
            self._api.cerrar_evento(v.evento)
            return
        try:
            n = self._api.resultado(v.handle, v.ov)
        except OSError as e:
            if _winerror(e) != ERROR_NOTIFY_ENUM_DIR:
                del self._activas[v.clave]
                self._cerrar(v)
                self._perder(v.clave, MOTIVO_SE_FUE)
                return
            n = 0
        if n == 0:
            self._marcar(v.clave, Aviso(DESBORDADO))
        else:
            for _accion, nombre in avisos_de_windows(self._api.bytes_de(v.bufer, n)):
                if not se_ignora(nombre.split("\\", 1)[0], v.patrones):
                    self._marcar(v.clave, Aviso(CAMBIO))
                    break
        try:
            self._api.quitar(v.evento)
            self._api.leer_cambios(v.handle, v.bufer, v.ov, self._tam)
            v.leyendo = True
        except OSError:
            del self._activas[v.clave]
            self._cerrar(v)
            self._perder(v.clave, MOTIVO_SE_FUE)

    def _cerrar(self, v: _Vigilancia, desregistrar: bool = True) -> None:
        """Cierra el handle de una vigilancia; su evento y su búfer, cuando acabe su lectura."""
        if v.handle is not None:
            if v.leyendo:
                self._api.cancelar(v.handle, v.ov)
            self._api.cerrar(v.handle)
            v.handle = None
        if desregistrar:
            self._desregistrar(v)
        if v.leyendo:
            self._acabando.append(v)
        elif v.evento is not None:
            self._api.cerrar_evento(v.evento)
            v.evento = None
        self._api.poner(self._control)

    def _desregistrar(self, v: _Vigilancia) -> None:
        """Quita el aviso de extracción de una vigilancia."""
        if v.aviso:
            self._api.desregistrar(v.aviso)
            v.aviso = 0

    def _marcar(self, clave: tuple[str, str], aviso: Aviso) -> None:
        """Apunta un aviso de una pareja, quedándose con lo más grave."""
        antes = self._pendientes.get(clave)
        if antes is None or GRAVEDAD[aviso.tipo] > GRAVEDAD[antes.tipo]:
            self._pendientes[clave] = aviso

    def _perder(self, clave: tuple[str, str], motivo: str) -> None:
        """Olvida una pareja y apunta que se ha perdido, con el motivo."""
        self._queridas.pop(clave, None)
        self._pendientes[clave] = Aviso(PERDIDA, motivo)
