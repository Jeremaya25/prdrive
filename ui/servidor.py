"""Lo que decide la ventana «Servidor…», sin Tk, sin disco y sin red.

La ventana (`ui/tk_servidor.py`) solo dibuja. Aquí vive lo que se puede probar
sin pantalla: cómo se lee una respuesta de `operations/list`, qué se pide a
rclone, cómo se navega sin que una respuesta tardía pinte la carpeta equivocada
(y el historial de atrás y adelante), las migas de la barra de direcciones y la
ruta que se escribe en ella, el recorrido de una búsqueda en las subcarpetas,
qué remotes se ofrecen, qué carpetas son de una
pareja y cómo se dice un fallo.
"""

from __future__ import annotations

import fnmatch
import os
import re
import unicodedata
from collections import deque
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

LEE_PERMISOS_EN_EL_LISTADO = frozenset({"sftp", "local"})
"""Backends cuyos metadatos salen del mismo listado, sin una petición por objeto.

Pedir `metadata` a uno que los lee por objeto (S3 hace un `HEAD` por archivo) convertiría
cada carpeta en miles de peticiones. Ampliarla exige comprobar en el código de rclone que
el backend los saca del listado. Un `crypt` sobre SFTP es `crypt`: no está.
"""

_FRACCION = re.compile(r"(\.\d{6})\d+")
_OCTAL = re.compile(r"[0-7]{1,7}")
_DECIMAL = re.compile(r"[0-9]{1,10}")


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
    """Lee un `ModTime` de rclone; `None` si no se entiende o no se puede enseñar.

    No se puede enseñar una fecha anterior a `PRIMER_ANO` ni una que desborde al
    pasarla a hora local (`9999-12-31T23:00-05:00`). rclone puede dar hasta
    nanosegundos y un desfase (`+02:00`); `fromisoformat` solo admite
    microsegundos, así que se recorta la fracción.
    """
    if not isinstance(texto, str):
        return None
    try:
        fecha = datetime.fromisoformat(_FRACCION.sub(r"\1", texto))
    except ValueError:
        return None
    if fecha.year < PRIMER_ANO:
        return None
    try:
        fecha.astimezone()
    except (OverflowError, OSError, ValueError):
        return None
    return fecha


def _numero(valor: Any, patron: re.Pattern[str], base: int) -> int | None:
    """Lee un número que rclone da como texto (`"40755"`, `"1000"`); `None` si no cuadra."""
    if not isinstance(valor, str) or not patron.fullmatch(valor):
        return None
    return int(valor, base)


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
    meta = item.get("Metadata")
    if not isinstance(meta, dict):
        meta = {}
    return Entrada(nombre, es_carpeta, tamano, _fecha(item.get("ModTime")),
                   _numero(meta.get("mode"), _OCTAL, 8), _numero(meta.get("uid"), _DECIMAL, 10),
                   _numero(meta.get("gid"), _DECIMAL, 10))


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


NUEVO, ATRAS, ADELANTE, RELEER = "nuevo", "atras", "adelante", "releer"
"""Cómo mueve el historial un listado cuando llega (`Historial.llegar`)."""


@dataclass(frozen=True)
class Peticion:
    """Un listado pedido.

    Args:
        numero: Su orden entre las pedidas; solo vale la última.
        remote: El remote del listado.
        ruta: La carpeta, normalizada.
        movimiento: Qué hace con el historial al llegar (`NUEVO`, `ATRAS`, `ADELANTE`,
            `RELEER`).
        busqueda: El texto de la búsqueda que se vuelve a poner al llegar, o `""`.
    """

    numero: int
    remote: str
    ruta: str
    movimiento: str = NUEVO
    busqueda: str = ""


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

    def _nueva(self, remote: str, ruta: str, movimiento: str = NUEVO,
               busqueda: str = "") -> Peticion:
        """Numera una petición nueva, que sustituye a cualquier otra en vuelo."""
        self._numero += 1
        return Peticion(self._numero, remote, remote_picker.normalizar(ruta), movimiento,
                        busqueda)

    def pedir(self, ruta: str, movimiento: str = NUEVO) -> Peticion:
        """Registra un listado de `ruta` en el remote que se está enseñando.

        Sustituye a la petición anterior, también a un `cambiar_remote()` en
        vuelo: la ruta sale de la tabla que se ve, así que va a su remote.
        """
        return self._nueva(self.remote, ruta, movimiento)

    def ir(self, remote: str, ruta: str, movimiento: str, busqueda: str = "") -> Peticion:
        """Pide un lugar con su remote dicho: el de un paso del historial.

        `remote` y `ruta` van juntos y explícitos, así que no hay riesgo de mandar
        una carpeta de una tabla al remote de otra.
        """
        return self._nueva(remote, ruta, movimiento, busqueda)

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


@dataclass(frozen=True)
class Lugar:
    """Un paso del historial: una carpeta de un remote y, si se buscaba en ella, el texto.

    Args:
        remote: El remote.
        ruta: La carpeta, normalizada.
        busqueda: Lo que se buscaba desde ella al salir, o `""`.
    """

    remote: str
    ruta: str
    busqueda: str = ""


def _mismo_sitio(a: Lugar | None, b: Lugar | None) -> bool:
    """Si dos lugares son la misma carpeta del mismo remote (la búsqueda no cuenta)."""
    return a is not None and b is not None and (a.remote, a.ruta) == (b.remote, b.ruta)


class Historial:
    """Atrás y adelante, como en el Explorador: los lugares a los que se ha llegado.

    Un lugar se apunta cuando su listado LLEGA (`llegar`), nunca al pedirlo: una
    carpeta que falla ni entra ni mueve nada. Ir a un lugar nuevo tras volver
    atrás tira lo que había delante.

    Attributes:
        actual: El lugar que se ve, o `None` si aún no ha llegado ninguno.
    """

    def __init__(self) -> None:
        self._lugares: list[Lugar] = []
        self._indice = -1

    @property
    def actual(self) -> Lugar | None:
        return self._lugares[self._indice] if self._indice >= 0 else None

    @property
    def puede_atras(self) -> bool:
        return self._indice > 0

    @property
    def puede_adelante(self) -> bool:
        return 0 <= self._indice < len(self._lugares) - 1

    def anterior(self) -> Lugar | None:
        """El lugar de atrás, sin moverse; `None` si no hay."""
        return self._lugares[self._indice - 1] if self.puede_atras else None

    def siguiente(self) -> Lugar | None:
        """El lugar de delante, sin moverse; `None` si no hay."""
        return self._lugares[self._indice + 1] if self.puede_adelante else None

    def llegar(self, lugar: Lugar, movimiento: str) -> None:
        """Apunta que ha llegado el listado de `lugar`.

        Args:
            lugar: Lo que se ve ahora.
            movimiento: `RELEER` no mueve nada; `ATRAS` y `ADELANTE` mueven un paso si
                `lugar` es el que toca (si no, cuentan como `NUEVO`); `NUEVO` lo pone
                tras el actual y tira lo de delante, salvo que sea el mismo sitio (y el
                actual no guarde una búsqueda que `lugar` deja).
        """
        if movimiento == RELEER and self.actual is not None:
            return
        if movimiento == ATRAS and _mismo_sitio(lugar, self.anterior()):
            self._indice -= 1
            self._lugares[self._indice] = lugar
            return
        if movimiento == ADELANTE and _mismo_sitio(lugar, self.siguiente()):
            self._indice += 1
            self._lugares[self._indice] = lugar
            return
        # La misma carpeta: se pone al día. Salvo que se llegue sin búsqueda a la carpeta
        # desde la que se buscaba (la ubicación de un resultado suyo): eso es un paso
        # nuevo, para que «Atrás» vuelva a los resultados.
        dejar_resultados = (movimiento == NUEVO and self.actual is not None
                            and self.actual.busqueda and not lugar.busqueda)
        if _mismo_sitio(lugar, self.actual) and not dejar_resultados:
            self._lugares[self._indice] = lugar
            return
        del self._lugares[self._indice + 1:]
        self._lugares.append(lugar)
        self._indice = len(self._lugares) - 1

    def apuntar_busqueda(self, texto: str) -> None:
        """Guarda en el lugar que se ve lo que se está buscando en él (`""` lo quita)."""
        if self.actual is not None:
            a = self.actual
            self._lugares[self._indice] = Lugar(a.remote, a.ruta, texto)


def migas(remote: str, ruta: str) -> tuple[tuple[str, str], ...]:
    """Devuelve los tramos de la barra de direcciones, del remote a la carpeta.

    Returns:
        `(rótulo, ruta)` por tramo: el primero es el remote con su raíz; luego cada
        carpeta con la ruta hasta ella.
    """
    tramos = [(remote, RAIZ)]
    hasta = RAIZ
    for nombre in remote_picker.normalizar(ruta).split("/")[1:]:
        if nombre:
            hasta = remote_picker.entrar(hasta, nombre)
            tramos.append((nombre, hasta))
    return tuple(tramos)


def recoger(anchos, disponible: int, ancho_puntos: int) -> int:
    """Cuántos tramos de en medio se recogen en «…» para que la barra quepa.

    Se recogen desde el principio, después del primero (el servidor): se ve
    siempre el último, y lo más cercano a él antes que lo lejano.

    Args:
        anchos: Lo que ocupa cada tramo, con su separador, en píxeles.
        disponible: El ancho que hay.
        ancho_puntos: Lo que ocupa el tramo «…».

    Returns:
        Cuántos tramos, contados desde el segundo, van a «…»; 0 si cabe todo. Nunca
        recoge el primero ni el último.
    """
    anchos = list(anchos)
    if sum(anchos) <= disponible or len(anchos) <= 2:
        return 0
    k = 1
    while (k < len(anchos) - 2
           and anchos[0] + ancho_puntos + sum(anchos[1 + k:]) > disponible):
        k += 1
    return k


def ruta_escrita(texto: str) -> str:
    """Devuelve la carpeta que alguien ha escrito en la barra de direcciones.

    Siempre desde la raíz del servidor: `\\` vale como `/`, sobran las barras
    dobles y la final, y en blanco es la raíz. `..` sube una carpeta, como en el
    Explorador, y nunca pasa de la raíz: una ruta con `..` dentro listaría la carpeta
    de verdad (rclone y el servidor lo resuelven), pero no se parecería a la de
    ninguna pareja ni a la del catálogo, y sus bloqueos no la reconocerían.
    """
    partes: list[str] = []
    for tramo in remote_picker.normalizar(texto).split("/"):
        if tramo == "..":
            if partes:
                partes.pop()
        elif tramo:
            partes.append(tramo)
    return RAIZ + "/".join(partes)


LIMITE_ELEMENTOS = 100_000
"""Cuántos elementos lee una búsqueda como mucho antes de pararse (memoria y tiempo)."""


def _plegar(texto: str) -> str:
    """El texto sin mayúsculas ni acentos, para comparar como lo haría una persona."""
    descompuesto = unicodedata.normalize("NFKD", str(texto).casefold())
    return "".join(ch for ch in descompuesto if not unicodedata.combining(ch))


def coincide(nombre: str, texto: str) -> bool:
    """Si un nombre es de lo que se busca.

    Sin mayúsculas ni acentos: el nombre contiene el texto. Con `*` o `?` el texto
    es un patrón del nombre entero (`*.pdf`). Un texto en blanco no coincide con nada.
    """
    buscado = _plegar(texto.strip())
    if not buscado:
        return False
    if "*" in buscado or "?" in buscado:
        return fnmatch.fnmatchcase(_plegar(nombre), buscado)
    return buscado in _plegar(nombre)


@dataclass(frozen=True)
class Resultado:
    """Algo encontrado al buscar: la carpeta donde está y su entrada.

    Args:
        carpeta: La carpeta que lo contiene, absoluta en el remote.
        entrada: Lo que dijo el listado de esa carpeta.
    """

    carpeta: str
    entrada: Entrada

    @property
    def ruta(self) -> str:
        """Su ruta absoluta en el remote."""
        return remote_picker.entrar(self.carpeta, self.entrada.nombre)


def _plural(n: int, uno: str, varios: str) -> str:
    return f"{n} {uno if n == 1 else varios}"


class Busqueda:
    """El recorrido de una búsqueda: las carpetas de debajo de una, en anchura.

    Solo apunta: qué carpetas faltan por leer, cuáles se han pedido y qué trajo cada
    una. Quien la usa pide los listados (`siguientes`) y le da las respuestas
    (`recibir`, `fallo`) con el `numero` que tenía al pedirlas: una respuesta de
    antes de `detener()` no cuenta. Lo leído se guarda, así que cambiar el texto
    buscado se resuelve sin volver al servidor (`resultados`).

    Args:
        remote: El remote donde se busca.
        raiz: La carpeta desde la que se busca.
        permisos: Si sus listados piden también los metadatos.
        entradas_raiz: Lo que hay en la raíz, si ya se sabe (la lista que se ve):
            entonces no se vuelve a pedir.

    Attributes:
        numero: La generación de las peticiones; `detener()` la cambia.
        leidas: `{carpeta: entradas}` de lo leído, en el orden en que llegó.
        en_vuelo: Las carpetas pedidas y aún sin respuesta.
        fallidas: Cuántas carpetas no se pudieron leer.
        elementos: Cuántos elementos se han leído.
        parada: Si se paró por pasar de `LIMITE_ELEMENTOS`.
        detenida: Si la paró la persona.
    """

    def __init__(self, remote: str, raiz: str, permisos: bool,
                 entradas_raiz: tuple[Entrada, ...] | None = None) -> None:
        self.remote = remote
        self.raiz = remote_picker.normalizar(raiz)
        self.permisos = permisos
        self.numero = 0
        self.pendientes: deque[str] = deque([self.raiz])
        self.en_vuelo: set[str] = set()
        self.leidas: dict[str, tuple[Entrada, ...]] = {}
        self.fallidas = 0
        self.elementos = 0
        self.parada = False
        self.detenida = False
        if entradas_raiz is not None:
            self.siguientes(1)
            self.recibir(self.numero, self.raiz, entradas_raiz)

    @property
    def acabada(self) -> bool:
        """Si ya no queda nada por leer ni por llegar, o se paró por el tope."""
        return self.parada or (not self.pendientes and not self.en_vuelo)

    @property
    def carpetas(self) -> int:
        """Cuántas carpetas se han leído."""
        return len(self.leidas)

    def siguientes(self, n: int) -> list[str]:
        """Devuelve hasta `n` carpetas por pedir, y las apunta como pedidas."""
        if self.parada or self.detenida:
            return []
        pedidas = []
        while self.pendientes and len(pedidas) < n:
            carpeta = self.pendientes.popleft()
            self.en_vuelo.add(carpeta)
            pedidas.append(carpeta)
        return pedidas

    def recibir(self, numero: int, carpeta: str, entradas: tuple[Entrada, ...]) -> bool:
        """Apunta lo que trajo `carpeta`; `False`, sin cambiar nada, si no se esperaba."""
        if numero != self.numero or carpeta not in self.en_vuelo:
            return False
        self.en_vuelo.discard(carpeta)
        self.leidas[carpeta] = tuple(entradas)
        self.elementos += len(entradas)
        self.pendientes.extend(remote_picker.entrar(carpeta, e.nombre)
                               for e in entradas if e.es_carpeta)
        if self.elementos > LIMITE_ELEMENTOS:
            self.parada = True
        return True

    def fallo(self, numero: int, carpeta: str) -> bool:
        """Apunta que `carpeta` no se pudo leer y se sigue; `False` si no se esperaba."""
        if numero != self.numero or carpeta not in self.en_vuelo:
            return False
        self.en_vuelo.discard(carpeta)
        self.fallidas += 1
        return True

    def detener(self) -> None:
        """Deja de pedir: lo que está en vuelo vuelve a faltar y su respuesta no contará."""
        self.numero += 1
        self.pendientes.extendleft(sorted(self.en_vuelo, reverse=True))
        self.en_vuelo.clear()
        self.detenida = True

    def reanudar(self) -> None:
        """Vuelve a pedir lo que falta (tras `detener()`)."""
        self.detenida = False

    def resultados(self, texto: str) -> list[Resultado]:
        """Lo leído que coincide con `texto`, carpeta a carpeta en el orden en que llegó."""
        return [Resultado(carpeta, e) for carpeta, entradas in self.leidas.items()
                for e in entradas if coincide(e.nombre, texto)]

    def de_carpeta(self, texto: str, carpeta: str) -> list[Resultado]:
        """Lo de `carpeta` que coincide con `texto`: lo que se añade al llegar."""
        return [Resultado(carpeta, e) for e in self.leidas.get(carpeta, ())
                if coincide(e.nombre, texto)]

    def texto_progreso(self, texto: str, encontrados: int) -> str:
        """Lo que dice la ventana mientras se busca."""
        return (f"Buscando «{texto}»… {_plural(self.carpetas, 'carpeta', 'carpetas')} · "
                f"{_plural(encontrados, 'encontrado', 'encontrados')}")

    def texto_final(self, texto: str, encontrados: int) -> str:
        """Lo que dice la ventana cuando ya no se busca (acabada o detenida)."""
        partes = [f"{_plural(encontrados, 'encontrado', 'encontrados')} en "
                  f"{_plural(self.carpetas, 'carpeta', 'carpetas')}"]
        if self.fallidas:
            partes.append(f"{_plural(self.fallidas, 'carpeta', 'carpetas')} no se "
                          + ("pudo leer" if self.fallidas == 1 else "pudieron leer"))
        if self.parada:
            partes.append("Búsqueda parada: demasiados elementos; busca desde una carpeta "
                          "más concreta.")
        return " · ".join(partes)


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
    Una pareja en la raíz del remote contiene todo el remote. Si varias contienen
    la ruta, gana la más honda (la de la carpeta más larga), no la primera de la configuración.
    """
    actual = remote_picker.normalizar(ruta)
    dentro = [(carpeta, nombre) for carpeta, nombre in parejas_en(config, remote).items()
              if actual == carpeta or actual.startswith(carpeta.rstrip("/") + "/")]
    return max(dentro, key=lambda par: len(par[0]))[1] if dentro else None


def _dice(error: Exception, patrones: tuple[str, ...]) -> bool:
    """Si el texto del error contiene alguno de los patrones (en minúsculas)."""
    texto = (error.mensaje if isinstance(error, ErrorRc) else str(error)).lower()
    return any(p in texto for p in patrones)


def es_de_permiso(error: Exception) -> bool:
    """Si rclone dice que no se puede entrar por permisos (texto, o un 403)."""
    if isinstance(error, RcdCaido):
        return False
    return (isinstance(error, ErrorRc) and error.estado == 403) or _dice(error, _PERMISO)


def no_existe(error: Exception) -> bool:
    """Si el error dice que lo pedido ya no está (un 404, o el texto de rclone).

    El texto basta: el `error` de un `job/status` llega sin código HTTP.
    """
    return (isinstance(error, ErrorRc) and error.estado == 404) or _dice(error, _NO_EXISTE)


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
    if no_existe(error):
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


def pide_permisos(fsinfo: dict, tipo: str) -> bool:
    """Si hay que pedir permisos (`opt.metadata`) en los listados de un remote.

    Args:
        fsinfo: La respuesta de `operations/fsinfo`.
        tipo: El `type =` del remote en `rclone.conf` (el `Name` de `fsinfo` es el
            nombre del remote, no el del backend).

    Returns:
        `True` solo si el backend sabe leer metadatos **y** los saca del listado
        (`LEE_PERMISOS_EN_EL_LISTADO`). Cualquier respuesta rara es `False`.
    """
    caracteristicas = fsinfo.get("Features") if isinstance(fsinfo, dict) else None
    leen = isinstance(caracteristicas, dict) and caracteristicas.get("ReadMetadata") is True
    return leen and tipo in LEE_PERMISOS_EN_EL_LISTADO


def texto_permisos(modo: int | None) -> str:
    """Devuelve los tres dígitos de permisos (`755`) o `SIN_DATO` si no se conocen."""
    return SIN_DATO if modo is None else f"{modo & 0o777:03o}"


def mi_uid_de(stat: dict | None) -> int | None:
    """Devuelve el uid del usuario en el servidor, o `None` si no se puede saber.

    Args:
        stat: La respuesta de `operations/stat` de la carpeta por defecto del
            backend (la de inicio en SFTP), pedida con metadatos.
    """
    item = stat.get("item") if isinstance(stat, dict) else None
    meta = item.get("Metadata") if isinstance(item, dict) else None
    return _numero(meta.get("uid"), _DECIMAL, 10) if isinstance(meta, dict) else None


def uid_del_proceso() -> int | None:
    """Devuelve el uid con el que corre este proceso, o `None` donde no existe (Windows).

    Es un punto de sustitución de los tests: lo que rclone verá como «yo» en un
    remote `local` es este uid, porque `rclone rcd` corre con el nuestro.
    """
    getuid = getattr(os, "getuid", None)
    return getuid() if getuid is not None else None


def uid_se_pregunta_al_servidor(tipo: str) -> bool:
    """Si el uid del usuario se averigua con un `operations/stat` (todo menos `local`).

    En `local` no hay a quién preguntar: se sabe, y el `stat` de `<remote>:`
    sería la carpeta desde la que corre `rcd`, no la del usuario.
    """
    return tipo != "local"


def mi_uid(tipo: str, stat: dict | None) -> int | None:
    """Devuelve el uid del usuario para marcar el candado previo, o `None` si no se sabe.

    Args:
        tipo: El `type =` del remote en `rclone.conf`.
        stat: La respuesta de `operations/stat` de `<remote>:` pedida con
            metadatos, o `None` si no se pidió (o falló). Solo cuenta fuera de `local`.

    Returns:
        En `local`, el uid de este proceso (`uid_del_proceso()`): rclone corre
        como nosotros, y `<remote>:` es el directorio de trabajo de `rcd`, que
        puede ser de otro dueño (un dispositivo ajeno), así que su `stat` no dice
        quién soy. En el resto (SFTP), el uid de la carpeta de inicio.
    """
    return uid_del_proceso() if tipo == "local" else mi_uid_de(stat)


def sin_acceso_previo(e: Entrada, mi_uid: int | None) -> bool:
    """Si es SEGURO que el usuario no puede entrar en la carpeta `e` (candado previo).

    Entrar exige `r` y `x`. Solo se marca lo seguro: si el permiso depende del
    grupo (no eres el dueño, el grupo puede y otros no), no se marca, porque los
    grupos del usuario no se saben por SFTP. Root (`mi_uid == 0`) entra siempre.

    Args:
        e: La entrada, con modo y dueño leídos.
        mi_uid: El uid del usuario, o `None` si no se sabe.
    """
    if not e.es_carpeta or e.modo is None or e.uid is None or mi_uid is None or mi_uid == 0:
        return False
    if e.uid == mi_uid:
        return e.modo & 0o500 != 0o500
    return e.modo & 0o050 != 0o050 and e.modo & 0o005 != 0o005


def cuantos(n: int) -> str:
    """Devuelve `1 elemento` o `{n} elementos`."""
    return f"{n} elemento" if n == 1 else f"{n} elementos"
