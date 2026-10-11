#!/usr/bin/env python3
"""El planificador del agente: qué toca ahora y cuándo volver a mirar.

Es puro, así que todo esto es una tabla de casos con un reloj de mentira: la
espera creciente tras un fallo, la batería, la red de uso medido, el «sin
conexión» (con su sondeo de respaldo y la ráfaga de avisos de red que se
agrupa en una sonda), la raíz bloqueada, la cola única y «Sincronizar ahora».
Y el plazo de «¿Atender esta unidad?».
"""

import math

from _harness import Checks

from common import equipo
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
    """Pide una decisión al planificador con valores por defecto."""
    return pl.decidir(raices, marcas or {}, entorno, ahora, politica, **kw)


def que(d):
    """Devuelve `(tipo, raíz, pareja)` de la tarea decidida, o `None`."""
    t = d.tarea
    return None if t is None else (t.tipo, t.raiz, t.pareja)


# la cola
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

# espera creciente
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

# modo sync: una vez por conexión
UNA = pl.Raiz("unidad", (pl.Pareja("claves"),), math.inf)
c("modo sync: la primera vez, sí", que(dec((UNA,))), ("pasada", "unidad", "claves"))
d = dec((UNA,), {("unidad", "claves"): pl.Marca(T0 - 9 * pl.HORA, 3)})
c("modo sync: hecha, nunca más en esta conexión", que(d), None)
c("  y se mira al tope, no nunca", d.mirar_en, P.mirar_maximo)

# moderarse
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

# El modo de ahorro de energía lo ha encendido el usuario (o el sistema, con
# poca batería): se respeta también enchufado.
ahorro = pl.Entorno(ahorro_energia=True)
c("en modo de ahorro de energía, nada", dec(entorno=ahorro).retenido,
  "modo de ahorro de energía")
c("  de fábrica", P.pausar_ahorro_energia, True)
c("la política puede no pausar en ahorro de energía",
  pl.moderacion(ahorro, pl.Politica(pausar_ahorro_energia=False)), None)
c("  y se guarda en agente.json",
  equipo.desde_dict(equipo.a_dict(equipo.Ajustes(
      politica=pl.Politica(pausar_ahorro_energia=False)))).politica.pausar_ahorro_energia,
  False)
c("un agente.json sin la clave: la de fábrica",
  equipo.desde_dict({"moderacion": {}}).politica.pausar_ahorro_energia, True)

# «Sincronizar ahora»
urg = [("unidad", "claves")]
for nombre, ent in (("pausa", pl.Entorno(pausado=True)), ("batería", bateria_baja),
                    ("red medida", medida)):
    d = dec(entorno=ent, urgentes=urg)
    c(f"«Sincronizar ahora» se salta la {nombre}", que(d), ("pasada", "unidad", "claves"))
c("«Sincronizar ahora» se salta el modo de ahorro de energía",
  que(dec(entorno=ahorro, urgentes=urg)), ("pasada", "unidad", "claves"))
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

# sin conexión
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

# cuándo se vuelve a sondear un remoto que no contesta
c("sin avisos de red, cada 5 min, como siempre", pl.sondeo(P, False), 5 * MIN)
c("con avisos de red, el temporizador es solo el respaldo: 30 min",
  pl.sondeo(P, True), 30 * MIN)
c("  mucho más que los 5 min de antes", pl.sondeo(P, True) >= 6 * pl.sondeo(P, False),
  True)
dos = pl.sin_conexion(pl.sin_conexion(pl.Entorno(), "equipo", "nas", T0 + 3600),
                      "unidad", "otro", T0 - 10)
ya = pl.sondear_ya(dos, T0)
c("sondear ya: cada remoto sin conexión toca ahora; el que ya tocaba, igual",
  dict(ya.sin_conexion), {("equipo", "nas"): T0, ("unidad", "otro"): T0 - 10})
c("  y lo demás del entorno no cambia",
  pl.sondear_ya(pl.Entorno(pausado=True), T0), pl.Entorno(pausado=True))

# la ráfaga de avisos de red: una sonda por ráfaga
r = pl.cambia_la_red(None, T0)
c("el primer aviso abre una ráfaga", r, pl.CambioDeRed(T0, T0))
c("  que se sondea cuando se calma", r.sondear_en, T0 + pl.ASENTAR_RED)
c("  no antes", pl.red_asentada(r, T0 + pl.ASENTAR_RED - 1, False), False)
c("  y a su hora, sí", pl.red_asentada(r, T0 + pl.ASENTAR_RED, False), True)
r = pl.cambia_la_red(pl.cambia_la_red(r, T0 + 2), T0 + 3)
c("más avisos seguidos (cada interfaz, el Wi-Fi que cae y sube) la alargan",
  (r.primero, r.ultimo, r.sondear_en), (T0, T0 + 3, T0 + 3 + pl.ASENTAR_RED))
c("  un aviso que llega desordenado no la acorta",
  pl.cambia_la_red(r, T0 + 1).ultimo, T0 + 3)
continua = None
for s in range(0, 100, 2):
    continua = pl.cambia_la_red(continua, T0 + s)
c("una red que no para de cambiar se sondea igual, a su tope",
  continua.sondear_en, T0 + pl.TOPE_RAFAGA_RED)
c("con una pasada o una sonda en marcha, la ráfaga espera a que acabe",
  pl.red_asentada(r, T0 + 999, True), False)
c("sin ráfaga, nada que sondear", pl.red_asentada(None, T0 + 999, False), False)

# raíz bloqueada o ausente
cerrada = pl.Raiz("equipo", A.parejas, A.intervalo, atendible=False)
d = dec((cerrada,))
c("una raíz bloqueada no lanza nada", que(d), None)
c("  no es un fallo: no hay motivo global", d.retenido, None)
c("  y no hace esperar más de lo normal", d.mirar_en, P.mirar_maximo)
c("la otra raíz sigue su curso", que(dec((cerrada, B))), ("pasada", "unidad", "claves"))

# el plazo de «¿Atender esta unidad?»
q = pl.Pregunta("abc", T0, 120)
c("sin respuesta, antes del plazo: se espera", pl.resolver(q, None, T0 + 60), None)
c("sin respuesta, al vencer: «Ahora no»", pl.resolver(q, None, T0 + 120), pl.AHORA_NO)
c("«Atender» a tiempo", pl.resolver(q, pl.ATENDER, T0 + 30), pl.ATENDER)
c("«Ahora no» a tiempo", pl.resolver(q, pl.AHORA_NO, T0 + 30), pl.AHORA_NO)
c("«Atender» tardío no cuenta",
  pl.resolver(q, pl.ATENDER, T0 + 200, cuando=T0 + 150), pl.AHORA_NO)
c("una respuesta que no es ninguna de las dos se ignora",
  pl.resolver(q, "quizá", T0 + 30), None)

# --- el intervalo se estira mientras las pasadas no mueven nada
c("sin pasadas vacías, el intervalo es el suyo", pl.estirado(5 * MIN, 0, P), 5 * MIN)
c("  dos seguidas todavía no lo tocan", pl.estirado(5 * MIN, 2, P), 5 * MIN)
c("  a la tercera se dobla", pl.estirado(5 * MIN, 3, P), 10 * MIN)
c("  a la sexta, otra vez", pl.estirado(5 * MIN, 6, P), 20 * MIN)
c("  y ahí se queda: cuatro veces como mucho", pl.estirado(5 * MIN, 600, P), 20 * MIN)
c("nunca más de media hora por haberse estirado", pl.estirado(15 * MIN, 9, P), 30 * MIN)
c("  y un intervalo que ya es mayor no se acorta", pl.estirado(45 * MIN, 9, P), 45 * MIN)
c("el modo sync (sin intervalo) no se toca", pl.estirado(math.inf, 9, P), math.inf)
c("apagado, no se estira", pl.estirado(5 * MIN, 9, pl.Politica(estirar=False)), 5 * MIN)

m = pl.Marca()
for _ in range(3):
    m = pl.registrar(m, pl.OK, T0, vacia=True)
c("tres pasadas buenas sin mover nada: tres vacías", (m.vacias, m.fallos), (3, 0))
c("  una que mueve algo las pone a cero", pl.registrar(m, pl.OK, T0).vacias, 0)
c("  una de la que no se sabe (un sync.py de antes) cuenta como que movió",
  pl.registrar(m, pl.OK, T0, vacia=False).vacias, 0)
c("  un fallo también", (pl.registrar(m, pl.FALLO, T0).vacias, pl.registrar(m, pl.FALLO, T0).fallos),
  (0, 1))
c("  y una pedida a mano, aunque no mueva nada: quien está delante quiere el de fábrica",
  pl.registrar(m, pl.OK, T0, vacia=True, urgente=True).vacias, 0)
c("  una de red no cuenta ni como intento ni como nada: se conservan",
  pl.registrar(m, pl.RED, T0), pl.Marca(None, 0, 3))
c("despertarla la devuelve a fábrica sin tocar cuándo se intentó",
  pl.despierta(pl.Marca(T0, 0, 7, 2, True)), pl.Marca(T0, 0))
c("  y a una que no está estirada no le hace nada", pl.despierta(pl.Marca(T0, 2)), pl.Marca(T0, 2))

CINCO = pl.Raiz("u", (pl.Pareja("docs", "nas"), pl.Pareja("llaves", "nas", llavero=True)), 5 * MIN)
estirada = {("u", "docs"): pl.Marca(T0, 0, 3), ("u", "llaves"): pl.Marca(T0, 0, 3)}
d = dec((CINCO,), estirada, ahora=T0 + 5 * MIN + 1, politica=LARGA)
c("con tres vacías, a los 5 min no le toca a la pareja; al llavero sí (no se estira nunca)",
  que(d), ("pasada", "u", "llaves"))
d = dec((CINCO,), {**estirada, ("u", "llaves"): pl.Marca(T0 + 5 * MIN, 0, 4)},
        ahora=T0 + 5 * MIN + 1, politica=LARGA)
c("  la pareja espera a los 10", (que(d), round(d.mirar_en)), (None, round(5 * MIN - 1)))
d = dec((CINCO,), {("u", "docs"): pl.Marca(T0, 0, 3), ("u", "llaves"): pl.Marca(T0 + 10 * MIN, 0)},
        ahora=T0 + 10 * MIN + 1, politica=LARGA)
c("  y entonces sí", que(d), ("pasada", "u", "docs"))
d = dec((CINCO,), {("u", "docs"): pl.Marca(T0, 0, 3), ("u", "llaves"): pl.Marca(T0 + 5 * MIN, 0)},
        ahora=T0 + 5 * MIN + 1, politica=pl.Politica(estirar=False))
c("con el ajuste apagado va a su intervalo", que(d), ("pasada", "u", "docs"))
d = dec((CINCO,), {("u", "docs"): pl.Marca(T0, 0, 6), ("u", "llaves"): pl.Marca(T0 + 5 * MIN, 0)},
        ahora=T0 + 5 * MIN + 1, politica=LARGA, urgentes=[("u", "docs")])
c("«Sincronizar ahora» no espera al intervalo estirado", (que(d), d.tarea.urgente),
  (("pasada", "u", "docs"), True))
c("cada(): lo que se enseña, estirado y sin estirar",
  (pl.cada(CINCO, CINCO.parejas[0], pl.Marca(T0, 0, 6), P),
   pl.cada(CINCO, CINCO.parejas[1], pl.Marca(T0, 0, 6), P)), (20 * MIN, 5 * MIN))

# --- una pareja saltada no se relanza en cada intervalo
saltada = pl.registrar(pl.Marca(T0 - 1, 0, 5), pl.SALTADA, T0)
c("saltada: ni un fallo ni vacías, pero queda dicho", saltada, pl.Marca(T0, 0, saltada=True))
SOLA = pl.Raiz("u", (pl.Pareja("docs", "nas"),), 5 * MIN)
d = dec((SOLA,), {("u", "docs"): saltada}, ahora=T0 + 5 * MIN + 1, politica=LARGA)
c("  a su intervalo no se relanza para saltarse igual", que(d), None)
d = dec((SOLA,), {("u", "docs"): saltada}, ahora=T0 + P.espera_saltada + 1, politica=LARGA)
c("  pasada la espera, se prueba otra vez", que(d), ("pasada", "u", "docs"))
d = dec((SOLA,), {("u", "docs"): pl.despierta(saltada)}, ahora=T0 + 5 * MIN + 1, politica=LARGA)
c("  y despertada (el agente retoma la raíz), vuelve a su intervalo", que(d),
  ("pasada", "u", "docs"))
c("  una pasada buena la saca de saltada", pl.registrar(saltada, pl.OK, T0).saltada, False)
LENTA = pl.Raiz("u", (pl.Pareja("docs", "nas"),), 3 * pl.HORA)
c("  con un intervalo mayor que esa espera manda el intervalo",
  pl.cada(LENTA, LENTA.parejas[0], saltada, P), 3 * pl.HORA)

# --- la separación aprende de las pasadas adelantadas que salen vacías
C = pl.PoliticaCambios()
c("sin pasadas adelantadas vacías, la separación de fábrica",
  pl.separacion_de(pl.Marca(T0), C), C.separacion)
c("  una sola no la mueve", pl.separacion_de(pl.Marca(T0, 0, 1, 1), C), C.separacion)
c("  dos seguidas la doblan", pl.separacion_de(pl.Marca(T0, 0, 2, 2), C), 2 * C.separacion)
c("  tres, otra vez", pl.separacion_de(pl.Marca(T0, 0, 3, 3), C), 4 * C.separacion)
c("  hasta su tope", pl.separacion_de(pl.Marca(T0, 0, 40, 40), C), C.separacion_tope)
m = pl.registrar(pl.Marca(T0, 0, 0, 0), pl.OK, T0, vacia=True, por_cambios=True)
c("una adelantada que sale vacía cuenta de las dos maneras", (m.vacias, m.vacias_por_cambios),
  (1, 1))
c("  una por intervalo que sale vacía no alarga la separación",
  pl.registrar(m, pl.OK, T0, vacia=True).vacias_por_cambios, 1)
c("  y una que mueve algo la devuelve a la de fábrica",
  pl.registrar(pl.Marca(T0, 0, 4, 4), pl.OK, T0, por_cambios=True).vacias_por_cambios, 0)
v = pl.Vigilada(cambio=T0 + 10, avisos=True)
c("con la separación doblada, el cambio espera más",
  (pl.toca_por_cambios(v, pl.Marca(T0), C), pl.toca_por_cambios(v, pl.Marca(T0, 0, 2, 2), C)),
  (T0 + C.separacion, T0 + 2 * C.separacion))
c("una pareja que se está saltando no se adelanta por sus cambios",
  pl.toca_por_cambios(v, saltada, C), math.inf)

raise SystemExit(c.report())
