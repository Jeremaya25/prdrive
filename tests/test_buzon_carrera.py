#!/usr/bin/env python3
"""Una petición que `pedir()` da por dejada llega al agente, pase lo que pase a la vez.

Quien pide abre el buzón y escribe su línea; el agente lo renombra, lo lee y lo
borra (`equipo.pedir()`, `equipo.recoger()`). Son dos procesos:

- En POSIX el agente puede renombrar un buzón que otro tiene abierto. Si lo
  lee antes de que ese otro escriba, la línea cae en un fichero ya leído y el
  borrado se la lleva: `pedir()` devolvía True y la petición no existía
  (medido en ext4 con procesos de verdad: 25391 de 3,2 millones en bucle
  cerrado). Aquí se provoca ese instante a mano: el agente llega, desde otro
  hilo, cuando quien pide ya tiene el buzón abierto y todavía no ha escrito.
- En Windows el renombrado falla mientras otro lo tenga abierto, así que no se
  pierde nada; lo que pasa es que abrir el buzón mientras el agente lo
  renombra se niega, y `pedir()` devolvía False. Ahora insiste un momento.

Al final, lo mismo con procesos de verdad y sin provocar nada: lo que se da
por dejado llega, una vez.
"""

import errno
import os
import sys
import threading
import time
from pathlib import Path

from _harness import REPO, Checks, tmpdir

import _buzon_procesos
from common import equipo

c = Checks("el buzón: lo que se da por dejado, llega")

ABRIR = Path.open
"""El `Path.open` de verdad: aquí se sustituye para colarse entre abrir y escribir."""
BASE = tmpdir("prdrive-buzon-")
BUZON = BASE / "state" / equipo.BUZON_SERVICIO
PAUSA = 0.3             # segundos que quien pide tarda en escribir, con el agente ya encima
ESPERA_DE_FABRICA = getattr(equipo, "ESPERA_BUZON", None)


def pides(peticiones: list[dict]) -> list[str]:
    """Devuelve el `pide` de cada petición, ordenados."""
    return sorted(p["pide"] for p in peticiones)


def poner_espera(segundos: float | None) -> None:
    """Pone `equipo.ESPERA_BUZON`; con `None`, la de fábrica."""
    if segundos is not None:
        equipo.ESPERA_BUZON = segundos
    elif ESPERA_DE_FABRICA is not None:
        equipo.ESPERA_BUZON = ESPERA_DE_FABRICA
    elif hasattr(equipo, "ESPERA_BUZON"):
        del equipo.ESPERA_BUZON


def pedir_con_el_agente_encima(peticion: dict) -> tuple[bool, list[dict], float]:
    """Pide mientras el agente recoge el buzón que quien pide acaba de abrir.

    El agente corre en otro hilo, como desde su proceso, y arranca cuando
    `pedir()` ya tiene el buzón abierto; quien pide le da `PAUSA` segundos, de
    sobra para renombrarlo, leerlo y borrarlo, antes de escribir su línea.

    Returns:
        Lo que devolvió `pedir()`, lo que se llevó el agente en esa recogida y
        los segundos que le llevó.
    """
    recogido: list[dict] = []
    tardo: list[float] = []

    def agente() -> None:
        """Recoge el buzón y apunta cuánto ha tardado."""
        t0 = time.monotonic()
        recogido.extend(equipo.recoger(BUZON))
        tardo.append(time.monotonic() - t0)

    hilo = threading.Thread(target=agente)

    def abrir(ruta, mode="r", *args, **kwargs):
        """Abre de verdad y, si es el buzón para añadir, deja llegar al agente."""
        f = ABRIR(ruta, mode, *args, **kwargs)
        if ruta == BUZON and "a" in mode and hilo.ident is None:
            hilo.start()
            hilo.join(PAUSA)
        return f

    Path.open = abrir
    try:
        dicho = equipo.pedir(peticion, BUZON)
    finally:
        Path.open = ABRIR
    hilo.join(60)
    return dicho, recogido, tardo[0] if tardo else -1.0


# 1. El agente recoge entre que quien pide abre el buzón y escribe.
poner_espera(30.0)                      # que no sea el plazo lo que decida estas comprobaciones
dicho, a_la_vez, tardo = pedir_con_el_agente_encima({"pide": equipo.PIDE_PAUSAR_RAIZ})
llegadas = a_la_vez + equipo.recoger(BUZON)
c("el agente recoge el buzón entre que se abre y se escribe: la petición llega",
  (dicho, pides(llegadas)), (True, [equipo.PIDE_PAUSAR_RAIZ]))
if os.name == "nt":
    print("  (saltado) en Windows el agente no se lleva un buzón abierto: no hay a quién esperar")
else:
    c("  porque el agente espera a que quien pide acabe de escribirla",
      (pides(a_la_vez), tardo >= PAUSA * 0.5), ([equipo.PIDE_PAUSAR_RAIZ], True))

equipo.pedir({"pide": equipo.PIDE_REANUDAR}, BUZON)
dicho, a_la_vez, _tardo = pedir_con_el_agente_encima({"pide": equipo.PIDE_PASADA, "parejas": []})
llegadas = a_la_vez + equipo.recoger(BUZON)
c("  con otra petición ya dentro: llegan las dos, una vez cada una",
  (dicho, pides(llegadas)), (True, [equipo.PIDE_PASADA, equipo.PIDE_REANUDAR]))
c("  y no queda nada del buzón por el camino",
  sorted(p.name for p in BUZON.parent.iterdir()), [])

if os.name == "nt":
    print("  (saltado) en Windows no hay turno del buzón que esperar ni que falte")
else:
    import fcntl

    # Quien se queda parado con el turno no detiene al agente.
    poner_espera(0.3)
    equipo.pedir({"pide": equipo.PIDE_PASADA}, BUZON)
    parado = os.open(BUZON.parent, os.O_RDONLY)
    try:
        fcntl.flock(parado, fcntl.LOCK_SH)
        t0 = time.monotonic()
        llegadas = equipo.recoger(BUZON)
        dt = time.monotonic() - t0
    finally:
        os.close(parado)
    c("un proceso parado con el turno no cuelga al agente: espera un plazo y sigue",
      (pides(llegadas), dt < 10.0), ([equipo.PIDE_PASADA], True))

    # Ni a quien pide, si el parado es el agente.
    parado = os.open(BUZON.parent, os.O_RDONLY)
    try:
        fcntl.flock(parado, fcntl.LOCK_EX)
        t0 = time.monotonic()
        dicho = equipo.pedir({"pide": equipo.PIDE_REANUDAR}, BUZON)
        dt = time.monotonic() - t0
    finally:
        os.close(parado)
    c("  ni a quien pide", (dicho, dt < 10.0, pides(equipo.recoger(BUZON))),
      (True, True, [equipo.PIDE_REANUDAR]))

    class SinCerrojos:
        """Un `fcntl` cuyo `flock` falla, como en un sistema de ficheros que no lo admite."""
        LOCK_SH, LOCK_EX, LOCK_NB = fcntl.LOCK_SH, fcntl.LOCK_EX, fcntl.LOCK_NB

        @staticmethod
        def flock(_fd, _modo) -> None:
            """Falla con «no hay cerrojos»."""
            raise OSError(errno.ENOLCK, "No locks available")

    equipo.fcntl = SinCerrojos
    try:
        dicho = equipo.pedir({"pide": equipo.PIDE_BLOQUEAR}, BUZON)
        llegadas = equipo.recoger(BUZON)
    finally:
        equipo.fcntl = fcntl
    c("sin cerrojos en el sistema de ficheros, el buzón sigue funcionando",
      (dicho, pides(llegadas)), (True, [equipo.PIDE_BLOQUEAR]))
poner_espera(None)


# 2. Windows: abrir el buzón mientras el agente lo renombra se niega un instante.
class Ocupado:
    """Niega las primeras aperturas del buzón, como Windows mientras el agente lo renombra.

    Args:
        veces: Cuántas aperturas se niegan; `None`, todas.

    Attributes:
        aperturas: Cuántas veces intentó `pedir()` abrir el buzón.
    """

    def __init__(self, veces: int | None) -> None:
        self.quedan = veces
        self.aperturas = 0

    def __enter__(self) -> "Ocupado":
        yo = self

        def abrir(ruta, mode="r", *args, **kwargs):
            """Lanza `PermissionError` mientras toque; después abre de verdad."""
            if ruta == BUZON and "a" in mode:
                yo.aperturas += 1
                if yo.quedan is None or yo.quedan > 0:
                    yo.quedan = None if yo.quedan is None else yo.quedan - 1
                    raise PermissionError(errno.EACCES, "El proceso no tiene acceso al archivo")
            return ABRIR(ruta, mode, *args, **kwargs)

        Path.open = abrir
        return self

    def __exit__(self, *_exc) -> None:
        Path.open = ABRIR


es_windows = equipo.IS_WIN
try:
    equipo.IS_WIN = True
    with Ocupado(3) as ocupado:
        dicho = equipo.pedir({"pide": equipo.PIDE_PARAR}, BUZON)
    c("Windows: al buzón ocupado un instante por el renombrado del agente se le espera",
      (dicho, ocupado.aperturas, pides(equipo.recoger(BUZON))),
      (True, 4, [equipo.PIDE_PARAR]))
    poner_espera(0.2)
    with Ocupado(None) as ocupado:
        t0 = time.monotonic()
        dicho = equipo.pedir({"pide": equipo.PIDE_PARAR}, BUZON)
        dt = time.monotonic() - t0
    c("  el que no se deja nunca se da por perdido pasado el plazo, y se dice",
      (dicho, ocupado.aperturas > 1, dt < 10.0, equipo.recoger(BUZON)),
      (False, True, True, []))
    equipo.IS_WIN = False
    with Ocupado(3) as ocupado:
        dicho = equipo.pedir({"pide": equipo.PIDE_PARAR}, BUZON)
    c("fuera de Windows un permiso denegado es de permisos: no se insiste",
      (dicho, ocupado.aperturas), (False, 1))
finally:
    equipo.IS_WIN = es_windows
    poner_espera(None)

c("un buzón que no se puede crear se dice, como siempre",
  equipo.pedir({"pide": equipo.PIDE_PARAR}, Path(__file__) / "state" / "x.pide"), False)


# 3. Con procesos de verdad, sin provocar nada.
BUZONES = 2
# Varios piden a la vez en cada buzón. En Windows, uno: allí dos procesos que
# añaden al mismo fichero en el mismo instante se pisan la línea (`open("a")`
# busca el final y escribe en dos pasos), haya agente o no, y eso no es de esta
# carrera (`agent-window.md`, «What a request can still lose»).
ESCRITORES = 1 if os.name == "nt" else 2
SEGUNDOS = 1.0          # lo que pide cada escritor
cuenta = _buzon_procesos.pedir_y_recoger(
    REPO, [BASE / f"r{i}" / "state" / equipo.BUZON_SERVICIO for i in range(BUZONES)],
    BASE, ESCRITORES, SEGUNDOS)
c("procesos de verdad: los que piden y los que recogen acaban bien", cuenta.codigos,
  [0] * (BUZONES * (ESCRITORES + 1)))
print(f"    {cuenta.dichas} peticiones dadas por dejadas en {BUZONES} buzones, "
      f"{ESCRITORES} pidiendo a la vez en cada uno")
c("  se ha pedido de verdad", cuenta.dichas > 100, True)
c("  ninguna petición dada por dejada se pierde", cuenta.perdidas, 0)
c("  y ninguna llega dos veces", cuenta.repetidas, 0)

sys.exit(c.report())
