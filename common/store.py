#!/usr/bin/env python3
"""
store.py — Los ficheros de estado en JSON que viajan dentro del pen.

Dos reglas, y las dos vienen del medio: el pen puede desaparecer a media frase y
puede estar leyéndolo otra máquina.

  * Leer nunca es un error. Un fichero que no está, que está a medias o que trae
    basura significa "aquí no hay nada escrito", no una excepción que propagar.
  * Escribir es atómico (fichero temporal + os.replace), y si falla, se dice que
    ha fallado en vez de reventar: ninguno de estos ficheros es imprescindible.

Los comparten el registro del servicio (daemon.lock.json) y la memoria de la UI
(ui_prefs.json). Y con ellos viaja `pid_alive`, que es lo que le da sentido a un
registro con un pid dentro: un fichero de bloqueo solo vale si se puede saber si
quien lo escribió sigue vivo.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


def stamp() -> str:
    """El formato de fecha de todos estos ficheros y del diario del servicio."""
    return f"{datetime.now():%Y-%m-%d %H:%M:%S}"


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: dict) -> bool:
    """True si se ha escrito. False = pen de solo lectura o ya extraído."""
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def pid_alive(pid: int) -> bool:
    """¿Sigue vivo ese proceso?

    OJO: en Windows NO vale os.kill(pid, 0). Con cualquier señal que no sea
    CTRL_C/CTRL_BREAK, os.kill llama a TerminateProcess, es decir, MATA el
    proceso en vez de comprobarlo. Hay que preguntar por el handle."""
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(handle, ctypes.byref(code))
        k32.CloseHandle(handle)
        return bool(ok) and code.value == STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True     # existe, pero es de otro usuario
