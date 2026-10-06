#!/usr/bin/env python3
"""El agente y el llavero de una raíz que atiende (fase 3 del llavero).

Con el reloj, los procesos y la foto de mentira de `_agente_falso.py`, y un
KeePassXC que está abierto o no según diga el test (`agente.keepassxc_abierto`).
Lo que se sujeta:
- El planificador: una pareja con su propio intervalo manda sobre el de su
  raíz, también para vigilarla, y en una raíz `sync` solo esa se recorre.
- Con KeePassXC abierto, el llavero se trae cada 5 min; cerrado, manda el
  intervalo de la raíz.
- Al abrirse y al cerrarse, una pasada del llavero enseguida; si ya hay una en
  marcha, el cambio espera a que acabe.
- En una raíz en modo `sync`, el llavero solo pasa mientras KeePassXC está
  abierto, y al abrirlo y cerrarlo.
- Se mira cada pocos segundos y solo en las raíces que sirve el agente y
  llevan llavero.
- La bandeja: «Abrir llavero» en el desplegable de un dispositivo con llavero,
  solo donde se abre (Windows), y la petición lanza su `runsync.py --llavero`
  con las guardas de su ventana.
- Un conflicto del llavero (lo que su `sync.py` apunta en `conflicts.json`):
  un aviso por copia nueva y conexión, y una línea de aviso en la bandeja que
  lleva a combinarlo.
- Las claves del navegador de una unidad que se fue sin expulsar se quitan al
  irse y al arrancar el agente (`agente.limpiar_navegador`, de mentira).
- «Bloquear» una raíz cifrada del equipo con llavero lo cierra antes (su
  `runsync.py --cerrar-llavero`), y si KeePassXC no se cierra no se bloquea.
  Es lo último: se hace Linux, con el VeraCrypt de mentira de
  `test_agente_veracrypt.py`.
"""

import math
from dataclasses import replace
import shutil
import sys
from pathlib import Path

from _harness import Checks, tmpdir

import _agente_falso as F
import agente
import penwatch
from common import equipo, llavero, moderacion, model, store, vestibulo
from common import planificador as pl
from ui import bandeja, icons

c = Checks("agente: el llavero de una raíz")
REAL_LIMPIAR = agente.limpiar_navegador
REAL_HUERFANO = agente.cerrar_keepassxc_huerfano
F.preparar()

TICK = agente.TICK
CAMBIOS = pl.PoliticaCambios()
DAEMON = "[daemon]\ninterval_minutes = 600\n"
"""Un intervalo que nunca llega: lo que lance una pasada es el llavero."""
LLAVERO = '\n[keychain]\nbase = "personal.kdbx"\n'

# ---------------------------------------------------------------------------
# 1. El planificador: el intervalo de una pareja
# ---------------------------------------------------------------------------
corto = pl.Pareja("keychain", "nas", vigila=True, intervalo=300.0)
largo = pl.Pareja("docs", "nas", vigila=True)
raiz = pl.Raiz("r", (corto, largo), 3600.0)
c("una pareja con su intervalo manda sobre el de la raíz",
  (pl.intervalo_de(raiz, corto), pl.intervalo_de(raiz, largo)), (300.0, 3600.0))
marcas = {("r", "keychain"): pl.Marca(1000.0), ("r", "docs"): pl.Marca(1000.0)}
d = pl.decidir([raiz], marcas, pl.Entorno(), 1301.0)
c("  y le toca antes", (d.tarea.pareja if d.tarea else None), "keychain")
sync = pl.Raiz("s", (corto, largo), math.inf)
c("en una raíz sync solo se recorre la que trae su intervalo",
  pl.a_recorrer([sync], {}, 0.0), [("s", "keychain")])
c("  sin él, ninguna", pl.a_recorrer([pl.Raiz("s", (largo,), math.inf)], {}, 0.0), [])

# En una red de uso medido el llavero sigue: pesa nada y es lo que más importa
# tener al día. Lo demás espera, como siempre.
llave = pl.Pareja("keychain", "nas", vigila=True, llavero=True)
docs = pl.Pareja("docs", "fotos", vigila=True)
mixta = pl.Raiz("r", (llave, docs), 3600.0)
medida = pl.Entorno(red_medida=True)
d = pl.decidir([mixta], {}, medida, 1000.0)
c("red de uso medido: la pasada del llavero sale", d.tarea and d.tarea.pareja, "keychain")
c("  sin dejar de decir que lo demás espera (el diario no va y viene)", d.retenido,
  "red de uso medido")
hecha = {("r", "keychain"): pl.Marca(1000.0)}
d = pl.decidir([mixta], hecha, medida, 1001.0)
c("  la de docs no, y se dice por qué", (d.tarea, d.retenido), (None, "red de uso medido"))
c("  y se vuelve a mirar cuando toque el llavero, no más tarde",
  d.mirar_en <= pl.Politica().mirar_maximo, True)
d = pl.decidir([mixta], {}, pl.Entorno(red_medida=True, con_bateria=True, bateria=5),
               1000.0)
c("con la batería baja, ni el llavero", (d.tarea, d.retenido),
  (None, "batería por debajo del 20 %"))
d = pl.decidir([mixta], {}, pl.Entorno(red_medida=True, ahorro_energia=True), 1000.0)
c("con el ahorro de energía, tampoco", d.tarea, None)
sin_red = pl.Entorno(red_medida=True, sin_conexion={("r", "nas"): 900.0,
                                                    ("r", "fotos"): 900.0})
d = pl.decidir([mixta], {}, sin_red, 1000.0)
c("red medida con su remoto sin conexión: se sondea el del llavero",
  (d.tarea.tipo, d.tarea.remoto) if d.tarea else None, (pl.SONDA, "nas"))
d = pl.decidir([mixta], {}, replace(sin_red, sin_conexion={("r", "fotos"): 900.0}), 1000.0)
c("  y no el de las demás", d.tarea.pareja if d.tarea else None, "keychain")
c("los recorridos, igual: solo el llavero",
  pl.a_recorrer([mixta], {}, 0.0, motivo="red de uso medido"), [("r", "keychain")])
c("  y nada con otro motivo", pl.a_recorrer([mixta], {}, 0.0, motivo="en pausa"), [])


# ---------------------------------------------------------------------------
# 2. Una raíz en modo daemon
# ---------------------------------------------------------------------------
ABIERTO = [False]
MIRADAS: list[Path] = []


def abierto(raiz) -> bool:
    """KeePassXC de mentira: abierto según `ABIERTO`, y apunta dónde se miró."""
    MIRADAS.append(Path(raiz))
    return ABIERTO[0]


agente.keepassxc_abierto = abierto
FIRMA = [1]
agente.huella_local = lambda ruta, tope, ignorar: pl.Huella(1, FIRMA[0])


def poner(uid: str, modo: str = equipo.DAEMON, con_llavero: bool = True) -> Path:
    """Una unidad con `docs` y, si se dice, llavero, en la lista con ese modo."""
    raiz = F.unidad(uid, parejas=("docs",), daemon=DAEMON)
    if con_llavero:
        config = raiz / ".prdrive" / "sync_config.toml"
        config.write_text(config.read_text(encoding="utf-8") + LLAVERO, encoding="utf-8")
    equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(equipo.Unidad(uid, modo)))
    return raiz


def del_llavero(raiz: Path) -> list:
    """Las pasadas del llavero lanzadas en esa raíz."""
    return [p for p in F.pasadas(raiz) if p.args[-1] == model.LLAVERO]


def terminar(ag, raiz: Path | None = None) -> None:
    """Termina bien las pasadas en marcha, de la raíz que sea, y las que salgan detrás."""
    while ag.pasada is not None:
        F.acabar(ag.pasada.proc, 0, "OK\n")
        F.vueltas(ag, 1)


def hasta(ag, raiz: Path, limite: float) -> float | None:
    """Da vueltas hasta que se lanza una pasada del llavero.

    Returns:
        Los segundos hasta el lanzamiento, o `None` si no se lanzó en `limite`.
    """
    n, desde = len(del_llavero(raiz)), F.reloj()
    for _ in range(int(limite / TICK)):
        F.vueltas(ag, 1)
        if len(del_llavero(raiz)) > n:
            return F.reloj() - TICK - desde
    return None


UID = "a" * 32
RAIZ = poner(UID)
F.RAICES[:] = [RAIZ]
ag = F.nuevo()
F.vueltas(ag, 2)
terminar(ag, RAIZ)
c("al conectarla, las dos pasadas de siempre, la del llavero la última",
  [p.args[-1] for p in F.pasadas(RAIZ)], ["docs", model.LLAVERO])
c("  el agente la sirve con el llavero entre sus parejas: el vigilante sobra",
  model.LLAVERO in F.lock(RAIZ).get("pairs", []), True)

MIRADAS.clear()
F.vueltas(ag, int(60 / TICK))
c("se mira si KeePassXC está abierto cada pocos segundos, no en cada vuelta",
  len(MIRADAS), int(60 / CAMBIOS.sondeo))
c("  en su raíz", set(MIRADAS), {RAIZ})
c("con KeePassXC cerrado, manda el intervalo de la raíz", hasta(ag, RAIZ, 400), None)

ABIERTO[0] = True
espera = hasta(ag, RAIZ, 30)
c("al abrirse KeePassXC, una pasada del llavero enseguida",
  espera is not None and espera <= CAMBIOS.sondeo + TICK, True)
c("  y el diario lo dice", any("KeePassXC abierto" in m for m in F.DIARIO), True)
terminar(ag, RAIZ)
fin = F.reloj()
espera = hasta(ag, RAIZ, 400)
c("abierto, lo de otro dispositivo se trae cada 5 min",
  espera is not None and abs(F.reloj() - TICK - fin - llavero.REMOTO_ABIERTO) <= 2 * TICK,
  True)
c("  y solo el llavero", [p.args[-1] for p in F.pasadas(RAIZ)][-1], model.LLAVERO)
terminar(ag, RAIZ)

ABIERTO[0] = False
espera = hasta(ag, RAIZ, 30)
c("al cerrarse, una pasada enseguida: sube lo que se guardó justo antes",
  espera is not None and espera <= CAMBIOS.sondeo + TICK, True)
c("  y el diario lo dice", any("KeePassXC cerrado" in m for m in F.DIARIO), True)
terminar(ag, RAIZ)
c("  después, otra vez el intervalo de la raíz", hasta(ag, RAIZ, 400), None)

# Con una pasada del llavero en marcha, el cambio espera a que acabe.
ag.marcas[(UID, model.LLAVERO)] = pl.Marca(None)
hasta(ag, RAIZ, 10)
c("(una pasada del llavero en marcha)", ag.pasada.tarea.pareja, model.LLAVERO)
ABIERTO[0] = True
F.vueltas(ag, int(20 / TICK))
c("abrirse durante una pasada del llavero no la cuenta todavía", UID in ag.keepassxc, False)
terminar(ag, RAIZ)
espera = hasta(ag, RAIZ, 30)
c("  acabada, se ve abierto y hay otra pasada: la de antes pudo empezar antes",
  (UID in ag.keepassxc, espera is not None), (True, True))
terminar(ag, RAIZ)

# En una red de uso medido el llavero sigue y lo demás espera.
moderacion.red_medida = lambda: True
ag.entorno_leido = -math.inf
ag.marcas[(UID, "docs")] = pl.Marca(None)
ag.marcas[(UID, model.LLAVERO)] = pl.Marca(None)
antes, dicho = len(F.pasadas(RAIZ)), len(F.DIARIO)
F.vueltas(ag, 3)
c("red de uso medido: sale la pasada del llavero y no la de docs",
  [p.args[-1] for p in F.pasadas(RAIZ)][antes:], [model.LLAVERO])
terminar(ag, RAIZ)
F.vueltas(ag, int(60 / TICK))
c("  docs sigue esperando", [p.args[-1] for p in F.pasadas(RAIZ)][antes:], [model.LLAVERO])
c("  y el diario lo dice una vez, sin ir y venir con cada pasada del llavero",
  [m for m in F.DIARIO[dicho:] if m.startswith(("no se lanza", "se vuelve"))],
  ["no se lanza nada salvo el llavero: red de uso medido"])
moderacion.red_medida = lambda: False
ag.entorno_leido = -math.inf
F.vueltas(ag, 3)
c("al volver la red normal, la de docs", [p.args[-1] for p in F.pasadas(RAIZ)][-1], "docs")
terminar(ag, RAIZ)

# Una raíz que el agente deja de servir no cuenta como «KeePassXC cerrado».
F.ventana_abierta(RAIZ)
dicho = len(F.DIARIO)
F.vueltas(ag, int(20 / TICK))
c("con su ventana abierta no se sirve, ni se mira KeePassXC",
  (UID in ag.keepassxc, any("KeePassXC cerrado" in m for m in F.DIARIO[dicho:])),
  (False, False))
(RAIZ / ".prdrive" / "state" / "ui.lock.json").unlink()
ABIERTO[0] = False

# ---------------------------------------------------------------------------
# 3. Una raíz en modo sync
# ---------------------------------------------------------------------------
F.RAICES[:] = []
F.vueltas(ag, 3)
UID_S = "b" * 32
SYNC = poner(UID_S, modo=equipo.SYNC)
F.RAICES[:] = [SYNC]
ag = F.nuevo()                           # lee la lista con la unidad nueva
F.vueltas(ag, 2)
terminar(ag, SYNC)
c("modo sync: una pasada por conexión, también del llavero",
  [p.args[-1] for p in F.pasadas(SYNC)], ["docs", model.LLAVERO])
c("  y con KeePassXC cerrado, nada más", hasta(ag, SYNC, 700), None)
c("  ni se recorre su carpeta", (UID_S, model.LLAVERO) in ag.vigiladas
  and ag.vigiladas[(UID_S, model.LLAVERO)].huella is not None, False)
ABIERTO[0] = True
c("al abrirse KeePassXC, el llavero pasa", hasta(ag, SYNC, 30) is not None, True)
terminar(ag, SYNC)
c("  y se trae cada 5 min mientras está abierto",
  hasta(ag, SYNC, llavero.REMOTO_ABIERTO + 20) is not None, True)
terminar(ag, SYNC)
F.vueltas(ag, 3)
FIRMA[0] += 1                            # un guardado en KeePassXC
espera = hasta(ag, SYNC, CAMBIOS.separacion + CAMBIOS.calma)
c("  y su carpeta se vigila: un guardado se sube, tras la calma",
  (espera is not None, ag.pasada is not None and ag.pasada.tarea.por_cambios), (True, True))
terminar(ag, SYNC)
c("  solo el llavero: docs no ha vuelto a pasar",
  [p.args[-1] for p in F.pasadas(SYNC)].count("docs"), 1)
ABIERTO[0] = False
c("al cerrarse, una última pasada", hasta(ag, SYNC, 30) is not None, True)
terminar(ag, SYNC)
c("  y vuelve a ser una por conexión", hasta(ag, SYNC, 700), None)

# ---------------------------------------------------------------------------
# 4. Sin llavero no se mira KeePassXC
# ---------------------------------------------------------------------------
F.RAICES[:] = []
F.vueltas(ag, 3)
UID_N = "c" * 32
SIN = poner(UID_N, con_llavero=False)
F.RAICES[:] = [SIN]
ag = F.nuevo()
F.vueltas(ag, 2)
terminar(ag, SIN)
MIRADAS.clear()
F.vueltas(ag, int(60 / TICK))
c("en una raíz sin llavero no se mira si KeePassXC está abierto", MIRADAS, [])


# ---------------------------------------------------------------------------
# 5. La bandeja: «Abrir llavero»
# ---------------------------------------------------------------------------
def dentro(resumen: dict, rotulo: str) -> list:
    """Las entradas del desplegable de ese dispositivo."""
    vista = bandeja.vista(resumen)
    return list(next(e for e in vista.menu if e.texto == rotulo).hijos)


def fila(resumen: dict, uid: str) -> dict:
    """La fila de ese dispositivo en el resumen."""
    return next(u for u in resumen["unidades"] if u["id"] == uid)


F.RAICES[:] = []
F.vueltas(ag, 3)
UID_B = "e" * 32
CON = poner(UID_B)
F.RAICES[:] = [CON, SIN]
ag = F.nuevo()
F.vueltas(ag, 2)
terminar(ag, CON)
resumen = ag.resumen()
c("el resumen dice qué dispositivo lleva llavero",
  (fila(resumen, UID_B)["llavero"], fila(resumen, UID_N)["llavero"]), (True, False))
c("  si su KeePassXC está abierto", fila(resumen, UID_B)["llavero_abierto"], False)
c("  y si este equipo lo abre: Windows y Linux",
  resumen["abre_llavero"], agente.IS_WIN or sys.platform.startswith("linux"))
en_windows = {**resumen, "abre_llavero": True}
nombre = fila(resumen, UID_B)["nombre"]
c("«Abrir llavero» va en su desplegable, tras el explorador",
  [e.texto for e in dentro(en_windows, nombre)][:4],
  ["Configurar", "Abrir en explorador", "Abrir llavero", "Sincronizar ahora"])
entrada = next(e for e in dentro(en_windows, nombre) if e.texto == "Abrir llavero")
c("  pide su llavero, con la llave por icono",
  (entrada.pide, entrada.icono, entrada.activa),
  (({"pide": equipo.PIDE_LLAVERO, "id": UID_B},), bandeja.I_LLAVERO, True))
c("  en uno sin llavero, no",
  "Abrir llavero" in [e.texto for e in dentro(en_windows, fila(resumen, UID_N)["nombre"])],
  False)
c("  ni donde no se abre", "Abrir llavero" in [
    e.texto for e in dentro({**resumen, "abre_llavero": False}, nombre)], False)
raiz_equipo = {**en_windows, "unidades": [{**fila(resumen, UID_B), "del_equipo": True}],
               "equipo": [{"id": UID_B, "nombre": "PRDRIVE", "ruta": str(CON),
                           "cifrada": True, "estado": bandeja.ABIERTA}]}
c("en una raíz del equipo abierta, también",
  "Abrir llavero" in [e.texto for e in dentro(raiz_equipo, "PRDRIVE")], True)
bloqueada = {**raiz_equipo, "equipo": [{**raiz_equipo["equipo"][0],
                                        "estado": bandeja.BLOQUEADA}]}
c("  bloqueada no: no se sabe si lo lleva",
  "Abrir llavero" in [e.texto for e in dentro(bloqueada, "PRDRIVE (bloqueada)")], False)

# La petición
F.LANZADOS.clear()
ag.pedir({"pide": equipo.PIDE_LLAVERO, "id": UID_B})
F.vueltas(ag, 1)
lanzado = [p for p in F.LANZADOS if p.args[-1] == "--llavero"]
c("pedirlo lanza su runsync.py --llavero, con el Python de las ventanas",
  [p.args for p in lanzado],
  [[agente.python(ventana=True), str(CON / ".prdrive" / "runsync.py"), "--llavero"]])
c("  desde fuera de la raíz", lanzado and str(lanzado[0].kwargs.get("cwd")), str(equipo.DIR))
c("  y el diario lo dice", any("abriendo su llavero" in m for m in F.DIARIO), True)
F.LANZADOS.clear()
ag.pedir({"pide": equipo.PIDE_LLAVERO, "id": UID_N})
F.vueltas(ag, 1)
c("en uno sin llavero no se lanza nada", F.LANZADOS, [])
F.PANTALLA[0] = False
ag.pedir({"pide": equipo.PIDE_LLAVERO, "id": UID_B})
F.vueltas(ag, 1)
F.PANTALLA[0] = True
c("sin entorno gráfico, tampoco", F.LANZADOS, [])
FUERA = "f" * 32
extrano = F.unidad(FUERA, parejas=("docs",), daemon=DAEMON)
config = extrano / ".prdrive" / "sync_config.toml"
config.write_text(config.read_text(encoding="utf-8") + LLAVERO, encoding="utf-8")
F.RAICES[:] = [CON, SIN, extrano]
F.vueltas(ag, 3)
F.LANZADOS.clear()
ag.pedir({"pide": equipo.PIDE_LLAVERO, "id": FUERA})
F.vueltas(ag, 1)
c("de una unidad que no está en la lista no se ejecuta nada",
  [p for p in F.LANZADOS if "--llavero" in p.args], [])
c("  ni se lee si lleva llavero", fila(ag.resumen(), FUERA)["llavero"], False)

# Activarlo desde su ventana se ve sin desconectarla.
config = SIN / ".prdrive" / "sync_config.toml"
config.write_text(config.read_text(encoding="utf-8") + LLAVERO, encoding="utf-8")
c("activarlo no se relee en cada vuelta", fila(ag.resumen(), UID_N)["llavero"], False)
F.pasar(agente.MIRAR_EMBLEMA)
c("  pasado MIRAR_EMBLEMA, sí", fila(ag.resumen(), UID_N)["llavero"], True)


# ---------------------------------------------------------------------------
# 6. Un conflicto del llavero
# ---------------------------------------------------------------------------
COPIA = ".keychain/personal.conflicto-remoto1.kdbx"


def conflictos(raiz: Path, copias: list) -> None:
    """Escribe lo que apuntaría su sync.py tras una pasada (`conflicts.actualizar_pareja()`)."""
    store.write_json(raiz / ".prdrive" / "state" / "conflicts.json",
                     {"cuando": "x", "parejas": {"docs": [], model.LLAVERO: copias}})


def pasada_del_llavero(ag, raiz: Path) -> None:
    """Hace una pasada del llavero de esa raíz, entera."""
    terminar(ag)
    ag.marcas[(UID_B, model.LLAVERO)] = pl.Marca(None)
    hasta(ag, raiz, 10)
    terminar(ag)


def del_llavero_avisos() -> list:
    """Los avisos de un conflicto del llavero."""
    return [a for a in F.AVISOS if "el llavero tiene dos versiones" in a[0]]


F.AVISOS.clear()
conflictos(CON, [COPIA])
pasada_del_llavero(ag, CON)
c("tras una pasada que deja una copia de la base, un aviso",
  [t for t, _ in del_llavero_avisos()], [f"{nombre}: el llavero tiene dos versiones"])
c("  que dice que no se ha perdido nada y cómo combinarlas",
  del_llavero_avisos()[0][1],
  agente.LLAVERO_EN_CONFLICTO + (agente.COMBINAR_AQUI if agente.ABRE_LLAVERO
                                 else agente.COMBINAR_A_MANO))
resumen = ag.resumen()
c("  el resumen lo cuenta", fila(resumen, UID_B)["llavero_conflicto"], 1)
en_windows = {**resumen, "abre_llavero": True}
linea = next(e for e in bandeja.vista(en_windows).menu if "dos versiones" in e.texto)
c("  la bandeja lo dice arriba, y lleva a combinarlo",
  (linea.texto, linea.pide),
  (f"{nombre}: el llavero tiene dos versiones · Combinar…",
   ({"pide": equipo.PIDE_LLAVERO, "id": UID_B},)))
c("  con el icono de aviso", bandeja.vista(en_windows).icono, icons.AVISO)
lejos = next(e for e in bandeja.vista({**resumen, "abre_llavero": False}).menu
             if "dos versiones" in e.texto)
c("  donde no se abre, a su ventana («Reparación»)",
  (lejos.texto.endswith("· Abrir…"), lejos.pide[0]["pide"]), (True, equipo.PIDE_ABRIR))
pasada_del_llavero(ag, CON)
c("la misma copia no se vuelve a avisar", len(del_llavero_avisos()), 1)
conflictos(CON, [])                      # «Combinar», desde su ventana
F.pasar(agente.MIRAR_EMBLEMA)
F.vueltas(ag, 1)
c("combinadas, se ve sin pasada del agente", fila(ag.resumen(), UID_B)["llavero_conflicto"], 0)
conflictos(CON, [COPIA])
pasada_del_llavero(ag, CON)
c("  y un conflicto nuevo con el mismo nombre se vuelve a avisar", len(del_llavero_avisos()), 2)
conflictos(extrano, [COPIA])
F.pasar(agente.MIRAR_EMBLEMA)
F.vueltas(ag, 1)
c("de una unidad que no está en la lista no se lee nada",
  (fila(ag.resumen(), FUERA)["llavero_conflicto"], len(del_llavero_avisos())), (0, 2))


# ---------------------------------------------------------------------------
# 7. Las claves del navegador de una unidad quitada sin expulsar
# ---------------------------------------------------------------------------
real_limpiar = agente.limpiar_navegador
if not agente.IS_WIN:
    c("en Linux, sin manifiestos de prdrive, no toca nada", REAL_LIMPIAR(), (0, []))
LIMPIEZAS: list[float] = []
QUITADAS = [1]


def limpiar():
    """`limpiar_navegador()` de mentira: apunta cuándo, y dice que quitó `QUITADAS`."""
    LIMPIEZAS.append(F.reloj())
    return QUITADAS[0], []


agente.limpiar_navegador = limpiar
try:
    terminar(ag)
    ag = F.nuevo()
    dicho = len(F.DIARIO)
    F.vueltas(ag, 1)
    c("al arrancar, el agente quita las que dejó una unidad que se fue mientras no estaba",
      (len(LIMPIEZAS), any("al arrancar: el navegador ya no busca" in m
                           for m in F.DIARIO[dicho:])), (1, True))
    F.vueltas(ag, 3)
    terminar(ag)
    c("  una vez: no en cada vuelta", len(LIMPIEZAS), 1)
    QUITADAS[0] = 0
    dicho = len(F.DIARIO)
    F.RAICES[:] = [SIN, extrano]
    F.vueltas(ag, 2)
    c("al irse una unidad, otra vez", len(LIMPIEZAS), 2)
    c("  y sin nada que quitar, no se dice nada",
      any("el navegador ya no busca" in m for m in F.DIARIO[dicho:]), False)

    def rota():
        raise OSError("acceso denegado")

    agente.limpiar_navegador = rota
    F.RAICES[:] = [extrano]
    F.vueltas(ag, 2)
    c("un fallo del registro no tumba al agente: lo dice en el diario",
      any("no he podido dejar como estaban las claves del navegador: acceso denegado" in m
          for m in F.DIARIO), True)
finally:
    agente.limpiar_navegador = real_limpiar

# En Linux, KeePassXC corre extraído en el equipo y no muere con la unidad:
# el agente le pide que se cierre cuando su raíz se va.
real_huerfano = agente.cerrar_keepassxc_huerfano
HUERFANOS: list[Path] = []
agente.cerrar_keepassxc_huerfano = lambda raiz: HUERFANOS.append(raiz) or 1
try:
    terminar(ag)
    F.RAICES[:] = [CON, SIN]
    ag = F.nuevo()
    F.vueltas(ag, 2)
    terminar(ag, CON)
    dicho = len(F.DIARIO)
    F.RAICES[:] = [SIN]
    F.vueltas(ag, 2)
    c("al irse una raíz, se pide que se cierre su KeePassXC", HUERFANOS, [CON])
    c("  y se dice en el diario",
      any("se ha ido con KeePassXC abierto; le pido que se cierre" in m
          for m in F.DIARIO[dicho:]), True)

    # Tarda en salir, y mientras corre `limpiar_navegador()` no toca nada: el
    # navegador se deja como estaba cuando sale (salió con procesos de verdad).
    agente.limpiar_navegador = limpiar
    VIVO = [True]
    agente.keepassxc_huerfano_abierto = lambda raiz: VIVO[0] and raiz == CON
    LIMPIEZAS.clear()
    F.RAICES[:] = [CON, SIN]
    F.vueltas(ag, 2)
    terminar(ag, CON)
    F.RAICES[:] = [SIN]
    F.vueltas(ag, 3)
    c("  mientras siga abierto, el navegador espera", len(LIMPIEZAS), 0)
    VIVO[0] = False
    F.vueltas(ag, 3)
    c("  y cuando sale, se deja como estaba, una vez", len(LIMPIEZAS), 1)
    VIVO[0] = True
    F.RAICES[:] = [CON, SIN]
    F.vueltas(ag, 2)
    terminar(ag, CON)
    F.RAICES[:] = [SIN]
    F.vueltas(ag, 2)
    F.RAICES[:] = [CON, SIN]
    F.vueltas(ag, 2)
    VIVO[0] = False
    F.vueltas(ag, 2)
    c("  si la raíz vuelve antes, lo suyo ya no es un huérfano: no se toca",
      (len(LIMPIEZAS), ag.navegador_tras_cierre), (1, {}))
    terminar(ag, CON)
finally:
    agente.cerrar_keepassxc_huerfano = real_huerfano
    agente.limpiar_navegador = real_limpiar
    agente.keepassxc_huerfano_abierto = lambda raiz: False
reales_huerfano = (agente.IS_WIN, agente.llavero.pids_keepassxc, agente.keepassxc.pedir_cierre)
cerrados: list[int] = []
try:
    agente.llavero.pids_keepassxc = lambda app_dir: [41, 42] if Path(app_dir) == CON / ".prdrive" \
        else []
    agente.keepassxc.pedir_cierre = cerrados.append
    agente.IS_WIN = False
    c("  en Linux, se les pide a los suyos, como al cerrarlo la persona",
      (REAL_HUERFANO(CON), cerrados), (2, [41, 42]))
    agente.IS_WIN = True
    c("  en Windows no hace falta: muere con la unidad", REAL_HUERFANO(CON), 0)
finally:
    agente.IS_WIN, agente.llavero.pids_keepassxc, agente.keepassxc.pedir_cierre = reales_huerfano


# ---------------------------------------------------------------------------
# 8. Bloquear una raíz cifrada del equipo con llavero
# ---------------------------------------------------------------------------
penwatch.candidate_roots = lambda cfg: ([Path(r) for r in cfg.get("extra_roots", [])]
                                        + list(F.RAICES))
VC = "/opt/veracrypt/veracrypt"
penwatch.installed_veracrypt = lambda: VC
penwatch._con_escritorio = lambda: True
vestibulo.retenido = lambda hc: None
penwatch.IS_WIN = agente.IS_WIN = False             # se monta en una carpeta
equipo.Unidad.letra = property(lambda self: "")
UID_C = "9" * 32
HC = tmpdir("prdrive-cifrado-") / vestibulo.CONTENEDOR
HC.write_bytes(b"\0" * 512)
PUNTO = tmpdir("prdrive-punto-")


def montar() -> None:
    """Lo que hace VeraCrypt al abrirla: aparece la raíz, con llavero, en su punto."""
    app = PUNTO / penwatch.APP_SUBDIR
    (app / "state").mkdir(parents=True, exist_ok=True)
    (app / "PRDRIVE").write_text(f"id={UID_C}\ntipo=equipo\n", encoding="utf-8")
    (app / "VERSION").write_text(F.VERSION + "\n", encoding="utf-8")
    for py in ("runsync.py", "sync.py"):
        (app / py).write_text("# de mentira\n", encoding="utf-8")
    (app / "sync_config.toml").write_text(
        '[defaults]\nremote = "nas"\n\n[[pair]]\nname = "notas"\nlocal = "notas"\n'
        'remote_path = "/R/notas"\n' + LLAVERO, encoding="utf-8")


def desmontar() -> None:
    """Vacía el punto de montaje: lo que hace VeraCrypt al cerrarla."""
    for hijo in PUNTO.iterdir():
        shutil.rmtree(hijo) if hijo.is_dir() else hijo.unlink()


def veracrypts() -> list:
    """Los VeraCrypt de mentira lanzados."""
    return [p for p in F.LANZADOS if p.args and p.args[0] == VC]


def cierres() -> list:
    """Los `runsync.py --cerrar-llavero` lanzados."""
    return [p for p in F.LANZADOS if p.args[-1] == "--cerrar-llavero"]


F.RAICES[:] = []
equipo.guardar_ajustes(equipo.Ajustes().con_unidad(
    equipo.Unidad(UID_C, equipo.DAEMON, "Mi portátil", str(PUNTO), str(HC))))
montar()
ag = F.nuevo()
F.vueltas(ag, 3)
terminar(ag)
c("(la raíz cifrada, abierta y atendida, con su llavero)",
  (UID_C in ag.conexiones, fila(ag.resumen(), UID_C)["llavero"]), (True, True))
F.LANZADOS.clear()
F.AVISOS.clear()
equipo.pedir({"pide": equipo.PIDE_BLOQUEAR, "id": UID_C})
F.vueltas(ag, 2)
c("bloquearla cierra antes su llavero: su runsync.py --cerrar-llavero",
  [p.args for p in cierres()],
  [[agente.python(), str(PUNTO / ".prdrive" / "runsync.py"), "--cerrar-llavero"]])
c("  fuera de la raíz", str(cierres()[0].kwargs.get("cwd")), str(equipo.DIR))
c("  y VeraCrypt espera a que acabe", veracrypts(), [])
F.vueltas(ag, 3)
c("  mientras sigue, una sola vez", (len(cierres()), veracrypts()), (1, []))
cierres()[0].rc = 1                      # KeePassXC no se ha cerrado
F.vueltas(ag, 1)
c("si KeePassXC no se cierra, no se bloquea y se dice",
  ([t for t, _ in F.AVISOS], veracrypts(), UID_C in ag.bloqueos),
  (["Mi portátil: no la bloqueo"], [], False))
F.vueltas(ag, 2)
c("  y se sigue atendiendo", (UID_C in ag.conexiones, F.lock(PUNTO).get("agente")), (True, True))
terminar(ag)
equipo.pedir({"pide": equipo.PIDE_BLOQUEAR, "id": UID_C})
F.vueltas(ag, 2)
terminar(ag)
cierres()[-1].rc = 0
F.vueltas(ag, 1)
c("cerrado el llavero, VeraCrypt desmonta",
  [p.args for p in veracrypts()], [[VC, "-d", str(HC)]])
desmontar()
F.vueltas(ag, 2)
c("  y queda bloqueada", (UID_C in ag.bloqueos, UID_C in ag.conexiones), (False, False))
F.LANZADOS.clear()
montar()
(PUNTO / ".prdrive" / "sync_config.toml").write_text(
    '[defaults]\nremote = "nas"\n\n[[pair]]\nname = "notas"\nlocal = "notas"\n'
    'remote_path = "/R/notas"\n', encoding="utf-8")
F.vueltas(ag, 3)
terminar(ag)
equipo.pedir({"pide": equipo.PIDE_BLOQUEAR, "id": UID_C})
F.vueltas(ag, 2)
c("una raíz sin llavero se bloquea sin más", (cierres(), len(veracrypts())), ([], 1))
sys.exit(c.report())
