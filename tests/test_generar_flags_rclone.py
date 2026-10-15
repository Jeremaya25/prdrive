#!/usr/bin/env python3
"""El script que regenera `common/flags_rclone.json` desde la rclone fijada.

No ejecuta rclone: trabaja con trozos de la salida real de `rclone help flags` y
de `rclone <comando> --help` (v1.75.2), que es lo que de verdad parsea. Lo que
importa es que el fichero de datos salga igual cada vez, que cada flag diga a
qué comandos pertenece y que lo que rclone deja fuera de `sync`/`copy`/`bisync`
(el servidor, el backend) no entre.
"""

import sys

from _harness import Checks

import generar_flags_rclone as gen

c = Checks("regenerar los flags de rclone (generar_flags_rclone.py)")

AYUDA_FLAGS = """\
Usage:
  rclone help flags [<filter>] [flags]

Flags:
      --group string   Only include flags from specific group
  -h, --help           help for flags
      --name           Apply filter only on flag names

Flags for anything which can copy a file (flag group Copy):
  -c, --checksum                                    Check for changes with size & checksum (if available, or fallback to size only)
      --cutoff-mode HARD|SOFT|CAUTIOUS              Mode to stop transfers when reaching the max transfer limit HARD|SOFT|CAUTIOUS (default HARD)
      --multi-thread-cutoff SizeSuffix              Use multi-thread downloads for files above this size (default 256Mi)

Flags used for sync commands (flag group Sync):
      --delete-after                    When synchronizing, delete files on destination after transferring (default)
      --max-delete int                  When synchronizing, limit the number of deletes (default -1)
      --track-renames-strategy string   Strategies to use when synchronizing using track-renames hash|modtime|leaf (default "hash")

Important flags useful for most commands (flag group Important):
  -n, --dry-run         Do a trial run with no permanent changes
  -v, --verbose count   Print lots more stuff (repeat for more)

Flags helpful for increasing performance (flag group Performance):
      --transfers int   Number of file transfers to run in parallel (default 4)

Flags for general configuration of rclone (flag group Config):
      --cache-dir string   Directory rclone will use for caching (default "/home/ana/.cache/rclone")
      --config string      Config file (default "/home/ana/.config/rclone/rclone.conf")
      --temp-dir string    Directory rclone will use for temporary files (default "C:\\Users\\ana\\AppData\\Local\\Temp")

Flags for logging and statistics (flag group Logging):
      --stats Duration   Interval between printing stats, e.g. 500ms, 60s, 5m (0 to disable) (default 1m0s)

Flags to control the Remote Control API (flag group RC):
      --rc-addr stringArray   IPaddress:Port or :Port to bind server to (default localhost:5572)

Backend-only flags (these can be set in the config file also) (flag group Backend):
      --s3-region string   Region to connect to
"""

AYUDA_BISYNC = """\
Flags:
      --check-access                         Ensure expected RCLONE_TEST files are found on both Path1 and Path2 filesystems, else abort.
      --conflict-resolve string              Automatically resolve conflicts by preferring the version that is: none, path1, path2, newer, older, larger, smaller (default: none) (default "none")
      --create-empty-src-dirs                Sync creation and deletion of empty directories. (Not compatible with --remove-empty-dirs)
  -h, --help                                 help for bisync
      --max-lock Duration                    Consider lock files older than this to be expired (default: 0 (never expire)) (minimum: 2m) (default 0s)
  -1, --resync                               Performs the resync run. Equivalent to --resync-mode path1. Consider using --verbose or --dry-run first.
      --workdir string                       Use custom working dir - useful for testing. (default: /home/ana/.cache/rclone/bisync)

Flags for anything which can copy a file (flag group Copy):
  -c, --checksum                                    Check for changes with size & checksum (if available, or fallback to size only)
      --cutoff-mode HARD|SOFT|CAUTIOUS              Mode to stop transfers when reaching the max transfer limit HARD|SOFT|CAUTIOUS (default HARD)
      --multi-thread-cutoff SizeSuffix              Use multi-thread downloads for files above this size (default 256Mi)

Flags used for sync commands (flag group Sync):
      --delete-after                    When synchronizing, delete files on destination after transferring (default)
      --max-delete int                  When synchronizing, limit the number of deletes (default -1)
      --track-renames-strategy string   Strategies to use when synchronizing using track-renames hash|modtime|leaf (default "hash")

Important flags useful for most commands (flag group Important):
  -n, --dry-run         Do a trial run with no permanent changes
  -v, --verbose count   Print lots more stuff (repeat for more)

Use "rclone [command] --help" for more information about a command.
"""

AYUDA_COPY = """\
Flags:
      --combined string         Make a combined report of changes to this file
      --create-empty-src-dirs   Create empty source dirs on destination after sync
  -h, --help                    help for copy

Flags for anything which can copy a file (flag group Copy):
  -c, --checksum                                    Check for changes with size & checksum (if available, or fallback to size only)
      --cutoff-mode HARD|SOFT|CAUTIOUS              Mode to stop transfers when reaching the max transfer limit HARD|SOFT|CAUTIOUS (default HARD)
      --multi-thread-cutoff SizeSuffix              Use multi-thread downloads for files above this size (default 256Mi)

Important flags useful for most commands (flag group Important):
  -n, --dry-run         Do a trial run with no permanent changes
  -v, --verbose count   Print lots more stuff (repeat for more)
"""

AYUDA_SYNC = """\
Flags:
      --combined string         Make a combined report of changes to this file
      --create-empty-src-dirs   Create empty source dirs on destination after sync
  -h, --help                    help for sync

Flags for anything which can copy a file (flag group Copy):
  -c, --checksum                                    Check for changes with size & checksum (if available, or fallback to size only)
      --cutoff-mode HARD|SOFT|CAUTIOUS              Mode to stop transfers when reaching the max transfer limit HARD|SOFT|CAUTIOUS (default HARD)
      --multi-thread-cutoff SizeSuffix              Use multi-thread downloads for files above this size (default 256Mi)

Flags used for sync commands (flag group Sync):
      --delete-after                    When synchronizing, delete files on destination after transferring (default)
      --max-delete int                  When synchronizing, limit the number of deletes (default -1)
      --track-renames-strategy string   Strategies to use when synchronizing using track-renames hash|modtime|leaf (default "hash")

Important flags useful for most commands (flag group Important):
  -n, --dry-run         Do a trial run with no permanent changes
  -v, --verbose count   Print lots more stuff (repeat for more)
"""

# Un texto de ayuda a secas: las secciones y sus flags, tal como salen.
secciones = dict(gen.leer_secciones(AYUDA_FLAGS))
c("las secciones salen con su grupo; la de la propia orden es «local»",
  list(secciones), ["local", "Copy", "Sync", "Important", "Performance", "Config", "Logging",
                    "RC", "Backend"])
copia = {e.nombre: e for e in secciones["Copy"]}
c("un flag con su nombre corto", (copia["checksum"].corto, copia["checksum"].tipo),
  ("c", "bool"))
c("sin tipo en la línea es un booleano", copia["checksum"].tipo, "bool")
c("el tipo es lo que va tras el nombre", copia["multi-thread-cutoff"].tipo, "SizeSuffix")
c("y una lista de valores también", copia["cutoff-mode"].tipo, "HARD|SOFT|CAUTIOUS")
c("el valor de fábrica sale del final de la ayuda", copia["multi-thread-cutoff"].defecto,
  "256Mi")
c("  y la ayuda se queda sin él", copia["multi-thread-cutoff"].ayuda,
  "Use multi-thread downloads for files above this size")
c("  sin comillas si venían con ellas",
  {e.nombre: e.defecto for e in secciones["Sync"]}["track-renames-strategy"], "hash")
c("un flag sin valor de fábrica lo deja vacío", copia["checksum"].defecto, "")
c("`verbose` es un contador", {e.nombre: e.tipo for e in secciones["Important"]}["verbose"],
  "count")
c("un valor de fábrica negativo", {e.nombre: e.defecto for e in secciones["Sync"]}["max-delete"],
  "-1")
c("el paréntesis del medio no es el valor de fábrica",
  {e.nombre: e.defecto for e in dict(gen.leer_secciones(AYUDA_BISYNC))["local"]}
  ["conflict-resolve"], "none")
c("  y de la ayuda de bisync se queda con la del medio",
  {e.nombre: e.ayuda for e in dict(gen.leer_secciones(AYUDA_BISYNC))["local"]}["conflict-resolve"],
  "Automatically resolve conflicts by preferring the version that is: none, path1, path2, "
  "newer, older, larger, smaller (default: none)")

# El fichero entero.
datos = gen.construir("v1.75.2", AYUDA_FLAGS,
                      {"bisync": AYUDA_BISYNC, "sync": AYUDA_SYNC, "copy": AYUDA_COPY})
flags = datos["flags"]
c("lleva la versión de rclone de la que sale", datos["rclone"], "v1.75.2")
c("el backend y el servidor de control no entran",
  [n for n in flags if n.startswith(("s3-", "rc-"))], [])
c("ni el `--help` de cada orden", "help" in flags, False)
c("los nombres van ordenados", list(flags), sorted(flags))

c("un global vale para las tres órdenes", flags["transfers"]["comandos"],
  ["bisync", "copy", "sync"])
c("y no es propio de ninguna", flags["transfers"]["propio"], False)
# Que una ayuda no enseñe el grupo de un global no quiere decir que no valga:
# `copy` no enseña `Sync` y `bisync` no enseña `Listing`, y `--fast-list` va en las dos.
c("un global del grupo Sync, aunque `copy` no lo enseñe, vale para las tres",
  (flags["max-delete"]["comandos"], flags["max-delete"]["propio"]),
  (["bisync", "copy", "sync"], False))
c("  y sigue diciendo su grupo, que es lo que lo sitúa", flags["max-delete"]["grupo"], "Sync")
c("uno de los grupos de todas las órdenes", flags["checksum"]["comandos"],
  ["bisync", "copy", "sync"])
c("uno solo de bisync", (flags["resync"]["comandos"], flags["resync"]["propio"]),
  (["bisync"], True))
c("  con su nombre corto", flags["resync"]["corto"], "1")
c("y uno propio de las tres órdenes", (flags["create-empty-src-dirs"]["comandos"],
                                        flags["create-empty-src-dirs"]["propio"]),
  (["bisync", "copy", "sync"], True))
c("uno propio de sync y copy, no de bisync", flags["combined"]["comandos"], ["copy", "sync"])
c("el grupo de cada global", (flags["transfers"]["grupo"], flags["max-delete"]["grupo"]),
  ("Performance", "Sync"))
c("y los propios, «local»", flags["resync"]["grupo"], "local")
c("el tipo y el valor de fábrica llegan al fichero",
  (flags["max-lock"]["tipo"], flags["max-lock"]["defecto"]), ("Duration", "0s"))

# `Duration` esconde dos gramáticas: la de rclone (`30`, `1d`, `off`) y la de Go
# (`30s`, y nada más). Solo se distinguen preguntándole al binario.
datos_go = gen.construir("v1.75.2", AYUDA_FLAGS,
                         {"bisync": AYUDA_BISYNC, "sync": AYUDA_SYNC, "copy": AYUDA_COPY},
                         duraciones_go={"stats"})
c("una duración de Go lo dice", datos_go["flags"]["stats"].get("formato"), "go")
c("una de rclone no lleva marca", "formato" in datos["flags"]["max-lock"], False)
c("y lo que no es duración tampoco, aunque se le pida",
  "formato" in gen.construir("v1.75.2", AYUDA_FLAGS, {"copy": AYUDA_COPY},
                             duraciones_go={"transfers"})["flags"]["transfers"], False)

preguntado = []


def fake_acepta(flag, valor):
    """Un rclone de mentira: `stats` lleva Go (rechaza `1d`) y `max-lock` rclone."""
    preguntado.append((flag, valor))
    return flag != "stats"


c("el sondeo pregunta por cada duración con un valor que solo rclone entiende",
  gen.sondear_duraciones(datos, fake_acepta), {"stats"})
c("  y solo por las duraciones", sorted({f for f, _v in preguntado}), ["max-lock", "stats"])
c("  con `1d`", {v for _f, v in preguntado}, {"1d"})

# Lo que depende de quién corre rclone no entra: el fichero es el mismo en cualquier equipo.
c("una ruta de la máquina no es un valor de fábrica: se deja en blanco",
  [flags[n]["defecto"] for n in ("cache-dir", "config", "temp-dir")], ["", "", ""])
c("  ni sale de la ayuda de un flag de bisync", flags["workdir"]["ayuda"],
  "Use custom working dir - useful for testing.")
c("ni queda en el fichero ninguna ruta de ese equipo",
  [t for t in ("/home/ana", "C:\\Users", "ana") if t in gen.a_texto(datos)], [])

# El fichero de datos es texto estable: la misma entrada da los mismos bytes.
texto = gen.a_texto(datos)
c("el texto se vuelve a leer igual", gen.leer_texto(texto), datos)
c("y es el mismo cada vez", gen.a_texto(datos), texto)
c("acaba en salto de línea", texto.endswith("}\n"), True)
c("un flag por línea, para que un cambio de rclone se vea en el diff",
  sum(1 for l in texto.splitlines() if l.startswith('    "transfers"')), 1)

# El fichero que hay en el repositorio es el que escribiría el script: nadie lo ha tocado a mano.
fichero = gen.SALIDA.read_text(encoding="utf-8")
c("el fichero del repositorio es el que escribe a_texto()",
  gen.a_texto(gen.leer_texto(fichero)) == fichero, True)
c("  y lleva una sola versión de rclone", gen.leer_texto(fichero)["rclone"].startswith("v"), True)
c("  las duraciones de Go son las que sondeó rclone (nueve en la v1.75.2)",
  sorted(n for n, f in gen.leer_texto(fichero)["flags"].items() if f.get("formato") == "go"),
  ["contimeout", "expect-continue-timeout", "fs-cache-expire-duration",
   "fs-cache-expire-interval", "kv-lock-time", "max-duration", "modify-window",
   "retries-sleep", "timeout"])

c("el fichero del repositorio no lleva rutas de quien lo generó",
  [t for t in ("/root/", "/home/", "/Users/", "C:\\", "/tmp/") if t in fichero], [])
c("  ni un valor de fábrica que sea una ruta absoluta",
  [n for n, f in gen.leer_texto(fichero)["flags"].items()
   if f["defecto"].startswith("/") or f["defecto"][1:3] in (":\\", ":/")], [])

# Si rclone cambia de formato, mejor que el script se queje a que escriba datos a medias.
try:
    gen.construir("v1", "Usage:\n  rclone help flags\n", {})
    dicho = ""
except gen.ErrorDeAyuda as e:
    dicho = str(e)
c("una ayuda sin flags no vale", "ningún flag" in dicho, True)

try:
    gen.comprobar_version("rclone v1.70.0\n- os/version: x", "v1.75.2")
    dicho = ""
except gen.ErrorDeAyuda as e:
    dicho = str(e)
c("un rclone que no es el fijado se rechaza, y dice cuál es",
  ("v1.70.0" in dicho, "v1.75.2" in dicho), (True, True))
c("el fijado se acepta", gen.comprobar_version("rclone v1.75.2\n- os/version: x", "v1.75.2"),
  None)

sys.exit(c.report())
