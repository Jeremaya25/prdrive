#!/usr/bin/env python3
"""
«Se ha conectado PRDRIVE-2. ¿Atenderla en este equipo?»

Una unidad cuyo id no está en la lista del agente nunca se sincroniza sin
preguntar. Se comprueba que:

  * sin respuesta en `espera_unidad_nueva` cuenta como «Ahora no»;
  * «Ahora no» dura hasta que la raíz desaparece, y se vuelve a preguntar al
    reaparecer;
  * una respuesta tardía de la ventana se ignora;
  * el «Atender» de la bandeja (el buzón) funciona mientras sigue conectada;
  * sin entorno gráfico es «Ahora no» al momento;
  * «Atender» la añade en modo daemon y la atiende;
  * y, sobre todo, que **antes del sí no se lanza ningún proceso con rutas de
    la unidad**.

Y la ventanita (`ui/tk_agente.py`), si hay Tk y pantalla.
"""

import os

from _harness import Checks

import _agente_falso as F
from common import equipo, planificador as pl

c = Checks("agente: una unidad nueva")
F.preparar()

UID = "1" * 32
RAIZ = F.unidad(UID, nombre="PRDRIVE-2")
F.RAICES[:] = [RAIZ]
equipo.guardar_ajustes(equipo.Ajustes(espera_unidad_nueva=120))


def con_rutas_de_la_unidad() -> list:
    return [p.args for p in F.LANZADOS if any(str(RAIZ) in a for a in p.args)
            or str(RAIZ) in str(p.kwargs.get("cwd", ""))]


def preguntas() -> list:
    return [p for p in F.LANZADOS if "pregunta" in p.args]


ag = F.nuevo()
F.vueltas(ag, 2)
c("una unidad que no está en la lista: se avisa", F.AVISOS[-1],
  ("Se ha conectado PRDRIVE-2", "¿Atenderla en este equipo?"))
c("  y se abre la pregunta", len(preguntas()), 1)
q = preguntas()[0]
c("  con su nombre y el plazo", q.args[-4:], ["--nombre", "PRDRIVE-2", "--segundos", "120"])
c("  como un hijo del propio agente (no carga Tk)", q.args[1].endswith("agente.py"), True)
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
c("el «Atender» de la bandeja la añade a la lista",
  equipo.leer_ajustes().unidades.get(UID), equipo.Unidad(UID, equipo.DAEMON, "PRDRIVE-2"))
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


# --- la ventanita ----------------------------------------------------------------
from ui import tk_agente  # noqa: E402

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

raise SystemExit(c.report())
