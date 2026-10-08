"""Corre las rondas del banco de la interfaz y resume (temporal, ver `banco/LEEME.md`).

Cada grupo (`banco/<grupo>/ronda.py`) hace UNA pasada en frío de cada escenario de
sus candidatos y escribe una línea JSON por escenario. Aquí se corre una pasada
de calentamiento por grupo (se tira), luego `rondas` pasadas intercaladas
(tk, qt, tk, qt...) para que una deriva de la máquina toque a todos igual, y al
final una pasada de capturas que prueba que las ventanas se pintan de verdad.

Al final del registro van las líneas `RESULTADO banco ...` (mediana, mínimo,
máximo, n) y `CAPTURA ...`: lo único que hace falta leer del trabajo.

Uso: python banco/correr.py --salida DIR [--grupos tk qt]   (con BANCO_CONF puesto)
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LIMITE = 600
"""Segundos para una pasada de un grupo; pasado eso se corta su árbol entero."""


def matar(proc: subprocess.Popen) -> None:
    """Corta el proceso y todos sus hijos."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        import signal
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass


def pasada(conf: dict, grupo: str, extra: list[str], registro: Path) -> tuple[list[dict], str]:
    """Corre una pasada de un grupo; devuelve sus líneas JSON y un resumen del fallo."""
    orden = [conf["python"], str(REPO / "banco" / grupo / "ronda.py"), *extra]
    opciones = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32" \
        else {"start_new_session": True}
    t = time.time()
    proc = subprocess.Popen(orden, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                            errors="replace", **opciones)
    try:
        salida, errores = proc.communicate(timeout=LIMITE)
        fallo = "" if proc.returncode == 0 else f"rc={proc.returncode}"
    except subprocess.TimeoutExpired:
        matar(proc)
        salida, errores = proc.communicate()
        fallo = f"más de {LIMITE} s"
    lineas = []
    for linea in salida.splitlines():
        try:
            d = json.loads(linea)
        except ValueError:
            continue
        if isinstance(d, dict):
            lineas.append(d)
    with registro.open("a", encoding="utf-8") as f:
        f.write(f"== {grupo} {' '.join(extra)} {time.time() - t:.1f}s {fallo} "
                f"{len(lineas)} líneas\n")
        if fallo or not lineas:
            f.write(errores[-4000:] + "\n")
    if fallo:
        print(f"  {grupo}: {fallo}; últimas líneas de error:\n{errores[-1500:]}", flush=True)
    return lineas, fallo


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", required=True)
    ap.add_argument("--grupos", nargs="+", default=["tk", "qt"])
    ap.add_argument("--rondas", type=int, default=0)
    ap.add_argument("--sin-capturas", action="store_true")
    a = ap.parse_args()
    conf = json.loads(Path(os.environ["BANCO_CONF"]).read_text(encoding="utf-8"))
    rondas = a.rondas or conf.get("rondas", 7)
    salida = Path(a.salida)
    salida.mkdir(parents=True, exist_ok=True)
    registro = salida / "registro.log"
    crudo = salida / "crudo.jsonl"
    crudo.write_text("", encoding="utf-8")
    plat = conf["plataforma"]

    fallos = []
    for grupo in a.grupos:
        print(f"calentamiento: {grupo}", flush=True)
        _, fallo = pasada(conf, grupo, [], registro)
        if fallo:
            fallos.append(f"calentamiento {grupo}: {fallo}")
    errores = []
    for i in range(rondas):
        for grupo in a.grupos:
            print(f"ronda {i + 1}/{rondas}: {grupo}", flush=True)
            lineas, fallo = pasada(conf, grupo, [], registro)
            if fallo:
                fallos.append(f"ronda {i + 1} {grupo}: {fallo}")
            with crudo.open("a", encoding="utf-8") as f:
                for d in lineas:
                    d["ronda"] = i
                    f.write(json.dumps(d, ensure_ascii=False) + "\n")
                    if "error" in d and i == 0:
                        errores.append(f"{d.get('candidate')} {d.get('scenario')}: {d['error']}")

    grupos: dict[tuple[str, str], list[dict]] = {}
    for linea in crudo.read_text(encoding="utf-8").splitlines():
        d = json.loads(linea)
        if "ms" in d and "candidate" in d and "scenario" in d:
            grupos.setdefault((d["candidate"], d["scenario"]), []).append(d)
    resumen = []
    for (cand, esc), ds in sorted(grupos.items()):
        ms = [float(d["ms"]) for d in ds]
        rss = [float(d["detail"]["rss_mb"]) for d in ds
               if isinstance(d.get("detail"), dict) and d["detail"].get("rss_mb") is not None]
        resumen.append({"candidate": cand, "scenario": esc, "n": len(ms),
                        "mediana": round(statistics.median(ms), 1), "min": round(min(ms), 1),
                        "max": round(max(ms), 1),
                        "rss_mb": round(statistics.median(rss), 1) if rss else None})
    (salida / "resumen.json").write_text(
        json.dumps({"plataforma": plat, "rondas": rondas, "fallos": fallos, "errores": errores,
                    "resultados": resumen}, indent=1, ensure_ascii=False), encoding="utf-8")
    md = [f"Plataforma {plat}, {rondas} rondas", "",
          "| candidato | escenario | mediana ms | mín | máx | n | RSS MB |",
          "|---|---|---|---|---|---|---|"]
    md += [f"| {r['candidate']} | {r['scenario']} | {r['mediana']} | {r['min']} | {r['max']} "
           f"| {r['n']} | {r['rss_mb'] if r['rss_mb'] is not None else ''} |" for r in resumen]
    (salida / "resumen.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    capturas = []
    if not a.sin_capturas:
        for grupo in a.grupos:
            print(f"capturas: {grupo}", flush=True)
            lineas, _ = pasada(conf, grupo, ["--captura", str(salida / "capturas")], registro)
            capturas += [d for d in lineas if "captura" in d]

    print("\n=== resumen ===", flush=True)
    for r in resumen:
        print(f"RESULTADO banco {plat} {r['candidate']} {r['scenario']} {r['mediana']} ms "
              f"(min {r['min']}, max {r['max']}, n {r['n']}, rss {r['rss_mb']})")
    for c in capturas:
        info = c.get("info", {})
        print(f"CAPTURA {plat} {c.get('candidate')} {c.get('screen')} ok={info.get('ok')} "
              f"{info.get('ancho')}x{info.get('alto')} colores={info.get('colores')} "
              f"printwindow={info.get('colores_printwindow', '-')} {info.get('motivo', '')}")
    for e in errores:
        print(f"ERROR banco {plat} {e}")
    for f in fallos:
        print(f"FALLO banco {plat} {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
