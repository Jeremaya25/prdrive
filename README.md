# prdrive

Sincronización portable entre **cualquier remoto de rclone** y una **unidad
extraíble**. Conectas el pendrive en cualquier equipo, se abre una ventana y se
sincroniza. Nada que instalar en el equipo anfitrión, ninguna dependencia de
Python, ningún servicio de terceros por medio.

- **Python puro** (3.11+), solo biblioteca estándar. No hay `requirements.txt`
  porque no hay nada que instalar.
- **El programa vive en el dispositivo**, en una carpeta oculta `.prdrive/`,
  junto a un binario portable de rclone.
- **Tu remoto es tuyo**: SFTP, WebDAV, S3, Drive… lo que soporte rclone. El
  código no conoce ningún servidor concreto.
- **Windows, Linux y macOS**, con el mismo dispositivo.

> **Aviso**: esto mueve y borra ficheros. Los modos `*-mirror` borran en el
> destino lo que no esté en el origen. Lee [Seguridad](#seguridad) antes de
> configurar el primero, y usa `--dry-run`.

---

## Índice

- [El modelo](#el-modelo) · [Instalación](#instalación) · [Uso diario](#uso-diario)
- [Configuración](#configuración) · [Modos](#modos) · [Filtros](#filtros)
- [Cómo funciona bisync por dentro](#cómo-funciona-bisync-por-dentro)
- [El servicio periódico](#el-servicio-periódico) · [El vigilante](#el-vigilante)
- [Diagnóstico](#diagnóstico) · [Seguridad](#seguridad)
- [Arquitectura](#arquitectura) · [Desarrollo](#desarrollo)

---

## El modelo

Hay tres piezas, y entenderlas es entender el programa entero:

```
   TU REMOTO                        EL DISPOSITIVO                EL EQUIPO
   (cualquier backend               (pendrive, SSD, tarjeta…)     (anfitrión)
    de rclone)

   pairs.toml  ─── catálogo ───►    .prdrive/sync_config.toml     penwatch
   qué parejas EXISTEN              cuáles usa ESTE               lo detecta
   [remote] cómo se conecta         + su rclone.conf y su clave   y lo lanza

   /datos/docs    ◄── bisync ──►    sync-data/docs
   /datos/claves  ◄── bisync ──►    sync-data/claves
```

**El catálogo** (`pairs.toml`, en tu remoto) dice **qué parejas existen** y **cómo
se conecta** un dispositivo. Es el mismo fichero para todos. El alta y la baja de
una carpeta ocurren ahí primero.

**El dispositivo** tiene su `sync_config.toml`, que dice **cuáles de ellas usa**.
Un pendrive pequeño puede llevar dos; el de casa, todas. Esa separación es
deliberada y no conviene colapsarla: crear una pareja y elegir usarla son dos
decisiones distintas.

**El vigilante** (`penwatch`) es lo único que se instala en el equipo anfitrión, y
es opcional.

Dos consecuencias que gobiernan el diseño:

- **En el remoto solo hay configuración.** El programa viaja dentro del
  instalador, no del servidor. Ninguna pareja sincroniza `.prdrive/`, así que ni
  el código, ni el estado, ni la clave privada pueden salir del dispositivo por
  ahí.
- **`sync_config.toml` guarda parejas completas, no referencias.** `sync.py` tiene
  que funcionar sin red. La procedencia de cada pareja (del catálogo, modificada
  aquí, huérfana, sin usar) se *deduce* comparándola con la última copia del
  catálogo, no se guarda en el fichero.

## Instalación

Necesitas Python 3.11+ con Tkinter en el equipo desde el que instalas, y un
remote de rclone al que puedas escribir.

```bash
git clone <este-repo> prdrive
cd prdrive
python prdrive-install.py
```

El asistente son ocho pasos, y el orden no es negociable: no se puede leer el
catálogo antes de saber con qué remoto se habla, ni elegir parejas antes de saber
dónde va el dispositivo, ni inicializarlas antes de que exista el `sync.py` que
las inicializa. Cada paso tiene su condición y **Siguiente** no se enciende hasta
cumplirla.

| # | paso | qué hace |
|---|---|---|
| 1 | **Conexión** | formulario de remoto nuevo, o importar uno de tu `rclone.conf`. Más la ruta del catálogo |
| 2 | **Comprobaciones** | consigue un rclone (lo busca, y si no lo descarga), conecta y lee el catálogo |
| 3 | **Destino** | qué unidad |
| 4 | **Cifrado** | VeraCrypt, BitLocker o ninguno |
| 5 | **Instalación** | copia el programa a `.prdrive/`, los lanzadores, el `rclone.conf` y la clave |
| 6 | **Parejas** | cuáles de las del catálogo usa este dispositivo |
| 7 | **Inicialización** | el `--resync` que fija la referencia de las parejas bisync |
| 8 | **Verificación** | que no falte nada de lo que hace falta para arrancar |

En el paso 3 se listan **todas** las unidades, no solo las que el sistema declara
extraíbles: muchos pendrives y casi todos los SSD por USB se declaran fijos, y
filtrar por ahí es la forma más rápida de que el tuyo no aparezca.

El paso 5 no borra nada fuera de `.prdrive/`. Si esa carpeta ya existe, se
sobrescribe el código y se conserva el resto — es la forma de actualizar un
dispositivo.

### La primera vez

El catálogo todavía no existe. Instala un primer dispositivo con la conexión a
mano y crea las parejas desde su ventana (**Parejas → Catálogo → Añadir**), o
sube un `pairs.toml` con el formato de
[`sync_config.example.toml`](sync_config.example.toml). A partir de ahí, cada
dispositivo nuevo hereda la conexión y las parejas del catálogo.

### Un ejecutable, para no repetir todo esto

```bash
pip install pyinstaller          # solo para compilar
python build_installer.py        # -> dist/prdrive-install.exe
```

Sale un instalador de un solo fichero que **lleva el programa dentro**. Dos
variantes, y la diferencia importa:

- **Sin perfil** (lo normal al clonar el repo): genérico, sin ningún secreto
  dentro, pregunta la conexión al abrirlo. Se puede repartir sin más.
- **Con perfil**: si en el checkout hay un `prdrive-profile.toml` con tu conexión
  y `keys/` con su clave, los **incrusta** y el ejecutable queda llave en mano.
  Ese binario lleva tu clave privada: compártelo solo en privado, y si se filtra
  revoca la clave en el servidor.

`install/secret.py` es el vehículo del perfil: se genera al compilar, está en
`.gitignore` y se borra siempre en un `finally`, también si la compilación falla.

## Uso diario

Doble clic en `runsync.pyw` en la raíz del dispositivo (`runsync.sh` en
Linux/macOS). Desde la línea de órdenes, dentro de `.prdrive/`:

```bash
python sync.py                 # sincroniza todas las parejas
python sync.py docs claves     # solo esas
python sync.py --list          # parejas y extremos resueltos (solo lectura)
python sync.py --doctor        # diagnóstico completo
python sync.py --dry-run       # simula; OBLIGATORIO antes de cualquier *-mirror
python sync.py --resync        # rehace la referencia de bisync
python sync.py -y              # aprueba el resync sin preguntar (cron)
python sync.py --keep-logs     # guarda también los logs de las pasadas buenas

python runsync.py              # la ventana (menú de consola si no hay Tkinter)
python runsync.py --auto       # arranca el servicio periódico sin ventana
python runsync.py --doctor     # cualquier otro argumento va tal cual a sync.py

python penwatch.py install     # registra el vigilante en ESTE equipo/usuario
python penwatch.py status      # qué hay registrado y si se ve el dispositivo
python penwatch.py probe       # solo detección
python penwatch.py uninstall
```

`runsync.py` sin argumentos **para siempre un servicio anterior** antes de nada.

## Configuración

`sync_config.toml` (dentro de `.prdrive/`) es el config de **ese** dispositivo. Se
edita desde la ventana de parejas o a mano; el mismo esquema sirve para el
`pairs.toml` del catálogo.

```toml
[defaults]
remote = "nas"                       # el remote de rclone que usan las parejas
catalog_path = "/prdrive-catalog/pairs.toml"
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

### Flags: se editan en el TOML, nunca en el código

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

El editor de flags de la ventana enseña **las cuatro capas resueltas**, con la
etiqueta de dónde viene cada valor, y avisa cuando un cambio sube el
`--max-delete` efectivo aunque no hayas tocado ese flag.

### `device_remote` (avanzado)

`device_remote = "disp"` en `[defaults]` hace que el lado local sea un remote
`combine` propio, definido en variables de entorno. Con eso el nombre de los
listados de bisync deja de depender de la letra de unidad, y el dispositivo es
igual de portable en `F:` que en `/media/quien/PRDRIVE`. Activarlo exige un
`--resync`. Un remote `alias` **no** sirve: devuelve el Fs de destino tal cual y
la ruta absoluta reaparece.

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
un proceso muerto caduca en vez de bloquear para siempre.

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

## Cómo funciona bisync por dentro

Esta es la parte delicada, y la que explica por qué hay código que parece de más.
Todo vive en `common/bisync.py`, que es el único sitio que imita el
comportamiento interno de rclone y cita los ficheros de sus fuentes que replica.

**La referencia** (*baseline*) son dos listados, uno por lado, que rclone guarda
para saber qué ha cambiado desde la última pasada. Sin ella, bisync no puede
distinguir «este fichero es nuevo» de «este fichero se ha borrado en el otro
lado».

**El nombre de esos listados sale de las rutas de los dos extremos.** rclone los
llama `F__sync-data_docs..nas__datos_docs.path1.lst` y similares. De ahí se
siguen tres cosas:

- Si el dispositivo se monta con otra letra, el nombre cambia y rclone no
  encuentra su referencia. `normalize_prefix()` renombra el juego de listados
  solo, antes de ejecutar. `heal_listings()` es la red de abajo: lee las líneas
  `Tip: Path1/Path2` de un log fallido y reintenta **una** vez.
- Si cambias `local`, `remote`, `remote_path` o `mode`, el nombre esperado también
  cambia — pero ahí renombrar sería mentir: le estarías diciendo a bisync que un
  listado del destino *anterior* describe el *nuevo*. Por eso el editor de
  parejas **aparta** la referencia (`state/<pareja>.old-<fecha>/`) y te obliga a
  un `--resync` explícito.
- Con `device_remote` el lado local pasa a llamarse `disp:sync-data/docs` y el
  nombre deja de depender de la máquina.

**Un `[defaults]` puede invalidar varias referencias a la vez.** `remote` y
`device_remote` alimentan los extremos de *todas* las parejas, así que un solo
cambio ahí mueve varios prefijos sin que hayas tocado ninguna pareja. La decisión
se toma **comparando prefijos** antes y después, no mirando qué claves se
editaron.

**Una ruta local que no existe es una alarma, no un descuido.** Si hay referencia
pero la carpeta local no está, se aborta con código 2 en vez de crearla: un lado
local vacío se leería como «se ha borrado todo» y se propagaría, con
`--max-delete` como único freno. Solo se crea la carpeta de las parejas que aún no
tienen referencia.

**El resync se pregunta una vez, antes de empezar.** Y si no hay terminal (cron,
el servicio, el vigilante) la respuesta por defecto es *no*: esas parejas se
saltan, con un código distinto de «ha fallado», en vez de rehacerse solas sin que
nadie mire.

## El servicio periódico

`runsync.py` puede quedarse sincronizando cada N minutos. Su coordinación vive en
`state/`, dentro del dispositivo, para que viaje con él:

| fichero | qué es |
|---|---|
| `daemon.lock.json` | pid, equipo, parejas y último ciclo. Escritura atómica |
| `daemon.stop` | su presencia es una petición de parada |
| `daemon.log` | registro, se recorta solo |
| `ui_prefs.json` | lo último que se eligió en la ventana |

La ventana arranca precargada con la última elección, por encima de `[daemon]` del
TOML, por encima de «todas las parejas / 30 minutos». Solo la ventana escribe esa
memoria: `--auto` la lee pero no la pisa, para que un arranque automático no
cambie lo que elegiste a mano.

El servicio se para cuando el dispositivo desaparece o cuando se vuelve a lanzar
`runsync.py`. En Windows se lanza con `pythonw.exe` y sin consola, y hace `chdir`
al directorio temporal para que la unidad se pueda extraer con seguridad.

## El vigilante

`penwatch.py` es lo único que se instala en el equipo anfitrión, y **nunca escribe
en el dispositivo** (eso bloquearía la extracción segura): su configuración, su
estado y su registro viven en el equipo.

- **Por usuario, sin permisos de administrador.** En Windows, una tarea del
  Programador de tareas disparada al iniciar sesión; en Linux, una unidad *user*
  de systemd más `loginctl enable-linger`.
- **Sondea, no se suscribe a eventos del sistema.** En una unidad cifrada el
  evento de conexión llega mucho antes de que el volumen se pueda leer, y lo que
  importa es «ya se puede leer», que solo se sabe intentándolo.
- **Identifica la unidad por el fichero `PRDRIVE` de su raíz** (con un `id=` dentro
  si lo lleva), nunca por la letra ni por el punto de montaje. Antes de lanzar
  nada confirma que existe `.prdrive/runsync.py`.
- Se dispara **una vez por conexión**: el disparo se rearma cuando la unidad
  desaparece.
- `--mode` decide qué lanza: `ui` (por defecto), `sync` o `daemon`.

## Diagnóstico

```bash
python sync.py --doctor
```

Dice, por cada pareja: dónde apuntan sus dos extremos, si la referencia de bisync
está sana (`fresh` / `ok` / `broken`), con qué nombre la busca rclone, si los
filtros han cambiado desde el último `--resync` y si hay algún `.lck` de un
proceso muerto.

Los logs de rclone **solo se guardan si la pasada falla** (o con `--keep-logs`),
para no gastar ciclos de escritura de la unidad. Quedan en `.prdrive/logs/`. Al
fallar se imprime la cola del log y se traduce el error de rclone a una
explicación, si es uno de los conocidos.

Casos habituales:

- **«Must run --resync».** Los filtros han cambiado. `python sync.py <pareja> --resync`.
- **No encuentra la referencia.** Suele ser la letra de unidad y se arregla solo;
  si cambiaste rutas a mano, `--resync`.
- **La ventana de parejas dice que no hay catálogo.** Sin red se abre con la
  última copia (`state/catalog.toml`) y **no deja editarlo**: no se puede
  sobrescribir con seguridad lo que no se acaba de leer. Puede que otro
  dispositivo lo haya tocado mientras tanto.

## Seguridad

Léelo entero antes de usar esto con datos que te importen.

- **La clave de tu remoto vive dentro del dispositivo**, en `.prdrive/keys/`.
  Quien lo encuentre entra en tus datos hasta que revoques esa clave. **Cífralo**
  (el asistente ayuda con VeraCrypt y BitLocker) y usa en el servidor un usuario
  dedicado y limitado, no el administrador.
- **La clave nunca sube al remoto.** Ninguna pareja sincroniza `.prdrive/`. Las
  rutas del `rclone.conf` del dispositivo son relativas (`key_file = keys/…`), que
  es además lo que lo hace funcionar con cualquier letra de unidad.
- **Los modos `*-mirror` borran.** `--max-delete` es el único freno automático.
  Prueba siempre con `--dry-run` primero.
- **Escribir el catálogo es lo más arriesgado del programa**, porque gobierna
  borrados en todos tus dispositivos. Por eso `catalog.push()` genera y verifica
  el TOML antes de tocar la red, **relee el remoto y se niega si ha cambiado**
  desde que se leyó, copia `pairs.toml` → `pairs.toml.bak` y solo entonces sube.
- **El instalador con perfil incrustado lleva tu clave privada.** No lo publiques.
- Las claves de recuperación de BitLocker se suben **al remoto** y nunca al
  dispositivo: dentro del volumen que descifran no servirían de nada.

## Arquitectura

```
prdrive/
├── sync.py            el motor: monta la orden de rclone, la lanza, informa
├── runsync.py         la ventana y el servicio periódico
├── penwatch.py        el vigilante del equipo anfitrión
├── prdrive-install.py el asistente de instalación
├── build_installer.py compila el ejecutable
├── common/            lo que comparten los puntos de entrada
│   ├── model.py       el TOML convertido en objetos ya resueltos
│   ├── bisync.py      lo que replica el comportamiento interno de rclone bisync
│   ├── config_file.py lee Y escribe el TOML, con round-trip verificado
│   ├── catalog.py     el catálogo del remoto: leer, cachear, escribir
│   └── store.py       los ficheros de estado en JSON del dispositivo
├── ui/                pantallas y su lógica
│   ├── theme.py       la paleta, las fuentes y los estilos ttk. Sin ventana
│   ├── icons.py       los iconos, rasterizados aquí. Sin dependencias
│   ├── tk*.py         solo dibujan
│   └── *_editor.py    lo que decide y toca disco. Sin Tk, probado sin pantalla
├── install/           lo que sabe el instalador. Sin Tk, sin dispositivo
│   ├── profile.py     la conexión: de dónde sale y cómo se escribe
│   ├── deploy.py      copiar el código, escribir el config, el --resync
│   ├── device.py      qué volúmenes hay y cuál es el bueno
│   └── crypto.py      VeraCrypt y BitLocker
├── tests/             scripts sueltos, sin framework
└── design/            las maquetas que implementa ui/
```

Tres reglas que sostienen todo lo demás:

**Se parsea una vez, en el borde.** `model.parse_config()` convierte el TOML en
objetos inmutables con las capas ya fundidas. Nadie aguas abajo vuelve a
preguntar por claves del TOML ni repite `.get(clave, defecto)`.

**Los `tk_*` solo dibujan.** Todo lo que decide o toca disco vive en módulos que
no importan Tkinter y se prueban sin pantalla. Y `import tkinter` va siempre
**dentro** de las funciones, nunca arriba: `ui/` lo importan también los caminos
sin interfaz, donde puede no haber ni tkinter ni pantalla, y el fallo tiene que
saltar al abrir la ventana, que es cuando se puede caer al menú de consola.

**Plan, consecuencias, confirmación, ejecución.** Editar parejas o el catálogo
devuelve primero un plan que no ha tocado nada, con la lista de lo que va a pasar.
Se enseña en una ventana con una línea por consecuencia —no en un cuadro de
diálogo con seis líneas de texto seguido, que es justo lo que nadie lee— y solo
entonces se ejecuta. La cirugía de disco va **antes** que escribir el config, y se
deshace si el config falla: la combinación a evitar es «config nuevo con
referencia vieja», y así el peor caso posible es una referencia apartada de más,
que un `--resync` arregla.

## Desarrollo

```bash
python tests/run_all.py               # todos, en procesos separados
python tests/test_install_deploy.py   # o uno suelto
python -m ui.icons                    # repinta el .ico (sin Tk, sin pantalla)
```

No hay linter ni build. Se verifica ejecutando: `run_all.py`, `--doctor` y
`--dry-run`. **Ningún test toca la red ni un dispositivo real**; el único punto de
red de cada módulo es una función que los tests sustituyen entera.

Convenciones: comentarios, docstrings y todo lo que ve el usuario, **en español**.
Los comentarios explican el *porqué* contra el comportamiento real de rclone, y a
menudo citan el fichero de sus fuentes que replican; eso se conserva al tocar
cualquier cosa relacionada con bisync.

`device-readme.md` es la guía rápida que el instalador deja en la raíz del
dispositivo. `CLAUDE.md` documenta la arquitectura con más detalle del que cabe
aquí, incluidas las trampas que no se ven leyendo el código.

## Licencia

Pendiente de elegir.
