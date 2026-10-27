#!/usr/bin/env python3
"""El script que añade a `common/keepassxc_arbol.json` el árbol del ZIP oficial de KeePassXC.

Sin red y sin el ZIP de verdad: un ZIP de mentira con la forma del oficial (una
carpeta de arriba, los tres ejecutables y alguna DLL), pasado con `--zip`, y
las sumas de sus ejecutables puestas en `pins.KEEPASSXC_EJECUTABLES` para la
prueba. Lo que se sujeta:
- Aborta, sin escribir nada, si un ejecutable no da la suma de los pines, si la
  versión no tiene fila en ellos o si el ZIP no da el SHA-256 pedido.
- Añade una versión sin quitar las otras.
- Su salida es estable: dos veces, el mismo fichero, ordenado.
- Lo que escribe es lo que entiende `components.keepassxc_arbol()`, y una
  carpeta extraída de ese ZIP cuadra con él.
"""

import contextlib
import hashlib
import io
import json
import sys
import zipfile

from _harness import Checks, tmpdir

import generar_arbol_keepassxc as gen
from common import components, pins

c = Checks("añadir el árbol de KeePassXC (generar_arbol_keepassxc.py)")

ARRIBA = "KeePassXC-9.9.9-Win64/"
FICHEROS = {".portable": b"", "KeePassXC.exe": b"MZ el programa",
            "keepassxc-cli.exe": b"MZ la cli", "keepassxc-proxy.exe": b"MZ el proxy",
            "Qt5Core.dll": b"MZ qt", "plugins/imageformats/qjpeg.dll": b"MZ jpeg"}
EJECUTABLES = ("KeePassXC.exe", "keepassxc-cli.exe", "keepassxc-proxy.exe")


def suma(datos: bytes) -> str:
    """Devuelve el SHA-256 de esos bytes."""
    return hashlib.sha256(datos).hexdigest()


def hacer_zip(ficheros: dict[str, bytes]) -> bytes:
    """Devuelve un ZIP con esos ficheros dentro de la carpeta de arriba."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(ARRIBA, b"")
        for nombre, datos in ficheros.items():
            zf.writestr(ARRIBA + nombre, datos)
    return buf.getvalue()


def correr(*args: str) -> tuple[int, str]:
    """Corre el generador con esos argumentos; devuelve su código y lo que dijo por stderr."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        try:
            codigo = gen.main(list(args))
        except SystemExit as e:
            codigo = e.code
    return codigo, err.getvalue()


carpeta = tmpdir("prdrive-gen-arbol-")
zip_ = carpeta / "KeePassXC-9.9.9-Win64.zip"
datos_zip = hacer_zip(FICHEROS)
zip_.write_bytes(datos_zip)
salida = carpeta / "keepassxc_arbol.json"
OTRA = {"1.0.0": {"windows-x64": {"KeePassXC.exe": [3, "x" * 64]}}}
salida.write_text(json.dumps(OTRA), encoding="utf-8")
pines_reales = pins.KEEPASSXC_EJECUTABLES


def con_pines(**cambios: bytes) -> None:
    """Fija las sumas de los ejecutables de la 9.9.9, con los `cambios` por nombre."""
    pins.KEEPASSXC_EJECUTABLES = {"9.9.9": {"windows-x64": {
        n: suma(cambios.get(n, FICHEROS[n])) for n in EJECUTABLES}}}


ARGS = ("--zip", str(zip_), "--version", "9.9.9", "--sha256", suma(datos_zip),
        "--salida", str(salida))
try:
    for nombre in EJECUTABLES:
        con_pines(**{nombre: b"MZ otro"})
        codigo, dicho = correr(*ARGS)
        c(f"aborta si {nombre} no da la suma de los pines, y no escribe nada",
          (codigo, json.loads(salida.read_text(encoding="utf-8"))), (1, OTRA))
        c.contains("  y dice cuál", dicho, nombre)
    pins.KEEPASSXC_EJECUTABLES = {}
    codigo, dicho = correr(*ARGS)
    c("aborta si la versión no tiene fila en los pines", codigo, 1)
    c.contains("  y dice qué añadir antes", dicho, "KEEPASSXC_EJECUTABLES")
    con_pines()
    codigo, dicho = correr("--zip", str(zip_), "--version", "9.9.9", "--sha256", "0" * 64,
                           "--salida", str(salida))
    c("aborta si el ZIP no da el SHA-256 pedido",
      (codigo, json.loads(salida.read_text(encoding="utf-8"))), (1, OTRA))
    c.contains("  y lo dice", dicho, "no da ese SHA-256")
    codigo, _ = correr("--zip", str(zip_), "--salida", str(salida))
    c("con --zip hacen falta --version y --sha256", codigo, 2)

    codigo, dicho = correr(*ARGS)
    leido = json.loads(salida.read_text(encoding="utf-8"))
    c("con todo en regla, añade la versión", (codigo, dicho), (0, ""))
    c("  sin quitar la que había", leido.get("1.0.0"), OTRA["1.0.0"])
    c("  con cada fichero del ZIP sin la carpeta de arriba: [tamaño, sha256]",
      leido["9.9.9"]["windows-x64"],
      {n: [len(d), suma(d)] for n, d in FICHEROS.items()})
    primero = salida.read_bytes()
    correr(*ARGS)
    c("la salida es estable: correrlo otra vez da el mismo fichero", salida.read_bytes(), primero)
    c("  ordenada, un fichero por línea y con \\n",
      (list(leido) == sorted(leido), b"\r" not in primero,
       primero.count(b"\n"), primero.endswith(b"}\n")),
      (True, True, 1 + (4 + 1) + (4 + len(FICHEROS)) + 1, True))

    # lo escrito es lo que entiende comprobar(): una carpeta extraída de ese ZIP cuadra
    real_arbol, real_cache = components.KEEPASSXC_ARBOL, components._ARBOLES
    components.KEEPASSXC_ARBOL, components._ARBOLES = salida, None
    try:
        arbol = components.keepassxc_arbol("9.9.9", "windows-x64")
        c("components.keepassxc_arbol() lo lee", sorted(arbol or {}), sorted(FICHEROS))
        destino = carpeta / "extraido"
        with zipfile.ZipFile(io.BytesIO(datos_zip)) as zf:
            zf.extractall(destino)
        c("  y una carpeta extraída de ese ZIP cuadra con él",
          components.keepassxc_arbol_no_cuadra(destino / ARRIBA.rstrip("/"), arbol or {}), None)
        c("  la fila que no se entiende entera no vale",
          components.keepassxc_arbol("1.0.0", "windows-x64"), None)
    finally:
        components.KEEPASSXC_ARBOL, components._ARBOLES = real_arbol, real_cache
finally:
    pins.KEEPASSXC_EJECUTABLES = pines_reales

sys.exit(c.report())
