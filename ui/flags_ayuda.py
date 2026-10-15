#!/usr/bin/env python3
"""La ayuda al escribir un flag de rclone en el editor de una pareja, sin Tkinter y sin red.

Son tres cosas, y ninguna le quita a la persona la última palabra:
- **Autocompletar** el nombre (`sugerir()`, `palabra_en()`, `completar()`).
- **Comprobar el tipo del valor** antes de guardar (`problema_valor()`).
- **Avisar** junto al flag, sin bloquear (`avisos()`): es de otro modo, choca con
  otro o borra/reescribe.

Los nombres, los tipos y los valores de fábrica salen de `common/flags_rclone.json`,
que genera `generar_flags_rclone.py` de la rclone FIJADA en `common/pins.py`:
hay que regenerarlo cuando se mueve `RCLONE_VERSION` (un test lo vigila). Lo que
rclone no puede decir (qué flag borra, qué dos se pisan, qué global no sirve en un
modo que solo copia) está en las tablas de abajo, escritas a mano y con el
motivo de cada una.

**No hay lista blanca**: un flag que no está en los datos se admite, sin comprobar
su valor. Quién sabe si existe es rclone, y la regla del proyecto es que un flag
nuevo se añade escribiéndolo. Solo rechazan `model.problema_flag()` (los que pone
`sync.py` o lanzan un programa), con su puerta de siempre (`flags_editor._validar`),
y el tipo de un valor, cuando es seguro que rclone lo rechazaría: un valor que
rompe la orden en cada pasada no se guarda. Ante la duda (un tipo que no se
comprueba, un horario de ancho de banda) se calla: es peor bloquear un valor bueno.

Cada gramática de valor está medida contra el binario de la v1.75.2 (la lista de lo
que acepta y rechaza está en `tests/test_flags_ayuda.py`).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, NamedTuple

from common import model

RUTA_DATOS = Path(__file__).resolve().parent.parent / "common" / "flags_rclone.json"
"""El fichero de datos que escribe `generar_flags_rclone.py`."""

AVISO_MODO = "modo"
"""Aviso: el flag es de otro modo (de otra orden de rclone) o no hace nada en este."""
AVISO_CHOQUE = "choque"
"""Aviso: el flag choca con otro que ya está puesto."""
AVISO_BORRADO = "borrado"
"""Aviso: el flag borra o reescribe ficheros."""

VERBOS = ("bisync", "copy", "sync")
"""Las órdenes de rclone que lanza `sync.py` (`model.Mode.verb`)."""


class Flag(NamedTuple):
    """Un flag de rclone tal como lo dice el fichero de datos.

    Args:
        nombre: Sin guiones y con `-` (`max-delete`).
        corto: Su nombre de una letra, o `""`.
        tipo: El de la ayuda de rclone (`int`, `Duration`, `stringArray`, `bool`,
            `HARD|SOFT|CAUTIOUS`…).
        defecto: Su valor de fábrica, o `""` si no lo dice.
        ayuda: Su explicación corta, en inglés (la de rclone).
        grupo: El grupo de rclone (`Sync`, `Filter`…) o `local` si es de una orden.
        propio: Si es de una orden y no global: fuera de ella rclone responde
            `unknown flag`.
        comandos: Las órdenes donde existe (`VERBOS`).
        go: Si es una `Duration` de Go (con unidad obligatoria) y no la de rclone.
    """
    nombre: str
    corto: str
    tipo: str
    defecto: str
    ayuda: str
    grupo: str
    propio: bool
    comandos: tuple[str, ...]
    go: bool


class Datos(NamedTuple):
    """Los flags de una versión de rclone.

    Args:
        rclone: La versión (`v1.75.2`), o `""` si no se han podido leer.
        flags: `{nombre normalizado: Flag}`.
    """
    rclone: str
    flags: dict[str, Flag]


def normalizar(nombre: str) -> str:
    """Devuelve el nombre como lo ve rclone: sin `--`, en minúsculas y con `-` por `_`."""
    return model.normalizar_flag(str(nombre).lstrip("-"))


def cargar(ruta: Path) -> Datos:
    """Lee un fichero de datos; si no se puede, devuelve unos datos vacíos.

    La ayuda no es obligatoria: sin el fichero, roto o a medias, el editor sigue
    valiendo y simplemente no sugiere ni comprueba. Un flag mal formado se
    deja y los demás se leen.
    """
    try:
        crudo = json.loads(Path(ruta).read_text(encoding="utf-8"))
        origen = crudo.get("flags", {})
        if not isinstance(origen, dict):
            raise ValueError("flags")
        version = str(crudo.get("rclone", ""))
    except (OSError, ValueError, AttributeError):
        return Datos("", {})
    flags: dict[str, Flag] = {}
    for nombre, f in origen.items():
        if not isinstance(f, dict):
            continue
        clave = normalizar(nombre)
        try:
            flags[clave] = Flag(
                nombre=clave, corto=str(f.get("corto", "")), tipo=str(f.get("tipo", "")),
                defecto=str(f.get("defecto", "")), ayuda=str(f.get("ayuda", "")),
                grupo=str(f.get("grupo", "")), propio=bool(f.get("propio", False)),
                comandos=tuple(f.get("comandos") or VERBOS), go=f.get("formato") == "go")
        except (TypeError, ValueError):
            continue                             # una entrada ilegible no tumba a las demás
    return Datos(version, flags)


_CARGADOS: dict[Path, Datos] = {}


def datos() -> Datos:
    """Devuelve los flags de la rclone fijada (`RUTA_DATOS`), leídos una sola vez."""
    if RUTA_DATOS not in _CARGADOS:
        _CARGADOS[RUTA_DATOS] = cargar(RUTA_DATOS)
    return _CARGADOS[RUTA_DATOS]


def conocido(nombre: str) -> Flag | None:
    """Devuelve el flag con ese nombre (como lo escriba la persona), o `None` si no está en los datos."""
    return datos().flags.get(normalizar(nombre))


# ----------------------------------------------------------------------------
# El tipo del valor
# ----------------------------------------------------------------------------

_DEC = r"(?:[0-9][0-9_]*\.?[0-9]*|\.[0-9]+)"
_EXP = r"(?:[eE][+-]?[0-9]+)?"
_ENTERO = re.compile(
    r"[+-]?(?:0[xX]_?[0-9a-fA-F]+(?:_[0-9a-fA-F]+)*|0[bB]_?[01]+(?:_[01]+)*"
    r"|0[oO]?_?[0-7]+(?:_[0-7]+)*|0|[1-9][0-9]*(?:_[0-9]+)*)")
_DURACION_GO = re.compile(r"[+-]?(?:(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:ns|us|µs|μs|ms|s|m|h))+|[+-]?0")
_DURACION_RCLONE = re.compile(rf"[+-]?{_DEC}{_EXP}(?:ns|us|µs|μs|ms|s|m|h|d|w|M|y)?")
_DURACION_VARIAS = re.compile(r"[+-]?(?:(?:[0-9][0-9_]*\.?[0-9]*|\.[0-9]+)(?:ns|us|µs|μs|ms|s|m|h))+")
_FECHA = re.compile(r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
                    r"(?:[T ](?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]+)?"
                    r"(?:Z|[+-][0-9]{2}:[0-9]{2})?)?")
_TAMANO = re.compile(rf"\+?{_DEC}{_EXP}(?:[bB]|[kKmMgGtTpPeE](?:[iI]|i[bB])?)?")
_NIVELES = frozenset(("debug", "info", "notice", "warning", "error", "critical", "alert",
                      "emergency", "off"))

_HEXADECIMAL = re.compile(r"[+-]?(?:0[xX][0-9a-fA-F_.]+(?:[pP][+-]?[0-9]+)?|[0-9a-fA-F_.]+[pP][+-]?[0-9]+)")
_ENTEROS = ("int", "int64", "int32", "uint", "uint64", "uint32")
_DECIMALES = ("float", "float64", "float32")

_NOMBRE_TIPO = {
    "int": "un número entero", "float": "un número",
    "Duration": "una duración", "SizeSuffix": "un tamaño", "LogLevel": "un nivel de log",
    "string": "un texto", "stringArray": "un texto o una lista de textos",
}


def _nombre_tipo(tipo: str) -> str:
    """Devuelve cómo se llama un tipo en una frase («un número entero»), o «un valor» si no se sabe."""
    if tipo in _ENTEROS:
        tipo = "int"
    elif tipo in _DECIMALES:
        tipo = "float"
    return "una opción" if _opciones(tipo) else _NOMBRE_TIPO.get(tipo, "un valor")


def _es_entero(valor: Any) -> bool:
    """Indica si rclone (que usa `ParseInt` en base 0 y 64 bits) leería este valor como entero."""
    if isinstance(valor, bool):
        return False
    if isinstance(valor, int):
        return -2**63 <= valor < 2**63
    if isinstance(valor, float) or not isinstance(valor, str):
        return False
    texto = valor.strip()
    if not _ENTERO.fullmatch(texto):
        return False
    limpio = texto.replace("_", "")
    try:
        n = int(limpio, 0)
    except ValueError:
        try:
            n = int(limpio, 8)               # el «0123» de Go: octal
        except ValueError:
            return False
    return -2**63 <= n < 2**63


def _es_decimal(valor: Any) -> bool:
    """Indica si rclone (`ParseFloat`) leería este valor como un número."""
    if isinstance(valor, bool):
        return False
    if isinstance(valor, (int, float)):
        return True
    if not isinstance(valor, str) or not valor.isascii():
        return False
    texto = valor.strip()
    try:
        float(texto)
        return True
    except ValueError:
        pass
    if not _HEXADECIMAL.fullmatch(texto):
        return False                             # `abc` no es un decimal en hexadecimal
    try:
        float.fromhex(texto)
        return True
    except ValueError:
        return False


def _es_duracion(valor: Any, go: bool) -> bool:
    """Indica si rclone leería este valor como una duración de ese tipo.

    La duración de rclone (`--max-lock`, `--stats`, `--min-age`…) admite un número
    a secas (segundos), `d`/`w`/`M`/`y`, `off` y una fecha; la de Go (`--timeout`,
    `--modify-window`…) pide unidad en todo menos en el `0`.
    """
    if isinstance(valor, bool):
        return False
    texto = str(valor)
    if go:
        return bool(_DURACION_GO.fullmatch(texto))
    return (texto == "off" or bool(_DURACION_RCLONE.fullmatch(texto))
            or bool(_DURACION_VARIAS.fullmatch(texto)) or bool(_FECHA.fullmatch(texto)))


def _es_tamano(valor: Any) -> bool:
    """Indica si rclone leería este valor como un tamaño: sin sufijo son KiB, y `off` lo quita."""
    if isinstance(valor, bool):
        return False
    texto = str(valor)
    return texto.lower() == "off" or bool(_TAMANO.fullmatch(texto))


def _opciones(tipo: str) -> tuple[str, ...]:
    """Devuelve las opciones de un tipo `A|B|C` de la ayuda de rclone, o `()` si no lo es."""
    return tuple(tipo.split("|")) if "|" in tipo else ()


def _mensaje_tipo(f: Flag, valor: Any) -> str:
    """Devuelve qué se esperaba de este flag y con qué ejemplo, para el aviso rojo."""
    n, tipo = f.nombre, f.tipo
    if tipo in ("bool", "count"):
        return (f"«{valor}» no vale: este flag es de sí o no, y se escribe {n} = true "
                f"(o false), sin comillas. Un texto o un número iría a la orden de rclone "
                f"como un argumento suelto y la rompería.")
    if tipo in _ENTEROS:
        return f"«{valor}» no es un número entero. Ejemplo: {n} = 4."
    if tipo in _DECIMALES:
        return f"«{valor}» no es un número. Ejemplo: {n} = 0.5."
    if tipo == "Duration":
        if f.go:
            return (f"«{valor}» no es una duración con unidad: {n} = \"30s\", \"2m\" o "
                    f"\"1h30m\" (aquí un número a secas, como 30, no vale).")
        return (f"«{valor}» no es una duración. Ejemplos: {n} = \"30s\", \"2m\", \"1h30m\", "
                f"\"1d\" o \"off\" (un número a secas son segundos).")
    if tipo == "SizeSuffix":
        return (f"«{valor}» no es un tamaño. Ejemplos: {n} = \"500k\", \"10M\", \"2G\" u "
                f"\"off\" (sin sufijo son KiB).")
    if tipo == "LogLevel":
        return (f"«{valor}» no es un nivel de log. Los hay DEBUG, INFO, NOTICE, WARNING, "
                f"ERROR, CRITICAL, ALERT, EMERGENCY y OFF.")
    opciones = _opciones(tipo)
    if opciones:
        return f"«{valor}» no es una opción de {n}. Las hay: {', '.join(opciones)}."
    return f"«{valor}» no vale para {n}."


def _problema_escalar(f: Flag, valor: Any) -> str | None:
    """Dice por qué un valor suelto no vale para este flag, o `None` si vale."""
    tipo = f.tipo
    if tipo in ("bool", "count"):
        return None if valor is True else _mensaje_tipo(f, valor)
    if valor is True:
        return (f"necesita un valor ({_nombre_tipo(tipo)}): true no vale, porque rclone se "
                f"comería como valor el argumento que va detrás.")
    if tipo in _ENTEROS:
        ok = _es_entero(valor)
    elif tipo in _DECIMALES:
        ok = _es_decimal(valor)
    elif tipo == "Duration":
        ok = _es_duracion(valor, f.go)
    elif tipo == "SizeSuffix":
        ok = _es_tamano(valor)
    elif tipo == "LogLevel":
        ok = str(valor).lower() in _NIVELES
    elif _opciones(tipo):
        ok = str(valor).upper() in _opciones(tipo)
    else:
        return None                              # texto, lista, horario…: no se opina
    return None if ok else _mensaje_tipo(f, valor)


def problema_valor(nombre: str, valor: Any) -> str | None:
    """Dice por qué este valor no vale para este flag, o `None` si vale.

    Solo opina de un flag que está en los datos y cuando está seguro. `false` vale
    siempre: es quitar el flag (`model.flags_to_args()` no lo pasa). Un valor que
    sea una lista se comprueba elemento a elemento.

    Args:
        nombre: El flag, como lo escriba la persona.
        valor: Su valor, con el tipo que dio `tomllib`.

    Returns:
        La frase para la persona, que dice qué se esperaba y con qué ejemplo.
    """
    f = conocido(nombre)
    if f is None or valor is False:
        return None
    elementos = valor if isinstance(valor, (list, tuple)) else [valor]
    for elemento in elementos:
        if f.tipo == "stringArray" and isinstance(elemento, bool):
            return (f"«{elemento}» no es un texto: {f.nombre} lleva textos, "
                    f"como {f.nombre} = [\"a\", \"b\"].")
        motivo = _problema_escalar(f, elemento)
        if motivo:
            return motivo
    return None


# ----------------------------------------------------------------------------
# Autocompletar
# ----------------------------------------------------------------------------

class Palabra(NamedTuple):
    """El nombre de flag que se está escribiendo en el cuadro.

    Args:
        inicio: Dónde empieza en el texto (índice).
        fin: Dónde acaba la palabra entera, más allá del cursor si lo hay.
        texto: Lo escrito hasta el cursor: con lo que se busca.
    """
    inicio: int
    fin: int
    texto: str


_LETRAS_DE_FLAG = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")


def palabra_en(texto: str, indice: int) -> Palabra | None:
    """Devuelve el nombre de flag que hay en `indice`, o `None` si ahí no se escribe uno.

    Un nombre es la primera palabra de una línea, a la izquierda del `=`: lo que
    va tras el igual es un valor, la segunda palabra no es un nombre y una línea
    de comentario no es nada.

    Args:
        texto: Lo que hay en el cuadro de flags.
        indice: Dónde está el cursor, en caracteres desde el principio.
    """
    ini_linea = texto.rfind("\n", 0, indice) + 1
    fin_linea = texto.find("\n", indice)
    fin_linea = len(texto) if fin_linea < 0 else fin_linea
    if "=" in texto[ini_linea:indice]:
        return None
    inicio = indice
    while inicio > ini_linea and texto[inicio - 1] in _LETRAS_DE_FLAG:
        inicio -= 1
    fin = indice
    while fin < fin_linea and texto[fin] in _LETRAS_DE_FLAG:
        fin += 1
    if inicio == fin or texto[ini_linea:inicio].strip():
        return None                              # nada escrito, o es la segunda palabra
    if texto[ini_linea:fin_linea].lstrip().startswith("#"):
        return None
    return Palabra(inicio, fin, texto[inicio:indice])


def sugerir(prefijo: str, modo: str | None = None, propios: Mapping[str, Any] | None = None,
            limite: int = 8) -> list[Flag]:
    """Devuelve los flags que empiezan (o, después, contienen) lo escrito.

    Sugiere solo lo que se puede poner de verdad: ni lo que `model.problema_flag()`
    rechazaría, ni lo que ya está en el cuadro, ni lo que rclone no conoce en la
    orden del modo. Sin modo (los flags comunes de `[defaults]`) solo lo que vale
    en las tres. No sugerir no es rechazar: lo escrito a mano se admite.

    Args:
        prefijo: Lo escrito hasta el cursor; con o sin `--`, con `-` o `_`.
        modo: El modo de la pareja, o `None` en los flags comunes.
        propios: Los flags que ya hay en el cuadro.
        limite: Cuántos devolver como mucho.

    Returns:
        Los flags, los que empiezan así primero y cada grupo por longitud y nombre.
        Sin nada escrito, ninguno.
    """
    p = normalizar(prefijo)
    if not p:
        return []
    mode = model.MODES.get(modo or "")
    verbos = {mode.verb} if mode else set(VERBOS)
    puestos = {normalizar(k) for k in (propios or {})}
    empiezan, contienen = [], []
    for f in datos().flags.values():
        if (p not in f.nombre or f.nombre in puestos or model.problema_flag(f.nombre)
                or not verbos <= set(f.comandos)):
            continue
        (empiezan if f.nombre.startswith(p) else contienen).append(f)
    orden = lambda f: (len(f.nombre), f.nombre)
    return (sorted(empiezan, key=orden) + sorted(contienen, key=orden))[:limite]


_CLAVE_ESCRITA = re.compile(r"\s*([A-Za-z][A-Za-z0-9_-]*)\s*=")


def escritos(texto: str, sin_linea_en: int | None = None) -> set[str]:
    """Devuelve los nombres de flag que ya hay escritos (con su `=`) en el cuadro.

    Se leen de las líneas y no de `tomllib` a propósito: mientras se escribe, el
    texto casi nunca es un TOML entero (`transf` a medias), y lo que ya está
    puesto tiene que dejar de sugerirse aunque la línea de al lado no cierre.

    Args:
        texto: Lo que hay en el cuadro.
        sin_linea_en: Un índice del texto: la línea en la que está no cuenta (la
            que se está editando).

    Returns:
        Los nombres, como los ve rclone (`normalizar()`).
    """
    nombres: set[str] = set()
    inicio = 0
    for linea in texto.split("\n"):
        fin = inicio + len(linea)
        propia = sin_linea_en is not None and inicio <= sin_linea_en <= fin
        m = _CLAVE_ESCRITA.match(linea)
        if m and not propia:
            nombres.add(normalizar(m.group(1)))
        inicio = fin + 1
    return nombres


def lineas_con(texto: str, nombres: set[str] | frozenset[str]) -> list[int]:
    """Devuelve los números de línea (desde 1) del cuadro cuyo flag está en `nombres`.

    Es para marcar en el propio cuadro la línea de un flag con aviso.

    Args:
        texto: Lo que hay en el cuadro.
        nombres: Los flags, normalizados (`normalizar()`).
    """
    salida = []
    for numero, linea in enumerate(texto.split("\n"), 1):
        m = _CLAVE_ESCRITA.match(linea)
        if m and normalizar(m.group(1)) in nombres:
            salida.append(numero)
    return salida


_TIPOS_PERSONA = {"bool": "sí o no", "count": "sí o no", "float": "número", "Duration": "duración",
                  "SizeSuffix": "tamaño", "LogLevel": "nivel", "string": "texto",
                  "stringArray": "lista", "BwTimetable": "ancho de banda"}


def etiqueta_tipo(f: Flag) -> str:
    """Devuelve el tipo de un flag con palabras de la persona: «sí o no», «duración», «tamaño»…"""
    if f.tipo in _ENTEROS:
        return "entero"
    if _opciones(f.tipo):
        return "opción"
    return _TIPOS_PERSONA.get(f.tipo, f.tipo or "texto")


def descripcion(f: Flag) -> str:
    """Devuelve la ayuda de rclone del flag (en inglés) y su valor de fábrica, en una línea."""
    por_defecto = f" · por defecto {f.defecto}" if f.defecto else ""
    return f"{f.ayuda}{por_defecto}"


def _relleno(f: Flag) -> tuple[str, int]:
    """Devuelve lo que se escribe tras `nombre = ` para ese tipo y dónde queda el cursor dentro."""
    if f.tipo in ("bool", "count"):
        return "true", 4
    if f.tipo in _ENTEROS or f.tipo in _DECIMALES:
        return "", 0
    if f.tipo == "stringArray":
        return '[""]', 2
    return '""', 1


def completar(texto: str, palabra: Palabra, flag: Flag) -> tuple[str, int]:
    """Pone el flag elegido en el lugar de la palabra y devuelve el texto y dónde queda el cursor.

    En una línea nueva escribe también el igual y un valor de partida del tipo
    del flag (`true`, `""`, `[""]`), con el cursor donde se sigue escribiendo; si la
    línea ya tiene su `=`, solo cambia el nombre.

    Args:
        texto: Lo que hay en el cuadro.
        palabra: La que se completa (`palabra_en()`).
        flag: El elegido.
    """
    fin_linea = texto.find("\n", palabra.fin)
    fin_linea = len(texto) if fin_linea < 0 else fin_linea
    if "=" in texto[palabra.fin:fin_linea]:
        nuevo = texto[:palabra.inicio] + flag.nombre + texto[palabra.fin:]
        return nuevo, palabra.inicio + len(flag.nombre)
    relleno, dentro = _relleno(flag)
    escrito = f"{flag.nombre} = {relleno}"
    nuevo = texto[:palabra.inicio] + escrito + texto[palabra.fin:]
    cursor = palabra.inicio + len(escrito) - (len(relleno) - dentro)
    return nuevo, cursor


# ----------------------------------------------------------------------------
# Avisos
# ----------------------------------------------------------------------------

class Aviso(NamedTuple):
    """Algo que conviene leer junto a un flag; no impide guardarlo.

    Args:
        flag: El flag al que va pegado, tal como lo escribió la persona (de la capa
            que se edita).
        tipo: `AVISO_MODO`, `AVISO_CHOQUE` o `AVISO_BORRADO`.
        texto: La frase para la persona.
    """
    flag: str
    tipo: str
    texto: str


class Choque(NamedTuple):
    """Dos o más flags que no pueden ir juntos o se pisan.

    Args:
        flags: Los flags; el aviso va con el primero propio de la pareja en este orden.
        verbos: Las órdenes de rclone donde pasa, o `None` en todas.
        texto: La frase; `{flags}` es la lista de los que están puestos.
    """
    flags: tuple[str, ...]
    verbos: tuple[str, ...] | None
    texto: str


CHOQUES: tuple[Choque, ...] = (
    # Medido con rclone v1.75.2 en sync, copy y bisync: «CRITICAL: Only one of
    # --delete-before, --delete-during or --delete-after can be used.», rc 1.
    Choque(("delete-before", "delete-during", "delete-after"), None,
           "{flags} no se pueden poner a la vez (solo uno de los tres): rclone aborta la pasada."),
    # Medido: con los dos, un fichero de igual tamaño y distinto contenido no se copia.
    Choque(("size-only", "checksum"), None,
           "{flags} se pisan: con --size-only rclone no mira los checksums, así que "
           "--checksum no sirve de nada."),
    # Medido: con los dos, un fichero que ya existe y es distinto no se copia.
    Choque(("ignore-existing", "ignore-times"), None,
           "{flags} se pisan: con --ignore-existing rclone se salta lo que ya existe en el "
           "destino, así que --ignore-times no llega a actuar."),
    Choque(("ignore-existing", "checksum"), None,
           "{flags} se pisan: con --ignore-existing rclone se salta lo que ya existe en el "
           "destino, así que --checksum no llega a comparar nada."),
    # De la ayuda de `rclone bisync`: «(Not compatible with --remove-empty-dirs)».
    Choque(("remove-empty-dirs", "create-empty-src-dirs"), ("bisync",),
           "{flags} son incompatibles en bisync (lo dice su ayuda), y prdrive pone "
           "--create-empty-src-dirs en cada pasada."),
    # De la ayuda de `rclone bisync`: «--force: Bypass --max-delete safety check».
    Choque(("force", "max-delete"), ("bisync",),
           "{flags}: --force se salta el freno de --max-delete, que es justo para lo que "
           "sirve ponerlo."),
)
"""Los choques que se avisan, con de dónde sale cada uno. Rclone no los dice en su ayuda."""

BORRADO: Mapping[str, tuple[str, tuple[str, ...] | None]] = {
    "delete-before": ("borra en el destino lo que ya no está en el origen, antes de copiar", None),
    "delete-during": ("borra en el destino lo que ya no está en el origen, mientras copia", None),
    "delete-after": ("borra en el destino lo que ya no está en el origen, al acabar de copiar",
                     None),
    "delete-excluded": ("borra del destino lo que los filtros dejan fuera", None),
    "ignore-errors": ("sigue borrando aunque haya habido errores de lectura: un lado que no se "
                      "ha leído entero parece vacío", None),
    "force": ("se salta el freno de --max-delete", None),
    "remove-empty-dirs": ("quita todas las carpetas vacías al final de la pasada", None),
    "conflict-loser": ("con delete, el que pierde un conflicto se borra en vez de guardarse "
                       "con otro nombre", ("delete",)),
    "resync-mode": ("en una resincronización da la razón a un lado y sobrescribe el otro",
                    ("path1", "path2", "newer", "older", "larger", "smaller")),
    "track-renames": ("mueve en el destino lo que cree renombrado en el origen", None),
    "fix-case": ("renombra en el destino para igualar las mayúsculas del origen", None),
    "name-transform": ("cambia los nombres de los ficheros al copiarlos", None),
    "inplace": ("escribe encima del fichero de destino sin pasar por uno temporal: una pasada "
                "cortada lo deja a medias", None),
    "ignore-times": ("vuelve a copiar todo, aunque ya esté igual", None),
    "no-check-dest": ("copia sin mirar el destino: sobrescribe lo que haya", None),
    "refresh-times": ("reescribe las fechas de los ficheros del remoto", None),
}
"""Los flags que borran o reescriben ficheros, con qué hacen y, si solo con algunos valores, cuáles.

Es la tabla de la regla de `AGENTS.md`: cualquier pareja `*-mirror` borra en el otro
lado y nada así se prueba sin `--dry-run`. `max-delete` y `max-delete-size` no están:
son el freno, y los vigila `flags_editor.warnings()`.
"""

SOLO_SINCRONIZA = frozenset((
    "delete-before", "delete-during", "delete-after", "delete-excluded", "max-delete",
    "max-delete-size", "ignore-errors", "track-renames", "track-renames-strategy", "fix-case"))
"""Globales que rclone solo usa al sincronizar (el grupo `Sync`): `copy` no hace nada con ellos.

rclone los acepta en `copy` (no da error), por eso salen de aquí y no de los datos.
Medido con la v1.75.2 sobre dos carpetas: `copy` deja intactos el fichero de más y el
excluido con `--delete-before/during/after` y `--delete-excluded`, que `sync` borra;
`--fix-case` no renombra, y de `--track-renames` el propio rclone dice «Ignoring
--track-renames as it doesn't work with copy or move, only sync». Los demás
(`--ignore-errors`, `--max-delete*`) solo modulan borrados, que `copy` no hace.
"""

def _activo(valor: Any) -> bool:
    """Indica si un valor hace que el flag llegue a rclone (`false`, `None` y vacío, no)."""
    return valor not in (False, None, "", [], ())


def _unir(nombres: list[str]) -> str:
    """Devuelve `--a, --b y --c` para una lista de flags."""
    marcados = [f"--{n}" for n in nombres]
    return marcados[0] if len(marcados) == 1 else ", ".join(marcados[:-1]) + " y " + marcados[-1]


def _aviso_de_modo(n: str, f: Flag | None, modo: str | None, verbos: set[str]) -> str | None:
    """Dice por qué el flag `n` no es de este modo, o `None` si lo es."""
    if f is not None and f.propio and not verbos <= set(f.comandos):
        donde = " y ".join(f.comandos) if len(f.comandos) < 3 else "las tres órdenes"
        if modo is None:
            return (f"--{n} es solo de {donde}: en las parejas de los otros modos rclone no lo "
                    f"conoce («unknown flag») y la pasada fallaría.")
        orden = next(iter(verbos))
        return (f"--{n} es de {donde}, y esta pareja ({modo}) usa «rclone {orden}»: rclone no "
                f"lo conoce («unknown flag») y la pasada fallaría.")
    if n in SOLO_SINCRONIZA and verbos == {"copy"}:
        return (f"--{n} no hace nada en este modo ({modo}): solo copia, nunca borra del "
                f"destino.")
    return None


def avisos(modo: str | None, defaults_flags: Mapping[str, Any] | None,
           propios: Mapping[str, Any] | None,
           capa: str = model.ORIGEN_PAREJA) -> list[Aviso]:
    """Devuelve lo que conviene leer junto a los flags que se están escribiendo.

    Solo habla de los flags de la capa que se edita, pero los choques se miran
    contra todos los que le llegarían a rclone (los de siempre, los del modo y los
    de `[defaults]`): `--remove-empty-dirs` choca con el `--create-empty-src-dirs`
    que trae prdrive. Dos heredados que chocan no son cosa de esta pareja y no
    salen. Nunca lanza ni impide nada.

    Args:
        modo: El modo de la pareja, o `None` en `[defaults]`.
        defaults_flags: `[defaults.flags]`.
        propios: Los flags de la capa que se edita.
        capa: `model.ORIGEN_PAREJA`, o `model.ORIGEN_DEFAULTS` si se editan los
            comunes (sin modo: lo de «otro modo» se mira contra las tres órdenes).

    Returns:
        Los avisos, por el orden en que se escribió cada flag.
    """
    mode = None if capa == model.ORIGEN_DEFAULTS else model.MODES.get(modo or "")
    verbos = {mode.verb} if mode else set(VERBOS)
    if capa == model.ORIGEN_DEFAULTS:
        efectivos = model.flags_efectivos(None, propios, None)
    else:
        efectivos = model.flags_efectivos(mode, defaults_flags, propios)
    puestos = {normalizar(e.nombre): e.valor for e in efectivos}
    escritos: dict[str, tuple[str, Any]] = {}
    for clave, valor in dict(propios or {}).items():
        escritos[normalizar(clave)] = (str(clave), valor)

    encontrados: list[tuple[int, int, Aviso]] = []
    for pos, (n, (escrito, valor)) in enumerate(escritos.items()):
        if not _activo(valor):
            continue
        texto_modo = _aviso_de_modo(n, conocido(n), modo if mode else None, verbos)
        if texto_modo:
            encontrados.append((pos, 0, Aviso(escrito, AVISO_MODO, texto_modo)))
            if n in SOLO_SINCRONIZA and verbos == {"copy"}:
                continue                         # no hace nada: no hay nada que borrar
        if n in BORRADO:
            motivo, valores = BORRADO[n]
            if valores is None or str(valor).lower() in valores:
                con_valor = f"--{n}" if valores is None else f"--{n} {valor}"
                cola = (" Una pareja *-mirror borra en el otro lado." if modo is None
                        or modo.endswith("-mirror") else "")
                encontrados.append((pos, 1, Aviso(
                    escrito, AVISO_BORRADO,
                    f"{con_valor} {motivo}. Pruébalo antes con «Simular» (--dry-run).{cola}")))

    for choque in CHOQUES:
        if choque.verbos is not None and (mode is None or mode.verb not in choque.verbos):
            continue
        puestos_aqui = [n for n in choque.flags if _activo(puestos.get(n))]
        propio = next((n for n in puestos_aqui if n in escritos and _activo(escritos[n][1])),
                      None)
        if len(puestos_aqui) < 2 or propio is None:
            continue
        pos = list(escritos).index(propio)
        encontrados.append((pos, 2, Aviso(escritos[propio][0], AVISO_CHOQUE,
                                          choque.texto.format(flags=_unir(puestos_aqui)))))
    return [a for _p, _r, a in sorted(encontrados, key=lambda t: (t[0], t[1]))]
