# El catálogo sin carpeta local: cada dispositivo elige la suya — diseño

Fecha: 01/11/2026. Issue: #196. Estado: **aprobado por el dueño** (01/11/2026, sin
revisión de la spec escrita: «sí, y ve directo»).

Decidido con el dueño el 01/11/2026:
- **El instalador pregunta la carpeta de cada pareja que se marca**, ya rellena con el
  nombre de la pareja. «Dejarlas todas sin usar» queda descartado: obligaría a que
  `sync.py`, el servicio y la pantalla de parejas aceptasen un `sync_config.toml` sin
  ninguna pareja, y hoy los tres lo rechazan.
- **Los dispositivos sin actualizar se aceptan y se avisa.** En cuanto el catálogo tenga
  una pareja sin `local`, un dispositivo de la versión anterior sigue sincronizando (su
  `sync_config.toml` está completo), pero sus parejas salen «modificada aquí», «Usar
  aquí» de una pareja nueva le da error y no puede editar el catálogo (falla sin escribir
  nada). Un instalador anterior no puede leer el catálogo. Ningún dato corre peligro: se
  dice en la guía, en el título del PR y en el plan de la subida que lo quita. Sin marca
  nueva en `fleet.ENTIENDE` y sin bloqueo.

## Qué se quiere

La carpeta local es de cada dispositivo, no del catálogo que comparten todos. Hoy cada
`[[pair]]` del catálogo (`remote.toml`) trae su `local` y «Usar aquí» lo copia tal cual:
todos los dispositivos acaban con la misma estructura de carpetas. Después del cambio el
catálogo describe solo el lado remoto (`name`, `remote`, `remote_path`, `mode`, filtros,
flags, `versions`, `watch`…) y cada dispositivo elige su carpeta al meter la pareja.

`sync_config.toml` no cambia de forma: sigue llevando entradas **completas**, con su
`local` (`sync.py` no necesita red).

## Diseño

### 1. Un solo sitio quita `local` del catálogo

`common/catalog.py` gana `sin_local(raw) -> dict`: una copia del catálogo en bruto con
`local` quitado de cada `[[pair]]`. La usan:

- **Los dos lectores**: `catalog._parse()` (lo que lee `pull()`) y `cached()` en el
  dispositivo, y `install/remote.parse_catalog()` en el instalador. `Catalog.raw` nunca
  lleva `local`; `Catalog.text` sigue siendo el fichero tal cual, que es contra lo que
  `push()` compara antes de escribir.
- **`push()`**, antes de generar el texto: cualquier subida (la pantalla de parejas, el
  paso del llavero del instalador, que sube `{**tomllib.loads(texto), "keychain": …}`)
  deja el catálogo sin `local`. Así «al volver a subir el catálogo se elimina» se cumple
  por construcción y nadie tiene que acordarse de quitarlo.

Por qué en la lectura y no en cada consumidor: los que leen `local` del catálogo son
muchos (`diff_keys`, las filas, `plan_enable`, `plan_revert`, los dos asistentes, las
pistas del formulario) y basta olvidar uno para que el campo vuelva.

`Catalog` gana `con_local: tuple[str, ...] = ()`: los nombres de las parejas cuyo texto
aún traía `local`. Solo lo usa el plan de la subida (§2) para avisar de que esa subida
lo quita.

### 2. Validar el catálogo sin `local`

`model.parse_config(data, equipo=False, catalogo=False)`: con `catalogo=True` cada pareja
se valida con un `local` de muestra (`model.LOCAL_DE_PLANTILLA`, una carpeta corriente),
sea cual sea el que traiga. Las reglas que dependen de la carpeta (la raíz entera, lo que
no cabe en un equipo) se aplican al meter la pareja en el dispositivo, que parsea su
config con la carpeta de verdad.

Lo llaman con `catalogo=True`: `catalog_editor` (alta, baja y `[defaults]` del
catálogo), `install/remote.parse_catalog()` y `config_file.dumps_checked(…,
catalogo=True)`, que es lo que `push()` usa.

`catalog.diff_keys()` deja de comparar las claves que son de cada dispositivo
(`catalog.DEL_DISPOSITIVO = ("local",)`): no puede haber diferencia en algo que el
catálogo no tiene, así que elegir carpeta no marca la pareja como «modificada aquí». Vale
igual para los `[defaults]`, que no tienen `local`.

`catalog_editor.plan_catalog_save()` avisa en `warnings`:
- si `cat.con_local` no está vacío (la primera subida desde una versión anterior): «Esta
  subida quita la carpeta local de N parejas del catálogo…», y que los dispositivos con
  una versión anterior siguen sincronizando, pero no podrán editar el catálogo ni usar
  parejas nuevas hasta actualizarse;
- en un alta: lo mismo de los dispositivos sin actualizar, que no podrán usarla.
`plan_catalog_remove()` y `plan_catalog_defaults()` dan el primer aviso igual.

El formulario del catálogo (la ventana de la pareja en la vista «Catálogo» y «Nueva
pareja…») ya no tiene «Ruta local»: `EditorPareja(con_local=False)`.
`pair_editor.validate(…, con_local=True)` deja de exigirla con `con_local=False`.

### 3. «Usar aquí» pide la carpeta

`pair_editor.plan_enable(raw, cat, name, local)`: `local` es la ruta ya relativa a la
raíz (`ruta_local_relativa()`). La entrada nueva es la del catálogo con ese `local`.

`tk_pairs.PantallaParejas.usar_aqui()` abre el diálogo de carpetas del sistema
(`filedialog.askdirectory`, `initialdir` = la raíz del dispositivo, `mustexist=False`
para que en Linux se pueda escribir una carpeta nueva; el de Windows tiene su «Nueva
carpeta»). Cancelar no hace nada y no toca `sync_config.toml`. Una carpeta de fuera del
dispositivo la rechaza `ruta_local_relativa()` (`messagebox.showerror`) y no se pide
plan. Con carpeta, el plan pasa por `plan_de()` y `confirmar_plan()` como hoy.

Lo que dice el plan (`consequences` / `warnings`), todo sin tocar nada:

- La carpeta elegida, y que se crea en la primera pasada si no existe. En un `up-mirror`
  no: sin carpeta la pasada aborta con 2 y no crea nada (#151).
- **`up-mirror` con la carpeta vacía o inexistente** (`warnings`): vacía, la primera pasada
  vaciaría el remoto; inexistente, abortará hasta que exista con lo que se quiere subir.
- **`down-mirror` con la carpeta con cosas** (`warnings`): la primera pasada borrará de ella
  lo que no esté en el remoto. El issue solo pedía «espejo con carpeta vacía»: ese es el
  peligro de `up-mirror`; el de `down-mirror` es el contrario.
- **Otra pareja ya usa esa carpeta, o una que la contiene o que está dentro**
  (`warnings`): nombra cuál. Dos parejas sobre los mismos ficheros se pisan los borrados.
- **Un `state/<pareja>/` que quedó de otra vez** (se quitó sin limpiar): si es bisync y el
  prefijo de su baseline no es el que espera la pareja con la carpeta elegida
  (`bisync.pair_state()` frente a `expected_prefix()`), se aparta
  (`EditPlan.shelve`, `state/<pareja>.old-<fecha>/`) y lo dice; la pareja pedirá su
  `--resync` explícito, como cualquier pareja nueva. Si el prefijo coincide (la misma
  carpeta que antes) se reutiliza, que es lo que pasa hoy. Nunca se renombra.
- bisync: la primera pasada pide un `--resync` (como hoy). El aviso del espejo (como hoy).

`plan_revert()` («Volver al catálogo») conserva el `local` del dispositivo: la entrada
vuelve a la del catálogo con la carpeta de aquí. `plan_override()` no cambia: con
`diff_keys()` sin `local`, cambiar la carpeta en el editor del dispositivo no la marca
«modificada aquí».

**Lo que se ve.** Una pareja que este dispositivo no usa, y cualquier fila de la vista
del catálogo, enseña solo el remoto (`CatalogRow.local` vacío; la celda dice el remoto sin
«↔»). La ventana de una pareja del dispositivo no pone «Catálogo: …» debajo de «Ruta
local». La ventana de una pareja sin usar (solo lectura) deja «Ruta local» vacía y dice
debajo «La eliges al usarla aquí.».

### 4. El instalador pregunta la carpeta

- **Asistente del dispositivo** (`tk_install._paso_parejas`): cada pareja lleva, además de
  su casilla, una caja con su carpeta, rellena con el nombre de la pareja
  (`deploy.carpeta_sugerida()`), editable. «Guardar el config y crear las carpetas»
  comprueba cada carpeta de las marcadas con `deploy.problema_carpeta()`
  (`model.problema_local()`, con `equipo` según la raíz) y se niega diciendo cuáles; con
  todas bien, pasa `locales` a `write_device_config()` y `make_local_dirs()`.
- **Asistente «En este equipo»** (`tk_equipo`): igual que hoy, pero la caja se rellena con
  `deploy.carpeta_sugerida()` en vez del `local` del catálogo, que ya no hay.
- **`deploy.device_config()`** exige una carpeta para cada pareja elegida (`InstallError`
  si falta alguna) y ya no copia ninguna del catálogo; `local_dirs()` lo mismo.
  `InstallState.locales` guarda las elegidas (los dos asistentes la rellenan al guardar),
  y `deploy.summary(catalog, selected, locales)` (el paso «Inicializar») enseña la
  carpeta elegida de cada pareja.

### 5. Lo que no cambia

- `sync.py`, el servicio, el agente, `bisync.expected_prefix()`, los frenos: el
  `sync_config.toml` de cada dispositivo sigue siendo completo.
- Los dispositivos ya instalados: su `sync_config.toml` no se toca y, con `diff_keys()`
  sin `local`, sus parejas no salen «modificada aquí».
- El llavero (`[keychain]`): su pareja la construye el código con su `local` fijo.

## Pruebas

Sin ventanas salvo donde ya las hay (las de Tk corren en la CI):

- `tests/test_catalog.py`: un catálogo sin `local` se lee, se escribe y se relee con
  round-trip estricto; uno antiguo con `local` se lee sin él, `con_local` lo dice y el
  `push()` lo sube sin él; `diff_keys()` no cuenta `local`; `cached()` también lo quita.
- `tests/test_model*.py`: `parse_config(catalogo=True)` valida parejas sin `local` y
  `parse_config()` normal sigue exigiéndolo.
- `tests/test_pair_editor*.py` / `test_catalog_editor*.py`: `plan_enable` con carpeta
  elegida, con baseline sobrante de otro prefijo (aparta) y del mismo (no aparta), los
  avisos de `up-mirror` vacía/inexistente, `down-mirror` con cosas y carpeta compartida
  o anidada; `plan_revert` conserva la carpeta; `plan_catalog_save` sin «Ruta local» y su
  aviso de transición; filas sin usar con solo el remoto.
- `tests/test_install_config.py` / `test_install_deploy.py`: `device_config()` exige
  carpeta por pareja y la usa; `problema_carpeta()`.
- Las de Tk que ya cubren la pantalla de parejas y los asistentes: «Usar aquí» con el
  diálogo sustituido (elegida, cancelada, fuera del dispositivo) y las cajas del asistente.

## Documentación

`docs/agents/reference/catalogue.md` (esquema, `sin_local`, `diff_keys`, `plan_enable`),
`provisioning.md` (el paso de las parejas), `host-root.md` (la caja rellena con el
nombre), `sync_config.example.toml` (el esquema de `remote.toml` sin `local`), y
`docs/guia/uso.md` y `docs/guia/como-funciona.md` donde el usuario ve «Usar aquí» y el
catálogo.
