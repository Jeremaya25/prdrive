# «Servidor…»: bajar y subir archivos y carpetas — diseño

Fecha: 27/10/2026. Estado: **construida** (código, pruebas automáticas y guía); las pruebas en máquina real (filas T1 a T6 de `docs/superpowers/pruebas/2026-10-27-servidor-pendiente-en-real.md`) están por hacer. Es la pieza 2 de
tres del explorador del servidor; la pieza 1 (explorar, solo lectura) está en la 0.8.0
(`docs/superpowers/specs/2026-10-27-explorador-servidor-design.md`,
`docs/agents/reference/servidor.md`). La pieza 3 (renombrar, mover, borrar) tendrá su spec.

## Por qué

Con la pieza 1 se ve lo que hay en el servidor, pero para coger o dejar algo hace falta otro
programa. Esta pieza añade bajar y subir archivos y carpetas desde el mismo explorador, con la
conexión del dispositivo, con progreso y cancelación, y sin poder estropear una pareja.

## Qué se quiere

- Bajar al equipo uno o varios archivos y carpetas elegidos en la lista.
- Subir a la carpeta que se ve archivos sueltos o una carpeta entera del equipo.
- Ver el progreso en el propio explorador y poder seguir navegando; cancelar.
- Que nada se sobrescriba sin preguntarlo, y que una subida no choque con lo que hará la
  siguiente pasada de una pareja.

No se quiere: arrastrar y soltar (Tk no lo trae sin la extensión `tkdnd`, que no es de la
biblioteca estándar), una cola de varios lotes, ni borrar nada (pieza 3).

## Decisiones del dueño (27/10/2026)

1. **Archivos y carpetas**, varios a la vez, en los dos sentidos.
2. **Subir dentro de una pareja: avisar según el modo y bloquear `up-mirror`.** Lo que se sube
   a la carpeta remota de una pareja lo ve su siguiente pasada:

   | Modo | Qué hace la siguiente pasada con lo subido | Aquí |
   |---|---|---|
   | `bisync` | lo baja al dispositivo; si se sobrescribió algo que también cambió allí, sale un conflicto | aviso |
   | `down`, `down-mirror` | lo baja al dispositivo | aviso |
   | `up` | lo deja | aviso |
   | `up-mirror` | **lo borra del servidor** (el servidor se iguala al dispositivo) | **bloqueado** |

   Bajar desde una pareja no tiene riesgo para el servidor: solo lee. **El caso simétrico**
   (añadido al escribir el spec, con la misma regla): bajar **dentro de la carpeta local de una
   pareja** del dispositivo lo ve también su siguiente pasada — en `down-mirror` lo **borraría**
   (lo local se iguala al servidor), así que se bloquea; en las demás, aviso de lo que hará.
3. **Un solo aviso de choques por lote, sin lista.** Antes de copiar se mira el destino; si algo
   ya existe sale «N elementos ya existen en el destino» con «Sobrescribir», «Omitir» y
   «Cancelar». No se pregunta archivo por archivo. Ese aviso es la confirmación que pide la regla
   de `AGENTS.md` para lo que reescribe datos del usuario: dice cuántos y dónde.
4. **Un `sync/copy` por lote** (se descartó un `copyfile` por archivo: más lento con muchos
   archivos pequeños, y solo hacía falta para preguntar archivo a archivo).
5. **Panel de progreso abajo**, se sigue navegando; un lote cada vez.

## Lo comprobado con rclone v1.75.2 (contra `rclone serve sftp` local, 27/10/2026)

- `sync/copy` con `_filter: {"IncludeRule": [...]}` copia solo lo elegido: un archivo
  (`/a.txt`), una carpeta entera (`/carpeta/**`) y una carpeta vacía con
  `createEmptySrcDirs: true`. Un nombre con caracteres de patrón (`raro [1]*`) funciona
  escapado (`/raro \[1\]\*/**`).
- `_config: {"IgnoreExisting": true}` deja intacto lo que ya existe; sin él, lo distinto se
  sobrescribe y lo idéntico se salta.
- `_async: true` + `_group` → `jobid`; `core/stats {group}` da `bytes`, `totalBytes`, `speed`,
  `eta`, `transfers`, `totalTransfers`, `checks` y `transferring[]` (nombre y porcentaje del
  archivo en curso); `job/stop {jobid}` cancela y `job/status` acaba con `success: false`.
- **Cancelar a mitad de un archivo no deja restos ni pierde lo que había**: al subir
  sobrescribiendo, el archivo del servidor conservó su versión anterior (SFTP sube a un nombre
  temporal y renombra al acabar); al bajar, no quedó archivo a medias en el disco.
- `operations/list` con `opt.recurse: true` da las rutas de un árbol, para contar choques.

## Piezas

### `common/rcd.py`

- `copiar(rcd, origen_fs, destino_fs, reglas, omitir, grupo) -> int`: un `sync/copy` asíncrono
  con `srcFs`, `dstFs`, `createEmptySrcDirs: true`, `_filter: {"IncludeRule": reglas}`,
  `_group: grupo` y, solo si `omitir`, `_config: {"IgnoreExisting": true}`. Devuelve el `jobid`.
  **Siempre `sync/copy`, nunca `sync/sync`** ni `sync/move`: copiar no borra nada en el destino.
- `progreso(rcd, grupo) -> dict` (`core/stats`), `estado(rcd, jobid) -> dict` (`job/status`),
  `cancelar(rcd, jobid) -> None` (`job/stop`, no lanza si el trabajo ya acabó).
- Son funciones sobre `Rcd.llamar()`: los tests siguen sustituyendo solo `rcd.peticion()` o el
  `Rcd` entero.

### `ui/transferencia.py` (nuevo; decide, sin Tk, sin red, sin disco)

- `Lote(sentido, remote, ruta_remota, carpeta_local, elementos)` congelado: `sentido` es
  `"bajar"` o `"subir"`; `elementos`, los nombres elegidos (en la carpeta remota al bajar, en la
  carpeta local al subir), cada uno con si es carpeta.
- `reglas_de(elementos) -> list[str]`: las `IncludeRule`. Un archivo `x` → `/x`; una carpeta `x`
  → `/x/**` (con `createEmptySrcDirs` eso basta también para una carpeta vacía: comprobado). Los caracteres de patrón de
  rclone (`* ? [ ] { } \`) se escapan con `\`. **Es lo más delicado del módulo**: un nombre mal
  escapado copiaría otra cosa.
- `fs_de(lote) -> (origen, destino)`: al bajar `"<remote>:/<ruta>"` → la carpeta local; al subir
  al revés. El remoto siempre por la raíz absoluta, como en la pieza 1.
- `choques(rutas_origen, rutas_destino) -> int`: cuántos **archivos** del lote ya existen en el
  destino con la misma ruta relativa. Una carpeta que ya existe no es un choque: se mezcla.
- `bloqueo_subida(config, remote, ruta_destino, elementos) -> str | None` y
  `aviso_subida(...) -> str | None`: el texto del bloqueo o del aviso según el modo de la pareja
  afectada, o `None`. Una subida afecta a una pareja si su destino está **dentro** de ella
  (`servidor.dentro_de`, gana la más interior) **o** si alguno de los elementos subidos acaba
  dentro de una (subir a `/datos` una carpeta `notas` cuando hay una pareja en `/datos/notas`).
  Con varias parejas afectadas: bloqueo si alguna es `up-mirror`; si no, un aviso que las nombra.
- `bloqueo_bajada(config, carpeta_local, elementos) -> str | None` y `aviso_bajada(...)`: lo
  mismo al bajar, frente a la carpeta local de cada pareja (`Pair.local` resuelta contra la raíz
  del dispositivo como hace `model`): bloqueo si la afectada es `down-mirror`, aviso en las demás.
  Fuera de las carpetas de las parejas (el escritorio, «Descargas»…) no hay ni aviso ni bloqueo.
- `progreso_de(stats, lote) -> Progreso`: textos ya hechos — título («Subiendo a /datos» /
  «Bajando a …»), archivo en curso, «3 de 41 archivos · 120 MB de 800 MB», fracción para la
  barra (o `None` si el total aún no se sabe), «4,2 MB/s · quedan 2 min». Campos que faltan, total
  0 y `eta` nula no lanzan.
- `resultado_de(estado, stats, cancelado) -> Resultado`: «Copiados 38 · omitidos 3» (tono ok),
  «Cancelado: copiados 12 de 41» (tono aviso) o el error en llano reutilizando
  `servidor.frase_error` (tono aviso, con «Reintentar»).
- Tamaños y velocidades con `servidor.tamano_legible`.

### `ui/tk_servidor.py`

- La lista pasa a `selectmode="extended"` (Ctrl/Mayús). Doble clic e Intro siguen entrando en
  una carpeta cuando la selección es una sola carpeta.
- Barra: «Bajar…» (encendido con algo elegido), «Subir archivos…» y «Subir carpeta…» (encendidos
  con conexión). Los tres se apagan mientras hay un lote.
- Los diálogos del sistema son funciones de módulo que los tests sustituyen:
  `elegir_destino(parent) -> str | None` (`filedialog.askdirectory`),
  `elegir_archivos(parent) -> list[str]` (`askopenfilenames`),
  `elegir_carpeta(parent) -> str | None` (`askdirectory`). Todos empiezan en la última carpeta
  local usada en esta ventana; nada se guarda en disco.
- El panel de progreso (sección siguiente) entre la lista y el pie.

## Flujo de un lote

1. Se elige qué y adónde. Al subir, con el destino = la carpeta que se ve.
2. Dentro de una pareja (subida: su carpeta remota; bajada: su carpeta local):
   `bloqueo_subida`/`bloqueo_bajada` → un aviso que no deja seguir;
   `aviso_subida`/`aviso_bajada` → una confirmación «Seguir» / «Cancelar» con el texto del modo.
3. Contar choques, en segundo plano (`tk.Indicador` «Mirando el destino…»): al subir,
   `operations/list` recursivo de **cada elemento** bajo el destino (no del destino entero, que
   puede ser enorme) frente al recorrido local de lo elegido; al bajar, al revés con `os.walk`
   de la carpeta local de destino limitado a los nombres elegidos.
4. Con choques, el aviso único: «N elementos ya existen en {destino}. ¿Sobrescribirlos u
   omitirlos?» → «Sobrescribir», «Omitir», «Cancelar» (por defecto «Cancelar»).
5. `rcd.copiar(...)`; el panel aparece.
6. Al acabar: el resultado en el panel; si se subió a la carpeta que se ve, se relee.

## El panel de progreso

- Una franja al pie de la lista que solo existe con un lote: título, archivo en curso, «N de M ·
  bytes de total», una `ttk.Progressbar` (indeterminada mientras el total es desconocido),
  velocidad y tiempo restante, y «Cancelar».
- `core/stats` y `job/status` se piden cada 500 ms en segundo plano (`segundo_plano` +
  `Sondeo`): la ventana no se congela y se puede seguir navegando. Las peticiones del listado y
  las del progreso van por el mismo `rcd`, que las atiende a la vez.
- Al acabar, el panel queda como una línea de resultado (`tk.bloque_aviso` del tono que diga
  `resultado_de`) con «Reintentar» si hubo error, hasta el siguiente lote o hasta cerrar.
  «Reintentar» repite el mismo lote con la misma decisión de choques: lo ya copiado e idéntico
  se salta, así que sigue donde se quedó.
- **Cancelar**: `rcd.cancelar(jobid)`; el panel dice «Cancelando…» hasta que `job/status` dice
  `finished`, y luego «Cancelado: copiados X de N». Lo copiado se queda.
- **Cerrar el explorador con un lote en marcha** pregunta «Hay una transferencia en marcha.
  ¿Cancelarla y cerrar?». «Sí»: cancelar, esperar a `finished` (con tope de `rcd.ESPERA_QUIT`) y
  cerrar como siempre. «No»: no se cierra.
- **Si la ventana muere de golpe**, los cinturones de la pieza 1 matan el `rcd`: el archivo que
  iba a medias puede dejar su temporal en el servidor. No se limpia aquí (borrar es la pieza 3);
  la guía lo dice.
- Expulsar no es posible con el explorador abierto (es modal), así que no hay expulsión a mitad
  de lote.

## Fallos

- Un error de rclone en el lote (permiso, sin espacio, conexión) acaba el trabajo con
  `success: false`: el panel dice la frase en llano y ofrece «Reintentar». Lo copiado antes se
  queda.
- `RcdCaido` durante un lote: el panel dice «Se perdió la conexión con rclone» y ofrece
  «Reconectar» (relanzar `rcd`, en el hilo de Tk como en la pieza 1); el lote no se reanuda solo.
- Un elemento local que desaparece entre elegirlo y copiarlo: lo dice rclone y sale como error.
- Los `NET_FLAGS` cortos de la pieza 1 siguen: un servidor que deja de responder da error en
  segundos.

## Pruebas

Ningún test arranca rclone ni toca la red: se sustituyen `rcd.peticion` (o el `Rcd`) y los tres
diálogos del sistema.

- `tests/test_transferencia.py`: `reglas_de` (archivo, carpeta, carpeta vacía, `* ? [ ] { } \`,
  espacios, acentos); `fs_de` en los dos sentidos; `choques` (archivos que coinciden, carpetas
  que solo se mezclan, nada en el destino); `bloqueo_subida`/`aviso_subida` en los cinco modos,
  una pareja en la raíz, parejas anidadas, una subida por encima de una pareja y varias parejas
  afectadas; `bloqueo_bajada`/`aviso_bajada` (`down-mirror` bloquea, las demás avisan, fuera de
  las parejas nada); `progreso_de` (campos que faltan, total 0, `eta` nula, tamaños y velocidades);
  `resultado_de` (ok, omitidos, cancelado, error).
- `tests/test_rcd.py`: `copiar()` manda `sync/copy` (nunca `sync/sync`) con el filtro,
  `createEmptySrcDirs`, `_async`, el grupo y `IgnoreExisting` solo con «Omitir»; `cancelar()`
  manda `job/stop` y no lanza si ya acabó; `progreso()` y `estado()`.
- `tests/test_tk_servidor.py`: botones y cuándo se encienden; selección múltiple; bloqueo en
  `up-mirror` y aviso en `bisync`; el aviso de choques con sus tres respuestas (y que «Cancelar»
  no copia nada); el panel con un progreso falso que avanza; «Cancelar» y su texto; el resultado
  y «Reintentar»; cerrar a mitad pregunta y con «No» no cierra; tras subir a la carpeta que se
  ve, se relee.
- `tests/test_tk_medidas.py`: la ventana con el panel visible cabe en las 10 pantallas.
- Antes de la PR, la prueba real de la pieza 1 ampliada: rclone v1.75.2 contra
  `rclone serve sftp` bajo Xvfb — subir, bajar, chocar con «Omitir» y «Sobrescribir», cancelar a
  mitad — con capturas.
- Pendiente en máquina real (filas nuevas en
  `docs/superpowers/pruebas/2026-10-27-servidor-pendiente-en-real.md`): un SFTP de verdad (con y
  sin renombrado del temporal al acabar); cancelar una subida grande en Windows; bajar a la propia
  unidad en FAT32/exFAT (fechas de 2 s: comprobar que rclone no vuelve a copiar lo idéntico);
  subir 10 000 archivos pequeños y medir.

## Documentación

- `docs/agents/reference/servidor.md`: la sección de transferencias (el filtro, `sync/copy`
  nunca `sync/sync`, el aviso por modo, cancelar, el panel).
- `docs/agents/reference/commands-testing.md`: los puntos de sustitución nuevos
  (`elegir_destino`, `elegir_archivos`, `elegir_carpeta`).
- `.claude/rules/servidor.md`: `ui/transferencia.py` y `tests/test_transferencia.py`.
- `docs/guia/servidor.md`: bajar y subir, el aviso de choques, qué pasa al cancelar, y el temporal
  que puede quedar si el programa se cierra de golpe.

## Qué pasa con los dispositivos que ya están en uso

Nada hasta que actualizan. Después, el explorador gana los botones; ni el `rclone.conf`, ni el
config, ni las parejas cambian. Lo que se sube a una pareja lo recoge su siguiente pasada como
cualquier cambio hecho en el servidor; en `up-mirror` no se deja subir.
