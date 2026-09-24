#!/usr/bin/env python3
"""
Qué lanza el vigilante al detectar el dispositivo, y si su copia está al día.

Las parejas y el intervalo son los del servicio: viven en el dispositivo y los lee
runsync, así que el vigilante no pasa ninguno, ni aunque un watch.json de una
versión anterior los traiga. Y el modo `sync` va por `--auto --once`: antes era
`runsync.py <parejas>`, que sin parejas se quedaba en `runsync.py` a secas y
abría la ventana en vez de sincronizar.

La copia del vigilante en el equipo la hace `install` y nada más la pone al día,
así que `copia_al_dia()` la compara con la del dispositivo para poder decirlo.

Nada de esto lanza un proceso ni escribe en el equipo de verdad: `Popen` y el
diario se sustituyen, y las rutas del equipo se apuntan a un temporal.
"""

import sys
from pathlib import Path

from _harness import Checks, tmpdir

import penwatch

c = Checks("penwatch: qué lanza y si su copia está al día")

EQUIPO = tmpdir("prdrive-pwlaunch-")
penwatch.LOG_FILE = EQUIPO / "penwatch.log"
penwatch.log = lambda msg: None

lanzadas: list[list[str]] = []


class _Popen:
    pid = 4321

    def __init__(self, args, **_kwargs):
        lanzadas.append(list(args))


real_popen = penwatch.subprocess.Popen
penwatch.subprocess.Popen = _Popen
RAIZ = Path("/media/prdrive")
try:
    def lanza(cfg: dict) -> list[str]:
        """Lo que va detrás del runsync.py del dispositivo."""
        lanzadas.clear()
        c(f"lanza en modo {cfg.get('mode')}", penwatch.launch(RAIZ, cfg), True)
        orden = lanzadas[0]
        c(f"y es el runsync.py del dispositivo ({cfg.get('mode')})",
          orden[1], str(RAIZ / penwatch.STRUCT_MARKER))
        return orden[2:]

    c("ui: la ventana, sin argumentos", lanza({"mode": "ui"}), [])
    c("daemon: el servicio, con lo del servicio", lanza({"mode": "daemon"}), ["--auto"])
    c("sync: una pasada, y no la ventana", lanza({"mode": "sync"}), ["--auto", "--once"])

    # Lo que escribía una versión anterior: ya no manda.
    viejo = {"pairs": ["docs", "claves"], "interval": 10}
    c("daemon: un watch.json de antes no pasa parejas ni intervalo",
      lanza({"mode": "daemon", **viejo}), ["--auto"])
    c("sync: tampoco", lanza({"mode": "sync", **viejo}), ["--auto", "--once"])
finally:
    penwatch.subprocess.Popen = real_popen


# --- la copia del equipo frente a la del dispositivo ----------------------------
real_copia = penwatch.SELF_COPY
propio = Path(penwatch.__file__).resolve()
try:
    penwatch.SELF_COPY = EQUIPO / "penwatch.py"
    c("sin copia en el equipo no está al día", penwatch.copia_al_dia(), False)

    penwatch.SELF_COPY.write_bytes(propio.read_bytes())
    c("la misma copia está al día", penwatch.copia_al_dia(), True)

    penwatch.SELF_COPY.write_bytes(propio.read_bytes() + b"\n# otra versi\xc3\xb3n\n")
    c("otra copia no", penwatch.copia_al_dia(), False)

    # Llamada desde la propia copia del equipo no hay con qué comparar.
    penwatch.SELF_COPY = propio
    c("desde la propia copia no se acusa a nadie", penwatch.copia_al_dia(), True)
finally:
    penwatch.SELF_COPY = real_copia

sys.exit(c.report())
