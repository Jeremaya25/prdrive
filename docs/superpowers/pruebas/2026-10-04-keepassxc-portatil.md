# Plan: KeePassXC portátil en un volumen de prdrive, para passkeys

Fecha: 2026-10-04 · Rama: `claude/gallant-lamport-95o1u2` · Estado: **hecho en
parte** (solo en WA, el 2026-10-04; sin Linux ni un W x64 de verdad): ver los
resultados. Discrepancias con lo deducido abajo: el punto 3 (B2, H-6), B4
(H-18), S2, S4 y PK6.
Los resultados van en un fichero aparte, al lado de este
(`2026-10-04-keepassxc-portatil-resultados.md`), como los de la unidad G:.

Es la **fase 0** de una idea: llevar las claves privadas de las passkeys dentro
del volumen cifrado de prdrive, en una base de datos de KeePassXC, y entrar con
ellas en sitios como GitHub desde cualquier equipo donde se abra la unidad.
prdrive **no tiene todavía ni una línea de código para esto**: todo se hace a
mano, y lo que salga decide si merece una fase 1 (KeePassXC como componente, con
su lanzador, como el VeraCrypt de viaje de `install/traveler.py`) y qué tendría
que resolver.

«Lo esperado» sale del código de KeePassXC **2.7.12** (etiqueta `2.7.12`; los
ficheros se citan abajo) y de lo que ya se sabe de prdrive. Si en el equipo se
ve otra cosa, se apunta la discrepancia y no se reinterpreta.

## Qué se dedujo del código de KeePassXC y no se ha visto

1. **Modo portátil = un fichero `.portable` escribible junto al ejecutable.**
   Entonces la configuración va a `<carpeta del exe>/config/keepassxc.ini` y
   `keepassxc_local.ini` (`src/core/Config.cpp`: `isPortable()`,
   `portableConfigDir()`). Solo tiene sentido con el ZIP de Windows: en el
   AppImage la carpeta del ejecutable está dentro de su montaje de solo lectura.
   En Linux la configuración se lleva a otro sitio con las variables
   `KPXC_CONFIG` y `KPXC_CONFIG_LOCAL` (`Config::defaultConfigFiles()`).
2. **Navegador en Windows, portátil**: escribe el manifiesto de mensajería
   nativa en `<exe>/config/org.keepassxc.keepassxc_browser_<navegador>.json`
   (en la unidad) y una clave del registro del **equipo**,
   `HKCU\Software\<Google\Chrome|Microsoft\Edge|Mozilla|…>\NativeMessagingHosts\org.keepassxc.keepassxc_browser`,
   que apunta a ese JSON. El JSON lleva `"path"` = `<carpeta del exe>\keepassxc-proxy.exe`,
   con la letra de la unidad (`src/browser/NativeMessageInstaller.cpp`:
   `getNativeMessagePath()`, `getInstalledProxyPath()`).
3. **Al arrancar, reescribe esos manifiestos** si la integración con el
   navegador está activa y `Browser/UpdateBinaryPath` (activo por defecto), para
   cada navegador cuyo JSON **ya existe** (`BrowserService::setEnabled()` →
   `NativeMessageInstaller::updateBinaryPaths()`). Consecuencias:
   - Windows portátil: los JSON viven en la unidad, así que en un equipo nuevo o
     con otra letra, abrir KeePassXC debería escribir el registro **sin ningún
     clic**.
   - Linux: los JSON viven en el equipo (`~/.config/google-chrome/NativeMessagingHosts/`,
     `~/.mozilla/native-messaging-hosts/`…), así que en un equipo nuevo hay que
     activar cada navegador a mano. Con AppImage, `"path"` = `$APPIMAGE`: el
     fichero AppImage dentro del volumen.
   - Desactivar un navegador en los ajustes borra su clave del registro o su JSON.
4. **Passkeys**: desde la 2.7.7 (`CHANGELOG.md`), solo a través de la extensión
   KeePassXC-Browser con la base conectada y «Enable Passkeys» activado en la
   extensión (`docs/topics/Passkeys.adoc`). UV y UP siempre a 1, contador de
   firmas siempre 0 (`src/browser/BrowserPasskeys.cpp`). La exportación
   (`.passkey`, JSON) va **sin cifrar**.
5. **La trampa de las versiones: los indicadores BE/BS.** La 2.7.12 pone
   BE = BS = 1 al crear una passkey, los guarda en la entrada
   (`KPEX_PASSKEY_FLAG_BE`/`_BS`, `BrowserService.cpp`) y, si la entrada no los
   tiene, también usa 1. Su `CHANGELOG.md` avisa: «MAY BREAK EXISTING PASSKEYS».
   Se deduce que las anteriores mandaban 0. WebAuthn nivel 3 pide al sitio que
   compruebe que BE no cambia en una credencial, así que **una passkey creada con
   una versión y usada con otra del otro lado de la 2.7.12 puede ser rechazada**
   por un sitio estricto.
6. **Guardado**: atómico por defecto (`QSaveFile`: temporal al lado y
   renombrado), guardado tras cada cambio y recarga automática si el fichero
   cambia en disco (los tres activos por defecto, `Config.cpp`). Antes de guardar
   compara el primer bloque del fichero con el que leyó: si alguien lo cambió
   (una sincronización, por ejemplo), **se niega** («Database file has unmerged
   changes») y ofrece combinar (`Database::saveAs()`). La copia previa al
   guardado (`{DB_FILENAME}.old.kdbx`) está desactivada por defecto. Bloqueo por
   inactividad a los 900 s.

Versiones de KeePassXC en los paquetes de cada sistema (consultado el
2026-10-04), que deciden qué se puede usar donde no hay portátil oficial:

| Origen | Versión | ¿Passkeys? | ¿BE = 1 (2.7.12+)? |
|---|---|---|---|
| Debian 12 | 2.7.4 | no | — |
| Debian 13 / Ubuntu 26.04 | 2.7.10 | sí | no |
| Ubuntu 24.04 | 2.7.6 | no | — |
| Flathub (x86_64 y **aarch64**) | 2.7.12 | sí | sí |
| Oficial: ZIP Win64, AppImage x86_64 | 2.7.12 | sí | sí |
| Oficial: 2.8.0-beta1, ZIP **ARM64** de Windows | 2.8.0-beta1 | sí | (por ver) |

## Equipos

- **W**: Windows 11 x64 **sin** KeePassXC instalado y, si se puede (una máquina
  virtual limpia), sin el redistribuible de Visual C++. Chrome, Edge y Firefox.
- **W2**: otro Windows x64 donde la unidad reciba **otra letra**. Si no hay
  otro equipo: en W, ocupar antes la letra con `subst X: C:\Temp` y abrir.
- **WI**: un Windows x64 con KeePassXC **instalado** (MSI) y su integración con
  el navegador activada.
- **WA**: Windows 11 ARM64, con Edge (nativo ARM64) y Firefox ARM64.
- **L**: Ubuntu 24.04 (su Firefox es un **snap**; además, Chrome `.deb`) y
  Fedora reciente (Firefox en RPM).
- **L13**: Debian 13 o Ubuntu 26.04 con el paquete 2.7.10.
- **LA**: Linux ARM64 (Raspberry Pi OS de 64 bits o Ubuntu ARM) con Flatpak.
- **Unidad**: un dispositivo prdrive **con VeraCrypt** (exFAT dentro), con su
  remoto funcionando. Para la sección 7, un segundo dispositivo con el mismo
  remoto.
- **Cuentas**: una cuenta de GitHub **de usar y tirar**, nunca la real (se
  registran y se rompen passkeys a propósito), y <https://webauthn.io>, que deja
  elegir las opciones de registro.

Descargas: el ZIP Win64 y el AppImage 2.7.12, el ZIP Win64 2.7.10 (para la
sección 5) y el ZIP ARM64 2.8.0-beta1. Cada uno se comprueba contra su
`.DIGEST` y su firma `.sig`, a mano, como se hace con VeraCrypt al mover el pin.

Disposición en el volumen para las pruebas. Es una propuesta, no la definitiva:

```
<volumen>/
├── .prdrive/                   lo de siempre; nada de esto va aquí dentro
├── KeePassXC/                  el ZIP de Windows descomprimido, con `.portable`
│   └── config/                 lo crea KeePassXC
├── KeePassXC-linux/
│   ├── KeePassXC-2.7.12-x86_64.AppImage
│   ├── keepassxc.sh            KPXC_CONFIG=…/config/keepassxc.ini KPXC_CONFIG_LOCAL=…/config/keepassxc_local.ini
│   └── config/
└── llavero/
    └── pruebas.kdbx            base de pruebas, nunca la de verdad
```

`llavero/` queda fuera de toda pareja hasta la sección 7.

## 0. Preparación

| Código | Dónde | Qué hacer | Qué se espera | Por qué / fuente |
|---|---|---|---|---|
| K0 | W | Comprobar `.DIGEST` y `.sig` de las cuatro descargas. Descomprimir el ZIP en `KeePassXC\` del volumen abierto y crear `KeePassXC\.portable` vacío. | Las sumas y las firmas cuadran. | — |
| K0b | W | Antes de abrir KeePassXC: exportar `HKCU\Software` (`reg export HKCU\Software antes.reg`) y listar `%APPDATA%\KeePassXC` y `%LOCALAPPDATA%\KeePassXC` (no deberían existir). | Sirve de referencia para K2 y B4. | huella en el equipo |

## 1. KeePassXC portátil en Windows

| Código | Dónde | Qué hacer | Qué se espera | Por qué / fuente |
|---|---|---|---|---|
| K1 | W | Abrir `KeePassXC\KeePassXC.exe` desde el volumen y crear `llavero\pruebas.kdbx` (KDBX 4, lo que proponga). | Arranca sin instalar nada y crea `KeePassXC\config\keepassxc.ini`. | `Config::isPortable()` |
| K2 | W | Cerrar KeePassXC y repetir lo de K0b. | No hay `%APPDATA%\KeePassXC` ni `%LOCALAPPDATA%\KeePassXC`. Apuntar **cualquier** diferencia en `HKCU\Software` (todavía sin navegador). | huella en el equipo |
| K3 | W (limpio) | K1 en un Windows sin el redistribuible de Visual C++. | Arranca. Si falta una DLL, apuntar cuál. | qué lleva el ZIP |
| K4 | W | Copiar la carpeta descomprimida desde Descargas (con la marca de «descargado de Internet») al volumen y abrirla. | Apuntar si sale SmartScreen o el aviso de fichero descargado, y si cambia con el volumen en exFAT frente a NTFS. | Mark-of-the-Web; con una descarga de prdrive no habría marca |
| K5 | W | Con KeePassXC abierto, «Expulsar PRDRIVE». | VeraCrypt pregunta si forzar, porque el `.exe` está abierto. Con «No» no se pierde nada. Cerrar KeePassXC y expulsar: sale bien. Apuntar el texto exacto que ve la persona. | `Expulsar PRDRIVE.bat` (`vestibule.md`) |
| K6 | W | Con la integración del navegador activa (después de B1): cerrar KeePassXC, **dejar el navegador abierto** y expulsar. | Es probable que `keepassxc-proxy.exe` siga vivo como hijo del navegador y retenga el volumen (`tasklist /fi "imagename eq keepassxc-proxy.exe"`). Apuntar si la expulsión se bloquea y qué hace falta cerrar. | el proxy lo lanza el navegador, no KeePassXC |
| K7 | W | Con una copia de la base: abrirla, añadir una entrada (se guarda sola) y **desenchufar sin expulsar**. Volver a enchufar y abrir. | La base abre y la entrada está. Si no, apuntar el error. Es el H-10 de G: con una base de contraseñas dentro. | `AutoSaveAfterEveryChange`, guardado atómico |

## 2. El navegador en Windows

| Código | Dónde | Qué hacer | Qué se espera | Por qué / fuente |
|---|---|---|---|---|
| B1 | W | Ajustes → Integración con navegadores: activar Chrome, Edge y Firefox. Instalar KeePassXC-Browser desde la tienda de cada uno (apuntar la versión), conectar la base y activar «Enable Passkeys». | Tres JSON en `KeePassXC\config\` y tres claves en `HKCU\Software\…\NativeMessagingHosts\org.keepassxc.keepassxc_browser` que apuntan a ellos. El `"path"` de cada JSON lleva la letra del volumen. | `getNativeMessagePath()` en portátil |
| B2 | W2 | Abrir la unidad en W2 (otra letra) **sin** abrir KeePassXC e intentar usar la extensión. Después abrir KeePassXC. | Sin KeePassXC, la extensión no conecta (apuntar el mensaje). Al abrirlo se escriben las claves del registro con la letra nueva **sin tocar ningún ajuste**. Cada navegador de W2 pide su propia conexión una vez: apuntar cuántas asociaciones van quedando guardadas en la base. | `updateBinaryPaths()` al arrancar |
| B3 | W | La misma unidad en W, con la letra de antes ocupada (`subst`). Abrir KeePassXC. | Igual que B2: el registro pasa a la letra nueva al arrancar. | ídem |
| B4 | W | Expulsar, `reg export` otra vez y comparar con `antes.reg`. Después desactivar los tres navegadores en los ajustes (con la unidad abierta) y volver a comparar. | Con la unidad fuera quedan las tres claves apuntando a una ruta que no existe: **es la huella que deja en el equipo**. Desactivar los navegadores las borra. Apuntar qué ve el navegador mientras tanto. | `setBrowserEnabled(false)` |
| B5 | WI | Abrir el portátil en un equipo con KeePassXC instalado y la integración activa. Después abrir el instalado. | Los dos usan el mismo nombre (`org.keepassxc.keepassxc_browser`): el último que arranca se queda con el registro. Apuntar si alguno se queja y si, después del portátil, el instalado vuelve a funcionar solo. | mismo `HOST_NAME` |

## 3. Las passkeys

Todo en W, salvo que se diga otra cosa, con KeePassXC 2.7.12.

| Código | Dónde | Qué hacer | Qué se espera | Por qué / fuente |
|---|---|---|---|---|
| PK1 | W | webauthn.io: registrar con las opciones por defecto y entrar. Repetir con «Discoverable credential: required» y «User verification: required». | KeePassXC pide confirmar en su diálogo y se entra. Se crea una entrada «(passkey)» en «KeePassXC-Browser Passwords». | `Passkeys.adoc` |
| PK2 | W | GitHub (cuenta de pruebas): Ajustes → Password and authentication → añadir una passkey. Cerrar sesión y entrar **solo con la passkey**. | Entra. Apuntar si GitHub muestra algo raro sobre el tipo de autenticador. | — |
| PK3 | W | Entrar con la passkey de PK2 desde otro navegador del mismo equipo (creada en Chrome, usada en Firefox). | Entra: la passkey está en la base, no en el navegador. | — |
| PK4 | W2, L, WA | Entrar en GitHub y en webauthn.io con las passkeys de PK1/PK2, con la unidad en cada equipo. | Entra en todos (con la 2.7.12 en todos; la mezcla de versiones es la sección 5). | — |
| PK5 | W | Exportar una passkey (`.passkey`). | KeePassXC avisa de que va sin cifrar. Apuntar dónde la guarda por defecto. **Borrarla después**: nunca en una carpeta sincronizada. | exportación sin cifrar |
| PK6 | W | Con la base **bloqueada** (o KeePassXC cerrado), entrar en GitHub. | La extensión pide desbloquear, o el navegador ofrece su propio diálogo (móvil, llave USB). Apuntar cuál de los dos y si se puede volver a KeePassXC. | — |

## 4. Linux

| Código | Dónde | Qué hacer | Qué se espera | Por qué / fuente |
|---|---|---|---|---|
| LX1 | L | Abrir la unidad con `abrir-prdrive.sh` por cada vía que haya (VeraCrypt en `/media/veracryptN`, udisks2, cryptsetup en `/mnt/prdrive-<id8>`) y ejecutar el AppImage desde ahí. | Arranca. Apuntar las opciones de montaje (`findmnt`) y si alguna vía monta con `noexec`. | `vestibule.md` |
| LX2 | L | En Ubuntu 24.04 sin `libfuse2`: ejecutar el AppImage. Después con `APPIMAGE_EXTRACT_AND_RUN=1`. | Sin FUSE 2, el AppImage no arranca: apuntar el mensaje. Con la variable, extrae y arranca. Apuntar dónde extrae y cuánto tarda. | runtime del AppImage |
| LX3 | L | Arrancar con `keepassxc.sh` (`KPXC_CONFIG`/`KPXC_CONFIG_LOCAL` hacia `KeePassXC-linux/config/`). Comparar `~/.config/keepassxc` y `~/.cache/keepassxc` antes y después. | La configuración queda en el volumen y esas dos carpetas no aparecen. | `Config::defaultConfigFiles()` |
| LX4 | L | Activar Chrome (`.deb`) y Firefox en los ajustes. Conectar la extensión. | JSON en `~/.config/google-chrome/NativeMessagingHosts/` y `~/.mozilla/native-messaging-hosts/` (**en el equipo**), con `"path"` = el AppImage del volumen. La extensión conecta. | `getNativeMessagePath()` Linux, `$APPIMAGE` |
| LX5 | L | Firefox **snap** de Ubuntu 24.04. | Apuntar si la mensajería nativa funciona y qué pide. Es el navegador por defecto de la distribución más común. | sandbox del snap |
| LX6 | L | Cerrar, abrir la unidad por **otra** vía (otro punto de montaje) y arrancar KeePassXC. | Los JSON del equipo pasan a la ruta nueva al arrancar, porque ya existían. En un Linux donde nunca se activó, hay que activar cada navegador a mano. | `updateBinaryPaths()` |
| LX7 | L | Con la extensión conectada, cerrar KeePassXC y expulsar sin cerrar el navegador. | Como K6: es probable que el proxy (el propio AppImage) mantenga el volumen ocupado. Apuntar qué dice `expulsar-prdrive.sh`. | — |
| LA1 | LA | Instalar KeePassXC 2.7.12 desde Flathub y abrir `llavero/pruebas.kdbx` del volumen. | Apuntar si el sandbox deja abrir la ruta del montaje (diálogo del portal o permiso de sistema de ficheros) y si recuerda la base al volver a abrir. | permisos del Flatpak |
| LA2 | LA | Integración con Chromium o Firefox **no** Flatpak. | El JSON apunta al exportado de Flatpak (`/var/lib/flatpak/exports/bin/org.keepassxc.KeePassXC`). Apuntar si conecta y si las passkeys funcionan. | `constructFlatpakPath()` |
| LA3 | LA, L | El paquete de la distribución (Debian 12: 2.7.4; Ubuntu 24.04: 2.7.6) con un sitio que pide passkey. | No hay passkeys en esas versiones: apuntar qué hace la extensión (¿pasa al diálogo del navegador?). La base se abre igual. | tabla de versiones |

## 5. Versiones mezcladas

Es la sección que decide si basta con que la unidad lleve la base, o si además
tiene que llevar una **única** versión de KeePassXC para todos los sistemas.

| Código | Dónde | Qué hacer | Qué se espera | Por qué / fuente |
|---|---|---|---|---|
| V1 | W, L13 | Crear passkeys con la **2.7.12** en webauthn.io y GitHub; entrar con la **2.7.10** (el paquete de L13 o el ZIP 2.7.10 en W). | La 2.7.10 manda BE = 0 a una credencial registrada con BE = 1. Apuntar, sitio por sitio, si se entra o se rechaza y con qué mensaje. | punto 5 de arriba |
| V2 | W, L13 | Al revés: crear con la 2.7.10 y entrar con la 2.7.12. | La 2.7.12 lee la entrada sin `KPEX_PASSKEY_FLAG_BE` y manda 1. Apuntar igual que V1. | `BrowserService.cpp`, valor por defecto |
| V3 | W, WA | Guardar la base con la 2.8.0-beta1 (añadir una entrada) y abrirla con la 2.7.12 y con la 2.7.10. | Se abre en las dos. Si alguna se niega o avisa del formato, apuntarlo. | formato KDBX |
| V4 | W | Abrir la base con la 2.7.10 tras usarla con la 2.7.12 y añadir una entrada; volver a la 2.7.12. | No se pierden ni las passkeys ni sus atributos `KPEX_PASSKEY_*`. | atributos desconocidos para la versión vieja |

## 6. Windows ARM

| Código | Dónde | Qué hacer | Qué se espera | Por qué / fuente |
|---|---|---|---|---|
| A1 | WA | El ZIP Win64 2.7.12 (x64, **emulado**) desde el volumen: K1, B1 y PK4. | Arranca emulado. Lo que falta saber es si Edge ARM64 lanza el `keepassxc-proxy.exe` x64 por mensajería nativa: apuntar si conecta. | KeePassXC no usa drivers; la emulación debería servir |
| A2 | WA | El ZIP ARM64 2.8.0-beta1 en otra carpeta del volumen (`KeePassXC-arm64\` con su `.portable`): B1 y PK4. | Funciona nativo. Ojo: es **otra carpeta de configuración**. Apuntar qué ajustes hay que repetir. | `portableConfigDir()` es por carpeta |
| A3 | W, WA | Pasar la unidad de W a WA y volver, abriendo en cada uno la carpeta de su arquitectura. | Cada arranque reescribe el registro de ese equipo hacia su proxy. Apuntar si algo se cruza (una asociación de navegador perdida, un ajuste que no viaja). | — |

## 7. La base sincronizada con prdrive

Con la base de pruebas, nunca con la de verdad. Pareja nueva `llavero`
(`local = "llavero"`), primero en modo `up` y después en `bisync` con
`versions = true`.

| Código | Dónde | Qué hacer | Qué se espera | Por qué / fuente |
|---|---|---|---|---|
| S1 | W | Pareja `up`: `python sync.py --dry-run llavero` y luego sin `--dry-run`. | Sube solo `pruebas.kdbx`: ningún temporal del guardado atómico. | `QSaveFile` renombra al acabar |
| S2 | W | Lanzar la pasada mientras se crean entradas seguidas en KeePassXC. Descargar después la copia del remoto y abrirla. | La copia del remoto abre (es una versión entera, vieja o nueva, nunca media). Si no abre, apuntar el tamaño y el log de rclone. | guardado atómico frente a la lectura de rclone |
| S3 | W, W2 | Pareja `bisync` en los dos dispositivos. Cambiar en A, sincronizar A, sincronizar B **con KeePassXC abierto en B**. | KeePassXC de B recarga la base solo y se ve el cambio. | `AutoReloadOnChange` |
| S4 | W, W2 | Cambiar en A y en B sin sincronizar en medio; sincronizar los dos. | bisync deja un conflicto: una copia con el sufijo de su lado. Abrir las dos en KeePassXC → «Combinar bases de datos»: no se pierde nada. Apuntar cuántos pasos son para la persona. | `conflict-resolve`, `conflicts-versions.md` |
| S5 | W2 | Con un cambio sin guardar en B (desactivar «guardar tras cada cambio» para la prueba), dejar que bisync traiga la versión de A y guardar en B. | KeePassXC **se niega** a sobrescribir («Database file has unmerged changes») y ofrece combinar. | `Database::saveAs()` |
| S6 | W | Activar «copia antes de guardar» y exportar un `.passkey` dentro de `llavero/`; pasada `--dry-run`. | Apuntar qué subiría (`pruebas.old.kdbx`, el `.passkey` **sin cifrar**). Decide los filtros que pondría la fase 1. | `BackupFilePathPattern`, exportación sin cifrar |
| S7 | W | `.prversions/` tras varias pasadas con cambios. | Las versiones viejas de la base se guardan y abren: son copias de seguridad que KeePassXC no hace por defecto. | `versions = true` |

## Lo que este plan no cubre

- La comparación de seguridad con una llave física o con Windows Hello: con el
  volumen abierto, cualquier programa de la sesión puede copiar el `.kdbx` (que
  sigue cifrado con su propia contraseña). Eso es diseño, no prueba.
- macOS y los móviles (abrir el `.kdbx` con otra aplicación).
- Que prdrive descargue, compruebe y actualice KeePassXC: es la fase 1, y
  depende de lo que salga aquí.

## Qué hacer con lo que salga

- **V1 o V2 rechazados en algún sitio**: la unidad tiene que llevar **una sola
  versión** para todos los sistemas, ≥ 2.7.12. En Linux ARM, eso solo lo da
  Flathub (LA1–LA2) hasta que haya AppImage aarch64; el paquete de la
  distribución quedaría fuera. Si nadie rechaza, basta con que viaje la base y el
  programa puede ser el del equipo.
- **B2/B3 sin ningún clic**: en Windows la fase 1 no necesita al agente para la
  integración con el navegador. **B4** dice qué tiene que contar la guía sobre lo
  que queda en el equipo y cómo se limpia.
- **K5–K6 / LX7 con la expulsión bloqueada**: «Expulsar PRDRIVE» tendría que
  avisar de KeePassXC y de su proxy (o cerrarlos) antes de llamar a VeraCrypt;
  hoy no sabe nada de ellos.
- **A1 sin conexión con el navegador**: en Windows ARM la fase 1 espera a la
  2.8.0 estable y lleva las dos arquitecturas, con A2–A3 como guía.
- **S2 con una copia rota en el remoto**: la pareja no puede sincronizar la base
  tal cual; se replantea (copia en frío desde el lanzador, o solo con KeePassXC
  cerrado).
- **S6**: los filtros mínimos que la fase 1 pondría en la pareja del llavero
  (`*.passkey` como mínimo) se deciden con lo que se vea.
