#!/usr/bin/env python3
"""Regenera `common/flags_rclone.json`: los flags de la rclone fijada en `common/pins.py`.

Es lo que lee el editor de flags de una pareja (`ui/flags_ayuda.py`) para
autocompletar y comprobar el tipo de un valor sin red, y lo que usa el config
(`model.problema_extra()`) para leer los flags de una letra como rclone. Hay que volver a correrlo
cada vez que se mueve `pins.RCLONE_VERSION` (`tests/test_flags_rclone_datos.py`
falla si el fichero es de otra versión):

    python generar_flags_rclone.py                  # baja la rclone fijada (comprobada)
    python generar_flags_rclone.py --rclone RUTA    # o usa esa, que tiene que ser la fijada

De dónde sale, comprobado con la v1.75.2:
- **`rclone help flags`** da todos los flags globales, con su grupo, su tipo y su
  valor de fábrica. No sirve `rclone rc --loopback options/info`: es JSON, pero
  le faltan veinte flags que `sync` acepta (`--verbose`, `--quiet`, `--stats`,
  `--delete-before/during/after`, `--bind`, `--dscp`, `--header*`…) y trae
  otros cien que son del servidor y del montaje (`serve`, `mount`), no de una
  pasada.
- **`rclone bisync|sync|copy --help`** dan, cada uno, los flags PROPIOS de la orden
  (sección `Flags:`: `--resilient`, `--combined`…). Fuera de ella rclone responde
  `unknown flag` (comprobado: `--resilient` en `sync`, `--combined` en `bisync`),
  y eso es lo que dicen `propio` y `comandos`. De un flag global, en cambio, solo se
  puede afirmar que rclone lo acepta en las tres: los grupos que cada `--help`
  enseña no dicen dónde sirve (`copy` no enseña `Listing` y `bisync` tampoco `Sync`
  ni `Listing`, y `--fast-list` va en las dos). Qué global es de borrado o está
  pensado para otro modo lo sabe la tabla a mano de `ui/flags_ayuda.py`.

Los flags del backend (`--s3-region`…), los del control remoto (`--rc-*`) y los de
las métricas no entran: viven en `rclone.conf` o los rechaza el config, y un flag
que no está aquí se admite igual (no hay lista blanca).

Las **letras**, en cambio, salen de todas las secciones, el backend incluido
(`-L` es `--copy-links` y `-x` `--one-file-system`, del backend `local`): van
aparte, en `cortos`, y son lo que usa `model.problema_extra()` para leer un `-vn1`
como lo lee rclone (pflag, `parseSingleShortArg`). El `-h` de cada orden no entra.
Por lo mismo, `con_valor_fuera` nombra los flags de los grupos que no entran que se
comen un valor (`--s3-region`): rclone se los da aunque empiecen por `-`.

Solo biblioteca estándar. Sin `--rclone`, usa el rclone fijado de
`install/rclone_bin.py` (caché o descarga, comprobado contra su SHA256SUMS).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parent
"""La raíz del proyecto."""

SALIDA = REPO / "common" / "flags_rclone.json"
"""El fichero de datos que se escribe."""

VERBOS = ("bisync", "sync", "copy")
"""Las órdenes de rclone que lanza `sync.py` (`model.Mode.verb`)."""

GRUPOS_FUERA = ("Backend", "RC", "Metrics")
"""Grupos de `rclone help flags` que no entran en los datos (ver arriba)."""

LOCAL = "local"
"""La «sección» de los flags propios de una orden, y su «grupo» en los datos."""


class ErrorDeAyuda(Exception):
    """La salida de rclone no es lo que se esperaba: no se escribe nada."""


class Entrada(NamedTuple):
    """Un flag tal como lo enseña una ayuda de rclone.

    Args:
        nombre: Sin guiones (`max-delete`).
        corto: Su nombre de una letra (`c` de `-c`), o `""`.
        tipo: El tipo que dice la ayuda (`int`, `Duration`, `stringArray`,
            `HARD|SOFT|CAUTIOUS`…); `bool` si no dice ninguno.
        defecto: Su valor de fábrica, sin comillas, o `""` si no lo dice.
        ayuda: Su explicación, en inglés y sin el valor de fábrica.
    """
    nombre: str
    corto: str
    tipo: str
    defecto: str
    ayuda: str


TIPOS_SIN_VALOR = ("bool", "count")
"""Los tipos de flag que no se comen el argumento siguiente (pflag les da `NoOptDefVal`)."""


_ENCABEZADO = re.compile(r"^(?:(Flags)|.+ \(flag group (\w+)\)):$")
_LINEA = re.compile(r"^\s+(?:-(\w), )?--([A-Za-z0-9][\w-]*)(?: (\S+))?(?:\s{2,}(.*))?$")
_DEFECTO = re.compile(r"\s\(default (\"[^\"]*\"|[^()]*)\)$")
_RUTA = r"(?:/|[A-Za-z]:[\\/])"
_VALOR_RUTA = re.compile(_RUTA)
_AYUDA_CON_RUTA = re.compile(rf"\s*\(default: {_RUTA}[^)]*\)")


def _entrada(linea: str) -> Entrada | None:
    """Devuelve el flag que describe una línea de una ayuda, o `None` si no es de un flag."""
    m = _LINEA.match(linea)
    if not m:
        return None
    corto, nombre, tipo, ayuda = m.group(1) or "", m.group(2), m.group(3) or "bool", m.group(4) or ""
    ayuda = ayuda.strip()
    defecto = ""
    hallado = _DEFECTO.search(ayuda)
    if hallado:
        defecto = hallado.group(1).strip('"')
        ayuda = ayuda[:hallado.start()].rstrip()
    # Una ruta depende de quién corra rclone (`--config`, `--cache-dir`, `--temp-dir`, el
    # `--workdir` de bisync: su HOME y su sistema): no es un dato de rclone y haría que el
    # fichero cambiara con cada equipo que lo regenere.
    if _VALOR_RUTA.match(defecto):
        defecto = ""
    ayuda = _AYUDA_CON_RUTA.sub("", ayuda)
    return Entrada(nombre, corto, tipo, defecto, ayuda)


def leer_secciones(texto: str) -> list[tuple[str, list[Entrada]]]:
    """Devuelve las secciones de flags de una ayuda de rclone, en el orden en que salen.

    Args:
        texto: La salida de `rclone help flags` o de `rclone <orden> --help`.

    Returns:
        `(sección, flags)`: la sección es `LOCAL` para el `Flags:` de la propia
        orden y el nombre del grupo (`Copy`, `Sync`…) para las demás.
    """
    secciones: list[tuple[str, list[Entrada]]] = []
    actual: list[Entrada] | None = None
    for linea in texto.splitlines():
        m = _ENCABEZADO.match(linea)
        if m:
            actual = []
            secciones.append((LOCAL if m.group(1) else m.group(2), actual))
        elif not linea.strip() or not linea[0].isspace():
            actual = None                      # otra cosa que no es un flag: acaba la sección
        elif actual is not None:
            entrada = _entrada(linea)
            if entrada:
                actual.append(entrada)
    return secciones


def construir(version: str, ayuda_flags: str, ayudas_ordenes: dict[str, str],
              duraciones_go: frozenset[str] | set[str] = frozenset()) -> dict:
    """Monta los datos de los flags a partir de las ayudas de rclone.

    Args:
        version: La versión de rclone de la que salen (`v1.75.2`).
        ayuda_flags: La salida de `rclone help flags`.
        ayudas_ordenes: La salida de `rclone <orden> --help`, por orden (`VERBOS`).
        duraciones_go: Los flags `Duration` que usan la duración de Go y no la de
            rclone (`sondear_duraciones()`): la ayuda dice `Duration` de los dos.

    Returns:
        `{"rclone": versión, "flags": {nombre: {...}}, "cortos": {letra: {...}}}`,
        con los flags y las letras ordenados. De cada flag: `corto`, `tipo`,
        `defecto`, `ayuda`, `grupo`, `propio` (si es de la orden y no global: fuera
        de ella rclone se queja de que no existe) y `comandos` (las órdenes de
        `VERBOS` donde existe: las tres si es global); los de `duraciones_go` llevan
        además `formato: "go"`. De cada letra (`cortos()`): `flag` y `valor`. Y
        `con_valor_fuera`: los nombres, ordenados, de los flags de `GRUPOS_FUERA`
        que se comen un valor.

    Raises:
        ErrorDeAyuda: Si la ayuda no trae ningún flag (rclone ha cambiado el formato)
            o una letra es de dos flags.
    """
    globales: dict[str, tuple[str, Entrada]] = {}
    fuera: set[str] = set()
    for seccion, entradas in leer_secciones(ayuda_flags):
        if seccion in GRUPOS_FUERA:
            fuera.update(e.nombre for e in entradas if e.tipo not in TIPOS_SIN_VALOR)
            continue
        if seccion == LOCAL:
            continue                             # el `Flags:` de `help flags` es de esa orden
        for e in entradas:
            globales.setdefault(e.nombre, (seccion, e))
    if not globales:
        raise ErrorDeAyuda("`rclone help flags` no trae ningún flag que leer: ¿ha cambiado "
                           "el formato de la ayuda?")

    propios: dict[str, tuple[Entrada, list[str]]] = {}
    for verbo in VERBOS:
        for seccion, entradas in leer_secciones(ayudas_ordenes.get(verbo, "")):
            if seccion != LOCAL:
                continue                         # los grupos globales no dicen dónde sirven
            for e in entradas:
                if e.nombre != "help":
                    propios.setdefault(e.nombre, (e, []))[1].append(verbo)

    flags: dict[str, dict] = {}
    for nombre, (grupo, e) in globales.items():
        flags[nombre] = _registro(e, grupo, False, list(VERBOS))
    for nombre, (e, verbos) in propios.items():
        if nombre not in flags:
            flags[nombre] = _registro(e, LOCAL, True, [v for v in VERBOS if v in verbos])
    for nombre in duraciones_go:
        if flags.get(nombre, {}).get("tipo") == "Duration":
            flags[nombre]["formato"] = "go"
    return {"rclone": version, "flags": dict(sorted(flags.items())),
            "cortos": cortos(ayuda_flags, ayudas_ordenes),
            "con_valor_fuera": sorted(fuera - set(flags))}


def cortos(ayuda_flags: str, ayudas_ordenes: dict[str, str]) -> dict[str, dict]:
    """Devuelve las letras que rclone acepta en `sync`, `copy` o `bisync`, y de qué flag son.

    Salen de todas las secciones de las ayudas, también de las que `construir()`
    deja fuera (el backend): rclone las acepta igual. El `Flags:` propio de `help
    flags` es de esa orden y no entra, ni el `-h` de cada una.

    Args:
        ayuda_flags: La salida de `rclone help flags`.
        ayudas_ordenes: La salida de `rclone <orden> --help`, por orden (`VERBOS`).

    Returns:
        `{letra: {"flag": nombre largo, "valor": si se come un valor}}`, por orden
        de letra. Una letra con valor se queda con el resto del argumento o con el
        siguiente (`TIPOS_SIN_VALOR`).

    Raises:
        ErrorDeAyuda: Si una letra es de dos flags distintos: no se sabría cuál lee rclone.
    """
    secciones = [(s, e) for s, e in leer_secciones(ayuda_flags) if s != LOCAL]
    for verbo in VERBOS:
        secciones += leer_secciones(ayudas_ordenes.get(verbo, ""))
    letras: dict[str, dict] = {}
    for _seccion, entradas in secciones:
        for e in entradas:
            if not e.corto or e.nombre == "help":
                continue
            registro = {"flag": e.nombre, "valor": e.tipo not in TIPOS_SIN_VALOR}
            if letras.setdefault(e.corto, registro)["flag"] != e.nombre:
                raise ErrorDeAyuda(f"La letra -{e.corto} es de --{letras[e.corto]['flag']} y "
                                   f"de --{e.nombre}: no se sabe cuál lee rclone.")
    return dict(sorted(letras.items()))


def sondear_duraciones(datos: dict, acepta) -> set[str]:
    """Devuelve qué flags `Duration` son de Go, preguntando a rclone con un valor de rclone.

    La ayuda llama `Duration` a dos cosas: `fs.Duration` (`30`, `1d`, `off`:
    `--max-lock`, `--stats`, `--min-age`, `--max-age`, `--log-file-max-age`) y la
    `time.Duration` de Go (`30s`, y un número a secas no vale: `--timeout`,
    `--modify-window`, `--max-duration`…). `1d` solo lo entiende la primera.

    Args:
        datos: Lo que da `construir()`.
        acepta: `acepta(flag, valor) -> bool`: si rclone da por bueno ese valor.
    """
    return {n for n, f in datos["flags"].items()
            if f["tipo"] == "Duration" and not acepta(n, "1d")}


def _registro(e: Entrada, grupo: str, propio: bool, comandos: list[str]) -> dict:
    """Devuelve el registro de un flag tal como va al fichero de datos."""
    return {"corto": e.corto, "tipo": e.tipo, "defecto": e.defecto, "ayuda": e.ayuda,
            "grupo": grupo, "propio": propio, "comandos": sorted(comandos)}


def a_texto(datos: dict) -> str:
    """Devuelve el fichero de datos como texto: un flag por línea, siempre igual.

    Un flag por línea hace que lo que cambia de una rclone a otra se vea en el
    diff de la PR; ni fecha ni nada que dependa de quién lo regenera.
    """
    def bloque(tabla: dict) -> str:
        return ",\n".join("    " + json.dumps(n, ensure_ascii=False) + ": "
                          + json.dumps(f, ensure_ascii=False) for n, f in tabla.items())
    nombres = ",\n".join("    " + json.dumps(n) for n in datos["con_valor_fuera"])
    return ('{\n  "rclone": ' + json.dumps(datos["rclone"]) + ',\n  "flags": {\n'
            + bloque(datos["flags"]) + '\n  },\n  "cortos": {\n' + bloque(datos["cortos"])
            + '\n  },\n  "con_valor_fuera": [\n' + nombres + "\n  ]\n}\n")


def leer_texto(texto: str) -> dict:
    """Devuelve los datos de un fichero escrito por `a_texto()`."""
    return json.loads(texto)


def comprobar_version(salida: str, fijada: str) -> None:
    """Se asegura de que `rclone version` dice la versión fijada.

    Raises:
        ErrorDeAyuda: Si es otra: los flags de una rclone distinta no son los que
            llevará el dispositivo.
    """
    m = re.match(r"rclone (v\S+)", salida.strip())
    if not m or m.group(1) != fijada:
        dice = m.group(1) if m else (salida.strip().splitlines() or ["nada"])[0]
        raise ErrorDeAyuda(f"Este rclone es {dice} y el fijado en common/pins.py es {fijada}.")


def _ejecutar(rclone: Path, *args: str) -> str:
    """Devuelve lo que escribe `rclone <args>` (salida y error juntos, como la ayuda)."""
    p = subprocess.run([str(rclone), *args], capture_output=True, text=True, encoding="utf-8",
                       stdin=subprocess.DEVNULL, timeout=60)
    if p.returncode != 0:
        raise ErrorDeAyuda(f"`rclone {' '.join(args)}` ha salido con {p.returncode}: "
                           f"{(p.stderr or p.stdout).strip()[:300]}")
    return p.stdout + p.stderr


def _acepta_con(rclone: Path, datos: dict):
    """Devuelve `acepta(flag, valor)` para `sondear_duraciones()`: pregunta al rclone de verdad.

    Un flag global se prueba con `rclone version`; uno propio de una orden,
    con esa orden y dos carpetas que no existen: rclone lee el valor de los flags
    antes de mirar nada más, y solo un valor malo da `invalid argument`.
    """
    def acepta(flag: str, valor: str) -> bool:
        orden = ("bisync", "x", "y") if datos["flags"][flag]["propio"] else ("version",)
        p = subprocess.run([str(rclone), *orden, f"--{flag}", valor], capture_output=True,
                           text=True, encoding="utf-8", stdin=subprocess.DEVNULL, timeout=60)
        salida = p.stdout + p.stderr
        return not any(m in salida for m in ("invalid argument", "unknown flag"))
    return acepta


def regenerar(rclone: Path, fijada: str) -> dict:
    """Corre ese rclone y devuelve los datos de sus flags.

    Raises:
        ErrorDeAyuda: Si no es la versión fijada o su ayuda no se entiende.
    """
    comprobar_version(_ejecutar(rclone, "version"), fijada)
    ayuda = _ejecutar(rclone, "help", "flags")
    ordenes = {v: _ejecutar(rclone, v, "--help") for v in VERBOS}
    datos = construir(fijada, ayuda, ordenes)
    return construir(fijada, ayuda, ordenes,
                     sondear_duraciones(datos, _acepta_con(rclone, datos)))


def _rclone_fijado() -> Path:
    """Devuelve el rclone fijado de este equipo: la caché del instalador o su descarga."""
    sys.path.insert(0, str(REPO))
    from install import platforms, rclone_bin

    plat = platforms.host()
    if plat is None:
        raise ErrorDeAyuda("Este equipo no es una plataforma de prdrive: usa --rclone.")
    return rclone_bin.pinned_rclone(plat, progreso=print)


def main(argv: list[str] | None = None) -> int:
    """Regenera el fichero de datos. Devuelve el código de salida."""
    sys.path.insert(0, str(REPO))
    from common import pins

    parser = argparse.ArgumentParser(description="Regenera common/flags_rclone.json "
                                                 "desde la rclone fijada en common/pins.py.")
    parser.add_argument("--rclone", type=Path, help="el binario de rclone; tiene que ser la "
                                                    "versión fijada (por defecto, el del instalador)")
    parser.add_argument("--salida", type=Path, default=SALIDA, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        datos = regenerar(args.rclone or _rclone_fijado(), pins.RCLONE_VERSION)
    except (ErrorDeAyuda, OSError, subprocess.SubprocessError) as e:
        print(f"No he podido regenerar los flags: {e}", file=sys.stderr)
        return 1
    texto = a_texto(datos)
    antes = args.salida.read_text(encoding="utf-8") if args.salida.exists() else ""
    args.salida.write_text(texto, encoding="utf-8", newline="\n")
    print(f"{args.salida}: {len(datos['flags'])} flags de rclone {datos['rclone']}"
          + ("" if texto != antes else " (sin cambios)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
