#!/usr/bin/env python3
"""Qué se puede hacer con una avería, sin Tkinter.

Mismo guion que `pair_editor` y `conflict_editor`, y por el mismo motivo: aquí
se piensa un plan y se enseñan sus consecuencias, y solo si la persona dice que
sí se toca el disco. Apartar un baseline es la operación que puede acabar en un
borrado masivo, así que no hay ninguna reparación que ocurra sola, ni al abrir
la pantalla ni después.

Qué está mal lo dice `common/revision.py`; aquí solo se contesta a «¿y qué hago
con esto?». Hay tres respuestas posibles:
- un plan (`plan_*`), que se confirma y se ejecuta;
- una orden para `sync.py` (`args_*`), que se lanza en la ventana de salida
  porque eso es una sincronización de verdad, con su registro y su log;
- nada, que es el caso de la carpeta local que no está (ver `revision._local`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from common import bisync, model, store
from common.model import Config, Pair
from common.revision import Hallazgo, aviso_carpeta_programa

from . import prefs


class ReparacionImposible(Exception):
    """Lo que se pide no se puede hacer; el mensaje es para la persona."""


def borrar(ruta: Path) -> None:
    """Borra un fichero.

    Es de módulo para que un test lo haga fallar.
    """
    ruta.unlink()


def apartar(nombre: str) -> Path | None:
    """Aparta el baseline de esa pareja.

    Es de módulo para que un test lo haga fallar.
    """
    return bisync.shelve_baseline(nombre)


def sincronizacion_en_curso() -> str | None:
    """Devuelve quién está sincronizando ahora mismo, o `None` si nadie.

    Se mira antes de borrar un bloqueo, que es lo único de aquí que podría
    hacer daño en caliente: quitarle el lock a una pasada viva deja que empiece
    otra sobre los mismos ficheros. Ante la duda se dice que sí lo hay: un
    registro de OTRO equipo no se puede comprobar (`pid_alive` solo sabe de los
    procesos de esta máquina) y equivocarse hacia «no se puede borrar» no rompe
    nada, mientras que equivocarse hacia el otro lado sí. Uno de este equipo
    pero de antes de reiniciar sí se sabe que es un resto: su pid ya es de otro
    proceso.
    """
    info = store.read_json(model.daemon_lock())
    if not info:
        return None
    host = info.get("host")
    try:
        pid = int(info.get("pid", -1))
    except (TypeError, ValueError):
        pid = -1
    if host == prefs.HOST and not store.vivo_en_este_arranque(info, prefs.HOST):
        return None                     # rastro de un servicio que ya no está
    quien = "el servicio periódico" if host == prefs.HOST else f"el servicio de {host}"
    return f"{quien} (pid {pid})"


@dataclass
class RepairPlan:
    """Lo que se va a hacer, antes de hacerlo.

    Mismo contrato que `pair_editor.EditPlan`: `consequences` y `warnings` se
    enseñan en `tk_pairs.confirmar_plan()` y `execute()` solo se llama si la
    persona ha dicho que sí.

    Args:
        titulo: Cómo se llama la reparación.
        consequences: Una línea por consecuencia.
        warnings: Lo que conviene saber antes de confirmar.
        _hacer: Lo que toca el disco; devuelve qué ha hecho.
    """
    titulo: str
    consequences: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    _hacer: Callable[[], list[str]] | None = None

    def execute(self) -> list[str]:
        """Hace la reparación y devuelve qué ha hecho, para poder contarlo."""
        return list(self._hacer()) if self._hacer is not None else []


def _pareja(config: Config, nombre: str | None) -> Pair:
    """Devuelve la pareja de ese nombre.

    Raises:
        ReparacionImposible: Si ya no está en la configuración.
    """
    pair = next((p for p in config.pairs if p.name == nombre), None)
    if pair is None:
        raise ReparacionImposible(
            f"La pareja «{nombre}» ya no está en la configuración: vuelve a abrir "
            "la pantalla para ver cómo está ahora.")
    return pair


def plan_apartar(config: Config, hallazgo: Hallazgo) -> RepairPlan:
    """Devuelve el plan de apartar el baseline de una pareja.

    Es para rehacerlo con un `--resync`. Se APARTA, no se borra: el directorio
    se renombra a `state/<pareja>.old-…` y queda inerte, por si hiciera falta
    volver a mirarlo. Y no se reaprovecha bajo el nombre nuevo, que es la
    tentación: eso le diría a bisync que el listado del destino viejo describe
    el nuevo y todo lo que no estuviera en el nuevo se leería como borrado.

    Raises:
        ReparacionImposible: Si la pareja o su baseline ya no están.
    """
    pair = _pareja(config, hallazgo.pareja)
    estado = bisync.pair_state(pair)
    if not estado.has_baseline:
        raise ReparacionImposible(
            f"«{pair.name}» ya no tiene baseline que apartar. Vuelve a abrir la "
            "pantalla para ver cómo está ahora.")

    def hacer() -> list[str]:
        """Aparta el baseline y dice dónde ha quedado."""
        destino = apartar(pair.name)
        if destino is None:
            raise ReparacionImposible(
                f"No he encontrado el baseline de «{pair.name}» para apartarlo.")
        return [f"El baseline de «{pair.name}» está ahora en {destino.name}"]

    return RepairPlan(
        f"Apartar el baseline de «{pair.name}»",
        [f"El contenido de state/{pair.name}/ se mueve a state/{pair.name}.old-<fecha>/",
         f"«{pair.name}» queda como si nunca se hubiera sincronizado",
         "No se borra nada: el baseline apartado se queda ahí, inerte"],
        ["Hasta que hagas el --resync, esa pareja se salta en cada pasada.",
         "El --resync vuelve a comparar los dos lados enteros y puede tardar."],
        hacer)


def plan_locks(config: Config, hallazgo: Hallazgo) -> RepairPlan:
    """Devuelve el plan de borrar los `.lck` que dejó una pasada cortada a medias.

    Lo único que hace falta saber para que esto sea seguro es que no haya nada
    sincronizando, y eso el programa sí lo sabe: el servicio se apunta en
    `state/daemon.lock.json` y la ventana, mientras hay una pasada en curso,
    apaga lo que toca el mismo estado.

    Raises:
        ReparacionImposible: Si hay una sincronización en marcha o los bloqueos
            ya no están.
    """
    pair = _pareja(config, hallazgo.pareja)
    ocupado = sincronizacion_en_curso()
    if ocupado:
        raise ReparacionImposible(
            f"Ahora mismo está sincronizando {ocupado}. Un bloqueo solo se borra "
            "cuando no hay ninguna pasada en marcha: espera a que termine.")

    sueltos = [Path(r) for r in hallazgo.dato if Path(r).exists()]
    if not sueltos:
        raise ReparacionImposible(
            f"Los bloqueos de «{pair.name}» ya no están: seguramente los ha "
            "soltado la pasada que los dejó.")

    def hacer() -> list[str]:
        """Borra los bloqueos sueltos y dice cuáles."""
        hechos = []
        for ruta in sueltos:
            try:
                borrar(ruta)
                hechos.append(f"Borrado {ruta.name}")
            except FileNotFoundError:
                pass                      # ya no estaba: lo que se quería
            except OSError as e:
                raise ReparacionImposible(
                    f"No se ha podido borrar {ruta.name}:\n\n{e}") from e
        return hechos

    return RepairPlan(
        f"Borrar los bloqueos de «{pair.name}»",
        [f"Se borran {len(sueltos)} fichero(s) de bloqueo en state/{pair.name}/",
         "No se toca ningún fichero tuyo: un .lck solo dice «aquí hay una pasada»"],
        ["Si hubiera una sincronización en marcha que no consta, quedaría sin su "
         "bloqueo y otra podría empezar encima. Comprueba que no la haya."],
        hacer)


PLANES = {"prefijo": plan_apartar, "lock": plan_locks}
"""Qué plan resuelve cada clave de hallazgo."""


def plan_para(config: Config, hallazgo: Hallazgo) -> RepairPlan:
    """Devuelve el plan de esa avería.

    Raises:
        ReparacionImposible: Si no tiene.
    """
    fabricar = PLANES.get(hallazgo.clave)
    if fabricar is None:
        raise ReparacionImposible("Esta avería no se arregla desde aquí.")
    return fabricar(config, hallazgo)


def tiene_plan(hallazgo: Hallazgo) -> bool:
    """Indica si esa avería tiene un plan de reparación."""
    return hallazgo.clave in PLANES


def args_resync(hallazgo: Hallazgo) -> list[str]:
    """Devuelve los argumentos de `sync.py` para rehacer el baseline de esa pareja.

    Lleva `--yes` porque la pregunta ya se ha hecho: quien pulsa aquí acaba de
    leer en su confirmación qué es un resync. Sin él, `sync.py` la haría por
    stdin, que detrás de una ventana no existe, y la pareja se saltaría.
    """
    return [str(hallazgo.pareja), "--resync", "--yes"]


def args_simular(nombres: list[str]) -> list[str]:
    """Devuelve los argumentos de `sync.py` para una pasada de mentira de esas parejas.

    Sin `--yes`, a propósito y por lo mismo que en
    `pair_editor.simular_args()`: una pareja sin baseline tiene que volver
    «Saltada: requiere --resync», que es justo lo que interesa leer antes de
    aprobar nada.
    """
    return [*nombres, "--dry-run"]


def aviso_resync(hallazgo: Hallazgo) -> RepairPlan:
    """Devuelve el plan, sin disco, de confirmar un resync.

    No es un plan de disco (lo hace rclone), pero se confirma igual: es la
    operación que vuelve a comparar los dos lados enteros.

    Si el hallazgo trae la copia de la carpeta del programa que subió una pareja
    de la raíz entera (`dato`), lo avisa aquí y no después: el resync deja de
    subirla pero no la borra, y el listado nuevo ya no la enseñaría.
    """
    avisos = ["Puede tardar, según lo que haya que listar.",
              "Si la pareja guarda versiones, lo que el resync sobrescriba se guarda "
              "en .prversions/."]
    if hallazgo.dato:
        avisos.append(aviso_carpeta_programa(hallazgo.dato[0]))
    return RepairPlan(
        f"Resincronizar «{hallazgo.pareja}»",
        ["Se rehace el baseline de la pareja: rclone compara los dos lados "
         "enteros y se queda con lo que hay ahora en cada uno",
         "No se borra nada por estar en un solo lado: un resync junta, no iguala"],
        avisos)


def hallazgos_reparables(hallazgos: list[Hallazgo]) -> list[Hallazgo]:
    """Devuelve los hallazgos que tienen algún botón.

    Es un plan o una pasada que lanzar.
    """
    return [h for h in hallazgos if tiene_plan(h) or h.clave in ("resync", "conflicto")]

