#!/usr/bin/env python3
"""
pair_editor.py — Lo que este pen hace con las parejas. Sin Tkinter.

Aquí no se dibuja nada: la pantalla (`ui/tk_pairs.py`) pide un plan, enseña sus
consecuencias y, si el usuario confirma, lo ejecuta. Esa separación existe porque
lo delicado no es el formulario, es lo que pasa en disco.

El alta y la baja de una pareja NO viven aquí: pasan primero por el catálogo del
NAS (`ui/catalog_editor.py`), porque una pareja es la misma para todos los
dispositivos. Lo que decide este módulo es de este pen: cuáles de las del
catálogo se usan aquí (`plan_enable` / `plan_remove`), si alguna se modifica solo
aquí (`plan_override`) y cómo se vuelve a lo que dice el catálogo
(`plan_revert`).

Lo delicado, en una frase: **cambiar un extremo de una pareja bisync sin apartar
su baseline puede provocar borrados masivos.** El nombre de los listados sale de
los extremos (`bisync.expected_prefix`), así que al cambiar uno,
`normalize_prefix()` renombraría el baseline viejo al nombre nuevo y bisync
compararía el listado del destino ANTERIOR contra el destino NUEVO: todo lo que
no estuviera en el nuevo se leería como borrado y se propagaría. Esa función se
escribió para un caso benigno (el pen pasa de G: a F:) y no puede distinguirlo
del maligno. Por eso el plan aparta el baseline él mismo.

Y por eso la decisión de apartarlo no se toma mirando qué claves ha tocado el
usuario, sino comparando el `expected_prefix` de antes con el de después
(`_prefixes`). Es lo único que importa de verdad, y así no se escapa nada: un
cambio en `[defaults]` (`remote`, `pen_remote`) mueve el prefijo de VARIAS
parejas a la vez sin que ninguna de ellas se haya tocado.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, NamedTuple

from common import bisync, catalog, config_file, model
from common.model import Config, ConfigError

# Los campos de los que depende el nombre de los listados de bisync. Ya no
# deciden nada (eso lo hace `_prefixes`), pero son lo que se le enseña al
# usuario: "cambia local, mode" se entiende y "cambia el prefijo" no.
ENDPOINT_KEYS = ("local", "remote", "remote_path", "mode")

# Lo que edita el formulario. El resto de claves de la pareja (flags,
# extra_flags, use_filters_file...) se conservan tal cual: la UI no las toca,
# porque la regla del proyecto es que los flags de rclone se escriben en el TOML.
FORM_KEYS = ("name", "local", "remote_path", "remote", "mode", "include", "exclude")

MIRROR_MODES = ("up-mirror", "down-mirror")
NOMBRE_PROHIBIDO = set('/\\:*?"<>|')

# De dónde sale cada fila de la lista, comparando con el catálogo.
ORIGEN_CATALOGO = "catálogo"
ORIGEN_LOCAL = "modificada aquí"
ORIGEN_HUERFANA = "huérfana"
ORIGEN_SIN_USAR = "sin usar"
ORIGEN_DESCONOCIDO = "—"          # no hay catálogo con el que comparar


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
    shelve: list[str] = field(default_factory=list)  # parejas cuyo baseline apartar
    rename: tuple[str, str] | None = None            # (nombre viejo, nombre nuevo)
    borrar_filtros: list[Path] = field(default_factory=list)

    def execute(self) -> list[str]:
        """Primero el disco, luego el config. Devuelve qué se ha hecho.

        El orden no es casual. La combinación peligrosa es "config nuevo con
        baseline viejo": escribiendo el config primero, un fallo al mover el
        estado dejaría exactamente eso. Al revés, el peor caso es un baseline
        apartado de más, que se arregla con un --resync.

        Dentro del disco, el renombrado va ANTES de apartar: así, cuando un
        cambio toca el nombre y un extremo a la vez, el estado y los filtros
        viajan juntos al nombre nuevo y es ese el que se aparta. Al revés
        quedarían `filters/<nombre viejo>.txt` huérfanos que nadie recoge."""
        movimientos: list[Move] = []
        hechos: list[str] = []
        try:
            if self.rename:
                viejo, nuevo = self.rename
                for origen, destino in bisync.rename_pair_state(viejo, nuevo):
                    movimientos.append(Move(origen, destino))
                if movimientos:
                    hechos.append(f"Estado movido de '{viejo}' a '{nuevo}'")
            for name in self.shelve:
                destino = bisync.shelve_baseline(name)
                if destino:
                    movimientos.append(Move(model.STATE_DIR / name, destino))
                    hechos.append(f"Baseline apartado en state/{destino.name}/")

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


def pair_index(raw: Mapping[str, Any], name: str) -> int:
    for i, pair in enumerate(raw.get("pair", [])):
        if pair.get("name") == name:
            return i
    raise ConfigError(f"No hay ninguna pareja llamada '{name}'.")


def _prefixes(raw: Mapping[str, Any]) -> dict[str, str]:
    """El nombre que bisync le pondría a los listados de cada pareja, hoy.

    Solo las bisync: son las únicas con baseline que se pueda invalidar. Un
    config que no parsea devuelve {}, y entonces nadie aparta nada; da igual,
    porque `plan_*` acaba llamando a `model.parse_config` y no llegaría a
    ejecutarse."""
    try:
        config = model.parse_config(raw)
    except ConfigError:
        return {}
    return {p.name: bisync.expected_prefix(p) for p in config.pairs if p.is_bisync}


def _analizar_prefijo(plan: EditPlan, antes_raw: Mapping[str, Any],
                      nombres: Mapping[str, str]) -> list[str]:
    """Apunta en el plan qué baselines dejan de valer. Devuelve sus nombres.

    `nombres` mapea el nombre que tenía cada pareja ANTES al que tiene DESPUÉS
    (iguales salvo en un renombrado). Se aparta cuando el prefijo cambia y
    también cuando desaparece —pasar de bisync a otro modo—: dejar ahí un
    baseline que ya no se comprueba es sembrar el caso peligroso para el día que
    se vuelva a bisync con otro destino."""
    antes = _prefixes(antes_raw)
    despues = _prefixes(plan.raw)
    afectadas = [nuevo for viejo, nuevo in nombres.items()
                 if viejo in antes and antes[viejo] != despues.get(nuevo)
                 and (model.STATE_DIR / viejo).is_dir()]
    plan.shelve = afectadas
    return afectadas


def clean_form(edited: Mapping[str, Any]) -> dict:
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
    campos = clean_form(edited)
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
        i = pair_index(raw, original_name)
        anterior = dict(raw["pair"][i])
        # Se parte de la pareja anterior para no perder lo que el formulario no
        # edita; las listas vaciadas a mano sí desaparecen.
        resultante = {**anterior, **campos}
        for key in ("include", "exclude"):
            if key in anterior and key not in campos:
                resultante.pop(key, None)
        nuevo_raw["pair"][i] = resultante

        _analizar_pareja(plan, raw, original_name, anterior, resultante)

    aviso = mirror_warning(_mode_of(resultante))
    if aviso:
        plan.warnings.append(aviso)

    model.parse_config(nuevo_raw)          # red final
    return plan


def _analizar_pareja(plan: EditPlan, antes_raw: Mapping[str, Any], original_name: str,
                     anterior: Mapping[str, Any], resultante: Mapping[str, Any]) -> None:
    """Las consecuencias de cambiar una pareja que este pen ya tenía."""
    nuevo_nombre = resultante["name"]
    if nuevo_nombre != original_name:
        plan.rename = (original_name, nuevo_nombre)

    apartadas = _analizar_prefijo(plan, antes_raw, {original_name: nuevo_nombre})
    cambiados = [k for k in ENDPOINT_KEYS if anterior.get(k) != resultante.get(k)]

    if cambiados:
        plan.consequences.append(
            "Cambia " + ", ".join(cambiados) + ": es de donde bisync saca el "
            "nombre de sus listados.")
    if apartadas:
        if plan.rename:
            plan.consequences.append(
                f"El estado se mueve primero de '{original_name}' a '{nuevo_nombre}' "
                "para que sus filtros no se queden huérfanos.")
        plan.consequences.append(
            f"Se apartará el baseline a state/{nuevo_nombre}.old-<fecha>/ y la pareja "
            "pedirá un --resync. Es a propósito: reaprovecharlo haría que bisync "
            "leyera como borrados los ficheros del destino anterior.")
    elif plan.rename and not cambiados:
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


def plan_remove(raw: Mapping[str, Any], name: str, clean_state: bool = False) -> EditPlan:
    """El plan de quitar una pareja. No toca nada."""
    i = pair_index(raw, name)
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
    plan.consequences.append(f"Se quita '{name}' de este pen. Sus datos NO se tocan, "
                             f"ni aquí ni en el NAS: solo deja de sincronizarse. Si "
                             f"está en el catálogo, sigue estándolo.")

    huerfanos = bisync.pair_state_paths(name)
    if huerfanos and clean_state:
        if (model.STATE_DIR / name).is_dir():
            plan.shelve = [name]
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


# ---------------------------------------------------------------------------
# Este pen frente al catálogo
# ---------------------------------------------------------------------------

def plan_enable(raw: Mapping[str, Any], cat: catalog.Catalog | None, name: str) -> EditPlan:
    """Empezar a usar aquí una pareja que ya existe en el catálogo."""
    entrada = catalog.find_pair(cat, name)
    if entrada is None:
        raise ConfigError(f"El catálogo no tiene ninguna pareja llamada '{name}'. "
                          f"Créala primero ahí y luego elígela aquí.")
    if any(p.get("name") == name for p in raw.get("pair") or []):
        raise ConfigError(f"'{name}' ya está en este pen.")

    nuevo_raw = copy.deepcopy(dict(raw))
    nuevo_raw.setdefault("pair", []).append(copy.deepcopy(entrada))
    plan = EditPlan(raw=nuevo_raw)
    plan.consequences.append(
        f"Se empieza a usar '{name}' en este pen, tal y como está en el catálogo.")
    plan.consequences.append(
        f"La ruta local '{entrada.get('local')}' se creará en la primera pasada si "
        f"todavía no existe.")
    if _mode_of(entrada) == "bisync":
        plan.consequences.append(
            "Al ser bisync, la primera pasada pedirá un --resync para fijar la "
            "referencia (compara ambos lados; no borra por diferencias).")

    aviso = mirror_warning(_mode_of(entrada))
    if aviso:
        plan.warnings.append(aviso)

    model.parse_config(nuevo_raw)
    return plan


def plan_override(raw: Mapping[str, Any], cat: catalog.Catalog | None,
                  name: str, edited: Mapping[str, Any]) -> EditPlan:
    """Modificar una pareja SOLO en este pen. El catálogo no se entera."""
    plan = plan_save(raw, edited, name)
    entrada = catalog.find_pair(cat, name)
    resultante = plan.raw["pair"][pair_index(plan.raw, clean_form(edited).get("name", name))]

    if entrada is None:
        cabecera = (f"'{name}' no está en el catálogo, así que este cambio solo "
                    f"existe en este pen.")
    elif catalog.diff_keys(resultante, entrada):
        cabecera = (f"'{name}' deja de seguir el catálogo en este pen: difiere en "
                    f"{', '.join(catalog.diff_keys(resultante, entrada))}. Los demás "
                    f"dispositivos no cambian.")
    else:
        cabecera = f"'{name}' queda otra vez igual que en el catálogo."
    plan.consequences.insert(0, cabecera)
    return plan


def plan_revert(raw: Mapping[str, Any], cat: catalog.Catalog | None, name: str) -> EditPlan:
    """Deshacer la modificación local: volver a lo que dice el catálogo."""
    entrada = catalog.find_pair(cat, name)
    if entrada is None:
        raise ConfigError(f"El catálogo no tiene '{name}', así que no hay a qué "
                          f"volver. O la quitas de este pen, o la creas en el "
                          f"catálogo.")
    i = pair_index(raw, name)
    anterior = dict(raw["pair"][i])
    difiere = catalog.diff_keys(anterior, entrada)
    if not difiere:
        raise ConfigError(f"'{name}' ya es exactamente la del catálogo.")

    nuevo_raw = copy.deepcopy(dict(raw))
    nuevo_raw["pair"][i] = copy.deepcopy(entrada)
    plan = EditPlan(raw=nuevo_raw)
    plan.consequences.append(
        f"'{name}' vuelve a como está en el catálogo (cambia {', '.join(difiere)}).")
    _analizar_pareja(plan, raw, name, anterior, entrada)

    aviso = mirror_warning(_mode_of(entrada))
    if aviso:
        plan.warnings.append(aviso)

    model.parse_config(nuevo_raw)
    return plan


def plan_defaults(raw: Mapping[str, Any], edited: Mapping[str, Any]) -> EditPlan:
    """Cambiar los [defaults] de este pen.

    Es el plan con más alcance de todos: `[defaults]` aporta el `remote` y el
    `pen_remote` a TODAS las parejas, así que un solo cambio aquí puede invalidar
    varios baselines de golpe sin que ninguna pareja se haya tocado. Por eso
    `EditPlan.shelve` es una lista."""
    nuevo_raw = copy.deepcopy(dict(raw))
    nuevo_raw["defaults"] = copy.deepcopy(dict(edited))
    plan = EditPlan(raw=nuevo_raw)

    cambiados = catalog.diff_keys(raw.get("defaults"), nuevo_raw["defaults"])
    if not cambiados:
        plan.consequences.append("No cambia nada en [defaults].")
        model.parse_config(nuevo_raw)
        return plan

    plan.consequences.append("Cambia en [defaults]: " + ", ".join(cambiados) + ".")
    nombres = {p["name"]: p["name"] for p in nuevo_raw.get("pair") or [] if p.get("name")}
    apartadas = _analizar_prefijo(plan, raw, nombres)
    if apartadas:
        plan.consequences.append(
            "[defaults] alimenta los extremos de todas las parejas, así que cambia el "
            "nombre de los listados de: " + ", ".join(apartadas) + ". Se apartarán sus "
            "baselines y pedirán un --resync.")
    if set(cambiados) & {"include", "exclude"}:
        plan.consequences.append(
            "Cambian los filtros comunes: las parejas bisync exigirán un --resync, "
            "porque no pueden saber qué ficheros excluidos existían antes.")

    model.parse_config(nuevo_raw)
    return plan


def plan_revert_defaults(raw: Mapping[str, Any], cat: catalog.Catalog | None) -> EditPlan:
    """Volver a los [defaults] del catálogo."""
    if cat is None:
        raise ConfigError("No hay catálogo con el que comparar.")
    if not catalog.diff_keys(raw.get("defaults"), cat.defaults):
        raise ConfigError("Los [defaults] ya son exactamente los del catálogo.")
    plan = plan_defaults(raw, cat.defaults)
    plan.consequences.insert(0, "Los [defaults] vuelven a los del catálogo.")
    return plan


# ---------------------------------------------------------------------------
# La lista que se pinta: parejas del catálogo + las que solo tiene este pen
# ---------------------------------------------------------------------------

class CatalogRow(NamedTuple):
    """Una línea de la lista, ya resuelta contra el catálogo."""
    name: str
    mode: str
    local: str
    remote: str
    estado: str
    aviso: str | None
    en_pen: bool
    origen: str
    difiere: tuple[str, ...]


def _display(entrada: Mapping[str, Any], defaults: Mapping[str, Any]) -> tuple[str, str, str]:
    """Modo y extremos de una pareja que este pen NO tiene.

    No pasa por `model.Pair` a propósito: sus rutas se resuelven contra el pen y
    aquí lo que se enseña es lo que dice el catálogo, no dónde caería."""
    mode = entrada.get("mode", model.DEFAULT_MODE)
    local = str(entrada.get("local", "?")).replace("\\", "/").strip("/") or "."
    remote = entrada.get("remote") or defaults.get("remote") or model.DEFAULT_REMOTE
    return mode, local, f"{remote}:{entrada.get('remote_path', '?')}"


def catalog_rows(config: Config, raw: Mapping[str, Any],
                 cat: catalog.Catalog | None) -> list[CatalogRow]:
    """Las del catálogo primero y en su orden, y detrás las que solo hay aquí."""
    locales = {p["name"]: dict(p) for p in raw.get("pair") or [] if p.get("name")}
    del_cat = catalog.pairs_by_name(cat)
    filas = {f.name: f for f in rows(config)}
    defaults_cat = cat.defaults if cat is not None else {}

    salida: list[CatalogRow] = []
    for name, entrada in del_cat.items():
        fila = filas.get(name)
        if fila is None:
            mode, local, remote = _display(entrada, defaults_cat)
            salida.append(CatalogRow(name, mode, local, remote, "—",
                                     mirror_warning(mode), False, ORIGEN_SIN_USAR, ()))
            continue
        difiere = catalog.diff_keys(locales.get(name), entrada)
        salida.append(CatalogRow(*fila, en_pen=True, difiere=difiere,
                                 origen=ORIGEN_LOCAL if difiere else ORIGEN_CATALOGO))

    for name, fila in filas.items():
        if name not in del_cat:
            origen = ORIGEN_DESCONOCIDO if cat is None else ORIGEN_HUERFANA
            salida.append(CatalogRow(*fila, en_pen=True, origen=origen, difiere=()))
    return salida


def defaults_origin(raw: Mapping[str, Any],
                    cat: catalog.Catalog | None) -> tuple[str, tuple[str, ...]]:
    """Si los [defaults] de este pen son los del catálogo, y en qué difieren."""
    if cat is None:
        return ORIGEN_DESCONOCIDO, ()
    difiere = catalog.diff_keys(raw.get("defaults"), cat.defaults)
    return (ORIGEN_LOCAL if difiere else ORIGEN_CATALOGO), difiere
