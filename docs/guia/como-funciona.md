[← Guías](README.md)

# Cómo funciona

El modelo de prdrive (qué vive en el remoto, en la unidad y en el equipo) y qué hace bisync por dentro.

## El modelo

Hay tres piezas, y entenderlas es entender el programa entero:

```
   TU REMOTO                        EL DISPOSITIVO                EL EQUIPO
   (cualquier backend               (pendrive, SSD, tarjeta…)     (anfitrión)
    de rclone)

   pairs.toml  ─── catálogo ───►    .prdrive/sync_config.toml     penwatch
   qué parejas EXISTEN              cuáles usa ESTE               lo detecta
   [remote] cómo se conecta         + su rclone.conf y su clave   y lo lanza

   devices/<id>.toml ◄── nota ───   quién es, qué versión lleva
   el registro de la flota          y cuándo sincronizó

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

**El registro de la flota** (`devices/`, al lado del catálogo) es un fichero
diminuto por dispositivo, que cada uno reescribe **solo el suyo** al sincronizar:
cómo se llama, qué versión lleva, para qué plataformas sirve, cómo acabó su
última pasada (y, si falló, desde cuándo no consta una buena) y **en qué equipos
se ha enchufado**, los cinco últimos, por su nombre de red. Es lo que permite ver
desde cualquiera de ellos cuántos hay, cuál lleva un mes en un cajón y dónde se
usó por última vez. El nombre de los equipos se publica siempre: quien puede leer
`devices/` tiene la clave del remoto, y con ella todo lo que se sincroniza.

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

- Con `device_remote` —que el instalador pone en todo dispositivo nuevo— el lado
  local pasa a llamarse `disp:sync-data/docs`, y el nombre deja de depender de
  dónde esté montado el dispositivo. Es lo que hace que enchufarlo en otro
  ordenador, o con otra letra, no rompa nada.
- Si cambias `local`, `remote`, `remote_path` o `mode`, el nombre esperado sí
  cambia, y ahí reaprovechar los listados sería mentir: le estarías diciendo a
  bisync que un listado del destino *anterior* describe el *nuevo*. Por eso el
  editor de parejas **aparta** la referencia (`state/<pareja>.old-<fecha>/`) y te
  obliga a un `--resync` explícito.
- **No hay ningún renombrado automático de listados.** Lo hubo, mientras el
  nombre dependía de la letra de unidad, y era un apaño peligroso: no se puede
  distinguir el caso benigno (el mismo destino con otro nombre) del maligno (otro
  destino). Con `device_remote` el caso benigno ya no ocurre.

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
