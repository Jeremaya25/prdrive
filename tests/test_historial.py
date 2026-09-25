#!/usr/bin/env python3
"""
El diario de pasadas (common/historial.py).

Es lo que dice desde cuándo falla una pareja: `last_run.json` solo guarda la
última pasada, y cada una pisa la anterior. Aquí se comprueba lo que se ve desde
fuera —qué se lee después de apuntar— y las dos cosas que el medio exige: que lo
normal sea AÑADIR una línea y no reescribir el fichero (los ciclos de escritura
del pendrive), y que una línea a medias o con basura no arrastre a las demás.
"""

import sys

from _harness import Checks, sandbox

from common import historial, model, store

c = Checks("el diario de pasadas (common/historial.py)")

N = historial.POR_PAREJA


def pasada(pareja, codigo=0, dia=1, hora=0, minuto=0, segundos=1.0, transferido=None):
    return historial.Pasada(pareja, f"2026-09-{dia:02d} {hora:02d}:{minuto:02d}:00",
                            codigo, segundos, transferido)


def secuencia(pareja, codigos):
    """Una pasada por código, un minuto después de la anterior."""
    return [pasada(pareja, cod, dia=1 + i // 1440, hora=(i // 60) % 24, minuto=i % 60)
            for i, cod in enumerate(codigos)]


# --- apuntar y leer ---------------------------------------------------------------
with sandbox():
    c("sin fichero no hay pasadas", historial.leer(), [])
    c("ni rachas", historial.rachas(["notas"]), {})

    una = pasada("notas", 0, segundos=12.5, transferido=2048)
    c("apuntar dice que ha escrito", historial.apuntar(una), True)
    otra = pasada("fotos", 3, dia=2)
    historial.apuntar(otra)
    c("se lee lo que se apuntó, en su orden", historial.leer(), [una, otra])
    c("una línea por pasada",
      historial.ruta().read_text(encoding="utf-8").count("\n"), 2)
    c("vive en state/", historial.ruta().parent, model.STATE_DIR)
    c("el resultado es el código", (una.ok, otra.ok), (True, False))

    # Lo que no se sabe se guarda como tal, y se lee igual.
    sin_nada = historial.Pasada("notas", "2026-09-03 08:00:00", 1, None, None)
    historial.apuntar(sin_nada)
    c("sin duración ni bytes, None y no un número inventado",
      historial.leer()[-1], sin_nada)

with sandbox():
    reloj = historial.Reloj()
    p = reloj.pasada("notas", 0, 1234)
    c("el reloj apunta cuándo empezó, con el sello de state/",
      store.desde_sello(p.inicio) is not None, True)
    c("y lo que duró, en segundos", p.segundos is not None and 0 <= p.segundos < 60, True)
    c("con lo transferido", p.transferido, 1234)
    c("historial.pasada() con reloj es la del reloj",
      historial.pasada("notas", 0, reloj, 1234)[:3], p[:3])

    # La pareja que se cortó antes de que nadie mirara la hora (el dispositivo
    # desaparece a mitad de una pasada de varias, `sync.run_all()`): consta igual.
    suelta = historial.pasada("notas", 1)
    c("sin reloj consta con la hora de ahora", store.desde_sello(suelta.inicio) is not None,
      True)
    c("y sin duración: un cero sería inventado", (suelta.codigo, suelta.segundos),
      (1, None))

with sandbox():
    # El dispositivo ya no está (o state/ no se deja escribir): se pierde la
    # línea, pero no revienta la pasada que la apuntaba.
    model.STATE_DIR = model.DEVICE_ROOT / "no-existe" / "state"
    c("si no se puede escribir, apuntar devuelve False sin lanzar",
      historial.apuntar(pasada("notas")), False)
    c("y leer sigue sin fallar", historial.leer(), [])


# --- líneas rotas -----------------------------------------------------------------
with sandbox():
    buena1 = pasada("notas", 0, dia=1)
    buena2 = pasada("notas", 1, dia=2)
    historial.ruta().write_text("\n".join([
        historial._linea(buena1).rstrip("\n"),
        "no es json",
        "[1, 2, 3]",
        '{"pareja": "notas"}',
        '{"pareja": "notas", "inicio": "ayer", "codigo": 0}',
        '{"pareja": "notas", "inicio": "2026-09-01 00:00:00", "codigo": true}',
        '{"pareja": "notas", "inicio": "2026-09-01 00:00:00", "codigo": 0.5}',
        '{"pareja": "", "inicio": "2026-09-01 00:00:00", "codigo": 0}',
        "",
        historial._linea(buena2).rstrip("\n"),
        # Un corte de corriente a mitad de escribir la última línea.
        '{"pareja": "notas", "inicio": "2026-09-0',
    ]), encoding="utf-8")
    c("las líneas que no son una pasada entera se saltan", historial.leer(),
      [buena1, buena2])

    rara = ('{"pareja": "notas", "inicio": "2026-09-05 00:00:00", "codigo": 0, '
            '"segundos": NaN, "transferido": -3}')
    c("lo accesorio que no se entiende se lee como «no consta»",
      historial._pasada(rara), historial.Pasada("notas", "2026-09-05 00:00:00", 0))
    c("Infinity tampoco es una duración",
      historial._pasada(rara.replace("NaN", "Infinity")).segundos, None)
    c("ni unos bytes con decimales",
      historial._pasada(rara.replace("-3", "1.5")).transferido, None)

    # La siguiente pasada no se pega detrás de la línea a medias: se perderían
    # las dos.
    nueva = pasada("notas", 0, dia=6)
    historial.apuntar(nueva)
    c("la pasada que sigue a una línea a medias se lee entera",
      historial.leer(), [buena1, buena2, nueva])

with sandbox():
    historial.ruta().write_bytes(b"\xff\xfe basura binaria \x00\n"
                                 + historial._linea(pasada("notas")).encode("utf-8"))
    c("bytes que no son UTF-8 no impiden leer lo demás", len(historial.leer()), 1)


# --- el recorte -------------------------------------------------------------------
with sandbox():
    reescrituras = []
    real = store.write_text

    def contar(ruta, texto):
        reescrituras.append(ruta)
        return real(ruta, texto)

    store.write_text = contar
    try:
        # Otra pareja con pocas pasadas, intercaladas: el recorte de la grande no
        # puede llevárselas por delante.
        pocas = secuencia("fotos", [0, 1, 0])
        muchas = secuencia("notas", [0] * (historial.RECORTE + 1))
        orden = []
        for i, p in enumerate(muchas[:historial.RECORTE]):
            orden.append(p)
            if i < len(pocas):
                orden.append(pocas[i])
        for p in orden:
            historial.apuntar(p)
        c("hasta el umbral solo se añade: ni una reescritura", reescrituras, [])
        c("y el fichero guarda todo", len(historial.leer()), historial.RECORTE + 3)

        historial.apuntar(muchas[-1])
        c("al pasar el umbral se reescribe una vez", len(reescrituras), 1)
        leidas = historial.leer()
        de_notas = [p for p in leidas if p.pareja == "notas"]
        c("la pareja grande se queda con sus últimas N", de_notas, muchas[-N:])
        c("la pequeña no pierde ninguna", [p for p in leidas if p.pareja == "fotos"], pocas)
        c("y lo que queda sigue en el orden en que se apuntó", leidas,
          [p for p in orden + muchas[-1:] if p in pocas or p in muchas[-N:]])

        # Hasta el siguiente recorte hacen falta otras N pasadas de esa pareja.
        mas = secuencia("notas", [1] * (N + 1))
        mas = [p._replace(inicio=p.inicio.replace("2026-09-0", "2026-10-0")) for p in mas]
        for p in mas[:N]:
            historial.apuntar(p)
        c("tras un recorte, otras N pasadas se añaden sin reescribir", len(reescrituras), 1)
        historial.apuntar(mas[N])
        c("y la siguiente vuelve a recortar", len(reescrituras), 2)
        c("otra vez a N", sum(1 for p in historial.leer() if p.pareja == "notas"), N)
    finally:
        store.write_text = real

with sandbox():
    # La red de seguridad por tamaño: parejas que ya no existen, cada una con sus
    # N, o basura que no es de nadie. Se recorta hasta la mitad del tope, y por
    # lo más viejo.
    tope_real = historial.TOPE_BYTES
    historial.TOPE_BYTES = 4096
    try:
        for i in range(80):
            historial.apuntar(pasada(f"pareja-{i:02d}", 0, dia=1 + i // 60, minuto=i % 60))
        tamano = historial.ruta().stat().st_size
        c("el fichero no pasa del tope", tamano <= historial.TOPE_BYTES, True)
        leidas = historial.leer()
        c("se queda con las más nuevas", leidas[-1].pareja, "pareja-79")
        c("y las viejas son las que se van", leidas[0].pareja != "pareja-00", True)
    finally:
        historial.TOPE_BYTES = tope_real

with sandbox():
    # La basura acumulada también cuenta para el tope, y el recorte la limpia.
    historial.TOPE_BYTES, tope_real = 2048, historial.TOPE_BYTES
    try:
        historial.ruta().write_text("basura\n" * 400, encoding="utf-8")
        historial.apuntar(pasada("notas"))
        c("un recorte por tamaño deja solo las pasadas legibles",
          historial.ruta().read_text(encoding="utf-8"),
          historial._linea(pasada("notas")))
    finally:
        historial.TOPE_BYTES = tope_real


# --- desde cuándo falla -----------------------------------------------------------
c("sin pasadas no hay racha", historial.racha([]), None)
c("si la última fue bien, tampoco", historial.racha(secuencia("n", [1, 1, 0])), None)

nunca = secuencia("n", [1, 1, 1])
r = historial.racha(nunca)
c("nunca ha ido bien: desde la primera que consta", r.desde, nunca[0].inicio)
c("pero no es exacta: pudo empezar antes del diario", r.exacta, False)
c("0 de las últimas 3", (r.buenas, r.pasadas), (0, 3))

tres = secuencia("n", [0, 0, 1, 0, 1, 1, 1])
r = historial.racha(tres)
c("falla desde hace 3: la primera de la racha", r.desde, tres[4].inicio)
c("y es exacta: antes hay una buena", r.exacta, True)
c("3 de las últimas 7 bien", (r.buenas, r.pasadas), (3, 7))

tropiezo = secuencia("n", [0] * 13 + [1])
r = historial.racha(tropiezo)
c("un tropiezo: falla desde la última", r.desde, tropiezo[-1].inicio)
c("13 de las últimas 14", (r.buenas, r.pasadas), (13, 14))

c("una sola pasada, fallida", historial.racha(secuencia("n", [1]))[1:],
  (False, 0, 1))

# Más pasadas de las que se cuentan: el diario puede tener hasta 2N antes del
# recorte. Se cuentan las últimas N, pero la racha se busca en todo lo que hay.
larga = secuencia("n", [0] + [1] * (N + 9))
r = historial.racha(larga)
c("«de las últimas» son como mucho N", (r.buenas, r.pasadas), (0, N))
c("pero el inicio de la racha se busca en todo el diario",
  (r.desde, r.exacta), (larga[1].inicio, True))

with sandbox():
    for p in secuencia("notas", [0, 1, 1]) + secuencia("fotos", [1, 0]) + \
            secuencia("docs", [1]):
        historial.apuntar(p)
    rachas = historial.rachas(["notas", "fotos", "otra"])
    c("rachas: solo de las pedidas que están fallando", sorted(rachas), ["notas"])
    c("con lo suyo", (rachas["notas"].buenas, rachas["notas"].pasadas), (1, 3))

sys.exit(c.report())
