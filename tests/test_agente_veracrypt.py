#!/usr/bin/env python3
"""
El agente residente con la raíz de este equipo CIFRADA con VeraCrypt (fase 3).

Con un VeraCrypt de mentira: lo que se lanza se apunta (`_agente_falso.Proc`) y
«montar» es que aparezca la raíz en su punto de montaje. Se comprueba:

  * la orden de abrir no lleva nunca la contraseña, y sí el destino fijo
    (`/letter` y `rm` en Windows; la carpeta en Linux);
  * abierta se decide al VER el id, no por la salida de VeraCrypt;
  * bloqueada, solo con el volumen de verdad cerrado; con «No» a forzar, sigue
    abierta y se dice;
  * `pedir_al_iniciar`: una vez al arrancar, no tras cancelar, nunca si está
    desactivado; y el ajuste lo escribe el agente, no quien lo pide;
  * el fantasma (letra con id y `.hc` libre) no se atiende;
  * un punto de montaje con cosas no se tapa;
  * `vestibulo.raiz_fisica()` encuentra la carpeta del contenedor por las
    raíces extra.
"""

import shutil
import sys
from pathlib import Path

from _harness import Checks, tmpdir

import _agente_falso as F
import agente
import penwatch
from common import equipo, store, vestibulo

c = Checks("agente: la raíz cifrada de este equipo")

F.preparar()
penwatch.candidate_roots = lambda cfg: ([Path(r) for r in cfg.get("extra_roots", [])]
                                        + list(F.RAICES))
VC = "/opt/veracrypt/veracrypt"
penwatch.installed_veracrypt = lambda: VC
penwatch._con_escritorio = lambda: True
RETENIDO: list = [None]             # lo que contesta vestibulo.retenido (Linux: None)
vestibulo.retenido = lambda hc: RETENIDO[0]

UID = "c" * 32
FISICA = tmpdir("prdrive-cifrado-")
HC = FISICA / vestibulo.CONTENEDOR
HC.write_bytes(b"\0" * 512)
PUNTO = tmpdir("prdrive-punto-")
UNIDAD = equipo.Unidad(UID, equipo.DAEMON, "Mi portátil", str(PUNTO), str(HC))


def montar() -> None:
    """Lo que hace VeraCrypt al abrirlo: aparece la raíz en su punto."""
    app = PUNTO / penwatch.APP_SUBDIR
    (app / "state").mkdir(parents=True, exist_ok=True)
    (app / "PRDRIVE").write_text(f"id={UID}\ntipo=equipo\n", encoding="utf-8")
    for py in ("runsync.py", "sync.py"):
        (app / py).write_text("# de mentira\n", encoding="utf-8")
    (app / "sync_config.toml").write_text(
        '[defaults]\nremote = "nas"\n\n[[pair]]\nname = "notas"\nlocal = "notas"\n'
        'remote_path = "/R/notas"\n', encoding="utf-8")


def desmontar() -> None:
    for hijo in PUNTO.iterdir():
        shutil.rmtree(hijo) if hijo.is_dir() else hijo.unlink()


def veracrypts() -> list:
    return [p for p in F.LANZADOS if p.args and p.args[0] == VC]


equipo.guardar_ajustes(equipo.Ajustes().con_unidad(UNIDAD))
c("la unidad sabe que es cifrada, y sin letra en Linux",
  (equipo.leer_ajustes().unidades[UID].cifrada, UNIDAD.letra), (True, ""))

# --- al iniciar sesión --------------------------------------------------------------
ag = F.nuevo()
F.vueltas(ag, 1)
c("antes de recorrer lo bastante, no pide nada", veracrypts(), [])
F.vueltas(ag, 1)
abrir = veracrypts()
c("al iniciar sesión pide abrirla, una vez", len(abrir), 1)
c("  con el contenedor y el punto de montaje fijo, y sin contraseña",
  abrir[0].args, [VC, str(HC), str(PUNTO)])
c("  lanzada suelta, fuera de la raíz", abrir[0].kwargs.get("cwd"), str(equipo.DIR))
F.vueltas(ag, 10)
c("si se cancela (no aparece), no se vuelve a pedir", len(veracrypts()), 1)
c("cerrada no es «no la encuentro»: ningún aviso", F.AVISOS, [])
c("  el estado la da por bloqueada", ag.resumen()["bloqueadas"], ["Mi portátil"])
c("  y nada se lanza", F.pasadas(), [])

# --- abrir: se decide al verla ---------------------------------------------------
montar()
F.vueltas(ag, 3)
c("abierta en cuanto se ve su id: se atiende", UID in ag.conexiones, True)
c("  con su servicio", F.lock(PUNTO).get("agente"), True)
c("  y una pasada", len(F.pasadas(PUNTO)), 1)
c("  ya no sale como bloqueada", ag.resumen()["bloqueadas"], [])
equipo.pedir({"pide": equipo.PIDE_DESBLOQUEAR})
F.vueltas(ag, 1)
c("desbloquear algo abierto no lanza nada", len(veracrypts()), 1)

# --- bloquear ---------------------------------------------------------------------
equipo.pedir({"pide": equipo.PIDE_BLOQUEAR, "id": UID})
F.vueltas(ag, 2)
c("bloquear espera a la pareja en curso", len(veracrypts()), 1)
F.acabar(F.pasadas(PUNTO)[0], rc=0)
F.vueltas(ag, 1)
cerrar = veracrypts()[1:]
c("acabada, desmonta sin --non-interactive: VeraCrypt pregunta si forzar",
  [p.args for p in cerrar], [[VC, "-d", str(HC)]])
c("  soltando antes el lock", (PUNTO / penwatch.DAEMON_LOCK_REL).exists(), False)
F.pasar(60)
F.vueltas(ag, 3)
c("  mientras sigue montada no la da por bloqueada, ni lanza pasadas",
  (UID in ag.bloqueos, len(F.pasadas(PUNTO))), (True, 1))
desmontar()
F.vueltas(ag, 2)
c("bloqueada cuando el volumen se ha ido de verdad",
  (UID in ag.bloqueos, UID in ag.conexiones), (False, False))
c("  el diario lo dice", any("bloqueada" in d for d in F.DIARIO), True)
c("  y el estado", ag.resumen()["bloqueadas"], ["Mi portátil"])

# --- desbloquear a mano, y «No» a forzar ---------------------------------------------
equipo.pedir({"pide": equipo.PIDE_DESBLOQUEAR, "id": UID})
F.vueltas(ag, 1)
c("desbloquear a mano vuelve a lanzar VeraCrypt", len(veracrypts()), 3)
montar()
F.vueltas(ag, 3)
F.acabar(F.pasadas(PUNTO)[-1], rc=0)
equipo.pedir({"pide": equipo.PIDE_BLOQUEAR})
F.vueltas(ag, 1)
c("bloquear sin id: la única raíz cifrada", len(veracrypts()), 4)
veracrypts()[-1].rc = 0             # VeraCrypt sale: se le dijo «No» a forzar
F.AVISOS.clear()
F.vueltas(ag, 4)
c("si sigue montada tras salir VeraCrypt, se dice",
  [t for t, _ in F.AVISOS], ["Mi portátil: sigue abierta"])
c("  y se sigue atendiendo", (UID in ag.bloqueos, F.lock(PUNTO).get("agente")),
  (False, True))

# --- bloquear con su ventana abierta --------------------------------------------------
F.ventana_abierta(PUNTO)
F.AVISOS.clear()
antes = len(veracrypts())
equipo.pedir({"pide": equipo.PIDE_BLOQUEAR})
F.vueltas(ag, 2)
c("con su ventana abierta, espera a que se cierre", len(veracrypts()), antes)
F.pasar(agente.ESPERA_VENTANA)
F.vueltas(ag, 1)
c("  y si no se cierra, lo dice y no bloquea",
  ([t for t, _ in F.AVISOS], len(veracrypts())), (["Mi portátil: no la bloqueo"], antes))
(PUNTO / penwatch.UI_LOCK_REL).unlink()

# --- el fantasma ------------------------------------------------------------------
RETENIDO[0] = False
F.AVISOS.clear()
F.vueltas(ag, 3)
c("su id con el contenedor libre es un fantasma: no se atiende",
  UID in ag.conexiones, False)
c("  se dice una vez, con la salida", [t for t, _ in F.AVISOS],
  ["Mi portátil: el volumen no responde"])
c("  y el estado lo cuenta", ag.resumen()["fantasmas"], [str(PUNTO)])
antes = len(veracrypts())
equipo.pedir({"pide": equipo.PIDE_BLOQUEAR})
F.vueltas(ag, 1)
c("  bloquear un fantasma sí lanza el desmontaje", len(veracrypts()), antes + 1)
desmontar()
RETENIDO[0] = None
F.vueltas(ag, 2)
c("  y queda bloqueada", (UID in ag.bloqueos, ag.resumen()["fantasmas"]), (False, []))

# --- un punto de montaje con cosas no se tapa ---------------------------------------
(PUNTO / "suelto.txt").write_text("x", encoding="utf-8")
F.AVISOS.clear()
antes = len(veracrypts())
equipo.pedir({"pide": equipo.PIDE_DESBLOQUEAR})
F.vueltas(ag, 1)
c("con cosas en el punto de montaje no monta encima",
  (len(veracrypts()), [t for t, _ in F.AVISOS]), (antes, ["Mi portátil: no la desbloqueo"]))
c("  y dice por qué", "quedarían tapadas" in F.AVISOS[0][1], True)
(PUNTO / "suelto.txt").unlink()

# --- el contenedor, desaparecido ---------------------------------------------------
HC.rename(HC.with_suffix(".aparte"))
F.AVISOS.clear()
F.vueltas(ag, 4)
c("sin su contenedor, se avisa una vez", [t for t, _ in F.AVISOS],
  ["Mi portátil: no encuentro su contenedor"])
c("  el estado lo cuenta", ag.resumen()["ausentes"], [str(HC)])
HC.with_suffix(".aparte").rename(HC)
F.vueltas(ag, 1)
c("  y vuelve", ag.resumen()["ausentes"], [])

# --- pedir_al_iniciar ----------------------------------------------------------------
equipo.pedir({"pide": equipo.PIDE_AJUSTE, "clave": "pedir_al_iniciar", "valor": False})
F.vueltas(ag, 1)
c("el ajuste lo escribe el agente", equipo.leer_ajustes().pedir_al_iniciar, False)
antes = len(veracrypts())
otro = F.nuevo()
F.vueltas(otro, 5)
c("desactivado, al arrancar no pide nada", len(veracrypts()), antes)
c("  y sale bloqueada", otro.resumen()["bloqueadas"], ["Mi portátil"])
c("ajuste por la línea de órdenes: un sí/no que no lo es se rechaza",
  agente.main(["ajuste", "pedir_al_iniciar", "talvez"]), 2)
c("  «sí» vale", agente.valor_ajuste("pedir_al_iniciar", "Sí"), True)

# --- añadir_raiz con contenedor ---------------------------------------------------
OTRA = "d" * 32
equipo.pedir({"pide": equipo.PIDE_RAIZ, "id": OTRA, "ruta": "/x/P", "nombre": "Otra",
              "contenedor": "/x/PRDRIVE-cifrado/PRDRIVE.hc"})
F.vueltas(otro, 1)
u = equipo.leer_ajustes().unidades[OTRA]
c("añadir_raiz guarda su contenedor", (u.cifrada, u.contenedor),
  (True, "/x/PRDRIVE-cifrado/PRDRIVE.hc"))
c("  y no pide su contraseña: la dejó abierta el asistente", OTRA in otro.pedidas, True)
equipo.guardar_ajustes(equipo.Ajustes().con_unidad(UNIDAD))

# --- raiz_fisica por las raíces extra ----------------------------------------------
(FISICA / vestibulo.MARCA).write_text(f"id={UID}\n", encoding="utf-8")
c("raiz_fisica() encuentra la carpeta del contenedor", vestibulo.raiz_fisica(UID), FISICA)
c("  que es una de las raíces extra", vestibulo.carpetas_de_contenedor(), [str(FISICA)])

# --- las órdenes de Windows ----------------------------------------------------------
penwatch.IS_WIN, agente.IS_WIN = True, True
try:
    win = equipo.Unidad(UID, equipo.DAEMON, "P", "P:\\", r"C:\u\PRDRIVE-cifrado\PRDRIVE.hc")
    c("en Windows la letra sale de la ruta", win.letra, "P")
    orden = penwatch.veracrypt_command(None, Path(win.contenedor), win.letra)
    c("abrir: /letter fija, /m rm, sin /password",
      ("/letter" in orden and orden[orden.index("/letter") + 1] == "P",
       ["/mountoption", "rm"] == orden[orden.index("rm") - 1:orden.index("rm") + 1],
       any("password" in a.lower() for a in orden)), (True, True, False))
    c("cerrar: /dismount de su letra, sin /silent",
      agente.orden_bloquear(win), [VC, "/dismount", "P", "/quit"])
    penwatch.installed_veracrypt = lambda: None
    c("sin VeraCrypt instalado, ninguna orden (nunca el que viaja)",
      (penwatch.veracrypt_command(None, Path(win.contenedor), "P"),
       agente.orden_bloquear(win)), (None, None))
finally:
    penwatch.IS_WIN, agente.IS_WIN = False, False
    penwatch.installed_veracrypt = lambda: VC

# --- abrir con la raíz cerrada -------------------------------------------------------
F.LANZADOS.clear()
c("abrir con la raíz cerrada y sin agente: no hay quien la desbloquee",
  agente.main(["abrir"]), 1)
store.write_json(equipo.lock_json(), {"pid": F.os.getpid(), "host": equipo.HOST})
agente.ESPERA_ABRIR = 0
equipo.recoger()
c("con el agente vivo, le pide desbloquearla (y espera a verla)",
  (agente.main(["abrir"]), [p["pide"] for p in equipo.recoger()]),
  (1, [equipo.PIDE_DESBLOQUEAR]))
c("  sin lanzar la ventana de una raíz cerrada", F.LANZADOS, [])

sys.exit(c.report())
