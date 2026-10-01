#!/usr/bin/env python3
"""La conexión de este dispositivo, empaquetada para llevársela a otro aparato.

Hoy ese aparato es un móvil que la lee de un código QR en pantalla. El
dispositivo ya tiene todo lo necesario para hablar con el remoto (su
`rclone.conf` y su clave en `keys/`); un móvil no puede enchufarse a él y
teclear a mano el host, el usuario y una clave privada de 400 bytes no es una
opción. Se enseña en pantalla y se lee con la cámara, que es lo único que los
dos aparatos tienen en común.

El formato es el de `install/profile.py`, a propósito: la carga es el TOML que
escribe `profile.dumps()` con tres claves más (la marca, la clave privada en
base64 y los known_hosts). Como esas tres le sobran a `profile.loads()`, el
MISMO texto se le puede pasar tal cual:

    carga = pairing.leer(texto)
    perfil = profile.loads(carga.texto, private_key=carga.private_key,
                           known_hosts=carga.known_hosts)

No se inventa un formato nuevo porque ya hay uno que sabe leer el instalador y
dos formatos para lo mismo acabarían separándose; `tests/test_qr.py` da la
vuelta completa y lo impide.

Vive en `common/` y no en `install/` porque `install/` no viaja al dispositivo
y esto lo ejecuta la ventana de Doctor con el dispositivo puesto y sin red. Por
la misma razón `parse_rclone_conf()` está aquí y `install/profile.py` lo
importa: es el único lector de `rclone.conf` del proyecto.

La carga lleva la clave privada dentro: no se guarda en ningún fichero, no se
copia al portapapeles y no sale de la pantalla. `construir()` devuelve texto y
quien lo llama lo dibuja y avisa.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from . import config_file, model
from .catalog import DEFAULT_CATALOG_PATH

MARCA = "prdrive"
"""Marca que va dentro de la carga para que el lector rechace un QR que no es nuestro.

Una cámara apuntando a una pantalla lee lo que le pongan delante, y «este
código no es de prdrive» es mucho mejor mensaje que el error de conectar con
una URL.
"""
FORMATO = 1
"""Versión del formato de la carga."""

RUTAS_DERIVADAS = ("key_file", "known_hosts_file")
"""Opciones de rclone.conf que no viajan en la carga.

Son rutas del disco de quien las escribió y en el aparato que las recibe valen
otra cosa. Es la misma regla, y la misma lista, que `profile.RUTAS_DERIVADAS`.
"""


class PairingError(model.ConfigError):
    """No se puede montar la carga: falta el `rclone.conf`, el remote o la clave.

    Hereda de `ConfigError` porque es lo mismo que le pasa al resto del
    proyecto (un dispositivo mal montado o a medio provisionar) y, como ella,
    no mata el proceso: esto lo abre una ventana.
    """


def parse_rclone_conf(text: str) -> dict[str, dict[str, str]]:
    """Devuelve `{nombre: {opción: valor}}` de un `rclone.conf`.

    Se lee a mano y no con `configparser` porque rclone escribe algún valor con
    `%` dentro (las plantillas de nombre) y `configparser` lo interpreta como
    interpolación y revienta. Basta entender una cabecera entre corchetes y
    `clave = valor`.
    """
    remotes: dict[str, dict[str, str]] = {}
    actual: dict[str, str] | None = None
    for linea in text.splitlines():
        linea = linea.strip()
        if not linea or linea.startswith(("#", ";")):
            continue
        if linea.startswith("[") and linea.endswith("]"):
            actual = {}
            remotes[linea[1:-1].strip()] = actual
            continue
        if actual is None or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        actual[clave.strip()] = valor.strip()
    return remotes


@dataclass(frozen=True)
class Carga:
    """Lo que lleva un QR de emparejamiento, separado en sus piezas.

    Args:
        texto: La carga entera y sin tocar: TOML válido, lo que hay que pasar a
            `profile.loads()`.
        private_key: La clave privada, que se saca aparte porque `loads()` la
            recibe por parámetro (nunca ha estado dentro del perfil).
        known_hosts: Contenido de `known_hosts`, o vacío.
        remote_name: Nombre del remote.
    """
    texto: str
    private_key: bytes | None
    known_hosts: str
    remote_name: str


def nombre_del_remote(raw_local: Mapping[str, object] | None = None) -> str:
    """Devuelve cómo se llama en este dispositivo el remote que usan las parejas.

    Sale de `[defaults].remote` y no del `rclone.conf` porque es el catálogo
    quien decide ese nombre: todos los `remote_path` se resuelven contra él, y
    un `rclone.conf` puede definir más de una sección.
    """
    defaults = dict((raw_local or {}).get("defaults") or {})   # type: ignore[union-attr]
    return str(defaults.get("remote") or model.DEFAULT_REMOTE)


def _ruta_del_catalogo(raw_local: Mapping[str, object] | None = None) -> str:
    """Devuelve `catalog_path` del dispositivo, o el de fábrica."""
    defaults = dict((raw_local or {}).get("defaults") or {})   # type: ignore[union-attr]
    return str(defaults.get("catalog_path") or DEFAULT_CATALOG_PATH)


def _leer_relativa(valor: str, app: Path) -> Path:
    """Resuelve una ruta del `rclone.conf` como la resuelve rclone.

    Es relativa al directorio de la aplicación, el `cwd` con el que todo el
    proyecto ejecuta rclone: es lo que hace portable al dispositivo y lo que
    hay que repetir aquí para encontrar la clave.
    """
    ruta = Path(valor).expanduser()
    return ruta if ruta.is_absolute() else app / ruta


def construir(raw_local: Mapping[str, object] | None = None,
              app_dir: Path | None = None) -> str:
    """Devuelve el texto que va dentro del QR, leído del dispositivo que lo enseña.

    Args:
        raw_local: El `sync_config.toml` en crudo, de donde salen el nombre del
            remote y la ruta del catálogo; si no se da, se lee.
        app_dir: Carpeta de la aplicación; por defecto la de verdad (el
            parámetro es para los tests).

    Raises:
        PairingError: Si falta el `rclone.conf`, el remote o la clave.
    """
    app = app_dir or model.APP_DIR
    if raw_local is None:
        raw_local = config_file.load_raw(app / "sync_config.toml")

    conf = app / "rclone.conf"
    try:
        texto_conf = conf.read_text(encoding="utf-8")
    except OSError as e:
        raise PairingError(
            f"Este dispositivo no tiene conexión que compartir: no puedo leer "
            f"{conf} ({e}).") from e

    remotes = parse_rclone_conf(texto_conf)
    nombre = nombre_del_remote(raw_local)
    if nombre not in remotes:
        tiene = ", ".join(sorted(remotes)) or "ninguno"
        raise PairingError(
            f"El rclone.conf del dispositivo no define el remote '{nombre}', "
            f"que es el que usan las parejas. Define: {tiene}.")

    opciones = dict(remotes[nombre])
    clave: bytes | None = None
    key_name = "id_ed25519"
    conocidos = ""

    key_file = opciones.get("key_file", "")
    if key_file:
        ruta = _leer_relativa(key_file, app)
        try:
            clave = ruta.read_bytes()
        except OSError as e:
            raise PairingError(
                f"El rclone.conf apunta a la clave {ruta}, pero no puedo "
                f"leerla: {e}.") from e
        key_name = ruta.name

    known = opciones.get("known_hosts_file", "")
    if known:
        try:
            conocidos = _leer_relativa(known, app).read_text(encoding="utf-8")
        except OSError:
            conocidos = ""      # sin known_hosts se sigue: es TOFU, no un fallo

    for derivada in RUTAS_DERIVADAS:
        opciones.pop(derivada, None)

    return dumps(nombre, opciones, key_name=key_name,
                 catalog_path=_ruta_del_catalogo(raw_local),
                 private_key=clave, known_hosts=conocidos)


def dumps(remote_name: str, options: Mapping[str, str], *, key_name: str,
          catalog_path: str, private_key: bytes | None = None,
          known_hosts: str = "") -> str:
    """Devuelve el TOML de la carga.

    El orden importa y no es estético: las claves sueltas van TODAS antes de
    `[options]`, porque en TOML lo que viene después de una cabecera de tabla
    pertenece a esa tabla y una línea traspapelada metería la clave privada en
    las opciones del backend, y de ahí en el `rclone.conf` del móvil.
    """
    cabeza: dict[str, object] = {
        MARCA: FORMATO,
        "remote_name": remote_name,
        "key_name": key_name,
        "catalog_path": catalog_path,
    }
    if private_key is not None:
        cabeza["private_key_b64"] = base64.b64encode(private_key).decode("ascii")
    if known_hosts.strip():
        cabeza["known_hosts"] = known_hosts

    limpias = {k: str(v) for k, v in options.items() if k not in RUTAS_DERIVADAS}
    return (config_file.dumps_table(cabeza) + "\n[options]\n"
            + config_file.dumps_table(limpias))


def leer(texto: str) -> Carga:
    """Comprueba que la carga es nuestra y separa lo que no es perfil.

    En producción lo hace el móvil, en Kotlin. Vive aquí porque es la
    definición ejecutable del formato (lo que el lado Kotlin tiene que
    reproducir) y permite probar la vuelta entera sin cámara.

    Raises:
        PairingError: Si no es TOML válido, no es de prdrive, es de otro
            formato o la clave no es base64.
    """
    import tomllib
    try:
        raw = tomllib.loads(texto)
    except tomllib.TOMLDecodeError as e:
        raise PairingError(f"El código no lleva un TOML válido: {e}") from e

    version = raw.get(MARCA)
    if version is None:
        raise PairingError("Este código no es de prdrive.")
    if version != FORMATO:
        raise PairingError(
            f"Este código es del formato {version} y aquí se entiende el "
            f"{FORMATO}: actualiza el aparato más antiguo de los dos.")

    b64 = str(raw.get("private_key_b64", "") or "")
    clave: bytes | None = None
    if b64:
        try:
            clave = base64.b64decode(b64, validate=True)
        except (ValueError, base64.binascii.Error) as e:   # type: ignore[attr-defined]
            raise PairingError(f"La clave del código no es base64 válido: {e}") from e

    return Carga(texto=texto, private_key=clave,
                 known_hosts=str(raw.get("known_hosts", "") or ""),
                 remote_name=str(raw.get("remote_name", "") or ""))
