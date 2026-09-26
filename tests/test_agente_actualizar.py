#!/usr/bin/env python3
"""
«Actualizar» el agente residente (fase 5, sección 8 del diseño).

  * El agente mira de tarde en tarde si hay una versión más nueva que la suya
    (en un hilo: es la red) y lo dice UNA vez; la bandeja ofrece «Actualizar a
    la vX», y mientras se actualiza, «Actualizando…» apagado.
  * «Actualizar» lanza un hijo suelto (`agente.py actualizar`), uno solo aunque
    se pida dos veces, y no espera nada: la cola no se para.
  * `agente.py actualizar` baja el código de la release con `update.download()`
    (a un temporal, nunca a una raíz), ejecuta SU instalador con
    `--update-agente` y el Python del agente, copia lo que dice al diario y
    borra el temporal. Sin versión nueva no baja nada; una descarga que no se
    comprueba no ejecuta nada.
  * `update.check()` y `pending()` guardan su caché donde se les diga: la del
    agente vive en su carpeta del equipo, no en ninguna raíz.
"""

import subprocess
import sys
from pathlib import Path

from _harness import Checks, tmpdir

import _agente_falso as F
import agente
from common import equipo, update
from ui import bandeja

c = Checks("«Actualizar» el agente")
F.preparar()
update.fetch = lambda url, timeout: c("ningún test toca la red", url, "nada")

REL = update.Release("v9.9.9", "9.9.9", "prdrive 9.9.9", update.PAGINA, "")

# --- mirar si hay versión nueva ----------------------------------------------------
buscadas: list = []
agente.buscar_version = lambda: buscadas.append(1) or REL
ag = F.nuevo()
ag.version = "0.4.0"
F.vueltas(ag, 1)
c("la primera vuelta mira si hay versión nueva", (buscadas, ag.nueva), ([1], "v9.9.9"))
F.vueltas(ag, 1)
c("  y lo dice una vez", [t for t, _ in F.AVISOS if "versión nueva" in t],
  ["Hay una versión nueva de prdrive: v9.9.9"])
F.vueltas(ag, 5)
c("  sin volver a mirar hasta MIRAR_VERSION, ni repetir el aviso",
  (len(buscadas), len([t for t, _ in F.AVISOS if "versión nueva" in t])), (1, 1))
F.pasar(agente.MIRAR_VERSION)
F.vueltas(ag, 1)
c("pasado MIRAR_VERSION, vuelve a mirar", len(buscadas), 2)
r = ag.resumen()
c("el resumen lleva su versión y la nueva", (r["version"], r["nueva"], r["actualizando"]),
  ("0.4.0", "v9.9.9", False))
c("la bandeja ofrece «Actualizar a la v9.9.9»",
  [e.pide for e in bandeja._todas(bandeja.vista(r).menu)
   if e.texto == "Actualizar a la v9.9.9"],
  [({"pide": equipo.PIDE_ACTUALIZAR},)])
c("  sin versión nueva, no",
  [e.texto for e in bandeja._todas(bandeja.vista({**r, "nueva": None}).menu)
   if e.texto.startswith("Actualiz")], [])

agente.buscar_version = lambda: (_ for _ in ()).throw(OSError("sin red"))
F.pasar(agente.MIRAR_VERSION)
F.vueltas(ag, 1)
c("sin red no pasa nada: se apunta y se sigue",
  (ag.nueva, any("no he podido mirar si hay versión nueva" in d for d in F.DIARIO)),
  ("v9.9.9", True))

# --- «Actualizar»: un hijo suelto ----------------------------------------------------
ag.pedir({"pide": equipo.PIDE_ACTUALIZAR})
F.vueltas(ag, 1)
hijos = [p for p in F.LANZADOS if p.args[-1] == "actualizar"]
c("«Actualizar» lanza agente.py actualizar, suelto y fuera de toda raíz",
  (len(hijos), hijos[0].args[1], hijos[0].kwargs.get("cwd")),
  (1, str(agente.SCRIPT_DIR / "agente.py"), str(equipo.DIR)))
r = ag.resumen()
c("  mientras, la bandeja dice «Actualizando…», apagado",
  [(e.texto, e.activa) for e in bandeja._todas(bandeja.vista(r).menu)
   if e.texto.startswith("Actualiz")], [("Actualizando a la v9.9.9…", False)])
ag.pedir({"pide": equipo.PIDE_ACTUALIZAR})
F.vueltas(ag, 1)
c("  pedirlo otra vez no lanza otro", len([p for p in F.LANZADOS
                                          if p.args[-1] == "actualizar"]), 1)
hijos[0].rc = 1
F.vueltas(ag, 1)
c("si acaba y el agente sigue siendo este, se puede volver a pedir",
  (ag.actualizando, ag.resumen()["actualizando"]), (None, False))

# --- agente.py actualizar ----------------------------------------------------------------
cache = tmpdir("prdrive-cache-") / "update.json"
agente.cache_version = lambda: cache
comprobado: list = []
update.check = lambda force=False, cache=None: comprobado.append((force, cache)) or (REL, None)
bajadas: list = []


def bajar(tag, destino, progreso=None):
    bajadas.append((tag, Path(destino)))
    Path(destino).mkdir(parents=True)
    (Path(destino) / "prdrive-install.py").write_text("", encoding="utf-8")
    return Path(destino)


update.download = bajar
ejecutadas: list = []
agente.ejecutar = lambda args, **kw: ejecutadas.append((args, kw)) or \
    subprocess.CompletedProcess(args, 0, "Actualizando el agente\n  Agente arrancado.\n", "")
update.installed_version = lambda root=None: "0.4.0"
F.AVISOS.clear()
rc = agente.main(["actualizar"])
c("agente.py actualizar pregunta a GitHub sin caché, con la del agente",
  comprobado[-1], (True, cache))
c("  baja el tag de la release a un temporal fuera de toda raíz",
  (bajadas[0][0], bajadas[0][1].is_relative_to(Path(agente.tempfile.gettempdir()))),
  ("v9.9.9", True))
args, kw = ejecutadas[0]
c("  ejecuta SU instalador con --update-agente y el Python del agente",
  args, [sys.executable, "-u", str(bajadas[0][1] / "prdrive-install.py"),
         "--update-agente"])
c("  con el directorio de trabajo en la carpeta del agente", kw.get("cwd"), str(equipo.DIR))
c("  lo que dice va al diario",
  any("actualizar:   Agente arrancado." in d for d in F.DIARIO), True)
c("  borra el temporal", bajadas[0][1].parent.exists(), False)
c("  y avisa de que está hecho", (rc, [t for t, _ in F.AVISOS]),
  (0, ["prdrive actualizado a la v9.9.9"]))

ejecutadas.clear()
bajadas.clear()
update.installed_version = lambda root=None: "9.9.9"
c("ya en la última: ni baja ni ejecuta nada", (agente.main(["actualizar"]), bajadas,
                                               ejecutadas), (0, [], []))
update.installed_version = lambda root=None: "0.4.0"


def bajar_mal(tag, destino, progreso=None):
    raise update.UpdateError("El zip descargado está dañado (x). No se ha extraído nada.")


update.download = bajar_mal
F.AVISOS.clear()
c("una descarga que no se comprueba no ejecuta nada",
  (agente.main(["actualizar"]), ejecutadas, [t for t, _ in F.AVISOS]),
  (1, [], ["prdrive: no he podido actualizar"]))
update.download = bajar
agente.ejecutar = lambda args, **kw: subprocess.CompletedProcess(args, 1, "", "InstallError\n")
F.AVISOS.clear()
c("si el instalador falla, se dice", (agente.main(["actualizar"]),
                                      [t for t, _ in F.AVISOS]),
  (1, ["prdrive: no he podido actualizar"]))

# --- la caché de update, donde se le diga --------------------------------------------------
import importlib  # noqa: E402

importlib.reload(update)
update.fetch = lambda url, timeout: (
    b'{"tag_name": "v9.9.9", "name": "x", "html_url": "u", "published_at": "p"}')
otra = tmpdir("prdrive-cache2-") / "sub" / "update.json"
rel, motivo = update.check(cache=otra)
c("update.check(cache=…) guarda ahí", (rel.tag, motivo, otra.is_file()), ("v9.9.9", None, True))
update.fetch = lambda url, timeout: c("con caché fresca no sale a la red", url, "nada")
c("  y la lee de ahí", update.check(cache=otra)[0].tag, "v9.9.9")
viejo = tmpdir("prdrive-viejo-")
(viejo / "VERSION").write_text("0.4.0\n", encoding="utf-8")
c("pending(raíz, cache=…) compara con la versión de esa raíz",
  update.pending(viejo, cache=otra).tag, "v9.9.9")
c("agent_command: el instalador de lo descargado, con --update-agente",
  update.agent_command("/t/x", "/py"), ["/py", "-u", str(Path("/t/x") / "prdrive-install.py"),
                                        "--update-agente"])

sys.exit(c.report())
