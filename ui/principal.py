#!/usr/bin/env python3
"""Lo que enseña y deja pulsar la ventana principal, decidido sin Tk.

`estado()` junta lo que se sabe (el config, las horas de las pasadas, lo último
que se leyó del dispositivo) en un `Estado`: un valor congelado que se compara
por contenido, y que dice qué escribe cada bloque de la ventana. `controles()`
dice, de ese `Estado`, qué controles se ven y cuáles se pueden pulsar: la tabla
de «desactivado ⇔ ocupado». Nada de aquí abre una ventana ni toca el disco, así
que se prueba como una tabla (`tests/test_principal.py`) y `ui/tk_principal.py`
solo dibuja lo que dice.

Es pura y tiene que cargarse antes del primer pintado: arriba solo importa la
biblioteca estándar, `common.model` (que toda ventana carga con `ui.prefs`) y
`ui.cuando`. `ui.watch` (con él, `common.fleet` y `common.components`) y
`ui.llavero_editor` se importan dentro de `estado()` y solo con una lectura en
la mano: esa lectura ya los ha cargado, y el primer pintado, que no la tiene, no
paga ninguno.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Collection, Mapping, NamedTuple

from common import model

from . import cuando

if TYPE_CHECKING:
    from common.model import Config
    from common.update import Release

    from .instantanea import Instantanea
    from .watch import Resumen

INICIAR = "iniciar"
"""La acción del botón del servicio que arranca el servicio de `runsync`.

Es `watch.INICIAR`, repetido a propósito para no importar `ui.watch` (y con él
`common.fleet`) antes del primer pintado; `tests/test_principal.py` los ata.
"""
EXPULSAR = "expulsar"
"""El pie con «Expulsar»: cierra el llavero y el contenedor, o el llavero solo."""
BLOQUEAR = "bloquear"
"""El pie con «Bloquear»: cierra la raíz cifrada de este equipo, que lo hace el agente."""
MARCAR_TODAS = "Marcar todas"
"""El texto del botón de la lista cuando hay casillas sin marcar."""
DESMARCAR_TODAS = "Desmarcar todas"
"""El texto del botón de la lista cuando están todas marcadas."""


def corto(texto: str, maximo: int = 30) -> str:
    r"""Devuelve una ruta recortada por delante, que es por donde sobra.

    En el dispositivo esto no hace nada (`DEVICE_ROOT` es `F:\`), pero montado
    en un punto con nombre largo (`/media/quien/PRDRIVE`) o corriendo desde el
    repositorio, una ruta entera estira la ventana hasta salirse de la
    pantalla.
    """
    return texto if len(texto) <= maximo else "…" + texto[-(maximo - 1):]


class Fila(NamedTuple):
    """Una pareja de la lista.

    Args:
        nombre: El nombre de la pareja.
        modo: El nombre de su modo (`bisync`, `up`…).
        cuando: Cuándo se sincronizó bien por última vez, o «—» si nunca.
        chip: El texto y el tipo del chip de la fila (su nota, o la cuenta de
            conflictos), o `None` si no tiene.
    """
    nombre: str
    modo: str
    cuando: str
    chip: tuple[str, str] | None


class Linea(NamedTuple):
    """Una línea de estado con botón: la del llavero o la del arranque automático.

    Args:
        texto: Lo que dice.
        aviso: Si va en ámbar.
        boton: Lo que dice el botón.
        activo: Si el botón se puede pulsar.
    """
    texto: str
    aviso: bool
    boton: str
    activo: bool

    @property
    def dibujo(self) -> tuple[str, bool, str]:
        """Lo que se dibuja de la línea: `(texto, aviso, boton)`.

        `activo` no va aquí: el botón se enciende o se apaga aparte, en
        `VistaPrincipal._poner_activos`.
        """
        return (self.texto, self.aviso, self.boton)


@dataclass(frozen=True)
class Estado:
    """Todo lo que la ventana principal escribe, ya decidido.

    Se compara por contenido: dos `Estado` iguales pintan lo mismo, y la vista
    no toca un bloque cuyo trozo no ha cambiado.

    Args:
        dispositivo: La raíz del dispositivo, recortada, para la cabecera.
        remotos: Los remotos de las parejas, recortados, para la cabecera.
        chip: El chip de la cabecera: texto, tipo (`Ok.`, `Aviso.`…) e icono
            (`None` si no lleva).
        aviso: El aviso de arranque, que se puede descartar; `None` si no hay.
        reparacion: Cuántas cosas hay que revisar. La línea de «Reparación…» se
            enseña con más de 0 y sin pasada en curso (`controles`).
        version: El texto del aviso de versión nueva; `None` si no hay.
        componentes: El texto del aviso de componentes anticuados. Solo hay uno
            de los dos avisos: con versión nueva, `None`.
        componentes_boton: Si el aviso de componentes lleva «Actualizar…».
        filas: Las parejas, en el orden del config.
        ultima: «última pasada …» con la hora de la más reciente, o "" si
            ninguna ha corrido.
        marcadas: Las parejas cuya casilla nace marcada. Una fila que ya
            existe conserva la suya.
        llavero: La línea del llavero; `None` si el dispositivo no lo lleva o
            aún no se ha leído.
        arranque: La línea del arranque automático; `None` si no hay nada que
            decir o aún no se ha leído.
        pausa: La frase que va debajo de la línea del arranque; `None` si no
            hay.
        servicio: La acción (`watch.INICIAR`, `PAUSAR`, `REANUDAR`, `SEGUIR`) y
            el texto del botón del servicio.
        pie: `EXPULSAR`, `BLOQUEAR` o `None` si el pie no lleva el segundo botón.
        en_curso: Si hay una pasada en curso lanzada desde la ventana.
        cargando: Si la lectura del dispositivo aún no ha llegado.
    """
    dispositivo: str
    remotos: str
    chip: tuple[str, str, str | None]
    aviso: str | None
    reparacion: int
    version: str | None
    componentes: str | None
    componentes_boton: bool
    filas: tuple[Fila, ...]
    ultima: str
    marcadas: frozenset[str]
    llavero: Linea | None
    arranque: Linea | None
    pausa: str | None
    servicio: tuple[str, str]
    pie: str | None
    en_curso: bool
    cargando: bool


def estado(config: Config, *, aviso: str | None, nueva: Release | None,
           instalada: str | None, tiempos: Mapping[str, float | None],
           marcadas: Collection[str], en_curso: bool, inst: Instantanea | None,
           vigilante: Resumen | None = None) -> Estado:
    """Devuelve lo que la ventana principal escribe con lo que se sabe ahora.

    Es pura: no lee ni escribe nada.

    Args:
        config: La configuración del dispositivo.
        aviso: El aviso de arranque; "" o `None` si no hay.
        nueva: La release pendiente (lo que dice la caché, no la red), o `None`.
        instalada: La versión instalada; "" o `None` si se desconoce.
        tiempos: Cuándo se sincronizó bien cada pareja por última vez
            (`ui.pair_times`); `None` o 0 para las que no han corrido.
        marcadas: Las parejas cuya casilla nace marcada.
        en_curso: Si hay una pasada en curso.
        inst: Lo último que se leyó del dispositivo (`ui.instantanea`), o
            `None` si aún no ha llegado: es el primer pintado, que sale solo
            de lo anterior y no enseña nada que dependa de la lectura.
        vigilante: Lo que la ventana le ha pedido al agente y la lectura aún no
            ha visto (`watch.pedido`, `watch.tras_servicio`): manda sobre el
            `vigilante` de `inst`. Sin lectura no se mira.

    Returns:
        El `Estado`.
    """
    cargando = inst is None
    pendientes = 0 if inst is None else inst.cuenta
    remotos = sorted({p.remote_name for p in config.pairs}) or [model.DEFAULT_REMOTE]

    # El chip dice lo que se sabe sin hablar con nadie: lo que hay apuntado en
    # state/. Es una sola cuenta, la misma que la línea de «Reparación…».
    if en_curso:
        chip = ("sincronizando…", "Acento.", "sync")
    elif cargando:
        chip = ("…", "", None)
    elif pendientes:
        chip = (f"{pendientes} que revisar" if pendientes > 1 else "1 que revisar",
                "Aviso.", "warn")
    else:
        chip = ("al día", "Ok.", "ok")

    version = None
    if nueva is not None:
        version = (f"Hay una actualización: {nueva.tag}\n"
                   f"Tienes la {instalada or 'desconocida'}. "
                   "«Actualizar…» baja la versión nueva y reabre la ventana.")
    # Los componentes son un `elif` de la versión nueva: los pines viajan CON el
    # programa, así que actualizarlo primero puede mover lo que toca; ofrecer
    # las dos cosas a la vez sería pedir el mismo trabajo dos veces y en el
    # orden malo.
    componentes, componentes_boton = None, False
    if version is None and inst is not None and inst.componentes_texto:
        componentes = ("Lo que lleva el dispositivo de fuera (rclone, Python, VeraCrypt) "
                       "no es lo que fija esta versión:\n" + inst.componentes_texto)
        componentes_boton = bool(inst.componentes_actualizables)

    notas = {} if inst is None else inst.notas
    cuentas = {} if inst is None else inst.conflictos
    filas = []
    for pareja in config.del_usuario:
        chip_fila = None
        if pareja.name in notas:
            chip_fila = (notas[pareja.name], "Aviso.")
        elif pareja.name in cuentas:
            # Se queda hasta que no quede ninguna copia en disco: no es un
            # suceso que se lee y se olvida, es un estado de la carpeta.
            cuantos = cuentas[pareja.name]
            chip_fila = ("1 conflicto" if cuantos == 1 else f"{cuantos} conflictos", "Aviso.")
        filas.append(Fila(pareja.name, pareja.mode.name,
                          cuando(tiempos.get(pareja.name)) or "—", chip_fila))
    ultima = cuando(max((m for m in tiempos.values() if m), default=None))

    llavero = arranque = pausa = pie = None
    servicio = (INICIAR, "Iniciar servicio")
    if inst is not None:
        from . import watch

        # Qué hace este equipo al enchufar y qué es el botón del servicio: de
        # lo que la ventana ha pedido y aún no se ha visto, o de la lectura.
        res = vigilante if vigilante is not None else inst.vigilante
        dicho = watch.linea(res)
        if dicho is not None:
            arranque = Linea(dicho.texto, dicho.aviso, dicho.boton, True)
            pausa = watch.pausa(res)
        del_servicio = watch.boton_servicio(res)
        servicio = (del_servicio.accion, del_servicio.texto)
        if inst.llavero is not None:
            from . import llavero_editor

            llavero = Linea(inst.llavero.texto, inst.llavero.aviso, llavero_editor.ABRIR,
                            inst.llavero.abrir)
        # Solo en un dispositivo que vive en un contenedor VeraCrypt, o con el
        # llavero abierto en uno que no es una carpeta de este equipo, que no
        # se quita: hay que cerrar KeePassXC y subir lo pendiente antes de
        # quitar la unidad.
        if inst.bloqueo is not None:
            pie = BLOQUEAR
        elif inst.expulsion is not None or (inst.llavero is not None and not inst.del_equipo):
            pie = EXPULSAR

    return Estado(
        dispositivo=corto(str(model.DEVICE_ROOT)), remotos=corto(", ".join(remotos)),
        chip=chip, aviso=aviso or None, reparacion=pendientes, version=version,
        componentes=componentes, componentes_boton=componentes_boton, filas=tuple(filas),
        ultima=f"última pasada {ultima}" if ultima else "", marcadas=frozenset(marcadas),
        llavero=llavero, arranque=arranque, pausa=pausa, servicio=servicio, pie=pie,
        en_curso=bool(en_curso), cargando=cargando)


class Control(NamedTuple):
    """Si un control se ve y si se puede pulsar.

    Es una pareja `(visible, activo)`: la vista, que lee lo mismo de sus
    widgets, la compara con una tupla.

    Args:
        visible: Si está en pantalla.
        activo: Si se puede pulsar. En un control que no se ve no significa
            nada: sale de la misma fórmula, y quien compara con los widgets lo
            mira solo en los que se ven.
    """
    visible: bool
    activo: bool


def controles(e: Estado) -> dict[str, Control]:
    """Devuelve, de cada control de la ventana, si se ve y si se puede pulsar.

    Es la tabla de «desactivado ⇔ ocupado»: lo que toca `state/` (una pasada,
    el servicio, las parejas, el llavero, el contenedor, los componentes) se
    apaga mientras se sincroniza, y también «Actualizar…» del programa, que
    sustituye `sync.py` y `common/` debajo de la pasada y reabre la ventana,
    cortándola. Lo que necesita la lectura del dispositivo (el estado de
    resync de «Sincronizar ahora», la foto de procesos del llavero,
    «Expulsar») no está hasta que llega. Por eso, antes de que llegue, de lo
    que toca `state/` solo se pueden pulsar «Parejas…» y «Ajustes…».

    Args:
        e: Lo que enseña la ventana.

    Returns:
        Un `Control` por cada clave: `sincronizar`, `servicio`, `parejas`,
        `ajustes`, `reparacion`, `llavero`, `pie`, `componentes`, `version`,
        `descartar`, `arranque` y `marcar_todas`.
    """
    libre = not e.en_curso
    con_lectura = libre and not e.cargando
    # «Pausar» y «Reanudar» solo dejan una petición en el buzón del agente y
    # no tocan nada de la raíz; «Iniciar servicio» cierra la ventana y arranca
    # el servicio, que escribe en state/.
    servicio_libre = e.servicio[0] != INICIAR or con_lectura
    return {
        "sincronizar": Control(True, con_lectura),
        "servicio": Control(True, servicio_libre),
        "parejas": Control(True, libre),
        "ajustes": Control(True, libre),
        "reparacion": Control(e.reparacion > 0 and libre, True),
        "llavero": Control(e.llavero is not None,
                           e.llavero is not None and e.llavero.activo and libre),
        "pie": Control(e.pie is not None, libre),
        "componentes": Control(e.componentes is not None and e.componentes_boton, libre),
        "version": Control(e.version is not None, libre),
        "descartar": Control(e.aviso is not None, True),
        "arranque": Control(e.arranque is not None, True),
        "marcar_todas": Control(len(e.filas) > 1, True),
    }


def frase_reparacion(cuantas: int) -> str:
    """Devuelve la frase de la línea de «Reparación…»: cuántas cosas hay que revisar."""
    return "Hay 1 cosa que revisar." if cuantas == 1 else f"Hay {cuantas} cosas que revisar."


def resumen_de_marcadas(marcadas: int, total: int, ultima: str) -> str:
    """Devuelve el «N de M» de la lista, con la última pasada si se sabe.

    Args:
        marcadas: Cuántas casillas hay marcadas ahora.
        total: Cuántas parejas hay.
        ultima: `Estado.ultima`.
    """
    texto = f"{marcadas} de {total}"
    if ultima:
        texto += f" · {ultima}"
    return texto


def texto_de_marcar_todas(marcadas: int, total: int) -> str:
    """Devuelve lo que dice el botón de la lista: lo que hará al pulsarlo."""
    return DESMARCAR_TODAS if marcadas == total else MARCAR_TODAS
