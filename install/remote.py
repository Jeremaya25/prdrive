#!/usr/bin/env python3
"""El `rclone.conf` efímero y el catálogo de parejas.

El instalador tiene que hablar con el remoto antes de que exista ningún
dispositivo, así que no puede usar el `rclone.conf` del dispositivo ni su
`keys/`: se los fabrica en un directorio temporal a partir del `Profile` que
lleva (ver `install/profile.py`) y los borra al salir.

Un perfil sin clave privada es perfectamente válido (un webdav con contraseña,
un sftp con agente) y entonces `EphemeralConf` solo escribe el conf. Lo que hay
que proteger es la clave cuando la hay, y de eso van las tres precauciones de
aquí: un directorio por proceso con su `owner.pid`, sobrescribir antes de
borrar y `sweep_stale()` para lo que dejó un instalador al que mataron duro.

Lo que se lanza contra rclone pasa siempre por `Rclone`, que admite un runner
inyectado: permite probar cómo se construye cada orden sin que ningún test
toque la red.
"""

from __future__ import annotations

import atexit
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from common import catalog, config_file, model
from common.model import ConfigError
from common.store import pid_alive

from . import CREATE_NO_WINDOW, IS_WIN, InstallError
from .profile import Profile, render_conf

TMP_PREFIX = "prdrive-key-"
"""Prefijo de los directorios temporales con la clave."""
OWNER_FILE = "owner.pid"
"""Fichero de cada directorio temporal con el pid de su dueño."""


def sweep_stale(base: Path | None = None) -> int:
    """Borra los directorios de clave que dejaron instaladores ya muertos.

    Hace falta porque un kill DURO (SIGKILL, o `TerminateProcess` en Windows)
    no deja correr ni `atexit` ni los manejadores de señal, y ahí se queda la
    clave. Cada directorio dice de qué pid es, así que el de un instalador que
    siga vivo (dos instalaciones a la vez) no se toca.

    Returns:
        Cuántos directorios ha borrado.
    """
    base = base or Path(tempfile.gettempdir())
    borrados = 0
    for viejo in base.glob(TMP_PREFIX + "*"):
        try:
            duenno = int((viejo / OWNER_FILE).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            duenno = None                       # sin dueño legible: es basura
        if duenno is not None and pid_alive(duenno):
            continue
        shutil.rmtree(viejo, ignore_errors=True)
        borrados += 1
    return borrados


_ABIERTAS: list["EphemeralConf"] = []
"""Los `EphemeralConf` abiertos, para cerrarlos al salir."""


class EphemeralConf:
    """Clave, known_hosts y `rclone.conf` en un temporal, borrado al cerrar.

    Vive todo lo que dure la sesión del asistente y no una orden suelta: rclone
    se invoca muchas veces y regenerar la clave en cada una no la protegería
    más, solo la escribiría más veces.

    Args:
        profile: La conexión.
        base: Carpeta donde crear el temporal; por defecto, el temporal del
            sistema.

    Attributes:
        dir: El directorio temporal.
        key_file: Dónde está la clave privada.
        known_file: Dónde están los known_hosts.
        conf_file: El `rclone.conf`.
    """

    def __init__(self, profile: Profile, base: Path | None = None) -> None:
        """Crea el temporal y escribe la clave, los known_hosts y el conf.

        Raises:
            InstallError: Si el perfil no da un `rclone.conf` válido
                (`render_conf`). No queda nada escrito: el conf se genera antes
                que la clave, y ante cualquier fallo se borra el directorio.
        """
        base = base or Path(tempfile.gettempdir())
        base.mkdir(parents=True, exist_ok=True)
        self.dir = Path(tempfile.mkdtemp(prefix=TMP_PREFIX, dir=base))
        self.profile = profile
        self.key_file = self.dir / profile.key_name
        self.known_file = self.dir / "known_hosts"
        self.conf_file = self.dir / "rclone.conf"

        try:
            # El conf va primero: si se rechaza, la clave ni llega a escribirse.
            texto = self._conf_text()
            (self.dir / OWNER_FILE).write_text(str(os.getpid()), encoding="utf-8")
            if profile.private_key is not None:
                self.key_file.write_bytes(profile.private_key)
                try:
                    self.key_file.chmod(0o600)
                except OSError:
                    pass    # Windows: los permisos POSIX no aplican; el temp ya es del usuario
            if profile.known_hosts:
                self.known_file.write_text(profile.known_hosts, encoding="utf-8")
            self.conf_file.write_text(texto, encoding="utf-8")
        except BaseException:
            self.close()        # sin esto la clave quedaría sin dueño que la barra
            raise
        _ABIERTAS.append(self)

    def _conf_text(self) -> str:
        """Devuelve el conf del perfil con las rutas de ESTE temporal.

        Cada ruta se pasa solo si hay algo que apuntar: un `key_file` que no
        existe hace fallar a rclone, mientras que no ponerlo deja que el
        backend se autentique como sepa (contraseña, agente, token).
        """
        return render_conf(
            self.profile,
            key_file=self.key_file if self.profile.private_key is not None else None,
            known_file=self.known_file if self.profile.known_hosts else None)


    @property
    def path(self) -> str:
        """Devuelve la ruta del `rclone.conf`."""
        return str(self.conf_file)

    def close(self) -> None:
        """Sobrescribe la clave antes de borrarla y se lleva el directorio.

        Sobrescribir no es ninguna garantía en un SSD ni en un sistema de
        ficheros con copia al escribir, donde el bloque original puede seguir
        ahí; sale gratis y evita el caso tonto de recuperarla con un undelete.
        """
        try:
            if self.key_file.is_file():
                self.key_file.write_bytes(b"\0" * self.key_file.stat().st_size)
        except OSError:
            pass
        shutil.rmtree(self.dir, ignore_errors=True)
        if self in _ABIERTAS:
            _ABIERTAS.remove(self)

    def __enter__(self) -> "EphemeralConf":
        """Devuelve el propio conf para usarlo con `with`."""
        return self

    def __exit__(self, *_exc) -> None:
        """Lo cierra al salir del `with`."""
        self.close()


def _cleanup_all() -> None:
    """Cierra todos los `EphemeralConf` abiertos."""
    for conf in list(_ABIERTAS):
        conf.close()


atexit.register(_cleanup_all)


def install_signal_handlers() -> None:
    """Hace que Ctrl-C y SIGTERM también borren la clave.

    Un kill duro no se puede interceptar; para ese caso está `sweep_stale()`,
    que limpia al arrancar lo que dejaron ejecuciones anteriores.
    """
    def _handler(signum, _frame):
        """Borra las claves y sale con 130 (SIGINT) o 143."""
        _cleanup_all()
        sys.exit(130 if signum == getattr(signal, "SIGINT", None) else 143)

    for nombre in ("SIGINT", "SIGTERM", "SIGBREAK", "SIGHUP"):
        sig = getattr(signal, nombre, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            pass        # p.ej. no estamos en el hilo principal


Runner = Callable[..., subprocess.CompletedProcess]
"""Función con la que se ejecuta una orden; los tests ponen la suya."""


def _default_runner(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Ejecuta una orden de rclone sin abrir ventana de consola en Windows."""
    # `CREATE_NO_WINDOW`: compilado con `--windowed` no hay consola, y sin esto
    # cada invocación de rclone abriría una ventana negra.
    if IS_WIN:
        kwargs.setdefault("creationflags", CREATE_NO_WINDOW)
    return subprocess.run(cmd, text=True, encoding="utf-8", errors="replace", **kwargs)


@dataclass
class Rclone:
    """Las órdenes de rclone del instalador, con su config efímero ya puesto.

    Args:
        binary: El ejecutable de rclone.
        conf: El `rclone.conf` efímero.
        runner: Con qué se ejecutan las órdenes; con uno de mentira los tests
            comprueban cómo se construye cada una sin tocar la red ni el disco.
        remote_name: Nombre del remote del conf. Viaja aquí porque convierte
            una ruta en un endpoint, y quien tiene el conf puesto es quien sabe
            cómo se llama el remote que hay dentro.
    """
    binary: str
    conf: str
    runner: Runner = field(default=_default_runner)
    remote_name: str = ""

    def command(self, *args: str) -> list[str]:
        """Devuelve la orden completa.

        La usa la ventana de salida, que la ejecuta ella.
        """
        return [str(self.binary), "--config", str(self.conf), *[str(a) for a in args]]

    def run(self, *args: str, capture: bool = False,
            timeout: float | None = None) -> subprocess.CompletedProcess:
        """Ejecuta una orden de rclone.

        Args:
            args: Argumentos tras `--config`.
            capture: Si se captura la salida.
            timeout: Segundos máximos.
        """
        kwargs: dict = {}
        if capture:
            kwargs["capture_output"] = True
        if timeout is not None:
            kwargs["timeout"] = timeout
        return self.runner(self.command(*args), **kwargs)

    def endpoint(self, path: str = "") -> str:
        """Devuelve `remote:ruta`, lo único que el proyecto sabe de un backend."""
        return f"{self.remote_name}:{path}"

    def check_connection(self, timeout: float = 45.0) -> None:
        """Comprueba que se llega al remoto.

        Raises:
            InstallError: Con lo que dijo rclone, o si no contesta a tiempo.
        """
        try:
            res = self.run("lsd", self.endpoint(), "--max-depth", "1",
                           capture=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            raise InstallError(
                f"El remoto '{self.remote_name}' no ha contestado en "
                f"{timeout:g}s.") from e
        if res.returncode != 0:
            raise InstallError(
                f"No se puede conectar con '{self.remote_name}':\n\n"
                f"{(res.stderr or '').strip()}")


@dataclass(frozen=True)
class Catalog:
    """El catálogo del remoto: el dict crudo y su cabecera de comentarios.

    Es crudo y no `model.Config` porque de aquí sale un TOML que hay que volver
    a escribir, y las `Pair` del modelo llegan con los `[defaults]` ya
    fundidos: volcarlas duplicaría los defaults dentro de cada pareja.

    Args:
        raw: El dict del TOML.
        head: Su cabecera de comentarios.
        endpoint: De dónde se leyó: `remote.toml` o, en un remoto sin
            renombrar, su `pairs.toml`.
    """
    raw: dict
    head: str
    endpoint: str = ""

    @property
    def pairs(self) -> list[dict]:
        """Devuelve las parejas del catálogo."""
        return list(self.raw.get("pair", []))

    @property
    def names(self) -> list[str]:
        """Devuelve los nombres de las parejas."""
        return [p.get("name", "") for p in self.pairs]

    def pair(self, name: str) -> dict | None:
        """Devuelve la pareja con ese nombre, o `None`."""
        for p in self.pairs:
            if p.get("name") == name:
                return p
        return None


def parse_catalog(text: str, endpoint: str = "") -> Catalog:
    """Convierte el texto del catálogo en un `Catalog`, validado.

    Se valida nada más leerlo y no cuando se use: un `mode` mal escrito en el
    catálogo tiene que reventar en el primer paso del asistente y no en el
    sexto, con el dispositivo ya sembrado.

    Args:
        text: El TOML.
        endpoint: De dónde se leyó, si se sabe.

    Raises:
        InstallError: Si no es TOML válido o no es un config válido.
    """
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise InstallError(f"El catálogo del remoto no es TOML válido: {e}") from e
    try:
        model.parse_config(raw)
    except ConfigError as e:
        raise InstallError(f"El catálogo del remoto no es un config válido:\n\n{e}") from e
    return Catalog(raw, config_file.header_of(text), endpoint)


def pull_catalog(rclone: Rclone, catalog_path: str,
                 timeout: float = 45.0) -> Catalog:
    """Se trae el catálogo del remoto.

    Con la regla de los dos nombres del dispositivo (`catalog.leer()`): da igual
    que la ruta diga `remote.toml` o `pairs.toml`, se lee el que haya.

    Si la ruta es una carpeta, `rclone cat` no falla sino que lo junta todo, y
    el error que saldría (TOML inválido, dos `[defaults]`) no dice la causa. El
    diagnóstico es el del dispositivo, `catalog.explicar_carpeta()`: uno solo
    para los dos lectores y sin ninguna pregunta más en el camino bueno.

    Raises:
        InstallError: Si no contesta, no se puede leer o no es un catálogo
            válido.
    """
    pedido = rclone.endpoint(catalog_path)

    def ejecutar(args: list[str]) -> subprocess.CompletedProcess:
        """Ejecuta una orden de rclone capturando la salida."""
        return rclone.run(*args, capture=True, timeout=timeout)

    try:
        res, donde = catalog.leer(ejecutar, pedido)
    except subprocess.TimeoutExpired as e:
        raise InstallError(
            f"El remoto no ha servido el catálogo en {timeout:g}s.") from e
    if res.returncode != 0:
        raise InstallError(catalog.motivo_lectura(pedido, donde, res, ":\n\n"))
    texto = res.stdout or ""

    try:
        leido = parse_catalog(texto, donde)
    except InstallError as e:
        carpeta = catalog.explicar_carpeta(ejecutar, donde, fallo=True)
        if carpeta is None:
            raise
        raise InstallError(carpeta) from e
    carpeta = catalog.explicar_carpeta(ejecutar, donde)
    if carpeta:
        raise InstallError(carpeta)
    return leido
