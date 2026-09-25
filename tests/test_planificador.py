#!/usr/bin/env python3
"""
El planificador del agente: qué toca ahora y cuándo volver a mirar.

Es puro, así que todo esto es una tabla de casos con un reloj de mentira: la
espera creciente tras un fallo, la batería, la red de uso medido, el «sin
conexión», la raíz bloqueada, la cola única y «Sincronizar ahora». Y el plazo de
«¿Atender esta unidad?».
"""

import math

from _harness import Checks

from common import planificador as pl

c = Checks("planificador del agente")

T0 = 1_000_000.0
MIN = 60.0
P = pl.Politica()

A = pl.Raiz("equipo", (pl.Pareja("docs", "nas"), pl.Pareja("fotos", "nas")), 30 * MIN)
B = pl.Raiz("unidad", (pl.Pareja("claves", "otro"),), 10 * MIN)


# La misma política con el tope de mirar en una hora, para ver cuándo toca de
# verdad lo siguiente sin que el minuto de siempre lo tape.
LARGA = pl.Politica(mirar_maximo=pl.HORA)


def dec(raices=(A, B), marcas=None, entorno=pl.Entorno(), ahora=T0, politica=P, **kw):
    return pl.decidir(raices, marcas or {}, entorno, ahora, politica, **kw)


def que(d):
    t = d.tarea
    return None if t is None else (t.tipo, t.raiz, t.pareja)


# --- la cola -----------------------------------------------------------------
d = dec()
c("sin historia, la primera pareja de la primera raíz", que(d),
  ("pasada", "equipo", "docs"))
d = dec(ocupado=True)
c("con una pasada en marcha no se decide otra", que(d), None)
c("  y se vuelve a mirar pronto", d.mirar_en, P.mirar_ocupado)

hechas = {("equipo", "docs"): pl.Marca(T0, 0)}
c("la siguiente pendiente, sea de la raíz que sea",
  que(dec(marcas=hechas)), ("pasada", "equipo", "fotos"))

todas = {("equipo", "docs"): pl.Marca(T0 - 25 * MIN),
         ("equipo", "fotos"): pl.Marca(T0 - 5 * MIN),
         ("unidad", "claves"): pl.Marca(T0 - 2 * MIN)}
d = dec(marcas=todas, politica=LARGA)
c("nada vencido: ninguna tarea", que(d), None)
c("  y se mira cuando vence la primera (docs, en 5 min)", d.mirar_en, 5 * MIN)

vencidas = {("equipo", "docs"): pl.Marca(T0 - 31 * MIN),
            ("equipo", "fotos"): pl.Marca(T0 - 5 * MIN),
            ("unidad", "claves"): pl.Marca(T0 - 15 * MIN)}
c("de dos vencidas, la que más lleva esperando",
  que(dec(marcas=vencidas)), ("pasada", "unidad", "claves"))

lejos = {k: pl.Marca(T0) for k in todas}
c("el tope de mirar: aunque nada toque en 10 min, se mira al minuto",
  dec(marcas=lejos).mirar_en, P.mirar_maximo)

# --- espera creciente --------------------------------------------------------
c("sin fallos, el intervalo", pl.espera(30 * MIN, 0), 30 * MIN)
c("un fallo, el doble", pl.espera(30 * MIN, 1), 60 * MIN)
c("dos fallos, el cuádruple", pl.espera(30 * MIN, 2), 120 * MIN)
c("muchos fallos, el tope de 4 h", pl.espera(30 * MIN, 9), 4 * pl.HORA)
c("un intervalo mayor que el tope no se acorta", pl.espera(6 * pl.HORA, 3),
  6 * pl.HORA)
c("un millón de fallos no revienta", pl.espera(30 * MIN, 10 ** 6), 4 * pl.HORA)

m = pl.registrar(pl.Marca(), pl.FALLO, T0)
c("un fallo suma uno", m, pl.Marca(T0, 1))
m2 = pl.registrar(m, pl.FALLO, T0 + 60 * MIN)
c("otro, dos", m2.fallos, 2)
c("la primera vez que falla se avisa", pl.empieza_a_fallar(pl.Marca(), m), True)
c("la segunda, no", pl.empieza_a_fallar(m, m2), False)
c("una buena vuelve a cero", pl.registrar(m2, pl.OK, T0), pl.Marca(T0, 0))
c("una saltada (pide --resync) tampoco es un fallo",
  pl.registrar(m2, pl.SALTADA, T0).fallos, 0)
c("una de red no suma fallos ni cuenta como intento",
  pl.registrar(m, pl.RED, T0 + 5), pl.Marca(None, 1))

solo_a = (A,)
tras_fallo = {("equipo", "docs"): pl.Marca(T0 - 45 * MIN, 1),
              ("equipo", "fotos"): pl.Marca(T0)}
d = dec(solo_a, tras_fallo, politica=LARGA)
c("tras un fallo, a los 45 min todavía no (espera 60)", que(d), None)
c("  y vuelve a mirar a los 15", d.mirar_en, 15 * MIN)
c("a los 61, sí", que(dec(solo_a, tras_fallo, ahora=T0 + 16 * MIN)),
  ("pasada", "equipo", "docs"))

# --- modo sync: una vez por conexión ------------------------------------------
UNA = pl.Raiz("unidad", (pl.Pareja("claves"),), math.inf)
c("modo sync: la primera vez, sí", que(dec((UNA,))), ("pasada", "unidad", "claves"))
d = dec((UNA,), {("unidad", "claves"): pl.Marca(T0 - 9 * pl.HORA, 3)})
c("modo sync: hecha, nunca más en esta conexión", que(d), None)
c("  y se mira al tope, no nunca", d.mirar_en, P.mirar_maximo)

# --- moderarse ----------------------------------------------------------------
bateria_baja = pl.Entorno(con_bateria=True, bateria=15)
d = dec(entorno=bateria_baja)
c("con batería por debajo del 20 % no se lanza nada", que(d), None)
c("  y se dice por qué", d.retenido, "batería por debajo del 20 %")
c("con batería de sobra, sí",
  que(dec(entorno=pl.Entorno(con_bateria=True, bateria=80))), ("pasada", "equipo", "docs"))
c("enchufado con la batería baja, también",
  que(dec(entorno=pl.Entorno(con_bateria=False, bateria=5))), ("pasada", "equipo", "docs"))
c("batería desconocida no para nada",
  que(dec(entorno=pl.Entorno(con_bateria=True, bateria=None))),
  ("pasada", "equipo", "docs"))
c("la política puede prohibir la batería del todo",
  pl.moderacion(pl.Entorno(con_bateria=True, bateria=90),
                pl.Politica(con_bateria=False)), "funcionando con batería")

medida = pl.Entorno(red_medida=True)
c("en una red de uso medido, nada", dec(entorno=medida).retenido, "red de uso medido")
c("red de uso medido desconocida: normal",
  dec(entorno=pl.Entorno(red_medida=None)).retenido, None)
c("la política puede no pausar en red medida",
  pl.moderacion(medida, pl.Politica(pausar_red_medida=False)), None)
c("en pausa, nada", dec(entorno=pl.Entorno(pausado=True)).retenido, "en pausa")

# --- «Sincronizar ahora» ------------------------------------------------------
urg = [("unidad", "claves")]
for nombre, ent in (("pausa", pl.Entorno(pausado=True)), ("batería", bateria_baja),
                    ("red medida", medida)):
    d = dec(entorno=ent, urgentes=urg)
    c(f"«Sincronizar ahora» se salta la {nombre}", que(d), ("pasada", "unidad", "claves"))
c("  y la tarea va marcada como urgente", dec(urgentes=urg).tarea.urgente, True)
c("«Sincronizar ahora» se salta la espera tras un fallo",
  que(dec(solo_a, tras_fallo, urgentes=[("equipo", "docs")])),
  ("pasada", "equipo", "docs"))
c("pero no pasa por delante de una pasada en marcha",
  que(dec(urgentes=urg, ocupado=True)), None)
c("ni lanza una raíz que no se puede atender",
  que(dec((pl.Raiz("unidad", B.parejas, B.intervalo, atendible=False),),
          urgentes=urg)), None)
c("una pareja urgente que ya no existe se ignora",
  que(dec(urgentes=[("unidad", "fantasma")])), ("pasada", "equipo", "docs"))

# --- sin conexión -------------------------------------------------------------
ent = pl.sin_conexion(pl.Entorno(), "equipo", "nas", T0 + P.sondeo_sin_conexion)
d = dec(entorno=ent)
c("lo que va a un remoto sin conexión no se lanza; lo demás, sí",
  que(d), ("pasada", "unidad", "claves"))
d = dec((A,), entorno=ent, politica=LARGA)
c("sin nada más, nada", que(d), None)
c("  y se mira cuando toca sondear", d.mirar_en, P.sondeo_sin_conexion)
d = dec((A,), entorno=ent, ahora=T0 + P.sondeo_sin_conexion)
c("al llegar la hora, una sonda de ese remoto, no una pareja",
  que(d), ("sonda", "equipo", None))
c("  del remoto que toca", d.tarea.remoto, "nas")
ent2 = pl.con_conexion(ent, "equipo", "nas")
c("de vuelta la conexión, sus parejas vuelven", que(dec((A,), entorno=ent2)),
  ("pasada", "equipo", "docs"))
red = {("equipo", "docs"): pl.registrar(pl.Marca(T0 - 1, 0), pl.RED, T0)}
c("la que falló por red es la primera en cuanto vuelve",
  que(dec((A,), red, entorno=ent2)), ("pasada", "equipo", "docs"))
c("una sonda de una raíz que ya no está no se lanza",
  que(dec((B,), entorno=pl.sin_conexion(pl.Entorno(), "equipo", "nas", T0 - 9999))),
  ("pasada", "unidad", "claves"))

# --- raíz bloqueada o ausente -------------------------------------------------
cerrada = pl.Raiz("equipo", A.parejas, A.intervalo, atendible=False)
d = dec((cerrada,))
c("una raíz bloqueada no lanza nada", que(d), None)
c("  no es un fallo: no hay motivo global", d.retenido, None)
c("  y no hace esperar más de lo normal", d.mirar_en, P.mirar_maximo)
c("la otra raíz sigue su curso", que(dec((cerrada, B))), ("pasada", "unidad", "claves"))

# --- el plazo de «¿Atender esta unidad?» --------------------------------------
q = pl.Pregunta("abc", T0, 120)
c("sin respuesta, antes del plazo: se espera", pl.resolver(q, None, T0 + 60), None)
c("sin respuesta, al vencer: «Ahora no»", pl.resolver(q, None, T0 + 120), pl.AHORA_NO)
c("«Atender» a tiempo", pl.resolver(q, pl.ATENDER, T0 + 30), pl.ATENDER)
c("«Ahora no» a tiempo", pl.resolver(q, pl.AHORA_NO, T0 + 30), pl.AHORA_NO)
c("«Atender» tardío no cuenta",
  pl.resolver(q, pl.ATENDER, T0 + 200, cuando=T0 + 150), pl.AHORA_NO)
c("una respuesta que no es ninguna de las dos se ignora",
  pl.resolver(q, "quizá", T0 + 30), None)

raise SystemExit(c.report())
