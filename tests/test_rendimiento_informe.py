#!/usr/bin/env python3
"""El veredicto de la comprobación de tiempos (`tests/rendimiento/informe.py`).

`rendimiento.yml` falla un PR por dos cosas y nada más: una cuenta determinista por
encima de su techo, o un momento más de un 25 % Y más de 30 ms más lento que en la
base medida en el mismo trabajo. Este test fija esas dos reglas con medidas
inventadas, sin Tk ni procesos: es la parte que no puede equivocarse sin que nadie
lo note, porque un PR que no falla no avisa.
"""

import sys

from _harness import REPO, Checks

sys.path.insert(0, str(REPO / "tests" / "rendimiento"))
import informe  # noqa: E402

c = Checks("comprobación de tiempos: el veredicto")


def tiempo(arbol, esc, ms, ronda=0, pares=5, escala="1.0"):
    return {"arbol": arbol, "scenario": esc, "ms": ms, "ronda": ronda, "pares": pares,
            "escala": escala, "detail": {}}


def cuenta(arbol, esc, ronda=0, pares=5, **cuentas):
    return {"arbol": arbol, "scenario": esc, "ms": 100, "ronda": ronda, "pares": pares,
            "escala": "1.0", "detail": {"cuentas": cuentas, "by_class": {"TLabel": cuentas.get("widgets", 0)}}}


def siete(arbol, esc, base_ms, extra=0.0, minimo_extra=None):
    """Siete vueltas de un momento: la mediana sube `extra`; el mejor tiempo, `minimo_extra`."""
    ms = [base_ms + d for d in (-3, -2, -1, 0, 1, 2, 3)]
    if arbol == "pr":
        ms = [m + extra for m in ms]
        if minimo_extra is not None:
            ms[0] = min(ms) - (extra - minimo_extra)         # el mejor tiempo de las siete
    return [tiempo(arbol, esc, m, ronda=i) for i, m in enumerate(ms)]


def veredicto(lineas, presupuesto=None, plataforma="linux-x64"):
    return informe.comparar(lineas, presupuesto or {}, plataforma)


# --- los tiempos: más de un 25 % Y más de 30 ms, y el mejor tiempo también
igual = veredicto(siete("base", "start-main", 800) + siete("pr", "start-main", 800))
c("sin cambios, nada falla", igual["fallos"], [])

peor = veredicto(siete("base", "start-main", 800) + siete("pr", "start-main", 800, extra=300))
c("+300 ms (+37 %) con el mejor tiempo también peor: falla", len(peor["fallos"]), 1)
c("  y la fila lo dice", peor["filas"][0]["estado"], "peor")

poco = veredicto(siete("base", "start-main", 100) + siete("pr", "start-main", 100, extra=28))
c("+28 ms (+28 %): no llega a 30 ms, no falla", poco["fallos"], [])

lento_pero_poco = veredicto(siete("base", "start-main", 2000) + siete("pr", "start-main", 2000, extra=400))
c("+400 ms pero +20 %: no llega al 25 %, no falla", lento_pero_poco["fallos"], [])

ruido = veredicto(siete("base", "start-main", 800) + siete("pr", "start-main", 800, extra=300, minimo_extra=5))
c("la mediana sube pero el mejor tiempo no: es ruido, avisa y no falla",
  (ruido["fallos"], ruido["filas"][0]["estado"], len(ruido["avisos"])), ([], "ruido?", 1))

mejor = veredicto(siete("base", "start-main", 800) + siete("pr", "start-main", 800, extra=-300))
c("más rápido que la base: no falla", mejor["fallos"], [])

# --- un momento al que la base llega y el PR ya no
falta = veredicto(siete("base", "open-parejas", 300))
c("el PR no llega a un momento al que la base llega: falla", len(falta["fallos"]), 1)
c("  y dice qué fichero actualizar", "driver.py" in falta["fallos"][0], True)
nuevo = veredicto(siete("pr", "open-parejas", 300))
c("un momento nuevo en el PR no falla", (nuevo["fallos"], nuevo["filas"][0]["estado"]), ([], "nuevo"))

# --- el calentamiento (ronda -1) no cuenta
calentamiento = [tiempo("pr", "start-main", 5000, ronda=-1)]
c("la vuelta de calentamiento no entra en la mediana",
  informe.tiempos(siete("pr", "start-main", 800) + calentamiento)["pr"][("start-main", 5, "1.0")]["mediana"], 800)

# --- las cuentas deterministas
presupuesto = {"techo": {"widgets.main.p5": 51, "modulos.main": 250,
                         "windows": {"modulos.main": 300}}}
base = [cuenta("base", "start-main", widgets=51, modulos=254)]
c("un techo por plataforma manda sobre el general",
  (informe.techos(presupuesto, "linux-x64")["modulos.main"], informe.techos(presupuesto, "windows-x64")["modulos.main"]),
  (250, 300))

justo = veredicto(base + [cuenta("pr", "start-main", widgets=51, modulos=250)], presupuesto)
c("una cuenta en su techo no falla", justo["fallos"], [])

pasado = veredicto(base + [cuenta("pr", "start-main", widgets=58, modulos=250)], presupuesto)
c("una cuenta por encima de su techo falla", len(pasado["fallos"]), 1)
c("  y dice qué clase de widget sobra", "+7 TLabel" in pasado["fallos"][0], True)

modulos = veredicto(base + [cuenta("pr", "start-main", widgets=51, modulos=255)], presupuesto, "linux-x64")
c("los módulos del primer pintado también tienen techo", len(modulos["fallos"]), 1)
c("  que en Windows es otro", veredicto(base + [cuenta("pr", "start-main", widgets=51, modulos=255)],
                                       presupuesto, "windows-x64")["fallos"], [])

menos = veredicto(base + [cuenta("pr", "start-main", widgets=40, modulos=250)], presupuesto)
c("por debajo del techo no falla, pero avisa de que se puede bajar",
  (menos["fallos"], any("bájalo" in a for a in menos["avisos"])), ([], True))

sin_techo = veredicto([cuenta("pr", "open-parejas", widgets=152)], {})
c("una cuenta sin techo no falla (la tabla la deja sin techo)",
  (sin_techo["fallos"], sin_techo["cuentas"][0]["estado"]), ([], "sin techo"))

desaparece = veredicto(base + [cuenta("pr", "start-agente", widgets=16)], presupuesto)
c("una cuenta que la base medía y el PR ya no: falla",
  any("widgets.main.p5" in f for f in desaparece["fallos"]), True)

# --- 5 y 50 parejas son cuentas distintas
a5 = cuenta("pr", "open-parejas", pares=5, widgets=152)
a50 = cuenta("pr", "open-parejas", pares=50, widgets=467)
claves = informe.cuentas([a5, a50], "pr")
c("las cuentas llevan las parejas en la clave",
  (claves["widgets.parejas.p5"]["valor"], claves["widgets.parejas.p50"]["valor"]), (152, 467))

# --- al 150 % las cuentas no cuentan (una barra de desplazamiento cambia el número)
c("las cuentas se toman al 100 %", informe.cuentas([dict(a5, escala="2.0")], "pr"), {})

# --- el resumen
texto = informe.markdown(peor, {"plataforma": "linux-x64", "pr": "abc", "base": "def", "rondas": 7,
                                "suelo": "130 ms", "python": "3.14.8", "tk": "9.0.4"})
c("el resumen dice que falla", "**Falla**" in texto, True)
c("  y el que no falla, que pasa",
  "**Pasa.**" in informe.markdown(igual, {"plataforma": "x", "pr": "a", "base": "b", "rondas": 7,
                                           "suelo": "-", "python": "-", "tk": "-"}), True)

sys.exit(c.report())
