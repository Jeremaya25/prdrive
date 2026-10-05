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

Al final está la mitad que decide de «Renombrar el catálogo…» (`renombrado()`,
`plan_renombrar()`), que dibuja `ui/tk_renombrar.py`: pasar el `pairs.toml` de
un remoto de antes a `remote.toml`, solo cuando la flota dice que todos lo
saben leer.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Callable, Mapping, NamedTuple

from common import catalog, config_file, fleet, model
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
                      "copia a su lado (.bak).")
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


# «Renombrar el catálogo…», en «Ajustes»

RENOMBRAR = "renombrar"
"""Acción del botón: pasar `pairs.toml` a `remote.toml`."""
APARTAR = "apartar"
"""Acción del botón: apartar el `pairs.toml` que sobra junto a `remote.toml`."""

EXPLICACION = (
    f"El catálogo se llamaba {catalog.FICHERO_ANTERIOR} y ahora se llama "
    f"{catalog.FICHERO}, porque ya no lleva solo parejas. Renombrarlo no es "
    f"obligatorio: los dispositivos de esta versión encuentran los dos. Solo se "
    f"puede cuando todos los que comparten el catálogo saben leer el nombre "
    f"nuevo; uno de antes dejaría de encontrarlo.")
"""Lo que dice la cabecera de la pantalla."""
LEYENDO_NOMBRE = "Mirando la carpeta del catálogo y las notas de la flota…"
"""Lo que dice el indicador mientras se lee el remoto."""
SIN_NOTA = ("Un dispositivo que nunca ha sincronizado con este remoto no ha dejado "
            "nota, y aquí no se puede ver.")
"""Lo que se dice siempre debajo de la flota: lo que la lista no puede saber."""
QUITAR_DE_LA_LISTA = ("Si alguno ya no se usa, quítalo en «Parejas» → «Dispositivos…». "
                      "Si se usa, actualízalo y deja que sincronice una vez: su nota "
                      "dirá entonces que lo sabe leer.")
"""Lo que se dice cuando algún dispositivo impide renombrar."""


class Bloqueo(NamedTuple):
    """Un dispositivo de la flota que no consta que sepa leer `remote.toml`.

    Args:
        nombre: Cómo se llama.
        motivo: Por qué: la versión que dice llevar, o que no lo dice.
        visto: Cuándo publicó su nota por última vez (`store.stamp()`), o vacío.
    """
    nombre: str
    motivo: str
    visto: str


class Renombrado(NamedTuple):
    """Lo que dice y deja hacer «Renombrar el catálogo…».

    Args:
        linea: La frase de lo que hay.
        tono: Su rol: `Pista.`, `Aviso.` o `Peligro.`.
        accion: Lo que hace el botón (`RENOMBRAR`, `APARTAR`), o vacío si no
            hay nada que se pueda hacer.
        bloquean: Los dispositivos que impiden renombrar.
        flota: Cuántos dispositivos tienen nota; `None` si no se ha mirado.
    """
    linea: str
    tono: str
    accion: str = ""
    bloquean: tuple[Bloqueo, ...] = ()
    flota: int | None = None


def _bloqueo(disp: fleet.Dispositivo) -> Bloqueo | None:
    """Devuelve por qué ese dispositivo impide renombrar, o `None` si no lo impide."""
    if catalog.FICHERO in disp.entiende:
        return None
    if not disp.version or disp.version == "desconocida":
        motivo = "su nota no dice qué versión lleva"
    else:
        motivo = f"lleva la {disp.version}, de antes del nombre nuevo"
    return Bloqueo(disp.nombre, motivo, disp.last_seen)


def renombrado(sitio: catalog.SinRenombrar | None, nombres: frozenset[str] | None,
               flota: list[fleet.Dispositivo], aviso_flota: str | None,
               yo: str) -> Renombrado:
    """Dice qué se puede hacer con el nombre del catálogo, con lo leído del remoto.

    Se renombra solo si en la carpeta está `pairs.toml` y no `remote.toml`, y
    si la flota se ha podido leer y todas sus notas dicen que lo saben leer
    (`fleet.ENTIENDE`). Este dispositivo no cuenta: su nota puede ser de antes
    de actualizarse, y el código que pregunta ya lo sabe leer. Si están los
    dos, lo que se ofrece es apartar el que sobra.

    Args:
        sitio: Los dos nombres del catálogo de este dispositivo
            (`catalog.sin_renombrar()`).
        nombres: Lo que hay en la carpeta (`catalog.nombres_en()`), o `None`
            si no se ha podido mirar.
        flota: Las notas de la flota.
        aviso_flota: Lo que dijo `fleet.leer()` si no pudo leerlas.
        yo: El id de este dispositivo.
    """
    if sitio is None:
        return Renombrado(
            f"El catálogo de este dispositivo tiene un nombre propio, ni "
            f"{catalog.FICHERO_ANTERIOR} ni {catalog.FICHERO}: no hay nada que "
            f"renombrar.", "Pista.")
    if nombres is None:
        return Renombrado(f"No se ha podido mirar qué hay en {sitio.carpeta}: sin "
                          f"conexión, o el remoto no contesta.", "Aviso.")
    nuevo, viejo = catalog.FICHERO in nombres, catalog.FICHERO_ANTERIOR in nombres
    if nuevo and viejo:
        return Renombrado(
            f"En {sitio.carpeta} están {catalog.FICHERO} y "
            f"{catalog.FICHERO_ANTERIOR}. Vale {catalog.FICHERO}, que es el que "
            f"buscan primero todos los dispositivos de esta versión; el otro lo dejó "
            f"una subida que se cruzó con el renombrado. Apártalo cuando hayas "
            f"comprobado en «Parejas» que no falta nada.", "Aviso.", APARTAR)
    if nuevo:
        return Renombrado(f"El catálogo ya se llama {catalog.FICHERO}. No hay nada "
                          f"que hacer.", "Pista.")
    if not viejo:
        return Renombrado(f"En {sitio.carpeta} no hay ningún catálogo.", "Aviso.")
    if aviso_flota:
        return Renombrado(f"No se ha podido leer la flota, y sin ella no se sabe si "
                          f"todos los dispositivos leen el nombre nuevo. "
                          f"{aviso_flota}", "Aviso.")
    otros = [d for d in flota if d.id != yo]
    bloquean = tuple(b for b in map(_bloqueo, otros) if b is not None)
    if bloquean:
        quienes = ("el dispositivo de abajo sepa" if len(bloquean) == 1
                   else f"los {len(bloquean)} dispositivos de abajo sepan")
        return Renombrado(
            f"Todavía no: no consta que {quienes} leer el nombre nuevo. "
            f"{QUITAR_DE_LA_LISTA}", "Aviso.", "", bloquean, len(flota))
    if not otros:
        linea = "En la flota no hay más dispositivos que este."
    elif len(otros) == 1:
        linea = "El otro dispositivo de la flota ya sabe leer el nombre nuevo."
    else:
        linea = (f"Los otros {len(otros)} dispositivos de la flota ya saben leer el "
                 f"nombre nuevo.")
    return Renombrado(linea, "Pista.", RENOMBRAR, (), len(flota))


def leer_renombrado(raw_local: Mapping[str, Any] | None = None
                    ) -> tuple[frozenset[str] | None, list[fleet.Dispositivo], str | None]:
    """Lee del remoto lo que necesita «Renombrar el catálogo…».

    Corre en segundo plano (`ui.segundo_plano`). Lo que ve de la carpeta lo
    apunta en la copia local, para «Reparación» y para «Ajustes»: si están los
    dos nombres, y si otro dispositivo ya renombró. La flota solo se lee si
    hace falta para decidir, porque es otra ida y vuelta.

    Returns:
        `(nombres, flota, aviso_flota)`: lo de `catalog.nombres_en()` y lo de
        `fleet.leer()`.
    """
    sitio = catalog.sin_renombrar(raw_local)
    if sitio is None:
        return None, [], None
    nombres = catalog.nombres_en(catalog.run, sitio.carpeta)
    if nombres is None:
        return None, [], None
    nuevo, viejo = catalog.FICHERO in nombres, catalog.FICHERO_ANTERIOR in nombres
    catalog.apuntar_duplicado(sitio.viejo if nuevo and viejo else None)
    if nuevo and not viejo:
        catalog.apuntar_renombrado(sitio.viejo, sitio.nuevo)
    if nuevo or not viejo:
        return nombres, [], None
    flota, aviso = fleet.leer(raw_local)
    return nombres, flota, aviso


def raw_del_dispositivo(raw_local: Mapping[str, Any] | None) -> dict | None:
    """Devuelve el `sync_config.toml` en crudo: el que se da o, si no, el del disco.

    «Ajustes» se abre sin él, y sin él el catálogo sería el de fábrica en vez
    del que dice el dispositivo. Si no se puede leer, `None`: lo de fábrica.
    """
    if raw_local is not None:
        return dict(raw_local)
    try:
        return config_file.load_raw()
    except ConfigError:
        return None


def ofrecer_renombrado(raw_local: Mapping[str, Any] | None = None) -> bool:
    """Dice si «Ajustes» enseña «Renombrar el catálogo…», sin tocar la red.

    Solo si lo último que se leyó del remoto fue su `pairs.toml`, o si consta
    que están los dos nombres. Sin ninguna lectura apuntada no se ofrece: el
    primer «Parejas» lo dirá, y renombrar nunca corre prisa.
    """
    sitio = catalog.sin_renombrar(raw_local)
    if sitio is None:
        return False
    if catalog.duplicado() is not None:
        return True
    return catalog.ultimo_leido() == sitio.viejo


@dataclass
class NombrePlan:
    """Un cambio de nombre en la carpeta del catálogo, todavía sin hacer.

    Tiene la forma de `CatalogPlan` para pasar por `confirmar_plan()`, pero no
    reescribe el catálogo: mueve ficheros en el remoto.

    Args:
        hacer: Lo que lo hace (`catalog.renombrar` o `catalog.apartar_sobrante`).
        consequences: Una línea por consecuencia.
        warnings: Lo que conviene saber antes de confirmar.
    """
    hacer: Callable[[], list[str]]
    consequences: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def execute(self) -> list[str]:
        """Lo hace en el remoto y devuelve qué ha hecho."""
        return self.hacer()


def plan_renombrar(estado: Renombrado,
                   raw_local: Mapping[str, Any] | None = None) -> NombrePlan:
    """Devuelve el plan de lo que ofrece el botón: renombrar o apartar.

    Raises:
        ConfigError: Si `estado` no ofrece nada que hacer.
    """
    sitio = catalog.sin_renombrar(raw_local)
    if sitio is None or not estado.accion:
        raise ConfigError(estado.linea)
    copia = dict(raw_local) if raw_local is not None else None
    if estado.accion == APARTAR:
        return NombrePlan(
            partial(catalog.apartar_sobrante, copia),
            [f"{sitio.viejo} pasa a llamarse {catalog.FICHERO_ANTERIOR}"
             f"{catalog.APARTADO}<fecha>: no se borra, y con ese nombre ya no lo lee "
             f"nadie.",
             f"{sitio.nuevo} no se toca.", ALCANCE],
            ["Si llevaba un cambio que no está en el catálogo bueno, ese cambio no "
             "cuenta: repítelo en «Parejas»."])
    return NombrePlan(
        partial(catalog.renombrar, copia),
        [f"{sitio.viejo} pasa a llamarse {catalog.FICHERO}, y su copia previa "
         f"(.bak) también. El contenido no cambia.",
         ALCANCE,
         f"Nadie tiene que hacer nada: los dispositivos que tienen apuntado "
         f"{catalog.FICHERO_ANTERIOR} buscan antes {catalog.FICHERO} en la misma "
         f"carpeta."],
        [f"Un dispositivo de una versión anterior dejaría de encontrar el catálogo "
         f"(lo que ya sincroniza sigue funcionando). {SIN_NOTA}",
         f"Un instalador de una versión anterior tampoco lo encontrará: usa uno de "
         f"esta versión, o escribe la ruta …/{catalog.FICHERO} en su paso "
         f"«Conexión»."])

