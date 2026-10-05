#!/usr/bin/env python3
"""Expulsar con llavero (`keepassxc.cerrar_llavero()`, `runsync.py --cerrar-llavero`).

Sin procesos de verdad: los de la unidad se dicen, cerrarlos se apunta, y la
pasada de lo pendiente devuelve el código que se le pida. Lo que se sujeta:
- KeePassXC se cierra como lo haría la persona (nunca a la fuerza) y se
  espera a que salga; si no sale, no se sigue: la unidad no está libre.
- El proxy del navegador se termina; el vigilante se para y se le espera.
- Lo pendiente sube con un tope, y solo se dice algo si no ha ido bien.
- Las claves del navegador vuelven a como estaban.
- `--cerrar-llavero` pregunta en la consola, y un fallo suyo no impide expulsar.
"""

import contextlib
import io
import sys
import types

from _harness import Checks, sandbox

import runsync
from common import components, config_file, keepassxc, llavero, model, pins, registro, store

c = Checks("expulsar con llavero")

DEF = {"remote": "nas", "catalog_path": "/prdrive-catalog/remote.toml"}
NOTAS = {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas"}


def config(con_llavero=True):
    """Un config con llavero (o sin él)."""
    data = {"defaults": DEF, "pair": [NOTAS]}
    if con_llavero:
        data["keychain"] = {"base": "personal.kdbx"}
    return model.parse_config(data)


class Equipo:
    """Los procesos del equipo y lo que se les hace."""

    def __init__(self) -> None:
        self.vivos: dict[int, str] = {}
        self.no_sale: set[int] = set()
        self.cerrados: list[int] = []
        self.terminados: list[int] = []
        self.pasadas: list = []
        self.rc = 0
        self.pendiente = False
        self.vigilante = False

    def pedir_cierre(self, pid):
        self.cerrados.append(pid)
        if pid not in self.no_sale:
            self.vivos.pop(pid, None)

    def terminar(self, pid):
        self.terminados.append(pid)
        self.vivos.pop(pid, None)

    def pasada(self, tope=None):
        self.pasadas.append(tope)
        return self.rc, ""


reales = (store.procesos, store.pid_alive, keepassxc.pedir_cierre, keepassxc.terminar,
          llavero.pasada, llavero.pendiente, llavero.vigilante_vivo, llavero.dormir,
          keepassxc.ESPERA_CIERRE, keepassxc.ESPERA_VIGILANTE,
          registro.leer, registro.escribir, registro.borrar, registro.vacia)
real_app = model.APP_DIR
try:
    with sandbox() as root:
        model.APP_DIR = root / ".prdrive"
        rclone = components.rclone_path(model.APP_DIR, pins.plataforma("windows-x64"))
        rclone.parent.mkdir(parents=True)
        rclone.write_bytes(b"rclone")
        carpeta = components.keepassxc_dir(model.APP_DIR, "windows-x64")
        eq = Equipo()
        store.procesos = lambda: dict(eq.vivos)
        store.pid_alive = lambda pid: pid in eq.vivos
        keepassxc.pedir_cierre, keepassxc.terminar = eq.pedir_cierre, eq.terminar
        llavero.pasada = eq.pasada
        llavero.pendiente = lambda pareja: eq.pendiente
        llavero.vigilante_vivo = lambda: eq.vigilante
        llavero.dormir = lambda s: None
        keepassxc.ESPERA_CIERRE = keepassxc.ESPERA_VIGILANTE = 0.05
        claves: dict = {}
        registro.leer = claves.get
        registro.escribir = lambda clave, valor: claves.__setitem__(clave, valor)
        registro.borrar = lambda clave: claves.pop(clave, None) is not None
        registro.vacia = lambda clave: None

        c("sin llavero, nada que cerrar", keepassxc.cerrar_llavero(config(False)),
          keepassxc.Cierre(True))

        eq.vivos = {10: str(carpeta / "KeePassXC.exe"), 11: str(carpeta / "keepassxc-proxy.exe"),
                    12: "C:/Program Files/Otro/otro.exe"}
        cierre = keepassxc.cerrar_llavero(config())
        c("KeePassXC se cierra como lo haría la persona, y el proxy se termina",
          (eq.cerrados, eq.terminados), ([10], [11]))
        c("  lo de otros programas no se toca", 12 in eq.vivos, True)
        c("  y sin nada pendiente, no se dice nada", cierre, keepassxc.Cierre(True))
        c("  ni se hace pasada", eq.pasadas, [])

        eq.vivos = {10: str(carpeta / "KeePassXC.exe")}
        eq.no_sale = {10}
        eq.cerrados.clear()
        cierre = keepassxc.cerrar_llavero(config())
        c("si KeePassXC no sale, la unidad no está libre, y se dice cómo cerrarlo",
          cierre, keepassxc.Cierre(False, (keepassxc.SIGUE_ABIERTO,)))
        c("  sin forzarlo: se le pidió una vez", eq.cerrados, [10])
        eq.vivos, eq.no_sale = {}, set()

        # el vigilante
        eq.vigilante = True
        llavero.vigilante_vivo = lambda: eq.vigilante
        keepassxc.cerrar_llavero(config())
        c("al vigilante se le pide que pare", llavero.parada_vigilante().exists(), True)
        eq.vigilante = False
        llavero.parada_vigilante().unlink()

        # lo pendiente
        eq.pendiente = True
        cierre = keepassxc.cerrar_llavero(config())
        c("lo pendiente sube con su tope, y si va bien no se dice nada",
          (eq.pasadas, cierre.lineas), ([keepassxc.TOPE_PASADA], ()))
        eq.rc = llavero.SIN_TIEMPO
        cierre = keepassxc.cerrar_llavero(config())
        c("sin red o sin tiempo: una línea, y se puede quitar igual",
          (cierre.listo, cierre.lineas),
          (True, (keepassxc.SUBIRA.format(rc=llavero.SIN_TIEMPO),)))
        donde = config().pareja_llavero.local_abs
        donde.mkdir(parents=True, exist_ok=True)
        (donde / "personal.kdbx").write_bytes(b"cortada")
        c.contains("con la base sin acabar, se dice", " ".join(
            keepassxc.cerrar_llavero(config()).lineas), "no está entera")
        (donde / "personal.kdbx").unlink()
        eq.rc = 0
        eq.pendiente = False

        # el navegador
        clave = keepassxc.clave_nativa("Software\\Mozilla")
        claves[clave] = str(model.DEVICE_ROOT / ".prdrive" / "x.json")
        keepassxc.cerrar_llavero(config())
        c("las claves del navegador de la unidad se quitan", clave in claves, False)

        # --cerrar-llavero, en la consola del .bat
        config_file.save({"defaults": DEF, "pair": [NOTAS],
                          "keychain": {"base": "personal.kdbx"}})
        eq.vivos = {10: str(carpeta / "KeePassXC.exe")}
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            rc = runsync.cerrar_llavero(preguntar=lambda texto: "n")
        c("--cerrar-llavero: si no se quiere cerrar KeePassXC, sale con 1",
          (rc, 10 in eq.vivos), (1, True))
        with contextlib.redirect_stdout(io.StringIO()):
            rc = runsync.cerrar_llavero(preguntar=lambda texto: "")
        c("  con Intro, lo cierra y sale con 0", (rc, 10 in eq.vivos), (0, False))

        def sin_terminal(texto):
            raise EOFError
        eq.vivos = {10: str(carpeta / "KeePassXC.exe")}
        with contextlib.redirect_stdout(io.StringIO()):
            c("  sin nadie que conteste, lo cierra", runsync.cerrar_llavero(sin_terminal), 0)

        real_cerrar = keepassxc.cerrar_llavero
        keepassxc.cerrar_llavero = lambda cfg: (_ for _ in ()).throw(RuntimeError("vaya"))
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            rc = runsync.cerrar_llavero(preguntar=lambda texto: "")
        keepassxc.cerrar_llavero = real_cerrar
        c("  un fallo suyo no impide expulsar: VeraCrypt dirá si queda algo abierto",
          (rc, "se sigue expulsando" in salida.getvalue()), (0, True))
finally:
    (store.procesos, store.pid_alive, keepassxc.pedir_cierre, keepassxc.terminar,
     llavero.pasada, llavero.pendiente, llavero.vigilante_vivo, llavero.dormir,
     keepassxc.ESPERA_CIERRE, keepassxc.ESPERA_VIGILANTE,
     registro.leer, registro.escribir, registro.borrar, registro.vacia) = reales
    model.APP_DIR = real_app

# las órdenes de Windows: cerrar es WM_CLOSE (sin /F); terminar, solo el proxy
ordenes: list = []
real_os, real_run = keepassxc.os, keepassxc.subprocess.run
keepassxc.os = types.SimpleNamespace(name="nt", environ={})
keepassxc.subprocess.run = lambda orden, **k: ordenes.append(orden)
try:
    keepassxc.pedir_cierre(10)
    keepassxc.terminar(11)
finally:
    keepassxc.os, keepassxc.subprocess.run = real_os, real_run
c("en Windows, cerrar KeePassXC es taskkill sin /F: si hay algo sin guardar, pregunta",
  ordenes, [["taskkill", "/PID", "10"], ["taskkill", "/F", "/PID", "11"]])
sys.exit(c.report())
