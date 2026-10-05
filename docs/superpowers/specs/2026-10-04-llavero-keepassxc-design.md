# El llavero (`.keychain`): KeePassXC de viaje y una base que se sincroniza sola

Fecha: 2026-10-04 · Estado: **decidida**; fases 0 y 1 hechas (sin probar en real: §15), 2 y 3 sin implementar; lo que cambió al hacer la 1, en §16 · Versión objetivo:
0.6.0 · Sustituye a la primera propuesta del mismo día (`3cdf1d5`) · Pruebas de
las que sale:
`docs/superpowers/pruebas/2026-10-04-keepassxc-portatil.md` y sus resultados
(solo Windows ARM64). Los códigos K/B/PK/V/A/S y los hallazgos H-n se citan tal
cual.

## Qué se pide

Llevar en la unidad las claves privadas de las **passkeys** (y las
contraseñas) en una base de KeePassXC, y entrar rápido en GitHub y en sitios
parecidos desde cualquier equipo donde se abra la unidad. La base se mantiene
igual en todos los dispositivos de la persona **sin que tenga que pensar en
ello**: ni parejas que configurar, ni carpetas que crear en el remoto, ni pasos
extra al expulsar.

## Decidido al plantearlo

- **KeePassXC viaja dentro de `.prdrive/`** (`.prdrive/keepassxc/`). prdrive lo
  descarga, lo comprueba y lo actualiza como rclone o VeraCrypt.
- **La base vive en `.keychain/`**, en la raíz del volumen, oculta como
  `.prdrive/`. **Una sola base**, con el nombre que traiga.
- **La gestiona prdrive.** No es un `[[pair]]` ni sale en «Parejas»: el código
  construye su pareja y fija sus filtros y su política de conflictos.
- **En el remoto va junto al catálogo**, en una subcarpeta `keychain/` de la
  carpeta del catálogo. No hay que crear ni elegir ninguna carpeta más.
- **Lo que se guarda sube solo.** Vigilan el servicio del dispositivo, el agente
  o, si no hay ninguno, un vigilante que arranca «Llavero» y vive lo mismo que
  KeePassXC. Lo de otro dispositivo llega cada **5 min** mientras KeePassXC está
  abierto.
- **Expulsar**: si queda algo sin subir, hace una pasada **sin decir nada**.
  Solo se habla si hay error, con un tope de 60 s. Sin red, una línea.
- **Cualquier dispositivo**, cifrado o no.
- **Se activa en el asistente dándole un `.kdbx`**, o trayendo el del remoto en
  un segundo dispositivo. También desde «Ajustes → Llavero…» (§9).
- **Fichero llave**: prdrive **no lo copia, no lo lee y no guarda ninguna huella
  suya**. Solo recuerda dónde lo tiene la persona en cada equipo. En el catálogo
  queda apuntado que la base lo pide, para avisar en otro dispositivo.
  YubiKey, no.
- **`pairs.toml` pasa a llamarse `remote.toml`**, porque ya no lleva solo
  parejas. Los remotos nuevos nacen así. En los que ya existen, «Ajustes» ofrece
  renombrarlo, pero solo cuando las notas de la flota dicen que todos los
  dispositivos leen ya el nombre nuevo (§3).
- **rclone no vigila nada por su cuenta.** La documentación de bisync lo dice:
  «Rclone does not yet have a built-in capability to monitor the local file
  system for changes and must be blindly run periodically». En la v1.75.1 el
  backend local no declara `ChangeNotify` (`backend/local/local.go`), y ese
  mecanismo es para cambios **del remoto**: solo lo usa `mount`, y solo en
  algunos remotos.
  - Se descarta `rclone mount` con `--vfs-cache-mode writes` +
    `--vfs-write-back`, lo más parecido: pide WinFsp o FUSE, la base dejaría de
    estar en la unidad para vivir en la caché, no funciona sin red y no detecta
    conflictos (gana el último que escribe).
  - La vigilancia es la nuestra: el sondeo del agente (`huella.py`,
    `PoliticaCambios`), aplicado a un solo fichero.

## Lo que dijeron las pruebas y dónde se atiende

| Hallazgo | Aquí |
|---|---|
| V1, V2: ningún sitio rechazó el salto de BE/BS | Una sola versión de viaje (≥ 2.7.12) en todos los equipos; la mezcla deja de pasar. §11 para Linux ARM |
| A1 bien, A2 roto (H-7) | En Windows ARM, el ZIP x64 emulado. §11 |
| K3: el ZIP no trae el runtime de Visual C++ | Se detecta al arrancar y se explica. §6 |
| B2, H-6: un equipo nuevo no se configura solo | prdrive escribe las claves del registro antes de abrir. §7 |
| B4, H-18, B5: el registro no se limpia | prdrive las quita al expulsar, o las devuelve a un KeePassXC instalado. §7, §10 |
| K5, K6, H-16: KeePassXC y el proxy retienen el volumen | «Expulsar» se encarga de los dos. §10 |
| H-1: Windows Hello deja una credencial en el equipo | `QuickUnlock` empieza apagado. §6 |
| H-11 (S2): temporales del guardado y «¿Desactivar almacenajes seguros?» | Solo viajan `*.kdbx`; `UseAtomicSaves` se reenciende en cada arranque; la base se comprueba antes de subir. §4, §6 |
| H-12 (S3): bisync con un solo fichero | Un compañero fijo al lado de la base. §4 |
| H-13: `--resync` con la base vieja | `resync-mode = "newer"`. §4 |
| H-14 (S4): el conflicto silencioso | `conflict-loser = "num"` y «Combinar». §8 |
| S5: KeePassXC combina si tiene cambios sin guardar | Se aprovecha tal cual. §8 |
| S6, H-15, PK5: exportaciones en claro, y la carpeta personal del equipo | No viajan; KeePassXC propone la raíz del volumen. §4, §6 |
| PK6, H-10, H-17 | La guía, y las pruebas R7–R8. §12, §15 |
| H-2: tres formatos de `.DIGEST` | No afecta: la suma va fijada en el código. §5 |

## 1. Lo que vive la persona

1. **Al preparar un dispositivo**, el asistente ofrece el llavero con tres
   salidas:
   - **«Usar esta base…»**: se elige un `.kdbx`.
   - **«Traer el del remoto»**: solo si el catálogo ya tiene uno.
   - **«Crear una nueva con KeePassXC»**: es una propuesta, §9.

   Si es una base propia, pregunta **«¿Esta base usa un fichero llave?»** y, si
   la respuesta es sí, **«¿Dónde está en este equipo?»**. Se apunta la ruta; el
   fichero no se toca.
2. **En cada navegador**, una vez por perfil: instalar KeePassXC-Browser,
   «Conectar» y activar «Enable Passkeys». La asociación se guarda en la base y
   viaja con ella (B2).
3. **Cada día**: abrir la unidad → «Llavero» (en la ventana de prdrive o en
   `Llavero.bat`) → KeePassXC se abre con la base y, si la hay, la ruta del
   fichero llave ya puesta → contraseña → los sitios piden la passkey y
   KeePassXC firma.
4. **Lo que se guarda** sube unos 20 s después del último cambio. Lo de otro
   dispositivo llega en 5 min como mucho mientras KeePassXC esté abierto, y
   siempre al pulsar «Llavero».
5. **En otro equipo**, el mismo «Llavero». prdrive prepara el registro de ese
   equipo (arregla B2). Si la base pide fichero llave y en ese equipo no se ha
   dicho dónde está, lo pregunta una vez.
6. **Expulsar**: si KeePassXC está abierto, se ofrece cerrarlo. El proxy y el
   vigilante se paran solos. Lo que quede sin subir, sube. El registro queda
   como estaba y se desmonta. La persona no ve nada distinto, solo tarda un poco
   más cuando había algo pendiente.
7. **Un segundo dispositivo** con el mismo remoto: «Traer el del remoto». Si la
   base pide fichero llave, el asistente lo avisa con su nombre («Esta base
   pide el fichero llave "personal.keyx"…») y pregunta dónde está en ese equipo.
8. **Si dos dispositivos cambiaron la base** sin sincronizar en medio,
   «Llavero» lo dice antes de abrir y ofrece combinarlas (§8).

## 2. Dónde está cada cosa

```
<raíz del volumen>/
├── .prdrive/
│   ├── keepassxc/
│   │   ├── windows-x64/              el ZIP tal cual (trae .portable); también en Windows ARM
│   │   │   ├── PRDRIVE-KEEPASSXC     el sello (§5)
│   │   │   └── config/               SOLO los JSON del navegador, que KeePassXC rehace al arrancar
│   │   └── config/windows/           keepassxc.ini, keepassxc_local.ini, raiz.txt
│   ├── filters/keychain.txt          generado (§4)
│   └── state/
│       ├── keychain/                 la baseline de bisync, como cualquier pareja
│       └── keychain.json             por equipo: dónde está el fichero llave
├── .keychain/                        oculta: punto delante + deploy.hide()
│   ├── LEEME.txt                     compañero fijo (H-12): qué es esto y que no se toque
│   └── <base>.kdbx
└── Llavero.bat · llavero.sh          lanzadores, junto a runsync.*
```

En el remoto:

```
<catalog_remote>:/prdrive-catalog/    la carpeta de `catalog_path`
├── remote.toml                       antes pairs.toml; lleva [keychain] (§3)
├── remote.toml.bak                   el de push()
├── devices/                          las notas de la flota
└── keychain/
    ├── LEEME.txt
    ├── <base>.kdbx
    └── .prversions/
```

- **`.keychain/` es de prdrive.** Va en `device.RUIDO` y se reescribe pasando
  antes por `deploy.unhide()`, como el marcador del vestíbulo. Lo que pase con
  una pareja del usuario con `local = "."` (la raíz entera) se decide en §4.
- **El programa y su configuración van separados**: la configuración se pasa con
  `--config` y `--localconfig` (`src/main.cpp`, opciones `config` y
  `localconfig`). Así cambiar de versión sustituye la carpeta del programa
  entera. Los JSON del navegador quedan en `<exe>/config/` porque está
  `.portable` (`getNativeMessagePath()`), y perderlos no importa: KeePassXC los
  rehace en cada arranque (`updateBinaryPaths()`).
- **La ruta del fichero llave queda en la unidad**, en `state/keychain.json`, por
  equipo (`prefs.HOST`, el mismo que usa `ui_prefs.json`). En el equipo no queda
  nada sin agente. En una unidad sin cifrar, esa ruta se puede leer: dice
  **dónde** está el fichero llave en cada equipo, no qué tiene.
- **Que el dispositivo lleva llavero se sabe por lo que hay**: `[keychain]` en
  `sync_config.toml` y KeePassXC con su sello.

## 3. El catálogo: `remote.toml` y su `[keychain]`

### El nombre nuevo (fase 0, hecha)

`pairs.toml` salía en 18 módulos y tests y en 8 documentos, y `catalog_path` en
76 sitios. Además, cada dispositivo en uso lo lee. El cambio fue en **su propia
fase, antes que el llavero**, con esta regla de compatibilidad. Al implementarla
cambiaron tres cosas respecto a lo decidido; van marcadas.

- **Para leer** (`catalog.leer()`, la usan el dispositivo y el instalador): si
  `catalog_path` nombra uno de los dos nombres, se busca **primero
  `remote.toml` y después `pairs.toml`, en la misma carpeta, nombre el que
  nombre**. Se pasa al segundo solo si rclone dice que el primero no existe
  (`cat` de un fichero que no está sale con 3, medido con v1.75.1); sin red no,
  porque tardaría lo mismo en no llegar. Un nombre propio se lee tal cual.
  - *Cambio:* se decidió «el que nombra `catalog_path` y, si no está, el otro».
    Con `remote.toml` siempre primero, «si están los dos manda `remote.toml`»
    sale solo, sin preguntar nada más. Y es lo barato al final: renombrado el
    remoto, cada lectura es un solo `cat` diga lo que diga cada dispositivo.
    Hasta entonces, el que dice `pairs.toml` paga un `cat` fallido por lectura.
- **Para escribir** (`push()`): en el fichero que se acaba de releer con la
  misma regla, nunca en el otro. Si otro dispositivo renombró entre la lectura y
  la escritura, el cambio va a `remote.toml`. Una subida a `pairs.toml` mira
  después si ha aparecido `remote.toml`. Si ha aparecido, la subida se cruzó con
  el renombrado: se dice que el cambio no cuenta y queda apuntado.
- **Si aparecen los dos**, manda `remote.toml`. Queda apuntado en la copia local
  (`state/catalog.json`) cuando lo ve alguien que mira: esa subida, la pantalla
  de renombrar o el propio renombrado. «Reparación» lo dice, sin botón porque es
  una operación en el remoto. La pantalla de renombrar ofrece entonces «Apartar
  pairs.toml…», que lo deja al lado como `pairs.toml.apartado-<fecha>` sin
  borrarlo.
- **Un remoto nuevo** nace con `remote.toml`: el `catalog_path` por defecto es
  `/prdrive-catalog/remote.toml`.
- **Un remoto que ya existe** se renombra solo cuando la persona lo pide y la
  flota dice que se puede:
  - «Ajustes» ofrece «Renombrar el catálogo…» mientras lo último que se leyó
    fue su `pairs.toml`, o mientras conste que están los dos. Lo decide sin red.
  - El botón solo se activa si **todas** las demás notas de `devices/` dicen que
    saben leer el nombre nuevo. *Cambio:* no se mira la versión, sino una lista
    nueva de la nota, `entiende = ["remote.toml"]` (`fleet.ENTIENDE`). Una
    versión no dice qué sabe hacer un dispositivo hasta saber en qué release
    entró cada cosa, y la fase 0 todavía no tiene número; la lista dice
    justo lo que se pregunta. Este dispositivo no cuenta, porque su nota puede
    ser de antes de actualizarse. La pantalla nombra a los que lo impiden, con
    su versión (o «su nota no dice qué versión lleva») y su última vez visto.
    También explica cómo desbloquearlo: quitar de la lista los que ya no se
    usan, o actualizarlos y dejar que sincronicen. Un dispositivo que nunca
    publicó nota no se puede ver, y el texto lo dice.
  - Renombrar es `moveto` de `pairs.toml`, y de su `.bak` si lo hay, a
    `remote.toml`, tras mirar la carpeta, porque `moveto` pisa el destino sin
    preguntar. No reescribe el contenido. *Cambio:* no se toca el
    `catalog_path` de nadie, tampoco el de este dispositivo. Con
    `remote.toml` primero no hace falta, y tocarlo habría hecho salir los
    `[defaults]` como «modificada aquí».
  - El plan avisa de que un instalador de antes no encontrará el catálogo: hay
    que usar uno de esta versión o escribir `…/remote.toml` en «Conexión».
- `problema_de_ruta()` acepta los dos nombres, y `explicar_carpeta()` sugiere el
  que haya dentro, `remote.toml` primero. Los textos de la ventana dicen «el
  catálogo» sin nombrar el fichero.

### `[keychain]`

```toml
[keychain]
base = "personal.kdbx"
fichero_llave = true
nombre_llave = "personal.keyx"   # solo una pista para la persona: ni ruta ni huella
```

- Lo escribe la activación (§9) con el `push()` del catálogo, `.bak` incluido.
  Lo cambia «Ajustes → Llavero…» si la persona añade o quita el fichero llave en
  KeePassXC. prdrive no tiene cómo saberlo: la cabecera KDBX no dice qué
  credenciales lleva la base.
- **No se guarda ninguna huella del fichero llave.** Para un fichero que no sea
  de los de KeePassXC, su clave es justo el SHA-256 del contenido
  (`FileKey::loadHashed()`): guardar esa suma sería guardar la llave. Si se elige
  el fichero equivocado, KeePassXC ya dice que la credencial no vale.
- **Una versión vieja de prdrive la lee, pero no puede reescribirla.** El modelo
  ignora una tabla desconocida, pero hasta la 0.5.3 el serializador
  (`config_file.dumps()`) la perdía al escribir. Entonces `dumps_checked()` se
  negaba con «no reproduce lo que se pidió», y en ese dispositivo no se podría
  editar el catálogo. No pierde nada, porque se niega.
  - La fase 0 ya escribe tal cual, al final, cualquier tabla que no conoce
    (`TABLAS_CONOCIDAS`). Lo fijan `test_catalog` y `engine.md`.
  - Antes de escribir `[keychain]` en el catálogo, la activación mira la flota
    como el renombrado: que todas las notas digan `remote.toml` en `entiende`,
    que es decir «fase 0 o posterior». Si no, avisa de quién se quedaría sin
    poder editar el catálogo.
- En el `sync_config.toml` del dispositivo basta con `[keychain] base = "…"`. El
  resto lo deduce el código.

## 4. La pareja del llavero, construida en código

- **`model.parse_config()`** construye la pareja cuando hay `[keychain]`, y el
  TOML no puede cambiarla:
  ```
  Pair(name="keychain", local=".keychain",
       remote=<catalog_remote>, remote_path=<carpeta de catalog_path>/keychain,
       mode=bisync, versions=True,
       flags: conflict-loser="num", resync-mode="newer")
  ```
  - `conflict-loser = "num"` (§8) gana al `setdefault("conflict-loser", "delete")`
    de `sync.py`:380.
  - `resync-mode = "newer"` es por H-13.

  El nombre `keychain` queda reservado solo si el llavero está activo, y activarlo
  se niega si ya hay una pareja del usuario que se llame así.
- **La baseline**: todo lo que entra en `bisync.expected_prefix()` está fijado,
  salvo la carpeta del catálogo. Mover el catálogo (`catalog_path`,
  `catalog_remote`) **aparca** la baseline y pide un `--resync`, como en cualquier
  pareja; con `newer` no se pierde nada.
- **Los filtros, generados**: solo entra lo que tiene que viajar. Es la misma
  lógica que `- .prversions/**`: una condición previa, no un filtro
  (`conflicts-versions.md`).
  ```
  - .prversions/**
  - *.old.kdbx
  + *.kdbx
  + LEEME.txt
  - **
  ```
  Así no viajan los temporales de `QSaveFile` (`<base>.kdbx.XXXXXX`, H-11 a),
  ni los `.passkey`, ni un CSV/HTML/XML exportado, ni nada que una versión futura
  de KeePassXC deje al lado. `+ *.kdbx` deja pasar también las copias de
  conflicto, que acaban en `.kdbx` (`suffix-keep-extension`). El orden lo pone
  esta pareja: `filters_content()` hoy escribe los `+` antes que los `-`.
- **Antes de cada pasada, la base tiene que estar entera** (`common/kdbx.py`, sin
  clave):
  - firmas `0x9AA2D903`/`0xB54BFB67`;
  - cabecera TLV hasta `EndOfHeader`;
  - el SHA-256 de la cabecera que lleva KDBX 4;
  - una cadena de bloques HMAC que acaba justo al final del fichero con un
    bloque de tamaño 0.

  Si no está entera, se espera 2 s y se mira otra vez. Si sigue igual, la pasada
  no corre y se dice. KDBX 3.1 solo comprueba la cabecera; un formato que no se
  conoce no bloquea. Es la red principal contra H-11. La otra es que rclone ya
  falla un fichero que cambia mientras lo sube.
- **El compañero fijo** (H-12): `LEEME.txt` no cambia nunca, así que un cambio
  solo en la base nunca es «todos los ficheros han cambiado». Si falta,
  «Reparación» lo repone.
- **Una pareja del usuario con `local = "."`** recibe `- /.keychain/**` del código.
  Si no, sincronizaría la base por otro camino, con otras reglas. El agente
  añade `.keychain` a `IGNORAR_CAMBIOS`. (Hoy `.prdrive/` no tiene esa misma
  protección en el código, y valdría la pena dársela, pero no es de este
  cambio.)
- **No sale en «Parejas»**, así que su estado va en una línea propia de la
  ventana principal: «Llavero: al día · hace 3 min», «subiendo…», «cambios sin
  subir (sin conexión)», «dos versiones: combinar», «la base no está entera».
  Sus conflictos cuentan en el aviso de siempre. `sync.py` la corre con las
  demás, y `sync.py keychain` sola. `--list` la enseña marcada.

## 5. El componente KeePassXC

- **Pin** (`common/pins.py`): `KEEPASSXC_VERSION = "2.7.12"`,
  `KEEPASSXC = {"windows-x64": ("KeePassXC-2.7.12-Win64.zip", sha256)}` y
  `KEEPASSXC_PARA = {"windows-arm64": "windows-x64"}`, con el porqué (A1, A2,
  H-7). Mover el pin es a mano: comprobar el `.sig` con la clave de KeePassXC
  (huella `BF5A669F…6397D0D2`, K0) y escribir la suma. En ejecución no se lee
  ningún `.DIGEST` (H-2).
- **`install/keepassxc_bin.py`** sigue el guion de `veracrypt_bin`:
  - descarga en la caché por versión, con `descarga.con_reintentos()`;
  - comprueba la suma antes de escribir nada;
  - extrae con la defensa contra `../` de `update.py`;
  - escribe el sello `PRDRIVE-KEEPASSXC` (`keepassxc`, `paquete`, `sha256` y una
    línea `fichero <rel> = <sha256>` por fichero);
  - sustituye con `.nuevo-<pid>` / `.viejo-<pid>` y `os.replace`, tras mirar el
    espacio libre, como `traveler.sustituir()`.
- **Actualizar**: una fila más en `components.pendientes()`. Con KeePassXC o su
  proxy corriendo desde `.prdrive/keepassxc/` (el proxy es del navegador), se
  espera y el recuadro ámbar dice «Cierra KeePassXC y el navegador para poner al
  día el llavero». Para eso `procesos_desde()` pasa de `install/components.py`
  (que no viaja) a `common/store.py`, e `install/` lo reexporta.
- **Con `[keychain]` y sin sello**, `pendientes()` lo cuenta como «no consta»,
  igual que un rclone sin sello. Es lo que hace barato activarlo desde «Ajustes»
  (§9).

## 5b. Vigilancia y pasadas

- **Una sola cosa atiende el llavero en cada momento**, por este orden: el agente
  si atiende el dispositivo, el servicio del dispositivo (`runsync --auto`) si
  corre, y si no, el vigilante del llavero. Un cerrojo en `state/` decide, como
  los de `model.ui_lock()` / `daemon_lock()`.
- **Cambios locales**: cada 10 s, el tamaño y el `mtime_ns` de la base. Si exFAT
  tuviera dos guardados del mismo tamaño en el mismo tic de reloj, se lee
  además la semilla de la cabecera (`MasterSeed`, unos cientos de bytes del
  principio), que KeePassXC cambia en cada guardado. Las reglas son las de
  `planificador.PoliticaCambios`: calma 20 s, separación 120 s.
  - Al salir 20 s después de la ráfaga, la pasada choca menos con un guardado
    (S2) que una periódica.
  - El servicio del dispositivo **gana esta vigilancia solo para el llavero**. La
    general (`watch = true`) sigue siendo cosa del agente.
- **Cambios del remoto**: cada 5 min mientras KeePassXC corre desde el volumen
  (`procesos_desde`). Si no corre, el intervalo de siempre.
- **El vigilante del llavero** (`runsync.py --vigilar-llavero`, `pythonw`, sin
  ventana):
  - vive mientras viva el KeePassXC del volumen;
  - cuando ese KeePassXC sale, hace la pasada pendiente si la hay y sale él
    también;
  - corre desde el volumen, así que «Expulsar» lo para.
- **«Pendiente de subir»** quiere decir que la base no coincide (tamaño,
  `mtime`) con su línea en el listado `path1` de la última pasada buena de bisync
  (`state/keychain/`). No hace falta otro registro, y pilla también lo que se
  guardó **durante** una pasada, que la vigilancia absorbe hasta la siguiente
  (`agent-scheduling.md`).

## 6. «Abrir llavero»

`runsync.py --llavero`, sin consola. Las decisiones están en
`common/llavero.py`, puro. Lo que toca el equipo (`registro.*`,
`procesos_desde`, `lanzar`, el diálogo de fichero) son funciones de módulo que
los tests sustituyen. Los pasos:

1. **Si ya está abierto desde el volumen**, se trae delante (por
   `SingleInstance`, lanzarlo con la base hace eso) y no hay más pasos.
2. **Si el equipo tiene otro KeePassXC abierto**, se avisa: con `SingleInstance`,
   el nuestro le pasaría la base a ese, que tiene otra configuración.
3. **Si hay copias de conflicto**, se ofrece «Combinar ahora» (§8).
4. **Traer lo último**: una pasada si la última tiene más de 2 min y hay
   conexión, pintada con `working()`. Si falla, se abre igual con una línea.
5. **El fichero llave**, si `fichero_llave`: la ruta de este equipo sale de
   `state/keychain.json`. Si no hay o ya no existe (estaba en otro pendrive que
   no está puesto, se movió…), un diálogo: «¿Dónde está "personal.keyx" en este
   equipo?». Se apunta la ruta. El fichero ni se abre.
6. **La configuración**, solo con KeePassXC cerrado. Se edita línea a línea: se
   cambian las claves de la lista y el resto queda byte a byte.
   - **En cada arranque**:
     - `UseAtomicSaves=true` (deshace un «Deshabilitar», H-11);
     - `Browser/UpdateBinaryPath=true`;
     - `GUI/CheckForUpdates=false` (la versión la pone prdrive);
     - las rutas de `LastOpenedDatabases`, `LastDatabases`, `LastActiveDatabase`
       y `LastDir` que empiezan por la raíz anterior (apuntada en `raiz.txt`)
       pasan a la actual.
   - **Solo al crearla**:
     - `Browser/Enabled=true`;
     - `Security/QuickUnlock=false` (H-1);
     - `RememberLastKeyFiles=false` (la ruta del fichero llave la recuerda
       prdrive por equipo; si no, KeePassXC propondría en un equipo la del otro);
     - `UpdateCheckMessageShown=true`;
     - `BackupBeforeSave=false` y `GUI/MinimizeOnClose=false`, que ya son los
       valores por defecto.
7. **El navegador**: §7.
8. **Lanzar**:
   ```
   KeePassXC.exe --config …\config\windows\keepassxc.ini
                 --localconfig …\config\windows\keepassxc_local.ini
                 [--keyfile <ruta de este equipo>]
                 <raíz>\.keychain\<base>.kdbx
   ```
   - Entorno: `KPXC_INITIAL_DIR=<raíz>`. Lo que se exporte cae en la raíz del
     volumen, a la vista. No en `.keychain/`, que está oculta y donde se quedaría
     olvidado, ni en la carpeta personal del equipo, que fue lo que pasó en PK5.
   - `--keyfile` rellena el campo del diálogo de desbloqueo
     (`mainWindow.openDatabase(filename, password, keyfile)`).
9. **El vigilante**: si nadie atiende el llavero, arranca uno (§5b).
10. **Si sale con `0xC0000135`** (falta el runtime de Visual C++, K3): qué falta,
    que hace falta un administrador y dónde está el instalador oficial de
    Microsoft.

## 7. El navegador en el equipo (Windows)

Las cuatro claves de `HKCU\Software\…\NativeMessagingHosts\org.keepassxc.keepassxc_browser`
(`NativeMessageInstaller.cpp`, `TARGET_DIR_*`). Chrome, Brave y Vivaldi
comparten una; Firefox y Tor, otra (H-5).

| Clave | JSON al que apunta prdrive |
|---|---|
| `Google\Chrome` | `<exe>\config\org.keepassxc.keepassxc_browser_chrome.json` |
| `Microsoft\Edge` | `…_edge.json` |
| `Mozilla` | `…_firefox.json` |
| `Chromium` | `…_chromium.json` |

- **Al abrir**: se escriben las cuatro, haya lo que haya. En Windows
  `isBrowserEnabled()` solo mira que la clave tenga valor, y al arrancar
  `updateBinaryPaths()` rehace los JSON y las claves de todo lo «habilitado».
  Es el camino de B3, provocado en un equipo nuevo. KeePassXC se las quedaría
  igualmente (B5).
- **Al cerrar** (§10), para cada clave que apunte dentro del volumen o a un
  `…\.prdrive\keepassxc\…` que ya no existe:
  - si existe `%LOCALAPPDATA%\KeePassXC\org.keepassxc.keepassxc_browser_<n>.json`
    (un KeePassXC **instalado**), la clave vuelve a apuntar ahí;
  - si no, se borra. `NativeMessagingHosts` se borra solo si queda vacía.

  Las claves de otros programas no se tocan. La regla no necesita recordar
  nada: lo deduce.
- Se escribe con `winreg` envuelto en `common/registro.py` (`leer`, `escribir`,
  `borrar`), punto de sustitución de los tests. Encima va el plan puro de
  `llavero.py`.
- Lo que prdrive no hace por la persona: instalar la extensión, conectarla y
  activar «Enable Passkeys», que son ajustes de cada perfil del navegador.

## 8. Conflictos: combinar, no elegir

Con `conflict-loser = "num"`, el perdedor se queda al lado como
`<base>.conflicto-remoto1.kdbx` y entra en `conflicts.json` como cualquier otro
conflicto.

- **«Combinar»**, la primera opción para el llavero, es un `EditPlan` de
  `conflict_editor`:
  - abre una consola con
    `keepassxc-cli merge --same-credentials [-k <fichero llave de este equipo>] <base> <copia>`.
    La contraseña la pide la CLI, nunca prdrive.
  - Con código 0, la copia va a `.keychain/.prversions/`, recuperable, y la
    siguiente pasada la quita del otro lado.
  - Si falla, no se toca nada y se explica la vía de la ventana de KeePassXC
    («Base de datos → Combinar desde base de datos…», S4).
  - Las opciones de siempre («quedarse con…») siguen detrás, avisando de que
    pierden lo de la otra.
- **El mejor momento es al abrir el llavero** (§6, paso 3): antes de que la
  ventana de KeePassXC tenga la base abierta. Si la tuviera, lo arregla la
  recarga (S3) o el diálogo de combinar (S5).
- **Se reutiliza para otro caso**: si al activar ya hay una base en el remoto y
  la persona da otra (§9), la suya entra como copia de conflicto y se combina al
  abrir.
- **No se combina en silencio**: haría falta la contraseña.

## 9. Activar el llavero

- **En el asistente**, después de «Parejas y configuración», en dispositivos
  cifrados o no:
  - **«Usar esta base…»**: `kdbx.py` la comprueba sin contraseña (no es KDBX →
    no; KDBX 3.1 → aviso de que KeePassXC la convierte a KDBX 4) y se **copia** a
    `.keychain/<nombre>`. El texto dice que la original se queda donde estaba y
    que **desde ahora la buena es la del dispositivo**. La original nunca se toca.
  - **«Traer el del remoto»**, si el catálogo tiene `[keychain]`: la primera
    pasada la baja. Si `fichero_llave`, se dice y se pregunta la ruta en este
    equipo.
  - **«Crear una nueva con KeePassXC»** (propuesta): se abre el KeePassXC recién
    puesto en su bienvenida, con `KPXC_INITIAL_DIR=<raíz>\.keychain`; la
    persona crea la base (KDBX 4 con Argon2 por defecto) y al cerrar KeePassXC el
    asistente la encuentra. prdrive no ve la contraseña.
  - Para una base propia o nueva, **«¿Usa un fichero llave?»** → **«¿Dónde está
    en este equipo?»**.
  - Al terminar: el sello de KeePassXC, `[keychain]` en `sync_config.toml` y en
    el catálogo, `LEEME.txt`, `Llavero.bat`/`llavero.sh` y la primera pasada
    (`--resync`, `newer`). Si el remoto ya tenía otra base, se aplica §8.
- **En un dispositivo ya preparado**: el panel «ya es un prdrive» del instalador
  suma «Añadir el llavero…» a «Actualizar» y «Añadir plataformas…».
- **«Ajustes → Llavero…»** en la ventana del dispositivo. No es complicado,
  porque el único paso que necesita el instalador es descargar KeePassXC, y eso
  ya lo resuelve otro camino:
  - activar pide lo mismo que el asistente y escribe `[keychain]` aquí y en el
    catálogo (`catalog_editor` ya sabe hacer `push()`), sin red salvo para el
    catálogo;
  - KeePassXC queda como «no consta» en `components.pendientes()` (§5), y el
    recuadro ámbar de siempre ofrece «Actualizar…». Eso lanza
    `--update-components` desde la release descargada, que lo pone y escribe
    `Llavero.bat`;
  - la misma pantalla sirve después para decir si la base usa fichero llave,
    cambiar su ruta en este equipo y desactivar el llavero. Desactivar quita
    `[keychain]` de aquí; `.keychain/` y el remoto no se tocan, y se dice.

## 10. Expulsar

El mismo paso previo, `llavero.cerrar()`, en los tres caminos:

- la ventana, antes de `cifrado.lanzar_expulsion` (`ui/tk.py`:1183);
- `Expulsar PRDRIVE.bat`, antes de `/dismount` (`install/vestibulo.py`:422-426),
  llamando a `runsync.py --cerrar-llavero` con el Python del dispositivo, que
  termina antes de desmontar;
- y, en la fase 3, el agente.

Los pasos:

1. **KeePassXC desde el volumen** → «KeePassXC está abierto. ¿Cerrarlo?». Se
   cierra como lo haría la persona (`taskkill /PID` sin `/F`, que manda
   `WM_CLOSE`), así que si hay algo sin guardar, KeePassXC pregunta. Se espera a
   que salga. Nunca `/F`.
2. **El proxy** (`keepassxc-proxy.exe` desde el volumen) → se termina. No guarda
   estado, y es lo que obligaba a cerrar el navegador (K6, H-16).
3. **El vigilante del llavero** → se para.
4. **Si hay algo pendiente** (§5b) → una pasada, **sin decir nada**, con un tope
   de 60 s:
   - bien → nada;
   - sin red o con el tope cumplido → una línea: «El llavero se subirá la
     próxima vez»;
   - conflicto, base que no está entera u otro fallo → se dice, y «Llavero» lo
     retoma la próxima vez.
5. **El registro** (§7, al cerrar).
6. **Lo de siempre**: VeraCrypt, `:libre`, «ya puedes quitar la unidad».

**En un dispositivo sin cifrar** hoy no hay «Expulsar»: la ventana solo lo
ofrece con VeraCrypt (`cifrado.expulsion()`). Con llavero, la ventana lo ofrece
también ahí. Hace los pasos 1–5 y termina con «Ya puedes quitarla (Quitar
hardware de forma segura)». Pedir a Windows la expulsión de verdad
(`CM_Request_Device_EjectW`) puede venir después. El vigilante cubre casi todo
lo demás: cuando se cierra KeePassXC, sube lo pendiente.

**Sin expulsar** (un tirón): KeePassXC muere y la base sobrevive por el guardado
atómico (K7, H-4). Quedan claves apuntando a una letra muerta, que no hacen
daño: el siguiente «Llavero» en ese equipo las rehace, y en la fase 3 las quita
el agente.

## 11. Linux y ARM (fase 2, cuando LX1–LX7 y LA1–LA3 digan)

- **Linux x64**: el AppImage fijado en `.prdrive/keepassxc/linux-x64/`.
  - Sin FUSE 2, o con el volumen `noexec`: se extrae una vez por equipo en
    `~/.cache/prdrive/keepassxc/<versión>/` (el exFAT del volumen no admite sus
    enlaces simbólicos) y se lanza `AppRun`. Hay precedente: `model.ejecutable()`.
  - La configuración, en `config/linux/`.
  - El proxy: `Browser/UseCustomProxy` + `CustomProxyLocation`, reescrito en cada
    arranque, hacia un envoltorio que sepa lanzar lo uno o lo otro.
  - Los manifiestos en `~/.config/…/NativeMessagingHosts/` y
    `~/.mozilla/native-messaging-hosts/` se escriben al abrir y se quitan al
    cerrar, con la misma regla que el registro.
  - El Firefox snap (LX5), sin probar.
- **Linux ARM**: no hay AppImage aarch64. Como V1/V2 no vieron rechazos con
  versiones mezcladas, se usa el KeePassXC del equipo (Flathub 2.7.12, LA1–LA2,
  o uno del sistema ≥ 2.7.7), con la misma base y el mismo fichero llave.
  Debian 12 (2.7.4) y Ubuntu 24.04 (2.7.6) abren la base pero no tienen
  passkeys: se dice.

## 12. La guía

`docs/guia/llavero.md`, más una línea en `device-readme.md`:

- Qué es el llavero, dónde está (oculto) y que no hay que tocar `.keychain/` a
  mano.
- Cada navegador, una vez: la extensión, «Conectar» y «Enable Passkeys», con
  capturas.
- El fichero llave: prdrive no lo copia ni lo sube. Tenlo en cada equipo donde
  vayas a abrir el llavero; prdrive pregunta dónde una vez por equipo.
- Lo que queda en el equipo mientras la unidad está abierta, que prdrive quita
  al expulsar, y qué pasa si se quita sin expulsar.
- Exportar (passkey, CSV…) deja el contenido sin cifrar en la raíz del volumen,
  y nunca viaja: bórralo al acabar.
- «¿Desactivar almacenajes seguros?» → «Cancelar» (H-11).
- Con la base bloqueada, desbloquea y abre otra pestaña (PK6). Tras reiniciar
  KeePassXC, recarga la extensión desde su icono si dice «no disponible» (H-17).
- «Synced» en GitHub es normal (PK2).
- Las versiones viejas de la base, en `.prversions/` de los dos lados (S7), y
  cómo se combinan dos versiones.
- Los equipos prestados: lo que se teclea en un equipo con algo malo instalado
  se puede leer, con passkeys o sin ellas.

## 13. Lo que no hace

- No copia, no lee, no sube ni guarda la huella del fichero llave. YubiKey,
  tampoco.
- No ve la contraseña de la base ni combina sin preguntar.
- No autorrellena ni habla con el navegador: eso es KeePassXC.
- Más de una base, macOS y móviles: fuera.

## 14. Fases

| Fase | Qué | Ficheros |
|---|---|---|
| **0. `remote.toml`** (hecha, `1e5bb51`) | Nombre nuevo con la regla de §3 y «Renombrar el catálogo a remote.toml…» en «Ajustes» | `common/catalog.py`, `common/fleet.py`, `install/remote.py`, `ui/catalog_editor.py`, `ui/tk_pairs.py`, `ui/tk_doctor.py`, `common/revision.py` (los dos ficheros a la vez), sus tests, `catalogue.md`, `fleet.md`, `sync_config.example.toml`, `docs/guia/` |
| **1. Windows** (x64, y ARM con el x64; hecha, `d1eb572`…`cd0f7fb`, sin probar en real) | Todo lo demás (lo que cambió, en §16) | `common/pins.py`, `common/kdbx.py` (nuevo), `common/llavero.py` (nuevo), `common/registro.py` (nuevo), `common/store.py` (`procesos_desde`), `common/model.py` (`[keychain]` → pareja), `common/bisync.py` (filtros; `- /.keychain/**`), `common/components.py`, `sync.py` (comprobación previa), `runsync.py` (`--llavero`, `--vigilar-llavero`, `--cerrar-llavero`; vigilancia del llavero en el servicio), `install/keepassxc_bin.py` (nuevo), `install/components.py`, `install/deploy.py` (lanzadores, `LEEME.txt`, ocultar), `install/vestibulo.py` (`.bat`), `install/device.py` (`RUIDO`), `agente.py` (`IGNORAR_CAMBIOS`, atender el llavero), `ui/conflict_editor.py`, `ui/tk_conflicts.py`, `ui/tk.py` (botón, línea, «Expulsar» sin VeraCrypt), `ui/tk_llavero.py` (nuevo), `ui/tk_doctor.py` (`ENTRADAS`), `ui/tk_install.py` (paso, «Añadir el llavero…»), `common/revision.py` (compañero que falta) |
| **2. Linux** | §11 | `install/keepassxc_bin.py`, `common/llavero.py`, `install/vestibulo.py` (`.sh`) |
| **3. El agente** | «Llavero» en la bandeja; aviso nativo de un conflicto del llavero; quitar las claves del registro cuando la unidad se va sin expulsar; el llavero en la raíz del equipo | `agente.py`, `ui/bandeja.py`, `common/avisos.py` |

La fase 1 crea `docs/agents/reference/llavero.md`, su regla en `.claude/rules/` y
una fila en la tabla de `AGENTS.md` (`test_reglas_claude.py` vigila que las tres
cuadren). `catalogue.md` y `agent-scheduling.md` cuentan lo suyo.

## 15. Pruebas

**Sin equipo:**

- `test_kdbx.py`: bases sintéticas (entera, cortada en cada sitio, firma mala,
  KDBX 3.1, desconocida) y la semilla como huella.
- `test_llavero.py`:
  - el plan del registro (equipo nuevo, otra letra, KeePassXC instalado, claves
    ajenas);
  - el `.ini` byte a byte;
  - el fichero llave por equipo (sin ruta, ruta que ya no existe, otro equipo);
  - `cerrar()` con procesos falsos;
  - «pendiente de subir» contra un listado de bisync;
  - quién atiende el llavero (agente, servicio, vigilante).
- `test_model` / `test_bisync`: la pareja que sale de `[keychain]`, el nombre
  reservado, los filtros y su orden, `- /.keychain/**` en una pareja de raíz, y
  que mover el catálogo aparca la baseline.
- `test_catalog`:
  - el nombre de `catalog_path` y, si falta, el otro;
  - escribir en el que exista;
  - los dos a la vez (manda `remote.toml`);
  - `[keychain]` ignorado por el lector de antes;
  - el botón de renombrar con una flota al día, con un dispositivo viejo y con
    una nota sin versión (`fleet` falso).

  Hechos en la fase 0, con un remoto de mentira que guarda ficheros y contesta
  como rclone v1.75.1, la carrera entre una subida y el renombrado incluida.
- `test_keepassxc_bin.py`: `fetch` falso, suma mala, `../`, sello, sustitución y
  espera por procesos; la deriva entre pins y sello (`test_components`).
- «Combinar» con una CLI falsa (0, fallo, copia que cambió entretanto).

**En real** (plan nuevo):

| Código | Qué falta ver |
|---|---|
| R1 | K3 en un Windows x64 limpio: `0xC0000135` y el mensaje |
| R2 | `--config`/`--localconfig` con `.portable`: la configuración en `config/windows/`, los JSON en `<exe>/config/` |
| R3 | B2 con las claves de prdrive: un equipo nuevo conecta sin marcar nada (Chrome, Edge, Firefox) |
| R4 | Terminar el proxy al expulsar: ¿reconecta la extensión al volver? (H-17) |
| R5 | Con un KeePassXC instalado (WI): sigue funcionando tras expulsar |
| R6 | «Combinar» desde prdrive, con fichero llave y sin él, con la ventana de KeePassXC abierta y cerrada |
| R7 | PK3 a mano: «Enable Passkeys» en Firefox |
| R8 | PK6 otra vez, con `Browser/UnlockDatabase=true` |
| R9 | V2 en GitHub (0→1), con una cuenta de usar y tirar |
| R10 | S2 con los filtros nuevos y la vigilancia: guardar en ráfagas, y la comprobación de base entera frente a un «Deshabilitar» |
| R11 | `--keyfile` con el fichero en otro pendrive con otra letra, y sin él puesto |
| R12 | La vigilancia en exFAT: dos guardados seguidos de igual tamaño; la semilla |
| R13 | Expulsar con algo pendiente: cuánto tarda de más, sin red y con el tope |
| R14 | El vigilante: arranca con «Llavero», sube al cerrar KeePassXC y no retiene el volumen al expulsar |
| R15 | Edge: B1, PK1 y R3 |
| R16 | Renombrar el catálogo de un remoto con dos dispositivos: el otro lo encuentra, y con uno viejo en la flota el botón no se activa |

## 16. Cómo quedó la fase 1

Hecha en ocho entregas (`d1eb572` el componente, `f4bdbbd` la pareja, `6ffeab1`
la vigilancia, `eef112e` «Abrir llavero», `0d14fb6` «Combinar», `018bfa0` y
`413c39d` activarlo, `cd0f7fb` expulsar). El detalle técnico está en
`docs/agents/reference/llavero.md`; la guía, en `docs/guia/llavero.md`. **Nada se
ha probado todavía en hardware real**: las pruebas R1–R15 de §15 siguen
pendientes. Cambió respecto a lo decidido:

- **La flota no se mira antes de escribir `[keychain]`** (§3): la persona es la
  única que usa el repositorio, y lo pidió así. Un dispositivo de antes de la
  fase 0 no podría editar el catálogo después.
- **`LEEME.txt` lo pone `llavero.preparar()` antes de cada pasada**, si falta, en
  vez de una avería de «Reparación» (§2, §14). Con los mismos bytes en todos los
  sistemas (`\n`), para que dos dispositivos no se pisen.
- **El llavero se resincroniza solo** cuando bisync lo pide (sin baseline,
  filtros cambiados), sin aprobación: es la única excepción a «una pareja que
  pide `--resync` se salta». `resync-mode = newer` y el backup-dir hacen que no
  se pierda nada, y saltarlo lo dejaba sin sincronizar sin que nadie se enterase
  (una pasada saltada sale con 0). Por eso no hay averías de resync del llavero.
- **El botón se llama «Abrir llavero»**, no «Llavero» (la línea de la ventana ya
  empieza por la base). `Llavero.bat` es `runsync.bat --llavero`, y lo pone la
  activación, no `--update-components`.
- **Antes de abrir** (§6): no hay pasada si el servicio o el agente atienden la
  raíz (chocaría con su lock de bisync), salvo que falte la base. Una pasada que
  falla se dice en la línea de la ventana; con un aviso, solo sin ventana
  (`Llavero.bat`). Los fallos del registro van en una sola línea.
- **El orden de §6 cambia**: «Combinar» va después de traer lo último (que es lo
  que trae la copia) y del fichero llave (que hace falta para combinar).
- **«Combinar»** corre en una consola a la vista (`runsync.py
  --combinar-llavero`, con el Python de consola), donde `keepassxc-cli merge
  --same-credentials` pide la contraseña; la copia va a `.prversions/` con el
  sello de rclone. Probado contra `keepassxc-cli` 2.7.6 de verdad.
- **El agente** atiende el llavero como una pareja vigilada, pero sin el tirón
  de 5 min con KeePassXC abierto: queda para la fase 3.
- **El `[keychain]` local es la tabla entera** (base, `fichero_llave`,
  `nombre_llave`), no solo `base`: así el dispositivo sabe sin red si la base
  pide fichero llave.
- **La base tiene que acabar en `.kdbx` en minúsculas**: el filtro `+ *.kdbx`
  distingue, y una `.KDBX` no viajaba. Al activar se normaliza.
- **Arreglo de paso**: el escaneo de conflictos no veía los del llavero, porque
  una pareja con versiones lleva siempre `--suffix-keep-extension` (lo pone
  `sync.py`) y `conflicts.esquema()` no lo sabía.
- **No están**: «Crear una nueva con KeePassXC» en el asistente (se crea en
  KeePassXC y se da con «Usar esta base…»), y «Añadir el llavero…» en el panel
  «ya es un prdrive» del instalador (un dispositivo preparado lo activa desde su
  ventana, sin otra conexión). `llavero.sh` y Linux siguen en la fase 2.
