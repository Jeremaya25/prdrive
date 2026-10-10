#!/usr/bin/env python3
"""Los hijos de solo lectura de la ventana se pueden cortar al cerrarla.

Una lectura que la ventana lanza a un hilo (`rclone lsjson` del catálogo, un
`schtasks /Query`) no se corta con el hilo: sigue viva con la unidad abierta
(su cwd es el dispositivo) cuando el usuario cierra o expulsa. `store` apunta
esos subprocesos mientras corren y `store.matar_hijos()` los corta.

Solo se apuntan las LECTURAS (`catalog.es_lectura`): una subida, un
renombrado o un borrado que se cortara a medias dejaría el remoto peor que
dejarlo acabar. Y `catalog.run()` sigue creando su hijo exactamente como antes
(sin sesión ni grupo propios): si lo hace `sync.py`, `matar_arbol` tiene que
seguir llegando a él (`test_matar_arbol.py`).

Se prueba con procesos de verdad. La mitad que necesita un «rclone» de mentira
(`_rclone_falso`) corre solo en POSIX; la de `store.correr_apuntado()` y
`watch.consulta()`, con un Python que duerme, en los dos sistemas.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from _harness import Checks, tmpdir

import _rclone_falso
from common import catalog, model, store
from ui import watch

c = Checks("subprocesos de solo lectura que se pueden cortar")

ESPERA = 10.0             # segundos que se le dan a un proceso o a un hilo para ponerse en marcha o acabar

DORMILON = ("import os, pathlib, sys, time\n"
            "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))\n"
            "parar = pathlib.Path(sys.argv[2])\n"
            "limite = time.monotonic() + 60\n"
            "while not parar.exists() and time.monotonic() < limite:\n"
            "    time.sleep(0.05)\n")
"""Un Python que apunta su pid y espera a que exista un fichero (o se le acabe el minuto)."""


def esperar_a(condicion, espera: float = ESPERA) -> bool:
    """Sondea `condicion()` hasta que se cumple o se acaba `espera`.

    Returns:
        Si se cumplió.
    """
    limite = time.monotonic() + espera
    while not condicion():
        if time.monotonic() >= limite:
            return False
        time.sleep(0.02)
    return True


def leer_pid(fichero: Path) -> int | None:
    """Devuelve el pid que apunta el proceso, o `None` si aún no lo ha escrito."""
    try:
        return int(fichero.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def liberar(pid: int | None) -> None:
    """Mata un proceso a las malas, para que una prueba que falla no lo deje dormido."""
    if pid is None or not store.pid_alive(pid):
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    else:
        os.kill(pid, 9)


class Dormilon:
    """Un proceso que duerme hasta que se le suelta, con sus dos ficheros.

    Attributes:
        pid: Dónde apunta su pid el proceso.
        parar: El fichero cuya existencia lo suelta.
    """

    def __init__(self) -> None:
        """Prepara los ficheros, aún sin proceso."""
        carpeta = tmpdir()
        self.pid = carpeta / "dormilon.pid"
        self.parar = carpeta / "dormilon.parar"

    def orden(self) -> list[str]:
        """Devuelve la orden que lanza el Python dormilón."""
        return [sys.executable, "-c", DORMILON, str(self.pid), str(self.parar)]

    def en_marcha(self) -> int | None:
        """Espera a que el proceso apunte su pid y lo devuelve (`None` si no llegó)."""
        esperar_a(lambda: leer_pid(self.pid) is not None)
        return leer_pid(self.pid)

    def soltar(self) -> None:
        """Deja que el proceso salga por sí mismo."""
        self.parar.write_text("ya", encoding="ascii")


def en_hilo(funcion, *args, **kwargs):
    """Lanza `funcion` en un hilo y devuelve `(hilo, resultado)`.

    `resultado` es una lista que recibe `("ok", valor)` o `("error", excepción)`.
    """
    resultado: list = []

    def correr() -> None:
        """Hace la llamada y apunta cómo salió."""
        try:
            resultado.append(("ok", funcion(*args, **kwargs)))
        except BaseException as e:                           # noqa: BLE001
            resultado.append(("error", e))

    hilo = threading.Thread(target=correr, daemon=True)
    hilo.start()
    return hilo, resultado


def apuntados(esperado: int | None = None) -> int:
    """Cuántos subprocesos tiene apuntados `store` ahora.

    Args:
        esperado: Si se da, espera un momento a que sean esos: el hijo ya está
            en marcha, pero el hilo que lo lanzó puede no haberlo apuntado aún.
    """
    if esperado is not None:
        esperar_a(lambda: len(store._HIJOS) == esperado, 3.0)
    return len(store._HIJOS)


# lo apuntado: apuntar, soltar y cortar, sin procesos
class Falso:
    """Un `Popen` de mentira: dice si está vivo y apunta si lo han matado."""

    def __init__(self, vivo: bool = True, falla: bool = False) -> None:
        """Prepara el proceso, vivo o ya salido; `falla` hace que matarlo lance."""
        self.vivo, self.falla, self.matado = vivo, falla, False

    def poll(self):
        """Devuelve `None` si sigue vivo, y un código si ya salió."""
        return None if self.vivo else 0

    def kill(self) -> None:
        """Lo mata, o lanza si el sistema se lo niega."""
        if self.falla:
            raise PermissionError(1, "Operation not permitted")
        self.vivo, self.matado = False, True


store._HIJOS.clear()
c("sin nada apuntado, matar_hijos() corta 0", store.matar_hijos(), 0)

vivo_a, vivo_b, salido = Falso(), Falso(), Falso(vivo=False)
for hijo in (vivo_a, vivo_b, salido, vivo_a):
    store.apuntar_hijo(hijo)
c("apuntar dos veces el mismo no lo duplica", apuntados(), 3)
c("matar_hijos() devuelve cuántos ha cortado de verdad (los vivos)", store.matar_hijos(), 2)
c("  los vivos mueren y el que ya había salido no se toca",
  (vivo_a.matado, vivo_b.matado, salido.matado), (True, True, False))
c("  y se olvida de todos", apuntados(), 0)
c("una segunda llamada no corta nada", store.matar_hijos(), 0)

suelto = Falso()
store.apuntar_hijo(suelto)
store.soltar_hijo(suelto)
store.soltar_hijo(suelto)                        # soltar uno que ya no está no es un error
c("un hijo soltado ya no se corta", (store.matar_hijos(), suelto.matado), (0, False))

negado, despues = Falso(falla=True), Falso()
store.apuntar_hijo(negado)
store.apuntar_hijo(despues)
try:
    cortados, lanzo = store.matar_hijos(), None
except Exception as e:                                       # noqa: BLE001
    cortados, lanzo = None, e
c("matar_hijos() no lanza nunca, aunque un proceso se niegue", lanzo, None)
c("  y sigue con los demás: cuenta solo los cortados", (cortados, despues.matado), (1, True))
store._HIJOS.clear()


# correr_apuntado: lo que hacía subprocess.run
hola = [sys.executable, "-c", "print('hola')"]
res = store.correr_apuntado(hola, timeout=ESPERA, text=True)
c("un hijo normal: salida, código y orden tal cual",
  (res.stdout, res.stderr, res.returncode, res.args), ("hola\n", "", 0, hola))
c("  y no queda apuntado", apuntados(), 0)

res = store.correr_apuntado(
    [sys.executable, "-c", "import sys; print('mal', file=sys.stderr); sys.exit(3)"],
    timeout=ESPERA, text=True)
c("un hijo que falla: su código y su error", (res.returncode, res.stderr.strip()), (3, "mal"))

res = store.correr_apuntado(hola, timeout=ESPERA)
c("sin text, la salida son bytes", res.stdout.strip(), b"hola")

res = store.correr_apuntado(
    [sys.executable, "-c", "import os; print(os.getcwd())"], timeout=ESPERA,
    text=True, cwd=str(tmpdir()))
c("los argumentos de Popen pasan (cwd)", os.path.isdir(res.stdout.strip()), True)

try:
    store.correr_apuntado(["/no/existe/de/ninguna/manera"], timeout=ESPERA)
    lanzo = None
except OSError as e:
    lanzo = isinstance(e, FileNotFoundError)
c("lo que no se puede lanzar lanza FileNotFoundError, como subprocess.run", lanzo, True)
c("  y no queda apuntado", apuntados(), 0)

# se pasa de tiempo: se corta y lanza TimeoutExpired, sin dejar nada apuntado
dormilon = Dormilon()
t0 = time.monotonic()
try:
    store.correr_apuntado(dormilon.orden(), timeout=0.4)
    lanzo = None
except subprocess.TimeoutExpired as e:
    lanzo = e
pid = leer_pid(dormilon.pid)
try:
    c("pasarse del tope lanza TimeoutExpired", type(lanzo).__name__, "TimeoutExpired")
    c("  sin esperar a que el hijo acabe por su cuenta", time.monotonic() - t0 < ESPERA, True)
    c("  el hijo estaba en marcha", pid is not None, True)
    if pid is not None:
        esperar_a(lambda: not store.pid_alive(pid))
        c("  y está muerto", store.pid_alive(pid), False)
    c("  y no queda apuntado", apuntados(), 0)
finally:
    liberar(pid)

# apuntado mientras corre y suelto al acabar
dormilon = Dormilon()
hilo, resultado = en_hilo(store.correr_apuntado, dormilon.orden(), timeout=60)
pid = dormilon.en_marcha()
try:
    c("corriendo, el hijo está apuntado", apuntados(1), 1)
    dormilon.soltar()
    hilo.join(ESPERA)
    c("  al acabar se suelta", (apuntados(), resultado[0][0], resultado[0][1].returncode),
      (0, "ok", 0))
finally:
    dormilon.soltar()
    liberar(pid)

# apuntar=False: corre, pero matar_hijos() no lo toca
dormilon = Dormilon()
hilo, resultado = en_hilo(store.correr_apuntado, dormilon.orden(), timeout=60, apuntar=False)
pid = dormilon.en_marcha()
try:
    c("con apuntar=False no se apunta", apuntados(), 0)
    c("  y matar_hijos() no lo corta", (store.matar_hijos(), store.pid_alive(pid)), (0, True))
    dormilon.soltar()
    hilo.join(ESPERA)
    c("  acaba por su cuenta", resultado[0][1].returncode, 0)
finally:
    dormilon.soltar()
    liberar(pid)

# matar_hijos() desde otro hilo
dormilon = Dormilon()
hilo, resultado = en_hilo(store.correr_apuntado, dormilon.orden(), timeout=60)
pid = dormilon.en_marcha()
try:
    c("antes de cortar está apuntado y vivo", (apuntados(1), store.pid_alive(pid)), (1, True))
    t0 = time.monotonic()
    c("matar_hijos() desde otro hilo corta uno", store.matar_hijos(), 1)
    hilo.join(ESPERA)
    c("  quien esperaba al hijo vuelve enseguida, con un código de fallo",
      (not hilo.is_alive(), time.monotonic() - t0 < ESPERA,
       resultado[0][0] == "ok" and resultado[0][1].returncode != 0), (True, True, True))
    esperar_a(lambda: not store.pid_alive(pid))
    c("  y el hijo ha muerto", store.pid_alive(pid), False)
    c("  y no queda apuntado", apuntados(), 0)
finally:
    dormilon.soltar()
    liberar(pid)


# watch.consulta: la pregunta al sistema también se apunta
dormilon = Dormilon()
hilo, resultado = en_hilo(watch.consulta, dormilon.orden(), timeout=60)
pid = dormilon.en_marcha()
try:
    c("consulta(): corriendo, está apuntada", apuntados(1), 1)
    c("  matar_hijos() la corta", store.matar_hijos(), 1)
    hilo.join(ESPERA)
    c("  y devuelve su resultado, sin lanzar y con código de fallo",
      (not hilo.is_alive(), resultado[0][0] == "ok" and resultado[0][1].returncode != 0),
      (True, True))
finally:
    dormilon.soltar()
    liberar(pid)

dormilon = Dormilon()
res = watch.consulta(dormilon.orden(), timeout=0.4)
pid = leer_pid(dormilon.pid)
try:
    c("consulta() que se pasa de tiempo: el código es el de siempre",
      res.returncode, watch.CODIGO_TIEMPO)
    c("  y no queda apuntada", apuntados(), 0)
finally:
    liberar(pid)
c("consulta() de lo que no existe: 127 y nada apuntado",
  (watch.consulta(["/no/existe/de/ninguna/manera"]).returncode, apuntados()), (127, 0))


# catalog.es_lectura: qué se apunta
temporal = Path(tempfile.gettempdir())
destino_temporal = str(temporal / "prdrive-flota-x1")
c("lecturas: cat, lsjson, lsf y lsd",
  [catalog.es_lectura(a) for a in (["cat", "nas:/c/remote.toml"],
                                   ["lsjson", "--stat", "nas:/c"],
                                   ["lsf", "-R", "--files-only", "nas:/v"],
                                   ["lsd", "nas:/"])], [True] * 4)
c("copy y copyto a un temporal local son lecturas",
  [catalog.es_lectura(a) for a in (["copy", "nas:/c/devices/", destino_temporal,
                                    "--include", "*.toml"],
                                   ["copyto", "nas:/c/x.toml", destino_temporal + "/x.toml"])],
  [True, True])
c("escrituras en el remoto: ninguna se apunta",
  [catalog.es_lectura(a) for a in (
      ["copyto", destino_temporal + "/nota.toml", "nas:/c/devices/x.toml"],
      ["copyto", "nas:/c/remote.toml", "nas:/c/remote.toml.bak"],
      ["copy", "nas:/a", "nas:/b"],
      ["moveto", "nas:/c/pairs.toml", "nas:/c/remote.toml"],
      ["delete", "nas:/v", "--files-from", "lista.txt"],
      ["deletefile", "nas:/c/devices/x.toml"],
      ["mkdir", "nas:/nueva"],
      ["purge", "nas:/v"],
      ["sync", "nas:/a", destino_temporal])], [False] * 9)
c("una copia a un sitio local que no es temporal no se apunta",
  [catalog.es_lectura(a) for a in (
      ["copy", "nas:/c", str(temporal.parent / "documentos")],
      ["copy", "nas:/c", "sync-data/docs"],                  # relativo: el dispositivo
      ["copy", "nas:/c", str(temporal / ".." / "documentos")],
      ["copy", "nas:/c", str(temporal)])], [False] * 4)
c("lo que no se sabe leer no se apunta (sin destino, flags delante, vacío)",
  [catalog.es_lectura(a) for a in (["copy", "nas:/c"], [],
                                   ["copy", "--include", "*.toml", "nas:/c", destino_temporal],
                                   ["--version"])], [False] * 4)


# catalog.run: crea su hijo como siempre
class Visto(Exception):
    """Para que el espía de `Popen` pare la llamada después de mirarla."""


def lanzado_por(args, so="posix", **kwargs):
    """Devuelve `(orden, kwargs)` con que `catalog.run(args)` llama a `Popen`.

    El `Popen` se sustituye por un espía que lo apunta y para; con `so="nt"`
    `catalog` cree estar en Windows.
    """
    vistos: list = []

    def espia(orden, **kw):
        """Apunta cómo se llamó a `Popen` y no lanza nada."""
        vistos.append((list(orden), kw))
        raise Visto()

    real_popen, real_os, real_binary = subprocess.Popen, catalog.os, catalog._binary
    subprocess.Popen = espia
    catalog._binary = lambda: "/rclone"
    if so == "nt":
        catalog.os = SimpleNamespace(name="nt", path=os.path)
    try:
        try:
            catalog.run(args, **kwargs)
        except Visto:
            pass
    finally:
        subprocess.Popen, catalog.os, catalog._binary = real_popen, real_os, real_binary
    return vistos[0]


orden, kw = lanzado_por(["lsjson", "nas:/c"], so="nt" if os.name == "nt" else "posix")
base = {"cwd": str(model.APP_DIR), "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
        "text": True, "encoding": "utf-8", "errors": "replace"}
c("catalog.run: la orden es binario, --config, NET_FLAGS y los args",
  orden, ["/rclone", "--config", str(model.RCLONE_CONF), *catalog.NET_FLAGS, "lsjson", "nas:/c"])
if os.name != "nt":
    c("catalog.run: el hijo se crea como siempre (misma sesión y grupo, stdin heredado)",
      kw, base)
orden, kw = lanzado_por(["lsjson", "nas:/c"], so="nt")
c("catalog.run en Windows: solo se añade CREATE_NO_WINDOW",
  kw, {**base, "creationflags": model.CREATE_NO_WINDOW})
orden, kw = lanzado_por(["moveto", "nas:/a", "nas:/b"], so="nt")
c("  también con una escritura", kw, {**base, "creationflags": model.CREATE_NO_WINDOW})


# catalog.run con un «rclone» de mentira (POSIX)
if not _rclone_falso.DISPONIBLE:
    print("  (saltado) el rclone de mentira es un script de sh: solo en POSIX")
    sys.exit(c.report())

carpeta = tmpdir()
falso = _rclone_falso.crear(carpeta)
pid_falso, parar_falso = carpeta / "falso.pid", carpeta / "falso.parar"
real_binary, real_timeout = catalog._binary, catalog.TIMEOUT
catalog._binary = lambda: falso
os.environ["PRDRIVE_FALSO_PID"] = str(pid_falso)
os.environ["PRDRIVE_FALSO_PARAR"] = str(parar_falso)


def preparar(modo: str) -> None:
    """Deja limpio el terreno del rclone de mentira y le dice qué hacer."""
    for fichero in (pid_falso, parar_falso):
        fichero.unlink(missing_ok=True)
    os.environ["PRDRIVE_FALSO_MODO"] = modo


try:
    # un rclone que contesta y sale
    preparar("eco")
    args = ["lsjson", "--stat", "nas:/prdrive-catalog"]
    res = catalog.run(args)
    eco = json.loads(res.stdout)
    c("run(): el resultado es el del hijo (código, salida y error)",
      (type(res).__name__, res.returncode, res.stderr.strip()),
      ("CompletedProcess", 3, "fallo de mentira"))
    c("  con la orden de siempre",
      eco["orden"][1:], ["--config", str(model.RCLONE_CONF), *catalog.NET_FLAGS, *args])
    c("  y en la carpeta del programa (model.APP_DIR)",
      os.path.realpath(eco["cwd"]), os.path.realpath(model.APP_DIR))
    c("  nada queda apuntado", apuntados(), 0)

    # qué se apunta mientras corre
    temp_x = str(temporal / "prdrive-flota-prueba")
    LECTURAS = [["cat", "nas:/c/remote.toml"], ["lsjson", "--files-only", "nas:/c"],
                ["lsf", "-R", "--csv", "nas:/v"], ["lsd", "nas:/"],
                ["copy", "nas:/c/devices/", temp_x, "--include", "*.toml"],
                ["copyto", "nas:/c/x.toml", temp_x + "/x.toml"]]
    ESCRITURAS = [["copyto", temp_x + "/nota.toml", "nas:/c/devices/x.toml"],
                  ["moveto", "nas:/c/pairs.toml", "nas:/c/remote.toml"],
                  ["delete", "nas:/v", "--files-from", "lista.txt"],
                  ["deletefile", "nas:/c/devices/x.toml"], ["mkdir", "nas:/nueva"],
                  ["purge", "nas:/v"]]

    def apunta_mientras_corre(args, esperado: int, **kwargs):
        """Lanza `catalog.run(args)` con un hijo que duerme y mira si está apuntado.

        Args:
            args: La orden de rclone.
            esperado: Cuántos hijos debería haber apuntados mientras corre.

        Returns:
            `(apuntados con el hijo en marcha, código al soltarlo)`.
        """
        preparar("dormir")
        hilo, resultado = en_hilo(catalog.run, args, **kwargs)
        pid = None
        try:
            esperar_a(lambda: leer_pid(pid_falso) is not None)
            pid = leer_pid(pid_falso)
            cuantos = apuntados(esperado)
            parar_falso.write_text("ya", encoding="ascii")
            hilo.join(ESPERA)
            return cuantos, getattr(resultado[0][1], "returncode", None)
        finally:
            parar_falso.write_text("ya", encoding="ascii")
            liberar(pid)

    c("run(): las lecturas se apuntan mientras corren (y salen con 0)",
      [apunta_mientras_corre(a, 1) for a in LECTURAS], [(1, 0)] * len(LECTURAS))
    c("run(): las escrituras no se apuntan nunca",
      [apunta_mientras_corre(a, 0) for a in ESCRITURAS], [(0, 0)] * len(ESCRITURAS))
    c("run(apuntar=True) apunta una escritura, y apuntar=False una lectura",
      (apunta_mientras_corre(ESCRITURAS[1], 1, apuntar=True),
       apunta_mientras_corre(LECTURAS[0], 0, apuntar=False)), ((1, 0), (0, 0)))
    c("  y al acabar no queda nada apuntado", apuntados(), 0)

    # matar_hijos() corta la lectura, y no toca la escritura
    preparar("dormir")
    hilo, resultado = en_hilo(catalog.run, ["lsjson", "nas:/c"])
    pid = None
    try:
        esperar_a(lambda: leer_pid(pid_falso) is not None)
        pid = leer_pid(pid_falso)
        apuntados(1)
        t0 = time.monotonic()
        c("matar_hijos() corta el rclone de una lectura", store.matar_hijos(), 1)
        hilo.join(ESPERA)
        c("  quien esperaba vuelve enseguida con un fallo",
          (not hilo.is_alive(), time.monotonic() - t0 < ESPERA,
           resultado[0][0] == "ok" and resultado[0][1].returncode != 0), (True, True, True))
        esperar_a(lambda: not store.pid_alive(pid))
        c("  y el rclone ha muerto", store.pid_alive(pid), False)
    finally:
        parar_falso.write_text("ya", encoding="ascii")
        liberar(pid)

    preparar("dormir")
    hilo, resultado = en_hilo(catalog.run, ["copyto", temp_x + "/n.toml", "nas:/c/devices/x.toml"])
    pid = None
    try:
        esperar_a(lambda: leer_pid(pid_falso) is not None)
        pid = leer_pid(pid_falso)
        c("matar_hijos() no toca la subida de una escritura",
          (store.matar_hijos(), store.pid_alive(pid)), (0, True))
        parar_falso.write_text("ya", encoding="ascii")
        hilo.join(ESPERA)
        c("  que acaba bien", resultado[0][1].returncode, 0)
    finally:
        parar_falso.write_text("ya", encoding="ascii")
        liberar(pid)

    # pasarse de TIMEOUT: se corta, lanza TimeoutExpired y no deja nada apuntado
    catalog.TIMEOUT = 0.4
    for args in (["lsjson", "nas:/c"], ["copyto", "a.toml", "nas:/c/a.toml"]):
        preparar("dormir")
        t0 = time.monotonic()
        try:
            catalog.run(args)
            lanzo = None
        except subprocess.TimeoutExpired as e:
            lanzo = e
        pid = leer_pid(pid_falso)
        try:
            c(f"run({args[0]}) que se pasa de TIMEOUT lanza TimeoutExpired, sin esperar",
              (type(lanzo).__name__, time.monotonic() - t0 < ESPERA),
              ("TimeoutExpired", True))
            if pid is not None:
                esperar_a(lambda: not store.pid_alive(pid))
            c("  mata al hijo y no deja nada apuntado",
              (pid is not None and store.pid_alive(pid), apuntados()), (False, 0))
        finally:
            liberar(pid)
    catalog.TIMEOUT = real_timeout

    # sin rclone, el mismo error de siempre y nada apuntado
    def sin_rclone() -> str:
        """Hace como si el dispositivo no tuviera rclone."""
        raise model.ConfigError("No encuentro el binario de rclone")

    catalog._binary = sin_rclone
    try:
        catalog.run(["lsjson", "nas:/c"])
        lanzo = None
    except model.ConfigError as e:
        lanzo = e
    c("sin rclone, run() lanza ConfigError y no apunta nada",
      (type(lanzo).__name__, apuntados()), ("ConfigError", 0))
finally:
    catalog._binary, catalog.TIMEOUT = real_binary, real_timeout
    for clave in ("PRDRIVE_FALSO_PID", "PRDRIVE_FALSO_PARAR", "PRDRIVE_FALSO_MODO"):
        os.environ.pop(clave, None)

sys.exit(c.report())
