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
| A12 | W, L | Con la unidad atendida, abrir su ventana (`runsync.py`) desde la unidad. | El agente se pausa (`status`: «en pausa: hay una ventana…»). Al cerrarla, vuelve a atenderla. Con «Iniciar servicio» en la ventana, el agente se aparta. | contrato de la sección 3, `Agente._contrato()` |
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
| R9 | W, L | Volver a pasar el asistente «En este equipo» con el agente ya instalado y añadir la raíz. | El agente no se reinstala. La raíz entra por el buzón (`añadir_raiz`) y se atiende sin reiniciar. | `install/agente.aplicar_unidades(raiz=)`, `PIDE_RAIZ` |
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
| C11 | W | Con la raíz abierta, la ventana (acceso «prdrive»): el botón del pie. | Dice «Bloquear», no «Expulsar». Al pulsarlo, se lo pide al agente, se cierra la ventana y la raíz queda bloqueada como en C4. | `ui/cifrado.bloqueo()` / `pedir_bloqueo()`, `ui/tk.py` |
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

*(se rellena al hacerla)*

## Fase 5 — Ventana ↔ agente

*(se rellena al hacerla)*

## Fase 6 — Bandeja en Linux

*(se rellena al hacerla; el diseño ya pide KDE, GNOME con AppIndicator (Ubuntu)
y GNOME sin ella (Fedora))*
