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

sys.exit(c.report())
