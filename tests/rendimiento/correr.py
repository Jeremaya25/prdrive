#!/usr/bin/env python3
"""Mide la interfaz de dos árboles de código en el mismo trabajo y compara (CI: `rendimiento.yml`).

    python tests/rendimiento/correr.py --pr DIR --base DIR --trabajo DIR
        [--python PY] [--rondas 7] [--salida DIR] [--capturas]

`--pr` es el árbol que se prueba y `--base` el de la rama a la que irá (otro
`checkout` en otra carpeta). Los dos se miden con el MISMO Python (el runtime
fijado de `tests/_runtime_ci.py`, que deja su ruta en `PRDRIVE_PYTHON`) y el MISMO
driver, el de `--pr`: el driver sabe llegar a cada pantalla, el árbol solo pone el
código. Una vuelta es una pasada de cada árbol, y el orden se alterna de una
vuelta a otra (base-PR, PR-base…), así una deriva de la máquina toca a los dos
igual. Antes de la primera hay una pasada de calentamiento por árbol que se tira.

Una pasada = un proceso nuevo, en frío, por flujo (`PLAN`): cada uno con su
dispositivo de muestra recién copiado, su `HOME` falso y un plazo; si se pasa se
mata el árbol de procesos entero (`taskkill /T /F` en Windows, el grupo en
POSIX). Nada toca el perfil de quien lo corre. Portátil: Windows y Linux, sin bash.

Deja en `--salida` (por defecto `TRABAJO/salida`): `crudo.jsonl` (todas las
líneas), `resumen.md`, `resumen.json` y `registro.log`; con `--capturas`, un PNG
por pantalla del PR, que prueban que la máquina pinta de verdad. El resumen se
añade a `$GITHUB_STEP_SUMMARY`. Sale con 1 si el PR falla (`informe.py`), con 2
si no se pudo medir.
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
import informe  # noqa: E402
import utiles  # noqa: E402

T_INICIO = time.time()
PLAZO_HIJO = 60.0
"""Segundos que se le da a un proceso hijo antes de matar su árbol."""

PLAN = (
    # (flujo, parejas, escala de Tk). La escala 2.0 es Windows al 150 %.
    ("parejas", 5, "1.0"), ("parejas", 50, "1.0"), ("parejas", 5, "2.0"),
    ("ajustes", 5, "1.0"), ("ajustes", 50, "1.0"), ("ajustes", 5, "2.0"),
    ("principal", 5, "1.0"), ("principal", 50, "1.0"),
    ("wizard", None, "1.0"), ("agente", None, "1.0"), ("log", None, "1.0"),
)
"""Lo que hace una pasada. «Parejas» y «Ajustes» con 5 y 50 parejas y al 150 %; la
ventana principal (marcar, sincronizar, volver de la pasada) con 5 y 50 al 100 %."""
PLAN_CAPTURAS = (("parejas", 5, "1.0"), ("ajustes", 5, "1.0"), ("wizard", None, "1.0"),
                 ("agente", None, "1.0"), ("log", None, "1.0"), ("parejas", 5, "2.0"),
                 ("ajustes", 5, "2.0"))
ESPERADOS = {
    "parejas": ("start-main", "apply-main", "open-parejas", "cold-parejas", "elegir-fila",
                "elegir-pareja", "reabrir-parejas"),
    "ajustes": ("open-ajustes", "pane-reparacion", "pane-volumen", "pane-actualizaciones",
                "pane-configuracion", "pane-otra-vez", "volver-ajustes"),
    "principal": ("marcar", "sincronizar-ventana", "volver-pasada"),
    "wizard": ("start-wizard", "apply-wizard"),
    "agente": ("start-agente", "apply-agente"),
    "log": ("log-10k",),
}
"""Los momentos que tiene que dejar cada flujo; si falta uno, es un error y no un hueco."""


def plataforma_local() -> str:
    """`windows-x64`, `linux-arm64`…: las claves de `common/pins.py`."""
    import platform
    arquitectura = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    return ("windows" if utiles.ES_WIN else "linux") + "-" + arquitectura


def corto(ref: str) -> str:
    """Un commit largo, a siete caracteres; una rama, tal cual."""
    return ref[:7] if len(ref) == 40 and all(c in "0123456789abcdef" for c in ref) else ref


def log(*partes) -> None:
    print(f"[+{time.time() - T_INICIO:6.1f}s]", *partes, file=sys.stderr, flush=True)


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


# ------------------------------------------------------------------------ entorno
class Medidor:
    """Prepara los dos árboles una vez y hace las pasadas.

    Args:
        python: El intérprete del runtime fijado con el que se corren todos los hijos.
        arboles: `{"base": Path, "pr": Path}`: raíces de código.
        trabajo: Carpeta de trabajo (dispositivos, copias, ficheros temporales).
    """

    def __init__(self, python: str, arboles: dict[str, Path], trabajo: Path):
        self.py = python
        self.arboles = arboles
        self.trabajo = trabajo.resolve()
        self.trabajo.mkdir(parents=True, exist_ok=True)
        self.staging = self.trabajo / "driver"
        self.cache = self.trabajo / "xdg-cache"        # fontconfig (solo Linux): tibia, como en un equipo de uso
        self.tmp = self.trabajo / "tmp"
        self.tmp.mkdir(exist_ok=True)
        self.cuenta = 0
        self.malos: set[str] = set()                   # árboles de los que no se pudo montar el dispositivo

    # -- entorno de un hijo ----------------------------------------------------
    def host_falso(self) -> tuple[dict, Path]:
        """El «equipo» del hijo: HOME y compañía dentro de `trabajo`, nada del perfil real."""
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
               if not k.upper().startswith(("PYTHON", "BENCH_", "PRDRIVE_"))
               and k.upper() not in ("GTK_THEME", "TCL_LIBRARY", "TK_LIBRARY", "TCLLIBPATH")}
        host, base = self.host_falso()
        env.update(host)
        env["PYTHONIOENCODING"] = "utf-8:replace"
        env["PRDRIVE_TEMA"] = "claro"                  # el mismo tema en todas las máquinas
        env.update(extra or {})
        return env, base

    # -- procesos --------------------------------------------------------------------
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

    # -- preparación (fuera de todo cronómetro) --------------------------------------
    def compilar(self, ruta: Path) -> None:
        subprocess.run([self.py, "-W", "ignore", "-m", "compileall", "-q", str(ruta)],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=180)

    def preparar_driver(self) -> None:
        """Copia los scripts del driver (sin este fichero) y los compila, como código instalado."""
        borrar(self.staging)
        shutil.copytree(AQUI, self.staging, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", "correr.py", "informe.py", "presupuesto.toml"))
        self.compilar(self.staging)

    def preparar_arbol(self, arbol: str) -> bool:
        """Los dispositivos de muestra (5 y 50 parejas) y el árbol del asistente, el agente y el log."""
        src = self.arboles[arbol]
        env, base = self.entorno()
        ok = True
        for n in sorted({n for _, n, _ in PLAN if n}):
            raiz = self.trabajo / f"dev-{arbol}-{n}"
            r = subprocess.run([self.py, "-W", "ignore", str(AQUI / "dispositivo.py"), str(src),
                                str(raiz), str(n)], env=env, cwd=str(self.trabajo),
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=300)
            if r.returncode != 0:
                log(f"dispositivo {arbol}/{n}: rc={r.returncode}\n" + r.stdout.decode("utf-8", "replace")[-1500:])
                ok = False
                continue
            copiar(raiz, self.trabajo / f"tpl-{arbol}-{n}")
        borrar(base)
        # Lo que corren el asistente, el agente y la ventana de la pasada (un .exe de
        # PyInstaller lleva el código ya compilado).
        inst = self.trabajo / f"inst-{arbol}"
        borrar(inst)
        inst.mkdir()
        ign = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
        for d in ("common", "ui", "install"):
            shutil.copytree(src / d, inst / d, ignore=ign)
        for f in ("VERSION", "agente.py", "penwatch.py", "pregunta.py"):
            if (src / f).exists():
                shutil.copy2(src / f, inst / f)
        self.compilar(inst)
        if not ok:
            self.malos.add(arbol)
        return ok

    # -- un flujo ----------------------------------------------------------------------
    def flujo(self, arbol: str, flujo: str, pares: int | None, escala: str,
              captura: Path | None = None, nombre: str = "") -> list[dict]:
        """Un proceso en frío de un flujo; devuelve sus líneas listas para `crudo.jsonl`."""
        solo_codigo = flujo in ("wizard", "agente", "log")     # no usan el dispositivo, sino el árbol compilado
        if solo_codigo:
            dev = self.trabajo / f"dev-{arbol}-5"
            cwd = self.trabajo / f"inst-{arbol}"
        else:
            dev = self.trabajo / f"dev-{arbol}-{pares}"
            copiar(self.trabajo / f"tpl-{arbol}-{pares}", dev)    # la ruta entra en el nombre de las bases
            cwd = dev
        extra = {"BENCH_DEVICE": str(dev), "BENCH_FLOW": flujo, "BENCH_SCALE": "" if escala == "1.0" else escala}
        if solo_codigo:
            extra["BENCH_APP"] = str(cwd)
        if captura:
            extra["BENCH_CAPTURA"] = str(captura)
            extra["BENCH_NOMBRE"] = nombre
        env, base = self.entorno(extra)
        try:
            r = self.hijo([self.py, str(self.staging / "entrada.py"), "driver"], env, cwd)
        finally:
            borrar(base)
        notas = next((x["detail"] for x in r["lineas"] if x["scenario"] == "_notes"), {})
        etiqueta = {"arbol": arbol, "flujo": flujo, "pares": pares, "escala": escala}
        if captura:
            return [dict(etiqueta, captura=x["detail"]["file"], screen=x["detail"]["screen"],
                         info=x["detail"]["info"]) for x in r["lineas"] if x["scenario"] == "_captura"]
        salida = [dict(etiqueta, **x) for x in r["lineas"] if not x["scenario"].startswith("_")]
        vistos = {x["scenario"] for x in salida}
        for esc in ESPERADOS[flujo]:
            if esc not in vistos:
                salida.append(dict(etiqueta, scenario=esc, error=self.causa(r, notas)))
                log(f"{arbol} {flujo}: falta {esc}: {salida[-1]['error']}")
                if r["salida"].strip():
                    log("salida del hijo:\n" + r["salida"][-2000:])
        if notas.get("error"):
            log(f"{arbol} {flujo} {pares} {escala}: {str(notas['error'])[-1500:]}")
        if notas.get("errores_parche"):
            log(f"{arbol} {flujo}: el driver no pudo sustituir {notas['errores_parche']}")
        return salida

    @staticmethod
    def causa(r: dict, notas: dict) -> str:
        if r["vencio"]:
            return f"sin terminar en {r['plazo']:.0f} s (árbol de procesos matado)"
        if notas.get("error"):
            return [s for s in str(notas["error"]).strip().splitlines() if s.strip()][-1][:300]
        return f"sin resultado (rc={r['rc']})"

    def suelo(self) -> list[dict]:
        env, base = self.entorno({"BENCH_FLOW": "suelo"})
        try:
            r = self.hijo([self.py, str(self.staging / "entrada.py"), "suelo"], env, self.staging)
        finally:
            borrar(base)
        return [dict(x, arbol="suelo", flujo="suelo") for x in r["lineas"]
                if x["scenario"] == "start-bare"]

    def pasada(self, arbol: str) -> list[dict]:
        lineas = []
        for flujo, pares, escala in PLAN:
            try:
                lineas += self.flujo(arbol, flujo, pares, escala)
            except Exception as e:                       # noqa: BLE001
                lineas.append({"arbol": arbol, "flujo": flujo, "pares": pares, "escala": escala,
                               "scenario": ESPERADOS[flujo][0], "error": f"{type(e).__name__}: {e}"})
        return lineas


def main() -> int:
    for f in (sys.stdout, sys.stderr):        # un carácter que la consola no sepa no debe tirar la ejecución
        try:
            f.reconfigure(errors="backslashreplace")
        except Exception:                     # noqa: BLE001
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--pr", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--trabajo", required=True)
    ap.add_argument("--python", default=os.environ.get("PRDRIVE_PYTHON"))
    ap.add_argument("--rondas", type=int, default=7)
    ap.add_argument("--salida")
    ap.add_argument("--capturas", action="store_true")
    ap.add_argument("--plataforma", default=os.environ.get("RENDIMIENTO_PLATAFORMA", ""))
    a = ap.parse_args()
    if not a.python:
        print("falta --python (o PRDRIVE_PYTHON)", file=sys.stderr)
        return 2
    arboles = {"base": Path(a.base).resolve(), "pr": Path(a.pr).resolve()}
    salida = Path(a.salida) if a.salida else Path(a.trabajo) / "salida"
    salida.mkdir(parents=True, exist_ok=True)
    crudo = salida / "crudo.jsonl"
    crudo.write_text("", encoding="utf-8")
    plataforma = a.plataforma or plataforma_local()

    def anotar(lineas: list[dict], ronda: int) -> None:
        with crudo.open("a", encoding="utf-8") as f:
            for d in lineas:
                f.write(json.dumps(dict(d, ronda=ronda), ensure_ascii=False) + "\n")

    m = Medidor(a.python, arboles, Path(a.trabajo))
    m.preparar_driver()
    for arbol in ("base", "pr"):
        log(f"preparando {arbol} ({arboles[arbol]})")
        m.preparar_arbol(arbol)
    if len(m.malos) == 2:
        print("No se pudo montar el dispositivo de muestra de ningún árbol.", file=sys.stderr)
        return 2

    for arbol in ("base", "pr"):                          # calentamiento: se tira (ronda -1)
        if arbol not in m.malos:
            log(f"calentamiento {arbol}")
            anotar(m.pasada(arbol), -1)
    for i in range(a.rondas):
        orden = ("base", "pr") if i % 2 == 0 else ("pr", "base")
        for arbol in orden:
            if arbol not in m.malos:
                log(f"vuelta {i + 1}/{a.rondas}: {arbol}")
                anotar(m.pasada(arbol), i)
        anotar(m.suelo(), i)
    capturas = []
    if a.capturas and "pr" not in m.malos:
        log("capturas")
        carpeta = salida / "capturas"
        carpeta.mkdir(exist_ok=True)
        for flujo, pares, escala in PLAN_CAPTURAS:
            capturas += m.flujo("pr", flujo, pares, escala, carpeta,
                                f"pr-{flujo}-{'p' + str(pares) if pares else 'x'}-{'150' if escala == '2.0' else '100'}")
        anotar(capturas, 0)

    lineas = informe.leer(crudo.read_text(encoding="utf-8"))
    presupuesto = informe.cargar_presupuesto(AQUI / "presupuesto.toml")
    r = informe.comparar(lineas, presupuesto, plataforma)
    suelo = [float(d["ms"]) for d in lineas if d.get("arbol") == "suelo"]
    detalle = next((d["detail"] for d in lineas if d.get("scenario") == "start-bare"), {})
    texto = informe.markdown(r, {
        "plataforma": plataforma, "rondas": a.rondas,
        "pr": corto(os.environ.get("RENDIMIENTO_PR", "pr")),
        "base": corto(os.environ.get("RENDIMIENTO_BASE", "base")),
        "python": detalle.get("python", "?"), "tk": detalle.get("tk", "?"),
        "suelo": (f"{sorted(suelo)[len(suelo) // 2]:.0f} ms (de {min(suelo):.0f} a {max(suelo):.0f})"
                  if suelo else "sin medir")})
    if capturas:
        pintadas = sum(1 for c in capturas if c["info"].get("ok"))
        texto += (f"\nCapturas: {pintadas} de {len(capturas)} pintadas"
                  + ("" if pintadas == len(capturas) else
                     " (**la máquina no pinta alguna ventana: los tiempos no valen**)") + ".\n")
    (salida / "resumen.md").write_text(texto, encoding="utf-8")
    (salida / "resumen.json").write_text(json.dumps(r, indent=1, ensure_ascii=False, default=str),
                                         encoding="utf-8")
    print(texto)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(texto + "\n")
    log(f"terminado en {time.time() - T_INICIO:.0f} s")
    return 1 if r["fallos"] else 0


if __name__ == "__main__":
    sys.exit(main())
