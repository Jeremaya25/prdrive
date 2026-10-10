# El agente ve una unidad bloqueada con BitLocker

Fecha: 2026-10-10 · Estado: **implementado** (texto aprobado; plan en
`docs/superpowers/plans/2026-10-10-agente-bitlocker-bloqueada.md`) · Área:
`docs/agents/reference/agent.md`, `tray.md` · Sin probar en real: nada de esto ha
corrido con una unidad bloqueada de verdad (lista viva, sección «Una unidad
bloqueada con BitLocker»).

## Qué se pide

Que el agente residente sepa cuándo hay enchufada una unidad de prdrive bloqueada
con BitLocker.

Hoy no lo sabe. `Agente._recorrer()` intenta leer `.prdrive/PRDRIVE` en cada letra;
un volumen bloqueado contesta con un error (o con «no existe») y se salta: ni
bandeja, ni aviso, ni línea en el diario. La unidad solo aparece cuando alguien la
desbloquea desde el Explorador y un recorrido posterior la lee. Con VeraCrypt no
pasa, porque fuera del contenedor queda el vestíbulo con su marca; un volumen de
BitLocker bloqueado no enseña nada de lo que lleva dentro.

## Decidido con la persona

- **Qué hace el agente al verla:** la enseña en la bandeja como bloqueada, con una
  entrada «Desbloquear…» que saca la ventana de BitLocker de Windows. **Nunca pide
  la contraseña por su cuenta** (a diferencia del vestíbulo de VeraCrypt de una
  unidad de la lista, que sí se abre una vez por conexión). Desbloqueada, se
  atiende como siempre.
- **Cuáles:** solo las unidades que ya conoce. El agente recuerda el volumen de una
  unidad de la lista y la reconoce por él cuando vuelve bloqueada; de cualquier
  otro disco con BitLocker no dice nada. Una unidad no se reconoce bloqueada hasta
  que este equipo la ha atendido una vez desbloqueada.

## Supuestos (a corregir si no valen)

- Solo Windows. BitLocker en Linux (`cryptsetup` con `bitlk`, dislocker) queda
  fuera.
- Solo unidades que se enchufan. Una raíz de este equipo en un disco de datos con
  BitLocker bloqueado sigue como hoy («no está en su sitio»).
- Sin aviso: Windows ya anuncia la unidad bloqueada al enchufarla.
- Una unidad de la lista en modo `nada` no se enseña, igual que hoy no se abre su
  vestíbulo de VeraCrypt (`Agente._vestibulos()`).
- `penwatch.py` no cambia.
- **Nada cambia en ningún dispositivo.** Lo único que se escribe es un campo nuevo
  en el `agente.json` del equipo.

## Lo comprobado para este diseño

En el equipo de desarrollo (Windows 11 Home ARM64), solo leyendo y solo sobre `C:`:

- El Explorador desbloquea con el verbo `unlock-bde` de
  `HKCR\Drive\shell`, cuya orden es `%SystemRoot%\System32\bdeunlock.exe %1` y cuyo
  `AppliesTo` es `System.Volume.BitLockerProtection:=6`: la misma propiedad que lee
  `common/bitlocker.py` y el mismo valor que `BDE_LOCKED`. `bdeunlock.exe` existe
  también en la edición Home.
- `GetVolumeNameForVolumeMountPointW("C:\\")` contesta sin elevar en 0,5 ms.
- `bitlocker.bitlocker_status("C")` tarda 59 ms la primera vez y unos 2 ms las
  siguientes.

Lo que **no** se ha podido comprobar está en «Pruebas → En real».

## Diseño

### 1. Recordar el volumen (`common/equipo.py`, `common/bitlocker.py`, `agente.py`)

`equipo.Unidad` gana `volumen: str = ""`: el nombre de volumen de Windows
(`\\?\Volume{GUID}\`) donde este equipo atendió la unidad por última vez con
BitLocker puesto. Es el último campo, así que las construcciones por posición que
hay no cambian.

- **Por qué ese nombre:** lo da el gestor de montajes, no el sistema de ficheros,
  así que se lee igual con el volumen bloqueado; no pide elevar; es una llamada de
  `kernel32`. Se descartan el número de serie USB (identifica el aparato y no el
  volumen, y pide más `ctypes`) y el identificador propio de BitLocker (`manage-bde`
  y WMI piden elevar, que es lo que `common/bitlocker.py` existe para evitar).
- **`bitlocker.volumen_de(raiz) -> str`** (nueva, de módulo, sustituible): el nombre
  de volumen de una raíz `X:\`, en minúsculas; cadena vacía fuera de Windows, si la
  ruta no es la raíz de una letra o si Windows no contesta. No lanza.
- **`BitLockerStatus` gana dos propiedades:** `locked` (`state == BDE_LOCKED`) y
  `present` (se sabe el estado y no es `BDE_OFF` ni `BDE_NOT_ENCRYPTABLE`: el
  volumen lleva BitLocker, esté como esté).
- **Cuándo se apunta** (`Agente._apuntar_volumen(con)`): cada vez que una unidad de
  la lista queda conectada con su código aceptado, es decir, en `_conectar()` tras
  la comprobación de la huella y en `_atender()` (el sí). Nunca para una raíz de
  este equipo, ni para una unidad `cambiada` o `vieja`.
  - Estado `present`: se guarda `volumen_de(con.raiz)`.
  - Estado conocido y no `present`: se borra (le han quitado BitLocker).
  - Estado sin comprobar (`known=False`): no se toca.
  - Raíz sin nombre de volumen (una carpeta donde se monta un volumen, o
    cualquiera fuera de Windows): ni se pregunta su estado ni se toca.
    `cifrada.bitlocker_de()` contesta por la letra de la ruta, que ahí es otro
    volumen.
  - Solo se escribe `agente.json` si el valor cambia.
  - Al apuntar un volumen a una unidad se le quita a cualquier otra de la lista que
    lo tuviera: un volumen no nombra a dos unidades.
- **`agente.json`:** `a_dict()` escribe `volumen` solo si lo hay; `desde_dict()` lo
  acepta solo si es una cadena con la forma `\\?\Volume{…}\` y la unidad no tiene
  `ruta`. No es un secreto: es un identificador que el equipo ya da a cualquier
  programa.

### 2. Verla bloqueada (`agente.py`)

En `_recorrer()`, solo si alguna unidad de la lista tiene `volumen` (fuera de
Windows ninguna lo tiene nunca), no es raíz, no está en modo `nada` y no está conectada:

- Las raíces candidatas que no han dado ni fichero de control ni vestíbulo (también
  las que han contestado con `OSError`) se comparan por `bitlocker.volumen_de()`
  con esos volúmenes recordados.
- Si una coincide, se pregunta `cifrada.bitlocker_de(raiz)` (el punto sustituible
  que ya usa la ventana, que recibe la raíz y no la letra). Solo cuenta `locked`. Cualquier otro estado, o no saberlo, no enseña nada: se falla hacia no
  decir nada, como `cifrada.estado()`.
- El resultado es `Agente.bitlocker: dict[str, Path]` (id → raíz), rehecho en cada
  recorrido. No hace falta verla `ESTABLE` veces: de la unidad no se lee ni se
  ejecuta nada.
- **Diario:** una línea la primera vez que se ve en cada conexión
  («Trabajo: bloqueada con BitLocker en E:\»); se rearma cuando deja de verse.
- **Cadencia:** mientras haya alguna, el recorrido de respaldo con bandeja pasa de
  `RECORRIDO_RESPALDO` (30 s) a `RECORRIDO_WINDOWS` (5 s). No se sabe si Windows
  difunde `WM_DEVICECHANGE` al desbloquear, y el diseño no depende de ello. Cada
  recorrido cuesta entonces una lectura de BitLocker de más (unos 2 ms).
- **Desbloqueada**, la letra da su fichero de control y sigue el camino de siempre:
  dos avistamientos, huella del código, modo. Nada de este diseño se salta una
  comprobación de ese camino.

### 3. La bandeja (`agente.py`, `ui/bandeja.py`)

- **`resumen()`** gana `"bitlocker"`: una lista ordenada por nombre de
  `{"id", "nombre", "raiz", "desbloqueando"}`. Las claves que hay no cambian
  (`"bloqueadas"` sigue siendo de las raíces cifradas de este equipo).
- **`bandeja.vista()`**: tras las unidades conectadas, un desplegable por cada una,
  «Trabajo (bloqueada)», con la marca de prdrive por icono (`MARCA`: de un
  dispositivo bloqueado no se enseña nada suyo) y una sola entrada:
  - «Desbloquear…» (`PIDE_DESBLOQUEAR` con su id, icono `I_DESBLOQUEAR`,
    `defecto=True`: en Windows, el doble clic sobre el desplegable la elige), o
  - «Desbloqueando: la contraseña la pide Windows», apagada, mientras la ventana de
    Windows sigue abierta. Es la frase de la raíz cifrada con «Windows» en vez de
    «VeraCrypt».
- **`bandeja.estado()`**: el candado (`icons.BLOQUEADO`) y «Trabajo bloqueada», en
  el mismo escalón que la raíz cifrada bloqueada y detrás de ella. No es un aviso:
  no va en `bandeja.avisos()`.
- **`agente.py status`**: «Bloqueada con BitLocker: Trabajo en E:
  (agente.py desbloquear ID)».

### 4. Desbloquear (`common/bitlocker.py`, `agente.py`)

- **`bitlocker.orden_desbloquear(raiz) -> list[str] | None`**:
  `[%SystemRoot%\System32\bdeunlock.exe, "E:\\"]`, con la ruta completa y solo si
  el fichero existe; `None` si no. Es lo que lanza el Explorador con ese verbo. No
  se usa `os.startfile()` ni un verbo del shell sobre la raíz de una unidad (la
  regla de `agente.orden_explorar()`).
- **`agente.desbloquear_bitlocker(raiz) -> subprocess.Popen | None`** (de módulo,
  sustituible, como `explorar()` y `abrir_contenedor()`): lanza esa orden sin
  consola y sin esperar. El agente no ve la contraseña, no ejecuta nada de la
  unidad y no eleva.
- **`PIDE_DESBLOQUEAR`** se reutiliza: si el id es de una unidad que está en
  `Agente.bitlocker`, se lanza el desbloqueo; si no, sigue el camino de hoy (la
  raíz cifrada de este equipo). Así vale también `agente.py desbloquear ID`. Un id
  de una unidad con volumen recordado que ahora no se ve bloqueada: una línea en el
  diario y nada más.
- El proceso lanzado se guarda por id. Mientras siga vivo, otra petición para la
  misma unidad no lanza nada y el resumen dice `desbloqueando`. Cuando sale, o la
  unidad se conecta, o sigue bloqueada (contraseña cancelada) y la entrada vuelve a
  «Desbloquear…».
- Al pedirlo se recorre en cada vuelta durante `RAFAGA` (60 s), para que la unidad
  se conecte a los pocos segundos de teclear la contraseña.
- Si no hay `bdeunlock.exe` o no arranca: un aviso «Trabajo: no he podido abrir el
  desbloqueo de Windows. Desbloquéala desde el Explorador.» y la línea del diario.

### 5. Límites que se aceptan

- **Primera vez en un equipo:** bloqueada, no se reconoce; hay que desbloquearla una
  vez a mano. Lo mismo si se le pone BitLocker en otro equipo después de la última
  vez que este la atendió.
- **El nombre de volumen es de este equipo.** Si Windows le da otro (un pendrive sin
  número de serie en otro puerto, el registro `MountedDevices` rehecho), no se
  reconoce bloqueada hasta que se vuelva a atender; entonces se apunta el nuevo.
- **Un pendrive reutilizado:** si el volumen recordado se formatea y se vuelve a
  cifrar con BitLocker para otra cosa, bloqueado se seguirá llamando «Trabajo
  (bloqueada)» hasta que se desbloquee (deja de estar bloqueado y desaparece) o
  hasta que la unidad vuelva a atenderse en otro volumen. No se ejecuta nada por
  ese nombre: lo que decide es el fichero de control y la huella, ya desbloqueada.
- **Si `bdeunlock.exe` no se queda vivo** mientras su ventana está abierta, la
  entrada vuelve enseguida a «Desbloquear…» y una segunda pulsación puede abrir
  otra ventana. Se mira en real.

## Qué se toca

`common/bitlocker.py` (`volumen_de()`, `orden_desbloquear()`, las dos propiedades;
su docstring pasa a decir que también lo usa el agente), `common/equipo.py`
(`Unidad.volumen`, `desde_dict()`, `a_dict()`), `agente.py` (`_apuntar_volumen()`,
el recorrido, la cadencia, `desbloquear_bitlocker()`, `PIDE_DESBLOQUEAR`,
`resumen()`, la orden `status` y la ayuda de `desbloquear`), `ui/bandeja.py`
(`vista()`, `estado()`).

Sin ficheros nuevos fuera de `tests/`: no hay regla ni documento de área nuevos.

Documentación: `docs/agents/reference/agent.md` («Detection» y el fichero
`agente.json`), `tray.md` (el desplegable y la prioridad del icono),
`commands-testing.md` (los puntos de indirección: `bitlocker.volumen_de`,
`cifrada.bitlocker_de`, `agente.desbloquear_bitlocker`),
`docs/guia/agente-residente.md` (para quien lo usa: qué verá y que la primera vez
hay que desbloquearla a mano) y las pruebas en real
(`docs/superpowers/pruebas/2026-09-25-equipo-pendiente-en-real.md`, sección nueva).

## Pruebas

- **`tests/test_agente_bitlocker.py` (nuevo, sin pantalla, verde en Windows y en
  Linux):** con `bitlocker.volumen_de`, `cifrada.bitlocker_de`,
  `agente.desbloquear_bitlocker` y `penwatch.candidate_roots` sustituidos. Solo la
  cadencia fuerza `agente.IS_WIN`: fuera de Windows `volumen_de()` no da nombre,
  así que no hay nada recordado ni nada que buscar.
  - Se apunta el volumen al conectar una unidad de la lista con BitLocker; no con
    BitLocker apagado; se borra cuando se lo quitan; no se toca si no se sabe; no
    se apunta a una raíz de este equipo, ni a una `cambiada`, ni a una que no está
    en la lista; el sí de «Atender» lo apunta; apuntarlo a una se lo quita a otra.
  - Bloqueada y conocida sale en `resumen()["bitlocker"]`; un volumen desconocido,
    un estado que no es `BDE_LOCKED`, un estado sin comprobar y una unidad en modo
    `nada` no salen; fuera de Windows no se pregunta nada.
  - `PIDE_DESBLOQUEAR` con su id lanza una vez, con su letra y nada más; una
    segunda petición con el proceso vivo no lanza; con un id que no está bloqueado
    no lanza; el de una raíz cifrada sigue yendo a VeraCrypt; sin `bdeunlock.exe`
    avisa.
  - Desbloqueada (el fichero de control ya se lee) se conecta como siempre y deja
    la lista de bloqueadas; con otra huella, se pregunta como siempre.
  - La cadencia: 5 s con una bloqueada, 30 s sin ninguna.
- **`tests/test_bandeja.py`:** el desplegable y su única entrada, la variante
  apagada, el icono y su sitio en la prioridad, y que sin `"bitlocker"` en el
  resumen la vista es la de antes.
  - `agente.json`: ida y vuelta de `volumen` por `equipo.a_dict()` y
    `desde_dict()`; se descarta una cadena con otra forma y la de una raíz con
    `ruta`; un `agente.json` de antes (sin el campo) se lee igual.
- **`tests/test_cifrada.py`** (el que ya prueba `common/bitlocker.py`): `locked`,
  `present`, `orden_desbloquear()` con y sin el fichero, y `volumen_de()` fuera de
  Windows y con una ruta que no es la raíz de una letra.
- **En real** (sección nueva de la lista viva; equipo **W**): este equipo de
  desarrollo es Windows 11 Home, que desbloquea BitLocker To Go pero no lo crea, así
  que hace falta un pendrive cifrado en un Windows Pro. No se sabe si una máquina
  de GitHub Actions puede cifrar un disco virtual (en Windows Server, BitLocker es
  una característica que pide reiniciar); se mira con la skill `real-machine-tests`.
  1. El nombre de volumen es el mismo bloqueado y desbloqueado.
  2. Sobrevive a otro puerto USB, a desenchufar y a reiniciar; apuntar qué pasa con
     un pendrive sin número de serie y con un disco USB que Windows presenta como
     fijo.
  3. `BitLockerProtection` da 6 leído desde el proceso del agente (`pythonw`, tarea
     programada), y cuánto tarda con la unidad recién enchufada.
  4. `bdeunlock.exe E:\` saca la ventana sin elevar desde el agente, y si el proceso
     sigue vivo mientras la ventana está abierta.
  5. Cuánto pasa desde que se desbloquea hasta «conectada», y si llega
     `WM_DEVICECHANGE`.
  6. Contraseña cancelada: la entrada vuelve a «Desbloquear…».
