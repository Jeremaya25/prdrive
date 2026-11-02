# Proteger la contraseña de VeraCrypt de los keyloggers (#199)

Fecha: 2026-11-01 · Estado: **implementado** (PR #203) (decidido con la persona en la conversación
del issue; plan en `docs/superpowers/plans/2026-11-01-escritorio-seguro.md`) · Área:
`docs/agents/reference/veracrypt.md`, `vestibule.md`, `penwatch.md`, `agent.md`,
`ui.md` · Sin probar en real: todo lo de la sección «Lo que queda para una máquina
real».

## Qué se pide

Una opción, **desactivada por defecto**, que proteja la contraseña del contenedor
VeraCrypt mientras se teclea para abrirlo. Si el entorno no lo permite, prdrive abre
como siempre y lo dice, con el motivo; nunca deja a nadie sin poder abrir.

## Decidido con la persona

1. **Alcance: solo la ventana de VeraCrypt.** Lo que abre la ventana de contraseña
   de VeraCrypt: `Abrir PRDRIVE.bat`, `abrir-prdrive.sh`, penwatch y el agente (una
   unidad al conectarla y la raíz cifrada del equipo al «Desbloquear»). El asistente
   (crear y montar con `/password` en Windows, `--stdin` en Linux) sigue igual, y el
   texto de la opción dice que no lo cubre.
2. **La opción vive en la unidad**, no en el equipo: una línea en la marca del
   vestíbulo, `.prdrive-vestibulo`, que está siempre al lado del contenedor. Así la
   cumple el `.bat` en un equipo ajeno sin prdrive, que es donde más probable es un
   keylogger. La raíz cifrada del equipo también lleva esa marca junto a su `.hc`
   (`raiz_equipo.marcar()`), así que el mismo mecanismo vale para las dos.
3. **Linux en X11: solo avisar.** No hay terminal aparte (`veracrypt --text` en otra
   consola virtual): se abre como siempre y se avisa de que no hay protección.

## Lo comprobado en el código de VeraCrypt

Contra `VeraCrypt_1.26.29` (la fijada en `common/pins.py`), `VeraCrypt_1.20` y
`VeraCrypt_1.19`, y contra el AppImage fijado (su SHA-256 coincide con el de
`pins.VERACRYPT_APPIMAGE`):

- **`/secureDesktop` se aplica a la ventana que abrimos.** `/volume X /quit` sin
  `/password` acaba en `AskVolumePassword()` (`Mount/Mount.c`), que dibuja el
  diálogo con `SecureDesktopDialogBoxParam()` (`Common/Dlgcode.c`). El interruptor
  de línea de órdenes manda sobre la preferencia guardada
  (`bCmdUseSecureDesktopValid ? bCmdUseSecureDesktop : bUseSecureDesktop`), así que
  no hace falta tocar la configuración de ningún VeraCrypt instalado.
- **La copia elevada lo recibe.** El Portable sin administrador se relanza con
  `"/q UAC " + args` (`LaunchElevatedProcess()`, `Common/Dlgcode.c`): los mismos
  argumentos, `/secureDesktop` incluido.
- **Si no se puede, VeraCrypt vuelve a su ventana normal EN SILENCIO.** Si
  `CreateDesktop()` o `SetThreadDesktop()` fallan, `SecureDesktopDialogBoxParam()`
  cae en «fallback to displaying in normal desktop»: ni error ni código de salida.
  Desde fuera no se puede saber. Lo único que lo delata es lo que ve la persona: en
  el escritorio seguro no hay nada detrás del diálogo.
- **Sin escritorio de entrada, espera.** Antes de crear el suyo, VeraCrypt espera en
  bucle a `OpenInputDesktop()` (con la sesión bloqueada, hasta que se desbloquee).
- **Existe desde la 1.20.** `L"/secureDesktop"` está en `Mount.c` de la 1.20 y no en
  el de la 1.19. Un VeraCrypt anterior no lo conoce: con varios argumentos, una
  opción desconocida es `AbortProcess ("COMMAND_LINE_ERROR")` y **no abre nada**.
  Por eso se mira la versión antes de pasarlo.
- **La versión se lee del recurso del ejecutable.** `FILEVERSION 1,26,29,3` en la
  1.26.29 y `1,19,4,0` en la 1.19 (`Mount/Mount.rc`): mayor y menor de
  `VS_FIXEDFILEINFO.dwFileVersionMS`.
- **`/enableIME` no se usa.** En la 1.26.29 (y en `master`) su `case` no tiene
  `break` y cae en `OptionDisableDeviceUpdate`: activarlo apaga además el refresco
  periódico de la lista de unidades. Sin él, el IME se desactiva en el escritorio
  seguro (`ImmDisableIME`), que es lo que VeraCrypt hace por defecto.
- **Crear no se puede proteger, nunca.** VeraCrypt Format en modo de órdenes
  (`/create`) aborta sin contraseña (`ERR_PASSWORD_MISSING`, `Format/Tcformat.c`), y
  Format no usa `SecureDesktopDialogBoxParam()` para la contraseña del volumen.
- **Linux: el VeraCrypt gráfico usa el GTK del sistema y no fuerza X11.** El
  AppImage no trae GTK (`libgtk-3.so.0` y `libgdk-3.so.0` son del equipo), su
  `AppRun` solo toca `LD_LIBRARY_PATH` y nada en `src/Main` fija `GDK_BACKEND`. GTK 3
  prueba Wayland antes que X11, así que en una sesión Wayland su ventana debería ser
  un cliente Wayland nativo. Falta verlo en real.
- **Tk va por XWayland** (Tk 9.0 no tiene backend Wayland): los campos de contraseña
  del asistente no quedan aislados de otros clientes X11. Es otra razón para no
  cubrir el asistente.

## Qué cubre y qué no (lo que dice la opción)

Cubre la contraseña que se teclea en la ventana de VeraCrypt al abrir el
dispositivo: en Windows, frente a los programas de la sesión (la mayoría de los
keyloggers de usuario); en Linux, en una sesión Wayland, frente a otros programas
de la sesión. **No cubre** un keylogger con permisos de administrador o a nivel de
driver/kernel, la contraseña que se escribe en el asistente al crear el dispositivo
o la raíz del equipo, ni la que se teclea en un terminal (Linux sin VeraCrypt:
udisks2 o cryptsetup; o VeraCrypt en modo texto).

## Diseño

### 1. La marca lleva la opción

`.prdrive-vestibulo` gana una línea que empieza por `escritorio_seguro=1`. Sin ella
(o con otro valor), desactivada. Es la única fuente: nadie más la guarda. Los tres
lectores la leen igual, desde el principio de la línea y sin mirar lo que sigue al
`1` (`findstr /b`, `grep '^…'` y `startswith`), para que no discrepen con una marca
editada a mano.

- `common/vestibulo.py`: `ESCRITORIO_SEGURO = "escritorio_seguro"`,
  `escritorio_seguro(raiz) -> bool` (lee; no lanza) y
  `poner_escritorio_seguro(raiz, valor)` (reescribe la marca conservando el resto de
  líneas, quitando la clave y añadiéndola si `valor`; atómica, destapando y volviendo
  a ocultar el fichero en Windows; lanza `OSError`).
- `install/vestibulo.marca(device_id, escritorio_seguro=False)` la escribe;
  `escribir()` y `raiz_equipo.marcar()` leen la de antes y la **conservan** si es del
  mismo id: el paso 5, «Añadir plataformas…» y rehacer la marca de la raíz del equipo
  no apagan la opción, y un dispositivo nuevo sobre una marca vieja empieza apagado.
- `penwatch.VESTIBULE_SECURE_KEY` es la copia de la clave (penwatch no importa nada
  del proyecto), con su test como las demás copias.

### 2. Windows: `/secureDesktop`, si el VeraCrypt lo tiene

- **penwatch** (y con él el agente, que abre por `penwatch.open_container()` y
  `penwatch.veracrypt_command()`): `proteccion(container, exe) -> Proteccion` decide,
  sin efectos salvo leer la marca de al lado del contenedor y la versión del
  ejecutable. `Proteccion(pedida, motivo)`: `pedida` dice si la marca la pide;
  `motivo` vacío si se aplica, o por qué no. `veracrypt_command()` añade
  `/secureDesktop` cuando `pedida and not motivo` y es Windows.
  - `veracrypt_version(exe) -> tuple[int, int] | None`: punto de indirección, ctypes
    sobre `version.dll` (`GetFileVersionInfoSizeW`, `GetFileVersionInfoW`,
    `VerQueryValueW("\\")`, firma `0xFEEF04BD`). `None` fuera de Windows o si no se
    puede leer.
  - Motivos: versión anterior a la 1.20; versión que no se ha podido leer.
- **`Abrir PRDRIVE.bat`**: una subrutina `:proteccion`, llamada después de elegir el
  VeraCrypt y antes de lanzarlo. Si `findstr` encuentra `escritorio_seguro=1` al
  principio de una línea de la marca, pregunta la versión a PowerShell **por el
  código de salida** (`exit mayor*1000+menor` sobre
  `(Get-Item $env:VC).VersionInfo`, sin paréntesis: los `.bat` no llevan ninguno en
  una línea de órdenes). Entre 1020 y 8999, `VC_SEGURO=/secureDesktop`; entre 1000 y
  1019, aviso de versión antigua; cualquier otro (0 sin versión, 1 error, 9009 sin
  PowerShell), aviso de versión desconocida. La orden de montar lleva `%VC_SEGURO%`.
  Con la opción aplicada, la línea de «Abriendo…» dice que la ventana sale en un
  escritorio aparte.
- **Nada detecta el regreso silencioso** a la ventana normal: la ayuda de la casilla
  dice cómo notarlo («si al escribirla ves tus ventanas detrás…»).

### 3. Linux: comprobar la sesión, no cambiar la orden

No se añade nada a la orden de VeraCrypt. Con la marca pidiéndolo:

- protección si `WAYLAND_DISPLAY` no está vacío y `GDK_BACKEND` está vacío o empieza
  por `wayland` o por `*` (el orden de siempre de GTK, que empieza por Wayland);
- si no, motivo: «la sesión no es Wayland» (X11) o «`GDK_BACKEND=…` hace que VeraCrypt
  vaya por X11».

Lo decide la misma `penwatch.proteccion()`. `abrir-prdrive.sh` lo repite en una
función `proteccion()`, llamada antes de cada vía: `ventana` antes del VeraCrypt
gráfico (las dos comprobaciones), `terminal` antes de `veracrypt --text`, udisks2 y
cryptsetup («la contraseña se escribe en esta terminal y la protección solo cubre la
ventana de VeraCrypt»).

### 4. Avisos: una vez por apertura, con el motivo

- `.bat` y `.sh`: unas líneas en su consola antes de lanzar VeraCrypt.
- penwatch: su diario (`log()`), en `open_container()`.
- El agente: un aviso del sistema (`avisar()`), que ya es una vez por conexión
  porque la apertura lo es. `penwatch.open_container()` gana un `al_avisar(motivo)`
  opcional que el agente pasa; para la raíz del equipo, el agente llama a
  `penwatch.proteccion()` con la orden que ya ha construido.

### 5. La casilla, en «Ajustes → Configuración»

- **«Proteger la contraseña de VeraCrypt de los keyloggers»**, solo cuando el
  dispositivo vive en un contenedor VeraCrypt (hay raíz física con marca).
- Sin leer en el hilo de Tk: `instantanea.leer()` gana el campo `escritorio_seguro`
  (`cifrado.escritorio_seguro(fisica)` → `cifrado.EscritorioSeguro(valor,
  bat_anterior)` o `None`), y «Ajustes» se lo pasa a `tk_configuracion.construir()`.
  Sin lectura compartida, no hay casilla.
- «Guardar» escribe la marca (`cifrado.guardar_escritorio_seguro()`), como ya escribe
  el intervalo; si no puede, lo dice y no cierra. La lectura no ve caducar la marca,
  así que «Ajustes» se queda con lo guardado para redibujar el apartado, y al cerrarse
  la ventana principal vuelve a leer.
- `bat_anterior`: el `Abrir PRDRIVE.bat` de al lado no lleva todavía la subrutina
  nueva (se busca su texto). Entonces la ayuda añade que en Windows, sin el agente,
  hace falta «Añadir plataformas…» para que la cumpla.
- Ayuda: `cifrado.ayuda_escritorio_seguro()`, en llano, con lo que cubre y lo que
  no (la sección de arriba).

### 6. Lo que no cambia

- Desactivada por defecto: una marca sin la línea es lo de siempre, byte a byte en la
  orden.
- No se toca la configuración de ningún VeraCrypt instalado (`veracrypt.md`, «There is
  no favourite»): solo el interruptor de línea de órdenes.
- El asistente, BitLocker, y Linux sin VeraCrypt (salvo la línea de aviso).
- **Dispositivos en uso**: el agente lo cumple al actualizarse; un penwatch instalado
  saldrá «desfasado» (`copia_al_dia()`) hasta reinstalarlo; los `.bat`/`.sh` nuevos
  llegan con «Añadir plataformas…» o reinstalando, nunca con `--update` (como todo el
  vestíbulo).

## Pruebas

Sin ventana ni dispositivo:
- `test_penwatch_vestibulo.py`: la copia de la clave; `proteccion()` en Windows
  (versión 1.26, 1.19, ilegible; sin la línea) y en Linux (Wayland, X11,
  `GDK_BACKEND`); la orden con y sin `/secureDesktop`, también la de la raíz del
  equipo; el motivo en el diario y en `al_avisar`. En Windows (CI),
  `veracrypt_version(sys.executable)` lee la versión de python.exe.
- `test_vestibulo.py`: la marca con y sin la línea, `escribir()` que la conserva;
  `:proteccion` del `.bat` (lee la marca, umbrales 1020/9000, `%VC_SEGURO%` en la
  orden, sin paréntesis, acentos tras `chcp`); en Windows (CI), la línea de PowerShell
  ejecutada contra python.exe devuelve `mayor*1000+menor`; el `.sh` **ejecutado**
  contra el `veracrypt` de mentira con y sin la línea, en Wayland, X11 y con
  `GDK_BACKEND=x11`, y por udisks2.
- `test_raiz_equipo.py`: `marcar()` conserva la línea.
- `test_agente_veracrypt.py`: el aviso del agente al abrir una unidad y al desbloquear
  la raíz con la opción pedida y no aplicable.
- La casilla: la decisión en `cifrado` (sin Tk) y la casilla en
  `tk_configuracion` (test de ventana, solo en CI).

## Lo que queda para una máquina real

Plan en `docs/superpowers/pruebas/2026-11-01-escritorio-seguro-pendiente-en-real.md`:
Windows con el VeraCrypt instalado y con el Portable (x64 y ARM64), con la sesión
bloqueada al enchufar, por escritorio remoto, con el UAC del Portable, pegando la
contraseña y con un teclado en pantalla; Linux (GNOME y KDE en Wayland, y una sesión
X11): si la ventana de VeraCrypt es cliente Wayland nativo, y si `xinput test-xi2
--root` o `xev` ven lo tecleado en ella y en un campo Tk.
