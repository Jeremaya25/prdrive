# Resultados: la instalación en el equipo, en Windows (0.5.0)

Fecha: 2026-09-29 · Lista: `2026-09-25-equipo-pendiente-en-real.md` · PR #54.

Código probado: `claude/exciting-turing-j1ay0k` (0c02a2b) **con `origin/main`
(0.4.2, #55) fusionado encima**, en un worktree aparte (rama local
`pruebas/050-sobre-main`, commit 9d2c0b9). Conflictos del merge: `VERSION`
(queda 0.5.0) y `prdrive-install.py` (se quedan las dos mitades: las órdenes
del agente y `cmd_relevo` / `--relevo --esperar --reabrir`). Ese mismo merge,
con el mismo contenido, es el cfba571 de la rama de la PR. La #56 (0.4.3) no
está dentro. Lo arreglado después de las pruebas está en la sección 9.

## 1. Entorno

- Windows 11 IoT Enterprise LTSC 10.0.26100, AMD64, sobremesa (sin batería),
  dos monitores 1920×1080 al 100 %. Ethernet de dominio. Sophos (on-access,
  HitmanPro.Alert) instalado.
- Python 3.14.6 del equipo (Tk 8.6); el agente, con su 3.13.15.
- **El shell de las pruebas corría ELEVADO.** Todo lo que se prueba se lanzó
  sin elevar (integridad media, con el token del Explorador), como lo lanzaría
  la persona; se comprobó el nivel del agente (medio).
- En la sesión sin elevar, **P:, I:, U: y Z: son unidades de red**
  (`P:` = `\\192.168.100.11\Departaments`); la sesión elevada no las ve.
- VeraCrypt: el MSI 1.26.29 está registrado y su driver `veracrypt` corre, pero
  **no existe `C:\Program Files\VeraCrypt`** (para prdrive no hay VeraCrypt
  instalado). En la caché del instalador, el Portable 1.26.24.
- OneDrive: variable `OneDrive=C:\Users\pcerqueda\OneDrive`; Documentos NO
  está redirigido. Sin Dropbox.
- `G:` Kingston DataTraveler 3.0 (serie 4E0981D058C9, 115,5 GB), exFAT.

## 2. Cómo se probó (y en qué se aparta de la lista)

La persona trabajaba en el equipo y pidió no interrumpir y que las ventanas de
prueba no salieran encima de la suya. Así que:

- **Escritorio oculto.** Lo que abre ventanas (la pregunta por una unidad
  nueva, la ventana de una raíz, la contraseña de VeraCrypt) se hizo con el
  agente corriendo en un escritorio de Windows aparte (`CreateDesktop`): las
  ventanas existen, se miden y se cierran, pero no salen en pantalla. Allí no
  hay bandeja, así que los avisos del sistema de esas pruebas quedan en el
  diario («sin avisos del sistema: solo aquí»), que es lo esperado. **La bandeja
  y los avisos se probaron con el agente en el escritorio real**, arrancado por
  su tarea.
- **Los clics, por mensajes.** «Atender» con la tecla espacio en el botón
  enfocado; la contraseña de VeraCrypt con `WM_SETTEXT` + `IDOK` (contraseña de
  pruebas); las preguntas de VeraCrypt con `IDYES`/`IDNO`. Nadie tocó el ratón.
- **El asistente, sin ventana.** Scripts que llaman a las mismas funciones que
  `ui/tk_install.py` / `ui/tk_equipo.py` en el mismo orden (como la sección 9
  de la campaña de G:). A1 se hizo con el `.exe` real (`--instalar-agente`).
- **«Iniciar servicio» (V1/V2)**: `runsync.ui_flow()` de verdad con
  `ui.start` sustituido por lo que devuelve la ventana al pulsar el botón.
- **Unidades «enchufadas»** con `subst` (sin elevar); la unidad cifrada de A13,
  una carpeta con su `PRDRIVE.hc` y su vestíbulo, montada con `subst W:`.
- **VeraCrypt «instalado» de pruebas** para la fase 3: el Portable 1.26.24
  (firma válida) con la disposición de una instalación, visible solo para los
  procesos lanzados con `ProgramFiles` apuntando a él; driver, el 1.26.29 del
  MSI, ya cargado. El contenedor de la raíz se creó desde el shell elevado con
  `crypto.create_container()` y los parámetros de `abrir_o_crear()` (sin UAC
  que aceptar); montar, abrir, cerrar y todo lo demás, sin elevar.
- **«Actualizar» (V8–V11)** sin release publicada con `--update-agente`: el
  `agente.py actualizar` de verdad con `update.fetch()` sustituido por zips
  locales (el árbol probado con `VERSION` 0.5.1…0.5.5; en 0.5.3–0.5.5 además
  otro `PYTHON_RELEASE`). Lo demás —comprobar, extraer, lanzar SU instalador— es
  real.
- **Remoto de pruebas**: `alias` a `C:\prdrive-pruebas\remoto`, y un remoto
  `red` (webdav de `rclone serve` en 127.0.0.1:18080) para cortar «la red» sin
  tocar la del equipo.

## 3. La batería en Windows

`python tests/run_all.py`: **FALLAN 9 de 74**, igual en la rama sola que con
`main` fusionado (el PR dice 74 de 74 en Linux).

- 8 son tests escritos para Linux que en Windows no tienen guarda:
  `test_dbus.py` (`socket.AF_UNIX`), `test_bandeja_linux.py` (pipe + `select`),
  `test_bandeja.py` (7: VeraCrypt en `/opt/veracrypt`), `test_agente_veracrypt.py`
  (ruta `C:\…` leída como letra), `test_agente_raiz.py` (`start_new_session`),
  `test_install_agente.py` (autostart XDG), `test_install_wizard.py` (fila
  «Bandeja», solo Linux), `test_raiz_equipo.py` (`~/.dropbox/info.json`, el
  `.desktop` y un VeraCrypt de mentira).
- **1 es un fallo de verdad**: `test_agente_contrato.py` → H-2.

## 4. Resultados

`OK` · `FALLO` · `DISCREPANCIA` (funciona, pero no como dice la lista) ·
`PARCIAL` (una parte) · `NO PROBADA` (y por qué).

### Fase 1 — El agente con unidades

| Prueba | Resultado | Observación |
|---|---|---|
| A1 | PARCIAL | `.exe --instalar-agente` sin elevar: código en `agente\0.5.0`, su Python en `runtime\<id>`, tarea «prdrive» (disparador al iniciar sesión, token interactivo, sin nivel → integridad media, sin límites de batería ni de tiempo), arrancado. Cerrar sesión y volver: no (interrumpe) |
| A2 | OK | penwatch (instalado antes en modo daemon) fuera: sin tarea ni `%LOCALAPPDATA%\PrDriveWatch`; su unidad en `agente.json` en `daemon`, con su nombre. El «lo dice»: el `.exe` es `--windowed` y no enseña nada al terminar bien (H-11) |
| A3 | NO PROBADA | Linux |
| A4 | OK | Unidad nueva vista a los 3 s; ventanita «prdrive — unidad nueva» (496×295) con cuenta atrás; a los 2:01 se cierra y cuenta «Ahora no» hasta desconectarla; al reconectar vuelve a preguntar; «Atender» la añade en `daemon` y la sincroniza enseguida. El aviso del sistema de esta prueba: en el escritorio oculto, solo diario |
| A5 | OK | Mientras pregunta, ningún proceso con rutas de la unidad; la pregunta recibe solo `--nombre` |
| A6 | OK | Remoto de la pareja apartado → «FALLÓ» → **un** aviso, colgado del icono de la bandeja, con el icono de advertencia; el segundo fallo no avisa; al volver, «bien» sin `--resync` (bisync: «retryable without --resync»). Windows lo atribuye a «Python» (H-6) |
| A7 | NO PROBADA | Linux |
| A8 | PARCIAL | `energia()` y `red_medida()` de verdad: «sin batería» y `False` en 18–21 ms (la vtabla de `INetworkCostManager` funciona). Batería < 20 % y red de uso medido: sobremesa en Ethernet de dominio, no se toca |
| A9 | NO PROBADA | Linux |
| A10 | OK | Servidor del remoto caído → «FALLÓ por la red» → sonda → **un** aviso «sin conexión con red» (icono informativo); ninguna pareja lanzada, sondas a los 5 min exactos; servidor de vuelta → en la sonda siguiente «vuelve la conexión con red» y la pareja sigue sola |
| A11 | NO PROBADA | Linux |
| A12 | OK ×4 | Abrir la ventana de la unidad atendida → «en pausa: hay una ventana de runsync abierta», lock suelto; al cerrarla vuelve a los 15 s. La carrera de H-2 no salió en estos 4 ciclos |
| A13 | OK | Unidad cifrada de la lista, conectada cerrada: pide la contraseña **una** vez (`/volume …\PRDRIVE.hc`, sin `/password`); abierta, atendida; «Expulsar PRDRIVE.bat» (con el Portable que lleva) la cierra en 4 s y en 75 s no vuelve a pedir; quitar y poner → «apertura rearmada» → pide otra vez; cancelada, no insiste |
| A14 | OK | Desinstalar: agente parado, tarea, acceso del menú y `%LOCALAPPDATA%\prdrive` fuera; «Las unidades no se han tocado» (solo soltó su `daemon.lock.json`) |
| A15 | NO PROBADA | ARM64 |

### Fase 2 — La raíz del equipo sin cifrar

| Prueba | Resultado | Observación |
|---|---|---|
| R1 | OK | `%USERPROFILE%\PRDRIVE`: `.prdrive\` oculta con `PRDRIVE` (`tipo=equipo`), `bin\x64\rclone.exe` con su sello y `rclone.conf`; sin `runtime\`, `runsync.bat` ni guía; la inicialización con el `python.exe` del agente. (Remoto sin clave: no hay `keys\`) |
| R2 | PARCIAL | El `.lnk` (IShellLinkW por vtabla) se lee bien: `pythonw` del agente, `"…agente.py" abrir`, carpeta del agente, icono `runsync.ico`, descripción. Lo que lanza abre la ventana de la raíz y el agente se pausa (vuelve 16 s tras cerrarla). Cómo sale en el menú Inicio: no mirado |
| R3 | NO PROBADA | Linux |
| R4 | PARCIAL | Solo el estado actual: «El disco C: no tiene BitLocker activado (el volumen NO está cifrado con BitLocker).» |
| R5 | DISCREPANCIA | El aviso por pareja funciona (`OneDrive/Notas` → «ya la sincroniza OneDrive»), pero la carpeta personal entera avisa al revés y tapa su explicación (H-4). Documentos no está redirigido aquí: el caso exacto de la lista no se pudo ver |
| R6 | NO PROBADA | Sin Dropbox |
| R7 | OK | Carpeta renombrada → **un** aviso «no encuentro su carpeta», nada lanzado (ni «Sincronizar ahora»), `status` «Falta la raíz»; al volver, sigue sola |
| R8 | OK | `local = "."` → `sync.py` se niega con el mensaje de la raíz; un solo aviso en dos fallos |
| R9 | OK | Con el agente de esta versión en marcha: no se reinstala (mismo pid), la raíz entra por el buzón y se atiende sin reiniciar; «Verificación» toda en verde |
| R10 | OK | Desinstalar con la raíz: sigue en su sitio y se dice dónde; el acceso del menú desaparece. Dice «(la clave incluida)» sin clave (H-10) |
| R11 | OK | Nota `tipo = "equipo"`; en la flota «INF22 (equipo)», ficha «Para: Una carpeta de un equipo, no una unidad» |

### Fase 3 — La raíz cifrada

| Prueba | Resultado | Observación |
|---|---|---|
| C1 | OK (lógica) | Sin VeraCrypt instalado (y con el Portable en la caché) `veracrypt_instalado()` → None: la opción VeraCrypt se apaga con `COMO_INSTALAR`. Pintado: no visto |
| C2 | **FALLO** (disperso) | **El contenedor se crea FIJO, no `/dynamic` (H-1).** Lo demás bien: montado en Q: (P: es de red: la primera libre sin elevar), etiqueta PRDRIVE, sin `$RECYCLE.BIN` (sí `System Volume Information`, como H-5 de G:), `.hc` y `.prdrive-vestibulo` oculto fuera con el mismo id |
| C3 | OK | `agente.json`: `ruta = Q:\`, su `contenedor`, `pedir_al_iniciar` el elegido; abierta y atendida |
| C4 | DISCREPANCIA | Sin nada abierto, VeraCrypt preguntó «Force unmount?» en 3 de 7 «Bloquear»: los dos primeros tras instalar y uno justo después de las pasadas del agente. Los otros cuatro, limpios en 1–4 s. Un octavo no terminó: VeraCrypt vivo sin ventana, lo terminé yo; no se sabe por qué (H-3) |
| C5 | OK | «No» → «sigue abierta… ciérralo y vuelve a bloquear» y sigue atendida; «Sí» → bloqueada, `.hc` libre, letra fuera. (La pregunta la provocó H-3, no un fichero abierto) |
| C6 | OK | Ventana de contraseña de VeraCrypt (sin `/password`, `/letter Q`, `/mountoption rm`); monta en **Q:** y se atiende 3 s después |
| C7 | OK | `subst Q:` → «La letra Q: está ocupada… Libérala y vuelve a desbloquear», sin lanzar VeraCrypt |
| C8 | PARCIAL | Simulado reiniciando el agente (no se cerró sesión): pide **una** vez; cancelada → a los 20 s «no se ha desbloqueado (¿contraseña cancelada?)», y no insiste |
| C9 | PARCIAL | Igual: con `pedir_al_iniciar` desactivado no pide nada, «Bloqueada», las unidades atendidas |
| C10 | NO PROBADA | Suspender el equipo de la persona |
| C11 | PARCIAL | En la raíz: `expulsion()` None y `bloqueo()` = su id (el pie dice «Bloquear»); `pedir_bloqueo()` deja `state\servicio.pide`, el agente lo recoge en 0,6 s y la bloquea en 1 s. El botón y el cierre de la ventana: no vistos |
| C12 | NO PROBADA | No se llena el C: de la persona. Además, con H-1 el contenedor que crea el asistente nunca es disperso, así que el hallazgo `espacio` no saldría nunca en una raíz del equipo |
| C13 | OK | Antes de crear, los restos `['.prdrive/', 'Notas-prueba/']`; fila roja «Instalación sin cifrar» en «Verificación»; nada borrado. Ver la observación de «Carpeta» en §6 |
| C14 | OK | Desinstalar con el contenedor abierto: sigue abierto, «…y ABIERTA en Q:\: ciérrala desde VeraCrypt cuando quieras», `.hc` y carpeta sin tocar |
| C15–C17 | NO PROBADAS | Linux |
| C18 | OK | Nota `tipo = "equipo"`, `cifrado = "veracrypt"`; en la flota « (equipo, cifrado)» |
| C19 | OK | `agente.py abrir` con la raíz bloqueada: pide desbloquearla, VeraCrypt pide la contraseña y la ventana sale sola (8 s) |
| C20 | OK | El recorrido otra vez con la raíz abierta: «montada en Q:\» sin volver a montar, el mismo id y el mismo pid del agente |

### Fase 4 — Bandeja en Windows

| Prueba | Resultado | Observación |
|---|---|---|
| B1 | PARCIAL | El icono sale (primero en el desbordamiento «^», como todo icono nuevo en Windows 11; subido a la barra con el mismo valor que usa Configuración) y nítido a 16 px al 100 %. 125/150/200 %: no (cambiaría la pantalla de la persona) |
| B2 | PARCIAL | Simulado: quitado el icono desde fuera (`NIM_DELETE`) y mandado `TaskbarCreated` → vuelve con su estado. Reiniciar el Explorador de verdad, o arrancar antes que la barra: no |
| B3 | NO PROBADA | Pintar el menú y pinchar: saldría sobre la ventana de la persona |
| B4 | PARCIAL | El menú calculado del estado real es el esperado (cabecera apagada, «Abrir INF22» por defecto, «Abrir» de cada unidad, «Sincronizar ahora» con submenú Todas + cada una, «Pausar», «Cerrar el agente»). «Pausar»/«Reanudar» por la misma petición: en pausa / se vuelve a sincronizar. «Cerrar el agente» = `parar` (B11) |
| B5 | OK | En la barra real: bien, sincronizando (pastilla azul), aviso (ámbar: fallo y sin conexión), pausa (campo oscuro), bloqueado (insignia negra). Se distinguen a 16 px por el color; las barras de pausa y el candado no se leen (§6) |
| B6 | PARCIAL | Con `subst`: quitar visto en 0,5–0,8 s, poner en 0,5–2,6 s; un montaje de VeraCrypt, 1,9 s después: llega `WM_DEVICECHANGE`. Un USB de verdad enchufado: no |
| B7 | PARCIAL | La entrada «Atender…» y el `PIDE_ATENDER` están en los tests; en real se atendió por la ventanita (A4) y por la ventana de la unidad (V5) |
| B8 | OK | Abierta: «Abrir INF22» / «Bloquear INF22» / la casilla. Bloqueada: «Abrir INF22…» / «Desbloquear INF22…». Desbloquear → «Desbloqueando… la pide VeraCrypt» (apagada) → cancelada → a los 20 s se vuelve a ofrecer. «Abrir…» bloqueada → contraseña → la ventana sale sola. La casilla la escribe el agente |
| B9 | OK | Los avisos de A6 y A10 cuelgan del icono de la bandeja (sin icono de paso), con título y texto; de advertencia el fallo, informativo el «sin conexión» |
| B10 | PARCIAL | Simulado con `WM_POWERBROADCAST`/`PBT_APMRESUMEAUTOMATIC`: «el equipo vuelve de la suspensión» y sonda inmediata. Suspender: no |
| B11 | PARCIAL | `parar` y desinstalar: sin icono huérfano. Cerrar sesión: no |
| B12 | NO PROBADA | ARM64 |

### Fase 5 — Ventana ↔ agente

| Prueba | Resultado | Observación |
|---|---|---|
| V1 | OK | «Iniciar servicio» con el agente en `daemon`: ningún `pythonw` nuevo de la unidad; «…vuelve a sincronizar este dispositivo en cuanto se cierre esta ventana»; el agente vuelve a los 0,7 s (sin gracia) con una pasada y su lock lleva las parejas y el intervalo elegidos |
| V2 | OK | En `sync`: el servicio de siempre (`pythonw … runsync.py --daemon`) y el agente «la atiende otro servicio (pid …)». Con el agente parado, igual; al volver se aparta, y cuando ese servicio se va (`daemon.stop`) toma el relevo |
| V3 | OK | En marcha: «lo sincroniza en segundo plano»; en pausa: «Está en pausa para todo…»; parado: en ámbar, «arranca al iniciar sesión» |
| V4 | OK | «Nada» → el agente suelta el lock a los 3,6 s; `agente.json` con la hora del agente (no de la ventana); vuelta a «segundo plano» → 2,5 s |
| V5 | OK | «Ahora no», y en la ventana de la unidad «no lo tiene en su lista… Atender…» → entra con el modo y el nombre de su flota |
| V6 | PARCIAL | La casilla de la raíz cifrada lee `agente.json` y lo pide al agente, que lo escribe; en una unidad y en una raíz sin cifrar no sale (`None`). Cerrar sesión: simulado en C8/C9 |
| V7 | OK | = R9 |
| V8 | OK | Un aviso «Hay una versión nueva de prdrive: v0.5.1 — Tienes la 0.5.0» (una vez), `status` lo dice y el menú ofrece «Actualizar a la v0.5.1». Actualizar: descarga, comprueba y ejecuta SU `--update-agente`; `agente\0.5.1`, `instalacion.json`, la tarea y el `.lnk` apuntan a 0.5.1, `agente\0.5.0` borrado, agente viejo parado y el nuevo arrancado por su tarea, aviso «prdrive actualizado a la v0.5.1». 13 s. Las unidades se quedan en su versión (solo se actualizan las raíces) |
| V9 | PARCIAL | Abierta, con y sin su ventana abierta: el código a la vX, sin tocar `sync_config.toml`, `rclone.conf` ni el fichero de control; la ventana sigue viva. Bloqueada: «INF22: bloqueada; su ventana ofrecerá la versión nueva al desbloquearla». Que la ventana lo ofrezca: sin release real no se ve |
| V10 | OK | Otro Python fijado → `runtime\<id nuevo>` al lado; el viejo (con el que corría «Actualizar») no se borra esa vez, y lo recoge la actualización siguiente; el agente nuevo arranca con el nuevo |
| V11 | OK | Con un proxy que corta la descarga: «No he podido descargar…», aviso «prdrive: no he podido actualizar», el agente sigue igual (mismo pid). El aviso enseña el error crudo (H-9) |
| V12 | NO PROBADA | Linux |

### Fase 6 — Bandeja en Linux

T1–T12: **NO PROBADAS** (no hay ningún Linux con escritorio disponible).

## 5. Hallazgos

### H-1 · La raíz cifrada del equipo nunca se crea dispersa (C2) — el más importante

- `crypto.soporta_dispersos(root)` pregunta a `GetVolumeInformationW` con la
  ruta que recibe (`install/crypto.py:343`), y esa llamada **solo acepta la
  raíz de un volumen** (`C:\`): con una carpeta falla y devuelve False.
  `crypto.sistema_de_ficheros()` (`:236`, vía `device.volume_for()`) devuelve
  `""` con una carpeta.
- En las unidades se le pasa `G:\` y funciona. En la raíz del equipo,
  `raiz_equipo.abrir_o_crear()` (`install/raiz_equipo.py:496-497`) y el paso
  «Cifrado» (`ui/tk_equipo.py:299`) le pasan la **carpeta** del contenedor.
- Medido: `C:\` → NTFS y dispersos True; `C:\Users\pcerqueda\PRDRIVE-cifrado`,
  `C:\Users\pcerqueda` y `C:\prdrive-pruebas` → `''` y False.
- Consecuencias: el contenedor se escribe **entero** (2 GiB en 6,9 s en este
  SSD; en un disco lento o con un tamaño grande, minutos), el paso dirá «se
  escribe entero al crearlo», el tope FAT32 no se comprueba en ese camino, y el
  hallazgo `espacio` de «Reparación» (que es para contenedores dispersos) no
  puede salir nunca (C12).
- Arreglo probable: resolver antes la raíz del volumen (`GetVolumePathNameW`)
  dentro de esas dos funciones, que es donde está el supuesto.

### H-2 · El agente puede dejar `daemon.lock.json` huérfano al abrir la ventana (batería)

- `test_agente_contrato.py` falla en Windows en las dos pasadas de la batería:
  `PermissionError: [WinError 32]` en `Agente._soltar()` (`agente.py:921`), al
  borrar `daemon.lock.json` mientras el `stop_previous_daemon()` de runsync lo
  está leyendo (Python abre sin `FILE_SHARE_DELETE`).
- `_soltar()` pone `con.lock = None` (`:919`) **antes** del `unlink`: si falla,
  el lock se queda en la unidad con el pid del agente y las siguientes llamadas
  ya no lo intentan. La excepción se sale de `_contrato()` y el agente pierde
  esa vuelta («error en una vuelta»). runsync espera `STOP_WAIT_SECONDS`, borra
  él el lock y dice que el servicio «está ocupado (¿sincronización en curso?)»,
  que no es verdad.
- En real no salió en 4 aperturas (A12): la ventana es de milisegundos. Pero
  la batería lo reproduce siempre en Windows.

### H-3 · «Bloquear» pregunta si forzar sin nada abierto (C4)

- En 3 de 7 «Bloquear» VeraCrypt preguntó «Volume contains files or folders
  being used by applications or system. Force unmount?». Restart Manager no
  encontró ningún proceso con ficheros abiertos en Q:, y el `.hc` solo lo tenía
  System (el driver).
- Pasó con el volumen recién instalado (117 ficheros recién escritos, dos veces
  seguidas en 3 min) y justo después de las pasadas del agente al arrancar.
  «Bloquear» en frío: limpio en 1–4 s. La correlación es con escrituras
  recientes en un volumen **NTFS** (el de dentro de la raíz en Windows): cuadra
  con Sophos, el indexador o `TrkWks` (que en NTFS tiene abierto
  `System Volume Information\tracking.log`). Sin herramienta de handles no está
  confirmado. En la campaña de G: el volumen de dentro era exFAT y no pasó.
- Lo que cuesta: el diseño deja la decisión de forzar a la persona, y si la
  pregunta sale sin motivo aprenderá a decir «Sí»… también cuando sí hay algo
  abierto. VeraCrypt solo reintenta 1,5 s. Una salida posible es esperar unos
  segundos tras la última pasada, o reintentar una vez antes de dejar que
  pregunte.

### H-4 · «Tu carpeta personal» con OneDrive avisa al revés (R5)

`raiz_equipo.examinar(~, PERSONAL)` devuelve el ámbar «C:\Users\pcerqueda está
**dentro de** una carpeta que ya sincroniza OneDrive… mejor una carpeta fuera».
Es al revés: la carpeta personal *contiene* OneDrive. Como el `return` del
cliente (`install/raiz_equipo.py:130`) va antes que el de la carpeta personal
(`:136`), la explicación de «Tu carpeta personal» no se enseña nunca en un
Windows con OneDrive, que es lo normal en Windows 11. El aviso por pareja
(`revisar_local`) sí es correcto y es lo que importa.

### H-5 · La batería no es portable a Windows

8 de los 9 ficheros que fallan son tests de Linux sin guarda (lista en §3). Sin
CI, quien pase la batería en Windows ve 9 fallos y no sabe cuál es de verdad.

### H-6 · Los avisos salen como «Python» (A6, A10, V11)

Windows titula la notificación con la descripción del ejecutable
(`pythonw.exe` → «Python»), no «prdrive». El icono sí es el de prdrive.

### Menores

- **H-7** `agente.py pasada ID PAREJA` con una pareja que no está en las del
  servicio no hace nada y no lo dice: la orden responde «Petición apuntada…» y
  el diario queda mudo (`agente.py:1434`).
- **H-8** La raíz en claro que queda tras recifrar (fuera de la lista) enseña
  en su ventana «no lo tiene en su lista: pregunta al enchufarlo… Atender…»
  (`ui/watch.py:305`). Una raíz no se enchufa, y «Atender» la añadiría como
  unidad sin ruta, que el agente nunca encontrará.
- **H-9** El aviso de V11 enseña el error crudo
  (`<urlopen error [WinError 10061] …>`).
- **H-10** Desinstalar dice «(la clave incluida)» aunque no haya clave (remoto
  sin clave; es la misma nota que en K2 de la campaña de G:).
- **H-11** `prdrive-install.exe --instalar-agente` / `--desinstalar-agente`
  no dicen nada al terminar bien: el `.exe` es `--windowed` y `print()` no sale.
- **H-12** Con el asistente ejecutado **como administrador**, `letras_libres()`
  vería libre una letra que en la sesión normal es de red (aquí P:), y el
  agente —sin elevar— la encontraría ocupada. Solo si se lanza elevado.

## 6. Observaciones

- **Paso «Carpeta» + VeraCrypt** (C13): sobre una raíz en claro, «Carpeta»
  dice «Ya es la raíz de este equipo (id 7d9f…). Se vuelve a instalar con el
  mismo id», y la cifrada sale con un id nuevo (bdf8…). El recuadro rojo de
  «Cifrado» lo explica, pero las dos frases seguidas se contradicen.
- **Iconos a 16 px** (B5): se distinguen por el color de la insignia o del
  campo; las barras de «pausa» se leen como una mancha blanca y el candado de
  «bloqueado» como un punto negro. Barra oscura: no probado.
- **Tras una actualización o un inicio de sesión**, el agente arranca por su
  tarea en el escritorio real, y una unidad cifrada de la lista enchufada y
  cerrada hace que VeraCrypt pida la contraseña: es lo que dice A13.
- **El agente se detecta rápido**: unidades en ~0,5–3 s tras enchufar (con
  bandeja), raíces cifradas a los ~2–3 s de montar.

## 7. Lo que queda por ver en un equipo de verdad

- **Con la persona delante, en este equipo (unos 10 min):** el menú de la
  bandeja con el ratón (B3, B4); un USB físico (B6); cerrar sesión y volver
  (A1, C8, C9, B11); la escala al 125/150/200 % (B1); reiniciar el Explorador
  (B2); suspender (B10, C10); el UAC de «Crear y montar» con NTFS dentro (C2);
  el asistente «En este equipo» pintado (C1, C11).
- **Con un VeraCrypt instalado de verdad** (MSI completo): la fase 3 otra vez,
  sobre todo H-3.
- **Con una release publicada que traiga `--update-agente`**: V8/V9 con
  GitHub de verdad, y que la ventana de una raíz desbloqueada ofrezca
  «Actualizar…».
- **Otros equipos:** Windows ARM64 (A15, B12), Linux con KDE/GNOME (A3, A7, A9,
  A11, R3, C15–C17, V12, T1–T12), y R6 con Dropbox.

## 8. Limpieza

- Agente desinstalado; penwatch no está (tampoco lo estaba antes).
- Contenedores desmontados, sin `subst`, sin procesos de las pruebas. El valor
  `IsPromoted` que se puso al icono del agente, quitado.
- Borradas las raíces de prueba (`%USERPROFILE%\PRDRIVE` y `PRDRIVE-cifrado`),
  las unidades de prueba, el remoto de prueba y el VeraCrypt de pruebas.
  `%APPDATA%\VeraCrypt` sigue vacío.
- `G:` vacía (exFAT, PEREPEN).
- Queda en `C:\prdrive-pruebas`: los scripts, el diario de las pruebas y las
  capturas de la bandeja (solo iconos).
- Sin tocar: el proceso `pythonw` (pid 12344) que corría desde el G: anterior
  desde el 28/09 11:58 (el de la #56).

## 9. Arreglos después de las pruebas

Cada uno con su test, visto en rojo antes del arreglo. La batería, en Windows,
en el escritorio oculto.

| Hallazgo | Arreglo | Test |
|---|---|---|
| H-1 | `crypto.soporta_dispersos()` y `crypto.sistema_de_ficheros()` preguntan al volumen que guarda la ruta (`device.raiz_del_volumen()`: `GetVolumePathNameW` en Windows, el punto de montaje en POSIX), exista ya la carpeta o no | `test_crypto_volumen.py` (nuevo): una carpeta contesta lo mismo que la raíz de su volumen |
| H-2 | `Agente._soltar()` deja de atender en el acto (`con.lock = None`) y, si el fichero no se deja borrar, lo reintenta en las vueltas siguientes (`Conexion.soltando`), sin lanzar nada mientras | `test_agente_contrato.py`: el borrado falla tres veces seguidas; la vuelta no se cae, no se lanza la pareja que tocaba y el lock acaba borrado. La parte con el runsync de verdad, que fallaba en cada pasada en Windows, pasa 5 de 5 |
| H-4 (R5) | «está dentro de» solo cuando la raíz está dentro de lo que sincroniza otro; la carpeta personal que contiene OneDrive enseña su explicación y una frase sin ámbar; una carpeta propia que lo contiene lo dice así | `test_raiz_equipo.py`: las dos direcciones |
| H-5 | Los tests de Linux corren también en Windows: lo que es de Linux se hace Linux en cualquier sistema (`IS_WIN`; y para un punto de montaje en carpeta, `Unidad.letra`), como ya se hacía Windows en cualquier sistema; lo que no puede correr (sockets de fichero, el `select()` de la bandeja de Linux) dice `(saltado) …`. Las rutas del `Exec=` de un `.desktop` se esperan con la regla de la especificación (`_harness.en_exec`) | los 8 ficheros de la §3 |

Y uno que salió al arreglar H-5: con `IS_WIN = False`, «¿vive este pid?» es
`os.kill(pid, 0)`, y en Windows la señal 0 es `CTRL_C_EVENT`: un **Ctrl+C a toda
la consola** (el test, `run_all` y el terminal de quien la lanza). Ya estaba al
alcance de `test_agente_veracrypt.py`, que no llegaba a ese punto porque fallaba
antes. `tests/_harness.py` hace ahora que en Windows la señal 0 pregunte de
verdad (nada si el proceso existe, `ProcessLookupError` si no).

H-3 (la pregunta de forzar al bloquear) y los menores (H-6 a H-12) siguen
abiertos.

## 10. Segunda pasada: lo endurecido tras la revisión del PR #54 (30/09)

Windows 11 x64, con el código de `85f5ad3` sin tocar. El agente se instaló sin
elevar, desde `prdrive-install.py`. Se probó con una memoria USB real (Kingston,
exFAT, en `G:`) aprovisionada como prdrive y con la raíz
`%USERPROFILE%\PRDRIVE`. El remoto de pruebas es un `alias` local. Informe
completo en el comentario del PR #54. **La batería en Windows: 76 de 76.**

| Prueba | Resultado |
|---|---|
| E1 | OK con la unidad USB y con la raíz sin cifrar. **Sin ver:** la raíz cifrada en `P:\` (hace falta un VeraCrypt instalado de verdad). |
| E2 | OK. Cuatro agentes lanzados a la vez: uno gana y tres dicen «Ya hay un agente en marcha». |
| E3 | OK tras `--update-agente` y `--update`. Un script que no pasa por el lanzador no pinta los iconos; es lo esperado. |
| E4 | OK en `daemon` y en `sync`. El lanzador dice «a mitad de una pareja»; no hay pasadas solapadas; el lock pasa al servicio de runsync. |
| E5 | OK el corte con el plazo corto (`sync.py` y su `rclone`, el mensaje con la pareja). OK el agente muerto a mitad de pasada: el nuevo no lanza nada hasta que acaba. **Falla H-13**, ya arreglado. |
| E6 | OK: la huella no cambia sin cambios, pregunta tras `sync.py` modificado y tras `--update`, conserva el modo, y vuelve a atenderse al restaurar los bytes. |
| E7 | OK: el `rclone` de las pasadas es `%LOCALAPPDATA%\prdrive\rclone\v1.75.1\rclone.exe`. Una unidad 0.4.3: aviso, nada suyo corre, `vieja` en `estado.json`. **Sin ver:** el `rclone` de la ventana abierta por el agente, la entrada gris de la bandeja y ARM64. |

### H-13 · `parar_agente()` corta al agente justo cuando acaba una pasada larga (E5) — arreglado

`PARAR_ESPERA` (12 s) contaba desde que se empezó a esperar, no desde que acabó
la pasada. Con una pasada de más de 12 s, el agente se cortaba en cuanto ella
terminaba, sin dejarle salir. Visto en real con `--update-agente` y una pasada de
~5 min: la pasada acabó bien a las 10:26:07 y a las 10:26:09 el instalador dijo
«terminado a la fuerza». El agente no apuntó el fin de la pasada ni soltó
`daemon.lock.json`.

**Arreglo:** el plazo cuenta desde la primera vuelta sin pasada, y
`ESPERA_PASADA` solo corta mientras hay una. Test en
`test_agente_endurecido.py`: rojo sin el arreglo y verde con él. Con el mismo
arreglo, la prueba en real acabó en «detenido tras acabar su pasada».

### H-14 · Una pasada cortada deja un `*.partial`, y la siguiente lo sincroniza (E5) — avisado

Tras el corte quedó `grande2.bin.<hash>.partial` (480 MB) en la carpeta local.
La pasada siguiente lo subió como un fichero más. El mensaje del corte lo dice
ahora y dice que se borre en cualquiera de los dos lados.

**No se excluye `*.partial` en los filtros:** cambiaría el md5 de los filtros de
todas las parejas bisync de todas las unidades, y todas pedirían `--resync`.

### H-15 · Tras cortar una pasada, la siguiente falla una vez y avisa (E5) — arreglado

Queda el `.lck` de bisync. La pasada siguiente sale con «Hay un lock de otra
ejecución», y el agente avisa «falla …» como si fuera un fallo nuevo. El mensaje
del corte lo anuncia, y «Reparación» o `--doctor` lo arreglan.

Ese `.lck` caduca solo: las parejas bisync llevan `--max-lock 2m`. Falló porque
el agente nuevo lanzó la pareja dentro de esos dos minutos.

**Arreglo:**
- `parar_agente()` apunta el corte en `pasada.json` (`cortada`), y ya no
  corta la pasada antes que al agente: el agente viejo podía verla acabar,
  avisar del fallo y borrar el registro.
- El agente nuevo deja **solo esa pareja** durante
  `equipo.ESPERA_TRAS_CORTE` (150 s) y sigue con las demás.
- No se borra ningún bloqueo: decide la caducidad de rclone.
- Una pareja que suba `max-lock` en sus propias opciones puede fallar una
  vez, como antes.

Test en `test_agente_endurecido.py`, visto en rojo sin el arreglo.

### H-16 · `--doctor` da un GRAVE falso con un remoto `alias` — abierto, menor

«El baseline no es de esta pareja»: rclone resuelve el `alias` a otra ruta y
`bisync.expected_prefix()` no. Con sftp/webdav no pasa; importa si el catálogo
llega a admitir `alias`.

### H-17 · `agente.py status`, justo tras arrancar un servicio de runsync — trivial

Durante unos segundos dice «en pausa: hay una ventana de runsync abierta».
Después dice «la atiende otro servicio (pid …)». Es transitorio.

### Sigue sin verse

Lo de la §7, más E1 con la raíz cifrada en `P:\`, lo que falta de E7, y todo E
en Linux. Un intento de B6 desactivando el USB desde el Administrador de
dispositivos falló con «Error genérico»: el `pythonw` ajeno de la §8 tenía la
unidad abierta. Solo se quitó y devolvió la letra con `mountvol`.

## 11. Tercera pasada: con la persona delante (30/09)

Windows 11 x64, el mismo equipo, con la persona en el teclado y el código de
`cf819a3`. El agente 0.5.0 sirve la raíz `%USERPROFILE%\PRDRIVE` y la memoria
USB de la §10 (`G:`, «PRUEBA-G»). Cierra lo que la §4 dejó en `PARCIAL` por
tocar la pantalla de la persona.

| Prueba | Resultado | Observación |
|---|---|---|
| A1 | OK | Cerrar sesión (11:54:47) y volver a entrar (11:54:53), sin abrir nada: la tarea `\prdrive` arranca el agente a las 11:54:56 (pid nuevo) y el icono aparece en la bandeja. El agente anterior murió sin escribir «agente detenido», como se espera de un cierre de sesión |
| B1 | OK | Al 100 %: nítido. Al 150 %, con la escala ya puesta al iniciar la sesión: el icono y el texto del menú se ven nítidos. 125 y 200 %: no |
| B2 | OK | Reiniciado el Explorador de verdad: el icono vuelve solo |
| B3 | OK | El menú con el ratón, dado por bueno por la persona (sin más detalle apuntado) |
| B4 | OK (a–c) | Entradas del menú con el ratón, cada una hace lo suyo. «Cerrar el agente» = `parar`, ver B11 |
| B5 | OK | Azul en marcha, blanco en pausa, ámbar con fallo |
| B6 | OK | Un USB físico: visto a los 23 s del corte, según el reloj de Windows; la pasada salió 2 s después de verlo. La persona dice «al instante». Ojo: la medida es del reloj, no de un cronómetro |
| B7 | OK | Dado por bueno por la persona (sin más detalle apuntado) |
| B10 | OK | Suspendido a las 11:51:06 y reanudado a las 11:51:41: «el equipo vuelve de la suspensión» y pasada enseguida. `G:` conserva su letra. Ver la observación 4 |
| B11 | OK | `agente.py parar`: el icono desaparece sin fantasma. Cerrar sesión y volver: no queda ningún icono huérfano |
| A4, A5, A6, A12 | OK | Con la persona delante. A6/B9: un solo aviso, y no se repite en el segundo fallo. A12: la ventana pausa al agente y este vuelve solo |

Tras volver de la sesión, el estado de `estado.json`, los `daemon.lock.json`
de la raíz y de `G:` (con el pid nuevo, sin huérfanos) y las pasadas de las
11:55 (`OK`) son coherentes. No queda `pasada.json`.

Observaciones, ninguna bloquea:
1. B1: el texto de la bandeja «prdrive — al día» se ve «cutre»; se prefiere un
   indicador más cuidado.
2. B5: la línea gris de la cabecera del menú («falla PRUEBA-G») «no es muy
   estética».
3. Sugerencia: un aviso nativo de «unidad detectada» al enchufar una unidad ya
   atendida. Hoy solo avisa de fallos y de unidades nuevas.
4. B10: «el equipo vuelve de la suspensión» sale dos veces (11:51:44 y 11:51:45):
   Windows manda dos eventos de reanudación. Inofensivo.
5. A12: el diario no dice cuándo el agente reanuda tras cerrarse la ventana
   (solo «ventana abierta» y «en pausa»).

   **Arreglados después, la 4 y la 5**, cada una con su test visto en rojo antes:
   - la 4: el agente apunta una sola vuelta de la suspensión cuando llegan dos
     en `agente.DESPERTAR_DOBLE` (10 s);
   - la 5: al volver a atender dice «…: sin ventana de runsync; vuelvo a
     atenderla» en su diario, y «reanudado» en el `daemon.log` de la unidad.

   La 3 queda para otra PR.

   **La 1 y la 2, cambiadas después** (sin ver en real: E8 de la lista):
   - el texto del ratón dice cuándo acabó bien la última pasada: «prdrive ·
     sincronizado hace 5 min»;
   - el menú ya no tiene cabecera gris. Con algo mal, arriba van los avisos, y
     cada uno lleva a su arreglo: «PRUEBA-G: falla docs · Abrir…», «Sin
     conexión: … · Probar ahora» o «Volumen fantasma en … · Bloquear»;
   - las entradas llevan icono: en Windows, glifos de `ui/icons.py` del color
     del texto del menú; en Linux, los del tema del escritorio.
6. B1: un cambio de escala **en caliente** estira el icono y el menú, porque el
   proceso declara DPI de sistema y toma el de la sesión al empezar. Es lo
   normal en Windows; con la escala puesta al iniciar la sesión, se ve bien.

Sigue sin verse de esta lista: B1 al 125 y 200 %, la barra oscura, C8 y C9
cerrando sesión con la raíz cifrada, C10, y lo que ya decía la §10.
