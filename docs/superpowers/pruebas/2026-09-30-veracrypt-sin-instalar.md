# Plan: VeraCrypt sin instalar, en equipos reales

Fecha: 2026-09-30 · Rama: `claude/dreamy-noether-9pyptj` · Estado: **por hacer**.
Los resultados van en un fichero aparte, al lado de este
(`2026-09-30-veracrypt-sin-instalar-resultados.md`), como los de la unidad G:.

Recoge en un solo sitio todo lo que el «zero install» con VeraCrypt promete y
nadie ha visto funcionar todavía:

- lo de #50 (el Portable en las unidades), que nunca se probó **sin** VeraCrypt
  instalado: en la campaña de G: y en la de la fase 3 había un driver de VeraCrypt
  ya cargado, así que no hubo UAC;
- lo de #51 (abrir en Linux con udisks2 o cryptsetup), sin probar en ninguna
  distribución;
- y lo nuevo de esta rama:
  - VeraCrypt fijado en la 1.26.29;
  - el agente con su Portable para la raíz cifrada del equipo;
  - el AppImage oficial en Linux;
  - `--quick` en Linux.

Los tests de `tests/` sustituyen VeraCrypt, udisks, cryptsetup, la red y los
procesos. «Lo esperado» sale del código; si en el equipo se ve otra cosa, se
apunta la discrepancia y no se reinterpreta.

## Equipos

- **W**: Windows 11 x64 **sin VeraCrypt instalado y sin su driver cargado**.
  Antes de empezar, comprobar que no hay ningún servicio `veracrypt`
  (`sc query veracrypt` → «no existe») y reiniciar si lo hubo. Usuario
  administrador con UAC (el caso normal): cada elevación es un aviso que acepta
  la persona.
- **W+**: el mismo equipo con VeraCrypt **1.26.x** instalado desde el MSI
  oficial, y otro con una **1.25.x** (para `ERR_DRIVER_VERSION`).
- **WA**: Windows 11 ARM64 sin VeraCrypt.
- **WS**: Windows con una cuenta **estándar** (sin administrador).
- **L**:
  - Ubuntu 24.04 (GNOME) y Fedora reciente (GNOME y KDE), sin VeraCrypt;
  - Debian 12;
  - un Linux ARM64 (Raspberry Pi OS de 64 bits o similar) para el AppImage de
    aarch64;
  - un servidor sin escritorio por SSH para U1–U10.

Unidad de pruebas: un USB de 16 GB o más, **vacío** (se reformatea).

## 1. El Portable en las unidades (#50, V1–V7)

La versión fijada es ahora la 1.26.29. Una unidad hecha con la 1.26.24 sirve
para V5 y para K1.

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| V1 | W | Asistente, unidad nueva, VeraCrypt: «Descargar VeraCrypt Portable», crear 2 GiB en exFAT y montar. | Descarga de ~39 MB con «SHA-256 correcto» y «Paquete íntegro: 14 ficheros». Un UAC al crear y otro al montar. El contenedor queda **con** sistema de ficheros (el H-4 de G:, arreglado) y el asistente sigue. | `veracrypt_bin.download_veracrypt()`, `crypto.create_container()` / `_esperar_copia_elevada()` |
| V2 | WA | Abrir la unidad de V1 con «Abrir PRDRIVE.bat». | Elige `VeraCrypt-arm64.exe`, UAC y contraseña, monta; «Expulsar PRDRIVE» la cierra y Windows deja quitarla. | `Abrir PRDRIVE.bat` (`%PROCESSOR_ARCHITECTURE%`) |
| V3 | W | Una unidad hecha en WA, abierta en W. | Igual que V2, al revés. | ídem |
| V4 | W+ (1.26.x) | «Abrir PRDRIVE.bat» y el asistente, con VeraCrypt 1.26.x instalado. | Usan el **instalado**, sin UAC, y no sale `ERR_DRIVER_VERSION`. | `find_veracrypt()`, el `.bat` |
| V4b | W+ (1.25.x) | Lo mismo con una 1.25.x instalada **y su driver cargado**, y además forzar el que viaja (renombrar el instalado un momento). | El instalado funciona. El que viaja da `ERR_DRIVER_VERSION` (`VERSION_NUM` 0x0125 frente a 0x0126). Apuntar el texto exacto que ve la persona. | `DriverAttach()` |
| V5 | W | `--update-components` de una unidad con el Portable 1.26.24: primero con la raíz física casi llena (< 50 MiB libres), después con sitio. | Llena: no toca nada y dice que no cabe. Con sitio: la carpeta `VeraCrypt\` pasa entera a la 1.26.29 (sello nuevo), nunca una mezcla. | `traveler.sustituir()`, `components.veracrypt_pendiente()` |
| V6 | W | Estropear el paquete de la caché (un byte), y cortar la red a mitad de descarga. | Byte cambiado: «no es el paquete de VeraCrypt fijado», la caché queda como estaba. Corte: reintenta tres veces y dice la URL y el SHA-256 para bajarlo a mano. | `veracrypt_bin._guardar()`, `descarga.con_reintentos()` |
| V7 | W | Durante V1, con el Administrador de tareas abierto. | Se ven dos `VeraCrypt Format-x64.exe` (el lanzado sale a los ~2 s; el elevado sigue) y el asistente espera al segundo. | `crypto._procesos()` → `store.procesos_llamados()` |
| V8 | WS | V1 con una cuenta estándar. | El UAC pide credenciales de administrador. Sin ellas no se crea nada y el mensaje lo dice (`FALLOS_MONTAJE`, «administrator privileges»), sin inventarse otra causa. | `crypto.explicar_montaje()` |

## 2. La raíz cifrada del equipo con el Portable del agente (nuevo)

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| P1 | W | Asistente «En este equipo → Una carpeta propia», paso «Cifrado», sin VeraCrypt. | «En un contenedor VeraCrypt» desactivado, el texto de `COMO_INSTALAR` y el botón «Descargar VeraCrypt Portable». Al pulsarlo, la opción se enciende y sale el aviso ámbar del UAC (`AVISO_PORTATIL`). | `raiz_equipo.veracrypt_para_raiz()`, `tk_equipo.paso_cifrado()` |
| P2 | W | Crear y montar la raíz (NTFS dentro, letra P: o la libre). | UAC al crear y al montar; el contenedor queda disperso (`fsutil sparse queryflag`), montado en la letra, con `.prdrive-vestibulo` fuera. | `raiz_equipo.abrir_o_crear()` |
| P3 | W | Terminar el asistente («Instalación», «Arranque»). | «Su VeraCrypt (Portable): …\\veracrypt\\1.26.29» en «Instalación»; `instalacion.json` lleva `"veracrypt"`; la carpeta tiene el sello y los ejecutables. | `install/agente.poner_veracrypt()`, `quiere_veracrypt()` |
| P4 | W | Bandeja → «Bloquear». | UAC; VeraCrypt desmonta. Si con un fichero abierto dentro pregunta si forzar, el agente **no** dice «sigue abierta» mientras la pregunta está en pantalla. Con «No», lo dice al cerrar la pregunta. | `agente.orden_bloquear()`, `Copia`, `_bloqueos()` |
| P5 | W | Bandeja → «Desbloquear…», y tardar más de 20 s en aceptar el UAC y escribir la contraseña. | No se da por cancelado mientras la copia elevada sigue; la raíz se atiende al verla abierta. Cancelar la contraseña: a los ~20 s vuelve a ofrecer «Desbloquear…». | `Desbloqueo`, `_seguir_desbloqueos()` |
| P6 | W | Cerrar sesión y volver a entrar con `pedir_al_iniciar` activado. | Un UAC y la contraseña, una vez. Apuntar si a la persona le resulta aceptable: es el precio que se prometió decir. | `Agente._al_iniciar()` |
| P7 | W | Tras P2, desbloquear/bloquear dos veces sin reiniciar; después reiniciar y repetir. | Apuntar **cuándo pide UAC y cuándo no**. La documentación dice que, con un NTFS escribible montado, el driver portátil se queda cargado hasta reiniciar: puede que, cargado, abrir y cerrar ya no pidan UAC. | modo portátil de VeraCrypt (sin verificar) |
| P8 | W | Estropear un byte de `VeraCrypt-x64.exe` en la carpeta del agente y pedir «Desbloquear». | No se lanza; el diario dice «no cuadra con su sello» y el aviso, que no hay VeraCrypt. | `agente.veracrypt_propio()`, `components.veracrypt_integro()` |
| P9 | W | Instalar VeraCrypt (MSI) con la raíz ya creada; reiniciar el agente. | Desbloquear usa el **instalado** (sin UAC). Al volver a pasar el asistente o actualizar el agente, la copia del agente se poda. | `veracrypt_de_la_raiz()`, `quiere_veracrypt()`, `podar()` |
| P10 | W | Desinstalar el agente con la raíz abierta y sin VeraCrypt instalado. | El mensaje dice que se cierra sola al reiniciar y que para volver a abrirla hace falta VeraCrypt. Si `veracrypt\` no se deja borrar (driver cargado), dice que queda algo en uso. | `install/agente.desinstalar()` |
| P11 | WA | P1–P5 en ARM64. | El agente lanza `VeraCrypt-arm64.exe` con su driver. | `veracrypt_propio()` (`native_arch()`) |

## 3. Linux con el AppImage oficial (nuevo)

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| AI1 | L (Ubuntu, Fedora) | Asistente, unidad nueva, VeraCrypt, sin VeraCrypt instalado: «Descargar VeraCrypt (AppImage)». | ~13 MB, «SHA-256 correcto», queda en la caché como `veracrypt` ejecutable. | `veracrypt_bin.ensure_appimage()` |
| AI2 | L | Crear 2 GiB en **exFAT** con él. | Pide la contraseña de administrador (sudo) para el loop, dm-crypt y `mkfs.exfat`. Apuntar si hace falta instalar `exfatprogs` y qué dice si falta. | `crypto.create_command()` POSIX |
| AI3 | L | Mirar el `.hc` de AI2 sobre ext4 y sobre exFAT (un USB). | Sobre ext4, disperso (`du` ≪ tamaño) gracias a `--quick`; sobre exFAT, entero (no admite dispersos). Apuntar los tiempos. | `--quick` en 1.26.29 |
| AI4 | L | Sin `fusermount` (desinstalar `fuse3` en una VM) y sin `libfuse2`. | El AppImage arranca igual (extrae y ejecuta). Apuntar qué pasa al **montar**, que sí usa FUSE. | runtime del AppImage |
| AI5 | L | Abrir el contenedor de AI2 en Windows con VeraCrypt, y uno de V1 en Linux con el AppImage. | Se abren; los ficheros escritos en un lado se leen en el otro con las mismas sumas. | formato del volumen |
| AI6 | L (escritorio) | Raíz cifrada del equipo con el AppImage (paso «Cifrado» → «Descargar VeraCrypt (AppImage)», crear, montar en `~/PRDRIVE`). | Se crea y se monta. El agente lleva su copia en `~/.local/share/prdrive/veracrypt/1.26.29/veracrypt`. «Bloquear» y «Desbloquear» abren la ventana **gráfica** del AppImage (contraseña, y la de administrador). | `penwatch.veracrypt_command(…, respaldo=)`, `orden_bloquear()` |
| AI7 | L ARM64 | AI1 + AI2 con el AppImage de aarch64. | Igual. Es el único que no sale en el `sha256sum.txt` de la release: solo lo respalda su firma PGP. | `pins.VERACRYPT_APPIMAGE["linux-arm64"]` |
| AI8 | L | VeraCrypt 1.26.24 instalado desde el paquete de la distribución, y crear. | Usa el instalado; `--quick` se ignora sin error y el contenedor se escribe entero (visto con el AppImage 1.26.24 en un contenedor, no con un paquete). | `find_veracrypt()` (instalado primero) |

## 4. Linux sin VeraCrypt para abrir (#51, U1–U10)

Igual que en #51, con un `PRDRIVE.hc` creado por prdrive **en Windows** (exFAT,
AES, SHA-512, PIM 0) y otro creado en Linux con el AppImage (AI2).

| Código | Qué | Anotar / da por bueno si… |
|---|---|---|
| U1 | ¿Existe `/etc/udisks2/tcrypt.conf` de serie? Versiones de udisks2, libblockdev y cryptsetup | por distribución |
| U2 | Con `tcrypt.conf`: `loop-setup` → ¿`IdType = crypto_unknown`? → `unlock` (¿cuánto tarda?) → `mount` | sin contraseña de administrador; montado con el uid del usuario; se escribe; `runsync.sh` arranca desde ahí |
| U3 | Sin `tcrypt.conf` | falla con «does not appear to be… TCRYPT», y el `.sh` pasa a la siguiente vía |
| U4 | Escritorio sin terminal: tras `loop-setup`, ¿GNOME Shell / Files / Dolphin piden la contraseña, con las opciones de VeraCrypt? | qué ve la persona, con capturas. Decide si penwatch y el agente hacen el `loop-setup` |
| U5 | `sudo cryptsetup open --type tcrypt --veracrypt PRDRIVE.hc …` | loop automático, tiempo de apertura, `mount` exFAT con uid/gid, escritura, `close` libera el loop |
| U6 | Lo mismo con `pkexec` en un escritorio | diálogo gráfico de administrador, sin terminal |
| U7 | Expulsar por cada vía; `losetup -j` sin root | nada queda colgado (`losetup -a`, `dmsetup ls`) |
| U8 | **Desenchufar sin expulsar**, con cada vía | qué queda (dm sobre un loop sin fichero), y cómo lo resuelven «Abrir» y «Expulsar». Es el H-10 de Windows en Linux, y hoy no se trata |
| U9 | **Integridad cruzada**: escribir 1 GB en Linux por cada vía, comprobar sumas en Windows con VeraCrypt, y al revés | las sumas cuadran. **Es la prueba que dice si los datos sobreviven** |
| U10 | VeraCrypt instalado y udisks con `tcrypt.conf` a la vez | el `.sh` usa VeraCrypt; nadie monta dos veces |

## 5. Dispositivos ya en uso: la versión fijada se mueve

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| K1 | W | Enchufar una unidad con el Portable 1.26.24 (con sello) y abrir su ventana con el código nuevo. | El bloque de componentes ofrece poner VeraCrypt al día (1.26.24 → 1.26.29). Aplicarlo cambia la carpeta entera y la unidad sigue abriéndose con «Abrir PRDRIVE.bat». | `components.veracrypt_pendiente()`, `install/components.py` |
| K2 | W | Una unidad de antes de #50 (`VeraCrypt\VeraCrypt.exe` sin sello). | Sale como pendiente con «Añadir plataformas…», sin botón; no se toca. | `components.actualizables()` |
| K3 | W | Un equipo con la raíz cifrada ya abierta con el instalado; actualizar el agente con `--update-agente`. | No se lleva VeraCrypt propio (hay instalado); `instalacion.json` sin `"veracrypt"`. | `quiere_veracrypt()` |

## Lo que este plan no cubre

- Una cuenta sin administrador en Windows **no puede** usar VeraCrypt sin
  instalar (V8 lo confirma, no lo arregla). Allí la única vía sin instalar nada
  es BitLocker To Go (se abre sin administrador; crearlo exige Pro).
- Instalar VeraCrypt desde el asistente (el MSI) está descartado.
