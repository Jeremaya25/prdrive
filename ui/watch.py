#!/usr/bin/env python3
"""
watch.py — Lo que la UI necesita de penwatch.py. Sin Tkinter.

La dependencia va en un solo sentido: la UI conoce a penwatch, penwatch no conoce
a nadie. Eso es deliberado y no se puede invertir — `penwatch.py` se copia al
equipo y tiene que seguir funcionando con el dispositivo desconectado, así que no puede
importar nada que viva en el dispositivo.

Para leer (estado, detección) se importa penwatch y se usan sus funciones, que ya
devuelven filas. Para instalar y desinstalar se lanza como proceso: son órdenes
que escriben en el equipo y cuentan lo que hacen por su salida, y esa salida se
enseña en la misma ventana que se usa para sync.py.

El vigilante solo decide QUÉ se hace al enchufar. Las parejas y el intervalo son
los del servicio, que viven en el dispositivo y se eligen en la ventana
principal: el servicio es uno, se arranque a mano o al enchufar.
"""

from __future__ import annotations

import sys
from typing import NamedTuple

from common import fleet, model

# En el orden en que se ofrecen: de lo que menos hace solo a lo que más.
MODES = ("ui", "daemon", "sync")
MODE_LABELS = {
    "ui": "Abrir la ventana",
    "daemon": "Arrancar el servicio",
    "sync": "Una pasada y nada más",
}
# Qué parejas y cada cuánto no se dice aquí: lo dice una sola vez la pantalla,
# debajo de las tres opciones (son los del servicio, para las dos que sincronizan).
MODE_HELP = {
    "ui": "abre la ventana de runsync y decides tú (por defecto)",
    "daemon": "sincroniza cada N minutos mientras siga puesto",
    "sync": "sincroniza una vez, en silencio, y se cierra",
}

# Lo que se hace al enchufar, dicho en la línea de la ventana principal.
_AL_ENCHUFAR = {
    "ui": "abre esta ventana",
    "daemon": "arranca el servicio",
    "sync": "una pasada de estas parejas",
}


class Resumen(NamedTuple):
    """Qué hace el arranque automático de este equipo con ESTE dispositivo.

    `estado`, de más a menos grave para quien lee la línea:
      no_disponible     penwatch no se puede importar: no se dice nada
      sin_instalar      en este equipo no hay vigilante
      otro_dispositivo  lo hay, pero vigila otro prdrive (un equipo tiene uno)
      desfasado         vigila este, con una copia de otra versión
      instalado         vigila este, y `modo` es lo que hará"""
    estado: str
    modo: str = ""

    @property
    def vigila_este(self) -> bool:
        """Hay un vigilante en este equipo que atiende a este dispositivo."""
        return self.estado in ("desfasado", "instalado")


class Linea(NamedTuple):
    """La línea de la ventana principal: el texto, si va en ámbar, y el botón."""
    texto: str
    aviso: bool
    boton: str


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
    Está en el equipo, nunca en el dispositivo, y decirlo es media explicación."""
    try:
        return str(_penwatch().LOG_FILE)
    except Exception:
        return ""


def is_installed() -> bool:
    pw = _penwatch()
    return bool(pw.read_json(pw.CONFIG_FILE))


def installed_options() -> dict:
    """Con qué se instaló, para precargar el formulario. Vacío si no lo está.

    Sin parejas ni intervalo aunque un watch.json de antes los traiga: ya no son
    del equipo, y reinstalar es precisamente lo que los quita."""
    pw = _penwatch()
    cfg = pw.read_json(pw.CONFIG_FILE)
    if not cfg:
        return {}
    return {
        "mode": cfg.get("mode", "ui"),
        "poll": cfg.get("poll_seconds", pw.POLL_SECONDS),
        "extra_roots": list(cfg.get("extra_roots") or []),
        "device_id": str(cfg.get("device_id") or ""),
    }


def resumen() -> Resumen:
    """Qué hace el arranque automático de este equipo con este dispositivo.

    Solo lee ficheros —watch.json, las dos copias de penwatch, el PRDRIVE—: nada
    de `schtasks` ni `systemctl`, porque lo pregunta la ventana al pintarse y la
    primera pintura tiene que ser instantánea (la misma regla que
    `update.pending()`). Si la tarea está registrada o no lo cuenta la pantalla
    del vigilante, que sí puede tardar. Nunca lanza.

    De módulo para que los tests la sustituyan."""
    try:
        pw = _penwatch()
        cfg = pw.read_json(pw.CONFIG_FILE)
    except Exception:                                   # noqa: BLE001
        return Resumen("no_disponible")
    if not cfg:
        return Resumen("sin_instalar")
    suyo = str(cfg.get("device_id") or "")
    # Sin id en watch.json el vigilante reconoce cualquier prdrive por la mera
    # presencia del PRDRIVE, así que también este.
    if suyo and suyo != fleet.device_id():
        return Resumen("otro_dispositivo")
    try:
        al_dia = pw.copia_al_dia()
    except Exception:                                   # noqa: BLE001
        al_dia = True
    modo = str(cfg.get("mode") or "ui")
    return Resumen("instalado" if al_dia else "desfasado", modo)


def linea(res: Resumen) -> Linea | None:
    """Lo que dice la ventana principal del arranque automático, o None.

    Aquí y no en la ventana para que el menú de consola diga lo mismo."""
    if res.estado == "no_disponible":
        return None
    if res.estado == "sin_instalar":
        return Linea("En este equipo no se arranca nada al enchufarlo.",
                     False, "Configurar…")
    if res.estado == "otro_dispositivo":
        return Linea("El arranque automático de este equipo es para otro "
                     "dispositivo.", False, "Cambiar…")
    if res.estado == "desfasado":
        return Linea("El arranque automático de este equipo es de otra versión: "
                     "puede no hacer lo que dice aquí.", True, "Revisar…")
    hace = _AL_ENCHUFAR.get(res.modo, res.modo)
    return Linea(f"Al enchufarlo en este equipo: {hace}.", False, "Cambiar…")


PAUSA = "En pausa mientras esta ventana esté abierta."


def install_command(mode: str = "ui", poll=None, extra_roots=(),
                    start: bool = True) -> list[str]:
    """La orden completa de instalación, para lanzarla y enseñar su salida.

    Sin parejas ni intervalo: son los del servicio (ver el docstring)."""
    cmd = [sys.executable, str(model.PENWATCH_PY), "install", "--mode", mode]
    if poll:
        cmd += ["--poll", str(poll)]
    for root in extra_roots:
        if str(root).strip():
            cmd += ["--extra-root", str(root).strip()]
    if not start:
        cmd.append("--no-start")
    return cmd


def uninstall_command() -> list[str]:
    return [sys.executable, str(model.PENWATCH_PY), "uninstall"]
