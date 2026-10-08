#!/usr/bin/env python3
"""Lo que la ventana lee del dispositivo, de una sola vez y sin Tk.

`leer()` junta en UNA pasada, pensada para un hilo de fondo, lo que la ventana
principal, «Parejas» y «Ajustes» necesitan saber del dispositivo: el estado de
cada pareja, las averías, los conflictos, los componentes, la raíz física del
contenedor, el arranque automático y la línea del llavero. La ventana pinta
primero con lo que ya tiene (la config, lo guardado) y cuando la lectura llega
la aplica y la reparte a las demás pantallas (`Compartida`), que así no vuelven
a leer lo mismo en el hilo de Tk.

No importa Tk ni ningún módulo pesado de `common/` al cargarse: cada lector se
importa dentro de la función que lo usa, para que `import ui.instantanea` sea
barato y lo pague quien lee. Cada lector es una función de módulo que los tests
sustituyen (`revision.revisar`, `components.pendientes`, `cifrado.expulsion`...,
y `estados_de` y `linea_del_llavero` de aquí).

La lectura no escribe nada del usuario. Lo único que puede escribir es
`filters/<pareja>.txt` (lo regenera `bisync.filters_file_for()` cuando la config
ha cambiado, y es justo lo que hace falta para saber si la pareja pide un
resync); `leer()` lo hace ANTES de tomar la huella, de modo que no caduca su
propia lectura, y esa escritura es atómica, para que otra pantalla que lo lea
desde el hilo de Tk no lo vea a medias.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping

if TYPE_CHECKING:
    from common.model import Config

    from .llavero_editor import Linea
    from .watch import Resumen


def _vigilante_vacio() -> Resumen:
    """Devuelve el vigilante de «no se sabe»: lo que la ventana pinta sin esa línea."""
    from . import watch
    return watch.Resumen("no_disponible")


@dataclass(frozen=True, eq=False)
class Instantanea:
    """Todo lo que la ventana lee del dispositivo en un refresco.

    Es una foto: no cambia una vez hecha, y se compara por identidad. Un campo
    cuyo lector falló lleva su valor por defecto (el de una ventana sin nada que
    enseñar) y consta en `fallos`; quien necesite la certeza de uno mira ahí.

    Args:
        estados: Por pareja bisync del usuario, `(PairState, FiltersState)`:
            lo que pinta «Parejas». La del llavero no está.
        notas: Por pareja, «requiere resync» donde haga falta.
        hallazgos: Lo que `revision.revisar()` encontró, lo más grave primero.
        cuenta: Cuántos de esos hallazgos cuentan para la ventana
            (`revision.cuenta()`).
        conflictos: Por pareja con alguno, cuántos conflictos tiene.
        componentes: Los componentes que no son los que fija el programa.
        componentes_texto: Una línea por componente, o `None` si no hay.
        componentes_actualizables: Si hay alguno que «Actualizar…» pueda poner
            al día.
        fisica: La raíz física del contenedor VeraCrypt de este dispositivo, o
            `None` si no vive en uno. Se busca una vez y se pasa a los lectores.
        expulsion: El script que cierra el contenedor, o `None`.
        bloqueo: El id de la raíz si es la raíz cifrada de este equipo, o `None`.
        del_equipo: Si la carpeta es una raíz de equipo.
        vigilante: Qué hace el arranque automático de este equipo
            (`watch.Resumen`).
        llavero: La línea del llavero (`llavero_editor.Linea`), o `None` si el
            dispositivo no lo lleva.
        device_id: El id del dispositivo, o `None` si no se pudo leer.
        fallos: Por campo que no se pudo leer, el `repr` del error.
        hecha: `time.time()` de cuando empezó la lectura.
        firma: De qué config es (`firma()`).
        huella: Las fechas y tamaños de lo que se leyó, tomados antes de leerlo
            (`tomar_huella()`); `None` si no hay (una instantánea vacía), y
            entonces no vale para nadie.
    """
    estados: Mapping[str, tuple] = field(default_factory=dict)
    notas: Mapping[str, str] = field(default_factory=dict)
    hallazgos: tuple = ()
    cuenta: int = 0
    conflictos: Mapping[str, int] = field(default_factory=dict)
    componentes: tuple = ()
    componentes_texto: str | None = None
    componentes_actualizables: bool = False
    fisica: Path | None = None
    expulsion: Path | None = None
    bloqueo: str | None = None
    del_equipo: bool = False
    vigilante: Resumen = field(default_factory=_vigilante_vacio)
    llavero: Linea | None = None
    device_id: str | None = None
    fallos: Mapping[str, str] = field(default_factory=dict)
    hecha: float = field(default_factory=time.time)
    firma: tuple = ()
    huella: tuple | None = None

    def vigente(self, config: Config) -> bool:
        """Indica si lo leído sigue siendo lo que hay en el dispositivo para esa config.

        Es cierto si la config es la misma (`firma()`) y la huella de ahora es
        IDÉNTICA a la de cuando se leyó: igualdad, sin holgura. Solo hace `stat`s
        (tres más uno por pareja bisync) y lee el registro del catálogo
        duplicado; no lanza: ante la duda, no vale.

        Args:
            config: La config con la que quien pregunta quiere usar la lectura.
        """
        if self.huella is None:
            return False
        try:
            return firma(config) == self.firma and tomar_huella(config) == self.huella
        except Exception:                            # noqa: BLE001
            return False


def firma(config: Config) -> tuple:
    """Devuelve qué config es, para saber si una lectura es de ella.

    Lleva de cada pareja lo que decide lo que se lee: su nombre, su modo, los
    dos extremos, y lo que entra en su fichero de filtros (`include`, `exclude`,
    las reglas del código y `versions`), que es lo que hace que sus filtros
    «hayan cambiado». Los flags de rclone no: no cambian nada de lo leído. Y si
    hay `[keychain]`. Solo mira atributos: no toca el disco (los extremos locales
    se dan como la ruta relativa, no como la absoluta, que hay que resolver).
    """
    parejas = tuple(
        (p.name, p.mode.name, p.local, p.device_remote, p.remote_name, p.remote_path,
         p.includes, p.excludes, p.reglas, p.versions, p.use_filters_file)
        for p in config.pairs)
    return parejas, config.llavero is not None


def _foto(ruta: Path) -> tuple:
    """Devuelve `(ruta, fecha en ns, tamaño)` de algo, o `(ruta, None, None)` si no está."""
    try:
        st = os.stat(ruta)
    except OSError:
        return (str(ruta), None, None)
    return (str(ruta), st.st_mtime_ns, st.st_size)


def tomar_huella(config: Config) -> tuple:
    """Devuelve la foto de lo que cambia lo que `leer()` lee.

    Son: `state/last_run.json` (lo escribe cada pasada), `state/conflicts.json`,
    la carpeta `filters/` y el workdir `state/<pareja>/` de cada pareja bisync
    (sus listados, un `.lck`, un baseline apartado). Cada una cuenta con su
    fecha y su tamaño, o como ausente. Y el registro del catálogo duplicado
    (`catalog.duplicado()`), por su VALOR y no por su fecha: cada lectura del
    catálogo reescribe `state/catalog.json`, y mirar su fecha caducaría la
    lectura en cada apertura de «Parejas» sin que cambie lo único que de ahí se
    lee. Es un JSON de unas líneas.

    NO cuentan `ui.lock.json`, `ui_prefs.json`, `servicio.pide`, `daemon.stop` ni
    los `.tmp`: los escribe la propia ventana o el servicio, y no cambian nada de
    lo leído. Por eso no se mira la fecha de `state/`, que cambia con todos ellos.
    En FAT32 (fechas de dos en dos segundos) un cambio del mismo tamaño en el
    mismo tic no se ve; no importa: lo que cambia el disco se vuelve a pensar
    (`revisar()`) antes de actuar, nunca se actúa sobre la foto.
    """
    from common import catalog, conflicts, model, results

    rutas = [results.ruta_estado(), conflicts.ruta_estado(), model.FILTERS_DIR]
    rutas += [p.workdir for p in config.pairs if p.is_bisync]
    return (*(_foto(ruta) for ruta in rutas), ("catalogo duplicado", catalog.duplicado()))


def estados_de(config: Config) -> dict[str, tuple]:
    """Devuelve, por pareja bisync del usuario, su baseline y sus filtros.

    Es lo que `pair_editor.rows()` calcula para cada fila de «Parejas». Si una
    pareja no se deja leer lanza: no se devuelven estados a medias.

    Returns:
        `{nombre: (PairState, FiltersState)}`.
    """
    from common import bisync

    return {pair.name: (bisync.pair_state(pair),
                        bisync.filters_state(bisync.filters_file_for(pair)))
            for pair in config.del_usuario if pair.is_bisync}


def linea_del_llavero(config: Config) -> Linea | None:
    """Devuelve la línea del llavero, o `None` si el dispositivo no lo lleva.

    Es la misma regla que `ui.tk.linea_llavero()`: solo importa `llavero_editor`
    (y con él KeePassXC y el llavero) cuando hay `[keychain]` con su pareja.
    """
    if config.llavero is None or config.pareja_llavero is None:
        return None
    from . import llavero_editor
    return llavero_editor.linea(config)


def _regenerar_filtros(config: Config) -> None:
    """Deja al día `filters/<pareja>.txt` de las parejas bisync, antes de la huella.

    Es lo único que la lectura puede escribir (`bisync.filters_file_for()`). Hecho
    aquí, los lectores de después lo encuentran al día y no escriben, y la huella
    se toma con `filters/` ya como va a quedar. Sigue con las demás parejas si
    una falla y lanza el primer error al final.
    """
    from common import bisync

    primero = None
    for pair in config.pairs:
        if not pair.is_bisync:
            continue
        try:
            bisync.filters_file_for(pair)
        except Exception as error:                   # noqa: BLE001
            primero = primero or error
    if primero is not None:
        raise primero


def _device_id() -> str | None:
    """Devuelve el id de este dispositivo, o `None` si no consta."""
    from common import fleet
    return fleet.device_id() or None


def _raiz_fisica(device_id: str | None) -> Path | None:
    """Devuelve la raíz física del contenedor de ese dispositivo, o `None`.

    Sin id no se busca nada: recorrer las unidades para no encontrarlo es lo más
    caro de la lectura.
    """
    if not device_id:
        return None
    from common import vestibulo
    return vestibulo.raiz_fisica(device_id)


def leer(config: Config, *,
         notas: Callable[[Config], Mapping[str, str]] | None = None,
         linea_llavero: Callable[[Config], Linea | None] | None = None) -> Instantanea:
    """Lee del dispositivo todo lo que pinta la ventana, de una sola vez.

    Está pensada para un hilo de fondo: no toca Tk, y devuelve datos. Nunca
    lanza: cada campo se lee bajo su propio `try`, el que falla queda en su
    valor por defecto y su error (`repr`) en `fallos`, y se sigue con el resto.
    Es un punto de sustitución: los tests la cambian por algo que devuelve una
    `Instantanea`.

    Empieza regenerando los ficheros de filtros que falten o hayan cambiado (lo
    único que puede escribir), toma la huella y solo entonces lee. La raíz física
    se busca una vez (un `stat` por unidad) y se la dan los lectores que la
    necesitan. El id del dispositivo lo preguntan por su cuenta los lectores que
    solo tienen el id (`cifrado.bloqueo()`, `watch.resumen()`).

    Args:
        config: La config que se pinta.
        notas: Cómo se saben las notas de resync por pareja; por defecto
            `ui.pair_status_notes`. La ventana principal pasa la suya, la del
            espacio de nombres de `ui.tk`, para que los tests que la sustituyen
            sigan valiendo.
        linea_llavero: Cómo se lee la línea del llavero; por defecto
            `linea_del_llavero`. Ídem.

    Returns:
        La instantánea, con `fallos` vacío si todo se leyó.
    """
    hecha = time.time()
    fallos: dict[str, str] = {}

    def intentar(campo: str, leer_campo: Callable[[], Any], defecto: Any) -> Any:
        """Lee un campo; si falla, apunta el error y devuelve su valor por defecto."""
        try:
            return leer_campo()
        except Exception as error:                   # noqa: BLE001
            fallos[campo] = repr(error)
            return defecto

    sello = intentar("firma", lambda: firma(config), ())
    intentar("filtros", lambda: _regenerar_filtros(config), None)
    huella = intentar("huella", lambda: tomar_huella(config), None)

    device_id = intentar("device_id", _device_id, None)
    fisica = intentar("fisica", lambda: _raiz_fisica(device_id), None)

    def leer_notas() -> dict[str, str]:
        lector = notas
        if lector is None:
            from . import pair_status_notes as lector
        return dict(lector(config))

    def leer_hallazgos() -> tuple[tuple, int]:
        from common import revision
        encontrados = tuple(revision.revisar(config, fisica=fisica))
        return encontrados, revision.cuenta(list(encontrados))

    def leer_componentes() -> tuple[tuple, str | None, bool]:
        from common import components
        pendientes = list(components.pendientes(fisica=fisica))
        return (tuple(pendientes),
                components.resumen(pendientes) if pendientes else None,
                bool(components.actualizables(pendientes)))

    def leer_conflictos() -> dict[str, int]:
        from common import conflicts
        return conflicts.contar(conflicts.cargar(config))

    def leer_expulsion() -> Path | None:
        from . import cifrado
        return cifrado.expulsion(fisica=fisica)

    def leer_bloqueo() -> str | None:
        from . import cifrado
        return cifrado.bloqueo()

    def leer_del_equipo() -> bool:
        from common import model
        return bool(model.es_equipo())

    def leer_vigilante() -> Resumen:
        from . import watch
        return watch.resumen()

    def leer_llavero() -> Linea | None:
        return (linea_llavero or linea_del_llavero)(config)

    estados = intentar("estados", lambda: estados_de(config), {})
    notas_pareja = intentar("notas", leer_notas, {})
    hallazgos, cuenta = intentar("hallazgos", leer_hallazgos, ((), 0))
    conflictos = intentar("conflictos", leer_conflictos, {})
    componentes, texto, actualizables = intentar(
        "componentes", leer_componentes, ((), None, False))
    expulsion = intentar("expulsion", leer_expulsion, None)
    bloqueo = intentar("bloqueo", leer_bloqueo, None)
    del_equipo = intentar("del_equipo", leer_del_equipo, False)
    try:
        vigilante = leer_vigilante()
    except Exception as error:                       # noqa: BLE001
        fallos["vigilante"] = repr(error)
        vigilante = _vigilante_vacio()
    llavero = intentar("llavero", leer_llavero, None)

    return Instantanea(
        estados=estados, notas=notas_pareja, hallazgos=hallazgos, cuenta=cuenta,
        conflictos=conflictos, componentes=componentes, componentes_texto=texto,
        componentes_actualizables=actualizables, fisica=fisica, expulsion=expulsion,
        bloqueo=bloqueo, del_equipo=del_equipo, vigilante=vigilante, llavero=llavero,
        device_id=device_id, fallos=fallos, hecha=hecha, firma=sello, huella=huella)


def vacia(config: Config) -> Instantanea:
    """Devuelve una instantánea sin nada: lo que la ventana guarda si el hilo falló.

    Importa `ui.watch` (su vigilante es «no se sabe»). No lleva huella, así que
    no vale para nadie: `Compartida.para()` no la reparte, y quien la reciba
    calcula lo suyo.
    """
    try:
        sello = firma(config)
    except Exception:                                # noqa: BLE001
        sello = ()
    return Instantanea(firma=sello)


class Compartida:
    """La última lectura de la ventana principal, que reparte a las demás pantallas.

    Solo se toca desde el hilo de Tk: `poner()` la llama quien recibe la lectura
    del hilo, y las pantallas se suscriben para repintar lo suyo cuando llega una
    nueva.

    Attributes:
        actual: La última puesta, o `None` si todavía no ha llegado ninguna.
    """

    def __init__(self) -> None:
        """Empieza sin ninguna lectura y sin suscritos."""
        self.actual: Instantanea | None = None
        self._suscritos: list[Callable[[Instantanea], None]] = []

    def poner(self, inst: Instantanea) -> None:
        """Guarda la lectura y avisa a cada suscrito, pasándosela.

        Avisa a todos aunque alguno falle (una ventana a medio cerrar no debe
        dejar sin aviso a las demás) y vuelve a lanzar el primer error al final:
        no se esconde.

        Args:
            inst: La lectura nueva.
        """
        self.actual = inst
        primero = None
        for aviso in list(self._suscritos):
            try:
                aviso(inst)
            except Exception as error:               # noqa: BLE001
                primero = primero or error
        if primero is not None:
            raise primero

    def suscribir(self, funcion: Callable[[Instantanea], None]) -> Callable[[], None]:
        """Pide que se llame a `funcion(instantanea)` cada vez que llegue una lectura.

        Returns:
            La función que da de baja la suscripción; llamarla otra vez no hace
            nada.
        """
        self._suscritos.append(funcion)

        def baja() -> None:
            if funcion in self._suscritos:
                self._suscritos.remove(funcion)

        return baja

    def para(self, config: Config) -> Instantanea | None:
        """Devuelve la última lectura si sigue valiendo para esa config, o `None`.

        Quien recibe `None` lee lo suyo, como si no hubiera lectura compartida.
        """
        actual = self.actual
        return actual if actual is not None and actual.vigente(config) else None
