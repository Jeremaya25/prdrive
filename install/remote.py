#!/usr/bin/env python3
"""
remote.py — La clave del NAS, el rclone.conf efímero y el catálogo de parejas.

El instalador tiene que hablar con el NAS antes de que exista ningún pen, así que
no puede usar el `rclone.conf` del pen ni su `keys/`: se los fabrica en un
directorio temporal a partir de una clave que viaja con él, y los borra al salir.

De dónde sale esa clave, en orden:

    1. `install/secret.py`, que genera `build_installer.py` al compilar el .exe.
       Es el caso normal del binario que se comparte.
    2. `keys/synology_ed25519` junto al instalador, cuando se ejecuta el .py
       desde un pen ya provisionado. Es el caso de desarrollo.
    3. Ninguno: se explica qué falta y no se sigue.

Así el fuente se puede versionar sin llevar el secreto dentro. El marcador
`__INJECT` existe para que una compilación mal hecha falle diciendo por qué en
vez de intentar conectarse con una clave de mentira.

Lo que se lanza contra rclone pasa siempre por `Rclone`, que admite un runner
inyectado: es lo que permite probar cómo se construye cada orden sin que ningún
test toque la red.
"""

from __future__ import annotations

import atexit
import base64
import binascii
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

from . import (CATALOG_PATH, CREATE_NO_WINDOW, IS_WIN, NAS_HOST, NAS_PORT,
               NAS_USER, REMOTE_NAME, InstallError, bundle_dir)

INJECT_MARKER = "__INJECT"
KEY_NAME = "synology_ed25519"
TMP_PREFIX = "perepen-key-"
OWNER_FILE = "owner.pid"


# ---------------------------------------------------------------------------
# Credenciales
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Credentials:
    """La clave privada y los known_hosts, más de dónde han salido.

    El origen no es adorno: es lo que el paso de comprobaciones enseña para que
    se vea si el .exe lleva la clave dentro o la está cogiendo de un pen."""
    private_key: bytes
    known_hosts: str
    origen: str


def _from_secret_module() -> Credentials | None:
    """Lo que inyectó `build_installer.py`, si es que se compiló con clave."""
    try:
        from . import secret            # type: ignore[attr-defined]
    except ImportError:
        return None

    b64 = getattr(secret, "PRIVATE_KEY_B64", "")
    if not b64 or b64.startswith(INJECT_MARKER):
        raise InstallError(
            "Este instalador se compiló sin clave privada (quedó el marcador "
            f"{INJECT_MARKER}). Vuelve a compilarlo con build_installer.py "
            "desde un pen que tenga keys/.")
    try:
        clave = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise InstallError(f"La clave inyectada no es base64 válido: {e}") from e
    return Credentials(clave, getattr(secret, "KNOWN_HOSTS", ""), "incrustada en el instalador")


def _from_pen_keys() -> Credentials | None:
    """Las llaves del pen desde el que se está ejecutando el .py."""
    keys = bundle_dir() / "keys"
    key_file, known_file = keys / KEY_NAME, keys / "known_hosts"
    try:
        if not key_file.is_file():
            return None
        conocidos = known_file.read_text(encoding="utf-8") if known_file.is_file() else ""
        return Credentials(key_file.read_bytes(), conocidos, f"leída de {keys}")
    except OSError:
        return None


def load_credentials() -> Credentials:
    """La clave con la que hablar con el NAS, o un error que explica qué falta."""
    for fuente in (_from_secret_module, _from_pen_keys):
        creds = fuente()
        if creds is not None:
            return creds
    raise InstallError(
        "No encuentro la clave privada del NAS.\n\n"
        "Si estás ejecutando el .py, hazlo desde un pen ya provisionado, que la "
        f"tiene en keys/{KEY_NAME}.\n"
        "Si es el ejecutable, hay que compilarlo con build_installer.py, que la "
        "incrusta al generarlo.")


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

    def __init__(self, creds: Credentials, base: Path | None = None) -> None:
        base = base or Path(tempfile.gettempdir())
        base.mkdir(parents=True, exist_ok=True)
        self.dir = Path(tempfile.mkdtemp(prefix=TMP_PREFIX, dir=base))
        self.key_file = self.dir / KEY_NAME
        self.known_file = self.dir / "known_hosts"
        self.conf_file = self.dir / "rclone.conf"

        (self.dir / OWNER_FILE).write_text(str(os.getpid()), encoding="utf-8")
        self.key_file.write_bytes(creds.private_key)
        try:
            self.key_file.chmod(0o600)
        except OSError:
            pass    # Windows: los permisos POSIX no aplican; el temp ya es del usuario
        self.known_file.write_text(creds.known_hosts, encoding="utf-8")
        self.conf_file.write_text(self._conf_text(), encoding="utf-8")
        _ABIERTAS.append(self)

    def _conf_text(self) -> str:
        # disable_hashcheck / shell_type=none: el Synology no ofrece md5sum por
        # SSH y sin esto rclone pierde un rato largo intentando averiguarlo.
        lineas = [
            f"[{REMOTE_NAME}]",
            "type = sftp",
            f"host = {NAS_HOST}",
            f"port = {NAS_PORT}",
            f"user = {NAS_USER}",
            f"key_file = {self.key_file}",
            "disable_hashcheck = true",
            "shell_type = none",
        ]
        if self.known_file.stat().st_size:
            lineas.insert(6, f"known_hosts_file = {self.known_file}")
        return "\n".join(lineas) + "\n"

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
    construye cada orden sin tocar la red ni el disco."""
    binary: str
    conf: str
    runner: Runner = field(default=_default_runner)

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

    def check_connection(self, timeout: float = 45.0) -> None:
        """¿Se llega al NAS? Lanza InstallError con lo que dijo rclone."""
        try:
            res = self.run("lsd", f"{REMOTE_NAME}:", "--max-depth", "1",
                           capture=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            raise InstallError(
                f"El NAS ({NAS_HOST}) no ha contestado en {timeout:g}s.") from e
        if res.returncode != 0:
            raise InstallError(
                f"No se puede conectar con {NAS_HOST}:\n\n{(res.stderr or '').strip()}")


# ---------------------------------------------------------------------------
# El catálogo
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Catalog:
    """El pairs.toml del NAS: el dict crudo y su cabecera de comentarios.

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
    sexto, con el pen ya sembrado."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise InstallError(f"El catálogo del NAS no es TOML válido: {e}") from e
    try:
        model.parse_config(raw)
    except ConfigError as e:
        raise InstallError(f"El catálogo del NAS no es un config válido:\n\n{e}") from e
    return Catalog(raw, config_file.header_of(text))


def pull_catalog(rclone: Rclone, timeout: float = 45.0) -> Catalog:
    """Se trae el catálogo global de parejas del NAS."""
    try:
        res = rclone.run("cat", f"{REMOTE_NAME}:{CATALOG_PATH}",
                         capture=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise InstallError(
            f"El NAS no ha servido el catálogo en {timeout:g}s.") from e
    if res.returncode != 0:
        raise InstallError(
            f"No puedo leer el catálogo {CATALOG_PATH}:\n\n{(res.stderr or '').strip()}")
    return parse_catalog(res.stdout or "")
