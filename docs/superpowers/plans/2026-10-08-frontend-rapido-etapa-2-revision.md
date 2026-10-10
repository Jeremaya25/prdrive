# Adversarial review of `plan-etapa-2.md` against the code (tip `8cdfce6`)

Scope: every factual claim in the plan was checked against the tree; the 0.7.1 tree used by the
timing check is `$SCRATCH/mainsrc` (VERSION 0.7.1). Stage 1b's in-flight copy
(`$SCRATCH/e1b/superficie/repo`) was looked at only to confirm which files it touches
(`ui/theme.py`, `tests/test_controles.py`, `ui.md`, `service.md`, `commands-testing.md`,
`.github/workflows/tests.yml`; not `tk.py`/`tk_pairs.py`).

Claims verified as true (no action): `Sondeo._encargo`/`_mirar` (tk.py:1376-1448), `Panel`
(tk.py:1049), `pair_status_notes` (ui/__init__.py:124, imported into `ui.tk`), `linea_llavero`
(tk.py:1574), `orden_sync`/`preguntar_resync` (tk.py:93/107, also in 0.7.1), `leer_estado`/`render`
(nested in `main_window`), `Visor.encajar`/`crecer`, `centrar`, `manual_args`, `tk_repair.repintar`
(nested), `revision.revisar`/`_espacio`, `vestibulo.sin_sitio_fuera`, `cifrado.expulsion`,
`watch.boton_servicio`, `prefs.guardar_parejas`, `catalog.run`, `watch.consulta`,
`store.matar_arbol`, `components.pendientes(fisica=_BUSCAR)` (already exists), 1a fixes
(`PASO_BARRA_MS`, `que_cargar`, `conservar_lo_escrito`, `poner_alrededor`) committed, driver hooks
`dlg.sondeo/lista/editor/indicador` (tk_pairs.py:644/658), `dlg.panel`/`dlg.resultados` (tk_doctor),
`ttk::progressbar` running state observable on both Tks (`::ttk::progressbar::Timers` + `after info`,
checked on 8.6.14 and 9.0.4), `winfo_manager()==""` after `grid_remove` (checked), icons cached per
interpreter (`icons._CACHE`, so image names are stable for `leer_vista`), no `wait_variable` anywhere
in either tree (Task 13's driver patch is safe for 0.7.1).

---

## BLOCKERS

### B1. Task 7 — `catalog.run` in its own session lets `sync.py`'s rclone escape the pass cut
- Code: `sync.py:931` calls `fleet.publicar(config)` after every non-dry-run pass →
  `common/fleet.py:683` `catalog.run(["copyto", tmp, destino])`. Today that rclone inherits
  `sync.py`'s process group (output_window starts `sync.py` with `start_new_session=True`,
  tk.py:2757-2772) and `store.matar_arbol()` (store.py:465-491) kills it with `os.killpg`.
- Wrong: Task 7 makes every `catalog.run` child `start_new_session=True` (POSIX) /
  `CREATE_NEW_PROCESS_GROUP` (Windows). On POSIX `killpg(sync_pid)` no longer reaches the
  fleet-note rclone: closing the pass window (or the agent cutting a pass on eject) leaves an orphan
  rclone with `cwd = model.APP_DIR` **on the device**, holding the volume for up to `TIMEOUT` (90 s).
  That is exactly what `matar_arbol` exists to prevent ("Matar solo a sync.py dejaría vivo a su
  rclone, con ficheros del volumen abiertos"). Same for the agent/service processes that call
  `catalog.run`. On Windows the new group also stops Ctrl+C reaching it in a console `sync.py`.
- Fix (plan text, Task 7 Interfaces): "`catalog.run(args)`: same process creation as today (no new
  session, no new process group: a child of `sync.py` must stay in the pass's group so
  `matar_arbol` still reaches it). It keeps the `Popen` while it runs; `store.matar_hijos()` kills
  each noted child directly (`Popen.kill()`; rclone has no children of its own)." Add a test: a
  `sync.py`-like parent started with `start_new_session=True` that calls `catalog.run` with a
  sleeping fake binary; `matar_arbol(parent)` kills the grandchild (extend `test_matar_arbol.py`).

### B2. Task 5 ↔ Task 11 — `ui/principal.py`'s imports make Task 11 Step 5 impossible
- Code: `ui/watch.py:26` imports `common.fleet` at top; `common/fleet.py:47` imports
  `catalog, components, results, update` at top (verified: `import ui.watch` loads
  `common.components` and `common.catalog`). `ui/llavero_editor.py:24` imports `catalog, cifrada,
  conflicts, keepassxc, llavero` at top. `main_window` imports `watch` in its header (tk.py:1606).
- Wrong: Task 5's interface needs `watch.INICIAR`, `watch.boton_servicio/linea/pausa` and
  `llavero_editor.ABRIR`; a builder will import them at the top of `principal.py`. Task 11 imports
  `principal` before the first paint, so `common.components` and `common.conflicts` are loaded
  before `update_idletasks()` and Task 11 Step 5 fails — and Task 11 does not own `ui/principal.py`
  (merged in Wave 1), so it cannot fix it.
- Fix: Task 5 Interfaces: "`ui/principal.py` imports only stdlib and `ui.prefs` at module level.
  `watch` and `llavero_editor` are imported inside `estado()` only when `inst is not None`.
  `principal.INICIAR = "iniciar"` (duplicated on purpose; a test ties it to `watch.INICIAR`).
  New case in `tests/test_principal.py`: `import ui.principal` in a fresh interpreter loads none of
  `common.components`, `common.conflicts`, `common.revision`, `common.fleet`, `penwatch`." Same rule
  for `ui/tk_principal.py` in Task 11, and Task 11 removes `components, conflicts, revision` and
  `watch` from `main_window`'s header (tk.py:1604-1606).

### B3. Task 11 — `tests/test_start.py` breaks and is not in Task 11's files
- Code: `tests/test_start.py:34-41` replaces `Tk.mainloop` with a function that walks the window and
  invokes «Iniciar servicio» immediately, with no `update_idletasks()` and the real
  `segundo_plano.lanzar`.
- Wrong: Task 5's table disables «Iniciar servicio» while `cargando`; `invoke()` on a disabled
  `ttk.Button` does nothing → `choice is None` → "con entorno gráfico: elección" fails. Under the
  protocol the Task 11 builder may not edit it.
- Fix: add `tests/test_start.py` to Task 11's Modify list, with "its fake mainloop sets
  `segundo_plano.lanzar = segundo_plano.en_el_acto` and calls `self.update_idletasks()` first".

---

## MAJOR

### M1. Task 3 — `Instantanea.vigente()` is false in practice, so the shared read is never shared
- Code: `runsync.tomar_ui()` creates `state/ui.lock.json` right before the window
  (runsync.py:391, `UI_LOCK = model.ui_lock()` = `STATE_DIR/ui.lock.json`); `ui_prefs.json` lives
  in `state/` (prefs.py:38) and every flush is a tmp+rename there; `servicio.pide`
  (watch.py:520-527) and the catalogue cache are also written in `state/`.
- Wrong: the rule "`model.STATE_DIR` … `mtime + HOLGURA_MTIME <= hecha`" fails for the first read
  of every session (the lock was created < 2 s before `hecha`), and any tick makes every later read
  stale until the next refresh. `Compartida.para()` returns `None` → Task 9's «Reparación» first
  paint and Task 10's `estados` always fall back to their own reads. Not unsafe, but the budget
  claims (Task 9 "«Reparación» −30…−80 ms", Task 10 "50 pairs −20…−100 ms", Task 3's budget line)
  are silently lost, and the tests only pass with a forged `hecha`.
- Fix (Task 3 Interfaces): replace the `STATE_DIR` + `hecha − HOLGURA` rule with a stat snapshot
  taken at the start of `leer()`: `huella: tuple` of `(path, st_mtime_ns, st_size)` (or `None` when
  missing) for `state/last_run.json`, `state/conflicts.json`, the catalogue-duplicate record read by
  `catalog.duplicado()`, `filters/`, and each bisync pair's workdir `state/<pair>/` (listings,
  `.lck`, a shelving rename all change it). `vigente(config)` = same `firma` and the same snapshot
  now (equality, no slack; on FAT32 a write in the same 2-s tick with the same size is missed, which
  is fine because every plan re-runs `revisar()`). Say explicitly that `ui.lock.json`,
  `ui_prefs.json`, `servicio.pide`, `daemon.stop` and `*.tmp` do not count. Step 2's key assertions
  become: touching `last_run.json` or a workdir → stale; writing `ui_prefs.json` or
  `ui.lock.json` → still vigente.

### M2. Task 11 — "a `try/finally` puts `en_curso` back" clears busy on success too
- Code: the pass keeps `en_curso` until `al_cerrar` (tk.py:2047-2068).
- Wrong: a literal `try: … finally: en_curso=False` re-enables «Sincronizar ahora», «Parejas…»,
  «Ajustes…» and «Expulsar» while the pass runs (breaks "desactivado ⇔ ocupado", Review Focus 5).
- Fix: "If anything in `continuar()` raises before `output_window()` returns, an `except
  BaseException:` puts `en_curso` back to `False`, `aplicar()`s and re-raises; on success
  `en_curso` stays until `al_cerrar`." Also: check `selected()` is non-empty in the click, before
  turning busy.

### M3. Task 11 — standalone «Arranque automático» would never refresh the line
- Code: `tk_watch.open_dialog()` returns `None` always (tk_watch.py:57-60; standalone `construir`
  never calls `devolver`); today `abrir_arranque` always re-reads `watch.resumen()`
  (tk.py:1865-1887). `tests/test_tk_servicio.py:321-345` expects the line to change after it.
- Wrong: "call `aplicar()` only when what they returned says something changed" → after installing
  or uninstalling penwatch the auto-start line stays stale.
- Fix: "`abrir_arranque` (watcher dialog, not the agent one) always refreshes (`refrescar_instantanea()`
  or a direct `watch.resumen()` + `aplicar()`), because `tk_watch.open_dialog` returns nothing."

### M4. Task 9/11 — «Ajustes» opened before the read lands gets `vigilante=None` / no components
- Code: tk_doctor.py:360-368 `construir_arranque`: `if vigilante is not None and
  vigilante.es_agente:` else the penwatch screen; «Actualizaciones» (tk_doctor.py:308-316) shows the
  components pane only `if estado["componentes"]`.
- Wrong: Task 11 keeps «Ajustes…» enabled while loading (the driver clicks it right away). On an
  agent host the pane shows penwatch's screen with «Instalar…» (installing penwatch next to the
  agent, which the installer removes on purpose); with stale components «Actualizaciones» says
  "al día". Task 9 only subscribes chips and the components list, not the pane content.
- Fix (Task 9): "`construir_arranque` takes `vigilante` from `compartida.actual` when present, else
  from the parameter, else calls `watch.resumen()` itself (file reads only, as 0.7.1 did at first
  paint); never falls to the penwatch screen for lack of data. «Actualizaciones» built before the
  read lands shows an `Indicador` and is rebuilt when `compartida.poner()` fires (or falls back to
  `components.pendientes()`)." Task 11 passes `vigilante=vista.get("vigilante")` (may be `None`).

### M5. Task 10 — the hand-edit check is before the plan, not before the write
- Code: `aplicar()` (tk_pairs.py:979-1009) waits on `confirmar_plan()` (modal, minutes) and then
  `plan.execute()` writes `nuevo_raw` computed from the old `estado["raw"]`.
- Wrong: spec R1 says `load_raw`/`parse_config` "se vuelven a mirar antes de cada escritura". A
  hand edit made while the confirmation is open is still overwritten; Review Focus 4 claims it is
  not.
- Fix: "Local plans: `aplicar()` re-checks `LecturaConfig` right before `plan.execute()`; if the
  file changed, nothing is executed, the screen refreshes and the footer says so. Test: the
  `confirmar_plan` stub edits `sync_config.toml` and answers yes → no write, hand edit kept."

### M6. Task 4 — `probe()` ordering and the A/B bias of waiting for the shared read
- Code: driver.py:425-432 — `ESTADO["modulos"]`, `root.update()`, then `cancel_afters(root)`
  **before** `medir()`/`record("start-main")`.
- Wrong: (a) "after recording the first paint and before `cancel_afters`" contradicts the current
  order; if the wait is added after `cancel_afters` (as the code reads), the instantanea's `Sondeo`
  poll is cancelled, `instantanea_lista` never turns true, «Sincronizar ahora» stays disabled and
  `sincronizar-ventana` is "falta" → PR fails. (b) If instead the wait loop runs `root.update()`
  before `cancel_afters`, it also runs `precargar_a_ratos` (tk.py:1547, one import per `after(1)`)
  and possibly `mirar_version`/`mirar_conflictos` (`after(300)`) in the PR only, so «Parejas»/
  «Ajustes» open with their modules already imported in the PR and not in 0.7.1: every
  open-parejas/open-ajustes comparison is biased in the PR's favour.
- Fix: "Task 11 also sets `root.sondeo_instantanea` (the single `Sondeo` of the read). In
  `probe()`, keep `cancel_afters(root)` where it is; after `medir()`/`record`, if the root has
  `instantanea`, wait (sleep, no `update()`) until `root.instantanea.hecho` or 5 s, then time
  `root.sondeo_instantanea._mirar(); root.update()` as `llega-instantanea` (same pattern as
  `catalogo-llega`, driver.py:330-343)." `widgets.main` stays the first-paint count (deterministic).

### M7. Task 4 / Task 1 — the catalogue arrival lands inside reopen timings at random
- Code: driver.py `_parche_catalog` (load waits on an `Event`); `drive_parejas` clears it before the
  first click, `on_parejas` sets it and leaves it set.
- Wrong: `reabrir-parejas` (Task 4) and `abrir-2` / `reabrir-oculta` (Task 1, "catalog.load
  answering at once") reopen with the event set: the remote answers at once and the arrival repaint
  (1.2 s on 0.7.1 Windows, a full rebuild on B1) lands inside the measured window whenever ≥ 120 ms
  passed before `ensenar()`'s `update()` (Windows) or `_wait_window`'s `update()`. On B1 this inflates
  `abrir-2` and therefore Task 12's R7 `gain` (risk of adopting R7 on noise).
- Fix: Task 4 "before the second click `ESTADO["catalogo"].clear()`, release it after recording
  `reabrir-parejas` (its own handler: it records only `reabrir-parejas`, not `open-parejas`,
  `cold-parejas` or `catalogo-llega`)". Task 1: "`etapa2_reabrir.py` holds `catalog.load` on an
  `Event` during `abrir-1`, `abrir-2` and `reabrir-oculta` (and around `dlg.aplicar()`), released
  after each measurement".

### M8. Task 7 — killing every `catalog.run` child at close also cuts remote writes
- Code: `catalog.run` is used for writes too: `catalog.push` copyto (catalog.py:621-690), renames
  (`moveto`, catalog.py:820-880), `versions_editor.borrar_remoto` (`delete`, :74), fleet
  `copyto`/`deletefile`, `remote_picker` `mkdir`.
- Wrong: Task 11's root `<Destroy>` → `store.matar_hijos()` cuts any of these in flight (they run in
  `working()` but a window-manager close of the root can still arrive). The spec only asks for
  reads ("`rclone lsf`, `schtasks`").
- Fix: "`catalog.run(args, apuntar=…)`: only read-only verbs (`cat`, `lsjson`, `lsf`, `lsd`, `copy`
  to a local temp) are noted; writes are never killed by `matar_hijos()`."

### M9. Tests whose stubs break silently when signatures gain keywords
- Code: `tests/test_tk_principal.py:50` `components.pendientes = lambda: []`; :171/175/226
  `cifrado.expulsion = lambda: …`; `tests/test_tk_servicio.py:62,621,638` same;
  `tests/test_tk_reparacion.py:428,474` `tk_repair.open_dialog = lambda parent, config, lanzar,
  marcadas=None: …`; :566 `construir_falso(panel, config, lanzar, marcadas=None)`.
- Wrong: `instantanea.leer` calls `expulsion(fisica=…)`, `pendientes(fisica=…)`; Task 11 passes
  `compartida=` to `tk_repair.open_dialog`; Task 9's `tk_doctor` passes `compartida=` to
  `tk_repair.construir`. In the read, the `TypeError` is swallowed into `fallos` and the field keeps
  its default: «Expulsar» never appears, so some assertions fail and others pass vacuously.
- Fix: Task 11 lists those stub lines and says "stubs take `**_k`"; its `conducir`-style helpers
  assert `inst.fallos == {}` after arrival. Task 9 owns `construir_falso` (:566); Task 11 owns
  :428/:474. Task 3 Step 1 adds "happy path: `fallos` is empty".

---

## MINOR

1. **Task 3, sentinels and `device_id`.** `revision._espacio` → `vestibulo.sin_sitio_fuera`: if
   `revisar` forwards its own `_BUSCAR` object to vestibulo, `fisica / CONTENEDOR` raises inside
   `_espacio`'s `except` and the «espacio» finding vanishes silently. Fix: one sentinel
   (`vestibulo.BUSCAR`) reused by `revision` and `cifrado`, or forward only explicit values. Also
   "device_id … computed once, passed down" has no interface: `_espacio` (revision.py:307),
   `cifrado.expulsion` (cifrado.py:39), `cifrado.bloqueo` (:77), `watch.resumen`/`_agente`
   (watch.py:263,283) and `llavero_editor.linea` → `cifrada.estado()` (cifrada.py:77-85, a fourth
   `raiz_fisica`) call it themselves. Either add `device_id=` params or limit Step 1's "once"
   assertion to `raiz_fisica` and to a config without `[keychain]`.
2. **Task 3, the thread writes.** `revisar()` regenerates `filters/<pair>.txt` with a non-atomic
   `write_text` (bisync.py:225-226) while «Parejas» (opened before the read lands) runs `rows()` →
   same file on the Tk thread: a transient md5 mismatch can show «requiere resync». Say it in
   `ui.md`, or have `leer()` use a read-only variant.
3. **Task 5 depends on Task 3 in the same wave.** `principal.estado(inst=…)` reads Task 3's fields.
   Say: Task 5 reads `inst` by attribute only and its tests use `types.SimpleNamespace` with Task 3's
   field names; after merging 3 and 5, one case feeds `instantanea.vacia(config)`.
4. **Task 8, existing QR tests.** `tests/test_captura_pantalla.py:350-354, 387, 402` assert
   `["proteger", "mostrar"]` with the window withdrawn; with the code computed in a thread they fail
   unless the file sets `segundo_plano.lanzar = segundo_plano.en_el_acto`. Replace "the existing
   cases pass unchanged" with that, and update the module docstring (line 17) and `pairing-qr.md`:
   standalone, the window now shows before it is protected (no code is on screen yet).
5. **Task 8/9, panes that keep polling while hidden.** `tk_llavero.construir_ajustes` has
   `Sondeo(marco)` and `Indicador(marco)` (tk_llavero.py:176,180); `tk_renombrar` has
   `Indicador(marco)` (tk_renombrar.py:71). With kept panes they keep polling and animating at
   31 fps while hidden. Convert both to `panel.sondeo()`/`panel.indicador()` (add `ui/tk_llavero.py`
   to Task 8). `ui.md:83` ("switching pane cancels them") must change too.
6. **Task 8, «Versiones» purge consistency.** With async reads, `plan_purgar(estado["pareja"],
   estado["local"], estado["remoto"], …)` (tk_versions.py:189) could mix the selected pair with
   another pair's listing. Say: the task returns `(pair, local, remote)` together, the arrival stores
   the triple, «Purgar» uses it and stays disabled while a read for another pair is in flight.
7. **Task 8, indirection registry.** `tk_qr.preparar_codigo` (and `watch.estado_vigilante`) must go
   in `commands-testing.md`'s registry, which Task 8 does not own. Add it; and add
   `commands-testing.md` (Tasks 2, 3, 4, 7 in Wave 1) to the merge hot spots.
8. **Task 10, "size changed" guard.** `Visor.crecer()` needs `update_idletasks()` to know the
   requested size (`_natural`, tk.py:259-268); there is no cheap way to ask Tk first. State the guard
   as logical: `poner()`/`refrescar()` return whether rows were added/removed or a wrapping text
   changed, and only then `crecer()`/`centrar()` run (this is what Open risk 3 relies on).
9. **Task 10, which config the shared states are for.** Use `compartida.para(estado["config"])`
   after the first `LecturaConfig.leer()`, not the `config` parameter: a hand edit since the main
   window loaded would otherwise show another pair definition's baseline state. Also
   `rows(config, estados)` still calls `bisync.resync_reasons(pair, state)`, which re-reads filters
   (bisync.py:394): compute the aviso from the given `(PairState, FiltersState)` and assert neither
   `pair_state` nor `filters_state` is called for given pairs.
10. **Task 11, one `Sondeo` for every refresh.** Specify a single `Sondeo` per window (created once):
    `recargar()` while the first read is in flight starts a second read, and only the newest must be
    applied (`Sondeo.esperar` drops the older one only if it is the same `Sondeo`).
11. **Task 11 Step 1, differential with checkbox values.** `leer_vista()` includes the variable
    value, and "an existing row keeps its value" while a fresh view starts from the last
    `marcadas`: random sequences that change `marcadas` for an existing pair always mismatch. Keep
    each pair's `marcadas` membership fixed from its first appearance, or mask variable values in the
    differential and test the keep-value rule separately.
12. **Task 11, flush placement.** `seleccion.volcar()` before `output_window()` puts a device write
    between the click and the pass window (100 ms budget). `sync.py` never reads `ui_prefs.json`;
    flush right after `output_window()` returns (window shown, `arrancar` not yet run): still
    "before the pass". Consider flushing inside `lanzar()` so passes from «Reparación»/keychain also
    flush.
13. **Spec items without a home.** R2's `invalidar()` (Panel.terminar invalidates instead of
    rebuilding) is replaced by "rebuild visible pane, drop the others": say it is a deliberate
    deviation. R2's `al_mostrar()` "refresca lo suyo" has no user (no pane registers a refresh).
    R4's header chip "del mismo tamaño": the «…» pill is narrower than «al día»/«N que revisar»;
    reserve the chip column width (measured with `theme.fuente_tk`) or record the deviation.
14. **Flaky timing assertions.** Task 2 "two `_mirar` within 60 ms" → assert the scheduled delay
    (wrap `ventana.after` and check 20). Task 11 "1 after updating for 0.3 s" and Task 8 "after
    updating for 0.2 s" → loop until the condition, bounded at 2 s. Task 5 "a read-only PREFS returns
    `False`" → patch `store.write_json` to return `False` (chmod does nothing as root, which this
    sandbox is, and Linux `os.replace` ignores the file's own mode).
15. **Task 11, «Marcar todas» width.** Measuring text with `theme.fuente_tk()` misses the button's
    padding, border and focus ring; today's reservation is `winfo_reqwidth() + 10` (tk.py:2192-2198).
    Add the style padding (`ttk.Style.lookup("Quiet.TButton", "padding")`) and a test that the
    reserved `minsize` is ≥ the button's `winfo_reqwidth()` with each text.
16. **Task 4 `principal` flow.** Toggle a checkbox that leaves ≥ 1 pair ticked, else «Sincronizar
    ahora» does nothing (tk.py:2306-2308) and `sincronizar-ventana` is "falta"; and in 0.7.1
    `guardar_parejas` writes nothing for an empty selection (`escrituras.marcar` would read 0).
17. **Task 9, unsubscribe.** The `<Destroy>` binding on `dlg` fires for every child (rebuilt panes,
    the QR frame): check `evento.widget is dlg` before unsubscribing.

## NIT

- Task 8: the table in `segundo_plano` is `_EN_VUELO`, not `_vivos`.
- Task 5: `principal.Estado.servicio` is `(action, text)` but `watch.BotonServicio` is
  `(texto, accion)`; build it by name. The Step 1 enumeration lists `INICIAR, PAUSAR, REANUDAR`; add
  `SEGUIR` («Reanudar todo», watch.py:510-512).
- Global "What the timing driver finds": the driver does not use `dlg.panel`/`dlg.resultados`
  (tests do); harmless.
- Review Focus 5 says no state-touching control is enabled before the read lands, but «Parejas…»/
  «Ajustes…» are, by design (Task 5's table): reword.
- Task 11: `mirar_conflictos.responder` compares with `vista["conflictos"]`; define what it compares
  with while `inst is None` (skip, or treat as changed).
- Task 11 Step 1 "counter on `ttk.Widget.configure`" misses `config()`, `state()`, `grid*()`; also
  count those, or assert the widget set and `leer_vista()` are unchanged.
- `leer_vista()` ordering: cells share `(row, column)` in `ListaParejas` (`fondo` spans the row at
  column 0 with the checkbox); define the tie-break (stacking order from `winfo_children()`, which
  `lower()` changes, or `(class, text)`).
- Task 15 should also remove `rendimiento.yml`'s `# TEMPORAL` `push:` trigger ("quitar antes del
  PR").
- Task 12 Step 1: the GitHub MCP server failed to connect in this session; give `gh run list/view
  --log` as the fallback.
- Task 11: `importados_tarde()` (test_imports_perezosos.py:82-98) only scans `ui/tk.py`'s
  `main_window`; a `from . import instantanea` inside `refrescar_instantanea` must go in `PRECARGA`,
  and late imports inside `tk_principal.py` are not checked at all.

## Budgets and coverage

- R1–R7 for stage 2 are all covered by some task. With M1 unfixed, the R4 "share the read" savings
  for «Reparación» and «Parejas» (50 pairs) do not happen. The plan already marks the launch budget
  and «Parejas» first open as not reached.
- The other in-app targets look plausible given the code (2-row restyle, diff with no widget churn,
  no rebuild when coming back), provided M6/M7 are fixed so the measurements are fair.
