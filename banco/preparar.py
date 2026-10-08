"""Prepara una máquina para el banco de la interfaz (temporal, ver `banco/LEEME.md`).

Baja el runtime fijado de esta plataforma con el propio instalador
(`install/runtime_bin.py`, comprobado contra su SHA256SUMS, con el Tk con Xft en
Linux), saca el árbol de la 0.6.5 (`git archive`), baja y poda Qt
(`banco/qt/traer_qt.py`) y escribe el `banco.json` que leen las rondas. Corre
con cualquier Python 3.11+ (en la nube, el de `setup-python`).

Uso: python banco/preparar.py --plataforma windows-x64 --trabajo DIR
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VERSION_065 = "fc7982d"
"""El merge de la PR #86: lo último antes del rediseño de la 0.7.0 (VERSION 0.6.5)."""


def runtime(clave: str, trabajo: Path) -> Path:
    """Baja, comprueba y extrae el runtime fijado; devuelve su intérprete de consola."""
    sys.path.insert(0, str(REPO))
    os.environ.setdefault("LOCALAPPDATA", str(trabajo / "cache"))
    from common import pins
    from install import runtime_bin
    plat = pins.plataforma(clave)
    archivo = runtime_bin.ensure_runtime(plat, lambda m: print(f"    {m}", flush=True))
    sha = runtime_bin.recorded_sha256(archivo) or runtime_bin.file_sha256(archivo)
    destino = trabajo / f"runtime-{clave}"
    runtime_bin.extract(archivo, destino, plat, sha)
    return destino / plat.interprete_consola


def arbol_065(trabajo: Path) -> Path:
    """Saca el árbol de la 0.6.5 del historial del repositorio."""
    destino = trabajo / "src-065"
    datos = subprocess.run(["git", "-C", str(REPO), "archive", "--format=zip", VERSION_065],
                           check=True, capture_output=True).stdout
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
        z.extractall(destino)
    return destino


def qt(clave: str, trabajo: Path) -> str | None:
    """Baja y poda PySide6 para esta plataforma; None si no se puede."""
    destino = trabajo / "qt"
    r = subprocess.run([sys.executable, str(REPO / "banco" / "qt" / "traer_qt.py"), clave,
                        str(destino)])
    return str(destino) if r.returncode == 0 else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plataforma", required=True)
    ap.add_argument("--trabajo", required=True)
    ap.add_argument("--rondas", type=int, default=7)
    a = ap.parse_args()
    trabajo = Path(a.trabajo).resolve()
    trabajo.mkdir(parents=True, exist_ok=True)

    print("== runtime", flush=True)
    python = runtime(a.plataforma, trabajo)
    print("== 0.6.5", flush=True)
    src065 = arbol_065(trabajo)
    print("== Qt", flush=True)
    dir_qt = qt(a.plataforma, trabajo)

    conf = {"python": str(python), "src071": str(REPO), "src065": str(src065),
            "qt": dir_qt, "trabajo": str(trabajo / "w"), "plataforma": a.plataforma,
            "rondas": a.rondas}
    Path(conf["trabajo"]).mkdir(parents=True, exist_ok=True)
    ruta = trabajo / "banco.json"
    ruta.write_text(json.dumps(conf, indent=1), encoding="utf-8")
    print(json.dumps(conf, indent=1))
    if os.environ.get("GITHUB_ENV"):
        with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as f:
            f.write(f"BANCO_CONF={ruta}\n")
    v = subprocess.run([str(python), "-c", "import sys, tkinter; print(sys.version); "
                        "print('Tk', tkinter.Tcl().eval('info patchlevel'))"],
                       capture_output=True, text=True)
    print(v.stdout.strip() or v.stderr.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
