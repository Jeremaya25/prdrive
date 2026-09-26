# Instalación en el equipo: prdrive residente

Fecha: 2026-09-25 · Estado: **aceptada**; fases 1 a 4 implementadas (el agente
sin bandeja, con unidades: `agente.py`, `common/planificador.py`,
`install/agente.py`; la raíz del equipo sin cifrar: `install/raiz_equipo.py`,
`ui/tk_equipo.py`; cifrada con VeraCrypt; y la bandeja de Windows:
`ui/bandeja.py`, `ui/bandeja_windows.py`; **sin probar en real**) · Versión
objetivo: 0.4.0 · Lo que falta probar en equipos reales:
`docs/superpowers/pruebas/2026-09-25-equipo-pendiente-en-real.md`

## Qué se pide

Un tercer tipo de instalación, además de «unidad sin cifrar» y «unidad cifrada»:
**prdrive instalado en el ordenador**. Corre en segundo plano de forma eficiente,
hace todo lo que hoy hace `runsync` y deja sitio a funciones futuras. Puede ir
**sin cifrar o cifrado en el propio equipo con VeraCrypt**.

## Decidido al plantearlo

- **Las dos cosas.** El programa residente sincroniza **sus propias parejas**
  (carpetas del equipo ↔ remoto) **y atiende a cualquier unidad prdrive** que se
  enchufe en ese equipo. **Las parejas propias son opcionales:** una
  instalación puede ser solo el agente, atendiendo unidades.
- **La raíz en claro es configurable:** una carpeta propia (`~/PRDRIVE` por
  defecto) o la carpeta personal (`~`).
- **Icono en la bandeja**: estado, «Sincronizar ahora», «Abrir», «Pausar» y,
  si hay contenedor, «Desbloquear» y «Bloquear».
- **Windows y Linux** desde la primera versión, **bandeja de Linux incluida**
  (StatusNotifierItem sobre un cliente D-Bus propio).
- **Cifrado local con VeraCrypt** como opción de la instalación en el equipo:
  el mismo contenedor `.hc` que ya se crea en las unidades, pero en el disco del
  ordenador.
- En la v1 entran tres de las mejoras de eficiencia: **un proceso en vez de N**,
  **moderarse** (batería, red de uso medido, sin conexión, espera creciente tras
  un fallo) y **avisos nativos** del sistema en lugar de la ventanita Tk.
  Reaccionar a cambios en los ficheros queda para después.

## La idea

> Un prdrive cuya «unidad» es una carpeta del equipo (o un contenedor VeraCrypt
> del equipo), y un proceso residente, **el agente**, que vive **fuera de toda
> raíz** y atiende por igual a esa raíz y a las unidades que se enchufen.

Esto se apoya en dos cosas.

**El motor no sabe que está en un USB.** `model.APP_DIR` es
`Path(__file__).parent.parent` y `DEVICE_ROOT` es su padre, así que una carpeta
con `.prdrive/` dentro, o el volumen montado de un contenedor, es un dispositivo
más para `sync.py`, `bisync.py`, `revision`, `fleet` y la ventana. El motor sigue
siendo uno.

**El agente no vive dentro de lo que atiende.** El cifrado obliga a ello, y todo
lo demás sale ganando:

- **Tiene que estar vivo con el contenedor cerrado**, para ofrecer
  «Desbloquear» y para seguir atendiendo las unidades que se enchufen.
- **Tiene que poder cerrar el contenedor** sin sujetarlo. Un proceso que corre
  desde dentro del volumen impide desmontarlo, que es justo el problema que
  `ui/cifrado.py` resuelve hoy con un script lanzado desde fuera.
- **La raíz del equipo pasa a ser una raíz atendida más**, igual que una unidad:
  el agente lanza su `.prdrive/sync.py` con su propio Python. Así hay un solo
  camino, no dos.
- **Su runtime se actualiza como el de penwatch:** un directorio por versión que
  nunca se cambia en sitio (sección 8).

`penwatch.py` ya vive así, copiado al equipo con su propio Python. El agente es
su sucesor.

## 1. Dónde está cada cosa

**En el equipo, fuera de toda raíz. Aquí no hay ningún secreto:**

```
%LOCALAPPDATA%\prdrive\          (~/.local/share/prdrive/ en Linux)
├── agente/<versión>/        copia del código: agente.py, common/, ui/ (sin Tk
│                            en el proceso), penwatch.py. Una por versión.
├── runtime/<stamp_id>/      su Python (python-build-standalone). Una por versión.
├── agente.json              raíces atendidas, unidades, modos, políticas
├── agente.lock.json         una sola instancia por usuario
└── agente.log
```

Esto es todo lo que tiene una instalación **solo agente**: ni raíz, ni conexión,
ni clave. Cada unidad trae su `rclone.conf` y su código, y el agente no necesita
nada más para atenderla.

**La raíz del equipo sin cifrar** (`DEVICE_ROOT`), en una de dos formas que se
eligen al instalar:

```
Carpeta propia (por defecto)          Carpeta personal
~/PRDRIVE/                            ~/
├── .prdrive/                         ├── .prdrive/          (el mismo árbol)
│   ├── PRDRIVE   id=…, tipo=equipo   ├── Documentos/Obsidian   ← local =
│   ├── bin/<arch>/  rclone, sin      │                           "Documentos/Obsidian"
│   │                runtime: la lanza el agente
│   ├── rclone.conf, keys/  la clave, en claro
│   └── state/
└── obsidian/ …   las parejas         └── …
```

**La raíz del equipo cifrada:**

```
~/PRDRIVE-cifrado/           la «raíz física»: una carpeta del equipo
├── PRDRIVE.hc               el contenedor (disperso si el disco lo admite)
└── .prdrive-vestibulo       id=… el mismo que el .prdrive/PRDRIVE de dentro

   montado en P:\ (Windows) o en ~/PRDRIVE (Linux) = DEVICE_ROOT
   └── .prdrive/ + las parejas, exactamente como arriba, clave incluida
```

- **`tipo=equipo`** en el fichero de control. Así el agente, el asistente y la
  flota saben qué es sin adivinarlo, y un `penwatch` viejo ignora la línea: solo
  lee `id=`.
- **La raíz física cifrada se parece a propósito a la de una unidad cifrada.**
  Tiene el mismo `CONTENEDOR` y la misma marca con el mismo id, así que
  `vestibulo.leer_id()`, `disperso()` y el hallazgo `espacio` sirven tal cual.
  Solo cambia cómo se encuentra (sección 4).
- **Carpeta propia o carpeta personal, configurable.** El motor es el mismo en
  los dos casos: la raíz es `DEVICE_ROOT`, las parejas siguen siendo relativas a
  ella y `pair_editor.ruta_local_relativa()` sigue rechazando lo que queda
  fuera. Lo que cambia es dónde está el límite:
  - **Carpeta propia:** el modelo de Dropbox. Nada de fuera de `~/PRDRIVE` se
    toca, y es la opción por defecto.
  - **Carpeta personal:** se sincroniza `~/Documentos/Obsidian` sin moverlo. A
    cambio:
    - **Las rutas del catálogo pensadas para una unidad** (`sync-data/…`)
      caerían sueltas en `~`. El paso «Parejas» enseña la ruta resuelta de cada
      pareja antes de escribir nada y ofrece cambiar su `local` en este equipo.
      Es el mismo `plan_override` que ya existe: la pareja queda como
      «modificada aquí».
    - **Otro cliente de sincronización:** si una ruta cae dentro de una carpeta
      de OneDrive, Dropbox o similar (en Windows, `Documentos` suele estar
      redirigida a OneDrive), se avisa en ámbar. Dos programas sincronizando la
      misma carpeta se pisan los borrados. Es un aviso, no un bloqueo. Las
      carpetas se saben sin adivinar: las variables `OneDrive`,
      `OneDriveConsumer` y `OneDriveCommercial`, y el `info.json` de Dropbox.
      Es un punto de indirección, para que los tests pongan las suyas.
  - **Se elige al instalar y no se cambia después** en la v1. Cambiarlo es
    «Reinstalar»: mover `DEVICE_ROOT` deja cada línea base apuntando a una
    carpeta que ya no está, y `_bisync_preflight()` las pararía todas.
  - `agente.json` guarda la ruta de cada raíz, así que el agente no deduce
    nada del nombre de la carpeta.
- **La pareja de la raíz entera (`local = "."`) queda prohibida en un equipo.**
  Sería el mismo `.prdrive/` con la clave dentro y, con la carpeta personal,
  todo `~`. Se rechaza con un `ConfigError` en `model.load_config()`, que lee el
  `tipo` del fichero de control, y no en la ventana, así que un TOML editado a
  mano tampoco se la salta.
- **Sin cifrar, la clave vive en claro en el disco del equipo.** El asistente lo
  dice en ámbar y enseña si el disco del sistema tiene BitLocker en estado `On`
  (la misma lectura de `install/crypto.py`). Es información, no una exigencia.
  Con VeraCrypt, la clave, `rclone.conf` y el estado de bisync están dentro del
  contenedor.

## 2. El agente (`agente.py`)

Es un proceso por usuario, arrancado al iniciar sesión, **sin Tk**, que corre con
su propio Python de `runtime/`. Hace esto:

1. **Planifica.** `common/planificador.py` es **puro**, sin reloj ni disco
   propios: recibe raíces (cada una abierta, bloqueada o ausente), parejas,
   últimos resultados, intervalos, estado de energía y red, y la hora, y devuelve
   qué toca ahora y cuándo volver a mirar. Se prueba sin procesos.
2. **Una cola para todo el equipo:** una pasada a la vez, sea de la raíz o de
   una unidad. Ahorra ancho de banda y evita algo que hoy puede pasar: una pareja
   del equipo y la misma pareja en la unidad enchufada, las dos contra el mismo
   `remote_path` a la vez.
3. **Cada pasada es un `sync.py` hijo**, el de la raíz que toca, uno por pareja,
   lanzado con el Python del agente y con el directorio de trabajo fuera de la
   raíz:
   - **Cada raíz ejecuta su propio código.** Una unidad puede traer otra versión
     que el agente, y sus listados y su `sync_config.toml` los escribió su propio
     `sync.py`. Ejecutar el suyo (con su rclone, que resuelve él solo) mantiene el
     contrato actual.
   - **Aislamiento:** un rclone colgado o un fallo del motor no tumba la bandeja.
   - Arrancar un Python cuesta unas décimas. Solo listar el remoto a rclone ya le
     cuesta segundos.
   - **Entre pasadas no queda nada abierto dentro de ninguna raíz**, así que una
     unidad se puede expulsar y un contenedor se puede bloquear. Hoy el servicio
     es un `pythonw.exe` que corre **desde** `.prdrive/runtime/` y solo lo
     compensa con `chdir` a temp.
4. **Detecta unidades sin recorrerlas cada 5 s.**
   - En Windows, `WM_DEVICECHANGE` en la ventana oculta que la bandeja necesita de
     todas formas, y a partir de ese aviso una racha de sondeos: un volumen
     cifrado se puede leer bastante después del aviso, que es por lo que penwatch
     sondea.
   - En Linux, `select.poll()` sobre `/proc/self/mountinfo` (`POLLPRI` al cambiar
     los montajes). Así se ve también cuándo el contenedor propio se abre o se
     cierra.
   - En los dos, un sondeo lento de respaldo. Recorrer las unidades es siempre
     `penwatch.candidate_roots()`, así que el proyecto sigue teniendo un único
     recorrido.
5. **La ventana es un proceso aparte, bajo demanda.** «Abrir» lanza el
   `runsync.py` de la raíz, o el de la unidad, como hijo y con el Python del
   agente. El agente no carga Tk nunca: el intérprete Tk residente son decenas de
   MB, y todo lo que hoy se sabe de hilos e intérpretes Tk (`avisar_fallo`,
   `Tcl_AsyncDelete`) sigue en la ventana, donde ya está resuelto.

**Lo que significa «un proceso en vez de N»**, medido en procesos vivos:

| | Hoy (unidad + penwatch) | Con el agente |
|---|---|---|
| Siempre vivo | `penwatch` (pythonw, sondeo cada 5 s) + un servicio por unidad (pythonw **desde la unidad**, sondeo cada 2 s) | **el agente** (pythonw del equipo) |
| Durante una pasada | `sync.py` + rclone por pareja | lo mismo, de uno en uno en toda la máquina |
| Al fallar | un intérprete Tk en un hilo del servicio | un aviso nativo, sin Tk |

Queda para una fase posterior ejecutar las parejas en el propio proceso cuando
la raíz tenga la misma versión que el agente, y un rclone residente
(`rclone rcd`). La v1 no los necesita, y el segundo abre un puerto, cosa que el
proyecto evita hoy.

## 3. Cómo atiende una raíz: el contrato del servicio

Para cualquier raíz, sea la del equipo o una unidad, el agente **hace de su
servicio** con los mismos ficheros que ya existen en su `state/`. Por eso
funciona con unidades que llevan código viejo.

- Mientras la atiende escribe su `daemon.lock.json` (pid y host del agente, las
  parejas, el ciclo), así que la ventana, el menú de consola y cualquier
  `penwatch` ven un servicio en marcha, que es lo que hay.
- Obedece `daemon.stop`, que es lo que hace `runsync` al abrir su ventana: acaba
  la pareja en curso, suelta el lock, borra el `.stop` y **deja esa raíz en
  pausa** mientras haya un `ui.lock.json` vivo de este equipo.
- Al cerrarse la ventana: si ha arrancado su propio servicio (hay un
  `daemon.lock.json` con otro pid vivo), el agente **se aparta**. La regla es un
  servicio por raíz, el que tenga el lock. Si no lo ha arrancado, el agente
  vuelve a atenderla.
- **Qué unidades atiende:** una lista explícita de ids en `agente.json`, cada uno
  con su modo al enchufar. Son los tres de penwatch (`ui`, `daemon`, `sync`) más
  `nada`. Una unidad que no está en la lista nunca se sincroniza sin preguntar
  (ver «Una unidad nueva», abajo).
- **Las parejas y el intervalo siguen siendo de la raíz** (`ui_prefs.json` >
  `[daemon]`, `prefs.startup_defaults()`). En el equipo solo se guarda lo que es
  del equipo, igual que decidió el issue #14.
- **Unidades cifradas con VeraCrypt:** el vestíbulo y `open_container()` se
  reutilizan tal cual, una vez por conexión, como en penwatch.
- **Sustituye a penwatch en ese equipo.** Instalar el agente importa el
  `device_id` y el modo de `watch.json` a la lista y desinstala penwatch, y lo
  dice. `penwatch` sigue existiendo para los equipos sin agente.

### Una unidad nueva

Cuando aparece una unidad prdrive cuyo id no está en la lista:

- **Se pregunta una vez, con tiempo límite.** Se enseña un aviso («Se ha
  conectado PRDRIVE-2. ¿Atenderla en este equipo?») y una ventanita con la
  pregunta y una cuenta atrás. Las respuestas son «Atender» y «Ahora no».
- **Si no se contesta en `espera_unidad_nueva`**, un ajuste de `agente.json`
  (**2 minutos por defecto**), cuenta como «Ahora no», y **«Ahora no» vale solo
  para esta conexión**:
  - La unidad no se atiende mientras siga enchufada.
  - La próxima vez que se enchufe se vuelve a preguntar. «Esta conexión» acaba
    cuando su raíz desaparece, la misma regla con la que penwatch rearma su
    disparo.
  - **Mientras siga conectada, se puede decir que sí desde la bandeja:** el menú
    tiene una entrada «PRDRIVE-2, conectada · Atender…».
- **«Atender»** la añade a la lista con el modo `daemon`, lo natural para un
  programa en segundo plano, y la atiende enseguida. El modo se cambia después
  en los ajustes.
- **Quién lleva el reloj: el agente, no la ventana.** El plazo es un dato del
  planificador. La ventana solo enseña la cuenta atrás y se cierra sola al
  llegar a cero. Si contesta tarde, la respuesta se ignora; para eso está la
  entrada de la bandeja. Sin entorno gráfico donde abrir la ventana, cuenta como
  «Ahora no» al momento, y la entrada de la bandeja o el diario lo dicen.
- **Antes del sí no se ejecuta nada de la unidad.** Para preguntar, el agente
  solo *lee* el id del fichero de control y el nombre de `state/fleet.json`. No
  lanza su `runsync.py`, ni su `sync.py`, ni su rclone. Ejecutar código de una
  unidad cualquiera al enchufarla es exactamente lo que AutoRun dejó de hacer, y
  por la misma razón.
- **La ventanita es un proceso hijo**, como la ventana principal: el agente
  sigue sin cargar Tk. Se dibuja en `ui/tk_agente.py`; qué hacer con la
  respuesta lo decide el agente.

## 4. Cifrado local con VeraCrypt

La raíz del equipo puede vivir en un contenedor `PRDRIVE.hc` del disco del
ordenador. Casi todo ya existe para las unidades (`install/crypto.py`,
`common/vestibulo.py`, la prueba en real de `docs/superpowers/pruebas/`). Lo
nuevo es **quién lo abre y quién lo cierra: el agente**.

### Crear

Se hace en el paso «Cifrado» del recorrido del equipo, con las mismas piezas y
las mismas reglas que en una unidad:

- `crypto.create_container()`, que espera a la copia elevada.
- `/dynamic` solo si `soporta_dispersos()` dice que sí. En un disco NTFS lo
  normal es que sí, y entonces el tamaño casi no cuesta.
- `revisar_contrasena()` antes de lanzar, porque `/silent` se salta esa
  comprobación.
- `/m rm` al montar, para que no aparezca `$RECYCLE.BIN` dentro de lo que se
  sincroniza.
- El hallazgo `espacio` en «Reparación» cuando el disco del equipo se queda sin
  sitio para que crezca un contenedor disperso.

En Linux no hay `/dynamic`: se escribe el tamaño entero, que en un disco interno
es bastante más rápido que en un USB.

**VeraCrypt instalado, no el que viaja.** En una unidad, el VeraCrypt portátil
existe para equipos donde no hay otro. En el ordenador propio se instala una
vez. El portátil pide administrador cada vez que carga el driver, y ramas suyas
como `ERR_DRIVER_VERSION` están sin verificar en real. El paso «Cifrado»
comprueba que haya uno instalado (`find_veracrypt()`). Si no lo hay, dice cómo
instalarlo y no ofrece la opción. **No se instala VeraCrypt desde aquí**, ni se
descarga, ni se lanza un instalador.

**Una letra fija en Windows.** `penwatch.veracrypt_command()` deja que VeraCrypt
elija letra, y en una unidad da igual. En el equipo no, porque los programas
apuntan a la raíz: un almacén de Obsidian en `P:\obsidian` se rompe si al día
siguiente es `Q:`. La letra se elige al crear (`crypto.free_drive_letter()`), se
guarda en `agente.json` y se pasa con `/letter`. Si está ocupada al abrir, el
agente no se inventa otra: lo dice. En Linux el punto de montaje es una carpeta
fija, `~/PRDRIVE`.

### Abrir («Desbloquear»)

- **La contraseña nunca pasa por nosotros:** se lanza
  `VeraCrypt.exe /volume … /letter P /mountoption rm /quit` **sin `/password`**, y
  la pide la ventana de VeraCrypt, igual que en `Abrir PRDRIVE.bat`. Una orden
  así no la tiene hoy nadie: se generaliza `penwatch.veracrypt_command()` para
  que reciba contenedor y destino en vez de deducirlos de la raíz.
- **Al iniciar sesión: configurable.** Es el ajuste `pedir_al_iniciar` de
  `agente.json`, que viene activado por defecto.
  - **Activado:** si el contenedor está cerrado, el agente pide abrirlo una vez.
    Si se cancela, no se vuelve a pedir hasta que se pulse «Desbloquear». Es la
    misma regla de «una vez por conexión» que tiene penwatch para las unidades
    cifradas.
  - **Desactivado:** el agente arranca con la raíz bloqueada y no pide nada
    hasta que se pulse «Desbloquear». Mientras tanto sigue atendiendo las
    unidades.
  - **Dónde se cambia:** lo elige el paso «Cifrado» del asistente (una casilla
    marcada), y después se cambia con una casilla del menú de la bandeja o desde
    «Ajustes» en la ventana de la raíz. Esto último cubre Linux sin bandeja.
  - **`agente.json` lo crea el asistente, y a partir de ahí solo lo escribe el
    agente.** La ventana es el código de la raíz, que puede ir en otra versión,
    así que no toca la configuración del equipo: pide el cambio con
    `agente.pide` (sección 5) y el agente lo aplica.
- **Que VeraCrypt salga con 0 no quiere decir que esté montado.** El agente sabe
  que está abierto cuando **ve** el volumen con el id de la marca, igual que los
  `.bat` del vestíbulo, y lo busca por la letra o el punto de montaje guardados.
  Una letra con el id al lado de un `.hc` libre es el fantasma que ya se conoce
  de las unidades: no se atiende, y la bandeja dice «Bloquear y volver a
  desbloquear».
- **En Linux pide dos contraseñas**: la del volumen y la de administrador que
  VeraCrypt necesita para montar. Es cosa de VeraCrypt, y el asistente lo avisa.

### Cerrar («Bloquear»)

- El agente deja de encolar esa raíz, espera a que termine la pareja en curso,
  cierra la ventana hija si la hay (pidiéndoselo con `daemon.stop`, no
  matándola) y lanza `/dismount <letra> /quit` **sin `/silent`**, como
  `Expulsar PRDRIVE.bat`: si un programa tiene un fichero abierto dentro,
  VeraCrypt pregunta si forzar, y esa decisión es del usuario.
- **La letra desaparecida no basta**, por lo mismo que en el vestíbulo: el agente
  da la raíz por bloqueada cuando `crypto.en_uso()` ve el `.hc` libre.
- **En la ventana de la raíz, «Expulsar» se convierte en «Bloquear».** Con
  `tipo=equipo`, `ui/cifrado.py` no lanza el script del vestíbulo: se lo pide al
  agente (sección 5).
- **No se configura el cierre automático de VeraCrypt** (al suspender, por
  inactividad, al cerrar sesión). Es de sus Preferencias, y escribir su
  `Configuration.xml` ya borró los favoritos del usuario una vez (ver la nota de
  `write_favorite()` en `crypto.py`). Si el usuario lo tiene activado, el volumen
  desaparece a mitad de una pasada, y eso es exactamente una unidad desenchufada:
  el agente lo trata igual.
- **Tampoco hay favoritos** que lo monten solo al iniciar sesión, por la misma
  nota: no registran nada y reescriben el fichero entero.
- **El agente no bloquea al suspender en la v1.** Queda como ajuste futuro
  (`bloquear_al_suspender`, desactivado por defecto), atado a
  `PBT_APMSUSPEND` en Windows y a la señal `PrepareForSleep` de logind en
  Linux. No se hace ahora porque tiene su propio problema: la suspensión avisa
  con poco margen y cortaría la pasada en curso, así que hay que decidir antes
  si se espera, se corta o se renuncia a bloquear. Mientras tanto, quien lo
  quiera tiene la preferencia de VeraCrypt, que el agente ya soporta como si se
  desenchufara la unidad. La v1 no reserva la clave en `agente.json`: se añade
  cuando exista.

### Lo que el cifrado hace más seguro, y lo que no

- **Con el contenedor cerrado no hay nada que sincronizar por error.** El estado
  de bisync también está dentro, así que una raíz cerrada no tiene ni carpeta ni
  línea base: el agente no la encuentra y no lanza nada. No se puede dar el caso
  de «línea base sin carpeta local» que `_bisync_preflight()` tiene que frenar en
  una raíz en claro.
- **En Linux, el punto de montaje vacío es una carpeta normal.** Lo que se
  guarde en `~/PRDRIVE` con el contenedor cerrado queda tapado al montarlo. El
  agente lo mira antes de abrir y, si hay algo, avisa en vez de montar encima.
- **Abierto, protege lo mismo que una unidad cifrada abierta: nada frente al
  propio usuario.** Cualquier programa de la sesión lee la clave. La memoria y el
  fichero de hibernación son advertencias de la documentación de VeraCrypt, no
  nuestras, y no prometemos más que ella.
- **Pasar a cifrado una raíz en claro deja el árbol viejo donde estaba**, con la
  misma regla que en una unidad: `crypto.restos_en_claro()` lo encuentra y el
  asistente lo dice en rojo, pero nada lo borra.

### Cómo lo encuentra el resto del código

`vestibulo.raiz_fisica()` recorre las raíces de las unidades con
`penwatch.candidate_roots({})`, y la carpeta `~/PRDRIVE-cifrado/` no es la raíz
de ninguna unidad. El arreglo es el que penwatch ya tiene para esto, las **raíces
extra**: `raiz_fisica()` le pasa como `extra_roots` las carpetas de contenedor
que haya en `agente.json`. Así funcionan sin más cambios el hallazgo `espacio`,
`cifrado.expulsion()` y el aviso de los restos en claro.

## 5. Bandeja, avisos y la ventana

Todo con la biblioteca estándar: ctypes en Windows y el protocolo D-Bus en Linux.

- **Windows:** `Shell_NotifyIconW` sobre una ventana oculta de solo mensajes, con
  su bucle en un hilo propio. El menú va con `TrackPopupMenu`. Los avisos son
  `NIF_INFO`, que en Windows 10/11 salen como notificación del sistema sin
  registrar un AppUserModelID. El icono lo pinta `icons.py` en cinco estados
  (bien, sincronizando, aviso, en pausa, **bloqueado**) y se carga con
  `LoadImageW` desde un `.ico` repintado, nunca copiado.
- **Linux: un cliente D-Bus propio, en la v1.** Es **la parte con más riesgo del
  plan**, y se hace con el mismo espíritu que `ui/qr.py`: sin dependencias,
  completo en lo que usa, y con las constantes citando la especificación (la
  *D-Bus Specification* de freedesktop.org para el protocolo, y la de
  StatusNotifierItem para la bandeja), como `common/bisync.py` cita a rclone.
  Son dos piezas:
  - **`common/dbus.py`**, sin Tk y sin bandeja: el socket de la sesión
    (`DBUS_SESSION_BUS_ADDRESS`), la autenticación `EXTERNAL`, la serialización
    de mensajes (firmas, alineación, cuerpo), las llamadas a métodos, las
    propiedades y la escucha de señales. Está en `common/` porque también lo
    usan cosas que no son de la ventana: los avisos
    (`org.freedesktop.Notifications.Notify`), la red de uso medido
    (`Metered` de NetworkManager, sección 6) y, más adelante, la señal
    `PrepareForSleep` de logind.
  - **`ui/bandeja_linux.py`**, que *exporta* objetos en el bus: un
    `org.kde.StatusNotifierItem` registrado en `org.kde.StatusNotifierWatcher`,
    y su menú por `com.canonical.dbusmenu`, que es un protocolo aparte y la
    mitad del trabajo. El icono viaja como `IconPixmap` (ARGB32 en orden de red),
    así que `icons.py` lo rasteriza directamente, sin `.ico` de por medio.
  - **Tamaño estimado:** 600-900 líneas entre las dos.
- **GNOME no tiene bandeja** sin la extensión AppIndicator: Ubuntu la trae y
  Fedora no. El agente lo sabe al arrancar, porque no hay nadie registrado como
  `org.kde.StatusNotifierWatcher`, y cae a un lanzador `.desktop` «prdrive» que
  arranca el agente o, si ya está vivo, le pide abrir la ventana (o
  desbloquear), más los avisos con el estado. La verificación del asistente lo
  dice, con el nombre de la extensión que falta. Así que «paridad» es, siempre,
  **las mismas funciones**, y la bandeja allí donde el escritorio tiene una.
- **Sin sesión D-Bus**, el aviso se queda en el diario, que es la misma caída
  que tiene hoy `avisar_fallo()`.
- **La ventana ↔ el agente, sin puertos.** Se usan dos buzones, que son ficheros
  que el agente sondea igual que `daemon.stop`:
  - **`state/servicio.pide`**, en la raíz, para lo que es de esa raíz:
    `reanudar`, `bloquear` o `pasada` con sus parejas.
  - **`agente.pide`**, en el directorio del agente en el equipo, para lo que es
    del equipo: un `ajuste` (`pedir_al_iniciar`, `espera_unidad_nueva`, el modo
    de una unidad) o `añadir_raiz`. Es una ruta fija por sistema, como el
    `HOST_DIR` de penwatch, así que la ventana la sabe sin preguntar.
  - «Iniciar servicio» deja de lanzar un servicio: escribe `ui_prefs.json`,
    como hoy, y un `reanudar`.
  - La línea del vigilante pasa a ser la línea del agente, que dice qué atiende
    y si está en pausa.

## 6. Moderarse

El planificador lo recibe todo como datos. Cada sonda es un punto de indirección
de módulo:

- **Batería:** en Windows `GetSystemPowerStatus` y en Linux
  `/sys/class/power_supply/*`. Por defecto sincroniza con batería y **se para por
  debajo del 20 %**.
- **Red de uso medido:** en Windows `INetworkCostManager` (COM por vtable, igual
  que ya se hace con `IShellItem2`) y en Linux la propiedad `Metered` de
  NetworkManager, leída con `common/dbus.py`. Sin NetworkManager no se sabe, y
  se trata como una red normal. Por defecto **se pausa**. «Sincronizar ahora» siempre se salta
  esta moderación.
- **Sin conexión:** si un fallo es de red (una categoría nueva en
  `KNOWN_ERRORS`), todo lo que va a **ese remoto** pasa a «sin conexión». Se
  sondea con `catalog.run()` + `NET_FLAGS` en vez de lanzar pareja tras pareja
  para que fallen igual. Al volver de la suspensión (`WM_POWERBROADCAST`) se mira
  enseguida.
- **Espera creciente por pareja:** `intervalo · 2^k` tras k fallos seguidos, con
  un tope de 4 h, y vuelve a cero tras una pasada buena. Los avisos siguen la
  regla actual: se avisa cuando una pareja **empieza** a fallar, no en cada
  ciclo.
- **Raíz bloqueada:** para el planificador es una raíz ausente. No es un fallo,
  no lleva a esperar más y no provoca avisos. La bandeja solo lo enseña.
- Nada de esto hace un `--resync` solo. Una pareja que lo pide se salta, igual
  que hoy con `stdin=DEVNULL`, y la bandeja lo cuenta como aviso.

## 7. Instalación

El asistente gana una primera pregunta: **«¿Dónde?» → «En una unidad» (lo de
hoy) / «En este equipo»**. El recorrido nuevo es otra lista de pasos
(`PASOS_EQUIPO`), como ya lo son `PASOS_ACTUALIZACION` y `PASOS_PLATAFORMAS`:

```
1 Carpeta         carpeta propia (~/PRDRIVE, editable) / carpeta personal (~) /
                  ninguna: solo atender unidades; ¿ya hay un prdrive ahí?
2 Cifrado         ninguno / VeraCrypt: contenedor, tamaño, letra o punto de
                  montaje, pedir_al_iniciar; lo crea, lo monta y fija
                  state.device_root
3 Conexión        igual
4 Comprobaciones  igual
5 Instalación     .prdrive/ + rclone en la raíz; agente + runtime en el equipo
6 Parejas         igual, con la ruta resuelta de cada una a la vista
7 Inicialización  --resync de las bisync
8 Unidades        qué unidades atiende y cómo, y espera_unidad_nueva
9 Arranque        registrar el agente al iniciar sesión y arrancarlo
10 Verificación
```

- **«Ninguna: solo atender unidades»** se salta los pasos 2, 3, 4, 6 y 7. Sin
  raíz no hay conexión que pedir, ni catálogo, ni clave en el equipo: cada
  unidad trae los suyos. «Instalación» copia solo el agente y su runtime.
  «Unidades» ofrece entonces lo que se sabe sin red: el `device_id` de un
  `watch.json` de penwatch y las unidades enchufadas en ese momento. El resto
  llega con el aviso de «unidad nueva». Con raíz, la lista sale además del
  registro de la flota (`devices/`).
- **Añadir una raíz más tarde** es volver a pasar el asistente «En este
  equipo»: ve el agente instalado, no lo reinstala, y le pide con `agente.pide`
  que añada la raíz (sección 5).
- **Carpeta personal.** El paso 1 lo explica en dos líneas (qué se gana, qué
  límite se pierde), y el paso 6 enseña la ruta resuelta de cada pareja y los
  avisos de otro cliente de sincronización antes de escribir nada.

- **«Cifrado» va antes de «Conexión» por lo mismo que en las unidades:** fija
  dónde escribe «Instalación». Con VeraCrypt, la detección de un prdrive ya
  instalado se repite al montar, como al final de `_paso_cifrado`.
- **El asistente monta con contraseña** (`crypto.mount_container()`, como hoy en
  las unidades), porque acaba de pedirla para crear el contenedor. A partir de
  ahí, abrir siempre es cosa de VeraCrypt y su ventana. Al terminar, el
  asistente deja el contenedor **abierto** y se lo entrega al agente.
- **Registro:** en Windows, la tarea programada por usuario de penwatch, con las
  mismas trampas ya resueltas (XML en UTF-16, `DisallowStartIfOnBatteries=false`,
  `ExecutionTimeLimit=PT0S`), que se saca a una función con el comando como
  parámetro. En Linux, **autostart XDG** en vez de la unidad systemd: una bandeja
  y la ventana de contraseña de VeraCrypt necesitan la sesión gráfica, y
  `enable-linger` no la da.
- **Una sola instancia por usuario** con `agente.lock.json` y `pid_alive()`, con
  el mismo criterio que `ui.lock.json`.
- **Desinstalar** quita el registro, el agente y su runtime. **Nunca borra la
  raíz ni el contenedor**, por la misma razón que re-cifrar no borra el árbol en
  claro. Si el contenedor está abierto, se deja abierto y se dice.

## 8. Actualizaciones

- **El agente:** la bandeja ofrece «Actualizar» cuando `update.check()` lo dice.
  Se descarga el zip, `prdrive-install.py --update-agente` copia
  `agente/<versión nueva>/` al lado, cambia el puntero de forma atómica, vuelve a
  registrar y reinicia, y se podan las versiones viejas. Con el runtime pasa lo
  mismo con `runtime/<stamp_id>/`. Es el patrón de `refresh_runtime()` y
  `prune_runtimes()` de penwatch: **nunca se cambia en sitio** lo que está
  corriendo.
- **El código de la raíz:** `--update <raíz>`, sin tocarlo, porque la estructura
  es la de siempre. Con la raíz cifrada, solo con el contenedor abierto. Si está
  cerrado, la actualización queda pendiente y se ofrece al desbloquear.
- **Agente y raíz pueden ir en versiones distintas un rato**, igual que el
  agente y una unidad: cada raíz ejecuta su propio `sync.py` (sección 2).

## 9. Flota

La nota de la raíz del equipo lleva `tipo = "equipo"`, y también `cifrado =
"veracrypt"` cuando lo está. `fleet.parse()` ya ignora las claves que no conoce,
así que las versiones viejas la leen sin romperse, y la ventana de la flota le
pone una etiqueta. `equipos` será siempre el mismo host, y está bien que sea así.
Mientras el contenedor está cerrado no se publica nada, porque no hay pasadas y
la nota se escribe tras cada pasada.

## Invariantes que no se tocan

- `_bisync_preflight()`: si hay línea base y no hay carpeta local, se aborta. En
  una raíz del equipo en claro esto es **más** importante que en una unidad:
  mover o renombrar `~/PRDRIVE` es fácil.
- Los `max-delete`, el prefijo de sesión y `device_remote` no cambian. La raíz del
  equipo usa `disp`, como cualquier dispositivo.
- Un `--resync` nunca se lanza sin nadie delante.
- **La contraseña de VeraCrypt nunca pasa por el agente.** El asistente la
  maneja al crear, como hoy, y nada la guarda.
- **Fuera del contenedor no hay secretos:** en `%LOCALAPPDATA%\prdrive\` no hay
  clave, `rclone.conf` ni listados.
- Ni favoritos de VeraCrypt ni escribir en su `Configuration.xml`.
- `penwatch.py` sigue sin importar nada del proyecto, y el agente importa de
  penwatch, nunca al revés.
- `tk_*` solo dibuja. `agente.py`, `planificador`, `bandeja` y `avisos` no
  importan tkinter.

## Qué cambia para las unidades que ya están en uso

Nada, mientras no se instale el agente. Cuando se instala:

- Una unidad con código viejo funciona gracias al contrato de la sección 3.
- **El único cambio que se nota:** con el agente, **abrir la ventana de la unidad
  ya no apaga el servicio para siempre**. Lo pausa mientras la ventana está
  abierta. Para pararlo, se usa «Pausar» en la bandeja. Hay que decirlo en el
  README y en `device-readme.md`.

## Preguntas resueltas

- **Carpeta propia o carpeta personal:** configurable, con la carpeta propia
  por defecto (sección 1). Con VeraCrypt la pregunta no existe: la raíz es el
  volumen.
- **Instalación sin parejas propias:** sí. Es la instalación «solo agente», sin
  raíz. No toca `parse_config()`: no es un config vacío, es que no hay config
  (sección 1 y sección 7). Una raíz a la que se le han quitado todas las
  parejas sigue siendo el `ConfigError` de siempre, y la bandeja lo enseña como
  aviso en vez de tumbar el agente.
- **Aviso de «unidad nueva»:** tiene un plazo configurable
  (`espera_unidad_nueva`, 2 min por defecto). Sin respuesta cuenta como «Ahora
  no», solo para esta conexión, y se puede decir que sí desde la bandeja
  mientras siga enchufada. «Atender» la añade en modo `daemon` (sección 3).
- **Bandeja en Linux:** entra en la v1, con cliente D-Bus propio, y cae al
  lanzador solo donde el escritorio no tiene bandeja (sección 5).
- **Pedir la contraseña al iniciar sesión:** es configurable
  (`pedir_al_iniciar`) y viene activado por defecto (sección 4, «Abrir»).
- **Bloquear al suspender:** no entra en la v1. Será un ajuste futuro,
  desactivado por defecto (sección 4, «Cerrar»).

## Fases

**La v1 son las seis.** Cada fase se puede publicar por separado y deja el
proyecto funcionando:

1. **El agente sin bandeja**, con unidades: la instalación «solo agente», su
   sitio en el equipo, el planificador, la cola, el contrato de la sección 3, el
   aviso de «unidad nueva», la sustitución de penwatch, la moderación y los
   avisos nativos. Aquí entra la mitad cliente de `common/dbus.py` (llamadas,
   propiedades, señales), porque los avisos y la red de uso medido de Linux la
   necesitan. Ya mejora a quien solo usa unidades.
2. **La raíz del equipo sin cifrar**: `tipo=equipo`, carpeta propia o
   personal, `PASOS_EQUIPO` sin «Cifrado», la ruta resuelta y el aviso de otro
   cliente de sincronización en «Parejas», y la raíz como una raíz atendida más.
   Como hasta la fase 4 no hay «Abrir» en la bandeja, la ventana de la raíz se
   abre con `agente.py abrir`, desde un acceso «prdrive» en el menú del sistema
   que pone el instalador (el lanzador de la sección 5, adelantado).
3. **Cifrado local con VeraCrypt**: el paso «Cifrado» del equipo,
   Desbloquear/Bloquear en el agente, `pedir_al_iniciar` elegido en el
   asistente, la letra fija, `raiz_fisica()` con raíces extra y «Expulsar» →
   «Bloquear». Se prueba en Windows real antes de publicarlo, como se hizo con
   la unidad G:. Hecho así, y en cinco cosas distinto de lo escrito arriba:
   - **Dónde:** el contenedor va en `<carpeta>-cifrado/` junto a la carpeta de
     «Carpeta» (`~/PRDRIVE-cifrado/`), y en Linux se monta en esa carpeta
     (`~/PRDRIVE`). En Windows esa carpeta no se usa: la raíz es la letra. Con
     la carpeta personal no se ofrece cifrar.
   - **Sistema de ficheros de dentro:** NTFS en Windows y exFAT en Linux. Un
     ext4 recién hecho por VeraCrypt es de root, y exFAT se monta con el uid
     del usuario.
   - **Fuera solo va la marca** (`.prdrive-vestibulo`), sin «Abrir/Expulsar
     PRDRIVE» ni guía: la raíz del equipo la abre y la cierra el agente.
   - **«Bloquear» va por `agente.pide`**, no por `state/servicio.pide`, que es
     de la fase 5. Por eso la ventana de runsync no se cierra con
     `daemon.stop`: no lo escucha. El botón «Bloquear» se lo pide al agente y
     cierra su propia ventana; el agente espera a que esa ventana se vaya
     (hasta un minuto) y, si sigue abierta, lo dice y no bloquea.
   - **`agente.py abrir` con la raíz cerrada** le pide al agente
     «desbloquear» y abre la ventana en cuanto la raíz aparece. Es lo que hace
     el acceso del menú.
4. **Bandeja en Windows**, con la detección por `WM_DEVICECHANGE` montada sobre
   su ventana y la casilla de `pedir_al_iniciar`. Hecho así, y en cinco cosas
   distinto de lo escrito arriba:
   - **La ventana oculta es de nivel superior, no de solo mensajes.** Las de
     solo mensajes no reciben difusiones, y `WM_DEVICECHANGE` de un volumen
     (también el de VeraCrypt) y `TaskbarCreated` lo son. Nunca se enseña.
   - **Qué enseña la bandeja lo decide `ui/bandeja.py`, puro**, a partir del
     resumen del agente (el de `estado.json`), y cada entrada del menú lleva
     peticiones con la forma del buzón. El agente las recibe por una cola en
     memoria que atiende junto a `agente.pide`: un solo camino. Dos
     peticiones nuevas: `abrir` (la ventana de una raíz; con la raíz cifrada
     bloqueada, desbloquea antes y la abre al verla) y `despertar` (vuelta de
     la suspensión).
   - **El menú sale con cualquiera de los dos botones**, y «Abrir» de la raíz
     del equipo va en negrita. El doble clic no hace nada aparte.
   - **«Cerrar el agente»** está en el menú, aunque no estaba en la lista:
     no hay otra forma de quitar un icono de la bandeja. Vuelve a arrancar al
     iniciar sesión.
   - **Los iconos llevan el estado en una pastilla de color** en la esquina
     (azul sincronizando, ámbar aviso, oscura con candado bloqueada; la pausa
     además pone el campo gris), porque a 16 px lo que se lee es el color.
     Una raíz cifrada bloqueada no es un aviso, y una red de uso medido o la
     batería usan el icono de pausa.
5. **Ventana ↔ agente**: la línea del agente, los dos buzones
   (`servicio.pide` y `agente.pide`), añadir una raíz a un agente ya instalado y
   «Actualizar».
6. **Bandeja en Linux**: la mitad que exporta objetos de `common/dbus.py`,
   `org.kde.StatusNotifierItem` + `com.canonical.dbusmenu`, y la caída al
   lanzador cuando no hay `StatusNotifierWatcher`. Se prueba en real en KDE, en
   GNOME con AppIndicator (Ubuntu) y en GNOME sin ella (Fedora).

Para después: parejas ejecutadas en el propio proceso, reaccionar a los cambios
de ficheros, `rclone rcd`, sincronizar la unidad con el equipo sin pasar por el
remoto, «Bloquear al suspender» como ajuste y un «No volver a preguntar» para
unidades ajenas.

## Pruebas

- `test_planificador.py`: tabla de casos con un reloj de prueba (espera
  creciente, batería, red de uso medido, sin conexión, raíz bloqueada, cola
  única, «Sincronizar ahora»).
- `test_unidad_nueva.py`: comprueba que
  - sin respuesta en `espera_unidad_nueva` cuenta como «Ahora no»;
  - «Ahora no» dura hasta que la raíz desaparece y se vuelve a preguntar al
    reaparecer;
  - una respuesta tardía de la ventana se ignora;
  - el «Atender» de la bandeja funciona mientras sigue conectada;
  - sin entorno gráfico es «Ahora no» al momento;
  - **antes del sí no se lanza ningún proceso con rutas de la unidad**.
- Raíz del equipo: `local = "."` es un `ConfigError` con `tipo=equipo`;
  `ruta_local_relativa()` con la carpeta personal; el aviso de OneDrive o
  Dropbox con sus ubicaciones falsas.
- `test_dbus.py`, con un bus falso sobre un `socketpair`, comprueba:
  - la serialización contra los ejemplos de la especificación (firmas,
    alineación, `a{sv}`, `(iiay)`);
  - el saludo `EXTERNAL`;
  - una llamada con su respuesta, y un error;
  - que el `StatusNotifierItem` y el `dbusmenu` exportados contestan a lo que
    pregunta un `StatusNotifierWatcher`;
  - la caída al lanzador cuando no hay ninguno.
- `test_agente_contrato.py`: raíces falsas con `daemon.lock.json`,
  `daemon.stop` y `ui.lock.json` escritos como lo haría un `runsync` viejo.
  Comprueba la pausa, el apartarse ante otro servicio y la vuelta.
- `test_agente_veracrypt.py`: con un `veracrypt` falso (como en
  `test_vestibulo.py`), comprueba:
  - la orden de abrir no lleva nunca `/password` y sí `/letter` y `rm`;
  - «abierto» se decide al ver el id, no por la salida del proceso;
  - la vuelta al estado bloqueado solo con el `.hc` libre;
  - con `pedir_al_iniciar` desactivado no se lanza VeraCrypt al arrancar; con
    él activado se lanza una vez y no se repite tras cancelar;
  - un `ajuste` pedido por `agente.pide` lo escribe el agente, no la ventana;
  - el aviso por el punto de montaje con contenido;
  - que `raiz_fisica()` encuentra la carpeta del contenedor por las raíces
    extra.
- Registro: el texto del XML y del `.desktop`, como ya hace penwatch. Se
  comprueba también que penwatch sigue sin importar el proyecto.
- `test_tk_medidas.py` cubre los pasos nuevos del asistente.
- La bandeja, los avisos y VeraCrypt se sustituyen en todos los tests. La prueba
  de verdad se hace en Windows y Linux reales y se apunta en
  `docs/superpowers/pruebas/`, con los mismos casos que la de la unidad G:
  (crear, abrir, bloquear con un fichero abierto, volumen fantasma tras
  suspender).
