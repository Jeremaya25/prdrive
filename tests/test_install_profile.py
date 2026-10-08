#!/usr/bin/env python3
"""El perfil de conexión: de dónde sale y cuánto rato está la clave en el disco.

Esto es lo más delicado del instalador. Se comprueba:
- La cascada: primero el perfil incrustado al compilar, luego el del checkout
  desde el que se ejecuta el .py y, si no hay ninguno, uno **vacío**. Que no
  haya perfil NO es un error: es el arranque normal de quien acaba de clonar el
  repositorio.
- Que una compilación mal hecha (con el marcador `__INJECT` todavía puesto) se
  niega en vez de intentar conectarse con una clave de mentira.
- Que el `rclone.conf` sale bien tanto en su forma efímera (rutas absolutas al
  temporal) como en la del dispositivo (relativas), y que al cerrar el temporal
  no queda nada.
- Que el barrido de arranque se lleva las claves que dejaron instaladores
  muertos, pero NO las de uno que siga vivo (dos instalaciones a la vez).
- Que el backend no se interpreta en ningún sitio: lo que se teclea es lo que
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
    """Quita el `install.secret` de mentira de los módulos cargados."""
    sys.modules.pop("install.secret", None)
    if hasattr(install, "secret"):
        del install.secret


# 1. el perfil incrustado al compilar
import base64  # noqa: E402

fingir_secreto(base64.b64encode(CLAVE).decode("ascii"))
p = profile.load()
c("se usa la clave incrustada", p.private_key, CLAVE)
c("y se dice de dónde sale", p.origen, "incrustada en el instalador")
c("con sus known_hosts", p.known_hosts, CONOCIDOS)
c("y con la conexión entera", (p.remote_name, p.options["host"]), ("nas", "nas.example"))
c("un perfil con tipo está configurado", p.configured, True)

# 2. una compilación sin clave no arranca
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

# 3. el perfil del checkout desde el que se ejecuta
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

    # Sin nada, se sigue adelante: el asistente abre su formulario en vez de
    # morir explicando que falta una clave que quien acaba de clonar el repo
    # nunca ha tenido.
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

# 4. el rclone.conf efímero
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

# 5. el barrido de claves huérfanas
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

# 6. importar un rclone.conf ajeno
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

# Importar exige lo mismo que el formulario (#47): un remote sin `type` no
# puede salir de aquí como perfil sin estar `configured` (la pantalla pintaría
# ✔ y «Siguiente» se quedaría gris, sin decir por qué).
(ajeno / "incompleto.conf").write_text(
    "[sintipo]\n"
    "host = otro.example\n"
    "\n"
    "[tipovacio]\n"
    "type = \n"
    "host = otro.example\n"
    "\n"
    "[sinhost]\n"
    "type = sftp\n"
    "user = yo\n"
    "key_file = keys/mi_clave\n"
    "\n"
    "[conssh]\n"
    "type = sftp\n"
    "ssh = ssh -o ServerAliveInterval=20 yo@otro.example\n", encoding="utf-8")
for cual, porque in (("sintipo", "type = …"), ("tipovacio", "type = …"),
                     ("sinhost", "host = …")):
    try:
        profile.from_rclone_conf(ajeno / "incompleto.conf", cual)
        c(f"importar «{cual}» se rechaza", "no lanzó", "InstallError")
    except InstallError as e:
        c.contains(f"importar «{cual}» se rechaza diciendo qué falta", str(e), porque)
        c.contains(f"y de qué remote habla («{cual}»)", str(e), f"'{cual}'")
# Con el ssh externo, rclone ignora host, user y port del conf: los lleva la
# orden. Exigir `host` ahí sería rechazar una configuración que funciona.
ssh = profile.from_rclone_conf(ajeno / "incompleto.conf", "conssh")
c("un sftp con ssh externo se importa sin host", ssh.configured, True)
c("y sin avisar del usuario, que va en la orden", profile.avisos(ssh), [])

# 7. el conf del dispositivo: relativo
c("el conf efímero usa rutas absolutas",
  "key_file = /tmp/x" in profile.render_conf(perfil, key_file="/tmp/x"), True)
c("y el del dispositivo, relativas",
  "key_file = keys/id_ed25519" in profile.render_conf(
      perfil, key_file="keys/id_ed25519"), True)

# 8. el formulario
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

# La plantilla tal cual (#47): `from_form` descarta los valores vacíos, así que
# queda `{"type": "sftp"}`, y eso daría un perfil «configurado» que rclone
# llevaría a `:22`, este mismo equipo.
for tipo, falta in (("sftp", "host = …"), ("webdav", "url = …")):
    opciones = profile.parse_options(profile.PLANTILLAS[tipo])
    opciones["type"] = tipo
    try:
        profile.from_form("nas", opciones)
        c(f"la plantilla de {tipo} sin rellenar se rechaza", "no lanzó", "InstallError")
    except InstallError as e:
        c.contains(f"la plantilla de {tipo} sin rellenar se rechaza, diciendo qué falta",
                   str(e), falta)
try:
    profile.from_form("nas", {"type": "sftp", "host": "   "})
    c("un host en blanco cuenta como ausente", "no lanzó", "InstallError")
except InstallError as e:
    c.contains("un host en blanco cuenta como ausente", str(e), "host = …")

# Criterio conservador: solo bloquea lo que rclone marca obligatorio y no tiene
# otra salida. Un s3 sin claves entra como anónimo, y un tipo sin plantilla no se
# interpreta: los dos los juzga el paso de comprobaciones, hablando con rclone.
opciones = profile.parse_options(profile.PLANTILLAS["s3"])
opciones["type"] = "s3"
c("la plantilla de s3 no tiene obligatorias", profile.from_form("nas", opciones).configured,
  True)
c("un tipo sin plantilla no se valida aquí",
  profile.from_form("nas", {"type": "stfp"}).configured, True)
# Lo que bloquea tiene que estar en su plantilla: si no, el formulario exigiría
# un campo que no enseña.
for tipo, obligatorias in profile.OBLIGATORIAS.items():
    c(f"las obligatorias de {tipo} están en su plantilla",
      {clave for clave, _ in obligatorias} <= set(
          linea.partition("=")[0].strip()
          for linea in profile.PLANTILLAS[tipo].splitlines()), True)

# El usuario de un sftp: no bloquea —puede funcionar donde se instala— pero se
# avisa, porque rclone usa el de cada equipo y el dispositivo viaja.
sin_user = profile.from_form("nas", {"type": "sftp", "host": "nas.example"})
c("un sftp sin user se acepta", sin_user.configured, True)
avisado = profile.avisos(sin_user)
c("pero se avisa, una vez", len(avisado), 1)
c.contains("de qué campo", avisado[0] if avisado else "", "user = …")
c("con user no hay nada que avisar", profile.avisos(profile.from_form(
    "nas", {"type": "sftp", "host": "nas.example", "user": "quien"})), [])
c("y un webdav sin user tampoco: es anónimo a propósito", profile.avisos(
    profile.from_form("nas", {"type": "webdav", "url": "https://dav.example/"})), [])

# 9. el perfil va y vuelve, sin la clave
vuelta = profile.loads(profile.dumps(perfil))
c("el perfil se relee igual",
  (vuelta.remote_name, dict(vuelta.options), vuelta.catalog_path),
  (perfil.remote_name, dict(perfil.options), perfil.catalog_path))
c("y el texto NO lleva la clave dentro",
  "PRIVATE" in profile.dumps(perfil), False)


# 10. cómo se le habla a rclone
llamadas = []


def falso_runner(cmd, **kw):
    """Runner de mentira: apunta la orden y sale bien."""
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
    """Runner de mentira que falla: el remoto no existe."""
    import subprocess
    return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no such host")


try:
    remote.Rclone("RCLONE", "CONF", runner=falla, remote_name="nas").check_connection()
    c("un remoto que no contesta se cuenta", "no lanzó", "InstallError")
except InstallError as e:
    c.contains("un remoto que no contesta se cuenta", str(e), "no such host")


# 11. lo que el catálogo no puede imponer, y un conf que no se rompe
def rechaza(etiqueta, accion, porque):
    """Comprueba que `accion()` lanza `InstallError` y que el mensaje dice `porque`."""
    try:
        accion()
        c(etiqueta, "no lanzó", "InstallError")
    except InstallError as e:
        c.contains(etiqueta, str(e), porque)


# Un `rclone.conf` no tiene escape para el salto de línea: un valor con uno
# escribiría una opción nueva (u otro remote) que nadie tecleó. Valen también los
# que parte `str.splitlines()`, que es como el proyecto lee un `rclone.conf`.
for salto in ("\n", "\r", "\r\n", chr(0x85), chr(0x2028)):
    roto = dataclasses.replace(
        perfil, options={**perfil.options, "user": f"quien{salto}type = alias"})
    rechaza("render_conf rechaza un valor con salto de línea" if salto == "\n"
            else f"render_conf rechaza un valor con {salto!r}",
            lambda roto=roto: profile.render_conf(roto), "'user'")
# El nombre se valida con la regla de rclone, no con la de `from_form`: un remote
# que ya existe (en un rclone.conf importado o en `[defaults].remote`) no puede
# quedarse sin dispositivos nuevos porque lleve un espacio o una arroba.
for nombre in ("nas]x", "nas\n[x", "a,b", "a:b", "a=b", "a'b", "-nas", "nas "):
    rechaza("render_conf rechaza un nombre de remote que rclone no admite"
            if nombre == "nas]x" else
            f"render_conf rechaza el nombre {nombre!r}",
            lambda nombre=nombre: profile.render_conf(
                dataclasses.replace(perfil, remote_name=nombre)), "no vale")
for nombre in ("Mi NAS", "almacén", "nas@home", "nas+b", "nas.1-b_2"):
    c(f"render_conf escribe el remote {nombre!r}",
      profile.render_conf(dataclasses.replace(perfil, remote_name=nombre)
                          ).splitlines()[0], f"[{nombre}]")
c("lo tecleado en el asistente sigue siendo más estricto",
  [n for n in ("Mi NAS", "nas@home", "nas") if profile.NOMBRE_VALIDO.fullmatch(n)],
  ["nas"])
# Una sola regla de rclone para el nombre: la de `model`.
from common import model  # noqa: E402

c("NOMBRE_RCLONE es la regla del config, no una copia",
  profile.NOMBRE_RCLONE is model.NOMBRE_REMOTE, True)
rechaza("render_conf rechaza el nombre de una opción con símbolos",
        lambda: profile.render_conf(dataclasses.replace(
            perfil, options={**perfil.options, "a b\n[x": "1"})), "'a b\\n[x'")
rechaza("y un salto de línea en una ruta de la clave",
        lambda: profile.render_conf(perfil, key_file="keys/a\nb"), "key_file")

# Un conf que se rechaza no deja la clave suelta en el temporal: `EphemeralConf`
# genera el conf antes de escribir nada y, si algo falla, se lleva su directorio.
sucia = tmpdir()
for etiqueta, malo, porque in (
        ("un nombre de remote inválido",
         dataclasses.replace(perfil, remote_name="nas]x"), "no vale"),
        ("un valor con salto de línea",
         dataclasses.replace(perfil, options={**perfil.options, "user": "a\nb"}),
         "'user'")):
    rechaza(f"EphemeralConf rechaza {etiqueta}",
            lambda malo=malo: remote.EphemeralConf(malo, base=sucia), porque)
    c(f"y con {etiqueta} no queda ningún prdrive-key-* con la clave",
      list(sucia.glob(remote.TMP_PREFIX + "*")), [])
    c(f"ni queda apuntado para cerrarlo ({etiqueta})",
      [e for e in remote._ABIERTAS if e.dir.parent == sucia], [])

# Qué es una orden y qué es un secreto: el criterio de no heredar ni exportar.
c("las opciones que ejecutan algo en este equipo",
  sorted(profile.OPCIONES_QUE_EJECUTAN), ["bearer_token_command", "ssh"])
for clave in ("key", "pass", "password", "token", "secret_access_key", "client_secret",
              "key_pem", "sas_url", "account_key", "key_file_pass",
              "bearer_token_command", "credentials_file", "PASS",
              "api_key", "sse_customer_key", "sse_customer_key_base64",
              "access_grant", "connection_string", "2fa",
              "cookies", "authorization", "authorization_expiry", "headers"):
    c(f"{clave} es secreta", profile.es_secreta(clave), True)
for clave in ("type", "host", "user", "port", "url", "vendor", "provider",
              "access_key_id", "key_file", "known_hosts_file", "shell_type",
              "disable_hashcheck", "region", "endpoint", "sse_kms_key_id",
              "key_exchange", "user_agent"):
    c(f"{clave} no es secreta", profile.es_secreta(clave), False)

base_nas = profile.from_form("nas", {"type": "sftp", "host": "h"})
cat_ssh = {"defaults": {"remote": "nas"},
           "remote": {"type": "sftp", "host": "h", "ssh": "sh -c id"}}
ajustado, notas = profile.align_with_catalog(base_nas, cat_ssh)
c("el catálogo no pasa ssh ni secretos",
  ("ssh" in ajustado.options,
   len([n for n in notas if "`ssh`: no se hereda" in n])), (False, 1))
c.contains("y la nota dice por qué", " ".join(notas), "es una orden de este equipo")
c("lo que no era orden sí se hereda", dict(ajustado.options),
  {"type": "sftp", "host": "h"})

cat_secretos = {"defaults": {"remote": "nas"},
                "remote": {"type": "sftp", "host": "h", "ssh": "sh -c id",
                           "pass": "ajeno", "key_pem": "pem"}}
ajustado, notas = profile.align_with_catalog(base_nas, cat_secretos)
c("el catálogo no pasa ni ssh ni secretos (pass, key_pem)",
  sorted(ajustado.options), ["host", "type"])
c("hay una nota para la orden y otra para los secretos", len(notas), 2)
c.contains("la de los secretos nombra las claves", " ".join(notas), "`key_pem` y `pass`")
c.contains("y dice que se pueden quitar del catálogo", " ".join(notas), "Se pueden quitar")
texto_conf = profile.render_conf(ajustado)
c("y aun así el dispositivo se provisiona, sin nada de eso",
  ("sh -c id" in texto_conf, "ajeno" in texto_conf, "pem" in texto_conf,
   "host = h" in texto_conf), (False, False, False, True))

# El mismo filtro en el otro lector del catálogo; este no tiene dónde dar notas.
leido = profile.with_catalog_remote(base_nas, {
    "type": "sftp", "host": "h2", "ssh": "sh -c id", "pass": "ajeno"})
c("with_catalog_remote filtra lo mismo", dict(leido.options),
  {"type": "sftp", "host": "h2"})

# Lo que el usuario teclea en el asistente es suyo: ahí `ssh` sí se admite.
propio = profile.from_form(
    "nas", {"type": "sftp", "host": "h", "ssh": "ssh -J x"})
c("lo tecleado aquí sí admite ssh", propio.options.get("ssh"), "ssh -J x")
c.contains("y llega al conf del dispositivo", profile.render_conf(propio),
           "ssh = ssh -J x")

# Si la conexión con la que se acaba de entrar lleva algo propio que es secreto o
# una orden, el dispositivo se queda con ella tal cual: sus contraseñas no se
# entregan a una conexión que el catálogo describa distinta y nadie ha comprobado.
con_clave = profile.from_form(
    "nas", {"type": "sftp", "host": "h", "user": "u", "pass": "oculta"})
ajustado, notas = profile.align_with_catalog(con_clave, {
    "defaults": {"remote": "nas"},
    "remote": {"type": "sftp", "host": "h2", "user": "u2"}})
c("un [remote] de otra conexión no recibe el pass del perfil",
  dict(ajustado.options), dict(con_clave.options))
otra = [n for n in notas if "describe otra conexión" in n]
c("y se dice, una vez", len(otra), 1)
c.contains("con su porqué", otra[0] if otra else "",
           "no se dan a una conexión que no se ha comprobado")
c("sin decir que las opciones salen del catálogo",
  [n for n in notas if "salen del [remote]" in n], [])
ajustado, notas = profile.align_with_catalog(con_clave, {
    "defaults": {"remote": "nas"},
    "remote": {"type": "sftp", "host": "h", "user": "u", "pass": "otra"}})
c("el pass del catálogo no pisa al del perfil", ajustado.options["pass"], "oculta")
c("si lo no secreto coincide, el perfil se queda como está",
  dict(ajustado.options), dict(con_clave.options))
c("y no se dice que sea otra conexión ni que cambie nada",
  [n for n in notas if "otra conexión" in n or "salen del [remote]" in n], [])
con_ssh = profile.from_form(
    "nas", {"type": "sftp", "host": "h", "ssh": "ssh -J x"})
ajustado, notas = profile.align_with_catalog(con_ssh, {
    "defaults": {"remote": "nas"}, "remote": {"type": "sftp", "host": "h2"}})
c("el ssh que se tecleó aquí tampoco se entrega a otro host",
  dict(ajustado.options), dict(con_ssh.options))
c("y también se dice", any("describe otra conexión" in n for n in notas), True)
c("with_catalog_remote deja igual un perfil con secretos",
  profile.with_catalog_remote(con_clave, {"type": "sftp", "host": "h2"}), con_clave)
# Sin nada propio que sea secreto ni orden, se adopta el [remote] ya filtrado.
ajustado, notas = profile.align_with_catalog(base_nas, {
    "defaults": {"remote": "nas"},
    "remote": {"type": "sftp", "host": "h2", "user": "u2", "ssh": "sh -c id"}})
c("sin nada propio secreto se adopta el [remote] filtrado", dict(ajustado.options),
  {"type": "sftp", "host": "h2", "user": "u2"})
c.contains("y se dice que las opciones salen del catálogo", " ".join(notas),
           "salen del [remote] del catálogo")

# TOML trae números y booleanos de verdad; rclone los escribe como texto
# («22», «true»). El mismo valor no puede parecer otra conexión por cómo se escriba.
con_opciones = profile.from_form("nas", {
    "type": "sftp", "host": "h", "user": "u", "pass": "oculta", "port": "22",
    "disable_hashcheck": "true"})
cat_tipos = {"defaults": {"remote": "nas"},
             "remote": {"type": "sftp", "host": "h", "user": "u", "port": 22,
                        "disable_hashcheck": True}}
ajustado, notas = profile.align_with_catalog(con_opciones, cat_tipos)
c("un entero y un booleano del catálogo no son otra conexión",
  [n for n in notas if "otra conexión" in n or "salen del [remote]" in n], [])
c("y el perfil se queda como está", dict(ajustado.options), dict(con_opciones.options))
ajustado, _ = profile.align_with_catalog(base_nas, cat_tipos)
c("sin nada propio secreto se adopta el booleano como lo escribe rclone",
  dict(ajustado.options),
  {"type": "sftp", "host": "h", "user": "u", "port": "22",
   "disable_hashcheck": "true"})
ajustado, _ = profile.align_with_catalog(base_nas, {
    "defaults": {"remote": "nas"},
    "remote": {"type": "sftp", "host": "h", "disable_hashcheck": False}})
c("y un false también", ajustado.options["disable_hashcheck"], "false")
c.contains("el conf lleva «true», no «True»", profile.render_conf(
    profile.align_with_catalog(base_nas, cat_tipos)[0]), "disable_hashcheck = true")
c("with_catalog_remote también los escribe como rclone",
  profile.with_catalog_remote(base_nas, cat_tipos["remote"]).options["disable_hashcheck"],
  "true")

# Un `[remote]` al que, sin lo que no se hereda, le falta algo que rclone exige
# no se usa: el dispositivo se quedaría con un sftp que marca `:22`, este equipo.
sin_host = {"defaults": {"remote": "nas"},
            "remote": {"type": "sftp", "ssh": "sh -c id"}}
ajustado, notas = profile.align_with_catalog(base_nas, sin_host)
c("un [remote] que sin ssh no tiene host no se usa", dict(ajustado.options),
  dict(base_nas.options))
rechazo = [n for n in notas if "No se usa el [remote] del catálogo" in n]
c("y se dice una vez", len(rechazo), 1)
c.contains("por qué: lo que no se hereda", rechazo[0] if rechazo else "", "sin `ssh`")
c.contains("y qué le falta", rechazo[0] if rechazo else "", "«host = …»")
c("with_catalog_remote tampoco lo usa",
  dict(profile.with_catalog_remote(base_nas, sin_host["remote"]).options),
  dict(base_nas.options))
ajustado, notas = profile.align_with_catalog(con_ssh, sin_host)
c("con el ssh tecleado aquí el perfil se queda como está",
  dict(ajustado.options), dict(con_ssh.options))
# La nota no puede decir que se quitó algo cuando no se quitó, ni cuando lo
# quitado no es lo que hacía falta.
for incompleto, cual in (({"type": "sftp", "user": "u"}, "sin nada quitado"),
                         ({"type": "sftp", "pass": "x"}, "quitando solo un secreto")):
    ajustado, notas = profile.align_with_catalog(
        base_nas, {"defaults": {"remote": "nas"}, "remote": incompleto})
    rechazo = [n for n in notas if "No se usa el [remote] del catálogo" in n]
    c(f"un [remote] sin host no se usa ({cual})",
      (dict(ajustado.options), len(rechazo)), (dict(base_nas.options), 1))
    c.contains(f"y dice qué le falta ({cual})", rechazo[0] if rechazo else "",
               "le falta «host = …»")
    c(f"sin atribuirlo a lo no heredado ({cual})",
      "sin `" in (rechazo[0] if rechazo else ""), False)

# Lo que se enseña para guardar en el catálogo no lleva nada secreto.
con_secretos = profile.Profile(
    remote_name="nas",
    options={"type": "sftp", "host": "h", "user": "u", "port": "22",
             "pass": "oculta", "token": "t", "secret_access_key": "s",
             "key_pem": "k", "ssh": "ssh -J x", "bearer_token_command": "cmd"})
c("to_catalog_remote no lleva secretos",
  profile.to_catalog_remote(con_secretos),
  {"name": "nas", "type": "sftp", "host": "h", "user": "u", "port": "22"})

sys.exit(c.report())
