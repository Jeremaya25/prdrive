#!/usr/bin/env python3
"""
remote.py — El rclone.conf efímero y el catálogo de parejas.

El instalador tiene que hablar con el remoto antes de que exista ningún
dispositivo, así que no puede usar el `rclone.conf` del dispositivo ni su
`keys/`: se los fabrica en un directorio temporal a partir del `Profile` que
lleva (ver `install/profile.py`), y los borra al salir.

Un perfil sin clave privada es perfectamente válido —un webdav con contraseña, un
sftp con agente— y entonces `EphemeralConf` solo escribe el conf. Lo que hay que
proteger es la clave cuando la hay, y de eso van las tres precauciones de aquí:
un directorio por proceso con su `owner.pid`, sobrescribir antes de borrar, y
`sweep_stale()` para lo que dejó un instalador al que mataron duro.

Lo que se lanza contra rclone pasa siempre por `Rclone`, que admite un runner
inyectado: es lo que permite probar cómo se construye cada orden sin que ningún
test toque la red.
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

from common import config_file, model
from common.model import ConfigError
from common.store import pid_alive

from . import CREATE_NO_WINDOW, IS_WIN, InstallError
from .profile import Profile, render_conf

TMP_PREFIX = "prdrive-key-"
OWNER_FILE = "owner.pid"


# ---------------------------------------------------------------------------
# El rclone.conf efímero
# ---------------------------------------------------------------------------

def sweep_stale(base: Path | None = None) -> int:
    """Borra los directorios de clave que dejaron instaladores ya muertos.

    Hace falta porque un kill DURO (SIGKILL, o TerminateProcess en Windows) no
    deja correr ni atexit ni los manejadores de señal, y ahí se queda la clave.
    Cada directorio dice de qué pid es, así que uno de un instalador que siga
    vivo —dos instalaciones a la vez— no se toca."""
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


class EphemeralConf:
    """Clave + known_hosts + rclone.conf en un temporal, borrado al cerrar.

    Vive todo lo que dure la sesión del asistente y no una orden suelta: rclone
    se invoca muchas veces y regenerar la clave en cada una no la protegería más,
    solo la escribiría más veces."""

    def __init__(self, profile: Profile, base: Path | None = None) -> None:
        base = base or Path(tempfile.gettempdir())
        base.mkdir(parents=True, exist_ok=True)
        self.dir = Path(tempfile.mkdtemp(prefix=TMP_PREFIX, dir=base))
        self.profile = profile
        self.key_file = self.dir / profile.key_name
        self.known_file = self.dir / "known_hosts"
        self.conf_file = self.dir / "rclone.conf"

        (self.dir / OWNER_FILE).write_text(str(os.getpid()), encoding="utf-8")
        if profile.private_key is not None:
            self.key_file.write_bytes(profile.private_key)
            try:
                self.key_file.chmod(0o600)
            except OSError:
                pass    # Windows: los permisos POSIX no aplican; el temp ya es del usuario
        if profile.known_hosts:
            self.known_file.write_text(profile.known_hosts, encoding="utf-8")
        self.conf_file.write_text(self._conf_text(), encoding="utf-8")
        _ABIERTAS.append(self)

    def _conf_text(self) -> str:
        """El conf del perfil, con las rutas de ESTE temporal.

        Cada ruta se pasa solo si hay algo que apuntar: un `key_file` que no
        existe hace fallar a rclone, mientras que no ponerlo deja que el backend
        se autentique como sepa —contraseña, agente, token—."""
        return render_conf(
            self.profile,
            key_file=self.key_file if self.profile.private_key is not None else None,
            known_file=self.known_file if self.profile.known_hosts else None)


    @property
    def path(self) -> str:
        return str(self.conf_file)

    def close(self) -> None:
        """Sobrescribe la clave antes de borrarla y se lleva el directorio.

        Sobrescribir no es ninguna garantía en un SSD ni en un sistema de
        ficheros con copia al escribir, donde el bloque original puede seguir
        ahí; es solo que sale gratis y evita el caso tonto de recuperarla con un
        undelete."""
        try:
            if self.key_file.is_file():
                self.key_file.write_bytes(b"\0" * self.key_file.stat().st_size)
        except OSError:
            pass
        shutil.rmtree(self.dir, ignore_errors=True)
        if self in _ABIERTAS:
            _ABIERTAS.remove(self)

    def __enter__(self) -> "EphemeralConf":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def _cleanup_all() -> None:
    for conf in list(_ABIERTAS):
        conf.close()


atexit.register(_cleanup_all)


def install_signal_handlers() -> None:
    """Ctrl-C y SIGTERM también tienen que borrar la clave.

    Un kill duro no se puede interceptar; para ese caso está `sweep_stale()`,
    que limpia al arrancar lo que dejaron ejecuciones anteriores."""
    def _handler(signum, _frame):
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


# ---------------------------------------------------------------------------
# Hablar con rclone
# ---------------------------------------------------------------------------

Runner = Callable[..., subprocess.CompletedProcess]


def _default_runner(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    # CREATE_NO_WINDOW: compilado con --windowed no hay consola, y sin esto cada
    # invocación de rclone abriría una ventana negra en la cara del usuario.
    if IS_WIN:
        kwargs.setdefault("creationflags", CREATE_NO_WINDOW)
    return subprocess.run(cmd, text=True, encoding="utf-8", errors="replace", **kwargs)


@dataclass
class Rclone:
    """Las órdenes de rclone del instalador, con su config efímero ya puesto.

    `runner` está para los tests: con uno de mentira se comprueba cómo se
    construye cada orden sin tocar la red ni el disco. `remote_name` viaja aquí
    porque es lo que convierte una ruta en un endpoint, y quien tiene el conf
    puesto es quien sabe cómo se llama el remote que hay dentro."""
    binary: str
    conf: str
    runner: Runner = field(default=_default_runner)
    remote_name: str = ""

    def command(self, *args: str) -> list[str]:
        """La orden completa. La usa la ventana de salida, que la ejecuta ella."""
        return [str(self.binary), "--config", str(self.conf), *[str(a) for a in args]]

    def run(self, *args: str, capture: bool = False,
            timeout: float | None = None) -> subprocess.CompletedProcess:
        kwargs: dict = {}
        if capture:
            kwargs["capture_output"] = True
        if timeout is not None:
            kwargs["timeout"] = timeout
        return self.runner(self.command(*args), **kwargs)

    def endpoint(self, path: str = "") -> str:
        """'remote:ruta'. Es lo único que el proyecto sabe de un backend."""
        return f"{self.remote_name}:{path}"

    def check_connection(self, timeout: float = 45.0) -> None:
        """¿Se llega al remoto? Lanza InstallError con lo que dijo rclone."""
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


# ---------------------------------------------------------------------------
# El catálogo
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Catalog:
    """El pairs.toml del remoto: el dict crudo y su cabecera de comentarios.

    Crudo y no `model.Config` porque de aquí sale un TOML que hay que volver a
    escribir, y las `Pair` del modelo llegan con los `[defaults]` ya fundidos:
    volcarlas duplicaría los defaults dentro de cada pareja."""
    raw: dict
    head: str

    @property
    def pairs(self) -> list[dict]:
        return list(self.raw.get("pair", []))

    @property
    def names(self) -> list[str]:
        return [p.get("name", "") for p in self.pairs]

    def pair(self, name: str) -> dict | None:
        for p in self.pairs:
            if p.get("name") == name:
                return p
        return None


def parse_catalog(text: str) -> Catalog:
    """Texto del catálogo -> Catalog, validado.

    Se valida aquí, nada más leerlo, y no cuando se use: un `mode` mal escrito en
    el catálogo tiene que reventar en el primer paso del asistente y no en el
    sexto, con el dispositivo ya sembrado."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise InstallError(f"El catálogo del remoto no es TOML válido: {e}") from e
    try:
        model.parse_config(raw)
    except ConfigError as e:
        raise InstallError(f"El catálogo del remoto no es un config válido:\n\n{e}") from e
    return Catalog(raw, config_file.header_of(text))


def pull_catalog(rclone: Rclone, catalog_path: str,
                 timeout: float = 45.0) -> Catalog:
    """Se trae el catálogo global de parejas del remoto."""
    donde = rclone.endpoint(catalog_path)
    try:
        res = rclone.run("cat", donde, capture=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise InstallError(
            f"El remoto no ha servido el catálogo en {timeout:g}s.") from e
    if res.returncode != 0:
        raise InstallError(
            f"No puedo leer el catálogo {donde}:\n\n{(res.stderr or '').strip()}")
    return parse_catalog(res.stdout or "")
