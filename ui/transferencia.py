"""Lo que decide una transferencia del explorador «Servidor…», sin Tk, sin disco y sin red.

La ventana (`ui/tk_servidor.py`) solo dibuja. Aquí vive qué se copia: el lote que
el usuario eligió, las reglas de filtro de rclone que copian exactamente esos
elementos, las dos mitades (`origen`, `destino`) de la copia y cuántos archivos
ya estaban en el destino.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import remote_picker

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
        nombre: Nombre suelto, sin ruta, tal como lo muestra el explorador.
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


def reglas_de(elementos) -> list[str]:
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
