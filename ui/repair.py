#!/usr/bin/env python3
"""
repair.py — Qué se puede hacer con una avería. Sin Tkinter.

Mismo guion que `pair_editor` y `conflict_editor`, y por el mismo motivo: aquí
se piensa un plan y se enseñan sus consecuencias, y solo si el usuario dice que
sí se toca el disco. Apartar un baseline es la operación que puede acabar en un
borrado masivo —por eso se quitó el renombrado automático de listados—, así que
no hay ninguna reparación que ocurra sola, ni al abrir la pantalla ni después.

Qué está mal lo dice `common/revision.py`; aquí solo se contesta a «¿y qué hago
con esto?». Tres respuestas posibles:

  * un plan (`plan_*`), que se confirma y se ejecuta;
  * una orden para `sync.py` (`args_*`), que se lanza en la ventana de salida
    porque eso es una sincronización de verdad, con su registro y su log;
  * nada, que es el caso de la carpeta local que no está: ver `revision._local`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from common import bisync, model, store
from common.model import Config, Pair
from common.revision import Hallazgo

from . import prefs


class ReparacionImposible(Exception):
    """No se puede hacer, y el mensaje es para el usuario."""


# --- las operaciones de disco, de módulo para que un test las haga fallar ---

def borrar(ruta: Path) -> None:
    ruta.unlink()


def apartar(nombre: str) -> Path | None:
    return bisync.shelve_baseline(nombre)


def sincronizacion_en_curso() -> str | None:
    """Quién está sincronizando ahora mismo, si alguien. None si nadie.

    Se mira antes de borrar un bloqueo, que es lo único de aquí que podría
    hacer daño en caliente: quitarle el lock a una pasada viva deja que empiece
    otra sobre los mismos ficheros.

    Ante la duda se dice que sí lo hay. Un registro de OTRO equipo no se puede
    comprobar —`pid_alive` solo sabe de los procesos de esta máquina—, y
    equivocarse hacia «no se puede borrar» no rompe nada, mientras que
    equivocarse hacia el otro lado sí."""
    info = store.read_json(model.daemon_lock())
    if not info:
        return None
    host = info.get("host")
    try:
        pid = int(info.get("pid", -1))
    except (TypeError, ValueError):
        pid = -1
    if host == prefs.HOST and not store.pid_alive(pid):
        return None                     # rastro de un servicio que ya no está
    quien = "el servicio periódico" if host == prefs.HOST else f"el servicio de {host}"
    return f"{quien} (pid {pid})"


@dataclass
class RepairPlan:
    """Lo que se va a hacer, antes de hacerlo.

    Mismo contrato que `pair_editor.EditPlan`: `consequences` y `warnings` se
    enseñan en `tk_pairs.confirmar_plan()` y `execute()` solo se llama si el
    usuario ha dicho que sí. Devuelve qué ha hecho, para poder contarlo."""
    titulo: str
    consequences: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    _hacer: Callable[[], list[str]] | None = None

    def execute(self) -> list[str]:
        return list(self._hacer()) if self._hacer is not None else []


def _pareja(config: Config, nombre: str | None) -> Pair:
    pair = next((p for p in config.pairs if p.name == nombre), None)
    if pair is None:
        raise ReparacionImposible(
            f"La pareja «{nombre}» ya no está en la configuración: vuelve a abrir "
            "la pantalla para ver cómo está ahora.")
    return pair


# ---------------------------------------------------------------------------
# Apartar un baseline que no es de esta pareja
# ---------------------------------------------------------------------------

def plan_apartar(config: Config, hallazgo: Hallazgo) -> RepairPlan:
    """Aparta el baseline de una pareja para que se rehaga con un --resync.

    Se APARTA, no se borra: el directorio se renombra a `state/<pareja>.old-…`
    y queda inerte, por si hiciera falta volver a mirarlo. Y no se reaprovecha
    bajo el nombre nuevo, que es la tentación: eso le diría a bisync que el
    listado del destino viejo describe el nuevo, y todo lo que no estuviera en
    el nuevo se leería como borrado."""
    pair = _pareja(config, hallazgo.pareja)
    estado = bisync.pair_state(pair)
    if not estado.has_baseline:
        raise ReparacionImposible(
            f"«{pair.name}» ya no tiene baseline que apartar. Vuelve a abrir la "
            "pantalla para ver cómo está ahora.")

    def hacer() -> list[str]:
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


# ---------------------------------------------------------------------------
# Borrar bloqueos que han quedado sueltos
# ---------------------------------------------------------------------------

def plan_locks(config: Config, hallazgo: Hallazgo) -> RepairPlan:
    """Borra los `.lck` que dejó una pasada cortada a medias.

    Lo único que hace falta saber para que esto sea seguro es que no haya nada
    sincronizando, y eso el programa sí lo sabe: el servicio se apunta en
    `state/daemon.lock.json` y la ventana, mientras hay una pasada en curso,
    apaga lo que toca el mismo estado."""
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


def plan_para(config: Config, hallazgo: Hallazgo) -> RepairPlan:
    """El plan de esa avería. `ReparacionImposible` si no tiene."""
    fabricar = PLANES.get(hallazgo.clave)
    if fabricar is None:
        raise ReparacionImposible("Esta avería no se arregla desde aquí.")
    return fabricar(config, hallazgo)


def tiene_plan(hallazgo: Hallazgo) -> bool:
    return hallazgo.clave in PLANES


# ---------------------------------------------------------------------------
# Lo que no es un plan, sino una pasada de sync.py
# ---------------------------------------------------------------------------

def args_resync(hallazgo: Hallazgo) -> list[str]:
    """Rehacer el baseline de esa pareja.

    Con `--yes` porque la pregunta ya se ha hecho: quien pulsa aquí acaba de
    leer en su confirmación qué es un resync. Sin él, `sync.py` la haría por
    stdin, que detrás de una ventana no existe, y la pareja se saltaría."""
    return [str(hallazgo.pareja), "--resync", "--yes"]


def args_simular(nombres: list[str]) -> list[str]:
    """Una pasada de mentira de esas parejas.

    Sin `--yes`, a propósito y por lo mismo que en `pair_editor.simular_args()`:
    una pareja sin baseline tiene que volver «Saltada: requiere --resync», que es
    justo lo que interesa leer antes de aprobar nada."""
    return [*nombres, "--dry-run"]


def aviso_resync(hallazgo: Hallazgo) -> RepairPlan:
    """El resync no es un plan de disco —lo hace rclone—, pero se confirma igual:
    es la operación que vuelve a comparar los dos lados enteros."""
    return RepairPlan(
        f"Resincronizar «{hallazgo.pareja}»",
        ["Se rehace el baseline de la pareja: rclone compara los dos lados "
         "enteros y se queda con lo que hay ahora en cada uno",
         "No se borra nada por estar en un solo lado: un resync junta, no iguala"],
        ["Puede tardar, según lo que haya que listar.",
         "Si la pareja guarda versiones, lo que el resync sobrescriba se guarda "
         "en .prversions/."])


def hallazgos_reparables(hallazgos: list[Hallazgo]) -> list[Hallazgo]:
    """Los que tienen algún botón: un plan, o una pasada que lanzar."""
    return [h for h in hallazgos if tiene_plan(h) or h.clave in ("resync", "conflicto")]


