# El llavero con un segundo dispositivo en exFAT — resultados

Fecha: 15/10/2026. Issues: #115 («Llavero: añadir un segundo dispositivo en exFAT deja el llavero del primero fallando») y #116 («Llavero: conflictos en un dispositivo exFAT que no ha tocado la base, y la copia vieja puede ganar»), los dos bloqueados por #114 (`modify-window`, ya en `main`). Código: rama `issue-115-llavero-exfat`, de `4ae9ac0`. Prueba en la nube: F32 (`tests/maquina/f32_llavero_dos_dispositivos_windows.py` y `_linux.py`, con `llavero_dos.py`).

El guion de las pruebas del 12/10 (LL-6 y LL-7, en `docs/superpowers/pruebas/2026-10-12-pendrive-w11-resultados.md`) se perdió con su rama (`claude/tests-issues-keychain-9077e0`); F32 lo escribe otra vez a partir de los issues.

## 1. Lo que dice el código de rclone v1.75.2

Leído en el tag `v1.75.2` (el que fija `common/pins.py`), no de memoria:

- **`--resync-mode newer` respeta `--modify-window`.** Es `ci.UpdateOlder = true` (`setResyncConfig()`, `cmd/bisync/resync.go`), y `NeedTransfer()` (`fs/operations/operations.go`) compara con `fs.GetModifyWindow()`: si la copia de destino va por delante **menos** que la ventana no hay nada que hacer; con una diferencia de la ventana o más, ya cuenta («Destination is newer» o, si el contenido es igual, «Updated modification time in destination»). Con la ventana de 2 s de #114, el redondeo de exFAT (+1,457 s medido, siempre por debajo de 2 s) deja de tocar la hora de la base en el remoto: **la causa 1 de #115 desaparece con #114.**
- **La causa 2 sigue**: `LEEME.txt` lo crea cada dispositivo con la hora de ese momento. Si el de B es 2 s o más más nuevo que el del remoto, el `--resync` de B le cambia la hora al del remoto.
- **`--force` salta exactamente dos comprobaciones** (`opt.Force` en `cmd/bisync/operations.go`, líneas 348 y 357, cada una en su `if !opt.Force`): `excessDeletes()` y «all files were changed». Ningún otro sitio de `cmd/bisync` lo lee (se buscó en todos los ficheros del paquete), y por eso no se puede dejar un `--max-delete` estricto junto a él. La comprobación de la carpeta local es de prdrive (`_bisync_preflight()`, antes de la primera orden de rclone), así que `--force` no la toca. La de borrados va antes: un log que dice «all files were changed» ya la había pasado, **pero la repetición es otra ejecución que vuelve a listar los dos lados**, y con `--force` lo que se borrara entre una y otra no frenaría. Por eso la repetición se simula antes (`--dry-run --force`) y solo se fuerza si no borra nada (revisión de la PR #149).

## 2. En la nube: F32

Dos dispositivos montados como el instalador (`install/deploy`), cada uno en su disco virtual (Windows: NTFS y exFAT en VHD; Linux: ext4 y exFAT en loop), contra el mismo remoto `local`, con el rclone fijado. Todo lo hace el código de cada dispositivo (`llavero_editor.plan_activar` y `sync.py keychain`); lo único que pone la prueba son los guardados, con una base KDBX 4 de mentira pero entera (`kdbx.comprobar()` la da por buena y su semilla cambia en cada guardado) y la hora que ella elige. En Windows el exFAT guarda la hora **+1,457 s por delante** (la medida de F3); las bases van en un segundo par, el peor caso (+1,877 s).

- **LL-6** (#115): A activa y pasa; B (3,5 s después, para que sus `LEEME.txt` se distingan de verdad) «trae el del remoto» y pasa; se mira que B no le cambie la hora a nada del remoto y que A, después, pase sin ver ningún cambio.
- **LL-7** (#116): B no toca nada. A guarda y pasa; B pasa; A guarda otra vez y pasa; B pasa. Con los dos guardados de A a 1,2 s y a más de 2 s. B no puede tener conflicto, ni ganar su copia vieja, ni verse «con cambios sin subir» nada más bajar.
- **La repetición** (#115): el remoto cambia de hora los dos ficheros (lo que le hacía B a A); a A le llega «all files were changed».

### Con #114 solo (`origin/main`, rama de control `claude/control-llavero-solo-114`, sin lo de #115)

Ejecución [38747341500](https://github.com/Jeremaya25/prdrive/actions/runs/38747341500): `RESULTADO F32 W fallo 19/24` y `RESULTADO F32 L fallo 19/24`.

| Paso | Windows (NTFS + exFAT) | Linux (ext4 + exFAT) |
|---|---|---|
| LL-7, guardados a 1,2 s y a más de 2 s: sin conflicto en B, no gana su copia vieja, B no se ve con cambios sin subir | **bien** (todas) | bien (todas) |
| LL-6: B trae el llavero y A pasa (rc 0) | bien | bien |
| LL-6: la primera pasada de B no cambia la hora de nada del remoto | **falla**: `LEEME.txt` pasa de la hora de A a la de B (+5,7 s); la base **no** se toca | falla (igual) |
| LL-6: A, después, no ve ningún cambio | **falla**: `File changed: time (newer) - LEEME.txt`, rc 0 (un fichero de dos: no llega a parar) | falla (igual) |
| La repetición: los dos ficheros cambian de hora en el remoto | **falla**: `Safety abort: all files were changed on Path2`, rc 1, y no se arregla solo (A y B) | falla (igual) |

Una primera versión del guion (ejecución [38745942671](https://github.com/Jeremaya25/prdrive/actions/runs/38745942671)), con A y B activados a menos de 1 s y la base en un segundo impar, dio lo mismo en LL-7 y en la repetición (`fallo 20/23`) y no veía lo de `LEEME.txt`: por eso se endureció.

### Con los arreglos de #115 (rama `issue-115-llavero-exfat`)

Ejecución [38756095655](https://github.com/Jeremaya25/prdrive/actions/runs/38756095655), la de la PR #149 sobre `b752ef0`, la que prueba lo que se publica: `RESULTADO F32 W ok 28/28 · exFAT: una hora con fracción queda +1.457 s respecto a la pedida · la repetición con --force hizo falta` y `RESULTADO F32 L ok 28/28`. Las versiones anteriores del guion, antes de la simulación que pidió la revisión, dieron ok 26/26 en los dos ([38747336097](https://github.com/Jeremaya25/prdrive/actions/runs/38747336097)) y ok 25/25 con el primer guion ([38745926932](https://github.com/Jeremaya25/prdrive/actions/runs/38745926932)).

- LL-6: B no cambia la hora de nada en el remoto, A sigue pasando sin ver cambios (`No changes found`), `LEEME.txt` tiene la misma hora en A, en B y en el remoto.
- LL-7, las dos separaciones: sin conflicto, ni gana la copia vieja.
- La repetición: `sync.py` simula la pasada con `--dry-run --force` (no borra nada), la repite una vez con `--force` y termina bien; la siguiente pasada de A, sin repetir, también. El log de la pasada parada se guarda (`keychain_…_1.log`). Son tres órdenes de bisync: la parada, la simulada y la forzada.
- **La simulación frena** (nuevo): con cinco ficheros en el llavero, cuatro con otra hora en el remoto y uno borrado allí (1 de 5 = 20 %, por debajo del freno del 25 %, así que bisync llega a «all files were changed»), la simulación dice que forzar borraría `X3.kdbx`, no se fuerza, la pasada acaba con 1 y el texto lo explica. Son dos órdenes de bisync: la parada y la simulada.

## 3. Qué dice esto de cada issue

- **#116 ya no se da con #114 solo.** Los dos LL-7 pasan sobre un exFAT de Windows de verdad con la ventana de 2 s, también con la hora en el peor caso, y la copia que baja B ya no cuenta como «cambios sin subir» (esa parte la arreglaba la tolerancia de `llavero.pendiente()`, #114). No hace falta comparar la semilla (`kdbx.semilla()`): no se ha escrito, y la restricción de que el llavero valga con cualquier programa que abra un `.kdbx` no se toca.
- **#115**: la causa 1 (la hora de la base) la quita #114; la causa 2 (`LEEME.txt`) la quita `LEEME_HORA`. Con #114 solo, lo que queda de LL-6 es un fichero de dos que cambia de hora (rc 0), no el «all files were changed» del issue: ese necesitaba que **también** cambiase la hora de la base. La repetición con `--force` se mantiene porque lo decidió así el triaje (con la simulación de antes, y nombrada como la única excepción en `AGENTS.md`), y cubre cualquier otro caso en que cambien de hora todos los ficheros de un lado (el comentario de rclone en `operations.go` pone como ejemplo un cambio de horario de verano). Se ejercita de forma sintética (tocando la hora de los dos ficheros del remoto), no con ese caso.

## 4. Lo que no se ha visto

- **Un pendrive de verdad.** Un VHD usa el mismo controlador de exFAT y FAT32 de Windows, que es lo que redondea, pero no es un USB.
- **KeePassXC guardando.** Los guardados son una base de mentira entera con la hora que elige la prueba: la frontera que se mira es la hora que guarda cada sistema de ficheros y lo que hace rclone con ella, que no depende del contenido. Un guardado de verdad (`QSaveFile`, escritura a un temporal y renombrado) hace lo mismo con la hora del fichero.
- **Un remoto con sumas** (SFTP, el del issue): el remoto es una carpeta del equipo (`type local`).
- **Un cambio de horario de verano**, el ejemplo que da rclone para «all files were changed»: no se ha reproducido.
- **Un dispositivo que ya tenía el llavero de antes de `LEEME_HORA`**: lo cubren los tests de siempre (un `LEEME.txt` con el texto de siempre y otra hora se corrige en la pasada siguiente), no la nube.

## 5. Lo que se vio de más, en el CI: el punto ciego de la ventana de 2 s

`llavero (ubuntu-latest)` falló una vez sobre e0dfb4d ([ejecución 38758125912](https://github.com/Jeremaya25/prdrive/actions/runs/38758125912)) en `la base, igual en los dos lados`, y pasó en el resto. No es de esta PR: el punto ciego de abajo está en `main` desde #114 (con el rclone y la ventana de `main` se reproduce igual, sin nada de #115).

- **Qué pasa.** bisync compara tamaño y hora. Con `modify-window = 2s` (#114), una base del **mismo tamaño** que su línea del listado y con una hora a menos de 2 s se da por no cambiada: `No changes found`, código 0. `llavero.pendiente()` usa la misma regla, así que la ventana decía «al día» con la combinada sin subir. Reproducido de forma determinista con el rclone fijado (v1.75.2) sobre dos carpetas locales: con `--modify-window 2s` no sube; con la ventana mínima, sí lo ve.
- **Por qué se dio ahí.** La prueba pulsaba «Combinar» 0,4 s después de la pasada que bajó el ganador, y el tamaño de la combinada coincidió con el del ganador (1742 B). Un KDBX va de 16 en 16 bytes y su tamaño se mueve unos ±100 B entre guardados (en 3 ejecuciones locales: 1854→1758 B al añadir una entrada), así que coincidir no es raro: del orden de 1 de cada 25.
- **Qué se ha hecho.** La prueba espera 2,5 s desde la hora del ganador antes de «Combinar», que es lo que tarda una persona. El punto ciego queda anotado en `llavero.md` y no se ha tocado: cerrarlo es comparar algo más que tamaño y hora (por ejemplo `--compare size,modtime,checksum` donde los dos lados tengan suma, o `kdbx.semilla()`), un cambio de diseño que no es de #115.
- **Alcance real.** No se pierde nada: la base sigue en el dispositivo y la sube el siguiente cambio. Hace falta un segundo guardado a menos de 2 s del primero con una pasada justo entre los dos; el vigilante espera la calma y 120 s entre pasadas, así que en la práctica solo lo alcanzaría una pasada periódica o la de arranque.
