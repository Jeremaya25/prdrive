#!/usr/bin/env python3
"""Los ficheros en conflicto de bisync: su nombre, su lado y el aviso.

Cómo se llaman, de qué lado vienen y cuánto dura el aviso.

Lo que se fija aquí es la traducción del nombre al lado, que es la parte que no
se puede equivocar: una etiqueta «versión de este dispositivo» puesta sobre la
versión del remoto haría que el usuario borrase justo la que quería conservar.
Esa traducción depende de los flags de la pareja igual que en rclone
(`cmd/bisync/resolve.go`), y por eso se prueba con varios juegos de flags.
"""

import json
import sys
import time
from dataclasses import replace
from pathlib import Path

from _harness import Checks, sandbox

from common import conflicts, model

c = Checks("conflictos de bisync (common/conflicts.py)")


def pareja(flags=None, mode="bisync", name="notas"):
    """Devuelve una pareja de mentira con esos flags y modo."""
    raw = {"name": name, "local": f"sync-data/{name}", "remote_path": f"/R/{name}",
           "mode": mode}
    if flags:
        raw["flags"] = flags
    return model.parse_config({"defaults": {"remote": "nas"}, "pair": [raw]}).pairs[0]


def escribir(ruta: Path, texto: str = "x") -> Path:
    """Escribe un fichero y devuelve su ruta."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8")
    return ruta


# el esquema de nombres sale de los flags, como en rclone
por_defecto = conflicts.esquema(pareja())
c("bisync trae sufijos distintos para cada lado",
  (por_defecto.sufijo1, por_defecto.sufijo2),
  (".conflicto-dispositivo", ".conflicto-remoto"))
c("y numera los perdedores (--conflict-loser num de rclone)", por_defecto.perdedor, "num")
c("el flag de verdad lo lleva la pareja, no un apaño del escáner",
  pareja().flags["conflict-suffix"], "conflicto-dispositivo,conflicto-remoto")

rclone_puro = conflicts.esquema(pareja({"conflict-suffix": "conflict"}))
c("un solo sufijo vale para los dos lados (setResolveDefaults)",
  (rclone_puro.sufijo1, rclone_puro.sufijo2), (".conflict", ".conflict"))

por_ruta = conflicts.esquema(pareja({"conflict-suffix": "conflict",
                                     "conflict-loser": "pathname"}))
c("pathname con un solo sufijo", por_ruta.perdedor, "pathname")

guion_bajo = conflicts.esquema(pareja({"conflict_suffix": "a,b"}))
c("el flag escrito con guion bajo también cuenta (flags_to_args los iguala)",
  (guion_bajo.sufijo1, guion_bajo.sufijo2), (".a", ".b"))


# del nombre al lado
def leer(nombre, esq=por_defecto):
    """Devuelve el lado y el original que `conflicts` lee en un nombre."""
    return conflicts.leer_nombre(nombre, esq)


c("path1 perdió: sufijo de este dispositivo",
  leer("plan.md.conflicto-dispositivo1"), ("plan.md", "path1", 1))
c("path2 perdió: sufijo del remoto",
  leer("plan.md.conflicto-remoto3"), ("plan.md", "path2", 3))
c("un fichero normal no es un conflicto", leer("plan.md"), None)
c("ni uno que solo lleva la palabra", leer("conflicto-remoto.md"), None)
c("un .conflictN viejo se reconoce, pero sin lado",
  leer("plan.md.conflict2"), ("plan.md", None, 2))
c("'.conflict' sin número no es de rclone", leer("plan.md.conflict"), None)

c("num con un solo sufijo: el número es un orden, no un lado",
  leer("plan.md.conflict1", rclone_puro), ("plan.md", None, 1))
c("pathname: .conflict1 es la de path1",
  leer("plan.md.conflict1", por_ruta), ("plan.md", "path1", 1))
c("pathname: .conflict2 es la de path2",
  leer("plan.md.conflict2", por_ruta), ("plan.md", "path2", 2))
c("pathname: un .conflict3 no puede ser suyo, queda sin lado",
  leer("plan.md.conflict3", por_ruta), ("plan.md", None, 3))

# El parser ya no admite `suffix-keep-extension` en `[pair.flags]` (lo pone
# sync.py), pero `esquema()` lo sigue leyendo de los flags: la pareja se monta a mano.
extension = conflicts.esquema(replace(pareja(), flags={**pareja().flags,
                                                       "suffix-keep-extension": True}))
c("--suffix-keep-extension: el sufijo va antes de la extensión",
  leer("plan.conflicto-remoto1.md", extension), ("plan.md", "path2", 1))
c("sin ese flag, un sufijo en medio no es un conflicto",
  leer("plan.conflicto-remoto1.md"), None)
versionada = model.parse_config({"defaults": {"remote": "nas"}, "pair": [
    {"name": "v", "local": "sync-data/v", "remote_path": "/R/v", "versions": True}]}).pairs[0]
c("con versions lo lleva siempre, aunque no esté en sus flags: lo pone sync.py",
  ("suffix-keep-extension" in versionada.flags, conflicts.esquema(versionada).mantener_extension),
  (False, True))

p = pareja()
c("en bisync path1 es el dispositivo",
  conflicts.lado(p, "path1"), conflicts.DISPOSITIVO)
c("y path2 el remoto", conflicts.lado(p, "path2"), conflicts.REMOTO)


# el escaneo
with sandbox():
    p = pareja()
    raiz = p.local_abs
    escribir(raiz / "plan.md", "del remoto")
    escribir(raiz / "plan.md.conflicto-dispositivo1", "de aquí")
    escribir(raiz / "sub" / "a.txt", "de aquí, ganó")
    escribir(raiz / "sub" / "a.txt.conflicto-remoto1", "del remoto, perdió")
    escribir(raiz / "sub" / "normal.txt")
    # Sin ganador (mismas fechas): rclone renombra los dos y el original desaparece.
    escribir(raiz / "b.txt.conflicto-dispositivo1")
    escribir(raiz / "b.txt.conflicto-remoto1")

    encontrados = conflicts.escanear(p)
    por_original = {x.original.name: x for x in encontrados}
    c("encuentra los tres ficheros en conflicto", sorted(por_original),
      ["a.txt", "b.txt", "plan.md"])
    c("y nada más", len(encontrados), 3)

    plan = por_original["plan.md"]
    c("perdió este dispositivo: su versión es la copia",
      plan.version(conflicts.DISPOSITIVO).ruta.name, "plan.md.conflicto-dispositivo1")
    c("y la del remoto es el original, que es el ganador",
      plan.version(conflicts.REMOTO).ruta.name, "plan.md")

    a = por_original["a.txt"]
    c("perdió el remoto: la de este dispositivo es el original",
      a.version(conflicts.DISPOSITIVO).ruta.name, "a.txt")
    c("y la del remoto la copia", a.version(conflicts.REMOTO).ruta.name,
      "a.txt.conflicto-remoto1")

    b = por_original["b.txt"]
    c("sin ganador: el original no está entre las versiones",
      [v.es_original for v in b.versiones], [False, False])
    c("sin ganador: cada copia con su lado",
      (b.version(conflicts.DISPOSITIVO).ruta.name, b.version(conflicts.REMOTO).ruta.name),
      ("b.txt.conflicto-dispositivo1", "b.txt.conflicto-remoto1"))
    c("la ruta que se enseña es relativa a la carpeta de la pareja", a.relativa, "sub/a.txt")

    # Dos veces perdió el mismo lado: el original ya no es «la del otro lado»
    # sin más, y la etiqueta de lado se le quita antes que inventarla.
    escribir(raiz / "plan.md.conflicto-dispositivo2")
    doble = next(x for x in conflicts.escanear(p) if x.original.name == "plan.md")
    c("dos copias del mismo lado: ninguna es «la» de ese lado",
      doble.version(conflicts.DISPOSITIVO), None)
    c("y el original queda sin lado", doble.versiones[0].lado, None)

    c("una pareja que no es bisync no tiene conflictos",
      conflicts.escanear(pareja(mode="up", name="notas")), [])

with sandbox():
    c("sin carpeta local no hay nada que escanear", conflicts.escanear(pareja()), [])


# El escaneo va tras cada pasada por TODA la carpeta: un nombre sin ninguno de
# los sufijos se descarta sin compilar patrones (con 20 000 ficheros eran 0,33 s
# de CPU por pasada).
def patrones_pedidos(p) -> tuple[int, list[str]]:
    """Escanea la pareja contando los patrones pedidos; devuelve la cuenta y los originales."""
    original = conflicts._patron
    pedidos = []

    def contado(sufijo, mantener_extension):
        """Cuenta el patrón y devuelve el de verdad."""
        pedidos.append(sufijo)
        return original(sufijo, mantener_extension)

    conflicts._patron = contado
    try:
        hallados = conflicts.escanear(p)
    finally:
        conflicts._patron = original
    return len(pedidos), [x.original.name for x in hallados]


with sandbox():
    p = pareja()
    escribir(p.local_abs / "plan.md.conflicto-remoto1")
    solo_conflicto, _ = patrones_pedidos(p)
    for i in range(40):
        escribir(p.local_abs / f"d{i % 4}" / f"nota{i}.md")
    con_normales, hallados = patrones_pedidos(p)
    c("el filtro previo no pierde el conflicto", hallados, ["plan.md"])
    c("y 40 ficheros normales más no piden ningún patrón", con_normales, solo_conflicto)


# Lo que no es de la pareja no se recorre: `.prversions/` guarda versiones, no
# conflictos, y en una pareja de la raíz entera el programa, el llavero y el
# ruido del sistema tampoco son contenido de nadie.
def pareja_raiz():
    """Devuelve una pareja bisync que sincroniza la raíz entera (`local = "."`)."""
    raw = {"name": "todo", "local": ".", "remote_path": "/R/todo", "mode": "bisync"}
    return model.parse_config({"defaults": {"remote": "nas"}, "pair": [raw]}).pairs[0]


def relativas(raiz: Path, rutas) -> list[str]:
    """Devuelve las rutas relativas a `raiz`, ordenadas y con `/`."""
    return sorted(r.relative_to(raiz).as_posix() for r in rutas)


with sandbox() as raiz_prueba:
    suelta = raiz_prueba / "arbol"
    escribir(suelta / "a.txt")
    escribir(suelta / ".prversions" / "b.txt")
    escribir(suelta / ".prversions" / "hondo" / "c.txt")
    escribir(suelta / "sub" / ".prversions" / "d.txt")
    escribir(suelta / "tmp.tmp")
    escribir(suelta / "sub" / "e.tmp")
    c("recorrer sin patrones devuelve todo lo que hay",
      relativas(suelta, conflicts.recorrer(suelta)),
      [".prversions/b.txt", ".prversions/hondo/c.txt", "a.txt", "sub/.prversions/d.txt",
       "sub/e.tmp", "tmp.tmp"])
    c("con patrones se saltan las carpetas y los ficheros de la raíz que casan",
      relativas(suelta, conflicts.recorrer(suelta, (".prversions", "*.tmp"))),
      ["a.txt", "sub/.prversions/d.txt", "sub/e.tmp"])

with sandbox():
    p = pareja()
    raiz = p.local_abs
    escribir(raiz / "plan.md")
    escribir(raiz / "plan.md.conflicto-remoto1")
    escribir(raiz / ".prversions" / "nota.md.conflicto-remoto1")
    escribir(raiz / ".prversions" / "hondo" / "otra.md.conflicto-dispositivo2")
    c("lo de .prversions no es un conflicto",
      [x.original.name for x in conflicts.escanear(p)], ["plan.md"])

    # Solo se poda la raíz de la pareja: más adentro, el nombre es de quien lo puso.
    escribir(raiz / "sub" / ".prversions" / "mia.md.conflicto-remoto1")
    c("y una carpeta con ese nombre más adentro sí es contenido",
      sorted(x.relativa for x in conflicts.escanear(p)),
      ["plan.md", "sub/.prversions/mia.md"])

    # El programa no es de una pareja que no sincroniza la raíz.
    escribir(raiz / model.APP_DIR.name / "tuya.md.conflicto-remoto1")
    c("en una pareja de una subcarpeta, una carpeta como la del programa es suya",
      sorted(x.relativa for x in conflicts.escanear(p)),
      sorted([f"{model.APP_DIR.name}/tuya.md", "plan.md", "sub/.prversions/mia.md"]))

with sandbox() as dispositivo:
    todo = pareja_raiz()
    c("la pareja de la raíz es la del dispositivo", todo.local_abs,
      dispositivo.resolve())
    escribir(dispositivo / "plan.md.conflicto-remoto1")
    escribir(dispositivo / "docs" / "acta.md.conflicto-dispositivo1")
    escribir(dispositivo / ".prversions" / "viejo.md.conflicto-remoto1")
    escribir(dispositivo / model.APP_DIR.name / "state" / "x.md.conflicto-remoto1")
    escribir(dispositivo / model.LLAVERO_LOCAL / "personal.conflicto-remoto1.kdbx")
    escribir(dispositivo / "System Volume Information" / "z.md.conflicto-remoto1")
    escribir(dispositivo / "$RECYCLE.BIN" / "w.md.conflicto-remoto1")
    c("en la raíz tampoco lo de .prdrive, el llavero ni el ruido del sistema",
      sorted(x.relativa for x in conflicts.escanear(todo)),
      ["docs/acta.md", "plan.md"])

    # Solo se poda lo que cuelga de la raíz.
    escribir(dispositivo / "docs" / model.LLAVERO_LOCAL / "mio.md.conflicto-remoto1")
    escribir(dispositivo / "docs" / "$RECYCLE.BIN" / "tuyo.md.conflicto-remoto1")
    c("más adentro, esos nombres son contenido",
      sorted(x.relativa for x in conflicts.escanear(todo)),
      ["docs/$RECYCLE.BIN/tuyo.md", f"docs/{model.LLAVERO_LOCAL}/mio.md", "docs/acta.md",
       "plan.md"])


# el estado persiste y se aclara solo
with sandbox():
    p = pareja()
    cfg = model.parse_config({"defaults": {"remote": "nas"},
                              "pair": [{"name": "notas", "local": "sync-data/notas",
                                        "remote_path": "/R/notas"}]})
    copia = escribir(p.local_abs / "x.md.conflicto-remoto1")
    escribir(p.local_abs / "x.md")
    conflicts.actualizar_pareja(p)
    c("el escaneo queda escrito en state/", conflicts.ruta_estado().exists(), True)
    c("se guarda relativo al dispositivo, no con la letra de unidad",
      conflicts.ruta_estado().read_text(encoding="utf-8").count(str(model.DEVICE_ROOT)), 0)

    cargados = conflicts.cargar(cfg)
    c("cargar lo lee sin recorrer el árbol", [x.original.name for x in cargados["notas"]],
      ["x.md"])

    copia.unlink()
    c("si la copia ya no está, el aviso se va solo", conflicts.cargar(cfg), {"notas": []})
    c("y el recuento también", conflicts.contar(conflicts.cargar(cfg)), {})

    escribir(p.local_abs / "y.md.conflicto-dispositivo1")
    c("refrescar escanea todas las parejas",
      [x.original.name for x in conflicts.refrescar(cfg)["notas"]], ["y.md"])
    c("contar da conflictos por pareja", conflicts.contar(conflicts.cargar(cfg)),
      {"notas": 1})

    conflicts.ruta_estado().write_text("{basura", encoding="utf-8")
    c("un estado ilegible es un estado vacío", conflicts.cargar(cfg), {"notas": []})


# Cada pasada vuelve a apuntar lo que encontró: si no ha cambiado nada, el
# fichero no se reescribe (en un pendrive, cada escritura gasta vida).
def mtime_estado() -> int:
    """Devuelve la fecha de modificación de `state/conflicts.json`, en ns."""
    return conflicts.ruta_estado().stat().st_mtime_ns


with sandbox():
    p = pareja()
    cfg = model.parse_config({"defaults": {"remote": "nas"},
                              "pair": [{"name": "notas", "local": "sync-data/notas",
                                        "remote_path": "/R/notas"}]})
    escribir(p.local_abs / "x.md")
    copia = escribir(p.local_abs / "x.md.conflicto-remoto1")
    conflicts.actualizar_pareja(p)
    antes = mtime_estado()
    contenido = conflicts.ruta_estado().read_text(encoding="utf-8")
    time.sleep(0.05)

    conflicts.actualizar_pareja(p)
    c("sin cambios no se reescribe conflicts.json", mtime_estado(), antes)
    conflicts.refrescar(cfg)
    c("refrescar con lo mismo tampoco lo reescribe", mtime_estado(), antes)
    c("y el contenido sigue siendo el mismo",
      conflicts.ruta_estado().read_text(encoding="utf-8"), contenido)

    nueva = escribir(p.local_abs / "y.md.conflicto-dispositivo1")
    conflicts.actualizar_pareja(p)
    c("si aparece un conflicto nuevo, se reescribe", mtime_estado() > antes, True)
    c("y lo apunta", sorted(x.relativa for x in conflicts.cargar(cfg)["notas"]),
      ["x.md", "y.md"])

    ahora = mtime_estado()
    time.sleep(0.05)
    nueva.unlink()
    copia.unlink()
    conflicts.actualizar_pareja(p)
    c("si desaparecen, también", mtime_estado() > ahora, True)
    c("y se queda sin conflictos", conflicts.contar(conflicts.cargar(cfg)), {})

    # Las parejas que ya no están en el config se caen al refrescar, y eso es
    # un cambio aunque la pareja que queda no haya cambiado.
    guardado = conflicts.ruta_estado()
    guardado.write_text(json.dumps({"cuando": "ayer", "parejas": {"vieja": ["sync-data/v/a.md.conflicto-remoto1"],
                                                                  "notas": []}}),
                        encoding="utf-8")
    conflicts.refrescar(cfg)
    c("una pareja que ya no está se cae del estado",
      sorted(json.loads(guardado.read_text(encoding="utf-8"))["parejas"]), ["notas"])

with sandbox():
    p = pareja()
    escribir(p.local_abs / "normal.md")
    conflicts.actualizar_pareja(p)
    primera = mtime_estado()
    time.sleep(0.05)
    conflicts.actualizar_pareja(p)
    c("sin ningún conflicto la primera pasada lo apunta y las demás no escriben",
      mtime_estado(), primera)

sys.exit(c.report())
