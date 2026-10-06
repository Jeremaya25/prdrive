# `watch = true` con los avisos del sistema — diseño

Fecha: 06/10/2026. Continúa `watch = true` (#61); lo que hay hoy está en
`docs/agents/reference/agent-scheduling.md` («A pair with `watch = true`…»).
Estado: **fases 1 y 2 hechas en código** (plan `docs/superpowers/plans/2026-10-06-watch-con-avisos.md`):
el recorrido de B en todas partes, inotify en Linux y `ReadDirectoryChangesW` en
Windows. Decidido el 06/10/2026: la pregunta 1 se acepta (el handle abierto en
Windows); la 2, como se proponía (los volúmenes de VeraCrypt se recorren hasta
comprobarlo, prueba F18); la 3, como se proponía, con un presupuesto (la mitad
de `max_user_watches`, que es de todo el usuario). Falta verlo en equipos
reales: filas F9–F19 de `docs/superpowers/pruebas/2026-09-25-equipo-pendiente-en-real.md`.

## Qué se quiere

Que vigilar una pareja deje de costar mientras no cambia nada. Hoy el agente
recorre la carpeta de cada pareja vigilada cada 10 s (`huella.de_carpeta()`:
`scandir` y `stat` de cada entrada), también a batería, y en un portátil con la
unidad enchufada y quieta es lo que más gasta.

Lo que tiene que seguir igual: la calma (una ráfaga es una pasada), la
separación entre pasadas, la moderación (pausa, batería, ahorro de energía, red
de uso medido), que lo que escribe la propia pasada no la dispare, y que
expulsar o bloquear una unidad no se encuentre nada abierto que lo impida.

**Criterios de éxito**, medidos con el mismo banco de pruebas que abajo:
- el agente sirviendo una pareja vigilada de 15 000 ficheros gasta **≤ 1 ms de
  CPU por segundo** en reposo (hoy 7,0);
- del último cambio a la pasada, lo mismo que hoy: la calma (20 s) y unos
  segundos;
- «Expulsar», «Bloquear» y la extracción segura del sistema funcionan igual con
  la vigilancia puesta;
- donde no hay avisos (una carpeta de red), todo sigue como hoy o mejor.

## Lo medido (06/10/2026)

Banco de pruebas: el agente de verdad (`agente.py run`) sirviendo una unidad de
mentira en modo daemon contra un OpenSSH local, Linux, cachés calientes. Los
números de Windows no están medidos.

| Qué | CPU del agente | Despertares |
|---|---|---|
| Sin unidades | 0,2 ms/s | 0,5/s |
| Unidad servida, sin `watch` | 0,6 ms/s | 0,6/s |
| Unidad servida, `watch` en 15 000 ficheros | **7,0 ms/s** | 0,8/s |

- Un recorrido de 20 000 entradas: **80 ms de CPU**. El suelo de este método
  (solo `scandir` y `stat`, sin hash) es 53 ms: un hash más barato no arregla
  nada.
- En un día, ~10 min de CPU por pareja vigilada, varias veces lo que cuestan
  todas las pasadas cada 30 min.
- El tope de 20 000 entradas deja fuera carpetas normales: la de pruebas de
  20 000 ficheros tenía 20 440 entradas contando carpetas, y el agente dejó de
  vigilarla.

Sonda de inotify sobre un ext4 montado en un dispositivo loop con esa misma
carpeta (442 carpetas). Este kernel no trae exFAT ni FAT32; inotify está en
la capa VFS y no en el sistema de ficheros, así que con ellos debería ir igual,
pero eso lo confirma la lista de equipos reales, no esta sonda.
- Poner 442 vigilancias: **19 ms de CPU, una vez**.
- Guardar, renombrar, cambiar la fecha y crear una carpeta llegan como
  `IN_CLOSE_WRITE`, `IN_MOVED_FROM`/`IN_MOVED_TO`, `IN_ATTRIB` e `IN_CREATE`.
- **Desmontar con las vigilancias puestas funciona**: `umount` no protesta, y
  llegan 442 `IN_UNMOUNT` y 442 `IN_IGNORED`.
- Esperar 3 s sin cambios: **0,1 ms de CPU**.

Tras la fase 1 (06/10/2026, el mismo Linux, cachés calientes; un banco más
pequeño que el de arriba: el motor y el vigía del agente, sin el resto del
agente ni OpenSSH), con 15 000 ficheros en 463 carpetas:
- Un recorrido: 58 ms de CPU. Cada 10 s son 5,8 ms/s; cada 2 min (la carpeta
  quieta, con B), 0,48 ms/s.
- Poner las 463 vigilancias: 15 ms de CPU, una vez.
- En reposo, el vigía con el descriptor oído y `recoger()` en cada tic:
  **0,09 ms/s**, que es lo que ya cuesta el tic. Sumado a los 0,6 ms/s del
  agente sirviendo una unidad, el criterio (≤ 1 ms/s) se cumple; falta
  repetirlo con el banco entero.

## Enfoques

**A. Avisos del sistema, con el recorrido de respaldo (el recomendado).**
inotify en Linux y `ReadDirectoryChangesW` en Windows dicen «algo ha cambiado»
sin recorrer nada. Donde no hay avisos fiables (una carpeta de red, una raíz
VeraCrypt en Windows mientras no se compruebe, el agente de Windows sin bandeja)
se recorre como hoy, pero con el recorrido adaptativo de B. Es lo único que
lleva el coste a casi cero, y además quita el tope de entradas. En Windows hay
que dejar abierta la carpeta entre pasadas, y eso es una decisión (pregunta 1).

**B. Solo recorrido adaptativo.** Cada 10 s tras un cambio, alargando hasta 2
min mientras la carpeta está quieta, y 60 s a batería. Barato de hacer y sin
riesgo para expulsar, pero un cambio tras un rato de calma tarda hasta 2 min en
verse, y en reposo sigue costando 0,5–1 ms/s por pareja. El tope sigue.

**C. A en Linux y B en Windows.** Evita la parte delicada de Windows (el
handle abierto) a cambio de dejar sin resolver el sistema donde más se usa un
portátil.

Se recomienda **A**, con B como el comportamiento de respaldo: así nada empeora
donde no hay avisos.

## Diseño

### Piezas

**`common/avisos_carpeta.py`** (sin Tk, como `common/red.py`): saber si una
carpeta ha cambiado, no qué fichero. Un objeto por agente con dos motores
detrás de la misma forma:
- `vigilar(clave, carpeta, ignorar) -> bool`: pone la vigilancia de una
  pareja; `False` si en esa carpeta no hay avisos fiables (se recorre).
- `dejar(clave)` y `dejar_raiz(uid)`: la quita (y en Windows, cierra su handle).
- `recoger() -> dict[clave, Aviso]`: lo que ha llegado desde la última vez.
  `Aviso` es `CAMBIO`, `DESBORDADO` (se perdieron avisos: cuenta como cambio) o
  `PERDIDA` (la carpeta ya no está, o se desmontó: esa pareja vuelve a
  recorrer).

Indirección: `agente.poner_avisos_carpeta()`, como `agente.poner_red()`; los
tests ponen uno de mentira.

**Linux, inotify** por `ctypes` (`inotify_init1`, `inotify_add_watch`,
`inotify_rm_watch`; la biblioteca estándar no los trae):
- Un descriptor para todo el agente y una vigilancia por carpeta. Ponerlas
  recorre solo las carpetas, una vez por conexión (las 442 de arriba, 19 ms).
  Cada vigilancia, con
  `IN_CLOSE_WRITE | IN_ATTRIB | IN_CREATE | IN_DELETE | IN_MOVED_FROM |
  IN_MOVED_TO | IN_DELETE_SELF | IN_MOVE_SELF`. No `IN_MODIFY`: llega con cada
  `write()`, y basta el cierre.
- Una carpeta nueva (`IN_CREATE | IN_ISDIR`) recibe su vigilancia, y cuenta
  como cambio: lo que se escribió dentro antes de vigilarla no habrá avisado.
- `IN_Q_OVERFLOW` es `DESBORDADO` para todas las parejas del descriptor (no se
  sabe de cuál era). `IN_UNMOUNT` y el `IN_IGNORED` de la carpeta de la pareja
  son `PERDIDA`.
- **Sin hilo nuevo**: el descriptor entra en el `poll` de `agente.Vigia`, junto
  a `/proc/self/mountinfo` y el pipe de despertar. Un aviso despierta la vuelta.
- Lo que no es local (`statfs` dice NFS, CIFS/SMB o FUSE de red como sshfs: la
  tabla en el módulo) devuelve `False`: inotify solo ve lo que se cambia desde
  este equipo.
- El tope pasa a ser de **carpetas** y lo pone el sistema:
  `/proc/sys/fs/inotify/max_user_watches` (desde Linux 5.11 crece con la RAM;
  antes, 8192). Con `ENOSPC` la pareja vuelve a recorrer y se dice una vez.

**Windows, `ReadDirectoryChangesW`**:
- Un handle por pareja: `CreateFileW(FILE_LIST_DIRECTORY, compartido para leer,
  escribir y borrar, FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OVERLAPPED)`, con
  `bWatchSubtree` y `FILE_NOTIFY_CHANGE_FILE_NAME | DIR_NAME | SIZE |
  LAST_WRITE`.
- Un hilo espera los eventos de todos los handles
  (`WaitForMultipleObjects`, hasta 64) y llama a `Vigia.despertar()`.
- Un búfer desbordado (la llamada vuelve bien con 0 bytes, o
  `ERROR_NOTIFY_ENUM_DIR`) es `DESBORDADO`.
- `GetDriveTypeW` de red devuelve `False`.
- **El handle abierto impide expulsar.** Cada handle se registra con
  `RegisterDeviceNotificationW` (`DBT_DEVTYP_HANDLE`) en la ventana de la
  bandeja:
  - `DBT_DEVICEQUERYREMOVE` cierra el handle y deja la pareja en `PERDIDA` hasta
    `DBT_DEVICEQUERYREMOVEFAILED` (se reabre) o la desconexión.
  - Sin bandeja no hay ventana que reciba eso: el agente sin bandeja recorre.

### En el agente

- `_vigilar()`: para cada pareja vigilada se pide `vigilar()` al conectarse la
  raíz y al pasar a servirla. Las que tienen avisos no se recorren nunca. Las
  otras se recorren con el ritmo de B. `_recoger_fotos()` queda para esas.
- **Lo que escribe la propia pasada.** Los avisos de una pareja con su pasada
  en marcha se tiran. Al acabar la pasada (`_fin_de_pasada()`) se vacía lo
  pendiente de esa pareja antes de olvidarlo, como hoy con la foto. El precio es
  el de hoy: lo que la persona cambia mientras corre la pasada espera al
  intervalo.
- **Lo que no cuenta**: los avisos bajo `IGNORAR_CAMBIOS` (`.prversions/`,
  `.prdrive/`, `.keychain/`) y `ruido_en()` en la raíz de la pareja. Se filtra
  por la ruta del aviso; en inotify, a esas carpetas ni se les pone vigilancia.
- **Planificador** (puro): `pl.avisado(vigilada, ahora)` hace lo que hoy hace
  `observar()` cuando la firma cambia: mueve `cambio` a `ahora`. Lo demás
  (`toca_por_cambios`, calma, separación, moderación) no cambia.
- **Moderación**: con ella reteniendo, los avisos se siguen apuntando (no
  cuestan nada) y la pasada sale tras la calma cuando la moderación suelta. Hoy
  el primer recorrido de después lo ve igual.
- **«Expulsar» y «Bloquear»**: antes de actuar, `dejar_raiz(uid)`, como hoy se
  espera a la foto en marcha (`_mirando()`). En Linux no hace falta (medido),
  pero deja todo en el mismo orden en los dos sistemas.
- **La invariante «nada abierto en la unidad entre pasadas»** (`agent.md`)
  cambia en Windows: queda abierto el handle de la carpeta de cada pareja
  vigilada, y se cierra solo cuando el sistema pide la unidad. Hay que
  escribirlo así en el doc.
- Lo que se ve: `estado.json` y `agente.py status` dicen por pareja «avisos» o
  «recorrido», y por qué recorre. `agente.log` lo dice una vez cuando una
  pareja pasa a recorrer.

### Recorrido de respaldo (B)

`PoliticaCambios` gana `sondeo_quieto` (120 s) y `sondeo_bateria` (60 s). Una
pareja recorre cada `sondeo` (10 s) durante `sondeo_quieto` tras su último
cambio visto, y luego cada `sondeo_quieto`. A batería, nunca menos de
`sondeo_bateria`. La regla vive en `pl.a_recorrer()`.

## Lo que no se hace

- Ver los cambios del remoto: siguen esperando al intervalo.
- Cambiar `llavero.Vigilancia`, la del vigilante del llavero y el servicio de
  runsync: solo mira los ficheros de la base y no cuesta. El servicio de
  runsync no vigila carpetas.
- fanotify (pide privilegios), macOS (no es plataforma).
- Saber qué fichero cambió, o pasar a rclone la lista: bisync necesita su
  listado entero.

## Pruebas

- **Puras**: `pl.avisado()`, el recorrido de B (`a_recorrer` con quieto y
  batería) y el filtro de rutas ignoradas.
- **Linux de verdad** (CI en ubuntu, en un temporal): crear, guardar, renombrar,
  borrar, cambiar la fecha, una carpeta nueva con un fichero dentro, nada en las
  carpetas ignoradas y `ENOSPC` con un `max_user_watches` de mentira (la
  indirección del número). Si la CI corre como root con dispositivos loop, el
  desmontaje con vigilancias puestas (la sonda de arriba); si no, `(saltado)`.
- **Windows de verdad** (CI en windows, en un temporal): los mismos cambios, el
  desbordamiento con un búfer mínimo, y que `dejar()` cierre el handle (se
  puede borrar la carpeta después).
- **El agente** con un `avisos_carpeta` de mentira, en `test_agente_watch.py`:
  una pareja con avisos no se recorre; un aviso con su pasada en marcha no
  cuenta; `PERDIDA` vuelve a recorrer; «Expulsar» y «Bloquear» llaman a
  `dejar_raiz()` antes de actuar.
- **El banco**: repetir la medida de arriba; el criterio es ≤ 1 ms/s.
- **Equipos reales**, a la lista `2026-09-25-equipo-pendiente-en-real.md`:
  pendrive exFAT y FAT32 en W y L; extracción segura y «Expulsar» con la
  vigilancia puesta en W; una raíz VeraCrypt en W y L; una carpeta de red.

## Preguntas abiertas

1. **Windows: ¿se acepta dejar abierto el handle de la carpeta de cada pareja
   vigilada entre pasadas**, cerrándolo cuando el sistema pide la unidad y
   antes de «Expulsar» y «Bloquear»? Si no, la opción es C (Windows recorre con
   B).
2. **Raíces VeraCrypt en Windows**: VeraCrypt desmonta con `FSCTL_LOCK_VOLUME`,
   y no está comprobado que antes mande `DBT_DEVICEQUERYREMOVE`. Si no lo
   manda, un desmontaje de fuera del agente (la propia ventana de VeraCrypt, su
   desmontaje automático, `Expulsar PRDRIVE.bat`) preguntaría si forzar.
   Propuesta: esas raíces recorren con B hasta comprobarlo en un equipo real.
3. **El tope.** Con avisos, ¿se quita el de 20 000 entradas (queda el de
   carpetas del sistema en Linux, y ninguno en Windows), o se mantiene uno
   propio? Propuesta: quitarlo con avisos y dejarlo para el recorrido.
