#!/usr/bin/env python3
"""
El registro de la flota: un fichero por dispositivo, y cada uno solo el suyo.

Lo que se comprueba es lo que hace que esto no pueda estropear nada: que la ruta
sale del catálogo y lleva el id dentro (así ningún dispositivo escribe sobre la
nota de otro), que lo que se publica se relee igual, que una nota rota o de una
versión futura no tumba la lista, y que la obsolescencia es una cuenta de días y
no una impresión.

El remoto se sustituye entero (`catalog.run`): aquí no se toca la red.
"""

import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from _harness import Checks, sandbox

from common import catalog, fleet, model, store

c = Checks("registro de la flota")

ENDPOINT = "nas:/prdrive-catalog/pairs.toml"
AYER = f"{datetime.now() - timedelta(days=1):%Y-%m-%d %H:%M:%S}"
HACE_UN_MES = f"{datetime.now() - timedelta(days=30):%Y-%m-%d %H:%M:%S}"

DISP = fleet.Dispositivo(id="a1b2c3", nombre="el pendrive azul", version="0.1.4",
                         plataformas=("windows-x64", "linux-x64"),
                         last_seen=AYER, last_result=fleet.RESULTADO_OK)


# --- dónde va cada nota ------------------------------------------------------
c("la carpeta cuelga de la del catálogo", fleet.carpeta_de(ENDPOINT),
  "nas:/prdrive-catalog/devices")
c("y sigue al catálogo si lo mueven",
  fleet.carpeta_de("nas:/otro/sitio/pairs.toml"), "nas:/otro/sitio/devices")
c("cada dispositivo escribe un fichero con SU id",
  fleet.fichero(ENDPOINT, "a1b2c3"), "nas:/prdrive-catalog/devices/a1b2c3.toml")
c("dos dispositivos, dos ficheros",
  fleet.fichero(ENDPOINT, "otro") != fleet.fichero(ENDPOINT, "a1b2c3"), True)


# --- el texto de la nota -----------------------------------------------------
texto = fleet.dumps(DISP)
c("lo publicado se relee exactamente igual", fleet.parse(texto), DISP)
c.contains("y lleva cabecera de quién lo escribe", texto, "nota de presencia")

c("una nota que no es TOML no tumba nada", fleet.parse("esto no { es toml"), None)
c("una nota sin id tampoco", fleet.parse('nombre = "x"\n'), None)
c("salvo que el nombre del fichero lo diga",
  (fleet.parse('nombre = "x"\n', "desde-el-fichero") or DISP).id, "desde-el-fichero")

# Una nota escrita por una versión futura, con campos que aquí no existen: lo
# que no se entienda se ignora, pero la fila tiene que salir igual.
futura = fleet.parse('id = "z9"\nnombre = "el nuevo"\ncosa_nueva = 42\n')
c("una nota de una versión futura se lee igual", (futura.id, futura.nombre), ("z9", "el nuevo"))
c("y lo que falta se enseña como desconocido", futura.version, "desconocida")


# --- obsoleto es una cuenta de días -------------------------------------------
c("visto ayer no es obsoleto", DISP.obsoleto(), False)
c("visto hace un mes sí", DISP._replace(last_seen=HACE_UN_MES).obsoleto(), True)
c("justo en el límite todavía no",
  DISP._replace(last_seen=f"{datetime.now() - timedelta(days=6, hours=23):%Y-%m-%d %H:%M:%S}"
                ).obsoleto(), False)
c("sin fecha legible cuenta como obsoleto", DISP._replace(last_seen="").obsoleto(), True)
c("el resultado distingue una pasada buena de una mala",
  (DISP.bien, DISP._replace(last_result="fallo en notas").bien), (True, False))

c("los vistos hace poco van primero",
  [d.id for d in fleet.ordenar([DISP._replace(id="viejo", last_seen=HACE_UN_MES), DISP])],
  ["a1b2c3", "viejo"])


# --- publicar ----------------------------------------------------------------
def falso_run(llamadas, rc=0, stderr=""):
    def _run(args):
        llamadas.append(list(args))
        return subprocess.CompletedProcess(args, rc, stdout="", stderr=stderr)
    return _run


CFG = {"defaults": {"remote": "nas", "catalog_path": "/prdrive-catalog/pairs.toml"},
       "pair": [{"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas"}]}

real_run, real_app = catalog.run, model.APP_DIR
try:
    with sandbox() as root:
        # El dispositivo se identifica por el fichero de control, que vive dentro
        # de la carpeta del programa. `sandbox()` NO reengancha `model.APP_DIR`
        # —hay tests que necesitan la de verdad—, así que aquí se hace a mano:
        # escribirlo en la real sería ensuciar el repositorio.
        model.APP_DIR = root / ".prdrive"
        model.APP_DIR.mkdir()
        (model.APP_DIR / "PRDRIVE").write_text("id=a1b2c3\n", encoding="utf-8")
        c("el id sale del fichero de control", fleet.device_id(), "a1b2c3")

        llamadas = []
        catalog.run = falso_run(llamadas)
        fleet.guardar_nombre("el pendrive azul")
        c("el nombre se guarda en el dispositivo", fleet.nombre(), "el pendrive azul")

        cfg = model.parse_config(CFG)
        c("se publica la nota", fleet.publicar(cfg, CFG), True)
        c("con un copyto a SU fichero", llamadas[-1][0], "copyto")
        c("y al sitio que dice el catálogo de este dispositivo",
          llamadas[-1][-1], "nas:/prdrive-catalog/devices/a1b2c3.toml")

        # Y ya no se repite: cuatro parejas por ciclo no son cuatro notas.
        llamadas.clear()
        c("una segunda pasada seguida no vuelve a subir nada",
          fleet.publicar(cfg, CFG), False)
        c("ni habla con el remoto", llamadas, [])
        c("salvo que se fuerce", fleet.publicar(cfg, CFG, forzar=True), True)

        # Lo que sí se cuenta enseguida es un cambio de fondo.
        fleet.guardar_nombre("el pendrive rojo")
        llamadas.clear()
        c("un cambio de nombre se publica ya", fleet.publicar(cfg, CFG), True)
        c("y queda apuntado lo último publicado",
          store.read_json(fleet.ruta_estado())["publicado"]["nombre"], "el pendrive rojo")

        # Un fallo de la pasada viaja en la nota: una flota en la que todos dicen
        # 'ok' no sirve para encontrar el dispositivo que lleva semanas fallando.
        from common import results
        results.apuntar("notas", 1, None)
        llamadas.clear()
        c("un fallo se publica", fleet.publicar(cfg, CFG), True)
        c.contains("y la nota lo dice", store.read_json(
            fleet.ruta_estado())["publicado"]["last_result"], "fallo en notas")

        # Sin remoto no pasa nada: es una nota, no la sincronización.
        catalog.run = falso_run([], rc=1, stderr="no such host")
        c("sin remoto, publicar falla en silencio",
          fleet.publicar(cfg, CFG, forzar=True), False)

        def reventar(args):
            raise OSError("el remoto ha desaparecido")
        catalog.run = reventar
        c("y una excepción tampoco sale de aquí",
          fleet.publicar(cfg, CFG, forzar=True), False)

    # Un dispositivo sin fichero de control no tiene a quién apuntar.
    with sandbox() as root:
        model.APP_DIR = root / ".prdrive"
        catalog.run = falso_run([])
        c("sin fichero de control no se publica nada", fleet.publicar(None, CFG), False)

    # --- leer la flota -------------------------------------------------------
    with sandbox():
        otros = [DISP, DISP._replace(id="d2", nombre="el del trabajo",
                                     last_seen=HACE_UN_MES)]

        def run_con_copia(args):
            """Simula el `rclone copy` de la carpeta: deja las notas en el destino."""
            c("la flota se lee de una sola vez", args[0], "copy")
            destino = Path(args[2])
            for d in otros:
                (destino / f"{d.id}{fleet.SUFIJO}").write_text(fleet.dumps(d),
                                                              encoding="utf-8")
            (destino / "rota.toml").write_text("{ esto no", encoding="utf-8")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        catalog.run = run_con_copia
        flota, aviso = fleet.leer(CFG)
        c("salen los dispositivos que han dejado nota", [d.id for d in flota],
          ["a1b2c3", "d2"])
        c("y sin aviso", aviso, None)
        c("una nota rota se ignora, el resto sale", len(flota), 2)
        c("el del cajón se marca como obsoleto",
          [d.obsoleto() for d in flota], [False, True])

        catalog.run = falso_run([], rc=1, stderr="no such host")
        flota, aviso = fleet.leer(CFG)
        c("sin remoto la lista sale vacía", flota, [])
        c.contains("con el motivo", aviso or "", "no such host")

        # Una flota en la que todavía no ha dejado nota nadie: la carpeta no
        # existe, y eso NO es un fallo de conexión (rclone lo distingue con su
        # propio código de salida).
        catalog.run = falso_run([], rc=fleet.RC_SIN_CARPETA,
                                stderr="directory not found")
        c("una carpeta que aún no existe es una flota vacía, sin aviso",
          fleet.leer(CFG), ([], None))
finally:
    catalog.run, model.APP_DIR = real_run, real_app

sys.exit(c.report())
