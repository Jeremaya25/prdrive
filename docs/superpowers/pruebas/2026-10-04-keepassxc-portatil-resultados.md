# KeePassXC portátil en un volumen de prdrive — resultados

Fecha: 04/10/2026. Plan: `2026-10-04-keepassxc-portatil.md` (mismos códigos).
Código de prdrive: `claude/gallant-lamport-95o1u2` en `1e02bc8`.

Hecho **solo en el equipo WA** (el plan pedía W, W2, WI, WA, L, L13 y LA): lo
que en el plan dice «W» se hizo aquí con el ZIP **x64 emulado**, y lo que
necesita «otro equipo» se simuló en este cuando se podía (cada fila lo dice).
Todo se hizo sin manos (UI Automation sobre las ventanas Qt, CDP sobre Brave,
Marionette sobre Firefox, `keepassxc-cli`), así que «pulsar» en esta tabla es
un clic automatizado, no una persona.

## 1. Entorno

- **Equipo (WA)**: Windows 11 Home 25H2 (26200), **ARM64**, sesión con
  administrador. VeraCrypt 1.26.29 **ARM64** instalado. Visual C++ 2015-2022
  x64 y arm64 (14.51) instalados, así que K3 no se pudo ver.
- **Navegadores**: Brave 154 (**ARM64** nativo) y Firefox 143.0.1 (**x64**,
  emulado). **No hay Edge utilizable** (la carpeta `Edge\Application\129…` está
  sin `msedge.exe`) ni Chrome. Brave y Firefox se lanzaron como instancias
  aparte, con perfiles nuevos en D: (`--user-data-dir`, `-profile`), sin tocar
  los de la persona. KeePassXC-Browser: 1.10.4 en Brave (el CRX de la Chrome
  Web Store, desempaquetado con su clave: mismo ID
  `oboonakemofpalcgghocfoadofidjkkk`), 1.10.3 en Firefox (el XPI firmado de AMO).
- **Unidad**: un dispositivo de pruebas **montado aquí**, no el real (P:, que
  no se tocó). Contenedor `D:\PRDRIVE.hc` de 3 GB, **exFAT dentro**, creado con
  `crypto.create_command()` sobre una USB exFAT de 8 GB (D:, ~5 MB/s), con el
  vestíbulo que escribe `install/vestibulo.escribir()` y su `.prdrive/PRDRIVE`.
  Montado en X: y, desde B3, en W:. Disposición del plan: `KeePassXC\`
  (2.7.12 x64), `KeePassXC-2.7.10\`, `KeePassXC-arm64\` (2.8.0-beta1),
  `KeePassXC-2.8-x64\` (2.8.0-beta1 x64, para V3), `KeePassXC-linux\` (sin usar)
  y `llavero\pruebas.kdbx`.
- **Base de pruebas**: creada con `keepassxc-cli db-create` 2.7.12 (KDBX 4.0,
  KDF AES de la CLI; la GUI habría propuesto Argon2). Contraseña `pruebas`.
- **Cuentas**: webauthn.io con usuarios desechables `prdrive-pk1-wa`,
  `prdrive-pk1b-wa` y `prdrive-v2-wa`. GitHub: la cuenta **real** de la persona
  (`Jeremaya25`), con su permiso **solo para passkeys**. Inició sesión ella en
  el Brave de pruebas. Tenía una passkey («pctocho»), que no se tocó. La de
  prueba se añadió, se usó y **se borró** al acabar. La sesión de ese Brave se
  cerró y su perfil se borró.
- **Sección 7**: remoto **local** (`alias` a `D:\pruebas\remoto`), con el código
  de prdrive copiado al volumen (`git archive`) y el rclone fijado (v1.75.1
  windows-arm64, SHA-256 comprobado) pasado por `PRDRIVE_RCLONE`. El segundo
  dispositivo es una carpeta (`D:\pruebas\dispB` con su propio `.prdrive`).

## 2. Tabla de resultados

| Prueba | Resultado | Observación |
|---|---|---|
| K0 | OK (+H-2) | Sumas y firmas de las cuatro descargas (más el MSI ARM64 y el ZIP x64 de la beta) cuadran; firma `BF5A669F…6397D0D2`, subclave `C1E4CBA3…B59076A8`. Los `.DIGEST` vienen en **tres formatos** distintos (H-2) |
| K0b | OK | `HKCU\Software` exportado; ni `%APPDATA%\KeePassXC` ni `%LOCALAPPDATA%\KeePassXC` |
| K1 | OK (+H-1, H-3) | Arranca emulado y deja `config\keepassxc.ini` y `keepassxc_local.ini` junto al `.exe`. El ZIP **ya trae `.portable`** (H-3). Al desbloquear salta **Windows Hello** (H-1) |
| K2 | OK | Ninguna carpeta en `%APPDATA%`/`%LOCALAPPDATA%`. En `HKCU` solo el `MuiCache` del shell con `X:\KeePassXC\KeePassXC.exe`. Más tarde Windows añadió también `FeatureUsage\AppSwitched` y `Compatibility Assistant\Store` (rastros del sistema, no de KeePassXC) |
| K3 | no hecha (deducido) | El equipo tiene el redistribuible. Por las importaciones: `KeePassXC.exe`, `keepassxc-proxy.exe`, Qt5 y botan piden `MSVCP140`, `VCRUNTIME140` y `VCRUNTIME140_1`, y **el ZIP no los trae**: en un Windows limpio no arrancaría. La 2.8.0-beta1 trae `vc_redist.*.exe` dentro del ZIP, sin instalar |
| K4 | OK | Simulado: ZIP en un NTFS (VHDX en D:) con `Zone.Identifier` ZoneId=3 y descomprimido con el Explorador (la marca pasa a cada fichero). Copiado a **exFAT la marca desaparece**; a NTFS se queda. Abierto con el Explorador **desde NTFS con marca: ni SmartScreen ni aviso** (el `.exe` está firmado) |
| K5 | OK | VeraCrypt: «El volumen contiene carpetas o archivos en uso por el sistema o alguna aplicación. ¿Forzar el desmontaje?». Con «No» no se pierde nada y el `.bat` dice «El contenedor sigue abierto en X:. ¿Queda algún programa usando la unidad? Ciérralo y vuelve a intentarlo. No quites la unidad todavía.». Con KeePassXC cerrado: «PRDRIVE está cerrado. Ya puedes quitar la unidad.» |
| K6 | CONFIRMADO | Con KeePassXC cerrado, `X:\KeePassXC\keepassxc-proxy.exe` sigue vivo (hijo de un `cmd.exe` hijo de Brave: H-16) y la expulsión pregunta lo mismo que K5. Hace falta **cerrar el navegador**: el proxy muere a los 3 s y la expulsión sale |
| K7 | OK (simulado) | Sin desenchufar: desmontaje **forzado** de X: justo después del autoguardado (≤ 2 s tras «Aceptar»). La base abre con la entrada y sin temporales. KeePassXC **se cae** (0xc0000409 en `xtajit64se.dll`, el emulador x64: H-4) |
| B1 | OK (matices) | Marcando Edge, Firefox y Chrome salen **6** JSON (`brave`, `chrome`, `edge`, `firefox`, `tor-browser`, `vivaldi`) con `"path": "X:\\KeePassXC\\keepassxc-proxy.exe"`. En el registro, 3 claves con valor y barras `/`: la de Chrome apunta al JSON de **brave** y la de Mozilla al de **tor-browser** (comparten clave; el contenido es idéntico). Además una clave de **Chromium vacía**, sin haberlo marcado (H-5) |
| B2 | **DISCREPANCIA** | Simulado borrando las claves (un equipo que nunca lo vio) y arrancando desde otra letra. **No se escribe nada útil**: solo 4 claves vacías, y los JSON no se tocan. Brave: «Specified native messaging host not found.». En Ajustes los navegadores salen **desmarcados**: hay que volver a marcarlos. Después conecta con la asociación de siempre (una por perfil de navegador; un navegador de otro equipo pediría la suya). Causa en el código: H-6 |
| B3 | OK | Misma unidad en W:: al arrancar, las 3 claves y los 6 JSON pasan a `W:` sin tocar nada |
| B4 | **DISCREPANCIA** (H-18) | Con la unidad fuera quedan **4 claves**: 3 apuntando a `X:/KeePassXC/config/…json` (que no existe) y la de Chromium vacía. **Desmarcar no las borra.** La 1.ª vez la clave de Chrome pasa a apuntar a `brave.json` y la de Mozilla a `tor-browser.json`. La 2.ª vez se vacían, pero **las 4 claves siguen** y en el volumen quedan `brave`, `tor-browser` y `vivaldi.json`. Hubo que borrarlas a mano |
| B5 | parcial | No hay equipo con el MSI. Visto entre la 2.7.12 y la 2.7.10 portátiles: **el último que arranca se queda con la clave**, y cuando vuelve a arrancar el otro la recupera (la clave ya existe, así que `updateBinaryPaths()` la reescribe). Ninguno se queja |
| PK1 | OK (+H-9) | Por defecto y con «discoverable: required» + «UV: required», en Brave ARM64 con KeePassXC x64: registra y entra (también sin usuario, eligiendo la credencial). Diferencias con el plan: el grupo es «KeePassXC-Browser **Passkeys**» (pregunta antes «¿Desea crear este grupo?») y la entrada se llama «webauthn.io (**Cerrojo**)» (H-9). Cada carga de la página saca además una «Solicitud de acceso al navegador» de autorrelleno |
| PK2 | OK | Con la 2.7.12 en Brave ARM64. «Add passkey» lleva a `/sessions/trusted-device` («Configure passwordless authentication»), y ahí KeePassXC registra para `github.com` / `Jeremaya25` → «Successfully added a passkey». Sin sudo. GitHub la llama «Chrome on Windows» (el apodo no se guardó) y la marca **«Synced»** (lo saca de BE/BS=1). Cerrar sesión y entrar **solo con «Continue with passkey»**: entra. Ojo: con la pestaña en segundo plano (`visibilityState=hidden`), el botón no hace nada, sin error |
| PK3 | parcial | Firefox x64 conecta (el proxy lo lanza `firefox.exe` directamente con `…_tor-browser.json`) y se asocia («WA-firefox-x64»). No se consiguió activar «Enable Passkeys» por automatización (el clic no se guarda), y sin esa opción Firefox manda la petición al **selector nativo de Windows** («Elige una clave de paso»). Sin concluir: a mano son dos clics |
| PK4 | parcial | WA: OK en webauthn.io y en GitHub (Brave ARM64 + KeePassXC x64). W2 y L: no hay equipos |
| PK5 | OK (+H-15) | Aviso: «El archivo llave de acceso va ha estar vulnerable a robos y usos no autorizados si lo dejas desprotegido. ¿Estas seguro de que quieres continuar?». La carpeta que propone es la **carpeta personal del equipo** (`%USERPROFILE%`), salvo `KPXC_INITIAL_DIR`. El `.passkey` es JSON en claro (`credentialId`, `privateKey`, `relyingParty`, `url`, `userHandle`, `username`): **no lleva BE/BS**. Borrado |
| PK6 | **DISCREPANCIA** | Con la base bloqueada la petición **se queda esperando en silencio**: ni diálogo de desbloqueo propio, ni el nativo, ni error en 75 s. Desbloquear no la reanuda, y esa pestaña ya no vale aunque se recargue (en otra pestaña sí entra). Al reiniciar KeePassXC, la extensión **no reconecta sola** (H-17) |
| LX1–LX7 | no hechas | No hay Linux |
| LA1–LA3 | no hechas | No hay Linux ARM |
| V1 | OK (webauthn.io y GitHub) | La 2.7.10 firma la passkey de la 2.7.12 (BE=1 al registrar) con **`flags=0x5`, BE=0 BS=0**. webauthn.io: `{"verified": true}`. **GitHub: entra** con la passkey de PK2 desde la 2.7.10, y después ya **no la marca «Synced»**: actualiza el estado de copia con cada uso en vez de rechazar el cambio |
| V2 | OK en webauthn.io; GitHub no hecho | La 2.7.10 registra sin `KPEX_PASSKEY_FLAG_BE/BS`; la 2.7.12 firma con **`flags=0x1d`, BE=1 BS=1**. webauthn.io: `{"verified": true}`. En GitHub no se hizo, para no añadir una segunda passkey a la cuenta real |
| V3 | OK (con x64) | Guardada con la CLI de la **2.8.0-beta1 x64** (la ARM64 no arranca: A2), sigue en KDBX 4.0 y la abren la 2.7.12 y la 2.7.10 con las passkeys |
| V4 | OK (CLI) | La 2.7.10 añade una entrada a una base con passkeys de la 2.7.12; la 2.7.12 sigue viendo todos los `KPEX_PASSKEY_*`, BE/BS incluidos |
| A1 | OK | ZIP x64 2.7.12 emulado: K1, B1 y PK4 bien. **Brave ARM64 lanza el `keepassxc-proxy.exe` x64** por mensajería nativa y conecta |
| A2 | **FALLO** (H-7) | 2.8.0-beta1 ARM64: «La aplicación no se pudo iniciar correctamente (0xc000007b)». El ZIP y el MSI ARM64 traen `KeePassXC.exe` ARM64 pero **las DLL de Qt6 en x64** |
| A3 | no hecha | Hace falta W, y A2 no arranca |
| S1 | OK | `up`: sube solo `pruebas.kdbx` |
| S2 | **DISCREPANCIA** (H-11) | Las 10 copias subidas abren todas (siempre una versión entera). Pero rclone **ve los temporales de `QSaveFile`** (`pruebas.kdbx.vMULRt`…), no puede abrirlos y la pasada acaba en FALLÓ (código 6 y 1). Y mientras rclone lee, **KeePassXC no puede guardar** («Acceso denegado»: 20 de 30 en la CLI). En la ventana el cambio se queda en «\*» sin aviso visible; tras ~30 s retenido sale «¿Desactivar almacenajes seguros?» con **«Deshabilitar» por defecto** |
| S3 | OK (+H-12) | KeePassXC de B recarga solo («22 apuntes» = lo que hay en disco). Antes hubo que esquivar H-12: con solo el `.kdbx` en la carpeta bisync aborta siempre |
| S4 | **DISCREPANCIA** (H-14) | Con `versions = true` **no queda copia con sufijo**: gana la más nueva y la otra va a `.prversions/` del lado que pierde (el remoto, y luego A en su pasada). La pasada dice «OK» y `conflicts.json` queda vacío. Recuperar: combinar la versión de `.prversions/` (con `keepassxc-cli merge`, un paso; en la ventana, «Base de datos → Combinar desde base de datos…», elegir el fichero y la contraseña). Nada se pierde, pero nadie avisa |
| S5 | OK (mejor de lo esperado) | Con un cambio sin guardar en B, al llegar la versión de A KeePassXC pregunta **en el momento**: «Recargar base de datos — El archivo de base de datos "pruebas.kdbx" ha sido modificado externamente», con Combinar / Ignorar / Descartar / Cancelar. «Combinar» y guardar: quedan las dos entradas |
| S6 | OK | `--dry-run` subiría `pruebas.old.kdbx` (la copia previa al guardado) y `webauthn.io (Cerrojo).passkey` (sin cifrar). El `.passkey` se borró |
| S7 | OK | Las 13 versiones de `.prversions/` (B, remoto y A) abren |

## 3. Hallazgos

- **H-1. Windows Hello y huella en el equipo.** Al desbloquear, con
  `Security/QuickUnlock` (activo por defecto, en `keepassxc_local.ini`) y Hello
  disponible, KeePassXC llama a `KeyCredentialManager::RequestCreateAsync(
  "keepassxc_winhello", FailIfExists)` y pide el PIN
  (`src/winhello/WindowsHello.cpp`; `DatabaseOpenWidget.cpp`: «Save Quick
  Unlock credentials if available»). Es una credencial de Hello **en el
  equipo**, no en la unidad, y mientras el diálogo espera, la ventana sigue en
  «[Bloqueada]». Con `[Security] QuickUnlock=false` no vuelve a salir
  (comprobado). La fase 1 lo pondría en la configuración portátil. Aquí se
  canceló el diálogo, así que probablemente no se creó la credencial; no se
  puede comprobar sin entrar en el contenedor NGC.
- **H-2. Tres formatos de `.DIGEST`.** 2.7.10 Win: hexadecimal en mayúsculas,
  `*` de binario y sin salto final. 2.7.12/2.8 Win: minúsculas y **CRLF**
  (`sha256sum -c` falla tal cual). AppImage: LF. Si la fase 1 descarga
  KeePassXC con `install/descarga.py`, el lector tiene que aguantar los tres.
- **H-3. El ZIP ya es portátil** (trae `.portable`, también la 2.7.10 y la beta)
  y **no trae el runtime de VC** (K3). La CLI también usa `config\` en modo
  portátil.
- **H-4. Programa dentro del volumen.** Si el volumen se va con KeePassXC
  abierto, el proceso muere (aquí en el emulador; en x64 nativo sería un error
  de página). La base sobrevive gracias al guardado atómico.
- **H-5. Claves del registro.** La de Chrome la comparten Chrome, Vivaldi y
  Brave, y la de Mozilla, Firefox y Tor: gana el último JSON escrito. Además
  aparece una clave **vacía** de Chromium, y en B2 cuatro vacías: el
  `QSettings` de `isBrowserEnabled()` crea la ruta al leerla.
- **H-6. B2: por qué un equipo nuevo no se configura solo.** En Windows,
  `NativeMessageInstaller::isBrowserEnabled()` lee **la clave del registro**,
  no el JSON (`return !settings.value("Default").isNull()`), y
  `updateBinaryPaths()` solo reescribe lo «habilitado». El punto 3 del plan
  («los JSON viven en la unidad, así que en un equipo nuevo… sin ningún clic»)
  es falso: en cada equipo nuevo hay que marcar los navegadores una vez. La
  fase 1 podría escribir ella las claves `HKCU\…\NativeMessagingHosts`
  apuntando a los JSON del volumen (es una clave por navegador, sin admin) o
  decírselo a la persona.
- **H-7. 2.8.0-beta1 ARM64 rota**: `Qt6*.dll` y `dxcompiler.dll` con máquina
  0x8664 (x64 puro, sin metadatos ARM64EC) junto a ejecutables 0xAA64, en el
  ZIP **y** en el MSI (extraído con `msiexec /a`, sin instalar).
- **H-8. 2.7.10 y `--pw-stdin`**: con la base como argumento se cae
  (0xC0000005) emulada. Abierta desde la ventana, bien. Solo afecta a la
  automatización.
- **H-9. La traducción cambia el título.** La 2.7.12 en español llama
  «Cerrojo» a la passkey (entrada «webauthn.io (Cerrojo)», etiqueta
  «Cerrojo») y la 2.7.10 «Passkey». Cosmético, pero confunde al buscar.
- **H-10. PK6.** Ver la tabla. Para la guía: con la base bloqueada, desbloquear
  y **abrir otra pestaña** (o recargar la extensión) antes de reintentar.
- **H-11. S2: rclone y el guardado atómico.** En Windows, `QSaveFile` escribe
  `<base>.kdbx.XXXXXX` al lado y luego reemplaza. (a) rclone lista ese temporal
  y no puede abrirlo → la pasada falla (código 6/1), aunque nunca sube nada
  roto. (b) rclone abre la base sin `FILE_SHARE_DELETE` → el reemplazo falla y
  KeePassXC no guarda mientras dura la lectura. En la ventana, el cambio queda
  pendiente («\*»), sin diálogo, y se guarda al siguiente cambio o a mano. Pero
  tras tres fallos seguidos KeePassXC ofrece «¿Desactivar almacenajes
  seguros?», con «Deshabilitar» como botón por defecto
  (`DatabaseWidget::save()`, `m_saveAttempts > 2`). Aceptarlo cambia
  `UseAtomicSaves=false` en la configuración que viaja, y entonces sí podría
  subir una base a medias. Para la fase 1: filtro `- *.kdbx.??????` en la
  pareja, pasadas **solo con KeePassXC cerrado o con la base bloqueada**, o una
  copia en frío. Y que la guía diga que a esa pregunta se contesta «Cancelar».
- **H-12. bisync y una carpeta de un solo fichero.** «Safety abort: all files
  were changed on Path1 … Run with --force if desired.»: si la carpeta solo
  tiene el `.kdbx`, cualquier cambio es el 100 %. Con un fichero fijo al lado
  (aquí `LEEME.txt`) y un `--resync` en cada lado, funciona. La fase 1 tiene
  que dejar ese compañero en `llavero/`.
- **H-13. `--resync` en un dispositivo con la base más vieja.** prdrive no pasa
  `--resync-mode`, así que rclone usa `path1` (gana el lado local): la base
  vieja pisaría la nueva del remoto. Con `versions = true` la pisada queda en
  `.prversions/` (`conflicts-versions.md`: «A --resync also honours the backup
  dir»). Aquí, B usó `[pair.flags] resync-mode = "newer"`, que el TOML ya
  permite.
- **H-14. S4: el conflicto silencioso.** Diseño documentado
  (`--conflict-loser delete` + `--backup-dir`). Para un llavero, perder en
  silencio la entrada de otro dispositivo hasta que alguien mire
  `.prversions/` es caro. La fase 1 debería avisar del conflicto de esa pareja,
  o combinar sola (`keepassxc-cli merge`) antes de dar la pasada por buena.
- **H-15. Carpeta de exportación.** `FileDialog::getLastDir()` usa
  `KPXC_INITIAL_DIR` y, si no, `QDir::homePath()`. Con
  `KPXC_INITIAL_DIR=<volumen>\llavero` el diálogo abrió en el volumen
  (comprobado). El lanzador de la fase 1 puede fijarla, pero apuntando
  **fuera** de toda pareja (por S6).
- **H-16. Quién lanza el proxy.** Brave (Chromium) lo lanza con un `cmd.exe`
  intermedio. Firefox lo lanza él mismo, pasándole la ruta del JSON. En los dos
  casos el proxy vive lo que viva el navegador (K6).
- **H-17. Reconexión.** Al cerrar y volver a abrir KeePassXC, la extensión de
  Brave se queda en «no disponible» hasta que se recarga desde su popup.
- **H-18. Desactivar no limpia el equipo.** Brave, Vivaldi y Tor no tienen
  casilla propia pero comparten la clave de Chrome/Mozilla, así que al guardar
  siguen «habilitados» y la reescriben con su JSON. Una segunda vuelta vacía los
  valores, pero `QSettings::remove("Default")` deja las claves vacías. Para
  dejar el equipo limpio no basta con los ajustes: hay que borrar
  `HKCU\Software\{Google\Chrome,Microsoft\Edge,Mozilla,Chromium}\NativeMessagingHosts\org.keepassxc.keepassxc_browser`
  (y `Mozilla\NativeMessagingHosts` si no existía). La fase 1 debería hacerlo
  ella, por ejemplo desde «Expulsar».

## 4. Incidencias durante las pruebas

- **Pulsaciones a ciegas.** En el primer desbloqueo mandé `pruebas` + Intro
  con `SendKeys` a la ventana activa, sin saber que delante estaba el diálogo
  de Hello (H-1). Si el PIN es numérico, las letras no entran, pero pudo contar
  como un intento. Desde entonces solo se pulsa con UI Automation sobre un
  elemento concreto, y el clic de ratón comprueba antes que el punto es de esa
  ventana: dos veces evitó pulsar sobre la terminal.
- **Un `.passkey` en C:.** En PK5, el texto de la carpeta no entró y el diálogo
  exportó a la carpeta por defecto: `%USERPROFILE%\webauthn.io (Cerrojo).passkey`
  (passkey de prueba de webauthn.io, sin cifrar). Se apuntó su estructura y se
  borró al momento.
- **Una clave privada en pantalla.** Un `keepassxc-cli show --all` mostró el
  cuerpo PEM de la passkey de prueba `prdrive-pk1-wa` (solo webauthn.io). No
  está en este fichero.
- La primera pasada en seco dejó su log temporal en `%TEMP%` (C:); `sync.py`
  lo borró al acabar. Las demás pasadas usaron `TEMP=D:\pruebas\tmp`.

## 5. Qué dice esto para la fase 1 (según «Qué hacer con lo que salga»)

- **V1/V2**: nadie rechazó. webauthn.io acepta el salto de BE en los dos
  sentidos, y GitHub acepta 1→0 (V1) actualizando su etiqueta «Synced»; 0→1 en
  GitHub no se probó. Con lo visto, **basta con que viaje la base** y el
  programa puede ser el del equipo, siempre que tenga passkeys (≥ 2.7.7). Pero
  conviene ≥ 2.7.12: lo pide el `CHANGELOG` de KeePassXC, y queda la duda de
  sitios más estrictos que estos dos.
- **B2/B3**: B3 sin clics, pero **B2 no** (H-6). En Windows la fase 1 tiene que
  escribir las claves del registro, o la guía decir «marca tus navegadores la
  primera vez en cada equipo». B4 dice qué limpiar: las claves
  `org.keepassxc.keepassxc_browser` de Chrome, Edge, Mozilla y Chromium.
- **K5–K6**: «Expulsar PRDRIVE» tendría que avisar de KeePassXC **y del
  navegador** (el proxy es su hijo) antes de llamar a VeraCrypt.
- **A1** conecta en ARM: la fase 1 puede llevar el ZIP x64 para Windows ARM
  mientras la 2.8 ARM64 esté rota (A2, H-7).
- **S2**: la pareja **no** puede sincronizar la base con KeePassXC guardando
  (H-11). Las pasadas tienen que ser con KeePassXC cerrado o con la base
  bloqueada, más el filtro de temporales.
- **S6**: filtros mínimos de la pareja del llavero: `- *.passkey`,
  `- *.old.kdbx` (o el patrón de `BackupFilePathPattern`) y
  `- *.kdbx.??????`. Además, el compañero fijo de H-12.

## 6. Limpieza

Hecha al acabar:

- **GitHub**: la passkey de prueba («Chrome on Windows», añadida el 4/10/2026)
  se borró. Queda solo «pctocho», la de la persona. Sesión cerrada en el Brave
  de pruebas y su perfil borrado. La entrada «GitHub (Cerrojo)» se borró de la
  base de pruebas (y de su papelera). No llegó a ninguna otra copia ni al
  remoto.
- **Registro**: borradas las 4 claves `org.keepassxc.keepassxc_browser` y
  `HKCU\Software\Mozilla\NativeMessagingHosts` (no existía en `antes.reg`). Los
  hosts que ya había (`com.anthropic.claude_code_browser_extension`,
  `com.microsoft.browsercore`) siguen. Quedan los rastros del propio Windows
  (`MuiCache`, `Compatibility Assistant\Store`, `FeatureUsage`) con rutas X:, N:
  y W:.
- KeePassXC, el Brave y el Firefox de pruebas cerrados. W: desmontado (el `.hc`
  queda libre) y el VHDX N: soltado.
- En D: queda todo lo de las pruebas (`PRDRIVE.hc`, vestíbulo, `pruebas\`,
  `descargas\`, `gnupg\`), con permiso para usar D: libremente.

