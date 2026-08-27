#!/usr/bin/env python3
"""
catalog_editor.py — Alta, edición y baja en el catálogo del remoto. Sin Tkinter.

Simétrico a `pair_editor.py` y con el mismo guion —plan, consecuencias,
confirmación, ejecución—, pero lo que hay al otro lado no es el disco de este
dispositivo: es un fichero del remoto que gobierna a TODOS. Eso cambia dos cosas.

La primera es qué se puede romper. Aquí no hay baselines que apartar (este
dispositivo no cambia por editar el catálogo), pero un error se propaga a todos
los demás la próxima vez que alguien mire. Por eso `catalog.push()` verifica el
TOML antes de subirlo, se niega si el remoto ha cambiado desde que se leyó y deja
un `.bak`.

La segunda es que **editar el catálogo no toca este dispositivo**. Dar de alta
una pareja la deja disponible, no puesta; darla de baja la deja huérfana aquí, no
quitada. Elegir qué usa este dispositivo es el otro módulo, y es a propósito: son
dos decisiones distintas y mezclarlas es justo lo que se quería evitar.

**Ya no hay ninguna pareja intocable.** Cuando el código del dispositivo bajaba
del remoto, la pareja que describía ese espejo era imprescindible para instalar y
el editor se negaba a borrarla. Ahora el instalador lleva el código dentro, así
que el catálogo son parejas de datos y todas valen lo mismo.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping

from common import catalog, model
from common.model import ConfigError

from . import pair_editor

ALCANCE = "Afecta a TODOS los dispositivos, no solo a este."
NO_APLICA_AQUI = ("Los dispositivos que ya usan esta pareja no cambian solos: "
                  "cada uno tiene que volver al catálogo cuando quiera el cambio.")
PIERDE_COMENTARIOS = ("El fichero se reescribe entero: se conserva la cabecera y se "
                      "pierden los comentarios intercalados. Antes se guarda una "
                      "copia en pairs.toml.bak.")


@dataclass
class CatalogPlan:
    """Un cambio pensado sobre el catálogo, todavía sin subir."""
    new_raw: dict
    base_text: str
    consequences: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_local: dict | None = None

    def execute(self) -> list[str]:
        return catalog.push(self.new_raw, self.base_text, self.raw_local)


def _editable(cat: catalog.Catalog | None) -> catalog.Catalog:
    if cat is None:
        raise ConfigError("No hay catálogo: sin él no se pueden dar de alta ni de "
                          "baja parejas.")
    if not cat.editable:
        raise ConfigError(
            "Esto es la copia local del catálogo, no el catálogo. Para editarlo hace "
            "falta conexión con el remoto: no se puede escribir encima de lo que otros "
            "dispositivos hayan hecho mientras tanto.")
    return cat


def _plan(cat: catalog.Catalog, nuevo_raw: dict,
          raw_local: Mapping[str, Any] | None) -> CatalogPlan:
    plan = CatalogPlan(new_raw=nuevo_raw, base_text=cat.text,
                       raw_local=dict(raw_local) if raw_local is not None else None)
    plan.consequences.append(ALCANCE)
    return plan


def plan_catalog_save(cat: catalog.Catalog | None, edited: Mapping[str, Any],
                      original_name: str | None = None,
                      raw_local: Mapping[str, Any] | None = None) -> CatalogPlan:
    """Dar de alta (original_name=None) o modificar una pareja del catálogo."""
    cat = _editable(cat)
    problemas = pair_editor.validate(cat.raw, edited, original_name)
    if problemas:
        raise ConfigError("\n".join(problemas))

    nuevo_raw = copy.deepcopy(dict(cat.raw))
    nuevo_raw.setdefault("pair", [])
    campos = pair_editor.clean_form(edited)
    plan = _plan(cat, nuevo_raw, raw_local)

    if original_name is None:
        resultante = campos
        nuevo_raw["pair"].append(resultante)
        plan.consequences.insert(
            0, f"Se crea la pareja '{campos['name']}' en el catálogo. Todavía no la "
               f"usa ningún dispositivo: cada uno tiene que elegirla.")
    else:
        i = pair_editor.pair_index(nuevo_raw, original_name)
        anterior = dict(nuevo_raw["pair"][i])
        # La misma regla que en el editor local, y por eso la función es la misma:
        # se parte de lo anterior para no perder lo que el formulario no edita, y
        # lo que se haya vaciado a mano sí desaparece.
        resultante = pair_editor.merge_form(anterior, campos)
        nuevo_raw["pair"][i] = resultante

        difiere = catalog.diff_keys(anterior, resultante)
        if not difiere:
            raise ConfigError(f"'{original_name}' se queda exactamente igual: no hay "
                              f"nada que subir.")
        plan.consequences.insert(
            0, f"Cambia '{original_name}' en el catálogo: {', '.join(difiere)}.")
        plan.consequences.append(NO_APLICA_AQUI)

    plan.consequences.append(PIERDE_COMENTARIOS)
    aviso = pair_editor.mirror_warning(resultante.get("mode", model.DEFAULT_MODE))
    if aviso:
        plan.warnings.append(aviso)

    model.parse_config(nuevo_raw)          # red final, la misma que en el dispositivo
    return plan


def plan_catalog_remove(cat: catalog.Catalog | None, name: str,
                        raw_local: Mapping[str, Any] | None = None) -> CatalogPlan:
    """Borrar una pareja del catálogo. No toca ningún dispositivo."""
    cat = _editable(cat)
    i = pair_editor.pair_index(cat.raw, name)
    nuevo_raw = copy.deepcopy(dict(cat.raw))
    del nuevo_raw["pair"][i]
    if not nuevo_raw["pair"]:
        raise ConfigError("No se puede dejar el catálogo sin ninguna pareja.")

    plan = _plan(cat, nuevo_raw, raw_local)
    plan.consequences.insert(0, f"Se borra '{name}' del catálogo.")
    plan.consequences.append(
        f"Los dispositivos que la estén usando NO la pierden: la seguirán sincronizando y "
        f"aquí aparecerá como huérfana hasta que se quite de cada uno.")
    plan.consequences.append(PIERDE_COMENTARIOS)
    plan.warnings.append("Los datos del remoto y de los dispositivos no se tocan.")

    model.parse_config(nuevo_raw)
    return plan


def plan_catalog_defaults(cat: catalog.Catalog | None, edited: Mapping[str, Any],
                          raw_local: Mapping[str, Any] | None = None) -> CatalogPlan:
    """Cambiar los [defaults] del catálogo."""
    cat = _editable(cat)
    nuevo_raw = copy.deepcopy(dict(cat.raw))
    nuevo_raw["defaults"] = copy.deepcopy(dict(edited))

    difiere = catalog.diff_keys(cat.defaults, nuevo_raw["defaults"])
    if not difiere:
        raise ConfigError("Los [defaults] se quedan exactamente igual: no hay nada "
                          "que subir.")

    plan = _plan(cat, nuevo_raw, raw_local)
    plan.consequences.insert(0, "Cambia en los [defaults] del catálogo: "
                                + ", ".join(difiere) + ".")
    plan.consequences.append(
        "[defaults] aporta el remote y los filtros comunes a TODAS las parejas, así "
        "que esto es lo de mayor alcance que se puede tocar aquí.")
    plan.consequences.append(NO_APLICA_AQUI)
    plan.consequences.append(PIERDE_COMENTARIOS)

    model.parse_config(nuevo_raw)
    return plan
