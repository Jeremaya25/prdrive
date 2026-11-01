# El catálogo sin carpeta local — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** que el catálogo (`remote.toml`) deje de llevar `local` y que cada dispositivo elija su carpeta al meter una pareja («Usar aquí» y los dos asistentes del instalador).

**Architecture:** `local` se quita en el único sitio donde se lee el catálogo (`catalog.sin_local()`, en los dos lectores) y en `push()`; el catálogo se valida con `model.parse_config(…, catalogo=True)`, que pone una carpeta de muestra. `plan_enable()` recibe la carpeta y avisa (espejos, carpeta compartida, baseline sobrante). El instalador pide una carpeta por pareja.

**Tech Stack:** Python 3.11+ stdlib, Tk 9; tests como scripts (`tests/_harness.Checks`, `sandbox()`).

**Spec:** `docs/superpowers/specs/2026-11-01-catalogo-sin-local-design.md`

## Global Constraints

- Comentarios, docstrings y textos de usuario en español; `docs/agents/` en inglés.
- `import tkinter` solo dentro de funciones; `tk_*` solo dibuja, las decisiones van en `pair_editor`/`catalog_editor`/`install/`.
- Nada que borre o reescriba datos sin `EditPlan` + `confirmar_plan()`; un baseline cuyo prefijo cambia se **aparta** (`state/<p>.old-<fecha>/`), nunca se renombra.
- `config_file.dumps_checked()` mantiene el round-trip estricto (`releido == raw`).
- `sync_config.toml` sigue llevando entradas completas, con `local`.
- Verificación mientras se trabaja: `python tests/run_all.py --cambios -j auto`; un test suelto: `python tests/test_X.py`. Sin pasada final completa (la hace la CI).

## Review Focus

- La copia local `state/catalog.toml` de un catálogo antiguo: `cached()` también quita `local` (test en Task 2).
- El paso del llavero del instalador sube `{**tomllib.loads(texto), "keychain": …}` con el `local` antiguo: `push()` lo quita y el round-trip pasa (test en Task 2).
- Volver a usar una pareja quitada sin limpiar, eligiendo la MISMA carpeta: el baseline se reutiliza, no se aparta (test en Task 4).
- Carpeta compartida comparada sin mayúsculas ni barras finales/`\` (`Fotos\` contra `fotos/2024` avisa: Windows y exFAT no distinguen mayúsculas) (test en Task 4).
- Una caja del asistente vacía o con `../x`: se niega diciendo qué pareja (test en Task 5).

---

### Task 1: Validar un catálogo sin `local`

**Files:**
- Modify: `common/model.py` (`parse_config`, junto a `DEFAULT_*`)
- Modify: `common/config_file.py` (`dumps_checked`)
- Test: `tests/test_parseo_seguro.py`, `tests/test_config_file.py`

**Interfaces:**
- Produces: `model.LOCAL_DE_PLANTILLA: str = "carpeta"`; `model.parse_config(data, equipo=False, catalogo=False) -> Config`; `config_file.dumps_checked(raw, head="", catalogo=False) -> str`.

- [ ] **Step 1: Tests**
  - `test_parseo_seguro.py`: «el catálogo sin local se valida»: `parse_config({"pair": [{"name": "a", "remote_path": "/a"}]}, catalogo=True)` no lanza; «y sin catalogo sigue exigiéndolo»: lo mismo sin `catalogo` lanza `ConfigError` con «falta 'local'»; «un local raro del catálogo no cuenta»: `{"name": "a", "local": "../x", "remote_path": "/a"}` con `catalogo=True` no lanza.
  - `test_config_file.py`: «dumps_checked del catálogo admite parejas sin local» con `catalogo=True` devuelve texto que `tomllib.loads()` iguala al dict.
- [ ] **Step 2:** `python tests/test_parseo_seguro.py` y `python tests/test_config_file.py` → fallan.
- [ ] **Step 3:** con `catalogo=True`, `parse_config` trabaja sobre una copia donde cada `[[pair]]` (que sea un `Mapping`) lleva `local = LOCAL_DE_PLANTILLA`, antes de `comprobar_seguridad()`. Docstring: las reglas que dependen de la carpeta se aplican al meter la pareja en el dispositivo. `dumps_checked` pasa `catalogo` a `parse_config`.
- [ ] **Step 4:** los dos tests pasan.
- [ ] **Step 5:** commit «El catálogo se valida sin carpeta local (#196)».

### Task 2: El catálogo se lee y se sube sin `local`

**Files:**
- Modify: `common/catalog.py` (`Catalog`, `_parse`, `cached`, `pull`, `push`, `diff_keys`)
- Test: `tests/test_catalog.py`

**Interfaces:**
- Consumes: `config_file.dumps_checked(…, catalogo=True)` (Task 1).
- Produces: `catalog.DEL_DISPOSITIVO = ("local",)`; `catalog.sin_local(raw: Mapping) -> dict` (copia profunda sin `local` en cada pareja); `catalog.con_local(raw: Mapping) -> tuple[str, ...]` (nombres de las parejas que lo traen); `Catalog.con_local: tuple[str, ...] = ()` (último campo, con valor por defecto); `diff_keys()` ignora `DEL_DISPOSITIVO`.

- [ ] **Step 1: Tests** (con un `TEXTO_VIEJO` cuyas parejas llevan `local`):
  - «un catálogo antiguo se lee sin local»: `pull()` con `responder(ok(TEXTO_VIEJO))` → ninguna pareja de `cat.raw` tiene `local`; «y dice cuáles lo traían»: `cat.con_local == ("notas",)` (o los que tenga); «el texto sigue siendo el del remoto»: `cat.text == TEXTO_VIEJO`.
  - «la copia local también»: tras ese `pull()`, `cached().raw` sin `local` y `cached().con_local` igual.
  - «push quita local al subir»: `push({**tomllib.loads(TEXTO_VIEJO)}, TEXTO_VIEJO)` → el texto subido (`copyto` de la llamada de subida, leído del temporal o de la copia local) no contiene `local =` y `tomllib.loads()` lo iguala a `sin_local(...)`.
  - «diff_keys no cuenta local»: `diff_keys({"local": "a", "mode": "up"}, {"mode": "up"}) == ()`, y `diff_keys({"local": "a", "mode": "up"}, {"mode": "bisync"}) == ("mode",)`.
  - Revisar los tests de `push()` existentes: un catálogo sin `local` sube y se relee igual.
- [ ] **Step 2:** `python tests/test_catalog.py` → falla.
- [ ] **Step 3:** `_parse()` devuelve `sin_local(tomllib.loads(text))`; `pull()` y `cached()` construyen `Catalog(..., con_local=con_local(crudo))` con el crudo sin quitar (en `cached()`, igual con `tomllib.loads`). `push()` hace `new_raw = sin_local(new_raw)` antes de `dumps_checked(new_raw, …, catalogo=True)`. Docstring de `sin_local`: por qué en la lectura y no en cada consumidor (spec §1).
- [ ] **Step 4:** pasa.
- [ ] **Step 5:** commit «El catálogo se lee y se sube sin carpeta local (#196)».

### Task 3: Editar el catálogo sin «Ruta local»

**Files:**
- Modify: `ui/catalog_editor.py` (`plan_catalog_save`, `plan_catalog_remove`, `plan_catalog_defaults`)
- Modify: `ui/pair_editor.py` (`validate`)
- Test: `tests/test_catalog_editor.py`

**Interfaces:**
- Consumes: `model.parse_config(…, catalogo=True)`, `Catalog.con_local` (Tasks 1–2).
- Produces: `pair_editor.validate(raw, edited, original_name, con_local=True) -> list[str]`; `catalog_editor.AVISO_SIN_ACTUALIZAR: str` y `catalog_editor.aviso_quita_local(n: int) -> str`.

- [ ] **Step 1: Tests**
  - «alta en el catálogo sin ruta local»: `plan_catalog_save(cat, {"name": "nueva", "remote_path": "/n", "mode": "up"})` no lanza; `plan.new_raw` sin `local` en `nueva`; `AVISO_SIN_ACTUALIZAR` en `plan.warnings`.
  - «la primera subida que quita local lo avisa»: con un `Catalog` cuyo `con_local == ("notas",)`, modificar `notas` → `aviso_quita_local(1)` en `warnings`; con `con_local == ()` no.
  - «baja y defaults también lo avisan» con `con_local` no vacío.
  - «el validador del dispositivo sigue exigiendo local»: `validate(raw, {...sin local...}, None)` trae «Falta la ruta local»; con `con_local=False` no.
- [ ] **Step 2:** `python tests/test_catalog_editor.py` → falla.
- [ ] **Step 3:** los tres planes llaman `model.parse_config(nuevo_raw, catalogo=True)` y añaden `aviso_quita_local(len(cat.con_local))` si `cat.con_local`; `plan_catalog_save` llama `validate(..., con_local=False)` y en un alta añade `AVISO_SIN_ACTUALIZAR`. Textos (exactos):
  - `AVISO_SIN_ACTUALIZAR = "Los dispositivos con una versión anterior de prdrive no podrán usar esta pareja hasta actualizarse: la carpeta la elige ahora cada dispositivo."`
  - `aviso_quita_local(n)`: `f"Esta subida quita la carpeta local de {n} pareja(s) del catálogo: ahora la elige cada dispositivo. Los que tengan una versión anterior de prdrive siguen sincronizando, pero no podrán editar el catálogo ni usar parejas nuevas hasta actualizarse."`
- [ ] **Step 4:** pasa; `python tests/test_pair_editor.py` sigue pasando.
- [ ] **Step 5:** commit «Editar el catálogo sin carpeta local (#196)».

### Task 4: «Usar aquí» con carpeta elegida

**Files:**
- Modify: `ui/pair_editor.py` (`plan_enable`, `plan_revert`, `_display`, `catalog_rows`, `catalog_only_rows`)
- Test: `tests/test_pair_editor.py`

**Interfaces:**
- Consumes: `catalog.sin_local`, `diff_keys` (Task 2).
- Produces: `pair_editor.plan_enable(raw, cat, name, local: str) -> EditPlan`; `pair_editor.solapadas(raw, local, salvo=None) -> list[str]` (parejas del dispositivo cuya carpeta es la misma, la contiene o está dentro; comparación con `/`, sin barras de los extremos y `casefold()`; `"."` contiene todo); `CatalogRow.local == ""` en las filas sin usar y en `catalog_only_rows`.

- [ ] **Step 1: Tests** (cambiar los de `plan_enable` existentes a la firma nueva; `cat` sin `local`):
  - «usar una del catálogo pone la carpeta elegida»: `plan_enable(raw, cat, "fotos", "Mis fotos").raw["pair"][-1] == {**find_pair(cat, "fotos"), "local": "Mis fotos"}`; tras `execute()`, `load_config()` la trae.
  - «up-mirror con la carpeta vacía avisa» (carpeta creada vacía) y «up-mirror sin carpeta avisa que aborta»: un aviso con «vaciaría el remoto» / «no existe»; «down-mirror con cosas avisa»: con un fichero dentro, aviso con «borrará»; «down-mirror vacía no avisa de eso».
  - «otra pareja con la misma carpeta avisa»: `local` = el de `notas` → aviso que nombra `notas`; «y una anidada también»: `"SYNC-DATA/notas/sub"` → avisa; «una carpeta al lado no»: `"sync-data/otra"` → sin ese aviso.
  - «baseline sobrante de otra carpeta se aparta»: dejar `state/fotos/` con listados de prefijo `"viejo"` → `plan.shelve == ["fotos"]`; tras `execute()` existe `state/fotos.old-*`. «de la misma carpeta se reutiliza»: listados con el `expected_prefix()` de la pareja con esa carpeta → `plan.shelve == []`.
  - «volver al catálogo conserva la carpeta»: `notas` con `local` y `remote_path` cambiados, catálogo sin `local` → `plan_revert(...).raw` tiene el `local` del dispositivo y el `remote_path` del catálogo.
  - «la fila sin usar no enseña carpeta»: `catalog_rows(...)["fotos"].local == ""`; `catalog_only_rows(...)` todas con `local == ""`. Ajustar los tests de filas que comparaban `local`.
- [ ] **Step 2:** `python tests/test_pair_editor.py` → falla.
- [ ] **Step 3:** `plan_enable`: entrada = `{**sin_local de la del catálogo, "local": local}`; `consequences`: la carpeta y si se crea en la primera pasada (no en `up-mirror`), el `--resync` de bisync; `warnings`: espejo (como hoy), espejos según `model.DEVICE_ROOT / local` (vacía / inexistente / con cosas), `solapadas()`; baseline: si `model.STATE_DIR / name` es un dir y la pareja es bisync, `bisync.pair_state(pareja)` con la `Pair` parseada del `nuevo_raw`; si `state.prefix` existe y difiere de `bisync.expected_prefix(pareja)`, o el estado es `broken`, `plan.shelve = [name]` y una consecuencia como la de `_analizar_pareja`. Textos de aviso (exactos):
  - up-mirror vacía: `f"La carpeta '{local}' está vacía y '{name}' es un espejo de subida: la primera pasada vaciaría el remoto. Pon antes lo que quieras subir."`
  - up-mirror inexistente: `f"La carpeta '{local}' no existe y '{name}' es un espejo de subida: la pasada no la crea y abortará hasta que exista con lo que quieras subir."`
  - down-mirror con cosas: `f"La carpeta '{local}' tiene cosas y '{name}' es un espejo de bajada: la primera pasada borrará de ella lo que no esté en el remoto."`
  - solapada: `f"La carpeta '{local}' ya la usa {', '.join(otras)} (la misma, o una dentro de la otra): dos parejas sobre los mismos ficheros se pisan los borrados."`
  - `plan_revert`: `nuevo = {**copy.deepcopy(entrada), "local": anterior["local"]}` y todo lo demás con `nuevo` en lugar de `entrada`.
  - `_display` devuelve `""` como local.
- [ ] **Step 4:** pasa.
- [ ] **Step 5:** commit «Usar aquí pide la carpeta de este dispositivo (#196)».

### Task 5: El instalador pide una carpeta por pareja (decisiones)

**Files:**
- Modify: `install/remote.py` (`parse_catalog`)
- Modify: `install/__init__.py` (`InstallState.locales`)
- Modify: `install/deploy.py` (`device_config`, `local_dirs`, `make_local_dirs`, `summary`, nuevas `carpeta_sugerida`, `problema_carpeta`)
- Test: `tests/test_install_config.py`, `tests/test_install_deploy.py`, `tests/test_install_catalogo.py`

**Interfaces:**
- Consumes: `catalog.sin_local`, `parse_config(catalogo=True)`.
- Produces: `InstallState.locales: dict[str, str]`; `deploy.carpeta_sugerida(pareja: Mapping) -> str` (el `name`); `deploy.problema_carpeta(local: str, equipo: bool = False) -> str | None` (vacío → `"Falta la carpeta."`, si no `model.problema_local(normalizado, equipo)`); `device_config(catalog, selected, catalog_path="", locales=None, equipo=False)` lanza `InstallError` nombrando las elegidas sin carpeta; `local_dirs`/`make_local_dirs` solo con `locales`; `summary(catalog, selected, locales=None)`.

- [ ] **Step 1: Tests**
  - `test_install_catalogo.py`: «el instalador lee un catálogo antiguo sin local»: `parse_catalog(TEXTO_VIEJO).pairs` sin `local`; «y uno nuevo sin local se valida».
  - `test_install_config.py`: «cada pareja lleva la carpeta elegida»: `device_config(cat, ["a"], locales={"a": "Docs"})["pair"][0]["local"] == "Docs"`; «sin carpeta se niega diciendo cuál»: `locales={}` → `InstallError` con `"a"` en el texto; ajustar los existentes que esperaban el `local` del catálogo.
  - `test_install_deploy.py`: `local_dirs(cat, ["a"], {"a": "Docs"}) == [Path("Docs")]`; `problema_carpeta("") == "Falta la carpeta."`, `problema_carpeta("../x")` no es `None`, `problema_carpeta("Docs") is None`; `carpeta_sugerida({"name": "fotos"}) == "fotos"`; `summary(cat, ["a"], {"a": "Docs"})[0][1]` empieza por `"Docs  <->  "`.
- [ ] **Step 2:** los tres fallan.
- [ ] **Step 3:** implementar según Interfaces; `parse_catalog` usa `sin_local(tomllib.loads(text))` y `parse_config(raw, catalogo=True)`.
- [ ] **Step 4:** pasan.
- [ ] **Step 5:** commit «El instalador pide la carpeta de cada pareja (#196)».

### Task 6: Las ventanas

**Files:**
- Modify: `ui/tk_pairs.py` (`EditorPareja(con_local=True)`, `_pista`, `VentanaPareja.que_cargar`, `formulario`, `ListaParejas.fila_tabla`, `examinar_local`, `PantallaParejas.usar_aqui`, nueva `elegir_carpeta`)
- Modify: `ui/tk_install.py` (`_paso_parejas`, `_paso_inicializar`)
- Modify: `ui/tk_equipo.py` (relleno de la caja, `wiz.state.locales`)
- Test: `tests/test_tk_screens.py`, `tests/test_tk_equipo_lecturas.py`, `tests/test_install_wizard.py` (los de Tk corren en la CI)

**Interfaces:**
- Consumes: `plan_enable(raw, cat, name, local)` (Task 4), `deploy.carpeta_sugerida`/`problema_carpeta`, `InstallState.locales` (Task 5).
- Produces: `tk_pairs.elegir_carpeta(parent, titulo: str) -> str` (envuelve `filedialog.askdirectory(parent=…, title=…, initialdir=str(model.DEVICE_ROOT), mustexist=False)`; `""` si se cancela); punto de indirección para los tests.

- [ ] **Step 1: Tests (Tk)**
  - `test_tk_screens.py` «Usar aquí»: con `tk_pairs.elegir_carpeta = lambda *a, **k: str(model.DEVICE_ROOT / "Mis fotos")` la pareja queda con `local == "Mis fotos"`; «cancelar no toca nada»: `lambda *a, **k: ""` → `cambiado` False y el config igual; «fuera del dispositivo se rechaza»: una ruta de `tempfile` fuera de `DEVICE_ROOT` con `messagebox.showerror` sustituido → se llama y no cambia nada.
  - `test_tk_screens.py`: la ventana del catálogo no tiene `editor.entradas["local"]`; la fila «fotos» sin usar: `leer()` enseña solo el remoto.
  - `test_install_wizard.py` / `test_tk_equipo_lecturas.py`: la caja de cada pareja sale rellena con su nombre; con una caja vacía «Guardar» no escribe y dice la pareja.
- [ ] **Step 2:** `python tests/test_tk_screens.py` (con display) → falla; si no hay display, se salta: queda para la CI.
- [ ] **Step 3:**
  - `EditorPareja(con_local=False)` no crea «Ruta local» (ni su «Examinar…»; `cargar()` y `datos()` lo toleran). `VentanaPareja` lo pasa con `del_catalogo`; `formulario()` del catálogo, igual.
  - `_pista("local", …)` sin «Catálogo: …»; una pareja sin usar (solo lectura) pone «La eliges al usarla aquí.» en la pista de «Ruta local».
  - `fila_tabla`: `f"{fila.local} ↔ {fila.remote}" if fila.local else fila.remote`.
  - `usar_aqui()`: `elegida = elegir_carpeta(self.delante(), f"Carpeta de '{fila.name}' en este dispositivo")`; vacía → nada; `ruta_local_relativa()` con `ConfigError` → `showerror`; si no, `plan_de(pair_editor.plan_enable, self.raw, self.cat, fila.name, local, titulo=…)`. `examinar_local()` usa también `elegir_carpeta`.
  - `_paso_parejas`: tercera columna con un `ttk.Entry` (`Mono.TEntry`) por pareja, `StringVar` con `wiz.state.locales.get(nombre) or deploy.carpeta_sugerida(pareja)`; la etiqueta de la fila enseña `↔ remote_path`; `guardar()` reúne `{n: caja}` de las marcadas, niega con `"Falta o no vale la carpeta de: " + ", ".join(malas)` si `problema_carpeta()` dice algo, y si no, pasa `locales` a `write_device_config()`/`make_local_dirs()` y guarda `wiz.state.locales`.
  - `_paso_inicializar`: `deploy.summary(wiz.catalog, wiz.state.selected, wiz.state.locales)`.
  - `tk_equipo`: relleno `wiz.equipo_locales.get(nombre) or deploy.carpeta_sugerida(pareja)`; al guardar, `wiz.state.locales = locales`.
- [ ] **Step 4:** `python tests/run_all.py --cambios -j auto` pasa (lo que no abre ventanas).
- [ ] **Step 5:** commit «Las ventanas piden la carpeta de cada pareja (#196)».

### Task 7: Documentación

**Files:**
- Modify: `docs/agents/reference/catalogue.md`, `provisioning.md`, `host-root.md`, `commands-testing.md` (registro: `tk_pairs.elegir_carpeta`)
- Modify: `sync_config.example.toml` (el esquema de `remote.toml` sin `local`), `docs/guia/uso.md`, `docs/guia/como-funciona.md`

- [ ] **Step 1:** catalogue.md: el esquema del catálogo sin `local`, `sin_local()`/`con_local`, `DEL_DISPOSITIVO` en `diff_keys()`, `plan_enable` (carpeta, avisos, baseline sobrante), `plan_revert`, el formulario del catálogo, los dispositivos sin actualizar. provisioning.md y host-root.md: la caja por pareja. Guía: «Usar aquí» pide la carpeta; el catálogo ya no la lleva.
- [ ] **Step 2:** `python tests/test_reglas_claude.py` y `python tests/run_all.py --cambios -j auto` pasan.
- [ ] **Step 3:** commit «Documentación: el catálogo sin carpeta local (#196)».
