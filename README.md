# rclone-sync

Sincronización **portable** entre un NAS Synology y un pen USB mediante
[rclone](https://rclone.org/). Todo vive en el pen y no depende de nada
instalado en la máquina salvo **Python 3.11+** (para `tomllib`). El binario de
rclone es portable (carpeta `bin/`).

La idea: enchufas el pen en cualquier PC/Mac/Linux, ejecutas `python sync.py` y
tus carpetas quedan sincronizadas con el NAS. El estado viaja con el pen, así
que la sincronización es coherente entre máquinas distintas.

---

## Estructura en el pen

```
PEN/
├── rclone-sync/
│   ├── sync.py            <- el script
│   ├── sync_config.toml   <- QUÉ sincronizar y CÓMO (parejas + flags)
│   ├── rclone.conf        <- config de rclone (remote SFTP + ruta a la clave)
│   ├── README.md          <- este fichero
│   ├── bin/<arch>/
│   │   ├── rclone.exe     <- binario portable Windows
│   │   └── rclone         <- binario portable Linux
│   ├── keys/              <- clave privada SSH (el pen va cifrado con BitLocker)
│   ├── state/             <- workdir de bisync (el estado viaja con el pen)
│   └── logs/              <- un log por ejecución y pareja
└── data/ (o sync-data/)   <- aquí viven las carpetas locales que se sincronizan
```

- Las rutas son **relativas a la ubicación del script**, así que da igual la
  letra de unidad que Windows asigne al pen.
- `bin/<arch>` se elige solo según la CPU: `arm` (ARM64/Apple Silicon/Raspberry)
  o `x64` (Intel/AMD).
- En Linux/mac, si el sistema de ficheros del pen (exFAT/NTFS) no conserva el bit
  de ejecución, el script copia rclone a un temporal con `+x` automáticamente.

---

## Uso

```bash
python sync.py                 # ejecuta TODAS las parejas del config
python sync.py obsidian fotos  # solo esas parejas
python sync.py --list          # lista las parejas configuradas y sale
python sync.py --dry-run       # simula, no toca nada (úsalo SIEMPRE la 1a vez)
python sync.py --resync        # rehace el baseline de bisync (1a vez o si se rompe)
python sync.py --yes           # responde 'sí' a todo (automatiza el resync); -y
```

> **La primera vez con una pareja `bisync`** hace falta un `--resync` para crear
> el baseline. Si a alguna pareja seleccionada le falta, el script **para al
> arrancar, lista las afectadas y pregunta UNA sola vez** (`¿Ejecutar --resync en
> TODAS ahora?`): respondes `s` (sí a todo) o `n` (por defecto, se saltan).
>
> - **`--yes` / `-y`** → responde 'sí' automáticamente, sin preguntar (para cron/scripts).
> - **No interactivo** sin `--yes` (stdin redirigido, cron) → no pregunta y salta
>   esas parejas de forma segura.
> - **`--resync`** en la línea de comandos → fuerza el resync de todas las parejas
>   bisync seleccionadas (tengan baseline o no), sin preguntar.

> **La primera vez en general**, prueba con `--dry-run` para ver qué haría sin
> tocar nada. Imprescindible antes de usar los modos `*-mirror` (borran).

---

## Configuración: `sync_config.toml`

Dos partes: `[defaults]` (valores comunes) y una `[[pair]]` por cada pareja de
carpetas a sincronizar.

### Parejas — `[[pair]]`

| Clave         | Qué es                                                              |
|---------------|--------------------------------------------------------------------|
| `name`        | Nombre de la pareja (lo usas en la línea de comandos y en el log).  |
| `local`       | Ruta relativa a la **raíz del pen** (la carpeta que contiene `rclone-sync/`). |
| `remote_path` | Ruta dentro del NAS, sobre el remote de `rclone.conf`.             |
| `mode`        | Dirección/tipo de sincronización (ver tabla de modos).            |
| `remote`      | (opcional) Nombre del remote; por defecto el de `[defaults]`.      |
| `include`     | (opcional) Lista de patrones a incluir.                            |
| `exclude`     | (opcional) Lista de patrones a excluir.                           |
| `[pair.flags]`| (opcional) Flags de rclone específicos de esta pareja.            |

### Modos disponibles

| Modo          | Subcomando | Dirección   | ¿Borra en destino?                          |
|---------------|-----------|-------------|---------------------------------------------|
| `bisync`      | `bisync`  | pen ⇄ NAS   | Bidireccional. Conflictos según `conflict-resolve`. |
| `up`          | `copy`    | pen → NAS   | **No** (aditivo). Seguro.                    |
| `down`        | `copy`    | NAS → pen   | **No** (aditivo). Seguro.                    |
| `up-mirror`   | `sync`    | pen → NAS   | **Sí**: borra en el NAS lo que no esté en el pen. |
| `down-mirror` | `sync`    | NAS → pen   | **Sí**: borra en el pen lo que no esté en el NAS. |

⚠️ Los modos `*-mirror` **borran en destino**. Prueba siempre con `--dry-run`.

---

## Flags de rclone (lo importante)

Los parámetros de rclone se declaran como `nombre = valor` en el TOML y el script
los traduce solo. **Para añadir un flag nuevo basta con escribir una línea; no se
toca `sync.py` nunca.**

### Cómo se escriben

| En el TOML                | Genera en rclone            |
|---------------------------|-----------------------------|
| `clave = true`            | `--clave` (booleano)        |
| `clave = false`           | *(se omite)*                |
| `clave = 4`               | `--clave 4`                 |
| `clave = "texto"`         | `--clave texto`             |
| `clave = ["a", "b"]`      | `--clave a --clave b` (repetido) |

Los guiones bajos valen por guiones: `drive_chunk_size` == `drive-chunk-size`.
No se escriben los `--`.

### Dónde se ponen y prioridad

Los flags se fusionan en **capas** (gana el de más abajo):

```
BASE_FLAGS (script)  <  MODE_DEFAULT_FLAGS[modo]  <  [defaults.flags]  <  [pair.flags]
```

1. **`BASE_FLAGS`** — los que el script activa siempre: `verbose`,
   `create-empty-src-dirs`. Se pueden desactivar con `= false`.
2. **`MODE_DEFAULT_FLAGS`** — propios de cada modo (definidos en `sync.py`):
   - `bisync` → `conflict-resolve = "newer"`, `max-delete = 25`
   - `up-mirror` / `down-mirror` → `max-delete = 50`
3. **`[defaults.flags]`** — comunes a **todas** las parejas (ej. `transfers`, `checkers`).
4. **`[pair.flags]`** — específicos de una pareja.

> Algunos flags solo son válidos para su subcomando (p.ej. `--conflict-resolve`
> solo existe en `bisync`, y rompería un `copy`). Por eso van en el `[pair.flags]`
> de la pareja correspondiente, **no** en `[defaults.flags]`.

### Flags gestionados por el script

Estos los pone el script solo, dependen de la ejecución y **no** se configuran:
`--config`, `--log-file`, `--dry-run`, y para bisync `--workdir` y `--resync`.

### Escape hatch — `extra_flags`

Para flags raros que no encajen en el esquema `nombre = valor`, hay una lista de
strings crudos que se añaden tal cual, disponible en `[defaults]` y por pareja:

```toml
extra_flags = ["--algún-flag-raro", "valor"]
```

### Ejemplo

```toml
[defaults]
remote = "synology"
exclude = ["**/.stfolder/**", "**/.stversions/**", "**/.stignore"]

[defaults.flags]           # comunes a todas las parejas
transfers = 4
checkers = 8

[[pair]]
name = "obsidian"
local = "sync-data/obsidian"
remote_path = "/PJ/Obsidian"
mode = "bisync"

[pair.flags]               # solo para esta pareja
conflict-resolve = "path2" # newer | path1 (local) | path2 (remoto) | larger | smaller
check-access = true
resilient = true
```

---

## Cómo funciona por dentro (`sync.py`)

- **`MODES`** — tabla `modo → (subcomando, extremo origen, extremo destino)`.
- **`BASE_FLAGS` / `MODE_DEFAULT_FLAGS`** — flags por defecto (ver arriba).
- **`flags_to_args(dict)`** — traduce `{nombre: valor}` a argumentos de rclone.
- **`build_filters(defaults, pair)`** — genera los `--include`/`--exclude`; los
  includes van **antes** que los excludes (rclone gana con la 1a coincidencia).
- **`build_command(...)`** — arma `[binario, subcomando, origen, destino]` +
  filtros + flags fusionados + `extra_flags`. No hay que tocarla para añadir flags.
- **`run_pair(...)`** — imprime el comando, lo ejecuta, y en bisync marca el
  baseline (`state/.init_<name>`) si fue OK y no era `--dry-run`.

---

## Logs y estado

- Cada ejecución escribe un log en `logs/<name>_<fecha>_<hora>.log`.
- `state/` es el workdir de bisync: guarda el baseline de cada pareja
  (`.init_<name>` marca que ya está inicializada). **No lo borres** salvo que
  quieras forzar un `--resync`.

---

## Requisitos

- **Python 3.11+** (para `tomllib`; en versiones más viejas, `pip install tomli`).
- Binario portable de rclone en `bin/<arch>/`. Descárgalo de
  <https://rclone.org/downloads/> para tu plataforma.
- `rclone.conf` con el remote SFTP del Synology y la ruta a la clave privada
  (que vive en `keys/`). El pen va cifrado con BitLocker.
