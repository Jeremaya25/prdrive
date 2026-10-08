#!/usr/bin/env python3
"""El ritmo del servicio: ve la parada en un segundo y no lee más a menudo lo caro.

Abrir la ventana para el servicio anterior (`daemon.stop`) y espera a que suelte
su registro. Lo que decide cuánto tarda la ventana en salir son dos relojes:
cada cuánto mira el servicio si debe parar (`STOP_POLL_SECONDS`) y cada cuánto
mira el lanzador si ya paró (`STOP_WAIT_STEP`). El registro y la foto de
procesos del llavero, que son lo caro, siguen cada `POLL_SECONDS`.

Con un reloj de mentira (`sleep` adelanta la hora sin esperar) para los ritmos,
y una vez con el de verdad para comprobar que el servicio de un proceso real lo
cumple.
"""

import os
import tempfile
import threading
import time as tiempo
from pathlib import Path

from _harness import Checks, sandbox

import runsync
from common import model, store

c = Checks("ritmo del servicio")


# las constantes que se sostienen unas a otras
c("el servicio mira si debe parar al menos cada segundo", runsync.STOP_POLL_SECONDS <= 1.0, True)
c("  y dos miradas caben en el plazo del lanzador",
  runsync.STOP_POLL_SECONDS * 2 < runsync.STOP_WAIT_SECONDS, True)
c("el lanzador mira cada décima", runsync.STOP_WAIT_STEP <= 0.1, True)
c("el registro y el llavero no se miran más a menudo que cada 5 s",
  runsync.POLL_SECONDS >= 5.0, True)


class Reloj:
    """Un `time` de mentira: `sleep` adelanta la hora sin esperar y apunta cuánto."""

    def __init__(self, t: float = 1000.0):
        self.t = t
        self.dormidas: list[float] = []

    def monotonic(self) -> float:
        return self.t

    def sleep(self, segundos: float) -> None:
        self.dormidas.append(segundos)
        self.t += segundos


diario: list[str] = []
reales = {n: getattr(runsync, n) for n in
          ("time", "dlog", "pen_present", "stop_requested", "daemon_cycle", "read_lock",
           "pareja_llavero", "atender_llavero", "pasada_llavero", "STOP", "LOCK")}
real_bajar, real_cwd = runsync.prioridad.bajar, os.getcwd()
runsync.dlog = diario.append
runsync.prioridad.bajar = lambda pid=None: True
runsync.pareja_llavero = lambda: object()       # «lleva llavero»; nada lo mira de verdad


def servicio(minutos: float, parar_a: float | None = None, quitar_a: float | None = None):
    """Corre `daemon_main()` con reloj de mentira y devuelve lo que se ha visto.

    Args:
        minutos: El intervalo del servicio.
        parar_a: Hora (reloj de mentira) en que aparece el `daemon.stop`.
        quitar_a: Hora en que desaparece el dispositivo.

    Returns:
        Un diccionario con el reloj, el diario y las horas de cada cosa.
    """
    reloj = Reloj()
    visto = {"ciclos": [], "llavero": [], "registro": [], "parada": [], "reloj": reloj}
    runsync.time = reloj
    diario.clear()
    runsync.daemon_cycle = lambda pairs, lock: visto["ciclos"].append(reloj.t)
    runsync.atender_llavero = lambda v, p: visto["llavero"].append(reloj.t)
    runsync.pasada_llavero = lambda v, p, por: None
    real_leer = reales["read_lock"]
    runsync.read_lock = lambda: visto["registro"].append(reloj.t) or real_leer()

    def parada() -> bool:
        visto["parada"].append(reloj.t)
        return parar_a is not None and reloj.t >= parar_a
    runsync.stop_requested = parada
    runsync.pen_present = lambda: quitar_a is None or reloj.t < quitar_a
    try:
        runsync.daemon_main(["notas"], minutos)
    finally:
        runsync.time = reales["time"]
        os.chdir(real_cwd)
    return visto


try:
    with sandbox():
        runsync.STOP = model.STATE_DIR / "daemon.stop"
        runsync.LOCK = model.STATE_DIR / "daemon.lock.json"

        # la parada llega a mitad de un segundo
        v = servicio(30, parar_a=1007.3)
        c("el servicio para por la petición", "parada solicitada por el lanzador" in diario[-1], True)
        c("  la ve en el siguiente segundo, no a los 5 s",
          0 <= v["reloj"].t - 1007.3 <= 1.0, True)
        c("  y mira si debe parar en cada segundo",
          sorted(set(v["parada"])), [1000.0 + i for i in range(9)])

        # lo caro sigue a su ritmo
        c("el llavero se atiende al empezar y luego cada 5 s", v["llavero"], [1000.0, 1005.0])
        c("  y el registro se lee a la vez", [t for t in v["registro"] if t < 1007.3],
          [1000.0, 1005.0])

        # la unidad que se va, igual
        v = servicio(30, quitar_a=1002.5)
        c("el servicio ve que se fue el dispositivo en un segundo",
          ("dispositivo no conectado" in diario[-1],
           0 <= v["reloj"].t - 1002.5 <= 1.0), (True, True))

        # la espera entre ciclos no se pasa de su hora: tres segundos son tres
        v = servicio(0.05, parar_a=1010.0)
        c("el último trozo de la espera llega justo al ciclo siguiente",
          [round(b - a, 6) for a, b in zip(v["ciclos"], v["ciclos"][1:])], [3.0, 3.0, 3.0])

        # el lanzador mira cada décima
        reloj = Reloj()
        runsync.time = reloj
        yo = {"pid": os.getpid(), "host": runsync.HOST, "started": "x"}
        store.write_json(runsync.LOCK, yo)
        sueltan = reloj.t + 0.55
        real_leer = reales["read_lock"]
        runsync.read_lock = lambda: None if reloj.t >= sueltan else dict(yo)
        try:
            dicho = runsync.stop_previous_daemon()
        finally:
            runsync.time, runsync.read_lock = reales["time"], real_leer
        c("el lanzador ve que el servicio soltó su registro a la décima siguiente",
          (dicho, reloj.dormidas), (f"Servicio anterior (pid {os.getpid()}) detenido.",
                                     [runsync.STOP_WAIT_STEP] * 6))
        c("  y le dejó el aviso de parar", runsync.STOP.exists(), True)
        runsync.STOP.unlink(missing_ok=True)

        # con el tiempo de verdad: un servicio que está esperando ve la parada ya
        runsync.LOCK.unlink(missing_ok=True)
        runsync.daemon_cycle = lambda pairs, lock: None
        runsync.atender_llavero = lambda v, p: None
        runsync.pen_present = lambda: True
        runsync.stop_requested = reales["stop_requested"]
        en_reposo = threading.Event()
        real_leer = reales["read_lock"]
        runsync.read_lock = lambda: en_reposo.set() or real_leer()
        hilo = threading.Thread(target=lambda: runsync.daemon_main(["notas"], 30), daemon=True)
        hilo.start()
        c("el servicio de verdad llega a esperar", en_reposo.wait(5), True)
        t0 = tiempo.monotonic()
        runsync.STOP.touch()
        hilo.join(3)
        c("  y con el tiempo de verdad ve el stop en un segundo y algo (no en 5)",
          (hilo.is_alive(), tiempo.monotonic() - t0 < 2.0),
          (False, True))
        c("  y suelta su registro", runsync.LOCK.exists(), False)
finally:
    for nombre, valor in reales.items():
        setattr(runsync, nombre, valor)
    runsync.prioridad.bajar = real_bajar
    os.chdir(real_cwd)

raise SystemExit(c.report())
