#!/usr/bin/env python3
"""
Lo que la revisión del PR #54 encontró en el agente y su instalación, y que se
arregla sin cambiar el diseño:

  * **Nombres de pareja que no son solo nombres.** `--resync` como nombre sería
    la opción de `sync.py` (y con ella, todas las parejas); `a/b` o `..`
    saldrían de `state/` y `filters/`. El parser común los rechaza, el agente no
    los lanza aunque el `sync.py` de la raíz sea de antes, y a `sync.py` le pasa
    el nombre detrás de un `--`.
  * **Un solo agente por equipo**, con el lock tomado en UN paso (O_EXCL): dos
    arranques a la vez no pueden ver los dos que no hay nadie.
  * **Escribir en una raíz sin seguir enlaces**: el diario y el lock del
    servicio que el agente deja en una unidad no pueden acabar, por un enlace,
    en un fichero del equipo; y el temporal de `store.write_json()` tampoco.
  * **La raíz del equipo, por enlaces**: una raíz elegida por un enlace que
    lleva a la carpeta del agente se rechaza, y una pareja cuyo `local` sale por
    un enlace de la raíz, también.
  * **«Actualizar» no escribe en un volumen fantasma**: una raíz cifrada con la
    letra y el id pero el `.hc` libre (H-10) cuenta como bloqueada.
  * **`install/` no importa `ui/`**: los iconos los pinta quien lanza la
    instalación (`install.pintar_iconos`).

Y lo que pedía cambiar el diseño, en una segunda vuelta:

  * **Un solo servicio por unidad**: el agente y el servicio de runsync toman
    `daemon.lock.json` en UN paso (`store.tomar_registro()`); el servicio le
    pide al agente que se aparte y espera a que suelte, el lanzador no le
    quita el lock al agente a mitad de pareja, y el agente mira que el lock
    sigue siendo suyo justo antes de lanzar.
  * **Parar el agente espera a su pasada**: la pasada queda apuntada
    (`pasada.json`), `parar_agente()` espera a que acabe, y pasado el plazo la
    corta con su rclone; un agente nuevo no lanza nada mientras siga viva la
    del anterior.
  * **El id no es una credencial**: al decir que sí se apunta la huella del
    código de la unidad (`agente.huella()`), y con otra se vuelve a preguntar.
"""

import ast
import os
import sys
from pathlib import Path

from _harness import Checks, tmpdir

import _agente_falso as F
import agente
import install
from common import equipo, model, store
from install import agente as ia, raiz_equipo

c = Checks("el agente, endurecido tras la revisión")
F.preparar()


def enlace(destino: Path, nombre: Path, carpeta: bool = False) -> bool:
    """Un enlace simbólico, si el sistema deja crearlo (Windows pide un permiso)."""
    try:
        os.symlink(destino, nombre, target_is_directory=carpeta)
        return True
    except (OSError, NotImplementedError):
        print(f"  (saltado) sin permiso para crear enlaces: {nombre.name}")
        return False


# --- nombres de pareja ------------------------------------------------------------
for nombre in ("--resync", "-x", "a/b", "a\\b", "..", ".", "c:d", "x\ty"):
    c(f"el nombre {nombre!r} no vale", model.problema_nombre(nombre) is not None, True)
for nombre in ("docs", "Mis fotos", "notas-2024", "ñandú_1"):
    c(f"el nombre {nombre!r} vale", model.problema_nombre(nombre), None)
try:
    model.parse_config({"pair": [{"name": "--resync", "local": "a", "remote_path": "/a"}]})
    c("el parser común lo rechaza", False, True)
except model.ConfigError as e:
    c("el parser común lo rechaza", "'-'" in str(e), True)

raiz = F.unidad("n" * 32, parejas=("docs",))
conf = raiz / ".prdrive" / "sync_config.toml"
conf.write_text(conf.read_text(encoding="utf-8")
                + '[[pair]]\nname = "--resync"\nlocal = "x"\nremote_path = "/x"\n\n'
                + '[[pair]]\nname = "../fuera"\nlocal = "y"\nremote_path = "/y"\n',
                encoding="utf-8")
c("el agente no lanza una pareja con un nombre así, aunque su sync.py sea de antes",
  [p.nombre for p in agente.leer_servicio(raiz).parejas], ["docs"])

# --- un solo agente ------------------------------------------------------------------
equipo.lock_json().unlink(missing_ok=True)
yo = {"pid": os.getpid(), "host": equipo.HOST, "started": "x"}
c("el primer agente toma el lock", equipo.tomar_lock(yo), None)
c("  y queda escrito el suyo", store.read_json(equipo.lock_json())["pid"], os.getpid())
c("un segundo arranque ve al primero y se va",
  (equipo.tomar_lock({**yo, "pid": 1}) or {}).get("pid"), os.getpid())
store.write_json(equipo.lock_json(), {"pid": 2 ** 22 + 7, "host": equipo.HOST})
c("el resto de un agente muerto se retira y se toma",
  (equipo.tomar_lock(yo), store.read_json(equipo.lock_json())["pid"]), (None, os.getpid()))
store.write_json(equipo.lock_json(), {"pid": os.getpid(), "host": "otro-equipo"})
c("  el de otro equipo, también", equipo.tomar_lock(yo), None)
c("crear en exclusiva: el que llega segundo no pisa",
  (store.crear_exclusivo(equipo.lock_json(), b"{}")), False)
equipo.lock_json().unlink()
c("cmd_run se va sin tocar nada si otro agente está vivo",
  (store.write_json(equipo.lock_json(), {"pid": os.getppid(), "host": equipo.HOST}),
   agente.main(["run"]), store.read_json(equipo.lock_json())["pid"]),
  (True, 0, os.getppid()))
equipo.lock_json().unlink()

# --- escribir en una raíz sin seguir enlaces ---------------------------------------------
fuera = tmpdir("prdrive-fuera-")
victima = fuera / "bashrc"
victima.write_text("original\n", encoding="utf-8")
estado = raiz / ".prdrive" / "state"
if enlace(victima, estado / "daemon.log"):
    agente.dlog(raiz, "hola")
    c("el diario de la raíz no sigue un enlace a un fichero del equipo",
      victima.read_text(encoding="utf-8"), "original\n")
    (estado / "daemon.log").unlink()
if enlace(victima, estado / "daemon.lock.tmp"):
    store.write_json(estado / "daemon.lock.json", {"pid": 1})
    c("el temporal de write_json no sigue un enlace que ya estuviera",
      (victima.read_text(encoding="utf-8"), store.read_json(estado / "daemon.lock.json")),
      ("original\n", {"pid": 1}))
otra = F.unidad("m" * 32, parejas=("docs",))
estado_otra = otra / ".prdrive" / "state"
import shutil  # noqa: E402
shutil.rmtree(estado_otra)
if enlace(fuera, estado_otra, carpeta=True):
    c("un state/ que lleva fuera de la raíz no es sitio para escribir",
      agente.en_la_raiz(otra, estado_otra / "daemon.lock.json"), None)
    agente.dlog(otra, "hola")
    c("  y el diario no escribe allí", (fuera / "daemon.log").exists(), False)
c("dentro de la raíz, sí", agente.en_la_raiz(raiz, estado / "daemon.lock.json"),
  estado / "daemon.lock.json")

# --- la raíz del equipo, por enlaces ------------------------------------------------------
casa = tmpdir("prdrive-casa-")
raiz_equipo.carpeta_personal = lambda: casa
raiz_equipo.carpetas_sincronizadas = lambda: []
atajo = casa / "atajo"
if enlace(equipo.DIR, atajo, carpeta=True):
    c("una raíz elegida por un enlace a la carpeta del agente no vale",
      raiz_equipo.examinar(atajo).estado, raiz_equipo.NO_VALE)
mia = casa / "PRDRIVE"
mia.mkdir()
if enlace(fuera, mia / "docs", carpeta=True):
    info = raiz_equipo.revisar_local(mia, "docs")
    c("una pareja cuyo local sale de la raíz por un enlace no vale",
      (info.error is not None, "fuera de la raíz" in (info.error or "")), (True, True))
if enlace(equipo.DIR, mia / "agente", carpeta=True):
    c("  y la que cae en la carpeta del agente, tampoco",
      "carpeta del agente" in (raiz_equipo.revisar_local(mia, "agente").error or ""), True)
c("una pareja normal dentro, sí", raiz_equipo.revisar_local(mia, "fotos").error, None)

# --- «Actualizar» y el volumen fantasma -----------------------------------------------------
fantasma = tmpdir("prdrive-fantasma-")
(fantasma / ".prdrive").mkdir()
(fantasma / ".prdrive" / "PRDRIVE").write_text("id=" + "g" * 32 + "\ntipo=equipo\n",
                                               encoding="utf-8")
equipo.guardar_ajustes(equipo.Ajustes().con_unidad(
    equipo.Unidad("g" * 32, equipo.DAEMON, "Fantasma", str(fantasma), "C:\\x\\PRDRIVE.hc")))
desplegadas: list = []
ia_deploy = __import__("install.deploy", fromlist=["deploy_code"])
real_deploy = ia_deploy.deploy_code
ia_deploy.deploy_code = lambda raiz, origen=None: desplegadas.append(Path(raiz)) or []
ia.vestibulo.retenido = lambda contenedor: False       # el .hc, libre
msgs = ia.actualizar_raices()
c("una raíz cifrada con el id a la vista pero el .hc libre es un fantasma: no se toca",
  (desplegadas, any("Fantasma: bloqueada" in m for m in msgs)), ([], True))
ia.vestibulo.retenido = lambda contenedor: True        # abierta de verdad
ia.actualizar_raices()
c("  abierta de verdad (el .hc retenido), sí", desplegadas, [fantasma])
ia_deploy.deploy_code = real_deploy

# --- install/ no importa ui/ -------------------------------------------------------------------
carpeta = Path(install.__file__).parent
importa_ui = []
for fichero in sorted(carpeta.glob("*.py")):
    for nodo in ast.walk(ast.parse(fichero.read_text(encoding="utf-8"))):
        nombres = ([a.name for a in nodo.names] if isinstance(nodo, ast.Import) else
                   [nodo.module or ""] if isinstance(nodo, ast.ImportFrom) else [])
        if any(n == "ui" or n.startswith("ui.") for n in nombres):
            importa_ui.append(fichero.name)
c("install/ no importa ui/ (los iconos, por install.pintar_iconos)", importa_ui, [])
pintadas: list = []
install.pintar_iconos = lambda carpeta, bandeja: pintadas.append((carpeta.name, bandeja))
install.pintar(Path("x"), bandeja=True)
install.pintar_iconos = lambda carpeta, bandeja: 1 / 0
install.pintar(Path("y"))
c("  pinta quien se lo diga, y un fallo no tumba la instalación", pintadas, [("x", True)])
install.pintar_iconos = None

# === Segunda vuelta ================================================================
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import penwatch  # noqa: E402
import runsync  # noqa: E402
from common import planificador as pl  # noqa: E402

F.RAICES[:] = []


def servida(uid: str, **kw):
    """Un agente nuevo con una unidad de la lista ya conectada y atendida."""
    r = F.unidad(uid, **kw)
    equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(
        equipo.Unidad(uid, equipo.DAEMON, "U", codigo=agente.huella(r) or "")))
    F.RAICES[:] = [r]
    a = F.nuevo()
    F.vueltas(a, 2)
    return a, r


# --- un solo servicio: el agente toma el lock en un paso ---------------------------------
S = "5" * 32
RS = F.unidad(S, parejas=("docs",))
equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(
    equipo.Unidad(S, equipo.DAEMON, "S", codigo=agente.huella(RS) or "")))
F.RAICES[:] = [RS]
ag = F.nuevo()
F.vueltas(ag, 1)
# El servicio de runsync escribe su lock justo entre que el agente mira y
# escribe: se simula haciendo que el agente no vea a nadie al mirar.
F.otro_servicio(RS)
ag._otro_servicio = lambda con: None
F.vueltas(ag, 2)
c("con otro servicio vivo en el lock al ir a escribir, el agente no lo pisa",
  (F.lock(RS).get("pid"), ag.conexiones[S].lock, len(F.pasadas(RS))),
  (os.getppid(), None, 0))
del ag._otro_servicio
(RS / penwatch.DAEMON_LOCK_REL).unlink()
F.vueltas(ag, 1)
c("  sin nadie, lo toma", F.lock(RS).get("pid"), os.getpid())
F.acabar(F.pasadas(RS)[-1])
F.vueltas(ag, 1)
F.otro_servicio(RS)                     # un runsync de antes, escribiendo sin mirar
antes = len(F.pasadas(RS))
ag._lanzar(pl.Tarea(pl.PASADA, S, "docs"), F.reloj())
c("justo antes de lanzar, si el lock ya no es suyo, no lanza",
  (len(F.pasadas(RS)), ag.conexiones[S].lock), (antes, None))
F.stop(RS).touch()
F.vueltas(ag, 2)
c("el stop de OTRO servicio no se lo come el agente: es para ese",
  F.stop(RS).exists(), True)
F.stop(RS).unlink()
(RS / penwatch.DAEMON_LOCK_REL).unlink()

# --- un solo servicio: el lado de runsync -------------------------------------------------
estado_rs = tmpdir("prdrive-runsync-")
runsync.LOCK = estado_rs / "daemon.lock.json"
runsync.STOP = estado_rs / "daemon.stop"
runsync.HOST = equipo.HOST
runsync.pen_present = lambda: True
datos = {"pid": os.getpid(), "host": equipo.HOST, "started": "x", "pairs": ["docs"]}
c("el servicio de runsync toma el lock libre", (runsync.tomar_lock(dict(datos)),
                                                 runsync.read_lock()["pid"]), (None, os.getpid()))
runsync.LOCK.unlink()
store.write_json(runsync.LOCK, {"pid": os.getppid(), "host": equipo.HOST})
c("  con otro servicio de runsync vivo, manda ese",
  (runsync.tomar_lock(dict(datos)) or {}).get("pid"), os.getppid())
store.write_json(runsync.LOCK, {"pid": 2 ** 22 + 9, "host": equipo.HOST})
c("  el de un pid muerto se retira", runsync.tomar_lock(dict(datos)), None)
runsync.LOCK.unlink()

# El agente lo tiene: se le pide que se aparte (daemon.stop) y se espera a que
# suelte, como hace él al acabar su pareja.
store.write_json(runsync.LOCK, {"pid": os.getppid(), "host": equipo.HOST, "agente": True})


def agente_que_suelta():
    limite = time.monotonic() + 5
    while time.monotonic() < limite and not runsync.STOP.exists():
        time.sleep(0.02)
    time.sleep(0.2)                     # acaba su pareja
    runsync.LOCK.unlink()
    runsync.STOP.unlink()


hilo = threading.Thread(target=agente_que_suelta)
hilo.start()
tomado = runsync.tomar_lock(dict(datos))
hilo.join()
c("con el lock del agente, el servicio le pide que se aparte y espera a que suelte",
  (tomado, runsync.read_lock()["pid"], runsync.STOP.exists()), (None, os.getpid(), False))
runsync.LOCK.unlink()
store.write_json(runsync.LOCK, {"pid": os.getppid(), "host": equipo.HOST, "agente": True})
runsync.ESPERA_AGENTE = 0.5
c("  un agente que no suelta: pasado el plazo, el servicio no arranca",
  (runsync.tomar_lock(dict(datos)) or {}).get("agente"), True)
runsync.STOP.unlink(missing_ok=True)
runsync.STOP_WAIT_SECONDS = 0.3
dicho = runsync.stop_previous_daemon()
c("el lanzador no le quita el lock al agente a mitad de pareja",
  ("a mitad de una pareja" in (dicho or ""), runsync.read_lock().get("agente")), (True, True))
runsync.LOCK.unlink()
runsync.STOP.unlink(missing_ok=True)

# --- parar el agente espera a su pasada ----------------------------------------------------
P = "4" * 32
ag, RP = servida(P, parejas=("docs",))
apuntada = store.read_json(equipo.pasada_json())
c("la pasada queda apuntada fuera de la unidad, con qué es",
  (apuntada.get("agente"), apuntada.get("unidad"), apuntada.get("pareja")),
  (os.getpid(), "U", "docs"))
lanzada = F.pasadas(RP)[-1]
if os.name != "nt":
    c("  en su propia sesión, para poder cortarla con su rclone",
      lanzada.kwargs.get("start_new_session"), True)
c("  y los .pyc de sus hijos, en la carpeta del agente",
  lanzada.kwargs.get("env", {}).get("PYTHONPYCACHEPREFIX"), str(equipo.DIR / "pycache"))
F.acabar(lanzada)
F.vueltas(ag, 1)
c("acabada, se borra", equipo.pasada_json().exists(), False)

viva = {"pid": os.getppid(), "agente": 2 ** 22 + 3, "unidad": "U", "pareja": "docs"}
equipo.apuntar_pasada(viva)
c("una pasada viva de este arranque cuenta", (equipo.pasada_viva() or {}).get("pid"),
  os.getppid())
arr = store.arranque_del_sistema()
if arr is not None:
    store.write_json(equipo.pasada_json(), {**viva, "host": equipo.HOST,
                                            "arranque": arr - 10_000})
    c("  la de otro arranque del sistema, no (el pid se reutiliza)",
      equipo.pasada_viva(), None)
equipo.apuntar_pasada(viva)
F.pasar(3600)
ag2 = F.nuevo()
c("un agente nuevo ve la pasada que dejó viva el anterior", ag2.heredada is not None, True)
antes = len(F.pasadas(RP))
F.vueltas(ag2, 3)
c("  y no lanza nada mientras siga", (len(F.pasadas(RP)), "agente anterior" in
                                       (ag2.retenido or "")), (antes, True))
equipo.apuntar_pasada({**viva, "pid": 2 ** 22 + 5})
F.vueltas(ag2, 1)
c("  acabada, vuelve a lo suyo", (ag2.heredada, len(F.pasadas(RP))), (None, antes + 1))
F.acabar(F.pasadas(RP)[-1])
F.vueltas(ag2, 1)

ia.ESPERA_PASADA = 0.8
avances: list = []
hijo = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.3)"],
                        start_new_session=os.name != "nt")
# Quien la recoge al acabar es su padre (el agente); aquí, un hilo: sin eso
# quedaría zombi, y un zombi sigue «vivo» para pid_alive().
threading.Thread(target=hijo.wait, daemon=True).start()
equipo.apuntar_pasada({**viva, "pid": hijo.pid})
dicho = ia.parar_agente(lambda f, t: avances.append(t))
c("parar_agente() espera a que acabe la pasada", "tras acabar su pasada" in (dicho or ""),
  True)
c("  y dice a qué espera", any("«docs»" in t for t in avances), True)
hijo = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                        start_new_session=os.name != "nt")
equipo.apuntar_pasada({**viva, "pid": hijo.pid})
t0 = time.monotonic()
dicho = ia.parar_agente()
try:
    hijo.wait(5)
except subprocess.TimeoutExpired:
    hijo.kill()
c("  pasado el plazo, la corta con su árbol y dice qué pareja era",
  (hijo.returncode is not None and hijo.returncode != 0, "se ha cortado" in (dicho or ""),
   "«docs»" in (dicho or "")), (True, True, True))
equipo.pasada_json().unlink(missing_ok=True)

# --- el id no es una credencial: la huella del código --------------------------------------
H = "3" * 32
RH = F.unidad(H, parejas=("docs",))
base = agente.huella(RH)
app_h = RH / ".prdrive"
(app_h / "state" / "algo.json").write_text("{}", encoding="utf-8")
(app_h / "sync_config.toml").write_text((app_h / "sync_config.toml").read_text(
    encoding="utf-8") + "\n# editado desde la ventana\n", encoding="utf-8")
(app_h / "icono-verde.ico").write_bytes(b"ico")
(app_h / "__pycache__").mkdir()
(app_h / "__pycache__" / "sync.cpython-312.pyc").write_bytes(b"pyc")
c("la huella no cambia con lo que cambia con el uso (estado, config, iconos, pyc)",
  agente.huella(RH), base)
(app_h / "json.py").write_text("print('hola')\n", encoding="utf-8")
c("  sí con un .py nuevo junto al programa (se importaría antes que el de verdad)",
  agente.huella(RH) != base, True)
(app_h / "json.py").unlink()
(app_h / "rclone.conf").write_text("[nas]\ntype = sftp\nssh = evil\n", encoding="utf-8")
c("  y con rclone.conf (la opción ssh de sftp es una orden)", agente.huella(RH) != base, True)
(app_h / "rclone.conf").unlink()

F.RAICES[:] = []
ag, RH2 = servida(H.replace("3", "2"), parejas=("docs",))
H2 = "2" * 32
c("atendida con su huella, se sirve", F.lock(RH2).get("pid"), os.getpid())
F.acabar(F.pasadas(RH2)[-1])
F.vueltas(ag, 1)
F.RAICES[:] = []
F.vueltas(ag, 2)
(RH2 / ".prdrive" / "sync.py").write_text("import os  # otro\n", encoding="utf-8")
preguntas_antes = [x for x in F.LANZADOS if "pregunta" in x.args]
F.RAICES[:] = [RH2]
pasadas_antes = len(F.pasadas(RH2))
F.vueltas(ag, 4)
preguntas = [x for x in F.LANZADOS if "pregunta" in x.args][len(preguntas_antes):]
c("con otro código, se vuelve a preguntar, diciéndolo",
  (len(preguntas), "--cambiada" in (preguntas[-1].args if preguntas else [])), (1, True))
c("  y hasta el sí no se ejecuta nada suyo: ni lock ni pasadas",
  (F.lock(RH2), len(F.pasadas(RH2))), ({}, pasadas_antes))
fila = next(u for u in ag.resumen()["unidades"] if u["id"] == H2)
c("  la bandeja la ofrece para atender, como cambiada", (fila["en_lista"], fila["cambiada"]),
  (False, True))
equipo.pedir({"pide": equipo.PIDE_ABRIR, "id": H2})
F.vueltas(ag, 1)
c("  «Abrir» no abre su ventana",
  [x for x in F.LANZADOS if x.args[-1].endswith("runsync.py")
   and x.args[-1].startswith(str(RH2))], [])
preguntas[-1].rc = 0                    # «Atender»
F.vueltas(ag, 2)
c("al decir que sí, apunta la huella nueva y conserva su modo",
  (equipo.leer_ajustes().unidades[H2].codigo, equipo.leer_ajustes().unidades[H2].modo),
  (agente.huella(RH2), equipo.DAEMON))
c("  y la vuelve a servir", F.lock(RH2).get("pid"), os.getpid())

# --- el rclone es el del agente, nunca el de la unidad --------------------------------------
base = agente.huella(RH)
(app_h / "bin" / "x64").mkdir(parents=True)
(app_h / "bin" / "x64" / "rclone").write_bytes(b"otro binario cualquiera")
c("la huella no lee bin/: el rclone de la unidad no se ejecuta", agente.huella(RH), base)
propio = F.RCLONE[0]
os.environ[model.RCLONE_DEL_AGENTE] = str(propio)
try:
    c("sync.py usa el rclone que pasa el agente", model.rclone_path(), propio)
    os.environ[model.RCLONE_DEL_AGENTE] = str(propio.with_name("no-esta"))
    c("  y si no está, ninguno: nunca cae en el de la unidad", model.rclone_path(), None)
    try:
        model.rclone_binary()
        dijo = ""
    except SystemExit as e:
        dijo = str(e)
    c("  y lo dice al fallar", "ha pasado su rclone" in dijo, True)
finally:
    del os.environ[model.RCLONE_DEL_AGENTE]
c("sin el agente, el de la unidad como siempre",
  model.rclone_path() in (None, *(d / model.rclone_name() for d in
                                  (model.BIN_DIR, *model.BIN_FALLBACK_DIRS))), True)

# --- unidades de antes de la 0.5.0: no se atienden -----------------------------------------
V = "6" * 32
RV = F.unidad(V, parejas=("docs",))
(RV / ".prdrive" / "VERSION").write_text("0.4.3\n", encoding="utf-8")
equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(
    equipo.Unidad(V, equipo.UI, "Vieja", codigo=agente.huella(RV) or "")))
F.RAICES[:] = [RV]
F.AVISOS.clear()
ag = F.nuevo()
F.vueltas(ag, 4)
c("una unidad de la lista con la 0.4.3: ni lock, ni pasadas, ni su ventana",
  (F.lock(RV), len(F.pasadas(RV)),
   [x for x in F.LANZADOS if x.args[-1] == str(RV / ".prdrive" / "runsync.py")]),
  ({}, 0, []))
c("  lo avisa diciendo qué versión lleva",
  [t for t, x in F.AVISOS if "0.4.3" in x and "actualices" in x],
  ["Vieja: su programa es anterior a la 0.5.0"])
c("  y lo dice como motivo", "0.4.3" in ag.conexiones[V].motivo, True)
from ui import bandeja  # noqa: E402
menu = [e for e in bandeja.vista(ag.resumen()).menu if "Vieja" in e.texto]
c("  la bandeja lo dice, sin ofrecer abrirla",
  [(e.texto, e.activa) for e in menu], [("Vieja: actualízala para que la atienda", False)])
W = "2" * 31 + "9"
RW = F.unidad(W, parejas=("docs",))
(RW / ".prdrive" / "VERSION").unlink()
F.RAICES[:] = [RW]
antes = [x for x in F.LANZADOS if "pregunta" in x.args]
F.vueltas(ag, 4)
c("una desconocida sin VERSION no se pregunta: primero hay que actualizarla",
  [x for x in F.LANZADOS if "pregunta" in x.args], antes)

T = "1" * 32
RT = F.unidad(T, parejas=("docs",))
equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(equipo.Unidad(T, equipo.DAEMON)))
F.RAICES[:] = [RT]
ag = F.nuevo()
F.vueltas(ag, 2)
c("atendida sin haberla visto (el asistente): la huella se apunta al conectarla",
  (equipo.leer_ajustes().unidades[T].codigo, F.lock(RT).get("pid")),
  (agente.huella(RT), os.getpid()))

sys.exit(c.report())
