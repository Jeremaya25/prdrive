"""Mide lo que GASTAN el agente residente y una pasada, sin Tk: los presupuestos de consumo.

Lo lanza `correr.py` a través de `entrada.py`, igual que `driver.py`, con el Python del
runtime fijado. Variables:

  BENCH_FLOW     consumo-reposo | consumo-servida | consumo-pasada
  BENCH_APP      árbol de código que se mide (con `tests/_agente_falso.py` y `tests/_harness.py`)
  BENCH_DEVICE   una copia nueva del dispositivo de muestra (solo `consumo-pasada`)
  BENCH_RCLONE   el rclone de verdad con el que corre la pasada (solo `consumo-pasada`)
  BENCH_OUT      fichero donde van los resultados (un JSON por línea)

Qué mide cada flujo (`docs/superpowers/pruebas/2026-10-11-watch-energia-windows-medidas.md`):

- `consumo-reposo`: el agente sin ninguna unidad, una hora de reloj de mentira. Cuenta las
  vueltas que da y las llamadas al sistema de ficheros que hace en su carpeta.
- `consumo-servida`: el agente con una unidad atendida (dos parejas cada 5 minutos) en la
  que nunca cambia nada, dos horas de reloj de mentira. Cuenta las vueltas, las llamadas al
  sistema de ficheros DENTRO de la unidad (lo que impide que un USB descanse) y los
  `sync.py` que lanza.
- `consumo-pasada`: una pasada bisync de verdad, sin cambios, de una pareja de 100 ficheros
  contra un remoto local. Cuenta las órdenes de rclone, y los ficheros y los KB que la
  pasada escribe en la unidad.

El agente es el de verdad (`Agente.vuelta()`) sobre el equipo de mentira de sus tests
(`tests/_agente_falso.py` DEL ÁRBOL que se mide): un reloj que avanza a mano y procesos que
no se lanzan. El bucle es el de `agente.cmd_run()`: una vuelta y una espera. La espera es
`agente.TICK`, o lo que diga `agente.cuanto_esperar(agente, decisión)` en el árbol que lo
tenga. Cada `sync.py` «lanzado» acaba en la vuelta siguiente, bien y sin haber movido nada.

Las cuentas van en `detail.cuentas` y no dependen de la máquina; el tiempo (`ms`) es lo que
tarda este proceso en dar esas vueltas, o lo que tarda la pasada.
"""
import builtins
import io
import json
import os
import shutil
import subprocess
import sys
import time

import utiles

APP = os.path.realpath(os.environ["BENCH_APP"])
FLOW = os.environ.get("BENCH_FLOW", "")
HORAS = {"consumo-reposo": 1.0, "consumo-servida": 2.0}
"""Horas de reloj de mentira que se simulan en cada flujo del agente."""
ASENTAR = 600.0
"""Segundos de mentira que se dejan pasar antes de contar: la conexión y las primeras pasadas."""
FICHEROS = 100
"""Ficheros de la pareja de `consumo-pasada`."""
PAREJA = "medida"
MARCA_PARTE = "@prdrive "
"""Cómo empieza la línea con la que `sync.py` cuenta al agente cómo fue cada pareja."""

ACTIVO = [False]
DENTRO = [0]
CUENTA: dict[str, int] = {}


# ----------------------------------------------------------------------------
# Las llamadas al sistema de ficheros, contadas por dónde caen.
# ----------------------------------------------------------------------------
def contar_en(raices: dict[str, str]) -> None:
    """Envuelve las funciones que tocan ficheros y cuenta las que caen bajo cada raíz.

    Solo cuenta mientras `ACTIVO[0]`, y solo la llamada de fuera: `os.path.exists()` que
    por dentro llama a `os.stat()` es un toque, no dos.

    Args:
        raices: `{nombre: carpeta}`; cada llamada suma en `CUENTA[nombre]`.
    """
    prefijos = [(nombre, os.path.normcase(os.path.realpath(ruta)))
                for nombre, ruta in raices.items()]

    def apuntar(p) -> None:
        if isinstance(p, int):
            return
        try:
            ruta = os.path.normcase(os.fsdecode(os.fspath(p)))
        except (TypeError, ValueError):
            return
        for nombre, prefijo in prefijos:
            if ruta.startswith(prefijo):
                CUENTA[nombre] = CUENTA.get(nombre, 0) + 1
                return

    def envolver(modulo, nombre: str) -> None:
        original = getattr(modulo, nombre, None)
        if original is None:
            return

        def envuelta(p=".", *a, **k):
            if ACTIVO[0] and DENTRO[0] == 0:
                apuntar(p)
            DENTRO[0] += 1
            try:
                return original(p, *a, **k)
            finally:
                DENTRO[0] -= 1
        setattr(modulo, nombre, envuelta)

    for nombre in ("stat", "lstat", "scandir", "listdir", "replace", "rename", "remove",
                   "unlink", "mkdir", "rmdir", "utime", "open"):
        envolver(os, nombre)
    for nombre in ("exists", "lexists", "isfile", "isdir", "getmtime", "getsize"):
        envolver(os.path, nombre)
    envolver(builtins, "open")
    envolver(io, "open")


# ----------------------------------------------------------------------------
# El agente, sobre el equipo de mentira de sus tests.
# ----------------------------------------------------------------------------
def salida_sin_cambios(proc) -> str:
    """Lo que escribe `sync.py` cuando sus parejas van bien y no mueven nada."""
    args = list(proc.args)
    parejas = args[args.index("--") + 1:] if "--" in args else []
    lineas = []
    for pareja in parejas:
        parte = {"pareja": pareja, "rc": 0, "movio": False, "ordenes": 1, "escrito": 0}
        lineas += [f"\n=== {pareja} (bisync) ===", f"[{pareja}] OK.",
                   MARCA_PARTE + json.dumps(parte, ensure_ascii=False)]
    return "\n".join(lineas) + f"\n\nHecho. {len(parejas)}/{len(parejas)} parejas OK.\n"


def simular(F, agente, ag, segundos: float) -> int:
    """Corre el bucle del agente durante `segundos` de reloj de mentira; devuelve las vueltas."""
    cuanto = getattr(agente, "cuanto_esperar", None)
    fin = F.reloj() + segundos
    vueltas = 0
    while F.reloj() < fin:
        decision = ag.vuelta(ag.toca_recorrer(F.reloj()))
        vueltas += 1
        pasada = ag.pasada
        if pasada is not None and pasada.proc.poll() is None:
            contando, ACTIVO[0] = ACTIVO[0], False      # esto lo escribe el arnés, no el agente
            F.acabar(pasada.proc, 0, salida_sin_cambios(pasada.proc))
            ACTIVO[0] = contando
        F.pasar(cuanto(ag, decision) if cuanto else agente.TICK)
    return vueltas


def agente_de_mentira():
    """Importa el agente del árbol que se mide y lo apunta a su equipo de mentira."""
    sys.path[:0] = [APP, os.path.join(APP, "tests")]
    import _agente_falso as F
    import agente
    from common import equipo
    F.preparar()
    return F, agente, equipo


def flujo_agente() -> None:
    F, agente, equipo = agente_de_mentira()
    raices = {"equipo": str(equipo.DIR)}
    if FLOW == "consumo-servida":
        raiz = F.unidad("bench0001", parejas=("docs", "fotos"),
                        daemon='[daemon]\npairs = ["docs", "fotos"]\ninterval_minutes = 5\n')
        equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(
            equipo.Unidad("bench0001", equipo.DAEMON, "U", codigo=agente.huella(raiz) or "")))
        F.RAICES[:] = [raiz]
        raices["unidad"] = str(raiz)
    ag = F.nuevo()
    simular(F, agente, ag, ASENTAR)
    contar_en(raices)
    lanzados = len(F.pasadas())
    ACTIVO[0] = True
    t0 = time.perf_counter()
    vueltas = simular(F, agente, ag, HORAS[FLOW] * 3600.0)
    ms = (time.perf_counter() - t0) * 1000
    ACTIVO[0] = False
    cuentas = {"vueltas": vueltas, "toques_equipo": CUENTA.get("equipo", 0)}
    if FLOW == "consumo-servida":
        if not any(c.lock for c in ag.conexiones.values()):
            raise RuntimeError("la unidad de muestra no llegó a estar atendida")
        cuentas["toques_unidad"] = CUENTA.get("unidad", 0)
        cuentas["pasadas"] = len(F.pasadas()) - lanzados
    utiles.escribir(FLOW, round(ms, 1), {"cuentas": cuentas, "horas": HORAS[FLOW]})


# ----------------------------------------------------------------------------
# Una pasada de verdad, sin cambios.
# ----------------------------------------------------------------------------
def foto(raiz: str) -> dict:
    """`{ruta relativa: (tamaño, mtime_ns)}` de todo lo que hay bajo `raiz`."""
    salida = {}
    for carpeta, _dirs, ficheros in os.walk(raiz):
        for f in ficheros:
            ruta = os.path.join(carpeta, f)
            try:
                st = os.stat(ruta)
            except OSError:
                continue
            salida[os.path.relpath(ruta, raiz).replace(os.sep, "/")] = (st.st_size, st.st_mtime_ns)
    return salida


def pasada(app: str, entorno: dict, *antes: str) -> tuple[int, str, float]:
    """Lanza `sync.py [antes] -- medida` como lo lanza el agente; devuelve `(rc, salida, ms)`."""
    t0 = time.perf_counter()
    r = subprocess.run([sys.executable, os.path.join(app, "sync.py"), *antes, "--", PAREJA],
                       env=entorno, cwd=app, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, timeout=45)
    return r.returncode, r.stdout.decode("utf-8", "replace"), (time.perf_counter() - t0) * 1000


def flujo_pasada() -> None:
    rclone = os.environ.get("BENCH_RCLONE") or ""
    if not os.path.isfile(rclone):
        raise RuntimeError("consumo-pasada necesita el rclone de verdad en BENCH_RCLONE")
    raiz = os.path.realpath(os.environ["BENCH_DEVICE"])
    app = os.path.join(raiz, ".prdrive")
    remoto = raiz + "-remoto"
    for d in (remoto, os.path.join(app, "state"), os.path.join(app, "logs"),
              os.path.join(raiz, "sync-data")):
        shutil.rmtree(d, ignore_errors=True)
    local = os.path.join(raiz, "sync-data", PAREJA)
    for i in range(FICHEROS):
        os.makedirs(os.path.join(local, f"{i // 25:02d}"), exist_ok=True)
        with open(os.path.join(local, f"{i // 25:02d}", f"fichero-{i:03d}.txt"), "w",
                  encoding="utf-8") as f:
            f.write(f"{i:06d}\n" + "x" * 300)
    os.makedirs(os.path.join(remoto, PAREJA), exist_ok=True)
    with open(os.path.join(app, "rclone.conf"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"[nas]\ntype = alias\nremote = {remoto}\n")
    with open(os.path.join(app, "sync_config.toml"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f'[defaults]\nremote = "nas"\n\n[[pair]]\nname = "{PAREJA}"\n'
                f'local = "sync-data/{PAREJA}"\nremote_path = "{PAREJA}"\nmode = "bisync"\n')
    entorno = dict(os.environ, PRDRIVE_RCLONE=rclone,
                   PYTHONPYCACHEPREFIX=os.path.join(os.environ.get("TEMP") or
                                                    os.environ.get("TMPDIR") or remoto, "pyc"))
    rc, texto, _ms = pasada(app, entorno, "--resync", "-y")
    if rc != 0:
        raise RuntimeError("la pasada de partida (--resync) falló:\n" + texto[-1500:])
    pasada(app, entorno)                                 # una de calentamiento, sin medir
    antes = foto(raiz)
    rc, texto, ms = pasada(app, entorno)
    despues = foto(raiz)
    if rc != 0 or "Saltada" in texto:
        raise RuntimeError("la pasada sin cambios no fue bien:\n" + texto[-1500:])
    escritos = {k: v for k, v in despues.items() if antes.get(k) != v}
    cuentas = {"ordenes": sum(1 for linea in texto.splitlines()
                              if linea.lstrip().startswith("ejecutando")),
               "ficheros": len(escritos),
               "kb": round(sum(tam for tam, _ in escritos.values()) / 1024)}
    utiles.escribir(FLOW, round(ms, 1), {"cuentas": cuentas, "escritos": sorted(escritos),
                                         "bytes": sum(tam for tam, _ in escritos.values())})


def main() -> None:
    notas: dict = {}
    try:
        if FLOW == "consumo-pasada":
            flujo_pasada()
        elif FLOW in HORAS:
            flujo_agente()
        else:
            raise RuntimeError(f"flujo desconocido: {FLOW!r}")
    except Exception:                                    # noqa: BLE001
        import traceback
        notas["error"] = traceback.format_exc()
    utiles.escribir("_notes", 0, notas)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)   # sin esperar a hilos del agente que quedaran vivos
