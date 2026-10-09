#!/usr/bin/env python3
"""Los tiempos de las ventanas de host con `PRDRIVE_PERF`: el asistente y la pregunta del agente.

Estas marcas van al diario del EQUIPO (`equipo/perf.log`, `host=True`), no al del
dispositivo, y las ponen las dos ventanas que corren fuera de él:

- el asistente (`ui/tk_install.py`): `start-wizard` (desde que se creó el proceso),
  `paso-<slug>` por cada paso al que se llega con «Siguiente» o «Atrás» (el primero
  lo cuenta `start-wizard`) y `apply-wizard`;
- la pregunta del agente (`ui/tk_agente.py`, lanzada por `pregunta.py`):
  `start-agente` y `apply-agente`.

Se comprueba que:
- con la medida apagada no se escribe ningún diario, ni se crea la carpeta del equipo;
- `run_wizard()` marca `apply-wizard` y `start-wizard` en el equipo, no `apply-main`,
  y la carpeta del equipo (que no existe al empezar) la crea la primera marca;
- la pregunta del agente, en proceso, marca `start-agente` y `apply-agente` en el equipo;
- `pregunta.py`, en su propio proceso, hace lo mismo, y sin la medida no escribe nada;
- cada «Siguiente» o «Atrás» anota el paso al que llega, con su `vez`, y el nombre del
  paso quita tildes y une las palabras con guiones.

Las partes de Tk se saltan sin pantalla o sin `tkinter`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from _harness import REPO, Checks, tmpdir

import _perf

c = Checks("PRDRIVE_PERF: ventanas de host (asistente y pregunta del agente)")

import ui  # noqa: E402 — `ui` antes que `tkinter`: su `__init__` carga el Tk con Xft del runtime
from common import equipo  # noqa: E402

try:
    import tkinter as tk
    _sonda = tk.Tk()
    _sonda.destroy()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from install import device  # noqa: E402
from ui import theme, tk_agente, tk_install  # noqa: E402

# El paso «Dispositivo» miraría las unidades de verdad: aquí no hay ninguna que mirar.
device.list_volumes = lambda *a, **k: []


def bombear(self, n: int = 0) -> None:
    """Hace de `mainloop`: despacha lo pendiente y cierra la ventana, sin esperar a nadie.

    Las marcas van en `after_idle` y se despachan aquí. Las cuentas atrás que queden
    pendientes se cancelan, para que no disparen cuando otro bloque de la prueba
    vuelva a bombear el mismo intérprete.
    """
    self.update()
    for pendiente in self.tk.splitlist(self.tk.call("after", "info")):
        self.after_cancel(pendiente)
    self.destroy()


@contextmanager
def bucle_de_prueba():
    """Cambia el `mainloop` de Tk por `bombear` mientras dura el bloque."""
    original = tk.Misc.mainloop
    tk.Misc.mainloop = bombear
    try:
        yield
    finally:
        tk.Misc.mainloop = original


TOLERANCIA_MS = 50.0
"""Margen de las cotas de `perf_desde_inicio()`: su reloj tiene centésimas de segundo en Linux y el tick de creación en Windows."""


def ms_de(linea: str) -> float:
    """Devuelve los milisegundos de una línea de `perf.log`: `<fecha> <hora> <momento> <ms> ms vez=N`."""
    return float(linea.split(" ", 3)[3].split()[0])


def entre_edades(ms: float, antes: float | None, despues: float | None) -> bool:
    """Dice si la duración de un `start-*` cae entre dos lecturas de la edad del proceso.

    Un `start-*` cuenta desde que se creó el proceso hasta que la ventana pinta: no
    puede ser menor que la edad leída antes de la llamada, ni mayor que la leída
    después, salvo el margen `TOLERANCIA_MS`.

    Args:
        ms: La duración que anotó la marca.
        antes: La edad del proceso leída justo antes de la llamada; `None` no cuenta como cota.
        despues: La edad del proceso leída justo después; `None` no cuenta como cota.
    """
    if antes is None or despues is None:
        return False
    return antes - TOLERANCIA_MS <= ms <= despues + TOLERANCIA_MS


def marcas(ruta: Path, momento: str) -> list[str]:
    """Devuelve las líneas de un diario cuyo momento es `momento`; `[]` si no hay diario."""
    if not ruta.is_file():
        return []
    return [linea for linea in ruta.read_text(encoding="utf-8").splitlines()
            if linea.split(" ", 3)[2:3] == [momento]]


def correr_pregunta(medida: bool) -> tuple[int, Path, float]:
    """Corre `pregunta.py` como lo lanza el agente y devuelve su código, su diario del equipo y su tiempo de pared.

    El hijo recibe una carpeta propia para sus datos (`LOCALAPPDATA` y `XDG_DATA_HOME`),
    nueva en cada llamada. En Windows `equipo.dir_equipo()` sale de `%LOCALAPPDATA%`, que
    el harness no redirige: sin esto el hijo escribiría en el agente real de quien corre
    la prueba, y la segunda llamada encontraría el diario de la primera.

    Args:
        medida: Si `PRDRIVE_PERF` va puesta en el entorno del hijo.

    Returns:
        El código de salida; el diario del equipo del hijo; y los milisegundos que tardó
        el proceso medidos alrededor de `subprocess.run`, que son una cota superior de su edad.
    """
    casa = tmpdir("prdrive-pregunta-")
    entorno = dict(os.environ)
    entorno.pop("PRDRIVE_PERF", None)
    entorno["LOCALAPPDATA"] = str(casa / "local")
    entorno["XDG_DATA_HOME"] = str(casa / "xdg")
    if medida:
        entorno["PRDRIVE_PERF"] = "1"
    inicio = time.perf_counter()
    proc = subprocess.run([sys.executable, str(REPO / "pregunta.py"), "--nombre", "A",
                           "--segundos", "1"], env=entorno, cwd=str(REPO),
                          stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
    pared = (time.perf_counter() - inicio) * 1000
    # La carpeta del equipo del hijo es la de su variable de este sistema, dentro de `casa`.
    base = casa / ("local" if equipo.IS_WIN else "xdg")
    return proc.returncode, base / equipo.APP_NAME / "perf.log", pared


TMP = tmpdir("prdrive-perf-anfitrion-")

# 1. Apagada: ni el asistente ni la pregunta escriben nada, ni crean la carpeta del equipo.
theme._apply_medido = False
with _perf.con_perf(TMP / "apagada", activo=False) as t:
    raiz = tk.Tk()
    raiz.withdraw()
    wiz = tk_install.build(raiz)
    wiz.ir(+1)
    raiz.update()
    raiz.destroy()
    with bucle_de_prueba():
        tk_agente.preguntar("PRDRIVE-2", 1)
    _perf.vaciar()
    c("apagada: el asistente y la pregunta no escriben diario ni crean la carpeta del equipo",
      ((t / "equipo" / "perf.log").exists(), (t / "logs" / "perf.log").exists(),
       (t / "equipo").exists()), (False, False, False))

# 2. El asistente como lo abre el lanzador: `run_wizard()` marca su arranque y su apply en el equipo.
theme._apply_medido = False
with _perf.con_perf(TMP / "asistente") as t:
    c("antes de abrir el asistente, la carpeta del equipo no existe", (t / "equipo").exists(), False)
    antes = ui.perf_desde_inicio()
    with bucle_de_prueba():
        rc = tk_install.run_wizard()
    despues = ui.perf_desde_inicio()
    ui.perf_quien = "main"          # `run_wizard()` lo deja en «wizard»: el resto vuelve a «main»
    _perf.vaciar()
    c("run_wizard devuelve 0", rc, 0)
    arranque = marcas(t / "equipo" / "perf.log", "start-wizard")
    c("start-wizard: una marca en el equipo, entre la edad del proceso antes y después de abrirlo",
      (len(arranque), bool(arranque) and entre_edades(ms_de(arranque[0]), antes, despues)),
      (1, True))
    c("apply-wizard (no apply-main): una marca en el equipo",
      (len(_perf.lineas(t, "apply-wizard", host=True)), len(_perf.lineas(t, "apply-main"))),
      (1, 0))
    c("el dispositivo no recibe ninguna marca del asistente",
      (len(_perf.lineas(t, "start-wizard")), len(_perf.lineas(t, "apply-wizard"))), (0, 0))
    c("la carpeta del equipo la crea la primera marca; el diario del dispositivo no existe",
      ((t / "equipo").is_dir(), (t / "logs" / "perf.log").exists()), (True, False))

# 3. La pregunta del agente, en proceso: `start-agente` y `apply-agente` van al equipo.
theme._apply_medido = False
ui.perf_quien = "agente"
try:
    with _perf.con_perf(TMP / "agente") as t:
        antes = ui.perf_desde_inicio()
        with bucle_de_prueba():
            tk_agente.preguntar("PRDRIVE-2", 1)
        despues = ui.perf_desde_inicio()
        _perf.vaciar()
        arranque = _perf.lineas(t, "start-agente", host=True)
        c("start-agente: una marca en el equipo, entre la edad del proceso antes y después de preguntar",
          (len(arranque), bool(arranque) and entre_edades(ms_de(arranque[0]), antes, despues)),
          (1, True))
        c("apply-agente: una marca en el equipo, y ninguna en el dispositivo",
          (len(_perf.lineas(t, "apply-agente", host=True)), len(_perf.lineas(t, "apply-agente"))),
          (1, 0))
finally:
    ui.perf_quien = "main"

# 4. `pregunta.py` en su propio proceso, como lo lanza el agente: lo mismo, y sin la medida, nada.
_codigo_sin, diario_sin, _pared_sin = correr_pregunta(medida=False)
c("pregunta.py sin PRDRIVE_PERF no escribe diario del equipo", diario_sin.exists(), False)
codigo, diario, pared = correr_pregunta(medida=True)
c("pregunta.py con la medida sale con «Ahora no» (1) al acabarse la cuenta atrás",
  codigo, tk_agente.AHORA_NO)
c("pregunta.py: apply-agente y start-agente, una vez cada uno, en el diario del equipo",
  (len(marcas(diario, "apply-agente")), len(marcas(diario, "start-agente"))), (1, 1))
# Solo cota superior: el proceso no puede llevar más vivo que lo que duró la llamada.
# La inferior la pone la prueba en proceso, que corre la misma línea.
arranque_hijo = marcas(diario, "start-agente")
c("pregunta.py: start-agente no pasa del tiempo de pared del proceso",
  bool(arranque_hijo) and ms_de(arranque_hijo[0]) <= pared + TOLERANCIA_MS, True)

# 5. Los pasos del asistente: cada «Siguiente» o «Atrás» anota el paso al que llega.
ui.perf_quien = "wizard"
try:
    with _perf.con_perf(TMP / "pasos") as t:
        raiz = tk.Tk()
        raiz.withdraw()
        try:
            wiz = tk_install.build(raiz)
            raiz.update()
            _perf.vaciar()
            c("el primer paso no tiene marca propia (lo cuenta start-wizard) y no crea el equipo",
              (len(_perf.lineas(t, "paso-donde", host=True)), (t / "equipo").exists()), (0, False))
            wiz.ir(+1)
            raiz.update()
            _perf.vaciar()
            c("«Siguiente» a «Dispositivo»: paso-dispositivo una vez, en el equipo y no en el dispositivo",
              (len(_perf.lineas(t, "paso-dispositivo", host=True)),
               len(_perf.lineas(t, "paso-dispositivo"))), (1, 0))
            c("  y esa marca crea la carpeta del equipo", (t / "equipo").is_dir(), True)
            wiz.ir(+1)
            raiz.update()
            _perf.vaciar()
            c("«Siguiente» a «Cifrado»: paso-cifrado una vez",
              len(_perf.lineas(t, "paso-cifrado", host=True)), 1)
            wiz.ir(-1)
            raiz.update()
            _perf.vaciar()
            segunda = _perf.lineas(t, "paso-dispositivo", host=True)
            c("«Atrás» vuelve a contar: paso-dispositivo llega a dos, la segunda con vez=2",
              (len(segunda), bool(segunda) and segunda[-1].endswith(" vez=2")), (2, True))
            c("el nombre del paso quita tildes y une las palabras con guiones",
              (tk_install.momento_del_paso("¿Dónde?"),
               tk_install.momento_del_paso("Parejas y configuración")),
              ("paso-donde", "paso-parejas-y-configuracion"))
        finally:
            raiz.destroy()
finally:
    ui.perf_quien = "main"

raise SystemExit(c.report())
