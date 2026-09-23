#!/usr/bin/env python3
"""
El registro de la flota: un fichero por dispositivo, y cada uno solo el suyo.

Lo que se comprueba es lo que hace que esto no pueda estropear nada: que la ruta
sale del catálogo y lleva el id dentro (así ningún dispositivo escribe sobre la
nota de otro), que lo que se publica se relee igual, que una nota rota o de una
versión futura no tumba la lista, y que la obsolescencia es una cuenta de días y
no una impresión. Y lo de la ficha: que la lista de equipos se hereda de la nota
anterior sin crecer ni repetirse, que el freno solo la deja pasar al cambiar de
equipo, y desde cuándo falla.

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

# --- dónde ha estado, y desde cuándo falla ------------------------------------
# Dos listas paralelas y no una lista de tablas: el serializador solo escribe
# escalares y listas de cadenas, y una nota de presencia no merece enseñarle más.
Equipo = fleet.Equipo
COMPLETA = DISP._replace(
    equipos=(Equipo("PORTATIL", AYER), Equipo("OFICINA-07", HACE_UN_MES)),
    last_result="fallo en fotos", ultima_buena=HACE_UN_MES)
c("una nota con equipos y última buena se relee igual",
  fleet.parse(fleet.dumps(COMPLETA)), COMPLETA)
c.contains("los equipos van en una lista", fleet.dumps(COMPLETA), "equipos = [")
c.contains("y sus fechas en otra, paralela", fleet.dumps(COMPLETA), "equipos_visto = [")
c("una nota sin equipos ni fallo no escribe esas claves",
  [k for k in ("equipos", "ultima_buena") if k in texto], [])

vieja = fleet.parse('id = "v"\nnombre = "de la 0.2.3"\n')
c("una nota de antes de los equipos no trae ninguno", vieja.equipos, ())
c("ni última buena", vieja.ultima_buena, "")
c("unos equipos que no son una lista no son ninguno",
  fleet.parse('id = "x"\nequipos = "PORTATIL"\n').equipos, ())
c("listas desparejadas: al que le falta la fecha se le deja vacía",
  fleet.parse('id = "d"\nequipos = ["A", "B"]\n'
              'equipos_visto = ["2026-09-01 10:00:00"]\n').equipos,
  (Equipo("A", "2026-09-01 10:00:00"), Equipo("B", "")))
c("una entrada que no es cadena se descarta, y su fecha con ella",
  fleet.parse('id = "r"\nequipos = ["A", 7, "C"]\n'
              'equipos_visto = ["1", "2", 3]\n').equipos,
  (Equipo("A", "1"), Equipo("C", "")))
larga = fleet.parse('id = "l"\nequipos = ['
                    + ", ".join(f'"E{i}"' for i in range(fleet.MAX_EQUIPOS + 3)) + "]\n")
c("más equipos de la cuenta se cortan al leer", len(larga.equipos), fleet.MAX_EQUIPOS)
c("y se quedan los primeros, que son los más recientes", larga.equipos[0].nombre, "E0")


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

real_run, real_app, real_equipo = catalog.run, model.APP_DIR, fleet.equipo_actual
try:
    with sandbox() as root:
        # El nombre del equipo que ejecuta los tests no es algo que un test
        # pueda afirmar: se sustituye, como el remoto.
        fleet.equipo_actual = lambda: "PORTATIL"
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

        def publicado():
            return store.read_json(fleet.ruta_estado())["publicado"]

        c("con desde cuándo: de esa pareja no consta ninguna pasada buena",
          publicado()["ultima_buena"], fleet.SIN_BUENA)

        # --- dónde ha estado ---------------------------------------------------
        # La lista se hereda de la última nota publicada, con el equipo de ahora
        # delante: ninguna escritura nueva en el dispositivo.
        def equipos():
            return list(publicado().get("equipos", []))

        c("la nota lleva el equipo desde el que se publica", equipos(), ["PORTATIL"])
        c("con la hora de la pasada, la misma que last_seen",
          publicado()["equipos_visto"], [publicado()["last_seen"]])

        llamadas.clear()
        c("en el mismo equipo el freno no cambia", fleet.publicar(cfg, CFG), False)

        fleet.equipo_actual = lambda: "OFICINA-07"
        c("enchufado en otro equipo se publica en la primera pasada",
          fleet.publicar(cfg, CFG), True)
        c("con el nuevo delante", equipos(), ["OFICINA-07", "PORTATIL"])

        fleet.equipo_actual = lambda: "PORTATIL"
        fleet.publicar(cfg, CFG)
        c("volver a uno que ya estaba lo pasa al frente sin repetirlo",
          equipos(), ["PORTATIL", "OFICINA-07"])

        for i in range(fleet.MAX_EQUIPOS):
            fleet.equipo_actual = lambda i=i: f"AULA-{i}"
            fleet.publicar(cfg, CFG)
        c("la lista no pasa de MAX_EQUIPOS, y se van los más antiguos",
          equipos(), [f"AULA-{i}" for i in reversed(range(fleet.MAX_EQUIPOS))])

        antes = equipos()
        fleet.equipo_actual = lambda: ""
        c("sin nombre de equipo la lista se queda como estaba",
          [e.nombre for e in fleet.nota(cfg).equipos], antes)
        c("y no hace publicar", fleet.publicar(cfg, CFG), False)

        # Lo que dejó apuntado una 0.2.3 no trae equipos: tras actualizar se
        # publica una vez, que es lo que se quiere, y solo una.
        fleet.equipo_actual = lambda: "AULA-4"
        datos = store.read_json(fleet.ruta_estado())
        for clave in ("equipos", "equipos_visto", "ultima_buena"):
            datos["publicado"].pop(clave, None)
        store.write_json(fleet.ruta_estado(), datos)
        c("lo publicado por una versión sin equipos hace publicar una vez",
          fleet.publicar(cfg, CFG), True)
        c("y solo una", fleet.publicar(cfg, CFG), False)

        # Sin red en un equipo nuevo no se apunta nada, y el reintento sale solo:
        # el equipo sigue sin ser el de la última nota.
        fleet.equipo_actual = lambda: "SOBREMESA"
        antes = equipos()
        catalog.run = falso_run([], rc=1, stderr="no such host")
        c("sin red en un equipo nuevo no se publica", fleet.publicar(cfg, CFG), False)
        c("ni se apunta como publicado", equipos(), antes)
        catalog.run = falso_run(llamadas)
        c("y la pasada siguiente lo reintenta sola", fleet.publicar(cfg, CFG), True)
        c("con la lista que no pudo subir", equipos(), ["SOBREMESA"] + antes)

        # «Reinstalar desde cero» renueva el id: para la flota es otro
        # dispositivo, y no hereda dónde estuvo el anterior.
        (model.APP_DIR / "PRDRIVE").write_text("id=reinstalado\n", encoding="utf-8")
        c("con otro id la lista empieza de cero",
          [e.nombre for e in fleet.nota(cfg).equipos], ["SOBREMESA"])
        (model.APP_DIR / "PRDRIVE").write_text("id=a1b2c3\n", encoding="utf-8")

        # --- desde cuándo falla ----------------------------------------------
        # Resultado y fecha salen de UNA lectura de `results`, así que no pueden
        # contradecirse.
        cfg2 = model.parse_config({"defaults": CFG["defaults"], "pair": [
            CFG["pair"][0],
            {"name": "fotos", "local": "sync-data/fotos", "remote_path": "/R/fotos"}]})

        def registro(**parejas):
            store.write_json(results.ruta_estado(), {"parejas": parejas})

        def fallo(buena):
            return {"cuando": "2026-09-20 10:00:00", "codigo": 1, "log": None,
                    "buena": buena}

        BIEN = {"cuando": "2026-09-20 10:00:00", "codigo": 0, "log": None,
                "buena": "2026-09-20 10:00:00"}
        registro(notas=BIEN, fotos=BIEN)
        c("si todo va bien no hay fecha de última buena", fleet.estado(cfg2), ("ok", ""))
        registro(notas=fallo("2026-09-10 08:00:00"), fotos=BIEN)
        c("si falla una, su última pasada buena", fleet.estado(cfg2),
          ("fallo en notas", "2026-09-10 08:00:00"))
        registro(notas=fallo("2026-09-10 08:00:00"), fotos=fallo("2026-09-01 08:00:00"))
        c("si fallan dos, la más antigua: desde entonces hay algo roto",
          fleet.estado(cfg2), ("fallo en notas, fotos", "2026-09-01 08:00:00"))
        registro(notas=fallo("2026-09-10 08:00:00"), fotos=fallo(None))
        c("si de alguna no consta ninguna, se dice eso",
          fleet.estado(cfg2)[1], fleet.SIN_BUENA)
        c("sin config no hay nada que haya fallado", fleet.estado(None), ("ok", ""))

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

        # --- quitar de la lista la nota de otro ------------------------------
        # La única escritura de este módulo sobre el fichero de OTRO. No destruye
        # nada —el dueño vuelve a publicarla en cuanto se enchufe—, pero sí tiene
        # a alguien esperando respuesta, así que dice qué ha pasado.
        llamadas = []
        catalog.run = falso_run(llamadas)
        c("quitar la nota de otro sale bien", fleet.olvidar("d2", CFG), None)
        c("y es un deletefile de SU fichero, no de la carpeta",
          llamadas[-1], ["deletefile", "nas:/prdrive-catalog/devices/d2.toml"])

        antes = len(llamadas)
        fallo = fleet.olvidar(fleet.device_id(), CFG)
        c("este dispositivo no puede quitarse a sí mismo", bool(fallo), True)
        c("y ni siquiera se le pide nada al remoto", len(llamadas), antes)

        c("sin id no se quita nada", bool(fleet.olvidar("", CFG)), True)

        catalog.run = falso_run([], rc=1, stderr="no such host")
        c.contains("un fallo del remoto se cuenta, no se traga",
                   fleet.olvidar("d2", CFG) or "", "no such host")

        # Ya no estaba: es el resultado que se pedía, por otro camino.
        catalog.run = falso_run([], rc=fleet.RC_SIN_CARPETA,
                                stderr="directory not found")
        c("una nota que ya no está no es un fallo", fleet.olvidar("d2", CFG), None)

        def reventar_borrado(args):
            raise OSError("el remoto se ha caído a media orden")

        catalog.run = reventar_borrado
        c("y una excepción tampoco sale de aquí",
          bool(fleet.olvidar("d2", CFG)), True)
finally:
    catalog.run, model.APP_DIR, fleet.equipo_actual = real_run, real_app, real_equipo

sys.exit(c.report())
