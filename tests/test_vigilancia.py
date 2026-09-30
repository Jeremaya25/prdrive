#!/usr/bin/env python3
"""
Vigilancia de cambios: `watch = true` dispara una pasada de esa pareja cuando
sus ficheros cambian y se calman.

Lo que hay que sujetar: la calma (muchos cambios seguidos son UNA pasada), la
separación mínima (sin perder lo que cambia mientras tanto), que `.prversions/`
no cuenta, que lo que cambia durante la pasada queda pendiente, y que la clave
solo vale donde la carpeta local es el origen.
"""

import os
from pathlib import Path

from _harness import Checks, sandbox

from common import model, vigilancia
from common.model import ConfigError

c = Checks("vigilancia: cambios en ficheros → pasada de la pareja")


def pareja(extra):
    raw = {"name": "n", "local": "datos", "remote_path": "/x", **extra}
    return model.parse_config({"defaults": {"remote": "nas"}, "pair": [raw]}).pairs[0]


# --- 1. la clave ----------------------------------------------------------------
c("por defecto no vigila", pareja({}).watch, False)
c("bisync admite watch", pareja({"mode": "bisync", "watch": True}).watch, True)
c("up admite watch", pareja({"mode": "up", "watch": True}).watch, True)
for modo in ("down", "down-mirror"):
    try:
        pareja({"mode": modo, "watch": True})
        c(f"{modo} rechaza watch", "aceptada", "ConfigError")
    except ConfigError as e:
        c(f"{modo} rechaza watch", "'watch'" in str(e), True)

# --- 2. el recorrido ------------------------------------------------------------
with sandbox() as root:
    carpeta = root / "datos"
    (carpeta / "a").mkdir(parents=True)
    (carpeta / ".prversions").mkdir()
    (carpeta / "a" / "uno.txt").write_text("1")
    (carpeta / ".prversions" / "x~1.txt").write_text("v")
    foto = vigilancia.instantanea(carpeta, ignorar=(model.VERSIONS_DIR,))
    c("ve los ficheros con ruta relativa y «/»", sorted(foto), ["a/uno.txt"])
    c("una carpeta que no existe es una instantánea vacía",
      vigilancia.instantanea(root / "nada"), {})
    (carpeta / "a" / "uno.txt").write_text("12")
    c("otro tamaño es un cambio",
      vigilancia.cambiada(foto, vigilancia.instantanea(carpeta, (model.VERSIONS_DIR,))), True)
    try:
        vigilancia.instantanea(carpeta, tope=0)
        c("pasado el tope avisa", "no", "Excedido")
    except vigilancia.Excedido:
        c("pasado el tope avisa", "sí", "sí")


# --- 3. las reglas, con reloj y recorrido de mentira ------------------------------
class Carpeta:
    """El 'disco': lo que devuelve el recorrido."""
    def __init__(self):
        self.contenido = {"f": (1, 1)}

    def __call__(self, ruta, ignorar):
        return dict(self.contenido)

    def toca(self):
        n = self.contenido["f"][0] + 1
        self.contenido["f"] = (n, 1)


disco = Carpeta()
avisos = []
v = vigilancia.Vigia({"p": Path("x")}, cada=1, calma=10, minimo=60,
                     recorrer=disco, avisar=avisos.append)

c("la primera vez solo toma nota", v.mirar(0), [])
c("sin cambios no hay nada", v.mirar(5), [])
disco.toca()
c("un cambio no dispara aún (calma)", v.mirar(6), [])
c("queda pendiente", v.pendiente("p"), True)
disco.toca()
c("otro cambio reinicia la calma", v.mirar(12), [])
c("a los 9 s del último sigue esperando", v.mirar(20), [])
c("pasada la calma dispara", v.mirar(22), ["p"])
c("y no se repite", v.mirar(23), [])

# Durante la pasada: la instantánea se toma antes, y lo que cambia después cuenta.
v.iniciar("p", 30)
c("tras iniciar ya no hay pendiente", v.pendiente("p"), False)
disco.toca()
c("lo que cambia durante la pasada se ve", v.mirar(32), [])
c("y queda pendiente", v.pendiente("p"), True)
c("pero la separación mínima lo retiene", v.mirar(45), [])
c("sin perderlo: dispara cuando pasa el mínimo", v.mirar(83), ["p"])

# --- 4. el tope apaga solo esa pareja ---------------------------------------------
def demasiado(ruta, ignorar):
    raise vigilancia.Excedido(str(ruta))


v2 = vigilancia.Vigia({"g": Path("x")}, cada=1, calma=1, minimo=1,
                      recorrer=demasiado, avisar=avisos.append)
c("con demasiados ficheros no dispara", v2.mirar(0), [])
c("lo dice una vez", len(avisos), 1)
c("y sigue sin disparar", v2.mirar(100), [])
c("sin repetir el aviso", len(avisos), 1)

# --- 5. el servicio: pasada parcial y toma de la instantánea ---------------------
import runsync
from common import update

runsync.dlog = lambda texto: None
runsync.pen_present = lambda: True
runsync.stop_requested = lambda: False
runsync.write_lock = lambda data: None
runsync.notificar_fallo = lambda nombres: None
update.check = lambda force=False: (None, None)
update.pending = lambda root=None: None
lanzadas = []
runsync.run_pair_quiet = lambda name: (lanzadas.append(name) or 0, "salida")


class VigiaFalsa:
    def __init__(self):
        self.iniciadas = []

    def iniciar(self, nombre, ahora):
        self.iniciadas.append((nombre, len(lanzadas)))


lock = {"last_results": {"otra": "OK (1s)", "p": "ERROR rc=1"}}
falsa = VigiaFalsa()
runsync.daemon_cycle(["p"], lock, falsa, parcial=True)
c("una pasada parcial lanza solo esa pareja", lanzadas, ["p"])
c("la instantánea se toma ANTES de lanzarla", falsa.iniciadas, [("p", 0)])
c("conserva el resultado de las demás",
  sorted(lock["last_results"]), ["otra", "p"])
c("y actualiza el de la pareja", lock["last_results"]["p"].startswith("OK"), True)
lock = {"last_results": {"otra": "OK (1s)"}}
runsync.daemon_cycle(["p"], lock)
c("un ciclo completo sí sustituye los resultados", sorted(lock["last_results"]), ["p"])

raise SystemExit(c.report())
