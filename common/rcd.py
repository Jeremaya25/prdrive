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
    - No puede quedar huérfano con ficheros del dispositivo abiertos: además del
      cierre ordenado, muere con la ventana aunque esta caiga de golpe (un Job
      Object en Windows, `PR_SET_PDEATHSIG` en Linux) y, si aun así sobrevive uno,
      el siguiente arranque lo mata por lo apuntado en `state/rcd.json`.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
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


_PRCTL: Any = None
"""El puntero a `prctl` de libc, resuelto en el padre antes del `Popen` (`_resolver_prctl`)."""
PR_SET_PDEATHSIG = 1
"""La opción de `prctl` que pide una señal cuando muere el padre."""
_SIGKILL = getattr(signal, "SIGKILL", 9)
"""`SIGKILL` (9 en todo POSIX); Windows no tiene `signal.SIGKILL`, pero allí no se usa."""
_JOBS: list[Any] = []
"""Los handles de los Job Objects de Windows: viven tanto como el proceso, nunca se cierran."""


def fichero_estado() -> Path:
    """El fichero donde se apunta el `rcd` vivo: `state/rcd.json`.

    Es una función y no una constante porque los tests mueven `model.STATE_DIR`
    mientras corren.
    """
    return model.STATE_DIR / "rcd.json"


def limpiar_huerfano() -> int | None:
    """Mata el `rcd` que un proceso anterior dejó vivo y borra su apunte; no lanza nunca.

    Es el último cinturón: si la ventana cayó de golpe y ni el Job Object ni
    `PDEATHSIG` cortaron al hijo, `state/rcd.json` guarda su pid y su hora de
    creación. Solo se mata si ese pid sigue vivo **y** se creó a la hora apuntada
    (con un segundo de holgura, la precisión de `store.creado`): si no, el número
    lo heredó otro proceso y no se le toca. Si no se sabe la hora de creación
    tampoco se mata, por la misma razón. El fichero se borra siempre.

    Returns:
        El pid que se mató, o `None` si no había nada que matar.
    """
    ruta = fichero_estado()
    matado = None
    try:
        datos = store.read_json(ruta)
        pid, creado = datos.get("pid"), datos.get("creado")
        if (isinstance(pid, int) and not isinstance(pid, bool) and pid != os.getpid()
                and isinstance(creado, (int, float)) and not isinstance(creado, bool)
                and store.pid_alive(pid)):
            ahora = store.creado(pid)
            if ahora is not None and abs(ahora - creado) < 1.0:
                store.matar_arbol(pid)
                matado = pid
    except Exception:  # noqa: BLE001 — limpiar no puede impedir que arranque el siguiente
        matado = None
    try:
        store.borrar(ruta)
    except Exception:  # noqa: BLE001
        pass
    return matado


def _olvidar(pid: int | None) -> None:
    """Borra `state/rcd.json` si apunta a ese pid; si es de otro `rcd`, lo deja."""
    try:
        if pid is not None and store.read_json(fichero_estado()).get("pid") == pid:
            store.borrar(fichero_estado())
    except Exception:  # noqa: BLE001
        pass


def _resolver_prctl() -> Any:
    """Busca `prctl` en libc, **en el padre**, antes de lanzar el hijo.

    Returns:
        La función, o `None` si el sistema no la tiene (todo salvo Linux).
    """
    global _PRCTL
    if _PRCTL is None and sys.platform.startswith("linux"):
        try:
            import ctypes
            funcion = ctypes.CDLL(None, use_errno=True).prctl
            funcion.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                                ctypes.c_ulong, ctypes.c_ulong]
            funcion.restype = ctypes.c_int
            _PRCTL = funcion
        except (ImportError, OSError, AttributeError):
            _PRCTL = None
    return _PRCTL


def _morir_con_el_padre() -> None:
    """Pide al kernel un `SIGKILL` para este proceso cuando muera su padre (Linux).

    Es el `preexec_fn` del hijo, así que corre entre `fork` y `exec`: solo llama
    a un puntero que `_resolver_prctl` ya resolvió en el padre, sin importar nada
    ni reservar memoria. `PR_SET_PDEATHSIG` salta cuando muere el **hilo** que
    hizo el `fork`, no el proceso: por eso `arrancar()` tiene que correr en el
    hilo de Tk, que dura tanto como la ventana. Lanzado desde un hilo de trabajo
    que acabase, el `rcd` moriría a los pocos segundos.
    """
    if _PRCTL is not None:
        _PRCTL(PR_SET_PDEATHSIG, int(_SIGKILL), 0, 0, 0)


def atar_al_job(proceso: subprocess.Popen) -> bool:
    """Mete el proceso en un Job Object que lo mata si muere esta ventana (Windows).

    El job lleva `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Su handle no se cierra
    nunca: lo guarda el proceso de la ventana y, cuando este muere, el sistema lo
    cierra y mata a todo el job. Es un punto que sustituyen los tests.

    Args:
        proceso: El `rcd` recién lanzado.

    Returns:
        True si quedó atado. False si no (otro sistema, o el sistema no deja):
        el `rcd` sigue su curso sin este cinturón.
    """
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class _Basico(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _Contadores(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class _Extendido(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _Basico),
                        ("IoInfo", _Contadores),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                ctypes.c_void_p, wintypes.DWORD]
        k32.SetInformationJobObject.restype = wintypes.BOOL
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

        job = k32.CreateJobObjectW(None, None)
        if not job:
            return False
        info = _Extendido()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            k32.CloseHandle(job)
            return False                      # 9 = JobObjectExtendedLimitInformation
        if not k32.AssignProcessToJobObject(job, int(proceso._handle)):  # type: ignore[attr-defined]
            k32.CloseHandle(job)
            return False
        _JOBS.append(job)
        return True
    except Exception:  # noqa: BLE001 — sin ctypes.WinDLL (POSIX) o sin el handle: sin cinturón
        return False


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
        estándar, y sin consola en Windows o en su propia sesión en POSIX. En
        Linux lleva además `preexec_fn=_morir_con_el_padre`; el punto de
        resolver `prctl` es éste, en el padre y antes del `Popen`.
    """
    opciones: dict[str, Any] = {
        "cwd": str(model.APP_DIR), "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL, "stderr": stderr}
    if os.name == "nt":
        opciones["creationflags"] = model.CREATE_NO_WINDOW
    else:
        opciones["start_new_session"] = True
        if _resolver_prctl() is not None:
            opciones["preexec_fn"] = _morir_con_el_padre
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
        _olvidar(getattr(self.proceso, "pid", None))
        try:
            self._stderr.close()
        except OSError:
            pass


def arrancar() -> Rcd:
    """Lanza `rclone rcd` en un puerto libre del bucle local, sin esperar a que esté listo.

    Hay que llamarla desde el hilo de Tk, **nunca desde un hilo de trabajo**:
    en Linux el hijo muere cuando muere el hilo que lo lanzó (`PDEATHSIG`), y
    el de Tk dura tanto como la ventana. Lanzar el hijo no bloquea; lo que
    tarda es `Rcd.esperar()`, que sí va a un hilo.

    Antes de lanzar mata al `rcd` que un proceso anterior dejara vivo
    (`limpiar_huerfano`), y después lo ata a un Job Object (Windows) y apunta su
    pid y su hora de creación en `state/rcd.json`, sin la contraseña.

    Returns:
        El `Rcd`, apuntado en `store` para que `store.matar_hijos()` lo corte.

    Raises:
        ConfigError: Si no hay rclone, no se puede abrir un puerto local o el
            sistema no deja ejecutar rclone.
    """
    binario = catalog._binary()
    try:
        puerto = puerto_libre()
    except OSError as e:
        raise ConfigError(f"No se puede abrir un puerto local: {e}") from e
    limpiar_huerfano()
    usuario, clave = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    orden = [binario, "rcd", "--config", str(model.RCLONE_CONF),
             "--rc-addr", f"127.0.0.1:{puerto}", *catalog.NET_FLAGS]
    # Ninguna `RCLONE_RC_*` de quien lanza prdrive pasa al hijo: rclone lee cada flag de
    # `rc` también de su variable, y `RCLONE_RC_NO_AUTH`, `_WEB_GUI`, `_SERVE`, `_ADDR` o
    # `_HTPASSWD` deshacerían lo que este módulo promete (sin `--rc-no-auth` no hay forma
    # de negarlas por argv). En Windows los nombres no distinguen mayúsculas.
    entorno = {k: v for k, v in os.environ.items() if not k.upper().startswith("RCLONE_RC_")}
    entorno.update(RCLONE_RC_USER=usuario, RCLONE_RC_PASS=clave)
    stderr = tempfile.TemporaryFile()
    try:
        proceso = lanzar(orden, entorno, stderr)
    except OSError as e:
        stderr.close()
        raise ConfigError(f"No se puede ejecutar rclone: {e}") from e
    except BaseException:
        stderr.close()
        raise
    if os.name == "nt":
        atar_al_job(proceso)    # si no se deja, sigue sin este cinturón: quedan los otros dos
    pid = getattr(proceso, "pid", None)
    if pid is not None:
        store.write_json(fichero_estado(), {"pid": pid, "creado": store.creado(pid)})
    store.apuntar_hijo(proceso)
    return Rcd(proceso, f"http://127.0.0.1:{puerto}/", usuario, clave, stderr)
