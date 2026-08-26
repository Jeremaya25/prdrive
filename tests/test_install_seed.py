#!/usr/bin/env python3
"""
La siembra: cómo se construye su orden y a dónde se deja apuntar.

La siembra es la parte destructiva del instalador —un `rclone sync` es un espejo
que BORRA en destino—, así que aquí se prueban dos cosas distintas:

  * que la orden lleva lo que tiene que llevar (sentido, filtros, freno de
    borrado, y el .git fuera),
  * y que `seed_target()` no da por bueno un destino que no es un pen.

Ningún test lanza rclone: se comprueba la lista de argumentos, no la ejecución.
"""

import sys
from pathlib import Path

from _harness import Checks, tmpdir

from install import InstallError, remote, seed

c = Checks("instalador: la siembra")

CATALOGO = """\
[defaults]
remote = "synology"
exclude = ["**/.stignore"]

[defaults.flags]
transfers = 4
max-delete = 10

[[pair]]
name = "perepen"
local = "."
remote_path = "/PJ/Perepen"
mode = "up-mirror"
exclude = ["sync-data/**", "rclone-sync/state/**"]

[pair.flags]
transfers = 2

[[pair]]
name = "obsidian"
local = "sync-data/obsidian"
remote_path = "/PJ/Obsidian"
mode = "bisync"

[[pair]]
name = "upload"
local = "sync-data/upload"
remote_path = "/PJ/Share/Pupurri"
mode = "up"
"""

cat = remote.parse_catalog(CATALOGO)
rclone = remote.Rclone("RCLONE", "CONF")


def valor_de(cmd, flag):
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


# --- la orden -----------------------------------------------------------------
cmd = seed.seed_command(rclone, cat, Path("/destino"))

c("usa el config efímero", cmd[:3], ["RCLONE", "--config", "CONF"])
c("es un espejo", cmd[3], "sync")
c("del NAS al pen, no al revés", cmd[4], "synology:/PJ/Perepen")
c("y el destino es el pen", cmd[5], str(Path("/destino")))

c("arrastra los excludes de [defaults]", "**/.stignore" in cmd, True)
c("y los de la pareja maestra", "sync-data/**" in cmd, True)
c("el estado de bisync no se siembra", "rclone-sync/state/**" in cmd, True)

# El catálogo no excluye .git porque allí la pareja va pen -> NAS, donde sí
# interesa respaldarlo. Sembrarlo serían cientos de megas de historial.
c("el .git no se siembra", "**/.git/**" in cmd and ".git/**" in cmd, True)

# Precedencia de flags: base < modo < [defaults.flags] < [pair.flags].
c("gana el flag de la pareja sobre el de defaults", valor_de(cmd, "--transfers"), "2")
c("gana el max-delete de defaults sobre el del modo",
  valor_de(cmd, "--max-delete"), "10")
c("y siempre van los flags base", "--create-empty-src-dirs" in cmd, True)

c("sin --dry-run si no se pide", "--dry-run" in cmd, False)
c("con --dry-run si se pide",
  "--dry-run" in seed.seed_command(rclone, cat, Path("/destino"), dry_run=True), True)

# El max-delete del modo down-mirror es el que actúa si nadie lo pisa.
solo = remote.parse_catalog(CATALOGO.replace("max-delete = 10\n", ""))
c("y si nadie lo pisa, el del modo down-mirror",
  valor_de(seed.seed_command(rclone, solo, Path("/d")), "--max-delete"), "50")

# --- un catálogo sin la pareja maestra no se puede sembrar --------------------
sin_maestra = remote.parse_catalog(
    '[[pair]]\nname="x"\nlocal="a"\nremote_path="/b"\nmode="up"\n')
try:
    seed.seed_command(rclone, sin_maestra, Path("/d"))
    c("sin la pareja 'perepen' no se siembra", "no lanzó", "InstallError")
except InstallError as e:
    c("sin la pareja 'perepen' no se siembra", "perepen" in str(e), True)

# --- carpetas locales ---------------------------------------------------------
c("las carpetas de las parejas elegidas",
  [str(p) for p in seed.local_dirs(cat, ["obsidian", "upload"])],
  [str(Path("sync-data/obsidian")), str(Path("sync-data/upload"))])
c("la raíz del pen ('.') no es una carpeta que crear",
  seed.local_dirs(cat, ["perepen"]), [])

pen = tmpdir()
creadas = seed.make_local_dirs(pen, cat, ["obsidian", "perepen"])
c("se crean de verdad", (pen / "sync-data" / "obsidian").is_dir(), True)
c("y se dice cuáles", len(creadas), 1)
c("llamarlo dos veces no repite", seed.make_local_dirs(pen, cat, ["obsidian"]), [])

# --- qué se inicializa y qué no ----------------------------------------------
todas = ["perepen", "obsidian", "upload"]
c("solo se inicializan las bisync", seed.resync_targets(cat, todas), ["obsidian"])
c("los espejos se identifican para poder avisar",
  seed.mirror_pairs(cat, todas), ["perepen"])

try:
    seed.resync_command(pen, ["obsidian"])
    c("sin sync.py sembrado no se puede inicializar", "no lanzó", "InstallError")
except InstallError as e:
    c("sin sync.py sembrado no se puede inicializar", "sembrado" in str(e), True)

app = pen / "rclone-sync"
app.mkdir(parents=True, exist_ok=True)
(app / "sync.py").write_text("# de mentira\n", encoding="utf-8")
orden = seed.resync_command(pen, ["obsidian"])
c("apunta al sync.py del pen", str(app / "sync.py") in orden, True)
c("y a la pareja pedida", "obsidian" in orden, True)
c("pide el resync", "--resync" in orden, True)
# Se lanza sin terminal: sin --yes, la pregunta tomaría el valor por defecto (no)
# y la pareja se saltaría en silencio, que es lo contrario de lo que se ha pedido.
c("y no se queda esperando una respuesta", "--yes" in orden, True)
c("lanzado con un Python de verdad, no con el instalador",
  Path(orden[0]).name.lower().startswith(("python", "py")), True)

try:
    seed.resync_command(pen, [])
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
        seed.resync_command(pen, ["obsidian"])
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
c("una carpeta que no existe se puede sembrar",
  device.seed_target(base / "nueva")[0], device.VACIO)
c("una carpeta vacía también", device.seed_target(base)[0], device.VACIO)

(base / "System Volume Information").mkdir()
(base / "$RECYCLE.BIN").mkdir()
c("lo que deja el sistema no cuenta como contenido",
  device.seed_target(base)[0], device.VACIO)

(base / "PEREPEN.hc").write_bytes(b"x")
c("un contenedor VeraCrypt en la raíz tampoco",
  device.seed_target(base)[0], device.VACIO)

(base / "TFM-sin-copia").mkdir()
situacion, motivo = device.seed_target(base)
c("una carpeta con cosas ajenas NO se siembra sin más", situacion, device.AJENO)
c.contains("y se dice que se borrarían", motivo, "BORRARÍA")
c.contains("nombrando lo que hay", motivo, "TFM-sin-copia")

(base / "PEREPEN").write_text("id=abc\n", encoding="utf-8")
(base / "rclone-sync").mkdir()
(base / "rclone-sync" / "runsync.py").write_text("#\n", encoding="utf-8")
c("un pen PEREPEN de verdad sí", device.seed_target(base)[0], device.PEREPEN_YA)

sys.exit(c.report())
