# Plan de pruebas en Windows: VeraCrypt con la unidad G:

Fecha: 2026-09-24 · Rama: `claude/veracrypt-functionality-review-rm91gr` ·
Versión del programa: 0.2.5

Este documento es para un **agente con acceso a un equipo Windows** y a una unidad
USB en `G:` que **no contiene nada de valor y se puede reformatear las veces que
haga falta**. El objetivo es probar en un equipo real lo que en la rama solo se
ha podido probar con pruebas unitarias en Linux: el cifrado con VeraCrypt de
principio a fin.

Antes de empezar, lee:

- `docs/superpowers/specs/2026-09-23-veracrypt-ciclo-de-vida-design.md`: qué se
  cambió, por qué, y la tabla de hechos verificados en el código de VeraCrypt
  (se citan aquí como «hecho #N»).
- `AGENTS.md`, secciones «VeraCrypt: what not to weaken», «The vestibule» y
  «Mount watcher».

## 0. Cómo se trabaja

- **Esto es probar, no programar.** No cambies código de la rama. Si algo falla,
  apúntalo con la evidencia y la hipótesis de dónde está el fallo (fichero y
  función), y sigue con lo demás. Si un fallo impide seguir, para y pregunta.
- **Lo esperado viene del código, y la realidad manda.** Si lo que ves no es lo
  que dice este plan, lo que vale es lo que ves: apúntalo como discrepancia, no lo
  «arregles» ni reinterpretes el plan para que cuadre.
- **Hay pasos que solo puede hacer la persona.** Tú no puedes aceptar un aviso
  de UAC, escribir en el diálogo de contraseña de VeraCrypt, hacer clic en el
  asistente de instalación ni desenchufar la unidad. Cuando toque, pídelo así, y
  espera a que conteste antes de seguir:

  > **ACCIÓN HUMANA (prueba F2):** en la ventana de VeraCrypt que acaba de
  > aparecer, escribe la contraseña `prdrive-prueba-no-real-2026` y pulsa
  > Aceptar. Dime cuándo lo has hecho y qué ha pasado.

- **No hagas commit ni push** de nada. El informe (sección 6) se deja como
  fichero y la persona decide.
- Usa **PowerShell** en todo lo que sea tuyo. Los ejemplos lo suponen.

## 1. Reglas de seguridad: no se negocian

1. **Solo `G:`.** Ninguna orden que escriba, formatee o monte puede apuntar a
   otra unidad. Antes de **cada** formateo, reparticionado o creación de un
   contenedor, ejecuta la comprobación de identidad de la sección 2.3 y **para**
   si no cuadra (la letra `G:` puede haber pasado a otro disco al desenchufar y
   enchufar).
2. **Nada de `diskpart clean`, `Clear-Disk` ni reparticionar** salvo en la
   prueba A y con permiso explícito de la persona para ese paso, dado después de
   enseñarle el número de disco y su modelo.
3. **No toques nada real de la persona:**
   - su remoto (el NAS o lo que sea) ni su catálogo: las pruebas usan un remoto
     local en `C:\prdrive-pruebas` (sección 2.4);
   - su dispositivo prdrive de verdad, si lo tiene: que **no** esté enchufado
     durante las pruebas;
   - el fichero `prdrive-profile.toml` y la carpeta `keys/` del checkout, si
     existen: no se editan ni se borran;
   - la configuración de VeraCrypt (`%APPDATA%\VeraCrypt\*.xml`) ni sus
     favoritos;
   - su vigilante (`penwatch`) si ya tiene uno instalado: ver 2.5.
4. **VeraCrypt: solo la letra de la prueba.** Para desmontar a la fuerza, siempre
   con letra: `& $vc /dismount X /force /quit /silent`. **Nunca** `/dismount` sin
   letra: cerraría también los volúmenes de la persona.
5. **Contraseñas de prueba**, que no son de nadie:
   - larga: `prdrive-prueba-no-real-2026` (27 caracteres);
   - corta, para la prueba del aviso: `corta123`.
6. Al terminar, la sección 5 (limpieza) es obligatoria aunque las pruebas se
   hayan quedado a medias.

## 2. Preparación

### 2.1 El código

```powershell
cd <ruta del checkout de prdrive>
git fetch origin claude/veracrypt-functionality-review-rm91gr
git checkout claude/veracrypt-functionality-review-rm91gr
git pull
git log --oneline -6
git status
```

En el log tienen que estar, entre otros: «VeraCrypt, fase 2: el programa sabe que
va cifrado», «fase 1: el vestíbulo…», «fase 0: lo que estaba roto…» y «Spec:
VeraCrypt del día de la instalación a todos los días». `git status` tiene que
salir limpio; si no, pregunta antes de cambiar de rama.

### 2.2 El entorno

Apunta todo esto en el informe:

```powershell
[Environment]::OSVersion.Version; (Get-CimInstance Win32_OperatingSystem).Caption
$env:PROCESSOR_ARCHITECTURE                # AMD64 o ARM64
py -3 --version                            # 3.11 o superior
py -3 -c "import tkinter; print(tkinter.TkVersion)"
$vc = "$env:ProgramFiles\VeraCrypt\VeraCrypt.exe"
(Get-Item $vc).VersionInfo.ProductVersion  # la versión de VeraCrypt instalada
Get-Process VeraCrypt -ErrorAction SilentlyContinue   # ¿está en segundo plano?
```

- Hace falta **Python 3.11+ con Tk** y **VeraCrypt instalado** en su sitio
  normal. Si falta algo, para y díselo a la persona.
- Si VeraCrypt ya está corriendo en segundo plano (icono en la bandeja), apúntalo:
  cambia el resultado de la prueba H.

### 2.3 La identidad de G:

La primera vez, guarda qué disco es `G:`. Se identifica el **disco** (modelo,
número de serie, tamaño), no el volumen: el número de serie del volumen cambia
con cada formateo.

```powershell
New-Item -ItemType Directory -Force C:\prdrive-pruebas | Out-Null

function Get-IdentidadG {
    $ld = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='G:'"
    if (-not $ld) { throw "No hay unidad G:" }
    $part = Get-CimAssociatedInstance -InputObject $ld -ResultClassName Win32_DiskPartition |
            Select-Object -First 1
    $disco = Get-CimAssociatedInstance -InputObject $part -ResultClassName Win32_DiskDrive
    $ldC = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$env:SystemDrive'"
    $partC = Get-CimAssociatedInstance -InputObject $ldC -ResultClassName Win32_DiskPartition |
             Select-Object -First 1
    $discoC = Get-CimAssociatedInstance -InputObject $partC -ResultClassName Win32_DiskDrive
    [pscustomobject]@{
        Modelo      = $disco.Model
        Serie       = "$($disco.SerialNumber)".Trim()
        Tamano      = [int64]$disco.Size
        Interfaz    = $disco.InterfaceType
        IndiceDisco = $disco.Index
        EsElDelSistema = ($disco.Index -eq $discoC.Index)
        TipoUnidad  = $ld.DriveType          # 2 = extraíble, 3 = fija
        Sistema     = $ld.FileSystem
    }
}

$g = Get-IdentidadG
$g | Format-List
if ($g.EsElDelSistema -or $g.Interfaz -ne "USB") { throw "G: NO es un USB aparte del sistema: PARA" }
$g | Select-Object Modelo, Serie, Tamano, IndiceDisco |
     ConvertTo-Json | Set-Content C:\prdrive-pruebas\g-identidad.json
```

**Enséñale a la persona** el modelo y el tamaño y pídele que confirme que es la
unidad de pruebas. Después, antes de cada operación destructiva:

```powershell
function Confirmar-G {
    $antes = Get-Content C:\prdrive-pruebas\g-identidad.json | ConvertFrom-Json
    $ahora = Get-IdentidadG
    if ($ahora.EsElDelSistema -or $ahora.Interfaz -ne "USB" -or
        $ahora.Modelo -ne $antes.Modelo -or $ahora.Serie -ne $antes.Serie -or
        $ahora.Tamano -ne $antes.Tamano) {
        throw "G: ya no es la unidad de pruebas. PARA y pregunta."
    }
    "G: confirmada: $($ahora.Modelo), $([math]::Round($ahora.Tamano/1GB,1)) GB"
}
```

**Formatear `G:`** (siempre después de `Confirmar-G`). `Format-Volume` necesita
PowerShell como administrador. Si el tuyo no lo es, pídeselo a la persona (que
ejecute la línea en «Terminal (Administrador)» o formatee desde el Explorador:
clic derecho en G: → Formatear…):

```powershell
Confirmar-G
Format-Volume -DriveLetter G -FileSystem exFAT -NewFileSystemLabel PRPRUEBA -Confirm:$false
# FileSystem: exFAT | NTFS | FAT32   (FAT32 solo si G: es de 32 GB o menos)
```

### 2.4 Un remoto de pruebas, en C:

El asistente necesita un remoto con un catálogo. Se usa un remoto `alias` de
rclone que apunta a una carpeta local, para que **nada** salga del equipo ni
toque el remoto de la persona:

```powershell
$remoto = "C:\prdrive-pruebas\remoto"
New-Item -ItemType Directory -Force "$remoto\prdrive-catalog", "$remoto\datos\prueba" | Out-Null
# WriteAllText escribe UTF-8 SIN BOM en cualquier PowerShell; Set-Content en
# Windows PowerShell 5.1 pondría un BOM, y tomllib no lo acepta.
$catalogo = @'
[defaults]
remote = "pruebas"

[[pair]]
name = "prueba"
local = "sync-data/prueba"
remote_path = "/datos/prueba"
mode = "bisync"
'@
[IO.File]::WriteAllText("$remoto\prdrive-catalog\pairs.toml", $catalogo)

# Datos para sincronizar: 200 ficheros pequeños y uno de 300 MB, para que una
# pasada dure lo bastante como para desenchufar en mitad (prueba H3).
1..200 | ForEach-Object { "fichero $_" | Set-Content "$remoto\datos\prueba\f$_.txt" }
$f = [IO.File]::Create("$remoto\datos\prueba\grande.bin"); $f.SetLength(300MB); $f.Close()
```

En el asistente (paso «Conexión»), la persona tendrá que poner:

- Nombre del remote: `pruebas` · Tipo: `alias`
- Opciones (una por línea, como en rclone.conf): `remote = C:\prdrive-pruebas\remoto`
- Catálogo: el que viene, `/prdrive-catalog/pairs.toml`

**Ojo:** si el checkout tiene un `prdrive-profile.toml`, el asistente abre con la
conexión REAL de la persona precargada. Avísala de que la sustituya por la de
prueba, y comprueba en el paso «Comprobaciones» que el catálogo leído es
`pruebas:/prdrive-catalog/pairs.toml` con la pareja `prueba`. Si sale su catálogo
real, **para**.

Si hay un `rclone` en el PATH, comprueba antes que el alias resuelve bien:

```powershell
@"
[pruebas]
type = alias
remote = $remoto
"@ | Set-Content C:\prdrive-pruebas\rclone-pruebas.conf
rclone --config C:\prdrive-pruebas\rclone-pruebas.conf lsf pruebas:/prdrive-catalog/
# tiene que listar pairs.toml
```

### 2.5 El vigilante que ya hubiera

```powershell
py -3 penwatch.py status
```

- Si dice que no hay nada instalado, la prueba J puede instalar uno y quitarlo
  al final.
- Si **ya hay uno** (para el dispositivo real de la persona), `penwatch install`
  lo sustituiría y `penwatch uninstall` borraría su carpeta entera. **Pregunta
  antes.** Si la persona da permiso, guarda primero:

  ```powershell
  Copy-Item -Recurse "$env:LOCALAPPDATA\PrDriveWatch" C:\prdrive-pruebas\vigilante-original
  schtasks /Query /TN PrDriveWatch /XML | Out-File -Encoding unicode C:\prdrive-pruebas\vigilante-original.xml
  ```

  y la limpieza (sección 5) lo restaura. Sin permiso, la prueba J se salta.

### 2.6 La batería automática, en Windows

Hasta ahora solo se ha pasado en Linux. Es la primera prueba y la más barata:

```powershell
py -3 tests\run_all.py *> C:\prdrive-pruebas\run_all.txt
Get-Content C:\prdrive-pruebas\run_all.txt -Tail 5
```

Las pruebas no tocan ningún dispositivo ni la red, y desvían a carpetas
temporales todo lo del vigilante (`%LOCALAPPDATA%` incluido). Si aun así alguna
abre VeraCrypt, escribe en `G:` o toca `%LOCALAPPDATA%\PrDriveWatch`, **para**:
eso ya es un hallazgo.

Esperado: todo en verde. En Linux falla `test_tk_densidad.py` por un píxel de
redondeo con la escala al 200 % (ya fallaba antes de esta rama); si en Windows
también falla, apúntalo igual. **Cualquier otro fallo es un hallazgo**, sobre
todo en `test_vestibulo.py`, `test_penwatch_vestibulo.py`, `test_traveler.py`,
`test_crypto_veracrypt.py`, `test_install_wizard.py` y `test_tk_principal.py`.
Copia la salida del que falle en el informe.

## 3. Ayudantes para las pruebas

Desde la raíz del checkout, para usar las funciones del programa sin el
asistente:

```powershell
function PyPr([string]$codigo) { py -3 -c $codigo }

# El VeraCrypt de este equipo, como lo encuentra el instalador
PyPr "from install import crypto; print(crypto.find_veracrypt())"
```

Encontrar la unidad donde está montado el contenedor de la prueba, por el id del
dispositivo (el mismo que usan los lanzadores):

```powershell
function Buscar-Montado([string]$id) {
    foreach ($l in [char[]]"CDEFHIJKLMNOPQRSTUVWXYZAB") {
        $c = "${l}:\.prdrive\PRDRIVE"
        if ((Test-Path -LiteralPath $c) -and
            (Select-String -LiteralPath $c -Pattern "^id=$id" -Quiet)) { return "${l}:" }
    }
}
# El id se lee de la marca de fuera, que está oculta:
function Id-Vestibulo { (Get-Content -Force G:\.prdrive-vestibulo |
                         Where-Object { $_ -like "id=*" }) -replace "^id=", "" }
```

## 4. Las pruebas

Cada prueba dice qué comprueba, los pasos, lo esperado y la evidencia a guardar.
Orden recomendado: A–D (mayormente tuyas, sin asistente), E (asistente, con la
persona), F–M (encima de lo que deja E), N opcional. Entre bloques, desmonta lo
que quede montado de la prueba anterior (con letra).

### A. Unidad FAT32: el tope de 4095 MiB (fase 0, hechos 9)

Solo si `G:` es de **32 GB o menos** (Windows no formatea FAT32 por encima). Si
es mayor, pregunta a la persona si quiere reparticionarla con una partición de
16 GB (regla 1.2); si no, marca A como NO PROBADA.

1. `Confirmar-G`; formatea `G:` en **FAT32**.
2. Comprueba lo que ve el programa:
   ```powershell
   PyPr "from install import crypto; fs=crypto.sistema_de_ficheros('G:\\'); print(fs, crypto.tope_contenedor(fs), crypto.soporta_dispersos('G:\\'))"
   ```
   Esperado: `FAT32 4293918720 False`.
3. Un tamaño por encima del tope se rechaza **sin lanzar VeraCrypt**:
   ```powershell
   PyPr "from pathlib import Path; from install import crypto; vc=crypto.find_veracrypt(); crypto.create_container(vc, Path('G:/PRDRIVE.hc'), 5*1024**3, 'prdrive-prueba-no-real-2026', 'exFAT')"
   Test-Path G:\PRDRIVE.hc
   ```
   Esperado: `InstallError` que dice «4095M o menos» y «exFAT o NTFS», y
   `Test-Path` → `False`.
4. **Justo en el tope** (el hecho 9: VeraCrypt redondea `/size` hacia arriba al
   sector; 4 GiB − 1 fallaría y 4095 MiB no). Tarda: escribe 4 GB enteros en el
   USB. Cronométralo.
   ```powershell
   Measure-Command { PyPr "from pathlib import Path; from install import crypto; vc=crypto.find_veracrypt(); crypto.create_container(vc, Path('G:/PRDRIVE.hc'), 4095*1024**2, 'prdrive-prueba-no-real-2026', 'exFAT')" }
   (Get-Item G:\PRDRIVE.hc).Length
   ```
   Esperado: se crea, y mide 4293918720 bytes (o un múltiplo de sector muy
   cercano; apunta el valor exacto). Si VeraCrypt pide permisos de
   administrador (puede pasar al dar formato exFAT dentro), es una ACCIÓN HUMANA.
5. Monta y desmonta con el propio programa, y mira qué hay dentro:
   ```powershell
   PyPr "from pathlib import Path; from install import crypto; vc=crypto.find_veracrypt(); p=crypto.mount_container(vc, Path('G:/PRDRIVE.hc'), 'prdrive-prueba-no-real-2026'); print(p)"
   # con la letra que salga, p. ej. P:
   Get-ChildItem -Force P:\
   PyPr "from pathlib import Path; from install import crypto; crypto.dismount(crypto.find_veracrypt(), Path('P:/'))"
   ```
   Esperado: monta; dentro **no** hay `System Volume Information` ni
   `$RECYCLE.BIN` (es lo que evita `/m rm`); el Explorador enseña la unidad con
   etiqueta PRDRIVE; desmonta sin error.

### B. Unidad exFAT: sin dispersos, contenedor fijo

1. `Confirmar-G`; formatea en **exFAT**.
2. ```powershell
   PyPr "from install import crypto; print(crypto.sistema_de_ficheros('G:\\'), crypto.tope_contenedor(crypto.sistema_de_ficheros('G:\\')), crypto.soporta_dispersos('G:\\'))"
   ```
   Esperado: `exFAT None False` (exFAT no tiene tope ni dispersos).
3. Crea uno pequeño (512M) y cronométralo; mide también la estimación del
   programa:
   ```powershell
   PyPr "from install import crypto; print(crypto.describir_espera(crypto.estimar_creacion('G:\\', 512*1024**2)))"
   Measure-Command { PyPr "from pathlib import Path; from install import crypto; crypto.create_container(crypto.find_veracrypt(), Path('G:/PRDRIVE.hc'), 512*1024**2, 'prdrive-prueba-no-real-2026', 'exFAT')" }
   ```
   Apunta la estimación y el tiempo real: la estimación tiene que ser del mismo
   orden.

### C. Unidad NTFS: contenedor dinámico (disperso)

1. `Confirmar-G`; formatea en **NTFS**.
2. `crypto.soporta_dispersos('G:\\')` → esperado `True`.
3. Crea uno dinámico con casi todo el hueco y cronométralo:
   ```powershell
   Measure-Command { PyPr "from pathlib import Path; from install import crypto; free=__import__('shutil').disk_usage('G:\\').free; crypto.create_container(crypto.find_veracrypt(), Path('G:/PRDRIVE.hc'), crypto.size_to_bytes('max', free), 'prdrive-prueba-no-real-2026', 'exFAT', dinamico=True)" }
   fsutil sparse queryflag G:\PRDRIVE.hc
   PyPr "from common import vestibulo; print(vestibulo.disperso('G:/PRDRIVE.hc'))"
   ```
   Esperado: segundos, no minutos, sea cual sea el tamaño; `fsutil` dice que es
   disperso; `disperso()` → `True`. (Si `fsutil` pide administrador, basta con
   `disperso()`.)
4. Borra el `.hc` para la prueba siguiente.

### D. El VeraCrypt que viaja (traveler), en este equipo (hechos 1–3)

Con `G:` en cualquier formato:

```powershell
PyPr "from pathlib import Path; from install import crypto, traveler; vc=crypto.find_veracrypt(); print([str(p) for p in traveler.instalar(vc, Path('G:/'))]); print(traveler.arquitecturas(Path('G:/VeraCrypt'))); [print(k) for k in traveler.comprobar(Path('G:/'))]"
Get-ChildItem G:\VeraCrypt
Get-AuthenticodeSignature G:\VeraCrypt\veracrypt-*.sys | Format-List Status, SignerCertificate
Get-FileHash "$env:ProgramFiles\VeraCrypt\veracrypt.sys", G:\VeraCrypt\veracrypt-*.sys
```

Esperado:

- En `G:\VeraCrypt\` hay `VeraCrypt.exe`, `VeraCrypt Format.exe`,
  `VeraCryptExpander.exe`, la licencia y **`veracrypt-x64.sys`** (o
  `veracrypt-arm64.sys` en un Windows ARM). **No** un `veracrypt.sys` a secas.
- `arquitecturas()` → `['x64']` (o `['arm64']`), y `comprobar()` dice «en un
  Windows ARM no monta (un driver no se emula)» (o al revés).
- La firma del `.sys` copiado es **Valid** y su hash es **idéntico** al del
  `veracrypt.sys` instalado: es el mismo binario, renombrado.

Si en la carpeta instalada no hay `veracrypt.sys` sino ya `veracrypt-x64.sys`,
apúntalo: contradice el hecho 1 para esa versión de VeraCrypt.

Que el traveler **monte** de verdad solo se puede probar en un equipo sin
VeraCrypt instalado: es la prueba N.

### E. El asistente completo con VeraCrypt (con la persona)

Deja el dispositivo que usan las pruebas F–M.

1. `Confirmar-G`; formatea en **NTFS** (así la casilla «Contenedor dinámico»
   está disponible y la creación es rápida).
2. Lanza el asistente: `py -3 prdrive-install.py`.
3. **ACCIÓN HUMANA**, paso a paso. Pídele a la persona que te cuente lo que ve en
   cada paso, y apúntalo:
   - **Dispositivo:** elegir `G:`.
   - **Cifrado:** VeraCrypt. Comprobar que el panel **no** enseña el recuadro rojo
     de «instalación SIN CIFRAR» (G: está recién formateada) ni la pista de
     FAT32; que «Contenedor dinámico: solo ocupa lo que guardes» está marcada;
     que «Dejar VeraCrypt en el dispositivo, para montarlo en equipos que…»
     está marcada. Escribir primero la contraseña
     **corta** (`corta123`) en los dos campos y pulsar «Crear y montar».
     Esperado: **pregunta** «La contraseña tiene menos de 20 caracteres…
     ¿Seguir con esta contraseña?», con «No» por defecto. Responder No; no se crea nada. Después
     escribir la larga y crear. Puede aparecer UAC.
   - **Conexión:** la de pruebas de 2.4 (¡no la real!).
   - **Comprobaciones:** tiene que leer el catálogo con la pareja `prueba`.
   - **Instalación:** el texto tiene que decir que fuera del contenedor quedará
     «la entrada para abrirlo y cerrarlo en cualquier equipo: «Abrir PRDRIVE»,
     «Expulsar PRDRIVE»…». Plataforma: la de este equipo, completa. Instalar.
   - **Parejas:** marcar `prueba`.
   - **Inicialización:** el `--resync` de `prueba` (copia los 201 ficheros).
   - **Verificación:** anotar TODAS las filas. Esperado en verde: «Entrada del
     dispositivo», «VeraCrypt portátil», «Driver de VeraCrypt» (con la
     arquitectura) y «VeraCrypt Expander»; **no** tiene que haber fila
     «Instalación sin cifrar». Y **no** tiene que existir el botón «Que VeraCrypt
     monte al conectar» (se quitó en la fase 0).
4. Con el contenedor todavía montado, comprueba tú:
   ```powershell
   Get-ChildItem -Force G:\          # raíz FÍSICA
   $id = Id-Vestibulo; $id
   $x = Buscar-Montado $id; $x       # la letra de lo montado
   Get-Content "$x\.prdrive\PRDRIVE"
   Get-ChildItem -Force "$x\"        # dentro del contenedor
   (Get-Item -Force G:\.prdrive-vestibulo).Attributes
   Get-Content G:\autorun.inf
   Format-Hex "G:\Abrir PRDRIVE.bat" | Select-Object -First 3
   ```
   Esperado:
   - En `G:\`: `PRDRIVE.hc`, `VeraCrypt\`, `Abrir PRDRIVE.bat`,
     `Expulsar PRDRIVE.bat`, `abrir-prdrive.sh`, `expulsar-prdrive.sh`,
     `LEEME-PRDRIVE.txt`, `.prdrive-vestibulo` (atributo **Hidden**) y
     `autorun.inf`. **Nada** de `.prdrive\` ni de `runsync.bat` fuera.
   - El `id=` de la marca de fuera es **el mismo** que el de
     `.prdrive\PRDRIVE` de dentro.
   - Dentro: `.prdrive\`, `runsync.bat`, `runsync.sh`, `README.md`,
     `sync-data\prueba\` con los 201 ficheros.
   - `autorun.inf`: `shell\montar\command=VeraCrypt\VeraCrypt.exe /q /m rm /v "PRDRIVE.hc"`
     y `shell\desmontar\command=VeraCrypt\VeraCrypt.exe /q /dismount`.
   - El `.bat` empieza por `@echo off` sin BOM (los primeros bytes son `40 65 63`)
     y tiene saltos de línea CRLF (`0D 0A`).
   - `LEEME-PRDRIVE.txt` se lee bien en el Bloc de notas (acentos incluidos).
5. **ACCIÓN HUMANA:** en el paso 8, «Desmontar el contenedor». Luego cerrar el
   asistente.

### F. «Abrir PRDRIVE» (fase 1)

Parte de: contenedor cerrado (`Buscar-Montado $id` no devuelve nada).

- **F1, abrir.** Lánzalo tú: `Start-Process "G:\Abrir PRDRIVE.bat"`.
  **ACCIÓN HUMANA:** escribir la contraseña en la ventana de VeraCrypt.
  Esperado: aparece la consola del `.bat` («Abriendo PRDRIVE: escribe la
  contrasena en la ventana de VeraCrypt.», sin tilde a propósito); VeraCrypt pide
  la contraseña en SU ventana; al aceptar, en pocos segundos se abre la ventana
  de prdrive y la consola se cierra sola. `Buscar-Montado $id` devuelve la letra.
  Comprueba también que la contraseña **no** aparece en la línea de órdenes de
  ningún proceso mientras la pide:
  ```powershell
  Get-CimInstance Win32_Process -Filter "Name='VeraCrypt.exe'" | Select-Object CommandLine
  ```
  Esperado: `/volume "G:\PRDRIVE.hc" /mountoption rm /mountoption label=PRDRIVE /history n /cache n /quit`, sin `/password`.
- **F2, ya abierto.** Con la ventana de prdrive abierta, lanza otra vez el
  `.bat`. Esperado: **no** pide contraseña ni monta otra vez; runsync dice que
  ya hay una ventana abierta. Pídele a la persona que cierre la ventana de
  prdrive (no expulsar todavía).
- **F3, cancelar.** Desmonta con letra (`& $vc /dismount X /force /quit /silent`),
  lanza el `.bat` y **ACCIÓN HUMANA:** Cancelar en la ventana de VeraCrypt.
  Esperado: en ~1 s la consola dice «El contenedor no se ha abierto…» y espera
  una tecla.
- **F4, lector de tarjetas.** Si el equipo tiene un lector de tarjetas u otra
  unidad extraíble **vacía**, repite F1 y pregunta a la persona si ha salido algún
  diálogo de Windows de «No hay disco en la unidad». Esperado: ninguno. (No está
  verificado: el `.bat` recorre las letras con `if exist`.)
- **F5, cuánto tarda en encontrarla.** Apunta cuánto pasa desde que se acepta la
  contraseña hasta que se abre la ventana de prdrive.

### G. «Expulsar» (fase 2)

Parte de: contenedor abierto con F1 y ventana de prdrive abierta.

- **G1, botón de la ventana.** **ACCIÓN HUMANA:** en el pie de la ventana tiene
  que haber un botón **«Expulsar»** (con un icono de triángulo sobre una barra).
  Pulsarlo → confirmación → Aceptar. Esperado: la ventana se cierra; se abre una
  consola que dice «Cerrando PRDRIVE…» y a los pocos segundos «PRDRIVE está
  cerrado. Ya puedes quitar la unidad.»; `Buscar-Montado $id` ya no encuentra
  nada. Después, **ACCIÓN HUMANA:** «Quitar hardware de forma segura» para
  `G:`. Esperado: Windows deja quitarla (no dice «en uso»).
- **G2, cancelar la confirmación.** Abre otra vez (F1), pulsa «Expulsar» y
  Cancelar. Esperado: no pasa nada y la ventana sigue abierta.
- **G3, apagado mientras sincroniza.** Pulsa «Sincronizar ahora» y, mientras
  corre, mira el botón «Expulsar». Esperado: apagado hasta que termina la
  pasada.
- **G4, algo abierto dentro.** Con el contenedor abierto y la ventana cerrada,
  deja un fichero abierto desde otro proceso y lanza `Expulsar PRDRIVE.bat`:
  ```powershell
  $h = [IO.File]::Open("$x\sync-data\prueba\f1.txt", 'Open', 'Read', 'None')
  Start-Process "G:\Expulsar PRDRIVE.bat"
  ```
  Esperado: VeraCrypt **pregunta** (su ventana) si forzar el desmontaje. Pídele a
  la persona que diga No; a los ~30 s la consola tiene que decir «El contenedor
  sigue abierto en X:. ¿Queda algún programa usando la unidad?…». Luego `$h.Close()` y vuelve a lanzar el `.bat`: esta vez cierra.
- **G5, ya cerrado.** Lanza `Expulsar PRDRIVE.bat` con el contenedor cerrado.
  Esperado: «PRDRIVE ya estaba cerrado…».
- **G6, sin contenedor.** En un equipo o sesión donde el dispositivo no vive en
  un contenedor (p. ej. tras la prueba K, sin cifrar), la ventana **no** tiene
  que enseñar «Expulsar».

### H. Desconectar SIN expulsar (la pregunta abierta)

Es lo que decide el siguiente cambio de código. **Solo observar y apuntar.** Las
predicciones salen del código de VeraCrypt (`Mount/Mount.c`, `WM_DEVICECHANGE`)
y no se han visto pasar.

- **H1, sin VeraCrypt en segundo plano.**
  1. `Get-Process VeraCrypt` no tiene que devolver nada; si lo hay, pídele a la
     persona que salga de VeraCrypt desde el icono de la bandeja («Salir»).
  2. Abre con F1, cierra la ventana de prdrive (sin expulsar).
  3. **ACCIÓN HUMANA:** desenchufar la unidad USB tal cual.
  4. Apunta: ¿sigue la letra del contenedor en el Explorador o en
     `Get-PSDrive -PSProvider FileSystem`? ¿Algún aviso de Windows («escritura
     retrasada», etc.)? Si la persona abre VeraCrypt, ¿lo lista como montado?
  5. **ACCIÓN HUMANA:** volver a enchufarla. Comprueba que vuelve a ser `G:` y
     `Confirmar-G`. Lanza `Abrir PRDRIVE.bat`.
  6. **Predicción:** VeraCrypt dice «El volumen ya está montado» y no pide
     contraseña; la consola acaba en «El contenedor no se ha abierto…», que
     **no** es la causa real. Apunta exactamente qué pasa.
  7. Limpieza: con la letra que tuviera, `& $vc /dismount X /force /quit /silent`,
     o que la persona use «Desmontar todo» en VeraCrypt. Luego F1 tiene que
     volver a funcionar.
- **H2, con VeraCrypt en segundo plano.**
  1. `& $vc /q background` (se queda en la bandeja; si ya había uno, no pasa
     nada: solo puede haber uno).
  2. Abre con F1, cierra la ventana de prdrive, **ACCIÓN HUMANA:** desenchufar.
  3. **Predicción:** VeraCrypt cierra el volumen solo y enseña un globo que
     empieza por «Before you physically remove or turn off a device containing a
     mounted volume…» (o su traducción). La letra desaparece.
  4. **ACCIÓN HUMANA:** volver a enchufar; `Confirmar-G`; F1. Predicción: abre
     normal.
  5. Al terminar, pídele a la persona que salga de VeraCrypt desde la bandeja
     si antes no estaba en segundo plano.
- **H3, desenchufar en mitad de una pasada.** Con el contenedor abierto y la
  ventana de prdrive, **ACCIÓN HUMANA:** «Sincronizar ahora» y desenchufar
  mientras copia `grande.bin` (si hace falta, borra antes `grande.bin` del lado
  del dispositivo para que tenga que volver a copiarlo). Apunta todo lo que se
  vea. Vuelve a enchufar, abre (limpiando como en H1 si hace falta) y apunta:
  - ¿Windows ofrece «Examinar y reparar» para el volumen de dentro?
  - ¿Qué dice «Reparación»?
  - Pide «Sincronizar ahora» otra vez: ¿se recupera sola la pasada (bisync va
    con `--recover` y `--max-lock 2m`) o pide `--resync`? ¿Queda algún fichero a
    medias en `sync-data\prueba`?
  - ¿El contenedor se sigue abriendo con su contraseña? (Esperado: sí; VeraCrypt
    no reescribe la cabecera al usarlo).

### I. «Reparación» avisa del sitio de fuera (fase 2)

Necesita el dispositivo de E (contenedor **dinámico** en NTFS).

1. Con el contenedor abierto, llena la unidad física hasta dejar menos de 1 GiB
   libre. En NTFS, alargar un fichero reserva el sitio sin escribirlo:
   ```powershell
   $libre = (Get-PSDrive G).Free
   $f = [IO.File]::Create("G:\relleno.bin"); $f.SetLength($libre - 500MB); $f.Close()
   (Get-PSDrive G).Free / 1MB
   ```
   (`G:\relleno.bin` está FUERA del contenedor, en la raíz física.)
2. Abre la ventana de prdrive (con F1 o el `runsync.bat` de dentro). Esperado:
   el chip dice «1 que revisar» (o uno más de lo que hubiera), y «Reparación»
   enseña «El contenedor se queda sin sitio fuera», **sin botón**, con los MB
   libres y la raíz física.
3. Lo mismo por consola:
   ```powershell
   & "$x\.prdrive\runtime\windows-x64\python.exe" "$x\.prdrive\sync.py" --doctor
   ```
   (en ARM64, `runtime\windows-arm64`). Esperado: la misma avería al final.
4. Borra `G:\relleno.bin`, vuelve a abrir la ventana: la avería ya no está.

### J. El vigilante abre el contenedor al conectar (fase 2)

Solo si 2.5 lo permite.

1. Con el contenedor abierto, instálalo desde el dispositivo (o que la persona
   use «Arranque automático…» en la ventana):
   ```powershell
   py -3 "$x\.prdrive\penwatch.py" install
   py -3 "$x\.prdrive\penwatch.py" status
   ```
   Apunta el `Dispositivo esperado (id)`: tiene que ser el `$id` de antes.
2. Cierra la ventana de prdrive, expulsa (G1) y **ACCIÓN HUMANA:** desenchufar y
   volver a enchufar.
3. Esperado: en ~5–10 s aparece **sola** la ventana de contraseña de VeraCrypt.
   **ACCIÓN HUMANA:** escribirla. Esperado: a los pocos segundos se abre la
   ventana de prdrive. Mira el diario:
   ```powershell
   Get-Content "$env:LOCALAPPDATA\PrDriveWatch\penwatch.log" -Tail 20
   ```
   Tienen que salir «dispositivo cifrado detectado en G:\», «abriendo el
   contenedor de G:\ con …; la contraseña la pide VeraCrypt» y después
   «dispositivo detectado en X:\» y «runsync lanzado (pid …, modo ui)».
4. **Una vez por conexión:**
   - Cierra la ventana, «Expulsar», **y NO desenchufes**. Espera un minuto.
     Esperado: **no** vuelve a pedir la contraseña.
   - Desenchufa y enchufa; cuando pida la contraseña, **Cancelar**. Espera un
     minuto. Esperado: no la vuelve a pedir hasta volver a desenchufar y enchufar.
5. Con el contenedor cerrado y la unidad puesta:
   `py -3 "$env:LOCALAPPDATA\PrDriveWatch\penwatch.py" status` → «Dispositivo
   ahora mismo: cifrado y cerrado, en G:\», y `probe` → «dispositivo cifrado,
   cerrado (id …)» en la fila de `G:\`.
6. Al terminar: `py -3 "$env:LOCALAPPDATA\PrDriveWatch\penwatch.py" uninstall`
   (y la restauración de la sección 5 si había uno antes).

### K. Recifrar un dispositivo que iba sin cifrar (fase 0)

1. `Confirmar-G`; formatea en exFAT. Asistente completo **Sin cifrar**, con la
   conexión de pruebas y la pareja `prueba`, hasta el final. Cierra.
2. Vuelve a lanzar el asistente sobre `G:` → «Reinstalar desde cero» →
   **VeraCrypt**. Esperado, **antes** de crear nada: un recuadro **rojo** que dice
   que en la raíz sigue una instalación SIN CIFRAR y nombra `.prdrive/` y
   `sync-data/`, habla de la clave en claro y de cambiar la clave del remoto.
3. Crea el contenedor (contraseña larga) y sigue hasta el paso 8. Esperado: una
   fila roja «Instalación sin cifrar».
4. Comprueba que **nada** de la instalación sin cifrar se ha borrado
   (`G:\.prdrive\`, `G:\sync-data\prueba\` siguen ahí).

### L. Poner al día un dispositivo VeraCrypt «de antes» (fases 0 y 1)

Simula un dispositivo hecho con la versión anterior a partir del de E (o de K):

```powershell
Remove-Item -Force "G:\Abrir PRDRIVE.bat", "G:\Expulsar PRDRIVE.bat", G:\abrir-prdrive.sh, G:\expulsar-prdrive.sh, G:\LEEME-PRDRIVE.txt
Remove-Item -Force G:\.prdrive-vestibulo
Rename-Item G:\VeraCrypt\veracrypt-x64.sys veracrypt.sys   # como lo dejaba la versión anterior
```

1. Asistente sobre `G:` → Cifrado → VeraCrypt → «Montar» con la contraseña.
   Esperado: aparece el panel «ya es un dispositivo prdrive».
2. **«Añadir plataformas…»** → Aplicar. Esperado: vuelve a estar el vestíbulo
   entero en `G:\` con el **mismo** id de antes (`Id-Vestibulo`).
3. Paso 8 no está en este recorrido: comprueba el traveler con
   `traveler.comprobar(Path('G:/'))` (como en D). Esperado: la fila del driver dice
   que se copió como `veracrypt.sys` y pide pulsar «Llevar VeraCrypt en el
   dispositivo».
4. Vuelve a lanzar el asistente por el recorrido largo hasta el paso 8 (o
   ejecuta `traveler.instalar` como en D) y pulsa «Llevar VeraCrypt en el
   dispositivo». Esperado: aparece `veracrypt-x64.sys` y la fila pasa a verde.

### M. El `autorun.inf`

**ACCIÓN HUMANA:** con la unidad puesta, mirar en el Explorador:

- ¿La unidad se llama PRDRIVE y lleva el icono de VeraCrypt? (Esperado: sí.)
- Clic derecho en la unidad: ¿aparecen «Montar el volumen PRDRIVE» y «Desmontar
  todos los volúmenes»? **No está verificado**: puede que Windows los ignore en
  un extraíble. Si aparecen, probar «Montar»: tiene que pedir la contraseña de
  `PRDRIVE.hc` (antes solo abría la ventana de VeraCrypt).

### N. Opcional: el traveler en un equipo SIN VeraCrypt

Es la única forma de comprobar que el VeraCrypt que viaja carga su driver (hecho
2). Necesita un segundo PC con Windows de la **misma arquitectura** y sin
VeraCrypt instalado (o una máquina virtual con paso de USB). Desinstalar
VeraCrypt del equipo de pruebas también vale, pero **pregunta antes**.

1. Enchufa `G:` (del dispositivo de E) en ese equipo. Doble clic en
   «Abrir PRDRIVE». Esperado: UAC (el driver se carga como administrador) →
   contraseña → se abre prdrive con **su propio Python** (no hace falta Python
   instalado).
2. Expulsar desde la ventana. Después, «Quitar hardware de forma segura».
   **Observar:** ¿Windows deja quitar la unidad o dice que está en uso? (En modo
   portátil el driver se carga desde la propia unidad; no está verificado qué
   pasa con él al expulsar.)
3. Si ese equipo tiene **otra** versión de VeraCrypt instalada en vez de ninguna:
   esperado que «Abrir PRDRIVE» use la instalada y funcione.

## 5. Limpieza (obligatoria)

1. Desmonta, **con letra**, cualquier contenedor de prueba que siga abierto
   (`Buscar-Montado $id`), y comprueba que no queda ningún `VeraCrypt.exe` lanzado
   por las pruebas (H2 lo deja en segundo plano).
2. Vigilante: `py -3 "$env:LOCALAPPDATA\PrDriveWatch\penwatch.py" uninstall` si
   lo instalaste. Si había uno de antes (2.5):
   ```powershell
   Copy-Item -Recurse C:\prdrive-pruebas\vigilante-original "$env:LOCALAPPDATA\PrDriveWatch"
   schtasks /Create /TN PrDriveWatch /XML C:\prdrive-pruebas\vigilante-original.xml /F
   schtasks /Run /TN PrDriveWatch
   py -3 "$env:LOCALAPPDATA\PrDriveWatch\penwatch.py" status
   ```
   y comprueba con la persona que su vigilante vuelve a apuntar a su dispositivo
   real (el id de antes).
3. Borra `C:\prdrive-pruebas` **después** de copiar el informe y lo que quieras
   adjuntar.
4. `Confirmar-G` y deja `G:` formateada en exFAT, vacía.
5. `git status` en el checkout: solo tiene que aparecer el informe de la sección
   6 (y nada del código cambiado).

## 6. El informe

Escríbelo en
`docs/superpowers/pruebas/2026-09-24-veracrypt-unidad-g-resultados.md` (sin
commit), con:

1. **Entorno:** Windows y compilación, arquitectura, Python, VeraCrypt (versión
   y si estaba en segundo plano), modelo y tamaño de `G:`.
2. **Tabla de resultados:** una fila por prueba (A, B, C1…), con `OK`, `FALLO`,
   `DISCREPANCIA` (funciona, pero no como dice el plan) o `NO PROBADA` (y por
   qué), y una línea de observación.
3. **Hallazgos**, uno por uno: qué se hizo, qué se esperaba, qué pasó, la
   evidencia (salida literal de la orden, o lo que contó la persona) y dónde
   crees que está la causa (fichero y función). Si contradice un «hecho #N» de
   la spec, dilo.
4. **La prueba H en detalle:** qué pasó en H1, H2 y H3 frente a las predicciones.
   Es la entrada para decidir si prdrive deja VeraCrypt en segundo plano después
   de abrir el contenedor.
5. **Tiempos:** A4, B3, C3, F5.
6. **Lo que este plan tenía mal**: pasos que no se podían hacer tal cual,
   órdenes que no funcionaron, supuestos equivocados.
