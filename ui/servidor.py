"""Lo que decide la ventana «Servidor…», sin Tk, sin disco y sin red.

La ventana (`ui/tk_servidor.py`) solo dibuja. Aquí vive lo que se puede probar
sin pantalla: cómo se lee una respuesta de `operations/list`, qué se pide a
rclone, cómo se navega sin que una respuesta tardía pinte la carpeta equivocada,
qué remotes se ofrecen, qué carpetas son de una pareja y cómo se dice un fallo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from common import pairing
from common.model import Config
from common.rcd import ErrorRc, RcdCaido

from . import remote_picker

RAIZ = remote_picker.RAIZ

TIPOS_INTERNOS = frozenset({"combine", "alias"})
"""Remotes de `rclone.conf` que son cosa de prdrive y no un servidor que explorar."""

SIN_DATO = "—"
"""Lo que enseña una celda cuyo dato no se conoce."""

UNIDADES = ("B", "KB", "MB", "GB", "TB")
"""Las unidades de `tamano_legible`, en base 1024."""

_PERMISO = ("permission denied", "permission_denied", "access denied", "forbidden")
"""Cómo dicen rclone, SFTP y WebDAV que no te dejan entrar (en minúsculas)."""
_SIN_RED = ("dial tcp", "connection refused", "no route to host", "no such host",
            "network is unreachable")
"""Cómo dice Go que no llega al servidor (en minúsculas)."""
_NO_EXISTE = ("directory not found", "object not found", "file not found", "no such file",
              "does not exist")
"""Cómo dice rclone que la carpeta ya no está (en minúsculas)."""
_TIEMPO = ("timeout", "timed out", "deadline exceeded")
"""Cómo dice Go que el servidor no contestó (en minúsculas)."""

PRIMER_ANO = 1970
"""Año desde el que una fecha es de verdad: rclone da `0001-01-01T00:00:00Z` cuando no sabe la hora.

Una fecha anterior no se puede pasar a hora local en todos los sistemas (en Windows
`astimezone()` falla antes de 1970), así que se trata como desconocida.
"""

_FRACCION = re.compile(r"(\.\d{6})\d+")


@dataclass(frozen=True)
class Entrada:
    """Una fila de la tabla: un archivo o una carpeta del servidor.

    Args:
        nombre: El nombre, sin ruta.
        es_carpeta: Si es una carpeta.
        tamano: Bytes, o `None` en una carpeta o si el servidor no lo dice.
        fecha: Última modificación (con zona si el servidor la dio), o `None`.
        modo: Los bits de permiso del servidor, o `None` si no se leyeron.
        uid: El dueño, o `None`.
        gid: El grupo, o `None`.
    """

    nombre: str
    es_carpeta: bool
    tamano: int | None
    fecha: datetime | None
    modo: int | None = None
    uid: int | None = None
    gid: int | None = None


def _fecha(texto: Any) -> datetime | None:
    """Lee un `ModTime` de rclone; `None` si no se entiende o es anterior a `PRIMER_ANO`.

    rclone puede dar hasta nanosegundos y un desfase (`+02:00`); `fromisoformat`
    solo admite microsegundos, así que se recorta la fracción.
    """
    if not isinstance(texto, str):
        return None
    try:
        fecha = datetime.fromisoformat(_FRACCION.sub(r"\1", texto))
    except ValueError:
        return None
    return fecha if fecha.year >= PRIMER_ANO else None


def _entrada(item: Any) -> Entrada | None:
    """Convierte un objeto de `operations/list`; `None` si no cuadra."""
    if not isinstance(item, dict):
        return None
    nombre = item.get("Name")
    if not isinstance(nombre, str) or not nombre:
        return None
    es_carpeta = item.get("IsDir") is True
    tamano = item.get("Size")
    if es_carpeta or isinstance(tamano, bool) or not isinstance(tamano, int) or tamano < 0:
        tamano = None
    return Entrada(nombre, es_carpeta, tamano, _fecha(item.get("ModTime")))


def entradas_de(respuesta: dict) -> tuple[Entrada, ...]:
    """Devuelve las entradas de una respuesta de `operations/list`.

    Args:
        respuesta: El JSON de rclone; los objetos están en `respuesta["list"]`.

    Returns:
        Las carpetas primero y luego los archivos, cada grupo por nombre sin
        distinguir mayúsculas. Un objeto que no cuadre se ignora, como
        `remote_picker.parse_lsd()`; una respuesta sin lista es una carpeta vacía.
    """
    items = respuesta.get("list") if isinstance(respuesta, dict) else None
    if not isinstance(items, list):
        return ()
    entradas = [e for e in map(_entrada, items) if e is not None]
    return tuple(sorted(entradas, key=lambda e: (not e.es_carpeta, e.nombre.lower())))


def remotes_de(texto_conf: str, por_defecto: str | None,
               device_remote: str | None) -> dict[str, str]:
    """Devuelve los remotes que se ofrecen en el desplegable.

    Args:
        texto_conf: El contenido del `rclone.conf` del dispositivo.
        por_defecto: El `remote` de `[defaults]`; va el primero si está.
        device_remote: El remote interno del dispositivo, que no se ofrece.

    Returns:
        `{nombre: tipo}` sin los `combine` ni los `alias` ni `device_remote`;
        primero `por_defecto` y luego el resto por nombre.
    """
    todos = {nombre: opciones.get("type", "")
             for nombre, opciones in pairing.parse_rclone_conf(texto_conf).items()
             if opciones.get("type", "") not in TIPOS_INTERNOS and nombre != device_remote}
    orden = sorted(todos, key=lambda n: (n != por_defecto, n))
    return {nombre: todos[nombre] for nombre in orden}


def params_listado(remote: str, ruta: str, permisos: bool) -> dict:
    """Devuelve los parámetros de `operations/list` para una carpeta.

    El `fs` es siempre `remote:/`: rclone guarda en caché un objeto por cadena
    `fs` y con ella una única conexión SSH. `remote` es un texto JSON, nunca una
    URL: un nombre con espacios, `%`, `#` o `?` llega tal cual, y la raíz llega vacía.

    Args:
        remote: El remote de `rclone.conf`.
        ruta: La carpeta, absoluta en el remote.
        permisos: Si se piden también los metadatos (modo, dueño y grupo).
    """
    opt: dict[str, bool] = {"noMimeType": True}
    if permisos:
        opt["metadata"] = True
    return {"fs": f"{remote}:/", "remote": remote_picker.normalizar(ruta).lstrip("/"), "opt": opt}


@dataclass(frozen=True)
class Peticion:
    """Un listado pedido.

    Args:
        numero: Su orden entre las pedidas; solo vale la última.
        remote: El remote del listado.
        ruta: La carpeta, normalizada.
    """

    numero: int
    remote: str
    ruta: str


class Navegacion:
    """Dónde está la ventana y qué enseña, con la última petición ganando.

    `remote`, `ruta` y `entradas` cambian juntos y solo en `recibir()`, así que
    la tabla nunca enseña la carpeta A con la ruta B arriba, ni una respuesta
    tardía pisa a otra más reciente.

    Args:
        remote: El remote en el que se abre.

    Attributes:
        remote: El remote de lo que se enseña.
        ruta: La carpeta de lo que se enseña.
        entradas: Lo que hay en ella.
        sin_acceso: Los `(remote, ruta)` en los que entrar ha fallado por permiso.
    """

    def __init__(self, remote: str) -> None:
        self.remote = remote
        self.ruta = RAIZ
        self.entradas: tuple[Entrada, ...] = ()
        self.sin_acceso: set[tuple[str, str]] = set()
        self._numero = 0

    def _nueva(self, remote: str, ruta: str) -> Peticion:
        """Numera una petición nueva, que sustituye a cualquier otra en vuelo."""
        self._numero += 1
        return Peticion(self._numero, remote, remote_picker.normalizar(ruta))

    def pedir(self, ruta: str) -> Peticion:
        """Registra un listado de `ruta` en el remote que se está enseñando.

        Sustituye a la petición anterior, también a un `cambiar_remote()` en
        vuelo: la ruta sale de la tabla que se ve, así que va a su remote.
        """
        return self._nueva(self.remote, ruta)

    def recibir(self, p: Peticion, entradas: tuple[Entrada, ...]) -> bool:
        """Acepta la respuesta de `p`; `False`, sin cambiar nada, si ya no es la última pedida."""
        if p.numero != self._numero:
            return False
        self.remote, self.ruta, self.entradas = p.remote, p.ruta, entradas
        return True

    def fallo(self, p: Peticion, error: Exception) -> str | None:
        """Registra que el listado `p` falló.

        Returns:
            La frase para el usuario, o `None` si `p` ya no es la última pedida.
            Si el fallo es de permiso, `(p.remote, p.ruta)` queda en `sin_acceso`.
        """
        if p.numero != self._numero:
            return None
        if es_de_permiso(error):
            self.sin_acceso.add((p.remote, p.ruta))
        return frase_error(error)

    def cambiar_remote(self, nombre: str) -> Peticion:
        """Pide la raíz de otro remote; `remote` cambia solo cuando esa respuesta llega."""
        return self._nueva(nombre, RAIZ)

    def hijo(self, nombre: str) -> str:
        """Devuelve la ruta de la carpeta `nombre` dentro de la actual."""
        return remote_picker.entrar(self.ruta, nombre)

    def padre(self) -> str:
        """Devuelve la ruta de la carpeta que contiene a la actual (la raíz es el techo)."""
        return remote_picker.subir(self.ruta)


def parejas_en(config: Config, remote: str) -> dict[str, str]:
    """Devuelve `{remote_path normalizado: nombre}` de las parejas de ese remote."""
    return {remote_picker.normalizar(p.remote_path): p.name
            for p in config.pairs if p.remote_name == remote}


def marca(config: Config, remote: str, ruta: str) -> str | None:
    """Devuelve la pareja cuya carpeta es exactamente `ruta` en ese remote, si la hay."""
    return parejas_en(config, remote).get(remote_picker.normalizar(ruta))


def dentro_de(config: Config, remote: str, ruta: str) -> str | None:
    """Devuelve la pareja cuya carpeta es `ruta` o la contiene, en ese remote.

    La comparación es por tramos: `/datos/notas2` no está dentro de `/datos/notas`.
    Una pareja en la raíz del remote contiene todo el remote.
    """
    actual = remote_picker.normalizar(ruta)
    for carpeta, nombre in parejas_en(config, remote).items():
        if actual == carpeta or actual.startswith(carpeta.rstrip("/") + "/"):
            return nombre
    return None


def _dice(error: Exception, patrones: tuple[str, ...]) -> bool:
    """Si el texto del error contiene alguno de los patrones (en minúsculas)."""
    texto = (error.mensaje if isinstance(error, ErrorRc) else str(error)).lower()
    return any(p in texto for p in patrones)


def es_de_permiso(error: Exception) -> bool:
    """Si rclone dice que no se puede entrar por permisos (texto, o un 403)."""
    if isinstance(error, RcdCaido):
        return False
    return (isinstance(error, ErrorRc) and error.estado == 403) or _dice(error, _PERMISO)


def es_sin_red(error: Exception) -> bool:
    """Si el error es que no se llega al servidor (no que `rcd` esté caído)."""
    return not isinstance(error, RcdCaido) and _dice(error, _SIN_RED)


def frase_error(error: Exception) -> str:
    """Devuelve la frase en español para un fallo de listado.

    Se comprueba antes si es `RcdCaido`: su texto cita el error de conexión con
    `rcd` y no debe leerse como un servidor sin red. Después: permiso, sin red,
    carpeta que ya no existe, tiempo agotado; lo que no se reconoce se cita tal
    cual lo dijo rclone.
    """
    if isinstance(error, RcdCaido):
        return "Se ha perdido la conexión con rclone."
    if es_de_permiso(error):
        return "No tienes permiso para ver esta carpeta."
    if es_sin_red(error):
        return "No hay conexión con el servidor."
    if (isinstance(error, ErrorRc) and error.estado == 404) or _dice(error, _NO_EXISTE):
        return "Esa carpeta ya no existe en el servidor."
    if _dice(error, _TIEMPO):
        return "El servidor no ha contestado a tiempo."
    return f"rclone dice: {error.mensaje if isinstance(error, ErrorRc) else error}"


def tamano_legible(n: int | None) -> str:
    """Devuelve un tamaño en base 1024: una cifra decimal con coma por debajo de 10, entero desde ahí."""
    if n is None:
        return SIN_DATO
    valor = float(n)
    unidad = 0
    while valor >= 1023.5 and unidad < len(UNIDADES) - 1:
        valor /= 1024
        unidad += 1
    if unidad == 0:
        return f"{n} B"
    texto = f"{valor:.1f}" if valor < 10 else f"{valor:.0f}"
    return f"{texto.removesuffix('.0').replace('.', ',')} {UNIDADES[unidad]}"


def fecha_legible(fecha: datetime | None) -> str:
    """Devuelve `dd/mm/aaaa hh:mm` en hora local; una fecha sin zona se enseña como viene."""
    if fecha is None or fecha.year < PRIMER_ANO:
        return SIN_DATO
    try:
        if fecha.tzinfo is not None:
            fecha = fecha.astimezone()
        return fecha.strftime("%d/%m/%Y %H:%M")
    except (OverflowError, OSError, ValueError):
        return SIN_DATO


def cuantos(n: int) -> str:
    """Devuelve `1 elemento` o `{n} elementos`."""
    return f"{n} elemento" if n == 1 else f"{n} elementos"
