#!/usr/bin/env python3
"""La guía de flags de rclone (`ui/flags_guia.py` y `ui/flags_catalogo.py`), sin Tk ni red.

Es la parte 3 de #95. Lo que se comprueba, y por qué:

- Que TODO lo que prdrive pone o reserva está explicado y marcado. La lista no se
  escribe aquí: sale del modelo (`BASE_FLAGS`, los flags de cada modo,
  `FLAGS_RESERVADOS`, `FLAGS_ESCRIBEN`) y de lo que `orden.tramos()` emite de verdad
  para una pareja de cada modo, de modo que un flag nuevo que ponga `sync.py` y no
  esté en la guía hace fallar este test.
- Que los textos no pueden desviarse del código: el valor de prdrive y el motivo de
  un reservado se leen del modelo, y cada ejemplo escribible pasa por el mismo
  parseo y la misma comprobación de tipo que el cuadro de la ventana.
- Que la búsqueda por texto y por efecto encuentra lo que pide una persona («qué
  hace con los borrados», «cómo ignoro ficheros temporales»).
- Que `docs/guia/flags-de-rclone.md` es exactamente lo que genera el catálogo.
"""

import re
import socket
import sys
import urllib.request
from pathlib import Path

from _harness import REPO, Checks

from common import model, orden
from ui import flags_ayuda, flags_catalogo as catalogo, flags_editor, flags_guia as guia

c = Checks("guía de flags de rclone (ui/flags_guia.py)")

DATOS = flags_ayuda.datos()
MODOS = tuple(model.MODES)


def nombres(fichas) -> list[str]:
    """Los nombres de unas fichas, en su orden."""
    return [f.nombre for f in fichas]


# ----------------------------------------------------------------------------
# Todo lo que prdrive pone o reserva está explicado y marcado
# ----------------------------------------------------------------------------

def que_emite_sync() -> set[str]:
    """Los flags que `sync.py` le pone a rclone, probando una pareja de cada modo.

    Se piden las órdenes de verdad (`orden.tramos()`), con y sin versiones, con una
    pasada normal, un simulacro y una resincronización, y con y sin fichero de
    filtros: lo que no salga por ninguna de ellas no lo pone el programa.
    """
    salida: set[str] = set()
    for modo in MODOS:
        for versiones in ((False, True) if modo == "bisync" else (False,)):
            entrada = {"name": "p", "local": "datos", "remote_path": "/R/p", "mode": modo,
                       "include": ["*.txt"], "exclude": ["*.tmp"]}
            if versiones:
                entrada["versions"] = True
            pareja = model.parse_config({"defaults": {"remote": "nas", "device_remote": "disp"},
                                         "pair": [entrada]}).pairs[0]
            for filtros in (None, Path("filtros.txt")):
                for simulacro, resync in ((False, False), (True, True)):
                    for tramo in orden.tramos(pareja, binario="rclone", filtros=filtros,
                                              config="rclone.conf", logfile="pasada.log",
                                              simulacro=simulacro, resync=resync, sello="~S"):
                        if tramo.args and tramo.args[0].startswith("--"):
                            salida.add(tramo.args[0][2:])
    # La raíz entera lleva además una regla del programa (`Pair.reglas`).
    raiz = model.parse_config({"defaults": {"remote": "nas", "device_remote": "disp"},
                               "pair": [{"name": "todo", "local": ".", "remote_path": "/R/t",
                                         "mode": "up-mirror"}]}).pairs[0]
    for tramo in orden.tramos(raiz, binario="rclone", filtros=None, config="c", logfile="l"):
        if tramo.args and tramo.args[0].startswith("--"):
            salida.add(tramo.args[0][2:])
    return salida


EMITIDOS = que_emite_sync()
c("la prueba ve lo que sync.py pone de verdad (si falla, la sonda no está probando nada)",
  {"config", "log-file", "workdir", "dry-run", "resync", "backup-dir1", "suffix", "include",
   "exclude", "filters-file", "conflict-loser", "stats", "max-delete"} <= EMITIDOS, True)

LO_DE_PRDRIVE = (set(model.BASE_FLAGS) | {n for m in model.MODES.values() for n in m.flags}
                 | set(model.FLAGS_RESERVADOS) | set(model.FLAGS_ESCRIBEN) | EMITIDOS)
SIN_EXPLICAR = sorted(n for n in LO_DE_PRDRIVE if not (guia.ficha(n) and guia.ficha(n).explicada))
c("la guía tiene una ficha EXPLICADA de cada flag que prdrive pone, reserva o rechaza",
  SIN_EXPLICAR, [])
if any(guia.ficha(n) is None for n in SIN_EXPLICAR):
    # Sin ficha no se puede comprobar nada más de ese flag: se dice cuál falta y se para aquí.
    print("  (se para) hay flags de prdrive que ni siquiera están en los datos de rclone; "
          "añádelos a common/flags_rclone.json o quítalos del modelo")
    sys.exit(c.report())

c("los reservados salen marcados «lo pone prdrive, no se puede cambiar», con el motivo del modelo",
  sorted(n for n, motivo in model.FLAGS_RESERVADOS.items()
         if (guia.ficha(n).estado, guia.ficha(n).motivo) != (guia.ESTADO_FIJO, motivo)), [])
c("  y esa marca dice lo que dice el issue",
  guia.ETIQUETA_ESTADO[guia.ESTADO_FIJO], "Lo pone prdrive, no se puede cambiar")
RECHAZADOS = [n for n in DATOS.flags if model.problema_flag(n) and n not in model.FLAGS_RESERVADOS]
c("los que el config rechaza sin ser de prdrive (programas y ficheros del equipo) existen",
  {"cpuprofile", "memprofile", "password-command", "metadata-mapper"} <= set(RECHAZADOS), True)
c("  y salen marcados como no admitidos, con el motivo del modelo",
  sorted(n for n in RECHAZADOS if (guia.ficha(n).estado, guia.ficha(n).motivo)
         != (guia.ESTADO_NO_ADMITIDO, model.problema_flag(n))), [])
c("los que prdrive pone con un valor que se puede cambiar salen como tales",
  sorted(n for n in (set(model.BASE_FLAGS) | {n for m in model.MODES.values() for n in m.flags})
         if guia.ficha(n).estado != guia.ESTADO_VALOR), [])
c("  y los demás explicados, que no son de prdrive, salen libres",
  guia.ficha("transfers").estado, guia.ESTADO_LIBRE)
c("  entre ellos el que un backup no pone solo: delete-after",
  guia.ficha("delete-after").estado, guia.ESTADO_LIBRE)

# El valor de prdrive se lee del modelo; no se escribe dos veces.
c("el valor de cada flag de la capa base sale del modelo, y en todos los modos",
  sorted(n for n, v in model.BASE_FLAGS.items()
         if flags_editor.valor_texto(v) not in guia.ficha(n).prdrive), [])
fallos = []
for modo in model.MODES.values():
    for n, v in modo.flags.items():
        texto = guia.ficha(n).prdrive
        if flags_editor.valor_texto(v) not in texto or modo.name not in texto:
            fallos.append((modo.name, n, texto))
c("el valor que trae cada modo sale del modelo, con el modo al que pertenece", fallos, [])
maximo = guia.ficha("max-delete").prdrive
c("max-delete dice sus dos valores (25 en bisync, 50 en los espejo) y a qué modo es cada uno",
  ("25" in maximo, "50" in maximo, "bisync" in maximo, "up-mirror" in maximo,
   "down-mirror" in maximo), (True,) * 5)
c("conflict-loser, que prdrive solo pone al guardar versiones, lo dice",
  ("delete" in guia.ficha("conflict-loser").prdrive
   and "versiones" in guia.ficha("conflict-loser").prdrive), True)
c("un flag que prdrive no toca no trae valor de prdrive", guia.ficha("transfers").prdrive, "")

# ----------------------------------------------------------------------------
# El modelo cambia por debajo de la guía y ella sigue diciendo la verdad
# ----------------------------------------------------------------------------

def con_el_modelo_cambiado(reservar=(), base=None):
    """Rehace las fichas con el modelo cambiado, y lo deja como estaba al salir.

    Es lo que pasa cuando otro cambio añade un flag reservado o pone uno en `BASE_FLAGS`:
    la guía lee del modelo y no puede quedarse con lo que sabía.
    """
    from contextlib import contextmanager

    @contextmanager
    def _cambio():
        reservados, base_antes = model.FLAGS_RESERVADOS, model.BASE_FLAGS
        model.FLAGS_RESERVADOS = {**reservados, **{n: "lo pone sync.py: motivo de prueba"
                                                   for n in reservar}}
        model.BASE_FLAGS = {**base_antes, **(base or {})}
        guia.reiniciar()
        try:
            yield
        finally:
            model.FLAGS_RESERVADOS, model.BASE_FLAGS = reservados, base_antes
            guia.reiniciar()
    return _cambio()


ANTES = {n: (guia.ficha(n).estado, guia.ficha(n).tema) for n in ("force", "modify-window")}
c("hoy force y modify-window son libres y cada uno de su tema",
  ANTES, {"force": (guia.ESTADO_LIBRE, guia.TEMA_BORRADO),
          "modify-window": (guia.ESTADO_LIBRE, guia.TEMA_COMPARAR)})

PAGINA_ANTES = guia.a_markdown()
with con_el_modelo_cambiado(reservar=("force",), base={"modify-window": "2s"}):
    forzado, ventana = guia.ficha("force"), guia.ficha("modify-window")
    c("si force pasa a ser un reservado, la guía lo marca así, con el motivo del modelo",
      (forzado.estado, forzado.motivo), (guia.ESTADO_FIJO, "lo pone sync.py: motivo de prueba"))
    c("  y lo pasa al tema de los que pone prdrive, sin tocar el catálogo",
      forzado.tema, guia.TEMA_PRDRIVE)
    c("  y no enseña como «en su lugar» el flag rechazado ni ningún TOML escribible",
      [t for r, t in guia.detalle(forzado) if r == guia.R_EN_SU_LUGAR and "force" in t.lower()
       and "=" in t], [])
    c("  ni el ejemplo de uno que ya no se escribe",
      guia.R_EJEMPLO in dict(guia.detalle(forzado)), False)
    c("si modify-window pasa a BASE_FLAGS, la guía dice el valor de prdrive",
      (ventana.estado, ventana.prdrive), (guia.ESTADO_VALOR, "2s en todos los modos"))
    c("  y lo pasa al tema de los que pone prdrive", ventana.tema, guia.TEMA_PRDRIVE)
    c("  y el detalle ya no dice que prdrive no lo toca",
      "no lo toca" in dict(guia.detalle(ventana))[guia.R_PRDRIVE], False)
    c("la página que genera cambia con el modelo (por eso hay que regenerarla)",
      guia.a_markdown() != PAGINA_ANTES, True)
c("y al volver el modelo a lo de antes, las fichas también",
  {n: (guia.ficha(n).estado, guia.ficha(n).tema) for n in ("force", "modify-window")}, ANTES)

# ----------------------------------------------------------------------------
# La guía y los datos de la rclone fijada no se contradicen
# ----------------------------------------------------------------------------

ENTRADAS = catalogo.ENTRADAS
c("hay explicaciones escritas a mano", len(ENTRADAS) > 60, True)
c("ninguna está dos veces", len({e.nombre for e in ENTRADAS}), len(ENTRADAS))
c("todas hablan de un flag de la rclone fijada (uno que rclone quitó o renombró hace fallar esto)",
  sorted(e.nombre for e in ENTRADAS if flags_ayuda.normalizar(e.nombre) not in DATOS.flags), [])
c("todas llevan el nombre como lo ve rclone: sin guiones y con `-`",
  sorted(e.nombre for e in ENTRADAS if e.nombre != flags_ayuda.normalizar(e.nombre)), [])
c("hay una ficha por cada flag de los datos, ni una más",
  sorted(nombres(guia.fichas())), sorted(DATOS.flags))
c("con riesgo y tema de los que existen",
  sorted(f.nombre for f in guia.fichas() if f.explicada and
         (f.riesgo not in guia.RIESGOS or f.tema not in guia.TEMAS)), [])

def modos_que_rclone_acepta(nombre: str) -> set[str]:
    """Los modos cuya orden de rclone conoce este flag, según los datos."""
    return {m.name for m in model.MODES.values() if m.verb in DATOS.flags[nombre].comandos}


c("los modos donde dice que sirve son modos que existen y cuya orden acepta el flag",
  sorted(f.nombre for f in guia.fichas() if f.explicada and not
         (set(f.modos) <= set(MODOS) and set(f.modos) <= modos_que_rclone_acepta(f.nombre)
          and f.modos)), [])
c("los que solo sincronizan (rclone los acepta al copiar y no hacen nada) no salen en up ni down",
  sorted(f.nombre for f in guia.fichas()
         if f.nombre in flags_ayuda.SOLO_SINCRONIZA and {"up", "down"} & set(f.modos)), [])
c("lo que avisa de borrado o reescritura al escribirlo nunca se clasifica de solo lectura",
  sorted(n for n in flags_ayuda.BORRADO
         if guia.ficha(n).riesgo not in (guia.RIESGO_BORRA, guia.RIESGO_NOMBRES)), [])
c("  y los que de verdad borran o sobrescriben, que la guía clasifica como tales",
  sorted(n for n in ("delete-after", "delete-before", "delete-during", "delete-excluded",
                     "ignore-errors", "force", "remove-empty-dirs", "resync-mode", "inplace",
                     "no-check-dest", "conflict-loser", "max-delete", "max-delete-size")
         if guia.ficha(n).riesgo != guia.RIESGO_BORRA), [])
c("lo que prdrive pone o reserva cuelga del tema «prdrive», y solo eso (lo decide el estado, "
  "que sale del modelo, no el catálogo)",
  sorted(f.nombre for f in guia.fichas()
         if (f.estado != guia.ESTADO_LIBRE) != (f.tema == guia.TEMA_PRDRIVE)), [])
c("lo que choca con otro, también está explicado",
  sorted(n for choque in flags_ayuda.CHOQUES for n in choque.flags
         if not guia.ficha(n).explicada), [])

# Los modos de los datos que NO están explicados se derivan de la orden de rclone.
sin_explicar = [f for f in guia.fichas() if not f.explicada]
c("hay flags sin explicación propia (el resto del fichero generado)", len(sin_explicar) > 50, True)
c("cada uno trae la ayuda corta de rclone, tal cual",
  sorted(f.nombre for f in sin_explicar if f.ayuda != DATOS.flags[f.nombre].ayuda or not f.ayuda), [])
c("  sin riesgo clasificado ni texto propio",
  sorted(f.nombre for f in sin_explicar
         if f.riesgo is not None or f.para_que or f.efecto or f.ejemplo or f.en_su_lugar
         or f.cuidado), [])
c("  y los modos donde sirven según la orden de rclone, de los datos (sin los de copiar "
  "cuando rclone solo los usa al sincronizar)",
  sorted(f.nombre for f in sin_explicar
         if set(f.modos) != modos_que_rclone_acepta(f.nombre)
         - ({"up", "down"} if f.nombre in flags_ayuda.SOLO_SINCRONIZA else set())), [])
cookies = guia.ficha("use-cookies")
c("use-cookies, que no se explica, es de «otros» y su ayuda es la de rclone, en inglés",
  (cookies.explicada, cookies.tema, "cookiejar" in cookies.ayuda), (False, guia.TEMA_OTROS, True))

# ----------------------------------------------------------------------------
# Los textos: para la persona, y los ejemplos valen
# ----------------------------------------------------------------------------

JERGA = re.compile(r"\b(baseline|BASE_FLAGS|Mode\.flags|tomllib|stdout|stderr)\b")
JERGA_PAGINA = re.compile(r"\b(BASE_FLAGS|Mode\.flags|tomllib|stdout|stderr)\b")
"""En la página de la guía vale «baseline»: es el motivo del modelo, que se cita tal cual."""
explicadas = [f for f in guia.fichas() if f.explicada]
ESCRIBIBLES = (guia.ESTADO_LIBRE, guia.ESTADO_VALOR)
c("toda ficha explicada lleva título, para qué sirve y efecto",
  sorted(f.nombre for f in explicadas if not (f.titulo and f.para_que and f.efecto)), [])
c("  y un ejemplo si se escribe (o, si no lo lleva, un cuidado que diga por qué)",
  sorted(f.nombre for f in explicadas
         if f.estado in ESCRIBIBLES and not (f.ejemplo.strip() or f.cuidado.strip())), [])
c("  o qué hacer en su lugar si no se puede escribir (lo que prdrive pone o el config rechaza)",
  sorted(f.nombre for f in explicadas
         if f.estado not in ESCRIBIBLES and not f.en_su_lugar.strip()), [])
c("  y un flag que ya no se escribe no lleva un ejemplo que copiar",
  sorted(f.nombre for f in explicadas if f.estado not in ESCRIBIBLES and f.ejemplo.strip()), [])
c("  los títulos son de una línea",
  sorted(f.nombre for f in explicadas if len(f.titulo) > 80 or "\n" in f.titulo), [])
c("  las frases acaban en punto",
  sorted(f.nombre for f in explicadas
         if not (f.para_que.endswith(".") and f.efecto.endswith("."))), [])
c("  sin jerga de quien programa: la guía es para quien usa el dispositivo",
  sorted(f.nombre for f in explicadas
         if JERGA.search(" ".join((f.titulo, f.para_que, f.efecto, f.ejemplo, f.en_su_lugar,
                                   f.cuidado)))), [])
c("  ni espacios dobles ni saltos sueltos que descuadrarían la ventana",
  sorted(f.nombre for f in explicadas
         if re.search(r"  |\n\n|^\s|\s$", " ".join((f.titulo, f.para_que, f.efecto)))), [])

mal = []
for f in explicadas:
    if f.estado not in (guia.ESTADO_LIBRE, guia.ESTADO_VALOR) or not f.ejemplo.strip():
        continue                                    # un reservado no se escribe; force no da ejemplo
    try:
        escrito = flags_editor.parse(f.ejemplo)
    except model.ConfigError as e:
        mal.append((f.nombre, f"no se admite: {e}"))
        continue
    if [flags_ayuda.normalizar(k) for k in escrito] != [f.nombre]:
        mal.append((f.nombre, f"el ejemplo escribe {sorted(escrito)}"))
    for valor in escrito.values():
        motivo = flags_ayuda.problema_valor(f.nombre, valor)
        if motivo:
            mal.append((f.nombre, motivo))
c("el ejemplo de cada flag que se puede escribir es TOML que el cuadro admite, de ese flag y "
  "con un valor del tipo que rclone espera", mal, [])
c("un flag que se puede escribir sin ejemplo es porque copiarlo sería un error, y dice por qué",
  sorted(f.nombre for f in explicadas if f.estado in (guia.ESTADO_LIBRE, guia.ESTADO_VALOR)
         and not f.ejemplo.strip() and not f.cuidado.strip()), [])
c("force no ofrece ejemplo: en una pareja valdría para TODAS las pasadas, también las que nadie "
  "vigila, y quitaría el freno de los borrados en cada una",
  (guia.ficha("force").ejemplo, "todas las pasadas" in guia.ficha("force").cuidado,
   guia.ficha("force").cuidado in dict(guia.detalle(guia.ficha("force")))[guia.R_CUIDADO]),
  ("", True, True))
c("  y la página tampoco lo enseña como algo que escribir",
  "`force = true`" in guia.a_markdown(), False)
c("ningún ejemplo de la guía es un flag que quite un freno de seguridad de una pasada normal",
  [f.nombre for f in explicadas if f.ejemplo.strip() and
   flags_ayuda.normalizar(f.ejemplo.split("=")[0]) in ("force", "ignore-errors")], [])
c("el de un reservado no se escribe: dice qué usar en su lugar",
  sorted(f.nombre for f in explicadas if f.estado in (guia.ESTADO_FIJO, guia.ESTADO_NO_ADMITIDO)
         and not f.en_su_lugar.strip()), [])


def parsear(ejemplo: str) -> dict:
    """Lo que escribe un ejemplo; `{}` si no se admite (la comprobación de arriba ya lo dijo)."""
    try:
        return flags_editor.parse(ejemplo)
    except model.ConfigError:
        return {}


c("los avisos de la ventana se pueden pedir de cada ejemplo sin que salte nada",
  all(isinstance(flags_ayuda.avisos("bisync", {}, parsear(f.ejemplo)), list)
      for f in explicadas if f.estado in (guia.ESTADO_LIBRE, guia.ESTADO_VALOR)), True)

# ----------------------------------------------------------------------------
# Buscar
# ----------------------------------------------------------------------------

todas = guia.buscar()
c("sin nada que buscar salen todas, una vez cada una",
  (len(todas), len(set(nombres(todas)))), (len(guia.fichas()), len(guia.fichas())))
c("  las explicadas primero",
  nombres(todas)[:len([f for f in todas if f.explicada])] == nombres(
      [f for f in todas if f.explicada]), True)
c("  y siempre en el mismo orden", nombres(guia.buscar()), nombres(todas))
c("una búsqueda solo de palabras de relleno equivale a no buscar nada",
  nombres(guia.buscar("qué hace con los")), nombres(todas))
c("  y una vacía o de espacios", (nombres(guia.buscar("")), nombres(guia.buscar("   \t"))),
  (nombres(todas), nombres(todas)))

# Por nombre
c("por el nombre exacto sale primero", guia.buscar("transfers")[0].nombre, "transfers")
c("  con los guiones de delante, en mayúsculas y con `_`, como se escribe en el TOML",
  [guia.buscar(q)[0].nombre for q in ("--max-delete", "MAX_DELETE", "Max-Delete")],
  ["max-delete"] * 3)
c("  y el que empieza igual va después que el exacto",
  nombres(guia.buscar("max-delete"))[:2], ["max-delete", "max-delete-size"])
c("por un trozo del nombre salen los que lo contienen",
  {"max-transfer", "transfers"} <= set(nombres(guia.buscar("transfer"))), True)
c("  los que empiezan primero", guia.buscar("transfer")[0].nombre, "transfers")
c("sin tildes ni mayúsculas da igual",
  nombres(guia.buscar("TIEMPO DE ESPERA")), nombres(guia.buscar("tiempo de espera")))
c("  y con tildes tampoco", nombres(guia.buscar("cómo ignoro")), nombres(guia.buscar("como ignoro")))
c("lo que no existe no devuelve nada, sin lanzar", guia.buscar("zzzqqqxx"), [])
for raro in ("(", "[a-", "*", "\\", "a" * 5000, "\x00", "ñandú ¿?", "--", "-"):
    try:
        guia.buscar(raro)
        guia.buscar(raro, riesgo=guia.RIESGO_BORRA)
        ok = True
    except Exception as e:                          # noqa: BLE001 — se quiere saber cuál
        ok = repr(e)
    c(f"una búsqueda rara no tumba nada ({raro[:12]!r})", ok, True)

# Por efecto: lo que se pregunta con palabras de la persona
borrados = nombres(guia.buscar("qué hace con los borrados"))
c("«qué hace con los borrados» encuentra los de borrado y su freno en los primeros",
  {"delete-after", "delete-during", "delete-before", "delete-excluded", "max-delete",
   "max-delete-size"} <= set(borrados[:12]), True)
temporales = nombres(guia.buscar("cómo ignoro ficheros temporales"))
c("«cómo ignoro ficheros temporales» da primero el que excluye (el cuadro «Excluir»)",
  temporales[0], "exclude")
c("  y cerca los que ayudan a lo mismo", {"exclude-from", "exclude-if-present"} <= set(temporales[:6]),
  True)
for pregunta, esperado, hasta in (
        ("limitar la velocidad de subida", "bwlimit", 1),
        ("cuántos ficheros a la vez", "transfers", 3),
        ("cuánto espera antes de rendirse", "timeout", 5),
        ("no copiar ficheros muy grandes", "max-size", 3),
        ("ignorar los ficheros antiguos", "min-age", 5),
        ("qué pasa si cambio un fichero en los dos lados", "conflict-resolve", 3),
        ("probar sin cambiar nada", "dry-run", 3),
        ("reintentar si falla", "retries", 3)):
    c(f"«{pregunta}» → {esperado} entre los {hasta} primeros",
      esperado in nombres(guia.buscar(pregunta))[:hasta], True)
c("un flag sin explicación propia se encuentra por la ayuda de rclone, en inglés",
  "use-cookies" in nombres(guia.buscar("cookiejar")), True)

# Filtros
bor = guia.buscar("", riesgo=guia.RIESGO_BORRA)
c("filtrar por riesgo «borra» deja solo los que borran o reescriben, y hay varios",
  (len(bor) > 10, {f.riesgo for f in bor}), (True, {guia.RIESGO_BORRA}))
c("  los de solo lectura no incluyen ninguno de esos",
  {f.nombre for f in guia.buscar("", riesgo=guia.RIESGO_LEE)} & {f.nombre for f in bor}, set())
c("  los que no tienen riesgo clasificado no salen con un filtro de riesgo",
  [f.nombre for f in guia.buscar("", riesgo=guia.RIESGO_LEE) if not f.explicada], [])
c("  y «cambia nombres» tiene al menos conflict-suffix y name-transform",
  {"conflict-suffix", "name-transform"} <= {f.nombre for f in
                                            guia.buscar("", riesgo=guia.RIESGO_NOMBRES)}, True)
solo_up = {f.nombre for f in guia.buscar("", modo="up")}
solo_bisync = {f.nombre for f in guia.buscar("", modo="bisync")}
solo_espejo = {f.nombre for f in guia.buscar("", modo="up-mirror")}
c("filtrar por modo: resilient es de bisync y de ningún otro",
  ("resilient" in solo_bisync, "resilient" in solo_up, "resilient" in solo_espejo),
  (True, False, False))
c("  delete-after solo sirve donde se sincroniza (los espejo), no al copiar ni en bisync",
  ("delete-after" in solo_espejo, "delete-after" in solo_up, "delete-after" in solo_bisync),
  (True, False, False))
c("  y transfers, de todos", all("transfers" in {f.nombre for f in guia.buscar("", modo=m)}
                                for m in MODOS), True)
c("filtrar por tema deja los de ese tema, y timeout es de «tiempos»",
  ({f.tema for f in guia.buscar("", tema=guia.TEMA_TIEMPOS) if f.explicada},
   "timeout" in {f.nombre for f in guia.buscar("", tema=guia.TEMA_TIEMPOS)}),
  ({guia.TEMA_TIEMPOS}, True))
c("«solo con explicación» quita el resto", all(f.explicada for f in
                                                 guia.buscar("", solo_explicadas=True)), True)
c("los filtros se juntan con la búsqueda",
  nombres(guia.buscar("borrar", modo="up")) == [n for n in nombres(guia.buscar("borrar"))
                                                if n in solo_up], True)
c("un filtro que no existe no devuelve nada, sin lanzar",
  (guia.buscar("", riesgo="x"), guia.buscar("", modo="x"), guia.buscar("", tema="x")),
  ([], [], []))

# ----------------------------------------------------------------------------
# Lo que enseña la ventana de cada flag
# ----------------------------------------------------------------------------

def rotulos(f) -> list[str]:
    """Los rótulos de `guia.detalle(f)`, en orden."""
    return [r for r, _t in guia.detalle(f)]


libre = guia.detalle(guia.ficha("transfers"))
c("el detalle de un flag libre trae lo que pide el issue: para qué sirve, efecto, riesgo, modos, "
  "valor de prdrive y ejemplo",
  {guia.R_PARA_QUE, guia.R_EFECTO, guia.R_RIESGO, guia.R_MODOS, guia.R_PRDRIVE,
   guia.R_EJEMPLO} <= set(rotulos(guia.ficha("transfers"))), True)
c("  el riesgo con palabras de la persona", dict(libre)[guia.R_RIESGO],
  guia.ETIQUETAS_RIESGO[guia.ficha("transfers").riesgo])
c("  el valor de fábrica de rclone y su ayuda, también",
  "4" in dict(libre)[guia.R_RCLONE] and "parallel" in dict(libre)[guia.R_RCLONE], True)
fijo = dict(guia.detalle(guia.ficha("workdir")))
c("el de un reservado lo marca como de prdrive y dice el motivo",
  (guia.ETIQUETA_ESTADO[guia.ESTADO_FIJO] in fijo[guia.R_ESTADO],
   model.FLAGS_RESERVADOS["workdir"] in fijo[guia.R_ESTADO]), (True, True))
no_adm = dict(guia.detalle(guia.ficha("cpuprofile")))
c("el de uno que el config rechaza, también",
  (guia.ETIQUETA_ESTADO[guia.ESTADO_NO_ADMITIDO] in no_adm[guia.R_ESTADO],
   model.problema_flag("cpuprofile") in no_adm[guia.R_ESTADO]), (True, True))
sin = dict(guia.detalle(guia.ficha("use-cookies")))
c("el de uno sin explicación propia lo dice y marca la ayuda de rclone como inglés",
  (guia.R_PARA_QUE in sin, guia.R_RCLONE in sin, "sin explicación" in sin[guia.R_ESTADO].lower(),
   "inglés" in guia.R_RCLONE), (False, True, True, True))
c("un flag que prdrive pone muestra su valor", "2s" in dict(guia.detalle(guia.ficha("stats")))[
    guia.R_PRDRIVE], True)
c("ningún detalle sale con un texto vacío",
  [f.nombre for f in guia.fichas() for _r, t in guia.detalle(f) if not t.strip()], [])

# Con la pareja delante, el detalle dice si el flag sirve en su modo.
c("un flag que sirve en el modo de la pareja lo dice",
  dict(guia.detalle(guia.ficha("delete-after"), "up-mirror"))[guia.R_TU_PAREJA],
  "Sí, sirve en tu pareja (up-mirror).")
c("  y uno que no, también",
  dict(guia.detalle(guia.ficha("resilient"), "up-mirror"))[guia.R_TU_PAREJA],
  "No sirve en tu pareja (up-mirror).")
c("  y sin pareja (los flags comunes de [defaults]) no se dice nada de ella",
  guia.R_TU_PAREJA in dict(guia.detalle(guia.ficha("resilient"), None)), False)
c("  lo mismo con uno sin explicación propia",
  dict(guia.detalle(guia.ficha("use-cookies"), "bisync"))[guia.R_TU_PAREJA],
  "Sí, sirve en tu pareja (bisync).")
c("sirve_en: sin modo sirve en todos; con él, según los modos de la ficha",
  (guia.sirve_en(guia.ficha("resilient"), None), guia.sirve_en(guia.ficha("resilient"), "bisync"),
   guia.sirve_en(guia.ficha("resilient"), "down")), (True, True, False))
c("un modo que no existe no sirve en ninguno", guia.sirve_en(guia.ficha("transfers"), "x"), False)

# ----------------------------------------------------------------------------
# De qué flag se habla desde el editor
# ----------------------------------------------------------------------------

TEXTO = 'transfers = 4\nmax-delete = 10\n\n# nota\nconflict-resolve = "newer"'
c("con el cursor en la línea de un flag, ese flag",
  guia.flag_de_la_linea(TEXTO, TEXTO.index("max-delete") + 3), "max-delete")
c("  también si el cursor está en el valor", guia.flag_de_la_linea(TEXTO, TEXTO.index("= 10") + 3),
  "max-delete")
c("  y al principio o al final de la línea",
  (guia.flag_de_la_linea(TEXTO, 0), guia.flag_de_la_linea(TEXTO, len("transfers = 4"))),
  ("transfers", "transfers"))
c("en una línea en blanco o en un comentario, ninguno",
  (guia.flag_de_la_linea(TEXTO, TEXTO.index("\n\n") + 1),
   guia.flag_de_la_linea(TEXTO, TEXTO.index("# nota") + 2)), ("", ""))
c("con _ o mayúsculas lo da como lo ve rclone",
  guia.flag_de_la_linea("Max_Delete = 3", 2), "max-delete")
c("sin texto, o con el cursor fuera, ninguno",
  (guia.flag_de_la_linea("", 0), guia.flag_de_la_linea(TEXTO, 9999),
   guia.flag_de_la_linea(TEXTO, -5)), ("", "conflict-resolve", "transfers"))

# ----------------------------------------------------------------------------
# docs/guia: la misma información, sin desviarse
# ----------------------------------------------------------------------------

PAGINA = REPO / "docs" / "guia" / "flags-de-rclone.md"
generada = guia.a_markdown()
c("la página se genera siempre igual", guia.a_markdown(), generada)
c("docs/guia/flags-de-rclone.md es EXACTAMENTE lo que genera el catálogo "
  "(si falla: python generar_guia_flags.py)",
  PAGINA.read_text(encoding="utf-8") if PAGINA.is_file() else None, generada)
c("la página termina con un salto de línea y no lleva espacios sobrantes",
  (generada.endswith("\n") and not generada.endswith("\n\n"),
   [i for i, linea in enumerate(generada.split("\n")) if linea != linea.rstrip()]), (True, []))
c("cada flag explicado tiene su apartado, con la marca de lo que es",
  sorted(f.nombre for f in explicadas if f"### `--{f.nombre}`" not in generada), [])
c("cada flag sin explicación sale en la tabla de los de rclone, con su ayuda en inglés "
  "(el `|` de una celda va escapado para no partir la fila)",
  sorted(f.nombre for f in sin_explicar
         if not re.search(rf"^\| `--{re.escape(f.nombre)}` \|.*"
                          rf"{re.escape(f.ayuda.replace('|', chr(92) + '|'))}",
                          generada, re.M)), [])
c("  y una vez cada uno", sorted(
    n for n in DATOS.flags if len(re.findall(rf"^(?:### |\| )`--{re.escape(n)}`", generada,
                                             re.M)) != 1), [])
c("la página lleva las marcas, para quien no abre el programa",
  all(m in generada for m in (guia.ETIQUETA_ESTADO[guia.ESTADO_FIJO],
                              guia.ETIQUETA_ESTADO[guia.ESTADO_NO_ADMITIDO],
                              *guia.ETIQUETAS_RIESGO.values())), True)
c("  y dice con qué rclone se hizo", f"rclone {DATOS.rclone}" in generada, True)
c("  sin jerga de quien programa (el motivo del modelo se cita tal cual)",
  JERGA_PAGINA.search(generada), None)
c("la página vuelve a la guía y se enlaza desde configuración y desde el índice",
  ("(README.md)" in generada,
   "flags-de-rclone.md" in (REPO / "docs/guia/configuracion.md").read_text(encoding="utf-8"),
   "flags-de-rclone.md" in (REPO / "docs/guia/README.md").read_text(encoding="utf-8")),
  (True, True, True))

# ----------------------------------------------------------------------------
# Sin Tk, sin red y fuera de la ventana principal
# ----------------------------------------------------------------------------

c("la lógica no importa tkinter",
  [m for m in ("tkinter", "ui.tk", "ui.theme") if m in sys.modules], [])
for modulo in ("flags_guia.py", "flags_catalogo.py"):
    codigo = (REPO / "ui" / modulo).read_text(encoding="utf-8")
    c(f"ui/{modulo} no menciona tkinter ni la red",
      re.findall(r"\b(?:import tkinter|from tkinter|import socket|import urllib|import http)\b",
                 codigo), [])


def sin_red(*_a, **_k):
    """Lo que haría cualquier intento de salir a la red durante este tramo."""
    raise AssertionError("la guía de flags ha intentado usar la red")


real = (socket.socket, socket.create_connection, urllib.request.urlopen)
socket.socket = socket.create_connection = urllib.request.urlopen = sin_red
try:
    guia.buscar("borrados")
    guia.a_markdown()
    ok = True
except AssertionError as e:
    ok = str(e)
finally:
    socket.socket, socket.create_connection, urllib.request.urlopen = real
c("buscar y generar la página funcionan con los sockets cortados", ok, True)

c("la ventana principal no sabe que existe la guía: se abre desde «Avanzado» de la pareja",
  sorted(m for m in ("tk.py", "tk_principal.py", "principal.py", "instantanea.py", "__init__.py")
         if re.search(r"flags_guia|flags_catalogo", (REPO / "ui" / m).read_text(encoding="utf-8"))),
  [])

sys.exit(c.report())
