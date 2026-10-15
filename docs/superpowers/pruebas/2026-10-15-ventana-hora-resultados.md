# La ventana de hora (`modify-window`) — resultados

Fecha: 15/10/2026. Issue: #114 («En un pendrive exFAT o FAT32, lo que baja del remoto se da por cambiado en la pasada siguiente»). Código: rama `issue-114-modify-window`, de `2c0bbda`. Prueba en la nube: F3 (`tests/maquina/f03_mtime_windows.py` y `f03_mtime_linux.py`), ejecución [38714150533](https://github.com/Jeremaya25/prdrive/actions/runs/38714150533).

La prueba F3 de la que habla el issue se perdió con su rama (`claude/tests-issues-keychain-9077e0`); esta es la que la sustituye, y mide además lo que el arreglo promete.

## 1. Lo que dice el código de rclone v1.75.2

Leído en un clon del tag `v1.75.2` (el que fija `common/pins.py`), no de memoria:

- **bisync usa la ventana donde compara horas.** `timeDiffers()` (`cmd/bisync/compare.go`) llama a `fs.GetModifyWindow()` (`fs/fs.go`: la mayor entre `--modify-window` y la `Precision()` de cada lado) y da por iguales dos horas que difieren **menos** que ella, en los dos sentidos. Lo usan `findDeltas()` (`deltas.go`: «File changed: time (newer|older)», el caso del issue), la comprobación de «cambiado en los dos lados con el mismo contenido» (`deltas.go`) y la validación de los listados finales (`listing.go`). `copy` y `sync` hacen lo mismo en `operations.equal()`.
- **`conflict-resolve = newer` NO la usa para elegir ganador.** `resolveNewerOlder()` (`cmd/bisync/resolve.go`) compara con `After()`/`Before()` al nanosegundo; la ventana solo sirve ahí para preguntar si hay soporte de hora. Comprobado con el binario: con `modify-window = 2s` puesta y la copia local 0,5 s por delante de un cambio real del remoto, rclone dice «Path1 is newer … Difference: 500ms», gana la local y la del remoto queda como `f.txt.conflicto-remoto1`. Es un límite conocido (`conflicts-versions.md`).
- **La ventana no está en ningún listado.** La cabecera de un listado es `# bisync listing v1 from <fecha>` y nada más; los únicos motivos de «Must run --resync» son una interrupción sin `--resilient`/`--recover` y listados desiguales.
- La precisión local se mide con un fichero de `os.CreateTemp("", "rclone")` (`readPrecision()`, `backend/local/local.go`): la carpeta temporal del equipo, no la unidad. Es lo que dice el issue.

## 2. Reproducción con el rclone fijado, en el contenedor de la sesión

Sin núcleo con vfat ni exFAT, el redondeo se simuló: tras la primera pasada se le suma +1,876543 s a la hora del fichero bajado (lo que midió el pendrive). rclone v1.75.2 de verdad, la cascada de flags de `model.flags_efectivos()` para `bisync`:

| Caso | Pasada 1 | Pasada 2 | Pasada 3 |
|---|---|---|---|
| Antes del cambio | `File is new` / `Copied (new)` | **`File changed: time (newer)`** en Path1, `Updated modification time in destination` | `No changes found` |
| Dispositivo nuevo, con la ventana | `File is new` | `No changes found` | `No changes found` |
| Dispositivo de antes (baseline hecho **sin** la ventana, sin `--resync`), con la ventana | `File is new` | `No changes found` | `No changes found` |

La primera fila es lo que cuenta el issue; con la ventana, la 2.ª pasada ya no se mueve, también en un dispositivo cuyo baseline es de antes.

## 3. Los tests de siempre

- `tests/test_ventana_hora.py` (nuevo, 34 comprobaciones). Fallaba 17 antes del cambio, por lo que debía: el flag no llegaba a ningún modo ni al llavero, y `pendiente()` daba pendiente a 1,9 s. Fija: el flag en los cinco modos y en el llavero, que una pareja o `[defaults.flags]` lo cambien, que **un baseline y un md5 de filtros hechos con el código de antes siguen siendo de la pareja** (mismo `expected_prefix()`, mismo workdir, mismos filtros, `resync_reasons() == []`), y `llavero.pendiente()` con la hora a +1,876543 s, ±1,9 s (no) y +2,0 s justos, +2,1 s, −2,1 s (sí), y con otra medida (sí).
- `tests/test_flags_efectivos.py`: las ocho órdenes que fija llevan ahora `--modify-window 2s` tras `--stats-one-line`.
- `python tests/run_all.py`: 158 ficheros.
  - Con el Python del sistema de la sesión (3.13, sin `tkinter`): **157 de 158**; falla `test_install_deploy.py` («congelado NO se usa sys.executable»), que falla igual en `main` limpio: el test simula `which` con `/usr/bin/python`, que en esta máquina ES `sys.executable`.
  - Con el Python fijado del dispositivo (3.14.8, Tk 9.0.4) bajo Xvfb, que corre también los tests de ventanas: **155 de 158**; fallan `test_iconos.py` (4), `test_tk_letra.py` (1) y `test_unidad_nueva.py` (1), **las mismas comprobaciones y en el mismo número** que en `main` limpio (medidas de letra de esta máquina). `test_install_deploy.py` pasa.

## 4. En la nube (F3)

`correr.py F3` con el rclone fijado (`tests/_runtime_ci.py rclone`, un paso nuevo de `maquina-real.yml`). Por cada sistema de ficheros, en un volumen de verdad: se mide cuánto guarda una hora con fracción (`.543210 s`) y se baja del remoto un fichero **nuevo** y luego uno que **cambia**, con dos pasadas más tras cada bajada. El baseline se hace siempre sin la ventana, como el de un dispositivo de antes. Se hace dos veces: sin la ventana (el fallo) y con los flags de fábrica.

| Sistema | Windows (VHD) | Linux (loop) |
|---|---|---|
| NTFS / ext4 | +0 s | +0 s |
| exFAT | **+1,457 s** (hacia arriba) | −3,21 ms (10 ms) |
| FAT32 | **+1,457 s** (hacia arriba) | −0,543 s (vfat: saltos de 2 s, hacia abajo) |

- Donde la unidad redondea, **sin** la ventana la pasada siguiente a una bajada da «File changed: time» (comprobado), y la hora del fichero en el remoto acaba corrida (+1,457 s en Windows): lo que cuenta el issue.
- **Con** los flags de fábrica, y sin `--resync`: la pasada que baja el fichero lo baja, la siguiente y la otra más dicen «No changes found» sin ningún «File changed», y la hora del remoto no se toca. Con el fichero nuevo y con el que cambia.
- Donde la unidad no redondea (NTFS, ext4), sin la ventana tampoco pasa nada, y la prueba lo exige.
- Resultado: `RESULTADO F3 W ok 33/33` y `RESULTADO F3 L ok 33/33`.

## 5. Lo que no se ha visto

- **Un pendrive de verdad** con el cambio puesto. Un VHD usa el mismo controlador de exFAT y FAT32 de Windows, que es lo que redondea (el +1,457 s sale igual que en el pendrive del 12/10), pero no es un USB.
- **Un remoto con sumas** (SFTP, el del issue): las pruebas usan una carpeta del equipo como remoto (`type local`). La comparación de horas de `findDeltas()` no depende del backend; el efecto sobre una subida entera sin `disable_hashcheck` no se ha medido.
- **Tk fuera de esta máquina:** los tres tests de arriba que fallan aquí los vuelve a correr la CI de la PR; los de ventanas pasan igual que en `main`.
- **La fila F3 de `2026-09-25-equipo-pendiente-en-real.md`** (cambiar un fichero sin cambiar su tamaño dos veces en menos de 2 s y ver si la huella del agente lo nota): esta prueba solo cubre su primera mitad (qué dice `st_mtime_ns` en cada sistema). No se marca «nube: ok».
- **#115 y #116** (el llavero en exFAT), fuera de alcance: `llavero.pendiente()` tolera ya la ventana, pero su arreglo depende del replanteamiento (#122).
