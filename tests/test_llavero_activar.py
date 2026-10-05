#!/usr/bin/env python3
"""Activar, cambiar y desactivar el llavero (`ui/llavero_editor.py`, «Ajustes → Llavero…»).

Sin red: el catálogo se da ya leído y `catalog.push()` apunta lo que subiría.
Lo que se sujeta:
- Con una base propia y un remoto sin llavero, la base se COPIA (la original no
  se toca), `[keychain]` va al catálogo y al config, y se ponen `LEEME.txt` y
  `Llavero.bat`. Si la subida falla, no se toca nada del dispositivo.
- Si el remoto ya tiene llavero, la base es la suya: una propia entra como
  copia de conflicto, para combinarla al abrir, y no se sube nada.
- Lo que no es una base entera no entra; una KDBX 3.1 avisa; `.KDBX` se
  normaliza, porque el filtro distingue.
- El fichero llave: solo su ruta, por equipo; cambiar si la base lo pide va al
  catálogo y al config.
- Desactivar quita `[keychain]` y `Llavero.bat`; la carpeta y el remoto se quedan.
"""

import hashlib
import struct
import sys
from pathlib import Path

from _harness import Checks, sandbox, tmpdir

from common import catalog, config_file, kdbx, keepassxc, llavero, model
from common.model import ConfigError
from ui import llavero_editor

c = Checks("activar el llavero")

DEF = {"remote": "nas", "catalog_path": "/prdrive-catalog/remote.toml"}
NOTAS = {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas"}
RAIZ = {"name": "todo", "local": ".", "remote_path": "/copia"}
LOCAL = {"defaults": DEF, "pair": [NOTAS]}
CATALOGO = {"defaults": {"remote": "nas"}, "pair": [NOTAS]}


def base_kdbx(mayor: int = 4) -> bytes:
    """Una base de KeePassXC de mentira, entera (la forma de `test_kdbx.py`)."""
    ancho = "<BH" if mayor == 3 else "<BI"
    cab = struct.pack("<IIHH", kdbx.FIRMA_1, kdbx.FIRMA_2, 1, mayor)
    campos = [(4, b"\x07" * 32), (0, b"\r\n\r\n")]
    if mayor == 3:
        campos.insert(0, (2, bytes.fromhex("31c1f2e6bf714350be5805216afc5aff")))
    for campo, valor in campos:
        cab += struct.pack(ancho, campo, len(valor)) + valor
    if mayor == 3:
        return cab + b"\xaa" * 64
    datos = cab + hashlib.sha256(cab).digest() + b"\x01" * 32
    for bloque in (b"x" * 100, b""):
        datos += b"\x02" * 32 + struct.pack("<i", len(bloque)) + bloque
    return datos


def leido(raw=CATALOGO, source="remote") -> catalog.Catalog:
    """El catálogo como si se acabara de leer del remoto."""
    texto = config_file.dumps(raw)
    return catalog.Catalog(raw=dict(raw), text=texto, source=source,
                           stamp="2026-10-05 10:00:00",
                           endpoint="nas:/prdrive-catalog/remote.toml")


def rechaza(etiqueta, hacer, fragmento):
    """Comprueba que `hacer()` lance `ConfigError` con ese fragmento."""
    try:
        hacer()
        c(etiqueta, "no lanzó", "ConfigError")
    except ConfigError as e:
        c.contains(etiqueta, str(e), fragmento)


subidas: list = []
real_push, real_ejecutable = catalog.push, keepassxc.ejecutable
catalog.push = lambda new_raw, base_text, raw_local=None: (
    subidas.append((dict(new_raw), base_text)), ["catálogo subido"])[1]
keepassxc.ejecutable = lambda: Path("/no/esta/KeePassXC.exe")

try:
    origenes = tmpdir("prdrive-origen-")
    propia = origenes / "Claves.KDBX"
    propia.write_bytes(base_kdbx())

    # una base propia, y un remoto sin llavero
    with sandbox() as root:
        config_file.save(LOCAL)
        rechaza("sin el catálogo recién leído, no", lambda: llavero_editor.plan_activar(
            LOCAL, leido(source="cache"), propia), "hace falta haber leído el catálogo")
        llave = root / "fuera" / "claves.keyx"
        plan = llavero_editor.plan_activar(LOCAL, leido(), propia, pide=True,
                                           nombre_llave="claves.keyx", llave=llave)
        texto = " ".join(plan.consequences)
        c.contains("el plan dice que se copia y que la original no se toca", texto,
                   "La original se queda donde está, sin tocar")
        c.contains("  que el catálogo apunta el llavero", texto, "[keychain] en remote.toml")
        c.contains("  el fichero llave: solo dónde está", texto,
                   "el fichero no se copia ni se lee")
        c.contains("  y que este equipo aún no tiene KeePassXC", " ".join(plan.warnings),
                   "lo pone «Actualizar…»")
        c("  deja el llavero activo: toca la primera pasada", plan.activa, True)
        c("nada se ha escrito antes de confirmar",
          (subidas, llavero.carpeta().exists(), "keychain" in config_file.load_raw()),
          ([], False, False))

        hechos = plan.execute()
        tabla = {"base": "Claves.kdbx", "fichero_llave": True, "nombre_llave": "claves.keyx"}
        c("al catálogo va [keychain], y nada más cambia",
          (subidas[-1][0].get("keychain"), subidas[-1][0]["pair"]), (tabla, CATALOGO["pair"]))
        c("  al config, el mismo [keychain]", config_file.load_raw().get("keychain"), tabla)
        c("  la base, copiada con .kdbx en minúsculas",
          (llavero.carpeta() / "Claves.kdbx").read_bytes(), base_kdbx())
        c("  la original, donde estaba", propia.read_bytes(), base_kdbx())
        c("  con su compañero fijo", (llavero.carpeta() / llavero.LEEME).is_file(), True)
        c("  y Llavero.bat, que llama a runsync.bat --llavero",
          (root / llavero.LANZADOR).read_bytes().decode("ascii").splitlines()[-1],
          'call "%~dp0runsync.bat" --llavero')
        c("  con \\r\\n, como cualquier .bat",
          (root / llavero.LANZADOR).read_bytes().count(b"\r\n") == 5, True)
        c("  y llavero.sh a su lado, para Linux", (root / llavero.LANZADOR_LINUX).is_file(), True)
        c("  la ruta del fichero llave, de este equipo", keepassxc.llave_apuntada(), llave)
        c("  y lo cuenta", hechos[0], "catálogo subido")
        c("el config resultante tiene la pareja del llavero",
          model.load_config().pareja_llavero is not None, True)

    # si la subida falla, el dispositivo no se toca
    with sandbox():
        config_file.save(LOCAL)
        plan = llavero_editor.plan_activar(LOCAL, leido(), propia)
        catalog.push = lambda *a, **k: (_ for _ in ()).throw(ConfigError("sin red"))
        rechaza("si no se puede escribir el catálogo, se dice", plan.execute, "sin red")
        c("  y el dispositivo sigue sin llavero",
          (llavero.carpeta().exists(), "keychain" in config_file.load_raw()), (False, False))
        catalog.push = lambda new_raw, base_text, raw_local=None: (
            subidas.append((dict(new_raw), base_text)), ["catálogo subido"])[1]

    # el remoto ya tiene llavero: la base es la suya
    con_llavero = {**CATALOGO, "keychain": {"base": "personal.kdbx", "fichero_llave": False}}
    with sandbox():
        config_file.save(LOCAL)
        subidas.clear()
        plan = llavero_editor.plan_activar(LOCAL, leido(con_llavero), propia)
        texto = " ".join(plan.consequences)
        c.contains("con llavero en el remoto, la propia entra como copia de conflicto", texto,
                   "como copia de conflicto de personal.kdbx")
        c.contains("  y se dice que la primera pasada trae la del remoto", texto,
                   "El remoto ya tiene un llavero, personal.kdbx")
        plan.execute()
        c("  no se sube nada", subidas, [])
        c("  el config lleva el [keychain] del remoto", config_file.load_raw()["keychain"],
          con_llavero["keychain"])
        c("  y la base propia, con el nombre que rclone daría a la de este lado",
          [r.name for r in llavero.bases(llavero.carpeta())],
          ["personal.conflicto-dispositivo1.kdbx"])

    # «Traer el del remoto»
    with sandbox() as root:
        config_file.save(LOCAL)
        rechaza("sin llavero en el remoto no hay qué traer",
                lambda: llavero_editor.plan_activar(LOCAL, leido(), None), "no tiene llavero")
        pide = {**CATALOGO, "keychain": {"base": "personal.kdbx", "fichero_llave": True,
                                         "nombre_llave": "personal.keyx"}}
        llave = root / "personal.keyx"
        plan = llavero_editor.plan_activar(LOCAL, leido(pide), None, llave=llave)
        c.contains("traerlo: lo baja la primera pasada", " ".join(plan.consequences),
                   "la primera pasada lo trae al dispositivo")
        c.contains("  y dice el fichero llave que pide, por su nombre",
                   " ".join(plan.consequences), "«personal.keyx»")
        subidas.clear()
        plan.execute()
        c("  sin subir nada, sin copiar nada, con la ruta de este equipo",
          (subidas, llavero.bases(llavero.carpeta()), keepassxc.llave_apuntada()),
          ([], [], llave))

    # lo que no es una base
    with sandbox():
        config_file.save(LOCAL)
        rota = origenes / "rota.kdbx"
        rota.write_bytes(base_kdbx()[:-10])
        rechaza("una base cortada no entra", lambda: llavero_editor.plan_activar(
            LOCAL, leido(), rota), "no es una base de KeePassXC entera")
        texto = origenes / "notas.txt"
        texto.write_text("hola", encoding="utf-8")
        rechaza("ni algo que no es .kdbx", lambda: llavero_editor.plan_activar(
            LOCAL, leido(), texto), "no es una base de KeePassXC (.kdbx)")
        vieja = origenes / "vieja.kdbx"
        vieja.write_bytes(base_kdbx(3))
        c.contains("una KDBX 3.1 entra, avisando de que KeePassXC la pasa a KDBX 4",
                   " ".join(llavero_editor.plan_activar(LOCAL, leido(), vieja).warnings),
                   "la pasa a KDBX 4")

    # una pareja de la raíz entera pedirá un resync
    with sandbox():
        raw = {"defaults": DEF, "pair": [NOTAS, {**RAIZ}]}
        config_file.save(raw)
        c.contains("con una pareja bisync de la raíz, se avisa del --resync",
                   " ".join(llavero_editor.plan_activar(raw, leido(), propia).warnings),
                   "«todo» sincroniza la raíz entera")

    # si la base pide fichero llave, aquí y en el catálogo
    with sandbox() as root:
        raw = {**LOCAL, "keychain": {"base": "personal.kdbx", "fichero_llave": False}}
        config_file.save(raw)
        rechaza("cambiarlo con un remoto que no tiene este llavero, no",
                lambda: llavero_editor.plan_pide_llave(raw, leido(), True), "no tiene este llavero")
        cat = leido({**CATALOGO, "keychain": {"base": "personal.kdbx", "fichero_llave": False}})
        llave = root / "personal.keyx"
        plan = llavero_editor.plan_pide_llave(raw, cat, True, "personal.keyx", llave)
        c.contains("el plan dice que es aquí y en el catálogo", plan.consequences[0],
                   "pide el fichero llave «personal.keyx», aquí y en el catálogo")
        subidas.clear()
        plan.execute()
        tabla = {"base": "personal.kdbx", "fichero_llave": True, "nombre_llave": "personal.keyx"}
        c("  sube el [keychain] cambiado y lo escribe aquí",
          (subidas[-1][0]["keychain"], config_file.load_raw()["keychain"]), (tabla, tabla))
        c("  con la ruta de este equipo", keepassxc.llave_apuntada(), llave)
        raw = config_file.load_raw()
        llavero_editor.plan_pide_llave(raw, leido({**CATALOGO, "keychain": tabla}), False).execute()
        c("y quitarlo quita el nombre y la ruta",
          (config_file.load_raw()["keychain"], keepassxc.llave_apuntada()),
          ({"base": "personal.kdbx", "fichero_llave": False}, None))

    # desactivarlo
    with sandbox() as root:
        raw = {**LOCAL, "pair": [NOTAS, RAIZ], "keychain": {"base": "personal.kdbx"}}
        config_file.save(raw)
        llavero.preparar_carpeta()
        (llavero.carpeta() / "personal.kdbx").write_bytes(base_kdbx())
        llavero.escribir_lanzador()
        plan = llavero_editor.plan_desactivar(raw)
        c.contains("desactivar dice que la carpeta y el remoto no se tocan",
                   " ".join(plan.consequences), "el remoto no se toca")
        c.contains("  y que una pareja de la raíz se la llevaría", " ".join(plan.warnings),
                   ".keychain/ viajará con ella")
        plan.execute()
        c("quita [keychain] y Llavero.bat; la base se queda",
          ("keychain" in config_file.load_raw(), (root / llavero.LANZADOR).exists(),
           (llavero.carpeta() / "personal.kdbx").is_file()), (False, False, True))
        c("  y le pide al vigilante que pare", llavero.parada_vigilante().exists(), True)
        rechaza("sin llavero no hay qué desactivar",
                lambda: llavero_editor.plan_desactivar(config_file.load_raw()), "no lleva")
        (root / llavero.LANZADOR).write_bytes(b"@echo off\r\nrem el mio\r\n")
        c("un Llavero.bat que no es el nuestro no se quita",
          (llavero.quitar_lanzador(), (root / llavero.LANZADOR).exists()), ([], True))

    # en una raíz de este equipo: no lleva lanzadores, se abre desde su ventana
    # o desde el menú del agente
    real_app = model.APP_DIR
    try:
        with sandbox() as root:
            model.APP_DIR = root / ".prdrive"
            model.APP_DIR.mkdir()
            (model.APP_DIR / "PRDRIVE").write_text("id=e\ntipo=equipo\n", encoding="utf-8")
            config_file.save(LOCAL)
            plan = llavero_editor.plan_activar(LOCAL, leido(), propia)
            texto = " ".join(plan.consequences)
            c.contains("en una raíz del equipo se abre desde la ventana o el menú del agente",
                       texto, "en el menú del agente")
            c("  y no habla de Llavero.bat", llavero.LANZADOR in texto, False)
            plan.execute()
            c("  ni lo pone", ((root / llavero.LANZADOR).exists(),
                               "keychain" in config_file.load_raw()), (False, True))
            c("  desactivarlo tampoco habla de él", llavero.LANZADOR in " ".join(
                llavero_editor.plan_desactivar(config_file.load_raw()).consequences), False)
    finally:
        model.APP_DIR = real_app

    # lo que enseña la pantalla
    sit = llavero_editor.situacion({**LOCAL, "keychain": {"base": "p.kdbx",
                                                          "fichero_llave": True,
                                                          "nombre_llave": "p.keyx"}})
    with sandbox():
        c.contains("activo, con fichero llave sin apuntar: lo preguntará al abrir",
                   " ".join(llavero_editor.lineas(sit, None, True)), "lo preguntará")
        c.contains("sin activar y sin llavero en el remoto",
                   " ".join(llavero_editor.lineas(llavero_editor.situacion(LOCAL), None, True)),
                   "el primero que lo active pone la base")
        c.contains("sin activar, con el del remoto y su fichero llave",
                   " ".join(llavero_editor.lineas(llavero_editor.situacion(LOCAL),
                                                  {"base": "p.kdbx", "fichero_llave": True,
                                                   "nombre_llave": "p.keyx"}, True)),
                   "pide el fichero llave «p.keyx»")
finally:
    catalog.push, keepassxc.ejecutable = real_push, real_ejecutable

sys.exit(c.report())
