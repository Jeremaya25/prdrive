# Plan: «Servidor…» (el explorador de solo lectura) en máquina real

Fecha: 2026-10-27 · Estado: **por hacer**. Los resultados van en un fichero aparte, al lado de
este (`2026-10-27-servidor-pendiente-en-real-resultados.md`), como los de los demás planes.

Los tests de `tests/test_rcd.py`, `tests/test_servidor.py` y `tests/test_tk_servidor.py`
sustituyen `rclone rcd`, la red y la pantalla. Lo que comprueban es la lógica; **nada de esto
se ha visto con un servidor de verdad, un proceso matado a la fuerza ni una unidad expulsada.**
Las comprobaciones con el binario real de rclone v1.75.2 (resumidas en
`docs/agents/reference/servidor.md`) se hicieron, pero no en un equipo con un dispositivo prdrive.

«Lo esperado» sale del código y del comportamiento que documenta `docs/agents/reference/servidor.md`.
En un equipo real manda lo que se vea: si no coincide, se apunta la diferencia tal cual y no se
reinterpreta.

## Equipos

- **W**: Windows 11 x64, con un dispositivo prdrive y el agente, y un servidor SFTP al que se
  llegue (un Linux con `sshd` en la misma red, o el propio equipo).
- **L**: un escritorio Linux con systemd y udisks2, con el mismo dispositivo y el mismo tipo de
  servidor.

Para las filas de SFTP, el servidor tiene una cuenta **sin dueño** sobre la carpeta de prueba:
`/srv/prueba/sin-permiso` con `chmod 700` y propietaria otra cuenta, y `/srv/prueba/abierta` con
`chmod 755`. Las rutas de las filas son absolutas en el servidor, que es lo que el explorador
muestra desde `/`.

## Pruebas

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| S1 | W, L | Abrir «Servidor…» con un remoto SFTP, entrar en una carpeta para que el `rclone rcd` esté vivo, y matar a la fuerza el proceso de la ventana (Windows: «Finalizar tarea» en el Administrador de tareas; Linux: `kill -9` al pid de `runsync.py`). Mirar la lista de procesos (`rclone rcd` en el Administrador de tareas, `pgrep -a rclone` en Linux) durante 10 s. | No queda ningún `rclone rcd` vivo: en Windows lo mata el Job Object; en Linux, `PR_SET_PDEATHSIG`. Nada en `state/rcd.json` apunta a un proceso que ya no existe la siguiente vez que se abre la ventana. | `common/rcd.py`: `atar_al_job()`, `_opciones_popen()`, `_morir_con_el_padre()`, `limpiar_huerfano()` |
| S2 | W, L | Con «Servidor…» abierto y una carpeta del servidor vista, cerrar la ventana con su botón «Cerrar». En cuanto se cierre, pulsar «Expulsar» en la ventana principal. Repetir cerrando con la X de la ventana. | La unidad se expulsa sin el aviso de «archivo en uso». El `rclone rcd` desaparece en unos 3 s tras cerrar (`ESPERA_QUIT`); si la expulsión llega antes, la ventana principal lo corta con `matar_hijos()`. | `rcd.Rcd.parar()`, `store.matar_hijos()`, `store._HIJOS` |
| S3 | W, L | Ocupar a mano el puerto que va a elegir prdrive: un script con `socket.bind(("127.0.0.1", P))` y `listen()`, donde `P` es el puerto que `common.rcd.puerto_libre()` devuelve (se fuerza ese valor en un intérprete de pruebas que llama a `ui.tk_servidor.open_dialog`). Después, abrir «Servidor…» sin nada más. | rclone sale con `address already in use` («Only one usage of each socket address» en Windows) y la ventana reintenta **una vez** con otro puerto y se ve la raíz. Si el segundo intento también choca: el texto «El puerto que se eligió para rclone ya lo usa otro programa.» con «Reintentar». | `rcd.PuertoOcupado`, `Rcd.esperar()`, `_FRASES_PUERTO_OCUPADO`, `tk_servidor.fallo()` |
| S4 | W, L | En el SFTP real, entrar en `sin-permiso` desde la raíz de la cuenta de prueba (sin haber entrado antes). Luego volver a `abierta` y entrar en `sin-permiso` otra vez. | Primera vez: la tabla se queda con la raíz, sale «No tienes permiso para ver esta carpeta.» y `sin-permiso` lleva candado y va apagada. Segunda vez: el mismo resultado, y el candado sigue puesto mientras la ventana esté abierta. La frase es la de prdrive, no el texto crudo de rclone: si rclone dice otra cosa (p. ej. `SSH_FX_PERMISSION_DENIED` sin «permission denied»), se anota el texto exacto. | `servidor.es_de_permiso()`, `Navegacion.sin_acceso`, `servidor.frase_error()` |
| S5 | W, L | Con el `rclone` del dispositivo (`common/pins.py`, `RCLONE_VERSION`), `rclone rcd` a mano con usuario y contraseña en el entorno (`RCLONE_RC_USER`/`RCLONE_RC_PASS`) y `operations/list` con `fs = "<remoto>:/"` y `remote = "abierta"`: tres veces con `opt` = `{"noMimeType": true}` y tres con `opt` = `{"noMimeType": true, "metadata": true}`, con el cronómetro. Mirar el log de `sshd` mientras: un solo inicio de sesión y un solo directorio abierto por listado. | Con `metadata: true` contra SFTP v1.75.2: ni error, ni una respuesta más lenta que sin él (diferencia dentro del ruido de las seis medidas), ni más aperturas de directorio. Si la respuesta trae `Metadata`, se anota tal cual; la columna de la ventana sigue en «—» con este rclone. | `servidor.params_listado()` (`opt.metadata`); `servidor.pide_permisos()` decide que hoy no se pide |
| S6 | W, L | Abrir «Servidor…», entrar en cinco carpetas seguidas (con el cronómetro, un clic cada vez) y mirar el log de `sshd`: cuántos inicios de sesión SSH hay en todo el rato. Repetir con `Examinar…` de una pareja (`tk_pairs.explorador_remoto`), cinco carpetas, midiendo lo mismo. Después, con `rclone rcd` a mano como en S5, un `operations/stat` con `fs = "<remoto>:"` y `remote = ""` (la carpeta de inicio, que es lo que pide la ventana cuando hay permisos): el log debe mostrar un inicio de sesión más, y solo ese. | Explorador: **un** inicio de sesión para todas las carpetas (`remote:/`), y cada clic tarda milisegundos tras el primero; «Examinar…» abre una conexión por carpeta, 0,5–2 s por clic. El `stat` de `remote:` añade un segundo inicio de sesión, y solo ese. | `servidor.params_listado()` (`fs` fijo), `rcd` (la caché de objetos de rclone), `tk_servidor._leer()` |
| S7 · cuando RCLONE_VERSION lo traiga | W, L | **Solo cuando el `rclone` fijado incluya el PR rclone/rclone#9631** (no antes; comprobarlo en `common/pins.py`). Con ese rclone: `operations/fsinfo` de un SFTP; un listado con `opt.metadata`; `operations/stat` de `<remote>:` con `opt.metadata`. Comparar con la lista de comprobación de `docs/agents/reference/servidor.md`, «Permissions». | `fsinfo` dice `ReadMetadata: true`; el listado trae `Metadata.mode` en formato `100600`/`40755`, `uid` y `gid` en decimal, sin peticiones extra al servidor; el `stat` de `<remote>:` da `uid`. La columna de permisos se rellena (tres cifras) y el candado previo sale solo en carpetas sin `r`+`x` para el dueño, sin cambiar código. Si algo falla, la columna sigue en «—» y nada se rompe. | `servidor.pide_permisos()`, `servidor._entrada()`, `servidor.mi_uid_de()`, `servidor.sin_acceso_previo()` |

Ninguna fila tiene todavía su prueba en la nube. S1 en Linux (matar a la fuerza y comprobar que
el proceso hijo desaparece) es lo más cercano a `tests/maquina/` (`fNN_*.py`, la skill
`real-machine-tests`): comprueba el borde del sistema, sin el servidor ni la ventana. Se puede
escribir cuando haga falta; hoy no existe.

## Qué hacer con lo que salga

- Una diferencia entre lo que pasa y lo que se espera: una incidencia en GitHub, con el equipo
  (W o L), el servidor (versión de OpenSSH y de rclone) y, si es posible, el log de `sshd` y el
  texto exacto que dio rclone.
- Una fila que sale bien en un equipo de verdad: se marca aquí y no se borra.
- Un `rclone` que cambia la forma de `Metadata` o de `ReadMetadata` (S7): se anota el formato
  exacto antes de tocar `ui/servidor.py`.
