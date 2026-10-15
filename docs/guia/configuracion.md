[← Guías](README.md)

# Configuración

El fichero de configuración de la unidad, los flags de rclone, `device_remote`, los modos y los filtros.

`sync_config.toml` (dentro de `.prdrive/`) es el config de **ese** dispositivo. Se
edita desde la ventana de parejas o a mano; el mismo esquema sirve para el
`remote.toml` del catálogo (`pairs.toml` en un remoto de antes).

```toml
[defaults]
remote = "nas"                       # el remote de rclone que usan las parejas
device_remote = "disp"               # el lado local, como remote propio
catalog_path = "/prdrive-catalog/remote.toml" # el fichero, no su carpeta
exclude = ["**/.stfolder/**", "**/.stignore"]

[defaults.flags]                     # flags de rclone para todas las parejas
checkers = 8
transfers = 4

[[pair]]
name = "docs"
local = "sync-data/docs"             # relativa a la raíz del dispositivo
remote_path = "/datos/docs"          # ruta dentro del remote
mode = "bisync"

[pair.flags]                         # solo para esta pareja
conflict-resolve = "newer"
```

## Flags: se editan en el TOML, nunca en el código

Las claves de `flags` se traducen a argumentos de rclone tal cual:

| en el TOML | a rclone |
|---|---|
| `checkers = 8` | `--checkers 8` |
| `resilient = true` | `--resilient` |
| `resilient = false` | *(se omite)* |
| `exclude_from = ["a", "b"]` | `--exclude-from a --exclude-from b` |

El `_` se convierte en `-`. **Añadir un flag de rclone es editar el TOML.** Se
funden en cuatro capas y gana la última:

```
BASE_FLAGS  <  flags del modo  <  [defaults.flags]  <  [pair.flags]
```

El script se reserva `--config`, `--log-file`, `--dry-run`, `--workdir` y
`--resync`, porque dependen de *esta* ejecución. Para lo que no quepa en el
esquema está `extra_flags`, una lista de cadenas que se pasan crudas.

### Lo que el config no admite

El config viaja con el dispositivo y se puede editar a mano. Para que un config
ajeno no pueda hacer que rclone ejecute una orden en el equipo donde enchufes la
unidad, ni que sincronice carpetas de fuera de ella, el programa se niega a
leerlo si trae:

- **Un flag que lanza un programa**: los que acaban en `-command` o en `-ssh`
  (`password-command`, `sftp-ssh`…), `metadata-mapper`, `rc` y los `rc-…`. Vale
  igual en `[defaults.flags]`, en `[pair.flags]` y en `extra_flags`, y también
  si va escondido en el valor de otro (`checksum = "--sftp-ssh=…"`).
- **Un flag que escribe un fichero cualquiera del equipo**: `cpuprofile` y
  `memprofile` guardarían (o vaciarían) la ruta que les pongas.
- **Un flag que ya pone el script**, también en `extra_flags`: `resync = true`
  forzaría un `--resync` en cada pasada, y un `--config` o un `--workdir` propios
  pisarían los del dispositivo.
- **Un `remote` que no sea un nombre**: el de un remote de tu `rclone.conf`, con
  letras, números, espacios entre palabras y `. _ + @ -`. Si lleva `,`, `:`, `=`
  o comillas, rclone lo leería como una conexión con sus propias opciones
  (`nas,ssh='…'`), y si empieza por `-`, como una opción. Tampoco vale una sola
  letra (`C`): en Windows rclone la leería como la unidad `C:`; ponle al remote
  un nombre de dos caracteres o más. Vale para el `remote` de una pareja y para
  el `remote` y el `catalog_remote` de `[defaults]`.
- **Un `include` o un `exclude` con un salto de línea**: en el fichero de filtros
  cada línea es una regla, y una `!` suelta borraría las de antes.
- **Un `local` que no es una carpeta de dentro del dispositivo**: con un `..` o
  una letra de unidad (`C:/…`) sincronizaría (y en un espejo, borraría) carpetas
  de tu ordenador; y la del programa (`.prdrive`, que lleva la clave) y la del
  llavero (`.keychain`, que tiene su propia pareja) tampoco valen, ni con
  puntos o espacios al final (`.prdrive.`), ni un tramo de solo puntos o espacios
  (`...`), ni un `:` en el nombre (`docs:flujo`). Una barra al principio
  (`/sync-data/docs`) se sigue admitiendo.

El aviso dice de qué pareja es (o de `[defaults]`) y qué clave sobra; hasta que
la quites a mano, la ventana no abre. El agente del equipo hace la misma
comprobación antes de atender una unidad, aunque su código sea más antiguo, y si
no pasa no la atiende y dice por qué. Lo que sí sigue valiendo es ponerlo en el
`rclone.conf`: allí es una opción del remote, no del config que viaja.

Es un límite, no una garantía de que no haya otra forma: no se miran las opciones
de un backend que redirigen la conexión (`--sftp-host`, `--…-url`,
`--…-endpoint`), ni `--temp-dir` o `--cache-dir`, ni los ficheros de filtros
(`--include-from`, `--exclude-from`, `--files-from`). Revisa el config de una
unidad que no sea tuya antes de enchufarla.

La capa base lleva `--verbose`, `--create-empty-src-dirs` y las estadísticas del
**progreso en vivo**: `--stats 2s --stats-one-line`. Con ellas rclone escribe en
su log, cada dos segundos, cuánto lleva; `sync.py` lo va leyendo mientras corre
la pareja y lo cuenta en una línea (`progreso: 2,1 MB de 3,4 MB · 61 % ·
1,1 MB/s`), que la ventana de salida reescribe en su sitio. Es solo
informativo: si no sale nada del log —porque una pareja cambia esos flags, por
ejemplo con `stats = "0"`—, no hay progreso y la pasada va igual.

El editor de flags de la ventana enseña **las cuatro capas resueltas**: cada
flag con su valor y la etiqueta de dónde viene (`siempre`, `modo bisync`,
`[defaults]` o `esta pareja`), y avisa cuando un cambio sube el `--max-delete`
efectivo aunque no hayas tocado ese flag. Eligiendo una fila:

- **Sobrescribir** copia al cuadro de la izquierda un flag heredado, con el valor
  que ya tenía, para que lo cambies solo en esta pareja.
- **Volver a heredar** quita del cuadro un flag de la pareja: pasa a valer lo que
  diga la capa de debajo (la fila dice cuál, o que rclone dejará de recibirlo).

Nada se guarda hasta «Guardar», que enseña antes lo que va a pasar. Debajo, **la
orden de rclone** que saldría de una pasada normal con esos flags, sin
ejecutarla: es la misma que monta `sync.py`, y lo que pone prdrive en cada pasada
(`--config`, `--log-file`, `--workdir`…) sale sombreado, porque no se puede
cambiar desde aquí.

**Al escribir un flag, el editor ayuda sin conexión.** Con lo que escribes en el
cuadro de la izquierda sale, bajo el cursor, la lista de flags de rclone que
empiezan (o contienen) lo escrito, con su tipo («sí o no», «duración», «tamaño»…)
y, en la pista de debajo, para qué sirve el marcado (el texto es el de rclone, en
inglés). La lista es la de la versión de rclone que lleva prdrive: no hace falta
red. **Tab** acepta el primero, **↑/↓** recorren la lista y **Intro** acepta el que
hayas marcado (si no has marcado ninguno, Intro es un salto de línea), **Esc**
la cierra y un clic en una fila la acepta. Los flags que prdrive pone por su
cuenta o que no se pueden poner aquí no se ofrecen.

- **Un flag que no sale en la lista se puede escribir igual.** La lista ayuda, no
  limita: rclone tiene la última palabra, y los flags nuevos se añaden
  escribiéndolos.
- **El tipo del valor se comprueba al guardar**, y solo cuando rclone seguro lo
  rechazaría: un número donde va una duración con unidad (`timeout = 30` pide
  `"30s"`), un tamaño que no lo es, `checksum = "true"` con comillas (rclone lo
  leería como un argumento suelto de la orden y la pasada fallaría). Con un valor
  así, la ventana no se cierra y dice qué se esperaba, con un ejemplo. `false` vale
  siempre: es quitar el flag. De un flag que la lista no conoce, o de un valor
  cuyo tipo no se comprueba (un horario de `bwlimit`), no se dice nada.
- **Los avisos no impiden guardar.** Aparecen en un recuadro ámbar bajo el cuadro y
  la línea del flag se sombrea. Son de tres clases: *otro modo* (un flag que solo
  es de bisync en una pareja que no lo es: rclone no lo conoce y la pasada
  fallaría; o uno de sincronizar en un modo que solo copia: no hace nada), *choque*
  (dos flags que no pueden ir juntos o se pisan, como dos de `--delete-*`, o
  `--remove-empty-dirs` con el `--create-empty-src-dirs` que ya pone prdrive) y
  *borrado* (borra o reescribe ficheros: pruébalo antes con «Simular», que es
  `--dry-run`, sobre todo en una pareja `*-mirror`).

## `device_remote`

`device_remote = "disp"` en `[defaults]` hace que el lado local sea un remote
`combine` propio, definido en variables de entorno. Con eso el nombre de los
listados de bisync deja de depender de la letra de unidad, y el dispositivo es
igual de portable en `F:` que en `/media/quien/PRDRIVE`.

**El instalador lo escribe en todos los dispositivos nuevos**, así que no hay
nada que activar. Va en los `[defaults]` del dispositivo y no en los del
catálogo a propósito: cambiarlo en el catálogo movería el nombre de los listados
de todos los dispositivos ya instalados, y cada uno tendría que rehacer su
referencia con un `--resync`. Eso es justo lo que hay que hacer si vienes de una
versión anterior: ponerlo a mano y resincronizar.

Un remote `alias` **no** sirve: devuelve el Fs de destino tal cual y la ruta
absoluta reaparece.

## Modos

| modo | subcomando | dirección | borra en | freno |
|---|---|---|---|---|
| `bisync` | `bisync` | ↔ | — | `--max-delete 25` |
| `up` | `copy` | dispositivo → remoto | nada | — |
| `down` | `copy` | remoto → dispositivo | nada | — |
| `up-mirror` | `sync` | dispositivo → remoto | **el remoto** | `--max-delete 50` |
| `down-mirror` | `sync` | remoto → dispositivo | **el dispositivo** | `--max-delete 50` |

`bisync` viene además con `--conflict-resolve newer`, `--resilient`, `--recover` y
`--max-lock 2m`: un error menor no obliga a rehacer la referencia, una
interrupción brusca se recupera sola en la pasada siguiente, y el `.lck` que deja
un proceso muerto caduca en vez de bloquear para siempre. Y con
`--conflict-suffix conflicto-dispositivo,conflicto-remoto`, para que el nombre de
la copia que pierde un conflicto diga de qué lado venía (ver
[Conflictos](conflictos-y-versiones.md#conflictos)).

Un `mode` mal escrito se rechaza **al leer el config**, no cuando esa pareja
corre: un error tipográfico para `--list`, `--doctor` y la ejecución por igual, en
vez de solo la pareja afectada.

## Filtros

`include` / `exclude` aceptan patrones de rclone y se ponen en `[defaults]` (valen
para todas) o en una pareja (se suman a los anteriores).

Para `bisync` se genera `filters/<pareja>.txt` y se pasa con `--filters-file`, y
entonces **no** se emiten además `--include`/`--exclude`: duplicar reglas rompe la
detección de cambios. rclone guarda el md5 de ese fichero junto a la referencia y
solo lo reescribe al hacer `--resync`, así que **cambiar los patrones de una
pareja bisync exige un `--resync`**. El programa compara el hash él mismo y lo
dice, en vez de dejar que rclone aborte con un mensaje suyo.

Una pareja que sincroniza la **raíz entera** de la unidad (`local = "."`) lleva
además, delante de las tuyas, una regla que deja fuera la carpeta del programa
(`.prdrive/`, con tu clave y el `rclone.conf`). Está en el programa y no se puede
quitar desde el config. En `copy` y `sync` es un `exclude`, y rclone aplica todos
los `include` antes que los `exclude`: un `include` tuyo que case con esa carpeta
la dejaría pasar. Al actualizar, una pareja `bisync` de la raíz que ya
existía pide **un `--resync`** desde la ventana (su fichero de filtros ha
cambiado), y hasta entonces el servicio y el agente la saltan; las parejas de la
raíz que no son `bisync` no necesitan nada. Si esa pareja llegó a subir
`.prdrive/` al remoto, el programa **no la borra**: al pedir el resync (en la
ventana, en «Reparación» o en la consola) te avisa de dónde está, y la borras tú.
