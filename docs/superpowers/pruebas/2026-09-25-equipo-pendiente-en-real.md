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
| A10 | W, L | Desconectar la red con una pareja en marcha. | Un aviso «sin conexión con …»; ya no se lanzan las parejas una a una, sino una sonda cada 5 min. Al volver la red, sigue sola. | `Agente._fin_de_sonda()` |
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
| B1 | W | Iniciar sesión con el agente instalado. | El icono sale en la bandeja (quizá en el desbordamiento «^»), con la marca y la línea «prdrive — al día» (o lo que toque) al pasar el ratón. Nítido al 100 %, 125 %, 150 % y 200 % (se carga a `SM_CXSMICON` con la densidad declarada). | `Bandeja.arrancar()`, `Api.ventana()` / `icono()` / `notificar()`, `icons.write_bandeja()`, `theme.nitidez()` |
| B2 | W | Iniciar sesión con el agente arrancando antes que la barra de tareas (equipo lento, o reiniciar el Explorador en el Administrador de tareas con el agente en marcha). | El icono aparece al crearse la barra (`TaskbarCreated`) y vuelve tras reiniciar el Explorador. | `Bandeja._mensaje()` con `TaskbarCreated` |
| B3 | W | Clic derecho y clic izquierdo en el icono; pinchar fuera del menú; Esc. | El menú sale donde está el ratón, «Abrir …» en negrita, las casillas marcadas donde toca; al pinchar fuera o con Esc se cierra sin elegir nada. | `Api.menu()`: `SetForegroundWindow` + `TrackPopupMenu(TPM_RETURNCMD)` + `WM_NULL` |
| B4 | W | Cada entrada: «Abrir», «Sincronizar ahora» (y su submenú con dos unidades), «Pausar» / «Reanudar», «Cerrar el agente». | Cada una hace lo suyo en uno o dos segundos (el agente se despierta, no espera al tic). «Cerrar el agente» lo termina y quita el icono. Un nombre con `&` sale tal cual. | `bandeja.vista()`, `Agente.pedir()`, `Vigia.despertar()`, `texto_menu()` |
| B5 | W | Los cinco estados: al día, una pasada en marcha, una pareja que falla, en pausa (y en red de uso medido), la raíz cifrada bloqueada. | El icono cambia (pastilla azul, ámbar, campo gris con barras, candado oscuro) y la línea lo dice. Distinguibles a 16 px sobre la barra clara y la oscura. | `bandeja.estado()`, `icons.capas_bandeja()` |
| B6 | W | Enchufar una unidad de la lista; quitarla; abrir y cerrar su VeraCrypt. | Se ve en segundos, no a los 5 s del sondeo: `WM_DEVICECHANGE` despierta la racha. Sin tocar nada, el recorrido de respaldo pasa a cada 30 s (el diario lo delata por los tiempos). Comprobar que la ventana oculta **sí** recibe `DBT_DEVICEARRIVAL` de un volumen y de un montaje de VeraCrypt. | `Bandeja._mensaje()` con `WM_DEVICECHANGE`, `cmd_run()` (`RECORRIDO_RESPALDO`) |
| B7 | W | Enchufar una unidad que no está en la lista y dejar pasar la pregunta. | La entrada «PRDRIVE-2, conectada · Atender…» la añade a la lista y la atiende. Nunca sale «Abrir» para ella antes del sí. | `bandeja._unidades()`, `PIDE_ATENDER` |
| B8 | W | Raíz cifrada: «Desbloquear…», «Bloquear», la casilla «Pedir la contraseña al iniciar sesión», y «Abrir …» con la raíz bloqueada. | Como C4–C9, desde el menú. «Abrir» con ella bloqueada pide la contraseña y abre la ventana sola al montarse. Cancelar la contraseña: a los ~20 s vuelve a ofrecer «Desbloquear…». La casilla cambia `agente.json` (lo escribe el agente). | `Agente._abrir()`, `_desbloquear(abrir=)`, `_seguir_desbloqueos()`, `PIDE_AJUSTE` |
| B9 | W | Un aviso (una pareja que empieza a fallar, una unidad nueva). | Sale como notificación del sistema **colgada del icono de la bandeja** (sin el icono de paso que aparece y desaparece), con el título y el texto; de aviso si es urgente. | `Bandeja.globo()`, `avisos.GLOBO`, `NIF_INFO` |
| B10 | W | Suspender y volver, con un remoto «sin conexión» (red caída antes de suspender, y de vuelta al despertar). | Al volver se sondea el remoto enseguida y se lee la batería y la red, sin esperar los 5 min del sondeo. | `WM_POWERBROADCAST` / `PBT_APMRESUMEAUTOMATIC`, `PIDE_DESPERTAR` |
| B11 | W | Cerrar sesión y volver a entrar; y `agente.py parar`. | No queda un icono huérfano en la bandeja (`NIM_DELETE` al cerrar); si queda por un cierre a la fuerza, desaparece al pasar el ratón. | `Bandeja.cerrar()`, `WM_DESTROY` |
| B12 | WA | B1, B3 y B6 en Windows ARM64 con el runtime ARM64. | Lo mismo. | ctypes en ARM64 |

## Fase 5 — Ventana ↔ agente

La ventana de una raíz le habla al agente por dos buzones: `state\servicio.pide`
en la raíz (lo de esa raíz: `reanudar`, `pasada`, `bloquear`) y `agente.pide`
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
| V1 | W, L | Unidad atendida por el agente en modo `daemon`. Abrir su ventana, marcar otras parejas, poner otro intervalo y pulsar «Iniciar servicio». | Ningún `pythonw` nuevo desde la unidad. El mensaje dice que el agente vuelve al cerrar la ventana. Al cerrarla, el agente vuelve **enseguida** (sin los 15 s de gracia), con una pasada, y su `daemon.lock.json` lleva las parejas y el intervalo elegidos. | `runsync._atender()` / `agente_sirve()` / `pedir_reanudar()`, `Agente._buzones_de_raices()`, `PIDE_REANUDAR` |
| V2 | W, L | V1 con la unidad en modo `sync`, y otra vez con el agente parado (`agente.py parar`). | El servicio de siempre (un `pythonw` de la unidad con su `daemon.lock.json`), y el agente se aparta mientras vive. | `watch.Resumen.servicio_del_agente` |
| V3 | W, L | La línea del agente en la ventana: con el agente en marcha, en pausa (su «Pausar») y parado. | Dice qué hace con esa unidad; en pausa lo dice; parado va en ámbar y dice que arranca al iniciar sesión. | `watch.linea()`, `watch._agente()` (lee `agente.lock.json` y `estado.json`) |
| V4 | W, L | «Cambiar…» en esa línea: pasar la unidad a «Nada», y luego a «Sincronizarlo en segundo plano». | La línea cambia al momento; en unos segundos el agente suelta la unidad (su `daemon.lock.json` desaparece) y la vuelve a tomar. `agente.json` lo escribe el agente (su hora de modificación es la del agente, no la de la ventana). | `ui/tk_watch.open_agente()`, `watch.pedir_modo()`, `PIDE_MODO` |
| V5 | W, L | Enchufar una unidad que no está en la lista, contestar «Ahora no», abrir su ventana desde la unidad y pulsar «Atender…» en la línea. | Entra en la lista con el modo elegido y el nombre de su flota. | `PIDE_MODO` de una unidad nueva |
| V6 | W, L | Raíz cifrada: «Ajustes» de su ventana, desmarcar «Pedir la contraseña al iniciar sesión». Cerrar sesión y volver a entrar. | No pide la contraseña al entrar; la casilla de la bandeja sale desmarcada. Volver a marcarla la deja como estaba. En una unidad o una raíz sin cifrar la casilla no sale. | `ui/tk_doctor.py`, `watch.pedir_al_iniciar()` / `pedir_ajuste()` |
| V7 | W, L | Volver a pasar el asistente «En este equipo» con el agente de la misma versión en marcha, añadiendo una raíz. | «Instalación» dice que no se reinstala; «Arranque» dice «Pedírselo al agente». El pid de `agente.lock.json` es el mismo antes y después, y la raíz se atiende sin reiniciar. | `install/agente.misma_version()` / `anadir()`, `ui/tk_equipo.py` |
| V8 | W | Con el `VERSION` rebajado (ver arriba): esperar el aviso y pulsar «Actualizar a la vX» en la bandeja. | Un aviso «Hay una versión nueva…» **una** vez. Tras pulsar, «Actualizando…» apagado; en menos de un minuto el icono se va y vuelve (el agente nuevo), `instalacion.json` apunta a `agente\<vX>`, la tarea programada también, la carpeta vieja ha desaparecido y el diario cuenta cada paso con «actualizar:». Otro aviso: «prdrive actualizado a la vX». | `Agente._mirar_version()` / `_actualizar()`, `agente.cmd_actualizar()`, `prdrive-install.py --update-agente`, `install/agente.actualizar()` |
| V9 | W | V8 con la raíz del equipo abierta y su ventana abierta; y otra vez con la raíz cifrada bloqueada. | Abierta: el código de su `.prdrive\` pasa a la vX sin tocar `sync_config.toml`, `state\` ni la clave. Bloqueada: el diario dice que su ventana lo ofrecerá, y al desbloquearla la ventana ofrece «Actualizar…». | `install/agente.actualizar_raices()`, `deploy.deploy_code()` |
| V10 | W | V8 con una versión que cambie el Python fijado (`pins.py`). | El runtime nuevo va a su carpeta al lado; el viejo, con el que corría «Actualizar», **no** se borra esa vez y se recoge en la siguiente instalación. El agente nuevo arranca con el nuevo. | `install/agente.podar()` (conserva el de `sys.executable`) |
| V11 | W | V8 sin red, y con un proxy que corte la descarga. | Aviso «no he podido actualizar»; el agente viejo sigue en marcha como estaba, y «Actualizar» se puede volver a pedir. | `update.download()`, `Agente._mirar_version()` |
| V12 | L | V8 en Linux: con bandeja (KDE), desde su menú; sin ella (GNOME sin AppIndicator), con `python agente.py actualizar`. | Con bandeja, como V8. Sin ella, el aviso dice «python agente.py actualizar», y ejecutarlo hace lo mismo (autostart y acceso del menú reescritos a la versión nueva). | `Agente.con_bandeja()`, `agente.cmd_actualizar()`, `install/agente.registrar()` en Linux |

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
| T3 | K, U | Clic izquierdo y derecho en el icono; pinchar fuera; Esc. | El menú sale con los dos (`ItemIsMenu`); se cierra sin elegir nada. Las casillas marcadas donde toca, las entradas apagadas en gris, el submenú de «Sincronizar ahora» con dos unidades, y un nombre con `_` sale tal cual (sin letra subrayada). No hay negrita en «Abrir» (dbusmenu no tiene entrada por defecto). | `Menu.disposicion()` / `propiedades()`, `etiqueta()` |
| T4 | K, U | Cada entrada, como B4: «Abrir», «Sincronizar ahora», «Pausar» / «Reanudar», «Cerrar el agente», y las de la raíz cifrada (B8). | Cada una hace lo suyo en uno o dos segundos. «Cerrar el agente» quita el icono. | `Event` / `EventGroup` → `Menu.pulsada()` → `Agente.pedir()` + `Vigia.despertar()` |
| T5 | K, U | Con el menú abierto, que cambie el estado (termina una pasada, se enchufa una unidad). | El menú se actualiza al volver a abrirlo (`LayoutUpdated`); pulsar una entrada del menú viejo hace lo que decía, no otra cosa. | `Menu.poner()` (ids nuevos en cada cambio, la numeración anterior guardada) |
| T6 | K, U | Los cinco estados de B5. | El icono cambia (`NewIcon`) y el texto al pasar el ratón también (`NewToolTip`); con avisos, Plasma lo marca como que pide atención (`NeedsAttention`) sin parpadear sin fin. | `_poner_pendiente()`, `Status` / `AttentionIconPixmap` |
| T7 | F | Instalar «solo agente» y con raíz en GNOME sin la extensión. | El diario dice «este escritorio no tiene bandeja»; «Verificación» del asistente tiene la fila «Bandeja» en rojo con el nombre de la extensión. En el menú de aplicaciones hay un «prdrive». | `poner_bandeja()`, `tk_equipo.escritorio()` / `SIN_BANDEJA`, `install/agente.quiere_menu()` |
| T8 | F | Desde ese «prdrive» del menú: con el agente parado (`agente.py parar`); en marcha sin raíz; en marcha con la raíz; con la raíz cifrada bloqueada. | Parado: lo arranca (y sin raíz lo dice con un aviso). Sin raíz: un aviso con el estado, lo mismo que diría el icono. Con raíz: su ventana. Bloqueada: VeraCrypt pide la contraseña y la ventana se abre al montarse. | `agente.cmd_abrir()` / `arrancar_agente()`, `bandeja.aviso_de_estado()` |
| T9 | F | Activar la extensión AppIndicator con el agente en marcha (sin cerrar sesión). | El icono aparece solo, sin reiniciar el agente. | `NameOwnerChanged`, `StatusNotifierHostRegistered` |
| T10 | K, U | Suspender y volver con un remoto sin conexión (B10). | Al volver, el diario muestra el sondeo enseguida (`PrepareForSleep(false)` de logind en el bus del sistema). | `REGLA_SUSPENDER`, `PIDE_DESPERTAR` |
| T11 | K, U | Enchufar y quitar una unidad con la bandeja puesta. | Igual de rápido que sin ella: en Linux los montajes siguen llegando por `mountinfo`, no por la bandeja. | `Vigia` |
| T12 | K | Cerrar sesión y volver a entrar; `agente.py parar`. | No queda un icono huérfano: al irse el agente, el watcher lo quita al perder su nombre el dueño. | `Bandeja.cerrar()` |
