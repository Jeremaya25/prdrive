#!/usr/bin/env python3
"""
Las plataformas del dispositivo: cuál es este equipo, qué lleva ya el
dispositivo, y la lista que se marca en el paso de instalación.

Todo sin Tk: la ventana solo pinta lo que decide `install/platforms.py`, igual
que `tk_pairs` pinta lo que decide `pair_editor`. Lo que se vigila aquí es sobre
todo lo que puede borrar: quitar de la lista una plataforma que el dispositivo ya
lleva no borra nada por sí solo —hay que confirmarlo—, y lo que no se confirma
se queda donde está.
"""

import sys

from _harness import Checks, tmpdir

from common import model, pins
from install import deploy, platforms, runtime_bin

c = Checks("instalador: las plataformas del dispositivo")

WIN, WARM = pins.plataforma("windows-x64"), pins.plataforma("windows-arm64")
LIN, LARM = pins.plataforma("linux-x64"), pins.plataforma("linux-arm64")

# --- qué plataforma es este equipo --------------------------------------------
c("sistema + arch_dir -> plataforma", pins.plataforma_para("windows", "arm"), WARM)
c("Linux x64", pins.plataforma_para("linux", "x64"), LIN)
c("macOS no es ninguna", pins.plataforma_para("darwin", "arm"), None)

sonda = model.maquina_nativa_windows
try:
    if model.os.name == "nt":
        # El caso de siempre: el instalador es un .exe x64 emulado en un ARM64, y
        # solo IsWow64Process2 dice la verdad. La plataforma sale de ahí.
        model.maquina_nativa_windows = lambda: 0xAA64
        c("un Windows ARM64 es windows-arm64 aunque el proceso sea x64",
          platforms.host(), WARM)
        model.maquina_nativa_windows = lambda: 0x8664
        c("y un x64, windows-x64", platforms.host(), WIN)
finally:
    model.maquina_nativa_windows = sonda

# --- en qué orden se prueba cada runtime ---------------------------------------
# El mismo orden que el runsync.bat: un ARM64 prefiere el suyo, pero ejecuta el
# x64 emulado; al revés no.
c("un ARM64 de Windows prueba el suyo y luego el x64",
  platforms.candidates(WARM), [WARM, WIN])
c("un x64 solo el suyo", platforms.candidates(WIN), [WIN])
c("Linux no emula: solo el suyo", platforms.candidates(LARM), [LARM])


# --- qué lleva ya un dispositivo ------------------------------------------------
def poner_rclone(raiz, plat):
    ruta = deploy.app_dir(raiz) / "bin" / plat.bin_dir / plat.rclone_exe
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(b"rclone")


def poner_runtime(raiz, plat, sello=True):
    d = platforms.runtime_dir(raiz, plat)
    (d / plat.interprete).parent.mkdir(parents=True, exist_ok=True)
    (d / plat.interprete).write_bytes(b"py")
    (d / plat.interprete_consola).write_bytes(b"py")
    if sello:
        (d / runtime_bin.STAMP).write_text(runtime_bin.stamp_text(plat, "s"),
                                           encoding="utf-8")


raiz = tmpdir()
c("un dispositivo vacío no lleva nada", platforms.provisioned(raiz), {})

poner_rclone(raiz, WIN)
poner_runtime(raiz, WIN)
poner_rclone(raiz, LIN)                 # comparte bin/x64 con Windows, sin chocar
poner_runtime(raiz, LARM, sello=False)  # a medias: sin sello no cuenta
lleva = platforms.provisioned(raiz)
c("Windows x64: rclone y Python", lleva.get("windows-x64"),
  platforms.Instalada(rclone=True, runtime=True))
c("Linux x64: solo rclone, aunque viva en el mismo bin/x64",
  lleva.get("linux-x64"), platforms.Instalada(rclone=True, runtime=False))
c("un runtime sin sello no cuenta como instalado", "linux-arm64" in lleva, False)
c("el sello se lee", platforms.runtime_stamp(raiz, WIN),
  runtime_bin.stamp_text(WIN, "s"))

# --- qué intérprete usaría este equipo -------------------------------------------
c("el del dispositivo para su plataforma, sin consola",
  platforms.device_interpreter(raiz, WIN),
  platforms.runtime_dir(raiz, WIN) / "pythonw.exe")
c("con consola cuando alguien lee la salida",
  platforms.device_interpreter(raiz, WIN, consola=True),
  platforms.runtime_dir(raiz, WIN) / "python.exe")
c("un ARM64 sin el suyo usa el x64, como el .bat",
  platforms.device_interpreter(raiz, WARM),
  platforms.runtime_dir(raiz, WIN) / "pythonw.exe")
c("Linux ARM64 a medias: ninguno", platforms.device_interpreter(raiz, LARM), None)
c("sin plataforma conocida (macOS): ninguno",
  platforms.device_interpreter(raiz, None), None)

# --- la lista del paso de instalación ----------------------------------------------
nueva = platforms.Matriz.para(tmpdir(), anfitrion=WIN)
c("en un dispositivo nuevo, este equipo viene marcado", nueva.elegidas, {"windows-x64"})
c("y la instalación completa", nueva.completa, True)
c("hay una fila por plataforma, en orden",
  [f.plataforma.clave for f in nueva.filas()], [p.clave for p in pins.PLATAFORMAS])
c("la fila de este equipo lo dice",
  [f.plataforma.clave for f in nueva.filas() if f.anfitrion], ["windows-x64"])
c("el total es rclone + Python de lo marcado",
  nueva.total_mb(), WIN.mb_rclone + WIN.mb_python)

nueva.elegir("linux-x64")
c("marcar otra suma la suya", nueva.total_mb(),
  WIN.mb_rclone + WIN.mb_python + LIN.mb_rclone + LIN.mb_python)

# La ligera no lleva Python: la columna se apaga y deja de contar.
nueva.completa = False
c("en la ligera el Python no cuenta", nueva.total_mb(), WIN.mb_rclone + LIN.mb_rclone)
c("y sus filas lo dicen con un cero",
  {f.plataforma.clave: f.mb_python for f in nueva.filas() if f.elegida},
  {"windows-x64": 0, "linux-x64": 0})
plan = nueva.plan()
c("el plan de la ligera instala rclone", [p.clave for p in plan.rclone],
  ["windows-x64", "linux-x64"])
c("y ningún Python", plan.runtime, [])
c.contains("y dice que cada equipo necesitará su Python",
           " ".join(plan.consecuencias()), "Python 3.11")

nueva.completa = True
plan = nueva.plan()
c("el de la completa, también Python", [p.clave for p in plan.runtime],
  ["windows-x64", "linux-x64"])
c("un dispositivo nuevo no borra nada", plan.borrar, [])

# Quitar algo que el dispositivo NO lleva es solo desmarcarlo.
c("quitar una plataforma que no está no pide confirmación",
  nueva.quitar("linux-x64"), False)
c("y deja de estar marcada", "linux-x64" in nueva.elegidas, False)

# --- quitar lo que el dispositivo YA lleva: borrar se confirma ---------------------
usado = platforms.Matriz.para(raiz, anfitrion=WIN)
c("en un dispositivo usado vienen marcadas este equipo y lo que ya lleva",
  usado.elegidas, {"windows-x64", "linux-x64"})
c("quitar una que ya lleva pide confirmación", usado.quitar("linux-x64"), True)
c("y hasta que se confirme no se borra nada", usado.plan().borrar, [])

usado.confirmar_borrado("linux-x64", False)
c("decir que no deja los binarios donde están", usado.plan().borrar, [])
c("sin volver a instalarlos", [p.clave for p in usado.plan().rclone], ["windows-x64"])

usado.quitar("linux-x64")
usado.confirmar_borrado("linux-x64", True)
c("decir que sí la manda borrar", [p.clave for p in usado.plan().borrar], ["linux-x64"])
c.contains("y la consecuencia lo dice en voz alta",
           " ".join(usado.plan().consecuencias()), "Linux x64")
c("la fila lo marca", [f.se_borra for f in usado.filas()
                       if f.plataforma.clave == "linux-x64"], [True])

usado.elegir("linux-x64")
c("volver a marcarla anula el borrado", usado.plan().borrar, [])

# --- avisos ------------------------------------------------------------------------
sin_nada = platforms.Matriz.para(tmpdir(), anfitrion=WIN)
sin_nada.quitar("windows-x64")
c("sin ninguna marcada no se puede instalar", sin_nada.listo, False)
c.contains("y se dice por qué", " ".join(sin_nada.avisos()), "al menos una")

solo_linux = platforms.Matriz.para(tmpdir(), anfitrion=WIN)
solo_linux.elegir("linux-x64")
solo_linux.quitar("windows-x64")
c("se puede preparar un dispositivo solo para otros equipos", solo_linux.listo, True)
c.contains("pero se avisa de que este no podrá usarlo",
           " ".join(solo_linux.avisos()), "Windows x64")

justo = platforms.Matriz.para(tmpdir(), anfitrion=WIN)
c("con sitio de sobra no hay aviso de espacio",
  any("libre" in a for a in justo.avisos(libre=10 * 2 ** 30)), False)
c.contains("sin sitio, se avisa",
           " ".join(justo.avisos(libre=10 * 2 ** 20)), "libre")
# Lo que ya está en el dispositivo no vuelve a ocupar.
ya = platforms.Matriz.para(raiz, anfitrion=WIN)
c("lo que ya lleva no cuenta como nuevo: solo falta el Python de Linux x64",
  ya.nuevo_mb(), LIN.mb_python)

sys.exit(c.report())
