# `watch = true` y el consumo del agente en Windows: medidas (11/10/2026)

Base de `docs/superpowers/specs/2026-10-11-watch-y-energia-hoja-de-ruta-design.md`.

**Equipo**: sobremesa i5-8500 (6 núcleos, no híbrido), Windows 11 IoT LTSC 26100, sesión interactiva
elevada, Python 3.14, rclone 1.75.1, con el agente 0.7.2 del usuario corriendo.
**Sin batería ni contadores de energía**: la energía se estima con CPU, despertares (cambios de
contexto), E/S y procesos lanzados; no hay un solo vatio medido. Los discos de prueba eran virtuales
(exFAT, NTFS, FAT32), no pendrives, y el remoto, una carpeta local.

**Método**: siete sondas desechables (fuera del repositorio), cada una una pregunta, con el motor
de verdad (`avisos_carpeta.ReadDirectoryChanges`) y una ventana oculta como la de la bandeja; el
agente, con el arnés de `tests/_agente_falso.py`; las pasadas, con una unidad desechable y el
`sync.py` y el rclone de verdad. La CPU va en ciclos (`QueryProcessCycleTime`) o por el job de
Windows; el reloj llevaba ruido de otras sondas y no se cita salvo que se diga. «✔✔» = el guion se
volvió a lanzar aparte y dio lo mismo.

## 1. Qué gasta qué

| Qué | Cuánto | Nota |
|---|---|---|
| Agente en reposo, sin unidades (el real, 24 h vivo) | 0,455 ms/s de CPU de media (39 s/día), ~1 despertar/s, 0 escrituras | el tic de 2 s son 0,21 ms/s; el recorrido de letras cada 30 s, el 51 % de la CPU y el 72 % de los despertares |
| Cada tic sin unidad | un `os.replace` que falla sobre `agente.pide` (el buzón) | la mitad del tic |
| Cada tic con una unidad servida | ~9 operaciones de fichero en la unidad, 1,5–2 ms de CPU, 20–61 operaciones de E/S; 0 escrituras | 273 operaciones por minuto: un USB nunca queda sin tráfico |
| Batería y red de uso medido, cada 60 s | la red por COM: 5,1 ms y ~31 despertares en RpcSs/netprofm; la batería, 0,1 ms | `GetNetworkConnectivityHint` cuesta 2 µs |
| Llavero servido: `_mirar_keepassxc` cada 10 s | recorre ~330 procesos: 28 ms y 2 058 operaciones por mirada (2,8 ms/s) | unas 6 veces todo el agente en reposo |
| **Una pasada bisync sin cambios**, 100 ficheros ✔✔ | 0,62–0,66 s de CPU, 3 procesos (pythonw, rclone, conhost) | 0,26 s son arrancar Python; de los 0,31 s de rclone, 0,22 s son arrancar. Con 10 000 ficheros: 1,3 s (bisync), 0,9 s (up) |
| Las pasadas del diario real (10/10, 4 parejas, 5 min) | 53 por hora; 259 s de procesos hijos vivos por hora | ~711 s de CPU y 3 456 procesos al día |
| **Lo que una pasada bisync sin cambios escribe en la unidad** ✔✔ | reescribe enteros sus 4 listados (solo cambia la fecha de la 1ª línea), más `.lck`, 2 `.lst-new` y `last_run.tmp`: 32 KB con 100 ficheros, 268 KB con 1 000 | 4 parejas cada 5 min: 36 o 300 MB al día (108 GB al año); `up`: 3 ficheros, 2–11 KB |
| Tras cada pasada, buena o mala | `conflicts.actualizar_pareja()` recorre con `os.walk` toda la carpeta local (`sync.py`, `report_conflicts`) | no medido aparte |
| Una pareja que pide `--resync` sin aprobar | se relanza en cada intervalo: `sync.py` arranca, dice «Saltada» y sale (`pl.registrar` la cuenta como buena) | ~0,35 s por lanzamiento, estimado |
| Detectar con avisos, en reposo ✔✔ | 0 ms y 0 despertares con 1, 10 y 60 parejas; 70 KB de memoria por pareja | |
| Detectar con avisos, por evento ✔✔ | un despertar y 85–130 µs por aviso, sin agrupar: 20 000 ficheros, 1,3 s (exFAT) o 2,6 s (NTFS) y 20 000–33 000 despertares; un fichero reescrito 50 veces por segundo, 10 ms/s y 100 despertares/s | lo mismo los avisos de carpetas ignoradas (`.prdrive`); con 60 parejas armadas, x2,3 |
| Detectar con el recorrido, 20 200 entradas | 88–100 ms de CPU cada uno: quieta, 2,7–3,0 s/h; con cambios, 32–36 s/h | con el tope de fábrica (20 000) ese árbol ya sale «cortada» |
| Cualquier lanzamiento de rclone | ≥ 250 ms de CPU | sondear el remoto con rclone cuesta casi una pasada pequeña |

Con una unidad conectada pesan, por este orden: las pasadas por intervalo (CPU, procesos y escrituras
en flash), el tic con la unidad servida y, muy por detrás, la detección. Sin unidad, el recorrido de
letras.

## 2. El motor de avisos de Windows

1. **Relanza la lectura en el acto** (`_acabada`). Esperando antes de relanzar ✔✔: goteo de 50 Hz, de
   10,5 a 0,70 ms/s con 0,25 s y a 0,28 ms/s con 1 s (despertares, de 100/s a 4,7 y 1,2); avalancha de
   5 000 ficheros con 1 s, de 359 ms y 5 041 despertares a 6,4 ms y 11, sin perder un registro ni
   desbordar el búfer de 64 KB (la tanda mayor, 47 KB). Con un búfer de 4 KB desborda, que ya cuenta
   como cambio.
2. **NTFS retiene el `MODIFIED` de una carpeta hasta que alguien la enumera o le hace `stat`** ✔✔: tras
   escribir dentro, un `listdir`, el propio recorrido o una ventana del Explorador lo hacen llegar (a
   +3 s o cuando sea) y cuenta como cambio: tras una pasada que escribió, una lectura ajena lanza una
   pasada de más. exFAT y FAT32 no lo hacen. Linux ignora `IN_ATTRIB` de carpetas.
3. **Renombrar o mover la carpeta de la pareja no avisa** ✔✔ (36 de 36): el handle sigue a la carpeta
   movida, el motor sigue dando cambio por lo que pase ahí, la carpeta nueva con el nombre de siempre
   queda sorda y `vigilar()` no hace nada. En Linux es `IN_MOVE_SELF` → `PERDIDA`.
   `GetFinalPathNameByHandleW` da la ruta nueva en 40–66 µs.
4. **Con la vigilancia puesta no se puede renombrar ni mover ninguna carpeta antecesora** ✔✔
   (`WinError 5`, 36 de 36, NTFS, exFAT y FAT32; sale en cuanto se suelta el handle). Es regla de
   Windows para cualquier handle abierto en el subárbol; no llega ningún aviso del intento. Borrarlas
   sí se puede (y da `PERDIDA`).
5. **Tras una `PERDIDA` la pareja se recorre para siempre** en esa conexión (28 recorridos en 40 min)
   aunque `vigilar()` la armaría bien.
6. La calma no tiene tope: un fichero que cambia cada 10 s durante 10 min deja 0 pasadas por cambios.
7. En NTFS un fichero escrito con `flush` pero abierto no avisa hasta `fsync` o cerrar; por `mmap`,
   nunca (ni cambian su tamaño ni su fecha).
8. Avisan sin cambio que sincronizar: temporales que nacen y mueren (`~$doc.docx`), reescribir lo
   mismo, la fecha de una carpeta.
9. En reposo, leyendo o listando: 0 avisos en las cuatro bases y en la raíz de un volumen (90 s).
10. `_correr` rehace la lista de eventos y hace un `WaitForSingleObject` por pareja en cada despertar.
11. Con el agente de verdad: ráfaga de 50 ficheros, una pasada a los 20 s; separación de 120 s exacta;
    en pausa los avisos se apuntan; 20 000 ficheros no desbordan; al irse la unidad no queda nada
    abierto (150 ciclos de armar y dejar: los mismos handles).
12. Volúmenes de VeraCrypt y bloqueo del volumen: medidos por la mañana, en
    `docs/superpowers/specs/2026-10-11-watch-windows-soltar-al-pedir-design.md`.

## 3. El recorrido (`huella.de_carpeta`) en Windows

- No ve nada a más de 260 caracteres de ruta (lo salta en silencio; con el prefijo de ruta larga, sí) ✔✔.
  El motor de avisos sí lo oye.
- Entra en las uniones (`mklink /J`), al revés de lo que dice su docstring; una unión en bucle le
  quita la foto (`None`, `WinError 1921`) ✔✔. Qué hace rclone con una unión no se ha mirado.
- No ve un cambio del mismo tamaño dentro de los 2 s de resolución de fecha de exFAT y FAT32.
- Una firma con `hash()` de la tupla en vez de blake2b: −26 % ✔✔.

## 4. Carpetas de red (SMB contra el propio Windows, en bucle local)

`ReadDirectoryChangesW` por UNC avisa de todo lo que se cambia por la ruta local: 0 perdidos de 1 600,
mediana 0,3–3,4 ms. Hoy lo impiden dos puertas del motor: `DRIVE_REMOTE` y que el registro de
extracción es imposible en red (error 1066). El búfer no puede pasar de 65 536 bytes (con más, la
lectura acaba con error 87). El recorrido por UNC cuesta x3,3 de reloj. No es un NAS con Samba ni
una red que se cae.

## 5. Palancas medidas como prueba de concepto

- El workdir de bisync fuera de la unidad ✔✔: los 4 listados, los `.lst-new` y el `.lck` dejan de
  escribirse en ella (266–351 KB por pasada sin cambios de 1 000 ficheros); copiando de vuelta solo
  los listados cuyo cuerpo cambia, la pasada normal siguiente no pide `--resync`. `last_run.json` y
  `historial.jsonl` se siguen escribiendo.
- Un `sync.py` por ciclo en vez de uno por pareja: −31 % de CPU, 12 → 9 procesos.
- El modo de eficiencia (`ProcessPowerThrottling`): la llamada se acepta y no se hereda a los hijos;
  el modo de fondo (prioridad de E/S y de memoria) sí. Su efecto, sin medir (ni batería ni núcleos de
  eficiencia).
- Un Python esperando sin plazo: 0,003 ms/s y 0,17 despertares/s.
- Sin efecto medible: `GOMAXPROCS`/`GOGC`, `--check-sync false`, `--dry-run` como sonda (escribe y
  cuesta lo mismo), quitar `--recover`, `rclone cat` como sonda (250 ms), los imports perezosos solos.

## 6. Lo que no se ha visto

Un portátil (vatios, batería, núcleos de eficiencia); un pendrive de verdad (la política de extracción
rápida, la suspensión del puerto USB, la extracción segura con la vigilancia puesta); un remoto de red
(lo que cuesta listarlo); un NAS; el antivirus en tiempo real (estaba desactivado); Linux.

## 7. Lo que costó medir, para no repetirlo

- Desmontar un volumen de VeraCrypt con `/force` y, después, `sc stop veracrypt`, dejaron su
  controlador a medio descargar: ningún VeraCrypt portable arranca en el equipo hasta reiniciar.
- Una unidad de mentira con `.prdrive\PRDRIVE` en la raíz de un disco virtual: el agente real del
  usuario la tomó por una unidad nueva y le avisó. En una subcarpeta no la ve.
- `tests/maquina/correr.py --de-verdad` F15 y F16 dejan sus discos virtuales conectados.
