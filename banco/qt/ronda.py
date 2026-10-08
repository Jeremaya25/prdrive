#!/usr/bin/env python3
"""Ronda del candidato Qt del banco de la interfaz (temporal, ver `banco/LEEME.md`).

Una pasada en frío de cada escenario de `qt-pyside6` (PySide6 Widgets, podado), cada
flujo en un proceso nuevo (`qtmain.py`), con el `BENCH_T0` que se toma justo antes de
`Popen`. Escribe por stdout una línea JSON por escenario:

    {"candidate": "qt-pyside6", "scenario": "start-main", "ms": 256.3, "detail": {...}}

o, si falla, `{"candidate": ..., "scenario": ..., "error": "..."}`. Lo demás va a stderr.
Sale siempre con 0.

Escenarios: start-main, cold-parejas, open-parejas, switch-pane y el extra
x-start-main-canned (start-main con los datos ya leídos: el coste del frontend sin los
módulos de `common/`; `--sin-extras` lo quita). `detail` lleva el desglose del arranque
(inicio de Python, import de PySide6, módulos del dispositivo, lectura del estado,
QApplication, fuentes, estilo, construcción, mostrar y pintar), los widgets, la memoria
(`rss_mb`), el Qt y la plataforma con que se corrió y cómo salió el proceso.

`--captura DIR`: no mide; abre cada pantalla (main, parejas, ajustes) y guarda en DIR
`qt-pyside6-<pantalla>.png` tal como se ve en pantalla (`banco/captura.py`), con una
línea `{"captura", "candidate", "screen", "info"}` por pantalla.

Lee `BANCO_CONF` (ver `banco/correr.py`): usa `python`, `src071` (los módulos de
`common/` y `ui/` que lee la aplicación), `qt` (carpeta con `PySide6/` y `shiboken6/`,
que se pone en `sys.path`; si es null o no importa, una línea de error por escenario) y
`trabajo` (donde se monta el dispositivo de 5 parejas, que se reusa entre pasadas
mientras no cambie el código que lo genera). No usa `rondas`: las repite `correr.py`.

Uso: <conf.python> banco/qt/ronda.py [--captura DIR] [--sin-extras] [--solo a,b]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parent.parent
CANDIDATO = "qt-pyside6"
ESCENARIOS = ("start-main", "cold-parejas", "open-parejas", "switch-pane")
EXTRAS = ("x-start-main-canned",)
PANTALLAS = ("main", "parejas", "ajustes")

LIMITE_FLUJO = 90
"""Segundos que puede tardar un proceso; pasado eso se corta su árbol entero."""
GRACIA_SALIDA = 10
"""Segundos que se le dan a un proceso para salir una vez impresa su línea; luego se corta."""
PRESUPUESTO = 200
"""Segundos para toda la ronda; agotados, los escenarios que faltan salen como error."""


# ------------------------------------------------------------------------------------------- salida
def imprimir(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=True), flush=True)


def log(texto: str) -> None:
    print(f"qt: {texto}", file=sys.stderr, flush=True)


def linea_error(nombre: str, texto: str, captura: bool) -> dict:
    texto = " ".join(str(texto).split())[:300]
    if captura:
        return {"captura": None, "candidate": CANDIDATO, "screen": nombre,
                "info": {"ok": False, "ancho": 0, "alto": 0, "colores": 0, "motivo": texto}}
    return {"candidate": CANDIDATO, "scenario": nombre, "error": texto}


# ------------------------------------------------------------------------------------------- procesos
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
    try:
        proc.kill()
    except OSError:
        pass


class Lector(threading.Thread):
    """Vacía un tubo del hijo (si no, un tubo lleno lo bloquearía) y cuenta sus líneas JSON."""

    def __init__(self, flujo) -> None:
        super().__init__(daemon=True)
        self.flujo = flujo
        self.lineas: list[str] = []
        self.json = 0

    def run(self) -> None:
        try:
            for linea in self.flujo:
                linea = linea.rstrip("\r\n")
                self.lineas.append(linea)
                if linea.lstrip().startswith("{"):
                    self.json += 1
        except (OSError, ValueError):
            pass


class Resultado:
    """Lo que dejó un proceso: sus objetos JSON, su stderr, cómo salió y cuánto tardó en salir."""

    def __init__(self) -> None:
        self.objetos: list[dict] = []
        self.stderr = ""
        self.rc: int | None = None
        self.salida = ""
        self.ms_hasta_salida = 0.0

    def ultima_linea_de_error(self) -> str:
        lineas = [x.strip() for x in self.stderr.splitlines() if x.strip()]
        return lineas[-1] if lineas else ""


def correr(orden: list[str], env: dict, limite: float = LIMITE_FLUJO, esperadas: int = 1) -> Resultado:
    """Lanza `orden` en un proceso nuevo con `BENCH_T0` y espera su salida, con tiempo máximo.

    Termina cuando el proceso sale, cuando lleva `GRACIA_SALIDA` s sin salir tras imprimir las
    `esperadas` líneas JSON (0: no se espera ninguna), o al pasar `limite`; en los dos últimos casos
    corta el árbol.
    """
    opciones = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32"
                else {"start_new_session": True})
    r = Resultado()
    env = dict(env)
    t0 = time.time()                                    # justo antes de Popen
    env["BENCH_T0"] = f"{t0:.6f}"
    proc = subprocess.Popen(orden, cwd=REPO, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                            **opciones)
    out, err = Lector(proc.stdout), Lector(proc.stderr)
    out.start()
    err.start()
    fin = time.monotonic() + limite
    visto = None
    estado = ""
    try:
        while proc.poll() is None:
            ahora = time.monotonic()
            if esperadas and out.json >= esperadas and visto is None:
                visto = ahora
            if visto is not None and ahora - visto > GRACIA_SALIDA:
                estado = "colgado al salir (cortado)"
                break
            if ahora > fin:
                estado = f"más de {limite:.0f} s (cortado)"
                break
            time.sleep(0.02)
    finally:
        r.ms_hasta_salida = (time.time() - t0) * 1000
        if proc.poll() is None:
            matar(proc)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            matar(proc)
        out.join(5)
        err.join(5)
    r.rc = proc.returncode
    r.stderr = "\n".join(err.lineas)
    for linea in out.lineas:
        try:
            d = json.loads(linea)
        except ValueError:
            continue
        if isinstance(d, dict):
            r.objetos.append(d)
    r.salida = estado or ("limpia" if r.rc == 0 else f"rc={r.rc}")
    return r


# ------------------------------------------------------------------------------------------- entorno
def entorno(conf: dict, trabajo: Path) -> dict:
    """El entorno de los hijos: el de la máquina, con el estado del equipo aislado y Qt en pantalla de verdad."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["BENCH_QT"] = str(conf["qt"])
    env["BENCH_CANDIDATE"] = CANDIDATO
    for k in ("QT_SCALE_FACTOR", "QT_SCREEN_SCALE_FACTORS"):
        env.pop(k, None)                               # que un factor suelto no cambie el tamaño medido
    anfitrion = trabajo / "anfitrion"                  # lo que mira el agente residente: vacío
    anfitrion.mkdir(parents=True, exist_ok=True)
    qpa = env.get("QT_QPA_PLATFORM", "")
    if sys.platform == "win32":
        env["LOCALAPPDATA"] = str(anfitrion / "local")
        env["APPDATA"] = str(anfitrion / "roaming")
        if qpa in ("", "offscreen", "minimal"):
            env.pop("QT_QPA_PLATFORM", None)           # «windows»: el escritorio de verdad
    else:
        env["XDG_DATA_HOME"] = str(anfitrion / "data")
        env["XDG_CONFIG_HOME"] = str(anfitrion / "config")
        run = env.get("XDG_RUNTIME_DIR", "")
        if not run or not os.access(run, os.W_OK):
            privado = trabajo / "run"
            privado.mkdir(parents=True, exist_ok=True)
            privado.chmod(0o700)
            env["XDG_RUNTIME_DIR"] = str(privado)
        env.pop("WAYLAND_DISPLAY", None)
        if qpa in ("", "offscreen", "minimal"):
            env["QT_QPA_PLATFORM"] = "xcb"
    return env


def huella(conf: dict) -> str:
    """Qué hay que rehacer del dispositivo: el código que se copia, quien lo genera y el intérprete."""
    src = Path(conf["src071"])
    h = hashlib.sha256()
    h.update(str(conf["python"]).encode())
    h.update((AQUI / "lib" / "dispositivo.py").read_bytes())
    for nombre in ("sync.py", "runsync.py", "penwatch.py", "VERSION"):
        f = src / nombre
        if f.is_file():
            e = f.stat()
            h.update(f"{nombre}:{e.st_size}:{e.st_mtime_ns}".encode())
    for sub in ("common", "ui"):
        for carpeta, dirs, nombres in os.walk(src / sub):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for nombre in sorted(nombres):
                if nombre.endswith((".pyc", ".pyo")):
                    continue
                f = Path(carpeta) / nombre
                e = f.stat()
                h.update(f"{f.relative_to(src).as_posix()}:{e.st_size}:{e.st_mtime_ns}".encode())
    return h.hexdigest()


def preparar_dispositivo(conf: dict, trabajo: Path, env: dict) -> tuple[Path, Path | None]:
    """Monta (o reusa) el dispositivo de 5 parejas y su volcado de datos; devuelve (raíz, volcado|None)."""
    dev = trabajo / "dispositivo"
    marca = trabajo / "dispositivo.json"
    volcado = trabajo / "volcado.json"
    clave = huella(conf)
    try:
        al_dia = json.loads(marca.read_text(encoding="utf-8")).get("huella") == clave
    except (OSError, ValueError):
        al_dia = False
    if not (al_dia and (dev / ".prdrive" / "sync_config.toml").is_file()):
        marca.unlink(missing_ok=True)
        volcado.unlink(missing_ok=True)
        t = time.time()
        p = subprocess.run([conf["python"], str(AQUI / "lib" / "dispositivo.py"), conf["src071"], str(dev)],
                           cwd=REPO, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=240)
        if p.returncode != 0:
            raise RuntimeError("no se pudo montar el dispositivo: "
                               + (p.stderr.strip().splitlines() or [f"rc={p.returncode}"])[-1])
        log(f"dispositivo montado en {time.time() - t:.1f} s")
        marca.write_text(json.dumps({"huella": clave}), encoding="utf-8")
    if not volcado.is_file():
        r = correr([conf["python"], str(AQUI / "qtmain.py"), "--scenario", "volcar", "--device", str(dev),
                    "--salida", str(volcado)], env, limite=120, esperadas=0)
        if r.rc != 0 or not volcado.is_file():
            log("no se pudo volcar los datos (el extra canned saldrá como error): " + r.ultima_linea_de_error())
            return dev, None
    return dev, volcado


# ------------------------------------------------------------------------------------------- principal
def main() -> int:
    ap = argparse.ArgumentParser(description="Ronda del candidato Qt del banco de la interfaz.")
    ap.add_argument("--captura", metavar="DIR", help="guarda una captura de cada pantalla en DIR en vez de medir")
    ap.add_argument("--sin-extras", action="store_true", help="sin x-start-main-canned")
    ap.add_argument("--solo", metavar="A,B", help="solo estos escenarios (o pantallas, con --captura)")
    a = ap.parse_args()
    captura = bool(a.captura)
    nombres = list(PANTALLAS if captura else ESCENARIOS + (() if a.sin_extras else EXTRAS))
    if a.solo:
        nombres = [n for n in nombres if n in a.solo.split(",")]

    def todos(texto: str) -> int:
        for n in nombres:
            imprimir(linea_error(n, texto, captura))
        return 0

    inicio = time.monotonic()
    try:
        conf = json.loads(Path(os.environ["BANCO_CONF"]).read_text(encoding="utf-8-sig"))
    except (KeyError, OSError, ValueError) as e:
        return todos(f"BANCO_CONF no se puede leer: {type(e).__name__}: {e}")
    qt = conf.get("qt")
    if qt:
        qt = conf["qt"] = str(Path(qt).resolve())        # los hijos cambian de carpeta de trabajo
    if not qt:
        return todos("sin Qt: conf.qt es null (no se pudo bajar o podar PySide6)")
    if not (Path(qt) / "PySide6").is_dir() or not (Path(qt) / "shiboken6").is_dir():
        return todos(f"sin Qt: {qt} no tiene PySide6/ y shiboken6/")
    if not Path(conf["python"]).is_file():
        return todos(f"no existe el intérprete {conf['python']}")
    trabajo = Path(conf["trabajo"]).resolve() / "qt"
    trabajo.mkdir(parents=True, exist_ok=True)
    env = entorno(conf, trabajo)
    python = conf["python"]

    try:
        dev, volcado = preparar_dispositivo(conf, trabajo, env)
    except Exception as e:                                       # noqa: BLE001
        return todos(f"{type(e).__name__}: {e}")
    env["BENCH_DEVICE"] = str(dev)
    if volcado is not None:
        env["BENCH_CANNED"] = str(volcado)

    # ¿Importa Qt? Una vez, en vez de fallar igual en cada escenario (y de paso lo deja en la caché de páginas).
    r = correr([python, str(AQUI / "qtmain.py"), "--scenario", "comprobar"], env, limite=120)
    comprobado = next((o for o in r.objetos if o.get("comprobar")), None)
    if comprobado is None:
        return todos("PySide6 no importa: " + (r.ultima_linea_de_error() or r.salida))
    log(f"Qt {comprobado.get('qt')}, PySide6 {comprobado.get('pyside')}, import {comprobado.get('ms')} ms")

    if captura:
        r = correr([python, str(AQUI / "qtmain.py"), "--scenario", "capturas", "--device", str(dev),
                    "--captura", str(Path(a.captura).resolve())], env, limite=150, esperadas=len(PANTALLAS))
        hechas = set()
        for o in r.objetos:
            if "captura" in o:
                hechas.add(o.get("screen"))
                imprimir(o)
        for n in nombres:
            if n not in hechas:
                imprimir(linea_error(n, r.ultima_linea_de_error() or f"sin captura ({r.salida})", True))
        return 0

    for n in nombres:
        if time.monotonic() - inicio > PRESUPUESTO:
            imprimir(linea_error(n, f"se agotó el tiempo de la ronda ({PRESUPUESTO} s)", False))
            continue
        extra = n in EXTRAS
        if extra and volcado is None:
            imprimir(linea_error(n, "sin los datos volcados para el extra canned", False))
            continue
        base = n[2:-len("-canned")] if extra else n
        orden = [python, str(AQUI / "qtmain.py"), "--scenario", base, "--device", str(dev)]
        if extra:
            orden.append("--canned")
        r = correr(orden, env)
        res = next((o for o in r.objetos if o.get("scenario") == n), None)
        if res is None:
            imprimir(linea_error(n, f"sin resultado (rc={r.rc}, {r.salida}): {r.ultima_linea_de_error()}", False))
            continue
        if isinstance(res.get("detail"), dict):
            res["detail"]["salida"] = r.salida
            res["detail"]["hasta_salida_ms"] = round(r.ms_hasta_salida, 1)
        imprimir(res)
        if "ms" in res:
            log(f"{n}: {res['ms']} ms (salida {r.salida})")
        else:
            log(f"{n}: error: {res.get('error')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
