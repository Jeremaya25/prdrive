# `watch = true` y el consumo del agente: hoja de ruta — diseño

Fecha: 11/10/2026. Estado: **construida en su mayor parte ese mismo día** (ver «Lo construido», al
final); el texto de abajo es la propuesta tal como se aprobó. No es una especificación para construir de una
vez: son cinco entregas independientes, cada una con su propia especificación y su plan cuando le
toque. Las cifras salen de `docs/superpowers/pruebas/2026-10-11-watch-energia-windows-medidas.md`
(un sobremesa sin batería: la energía se estima con CPU, despertares, procesos y escrituras).

## Qué se quiere

1. **Más limpio**: que en Windows una pareja vigilada se comporte como en Linux y sin sorpresas (ni
   pasadas de más, ni carpetas que se quedan sordas, ni volúmenes «en uso»).
2. **Más barato**: que una unidad en la que no cambia nada cueste casi nada en CPU, en despertares,
   en procesos y en escrituras de flash.

## Dónde está el gasto

Con una unidad conectada y 4 parejas cada 5 minutos (lo que hay en el equipo medido):

| Partida | Al día | |
|---|---|---|
| Pasadas por intervalo que no encuentran nada | ~711 s de CPU, 3 456 procesos, 36–300 MB escritos en la unidad | lo que domina |
| El tic de 2 s con la unidad servida | ~9 operaciones de fichero en la unidad cada 2 s (273 por minuto) | el USB nunca descansa |
| El agente sin unidades | 39 s de CPU, ~1 despertar por segundo | la mitad, recorrer las letras cada 30 s |
| Detectar cambios con avisos | 0 en reposo | caro solo en ráfagas, y por los avisos que lanzan pasadas de más |

La detección, que era la pregunta de partida, es lo que menos gasta. Lo que hace `watch` caro es lo
que dispara, y lo que hace caro al agente es lo que hace por reloj.

## Cómo se ha llegado aquí

Siete sondas en un Windows de verdad; 23 propuestas; cuatro revisiones independientes que intentaron
refutarlas contra el código. Ocho no pasaron (abajo, con su motivo) y salieron veinte ideas nuevas,
de las que entran las que se apoyan en algo medido.

## Las entregas

Ordenadas por lo que ahorran frente a lo que arriesgan. E = esfuerzo (S: horas, M: días, L: semanas).

### 0. Medir siempre (antes o a la vez que la 1)

- **El consumo, a la vista** (M). Contadores por unidad y día en el equipo, nunca en la unidad:
  pasadas, procesos, segundos, KB de listados. En «Ajustes»/Doctor: «hoy: 212 pasadas, 41 MB
  escritos». Sin esto no se puede saber si lo demás funciona en equipos reales.
- **Presupuestos como pruebas** (M). Tres o cuatro de las sondas, a `tests/rendimiento/`: el agente
  en reposo, las operaciones sobre una unidad quieta, los procesos y los KB de una pasada sin
  cambios. Lo que se gane no se pierde en silencio con el siguiente sondeo que alguien añada.

### 1. Menos pasadas (`common/planificador.py`, `sync.py`, `agente.py`)

- **La señal «esta pasada no movió nada»** (S). `sync.py` compara el cuerpo de los listados (sin la
  primera línea, que lleva la fecha) antes y después, y lo dice en una línea para el agente. Es el
  requisito de casi todo lo de abajo; hoy no existe.
- **El intervalo se estira** (M). Si varias pasadas seguidas de una pareja no mueven nada, su
  intervalo se dobla hasta un tope (propuesto: x4, máximo 30 min); una transferencia, un fallo, un
  aviso de `watch`, «Sincronizar ahora», reconectar la unidad, volver la red o abrir la ventana lo
  devuelven al de fábrica. El llavero y el modo `sync` no se tocan. Se ve: «cada 5 min (ahora cada
  20)». **De 53 pasadas por hora a unas 10 tras una hora quieta: −570 s de CPU, −2 800 procesos y
  −240 MB de escrituras al día** (esto último, con parejas de 1 000 ficheros). El precio: lo que
  cambie en el remoto tarda hasta el tope en bajar.
- **La separación aprende** (S). Lo mismo para las pasadas adelantadas por avisos: si salen vacías
  varias veces seguidas, la separación (120 s) se multiplica hasta un tope. Acota cualquier ruido,
  se sepa o no de dónde viene: del techo de 30 pasadas vacías por hora a 2–4 (estimado).
- **Una pareja saltada no se relanza** (S) hasta que cambie lo que la saltó. Hoy una que pide
  `--resync` arranca `sync.py` en cada intervalo para decir «Saltada», para siempre.
- **Los conflictos no se rebuscan tras una pasada que no movió nada** (S). Hoy cada pasada recorre
  con `os.walk` toda la carpeta local.
- **«Expulsar» sube antes lo pendiente** (M). Hoy descarta lo que estaba dentro de la calma y la
  unidad se va con ello sin subir. Es lo que permite fiarse de intervalos largos.

Política, a decidir por el dueño (no hace falta ninguna para lo anterior):
- intervalo propio por pareja en el TOML (el planificador ya lo admite; solo lo usa el llavero);
- intervalo por N con batería (hoy, o sincroniza igual o se para);
- con la sesión bloqueada o sin nadie delante, las pasadas por intervalo callan y hay una de puesta
  al día al volver (las de cambios siguen saliendo);
- el intervalo nunca menor que k veces lo que duró la última pasada sin cambios (protege las
  parejas grandes: con 10 000 ficheros, ~3 GB de listados al día a 5 min).

### 2. El motor de avisos de Windows, sin sorpresas (`common/avisos_carpeta.py`, `ui/bandeja_windows.py`, `common/huella.py`)

- **Agrupar lecturas** (S): esperar 1 s antes de volver a lanzar `ReadDirectoryChangesW`, con el
  plazo en la espera del hilo. Medido: −97 % de CPU y −98 % de despertares en ráfagas, sin perder
  avisos.
- **El efecto neto de los avisos** (M), en los dos sistemas: un nombre que nació y murió dentro de la
  tanda, o una carpeta que solo trae `MODIFIED`, no es un cambio; cualquier duda, sí. Quita los
  temporales de editor y el aviso tardío de NTFS sin fotos ni recorridos.
- **Renombrar la carpeta de la pareja** (S): al armar se guarda la ruta final del propio handle; si
  una tanda llega con otra, `PERDIDA`, como en Linux. **Y volver a los avisos tras una pérdida** (S)
  cuando la carpeta vuelve a existir, con tope de intentos.
- **Soltar la carpeta cuando piden el volumen** (M): la primera mitad de
  `2026-10-11-watch-windows-soltar-al-pedir-design.md` (`GUID_IO_VOLUME_LOCK`).
- **El recorrido** (S): el prefijo de ruta larga, para ver más allá de 260 caracteres. Las uniones,
  después de mirar qué hace rclone con ellas.
- **Decirlo**: con la vigilancia puesta Windows no deja renombrar las carpetas de arriba de la
  pareja. No tiene arreglo sin oír el volumen entero; va a la guía.
- **La prueba que falta** (S): el agente con el motor de verdad en Windows (`test_agente_watch.py`
  §11e solo corre con inotify).

Después, con más riesgo: respetar en los avisos las exclusiones de la pareja (M; traducir mal un
patrón de rclone retrasa un cambio real hasta el intervalo) y una lista corta de ruido de editor
excluida por defecto en las parejas nuevas (S).

### 3. El agente sin reloj (`agente.py`, `common/equipo.py`, `common/red.py`, `penwatch.py`)

Por pasos, sin rehacer `vuelta()`:
- no leer batería ni red sin raíces servidas (S); `GetLogicalDrives` como interruptor del recorrido
  de letras y la máscara de letras del aviso de volumen (S–M): el recorrido completo, cada 2–5 min;
- `cmd_run` espera lo que el planificador ya calcula (`Decision.mirar_en`, que hoy se tira), con
  topes cortos mientras haya pasada, hijo, ráfaga o unidad servida; un hijo que acaba despierta (M);
- el agente oye su propia carpeta de buzón en vez de intentar un renombrado en cada vuelta, y el
  contrato con la ventana de runsync pasa de ~9 operaciones en la unidad a 2–3 (M);
- el llavero: una sola foto de procesos por mirada y preguntar antes si su `KeePassXC.exe` está en
  uso (M); la red de uso medido, del aviso que `red.py` ya recibe (M).

Estimado, no medido: sin unidades, de 39 s de CPU al día a unos pocos; con una servida, de 273
operaciones por minuto en la unidad a 36–90.

### 4. Menos escritura y menos procesos (después de la 1)

- **El workdir de bisync fuera de la unidad** (L), con la unidad como única verdad: una marca de
  época escrita la última en la copia de vuelta, la copia del equipo solo vale si coincide, y un
  baseline aparcado no resucita nunca. Toca las invariantes del baseline: especificación propia.
  Tras la entrega 1 le quedan por quitar unos 60 MB al día de los 300.
- **Un `sync.py` por ciclo y raíz** (M), con el resultado por pareja en líneas legibles por máquina.
  −31 % de CPU del ciclo; tras la entrega 1 le quedan unos 40 s al día.

### 5. Avisos en los volúmenes de VeraCrypt

La segunda mitad de la especificación de la mañana, detrás de un ajuste y sin activar hasta verla en
un equipo real: la ventana de VeraCrypt, su desmontaje automático, `Expulsar PRDRIVE.bat` y un
pendrive. Ahorra el recorrido de esas parejas (2,7–3,0 s por hora quietas, 32–36 s con cambios, a
20 000 entradas) y su espera de hasta 2 min.

## Lo que no entra, y por qué

| Idea | Motivo |
|---|---|
| Una foto de confirmación antes de cada pasada por cambios | no ve lo que ve bisync (rutas largas, filtros, flags del TOML) y la foto de partida tras cada pasada cuesta más de lo que ahorra |
| Un handle por unidad en su raíz en vez de uno por pareja | oye todo el volumen y un desborde ajeno lanzaría una pasada vacía por pareja; en reposo no ahorra nada |
| Un tope para la calma | añade pasadas: un fichero que cambia sin parar se sincronizaría cada 2 min en vez de cada intervalo |
| rclone sin consola (`DETACHED_PROCESS`) | 4 puntos de CPU como mucho, y un remoto que lance un programa de consola abriría una ventana |
| Modo de eficiencia y modo de fondo de Windows | ningún efecto medible aquí; el modo de fondo choca con lo decidido en `prioridad.py` (el lock de bisync caduca). Medirlo antes en un portátil |
| Una marca de generación en el remoto | mirarla cuesta el 40 % de una pasada y no ve lo cambiado por fuera; el intervalo que se estira da lo mismo sin estado en el remoto |
| Subir solo el fichero guardado | el motor no guarda nombres y un `copy` pisa lo que otro dispositivo cambió, sin conflicto ni versión |
| Avisos del remoto (`ChangeNotify`) | pide un rclone residente y no existe en SFTP; como experimento, no como plan |
| Una firma más barata en el recorrido | −26 % de algo que con avisos casi no se usa |
| Un proceso residente por unidad; un agente que nace con cada pendrive | lo que ahorran ya lo dan las entregas 1 y 3 con menos riesgo |

## Lo que falta por ver en equipos reales

Un portátil (lo único que puede decir cuánto de todo esto son vatios); un pendrive de verdad
(extracción segura con la vigilancia puesta, suspensión del puerto, escritura sin caché); un remoto
de red (lo que cuesta listarlo: ahí el intervalo que se estira ahorra más de lo medido); un NAS para
los avisos por SMB (en bucle local contra Windows no se perdió ninguno).

## Lo construido (11/10/2026)

Un commit por entrega, cada uno con la suite entera en Windows, sus tests nuevos también en Linux
(WSL) y la comprobación de tiempos (`tests/rendimiento/`) contra el commit anterior. Medido con
`tests/rendimiento/consumo.py` (reloj de mentira, una instalación con bandeja) y, donde se dice,
con el motor de verdad:

| | Antes (0.7.2) | Después |
|---|---|---|
| Agente sin unidades, vueltas por hora | 1 800 | 120 |
| Unidad quieta dos horas: `sync.py` lanzados (dos parejas cada 5 min) | 48 | 16 con la entrega 1; 8 con la 4 |
| Unidad quieta dos horas: operaciones de fichero en la unidad | 30 048 | 5 035 |
| Bloquear el volumen con una carpeta vigilada (`FSCTL_LOCK_VOLUME`, motor de verdad) | falla los 4 intentos | sale al primero, 38 ms |
| Ráfaga de 300 ficheros en una carpeta vigilada (motor de verdad) | una lectura por aviso | 8 lecturas como mucho |

- **0, medir**: hecho. El parte de cada pareja (`common/parte.py`), la cuenta por unidad y día
  (`common/consumo.py`, en `agente.py status`) y los presupuestos (`consumo.*` en
  `tests/rendimiento/presupuesto.toml`, con una pasada de verdad en la CI).
- **1, menos pasadas**: hecho. El intervalo que se estira (de fábrica, x4 y 30 min; se apaga con
  `agente.py ajuste estirar_intervalo no`), la separación que aprende, la pareja saltada, los
  conflictos que no se rebuscan y «Expulsar», que sube antes lo pendiente. **Cambio respecto de la
  propuesta**: un aviso de `watch` no devuelve el intervalo al de fábrica por sí solo; lo devuelve
  la pasada que ese aviso adelanta, si mueve algo. Así el ruido no lo desestira. De la política
  opcional (intervalo por pareja, por N con batería, sesión ausente, tope por duración), nada.
- **2, el motor de Windows**: hecho. Agrupar, el efecto neto (también en Linux), la carpeta movida
  y volver a oír, soltar al pedir el volumen, la ruta larga, la prueba del agente con el motor de
  verdad. Sin hacer: las uniones (`mklink /J`) y los dos extras «con más riesgo» (las exclusiones
  de la pareja en los avisos, la lista de ruido de editor).
- **3, el agente sin reloj**: hecho en lo que más pesa. La espera de `cmd_run`
  (`cuanto_esperar()`, 30 s sin nada a la vista), el oyente del buzón, una lectura de `state/` por
  vuelta, el recorrido de respaldo a 2 min con `GetLogicalDrives`, y batería y red solo con algo a
  la vista. Con una unidad a la vista el tic sigue siendo de 2 s (cada uno, mucho más barato).
  Sin hacer: que un hijo que acaba despierte, el llavero (una foto de procesos por mirada) y la
  red de uso medido por su aviso.
- **4, menos procesos**: hecho «un `sync.py` por ciclo y raíz» (las parejas a las que les toca a
  la vez, con un minuto de margen; solo cuando el `sync.py` de la unidad ya escribe partes, y el
  llavero siempre aparte). Comprobado con `sync.py` y rclone de verdad sobre cuatro parejas. **Sin hacer, a propósito: el
  workdir de bisync fuera de la unidad.** Toca las invariantes del baseline y esta hoja ya pedía
  su propia especificación; no se construye sin ella ni sin una unidad de verdad delante.
- **5, VeraCrypt**: construido detrás de `agente.py ajuste avisos_veracrypt sí`, apagado de
  fábrica. Visto el 12/10/2026 con VeraCrypt Portable 1.26.29 de verdad en un sobremesa
  (`tests/maquina/f18_veracrypt_windows.py` 17/17 y `f23_veracrypt_ventana_windows.py` 15/15, en
  `maquina-real-resultados.md`): `/dismount` con y sin `/silent`, «Unmount All» de su ventana y
  su desmontaje automático por inactividad **sin forzar** desmontan con la carpeta vigilada sin
  preguntar nada; si otro programa lo impide, la vigilancia vuelve sola a los 5 s. Sin ver: el
  desmontaje automático forzando (el de fábrica de VeraCrypt), `Expulsar PRDRIVE.bat` entero y
  un pendrive. El ajuste sigue apagado hasta que lo decida el dueño.

Lo que solo puede decir un equipo real está en
`docs/superpowers/pruebas/2026-09-25-equipo-pendiente-en-real.md` («Menos consumo y el motor de
avisos de Windows»).

## Preguntas para el dueño

1. **¿Se empieza por la entrega 1?** Es la que más ahorra y no toca el motor.
2. **El intervalo que se estira, ¿activado de fábrica?** ¿Con qué tope (propuesto: x4, 30 min)?
3. **De la política**, ¿qué entra: intervalo por pareja, por N con batería, sesión ausente, tope por
   duración?
4. **El consumo a la vista**: ¿en «Ajustes», en Doctor, o solo en `agente.py status`?
5. **VeraCrypt**: ¿se espera a tener un equipo real donde verlo, como se propone?
