# «Servidor…»: nueva carpeta, renombrar, mover y borrar en el servidor — diseño

Fecha: 27/10/2026. Estado: **construida** (código, pruebas automáticas y guía); las pruebas en máquina real (filas G1 a G5 de `docs/superpowers/pruebas/2026-10-27-servidor-pendiente-en-real.md`) están por hacer. Es la pieza 3 de tres del explorador
del servidor. La pieza 1 (explorar, solo lectura) está en la 0.8.0
(`docs/superpowers/specs/2026-10-27-explorador-servidor-design.md`) y la pieza 2 (bajar y subir)
en la 0.8.1 (`docs/superpowers/specs/2026-10-27-servidor-transferencias-design.md`); las dos
están contadas en `docs/agents/reference/servidor.md`.

## Por qué

Con las piezas 1 y 2 se ve el servidor y se copia en los dos sentidos, pero ordenarlo (crear
una carpeta antes de subir, cambiar un nombre, llevar algo a otra carpeta, quitar lo que sobra)
sigue pidiendo otro programa. Esta pieza lo añade al mismo explorador. Es la delicada: tocar a
mano el lado remoto de una pareja lo ve su siguiente pasada como cambios o borrados, y lo que
se borra en el servidor se borra para siempre.

## Qué se quiere

- **Nueva carpeta** en la carpeta que se ve.
- **Renombrar** un archivo o una carpeta.
- **Mover** uno o varios elementos a otra carpeta del mismo servidor, con cortar y pegar.
- **Borrar** uno o varios elementos, sabiendo antes cuánto hay dentro.
- Que nada pise algo que ya existe, que la raíz de una pareja y la carpeta del catálogo no se
  puedan romper desde aquí y que, dentro de una pareja, se diga qué hará su próxima pasada.

No se quiere: papelera (SFTP no la tiene; borrar es para siempre y se dice), arrastrar y soltar
(Tk no lo trae sin `tkdnd`), copiar dentro del servidor, mover entre remotes distintos, ni leer
el catálogo para proteger las parejas de otros dispositivos (decisión 6).

## Decisiones del dueño (27/10/2026)

1. **Las tres más «Nueva carpeta»**: nueva carpeta, renombrar, mover y borrar.
2. **Parejas: bloquear la raíz, avisar dentro.** Renombrar, mover o borrar la carpeta raíz de
   una pareja (o una que la contenga) se bloquea, en todos los modos. Dentro de la carpeta de
   una pareja se puede, y la pantalla de confirmación dice con las palabras del modo qué hará
   la próxima pasada.
3. **Mover es cortar y pegar** en la misma ventana: «Cortar», navegar, «Pegar aquí». Solo
   dentro del mismo remote.
4. **Borrar cuenta antes lo que hay dentro**: «Se borrará para siempre: «fotos» con 1 234
   archivos (3,4 GB)…».
5. **Cada acción es un lote que sigue la máquina de la pieza 2**: el mismo panel de abajo,
   «Cancelar», un lote a la vez, la pregunta al cerrar. Nada de llamadas síncronas de 60 s.
   **Revisada tras la prueba** (abajo): el lote no es un `job/batch` sino **un trabajo
   asíncrono por elemento, lanzados uno tras otro** desde la ventana, todos en el mismo grupo de
   estadísticas. «Cancelar» para antes del elemento siguiente; el que va acaba (rclone no para un
   borrado a medias).
6. **Se protegen las parejas de este dispositivo y la carpeta del catálogo; el catálogo no se
   lee.** Una pareja que solo tiene otro dispositivo no se conoce aquí: queda como límite
   conocido, dicho en la guía.

## Lo comprobado con rclone v1.75.2 (contra `rclone serve sftp` local, 27/10/2026)

- `sync/move` de una carpeta a un destino que **no existe** es un renombrado en el servidor:
  301 archivos en 22 ms y el mismo inodo. Con el destino existente rclone mezcla archivo a
  archivo y pisa; por eso nunca se lanza contra un destino que existe.
- `operations/movefile` sirve para renombrar y mover un archivo. **Trampa:** contra un destino
  que ya existe y que rclone cree igual (mismo tamaño y fecha) **borra el origen sin escribir
  nada**. Otra razón para comprobar antes que el nombre está libre.
- `operations/mkdir` sobre una carpeta que ya existe **no falla**: la comprobación de que el
  nombre está libre es nuestra.
- `operations/purge` borra una carpeta con todo lo de dentro; `operations/deletefile`, un
  archivo; un archivo que no existe da 404 «object not found».
- `operations/size` (`fs` + `remote`) da `{"count", "bytes"}` de una carpeta en una llamada.
- `job/batch` con `_async: true`, `_group` y `concurrency: 1` corre varias órdenes como **un**
  trabajo: un `jobid`, `job/status` con `output.results` (uno por orden, `{}` si fue bien o
  `{"error", "status", "input", "path"}` si no). **`success` es `true` aunque falle una orden**:
  el resultado se lee de `output.results`. `core/stats` del grupo cuenta `renames`, `deletes`,
  `deletedDirs` y `transfers`.
- **`job/stop` no para un `job/batch`**: con un `purge` de 20 000 archivos en marcha, tras el
  `job/stop` el `purge` acabó de borrarlos todos y **la orden siguiente se ejecutó igual**.
  Por eso no se usa `job/batch` (decisión 5 revisada).
- **Un borrado no se para a medias**: `job/stop` de un `operations/purge` asíncrono suelto deja
  que borre los 20 000 archivos y solo falla al final («failed to rmdirs: context canceled»);
  `operations/delete` hace lo mismo. «Cancelar» solo puede no empezar el elemento siguiente.

## Cómo se ve y cómo se usa

**Dónde.** Una barra encima de la lista con «Nueva carpeta…», «Renombrar…», «Cortar» y
«Borrar…». Las mismas acciones y «Pegar aquí» en el menú del botón derecho, y con teclas: F2
(renombrar), Supr (borrar), Ctrl+X (cortar), Ctrl+V (pegar aquí), Ctrl+Mayús+N (nueva carpeta).
El pie queda como está: «Bajar…», «Subir archivos…», «Subir carpeta…», «Cerrar».

**Cuándo se encienden** (siempre con conexión y sin un lote en marcha, como los de la pieza 2):
«Nueva carpeta…» siempre; «Renombrar…» con exactamente una fila elegida; «Cortar» y «Borrar…»
con una o varias. El botón derecho sobre una fila no elegida la elige primero.

**Nueva carpeta… y Renombrar…** abren un diálogo pequeño con un campo. Al renombrar un archivo
el nombre sale elegido sin la extensión (lo de antes del último punto, si el punto no es el
primer carácter). Se rechaza, con el motivo bajo el campo y «Aceptar» apagado:

- un nombre vacío o solo de espacios;
- uno con `/`;
- `.` o `..`;
- uno que ya existe en la carpeta, sin distinguir mayúsculas (`casefold()` en los dos lados,
  como los choques de la pieza 2). Cambiar solo las mayúsculas del propio elemento
  (`foto.jpg` → `Foto.jpg`) sí vale; el mismo nombre exacto no hace nada.

El nombre se usa tal cual (no se recortan espacios por dentro ni por los lados salvo el caso de
solo espacios: un nombre con un espacio al final es válido en el servidor).

**Cortar → Pegar aquí.** Tras «Cortar» aparece encima de la lista una línea: «3 elementos para
mover desde /datos/fotos · Pegar aquí · Cancelar» (singular con uno). Se mantiene al navegar.
«Pegar aquí» mueve lo cortado a la carpeta que se ve. Se rechaza, con un aviso, y la línea
sigue:

- en la misma carpeta de donde salió («Ya están en esta carpeta.»);
- dentro de una carpeta cortada o de algo suyo («No se puede mover una carpeta dentro de sí
  misma.»);
- con algo del mismo nombre en el destino («Ya hay «x» en /destino: renómbralo antes.»; con
  varios, el primero y cuántos más). Nunca se pisa.

En otro remote «Pegar aquí» está apagado y la línea dice «Solo se puede pegar en el mismo
servidor.». Cambiar de remote **no** quita lo cortado (al volver al remote del corte, «Pegar
aquí» se enciende otra vez); lo quitan «Cancelar», cortar otra cosa y un pegado que llegó a
lanzar alguna orden (acabe bien, mal o cancelado). Un pegado cuyo destino no se pudo leer deja lo
cortado, y su «Reintentar» solo actúa si lo cortado sigue igual. «Cancelar» de la línea está
apagado mientras corre un cambio.

**Borrar…** primero cuenta lo de dentro (en segundo plano, «Mirando qué hay dentro…» en la
línea de la ventana; un `tamano()` por carpeta elegida) y luego abre la pantalla de
confirmación (`tk_pairs.confirmar_plan()`, título «Borrar del servidor», nota «El servidor no
tiene papelera.») con una línea por elemento: «Se borrará para siempre «fotos», con 1 234
archivos (3,4 GB).» y «Se borrará para siempre «leeme.txt» (12 KB).». Si contar falla, se
dice en el panel con «Reintentar» y no se borra nada.

**Mientras corre.** El panel de la pieza 2, con su título («Borrando en /datos…», «Moviendo a
/x…», «Renombrando «a» a «b»…», «Creando la carpeta «n»») y «Cancelar». El panel solo sale si el
trabajo sigue vivo tras el primer sondeo; si acabó antes, el resultado va a la línea de la
ventana («Renombrado a «Foto.jpg».») sin enseñar el panel. Al acabar (bien, mal o cancelado) se
relee la carpeta que se ve y, si sigue a la vista, queda elegido lo nuevo (la carpeta creada,
el nombre nuevo, lo pegado).

## Parejas y catálogo

Cada acción toca rutas del servidor, divididas en **las que salen** y **las que llegan**:

| Acción | Salen | Llegan |
|---|---|---|
| Borrar | cada elemento | — |
| Renombrar | el nombre viejo | el nombre nuevo |
| Mover (pegar) | cada elemento en su carpeta de origen | cada elemento en la carpeta de destino |
| Nueva carpeta | — | la carpeta nueva |

Se comparan con las parejas del **mismo** `remote_name` de `config.pairs` (la del llavero
incluida), por tramos de ruta, nunca por prefijo de texto, con `remote_picker.normalizar()` como
ya hacen `marca()`, `dentro_de()` y `transferencia.afectadas_subida()`.

**Se bloquea** (un aviso dice por qué y no pasa nada) si alguna ruta tocada, de las que salen o
de las que llegan:

1. **es la raíz de una pareja o la contiene** (`remote_path` igual a la ruta o por debajo de
   ella). Incluye renombrar otra carpeta al nombre de la raíz de una pareja que aún no existe:
   su próxima pasada la tomaría como suya;
2. **es la carpeta del catálogo, la contiene o está dentro de ella**:
   `model.carpeta_del_catalogo(defaults)` en el remote del catálogo, con `remote.toml` y el
   `keychain/` del llavero;
3. **llega dentro de una pareja `up-mirror`** (mover allí o crear una carpeta): su próxima
   pasada la borraría del servidor, y al mover el original ya no estaría en ninguna parte.

**Se avisa** si no hay bloqueo y alguna ruta está dentro de una pareja (la más honda, como en la
pieza 2: todas las que comparten esa carpeta). Una línea por pareja y lado en la pantalla de
confirmación:

| Modo | Algo sale de la pareja | Algo llega a la pareja |
|---|---|---|
| bisync | «La próxima pasada de «X» lo quitará también del dispositivo.» | «La próxima pasada de «X» lo copiará al dispositivo.» |
| down-mirror | «La próxima pasada de «X» lo quitará también del dispositivo.» | «La próxima pasada de «X» lo copiará al dispositivo.» |
| down | «El dispositivo conserva su copia: «X» no borra.» | «La próxima pasada de «X» lo copiará al dispositivo.» |
| up | «La próxima pasada de «X» lo volverá a subir desde el dispositivo.» | «El dispositivo no lo recibirá: «X» solo sube.» |
| up-mirror | «La próxima pasada de «X» lo volverá a subir desde el dispositivo.» | bloqueado (arriba) |

**La pantalla de confirmación sale** siempre al borrar, y en las demás acciones solo si hay
avisos de pareja. Fuera de las parejas renombrar, mover o crear no piden más confirmación: el
diálogo o el clic en «Pegar aquí» son la intención, y las tres tienen vuelta atrás.

## Piezas

### `common/rcd.py`

- `lanzar_orden(r, orden, grupo) -> int`: lanza UNA orden asíncrona (`_async: true`,
  `_group: grupo`) y devuelve su `jobid`. La orden es `{"_path": …, …parámetros}`. Lanza
  `ValueError` antes de llamar a nada si el `_path` no está en `ORDENES_PERMITIDAS =
  {"operations/mkdir", "operations/movefile", "operations/deletefile", "operations/purge",
  "sync/move"}`.
- `tamano(r, fs, remote) -> tuple[int, int]`: `operations/size`, `(archivos, bytes)`; un campo
  que falta o no es entero cuenta 0.
- El seguimiento usa lo que ya hay: `progreso()`, `estado()`, `cancelar()`.
- El invariante de la pieza 2 cambia de forma: `copiar()` sigue sin poder borrar nada (solo
  `sync/copy`), y `sync/move`, `purge` y `deletefile` solo salen de `lanzar_orden()`.
  `sync/sync` y `job/batch` no salen de ningún sitio.

### `ui/gestion.py` (nuevo; decide, sin Tk, sin red, sin disco)

- `BORRAR`, `RENOMBRAR`, `MOVER`, `NUEVA`.
- `Operacion(tipo, remote, carpeta, elementos, destino=None, nombre=None)`, congelada:
  `carpeta` es donde están los elementos (o donde se crea), `elementos` son
  `transferencia.Elemento`, `destino` la carpeta a la que se pega y `nombre` el nombre nuevo o
  de la carpeta nueva.
- `validar_nombre(nombre, existentes, actual=None) -> str | None`: el motivo del rechazo o
  `None`.
- `validar_pegado(op, nombres_en_destino) -> str | None`: misma carpeta, dentro de sí misma,
  nombre ocupado.
- `rutas_tocadas(op) -> tuple[tuple[str, ...], tuple[str, ...]]`: `(salen, llegan)`.
- `bloqueo(op, config, catalogo) -> str | None` (`catalogo` = `(remote, carpeta)` de
  `model.carpeta_del_catalogo()`) y `avisos(op, config) -> tuple[str, ...]`: la tabla de
  arriba. La búsqueda de «la pareja más honda que contiene esta ruta» y de «las parejas que
  cuelgan de esta ruta» pasa a una función compartida con `transferencia` (que la usa ya en
  `afectadas_subida`), para que la regla no esté escrita dos veces.
- `ordenes_de(op) -> list[dict]`: una orden por elemento (`{"_path": …, …}`), en el orden de los
  elementos:
  - borrar: carpeta → `operations/purge` (`fs = "<remote>:/"`, `remote` = ruta sin la barra
    del principio); archivo → `operations/deletefile` igual;
  - renombrar y mover: carpeta → `sync/move` (`srcFs = "<remote>:/<origen>"`,
    `dstFs = "<remote>:/<destino>"`, `deleteEmptySrcDirs: true`); archivo →
    `operations/movefile` (`srcFs = dstFs = "<remote>:/"`, `srcRemote`, `dstRemote`);
  - nueva carpeta: `operations/mkdir`.
  Los nombres van tal cual, sin escapar: aquí no hay filtros (no es `reglas_de()`).
- `Plan(consequences, warnings)`, congelada, y `plan_de(op, conteos, avisos) -> Plan`: lo que
  enseña `confirmar_plan()`, que solo lee esos dos campos (no es `pair_editor.EditPlan`: aquí
  no hay config que guardar; ejecutar es lanzar el lote). Al borrar, una línea por elemento con lo
  que hay dentro.
- `titulo_de(op) -> str`, `resultado_de(estados, stats, cancelado, op) ->
  transferencia.Resultado`: `estados` es el `job/status` final de cada orden lanzada, en orden
  (las que no se lanzaron por cancelar no están). Todo bien: «Borrados 3», «Movidos 2 a /x», «Renombrado a
  «b».», «Creada «n».» (con su singular). Algún fallo: «Borrados 2 de 3: «x» no se pudo: …», con
  la frase de `servidor.frase_error()`, un 404 como «ya no estaba» y un permiso como «No tienes
  permiso para {borrar|mover|crear} en {carpeta}.», tono «aviso» y sin «Reintentar» (el estado
  ha cambiado: se relee y se vuelve a elegir). Cancelado: «Cancelado: borrados 1 de 3» (los
  que acabaron bien de los elegidos), y «el que iba puede haber quedado a medias» cuando la
  última orden lanzada acabó con error («context canceled»).

### `ui/tk_lote.py` (nuevo; la máquina de lotes, sacada de `tk_servidor.py`)

Hoy la máquina (lanzar → sondear → «Sin respuesta…» → cancelar → resultado → la pregunta al
cerrar) vive en cierres dentro de `tk_servidor.py` (981 líneas; deuda apuntada en
`servidor.md`). Pasa a una clase `Seguimiento` (con la opción de no enseñar el panel hasta que un sondeo diga
que el trabajo sigue vivo) que recibe **una lista de lanzadores** (cada uno, una función que
lanza una orden y devuelve su `jobid`; una copia de la pieza 2 es una lista de uno), cómo
convertir `stats` y la cuenta de elementos en una línea del panel, y cómo convertir los estados
finales en un `Resultado`. Lanza el primero, lo sigue hasta `finished`, apunta su estado y lanza
el siguiente; «Cancelar» manda `job/stop` al que va y no lanza más. Conserva tal cual las reglas de la pieza 2: `FALLOS_PARA_AVISAR`, «job not
found», el `rcd` muerto, `cancelar` una sola vez, `_cancelar_y_esperar` al cerrar. Las
transferencias y la gestión la usan las dos. Las pruebas de la pieza 2 en
`tests/test_tk_servidor.py` siguen sin cambiar: son la red de la extracción.

### `ui/tk_gestion.py` (nuevo; solo dibuja)

- `pedir_nombre(parent, titulo, inicial, validar) -> str | None`: el diálogo de un campo, con el
  motivo bajo el campo, «Aceptar» apagado mientras haya motivo, Intro/Escape, y la selección
  sin la extensión.
- La barra de herramientas y el menú del botón derecho (los construye; las acciones son de
  `tk_servidor`).

### `ui/tk_servidor.py`

Los cuatro flujos, la línea de lo cortado, las teclas y el encendido de los botones. Cada flujo
lee `nav.remote`, `nav.ruta` y la selección **antes** de abrir cualquier diálogo (la regla de la
pieza 2: un diálogo corre un bucle anidado y un listado puede cambiar `nav` mientras tanto).

## Flujo de una acción

1. **Elegir**: diálogo de nombre (nueva, renombrar), «Pegar aquí» (mover) o «Borrar…».
2. **Bloqueo** de parejas y catálogo (puro, al momento): si hay, aviso y fin.
3. **Mirar** en segundo plano, con «Mirando…» en la línea de la ventana: los nombres del destino
   con un `operations/list` no recursivo (nueva, renombrar, pegar; la lista en pantalla puede
   ser vieja), o un `tamano()` por carpeta (borrar). Un nombre ocupado se rechaza aquí.
4. **Confirmar** con `confirmar_plan()` cuando toca (borrar siempre; las demás con avisos).
5. **Lanzar** las órdenes de `ordenes_de()` una tras otra con `lanzar_orden()`, con un
   `_group` nuevo (`gestion-<n>`), y seguirlas con `Seguimiento`.
6. **Acabar**: resultado en el panel o en la línea, releer la carpeta, elegir lo nuevo.

## Fallos

- Los de la pieza 2, por la misma máquina: `rcd` muerto → «Se perdió la conexión con rclone.» y
  «Reconectar»; sondeos que fallan → «Sin respuesta…» sin soltar el lote; «job not found» →
  «No se sabe cómo acabó: revisa la carpeta.».
- Por elemento, en el resultado (arriba). El resultado cuenta **elementos**, no archivos.
- Cancelar: no se lanza el elemento siguiente y el que va sigue hasta acabar (rclone no para un
  borrado a medias; un movimiento que copia y borra, en un servidor sin movimiento propio, sí se
  puede cortar y dejar a medias, y se dice); lo hecho queda hecho; se relee la carpeta. El panel
  dice «Cancelando… se para al acabar «x».».
- Mirar que falla: el panel lo dice con «Reintentar», y no se lanza nada.

## Límites conocidos (van a «Known, not fixed»)

- **Carrera entre mirar y lanzar**: si otro crea el mismo nombre entre la comprobación y el
  trabajo, `movefile` contra un archivo «igual» borra el origen sin escribir, y `sync/move` de
  una carpeta mezcla y pisa. La ventana es de una fracción de segundo y pide que otro escriba en
  esa carpeta a la vez.
- **Parejas de otros dispositivos**: solo se conocen las de este (decisión 6).
- **Servidores sin movimiento en el servidor** (algunos WebDAV, S3): `sync/move` y `movefile`
  copian y borran; una carpeta grande tarda, y el panel lo sigue. Fila pendiente en real.
- **Cambiar solo mayúsculas** en un servidor que no las distingue (OpenSSH en Windows, SMB):
  sin probar; fila pendiente en real.

## Pruebas

- `tests/test_gestion.py` (pura, en `GUI_NO`): `validar_nombre` (vacío, espacios, `/`, `.`,
  `..`, ocupado sin distinguir mayúsculas, solo mayúsculas del propio, igual exacto);
  `validar_pegado`; `rutas_tocadas` de las cuatro; toda la tabla de bloqueos y avisos (cada modo
  × sale/llega, raíz, contenedor de raíz, renombrar al nombre de una raíz, catálogo y dentro del
  catálogo, pareja anidada, otro remote, la pareja del llavero); las entradas exactas de
  `ordenes_de` con nombres con espacios, `%`, `#`, `?`, `*`, `[`, `{`; `resultado_de` con todo
  bien, un fallo en medio, un 404, un permiso, cancelado tras el primero, y cancelado con el que
  iba a medias.
- `tests/test_rcd.py`: `lanzar_orden` rechaza un `_path` fuera de los permitidos (y `job/batch`)
  sin llamar a nada, y manda la orden asíncrona con su grupo; `tamano`.
- `tests/test_tk_gestion.py` (en `GUI`): el diálogo de nombre (selección sin extensión, motivo
  bajo el campo, «Aceptar» apagado, Intro/Escape).
- `tests/test_tk_servidor.py`: cada flujo con el `rcd` falso; cortar → navegar → pegar; pegar
  rechazado (misma carpeta, dentro de sí misma, ocupado, otro remote); el encendido de la barra;
  las teclas y el menú; bloqueos y avisos que llegan a la ventana; cerrar con una acción en
  marcha. Las pruebas de la pieza 2 pasan sin tocarlas tras la extracción.
- Durante la construcción, de punta a punta con el `rclone` real contra `rclone serve sftp`:
  borrar una carpeta de 300 archivos, mover y renombrar en el servidor, cancelar un borrado
  grande, y que un nombre ocupado se rechace.
- Filas nuevas G1… en `docs/superpowers/pruebas/2026-10-27-servidor-pendiente-en-real.md`:
  servidor sin movimiento en el servidor, cambiar solo mayúsculas en un servidor que no las
  distingue, borrar 10 000 archivos en un servidor de verdad.

## Documentación

- `docs/agents/reference/servidor.md`: la pieza 3 (reglas, flujo, tabla, límites), el
  invariante de órdenes nuevo, y `tk_lote.py`.
- `.claude/rules/servidor.md`: las rutas nuevas (`gestion.py`, `tk_gestion.py`, `tk_lote.py` y
  sus pruebas); `docs/agents/reference/commands-testing.md`: el registro de las pruebas y de los
  puntos que las pruebas sustituyen (`tk_gestion.pedir_nombre`).
- `docs/guia/servidor.md`: cómo se crea, renombra, mueve y borra; qué se bloquea y por qué; que
  borrar es para siempre; el límite de las parejas de otros dispositivos.

## Qué pasa con los dispositivos que ya están en uso

Nada cambia hasta que se usan los botones nuevos: no hay datos nuevos en el dispositivo ni en
el servidor, ni cambios de config o de estado. Llega con la actualización normal.

## Cómo quedó al construirla

Donde el código y este texto difieren, manda el código (`docs/agents/reference/servidor.md`,
«Management»). Lo que cambió al construir: cambiar de remote no quita lo cortado (ver arriba); los
paneles se titulan «Borrando en {carpeta}», «Moviendo a {destino}», «Renombrando «a» a «b»» y
«Creando la carpeta «n»»; el seguimiento de varias órdenes vive en `ui/tk_lote.py` (`Seguimiento`),
no en `tk_servidor.py`; y las órdenes de gestión salen solo por `rcd.lanzar_orden()`, con la lista
cerrada `rcd.ORDENES_PERMITIDAS`. Lo que sigue sin resolver está en «Known, not fixed» de esa
documentación: la carrera entre mirar y lanzar, las parejas de otros dispositivos, los servidores
sin mover por dentro, el renombrado que solo cambia mayúsculas, el límite de
`remote_picker.normalizar()` (una carpeta con un espacio al final o una barra invertida) y que el
menú del botón derecho no toma los colores en Windows.
