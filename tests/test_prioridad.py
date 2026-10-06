#!/usr/bin/env python3
"""Las pasadas que nadie mira van con prioridad baja, y su rclone también.

Se prueba de verdad en el sistema donde corre: en Linux, el `nice` y la
prioridad de E/S de un proceso y de su nieto (el rclone de la pasada hereda
la del `sync.py` que lo lanza); en Windows, la clase de prioridad. Y con el
agente de mentira, que sus pasadas la piden: en Windows al crearlas, en Linux
nada más lanzarlas.
"""

from __future__ import annotations

import os
import subprocess
import sys

from _harness import REPO, Checks, tmpdir

import _agente_falso as F
import agente
from common import equipo, prioridad

c = Checks("prioridad de las pasadas desatendidas (common/prioridad.py)")

DORMIR = [sys.executable, "-c", "import time; time.sleep(60)"]


def dormido() -> subprocess.Popen:
    """Lanza un proceso que solo espera; el test lo mata al acabar."""
    flags = 0x08000000 if os.name == "nt" else 0    # CREATE_NO_WINDOW
    return subprocess.Popen(DORMIR, creationflags=flags)


def pid_muerto() -> int:
    """Devuelve el pid de un proceso que ya ha acabado."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


c("un pid que no existe: no lanza y dice que no", prioridad.bajar(pid_muerto()), False)

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.GetPriorityClass.argtypes = (wintypes.HANDLE,)
    k32.GetPriorityClass.restype = wintypes.DWORD
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)

    def clase(pid: int) -> int:
        """Devuelve la clase de prioridad de ese proceso (0 si no se lee)."""
        h = k32.OpenProcess(0x1000, False, pid)     # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return 0
        try:
            return k32.GetPriorityClass(h)
        finally:
            k32.CloseHandle(h)

    hijo = dormido()
    try:
        c("Windows: bajar(pid) le pone BELOW_NORMAL a otro proceso",
          (prioridad.bajar(hijo.pid), clase(hijo.pid)), (True, prioridad.CLASE_WINDOWS))
    finally:
        hijo.kill()
        hijo.wait()

    NIETO = ("import ctypes, sys, subprocess; "
             "from common import prioridad; prioridad.bajar(); "
             "codigo = ('import ctypes; k = ctypes.windll.kernel32; '"
             "          'k.GetCurrentProcess.restype = ctypes.c_void_p; '"
             "          'k.GetPriorityClass.argtypes = (ctypes.c_void_p,); '"
             "          'print(k.GetPriorityClass(k.GetCurrentProcess()))'); "
             "print(subprocess.run([sys.executable, '-c', codigo], capture_output=True, "
             "text=True, creationflags=0x08000000).stdout.strip())")
    salida = subprocess.run([sys.executable, "-c", NIETO], cwd=REPO, capture_output=True,
                            text=True, creationflags=0x08000000)
    c("Windows: bajar() sin pid baja al que llama y su hijo la hereda (el rclone de "
      "la pasada)", salida.stdout.strip(), str(prioridad.CLASE_WINDOWS))
    print("  (saltado) Linux: nice e ioprio, en un Linux")
else:
    def nice(pid: int) -> int:
        """Devuelve el `nice` del hilo principal de ese proceso."""
        return os.getpriority(os.PRIO_PROCESS, pid)

    hijo = dormido()
    try:
        c("Linux: bajar(pid) le pone nice 10 y E/S «best effort» al nivel 7",
          (prioridad.bajar(hijo.pid), nice(hijo.pid), prioridad.leer_ioprio(hijo.pid)),
          (True, prioridad.NICE, (prioridad.IOPRIO_CLASE_BE, prioridad.IOPRIO_NIVEL)))
    finally:
        hijo.kill()
        hijo.wait()

    hijo = dormido()
    try:
        os.setpriority(os.PRIO_PROCESS, hijo.pid, 15)
        prioridad.bajar(hijo.pid)
        c("  nunca la sube: un nice 15 se queda en 15", nice(hijo.pid), 15)
    finally:
        hijo.kill()
        hijo.wait()

    if prioridad.leer_ioprio(os.getpid()) is not None:
        hijo = dormido()
        try:
            prioridad._poner_ioprio(hijo.pid, prioridad.IOPRIO_CLASE_IDLE, 0)
            prioridad.bajar(hijo.pid)
            c("  ni le quita la E/S «idle» a quien ya la tiene",
              prioridad.leer_ioprio(hijo.pid)[0], prioridad.IOPRIO_CLASE_IDLE)
        finally:
            hijo.kill()
            hijo.wait()
    else:
        print("  (saltado) ioprio: esta CPU no está en la tabla de llamadas")

    NIETO = ("import os, sys, subprocess; "
             "from common import prioridad; prioridad.bajar(); "
             "codigo = ('import os; from common import prioridad; '"
             "          'print(os.getpriority(os.PRIO_PROCESS, 0), prioridad.leer_ioprio(0))'); "
             "print(subprocess.run([sys.executable, '-c', codigo], capture_output=True, "
             "text=True).stdout.strip())")
    salida = subprocess.run([sys.executable, "-c", NIETO], cwd=REPO, capture_output=True,
                            text=True)
    c("Linux: bajar() sin pid baja al que llama y su hijo lo hereda (el rclone de la "
      "pasada)", salida.stdout.strip(),
      f"{prioridad.NICE} ({prioridad.IOPRIO_CLASE_BE}, {prioridad.IOPRIO_NIVEL})")
    print("  (saltado) Windows: la clase de prioridad, en un Windows")


# El agente: sus pasadas la piden, en Windows al crearlas y en POSIX nada más
# lanzarlas (un sync.py tarda más de 0,1 s en llegar a lanzar su rclone).
class ConPid(F.Proc):
    """Un proceso de mentira con pid, como los de verdad."""

    def __init__(self, args, **kwargs):
        """Lo apunta como `F.Proc` y le da un pid que no es de nadie."""
        super().__init__(args, **kwargs)
        self.pid = 4_000_000 + len(F.LANZADOS)


def una_pasada(es_windows: bool) -> tuple[F.Proc, list[int]]:
    """Conecta una unidad de mentira en modo daemon y devuelve su primera pasada."""
    F.preparar()
    agente.IS_WIN = es_windows
    bajadas: list[int] = []
    agente.bajar_prioridad = bajadas.append
    agente.lanzar = lambda args, **kw: ConPid(args, **kw)
    F.LANZADOS.clear()
    F.RAICES.clear()
    uid = ("w" if es_windows else "l") * 32
    raiz = F.unidad(uid, parejas=("notas",))
    F.RAICES.append(raiz)
    equipo.guardar_ajustes(equipo.Ajustes().con_unidad(
        equipo.Unidad(uid, equipo.DAEMON, "Prioridad")))
    F.vueltas(F.nuevo(), 4)
    pasadas = F.pasadas(raiz)
    return (pasadas[0] if pasadas else None), bajadas


ES_WIN = agente.IS_WIN
try:
    pasada, bajadas = una_pasada(es_windows=False)
    c("agente en POSIX: lanza la pasada", pasada is not None, True)
    c("  y nada más lanzarla le baja la prioridad", bajadas, [pasada.pid] if pasada else [])
    c("  sin clase de prioridad de Windows al crearla",
      bool(pasada and pasada.kwargs.get("creationflags", 0) & prioridad.CLASE_WINDOWS), False)

    pasada, bajadas = una_pasada(es_windows=True)
    c("agente en Windows: la pasada se crea con BELOW_NORMAL (la hereda su rclone)",
      bool(pasada and pasada.kwargs.get("creationflags", 0) & prioridad.CLASE_WINDOWS), True)
    c("  sin bajarla después", bajadas, [])
finally:
    agente.IS_WIN = ES_WIN


# El servicio de runsync y su `--auto --once` se bajan a sí mismos antes de
# lanzar nada: sus `sync.py` y sus rclone la heredan.
import runsync  # noqa: E402

pedidas: list = []
diario: list[str] = []
BAJAR_REAL = runsync.prioridad.bajar
CWD = os.getcwd()
carpeta = tmpdir("prdrive-prioridad-")
runsync.prioridad.bajar = lambda pid=None: pedidas.append(pid) or True
runsync.dlog = diario.append
runsync.LOCK = carpeta / "daemon.lock.json"
runsync.STOP = carpeta / "daemon.stop"
runsync.pareja_llavero = lambda: None
try:
    runsync.pen_present = lambda: False
    c("servicio: arranca y, sin dispositivo, para", runsync.daemon_main(["docs"], 30), 0)
    c("  bajando antes su propia prioridad", pedidas, [None])

    pedidas.clear()
    runsync.servicio_en_marcha = lambda: None
    lanzadas: list = []
    runsync.run_interactive = lambda parejas: lanzadas.append((list(parejas), list(pedidas))) or 0
    runsync.una_pasada(["docs"])
    c("--auto --once: se baja antes de lanzar la pasada", lanzadas, [(["docs"], [None])])
finally:
    runsync.prioridad.bajar = BAJAR_REAL
    os.chdir(CWD)

sys.exit(c.report())
