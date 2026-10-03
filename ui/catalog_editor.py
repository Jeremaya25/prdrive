#!/usr/bin/env python3
"""Alta, edición y baja en el catálogo del remoto, sin Tkinter.

Es simétrico a `pair_editor.py` y con el mismo guion (plan, consecuencias,
confirmación, ejecución), pero lo que hay al otro lado no es el disco de este
dispositivo: es un fichero del remoto que gobierna a TODOS. Eso cambia dos
cosas.

La primera es qué se puede romper. Aquí no hay baselines que apartar (este
dispositivo no cambia por editar el catálogo), pero un error se propaga a todos
los demás la próxima vez que alguien mire. Por eso `catalog.push()` verifica el
TOML antes de subirlo, se niega si el remoto ha cambiado desde que se leyó y
deja un `.bak`.

La segunda es que **editar el catálogo no toca este dispositivo**. Dar de alta
una pareja la deja disponible, no puesta; darla de baja la deja huérfana aquí,
no quitada. Elegir qué usa este dispositivo es el otro módulo, y es a
propósito: son dos decisiones distintas y mezclarlas es justo lo que se quería
evitar.

Ninguna pareja es intocable: el instalador lleva el código dentro, así que el
catálogo son parejas de datos y todas valen lo mismo.

La pantalla se abre con la copia local y lee el remoto en segundo plano; qué
dice mientras tanto, y qué deja hacer, lo decide `lectura()`.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping, NamedTuple

from common import catalog, model
from common.model import ConfigError

from . import pair_editor

ALCANCE = "Afecta a TODOS los dispositivos, no solo a este."
"""Lo que se dice siempre al cambiar el catálogo."""
NO_APLICA_AQUI = ("Los dispositivos que ya usan esta pareja no cambian solos: "
                  "cada uno tiene que volver al catálogo cuando quiera el cambio.")
"""Lo que se dice al cambiar una pareja o los `[defaults]`.

Los demás dispositivos no se enteran solos.
"""
PIERDE_COMENTARIOS = ("El fichero se reescribe entero: se conserva la cabecera y se "
                      "pierden los comentarios intercalados. Antes se guarda una "
                      "copia en pairs.toml.bak.")
"""Lo que se dice siempre antes de reescribir el fichero del catálogo."""

LEYENDO_SIN_COPIA = ("Leyendo el catálogo del remoto. Este dispositivo no tiene copia "
                     "local, así que hasta que llegue solo se ven sus propias parejas.")
"""Lo que se dice mientras se lee el remoto sin copia local que enseñar."""
RELEYENDO = "Releyendo el catálogo del remoto. Mientras tanto no se puede editar."
"""Lo que se dice mientras se relee un catálogo que ya se había leído del remoto."""
SIN_CATALOGO = ("No hay catálogo ni copia local, así que solo se puede trabajar con "
                "las parejas que ya tiene este dispositivo.")
"""Lo que se dice sin catálogo cuando la lectura no ha dejado su propio aviso."""


class Lectura(NamedTuple):
    """Lo que la pantalla de parejas dice del catálogo que enseña, y lo que deja hacer.

    Args:
        chip: El estado en dos palabras, para el chip de arriba.
        tipo: El estilo del chip: `Acento.`, `Aviso.`, `Peligro.` o `Apagado.`.
        icono: El icono del chip.
        linea: La explicación de debajo de la cabecera; vacía si no hay nada
            que explicar.
        tono: El rol de esa explicación: `Pista.`, `Aviso.` o `Peligro.`.
        leyendo: Si se está esperando al remoto: el indicador va y viene.
        editable: Si los botones que escriben en el catálogo se pueden pulsar.
    """
    chip: str
    tipo: str
    icono: str
    linea: str
    tono: str
    leyendo: bool
    editable: bool


def _de_cuando(stamp: str) -> str:
    """Devuelve «del <fecha>» para una copia, o que no se sabe de cuándo es."""
    if not stamp or stamp == catalog.SIN_FECHA:
        return "(no consta de cuándo es)"
    return f"del {stamp}"


def lectura(cat: catalog.Catalog | None, aviso: str | None,
            leyendo: bool) -> Lectura:
    """Dice qué enseña la pantalla de parejas del catálogo y si se puede editar.

    Solo se edita lo que se acaba de leer del remoto (`Catalog.editable`) y
    nunca mientras se está leyendo: lo que se enseña entonces es la copia
    local, o lo que había antes de releer, y subir partiendo de ahí sería
    escribir a ciegas. «Examinar…» depende de la misma respuesta.

    Args:
        cat: Lo que se enseña ahora: el del remoto, la copia local o nada.
        aviso: Lo que dijo `catalog.load()` si no pudo leer el remoto.
        leyendo: Si hay una lectura del remoto en marcha.
    """
    if leyendo:
        if cat is None:
            return Lectura("leyendo el catálogo…", "Apagado.", "clock",
                           LEYENDO_SIN_COPIA, "Pista.", True, False)
        if cat.editable:
            return Lectura(f"catálogo leído · {cat.stamp}", "Acento.", "ok",
                           RELEYENDO, "Pista.", True, False)
        return Lectura(f"copia local · {cat.stamp}", "Apagado.", "clock",
                       f"Leyendo el catálogo del remoto. Mientras llega se enseña "
                       f"la copia local {_de_cuando(cat.stamp)}, que no se puede "
                       f"editar.", "Pista.", True, False)
    if cat is None:
        return Lectura("sin catálogo", "Peligro.", "warn", aviso or SIN_CATALOGO,
                       "Peligro.", False, False)
    if cat.editable:
        return Lectura(f"catálogo leído · {cat.stamp}", "Acento.", "ok", "",
                       "Pista.", False, True)
    return Lectura(f"copia local · {cat.stamp}", "Aviso.", "warn",
                   aviso or (f"Se enseña la copia local {_de_cuando(cat.stamp)}: el "
                             f"catálogo solo se puede editar recién leído del remoto."),
                   "Aviso.", False, False)


@dataclass
class CatalogPlan:
    """Un cambio pensado sobre el catálogo, todavía sin subir.

    Args:
        new_raw: El catálogo resultante, en bruto.
        base_text: El texto del remoto sobre el que se piensa; `push()` se
            niega si ha cambiado.
        consequences: Una línea por consecuencia.
        warnings: Lo que conviene saber antes de confirmar.
        raw_local: El `sync_config.toml` de este dispositivo, si hay que
            tenerlo en cuenta.
    """
    new_raw: dict
    base_text: str
    consequences: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_local: dict | None = None

    def execute(self) -> list[str]:
        """Sube el cambio al remoto y devuelve qué ha hecho."""
        return catalog.push(self.new_raw, self.base_text, self.raw_local)


def _editable(cat: catalog.Catalog | None) -> catalog.Catalog:
    """Devuelve el catálogo si se puede editar.

    Raises:
        ConfigError: Si no hay catálogo o es la copia local.
    """
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
    """Devuelve un plan vacío sobre ese catálogo, con el alcance ya dicho."""
    plan = CatalogPlan(new_raw=nuevo_raw, base_text=cat.text,
                       raw_local=dict(raw_local) if raw_local is not None else None)
    plan.consequences.append(ALCANCE)
    return plan


def plan_catalog_save(cat: catalog.Catalog | None, edited: Mapping[str, Any],
                      original_name: str | None = None,
                      raw_local: Mapping[str, Any] | None = None) -> CatalogPlan:
    """Devuelve el plan de dar de alta o modificar una pareja.

    Con `original_name=None` es un alta.

    Raises:
        ConfigError: Si el formulario no vale, no cambia nada o el catálogo no
            se puede editar.
    """
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
        # La misma regla que en el editor local, y por eso la función es la
        # misma: se parte de lo anterior para no perder lo que el formulario no
        # edita, y lo que se haya vaciado a mano sí desaparece.
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
    """Devuelve el plan de borrar una pareja del catálogo.

    No toca ningún dispositivo.
    """
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
    """Devuelve el plan de cambiar los `[defaults]` del catálogo."""
    cat = _editable(cat)
    nuevo_raw = copy.deepcopy(dict(cat.raw))
    nuevo_raw["defaults"] = copy.deepcopy(dict(edited))

    difiere = catalog.diff_keys(cat.defaults, nuevo_raw["defaults"])
    if not difiere:
        raise ConfigError("Los [defaults] se quedan exactamente igual: no hay nada "
                          "que subir.")
    catalog.validar_ruta_editada(cat.defaults, nuevo_raw["defaults"])

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
