#!/usr/bin/env python3
"""
pair_editor.py — Alta, edición y baja de parejas. Sin Tkinter.

Aquí no se dibuja nada: la pantalla (`ui/tk_pairs.py`) pide un plan, enseña sus
consecuencias y, si el usuario confirma, lo ejecuta. Esa separación existe porque
lo delicado no es el formulario, es lo que pasa en disco.

Lo delicado, en una frase: **cambiar un extremo de una pareja bisync sin apartar
su baseline puede provocar borrados masivos.** El nombre de los listados sale de
los extremos (`bisync.expected_prefix`), así que al cambiar uno,
`normalize_prefix()` renombraría el baseline viejo al nombre nuevo y bisync
compararía el listado del destino ANTERIOR contra el destino NUEVO: todo lo que
no estuviera en el nuevo se leería como borrado y se propagaría. Esa función se
escribió para un caso benigno (el pen pasa de G: a F:) y no puede distinguirlo
del maligno. Por eso el plan aparta el baseline él mismo.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, NamedTuple

from common import bisync, config_file, model
from common.model import Config, ConfigError

# Los campos de los que depende el nombre de los listados de bisync. Tocar
# cualquiera de ellos invalida el baseline (ver el docstring del módulo).
ENDPOINT_KEYS = ("local", "remote", "remote_path", "mode")

# Lo que edita el formulario. El resto de claves de la pareja (flags,
# extra_flags, use_filters_file...) se conservan tal cual: la UI no las toca,
# porque la regla del proyecto es que los flags de rclone se escriben en el TOML.
FORM_KEYS = ("name", "local", "remote_path", "remote", "mode", "include", "exclude")

MIRROR_MODES = ("up-mirror", "down-mirror")
NOMBRE_PROHIBIDO = set('/\\:*?"<>|')


class PairRow(NamedTuple):
    """Una línea de la lista de parejas."""
    name: str
    mode: str
    local: str
    remote: str
    estado: str
    aviso: str | None      # lo que hay que mirar dos veces


def _mode_of(pair: Mapping[str, Any]) -> str:
    return pair.get("mode", model.DEFAULT_MODE)


def mirror_warning(mode: str) -> str | None:
    if mode not in MIRROR_MODES:
        return None
    destino = "el NAS" if model.MODES[mode].dest == "remote" else "el pen"
    return (f"Modo '{mode}': es un espejo, BORRA en {destino} lo que no esté en el "
            f"origen. Pruébalo antes con --dry-run.")


def rows(config: Config) -> list[PairRow]:
    """Lo que se pinta en la lista, con el estado ya resuelto."""
    salida = []
    for pair in config.pairs:
        estado = "—"
        aviso = mirror_warning(pair.mode.name)
        if pair.is_bisync:
            state = bisync.pair_state(pair)
            filtros = bisync.filters_state(bisync.filters_file_for(pair))
            estado = state.status
            if filtros.needs_resync:
                estado += f", filtros {filtros.status}"
            if aviso is None and bisync.resync_reasons(pair, state):
                aviso = "requiere resync"
        salida.append(PairRow(pair.name, pair.mode.name, pair.local_endpoint,
                              pair.remote_endpoint, estado, aviso))
    return salida


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------

def validate(raw: Mapping[str, Any], edited: Mapping[str, Any],
             original_name: str | None) -> list[str]:
    """Problemas que impiden guardar. Lista vacía = adelante."""
    problemas = []
    name = str(edited.get("name") or "").strip()

    if not name:
        problemas.append("El nombre no puede estar vacío.")
    elif NOMBRE_PROHIBIDO & set(name) or name in (".", ".."):
        problemas.append(
            "El nombre es también el de una carpeta dentro de state/, así que no "
            'puede llevar / \\ : * ? " < > |')
    otros = [p.get("name") for p in raw.get("pair", []) if p.get("name") != original_name]
    if name and name in otros:
        problemas.append(f"Ya hay otra pareja que se llama '{name}'.")

    if not str(edited.get("local") or "").strip():
        problemas.append("Falta la ruta local (relativa a la raíz del pen).")
    if not str(edited.get("remote_path") or "").strip():
        problemas.append("Falta la ruta en el remoto.")
    if edited.get("mode") not in model.MODES:
        problemas.append(f"Modo inválido. Válidos: {', '.join(sorted(model.MODES))}.")
    return problemas


# ---------------------------------------------------------------------------
# Planes: primero qué va a pasar, y solo después hacerlo
# ---------------------------------------------------------------------------

class Move(NamedTuple):
    origen: Path
    destino: Path


@dataclass
class EditPlan:
    """El resultado de pensar un cambio, antes de ejecutarlo.

    `consequences` se le enseña al usuario ANTES de confirmar; `execute()` solo se
    llama si dice que sí."""
    raw: dict
    consequences: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    shelve: str | None = None                       # pareja cuyo baseline apartar
    rename: tuple[str, str] | None = None           # (nombre viejo, nombre nuevo)
    borrar_filtros: list[Path] = field(default_factory=list)

    def execute(self) -> list[str]:
        """Primero el disco, luego el config. Devuelve qué se ha hecho.

        El orden no es casual. La combinación peligrosa es "config nuevo con
        baseline viejo": escribiendo el config primero, un fallo al mover el
        estado dejaría exactamente eso. Al revés, el peor caso es un baseline
        apartado de más, que se arregla con un --resync."""
        movimientos: list[Move] = []
        hechos: list[str] = []
        try:
            if self.shelve:
                destino = bisync.shelve_baseline(self.shelve)
                if destino:
                    movimientos.append(Move(model.STATE_DIR / self.shelve, destino))
                    hechos.append(f"Baseline apartado en state/{destino.name}/")
            if self.rename:
                viejo, nuevo = self.rename
                for origen, destino in bisync.rename_pair_state(viejo, nuevo):
                    movimientos.append(Move(origen, destino))
                if movimientos:
                    hechos.append(f"Estado movido de '{viejo}' a '{nuevo}'")

            config_file.save(self.raw)
            hechos.append("Config guardado (copia en sync_config.toml.bak)")
        except Exception:
            for mov in reversed(movimientos):        # dejarlo como estaba
                try:
                    mov.destino.rename(mov.origen)
                except OSError:
                    pass
            raise

        # Los filtros son datos derivados del TOML, así que se borran ya escrito
        # el config: si algo hubiera fallado antes, seguirían haciendo falta.
        for path in self.borrar_filtros:
            try:
                path.unlink(missing_ok=True)
                hechos.append(f"Borrado filters/{path.name}")
            except OSError:
                pass
        return hechos


def _pair_index(raw: Mapping[str, Any], name: str) -> int:
    for i, pair in enumerate(raw.get("pair", [])):
        if pair.get("name") == name:
            return i
    raise ConfigError(f"No hay ninguna pareja llamada '{name}'.")


def _clean(edited: Mapping[str, Any]) -> dict:
    """Los campos del formulario, sin los que se han dejado vacíos."""
    salida: dict[str, Any] = {}
    for key in FORM_KEYS:
        if key not in edited:
            continue
        value = edited[key]
        if isinstance(value, (list, tuple)):
            items = [str(v).strip() for v in value if str(v).strip()]
            if items:
                salida[key] = items
        elif str(value).strip():
            salida[key] = str(value).strip()
    return salida


def plan_save(raw: Mapping[str, Any], edited: Mapping[str, Any],
              original_name: str | None = None) -> EditPlan:
    """El plan de dar de alta (original_name=None) o de modificar una pareja."""
    problemas = validate(raw, edited, original_name)
    if problemas:
        raise ConfigError("\n".join(problemas))

    nuevo_raw = copy.deepcopy(dict(raw))
    nuevo_raw.setdefault("pair", [])
    campos = _clean(edited)
    plan = EditPlan(raw=nuevo_raw)

    if original_name is None:
        resultante = campos
        nuevo_raw["pair"].append(resultante)
        plan.consequences.append(f"Se añade la pareja '{campos['name']}'.")
        if _mode_of(campos) == "bisync":
            plan.consequences.append(
                "Al ser bisync, la primera pasada pedirá un --resync para fijar la "
                "referencia (compara ambos lados; no borra por diferencias).")
    else:
        i = _pair_index(raw, original_name)
        anterior = dict(raw["pair"][i])
        # Se parte de la pareja anterior para no perder lo que el formulario no
        # edita; las listas vaciadas a mano sí desaparecen.
        resultante = {**anterior, **campos}
        for key in ("include", "exclude"):
            if key in anterior and key not in campos:
                resultante.pop(key, None)
        nuevo_raw["pair"][i] = resultante

        cambiados = [k for k in ENDPOINT_KEYS if anterior.get(k) != resultante.get(k)]
        if cambiados:
            plan.consequences.append(
                "Cambia " + ", ".join(cambiados) + ": es de donde bisync saca el "
                "nombre de sus listados.")
            if (model.STATE_DIR / original_name).is_dir():
                plan.shelve = original_name
                plan.consequences.append(
                    f"Se apartará el baseline a state/{original_name}.old-<fecha>/ y "
                    "la pareja pedirá un --resync. Es a propósito: reaprovecharlo "
                    "haría que bisync leyera como borrados los ficheros del destino "
                    "anterior.")
        elif anterior.get("name") != resultante.get("name"):
            plan.rename = (original_name, resultante["name"])
            plan.consequences.append(
                f"Solo cambia el nombre: se mueven state/{original_name}/ y sus "
                "filtros, y el baseline sigue valiendo (el nombre de los listados no "
                "depende del nombre de la pareja).")

        if not cambiados and _mode_of(resultante) == "bisync":
            if any(anterior.get(k) != resultante.get(k) for k in ("include", "exclude")):
                plan.consequences.append(
                    "Cambian los filtros: bisync exigirá un --resync, porque no puede "
                    "saber qué ficheros excluidos existían antes.")

        if not plan.consequences:
            plan.consequences.append("El cambio no afecta al estado de bisync.")

    aviso = mirror_warning(_mode_of(resultante))
    if aviso:
        plan.warnings.append(aviso)

    model.parse_config(nuevo_raw)          # red final
    return plan


def plan_remove(raw: Mapping[str, Any], name: str, clean_state: bool = False) -> EditPlan:
    """El plan de quitar una pareja. No toca nada."""
    i = _pair_index(raw, name)
    nuevo_raw = copy.deepcopy(dict(raw))
    del nuevo_raw["pair"][i]
    if not nuevo_raw["pair"]:
        raise ConfigError("No se puede quitar la última pareja: el config se quedaría "
                          "sin ninguna y sync.py no arrancaría.")

    # Si [daemon].pairs la nombraba, se cae también: el servicio intentaría
    # sincronizar una pareja que ya no existe y fallaría en cada ciclo.
    daemon = nuevo_raw.get("daemon")
    if isinstance(daemon, dict) and name in (daemon.get("pairs") or []):
        daemon["pairs"] = [n for n in daemon["pairs"] if n != name]

    plan = EditPlan(raw=nuevo_raw)
    plan.consequences.append(f"Se quita '{name}' del config. Sus datos NO se tocan.")

    huerfanos = bisync.pair_state_paths(name)
    if huerfanos and clean_state:
        if (model.STATE_DIR / name).is_dir():
            plan.shelve = name
            plan.consequences.append(
                f"Su baseline se apartará a state/{name}.old-<fecha>/; no se borra.")
        plan.borrar_filtros = [p for p in huerfanos if p.parent == model.FILTERS_DIR]
        if plan.borrar_filtros:
            plan.consequences.append(
                "Se borrarán sus filtros generados, que son datos derivados del TOML.")
    elif huerfanos:
        plan.consequences.append(
            "Quedará sin usar: " + ", ".join(p.name for p in huerfanos))

    model.parse_config(nuevo_raw)
    return plan
