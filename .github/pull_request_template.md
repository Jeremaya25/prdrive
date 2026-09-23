<!--
EL TÍTULO: la release se publica con `--generate-notes`, así que el título de
esta PR acaba en la ventana de actualización de cada dispositivo. Escríbelo en
castellano y para quien usa el dispositivo: qué cambia para él, no qué función
se ha tocado. Si cierra un issue, «(#N)» al final.

Borra lo que no aplique. Una casilla marcada es una afirmación: si no lo has
comprobado, no la marques, y dilo.
-->

## Qué cambia y por qué

<!-- El problema en una o dos frases y cómo lo resuelve esto. Si hay un spec en
docs/superpowers/specs/, enlázalo en vez de repetirlo. -->

Closes #

## Dónde toca

<!-- Cada sitio donde este cambio lee o escribe. Decide qué hay que probar y qué
puede romperse en un dispositivo que ya está en uso. -->

- [ ] El dispositivo: el código de `.prdrive/`, `state/`, `sync_config.toml`
- [ ] El equipo anfitrión: el vigilante (`penwatch.py`, `watch.json`, la tarea o la unidad)
- [ ] El remoto: los datos sincronizados, el catálogo (`pairs.toml`) o las notas de la flota (`devices/`)
- [ ] El instalador: `install/`, `prdrive-install.py`, `build_installer.py`
- [ ] Solo la ventana o el menú de consola

## Datos en juego

<!-- Lo que puede borrar ficheros, o hacer creer a bisync que se han borrado. Si
no toca nada de esto, escribe «Ninguno» y borra la lista. -->

- [ ] Cambia algo que entra en `bisync.expected_prefix()` (`local`, `remote`, `remote_path`, `mode`, `device_remote`, `RAIZ_UPSTREAM`). Qué baselines se apartan, y quién pide el `--resync`:
- [ ] Toca `max-delete`, `_bisync_preflight()`, los filtros o `--backup-dir`
- [ ] Toca un modo `*-mirror`, y se ha probado con `--dry-run` antes que sin él
- [ ] Borra algo, en el dispositivo o en el remoto, y pasa por `confirmar_plan()` con sus consecuencias

## Dispositivos que ya existen

<!-- Un dispositivo se actualiza con `--update`, no se vuelve a aprovisionar: lo
que escribió la versión anterior sigue ahí. Contesta las que apliquen. -->

- **Estado y configuración de antes**: ¿qué pasa con lo que dejó la versión anterior en `state/` o en `sync_config.toml`?
- **El vigilante de cada equipo** es la copia que hizo `install`, y no se actualiza solo: ¿funciona igual con una copia anterior?
- **La flota**: ¿qué ve un dispositivo con otra versión que lee el mismo catálogo o las mismas notas?
- **Ficheros nuevos que tienen que llegar al dispositivo**: están en `DEPLOY_FILES`/`DEPLOY_TREES` (`install/deploy.py`) **y** en `DATOS_FICHEROS`/`DATOS_ARBOLES` (`build_installer.py`).
- Los lanzadores de la raíz no se reescriben al actualizar: nada de esto cuenta con que cambien.

## Comprobado

<!-- Aquí no hay CI que pase los tests: cuenta cómo se ha hecho. Los tests de Tk
se saltan solos cuando no hay pantalla, así que un «todo verde» sin Tk no ha
probado ninguna ventana. -->

- [ ] `python tests/run_all.py`: __ de __ ficheros · Tk: sí / no · sistema:
- [ ] Tests nuevos o cambiados que fallan sin este cambio
- [ ] Las pantallas nuevas, o las que crecen, están en la matriz de `tests/test_tk_medidas.py`
- [ ] En un dispositivo de verdad (plataforma, cifrado, qué se ha hecho):
- [ ] `sync.py --doctor` / `--dry-run` sobre:

## Reglas del repositorio

<!-- Las que se rompen sin querer. El detalle está en AGENTS.md. -->

- [ ] Solo biblioteca estándar, Python 3.11; `import tkinter` dentro de las funciones
- [ ] Las capas siguen separadas: los `tk_*` solo dibujan; `penwatch.py` no importa `common/` ni `ui/`; `install/` no importa `ui/` fuera de `tk_install`
- [ ] Lo nuevo que toca la red, un dispositivo o el escritorio es una función de módulo que un test puede sustituir
- [ ] Las constantes repetidas a propósito (`CONTROL_FILE`, `RUNTIME_STAMP`, las rutas de los locks…) siguen iguales en todas sus copias
- [ ] Colores, fuentes y glifos salen de `theme.py` e `icons.py`, y las medidas pasan por `theme.medida()`
- [ ] Comentarios, docstrings y textos en castellano, con las citas al código de rclone, VeraCrypt o la ISO conservadas

## Documentación y versión

- [ ] AGENTS.md
- [ ] README.md
- [ ] `device-readme.md`: la guía corta que va al dispositivo, sin detalles internos
- [ ] `sync_config.example.toml`, si cambia el esquema
- [ ] `VERSION` sube a ____: **el merge a `main` publica la release**
