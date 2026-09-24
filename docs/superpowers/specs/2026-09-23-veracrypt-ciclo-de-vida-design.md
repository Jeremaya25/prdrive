# VeraCrypt: del día de la instalación a todos los días

Fecha: 2026-09-23 · Estado: diseño aprobado · Versión: 0.2.5

## El problema

El soporte de VeraCrypt está bien hecho en lo que cubre: crear el contenedor con
`/dynamic` cuando se puede, montarlo con `/m rm`, no dar un montaje por bueno por
el código de retorno, no repetir nunca la contraseña. Pero cubre **un momento**
—la instalación— y un dispositivo cifrado se abre y se cierra **todos los días**.
`runsync`, `penwatch` y la ventana principal no saben que el dispositivo va
cifrado:

- **Abrirlo** es cosa del usuario, en cada equipo: abrir VeraCrypt, elegir el
  fichero, una letra, la contraseña. Nada en la raíz física dice cómo: la guía y
  los lanzadores están *dentro* del contenedor.
- **penwatch no puede ayudar**: identifica el dispositivo por
  `.prdrive/PRDRIVE`, que está dentro del contenedor, así que sin montar no ve
  nada.
- **Cerrarlo** no existe fuera del paso 8 del asistente, y la guía del
  dispositivo dice que para extraerlo «basta con cerrar la ventana».

Y al revisar el código contra el de VeraCrypt salieron fallos que no son de
alcance sino de funcionamiento.

## Lo verificado en el código de VeraCrypt

Todo contra el tag **VeraCrypt_1.26.24**, y lo que importa también contra
`master`. Las citas van en el código, como las de rclone en `common/bisync.py`.

| # | Hecho | Dónde | Consecuencia para prdrive |
|---|---|---|---|
| 1 | El instalador deja el driver en su carpeta como **`veracrypt.sys`**: el nombre de destino es `szFiles[i]+1` (`Averacrypt.sys`); solo el de *origen* dentro del paquete lleva la arquitectura. | `Setup/Setup.c:866`, `Setup/Setup.h` | `traveler.instalar()` copia `veracrypt.sys` tal cual. |
| 2 | En modo portátil `DriverLoad()` busca **`veracrypt-x64.sys` o `veracrypt-arm64.sys`** junto al `.exe`; si no está, `DRIVER_NOT_FOUND`. El propio diálogo de VeraCrypt, en el caso MSI, **renombra** `veracrypt.sys` → `veracrypt-x64.sys`. | `Common/Dlgcode.c:4988`, `Mount/Mount.c` (`TravelerDlgProc`) | **El traveler de prdrive, hecho desde una instalación normal, no puede cargar el driver.** Y `arquitecturas()` lee `veracrypt.sys` como «x86». |
| 3 | `IsARM()` pregunta por la máquina **nativa** (`IsWow64Process2`): un `VeraCrypt.exe` x64 emulado en Windows ARM busca `veracrypt-arm64.sys`. Un driver no se emula nunca. | `Common/Dlgcode.c:11050` | Es falso que «el x64 también vale en Windows ARM». Cada arquitectura solo vale en la suya. |
| 4 | Si hay otra versión de VeraCrypt instalada con su driver cargado, el `.exe` que viaja falla con **`ERR_DRIVER_VERSION`** (en modo portátil intenta descargar el otro driver, y no puede con el de una instalación). | `Common/Dlgcode.c` (`DriverAttach`), `Common/Language.xml` (`DRIVER_VERSION`) | Quien abre el contenedor tiene que **preferir el VeraCrypt instalado** y usar el que viaja solo si no hay otro. |
| 5 | `VolumeGuidPathToDevicePath()` solo acepta rutas que **terminan en `}\`** (un volumen entero). Con un fichero detrás devuelve vacío, y el temporizador del montaje al conectar hace `continue`. | `Common/Dlgcode.c:13539`, `Mount/Mount.c:7781` (igual en `master`) | **El favorito que escribe prdrive (`\\?\Volume{GUID}\PRDRIVE.hc`) no se monta nunca al conectar.** |
| 6 | El arranque con Windows (`HKCU\…\Run\VeraCrypt`) lo escribe `ManageStartupSeq()`, y solo se llama desde el diálogo de Preferencias y desde el de Favoritos. Poner `StartOnLogon=1` en `Configuration.xml` no registra nada. | `Common/Dlgcode.c:10087`, `Mount/Mount.c:3638`, `Mount/Favorites.cpp:322` | `set_config_flag("StartOnLogon")` no hace lo que dice el mensaje. |
| 7 | `write_favorite()` construye el XML **desde cero**. | `install/crypto.py` (reproducido) | Borra todos los favoritos que el usuario tuviera (deja un `.bak`, sin decirlo). |
| 8 | Con `/silent`, VeraCrypt Format **se salta** el aviso de contraseña corta: `CheckPasswordLength(…, Silent, Silent)`. El umbral es `PASSWORD_LEN_WARNING = 20` y el máximo `MAX_PASSWORD = 128` bytes en UTF-8. | `Format/Tcformat.c:6423`, `Common/Password.c:137`, `Common/Password.h` | El asistente acepta cualquier contraseña no vacía sin que nadie avise. |
| 9 | `/size` se redondea **hacia arriba** al tamaño de sector. | `Format/Tcformat.c:6306` | El tope para una unidad FAT32 no puede ser 4 GiB − 1: se usa 4095 MiB. |
| 10 | `VeraCrypt.exe /v <fichero> /q` sin `/l` monta en la **primera letra libre**; sin `/p`, pide la contraseña con **su propio diálogo**; con `/q` sin argumento sale con **0 si montó, 1 si no** (también si se cancela). `/a` además abre una ventana del Explorador. | `Mount/Mount.c` (`ExtractCommandLine`, `WM_INITDIALOG`) | Es la orden del lanzador exterior: la contraseña no pasa ni por nuestra línea de órdenes ni por nuestro proceso. |
| 11 | Desmontar sin `/force` reintenta **30 × 50 ms**; si sigue habiendo ficheros abiertos y no es `/silent`, VeraCrypt pregunta si forzar. | `Common/Dlgcode.h:63`, `Common/Dlgcode.c` (`UnmountVolumeBase`) | No sirve lanzar el desmontaje y salir deprisa: tiene que ocurrir cuando la ventana ya se haya cerrado, desde fuera del contenedor. |
| 12 | `/dismount` (`/d`) se acepta en todas; `/unmount` (`/u`) **no existe** en 1.25.9 ni en 1.26.7 (sí en 1.26.24 y `master`), y un argumento desconocido es `COMMAND_LINE_ERROR`. | `Mount/Mount.c` (tabla de argumentos de `ExtractCommandLine`) | `/dismount` vale con cualquier versión. El `autorun.inf` usaba `/u`. |
| 13 | El propio `autorun.inf` de VeraCrypt nombra el volumen **relativo a la raíz** y entre comillas: `/v "PRDRIVE.hc"`. | `Mount/Mount.c:4584`, `:5040` | La entrada «Montar» del nuestro no llevaba `/v`: solo abría la ventana. |
| 14 | En Linux, `veracrypt <volumen>` en modo gráfico monta de forma interactiva (contraseña y la de administrador con sus diálogos) en `<prefijo>N`, con prefijo `/media/veracrypt`, `/run/media/veracrypt` o `/mnt/veracrypt` (o `VERACRYPT_MOUNT_PREFIX`), y sale con 0, o con 1 si se cancela. | `Main/CommandLineInterface.cpp:694`, `Main/UserInterface.cpp:1065`, `Core/Unix/CoreUnix.cpp:288` | Es la orden del lanzador exterior en Linux. |

## Alcance

**Entra** (este cambio):

- **Fase 0 — lo que está roto**: traveler (nombre del driver y arquitectura),
  el favorito, el tope FAT32, la instalación en claro que se queda al recifrar,
  la contraseña, el `autorun.inf` y la guía del dispositivo.
- **Fase 1 — el vestíbulo**: lo que queda a la vista *fuera* del contenedor
  para abrirlo y cerrarlo en cualquier equipo.
- **Fase 2 — el programa sabe que va cifrado**: penwatch abre el contenedor al
  conectar, la ventana tiene «Expulsar», y «Reparación» avisa cuando un
  contenedor dinámico se va a quedar sin sitio fuera.

**No entra** (fase 3, después):

- Agrandar el contenedor y cambiar la contraseña desde «Ajustes» (los dos
  delegando en VeraCrypt).
- Migrar los datos de un dispositivo sin cifrar al contenedor.
- Crear el contenedor en Linux de forma fiable (montar exige root y la creación
  escribe el volumen entero). Se sigue pudiendo; esta versión no lo mejora.
- Una partición cifrada en lugar de un fichero: **descartada**. Exige
  administrador y reparticionar, y en cualquier equipo sin VeraCrypt Windows
  ofrece «¿Formatear el disco?», que es un clic catastrófico.

## Fase 0 — lo que está roto

### El traveler (`install/traveler.py`)

- **`maquina_pe(ruta) -> str | None`**: la arquitectura de un binario por su
  cabecera PE (`IMAGE_FILE_HEADER.Machine`: `0x8664` → `x64`, `0xAA64` →
  `arm64`, `0x14C` → `x86`). Sin dependencias: `e_lfanew` en `0x3C`, firma
  `PE\0\0`, y el `uint16` siguiente. Es la misma evidencia que usa Windows, no
  una suposición sobre el equipo que prepara.
- **`plan()`** copia los `veracrypt-<arq>.sys` que haya con su nombre, y el
  `veracrypt.sys` de una instalación **como `veracrypt-<arq>.sys`**, con la
  arquitectura leída de su cabecera. Es exactamente lo que hace el diálogo de
  VeraCrypt en el caso MSI. Sin arquitectura legible, `InstallError`: un nombre
  inventado es un traveler que no monta.
- **`arquitecturas()`** solo cuenta los nombres que `DriverLoad()` busca
  (`veracrypt-x64.sys`, `veracrypt-arm64.sys`). Un `veracrypt.sys` suelto —lo
  que dejaron las versiones anteriores— no cuenta, y `comprobar()` lo dice:
  «se copió con un nombre que VeraCrypt portátil no busca; vuelve a pulsar
  "Llevar VeraCrypt"».
- **Cada arquitectura vale solo en la suya.** `comprobar()`: «solo x64: en un
  Windows ARM no monta (un driver no se emula)» y al revés. El docstring del
  módulo, `README.md` y `AGENTS.md` dejan de decir que el x64 vale en ARM.
- El resto no cambia: sigue haciendo falta ser administrador en el equipo, y la
  firma sigue sin verificarse.

### El favorito, fuera

`crypto.write_favorite()`, `crypto.set_config_flag()`, `crypto.ruta_favorita()`,
`crypto.volume_guid_path()` y `crypto.open_veracrypt()` se **borran**, y con
ellos el botón «Que VeraCrypt monte al conectar» del paso 8. No se arregla:

- tal como está no monta nunca (hecho 5), no deja VeraCrypt arrancando al
  iniciar sesión (hecho 6) y borra los favoritos del usuario (hecho 7);
- arreglarlo exigiría guardar el contenedor por **letra** (la única forma que el
  montaje al conectar resuelve para un fichero), escribir en el registro de
  otra aplicación y seguir dependiendo de que esa letra esté libre —«si está
  ocupada, VeraCrypt no monta y no dice nada», dice su documentación—;
- y la fase 2 lo sustituye en todos los equipos, no solo en el que instaló, sin
  tocar la configuración de VeraCrypt.

### Tope FAT32 (`install/crypto.py`)

- **`sistema_de_ficheros(raiz) -> str`**: indirección de módulo (los tests la
  sustituyen) sobre `device.volume_for(raiz).filesystem`; `""` si no se sabe.
- **`tope_contenedor(fs) -> int | None`**: 4095 MiB para `FAT`, `FAT12`,
  `FAT16`, `FAT32`, `vfat` y `msdos` (en minúsculas; `exfat` **no**); None si no
  hay tope. 4095 MiB y no 4 GiB − 1 por el hecho 9.
- `suggested_size(free, dinamico, tope=None)` y `size_to_bytes(raw, free,
  tope=None)` lo respetan; `create_container()` rechaza con `InstallError`
  cualquier tamaño por encima **antes** de lanzar VeraCrypt, con la salida:
  reformatear la unidad en exFAT o NTFS, o elegir 4095M o menos.
- La pantalla lo dice junto al tamaño («FAT32: un fichero no puede pasar de
  4 GiB»).

### La instalación en claro que se queda (`install/crypto.py` + pantallas)

- **`restos_en_claro(raiz_fisica) -> list[str]`**: si en la raíz física hay un
  prdrive sin cifrar (`.prdrive/PRDRIVE` o `.prdrive/runsync.py`), devuelve
  `.prdrive/` y las entradas de primer nivel que no son `RUIDO` (las carpetas
  de datos). Lista vacía si no hay nada.
- El panel de VeraCrypt lo pinta en un bloque rojo **antes** de crear:
  crear el contenedor no mueve ni borra nada; `.prdrive/keys/` sigue con la
  clave en claro; las carpetas pueden tener cambios sin sincronizar; y en
  memoria flash borrar no garantiza que no se pueda recuperar, así que si
  alguien pudo copiar el dispositivo mientras estaba en claro, hay que **cambiar
  la clave del remoto**.
- El paso 8 añade una fila roja con lo mismo mientras siga ahí.
- **No se borra nada automáticamente** («nada se repara solo»): las carpetas de
  datos pueden llevar cambios que no están en el remoto.

### La contraseña (`install/crypto.py` + `ui/tk_crypto.py`)

- **`revisar_contrasena(pw) -> tuple[str | None, str | None]`**: `(error,
  aviso)`, medido en **bytes UTF-8**, como VeraCrypt. Error si está vacía o
  pasa de 128. Aviso si tiene menos de 20: el mismo que VeraCrypt enseñaría sin
  `/silent`.
- Solo al **crear**. El aviso es una pregunta con «No» por defecto, como la de
  VeraCrypt (`MB_DEFBUTTON2`).

### El `autorun.inf` (`install/traveler.py`)

`shell\montar\command=VeraCrypt\VeraCrypt.exe /q /m rm /v "PRDRIVE.hc"` y
`shell\desmontar\command=VeraCrypt\VeraCrypt.exe /q /dismount`. Es la forma del
suyo (hecho 13) con `/dismount` en vez de `/u` (hecho 12). Qué hace el
Explorador con estos verbos en un extraíble no está verificado y el docstring lo
dice; lo que sí funciona es `label` e `icon`.

### La guía del dispositivo (`device-readme.md`)

«Extráela con seguridad» deja de decir que basta con cerrar la ventana: con
VeraCrypt hay que cerrar el contenedor (en la fase 2, «Expulsar»).

## Fase 1 — el vestíbulo

Lo que queda **fuera** del contenedor, en la raíz física, para abrirlo y
cerrarlo en cualquier equipo:

```
E:\
├── PRDRIVE.hc               el contenedor
├── VeraCrypt\               el traveler (si se pidió)
├── Abrir PRDRIVE.bat        Windows: abre el contenedor y lanza prdrive
├── Expulsar PRDRIVE.bat     Windows: cierra el contenedor
├── abrir-prdrive.sh         Linux: lo mismo
├── expulsar-prdrive.sh      Linux: lo mismo
├── LEEME-PRDRIVE.txt        qué es esto y cómo se abre, en diez líneas
├── .prdrive-vestibulo       la marca: el id del dispositivo
└── autorun.inf              nombre e icono de la unidad
```

### La marca: `.prdrive-vestibulo`

```
# PRDRIVE — entrada de un dispositivo prdrive cifrado con VeraCrypt. NO LA BORRES.
# El dispositivo está dentro de PRDRIVE.hc; esta marca es lo que permite
# reconocerlo desde fuera, antes de abrirlo.
id=3f9c…
contenedor=PRDRIVE.hc
```

- El **mismo id** que `.prdrive/PRDRIVE` dentro del contenedor: así penwatch,
  atado a ese id, reconoce el dispositivo cerrado, y la ventana, desde dentro,
  encuentra su raíz física.
- Oculta (punto en POSIX, `deploy.hide()` en Windows).
- Deja a la vista que el volumen es un prdrive. Ya lo decían `PRDRIVE.hc` y la
  carpeta `VeraCrypt\`: la negación plausible no existía antes de esto.

### `Abrir PRDRIVE.bat`

1. `cd /d "%~dp0"`: su directorio de trabajo no puede quedar dentro del
   contenedor.
2. Si alguna unidad ya tiene `.prdrive\PRDRIVE` con **este** id, no monta:
   lanza el `runsync.bat` de esa unidad y sale.
3. Elige VeraCrypt: el instalado (`%ProgramFiles%\VeraCrypt\VeraCrypt.exe`)
   antes que el que viaja (`%~dp0VeraCrypt\VeraCrypt.exe`), por el hecho 4. Sin
   ninguno, lo dice y remite a `LEEME-PRDRIVE.txt`.
4. `start "" /wait "%VC%" /volume "%~dp0PRDRIVE.hc" /mountoption rm
   /mountoption label=PRDRIVE /history n /cache n /quit` (hecho 10). La
   contraseña la pide VeraCrypt: nunca pasa por el `.bat`.
5. No se fía del código de salida (regla 2 de `crypto.py`: en modo portátil
   VeraCrypt se relanza elevado): busca la unidad con el id, reintentando unos
   segundos. Si no aparece, dice que no se ha abierto y sale.
6. Lanza `<unidad>\runsync.bat`.

Mismas reglas que `runsync.bat`: CRLF, sin bloques entre paréntesis (una ruta
con `)` los rompe) y `chcp 65001` solo donde se escribe texto con acentos.

### `Expulsar PRDRIVE.bat`

`cd /d "%~dp0"`, encuentra la unidad con el id y, si la encuentra, espera tres
segundos (quien la llama es la ventana que se está cerrando, hecho 11) y lanza
`"%VC%" /dismount <letra> /quit` **sin** `/silent`: si queda algo abierto,
VeraCrypt pregunta si forzar, con su diálogo. Si no la encuentra, no hay nada
abierto.

### `abrir-prdrive.sh` y `expulsar-prdrive.sh`

- Abrir: si ya está montado (busca el id bajo los prefijos del hecho 14), lanza
  su `runsync.sh`. Si no, `veracrypt "<raíz>/PRDRIVE.hc"` —con escritorio, en
  modo gráfico; sin él, `--text`, que pregunta por la terminal—, busca el
  montaje y lanza `runsync.sh`.
- Expulsar: `sleep 3` y `veracrypt -d "<raíz>/PRDRIVE.hc"`.
- Sin VeraCrypt instalado lo dicen: en Linux no hay traveler.

### `LEEME-PRDRIVE.txt`

Diez líneas, texto plano, UTF-8 con BOM y CRLF: qué es la unidad, «doble clic en
Abrir PRDRIVE» (o `sh abrir-prdrive.sh`), que hará falta la contraseña y quizá
aceptar el aviso de administrador, «Expulsar PRDRIVE» antes de quitarla, y que
**no se borre** `PRDRIVE.hc`.

### Quién lo escribe

- **`install/vestibulo.py`** (nuevo; no importa Tk): los textos
  (`bat_abrir()`, `bat_expulsar()`, `sh_abrir()`, `sh_expulsar()`, `leeme()`,
  `marca()`), `escribir(raiz_fisica, device_id) -> list[Path]` y
  `comprobar(raiz_fisica, device_id) -> list[Check]`.
- Lo llama el **paso 5** cuando `encryption == "veracrypt"`, justo después de
  `ensure_control_file()` (que es de donde sale el id), y **«Añadir
  plataformas…»** cuando el dispositivo está en un contenedor: es el camino que
  ya existe para poner lanzadores a un dispositivo viejo. La misma regla que los
  lanzadores: **nunca** `--update`, «Actualización» ni `deploy_code()`.
- El paso 8 añade sus filas a la verificación.
- `device.RUIDO` suma los seis nombres nuevos, o un dispositivo recién hecho se
  leería como ajeno la próxima vez.

### Las constantes, y quién las repite

`common/vestibulo.py` tiene `MARCA`, `CONTENEDOR`, `ABRIR_BAT`, `EXPULSAR_BAT`,
`ABRIR_SH`, `EXPULSAR_SH` y `LEEME`. `install/` las importa. **penwatch las
repite** (se copia al equipo y no importa nada del proyecto) y un test comprueba
que no se separan, como ya pasa con `CONTROL_FILE`.

## Fase 2 — el programa sabe que va cifrado

### penwatch abre el contenedor al conectar

Sustituye al favorito, en **cualquier** equipo que tenga penwatch.

- **`find_vestibulo(cfg) -> Path | None`**: una raíz con `.prdrive-vestibulo`
  cuyo `id` es el `device_id` del vigilante y con el contenedor al lado.
- En `watch_loop`, cuando `find_pen()` no encuentra el dispositivo pero sí su
  vestíbulo, y el disparo de apertura no se ha gastado en esta conexión:
  **`abrir_contenedor(root)`** lanza VeraCrypt con la orden del hecho 10 (el
  instalado antes que el que viaja, por el hecho 4; en Linux `veracrypt
  <contenedor>` si hay escritorio). VeraCrypt pide la contraseña.
- **No lanza runsync**: cuando el volumen aparece montado, el bucle de siempre
  lo encuentra por `.prdrive/PRDRIVE` y lanza lo que diga `mode`. Así se
  respeta el modo (`daemon` no abre ventana) y no hay dos lanzamientos
  compitiendo por el cerrojo de la ventana.
- **Una vez por conexión**: si el usuario cancela la contraseña, no se vuelve a
  preguntar hasta que el dispositivo desaparezca y vuelva. El estado guarda
  `vestibulo` (la raíz) y se rearma igual que `launched`.
- Nunca escribe en el dispositivo; `cwd` en `HOST_DIR`, como `launch()`.
- `status` y `probe` dicen «cifrado y cerrado» cuando ven el vestíbulo.

### «Expulsar» en la ventana principal

- **`common/vestibulo.py`**: `raiz_fisica(device_id) -> Path | None` recorre las
  raíces con `penwatch.candidate_roots({})` —importado dentro de la función,
  como hace `ui/watch.py`: un solo recorrido de unidades en todo el proyecto, el
  que ya sabe no sacar el diálogo de «no hay disco»— y busca la marca con ese
  id. None en cualquier fallo.
- **`ui/cifrado.py`** (nuevo; no importa Tk): `expulsion() -> Path | None`, el
  script de expulsar si este dispositivo está dentro de un contenedor, y
  **`lanzar_expulsion(script)`**, indirección de módulo: `os.startfile` en
  Windows (lo mismo que un doble clic), `sh` en una sesión nueva en Linux, con
  `cwd` en la raíz física.
- La ventana pinta **«Expulsar»** en el pie, junto a «Iniciar servicio», **solo**
  si `expulsion()` encuentra algo. Se apaga mientras corre una pasada, como el
  resto. Al pulsarlo, una confirmación (se cierra la ventana, se cierra el
  contenedor, después se puede quitar), `lanzar_expulsion()` y se cierra.
  Con la ventana abierta no hay servicio en marcha (abrirla lo para), así que
  cerrar la ventana es cerrar todo lo nuestro que tiene ficheros abiertos.
- `icons.py` gana el glifo `expulsar`.

### «Reparación» avisa del espacio de fuera

Un contenedor **dinámico** crece a medida que se escribe; si la unidad física se
llena, el volumen de dentro da errores de E/S en mitad de un bisync, y rclone no
puede explicar por qué.

- **`vestibulo.disperso(contenedor) -> bool`**: el atributo
  `FILE_ATTRIBUTE_SPARSE_FILE` en Windows; en POSIX, `st_blocks * 512 <
  st_size`.
- **`revision.revisar()`** añade el hallazgo `espacio` (gravedad de aviso) cuando
  el dispositivo está en un contenedor disperso y a la unidad física le queda
  menos de **1 GiB** libre. El detalle da las dos cifras. No tiene botón:
  la solución es liberar sitio fuera o pasar el contenedor a uno fijo.
- Es la misma diagnosis para `sync.py --doctor` y la ventana; `revision` importa
  `vestibulo`, que es de `common/`.

### El asistente

- `AVISO_AUTOARRANQUE` pasa a decir que, con penwatch en el equipo, al conectar
  el dispositivo aparece la contraseña de VeraCrypt y después la ventana; y que
  sin él está «Abrir PRDRIVE».
- El paso 8 pierde «Que VeraCrypt monte al conectar» (fase 0) y conserva
  «Instalar el arranque automático (penwatch)», que ahora cubre también esto.

## Lo que NO cambia

- La creación: `/dynamic` cuando hay dispersos, `/quick`, AES + SHA-512,
  `/pim 0`, `--stdin` en Linux. La contraseña sigue sin guardarse.
- Montar en el asistente sigue siendo `mount_container()` con la contraseña en
  la línea de órdenes en Windows (su CLI no admite otra cosa) y `redact()`.
  El vestíbulo es el camino de todos los días y ahí la contraseña ya no pasa por
  nosotros.
- `.prdrive/`, los lanzadores de dentro y la guía de dentro siguen dentro del
  contenedor.
- BitLocker: nada.
- penwatch sigue sin escribir en el dispositivo y sin importar nada.

## Pruebas

- **`tests/test_traveler.py`**: `maquina_pe()` con cabeceras sintéticas (x64,
  arm64, x86, no PE, truncada); `plan()` renombra `veracrypt.sys` según su
  cabecera y copia `veracrypt-*.sys` tal cual; sin arquitectura legible, error;
  `arquitecturas()` ignora `veracrypt.sys`; `comprobar()` con solo x64, solo
  arm64, los dos, y el `veracrypt.sys` heredado; el `autorun.inf` lleva `/v` y
  `/dismount`.
- **`tests/test_crypto_veracrypt.py`**: sin favoritos (las funciones ya no
  existen); `tope_contenedor()` con cada nombre de FAT y exFAT/NTFS;
  `suggested_size()` y `size_to_bytes("max")` con tope; `create_container()`
  rechaza antes de lanzar nada; `revisar_contrasena()` en los bordes (0, 19, 20,
  128, 129 bytes, y acentos que cuentan dos); `restos_en_claro()`.
- **`tests/test_vestibulo.py`** (nuevo): los textos (CRLF en los `.bat`, sin
  `(`/`)` fuera de los comentarios, el id y el contenedor dentro, instalado
  antes que traveler, `/dismount`, sin `/silent` al expulsar, sin `/password`);
  `escribir()` deja los seis ficheros; la marca se lee con `leer_id()`;
  `comprobar()`; `destino()`; y los `.sh` **ejecutados** contra un `veracrypt`
  de mentira.
- **`tests/test_penwatch_vestibulo.py`** (nuevo): `find_vestibule()` con id
  correcto, otro id, sin contenedor; la orden de VeraCrypt en Windows y en
  Linux; el bucle lanza la apertura una sola vez por conexión, no la repite
  tras «Expulsar» y la rearma al desaparecer; no lanza runsync desde el
  vestíbulo; las constantes coinciden con `common/vestibulo.py`. También
  `raiz_fisica()`, `disperso()`, el hallazgo `espacio` (solo con contenedor
  disperso y poco sitio fuera) y `cifrado.expulsion()` /
  `lanzar_expulsion()`.
- Los nombres nuevos están en `RUIDO` (en `tests/test_vestibulo.py`).
- **`tests/test_install_wizard.py`**: el panel de VeraCrypt con restos en claro,
  FAT32 y contraseña corta; el paso 5 con contenedor deja el vestíbulo con el id
  del fichero de control; «Añadir plataformas…» se lo pone a uno de antes.
- **`tests/test_tk_medidas.py`**: el panel de VeraCrypt en su peor caso, en toda
  la matriz. **`tests/test_tk_principal.py`**: la ventana con y sin
  «Expulsar», cancelar y confirmar.
- `python tests/run_all.py` en verde.

## Documentación

- **`AGENTS.md`**, «VeraCrypt: four things not to weaken» pasa a cubrir el
  traveler corregido (renombrar el driver; cada arquitectura solo en la suya),
  el vestíbulo, penwatch abriendo el contenedor y por qué no hay favorito. La
  lista de constantes duplicadas suma las del vestíbulo.
- **`README.md`**: «Cifrar con VeraCrypt» (traveler, vestíbulo, abrir y
  expulsar, FAT32, la contraseña).
- **`device-readme.md`**: cómo se abre y cómo se expulsa, corto.
- **`VERSION`** → `0.2.5`.

## Después (fase 3)

- «Ajustes» → agrandar el contenedor y cambiar la contraseña, delegando en
  VeraCrypt (el Expander y su diálogo), desde el vestíbulo porque el contenedor
  tiene que estar cerrado.
- Migrar un dispositivo sin cifrar al contenedor, con la advertencia de la
  clave.
- Linux como sistema de creación de primera.
- Copia de la cabecera del volumen fuera del dispositivo (VeraCrypt ya guarda
  una de respaldo dentro del propio `.hc`).
