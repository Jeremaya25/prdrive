#!/usr/bin/env python3
"""«Actualizar» el agente residente (fase 5, sección 8 del diseño).

Lo que se comprueba:
- El agente mira de tarde en tarde si hay una versión más nueva que la suya (en
  un hilo: es la red) y lo dice UNA vez; la bandeja ofrece «Actualizar a la vX»
  y, mientras se actualiza, «Actualizando…» apagado.
- «Actualizar» lanza un hijo suelto (`agente.py actualizar`), uno solo aunque
  se pida dos veces, y no espera nada: la cola no se para.
- `agente.py actualizar` baja el código de la release con `update.download()`
  (a un temporal, nunca a una raíz), ejecuta SU instalador con
  `--update-agente` y el Python del agente, copia lo que dice al diario y borra
  el temporal. Sin versión nueva no baja nada; una descarga que no se comprueba
  no ejecuta nada.
- `update.check()` y `pending()` guardan su caché donde se les diga: la del
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

# mirar si hay versión nueva
buscadas: list = []
agente.buscar_version = lambda: buscadas.append(1) or REL
ag = F.nuevo()
ag.version = "0.4.0"
F.vueltas(ag, 1)
c("la primera vuelta mira si hay versión nueva", (buscadas, ag.nueva), ([1], "v9.9.9"))
F.vueltas(ag, 1)
c("  y lo dice una vez", [t for t, _ in F.AVISOS if "versión nueva" in t],
  ["Hay una versión nueva de prdrive: v9.9.9"])
c("  sin bandeja, cómo ponerla a mano",
  [x for t, x in F.AVISOS if "versión nueva" in t][0].endswith("agente.py actualizar"), True)


class Icono:
    """Bandeja de mentira que dice si su icono está puesto."""
    puesta = False


ag.bandeja = Icono()
c("  una bandeja sin icono puesto (Linux sin watcher) no cuenta", ag.con_bandeja(), False)
Icono.puesta = True
c("  con el icono puesto, sí: «Actualízala desde su icono»", ag.con_bandeja(), True)
ag.bandeja = None
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

# «Buscar actualizaciones»: preguntar ya, sin esperar a la caché ni a MIRAR_VERSION
agente.buscar_version = lambda: None
bs = F.nuevo()
bs.version = "0.4.0"
F.vueltas(bs, 1)
preguntadas: list = []
respuesta: list = [(REL, None)]
agente.buscar_version_ya = lambda: preguntadas.append(1) or respuesta[0]
c("sin versión nueva conocida, la bandeja ofrece «Buscar actualizaciones»",
  [e.pide for e in bandeja._todas(bandeja.vista(bs.resumen()).menu)
   if e.texto == "Buscar actualizaciones"],
  [({"pide": equipo.PIDE_BUSCAR_VERSION},)])
F.AVISOS.clear()
bs.pedir({"pide": equipo.PIDE_BUSCAR_VERSION})
F.vueltas(bs, 1)
c("pedirlo pregunta a GitHub una vez, y apunta la versión nueva",
  (len(preguntadas), bs.nueva, bs.buscando), (1, "v9.9.9", False))
c("  y la dice como siempre, sin aviso de más",
  [t for t, _ in F.AVISOS], ["Hay una versión nueva de prdrive: v9.9.9"])
c("  ya conocida, la bandeja ofrece «Actualizar» y no «Buscar»",
  [e.texto for e in bandeja._todas(bandeja.vista(bs.resumen()).menu)
   if e.texto.startswith(("Actualiz", "Buscar"))], ["Actualizar a la v9.9.9"])

al_dia = update.Release("v0.4.0", "0.4.0", "prdrive 0.4.0", update.PAGINA, "")
respuesta[0] = (al_dia, None)
bs.nueva, bs.nueva_avisada = None, None
F.AVISOS.clear()
bs.pedir({"pide": equipo.PIDE_BUSCAR_VERSION})
F.vueltas(bs, 1)
c("ya en la última: lo dice y no hay nada que actualizar",
  (bs.nueva, [x for _, x in F.AVISOS]), (None, ["Ya tienes la última versión (0.4.0)"]))

respuesta[0] = (None, "No he podido preguntarle a GitHub si hay versión nueva: sin red")
bs.nueva = bs.nueva_avisada = "v9.9.9"
F.AVISOS.clear()
bs.pedir({"pide": equipo.PIDE_BUSCAR_VERSION})
F.vueltas(bs, 1)
c("sin red lo dice y no olvida lo que ya sabía",
  (bs.nueva, len(F.AVISOS), "sin red" in F.AVISOS[0][1]), ("v9.9.9", 1, True))
agente.buscar_version_ya = lambda: (_ for _ in ()).throw(OSError("roto"))
F.AVISOS.clear()
bs.pedir({"pide": equipo.PIDE_BUSCAR_VERSION})
F.vueltas(bs, 1)
c("una excepción tampoco tumba al agente: se dice y se libera",
  (bs.buscando, len(F.AVISOS)), (False, 1))

# mientras busca no se acepta otra, y la bandeja lo dice apagado
agente.hilo = lambda funcion: None            # el hilo no llega a correr
bs.nueva = None
bs.pedir({"pide": equipo.PIDE_BUSCAR_VERSION})
F.vueltas(bs, 1)
c("mientras busca, la bandeja dice «Buscando…», apagado",
  [(e.texto, e.activa) for e in bandeja._todas(bandeja.vista(bs.resumen()).menu)
   if e.texto.startswith(("Buscand", "Buscar"))], [("Buscando actualizaciones…", False)])
antes = len(F.DIARIO)
bs.pedir({"pide": equipo.PIDE_BUSCAR_VERSION})
F.vueltas(bs, 1)
c("  pedirlo otra vez no lanza otra",
  any("ya se está buscando" in d for d in F.DIARIO[antes:]), True)
agente.hilo = lambda funcion: funcion()

# el veredicto, el mismo en la ventana y en la bandeja
c("veredicto: hay una nueva", update.veredicto(REL, None, "0.4.0"),
  "Hay una versión nueva: v9.9.9")
c("  ya está al día", update.veredicto(REL, None, "9.9.9"),
  "Ya tienes la última versión (9.9.9)")
c("  un fallo manda aunque haya caché, y solo dice la primera línea",
  update.veredicto(REL, "No he podido mirar.\nSe enseña lo último.", "0.4.0"),
  "No he podido mirar.")
c("  sin release ni motivo", update.veredicto(None, None, "0.4.0"),
  "No sé qué versión es la última.")

# «Actualizar»: un hijo suelto
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

# agente.py actualizar
cache = tmpdir("prdrive-cache-") / "update.json"
agente.cache_version = lambda: cache
comprobado: list = []
update.check = lambda force=False, cache=None: comprobado.append((force, cache)) or (REL, None)
bajadas: list = []


def bajar(tag, destino, progreso=None):
    """Descarga de mentira: apunta lo pedido y deja un instalador vacío."""
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
    """Descarga que falla porque el zip está dañado."""
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

# la caché de update, donde se le diga
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
