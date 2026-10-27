"""El `rclone rcd` vivo con el que habla la ventana «Servidor…».

La ventana explora el remoto con un único `rclone rcd` residente, al que llama
por HTTP en 127.0.0.1 (una llamada por carpeta, sin pagar el arranque de rclone
cada vez). Este módulo sabe arrancarlo, esperarlo, llamarle y pararlo; no sabe
nada de qué se le pide.

Reglas que no se aflojan:
    - Solo escucha en `127.0.0.1`, en un puerto que da el sistema, y siempre con
      usuario y contraseña. Van en el entorno del hijo (`RCLONE_RC_USER` y
      `RCLONE_RC_PASS`), nunca en su línea de órdenes, que otro proceso del equipo
      puede leer.
    - Su stderr va a un fichero temporal del equipo, nunca a una tubería: `rcd`
      escribe avisos sin parar y una tubería que nadie lee acaba bloqueándolo.
    - `peticion` no usa el proxy del sistema: es el bucle local.
    - Está apuntado en `store` mientras vive, para que `store.matar_hijos()` lo
      corte al cerrar la ventana o antes de expulsar la unidad.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from typing import IO, Any

from . import catalog, model, store
from .model import ConfigError

ESPERA_ARRANQUE = 10.0  # segundos hasta que `rc/noop` contesta
ESPERA_QUIT = 3.0       # segundos que se le dan a salir tras `core/quit` antes de matarlo
TIMEOUT_PETICION = 60.0  # segundos por llamada
SONDEO = 0.1            # segundos entre dos `rc/noop` mientras arranca

_FRASES_PUERTO_OCUPADO = ("address already in use", "only one usage of each socket address")
"""Cómo dice rclone, en minúsculas, que el puerto ya lo tiene otro (Linux y Windows)."""


class PuertoOcupado(ConfigError):
    """Otro proceso se quedó con el puerto entre elegirlo y arrancar `rcd`."""


class RcdCaido(Exception):
    """El `rcd` no contesta: ha salido, se ha cortado la conexión o se agotó el tiempo."""


class ErrorRc(Exception):
    """`rcd` contestó con un error.

    Attributes:
        mensaje: El campo `error` de la respuesta, o el texto si no era JSON.
        estado: El estado HTTP de la respuesta.
    """

    def __init__(self, mensaje: str, estado: int) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.estado = estado


def puerto_libre() -> int:
    """Pide al sistema un puerto libre del bucle local.

    Returns:
        El puerto. Queda libre al devolverlo, así que otro proceso puede
        cogerlo antes de que `rcd` lo abra (`PuertoOcupado`).
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _opciones_popen(stderr: IO[bytes] | int) -> dict[str, Any]:
    """Los argumentos con los que `lanzar` crea el proceso.

    Args:
        stderr: A dónde va el stderr del hijo.

    Returns:
        Los argumentos con nombre de `subprocess.Popen`: en la carpeta del
        programa (donde `rclone.conf` usa rutas relativas), sin entrada ni salida
        estándar, y sin consola en Windows o en su propia sesión en POSIX.
    """
    opciones: dict[str, Any] = {
        "cwd": str(model.APP_DIR), "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL, "stderr": stderr}
    if os.name == "nt":
        opciones["creationflags"] = model.CREATE_NO_WINDOW
    else:
        opciones["start_new_session"] = True
    return opciones


def lanzar(orden: list[str], entorno: dict[str, str], stderr: IO[bytes] | int) -> subprocess.Popen:
    """Crea el proceso de `rcd`; es el punto que sustituyen los tests.

    Args:
        orden: La línea de órdenes completa, binario incluido.
        entorno: El entorno del hijo, con las credenciales.
        stderr: El fichero al que va su stderr.
    """
    return subprocess.Popen(orden, env=entorno, **_opciones_popen(stderr))


def peticion(url: str, cuerpo: bytes, cabeceras: dict[str, str],
             timeout: float) -> tuple[int, str]:
    """Hace un POST sin pasar por el proxy del sistema; es el punto que sustituyen los tests.

    Args:
        url: La dirección completa.
        cuerpo: El cuerpo de la petición.
        cabeceras: Las cabeceras.
        timeout: Segundos antes de darla por perdida.

    Returns:
        El estado HTTP y el cuerpo. Un estado de error (404, 500…) también se
        devuelve: no es una excepción.

    Raises:
        RcdCaido: Si no se puede hablar con el servidor.
    """
    abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    solicitud = urllib.request.Request(url, data=cuerpo, headers=cabeceras, method="POST")
    try:
        with abridor.open(solicitud, timeout=timeout) as respuesta:
            return respuesta.status, respuesta.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        with e:
            return e.code, e.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
        raise RcdCaido(f"rclone no contesta: {e}") from e


class Rcd:
    """Un `rclone rcd` lanzado.

    Args:
        proceso: El proceso, ya lanzado.
        url: Su dirección, `http://127.0.0.1:<puerto>/`.
        usuario: El usuario de su autenticación.
        clave: Su contraseña.
        stderr: El fichero temporal donde escribe su stderr.

    Attributes:
        proceso: El proceso de `rclone rcd`.
        url: Su dirección.
    """

    def __init__(self, proceso: subprocess.Popen, url: str, usuario: str, clave: str,
                 stderr: IO[bytes]) -> None:
        self.proceso = proceso
        self.url = url
        self._stderr = stderr
        autorizacion = base64.b64encode(f"{usuario}:{clave}".encode()).decode("ascii")
        self._cabeceras = {"Content-Type": "application/json",
                           "Authorization": f"Basic {autorizacion}"}

    @property
    def vivo(self) -> bool:
        """Si el proceso sigue en marcha."""
        return self.proceso.poll() is None

    def _salida_de_error(self) -> str:
        """Lo que escribió el proceso en su stderr."""
        try:
            self._stderr.flush()
            self._stderr.seek(0)
            return self._stderr.read().decode("utf-8", errors="replace").strip()
        except (OSError, ValueError):
            return ""

    def esperar(self, tope: float = ESPERA_ARRANQUE) -> None:
        """Espera a que `rcd` conteste a `rc/noop`.

        Args:
            tope: Segundos máximos de espera.

        Raises:
            PuertoOcupado: Si el proceso salió porque el puerto ya estaba cogido.
            ConfigError: Si salió por otra razón (con su stderr en el mensaje) o
                no contestó a tiempo.
        """
        limite = time.monotonic() + tope
        while True:
            if not self.vivo:
                salida = self._salida_de_error()
                if any(f in salida.lower() for f in _FRASES_PUERTO_OCUPADO):
                    raise PuertoOcupado("El puerto que se eligió para rclone ya lo usa otro programa.")
                raise ConfigError(f"rclone no ha podido arrancar:\n\n{salida}")
            try:
                self.llamar("rc/noop")
                return
            except (RcdCaido, ErrorRc):
                pass
            if time.monotonic() >= limite:
                raise ConfigError(f"rclone no ha contestado en {tope:g} s.")
            time.sleep(SONDEO)

    def llamar(self, metodo: str, params: dict | None = None) -> dict:
        """Llama a un método de la API de `rcd`.

        Args:
            metodo: El método, p. ej. `operations/list`.
            params: Sus parámetros.

        Returns:
            La respuesta, ya como diccionario.

        Raises:
            ErrorRc: Si rclone contesta con un error.
            RcdCaido: Si no se puede hablar con `rcd`.
        """
        estado, texto = peticion(
            f"{self.url}{metodo}", json.dumps(params or {}).encode("utf-8"),
            self._cabeceras, TIMEOUT_PETICION)
        try:
            datos = json.loads(texto) if texto.strip() else {}
        except ValueError:
            datos = None
        if estado != 200:
            mensaje = datos.get("error") if isinstance(datos, dict) else None
            raise ErrorRc(str(mensaje or texto.strip() or f"HTTP {estado}"), estado)
        if not isinstance(datos, dict):
            raise ErrorRc("rclone contestó algo que no se puede leer", estado)
        return datos

    def parar(self) -> None:
        """Pide a `rcd` que salga y, si no lo hace a tiempo, lo mata; no lanza nunca."""
        try:
            self.llamar("core/quit")
        except (RcdCaido, ErrorRc):
            pass
        try:
            self.proceso.wait(timeout=ESPERA_QUIT)
        except subprocess.TimeoutExpired:
            pass
        try:
            if self.proceso.poll() is None:
                self.proceso.kill()
                self.proceso.wait(timeout=ESPERA_QUIT)
        except (OSError, subprocess.SubprocessError):
            pass
        store.soltar_hijo(self.proceso)
        try:
            self._stderr.close()
        except OSError:
            pass


def arrancar() -> Rcd:
    """Lanza `rclone rcd` en un puerto libre del bucle local, sin esperar a que esté listo.

    Hay que llamarla desde el hilo de Tk: lanzar el hijo no bloquea y lo que
    tarda es `Rcd.esperar()`, que sí va a un hilo.

    Returns:
        El `Rcd`, apuntado en `store` para que `store.matar_hijos()` lo corte.

    Raises:
        ConfigError: Si no hay rclone o el sistema no deja ejecutarlo.
    """
    binario = catalog._binary()
    puerto = puerto_libre()
    usuario, clave = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    orden = [binario, "rcd", "--config", str(model.RCLONE_CONF),
             "--rc-addr", f"127.0.0.1:{puerto}", *catalog.NET_FLAGS]
    entorno = {**os.environ, "RCLONE_RC_USER": usuario, "RCLONE_RC_PASS": clave}
    stderr = tempfile.TemporaryFile()
    try:
        proceso = lanzar(orden, entorno, stderr)
    except OSError as e:
        stderr.close()
        raise ConfigError(f"No se puede ejecutar rclone: {e}") from e
    except BaseException:
        stderr.close()
        raise
    store.apuntar_hijo(proceso)
    return Rcd(proceso, f"http://127.0.0.1:{puerto}/", usuario, clave, stderr)
