#!/usr/bin/env python3
"""El catálogo del remoto (`common/catalog.py`).

`catalog.run` se sustituye entera: aquí no se habla con ningún remoto. Lo que
se comprueba es lo que puede hacer daño de verdad (que escribir se niegue
cuando el remoto ha cambiado bajo nuestros pies, y que la copia de seguridad se
suba ANTES que el fichero nuevo) y lo que sostiene la pantalla cuando no hay
red.
"""

import subprocess
import sys
import threading
import tomllib

from _harness import Checks, sandbox

from common import catalog, config_file, model, store
from install import profile
from common.model import ConfigError

c = Checks("catálogo del remoto (common/catalog.py)")

CAT = {"defaults": {"remote": "nas", "exclude": ["**/.stfolder/**"]},
       "pair": [{"name": "prdrive", "local": ".", "remote_path": "/prdrive",
                 "mode": "up-mirror"},
                {"name": "notas", "local": "sync-data/notas",
                 "remote_path": "/R/notas", "mode": "bisync"}]}
CABECERA = "# El catálogo global de parejas.\n# Una línea más de cabecera.\n"
TEXTO = config_file.dumps(CAT, CABECERA)

llamadas: list[list[str]] = []


def responder(*respuestas):
    """Sustituye catalog.run por una cola de respuestas, apuntando cada orden."""
    cola = list(respuestas)
    llamadas.clear()

    def _run(args):
        """Contesta con la siguiente respuesta de la cola y apunta la orden."""
        llamadas.append(list(args))
        rc, salida, error = cola.pop(0) if cola else (0, "", "")
        return subprocess.CompletedProcess(args, rc, salida, error)
    catalog.run = _run


def ok(salida=TEXTO):
    """Devuelve una respuesta de rclone que sale bien."""
    return (0, salida, "")


def falla(error="no route to host"):
    """Devuelve una respuesta de rclone que falla."""
    return (1, "", error)


# de dónde se lee
c("el endpoint por defecto sale de las constantes compartidas", catalog.endpoint(),
  f"{model.DEFAULT_REMOTE}:{catalog.DEFAULT_CATALOG_PATH}")
# El instalador lee el catálogo cuando todavía no hay dispositivo, así que
# tiene que buscarlo en el mismo sitio: hay una sola cadena y esto la vigila.
c("y el instalador usa exactamente esa", profile.empty().catalog_path,
  catalog.DEFAULT_CATALOG_PATH)
c("[defaults] puede moverlo",
  catalog.endpoint({"defaults": {"remote": "otro", "catalog_path": "/x/y.toml"}}),
  "otro:/x/y.toml")

c("diff_keys ve altas, bajas y cambios",
  catalog.diff_keys({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 4}), ("b", "c"))
c("y dice que no hay diferencia cuando no la hay",
  catalog.diff_keys({"a": 1}, {"a": 1}), ())

# leer deja copia, y la copia salva la pantalla sin red
with sandbox():
    responder(ok())
    cat = catalog.pull(CAT)
    c("leer usa 'cat' contra el endpoint", llamadas[0],
      ["cat", "nas:/prdrive-catalog/remote.toml"])
    # El diagnóstico de la carpeta (#48) solo pregunta cuando algo huele mal:
    # abrir la ventana de parejas no puede costar una ida y vuelta más.
    c("y en el camino bueno no pregunta nada más", len(llamadas), 1)
    c("y trae las parejas", [p["name"] for p in cat.raw["pair"]], ["prdrive", "notas"])
    c("viene del remoto y por tanto es editable", (cat.source, cat.editable),
      ("remote", True))
    c("ha quedado copia local", catalog.cache_toml().read_text(encoding="utf-8"), TEXTO)

    responder(falla())
    cat, aviso = catalog.load()
    c("sin red se cae a la copia", cat.source, "cache")
    c("y la copia NO se puede editar", cat.editable, False)
    c("con las mismas parejas", [p["name"] for p in cat.raw["pair"]],
      ["prdrive", "notas"])
    c("y se dice por qué", "Sin conexión" in aviso, True)

with sandbox():
    responder(falla())
    cat, aviso = catalog.load()
    c("sin red y sin copia no hay catálogo", cat, None)
    c("pero se explica, no se revienta", "No hay catálogo" in aviso, True)

with sandbox():
    responder((0, "esto ] no [ es toml", ""))
    cat, aviso = catalog.load()
    c("un catálogo ilegible tampoco revienta", cat, None)
    c("y dice que no es TOML válido", "TOML" in aviso, True)

# la copia local se escribe de forma atómica y las lecturas en hilos no se pisan
with sandbox():
    escritos = []
    real_write_text = store.write_text

    def apunta(ruta, texto):
        """`store.write_text` apuntando qué ficheros se escriben por él."""
        escritos.append(ruta.name)
        return real_write_text(ruta, texto)

    store.write_text = apunta
    try:
        catalog._write_cache(catalog.Catalog(raw=CAT, text=TEXTO, source="remote",
                                             stamp="2026-10-03 10:00", endpoint="nas:/x"))
    finally:
        store.write_text = real_write_text
    c("la copia local pasa por store.write_text (atómico), el texto y los metadatos",
      escritos, ["catalog.toml", "catalog.json"])
    c("  sin dejar temporales", sorted(p.name for p in catalog.cache_toml().parent.iterdir()),
      ["catalog.json", "catalog.toml"])

    # Dos lecturas que acaban a la vez, y la ventana leyendo la copia entretanto:
    # nunca un fichero a medias ni vacío (que se leería como «sin catálogo» o como
    # un catálogo sin parejas).
    otro = {**CAT, "pair": CAT["pair"][:1]}
    textos = [TEXTO, config_file.dumps(otro, CABECERA)]
    vistos: list[int | None] = []
    activo = threading.Event()
    activo.set()

    def escribe_siempre(texto):
        """Escribe la copia una y otra vez, como lo hace cada lectura que acaba."""
        for _ in range(150):
            catalog._write_cache(catalog.Catalog(raw=tomllib.loads(texto), text=texto,
                                                 source="remote", stamp="x", endpoint="nas:/x"))

    def lee_siempre():
        """Lee la copia mientras se escribe y apunta cuántas parejas ve."""
        while activo.is_set():
            cat = catalog.cached()
            vistos.append(None if cat is None else len(cat.raw.get("pair") or []))

    hilos = [threading.Thread(target=escribe_siempre, args=(t,)) for t in textos]
    lector = threading.Thread(target=lee_siempre)
    lector.start()
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    activo.clear()
    lector.join()
    c("dos escrituras a la vez y una lectura en medio: siempre una copia entera",
      (len(vistos) > 0, set(vistos) <= {1, 2}), (True, True))

# escribir: lo peligroso
with sandbox():
    nuevo = {**CAT, "pair": CAT["pair"] + [{"name": "fotos", "local": "sync-data/fotos",
                                            "remote_path": "/R/fotos", "mode": "up"}]}
    responder(ok(), ok(""), ok(""))
    hechos = catalog.push(nuevo, TEXTO, CAT)

    c("primero se relee el remoto", llamadas[0][0], "cat")
    c("después se copia el .bak, ANTES de escribir", llamadas[1],
      ["copyto", "nas:/prdrive-catalog/remote.toml",
       "nas:/prdrive-catalog/remote.toml.bak"])
    c("y por último se sube el fichero nuevo",
      llamadas[2][0] == "copyto" and llamadas[2][-1].endswith("remote.toml"), True)
    c("y en remote.toml no se pregunta nada más", len(llamadas), 3)
    c("se cuenta lo que se ha hecho", len(hechos), 2)

    subido = tomllib.loads(catalog.cache_toml().read_text(encoding="utf-8"))
    c("la copia local queda al día", [p["name"] for p in subido["pair"]],
      ["prdrive", "notas", "fotos"])
    c("y la cabecera del catálogo sobrevive",
      catalog.cache_toml().read_text(encoding="utf-8").startswith(CABECERA.rstrip()), True)

with sandbox():
    responder(ok("otra cosa distinta"))
    try:
        catalog.push(CAT, TEXTO)
        c("no se escribe encima de un catálogo cambiado", "no lanzó", "ConfigError")
    except ConfigError as e:
        c("no se escribe encima de un catálogo cambiado", "ha cambiado" in str(e), True)
    c("y no se ha llegado a copiar nada", len(llamadas), 1)

with sandbox():
    responder(ok(), falla("permiso denegado"))
    try:
        catalog.push({**CAT, "pair": [CAT["pair"][0]]}, TEXTO)
        c("si falla el .bak no se escribe", "no lanzó", "ConfigError")
    except ConfigError as e:
        c("si falla el .bak no se escribe", "No se ha escrito nada" in str(e), True)
    c("y no se ha subido nada", len(llamadas), 2)

with sandbox():
    responder(ok())
    try:
        catalog.push({"defaults": {}, "pair": []}, TEXTO)
        c("un catálogo sin parejas se rechaza antes de tocar la red",
          "no lanzó", "ConfigError")
    except ConfigError as e:
        c("un catálogo sin parejas se rechaza antes de tocar la red",
          "ninguna [[pair]]" in str(e), True)
    c("ni siquiera se ha releído el remoto", llamadas, [])

# una carpeta no es un catálogo (#48)
#
# `rclone cat` de una carpeta no falla: junta todo lo que hay dentro. Con el
# pairs.toml y el .bak que deja push(), son dos copias seguidas del catálogo, y
# eso es exactamente el error que se veía. Las respuestas de `lsjson --stat`
# son las de rclone v1.75.1 contra una carpeta y un fichero de verdad.
DOS_COPIAS = TEXTO + TEXTO
try:
    tomllib.loads(DOS_COPIAS)
    c("dos copias seguidas no son TOML", "se leyó", "TOMLDecodeError")
except tomllib.TOMLDecodeError as e:
    c.contains("dos copias seguidas dan el error del issue", str(e),
               "Cannot declare ('defaults',) twice")

STAT_CARPETA = ('{\n\t"Path": "",\n\t"Name": "",\n\t"Size": -1,\n'
                '\t"MimeType": "inode/directory",\n'
                '\t"ModTime": "2026-09-25T11:38:30.975365128Z",\n\t"IsDir": true\n}\n')
STAT_FICHERO = ('{\n\t"Path": "remote.toml",\n\t"Name": "remote.toml",\n\t"Size": 94,\n'
                '\t"MimeType": "application/toml",\n'
                '\t"ModTime": "2026-09-25T11:38:30.643855347Z",\n\t"IsDir": false\n}\n')
NO_EXISTE = (3, "", "NOTICE: Failed to lsjson: directory not found")
EN_CARPETA = {"defaults": {"remote": "nas", "catalog_path": "/prdrive-catalog"}}


def lee(raw_local=None):
    """pull() y lo que dijo, o None si no lanzó."""
    try:
        catalog.pull(raw_local)
        return None
    except ConfigError as e:
        return str(e)


with sandbox():
    responder(ok(DOS_COPIAS), ok(STAT_CARPETA), ok(STAT_FICHERO))
    motivo = lee(EN_CARPETA) or ""
    c.contains("una carpeta se dice como carpeta", motivo, "es una carpeta")
    c.contains("y se sugiere el remote.toml que hay dentro", motivo,
               "«/prdrive-catalog/remote.toml»")
    c("y no se habla de TOML, que no es la causa", "TOML" in motivo, False)
    c("se pregunta qué es la ruta, y si dentro hay un remote.toml", llamadas,
      [["cat", "nas:/prdrive-catalog"],
       ["lsjson", "--stat", "nas:/prdrive-catalog"],
       ["lsjson", "--stat", "nas:/prdrive-catalog/remote.toml"]])
    c("lo que trajo el cat no se cachea", catalog.cache_toml().exists(), False)

    responder(ok(DOS_COPIAS), ok(STAT_CARPETA), ok(STAT_FICHERO))
    cat, aviso = catalog.load(EN_CARPETA)
    c("load() sigue sin lanzar", cat, None)
    c.contains("y el aviso lleva el diagnóstico", aviso or "", "es una carpeta")

with sandbox():
    # Un remoto sin renombrar: dentro solo está pairs.toml.
    responder(ok(DOS_COPIAS), ok(STAT_CARPETA), NO_EXISTE, ok(STAT_FICHERO))
    c.contains("en un remoto sin renombrar se sugiere su pairs.toml", lee(EN_CARPETA) or "",
               "Dentro hay un pairs.toml, así que seguramente es «/prdrive-catalog/pairs.toml»")

with sandbox():
    responder(ok(DOS_COPIAS), ok(STAT_CARPETA), NO_EXISTE, NO_EXISTE)
    motivo = lee(EN_CARPETA) or ""
    c.contains("sin ninguno de los dos dentro se da un ejemplo", motivo,
               "Por ejemplo «/prdrive-catalog/remote.toml»")
    c("sin afirmar que esté", "Dentro hay" in motivo, False)

with sandbox():
    # Una carpeta con un solo pairs.toml se lee SIN error: es la ruta que no
    # termina en .toml lo que hace preguntar.
    responder(ok(TEXTO), ok(STAT_CARPETA), ok(STAT_FICHERO))
    c.contains("una carpeta que se lee bien por casualidad también se dice",
               lee(EN_CARPETA) or "", "es una carpeta")

with sandbox():
    # Una carpeta vacía: `cat` sale con 0 y no trae nada.
    responder(ok(""), ok(STAT_CARPETA), NO_EXISTE)
    c.contains("una carpeta vacía también", lee(EN_CARPETA) or "", "es una carpeta")

    responder(ok(""))
    c("un catálogo vacío de verdad se sigue leyendo", lee(CAT), None)
    # Vacío puede ser «no está» en un remoto de cubetas: se mira el otro nombre.
    c("mirando antes si al lado hay un pairs.toml", llamadas,
      [["cat", "nas:/prdrive-catalog/remote.toml"], ["cat", "nas:/prdrive-catalog/pairs.toml"]])

with sandbox():
    # Un diagnóstico falso es peor que ninguno.
    responder(ok("esto ] no [ es toml"), ok(STAT_FICHERO))
    c.contains("un fichero que no es TOML sigue diciendo eso", lee(CAT) or "",
               "no es TOML válido")
    responder(ok(DOS_COPIAS), (0, "esto no es json", ""))
    c.contains("una respuesta que no se entiende no diagnostica nada",
               lee(EN_CARPETA) or "", "no es TOML válido")
    responder(ok(DOS_COPIAS), NO_EXISTE)
    c.contains("ni un lsjson que falla", lee(EN_CARPETA) or "", "no es TOML válido")

with sandbox():
    responder(falla())
    lee(EN_CARPETA)
    c("si falla el propio cat no se pregunta nada más: sin red tardaría lo mismo",
      len(llamadas), 1)

with sandbox():
    sin_extension = {"defaults": {"remote": "nas", "catalog_path": "/cat/pares"}}
    responder(ok(TEXTO), ok(STAT_FICHERO))
    c("un catálogo sin .toml que es un fichero se sigue leyendo",
      lee(sin_extension), None)
    c("a costa de una sola pregunta", len(llamadas), 2)

# la ruta tecleada
c.contains("una carpeta tecleada se rechaza sin red",
           catalog.problema_de_ruta("/prdrive-catalog") or "",
           "«/prdrive-catalog/remote.toml»")
c.contains("con la barra del final, sin barra doble",
           catalog.problema_de_ruta("/prdrive-catalog/") or "",
           "«/prdrive-catalog/remote.toml»")
c("un fichero .toml vale", catalog.problema_de_ruta("/x/pairs.toml"), None)
c("los dos nombres valen", catalog.problema_de_ruta("/x/remote.toml"), None)
c("en mayúsculas también", catalog.problema_de_ruta("/x/PAIRS.TOML"), None)
c("vacía vale: se cae a la de fábrica", catalog.problema_de_ruta("  "), None)

catalog.validar_ruta_editada({"catalog_path": "/cat/pares"},
                             {"catalog_path": "/cat/pares", "keep_logs": True})
c("una ruta que ya estaba no se revisa al guardar otra cosa", True, True)
try:
    catalog.validar_ruta_editada({}, {"catalog_path": "/prdrive-catalog"})
    c("cambiarla a una carpeta se rechaza", "no lanzó", "ConfigError")
except ConfigError as e:
    c.contains("cambiarla a una carpeta se rechaza", str(e), "no termina en .toml")

# los dos nombres: remote.toml, y pairs.toml en un remoto sin renombrar
#
# Un remoto de mentira con ficheros de verdad, para que escribir, renombrar y
# la carrera entre los dos se puedan seguir por lo que queda en él. Contesta
# como rclone v1.75.1 con el backend local: `cat` y `lsjson --stat` de algo que
# no existe salen con 3, y `moveto` de un origen que no existe, con 1.
import json  # noqa: E402

NUEVO, VIEJO = "nas:/prdrive-catalog/remote.toml", "nas:/prdrive-catalog/pairs.toml"
CARPETA = "nas:/prdrive-catalog/"
CON_VIEJO = {"defaults": {"remote": "nas", "catalog_path": "/prdrive-catalog/pairs.toml"}}
CON_NUEVO = {"defaults": {"remote": "nas", "catalog_path": "/prdrive-catalog/remote.toml"}}


class Remoto:
    """Un remoto de mentira: ficheros por endpoint y las órdenes de rclone del catálogo.

    `antes[n]` se ejecuta justo antes de la orden número `n` (desde 1): es como
    se mete otro dispositivo en mitad de una escritura.
    """

    def __init__(self, ficheros, falla=(), cubeta=False):
        self.f = dict(ficheros)
        self.ordenes: list[list[str]] = []
        self.antes: dict = {}
        self.falla = set(falla)
        self.cubeta = cubeta

    def __call__(self, args):
        self.ordenes.append(list(args))
        gancho = self.antes.pop(len(self.ordenes), None)
        if gancho:
            gancho(self)
        op = args[0]
        if op in self.falla:
            return subprocess.CompletedProcess(args, 1, "", f"{op}: permiso denegado")
        if op == "cat":
            if args[1] in self.f:
                return subprocess.CompletedProcess(args, 0, self.f[args[1]], "")
            if self.cubeta:           # un prefijo vacío no es un error: nada, y 0
                return subprocess.CompletedProcess(args, 0, "", "")
            return subprocess.CompletedProcess(args, 3, "", "directory not found")
        if op == "lsjson" and args[1] == "--stat":
            if args[2] in self.f:
                return subprocess.CompletedProcess(
                    args, 0, json.dumps({"Name": args[2].rsplit("/", 1)[1], "IsDir": False}), "")
            if self.cubeta:           # y lo que no existe se lee como una carpeta
                return subprocess.CompletedProcess(args, 0, json.dumps({"IsDir": True}), "")
            return subprocess.CompletedProcess(args, 3, "", "directory not found")
        if op == "lsjson" and args[1] == "--files-only":
            dentro = [{"Name": k[len(args[2]):], "IsDir": False} for k in self.f
                      if k.startswith(args[2]) and "/" not in k[len(args[2]):]]
            return subprocess.CompletedProcess(args, 0, json.dumps(dentro), "")
        if op == "copyto":
            origen = args[1]
            if origen in self.f:
                self.f[args[2]] = self.f[origen]
            elif Path(origen).is_file():
                self.f[args[2]] = Path(origen).read_text(encoding="utf-8")
            else:
                return subprocess.CompletedProcess(args, 3, "", "directory not found")
            return subprocess.CompletedProcess(args, 0, "", "")
        if op == "moveto":
            if args[1] not in self.f:
                return subprocess.CompletedProcess(args, 1, "", "no such file or directory")
            self.f[args[2]] = self.f.pop(args[1])
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, "", "")


def remoto(ficheros, falla=(), cubeta=False):
    """Pone un `Remoto` como `catalog.run` y lo devuelve."""
    rem = Remoto(ficheros, falla, cubeta)
    catalog.run = rem
    return rem


from pathlib import Path  # noqa: E402

c("candidatos: pairs.toml busca primero remote.toml en la misma carpeta",
  catalog.candidatos(VIEJO), (NUEVO, VIEJO))
c("  y remote.toml, después pairs.toml", catalog.candidatos(NUEVO), (NUEVO, VIEJO))
c("  en la raíz del remoto también", catalog.candidatos("nas:pairs.toml"),
  ("nas:remote.toml", "nas:pairs.toml"))
c("  un nombre propio se busca tal cual", catalog.candidatos("nas:/c/mio.toml"),
  ("nas:/c/mio.toml",))
c("  y una carpeta también", catalog.candidatos("nas:/prdrive-catalog"),
  ("nas:/prdrive-catalog",))

with sandbox():
    rem = remoto({VIEJO: TEXTO})
    cat = catalog.pull(CON_VIEJO)
    c("un remoto sin renombrar se lee aunque el dispositivo diga pairs.toml",
      cat.names, ["prdrive", "notas"])
    c("  probando antes remote.toml", rem.ordenes, [["cat", NUEVO], ["cat", VIEJO]])
    c("  y el catálogo dice de qué fichero salió", cat.endpoint, VIEJO)
    c("  igual que la copia local", catalog.ultimo_leido(), VIEJO)
    rem = remoto({VIEJO: TEXTO})
    c("  y diga remote.toml", catalog.pull(CON_NUEVO).endpoint, VIEJO)

with sandbox():
    rem = remoto({NUEVO: TEXTO})
    cat = catalog.pull(CON_VIEJO)
    c("un remoto renombrado se lee aunque el dispositivo diga pairs.toml",
      (cat.endpoint, len(rem.ordenes)), (NUEVO, 1))

with sandbox():
    rem = remoto({NUEVO: TEXTO, VIEJO: "otro = 1\n"})
    c("con los dos, manda remote.toml", catalog.pull(CON_VIEJO).endpoint, NUEVO)

with sandbox():
    rem = remoto({})
    motivo = lee(CON_VIEJO) or ""
    c.contains("sin ninguno de los dos, se nombran los dos", motivo,
               f"No hay catálogo en {NUEVO} ni en {VIEJO}")
    responder(falla())
    lee(CON_VIEJO)
    c("sin red no se prueba el otro nombre", len(llamadas), 1)

# Un remoto de cubetas (S3, B2, GCS…): `cat` de lo que no existe sale con 0 y
# nada, y `lsjson --stat` lo da por carpeta (`backend/s3/s3.go`, v1.75.1, sin
# `--s3-directory-markers`). Sin cuidado, un remoto sin renombrar se leería como
# un remote.toml vacío, y la primera escritura lo crearía al lado del bueno.
with sandbox():
    rem = remoto({VIEJO: TEXTO}, cubeta=True)
    cat = catalog.pull(CON_VIEJO)
    c("cubeta: un remote.toml que no está no se lee como un catálogo vacío",
      (cat.endpoint, cat.names), (VIEJO, ["prdrive", "notas"]))
    rem.ordenes.clear()
    catalog.push({**CAT, "pair": CAT["pair"][:1]}, cat.text, CON_VIEJO)
    c("  y escribir va a pairs.toml, sin crear remote.toml",
      (sorted(rem.f), tomllib.loads(rem.f[VIEJO])["pair"][0]["name"]),
      ([VIEJO, VIEJO + ".bak"], "prdrive"))
    c("  sin confundir la carpeta de mentira con un renombrado", catalog.duplicado(), None)

with sandbox():
    rem = remoto({VIEJO: TEXTO}, cubeta=True)
    base = catalog.pull(CON_VIEJO)
    rem.ordenes.clear()
    rem.antes[4] = lambda r: r.f.__setitem__(NUEVO, r.f.pop(VIEJO))
    try:
        catalog.push({**CAT, "pair": CAT["pair"][:1]}, base.text, CON_VIEJO)
        c("cubeta: la carrera con el renombrado también se ve", "no lanzó", "ConfigError")
    except ConfigError as e:
        c.contains("cubeta: la carrera con el renombrado también se ve", str(e),
                   "el cambio no cuenta")

with sandbox():
    remoto({}, cubeta=True)
    cat = catalog.pull(CON_VIEJO)
    c("cubeta: sin ninguno, un catálogo vacío en remote.toml, como siempre",
      (cat.endpoint, cat.raw), (NUEVO, {}))

with sandbox():
    rem = remoto({VIEJO: TEXTO})
    rem.antes[1] = lambda r: r.f.__setitem__(NUEVO, "")
    c("un remote.toml vacío no tapa un pairs.toml con parejas",
      catalog.pull(CON_VIEJO).endpoint, VIEJO)

with sandbox():
    rem = remoto({VIEJO: TEXTO}, falla={"cat"})
    lee(CON_VIEJO)
    c("un fallo de verdad en el primero no prueba el segundo", len(rem.ordenes), 1)

# escribir: en el que exista justo antes de escribir, y nunca crear el otro
with sandbox():
    rem = remoto({VIEJO: TEXTO})
    base = catalog.pull(CON_VIEJO)
    otro = {**CAT, "pair": CAT["pair"][:1]}
    rem.ordenes.clear()
    hechos = catalog.push(otro, base.text, CON_VIEJO)
    c("en un remoto sin renombrar se escribe pairs.toml",
      tomllib.loads(rem.f[VIEJO])["pair"][0]["name"], "prdrive")
    c("  con su .bak", rem.f.get(VIEJO + ".bak"), TEXTO)
    c("  y sin crear remote.toml", NUEVO in rem.f, False)
    c("  comprobando después que nadie lo ha renombrado mientras",
      rem.ordenes[-1], ["lsjson", "--stat", NUEVO])
    c("  y se cuenta", len(hechos), 2)

with sandbox():
    rem = remoto({VIEJO: TEXTO})
    base = catalog.pull(CON_VIEJO)
    rem.f[NUEVO] = rem.f.pop(VIEJO)     # otro dispositivo renombra entretanto
    catalog.push({**CAT, "pair": CAT["pair"][:1]}, base.text, CON_VIEJO)
    c("si lo han renombrado desde que se leyó, se escribe en remote.toml",
      tomllib.loads(rem.f[NUEVO])["pair"][0]["name"], "prdrive")
    c("  y pairs.toml no vuelve", VIEJO in rem.f, False)

with sandbox():
    # La carrera: el renombrado cae entre la copia previa y la subida.
    rem = remoto({VIEJO: TEXTO})
    base = catalog.pull(CON_VIEJO)
    rem.ordenes.clear()
    rem.antes[4] = lambda r: r.f.__setitem__(NUEVO, r.f.pop(VIEJO))
    try:
        catalog.push({**CAT, "pair": CAT["pair"][:1]}, base.text, CON_VIEJO)
        c("una subida que se cruza con el renombrado se dice", "no lanzó", "ConfigError")
    except ConfigError as e:
        c.contains("una subida que se cruza con el renombrado se dice", str(e),
                   "el cambio no cuenta")
    c("  y queda apuntado que hay dos", catalog.duplicado()[0], VIEJO)
    from common import revision  # noqa: E402
    hallazgo = revision._catalogo_duplicado()
    c("  que «Reparación» enseña", (hallazgo.clave, hallazgo.gravedad),
      ("catalogo", revision.AVISO))
    c.contains("  diciendo cuál vale", hallazgo.detalle, "Vale remote.toml")

with sandbox():
    rem = remoto({VIEJO: TEXTO})
    catalog.pull(CON_VIEJO)
    catalog.apuntar_duplicado(VIEJO)
    catalog._write_cache(catalog.Catalog(raw=CAT, text=TEXTO, source="remote",
                                         stamp="x", endpoint=NUEVO))
    c("la marca de los dos sobrevive a una lectura de la misma carpeta",
      catalog.duplicado()[0], VIEJO)
    catalog._write_cache(catalog.Catalog(raw=CAT, text=TEXTO, source="remote",
                                         stamp="x", endpoint="nas:/otro/remote.toml"))
    c("  y no a la de otra carpeta", catalog.duplicado(), None)
    catalog.apuntar_duplicado(VIEJO)
    catalog.pull(CON_VIEJO)
    c("  y leer pairs.toml porque no hay remote.toml la borra", catalog.duplicado(), None)

# renombrar
with sandbox():
    rem = remoto({VIEJO: TEXTO, VIEJO + ".bak": "antes = 1\n"})
    catalog.pull(CON_VIEJO)
    rem.ordenes.clear()
    hechos = catalog.renombrar(CON_VIEJO)
    c("renombrar mueve pairs.toml a remote.toml, sin tocar su contenido",
      (rem.f.get(NUEVO), VIEJO in rem.f), (TEXTO, False))
    c("  y su .bak", (rem.f.get(NUEVO + ".bak"), VIEJO + ".bak" in rem.f),
      ("antes = 1\n", False))
    c("  mirando antes qué hay en la carpeta",
      rem.ordenes[0], ["lsjson", "--files-only", CARPETA])
    c("  y la copia local dice ya que sale de remote.toml", catalog.ultimo_leido(), NUEVO)
    c("  y lo cuenta", len(hechos), 2)
    try:
        catalog.renombrar(CON_VIEJO)
        c("renombrar dos veces se niega", "no lanzó", "ConfigError")
    except ConfigError as e:
        c.contains("renombrar dos veces se niega", str(e), "ya se llama remote.toml")

with sandbox():
    rem = remoto({VIEJO: TEXTO})
    catalog.renombrar(CON_NUEVO)
    c("sin .bak, solo el catálogo", sorted(rem.f), [NUEVO])

with sandbox():
    rem = remoto({VIEJO: TEXTO, NUEVO: "otro = 1\n"})
    try:
        catalog.renombrar(CON_VIEJO)
        c("con los dos no se renombra: moveto pisaría remote.toml", "no lanzó",
          "ConfigError")
    except ConfigError as e:
        c.contains("con los dos no se renombra: moveto pisaría remote.toml", str(e),
                   "Vale remote.toml")
    c("  no se ha movido nada", rem.f, {VIEJO: TEXTO, NUEVO: "otro = 1\n"})
    c("  y queda apuntado", catalog.duplicado()[0], VIEJO)
    hechos = catalog.apartar_sobrante(CON_VIEJO)
    apartado = [k for k in rem.f if k.startswith(VIEJO + catalog.APARTADO)]
    c("apartar deja el que sobra al lado, con otro nombre", (len(apartado), VIEJO in rem.f),
      (1, False))
    c("  sin tocar remote.toml", rem.f[NUEVO], "otro = 1\n")
    c("  ni borrar nada", rem.f[apartado[0]], TEXTO)
    c("  y la marca se va", catalog.duplicado(), None)
    try:
        catalog.apartar_sobrante(CON_VIEJO)
        c("apartar sin los dos se niega", "no lanzó", "ConfigError")
    except ConfigError as e:
        c.contains("apartar sin los dos se niega", str(e), "no hay nada que apartar")

with sandbox():
    rem = remoto({VIEJO: TEXTO}, falla={"lsjson"})
    try:
        catalog.renombrar(CON_VIEJO)
        c("sin poder mirar la carpeta no se renombra", "no lanzó", "ConfigError")
    except ConfigError as e:
        c.contains("sin poder mirar la carpeta no se renombra", str(e),
                   "No se ha tocado nada")
    c("  y no se ha movido nada", rem.f, {VIEJO: TEXTO})

with sandbox():
    rem = remoto({VIEJO: TEXTO}, falla={"moveto"})
    try:
        catalog.renombrar(CON_VIEJO)
        c("si moveto falla se dice", "no lanzó", "ConfigError")
    except ConfigError as e:
        c.contains("si moveto falla se dice", str(e), "sigue como estaba")

with sandbox():
    remoto({"nas:/c/mio.toml": TEXTO})
    try:
        catalog.renombrar({"defaults": {"remote": "nas", "catalog_path": "/c/mio.toml"}})
        c("un catálogo con nombre propio no se renombra", "no lanzó", "ConfigError")
    except ConfigError as e:
        c.contains("un catálogo con nombre propio no se renombra", str(e),
                   "no hay nada que renombrar")

c("nombres_en: solo los del catálogo y sus .bak",
  catalog.nombres_en(Remoto({VIEJO: "", NUEVO + ".bak": "", CARPETA + "otra.toml": "",
                             CARPETA + "devices/x.toml": ""}), CARPETA),
  frozenset({"pairs.toml", "remote.toml.bak"}))
c("  una carpeta que no existe no tiene nada",
  catalog.nombres_en(lambda a: subprocess.CompletedProcess(a, 3, "", ""), CARPETA),
  frozenset())
c("  y lo que no se entiende no se sabe",
  catalog.nombres_en(lambda a: subprocess.CompletedProcess(a, 0, "{", ""), CARPETA), None)

# Una tabla que esta versión no conoce, como la [keychain] del llavero: el
# modelo la ignora al leer y el serializador la conserva al reescribir, así que
# un catálogo que la lleva se sigue pudiendo editar.
CON_LLAVERO = {**CAT, "keychain": {"base": "personal.kdbx", "fichero_llave": True,
                                   "nombre_llave": "personal.keyx"}}
c("una tabla desconocida no impide leer", [p.name for p in model.parse_config(CON_LLAVERO).pairs],
  ["prdrive", "notas"])
c("  y sobrevive a la escritura", tomllib.loads(config_file.dumps_checked(CON_LLAVERO))["keychain"],
  CON_LLAVERO["keychain"])
with sandbox():
    rem = remoto({NUEVO: config_file.dumps(CON_LLAVERO)})
    base = catalog.pull(CON_NUEVO)
    nuevo_raw = {**base.raw, "pair": base.raw["pair"][:1]}
    catalog.push(nuevo_raw, base.text, CON_NUEVO)
    c("  también al editar el catálogo", tomllib.loads(rem.f[NUEVO]).get("keychain"),
      CON_LLAVERO["keychain"])


sys.exit(c.report())
