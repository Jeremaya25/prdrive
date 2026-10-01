# VeraCrypt Portable (#50) — pruebas V1–V7 en real

Fecha: 30/09/2026. Equipo: Windows 11 IoT Enterprise LTSC 2024 (26100), x64.
Unidad de pruebas: **G:** (115 GB, exFAT, prdrive 0.5.0 sin cifrar, id
`73cb9c4b…`). Código: `main` en `f3aab97` (0.5.0). Plan: la tabla de #50.

V2 y V3 (Windows ARM64) quedan para otro equipo.

| Prueba | Estado |
|---|---|
| V1 | OK |
| V2, V3 | pendientes (Windows ARM64) |
| V4 | **no hecha** (pospuesta, sin VeraCrypt instalado) |
| V5 | OK |
| V6 | OK |
| V7 | OK |

## Estado de partida

- Sin VeraCrypt en `Program Files` ni en el registro de desinstalación, **pero
  con un driver suelto**: servicio `veracrypt` (inicio `System`, tipo kernel)
  con `C:\WINDOWS\system32\drivers\veracrypt.sys` **1.26.29.3**, cargado. Sin
  filtros de clase que lo nombren.
  - Hallazgo **P-1**: un driver de otra versión sin instalación visible.
    `penwatch.installed_veracrypt()` / `crypto.find_veracrypt()` no ven nada
    instalado y eligen el Portable 1.26.24, que con ese driver cargado fallaría
    con `ERR_DRIVER_VERSION`. Ni el asistente ni el `.bat` lo detectan hoy.
- Se quitó para V1: `sc stop` (se queda en `STOP_PENDING`: el driver no se
  descarga en caliente), `sc delete`, `.sys` renombrado a
  `veracrypt.sys.borrar`, reinicio.
- La caché real (`%LOCALAPPDATA%\prdrive-install\veracrypt\1.26.24`) se borró
  antes de V1 para que descargue desde cero.
- Antes de V1, G: tenía la instalación anterior en claro (`.prdrive/`,
  `sync-data/`, `README.md`, `runsync.*`). Después de V1 no estaba, y
  `System Volume Information` tenía fecha de las 13:39, antes del reinicio. El
  asistente no borra nada de eso (`crypto.restos_en_claro()` solo avisa) y el
  usuario cree que formateó G: a mano. **No se cuenta como fallo, pero el aviso
  de restos en claro no se ha visto en esta pasada.**

## V6 — paquete corrupto y descarga cortada: OK

Script en el scratchpad de la sesión, sobre una **copia** de la caché real
(15 ficheros, verificada) y la descarga **real** de Launchpad (40 413 480
bytes, 6,6 s, SHA-256 el fijado). Instantánea (sha256 + mtime) de cada fichero
de la caché antes y después de cada caso.

| Caso | Resultado | Caché |
|---|---|---|
| A: descarga real | SHA-256 correcto, 14 ficheros seleccionados | — |
| B: un byte cambiado en medio | «… no es el paquete de VeraCrypt fijado», a la primera | intacta |
| B2: el mismo byte con el pin movido a su hash | «su CRC-32 no cuadra (VerifyPackageIntegrity)» | intacta |
| C: servidor local que anuncia todo y corta a la mitad | `IncompleteRead` → 3 peticiones, esperas 5 s y 15 s → `SinRed` «(probado 3 veces)» | intacta |
| D: la mitad con un `Content-Length` que la da por completa | falla el hash, **1** petición, sin reintentos | intacta |
| E: paquete corrupto dejado a mano en la caché, sin sello | `ensure_veracrypt()` lo dice y no va a la red (0 peticiones); el fichero a mano sigue ahí | intacta |
| F: un byte de `VeraCrypt-x64.exe` cambiado en la caché | `cached()` → None, `ensure_veracrypt()` descarga de nuevo y queda verificada | reparada |

## V1 — x64 sin VeraCrypt: OK

Tras el reinicio: sin servicio `veracrypt`, sin `.sys`, caché vacía. Asistente
lanzado por el usuario desde un terminal **sin administrador**
(`python prdrive-install.py`, Python 3.14 del equipo): G: → «Reinstalar desde
cero» → VeraCrypt → «Descargar VeraCrypt Portable» → contenedor de 2 GiB (exFAT
en G:, así que fijo) → Conexión con un remote `alias` local de prueba
(`D:\prdrive-prueba-remoto`, catálogo con una pareja `docs` en bisync) →
instalación ligera → `docs` → inicialización → verificación.

| Qué | Resultado |
|---|---|
| Descarga y caché | `%LOCALAPPDATA%\prdrive-install\veracrypt\1.26.24\` con los 14 ficheros + `PRDRIVE-VERACRYPT` |
| Crear | `VeraCrypt Format-x64.exe` **de la caché** (`/create G:\PRDRIVE.hc /size 2147483648 … /filesystem exFAT /quick /silent /force`) |
| Montar | `VeraCrypt-x64.exe` **de la caché** (`/volume … /letter Q /m rm /m label=PRDRIVE /quit /silent`) |
| UAC | **2**: uno al crear, uno al montar (lo esperado: cada operación con el Portable) |
| Contenedor | Q: exFAT, 2 GiB, con sistema de ficheros: `.prdrive/`, `sync-data/docs/leeme.txt` traído por el `--resync` |
| Driver | servicio `veracrypt` creado por el Portable: `Start = 4`, `ImagePath` en la caché, RUNNING con Q: montada |
| Raíz física | `PRDRIVE.hc`, `VeraCrypt\` (las dos arquitecturas, sin renombrar, con sello 1.26.24 y el sha256 del paquete), vestíbulo (`Abrir/Expulsar PRDRIVE.bat`, `.sh`, `LEEME`, marca oculta), `autorun.inf` con `icon=VeraCrypt\VeraCrypt-x64.exe` |
| Id | `id=` de `.prdrive-vestibulo` = `id=` de `Q:\.prdrive\PRDRIVE` |

## V7 — la copia elevada de Format: OK

Vigía de procesos (Win32_Process cada 300 ms) durante V1:

```
13:54:27.693 + pid=15772 padre=12588 VeraCrypt Format-x64.exe  /create G:\PRDRIVE.hc …
13:54:29.944 + pid=8832  padre=15772 VeraCrypt Format-x64.exe  /q UAC /create …
13:54:32.172 - pid=15772            (el que lanzamos sale a los 4,5 s)
13:55:47.101 - pid=8832             (la copia elevada termina: 1 min 17 s escribiendo)
13:55:47.485 + pid=17220 padre=12588 VeraCrypt-x64.exe  /volume … /letter Q …
13:55:49.345 + pid=8392  padre=17220 VeraCrypt-x64.exe  /q UAC /volume …
13:55:51.070 - pid=8392
13:55:51.440 - pid=17220
```

`_esperar_copia_elevada()` vio la copia con el nombre nuevo: el montaje empieza
0,4 s **después** de que termine la copia elevada, no al salir el proceso
propio (75 s antes). El `.hc` tiene como última escritura 13:55:46.

Hallazgo **P-2** (de VeraCrypt, no nuestro): la contraseña va en la línea de
órdenes (`/password …`) del proceso que lanzamos **y** de su copia elevada, y
cualquier proceso del mismo usuario la lee (WMI `CommandLine`). En Windows no
hay otra vía no interactiva (sin stdin ni fichero de contraseña en su CLI).
Dura lo que tarda en crear y montar. Solo en el asistente: el vestíbulo y el
agente no pasan contraseña.

## V5 — `--update-components` con la unidad casi llena: OK

Montaje: una copia del repo con `pins.VERACRYPT_VERSION = "1.26.99"` (mismo
SHA-256) y el paquete real dejado a mano en la caché como
`VeraCrypt Portable 1.26.99.exe` (lo adopta `adoptar()`, sin red). Q: montada,
`python prdrive-install.py --update-components Q:\`. El relleno se hizo con
`fsutil file createnew G:\relleno-v5.bin` hasta dejar 20 MB: en exFAT **escribe
los ceros** (113 GiB, una hora); recortarlo después con `SetLength` es
instantáneo.

| Caso | Resultado |
|---|---|
| 20 MB libres | «No cabe VeraCrypt en G:\: hacen falta unos 29 MB y quedan 20 MB libres. No se ha tocado nada…», `FALLO`, rc 1. Sin `.VeraCrypt.nuevo-*`, los 15 ficheros con el mismo hash que antes |
| 35 MB libres | `hecho 1.26.24 → 1.26.99`, rc 0. `verificada(G:\VeraCrypt, "1.26.99")` True, `pendientes()` vacío, sin `.viejo`/`.nuevo`, el mismo espacio libre que antes |
| `G:\VeraCrypt\VeraCrypt-x64.exe` abierto, vuelta a 1.26.24 | `POSPUESTO … está en uso`, el sello sigue en 1.26.99 |
| Cerrado | `hecho 1.26.99 → 1.26.24`, verificada |

La mezcla vieja/nueva no llegó a verse en ningún momento: lo que había en la
carpeta era siempre una versión entera o la otra. La ventana entre los dos
`os.replace` no se forzó.

Nota: con un componente pospuesto la salida acaba en «Hecho.» y rc 0; solo el
`FALLO` da rc 1.

## Expulsar con el Portable (de paso): OK, con un hallazgo

01/10: `G:\Expulsar PRDRIVE.bat` con doble clic, sin quitar la unidad. Q: ya
no está y `PRDRIVE.hc` se abre en exclusiva (libre).

Hallazgo **P-3**: el driver del Portable **sigue cargado** después de expulsar.
- El servicio `veracrypt` sigue RUNNING, con `Start = 4` y `ImagePath` en la
  caché (`…\prdrive-install\veracrypt\1.26.24\veracrypt-x64.sys`).
- Lo cargó el `VeraCrypt-x64.exe` de la caché al montar en el asistente con
  `/quit`, y ese proceso salió con el volumen montado. El que desmonta (el de
  `G:\VeraCrypt\`) no lo cargó, así que no lo descarga.
- Queda cargado hasta reiniciar. Con `Start = 4` no debería volver a cargarse
  al arrancar; falta comprobar si la clave del servicio sobrevive al reinicio.
- Consecuencia probable: instalar después un VeraCrypt de otra versión pide
  reiniciar, y es la misma familia de problemas que P-1.

## V4 — NO HECHA

Pospuesta a petición del usuario (01/10): no se instaló ningún VeraCrypt. El
plan sigue siendo el de #50:
1. instalar un VeraCrypt de otra versión (reiniciando si lo pide, por P-3);
2. `Abrir PRDRIVE.bat` usa el instalado y monta sin `ERR_DRIVER_VERSION`;
3. el asistente («Reinstalar desde cero» → VeraCrypt) ofrece el instalado y no
   el Portable.

Va la última porque deja un VeraCrypt instalado en el equipo.
