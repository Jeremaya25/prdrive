#!/usr/bin/env python3
"""Expulsar con llavero (`keepassxc.cerrar_llavero()`, `runsync.py --cerrar-llavero`).

Sin procesos de verdad: los de la unidad se dicen, cerrarlos se apunta, y la
pasada de lo pendiente devuelve el código que se le pida. Lo que se sujeta:
- KeePassXC se cierra como lo haría la persona (nunca a la fuerza) y se
  espera a que salga; si no sale, no se sigue: la unidad no está libre.
- El proxy del navegador se termina; el vigilante se para y se le espera, y si
  no se va se le termina con lo que cuelga de él (#119) siendo de verdad él:
  un pid que ya es de otro programa no se toca.
- Lo pendiente sube con un tope, y solo se dice algo si no ha ido bien.
- Las claves del navegador vuelven a como estaban.
- `--cerrar-llavero` pregunta en la consola, y un fallo suyo no impide expulsar.
"""

import contextlib
import io
import os
import sys
import time
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
        self.matados: list[int] = []
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

    def matar_arbol(self, pid):
        self.matados.append(pid)
        self.vivos.pop(pid, None)

    def pasada(self, tope=None):
        self.pasadas.append(tope)
        return self.rc, ""


reales = (store.procesos, store.pid_alive, keepassxc.pedir_cierre, keepassxc.terminar,
          llavero.pasada, llavero.pendiente, llavero.vigilante_vivo, llavero.dormir,
          llavero.matar_arbol, store.orden_de,
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
        llavero.matar_arbol = eq.matar_arbol
        ordenes: dict[int, list[str]] = {}
        store.orden_de = lambda pid: ordenes.get(pid, [])
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
        VIGILANTE = 777
        EN_LA_UNIDAD = str(model.DEVICE_ROOT / ".prdrive" / "runtime" / "pythonw.exe")
        DEL_EQUIPO = "C:/Python313/python.exe"
        SUYA = ["python3", "runsync.py", "--vigilar-llavero"]
        registro_v = llavero.registro_vigilante()
        diario = model.STATE_DIR / "daemon.log"

        def vigilante_con(exe, orden):
            """Deja un vigilante vivo (pid, ejecutable y línea de órdenes) con su registro."""
            store.write_json(registro_v, {"pid": VIGILANTE, "host": llavero.equipo(),
                                          "started": store.stamp()})
            eq.vivos[VIGILANTE] = exe
            ordenes[VIGILANTE] = orden
            eq.matados.clear()

        def lo_dicho():
            """Lo que el diario del servicio cuenta del vigilante."""
            return diario.read_text(encoding="utf-8") if diario.exists() else ""

        # Lo que deja una pasada cortada: su `.lck`, que rclone respeta (--max-lock 2m) aunque
        # el dueño haya muerto (rclone v1.75.2: «prior lock file found»). Dice de quién es.
        trabajo = config().pareja_llavero.workdir
        trabajo.mkdir(parents=True, exist_ok=True)
        MUERTO, VIVO = 4242, 9999
        eq.vivos[VIVO] = "rclone"
        store.write_json(trabajo / "a..b.lck", {"Session": "x", "PID": str(MUERTO)})
        store.write_json(trabajo / "otra..par.lck", {"Session": "y", "PID": str(VIVO)})
        (trabajo / "rota..par.lck").write_text("{no es json", encoding="utf-8")

        def candados():
            return sorted(p.name for p in trabajo.glob("*.lck"))

        TRES = ["a..b.lck", "otra..par.lck", "rota..par.lck"]
        llavero.vigilante_vivo = lambda: VIGILANTE in eq.vivos
        vigilante_con(DEL_EQUIPO, SUYA)
        llavero.dormir = lambda s: eq.vivos.pop(VIGILANTE, None)     # se va nada más pedírselo
        keepassxc.cerrar_llavero(config())
        c("al vigilante se le pide que pare", llavero.parada_vigilante().exists(), True)
        c("  y si se va, no se le toca ni se dice nada", (eq.matados, lo_dicho()), ([], ""))
        c("  ni se toca ningún bloqueo", candados(), TRES)
        llavero.parada_vigilante().unlink()
        llavero.dormir = lambda s: None

        vistos: list = []

        def pasada_mirando(tope=None):
            vistos.append(candados())
            return eq.pasada(tope)

        llavero.pasada, eq.pendiente = pasada_mirando, True
        vigilante_con(DEL_EQUIPO, SUYA)
        cierre = keepassxc.cerrar_llavero(config())
        llavero.pasada, eq.pendiente = eq.pasada, False
        eq.pasadas.clear()
        c("si no se va tras pedírselo y esperar, se termina con lo que cuelga de él (#119)",
          eq.matados, [VIGILANTE])
        c("  y la pasada de lo pendiente no encuentra el bloqueo de su rclone muerto, que la "
          "habría parado dos minutos (rclone no mira si el dueño vive)",
          vistos, [["otra..par.lck", "rota..par.lck"]])
        c.contains("  se dice en el diario", lo_dicho(), "a..b.lck")
        c("  y el de una pasada que sigue viva, y el que no se entiende, se quedan",
          candados(), ["otra..par.lck", "rota..par.lck"])
        c("  se dice en el diario, con su pid", ("vigilante" in lo_dicho(), "777" in lo_dicho()),
          (True, True))
        c("  su registro y la petición de parada se van con él",
          (registro_v.exists(), llavero.parada_vigilante().exists()), (False, False))
        c("  y no impide quitar la unidad ni asusta con una línea", cierre, keepassxc.Cierre(True))
        diario.unlink(missing_ok=True)

        # Windows: no se ve su línea de órdenes, pero su ejecutable corre desde la unidad
        vigilante_con(EN_LA_UNIDAD, [])
        keepassxc.cerrar_llavero(config())
        c("  en Windows, sin línea de órdenes, vale que corra desde la unidad", eq.matados,
          [VIGILANTE])
        diario.unlink(missing_ok=True)

        # el pid ya es de otro programa (un registro que quedó de un vigilante muerto)
        for etiqueta, exe, orden in (
                ("con línea de órdenes que no es la suya", DEL_EQUIPO, ["python3", "otra.py"]),
                ("sin línea de órdenes y desde fuera de la unidad", "C:/Otro/otro.exe", [])):
            vigilante_con(exe, orden)
            cierre = keepassxc.cerrar_llavero(config())
            c(f"un pid que ya es de otro programa, {etiqueta}, no se termina",
              (eq.matados, VIGILANTE in eq.vivos, cierre.listo), ([], True, True))
            c.contains("  y el diario dice que no se ha tocado", lo_dicho(), "no se ha terminado")
            diario.unlink(missing_ok=True)
        eq.vivos.pop(VIGILANTE, None)
        registro_v.unlink(missing_ok=True)
        llavero.parada_vigilante().unlink(missing_ok=True)

        # En Windows basta con que el ejecutable corra desde la unidad, y con un pid
        # reutilizado eso puede ser quien expulsa, su padre o un programa que no es el vigilante
        carpeta_app = model.DEVICE_ROOT / ".prdrive"
        for etiqueta, pid, exe in (
                ("quien expulsa", os.getpid(), EN_LA_UNIDAD),
                ("su padre", os.getppid(), EN_LA_UNIDAD),
                ("un rclone de la unidad", 5552, str(carpeta_app / "bin" / "rclone.exe"))):
            store.write_json(registro_v, {"pid": pid, "host": llavero.equipo(),
                                          "started": store.stamp()})
            eq.vivos[pid], ordenes[pid] = exe, []
            eq.matados.clear()
            llavero.vigilante_vivo = lambda p=pid: p in eq.vivos
            keepassxc.cerrar_llavero(config())
            c(f"el pid de {etiqueta} no es el del vigilante, aunque su ejecutable corra desde "
              "la unidad: no se termina", (eq.matados, pid in eq.vivos), ([], True))
            eq.vivos.pop(pid, None)
            diario.unlink(missing_ok=True)
        registro_v.unlink(missing_ok=True)
        llavero.parada_vigilante().unlink(missing_ok=True)
        llavero.vigilante_vivo = lambda: VIGILANTE in eq.vivos

        # ni terminándolo se va (un permiso, un antivirus): se dice, y la unidad se deja quitar
        vigilante_con(DEL_EQUIPO, SUYA)
        llavero.matar_arbol = lambda pid: eq.matados.append(pid)
        empieza = time.monotonic()
        cierre = keepassxc.cerrar_llavero(config())
        tardado = time.monotonic() - empieza
        llavero.matar_arbol = eq.matar_arbol
        c("si ni terminándolo se va, se intenta una vez y se dice que sigue vivo",
          (eq.matados, "sigue vivo" in lo_dicho(), cierre.listo), ([VIGILANTE], True, True))
        c("  esperando por pasos de dormir() y no por reloj de pared: con dormir() de mentira "
          "no se espera de verdad", tardado < 1.0, True)
        c("  y su registro se queda: sigue siendo suyo", registro_v.exists(), True)
        diario.unlink(missing_ok=True)
        eq.vivos.pop(VIGILANTE, None)
        registro_v.unlink(missing_ok=True)
        llavero.parada_vigilante().unlink(missing_ok=True)
        llavero.vigilante_vivo = lambda: eq.vigilante

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

        def sin_stdin(texto):
            raise RuntimeError("input(): lost sys.stdin")
        eq.vivos = {10: str(carpeta / "KeePassXC.exe")}
        with contextlib.redirect_stdout(io.StringIO()):
            rc = runsync.cerrar_llavero(sin_stdin)
        c("  con pythonw (el agente, antes de «Bloquear»), tampoco: lo cierra",
          (rc, 10 in eq.vivos), (0, False))

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
     llavero.matar_arbol, store.orden_de,
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
