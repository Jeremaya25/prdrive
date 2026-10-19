#!/usr/bin/env python3
"""Lo que el agente deja fuera de su carpeta, y desinstalarlo sin dejar rastro (`common/presencia.py`).

Sin tocar el equipo: el registro es el de mentira de `_harness` (`REGISTRO`),
y `schtasks`, el arranque del agente y el `cmd` que borra la carpeta se
sustituyen por lo que apuntan. Se comprueba:

- En Windows, el arranque es el valor `prdrive` de `Run` (no una tarea: la
  vieja se borra), lo apagado por la persona se respeta, y la ficha de
  «Aplicaciones instaladas» lleva su «Desinstalar» y conserva su fecha.
- El agente arranca con su orden, fuera de toda unidad y sin heredar lo del
  instalador compilado ni lo que el agente viejo pone a sus hijos.
- Desinstalar enseña antes qué hará, y después no deja nada: ni registro, ni
  autostart, ni menú, ni caché, ni carpeta. Nunca toca la raíz del equipo.
- Con algo de prdrive abierto desde su carpeta, se para sin quitar nada.
- Corriendo desde su propia carpeta (el «Desinstalar» de Windows), la carpeta
  se borra al salir, con `RunOnce` por si algo sigue en uso.
- `agente.py desinstalar`: `--si` no pregunta; sin ventana ni consola, no toca
  nada.
"""

import io
import os
import sys
from pathlib import Path

from _harness import REGISTRO, Checks, tmpdir

from common import components, equipo, presencia, store

c = Checks("el agente en el equipo: arranque, ficha y desinstalar")

AUTOSTART = tmpdir("prdrive-autostart-") / "autostart" / "prdrive.desktop"
MENU = tmpdir("prdrive-menu-") / "prdrive.desktop"
presencia.autostart_file = lambda: AUTOSTART
presencia.acceso_menu = lambda: MENU
presencia.PARAR_ESPERA = 0.5
presencia.ESPERA_AJENOS = 0.0
ORDENES: list = []
presencia.ejecutar = lambda orden: ORDENES.append(orden) or \
    __import__("subprocess").CompletedProcess(orden, 0, "", "")
SUELTOS: list = []
presencia.lanzar_suelto = lambda linea: SUELTOS.append(linea)
LETRAS: list = []
presencia.limpiar_letras = lambda: LETRAS.append("limpiar") or ["H"]
NAVEGADOR: list = []
presencia.limpiar_navegador = lambda: NAVEGADOR.append("limpiar") or (0, [])
AJENOS: dict = {}
store_procesos_desde = store.procesos_desde
store.procesos_desde = lambda carpeta: dict(AJENOS) if Path(carpeta) == equipo.DIR else {}
CORRE_DESDE = {"si": False}
components.corre_desde = lambda carpeta: CORRE_DESDE["si"]


def con_windows(funcion):
    """Ejecuta `funcion()` por la rama de Windows de `presencia` y devuelve lo que dé."""
    antes = presencia.IS_WIN
    presencia.IS_WIN = True
    try:
        return funcion()
    finally:
        presencia.IS_WIN = antes


def instalado() -> tuple[Path, Path]:
    """Deja una carpeta del agente de mentira y devuelve `(python, código)`."""
    codigo = equipo.dir_codigo() / "0.9.0"
    codigo.mkdir(parents=True, exist_ok=True)
    (codigo / "agente.py").write_text("# agente\n", encoding="utf-8")
    (codigo / "runsync.ico").write_bytes(b"ico")
    python = equipo.dir_runtimes() / "x" / "pythonw.exe"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_bytes(b"x" * 4096)
    return python, codigo


# --- las órdenes, citadas como las guarda Windows
c("linea: cita lo que lleva espacios, y nada más",
  presencia.linea([r"C:\Users\Ana María\py.exe", "agente.py", "run"]),
  r'"C:\Users\Ana María\py.exe" agente.py run')
c("la orden de desinstalar es agente.py desinstalar; la silenciosa, con --si",
  (presencia.orden_desinstalar("py", Path("c"))[1:],
   presencia.orden_desinstalar("py", Path("c"), sin_preguntar=True)[-1]),
  ([str(Path("c") / "agente.py"), "desinstalar"], "--si"))

# --- Windows: el arranque es el valor de Run, no una tarea
equipo.DIR = tmpdir("prdrive-equipo-pres-")
PY, COD = instalado()
dicho = con_windows(lambda: presencia.registrar_arranque(PY, COD))
c("Windows: el arranque es el valor «prdrive» de Run, con su Python y agente.py run",
  REGISTRO.leer(presencia.CLAVE_RUN, "prdrive"),
  presencia.linea([str(PY), str(COD / "agente.py"), "run"]))
c("  la tarea programada de antes se borra", ORDENES[-1],
  ["schtasks", "/Delete", "/TN", "prdrive", "/F"])
c("  y se dice las dos cosas", (any("Aplicaciones de arranque" in m for m in dicho),
                                any("tarea programada" in m for m in dicho)), (True, True))
ORDENES.clear()
presencia.ejecutar = lambda orden: ORDENES.append(orden) or \
    __import__("subprocess").CompletedProcess(orden, 1, "", "no existe")
dicho = con_windows(lambda: presencia.registrar_arranque(PY, COD))
c("  sin tarea vieja no se dice nada de ella", any("tarea" in m for m in dicho), False)
REGISTRO.escribir_numero(presencia.CLAVE_APAGADO, 3, "prdrive")
con_windows(lambda: presencia.registrar_arranque(PY, COD))
c("  lo que la persona apagó en «Aplicaciones de arranque» sigue apagado",
  REGISTRO.dato(presencia.CLAVE_APAGADO, "prdrive"), 3)
c("  y cuenta como registrado", con_windows(presencia.arranque_registrado), True)

# --- Windows: la ficha de «Aplicaciones instaladas»
con_windows(lambda: presencia.registrar_ficha(PY, COD, "0.9.0"))
ficha = presencia.CLAVE_FICHA
c("la ficha: nombre, versión, dónde está y su icono",
  [REGISTRO.leer(ficha, n) for n in ("DisplayName", "DisplayVersion", "InstallLocation",
                                     "DisplayIcon")],
  ["prdrive", "0.9.0", str(equipo.DIR), str(COD / "runsync.ico")])
c("  su «Desinstalar» es agente.py desinstalar con el Python sin consola del agente",
  REGISTRO.leer(ficha, "UninstallString"),
  presencia.linea([str(PY), str(COD / "agente.py"), "desinstalar"]))
c("  y el silencioso, con --si", REGISTRO.leer(ficha, "QuietUninstallString").endswith(" --si"),
  True)
c("  sin «Modificar» ni «Reparar», y lo que ocupa en KiB",
  (REGISTRO.dato(ficha, "NoModify"), REGISTRO.dato(ficha, "NoRepair"),
   REGISTRO.dato(ficha, "EstimatedSize") >= 4), (1, 1, True))
REGISTRO.escribir(ficha, "20250101", "InstallDate")
con_windows(lambda: presencia.registrar_ficha(PY, COD, "0.9.1"))
c("  al actualizar cambia la versión y se queda la fecha de instalación",
  (REGISTRO.leer(ficha, "DisplayVersion"), REGISTRO.leer(ficha, "InstallDate")),
  ("0.9.1", "20250101"))
c("  y cuenta como registrada", presencia.ficha_registrada(), True)
c("fuera de Windows no hay ficha", presencia.registrar_ficha(PY, COD, "0.9.0"), None)

# --- arrancar: su orden, fuera de toda unidad, con el entorno de un inicio de sesión
LANZADOS: list = []
presencia.lanzar = lambda args, **kw: LANZADOS.append((args, kw))
os.environ["PRDRIVE_RCLONE"] = "/viejo/rclone"
os.environ["PYTHONPYCACHEPREFIX"] = "/viejo/pycache"
os.environ["TCL_LIBRARY"] = "/tmp/_MEI123/tcl"
os.environ["_PYI_ARCHIVE_FILE"] = "/tmp/x.exe"
c("arrancar: lo dice", presencia.arrancar(PY, COD), "Agente arrancado.")
args, kw = LANZADOS[-1]
c("  con su orden y en su carpeta", (args, kw["cwd"]),
  (presencia.orden(PY, COD), str(equipo.DIR)))
c("  sin el rclone ni la caché de .pyc que el agente viejo pone a sus hijos",
  ("PRDRIVE_RCLONE" in kw["env"], "PYTHONPYCACHEPREFIX" in kw["env"]), (False, False))
c("  desde un .py, lo del entorno de Tcl se hereda",
  kw["env"].get("TCL_LIBRARY"), "/tmp/_MEI123/tcl")
sys.frozen = True
try:
    limpio = presencia.entorno_limpio()
finally:
    del sys.frozen
c("  desde el instalador compilado, nada de la carpeta temporal de PyInstaller",
  ("TCL_LIBRARY" in limpio, "_PYI_ARCHIVE_FILE" in limpio, "PATH" in limpio),
  (False, False, "PATH" in os.environ))
for v in ("PRDRIVE_RCLONE", "PYTHONPYCACHEPREFIX", "TCL_LIBRARY", "_PYI_ARCHIVE_FILE"):
    os.environ.pop(v)
presencia.lanzar = lambda args, **kw: (_ for _ in ()).throw(OSError("sin permiso"))
c("  si no se puede, arrancará al iniciar sesión", "al iniciar sesión" in
  presencia.arrancar(PY, COD), True)

# --- el plan de desinstalar: qué se quita y qué se queda
RAIZ = tmpdir("prdrive-raiz-pres-")
(RAIZ / ".prdrive").mkdir()
(RAIZ / ".prdrive" / "PRDRIVE").write_text("id=" + "r" * 32 + "\n", encoding="utf-8")
equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(
    equipo.Unidad("r" * 32, equipo.DAEMON, "Casa", str(RAIZ))))
MENU.write_text("[Desktop Entry]\n", encoding="utf-8")
plan = con_windows(presencia.plan_desinstalar)
c("el plan: deja de arrancar y sale de «Aplicaciones instaladas»",
  any("Aplicaciones instaladas" in m for m in plan.consequences), True)
c("  se quita el acceso del menú y se borra su carpeta",
  (any("menú" in m for m in plan.consequences),
   any(str(equipo.DIR) in m for m in plan.consequences)), (True, True))
c("  las unidades no se tocan", any("unidades no se tocan" in m for m in plan.consequences),
  True)
c("  y la raíz se queda, y lo dice", [str(RAIZ) in m and "se queda" in m
                                     for m in plan.warnings], [True])
c("  pensarlo no ha tocado nada", (equipo.DIR.exists(), MENU.exists(),
                                   REGISTRO.leer(presencia.CLAVE_RUN, "prdrive") is not None),
  (True, True, True))

# --- con algo de prdrive abierto desde su carpeta, se para sin quitar nada
AJENOS[4321] = str(PY)
try:
    con_windows(presencia.desinstalar)
    c("con la ventana de la raíz abierta, no desinstala", "desinstalado", "error")
except presencia.DesinstalacionError as e:
    c("con la ventana de la raíz abierta, no desinstala, y dice quién la tiene",
      ("pythonw.exe (pid 4321)" in str(e), "no se ha quitado nada" in str(e)), (True, True))
c("  y no ha quitado nada", (equipo.DIR.exists(), MENU.exists(),
                             REGISTRO.leer(presencia.CLAVE_RUN, "prdrive") is not None,
                             presencia.ficha_registrada()), (True, True, True, True))
AJENOS.clear()

# --- Windows, desde el instalador: todo fuera, la carpeta ya
REGISTRO.escribir(presencia.CLAVE_RUNONCE, "otra cosa", "otro")
ORDENES.clear()
msgs = con_windows(presencia.desinstalar)
c("desinstalar en Windows: fuera el arranque, lo apagado y la ficha",
  (REGISTRO.leer(presencia.CLAVE_RUN, "prdrive"),
   REGISTRO.dato(presencia.CLAVE_APAGADO, "prdrive"), REGISTRO.vacia(ficha)),
  (None, None, None))
c("  la tarea vieja, por si quedaba", ORDENES, [["schtasks", "/Delete", "/TN", "prdrive", "/F"]])
c("  el nombre y el icono de las letras, también de un volumen abierto, y el navegador",
  (LETRAS, NAVEGADOR), (["limpiar"], ["limpiar"]))
c("  el acceso del menú y la carpeta entera", (MENU.exists(), equipo.DIR.exists()),
  (False, False))
c("  lo de otros programas no se toca", REGISTRO.leer(presencia.CLAVE_RUNONCE, "otro"),
  "otra cosa")
c("  ni hace falta RunOnce", REGISTRO.leer(presencia.CLAVE_RUNONCE, "prdrive"), None)
c("  dice que las unidades no se han tocado, y dónde se queda la raíz",
  ("Las unidades no se han tocado." in msgs, any(str(RAIZ) in m for m in msgs)), (True, True))
c("  la raíz, intacta", (RAIZ / ".prdrive" / "PRDRIVE").is_file(), True)

# --- Windows, desde su propia carpeta: se borra al salir, con RunOnce de respaldo
equipo.DIR = tmpdir("prdrive-equipo-pres2-")
PY, COD = instalado()
con_windows(lambda: presencia.registrar_arranque(PY, COD))
con_windows(lambda: presencia.registrar_ficha(PY, COD, "0.9.0"))
CORRE_DESDE["si"] = True
SUELTOS.clear()
msgs = con_windows(presencia.desinstalar)
c("desde su carpeta (el «Desinstalar» de Windows): la carpeta sigue mientras corre",
  equipo.DIR.exists(), True)
c("  y lo dice", any("se borra al cerrar" in m for m in msgs), True)
runonce = REGISTRO.leer(presencia.CLAVE_RUNONCE, "prdrive")
c("  con RunOnce por si algo sigue en uso al salir",
  (runonce or "").endswith(f'/d /c rmdir /s /q "{equipo.DIR}"'), True)
c("  todavía no se ha lanzado nada", SUELTOS, [])
con_windows(presencia.rematar)
c("rematar: lanza el cmd que la borra al quedar libre", SUELTOS,
  [presencia.orden_borrado(equipo.DIR)])
c("  una sola vez", (con_windows(presencia.rematar), len(SUELTOS)), (None, 1))
linea = presencia.orden_borrado(Path(r"C:\Users\Ana (casa)\AppData\Local\prdrive"))
c("orden_borrado: cmd con /s /c, la carpeta entre comillas, y quita su RunOnce al acabar",
  (" /d /s /c \"(for /l %i in (1,1,60) do " in linea,
   'rmdir /s /q "C:\\Users\\Ana (casa)\\AppData\\Local\\prdrive"' in linea,
   linea.endswith('reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce" '
                  '/v prdrive /f >nul 2>&1"')), (True, True, True))
c("una ruta con % no se apunta en RunOnce (cmd la expandiría)",
  con_windows(lambda: presencia.apuntar_borrado(Path(r"C:\Users\50%\prdrive"))), False)
CORRE_DESDE["si"] = False

# --- Linux: autostart, menú, caché y carpeta
equipo.DIR = tmpdir("prdrive-equipo-pres3-")
PY, COD = instalado()
presencia.registrar_arranque(PY, COD)
MENU.write_text("[Desktop Entry]\n", encoding="utf-8")
CACHE = presencia.cache_usuario()
(CACHE / "keepassxc").mkdir(parents=True, exist_ok=True)
(CACHE / "rclone-1-2").write_bytes(b"x")
c("Linux: el arranque es el autostart XDG", (AUTOSTART.is_file(),
                                             presencia.arranque_registrado()), (True, True))
c("  el plan dice que se borra la caché", any(str(CACHE) in m for m in
                                              presencia.plan_desinstalar().consequences), True)
msgs = presencia.desinstalar()
c("desinstalar en Linux: fuera el autostart, el menú, la caché y la carpeta",
  (AUTOSTART.exists(), MENU.exists(), CACHE.exists(), equipo.DIR.exists()),
  (False, False, False, False))
c("  y no toca la raíz", (RAIZ / ".prdrive" / "PRDRIVE").is_file(), True)
equipo.DIR = tmpdir("prdrive-equipo-pres4-")
instalado()
CACHE.mkdir(parents=True, exist_ok=True)
store.procesos_desde = lambda carpeta: {77: "/x/keepassxc"} if Path(carpeta) == CACHE else {}
msgs = presencia.desinstalar()
c("  una caché en uso (un KeePassXC abierto) se queda, y lo dice",
  (CACHE.exists(), any("sigue en uso" in m for m in msgs)), (True, True))
store.procesos_desde = lambda carpeta: dict(AJENOS) if Path(carpeta) == equipo.DIR else {}
CORRE_DESDE["si"] = True
equipo.DIR = tmpdir("prdrive-equipo-pres5-")
instalado()
presencia.desinstalar()
c("  desde su carpeta, también en Linux espera al final", equipo.DIR.exists(), True)
presencia.rematar()
c("  y rematar la borra", equipo.DIR.exists(), False)
CORRE_DESDE["si"] = False

# --- agente.py desinstalar
import agente  # noqa: E402
from ui import tk_desinstalar  # noqa: E402

cwd = os.getcwd()
try:
    equipo.DIR = tmpdir("prdrive-equipo-pres6-")
    instalado()
    tk_desinstalar.main = lambda plan: tk_desinstalar.SIN_VENTANA
    stdin_real = sys.stdin
    sys.stdin = io.StringIO("")
    try:
        rc = agente.main(["desinstalar"])
    finally:
        sys.stdin = stdin_real
    c("agente.py desinstalar sin ventana ni consola a la que preguntar: no toca nada",
      (rc, equipo.DIR.exists()), (2, True))
    abiertas: list = []
    tk_desinstalar.main = lambda plan: abiertas.append(plan) or tk_desinstalar.NO
    c("  con ventana, es ella quien pregunta (y aquí dice que no)",
      (agente.main(["desinstalar"]), len(abiertas), equipo.DIR.exists()), (1, 1, True))
    rc = agente.main(["desinstalar", "--si"])
    c("  --si desinstala sin preguntar", (rc, equipo.DIR.exists()), (0, False))
finally:
    os.chdir(cwd)

store.procesos_desde = store_procesos_desde
raise SystemExit(c.report())
