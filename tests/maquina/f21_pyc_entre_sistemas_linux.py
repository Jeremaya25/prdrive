"""F21 (Linux): los `.pyc` de hash comprobado del programa, preparados con el Python fijado.

Es la mitad de Linux de la prueba de `.pyc` entre sistemas (la de Windows,
`f21_pyc_entre_sistemas_windows.py`, la lee). Con el Python que deja
`tests/_runtime_ci.py runtime` (`PRDRIVE_PYTHON`) precompila una copia de
`common/`, `ui/` y `penwatch.py` con `install.deploy.precompilar()`, igual que el
instalador en el dispositivo, y deja en `$F21_ARBOL`:

- `.prdrive/`: el árbol con sus `.pyc` de hash comprobado (bandera 0b11) y
  `control_marca_tiempo.py`, un fuente de hora impar compilado con `.pyc` de hora;
- `manifiesto.json`: cada `.pyc` con su fuente, su bandera, su hash de fuente y su
  SHA-256.

No despliega nada: ni rclone, ni configuración, ni dispositivo.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

import comun

CODIGO = "F21"
SISTEMA = "L"
QUE = "los .pyc de hash comprobado del programa, con el Python fijado (la mitad de Linux)"

ETIQUETA = "cpython-314"
"""La etiqueta de los `.pyc` del Python fijado (`sys.implementation.cache_tag`)."""

CONTROL = "control_marca_tiempo.py"
"""Fuente de control: su hora es impar y su `.pyc` es de hora, que cambia entre sistemas."""

CONTROL_TEXTO = '"""Control de F21: un fuente con hora impar, compilado con .pyc de hora."""\nVALOR = 1\n'

SONDA = "import sys; print('%d.%d.%d' % sys.version_info[:3], sys.implementation.cache_tag)"

COMPILAR_HORA = ("import py_compile, sys; py_compile.compile(sys.argv[1], doraise=True, "
                 "invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)")


def _entrada(app: Path, pyc: Path) -> dict:
    """Lo que la mitad de Windows necesita de un `.pyc`: de qué fuente sale y cómo se valida.

    Args:
        app: La carpeta `.prdrive/` precompilada.
        pyc: Un `.pyc` de `app` con la etiqueta de `ETIQUETA`.

    Returns:
        `modulo` (nombre con puntos), `fuente` y `pyc` (relativos a `app`, con `/`),
        `bandera` (la de la cabecera), `hash_fuente` (solo si es de hash), `sha256`
        del `.pyc` y su tamaño.
    """
    cab = pyc.read_bytes()[:16]
    bandera = int.from_bytes(cab[4:8], "little")
    fuente = pyc.parent.parent / pyc.name.replace(f".{ETIQUETA}.pyc", ".py")
    rel = fuente.relative_to(app).as_posix()
    partes = rel[:-len(".py")].split("/")
    if partes[-1] == "__init__":
        partes.pop()
    return {
        "modulo": ".".join(partes),
        "fuente": rel,
        "pyc": pyc.relative_to(app).as_posix(),
        "bandera": bandera,
        "hash_fuente": cab[8:16].hex() if bandera & 1 else None,
        "sha256": hashlib.sha256(pyc.read_bytes()).hexdigest(),
        "tamano": pyc.stat().st_size,
    }


def probar(p: comun.Prueba) -> None:
    """Precompila la copia con el Python fijado y deja el árbol y su manifiesto en `$F21_ARBOL`.

    Raises:
        Saltada: Si no hay `F21_ARBOL` (la corre el trabajo `pyc-linux`) o no hay
            Python fijado en `PRDRIVE_PYTHON`.
    """
    from common import pins
    from install import deploy

    arbol = os.environ.get("F21_ARBOL", "")
    if not arbol:
        raise comun.Saltada("F21 corre en su trabajo propio (pyc-linux): falta F21_ARBOL")
    python = os.environ.get("PRDRIVE_PYTHON", "")
    if not Path(python).is_file():
        raise comun.Saltada("no hay Python fijado (PRDRIVE_PYTHON: tests/_runtime_ci.py runtime)")

    r = comun.ejecutar([python, "-I", "-c", SONDA], timeout=60)
    p.ver("el intérprete arranca", r.returncode, 0)
    if r.returncode != 0:
        return
    p.ver("es el Python fijado (versión y etiqueta de .pyc)", r.stdout.split(),
          [pins.PYTHON_VERSION, ETIQUETA])
    version = pins.PYTHON_VERSION

    raiz = Path(arbol)
    app = raiz / ".prdrive"
    shutil.rmtree(app, ignore_errors=True)
    app.mkdir(parents=True)
    ignorar = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
    for nombre in ("common", "ui"):
        shutil.copytree(comun.REPO / nombre, app / nombre, ignore=ignorar)
    shutil.copy2(comun.REPO / "penwatch.py", app / "penwatch.py")

    p.ver("precompilar deja los .pyc del programa (install.deploy.precompilar)",
          deploy.precompilar(app, python, biblioteca=False), True)
    for nombre in ("common", "ui"):
        n = len(list((app / nombre).rglob(f"*.{ETIQUETA}.pyc")))
        p.ver(f"{nombre}/ tiene sus .pyc de {ETIQUETA}", n > 0, True)

    fuente = app / CONTROL
    fuente.write_text(CONTROL_TEXTO, encoding="utf-8")
    impar = int(time.time()) | 1
    os.utime(fuente, (impar, impar))
    r = comun.ejecutar([python, "-I", "-c", COMPILAR_HORA, str(fuente)], timeout=60)
    p.ver("el control se compila con .pyc de hora", r.returncode, 0)
    pyc_control = app / "__pycache__" / f"control_marca_tiempo.{ETIQUETA}.pyc"
    p.ver("la hora del control es impar", int(fuente.stat().st_mtime) % 2, 1)
    p.ver("y su .pyc es de hora (bandera 0)",
          int.from_bytes(pyc_control.read_bytes()[4:8], "little"), 0)

    entradas = [_entrada(app, pyc) for pyc in sorted(app.rglob(f"*.{ETIQUETA}.pyc"))]
    sin_hash = [e["fuente"] for e in entradas if e["fuente"] != CONTROL and e["bandera"] != 0b11]
    p.ver("los .pyc del programa son de hash comprobado (bandera 0b11)", sin_hash, [])
    p.nota(f"{len(entradas) - 1} .pyc de hash comprobado (y el de control)")

    manifiesto = {"etiqueta": ETIQUETA, "version": version, "entradas": entradas}
    (raiz / "manifiesto.json").write_text(json.dumps(manifiesto, indent=1), encoding="utf-8")
