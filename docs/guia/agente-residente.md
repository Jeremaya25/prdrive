[← Guías](README.md)

# El agente residente

prdrive instalado en el ordenador: atiende las unidades que enchufas y, si quieres, una carpeta del propio equipo.

La otra forma de instalar: **prdrive en el ordenador**, como un proceso de tu
usuario que arranca al iniciar sesión, corre en segundo plano y atiende las
unidades prdrive que enchufas en ese equipo. Es el sucesor de
[el vigilante](servicio-y-vigilante.md#el-vigilante): donde se instala, lo sustituye (el instalador
pasa a su lista la unidad que vigilaba penwatch y lo desinstala, y lo dice).

```bash
python prdrive-install.py                      # el asistente → «En este equipo»
python prdrive-install.py --instalar-agente    # lo mismo, sin ventanas
python prdrive-install.py --desinstalar-agente # quitarlo (no toca ninguna unidad)
```

Puede sincronizar además **una carpeta del propio equipo**, la raíz del equipo
(abajo), o no tener ninguna y solo atender unidades: la instalación **«solo
agente»**. El diseño completo está en
`docs/superpowers/specs/2026-09-25-instalacion-en-el-equipo-design.md`.

- **Vive fuera de toda unidad**, en `%LOCALAPPDATA%\prdrive\` o en
  `~/.local/share/prdrive/`, con **su propio Python** (python-build-standalone,
  descargado y comprobado como el de las unidades). Ahí no hay ningún secreto: ni
  clave, ni `rclone.conf`, ni listados. Cada unidad trae los suyos.
- **Cada unidad ejecuta su propio código.** Cada pasada es el `sync.py` de esa
  unidad, lanzado como proceso aparte con el Python del agente y el directorio de
  trabajo fuera de ella: una unidad de otra versión funciona, un rclone colgado no
  tumba al agente, y entre pasadas no queda nada abierto en la unidad, así que se
  puede expulsar.
- **Una pasada a la vez en todo el equipo**, sea de la unidad que sea: ahorra
  ancho de banda y evita que dos unidades con la misma pareja vayan contra la
  misma carpeta del remoto a la vez.
- **Nunca sincroniza una unidad sin preguntar.** La primera vez que se enchufa
  una que no está en su lista, avisa («Se ha conectado PRDRIVE-2. ¿Atenderla en
  este equipo?») y abre una ventanita con cuenta atrás (2 minutos por defecto).
  **«Atender»** la añade en modo `daemon`; **«Ahora no»** —o no contestar— vale
  solo para esa conexión: la próxima vez que la enchufes, vuelve a preguntar.
  Antes del sí no se ejecuta nada de la unidad: solo se leen su id y su nombre.
  Sin escritorio, cuenta como «Ahora no» al momento, y el diario dice cómo
  atenderla: `python agente.py atender <id>`.
- **Qué hace con cada unidad** es su modo: `ui` abre su ventana, `daemon` la
  sincroniza en segundo plano, `sync` hace una pasada al enchufarla y `nada`, nada.
  Las parejas y el intervalo siguen siendo **los del servicio de la unidad**, los
  que se eligen en su ventana.
- **Solo atiende unidades con la 0.5.0 o posterior.** Sincroniza con **su propio
  rclone**, el fijado, que baja al instalarse, y no con el que lleva la unidad;
  las unidades de antes no saben usarlo, así que el agente no las atiende (ni
  pregunta por ellas) hasta que las actualices, y lo dice.
- **Recuerda el código de cada unidad que atiendes.** Si al enchufarla trae otro
  (la has actualizado, o no es tu unidad aunque lleve su id), no ejecuta nada
  suyo y vuelve a preguntar, diciendo que su código ha cambiado.
- **Atiende el [llavero](llavero.md)** de una unidad que lo lleve, sea cual sea
  su modo: mientras KeePassXC está abierto, lo de otros dispositivos llega cada
  5 minutos y lo que guardas sube solo. Su desplegable lleva **Abrir llavero**;
  si la base tiene dos versiones, avisa; y si quitas la unidad sin expulsar,
  deja el navegador como estaba y, en Linux, cierra KeePassXC, que allí no se
  va con la unidad.
- **Hace de servicio de la unidad con sus mismos ficheros** (`daemon.lock.json`,
  `daemon.stop`, `ui.lock.json`). **El único cambio que se nota: abrir la ventana de la unidad ya no apaga el
  servicio para siempre, lo pausa mientras está abierta.** Si el agente la
  sincroniza en segundo plano, la ventana no ofrece «Iniciar servicio» sino
  **«Pausar»**: el agente no vuelve al cerrarla, ni aunque se reinicie, hasta
  que pulses **«Reanudar»** en esa misma ventana (vuelve en cuanto la cierras,
  con una pasada). Es la pausa de esa unidad sola, y el icono de la bandeja la
  enseña con su nombre. En cualquier otro caso (otro modo, o el agente parado)
  sigue estando «Iniciar servicio», que arranca el servicio de siempre, y el
  agente se aparta: un servicio por unidad, el que tenga el lock. Para pararlo
  todo, «Pausar» en la bandeja o `python agente.py pausa` (y `sigue`; con esa
  pausa puesta, la ventana ofrece «Reanudar todo»).
- **La ventana de la unidad dice qué hace el agente con ella**, si está en pausa
  y si no está en marcha, y su botón **«Cambiar…»** (o **«Atender…»**, si no la
  tiene en su lista) le pide otro modo. La ventana no escribe la configuración
  del equipo: se lo pide al agente por su buzón (`agente.pide`), y lo que es de
  una unidad («pausar», «reanudar», «bloquear») por el de la unidad,
  `.prdrive/state/servicio.pide`.
- **Se actualiza solo, cuando se lo pides.** Mira de vez en cuando si hay una
  versión nueva y avisa una vez; **«Actualizar a la vX»** en la bandeja (o
  `python agente.py actualizar`) baja el código de la release, lo comprueba y
  ejecuta su instalador (`prdrive-install.py --update-agente`): el agente nuevo
  se pone al lado del viejo, se vuelve a registrar y arranca, y la raíz de este
  equipo, si está abierta, pasa también a la versión nueva. Su lista y sus
  ajustes no se tocan.
- **Pone al día tus unidades.** Si una unidad de su lista (o la raíz de este
  equipo) lleva un programa más antiguo que el del agente, lo avisa una vez y su
  desplegable en la bandeja ofrece **«Actualizar a la vX»** (o `python agente.py
  actualizar <id>`): baja el código de la versión del agente y lo pone en la
  unidad, como haría su ventana, conservando su configuración, sus claves y su
  estado. Espera a que acabe la pareja en curso y no la sincroniza mientras
  tanto; con su ventana abierta no lo hace (actualízala desde ella). Al acabar
  no vuelve a preguntar por su código, salvo que ya hubiera cambiado antes.
  Sirve también para las unidades de antes de la 0.5.0, que así vuelve a
  atender. Volver a pasar el asistente con el agente de la misma
  versión no lo reinstala: solo le pide lo nuevo.
- **Se modera solo.** Con batería por debajo del 20 %, en una red de uso medido
  o con el modo de ahorro de energía del sistema puesto (el «ahorro de batería» o
  «ahorro de energía» de Windows, el perfil «ahorro de energía» de GNOME o KDE),
  también enchufado, no lanza nada (en la red de uso medido, nada salvo el
  llavero, que pesa poco y es lo que más importa tener al día); si un remoto
  no contesta, deja de lanzar pareja tras pareja contra él y lo sondea cada 5
  minutos; tras un fallo, cada pareja espera el doble de su intervalo (hasta 4
  horas), y a cero con la primera pasada buena.
  «Sincronizar ahora» (`python agente.py pasada <id>`) se salta todo eso. Nunca
  hace un `--resync` por su cuenta.
- **Avisa con los avisos del sistema**, sin ventanas propias, y solo cuando una
  pareja **empieza** a fallar o un remoto se queda sin conexión. En Linux por
  D-Bus (un cliente propio, sin dependencias: `common/dbus.py`); en Windows con
  el globo del área de notificación. Sin avisos, queda en su diario,
  `agente.log`.
- **Tiene un icono en la bandeja**, en Windows y en Linux, que dice cómo va (al día,
  sincronizando, un aviso, en pausa, la raíz cifrada bloqueada) y, con clic
  derecho o izquierdo, un menú: **Abrir** la raíz de este equipo o una unidad
  de su lista, **Sincronizar ahora**, **Expulsar** (una unidad extraíble de su
  lista: la suelta para que puedas quitarla; si algo la tiene abierta, no la
  fuerza y te lo dice), **Pausar**/**Reanudar**, **Desbloquear**
  y **Bloquear** la raíz cifrada con la casilla «Pedir la contraseña al iniciar
  sesión», **Atender…** una unidad a la que dijiste «Ahora no» mientras siga
  enchufada, y **Cerrar el agente** (vuelve a arrancar al iniciar sesión).
  Abajo del todo dice qué versión lleva el agente y, dentro del desplegable de
  cada dispositivo, la de su programa. En
  Linux es un StatusNotifierItem (KDE, y GNOME con la extensión «AppIndicator
  and KStatusNotifierItem Support», que Ubuntu ya trae), hablado por D-Bus sin
  dependencias. **Donde el escritorio no tiene bandeja** (GNOME sin esa
  extensión), el acceso «prdrive» del menú de aplicaciones hace sus veces:
  arranca el agente si no está, abre la ventana de la raíz de este equipo o,
  sin raíz, dice con un aviso cómo va; si la bandeja aparece después, el icono
  se pone solo. La «Verificación» del asistente dice si falta.
- **Detecta las unidades** con el mismo recorrido que penwatch, pero sin sondear
  cada 5 segundos: en Linux se despierta cuando cambian los montajes, y en
  Windows con el aviso de dispositivo que recibe la ventana oculta de la bandeja. Las
  unidades VeraCrypt de su lista se abren como con penwatch: VeraCrypt pide la
  contraseña en su ventana, una vez por conexión.
- **Sincroniza al cambiar los ficheros, si una pareja lo pide.** Con `watch = true`
  (solo donde el local es origen: bisync, up y up-mirror) el agente escucha los
  avisos del sistema sobre la carpeta de la pareja (inotify en Linux; en
  Windows, con la bandeja abierta) y, 20 s después de que dejen de cambiar,
  adelanta su pasada al intervalo; nunca dos pasadas de la misma pareja con
  menos de 2 minutos entre ellas. Donde el sistema no avisa (una carpeta de
  red, un volumen de VeraCrypt en Windows) recorre la carpeta sin abrir
  ficheros: cada 10 s mientras cambia y cada 2 minutos cuando está quieta, así
  que un cambio tras un rato quieta se ve hasta 2 minutos después;
  `agente.py status` dice qué parejas se recorren y por qué. En Windows el
  agente tiene abierta la carpeta que escucha: «Quitar hardware de forma
  segura» y «Expulsar» la sueltan antes de quitar la unidad. Es una pasada
  corriente: en pausa, con batería, en ahorro de energía o en una red de uso
  medido espera como las demás. No ve los cambios del remoto, ni lo que se
  cambie mientras la pasada corre, y una carpeta que se recorre con más de
  20 000 entradas deja de vigilarse (lo dice el diario) y sigue por su
  intervalo. Detalles en `sync_config.example.toml`.
- **Se registra por usuario, sin administrador**: en Windows con una tarea
  programada; en Linux con un autostart del escritorio (y no con systemd: los
  avisos y la pregunta por una unidad nueva necesitan la sesión gráfica).

```bash
python agente.py status               # qué atiende y cómo (en su carpeta del equipo)
python agente.py modo <id> daemon     # ui | daemon | sync | nada
python agente.py pasada <id> [pareja] # sincronizar ahora
python agente.py pausa | sigue
python agente.py abrir [id]           # la ventana de la raíz (o arranca el agente / dice cómo va)
python agente.py desbloquear | bloquear          # la raíz cifrada de este equipo
python agente.py ajuste pedir_al_iniciar no      # no pedir su contraseña al entrar
python agente.py actualizar           # la versión nueva, como «Actualizar» de la bandeja
python agente.py actualizar <id>      # esa unidad, a la versión del agente
python agente.py expulsar <id>        # soltar esa unidad extraíble, como «Expulsar» de la bandeja
```

Esas órdenes no tocan nada por sí mismas: dejan la petición en el buzón del
agente (`agente.pide`), y él escribe su configuración. **Sin probar todavía en un
Windows real**: la tarea programada, la bandeja y los avisos (`Shell_NotifyIconW`), la batería y el ahorro de energía,
la red de uso medido (`INetworkCostManager`), el acceso del menú Inicio
(`IShellLinkW`) y «Actualizar»; ni en un escritorio Linux de verdad la
bandeja (StatusNotifierItem y dbusmenu).

## La raíz del equipo

Una carpeta del ordenador con `.prdrive/` dentro es, para el motor, un
dispositivo más: `sync.py`, la ventana, «Reparación» y la flota no saben que no
está en un USB. El asistente «En este equipo» pregunta en su paso **Carpeta**
cuál:

- **Una carpeta propia** (`~/PRDRIVE` por defecto, o la que escribas): prdrive y
  tus parejas dentro, como la carpeta de Dropbox. Nada de fuera se toca.
- **Tu carpeta personal** (`~`): sincroniza carpetas que ya tienes, como
  `Documentos/Obsidian`, sin moverlas. A cambio, el límite es todo tu usuario.
- **Ninguna**: solo atender unidades.

Se elige al instalar y **no se cambia después**: mover la raíz deja cada pareja
sin su carpeta (y `sync.py` se niega a sincronizar una línea base sin su carpeta
local, que es lo que se quiere). Cambiarla es volver a instalar.

Con raíz, el recorrido es el de una unidad con otra cabeza y otra cola:
**Carpeta → Cifrado → Conexión → Comprobaciones → Instalación → Parejas → Inicialización →
Unidades → Arranque → Verificación**. Lo que cambia:

- **Qué lleva la raíz:** `.prdrive/` con el programa, rclone *solo para este
  equipo*, la conexión y su clave, y un fichero de control con `tipo=equipo`. Sin
  Python propio ni lanzadores: la sincroniza el agente con el suyo, y su ventana
  se abre desde el acceso **«prdrive» del menú del sistema** (`python agente.py
  abrir`).
- **La clave queda en claro en el disco del equipo**, como en una unidad sin
  cifrar. El asistente lo dice en ámbar y, en Windows, si el disco tiene BitLocker
  activado. Es información, no una exigencia.
- **En «Parejas» se ve dónde cae cada una en este equipo**, y se puede cambiar su
  ruta solo aquí (la pareja queda como «modificada aquí»): con la carpeta
  personal, una ruta pensada para una unidad (`sync-data/…`) caería suelta en tu
  carpeta de usuario. Si la carpeta ya la sincroniza **OneDrive o Dropbox**, lo
  dice en ámbar: dos programas sincronizando lo mismo se pisan los borrados. Se
  sabe sin adivinar, por las variables de OneDrive y el `info.json` de Dropbox.
- **La pareja de la raíz entera (`local = "."`) no vale en un equipo**, ni una que
  salga de ella (`..`, una ruta absoluta): sería sincronizar el propio `.prdrive/`,
  con la clave, y con la carpeta personal, todo tu usuario. Lo rechaza el propio
  `sync.py` al leer el config, así que un TOML editado a mano tampoco se lo salta.
- **El agente la atiende como a una unidad**, con el mismo contrato: si abres su
  ventana, se pausa; si la carpeta desaparece (la has movido), avisa una vez y no
  lanza nada hasta que vuelve.
- **En la flota** su nota lleva `tipo = "equipo"`, y la ventana de la flota la
  marca como «(equipo)». El paso «Unidades» puede ofrecer las unidades apuntadas
  en la flota, pero entran como «preguntar al enchufarla»: nunca en la lista sin
  que se diga que sí.
- **Desinstalar el agente nunca borra la raíz**: tiene tus carpetas, y la clave.
  Lo dice, con la ruta, para que la borres a mano si ya no la quieres.

### Cifrada con VeraCrypt

Con una carpeta propia, el paso **Cifrado** puede meter la raíz en un
contenedor VeraCrypt: `~/PRDRIVE-cifrado/PRDRIVE.hc`, que se monta siempre en la
misma letra en Windows (`P:` si está libre: los programas apuntan a la raíz, y un
almacén de Obsidian en `P:\obsidian` no puede amanecer en `Q:`) y en `~/PRDRIVE`
en Linux. Dentro van el programa, la clave, el estado y las parejas; fuera, solo
el contenedor y una marca con su id.

- **En Windows no hace falta tenerlo instalado.** Sin VeraCrypt, el paso ofrece
  **Descargar VeraCrypt Portable** —el mismo paquete oficial, comprobado, que
  usan las unidades— y el agente se lleva una copia a su carpeta
  (`veracrypt/<versión>/`), que vuelve a comprobar contra su sello antes de cada
  uso. Sin instalar nada, pero **con el aviso de administrador (UAC) cada vez que
  abre o cierra la raíz**: al crearla, al desbloquearla —también al iniciar sesión
  si se pide la contraseña— y al bloquearla. VeraCrypt no puede cargar su driver
  sin ser administrador; instalado, lo carga una vez y ya no pregunta. Si hay uno
  instalado se usa ese, y si lo instalas después el agente pasa a usarlo solo.
  En Linux, sin VeraCrypt instalado, lo mismo con el AppImage oficial
  (**Descargar VeraCrypt (AppImage)**); con uno o con otro, VeraCrypt pide
  además la contraseña de administrador para montar.
- **La contraseña nunca pasa por prdrive.** El asistente la usa una vez, para
  crear y montar, y deja el contenedor abierto. Desde ahí lo abre el agente con
  la ventana de VeraCrypt: al iniciar sesión (una vez; si cancelas, hasta que
  pidas `agente.py desbloquear`), o nunca, si desmarcas «Pedir la contraseña al
  iniciar sesión» (en el asistente, y después en la bandeja o en «Ajustes» de su
  ventana). Con la raíz cerrada, el acceso «prdrive» del menú la
  desbloquea y abre la ventana.
- **Bloquear** es el botón del pie de su ventana (donde una unidad cifrada tiene
  «Expulsar»), o `agente.py bloquear`. El agente acaba la pareja en curso y le
  pide a VeraCrypt que desmonte **sin forzar**: si algún programa tiene algo
  abierto dentro, VeraCrypt pregunta, y tú decides. Cerrada, no hay nada que
  sincronizar ni que avisar; las unidades se siguen atendiendo.
- **No cambia de letra ni de sitio por su cuenta.** Si la letra la tiene otra
  unidad, o en `~/PRDRIVE` hay cosas con el contenedor cerrado (quedarían
  tapadas), lo dice y no monta. Si la letra se queda «colgada» tras suspender (el
  volumen fantasma que ya conocen las unidades cifradas), no la atiende y te dice
  que la bloquees y la vuelvas a desbloquear.
- **Ni favoritos de VeraCrypt ni tocar su configuración**, como en las unidades.
  Si en sus Preferencias tienes que desmonte al suspender, para el agente es como
  desenchufar una unidad.
- Pasar a cifrado una raíz que iba en claro **deja la vieja donde estaba**, con
  la clave: el asistente lo dice en rojo, y la borras tú cuando compruebes que
  no falta nada. Desinstalar el agente no cierra ni borra el contenedor.

**Sin probar todavía en un equipo real**, ni en Windows ni en Linux. Lo que hay
que comprobar está apuntado en
`docs/superpowers/pruebas/2026-09-25-equipo-pendiente-en-real.md`.
