#!/usr/bin/env python3
"""Los flags de rclone de una pareja (o de `[defaults]`), sin Tkinter.

Aquí se traduce entre lo que la persona escribe en un cuadro de texto y lo que
acaba en el TOML, en los dos sentidos, y se comprueba que lo escrito se puede
escribir de verdad. Dibujar es cosa de `ui/tk_pairs.py`.

Hay dos decisiones que conviene no deshacer:
- **El texto se parsea con `tomllib`, no a mano.** El destino de estas líneas
  es una tabla `[pair.flags]` del TOML, así que la única forma de que el
  formulario y el fichero entiendan lo mismo es usar el mismo parser. Un
  mini-parser propio acabaría aceptando `max-delete = 1_000` o `"true"` y
  guardando algo distinto de lo que se lee en pantalla.
- **No se admite cualquier flag.** `sync.py` pone los suyos en cada ejecución
  (`--config`, `--log-file`, `--dry-run`, `--workdir`, `--resync`) y los de
  filtrado salen de los patrones incluir/excluir (`orden.filter_args`). Repetirlos
  aquí no los sustituye: rclone recibiría el flag dos veces y, en el caso de
  `--workdir` o `--filters-file`, eso es apuntar a bisync a un baseline que no
  es el suyo. Por eso `RESERVED` (`model.FLAGS_RESERVADOS`) se rechaza al
  parsear y no al ejecutar. Tampoco se admite un flag que haga que rclone
  lance un programa de este equipo (`--sftp-ssh`, `--password-command`…) ni
  uno que escriba un fichero cualquiera de él (`--cpuprofile`, `--memprofile`):
  el config viaja con el dispositivo. Todas son reglas de
  `model.problema_flag()`, la puerta del parser del config; aquí solo se avisa
  al escribir.

Lo demás se admite sin lista blanca: quién sabe qué flags existen es rclone, y
la regla del proyecto es que un flag nuevo se añade escribiéndolo, no tocando
código. Lo único que se comprueba de un flag que sí está en los datos de la
rclone fijada es el tipo de su valor (`flags_ayuda.problema_valor()`, por la
misma puerta), y solo cuando es seguro que rclone lo rechazaría. El
autocompletado y los avisos que no bloquean (`flags_ayuda.sugerir()`,
`avisos()`) viven en `ui/flags_ayuda.py`.

Además del texto, el editor enseña los flags EFECTIVOS de la pareja, cada uno
con la capa de la que sale (`effective()`), deja sobrescribir uno heredado o
volver a heredarlo (`sobrescribir()`, `heredar()`: dan el `[pair.flags]` nuevo)
y enseña la orden de rclone que saldría (`lineas_de_la_orden()`). Las tres
cosas salen de `model.flags_efectivos()` y de `orden.tramos()`, las mismas
piezas con las que `sync.py` monta cada pasada: nada de esto es una copia.
"""

from __future__ import annotations

import re
import tomllib
from typing import Any, Mapping, NamedTuple

from common import config_file, model, orden
from common.model import ConfigError, FlagEfectivo
from . import flags_ayuda


class FlagReservado(ConfigError):
    """Un flag que no se admite aquí: lo pone el programa o toca este equipo.

    Es lo que rechaza `model.problema_flag()`: los de `RESERVED`, los que hacen
    que rclone ejecute una orden de este equipo y los que le hacen escribir un
    fichero cualquiera (`model.FLAGS_ESCRIBEN`). Lo es tanto el del cuadro de
    flags como el del de argumentos extra, para que el aviso lleve el mismo
    título (`titulo_error()`) escriba donde escriba la persona.
    """


TITULO_RESERVADO = "Este flag no se puede poner aquí"
"""El título del aviso de un flag reservado."""
TITULO_NO_VALE = "Esto no se puede guardar así"
"""El título del aviso de cualquier otro texto que no vale."""


def titulo_error(error: ConfigError) -> str:
    """Devuelve el título del aviso rojo que explica por qué no vale lo escrito."""
    return TITULO_RESERVADO if isinstance(error, FlagReservado) else TITULO_NO_VALE


RESERVED = model.FLAGS_RESERVADOS
"""Flags que `sync.py` pone por su cuenta, con el motivo de cada uno."""

_NOMBRE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
"""Un nombre de flag válido: lo que va detrás de `--`.

`flags_to_args()` convierte `_` en `-`.
"""

ESCALARES = (bool, int, float, str)
"""Tipos de valor que admite un flag, solo o dentro de una lista."""

FRENOS = ("max-delete", "max-delete-size")
"""Flags cuyo valor es un freno de mano y no una preferencia: cambiarlos se avisa."""


ETIQUETA_PRDRIVE = "lo pone prdrive"
"""Lo que se lee en un trozo de la orden que añade el programa y no se configura."""

LOG_PREVIO = "<log de la pasada>"
"""Lo que la vista previa pone donde `sync.py` pone el log temporal de cada pasada."""

SELLO_PREVIO = "<marca de la pasada>"
"""Lo que la vista previa pone donde `sync.py` pone el sufijo de las versiones."""

LEYENDA_ORDEN = ("Sombreado, lo que pone prdrive en cada pasada (--config, --log-file, "
                 "--workdir…): los pone prdrive y no se cambian desde aquí. Es la orden de "
                 "una pasada normal; un --resync o una simulación añaden lo suyo.")
"""Lo que explica la vista previa de la orden, bajo ella."""


class Row(NamedTuple):
    """Una línea de la tabla de flags efectivos.

    Args:
        nombre: El flag sin guiones y con `-` (`max-delete`).
        flag: El flag tal cual se le pasa a rclone (`--transfers 4`); si está
            apagado y por eso no llega, solo `--nombre`.
        valor: Su valor para leerlo (`4`, `activado`, `desactivado`, `a, b`).
        crudo: Su valor con el tipo del TOML, el que se copia al sobrescribirlo.
        origen: La capa que ha ganado (`model.ORIGEN_*`).
        etiqueta: Esa capa, para la persona (`etiqueta()`).
        propio: Si sale de la capa que se está editando: es lo que se puede
            quitar. Lo demás se puede sobrescribir.
        activo: Si llega a rclone; un flag a `false` se enseña pero no llega.
        nota: Qué pasa si se toca esta fila (`acciones()`).
    """
    nombre: str
    flag: str
    valor: str
    crudo: Any
    origen: str
    etiqueta: str
    propio: bool
    activo: bool
    nota: str


class Linea(NamedTuple):
    """Un trozo de la orden de rclone de la vista previa.

    Args:
        args: Los argumentos del trozo, tal como van a la línea de comandos.
        origen: Quién lo pone (`model.ORIGEN_*`).
        etiqueta: Ese origen, para la persona.
        lo_pone_prdrive: Si lo añade el programa en cada pasada (`--config`,
            `--log-file`, `--workdir`…): no se configura y no se puede cambiar.
    """
    args: tuple[str, ...]
    origen: str
    etiqueta: str
    lo_pone_prdrive: bool

    @property
    def texto(self) -> str:
        """Devuelve el trozo como se escribiría en la línea de comandos."""
        return " ".join(self.args)


normalize = model.normalizar_flag


def dump(flags: Mapping[str, Any] | None) -> str:
    """Devuelve la tabla como texto editable: exactamente lo que escribiría el TOML."""
    return config_file.dumps_table(dict(flags or {}))


def parse(text: str) -> dict:
    """Devuelve el texto del cuadro como tabla de flags.

    Solo se acepta lo que `common/config_file.py` sabe volver a escribir
    (escalares y arrays de escalares), porque `save()` se niega a escribir un
    config que no se relea igual y ese «no» llegaría demasiado tarde: con el
    diálogo ya cerrado y el plan ya confirmado.

    Raises:
        ConfigError: Si el texto no vale.
    """
    lineas = [l for l in text.splitlines() if l.strip()]
    for linea in lineas:
        if linea.lstrip().startswith("-"):
            raise ConfigError(
                f"'{linea.strip()}' es como se escribe en la línea de comandos. Aquí "
                f"va una línea por flag y sin los guiones: transfers = 4, o "
                f"checksum = true.")
    try:
        tabla = tomllib.loads("\n".join(lineas))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Eso no es TOML válido ({e}).\n\nUna línea por flag, "
                          f"'clave = valor': transfers = 4, max-delete = 25, "
                          f'conflict-resolve = "newer", checksum = true.') from e

    for key, value in tabla.items():
        _validar(key, value)
    return tabla


def _validar(key: str, value: Any) -> None:
    """Comprueba un flag del cuadro y lanza `ConfigError` si no vale."""
    if not _NOMBRE.fullmatch(key):
        raise ConfigError(f"'{key}' no puede ser el nombre de un flag: es lo que va "
                          f"detrás de '--', o sea letras, números, '-' y '_'.")
    motivo = model.problema_flag(key)
    if motivo:
        raise FlagReservado(f"'{key}' no se configura aquí: {motivo}.")
    if isinstance(value, dict):
        raise ConfigError(f"'{key}': aquí no caben tablas, solo 'clave = valor'.")
    if isinstance(value, (list, tuple)):
        for item in value:
            if not isinstance(item, ESCALARES):
                raise ConfigError(f"'{key}': una lista solo admite textos, números "
                                  f"o true/false.")
    elif not isinstance(value, ESCALARES):
        raise ConfigError(f"'{key}': valor no admitido ({type(value).__name__}). "
                          f"Textos entre comillas, números, o true/false.")
    motivo = model.problema_valor_flag(key, value)
    if motivo:
        raise ConfigError(f"'{key}': en su valor, {motivo}")
    motivo = flags_ayuda.problema_valor(key, value)
    if motivo:
        raise ConfigError(f"'{key}': {motivo}")


def dump_extra(extra: Any) -> str:
    """Devuelve `extra_flags` como texto: un argumento por línea."""
    return "\n".join(model._as_tuple(extra))


def parse_extra(text: str) -> list[str]:
    """Devuelve el cuadro de `extra_flags`: un argumento de rclone por línea, tal cual.

    Es la salida de emergencia para lo que `clave = valor` no sabe expresar y
    va sin tocar a la línea de comandos: por eso el valor de un flag ocupa su
    propia línea (`--bwlimit` y `8M` son dos argumentos, no uno). Lo que el
    config no admite (`model.problema_extra()`) se rechaza aquí, para que el
    diálogo lo diga al escribirlo y no más tarde, al guardar el plan.

    Raises:
        FlagReservado: Si algún argumento lanza un programa o es de los que pone
            `sync.py` (es un `ConfigError`).
    """
    args = [l.strip() for l in text.splitlines() if l.strip()]
    motivo = model.problema_extra(args)
    if motivo:
        raise FlagReservado(motivo)
    return args


def merge(mode_name: str | None, defaults_flags: Mapping[str, Any] | None,
          pair_flags: Mapping[str, Any] | None) -> dict:
    """Devuelve las capas fundidas igual que en `model._build_pair`.

    El orden es base < modo < `[defaults.flags]` < `[pair.flags]`.
    """
    modo = model.MODES.get(mode_name or "")
    return {f.nombre: f.valor
            for f in model.flags_efectivos(modo, defaults_flags, pair_flags)}


def etiqueta(origen: str, mode_name: str | None = None) -> str:
    """Devuelve cómo se lee una capa de flags (`model.ORIGEN_*`).

    Args:
        origen: La capa.
        mode_name: El modo de la pareja, para nombrar la capa del modo.
    """
    return {model.ORIGEN_BASE: "siempre",
            model.ORIGEN_MODO: f"modo {mode_name}",
            model.ORIGEN_DEFAULTS: "[defaults]",
            model.ORIGEN_PAREJA: "esta pareja",
            model.ORIGEN_PRDRIVE: ETIQUETA_PRDRIVE,
            model.ORIGEN_PATRONES: "incluir/excluir",
            model.ORIGEN_EXTRA: "extra"}[origen]


def cascada(capa: str = model.ORIGEN_PAREJA) -> str:
    """Devuelve la frase que dice en qué orden se funden las capas de flags.

    Args:
        capa: La capa que se edita; en `[defaults]` no hay modo ni pareja.
    """
    if capa == model.ORIGEN_DEFAULTS:
        return "Se funden en este orden: siempre → [defaults]."
    return "Se funden en este orden: siempre → modo → [defaults] → esta pareja."


def sin_orden(error: ConfigError) -> str:
    """Devuelve lo que se dice en lugar de la orden cuando la pareja aún no se puede resolver."""
    return f"Todavía no se puede componer la orden: {error}"


def valor_texto(valor: Any) -> str:
    """Devuelve el valor de un flag para leerlo: `activado`, `desactivado`, o el valor."""
    if valor is True:
        return "activado"
    if valor is False or valor is None:
        return "desactivado"
    if isinstance(valor, (list, tuple)):
        return ", ".join(str(v) for v in valor) or "desactivado"
    return str(valor)


def _por_nombre(efectivos: list[FlagEfectivo]) -> dict[str, FlagEfectivo]:
    """Junta los flags por el nombre que ve rclone: de dos grafías gana la última."""
    return {normalize(f.nombre): f for f in efectivos}


def effective(mode_name: str | None, defaults_flags: Mapping[str, Any] | None,
              pair_flags: Mapping[str, Any] | None,
              capa: str = model.ORIGEN_PAREJA) -> list[Row]:
    """Devuelve los flags que recibiría rclone y de qué capa sale cada uno.

    Es el sentido de todo esto: se escriben en cuatro sitios y hasta ahora solo
    se veían juntos en la línea de comandos, o sea cuando ya se está
    ejecutando. Sale de `model.flags_efectivos()`, la misma cascada de la que
    sale `Pair.flags`.

    Args:
        mode_name: El modo de la pareja.
        defaults_flags: `[defaults.flags]`.
        pair_flags: Lo que se está editando: `[pair.flags]`, o `[defaults.flags]`
            si `capa` es `model.ORIGEN_DEFAULTS`.
        capa: La capa que se edita. Con `ORIGEN_DEFAULTS` no hay modo ni nada
            por encima de la base: `pair_flags` son los comunes y los de
            `defaults_flags` y `mode_name` no cuentan.

    Returns:
        Una fila por flag, ordenadas por nombre.
    """
    if capa == model.ORIGEN_DEFAULTS:
        mode_name, modo = None, None
        ganadores = model.flags_efectivos(None, pair_flags, None)
        debajo = model.flags_efectivos(None, None, None)
    else:
        modo = model.MODES.get(mode_name or "")
        ganadores = model.flags_efectivos(modo, defaults_flags, pair_flags)
        debajo = model.flags_efectivos(modo, defaults_flags, None)
    de_debajo = _por_nombre(debajo)

    filas = []
    for nombre, f in _por_nombre(ganadores).items():
        args = model.flags_to_args({f.nombre: f.valor})
        propio = f.origen == capa
        if propio:
            antes = de_debajo.get(nombre)
            nota = ("Si lo quitas, rclone deja de recibirlo." if antes is None else
                    f"Si lo quitas, vuelve a valer {valor_texto(antes.valor)} "
                    f"({etiqueta(antes.origen, mode_name)}).")
        else:
            nota = (f"Viene de {etiqueta(f.origen, mode_name)}. Sobrescribirlo lo copia a "
                    f"lo que escribes, para que lo cambies.")
        filas.append(Row(nombre=nombre, flag=" ".join(args) if args else f"--{nombre}",
                         valor=valor_texto(f.valor) if args else "desactivado",
                         crudo=f.valor, origen=f.origen,
                         etiqueta=etiqueta(f.origen, mode_name), propio=propio,
                         activo=bool(args), nota=nota))
    return sorted(filas, key=lambda fila: fila.nombre)


def sobrescribir(propios: Mapping[str, Any] | None, nombre: str, valor: Any) -> dict:
    """Devuelve la tabla de flags de la pareja con ese flag puesto a ese valor.

    Es sobrescribir uno heredado (se pone con el valor que heredaba, y vale lo
    mismo hasta que se cambie) o cambiar uno propio. Pasa por la misma puerta
    que lo escrito en el cuadro (`_validar()`), así que un flag que `sync.py`
    pone por su cuenta o que lanza un programa de este equipo se rechaza aquí
    igual que allí.

    Args:
        propios: `[pair.flags]` de ahora; no se toca.
        nombre: El flag, con `-` o con `_`.
        valor: Su valor, con el tipo del TOML.

    Raises:
        FlagReservado: Si el flag no se admite (`model.problema_flag()`).
        ConfigError: Si el flag o su valor no valen.
    """
    clave = normalize(nombre)
    _validar(clave, valor)
    nuevos = {k: v for k, v in dict(propios or {}).items() if normalize(k) != clave}
    nuevos[clave] = valor
    return nuevos


def heredar(propios: Mapping[str, Any] | None, nombre: str) -> dict:
    """Devuelve la tabla de flags de la pareja sin ese flag: vuelve a valer lo heredado.

    Quita el flag con cualquiera de sus grafías (`max-delete`, `max_delete`).
    Si no era de la pareja, no cambia nada.

    Args:
        propios: `[pair.flags]` de ahora; no se toca.
        nombre: El flag.
    """
    clave = normalize(nombre)
    return {k: v for k, v in dict(propios or {}).items() if normalize(k) != clave}


def acciones(fila: Row | None) -> tuple[bool, bool]:
    """Dice qué se puede hacer con una fila de la tabla.

    Returns:
        `(sobrescribir, volver a heredar)`: lo heredado se sobrescribe y lo
        propio se quita; sin fila elegida, ninguna de las dos.
    """
    if fila is None:
        return (False, False)
    return (not fila.propio, fila.propio)


def trozos(lineas: list[Linea]) -> list[tuple[str, bool]]:
    """Junta las líneas seguidas que pone la misma mano, para dibujar la orden de corrido.

    Returns:
        `(texto, lo_pone_prdrive)` por cada racha: lo que pone el programa
        queda en bloques (`rclone bisync <extremos> --filters-file …`,
        `--config … --log-file … --workdir …`) y lo demás, en los suyos.
    """
    rachas: list[tuple[list[str], bool]] = []
    for linea in lineas:
        if rachas and rachas[-1][1] == linea.lo_pone_prdrive:
            rachas[-1][0].append(linea.texto)
        else:
            rachas.append(([linea.texto], linea.lo_pone_prdrive))
    return [(" ".join(textos), puesto) for textos, puesto in rachas]


def lineas_de_la_orden(pair: model.Pair, filtros=None) -> list[Linea]:
    """Devuelve la orden de rclone de una pasada normal de la pareja, sin ejecutarla.

    La monta `orden.tramos()`, lo mismo que `sync.build_command()`. Donde la
    orden lleva algo que solo existe al ejecutar (el log de la pasada, el sufijo
    de las versiones) se pone `LOG_PREVIO` o `SELLO_PREVIO`, y el rclone se
    llama `rclone`. Lo que añade el programa va marcado (`Linea.lo_pone_prdrive`).

    Args:
        pair: La pareja, ya resuelta (`model.parse_config()`).
        filtros: Su fichero de filtros (`bisync.ruta_filtros()`), o `None`.
    """
    tramos = orden.tramos(pair, binario="rclone", filtros=filtros, config=model.RCLONE_CONF,
                          logfile=LOG_PREVIO, sello=SELLO_PREVIO)
    return [Linea(t.args, t.origen, etiqueta(t.origen, pair.mode.name),
                  t.origen == model.ORIGEN_PRDRIVE) for t in tramos]


def summary(flags: Mapping[str, Any] | None, extra: Any = None) -> str:
    """Devuelve lo que dice el botón: cuántos propios hay sin tener que abrirlos."""
    n, m = len(dict(flags or {})), len(model._as_tuple(extra))
    if not n and not m:
        return "ninguno propio"
    partes = []
    if n:
        partes.append(f"{n} flag{'s' if n != 1 else ''}")
    if m:
        partes.append(f"{m} extra")
    return " + ".join(partes)


def changes(antes: Mapping[str, Any] | None,
            despues: Mapping[str, Any] | None) -> list[str]:
    """Devuelve, flag a flag, qué se ha tocado; alimenta las consecuencias del plan."""
    uno, otro = dict(antes or {}), dict(despues or {})
    salida = []
    for key in sorted(set(uno) | set(otro)):
        if uno.get(key) == otro.get(key):
            continue
        if key not in otro:
            salida.append(f"quita {key} (vuelve a valer el de la capa de debajo)")
        elif key not in uno:
            salida.append(f"añade {key} = {otro[key]!r}")
        else:
            salida.append(f"{key}: {uno[key]!r} -> {otro[key]!r}")
    return salida


def warnings(antes: Mapping[str, Any] | None,
             despues: Mapping[str, Any] | None,
             mode_name: str | None = None) -> list[str]:
    """Devuelve los avisos que merecen leerse dos veces antes de guardar.

    Recibe los flags YA FUNDIDOS (los de `merge()`) y no los de una capa
    suelta, que es lo único que hace bien esta comprobación: quitar un flag de
    la pareja lo sube o lo baja según lo que diga la capa de debajo, y cambiar
    de modo lo cambia sin que nadie haya tocado ningún flag.

    `--max-delete` es el freno que impide que un lado vacío (una ruta que no
    está montada, un baseline que se ha quedado viejo) arrase el otro: subirlo
    o quitarlo no es una preferencia de rendimiento. En bisync, además, NO es
    una cuenta de ficheros: `Options.applyContext()` (cmd/bisync/cmd.go) lo
    reduce a un porcentaje de 0 a 100 y `excessDeletes()`
    (cmd/bisync/deltas.go) lo compara contra `borrados /
    ficheros_del_listado_anterior`, así que `mode_name` decide la unidad del
    aviso. En copy/mirror sí es la cuenta corriente de `sync`.
    """
    avisos = []
    efectivos_antes = dict(antes or {})
    efectivos = dict(despues or {})
    modo = model.MODES.get(mode_name or "")
    es_bisync = bool(modo and modo.is_bisync)
    for freno in FRENOS:
        viejo, nuevo = efectivos_antes.get(freno), efectivos.get(freno)
        if viejo == nuevo:
            continue
        if nuevo in (None, False):
            avisos.append(
                f"Sin '{freno}' desaparece el freno que impide que un lado vacío o "
                f"desmontado borre el otro entero.")
        elif isinstance(nuevo, int) and isinstance(viejo, int) and nuevo > viejo:
            if freno == "max-delete" and es_bisync:
                avisos.append(
                    f"'{freno}' pasa de {viejo} a {nuevo}: en bisync es un "
                    f"porcentaje del listado anterior, no una cuenta de ficheros, "
                    f"así que se permite borrar de golpe una porción mayor antes "
                    f"de que rclone aborte.")
            else:
                avisos.append(
                    f"'{freno}' pasa de {viejo} a {nuevo}: se permiten más "
                    f"borrados de golpe antes de que rclone aborte.")
    return avisos
