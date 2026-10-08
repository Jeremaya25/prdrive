#!/usr/bin/env python3
"""Mide en esta máquina lo que decide las tareas 13 y 14 de la etapa 2 (R3 y R7).

TEMPORAL, como todo `etapa2_*`: lo borra la tarea 15 de la etapa 2.

    python tests/rendimiento/etapa2_medir.py --arbol DIR --trabajo DIR
        [--python PY] [--rondas 7] [--solo tabla|reabrir|perfil] [--salida DIR]

`--arbol` es el código que se mide (un `checkout`). Con el MISMO Python (el runtime
fijado de `tests/_runtime_ci.py`, en `PRDRIVE_PYTHON`) y un dispositivo de muestra
hecho con `dispositivo.py` (5 y 50 parejas), cada medida es un proceso nuevo y en
frío, como las de `correr.py`: `--rondas` vueltas más una de calentamiento que se
tira, con el orden de las variantes alternado de una vuelta a otra.

- `tabla` (R3): la lista de parejas de tres maneras, `ref` (la del árbol), `ligera`
  (cinco widgets por fila) y `lienzo` (un solo `tk.Canvas`, solo con SVG), con 5, 10,
  20 y 50 filas: `construir`, `elegir`, `refrescar`, `reemplazar` y los widgets.
- `reabrir` (R7): «Parejas», «Ajustes» y la ventana de la pasada, rehechas frente a
  escondidas y enseñadas otra vez.
- `perfil`: un `cProfile` de los momentos lentos de la aplicación, con 5 y 50 parejas.

Deja en `--salida` (por defecto `TRABAJO/salida`): `crudo.jsonl` (todas las líneas),
`resultados.json`, `resumen.md` (con las dos decisiones al principio, que aplica la
tarea 12) y `registro.log`; el resumen se añade a `$GITHUB_STEP_SUMMARY`. Sale con 0
aunque falle una variante: el fallo va en el resumen, y una variante que falla no
cuenta para ninguna cifra.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
import correr  # noqa: E402  -- el Medidor de los procesos hijos

VARIANTES = ("ref", "ligera", "lienzo")
TAMANOS = (5, 10, 20, 50)
VENTANAS = ("parejas", "ajustes", "pasada")
MOMENTOS_TABLA = ("construir", "elegir", "refrescar", "reemplazar")
MOMENTOS_REABRIR = ("abrir-1", "abrir-2", "abrir-3", "reabrir-oculta", "cerrar-destruir",
                    "cerrar-ocultar")
MOMENTOS_PERFIL = ("abrir-parejas", "catalogo-llega", "abrir-ajustes",
                   "apartado-reparacion", "apartado-configuracion")
PAREJAS_PERFIL = (5, 50)

DIF_LIENZO = 20.0
"""Lo que tiene que ganar el lienzo a las filas ligeras en `construir` con 20 filas (ms)."""
DIF_LIGERA = 10.0
"""Lo que tienen que ganar las filas ligeras a la lista de hoy en `construir` con 20 filas (ms)."""
GANANCIA_R7 = 0.50
"""La parte de `abrir-2` que tiene que ahorrar esconder una ventana para adoptarlo."""
MARGEN_GANADOR = 5.0
"""Cuánto peor que otra puede ser la ganadora en `elegir` y `refrescar` (ms)."""

PLAZO_TABLA = 120.0
PLAZO_REABRIR = 180.0
PLAZO_PERFIL = 300.0
"""Segundos que se le da a un hijo de cada bloque antes de matar su árbol."""


def log(*partes) -> None:
    correr.log(*partes)


# ------------------------------------------------------------------ estadística pura
def mediana(valores: list[float]) -> float | None:
    """Devuelve la mediana, o `None` si no hay valores."""
    return statistics.median(valores) if valores else None


def agrupar(registros: list[dict], bloque: str, *campos: str) -> dict[tuple, dict[str, list]]:
    """Agrupa los valores de las vueltas que cuentan: `{(campos...): {momento: [ms...]}}`.

    La vuelta de calentamiento (`ronda < 0`) y los hijos que fallaron no cuentan.
    """
    salida: dict[tuple, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in registros:
        if r.get("bloque") == bloque and r.get("ronda", 0) >= 0 and "scenario" in r:
            salida[tuple(r.get(c) for c in campos)][r["scenario"]].append(float(r["ms"]))
    return salida


def med(grupo: dict[tuple, dict[str, list]], clave: tuple, momento: str) -> float | None:
    """La mediana de un momento de un grupo, o `None` si no se midió."""
    return mediana(grupo.get(clave, {}).get(momento, []))


def decision_r3(tabla: dict) -> dict:
    """Aplica la regla de R3 a las medianas de `construir` con 20 filas.

    Es la regla de la tarea 12: el lienzo si le gana a las filas ligeras por
    `DIF_LIENZO` ms o más; si no, las filas ligeras si le ganan a la lista de hoy
    por `DIF_LIGERA` ms o más; si no, ninguna. La ganadora no puede ser más de
    `MARGEN_GANADOR` ms peor que otra en `elegir` y `refrescar`.

    Args:
        tabla: `agrupar(registros, "tabla", "variante", "n")`.

    Returns:
        `lienzo_vs_ligera`, `ligera_vs_ref` (ms o `None`), `resultado` (`lienzo`,
        `ligera`, `ninguna` o `sin dato`) y `comprobacion` (los momentos en que la
        ganadora pierde por más del margen, a 20 filas).
    """
    ref, ligera, lienzo = (med(tabla, (v, 20), "construir") for v in VARIANTES)
    d_lienzo = None if ligera is None or lienzo is None else ligera - lienzo
    d_ligera = None if ref is None or ligera is None else ref - ligera
    if d_lienzo is None or d_ligera is None:
        resultado = "sin dato"           # sin una de las tres no se puede decidir
    elif d_lienzo >= DIF_LIENZO:
        resultado = "lienzo"
    elif d_ligera >= DIF_LIGERA:
        resultado = "ligera"
    else:
        resultado = "ninguna"
    peor = []
    if resultado in ("lienzo", "ligera"):
        for momento in ("elegir", "refrescar"):
            propia = med(tabla, (resultado, 20), momento)
            for otra in VARIANTES:
                valor = med(tabla, (otra, 20), momento)
                if otra != resultado and propia is not None and valor is not None \
                        and propia - valor > MARGEN_GANADOR:
                    peor.append({"momento": momento, "contra": otra,
                                 "dif_ms": round(propia - valor, 1)})
    return {"lienzo_vs_ligera": d_lienzo, "ligera_vs_ref": d_ligera, "resultado": resultado,
            "comprobacion": peor}


def decision_r7(reabrir: dict) -> dict:
    """Devuelve, por ventana, la ganancia de esconder frente a rehacer y si se adopta.

    `ganancia = 1 - reabrir-oculta / abrir-2`, con las medianas; se adopta con
    `GANANCIA_R7` o más.
    """
    salida = {}
    for ventana in VENTANAS:
        rehacer = med(reabrir, (ventana,), "abrir-2")
        esconder = med(reabrir, (ventana,), "reabrir-oculta")
        ganancia = None if not rehacer or esconder is None else 1 - esconder / rehacer
        salida[ventana] = {"abrir-2": rehacer, "reabrir-oculta": esconder, "ganancia": ganancia,
                           "adopta": None if ganancia is None else ganancia >= GANANCIA_R7}
    return salida


# --------------------------------------------------------------------- el informe
def f1(valor: float | None) -> str:
    """Un número con un decimal, o un guion si no lo hay."""
    return "—" if valor is None else f"{valor:.1f}"


def entero(valor: float | None) -> str:
    """Un número sin decimales, o un guion si no lo hay."""
    return "—" if valor is None else str(int(valor))


def celda(grupo: dict, clave: tuple, momento: str) -> str:
    """`mediana (mínimo)` de un momento, o un guion."""
    valores = grupo.get(clave, {}).get(momento, [])
    return "—" if not valores else f"{statistics.median(valores):.1f} ({min(valores):.1f})"


def si_no(valor: bool | None) -> str:
    return "sin dato" if valor is None else ("SÍ" if valor else "NO")


def lineas_r3(r3: dict) -> list[str]:
    """Las líneas de la decisión de R3."""
    d1, d2 = r3["lienzo_vs_ligera"], r3["ligera_vs_ref"]
    nombres = {"lienzo": "el lienzo", "ligera": "las filas ligeras", "ninguna": "ninguna",
               "sin dato": "sin dato"}
    salida = [
        f"- **R3, lienzo frente a ligera**, `construir` con 20 filas: ligera − lienzo = "
        f"**{f1(d1)} ms**; se adopta el lienzo con {DIF_LIENZO:.0f} ms o más → "
        f"**{si_no(None if d1 is None else d1 >= DIF_LIENZO)}**.",
        f"- **R3, ligera frente a ref**, `construir` con 20 filas: ref − ligera = "
        f"**{f1(d2)} ms**; se adoptan las filas ligeras con {DIF_LIGERA:.0f} ms o más → "
        f"**{si_no(None if d2 is None else d2 >= DIF_LIGERA)}**.",
        f"- **R3, resultado de la regla**: **{nombres[r3['resultado']]}**."]
    if r3["comprobacion"]:
        salida.append("- Comprobación de la ganadora (a 20 filas, no más de "
                      f"{MARGEN_GANADOR:.0f} ms peor que otra): **falla** en "
                      + "; ".join(f"`{c['momento']}` contra {c['contra']} (+{c['dif_ms']} ms)"
                                  for c in r3["comprobacion"]) + ".")
    elif r3["resultado"] in ("lienzo", "ligera"):
        salida.append("- Comprobación de la ganadora en `elegir` y `refrescar`: pasa.")
    return salida


def lineas_r7(r7: dict) -> list[str]:
    """Las líneas de la decisión de R7, una por ventana."""
    salida = []
    for ventana in VENTANAS:
        v = r7[ventana]
        if v["ganancia"] is None:
            salida.append(f"- **R7, {ventana}**: sin dato.")
            continue
        salida.append(f"- **R7, {ventana}**: ganancia = 1 − reabrir-oculta / abrir-2 = 1 − "
                      f"{f1(v['reabrir-oculta'])} / {f1(v['abrir-2'])} = "
                      f"**{v['ganancia']:.2f}**; se adopta con {GANANCIA_R7:.2f} o más → "
                      f"**{si_no(v['adopta'])}**.")
    return salida


def lineas_decision(r3: dict, r7: dict, solo: str | None = None) -> list[str]:
    """Las líneas de decisión que van al principio del resumen.

    Con `solo`, solo las del bloque que se ha medido (ninguna para el perfil).
    """
    if solo == "perfil":
        return []
    salida = ["## Decisiones (las aplica la tarea 12 con la medida de la rama fusionada)", ""]
    if solo != "reabrir":
        salida += lineas_r3(r3)
    if solo != "tabla":
        salida += lineas_r7(r7)
    return salida


def seccion_tabla(tabla: dict, notas: dict) -> list[str]:
    """La tabla de la lista de parejas, y los widgets por fila."""
    salida = ["## Lista de «Parejas» (R3)", "",
              "Milisegundos, mediana y (mínimo) de las vueltas; `widgets` son los de la lista.",
              "", "| Filas | Variante | construir | elegir | refrescar | reemplazar | widgets |",
              "|---|---|---|---|---|---|---|"]
    for n in TAMANOS:
        for v in VARIANTES:
            saltada = notas.get(("saltado", v, n))
            if saltada:
                salida.append(f"| {n} | {v} | saltado: {saltada} | — | — | — | — |")
                continue
            ws = tabla.get((v, n), {}).get("widgets", [])
            salida.append(f"| {n} | {v} | " + " | ".join(
                celda(tabla, (v, n), m) for m in MOMENTOS_TABLA)
                + f" | {entero(mediana(ws))} |")
    por_fila = []
    for v in VARIANTES:
        a, b = med(tabla, (v, 5), "widgets"), med(tabla, (v, 50), "widgets")
        if a is not None and b is not None:
            por_fila.append(f"`{v}` {(b - a) / 45:.1f}")
    if por_fila:
        salida += ["", "Widgets por fila (de 5 a 50 filas): " + ", ".join(por_fila) + "."]
    return salida


def seccion_reabrir(reabrir: dict, aplicar: dict) -> list[str]:
    """La tabla de rehacer frente a esconder.

    Args:
        reabrir: `agrupar(registros, "reabrir", "ventana")`.
        aplicar: Por ventana, si su pantalla tiene `aplicar()` y la reapertura lo llamó.
    """
    salida = ["## Rehacer una ventana frente a esconderla (R7)", "",
              "Milisegundos, mediana y (mínimo). `abrir-1` es la primera apertura, `abrir-2` "
              "la que rehace la ventana tras destruirla y `reabrir-oculta` la que la enseña "
              "de nuevo sin destruirla (`abrir-3` es la apertura que se esconde).", "",
              "| Ventana | " + " | ".join(MOMENTOS_REABRIR) + " | widgets | ganancia |",
              "|---|" + "---|" * (len(MOMENTOS_REABRIR) + 2)]
    r7 = decision_r7(reabrir)
    for ventana in VENTANAS:
        g = r7[ventana]["ganancia"]
        salida.append(f"| {ventana} | " + " | ".join(
            celda(reabrir, (ventana,), m) for m in MOMENTOS_REABRIR)
            + f" | {entero(med(reabrir, (ventana,), 'widgets'))} | "
            + ("—" if g is None else f"{g:.2f}") + " |")
    salida += ["", "La reapertura llamó a `dlg.aplicar()`: " + ", ".join(
        f"{v} {'sí' if aplicar.get(v) else 'no'}" for v in ("parejas", "ajustes")) + "."]
    proceso = med(reabrir, ("pasada",), "proceso")
    if proceso is not None:
        salida += ["", f"Lanzar el proceso de una pasada cuesta {proceso:.1f} ms: "
                   "`reabrir-oculta` de la pasada no lo cuenta y una ventana escondida "
                   "tendría que pagarlo."]
    return salida


def seccion_perfil(perfiles: list[dict]) -> list[str]:
    """Los perfiles, con las diez funciones que más gastan de cada momento."""
    salida = ["## Perfil de los momentos lentos", "",
              "Con `cProfile`: el tiempo se alarga (todo lo que es Python), así que solo "
              "importa el reparto. `Tk` es la parte del tiempo propio dentro de llamadas a "
              "Tcl/Tk (`_tkinter`); `tkapp.call` solo las órdenes de `call`.", ""]
    if not perfiles:
        return salida + ["Sin perfiles."]
    for p in perfiles:
        d = p["detail"]
        parte = "—" if d.get("tk_parte") is None else f"{100 * d['tk_parte']:.0f} %"
        llamadas = "—" if d.get("tk_call_parte") is None else f"{100 * d['tk_call_parte']:.0f} %"
        salida += [f"<details><summary><b>{p['parejas']} parejas · "
                   f"{p['scenario'].removeprefix('perfil-')}</b>: {p['ms']:.0f} ms "
                   f"({d.get('total_ms', 0):.0f} ms propios), Tk {parte}, tkapp.call "
                   f"{llamadas}, {d.get('widgets', '?')} widgets</summary>", "", "```",
                   f"{'propio ms':>10} {'llamadas':>9}  función"]
        for f in d.get("top", [])[:10]:
            salida.append(f"{f['propio_ms']:>10.1f} {f['llamadas']:>9}  {f['funcion']}")
        salida += ["```", "", "</details>", ""]
    return salida


def seccion_fallos(fallos: list[dict]) -> list[str]:
    """Lo que no se pudo medir, con su causa."""
    if not fallos:
        return []
    salida = ["## Fallos", "", "Un hijo que falla no cuenta para ninguna cifra de arriba.", ""]
    vistos = set()
    for f in fallos:
        etiqueta = " ".join(str(f[c]) for c in ("bloque", "variante", "n", "ventana")
                            if f.get(c) is not None)
        clave = (etiqueta, f["error"])
        if clave in vistos:
            continue
        vistos.add(clave)
        salida += [f"- `{etiqueta}` (vuelta {f.get('ronda')}): {f['error']}"]
    return salida


# ----------------------------------------------------------------- el medidor de hijos
class Etapa2(correr.Medidor):
    """Prepara los dispositivos y lanza los hijos de la etapa 2 con el `Medidor` de `correr`."""

    def __init__(self, python: str, arbol: Path, trabajo: Path):
        super().__init__(python, {"pr": arbol}, trabajo)
        self.registros: list[dict] = []
        self.fallos: list[dict] = []
        self.notas: dict = {}
        self.entorno_info: dict = {}
        self.crudo: Path | None = None

    def preparar_dispositivos(self, tamanos: tuple[int, ...]) -> bool:
        """Monta los dispositivos de muestra de esos tamaños y guarda una plantilla de cada uno."""
        ok = True
        env, base = self.entorno()
        for n in tamanos:
            raiz = self.trabajo / f"dev-pr-{n}"
            r = subprocess.run([self.py, "-W", "ignore", str(AQUI / "dispositivo.py"),
                                str(self.arboles["pr"]), str(raiz), str(n)], env=env,
                               cwd=str(self.trabajo), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
            if r.returncode != 0:
                log(f"dispositivo {n}: rc={r.returncode}\n"
                    + r.stdout.decode("utf-8", "replace")[-1500:])
                ok = False
                continue
            correr.copiar(raiz, self.trabajo / f"tpl-pr-{n}")
        correr.borrar(base)
        return ok

    def hijo_etapa2(self, modulo: str, argumentos: list, dispositivo: Path, plazo: float,
                    nuevo: bool) -> dict:
        """Lanza `entrada.py MODULO ARGS` en frío sobre un dispositivo y devuelve su resultado.

        Args:
            nuevo: Si el dispositivo se copia de su plantilla antes (el hijo escribe
                en `state/`); los de la tabla solo lo leen y usan el montado.
        """
        if nuevo:
            correr.copiar(self.trabajo / ("tpl-" + dispositivo.name.removeprefix("dev-")),
                          dispositivo)
        env, base = self.entorno({"BENCH_DEVICE": str(dispositivo)})
        try:
            return self.hijo([self.py, str(self.staging / "entrada.py"), modulo,
                              *[str(a) for a in argumentos]], env, dispositivo, plazo)
        finally:
            correr.borrar(base)

    def anotar(self, resultado: dict, etiqueta: dict, esperados: tuple[str, ...]) -> None:
        """Guarda las líneas de un hijo, o su fallo si no dejó lo esperado.

        Una línea `saltado` (la variante no puede correr aquí) no es un fallo. Las
        líneas de un hijo con error se apuntan en el crudo, marcadas, y no cuentan.
        """
        lineas = resultado["lineas"]
        notas = next((x["detail"] for x in lineas if x["scenario"] == "_notes"), {})
        if notas.get("tk"):
            self.entorno_info.setdefault("tk", notas["tk"])
        if notas.get("python"):
            self.entorno_info.setdefault("python", notas["python"])
        saltado = next((x for x in lineas if x["scenario"] == "saltado"), None)
        if saltado is not None:
            self.notas[("saltado", etiqueta["variante"], etiqueta["n"])] = saltado["detail"][
                "motivo"]
            self.escribir_crudo([dict(etiqueta, **x) for x in lineas])
            return
        error = None
        if resultado["vencio"]:
            error = f"sin terminar en {resultado['plazo']:.0f} s (árbol de procesos matado)"
        elif notas.get("error"):
            error = [s for s in str(notas["error"]).strip().splitlines() if s.strip()][-1][:300]
        else:
            vistos = {x["scenario"] for x in lineas}
            faltan = [e for e in esperados if e not in vistos]
            if faltan:
                error = f"falta {', '.join(faltan)} (rc={resultado['rc']})"
        if error is None and notas.get("errores_parche"):
            error = f"no se pudo sustituir {notas['errores_parche']}"
        if error is not None:
            fallo = dict(etiqueta, error=error)
            self.fallos.append(fallo)
            log(f"{etiqueta}: {error}")
            if resultado["salida"].strip():
                log("salida del hijo:\n" + resultado["salida"][-1500:])
            self.escribir_crudo([dict(etiqueta, **x, fallido=True) for x in lineas] + [fallo])
            return
        registros = [dict(etiqueta, scenario=x["scenario"], ms=x["ms"], detail=x["detail"])
                     for x in lineas if not x["scenario"].startswith("_")]
        if etiqueta["bloque"] == "reabrir":      # los widgets de la ventana, como una medida más
            registros += [dict(etiqueta, scenario="widgets", ms=x["detail"]["widgets"], detail={})
                          for x in lineas if x["scenario"] == "abrir-1"
                          and "widgets" in x["detail"]]
        self.registros += registros
        self.escribir_crudo(registros)

    def escribir_crudo(self, lineas: list[dict]) -> None:
        if self.crudo is None:
            return
        with self.crudo.open("a", encoding="utf-8") as f:
            for d in lineas:
                f.write(json.dumps(d, ensure_ascii=False, default=str) + "\n")

    # ------------------------------------------------------------------ los bloques
    def bloque_tabla(self, rondas: int) -> None:
        """R3: cada variante con cada tamaño, en frío, alternando el orden de las variantes."""
        dev = self.trabajo / "dev-pr-5"
        for ronda in range(-1, rondas):
            giro = ronda % len(VARIANTES)
            variantes = VARIANTES[giro:] + VARIANTES[:giro]
            log(f"tabla: vuelta {ronda + 1}/{rondas}")
            for n in TAMANOS:
                for v in variantes:
                    etiqueta = {"bloque": "tabla", "variante": v, "n": n, "ronda": ronda}
                    try:
                        r = self.hijo_etapa2("etapa2_tabla", [v, n], dev, PLAZO_TABLA, False)
                    except Exception as e:               # noqa: BLE001
                        self.fallos.append(dict(etiqueta, error=f"{type(e).__name__}: {e}"))
                        continue
                    self.anotar(r, etiqueta, MOMENTOS_TABLA + ("widgets",))

    def bloque_reabrir(self, rondas: int) -> None:
        """R7: cada ventana, rehecha y escondida, en frío."""
        dev = self.trabajo / "dev-pr-5"
        for ronda in range(-1, rondas):
            giro = ronda % len(VENTANAS)
            ventanas = VENTANAS[giro:] + VENTANAS[:giro]
            log(f"reabrir: vuelta {ronda + 1}/{rondas}")
            for ventana in ventanas:
                etiqueta = {"bloque": "reabrir", "ventana": ventana, "ronda": ronda}
                try:
                    r = self.hijo_etapa2("etapa2_reabrir", [ventana], dev, PLAZO_REABRIR, True)
                except Exception as e:                   # noqa: BLE001
                    self.fallos.append(dict(etiqueta, error=f"{type(e).__name__}: {e}"))
                    continue
                esperados = ("abrir-1", "abrir-2", "abrir-3", "reabrir-oculta")
                self.anotar(r, etiqueta, esperados)

    def bloque_perfil(self) -> None:
        """El perfil de los momentos lentos, una vez con cada número de parejas."""
        for n in PAREJAS_PERFIL:
            dev = self.trabajo / f"dev-pr-{n}"
            etiqueta = {"bloque": "perfil", "parejas": n, "ronda": 0}
            log(f"perfil con {n} parejas")
            try:
                r = self.hijo_etapa2("etapa2_perfil", [], dev, PLAZO_PERFIL, True)
            except Exception as e:                       # noqa: BLE001
                self.fallos.append(dict(etiqueta, error=f"{type(e).__name__}: {e}"))
                continue
            self.anotar(r, etiqueta, tuple("perfil-" + m for m in MOMENTOS_PERFIL))


def informe(m: Etapa2, plataforma: str, rondas: int, solo: str | None) -> tuple[str, dict]:
    """Arma el resumen en Markdown y el diccionario de `resultados.json`."""
    tabla = agrupar(m.registros, "tabla", "variante", "n")
    reabrir = agrupar(m.registros, "reabrir", "ventana")
    r3, r7 = decision_r3(tabla), decision_r7(reabrir)
    perfiles = sorted((r for r in m.registros if r["bloque"] == "perfil"),
                      key=lambda r: (r["parejas"], MOMENTOS_PERFIL.index(
                          r["scenario"].removeprefix("perfil-"))))
    e = m.entorno_info
    cabecera = [f"# Etapa 2: R3 y R7 medidos en {plataforma}", "",
                f"Python {e.get('python', '?')}, Tk {e.get('tk', '?')}; "
                f"{rondas} vuelta(s) de medida y una de calentamiento que se tira; "
                f"árbol `{os.environ.get('GITHUB_SHA', '')[:7] or 'local'}`.", ""]
    lineas = list(cabecera) + lineas_decision(r3, r7, solo)
    lineas.append("")
    if solo in (None, "tabla"):
        lineas += seccion_tabla(tabla, m.notas) + [""]
    if solo in (None, "reabrir"):
        aplicar = {r["ventana"]: bool(r["detail"].get("aplicar")) for r in m.registros
                   if r["bloque"] == "reabrir" and r["scenario"] == "reabrir-oculta"}
        lineas += seccion_reabrir(reabrir, aplicar) + [""]
    if solo in (None, "perfil"):
        lineas += seccion_perfil(perfiles) + [""]
    lineas += seccion_fallos(m.fallos)
    texto = "\n".join(lineas).rstrip() + "\n"
    datos = {
        "plataforma": plataforma, "rondas": rondas, **m.entorno_info,
        "tabla": {f"{v}/{n}": {mo: {"mediana": mediana(vs), "minimo": min(vs), "vueltas": len(vs)}
                               for mo, vs in momentos.items()}
                  for (v, n), momentos in tabla.items()},
        "saltadas": [{"variante": v, "n": n, "motivo": x}
                     for (k, v, n), x in m.notas.items() if k == "saltado"],
        "reabrir": {w[0]: {mo: {"mediana": mediana(vs), "minimo": min(vs), "vueltas": len(vs)}
                           for mo, vs in momentos.items()}
                    for w, momentos in reabrir.items()},
        "perfil": [{"parejas": p["parejas"], "momento": p["scenario"], "ms": p["ms"],
                    **p["detail"]} for p in perfiles],
        "decision": {"r3": r3, "r7": r7}, "fallos": m.fallos}
    return texto, datos


def main() -> int:
    for f in (sys.stdout, sys.stderr):        # un carácter que la consola no sepa no debe tirar la ejecución
        try:
            f.reconfigure(errors="backslashreplace")
        except Exception:                     # noqa: BLE001
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--arbol", required=True)
    ap.add_argument("--trabajo", required=True)
    ap.add_argument("--python", default=os.environ.get("PRDRIVE_PYTHON"))
    ap.add_argument("--rondas", type=int, default=7)
    ap.add_argument("--solo", choices=("tabla", "reabrir", "perfil"))
    ap.add_argument("--salida")
    ap.add_argument("--plataforma", default=os.environ.get("RENDIMIENTO_PLATAFORMA", ""))
    a = ap.parse_args()
    if not a.python:
        print("falta --python (o PRDRIVE_PYTHON)", file=sys.stderr)
        return 2
    salida = Path(a.salida) if a.salida else Path(a.trabajo) / "salida"
    salida.mkdir(parents=True, exist_ok=True)
    plataforma = a.plataforma or correr.plataforma_local()

    m = Etapa2(a.python, Path(a.arbol).resolve(), Path(a.trabajo))
    m.crudo = salida / "crudo.jsonl"
    m.crudo.write_text("", encoding="utf-8")
    m.preparar_driver()
    tamanos = (5, 50) if a.solo in (None, "perfil") else (5,)
    if not m.preparar_dispositivos(tamanos):
        log("no se pudo montar algún dispositivo de muestra: lo que lo necesite fallará")
    t0 = time.time()
    for bloque in ("tabla", "reabrir", "perfil"):
        if a.solo in (None, bloque):
            try:
                getattr(m, "bloque_" + bloque)(*(() if bloque == "perfil" else (a.rondas,)))
            except Exception as e:                       # noqa: BLE001
                m.fallos.append({"bloque": bloque, "error": f"{type(e).__name__}: {e}"})
                log(f"{bloque}: {type(e).__name__}: {e}")
    texto, datos = informe(m, plataforma, a.rondas, a.solo)
    (salida / "resumen.md").write_text(texto, encoding="utf-8")
    (salida / "resultados.json").write_text(
        json.dumps(datos, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(texto)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(texto + "\n")
    log(f"terminado en {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
