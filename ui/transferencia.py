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

from common import rcd
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


def _mas_hondas(contienen: list[tuple[int, str]]) -> set[str]:
    """Devuelve los nombres de TODAS las parejas a la mayor hondura, no solo de una.

    Dos parejas pueden compartir carpeta; si una es `*-mirror` y se eligiera solo
    una de las dos, el bloqueo podría escaparse.
    """
    if not contienen:
        return set()
    hondura = max(h for h, _ in contienen)
    return {nombre for h, nombre in contienen if h == hondura}


def afectadas_subida(config: Config, remote: str, ruta_destino: str,
                     elementos: Iterable[Elemento]) -> tuple[Afectada, ...]:
    """Devuelve las parejas del servidor que recibirían lo que se sube.

    Cuenta las parejas de la carpeta más honda que contiene la carpeta de destino (todas
    las que comparten esa carpeta), las parejas cuya carpeta es uno de los elementos
    subidos y las que cuelgan de una carpeta subida (subir `notas/` a `/datos` toca a la
    pareja de `/datos/notas`). La comparación es por tramos de ruta, no por prefijo de
    texto.

    Args:
        config: Configuración con las parejas.
        remote: Remote al que se sube; las parejas de otros remotes no cuentan.
        ruta_destino: Carpeta del servidor que recibe la subida.
        elementos: Lo que se sube.

    Returns:
        Las parejas alcanzadas, sin repetir y en el orden de la configuración.
    """
    carpetas = [(remote_picker.normalizar(p.remote_path), p.name)
                for p in config.pairs if p.remote_name == remote]
    destino = remote_picker.normalizar(ruta_destino)
    nombres = _mas_hondas([
        (len(carpeta.rstrip("/")), nombre) for carpeta, nombre in carpetas
        if destino == carpeta or destino.startswith(carpeta.rstrip("/") + "/")
    ])
    base = destino.rstrip("/")
    for e in elementos:
        objetivo = remote_picker.normalizar(base + "/" + e.nombre)
        for carpeta, nombre in carpetas:
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
    nombres = _mas_hondas([(len(local.parts), nombre) for nombre, local in locales
                           if destino.is_relative_to(local)])
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


def _numero(stats: dict, clave: str) -> float:
    """Devuelve un campo numérico de `core/stats`; 0 si falta, es nulo o no es un número."""
    valor = stats.get(clave)
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return 0
    return valor


def _tiempo(segundos: float) -> str:
    """Dice una duración como `N s` (< 60), `N min` (< 3600) o `N h`."""
    n = max(0, int(segundos))
    if n < 60:
        return f"{n} s"
    if n < 3600:
        return f"{n // 60} min"
    return f"{n // 3600} h"


@dataclass(frozen=True)
class Progreso:
    """Lo que enseña el panel de progreso de un lote en marcha.

    Args:
        titulo: `Subiendo a …` o `Bajando a …`.
        archivo: El archivo que se está copiando; vacío si rclone aún no dice cuál.
        cuenta: `{hechos} de {total} archivos · {bytes} de {total_bytes}`.
        fraccion: De 0 a 1; `None` si aún no se sabe el total (barra indeterminada).
        ritmo: `{velocidad}/s · quedan {eta}`; solo la velocidad si no hay estimación,
            vacío si no hay velocidad.
    """

    titulo: str
    archivo: str
    cuenta: str
    fraccion: float | None
    ritmo: str


def progreso_de(stats: dict, lote: Lote, destino_visible: str) -> Progreso:
    """Convierte un `core/stats` de rclone en los textos del panel.

    Nunca lanza: antes de que acabe el listado `totalBytes` y `totalTransfers` valen 0,
    `eta` es nulo y `transferring` puede faltar.

    Args:
        stats: La respuesta de `core/stats`; puede estar vacía.
        lote: El lote en marcha (da el sentido).
        destino_visible: El destino tal como lo ve el usuario.

    Returns:
        Los textos y la fracción del panel.
    """
    verbo = "Subiendo" if lote.sentido == SUBIR else "Bajando"
    en_curso = stats.get("transferring")
    primero = en_curso[0] if isinstance(en_curso, list) and en_curso else None
    nombre = primero.get("name") if isinstance(primero, dict) else None
    hechos = int(_numero(stats, "transfers"))
    total = int(_numero(stats, "totalTransfers"))
    enviados = int(_numero(stats, "bytes"))
    total_bytes = int(_numero(stats, "totalBytes"))
    fraccion = min(1.0, max(0.0, enviados / total_bytes)) if total_bytes > 0 else None
    velocidad = _numero(stats, "speed")
    ritmo = ""
    if velocidad > 0:
        ritmo = f"{servidor.tamano_legible(int(velocidad))}/s"
        if isinstance(stats.get("eta"), (int, float)) and not isinstance(stats.get("eta"), bool):
            ritmo += f" · quedan {_tiempo(stats['eta'])}"
    return Progreso(
        titulo=f"{verbo} a {destino_visible}",
        archivo=nombre if isinstance(nombre, str) else "",
        cuenta=(f"{hechos} de {total} archivos · {servidor.tamano_legible(max(0, enviados))} "
                f"de {servidor.tamano_legible(total_bytes)}"),
        fraccion=fraccion,
        ritmo=ritmo,
    )


@dataclass(frozen=True)
class Resultado:
    """Cómo acabó un lote.

    Args:
        texto: La frase que se enseña.
        tono: `"ok"` o `"aviso"`.
        reintentar: Si se ofrece `Reintentar` (solo tras un fallo, no tras cancelar).
    """

    texto: str
    tono: str
    reintentar: bool


def resultado_de(estado: dict, stats: dict, cancelado: bool, destino_visible: str) -> Resultado:
    """Convierte el `job/status` y el `core/stats` finales en el resultado del lote.

    Args:
        estado: La respuesta de `job/status` del trabajo terminado.
        stats: El último `core/stats` del lote.
        cancelado: Si el usuario canceló (manda sobre lo que diga rclone).
        destino_visible: El destino tal como lo ve el usuario.

    Returns:
        El texto, su tono y si se ofrece reintentar.
    """
    copiados = int(_numero(stats, "transfers"))
    if cancelado:
        return Resultado(
            f"Cancelado: copiados {copiados} de {int(_numero(stats, 'totalTransfers'))}",
            "aviso", False)
    if estado.get("success"):
        # Con `IgnoreExisting` y con archivos idénticos, rclone cuenta lo omitido en `checks`.
        omitidos = int(_numero(stats, "checks")) - copiados
        texto = f"Copiados {copiados}" + (f" · omitidos {omitidos}" if omitidos > 0 else "")
        return Resultado(texto, "ok", False)
    error = rcd.ErrorRc(str(estado.get("error") or "no se ha podido copiar"), 0)
    if servidor.es_de_permiso(error):
        return Resultado(f"No tienes permiso para escribir en {destino_visible}.", "aviso", True)
    return Resultado(servidor.frase_error(error), "aviso", True)
