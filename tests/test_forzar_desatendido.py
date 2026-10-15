#!/usr/bin/env python3
"""Ninguna ruta desatendida puede pasar `--force`.

`--force` salta el freno de borrados de UNA pasada y lo pide una persona, desde la
ventana tras leer lo que va a pasar (`ui/repair.aviso_forzar()`), o a mano con
`python sync.py PAREJA --force`. El servicio, `--auto`, el agente y la ventana
principal no lo pasan nunca, igual que un resync no se lanza solo. Aquí se mira lo
que de verdad lanzan, no lo que dicen sus comentarios; y, para lo que no se haya
previsto, un recorrido por las fuentes que obliga a decidir cada vez que un
módulo nuevo nombra la opción.

Que `sync.py --force` sin nombrar pareja se rechace (la línea que haría
`runsync.py --daemon --force` si alguien la escribiera) está en `test_forzar.py`.
"""

import subprocess
import sys
from glob import glob
from pathlib import Path

from _harness import REPO, Checks, mkcfg, sandbox

import _agente_falso as F
import agente
import runsync
import ui
from common import equipo, model
from ui import repair

c = Checks("ninguna ruta desatendida pasa --force")

# ---- El servicio periódico y `--auto --once` -----------------------------------------------

llamadas: list[tuple[list, dict]] = []
real_run = subprocess.run


def run_falso(cmd, **kwargs):
    """Apunta lo que se lanza y contesta que fue bien."""
    llamadas.append((list(cmd), kwargs))
    return subprocess.CompletedProcess(cmd, 0, "", "")


with sandbox():
    subprocess.run = run_falso
    try:
        runsync.run_pair_quiet("notas")
        servicio = llamadas[-1]
        c("el servicio lanza sync.py con el nombre de la pareja y nada más",
          servicio[0][1:], [str(model.SYNC_PY), "notas"])
        c("  con la entrada cerrada: lo que pida confirmación se salta, no se contesta",
          servicio[1]["stdin"], subprocess.DEVNULL)

        real = (runsync.servicio_en_marcha, runsync.pareja_llavero, runsync.dlog,
                runsync.prioridad.bajar)
        runsync.servicio_en_marcha = lambda: None
        runsync.pareja_llavero = lambda: None
        runsync.dlog = lambda *_a, **_k: None
        runsync.prioridad.bajar = lambda: None
        try:
            runsync.una_pasada(["notas", "fotos"])
        finally:
            (runsync.servicio_en_marcha, runsync.pareja_llavero, runsync.dlog,
             runsync.prioridad.bajar) = real
        c("`--auto --once` pasa solo las parejas, sin opciones",
          llamadas[-1][0][1:], [str(model.SYNC_PY), "notas", "fotos"])
    finally:
        subprocess.run = real_run

# ---- La ventana principal y la consola --------------------------------------------------------

with sandbox():
    cfg = mkcfg(["notas"])
    c("«Sincronizar ahora» y el menú de consola piden la pasada normal, con o sin resync",
      [ui.manual_args(cfg, ["notas"], lambda pendientes, carpetas: si) for si in (True, False)],
      [["notas", "--yes"], ["notas"]])

with sandbox():
    cfg = mkcfg(["notas"])
    h = type("H", (), {"pareja": "notas"})()
    c("ni el resync ni la simulación de «Reparación» lo llevan",
      {a for args in (repair.args_resync(h), repair.args_simular(["notas"]))
       for a in args} & {"--force"}, set())

# ---- El agente ------------------------------------------------------------------------------------

F.preparar()
UID = "forzar-0001"
raiz = F.unidad(UID, parejas=("docs", "fotos"),
                daemon='[daemon]\npairs = ["docs", "fotos"]\ninterval_minutes = 5\n')
equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(
    equipo.Unidad(UID, equipo.DAEMON, "U", codigo=agente.huella(raiz) or "")))
F.RAICES[:] = [raiz]
ag = F.nuevo()
F.vueltas(ag, 3)
for _ in range(3):
    if ag.pasada is not None:
        F.acabar(ag.pasada.proc, 0, "[docs] OK.\n\nHecho. 1/1 parejas OK.\n")
        F.vueltas(ag, 1)
    F.pasar(6 * 60.0)
    F.vueltas(ag, 2)
lanzadas = F.pasadas(raiz)
c("el agente ha lanzado pasadas", len(lanzadas) >= 1, True)
c("  todas son sync.py, `--` y los nombres: lo que sigue a `--` nunca es una opción",
  all(p.args[2] == "--" and not any(a.startswith("-") for a in p.args[3:]) for p in lanzadas),
  True)
c("  y ninguna lleva --force", [p.args for p in lanzadas if "--force" in p.args], [])

# ---- Las fuentes: quién nombra la opción -------------------------------------------------------

PERMITIDOS = {
    "common/frenos.py": "las explicaciones de la consola y cómo se dice forzar",
    "common/model.py": "la razón por la que `force` es un flag reservado",
    "common/orden.py": "el flag que añade la orden de una pasada forzada",
    "common/revision.py": "el texto del hallazgo del freno (lo imprime --doctor)",
    "sync.py": "el argumento de la línea de órdenes",
    "ui/repair.py": "los argumentos que lanza «Forzar sincronización…» y su plan",
    "ui/flags_ayuda.py": "solo texto: un aviso del editor de flags («--force se salta --max-delete»)",
}
"""Los únicos módulos que nombran `--force`, y por qué.

Un módulo que lance `sync.py` y no esté aquí no puede pasarlo: si necesita nombrarlo,
que quien lo escriba lo piense y lo añada con su motivo, junto a un test que fije que
solo lo pasa quien lo pide una persona.
"""

fuentes = sorted({Path(f).as_posix() for g in ("*.py", "common/*.py", "ui/*.py", "install/*.py")
                  for f in glob(g, root_dir=REPO)})
nombran = {f for f in fuentes if "--force" in (REPO / f).read_text(encoding="utf-8")}
c("solo nombran --force los módulos previstos", sorted(nombran - set(PERMITIDOS)), [])
c("  y no queda ninguno previsto que ya no lo nombre (la lista no se pudre)",
  sorted(set(PERMITIDOS) - nombran), [])
lanzadores = {"runsync.py", "agente.py", "penwatch.py", "prdrive-install.py", "ui/__init__.py",
              "ui/tk.py", "ui/console.py", "common/llavero.py", "common/keepassxc.py"}
c("  y ninguno de los que lanzan sync.py (el servicio, el vigilante, el agente, las ventanas) "
  "está entre ellos", sorted(lanzadores & nombran), [])

sys.exit(c.report())
