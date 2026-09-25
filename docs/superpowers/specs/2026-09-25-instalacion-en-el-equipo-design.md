# Instalación en el equipo: prdrive residente

Fecha: 2026-09-25 · Estado: **borrador**, sin implementar · Versión objetivo: 0.4.0

## Qué se pide

Un tercer tipo de instalación, además de «unidad sin cifrar» y «unidad cifrada»:
**prdrive instalado en el ordenador**, que corre en segundo plano de forma
eficiente, hace todo lo que hoy hace `runsync` y deja sitio a funciones futuras.

## Decidido al plantearlo

- **Las dos cosas.** El programa residente sincroniza **sus propias parejas**
  (carpetas del equipo ↔ remoto) **y atiende a cualquier unidad prdrive** que se
  enchufe en ese equipo.
- **Icono en la bandeja**: estado, «Sincronizar ahora», «Abrir», «Pausar».
- **Windows y Linux** desde la primera versión.
- En la v1 entran tres de las mejoras de eficiencia: **un proceso en vez de N**,
  **moderarse** (batería, red de uso medido, sin conexión, espera creciente tras
  un fallo) y **avisos nativos** del sistema en lugar de la ventanita Tk.
  Reaccionar a cambios en los ficheros queda para después.

## La idea

> Un prdrive cuya «unidad» es una carpeta del equipo, y un proceso residente,
> **el agente**, que la atiende a ella y a las unidades que se enchufen.

La primera mitad no cuesta casi nada, porque el motor no sabe que está en un
USB: `model.APP_DIR` es `Path(__file__).parent.parent` y `DEVICE_ROOT` es su
padre. Una carpeta `~/PRDRIVE/` con `.prdrive/` dentro es, para `sync.py`,
`bisync.py`, `revision`, `fleet` y la ventana, **un dispositivo más**. Así el motor
sigue siendo uno, que es la regla de este proyecto.

La segunda mitad es lo nuevo: `agente.py`, que sustituye en ese equipo a
`penwatch.py` y al servicio que hoy arranca desde la unidad.

## 1. La raíz en el equipo

```
~/PRDRIVE/                 (C:\Users\<u>\PRDRIVE en Windows) = DEVICE_ROOT
├── .prdrive/              oculto, la misma estructura que en una unidad
│   ├── PRDRIVE            fichero de control: id=… y además tipo=equipo
│   ├── runtime/<clave>/   solo la plataforma de este equipo, y es obligatorio
│   ├── bin/<arch>/        rclone
│   ├── rclone.conf, keys/ la clave, en el perfil del usuario
│   └── state/             el del motor + agente.json + agente.lock.json
├── obsidian/              las parejas, relativas a la raíz como en una unidad
└── …
```

- **`tipo=equipo`** en el fichero de control. Así el agente, el asistente y la
  flota saben qué es sin adivinarlo, y un `penwatch` viejo ignora la línea: solo
  lee `id=`. La raíz no es la raíz de un volumen, así que `candidate_roots()`
  nunca la confunde con una unidad enchufada.
- **La carpeta de las parejas es la raíz, y solo la raíz** (v1). La regla de
  `pair_editor.ruta_local_relativa()` no cambia: una pareja no sincroniza nada que
  esté fuera. La pregunta abierta 1 plantea la alternativa (la raíz = `~`).
- **La pareja de la raíz entera (`local = "."`) queda prohibida en un equipo.**
  En una unidad es raro. Aquí sería el mismo `.prdrive/` con la clave dentro.
- **La clave vive en el disco del equipo.** No pasa por el paso «Cifrado» (no hay
  contenedor que crear). El asistente lo dice en un bloque ámbar y enseña si el
  disco del sistema tiene BitLocker en estado `On`, con la misma lectura que ya
  hace `install/crypto.py`. Es solo informativo: no lo exige.

## 2. El agente (`agente.py`)

Es un proceso por usuario, arrancado al iniciar sesión, **sin Tk**, que corre con
el runtime propio de la raíz del equipo. Hace esto:

1. **Planifica.** `common/planificador.py` es **puro**, sin reloj ni disco
   propios: recibe raíces, parejas, últimos resultados, intervalos, estado de
   energía y red, y la hora, y devuelve qué toca ahora y cuándo volver a mirar.
   Se prueba sin procesos.
2. **Una cola para todo el equipo:** una pasada a la vez, sea de la raíz o de
   una unidad. Ahorra ancho de banda y evita algo que hoy puede pasar: una pareja
   del equipo y la misma pareja en la unidad enchufada, las dos contra el mismo
   `remote_path` a la vez.
3. **Cada pasada sigue siendo un `sync.py` hijo**, uno por pareja, lanzado con el
   Python del agente:
   - **La unidad ejecuta su propio código.** Una unidad puede traer otra versión
     que el agente, y sus listados y su `sync_config.toml` los escribió su propio
     `sync.py`. Ejecutar el `.prdrive/sync.py` de la unidad (con el rclone de la
     unidad, que resuelve él solo) mantiene el contrato actual. Meter ese código
     en el proceso del agente no lo mantiene.
   - **Aislamiento:** un rclone colgado o un fallo del motor no tumba la bandeja.
   - Arrancar un Python cuesta unas décimas. Solo listar el remoto a rclone ya le
     cuesta segundos.
   - **Con el Python del equipo, no con el de la unidad**, para que no quede nada
     sujetando la unidad entre pasadas y se pueda expulsar. Hoy el servicio es un
     `pythonw.exe` que corre **desde** `.prdrive/runtime/` y solo lo compensa con
     `chdir` a temp.
4. **Detecta unidades sin recorrerlas cada 5 s.**
   - En Windows, `WM_DEVICECHANGE` en la ventana oculta que la bandeja necesita de
     todas formas, y a partir de ese aviso una racha de sondeos: el volumen
     cifrado se puede leer bastante después del aviso, que es por lo que penwatch
     sondea.
   - En Linux, `select.poll()` sobre `/proc/self/mountinfo` (`POLLPRI` al cambiar
     los montajes).
   - En los dos, un sondeo lento de respaldo. Recorrer las unidades es siempre
     `penwatch.candidate_roots()`, importado igual que lo hace `ui/watch.py`, así
     que el proyecto sigue teniendo un único recorrido.
5. **La ventana es un proceso aparte, bajo demanda.** «Abrir» lanza el
   `runsync.py` de la raíz, o el de la unidad, como hijo. El agente no carga Tk
   nunca: el intérprete Tk residente son decenas de MB, y todo lo que hoy se sabe
   de hilos e intérpretes Tk (`avisar_fallo`, `Tcl_AsyncDelete`) sigue en la
   ventana, donde ya está resuelto.

**Lo que significa «un proceso en vez de N»**, medido en procesos vivos:

| | Hoy (unidad + penwatch) | Con el agente |
|---|---|---|
| Siempre vivo | `penwatch` (pythonw, sondeo cada 5 s) + un servicio por unidad (pythonw **desde la unidad**, sondeo cada 2 s) | **el agente** (pythonw del equipo) |
| Durante una pasada | `sync.py` + rclone por pareja | lo mismo, de uno en uno en toda la máquina |
| Al fallar | un intérprete Tk en un hilo del servicio | un aviso nativo, sin Tk |

Queda para una fase posterior ejecutar en el propio proceso las parejas **de la
raíz del equipo**, que sí tienen la misma versión que el agente, y un rclone
residente (`rclone rcd`). La v1 no los necesita, y el segundo abre un puerto,
cosa que el proyecto evita hoy.

## 3. Unidades enchufadas: el agente cumple el contrato del servicio

Para una unidad, el agente **hace de su servicio** con los mismos ficheros que ya
existen en su `state/`. Por eso funciona con unidades que llevan código viejo.

- Mientras atiende una unidad escribe su `daemon.lock.json` (pid y host del
  agente, las parejas, el ciclo), así que la ventana de la unidad, el menú de
  consola y cualquier `penwatch` ven un servicio en marcha, que es lo que hay.
- Obedece `daemon.stop`, que es lo que hace `runsync` al abrir su ventana: acaba
  la pareja en curso, suelta el lock, borra el `.stop` y **deja esa unidad en
  pausa** mientras haya un `ui.lock.json` vivo de este equipo.
- Al cerrarse la ventana: si ha arrancado su propio servicio (hay un
  `daemon.lock.json` con otro pid vivo), el agente **se aparta**. La regla es un
  servicio por unidad, el que tenga el lock. Si no lo ha arrancado, el agente
  vuelve a atenderla.
- **Qué unidades atiende:** una lista explícita de ids en `agente.json`, cada uno
  con su modo al enchufar. Son los tres de penwatch (`ui`, `daemon`, `sync`)
  más `nada`. Una unidad prdrive que no está en la lista provoca un aviso («Se ha
  conectado PRDRIVE-2. ¿Atenderla en este equipo?») y nunca se sincroniza sin
  preguntar.
- **Las parejas y el intervalo siguen siendo de la unidad** (`ui_prefs.json` >
  `[daemon]`, `prefs.startup_defaults()`). En el equipo solo se guarda lo que es
  del equipo, igual que decidió el issue #14.
- **Cifradas con VeraCrypt:** el vestíbulo y `open_container()` se reutilizan
  tal cual, una vez por conexión, como en penwatch.
- **Sustituye a penwatch en ese equipo.** Instalar el agente importa el
  `device_id` y el modo de `watch.json` a la lista y desinstala penwatch, y lo
  dice. `penwatch` sigue existiendo para los equipos sin agente.

## 4. Bandeja y avisos (`ui/bandeja.py`, `ui/avisos.py`)

Todo con la biblioteca estándar: ctypes en Windows y el protocolo D-Bus en Linux.

- **Windows:** `Shell_NotifyIconW` sobre una ventana oculta de solo mensajes, con
  su bucle en un hilo propio. El menú va con `TrackPopupMenu`. Los avisos son
  `NIF_INFO`, que en Windows 10/11 salen como notificación del sistema sin
  registrar un AppUserModelID. El icono lo pinta `icons.py` en cuatro estados
  (bien, sincronizando, aviso, en pausa) y se carga con `LoadImageW` desde un
  `.ico` repintado, nunca copiado.
- **Linux, avisos:** `org.freedesktop.Notifications.Notify`. Sin D-Bus, el aviso
  se queda en el diario, que es la misma caída que tiene hoy `avisar_fallo()`.
- **Linux, bandeja:** es **la parte con más riesgo del plan**. La norma actual es
  StatusNotifierItem, y exige *exportar* un objeto en el bus: autenticación
  EXTERNAL, serialización, propiedades y señales. Serían unas 600-900 líneas de
  cliente D-Bus propio, con el mismo espíritu que `ui/qr.py`. Además, **GNOME no
  tiene bandeja** sin la extensión AppIndicator: Ubuntu la trae y Fedora no.
  «Paridad» significa, por tanto, **las mismas funciones**, pero no siempre la
  misma superficie. Sin bandeja quedan un lanzador `.desktop` «prdrive» que abre
  la ventana y los avisos con el estado.
- **La ventana de la raíz del equipo** cambia la línea del vigilante por la línea
  del agente, que dice qué atiende y si está en pausa. Su «Iniciar servicio» deja
  de lanzar un servicio y se lo pasa al agente: escribe `ui_prefs.json` como
  hoy, más `state/servicio.pide`, que el agente sondea igual que `daemon.stop`.
  Sin puertos, como el resto de la coordinación.

## 5. Moderarse

El planificador lo recibe todo como datos. Cada sonda es un punto de indirección
de módulo:

- **Batería:** en Windows `GetSystemPowerStatus` y en Linux
  `/sys/class/power_supply/*`. Por defecto sincroniza con batería y **se para por
  debajo del 20 %**.
- **Red de uso medido:** en Windows `INetworkCostManager` (COM por vtable, igual
  que ya se hace con `IShellItem2`) y en Linux la propiedad `Metered` de
  NetworkManager. Por defecto **se pausa**. «Sincronizar ahora» siempre se salta
  esta moderación.
- **Sin conexión:** si un fallo es de red (una categoría nueva en
  `KNOWN_ERRORS`), todo lo que va a **ese remoto** pasa a «sin conexión». Se
  sondea con `catalog.run()` + `NET_FLAGS` en vez de lanzar pareja tras pareja
  para que fallen igual. Al volver de la suspensión (`WM_POWERBROADCAST`) se mira
  enseguida.
- **Espera creciente por pareja:** `intervalo · 2^k` tras k fallos seguidos, con
  un tope de 4 h, y vuelve a cero tras una pasada buena. Los avisos siguen la
  regla actual: se avisa cuando una pareja **empieza** a fallar, no en cada
  ciclo.
- Nada de esto hace un `--resync` solo. Una pareja que lo pide se salta, igual
  que hoy con `stdin=DEVNULL`, y la bandeja lo cuenta como aviso.

## 6. Instalación

El asistente gana una primera pregunta: **«¿Dónde?» → «En una unidad» (lo de
hoy) / «En este equipo»**. El recorrido nuevo es otra lista de pasos
(`PASOS_EQUIPO`), como ya lo son `PASOS_ACTUALIZACION` y `PASOS_PLATAFORMAS`:

```
1 Carpeta         dónde va la raíz (por defecto ~/PRDRIVE); ¿ya es un prdrive?
2 Conexión        igual
3 Comprobaciones  igual
4 Instalación     .prdrive/ + rclone + runtime de ESTA plataforma, sin elegir
5 Parejas         igual, y las rutas por debajo de la carpeta
6 Inicialización  --resync de las bisync
7 Unidades        qué unidades de la flota atiende y cómo (lista de devices/)
8 Arranque        registrar el agente al iniciar sesión y arrancarlo
9 Verificación
```

- **Registro:** en Windows, la tarea programada por usuario de penwatch, con las
  mismas trampas ya resueltas (XML en UTF-16, `DisallowStartIfOnBatteries=false`,
  `ExecutionTimeLimit=PT0S`), que se saca a una función con el comando como
  parámetro. En Linux, **autostart XDG** en vez de la unidad systemd: una bandeja
  necesita el bus de la sesión gráfica, y `enable-linger` no se lo da.
- **Una sola instancia por usuario** con `agente.lock.json` y `pid_alive()`, con
  el mismo criterio que `ui.lock.json`.
- **Desinstalar** quita el registro y el agente, y **nunca borra la carpeta**,
  por la misma razón que re-cifrar no borra el árbol en claro.

## 7. Actualizaciones

- **El código:** `prdrive-install.py --update <raíz>` sirve sin tocarlo, porque
  la estructura es la misma. Lo nuevo es que el agente debe reiniciarse: la
  bandeja ofrece «Actualizar», deja de atender, lanza el aplicador descargado y
  se vuelve a lanzar.
- **El runtime:** el agente corre desde `runtime/<clave>/`, así que el
  intercambio de `install_runtime()` fallaría con `runtime_en_uso`. Se usa el
  patrón que penwatch ya resolvió: **un directorio por versión que nunca se
  cambia en sitio**. Se copia al lado, se apunta el puntero de forma atómica, se
  vuelve a registrar, se reinicia y se podan los directorios viejos.

## 8. Flota

La nota de la raíz del equipo lleva `tipo = "equipo"`. `fleet.parse()` ya ignora
las claves que no conoce, así que las versiones viejas la leen sin romperse, y la
ventana de la flota le pone una etiqueta. `equipos` será siempre el mismo host, y
está bien que sea así.

## Invariantes que no se tocan

- `_bisync_preflight()`: si hay línea base y no hay carpeta local, se aborta. En
  un equipo esto es **más** importante que en una unidad: mover o renombrar
  `~/PRDRIVE` es fácil.
- Los `max-delete`, el prefijo de sesión y `device_remote` no cambian. La raíz del
  equipo usa `disp`, como cualquier dispositivo.
- Un `--resync` nunca se lanza sin nadie delante.
- `penwatch.py` sigue sin importar nada del proyecto, y el agente importa de
  penwatch, nunca al revés.
- `tk_*` solo dibuja. `agente.py`, `planificador`, `bandeja` y `avisos` no
  importan tkinter.

## Qué cambia para las unidades que ya están en uso

Nada, mientras no se instale el agente. Cuando se instala:

- Una unidad con código viejo funciona gracias al contrato de la sección 3.
- **El único cambio que se nota:** con el agente, **abrir la ventana de la unidad
  ya no apaga el servicio para siempre**. Lo pausa mientras la ventana está
  abierta. Para pararlo, se usa «Pausar» en la bandeja. Hay que decirlo en el
  README y en `device-readme.md`.

## Preguntas abiertas

1. **¿La raíz es una carpeta dedicada (`~/PRDRIVE`) o la carpeta personal
   (`~`)?** Con la dedicada, el límite queda claro y nada de fuera se toca: es el
   modelo de Dropbox. Con la carpeta personal se puede sincronizar
   `~/Documentos/Obsidian` sin moverlo, pero se pierde ese límite y muchas parejas
   del catálogo (`sync-data/…`) caerían sueltas en `~`. **Propuesta: dedicada en
   la v1.**
2. **¿Una instalación en el equipo sin parejas propias**, es decir, solo el
   agente atendiendo unidades? Hoy `parse_config()` rechaza un config sin
   `[[pair]]`. **Propuesta: permitirlo solo con `tipo=equipo`.**
3. **¿Cuánto espera el aviso de «unidad nueva»** antes de dar la respuesta por
   «no»?
4. **Bandeja en Linux:** ¿se acepta el cliente D-Bus propio, o basta en la v1 con
   el lanzador y los avisos?

## Fases

Cada fase se puede publicar por separado y deja el proyecto funcionando:

1. **La raíz en el equipo**: `tipo=equipo`, `PASOS_EQUIPO` (sin agente) y el
   servicio actual de `runsync --auto` registrado al iniciar sesión. Ya sirve y
   no pide nada nuevo del motor.
2. **El agente sin bandeja**: el planificador, la cola, el contrato de la
   sección 3, las unidades atendidas, la sustitución de penwatch, la moderación y
   los avisos nativos.
3. **Bandeja en Windows**, con la detección de unidades por `WM_DEVICECHANGE`
   montada sobre su ventana.
4. **Ventana ↔ agente**: la línea del agente, `servicio.pide`, «Actualizar» y el
   reinicio, y el runtime por versión.
5. **Bandeja en Linux** (StatusNotifierItem) con la caída al lanzador.

Para después: parejas de la raíz ejecutadas en el propio proceso, reaccionar a
los cambios de ficheros, `rclone rcd` y sincronizar la unidad con el equipo sin
pasar por el remoto.

## Pruebas

- `test_planificador.py`: tabla de casos con un reloj de prueba (espera
  creciente, batería, red de uso medido, sin conexión, cola única,
  «Sincronizar ahora»).
- `test_agente_contrato.py`: raíces falsas con `daemon.lock.json`,
  `daemon.stop` y `ui.lock.json` escritos como lo haría un `runsync` viejo.
  Comprueba la pausa, el apartarse ante otro servicio y la vuelta.
- Registro: el texto del XML y del `.desktop`, como ya hace penwatch. Se
  comprueba también que penwatch sigue sin importar el proyecto.
- `test_tk_medidas.py` cubre los pasos nuevos del asistente.
- La bandeja y los avisos se sustituyen en todos los tests. La prueba de verdad
  se hace en Windows y Linux reales y se apunta en `docs/superpowers/pruebas/`,
  como la de VeraCrypt.
