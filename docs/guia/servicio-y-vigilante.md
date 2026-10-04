[← Guías](README.md)

# El servicio periódico y el vigilante

Sincronizar cada N minutos y que la unidad se abra o sincronice sola al enchufarla.

## El servicio periódico

`runsync.py` puede quedarse sincronizando cada N minutos. Es **un solo servicio con
dos maneras de arrancarlo**: a mano, con «Iniciar servicio», o al enchufar el
dispositivo en un equipo que tenga [el vigilante](#el-vigilante). Las dos usan las
mismas parejas y el mismo intervalo, los que se eligen en la ventana. Su coordinación
vive en `state/`, dentro del dispositivo, para que viaje con él:

| fichero | qué es |
|---|---|
| `daemon.lock.json` | pid, equipo, parejas y último ciclo. Escritura atómica |
| `daemon.stop` | su presencia es una petición de parada |
| `daemon.log` | registro, se recorta solo |
| `ui.lock.json` | pid y equipo de la ventana abierta, si la hay |
| `ui_prefs.json` | las parejas y el intervalo del servicio |
| `last_run.json` | cómo acabó la última pasada de cada pareja, y qué log la explica |
| `historial.jsonl` | las últimas 50 pasadas de cada pareja: cuándo, cuánto duró, si fue bien. Se recorta solo |
| `conflicts.json` | los ficheros en conflicto del último recorrido |

**Un fallo no se queda escondido.** `sync.py` apunta en `last_run.json` el
resultado de cada pareja, la lance quien la lance. Al abrir la ventana, las
parejas cuya última pasada falló salen en un bloque ámbar con un botón al log
conservado, hasta que una pasada buena lo quite. Y el servicio, cuando una pareja
**empieza** a fallar, abre él mismo una ventanita —en su propio intérprete, sin
lanzar ningún proceso—: un ciclo bueno no enseña nada, y el mismo fallo repetido
cada media hora no vuelve a saltar. Sin pantalla, el aviso se queda en
`daemon.log`. El servicio sigue sin preguntar nada nunca: una pareja que pide
`--resync` se salta.

**Desde cuándo falla.** Cada pasada real deja además una línea en
`historial.jsonl`, y la fila del fallo en «Reparación» —y `sync.py --doctor`—
lo resume: «Falla desde el 12/09 · 0 de las últimas 14 bien». Es lo que separa
un tropiezo de una avería. Para gastar lo mínimo del pendrive, cada pasada
**añade** una línea y el fichero solo se reescribe entero cuando una pareja pasa
de 100, para dejarla en 50.

**Qué parejas y cada cuánto.** Las casillas de la ventana son las mismas para
«Sincronizar ahora» y para «Iniciar servicio», y salen marcadas con las del
servicio; «Marcar todas» y «Desmarcar todas» están en el rótulo de la lista. El
intervalo, «El servicio repite cada N minutos», está en **«Ajustes…» →
«Configuración…»**: solo lo usa el servicio y se toca pocas veces. **Las parejas
solo las guarda «Iniciar servicio»**, y «Configuración» guarda solo el
intervalo, sin fijar las parejas: una pasada manual con dos parejas marcadas no
decide qué sincroniza el servicio la próxima vez que enchufes el dispositivo. Lo
guardado manda sobre `[daemon]` del TOML, que manda sobre «todas las parejas /
30 minutos», y vale igual para la ventana, para `--auto` y para el vigilante.
`--auto` lo lee pero no lo pisa.

El servicio se para cuando el dispositivo desaparece o cuando se vuelve a lanzar
`runsync.py`. En Windows se lanza con `pythonw.exe` y sin consola, y hace `chdir`
al directorio temporal para que la unidad se pueda extraer con seguridad.

**Una ventana a la vez.** Como abrir `runsync.py` detiene el servicio anterior,
dos ventanas se lo quitarían la una a la otra: la segunda no se abre y lo dice.
Mientras haya ventana abierta o servicio en marcha, el vigilante tampoco lanza
nada al enchufar el dispositivo; la línea del arranque automático de la ventana
lo dice, y al arrancar el servicio se avisa de lo mismo.

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
- **Identifica la unidad por el fichero `.prdrive/PRDRIVE`** (con un `id=` dentro
  si lo lleva), nunca por la letra ni por el punto de montaje. Antes de lanzar
  nada confirma que existe `.prdrive/runsync.py`. Va dentro de la carpeta del
  programa y no en la raíz porque para identificar la unidad da igual dónde
  esté, mientras la ruta sea relativa a ella.
- Se dispara **una vez por conexión**: el disparo se rearma cuando la unidad
  desaparece.
- **Con VeraCrypt, abre el contenedor.** Cerrado, el `.prdrive/PRDRIVE` no se ve;
  lo que sí se ve es la marca de fuera, con el mismo id. Con ella el vigilante le
  pide a VeraCrypt que abra el contenedor —la contraseña la pide VeraCrypt en su
  ventana, no pasa por prdrive— y, en cuanto está abierto, sigue como siempre.
  **Una vez por conexión** también: si cancelas la contraseña no vuelve a
  preguntar hasta que quites la unidad y la vuelvas a poner, y tampoco después
  de «Expulsar». En Linux, solo con escritorio y con VeraCrypt instalado: sin
  él, udisks2 y cryptsetup piden la contraseña en una terminal, y el vigilante
  no tiene. Apunta en su diario con qué se abre en ese equipo, y en cuanto lo
  abres con `abrir-prdrive.sh`, sigue como siempre.
- **No lanza nada si ya hay ventana o servicio en marcha** en ese equipo: lee
  (sin escribir) los dos registros del dispositivo y lo anota en su diario. El
  disparo se da por gastado igual, para no reintentarlo cada minuto detrás de una
  ventana abierta.
- `--mode` decide qué lanza: `ui` (por defecto) abre la ventana, `daemon` arranca
  el servicio (`runsync --auto`) y `sync` hace una pasada y nada más (`runsync
  --auto --once`). **Qué parejas y cada cuánto no se decide aquí**: son los del
  servicio, que viven en el dispositivo; el vigilante lanza runsync sin ellos y
  runsync los lee allí.
- **La ventana dice qué hace este equipo al enchufar**, en una línea encima del
  pie —«Al enchufarlo en este equipo: arranca el servicio · Cambiar…»—, y lleva a
  la pantalla del vigilante. También dice si el vigilante de este equipo es para
  otro dispositivo, o si es de otra versión: la copia del equipo solo la pone al
  día `install`, así que tras actualizar el dispositivo hay que reinstalarlo.
- **Tiene su propio Python.** `install` copia el del dispositivo a su carpeta del
  equipo y registra la tarea con esa copia, así que no se rompe cuando alguien
  actualiza o desinstala el Python del sistema. En cada detección compara el
  sello del dispositivo con el de la copia y, si difieren, copia la versión nueva
  al lado, cambia el puntero y vuelve a registrar la tarea (sustituir la carpeta
  en su sitio no se puede: el vigilante corre desde ella). Si el dispositivo no
  lleva Python para ese equipo, usa el del sistema y `penwatch status` lo dice.
