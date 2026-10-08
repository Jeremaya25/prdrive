[← Guías](README.md)

# Uso diario

Abrir la ventana, la pantalla de parejas, actualizar el programa y poner al día rclone, Python y VeraCrypt de la unidad.

Doble clic en `runsync.bat` en la raíz del dispositivo (`runsync.sh` en Linux).
El `.bat` arranca con el Python del dispositivo —el de ARM64 en un equipo ARM64,
si no el de x64, que un ARM64 ejecuta emulado— y, si no lleva ninguno que sirva,
con el `pythonw.exe` del equipo; la consola parpadea un instante y se va. El `.sh`
hace lo mismo con `runtime/linux-*/bin/python3` y `python3`. Los lanzadores se
escriben al aprovisionar y **no se tocan al actualizar**.

Desde la línea de órdenes, dentro de `.prdrive/` (con `python` el del equipo, o el
del dispositivo: `runtime\windows-x64\python.exe`, `runtime/linux-x64/bin/python3`):

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
python runsync.py --auto --once  # una pasada de las parejas del servicio y se acaba
python runsync.py --doctor     # cualquier otro argumento va tal cual a sync.py

python penwatch.py install     # registra el vigilante en ESTE equipo/usuario
python penwatch.py status      # qué hay registrado y si se ve el dispositivo
python penwatch.py probe       # solo detección
python penwatch.py uninstall
```

`runsync.py` sin argumentos **para siempre un servicio anterior** antes de nada.

**Con VeraCrypt**, los lanzadores están dentro del contenedor: se empieza por
**Abrir PRDRIVE**, en la raíz de la unidad (ver [Cifrar con
VeraCrypt](cifrado.md)). Y para quitarla, **Expulsar**, en el pie de la
ventana: cierra la ventana y después el contenedor. No desmonta ella misma
—corre desde dentro del contenedor, y mientras corra VeraCrypt no puede
desmontar sin forzar—: lanza **Expulsar PRDRIVE** de fuera y se cierra. Si algún
otro programa tiene algo abierto dentro, VeraCrypt pregunta si forzar.

**Con el llavero** (ver [El llavero](llavero.md)), la ventana tiene además
**Abrir llavero**, y **Expulsar** sale también en una unidad sin cifrar: antes de
nada cierra KeePassXC (si está abierto) y sube lo que falte.

## La ventana de parejas

Se abre desde «Parejas…» y es donde se decide qué sincroniza este dispositivo.
Arriba se elige **qué se edita**: «Este dispositivo» (lo que cambies se queda
aquí) o «Catálogo» (lo verán todos los dispositivos; la pantalla lo recuerda con
un aviso ámbar). Debajo, la lista con el modo y el estado de cada pareja, y la
**pareja elegida**, que se cambia ahí mismo: «Guardar aquí…» o «Guardar en el
catálogo…» enseñan antes lo que va a pasar. Una pareja que este dispositivo no
usa se ve pero no se cambia: primero **Usar aquí**. Si pasas a otra pareja con
cambios sin guardar, se pregunta antes de perderlos. Cuatro cosas más que se
hacen desde ahí:

- **Simular.** Lanza un `--dry-run` de la pareja elegida en la ventana de salida:
  rclone enumera lo que copiaría y lo que borraría, y no toca nada. Es la forma
  de ver los borrados de un espejo *antes* de aprobarlos.
- **Examinar…** junto a la ruta remota abre un explorador del remoto (`rclone
  lsd`): entrar, subir y, si hace falta, **crear la carpeta** que falta. Se apaga
  cuando no hay conexión, igual que lo que toca el catálogo. La ruta local usa el
  diálogo de carpetas del sistema y se guarda relativa a la raíz del dispositivo.
- **Dispositivos…** enseña [la flota](como-funciona.md#el-modelo): todos los que comparten este
  catálogo, cuándo se les vio por última vez, **desde qué equipo** (el último
  ordenador donde se enchufaron) y cómo acabó su última pasada. Los que llevan
  más de una semana sin aparecer salen apagados. Debajo, la **ficha** del
  elegido: su versión, para qué plataformas sirve, desde cuándo falla si falla, y
  los últimos equipos donde ha estado, con **«· este equipo»** en el ordenador
  desde el que miras. Es solo de lectura para los nombres: el de **este**
  dispositivo se cambia en [«Nombre e icono de la unidad»](diagnostico.md#nombre-e-icono-de-la-unidad)
  y ningún dispositivo escribe la nota de otro.
- **Editar flags…** (en «Avanzado», junto a incluir y excluir) enseña las cuatro
  capas resueltas y avisa si un cambio sube el `--max-delete` efectivo.

Todo lo que escribe algo pasa antes por la misma ceremonia: un plan que todavía
no ha tocado nada, con una línea por consecuencia, y una confirmación.

## Actualizarse

Cuando hay una release nueva en GitHub, la ventana lo dice en un recuadro ámbar
y el botón lo resuelve: se descargan los ~270 KB del código de ese tag, se
verifican, se sustituye el programa del dispositivo y la ventana se reabre ya
con la versión nueva. **No se toca nada tuyo**: la configuración, las claves, el
estado de bisync, los filtros, los diarios, el rclone, el Python del dispositivo y
los lanzadores se quedan donde estaban. rclone y Python son componentes, no
código: el zip de la release no los lleva.

Si no quieres esperar a que la ventana mire por su cuenta (lo hace al abrirse y
como mucho una vez cada 24 horas), **«Ajustes… → Actualizaciones → Buscar
actualizaciones»** pregunta a GitHub en ese momento y te dice debajo del botón
si ya tienes la última o por qué no ha podido mirar. Si hay una versión nueva,
el mismo apartado pasa a enseñarla con su «Actualizar ahora», y el recuadro de
la ventana principal aparece al cerrar «Ajustes».

La versión instalada es el fichero `VERSION` de `.prdrive/`, y se compara con el
tag de la última release. Un dispositivo instalado antes de que esto existiera
no lo tiene, así que se lee como «desconocida» y se le ofrece la actualización,
que es justo lo que le hace falta.

Por dentro, el que instala es el código **recién descargado**, no el del
dispositivo:

```bash
python <descarga>/prdrive-install.py --update E:\    # lo que hace el botón
```

Y así porque `install/` no viaja al dispositivo a propósito: el zip sí lo trae,
de modo que la versión nueva se instala a sí misma y no hay una segunda copia
del manifiesto de qué se despliega que pueda quedarse atrás. Es el paso 5 del
asistente, sin el asistente.

Se pregunta **una vez al día**: la respuesta se guarda en `state/update.json` y
el aviso se pinta desde ahí, así que abrir la ventana no espera nunca a la red.
Sin conexión no pasa nada — se enseña lo último que se supo, o nada.

### Los componentes: rclone, el Python y el VeraCrypt del dispositivo

El programa es una cosa y los componentes otra. Cada release **fija** en
`common/pins.py` una versión exacta de rclone, una release exacta de
python-build-standalone y una versión del VeraCrypt Portable, y esos pines
viajan dentro del programa. Cuando el dispositivo lleva otros —porque se instaló
hace meses, o porque una release nueva movió los pines—, la ventana lo dice en
el mismo recuadro ámbar y el botón los sustituye.

Cómo se sabe qué lleva: cada componente deja escrito de dónde salió, en
`runtime/<plataforma>/PRDRIVE-RUNTIME`, en `bin/<arch>/<rclone>.PRDRIVE-RCLONE` y,
fuera del contenedor, en `VeraCrypt\PRDRIVE-VERACRYPT`. Hace falta porque un
binario no dice su versión sin ejecutarlo, y el de otra plataforma no se puede
ejecutar aquí. Un dispositivo anterior a esto no tiene el sello de rclone: se lee
**«no consta»**, que cuenta como pendiente, y la primera actualización lo deja
apuntado para siempre. El VeraCrypt sin sello de un dispositivo de antes es la
excepción: la ventana lo dice, pero no lo toca, porque su entrada de fuera solo
sabe abrir esa copia; se cambian los dos con **Añadir plataformas…**.

```bash
python <descarga>/prdrive-install.py --update-components E:\   # lo que hace el botón
```

- **Se descarga el zip de la versión INSTALADA**, no el de la última release: la
  maquinaria que baja y comprueba los componentes tiene que ser la de la versión
  que los fija.
- **Cada sustitución es un renombrado**, no una escritura encima. En ningún
  instante hay medio binario en `bin/`, que es el estado en el que el
  dispositivo no sincroniza en ningún equipo.
- **Lo que está en uso se pospone** y se dice cuál y por qué: un rclone
  sincronizando ahora mismo o un VeraCrypt que se está ejecutando desde la
  unidad.
- **El Python con el que está abierta la ventana se cambia con ella cerrada.**
  Cambiar la carpeta de un intérprete que está corriendo le borraría la
  biblioteca estándar debajo. Por eso el botón:
  1. lo avisa antes de empezar;
  2. extrae ese mismo Python en el temporal de este equipo;
  3. deja lanzado desde ahí un *relevo*.

  La ventana se cierra, y una ventanita va diciendo a qué espera y cuánto lleva
  copiado. El relevo sustituye el runtime del dispositivo y vuelve a abrir la
  ventana. En un USB tarda un par de minutos; no hace falta ningún Python
  instalado.
  - Si algo más corre desde ese Python (otra ventana de prdrive, o un aviso suyo
    olvidado detrás), lo dice antes de cerrar nada y con qué proceso.
  - Un segundo «Actualizar…» con un relevo en marcha no lanza otro.
  - Si algo sale mal, el relevo lo dice en una ventana con su registro.
- **Los restos de un intento cortado se barren**: un `runtime/.<plataforma>.nuevo-…`
  que dejó un proceso que ya no vive se borra la próxima vez.
- **No se instala ninguna plataforma nueva.** Para eso está «Añadir
  plataformas…» del asistente, que enseña los megas antes de bajarlos.
- No se tocan el programa, la configuración, las claves, el estado ni los
  lanzadores.

Sigue valiendo pasar el instalador por encima, que es lo mismo por otro camino.
