# El llavero en la nube — resultados

Fecha: 05/10/2026. Especificación: `../specs/2026-10-04-llavero-keepassxc-design.md`
(los R-n son los de su §15). Código: `claude/gallant-lamport-95o1u2`, de
`327819b` (la fase 2 acabada) a `077c0b4`.

Hecho **sin hardware**: en el contenedor Linux de una sesión en la nube, a
mano y con guiones, y luego en los equipos de usar y tirar de GitHub Actions
(Windows y Linux) con `tests/integracion/llavero_real.py`. Todo es de verdad
salvo lo que dice cada fila: rclone y KeePassXC bajados y comprobados, el
código del dispositivo corriendo en el dispositivo, procesos y ficheros
reales. Lo que no hay es una persona, un USB que se saca, un navegador ni una
cuenta con passkeys.

## 1. Entorno

- **Linux (la nube)**: Ubuntu 24.04.4, como root, sin `libfuse2`. Sin módulo
  exFAT en el núcleo: una imagen de 600 MB con **exFAT por FUSE**
  (`exfat-fuse` 1.4.0) en un loop. Pantalla `Xvfb :99` sin gestor de ventanas.
  `xterm` 390 (`x-terminal-emulator` → `lxterm` → `uxterm`), `xdotool` para
  escribir, y el `keepassxc` 2.7.6 de Ubuntu instalado.
- **El dispositivo**: montado con el código del instalador
  (`deploy.deploy_code`, `write_device_remote`, `write_device_config`,
  `write_launchers`, `device.ensure_control_file`), rclone v1.75.1, un remoto
  `local` en una carpeta del contenedor con su catálogo y una pareja. La
  carpeta personal y las XDG, en un temporal.
- **KeePassXC**: el AppImage 2.7.12 fijado, puesto con
  `install.components.aplicar` (lo de «Actualizar…»), y una base de pruebas
  creada con su `keepassxc-cli`.
- **Windows y Linux (GitHub Actions)**: `windows-latest` y `ubuntu-latest`
  (xvfb), Python 3.11, con `.github/workflows/llavero-real.yml`. Ver §4.

## 2. Fallos que salieron, y su arreglo

Cinco, los cinco invisibles para los tests (rclone y KeePassXC simulados):

| # | Qué pasaba | Por qué | Arreglo |
|---|---|---|---|
| 1 | La primera pasada del llavero fallaba siempre en un remoto recién activado | `bisync --resync` aborta si la carpeta del remoto no existe, y `keychain/` no la crea nadie | `5f662ad`: `rclone mkdir` antes del resync |
| 2 | **Ninguna pasada dejaba copia de conflicto**: con cambios en los dos lados ganaba la base más nueva y la otra iba a `.prversions/` sin que nadie la combinara | `--resync-mode` es un `--resync` para rclone (`setResyncDefaults()`), y el llavero lo llevaba en todas las pasadas | `8d1b003`: solo en un resync, también si lo pone el usuario |
| 3 | Tras «Combinar», cada pasada abortaba con «too many deletes», aquí y en los demás dispositivos | El freno es un 25 % del listado anterior, y el llavero tiene tres o cuatro ficheros: quitar una copia ya es un 33 % | `d59fa30`: si lo borrado son solo copias de conflicto, la pasada se repite una vez sin el freno |
| 4 | Quitada la unidad sin expulsar, el agente dejaba los manifiestos del navegador | Limpiaba justo después de pedirle a KeePassXC que se cerrara, y tarda ~0,5 s en salir | `23493a3`: queda pendiente y se hace cuando sale |
| 5 | Tras «Combinar» un conflicto que ganó el remoto, salía otro conflicto con una copia que no traía nada | **Fallo de rclone** (v1.75.1, y sigue en `master`): `modifyListing()` quita el nombre de la base de los dos listados al apuntar el renombrado del perdedor de este lado | `b5d6047`: otra pasada en seguida, con las dos iguales, y bisync la vuelve a apuntar |

El 2 escondía al 3 y al 5: con cada pasada siendo un resync no había ni
conflictos que combinar ni borrados que propagar. Del 5 convendría abrir una
incidencia en rclone (`cmd/bisync/listing.go`: con `--conflict-loser num` y
gana Path2, el bucle de `b.renames` hace `srcList.remove(srcOldName)` y
`dstList.remove(dstOldName)` aunque la copia del ganador ya está con ese
nombre); el arreglo de prdrive no estorba si lo corrigen.

## 3. Lo que se vio en Linux

| R | Qué | Cómo | Resultado |
|---|---|---|---|
| R24 | El AppImage como componente, extraído en `~/.cache/prdrive/keepassxc/2.7.12/` | `components.aplicar` (bajado y comprobado contra el sello), «Abrir llavero» con el código del dispositivo, en exFAT por FUSE y sin `libfuse2` | **Sí**: se extrae en 1,5–3 s y abre la base. Sin `noexec` ni Fedora |
| R25 | La configuración en `.prdrive/keepassxc/config/linux/`, nada en `~/.config/keepassxc` | Mirar las dos carpetas tras abrir, guardar y cerrar | **Sí**. Las recientes en otro equipo, no se probó |
| R26 | El navegador sin marcar nada | Los manifiestos de Chrome y Firefox (sus carpetas existen) y un `change-public-keys` de KeePassXC-Browser por el proxy que nombra cada uno; también por el proxy 2.7.6 de Ubuntu | **Sí, el protocolo**: responde la 2.7.12 con `success`. Sin navegador ni extensión de verdad |
| R27 | El Firefox snap | — | No |
| R28 | Expulsar | `runsync.py --cerrar-llavero` (lo que llama `Expulsar PRDRIVE`) con KeePassXC y el vigilante abiertos | **Sí**: SIGTERM, cerrado en 2 s, lo pendiente sube, los manifiestos se quitan, sale con 0. Que el proxy no retiene el volumen, sin navegador no se pudo ver |
| R29 | Quitar la unidad sin expulsar | `umount -l` con KeePassXC y el vigilante abiertos; luego, sin vigilante, las funciones del agente con los procesos de verdad | **Sí**: el vigilante lo cierra en ≤ 2 s; el agente lo cierra y quita los manifiestos al salir (tras el arreglo 4). Lo de «pregunta si hay algo sin guardar», no (nada sin guardar en la ventana) |
| R30 | «Combinar» en una terminal | Un conflicto de verdad, el plan de «Combinar» con la terminal real y `xdotool` escribiendo la contraseña en ella | **Sí, con xterm**: se abre, `keepassxc-cli merge` la pide, combina en 3 s y aparta la copia. Ni GNOME, ni KDE, ni Xfce; cerrar la terminal a medias no se vio |
| R31 | Linux ARM64 con el KeePassXC del equipo | El de Ubuntu 2.7.6, haciendo como si no hubiera paquete (`paquete_del_equipo()` → `None`) | **Sí, con el de la distribución**: abre la base con él, avisa de que no tiene passkeys, es «de la unidad» y «Expulsar» lo cierra en 1,6 s. Ni Flathub ni ARM64 de verdad, ni fichero llave |
| R10, R12, R14 | La vigilancia | Guardar con `keepassxc-cli add` con KeePassXC abierto y medir | Un guardado sube a los 5–125 s (la separación de 120 s desde la última pasada); un cambio del remoto baja a los 300 s (`REMOTO_ABIERTO`); el vigilante se va al expulsar y al quitar la unidad. En exFAT por FUSE, no en un USB |

**Observado y sin arreglar:**

- Quitada la unidad, KeePassXC escribe su `keepassxc_local.ini` al salir, y si
  el punto de montaje sigue ahí y se puede escribir vuelve a crear
  `.prdrive/keepassxc/config/linux/` dentro. Aquí pasó porque era root y el
  punto de montaje era una carpeta mía. Con udisks el punto de montaje se
  borra y `/media/<usuario>` (o `/run/media/<usuario>`) no se deja escribir,
  así que no debería pasar: está por ver en un equipo de verdad.
- Sin agente, una unidad quitada deja los manifiestos de Linux. Apuntan al
  proxy de la caché, que sigue ahí y llega a cualquier KeePassXC: no estorban,
  y el próximo «Abrir llavero» los rehace.

## 4. Windows y Linux en GitHub Actions

`tests/integracion/llavero_real.py` hace de punta a punta lo de §3 que no
necesita una persona: bajar rclone y KeePassXC, activar, abrir (en Windows,
las cuatro claves de HKCU y el JSON que escribe KeePassXC al arrancar), el
mensaje de KeePassXC-Browser por el proxy, un guardado que sube el vigilante,
un conflicto de verdad combinado con `plan_combinar()` (la contraseña por la
entrada en vez de en la consola), el borrado de la copia, y expulsar.

- En la nube (Linux): todo bien en `b5d6047`, tras dos vueltas que dieron con
  los fallos 3 y 5.
- En GitHub Actions: pendiente de la primera ejecución.

## 5. Lo que queda para el equipo de verdad

Lo que necesita a una persona, un USB o un navegador: R1–R9, R11, R13, R15–R23
(fase 1 y 3, Windows), y de Linux R27, `noexec` y Fedora (R24), las recientes
(R25), un navegador de verdad (R26, R28), «pregunta si hay algo sin guardar»
(R29), las terminales de escritorio (R30), Flathub y ARM64 (R31), y el punto
de §3 sobre el `keepassxc_local.ini`.
