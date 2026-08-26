#!/usr/bin/env python3
"""
watch.py — Lo que la UI necesita de penwatch.py. Sin Tkinter.

La dependencia va en un solo sentido: la UI conoce a penwatch, penwatch no conoce
a nadie. Eso es deliberado y no se puede invertir — `penwatch.py` se copia al
equipo y tiene que seguir funcionando con el pen desconectado, así que no puede
importar nada que viva en el pen.

Para leer (estado, detección) se importa penwatch y se usan sus funciones, que ya
devuelven filas. Para instalar y desinstalar se lanza como proceso: son órdenes
que escriben en el equipo y cuentan lo que hacen por su salida, y esa salida se
enseña en la misma ventana que se usa para sync.py.
"""

from __future__ import annotations

import sys

from common import model

MODES = ("ui", "sync", "daemon")
MODE_HELP = {
    "ui": "abre la ventana de runsync y decides tú (por defecto)",
    "sync": "sincroniza una vez, en silencio, y se cierra",
    "daemon": "arranca el servicio periódico",
}


def _penwatch():
    """penwatch se importa aquí dentro y no arriba.

    Es un script hermano, no un módulo del paquete: si por lo que sea no se
    pudiera importar, eso no debe impedir que se abra la ventana principal."""
    import penwatch
    return penwatch


def available() -> bool:
    try:
        _penwatch()
        return True
    except Exception:
        return False


def status_rows() -> list[tuple[str, str]]:
    return _penwatch().status_rows()


def probe_rows() -> list[tuple[str, str]]:
    return _penwatch().probe_rows()


def log_tail(lines: int = 10) -> list[str]:
    return _penwatch().log_tail(lines)


def log_path() -> str:
    """Dónde vive el diario, para poder enseñarlo junto a lo que se lee de él.
    Está en el equipo, nunca en el pen, y decirlo es media explicación."""
    try:
        return str(_penwatch().LOG_FILE)
    except Exception:
        return ""


def is_installed() -> bool:
    pw = _penwatch()
    return bool(pw.read_json(pw.CONFIG_FILE))


def installed_options() -> dict:
    """Con qué se instaló, para precargar el formulario. Vacío si no lo está."""
    pw = _penwatch()
    cfg = pw.read_json(pw.CONFIG_FILE)
    if not cfg:
        return {}
    return {
        "mode": cfg.get("mode", "ui"),
        "pairs": list(cfg.get("pairs") or []),
        "interval": cfg.get("interval"),
        "poll": cfg.get("poll_seconds", pw.POLL_SECONDS),
        "extra_roots": list(cfg.get("extra_roots") or []),
    }


def install_command(mode: str = "ui", pairs=(), interval=None, poll=None,
                    extra_roots=(), start: bool = True) -> list[str]:
    """La orden completa de instalación, para lanzarla y enseñar su salida."""
    cmd = [sys.executable, str(model.PENWATCH_PY), "install", "--mode", mode]
    if interval:
        cmd += ["--interval", str(interval)]
    if poll:
        cmd += ["--poll", str(poll)]
    for root in extra_roots:
        if str(root).strip():
            cmd += ["--extra-root", str(root).strip()]
    if not start:
        cmd.append("--no-start")
    # --pairs va al final: admite varios valores y se comería lo que viniera detrás.
    limpias = [p for p in pairs if str(p).strip()]
    if limpias:
        cmd += ["--pairs", *limpias]
    return cmd


def uninstall_command() -> list[str]:
    return [sys.executable, str(model.PENWATCH_PY), "uninstall"]
