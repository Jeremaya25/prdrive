#!/usr/bin/env python3
"""
La clave del NAS: de dónde sale y cuánto rato está en el disco.

Esto es lo más delicado del instalador. Se comprueba:

  * La cadena de resolución: primero la clave incrustada al compilar, y si no la
    hay, la del pen desde el que se ejecuta el .py.
  * Que una compilación mal hecha —con el marcador `__INJECT` todavía puesto— se
    niega a arrancar en vez de intentar conectarse con una clave de mentira.
  * Que el rclone.conf efímero sale bien y que al cerrar no queda nada.
  * Que el barrido de arranque se lleva las claves que dejaron instaladores
    muertos, pero NO las de uno que siga vivo (dos instalaciones a la vez).

No se usa la clave de verdad en ningún momento: todas las de aquí son inventadas.
"""

import os
import sys
import types
from pathlib import Path

from _harness import Checks, tmpdir

import install
from install import InstallError, remote

c = Checks("instalador: la clave y el conf efímero")

CLAVE = b"-----BEGIN OPENSSH PRIVATE KEY-----\nde mentira\n"
CONOCIDOS = "nas.example ssh-ed25519 AAAAC3NzaC1lZDI1NTE5\n"


def fingir_secreto(b64):
    """Mete un install.secret de mentira, como el que genera la compilación."""
    mod = types.ModuleType("install.secret")
    mod.PRIVATE_KEY_B64 = b64
    mod.KNOWN_HOSTS = CONOCIDOS
    sys.modules["install.secret"] = mod
    install.secret = mod


def quitar_secreto():
    sys.modules.pop("install.secret", None)
    if hasattr(install, "secret"):
        del install.secret


# --- 1. la clave incrustada al compilar --------------------------------------
import base64  # noqa: E402

fingir_secreto(base64.b64encode(CLAVE).decode("ascii"))
creds = remote.load_credentials()
c("se usa la clave incrustada", creds.private_key, CLAVE)
c("y se dice de dónde sale", creds.origen, "incrustada en el instalador")
c("con sus known_hosts", creds.known_hosts, CONOCIDOS)

# --- 2. una compilación sin clave no arranca ---------------------------------
fingir_secreto("__INJECT__")
try:
    remote.load_credentials()
    c("el marcador __INJECT se rechaza", "no lanzó", "InstallError")
except InstallError as e:
    c("el marcador __INJECT se rechaza", "sin clave privada" in str(e), True)
    c.contains("y se dice cómo arreglarlo", str(e), "build_installer.py")

fingir_secreto("esto no es base64 válido!!")
try:
    remote.load_credentials()
    c("una clave que no es base64 se rechaza", "no lanzó", "InstallError")
except InstallError as e:
    c("una clave que no es base64 se rechaza", "base64" in str(e), True)

quitar_secreto()

# --- 3. la clave del pen desde el que se ejecuta ------------------------------
falso_pen = tmpdir()
(falso_pen / "keys").mkdir()
(falso_pen / "keys" / "synology_ed25519").write_bytes(CLAVE)
(falso_pen / "keys" / "known_hosts").write_text(CONOCIDOS, encoding="utf-8")

original = remote.bundle_dir
remote.bundle_dir = lambda: falso_pen
try:
    creds = remote.load_credentials()
    c("sin clave incrustada se lee la del pen", creds.private_key, CLAVE)
    c.contains("y se dice de dónde", creds.origen, "keys")

    vacio = tmpdir()
    remote.bundle_dir = lambda: vacio
    try:
        remote.load_credentials()
        c("sin clave en ningún sitio se explica qué falta", "no lanzó", "InstallError")
    except InstallError as e:
        c.contains("sin clave en ningún sitio se explica qué falta",
                   str(e), "build_installer.py")
finally:
    remote.bundle_dir = original

# --- 4. el rclone.conf efímero ------------------------------------------------
base = tmpdir()
conf = remote.EphemeralConf(remote.Credentials(CLAVE, CONOCIDOS, "test"), base=base)
texto = conf.conf_file.read_text(encoding="utf-8")

c("la clave se escribe tal cual", conf.key_file.read_bytes(), CLAVE)
c.contains("el conf define el remote", texto, "[synology]")
c.contains("es sftp", texto, "type = sftp")
c.contains("apunta a la clave temporal", texto, str(conf.key_file))
c.contains("y a los known_hosts", texto, "known_hosts_file")
# El Synology no ofrece md5sum por SSH; sin esto rclone pierde un rato largo.
c.contains("sin comprobación de hash", texto, "disable_hashcheck = true")
c("deja constancia de qué proceso es suyo",
  (conf.dir / remote.OWNER_FILE).read_text(encoding="utf-8"), str(os.getpid()))

directorio = conf.dir
conf.close()
c("al cerrar no queda nada", directorio.exists(), False)

# Sin known_hosts no se emite la línea: apuntar a un fichero vacío hace que rclone
# rechace la conexión en vez de preguntar.
sin = remote.EphemeralConf(remote.Credentials(CLAVE, "", "test"), base=base)
c("sin known_hosts no se emite esa línea",
  "known_hosts_file" in sin.conf_file.read_text(encoding="utf-8"), False)
sin.close()

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

# --- 6. cómo se le habla a rclone --------------------------------------------
llamadas = []


def falso(cmd, **kw):
    import subprocess
    llamadas.append((cmd, kw))
    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


r = remote.Rclone("RCLONE", "CONF", runner=falso)
c("el config va siempre delante", r.command("lsd", "x:"),
  ["RCLONE", "--config", "CONF", "lsd", "x:"])
r.run("cat", "x:/y", capture=True, timeout=5)
c("se pide capturar la salida cuando toca", llamadas[-1][1]["capture_output"], True)
c("y el timeout viaja", llamadas[-1][1]["timeout"], 5)


def falla(cmd, **kw):
    import subprocess
    return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no such host")


try:
    remote.Rclone("RCLONE", "CONF", runner=falla).check_connection()
    c("un NAS que no contesta se cuenta", "no lanzó", "InstallError")
except InstallError as e:
    c.contains("un NAS que no contesta se cuenta", str(e), "no such host")

sys.exit(c.report())
