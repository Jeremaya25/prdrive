#!/usr/bin/env python3
"""El llavero al preparar un dispositivo (`install/llavero.py`), sin red y sin ventana.

rclone es de mentira: sirve el catálogo y apunta lo que se le sube. KeePassXC no
se descarga: `keepassxc_bin.instalar()` apunta a qué dispositivo iba. Lo que se
sujeta:
- La misma regla que la ventana (`llavero.decidir_alta()`): con un remoto sin
  llavero, la base propia es la base y el catálogo se queda con su
  `[keychain]`; con uno que ya lo tiene, la propia entra como copia.
- `aplicar()` va de fuera adentro: KeePassXC, el catálogo, y después lo del
  dispositivo (la base, el config, `Llavero.bat`, la ruta del fichero llave),
  todo en SU raíz y nada en la de este proceso.
- Si mientras tanto otro dispositivo puso un llavero, no se escribe nada.
"""

import hashlib
import struct
import subprocess
import sys
import tomllib
from pathlib import Path

from _harness import Checks, tmpdir

from common import components, config_file, kdbx, keepassxc, llavero, model, pins
from install import InstallError, deploy, keepassxc_bin
from install import llavero as llavero_install
from install import remote

c = Checks("instalador: el llavero")

CATALOGO = '[defaults]\nremote = "nas"\n\n[[pair]]\nname = "docs"\nlocal = "sync-data/docs"\n' \
           'remote_path = "/datos/docs"\n'
ENDPOINT = "nas:/prdrive-catalog/remote.toml"


def base_kdbx() -> bytes:
    """Una base KDBX 4 de mentira, entera (la forma de `test_kdbx.py`)."""
    cab = struct.pack("<IIHH", kdbx.FIRMA_1, kdbx.FIRMA_2, 1, 4)
    for campo, valor in ((4, b"\x07" * 32), (0, b"\r\n\r\n")):
        cab += struct.pack("<BI", campo, len(valor)) + valor
    datos = cab + hashlib.sha256(cab).digest() + b"\x01" * 32
    for bloque in (b"x" * 100, b""):
        datos += b"\x02" * 32 + struct.pack("<i", len(bloque)) + bloque
    return datos


class Remoto:
    """Un rclone de mentira con un catálogo: `cat`, `copyto` y lo que se ha subido."""

    def __init__(self, texto: str) -> None:
        self.texto = texto
        self.subido: list[str] = []

    def __call__(self, cmd, **kwargs):
        args = cmd[3:]                              # tras binario, --config y conf
        if args[0] == "cat":
            return subprocess.CompletedProcess(cmd, 0, self.texto, "")
        if args[0] == "copyto" and Path(args[1]).is_file():
            self.texto = Path(args[1]).read_text(encoding="utf-8")
            self.subido.append(self.texto)
        return subprocess.CompletedProcess(cmd, 0, "", "")


def dispositivo() -> Path:
    """Un dispositivo recién preparado: código con su config y el rclone de Windows x64."""
    raiz = tmpdir("prdrive-insllavero-")
    app = deploy.app_dir(raiz)
    rclone = components.rclone_path(app, pins.plataforma("windows-x64"))
    rclone.parent.mkdir(parents=True)
    rclone.write_bytes(b"rclone")
    config_file.save({"defaults": {"remote": "nas"},
                      "pair": [{"name": "docs", "local": "sync-data/docs",
                                "remote_path": "/datos/docs"}]},
                     path=deploy.config_path(raiz))
    return raiz


puestos: list = []
real_instalar = keepassxc_bin.instalar
keepassxc_bin.instalar = lambda app, clave, progreso=None: (
    puestos.append((Path(app), clave)), [f"KeePassXC {clave}"])[1]
try:
    origen = tmpdir("prdrive-insorigen-") / "personal.kdbx"
    origen.write_bytes(base_kdbx())

    # un remoto sin llavero
    raiz = dispositivo()
    cat = remote.parse_catalog(CATALOGO, ENDPOINT)
    llave = tmpdir("prdrive-insllave-") / "personal.keyx"
    plan = llavero_install.pensar(raiz, cat, origen, pide=True, nombre_llave=llave.name,
                                  llave=llave)
    c("con un remoto sin llavero, la base propia es la base y se apunta en el catálogo",
      (plan.alta.subir, plan.alta.copia, plan.alta.destino),
      (True, False, raiz / model.LLAVERO_LOCAL / "personal.kdbx"))
    c.contains("  y se dice que la original no se toca", " ".join(plan.lineas),
               "la original se queda donde está")
    rc = Remoto(CATALOGO)
    hechos = llavero_install.aplicar(plan, raiz, remote.Rclone("RCLONE", "CONF", runner=rc,
                                                               remote_name="nas"), ENDPOINT)
    c("pone KeePassXC en el dispositivo, el de su Windows",
      puestos, [(deploy.app_dir(raiz), "windows-x64")])
    tabla = {"base": "personal.kdbx", "fichero_llave": True, "nombre_llave": "personal.keyx"}
    c("sube el catálogo con [keychain]", tomllib.loads(rc.subido[-1]).get("keychain"), tabla)
    c("  y nada más cambia en él", tomllib.loads(rc.subido[-1])["pair"],
      tomllib.loads(CATALOGO)["pair"])
    c("la base, en el llavero del dispositivo",
      (raiz / model.LLAVERO_LOCAL / "personal.kdbx").read_bytes(), base_kdbx())
    c("  con su compañero fijo", (raiz / model.LLAVERO_LOCAL / llavero.LEEME).is_file(), True)
    c("[keychain] en su sync_config.toml",
      config_file.load_raw(deploy.config_path(raiz)).get("keychain"), tabla)
    c("Llavero.bat en su raíz", (raiz / llavero.LANZADOR).is_file(), True)
    c("la ruta del fichero llave, en SU state/",
      keepassxc.registro_llaves(deploy.app_dir(raiz) / "state").is_file(), True)
    c("  y nada en el state/ de este proceso", keepassxc.registro_llaves().exists(), False)
    c("el config resultante tiene la pareja del llavero",
      model.parse_config(config_file.load_raw(deploy.config_path(raiz))).pareja_llavero
      is not None, True)
    c("lo cuenta", hechos[0], "KeePassXC windows-x64")

    # un remoto que ya tiene llavero
    raiz = dispositivo()
    con = CATALOGO + '\n[keychain]\nbase = "claves.kdbx"\nfichero_llave = false\n'
    cat = remote.parse_catalog(con, ENDPOINT)
    c("se ve el llavero del remoto", llavero_install.tabla_remota(cat),
      {"base": "claves.kdbx", "fichero_llave": False})
    plan = llavero_install.pensar(raiz, cat, origen)
    rc = Remoto(con)
    llavero_install.aplicar(plan, raiz, remote.Rclone("RCLONE", "CONF", runner=rc,
                                                      remote_name="nas"), ENDPOINT)
    c("con llavero en el remoto, no se sube nada", rc.subido, [])
    c("  y la propia entra como copia de conflicto de la suya",
      sorted(p.name for p in (raiz / model.LLAVERO_LOCAL).glob("*.kdbx")),
      ["claves.conflicto-dispositivo1.kdbx"])
    plan = llavero_install.pensar(raiz, cat, None)
    c("traerla: sin copiar nada", plan.alta.destino, None)

    # mientras tanto, otro dispositivo puso un llavero
    raiz = dispositivo()
    plan = llavero_install.pensar(raiz, remote.parse_catalog(CATALOGO, ENDPOINT), origen)
    rc = Remoto(con)
    try:
        llavero_install.aplicar(plan, raiz, remote.Rclone("RCLONE", "CONF", runner=rc,
                                                          remote_name="nas"), ENDPOINT)
        c("si otro dispositivo puso un llavero mientras tanto, se dice", "no lanzó", "InstallError")
    except InstallError as e:
        c.contains("si otro dispositivo puso un llavero mientras tanto, se dice", str(e),
                   "otro dispositivo ha activado el llavero")
    c("  y no se escribe nada", (rc.subido, (raiz / model.LLAVERO_LOCAL).exists(),
                                 "keychain" in config_file.load_raw(deploy.config_path(raiz))),
      ([], False, False))

    # lo que no es una base
    rota = tmpdir("prdrive-insrota-") / "rota.kdbx"
    rota.write_bytes(base_kdbx()[:-10])
    try:
        llavero_install.pensar(raiz, remote.parse_catalog(CATALOGO, ENDPOINT), rota)
        c("una base cortada no entra", "no lanzó", "InstallError")
    except InstallError as e:
        c.contains("una base cortada no entra", str(e), "no es una base de KeePassXC entera")
finally:
    keepassxc_bin.instalar = real_instalar

sys.exit(c.report())
