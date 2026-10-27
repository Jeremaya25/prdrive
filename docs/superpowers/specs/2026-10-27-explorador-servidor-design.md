# «Servidor…»: explorar el remoto desde la ventana — diseño

Fecha: 27/10/2026. Estado: **construido (pieza 1)**: `common/rcd.py`, `ui/servidor.py`,
`ui/tk_servidor.py` y el botón «Servidor…»; el diseño se aprobó en conversación. Falta probarlo en
una máquina real (`docs/superpowers/pruebas/2026-10-27-servidor-pendiente-en-real.md`). Es la
pieza 1 de tres; cada pieza tiene su spec, su plan y su PR.
Lo que hay hoy: el «Examinar…» de `remote_path` (`ui/remote_picker.py` +
`tk_pairs.explorador_remoto`, `docs/agents/reference/catalogue.md` «The remote folder picker»),
que recorre solo carpetas con `rclone lsd` y solo crea con `mkdir`.

## Por qué

El dueño quiere usar la conexión que ya tiene el dispositivo como un WinSCP: coger o dejar
archivos sueltos que no están en ninguna pareja, ordenar el servidor y ver cómo está el lado
remoto de lo que se sincroniza, sin instalar nada más en el equipo.

## Qué se quiere (las tres piezas)

1. **Explorar, solo lectura** (este spec): recorrer todo el remoto, carpetas y archivos, con
   tamaño, fecha y permisos, y ver qué carpetas son de una pareja. No escribe nada.
2. **Transferencias** (spec propio): bajar y subir archivos sueltos, con progreso y cancelación.
3. **Gestión** (spec propio): renombrar, mover y borrar. Es la delicada: tocar a mano el lado
   remoto de una pareja bisync se lee como cambios o borrados en la siguiente pasada, y el
   remoto es de toda la flota. Irá con `EditPlan` y `tk_pairs.confirmar_plan()`, como todo lo
   que borra o reescribe datos.

No se quiere en la pieza 1: escribir nada en el remoto, dos paneles, teclear una ruta, ni
sustituir el «Examinar…» de las parejas (sigue como está).

## Decisiones del dueño (27/10/2026)

1. **Alcance: todo el remoto, desde `/`**, como WinSCP y como el «Examinar…» que ya existe; lo
   que rclone pueda leer con esa conexión. Las carpetas de parejas se marcan aquí y se protegen
   en la pieza 3.
2. **Un panel**: solo el servidor. Bajar será «Guardar en…» del sistema y subir, elegir archivos
   (pieza 2). Descartado el doble panel local | servidor: el doble de ventana que mantener, y el
   disco ya lo enseña el explorador del sistema.
3. **Transporte: un `rclone rcd` vivo mientras el explorador está abierto**, hablándole por HTTP
   en `127.0.0.1`. Se prefirió a un `rclone` por acción (`lsjson` por `catalog.run()`, lo que
   hace el «Examinar…») porque cada carpeta reabriría la conexión (0,5–2 s por clic en SFTP), y
   porque la pieza 2 necesita progreso y cancelación, que `rcd` da con sus trabajos asíncronos.
   Descartado montar el remoto (`rclone mount`): exige WinFsp o FUSE en el equipo y rompe lo
   portátil.
4. **Columna de permisos ya, con «—» mientras rclone no los dé.** El backend SFTP de rclone
   v1.75.2 no expone `mode`/`uid`/`gid` (tabla de `rclone.org/overview`: SFTP, Metadata «-»).
   Está propuesto en el issue rclone/rclone#7310 (abierto desde 09/2023, *help wanted*) y lo
   implementa el PR rclone/rclone#9631 (abierto el 19/07/2026, pendiente de revisión de ncw, sin
   comentarios de mantenedores a 27/10/2026): solo lectura, sacado **del propio listado** («no
   extra round-trip»), con el formato del backend `local` (`mode` octal con los bits de tipo,
   `100600`, `40755`; `uid`/`gid` en decimal), detrás del `--metadata` de siempre. El código se
   escribe para ese formato y se activa solo (sección «Permisos») cuando una versión de rclone
   que lo traiga llegue a `RCLONE_VERSION`, sin tocar nada.
5. **Nada de consultas por carpeta para saber los permisos.** Si para tenerlos hace falta una
   consulta extra por entrada, no se piden y la columna dice «—».

## Piezas

### `common/rcd.py`: el `rclone rcd` vivo (sin Tk)

- `arrancar() -> Rcd`: limpia un huérfano anterior (ciclo de vida, cinturón 3), elige un puerto
  libre en `127.0.0.1` (abre un socket en el puerto 0, lee el que le ha dado el sistema y lo
  cierra; si `rcd` no puede escuchar en él, se reintenta una vez con otro), genera usuario y
  contraseña con `secrets.token_urlsafe(32)` y lanza
  `rclone rcd --config <model.RCLONE_CONF> --rc-addr 127.0.0.1:<puerto> <NET_FLAGS>`, con
  `cwd = model.APP_DIR` (el `rclone.conf` resuelve ahí `key_file` y `known_hosts_file`),
  `CREATE_NO_WINDOW` en Windows, `stdin=DEVNULL` y el usuario y la contraseña en
  `RCLONE_RC_USER`/`RCLONE_RC_PASS` (rclone lee cualquier flag de `RCLONE_<FLAG>`), **nunca en
  `argv`**, donde los vería cualquiera con `ps`. `NET_FLAGS` es el de `catalog.py`, importado, no
  copiado: una wifi mala da error en segundos y no en 5 minutos.
- `Rcd.esperar(tope=10)`: llama a `rc/noop` hasta que conteste o pase el tope. Si el proceso sale
  antes, lanza `ConfigError` con lo que rclone dijo por stderr.
- `Rcd.llamar(metodo, params) -> dict`: POST JSON a `http://127.0.0.1:<puerto>/<metodo>` con
  autenticación básica, por `urllib`. Una respuesta de error de rclone (`{"error": …}`, estado
  HTTP distinto de 200) lanza `ErrorRc(mensaje, estado)`; no poder conectar lanza
  `RcdCaido`.
- `Rcd.parar()`: `core/quit` y, si a los 2 s sigue vivo, `kill()`. Lo olvida de `store` y borra
  `state/rcd.json`. No lanza nunca.
- **Puntos de sustitución** (`commands-testing.md`, registro de indirecciones): `rcd.lanzar(orden,
  entorno) -> Popen` y `rcd.peticion(url, cuerpo, cabeceras, timeout) -> (estado, texto)`.
  Ningún test arranca rclone ni toca la red.

### `ui/servidor.py`: lo que decide la ventana (sin Tk ni disco)

- `Entrada(nombre, es_carpeta, tamano, fecha, modo)` congelada, de cada objeto de
  `operations/list` (el formato de `lsjson`: `Name`, `IsDir`, `Size`, `ModTime`, `Metadata`).
  Orden: carpetas primero, luego por nombre sin distinguir mayúsculas. Una entrada que no cuadre
  se ignora, como `remote_picker.parse_lsd()`.
- Navegación: `remote`, `ruta`, `entradas`; `entrar(nombre)`, `subir()`, `releer()`,
  `cambiar_remote(nombre)` (vuelve a `/`). Reutiliza `remote_picker.normalizar/subir/entrar`.
- **La última petición gana**: cada listado pedido lleva un número creciente y
  `recibir(numero, respuesta)` descarta una respuesta que no es la última pedida. La tabla nunca
  enseña la carpeta A con la ruta B arriba.
- **Remotes del desplegable**: los de `pairing.parse_rclone_conf()` del `rclone.conf` del
  dispositivo, sin los internos de prdrive (el `device_remote` `combine` de `[defaults]` y los
  `alias`), empezando por el de `[defaults].remote`.
- **La capa de parejas**: una carpeta cuya ruta completa es el `remote_path` de una pareja del
  config **en ese mismo remote** lleva `· pareja «Nombre»`. Estando dentro de una (la ruta actual empieza
  por un `remote_path`), el aviso «Estás dentro de la pareja «Nombre»». En la pieza 1 solo
  informa; en la 3 es lo que activa la protección.
- **«Sin acceso»**: una carpeta en la que entrar ha fallado por permiso (`ErrorRc` cuyo texto es
  de permiso: `permission denied`, el `SSH_FX_PERMISSION_DENIED` de SFTP, un 403 de WebDAV) queda
  marcada con candado mientras la ventana siga abierta. Se recuerda por `(remote, ruta)`.
- Textos y errores traducidos (`no such file`, `permission denied`, timeout, sin red) a frases en
  español; lo que no se reconoce se enseña tal cual lo dijo rclone.
- Permisos: sección propia, abajo.

### `ui/tk_servidor.py`: solo dibuja

- Barra: desplegable de remote, la ruta (texto, no editable), «↑», «Releer».
- `tk.Indicador` bajo la barra para «Conectando con el servidor…», los errores de listado y el
  aviso de «dentro de la pareja».
- La tabla es `tk.Tabla` (un solo lienzo, `tk_tabla`). Columnas: nombre (`CeldaIcono` carpeta o
  archivo; candado si «Sin acceso»; `· pareja «Nombre»` si es de una pareja), tamaño (legible, «—» en
  carpetas: SFTP no da el tamaño de una carpeta sin recorrerla), fecha de modificación en hora
  local, permisos.
- Doble clic o Intro entra en una carpeta; Retroceso o «↑» sube.
- Pie: «N elementos». En la pieza 1 no hay botones de «Bajar»/«Subir»: no se enseñan botones
  muertos.
- Sigue `ui.md`: colores, fuentes y glifos de `theme`/`icons`, distancias por `theme.medida()`,
  `import tkinter` dentro de funciones.

### La ventana principal

«Servidor…» junto a «Parejas…» y «Ajustes…» (`tk_principal`), con su icono en `icons`.
`principal.controles()` lo deja pulsar cuando el dispositivo tiene `rclone.conf` con al menos un
remote que no es interno. Si el import del explorador cuelga del botón, va en `ui.tk.PRECARGA`
(`tests/test_imports_perezosos.py`).

## Ciclo de vida del `rcd`

Es lo delicado del transporte elegido: un proceso que tiene abiertos el binario y
`rclone.conf` **del dispositivo** bloquea la expulsión si se queda colgado, sobre todo en
Windows.

- **Cuándo vive**: arranca al abrir «Servidor…», no con la ventana principal. Muere al cerrar el
  explorador. Hay uno por proceso de ventana; cerrar y volver a abrir arranca otro (alrededor de
  un segundo). No se deja vivo «por si acaso».
- **Cinturón 1, cierre ordenado**: se apunta con `store.apuntar_hijo()`, así que
  `store.matar_hijos()` lo corta al cerrar la ventana principal y **antes de expulsar**, igual
  que las lecturas de hoy.
- **Cinturón 2, la ventana muere de golpe**:
  - Windows: el hijo entra en un *Job Object* con `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`
    (`ctypes`: `CreateJobObjectW`, `SetInformationJobObject`, `AssignProcessToJobObject`). El
    handle del job lo guarda el proceso de la ventana; cuando muere, el sistema cierra el handle y
    mata el job.
  - Linux: `prctl(PR_SET_PDEATHSIG, SIGKILL)` en el hijo (`preexec_fn` con `ctypes`). **Esa
    señal salta cuando muere el hilo que lo lanzó, no el proceso**: el `Popen` se hace en el hilo
    de Tk (es instantáneo) y solo la espera a `rc/noop` va en segundo plano.
- **Cinturón 3, sobrevive uno**: `state/rcd.json` guarda el PID y su hora de creación
  (`store.creado()`), nunca la contraseña. Al arrancar otro, si ese PID sigue
  vivo **y** su hora de creación coincide (no es otro proceso que heredó el número), se mata con
  `store.matar_arbol()` (por eso se lanza como jefe de su sesión en POSIX); si no coincide,
  solo se borra el fichero. `--doctor` no lo toca: imprime el estado sin tocar nada.
- **Canal**: solo `127.0.0.1`; sin `--rc-web-gui` y sin `--rc-no-auth`. Con usuario y contraseña
  aleatorios que solo viven en memoria, otro usuario del equipo no puede usarlo para leer el
  `rclone.conf` (`config/dump`) ni el servidor.

## Navegar y fallar

- **Abrir** (regla #66 de `ui.md`: una pantalla que espera a la red se abre primero y lee
  después): la ventana sale enseguida, vacía, con «Conectando con el servidor…». El `Popen` va en
  el hilo de Tk; `esperar()`, el `operations/fsinfo` del remote (sección «Permisos») y el primer
  listado de `/`, en segundo plano. Con la respuesta se pinta la tabla.
- **Cada listado** es `operations/list` con `fs = "<remote>:/"` **siempre el mismo**, `remote =
  <ruta sin la barra inicial>` (`datos/notas`) y `opt = {noMimeType: true}` (más `metadata: true`
  según «Permisos»). El `fs` fijo es lo que hace valer el `rcd` vivo: rclone guarda en caché un
  objeto de remote por cadena `fs`, con su conexión SSH; un `fs = "remote:/datos/notas"` por
  carpeta abriría una conexión nueva en cada clic. Y es `remote:/`, la raíz absoluta, no
  `remote:`, que en SFTP es la carpeta de inicio (`remote_picker.normalizar()`). Sin recursión ni hashes, a
  través de `tk.Indicador` y no del `working()` modal: leer no deja nada a medias. Una carpeta de
  miles de entradas va en una sola petición; `tk_tabla` las pinta en un lienzo, sin paginar.
- **Un listado que falla** (no existe, permiso, timeout) deja la carpeta anterior en la tabla y
  pone el error en el indicador; si es de permiso, marca «Sin acceso». La ventana no se cierra.
- **`rcd` muerto** (`RcdCaido`): aviso con «Reconectar», que relanza `rcd` y repite la última
  petición. No se reintenta en silencio.
- **Sin red al abrir**: «No hay conexión con el servidor» con «Reintentar».
- **Cerrar**: `parar()` en segundo plano; la ventana se cierra sin esperarlo.

## Permisos (columna y candado previo)

**Cuándo se piden.** Al elegir un remote se pregunta una vez `operations/fsinfo` y se piden
permisos (`opt.metadata = true` en cada listado) **solo si**:
1. `Features.ReadMetadata` es verdadero, y
2. el tipo del backend (la línea `type =` de su sección en el `rclone.conf`; el `Name` de
   `fsinfo` es el nombre del remote, no su tipo) está en `LEE_PERMISOS_EN_EL_LISTADO =
   {"sftp", "local"}`, los backends cuyos metadatos salen del mismo listado. Un `crypt` sobre
   un SFTP es `crypt`: no se piden.

La condición 2 no es una lista de versiones: es lo que impide la consulta cara. Pedir `metadata`
a un backend que la lee **por objeto** (S3, con un `HEAD` por archivo) convertiría cada carpeta
en miles de peticiones. Ampliar la lista exige comprobar en el código de rclone que el backend
los saca del listado.

Con rclone v1.75.2, SFTP da `ReadMetadata = false`: no se piden y la columna dice «—» en todas
las filas. Cuando una versión con el PR rclone/rclone#9631 (o lo que lo sustituya) llegue a
`RCLONE_VERSION`, `fsinfo` dirá `true` y la columna se rellena **sin cambiar código**.

**Qué se enseña.**
- `Entrada.modo` es el `Metadata["mode"]` leído como octal (`"40755"` → `0o40755`); si falta o
  no se puede leer, `None`. Se lee **defensivamente**: un formato distinto del previsto da `None`
  y «—», nunca una excepción, porque el PR puede cambiar en la revisión.
- La columna enseña los 3 dígitos de permisos: `modo & 0o777` en octal, `755`, `700`. Sin modo,
  «—». Siempre visible, también con «—»: la ventana no cambia de forma con el backend.

**Candado previo** (avisar antes de entrar, no solo después de fallar).
- Necesita saber quién eres en el servidor. `mi_uid` se deduce del `uid` de la carpeta por
  defecto del backend (la de inicio en SFTP), que se pide una vez por remote junto a `fsinfo`
  cuando se piden permisos. Si no se puede saber, `None`.
- Una carpeta lleva candado previo **solo cuando es seguro** que no puedes entrar (entrar en una
  carpeta exige `r` y `x`):
  - eres el dueño (`uid == mi_uid`) y los bits de dueño no tienen `r` y `x`; o
  - no eres el dueño, ni los bits de grupo ni los de otros tienen `r` y `x`, y `mi_uid != 0`.
- Cuando depende del grupo (no eres el dueño, el grupo puede y otros no), **no** se marca: los
  grupos del usuario no se saben por SFTP. Se enseña solo el número.
- El candado después de fallar («Sin acceso») sigue igual con o sin permisos: es lo que funciona
  hoy.

**Lo que hay que comprobar cuando rclone lo traiga** (sube `RCLONE_VERSION`):
- que `operations/fsinfo` de un remote SFTP dice `ReadMetadata: true`;
- que `operations/list` con `opt.metadata` trae `Metadata.mode`/`uid`/`gid` con el formato de
  arriba **sin** más peticiones al servidor (`-vv --dump headers` o el log de SFTP del servidor:
  una sola apertura de directorio por carpeta);
- de dónde sale `mi_uid` con esa versión (`operations/stat` de la raíz del remote);
- si algo de esto falla, la regla de «Cuándo se piden» deja la columna en «—» y no se rompe nada.

## Pruebas

Ningún test arranca rclone ni toca la red: se sustituyen `rcd.lanzar()` y `rcd.peticion()`.

- `tests/test_rcd.py`: arrancar espera a `rc/noop` y respeta el tope; un proceso que sale antes
  da `ConfigError` con su stderr; usuario y contraseña en el entorno y **no** en `argv`; escucha
  en `127.0.0.1`; `parar()` hace `core/quit` y luego `kill`; queda apuntado en `store`; un
  `state/rcd.json` viejo se mata solo si coinciden PID y hora de creación, y nunca guarda la
  contraseña; las ramas del Job Object y de `PDEATHSIG` se fuerzan con `IS_WIN` o dicen
  `(saltado) …`; el `Popen` se hace en el hilo que llama.
- `tests/test_servidor.py` (sin pantalla): `operations/list` → entradas, orden y fechas; la marca
  la marca de pareja solo en el mismo remote y el aviso de «dentro de la pareja»; el desplegable sin
  `combine` ni `alias`; la respuesta vieja descartada; la traducción de errores y «Sin acceso»;
  permisos: cuándo se piden (`ReadMetadata` falso, backend fuera de la lista, S3 con
  `ReadMetadata` verdadero → no), `mode` con el formato del PR (`100600`, `40755`) y formatos
  raros → `None` → «—», y la tabla del candado previo (dueño, grupo, otros, root, `mi_uid`
  desconocido).
- `tests/test_tk_servidor.py`: la ventana abre antes de leer, el indicador, las filas de la
  tabla, «—» en la columna de permisos, «Reconectar». Las ventanas corren en el CI (Linux y
  Windows), no en local.
- `tests/test_principal.py`: cuándo se puede pulsar «Servidor…».
- `tests/test_reglas_claude.py`: el doc de área nuevo y su regla.
- **Pendiente en máquina real** (`docs/superpowers/pruebas/`, skill `real-machine-tests`):
  matar la ventana a la fuerza y comprobar que `rcd` muere (Windows y Linux); expulsar la unidad
  tras cerrar el explorador; otro programa que coge el puerto elegido; un SFTP real con carpetas
  sin permiso (candado tras fallar); que `opt.metadata` contra SFTP v1.75.2 no rompe ni ralentiza
  el listado; que navegar varias carpetas usa **una** conexión SSH (el log de `sshd`: un solo
  inicio de sesión) y el tiempo por clic frente al «Examinar…» de hoy.

## Documentación

- Doc de área nuevo `docs/agents/reference/servidor.md`, su fila en la tabla de `AGENTS.md` y su
  regla en `.claude/rules/` (skill `new-area-doc`). Cubre `common/rcd.py`, `ui/servidor.py` y
  `ui/tk_servidor.py`.
- `commands-testing.md`: los puntos de sustitución nuevos.
- `docs/guia/`: una página para quien usa el dispositivo, «Ver lo que hay en el servidor».
- El título de la PR es texto de la versión, en español y para quien usa el dispositivo.

## Qué pasa con los dispositivos que ya están en uso

Nada cambia hasta que se actualizan. Tras actualizar sale el botón «Servidor…»; el
`rclone.conf`, el config y las parejas no se tocan. Explorar no escribe en el remoto.
