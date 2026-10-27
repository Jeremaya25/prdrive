#!/usr/bin/env python3
"""Añade a `common/keepassxc_arbol.json` el árbol del ZIP oficial de KeePassXC de una versión.

Es la tabla con la que `keepassxc.comprobar()` mira, antes de lanzar nada de la
unidad, que la carpeta del paquete de Windows no tenga un fichero de más, de
menos o con otro tamaño (`components.keepassxc_arbol_no_cuadra()`). Hay que
correrlo cada vez que se mueve `pins.KEEPASSXC_VERSION`, después de añadir su
fila a `pins.KEEPASSXC_EJECUTABLES` (`tests/test_keepassxc_pin.py` falla si la
versión fijada no tiene árbol):

    python generar_arbol_keepassxc.py
        # el ZIP fijado (`pins.KEEPASSXC["windows-x64"]`), de la caché del
        # instalador o bajado, comprobado contra su SHA-256
    python generar_arbol_keepassxc.py --zip RUTA --version V --sha256 S
        # ese ZIP, que tiene que dar esa suma: para la fila de una versión que
        # ya no es la fijada

Por cada fichero de `keepassxc_bin.miembros()` (sin la carpeta de arriba, con
`/`) apunta `[tamaño, sha256]`. Antes de escribir nada comprueba que los
ejecutables den las sumas de `pins.KEEPASSXC_EJECUTABLES[V]["windows-x64"]`:
la tabla del árbol no puede decir otra cosa que la de los pines. La versión se
AÑADE sin quitar las otras: un dispositivo con el código ya actualizado y el
KeePassXC todavía no sigue abriendo el suyo. La salida es JSON ordenado y
estable: correrlo dos veces da el mismo fichero.

Solo biblioteca estándar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
"""La raíz del proyecto."""

SALIDA = REPO / "common" / "keepassxc_arbol.json"
"""El fichero de datos que se escribe (`components.KEEPASSXC_ARBOL`)."""

PAQUETE = "windows-x64"
"""El paquete del que se apunta el árbol: el único que se ejecuta desde la unidad."""


class ErrorDeArbol(Exception):
    """El ZIP o la tabla no son lo que se esperaba: no se escribe nada."""


def _resumen(ruta: Path) -> str:
    """Devuelve el SHA-256 de un fichero, leyéndolo a trozos."""
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for trozo in iter(lambda: f.read(1024 * 1024), b""):
            h.update(trozo)
    return h.hexdigest()


def arbol_del_zip(zip_: Path) -> dict[str, list]:
    """Devuelve `{ruta: [tamaño, sha256]}` de cada fichero del ZIP, sin su carpeta de arriba.

    Raises:
        ErrorDeArbol: Si el ZIP no se puede leer, no tiene la forma del oficial
            (`keepassxc_bin.miembros()`) o trae dos rutas que solo se distinguen
            en mayúsculas (Windows las vería como una).
    """
    from install import InstallError, keepassxc_bin

    arbol: dict[str, list] = {}
    try:
        with zipfile.ZipFile(zip_) as zf:
            for info, rel in keepassxc_bin.miembros(zf):
                h = hashlib.sha256()
                tamano = 0
                with zf.open(info) as f:
                    for trozo in iter(lambda: f.read(1024 * 1024), b""):
                        h.update(trozo)
                        tamano += len(trozo)
                arbol[rel] = [tamano, h.hexdigest()]
    except (OSError, zipfile.BadZipFile, InstallError) as e:
        raise ErrorDeArbol(f"No he podido leer {zip_}: {e}") from e
    if len({rel.casefold() for rel in arbol}) != len(arbol):
        raise ErrorDeArbol(f"{zip_} trae rutas que solo se distinguen en mayúsculas.")
    return arbol


def comprobar_ejecutables(arbol: dict[str, list], version: str) -> None:
    """Comprueba que los ejecutables del árbol den las sumas de `pins.KEEPASSXC_EJECUTABLES`.

    Raises:
        ErrorDeArbol: Si la versión no tiene fila de Windows en la tabla, si un
            ejecutable falta en el ZIP o si su suma es otra.
    """
    from common import pins

    fijados = pins.KEEPASSXC_EJECUTABLES.get(version, {}).get(PAQUETE)
    if not fijados:
        raise ErrorDeArbol(f"pins.KEEPASSXC_EJECUTABLES no tiene {PAQUETE} de la versión "
                           f"{version}: añádelo antes.")
    for nombre, suma in sorted(fijados.items()):
        if nombre not in arbol:
            raise ErrorDeArbol(f"El ZIP no trae {nombre}, que pins.KEEPASSXC_EJECUTABLES fija.")
        if arbol[nombre][1] != suma:
            raise ErrorDeArbol(f"{nombre} del ZIP no da la suma de pins.KEEPASSXC_EJECUTABLES"
                               f"[{version!r}]:\n  fijada:  {suma}\n  del ZIP: {arbol[nombre][1]}")


def leer(salida: Path) -> dict:
    """Devuelve la tabla que ya hay, o `{}` si no hay fichero.

    Raises:
        ErrorDeArbol: Si hay fichero y no se entiende: no se pisa a ciegas.
    """
    if not salida.exists():
        return {}
    try:
        datos = json.loads(salida.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ErrorDeArbol(f"No entiendo {salida}: {e}") from e
    if not isinstance(datos, dict) or not all(isinstance(v, dict) for v in datos.values()):
        raise ErrorDeArbol(f"{salida} no es una tabla {{versión: {{paquete: …}}}}.")
    return datos


def a_texto(datos: dict) -> str:
    """Devuelve la tabla como JSON ordenado y estable, un fichero por línea."""
    lineas = ["{"]
    versiones = sorted(datos)
    for i, version in enumerate(versiones):
        lineas.append(f"  {json.dumps(version)}: {{")
        paquetes = sorted(datos[version])
        for j, paquete in enumerate(paquetes):
            lineas.append(f"    {json.dumps(paquete)}: {{")
            ficheros = sorted(datos[version][paquete])
            for k, ruta in enumerate(ficheros):
                tamano, suma = datos[version][paquete][ruta]
                coma = "," if k < len(ficheros) - 1 else ""
                lineas.append(f"      {json.dumps(ruta, ensure_ascii=False)}: "
                              f"[{int(tamano)}, {json.dumps(suma)}]{coma}")
            lineas.append("    }" + ("," if j < len(paquetes) - 1 else ""))
        lineas.append("  }" + ("," if i < len(versiones) - 1 else ""))
    lineas.append("}")
    return "\n".join(lineas) + "\n"


def _zip_fijado() -> Path:
    """Devuelve el ZIP fijado: el de la caché del instalador o su descarga, comprobado."""
    from install import keepassxc_bin

    return keepassxc_bin.ensure_zip(PAQUETE, progreso=print)


def main(argv: list[str] | None = None) -> int:
    """Añade la fila de la versión al fichero de datos. Devuelve el código de salida."""
    sys.path.insert(0, str(REPO))
    from common import pins
    from install import InstallError

    parser = argparse.ArgumentParser(description="Añade a common/keepassxc_arbol.json el árbol "
                                                 "del ZIP oficial de KeePassXC.")
    parser.add_argument("--zip", type=Path, help="el ZIP oficial de Windows (por defecto, el "
                                                 "fijado en common/pins.py)")
    parser.add_argument("--version", help="su versión (obligatoria con --zip)")
    parser.add_argument("--sha256", help="su SHA-256, el del pin (obligatorio con --zip)")
    parser.add_argument("--salida", type=Path, default=SALIDA, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.zip is None and (args.version or args.sha256):
        parser.error("--version y --sha256 van con --zip")
    if args.zip is not None and not (args.version and args.sha256):
        parser.error("con --zip hacen falta --version y --sha256")
    try:
        if args.zip is None:
            version, zip_ = pins.KEEPASSXC_VERSION, _zip_fijado()
        else:
            version, zip_ = args.version, args.zip
            obtenida = _resumen(zip_)
            if obtenida != args.sha256.strip().lower():
                raise ErrorDeArbol(f"{zip_} no da ese SHA-256:\n  pedido:   {args.sha256}\n"
                                   f"  obtenido: {obtenida}")
        arbol = arbol_del_zip(zip_)
        comprobar_ejecutables(arbol, version)
        datos = leer(args.salida)
        datos.setdefault(version, {})[PAQUETE] = arbol
        texto = a_texto(datos)
        antes = args.salida.read_text(encoding="utf-8") if args.salida.exists() else ""
        args.salida.write_text(texto, encoding="utf-8", newline="\n")
    except (ErrorDeArbol, InstallError, OSError) as e:
        print(f"No he podido generar el árbol de KeePassXC: {e}", file=sys.stderr)
        return 1
    print(f"{args.salida}: {len(arbol)} ficheros de KeePassXC {version} ({PAQUETE})"
          + ("" if texto != antes else " (sin cambios)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
