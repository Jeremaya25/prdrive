# Un servicio, dos maneras de arrancarlo (issue #14)

Fecha: 2026-09-23 · Estado: aceptada e implementada · Versión: 0.3.1

## El problema

Tres controles de la ventana principal hablan de lo mismo —cuándo se sincroniza
solo— y no se entiende cuál manda:

- **«Iniciar servicio»** (`ui/tk.py`, el pie) arranca el servicio periódico con lo
  marcado y el intervalo de «Repetir cada», y cierra la ventana.
- **«Arranque automático…»** abre `tk_watch`, que registra el vigilante en **este
  equipo** con su modo, sus parejas y su intervalo.
- **«Repetir cada N minutos»** está en medio de la ventana y solo lo usa «Iniciar
  servicio».

El issue dice que el intervalo de la ventana «no tiene ninguna relación» con el
del arranque automático. Leyendo el código, la relación existe pero no se ve, y
eso es peor:

- **Cuatro sitios deciden parejas e intervalo.** `[daemon]` del catálogo, copiado
  a `[daemon]` de `sync_config.toml` al aprovisionar (`deploy._daemon_section`);
  `state/ui_prefs.json` en el dispositivo; y `watch.json` en el equipo. Para el
  vigilante en modo `daemon` manda `watch.json` > `ui_prefs.json` > `[daemon]` >
  todas cada 30 min (`penwatch.launch` → `runsync.auto_start` →
  `prefs.startup_defaults`).
- **«Sincronizar ahora» también escribe esa memoria** (`tk.py`, `sincronizar()`
  llama a `prefs.save_prefs("manual", …)`). Marcar solo «fotos» para una pasada
  rápida hace que el próximo arranque automático sincronice solo «fotos».
- **El formulario del vigilante dice dos cosas falsas.** «vacío = el de [daemon]
  del TOML»: vacío es la última elección de la ventana, y solo si no hay ninguna,
  `[daemon]`. «Vacío = todas»: en modo `daemon` es lo mismo que lo anterior, y en
  modo `sync` es el fallo siguiente.
- **Fallo: `--mode sync` sin parejas abre la ventana.** `penwatch.launch()` lanza
  `runsync.py` sin argumentos, que es `ui_flow()`: abre la ventana (y para el
  servicio que hubiera) en vez de hacer una pasada en silencio. Ningún test
  cubre `launch()`.

## Decidido al plantearlo

- **Una sola cosa, dos maneras de arrancarla.** «El servicio» es sincronizar solo
  cada N minutos mientras el dispositivo siga puesto. Se arranca a mano («Iniciar
  servicio») o al enchufar el dispositivo en este equipo (el vigilante).
- **Parejas e intervalo, solo en el dispositivo.** Una sola configuración que
  viaja con él. El equipo guarda solo lo que es del equipo: qué hacer al enchufar,
  el sondeo y las raíces extra. No hay excepción por equipo.
- **Casillas compartidas.** La lista de parejas de la ventana es la misma para
  las dos acciones. **Solo «Iniciar servicio» guarda** lo marcado y el intervalo;
  «Sincronizar ahora» no guarda nada. La ventana abre con lo del servicio marcado.
- **Un botón para marcar o desmarcar todas.**

## El modelo

| Qué | Dónde | Quién lo escribe |
|---|---|---|
| Parejas + intervalo del servicio | `state/ui_prefs.json` (dispositivo) | «Iniciar servicio» y la opción 3 del menú de consola |
| Valor de fábrica de lo anterior | `[daemon]` de `sync_config.toml` (dispositivo) | el instalador, desde el catálogo |
| Qué hacer al enchufar, sondeo, raíces extra | `watch.json` (equipo) | `penwatch install` |

Precedencia, igual para la ventana, `--auto` y el vigilante: `ui_prefs.json` >
`[daemon]` > todas cada 30 min. Los argumentos explícitos de `runsync --auto`
(`--interval N`, parejas) siguen mandando sobre todo: es la interfaz de un acceso
directo o un cron, y lo que mandan los vigilantes que aún no se han reinstalado
(ver «Compatibilidad»).

**El fichero no cambia de nombre.** `ui_prefs.json` pasa a significar «la
configuración del servicio», que es también con lo que sale precargada la
ventana. Renombrarlo pediría una migración para un cambio de palabra.

**Un registro `action == "manual"` no cuenta.** Solo pueden existir de antes de
este cambio, y son exactamente el recuerdo de una pasada manual que no debe
decidir el servicio. `startup_defaults()` los trata como si no hubiera registro
y cae a `[daemon]`. Se descartan por `== "manual"` y no por `!= "daemon"`: un
registro sin `action`, escrito a mano o por una versión muy vieja, sigue
valiendo.

### Lo que se pierde

Quien solo sincroniza a mano y siempre desmarca las mismas parejas (una muy
grande, por ejemplo) deja de tenerlo recordado: la ventana abre con las del
servicio, o todas. El botón de marcar y desmarcar todas lo abarata, pero es un
paso más en cada apertura. Si pesa, la salida es que «Iniciar servicio» no sea la
única manera de guardar la selección (un «Recordar esta selección»); no entra en
esta versión.

## Diseño

### `ui/prefs.py`

- `startup_defaults()`: un registro con `action == "manual"` es como no tener
  registro. La nota pasa de «Precargado con la última elección» a «Parejas e
  intervalo del servicio, elegidos el …».
- `save_prefs()` no cambia de firma. El docstring del módulo dice qué guarda
  ahora y quién lo escribe.

### `runsync.py`

- `_atender()` guarda las preferencias **solo** con `choice.action == "daemon"`.
- **`--auto --once`**: una pasada de las parejas del servicio y nada más. Resuelve
  las parejas igual que `--auto` (argumentos > `startup_defaults()`), e ignora
  `--interval`. Si en este equipo hay una ventana abierta o un servicio vivo, no
  hace nada y lo dice: el vigilante ya no lanzaría en ese caso, pero un cron sí,
  y una pasada al lado del servicio chocaría con el lock de bisync. **No** para el
  servicio anterior, a diferencia de `--auto`: cambiar un servicio por una sola
  pasada dejaría el dispositivo sin servicio, y no es lo que se pide.
  La pasada es `sync.py <parejas>` con la entrada y la salida heredadas, lo mismo
  que hace hoy el modo `sync` con parejas: sin terminal, una pareja que pide
  `--resync` se salta, y la salida va al diario del vigilante.
- `auto_start()` acepta `--once` e `--interval N` en cualquier orden antes de las
  parejas.
- El docstring del módulo documenta `--auto [--once] [--interval N] [parejas]`.

### `penwatch.py`

- `launch()`: `daemon` → `runsync.py --auto`; `sync` → `runsync.py --auto --once`;
  `ui` → `runsync.py`, como hoy. **No pasa parejas ni intervalo**, y si un
  `watch.json` los trae, los ignora. Arregla el fallo de `sync` sin parejas.
- `install` pierde `--pairs` e `--interval`. `cmd_install` deja de escribirlos, y
  su resumen final y la fila «Modo» de `status_rows()` dejan de enseñarlos.
- **`copia_al_dia() -> bool`**: compara los bytes de `SELF_COPY` con los del
  propio `__file__`, que es el `penwatch.py` del dispositivo cuando lo llama la
  ventana o se ejecuta desde `.prdrive/`. El vigilante del equipo es la copia que
  hizo `install`, y **nada la pone al día sola**: `refresh_runtime()` refresca el
  Python, no el script. Si no coinciden, `status_rows()` añade una fila de aviso
  («La copia de este equipo no es la de este dispositivo: reinstálala para que
  haga lo que dice la ventana»), así que `penwatch status` también lo dice.
- El docstring del módulo: los modos y que parejas e intervalo son los del
  servicio, en el dispositivo. La restricción del issue sigue en pie: penwatch no
  lee nada del dispositivo aparte de lo que ya leía; quien lee la configuración es
  `runsync`, que corre desde el dispositivo.

### `ui/watch.py`

- `install_command()` pierde `pairs` e `interval`; `installed_options()` los deja
  de devolver y devuelve `device_id`.
- `MODE_HELP` con el sentido nuevo: `daemon` «arranca el servicio, con las parejas
  y el intervalo de la ventana principal»; `sync` «una pasada de las parejas del
  servicio, en silencio, y se cierra».
- **`resumen() -> Resumen`**: lo que la ventana principal dice en una línea, como
  dato y sin Tk. Solo lee ficheros (`watch.json`, las dos copias de penwatch, el
  PRDRIVE del dispositivo): nada de `schtasks` ni `systemctl`, porque se pregunta
  al pintar y la primera pintura tiene que ser instantánea (la regla de
  `update.pending()`). Estados, el primero que aplique:
  1. `no_disponible`: penwatch no se puede importar → no hay línea.
  2. `sin_instalar`: no hay `watch.json`.
  3. `otro_dispositivo`: `watch.json` tiene `device_id` y no es
     `fleet.device_id()`. Un equipo tiene un solo vigilante, así que con dos
     prdrive el segundo en instalarse se queda con él.
  4. `desfasado`: `penwatch.copia_al_dia()` es False.
  5. `instalado`, con su modo.

  Función de módulo, para que los tests la sustituyan (la convención de
  AGENTS.md).

### La ventana principal (`ui/tk.py`)

```
PAREJAS  [Marcar todas]                    3 de 4 · última pasada hace 2 h
┌───────────────────────────────────────────────────────────────────┐
│ ☑ docs    bisync                         hace 2 h      [al día]   │
│ …                                                                 │
└───────────────────────────────────────────────────────────────────┘
[Parejas…]                                                   [Ajustes…]

⏱ Repetir cada [30] minutos, mientras el dispositivo siga puesto
⏻ Al enchufarlo en este equipo: arranca el servicio.        [Cambiar…]
─────────────────────────────────────────────────────────────────────
[ Sincronizar ahora                            ] [ Iniciar servicio ]
```

- **Marcar o desmarcar todas**: un `Quiet.TButton` en la fila del rótulo
  «Parejas». Su texto dice lo que hará: «Marcar todas» si falta alguna,
  «Desmarcar todas» si están todas. Se actualiza con un `trace` en cada casilla,
  igual que el «3 de 4» del resumen, que hoy se calcula una vez al pintar y pasa a
  seguir las casillas. Solo aparece con dos parejas o más.
- **«Repetir cada» baja junto al pie**, encima del separador, porque es un dato
  del servicio y no de la lista. Sigue precargado con el intervalo del servicio y
  sobrevive a los repintados como hoy (`vista["intervalo"]`).
- **La línea del arranque automático sustituye al botón** «Arranque automático…».
  Su texto sale de `watch.resumen()`:

  | Estado | Texto | Botón |
  |---|---|---|
  | `sin_instalar` | En este equipo no se arranca nada al enchufarlo. | Configurar… |
  | `otro_dispositivo` | El arranque automático de este equipo es para otro dispositivo. | Cambiar… |
  | `desfasado` | El arranque automático de este equipo es de otra versión: puede no hacer lo que dice aquí. (en ámbar) | Revisar… |
  | `instalado`, `ui` | Al enchufarlo en este equipo: abre esta ventana. | Cambiar… |
  | `instalado`, `daemon` | Al enchufarlo en este equipo: arranca el servicio. | Cambiar… |
  | `instalado`, `sync` | Al enchufarlo en este equipo: una pasada de estas parejas. | Cambiar… |

  El botón abre `tk_watch` como hoy, y al volver se repinta la línea. Sigue
  encendido mientras corre una pasada, como el botón al que sustituye: el
  vigilante no toca nada del dispositivo. Con el
  vigilante instalado para este dispositivo, la línea lleva en pista «en pausa
  mientras esta ventana esté abierta», y esa frase sale del aviso de arranque de
  `ui_flow()`, que la decía una vez y desaparecía. El aviso de después de
  «Iniciar servicio» se queda: ese sale cuando la ventana ya se ha cerrado.
- `sincronizar()` deja de llamar a `prefs.save_prefs()`. `servicio()` sigue
  devolviendo `Choice("daemon", marcadas, minutos)`, y quien guarda es `_atender()`,
  como hoy.

### La pantalla del vigilante (`ui/tk_watch.py`)

- **El formulario pierde «Parejas» e «Intervalo del servicio».** En su lugar, una
  pista: «Las parejas y el intervalo son los del servicio: se eligen en la ventana
  principal y viajan con el dispositivo».
- **El modo, con tres radios en palabras** en vez de un combobox con `ui` / `sync`
  / `daemon`: «Abrir la ventana», «Arrancar el servicio», «Una pasada y nada más».
  Cada una con su `MODE_HELP` en pista.
- `formulario_instalacion()` deja de necesitar `config`, que solo servía para las
  casillas.
- Con `desfasado`, la fila de aviso de `status_rows()` sale en la tarjeta como
  cualquier aviso de penwatch, y «Reinstalar…» es el arreglo: `install` se lanza
  con el `penwatch.py` del dispositivo, que se copia sobre el del equipo.

### El menú de consola (`ui/console.py`)

Sin cambios de forma. Las opciones 1 y 2 son pasadas manuales y dejan de guardar
(`_atender()`); la 3 es el servicio y guarda. La línea de «Precargado…» usa la
nota nueva de `startup_defaults()`.

## Compatibilidad

| Situación | Qué pasa |
|---|---|
| Vigilante viejo en `daemon` con parejas o intervalo propios | Sigue pasándolos a `--auto`, que los respeta. La línea dice `desfasado` hasta que se reinstala. |
| Vigilante viejo en `sync` sin parejas | Sigue abriendo la ventana (el fallo vive en la copia del equipo). La línea dice `desfasado`. |
| Vigilante viejo en `sync` con parejas | `runsync.py <parejas>`: una pasada como hoy. |
| `ui_prefs.json` con `action = "manual"` | Se ignora: la ventana y `--auto` salen con `[daemon]` o todas. |
| `ui_prefs.json` con `action = "daemon"` | Es la configuración del servicio, sin cambios. |
| Vigilante nuevo y un dispositivo que ha vuelto a una versión anterior, en `sync` | El `runsync` viejo no conoce `--once`: lo toma por una pareja desconocida y arranca el servicio. La línea dice `desfasado`. |

No hay código de migración: reinstalar el vigilante lo pone al día, y la ventana
lo pide.

## Lo que NO cambia

- `penwatch.py` no importa `common/` ni `ui/`, y no lee del dispositivo nada que
  no leyera: el PRDRIVE, `runsync.py`, los dos registros, el runtime. Solo
  compara su copia con la del equipo, y eso lo hace quien lo importa desde el
  dispositivo.
- El servicio coordina por `state/` del dispositivo (`daemon.lock.json`,
  `daemon.stop`).
- `runsync.py` sin argumentos para el servicio anterior antes de nada.
- `--auto` y el servicio solo leen `ui_prefs.json`; lo escribe solo la ventana (o
  el menú), y ahora solo al arrancar el servicio.
- `[daemon]` del catálogo y su recorte al aprovisionar.

## Pruebas

- **`tests/test_prefs.py`**: un registro `manual` no cuenta y se vuelve a
  `[daemon]`; uno `daemon` sí; uno sin `action`, también. Los dos casos que hoy
  guardan `manual` para probar el orden y el recorte pasan a `daemon`.
- **`tests/test_auto.py`**: `--once` lanza `sync.py` con las parejas del servicio
  y no llama a `spawn_daemon`; con un servicio vivo en este equipo no hace nada y
  no lo para; `--interval` y `--once` en los dos órdenes; los argumentos siguen
  mandando.
- **`tests/test_penwatch_launch.py`** (nuevo; hoy nada cubre `launch()`): con
  `Popen` sustituido, `daemon` → `--auto`, `sync` → `--auto --once`, `ui` → sin
  argumentos; un `watch.json` con `pairs` e `interval` no los pasa. `copia_al_dia()`
  con copias iguales, distintas y sin copia.
- **`tests/test_watch.py`**: `install_command()` sin parejas ni intervalo;
  `resumen()` en sus cinco estados, con penwatch y `fleet.device_id` sustituidos.
- **`tests/test_tk_screens.py`**: «Marcar todas» marca todas y pasa a decir
  «Desmarcar todas», y al revés; el «N de M» sigue a las casillas; «Sincronizar
  ahora» no escribe `ui_prefs.json`; la línea del vigilante dice lo de la tabla
  en cada estado; el formulario de `tk_watch` no tiene parejas ni intervalo.
- **`tests/test_start.py`, `tests/test_tk_reparacion.py`**: siguen encontrando
  «Iniciar servicio» y «Sincronizar ahora» por su texto; se comprueba que no
  hace falta tocarlos.
- **`tests/test_tk_medidas.py`**: la ventana principal con la línea más larga
  (`desfasado`) y el botón de marcar, en toda la matriz de resolución ×
  `tk scaling`.
- `python tests/run_all.py` en verde.

## Documentación

- **`AGENTS.md`**: «Daemon»: la precedencia nueva y que solo «Iniciar servicio»
  escribe `ui_prefs.json`; «Mount watcher»: sin parejas ni intervalo, `--auto
  --once`, `copia_al_dia()` y por qué la copia del equipo no se pone al día sola;
  «UI»: la línea del arranque automático en lugar del botón.
- **`README.md`**: «El servicio periódico» (qué se recuerda y quién lo escribe),
  «El vigilante» (los modos y de dónde salen parejas e intervalo) y la lista de
  órdenes (`--auto --once`, `install` sin `--pairs`/`--interval`).
- **`device-readme.md`**: «La ventana» y el «Arranque automático» de abajo, en el
  tono de la guía: el intervalo es del servicio, y la línea dice qué hace este
  equipo al enchufar.
- **`VERSION`** → `0.3.1` (se pensó como `0.2.5`; ver «Al implementarlo»).

## Al implementarlo

Lo que cambió respecto a lo de arriba, y por qué:

- **La fila «Modo» de `status_rows()` sigue enseñando parejas e intervalo
  mientras un `watch.json` de antes los traiga.** La copia vieja del equipo los
  usa, así que es justo cuando importan; al reinstalar desaparecen del fichero.
- **El menú de consola también dice la línea del vigilante**, con la pausa. La
  frase de la pausa salió del aviso de arranque, que era por donde le llegaba a
  la consola.
- **El «N de M» y el botón de marcar siguen a las casillas por su `command`, no
  por un `trace`.** La orden de Tcl de un trace no muere con el widget: sujetaba
  la ventana entera, con sus imágenes, hasta cerrar el intérprete, y al salir
  `Image.__del__` protestaba.
- **Las medidas de la ventana principal van en `tests/test_tk_servicio.py`** y no
  en `test_tk_medidas.py`: la principal abre su propio intérprete de Tk, así que
  la escala se le pone al aplicarle el tema. `test_tk_medidas` no la medía.
- **`MODE_HELP` es más corto** («sincroniza cada N minutos mientras siga puesto»,
  «sincroniza una vez, en silencio, y se cierra»): de dónde salen parejas e
  intervalo lo dice una sola vez la pista de debajo de las tres opciones.
- `tk_watch.open_dialog()` y `formulario_instalacion()` pierden el parámetro
  `config`, que solo servía para las casillas de parejas.
- **Sale como 0.3.1, no como 0.2.5.** Mientras esperaba, `main` publicó la 0.3.0
  (VeraCrypt), que también toca la ventana principal: «Expulsar» en el pie y su
  estado en `leer_estado()`. Los dos se quedan, y la medida de la ventana
  principal de `tests/test_tk_servicio.py` incluye ese tercer botón.

## Después

- **Que el vigilante se ponga al día solo.** `refresh_runtime()` ya copia el
  Python del dispositivo cuando cambia; hacer lo mismo con `penwatch.py` quitaría
  el estado `desfasado`. No entra aquí: el proceso que corre seguiría con el
  código viejo hasta reiniciarse, y eso pide pensar el reinicio.
- **Un «Recordar esta selección»** para las pasadas manuales, si lo que se pierde
  (arriba) resulta pesar.
- **`--once` no toma ningún registro**, igual que el modo `sync` de hoy: una
  ventana abierta durante esa pasada no la ve. Es lo mismo que ya pasa, y no lo
  empeora.
