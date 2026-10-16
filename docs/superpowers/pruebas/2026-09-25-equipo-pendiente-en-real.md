# Lo que falta probar en equipos reales: la instalación en el equipo

Fecha: 2026-09-25 · Diseño:
`docs/superpowers/specs/2026-09-25-instalacion-en-el-equipo-design.md` ·
Estado: **lista viva**. Se amplía con cada fase y se vacía cuando cada prueba
se hace de verdad.

Los tests de `tests/` sustituyen todo lo que toca el sistema: la tarea
programada, los avisos, VeraCrypt, la batería, la red y el menú. Así que nada de
esta lista está visto funcionar. Aquí se apunta **qué hay que ver en un equipo
de verdad antes de publicar la v1**, para no tener que reconstruirlo de memoria
cuando las seis fases estén hechas. Con esta lista se escribirá el plan de
pruebas completo, como el de la unidad G:
(`2026-09-24-veracrypt-unidad-g.md`), y sus resultados irán en un fichero
aparte, al lado de este.

Cada prueba lleva:
- un código;
- dónde se hace;
- qué hacer;
- qué se espera ver;
- el código que se pone a prueba.

«Lo esperado» sale del código, y en un equipo real manda lo que se vea: si no
coincide, se apunta la discrepancia y no se reinterpreta.

Las filas con «· nube: ok» se han visto en una máquina de usar y tirar de GitHub
Actions (`tests/maquina/`, resultados en `maquina-real-resultados.md`): la
frontera con el sistema, en discos virtuales. Siguen aquí hasta verlas con un
dispositivo de verdad, pero lo que queda por mirar es lo físico.

Equipos que hacen falta:
- **W**: Windows 11 x64;
- **WA**: Windows 11 ARM64, solo donde se dice;
- **L**: Linux con escritorio. Donde importa, KDE, y GNOME con y sin
  AppIndicator.

## Fase 1 — El agente sin bandeja, con unidades

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| A1 | W | Instalar «En este equipo → Ninguna» desde el `.exe`. Cerrar sesión y volver a entrar. | Queda una tarea programada por usuario con el agente (`pythonw.exe … agente.py run`), sin administrador. Tras volver a entrar, `agente.py status` lo da vivo. | `penwatch.task_xml()` / `register_task()`, `install/agente.registrar()` |
| A2 | W | Con penwatch ya instalado y apuntando a una unidad, instalar el agente. | penwatch desinstalado (sin tarea, sin `%LOCALAPPDATA%\prdriveWatch`), su unidad en `agente.json` con su modo, y el asistente lo dice. | `install/agente.quitar_penwatch()`, `de_penwatch()` |
| A3 | L | Lo mismo que A1 en Linux. | `~/.config/autostart/prdrive-agente.desktop` con `Exec=` bien entrecomillado; el agente arranca al entrar en la sesión gráfica. | `penwatch.autostart_desktop()` |
| A4 | W, L | Enchufar una unidad prdrive que no está en la lista. | Un aviso del sistema («Se ha conectado …») y la ventanita con cuenta atrás. «Atender» la añade en `daemon`. Sin contestar, se cierra sola a los 2 min y cuenta como «Ahora no» hasta desenchufarla. | `Agente._preguntar()`, `ui/tk_agente.py` |
| A5 | W, L | Antes de contestar A4, mirar los procesos. | Ningún proceso lleva rutas de la unidad: ni su `runsync.py`, ni `sync.py`, ni rclone. | `Agente._conectar()` |
| A6 | W | Hacer que una pareja empiece a fallar (remoto con una ruta que no existe). | **Un** aviso nativo con `Shell_NotifyIconW` + `NIF_INFO`, que en Windows 10/11 sale como notificación del sistema. Nada más en los ciclos siguientes. | `common/avisos.py` (sin probar nunca en Windows) |
| A7 | L | Lo mismo que A6 en KDE y en GNOME. | Aviso por `org.freedesktop.Notifications.Notify`, con el icono. Sin sesión D-Bus, solo en `agente.log`. | `common/dbus.py`, `common/avisos.py` |
| A8 | W | Portátil a batería, por debajo del 20 %. Después, una red Wi-Fi marcada como «de uso medido». | `agente.py status` dice «batería por debajo del 20 %» / «red de uso medido» y no lanza nada. «Sincronizar ahora» (`agente.py pasada ID`) sí lanza. | `moderacion._energia_windows()`, `_medida_windows()` (`INetworkCostManager` por vtabla) |
| A9 | L | Lo mismo que A8, con NetworkManager marcando la red como medida (`nmcli connection modify … connection.metered yes`). | Igual que A8. | `moderacion._energia_linux()`, `_medida_linux()` |
| A10 | W, L | Desconectar la red con una pareja en marcha. | Un aviso «sin conexión con …»; ya no se lanzan las parejas una a una, sino una sonda cuando vuelve la red (N1–N8) y, si no, cada 30 min (cada 5 donde no se oyen los cambios de red). Al volver la red, sigue sola. | `Agente._fin_de_sonda()`, `pl.sondeo()` |
| A11 | L | Enchufar una unidad y medir cuánto tarda en verla. | Unos segundos, no los 30 del respaldo: `POLLPRI` de `/proc/self/mountinfo`. | `agente.Vigia` |
| A12 | W, L | Con la unidad atendida, abrir su ventana (`runsync.py`) desde la unidad. | El agente se pausa (`status`: «en pausa: hay una ventana…»). Al cerrarla, vuelve a atenderla. «Iniciar servicio» en la ventana: ver V1 y V2 (fase 5). | contrato de la sección 3, `Agente._contrato()` |
| A13 | W | Unidad VeraCrypt de la lista, enchufada cerrada. | VeraCrypt pide la contraseña **una** vez por conexión. Tras «Expulsar» con la unidad puesta no la vuelve a pedir. | `Agente._vestibulos()`, `penwatch.open_container()` |
| A14 | W, L | Desinstalar el agente (`prdrive-install.py --desinstalar-agente`). | Sin tarea ni autostart, sin `%LOCALAPPDATA%\prdrive`; ninguna unidad tocada. | `install/agente.desinstalar()` |
| A15 | WA | A1 en Windows ARM64. | El runtime del agente es el arm64. | `install/agente.poner_runtime()` |

## Fase 2 — La raíz del equipo sin cifrar

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| R1 | W | Instalar con «Una carpeta propia» (`%USERPROFILE%\PRDRIVE`), con un remoto de pruebas. | La raíz tiene `.prdrive\` con `PRDRIVE` (`tipo=equipo`), `bin\x64\rclone.exe`, `rclone.conf` y la clave. No hay `runtime\`, ni `runsync.bat`, ni guía. La inicialización corre con el Python del agente. | `raiz_equipo.instalar()`, `plan_rclone()` |
| R2 | W | Mirar el menú Inicio tras R1. | Una entrada «prdrive» con el icono. Al pulsarla se abre la ventana de la raíz, y el agente se pausa mientras está abierta. | `install/agente.crear_lnk()` (`IShellLinkW` por vtabla, **sin probar**), `agente.py abrir` |
| R3 | L | R1 + R2 en Linux. | `~/.local/share/applications/prdrive.desktop`; en el menú de KDE y en el de GNOME. | `install/agente.menu_desktop()` |
| R4 | W | Con BitLocker activado en `C:` y después sin él, mirar el paso «Instalación». | La línea dice si el disco del sistema está cifrado (`On`) o no. Es solo información. | `raiz_equipo.cifrado_del_disco()` |
| R5 | W | Con OneDrive redirigiendo `Documentos`: instalar con «Tu carpeta personal» y una pareja con `local` en `Documents\…`. | El aviso ámbar en «Parejas» dice que esa carpeta la sincroniza OneDrive. | `raiz_equipo.carpetas_sincronizadas()` (variables `OneDrive*`) |
| R6 | W, L | Lo mismo que R5 con Dropbox instalado. | El mismo aviso, por el `info.json` de Dropbox. | `raiz_equipo._info_dropbox()` |
| R7 | W, L | Renombrar la carpeta de la raíz con el agente en marcha, y devolverle el nombre. | Un solo aviso «no encuentro su carpeta» y nada lanzado mientras falta. Al volver, sigue sola. | `Agente._raices_ausentes()` |
| R8 | W, L | Editar a mano `sync_config.toml` de la raíz con `local = "."` y lanzar una pasada. | `sync.py` se niega con el `ConfigError` de la raíz del equipo; el agente avisa una vez. | `model.problema_local_equipo()` |
| R9 | W, L | Volver a pasar el asistente «En este equipo» con el agente ya instalado y añadir la raíz. | El agente no se reinstala (V7). La raíz entra por el buzón (`añadir_raiz`) y se atiende sin reiniciar. | `install/agente.aplicar_unidades(raiz=)`, `anadir()`, `PIDE_RAIZ` |
| R10 | W | Desinstalar el agente con la raíz puesta. | La raíz sigue en su sitio, el asistente dice dónde, y la entrada del menú Inicio desaparece. | `install/agente.desinstalar()`, `quitar_menu()` |
| R11 | W, L | Mirar la ventana de la flota desde una unidad tras una pasada de la raíz. | La raíz aparece como «Nombre (equipo)» y «En un equipo» en su ficha. | `fleet` `tipo`, `ui/tk_fleet.py` |

## Fase 3 — La raíz del equipo cifrada con VeraCrypt

Hace falta **VeraCrypt instalado** en el equipo (el paso «Cifrado» no ofrece la
opción sin él). Contenedor en una carpeta del disco del sistema; contraseña de
pruebas, nunca una real.

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| C1 | W | Sin VeraCrypt instalado (solo el portable en la caché), llegar al paso «Cifrado» del equipo. | Solo «Sin cifrar», con la frase de cómo instalar VeraCrypt. No se ofrece descargarlo. | `raiz_equipo.veracrypt_instalado()`, `penwatch.installed_veracrypt()` |
| C2 | W | Con VeraCrypt instalado, crear el contenedor en `%USERPROFILE%\PRDRIVE-cifrado`, de 2G, con la letra que proponga (P:). | Se crea disperso (`/dynamic`, NTFS dentro), se monta en esa letra con `/m rm` (sin `$RECYCLE.BIN` dentro) y el asistente sigue sobre `P:\`. Fuera quedan el `.hc` y `.prdrive-vestibulo`, con el mismo id que `P:\.prdrive\PRDRIVE`. | `raiz_equipo.abrir_o_crear()`, `crypto.create_container()` / `mount_container(letra=)`, `raiz_equipo.marcar()` |
| C3 | W | Terminar el asistente de C2 y comprobar `agente.json`. | La raíz lleva `ruta` = `P:\` y su `contenedor`, y `pedir_al_iniciar` es lo que se marcó. El contenedor queda **abierto** y el agente lo atiende. | `install/agente.aplicar_unidades(raiz=, pedir_al_iniciar=)`, `equipo.Unidad.contenedor` |
| C4 | W | Bloquear: `agente.py bloquear`, con la raíz sin nada abierto. | Sin `/silent`, VeraCrypt desmonta. El agente da la raíz por bloqueada **cuando el `.hc` queda libre**. `status`: «bloqueada». | `Agente._bloqueos()`, `agente.bloqueada()`, `vestibulo.retenido()` |
| C5 | W | Bloquear con un fichero de dentro abierto (un `.txt` en el Bloc de notas). | VeraCrypt pregunta si forzar. Con «No», la raíz sigue abierta y atendida, y el diario lo dice. Con «Sí», bloqueada. | idem, «La letra desaparecida no basta» |
| C6 | W | Desbloquear: `agente.py desbloquear`. | La ventana de VeraCrypt pide la contraseña (nunca pasa por prdrive) y monta en **P:**, no en otra letra. Se atiende en cuanto el agente ve el id. | `penwatch.veracrypt_command(None, container, dest)` |
| C7 | W | Ocupar la letra P: (`subst P: C:\Windows\Temp`) y desbloquear. | El agente no se inventa otra letra: avisa de que P: está ocupada y no lanza VeraCrypt. | `Agente._desbloquear()`, `agente.punto_ocupado()` |
| C8 | W | Cerrar sesión con el contenedor cerrado y `pedir_al_iniciar` activado, y volver a entrar. | VeraCrypt pide la contraseña **una** vez. Si se cancela, no vuelve a pedirla hasta `desbloquear`. | `Agente._al_iniciar()` |
| C9 | W | C8 con `pedir_al_iniciar` desactivado (`agente.py ajuste pedir_al_iniciar no`). | No pide nada al entrar; la raíz sale «bloqueada» y las unidades se siguen atendiendo. | idem |
| C10 | W | Suspender el equipo con el contenedor abierto, con la preferencia de VeraCrypt «desmontar al suspender» activada, y volver. | Es una unidad desenchufada: la pasada en curso no cuenta y la raíz sale bloqueada. Si queda la letra con el `.hc` libre (el fantasma de H-10), el agente no la atiende y dice «Bloquear y volver a desbloquear». | `Agente._fantasmas()` |
| C11 | W | Con la raíz abierta, la ventana (acceso «prdrive»): el botón del pie. | Dice «Bloquear», no «Expulsar». Al pulsarlo, se lo pide al agente por `state\servicio.pide` (fase 5; el fichero desaparece en unos segundos), se cierra la ventana y la raíz queda bloqueada como en C4. | `ui/cifrado.bloqueo()` / `pedir_bloqueo()`, `Agente._buzones_de_raices()`, `ui/tk.py` |
| C12 | W | Con la raíz cifrada, «Reparación» con menos de 1 GiB libre en `C:`. | Sale el hallazgo `espacio` (el contenedor es disperso). | `vestibulo.raiz_fisica()` con las raíces extra de `agente.json` |
| C13 | W | Reinstalar cifrado sobre una raíz que iba sin cifrar en la misma carpeta. | Rojo antes de crear, y fila roja en «Verificación»: la instalación en claro sigue ahí y nada la borra. | `crypto.restos_en_claro()` |
| C14 | W | Desinstalar el agente con el contenedor abierto. | Queda abierto, el asistente lo dice, y ni el `.hc` ni la carpeta se tocan. | `install/agente.desinstalar()` |
| C15 | L | C2 en Linux: contenedor en `~/PRDRIVE-cifrado`, montado en `~/PRDRIVE`. | Sin `/dynamic`: se escribe entero, y el asistente avisa de que VeraCrypt pide también la contraseña de administrador. | `crypto.create_command()` / `mount_command()` POSIX |
| C16 | L | Con el contenedor cerrado, dejar un fichero suelto en `~/PRDRIVE` y desbloquear. | El agente no monta encima: avisa de que el punto de montaje tiene contenido. | `agente.punto_ocupado()`, `raiz_equipo.examinar_contenedor()` |
| C17 | L | C4–C6 en Linux (`veracrypt -d <hc>` sin `--non-interactive`, montaje en el punto guardado). Con exFAT dentro, comprobar que el usuario puede escribir sin sudo. | Como en Windows, con el punto de montaje en vez de la letra. «Bloqueada» cuando el punto ya no está montado. La GUI de VeraCrypt con `veracrypt <hc> <punto>` pide la contraseña y monta. | `Agente._bloqueos()` / `_desbloquear()`, `agente.bloqueada()` en Linux |
| C18 | W, L | Tras una pasada con la raíz cifrada, mirar su nota en la flota. | `tipo = "equipo"` y `cifrado = "veracrypt"`; «(equipo, cifrado)» en la ventana de la flota. Con el contenedor cerrado no se publica nada. | `fleet.nota_de()` / `_cifrado()`, `tk_fleet.marca()` |
| C19 | W, L | Con la raíz bloqueada, pulsar el acceso «prdrive» del menú. | Pide desbloquear al agente, VeraCrypt pide la contraseña y la ventana se abre sola en cuanto la raíz aparece (hasta 3 min). | `agente.cmd_abrir()` |
| C20 | W | Reinstalar sobre la raíz cifrada ya abierta (asistente otra vez, «Abrir el contenedor»). | Reconoce el volumen montado sin volver a montarlo, conserva el id, y el agente sigue atendiéndola. | `crypto.mounted_container()` (heurística de Windows: `.hc` retenido + una sola unidad con control) |

## Fase 4 — Bandeja en Windows

Todo lo de `ui/bandeja_windows.Api` (ctypes contra user32 y shell32) está sin
ejecutar: los tests le ponen un Windows de mentira. Lo primero que puede fallar
es la propia llamada (una firma de ctypes mal puesta tumba el hilo de la
bandeja), y entonces el agente sigue sin ella: el diario dice «no he podido
poner la bandeja» y se recorre cada 5 s como antes. Mirar `agente.log` en cada
prueba.

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| B1 | W | Iniciar sesión con el agente instalado. | El icono sale en la bandeja (quizá en el desbordamiento «^»), con la marca y la línea «prdrive · sincronizado hace …» (o lo que toque) al pasar el ratón. Nítido al 100 %, 125 %, 150 % y 200 % (se carga a `SM_CXSMICON` con la densidad declarada). | `Bandeja.arrancar()`, `Api.ventana()` / `icono()` / `notificar()`, `icons.write_bandeja()`, `theme.nitidez()` |
| B2 | W | Iniciar sesión con el agente arrancando antes que la barra de tareas (equipo lento, o reiniciar el Explorador en el Administrador de tareas con el agente en marcha). | El icono aparece al crearse la barra (`TaskbarCreated`) y vuelve tras reiniciar el Explorador. | `Bandeja._mensaje()` con `TaskbarCreated` |
| B3 | W | Clic derecho y clic izquierdo en el icono; pinchar fuera del menú; Esc. | El menú sale donde está el ratón, «Abrir …» en negrita, las casillas marcadas donde toca; al pinchar fuera o con Esc se cierra sin elegir nada. | `Api.menu()`: `SetForegroundWindow` + `TrackPopupMenu(TPM_RETURNCMD)` + `WM_NULL` |
| B4 | W | Cada entrada: las de dentro del desplegable de un dispositivo («Configurar», «Abrir en explorador», «Sincronizar ahora»), «Sincronizar todo ahora» con dos unidades, «Pausar» / «Reanudar», «Cerrar el agente» (ver D1–D8). | Cada una hace lo suyo en uno o dos segundos (el agente se despierta, no espera al tic). «Cerrar el agente» lo termina y quita el icono. Un nombre con `&` sale tal cual. | `bandeja.vista()`, `Agente.pedir()`, `Vigia.despertar()`, `texto_menu()` |
| B5 | W | Los cinco estados: al día, una pasada en marcha, una pareja que falla, en pausa (y en red de uso medido), la raíz cifrada bloqueada. | El icono cambia (pastilla azul, ámbar, campo gris con barras, candado oscuro) y la línea lo dice. Distinguibles a 16 px sobre la barra clara y la oscura. | `bandeja.estado()`, `icons.capas_bandeja()` |
| B6 | W | Enchufar una unidad de la lista; quitarla; abrir y cerrar su VeraCrypt. | Se ve en segundos, no a los 5 s del sondeo: `WM_DEVICECHANGE` despierta la racha. Sin tocar nada, el recorrido de respaldo pasa a cada 30 s (el diario lo delata por los tiempos). Comprobar que la ventana oculta **sí** recibe `DBT_DEVICEARRIVAL` de un volumen y de un montaje de VeraCrypt. | `Bandeja._mensaje()` con `WM_DEVICECHANGE`, `cmd_run()` (`RECORRIDO_RESPALDO`) |
| B7 | W | Enchufar una unidad que no está en la lista y dejar pasar la pregunta. | Su desplegable «PRDRIVE-2 (sin atender)», con la marca de prdrive por icono, solo lleva «Atender…», que la añade a la lista y la atiende. Nunca salen «Configurar» ni «Abrir en explorador» para ella antes del sí. | `bandeja._unidades()`, `PIDE_ATENDER` |
| B8 | W | Raíz cifrada, desde su desplegable: «Desbloquear…», «Bloquear», la casilla «Pedir la contraseña al iniciar sesión», y «Configurar…» con la raíz bloqueada. | Como C4–C9, desde el menú. «Configurar…» con ella bloqueada pide la contraseña y abre la ventana sola al montarse. Cancelar la contraseña: a los ~20 s vuelve a ofrecer «Desbloquear…». La casilla cambia `agente.json` (lo escribe el agente). | `Agente._abrir()`, `_desbloquear(abrir=)`, `_seguir_desbloqueos()`, `PIDE_AJUSTE` |
| B9 | W | Un aviso (una pareja que empieza a fallar, una unidad nueva). | Sale como notificación del sistema **colgada del icono de la bandeja** (sin el icono de paso que aparece y desaparece), con el título y el texto; de aviso si es urgente. | `Bandeja.globo()`, `avisos.GLOBO`, `NIF_INFO` |
| B10 | W | Suspender y volver, con un remoto «sin conexión» (red caída antes de suspender, y de vuelta al despertar). | Al volver se sondea el remoto enseguida y se lee la batería y la red, sin esperar al sondeo de respaldo. | `WM_POWERBROADCAST` / `PBT_APMRESUMEAUTOMATIC`, `PIDE_DESPERTAR` |
| B11 | W | Cerrar sesión y volver a entrar; y `agente.py parar`. | No queda un icono huérfano en la bandeja (`NIM_DELETE` al cerrar); si queda por un cierre a la fuerza, desaparece al pasar el ratón. | `Bandeja.cerrar()`, `WM_DESTROY` |
| B12 | WA | B1, B3 y B6 en Windows ARM64 con el runtime ARM64. | Lo mismo. | ctypes en ARM64 |

## Fase 5 — Ventana ↔ agente

La ventana de una raíz le habla al agente por dos buzones: `state\servicio.pide`
en la raíz (lo de esa raíz: `pausar_raiz`, `reanudar`, `pasada`, `bloquear`) y `agente.pide`
en `%LOCALAPPDATA%\prdrive` (lo del equipo: el modo, un ajuste). Ninguno
tiene más prueba que los tests; lo que hay que ver aquí es que el fichero
aparece, que el agente lo consume en unos segundos y que hace lo que dice.

«Actualizar» (V8–V12) necesita una **release publicada después de esta fase**:
el zip que baja es el que trae `--update-agente`. Para tener algo que
actualizar, instalar el agente de esa release y bajarle el número a mano en
`%LOCALAPPDATA%\prdrive\agente\<versión>\VERSION` (p. ej. `0.3.9`), y
reiniciar el agente (`agente.py parar` y volver a entrar en la sesión).

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| V1 | W, L | Unidad atendida por el agente en modo `daemon`. Abrir su ventana: en el pie, «Pausar» y no «Iniciar servicio». Pulsar «Pausar» y cerrar la ventana; volver a abrirla, marcar otras parejas, «Reanudar» y cerrarla. Otra vez desde la consola (`runsync.py` sin escritorio, opción 3). | Ningún `pythonw` nuevo desde la unidad, y la ventana no se cierra al pulsar. Tras «Pausar», al cerrarla el agente **no** vuelve (`daemon.lock.json` no aparece; `agente.py status`: «en pausa desde su ventana»). Tras «Reanudar», al cerrarla vuelve **enseguida** (sin los 15 s de gracia), con una pasada. Desde la consola, el mensaje dice que el agente es el servicio y vuelve al salir. | `watch.boton_servicio()` / `pedir_servicio()`, `Agente._buzones_de_raices()`, `PIDE_PAUSAR_RAIZ` / `PIDE_REANUDAR`, `runsync._atender()` / `pedir_reanudar()` |
| V2 | W, L | V1 con la unidad en modo `sync`, y otra vez con el agente parado (`agente.py parar`). | El servicio de siempre (un `pythonw` de la unidad con su `daemon.lock.json`), y el agente se aparta mientras vive. | `watch.Resumen.servicio_del_agente` |
| V3 | W, L | La línea del agente en la ventana: con el agente en marcha, en pausa (el «Pausar» de la bandeja), con la unidad pausada desde su ventana, y parado. | Dice qué hace con esa unidad; cada pausa lo dice (la de la bandeja «para todo», con «Reanudar todo» en el pie); parado va en ámbar, dice que arranca al iniciar sesión y el pie vuelve a «Iniciar servicio». | `watch.linea()`, `watch._agente()` (lee `agente.lock.json`, `agente.json` y `estado.json`), `watch.boton_servicio()` |
| V4 | W, L | «Cambiar…» en esa línea: pasar la unidad a «Nada», y luego a «Sincronizarlo en segundo plano». | La línea cambia al momento; en unos segundos el agente suelta la unidad (su `daemon.lock.json` desaparece) y la vuelve a tomar. `agente.json` lo escribe el agente (su hora de modificación es la del agente, no la de la ventana). | `ui/tk_watch.open_agente()`, `watch.pedir_modo()`, `PIDE_MODO` |
| V5 | W, L | Enchufar una unidad que no está en la lista, contestar «Ahora no», abrir su ventana desde la unidad y pulsar «Atender…» en la línea. | Entra en la lista con el modo elegido y el nombre de su flota. | `PIDE_MODO` de una unidad nueva |
| V6 | W, L | Raíz cifrada: «Ajustes» → «Configuración…» de su ventana, desmarcar «Pedir la contraseña al iniciar sesión» y «Guardar». Cerrar sesión y volver a entrar. | No pide la contraseña al entrar; la casilla de la bandeja sale desmarcada. Volver a marcarla la deja como estaba. En una unidad o una raíz sin cifrar la casilla no sale. | `ui/tk_configuracion.py`, `watch.pedir_al_iniciar()` / `pedir_ajuste()` |
| V7 | W, L | Volver a pasar el asistente «En este equipo» con el agente de la misma versión en marcha, añadiendo una raíz. | «Instalación» dice que no se reinstala; «Arranque» dice «Pedírselo al agente». El pid de `agente.lock.json` es el mismo antes y después, y la raíz se atiende sin reiniciar. | `install/agente.misma_version()` / `anadir()`, `ui/tk_equipo.py` |
| V8 | W | Con el `VERSION` rebajado (ver arriba): esperar el aviso y pulsar «Actualizar a la vX» en la bandeja. | Un aviso «Hay una versión nueva…» **una** vez. Tras pulsar, «Actualizando…» apagado; en menos de un minuto el icono se va y vuelve (el agente nuevo), `instalacion.json` apunta a `agente\<vX>`, la tarea programada también, la carpeta vieja ha desaparecido y el diario cuenta cada paso con «actualizar:». Otro aviso: «prdrive actualizado a la vX». | `Agente._mirar_version()` / `_actualizar()`, `agente.cmd_actualizar()`, `prdrive-install.py --update-agente`, `install/agente.actualizar()` |
| V9 | W | V8 con la raíz del equipo abierta y su ventana abierta; y otra vez con la raíz cifrada bloqueada. | Abierta: el código de su `.prdrive\` pasa a la vX sin tocar `sync_config.toml`, `state\` ni la clave. Bloqueada: el diario dice que su ventana lo ofrecerá, y al desbloquearla la ventana ofrece «Actualizar…». | `install/agente.actualizar_raices()`, `deploy.deploy_code()` |
| V10 | W | V8 con una versión que cambie el Python fijado (`pins.py`). | El runtime nuevo va a su carpeta al lado; el viejo, con el que corría «Actualizar», **no** se borra esa vez y se recoge en la siguiente instalación. El agente nuevo arranca con el nuevo. | `install/agente.podar()` (conserva el de `sys.executable`) |
| V11 | W | V8 sin red, y con un proxy que corte la descarga. | Aviso «no he podido actualizar»; el agente viejo sigue en marcha como estaba, y «Actualizar» se puede volver a pedir. | `update.download()`, `Agente._mirar_version()` |
| V12 | L | V8 en Linux: con bandeja (KDE), desde su menú; sin ella (GNOME sin AppIndicator), con `python agente.py actualizar`. | Con bandeja, como V8. Sin ella, el aviso dice «python agente.py actualizar», y ejecutarlo hace lo mismo (autostart y acceso del menú reescritos a la versión nueva). | `Agente.con_bandeja()`, `agente.cmd_actualizar()`, `install/agente.registrar()` en Linux |
| V13 | W, L | Unidad (FAT32 y exFAT) atendida por el agente en modo `daemon`: abrir su ventana, «Ajustes» → «Configuración…», poner otro intervalo y «Guardar»; cerrar la ventana. Otra vez sin agente, con «Iniciar servicio» después. | `state\ui_prefs.json` cambia solo en `interval_min` (las `pairs`, si las había, siguen; si no las había, no aparecen). Con el agente: al cerrar la ventana su `daemon.lock.json` lleva el intervalo nuevo (lo relee por la fecha del fichero, que en FAT32 va de 2 en 2 s). Sin él: el servicio que arranca lo dice («cada N min»). | `prefs.guardar_intervalo()`, `Agente._cargar_servicio()` |
| V14 | W, L | Pausar una unidad desde su ventana (V1) y una raíz del equipo desde la suya; cerrar sesión y volver a entrar; mirar el icono de la bandeja y su menú. Luego «Pausar» y «Reanudar» de la bandeja. | Tras volver a entrar, las dos siguen en pausa (`"pausada": true` en `agente.json`, escrito por el agente). La bandeja: icono de pausa y «… en pausa» al pasar el ratón; la otra unidad sigue sincronizándose. La pausa de la bandeja no quita la de la ventana, ni al revés. | `equipo.Unidad.pausada`, `Agente._sirve()`, `bandeja.estado()` |
| V15 | L · F22 · nube | Una unidad FAT32, otra exFAT y otra NTFS montadas en Linux y atendidas por el agente en modo `daemon`: en la ventana de cada una, «Pausar», «Reanudar» y «Sincronizar ahora» varias veces seguidas, mirando `agente.log`. La parte del sistema de ficheros se corre sola (`.github/workflows/maquina-real.yml`, fila F22: FAT32, exFAT y ext4 en discos virtuales; NTFS no). | Cada petición llega y el agente la atiende en unos segundos. En la nube: el cerrojo (`flock`) de la carpeta `state/` excluye al agente de quien pide, y con dos procesos pidiendo sin parar ninguna petición dada por dejada se pierde ni llega dos veces. Si en alguno `flock` no se deja, el buzón sigue funcionando sin turno, como antes de tenerlo: apuntarlo. | `equipo.turno()`, `equipo.pedir()`, `equipo.recoger()`, `tests/maquina/f22_buzon_turno_linux.py` |

## Fase 6 — Bandeja en Linux

Nada de esto ha hablado con un escritorio: `ui/bandeja_linux.py` y la mitad que
exporta de `common/dbus.py` solo han conversado con el bus de mentira de
`tests/_bus_falso.py`, que contesta lo que la especificación dice que contesta
un watcher. Lo que más puede fallar es lo que un anfitrión de verdad pregunta y
el falso no (una propiedad que falte, una firma que no acepte), y el orden de
arranque en el inicio de sesión. En cada prueba mirar `agente.log`, y con
`busctl --user tree` / `busctl --user introspect org.kde.StatusNotifierItem-<pid>-1
/StatusNotifierItem` lo que el agente exporta de verdad; `dbus-monitor --session`
enseña lo que el anfitrión le pide.

Equipos: **K** KDE Plasma (6, Wayland y X11); **U** Ubuntu con GNOME y su
extensión AppIndicator; **F** Fedora con GNOME, sin ella. Donde se pueda,
también un escritorio con waybar o XFCE (su bandeja es otra implementación del
anfitrión).

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| T1 | K, U | Iniciar sesión con el agente instalado. | El icono sale en la bandeja con la marca, nítido a escala 1 y 2 (se manda en 16, 22, 24, 32, 48 y 64 px), y al pasar el ratón «prdrive» y el estado. En `busctl --user list` está `org.kde.StatusNotifierItem-<pid>-1`. | `Bandeja.arrancar()` / `_registrar()`, `icons.pixmap_bandeja()` (ARGB32 en orden de red: si sale con los colores cambiados, el orden de los bytes está mal) |
| T2 | K | Reiniciar `plasmashell` con el agente en marcha (`systemctl --user restart plasma-plasmashell`); y un inicio de sesión donde el agente arranque antes que el panel. | El icono vuelve solo: `NameOwnerChanged` del watcher lo registra otra vez. En el diario no queda «no tiene bandeja» si el panel llegó después. | `Bandeja._senal()` con `NameOwnerChanged`, `REGLA_WATCHER` |
| T3 | K, U | Clic izquierdo y derecho en el icono; pinchar fuera; Esc. | El menú sale con los dos (`ItemIsMenu`); se cierra sin elegir nada. Las casillas marcadas donde toca, las entradas apagadas en gris, un desplegable por dispositivo, y un nombre con `_` sale tal cual (sin letra subrayada). No hay negrita en «Configurar» (dbusmenu no tiene entrada por defecto). | `Menu.disposicion()` / `propiedades()`, `etiqueta()` |
| T4 | K, U | Cada entrada, como B4: «Configurar», «Abrir en explorador», «Sincronizar ahora», «Pausar» / «Reanudar», «Cerrar el agente», y las de la raíz cifrada (B8). | Cada una hace lo suyo en uno o dos segundos. «Cerrar el agente» quita el icono. | `Event` / `EventGroup` → `Menu.pulsada()` → `Agente.pedir()` + `Vigia.despertar()` |
| T5 | K, U | Con el menú abierto, que cambie el estado (termina una pasada, se enchufa una unidad). | El menú se actualiza al volver a abrirlo (`LayoutUpdated`); pulsar una entrada del menú viejo hace lo que decía, no otra cosa. | `Menu.poner()` (ids nuevos en cada cambio, la numeración anterior guardada) |
| T6 | K, U | Los cinco estados de B5. | El icono cambia (`NewIcon`) y el texto al pasar el ratón también (`NewToolTip`); con avisos, Plasma lo marca como que pide atención (`NeedsAttention`) sin parpadear sin fin. | `_poner_pendiente()`, `Status` / `AttentionIconPixmap` |
| T7 | F | Instalar «solo agente» y con raíz en GNOME sin la extensión. | El diario dice «este escritorio no tiene bandeja»; «Verificación» del asistente tiene la fila «Bandeja» en rojo con el nombre de la extensión. En el menú de aplicaciones hay un «prdrive». | `poner_bandeja()`, `tk_equipo.escritorio()` / `SIN_BANDEJA`, `install/agente.quiere_menu()` |
| T8 | F | Desde ese «prdrive» del menú: con el agente parado (`agente.py parar`); en marcha sin raíz; en marcha con la raíz; con la raíz cifrada bloqueada. | Parado: lo arranca (y sin raíz lo dice con un aviso). Sin raíz: un aviso con el estado, lo mismo que diría el icono. Con raíz: su ventana. Bloqueada: VeraCrypt pide la contraseña y la ventana se abre al montarse. | `agente.cmd_abrir()` / `arrancar_agente()`, `bandeja.aviso_de_estado()` |
| T9 | F | Activar la extensión AppIndicator con el agente en marcha (sin cerrar sesión). | El icono aparece solo, sin reiniciar el agente. | `NameOwnerChanged`, `StatusNotifierHostRegistered` |
| T10 | K, U | Suspender y volver con un remoto sin conexión (B10). | Al volver, el diario muestra el sondeo enseguida (`PrepareForSleep(false)` de logind en el bus del sistema). | `REGLA_SUSPENDER`, `PIDE_DESPERTAR` |
| T11 | K, U | Enchufar y quitar una unidad con la bandeja puesta. | Igual de rápido que sin ella: en Linux los montajes siguen llegando por `mountinfo`, no por la bandeja. | `Vigia` |
| T12 | K | Cerrar sesión y volver a entrar; `agente.py parar`. | No queda un icono huérfano: al irse el agente, el watcher lo quita al perder su nombre el dueño. | `Bandeja.cerrar()` |

## Los avisos de que vuelve la red (#67)

Con un remoto «sin conexión», el agente ya no lo sondea cada 5 min: lo sondea
cuando el sistema dice que vuelve a haber red (`common/red.py`), una vez por
ráfaga de avisos, y si no, cada 30 min. Nada de esto ha visto una red de verdad
salvo una cosa: en Linux, con el núcleo de una máquina de pruebas, añadir una
dirección global avisa, quitarla no, y volver a añadirla avisa otra vez. Lo
demás (la llamada de Windows, NetworkManager de verdad, una VPN, un portal
cautivo, la suspensión) solo ha hablado con fuentes de mentira. En cada prueba
mirar `agente.log` (al arrancar dice qué oye) y `agente.py status` (la línea
«Cambios de red»).

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| N1 | W | Con un remoto «sin conexión» (cortar el Wi-Fi a mitad de una pasada), volver a conectar el Wi-Fi. | Al arrancar, «oigo los cambios de red (NotifyNetworkConnectivityHintChange)». Al volver la red, en unos segundos, UNA línea «la red ha cambiado: se prueban ya los remotos sin conexión», la sonda y «vuelve la conexión con …»; la pareja sigue sola. | `red.ApiWindows` (la estructura `NL_NETWORK_CONNECTIVITY_HINT` va por valor en la llamada de ctypes: si el nivel sale mal o el agente cae al cambiar la red, es eso), `pl.CambioDeRed` |
| N2 | W, L | Con el remoto sin conexión y SIN tocar la red, esperar 10 min mirando `agente.log` y los procesos. | Ninguna sonda (`rclone lsd`) entre medias: la siguiente, a los 30 min del último intento. | `pl.sondeo()`, `Politica.sondeo_de_respaldo` |
| N3 | W, L | Que la red caiga y vuelva varias veces seguidas: desactivar y activar el adaptador tres veces en 20 s, o reiniciar el router. | Una sonda por ráfaga, no una por aviso: la línea «la red ha cambiado…» una vez, unos 5 s después del último aviso (30 s como mucho desde el primero). | `ASENTAR_RED`, `TOPE_RAFAGA_RED`, `red_asentada()` |
| N4 | L | N1 en KDE y en GNOME con NetworkManager (`nmcli radio wifi off`, luego `on`); y en un equipo sin NetworkManager (systemd-networkd o iwd). | Con NetworkManager, «oigo los cambios de red (netlink y NetworkManager)»; sin él, «(netlink)», y la red que vuelve se oye igual (una dirección nueva). Un DHCP que solo renueva no lanza nada. | `red.Direcciones`, `abrir_netlink()`, `REGLA_NM_ESTADO` |
| N5 | W, L | Un remoto solo accesible por VPN (WireGuard u OpenVPN): con él sin conexión, levantar la VPN. | Linux: la dirección de la interfaz de la VPN avisa y la sonda va en segundos. Windows: depende de si la VPN cambia el nivel de conectividad; si no avisa, la sonda llega con el respaldo de 30 min o con «Probar ahora». Apuntar lo que pase. | `Direcciones`, `NIVELES_CON_RED` |
| N6 | W, L | Un portal cautivo (hotel, tren): conectarse, ver el remoto sin conexión, pasar el portal. | Linux con NetworkManager (y su comprobación de conectividad): de `CONNECTED_SITE` a `CONNECTED_GLOBAL` avisa y la sonda va. Windows: de `ConstrainedInternetAccess` a `InternetAccess` avisa. | `NM_CONECTADO`, `NIVELES_CON_RED` |
| N7 | W, L | Suspender con el remoto sin conexión y volver en otra red (con B10 / T10). | Al volver, `despertar` sondea enseguida (quizá sin red todavía, y falla) y, cuando la red llega, el aviso sondea otra vez: no se queda esperando 30 min. | `PIDE_DESPERTAR`, `PIDE_CAMBIO_DE_RED`, `red_asentada()` |
| N8 | W, L | `agente.py parar` y «Cerrar el agente» con el agente oyendo la red; y, si hay uno a mano, un Windows 10 anterior a la 2004. | Se va sin colgarse (`CancelMibChangeNotify2` desde el hilo del agente, nunca desde la llamada; en Linux el hilo «red» acaba). En el Windows viejo: «no oigo los cambios de red: … cada 5 min» y todo lo demás igual. | `AvisosDeRed.cerrar()`, `ApiWindows.cancelar()` |

## Tras la revisión del PR #54

Lo que se endureció después de la revisión cambia caminos que ya se vieron
funcionar en Windows (el lock del servicio, el diario de la raíz, el lock del
agente). Hay que volver a verlos: si la comprobación de enlaces se equivoca con
una letra de verdad, el agente dejaría de tomar la raíz sin decir nada.

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| E1 | W, L | Unidad en la lista enchufada; raíz del equipo sin cifrar; raíz cifrada en `P:\` (W) y montada en su carpeta (L). | El agente toma cada una como antes: su `daemon.lock.json` con `"agente": true` y líneas nuevas en `state\daemon.log`. | `agente.en_la_raiz()` (`os.path.realpath` de una letra de VeraCrypt y de una unidad USB) |
| E2 | W | Iniciar sesión (la tarea arranca el agente) y, a la vez, abrir «prdrive» del menú con el agente parado. | Un solo agente: un solo icono y un solo pid en `agente.lock.json`; el otro sale diciendo «Ya hay un agente en marcha». | `equipo.tomar_lock()`, `store.crear_exclusivo()` |
| E3 | W, L | Instalar desde el `.exe` / el asistente y con `--update-agente`. | `runsync.ico` en la carpeta del agente y en `.prdrive\` de la raíz, y los cinco `bandeja-*.ico`: los pinta el lanzador. | `install.pintar_iconos`, `prdrive-install._con_quien_pintar()` |
| E4 | W, L | Con el agente sirviendo una unidad en modo `sync`, abrir su ventana y «Iniciar servicio»; cerrarla. Otra vez con el agente a mitad de una pareja larga. | Un solo servicio: `daemon.lock.json` pasa del agente al de runsync y el agente dice «la atiende otro servicio». A mitad de pareja, el servicio de runsync espera a que el agente la acabe (`daemon.log`: ninguna pasada solapada) y el lanzador dice «a mitad de una pareja». | `runsync.tomar_lock()`, `Agente._tomar()`, `store.tomar_registro()` |
| E5 | W, L | Con una pasada larga en marcha, «Actualizar» desde la bandeja; otra vez desinstalando (`--desinstalar-agente`). Y una tercera con `ESPERA_PASADA` corta (a mano) para ver el corte. | Espera a que acabe la pasada, diciéndolo («Esperando a que acabe la pasada de «…»»), y solo entonces sigue. Con el plazo corto: se cortan `sync.py` Y su `rclone` (ninguno en el Administrador de tareas / `ps`), y el mensaje nombra la pareja. Tras el corte, el agente nuevo sigue con las demás parejas y deja la cortada unos 2 min y medio (diario: «espera a que caduque su bloqueo», luego «vuelve a su turno»); esa pasada sale bien, sin «prior lock file found» ni aviso de fallo (H-15). Cerrar sesión con una pasada en marcha y volver: el agente nuevo no lanza nada hasta que acabe. | `parar_agente()`, `matar_arbol()` (`taskkill /T`, `killpg`), `equipo.pasada_viva()`, `store.arranque_del_sistema()` (`GetTickCount64`) |
| E6 | W, L | Una unidad en la lista: enchufarla (sigue igual), actualizarla con `--update` y volver a enchufarla; copiar su `.prdrive\` a otra memoria y cambiar su `sync.py`. | Sin cambios, ni pregunta ni espera apreciable. Actualizada: «su código ha cambiado» una vez; con «Atender» sigue en su modo. La copia modificada: la pregunta, y nada suyo corre (ni lock ni ventana) hasta contestar. | `agente.huella()`, `Conexion.cambiada`, `tk_agente --cambiada`, `PYTHONPYCACHEPREFIX` |
| E7 | W (x64 y ARM64), L | Instalar el agente y mirar `rclone\<versión>\` en su carpeta; una pasada y la ventana de una unidad abierta desde la bandeja; en el Administrador de tareas / `ps`, qué `rclone` corre. Luego enchufar una unidad con la 0.4.x. | El rclone que corre es el de la carpeta del agente, nunca el de `.prdrive\bin\` (también el de la ventana abierta por el agente, y en ARM64 el arm64). La 0.4.x: un aviso con su versión, nada suyo corre, y en la bandeja «…: actualízala para que la atienda» en gris. | `install/agente.poner_rclone()`, `model.RCLONE_DEL_AGENTE`, `agente.version_vieja()` |
| E8 | W, L | Abrir el menú de la bandeja con todo bien, con una pareja que falla, con un remoto sin conexión y con la raíz cifrada; pasar el ratón por el icono tras una pasada, y un par de minutos después. Windows con el tema claro, el oscuro y alto contraste; Linux en KDE y en GNOME con AppIndicator, en claro y en oscuro. | Sin línea gris de estado arriba. Con avisos, arriba y clicables: «…: falla X · Abrir…» abre la ventana de la unidad, «Sin conexión: … · Probar ahora» lanza la sonda (diario: «se prueban ya los remotos sin conexión»). Iconos en «Abrir», «Sincronizar ahora», «Pausar»/«Reanudar», «Bloquear»/«Desbloquear…», «Actualizar…», «Cerrar el agente» y los avisos: nítidos a 100/150/200 %, del color del texto del menú en Windows (legibles en alto contraste) y del tema en Linux. El texto del ratón: «prdrive · sincronizado hace un momento», luego «hace N min». | `icons.pixeles_menu()`, `Api.menu()` (`MIIM_BITMAP`, `CreateDIBSection`), `bandeja_linux.ICONOS_DEL_TEMA`, `bandeja.hace()` |

Vistas en Windows x64 el 30/09 (resultados, §10):
- E2, E3, E4 y E6, enteras;
- E1, salvo la raíz cifrada en `P:\`;
- E5, con H-13 arreglado después;
- E7, salvo la ventana abierta por el agente, la entrada gris de la bandeja y ARM64.

Quedan esas partes, y todas las E en Linux.

## Tras el #68 — Un desplegable por dispositivo

El menú de la bandeja agrupa lo de cada dispositivo en su desplegable, con el
icono de su `autorun.inf`. La parte que decide (`bandeja.vista()`) y la que
lee el icono (`volumen.emblema()`, `icons.png_de_ico()`) están probadas; lo que
pinta y lo que abre, no: `Api.menu()` contra user32/gdi32 solo ha hablado con
bibliotecas de mentira, y `icon-data` con el bus de mentira. Hacen falta dos o
tres unidades: una con un color de la marca puesto en «Nombre e icono…», otra
con un `.ico` propio (uno de 32 bits con alfa y otro de 24 bits, sin él) y otra
sin `autorun.inf`; y la raíz cifrada del equipo.

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| D1 | W, L (K y U) | Abrir el menú con las tres unidades y la raíz cifrada abierta; Windows al 100, 150 y 200 %, claro y oscuro. | Un desplegable por dispositivo (primero la raíz), cada uno con SU icono a color: la marca en su color, el `.ico` propio, la marca de prdrive sin `autorun.inf`. Nítidos y del tamaño de los glifos de al lado; con alfa, sin cuadro alrededor. Dentro, sin repetir el nombre: «Configurar» (en negrita en Windows), «Abrir en explorador», «Sincronizar ahora». | `bandeja._raices_del_equipo()` / `_unidades()`, `Api._bitmap_emblema()`, `bandeja_linux.png_emblema()` (`icon-data`) |
| D2 | W | El `.ico` propio de 24 bits, sin alfa. | Transparente donde lo dice su máscara, sin fondo negro. Si sale un cuadro negro o nada, `DrawIconEx` con `DI_MASK` no pinta la máscara como se espera (`alfa_desde_mascara()`). | `Api._pixeles_ico()`, `_dibujar_icono()` |
| D3 | W | Doble clic sobre el nombre de un dispositivo en el menú (no en «Configurar»); y un clic simple. | El doble clic cierra el menú y abre su ventana de runsync («Default Menu Items»: la entrada por defecto del submenú). El clic simple solo abre el submenú. Si el doble clic no hace nada, apuntarlo: «Configurar» sigue siendo el camino. | `SetMenuDefaultItem` en el submenú, `TrackPopupMenu(TPM_RETURNCMD)` |
| D4 | K, U, y waybar o XFCE si se puede | Pinchar en el nombre de un dispositivo. | Se abre el submenú y no pasa nada más (en `dbus-monitor` no llega `Event … "clicked"` para ese id, o si llega, el agente no hace nada). | `Menu.pulsada()` con `children-display = submenu` |
| D5 | W, L | «Abrir en explorador» de una unidad, de la raíz sin cifrar y de la raíz cifrada bloqueada. | El Explorador / el gestor de archivos se abre en la raíz de la unidad o en la carpeta de la raíz, sin ventana de runsync. Con la raíz bloqueada: VeraCrypt pide la contraseña y, al montarse, se abre su carpeta (no su ventana). En una unidad con `autorun.inf`, el Explorador no ejecuta nada suyo (solo la enseña). | `agente.explorar()` / `orden_explorar()` (`explorer.exe`, `xdg-open`), `Agente._abrir(explorador=True)`, `Desbloqueo.explorar` |
| D6 | W, L | Cambiar el icono de una unidad atendida desde su ventana («Nombre e icono…») sin desenchufarla. | Antes de un minuto el desplegable lleva el icono nuevo (`MIRAR_EMBLEMA`), aunque el Explorador siga con el viejo hasta volver a enchufarla. | `Agente._emblema()`, `volumen.emblema()` |
| D7 | W, L | Una unidad que no está en la lista, una con el código cambiado y una 0.4.x, las tres con icono propio; y la raíz cifrada bloqueada. | Las tres con la marca de prdrive, no con el suyo, y el rótulo «(sin atender)», «(código cambiado)», «(por actualizar)»; la raíz, «(bloqueada)» y la marca. En el diario del agente no hay lectura de nada suyo. | `bandeja._emblema()` (`en_lista`), `Agente._emblema()` |
| D8 | W, L | Con dos unidades atendidas y luego con una sola. | Con dos, «Sincronizar todo ahora» fuera de los desplegables pide las dos; con una, no sale (su «Sincronizar ahora» basta). | `bandeja._del_agente()` |

## Los cambios locales de una pareja (#61)

Una pareja con `watch = true` se sincroniza poco después de que cambien sus
ficheros locales (`common/huella.py`, `Agente._vigilar()`; en Linux, con los avisos
del sistema, `common/avisos_carpeta.py`). Las reglas (la
calma, la separación, el tope) y el cableado (el hilo, las pausas, la foto de
después de cada pasada) están probados con un reloj y una foto de mentira; lo
único de verdad que ha recorrido el disco son las carpetas de un temporal. Lo
que no se sabe es **cuánto cuesta mirar una carpeta grande en un medio lento**,
qué dice cada sistema de ficheros de los mtime, y si un recorrido a medias
estorba una expulsión. En cada prueba mirar `agente.log` (las líneas «han
cambiado sus ficheros» y «deja de vigilarse»), el `state/daemon.log` de la raíz y
`agente.py status` (la línea «Sincroniza al cambiar sus ficheros»).

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| F1 | W, L | Una pareja bisync con `watch = true` en una unidad y en la raíz del equipo, en modo `daemon`. Cambiar un fichero de su carpeta; luego copiar 200 de golpe; luego guardar un fichero cada 30 s durante 5 min. | Una pasada a los 20-35 s del cambio, con «(han cambiado sus ficheros)» en el diario. Los 200 ficheros son UNA pasada. Con el guardado cada 30 s, una pasada cada 2 min como mucho. `status` dice «Sincroniza al cambiar sus ficheros: …». | `Agente._vigilar()`, `pl.a_recorrer()`, `pl.toca_por_cambios()` |
| F2 | W, L | Una carpeta con unas 20 000 entradas en un pendrive USB 2.0 y en un disco USB: cronometrar a mano `huella.de_carpeta()` con la caché fría (recién enchufado) y con la caliente; mirar la luz del pendrive, la CPU y que la bandeja y la ventana respondan mientras se recorre. Luego pasar de 20 000. | Unos segundos en frío y menos en caliente; la bandeja, los buzones y las pasadas de otras parejas no se enteran (el recorrido va en un hilo). Con una entrada de más: UNA línea «deja de vigilarse y sigue por su intervalo» en el diario y en el de la raíz, y la luz del pendrive se calla. Apuntar los tiempos: si en frío pasa de 10 s hay que bajar el tope o subir el sondeo. | `Muestreo`, `hilo()`, `huella.de_carpeta()` (`os.scandir`), `PoliticaCambios.tope_entradas` / `.sondeo` |
| F3 | W, L | En exFAT, FAT32, NTFS y ext4: cambiar un fichero SIN cambiar su tamaño (un carácter por otro), dos veces en menos de 2 s; reemplazar un fichero por otro del mismo tamaño y con el mismo mtime (`cp -p`, `robocopy /COPY:T`). | FAT guarda el mtime con 2 s de resolución y exFAT con un campo de 2 s más un incremento de 10 ms: mirar qué dice `st_mtime_ns` en cada sistema y si el segundo cambio, con el primero ya visto, se pierde o tarda en notarse. El reemplazo con mtime y tamaño idénticos es invisible a este método (apuntarlo: esa pasada espera al intervalo). | `huella._hash()` (ruta, tamaño, `st_mtime_ns`) |
| F4 | W, L | En la raíz del equipo cifrada con VeraCrypt (`P:\` / su carpeta): F1 y F2. Y «Bloquear» (la bandeja, o `agente.py bloquear`) mientras corre un recorrido de una carpeta de 20 000 entradas. | Mismo comportamiento que fuera del contenedor, con el coste del cifrado: apuntar cuánto tarda. «Bloquear» espera a que acabe el recorrido y VeraCrypt no pregunta si forzar. | `Agente._mirando()` en `_bloqueos()`, `agente.orden_bloquear()` |
| F5 | W, L | En una unidad sin cifrar, con un recorrido largo en marcha (F2), «Expulsar» del Explorador / `eject` y, en una VeraCrypt, «Expulsar» de su ventana. | La ventana de runsync para el servicio, pero no un recorrido que ya corra: apuntar si el sistema dice «en uso» durante esos segundos y, si lo dice, que se pasa al reintentar. Nada queda abierto después. | `Muestreo.correr()`, `cifrado.lanzar_expulsion()` |
| F6 | W, L | Una pareja cuya carpeta es un recurso de red montado (SMB, NFS, una unidad de rclone): F1 y F2; y cortar la red a mitad de un recorrido. | Un recorrido que se cuelga deja su hilo esperando (`scandir` sobre una carpeta de red caída puede tardar minutos) y, mientras, no se pide otro para ninguna pareja, pero la vuelta, las pasadas y la bandeja siguen y el intervalo manda. Apuntar cuánto tarda en volver y si luego retoma solo. | `Agente.muestreo` (uno a la vez), `huella.de_carpeta()` (un `OSError` es «no sé», no un cambio) |
| F7 | W, L | Una pareja bisync con `watch = true` y `versions = true`, y otra con `local = "."`: cambiar algo en el remoto para que la pasada BAJE ficheros; borrar un fichero local para que la pasada guarde una versión. | Tras cada pasada, ninguna pasada más: ni lo que bajó, ni lo que cayó en `.prversions/`, ni lo que la pasada escribió en `.prdrive\state\` de la `local = "."`, la dispara. Un cambio hecho a mano MIENTRAS corría la pasada espera al intervalo (es el precio apuntado). | `Agente._rehacer_foto()`, `pl.tras_pasada()`, `huella.IGNORAR`, `agente.IGNORAR_CAMBIOS` |
| F8 | W, L | Un cambio con el equipo en pausa (bandeja), con batería por debajo del 20 %, en una red de uso medido, con la raíz pausada desde su ventana y con su ventana abierta; luego volver a lo normal. | Sin pasada y sin recorrer la carpeta mientras dura (el estado dice por qué retiene). Al volver, el primer recorrido ve el cambio y la pasada sale a los 20-35 s; si el cambio se hizo desde la ventana, no sale ninguna de más. | `pl.a_recorrer(retenido=)`, `Conexion.motivo`, `Agente._vigilar()` (`vigiladas` se olvida al dejar de servirse) |
| F9 · nube: ok | L | Con los avisos del sistema (#61, fase 1 de `2026-10-06-watch-con-avisos`): una pareja bisync con `watch = true` en un pendrive exFAT, en uno FAT32 y en la raíz del equipo (ext4). Guardar un fichero; renombrar una carpeta y guardar dentro; copiar 5 000 ficheros de golpe. | `agente.log` dice «oigo los cambios de las carpetas… (inotify)» y `status` NO dice «Recorre su carpeta». Cada cosa, una pasada a los 20-25 s; la copia, UNA. En `top`, el agente quieto en reposo y sin picos durante la copia. | `avisos_carpeta.Inotify`, `Vigia.oir()`, `Agente._recoger_avisos()` |
| F10 · nube: ok | L | Con la vigilancia puesta: «Expulsar» de la bandeja, desmontar desde el gestor de archivos (`udisksctl unmount`) y «Bloquear» una raíz VeraCrypt. | Nadie dice «en uso» por el agente; al volver a enchufar o desbloquear, se vigila otra vez (sin «Recorre su carpeta» en `status`). | `Agente._soltar_avisos()`, `IN_UNMOUNT` |
| F11 · nube: ok | L | Una pareja cuya carpeta es un recurso de red (SMB, NFS, una unidad de rclone o sshfs). | Una vez en el diario y en `daemon.log`: «sin avisos del sistema, se recorre su carpeta: es una carpeta de red o compartida (…)»; `status` lo cuenta; quieta, se recorre cada 2 min. | `avisos_carpeta.DE_RED`, `sistema_de()` |
| F12 · nube: ok | L | `sudo sysctl fs.inotify.max_user_watches=2000` y una pareja con más de 1 000 carpetas; abrir VS Code sobre otra carpeta grande. Volver a poner el valor de antes al acabar. | La pareja se recorre y se dice por qué («más carpetas de las que caben en los avisos del sistema…»); VS Code no protesta por falta de vigilancias. | `avisos_carpeta.PRESUPUESTO` |
| F13 · nube: ok | W | Una pareja vigilada en una carpeta de red (`\\nas\docs`) o en un volumen de VeraCrypt (la raíz del equipo en `P:\`, o un pendrive abierto con «Abrir PRDRIVE»): quieta 5 min, un cambio; enseguida otro; luego lo mismo a batería. | `status` dice «Recorre su carpeta (sin avisos del sistema): … (es una carpeta de red…/es un volumen de VeraCrypt…)». El primer cambio sale como mucho a los 2 min 20 s; el segundo, a los 20-35 s; a batería, recorridos cada minuto como poco. El llavero sigue saliendo a los 20-35 s de guardar. | `pl.cada_cuanto()`, `avisos_carpeta.MOTIVO_RED_WINDOWS`/`MOTIVO_VERACRYPT` |
| F14 · nube: ok | W | Con los avisos de Windows (fase 2): una pareja bisync con `watch = true` en un pendrive NTFS, uno exFAT y uno FAT32, y en la raíz del equipo sin cifrar. Guardar un fichero; renombrar una carpeta y guardar dentro; copiar 5 000 ficheros de golpe. | `agente.log` dice «oigo los cambios… (ReadDirectoryChangesW)» y `status` NO dice «Recorre su carpeta». Cada cosa, una pasada a los 20-25 s; la copia, UNA. En el Administrador de tareas, el agente quieto en reposo. | `avisos_carpeta.ReadDirectoryChanges`, `Win32` |
| F15 | W | Con la vigilancia puesta, «Quitar hardware de forma segura» (o «Expulsar» del Explorador) del pendrive. Luego, con un fichero suyo abierto en un editor, otra vez; cerrar el editor, cambiar un fichero y esperar. | La primera, sin «el dispositivo está en uso»: el agente cerró su handle a tiempo. La segunda la impide el editor (es lo suyo, no el agente) y, al no extraerse, la vigilancia vuelve sola: el cambio de después lanza su pasada a los 20-35 s, sin «Recorre su carpeta». | `Bandeja._mensaje()` (`DBT_DEVICEQUERYREMOVE`), `ReadDirectoryChanges.dispositivo()`, `Api.handle_de()`, `Win32.registrar()` |
| F16 · nube: ok | W | Con la vigilancia puesta: «Expulsar» y, en la raíz cifrada, «Bloquear» desde la bandeja; y arrancar el pendrive sin expulsarlo. | Las dos acaban sin «en uso» ni «¿forzar?»; al volver a enchufar o desbloquear, se vigila otra vez. El pendrive arrancado deja en el diario la desconexión de siempre, sin errores del motor. | `Agente._soltar_avisos()`, `DBT_DEVICEREMOVECOMPLETE` |
| F17 | W | El agente sin bandeja (Explorador caído al iniciar sesión, o la bandeja que no arranca). | `agente.log`: «sin bandeja no se dejan carpetas abiertas en las unidades…»; todas las parejas vigiladas se recorren (F13) y nada impide expulsar. | `agente.poner_avisos_carpeta()` |
| F18 · nube: ok | W | La pregunta 2 de la especificación: ¿manda VeraCrypt `DBT_DEVICEQUERYREMOVE` a un handle abierto dentro de su volumen antes de desmontarlo (desde su ventana, su desmontaje automático y `Expulsar PRDRIVE.bat`)? Hace falta una prueba aparte (un programa que abra una carpeta de `P:\`, registre el aviso y apunte lo que llega). | Si llega antes de que VeraCrypt pida forzar, los volúmenes de VeraCrypt pueden vigilarse con avisos: quitar `MOTIVO_VERACRYPT` y su comprobación. Si no llega, se quedan recorriéndose. | `avisos_carpeta.DISPOSITIVOS_VERACRYPT` |
| F19 · nube: ok | W | Las comprobaciones de Windows de verdad de `tests/test_avisos_carpeta.py` (en la CI de Windows de un PR, o `python tests/test_avisos_carpeta.py` en W). | Pasan: un cambio avisa, `.prversions` no, el búfer pequeño es «desbordado», tras `dejar()` la carpeta se borra. | `Win32` (las firmas de ctypes, `OVERLAPPED`, `DEV_BROADCAST_HANDLE`) |

## Poner al día una raíz con la versión del agente

Una raíz de la lista con un programa anterior al del agente lleva «Actualizar a
la vX» en su desplegable (`Agente._actualizable()`), y un aviso lo dice una vez
por versión suya. Lo pide `PIDE_ACTUALIZAR_UNIDAD`; un hijo suelto (`agente.py
actualizar-raiz`) baja el tag DEL AGENTE y ejecuta su `prdrive-install.py
--update` sobre la raíz. Está probado con procesos y descargas de mentira; lo
que falta es el instalador de verdad sobre un pendrive de verdad. Hace falta un
agente de una release publicada y unidades con una versión anterior (una
0.5.x y una 0.4.x de la lista; y una de otra versión que NO esté en la lista).

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| A1 | W, L | Enchufar la 0.5.x de la lista. | Un aviso «… tiene la 0.5.x» una vez (ni al volver a enchufarla mientras viva el agente). En su desplegable, «Actualizar a la vX» encima de «Versión 0.5.x»; la que no está en la lista no lo lleva. | `Agente._avisar_actualizable()`, `bandeja._poner_al_dia()` |
| A2 | W, L | «Actualizar a la vX» con una pasada larga suya en marcha. | «Actualizando a la vX…» apagado y Configurar/Abrir/Sincronizar apagados; no empieza hasta que acaba la pasada (`daemon.lock.json` desaparece y entonces el diario dice «actualizándola»). Al acabar: «… actualizada a la vX», el desplegable dice «Versión vX», **no** pregunta por su código y vuelve a sincronizar. `agente.json` lleva su huella nueva; `sync_config.toml`, `state\`, `keys\`, `bin\` y `runtime\` no se han tocado. | `_actualizaciones()`, `_fin_de_actualizacion()`, `cmd_actualizar_raiz()`, `--update` |
| A3 | W, L | Con su ventana abierta, «Actualizar a la vX» desde la bandeja. | Un aviso «tiene su ventana abierta» y nada más; cerrada la ventana, pedirlo otra vez funciona. | `Agente._con_ventana()` |
| A4 | W, L | La 0.4.x de la lista. | El aviso de que no se atiende dice cómo ponerla al día (desde su desplegable, o `agente.py actualizar <id>` sin bandeja). Tras «Actualizar», se atiende sin preguntar. | `_conectar()`, `version_vieja()` |
| A5 | W, L | Sin red; y desenchufando la unidad a mitad. | Sin red: «no he podido actualizarla» y se sigue sincronizando como estaba. Desenchufada a mitad: al volver a enchufarla, si su código llegó a cambiar pregunta «su código ha cambiado», y si no, sigue como estaba; nunca sincroniza con un código a medias sin preguntar. | `SIN_TOCAR`, `Conexion.a_medias`, `huella()` |
| A6 | W | Una unidad en un contenedor VeraCrypt de la lista, abierta. | Igual que A2, en la letra del volumen abierto; el vestíbulo (`VeraCrypt\`, `Abrir PRDRIVE.bat`) no se toca. | `--update` sobre `con.raiz` |

## El llavero (fase 3 de su especificación)

El agente atiende el llavero de una raíz: lo trae cada 5 min con KeePassXC
abierto, lo abre desde la bandeja, avisa de un conflicto, limpia las claves del
navegador de una unidad quitada sin expulsar y cierra el llavero antes de
bloquear una raíz cifrada; en Linux (fase 2), además, cierra el KeePassXC de
una unidad que se va y quita sus manifiestos del navegador. Las pruebas son
R17–R23 y, para Linux, R24–R31 de
`docs/superpowers/specs/2026-10-04-llavero-keepassxc-design.md` (§15), con las
del resto del llavero: no se repiten aquí.

### KeePassXC fuera de la huella, comprobado contra su SHA-256 (#117)

`keepassxc/` ya no entra en la huella del agente; antes de lanzar o registrar
un ejecutable de la unidad se compara con `pins.KEEPASSXC_EJECUTABLES`. Los
tests lo sujetan con ficheros de mentira; lo que solo prueba un equipo real:

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| KP1 | W | Un pendrive de verdad con el llavero ya activo y la unidad atendida: abrir «Abrir llavero», mover la ventana de KeePassXC, cambiar un ajuste, expulsar y volver a enchufarla, también en otro equipo con otra letra. | Ninguna pregunta «su código ha cambiado». La huella (`agente.huella()`, a mano) tarda milisegundos, no los 8–9 s de antes. | `agente.HUELLA_SIN_CARPETAS` |
| KP2 | W | Con el KeePassXC 2.7.12 que deja el instalador (sin tocar nada a mano), exFAT y NTFS: «Abrir llavero», «Combinar» una copia de conflicto y la sonda del fichero llave (llavero sin contraseña). | Se abre y combina sin avisar de que no es el oficial: las sumas de la tabla son las de los ficheros que el instalador deja en la unidad. | `keepassxc.comprobar()` |
| KP3 | W | Cambiar un byte de `keepassxc-proxy.exe` y, aparte, de `KeePassXC.exe`, con el sello intacto; «Abrir llavero». Luego, sin borrar nada, mirar la ventana y pulsar «Actualizar…». | No se abre, no se escribe ni la configuración ni ninguna clave del registro, y el aviso manda a «Actualizar…» (no a borrar ninguna carpeta). Tras el aviso, la ventana ofrece «Actualizar…» («lleva 2.7.12 (con ficheros que no cuadran)»); al pulsarlo se repone el paquete, se apaga el aviso (`state/keepassxc-no-oficial.json` sin el apunte) y se abre. | `NoOficial`, `SALIDA_ACTUALIZAR`, `keepassxc_bin.al_dia()` |
| KP4 | L | KP2 en Linux x64 con el AppImage. Después, con lo extraído en `~/.cache/prdrive/keepassxc/`, cambiar el AppImage de la unidad; y lo mismo con esa caché borrada. | Con la caché al día se abre igual; sin ella no se extrae nada y el aviso lo dice. | `keepassxc.preparar_appimage()` |

### «Abrir llavero» desde la bandeja con las pasadas retenidas

Con la pausa de la bandeja, la batería o el ahorro de energía, «Abrir llavero»
encola una pasada urgente del llavero (`Agente._traer_al_abrir()`) y KeePassXC
se abre a la vez. Los tests lo sujetan con el agente de mentira; lo que solo
prueba un KeePassXC de verdad es qué ve quien desbloquea antes de que acabe:

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| KR1 | W, L | Dos equipos con la misma unidad (o dos unidades con el mismo llavero). En el B, añadir una entrada y esperar a su pasada. En el A, con la unidad atendida, «Pausar» en la bandeja y «Abrir llavero»; desbloquear sin prisa. Repetir desbloqueando lo antes posible, y otra vez editando algo antes de que acabe la pasada. Después, guardar un cambio en el A, cerrar KeePassXC y «Reanudar». | El diario del agente dice «se trae lo último de su llavero aunque no se sincroniza (en pausa)» y la base desbloqueada tiene la entrada del B. Desbloqueada antes de que acabe la pasada: apuntar qué hace KeePassXC al cambiar el fichero (recargarlo solo, o preguntar si combinar con lo editado). El cambio del A no sube hasta «Reanudar». | `Agente._traer_al_abrir()`, `pl.retiene_al_llavero()` |

## El modo de ahorro de energía

El agente no lanza pasadas ni recorre carpetas vigiladas mientras el sistema
está en modo de ahorro de energía (`Politica.pausar_ahorro_energia`). Se lee
con la batería cada minuto (`moderacion.energia()`); los tests ponen un
power-profiles-daemon de mentira y los campos de `SYSTEM_POWER_STATUS` a mano.

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| E1 | W (portátil y sobremesa) | Encender el ahorro de batería / «Ahorro de energía» (Windows 11 24H2) desde la configuración rápida, enchufado y a batería, con una unidad de la lista. | En menos de un minuto la bandeja dice «esperando: modo de ahorro de energía» y no sale ninguna pasada; «Sincronizar ahora» sí la lanza. Al apagarlo, vuelve. Apuntar si el ahorro de energía de un sobremesa (sin batería) pone `SystemStatusFlag` a 1. | `moderacion.energia_de_windows()` |
| E2 | L (GNOME y KDE) | Elegir el perfil «Ahorro de energía» en el menú del sistema; luego `powerprofilesctl set balanced`. Repetir en una distro con `tuned-ppd` (Fedora 41+). | Lo mismo que E1. Apuntar la versión de power-profiles-daemon y por qué nombre contesta. | `moderacion._ahorro_linux()` |

## Expulsar una unidad desde la bandeja

El desplegable de una unidad extraíble de la lista lleva «Expulsar»
(`PIDE_EXPULSAR`, `agente.py expulsar ID`). Lo que decide quién lo lleva y cómo
se suelta está en `common/expulsar.py` y probado con un sysfs, una tabla de
montajes, un `udisksctl` y unos `DeviceIoControl` de mentira. Falta el sistema
de verdad: en Windows, el bloqueo, el desmontaje y la expulsión del volumen
(`FSCTL_LOCK_VOLUME`, `FSCTL_DISMOUNT_VOLUME`, `IOCTL_STORAGE_EJECT_MEDIA`) y la
lectura del bus (`IOCTL_STORAGE_QUERY_PROPERTY`), que no se han ejecutado nunca.
Visto en un Windows 11 el 12/10/2026 (0.7.4, con el agente; issue #128): con solo
`IOCTL_STORAGE_EJECT_MEDIA` el medio sale pero el dispositivo y su letra siguen en el
Explorador hasta quitar el pendrive. Por eso `_expulsar_windows()` retira ahora el
dispositivo (`CM_Request_Device_EjectW`, X7–X10); lo que ejecuta de verdad la nube
(la cadena de dispositivos y los prototipos de `cfgmgr32` sobre un disco virtual) es la
fila F29 de `tests/maquina/`, y un pendrive solo lo prueba una persona.

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| X1 | W, L | Un pendrive USB de la lista (que Windows presente como extraíble, y otro que se presente como fijo), una tarjeta SD, un disco USB externo y un disco interno con prdrive de la lista. | Solo el pendrive, la tarjeta y el disco USB llevan «Expulsar» en su desplegable; el interno y la unidad del sistema, no. Mirar qué bus y qué `RemovableMedia` da cada uno (`expulsar._bus_windows()`) y si los pendrives «fijos» salen. | `expulsar.compatible()`, `bandeja._expulsar()` |
| X2 · visto 12/10: el IOCTL deja el dispositivo y su letra (#128, X7) | W, L | «Expulsar» con la unidad quieta. | «Expulsando…» apagado unos segundos, un aviso «… ya puedes quitarla», la unidad desaparece del Explorador / del gestor de archivos y del menú, y se puede tirar del cable sin que el sistema proteste. En Linux, el disco se apaga (la luz). En Windows, apuntar si basta el `IOCTL_STORAGE_EJECT_MEDIA` o el pendrive sigue «apareciendo» hasta quitarlo. | `Agente._expulsiones()`, `expulsar._expulsar_windows()` / `_expulsar_linux()` |
| X3 | W, L | «Expulsar» con una pasada larga en marcha; y con una carpeta abierta en el Explorador / un fichero abierto en un programa. | Con la pasada, espera a que acabe y no lanza otra. Con algo abierto, NO la fuerza: un aviso «no la expulso» con el motivo, y la unidad sigue sincronizándose. En Windows, apuntar si el Explorador con la carpeta abierta basta para que `FSCTL_LOCK_VOLUME` falle, y si los cuatro intentos son suficientes para lo que suelta solo (antivirus, indexador). | `expulsar.INTENTOS_BLOQUEO`, `_motivo_linux()` |
| X4 | W, L | «Expulsar» con la ventana de esa unidad abierta. | No expulsa; a los 60 s dice que su ventana sigue abierta. Cerrada la ventana, pedirlo otra vez funciona. | `Agente._expulsiones()` |
| X5 | W, L | Una unidad en un contenedor VeraCrypt de la lista. | No lleva «Expulsar» (su volumen es virtual): se cierra con «Expulsar PRDRIVE». | `expulsar.compatible()` (`/dev/mapper`, bus no extraíble) |
| X6 | W | Con el agente en una cuenta sin administrador, «Expulsar» un pendrive. | Va igual: abrir el volumen para bloquearlo no pide elevar para un dispositivo extraíble. Si pide, apuntarlo: `_abrir_volumen()` devuelve `None` y el aviso dice «no deja abrir la unidad». | `expulsar._abrir_volumen()` |
| X7 | W | #128: un pendrive USB de verdad de la lista, con la unidad quieta: «Expulsar» de la bandeja. Mirar el Explorador, «Quitar hardware de forma segura» y `agente.log`; después quitarlo y volver a enchufarlo. | La letra desaparece del Explorador y de «Este equipo» (no queda vacía), el dispositivo sale de «Quitar hardware de forma segura» y el aviso dice «ya puedes quitarla»; al volver a enchufarlo llega como siempre (letra, bandeja, la pasada). Apuntar cuánto tarda desde el clic y qué cadena de dispositivos leyó `expulsar._cadena_windows()` y cuál retiró. | `expulsar._expulsar_windows()`, `_cadena_windows()`, `_retirar_dispositivo()` |
| X8 | W | #128: el mismo pendrive con dos particiones (dos letras), la otra con una carpeta abierta en un programa; «Expulsar» de la primera. Y con el indexador o un servicio teniendo algo abierto. | No se fuerza: el aviso dice «Windows no deja quitar la unidad X: …» con la causa que dé Windows (programa, servicio o dispositivo; `PNP_VETOS`). Apuntar qué `PNP_VETO_TYPE` y qué nombre da cada caso, y si el volumen queda desmontado tras el veto (se vuelve a montar al tocarlo). Al cerrar lo que la usa y repetir, sale. | `expulsar._texto_veto()`, `PNP_VETOS` |
| X9 | W | #128: una tarjeta SD en un lector (el del portátil y uno USB) y un disco USB externo con prdrive de la lista; «Expulsar». | Igual que X7. Apuntar la cadena de dispositivos de cada uno y cuál se retira (¿el lector entero, con sus otras ranuras?). Un disco USB externo que no declare extraíble el medio debe retirarse igual, por su bus. | `expulsar._elegir_nodo()`, `_dispositivo_a_retirar()` |
| X10 | W | #128, punto 3: con una tarjeta en un lector que deja su letra puesta, sacar y volver a meter la tarjeta (o `IOCTL_STORAGE_LOAD_MEDIA` tras expulsar el medio) con el agente mirando; y tras X7 comprobar que en un pendrive ya no queda un medio que «volver a cargar». | En un pendrive no se da (el dispositivo se fue). Con la letra puesta: llega un `WM_DEVICECHANGE` (apuntar su `wParam` y los `dbcv_flags`, `DBTF_MEDIA`) y el agente la ve a los pocos segundos, o no llega y la ve el recorrido de respaldo (120 s). Si no llega, es lo que decide si hace falta algo más. | `bandeja_windows._mensaje()`, `RECORRIDO_RESPALDO` |
| X11 | W | #128, punto 1: con Windows en modo oscuro, en la ventana principal «Expulsar» (con y sin llavero) y «Bloquear» (raíz cifrada); y un error (el script del vestíbulo sin su fichero, por ejemplo). Repetirlo a 150 % de escala y en un segundo monitor. | Los cuadros salen oscuros sobre la ventana oscura (no el cuadro claro de Windows), centrados sobre ella, con el botón principal enfocado; Intro acepta y Escape cancela; ni cortados ni detrás de la ventana. | `ui.tk.preguntar()`, `ui.tk.avisar()` |

## El nombre por defecto de las unidades

`common/nombres.py` (#128): sin nombre propio, una unidad se llama como la etiqueta de su
volumen o «prdrive · <4 del id>», y solo si dos coinciden lleva detrás el equipo que la
aprovisionó. Probado con dobles de la etiqueta y de `fleet.json`; falta lo que lee de verdad
el sistema.

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| N1 | W, L | Dos pendrives aprovisionados desde el mismo ordenador y sin nombre propio (el instalador guarda el nombre del equipo en `state/fleet.json`), uno con etiqueta de volumen («AZUL») y otro sin ella; los dos puestos a la vez. | En el menú de la bandeja, en los avisos y en `agente.log` salen «AZUL» y «prdrive · xxxx», no el nombre del ordenador dos veces. En Windows, la etiqueta es la que enseña el Explorador; en Linux, la de `/dev/disk/by-label` (con udisks, con espacios y acentos bien). | `nombres.etiqueta_de()`, `agente.nombre_de()` |
| N2 | W, L | Los dos pendrives con la misma etiqueta («USB DISK»), puestos uno detrás de otro y luego los dos a la vez; después ponerle nombre propio a uno desde «Ajustes → Nombre e icono». | El segundo lleva el equipo detrás («USB DISK (DESKTOP-…)»); el primero no cambia mientras siga puesto. El que tiene nombre propio sale con él, sin sufijo, y el otro se distingue de él. | `nombres.distinguir()`, `Agente._nombres_de_otras()` |
| N3 | W | Un pendrive que el agente ya atendía con el nombre del ordenador (de antes de este cambio): actualizar el agente y volver a enchufarlo. | Deja de llamarse como el ordenador en cuanto se conecta (etiqueta o «prdrive · xxxx») y `agente.json` lo recuerda con el nombre nuevo; uno al que la persona puso nombre propio lo conserva. | `agente.nombre_de()`, `nombres.es_del_equipo()` |

## El arranque en los registros de bloqueo

Los registros de la ventana, el servicio, el vigilante del llavero y el agente
(`ui.lock.json`, `daemon.lock.json`, `llavero.lock.json`, `agente.lock.json`)
apuntan cuándo arrancó el sistema (`store.arranque_del_sistema()`), y un pid
vivo de otro arranque no cuenta como vivo (`store.vivo_en_este_arranque()`). En
Windows ese arranque sale de la hora menos `GetTickCount64()`; con el inicio
rápido, «Apagar» hiberna el núcleo y al encender sigue contando desde el mismo
arranque, así que ahí la comprobación cae al pid solo. Los tests fijan el
arranque a mano: lo que falta es verlo en un equipo de verdad.

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| H1 | W (con el inicio rápido activado) | Con la ventana de runsync abierta sobre una unidad (y el agente en marcha en esa raíz), «Apagar» el equipo (no «Reiniciar»), encenderlo y mirar `ui.lock.json` y `agente.lock.json`. Buscar un proceso cualquiera que haya heredado el pid que apuntan (`tasklist /FI "PID eq <pid>"`); si no lo hay, repetir hasta que lo haya o dar la prueba por no concluyente. | Apuntar si el `arranque` de los registros de antes coincide con el de ahora (se espera que sí: el núcleo se reanuda). Entonces un pid reutilizado SÍ bloquea la ventana nueva («ya hay una ventana abierta») y el agente SÍ se queda en pausa por ella: es el límite conocido (cae al pid solo, como antes). Si NO coincide, la ventana nueva se abre y el registro viejo se limpia. | `store.arranque_del_sistema()`, `store.vivo_en_este_arranque()`, `runsync._viva_aqui()`, `agente._registro_vivo()` |
| H2 | W, L | «Reiniciar» (no «Apagar») con la ventana abierta y el agente en marcha; tras volver, abrir la ventana otra vez. | La ventana nueva se abre sin decir que ya hay otra, `ui.lock.json` pasa a ser el suyo y el agente no se queda en pausa por el registro de antes. | `runsync.tomar_ui()`, `agente._registro_vivo()` |
| H3 | W, L | Dejar el equipo encendido más de 7 días con el servicio de runsync y el agente atendiendo la misma raíz (sin apagar ni hibernar) y la sincronización de la hora activada. Pasados los días, mirar la ventana (¿«Servicio en marcha»?), abrir `runsync.py` (que debe parar el servicio, no decir que no hay nada que parar) y `python agente.py status`. | El servicio sigue contando como vivo: su `daemon.lock.json` lleva un `arranque` reciente (lo reescribe en cada ciclo) y la diferencia con el de ahora cabe en `HOLGURA_ARRANQUE` (600 s). `agente.lock.json` solo se escribe al arrancar: apuntar cuánto se ha desviado su `arranque` del de ahora y si el agente sigue contando como vivo para `agente.py status` y el instalador. | `store.HOLGURA_ARRANQUE`, `runsync.daemon_cycle()`, `Agente._apuntar_en_lock()`, `equipo.agente_vivo()` |

## Una unidad bloqueada con BitLocker

El agente reconoce una unidad de su lista enchufada y bloqueada con BitLocker
por el nombre de volumen que apuntó la última vez que la atendió, la enseña en
la bandeja como «(bloqueada)» y ofrece «Desbloquear…», que lanza
`bdeunlock.exe` (diseño:
`docs/superpowers/specs/2026-10-10-agente-bitlocker-bloqueada-design.md`). Los
tests sustituyen el nombre de volumen, el estado de BitLocker y la ventana de
Windows. Visto en un Windows 11 Home ARM64, solo sobre `C:`: el nombre de
volumen se lee sin elevar, `BitLockerProtection` da 1, y el verbo `unlock-bde`
del Explorador es `bdeunlock.exe %1` con `AppliesTo` en el estado 6. Con un
volumen **bloqueado** no se ha visto nada.

Hace falta un pendrive cifrado con BitLocker To Go en un Windows Pro (la
edición Home lo desbloquea pero no lo crea), con prdrive dentro y en la lista
del agente. No se sabe si una máquina de GitHub Actions puede cifrar un disco
virtual: en Windows Server, BitLocker es una característica que pide reiniciar.
Tampoco es cosa de la nube la ventana de contraseña de B7 a B9 (#123, «Pedir la
contraseña al conectarla»): `bdeunlock.exe` pide la contraseña a una persona.

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| B1 | W | Con la unidad desbloqueada y atendida, mirar `agente.json`; expulsarla, enchufarla sin desbloquear y comparar con `mountvol`. | `agente.json` lleva su `volumen`, y es el mismo nombre que `mountvol` da a esa letra con el volumen bloqueado. | `bitlocker.volumen_de()`, `Agente._apuntar_volumen()` |
| B2 | W | Enchufarla bloqueada en otro puerto USB; tras reiniciar el equipo; y repetir con un pendrive sin número de serie y con un disco USB que Windows presente como fijo. | Se reconoce en todos los casos. Si en alguno Windows le da otro nombre de volumen, no sale en la bandeja hasta desbloquearla a mano una vez: apuntar en cuál. | `Agente._mirar_bitlocker()` |
| B3 | W | Con el agente arrancado por su tarea programada (`pythonw`), enchufarla bloqueada y mirar la bandeja, `agente.log` y `agente.py status`. | A los pocos segundos, el desplegable «<nombre> (bloqueada)» con «Desbloquear…», el candado en el icono, una línea «bloqueada con BitLocker en E:\» en el diario y la línea de `status`. Apuntar cuánto tarda la lectura con la unidad recién enchufada, y que el agente no se queda parado en ella. | `cifrada.bitlocker_de()`, `bandeja._bitlocker()` |
| B4 | W | Elegir «Desbloquear…»; elegirlo otra vez con la ventana abierta; repetir con una cuenta sin administrador. | Sale la ventana de BitLocker de Windows para esa letra, sin pedir elevar; mientras está abierta la entrada dice «Desbloqueando: la contraseña la pide Windows» y no abre otra. Apuntar si `bdeunlock.exe` sigue vivo mientras su ventana está abierta: si no, la entrada vuelve enseguida a «Desbloquear…». | `agente.desbloquear_bitlocker()`, `bitlocker.orden_desbloquear()` |
| B5 | W | Teclear la contraseña; y otra vez, desbloqueándola desde el Explorador sin pasar por la bandeja. | La unidad se conecta y se atiende sola. Apuntar cuántos segundos pasan desde que se desbloquea hasta «conectada» en el diario, y si llega `WM_DEVICECHANGE` (se nota porque la conexión es inmediata y no espera al recorrido de 5 s). | `Agente.cada_recorrido()`, `Agente._recorrer()` |
| B6 | W | Cancelar la ventana de Windows sin teclear nada; después, quitar la unidad con la ventana abierta. | Cancelada, la entrada vuelve a «Desbloquear…» y la unidad sigue «(bloqueada)». Quitada, su desplegable desaparece del menú y el icono deja el candado. | `Agente._desbloquear_bitlocker()`, `Agente._mirar_bitlocker()` |
| B7 | W | #123: con «Pedir la contraseña al conectarla» marcada (en el desplegable «<nombre> (bloqueada)» de la bandeja, o en «Ajustes → Configuración» con la unidad abierta), cerrar sesión con la unidad puesta y bloqueada y volver a entrar; después, con el agente ya en marcha, quitarla y enchufarla bloqueada. | Sale sola la ventana de BitLocker de Windows (la de B4) al iniciar sesión y al enchufarla, una vez por conexión, sin ningún aviso de prdrive. Apuntar cuántos segundos pasan hasta la ventana y, sobre todo, si sale al frente o se queda detrás de las demás: la lanza el agente (`pythonw`, de la tarea programada) y no un clic del usuario, y no se sabe si Windows le da el primer plano. | `Agente._pedir_bitlocker()`, `agente.desbloquear_bitlocker()` |
| B8 | W | #123: con esa ventana abierta, cancelarla y esperar un minuto con la unidad puesta; desbloquearla, hacer «Expulsar» y mirar qué ve el agente; quitarla y volver a enchufarla. | Cancelada no vuelve a salir sola mientras siga puesta; desenchufada y enchufada otra vez, sí. Tras «Expulsar» de una unidad con BitLocker, apuntar qué queda a la vista: si Windows la deja bloqueada en su letra, el agente la ve bloqueada y NO debe sacar la ventana (cuenta como la misma conexión); si la deja desmontada sin bloquear o la quita, no hay ventana. | `Agente._desconectar()`, `Agente.bitlocker_presentes` |
| B9 | W | #123: desmarcar la casilla en una unidad de BitLocker (de fábrica va desmarcada) y enchufarla bloqueada; y en una de VeraCrypt (de fábrica va marcada), desmarcarla y enchufarla cerrada. Reiniciar el agente. | La de BitLocker no abre nada, como antes. La de VeraCrypt no saca la contraseña de VeraCrypt, y su «Abrir PRDRIVE» sigue funcionando. Cerrada no tiene desplegable en la bandeja (no se atiende hasta abrirla); el ajuste se cambia con ella abierta. Tras reiniciar el agente, las casillas siguen como se dejaron. | `Agente._vestibulos()`, `Unidad.pedir_al_conectar` |

## Menos consumo y el motor de avisos de Windows

`docs/superpowers/specs/2026-10-11-watch-y-energia-hoja-de-ruta-design.md` («Lo construido») y
`docs/superpowers/pruebas/2026-10-11-watch-energia-windows-medidas.md`. Lo medido salió de un
sobremesa sin batería, con discos virtuales y un remoto local; el motor nuevo se comprobó de verdad
en un disco virtual NTFS (bloqueo del volumen a la primera, 38 ms). Falta lo que solo dice un
equipo de uso, y sobre todo un portátil.

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| C1 | W, L | Un portátil a batería, una unidad con cuatro parejas cada 5 min y nada que cambiar, dos horas; comparar el consumo (`powercfg /srumutil`, `powertop`) con la versión anterior. | Menos despertares y menos procesador; `agente.py status` dice «Hoy: N pasadas (M sin nada que hacer)» y las parejas «cada 20 min». | `planificador.estirado()`, `consumo.py` |
| C2 | W, L | Con una pareja a cada 20 min por llevar rato quieta, cambiar un fichero en el remoto y, aparte, uno local en una pareja sin `watch`. | Los dos se sincronizan en la pasada siguiente (hasta 20 min) y la pareja vuelve a cada 5. ¿Es aceptable de fábrica, o hay que bajar el tope? | `Politica.estirar_*` |
| C3 | W, L | Cambiar un fichero en una unidad y pulsar «Expulsar» enseguida; repetir sin red y con otra unidad a media pasada larga. | Sincroniza antes y dice «ya puedes quitarla»; sin red o sin turno, lo dice igual nombrando lo que se queda sin sincronizar, en menos de 20 s. | `Agente._por_subir()` |
| C4 · local 12/10: ok en disco virtual (F24: bloqueo y chkdsk /f); faltan el pendrive, «Quitar hardware», formatear y BitLocker | W | Un pendrive de verdad con una pareja `watch`: «Quitar hardware de forma segura», «Expulsar» del Explorador, `chkdsk X:`, formatear, y bloquearlo con BitLocker, todo con el agente atendiéndolo. | Nadie lo encuentra «en uso»; tras un `chkdsk` la pareja vuelve a oírse sola (un cambio después lanza su pasada). | `ReadDirectoryChanges.dispositivo()` (`GUID_IO_VOLUME_LOCK`) |
| C5 · local 12/10: ok (F26) | W | Copiar 20 000 ficheros a una carpeta vigilada mirando el procesador del agente; y dejar un programa reescribiendo un fichero sin parar. | Una pasada a los 20 s del final, sin que el agente suba del 1 % mientras dura. | `AGRUPAR` |
| C6 · local 12/10: ok en Windows con el .~lock y git (F27); faltan Word de verdad y Linux | W, L | En una carpeta vigilada: abrir y cerrar un documento de Word o LibreOffice sin guardar; un `git status` en un repositorio dentro. | Ninguna pasada por los temporales y los `.lock` que nacen y mueren (el `~$` de Word, que vive mientras el documento está abierto, sí cuesta las suyas). | `avisos_carpeta.Neto` |
| C7 · local 12/10: ok el motor (F25); falta verlo con el agente | W | Renombrar la carpeta de una pareja vigilada y crear otra con su nombre; intentar renombrar la carpeta de encima. | La primera se nota como mucho en la pasada siguiente (el diario dice que se recorre) y a los dos minutos se vuelve a oír la nueva. La de encima no se deja renombrar: es lo que dice la guía. | `Win32.ruta_final()`, `Agente._toca_volver_a_oir()` |
| C8 | W, L | Sin ninguna unidad, dejar el agente una hora y mirar sus despertares; después `agente.py pasada`, el menú de la bandeja, y enchufar una unidad. | Dos vueltas por minuto en reposo, y todo lo pedido se atiende al momento (el diario dice «oigo el buzón del agente»). | `cuanto_esperar()`, `avisos_buzon.py` |
| C9 | W, L | Con una unidad atendida y quieta, mirar su luz de actividad o su tráfico (`iostat`, el Monitor de recursos). Abrir su ventana y cerrarla. | Casi sin tráfico entre pasadas; la ventana se abre sin esperar más que antes y, al cerrarla, el agente vuelve en los 15 s de siempre. | `mirar_estado()`, `Agente._registro()` |
| C10 · local 12/10: ok (F18, F23 y F28: orden con y sin /silent, botón de su ventana, desmontaje automático forzando y sin forzar); el ajuste ya viene encendido; faltan el .bat entero y un pendrive | W | `agente.py ajuste avisos_veracrypt sí`, reiniciar el agente, y con una pareja `watch` en un volumen de VeraCrypt: desmontarlo desde la ventana de VeraCrypt, con `Expulsar PRDRIVE.bat`, con su desmontaje automático, y con un fichero abierto dentro. | El diario dice que oye los volúmenes de VeraCrypt y la pareja no se recorre; el desmontaje no pregunta «¿forzar?» por culpa del agente; si se cancela, a los 5 s se vuelve a oír. Visto el 12/10/2026 en un sobremesa: el ajuste viene encendido. | `ReadDirectoryChanges.volumen()` |
| C11 | W, L | Una unidad con cuatro parejas del mismo intervalo: mirar los procesos en una pasada. | Tras la primera vuelta, un solo `sync.py` por ciclo con sus cuatro rclone seguidos; cada pareja con su resultado en la ventana y en la bandeja. | `Agente._acompanan()` |

## El nombre y el icono de una unidad VeraCrypt (#63)

El Explorador no lee el `autorun.inf` de un volumen que monta VeraCrypt, así que prdrive copia su
`label=` e `icon=` a `HKCU\Software\Classes\Applications\Explorer.exe\Drives\<letra>\DefaultLabel`
y `DefaultIcon`, con la marca `PRDRIVE` (`common/explorador.py`, `drive-name-icon.md`). Visto en real
el 15/10/2026: `DefaultIcon` en un volumen VeraCrypt (a mano, comentario D1 del #63) y los dos en una
letra de `subst` (`poner()`/`quitar()` de verdad, y la subrutina `:olvidar_letra` del `.bat`).
Falta con prdrive abriendo un volumen VeraCrypt de verdad, en un pendrive con un `.ico` propio.

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| I1 | W | Abrir la unidad con `Abrir PRDRIVE.bat` y abrir «Este equipo» en una ventana nueva. | La letra del volumen sale con el nombre y el icono de «Nombre e icono», no «PRDRIVE» con el icono genérico. En `regedit` están `DefaultIcon` (ruta absoluta del `.ico`) y `DefaultLabel`, cada una con `PRDRIVE` = el id de la unidad. | `cifrado.nombrar_letra()`, `explorador.poner()` |
| I2 | W | Con «Este equipo» ya abierto, cambiar el icono y el nombre en «Ajustes → Nombre e icono» y guardar. | La ventana abierta cambia sola (`SHChangeNotify`) o, si no, al pulsar F5 (lo que dice la ventana). Apuntar cuál de las dos. | `volumen.guardar()`, `explorador.avisar_shell()` |
| I3 | W | «Expulsar» desde la ventana de prdrive; luego `Expulsar PRDRIVE.bat` de un vestíbulo reescrito (paso 5 o «Añadir plataformas…»). | En los dos, la subclave de la letra desaparece (y `Applications\Explorer.exe` si no tenía nada más). Con un vestíbulo de antes, el `.bat` no la quita: lo hace la ventana o el siguiente arranque de prdrive. | `cifrado.olvidar_letra()`, `:olvidar_letra` |
| I4 | W | Cerrar el volumen desde la ventana de VeraCrypt (o quitar el pendrive sin expulsar), conectar otra unidad que tome esa letra y abrir prdrive desde otro dispositivo. | Al arrancar prdrive se borran las claves huérfanas: la otra unidad sale con su nombre y su icono, no con el `.ico` que ya no está. | `explorador.limpiar()` |
| I5 | W | Con el agente atendiendo la unidad (o la raíz cifrada del equipo): conectarla/desbloquearla y expulsarla/bloquearla desde la bandeja. | Igual que I1 al conectarse y que I3 al irse, sin abrir la ventana de prdrive. | `Agente._conectar()`, `Agente._desconectar()` |
| I6 | W | Con BitLocker, y con una unidad sin cifrar, abrir prdrive. | No se escribe ninguna clave: solo se hace con volúmenes de VeraCrypt (`\Device\VeraCryptVolume<letra>`). | `explorador.de_veracrypt()` |

## Atajos de teclado globales (#109)

«Atajos de teclado…» de la bandeja abre la ventana que los graba (`ui/tk_atajos.py`, por
`pregunta.py --atajos`); el agente los pone con `RegisterHotKey` en el hilo de la bandeja en
Windows, `XGrabKey` en X11 y el portal `org.freedesktop.portal.GlobalShortcuts` en Wayland
(`ui/atajos_linux.py`), y cada atajo pulsado es una petición más (`atajo`) sobre la última unidad
usada (`tray.md`, `agent-window.md`). Visto en la nube: F30 (Windows, con el Bloc de notas
delante) y F31 (X11 en un Xvfb, con otra aplicación con el foco, que no recibe la tecla). El
portal no se ha visto en ningún escritorio: ni Plasma, ni GNOME 48, ni Hyprland.

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| K1 · nube: ok (F30) | W | Con una unidad atendida: «Atajos de teclado…», grabar Ctrl+Alt+F9 en «Sincronizar ahora» y guardar. Con el navegador delante, pulsarlo; mantenerlo pulsado. | La ventana se cierra sola al guardar. Sale el aviso «PEN: sincronizando» y la pasada empieza; el navegador no recibe la tecla. Mantenida, una sola vez (`MOD_NOREPEAT`). | `Bandeja._poner_atajos()`, `WM_HOTKEY`, `Agente._atajo()` |
| K2 | W | Grabar una combinación que ya tenga otro programa (la de un reproductor o la Barra de juegos, `Win+Alt+R`) y guardar; luego una de Windows (`Win+E`). | La ventana sigue abierta y la fila dice «…no se ha podido poner: otro programa (o el propio sistema) ya la usa»; queda sin atajo. Apuntar qué dice Windows de `Win+E`. | `atajos.motivo_windows()`, `Agente._atajos_puestos()` |
| K3 · nube: ok (F31) | L | X11 (GNOME en Xorg, XFCE o KDE en X11): lo mismo que K1, también con el bloqueo de mayúsculas o el numérico encendidos. | Igual que K1, en los tres casos. | `atajos_linux.X11`, `atajos.BLOQUEOS_X11` |
| K4 | L | X11: grabar una combinación del escritorio (`Ctrl+Alt+T`, la terminal) y guardar. | Se dice al guardar: «otro programa (o el propio sistema) ya la usa». Si el escritorio no la agarra con `XGrabKey` (la oye de otra forma), el atajo se pone y pulsarlo hace las dos cosas: apuntarlo. | `Xlib.agarrar()` (`BadAccess`) |
| K5 | L | Wayland con el portal (Plasma 6, GNOME 48 o posterior, Hyprland): «Atajos de teclado…», grabar y guardar; confirmar en la ventana del escritorio. Luego, con otra aplicación delante, pulsarlo. Repetir cancelando la ventana del escritorio. Cerrar sesión y volver a entrar. | Sale la ventana del escritorio con «prdrive: Sincronizar ahora»; aceptada, la de prdrive se cierra y el atajo hace su acción con otra aplicación delante; cancelada, la de prdrive dice «No se ha guardado nada» y siguen los de antes, y el agente los vuelve a pedir: ¿sale otra vez la ventana del escritorio para los de antes? Apuntarlo. Al volver a entrar, ¿pregunta otra vez el escritorio al arrancar el agente? Apuntarlo: si pregunta, el portal pide guardar la sesión de otra forma. | `atajos_linux.Portal`, `Registry.Register("prdrive")` |
| K6 | L | Wayland sin el portal de atajos (GNOME anterior a 48, o un compositor sin `xdg-desktop-portal`): «Atajos de teclado…». | La ventana solo dice «No se pueden usar en este equipo» y por qué (le falta el portal GlobalShortcuts); el diario lo dice una vez. | `atajos.mecanismo()`, `Portal._correr()` |
| K7 | W, L | Dos unidades atendidas: abrir la ventana de una con su propio acceso (no desde la bandeja) y, con ella cerrada, pulsar «Abrir su carpeta»; luego «Configurar» de la otra en la bandeja y otra vez el atajo; luego «Pausar o reanudar» dos veces. | Primero la carpeta de la primera, luego la de la segunda. Pausar dice «PEN: en pausa» y su desplegable «(en pausa)»; la segunda vez, «PEN: reanudada». | `atajos.objetivo()`, `Agente._usada()` |
| K8 | L | X11: con atajos puestos, cerrar la sesión; y matar el servidor X con el agente en marcha (`sudo systemctl restart display-manager`, en una máquina de pruebas). | El agente no deja un volcado ni un aviso de que ha fallado; su diario sigue (o termina con «agente detenido»). | `XSetIOErrorExitHandler`, `Xlib.vivo()` |
| K9 | W | Teclado en español: «Atajos de teclado…», «Grabar» y AltGr+2; luego Ctrl+Alt+E. Guardar Ctrl+Alt+F9 en otra acción y, con el Bloc de notas delante, escribir «@», «#», «€» y «|». | La fila dice que en Windows Ctrl+Alt con una letra o un número es AltGr, y sigue grabando. Con Ctrl+Alt+F9 puesto, los cuatro caracteres se escriben y no salta ningún atajo. | `atajos.problema()` (`ALTGR`) |
| K10 | L | Wayland con el portal: guardar, y dejar la ventana de confirmación del escritorio abierta más de 3 minutos sin contestar. Luego volver a «Atajos de teclado…» y guardar otra vez. | Pasado el plazo, la de prdrive dice que el agente tarda y luego «No se ha guardado nada» (el sistema no ha contestado). El segundo «Guardar» no se queda esperando detrás del primero: la ventana vieja del escritorio se cierra y sale la nueva. | `Portal._abandonar()` (`Request.Close`), `ESPERA_ATAJOS` |
| K11 | L | Wayland con el portal (o X11), con atajos guardados: cerrar la sesión y volver a entrar, con el agente arrancando con la sesión. Mirar su diario. | Si el portal (o la pantalla) no estaba listo al primer intento, el diario dice «no se pueden poner aquí (…); lo vuelvo a intentar en 30 s» y, al rato, «atajos de teclado: con …»; los atajos funcionan sin reiniciar el agente. | `Agente._motor_de_atajos()` (`REINTENTO_ATAJOS`) |
