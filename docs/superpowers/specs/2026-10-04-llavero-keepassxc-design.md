# El llavero: KeePassXC en el volumen, para contraseñas y passkeys

Fecha: 2026-10-04 · Estado: **propuesta**, por decidir (las preguntas abiertas
están al final) · Versión objetivo: 0.6.0 · De dónde sale:
`docs/superpowers/pruebas/2026-10-04-keepassxc-portatil.md` y sus resultados
(`…-resultados.md`, solo en Windows ARM64; los códigos K/B/PK/V/A/S y los
hallazgos H-n se citan tal cual).

## Qué se pide

Que el volumen cifrado de prdrive guarde las **claves privadas de las
passkeys** (y, de paso, las contraseñas) y que entrar en GitHub y en sitios
parecidos sea rápido desde cualquier equipo donde se abra la unidad. Tiene que
ser útil para quien lleva la unidad y no un montaje que haya que vigilar: sin
pasos que se olvidan, sin restos en el equipo y sin perder entradas al
sincronizar.

## Lo que dijeron las pruebas y lo que decide

| Hallazgo | Qué decide aquí |
|---|---|
| V1, V2: nadie rechazó el salto de BE/BS (webauthn.io en los dos sentidos, GitHub 1→0) | **Lo que importa es que viaje la base.** El programa de viaje se fija en una sola versión (≥ 2.7.12), pero el del equipo vale donde no haya uno de viaje (Linux ARM). §3, §9 |
| A1 bien, A2 roto (H-7) | En Windows ARM se lleva el ZIP **x64**, que corre emulado. §3 |
| K3 (deducido): el ZIP no trae el runtime de Visual C++ | Se detecta al arrancar y se explica qué hacer. §3, decisión 3 |
| H-3: el ZIP ya trae `.portable` | No hay que prepararlo, solo dejarlo como viene. §3 |
| B2, H-6: un equipo nuevo **no** se configura solo | **prdrive escribe las claves del registro** antes de abrir KeePassXC. §5 |
| B4, H-18: desmarcar los navegadores no limpia el equipo | **prdrive las quita al expulsar** y deja como estaba lo que fuera de un KeePassXC instalado (B5). §5, §8 |
| K5, K6, H-16: KeePassXC y el proxy del navegador retienen el volumen | «Expulsar» se ocupa de los dos antes de llamar a VeraCrypt. §8 |
| H-1: Windows Hello crea una credencial en el equipo | `QuickUnlock` empieza apagado. §4 |
| H-11 (S2): rclone ve los temporales del guardado, y el «¿Desactivar almacenajes seguros?» | La pareja del llavero solo deja pasar `*.kdbx`. prdrive vuelve a encender los guardados atómicos en cada arranque y comprueba que la base está entera antes de subirla. §6 |
| H-12 (S3): bisync aborta con un solo fichero en la carpeta | Junto a la base va siempre un fichero fijo. §6 |
| H-13: `--resync` en un dispositivo con la base vieja | `resync-mode = "newer"` en la pareja. §6 |
| H-14 (S4): conflicto silencioso con `versions = true` | En esta pareja el conflicto **se ve**: `conflict-loser = "num"` y «Combinar». §7 |
| S5: KeePassXC combina solo si tiene cambios sin guardar | Se aprovecha como está. §7 |
| S6, H-15: exportaciones en claro | Nunca viajan, por la misma lista de lo que viaja. «Reparación» las enseña. §6 |
| PK6, H-10, H-17: base bloqueada, extensión que no reconecta | Por ahora, la guía. Hay pruebas nuevas para saber más. §10, §13 |
| H-2: tres formatos de `.DIGEST` | No afecta: la suma va fijada en el código, como la de VeraCrypt. §3 |

## La idea

> El **llavero** de un dispositivo es una carpeta `llavero/` con una o varias
> bases `.kdbx`, sincronizada por una pareja más, la pareja `llavero`. Al lado
> va un **KeePassXC de viaje** en `.prdrive/keepassxc/`, que se actualiza como
> rclone o VeraCrypt. Y hay dos acciones nuevas: **«Abrir llavero»** prepara el
> equipo (registro, configuración, la última versión de la base) y abre
> KeePassXC. **«Expulsar»** lo cierra todo y deja el equipo como estaba.

Lo que no cambia:

- **La contraseña de la base nunca pasa por prdrive.** Cuando hace falta
  (combinar dos versiones, §7), la pide `keepassxc-cli` en su propia consola,
  como VeraCrypt pide la suya en su diálogo (`vestibule.md`).
- **prdrive no descifra la base.** Solo comprueba su forma con lo que el
  formato KDBX deja comprobar sin clave (§6).
- **Las passkeys siguen siendo cosa de KeePassXC y de su extensión.** prdrive
  no es un autenticador ni un gestor de contraseñas: lleva, actualiza, prepara y
  limpia.
- **Nada de `.prdrive/` viaja al remoto** (ya era así). El programa y su
  configuración no se sincronizan; la base, sí.

## 1. Lo que vive la persona

1. **Al preparar el dispositivo** (cifrado), el asistente ofrece una casilla:
   «Llevar un llavero (KeePassXC) para contraseñas y passkeys». Si el catálogo
   del remoto ya tiene la pareja `llavero` (de otro dispositivo), sale marcada.
   En un dispositivo que ya existe, el panel «ya es un prdrive» suma «Añadir el
   llavero…» a «Actualizar» y «Añadir plataformas…».
2. **La primera vez**, con la unidad abierta, se pulsa «Llavero» (en la ventana
   de prdrive o en `Llavero.bat` de la raíz del volumen). Una pantalla corta
   explica tres cosas: que se va a crear la base, que su contraseña es
   **distinta** de la de la unidad, y que se guarda donde KeePassXC proponga
   (`llavero/`). KeePassXC se abre en su bienvenida, con el diálogo de guardar
   ya en `llavero/` (`KPXC_INITIAL_DIR`, H-15). Por defecto crea KDBX 4 con
   Argon2. Para usar una base que ya se tiene, se copia a `llavero/`.
3. **En cada navegador** (una vez por perfil de navegador, no por equipo): se
   instala KeePassXC-Browser, se pulsa «Conectar» y se activa «Enable
   Passkeys». La asociación se guarda en la base y viaja con ella (B2).
4. **Cada día**: abrir la unidad → «Llavero» → la contraseña de la base → los
   sitios piden passkey y KeePassXC firma. GitHub la enseña como «Synced»
   (PK2), y es normal.
5. **En otro equipo** (u otra letra): el mismo «Llavero». prdrive escribe el
   registro de ese equipo antes de abrir KeePassXC y no hay que marcar nada en
   sus ajustes (arregla B2). Si ese navegador nunca se conectó, toca el paso 3.
6. **Expulsar** (desde la ventana o con `Expulsar PRDRIVE.bat`): si KeePassXC
   está abierto, se ofrece cerrarlo; el proxy se termina solo. Si hay cambios
   sin subir, se suben. Las claves del registro se quitan y se desmonta como
   siempre. La persona no tiene que cerrar el navegador (K6).
7. **Otro dispositivo con el mismo remoto** recibe la base por la pareja
   `llavero`. Si los dos cambiaron la base sin sincronizar en medio, «Llavero»
   lo dice antes de abrir y ofrece combinar las dos versiones (§7).

## 2. Dónde está cada cosa

```
<volumen>/
├── .prdrive/
│   ├── keepassxc/
│   │   ├── windows-x64/            el ZIP 2.7.12 tal cual (trae .portable); también en Windows ARM
│   │   │   ├── PRDRIVE-KEEPASSXC   el sello (§3)
│   │   │   └── config/             lo que escribe KeePassXC en portátil: SOLO los JSON del navegador
│   │   ├── linux-x64/              fase 2 (§9)
│   │   └── config/
│   │       ├── windows/            keepassxc.ini, keepassxc_local.ini, raiz.txt
│   │       └── linux/              fase 2
│   └── filters/llavero.txt         generado (§6)
├── Llavero.bat · llavero.sh        lanzadores de la raíz del volumen, junto a runsync.*
└── llavero/                        la pareja `llavero`
    ├── LEEME-LLAVERO.txt           el fichero fijo de H-12, y qué es esta carpeta
    └── <nombre>.kdbx
```

- **El programa y la configuración van separados.** La configuración se pasa
  con `--config` y `--localconfig`. Así cambiar de versión sustituye la carpeta
  del programa entera, sin mover nada de la persona. Los JSON del navegador
  siguen en `<exe>/config/` (`getNativeMessagePath()` en portátil), pero
  KeePassXC los rehace en cada arranque (`updateBinaryPaths()`), así que
  perderlos en un cambio de versión no importa.
- **La configuración va por sistema** (`windows/`, `linux/`), porque lleva rutas
  de ese sistema (`LastOpenedDatabases`…). Las dos empiezan con los mismos
  valores (§4).
- **Que el dispositivo lleva llavero se sabe por lo que hay**, como con
  VeraCrypt: `.prdrive/keepassxc/` con su sello y la pareja `llavero` en
  `sync_config.toml`. No hay otro registro.
- `Llavero.bat` y `llavero.sh` siguen las reglas de `runsync.*`: CRLF, sin
  bloques entre paréntesis, `chcp 65001`; los escribe `deploy.write_launchers()`
  y no `--update`. Lanzan `runsync.py --llavero` con el Python del dispositivo,
  sin consola. Se añaden a `device.RUIDO`.

## 3. El componente KeePassXC

- **El pin**, en `common/pins.py`: `KEEPASSXC_VERSION = "2.7.12"` y
  `KEEPASSXC = {clave: (nombre, sha256)}` para `windows-x64` (el ZIP Win64). Se
  añade `KEEPASSXC_PARA = {"windows-arm64": "windows-x64"}`, con el porqué
  citado (A1, A2, H-7). La URL es la de las versiones de
  `keepassxreboot/keepassxc` en GitHub.
- **Mover el pin es a mano**, como con VeraCrypt: comprobar el `.sig` con la
  clave de KeePassXC (huella `BF5A669F…6397D0D2`, K0) y escribir la suma. En
  ejecución no se lee ningún `.DIGEST`, así que sus tres formatos (H-2) dan
  igual.
- **`install/keepassxc_bin.py`** copia el guion de `veracrypt_bin`:
  - descarga en la caché por versión, con `descarga.con_reintentos()`;
  - comprueba la suma antes de escribir nada;
  - extrae con la misma defensa contra `../` que `update.py`;
  - deja un sello `PRDRIVE-KEEPASSXC` (`keepassxc`, `paquete`, `sha256` y una
    línea `fichero <rel> = <sha256>` por fichero, como el de VeraCrypt);
  - cambia la carpeta con `.nuevo-<pid>` / `.viejo-<pid>` y `os.replace`, tras
    mirar el espacio libre, como `traveler.sustituir()`.
- **Actualizar**: `components.pendientes()` gana una fila. Con un proceso
  corriendo desde `.prdrive/keepassxc/<clave>/` (KeePassXC o el proxy, que es
  del navegador), la actualización **espera**. Lo dice el recuadro ámbar: «Cierra
  KeePassXC y el navegador para poner al día el llavero». `procesos_desde()`
  está hoy en `install/components.py`, que no viaja. Pasa a `common/store.py`
  junto a `procesos_llamados()`, y `install/` lo reexporta.
- **El runtime de Visual C++** (K3): el ZIP no lo trae. «Llavero» lo detecta
  por el resultado: si KeePassXC sale enseguida con `0xC0000135`
  (`STATUS_DLL_NOT_FOUND`), dice qué falta, que hace falta un administrador y
  dónde está el instalador oficial de Microsoft. Llevar las DLL junto al `.exe`
  es la decisión 3.
- **Mientras KeePassXC corre, no se actualiza solo**: prdrive escribe
  `GUI/CheckForUpdates=false` y `UpdateCheckMessageShown=true`. Si no, un
  KeePassXC que se pone al día por su cuenta dejaría el sello mintiendo.

## 4. «Abrir llavero»

`runsync.py --llavero`. Las decisiones están en `common/llavero.py` (sin Tk ni
disco: devuelve planes). Lo que toca el equipo son funciones de módulo que los
tests sustituyen (`registro.*`, `procesos_desde`, `lanzar`). En orden:

1. **¿Ya está abierto?** Si hay un KeePassXC corriendo desde el volumen, se trae
   delante (lanzarlo otra vez con la base hace eso, porque `SingleInstance`) y
   ya está. Si hay otro KeePassXC **del equipo** abierto, se avisa: con
   `SingleInstance`, el nuestro le pasaría la base a ese, que tiene otra
   configuración. La persona elige entre cerrarlo o abrir la base con ese.
2. **Traer la última versión**: una pasada de la pareja `llavero` si la última
   tiene más de unos minutos y hay conexión. Lo pinta `working()`, como
   «Sincronizar ahora». Si falla o no hay red, se abre igual y se dice que puede
   no ser la última. Así abrir parte casi siempre de lo más nuevo, y los
   conflictos son raros.
3. **¿Hay dos versiones?** Si quedan copias de conflicto en `llavero/` (§7), se
   ofrece «Combinar ahora» antes de abrir.
4. **Configuración**, que solo se toca con KeePassXC cerrado, porque al salir
   reescribe su `.ini`. Se edita línea a línea: se cambian las claves de esta
   lista y el resto del fichero queda byte a byte.
   - **En cada arranque, porque son de prdrive**:
     - `UseAtomicSaves=true` (H-11: deshace un «Deshabilitar» de la sesión
       anterior).
     - `Browser/UpdateBinaryPath=true`.
     - `GUI/CheckForUpdates=false`.
     - Las rutas de `LastOpenedDatabases`, `LastDatabases`, `LastActiveDatabase`
       y `LastDir` que empiezan por la raíz anterior pasan a la actual. La
       anterior se apunta en `config/windows/raiz.txt`. Así otra letra no deja
       bases «no encontradas».
   - **Solo al crear la configuración, y luego manda la persona**:
     - `Browser/Enabled=true`.
     - `Security/QuickUnlock=false` (H-1). Encenderlo ata el desbloqueo rápido
       a Windows Hello de cada equipo, y en uno prestado pide el PIN del dueño.
     - `BackupBeforeSave=false`, que ya es el valor por defecto; con él no salen
       los `.old.kdbx`.
     - `GUI/MinimizeOnClose=false`, también por defecto: cerrar cierra, y eso
       necesita «Expulsar».
5. **El navegador** (§5): se escriben las claves del registro.
6. **Lanzar**:
   ```
   KeePassXC.exe --config …\config\windows\keepassxc.ini
                 --localconfig …\config\windows\keepassxc_local.ini
                 <raíz>\llavero\<cada base>.kdbx
   ```
   Lleva `KPXC_INITIAL_DIR=<raíz>\llavero` en el entorno. Si no hay ninguna base,
   va sin rutas: es la bienvenida, y antes sale la pantalla de «la primera vez».
   Las copias de conflicto no se pasan. Si sale con `0xC0000135`, se aplica §3.

## 5. El navegador en el equipo

### Windows

Las claves son cuatro (`NativeMessageInstaller.cpp`, `TARGET_DIR_*`), todas en
`HKCU`, sin administrador. Chrome, Brave y Vivaldi comparten una; Firefox y Tor,
otra (H-5).

| Clave `HKCU\Software\…\NativeMessagingHosts\org.keepassxc.keepassxc_browser` | JSON al que apunta prdrive |
|---|---|
| `Google\Chrome` | `<exe>\config\org.keepassxc.keepassxc_browser_chrome.json` |
| `Microsoft\Edge` | `…_edge.json` |
| `Mozilla` | `…_firefox.json` |
| `Chromium` | `…_chromium.json` |

- **Al abrir**: se escriben las cuatro (valor por defecto = ese JSON), haya lo
  que haya. Basta con eso. En Windows, `isBrowserEnabled()` solo mira que la
  clave tenga valor, y al arrancar `updateBinaryPaths()` reescribe los JSON y
  las claves de todo lo «habilitado» con la ruta de verdad. Es el camino de B3,
  provocado a propósito en un equipo nuevo. Hay que escribirlas aunque
  apunten a otro sitio: KeePassXC se las quedaría igual (B5, «el último que
  arranca se queda con la clave»).
- **Al cerrar** (§8), para cada clave que apunte dentro de este volumen o a un
  `…\.prdrive\keepassxc\…` que ya no existe:
  - si existe `%LOCALAPPDATA%\KeePassXC\org.keepassxc.keepassxc_browser_<n>.json`
    (el JSON de un KeePassXC **instalado**, `getNativeMessagePath()` sin
    portátil), la clave vuelve a apuntar ahí: el instalado sigue funcionando sin
    volver a marcar nada;
  - si no, se borran la clave y su valor (H-18). `NativeMessagingHosts` se borra
    solo si queda vacía.

  Las claves de otros programas (`com.microsoft.browsercore`…) no se tocan nunca.
  La regla no necesita recordar el estado de antes: lo deduce, como el cierre de
  Linux del vestíbulo.
- **Lo que prdrive no hace por la persona**: instalar la extensión, conectarla y
  activar «Enable Passkeys». Son ajustes de cada perfil del navegador. La guía
  los cuenta con capturas.
- Se escribe con `winreg`, que hoy no se usa en ningún sitio. Lo envuelve
  `common/registro.py` (`leer`, `escribir`, `borrar`), punto de sustitución de
  los tests. Encima va el plan puro de `llavero.py`: qué escribir, qué
  restaurar, qué borrar.

### Linux (fase 2, §9)

`isBrowserEnabled()` es «existe el JSON en `~/.config/<navegador>/NativeMessagingHosts/`»
(o `~/.mozilla/native-messaging-hosts/`). prdrive escribe esos ficheros al
abrir y quita al cerrar los que apunten al volumen. Es la misma regla con
ficheros.

## 6. La pareja `llavero`

En el catálogo y en `sync_config.toml`:

```toml
[[pair]]
name = "llavero"
tipo = "llavero"
local = "llavero"
remote_path = "llavero"
mode = "bisync"
versions = true

[pair.flags]
conflict-loser = "num"     # §7: el perdedor se queda al lado, a la vista
resync-mode = "newer"      # H-13: un --resync no pisa la base nueva con la vieja
```

- **`tipo = "llavero"`** es la única clave nueva del modelo
  (`Pair.llavero: bool`). Hace tres cosas que no se pueden dejar a mano:
  1. **Los filtros, generados por código.** Es el mismo razonamiento que
     `- .prversions/**`: una condición previa, no un filtro (`conflicts-versions.md`).
     Viajan **solo** las bases y su compañero:
     ```
     - .prversions/**
     - *.old.kdbx
     + *.kdbx
     + LEEME-LLAVERO.txt
     - **
     ```
     Así no viajan los temporales de `QSaveFile` (`<base>.kdbx.XXXXXX`, que no
     acaban en `.kdbx`: H-11 a), ni el `.passkey`, ni un CSV/HTML/XML exportado
     en claro, ni un fichero llave. Es una lista de lo que entra, no de lo que
     sale: una exportación nueva de KeePassXC tampoco viajaría. El orden importa:
     `filters_content()` hoy pone los `+` antes que los `-`, así que esta pareja
     necesita el suyo. Cambiarlo en otra versión obliga a un `--resync` (suma
     md5); con `resync-mode = "newer"` no se pierde nada.
  2. **Antes de cada pasada, la base tiene que estar entera** (`common/kdbx.py`,
     sin clave):
     - firmas `0x9AA2D903`/`0xB54BFB67` y versión;
     - cabecera TLV hasta `EndOfHeader`;
     - el **SHA-256 de la cabecera** que guarda KDBX 4 (comprobable sin clave);
     - la cadena de bloques HMAC (32 + 4 + datos) acaba **justo al final del
       fichero con un bloque de tamaño 0**.

     Así se pilla una base cortada: un guardado no atómico a medias, o un tirón
     de la unidad en mal momento. En KDBX 3.1 solo se puede comprobar la
     cabecera. Si una base no está entera, se espera dos segundos y se mira otra
     vez (puede estar guardándose); si sigue igual, **la pareja no corre** y lo
     dice: «"x.kdbx" no está entera: no se sube. Ábrela en KeePassXC…». Un
     formato desconocido no bloquea. Es la segunda red: la primera es que rclone
     ya falla un fichero que cambia mientras lo sube («source file is being
     updated»).
  3. **Lo que sale en la ventana**: el botón «Llavero», «Combinar» en los
     conflictos (§7) y, en «Reparación», las exportaciones en claro que haya en
     `llavero/` (`*.passkey`, `*.csv`, `*.html`, `*.xml`). No viajan, pero están
     ahí, descifradas, mientras la unidad esté abierta.
- **El compañero fijo** (H-12): `LEEME-LLAVERO.txt` lo escribe el instalador y
  no cambia. Así un cambio solo en la base nunca es «todos los ficheros han
  cambiado». Si se borra, «Reparación» lo dice y lo repone.
- **Pasadas con KeePassXC abierto: sí** (decisión 2). Lo que se vio en S2(b),
  que KeePassXC no puede guardar mientras rclone lee, solo pasa si se guarda
  justo mientras se **sube** la versión anterior. No se pierde nada: el cambio
  se queda en «\*» y entra en el siguiente guardado. El peligro era contestar
  «Deshabilitar» al tercer fallo. Contra eso: la guía dice «Cancelar», el
  siguiente «Llavero» lo vuelve a encender, y quedan las dos redes de arriba.
  Además, la pasada de «Abrir» y la de «Expulsar» van con KeePassXC cerrado.
- **El aviso de `sync.py`:98** («Fichero bloqueado por otro proceso (Obsidian,
  KeePass, antivirus)») tiene, para esta pareja, una versión concreta: «KeePassXC
  estaba guardando; se reintenta en la próxima pasada».

## 7. Conflictos: combinar, no elegir

Con `conflict-loser = "num"` (un `[pair.flags]` manda sobre el `setdefault` de
`sync.py`:380), el perdedor **se queda al lado** como
`<base>.conflicto-remoto1.kdbx`. `suffix-keep-extension` va con `versions`.
Pasa a `conflicts.json` y a la ventana como cualquier conflicto, y sigue
acabando en `.kdbx`, así que se abre y viaja.

- **«Combinar»**, la primera opción para un `.kdbx` en `ui/tk_conflicts.py`, es
  un `EditPlan` más de `conflict_editor`:
  - consecuencias: «Se juntan las dos versiones en "x.kdbx". Lo de las dos se
    queda; si una misma entrada cambió en las dos, gana la más nueva y la otra
    queda en su historial»;
  - `execute()` abre una consola con
    `keepassxc-cli merge --same-credentials <base> <copia>`, y la contraseña la
    pide la propia CLI;
  - con código 0 mueve la copia a `llavero/.prversions/`. No la borra: queda
    recuperable y la siguiente pasada la quita del otro lado;
  - si falla (contraseña mal, credenciales distintas, fichero llave), no se toca
    nada y se dice cómo hacerlo en la ventana de KeePassXC («Base de datos →
    Combinar desde base de datos…»), que es lo que se vio en S4.

  Las opciones de siempre («quedarse con…») siguen, detrás y con el aviso de que
  pierden las entradas de la otra versión.
- **El momento** es «Llavero» (§4, paso 3): combinar antes de abrir evita que la
  ventana de KeePassXC tenga la base abierta mientras la CLI la reescribe.
  Aunque la tuviera, lo arregla la recarga automática (S3), o S5 si había
  cambios sin guardar.
- **Lo que no se hace**: combinar en silencio. Haría falta la contraseña, y la
  idea es que nunca pase por prdrive.

## 8. Expulsar

El mismo paso previo, `llavero.cerrar()`, en los tres caminos: la ventana
(antes de `cifrado.lanzar_expulsion`, `ui/tk.py`:1183), `Expulsar PRDRIVE.bat`
(antes de `/dismount`, `install/vestibulo.py`:422-426, llamando a
`runsync.py --cerrar-llavero` con el Python del dispositivo, que acaba antes de
desmontar) y, en la fase 3, el agente.

1. **KeePassXC corriendo desde el volumen** → «KeePassXC está abierto.
   ¿Cerrarlo?». «Cerrar» le pide que se cierre como lo haría la persona
   (`taskkill /PID` sin `/F`, que manda `WM_CLOSE`), así que si queda algo sin
   guardar, KeePassXC lo pregunta. Se espera a que salga. Nunca `/F`: S2 enseñó
   que puede haber un «\*» pendiente.
2. **`keepassxc-proxy.exe` desde el volumen** → se termina. Es un relevo sin
   estado entre el navegador y KeePassXC, y es justo lo que obligaba a cerrar el
   navegador (K6, H-16). La extensión se queda «no disponible», como sin
   KeePassXC. **Por ver**: si al volver a abrir el llavero reconecta sola (H-17,
   §13).
3. **La última pasada del llavero**, si la base cambió después de la última. Si
   no hay red: «Los cambios del llavero se subirán la próxima vez que se abra».
   No bloquea.
4. **El registro** (§5, «al cerrar»).
5. Lo de siempre: VeraCrypt, `:libre`, «ya puedes quitar la unidad».

**Sin expulsar** (un tirón): KeePassXC muere y la base sobrevive por el guardado
atómico (K7, H-4). Quedan las claves apuntando a una letra muerta. No hacen
daño: el navegador dice que no encuentra el programa. El siguiente «Llavero» en
ese equipo las reescribe, y en la fase 3 el agente las quita al ver irse la
unidad. Los rastros del propio Windows (`MuiCache`…) no son de prdrive y la guía
lo dice.

## 9. Linux (fase 2, cuando LX1–LX7 y LA1–LA3 digan)

Lo que se sabe hoy es deducido. Lo que hay que decidir con esas pruebas:

- **El programa**: el AppImage x86_64 fijado en `.prdrive/keepassxc/linux-x64/`.
  - Sin FUSE 2 (LX2), o con el volumen `noexec`: se extrae **una vez por
    equipo** en `~/.cache/prdrive/keepassxc/<versión>/`, porque el exFAT del
    volumen no admite los enlaces simbólicos de la imagen, y se lanza `AppRun`
    desde ahí. No hay secretos, como el runtime del agente. Ya hay un precedente
    de copiar fuera del volumen lo que no se puede ejecutar dentro:
    `model.ejecutable()`.
  - La configuración, `--config`/`--localconfig` a `config/linux/` en el volumen
    (LX3).
- **El proxy**: el navegador lanza el `"path"` del JSON sin el entorno de
  prdrive, así que se usa `Browser/UseCustomProxy` + `CustomProxyLocation`,
  reescrito en cada arranque, hacia un `keepassxc-proxy.sh` que sepa lanzar el
  AppImage o la copia extraída.
- **Firefox snap** (LX5): sin probar. Si no hay mensajería nativa, la guía dice
  qué Firefox usar.
- **Linux ARM: el programa del equipo.** No hay AppImage aarch64, y V1/V2 dicen
  que la base vale con cualquier KeePassXC ≥ 2.7.7. «Llavero» busca el Flatpak
  (2.7.12 en Flathub, LA1–LA2) o un `keepassxc` del sistema con versión
  suficiente y abre la base con él. Debian 12 (2.7.4) y Ubuntu 24.04 (2.7.6)
  abren la base, pero sin passkeys: se dice.

## 10. Lo que la guía le cuenta a la persona

`docs/guia/llavero.md`, más una línea en `device-readme.md`. Va sin tecnicismos:

- **Dos cerraduras**: la de la unidad y la de la base. Mejor dos contraseñas
  distintas. La copia del remoto solo tiene la segunda: que sea buena.
- **Equipos prestados**: un equipo con algo malo instalado ve lo que se teclea y
  lo que hay en la unidad abierta. Las passkeys no protegen de eso. Úsalo en
  equipos de confianza.
- **Qué queda en el equipo** mientras la unidad está abierta, que prdrive quita
  al expulsar, y qué pasa si se quita sin expulsar.
- **Exportar** (passkey, CSV…) deja el contenido sin cifrar. No viaja nunca,
  pero bórralo al acabar. «Reparación» lo recuerda.
- **«¿Desactivar almacenajes seguros?» → «Cancelar»** (H-11).
- **Con la base bloqueada**, un sitio que pide passkey se queda esperando:
  desbloquea y **abre otra pestaña** (PK6, H-10). Tras reiniciar KeePassXC, si
  la extensión dice «no disponible», recárgala desde su icono (H-17).
- **«Synced» en GitHub** es normal (PK2).
- **Las versiones viejas de la base** se guardan en `.prversions/`, en los dos
  lados (S7). Combinar dos versiones: §7, con capturas.
- **Desbloqueo rápido con Windows Hello**: qué hace y por qué empieza apagado
  (H-1).

## 11. Lo que no hace

- No autorrellena nada ni habla con el navegador: eso es KeePassXC.
- No crea passkeys ni lee la base.
- macOS y móviles: fuera. La base es un `.kdbx` normal, así que otras
  aplicaciones la abren, pero prdrive no las lleva ni las configura.
- No combina sin preguntar, ni guarda la contraseña de la base en ningún sitio.
- No convierte una unidad sin cifrar en una con llavero (decisión 1).

## 12. Fases

| Fase | Qué | Ficheros |
|---|---|---|
| **1. Windows** (x64 y ARM con el x64) | Componente, «Llavero», registro, pareja con sus filtros y su comprobación, «Combinar», «Expulsar», asistente, guía | `common/pins.py`, `common/kdbx.py` (nuevo), `common/llavero.py` (nuevo), `common/registro.py` (nuevo), `common/store.py` (`procesos_desde`), `common/model.py` (`tipo`), `common/bisync.py` (filtros), `sync.py` (comprobación previa), `common/components.py`, `install/keepassxc_bin.py` (nuevo), `install/components.py`, `install/deploy.py` (lanzadores, `LEEME-LLAVERO.txt`), `install/vestibulo.py` (`.bat`), `install/device.py` (`RUIDO`), `runsync.py` (`--llavero`, `--cerrar-llavero`), `ui/conflict_editor.py`, `ui/tk_conflicts.py`, `ui/tk.py` (botón, expulsar), `ui/tk_llavero.py` (nuevo: primera vez, avisos), `ui/repair.py`/`common/revision.py` (exportaciones, compañero), `ui/tk_install.py` + `ui/tk_crypto.py` (casilla, «Añadir el llavero…») |
| **2. Linux** | Lo de §9, tras LX/LA | `install/keepassxc_bin.py`, `common/llavero.py`, `install/vestibulo.py` (`.sh`) |
| **3. El agente** | «Abrir llavero» en la bandeja; aviso nativo de un conflicto en el llavero (hoy los conflictos no avisan); quitar las claves cuando la unidad se va sin expulsar; el llavero en la raíz del equipo, para un KeePassXC instalado | `agente.py`, `ui/bandeja.py`, `common/avisos.py` |

Cada fase actualiza su documentación de área. La fase 1 crea
`docs/agents/reference/llavero.md` y su regla en `.claude/rules/`, y añade una
fila a la tabla de `AGENTS.md`; `test_reglas_claude.py` vigila que las tres
cuadren.

## 13. Pruebas

**Sin equipo** (scripts de `tests/`, como siempre):

- `test_kdbx.py`: bases sintéticas (las firmas, la cabecera y su SHA-256 se
  construyen con `hashlib`, sin criptografía de KeePassXC): entera, cortada en
  cada sitio, con firma mala, KDBX 3.1 y formato desconocido.
- `test_llavero.py`:
  - el plan del registro con un `registro` falso: equipo nuevo, letra cambiada,
    KeePassXC instalado (restaurar), claves de otros programas intactas;
  - la edición del `.ini` (byte a byte fuera de las claves de la lista) y las
    rutas de otra raíz;
  - los filtros y su orden;
  - «Combinar» con una CLI falsa (0, error, copia que cambió);
  - `cerrar()` con procesos falsos (KeePassXC, proxy, ninguno).
- `test_keepassxc_bin.py`: `fetch` falso, suma mala, `../` en el ZIP, sello,
  cambio de carpeta y espera por procesos. También la deriva entre pins y sello
  (`test_components`).
- Los lanzadores nuevos en los tests del vestíbulo y de `deploy` (CRLF, `RUIDO`,
  `TODOS`).

**En real**: un plan nuevo con lo que el primero no pudo decir, más lo que esta
especificación supone:

| Código | Qué falta ver |
|---|---|
| R1 | K3 en un Windows x64 limpio: ¿`0xC0000135`, y el mensaje? |
| R2 | `--config`/`--localconfig` con `.portable`: la configuración en `config/windows/`, los JSON en `<exe>/config/` |
| R3 | B2 con las claves de prdrive: un equipo nuevo conecta sin marcar nada (Chrome, Edge, Firefox) |
| R4 | Terminar el proxy al expulsar: ¿la extensión reconecta al volver a abrir? (H-17) |
| R5 | WI de verdad: el KeePassXC instalado sigue funcionando tras expulsar (restaurar la clave) |
| R6 | «Combinar» desde prdrive, con la ventana de KeePassXC cerrada y abierta |
| R7 | PK3 a mano: «Enable Passkeys» en Firefox |
| R8 | PK6 otra vez: ¿por qué no sale el diálogo de desbloqueo con `Browser/UnlockDatabase=true`? |
| R9 | V2 en GitHub (0→1), con una cuenta de usar y tirar |
| R10 | S2 con los filtros nuevos, y la comprobación de base entera contra un guardado no atómico («Deshabilitar») |
| R11 | Actualizar KeePassXC con el proxy vivo: espera y lo dice |
| R12 | Edge: B1, PK1 y R3 (en WA no había) |

## Preguntas abiertas (con lo que se recomienda)

1. **¿Solo en dispositivos cifrados?** Se recomienda **sí** en la v1. La base va
   cifrada igual, pero la promesa de «dos cerraduras» y las exportaciones en
   claro dentro de `llavero/` solo se sostienen con VeraCrypt debajo. La raíz
   cifrada del equipo, en la fase 3.
2. **¿Sincronizar el llavero con KeePassXC abierto?** Se recomienda **sí**, con
   las tres redes del §6 y las pasadas de «Abrir» y «Expulsar» en frío. La
   alternativa que dejaban los resultados, «solo con KeePassXC cerrado», es más
   segura contra S2(b), pero los cambios de un dispositivo no llegarían al otro
   mientras la persona lo tenga abierto todo el día.
3. **¿El runtime de Visual C++?** Se recomienda **detectarlo y explicarlo** (§3).
   Llevar las DLL junto a KeePassXC lo arreglaría sin administrador, pero antes
   habría que mirar la licencia de redistribución de Microsoft, y hoy no hay
   evidencia de cuántos equipos lo necesitan (R1).
4. **¿Linux en la fase 1?** Se recomienda **no**: nada de §9 se ha visto, y las
   pruebas fueron en Windows. Mejor una fase 1 entera en Windows que dos a medias.
5. **«Una sola contraseña»** (un fichero llave dentro del volumen en vez de
   contraseña maestra: abrir la unidad bastaría para abrir la base) es lo más
   rápido para entrar en GitHub. Pero quita la segunda cerradura en el equipo y
   obliga a llevar el fichero llave a cada dispositivo **sin** el remoto. Se
   recomienda dejarlo para después, como opción explícita.
6. **El nombre**: «Llavero» en la ventana y en la carpeta, con «(KeePassXC)» la
   primera vez que sale. Para la passkey, la guía dice «passkey (llave de
   acceso)». No «Cerrojo», que es la traducción de KeePassXC (H-9) y confunde.
