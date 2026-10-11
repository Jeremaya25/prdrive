# `watch = true` en Windows: soltar la carpeta cuando piden el volumen, y avisos también en VeraCrypt — diseño

Fecha: 11/10/2026. Continúa `docs/superpowers/specs/2026-10-06-watch-con-avisos-design.md`
(fases 1 y 2, ya en código) y **revisa la respuesta a su pregunta 2**: F18 se
contestó en una máquina de GitHub sin escritorio interactivo, que no entrega
`WM_DEVICECHANGE` a las ventanas (lo vio F15 el mismo día), así que su «no llega
ningún aviso al desmontar» no vale para un equipo de verdad. Lo que hay hoy
está en `docs/agents/reference/agent-scheduling.md` («Windows,
`ReadDirectoryChangesW`»). Estado: **propuesta, sin código**.

**Revisión de la tarde del 11/10/2026** (`2026-10-11-watch-y-energia-hoja-de-ruta-design.md`): se
parte en dos. Soltar la carpeta al `GUID_IO_VOLUME_LOCK` en un volumen normal va en la entrega 2 de
esa hoja de ruta; los avisos en volúmenes de VeraCrypt, en la 5, detrás de un ajuste y sin activar
hasta verlos en un equipo real. En las dos, ninguna E/S con el cerrojo del motor tomado:
`dispositivo()` lo toma desde el hilo de la bandeja y VeraCrypt solo reintenta 1,5 s.

## Qué se quiere

Que en Windows una pareja vigilada se comporte como en Linux: avisos del sistema
en todo volumen local, y que la carpeta que el motor deja abierta no estorbe a
nadie que pida el volumen.

Hoy, visto el 11/10/2026 en un Windows 11 con escritorio interactivo:

1. **Un volumen de VeraCrypt se recorre siempre** (la unidad cifrada abierta con
   «Abrir PRDRIVE», la raíz cifrada del equipo). En Linux su volumen es un
   montaje local más (`avisos_carpeta.DE_RED` no lo excluye) y se le ponen
   vigilancias. En Windows: un recorrido cada 10 s tras un cambio y cada 2 min
   con la carpeta quieta, un cambio tras un rato de calma tarda hasta 2 min en
   verse, el tope de 20 000 entradas sigue, y su llavero, cuando se vigila, se
   recorre siempre cada 10 s (`pl.cada_cuanto()`).
2. **En un volumen sin cifrar, la carpeta abierta hace fallar a quien pide el
   volumen en exclusiva** (`FSCTL_LOCK_VOLUME`: comprobar el disco, formatear,
   otro programa que expulsa) si no pasa por el «Expulsar» o
   el «Bloquear» del agente, que la sueltan antes. Windows sí avisa al handle
   registrado (`DBT_CUSTOMEVENT` con `GUID_IO_VOLUME_LOCK`), antes de decidir el
   bloqueo; la bandeja tira ese aviso.

**Criterios de éxito:**
- una pareja vigilada en un volumen de VeraCrypt no se recorre, y del cambio a
  la pasada va la calma (20 s) y unos segundos;
- desmontar ese volumen sin forzar desde fuera del agente (la ventana de
  VeraCrypt, `Expulsar PRDRIVE.bat`) funciona con la vigilancia puesta, sin
  «¿forzar?»;
- con la vigilancia puesta en un volumen sin cifrar, un `FSCTL_LOCK_VOLUME` de
  cualquiera sale a la primera;
- lo que hoy funciona (extracción segura, «Expulsar», «Bloquear», el recorrido
  donde no hay avisos) sigue igual.

## Lo medido (11/10/2026)

Windows 11 IoT LTSC (26100), sesión interactiva, Python 3.14. Sondas
desechables, fuera del repositorio; el oyente es una ventana oculta de nivel
superior como la de la bandeja (`WS_POPUP`, `WS_EX_TOOLWINDOW`).

**VeraCrypt Portable 1.26.29**, contenedor de 200 MB montado con `/m rm`, con
exFAT y con NTFS dentro (los dos dan lo mismo):

| Qué | Resultado |
|---|---|
| `RegisterDeviceNotificationW` del handle de una carpeta suya | no se puede, error 1066 (como F18) |
| `ReadDirectoryChangesW` dentro (crear, guardar, renombrar, subcarpeta, borrar) | avisa, el primero a los 3–5 ms; quieta 3 s, nada |
| `/dismount` sin forzar con la carpeta abierta, **sin soltarla** | `rc=1` a los 2,2 s, sigue montado. A la ventana llega `DBT_DEVICEREMOVEPENDING` de tipo volumen con la máscara de su letra, **antes** del primer intento, y nada más |
| Lo mismo **soltándola al llegar ese aviso** | `rc=0` en 0,55–0,6 s (lo que tarda sin nada abierto); después llega `DBT_DEVICEREMOVECOMPLETE` |
| Soltándola 0,5 s y 1,2 s tarde | `rc=0` en 1,1 s y 1,7 s: VeraCrypt reintenta 1,5 s (lo que ya dice `install/vestibulo.py`) |
| Oyente **sin elevar** (tarea programada, como el agente) y VeraCrypt elevado | recibe el aviso y suelta: `rc=0` en 0,62 s; sin soltar, `rc=1` |
| `/dismount /force` con la carpeta abierta | se desmonta; la lectura pendiente **no acaba nunca**; llega `DBT_DEVICEREMOVECOMPLETE` |
| «Expulsar» del Explorador (verbo `Eject`) sobre su letra | no hace nada, ni con todo cerrado |
| Un recorrido (`huella.de_carpeta()`) de 19 190 entradas | 94–109 ms de CPU en caliente; recién montado, 141 ms de CPU y 200–290 ms de reloj |

**Volumen sin cifrar** (disco virtual, exFAT y NTFS):

| Qué | Resultado |
|---|---|
| El agente de verdad (`Agente` con el arnés de `tests/_agente_falso.py`) y el motor de verdad, en una carpeta del equipo (NTFS) y en la raíz de un disco exFAT | se vigila con avisos, cero recorridos, un fichero nuevo lanza «(han cambiado sus ficheros)» tras la calma, lo que escribe la pasada no lanza otra, `.prdrive/` no cuenta |
| `FSCTL_LOCK_VOLUME` (4 intentos, como `expulsar._expulsar_windows()`) con la carpeta vigilada y registrada, sin soltarla | falla los 4. En cada intento llega `DBT_CUSTOMEVENT`/`GUID_IO_VOLUME_LOCK` y, 2–13 ms después, `GUID_IO_VOLUME_LOCK_FAILED` |
| Lo mismo **soltándola al llegar `GUID_IO_VOLUME_LOCK`** | el bloqueo sale **al primer intento** (10–40 ms): el sistema espera a que la ventana atienda el aviso antes de decidir. Al soltar el bloqueo llega `GUID_IO_VOLUME_UNLOCK`: el registro sigue avisando con el handle ya cerrado |
| `expulsar._expulsar_windows()` sin `dejar_raiz()` antes, soltando al aviso | sale bien: `VOLUME_LOCK`, `VOLUME_DISMOUNT`, `VOLUME_UNLOCK` (y `VOLUME_MOUNT` cuando alguien vuelve a tocar el disco virtual) |
| F15 tal cual, por primera vez con escritorio: «Expulsar» del Explorador | no manda `DBT_DEVICEQUERYREMOVE`: manda `DBT_CUSTOMEVENT`, y el volumen se va aunque no se suelte y aunque otro programa tenga un fichero abierto (el Explorador fuerza). La pareja se pierde, como debe. **Un disco virtual no sirve para probar la extracción de un pendrive** |

No visto: un pendrive de verdad (no había ninguno montado), la ventana de
VeraCrypt y su desmontaje automático (solo `/dismount` por línea de órdenes).

**Lo que costó la sonda**, para no repetirlo: tras desmontar con `/force` el
controlador portable de VeraCrypt ya no se descargó, y un `sc stop veracrypt`
lo dejó a medio descargar; desde ahí ningún VeraCrypt portable arranca en ese
equipo («El servicio especificado se ha marcado para ser eliminado») hasta
reiniciar. Ninguna prueba en un equipo que no sea de usar y tirar desmonta
forzando.

## Enfoques

**A. Soltar al pedir, con dos avisos y una sola reacción (el recomendado).** El
motor cierra la carpeta en cuanto alguien pide el volumen y la vuelve a abrir si
al final no se va. Quién lo dice depende del volumen: Windows al handle
registrado (`GUID_IO_VOLUME_LOCK`, además del `DBT_DEVICEQUERYREMOVE` de hoy) y
VeraCrypt a todas las ventanas (`DBT_DEVICEREMOVEPENDING` de su letra). Con eso
los volúmenes de VeraCrypt dejan de ser una excepción.

**B. Solo VeraCrypt.** Lo mismo sin atender `GUID_IO_VOLUME_LOCK`. Menos
código, pero deja el segundo problema y la bandeja se toca igual.

**C. A, y además una ventana propia del motor** en su hilo
(`MsgWaitForMultipleObjects`), como `common/red.py` es independiente de la
bandeja: desaparece «sin bandeja no hay motor» y todos los cierres pasan a un
solo hilo. Más limpio, pero es rehacer el hilo del motor para un caso (el agente
sin bandeja) que casi no se da. Puede venir después sin deshacer nada de A.

Descartados, sin probarlos: el diario USN (solo NTFS; los pendrives van en
exFAT), las notificaciones del shell (`SHChangeNotifyRegister`:
el handle lo tendría shell32 dentro del agente, con un contrato peor
documentado) y abaratar el recorrido (la especificación anterior midió su suelo:
el problema es la espera y el despertar periódico, no el hash).

Se recomienda **A**.

## Diseño

### El motor (`common/avisos_carpeta.py`, `ReadDirectoryChanges`)

Una vigilancia está **activa** (handle abierto, lectura lanzada), **callada**
(handle cerrado porque alguien pidió el volumen; ni avisa ni se recorre) o deja
de existir (`PERDIDA`, o `dejar()`). Hoy solo la calla `DBT_DEVICEQUERYREMOVE`.

**Volumen normal** (se registra como hoy). `dispositivo(evento, handle, guid)`
gana el `DBT_CUSTOMEVENT`, con los GUID de `ioevent.h`:

| Aviso | Reacción |
|---|---|
| `GUID_IO_VOLUME_LOCK` | cerrar el handle en el acto (dentro del aviso: el sistema espera) y callar; el registro se conserva |
| `GUID_IO_VOLUME_LOCK_FAILED` | volver a abrir |
| `GUID_IO_VOLUME_UNLOCK` sin `GUID_IO_VOLUME_DISMOUNT` desde el bloqueo | volver a abrir |
| `GUID_IO_VOLUME_DISMOUNT` | sigue callada: abrirla ahora volvería a montar un volumen que alguien acaba de desmontar para quitarlo |
| `GUID_IO_VOLUME_MOUNT` | volver a abrir |
| `DBT_DEVICEQUERYREMOVE`, `…QUERYREMOVEFAILED`, `…REMOVEPENDING`, `…REMOVECOMPLETE` | como hoy |

Los demás GUID se ignoran. Volver a abrir es lo que ya hace
`DBT_DEVICEQUERYREMOVEFAILED` (una petición al hilo del motor), y **cuenta como
un cambio**: entre cerrar y abrir no se ha oído nada.

**Volumen de VeraCrypt.** `vigilar()` deja de rechazarlo. No se registra (no se
puede) y la vigilancia apunta su letra. Un método nuevo, `volumen(evento,
letras)`, que la bandeja llama con los avisos de tipo volumen:

| Aviso de su letra | Reacción |
|---|---|
| `DBT_DEVICEREMOVEPENDING` | cerrar el handle en el acto y callar, con un plazo (`REARMAR_VERACRYPT`, 5 s) |
| `DBT_DEVICEREMOVECOMPLETE` | `PERDIDA` (`MOTIVO_DESMONTADA`), esté activa o callada |
| pasa el plazo y la letra sigue siendo de VeraCrypt | volver a abrir, y cuenta como un cambio |
| pasa el plazo y ya no lo es | `PERDIDA` |

- El plazo existe porque VeraCrypt no dice que el desmontaje ha fallado o se ha
  cancelado. Cinco segundos cubren de sobra su segundo y medio de reintentos; si
  entonces está preguntando «¿forzar?» por algo de otro, reabrir no estorba:
  forzar no necesita la carpeta cerrada, y un «sí» vuelve a mandar el aviso.
- El plazo lo lleva el hilo del motor: su `WaitForMultipleObjects` deja de
  esperar sin límite mientras haya alguno.
- `DBT_DEVICEREMOVECOMPLETE` es la única señal de un desmontaje forzado: la
  lectura pendiente no acaba.
- Solo se atienden los avisos de volumen de las letras que el motor tiene como
  de VeraCrypt: el `DBT_DEVICEREMOVECOMPLETE` de un pendrive normal sigue
  llegando por su handle.

Lo demás no cambia: una carpeta de red sigue sin avisos, el tope de 63 parejas,
`descartar()`, el filtro de la raíz de la pareja.

### La bandeja (`ui/bandeja_windows.py`)

Sigue sin decidir nada: lee el aviso y lo pasa antes de contestar a Windows.
- `Api.handle_de()` pasa a `Api.aviso_de(lparam)`: de un `DEV_BROADCAST_HANDLE`,
  su handle y su `dbch_eventguid`; de un `DEV_BROADCAST_VOLUME`, las letras de
  `dbcv_unitmask`.
- `WM_DEVICECHANGE`: los avisos de un handle (ahora también `DBT_CUSTOMEVENT`)
  van a `Bandeja.dispositivo(evento, handle, guid)`; `DBT_DEVICEREMOVEPENDING` y
  `DBT_DEVICEREMOVECOMPLETE` de tipo volumen, a `Bandeja.volumen(evento,
  letras)`. Un fallo de quien atiende no impide contestar, como hoy.
- `agente.poner_avisos_carpeta()` engancha los dos.

### En el agente

- El planificador no se toca: reabrir es un `CAMBIO` más.
- `_soltar_avisos()` antes de «Expulsar» y «Bloquear» se queda: es lo que
  garantiza el orden sin depender de que la ventana atienda a tiempo.
- `MOTIVO_VERACRYPT` desaparece de `Agente.sin_avisos` y de `agente.py status`.
- **La invariante «nada abierto en la unidad entre pasadas»** (`agent.md`):
  en Windows la carpeta de cada pareja vigilada queda abierta también en un
  volumen de VeraCrypt, y se cierra cuando VeraCrypt anuncia el desmontaje o
  alguien pide el volumen.

### Lo que ve la persona

Nada nuevo en ninguna ventana. Una unidad cifrada sincroniza a los 20 s de
guardar en vez de hasta 2 min 20 s, y nadie se encuentra «en uso» por el agente.

## Riesgos, dichos en voz alta

- **La ventana de la bandeja ocupada más de 1,5 s** cuando VeraCrypt anuncia el
  desmontaje: VeraCrypt dirá que hay algo abierto y preguntará si forzar. Decir
  que no y repetir funciona. Hoy ese riesgo solo existe mientras dura un
  recorrido (`_mirando()`).
- **Un camino de VeraCrypt que no anuncie.** Lo medido es `/dismount`; de memoria
  de su código, el botón de su ventana y el desmontaje automático pasan por la
  misma función, pero no está visto. Si alguno no anuncia, ese preguntaría si
  forzar: es una fila de equipo real, y la salida es volver a recorrer.
- **Reabrir de más.** Un programa que pide el bloqueo en bucle haría cerrar y
  abrir cada vez, con un cambio apuntado cada vez; la separación (120 s) acota
  las pasadas que salen de ahí.
- **Un pendrive de verdad** no se ha visto en ninguna de las dos fases: la
  extracción segura con la vigilancia puesta sigue siendo la fila F15.
- **Sin bandeja no hay motor**, como hoy.

## Lo que no se hace

- La ventana propia del motor (enfoque C).
- Avisos en carpetas de red: en Windows SMB los da el servidor y podrían valer,
  pero depende de cada NAS y no está probado.
- Quitar el recorrido: sigue siendo el respaldo.

## Pruebas

- **El motor contra un `Win32` de mentira** (`tests/test_avisos_carpeta.py`):
  cada fila de las dos tablas; el plazo que vence con la letra presente y sin
  ella; `dejar()` y `dejar_raiz()` de una callada; un aviso de volumen de una
  letra que no es de VeraCrypt no hace nada; `GUID_IO_VOLUME_UNLOCK` tras
  `GUID_IO_VOLUME_DISMOUNT` no reabre.
- **La bandeja** (`tests/test_bandeja_windows.py`): pasa el GUID de un
  `DBT_CUSTOMEVENT` y las letras de un aviso de volumen, antes de contestar; lo
  que no es de un handle ni de un volumen, a nadie.
- **El agente con el motor de verdad en Windows** (`tests/test_agente_watch.py`,
  junto a §11e, que hoy solo corre con inotify): una ventana oculta y la sonda de
  arriba. Es un hueco que ya existía: en Windows el cableado solo se prueba con
  un motor de mentira.
- **`tests/maquina/`**: F18 se rehace (avisa dentro; con el aviso se desmonta
  sin forzar; sin él, no) y deja de forzar en su limpieza; una fila nueva para
  el bloqueo en un disco virtual (las tres filas de `FSCTL_LOCK_VOLUME`); F15
  dice que necesita un pendrive. Las tres necesitan escritorio interactivo: en la
  nube se saltan, como F15 hoy.
- **Equipos reales**: la ventana de VeraCrypt y su desmontaje automático con la
  vigilancia puesta; `Expulsar PRDRIVE.bat`; «Bloquear» de la raíz cifrada;
  comprobar el disco de un pendrive vigilado.

## Preguntas abiertas

1. **¿Reabrir cuenta como un cambio?** Es lo prudente (no se ha oído nada
   mientras estaba cerrada) y cuesta, como mucho, una pasada de más. La
   alternativa es no apuntar nada y que lo de ese hueco espere al intervalo.
2. **El plazo de 5 s** para volver a abrir en un volumen de VeraCrypt.
3. **¿Entra el enfoque C?** Se propone que no.
