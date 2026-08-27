#!/usr/bin/env python3
"""
El perfil de conexión: de dónde sale y cuánto rato está la clave en el disco.

Esto es lo más delicado del instalador. Se comprueba:

  * La cascada: primero el perfil incrustado al compilar, luego el del checkout
    desde el que se ejecuta el .py, y si no hay ninguno, uno **vacío**. Que no
    haya perfil NO es un error: es el arranque normal de quien acaba de clonar el
    repositorio, y antes ahí el asistente se moría.
  * Que una compilación mal hecha —con el marcador `__INJECT` todavía puesto— se
    niega en vez de intentar conectarse con una clave de mentira.
  * Que el rclone.conf sale bien tanto en su forma efímera (rutas absolutas al
    temporal) como en la del dispositivo (relativas), y que al cerrar el temporal
    no queda nada.
  * Que el barrido de arranque se lleva las claves que dejaron instaladores
    muertos, pero NO las de uno que siga vivo (dos instalaciones a la vez).
  * Que el backend no se interpreta en ningún sitio: lo que se teclea es lo que
    va al conf.

No se usa ninguna clave de verdad: todas las de aquí son inventadas.
"""

import os
import sys
import types
from pathlib import Path

from _harness import Checks, tmpdir

import install
from install import InstallError, profile, remote

c = Checks("instalador: el perfil de conexión")

CLAVE = b"-----BEGIN OPENSSH PRIVATE KEY-----\nde mentira\n"
CONOCIDOS = "nas.example ssh-ed25519 AAAAC3NzaC1lZDI1NTE5\n"
PERFIL_TOML = profile.dumps(profile.from_form(
    "nas", {"type": "sftp", "host": "nas.example", "port": "22", "user": "quien"}))


def fingir_secreto(b64, perfil_toml=PERFIL_TOML):
    """Mete un install.secret de mentira, como el que genera la compilación."""
    mod = types.ModuleType("install.secret")
    mod.PRIVATE_KEY_B64 = b64
    mod.KNOWN_HOSTS = CONOCIDOS
    mod.PROFILE_TOML = perfil_toml
    sys.modules["install.secret"] = mod
    install.secret = mod


def quitar_secreto():
    sys.modules.pop("install.secret", None)
    if hasattr(install, "secret"):
        del install.secret


# --- 1. el perfil incrustado al compilar --------------------------------------
import base64  # noqa: E402

fingir_secreto(base64.b64encode(CLAVE).decode("ascii"))
p = profile.load()
c("se usa la clave incrustada", p.private_key, CLAVE)
c("y se dice de dónde sale", p.origen, "incrustada en el instalador")
c("con sus known_hosts", p.known_hosts, CONOCIDOS)
c("y con la conexión entera", (p.remote_name, p.options["host"]), ("nas", "nas.example"))
c("un perfil con tipo está configurado", p.configured, True)

# --- 2. una compilación sin clave no arranca ---------------------------------
fingir_secreto("__INJECT__")
try:
    profile.load()
    c("el marcador __INJECT se rechaza", "no lanzó", "InstallError")
except InstallError as e:
    c("el marcador __INJECT se rechaza", "sin clave privada" in str(e), True)
    c.contains("y se dice cómo arreglarlo", str(e), "build_installer.py")

fingir_secreto("esto no es base64 válido!!")
try:
    profile.load()
    c("una clave que no es base64 se rechaza", "no lanzó", "InstallError")
except InstallError as e:
    c("una clave que no es base64 se rechaza", "base64" in str(e), True)

quitar_secreto()

# --- 3. el perfil del checkout desde el que se ejecuta ------------------------
falso = tmpdir()
(falso / profile.PROFILE_FILE).write_text(PERFIL_TOML, encoding="utf-8")
(falso / "keys").mkdir()
(falso / "keys" / profile.DEFAULT_KEY_NAME).write_bytes(CLAVE)
(falso / "keys" / "known_hosts").write_text(CONOCIDOS, encoding="utf-8")

original = profile.bundle_dir
profile.bundle_dir = lambda: falso
try:
    p = profile.load()
    c("sin perfil incrustado se lee el del checkout", p.private_key, CLAVE)
    c.contains("y se dice de dónde", p.origen, profile.PROFILE_FILE)
    c("con su conexión", p.options["host"], "nas.example")

    # LA diferencia con lo de antes: sin nada, se sigue adelante. El asistente
    # abre su formulario en vez de morir explicando que falta una clave que quien
    # acaba de clonar el repo nunca ha tenido.
    vacio = tmpdir()
    profile.bundle_dir = lambda: vacio
    p = profile.load()
    c("sin perfil en ningún sitio NO se revienta", p.configured, False)
    c("se devuelve uno vacío", p.origen, "sin configurar")
    c("con un nombre de remote de partida", p.remote_name,
      profile.DEFAULT_REMOTE_NAME)
    c("y la ruta de catálogo de fábrica", p.catalog_path,
      profile.DEFAULT_CATALOG_PATH)
finally:
    profile.bundle_dir = original

# --- 4. el rclone.conf efímero ------------------------------------------------
perfil = profile.Profile(
    remote_name="nas",
    options={"type": "sftp", "host": "nas.example", "port": "22",
             "user": "quien", "disable_hashcheck": "true", "shell_type": "none"},
    private_key=CLAVE, known_hosts=CONOCIDOS, key_name="id_ed25519",
    origen="test")

base = tmpdir()
conf = remote.EphemeralConf(perfil, base=base)
texto = conf.conf_file.read_text(encoding="utf-8")

c("la clave se escribe tal cual", conf.key_file.read_bytes(), CLAVE)
c.contains("el conf define el remote", texto, "[nas]")
c.contains("es sftp", texto, "type = sftp")
c.contains("apunta a la clave temporal", texto, str(conf.key_file))
c.contains("y a los known_hosts", texto, "known_hosts_file")
# Muchos servidores SFTP no ofrecen md5sum por SSH; sin esto rclone pierde un rato
# largo intentando averiguarlo. Es una opción del usuario, no del proyecto: llega
# donde se tecleó y se copia tal cual.
c.contains("las opciones del backend viajan tal cual", texto,
           "disable_hashcheck = true")
c("deja constancia de qué proceso es suyo",
  (conf.dir / remote.OWNER_FILE).read_text(encoding="utf-8"), str(os.getpid()))

directorio = conf.dir
conf.close()
c("al cerrar no queda nada", directorio.exists(), False)

# Sin known_hosts no se emite la línea: apuntar a un fichero vacío hace que rclone
# rechace la conexión en vez de preguntar.
import dataclasses  # noqa: E402

sin = remote.EphemeralConf(dataclasses.replace(perfil, known_hosts=""), base=base)
c("sin known_hosts no se emite esa línea",
  "known_hosts_file" in sin.conf_file.read_text(encoding="utf-8"), False)
sin.close()

# Un backend sin fichero de clave tampoco escribe key_file: apuntar a una clave
# que no existe hace fallar a rclone en vez de dejarle autenticarse como sepa.
sin_clave = remote.EphemeralConf(
    dataclasses.replace(perfil, private_key=None, known_hosts=""), base=base)
c("sin clave privada no se emite key_file",
  "key_file" in sin_clave.conf_file.read_text(encoding="utf-8"), False)
sin_clave.close()

# --- 5. el barrido de claves huérfanas ---------------------------------------
barrido = tmpdir()
muerto = barrido / (remote.TMP_PREFIX + "muerto")
muerto.mkdir()
(muerto / remote.OWNER_FILE).write_text("999999", encoding="utf-8")

huerfano = barrido / (remote.TMP_PREFIX + "sindueno")
huerfano.mkdir()

vivo = barrido / (remote.TMP_PREFIX + "vivo")
vivo.mkdir()
(vivo / remote.OWNER_FILE).write_text(str(os.getpid()), encoding="utf-8")

remote.sweep_stale(base=barrido)
c("se borra la clave de un instalador muerto", muerto.exists(), False)
c("y la de uno sin dueño legible", huerfano.exists(), False)
# Dos instalaciones a la vez: la del otro proceso NO se toca.
c("pero no la de uno que sigue vivo", vivo.exists(), True)

# --- 6. importar un rclone.conf ajeno ----------------------------------------
ajeno = tmpdir()
(ajeno / "keys").mkdir()
(ajeno / "keys" / "mi_clave").write_bytes(CLAVE)
(ajeno / "rclone.conf").write_text(
    "# un conf de verdad tiene comentarios\n"
    "[personal]\n"
    "type = sftp\n"
    "host = otro.example\n"
    "user = yo\n"
    "key_file = keys/mi_clave\n"
    "\n"
    "[trabajo]\n"
    "type = webdav\n"
    "url = https://dav.example/\n", encoding="utf-8")

c("se ven todos los remotes del fichero",
  profile.remotes_in(ajeno / "rclone.conf"), ["personal", "trabajo"])

imp = profile.from_rclone_conf(ajeno / "rclone.conf", "personal")
c("se importa el remote elegido", imp.remote_name, "personal")
c("con sus opciones", imp.options["host"], "otro.example")
c("y la clave se LEE, no se referencia", imp.private_key, CLAVE)
c("recordando cómo se llamaba", imp.key_name, "mi_clave")
# key_file no puede viajar dentro del perfil: vale una cosa en el temporal del
# instalador y otra en el dispositivo, y la del equipo de origen no vale en
# ninguno de los dos.
c("la ruta de la clave NO se guarda", "key_file" in imp.options, False)

otro = profile.from_rclone_conf(ajeno / "rclone.conf", "trabajo")
c("un backend sin clave se importa igual",
  (otro.options["type"], otro.private_key), ("webdav", None))

try:
    profile.from_rclone_conf(ajeno / "rclone.conf", "inventado")
    c("un remote que no está se dice", "no lanzó", "InstallError")
except InstallError as e:
    c.contains("un remote que no está se dice", str(e), "personal")

# --- 7. el conf del dispositivo: relativo ------------------------------------
c("el conf efímero usa rutas absolutas",
  "key_file = /tmp/x" in profile.render_conf(perfil, key_file="/tmp/x"), True)
c("y el del dispositivo, relativas",
  "key_file = keys/id_ed25519" in profile.render_conf(
      perfil, key_file="keys/id_ed25519"), True)

# --- 8. el formulario ---------------------------------------------------------
c("las opciones se leen como en un rclone.conf",
  profile.parse_options("type = sftp\n# comentario\n\nhost = x\n"),
  {"type": "sftp", "host": "x"})
for malo, porque in (("sin igual", "falta el '='"),
                     ("key_file = /x", "lo escribe el instalador")):
    try:
        profile.parse_options(malo)
        c(f"se rechaza «{malo}»", "no lanzó", "InstallError")
    except InstallError as e:
        c.contains(f"se rechaza «{malo}»", str(e), porque)

for malo in ("", "  "):
    try:
        profile.from_form(malo, {"type": "sftp"})
        c("un remote sin nombre se rechaza", "no lanzó", "InstallError")
    except InstallError:
        c("un remote sin nombre se rechaza", True, True)

try:
    profile.from_form("con espacios y/barras", {"type": "sftp"})
    c("un nombre de remote inválido se rechaza", "no lanzó", "InstallError")
except InstallError as e:
    c.contains("un nombre de remote inválido se rechaza", str(e), "no vale")

try:
    profile.from_form("nas", {"host": "x"})
    c("sin tipo de backend se rechaza", "no lanzó", "InstallError")
except InstallError as e:
    c.contains("sin tipo de backend se rechaza", str(e), "tipo de remote")

# --- 9. el perfil va y vuelve, sin la clave -----------------------------------
vuelta = profile.loads(profile.dumps(perfil))
c("el perfil se relee igual",
  (vuelta.remote_name, dict(vuelta.options), vuelta.catalog_path),
  (perfil.remote_name, dict(perfil.options), perfil.catalog_path))
c("y el texto NO lleva la clave dentro",
  "PRIVATE" in profile.dumps(perfil), False)

# --- 10. cómo se le habla a rclone -------------------------------------------
llamadas = []


def falso_runner(cmd, **kw):
    import subprocess
    llamadas.append((cmd, kw))
    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


r = remote.Rclone("RCLONE", "CONF", runner=falso_runner, remote_name="nas")
c("el config va siempre delante", r.command("lsd", "x:"),
  ["RCLONE", "--config", "CONF", "lsd", "x:"])
c("el endpoint es 'remote:ruta' y nada más", r.endpoint("/a/b"), "nas:/a/b")
r.run("cat", "x:/y", capture=True, timeout=5)
c("se pide capturar la salida cuando toca", llamadas[-1][1]["capture_output"], True)
c("y el timeout viaja", llamadas[-1][1]["timeout"], 5)


def falla(cmd, **kw):
    import subprocess
    return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no such host")


try:
    remote.Rclone("RCLONE", "CONF", runner=falla, remote_name="nas").check_connection()
    c("un remoto que no contesta se cuenta", "no lanzó", "InstallError")
except InstallError as e:
    c.contains("un remoto que no contesta se cuenta", str(e), "no such host")

sys.exit(c.report())
