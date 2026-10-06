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

Windows no tiene motor todavía (`abrir()` devuelve `None`): sus parejas se
recorren. Nada de esto lanza a quien llama salvo `abrir()`: un aviso que no se
puede poner es una pareja que se recorre, no un agente caído.
"""

from __future__ import annotations

import ctypes
import errno
import os
import re
import struct
import sys
import threading
from pathlib import Path
from typing import NamedTuple

from .huella import se_ignora

ES_LINUX = sys.platform.startswith("linux")

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


def abrir() -> Inotify | None:
    """Abre el motor de avisos de este sistema.

    Returns:
        El motor, o `None` donde no lo hay (fuera de Linux).

    Raises:
        OSError: Si el sistema no deja abrir un descriptor de inotify (se han
            acabado los de este usuario, `fs.inotify.max_user_instances`).
    """
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

    def descartar(self, clave: tuple[str, str]) -> None:
        """Tira lo que ha llegado de una pareja: lo escribió su propia pasada."""
        self.leer()
        with self._cerrojo:
            self._pendientes.pop(clave, None)

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
