#!/usr/bin/env python3
"""El llavero sin contraseña, solo con su fichero llave (`[keychain] llave_interna`).

Sin KeePassXC ni red: la CLI (`keepassxc.convertir`, `llave_vale`), el catálogo
(`catalog.push`) y «¿está cifrado?» (`cifrada.estado`) se sustituyen. Lo que se
sujeta:
- `llave_interna` es un booleano y exige `fichero_llave`; sin ella la pareja
  es la de siempre.
- Sin cifrar no se activa, no se abre ni se sincroniza (`sync.LLAVERO_SIN_CIFRAR`,
  sin rclone), y no hay base ajena que valga con la bandera en el remoto.
- Traer el del remoto con la bandera copia el fichero llave a `.keychain/` y no
  apunta su ruta; nada sube.
- Convertir una base: se copia, la llave se genera y se guarda aparte (fuera del
  dispositivo), la CLI la deja sin contraseña y solo entonces se escribe el
  catálogo; si algo falla antes, no queda nada.
- La llave no viaja: ningún filtro del llavero la deja pasar.
- Abrir pasa `--keyfile` solo en este modo; combinar, `--no-password`.
- La sonda de la llave (`sonda_cli`) corre de verdad: en Windows, sin ventana.
"""

import contextlib
import hashlib
import io
import os
import struct
import subprocess
import sys
import types
from pathlib import Path

from _harness import Checks, sandbox, tmpdir

from common import (catalog, cifrada, components, config_file, kdbx, keepassxc, llavero,
                    model, results)
from common.model import ConfigError
import runsync
import sync
from ui import llavero_editor

c = Checks("llavero sin contraseña (llave_interna)")

DEF = {"remote": "nas", "catalog_path": "/prdrive-catalog/remote.toml"}
NOTAS = {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas"}
LOCAL = {"defaults": DEF, "pair": [NOTAS]}
CATALOGO = {"defaults": {"remote": "nas"}, "pair": [NOTAS]}
CIFRADA = cifrada.Cifrado(True, cifrada.VERACRYPT)
SIN_CIFRAR = cifrada.Cifrado(False, "", "Esta unidad no está dentro de un contenedor VeraCrypt.")
INTERNA = {"base": "personal.kdbx", "fichero_llave": True, "llave_interna": True}


def base_kdbx() -> bytes:
    """Una base KDBX 4 de mentira, entera (la forma de `test_kdbx.py`)."""
    cab = struct.pack("<IIHH", kdbx.FIRMA_1, kdbx.FIRMA_2, 1, 4)
    for campo, valor in ((4, b"\x07" * 32), (0, b"\r\n\r\n")):
        cab += struct.pack("<BI", campo, len(valor)) + valor
    datos = cab + hashlib.sha256(cab).digest() + b"\x01" * 32
    for bloque in (b"x" * 100, b""):
        datos += b"\x02" * 32 + struct.pack("<i", len(bloque)) + bloque
    return datos


def leido(raw=CATALOGO) -> catalog.Catalog:
    """El catálogo como si se acabara de leer del remoto."""
    return catalog.Catalog(raw=dict(raw), text=config_file.dumps(raw), source="remote",
                           stamp="2026-10-06 10:00:00",
                           endpoint="nas:/prdrive-catalog/remote.toml")


def rechaza(etiqueta, hacer, fragmento, error=ConfigError):
    """Comprueba que `hacer()` lance ese error con ese fragmento."""
    try:
        hacer()
        c(etiqueta, "no lanzó", error.__name__)
    except error as e:
        c.contains(etiqueta, str(e), fragmento)


def config(llave=INTERNA):
    """Devuelve un config con ese `[keychain]`."""
    return model.parse_config({**LOCAL, "keychain": dict(llave)})


# --- el esquema
c("sin la clave, la pareja es la de siempre",
  config({"base": "p.kdbx"}).pareja_llavero.llave_interna, False)
c("con ella, la pareja lo sabe", config().pareja_llavero.llave_interna, True)
rechaza("sin fichero_llave, no", lambda: config({"base": "p.kdbx", "llave_interna": True}),
        "necesita fichero_llave")
rechaza("no booleana, no", lambda: config({"base": "p.kdbx", "fichero_llave": True,
                                           "llave_interna": "sí"}), "true o false")
c("false está bien", config({"base": "p.kdbx", "llave_interna": False}).pareja_llavero
  .llave_interna, False)

import tomllib
texto = config_file.dumps_checked({**CATALOGO, "keychain": dict(INTERNA)})
c("la clave viaja por el serializador del catálogo y vuelve igual",
  tomllib.loads(texto)["keychain"], INTERNA)

# --- la llave no viaja: ningún filtro del llavero la deja pasar
def pasa(nombre: str) -> bool:
    """Evalúa `LLAVERO_REGLAS` como rclone: gana la primera regla que casa."""
    from fnmatch import fnmatchcase
    for regla in model.LLAVERO_REGLAS:
        signo, patron = regla.split(" ", 1)
        if patron == "**" or fnmatchcase(nombre, patron):
            return signo == "+"
    return False


c("la base viaja, la llave no", (pasa("personal.kdbx"), pasa(model.LLAVERO_LLAVE)), (True, False))

# --- la regla única del alta
d = Path("/no/esta/.keychain")
tabla_remota = dict(INTERNA)
rechaza("con la bandera en el remoto, sin cifrar no se trae", lambda: llavero.decidir_alta(
    d, tabla_remota, None, cifrado=SIN_CIFRAR), "solo puede estar en un dispositivo cifrado",
    ValueError)
rechaza("  ni se usa una base propia, aunque esté cifrado", lambda: llavero.decidir_alta(
    d, tabla_remota, Path("x.kdbx"), cifrado=CIFRADA), "otra forma no se podría combinar",
    ValueError)
alta = llavero.decidir_alta(d, tabla_remota, None, cifrado=CIFRADA)
c("  cifrado, se trae: el [keychain] es el del remoto", (alta.tabla, alta.destino, alta.subir),
  (INTERNA, None, False))
rechaza("convertir con llavero ya en el remoto, no", lambda: llavero.decidir_alta(
    d, {"base": "otra.kdbx"}, Path("x.kdbx"), interna=True, cifrado=CIFRADA),
    "ya tiene llavero", ValueError)
rechaza("convertir sin cifrar, no", lambda: llavero.decidir_alta(
    d, None, Path("x.kdbx"), interna=True, cifrado=SIN_CIFRAR), "cifrado", ValueError)

# --- el fichero llave y su copia
with sandbox() as root:
    destino = root / ".keychain" / model.LLAVERO_LLAVE
    llavero.generar_llave(destino)
    texto = destino.read_text(encoding="ascii")
    c("la llave generada: 64 caracteres hexadecimales, sin salto de línea",
      (len(texto), int(texto, 16) >= 0, texto == texto.strip()), (64, True, True))
    rechaza("  no se pisa una que existe", lambda: llavero.generar_llave(destino), "", FileExistsError)
    fuera = tmpdir("prdrive-fuera-")
    llavero.guardar_copia_llave(destino, fuera / "copia.keyx")
    c("la copia, fuera del dispositivo, igual", (fuera / "copia.keyx").read_text(), texto)
    rechaza("  dentro del dispositivo, no", lambda: llavero.guardar_copia_llave(
        destino, root / "copia.keyx"), "fuera del dispositivo", OSError)

# --- traer el del remoto con la bandera
subidas: list = []
real_push, real_ejecutable = catalog.push, keepassxc.ejecutable
catalog.push = lambda new_raw, base_text, raw_local=None: (
    subidas.append(dict(new_raw)), ["catálogo subido"])[1]
keepassxc.ejecutable = lambda: Path("/no/esta/KeePassXC.exe")
try:
    con_bandera = {**CATALOGO, "keychain": dict(INTERNA)}
    with sandbox() as root:
        config_file.save(LOCAL)
        fuera = tmpdir("prdrive-llave-")
        suya = fuera / "mia.keyx"
        suya.write_text("a" * 64, encoding="ascii")
        rechaza("sin dar el fichero llave, no", lambda: llavero_editor.plan_activar(
            LOCAL, leido(con_bandera), None, cifrado=CIFRADA), "da el fichero llave")
        rechaza("sin cifrar, no", lambda: llavero_editor.plan_activar(
            LOCAL, leido(con_bandera), None, llave=suya, cifrado=SIN_CIFRAR), "cifrado")
        rechaza("con una base propia, no", lambda: llavero_editor.plan_activar(
            LOCAL, leido(con_bandera), Path("x.kdbx"), llave=suya, cifrado=CIFRADA),
            "no se podría combinar")
        plan = llavero_editor.plan_activar(LOCAL, leido(con_bandera), None, llave=suya,
                                           cifrado=CIFRADA)
        c.contains("el plan dice que la llave se copia y no sube", " ".join(plan.consequences),
                   "no sube nunca al remoto")
        plan.execute()
        c("traerlo: la llave, copiada al dispositivo", (llavero.carpeta() / model.LLAVERO_LLAVE)
          .read_text(), "a" * 64)
        c("  la original, donde estaba", suya.read_text(), "a" * 64)
        c("  su ruta no se apunta", keepassxc.llave_apuntada(), None)
        c("  el config lleva la bandera", config_file.load_raw()["keychain"], INTERNA)
        c("  nada sube", subidas, [])
        c("  la pareja del llavero la sabe",
          model.load_config().pareja_llavero.llave_interna, True)
        rechaza("pedir o quitar el fichero llave desde aquí, no", lambda: (
            llavero_editor.plan_pide_llave(config_file.load_raw(), leido(con_bandera), False)),
            "va sin contraseña")
        sit = llavero_editor.situacion(config_file.load_raw())
        c.contains("la tarjeta lo dice", " ".join(llavero_editor.lineas(sit, None, True)),
                   "sin contraseña")
        plan = llavero_editor.plan_desactivar(config_file.load_raw())
        c.contains("desactivar avisa de que la llave se queda", " ".join(plan.warnings),
                   "se queda en el dispositivo")

    # el remoto sin llavero: la tarjeta de un dispositivo sin activar
    sin_activar = llavero_editor.lineas(llavero_editor.Situacion(False), dict(INTERNA), True)
    c.contains("el remoto con la bandera: se avisa a quien no lo tiene aún", " ".join(sin_activar),
               "sin contraseña")

    # --- convertir una base propia
    convertidas: list = []
    real_conv, real_vale, real_sin = keepassxc.convertir, keepassxc.llave_vale, keepassxc.sin_conversion
    resultado = {"codigo": 0, "vale": True}

    def convertir(base, llave, llave_actual=None):
        """La CLI de mentira: apunta lo que le pidieron y dice el código que toque."""
        convertidas.append((base, llave, llave_actual))
        return resultado["codigo"]

    keepassxc.convertir = convertir
    keepassxc.llave_vale = lambda base, llave: resultado["vale"]
    keepassxc.sin_conversion = lambda: None
    try:
        propia = tmpdir("prdrive-propia-") / "Claves.KDBX"
        propia.write_bytes(base_kdbx())
        with sandbox() as root:
            config_file.save(LOCAL)
            aparte = tmpdir("prdrive-aparte-") / "llave.keyx"
            rechaza("con llavero en el remoto, no", lambda: llavero_editor.plan_llave_interna(
                LOCAL, leido({**CATALOGO, "keychain": {"base": "x.kdbx"}}), propia, aparte,
                cifrado=CIFRADA), "ya tiene llavero")
            rechaza("sin cifrar, no", lambda: llavero_editor.plan_llave_interna(
                LOCAL, leido(), propia, aparte, cifrado=SIN_CIFRAR), "cifrado")
            rechaza("con la copia dentro del dispositivo, no", lambda: llavero_editor.plan_llave_interna(
                LOCAL, leido(), propia, root / "copia.keyx", cifrado=CIFRADA),
                "fuera del dispositivo")
            aparte.write_text("ya hay algo")
            rechaza("con la copia ya existente, no", lambda: llavero_editor.plan_llave_interna(
                LOCAL, leido(), propia, aparte, cifrado=CIFRADA), "ya existe")
            aparte.unlink()
            keepassxc.sin_conversion = lambda: "no hay db-edit"
            rechaza("sin keepassxc-cli con db-edit, no", lambda: llavero_editor.plan_llave_interna(
                LOCAL, leido(), propia, aparte, cifrado=CIFRADA), "no hay db-edit")
            keepassxc.sin_conversion = lambda: None
            plan = llavero_editor.plan_llave_interna(LOCAL, leido(), propia, aparte,
                                                     llave_actual=Path("vieja.keyx"),
                                                     cifrado=CIFRADA)
            c.contains("el plan avisa de que la protección se sustituye", " ".join(plan.warnings),
                       "se sustituye")
            c.contains("  y de que la llave se guarda aparte", " ".join(plan.consequences),
                       "fuera del dispositivo")
            c("  nada se ha tocado antes de confirmar",
              (subidas, llavero.carpeta().exists(), aparte.exists()), ([], False, False))

            # sale mal: la CLI falla
            resultado["codigo"] = 1
            rechaza("si la CLI falla, se dice", plan.execute, "no ha podido dejar la base sin contraseña")
            c("  y no queda nada: ni base, ni llave, ni copia, ni catálogo, ni config",
              (sorted(p.name for p in llavero.carpeta().iterdir() if p.name != llavero.LEEME),
               aparte.exists(), subidas, "keychain" in config_file.load_raw()),
              ([], False, [], False))
            # sale mal: la llave no abre la base
            resultado.update(codigo=0, vale=False)
            rechaza("si la llave no abre la base, se dice", plan.execute, "no se abre solo con")
            c("  y tampoco queda nada", (aparte.exists(), subidas), (False, []))
            # sale mal: no se puede escribir el catálogo
            resultado.update(vale=True)
            catalog.push = lambda *a, **k: (_ for _ in ()).throw(ConfigError("sin red"))
            rechaza("si el catálogo falla, se dice", plan.execute, "sin red")
            c("  y se deshace lo local", (aparte.exists(), (llavero.carpeta() / "personal.kdbx").exists(),
                                         (llavero.carpeta() / model.LLAVERO_LLAVE).exists()),
              (False, False, False))
            catalog.push = lambda new_raw, base_text, raw_local=None: (
                subidas.append(dict(new_raw)), ["catálogo subido"])[1]
            convertidas.clear()
            hechos = plan.execute()
            base, llave, actual = convertidas[0]
            c("bien: la CLI recibe la copia, la llave nueva y la actual",
              (base, llave, actual), (llavero.carpeta() / "Claves.kdbx",
                                      llavero.carpeta() / model.LLAVERO_LLAVE, Path("vieja.keyx")))
            c("  la base del dispositivo, copiada con .kdbx en minúsculas; la original, intacta",
              (base.read_bytes(), propia.read_bytes()), (base_kdbx(), base_kdbx()))
            c("  la copia de la llave, igual que la del dispositivo", aparte.read_text(),
              llave.read_text())
            tabla = {"base": "Claves.kdbx", "fichero_llave": True, "llave_interna": True}
            c("  al catálogo, [keychain] con la bandera", subidas[-1].get("keychain"), tabla)
            c("  al config, lo mismo", config_file.load_raw().get("keychain"), tabla)
            c("  y lo cuenta", hechos[0], "catálogo subido")
    finally:
        keepassxc.convertir, keepassxc.llave_vale, keepassxc.sin_conversion = (
            real_conv, real_vale, real_sin)
finally:
    catalog.push, keepassxc.ejecutable = real_push, real_ejecutable

# --- abrir y combinar
exe = Path("/k/KeePassXC.exe")
base = Path("/d/.keychain/personal.kdbx")
llave = Path("/d/.keychain/llave.keyx")
c("abrir: con la llave interna, --keyfile", keepassxc.orden(exe, base, llave_interna=llave)[-3:],
  ["--keyfile", str(llave), str(base)])
c("  sin ella, no", "--keyfile" in keepassxc.orden(exe, base), False)
externo = keepassxc.Externo(("/usr/bin/flatpak", "run", keepassxc.FLATPAK_ID), flatpak=True)
c("  con el KeePassXC del equipo, igual",
  keepassxc.orden_externo(externo, base, Path("/d"), llave_interna=llave)[-3:],
  ["--keyfile", str(llave), str(base)])
c("combinar sin contraseña: --no-password y la llave",
  keepassxc.orden_combinar(Path("cli"), base, Path("c.kdbx"), llave, True),
  ["cli", "merge", "--same-credentials", "--no-password", "--key-file", str(llave), str(base),
   "c.kdbx"])
c("  con contraseña, como antes",
  keepassxc.orden_combinar(Path("cli"), base, Path("c.kdbx"), llave),
  ["cli", "merge", "--same-credentials", "--key-file", str(llave), str(base), "c.kdbx"])
c("convertir: db-edit con la llave nueva y sin contraseña",
  keepassxc.orden_convertir(Path("cli"), base, llave),
  ["cli", "db-edit", "--set-key-file", str(llave), "--unset-password", str(base)])
c("  con el fichero llave que ya tenía la base",
  keepassxc.orden_convertir(Path("cli"), base, llave, Path("vieja.keyx")),
  ["cli", "db-edit", "--key-file", "vieja.keyx", "--set-key-file", str(llave),
   "--unset-password", str(base)])

vistas: list = []
real_combinar_aqui = keepassxc.combinar_aqui
keepassxc.combinar_aqui = lambda b, cop, k=None, **kw: vistas.append((b, cop, k, kw)) or 0
try:
    runsync.combinar_llavero(["b.kdbx", "c.kdbx", "--keyfile", "k.keyx", "--sin-contrasena"])
    runsync.combinar_llavero(["b.kdbx", "c.kdbx"])
finally:
    keepassxc.combinar_aqui = real_combinar_aqui
c("runsync --combinar-llavero --sin-contrasena llega a la consola",
  (vistas[0][2:], vistas[1][3]), ((Path("k.keyx"), {"sin_contrasena": True}), {}))
real_convertir_aqui = keepassxc.convertir_aqui
keepassxc.convertir_aqui = lambda b, k, actual=None: vistas.append((b, k, actual)) or 0
try:
    c("runsync --convertir-llavero BASE LLAVE --actual K",
      (runsync.convertir_llavero(["b.kdbx", "n.keyx", "--actual", "v.keyx"]), vistas[-1]),
      (0, (Path("b.kdbx"), Path("n.keyx"), Path("v.keyx"))))
finally:
    keepassxc.convertir_aqui = real_convertir_aqui

# la sonda de la llave
ordenes: list = []
real_cli, real_lanzable, real_sonda = keepassxc.cli, keepassxc.cli_lanzable, keepassxc.sonda_cli
try:
    with sandbox() as root:
        programa = root / "keepassxc-cli"
        programa.write_text("")
        keepassxc.cli = lambda: programa
        keepassxc.cli_lanzable = lambda p: p
        codigos = iter([0, 1])
        keepassxc.sonda_cli = lambda o, e: ordenes.append(o) or next(codigos)
        c("la sonda: una llave que abre", keepassxc.llave_vale(base, llave), True)
        c("  una que no", keepassxc.llave_vale(base, llave), False)
        c("  sin contraseña que pedir, con la llave",
          ordenes[0], [str(programa), "ls", "-q", "--no-password", "--key-file", str(llave),
                       str(base)])
        keepassxc.sonda_cli = lambda o, e: (_ for _ in ()).throw(OSError("no arranca"))
        c("  si no arranca, no se sabe (no es «no vale»)", keepassxc.llave_vale(base, llave), None)
        keepassxc.cli = lambda: None
        c("  sin keepassxc-cli, tampoco", keepassxc.llave_vale(base, llave), None)
        c("  y convertir dice que falta", keepassxc.sin_conversion(), keepassxc.SIN_CLI_CONVERTIR)
finally:
    keepassxc.cli, keepassxc.cli_lanzable, keepassxc.sonda_cli = real_cli, real_lanzable, real_sonda


def o_error(funcion):
    """Devuelve lo que da `funcion()`, o su excepción escrita, para que el fallo se cuente."""
    try:
        return funcion()
    except Exception as e:                           # noqa: BLE001 — se cuenta como fallo
        return repr(e)


# la sonda de verdad, sin sustituirla: en Windows, sin ventana de consola
llamadas: list = []
real_os, real_run = keepassxc.os, keepassxc.subprocess.run


def correr(orden_, **kw):
    """`subprocess.run` de mentira: apunta cómo se lanzaría y sale con 0."""
    llamadas.append(kw)
    return subprocess.CompletedProcess(orden_, 0)


try:
    with sandbox() as root:
        programa = root / "keepassxc-cli.exe"
        programa.write_text("")
        keepassxc.cli = lambda: programa
        keepassxc.cli_lanzable = lambda p: p
        keepassxc.os = types.SimpleNamespace(name="nt", environ={})
        keepassxc.subprocess.run = correr
        c("en Windows, la sonda de verdad dice si la llave vale",
          o_error(lambda: keepassxc.llave_vale(base, llave)), True)
        c("  sin ventana de consola ni teclado",
          [(kw.get("creationflags"), kw.get("stdin")) for kw in llamadas],
          [(model.CREATE_NO_WINDOW, subprocess.DEVNULL)])
finally:
    keepassxc.os, keepassxc.subprocess.run = real_os, real_run
    keepassxc.cli, keepassxc.cli_lanzable = real_cli, real_lanzable
c("la sonda de verdad en este sistema: devuelve el código del programa",
  o_error(lambda: keepassxc.sonda_cli(
      [sys.executable, "-c", "import os, sys; sys.exit(int(os.environ['PRDRIVE_SONDA']))"],
      dict(os.environ, PRDRIVE_SONDA="3"))), 3)

# --- la pasada sin cifrar no corre
real_estado, real_execute = cifrada.estado, sync.execute
ordenes.clear()
try:
    with sandbox() as root:
        model.APP_DIR = root / ".prdrive"
        pareja = config().pareja_llavero
        sync.execute = lambda ctx, cmd, logfile=None: ordenes.append(cmd) or 0
        cifrada.estado = lambda app_dir=None: SIN_CIFRAR
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            rc = sync.run_pair(sync.RunContext(binary="RCLONE", env={}, resync_approved=True),
                               pareja)
        c("sin cifrar, la pasada no corre ni toca rclone", (rc, ordenes),
          (sync.LLAVERO_SIN_CIFRAR, []))
        c.contains("  y dice por qué", salida.getvalue(), "va sin contraseña")
        c.contains("  con el motivo", salida.getvalue(), "contenedor VeraCrypt")
        c("  y consta como fallo, para la ventana",
          [f.pareja for f in results.fallos_de([model.LLAVERO])], [model.LLAVERO])
        # la línea de la ventana, ámbar y sin botón
        real_ej = keepassxc.ejecutable
        exe = components.keepassxc_exe(model.APP_DIR, "windows-x64")
        keepassxc.ejecutable = lambda: exe
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"")
        linea = llavero_editor.linea(config())
        c("la línea de la ventana: ámbar, sin botón, con el motivo",
          (linea.aviso, linea.abrir), (True, False))
        c.contains("  y lo que pasa", linea.texto, "solo se sincroniza en un dispositivo cifrado")
        keepassxc.ejecutable = real_ej
        # abrir: el motivo antes que nada
        ap = keepassxc.mirar_apertura(config())
        c.contains("abrir sin cifrar: se dice y no se abre", ap.motivo or "", "solo se abre en un "
                   "dispositivo cifrado")
        cifrada.estado = lambda app_dir=None: CIFRADA
        ap = keepassxc.mirar_apertura(config())
        c.contains("  cifrado pero sin la llave en el dispositivo", ap.motivo or "",
                   "no está")
finally:
    cifrada.estado, sync.execute = real_estado, real_execute

sys.exit(c.report())
