"""Compara lo medido en dos árboles y decide si el PR falla (puro: sin Tk ni procesos).

Entrada: las líneas de `crudo.jsonl` que deja `correr.py` (una por momento medido,
etiquetada con `arbol` = `base` | `pr`, la `ronda`, los `pares` y la `escala`) y el
`presupuesto.toml`. Salida: un veredicto y el resumen en Markdown.

Un PR falla solo por dos cosas (spec del frontend rápido, §5):

1. una **cuenta determinista** por encima de su techo de `presupuesto.toml`: widgets
   por pantalla, pasadas de `<<ThemeChanged>>` al abrir pantallas, estilos creados
   tras el primer widget, módulos importados antes del primer pintado;
2. un **empeoramiento claro frente a la base medido en el mismo trabajo**: la
   mediana del PR pasa de la de la base en más de `PORCENTAJE` Y en más de `MS`
   milisegundos, y el mejor tiempo del PR también pasa del mejor de la base en
   más de `MS` (un vecino ruidoso estropea medianas, no el mínimo).

Las metas de tiempo se informan frente a lo medido, pero no hacen fallar: la máquina
de GitHub varía de una ejecución a otra. También falla que el PR deje de llegar a
un momento al que la base llega (el driver ya no encuentra el botón: hay que
actualizar `driver.py` en el mismo PR).
"""

from __future__ import annotations

import json
import statistics
import tomllib

PORCENTAJE = 0.25
"""Cuánto más lento que la base tiene que ser un momento, en proporción, para fallar."""
MS = 30.0
"""Y cuántos milisegundos más, a la vez."""

ETIQUETAS = {
    "start-main": "Ventana principal, desde que se lanza",
    "apply-main": "  theme.apply() de la principal",
    "llega-instantanea": "Llega a la principal la lectura del estado",
    "marcar": "Marcar una pareja en la principal",
    "sincronizar-ventana": "«Sincronizar ahora», hasta ver la ventana de la pasada",
    "volver-pasada": "Cerrar la ventana de la pasada y volver a la principal",
    "open-parejas": "Abrir «Parejas»",
    "cold-parejas": "«Parejas», desde que se lanza",
    "catalogo-llega": "Llega el catálogo a «Parejas»",
    "elegir-fila": "Elegir otra fila de «Parejas»",
    "elegir-pareja": "Elegir otra pareja de «Parejas»",
    "reabrir-parejas": "Volver a abrir «Parejas»",
    "open-dispositivos": "Abrir «Dispositivos»",
    "llega-flota": "Llegan las notas de la flota a «Dispositivos»",
    "elegir-dispositivo": "Elegir otro dispositivo de «Dispositivos»",
    "open-pareja": "Abrir la ventana de una pareja («Modificar…»)",
    "open-flags": "Abrir el editor de flags",
    "open-ajustes": "Abrir «Ajustes»",
    "pane-reparacion": "Apartado «Reparación»",
    "pane-volumen": "Apartado «Nombre e icono»",
    "pane-actualizaciones": "Apartado «Actualizaciones»",
    "pane-configuracion": "Apartado «Configuración»",
    "pane-otra-vez": "Volver a un apartado ya visto de «Ajustes»",
    "volver-ajustes": "Cerrar «Ajustes» y volver a la principal",
    "start-agente": "Pregunta del agente, desde que se lanza",
    "apply-agente": "  theme.apply() de la pregunta",
    "start-wizard": "Asistente, desde que se lanza",
    "apply-wizard": "  theme.apply() del asistente",
    "paso-dispositivo": "Asistente: pasar al paso «Dispositivo»",
    "log-10k": "10 000 líneas en la ventana de la pasada",
}
"""Los momentos que se comparan, en el orden de la tabla del resumen."""

PANTALLAS_CON_PARES = ("main", "parejas", "ajustes")
"""Las pantallas cuyo tamaño depende de cuántas parejas hay (llevan `.p5`/`.p50`)."""


# ------------------------------------------------------------------------ lectura
def leer(texto: str) -> list[dict]:
    """Las líneas JSON de `crudo.jsonl`, ignorando las que no lo son."""
    lineas = []
    for linea in texto.splitlines():
        try:
            d = json.loads(linea)
        except ValueError:
            continue
        if isinstance(d, dict):
            lineas.append(d)
    return lineas


def _clave(d: dict) -> tuple:
    return (d["scenario"], d.get("pares"), d.get("escala"))


def tiempos(lineas: list[dict]) -> dict[str, dict[tuple, dict]]:
    """Mediana, mínimo, máximo y n de cada momento, por árbol.

    Returns:
        `{arbol: {(escenario, pares, escala): {"mediana", "min", "max", "n", "rss"}}}`.
    """
    por: dict[str, dict[tuple, list[float]]] = {}
    rss: dict[str, dict[tuple, list[float]]] = {}
    for d in lineas:
        if d.get("arbol") not in ("base", "pr") or "ms" not in d or "error" in d:
            continue
        if d["scenario"].startswith("_") or d.get("ronda", -1) < 0:
            continue                                  # el calentamiento se tira
        por.setdefault(d["arbol"], {}).setdefault(_clave(d), []).append(float(d["ms"]))
        r = (d.get("detail") or {}).get("rss_mb")
        if r is not None:
            rss.setdefault(d["arbol"], {}).setdefault(_clave(d), []).append(float(r))
    salida: dict[str, dict[tuple, dict]] = {}
    for arbol, claves in por.items():
        for clave, ms in claves.items():
            salida.setdefault(arbol, {})[clave] = {
                "mediana": round(statistics.median(ms), 1), "min": round(min(ms), 1),
                "max": round(max(ms), 1), "n": len(ms),
                "rss": (round(statistics.median(rss[arbol][clave]), 1)
                        if clave in rss.get(arbol, {}) else None)}
    return salida


def _pares(d: dict) -> str:
    return f".p{d['pares']}" if d.get("pares") else ""


def cuentas(lineas: list[dict], arbol: str) -> dict[str, dict]:
    """Las cuentas deterministas de un árbol, con la clave que usa `presupuesto.toml`.

    Solo al 100 %: a otra escala una pantalla puede necesitar barras de desplazamiento y
    el número cambia sin que el código haya cambiado. `escrituras.marcar` son las
    escrituras a `state/` (`store.write_json`) que caben dentro del clic en una casilla de
    la ventana principal, con la `root.update()` que le sigue; no dependen del tamaño.

    Returns:
        `{clave: {"valor": el mayor visto, "valores": todos los distintos, "por_clase": …}}`.
        Más de un valor distinto en una clave es una cuenta que no es determinista.
    """
    vistos: dict[str, dict] = {}

    def apuntar(clave: str, valor, d: dict) -> None:
        if valor is None:
            return
        v = vistos.setdefault(clave, {"valores": set(), "por_clase": None})
        v["valores"].add(int(valor))
        if clave.startswith("widgets."):
            v["por_clase"] = (d.get("detail") or {}).get("by_class")

    for d in lineas:
        if d.get("arbol") != arbol or "error" in d or d.get("escala") != "1.0":
            continue
        c = (d.get("detail") or {}).get("cuentas")
        if not c:
            continue
        esc = d["scenario"]
        if esc.startswith("start-"):
            pantalla = esc[len("start-"):]
            apuntar(f"widgets.{pantalla}{_pares(d) if pantalla in PANTALLAS_CON_PARES else ''}",
                    c.get("widgets"), d)
            apuntar(f"modulos.{pantalla}", c.get("modulos"), d)
            apuntar(f"tema.arranque.{pantalla}", c.get("tema"), d)
            if pantalla == "main":
                apuntar("estilos.main", c.get("estilos_tardios"), d)
        elif esc in ("open-parejas", "open-ajustes"):
            pantalla = esc[len("open-"):]
            apuntar(f"widgets.{pantalla}{_pares(d)}", c.get("widgets"), d)
            apuntar(f"tema.abrir.{pantalla}", c.get("tema"), d)
            apuntar(f"estilos.{pantalla}", c.get("estilos_tardios"), d)
        elif esc == "open-dispositivos":
            apuntar("tema.abrir.dispositivos", c.get("tema"), d)
            apuntar("estilos.dispositivos", c.get("estilos_tardios"), d)
        elif esc == "llega-flota":
            # Los widgets de «Dispositivos» son los de después de llegar las notas: son los
            # que crecen con los dispositivos. Sin `.p5`: la flota de muestra es la misma.
            apuntar("widgets.dispositivos", c.get("widgets"), d)
        elif esc in ("open-flags", "open-pareja"):
            # Sin `.p5`: la pareja es siempre la primera del dispositivo de muestra.
            pantalla = esc[len("open-"):]
            apuntar(f"widgets.{pantalla}", c.get("widgets"), d)
            apuntar(f"tema.abrir.{pantalla}", c.get("tema"), d)
            apuntar(f"estilos.{pantalla}", c.get("estilos_tardios"), d)
        elif esc.startswith("pane-"):
            apuntar("tema.apartado", c.get("tema"), d)
            apuntar("estilos.apartado", c.get("estilos_tardios"), d)
        elif esc == "llega-instantanea":
            # La principal con la lectura compartida ya aplicada: los widgets que pone la
            # lectura en la ventana (las parejas de la lista). Solo lo mide el flujo `principal`.
            apuntar(f"widgets.main_leida{_pares(d)}", c.get("widgets"), d)
        elif esc == "marcar":
            apuntar("escrituras.marcar", c.get("escrituras"), d)
    for v in vistos.values():
        v["valor"] = max(v["valores"])
        v["valores"] = sorted(v["valores"])
    return vistos


def techos(presupuesto: dict, plataforma: str) -> dict[str, int]:
    """Los techos que valen en esa plataforma: `[techo]` y, encima, `[techo.windows|linux]`."""
    t = {k: v for k, v in presupuesto.get("techo", {}).items() if not isinstance(v, dict)}
    t.update(presupuesto.get("techo", {}).get(plataforma.split("-")[0], {}))
    return t


# --------------------------------------------------------------------- comparación
def comparar(lineas: list[dict], presupuesto: dict, plataforma: str) -> dict:
    """Pone frente a frente la base y el PR.

    Args:
        lineas: Las de `crudo.jsonl`.
        presupuesto: El `presupuesto.toml` ya leído.
        plataforma: `windows-x64`, `linux-x64`, `windows-arm64`…

    Returns:
        `{"filas": [...], "cuentas": [...], "fallos": [str], "avisos": [str],
        "techos_medidos": {clave: valor}}`.
    """
    t = tiempos(lineas)
    base, pr = t.get("base", {}), t.get("pr", {})
    errores = {(d["arbol"], d["scenario"]) for d in lineas if "error" in d and d.get("arbol")}
    metas = presupuesto.get("meta_ms", {}) if plataforma == "windows-x64" else {}
    fallos: list[str] = []
    avisos: list[str] = []
    filas = []
    orden = {e: i for i, e in enumerate(ETIQUETAS)}
    claves = sorted(set(base) | set(pr),
                    key=lambda k: (orden.get(k[0], 99), k[1] or 0, k[2] or ""))
    for clave in claves:
        esc, pares, escala = clave
        if esc not in ETIQUETAS:
            continue
        b, p = base.get(clave), pr.get(clave)
        fila = {"escenario": esc, "pares": pares, "escala": escala, "base": b, "pr": p,
                "estado": "ok", "meta": metas.get(esc) if (escala == "1.0" and pares in (5, None)) else None}
        nombre = f"{ETIQUETAS[esc].strip()} ({pares or '—'} parejas, {_pct(escala)})"
        if b and not p:
            fila["estado"] = "falta"
            fallos.append(f"{nombre}: el PR ya no llega a este momento y la base sí "
                          f"(¿cambió un botón o una pantalla? Actualiza `tests/rendimiento/driver.py`).")
        elif p and not b:
            fila["estado"] = "nuevo"
        elif b and p:
            dif = p["mediana"] - b["mediana"]
            prop = dif / b["mediana"] if b["mediana"] else 0.0
            fila["dif_ms"], fila["dif_pct"] = round(dif, 1), round(prop * 100)
            if dif > MS and prop > PORCENTAJE:
                if p["min"] - b["min"] > MS:
                    fila["estado"] = "peor"
                    fallos.append(f"{nombre}: {b['mediana']:.0f} → {p['mediana']:.0f} ms "
                                  f"(+{dif:.0f} ms, +{prop * 100:.0f} %); mejor tiempo "
                                  f"{b['min']:.0f} → {p['min']:.0f} ms.")
                else:
                    fila["estado"] = "ruido?"
                    avisos.append(f"{nombre}: la mediana sube {dif:.0f} ms (+{prop * 100:.0f} %) "
                                  f"pero el mejor tiempo no ({b['min']:.0f} → {p['min']:.0f} ms): "
                                  f"se toma por ruido de la máquina; vuelve a lanzar el trabajo.")
        filas.append(fila)
    sin_ambos = sorted({s for (a, s) in errores if a == "pr"} - {s for (a, s) in errores if a == "base"})
    for s in sin_ambos:
        avisos.append(f"El PR dio error en `{s}`; la base no.")

    # --- cuentas deterministas
    cb, cp = cuentas(lineas, "base"), cuentas(lineas, "pr")
    tope = techos(presupuesto, plataforma)
    metas_c = presupuesto.get("meta", {})
    filas_c = []
    for clave in sorted(set(cb) | set(cp) | set(tope)):
        vb = cb.get(clave, {}).get("valor")
        vp = cp.get(clave, {}).get("valor")
        techo = tope.get(clave)
        estado = "ok"
        if vb is not None and vp is None:
            estado = "falta"
            fallos.append(f"`{clave}`: el PR ya no llega a medirla y la base sí.")
        elif vp is not None and techo is None:
            estado = "sin techo"
        elif vp is not None and vp > techo:
            estado = "sobre el techo"
            extra = _clases(cb.get(clave, {}).get("por_clase"), cp[clave].get("por_clase"))
            fallos.append(f"`{clave}`: {vp} > techo {techo}" + (f" (base {vb})" if vb is not None else "")
                          + (f"; {extra}" if extra else "") + ".")
        elif vp is not None and vp < techo:
            estado = "techo bajable"
            avisos.append(f"`{clave}` = {vp} y el techo es {techo}: bájalo en `presupuesto.toml`.")
        if vp is not None and len(cp[clave]["valores"]) > 1:
            avisos.append(f"`{clave}` no es determinista en este trabajo: {cp[clave]['valores']} "
                          f"(se compara con el mayor).")
        filas_c.append({"clave": clave, "base": vb, "pr": vp, "techo": techo,
                        "meta": metas_c.get(clave), "estado": estado})
    return {"filas": filas, "cuentas": filas_c, "fallos": fallos, "avisos": avisos,
            "techos_medidos": {c["clave"]: c["pr"] for c in filas_c if c["pr"] is not None},
            "modulos_nuevos": _modulos_nuevos(lineas)}


def _pct(escala: str | None) -> str:
    return {"1.0": "100 %", "2.0": "150 %"}.get(escala or "", escala or "—")


def _clases(antes: dict | None, ahora: dict | None) -> str:
    """«+7 TButton, +14 TLabel»: qué clases de widget explican la subida."""
    if not antes or not ahora:
        return ""
    difs = sorted(((ahora.get(c, 0) - antes.get(c, 0), c) for c in set(antes) | set(ahora)),
                  reverse=True)
    return ", ".join(f"{d:+d} {c}" for d, c in difs[:4] if d)


def _modulos_nuevos(lineas: list[dict]) -> dict[str, list[str]]:
    """Qué módulos carga el PR antes del primer pintado que la base no carga (y al revés)."""
    def lista(arbol: str, esc: str) -> set[str]:
        for d in lineas:
            if (d.get("arbol") == arbol and d["scenario"] == esc and d.get("escala") == "1.0"
                    and (d.get("detail") or {}).get("modulos_lista")):
                return set(d["detail"]["modulos_lista"])
        return set()
    salida = {}
    for esc in ("start-main", "start-agente", "start-wizard"):
        b, p = lista("base", esc), lista("pr", esc)
        if b and p and b != p:
            salida[esc] = [f"+{m}" for m in sorted(p - b)][:25] + [f"-{m}" for m in sorted(b - p)][:25]
    return salida


# ---------------------------------------------------------------------------- texto
def _ms(m: dict | None) -> str:
    return "—" if not m else f"{m['mediana']:.0f}"


def markdown(r: dict, meta: dict) -> str:
    """El resumen del trabajo, para `$GITHUB_STEP_SUMMARY`.

    Args:
        r: Lo que devuelve `comparar()`.
        meta: `plataforma`, `pr`, `base`, `rondas`, `suelo`, `python`, `tk`.
    """
    sl = [f"## Rendimiento: {meta['plataforma']}", "",
          f"PR `{meta['pr']}` frente a `{meta['base']}`, {meta['rondas']} vueltas intercaladas "
          f"(base y PR se alternan en cada vuelta). Python {meta['python']}, Tk {meta['tk']}. "
          f"Suelo (ventana vacía de Tk): {meta['suelo']}.", ""]
    if r["fallos"]:
        sl += [f"**Falla** por {len(r['fallos'])} motivo(s):", ""] + [f"- {f}" for f in r["fallos"]]
    else:
        sl += ["**Pasa.** Nada supera un techo ni empeora claramente frente a la base."]
    if r["avisos"]:
        sl += ["", "Avisos (no hacen fallar):", ""] + [f"- {a}" for a in r["avisos"]]
    sl += ["", "### Momentos (mediana en ms)", "",
           "| Momento | Parejas | Escala | Base | PR | Dif. | Meta | Estado |",
           "|---|---|---|---|---|---|---|---|"]
    for f in r["filas"]:
        dif = "" if "dif_ms" not in f else f"{f['dif_ms']:+.0f} ({f['dif_pct']:+d} %)"
        meta_ms = f["meta"]
        cumple = ""
        if meta_ms is not None and f["pr"]:
            cumple = f"≤ {meta_ms:g} " + ("cumple" if f["pr"]["mediana"] <= meta_ms else "no")
        sl.append(f"| {ETIQUETAS[f['escenario']]} | {f['pares'] or '—'} | {_pct(f['escala'])} | "
                  f"{_ms(f['base'])} | {_ms(f['pr'])} | {dif} | {cumple} | {f['estado']} |")
    efectos = _efectos(r["filas"])
    if efectos:
        sl += ["", "### Efectos en el PR (meta: +20 % al 150 %, +50 ms con 50 parejas)", ""] + efectos
    sl += ["", "### Cuentas deterministas", "",
           "| Cuenta | Base | PR | Techo | Meta | Estado |", "|---|---|---|---|---|---|"]
    for c in r["cuentas"]:
        sl.append(f"| `{c['clave']}` | {'—' if c['base'] is None else c['base']} | "
                  f"{'—' if c['pr'] is None else c['pr']} | "
                  f"{'—' if c['techo'] is None else c['techo']} | "
                  f"{'' if c['meta'] is None else '≤ ' + str(c['meta'])} | {c['estado']} |")
    if r["modulos_nuevos"]:
        sl += ["", "### Módulos antes del primer pintado que cambian frente a la base", ""]
        for esc, mods in r["modulos_nuevos"].items():
            sl.append(f"- `{esc}`: {', '.join(mods)}")
    sl += ["", "<details><summary>Cuentas medidas, para pegar en <code>presupuesto.toml</code></summary>", "",
           "```toml"] + [f'"{k}" = {v}' for k, v in sorted(r["techos_medidos"].items())] + ["```", "",
           "</details>", ""]
    return "\n".join(sl)


def _efectos(filas: list[dict]) -> list[str]:
    """Cuánto cuesta el 150 % y cuánto las 50 parejas, con la mediana del PR."""
    pr = {(f["escenario"], f["pares"], f["escala"]): f["pr"]["mediana"] for f in filas if f["pr"]}
    sl = []
    for esc in ("start-main", "open-parejas", "cold-parejas", "open-ajustes"):
        a, b = pr.get((esc, 5, "1.0")), pr.get((esc, 5, "2.0"))
        if a and b:
            sl.append(f"- 150 % en lugar de 100 %, {ETIQUETAS[esc].strip()}: {a:.0f} → {b:.0f} ms "
                      f"({(b / a - 1) * 100:+.0f} %)")
    for esc in ("start-main", "open-parejas", "cold-parejas"):
        a, b = pr.get((esc, 5, "1.0")), pr.get((esc, 50, "1.0"))
        if a and b:
            sl.append(f"- 50 parejas en lugar de 5, {ETIQUETAS[esc].strip()}: {a:.0f} → {b:.0f} ms "
                      f"({b - a:+.0f} ms)")
    return sl


def cargar_presupuesto(ruta) -> dict:
    """Lee `presupuesto.toml`; un fichero que falta es un presupuesto vacío."""
    try:
        with open(ruta, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
