#!/usr/bin/env python3
"""
prefs.py — Las parejas y el intervalo del servicio.

El servicio periódico es uno solo, se arranque a mano («Iniciar servicio») o al
enchufar el dispositivo (el vigilante, `runsync --auto`), y su configuración vive
en `state/ui_prefs.json`: viaja en el dispositivo y acompaña al usuario de una
máquina a otra. Es también con lo que sale precargada la ventana. Ese recuerdo
manda sobre `[daemon]` del TOML, que a su vez manda sobre los valores de fábrica.

Solo se escribe al ARRANCAR el servicio (`save_prefs`, desde runsync). Una pasada
manual no lo toca: marcar una sola pareja para sincronizarla ahora no puede
decidir qué sincroniza el servicio la próxima vez que se enchufe el dispositivo.
`--auto` y el servicio únicamente leen, para que un arranque automático nunca
reescriba lo que se decidió a mano.

El fichero conserva el nombre de cuando era «lo último que se eligió en la UI»:
renombrarlo pediría una migración para cambiar una palabra.
"""

from __future__ import annotations

import socket

from common import model, store
from common.model import Config

PREFS = model.STATE_DIR / "ui_prefs.json"
HOST = socket.gethostname()


def read_prefs() -> dict:
    """La última elección de la UI; vacío si aún no hay ninguna."""
    return store.read_json(PREFS)


def save_prefs(action: str, pairs: list[str], interval_min: float,
               all_names: list[str]) -> None:
    """Recuerda lo elegido para el servicio. 'known' anota qué parejas existían
    en ese momento: así una pareja añadida al TOML más tarde no se confunde con
    una que el usuario había desmarcado (ver startup_defaults).

    `action` se sigue guardando aunque ya solo llegue 'daemon': es lo que
    distingue los registros de antes, cuando una pasada manual también
    escribía aquí (ver `startup_defaults`)."""
    data = {
        "action": action,
        "pairs": list(pairs),
        "interval_min": interval_min,
        "known": list(all_names),
        "host": HOST,
        "saved": store.stamp(),
    }
    old = read_prefs()
    if all(old.get(k) == v for k, v in data.items() if k not in ("host", "saved")):
        return  # misma elección que la vez anterior: no se gasta escritura en el dispositivo
    store.write_json(PREFS, data)  # si el dispositivo ya no está, recordar no es vital


def daemon_defaults(config: Config) -> tuple[list[str], float]:
    """Los valores de [daemon] del TOML, saneados contra las parejas que existen."""
    names = config.names
    pairs = [n for n in config.daemon.get("pairs", names) if n in names] or names
    return pairs, float(config.daemon.get("interval_minutes", model.DEFAULT_INTERVAL_MIN))


def startup_defaults(config: Config) -> tuple[list[str], float, str | None]:
    """Las parejas y el intervalo del servicio: con qué sale precargada la UI y
    con qué arranca --auto sin argumentos. Precedencia: lo guardado al arrancar
    el servicio > [daemon] del TOML > todas las parejas cada 30 min. Devuelve
    (parejas, minutos, nota); la nota es None si no hay recuerdo, y si no, el
    texto con el que la UI dice de dónde salen las casillas marcadas."""
    all_names = config.names
    d_pairs, d_interval = daemon_defaults(config)

    prefs = read_prefs()
    # Un registro 'manual' solo puede ser de antes de que las pasadas manuales
    # dejaran de escribir aquí, y es justo el recuerdo de una pasada suelta que
    # no debe decidir el servicio. Se descarta por 'manual' y no por «distinto
    # de 'daemon'»: uno sin `action`, escrito a mano, sigue valiendo.
    if not prefs or prefs.get("action") == "manual":
        return d_pairs, d_interval, None

    saved = prefs.get("pairs")
    remembered = {n for n in saved if isinstance(n, str)} if isinstance(saved, list) else set()
    known = prefs.get("known")
    if isinstance(known, list):
        # Parejas añadidas al TOML después de aquella elección: nadie las ha
        # desmarcado nunca, así que entran marcadas.
        remembered |= {n for n in all_names if n not in known}
    # Recortado a lo que sigue existiendo y en el orden del TOML.
    pairs = [n for n in all_names if n in remembered]
    if not pairs:
        # Nada de aquello existe ya (parejas renombradas, TOML regenerado): el
        # recuerdo entero es basura, se vuelve al TOML sin anunciar nada.
        return d_pairs, d_interval, None

    try:
        interval = max(1.0, float(prefs.get("interval_min", d_interval)))
    except (TypeError, ValueError):
        interval = d_interval

    when = prefs.get("saved")
    return pairs, interval, ("Parejas e intervalo del servicio"
                             + (f", elegidos el {when}" if when else ""))
