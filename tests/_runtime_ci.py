#!/usr/bin/env python3
"""Deja el Python fijado del dispositivo listo para la CI: la suite y los tiempos.

Lo usan `.github/workflows/tests.yml` (la pata con Tk 9) y
`.github/workflows/rendimiento.yml`: los dos necesitan el MISMO Python y el MISMO
Tk que lleva un dispositivo, y no el de `setup-python` (Tk 8.6). Lo baja y lo
abre el propio instalador (`install/runtime_bin.py`, comprobado contra el
SHA256SUMS de la release fijada en `common/pins.py`), igual que
`tests/maquina/f20_tk9_windows.py`. Va en un paso previo del workflow y no dentro
de un test porque la suite no toca la red. No es un test (`run_all.py` solo
recoge `test_*.py`). Solo biblioteca estándar.

    python tests/_runtime_ci.py clave
    python tests/_runtime_ci.py runtime PLATAFORMA DESTINO CACHE

`clave` escribe la clave de la caché de Actions (la release de Python y el
paquete del Tk con Xft que fija `common/pins.py`). `runtime` deja el runtime
extraído en DESTINO, usando CACHE como caché de descargas, y escribe la ruta de
su intérprete de consola. En Actions, además, las dos órdenes la dejan donde lo
lee el resto del trabajo: `clave` en `$GITHUB_OUTPUT` y `runtime` en
`$GITHUB_ENV` como `PRDRIVE_PYTHON`, sin pasar por el intérprete de órdenes
del paso (que en Windows con bash cambia las barras).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _anotar(variable: str, nombre: str, valor: str) -> None:
    """Añade `nombre=valor` al fichero que Actions lee en `$variable`, si existe."""
    ruta = os.environ.get(variable)
    if ruta:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(f"{nombre}={valor}\n")


def clave() -> int:
    """Escribe la clave de la caché: cambia cuando cambia lo que se descarga."""
    from common import pins

    valor = f"{pins.PYTHON_RELEASE}-{pins.PYTHON_VERSION}-{pins.TK_XFT_TAG}"
    print(valor)
    _anotar("GITHUB_OUTPUT", "clave", valor)
    return 0


def runtime(plataforma: str, destino: Path, cache: Path) -> int:
    """Baja (o toma de la caché), comprueba y extrae el runtime de esa plataforma.

    Una suma apuntada junto a un archivo de la caché no prueba nada, porque se
    restauró con él: se borran las sumas y `runtime_bin.adoptar()` vuelve a
    comparar el archivo con el SHA256SUMS publicado. El paquete del Tk con Xft
    se compara siempre con el SHA-256 de `common/pins.py`. Si la caché no
    cuadra se tira y se baja de nuevo, una vez: lo que se usa sale siempre de
    una descarga comprobada.

    Args:
        plataforma: Clave de `pins.PLATAFORMAS` (`linux-x64`, `windows-x64`).
        destino: Carpeta donde se extrae el runtime.
        cache: Carpeta de descargas, la que Actions guarda entre ejecuciones.

    Returns:
        0 si el runtime queda comprobado y con el Tk fijado; 1 si no.
    """
    # `runtime_bin.cache_dir()` lee LOCALAPPDATA en cada llamada, en Windows y
    # en Linux: así la caché cae en una carpeta que Actions sabe guardar.
    os.environ["LOCALAPPDATA"] = str(cache)
    from common import pins
    from install import InstallError, runtime_bin

    def decir(mensaje: str) -> None:
        print(mensaje, file=sys.stderr, flush=True)

    plat = pins.plataforma(plataforma)
    try:
        for suma in Path(cache).rglob("*.sha256"):
            suma.unlink()
        archivo = runtime_bin.ensure_runtime(plat, decir)
    except (InstallError, OSError) as e:
        decir(f"La caché no vale ({e}); se descarga de nuevo")
        shutil.rmtree(cache, ignore_errors=True)
        try:
            archivo = runtime_bin.ensure_runtime(plat, decir)
        except InstallError as e2:
            print(e2, file=sys.stderr)
            return 1
    runtime_bin.extract(archivo, destino, plat, runtime_bin.file_sha256(archivo))

    python = destino / plat.interprete_consola
    if not python.is_file():
        print(f"No está {python}", file=sys.stderr)
        return 1
    if runtime_bin.lleva_tk(plat):
        # `ensure_tk()` no falla nunca: sin el paquete el runtime sigue con el
        # Tk de serie, y esta pata ya no probaría lo que lleva un dispositivo.
        xft = destino.joinpath(*runtime_bin.TK_DIR.split("/"), runtime_bin.TK_LIB)
        if not xft.is_file():
            print(f"Falta el Tk con Xft ({xft}): {runtime_bin.tk_url(plat)}", file=sys.stderr)
            return 1
    visto = subprocess.run(
        [str(python), "-c", "import tkinter; print(tkinter.Tcl().eval('info patchlevel'))"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip()
    if visto != pins.TK_XFT_VERSION:
        print(f"Tk {visto!r} en lugar de {pins.TK_XFT_VERSION}", file=sys.stderr)
        return 1
    print(python)
    _anotar("GITHUB_ENV", "PRDRIVE_PYTHON", str(python))
    return 0


def main(argv: list[str]) -> int:
    """Despacha `clave` o `runtime`."""
    if argv[1:] == ["clave"]:
        return clave()
    if len(argv) == 5 and argv[1] == "runtime":
        return runtime(argv[2], Path(argv[3]), Path(argv[4]))
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
