#!/usr/bin/env python3
"""Ronda del grupo `tk` del banco de la interfaz (temporal, ver `banco/LEEME.md`).

Uso, desde la raíz del repo y con `BANCO_CONF` puesto:

    <python del runtime> banco/tk/ronda.py [--captura DIR] [--solo CAND[,CAND...]] [--presupuesto S]

Por defecto hace UNA pasada en frío de cada escenario de cada candidato, cada
flujo en un proceso nuevo, y escribe una línea JSON por escenario en stdout:

    {"candidate": ..., "scenario": ..., "ms": ..., "detail": {...}}

o, si un escenario falla, `{"candidate": ..., "scenario": ..., "error": "..."}`. Todo
lo demás va a stderr. Sale siempre con 0 (salvo que falte la configuración).

Candidatos (Tk, mismo runtime fijado):
  tk-071            la 0.7.1 tal cual: start-main, open-parejas, cold-parejas, open-ajustes,
                    switch-pane, start-wizard, start-agente
  tk-071-pngcache   «y si»: la 0.7.1 con los PNG de los iconos ya en disco (los pintó otro
                    proceso, el de tk-071) y sin pintarlos en Python. Mismos escenarios
  tk-071-dpi150     la 0.7.1 con `tk scaling` 2.0 (Windows al 150 %): parejas y ajustes
  tk-065            la 0.6.5, la última de antes del rediseño (sin switch-pane)
  tk-flat           ttk plano y ligero (97 widgets en Parejas): start-main, cold-parejas, open-parejas
  tk-bare           el suelo: una ventana de Tk desnuda (start-bare)
  tk-widgets        coste de un widget: plain-N y drawn-N, con N en 50, 150 y 300

`--captura DIR` no mide: abre cada pantalla una vez y guarda un PNG de la ventana tal
como se ve en pantalla (`banco/captura.py`), una línea `{"captura": ...}` por captura.

Portátil: Windows y Linux, sin bash. Cada hijo se lanza con `subprocess.Popen`
(sesión propia en POSIX, grupo de procesos propio en Windows), con plazo; si se
pasa, se mata el árbol entero (`taskkill /T /F` en Windows, el grupo en POSIX).
El «equipo» falso (HOME, USERPROFILE, APPDATA, LOCALAPPDATA, TEMP, XDG_*) cae dentro
de `trabajo`, así que nada toca el perfil real de quien lo corre.

Presupuesto de tiempo (`--presupuesto`, 200 s por defecto): lo imprescindible va
primero y los extras (ajustes, asistente, agente, 150 %) se omiten, con una línea de
error que lo dice, en cuanto se pasa de lo asignado a cada clase.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True
AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
import utiles  # noqa: E402

T_INICIO = time.time()
REPO = AQUI.parent.parent
PLAZO_HIJO = 35.0
"""Segundos que se le da a un proceso hijo antes de matar su árbol."""

# Qué escenarios salen de cada flujo del driver.
FLUJOS = {
    "parejas": ("start-main", "open-parejas", "cold-parejas"),
    "ajustes": ("open-ajustes", "switch-pane"),
    "wizard": ("start-wizard",),
    "agente": ("start-agente",),
}
TODOS_FLUJOS = ("parejas", "ajustes", "wizard", "agente")
# Los candidatos que corren el código real de prdrive a través del driver.
CANDIDATOS = {
    "tk-071": {"ver": "071", "xft": "ui", "flujos": TODOS_FLUJOS},
    "tk-071-pngcache": {"ver": "071", "xft": "ui", "flujos": TODOS_FLUJOS, "pngcache": True},
    "tk-071-dpi150": {"ver": "071", "xft": "ui", "flujos": ("parejas", "ajustes"),
                      "escala": "2.0"},
    "tk-065": {"ver": "065", "xft": "precarga", "flujos": TODOS_FLUJOS,
               "sin": ("switch-pane",), "paneles": False},
}
FLAT = ("start-main", "cold-parejas", "open-parejas")
PANTALLA_FLAT = {"start-main": "main", "cold-parejas": "parejas"}
WIDGETS = ((50, "plain"), (50, "drawn"), (150, "plain"), (150, "drawn"),
           (300, "plain"), (300, "drawn"))
TODOS = ("tk-071", "tk-071-pngcache", "tk-071-dpi150", "tk-065", "tk-flat", "tk-bare",
         "tk-widgets")


def version_de(cand: str, arg: str) -> str:
    """La versión de prdrive cuyo dispositivo necesita ese trabajo ('' si ninguno)."""
    if cand in CANDIDATOS:
        return CANDIDATOS[cand]["ver"]
    return "071" if cand == "tk-widgets" and arg.startswith("drawn") else ""


def log(*partes) -> None:
    print(f"[tk +{time.time() - T_INICIO:5.1f}s]", *partes, file=sys.stderr, flush=True)


def linea(d: dict) -> None:
    print(json.dumps(d), flush=True)          # ASCII puro: da igual la página de códigos de la consola


def error(cand: str, esc: str, texto: str) -> None:
    linea({"candidate": cand, "scenario": esc, "error": " ".join(str(texto).split())[:300]})


# ---------------------------------------------------------------------- ficheros
def _escribible(func, ruta, *_):
    os.chmod(ruta, stat.S_IWRITE)
    func(ruta)


def borrar(ruta: Path) -> None:
    """Borra un árbol; en Windows reintenta (un antivirus o un proceso recién muerto lo retienen)."""
    clave = "onexc" if sys.version_info >= (3, 12) else "onerror"
    for i in range(6):
        try:
            shutil.rmtree(ruta, **{clave: _escribible})
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.25 * (i + 1))
    shutil.rmtree(ruta, ignore_errors=True)


def copiar(origen: Path, destino: Path) -> None:
    """Copia un árbol entero, sin enlaces simbólicos (portátil), conservando fechas."""
    borrar(destino)
    shutil.copytree(origen, destino, symlinks=False)


# ----------------------------------------------------------------------- entorno
class Ronda:
    def __init__(self, conf: dict, captura: Path | None, presupuesto: float):
        self.conf = conf
        self.py = conf["python"]
        self.trabajo = Path(conf["trabajo"]).resolve()
        self.trabajo.mkdir(parents=True, exist_ok=True)
        self.captura = captura
        self.presupuesto = presupuesto
        self.staging = self.trabajo / "banco-tk"
        self.pngs = self.trabajo / "pngs-071.pkl"
        self.cache = self.trabajo / "xdg-cache"       # fontconfig (solo Linux): tibia, como en un equipo de uso
        self.tmp = self.trabajo / "tmp"
        self.tmp.mkdir(exist_ok=True)
        self.cuenta = 0
        self.primados: set[str] = set()                # flujos cuyos PNG ya están en el pickle
        self.escribe_pngs = False                      # si tk-071 debe dejar sus PNG al salir

    # -- entorno de un hijo ----------------------------------------------------
    def host_falso(self) -> tuple[dict, Path]:
        """El «equipo» del hijo: HOME y compañía dentro de `trabajo`, nada del perfil real.

        Windows: USERPROFILE/HOME (+ HOMEDRIVE/HOMEPATH), APPDATA, LOCALAPPDATA (de donde
        sacan su sitio `equipo.DIR` y penwatch) y TEMP/TMP. Linux: HOME, XDG_CONFIG_HOME,
        XDG_DATA_HOME (el del agente) y TMPDIR, más la caché de fontconfig, que se conserva
        entre hijos (tibia, como en un equipo de uso). Windows no tiene caché de fontconfig.
        """
        self.cuenta += 1
        base = self.trabajo / "host" / f"h{self.cuenta}"
        borrar(base)
        home, temp = base / "home", base / "temp"
        if utiles.ES_WIN:
            roaming, local = base / "AppData" / "Roaming", base / "AppData" / "Local"
            dirs = (home, roaming, local, temp)
            env = {"HOME": str(home), "USERPROFILE": str(home), "APPDATA": str(roaming),
                   "LOCALAPPDATA": str(local), "TEMP": str(temp), "TMP": str(temp)}
            unidad, resto = os.path.splitdrive(str(home))
            env.update(HOMEDRIVE=unidad, HOMEPATH=resto)
        else:
            config, datos = base / "xdg-config", base / "xdg-data"
            dirs = (home, config, datos, temp, self.cache)
            env = {"HOME": str(home), "XDG_CONFIG_HOME": str(config),
                   "XDG_DATA_HOME": str(datos), "XDG_CACHE_HOME": str(self.cache),
                   "TMPDIR": str(temp)}
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
        return env, base

    def entorno(self, extra: dict | None = None) -> tuple[dict, Path]:
        env = {k: v for k, v in os.environ.items()
               if not k.upper().startswith(("PYTHON", "BENCH_", "BANCO_"))
               and k.upper() not in ("GTK_THEME", "PRDRIVE_TEMA", "TCL_LIBRARY", "TK_LIBRARY",
                                     "TCLLIBPATH")}
        host, base = self.host_falso()
        env.update(host)
        env["PYTHONIOENCODING"] = "utf-8:replace"
        env["BANCO_CAPTURA"] = str(REPO / "banco" / "captura.py")
        env["BANCO_FUENTES"] = str(Path(self.conf["src071"]) / "ui" / "fuentes")
        env.update(extra or {})
        return env, base

    # -- procesos ----------------------------------------------------------------
    def hijo(self, orden: list[str], env: dict, cwd: Path, plazo: float = PLAZO_HIJO) -> dict:
        """Lanza un hijo, espera con plazo y devuelve sus líneas, su salida y cómo acabó."""
        fd, salida_json = tempfile.mkstemp(prefix="bench-out-", suffix=".jsonl", dir=self.tmp)
        os.close(fd)
        env = dict(env, BENCH_OUT=salida_json)
        opciones = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if utiles.ES_WIN
                    else {"start_new_session": True})
        t0 = time.time()
        env["BENCH_T0"] = repr(t0)                     # justo antes de lanzar
        vencio = False
        proc = subprocess.Popen(orden, env=env, cwd=str(cwd), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **opciones)
        try:
            salida, _ = proc.communicate(timeout=plazo)
        except subprocess.TimeoutExpired:
            vencio = True
            utiles.matar_arbol(proc)
            try:
                salida, _ = proc.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                salida = b""
        else:
            if not utiles.ES_WIN:                      # nada que quede colgando del grupo
                utiles.matar_arbol(proc)
        wall = round((time.time() - t0) * 1000, 1)
        lineas = []
        try:
            for x in Path(salida_json).read_text(encoding="utf-8").splitlines():
                if x.strip():
                    lineas.append(json.loads(x))
        except (OSError, ValueError):
            pass
        finally:
            try:
                Path(salida_json).unlink()
            except OSError:
                pass
        return {"lineas": lineas, "salida": salida.decode("utf-8", "replace"), "rc": proc.returncode,
                "vencio": vencio, "wall": wall, "plazo": plazo}

    def orden(self, *modulo_y_args: str) -> list[str]:
        return [self.py, str(self.staging / "entrada.py"), *modulo_y_args]

    # -- preparación (fuera de todo cronómetro) --------------------------------------
    def compilar(self, ruta: Path) -> None:
        subprocess.run([self.py, "-W", "ignore", "-m", "compileall", "-q", str(ruta)],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=120)

    def preparar_staging(self) -> None:
        """Copia los scripts del banco y los compila: el código del banco es «instalado», como el de la app."""
        borrar(self.staging)
        shutil.copytree(AQUI, self.staging,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "ronda.py"))
        self.compilar(self.staging)

    def preparar_dispositivo(self, ver: str) -> bool:
        """Dispositivo de muestra de esa versión, su plantilla y el árbol del asistente/agente."""
        src = Path(self.conf["src" + ver]).resolve()
        raiz = self.trabajo / f"dev-{ver}"
        env, base = self.entorno()
        r = subprocess.run([self.py, "-W", "ignore", str(AQUI / "dispositivo.py"), str(src),
                            str(raiz)], env=env, cwd=str(self.trabajo), stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
        borrar(base)
        if r.returncode != 0:
            log(f"dispositivo {ver}: rc={r.returncode}\n"
                + r.stdout.decode("utf-8", "replace")[-1500:])
            return False
        copiar(raiz, self.trabajo / f"tpl-{ver}")
        # Lo que corre el asistente y el agente (un .exe de PyInstaller lleva el código ya compilado).
        inst = self.trabajo / f"inst-{ver}"
        borrar(inst)
        inst.mkdir()
        ign = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
        for d in ("common", "ui", "install"):
            shutil.copytree(src / d, inst / d, ignore=ign)
        shutil.copy2(src / "VERSION", inst / "VERSION")
        self.compilar(inst)
        return True

    def restaurar(self, ver: str) -> Path:
        """Un dispositivo nuevo en el mismo sitio donde se hicieron sus bases (la ruta entra en el nombre)."""
        dev = self.trabajo / f"dev-{ver}"
        copiar(self.trabajo / f"tpl-{ver}", dev)
        return dev

    # -- un flujo del driver ---------------------------------------------------------------
    def flujo(self, cand: str, flujo: str, informar: bool = True) -> None:
        c = CANDIDATOS[cand]
        esperados = tuple(e for e in FLUJOS[flujo] if e not in c.get("sin", ()))
        ver = c["ver"]
        solo_codigo = flujo in ("wizard", "agente")     # no usan el dispositivo, sino el árbol compilado
        dev = self.trabajo / f"dev-{ver}" if solo_codigo else self.restaurar(ver)
        extra = {"BENCH_DEVICE": str(dev), "BENCH_FLOW": flujo, "BENCH_XFT": c["xft"],
                 "BENCH_CAND": cand}
        cwd = dev
        if solo_codigo:
            cwd = self.trabajo / f"inst-{ver}"
            extra["BENCH_APP"] = str(cwd)
        if c.get("escala"):
            extra["BENCH_SCALE"] = c["escala"]
        if c.get("paneles") is False:
            extra["BENCH_PANES"] = "0"
        if c.get("pngcache"):
            extra["BENCH_PNGCACHE"] = str(self.pngs)
        elif cand == "tk-071" and self.escribe_pngs:
            # Al salir, ya medido, deja sus PNG para el candidato pngcache (no los carga: no altera lo medido).
            extra["BENCH_PNGCACHE_OUT"] = str(self.pngs)
        if self.captura:
            extra["BENCH_CAPTURA"] = str(self.captura)
        env, base = self.entorno(extra)
        try:
            r = self.hijo(self.orden("driver"), env, cwd)
        finally:
            borrar(base)
        if cand == "tk-071":
            self.primados.add(flujo)
        if informar:
            self.informar(cand, esperados, r, flujo)

    def informar(self, cand: str, esperados: tuple, r: dict, flujo: str) -> None:
        """Convierte lo que dejó un hijo en las líneas del contrato (o en capturas, con --captura)."""
        notas = next((x["detail"] for x in r["lineas"] if x["scenario"] == "_notes"), {})
        capturas = [x["detail"] for x in r["lineas"] if x["scenario"] == "_captura"]
        if self.captura:
            for cp in capturas:
                linea({"captura": cp["file"], "candidate": cand, "screen": cp["screen"],
                       "info": cp["info"]})
            if not capturas or notas.get("error") or r["vencio"]:
                self.fallo(cand, f"captura-{flujo}", r, notas)
            return
        vistos = set()
        for x in r["lineas"]:
            esc = x["scenario"]
            if esc.startswith("_") or esc not in esperados:
                continue
            vistos.add(esc)
            d = dict(x["detail"])
            d.setdefault("process_wall_ms", r["wall"])
            d.setdefault("xft_mode", CANDIDATOS[cand]["xft"] if utiles.ES_LINUX else "n/a")
            if esc == "open-parejas":
                for k, v in notas.items():
                    if k.startswith(("parejas_", "open_parejas_second")):
                        d[k] = v
            if esc in ("start-main", "start-wizard", "start-agente"):
                for k, v in notas.items():
                    if k.startswith("pngcache_"):
                        d[k] = v
            linea({"candidate": cand, "scenario": esc, "ms": x["ms"], "detail": d})
        for esc in esperados:
            if esc not in vistos:
                self.fallo(cand, esc, r, notas)

    def fallo(self, cand: str, esc: str, r: dict, notas: dict) -> None:
        """Una línea de error con la causa más corta que se sepa, y la salida del hijo a stderr."""
        if r["vencio"]:
            causa = f"sin terminar en {r['plazo']:.0f} s (árbol de procesos matado)"
        elif notas.get("error"):
            causa = [s for s in str(notas["error"]).strip().splitlines() if s.strip()][-1]
        else:
            causa = f"sin resultado (rc={r['rc']})"
        error(cand, esc, causa)
        if r["salida"].strip():
            log(f"salida de {cand}/{esc}:\n" + r["salida"][-2500:])
        if notas.get("error"):
            log(f"error de {cand}/{esc}:\n" + str(notas["error"])[-2500:])

    # -- los demás candidatos ----------------------------------------------------------------
    def flat(self, esc: str) -> None:
        extra = {"BENCH_CAND": "tk-flat"}
        orden = self.orden("flat.run", esc)
        destino = None
        if self.captura:
            destino = self.captura / f"tk-flat-{PANTALLA_FLAT[esc]}.png"
            orden += ["--captura", str(destino)]
        env, base = self.entorno(extra)
        try:
            r = self.hijo(orden, env, self.staging)
        finally:
            borrar(base)
        if self.captura:
            for cp in (x["detail"] for x in r["lineas"] if x["scenario"] == "_captura"):
                linea({"captura": cp["file"], "candidate": "tk-flat",
                       "screen": PANTALLA_FLAT[esc], "info": cp["info"]})
                return
            self.fallo("tk-flat", f"captura-{esc}", r, {})
            return
        ok = False
        for x in r["lineas"]:
            if x["scenario"] == esc:
                d = dict(x["detail"], process_wall_ms=r["wall"])
                linea({"candidate": "tk-flat", "scenario": esc, "ms": x["ms"], "detail": d})
                ok = True
        if not ok:
            self.fallo("tk-flat", esc, r, {})

    def bare(self) -> None:
        env, base = self.entorno({"BENCH_CAND": "tk-bare"})
        try:
            r = self.hijo(self.orden("suelo"), env, self.staging)
        finally:
            borrar(base)
        for x in r["lineas"]:
            if x["scenario"] == "start-bare":
                d = dict(x["detail"], process_wall_ms=r["wall"])
                linea({"candidate": "tk-bare", "scenario": "start-bare", "ms": x["ms"], "detail": d})
                return
        self.fallo("tk-bare", "start-bare", r, {})

    def widgets(self, n: int, modo: str) -> None:
        extra = {"BENCH_CAND": "tk-widgets"}
        if modo == "drawn":
            extra["BENCH_APP"] = str(self.trabajo / "dev-071" / ".prdrive")
        env, base = self.entorno(extra)
        try:
            r = self.hijo(self.orden("widgets", modo, str(n)), env, self.staging)
        finally:
            borrar(base)
        for x in r["lineas"]:
            if x["scenario"] == f"{modo}-{n}":
                d = dict(x["detail"], process_wall_ms=r["wall"])
                linea({"candidate": "tk-widgets", "scenario": x["scenario"], "ms": x["ms"],
                       "detail": d})
                return
        self.fallo("tk-widgets", f"{modo}-{n}", r, {})

    # -- el plan ------------------------------------------------------------------------------
    def plan(self, sel: list[str]) -> list[tuple]:
        """(clase, candidato, arg, escenarios esperados): lo imprescindible primero, los extras al final."""
        nucleo, extras = [], []
        if self.captura:
            # Una captura por pantalla; pngcache pinta lo mismo que tk-071 (solo main y parejas).
            orden = [("tk-071", TODOS_FLUJOS), ("tk-071-pngcache", ("parejas",)),
                     ("tk-071-dpi150", ("parejas", "ajustes")), ("tk-065", TODOS_FLUJOS)]
            for cand, flujos in orden:
                if cand in sel:
                    nucleo += [("nucleo", cand, f, ()) for f in flujos]
            if "tk-flat" in sel:
                nucleo += [("nucleo", "tk-flat", e, ()) for e in ("start-main", "cold-parejas")]
            return nucleo
        if "tk-bare" in sel:
            nucleo.append(("nucleo", "tk-bare", "", ("start-bare",)))
        if "tk-flat" in sel:
            nucleo += [("nucleo", "tk-flat", e, (e,)) for e in FLAT]
        for cand in ("tk-071", "tk-071-pngcache", "tk-065"):
            if cand in sel:
                nucleo.append(("nucleo", cand, "parejas", FLUJOS["parejas"]))
        if "tk-widgets" in sel:
            nucleo += [("nucleo", "tk-widgets", f"{m}:{n}", (f"{m}-{n}",)) for n, m in WIDGETS]
        for cand in ("tk-071", "tk-071-pngcache", "tk-065"):
            if cand in sel:
                extras.append(("extra", cand, "ajustes", FLUJOS["ajustes"]))
        if "tk-071-dpi150" in sel:
            extras += [("extra", "tk-071-dpi150", f, FLUJOS[f]) for f in ("parejas", "ajustes")]
        for flujo in ("wizard", "agente"):
            for cand in ("tk-071", "tk-071-pngcache", "tk-065"):
                if cand in sel:
                    extras.append(("extra", cand, flujo, FLUJOS[flujo]))
        return nucleo + extras

    def corre(self, trabajo: tuple) -> None:
        clase, cand, arg, esperados = trabajo
        if cand == "tk-bare":
            self.bare()
        elif cand == "tk-flat":
            self.flat(arg)
        elif cand == "tk-widgets":
            modo, n = arg.split(":")
            self.widgets(int(n), modo)
        else:
            if CANDIDATOS[cand].get("pngcache") and arg not in self.primados:
                # No hay PNG guardados de este flujo (tk-071 no lo corrió): se pintan antes, sin informar.
                self.flujo("tk-071", arg, informar=False)
            self.flujo(cand, arg)

    def omitido(self, trabajo: tuple, motivo: str) -> None:
        clase, cand, arg, esperados = trabajo
        if self.captura:
            error(cand, f"captura-{arg}", motivo)
            return
        for esc in esperados:
            error(cand, esc, motivo)

    def correr(self, sel: list[str]) -> None:
        versiones = set()
        for cand in sel:
            if cand in CANDIDATOS:
                versiones.add(CANDIDATOS[cand]["ver"])
        if "tk-widgets" in sel:
            versiones.add("071")
        t = time.time()
        self.preparar_staging()
        malos = set()
        for ver in sorted(versiones):
            if not self.preparar_dispositivo(ver):
                malos.add(ver)
        self.pngs.unlink(missing_ok=True)
        self.escribe_pngs = "tk-071-pngcache" in sel
        log(f"preparado en {time.time() - t:.1f} s (dispositivos: {sorted(versiones - malos)})")
        if self.captura:
            self.captura.mkdir(parents=True, exist_ok=True)
        limite = {"nucleo": self.presupuesto - 30, "extra": self.presupuesto * 0.7}
        for tr in self.plan(sel):
            clase, cand, arg, _ = tr
            ver = version_de(cand, arg)
            if ver in malos:
                self.omitido(tr, f"no se pudo preparar el dispositivo de la {ver}")
                continue
            if time.time() - T_INICIO > limite[clase]:
                self.omitido(tr, "omitido: presupuesto de tiempo agotado")
                continue
            t = time.time()
            try:
                self.corre(tr)
            except Exception as e:                       # noqa: BLE001
                for esc in (tr[3] or (f"captura-{arg}",)):
                    error(cand, esc, f"{type(e).__name__}: {e}")
            log(f"{cand} {arg} {time.time() - t:.1f} s")


def main() -> int:
    for f in (sys.stdout, sys.stderr):        # un carácter que la consola no sepa no debe tirar la ronda
        try:
            f.reconfigure(errors="backslashreplace")
        except Exception:                     # noqa: BLE001
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--captura", metavar="DIR")
    ap.add_argument("--solo", help="candidatos separados por comas (para pruebas)")
    ap.add_argument("--presupuesto", type=float, default=200.0)
    a = ap.parse_args()
    ruta = os.environ.get("BANCO_CONF")
    if not ruta:
        print("falta BANCO_CONF", file=sys.stderr)
        return 2
    conf = json.loads(Path(ruta).read_text(encoding="utf-8"))
    sel = list(TODOS)
    if a.solo:
        sel = [c for c in a.solo.split(",") if c in TODOS]
    ronda = Ronda(conf, Path(a.captura).resolve() if a.captura else None, a.presupuesto)
    try:
        ronda.correr(sel)
    except Exception as e:                               # noqa: BLE001
        error("tk", "ronda", f"{type(e).__name__}: {e}")
    log(f"ronda terminada en {time.time() - T_INICIO:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
