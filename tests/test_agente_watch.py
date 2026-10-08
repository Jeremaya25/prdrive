#!/usr/bin/env python3
"""El agente y los cambios locales de una pareja (`watch = true`, #61).

Lo que cada pieza decide ya está en `test_watch_pareja.py` (la clave, la foto
de la carpeta, las reglas del planificador). Aquí se comprueba el cableado de
`agente.py`, con un reloj de mentira y una foto de mentira (`agente.huella_local`):
- Qué se vigila: solo la pareja que lo pide, en un modo con el local de origen.
- Un cambio es UNA pasada tras la calma; una ráfaga, también una; y dos pasadas
  de la misma pareja no están más cerca que la separación.
- Lo que escribe la propia pasada no la dispara otra vez.
- La moderación (batería, red de uso medido, pausa, la pausa de la ventana de
  la raíz, su ventana abierta) retiene tanto la pasada como el recorrido.
- El recorrido va en un hilo: la vuelta no lo espera, y solo hay uno a la vez.
  La foto de una pareja cuya pasada empezó o acabó mientras se miraba, o de una
  unidad que se fue, no cuenta.
- Pasado el tope de entradas, o con la carpeta fuera de la raíz, se abandona:
  se dice una vez y el intervalo manda.
- El estado (`estado.json`, `status`) dice qué se vigila.
- El recorrido se espacia con la carpeta quieta y a batería (las secciones de
  antes miran el cableado al ritmo de siempre, `CAMBIOS`).
- Con los avisos del sistema (un motor de mentira, `AvisosFalsos`): la pareja
  no se recorre; un aviso es una pasada tras la calma; el de su propia pasada
  no cuenta; uno perdido vuelve a recorrer y se dice; sin avisos para una
  carpeta, se recorre y se dice por qué; se dejan al dejar de servir la raíz,
  al irse y antes de «Expulsar» y «Bloquear».
"""

import contextlib
import io
import math
import os
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from _harness import Checks, tmpdir

import _agente_falso as F
import agente
import penwatch
from common import avisos_carpeta as ac
from common import equipo, expulsar, huella, model, moderacion, store, vestibulo
from common import planificador as pl

c = Checks("agente: cambios locales de una pareja (watch)")
F.preparar()

TICK = agente.TICK
FABRICA = pl.PoliticaCambios()
CAMBIOS = replace(FABRICA, sondeo_quieto=FABRICA.sondeo)
"""Las reglas de fábrica sin espaciar el recorrido: aquí se mira el cableado."""

FIRMAS: dict[str, int] = {}
"""La firma de la carpeta de cada pareja, por nombre; el test la cambia a mano."""
MIRADAS: list[tuple[str, int, tuple]] = []
"""Las carpetas que el agente ha mirado: nombre, tope e ignoradas."""
DAEMON = "[daemon]\ninterval_minutes = 600\n"
"""Un intervalo que nunca llega: lo que lance una pasada son los cambios."""
VIGILA = "watch = true\n"


def foto(ruta, tope, ignorar):
    """La foto de mentira: una firma que decide el test."""
    MIRADAS.append((Path(ruta).name, tope, tuple(ignorar)))
    return pl.Huella(10, FIRMAS[Path(ruta).name])


def nuevo() -> "agente.Agente":
    """Un agente con el reloj de mentira y las reglas de `CAMBIOS`."""
    ag = F.nuevo()
    ag.cambios = CAMBIOS
    return ag


def mirada(nombre: str = "docs") -> int:
    """Cuántas veces se ha mirado la carpeta de esa pareja."""
    return sum(1 for m in MIRADAS if m[0] == nombre)


def terminar(ag, raiz) -> None:
    """Termina bien las pasadas que haya en marcha, y las que salgan detrás."""
    while ag.pasada is not None:
        F.acabar(F.pasadas(raiz)[-1], 0, "OK\n")
        F.vueltas(ag, 1)


def quieto(ag, segundos: float) -> None:
    """Da vueltas durante esos segundos."""
    F.vueltas(ag, int(segundos / TICK))


def poner(uid: str, **kwargs) -> Path:
    """Pone una unidad con una pareja `docs` que vigila (u otras) y la deja en la lista."""
    raiz = F.unidad(uid, daemon=DAEMON, **kwargs)
    equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(equipo.Unidad(uid, equipo.DAEMON)))
    return raiz


# ---------------------------------------------------------------------------
# 1. Qué se vigila
# ---------------------------------------------------------------------------
agente.huella_local = foto
UID = "d" * 32
RAIZ = poner(UID, parejas=("docs", "fotos", "bajada"), nombre="PRDRIVE-W",
             extra={"docs": VIGILA, "bajada": 'mode = "down"\n' + VIGILA})
BUZON = RAIZ / ".prdrive" / "state" / equipo.BUZON_SERVICIO
F.RAICES[:] = [RAIZ]
FIRMAS.update({"docs": 1, "fotos": 1, "bajada": 1})


def docs() -> list:
    """Las pasadas de docs que se han lanzado."""
    return [p for p in F.pasadas(RAIZ) if p.args[-1] == "docs"]


def hasta_pasada(ag, limite: float) -> float | None:
    """Da vueltas hasta que se lanza una pasada de docs.

    Returns:
        Los segundos que pasaron desde que empezó hasta el lanzamiento, o `None`
        si no se lanzó en `limite` segundos.
    """
    n, desde = len(docs()), F.reloj()
    for _ in range(int(limite / TICK)):
        F.vueltas(ag, 1)
        if len(docs()) > n:
            return F.reloj() - TICK - desde
    return None


servicio = agente.leer_servicio(RAIZ)
c("solo vigila la pareja que pide watch = true",
  {p.nombre: p.vigila for p in servicio.parejas},
  {"docs": True, "fotos": False, "bajada": False})
c("  un watch = true en 'down' no cuenta: el local no es origen (lo rechazaría su sync.py)",
  dict(servicio.locales), {"docs": "sync-data/docs"})

ag = nuevo()
F.vueltas(ag, 2)
terminar(ag, RAIZ)
c("las primeras pasadas son las de siempre: las tres, por su orden",
  [p.args[-1] for p in F.pasadas(RAIZ)], ["docs", "fotos", "bajada"])
c("  y ninguna es por cambios", [m for m in F.DIARIO if "han cambiado sus ficheros" in m], [])
F.vueltas(ag, 3)
c("solo se ha mirado la carpeta de docs", {m[0] for m in MIRADAS}, {"docs"})
c("  con el tope de las reglas y sin mirar .prversions/ ni .prdrive/",
  {(m[1], m[2]) for m in MIRADAS}, {(CAMBIOS.tope_entradas, (".prversions", ".prdrive", ".keychain"))})
c("  y tiene la foto de partida", ag.vigiladas[(UID, "docs")].huella, pl.Huella(10, 1))
c("  de ninguna otra pareja", sorted(nom for (_, nom) in ag.vigiladas), ["docs"])

# ---------------------------------------------------------------------------
# 2. Un cambio: UNA pasada tras la calma
# ---------------------------------------------------------------------------
n = len(docs())
m0 = mirada()
quieto(ag, 130)
c("sin cambios no hay pasada: manda el intervalo (10 h)", len(docs()), n)
c("  pero se sigue mirando, cada pocos segundos", mirada() - m0 >= 8, True)

FIRMAS["docs"] = 2
espera = hasta_pasada(ag, 90)
c("un cambio lanza una pasada de esa pareja", espera is not None, True)
c("  no antes de la calma desde que se vio el cambio",
  espera is not None and espera >= CAMBIOS.calma, True)
c("  y pronto: la calma más lo que tarda en verse",
  espera is not None and espera <= CAMBIOS.calma + CAMBIOS.sondeo + 3 * TICK, True)
c("  una sola", len(docs()) - n, 1)
c("  adelantada por cambios", ag.pasada.tarea.por_cambios, True)
c("  y el diario lo dice",
  any("docs (han cambiado sus ficheros)" in m for m in F.DIARIO), True)

# Lo que escribe la propia pasada no la dispara otra vez.
m1 = mirada()
FIRMAS["docs"] = 3                       # rclone escribiendo
quieto(ag, 8)
c("mientras corre la pasada de una pareja no se mira su carpeta", mirada(), m1)
F.acabar(docs()[-1], 0, "OK\n")
F.vueltas(ag, 1)
c("al acabar se pide ya la foto de después: la de partida vuelve a empezar",
  ag.vigiladas[(UID, "docs")].huella, None)
quieto(ag, 2 * TICK)
vigilada = ag.vigiladas[(UID, "docs")]
c("  y con ella no hay cambio pendiente", (vigilada.huella, vigilada.cambio),
  (pl.Huella(10, 3), None))
quieto(ag, 200)
c("lo que escribió la pasada no la dispara otra vez", len(docs()) - n, 1)

# ---------------------------------------------------------------------------
# 3. La separación entre dos pasadas de la misma pareja
# ---------------------------------------------------------------------------
FIRMAS["docs"] = 4
hasta_pasada(ag, 90)
terminar(ag, RAIZ)
fin = ag.marcas[(UID, "docs")].ultimo_intento
quieto(ag, 10)
FIRMAS["docs"] = 5
n = len(docs())
c("un cambio justo después de una pasada espera a la separación",
  hasta_pasada(ag, 200) is not None, True)
lanzada = F.reloj() - TICK
c("  no antes de la separación desde que acabó la anterior",
  lanzada >= fin + CAMBIOS.separacion, True)
c("  y en cuanto se cumple", lanzada <= fin + CAMBIOS.separacion + 2 * TICK, True)
terminar(ag, RAIZ)
quieto(ag, 140)

# ---------------------------------------------------------------------------
# 4. Una ráfaga de cambios es UNA pasada
# ---------------------------------------------------------------------------
n = len(docs())
for _ in range(10):
    FIRMAS["docs"] += 1
    F.vueltas(ag, 3)                     # un cambio cada 6 s, un minuto
c("durante una ráfaga no se lanza nada", len(docs()), n)
espera = hasta_pasada(ag, 90)
c("pasada la ráfaga, una pasada", (espera is not None, len(docs()) - n), (True, 1))
c("  tras la calma, que cuenta desde el último cambio",
  espera is not None and espera >= CAMBIOS.calma - 3 * TICK, True)
terminar(ag, RAIZ)
quieto(ag, 150)
c("  y solo esa", len(docs()) - n, 1)

# ---------------------------------------------------------------------------
# 5. La moderación retiene la pasada Y el recorrido
# ---------------------------------------------------------------------------
n = len(docs())
moderacion.energia = lambda: moderacion.Energia(con_bateria=True, porcentaje=10)
ag.entorno_leido = -math.inf
F.vueltas(ag, 1)
m1 = mirada()
FIRMAS["docs"] += 1
quieto(ag, 120)
c("con batería baja no se lanza la pasada de un cambio", len(docs()), n)
c("  ni se recorre la carpeta: gastaría lo que se quiere ahorrar", mirada(), m1)
c("  y se dice por qué", ag.retenido, "batería por debajo del 20 %")
moderacion.energia = lambda: moderacion.Energia()
ag.entorno_leido = -math.inf
espera = hasta_pasada(ag, 90)
c("al volver, el primer recorrido ve el cambio y la pasada sale tras la calma",
  (espera is not None, len(docs()) - n, ag.pasada.tarea.por_cambios), (True, 1, True))
terminar(ag, RAIZ)
quieto(ag, 140)

n = len(docs())
moderacion.red_medida = lambda: True
ag.entorno_leido = -math.inf
F.vueltas(ag, 1)
m1 = mirada()
FIRMAS["docs"] += 1
quieto(ag, 120)
c("en una red de uso medido, lo mismo: ni pasada ni recorrido",
  (len(docs()), mirada(), ag.retenido), (n, m1, "red de uso medido"))
moderacion.red_medida = lambda: False
ag.entorno_leido = -math.inf
c("  y al volver la red normal, la pasada",
  (hasta_pasada(ag, 90) is not None, len(docs()) - n), (True, 1))
terminar(ag, RAIZ)
quieto(ag, 140)

n = len(docs())
moderacion.energia = lambda: moderacion.Energia(ahorro=True)
ag.entorno_leido = -math.inf
F.vueltas(ag, 1)
m1 = mirada()
FIRMAS["docs"] += 1
quieto(ag, 120)
c("en modo de ahorro de energía, enchufado: ni pasada ni recorrido",
  (len(docs()), mirada(), ag.retenido), (n, m1, "modo de ahorro de energía"))
moderacion.energia = lambda: moderacion.Energia()
ag.entorno_leido = -math.inf
c("  y al quitarlo, la pasada",
  (hasta_pasada(ag, 90) is not None, len(docs()) - n), (True, 1))
terminar(ag, RAIZ)
quieto(ag, 140)

n = len(docs())
ag.pausado = True
F.vueltas(ag, 1)
m1 = mirada()
FIRMAS["docs"] += 1
quieto(ag, 120)
c("en pausa (la bandeja): ni pasada ni recorrido",
  (len(docs()), mirada(), ag.retenido), (n, m1, "en pausa"))
ag.pausado = False
c("  y al seguir, la pasada", (hasta_pasada(ag, 90) is not None, len(docs()) - n), (True, 1))
terminar(ag, RAIZ)
quieto(ag, 140)

# ---------------------------------------------------------------------------
# 6. Una raíz pausada desde su ventana, o con ella abierta, no se recorre
# ---------------------------------------------------------------------------
n = len(docs())
equipo.pedir({"pide": equipo.PIDE_PASADA, "parejas": ["fotos"]}, BUZON)
F.vueltas(ag, 1)
c("con otra pareja en marcha...",
  ag.pasada is not None and ag.pasada.tarea.pareja == "fotos", True)
equipo.pedir({"pide": equipo.PIDE_PAUSAR_RAIZ}, BUZON)
F.vueltas(ag, 2)
m1 = mirada()
quieto(ag, 30)
c("  la pausa de la ventana ya manda aunque el lock siga hasta acabar: no se recorre",
  (F.lock(RAIZ).get("pid"), mirada()), (os.getpid(), m1))
terminar(ag, RAIZ)
F.vueltas(ag, 2)
m1 = mirada()
FIRMAS["docs"] += 1
quieto(ag, 120)
c("con su raíz pausada desde su ventana: sin lock, sin pasada y sin recorrer",
  (F.lock(RAIZ), len(docs()), mirada()), ({}, n, m1))
c("  y se olvida lo que se sabía de ella", (UID, "docs") in ag.vigiladas, False)
c("  el estado no dice que la vigile",
  next(u for u in ag.resumen()["unidades"] if u["id"] == UID)["vigila"], [])

equipo.pedir({"pide": equipo.PIDE_REANUDAR}, BUZON)
F.vueltas(ag, 2)
c("al reanudar, la pasada de siempre (no por cambios)",
  (len(docs()) - n, ag.pasada.tarea.por_cambios), (1, False))
terminar(ag, RAIZ)
quieto(ag, 200)
c("  y el cambio de mientras estuvo pausada no dispara otra: la foto de partida es nueva",
  len(docs()) - n, 1)

n = len(docs())
F.stop(RAIZ).touch()
F.ventana_abierta(RAIZ)
F.vueltas(ag, 2)
m1 = mirada()
FIRMAS["docs"] += 1
quieto(ag, 60)
c("con su ventana abierta: sin lock, sin recorrer y sin pasada",
  (F.lock(RAIZ), len(docs()), mirada()), ({}, n, m1))
(RAIZ / penwatch.UI_LOCK_REL).unlink()
F.pasar(agente.GRACIA)
quieto(ag, 200)
c("  al irse la ventana vuelve a mirar, y lo hecho desde ella no es un cambio",
  (mirada() > m1, len(docs()) - n), (True, 0))

# ---------------------------------------------------------------------------
# 7. Las demás parejas, nunca
# ---------------------------------------------------------------------------
FIRMAS["fotos"] = 99
FIRMAS["bajada"] = 99
quieto(ag, 120)
c("una pareja sin watch (o con uno que no vale) no se mira en toda la prueba",
  {m[0] for m in MIRADAS}, {"docs"})
c("  y sus cambios no lanzan nada", [m for m in F.DIARIO if "han cambiado sus ficheros" in m
                                    and ("fotos" in m or "bajada" in m)], [])

# ---------------------------------------------------------------------------
# 8. El estado y `status`
# ---------------------------------------------------------------------------
unidad_w = next(u for u in ag.resumen()["unidades"] if u["id"] == UID)
c("el estado dice qué se vigila", (unidad_w["vigila"], unidad_w["vigila_abandonada"]),
  (["docs"], []))
c("  y llega a estado.json", next(u for u in equipo.leer_estado()["unidades"]
                                  if u["id"] == UID)["vigila"], ["docs"])
store.write_json(equipo.lock_json(), {"pid": os.getpid(), "host": agente.HOST})
salida = io.StringIO()
with contextlib.redirect_stdout(salida):
    agente.cmd_status(None)
c("  y `status` lo cuenta", "Sincroniza al cambiar sus ficheros: docs" in salida.getvalue(),
  True)
equipo.lock_json().unlink()

F.RAICES[:] = []
F.vueltas(ag, 1)
c("una unidad que se va olvida lo que sabía de sus parejas",
  (UID in ag.conexiones, ag.vigiladas), (False, {}))

# ---------------------------------------------------------------------------
# 9. El recorrido va en un hilo
# ---------------------------------------------------------------------------
F.preparar()
UID2 = "e" * 32
RAIZ2 = poner(UID2, parejas=("docs",), extra={"docs": VIGILA})
F.RAICES[:] = [RAIZ2]

llamadas: list[str] = []
entro, suelta = threading.Event(), threading.Event()


def foto_lenta(ruta, tope, ignorar):
    """Una foto que tarda hasta que el test la suelta."""
    llamadas.append(Path(ruta).name)
    entro.set()
    suelta.wait(20)
    return pl.Huella(3, 1)


agente.huella_local = foto_lenta
agente.hilo = lambda funcion: threading.Thread(target=funcion, daemon=True).start()

ag2 = nuevo()
desde = time.monotonic()
F.vueltas(ag2, 2)
entro.wait(5)
pasada2 = F.pasadas(RAIZ2)
c("la vuelta no espera a la foto: hay pasada y la foto sigue en marcha",
  (len(pasada2), ag2.muestreo is not None and not ag2.muestreo.hecho,
   time.monotonic() - desde < 5), (1, True, True))
F.vueltas(ag2, 6)
c("  y no se pide otra mientras tanto: una a la vez", llamadas, ["docs"])
F.acabar(pasada2[0], 0, "OK\n")
F.vueltas(ag2, 1)
c("  acaba la pasada con la foto todavía en marcha: sigue sin otra", llamadas, ["docs"])
suelta.set()
for _ in range(250):
    if ag2.muestreo.hecho:
        break
    time.sleep(0.02)
F.vueltas(ag2, 1)
c("la foto que se estaba tomando cuando acabó la pasada no cuenta",
  [k for k, v in ag2.vigiladas.items() if v.huella is not None], [])
for _ in range(250):
    F.vueltas(ag2, 1)
    if ag2.vigiladas.get((UID2, "docs"), pl.Vigilada()).huella is not None:
        break
    time.sleep(0.02)
c("  la siguiente, ya sin pasada de por medio, sí",
  ag2.vigiladas[(UID2, "docs")].huella, pl.Huella(3, 1))
agente.hilo = lambda funcion: funcion()


def entregar(ag, clave, con, validas, descartar=(), en_curso=False):
    """Le da al agente un muestreo terminado con una foto y dice qué quedó de ella.

    Returns:
        Lo recordado de esa pareja después de recogerlo, o `None` si no se recordó nada.
    """
    ag.vigiladas.pop(clave, None)
    m = agente.Muestreo([agente.Mirar(clave, con, RAIZ2, RAIZ2 / "sync-data" / "docs")], 10, ())
    m.fotos[clave] = pl.Huella(3, 7)
    m.descartar.update(descartar)
    m.hecho = True
    ag.muestreo = m
    ag.pasada = agente.Pasada(F.Proc([]), pl.Tarea(pl.PASADA, *clave), F.reloj(), Path("x"),
                              "x") if en_curso else None
    ag._recoger_fotos(F.reloj(), set(validas))
    ag.pasada = None
    return ag.vigiladas.get(clave)


clave2 = (UID2, "docs")
con2 = ag2.conexiones[UID2]
ag2.muestreo = None
c("una foto que nada invalida se recuerda (la de partida)",
  entregar(ag2, clave2, con2, [clave2]).huella, pl.Huella(3, 7))
c("  la de una unidad que se fue y volvió (otra conexión) no cuenta",
  entregar(ag2, clave2, agente.Conexion(UID2, RAIZ2, "otra", 0.0), [clave2]), None)
c("  la de una pareja cuya pasada acabó mientras se miraba, tampoco",
  entregar(ag2, clave2, con2, [clave2], descartar=[clave2]), None)
c("  ni la de una con la pasada en marcha", entregar(ag2, clave2, con2, [clave2], en_curso=True),
  None)
c("  ni la de una que ya no se vigila", entregar(ag2, clave2, con2, []), None)
ag2.muestreo = None

# ---------------------------------------------------------------------------
# 10. Demasiadas entradas: se abandona
# ---------------------------------------------------------------------------
F.preparar()
MIRADAS.clear()


def foto_enorme(ruta, tope, ignorar):
    """Una carpeta con más entradas que el tope."""
    MIRADAS.append((Path(ruta).name, tope, tuple(ignorar)))
    return pl.Huella(tope + 1, 0, cortada=True)


agente.huella_local = foto_enorme
UID4 = "a" * 32
RAIZ4 = poner(UID4, parejas=("docs",), nombre="GRANDE", extra={"docs": VIGILA})
F.RAICES[:] = [RAIZ4]
ag4 = nuevo()
F.vueltas(ag4, 2)
terminar(ag4, RAIZ4)
quieto(ag4, 30)
c("una carpeta con más entradas que el tope se abandona",
  ag4.vigiladas[(UID4, "docs")].abandonada, True)
mirada4 = len(MIRADAS)
quieto(ag4, 200)
c("  y no se vuelve a mirar en esta conexión", len(MIRADAS), mirada4)
c("  se dice una vez en el diario del agente",
  sum("deja de vigilarse" in m for m in F.DIARIO), 1)
c("  y en el de la raíz",
  (RAIZ4 / ".prdrive" / "state" / "daemon.log").read_text(encoding="utf-8").count(
      "no se vigila, manda el intervalo"), 1)
res = next(u for u in ag4.resumen()["unidades"] if u["id"] == UID4)
c("  el estado la da por abandonada, no por vigilada",
  (res["vigila"], res["vigila_abandonada"]), ([], ["docs"]))
c("  y el intervalo sigue mandando: ninguna pasada más", len(F.pasadas(RAIZ4)), 1)


def foto_real(ruta, tope, ignorar):
    """La foto de verdad, apuntando qué se mira."""
    MIRADAS.append((Path(ruta).name, tope, tuple(ignorar)))
    return huella.de_carpeta(ruta, tope, ignorar)


# La foto de verdad, sobre carpetas de verdad y con el tope más corto.
F.preparar()
agente.huella_local = foto_real
UID5 = "b" * 32
RAIZ5 = poner(UID5, parejas=("docs", "otra"), extra={"docs": VIGILA, "otra": VIGILA})
docs5, otra5 = RAIZ5 / "sync-data" / "docs", RAIZ5 / "sync-data" / "otra"
(docs5 / ".prversions").mkdir(parents=True)
otra5.mkdir(parents=True)
for i in range(3):
    (docs5 / f"n{i}.md").write_text("x", encoding="utf-8")
for i in range(10):
    (docs5 / ".prversions" / f"v{i}~1.md").write_text("x", encoding="utf-8")
for i in range(8):
    (otra5 / f"n{i}.md").write_text("x", encoding="utf-8")
F.RAICES[:] = [RAIZ5]
ag5 = nuevo()
ag5.cambios = replace(CAMBIOS, tope_entradas=5)
F.vueltas(ag5, 2)
terminar(ag5, RAIZ5)
quieto(ag5, 60)
c("con carpetas de verdad, 3 entradas y 10 de .prversions/ caben en un tope de 5",
  ag5.vigiladas[(UID5, "docs")].abandonada, False)
c("  y 8 entradas no", ag5.vigiladas[(UID5, "otra")].abandonada, True)
(docs5 / "nuevo.md").write_text("y", encoding="utf-8")
n = len([p for p in F.pasadas(RAIZ5) if p.args[-1] == "docs"])
for _ in range(70):
    F.vueltas(ag5, 1)
    if len([p for p in F.pasadas(RAIZ5) if p.args[-1] == "docs"]) > n:
        break
c("  y un fichero nuevo, visto por el recorrido de verdad, lanza la pasada",
  (len([p for p in F.pasadas(RAIZ5) if p.args[-1] == "docs"]) - n,
   ag5.pasada.tarea.por_cambios), (1, True))

# ---------------------------------------------------------------------------
# 11. La carpeta de la pareja no sale de la raíz
# ---------------------------------------------------------------------------
F.preparar()
MIRADAS.clear()


def foto_cualquiera(ruta, tope, ignorar):
    """Apunta qué se mira; no debería llamarse."""
    MIRADAS.append((str(ruta), tope, tuple(ignorar)))
    return pl.Huella(1, 1)


agente.huella_local = foto_cualquiera
UID6 = "c" * 32
FUERA = F.unidad("0" * 32, parejas=("secreto",))           # otra carpeta, fuera de la raíz
# Un `..` en el `local` ni llega a vigilarse: `leer_servicio()` no sirve esa raíz
# (`model.comprobar_seguridad()`). Queda la que sale por un enlace, que solo se
# ve al resolver la ruta.
ARRIBA = F.unidad("3" * 32, parejas=("arriba",), extra={"arriba": VIGILA},
                  locales={"arriba": "../carpeta-de-al-lado"})
try:
    agente.leer_servicio(ARRIBA)
    sirve_arriba = True
except ValueError:
    sirve_arriba = False
c("una `local` que sube fuera de la raíz no se sirve: no llega a vigilarse", sirve_arriba, False)
RAIZ6 = poner(UID6, parejas=("enlace",), nombre="ENLACES", extra={"enlace": VIGILA})
enlace = False
try:
    (RAIZ6 / "sync-data").mkdir()
    os.symlink(FUERA, RAIZ6 / "sync-data" / "enlace", target_is_directory=True)
    enlace = True
except (OSError, NotImplementedError):
    print("  (saltado) no se pueden crear enlaces simbólicos: no se prueba el que sale")
F.RAICES[:] = [RAIZ6]
ag6 = nuevo()
F.vueltas(ag6, 2)
terminar(ag6, RAIZ6)
quieto(ag6, 60)
if enlace:
    c("un enlace que saca la carpeta de la raíz no se sigue: se abandona",
      (ag6.vigiladas[(UID6, "enlace")].abandonada, MIRADAS), (True, []))
    c("  y se dice, una vez",
      sum("enlace: su carpeta cae fuera de la raíz" in m for m in F.DIARIO), 1)

# ---------------------------------------------------------------------------
# 11b. Qué carpeta se mira, y una que no se deja mirar
# ---------------------------------------------------------------------------
# El `local` se lee como el motor (`\` pasa a `/`, sin las de los extremos), el ruido del
# sistema solo se deja fuera si la carpeta es la raíz de la unidad, y una
# carpeta que sale sin foto varias veces seguidas se dice una vez.
F.preparar()
MIRADAS.clear()
CIEGAS: set[str] = set()
"""Las carpetas (su ruta) cuya foto sale `None` ahora mismo."""


def foto_a_ratos(ruta, tope, ignorar):
    """Apunta qué se mira; las carpetas de `CIEGAS` no dan foto."""
    MIRADAS.append((str(ruta), tope, tuple(ignorar)))
    return None if str(ruta) in CIEGAS else pl.Huella(3, 1)


agente.huella_local = foto_a_ratos
UID8 = "8" * 32
RAIZ8 = poner(UID8, parejas=("docs", "raiz", "otra"), nombre="CIEGA",
              extra={"docs": VIGILA, "raiz": VIGILA, "otra": VIGILA},
              locales={"docs": "sync-data\\\\docs", "raiz": ".", "otra": "/sync-data/otra/"})
c("el `local` se lee como lo lee el motor: barras normales y sin las de los extremos",
  dict(agente.leer_servicio(RAIZ8).locales),
  {"docs": "sync-data/docs", "raiz": ".", "otra": "sync-data/otra"})
F.RAICES[:] = [RAIZ8]
CIEGAS.add(str(RAIZ8 / "sync-data" / "otra"))
ag8 = nuevo()
F.vueltas(ag8, 2)
terminar(ag8, RAIZ8)
quieto(ag8, 20)
ignoradas = {m[0]: m[2] for m in MIRADAS}
c("se mira la carpeta que sincroniza el motor, no una con la barra invertida",
  sorted(ignoradas), sorted(str(RAIZ8 / x) for x in ("sync-data/docs", ".", "sync-data/otra")))
c("  en una carpeta cualquiera no se deja fuera nada más que lo de siempre",
  ignoradas[str(RAIZ8 / "sync-data" / "docs")], agente.IGNORAR_CAMBIOS)
c("  en la raíz de la unidad (`local = \".\"`), también el ruido del sistema",
  ignoradas[str(RAIZ8)], agente.IGNORAR_CAMBIOS + model.RUIDO_DEL_SISTEMA)
c("  y con él lo que hay que dejar fuera: System Volume Information y $RECYCLE.BIN",
  {"system volume information", "$recycle.bin"} <= set(ignoradas[str(RAIZ8)]), True)

quieto(ag8, 60)
c("una carpeta que no da foto varios recorridos seguidos se dice, una vez, en el diario",
  sum("otra: no se puede mirar su carpeta" in m for m in F.DIARIO), 1)
c("  y en el de la raíz",
  (RAIZ8 / ".prdrive" / "state" / "daemon.log").read_text(encoding="utf-8").count(
      "[otra] watch: no se puede mirar su carpeta"), 1)
c("  las demás no dicen nada", [m for m in F.DIARIO if "no se puede mirar" in m
                                 and "otra:" not in m], [])
c("  y no por eso se pierde la vigilancia: sigue sin foto, ni cambio ni abandono",
  (ag8.vigiladas[(UID8, "otra")].huella, ag8.vigiladas[(UID8, "otra")].cambio,
   ag8.vigiladas[(UID8, "otra")].abandonada), (None, None, False))
ag8.urgentes.append((UID8, "otra"))
F.vueltas(ag8, 2)
terminar(ag8, RAIZ8)
quieto(ag8, 60)
c("  una pasada de esa pareja entremedias no repite la línea",
  sum("otra: no se puede mirar su carpeta" in m for m in F.DIARIO), 1)
CIEGAS.clear()
quieto(ag8, 60)
c("al volver a poder mirarla, se dice una vez",
  sum("otra: su carpeta vuelve a poder mirarse" in m for m in F.DIARIO), 1)
c("  y la foto es la de partida", ag8.vigiladas[(UID8, "otra")].fallidas, 0)

# ---------------------------------------------------------------------------
# 11c. Con las reglas de fábrica el recorrido se espacia
# ---------------------------------------------------------------------------
# Quieta, cada `sondeo_quieto`; tras ver un cambio, cada `sondeo` durante
# `sondeo_quieto`; a batería, nunca antes de `sondeo_bateria`.
F.preparar()
CUANDO: list[float] = []
"""La hora de cada foto de la sección."""


def foto_con_hora(ruta, tope, ignorar):
    """La foto de mentira, apuntando cuándo se tomó."""
    CUANDO.append(F.reloj())
    return pl.Huella(10, FIRMAS[Path(ruta).name])


agente.huella_local = foto_con_hora
UID9 = "7" * 32
RAIZ9 = poner(UID9, parejas=("docs",), extra={"docs": VIGILA})
F.RAICES[:] = [RAIZ9]
FIRMAS["docs"] = 1
ag9 = F.nuevo()
c("el agente usa las reglas de fábrica", ag9.cambios, FABRICA)
F.vueltas(ag9, 2)
terminar(ag9, RAIZ9)
quieto(ag9, 30)
n0 = len(CUANDO)
quieto(ag9, 400)
c("quieta, se recorre cada sondeo_quieto: 3 o 4 veces en 400 s", len(CUANDO) - n0 in (3, 4),
  True)


def pasadas9() -> int:
    """Cuántas pasadas de la unidad de esta sección se han lanzado."""
    return len(F.pasadas(RAIZ9))


n = pasadas9()
FIRMAS["docs"] += 1
cambio = F.reloj()
for _ in range(int(200 / TICK)):
    F.vueltas(ag9, 1)
    if pasadas9() > n:
        break
c("un cambio en una carpeta quieta se ve, como mucho, al sondeo_quieto",
  pasadas9() - n == 1 and F.reloj() - cambio <= FABRICA.sondeo_quieto + FABRICA.calma
  + 3 * TICK, True)
terminar(ag9, RAIZ9)
n0 = len(CUANDO)
quieto(ag9, 60)
c("  y tras verlo vuelve al sondeo: 5 o más recorridos en un minuto", len(CUANDO) - n0 >= 5,
  True)

moderacion.energia = lambda: moderacion.Energia(con_bateria=True, porcentaje=80)
ag9.entorno_leido = -math.inf
quieto(ag9, 200)
n = pasadas9()
FIRMAS["docs"] += 1
for _ in range(int(200 / TICK)):
    F.vueltas(ag9, 1)
    if pasadas9() > n:
        break
terminar(ag9, RAIZ9)                      # y la foto de después, ya
n0 = len(CUANDO)
quieto(ag9, 240)
huecos = [b - a for a, b in zip(CUANDO[n0 - 1:], CUANDO[n0:])]
c("a batería, aunque se mueva, nunca antes de sondeo_bateria",
  bool(huecos) and min(huecos) >= FABRICA.sondeo_bateria, True)
moderacion.energia = lambda: moderacion.Energia()
agente.huella_local = foto

# ---------------------------------------------------------------------------
# 11d. Con los avisos del sistema
# ---------------------------------------------------------------------------
ORDEN: list[tuple] = []
"""Lo que se ha pedido al motor de avisos de mentira, y otras cosas, en orden."""


class AvisosFalsos:
    """Un motor de avisos de mentira: apunta lo que le piden y entrega lo que pone el test.

    Attributes:
        pendientes: Lo que entregará el próximo `recoger()`, por pareja.
        motivos: Lo que contesta `vigilar()` por pareja (`None`, se vigila).
    """

    def __init__(self) -> None:
        """Empieza sin nada pendiente y vigilándolo todo."""
        self.pendientes: dict = {}
        self.motivos: dict = {}

    def vigilar(self, clave, carpeta, ignorar):
        """Apunta la petición y contesta lo que diga `motivos`."""
        ORDEN.append(("vigilar", clave))
        return self.motivos.get(clave)

    def dejar(self, clave):
        """Apunta que se deja una pareja."""
        ORDEN.append(("dejar", clave))

    def dejar_raiz(self, uid):
        """Apunta que se deja una raíz."""
        ORDEN.append(("dejar_raiz", uid))

    def recoger(self):
        """Entrega lo pendiente."""
        avisos, self.pendientes = self.pendientes, {}
        return avisos

    def descartar(self, clave):
        """Tira lo pendiente de una pareja salvo una pérdida, como el de verdad."""
        ORDEN.append(("descartar", clave))
        aviso = self.pendientes.get(clave)
        if aviso is None or aviso.tipo == ac.PERDIDA:
            return None
        return self.pendientes.pop(clave)

    def cerrar(self):
        """Nada que cerrar."""


def pedidas(que: str, clave=None) -> int:
    """Cuántas veces se ha pedido eso al motor (de esa pareja o raíz)."""
    return sum(1 for o in ORDEN if o[0] == que and (clave is None or o[1] == clave))


F.preparar()
MIRADAS.clear()
agente.huella_local = foto
UIDA = "f" * 32
RAIZA = poner(UIDA, parejas=("docs", "fotos"), nombre="AVISOS", extra={"docs": VIGILA})
BUZONA = RAIZA / ".prdrive" / "state" / equipo.BUZON_SERVICIO
F.RAICES[:] = [RAIZA]
FIRMAS.update({"docs": 1, "fotos": 1})
DOCSA = (UIDA, "docs")
motor = AvisosFalsos()
aga = nuevo()
aga.avisos_carpeta = motor
F.vueltas(aga, 2)
terminar(aga, RAIZA)
quieto(aga, 300)
c("con avisos, la pareja se vigila con ellos al conectarse", pedidas("vigilar", DOCSA), 1)
c("  y su carpeta no se recorre nunca", mirada(), 0)
c("  lo recordado dice que oye avisos", aga.vigiladas[DOCSA].avisos, True)
c("  y el estado no dice que recorra", next(u for u in aga.resumen()["unidades"]
                                            if u["id"] == UIDA)["vigila_recorre"], {})


def docsa() -> int:
    """Cuántas pasadas de docs de esta unidad se han lanzado."""
    return sum(1 for p in F.pasadas(RAIZA) if p.args[-1] == "docs")


def hasta_pasada_a(limite: float) -> float | None:
    """Da vueltas hasta que sale una pasada de docs; devuelve cuánto tardó."""
    n, desde = docsa(), F.reloj()
    for _ in range(int(limite / TICK)):
        F.vueltas(aga, 1)
        if docsa() > n:
            return F.reloj() - TICK - desde
    return None


n, tiradas = docsa(), pedidas("descartar", DOCSA)
motor.pendientes[DOCSA] = ac.Aviso(ac.CAMBIO)
espera = hasta_pasada_a(90)
c("un aviso lanza la pasada tras la calma",
  (espera is not None and CAMBIOS.calma <= espera <= CAMBIOS.calma + 2 * TICK,
   docsa() - n, aga.pasada.tarea.por_cambios), (True, 1, True))
quieto(aga, 8)
motor.pendientes[DOCSA] = ac.Aviso(ac.CAMBIO)           # rclone escribiendo
F.vueltas(aga, 1)
motor.pendientes[DOCSA] = ac.Aviso(ac.CAMBIO)           # y lo último, ya en la cola
terminar(aga, RAIZA)
c("al acabar la pasada se tira lo que escribió", pedidas("descartar", DOCSA) - tiradas, 1)
quieto(aga, 200)
c("  y nada de lo que escribió la pasada lanza otra", docsa() - n, 1)
c("  sigue oyendo avisos, sin recorrer", (aga.vigiladas[DOCSA].avisos, mirada()), (True, 0))

n, antes = docsa(), pedidas("vigilar", DOCSA)
motor.pendientes[DOCSA] = ac.Aviso(ac.DESBORDADO)
c("un desbordado es un cambio...", hasta_pasada_a(90) is not None, True)
c("  y la vigilancia se rehace", pedidas("vigilar", DOCSA), antes + 1)
terminar(aga, RAIZA)
quieto(aga, 140)

n = docsa()
moderacion.energia = lambda: moderacion.Energia(con_bateria=True, porcentaje=10)
aga.entorno_leido = -math.inf
F.vueltas(aga, 1)
motor.pendientes[DOCSA] = ac.Aviso(ac.CAMBIO)
quieto(aga, 120)
c("con la moderación reteniendo, el aviso no lanza la pasada", docsa(), n)
c("  pero se apunta", aga.vigiladas[DOCSA].cambio is not None, True)
moderacion.energia = lambda: moderacion.Energia()
aga.entorno_leido = -math.inf
espera = hasta_pasada_a(30)
c("  y al soltar, la pasada sale ya: su calma ya pasó",
  espera is not None and espera <= 2 * TICK, True)
terminar(aga, RAIZA)
quieto(aga, 140)

n = docsa()
motor.pendientes[DOCSA] = ac.Aviso(ac.PERDIDA, "su carpeta ya no está donde estaba")
F.vueltas(aga, 1)
c("perder la vigilancia vuelve a recorrer", aga.vigiladas[DOCSA].avisos, False)
quieto(aga, 20)
c("  la carpeta se recorre", mirada() > 0, True)
c("  se dice una vez, con el motivo", sum("ya no está donde estaba" in m for m in F.DIARIO), 1)
c("  también en el diario de la raíz",
  "ya no está donde estaba" in (RAIZA / ".prdrive" / "state" / "daemon.log").read_text(
      encoding="utf-8"), True)
unidad_a = next(u for u in aga.resumen()["unidades"] if u["id"] == UIDA)
c("  y el estado dice que recorre, y por qué",
  unidad_a["vigila_recorre"], {"docs": "su carpeta ya no está donde estaba"})
store.write_json(equipo.estado_json(), aga.resumen())
store.write_json(equipo.lock_json(), {"pid": os.getpid(), "host": agente.HOST})
salida = io.StringIO()
with contextlib.redirect_stdout(salida):
    agente.cmd_status(None)
c("  y `status` lo cuenta", "Recorre su carpeta (sin avisos del sistema): docs (su carpeta ya "
  "no está donde estaba)" in salida.getvalue(), True)
equipo.lock_json().unlink()
FIRMAS["docs"] += 1
c("  y un cambio lo ve el recorrido", hasta_pasada_a(60) is not None, True)
terminar(aga, RAIZA)

equipo.pedir({"pide": equipo.PIDE_PAUSAR_RAIZ}, BUZONA)
F.vueltas(aga, 2)
c("una raíz pausada desde su ventana deja sus vigilancias", pedidas("dejar", DOCSA) >= 1, True)
c("  y olvida por qué recorría", DOCSA in aga.sin_avisos, False)
antes = pedidas("vigilar", DOCSA)
equipo.pedir({"pide": equipo.PIDE_REANUDAR}, BUZONA)
F.vueltas(aga, 3)
terminar(aga, RAIZA)
F.vueltas(aga, 2)
c("  al reanudar, se vuelve a vigilar con avisos",
  (pedidas("vigilar", DOCSA) - antes, aga.vigiladas[DOCSA].avisos), (1, True))

F.RAICES[:] = []
F.vueltas(aga, 1)
c("al irse la unidad se dejan las vigilancias de su raíz",
  (pedidas("dejar_raiz", UIDA) >= 1, aga.vigiladas), (True, {}))

# Sin avisos para esa carpeta (de red, o sin sitio): se recorre y se dice.
F.preparar()
MIRADAS.clear()
agente.huella_local = foto
UIDB = "1" * 32
RAIZB = poner(UIDB, parejas=("docs",), nombre="RED", extra={"docs": VIGILA})
F.RAICES[:] = [RAIZB]
motor = AvisosFalsos()
motor.motivos[(UIDB, "docs")] = "es una carpeta de red o compartida (nfs4)"
agb = nuevo()
agb.avisos_carpeta = motor
F.vueltas(agb, 2)
terminar(agb, RAIZB)
quieto(agb, 30)
c("sin avisos para su carpeta, se recorre", (mirada() > 0, agb.vigiladas[(UIDB, "docs")].avisos),
  (True, False))
c("  se dice una vez por qué", sum("carpeta de red o compartida (nfs4)" in m for m in F.DIARIO), 1)
c("  y el estado lo cuenta", next(u for u in agb.resumen()["unidades"]
                                  if u["id"] == UIDB)["vigila_recorre"],
  {"docs": "es una carpeta de red o compartida (nfs4)"})

# El resultado de ponerla de una conexión anterior no cuenta y no se queda puesto.
con_vieja = agente.Conexion(UIDB, RAIZB, "vieja", 0.0)
m_viejo = agente.Muestreo([agente.Mirar((UIDB, "docs"), con_vieja, RAIZB,
                                        RAIZB / "sync-data" / "docs", armar=True)], 10, ())
m_viejo.armadas[(UIDB, "docs")] = None
m_viejo.hecho = True
agb.muestreo = m_viejo
dejadas = pedidas("dejar", (UIDB, "docs"))
F.vueltas(agb, 1)
c("lo puesto para una conexión anterior se deja y no cuenta",
  (pedidas("dejar", (UIDB, "docs")) - dejadas, agb.vigiladas[(UIDB, "docs")].avisos), (1, False))

# Sin motor (Windows, o sin inotify): todas recorren, y el estado lo dice.
agc = nuevo()
F.vueltas(agc, 2)
terminar(agc, RAIZB)
c("sin motor de avisos el estado dice que recorre", next(
    u for u in agc.resumen()["unidades"] if u["id"] == UIDB)["vigila_recorre"],
  {"docs": agente.SIN_MOTOR_DE_AVISOS})

# «Expulsar» deja las vigilancias de la raíz antes de soltarla.
F.preparar()
UIDE = "2" * 32
RAIZE = poner(UIDE, parejas=("docs",), nombre="EXPULSABLE", extra={"docs": VIGILA})
F.RAICES[:] = [RAIZE]
F.COMPATIBLES.add(RAIZE)
expulsar_falso = expulsar.expulsar
expulsar.expulsar = lambda raiz: ORDEN.append(("expulsar", Path(raiz))) or expulsar_falso(raiz)
age = nuevo()
age.avisos_carpeta = AvisosFalsos()
F.vueltas(age, 2)
terminar(age, RAIZE)
F.vueltas(age, 2)
ORDEN.clear()
equipo.pedir({"pide": equipo.PIDE_EXPULSAR, "id": UIDE})
F.vueltas(age, 3)
c("«Expulsar» deja las vigilancias de la raíz antes de expulsarla",
  [o for o in ORDEN if o[0] in ("dejar_raiz", "expulsar")][:2],
  [("dejar_raiz", UIDE), ("expulsar", RAIZE)])
agente.huella_local = foto

# ---------------------------------------------------------------------------
# 11e. Con el inotify de verdad (Linux)
# ---------------------------------------------------------------------------
motor_real = ac.abrir()
if motor_real is None:
    print("  (saltado) sin inotify: no se prueba el agente con los avisos de verdad")
else:
    F.preparar()
    RECORRIDAS: list[str] = []
    agente.huella_local = lambda ruta, tope, ignorar: RECORRIDAS.append(str(ruta)) or None
    UIDR = "3" * 32
    RAIZR = poner(UIDR, parejas=("docs",), nombre="INOTIFY", extra={"docs": VIGILA},
                  locales={"docs": "."})
    F.RAICES[:] = [RAIZR]
    agr = nuevo()
    agr.avisos_carpeta = motor_real
    F.vueltas(agr, 2)
    terminar(agr, RAIZR)
    F.vueltas(agr, 2)
    c("con inotify de verdad, la pareja se vigila con avisos",
      (agr.vigiladas[(UIDR, "docs")].avisos, motor_real.vigilancias() > 0), (True, True))
    n = len(F.pasadas(RAIZR))
    (RAIZR / ".prdrive" / "state" / "algo.json").write_text("{}", encoding="utf-8")
    quieto(agr, 60)
    c("  lo que se escribe en .prdrive/ (local = \".\") no lanza nada",
      len(F.pasadas(RAIZR)), n)
    (RAIZR / "nota.md").write_text("hola", encoding="utf-8")
    for _ in range(int(60 / TICK)):
        F.vueltas(agr, 1)
        if len(F.pasadas(RAIZR)) > n:
            break
    c("  un fichero nuevo lanza la pasada, sin recorrer la carpeta",
      (len(F.pasadas(RAIZR)) - n, agr.pasada.tarea.por_cambios, RECORRIDAS), (1, True, []))
    (RAIZR / "de-rclone.md").write_text("bajado", encoding="utf-8")
    terminar(agr, RAIZR)
    quieto(agr, 200)
    c("  y lo que escribe la pasada no lanza otra", len(F.pasadas(RAIZR)) - n, 1)
    F.RAICES[:] = []
    F.vueltas(agr, 1)
    c("  al irse la unidad no queda ninguna vigilancia", motor_real.vigilancias(), 0)
    motor_real.cerrar()
    agente.huella_local = foto

# ---------------------------------------------------------------------------
# 11f. Poner el motor: en Windows, solo con la ventana de la bandeja
# ---------------------------------------------------------------------------
F.preparar()
real_abrir, real_is_win = ac.abrir, agente.IS_WIN
VENTANAS: list = []


class MotorFalso:
    """Un motor de avisos de Windows de mentira: sin descriptor, con `dispositivo`."""
    fd = None

    def dispositivo(self, evento, handle):
        """Lo que la bandeja le pasaría."""

    def leer(self):
        """Nada que leer."""


motor_w = MotorFalso()
ac.abrir = lambda hwnd=None: VENTANAS.append(hwnd) or motor_w
agente.IS_WIN = True
agw = nuevo()
agw.bandeja = None
c("en Windows, sin bandeja no hay motor", (agente.poner_avisos_carpeta(agw, agente.Vigia()),
                                          VENTANAS), (None, []))
c("  y se dice: las carpetas se recorren",
  any("sin bandeja no se dejan carpetas abiertas" in m for m in F.DIARIO), True)
agw.bandeja = SimpleNamespace(hwnd=0x55, dispositivo=None)
c("con bandeja, el motor se abre con su ventana",
  (agente.poner_avisos_carpeta(agw, agente.Vigia()) is motor_w, VENTANAS), (True, [0x55]))
c("  y la bandeja le pasa los avisos de extracción",
  agw.bandeja.dispositivo == motor_w.dispositivo, True)
c("  y se dice", any("(ReadDirectoryChangesW)" in m for m in F.DIARIO), True)
agente.IS_WIN = real_is_win
ac.abrir = real_abrir

# ---------------------------------------------------------------------------
# 12. «Bloquear» espera a la foto en marcha
# ---------------------------------------------------------------------------
# Con un VeraCrypt de mentira, en Linux (una carpeta como punto de montaje): lo
# que se lanza se apunta. Va el último porque cambia `IS_WIN` y `letra`.
F.preparar()
penwatch.candidate_roots = lambda cfg: ([Path(r) for r in cfg.get("extra_roots", [])]
                                        + list(F.RAICES))
VC = "/opt/veracrypt/veracrypt"
penwatch.installed_veracrypt = lambda: VC
penwatch._con_escritorio = lambda: True
vestibulo.retenido = lambda hc: None
penwatch.IS_WIN = agente.IS_WIN = False
equipo.Unidad.letra = property(lambda self: "")

UID7 = "9" * 32
HC = tmpdir("prdrive-cifrado-") / vestibulo.CONTENEDOR
HC.write_bytes(b"\0" * 512)
PUNTO = tmpdir("prdrive-punto-")
app = PUNTO / penwatch.APP_SUBDIR
(app / "state").mkdir(parents=True)
(app / "PRDRIVE").write_text(f"id={UID7}\ntipo=equipo\n", encoding="utf-8")
(app / "VERSION").write_text(F.VERSION + "\n", encoding="utf-8")
for py in ("runsync.py", "sync.py"):
    (app / py).write_text("# de mentira\n", encoding="utf-8")
(app / "sync_config.toml").write_text(
    '[defaults]\nremote = "nas"\n\n[[pair]]\nname = "notas"\nlocal = "notas"\n'
    'remote_path = "/R/notas"\nwatch = true\n', encoding="utf-8")
equipo.guardar_ajustes(equipo.Ajustes().con_unidad(
    equipo.Unidad(UID7, equipo.DAEMON, "Mi portátil", str(PUNTO), str(HC))))
F.RAICES[:] = [PUNTO]

llamadas.clear()
entro.clear()
suelta.clear()
agente.huella_local = foto_lenta
agente.hilo = lambda funcion: threading.Thread(target=funcion, daemon=True).start()
ag7 = nuevo()
F.vueltas(ag7, 3)
entro.wait(5)
F.acabar(F.pasadas(PUNTO)[0], 0, "OK\n")
F.vueltas(ag7, 1)
veracrypts = lambda: [p for p in F.LANZADOS if p.args and p.args[0] == VC]  # noqa: E731
antes = len(veracrypts())
equipo.pedir({"pide": equipo.PIDE_BLOQUEAR, "id": UID7})
F.vueltas(ag7, 4)
c("«Bloquear» espera a la foto en marcha, que tiene la carpeta abierta",
  (ag7.muestreo is not None and not ag7.muestreo.hecho, len(veracrypts()) - antes), (True, 0))
suelta.set()
for _ in range(250):
    if ag7.muestreo is None or ag7.muestreo.hecho:
        break
    time.sleep(0.02)
F.vueltas(ag7, 2)
c("  y desmonta en cuanto acaba", [p.args for p in veracrypts()[antes:]],
  [[VC, "-d", str(HC)]])
agente.hilo = lambda funcion: funcion()

# Con avisos, «Bloquear» deja las vigilancias de la raíz antes de lanzar VeraCrypt.
F.RAICES[:] = [PUNTO]
lanzar_falso = agente.lanzar
agente.lanzar = lambda args, **kw: ORDEN.append(("lanzar", args[0])) or lanzar_falso(args, **kw)
ag7b = nuevo()
ag7b.avisos_carpeta = AvisosFalsos()
F.vueltas(ag7b, 3)
for p in F.pasadas(PUNTO):
    if p.rc is None:
        F.acabar(p, 0, "OK\n")
F.vueltas(ag7b, 2)
c("con avisos, la raíz cifrada se vigila con ellos", pedidas("vigilar", (UID7, "notas")) >= 1,
  True)
ORDEN.clear()
equipo.pedir({"pide": equipo.PIDE_BLOQUEAR, "id": UID7})
F.vueltas(ag7b, 3)
c("«Bloquear» deja las vigilancias de la raíz antes de lanzar VeraCrypt",
  [o for o in ORDEN if o == ("dejar_raiz", UID7) or o == ("lanzar", VC)][:2],
  [("dejar_raiz", UID7), ("lanzar", VC)])

raise SystemExit(c.report())
