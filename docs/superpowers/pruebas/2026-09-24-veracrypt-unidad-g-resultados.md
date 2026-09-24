# Resultados: VeraCrypt con la unidad G: (Windows)

Fecha: 2026-09-24 · Rama: `claude/veracrypt-functionality-review-rm91gr` ·
Plan: `2026-09-24-veracrypt-unidad-g.md` · Arreglos en `5c0e29b` y `409e979`
(secciones 8 y 9).

## 1. Entorno

- Windows 11 IoT Enterprise LTSC, 10.0.26100, AMD64. La persona es
  administradora con token filtrado por UAC: el shell de las pruebas NO estaba
  elevado y cada elevación fue un aviso UAC que aceptó ella.
- Python 3.14.6 (`py -3`), Tk 8.6. El runtime que lleva el dispositivo: 3.13.15.
- **VeraCrypt: NO instalado.** Solo el paquete **VeraCrypt Portable 1.26.29**
  (firma Authenticode válida, IDRIX SARL), extraído en
  `C:\prdrive-pruebas\VeraCrypt`. No había ningún VeraCrypt en segundo plano. El
  programa no puede usar ese paquete tal cual (H-3); ver la sección 6 para cómo
  se siguió.
- `G:`: Kingston DataTraveler 3.0, 124 012 546 560 bytes
  (115,5 GB), USB, MBR, disco 3. Llegó en exFAT, etiqueta PEREPEN, vacía.
- Otras unidades: E: es un lector de CD vacío (sirvió para F4); P:, I:, U:, Z:
  son de red.
- Había un vigilante (`PrDriveWatch`, modo daemon) atado al dispositivo real de
  la persona; ese dispositivo no se enchufó. La persona
  autorizó desinstalarlo y **no** pidió restaurarlo.
- rclone del remoto de pruebas: el de la caché del instalador, v1.75.1. Remoto
  `pruebas` de tipo `alias` sobre `C:\prdrive-pruebas\remoto`.
- A mitad de las pruebas hubo que **reiniciar** el equipo (H-6).

## 2. Tabla de resultados

| Prueba | Resultado | Observación |
|---|---|---|
| 2.6 batería | FALLO (2 de 52) | `test_vestibulo.py`: bug real (H-1). `test_penwatch_vestibulo.py`: el test no es portable (H-2) |
| A1 | OK | Reparticionado a 16 GB FAT32 (el script del plan no bastaba: ver 6) |
| A2 | OK | `FAT32 4293918720 False` |
| A3 | OK | `InstallError` con «4095M o menos» y «exFAT o NTFS», en 0,0 s; no se crea `.hc` |
| A4 | DISCREPANCIA | Queda de 4293918720 bytes exactos, pero `create_container()` vuelve a los 8,3 s con el fichero a 4293787648 (−128 KiB) y VeraCrypt sigue escribiendo ~2 min 45 s (H-4) |
| A5 | DISCREPANCIA | Monta (al segundo intento: el primero chocó con H-4), etiqueta PRDRIVE, desmonta sin error; **dentro SÍ hay `System Volume Information`** (H-5). No hay `$RECYCLE.BIN` |
| B2 | OK | `exFAT None False` |
| B3 | OK (+H-4) | Estimación «menos de dos minutos»; real ~11 s de creación más ~36 s de UAC |
| C2 | OK | `NTFS None True` |
| C3 | OK (+H-4) | 115 GB dinámico en ~8 s; `fsutil`: disperso; `disperso()` → True |
| C4 | OK (de otra forma) | El entorno del agente no deja borrar en la raíz de G:; el `.hc` se quitó reformateando |
| D | OK | Desde una carpeta con la disposición de una instalación (6): `veracrypt.sys` → `veracrypt-x64.sys`; `['x64']`; «x64: en un Windows ARM no monta (un driver no se emula)»; firma Valid (Microsoft WHCP); hash idéntico |
| E · panel | OK | Sin recuadro rojo ni pista de FAT32; «Contenedor dinámico» y «Dejar VeraCrypt en el dispositivo…» marcadas |
| E · contraseña corta | OK | `corta123` hace la pregunta, con «No» por defecto |
| E · crear y montar | **FALLO** | H-4: monta mientras VeraCrypt Format (elevado) sigue trabajando; el volumen queda **sin sistema de ficheros** y el aviso dice «lo más probable es que YA esté montado» |
| E · resto | OK | Con el contenedor creado aparte: «Montar» → Q:; Comprobaciones, Instalación, Parejas, `--resync` (300 MB, 22 s) y Verificación, todo en verde; sin fila «Instalación sin cifrar»; sin «Que VeraCrypt monte al conectar» |
| E4 | OK | Vestíbulo completo en G:, marca oculta, el mismo id fuera y dentro (`27e1347c…`), 201 ficheros, `autorun.inf` correcto, `.bat` que empieza `40 65 63` sin BOM, 81 CRLF y ningún LF suelto, LEEME con BOM. Nota: SVI dentro (H-5) |
| E5 | OK | «Desmontar el contenedor» correcto, con UAC |
| F1 | OK | Monta con el VeraCrypt que viaja; la orden no lleva `/password` (ver 3, H-4bis); abre prdrive con el Python del dispositivo; la consola se cierra sola |
| F2 | OK (1.ª vez no reproducida) | La primera vez la persona no vio el aviso y el proceso ya no estaba; repetido dos veces, «Ya hay una ventana de prdrive abierta…» sale bien |
| F3 | DISCREPANCIA | Con el VeraCrypt que viaja el `.bat` no se entera de la cancelación: dice «Si la has cancelado, cierra esta ventana» y espera 180 s. La persona la cerró a mano al minuto |
| F4 | OK | Con un CD vacío (E:), ningún diálogo «No hay disco» en F1, F3 ni G |
| F5 | OK | «Casi nada» desde la contraseña hasta la ventana |
| G1 · 1.ª vez | **FALLO** | Tras «Expulsar», Windows: «El dispositivo está en uso» (evento 225: System, pid 4). Venía de un desmontaje forzado (H-6) |
| G1 · limpio | OK | Tras reiniciar: confirmación, consola «Cerrando PRDRIVE…» → «PRDRIVE está cerrado…», driver descargado y Windows deja quitar la unidad |
| G2 | OK | Cancelar la confirmación no hace nada |
| G3 | OK | Durante la pasada todo gris, «Expulsar» incluido. Nota: «Arranque automático…» sigue encendido |
| G4 | OK | «Volume contains files or folders being used… Force unmount?» → No → a los ~30 s «El contenedor sigue abierto en F:…»; soltado el fichero, el segundo «Expulsar» cierra |
| G4b (añadida) | **FALLO** | «Expulsar» con un fichero abierto respondiendo **Sí** a forzar: la consola dice «Ya puedes quitar la unidad» y Windows dice que está en uso (H-6) |
| G5 | OK | «PRDRIVE ya estaba cerrado…» |
| G6 | OK | Dispositivo sin cifrar (tras K1): no hay «Expulsar» |
| H1 | DISCREPANCIA grave | Sección 4 y H-10 |
| H2 | DISCREPANCIA | VeraCrypt en la bandeja **no** desmonta ni enseña ningún globo (sección 4) |
| H3 | Ver 4 | Se recupera sin `--resync`; por el camino, un traceback (H-9) |
| I1–I2 | OK | «2 que revisar»; «El contenedor se queda sin sitio fuera», sin botón, «en G:\ quedan 500 MB libres» |
| I3 | OK | `sync.py --doctor` da la misma avería |
| I4 | OK | Liberado el sitio, la avería desaparece |
| J1 | OK | Instalado desde el dispositivo con su propio Python; «Dispositivo esperado (id)» = `27e1347c…`. Nota: `status` dijo «parado» los primeros segundos |
| J2 | **FALLO** | Instalado con el contenedor abierto, el primer «Expulsar» (sin desenchufar) hace que el vigilante **pida la contraseña al momento** (H-8) |
| J3 | OK | Al enchufar, ~5 s hasta la contraseña y ~5 s más hasta la ventana; en el diario, las cuatro líneas esperadas |
| J4a | OK | Tras «Expulsar» sin desenchufar, no vuelve a pedirla |
| J4b | OK | Cancelada al enchufar, no vuelve a pedirla hasta desenchufar |
| J5 | OK | `status`: «cifrado y cerrado, en G:\»; `probe`: «dispositivo cifrado, cerrado (id 27e1347c…)» |
| J6 | OK | Desinstalado. Nota: dice «el fichero .prdrive\PRDRIVE sigue ahí», y en un dispositivo cifrado está dentro del contenedor |
| K1 | OK | Instalación sin cifrar completa (id `49165a74…`) |
| K2 | OK | Recuadro rojo antes de crear, que nombra `.prdrive/`, `README.md` y `sync-data/`, la clave en claro y cambiar la clave del remoto. Notas: cuenta `README.md` como resto; con un remoto sin clave no hay `.prdrive/keys/` y aun así dice que está ahí |
| K3 | OK | Fila roja «Instalación sin cifrar» en el paso 8 (con el contenedor creado aparte por H-4) |
| K4 | OK | No se ha borrado nada: `G:\.prdrive\` y los 201 ficheros siguen ahí |
| L0 (añadida) | **FALLO** | «Añadir plataformas…» sobre un dispositivo VeraCrypt que YA tiene vestíbulo: «No he podido escribir G:\.prdrive-vestibulo: [Errno 13] Permission denied» (H-1) |
| L1 | OK | Tras «Montar», el panel «ya es un dispositivo prdrive» |
| L2 | OK | Vuelve el vestíbulo entero, con el **mismo** id. Nota: dice «1 elementos puestos» |
| L3 | DISCREPANCIA (a favor) | «Añadir plataformas…» ya había rehecho el traveler (`veracrypt-x64.sys`); `comprobar()` en verde, sin tener que pulsar «Llevar VeraCrypt». Queda también el `veracrypt.sys` viejo, que no molesta |
| L4 | OK (implícito) | Ya estaba en verde tras L2 |
| M1 | OK, con matiz | Nombre PRDRIVE e icono de VeraCrypt, pero solo tras volver a conectar la unidad: el Explorador lee el `autorun.inf` cuando llega el volumen, y se escribió con la unidad ya puesta |
| M2 | DISCREPANCIA | «Montar el volumen PRDRIVE» y «Desmontar todos los volúmenes» **no** aparecen (ni en «Mostrar más opciones»): Windows ignora `shell\…` en un extraíble |
| N1 | OK | Este equipo no tiene VeraCrypt: «Abrir PRDRIVE» → UAC → contraseña → prdrive con su propio Python |
| N2 | OK / FALLO | Tras un «Expulsar» limpio, Windows deja quitar la unidad; tras uno forzado, no (H-6) |
| N3 | NO PROBADA | No hay otro VeraCrypt instalado en ningún equipo disponible |

## 3. Hallazgos

### H-4 · `create_container()` da el contenedor por creado antes de que exista (el más grave)

- **Qué pasa:** VeraCrypt Format, sin administrador, se relanza elevado (UAC) y
  el proceso que lanzamos sale enseguida con 0. `create_container()` se fía de
  `returncode == 0 and container.exists()` y vuelve mientras la copia elevada
  sigue escribiendo.
- **Evidencia** (B3, procesos cada 0,5 s): Format #16444 (hijo nuestro) lanza
  #26060 (padre #16444) tras el UAC y sale; `create_container()` dice «creado»
  con el fichero a 536739840 bytes (512 MiB − 128 KiB, todavía sin la cabecera
  de respaldo); #26060 sigue ~5 s más hasta 536870912. Visto también en A4
  (4 GiB en FAT32: ~2 min 45 s de hueco), C3 (dinámico, ~4 s), con FAT dentro y
  en K (2 GiB fijo en exFAT: 13,5 s dichos frente a ~91 s reales). Pasa aunque
  el driver ya esté cargado.
- **En el asistente (E):** «Crear y montar» monta sobre un contenedor a medio
  hacer. El volumen queda montado en Q: **sin sistema de ficheros** («El volumen
  no contiene un sistema de archivos reconocido»); Format ya no puede darle
  formato. El aviso culpa a otra cosa: «El contenedor está abierto, así que lo
  más probable es que YA esté montado» (`en_uso()` ve el `.hc` abierto, pero
  quien lo tiene es Format). El contenedor queda inservible. En A5 el mismo
  choque hizo fallar el primer montaje.
- **Dónde:** `install/crypto.py`, `create_container()`: le falta la regla 2 que
  `mount_container()` sí aplica (no fiarse del código de salida porque VeraCrypt
  se relanza elevado). También `explicar_montaje()` / `en_uso()`: el diagnóstico.
- La orden elevada de montar sí lleva la marca: `"G:\VeraCrypt\VeraCrypt.exe" /q UAC
  /volume "G:\PRDRIVE.hc" … /quit` (leída con una consulta elevada, F1).
  Coincide con lo que ya dice AGENTS.md para el vestíbulo.

### H-6 · Después de un desmontaje forzado, la unidad no se puede quitar

- **Reproducido por el camino del producto (G4b):** «Expulsar» con un fichero
  abierto dentro, respondiendo **Sí** a «Force unmount?». La consola dice «PRDRIVE
  está cerrado. Ya puedes quitar la unidad.», pero el driver sigue `Running`, sin
  ningún proceso de VeraCrypt, y Windows se niega: «'PRDRIVE (G:)' está en uso…».
  La primera vez (G1) venía de un `/force` mío en F3; el Explorador o el
  indexador tendrían F: abierta.
- **Quién bloquea:** evento Kernel-PnP 225, «La aplicación System con id. de
  proceso 4 detuvo la eliminación o expulsión del dispositivo
  USB\VID_0951&PID_1666…».
- **Causa probable** (sin herramienta de handles, así que no está verificado a
  nivel de handle): el volumen forzado se queda vivo mientras alguien tenga
  ficheros abiertos, y el driver con él sigue teniendo abierto
  `G:\PRDRIVE.hc`. **No es la imagen del driver:** en J, con el driver cargado
  desde `G:\VeraCrypt\veracrypt-x64.sys` y nada montado, Windows dejó quitar la
  unidad.
- **Cómo se sale:** cerrar lo que tenía el fichero y volver a lanzar el VeraCrypt
  que viaja y dejarlo salir (cualquier orden: al salir, sin volúmenes, descarga
  el driver), o reiniciar. Un `sc stop veracrypt` lo empeora: el driver se queda
  en `STOP_PENDING`, el servicio «marcado para eliminación», y VeraCrypt ya no
  monta nada («El servicio especificado se ha marcado para ser eliminado.
  Source: wWinMain: 11038») hasta reiniciar.
- **Dónde:** `install/vestibulo.py`, `bat_expulsar()`: da por cerrado el
  contenedor cuando desaparece la letra, lo que también pasa tras un desmontaje
  forzado con ficheros abiertos. Una comprobación posible (sin probar): que
  `G:\PRDRIVE.hc` se pueda abrir en exclusiva antes de decir «ya puedes
  quitarla».

### H-10 · Desenchufar sin expulsar deja un volumen fantasma que el programa da por bueno

- Tras desenchufar con el contenedor abierto (H1 y H2), **F: sigue** («Healthy /
  OK»), VeraCrypt la lista como montada, los directorios se listan y el fichero
  de control se lee (de la caché); leer datos da `Permission denied` o «El
  dispositivo no está listo», y **una escritura en F: parece funcionar** (se
  queda en caché y se pierde sin avisar).
- Al volver a enchufar, `Abrir PRDRIVE.bat` encuentra el id en el F: fantasma y
  **no intenta montar**: lanza `F:\runsync.bat` y abre prdrive **desde el volumen
  que ya no existe**. La ventana enseña la pareja «al día», «Expulsar» y nada
  raro; al pulsar «Reparación» se cierra sola (no puede importar
  `ui/tk_repair.py`, que no estaba en caché). Una segunda vez lanzado por la
  persona no llegó a abrirse.
- Se sale con un desmontaje forzado con letra; después F1 vuelve a funcionar.
- **Dónde:** `install/vestibulo.py` (`:buscar` del `.bat`: `if exist` + `findstr`
  sobre el fichero de control, que la caché sigue sirviendo). penwatch
  (`find_pen()`) usa la misma evidencia (no probado). Un criterio que separa el
  fantasma del bueno (sin probar): con el volumen de verdad, `G:\PRDRIVE.hc`
  está abierto en exclusiva; en el fantasma, recién enchufada la unidad, no.

### H-1 · `vestibulo.escribir()` no puede reescribir la marca en Windows

- La primera escritura oculta `.prdrive-vestibulo` (`deploy.hide()`) y Windows
  no deja abrir con `CREATE_ALWAYS` (el `'w'` de Python) un fichero oculto:
  `PermissionError`. Reproducido aparte (`write_text` sobre un oculto falla;
  abrir con `r+` y truncar funciona).
- **En el asistente real (L0):** «Añadir plataformas…» sobre un dispositivo
  VeraCrypt que ya tiene vestíbulo → «No se ha podido aplicar: No he podido
  escribir G:\.prdrive-vestibulo: [Errno 13] Permission denied». Lo mismo
  valdrá para el paso 5 sobre uno que ya lo tenga. La batería ya lo caza en
  Windows (`test_vestibulo.py`, línea 155); en Linux no se ve.
- **Dónde:** `install/vestibulo.py`, `escribir()`.

### H-8 · El vigilante pide la contraseña al expulsar si se instaló con el contenedor abierto

- J: instalado desde el dispositivo abierto (lo que hace «Arranque automático…»
  desde la ventana). Primer «Expulsar» sin desenchufar → a los 5 s aparece la
  contraseña de VeraCrypt. Diario: «dispositivo no disponible; disparo
  rearmado» → «dispositivo cifrado detectado en G:\» → «abriendo el
  contenedor…». `state.json` tras instalar: `launched: false`, `note: "montaje
  presente durante la instalación"`, sin `vestibule`.
- Una vez cancelada, ya no la repite (J4), y después de un ciclo normal todo va
  bien (J4a).
- **Dónde:** `penwatch.py`: el estado inicial de `install` y el rearme de
  `watch_loop`. Un dispositivo que desaparece con su vestíbulo todavía ahí es
  un «Expulsar», no una conexión nueva, y el estado de instalación no lo sabe.

### H-9 · Si el dispositivo desaparece a mitad de pasada, `sync.py` acaba en un traceback

- H3: rclone falla («The device is not ready» → `Bisync critical error` → `Must
  run --resync to recover`) y `sync.py` intenta guardar el log en
  `F:\.prdrive\logs`: `PermissionError: [WinError 21] El dispositivo no está
  listo` sin capturar, en `keep_log()` (`model.LOG_DIR.mkdir`) desde
  `dispose_log()`. La ventana enseña el traceback en vez de la cola del log y
  la explicación de `KNOWN_ERRORS`. El log de `%TEMP%` sí se conserva.
- **Dónde:** `sync.py`, `keep_log()` / `dispose_log()`.

### H-7 · Con un remoto `alias`, «Reparación» da un «grave» falso (fuera del alcance de VeraCrypt)

- rclone nombra la línea base con el remoto **resuelto**:
  `disp_sync-data_prueba..C__prdrive-pruebas_remoto_datos_prueba`.
  `bisync.expected_prefix()` predice `…pruebas__datos_prueba`, y «Reparación» /
  `--doctor` dicen «GRAVE: el baseline no es de esta pareja… rclone no lo va a
  encontrar», con un botón «Apartar el baseline…». Pero las pasadas funcionan:
  rclone lo encuentra (la de las 09:57, la de H3). `--doctor` se contradice:
  «estado: ok» y «GRAVE» a la vez. Apartarlo forzaría un `--resync` para nada.
- **Dónde:** `common/bisync.py`, `canonical_path()` / `expected_prefix()`, que no
  modelan los remotos que envuelven a otro (`alias`, y quizá otros).

### H-3 · El VeraCrypt portátil 1.26.29 no sirve al programa

El paquete portable solo trae `VeraCrypt-x64.exe`, `VeraCrypt Format-x64.exe`,
`VeraCryptExpander-x64.exe` (y los `-arm64`), `veracrypt-x64.sys` y
`veracrypt-arm64.sys`: **no hay ningún `VeraCrypt.exe`**. Con esa carpeta,
`crypto.find_veracrypt(carpeta)` → None, y `traveler.plan()` solo copiaría las
licencias y los drivers. Los lanzadores y penwatch buscan
`VeraCrypt\VeraCrypt.exe`. El asistente ofrece «dime dónde está», pero con una
carpeta portable no funciona. **Dónde:** `install/crypto.py` (`WIN_CANDIDATES`,
`find_veracrypt`), `install/traveler.py` (`IMPRESCINDIBLE`, `ACOMPANAN`).

### H-5 · `/m rm` no evita `System Volume Information`

Windows 11 26100 la crea dentro del contenedor al montarlo (A5: creada a las
8:45:52, el momento del montaje) aunque monte como extraíble, igual que en
cualquier USB (G: también la tiene). `$RECYCLE.BIN` no aparece. El docstring de
`mount_command()` y AGENTS.md («`/m rm` is not cosmetic») dicen que la evita. No
entra en ninguna pareja salvo que una sincronice la raíz del dispositivo.

### H-2 · `test_penwatch_vestibulo.py` no es portable

«Linux: veracrypt con el contenedor, en su ventana» pone `penwatch.IS_WIN =
False` y un `veracrypt` sin extensión en el PATH; en Windows `shutil.which` exige
una extensión (PATHEXT) y devuelve None. Es un fallo del test, no del producto.

### Observaciones menores

- F3: con el VeraCrypt que viaja, cancelar deja la consola esperando 180 s. Ya
  lo dice («Si la has cancelado, cierra esta ventana»), pero no se cierra sola.
- `Expulsar PRDRIVE.bat` espera 30 s aunque vaya con el VeraCrypt que viaja
  (UAC). Si el UAC tarda más, diría «sigue abierto» sin razón. No se vio.
- «Arranque automático…» sigue activo durante una pasada (G3).
- `penwatch status` dice «parado» los primeros segundos tras «Vigilante
  arrancado» (J1).
- `penwatch uninstall` habla de «.prdrive\PRDRIVE» también en un dispositivo
  cifrado (J6).
- «Añadir plataformas…»: «Hecho: 1 elementos puestos» tras escribir seis
  ficheros (L2).
- Recuadro rojo de restos (K2): cuenta `README.md` y afirma que hay una clave en
  `.prdrive/keys/` aunque no exista (remoto sin clave).
- rclone dentro del contenedor exFAT: `Failed to set sparse: FSCTL_SET_SPARSE:
  Incorrect function` en cada copia grande. No afecta al resultado.
- Tras chkdsk (H3), quedan `…lst-err` de la pasada abortada; `--doctor` los
  llama «residuales».
- VeraCrypt portátil no se queda en segundo plano con `/q background`; sí
  abriendo su ventana y cerrándola con la X.
- Cada operación de VeraCrypt portátil pide UAC, también desmontar. Un UAC que
  queda detrás de otras ventanas deja la orden colgada sin decir nada (pasó una
  vez: más de 2 min).

## 4. La prueba H en detalle

Todas con el driver cargado desde `C:\prdrive-pruebas\VC` (como un VeraCrypt
instalado), para no arrancar la unidad con el driver cargado desde ella.

- **H1, sin VeraCrypt en segundo plano.** Al desenchufar, **ningún aviso**. F:
  sigue en el Explorador y en `Get-Volume`; VeraCrypt la lista como montada
  (PRDRIVE, 115 GiB, AES, Normal). Al volver a enchufar (sigue siendo G:),
  **la predicción no se cumple**: `Abrir PRDRIVE.bat` no llega a VeraCrypt,
  porque el `:buscar` encuentra el id en el F: fantasma y lanza prdrive desde
  él (H-10). Limpieza: desmontaje forzado con letra, y F1 vuelve a funcionar.
- **H2, con VeraCrypt en segundo plano** (el portable de C:, en la bandeja).
  **La predicción no se cumple**: al desenchufar, VeraCrypt **no** cierra el
  volumen ni enseña el globo «Before you physically remove…». Pasados 15 s, F:
  sigue ahí con VeraCrypt vivo en la bandeja. Al volver a enchufar pasa lo mismo
  que en H1. **Salvedad:** es VeraCrypt **portable**; uno instalado podría
  comportarse distinto (no se pudo probar).
- **H3, desenchufar a mitad de pasada** (`grande.bin` de 1 GB copiándose al
  dispositivo). No hay aviso de Windows ni de VeraCrypt. rclone: «The device is
  not ready», 3 reintentos (`--resilient`), `Bisync critical error` y «Must run
  --resync to recover»; `sync.py` termina en un traceback (H-9). Al volver:
  - VeraCrypt (no Windows) avisa «The filesystem on the volume mounted as 'F:'
    was not cleanly unmounted…» y ofrece comprobarlo; chkdsk: «Se encontraron
    daños al examinar el mapa de bits del volumen… Windows ha hecho algunas
    correcciones».
  - «Reparación»: además de H-7, «hay 1 bloqueo(s) sin dueño».
  - «Sincronizar ahora» **se recupera sola**, sin `--resync` (`--recover`, y el
    bloqueo ya había caducado por `--max-lock 2m`): copia el GB y termina OK. No
    queda ningún `.partial` ni ningún `.lck`; 201 ficheros.
  - El contenedor se sigue abriendo con su contraseña.

**Para decidir si prdrive deja VeraCrypt en segundo plano:** con el portable
1.26.29, estar en segundo plano **no** cambió nada al desenchufar. El problema
que sí se vio es otro y es de prdrive: el volumen fantasma, que el `.bat` (y
seguramente penwatch) dan por bueno (H-10). Para decidirlo del todo falta repetir
H2 con un VeraCrypt **instalado**.

## 5. Tiempos

- A4 (4095 MiB en FAT32, fijo): 8,3 s según `create_container()`; ~2 min 45 s
  reales (fichero creado a las 8:41:35, última escritura a las 8:44:18).
- B3 (512 MiB en exFAT, fijo): 42,5 s según `create_container()`, incluidos ~36 s
  de UAC; fin real a los ~47,7 s. Estimación del programa: «menos de dos minutos».
- C3 (115 GB dinámico en NTFS): 3,7 s según `create_container()`; fin real ~8 s.
- K (2 GiB en exFAT, fijo): 13,5 s según `create_container()`; fin real ~91 s.
  El asistente estimaba 64G en «unos 52 min».
- F5: «casi nada» (percepción de la persona). J3 (penwatch): ~5 s hasta la
  contraseña y ~5 s más hasta la ventana; en el diario, 20 s de «abriendo» a
  «runsync lanzado», contando lo que se tardó en escribir la contraseña.
- `--resync` de 300 MB en E: 22 s (21,4 MB/s). Pasada de 1 GB tras H3: 14,3 MB/s.

## 6. Lo que este plan tenía mal

- **Suponía VeraCrypt instalado.** Solo había el portable, que el programa no
  puede usar (H-3). Para seguir se hizo `C:\prdrive-pruebas\VC` con la
  disposición de una instalación: los `-x64` renombrados sin arquitectura (lo
  que hace el instalador, hecho 1), `veracrypt.sys` y además `veracrypt-x64.sys`
  para que el driver cargue en modo portátil; se pasó al asistente en el PATH.
  D se hizo desde una copia con solo `veracrypt.sys`. Consecuencias: nada usa
  `%ProgramFiles%`, así que los lanzadores y penwatch siempre fueron por el
  VeraCrypt que viaja (esto cubre N en este equipo), cada montaje, creación y
  desmontaje pidió UAC, y las ramas «el instalado antes que el que viaja» y
  `ERR_DRIVER_VERSION` quedaron sin probar.
- **Reparticionar:** `New-Partition -DriveLetter G` falla en un extraíble («The
  requested access path is already in use»: la letra se queda en el dispositivo
  aunque no haya partición), y la partición nueva sale sin letra. Hay que
  crearla sin letra y ponérsela con `Set-Partition -NewDriveLetter`.
- **E y K «Crear y montar»** no se pueden completar desde el asistente por
  H-4: el contenedor se creó aparte, esperando a VeraCrypt, y el asistente lo
  montó como «Ya existe».
- **F1:** la línea de órdenes del VeraCrypt elevado no se puede leer sin
  administrador (WMI la devuelve vacía); se leyó con una consulta elevada.
- **F3:** el «~1 s» solo vale con VeraCrypt instalado; con el que viaja son 180 s.
- **G1 / H:** el plan no contaba con que, con el VeraCrypt que viaja, el driver
  se carga desde la propia unidad. Antes de cada desenchufado se comprobó el
  driver; en H se precargó desde C:.
- **H2:** `& $vc /q background` no deja VeraCrypt portátil en la bandeja; hay que
  abrir su ventana y cerrarla con la X.
- **H3:** «borra antes `grande.bin` del lado del dispositivo para que tenga que
  volver a copiarlo»: en bisync eso **propaga el borrado al remoto**. Se agrandó
  `grande.bin` en el remoto a 1 GB.
- **J1:** instalar el vigilante con el contenedor abierto provoca H-8 al primer
  «Expulsar». El plan no lo esperaba.
- **L:** borrar la marca antes de «Añadir plataformas…» esconde H-1; se añadió L0
  con la marca puesta. Y como «Añadir plataformas…» rehace el traveler, L3 ya no
  enseña la fila del `veracrypt.sys` viejo.
- **M:** el `autorun.inf` solo se lee al llegar el volumen; hay que desenchufar y
  volver a enchufar (aquí fue un reinicio) antes de mirar.
- **Entorno del agente:** bloquea `Remove-Item` en la raíz de G: y cualquier
  orden con `Format-*` sobre G:; se usaron scripts, se movió en vez de borrar
  (L), se vació con `SetLength(0)` (I4) o se reformateó (C4).

## 7. Limpieza

- G: formateada en exFAT, vacía (etiqueta PRPRUEBA), a tamaño completo;
  `Confirmar-G` correcto.
- Ningún contenedor montado, ningún VeraCrypt corriendo, el driver descargado.
- Vigilante desinstalado; el de antes no se ha restaurado, por decisión de la
  persona.
- **`C:\prdrive-pruebas` NO se ha borrado:** contiene los scripts, las copias de
  VeraCrypt y el remoto de pruebas. Lo borra la persona cuando quiera.
- `git status`: solo este fichero.

## 8. Arreglos después de las pruebas (sin volver a pasar por G: todavía)

Los cinco que impedían fusionar o convenía cerrar en esta rama. Cada uno con su
test en rojo antes del arreglo; la batería entera pasa salvo H-2, que ya fallaba
antes y va aparte.

| Hallazgo | Arreglo | Test |
|---|---|---|
| H-4 | `crypto.create_container()` anota los `VeraCrypt Format` vivos antes de lanzar y espera a que terminen los nuevos (`_esperar_copia_elevada()`); la lista sale de una instantánea de Toolhelp (`_procesos()`), que sí ve la copia elevada | `test_crypto_veracrypt.py`, 5d |
| H-1 | `vestibulo.escribir()` destapa la marca (`deploy.unhide()`) antes de reescribir y la vuelve a ocultar | `test_vestibulo.py`, «se puede volver a escribir encima» |
| H-6 | `Expulsar PRDRIVE.bat`: cuando se va la letra, espera hasta 10 s a ver el `.hc` suelto (`:libre`); si sigue retenido dice que no se quite, que se cierren los programas y se vuelva a expulsar, o reiniciar. «Ya estaba cerrado» también mira antes | `test_vestibulo.py`; en Windows ejecuta `:libre` contra un `.hc` retenido |
| H-10 | `Abrir PRDRIVE.bat`: una unidad con el id y el `.hc` de al lado suelto es el fantasma; no lanza desde ella y dice «Expulsar» y después «Abrir» | `test_vestibulo.py` |
| H-8 | `penwatch.watch_loop()`: si desaparece el volumen montado y queda su vestíbulo, lo da por atendido (es «Expulsar», no una conexión nueva) | `test_penwatch_vestibulo.py`, con el estado que escribe `install` |

Recorrido de punta a punta en este equipo, sin VeraCrypt: los `.bat` generados,
con una letra de `subst` como volumen montado y un `.hc` retenido en exclusiva
como lo retiene el driver. Los cuatro caminos (fantasma, montado de verdad,
suelto, retenido) hacen lo que deben y el `.hc` queda intacto.

Commit `5c0e29b`. Lo que va aparte, en issues: #36 (H-9), #37 (H-7), #38 (H-3),
#39 (H-5), #40 (H-2) y #41 (observaciones menores).

## 9. Vuelta a G: tras los arreglos (13:00–13:17)

Sin el asistente: scripts que llaman a las mismas funciones que él
(`C:\prdrive-pruebas\e2.py`, `aprovisionar.py`), con el VeraCrypt de
`C:\prdrive-pruebas\VC` sin administrador y el driver cargado desde ahí. La
persona solo aceptó UAC, respondió a VeraCrypt y enchufó y desenchufó. Para
comprobar que Windows deja quitar la unidad, `expulsar_g.py` pide la
expulsión como «Quitar hardware de forma segura» (`CM_Request_Device_EjectW`)
y devuelve el veto si lo hay.

| Prueba | Resultado | Observación |
|---|---|---|
| E | OK | 2 GiB fijo en exFAT. La copia elevada de Format termina a los ~80 s; `create_container()` vuelve a los 81,6 s, con el fichero entero (2147483648) y ningún Format vivo. Sin el arreglo habría vuelto a los 32 s, cuando salió el proceso que lanzamos. Monta en Q: a los 85,6 s **con sistema de ficheros** (2 GiB libres) |
| paso 5 + traveler | OK | 16 elementos y el id `3c9cf355…` fuera y dentro, con la marca oculta; traveler `['x64']` |
| L0 | OK | «Añadir plataformas…» con el vestíbulo puesto: sin error, el mismo id, y la marca sigue oculta |
| J2 | OK | El vigilante se instaló con el contenedor abierto (`launched: true`, «montaje presente durante la instalación», sin `vestibule`). Tras «Expulsar» (forzado, G4b) apunta `"vestibule": "G:\\"` y en 45 s no pide la contraseña |
| G4b | OK, pero H-6 no se reprodujo | «Expulsar» con `Q:\abierto.txt` abierto en exclusiva, UAC y «Sí» a forzar. Con el fichero **todavía abierto**, el segundo «Expulsar» dice «ya estaba cerrado. Puedes quitar la unidad», y **Windows la expulsa sin veto**. Esta vez el driver soltó el `.hc` al forzar, así que la retención de las pruebas (H-6) no apareció. La rama «retenido» solo está probada con `subst` (sección 8). La duda de si al cerrar el fichero el `.hc` queda suelto no se ha podido contestar, porque no estaba retenido |
| G4b · espera | DISCREPANCIA (#41) | La primera consola se rindió a los 30 s («sigue abierto… No quites la unidad todavía») antes de que la persona llegara a responder a VeraCrypt. Es el mensaje prudente, pero erróneo |
| H1 | OK | Tras desenchufar sin expulsar, Q: sigue «Healthy» con el fichero de control legible. Al volver a enchufar, «Abrir» dice «PRDRIVE aparece abierto en Q:, pero el contenedor de esta unidad no lo está…» y **no lanza nada**. «Expulsar» lo cierra en 14 s, sin preguntar si forzar, y dice «ya puedes quitar la unidad». **Windows la expulsa sin veto** |
| H1 · vigilante | Observación (#41) | Con el fantasma, penwatch no se entera: no rearma, no pide la contraseña al volver a enchufar y no lanza nada desde el fantasma. Tras «Expulsar» marca el vestíbulo, así que en esa conexión no abre el contenedor solo |

**Entorno:** el shell Bash del agente tiene un sandbox que desvía las escrituras
en `%LOCALAPPDATA%`. Un `penwatch install` lanzado desde ahí registró la tarea de
verdad, pero sus ficheros quedaron en el espacio desviado, y la tarea fallaba con
0x80070002 (fichero no encontrado). Desde PowerShell se instaló bien. No es un
fallo del producto.

**Estado al acabar:** G: expulsada, con el contenedor de prueba y el vestíbulo
(sin formatear). Vigilante desinstalado. El driver sigue cargado desde
`C:\prdrive-pruebas\VC` hasta reiniciar o hasta que VeraCrypt salga sin
volúmenes.

## 10. Después de la vuelta a G: (`409e979`)

- **«Expulsar» espera mientras VeraCrypt pregunta si forzar.** Si al empezar no
  había ningún `VeraCrypt.exe` vivo, la espera no cuenta mientras quede uno: la
  copia elevada del que viaja, a la que `start /wait` no espera. Lo prueba
  `test_vestibulo.py`, ejecutando el trozo del `.bat` contra una copia de
  `ping.exe` llamada `VeraCrypt.exe`. **Sin probar con VeraCrypt de verdad.**
- **H-2 (#40):** en Windows, el `veracrypt` falso del test lleva `.exe`. La
  batería pasa entera en Windows (52 de 52).
- **H-5 (#39):** el docstring de `mount_command()` y AGENTS.md dicen ya que
  `/m rm` evita `$RECYCLE.BIN`, pero no `System Volume Information`.
- **Entorno:** en el shell Bash del agente, `tasklist | find` se queda colgado
  por el sandbox, así que el test lleva un límite de 30 s. Desde PowerShell va
  bien.
