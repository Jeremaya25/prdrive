#!/usr/bin/env python3
"""
El despliegue: qué deja el instalador en el dispositivo y dónde.

Antes esto era la siembra —un `rclone sync` del espejo maestro del remoto—, y lo
que había que vigilar era que no arrasara el destino. Ahora el instalador lleva el
programa dentro y lo copia, así que lo que se comprueba es otra cosa:

  * que aterriza TODO lo que el dispositivo necesita para arrancar solo, y en la
    carpeta oculta que le toca;
  * que el `rclone.conf` que se escribe usa rutas RELATIVAS, que es lo que hace
    que el dispositivo funcione con otra letra de unidad;
  * que copiar no toca nada de fuera de esa carpeta;
  * y que `install_target()` sigue distinguiendo un volumen ajeno.

Ningún test lanza rclone ni toca la red: se comprueban ficheros y listas de
argumentos, nunca la ejecución.
"""

import sys
from pathlib import Path

from _harness import Checks, tmpdir

from install import InstallError, deploy, profile, remote

c = Checks("instalador: el despliegue")

CATALOGO = """\
[defaults]
remote = "nas"
exclude = ["**/.stignore"]

[defaults.flags]
transfers = 4
max-delete = 10

[[pair]]
name = "respaldo"
local = "."
remote_path = "/respaldo"
mode = "up-mirror"

[[pair]]
name = "docs"
local = "sync-data/docs"
remote_path = "/datos/docs"
mode = "bisync"

[[pair]]
name = "upload"
local = "sync-data/upload"
remote_path = "/datos/varios"
mode = "up"
"""

cat = remote.parse_catalog(CATALOGO)


def arbol_falso() -> Path:
    """Un checkout de mentira con lo que `deploy_code()` espera encontrar."""
    base = tmpdir() / "origen"
    (base / "common").mkdir(parents=True)
    (base / "ui").mkdir(parents=True)
    (base / "ui" / "__pycache__").mkdir()
    for nombre in deploy.DEPLOY_FILES:
        (base / nombre).write_text(f"# {nombre}\n", encoding="utf-8")
    (base / "common" / "model.py").write_text("# model\n", encoding="utf-8")
    (base / "ui" / "tk.py").write_text("# tk\n", encoding="utf-8")
    (base / "ui" / "__pycache__" / "tk.pyc").write_bytes(b"basura")
    # Lo que NO se despliega: el dispositivo no instala nada.
    (base / "install").mkdir()
    (base / "install" / "secret.py").write_text("SECRETO\n", encoding="utf-8")
    return base


# --- copiar el programa -------------------------------------------------------
origen = arbol_falso()
rclone_falso = origen / "rclone-de-mentira"
rclone_falso.write_bytes(b"MZ")

destino = tmpdir() / "unidad"
destino.mkdir()
(destino / "mis-cosas.txt").write_text("no me toques\n", encoding="utf-8")

escrito = deploy.deploy_code(destino, rclone_falso, origen=origen)
app = destino / deploy.APP_SUBDIR

c("la carpeta del código empieza por punto", deploy.APP_SUBDIR.startswith("."), True)
c("y cuelga del dispositivo", app.is_dir(), True)
for nombre in deploy.DEPLOY_FILES:
    c(f"llega {nombre}", (app / nombre).is_file(), True)
c("llega el paquete common/", (app / "common" / "model.py").is_file(), True)
c("llega el paquete ui/", (app / "ui" / "tk.py").is_file(), True)
c("el __pycache__ del origen no viaja", (app / "ui" / "__pycache__").exists(), False)

# El instalador no tiene nada que hacer en el dispositivo, y su secret.py es justo
# lo que no puede acabar suelto por ahí.
c("install/ NO se despliega", (app / "install").exists(), False)

c("el binario de rclone va donde lo busca el modelo",
  (app / "bin" / deploy.bin_subdir() / deploy.exe_name()).is_file(), True)
c("se dice todo lo que se ha escrito", len(escrito) >= 6, True)

# Copiar no es un espejo: lo que ya estaba en el volumen sigue estando. Esto es
# exactamente lo que la siembra NO podía prometer.
c("lo que había en el volumen no se toca",
  (destino / "mis-cosas.txt").read_text(encoding="utf-8"), "no me toques\n")

# --- actualizar: lo mismo, pero sin tocar el rclone ni nada del usuario -------
# Es el camino de `prdrive-install.py --update`, que corre desde el zip recién
# descargado sobre un dispositivo que ya existe. Lo que se vigila es lo único
# que puede hacer daño: que se lleve por delante la configuración o la clave.
al_dia = tmpdir() / "unidad-usada"
app_usada = al_dia / deploy.APP_SUBDIR
(app_usada / "keys").mkdir(parents=True)
(app_usada / "state" / "docs").mkdir(parents=True)
(app_usada / "keys" / "id_ed25519").write_bytes(b"CLAVE-QUE-NO-SE-TOCA")
(app_usada / "rclone.conf").write_text("[nas]\nkey_file = keys/id_ed25519\n",
                                       encoding="utf-8")
(app_usada / "sync_config.toml").write_text("# lo mío\n", encoding="utf-8")
(app_usada / "state" / "docs" / "listado.lst").write_text("x\n", encoding="utf-8")
(app_usada / "sync.py").write_text("# version vieja\n", encoding="utf-8")

nuevo = deploy.deploy_code(al_dia, origen=origen)

c("actualizar sustituye el código",
  (app_usada / "sync.py").read_text(encoding="utf-8"), "# sync.py\n")
c("y deja el VERSION nuevo", (app_usada / "VERSION").is_file(), True)
# Sin binario que copiar no se crea bin/: el del dispositivo ya está puesto, y
# pasarle el suyo propio como origen daría SameFileError.
c("sin rclone no se toca bin/", (app_usada / "bin").exists(), False)
c("ni se cuenta entre lo escrito", any("bin" in p.parts for p in nuevo), False)
c("la clave privada sigue intacta",
  (app_usada / "keys" / "id_ed25519").read_bytes(), b"CLAVE-QUE-NO-SE-TOCA")
c("el rclone.conf del dispositivo sigue intacto",
  (app_usada / "rclone.conf").read_text(encoding="utf-8"),
  "[nas]\nkey_file = keys/id_ed25519\n")
c("su sync_config.toml sigue intacto",
  (app_usada / "sync_config.toml").read_text(encoding="utf-8"), "# lo mío\n")
c("y la línea base de bisync no se ha movido",
  (app_usada / "state" / "docs" / "listado.lst").is_file(), True)

# --- los lanzadores -----------------------------------------------------------
# La completa lleva Python propio, así que no depende de la asociación .pyw ->
# pythonw.exe que solo existe con un Python instalado: .bat y .sh, y nada más.
lanzadores = deploy.write_launchers(destino, completa=True)
c("la completa escribe exactamente .bat y .sh", sorted(p.name for p in lanzadores),
  ["runsync.bat", "runsync.sh"])
c("y en la raíz del volumen, no dentro de la carpeta oculta",
  {p.parent for p in lanzadores}, {destino})

ligera = deploy.write_launchers(destino, completa=False)
c("la ligera añade el .pyw, que solo sirve con un Python en el equipo",
  sorted(p.name for p in ligera), ["runsync.bat", "runsync.pyw", "runsync.sh"])
pyw = (destino / "runsync.pyw").read_text(encoding="utf-8")
c.contains("el .pyw apunta a la carpeta del código", pyw, deploy.APP_SUBDIR)
c.contains("y arranca runsync.py", pyw, "runsync.py")

deploy.write_launchers(destino, completa=True)
c("pasar de ligera a completa quita el .pyw que ya no hace falta",
  (destino / "runsync.pyw").exists(), False)

bat = (destino / "runsync.bat").read_bytes().decode("utf-8")
c("el .bat va con CRLF, que es lo que cmd lee sin sorpresas con los goto",
  "\r\n" in bat and "\n" not in bat.replace("\r\n", ""), True)
c.contains("elige por la arquitectura que cmd ve de verdad", bat,
           "%PROCESSOR_ARCHITECTURE%")
# El orden es la cadena del issue: ARM64 propio, x64 propio (emulado en un ARM64,
# y el .bat corre en el cmd nativo, así que la variable dice la verdad), y el
# Python del equipo si no hay ninguno.
orden_bat = [bat.index(r"runtime\windows-arm64\pythonw.exe"),
             bat.index(r"runtime\windows-x64\pythonw.exe"),
             bat.index("(pythonw.exe)")]
c("prueba el ARM64 propio, luego el x64 propio y luego el del equipo",
  orden_bat, sorted(orden_bat))
c.contains("se suelta con start y la consola no se queda", bat, 'start ""')
c.contains("arranca el runsync.py del dispositivo", bat,
           rf"%APP%\runsync.py")
c.contains("sin ningún Python dice cómo se arregla", bat, "Añadir plataformas")
c.contains("y espera a que se lea", bat, "pause")
sh = (destino / "runsync.sh").read_text(encoding="utf-8")
c.contains("el .sh usa el Python propio de Linux x64", sh, "linux-x64")
c.contains("y el de ARM64", sh, "linux-arm64")
c.contains("comprueba que se puede ejecutar (exFAT, noexec)", sh, "[ -x")
c.contains("y si no, el python3 del equipo", sh, "command -v python3")
c.contains("y sin ninguno también dice cómo se arregla", sh, "Añadir plataformas")
# Microsoft retira VBScript: nada de lanzadores .vbs, ni hoy ni escondidos.
todos = bat + sh + pyw
c("ningún lanzador depende de VBScript",
  any(x in todos.lower() for x in (".vbs", "wscript", "cscript")), False)

# La raíz de un dispositivo completo queda con lo justo: dos lanzadores y la guía.
limpia = tmpdir() / "raiz-limpia"
limpia.mkdir()
deploy.write_launchers(limpia, completa=True)
(origen / deploy.GUIDE_SOURCE).write_text("# guía\n", encoding="utf-8")
deploy.write_guide(limpia, origen=origen)
c("una completa deja en la raíz dos lanzadores y la guía",
  sorted(p.name for p in limpia.iterdir()), ["README.md", "runsync.bat", "runsync.sh"])

# La guía rápida ya no puede llegar por el espejo: o la escribe el instalador, o
# el usuario se queda sin nada que leer al abrir la unidad.
guia = deploy.write_guide(destino, origen=origen)
c("la guía se deja en la raíz con el nombre que se busca",
  guia, destino / deploy.GUIDE_TARGET)
# Es documentación, no maquinaria: que falte no puede tumbar una instalación.
c("y si el instalador no la lleva dentro, no pasa nada",
  deploy.write_guide(destino, origen=tmpdir()), None)

# --- los lanzadores no se tocan al actualizar ---------------------------------
# Se escriben al aprovisionar y ya está: el camino de actualizar —el aviso de la
# ventana, que ejecuta `prdrive-install.py --update` desde el zip descargado—
# cambia el programa, no la forma de arrancarlo.
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "prdrive_install", Path(__file__).resolve().parent.parent / "prdrive-install.py")
instalador = importlib.util.module_from_spec(spec)
spec.loader.exec_module(instalador)

inmutable = tmpdir() / "inmutable"
deploy.deploy_code(inmutable, origen=origen)
(inmutable / "runsync.bat").write_bytes(b"rem el mio\r\n")
(inmutable / "runsync.sh").write_text("# el mío\n", encoding="utf-8")
fuente_real = deploy.deploy_source
deploy.deploy_source = lambda: origen
try:
    instalador.cmd_update(str(inmutable))
finally:
    deploy.deploy_source = fuente_real
c("--update no reescribe el .bat",
  (inmutable / "runsync.bat").read_bytes(), b"rem el mio\r\n")
c("ni el .sh", (inmutable / "runsync.sh").read_text(encoding="utf-8"), "# el mío\n")
c("ni se inventa un .pyw", (inmutable / "runsync.pyw").exists(), False)

# --- rclone y Python por plataforma --------------------------------------------
from common import pins  # noqa: E402
from install import platforms, rclone_bin, runtime_bin  # noqa: E402

WIN, LIN = pins.plataforma("windows-x64"), pins.plataforma("linux-x64")
LARM = pins.plataforma("linux-arm64")


def archivo_runtime(plat, contenido=b"py") -> Path:
    """Un archivo de python-build-standalone de mentira para esa plataforma."""
    import io
    import tarfile
    ruta = tmpdir() / f"{plat.clave}.tar.gz"
    with tarfile.open(ruta, "w:gz") as tf:
        for rel in {plat.interprete, plat.interprete_consola, "lib-de-mentira.py"}:
            info = tarfile.TarInfo(f"python/{rel}")
            info.size = len(contenido)
            info.mode = 0o755
            tf.addfile(info, io.BytesIO(contenido))
    return ruta


archivos = {p.clave: archivo_runtime(p) for p in (WIN, LIN, LARM)}
descargados: list[str] = []
reales = (rclone_bin.rclone_for, runtime_bin.ensure_runtime)
rclone_bin.rclone_for = lambda plat, progreso=None, allow_download=True: (
    descargados.append("rclone " + plat.clave) or rclone_falso)
runtime_bin.ensure_runtime = lambda plat, progreso=None, allow_download=True: (
    descargados.append("python " + plat.clave) or archivos[plat.clave])
try:
    multi = tmpdir() / "multi"
    matriz = platforms.Matriz.para(multi, anfitrion=WIN)
    matriz.elegir("linux-x64")
    escritos, borrados = deploy.apply_platforms(multi, matriz.plan())
    c("se consigue rclone y Python de cada plataforma marcada",
      sorted(descargados), ["python linux-x64", "python windows-x64",
                            "rclone linux-x64", "rclone windows-x64"])
    c("rclone de Windows en bin/x64/rclone.exe",
      platforms.rclone_path(multi, WIN).is_file(), True)
    c("el de Linux al lado, sin pisarlo", platforms.rclone_path(multi, LIN).is_file(), True)
    c("el Python de cada una en runtime/<clave>/",
      sorted(platforms.provisioned(multi)), ["linux-x64", "windows-x64"])
    c("con su sello", platforms.runtime_stamp(multi, WIN),
      runtime_bin.stamp_text(WIN, runtime_bin.recorded_sha256(archivos["windows-x64"])
                             or runtime_bin.file_sha256(archivos["windows-x64"])))
    c("sin carpetas de trabajo olvidadas",
      sorted(p.name for p in (deploy.app_dir(multi) / "runtime").iterdir()),
      ["linux-x64", "windows-x64"])
    c("nada borrado en un dispositivo nuevo", borrados, [])

    # Otra vez lo mismo: el runtime con el mismo sello no se vuelve a extraer.
    marca = platforms.runtime_dir(multi, WIN) / "marca-de-antes"
    marca.write_text("x", encoding="utf-8")
    deploy.apply_platforms(multi, matriz.plan())
    c("un runtime que ya es ese mismo no se toca", marca.exists(), True)

    # Otro archivo (otra release): se sustituye entero, por intercambio.
    archivos["windows-x64"] = archivo_runtime(WIN, b"py nuevo")
    deploy.apply_platforms(multi, matriz.plan())
    c("uno distinto se sustituye entero", marca.exists(), False)
    c("con lo nuevo dentro",
      (platforms.runtime_dir(multi, WIN) / WIN.interprete).read_bytes(), b"py nuevo")
    c("y sin restos del intercambio",
      sorted(p.name for p in (deploy.app_dir(multi) / "runtime").iterdir()),
      ["linux-x64", "windows-x64"])

    # Ligera: rclone sí, Python no; y lo que ya había de Python no se borra solo.
    descargados.clear()
    ligera_m = platforms.Matriz.para(multi, anfitrion=WIN)
    ligera_m.completa = False
    deploy.apply_platforms(multi, ligera_m.plan())
    c("la ligera solo consigue rclone", sorted(descargados),
      ["rclone linux-x64", "rclone windows-x64"])
    c("y no borra el Python que ya estaba",
      sorted(platforms.provisioned(multi)), ["linux-x64", "windows-x64"])

    # Quitar Linux x64 y confirmar el borrado: se va su rclone y su Python, y
    # solo los suyos —el rclone.exe de Windows vive en la misma carpeta—.
    quitar = platforms.Matriz.para(multi, anfitrion=WIN)
    quitar.quitar("linux-x64")
    quitar.confirmar_borrado("linux-x64", True)
    _, borrados = deploy.apply_platforms(multi, quitar.plan())
    c("se borra lo de la plataforma quitada",
      platforms.provisioned(multi).get("linux-x64"), None)
    c("y solo lo suyo", platforms.rclone_path(multi, WIN).is_file(), True)
    c("se dice qué se ha borrado", len(borrados), 2)

    # Sin confirmar, quitar no borra.
    no_borra = platforms.Matriz.para(multi, anfitrion=WIN)
    no_borra.quitar("windows-x64")
    no_borra.confirmar_borrado("windows-x64", False)
    deploy.apply_platforms(multi, no_borra.plan())
    c("desmarcar sin confirmar no borra nada",
      sorted(platforms.provisioned(multi)), ["windows-x64"])
finally:
    rclone_bin.rclone_for, runtime_bin.ensure_runtime = reales

# --- un runtime en uso no se deja a medias ---------------------------------------
# En Windows, el runtime del que está corriendo prdrive no se puede renombrar. El
# intercambio falla ENTERO —el runtime viejo sigue ahí y funciona— en vez de
# dejar la carpeta medio borrada.
enuso = tmpdir() / "en-uso"
deploy.install_runtime(enuso, WIN, archivo_runtime(WIN, b"viejo"))
reemplazar = deploy.os.replace
llamadas = {"n": 0}


def replace_que_falla(a, b):
    llamadas["n"] += 1
    if llamadas["n"] == 1:
        raise PermissionError("en uso")
    return reemplazar(a, b)


deploy.os.replace = replace_que_falla
try:
    deploy.install_runtime(enuso, WIN, archivo_runtime(WIN, b"nuevo"))
    c("un runtime en uso no se sustituye en silencio", "siguió", "InstallError")
except InstallError as e:
    c("un runtime en uso no se sustituye en silencio", "InstallError", "InstallError")
    c.contains("y se dice qué hacer", str(e), "Cierra prdrive")
finally:
    deploy.os.replace = reemplazar
c("el runtime de antes sigue entero",
  (platforms.runtime_dir(enuso, WIN) / WIN.interprete).read_bytes(), b"viejo")
c("y no quedan restos", sorted(p.name for p in (deploy.app_dir(enuso) / "runtime").iterdir()),
  ["windows-x64"])

# --- el instalador usa el Python del dispositivo -----------------------------------
# Es lo que hace real «nada que instalar»: inicializar las parejas (paso 7) y
# registrar el vigilante ya no piden un Python en el equipo que instala.
propio = tmpdir() / "con-python"
anfitrion = platforms.host()
if anfitrion is not None:
    deploy.install_runtime(propio, anfitrion, archivo_runtime(anfitrion))
    (deploy.app_dir(propio) / "sync.py").write_text("#\n", encoding="utf-8")
    (deploy.app_dir(propio) / "penwatch.py").write_text("#\n", encoding="utf-8")
    consola = platforms.runtime_dir(propio, anfitrion) / anfitrion.interprete_consola
    c("inicializar usa el Python del dispositivo, el de consola",
      deploy.resync_command(propio, ["docs"])[0], str(consola))
    c("y registrar el vigilante, también",
      deploy.penwatch_install_command(propio)[0], str(consola))

# --- la conexión del dispositivo ----------------------------------------------
perfil = profile.from_form(
    "nas", {"type": "sftp", "host": "servidor.ejemplo", "user": "quien"})
perfil = profile.Profile(**{**perfil.__dict__, "private_key": b"CLAVE-PRIVADA",
                            "known_hosts": "servidor.ejemplo ssh-ed25519 AAAA\n",
                            "key_name": "id_ed25519"})

puestos = deploy.write_device_remote(destino, perfil)
conf = (app / "rclone.conf").read_text(encoding="utf-8")

c("se escribe el rclone.conf del dispositivo", (app / "rclone.conf").is_file(), True)
c("y la clave, dentro de la carpeta del código",
  (app / "keys" / "id_ed25519").read_bytes(), b"CLAVE-PRIVADA")
c("con sus known_hosts", (app / "keys" / "known_hosts").is_file(), True)
c("se dice qué se ha escrito", len(puestos), 3)

# Lo que hace portable al dispositivo: rclone resuelve estas rutas contra su cwd,
# que el proyecto fija siempre en model.APP_DIR. Absolutas solo valdrían en el
# equipo donde se instaló.
c.contains("key_file es RELATIVA", conf, "key_file = keys/id_ed25519")
c.contains("known_hosts_file también", conf, "known_hosts_file = keys/known_hosts")
c("no hay ninguna ruta absoluta del equipo que instala",
  str(destino) in conf, False)
c.contains("y lleva la cabecera del remote", conf, "[nas]")
c.contains("con sus opciones", conf, "host = servidor.ejemplo")

# Un backend sin fichero de clave —contraseña, token, agente— no escribe ninguna,
# y sobre todo no deja un key_file apuntando a algo que no existe.
otro = tmpdir() / "sin-clave"
otro.mkdir()
deploy.write_device_remote(otro, profile.from_form("web", {"type": "webdav",
                                                           "url": "https://x/y"}))
conf2 = (otro / deploy.APP_SUBDIR / "rclone.conf").read_text(encoding="utf-8")
c("sin clave privada no se escribe key_file", "key_file" in conf2, False)
c("ni carpeta de claves", (otro / deploy.APP_SUBDIR / "keys").exists(), False)

# --- un origen incompleto se dice, no se instala a medias ---------------------
roto = tmpdir() / "roto"
roto.mkdir()
try:
    deploy.deploy_code(tmpdir() / "x", rclone_falso, origen=roto)
    c("un instalador sin el árbol dentro se queja", "no lanzó", "InstallError")
except InstallError as e:
    c.contains("un instalador sin el árbol dentro se queja", str(e), "sync.py")

# --- carpetas locales ---------------------------------------------------------
c("las carpetas de las parejas elegidas",
  [str(p) for p in deploy.local_dirs(cat, ["docs", "upload"])],
  [str(Path("sync-data/docs")), str(Path("sync-data/upload"))])
c("la raíz del dispositivo ('.') no es una carpeta que crear",
  deploy.local_dirs(cat, ["respaldo"]), [])

dispositivo = tmpdir()
creadas = deploy.make_local_dirs(dispositivo, cat, ["docs", "respaldo"])
c("se crean de verdad", (dispositivo / "sync-data" / "docs").is_dir(), True)
c("y se dice cuáles", len(creadas), 1)
c("llamarlo dos veces no repite", deploy.make_local_dirs(dispositivo, cat, ["docs"]), [])

# --- qué se inicializa y qué no ----------------------------------------------
todas = ["respaldo", "docs", "upload"]
c("solo se inicializan las bisync", deploy.resync_targets(cat, todas), ["docs"])
c("los espejos se identifican para poder avisar",
  deploy.mirror_pairs(cat, todas), ["respaldo"])

try:
    deploy.resync_command(dispositivo, ["docs"])
    c("sin sync.py instalado no se puede inicializar", "no lanzó", "InstallError")
except InstallError as e:
    c.contains("sin sync.py instalado no se puede inicializar", str(e), "instalado")

app2 = deploy.app_dir(dispositivo)
app2.mkdir(parents=True, exist_ok=True)
(app2 / "sync.py").write_text("# de mentira\n", encoding="utf-8")
orden = deploy.resync_command(dispositivo, ["docs"])
c("apunta al sync.py del dispositivo", str(app2 / "sync.py") in orden, True)
c("y a la pareja pedida", "docs" in orden, True)
c("pide el resync", "--resync" in orden, True)
# Se lanza sin terminal: sin --yes, la pregunta tomaría el valor por defecto (no)
# y la pareja se saltaría en silencio, que es lo contrario de lo que se ha pedido.
c("y no se queda esperando una respuesta", "--yes" in orden, True)
c("lanzado con un Python de verdad, no con el instalador",
  Path(orden[0]).name.lower().startswith(("python", "py")), True)

try:
    deploy.resync_command(dispositivo, [])
    c("sin parejas no hay nada que inicializar", "no lanzó", "InstallError")
except InstallError:
    c("sin parejas no hay nada que inicializar", True, True)

# --- la trampa que solo aparece compilado ------------------------------------
# Congelado con PyInstaller, sys.executable es el propio instalador: usarlo
# relanzaría el asistente en vez de sincronizar. Se finge ese estado para poder
# comprobarlo sin compilar nada.
import shutil as _shutil  # noqa: E402

import install  # noqa: E402

c("sin congelar se usa el intérprete actual",
  install.python_command(), [sys.executable])

which_original, frozen_antes = _shutil.which, getattr(sys, "frozen", None)
install.shutil.which = lambda nombre: ("/usr/bin/" + nombre
                                       if nombre in ("python", "python3") else None)
sys.frozen = True
try:
    congelado = install.python_command()
    c("congelado NO se usa sys.executable", sys.executable in congelado, False)
    c("sino un Python de verdad que se busca aparte", congelado, ["/usr/bin/python"])

    install.shutil.which = lambda nombre: "/usr/bin/py" if nombre == "py" else None
    c("y si no hay ninguno, vale el lanzador 'py'",
      install.python_command(), ["/usr/bin/py", "-3"])

    install.shutil.which = lambda nombre: None
    c("sin ningún Python se dice que no hay", install.python_command(), None)
    try:
        deploy.resync_command(dispositivo, ["docs"])
        c("y no se intenta inicializar sin él", "no lanzó", "InstallError")
    except InstallError as e:
        c.contains("y no se intenta inicializar sin él", str(e), "Python 3.11+")
finally:
    install.shutil.which = which_original
    if frozen_antes is None:
        del sys.frozen
    else:
        sys.frozen = frozen_antes

# --- el guardián del destino --------------------------------------------------
from install import device  # noqa: E402

base = tmpdir()
c("una carpeta que no existe se puede usar",
  device.install_target(base / "nueva")[0], device.VACIO)
c("una carpeta vacía también", device.install_target(base)[0], device.VACIO)

(base / "System Volume Information").mkdir()
(base / "$RECYCLE.BIN").mkdir()
c("lo que deja el sistema no cuenta como contenido",
  device.install_target(base)[0], device.VACIO)

(base / "PRDRIVE.hc").write_bytes(b"x")
c("un contenedor VeraCrypt en la raíz tampoco",
  device.install_target(base)[0], device.VACIO)

# Lo que escribe el propio instalador tiene que estar en RUIDO: si no, el
# dispositivo que acaba de hacer se clasificaría como ajeno la siguiente vez y
# pediría la confirmación a ciegas.
(base / "runsync.pyw").write_text("#\n", encoding="utf-8")
(base / "runsync.bat").write_text("#\n", encoding="utf-8")
(base / "runsync.sh").write_text("#\n", encoding="utf-8")
(base / "runsync.ico").write_bytes(b"\0")
c("ni los lanzadores que ponemos nosotros",
  device.install_target(base)[0], device.VACIO)

(base / "TFM-sin-copia").mkdir()
situacion, motivo = device.install_target(base)
c("una carpeta con cosas ajenas se marca como ajena", situacion, device.AJENO)
c.contains("nombrando lo que hay", motivo, "TFM-sin-copia")
# El aviso dice lo que pasa de verdad. Cuando esto era un espejo amenazaba con
# BORRARÍA en mayúsculas, porque era cierto; ahora sería mentira y asustaría para
# nada.
c.contains("y tranquiliza en vez de amenazar", motivo, "No se borrará nada")

# El fichero de control vive DENTRO de `.prdrive/`, no en la raíz del volumen:
# para identificar la unidad da igual dónde esté mientras la ruta sea relativa a
# ella, y ahí no deja un fichero suelto entre los datos del usuario.
deploy.app_dir(base).mkdir(exist_ok=True)
(base / device.CONTROL_FILE).write_text("id=abc\n", encoding="utf-8")
(deploy.app_dir(base) / "runsync.py").write_text("#\n", encoding="utf-8")
c("el control va dentro de la carpeta del programa, no en la raíz",
  device.CONTROL_FILE.parent.name, deploy.APP_SUBDIR)
c("un dispositivo prdrive de verdad se reconoce",
  device.install_target(base)[0], device.YA_INSTALADO)
c("y la raíz no gana ningún fichero suelto",
  (base / "PRDRIVE").exists(), False)

# El caso que se escapaba. Un dispositivo RECIÉN provisionado no tiene todavía ni
# un fichero del usuario, y `.prdrive` está en RUIDO —tiene que estarlo, ver
# arriba—, así que no deja nada a la vista. Mientras el «¿está vacío?» iba antes
# que el «¿es un prdrive?», el dispositivo más nuevo que existe se leía como una
# carpeta vacía y el asistente no ofrecía el recorrido corto para actualizarlo.
recien = tmpdir()
deploy.app_dir(recien).mkdir(exist_ok=True)
(recien / device.CONTROL_FILE).write_text("id=abc\n", encoding="utf-8")
(deploy.app_dir(recien) / "runsync.py").write_text("#\n", encoding="utf-8")
c("un dispositivo recién hecho, aún sin datos, se reconoce igual",
  device.install_target(recien)[0], device.YA_INSTALADO)

# La frontera del otro lado: hacen falta LAS DOS cosas. Con el control pero sin
# el programa no hay instalación que actualizar, y leerlo como vacío es lo
# correcto —no hay nada del usuario que conservar y se puede instalar encima sin
# preguntar—, que es justo lo que dice `Volume.nota` de ese caso.
a_medias = tmpdir()
deploy.app_dir(a_medias).mkdir(exist_ok=True)
(a_medias / device.CONTROL_FILE).write_text("id=abc\n", encoding="utf-8")
c("con el control pero sin el programa no es un dispositivo",
  device.install_target(a_medias)[0], device.VACIO)

sys.exit(c.report())
