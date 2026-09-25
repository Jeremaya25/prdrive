# Instalación en el equipo: prdrive residente

Fecha: 2026-09-25 · Estado: **borrador**, sin implementar · Versión objetivo: 0.4.0

## Qué se pide

Un tercer tipo de instalación, además de «unidad sin cifrar» y «unidad cifrada»:
**prdrive instalado en el ordenador**. Corre en segundo plano de forma eficiente,
hace todo lo que hoy hace `runsync` y deja sitio a funciones futuras. Puede ir
**sin cifrar o cifrado en el propio equipo con VeraCrypt**.

## Decidido al plantearlo

- **Las dos cosas.** El programa residente sincroniza **sus propias parejas**
  (carpetas del equipo ↔ remoto) **y atiende a cualquier unidad prdrive** que se
  enchufe en ese equipo.
- **Icono en la bandeja**: estado, «Sincronizar ahora», «Abrir», «Pausar» y,
  si hay contenedor, «Desbloquear» y «Bloquear».
- **Windows y Linux** desde la primera versión.
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

**La raíz del equipo sin cifrar** (`DEVICE_ROOT`):

```
~/PRDRIVE/                   (C:\Users\<u>\PRDRIVE)
├── .prdrive/                oculto, la misma estructura que en una unidad
│   ├── PRDRIVE              id=… y además tipo=equipo
│   ├── bin/<arch>/          rclone. No lleva runtime: la lanza el agente.
│   ├── rclone.conf, keys/   la clave, en el disco del equipo SIN cifrar
│   └── state/
└── obsidian/ …              las parejas, relativas a la raíz
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
- **La carpeta de las parejas es la raíz, y solo la raíz** (v1). La regla de
  `pair_editor.ruta_local_relativa()` no cambia (pregunta abierta 1).
- **La pareja de la raíz entera (`local = "."`) queda prohibida en un equipo.**
  Sería el mismo `.prdrive/` con la clave dentro.
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
  `nada`. Una unidad prdrive que no está en la lista provoca un aviso («Se ha
  conectado PRDRIVE-2. ¿Atenderla en este equipo?») y nunca se sincroniza sin
  preguntar.
- **Las parejas y el intervalo siguen siendo de la raíz** (`ui_prefs.json` >
  `[daemon]`, `prefs.startup_defaults()`). En el equipo solo se guarda lo que es
  del equipo, igual que decidió el issue #14.
- **Unidades cifradas con VeraCrypt:** el vestíbulo y `open_container()` se
  reutilizan tal cual, una vez por conexión, como en penwatch.
- **Sustituye a penwatch en ese equipo.** Instalar el agente importa el
  `device_id` y el modo de `watch.json` a la lista y desinstala penwatch, y lo
  dice. `penwatch` sigue existiendo para los equipos sin agente.

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
  - **`agente.json` solo lo escribe el agente.** La ventana es el código de la
    raíz, que puede ir en otra versión, así que no toca la configuración del
    equipo: pide el cambio con `servicio.pide` (`ajuste`) y el agente lo aplica.
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
- **Linux, avisos:** `org.freedesktop.Notifications.Notify`. Sin D-Bus, el aviso
  se queda en el diario, que es la misma caída que tiene hoy `avisar_fallo()`.
- **Linux, bandeja:** es **la parte con más riesgo del plan**. La norma actual es
  StatusNotifierItem, y exige *exportar* un objeto en el bus: autenticación
  EXTERNAL, serialización, propiedades y señales. Serían unas 600-900 líneas de
  cliente D-Bus propio, con el mismo espíritu que `ui/qr.py`. Además, **GNOME no
  tiene bandeja** sin la extensión AppIndicator: Ubuntu la trae y Fedora no.
  «Paridad» significa, por tanto, **las mismas funciones**, pero no siempre la
  misma superficie. Sin bandeja queda un lanzador `.desktop` «prdrive» que
  arranca el agente o, si ya está vivo, le pide abrir la ventana (o
  desbloquear), más los avisos con el estado.
- **La ventana ↔ el agente, sin puertos.**
  - La ventana escribe `state/servicio.pide` en su raíz: `reanudar`, `bloquear`
    o `pasada` con sus parejas.
  - El agente lo sondea igual que `daemon.stop`.
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
  NetworkManager. Por defecto **se pausa**. «Sincronizar ahora» siempre se salta
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
1 Carpeta         dónde va (por defecto ~/PRDRIVE); ¿ya hay un prdrive ahí?
2 Cifrado         ninguno / VeraCrypt: contenedor, tamaño, letra o punto de
                  montaje; lo crea, lo monta y fija state.device_root
3 Conexión        igual
4 Comprobaciones  igual
5 Instalación     .prdrive/ + rclone en la raíz; agente + runtime en el equipo
6 Parejas         igual, y las rutas por debajo de la raíz
7 Inicialización  --resync de las bisync
8 Unidades        qué unidades de la flota atiende y cómo (lista de devices/)
9 Arranque        registrar el agente al iniciar sesión y arrancarlo
10 Verificación
```

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

## Preguntas abiertas

1. **¿La raíz es una carpeta dedicada (`~/PRDRIVE`) o la carpeta personal
   (`~`)?** Con la dedicada, el límite queda claro y nada de fuera se toca: es el
   modelo de Dropbox. Con la carpeta personal se puede sincronizar
   `~/Documentos/Obsidian` sin moverlo, pero se pierde ese límite y muchas parejas
   del catálogo (`sync-data/…`) caerían sueltas en `~`. Con VeraCrypt la pregunta
   no existe: la raíz es el volumen. **Propuesta: dedicada en la v1.**
2. **¿Una instalación en el equipo sin parejas propias**, es decir, solo el
   agente atendiendo unidades? Hoy `parse_config()` rechaza un config sin
   `[[pair]]`. **Propuesta: permitirlo solo con `tipo=equipo`.**
3. **¿Cuánto espera el aviso de «unidad nueva»** antes de dar la respuesta por
   «no»?
4. **Bandeja en Linux:** ¿se acepta el cliente D-Bus propio, o basta en la v1 con
   el lanzador y los avisos?

Resueltas:

- **Pedir la contraseña al iniciar sesión:** es configurable
  (`pedir_al_iniciar`) y viene activado por defecto (sección 4, «Abrir»).
- **Bloquear al suspender:** no entra en la v1. Será un ajuste futuro,
  desactivado por defecto (sección 4, «Cerrar»).

## Fases

Cada fase se puede publicar por separado y deja el proyecto funcionando:

1. **El agente sin bandeja**, con unidades: su sitio en el equipo, el
   planificador, la cola, el contrato de la sección 3, la sustitución de
   penwatch, la moderación y los avisos nativos. Ya mejora a quien solo usa
   unidades.
2. **La raíz del equipo sin cifrar**: `tipo=equipo`, `PASOS_EQUIPO` sin
   «Cifrado», y la raíz como una raíz atendida más.
3. **Cifrado local con VeraCrypt**: el paso «Cifrado» del equipo,
   Desbloquear/Bloquear en el agente, `pedir_al_iniciar` elegido en el
   asistente, la letra fija, `raiz_fisica()` con raíces extra y «Expulsar» →
   «Bloquear». Se prueba en Windows real antes de publicarlo, como se hizo con
   la unidad G:.
4. **Bandeja en Windows**, con la detección por `WM_DEVICECHANGE` montada sobre
   su ventana y la casilla de `pedir_al_iniciar`.
5. **Ventana ↔ agente**: la línea del agente, `servicio.pide` (con `ajuste`) y
   «Actualizar».
6. **Bandeja en Linux** (StatusNotifierItem) con la caída al lanzador.

Para después: parejas ejecutadas en el propio proceso, reaccionar a los cambios
de ficheros, `rclone rcd`, sincronizar la unidad con el equipo sin pasar por el
remoto y «Bloquear al suspender» como ajuste.

## Pruebas

- `test_planificador.py`: tabla de casos con un reloj de prueba (espera
  creciente, batería, red de uso medido, sin conexión, raíz bloqueada, cola
  única, «Sincronizar ahora»).
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
  - un `ajuste` pedido por `servicio.pide` lo escribe el agente, no la ventana;
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
