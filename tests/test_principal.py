#!/usr/bin/env python3
"""Lo que enseña y deja pulsar la ventana principal, sin Tk (`ui/principal.py`).

Dos cosas se prueban aquí como tablas, sin abrir ninguna ventana:

- `estado()`: de lo que se sabe (el config, las horas, la lectura del
  dispositivo) a lo que dice cada bloque. Los textos son los que `render()` de
  la ventana escribía, movidos tal cual.
- `controles()`: la tabla de «desactivado ⇔ ocupado». Ningún control que toca
  `state/` se puede pulsar mientras se sincroniza, ni los que necesitan la
  lectura mientras no ha llegado.

La lectura (`ui.instantanea.Instantanea`) la hace otra tarea: aquí se sustituye
por un `SimpleNamespace` con sus mismos campos, que es todo lo que `estado()`
mira.
"""

import ast
import dataclasses
import itertools
import json
import subprocess
import sys
import time
from types import SimpleNamespace

from _harness import REPO, Checks, mkcfg

from common import model, update
from ui import cuando, llavero_editor, principal, watch

c = Checks("ventana principal sin Tk (ui/principal.py)")


# ---------------------------------------------------------------------------
# Lo que importa el módulo: tiene que poder cargarse antes del primer pintado.
# ---------------------------------------------------------------------------

PESADOS = ("common.components", "common.conflicts", "common.revision", "common.fleet",
           "common.bisync", "common.results", "common.llavero", "common.keepassxc",
           "common.update", "penwatch", "tkinter", "ui.watch", "ui.llavero_editor")
"""Lo que `import ui.principal` y un `estado()` sin lectura no pueden traer."""

CONFIG_DEL_HIJO = (
    "model.parse_config({'defaults': {'remote': 'nas'}, 'pair': ["
    "{'name': 'a', 'local': 'sync-data/a', 'remote_path': '/R/a'}]})")


def en_proceso_limpio(codigo: str) -> dict:
    """Ejecuta `codigo` en un intérprete nuevo y devuelve el JSON que imprime."""
    proc = subprocess.run([sys.executable, "-c", codigo], cwd=str(REPO), capture_output=True,
                          text=True, timeout=120)
    if proc.returncode:
        print(proc.stderr)
    return json.loads(proc.stdout)


tras_import = en_proceso_limpio(
    "import json, sys; import ui.principal; print(json.dumps(sorted(sys.modules)))")
c("import ui.principal: no carga nada de lo pesado ni Tk",
  sorted(set(PESADOS) & set(tras_import)), [])

PRIMER_PINTADO = en_proceso_limpio(f"""
import json, sys
from common import model
from ui import principal
cfg = {CONFIG_DEL_HIJO}
principal.estado(cfg, aviso=None, nueva=None, instalada=None, tiempos={{}}, marcadas=(),
                 en_curso=False, inst=None)
print(json.dumps(sorted(sys.modules)))
""")
c("estado() sin lectura (el primer pintado): tampoco",
  sorted(set(PESADOS) & set(PRIMER_PINTADO)), [])

SIN_LLAVERO = en_proceso_limpio(f"""
import json, sys
from types import SimpleNamespace
from common import model
from ui import principal, watch
cfg = {CONFIG_DEL_HIJO}
inst = SimpleNamespace(notas={{}}, cuenta=0, conflictos={{}}, componentes_texto=None,
                       componentes_actualizables=False, expulsion=None, bloqueo=None,
                       del_equipo=False, llavero=None, vigilante=watch.Resumen("sin_instalar"))
principal.estado(cfg, aviso=None, nueva=None, instalada=None, tiempos={{}}, marcadas=(),
                 en_curso=False, inst=inst)
print(json.dumps(sorted(sys.modules)))
""")
c("estado() con lectura y sin llavero: no importa llavero_editor",
  "ui.llavero_editor" in SIN_LLAVERO, False)

CON_LLAVERO = en_proceso_limpio(f"""
import json, sys
from types import SimpleNamespace
from common import model
from ui import principal, watch
cfg = {CONFIG_DEL_HIJO}
inst = SimpleNamespace(notas={{}}, cuenta=0, conflictos={{}}, componentes_texto=None,
                       componentes_actualizables=False, expulsion=None, bloqueo=None,
                       del_equipo=False, vigilante=watch.Resumen("sin_instalar"),
                       llavero=SimpleNamespace(texto="x", aviso=False, abrir=True))
principal.estado(cfg, aviso=None, nueva=None, instalada=None, tiempos={{}}, marcadas=(),
                 en_curso=False, inst=inst)
print(json.dumps(sorted(sys.modules)))
""")
c("  y con la línea del llavero sí, que es cuando la necesita",
  "ui.llavero_editor" in CON_LLAVERO, True)


def importados_arriba(ruta: str) -> list[tuple[str, str]]:
    """Devuelve `(módulo, nombre)` de lo que importa el cuerpo del módulo, sin sus funciones."""
    arbol = ast.parse((REPO / ruta).read_text(encoding="utf-8"))
    salida = []
    for nodo in arbol.body:
        if isinstance(nodo, ast.Import):
            salida += [(a.name, "") for a in nodo.names]
        elif isinstance(nodo, ast.ImportFrom):
            salida += [("." * nodo.level + (nodo.module or ""), a.name) for a in nodo.names]
    return salida


PERMITIDOS = {("__future__", "annotations"), ("dataclasses", "dataclass"),
              ("typing", "TYPE_CHECKING"), ("typing", "Collection"), ("typing", "Mapping"),
              ("typing", "NamedTuple"), ("common", "model"), (".", "cuando")}
"""Los únicos imports de arriba.

La biblioteca estándar, el `model` que ya carga `ui.prefs` y el `ui.cuando` del paquete.
"""
c("el cuerpo del módulo solo importa lo permitido (watch y llavero_editor, dentro de estado())",
  sorted(set(importados_arriba("ui/principal.py")) - PERMITIDOS), [])

c("principal.INICIAR es el watch.INICIAR (duplicado a propósito)",
  principal.INICIAR, watch.INICIAR)
c("  el botón del llavero dice lo de siempre", llavero_editor.ABRIR, "Abrir llavero")
c("  y el del servicio sin agente, también",
  watch.boton_servicio(watch.Resumen("sin_instalar")),
  watch.BotonServicio("Iniciar servicio", watch.INICIAR))


# ---------------------------------------------------------------------------
# Material de las pruebas.
# ---------------------------------------------------------------------------

CFG = mkcfg(["docs", "fotos", "claves"], pairs=[
    {"name": "docs", "local": "sync-data/docs", "remote_path": "/R/docs", "mode": "bisync"},
    {"name": "fotos", "local": "sync-data/fotos", "remote_path": "/R/fotos", "mode": "up"},
    {"name": "claves", "local": "sync-data/claves", "remote_path": "/R/claves",
     "mode": "down-mirror", "remote": "otro"}])
UNA = mkcfg(["docs"])
LLAVERO = model.parse_config({
    "defaults": {"remote": "nas"}, "keychain": {"base": "personal.kdbx"},
    "pair": [{"name": "docs", "local": "sync-data/docs", "remote_path": "/R/docs"}]})

AHORA = time.time()
AYER = AHORA - 36 * 3600
HACE_UN_RATO = AHORA - 3600
"""Marcas de tiempo para `tiempos`; el texto lo da `ui.cuando`, que es el de la ventana."""

RELEASE = update.Release("v0.9.0", "0.9.0", "Nueva", "https://example.invalid/r", "2026-10-01")
SIN_INSTALAR = watch.Resumen("sin_instalar")


def lectura(**cambios) -> SimpleNamespace:
    """Una lectura sin nada que decir, con los campos de `Instantanea` que lee `estado()`."""
    campos = dict(notas={}, cuenta=0, conflictos={}, componentes=(), componentes_texto=None,
                  componentes_actualizables=False, expulsion=None, bloqueo=None,
                  del_equipo=False, llavero=None, vigilante=SIN_INSTALAR)
    campos.update(cambios)
    return SimpleNamespace(**campos)


def estado(config=CFG, **cambios) -> principal.Estado:
    """`principal.estado()` con valores neutros para lo que cada prueba no toca."""
    args = dict(aviso=None, nueva=None, instalada="0.8.0", tiempos={}, marcadas=(),
                en_curso=False, inst=lectura(), vigilante=None)
    args.update(cambios)
    return principal.estado(config, **args)


# ---------------------------------------------------------------------------
# Los textos.
# ---------------------------------------------------------------------------

lleno = estado()
c("Estado es un valor: dos iguales son iguales y se pueden juntar",
  (lleno == estado(), hash(lleno) == hash(estado()), len({lleno, estado()})), (True, True, 1))
try:
    lleno.chip = ("x", "", None)
    congelado = False
except dataclasses.FrozenInstanceError:
    congelado = True
c("  y no se puede tocar", congelado, True)
c("  uno con algo distinto no lo es", estado(aviso="otro") == lleno, False)

# La cabecera: los dos textos cortos de siempre.
c("dispositivo: la raíz del dispositivo", lleno.dispositivo, principal.corto(str(model.DEVICE_ROOT)))
c("remotos: los de las parejas, sin repetir y ordenados", lleno.remotos, "nas, otro")
c("  con una sola pareja, su remoto", estado(UNA).remotos, "nas")
sin_parejas = SimpleNamespace(pairs=(), names=[], del_usuario=())
c("  y sin parejas, el remoto de fábrica", estado(sin_parejas).remotos, model.DEFAULT_REMOTE)
c("corto: lo que cabe se queda", principal.corto("F:\\"), "F:\\")
c("  lo que no, se recorta por delante, que es por donde sobra",
  (principal.corto("x" * 40), len(principal.corto("x" * 40))), ("…" + "x" * 29, 30))
c("  con otro máximo", principal.corto("abcdefghij", 5), "…ghij")
c("la pareja del llavero cuenta para los remotos pero no es una fila",
  (estado(LLAVERO).remotos, [f.nombre for f in estado(LLAVERO).filas]), ("nas", ["docs"]))

# El chip de la cabecera, en sus cuatro casos, y quién gana si coinciden.
c("chip: al día", lleno.chip, ("al día", "Ok.", "ok"))
c("  con una cosa que revisar", estado(inst=lectura(cuenta=1)).chip,
  ("1 que revisar", "Aviso.", "warn"))
c("  con varias", estado(inst=lectura(cuenta=3)).chip, ("3 que revisar", "Aviso.", "warn"))
c("  sincronizando", estado(en_curso=True).chip, ("sincronizando…", "Acento.", "sync"))
c("  sincronizar gana a lo que haya que revisar",
  estado(en_curso=True, inst=lectura(cuenta=3)).chip, ("sincronizando…", "Acento.", "sync"))
c("  mientras llega la lectura, una píldora neutra", estado(inst=None).chip, ("…", "", None))
c("  y una pasada en curso se dice aunque aún no haya lectura",
  estado(inst=None, en_curso=True).chip, ("sincronizando…", "Acento.", "sync"))

# El aviso de arranque.
c("aviso: sin él, nada", (lleno.aviso, estado(aviso="").aviso), (None, None))
c("  con él, el texto", estado(aviso="Servicio anterior (pid 4242) detenido.").aviso,
  "Servicio anterior (pid 4242) detenido.")

# La línea de «Reparación…».
c("reparacion: la cuenta de la lectura", (lleno.reparacion, estado(inst=lectura(cuenta=2)).reparacion),
  (0, 2))
c("  y 0 mientras no hay lectura, aunque se sepa algo", estado(inst=None).reparacion, 0)
c("frase de la línea: una cosa", principal.frase_reparacion(1), "Hay 1 cosa que revisar.")
c("  varias", principal.frase_reparacion(4), "Hay 4 cosas que revisar.")

# La versión nueva y los componentes: el aviso de versión tapa al de componentes.
COMPONENTES = dict(componentes=("rclone",), componentes_texto="rclone: 1.60 en vez de 1.70",
                   componentes_actualizables=True)
c("version: sin release, nada", (lleno.version, lleno.componentes, lleno.componentes_boton),
  (None, None, False))
c("  con release, el bloque de siempre",
  estado(nueva=RELEASE).version,
  "Hay una actualización: v0.9.0\nTienes la 0.8.0. «Actualizar…» baja la versión nueva "
  "y reabre la ventana.")
c("  y sin versión instalada, «desconocida»",
  ("Tienes la desconocida." in estado(nueva=RELEASE, instalada=None).version,
   "Tienes la desconocida." in estado(nueva=RELEASE, instalada="").version), (True, True))
c("  se ve también mientras llega la lectura (sale de la caché)",
  estado(nueva=RELEASE, inst=None).version is not None, True)
c("componentes: el texto de siempre y el botón",
  (estado(inst=lectura(**COMPONENTES)).componentes,
   estado(inst=lectura(**COMPONENTES)).componentes_boton),
  ("Lo que lleva el dispositivo de fuera (rclone, Python, VeraCrypt) no es lo que fija "
   "esta versión:\nrclone: 1.60 en vez de 1.70", True))
c("  sin botón si ninguno se puede poner al día",
  (estado(inst=lectura(**{**COMPONENTES, "componentes_actualizables": False})).componentes
   is not None,
   estado(inst=lectura(**{**COMPONENTES, "componentes_actualizables": False})).componentes_boton),
  (True, False))
con_version = estado(nueva=RELEASE, inst=lectura(**COMPONENTES))
c("  una release lo esconde (y su botón)",
  (con_version.version is not None, con_version.componentes, con_version.componentes_boton),
  (True, None, False))
c("  y no hay hasta que llega la lectura",
  (estado(inst=None).componentes, estado(inst=None).componentes_boton), (None, False))

# Las filas: nombre, modo, hora y chip.
c("filas: una por pareja del usuario, en su orden, con su modo",
  [(f.nombre, f.modo) for f in lleno.filas],
  [("docs", "bisync"), ("fotos", "up"), ("claves", "down-mirror")])
c("  sin hora, un guion", [f.cuando for f in lleno.filas], ["—", "—", "—"])
c("  con hora, la de la ventana",
  [f.cuando for f in estado(tiempos={"docs": HACE_UN_RATO, "fotos": AYER}).filas],
  [cuando(HACE_UN_RATO), cuando(AYER), "—"])
c("  una hora de 0 o None es no haber corrido",
  [f.cuando for f in estado(tiempos={"docs": 0, "fotos": None}).filas], ["—", "—", "—"])
c("  sin chips si no hay nada que decir", [f.chip for f in lleno.filas], [None, None, None])
c("  la nota de «requiere resync» es un chip de aviso",
  [f.chip for f in estado(inst=lectura(notas={"fotos": "requiere resync"})).filas],
  [None, ("requiere resync", "Aviso."), None])
c("  los conflictos, uno o varios",
  [f.chip for f in estado(inst=lectura(conflictos={"docs": 1, "claves": 3})).filas],
  [("1 conflicto", "Aviso."), None, ("3 conflictos", "Aviso.")])
c("  la nota gana a los conflictos de la misma pareja",
  estado(inst=lectura(notas={"docs": "requiere resync"}, conflictos={"docs": 2})).filas[0].chip,
  ("requiere resync", "Aviso."))
c("  los conflictos de una pareja que ya no está no salen",
  [f.chip for f in estado(inst=lectura(conflictos={"vieja": 2})).filas], [None, None, None])
c("  mientras llega la lectura no hay chips",
  [f.chip for f in estado(inst=None, tiempos={"docs": AHORA}).filas], [None, None, None])
c("  y las horas sí, que salen de lo guardado",
  estado(inst=None, tiempos={"docs": HACE_UN_RATO}).filas[0].cuando, cuando(HACE_UN_RATO))

# «Última pasada»: la más reciente de todas.
c("ultima: sin pasadas, nada", (lleno.ultima, estado(tiempos={"docs": None}).ultima), ("", ""))
c("  la más reciente",
  estado(tiempos={"docs": AYER, "fotos": HACE_UN_RATO, "claves": None}).ultima,
  f"última pasada {cuando(HACE_UN_RATO)}")

# Qué casillas nacen marcadas.
c("marcadas: las que se dan, como conjunto",
  (estado(marcadas=["docs", "claves"]).marcadas, estado(marcadas=()).marcadas),
  (frozenset({"docs", "claves"}), frozenset()))

# La línea del llavero.
c("llavero: sin él, nada", lleno.llavero, None)
c("  con él, su texto, ámbar si avisa, y el botón de siempre",
  (estado(LLAVERO, inst=lectura(llavero=llavero_editor.Linea("base, al día.", False, True))).llavero,
   estado(LLAVERO, inst=lectura(llavero=llavero_editor.Linea("falla", True, False))).llavero),
  (principal.Linea("base, al día.", False, "Abrir llavero", True),
   principal.Linea("falla", True, "Abrir llavero", False)))
c("  y mientras llega la lectura, nada", estado(LLAVERO, inst=None).llavero, None)

# El arranque automático, su frase de pausa y el botón del servicio salen de `watch`.
INSTALADO = watch.Resumen("instalado", modo="daemon")
AGENTE = watch.Resumen("agente_raiz", modo="daemon", vivo=True)
AGENTE_PAUSADA = watch.Resumen("agente_raiz", modo="daemon", vivo=True, pausada=True)
AGENTE_PAUSADO = watch.Resumen("agente_raiz", modo="daemon", vivo=True, pausado=True)
AGENTE_PARADO = watch.Resumen("agente_raiz", modo="daemon", vivo=False)
for nombre, res in (("sin vigilante", SIN_INSTALAR), ("vigilante instalado", INSTALADO),
                    ("agente", AGENTE), ("agente en pausa desde la ventana", AGENTE_PAUSADA),
                    ("agente en pausa de la bandeja", AGENTE_PAUSADO),
                    ("agente parado", AGENTE_PARADO),
                    ("sin saber", watch.Resumen("no_disponible"))):
    e = estado(inst=lectura(vigilante=res))
    dicho = watch.linea(res)
    boton = watch.boton_servicio(res)
    c(f"{nombre}: la línea es la de watch.linea",
      e.arranque, None if dicho is None else principal.Linea(dicho.texto, dicho.aviso,
                                                             dicho.boton, True))
    c("  la frase de pausa, la de watch.pausa (solo si hay línea)",
      e.pausa, None if dicho is None else watch.pausa(res))
    c("  el servicio, el de watch.boton_servicio", e.servicio, (boton.accion, boton.texto))
c("arranque: lo que dice de un vigilante instalado, tal cual",
  (estado(inst=lectura(vigilante=INSTALADO)).arranque,
   estado(inst=lectura(vigilante=INSTALADO)).pausa),
  (principal.Linea("Al enchufarlo en este equipo: arranca el servicio.", False, "Cambiar…", True),
   "En pausa mientras esta ventana esté abierta."))
c("  sin vigilante, la línea para configurarlo y nada que pausar",
  (lleno.arranque, lleno.pausa),
  (principal.Linea("En este equipo no se arranca nada al enchufarlo.", False, "Configurar…",
                   True), None))
c("  si no se sabe, ni línea ni frase",
  (estado(inst=lectura(vigilante=watch.Resumen("no_disponible"))).arranque,
   estado(inst=lectura(vigilante=watch.Resumen("no_disponible"))).pausa), (None, None))
c("servicio: sin agente, «Iniciar servicio»", lleno.servicio, (watch.INICIAR, "Iniciar servicio"))
c("  con el agente como servicio, «Pausar»",
  estado(inst=lectura(vigilante=AGENTE)).servicio, (watch.PAUSAR, "Pausar"))
c("  con esta raíz en pausa, «Reanudar»",
  estado(inst=lectura(vigilante=AGENTE_PAUSADA)).servicio, (watch.REANUDAR, "Reanudar"))
c("  con el agente en pausa de la bandeja, «Reanudar todo»",
  estado(inst=lectura(vigilante=AGENTE_PAUSADO)).servicio, (watch.SEGUIR, "Reanudar todo"))
c("  mientras llega la lectura, «Iniciar servicio» (apagado, ver controles)",
  estado(inst=None).servicio, (principal.INICIAR, "Iniciar servicio"))
c("  y sin lectura no hay línea de arranque ni pausa",
  (estado(inst=None).arranque, estado(inst=None).pausa), (None, None))

# `vigilante` es lo que la ventana ha pedido al agente y la lectura aún no ha visto.
pedido = watch.pedido(AGENTE, "sync")
c("vigilante pedido: manda sobre el de la lectura",
  estado(inst=lectura(vigilante=AGENTE), vigilante=pedido).arranque.texto,
  watch.linea(pedido).texto)
c("  y el servicio sale de él",
  estado(inst=lectura(vigilante=SIN_INSTALAR), vigilante=AGENTE_PAUSADA).servicio,
  (watch.REANUDAR, "Reanudar"))
c("  sin él, el de la lectura",
  estado(inst=lectura(vigilante=AGENTE), vigilante=None).servicio, (watch.PAUSAR, "Pausar"))

# El pie: «Bloquear», «Expulsar» o nada.
EXPULSION = REPO / "Expulsar PRDRIVE.bat"
c("pie: nada", lleno.pie, None)
c("  «Bloquear» con la raíz cifrada de un equipo", estado(inst=lectura(bloqueo="uid")).pie,
  principal.BLOQUEAR)
c("  «Expulsar» con un contenedor", estado(inst=lectura(expulsion=EXPULSION)).pie,
  principal.EXPULSAR)
c("  «Bloquear» gana a «Expulsar»",
  estado(inst=lectura(bloqueo="uid", expulsion=EXPULSION)).pie, principal.BLOQUEAR)
LLAVE = llavero_editor.Linea("base, al día.", False, True)
c("  «Expulsar» también sin contenedor si lleva el llavero",
  estado(LLAVERO, inst=lectura(llavero=LLAVE)).pie, principal.EXPULSAR)
c("  salvo en una carpeta de este equipo, que no se quita",
  estado(LLAVERO, inst=lectura(llavero=LLAVE, del_equipo=True)).pie, None)
c("  aunque tenga contenedor, «Expulsar» se queda",
  estado(LLAVERO, inst=lectura(llavero=LLAVE, del_equipo=True, expulsion=EXPULSION)).pie,
  principal.EXPULSAR)
c("  y mientras llega la lectura, nada",
  estado(inst=None).pie, None)
c("los textos de los botones del pie son los de siempre",
  (principal.BLOQUEAR, principal.EXPULSAR), ("bloquear", "expulsar"))

# Ocupado y cargando se copian tal cual.
c("en_curso y cargando", (lleno.en_curso, lleno.cargando, estado(en_curso=True).en_curso,
                          estado(inst=None).cargando), (False, False, True, True))

# Mientras llega la lectura no hay nada que dependa de ella.
cargando = estado(inst=None, nueva=RELEASE, tiempos={"docs": HACE_UN_RATO, "fotos": AYER},
                  marcadas=["docs"], aviso="algo")
c("cargando: no hay lectura que enseñar",
  (cargando.chip, cargando.reparacion, cargando.componentes, cargando.llavero,
   cargando.arranque, cargando.pausa, cargando.pie, cargando.servicio,
   [f.chip for f in cargando.filas]),
  (("…", "", None), 0, None, None, None, None, None, (principal.INICIAR, "Iniciar servicio"),
   [None, None, None]))
c("  y sí lo que se sabe sin ella: aviso, release, horas y casillas",
  (cargando.aviso, cargando.version is not None, cargando.ultima,
   cargando.filas[0].cuando, cargando.marcadas),
  ("algo", True, f"última pasada {cuando(HACE_UN_RATO)}", cuando(HACE_UN_RATO),
   frozenset({"docs"})))

# Los textos de debajo de la lista.
c("resumen de marcadas: «N de M»", principal.resumen_de_marcadas(2, 3, ""), "2 de 3")
c("  con la última pasada", principal.resumen_de_marcadas(0, 3, "última pasada 08:20"),
  "0 de 3 · última pasada 08:20")
c("«Marcar todas» / «Desmarcar todas»: dice lo que hará",
  (principal.texto_de_marcar_todas(1, 3), principal.texto_de_marcar_todas(3, 3),
   principal.texto_de_marcar_todas(0, 3)),
  ("Marcar todas", "Desmarcar todas", "Marcar todas"))
c("  los dos textos, para reservar el sitio del más largo",
  (principal.MARCAR_TODAS, principal.DESMARCAR_TODAS), ("Marcar todas", "Desmarcar todas"))

# `estado()` no toca lo que recibe.
tiempos = {"docs": HACE_UN_RATO}
conflictos = {"docs": 1}
notas = {"fotos": "requiere resync"}
antes = (dict(tiempos), dict(conflictos), dict(notas))
estado(tiempos=tiempos, inst=lectura(conflictos=conflictos, notas=notas))
c("estado() no modifica lo que se le da", (tiempos, conflictos, notas), antes)


# ---------------------------------------------------------------------------
# La tabla de «desactivado ⇔ ocupado».
# ---------------------------------------------------------------------------

def base(**cambios) -> principal.Estado:
    """Un `Estado` en reposo (sin nada abierto ni ocupado) con esos campos cambiados."""
    campos = dict(
        dispositivo="F:\\", remotos="nas", chip=("al día", "Ok.", "ok"), aviso=None,
        reparacion=0, version=None, componentes=None, componentes_boton=False,
        filas=(principal.Fila("docs", "bisync", "—", None),), ultima="",
        marcadas=frozenset({"docs"}), llavero=None, arranque=None, pausa=None,
        servicio=(principal.INICIAR, "Iniciar servicio"), pie=None, en_curso=False,
        cargando=False)
    campos.update(cambios)
    return principal.Estado(**campos)


def filas_de(n: int) -> tuple:
    """`n` filas de pareja."""
    return tuple(principal.Fila(f"p{i}", "bisync", "—", None) for i in range(n))


C = principal.Control
SOLO_LLAVERO_ABRIR = principal.Linea("t", False, "Abrir llavero", True)
LLAVERO_QUE_NO_ABRE = principal.Linea("t", True, "Abrir llavero", False)

c("los controles son los de la tabla, ni uno más ni uno menos",
  sorted(principal.controles(base())),
  sorted(["sincronizar", "servicio", "parejas", "ajustes", "reparacion", "llavero", "pie",
          "componentes", "version", "descartar", "arranque", "marcar_todas"]))

# Todas las combinaciones, cada fila de la tabla escrita aparte.
total = 0
malas = []
ocupado_y_pulsable = []
for (en_curso, cargando, llave, pie, (comp, comp_boton), accion, parejas, reparacion, version,
     aviso, arranque) in itertools.product(
        (False, True), (False, True),
        (None, SOLO_LLAVERO_ABRIR, LLAVERO_QUE_NO_ABRE),
        (None, principal.EXPULSAR, principal.BLOQUEAR),
        ((None, False), ("texto", True), ("texto", False)),
        ((principal.INICIAR, "Iniciar servicio"), (watch.PAUSAR, "Pausar"),
         (watch.REANUDAR, "Reanudar"), (watch.SEGUIR, "Reanudar todo")),
        (1, 3), (0, 2), (None, "v"), (None, "a"), (None, SOLO_LLAVERO_ABRIR)):
    e = base(en_curso=en_curso, cargando=cargando, llavero=llave, pie=pie, componentes=comp,
             componentes_boton=comp_boton, servicio=accion, filas=filas_de(parejas),
             reparacion=reparacion, version=version, aviso=aviso, arranque=arranque)
    esperado = {
        # siempre se ve; se pulsa sin pasada en curso y con la lectura ya llegada
        "sincronizar": C(True, (not en_curso) and (not cargando)),
        # «Iniciar servicio» cierra la ventana y arranca otro proceso: como la pasada;
        # «Pausar», «Reanudar» y «Reanudar todo» solo dejan una petición en un buzón
        "servicio": C(True, True if accion[0] != principal.INICIAR
                      else (not en_curso) and (not cargando)),
        # las dos pantallas se abren mientras llega la lectura, no durante la pasada
        "parejas": C(True, not en_curso),
        "ajustes": C(True, not en_curso),
        # la línea de «Reparación…» no se enseña durante la pasada
        "reparacion": C(reparacion > 0 and not en_curso, True),
        "llavero": C(llave is not None,
                     llave is not None and llave.activo and not en_curso),
        "pie": C(pie is not None, not en_curso),
        "componentes": C(comp is not None and comp_boton, not en_curso),
        # «Actualizar…» sustituye el programa (también `sync.py`) y reabre la
        # ventana: no con una pasada suya en marcha
        "version": C(version is not None, not en_curso),
        "descartar": C(aviso is not None, True),
        "arranque": C(arranque is not None, True),
        "marcar_todas": C(parejas > 1, True),
    }
    obtenido = principal.controles(e)
    total += 1
    if obtenido != esperado:
        malas.append((obtenido, esperado))
    if en_curso:
        # nada de lo que toca `state/` se pulsa durante la pasada
        ocupado_y_pulsable += [k for k in ("sincronizar", "parejas", "ajustes", "llavero", "pie",
                                           "componentes", "version") if obtenido[k].activo]
        if accion[0] == principal.INICIAR and obtenido["servicio"].activo:
            ocupado_y_pulsable.append("servicio")
c(f"controles(): las {total} combinaciones dan la tabla", malas[:1], [])
c("  ningún control que toque state/ se pulsa durante una pasada", ocupado_y_pulsable, [])

# Lo mismo con valores a mano, para que un cambio de la tabla se lea aquí.
c("reparacion: se ve con algo que revisar y sin pasada",
  [principal.controles(base(reparacion=n, en_curso=o))["reparacion"]
   for n, o in ((0, False), (2, False), (2, True), (0, True))],
  [C(False, True), C(True, True), C(False, True), C(False, True)])
c("version: «Actualizar…» se apaga mientras sincroniza",
  [principal.controles(base(version="v", en_curso=o))["version"] for o in (False, True)],
  [C(True, True), C(True, False)])
c("componentes: sin botón no hay nada que pulsar",
  principal.controles(base(componentes="t", componentes_boton=False))["componentes"],
  C(False, True))
c("marcar_todas: con una pareja no hace falta", principal.controles(base())["marcar_todas"],
  C(False, True))

# Mientras llega la lectura (primer pintado): solo se abren las dos pantallas.
primero = principal.controles(estado(inst=None))
c("cargando: «Sincronizar ahora» e «Iniciar servicio» apagados",
  (primero["sincronizar"], primero["servicio"]), (C(True, False), C(True, False)))
c("  «Parejas…» y «Ajustes…» abiertos, que se pulsan nada más pintar",
  (primero["parejas"], primero["ajustes"]), (C(True, True), C(True, True)))
c("  sin llavero, sin «Expulsar», sin «Reparación…» y sin aviso de componentes",
  (primero["llavero"].visible, primero["pie"].visible, primero["componentes"].visible,
   primero["reparacion"].visible, primero["arranque"].visible), (False,) * 5)

# Con la lectura: en reposo todo lo que se ve se pulsa, y en la pasada casi nada.
TODO = dict(llavero=LLAVE, bloqueo="uid", cuenta=2, **COMPONENTES)
reposo = principal.controles(estado(LLAVERO, inst=lectura(**TODO)))
c("en reposo: todo lo que se ve se pulsa",
  [k for k, v in reposo.items() if v.visible and not v.activo], [])
c("  y todo lo que toca state/ se ve",
  [k for k in ("sincronizar", "servicio", "parejas", "ajustes", "reparacion", "llavero", "pie",
               "componentes") if not reposo[k].visible], [])
en_pasada = principal.controles(estado(LLAVERO, en_curso=True, inst=lectura(**TODO)))
c("  y durante la pasada, de lo que se ve solo se pulsa la línea del arranque",
  sorted(k for k, v in en_pasada.items() if v.visible and v.activo), ["arranque"])

# Un Control se compara con una tupla (la vista lo lee de los widgets como `(visible, activo)`).
c("Control es una pareja (visible, activo)", (C(True, False) == (True, False),
                                              C(True, False)._fields), (True, ("visible", "activo")))

# Con la lectura de verdad (`ui.instantanea`, otra tarea): los campos que `estado()` lee son
# los suyos y una lectura vacía —lo que la ventana guarda si el hilo falla— no enseña nada.
try:
    from ui import instantanea
except ImportError:
    instantanea = None
    print("  (saltado) ui.instantanea no existe todavía: sin la lectura de verdad")
if instantanea is not None:
    vacia = instantanea.vacia(CFG)
    c("vacia(): tiene todos los campos que lee estado()",
      [k for k in vars(lectura()) if not hasattr(vacia, k)], [])
    e = principal.estado(CFG, aviso=None, nueva=None, instalada="0.8.0", tiempos={},
                         marcadas=(), en_curso=False, inst=vacia)
    c("  y con ella, una ventana al día y sin nada que revisar",
      (e.cargando, e.chip, e.reparacion, e.componentes, e.llavero, e.pie,
       [f.chip for f in e.filas]), (False, ("al día", "Ok.", "ok"), 0, None, None, None,
                                    [None, None, None]))

sys.exit(c.report())
