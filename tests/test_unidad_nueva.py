#!/usr/bin/env python3
"""«Se ha conectado PRDRIVE-2. ¿Atenderla en este equipo?»

Una unidad cuyo id no está en la lista del agente nunca se sincroniza sin
preguntar. Se comprueba que:
- Sin respuesta en `espera_unidad_nueva` cuenta como «Ahora no».
- «Ahora no» dura hasta que la raíz desaparece, y se vuelve a preguntar al
  reaparecer.
- Una respuesta tardía de la ventana se ignora.
- El «Atender» de la bandeja (el buzón) funciona mientras sigue conectada.
- Sin entorno gráfico es «Ahora no» al momento.
- «Atender» la añade en modo daemon y la atiende.
- Y, sobre todo, que **antes del sí no se lanza ningún proceso con rutas de la
  unidad**.

Y la ventanita (`ui/tk_agente.py`), si hay Tk y pantalla, y su entrada pequeña
(`pregunta.py`): la orden que la lanza, la que vuelve a `agente.py pregunta` si
falta, cómo lee su línea y que sale con los mismos códigos que `agente.py`.
"""

import os
import subprocess
import sys

from _harness import REPO, Checks, tmpdir

import _agente_falso as F
import agente
from common import equipo, planificador as pl

c = Checks("agente: una unidad nueva")
F.preparar()

UID = "1" * 32
RAIZ = F.unidad(UID, nombre="PRDRIVE-2")
F.RAICES[:] = [RAIZ]
equipo.guardar_ajustes(equipo.Ajustes(espera_unidad_nueva=120))


def con_rutas_de_la_unidad() -> list:
    """Devuelve los procesos lanzados que llevan rutas de la unidad."""
    return [p.args for p in F.LANZADOS if any(str(RAIZ) in a for a in p.args)
            or str(RAIZ) in str(p.kwargs.get("cwd", ""))]


preguntas = F.preguntas


ag = F.nuevo()
F.vueltas(ag, 2)
c("una unidad que no está en la lista: se avisa", F.AVISOS[-1],
  ("Se ha conectado PRDRIVE-2", "¿Atenderla en este equipo?"))
c("  y se abre la pregunta", len(preguntas()), 1)
q = preguntas()[0]
c("  con su nombre y el plazo", q.args[-4:], ["--nombre", "PRDRIVE-2", "--segundos", "120"])
c("  como un hijo suelto del agente (no carga Tk): pregunta.py, no agente.py",
  q.args[1], str(agente.SCRIPT_DIR / "pregunta.py"))
c("  sin ninguna ruta de la unidad", con_rutas_de_la_unidad(), [])
F.vueltas(ag, 5)
c("mientras se espera, nada: ni lock", F.lock(RAIZ), {})
c("  ni procesos de la unidad", con_rutas_de_la_unidad(), [])

F.pasar(120)
F.vueltas(ag, 1)
c("sin respuesta en el plazo: «Ahora no»", ag.conexiones[UID].respuesta, pl.AHORA_NO)
c("  la ventana, si seguía, se cierra", q.terminado, True)
c("  y la unidad no entra en la lista", UID in equipo.leer_ajustes().unidades, False)
F.vueltas(ag, 10, cada=60)
c("«Ahora no» vale mientras siga conectada: no se vuelve a preguntar",
  len(preguntas()), 1)
c("  y sigue sin ejecutarse nada suyo", con_rutas_de_la_unidad(), [])

F.RAICES[:] = []
F.vueltas(ag, 1)
F.RAICES[:] = [RAIZ]
F.vueltas(ag, 2)
c("al desenchufarla y volver, se pregunta otra vez", len(preguntas()), 2)

# Respuesta tardía: la ventana contesta «Atender» después del plazo.
F.pasar(121)
preguntas()[-1].rc = 0
F.vueltas(ag, 1)
c("una respuesta que llega tarde no cuenta", ag.conexiones[UID].respuesta, pl.AHORA_NO)
c("  ni se añade a la lista", UID in equipo.leer_ajustes().unidades, False)

# «Atender» desde la bandeja, mientras sigue conectada.
equipo.pedir({"pide": equipo.PIDE_ATENDER, "id": UID})
F.vueltas(ag, 1)
c("el «Atender» de la bandeja la añade a la lista, con la huella de su código",
  equipo.leer_ajustes().unidades.get(UID),
  equipo.Unidad(UID, equipo.DAEMON, "PRDRIVE-2", codigo=agente.huella(RAIZ)))
F.vueltas(ag, 1)
c("  y la atiende enseguida", F.lock(RAIZ).get("pid"), os.getpid())
c("  ahora sí con sus rutas: su sync.py", len(F.pasadas(RAIZ)), 1)

# «Atender» en la ventana, a tiempo.
DOS = "2" * 32
R2 = F.unidad(DOS, nombre="Azul")
F.RAICES[:] = [R2]
ag = F.nuevo()
F.vueltas(ag, 2)
F.pasar(30)
preguntas()[-1].rc = 0                  # tk_agente.ATENDER
F.vueltas(ag, 1)
c("«Atender» a tiempo: en la lista, en modo daemon",
  equipo.leer_ajustes().unidades[DOS].modo, equipo.DAEMON)
F.vueltas(ag, 1)
c("  y atendida", F.lock(R2).get("pid"), os.getpid())

# «Ahora no» en la ventana.
TRES = "3" * 32
R3 = F.unidad(TRES)
F.RAICES[:] = [R3]
ag = F.nuevo()
F.vueltas(ag, 2)
preguntas()[-1].rc = 1                  # tk_agente.AHORA_NO
F.vueltas(ag, 1)
c("«Ahora no» en la ventana", ag.conexiones[TRES].respuesta, pl.AHORA_NO)
c("  sin nombre en la flota, se la llama por su id",
  ag.conexiones[TRES].nombre, "PRDRIVE 33333333")

# La ventana que no se puede abrir (sin Tk): «Ahora no» al momento.
CUATRO = "4" * 32
R4 = F.unidad(CUATRO)
F.RAICES[:] = [R4]
ag = F.nuevo()
F.vueltas(ag, 2)
preguntas()[-1].rc = 2                  # tk_agente.SIN_VENTANA
F.vueltas(ag, 1)
c("si la ventanita no ha podido abrirse, «Ahora no»",
  ag.conexiones[CUATRO].respuesta, pl.AHORA_NO)

# Sin entorno gráfico.
CINCO = "5" * 32
R5 = F.unidad(CINCO)
F.RAICES[:] = [R5]
F.PANTALLA[0] = False
antes = len(preguntas())
ag = F.nuevo()
F.vueltas(ag, 2)
c("sin entorno gráfico: «Ahora no» al momento", ag.conexiones[CINCO].respuesta,
  pl.AHORA_NO)
c("  sin intentar abrir la pregunta", len(preguntas()), antes)
c("  y el diario dice cómo atenderla", any(f"agente.py atender {CINCO}" in d
                                          for d in F.DIARIO), True)
F.PANTALLA[0] = True

c("ninguna unidad sin aceptar ha visto un proceso con sus rutas",
  [a for p in F.LANZADOS for a in p.args
   if any(str(r) in a for r in (R3, R4, R5))], [])


# la orden que abre la ventanita
PYTHON = agente.python(ventana=True)
c("la orden: pregunta.py, sin cargar el agente",
  agente.orden_pregunta("PRDRIVE-2", 120, False),
  [PYTHON, str(agente.SCRIPT_DIR / "pregunta.py"), "--nombre", "PRDRIVE-2", "--segundos", "120"])
c("  con --cambiada al final si el código ha cambiado",
  agente.orden_pregunta("PRDRIVE-2", 120, True)[-1], "--cambiada")
c("  y el plazo siempre entero", agente.orden_pregunta("A", 90.7, False)[-1], "90")
REAL_SCRIPT_DIR = agente.SCRIPT_DIR
SIN = tmpdir("prdrive-sin-pregunta-")
agente.SCRIPT_DIR = SIN
try:
    c("sin pregunta.py al lado, vuelve a agente.py pregunta",
      agente.orden_pregunta("PRDRIVE-2", 120, True),
      [PYTHON, str(SIN / "agente.py"), "pregunta", "--nombre", "PRDRIVE-2", "--segundos", "120",
       "--cambiada"])
finally:
    agente.SCRIPT_DIR = REAL_SCRIPT_DIR

# su entrada pequeña
import pregunta  # noqa: E402

c("pregunta.py lee su línea", pregunta.leer(["--nombre", "A", "--segundos", "30"]),
  ("A", 30, False))
c("  y --cambiada, estén donde estén", pregunta.leer(["--cambiada", "--segundos", "5", "--nombre", "B"]),
  ("B", 5, True))
c("  sin nombre, sin plazo o con un plazo que no es un número, no cuadra",
  [pregunta.leer(a) for a in (["--segundos", "30"], ["--nombre", "A"], ["--nombre"],
                              ["--nombre", "A", "--segundos", "x"], [])],
  [None] * 5)


def sale_con(*argv: str, sin_pantalla: bool = False) -> int:
    """Corre la entrada de verdad, en su propio proceso, y devuelve su código de salida."""
    entorno = dict(os.environ)
    if sin_pantalla:
        for clave in ("DISPLAY", "WAYLAND_DISPLAY"):
            entorno.pop(clave, None)
    return subprocess.run([sys.executable, str(REPO / argv[0]), *argv[1:]], env=entorno,
                          stdin=subprocess.DEVNULL, capture_output=True, timeout=60).returncode


c("sin argumentos sale con 2 («no se ha podido abrir»), como `agente.py pregunta` mal llamado",
  sale_con("pregunta.py"), 2)
if os.name != "nt":
    c("sin pantalla sale con 2", sale_con("pregunta.py", "--nombre", "A", "--segundos", "1",
                                          sin_pantalla=True), 2)
    c("  igual que agente.py pregunta", sale_con("agente.py", "pregunta", "--nombre", "A",
                                                "--segundos", "1", sin_pantalla=True), 2)


# la ventanita
from ui import tk_agente  # noqa: E402

# `agente.py pregunta` sigue ahí, para cuando falta pregunta.py: hace lo mismo y sale con su código
vistas: list = []
tk_agente_main = tk_agente.main
tk_agente.main = lambda nombre, segundos, cambiada=False: vistas.append(
    (nombre, segundos, cambiada)) or tk_agente.AHORA_NO
try:
    c("agente.py pregunta abre la misma ventanita con lo que se le dice y sale con su código",
      (agente.main(["pregunta", "--nombre", "A", "--segundos", "30", "--cambiada"]), vistas),
      (tk_agente.AHORA_NO, [("A", 30, True)]))
finally:
    tk_agente.main = tk_agente_main

c("la cuenta atrás en minutos y segundos", tk_agente.cuenta(105),
  "Si no contestas, en 1:45 se cierra sola y cuenta como «Ahora no».")
c("  sin números negativos", tk_agente.cuenta(-3).startswith("Si no contestas, en 0:00"),
  True)

try:
    import tkinter as tk
    raiz_tk = tk.Tk()
except Exception as e:                                  # noqa: BLE001
    print(f"  (saltado) sin entorno gráfico: {e}")
else:
    from ui import theme
    theme.apply(raiz_tk)
    raiz_tk.withdraw()
    dichas: list = []
    piezas = tk_agente.construir(raiz_tk, "PRDRIVE-2", 120, dichas.append)
    piezas["atender"].invoke()
    piezas["ahora_no"].invoke()
    c("los botones contestan lo que dicen", dichas, [tk_agente.ATENDER, tk_agente.AHORA_NO])
    c("y la nota enseña el plazo", piezas["nota"].cget("text"), tk_agente.cuenta(120))
    raiz_tk.destroy()
    # de verdad, en su proceso: con un segundo de cuenta atrás sale con «Ahora no» (1)
    c("con pantalla, la cuenta atrás a cero sale con 1, igual por pregunta.py que por agente.py",
      (sale_con("pregunta.py", "--nombre", "A", "--segundos", "1"),
       sale_con("agente.py", "pregunta", "--nombre", "A", "--segundos", "1")), (1, 1))

raise SystemExit(c.report())
