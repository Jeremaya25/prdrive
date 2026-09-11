#!/usr/bin/env python3
"""
Los ficheros en conflicto de bisync: cómo se llaman, de qué lado vienen y cuánto
dura el aviso.

Lo que se fija aquí es la traducción del nombre al lado, que es la parte que no
se puede equivocar: una etiqueta «versión de este dispositivo» puesta sobre la
versión del remoto haría que el usuario borrase justo la que quería conservar.
Esa traducción depende de los flags de la pareja igual que en rclone
(`cmd/bisync/resolve.go`), y por eso se prueba con varios juegos de flags.
"""

import sys
from pathlib import Path

from _harness import Checks, sandbox

from common import conflicts, model

c = Checks("conflictos de bisync (common/conflicts.py)")


def pareja(flags=None, mode="bisync", name="notas"):
    raw = {"name": name, "local": f"sync-data/{name}", "remote_path": f"/R/{name}",
           "mode": mode}
    if flags:
        raw["flags"] = flags
    return model.parse_config({"defaults": {"remote": "nas"}, "pair": [raw]}).pairs[0]


def escribir(ruta: Path, texto: str = "x") -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8")
    return ruta


# --- el esquema de nombres sale de los flags, como en rclone -----------------
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


# --- del nombre al lado ------------------------------------------------------
def leer(nombre, esq=por_defecto):
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

extension = conflicts.esquema(pareja({"suffix-keep-extension": True}))
c("--suffix-keep-extension: el sufijo va antes de la extensión",
  leer("plan.conflicto-remoto1.md", extension), ("plan.md", "path2", 1))
c("sin ese flag, un sufijo en medio no es un conflicto",
  leer("plan.conflicto-remoto1.md"), None)

p = pareja()
c("en bisync path1 es el dispositivo",
  conflicts.lado(p, "path1"), conflicts.DISPOSITIVO)
c("y path2 el remoto", conflicts.lado(p, "path2"), conflicts.REMOTO)


# --- el escaneo ----------------------------------------------------------------
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


# --- el estado persiste y se aclara solo ---------------------------------------
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

sys.exit(c.report())
