"""Lo que decide una transferencia del explorador «Servidor…», sin Tk, sin disco y sin red.

La ventana (`ui/tk_servidor.py`) solo dibuja. Aquí vive qué se copia: el lote que
el usuario eligió, las reglas de filtro de rclone que copian exactamente esos
elementos, las dos mitades (`origen`, `destino`) de la copia y cuántos archivos
ya estaban en el destino.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from common.model import Config

from . import remote_picker, servidor

BAJAR = "bajar"
"""Sentido de un lote que copia del servidor al equipo."""
SUBIR = "subir"
"""Sentido de un lote que copia del equipo al servidor."""

_METACARACTERES = "\\*?[]{}"
"""Caracteres que un filtro de rclone entiende como patrón y hay que escapar con `\\`."""


@dataclass(frozen=True)
class Elemento:
    """Un archivo o una carpeta elegidos para copiar.

    Args:
        nombre: Nombre suelto, sin ruta (sin `/`), tal como lo muestra el explorador.
        es_carpeta: Si se copia con todo lo que contiene.
    """

    nombre: str
    es_carpeta: bool


@dataclass(frozen=True)
class Lote:
    """Lo que el usuario pidió copiar en una sola operación.

    Args:
        sentido: `BAJAR` o `SUBIR`.
        remote: Nombre del remote de `rclone.conf`.
        ruta_remota: Carpeta del servidor (origen al bajar, destino al subir), en la
            forma de `remote_picker.normalizar`.
        carpeta_local: Carpeta del equipo (destino al bajar, origen al subir), en esa
            misma forma de ruta absoluta.
        elementos: Lo elegido dentro de la carpeta de origen.
    """

    sentido: str
    remote: str
    ruta_remota: str
    carpeta_local: str
    elementos: tuple[Elemento, ...]


def _escapar(nombre: str) -> str:
    """Escapa con `\\` los caracteres que rclone leería como patrón."""
    return "".join("\\" + ch if ch in _METACARACTERES else ch for ch in nombre)


def reglas_de(elementos: Iterable[Elemento]) -> list[str]:
    """Devuelve las reglas `IncludeRule` que copian justo estos elementos.

    Cada regla va como entrada propia de la lista, así que rclone no interpreta un
    prefijo `+ `/`- `: un nombre que empieza por `!`, `+` o `-` es un nombre. Un
    archivo `x` es `/x`; una carpeta `x` es `/x/**`, que con `createEmptySrcDirs`
    la copia entera, también vacía.

    Args:
        elementos: Los `Elemento` elegidos.

    Returns:
        Una regla por elemento, en su orden; vacía si no hay elementos (quien llama
        no debe pedir una copia sin reglas).
    """
    return [
        "/" + _escapar(e.nombre) + ("/**" if e.es_carpeta else "")
        for e in elementos
    ]


def fs_de(lote: Lote) -> tuple[str, str]:
    """Devuelve `(origen, destino)` de la copia del lote.

    El lado del servidor siempre cuelga de la raíz absoluta (`nas:/`, `nas:/datos`),
    como en el resto del explorador; el del equipo es la carpeta tal cual.
    """
    servidor = f"{lote.remote}:/{lote.ruta_remota.lstrip('/')}"
    if lote.sentido == BAJAR:
        return servidor, lote.carpeta_local
    return lote.carpeta_local, servidor


def choques(rutas_origen: set[str], rutas_destino: set[str]) -> int:
    """Cuenta los archivos de origen que ya existen en el destino.

    Args:
        rutas_origen: Rutas relativas de los archivos a copiar, separadas por `/`.
        rutas_destino: Rutas relativas de los archivos que hay en el destino.
            Solo archivos: una carpeta que ya existe se fusiona y no cuenta.

    Returns:
        Cuántas rutas de origen están también en el destino.
    """
    return len(rutas_origen & rutas_destino)


def texto_choques(n: int, destino: str) -> str:
    """Dice cuántos elementos ya existen en el destino, con la pregunta que sigue."""
    if n == 1:
        return f"1 elemento ya existe en {destino}. ¿Sobrescribirlo u omitirlo?"
    return f"{n} elementos ya existen en {destino}. ¿Sobrescribirlos u omitirlos?"


@dataclass(frozen=True)
class Afectada:
    """Una pareja que recibiría lo que se copia.

    Args:
        pareja: Nombre de la pareja.
        modo: Nombre de su modo (`bisync`, `up`, `down`, `up-mirror`, `down-mirror`).
    """

    pareja: str
    modo: str


def _afectadas(config: Config, nombres: set[str]) -> tuple[Afectada, ...]:
    """Devuelve las parejas con esos nombres, sin repetir y en el orden de la configuración."""
    return tuple(Afectada(p.name, p.mode.name) for p in config.pairs if p.name in nombres)


def afectadas_subida(config: Config, remote: str, ruta_destino: str,
                     elementos: Iterable[Elemento]) -> tuple[Afectada, ...]:
    """Devuelve las parejas del servidor que recibirían lo que se sube.

    Cuenta la pareja más honda que contiene la carpeta de destino, las parejas cuya
    carpeta es uno de los elementos subidos y las que cuelgan de una carpeta subida
    (subir `notas/` a `/datos` toca a la pareja de `/datos/notas`). La comparación es
    por tramos de ruta, no por prefijo de texto.

    Args:
        config: Configuración con las parejas.
        remote: Remote al que se sube; las parejas de otros remotes no cuentan.
        ruta_destino: Carpeta del servidor que recibe la subida.
        elementos: Lo que se sube.

    Returns:
        Las parejas alcanzadas, sin repetir y en el orden de la configuración.
    """
    nombres: set[str] = set()
    dentro = servidor.dentro_de(config, remote, ruta_destino)
    if dentro:
        nombres.add(dentro)
    base = remote_picker.normalizar(ruta_destino).rstrip("/")
    carpetas = servidor.parejas_en(config, remote)
    for e in elementos:
        objetivo = remote_picker.normalizar(base + "/" + e.nombre)
        for carpeta, nombre in carpetas.items():
            if carpeta == objetivo or (e.es_carpeta and carpeta.startswith(objetivo + "/")):
                nombres.add(nombre)
    return _afectadas(config, nombres)


def afectadas_bajada(config: Config, carpeta_destino: str,
                     elementos: Iterable[Elemento]) -> tuple[Afectada, ...]:
    """Devuelve las parejas cuya carpeta del equipo recibiría lo que se baja.

    Es la misma cuenta que `afectadas_subida` contra la carpeta local de cada pareja
    (`Pair.local_abs`), con rutas resueltas y `Path.is_relative_to`: nunca un prefijo
    de texto.

    Args:
        config: Configuración con las parejas.
        carpeta_destino: Carpeta del equipo que recibe la bajada.
        elementos: Lo que se baja.

    Returns:
        Las parejas alcanzadas, sin repetir y en el orden de la configuración.
    """
    destino = Path(carpeta_destino).resolve()
    locales = [(p.name, p.local_abs) for p in config.pairs]
    nombres: set[str] = set()
    contienen = [(len(local.parts), nombre) for nombre, local in locales
                 if destino.is_relative_to(local)]
    if contienen:
        nombres.add(max(contienen)[1])
    for e in elementos:
        objetivo = (destino / e.nombre).resolve()
        for nombre, local in locales:
            if local == objetivo or (e.es_carpeta and local.is_relative_to(objetivo)):
                nombres.add(nombre)
    return _afectadas(config, nombres)


_PELIGROSO = {SUBIR: "up-mirror", BAJAR: "down-mirror"}
"""Modo de pareja que borraría lo copiado en su próxima pasada, según el sentido."""

_BLOQUEOS = {
    SUBIR: "«{p}» deja el servidor igual que el dispositivo: lo que subas aquí lo borraría "
           "su próxima pasada. Súbelo a su carpeta del dispositivo.",
    BAJAR: "«{p}» deja su carpeta igual que el servidor: lo que bajes aquí lo borraría "
           "su próxima pasada. Bájalo fuera de ella.",
}
"""Texto del bloqueo de cada sentido."""

_BAJA_AL_DISPOSITIVO = "Lo que subas a «{p}» lo bajará al dispositivo su próxima pasada."
_SUBE_AL_SERVIDOR = "Lo que bajes a la carpeta de «{p}» lo subirá al servidor su próxima pasada."
_AVISOS = {
    SUBIR: {
        "bisync": "Lo que subas a «{p}» lo bajará al dispositivo su próxima pasada; si "
                  "sobrescribes algo que también ha cambiado allí, saldrá un conflicto.",
        "down": _BAJA_AL_DISPOSITIVO,
        "down-mirror": _BAJA_AL_DISPOSITIVO,
        "up": "«{p}» solo sube del dispositivo: lo que subas aquí se quedará en el servidor.",
    },
    BAJAR: {
        "bisync": _SUBE_AL_SERVIDOR,
        "up": _SUBE_AL_SERVIDOR,
        "up-mirror": _SUBE_AL_SERVIDOR,
        "down": "«{p}» solo baja del servidor: lo que bajes aquí se quedará en el dispositivo.",
    },
}
"""Aviso de cada modo de pareja, por sentido; el modo que bloquea no tiene aviso."""


def bloqueo(sentido: str, afectadas: Iterable[Afectada]) -> str | None:
    """Devuelve el texto que impide la copia, o `None` si ninguna pareja la impide.

    Impide subir a una pareja `up-mirror` (su próxima pasada borraría lo subido) y
    bajar a la carpeta de una `down-mirror`. Si hay varias, habla la primera.
    """
    for a in afectadas:
        if a.modo == _PELIGROSO[sentido]:
            return _BLOQUEOS[sentido].format(p=a.pareja)
    return None


def aviso(sentido: str, afectadas: Iterable[Afectada]) -> str | None:
    """Devuelve lo que pasará con lo copiado en cada pareja alcanzada, o `None`.

    Args:
        sentido: `BAJAR` o `SUBIR`.
        afectadas: Las parejas alcanzadas.

    Returns:
        Los textos de todas las parejas, separados por una línea en blanco; `None`
        si no hay ninguna o si la copia está bloqueada (entonces manda `bloqueo`).
    """
    afectadas = tuple(afectadas)
    if bloqueo(sentido, afectadas) is not None:
        return None
    textos = [_AVISOS[sentido][a.modo].format(p=a.pareja) for a in afectadas]
    return "\n\n".join(textos) or None
