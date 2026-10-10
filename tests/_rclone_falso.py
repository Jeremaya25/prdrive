#!/usr/bin/env python3
"""Un «rclone» de mentira que es un proceso de verdad.

`catalog.run()` lanza `[binario, --config, conf, *NET_FLAGS, *args]` y cuelga
de lo que haga ese proceso: cuánto tarda, cómo sale, a quién mata el sistema
con él. Sustituir `run()` entera no prueba nada de eso, y sustituir solo
`catalog._binary()` por un script exige un ejecutable que ignore los flags de
rclone, que `python` no ignora. Este es un script de `sh` que hace `exec` del
intérprete: el proceso que ve `catalog.run()` es el propio Python, sin una capa
intermedia que se quede viva al matarlo.

Qué hace lo decide `$PRDRIVE_FALSO_MODO`, que hereda del proceso que lo lanza:
- `dormir`: apunta su pid en `$PRDRIVE_FALSO_PID` y espera a que exista el
  fichero `$PRDRIVE_FALSO_PARAR` (o se le acabe el minuto); entonces sale con 0.
- `eco` (el de por defecto): escribe en la salida su orden y su carpeta en
  JSON, algo en el error y sale con 3.

Solo en POSIX: en Windows el ejecutable tendría que ser un `.cmd`, y matar al
`cmd.exe` deja al Python vivo con las tuberías abiertas.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

DISPONIBLE = os.name != "nt"
"""Si este sistema sabe hacer el ejecutable de mentira."""

PROGRAMA = '''\
import json, os, pathlib, sys, time
if os.environ.get("PRDRIVE_FALSO_MODO") == "dormir":
    pathlib.Path(os.environ["PRDRIVE_FALSO_PID"]).write_text(str(os.getpid()))
    parar = pathlib.Path(os.environ["PRDRIVE_FALSO_PARAR"])
    limite = time.monotonic() + 60
    while not parar.exists() and time.monotonic() < limite:
        time.sleep(0.05)
    sys.exit(0)
print(json.dumps({"orden": sys.argv, "cwd": os.getcwd()}))
print("fallo de mentira", file=sys.stderr)
sys.exit(3)
'''
"""El programa de Python del rclone de mentira."""


def crear(carpeta: Path) -> str:
    """Escribe el rclone de mentira en `carpeta`.

    Args:
        carpeta: Donde se deja (su `rclone-falso` y su `rclone-falso.py`).

    Returns:
        La ruta del ejecutable, lista para ponerla como `catalog._binary()`.
    """
    programa = carpeta / "rclone-falso.py"
    programa.write_text(PROGRAMA, encoding="utf-8")
    ejecutable = carpeta / "rclone-falso"
    ejecutable.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{programa}" "$@"\n',
                          encoding="utf-8")
    ejecutable.chmod(ejecutable.stat().st_mode | stat.S_IXUSR)
    return str(ejecutable)
