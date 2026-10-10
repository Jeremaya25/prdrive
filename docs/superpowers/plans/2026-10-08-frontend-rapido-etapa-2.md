# Frontend rápido, etapa 2 («La ventana abierta») — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Tasks of the same wave are built **in parallel**, each on its own scratch copy, and merged in the order the wave gives (see «Parallel build protocol»).

**Goal:** Once a window is open, every click answers at once: ticking a pair, choosing a row, the remote catalogue arriving, coming back from «Ajustes», «Sincronizar ahora». Nothing a click waits for touches the drive, a process or the network, and no screen is rebuilt to show one change. Same look, same screens, same behaviour.

**Architecture:** Three ideas, applied screen by screen:
- **Build once, change in place (R1).** Each screen keeps its widgets and a pure description of what it shows; a change is `aplicar(estado)` (configure, grid, grid_remove), never destroy-and-rebuild. The main window's decisions move to a module without Tk (`ui/principal.py`) so they are tested as a table; «Parejas» diffs its rows by name; «Ajustes» restyles two sidebar buttons and keeps the panes it built (R2).
- **Read after painting, once (R4).** `ui/instantanea.py` (no Tk) reads, in one pass on a daemon thread, everything the main window, «Parejas» and «Ajustes» used to read on the Tk thread; the main window paints first from the config, `ui_prefs.json`, `last_run.json` and saved copies, and shares the read with the other two (`instantanea.Compartida`). Slow pane reads (the volume, `schtasks`/`systemctl`, the remote's versions, the QR encoding) go to threads too.
- **Nothing between a click and its repaint (R6).** The tick's `ui_prefs.json` write is coalesced (~250 ms) and flushed before a pass, a service start and on close; «Sincronizar ahora» turns busy in place, shows the pass window and launches `sync.py` on the next turn.

R7 (hide instead of destroy) and R3 (one-canvas table for the «Parejas» list) are **decided by measurement on Windows**: an early task builds the measurement and runs it in a temporary CI job; a later task re-runs it on the merged branch and picks the branch of Task 13 and Task 14.

**Tech Stack:** Python 3.11+ stdlib only; tkinter (Tk 8.6 and Tk 9.0.4); plain-script tests (`tests/_harness.Checks`); GitHub Actions (`rendimiento.yml`, a temporary `medida-etapa2.yml`).

**Spec:** `docs/superpowers/specs/2026-10-08-frontend-rapido-design.md` (version 2): §2 R1, R2, R3, R4, R6, R7; «Qué se quiere» (both tables); «Etapas» 2; «Decisiones para revisar» 3 and 4.

**Inputs this plan was built from** (paths relative to the scratchpad `/tmp/claude-0/-home-user-prdrive/03b34008-f2da-52c1-8cde-5efd2782344d/scratchpad/`, `$SCRATCH` below):
- the screens audit `diseno/notas-pantallas.md` (raw data `diseno/pantallas/res/`);
- the table spike `diseno/notas-tabla.md`, code `diseno/tabla/` (`v_canvas.py`, `kit.py`, `tabla_canvas.py`, `bench.py`);
- the stage-1a Windows run (`ci1a/rend-113538635910.txt`, x64, 0.7.1 → 1a): main window 1346 → 911 ms; open «Parejas» 842 → 861 (5 pairs), 2126 → 2127 (50); catalogue arrival 1210 → 1212 (5), 6234 → 6297 (50); open «Ajustes» 232 → 250; panes Reparación 211, Nombre e icono 281, Configuración 162, Actualizaciones 29.

There are **no reference artifacts** for this stage: builders implement from the Interfaces and the test lists, which carry every decision.

**Base commit.** Wave 1 starts from the branch tip with stage 1a (and its review fixes) and stage 1b (SVG painter in `ui/icons.py`, state-bit surfaces in `ui/theme.py`) committed; the exact sha is given in each builder's message. Nothing in Waves 1–2 edits `ui/theme.py`, `ui/icons.py`, `tests/test_controles.py`, `tests/test_superficie.py` or `tests/test_iconos*.py`. Since 1b, a mapped rounded control keeps its style name and carries its surface in the state bits `user1`–`user3` (`ui.md`); `Sobre<RRGGBB>.` prefixes only remain on controls sitting on an accent or danger face.

**Read «Corrections after review» (end of this file) before your task: it overrides the task text wherever they differ.**

---

## Budget map (Windows x64, 5 pairs, 100 %; spec «Qué se quiere»)

Estimates assume stage 1b merged (SVG pieces: icon painting and `apply()` drop) and are what the review should hold each task to; Task 12 and Task 15 replace them with measurements.

| Moment | 0.7.1 / 1a | Target | Tasks | Expected after stage 2 |
|---|---|---|---|---|
| Tick or untick a pair in the main window | writes `ui_prefs.json` in the click | ≤ 16 ms, 0 writes in the click | 5, 11 | 2–6 ms, 0 writes |
| Choose another row in «Parejas» (highlight) | restyles every row (~4 configures × N) | ≤ 16 ms | 10 | 2–6 ms (5), 3–8 ms (50) |
| Choose another pair (editor loaded) | — | ≤ 40 ms | 10 | 10–30 ms |
| Catalogue arrives in «Parejas» | 1212 / 6297 ms | ≤ 30 ms (5) | 10 (+14) | 10–30 ms (5), 30–90 ms (50) |
| Back from «Ajustes»/«Reparación», nothing changed | full `render()` + `encajar` | ≤ 30 ms | 11 | 1–5 ms |
| «Sincronizar ahora» → pass window seen | `render()` + window | ≤ 100 ms | 6, 11 | 60–110 ms (Windows show floor 45–80 ms) |
| Open «Parejas» | 842 / 861 | ≤ 150 ms | 10 (+13, 14) | 250–400 ms first open; 70–130 ms reopened with R7 |
| Open «Ajustes» | 232 / 250 | ≤ 150 ms | 9 | 120–180 ms |
| Switch pane in «Ajustes» | 29–281 | ≤ 60 ms | 8, 9 | 30–80 ms first visit, 5–20 ms revisit |
| Main window from launch | 1346 / 911 | ≤ 350 ms | 3, 11 | 500–650 ms (1b −250; stage 2 −50…−150): **not reached** |
| «Parejas» with 50 pairs instead of 5 | +1266 ms | ≤ +50 ms | 14 | +40–100 ms with the canvas list; +200 ms with lean rows |

---

## Global Constraints

- **Python and dependencies:** stdlib only; Python ≥ 3.11 for all code (CI leg 1). Device runtime is python-build-standalone 3.14.8 with Tk 9.0.4 (CI leg 2).
- **Language:** comments, docstrings and user-visible text in Spanish; `docs/agents/` and this plan in English; follow `docs/agents/code-writing-conventions.md` (Google-style docstrings, variable docstrings for policy constants).
- **Tk rules:**
  - `import tkinter` only inside functions.
  - `tk_*` modules only draw; decisions live in modules without Tk (`ui/principal.py`, `ui/instantanea.py`, `ui/pair_editor.py`, `ui/repair.py`, `ui/watch.py`, `ui/prefs.py`) and are tested headless.
  - `theme.py`/`icons.py` own colours, fonts, glyphs and styles; distances go through `theme.medida()` (or `icons.px()` for what Tk cannot scale).
  - **No ttk style is created, configured or mapped after the first widget of an interpreter** (spec §1b): a new style goes inside `theme.apply()`.
  - **No `update_idletasks()` in the middle of building** (the one in `render()` that measures «Marcar todas» goes); those of `mostrar()`/`ensenar()`/`centrar()`/`proteger_de_capturas()` stay where they are.
- **Threads:** every new thread is `daemon`, never touches Tk (no `PhotoImage`, no `Font`, no widget), returns data, and receives a `functools.partial` of data, never a lambda among widgets (`ui.md`, «Waiting helpers»). Results come back through `tk.Sondeo` on the Tk thread.
- **Files owned by stage 1b are not edited in Waves 1–2:** `ui/theme.py`, `ui/icons.py`, `tests/test_controles.py`, `tests/test_iconos*.py`. Task 14 (after 1b merges) may add one public helper or one style inside `theme.apply()`, nothing else.
- **`penwatch.py` must not change one byte** (`git diff --stat -- penwatch.py` prints nothing): `penwatch.copia_al_dia()` compares its bytes.
- **`runsync.ui_flow()` keeps its order:** take `ui.lock.json`, stop the service, then open the window. No task edits `runsync.py`.
- **Names tests replace in `ui.tk` stay module-level names there and are looked up at call time** (no local aliases, no `from .tk import x` in the new `tk_principal.py` for them): `IS_WIN`, `pantalla_util`, `mostrar`, `_atributo_dwm`, `_afinidad_de_pantalla`, `aviso_fallo`, `root_oculto`, `precargar`, `output_window`, `LINEAS_VENTANA`, `preguntar_resync`, `pair_status_notes`, `abrir`, `orden_sync`. Each screen module keeps its own `mostrar` name (tests replace `tk_pairs.mostrar`, `tk_doctor.mostrar`…).
- **What the timing driver finds stays as it is** (`tests/rendimiento/driver.py`): the button texts «Parejas…», «Ajustes…», «Sincronizar ahora»; the sidebar labels «Reparación», «Nombre e icono», «Actualizaciones», «Configuración»; on «Parejas» `dlg.sondeo` (with `_encargo` and `_mirar()`), `dlg.lista` (always the visible list, with `elegir(name, avisar)` and `orden`), `dlg.editor`, `dlg.indicador`; on «Ajustes» `dlg.panel`, `dlg.resultados`. «Parejas…» and «Ajustes…» stay **enabled** while the shared read is loading (the driver clicks them right after the first paint).
- **Safety invariants unchanged:** everything that deletes or rewrites user data still returns an `EditPlan`/`RepairPlan` shown through `tk_pairs.confirmar_plan()`; nothing repairs itself; no `*-mirror` pass runs without `--dry-run` in any test.
- **Visual changes allowed, and only these:** while the shared read loads, the header chip is a neutral pill («…»), the per-pair chips are absent, and «Sincronizar ahora», «Iniciar servicio» (with that text) are disabled while the keychain line, the auto-start line, the «Reparación…» line, the components notice and «Expulsar»/«Bloquear» are hidden; when it lands the window grows (it is not re-centred, and moves up only if its bottom would leave `pantalla_util`). A pane whose read is slow paints its frame with an `Indicador` and fills in when the read lands. Everything else is pixel-for-pixel the 0.7.1 look.
- **Indirection points:** each new one is a module-level function tests replace, added to the registry in `docs/agents/reference/commands-testing.md`.
- **New modules** (`ui/instantanea.py`, `ui/principal.py`, `ui/tk_principal.py`, and `ui/tk_tabla.py` if Task 14 A runs) are listed in `.claude/rules/ui.md` `paths` by the task that creates them (`tests/test_reglas_claude.py` fails otherwise); `AGENTS.md`'s layout map is updated once, in Task 15.
- **Both legs, every task, before delivering:**
  - Tk 8.6: `xvfb-run -a -s "-screen 0 1920x1080x24" /usr/bin/python3.12 tests/run_all.py`
  - Tk 9: `xvfb-run -a -s "-screen 0 1920x1080x24" $SCRATCH/runtime-linux64/bin/python3 tests/run_all.py`
  - Known flake under CPU load: `test_avisos_carpeta.py` (inotify timing): re-run it alone before calling it a failure.
- **Commits:** on `claude/adoring-pascal-5j258r`, one per task, by whoever merges; Spanish message saying what changes for the user (each task gives one); footer lines as in recent commits. **No PR:** the owner opens it.

## Parallel build protocol

- **Each builder** works on its own copy: `mkdir -p DIR && git -C /home/user/prdrive archive <base> | tar -x -C DIR` with `DIR = $SCRATCH/e2/<task>/repo`, then `cd DIR && git init -q && git add -A && git commit -qm base` **before editing**; at the end `git diff > $SCRATCH/e2/<task>/cambio.patch` and a short `$SCRATCH/e2/<task>/informe.md` (what changed, test counts on both legs, widget/module counts it saw, anything it needed outside its files). A builder edits **only the files its task owns**; if another file must change, it says so in the report instead.
- **Waves and bases:**
  - **Wave 1** (base B1 = branch tip with the 1a review committed): Tasks 1–7, all independent. Merge order: 2, 3, 5, 6, 7, 4, 1. B2 = B1 + those merges.
  - **Wave 2** (base B2): Tasks 8–11, independent of each other (each only passes or receives `compartida`, which Task 2 already accepts). Merge order: 10, 11, 9, 8 — R1 and R6 land first, as the biggest Windows wins (the 1.2 s catalogue arrival, the in-click write, the full repaints); the R4 pane reads last.
  - **Wave 3** (base: Wave 2 merged **and stage 1b merged**): Task 12, then Tasks 13 and 14 in parallel (merge 14, then 13).
  - **Wave 4:** Task 15.
- **Known merge hot spots** (all additive; resolve by keeping both sides):
  - `ui/tk.py`: Task 2 (`Sondeo`, `Indicador`, `Panel`), Task 6 (`output_window`), Task 11 (`main_window`) — disjoint regions.
  - `.claude/rules/ui.md`: Tasks 3, 5, 11 (one path line each).
  - `tests/test_tk_screens.py`: Tasks 8 (pane cases), 9 (Ajustes cases), 10 (Parejas cases); each edits only its own sections and puts new assertions in its own new file.
  - `tests/test_tk_reparacion.py`: Task 11 (main-window sections), Task 9 (pane sections).
  - `ui/watch.py`: Task 7 (`consulta()`), Task 8 (`estado_vigilante()`).
  - `docs/agents/reference/ui.md`: Tasks 2, 3, 6, 7, 8, 9, 11, each in its own section.
  - `tests/rendimiento/presupuesto.toml`: Task 4 (new keys), stage 1b, Task 15 (ceilings).

## Review Focus

1. **A tick followed within 250 ms by closing the window, «Sincronizar ahora», «Iniciar servicio» or «Expulsar»:** `ui_prefs.json` holds the last selection. Test: Task 11, «el tic se vuelca al cerrar / al lanzar / al iniciar el servicio».
2. **The QR on screen, in «Ajustes» and alone:** protection is set before the image exists, the pane is never kept, leaving lifts it, and a code arriving after the pane was left creates nothing and protects nothing. Tests: Task 8 (`test_captura_pantalla.py` new cases), Task 9 («el QR nunca se guarda»).
3. **«Reparación» painted from a stale shared read:** a plan always re-runs `revisar()`; a finding that is gone says so and touches nothing; `execute()` re-checks its conditions. Test: Task 9, «un hallazgo que ya no está no hace nada».
4. **`sync_config.toml` edited by hand while «Parejas» is open, and typing while the catalogue arrives:** the hand edit is not overwritten; what is typed survives (stage 1a's tests still pass). Tests: Task 10, «una edición a mano entre dos guardados no se pierde»; `test_tk_segundo_plano.py`.
5. **«desactivado ⇔ ocupado»:** no control that touches `state/` is enabled during a pass or before the shared read lands, and a pass window that fails to launch or is closed before launching never leaves the main window busy. Tests: Task 5 (table), Task 6 (`test_tk_pasada.py`), Task 11 (differential + busy).
6. **Deterministic counts with a read thread:** `modulos.main` and `widgets.main.*` do not depend on thread timing. Test: Task 11, `test_imports_perezosos.py` new case; Task 4's driver reports one value per key.
7. **The window still opens after the service stops:** `runsync.py` untouched; `test_instancia_unica.py`, `test_auto.py`, `test_servicio_ritmo.py` pass unchanged.

---

## Wave 1 (base B1)

### Task 1: Measure R3 and R7 on Windows (temporary)

Decides what Tasks 13 and 14 do. Its first run (on B1) is an early read; Task 12 re-runs it on the merged branch for the decision.

**Files:**
- Create:
  - `tests/rendimiento/etapa2_medir.py` (entry point and report)
  - `tests/rendimiento/etapa2_tabla.py` (child: one list variant, one size)
  - `tests/rendimiento/etapa2_lienzo.py` (canvas list, ported from `$SCRATCH/diseno/tabla/v_canvas.py` + `kit.py`)
  - `tests/rendimiento/etapa2_ligera.py` (lean ttk list)
  - `tests/rendimiento/etapa2_reabrir.py` (child: rebuild vs hide-and-reshow, real tree)
  - `tests/rendimiento/etapa2_perfil.py` (child: cProfile of the slow in-app moments)
  - `.github/workflows/medida-etapa2.yml` (TEMPORAL)
  - `docs/superpowers/pruebas/2026-10-09-etapa-2-medidas.md` (results; Task 12 completes it)
- Modify: nothing else. (`.claude/rules/commands-testing.md` already covers `tests/rendimiento/*`.)

**Interfaces:**
- `python tests/rendimiento/etapa2_medir.py --arbol DIR --trabajo DIR [--python PY] [--rondas 7] [--solo tabla|reabrir|perfil]`:
  - builds sample devices with `tests/rendimiento/dispositivo.py` (5 and 50 pairs) from `--arbol`;
  - runs each child in a fresh process, `--rondas` times plus one discarded warm-up, alternating variants;
  - writes `resultados.json`, `resumen.md` (medians, min, widget counts, and the two decision lines below) and appends `resumen.md` to `$GITHUB_STEP_SUMMARY` when set; exit 0 even when a variant fails (the failure goes in the summary).
- **Table children** (`etapa2_tabla.py VARIANTE N`), with `VARIANTE` in `ref | ligera | lienzo` and `N` in 5, 10, 20, 50; each child imports `ui` before `tkinter`, `theme.nitidez()`, `Tk()`, `theme.apply(root)`, one warm-up Toplevel, then in a withdrawn Toplevel holding a `Card.TFrame`:
  - `ref`: the tree's own `tk_pairs.ListaParejas` with real `pair_editor.CatalogRow`s (5 bisync/up/down modes, one mirror, one «no se usa aquí», two with notes);
  - `ligera`: `ListaLigera` with the same API (`poner(filas, del_catalogo)`, `elegir(name, avisar)`, `fila()`, `filas`, `orden`, `elegida`): **5 widgets per row** (row background frame; one label with the checkbox image as `compound="left"` plus the name; the path label; the mode chip; the state chip) and **no separator widgets** (rows on an inner frame whose background is the line colour, 1 px apart; the script creates that one style itself right after `apply()`, which a measurement may do). Diffs by name; selecting restyles two rows. 4 widgets per row is only reachable by dropping a chip or the row highlight, which changes the look: the report says so;
  - `lienzo`: `ListaLienzo`, the same API on one `tk.Canvas` (items only, no embedded windows; pills with disc via SVG photos, so Tk 9 only: on Tk 8.6 the variant is skipped and the summary says so).
  - Measured moments (ms, `perf_counter`, each followed by `update()`): `construir` (create + `ensenar()` of the Toplevel); `elegir` (`elegir(otra, avisar=False)`); `refrescar` (`poner()` of the same names with a third of the chips changed); `reemplazar` (`poner()` of all-new names); plus `widgets` (recursive `winfo_children` count).
- **Reopen children** (`etapa2_reabrir.py VENTANA`, `VENTANA` in `parejas | ajustes | pasada`, sample device with 5 pairs), driving the real `runsync.py` main window like `driver.py` does (patched `Tk.mainloop`, `Misc.wait_window`, `common.catalog.load` answering at once, `common.update.check` offline, `ui.tk.orden_sync` → `[sys.executable, "-c", "pass"]`):
  - `abrir-1`: first open (cold); `abrir-2`: close (destroy) then open again (rebuild);
  - `reabrir-oculta`: a third open where the patched `wait_window` **withdraws and releases the grab instead of destroying**, then a reshow: `ui.tk.ensenar(dlg)`, `dlg.grab_set()`, `getattr(dlg, "aplicar", None)` called if the tree provides it (Tasks 9 and 10 add it), `dlg.update()`;
  - for `pasada`: `output_window("Prueba", [py, "-c", "pass"], parent=root, modal=False)` twice (rebuild) against withdraw + clearing the `Text` + `ensenar()` (reshow).
- **Profile child** (`etapa2_perfil.py`): with `cProfile`, the same flow as the driver's «Parejas» (open; catalogue arrival through `dlg.sondeo._mirar()`), then «Ajustes» → «Configuración» → «Reparación». Prints, per moment, the top 25 functions by `tottime` and the share of `tkapp.call`/`_tkinter` time. Goes in the artifact and, trimmed to the top 10, in the summary.
- **Decision lines** printed in `resumen.md` (Task 12 applies them):
  - R3: `lienzo` vs `ligera`, `construir` at 20 rows, median difference in ms (canvas adopted if ≥ 20 ms faster); and `ligera` vs `ref` at 20 rows (lean adopted if ≥ 10 ms faster).
  - R7, per window: `gain = 1 − reabrir-oculta / abrir-2` (adopted if ≥ 0.50).
- **`.github/workflows/medida-etapa2.yml`** (first line comment: `# TEMPORAL: lo borra la tarea 15 de la etapa 2`): `on: push` to `claude/adoring-pascal-5j258r` with `paths: ["tests/rendimiento/etapa2_*", ".github/workflows/medida-etapa2.yml", "ui/**"]`, plus `workflow_dispatch`; matrix `windows-latest`/`windows-x64` and `ubuntu-latest`/`linux-x64`; steps copied from `rendimiento.yml` (checkout, setup-python 3.11, 1920×1080 on Windows, xvfb + libxft2 on Linux, runtime cache and `python tests/_runtime_ci.py runtime …`), then `python tests/rendimiento/etapa2_medir.py --arbol . --trabajo "${{ runner.temp }}/e2" --python "$PRDRIVE_PYTHON" --rondas 7` (under `xvfb-run` on Linux) and `actions/upload-artifact` of `${{ runner.temp }}/e2/salida`.

- [ ] **Step 1: Port the canvas list.** Copy what `ListaLienzo` needs from `$SCRATCH/diseno/tabla/v_canvas.py` and `kit.py` (SVG pill and disc, glyph SVG, fonts per interpreter, hit-testing, two-row repaint on select): no `REPO` constant, no `/proc` (Windows), no `ttf.py` (measure text with `theme.fuente_tk(widget, rol)`).
- [ ] **Step 2: Local smoke run on both Tks.**
  - Run: `xvfb-run -a -s "-screen 0 1920x1080x24" $SCRATCH/runtime-linux64/bin/python3 tests/rendimiento/etapa2_medir.py --arbol . --trabajo $SCRATCH/e2/t1/trabajo --python $SCRATCH/runtime-linux64/bin/python3 --rondas 1`, and the same with `--python /usr/bin/python3.12 --solo tabla`.
  - Expected: exit 0; `resumen.md` has the three tables (tabla, reabrir, perfil) and both decision lines on Tk 9; on Tk 8.6 the `lienzo` rows say «saltado: sin SVG».
  - Expected widget counts per row: `ref` 7 (incl. separator), `ligera` 5, `lienzo` 0 (one canvas for the list).
- [ ] **Step 3: Parity of the three lists.** In the child, after `poner()`, assert the drawn texts are the same in the three variants (names, «local ↔ remoto», mode, chip text): `ref` and `ligera` by reading their labels, `lienzo` by its `leer()`. A mismatch fails the child (a faster list that shows something else decides nothing).
- [ ] **Step 4: Push and read the Windows run** (`medida-etapa2`, job `windows-x64`): the step summary and the artifact. Record in `docs/superpowers/pruebas/2026-10-09-etapa-2-medidas.md`, section «Primera lectura (B1)»: the medians per variant and N, reopen gains, and the profile's top lines for «Parejas» open and catalogue arrival (where the 1.2 s go).
- [ ] **Step 5:** Commit «Medida temporal en Windows: tabla sobre un lienzo frente a filas ligeras, y esconder ventanas frente a rehacerlas».

**Budget:** none directly; decides R3 (50-pairs budget) and R7 («Abrir Parejas» ≤ 150 ms).

### Task 2: Shared helpers — `Sondeo`/`Indicador` pause, the pane contract, `compartida`, the view reader

**Files:**
- Modify:
  - `ui/tk.py`: `Sondeo`, `Indicador`, `Panel` only.
  - `ui/tk_pairs.py`: `open_dialog` signature only.
  - `ui/tk_doctor.py`: `open_dialog` signature only.
  - `ui/tk_repair.py`: `open_dialog` and `construir` signatures only.
  - `docs/agents/reference/ui.md` («Waiting helpers»: `cada`, `pausar()`/`seguir()`; «Ajustes»: the pane contract), `docs/agents/reference/commands-testing.md` (harness: `tests/_vista.py`).
- Create: `tests/_vista.py`, `tests/test_tk_panel.py`, `tests/test_tk_vista.py`.

**Interfaces:**
- `class Sondeo(ventana, cada: int = SONDEO_MS)`: polls every `cada` ms.
  - `pausar() -> None`: cancels the pending `after` but keeps the `Encargo` and callback.
  - `seguir() -> None`: if an `Encargo` is kept, calls back at once if it is done, else polls again.
  - `esperando` is `True` while an `Encargo` is kept, paused or not.
  - `_encargo`, `_mirar()` keep their names and meaning (the timing driver uses them).
- `Indicador.pausar()` / `Indicador.seguir()`: stop / restart the bar animation while it is waiting; the sentence is untouched.
- `Panel` additions (no behaviour change for a standalone dialog):
  - `al_mostrar(funcion) -> None`, `al_ocultar(funcion) -> None`: register callbacks.
  - `sondeo() -> Sondeo`: a `Sondeo` hung off `self.marco`, registered so the panel pauses it.
  - `indicador(padre, ancho: int = 560) -> Indicador`: likewise.
  - `mostrado() -> None`: resumes its sondeos and indicators, then calls the `al_mostrar` callbacks. Called by whoever shows the pane again (Task 9), never on the first build.
  - `ocultado() -> None`: pauses its sondeos and indicators, then calls the `al_ocultar` callbacks.
- New keyword, accepted and ignored until Wave 2 (docstring: «la lectura compartida de la ventana principal (`ui.instantanea.Compartida`), o `None`»):
  - `tk_pairs.open_dialog(parent, config, compartida=None) -> bool`
  - `tk_doctor.open_dialog(..., marcadas=None, compartida=None) -> dict`
  - `tk_repair.open_dialog(parent, config, lanzar, marcadas=None, compartida=None) -> bool`
  - `tk_repair.construir(panel, config, lanzar, marcadas=None, compartida=None) -> None`
- `tests/_vista.py` (test helper, no assertions):
  - `ESTADOS_IGNORADOS = {"active", "focus", "hover", "pressed", "alternate", "background", "user1", "user2", "user3"}`.
  - `a_la_vista(widget) -> bool`: the widget and every ancestor below its toplevel have a geometry manager (`winfo_manager() != ""`). A `grid_remove`d widget, or the child of one, is not.
  - `visibles(raiz, clase=None, texto=None) -> list`: the widgets `a_la_vista` under `raiz`, depth-first, filtered by class and `cget("text")`.
  - `leer_vista(raiz) -> list[tuple]`: one tuple per visible widget, depth-first, children ordered by `(grid row, column)` for grid, packing order for pack, name for place: `(depth, winfo_class, text, style without a "Sobre<RRGGBB>." prefix, sorted state minus ESTADOS_IGNORADOS, image name, grid row/column/rowspan/columnspan/sticky, wraplength, value of the textvariable or variable)`. Widget names are not part of it.

- [ ] **Step 1: Pause and resume.**
  - Run: `xvfb-run -a /usr/bin/python3.12 tests/test_tk_panel.py` and the same with the runtime.
  - Key assertions: a paused `Sondeo` schedules nothing (`after info` lists none of its ids) and calls back once on `seguir()` when the `Encargo` finished meanwhile; `cada=20` polls at 20 ms (two `_mirar` within 60 ms with `update()`); a paused `Indicador` bar is stopped (`barra.instate` / Tcl `ttk::progressbar` not running) and restarts on `seguir()`; `Panel.ocultado()` pauses every `panel.sondeo()`/`panel.indicador()` and calls `al_ocultar` once; `mostrado()` reverses it; destroying `panel.marco` still cancels its sondeos (the existing `<Destroy>` rule).
- [ ] **Step 2: The reader.**
  - Run: `tests/test_tk_vista.py` on both legs.
  - Key assertions: a `grid_remove`d widget and the children of a `grid_remove`d frame are not `a_la_vista`; two frames built in different orders with the same final layout read equal; a different text, style, state or grid cell reads different; `user1`–`user3` and `active` do not count; a `SobreFFFFFF.Primary.TButton` reads as `Primary.TButton`.
- [ ] **Step 3:** The `compartida=None` keywords exist and nothing calls them yet: both legs pass unchanged.
- [ ] **Step 4:** Docs. Commit «Las pantallas pueden pausar lo que esperan mientras no se ven».

**Budget:** none directly; makes R2 and R4 (Tasks 8–11) possible.

### Task 3: `ui/instantanea.py` — one read per refresh, after painting

**Files:**
- Create: `ui/instantanea.py`, `tests/test_instantanea.py`.
- Modify:
  - `common/revision.py`: `revisar(config, *, fisica=_BUSCAR)`, passing it to `_espacio()`.
  - `common/vestibulo.py`: `sin_sitio_fuera(device_id, fisica=_BUSCAR)`.
  - `ui/cifrado.py`: `expulsion(fisica=_BUSCAR)`.
  - `tests/test_revision.py`, `tests/test_vestibulo.py` (one case each: a given `fisica` skips `raiz_fisica()`).
  - `.claude/rules/ui.md` (paths `ui/instantanea.py`, `tests/test_instantanea.py`).
  - `docs/agents/reference/ui.md` (new subsection «One read per refresh»), `docs/agents/reference/commands-testing.md` (registry: `instantanea.leer`).

**Interfaces:**
- **What it gathers** (from the audit: on Windows the main window's first paint read `pair_state` ×6, `filters_state` ×6, `raiz_fisica` ×3 — each a walk over the drive letters —, `conflicts.cargar` ×2, `device_id` ×3 and one process snapshot):

  | Field | Read by | Was read on the Tk thread by |
  |---|---|---|
  | `estados: Mapping[str, tuple[PairState, FiltersState]]` (bisync pairs) | «Parejas» rows | `pair_editor.rows()` at every `refrescar()` |
  | `notas: Mapping[str, str]` | main rows | `render()` → `pair_status_notes()` |
  | `hallazgos: tuple[Hallazgo, ...]`, `cuenta: int` | main chip and line; «Ajustes» chip; «Reparación» first paint | `leer_estado()`, `tk_repair.repintar()` |
  | `conflictos: Mapping[str, int]` | main rows | `leer_estado()` |
  | `componentes: tuple`, `componentes_texto: str \| None`, `componentes_actualizables: bool` | main notice; «Ajustes» chip and pane | `leer_estado()` |
  | `fisica: Path \| None` (once) | expulsion, `_espacio`, components | three `raiz_fisica()` |
  | `expulsion: Path \| None`, `bloqueo: str \| None`, `del_equipo: bool` | main footer | `leer_estado()` |
  | `vigilante: watch.Resumen` | main auto-start line and footer button; «Ajustes» «Arranque automático» | `leer_estado()` |
  | `llavero: llavero_editor.Linea \| None` (process snapshot) | main keychain line | `leer_estado()` |
  | `device_id: str \| None` | — (computed once, passed down) | three `fleet.device_id()` |
  | `fallos: Mapping[str, str]` | logs/tests | — |
  | `hecha: float` (`time.time()` at the start), `firma: tuple` | `vigente()` | — |

- `leer(config, *, notas=None, linea_llavero=None) -> Instantanea`: never raises (each field under its own `try`, default as `leer_estado()` used, the error's `repr` in `fallos`); imports what it needs inside; touches no Tk. `notas` defaults to `ui.pair_status_notes`, `linea_llavero` to the same rule as `ui.tk.linea_llavero` (the main window passes both from `ui.tk`'s namespace, so tests that replace `uitk.pair_status_notes` keep working). An indirection point.
- `vacia(config) -> Instantanea`: everything empty, `cuenta` 0 (what the main window keeps if the thread itself failed).
- `firma(config) -> tuple`: `tuple((p.name, p.mode.name, p.local_endpoint, p.remote_endpoint) for p in config.pairs)` plus whether `[keychain]` is set.
- `HOLGURA_MTIME = 2.0` (seconds; FAT32 stores even seconds).
- `Instantanea.vigente(config) -> bool`: same `firma`, and `model.STATE_DIR`, `results.ruta_estado()` (`state/last_run.json`) and `conflicts.ruta_estado()` (`state/conflicts.json`) all have `mtime + HOLGURA_MTIME <= hecha` (a missing file counts as old). Three `stat`s, no other read.
- `class Compartida` (Tk thread only): `actual: Instantanea | None`; `poner(inst) -> None` (stores and calls every subscriber with it); `suscribir(funcion) -> Callable[[], None]` (returns the unsubscribe); `para(config) -> Instantanea | None` (`actual` if it is `vigente(config)`, else `None`).

- [ ] **Step 1: One pass, nothing twice.**
  - Run: `python3 tests/test_instantanea.py` (headless).
  - Key assertions: with `vestibulo.raiz_fisica` and `fleet.device_id` replaced by counters, one `leer()` calls each **once**; every field comes from the replaced readers (`revision.revisar`, `conflicts.cargar`/`contar`, `components.pendientes`, `cifrado.expulsion`/`bloqueo`, `model.es_equipo`, `watch.resumen`, the passed `notas` and `linea_llavero`); a reader that raises leaves its default and a line in `fallos`, and the rest is still read; `"tkinter" not in sys.modules` after `leer()` in a fresh interpreter (subprocess).
- [ ] **Step 2: Freshness.**
  - Key assertions: `vigente()` is false for another config (pair added, mode changed), false when `state/last_run.json` is touched after `hecha - HOLGURA_MTIME`, true otherwise; `Compartida.para()` follows it; `suscribir()` calls back on `poner()` and not after the unsubscribe.
- [ ] **Step 3:** `python3 tests/test_revision.py` and `tests/test_vestibulo.py`: a given `fisica` (also `None`) is used as is and `raiz_fisica` is not called.
- [ ] **Step 4:** `python3 tests/test_reglas_claude.py`. Both legs. Docs. Commit «La ventana lee el estado del dispositivo una sola vez y sin hacer esperar».

**Budget:** main window from launch (−40…−150 ms on Windows once Task 11 moves the read after the first paint); «Parejas» open with 50 pairs (−20…−100 ms, Task 10); «Reparación» first paint (Task 9).

### Task 4: The timing check measures the open window

**Files:**
- Modify:
  - `tests/rendimiento/driver.py`
  - `tests/rendimiento/correr.py` (`PLAN`: `("principal", 5, "1.0")`, `("principal", 50, "1.0")`; `ESPERADOS["principal"] = ("marcar", "sincronizar-ventana")`)
  - `tests/rendimiento/informe.py` (`ETIQUETAS`; `cuentas()` learns `escrituras.marcar`)
  - `tests/rendimiento/presupuesto.toml` (`[meta_ms]` for the new moments; `[techo] "escrituras.marcar" = 1`; `[meta] "escrituras.marcar" = 0`)
  - `tests/test_rendimiento_informe.py`
  - `docs/agents/reference/commands-testing.md` («Timing check»)

**Interfaces:**
- **New patches** (in `PARCHES`, applied on import like the rest):
  - `common.store`: `write_json` counts calls whose path is under `BENCH_DEVICE` (`ESTADO["escrituras"]`).
  - `ui.tk`: `orden_sync` returns `[sys.executable, "-c", "pass"]` (no real pass ever runs in the check), and `preguntar_resync` returns `False` (a resync question would block the driver).
- **The shared read:** in `probe()`, after recording the first paint and **before** `cancel_afters(root)`, if the root has `instantanea_lista` (Task 11 sets it), loop `root.update()` + `time.sleep(0.001)` until it is true or 5 s pass, and record `llega-instantanea` (ms from the first paint). The base tree (0.7.1) has no such attribute: skip.
- **New moments** (all also produced by 0.7.1 unless noted; a moment only the PR has reads «nuevo», never a failure):
  - flow `parejas`, after `catalogo-llega`: `elegir-fila` (`dlg.lista.elegir(dlg.lista.orden[1], avisar=False)` + `dlg.update()`), `elegir-pareja` (the same with `avisar=True`, other row); then close «Parejas» and click «Parejas…» again: `reabrir-parejas` (button to shown, through the same `on_shown` hook).
  - flow `ajustes`, after the four panes: `pane-otra-vez` (click «Reparación» again); then `volver-ajustes` (from the moment the patched `wait_window` destroys «Ajustes» until the button's `invoke()` returns and `root.update()` ends).
  - flow `principal` (new): `llega-instantanea` (PR only); `marcar` (invoke the first visible `ttk.Checkbutton` of the root + `root.update()`), with count `escrituras.marcar` = writes during that click; then wait ≤ 5 s (updating) until «Sincronizar ahora» is enabled, invoke it and loop `update()` until a new `Toplevel` is viewable: `sincronizar-ventana`; then wait ≤ 10 s for its title to carry the verdict («— OK»), destroy it and time until `root.update()` ends: `volver-pasada`.
- **`[meta_ms]`** (spec, in-app table): `marcar` 16, `elegir-fila` 16, `elegir-pareja` 40, `volver-ajustes` 30, `volver-pasada` 30, `sincronizar-ventana` 100, `reabrir-parejas` 150, `pane-otra-vez` 60. `llega-instantanea` is reported without a target.

- [ ] **Step 1:** `python3 tests/test_rendimiento_informe.py`. Expected: all OK, with new cases: a moment present only in the PR reads «nuevo»; `escrituras.marcar` above its ceiling fails; the new labels are in `ETIQUETAS` order.
- [ ] **Step 2: Local A/B of B1 against itself.**
  - Run: `xvfb-run -a -s "-screen 0 1920x1080x24" python3 tests/rendimiento/correr.py --pr . --base . --trabajo $SCRATCH/e2/t4/rend --python $SCRATCH/runtime-linux64/bin/python3 --rondas 2`.
  - Expected: exit 0; every new moment has a value in both trees except `llega-instantanea`; `escrituras.marcar` = 1 in both; no `_notes` error.
- [ ] **Step 3:** Commit «La comprobación de tiempos mide también la ventana abierta: marcar, elegir, volver y sincronizar».

**Budget:** none; it is the yardstick for every in-app target. Expected Windows effect: about +2 minutes per `rendimiento` run.

### Task 5: The main window's decisions without Tk, and the coalesced tick

**Files:**
- Create: `ui/principal.py`, `tests/test_principal.py`.
- Modify: `ui/prefs.py` (+ `SeleccionPendiente`, `ESPERA_MS`), `tests/test_prefs.py`, `.claude/rules/ui.md` (paths `ui/principal.py`, `tests/test_principal.py`).

**Interfaces:**
- `principal.Fila(nombre: str, modo: str, cuando: str, chip: tuple[str, str] | None)`; `principal.Linea(texto: str, aviso: bool, boton: str, activo: bool)`.
- `principal.Estado` (frozen dataclass, hashable, compared by value):
  - `dispositivo: str`, `remotos: str` (the header's two short texts, `corto()` as today);
  - `chip: tuple[str, str, str | None]` (text, type, icon): `("sincronizando…", "Acento.", "sync")` when `en_curso`; `("…", "", None)` when `cargando`; `("N que revisar" | "1 que revisar", "Aviso.", "warn")` when `cuenta`; else `("al día", "Ok.", "ok")`;
  - `aviso: str | None`;
  - `reparacion: int` (the count; the line shows when > 0 and not `en_curso`);
  - `version: str | None` (the release block's text) and, only when there is none, `componentes: str | None` + `componentes_boton: bool`;
  - `filas: tuple[Fila, ...]` (chip: the note, else «N conflicto(s)», else `None`; no chips while `cargando`), `ultima: str` («última pasada …» or ""), `marcadas: frozenset[str]` (what a new row's checkbox starts with);
  - `llavero: Linea | None`, `arranque: Linea | None`, `pausa: str | None`;
  - `servicio: tuple[str, str]` (`watch.boton_servicio()`'s action and text; `(watch.INICIAR, "Iniciar servicio")` while `cargando`);
  - `pie: str | None` (`"bloquear"` with `bloqueo`; else `"expulsar"` with `expulsion`, or with the keychain on a device that is not a host folder; else `None`);
  - `en_curso: bool`, `cargando: bool`.
- `principal.estado(config, *, aviso, nueva, instalada, tiempos, marcadas, en_curso, inst, vigilante=None) -> Estado`: pure; `inst` is an `Instantanea` or `None` (`cargando`); `vigilante` overrides `inst.vigilante` (what the window asked the agent, `watch.pedido()`/`watch.tras_servicio()`, until the next read lands). The texts are today's `render()` texts, moved verbatim.
- `principal.Control(visible: bool, activo: bool)` and `principal.controles(e: Estado) -> dict[str, Control]`, the **«desactivado ⇔ ocupado» table**:

  | Key | visible | activo |
  |---|---|---|
  | `sincronizar` | always | `not en_curso and not cargando` |
  | `servicio` | always | action ≠ `INICIAR`: always; else `not en_curso and not cargando` |
  | `parejas`, `ajustes` | always | `not en_curso` |
  | `reparacion` | `reparacion > 0 and not en_curso` | always |
  | `llavero` | `llavero is not None` | `llavero.activo and not en_curso` |
  | `pie` | `pie is not None` | `not en_curso` |
  | `componentes` | `componentes is not None and componentes_boton` | `not en_curso` |
  | `version`, `descartar`, `arranque` | `version` / `aviso` / `arranque` is not `None` | always |
  | `marcar_todas` | `len(filas) > 1` | always |

- `prefs.ESPERA_MS = 250`.
- `prefs.SeleccionPendiente`: `poner(config, pares) -> None` (remembers the last selection, writes nothing); `pendiente -> bool`; `volcar() -> bool | None` (writes the last one with `guardar_parejas()` and forgets it; `None` when nothing was pending). Never raises (a drive that cannot be written returns `False`, as `guardar_parejas`).

- [ ] **Step 1: The table.**
  - Run: `python3 tests/test_principal.py` (headless).
  - Key assertions: for every combination of `en_curso`, `cargando`, keychain (none / can open / cannot open), footer (none / expulsar / bloquear), components (none / with button / without), service action (`INICIAR`, `PAUSAR`, `REANUDAR`) and 1 or 3 pairs, `controles()` equals the table above, written out row by row; no control that touches `state/` (`sincronizar`, `servicio` with `INICIAR`, `parejas`, `ajustes`, `llavero`, `pie`, `componentes`) is `activo` while `en_curso`.
- [ ] **Step 2: The texts.**
  - Key assertions: the header chip in its four cases; a pair with a note shows the note and not its conflicts; a release hides the components block; with the agent as the root's service `servicio` is «Pausar»/«Reanudar»/«Reanudar todo» from `watch.boton_servicio`; `cargando` gives no row chips, no keychain/auto-start lines and `("…", "", None)`; `ultima` uses the most recent time.
- [ ] **Step 3: The coalesced tick.**
  - Run: `python3 tests/test_prefs.py`.
  - Key assertions: three `poner()` then one `volcar()` writes once, with the last selection; `volcar()` with nothing pending returns `None` and does not touch the file; an empty selection is not written (as `guardar_parejas`); a read-only `PREFS` returns `False`.
- [ ] **Step 4:** `python3 tests/test_reglas_claude.py`; both legs. Commit «Lo que enseña y deja pulsar la ventana principal se decide en un sitio y se prueba como tabla».

**Budget:** «Marcar una pareja» ≤ 16 ms with 0 writes (with Task 11); the busy rule behind «Sincronizar ahora».

### Task 6: The pass window shows first and launches after

**Files:**
- Modify: `ui/tk.py` (`output_window` only), `tests/test_matar_arbol.py`, `tests/test_tk_salida.py` (only if a case needs the first turn), `docs/agents/reference/ui.md` («Main window and output»).
- Create: `tests/test_tk_pasada.py`.

**Interfaces:**
- `output_window(...)`: same signature and return. The window is built and shown (`centrar`, `ensenar`) **before** the process exists; `Popen` and the reader thread start in `root.after(1, arrancar)`.
  - `root.proceso`: the `Popen` once started (`None` before); tests read it.
  - Closed before `arrancar` runs: no process is started; `al_cerrar(1)` is called once; `cortar()` does nothing.
  - `Popen` raising `OSError`: the window says «No se ha podido lanzar: …» in the log, the chip and title show `ERROR (código 127)`, `state["rc"] = 127`, and `al_cerrar(127)` fires on close. Nothing else changes (`_Salida`, «Guardar el log», `veredictos`, the three cut points, `matar_arbol` once).
  - The modal path (`modal=True`) schedules `arrancar` before `esperar()`.

- [ ] **Step 1: Order and failure.**
  - Run: `xvfb-run -a /usr/bin/python3.12 tests/test_tk_pasada.py` and the same with the runtime.
  - Key assertions: with `uitk.ensenar` and `subprocess.Popen` wrapped to log, the log reads `["ensenar", "Popen"]`; closing before the first turn launches nothing and calls `al_cerrar` once with 1; a missing binary gives the 127 verdict in the title, one `al_cerrar(127)`, and the window stays usable («Guardar el log» saves the error line).
- [ ] **Step 2: Cutting still cuts.**
  - Run: `tests/test_matar_arbol.py` and `tests/test_tk_salida.py` on both legs.
  - `test_matar_arbol.py`: both window cases wait (`esperar_viva`) until `ventana.proceso` is not `None` before closing; then «cerrar la ventana corta el árbol una sola vez» is still 1.
  - Expected: `test_tk_salida.py` 43 OK unchanged (25 000 lines, whole log saved).
- [ ] **Step 3:** Docs. Both legs. Commit «La ventana de una pasada sale al momento y la pasada empieza justo después».

**Budget:** «Sincronizar ahora» → pass window ≤ 100 ms (with Task 11). Expected Windows effect: the window appears ~10–30 ms sooner (no `Popen` and thread start before building); the pass itself starts that much later.

### Task 7: Children launched from the window die with it (low priority)

Spec R4 «Hijos y salida». No timing budget; it can slip to stage 3 without affecting any other task.

**Files:**
- Modify: `common/store.py`, `common/catalog.py` (`run()` only), `ui/watch.py` (`consulta()` only), `docs/agents/reference/catalogue.md` (`run()`), `docs/agents/reference/ui.md` («Waiting helpers»), `docs/agents/reference/commands-testing.md` (registry: `store.matar_hijos`).
- Create: `tests/test_hijos.py`.

**Interfaces:**
- `store.apuntar_hijo(pid: int) -> None`, `store.soltar_hijo(pid: int) -> None` (thread-safe set behind a lock).
- `store.matar_hijos() -> int`: `matar_arbol()` of each pid still noted, returns how many; never raises. An indirection point.
- `catalog.run(args)`: same contract and result (`CompletedProcess`, `TimeoutExpired` after killing on `TIMEOUT`); now `Popen` with `stdin=DEVNULL`, `start_new_session=True` on POSIX / `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW` on Windows (so `matar_arbol` can cut its tree), noted while it runs.
- `watch.consulta(cmd, timeout)`: same contract; notes its child while it runs.
- Not covered, and said in `ui.md`: `penwatch.run_quiet()` (penwatch does not change), so the «Arranque automático» read of Task 8 can leave a `schtasks` behind.

- [ ] **Step 1:** `python3 tests/test_hijos.py`. Key assertions: a slow `catalog.run` (with `_binary()` replaced by a Python script that sleeps) is noted while running and gone after; `matar_hijos()` from another thread ends it and returns 1; `run()` still returns stdout/rc of a normal child and raises `TimeoutExpired` with `TIMEOUT` patched to 0.2 s, leaving nothing noted.
- [ ] **Step 2:** `python3 tests/test_catalog.py` and `tests/test_watch.py` unchanged. Both legs. Commit «Al cerrar la ventana no queda ningún rclone suyo leyendo la unidad».

---

## Wave 2 (base B2 = Wave 1 merged; merge order 10, 11, 9, 8)

### Task 8: Pane reads after painting (Nombre e icono, Arranque automático, Versiones, QR)

**Files:**
- Modify:
  - `ui/tk_volumen.py`, `ui/tk_versions.py`, `ui/tk_watch.py`, `ui/tk_qr.py`
  - `ui/tk_renombrar.py`: its `Sondeo(marco)` becomes `panel.sondeo()` (one line), so a kept «Catálogo del remoto» pane stops polling while hidden
  - `ui/watch.py` (+ `EstadoVigilante`, `estado_vigilante()`, `deteccion()`)
  - `tests/test_tk_screens.py` (only the cases of these four screens), `tests/test_watch.py`, `tests/test_captura_pantalla.py`
  - `docs/agents/reference/pairing-qr.md`, `docs/agents/reference/ui.md` («Ajustes»: panes that read)
- Create: `tests/test_tk_apartados_lectura.py`.

**Interfaces:**
- Each pane's `construir(panel, …)` paints its whole frame first, with a `panel.indicador(...)` saying what it waits for, then reads through `segundo_plano` and `panel.sondeo()`; what depends on the read is disabled until it lands. Standalone (`open_dialog`) the same code runs inside `dialogo()`.
- **«Nombre e icono»**: `volumen.leer()` through `segundo_plano.lanzar_sin_repetir("volumen", None, volumen.leer)`; the name entry, the colour choice and «Guardar» are disabled until it lands. The five colour samples stay on the Tk thread (with stage 1b they are SVG; they were never the read).
- **«Arranque automático»**:
  - `watch.EstadoVigilante(filas, instalado)` and `watch.estado_vigilante() -> EstadoVigilante` (no Tk, never raises): `penwatch.status_rows()` and `is_installed()`. `watch.deteccion() -> list[tuple[str, str]]`: `penwatch.probe_rows()`.
  - Both go through `segundo_plano.lanzar_sin_repetir("vigilante", None, …)`. The journal (`watch.log_tail()`) and the install button's text (`watch.is_installed()`, a JSON read) stay synchronous.
  - **Time limit:** `watch.TOPE_VIGILANTE_S = CONSULTA_S` (8 s). A `marco.after()` timer started with the read paints, if the read has not landed, the row «El sistema no ha contestado en 8 s: no se sabe si la tarea está registrada.» and stops the indicator; the timer checks `marco.winfo_exists()` and is cancelled by the arrival. The thread may stay alive (penwatch has no timeout and does not change): `lanzar_sin_repetir` keeps one per kind.
- **«Versiones guardadas»**: no `working()` before showing. `versions_editor.leer_local(pair)` and `leer_remoto(pair)` run in one task through `lanzar_sin_repetir(("versiones", pair.name), None, …)`; the counts say «—» and «Purgar»/«Abrir la carpeta» are disabled until it lands; «Releer» and choosing another pair go the same way. Purging stays in `working()` (it writes).
- **«Emparejar un móvil»** (`tk_qr.construir`):
  - `tk_qr.preparar_codigo(raw_local) -> qr.Codigo` (an indirection point): `pairing.construir()` + `qr.codificar(texto, CORRECCION)`, run with plain `segundo_plano.lanzar()` — **never `lanzar_sin_repetir`**, whose `_vivos` table would keep the key alive after the pane goes. The payload text is not returned or kept.
  - Until it lands the card shows «Preparando el código…». On arrival, in this order: `proteger_de_capturas(dlg)`, then `icons.matriz(...)` and its label, then the version line and the capture line (row 2, as today); in «Ajustes» the `<Destroy>` binding that calls `soltar_capturas(dlg)` is set together with the protection.
  - A pane left before the code arrives: the `Sondeo` dies with `panel.marco`, nothing is protected and no image is created.
  - `icons.matriz` stays on the Tk thread (`icons.py` belongs to stage 1b); if the pane still costs > 60 ms on Windows after 1b, splitting its raster from the `PhotoImage` is a later stage's.

- [ ] **Step 1: Paint first.**
  - Run: `xvfb-run -a /usr/bin/python3.12 tests/test_tk_apartados_lectura.py` and the same with the runtime.
  - Key assertions, with `segundo_plano.lanzar` returning an `Encargo` that never finishes (and `segundo_plano.olvidar_lecturas()` between cases, as `test_tk_medidas.py` does): each of the four panes is built with its header and its indicator waiting; `volumen.leer`, `versions_editor.leer_remoto`, `watch.estado_vigilante` and `qr.codificar` were not called on the Tk thread (replaced by functions that record `threading.get_ident()`, run with the real `lanzar`); the dependent buttons are disabled.
  - With `en_el_acto` (as `test_tk_screens.py`): each pane is whole before showing, as today.
- [ ] **Step 2: The watcher's time limit.** With a never-ending read and `watch.TOPE_VIGILANTE_S = 0.05`, after updating for 0.2 s the pane shows «no ha contestado» and its indicator is stopped; a read landing after that replaces the row with the real ones.
- [ ] **Step 3: The QR's order and lifecycle.**
  - Run: `tests/test_captura_pantalla.py` on both legs.
  - New case «el QR que llega después»: with `tk_qr.proteger_de_capturas` and `icons.matriz` wrapped to log, a delayed `Encargo` gives `["proteger", "matriz"]` after arrival and nothing before; the line under the amber block matches the protection returned.
  - New case «salir antes de que llegue»: leaving the pane (destroying `panel.marco`) before arrival, then finishing the `Encargo` and updating, logs neither call.
  - New case «salir y volver» (in «Ajustes»): QR → «Configuración» → QR protects twice and releases once in between (`_afinidad_de_pantalla` log `[0x11, 0, 0x11]` with `IS_WIN` forced).
  - Expected: the existing cases pass unchanged.
- [ ] **Step 4:** `tests/test_tk_screens.py` (pane cases updated to `en_el_acto` and to patch `versions_editor.leer_remoto` instead of `tk_versions.working`), `tests/test_watch.py` (`estado_vigilante()` never raises with a broken penwatch). Docs. Both legs. Commit «Los apartados de Ajustes se pintan al momento y leen después: la unidad, el arranque automático, las versiones y el código QR».

**Budget:** «Cambiar de apartado» ≤ 60 ms. Expected Windows effect: «Nombre e icono» 281 → 40–80 ms with 1b (the drive-letter walk leaves the click); «Arranque automático» no longer waits for `schtasks` (100–300 ms, up to forever); «Versiones guardadas» paints in ~30 ms instead of after the remote (seconds); «Emparejar un móvil» −20…−60 ms (encoding).

### Task 9: «Ajustes» in place, and «Reparación» from the shared read

**Files:**
- Modify:
  - `ui/tk_doctor.py`, `ui/tk_repair.py`, `ui/repair.py`
  - `tests/test_tk_reparacion.py` (pane sections only), `tests/test_repair.py`, `tests/test_tk_screens.py` (Ajustes cases only)
  - `docs/agents/reference/ui.md` («Ajustes»), `docs/agents/reference/repair.md`
- Create: `tests/test_tk_ajustes_vista.py`.

**Interfaces:**
- **The sidebar:**
  - `marcar(antes: str | None, ahora: str)`: restyles only those two buttons (`Nav.TButton`/`NavSel.TButton` and their `boton_icono` background).
  - `chips: dict[str, tuple | None]` remembers each chip drawn; `poner_chips()` recomputes `chip_de()` for every key and replaces only the chip labels whose tuple changed. `pintar_barra()` runs once, at build.
  - With `compartida`: `chip_de("reparacion")` uses `compartida.actual.cuenta` and `("actualizaciones")` its components, falling back to the `hallazgos`/`componentes` parameters; `open_dialog` subscribes `poner_chips` (and the components list) to `compartida` and unsubscribes on `<Destroy>`.
- **The panes (R2):**
  - `paneles: dict[str, tuple[frame, Panel]]`. Each pane is built the first time it is chosen, in its own frame in `contenido`; leaving it calls `panel.ocultado()` and `grid_remove()`; coming back `grid()`s it and calls `panel.mostrado()` and `panel.ajustar()`.
  - **«qr» is never kept:** leaving it destroys its frame (its `<Destroy>` lifts the protection).
  - `rehacer(nota)` (what `Panel.terminar()` calls in «Ajustes»): destroys and rebuilds the visible pane with the green note, **drops every other kept pane** (what it showed may have changed) and calls `poner_chips()`.
  - `dlg.aplicar()`: puts the window back as a fresh open would (search cleared, all kept panes dropped, `INICIAL` or `inicial` built, chips recomputed). Not used yet; the measurement (Task 1) and R7 (Task 13) call it.
  - `dlg.panel` is the visible pane's `Panel`; `dlg.paneles` exposes the dict (tests).
- **«Reparación»** (`tk_repair.construir(..., compartida=None)`):
  - First paint: `compartida.para(config).hallazgos` when there is one (the read is newer than the last pass and than `state/`), else `revision.revisar(config)` as today. The conflicts section is unchanged.
  - `repair.vigente(config, hallazgo) -> Hallazgo | None`: re-runs `revision.revisar(config)` and returns the finding with the same `(clave, pareja)`, or `None`.
  - Before every plan (`aplicar`, `resincronizar`): `vigente()`; `None` → `messagebox.showinfo(«Esto ya no está: …»)` and `repintar()`; otherwise the plan is made from the fresh finding.
  - `repintar()` (after executing, after resolving a conflict) always calls `revision.revisar()`, never the shared read.
  - `RepairPlan` execution re-checks: `plan_locks`'s `hacer()` calls `sincronizacion_en_curso()` again and raises `ReparacionImposible` if someone is syncing now; `plan_apartar`'s checks `pair_state(pair).has_baseline` again.

- [ ] **Step 1: Two buttons and the chips.**
  - Run: `xvfb-run -a /usr/bin/python3.12 tests/test_tk_ajustes_vista.py` and the same with the runtime.
  - Key assertions: switching pane changes the style of exactly two sidebar buttons (styles read before and after); the sidebar's widget objects are the same before and after any switch; `compartida.poner()` with the same count replaces no chip; with another count, exactly the «Reparación» chip label is a new widget.
- [ ] **Step 2: Kept panes (the R2 differential).**
  - The test sets `segundo_plano.lanzar = segundo_plano.en_el_acto` and replaces `tk_versions.working`, `versions_editor.leer_remoto` and `volumen.leer`, so it holds both before and after Task 8 changes how those panes read (Task 8 merges after this one and re-runs it).
  - Key assertions: visiting «Configuración», «Versiones», «Nombre e icono», «Configuración» keeps «Configuración»'s frame (same widget); for each pane, `leer_vista()` after five random visits equals `leer_vista()` of the same pane in a fresh «Ajustes» opened on it; leaving a pane calls its `Panel.ocultado()` once and coming back `Panel.mostrado()` once (spied on the class; what they pause is Task 2's test); «qr» is never in `dlg.paneles` after leaving it; `terminar("Guardado.")` rebuilds the pane with the note and empties the other kept panes; `dlg.aplicar()` reads equal to a fresh open.
- [ ] **Step 3: «Reparación» from the shared read.**
  - Key assertions: with a `compartida` holding a finding the disk no longer has, the first paint shows it without calling `revisar` (counter); its button calls `revisar` once, shows «ya no está» and executes nothing (`confirmar_plan` not called); after a plan is executed the list comes from `revisar`; with no `compartida`, `revisar` runs once as today.
  - Run: `python3 tests/test_repair.py`: `vigente()` cases; `plan_locks`'s execution raises when `sincronizacion_en_curso()` turns true between plan and execute; `plan_apartar`'s raises when the baseline was shelved in between.
- [ ] **Step 4:** `tests/test_tk_reparacion.py` (pane sections), `tests/test_tk_screens.py` (Ajustes cases). Docs. Both legs. Commit «En Ajustes, cambiar de apartado ya no repinta la barra y volver a uno ya visto es instantáneo».

**Budget:** «Cambiar de apartado» ≤ 60 ms; «Abrir Ajustes» ≤ 150 ms. Expected Windows effect: every first visit −40…−80 ms (nine buttons restyled became two); «Reparación» −30…−80 ms more (no `revisar()` in the click); a revisit 5–20 ms; open «Ajustes» −10…−30 ms.

### Task 10: «Parejas» in place

**Files:**
- Modify:
  - `ui/tk_pairs.py` (`ListaParejas`, `EditorPareja`, `open_dialog`)
  - `ui/pair_editor.py` (+ `LecturaConfig`, `rows(config, estados=None)`, `catalog_rows(config, raw, cat, estados=None)`, `botones(fila, lect)`)
  - `tests/test_tk_screens.py` (Parejas cases only), `tests/test_tk_segundo_plano.py` (Parejas cases only), `tests/test_pair_editor.py`
  - `docs/agents/reference/catalogue.md` («Editing pairs from the UI»)
- Create: `tests/test_tk_parejas_vista.py`.

**Interfaces:**
- **`ListaParejas.poner(filas, del_catalogo=False)` diffs by name:**
  - a kept row with the same `CatalogRow`, tone and note touches nothing;
  - a changed one reconfigures its checkbox image, labels and styles, and replaces only the chip label (mode or state) whose `(text, type, icon)` changed;
  - a gone row destroys its widgets and separator; a new one is created;
  - a new order regrids rows and separators.
  - `filas[name]` keeps `"fila"`, `"sup"`, `"apagada"`, `"fondo"`, `"casilla"`, `"nombre"`, `"ruta"`, plus `"modo"`, `"estado"`.
- **`ListaParejas.elegir()`** restyles only the row it leaves and the row it takes (`_pintar(antes, ahora)`).
- **The two views:**
  - One `ListaParejas` per view. The catalogue's list, its action bar, its amber notice and «Ajustes del catálogo…» are created the first time «Catálogo» is chosen (R2).
  - Switching view is `grid_remove()`/`grid()`; a hidden list marked stale is diffed when shown. `dlg.lista` always names the visible list.
- **The rest of `refrescar()` in place:**
  - The catalogue chip, the `[defaults]` origin chip and the selected-pair chip are replaced only when their tuple changes; the endpoint and the `[defaults]` line are configured.
  - `dlg.visor.crecer()` and `centrar()` run only when the requested size changed.
- **The editor's reload rule** (on top of stage 1a's `que_cargar()`/`estado["base"]`/`conservar_lo_escrito()`):
  - nothing unsaved and `que_cargar() == estado["base"]` → `pintar_eleccion()` only, no `editor.cargar()`;
  - nothing unsaved and different → `cargar_editor()`;
  - unsaved → `conservar_lo_escrito()`, as stage 1a.
- **Lazy «Avanzado»:** `EditorPareja(plegable=True)` builds its include/exclude/flags block on the first «Mostrar». Until then `cargar()` keeps the values and `datos()` returns them; `formulario()` (`plegable=False`) builds it at once.
- **`pair_editor.LecturaConfig(ruta=None)`:** `leer() -> tuple[dict, Config]` re-stats `sync_config.toml` (`st_mtime_ns`, `st_size`) every call and parses (`load_raw` + `parse_config(raw, equipo=model.es_equipo())`) only when they changed; raises `ConfigError` like `load_raw`. `cambio -> bool` after the last `leer()`.
- **`refrescar()` and `plan_de()` read through it.** `plan_de()` re-reads first: if the file changed since the screen last showed it, the screen refreshes, the footer says «sync_config.toml ha cambiado fuera de esta pantalla: se ha vuelto a leer. Revisa y vuelve a guardar.», and no plan is made.
- **Pair states:** `pair_editor.rows(config, estados=None)` and `catalog_rows(..., estados=None)` take `{name: (PairState, FiltersState)}` and read only the pairs missing from it.
  - At open: `compartida.para(config).estados` when there is one, else `None`.
  - `estado["estados"]` keeps them while the dialog lives; a local plan executed sets it to `None` (the next `refrescar()` reads).
- **`pair_editor.botones(fila, lect) -> dict[str, bool]`:** the pure rule `habilitar()` used inline (keys: the button texts and `"Descartar del catálogo"`, `"Releer"`).
- **`dlg.aplicar()`:** puts the dialog back as a fresh open would (device view, first row, editor reloaded and folded, initial footer note, `estado["cambiado"] = False`, `leer_catalogo()`). Not used yet; Tasks 1 and 13 call it.

- [ ] **Step 1: The differential.**
  - Run: `xvfb-run -a /usr/bin/python3.12 tests/test_tk_parejas_vista.py` and the same with the runtime.
  - Key assertions, 50 seeded random sequences of `poner()` (rows added, removed, reordered, chips and modes changed, `del_catalogo` flipped): the list's `leer_vista()` equals that of a fresh `ListaParejas` given the final rows.
  - `poner()` of the same rows creates and destroys no widget (the set of widget objects is identical); one changed state chip replaces exactly one widget.
  - `elegir()` changes the styles of exactly two rows.
- [ ] **Step 2: Arrival and toggle.**
  - Key assertions: the catalogue arriving with the same pairs creates no widget, does not call `editor.cargar()` (counter), turns the chip into «catálogo leído · …» and enables the catalogue buttons.
  - The first «Catálogo» creates its list and bar; switching back and forth again creates nothing; `dlg.lista` is the visible list each time.
  - «Mostrar» in «Avanzado» creates the block once, with the values `datos()` already returned.
- [ ] **Step 3: The config read.**
  - Run: `python3 tests/test_pair_editor.py`.
  - Key assertions: two `leer()` of an unchanged file parse once (counter on `model.parse_config`); a size or mtime change parses again; `botones()` table (en_pen, difiere, editable, leyendo); `rows(config, estados=…)` calls `bisync.pair_state` only for missing pairs.
  - In `tests/test_tk_parejas_vista.py`, «una edición a mano entre dos guardados no se pierde»: open, write `sync_config.toml` by hand, press «Guardar aquí…» → no plan (`confirmar_plan` not called), the footer says it changed, `estado["raw"]` has the hand edit.
- [ ] **Step 4: Stage 1a still holds.** `tests/test_tk_segundo_plano.py` (typed text survives a slow catalogue; a changed pair reloads and says so) and `tests/test_tk_screens.py` on both legs; only Parejas cases are touched, and only where they read hidden widgets (use `tests/_vista.visibles`).
- [ ] **Step 5:** Docs. Both legs. Commit «Parejas ya no se rehace al llegar el catálogo ni al elegir: cambia solo lo que cambia».

**Budget:** «Llega el catálogo» ≤ 30 ms (5 pairs); «Elegir otra fila» ≤ 16 ms; «Elegir otra pareja» ≤ 40 ms; «Abrir Parejas» toward ≤ 150 ms. Expected Windows effect: arrival 1212 → 10–30 ms (5) and 6297 → 30–90 ms (50); choosing a row ~2–6 ms; open −30…−80 ms (about 25 widgets fewer, no second config parse, states from the shared read with 50 pairs).

### Task 11: The main window in place

**Files:**
- Create: `ui/tk_principal.py`, `tests/test_tk_principal_vista.py`.
- Modify:
  - `ui/tk.py` (`main_window` only)
  - `tests/test_tk_principal.py`, `tests/test_tk_servicio.py`, `tests/test_ui.py`, `tests/test_tk_reparacion.py` (main-window sections), `tests/test_imports_perezosos.py` (one case), `tests/test_tk_medidas.py` (only if broken)
  - `.claude/rules/ui.md` (path `ui/tk_principal.py`)
  - `docs/agents/reference/ui.md` («Main window and output»), `docs/agents/reference/service.md` («Three writers»)

**Interfaces:**
- **`tk_principal.VistaPrincipal(frame, acciones)`** (draws only; imports nothing from `ui.tk` that tests replace):
  - `acciones` is a `NamedTuple` of callbacks: `sincronizar`, `servicio(accion)`, `parejas`, `ajustes`, `reparacion`, `llavero`, `expulsar`, `bloquear`, `arranque`, `descartar`, `actualizar`, `componentes`, `al_marcar`, `marcar_todas`.
  - Builds the fixed parts once. Each optional block (startup notice, «Reparación…» line, release block, components block, keychain line, auto-start line, pause sentence, «Expulsar»/«Bloquear», «Marcar todas») is created the first time an `Estado` needs it and then only shown or hidden.
  - `aplicar(e: principal.Estado) -> bool`: configures what differs from the last `Estado` applied, block by block (a block whose part of the `Estado` is equal is not touched), and returns whether the requested size may have changed.
  - Rows are keyed by name like Task 10's list; a new row's checkbox starts from `e.marcadas`, an existing one keeps its value.
  - «Marcar todas»'s width is reserved by measuring both texts with `theme.fuente_tk()` (no `update_idletasks()`).
  - `casillas: dict[str, BooleanVar]`.
  - `controles_tk() -> dict[str, tuple[bool, bool]]`: `(a_la_vista, enabled)` per key of `principal.controles()`.
- **`main_window(config, startup_msg)`** keeps its contract and the `ui.tk` names tests replace. In order:
  1. Builds the window and applies `principal.estado(..., inst=None)` (first paint: config, `ui_prefs.json`, `last_run.json`, `update.pending()`; nothing from `revision`, `conflicts`, `components`, `watch` or the keychain).
  2. `encajar`, `centrar`, `ensenar(root)`.
  3. `root.after_idle(refrescar_instantanea)` **after** `ensenar` (so the read's imports come after the driver's module count, and tests run it with `update_idletasks()`).
  4. `precargar_a_ratos`, `mainloop`.
- **`refrescar_instantanea()`:**
  - Runs `segundo_plano.lanzar(partial(instantanea.leer, vista["config"], notas=pair_status_notes, linea_llavero=linea_llavero))` and waits on it with `Sondeo(root, cada=SONDEO_INSTANTANEA_MS)`.
  - `SONDEO_INSTANTANEA_MS = 20`.
  - Sets `root.instantanea = encargo` and `root.instantanea_lista = False` (`True` once applied); these are the driver's and the tests' hooks.
- **On arrival:**
  - `vista["inst"]` is set (an error gives `instantanea.vacia(config)`) and the window's pending agent request is forgotten; `compartida.poner(inst)`.
  - `aplicar()`, then `encajar` **without** `centrar`; if the bottom would leave `pantalla_util`, the window moves up just enough.
- **Refreshing:** the same `refrescar_instantanea()` runs after a pass closes, after «Abrir llavero» returns, after «Reparación»/«Llavero»/components report a change in «Ajustes», after `recargar()`, and when the folder scan (`mirar_conflictos`) finds other counts. «Una sola pasada por refresco»: no other reader of these fields is left in `ui/tk.py`.
- **Coming back from a screen** (R1): `abrir_parejas`/`abrir_ajustes`/`abrir_reparacion`/`abrir_arranque`/`abrir_llavero`/`mirar_version` call `aplicar()` only when what they returned says something changed (a saved config, a non-empty `hecho`, another release, a requested mode). `aplicar()` with an equal `Estado` does nothing; `encajar`/`centrar` run only when `aplicar()` says the size may have changed.
- **`compartida = instantanea.Compartida()`** is passed to `tk_pairs.open_dialog`, `tk_doctor.open_dialog` and `tk_repair.open_dialog`.
- **Ticks (R6):**
  - `al_marcar()` updates «N de M» and the button text, then `seleccion.poner(config, ticked)` and re-arms one `root.after(prefs.ESPERA_MS, seleccion.volcar)`. Nothing is written inside the click.
  - `seleccion.volcar()` also runs: in the continuation of «Sincronizar ahora» before `output_window`; in `servicio()` before returning the `Choice`; and in a `<Destroy>` handler on the root (`evento.widget is root`), which also calls `store.matar_hijos()` when Task 7 is merged (and «Expulsar»/«Bloquear» call it before launching the script or asking the agent).
- **«Sincronizar ahora» (R1 + R6):**
  1. `vista["en_curso"] = True; aplicar()` in the click.
  2. `root.after(1, continuar)`. `continuar()` runs `manual_args(...)` (it reads resync state and may ask, at click time, never from the shared read), `seleccion.volcar()`, then `output_window(..., modal=False, al_cerrar=…)` (Task 6 shows it, then launches).
  3. If anything in `continuar()` raises, a `try/finally` puts `en_curso` back to `False` and `aplicar()`s.
- **«Expulsar»** re-resolves `cifrado.expulsion()` at the click (the shared read may be old).

- [ ] **Step 1: The differential and the table on the real view.**
  - Run: `xvfb-run -a /usr/bin/python3.12 tests/test_tk_principal_vista.py` and the same with the runtime.
  - Key assertions, 100 seeded random sequences of `Estado`s (pairs added, removed and reordered; chips; `en_curso`; `cargando`; startup notice; release; components with and without button; keychain none/can open/cannot; auto-start line with and without pause; service action; footer none/expulsar/bloquear):
    - after each `aplicar()`, `controles_tk()` equals `principal.controles()`;
    - after the sequence, `leer_vista()` of the view equals that of a fresh `VistaPrincipal` given the last `Estado`;
    - `aplicar()` of the same `Estado` twice returns `False` the second time and configures nothing (counter on `ttk.Widget.configure`).
- [ ] **Step 2: Loading, arrival and busy.**
  - Key assertions, driving `main_window` with `mainloop` replaced (sonda) and `segundo_plano.lanzar` returning a never-ending `Encargo`:
    - the header chip is «…»; «Sincronizar ahora» and «Iniciar servicio» are disabled; «Parejas…» and «Ajustes…» are enabled; no keychain line, no «Expulsar».
    - Finishing the `Encargo` and updating applies it: `root.instantanea_lista` is true, «Expulsar» shows when the read says so, the window's `reqheight` grew and its `winfo_x()`/`winfo_y()` did not change.
  - «Sincronizar ahora»: the order log (`aplicar` busy, `manual_args`, `output_window`) holds and `output_window` runs in a later turn.
  - `uitk.output_window` raising leaves «Sincronizar ahora» enabled again.
  - Coming back from «Ajustes» with `tk_doctor.open_dialog` returning `{}` calls neither `VistaPrincipal.aplicar` nor `visor.encajar`.
- [ ] **Step 3: The tick.**
  - «marcar no escribe en el clic»: `prefs.guardar_parejas` counter is 0 right after `invoke()`, 1 after updating for 0.3 s.
  - «el tic se vuelca al cerrar / al lanzar / al iniciar el servicio»: a tick then `root.destroy()`, then «Sincronizar ahora», then «Iniciar servicio», each within 50 ms, leaves the last selection in `ui_prefs.json` (read back with `prefs.read_prefs()`).
- [ ] **Step 4: The existing main-window tests.**
  - `tests/test_tk_principal.py`, `test_tk_servicio.py`, `test_ui.py`, `test_tk_reparacion.py`: their `conducir()`-style helpers set `segundo_plano.lanzar = segundo_plano.en_el_acto` and start each sonda with `self.update_idletasks()`; their button and text searches use `tests/_vista.visibles()` (hidden blocks now exist, `grid_remove`d).
  - Expected: every assertion that was there still holds (startup notice dismissable and the window shrinks; service/watcher/keychain lines; twelve pairs, amber lines and «Expulsar» fit the `test_tk_medidas` matrix).
- [ ] **Step 5: Imports before the first paint.** `tests/test_imports_perezosos.py`, new case, in a fresh interpreter like the file's other cases: with `mainloop` replaced by a sonda that records `sys.modules` **before** `update_idletasks()`, none of `common.revision`, `common.conflicts`, `common.components`, `penwatch` is loaded; after `update_idletasks()` (with `en_el_acto`) they are.
- [ ] **Step 6:** `git diff --stat -- penwatch.py runsync.py` prints nothing. `python3 tests/test_reglas_claude.py`. Docs. Both legs. Commit «La ventana principal cambia solo lo que cambia: marcar, volver de Ajustes y sincronizar ya no la rehacen ni escriben en la unidad al pulsar».

**Budget:** «Marcar» ≤ 16 ms with 0 writes; «Volver de Ajustes/Reparación» ≤ 30 ms; «Sincronizar ahora» → window ≤ 100 ms; main window from launch (toward ≤ 350 ms). Expected Windows effect: marcar ~2–6 ms; coming back 1–5 ms when nothing changed; «Sincronizar ahora» 60–110 ms; first paint −50…−150 ms (imports and reads after it); widgets at first paint ~51 → ~35 (5 pairs).

---

## Wave 3 (base: Wave 2 merged and stage 1b merged)

### Task 12: Measure and decide R7 and R3

**Files:**
- Modify: `docs/superpowers/pruebas/2026-10-09-etapa-2-medidas.md` (section «Decisión»), `docs/superpowers/specs/2026-10-08-frontend-rapido-design.md` («Decisiones para revisar» 3 and 4: the measured outcome, one sentence each).

- [ ] **Step 1:** Push the merged branch. Read `medida-etapa2` (Windows x64 and Linux) and `rendimiento` (Windows x64, Linux) for that sha. Use the GitHub MCP tools: `actions_list` `list_workflow_jobs`, then `get_job_logs` with `tail_lines`.
- [ ] **Step 2: R7, per window** («Parejas», «Ajustes», the pass window): `gain = 1 − reabrir-oculta / abrir-2` from `medida-etapa2` (with Tasks 9/10's `dlg.aplicar()` in the reshow). **Adopt for a window if `gain ≥ 0.50` on Windows x64.**
- [ ] **Step 3: R3** at 20 rows, `construir`, Windows x64 medians: **canvas if `ligera − lienzo ≥ 20 ms`**; else **lean rows if `ref − ligera ≥ 10 ms`**; else neither. Check also that the winner is not worse than the others by more than 5 ms in `elegir` and `refrescar`.
- [ ] **Step 4:** Record the numbers, the rules and the outcome; pick Task 13 A/B and Task 14 A/B/C. Commit «Etapa 2: medido en Windows si conviene esconder ventanas y si la lista de Parejas va sobre un lienzo».

**Expected outcome** (to be confirmed): R7 for «Parejas» and «Ajustes» (rebuild ~250–400 ms against a reshow of 60–120 ms), not for the pass window (rebuild ~80–120 ms against a 45–80 ms show floor); R3 canvas (lean rows still cost ~5 × 0.8 ms per row on Windows).

### Task 13: R7 — hide instead of destroy (conditional)

**Branch A — adopted** for the windows Task 12 named.

**Files:**
- Modify:
  - `ui/tk.py` (`mostrar(dlg, parent=None, hasta=None)`; `guardada(parent, clave)`/`guardar(parent, clave, dlg)` helpers; `output_window` only if the pass window qualified)
  - `ui/tk_pairs.py` and/or `ui/tk_doctor.py` (`open_dialog`)
  - `tests/rendimiento/driver.py` (`Misc.wait_variable` intercepted like `wait_window`: update, timestamp, hook, then close the kept dialog through its own close path)
  - every test that replaces a `mostrar` (find them with `grep -n "mostrar = " tests/*.py`; `tests/test_tk_screens.py`'s `ocultar()` among them): the replacements take `**k`
  - `docs/agents/reference/ui.md` (new «Windows that hide» subsection)
- Create: `tests/test_tk_reabrir.py`.

**Interfaces:**
- **Showing and closing:**
  - `mostrar(dlg, parent, hasta=var)`: `centrar`, `ensenar`, `grab_set`, then `dlg.wait_variable(var)` instead of `wait_window`; without `hasta` it is today's `mostrar`.
  - A kept dialog's «Cerrar» and its `WM_DELETE_WINDOW` run `grab_release()`, `panel/lista` pauses (`ocultado()`, `Sondeo.pausar()`), `withdraw()`, `var.set(True)`.
- **Reopening:** `open_dialog` finds the dialog kept on `parent` (`guardada(parent, "parejas")`), calls `dlg.aplicar()` (Tasks 9/10) and `mostrar(..., hasta=)`; the first open builds and keeps it; destroying `parent` destroys it. `open_dialog` returns what it returned before (`estado["cambiado"]`, `resultados`), reset by `dlg.aplicar()`.
- **«Ajustes» showing «Emparejar un móvil» when closed:** the QR frame is destroyed before hiding (protection lifted), never kept.
- **Unchanged:** `gc.collect()` after each close stays.

- [ ] **Step 1:** `tests/test_tk_reabrir.py` on both legs. Key assertions:
  - open, change view/selection/typed text/pane, close, reopen: `leer_vista()` equals that of a fresh open in a second parent;
  - the grab is released while hidden (`grab_current()` is not the dialog) and set when shown;
  - a hidden dialog's `Sondeo` schedules nothing;
  - closing «Ajustes» on the QR pane calls `soltar_capturas` and keeps no QR frame;
  - `open_dialog` returns `False`/`{}` on a reopen with no change.
- [ ] **Step 2:** The driver still measures `open-parejas`, `open-ajustes` and now `reabrir-parejas` through the reshow. Local `correr.py --rondas 2` A/B against B1: exit 0. Both legs. Commit «Volver a abrir Parejas y Ajustes es instantáneo: se esconden en vez de cerrarse».

**Budget:** «Abrir Parejas» ≤ 150 ms (reopened), «Abrir Ajustes» ≤ 150 ms (reopened). Expected Windows effect: reopen ~250–400 → 70–130 ms (Parejas), ~120–180 → 60–100 ms (Ajustes). The first open per process is unchanged.

**Branch B — not adopted:** no code. Task 12's record says why; «Decisiones para revisar» 4 reads «medido: no compensa».

### Task 14: R3 — the «Parejas» list (conditional)

**Branch A — canvas adopted.**

**Files:**
- Create: `ui/tk_tabla.py`, `tests/test_tk_tabla.py`.
- Modify:
  - `ui/tk_pairs.py` (`ListaParejas` becomes an adapter)
  - `ui/theme.py`: only two public helpers, `mezcla(a, b, t) -> str` and `colores_chip(tipo) -> tuple` (a wrapper of `_chips()`)
  - `tests/test_tk_parejas_vista.py`, `tests/test_tk_screens.py` (row-widget reads → `leer()`)
  - `.claude/rules/ui.md` (path `ui/tk_tabla.py`)
  - `docs/agents/reference/ui.md` (the table), `docs/agents/reference/catalogue.md` (the list)

**Interfaces:**
- **`tk_tabla.TablaLienzo(parent, columnas, al_elegir=None, puede_dejar=None, vacio="")`:** draws only, on one `tk.Canvas`, with items and never embedded windows (so `ui.md`'s «not in a Canvas» rule for the `Visor` does not apply).
  - **API:** `poner(filas)` diffs by `iid` and redraws only changed rows (a full relayout only when a column width changes); `elegir(iid, avisar=True) -> bool`; `filas`, `orden`, `elegida`, `cabeceras`; `leer() -> list[tuple[str, ...]]` (what is drawn, as text).
  - **Keyboard:** Tab focus with the 2 px accent ring; ↑/↓/Inicio/Fin/RePág/AvPág; Intro calls `al_elegir`. It does not take the `Visor`'s wheel.
  - **Mouse:** click selects; hover is a blend from `theme.mezcla()`.
  - **Drawing:** `<Configure>` redraws after 40 ms (debounced); a path too long is elided with «…» (the editor shows it whole); fonts from `theme.fuente_tk()`; distances through `theme.medida()`/`icons.px()`; colours read as `theme.X` at call time.
  - **Chips** are a rounded polygon plus `icons.disco()` plus a text item.
- **`ListaParejas` adapter:** same constructor and attributes (`marco`, `filas[name]["fila"]`, `orden`, `elegida`, `poner(filas, del_catalogo)`, `elegir(name, avisar)`, `fila()`), plus `leer()`. The checkbox column is an indicator: choosing a row does not change it; «Usar aquí»/«Quitar» do.
- **Stage 3** uses `TablaLienzo` for «Dispositivos» and the flags table (`tk.Tabla`); not in this stage.

- [ ] **Step 1:** `tests/test_tk_tabla.py` on Tk 9 and Tk 8.6 (on Tk 8.6 the disc comes from the Python painter). Key assertions:
  - `leer()` after `poner()` equals the expected texts, with long paths elided;
  - ↓/↑/Fin/Inicio move the selection and call `al_elegir` (refused when `puede_dejar` says no);
  - a click at a row's y selects it;
  - `poner()` of the same rows leaves `find_all()` unchanged, and one changed chip changes only that row's items;
  - the wheel over the list scrolls the `Visor`.
- [ ] **Step 2:** `tests/test_tk_parejas_vista.py`'s differential runs against `leer()`; `widgets.parejas.p5` drops by ~30, `p50` by ~300 (counted by the driver). Both legs. Commit «La lista de Parejas se dibuja de una vez: abrir con muchas parejas ya no tarda».

**Budget:** «Parejas» with 50 pairs ≤ +50 ms over 5. Expected Windows effect: +1266 ms → +40–100 ms; open with 5 pairs −15…−30 ms.

**Branch B — lean rows adopted.**
- **Files:** `ui/tk_pairs.py` (`ListaParejas` rows), `ui/theme.py` (one style created inside `apply()`: `Plano.Linea.TFrame`, background `LINEA_SUAVE`), tests as in Branch A without `tk_tabla`.
- **Interfaces:** 5 widgets per row (row frame; checkbox image + name in one label, `compound="left"`; path; mode chip; state chip); separators are 1-px gaps over a `Plano.Linea.TFrame`; the diff, the two-row restyle and `filas[name]` keys of Task 10 unchanged.
- **Expected Windows effect:** 50 pairs +1266 → ~+200 ms; the 50-pair budget is not met (said in Task 15's results).

**Branch C — neither:** no code; Task 10's list stays (7 widgets per row) and the results say the 50-pair budget is not met.

---

## Wave 4

### Task 15: Close the stage

**Files:**
- Delete (`git rm`): `.github/workflows/medida-etapa2.yml`, `tests/rendimiento/etapa2_*.py`.
- Modify:
  - `tests/rendimiento/presupuesto.toml`: `[techo]` `widgets.main.p5`/`p50`, `widgets.parejas.p5`/`p50`, `widgets.ajustes.*`, `escrituras.marcar = 0`; `[techo.linux]`/`[techo.windows]` `modulos.main` from the measured counts.
  - `AGENTS.md`: layout map `ui/` line: `principal` and `instantanea` among the decision halves, `tk_principal` (and `tk_tabla`) among the `tk_*`.
  - `docs/agents/reference/ui.md` (one coherence pass over the sections Tasks 2–14 touched).
  - `docs/superpowers/specs/2026-10-08-frontend-rapido-design.md` («Estado» line: stage 2 done and measured).
- Create: `docs/superpowers/pruebas/2026-10-xx-etapa-2-resultados.md`.

- [ ] **Step 1:** Push. Read the `Tests` run (jobs `tests` and `tests-tk9`, Linux and Windows) and the `Rendimiento` run (windows-x64, linux-x64) for the pushed sha. If a Windows test fails, root-cause it as a bug in code or test; never skip it.
- [ ] **Step 2: Ceilings.** Copy the counts the summary prints («techo bajable») into `presupuesto.toml`, Linux and Windows separately for `modulos.*`.
- [ ] **Step 3: Results.** Write the results file:
  - per moment of both spec tables: 0.7.1, 1a, 1b, stage 2, on Windows and Linux;
  - the deterministic counts;
  - which budgets are met and which are not, and why (expected: main window from launch above 0.35 s; «Parejas» first open above 0.15 s unless R7 reopens; the 50-pair budget depends on Task 14);
  - the R3/R7 decisions with their numbers.
- [ ] **Step 4:** `python3 tests/test_reglas_claude.py`; both legs. Commit «Etapa 2 medida en Windows y Linux», and push.

---

## Open risks

1. **The launch budget (main window ≤ 0.35 s, «Parejas» from launch ≤ 0.50 s) is not reached by this stage** even with 1b: Python start, imports and `Tk()` remain (~400–500 ms on Windows). Stage 2 removes the reads and some widgets from the first paint; what else is left needs stage 4's `PRDRIVE_PERF=1` to locate.
2. **First open of «Parejas» ≤ 150 ms** depends on 1b's SVG pieces (most of today's 861 ms looks like icon painting and repainting, not widget count; Task 1's Windows profile confirms or refutes it before Wave 2) and, for reopening, on R7.
3. **The 1.2 s catalogue arrival is explained only on Linux.** If the Windows profile (Task 1) shows the cost is a whole-window relayout or repaint triggered by `Visor.crecer`/`centrar` rather than the rebuild itself, Task 10's «size changed» guard is what fixes it; the in-place diff alone would not.
4. **Lean rows cannot be 4 widgets** without dropping a chip or the full-row highlight (a visual change); the measured lean variant has 5. If the canvas loses on Windows, the 50-pair budget is not met.
5. **«Arranque automático» can leave a `schtasks`/`systemctl` child running** after its 8 s limit: `penwatch.run_quiet()` has no timeout and `penwatch.py` must not change, so that child is neither cut nor noted for `matar_hijos()`. With the window's cwd on the device, a hung child could hold the volume during «Expulsar».
6. **The first paint now shows less** (neutral chip, no per-pair chips or lines) for the ~20–150 ms the read takes, and the footer's second button can turn from a disabled «Iniciar servicio» into «Pausar» when the read lands. It is the spec's choice; on a slow USB drive the gap is longer and the change more visible.
7. **Behaviour changes to watch in review:**
   - the pass process starts after its window instead of before;
   - «Guardar aquí…» after a hand edit asks to save again instead of overwriting;
   - «Reparación» says «ya no está» for a stale finding.
8. **Merge friction:** Wave 2 tasks share `tests/test_tk_screens.py`, `tests/test_tk_reparacion.py` and `ui.md`; the merge order and «own sections only» keep conflicts textual, but a builder that «fixes» another task's section creates real ones.
9. **The driver runs the PR's code against `main` (0.7.1):** every new driver step must work on both trees. Task 13 changes how dialogs wait (`wait_variable`), and if its driver change misses a path, «Abrir Parejas» stops being measured and the check fails as «falta».
10. **Stage 1b timing:** Wave 3 needs 1b merged (Task 14 adds to `theme.py`, and the R3/R7 numbers only mean something with 1b's drawing). If 1b slips, Tasks 12–14 wait; Tasks 1–11 do not.

---

## Corrections after review (override the task text)

An adversarial review checked this plan against the code (findings: `docs/superpowers/plans/2026-10-08-frontend-rapido-etapa-2-revision.md`, with file:line references; read the entry for your task there too). Every finding below is accepted. Where a correction and the task text disagree, the correction wins.

### Global

- **Stub signatures.** When a function gains a keyword, every test stub of it takes `**_k` (M9). The ones known: `tests/test_tk_principal.py:50` (`components.pendientes`), `:171/175/226` (`cifrado.expulsion`); `tests/test_tk_servicio.py:62,621,638`; `tests/test_tk_reparacion.py:428,474` (`tk_repair.open_dialog`, owned by Task 11) and `:566` (`construir_falso`, owned by Task 9).
- **Timing assertions are never «after N ms»**: loop until the condition holds, bounded at 2 s; or assert the scheduled delay (wrap `after`) instead of counting polls (minor 14).
- **No `chmod` to simulate a read-only drive** (the sandbox runs as root): patch `store.write_json` to return `False` (minor 14).
- `segundo_plano`'s table of live tasks is `_EN_VUELO` (not `_vivos`).
- `commands-testing.md` is a merge hot spot too (Tasks 2, 3, 4, 7, 8).
- Review Focus 5 reads: «no control that touches `state/` is enabled during a pass; before the shared read lands only «Parejas…» and «Ajustes…» are, by design».

### Task 1 (measurement)

- `etapa2_reabrir.py` holds `catalog.load` on an `Event` during `abrir-1`, `abrir-2` and `reabrir-oculta` (and around `dlg.aplicar()`), releasing it after each measurement, so the catalogue's arrival never lands inside a timed window (M7).

### Task 3 (`ui/instantanea.py`)

- **Freshness is a stat snapshot, not a folder date (M1).** `leer()` records at its start `huella: tuple` of `(path, st_mtime_ns, st_size)` (or `None` when missing) for: `state/last_run.json`, `state/conflicts.json`, the catalogue-duplicate record `catalog.duplicado()` reads, the `filters/` folder, and each bisync pair's workdir `state/<pair>/`. `vigente(config)` = same `firma` and an identical snapshot now (equality, no slack). `ui.lock.json`, `ui_prefs.json`, `servicio.pide`, `daemon.stop` and `*.tmp` do not count. `HOLGURA_MTIME` goes. Step 2 becomes: touching `last_run.json` or a pair's workdir → stale; writing `ui_prefs.json` or `ui.lock.json` → still `vigente`.
- **One sentinel (minor 1):** `vestibulo.BUSCAR` is the single «look it up yourself» value, reused by `revision`, `cifrado` and `vestibulo` (never forward one module's private sentinel to another: the «espacio» finding would vanish silently). The «once» assertion of Step 1 covers `raiz_fisica` (with a config without `[keychain]`); `device_id` is not asserted once.
- **The read must not write (minor 2):** if `revisar()` regenerates `filters/<pair>.txt`, `leer()` uses a read-only path (or the write is atomic); say which in `ui.md`.
- Step 1 adds «happy path: `fallos` is empty» (M9).

### Task 4 (driver)

- **Keep `cancel_afters(root)` where it is (M6).** Task 11 sets `root.sondeo_instantanea` (the read's single `Sondeo`) and `root.instantanea` (the `Encargo`). In `probe()`, after `medir()`/`record`, if the root has `instantanea`: wait with `time.sleep` (no `update()`) until `root.instantanea.hecho` or 5 s, then time `root.sondeo_instantanea._mirar(); root.update()` as `llega-instantanea` (the `catalogo-llega` pattern). Never pump the event loop before measuring «Parejas»/«Ajustes»: it would run `precargar_a_ratos` in the PR only and bias every comparison.
- **Reopen (M7):** before the second «Parejas…» click, `ESTADO["catalogo"].clear()`; release it after recording `reabrir-parejas`, which has its own handler (it records only `reabrir-parejas`).
- **The `principal` flow (minor 16):** the toggled checkbox must leave ≥ 1 pair ticked (untick then tick the same one, timing the second), else «Sincronizar ahora» does nothing; in 0.7.1 an empty selection writes nothing.

### Task 5 (`ui/principal.py`)

- **Imports (B2):** `ui/principal.py` imports only the stdlib and `ui.prefs` at module level. `watch` and `llavero_editor` are imported inside `estado()` only when `inst is not None`. `principal.INICIAR = "iniciar"` is duplicated on purpose; a test ties it to `watch.INICIAR`. New case: `import ui.principal` in a fresh interpreter loads none of `common.components`, `common.conflicts`, `common.revision`, `common.fleet`, `penwatch`.
- **Depends on Task 3's names only (minor 3):** `estado()` reads `inst` by attribute; its tests use `types.SimpleNamespace` with Task 3's field names (after merging, one case feeds `instantanea.vacia(config)`).
- `Estado.servicio` is built by name from `watch.BotonServicio` (`(texto, accion)` there); the Step 1 enumeration adds `watch.SEGUIR` («Reanudar todo»).
- `prefs` read-only case: patch `store.write_json` (Global).

### Task 7 (children)

- **Same process group as today (B1):** `catalog.run` keeps creating its child exactly as now (no new session, no new process group), so a `catalog.run` from inside `sync.py` stays in the pass's group and `matar_arbol` still reaches it. It keeps the `Popen` while it runs; `store.matar_hijos()` kills each noted child directly (`Popen.kill()`; rclone has no children). Extend `tests/test_matar_arbol.py`: a parent started with `start_new_session=True` that calls `catalog.run` with a sleeping fake binary; `matar_arbol(parent)` kills the grandchild.
- **Only reads are noted (M8):** `catalog.run(args, apuntar=None)` notes the child only for read-only verbs (`cat`, `lsjson`, `lsf`, `lsd`, and `copy`/`copyto` whose destination is a local temp); writes (`copyto` to the remote, `moveto`, `delete`, `deletefile`, `mkdir`, `purge`) are never killed by `matar_hijos()`.

### Task 8 (pane reads)

- **QR tests (minor 4):** `tests/test_captura_pantalla.py`'s existing cases set `segundo_plano.lanzar = segundo_plano.en_el_acto`; update its module docstring (line 17) and `pairing-qr.md`: standalone, the window now shows before it is protected, with no code on screen yet.
- **Panes that keep polling (minor 5):** add `ui/tk_llavero.py` (its `Sondeo(marco)`/`Indicador(marco)`, lines ~176/180) and `ui/tk_renombrar.py` (`Indicador(marco)`, ~71) to the files: both use `panel.sondeo()`/`panel.indicador()`. Update `ui.md`'s «switching pane cancels them» sentence.
- **«Versiones» (minor 6):** the read returns `(pair, local, remote)` together; the arrival stores the triple; «Purgar» uses that triple and stays disabled while a read for another pair is in flight.
- **Registry (minor 7):** `tk_qr.preparar_codigo` and `watch.estado_vigilante` go in `commands-testing.md`'s registry (Task 8 owns that line).

### Task 9 («Ajustes»)

- **A pane built before the read lands (M4):** `construir_arranque` takes `vigilante` from `compartida.actual` when present, else from the parameter, else calls `watch.resumen()` itself; it never falls to the penwatch screen for lack of data. «Actualizaciones» built before the read lands shows an `Indicador` and is rebuilt when `compartida.poner()` fires (or calls `components.pendientes()` itself).
- **Unsubscribe (minor 17):** the `<Destroy>` handler checks `evento.widget is dlg`.
- **R2 deviation (minor 13):** `Panel.terminar()` rebuilds the visible pane and drops the other kept ones instead of the spec's `invalidar()`; say so in `ui.md` as a deliberate choice.

### Task 10 («Parejas»)

- **The hand-edit check is before the write (M5):** local plans: `aplicar()` re-checks `LecturaConfig` right before `plan.execute()`; if the file changed, nothing executes, the screen refreshes and the footer says so. Test: the `confirmar_plan` stub edits `sync_config.toml` and answers yes → no write, hand edit kept. (The check in `plan_de()` stays too.)
- **The size guard is logical (minor 8):** `poner()`/`refrescar()` return whether rows were added or removed or a wrapping text changed; only then `crecer()`/`centrar()` run.
- **Which config the shared states are for (minor 9):** `compartida.para(estado["config"])` after the first `LecturaConfig.leer()`. `rows(config, estados)` computes the resync notice from the given `(PairState, FiltersState)`; a test asserts neither `pair_state` nor `filters_state` is called for given pairs.

### Task 11 (main window)

- **Imports (B2):** `ui/tk_principal.py` follows Task 5's import rule; Task 11 removes `components`, `conflicts`, `revision` and `watch` from `main_window`'s header imports (tk.py ~1604-1606). A `from . import instantanea` inside `refrescar_instantanea` goes in `PRECARGA`; extend `importados_tarde()` (test_imports_perezosos.py ~82-98) to scan `ui/tk_principal.py` too.
- **`tests/test_start.py` (B3)** is in Task 11's files: its fake mainloop sets `segundo_plano.lanzar = segundo_plano.en_el_acto` and calls `self.update_idletasks()` first.
- **Busy on failure only (M2):** if anything in `continuar()` raises before `output_window()` returns, an `except BaseException:` puts `en_curso` back to `False`, `aplicar()`s and re-raises; on success `en_curso` stays until `al_cerrar`. Check `selected()` is non-empty in the click, before turning busy.
- **«Arranque automático» always refreshes (M3):** `abrir_arranque` (the watcher dialog, not the agent one) refreshes the line after it closes (`tk_watch.open_dialog` returns nothing); `tests/test_tk_servicio.py:321-345` keeps passing.
- **«Ajustes» before the read (M4):** pass `vigilante=vista.get("vigilante")` (may be `None`) and `compartida`.
- **One `Sondeo` (minor 10):** a single `Sondeo` per window, created once; a newer read replaces the older one, whose result is dropped.
- **Differential (minor 11):** mask checkbox variable values in the differential and test the keep-value rule separately; besides counting `configure`, assert the widget set and `leer_vista()` are unchanged on an equal `Estado` (nit).
- **Flush placement (minor 12):** `seleccion.volcar()` runs right after `output_window()` returns (window shown, process not yet launched), not before it; consider flushing inside `lanzar()` so passes from «Reparación» and the keychain also flush.
- **«Marcar todas» width (minor 15):** add the style padding (`ttk.Style.lookup("Quiet.TButton", "padding")`) and border to the measured text; test that the reserved `minsize` is ≥ the button's `winfo_reqwidth()` with each text.
- **Header chip size (minor 13):** reserve the chip's column width for the widest of «al día» / «N que revisar» (measured with `theme.fuente_tk`), so «…» does not shift the header when the read lands.
- `mirar_conflictos.responder` while `inst is None`: treat as changed (refresh) (nit).
- After arrival, the helpers assert `inst.fallos == {}` (M9).

### Task 12 and 15

- Task 12: read runs with the GitHub MCP tools; if unavailable, the public API (`curl https://api.github.com/repos/Jeremaya25/prdrive/actions/runs/...`) and the job logs.
- Task 15 does **not** remove the temporary `push:` triggers of `tests.yml` and `rendimiento.yml`: with no PR open they are the only way CI runs on this branch; they go when the owner opens the PR («TEMPORAL: quitar antes del PR»).
