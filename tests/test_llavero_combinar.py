#!/usr/bin/env python3
"""«Combinar» las copias de conflicto de la base del llavero (`ui/conflict_editor.py`).

Sin consola y sin KeePassXC: `keepassxc.combinar()` (la consola que pide la
contraseña) se sustituye por un apunte. Con `keepassxc-cli` instalado se
comprueba además que la orden que se construye combina de verdad dos bases.
Lo que se sujeta:
- La orden: `merge --same-credentials`, con el fichero llave de este equipo.
- La consola dice qué pasa y, si no sale bien, espera a que se lea.
- El plan: la base se queda con lo de las dos, cada copia combinada va a
  `.prversions/` con el sello de rclone (deja de viajar y deja de ser un
  conflicto), y lo que no se combina no se toca. Elegir una versión del
  llavero avisa de que pierde lo de la otra.
- «Abrir llavero» lo ofrece antes de abrir, y cancelar abre igual.
"""

import contextlib
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

from _harness import Checks, sandbox, tmpdir

from common import components, conflicts, keepassxc, llavero, model, registro, revision
from ui import conflict_editor, llavero_editor, versions_editor
from ui.conflict_editor import ResolucionImposible

c = Checks("combinar el llavero")

DEF = {"remote": "nas", "catalog_path": "/prdrive-catalog/remote.toml"}
NOTAS = {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas"}
BASE = "personal.kdbx"
REMOTA = "personal.conflicto-remoto1.kdbx"
DE_AQUI = "personal.conflicto-dispositivo1.kdbx"


def config(**llave):
    """Un config con llavero, con esas claves de más en `[keychain]`."""
    return model.parse_config({"defaults": DEF, "pair": [NOTAS],
                               "keychain": {"base": BASE, **llave}})


def rechaza(etiqueta, hacer, fragmento):
    """Comprueba que `hacer()` lance `ResolucionImposible` con ese fragmento."""
    try:
        hacer()
        c(etiqueta, "no lanzó", "ResolucionImposible")
    except ResolucionImposible as e:
        c.contains(etiqueta, str(e), fragmento)


# --- la orden
cli = Path("E:/.prdrive/keepassxc/windows-x64/keepassxc-cli.exe")
base, copia = Path("E:/.keychain") / BASE, Path("E:/.keychain") / REMOTA
c("la orden combina la copia en la base, con la contraseña una vez",
  keepassxc.orden_combinar(cli, base, copia),
  [str(cli), "merge", "--same-credentials", str(base), str(copia)])
c("  y el fichero llave de este equipo, si lo pide",
  keepassxc.orden_combinar(cli, base, copia, Path("D:/k.keyx"))[3:5],
  ["--key-file", str(Path("D:/k.keyx"))])

real = shutil.which("keepassxc-cli")
if real:
    d = tmpdir("prdrive-merge-")
    entorno = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}

    def cli_real(*args, entrada):
        """Corre el keepassxc-cli instalado con esa entrada."""
        return subprocess.run([real, *args], input=entrada, text=True, capture_output=True,
                              env=entorno, cwd=d)

    cli_real("db-create", "-p", str(d / BASE), entrada="clave\nclave\n")
    shutil.copy(d / BASE, d / REMOTA)
    cli_real("add", "-q", "--username", "ana", "-p", str(d / REMOTA), "gitlab",
             entrada="clave\npw\npw\n")
    orden = keepassxc.orden_combinar(Path(real), d / BASE, d / REMOTA)
    hecho = cli_real(*orden[1:], entrada="clave\n")
    c("con keepassxc-cli de verdad, la orden combina", hecho.returncode, 0)
    c("  y la base se queda con lo de la copia",
      cli_real("ls", "-q", str(d / BASE), entrada="clave\n").stdout.split(), ["gitlab"])
    c("  con otra contraseña no, y lo dice con su código",
      cli_real(*orden[1:], entrada="mala\n").returncode != 0, True)
else:
    print("  (saltado) no hay keepassxc-cli para probar la orden de verdad")

# --- la consola
reales = (keepassxc.cli, keepassxc.ejecutar_cli)
try:
    falso = tmpdir("prdrive-cli-") / "keepassxc-cli.exe"
    falso.write_bytes(b"MZ")
    keepassxc.cli = lambda: falso
    corridas, esperas = [], []
    for codigo in (0, 1):
        keepassxc.ejecutar_cli = lambda orden, codigo=codigo: (corridas.append(orden), codigo)[1]
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            rc = keepassxc.combinar_aqui(base, copia, esperar=esperas.append)
        if codigo == 0:
            c("la consola dice qué entra dónde, y que la contraseña la pide KeePassXC",
              ("«personal.conflicto-remoto1.kdbx» entra en «personal.kdbx»" in salida.getvalue(),
               "la pide KeePassXC, no prdrive" in salida.getvalue()), (True, True))
            c("  si sale bien, se cierra sin esperar", (rc, esperas), (0, []))
            c("  con la orden de combinar", corridas[-1][1:3], ["merge", "--same-credentials"])
        else:
            c("si no, dice que no se ha tocado nada y espera a que se lea",
              (rc, "No se ha combinado (código 1)" in salida.getvalue(), len(esperas)),
              (1, True, 1))
    keepassxc.cli = lambda: None
    esperas.clear()
    with contextlib.redirect_stdout(io.StringIO()):
        c("sin keepassxc-cli, 2, y espera", (keepassxc.combinar_aqui(base, copia,
                                                                    esperar=esperas.append),
                                            len(esperas)), (2, 1))
finally:
    keepassxc.cli, keepassxc.ejecutar_cli = reales


# --- el plan
def poner(carpeta: Path, nombre: str, datos: bytes) -> Path:
    """Escribe un fichero en la carpeta del llavero."""
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / nombre).write_bytes(datos)
    return carpeta / nombre


reales = (keepassxc.cli, keepassxc.combinar, conflict_editor.mover)
try:
    with sandbox():
        cfg = config()
        pareja = cfg.pareja_llavero
        carpeta = pareja.local_abs
        poner(carpeta, BASE, b"base")
        poner(carpeta, REMOTA, b"la de otro dispositivo")
        conflicto = conflicts.actualizar_pareja(pareja)[0]
        falso = tmpdir("prdrive-cli-") / "keepassxc-cli.exe"
        keepassxc.cli = lambda: falso
        c("sin keepassxc-cli no se puede combinar", conflict_editor.puede_combinar(conflicto),
          False)
        rechaza("  y el plan dice que se puede desde la ventana de KeePassXC",
                lambda: conflict_editor.plan_combinar(conflicto, None),
                "Combinar desde base de datos")
        falso.write_bytes(b"MZ")
        c("con él, sí: es la base del llavero, con su nombre y una copia",
          (conflict_editor.es_del_llavero(conflicto), conflict_editor.puede_combinar(conflicto)),
          (True, True))
        c("en la lista, la pareja no sale con su nombre interno",
          conflict_editor.nombre_pareja(conflicto.pareja), "(el llavero)")

        plan = conflict_editor.plan_combinar(conflicto, None)
        texto = " ".join(plan.consequences)
        c.contains("el plan: lo de la copia entra en la base", texto,
                   "entra en «personal.kdbx», que se queda con lo de las dos")
        c.contains("  la contraseña la pide una consola, no prdrive", texto, "prdrive no la ve")
        c.contains("  y la copia va a .prversions", texto, model.VERSIONS_DIR)
        c("  sin avisos con KeePassXC cerrado", plan.warnings, [])
        c.contains("  con KeePassXC abierto, avisa de que verá el cambio",
                   " ".join(conflict_editor.plan_combinar(conflicto, None, abierto=True).warnings),
                   "recargará")
        c.contains("  con fichero llave, se dice que ya va puesto",
                   " ".join(conflict_editor.plan_combinar(conflicto, Path("k")).consequences),
                   "ya va puesto")
        rechaza("  con el llavero sin contraseña y sin su llave en el dispositivo, no",
                lambda: conflict_editor.plan_combinar(conflicto, None, sin_contrasena=True),
                "su fichero llave no está en el dispositivo")
        sin = conflict_editor.plan_combinar(conflicto, Path("k"), sin_contrasena=True)
        c.contains("  con ella, no pide contraseña", " ".join(sin.consequences),
                   "no pide contraseña")
        llamadas = []
        keepassxc.combinar = lambda b, cp, ll, **kw: (llamadas.append((b.name, cp.name, ll, kw)),
                                                      0)[1]
        sin.execute()
        c("  y la consola recibe sin_contrasena", llamadas, [(BASE, REMOTA, Path("k"),
                                                            {"sin_contrasena": True})])
        poner(carpeta, REMOTA, b"la de otro dispositivo")
        conflicto = conflicts.actualizar_pareja(pareja)[0]
        plan = conflict_editor.plan_combinar(conflicto, None)
        llamadas = []
        keepassxc.combinar = lambda b, cp, ll: (llamadas.append((b.name, cp.name, ll)), 0)[1]
        hechos = plan.execute()
        c("combinar llama a la consola con la base y la copia",
          llamadas, [(BASE, REMOTA, None)])
        c("  y lo cuenta", hechos, [f"«{REMOTA}» combinada en «{BASE}»"])
        guardadas = list((carpeta / model.VERSIONS_DIR).iterdir())
        c("la copia deja la carpeta y va a .prversions",
          ((carpeta / REMOTA).exists(), len(guardadas)), (False, 1))
        c("  con el sello de rclone, que «Versiones…» lee",
          versions_editor.leer_nombre(guardadas[0].name)[0], REMOTA)
        c("  así que deja de viajar", [r.name for r in llavero.bases(carpeta)], [BASE])
        c("  y deja de ser un conflicto", conflicts.escanear(pareja), [])
        c("la base no la toca prdrive: la escribe keepassxc-cli",
          (carpeta / BASE).read_bytes(), b"base")

        # lo que no sale bien
        poner(carpeta, REMOTA, b"otra vez")
        conflicto = conflicts.actualizar_pareja(pareja)[0]
        plan = conflict_editor.plan_combinar(conflicto, None)
        keepassxc.combinar = lambda b, cp, ll: 1
        rechaza("si no se combina, se dice cómo hacerlo en la ventana de KeePassXC",
                plan.execute, "«Base de datos → Combinar desde base de datos…»")
        rechaza("  con la ruta de la copia", plan.execute, str(carpeta / REMOTA))
        c("  y la copia sigue donde estaba", (carpeta / REMOTA).exists(), True)

        llamadas.clear()
        keepassxc.combinar = lambda b, cp, ll: (llamadas.append(cp.name), 0)[1]
        (carpeta / BASE).write_bytes(b"guardada mientras tanto")
        rechaza("si la base cambió desde el plan, no se combina", plan.execute, "ha cambiado")
        c("  ni se llama a la consola", llamadas, [])

        poner(carpeta, DE_AQUI, b"la de aqui")
        conflicto = conflicts.actualizar_pareja(pareja)[0]
        plan = conflict_editor.plan_combinar(conflicto, None)
        keepassxc.combinar = lambda b, cp, ll: 0 if cp.name == DE_AQUI else 1
        rechaza("con dos copias, se para en la que no se combina", plan.execute, REMOTA)
        c("  y la que sí, ya está apartada", ((carpeta / DE_AQUI).exists(),
                                             (carpeta / REMOTA).exists()), (False, True))

        keepassxc.combinar = lambda b, cp, ll: 0

        def no_mueve(origen, destino):
            raise OSError("en uso")
        conflict_editor.mover = no_mueve
        conflicto = conflicts.actualizar_pareja(pareja)[0]
        rechaza("combinada pero sin poder apartarla, se dice que repetir no cambia nada",
                conflict_editor.plan_combinar(conflicto, None).execute, "no cambia nada")
        conflict_editor.mover = reales[2]

        # elegir una versión del llavero avisa de que pierde lo de la otra
        version = next(v for v in conflicto.versiones if not v.es_original)
        c("quedarse con una versión del llavero avisa de lo que se pierde",
          conflict_editor.PIERDE_LLAVERO in conflict_editor.plan_conservar(conflicto, version)
          .warnings, True)
        c.contains("«Reparación» lo cuenta como el llavero, no como «keychain»",
                   next(h.titulo for h in revision.revisar(cfg) if h.clave == "conflicto"),
                   "El llavero: la base tiene copias de conflicto")

        # lo que no es la base del llavero
        notas = cfg.pairs[0]
        poner(notas.local_abs, "plan.md", b"a")
        poner(notas.local_abs, "plan.md.conflicto-remoto1", b"b")
        otro = conflicts.actualizar_pareja(notas)[0]
        c("un conflicto de otra pareja no se combina",
          (conflict_editor.es_del_llavero(otro), conflict_editor.puede_combinar(otro)),
          (False, False))
        rechaza("  y su plan no existe", lambda: conflict_editor.plan_combinar(otro, None),
                "Solo se combina la base del llavero")
        c("  ni avisa de nada del llavero",
          conflict_editor.PIERDE_LLAVERO in conflict_editor.plan_conservar(
              otro, otro.versiones[1]).warnings, False)
        (carpeta / BASE).unlink()
        conflicto = conflicts.actualizar_pareja(pareja)[0]
        rechaza("sin la base con su nombre, no hay dónde combinar",
                lambda: conflict_editor.plan_combinar(conflicto, None), "no hay dónde combinar")
finally:
    keepassxc.cli, keepassxc.combinar, conflict_editor.mover = reales


# --- con la raíz detrás de un enlace (en Windows basta un nombre corto como
# RUNNER~1, que resolver alarga): la base y la que encuentra el escaneo, que va
# resuelta, son el mismo fichero escrito de dos maneras
with sandbox() as root:
    enlace = tmpdir("prdrive-enlace-") / "raiz"
    try:
        enlace.symlink_to(root, target_is_directory=True)
    except OSError:
        print("  (saltado) sin permiso para crear enlaces")
    else:
        model.DEVICE_ROOT = enlace
        carpeta = llavero.carpeta()
        carpeta.mkdir()
        poner(carpeta, BASE, b"base")
        poner(carpeta, REMOTA, b"copia")
        c("con la raíz detrás de un enlace, la copia de la base se ve igual",
          llavero_editor.conflicto_de_la_base(config(), carpeta / BASE) is not None, True)


# --- «Abrir llavero» lo ofrece antes de abrir
class Proc:
    """Un KeePassXC que sigue abierto."""

    def poll(self):
        return None


reales = (keepassxc.paquete_del_equipo, llavero.keepassxc_abierto, keepassxc.otro_abierto,
          llavero.atiende_el_servicio, keepassxc.lanzar, keepassxc.ESPERA_ARRANQUE,
          llavero.lanzar_vigilante, keepassxc.combinar, registro.escribir, llavero.dormir)
real_app = model.APP_DIR
try:
    with sandbox() as root:
        model.APP_DIR = root / ".prdrive"
        exe = components.keepassxc_exe(model.APP_DIR, "windows-x64")
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"MZ")
        exe.with_name(keepassxc.CLI).write_bytes(b"MZ")
        estado = {"abierto": False}
        lanzadas, combinadas = [], []
        keepassxc.paquete_del_equipo = lambda: "windows-x64"
        llavero.keepassxc_abierto = lambda app_dir=None: estado["abierto"]
        keepassxc.otro_abierto = lambda: False
        llavero.atiende_el_servicio = lambda: True          # no hay pasada antes de abrir
        keepassxc.lanzar = lambda orden, entorno: (lanzadas.append(orden), Proc())[1]
        keepassxc.ESPERA_ARRANQUE = 0.01
        llavero.lanzar_vigilante = lambda: None
        keepassxc.combinar = lambda b, cp, ll: (combinadas.append((cp.name, ll)), 0)[1]
        registro.escribir = lambda clave, valor: None
        llavero.dormir = lambda s: None
        carpeta = llavero.carpeta()

        def abrir(cfg, sigue, llave=None):
            """Hace «Abrir llavero»; `sigue` es la respuesta a la confirmación."""
            pasos, confirmados = [], []

            def esperar(mensaje, funcion):
                pasos.append(mensaje)
                try:
                    return True, funcion()
                except Exception as e:                        # noqa: BLE001
                    return False, e

            def confirmar(plan, titulo, nota):
                confirmados.append((titulo, nota))
                return sigue
            dicho: list = []
            hecho = llavero_editor.abrir(cfg, dicho.append, esperar,
                                         lambda nombre: (pasos.append("llave"), llave)[1],
                                         confirmar, decir_sin_traer=False)
            return hecho, pasos, confirmados, dicho

        poner(carpeta, BASE, b"base")
        poner(carpeta, REMOTA, b"copia")
        hecho, pasos, confirmados, dicho = abrir(config(), sigue=False)
        c("con una copia de conflicto, se ofrece combinar antes de abrir",
          confirmados, [(llavero_editor.COMBINAR, llavero_editor.SIN_COMBINAR)])
        c("  cancelar abre igual, sin combinar",
          (hecho, pasos, combinadas, (carpeta / REMOTA).exists()),
          (True, [llavero_editor.ABRIENDO], [], True))

        hecho, pasos, _, dicho = abrir(config(), sigue=True)
        c("  aceptar combina en la consola y después abre",
          (hecho, pasos, combinadas), (True, [conflict_editor.ESPERANDO_CONSOLA,
                                              llavero_editor.ABRIENDO], [(REMOTA, None)]))
        c("  la copia queda apartada, y así consta para «Reparación»",
          ((carpeta / REMOTA).exists(), conflicts.contar(conflicts.cargar(config()))), (False, {}))

        poner(carpeta, REMOTA, b"copia")
        llave = root / "personal.keyx"
        llave.write_bytes(b"secreto")
        combinadas.clear()
        hecho, pasos, _, _ = abrir(config(fichero_llave=True), sigue=True, llave=llave)
        c("con fichero llave, se pregunta antes de combinar, y se le pasa",
          (pasos[0], combinadas), ("llave", [(REMOTA, llave)]))

        poner(carpeta, REMOTA, b"copia")
        keepassxc.combinar = lambda b, cp, ll: 1
        hecho, pasos, _, dicho = abrir(config(), sigue=True)
        c("si no se combina, se dice y se abre igual",
          (hecho, len(dicho), "Combinar desde base de datos" in dicho[0]), (True, 1, True))

        estado["abierto"] = True
        hecho, pasos, confirmados, _ = abrir(config(), sigue=True)
        c("con KeePassXC ya abierto, no se ofrece: solo se trae delante",
          (hecho, confirmados, pasos), (True, [], [llavero_editor.ABRIENDO]))
        estado["abierto"] = False

        (carpeta / REMOTA).unlink()
        hecho, pasos, confirmados, _ = abrir(config(), sigue=True)
        c("sin copias, no se pregunta nada", (confirmados, pasos), ([], [llavero_editor.ABRIENDO]))
finally:
    (keepassxc.paquete_del_equipo, llavero.keepassxc_abierto, keepassxc.otro_abierto,
     llavero.atiende_el_servicio, keepassxc.lanzar, keepassxc.ESPERA_ARRANQUE,
     llavero.lanzar_vigilante, keepassxc.combinar, registro.escribir, llavero.dormir) = reales
    model.APP_DIR = real_app

sys.exit(c.report())
