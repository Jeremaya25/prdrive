# Frontend rápido, etapa 3 («El resto») — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Tasks of the same wave are built **in parallel**, each on its own scratch copy, and merged in the order the wave gives (see «Parallel build protocol»).

**Goal:** The screens stage 2 did not touch get the same treatment: «Dispositivos» and the flags editor stop growing with their data, no step of the install wizard freezes while it reads the disk, the system or the network, the agent's question is drawn with at most 11 widgets, and the installer `.exe` is built with the device's own Python 3.14.8 and Tk 9.0.4 and is tested before it is published. Same look, same screens, same behaviour.

**Architecture:** Four independent strands, then the table:
- **Tables on the canvas (R3, decided in stage 2).** `ui.tk.Tabla` (fleet, flags editor) is redrawn on stage 2's `ui/tk_tabla.py` `TablaLienzo`, keeping every attribute its callers and tests read. Only this strand waits for stage 2 Task 14.
- **Build once, change in place (R1/R2) for «Dispositivos».** The card under the table becomes a fixed set of labels configured per device; its size is reserved by measuring those labels, never by painting one card per device (`reservar()` today).
- **Read after painting (R4) in the wizard.** Every read the spec lists for the wizard (`device.list_volumes()`, the host-Python check, the device verification with `schtasks`/D-Bus, the fleet note's `rclone`, `tk_crypto`'s write probe, `tk_equipo`'s per-keystroke folder examinations) leaves the Tk thread through `ui.segundo_plano` + `tk.Sondeo`, or goes into `working()` when it writes to the remote.
- **The installer on the pinned runtime (§4).** The release job builds with an unpruned copy of the pinned python-build-standalone 3.14.8 (Tk 9.0.4), PyInstaller pinned to 6.22.3, `build_installer.comprobar_tk()`, `device.check_python()` asking the host's Python in a subprocess, and a new non-interactive `--autoprueba` that the CI runs on the built `.exe` before anything is published.

**Tech Stack:** Python 3.11+ stdlib only for everything that runs on a device or host; PyInstaller 6.22.3 at build time only; tkinter (Tk 8.6 and Tk 9.0.4); plain-script tests (`tests/_harness.Checks`); GitHub Actions (`tests.yml`, `rendimiento.yml`, a new `instalador.yml`, `build-installer-release.yml`, a new composite action).

**Spec:** `docs/superpowers/specs/2026-10-08-frontend-rapido-design.md` (version 2): «Etapas» item 3; §2 R1–R5 (R3 as decided: canvas; R7 not adopted); §3 «El arranque» (`.pyc`, `pregunta.py` already done in 1a); §4 «Tk 8.6, el instalador y la CI»; §5; «Qué se quiere»; «Decisiones para revisar» 6.

**Inputs this plan was built from** (`$SCRATCH` = `/tmp/claude-0/-home-user-prdrive/03b34008-f2da-52c1-8cde-5efd2782344d/scratchpad`):
- The stage 2 plan and its review (`docs/superpowers/plans/2026-10-08-frontend-rapido-etapa-2*.md`), with its «Corrections after review» applied; the R3/R7 first reading (`docs/superpowers/pruebas/2026-10-09-etapa-2-medidas.md`: canvas 79 ms against lean rows 162 and today's rows 1403 at 20 rows on Windows; R7 gains 0.11–0.46, not adopted).
- Stage 1a/1b results (`docs/superpowers/pruebas/2026-10-08-etapa-1{a,b}-resultados.md`): agent's question 235 ms, wizard 389 ms, `widgets.agente` 16, `widgets.wizard` 20 (Windows x64, 1b).
- The screens audit `$SCRATCH/diseno/notas-pantallas.md` and `$SCRATCH/diseno/pantallas/res/{wizard,fleet,misc}.json` (Linux, 0.7.1): wizard step bodies 7–71 widgets (Conexión 41, Instalación 42, Plataformas 39, Verificación 41, host-route Verificación 71); flags editor 78 widgets with 3 flags; fleet 33 at open, +7 per device, `reservar()` creating 24N+18 on arrival.
- A count made for this plan at tip `1e339b9` (Linux, Tk 9.0.4; script `$SCRATCH/e3/sondas/contar.py`): «Dispositivos» with 3 devices **68** widgets (table 28, card 17 with its frame and label, header 10, `Visor` + body 6, footer 6, empty-fleet label 1); flags editor **82** with 3 flags (table 56 = 13 rows) and **70** with none (table 44); everything but the table is **26** in both. Agent's question **16** (`Visor` 5, body frame 1, `arriba` 1, mark 1, `cabecera` frame + 2 labels, 2 notes, `pie` + 2 buttons).
- PyInstaller facts, read on 09/10/2026 from PyPI (`$SCRATCH/e3/sondas/pyinstaller.json`) and the official changelog (`$SCRATCH/e3/sondas/changes.html`): **6.15.0 (2025-08-03) «Add Python 3.14 support»**; **6.22.0 (2026-08-08) «Implement support for Tcl/Tk 9 builds with embedded data archives in tkinter hooks»**, plus «error about missing Tcl/Tk data directories is raised at build time»; latest **6.22.3 (2026-09-12)**, `requires_python <3.16,>=3.8`, Windows x64 wheel `pyinstaller-6.22.3-py3-none-win_amd64.whl` sha256 `500bd58c7bf7e584a8435adccbd763a0b918d5c12b08d74ff50fd79b2915458b`; dependencies `altgraph`, `packaging>=22.0`, `pefile>=2022.5.30` and `pywin32-ctypes>=0.2.1` (win32), `pyinstaller-hooks-contrib>=2026.7`, `setuptools>=42.0.0`. **Not verifiable offline, so verified in CI by Task 6:** that 6.22.3 bundles the Tcl/Tk 9.0.4 of the python-build-standalone 3.14.8 Windows build so that `Tk()`, the SVG probe and the bundled font work inside the `.exe`.

There are **no reference artifacts**: builders implement from the Interfaces and the test lists.

**Base commits.**
- **B1** = the branch tip once stage 2 **Wave 2** (Tasks 8–11) is merged. Stage 2 Wave 3–4 (Tasks 12–15) may still be in flight: Wave 1 of this plan does not edit the files they own (Global Constraints).
- **B2** = Wave 1 of this plan merged **and** stage 2 completely merged (Task 14 Branch A, `ui/tk_tabla.py`; Task 15).
The exact sha is given in each builder's message.

**Read «Corrections after review» (end of this file, added after the adversarial review) before your task: it overrides the task text wherever they differ.**

---

## Budget map (Windows x64, 100 %; spec «Qué se quiere» and R5)

Times are estimates from the inputs above; Task 8 replaces them with measurements.

| Moment or count | Before stage 3 | Target | Tasks | Expected after stage 3 |
|---|---|---|---|---|
| Agent's question, from launch | 235 ms | ≤ 300 ms | 2 | 225–235 ms (met already) |
| `widgets.agente` | 16 | ≤ 11 | 2 | 11 |
| Wizard, from launch | 389 ms | ≤ 300 ms (informative) | 2 | ~385 ms: **not reached** (Open risk 3) |
| Wizard: «Siguiente» from «¿Dónde?» to «Dispositivo» (new moment) | `list_volumes()` in the click (Windows: kernel32 walk + `disk_usage` per volume, 20–500 ms) | no read in the click (R4) | 1, 4 | paint 30–80 ms; the list lands later |
| Wizard steps, widgets in the body | 7–71 | ≤ 40 | 4, 5 | ≤ 40, **except «Verificación»**: ≤ 6 + 4 per check row (Open risk 2) |
| Wizard reads on the Tk thread | `list_volumes`, host Python, verification (`schtasks` ≤ 8 s, D-Bus), fleet note (`rclone` ≤ 45 s), crypto probe (8 MiB + `fsync`), `examinar` per keystroke | none | 4, 5, 6 | none |
| Open «Dispositivos» (12 devices, new moment) | ~40–80 ms | — | 1, 3, 7 | similar |
| Fleet arrives in «Dispositivos» (new moment) | 7 widgets per device (~70 ms per row on Windows, stage 2 list measurement) + `reservar()` painting 12 cards: ~1–1.5 s | — (R1) | 3, 7 | 20–60 ms |
| `widgets.dispositivos` (after arrival) | 33 + 7N + card ≈ 131 for 12 devices | ≤ 35 | 2, 3, 7 | 41 + one per date shown (≈ 46 with the sample fleet), **constant in N**: not reached with the same look (Open risk 1) |
| Open the flags editor (new moment) | 82 widgets (3 flags) | — | 1, 7 | −40…−120 ms (≈ 55 widgets fewer) |
| `widgets.flags` | 78–82 | ≤ 34 | 2, 7 | 26–28 |
| Installer `.exe` | setup-python 3.11 (Tk 8.6), PyInstaller unpinned, not run before release | 3.14.8, Tk ≥ 9, PyInstaller ≥ 6.22 pinned, tested (§4) | 6 | python-build-standalone 3.14.8, Tk 9.0.4, PyInstaller 6.22.3, `--autoprueba` gate |

---

## Global Constraints

- **Python and dependencies:** stdlib only for everything that runs on a device or a host; PyInstaller is a build-time dependency (as today). Python ≥ 3.11 for all code (CI leg 1 and the light install); the device runtime is python-build-standalone 3.14.8 with Tk 9.0.4 (CI leg 2).
- **Language:** comments, docstrings and user-visible text in Spanish; `docs/agents/` and this plan in English; `docs/agents/code-writing-conventions.md` (Google-style docstrings, variable docstrings for policy constants).
- **Tk rules:**
  - `import tkinter` only inside functions.
  - `tk_*` modules only draw; decisions live in modules without Tk and are tested headless. Pure helpers a `tk_*` module already keeps for tests (`tk_fleet.ficha()`, `tk_equipo.comprobaciones()`) may stay there.
  - Colours, fonts, glyphs and styles only through `theme`/`icons`; distances through `theme.medida()` (or `icons.px()` for what Tk cannot scale).
  - **No ttk style is created, configured or mapped after the first widget of an interpreter** (new styles go inside `theme.apply()`).
  - **No `update_idletasks()` in the middle of building**, except the one-per-arrival measurement Task 3 allows, and only if its Step 1 shows label sizes are not available otherwise.
- **Threads:** every new thread is `daemon` (`segundo_plano`), never touches Tk, returns data and receives a `functools.partial` of data (never a lambda among widgets). Results come back on the Tk thread through a `tk.Sondeo` hung off a widget **of the step or window that asked**, so a step change or a closed window cancels the wait. Writes to the remote stay in `working()` (`ui.md`, «Waiting helpers»).
- **Files this plan's Wave 1 must not edit** (stage 2 Waves 3–4 own them): `ui/theme.py`, `ui/icons.py`, `ui/tk_pairs.py`, `ui/tk_tabla.py`, `tests/test_tk_tabla.py`, `tests/test_tk_parejas_vista.py`, the «Parejas» sections of `tests/test_tk_screens.py`, `AGENTS.md`, the spec, `docs/superpowers/pruebas/2026-10-09-etapa-2-medidas.md`. Wave 2 (Task 7) may edit `ui/tk_pairs.py` (`flags_form` only) and `ui/tk_tabla.py`, and add at most one public helper to `ui/theme.py` (no style).
- **`penwatch.py` must not change one byte** and **`runsync.py` is untouched**: `git diff --stat -- penwatch.py runsync.py` prints nothing in every task.
- **Names tests replace stay module-level and are looked up at call time:** `tk_install.working`, `tk_install.output_window`, `tk_crypto.working`, `tk_equipo.working`, `tk_equipo.escritorio`, `tk_fleet.mostrar`, `tk_fleet.working`, `tk_pairs.mostrar`, `device.list_volumes`, `crypto.medir_escritura`, `deploy.publish_fleet_note`, `fleet.leer`, `watch.consulta`, `segundo_plano.lanzar`. A function handed to a thread is the module attribute read when the step is built (`partial(crypto.medir_escritura, …)`), so a test that replaced it before the step was built is obeyed.
- **What the timing driver finds stays as it is:** the button texts «Parejas…», «Ajustes…», «Sincronizar ahora», «Dispositivos…», «Mostrar», «Editar flags…», «Siguiente»; the sidebar labels of «Ajustes»; `dlg.sondeo` (with `_encargo` and `_mirar()`) and `dlg.tabla` on «Dispositivos»; `dlg.lista`, `dlg.editor`, `dlg.indicador` on «Parejas».
- **Safety invariants unchanged:** everything that deletes or rewrites user data still returns an `EditPlan`/`RepairPlan` shown through `tk_pairs.confirmar_plan()`; nothing repairs itself; no `*-mirror` pass runs without `--dry-run` in any test; `fleet.olvidar()` keeps its `askokcancel` + `working()`.
- **Visual changes allowed, and only these:**
  1. Wizard steps whose read leaves the click show it is reading: «Dispositivo» (an empty list with an `Indicador` «Buscando unidades…»), both «Verificación» (an `Indicador` «Comprobando…», the table appears when the read lands), «Carpeta» and the host «Parejas» (the line under the field says «Mirando la carpeta…» and «Siguiente» is off until the examination of what is written lands), the VeraCrypt panel («Midiendo lo que escribe la unidad…» while the probe runs, «Crear y montar» off meanwhile).
  2. «Guardar el config y crear las carpetas» (both routes) shows the `working()` bar while the fleet note is published, instead of a frozen window.
  3. The fleet table hovers its rows if, and exactly as, stage 2's canvas list does («Parejas»).
  4. Distances written as bare integers in code a task rewrites go through `theme.medida()`: identical at 100 %, scaled elsewhere (the card's `(8, 0)`/`(2, 0)` line gaps).
  5. In the «Dispositivos» card the rows keep their place from one device to another (the spec's «etiquetas fijas»): a device whose name fits one line, or without the «Última pasada buena» line, leaves that reserved line empty where it is, instead of everything below moving up and the reserved space collecting at the bottom of the card.
  Everything else is pixel-for-pixel the look at B1.
- **Indirection points:** each new one is a module-level function tests replace, added to the registry in `docs/agents/reference/commands-testing.md`.
- **New Python modules** are listed in a `.claude/rules/*.md` `paths` (`tests/test_reglas_claude.py`); this plan creates no new module under `common/`, `ui/` or `install/`.
- **Both legs, every task, before delivering:**
  - Tk 8.6: `xvfb-run -a -s "-screen 0 1920x1080x24" /usr/bin/python3.12 tests/run_all.py`
  - Tk 9: `xvfb-run -a -s "-screen 0 1920x1080x24" $SCRATCH/runtime-linux64/bin/python3 tests/run_all.py`
  - Known flake under CPU load: `test_avisos_carpeta.py` (inotify timing): re-run it alone before calling it a failure.
- **Timing assertions are never «after N ms»:** loop until the condition holds, bounded at 2 s, or assert the delay handed to `after`. **No `chmod`** to simulate a read-only drive (the sandbox runs as root).
- **Commits:** on `claude/adoring-pascal-5j258r`, one per task, by whoever merges; Spanish message saying what changes for the user (each task gives one); footer lines as in recent commits. **No PR** (the owner opens it), no `VERSION` bump, never a marker that skips CI.

## Parallel build protocol

- **Each builder** works on its own copy: `mkdir -p DIR && git -C /home/user/prdrive archive <base> | tar -x -C DIR` with `DIR = $SCRATCH/e3/<task>/repo`, then `cd DIR && git init -q && git add -A && git commit -qm base` **before editing**; at the end `git add -A && git diff --cached HEAD > $SCRATCH/e3/<task>/cambio.patch` and a short `$SCRATCH/e3/<task>/informe.md` (what changed, test counts on both legs, widget counts it measured, anything it needed outside its files, deviations). A builder edits **only the files its task owns**; if another file must change, it says so in the report instead. The common builder brief of stage 2 (`$SCRATCH/e2/encargo-comun.md`) applies, with `e3` for `e2`.
- **Waves and bases:**
  - **Wave 1** (base B1): Tasks 1–6, independent of each other and of stage 2 Task 14. Merge order: **6, 2, 4, 5, 3, 1** (the build first, it touches no UI; the `Visor` before the screens that sit in it; the timing check last, so its local A/B ran against everything). B1' = B1 + those merges.
  - **Wave 2** (base B2 = B1' + stage 2 Tasks 12–15 merged): Task 7. **Waits for stage 2 Task 14** (Branch A, `ui/tk_tabla.py`).
  - **Wave 3**: Task 8 (close and measure).
- **Known merge hot spots** (all additive; resolve by keeping both sides):
  - `tests/test_install_wizard.py`: Task 4 (header and drive-route sections), Task 5 (crypto and host-route sections). Both set `segundo_plano.lanzar = segundo_plano.en_el_acto`: Task 4 at the top, Task 5 at the start of each section it owns (a harmless duplicate).
  - `tests/test_tk_medidas.py`: Task 2 (the two `visor.horizontal` reads, ~228–230 and ~1036–1037 at `1e339b9`), Tasks 4/5 (wizard sections, only if broken). Task 3 does not edit it.
  - `tests/test_tk_servicio.py`: Task 2 only (~603–605 at `1e339b9`).
  - `docs/agents/reference/provisioning.md`: Task 4 («The steps»), Task 6 («The PyInstaller build», «Platforms»).
  - `docs/agents/reference/commands-testing.md`: Task 1 («Timing check»), Task 6 (commands, registry, CI).
  - `docs/agents/reference/ui.md`: Task 2 (`Visor`), Task 7 (`Tabla`), plus stage 2 Task 14/15.
  - `tests/rendimiento/presupuesto.toml`: Task 1 (new keys), stage 2 Task 15 (its ceilings), Task 8 (ceilings).
  - `.claude/rules/provisioning.md`: Task 6 only.

## Review Focus

1. **No wizard step lets «Siguiente» act on a stale read.** A volume list that lands after a path was typed by hand does not replace the hand choice; an examination that lands for an older text is dropped; «Crear y montar» stays off while the write probe runs; «Siguiente» on «Carpeta» is off between a keystroke and the examination of that very text. Tests: Task 4 «la lista que llega tarde no pisa la ruta a mano»; Task 5 «el examen de un texto viejo no cuenta», «no se crea el contenedor mientras se mide».
2. **The installer never imports `tkinter` in its own process to judge the host's Python**, the question runs with `-I`, `stdin=DEVNULL`, a time limit and `CREATE_NO_WINDOW`, and a host Python that does not answer is said, not hung on. Tests: Task 6, `tests/test_install_device.py` new cases.
3. **A `.exe` without Tk 9 and SVG is never published.** `build_installer.comprobar_tk()` refuses Tk < 9 before compiling, and the release job runs `--autoprueba` on the built `.exe` and stops before `gh release create` if it fails. Tests: Task 6 (`tests/test_build_installer.py`, `tests/test_autoprueba.py`) and the first `instalador.yml` run.
4. **The `Visor` reserves the same strip without the horizontal bar**, and content wider than the viewport still gets one. Test: Task 2, `tests/test_tk_visor.py`, plus the `test_tk_medidas.py` matrix unchanged.
5. **«Dispositivos»' reserved card fits every device without painting one card per device**, and choosing a row creates no widget. Tests: Task 3 (`tests/test_tk_flota_vista.py`) and the existing fleet walk in `tests/test_tk_medidas.py`.
6. **The canvas `Tabla` keeps every contract its callers and tests read** (`filas`, `orden`, `elegida`, `cabeceras`, `al_elegir()` without arguments, `elegir(iid, avisar)`, `marco`, `grid()`), draws its first layout before the window is uncloaked, keeps the `Visor`'s wheel and the arrow keys. Tests: Task 7.
7. **Counts are deterministic:** `widgets.dispositivos` does not depend on the number of devices; `widgets.flags` on nothing but the selected pair; `widgets.agente` is 11 on both systems.
8. **`penwatch.py` and `runsync.py` untouched**; `test_instancia_unica.py`, `test_auto.py`, `test_start.py` pass unchanged.

---

## Wave 1 (base B1)

### Task 1: The timing check measures «Dispositivos», the flags editor and a wizard step

The check today never opens «Dispositivos» or the flags editor, and drives the wizard only to its first paint, so none of this stage's screens has a deterministic ceiling. This task adds them, measured on both trees.

**Files:**
- Modify:
  - `tests/rendimiento/driver.py`
  - `tests/rendimiento/correr.py` (`PLAN`: `("flota", 5, "1.0")`; `PLAN_CAPTURAS`: the same entry; `ESPERADOS["flota"] = ("open-dispositivos", "llega-flota", "open-flags")`; `ESPERADOS["wizard"]` gains `"paso-dispositivo"`)
  - `tests/rendimiento/informe.py` (`ETIQUETAS`, `cuentas()`)
  - `tests/rendimiento/presupuesto.toml` (new keys only; see below)
  - `tests/test_rendimiento_informe.py`
  - `docs/agents/reference/commands-testing.md` («Timing check»)

**Interfaces:**
- **New patch** `PARCHES["common.fleet"] = _parche_fleet`: replaces `fleet.leer(raw_local=None)` with a function that waits on `ESTADO["flota"]` (a `threading.Event`, 60 s at most) and returns `(FLOTA_DE_MUESTRA, None)`. `FLOTA_DE_MUESTRA` is built inside the patch from the tree's own `m.Dispositivo`/`m.Equipo` with only the fields both trees have (`id`, `nombre`, `version`, `plataformas`, `last_seen`, `last_result`, `equipos`, `ultima_buena`; 0.7.1's `common/fleet.py:152-159`): **12 devices**, deterministic, with 0 to `MAX_EQUIPOS` (5) equipos, one stale for a week (`apagado`), three failing with a long `last_result` («fallo en a, b, c…» long enough to wrap at 440 design px), one whose id is this device's (`fleet.device_id()` of the sample device). The driver sets the event at the end, like `ESTADO["catalogo"]`.
- **Flow `flota`** (sample device with 5 pairs, 100 %): after the first paint, `llega_instantanea(root)` (add `"flota"` to its flow list), then with the catalogue `Event` **held for the whole flow**:
  1. click «Parejas…»; in its `on_shown`, clear `ESTADO["flota"]`, set `HOOK["on_shown"]` to the fleet handler, take `t_req`, invoke «Dispositivos…» (`find_button(dlg, "Dispositivos…")`);
  2. fleet handler (`_wait_window` of the fleet dialog): record `open-dispositivos` = `t − t_req` with `medir(fdlg)`; `shot("dispositivos", fdlg)`; set `ESTADO["flota"]`; sleep (no `update()`) until `fdlg.sondeo._encargo.hecho` or 5 s; time `fdlg.sondeo._mirar(); fdlg.update()` as `llega-flota` with `medir(fdlg)`; `shot("dispositivos-llena", fdlg)`;
  3. back in the «Parejas» handler: invoke «Mostrar» (the editor's «Avanzado»), `dlg.update()`, set `HOOK["on_shown"]` to the flags handler, take `t_req`, invoke «Editar flags…»;
  4. flags handler: record `open-flags` with `medir(fdlg)`; `shot("flags", fdlg)`.
  A missing button sets `NOTES["error"]` with which one; a disabled «Editar flags…» (an editor that is read-only) is an error too.
- **Flow `wizard`**, after `start-wizard`/`apply-wizard`: `root.update()`, `t0`, invoke «Siguiente» (`find_button(root, "Siguiente")`; «¿Dónde?» allows it with its default «En una unidad»), `root.update()`, record `paso-dispositivo` with `medir(root)`. The real `device.list_volumes()` of the runner runs: in the click on 0.7.1 and B1, in a thread after Task 4.
- **`informe.py`:**
  - `ETIQUETAS` (in this order, after `reabrir-parejas`): `open-dispositivos` «Abrir «Dispositivos»», `llega-flota` «Llegan las notas de la flota a «Dispositivos»», `open-flags` «Abrir el editor de flags»; after `apply-wizard`: `paso-dispositivo` «Asistente: pasar al paso «Dispositivo»».
  - `cuentas()`: `open-dispositivos` → `tema.abrir.dispositivos`, `estilos.dispositivos`; `llega-flota` → `widgets.dispositivos` (the count after the notes land: it is the one that grows with devices); `open-flags` → `widgets.flags`, `tema.abrir.flags`, `estilos.flags`. None carries `.p5`/`.p50`.
- **`presupuesto.toml`:** `[techo]` for `widgets.dispositivos`, `widgets.flags`, `tema.abrir.dispositivos`, `tema.abrir.flags`, `estilos.dispositivos`, `estilos.flags` at the values the **PR tree at B1** gives (measured locally, they are deterministic and system-independent; say them in the report); `[meta]` `widgets.dispositivos = 35`, `widgets.flags = 34`, `tema.abrir.dispositivos = 0`, `tema.abrir.flags = 0`, `estilos.dispositivos = 0`, `estilos.flags = 0`. No `[meta_ms]` (the spec has no target for these moments): they are reported without one.

- [ ] **Step 1:** `python3 tests/test_rendimiento_informe.py`. New key assertions: the four new moments are in `ETIQUETAS` order; `llega-flota`'s widgets become `widgets.dispositivos` and `open-flags`'s `widgets.flags`, without `.p5`; a moment only the PR has reads «nuevo»; `widgets.flags` above its ceiling fails.
- [ ] **Step 2: Both trees reach every new moment.**
  - Run: `xvfb-run -a -s "-screen 0 1920x1080x24" python3 tests/rendimiento/correr.py --pr . --base $SCRATCH/mainsrc --trabajo $SCRATCH/e3/t1/rend --python $SCRATCH/runtime-linux64/bin/python3 --rondas 2` (`$SCRATCH/mainsrc` is 0.7.1).
  - Expected: exit 0 or only time verdicts; `open-dispositivos`, `llega-flota`, `open-flags`, `paso-dispositivo` have a value in **both** trees; no «falta»; no `_notes` error; the counts above are printed.
  - Then `--capturas` once and look at `pr-flota-*` PNGs: the fleet with 12 rows and its card, the flags editor with its table.
- [ ] **Step 3:** Docs («Timing check»: the `flota` flow, the synthetic fleet, the wizard step). Commit «La comprobación de tiempos mide también «Dispositivos», el editor de flags y el paso a «Dispositivo» del asistente».

**Budget:** none; it is the yardstick for Tasks 2–7. Expected Windows effect: ~+1 minute per `rendimiento` run.

### Task 2: The agent's question in 11 widgets, and the `Visor`'s horizontal bar only when needed

**Files:**
- Modify:
  - `ui/tk.py`: `Visor` and `cuerpo_visible` only.
  - `ui/tk_agente.py`: `construir` only.
  - `tests/test_tk_medidas.py` and `tests/test_tk_servicio.py`: only the lines that read `visor.horizontal` (at `1e339b9`: `test_tk_medidas.py` ~228–230, ~1036–1037; `test_tk_servicio.py` ~603–605; grep B1 for any other `visor.horizontal`/`.horizontal.grid_info` and convert it too).
  - `tests/test_unidad_nueva.py` (the window section: new structural assertions).
  - `docs/agents/reference/ui.md` («Theme, icons, window sizing»: the `Visor` paragraph).
- Create: `tests/test_tk_visor.py`.

**Interfaces:**
- **`Visor`:**
  - `self.horizontal` is `None` until content is wider than the viewport; `_revisar()` creates it then (same options as today, `ttk.Scrollbar(self.marco, orient="horizontal", command=…)`) and grids it; from then on it behaves as today (shown or `grid_remove`d).
  - The strip stays reserved from the start: `self.marco.rowconfigure(1, minsize=self.vertical.winfo_reqwidth())` (the bar's thickness; a test pins it equal to a horizontal bar's `winfo_reqheight()` on both Tks).
  - `_mover(0, …)` tells the bar only if it exists.
  - `barras() -> tuple[bool, bool]`: whether the vertical bar is gridded, and whether the horizontal one exists and is gridded. Tests read this instead of `visor.horizontal.grid_info()`.
- **`cuerpo_visible(ventana, directo: bool = False, **opciones)`:** with `directo=True` the options go to `visor.interior` itself (`interior.configure(**opciones)`), no `columnconfigure`/`rowconfigure` is set on it (the caller lays out its own columns; today's `interior.columnconfigure(0, weight=1)` would stretch the mark's column) and the interior is returned: one frame fewer. Default unchanged.
- **`tk_agente.construir(root, nombre, segundos, responder, cambiada=False) -> dict`** draws, straight into `cuerpo_visible(root, directo=True, padding=(theme.E5, theme.E5, theme.E5, theme.E4))`: the mark (row 0, `rowspan=2`, column 0, `sticky="nw"`, `padx=(0, theme.E3)`), the title (row 0, column 1, `columnspan=3`), the explanation (row 1, same columns, `pady=(theme.E1, 0)`, `wraplength=theme.medida(400)`), the countdown note and the «Ahora no vale…» note (rows 2 and 3, `columnspan=4`, the same `pady` and `wraplength` as today), «Ahora no» (row 4, column 2, `padx=(0, theme.E2)`) and «Atender» (row 4, column 3), all of row 4 with `pady=(theme.E5, 0)`; column 1 has `weight=1`. No `arriba`, no `cabecera` frame, no `pie`. The returned keys are the same (`marco` is the interior). Widgets: `Visor` 4 (`marco`, `lienzo`, `vertical`, `interior`) + 7 = **11**.

- [ ] **Step 1: The bar.**
  - Run: `xvfb-run -a /usr/bin/python3.12 tests/test_tk_visor.py` and the same with the runtime.
  - Key assertions: a fresh `Visor` has `horizontal is None` and row 1's minsize equals a horizontal `ttk.Scrollbar`'s `winfo_reqheight()` in the same interpreter (create one in the test, after `theme.apply()`), so the reserved strip, and with it the window's requested size, is what it was; content wider than the viewport creates the bar, grids it, and `barras()` reads `(…, True)`; narrowing the content `grid_remove`s it (`(…, False)`), it is not destroyed; `_desplazar(0, "moveto", "0.5")` moves the interior and tells the bar; creating the bar after the window is shown sends no `<<ThemeChanged>>` and creates no ttk style (`ttk::style theme styles` count unchanged).
- [ ] **Step 2: The question.**
  - Key assertions (`tests/test_unidad_nueva.py`): `construir()` leaves 11 descendants under the root (both legs); the buttons still answer `ATENDER`/`AHORA_NO`; the note shows `cuenta(120)`; the mark's top equals the title's top; the explanation starts at the title's left and right below it; «Atender»'s right edge equals the content's right edge minus the padding; «Ahora no» is left of «Atender» with a gap of `E2`.
  - **Parity (in the report, not a test):** capture today's window (B1) and the new one with ImageMagick `import` under xvfb at `tk scaling` 1.333 and 2.0, light and dark (`PRDRIVE_TEMA`), and compare: 0 differing pixels expected; any difference is explained or fixed.
- [ ] **Step 3:** `tests/test_tk_medidas.py`, `tests/test_tk_servicio.py`, `tests/test_tk_ensenar.py` pass on both legs with `barras()`. Docs (the `Visor`: the strip is reserved, the bar is created when needed; `cuerpo_visible(directo=)`). Commit «La pregunta del agente se dibuja con menos piezas, y ninguna ventana crea la barra horizontal hasta que la necesita».

**Budget:** `widgets.agente` 16 → 11; every window that sits in a `Visor` −1 widget (`widgets.main.*`, `widgets.parejas.*`, `widgets.ajustes.*`, `widgets.wizard`, «Dispositivos», flags editor). Expected Windows effect: −3…−8 ms on the agent's question; negligible elsewhere.

### Task 3: «Dispositivos» — the card in place, no card per device to measure it

**Files:**
- Modify: `ui/tk_fleet.py` (`open_dialog` and what it draws; `ficha()`, `fila()`, `fecha()`, `ultimo_equipo()`, `marca()`, `ultima_pasada()` keep their contracts), `tests/test_tk_screens.py` (fleet sections only, only if broken), `tests/test_tk_segundo_plano.py` (fleet section only, only if broken), `docs/agents/reference/fleet.md`.
- Create: `tests/test_tk_flota_vista.py`.

**Interfaces:**
- **The card is a fixed set of labels**, built once when the dialog is built (it starts hidden, as today when nothing is chosen) and filled with `configure()` for the chosen device: the name (`Card.Fuerte.TLabel`, `wraplength=theme.medida(460)`), the short id (`Card.MonoPista.TLabel`), one rótulo per `ROTULOS_FICHA` (`Card.Rotulo.TLabel`), «Versión» and «Para» (one line each), «Estado» (two labels: the result, and the pista line, empty when there is none), «Equipos» (`fleet.MAX_EQUIPOS` text labels, always, as today's reserve lines, `" "` when unused; date labels created up to the most dates any device of the current fleet has, `""` when unused). Same columns, styles (each line's style follows `Linea.pista`, as today), `wraplength` and gaps as `pintar_ficha()` today (`ui/tk_fleet.py:295-323` at `1e339b9`), with the gaps written `theme.E2`/`theme.medida(2)` (allowed visual change 4); **the rows are fixed** (name and id; «Versión»; «Para»; «Estado» ×2; «Equipos» × `MAX_EQUIPOS`), so a section never moves when another device is shown (allowed visual change 5). Date labels are created when a fleet needs more than exist, and never destroyed; an optional label with nothing to say (the second «Estado» line, an unused date) is `grid_remove`d, so it neither shows nor counts as on screen for `tests/_vista`.
  - A small draw-only helper class (e.g. `Ficha(padre)` with `marco`, `poner(disp, equipo_aqui)`, `reservar(flota, equipo_aqui)`) keeps it readable; `ficha()` stays the one pure description and is what `poner()` draws.
- **`reservar(flota)` measures labels, not cards:** for each device it configures the labels of each card row with that device's texts and reads their requested size; it sets each card row's and column's `minsize` to the largest (plus the row's gaps), then shows the chosen device. Because the rows are fixed, the card's size is the sum of those row minimums: there is no whole-card size to measure. **Step 1 decides how the size is read:** if `label.configure(text=…)` updates `winfo_reqwidth()/winfo_reqheight()` with no `update_idletasks()` on both Tks, use that (no idle pass at all); if not, fill the labels once with the per-row worst case (the text that needs most lines, then the widest) and run **one** `update_idletasks()` per arrival. Never one per device, and never a widget created to measure.
- **The rest in place:** the header chip is replaced only when its `(text, type, icon)` changes; the empty-fleet sentence (`SIN_NOTA`) is created the first time the fleet is empty (same cell: `marco` row 2); `acciones` and `cierre` become one footer frame with the same cells (`Cerrar` `sticky="e"`), or stay as they are if the builder finds a pixel difference.
- `dlg.tabla`, `dlg.indicador`, `dlg.sondeo` keep their names; add `dlg.ficha` (the helper) for tests. `open_dialog()` still returns `None`.
- The table stays `tk.Tabla` here; Task 7 changes what draws it.

- [ ] **Step 1: How label sizes are read.** A probe script (in the report, not committed) on both Tks: a `ttk.Label` with `wraplength` gets a longer text; is `winfo_reqheight()` updated before any idle pass? Record the answer and the chosen path.
- [ ] **Step 2: The view.**
  - Run: `xvfb-run -a /usr/bin/python3.12 tests/test_tk_flota_vista.py` and the same with the runtime.
  - Key assertions, with `fleet.leer` replaced and `segundo_plano.lanzar = segundo_plano.en_el_acto`:
    - after arrival, the dialog's widget count is the same with 3 and with 25 devices (fleets with the same maximum of dates), and is reported;
    - choosing every row in turn creates and destroys no widget (the set of widget objects is identical) and, for each device, `tests/_vista.leer_vista(dlg.ficha.marco)` equals that of a fresh dialog opened with a one-device fleet holding that device;
    - `reservar()` creates no widget, and calls `Misc.update_idletasks` at most once per arrival (counter on the class method) — zero if Step 1 found sizes synchronous;
    - a «Releer» bringing a longer «Estado» grows the reserve (`dlg.visor.crecer` path), as today.
- [ ] **Step 3: What already holds.** `tests/test_tk_screens.py` fleet sections (the card is the chosen one; quitar on/off; the empty fleet's sentence at `marco` row 2), `tests/test_tk_segundo_plano.py` fleet section (slow fleet: indicator, chip, buttons off; arrival fills), `tests/test_tk_medidas.py` fleet walk at 1080p 100 % and 200 % («ninguna ficha queda cortada», «lo que pide la ventana no cambia al elegir otra»): unchanged, both legs.
- [ ] **Step 4:** Docs (`fleet.md`: the card is fixed labels; its size is measured on those labels, never one card per device). Commit «Dispositivos ya no pinta una ficha por equipo para medirse: la ficha se rellena en su sitio».

**Budget:** «Llega la flota» −30…−60 % on Windows with 12 devices (12 card paints and their idle passes go); choosing a row configures ~20 labels instead of destroying and creating ~15. `widgets.dispositivos` barely moves here (≈ 131 with 12 devices: the 7 widgets per row are what grows, and Task 7 removes them); the fixed card is ~18 + one per date, against 15–17 today.

### Task 4: The wizard, drive route — reads after painting, steps within 40 widgets

**Files:**
- Modify: `ui/tk_install.py` (the steps listed below; `Wizard` gains one attribute), `tests/test_install_wizard.py` (header and drive-route sections), `tests/test_tk_medidas.py` (wizard sections, only if broken), `docs/agents/reference/provisioning.md` («The steps»).
- Create: `tests/test_tk_asistente.py`.

**Interfaces:**
- **«Dispositivo» (`_paso_destino`):**
  - The step paints its `Treeview` empty with an `Indicador(cuerpo)` «Buscando unidades…» under the card, then `segundo_plano.lanzar_sin_repetir("unidades", None, device.list_volumes)` waited on by a `Sondeo` hung off the step's card frame. «Actualizar lista» is off while reading and reads the same way.
  - On arrival: fill the tree and hide the indicator. **If a path was chosen by hand meanwhile** (a «Usar esta ruta» after the read started wins), leave the tree without selection and do not call `mostrar()`: it reads the tree's selection and would set `wiz.state.device = None` (`ui/tk_install.py:870-882` at `1e339b9`). Otherwise restore the selection of `wiz.state.device` if it is listed and run `mostrar()` (which runs `revisar_desvio()`). Then `wiz.revisar()`. A read that raised says why in the indicator (`Aviso.`) and leaves the tree empty.
  - «Usar esta ruta»: `device.volume_for(destino)` (it calls `list_volumes()`, `install/device.py:388-407`) runs the same way; the choice applies on arrival if the text is still the one asked about.
- **«Comprobaciones» (`_paso_comprobaciones`):** `_filas_python(wiz)` no longer runs on the Tk thread: the `trabajo()` that `working()` already runs computes `device.check_python()` too and the result is kept in **`Wizard.python_equipo: device.Check | None`** (documented in the class docstring); painting the step again uses the kept one (or a «sin comprobar» row when there is none). On the host route it is still `[]`.
- **«Parejas y configuración» (`_paso_parejas.guardar`):** the config and folders are written as today (local, synchronous); `deploy.publish_fleet_note(...)` goes into `working(wiz.root, "flota", partial(deploy.publish_fleet_note, wiz.rclone, wiz.device_root, wiz.perfil.endpoint_catalog), "Apuntando el dispositivo en la flota del remoto.")`; a failure of `working()` itself reads as «no se ha podido apuntar» (best effort, as today).
- **«Verificación» (`_paso_final.revisar_dispositivo`):** a module-level function without Tk, `comprobaciones_dispositivo(raiz, elegidas, clave, cifrado, unidad) -> list[tuple[str, bool | str | None, str]]`, does `device.verify_device()` plus, with VeraCrypt, `vestibulo.comprobar`, `traveler.comprobar`, `crypto.comprobar_restos` (today's body, `ui/tk_install.py:1839-1858` at `1e339b9`); it runs through `segundo_plano.lanzar` and a `Sondeo` hung off the step's table frame; an `Indicador` «Comprobando el dispositivo…» shows meanwhile; «Volver a comprobar» is off while reading; on arrival `tabla_estado(...)` is drawn and `wiz.reencajar()`. «Llevar VeraCrypt…» re-runs it the same way.
- **Widgets (R5, ≤ 40 per step body, counted as the descendants of `wiz.cuerpo`):**
  - «Conexión»: the «Importar de un rclone.conf» form is built the first time that card is chosen (R2); its variables stay where they are, so switching back and forth keeps what was typed.
  - «Instalación» and «Plataformas» (`_lista_plataformas`): no frame that only groups (`radios`), no empty header label; any further trim keeps the look (the builder measures and says which). With today's four platforms, ≤ 40.
  - «Verificación»: `tabla_estado` stays ttk (spec R3: its detail wraps); its cost is bounded instead: **≤ 6 + 4 per check row** (name, chip, detail and the separator).
- Nothing in `install/` changes in this task (`device.check_python()` keeps its signature; Task 6 changes its body).

- [ ] **Step 1: Reads leave the Tk thread.**
  - Run: `xvfb-run -a /usr/bin/python3.12 tests/test_tk_asistente.py` and the same with the runtime.
  - Key assertions, building the real wizard (`tk_install.build`) with the fixtures of `tests/test_install_wizard.py` (profile, catalogue, a temp device): with `device.list_volumes`, `device.volume_for`, `device.check_python`, `device.verify_device` and `deploy.publish_fleet_note` replaced by recorders of `threading.get_ident()` and the real `segundo_plano.lanzar`, none runs on the main thread (loop until done, bounded at 2 s); with a never-ending `Encargo`, «Dispositivo» shows its indicator, an empty tree, «Actualizar lista» and «Siguiente» off, and «Verificación» its indicator and «Volver a comprobar» off; «la lista que llega tarde no pisa la ruta a mano»: a hand path chosen while the list reads is still `wiz.state.device` after the list lands; the fleet note goes through `tk_install.working` (recorded title «flota»); a step change while a read is in flight leaves no pending `after` of that step (`after info`).
- [ ] **Step 2: Widget budget.** Same file: every step of `PASOS_INSTALACION`, `PASOS_ACTUALIZACION` and `PASOS_PLATAFORMAS` (the audit's set-up: the fixtures above, 5 catalogue pairs, two selected, `en_el_acto`) has ≤ 40 descendants under `wiz.cuerpo`, except «Verificación», which has ≤ 6 + 4 × rows; print each count. «Conexión»: choosing «Importar…» builds its form once, switching back keeps it, and the text typed in either form survives a round trip.
- [ ] **Step 3: What already holds.** `tests/test_install_wizard.py` (sets `segundo_plano.lanzar = segundo_plano.en_el_acto` at the top, with the `working_directo` block) and the wizard sections of `tests/test_tk_medidas.py` pass on both legs; every assertion that was there still holds.
- [ ] **Step 4:** `git diff --stat -- penwatch.py runsync.py install/` prints nothing. Docs («The steps»: what each step reads after painting; the fleet note in `working()`). Commit «El asistente ya no se queda parado mientras busca unidades, comprueba Python, verifica el dispositivo o apunta la unidad en la flota».

**Budget:** wizard steps ≤ 40 widgets (Conexión 41 → ~33; Instalación 42 → ≤ 40; Plataformas 39 → ≤ 37); `paso-dispositivo` paints in 30–80 ms on Windows whatever the volumes; the fleet note no longer freezes the window for up to 45 s.

### Task 5: The wizard, host route and encryption — reads after painting

**Files:**
- Modify: `ui/tk_equipo.py`, `ui/tk_crypto.py`, `tests/test_install_wizard.py` (crypto and host-route sections only), `docs/agents/reference/host-root.md` («Wizard route»), `docs/agents/reference/veracrypt.md` (the write probe).
- Create: `tests/test_tk_equipo_lecturas.py`.

**Interfaces:**
- **The write probe (`tk_crypto._panel_veracrypt.refrescar_espera`):** `crypto.medir_escritura(estado.device)` (8 MiB plus `fsync`, `install/crypto.py:469-503`) runs through `segundo_plano.lanzar_sin_repetir(("sonda", str(estado.device)), None, partial(crypto.medir_escritura, estado.device))` with a `Sondeo` hung off the panel; meanwhile `espera` says «Midiendo lo que escribe la unidad…» and «Crear y montar» is off (the probe writes beside where the container goes); on arrival `estado.velocidad_escritura` is set (`0.0` when it failed, as today) and the division is redone. A dynamic container never starts the probe (as today). Typing a size recomputes only the division.
- **Examinations per keystroke (`tk_equipo`):** `paso_carpeta.revisar`, `_carpeta_cifrada.revisar`/`revisar_punto` and `paso_parejas.revisar_fila` (`raiz_equipo.examinar`, `examinar_contenedor`, `revisar_local`) are **debounced** (`ESPERA_TECLA_MS = 250`, one pending `after` per field, re-armed by each keystroke) and run through `segundo_plano.lanzar` with a `Sondeo` per field; on each keystroke the field's dependent state is cleared at once (`wiz.state.device_root = None` for «Carpeta», the button off for the container, the pair's line «Mirando…»), and `wiz.revisar()` turns «Siguiente» off; an arrival is applied **only if the field still holds the text examined** (`entrada.get()` then, not the text `validatecommand` saw). The first examination when the step paints is launched at once, without the debounce, through the same thread path. `ESPERA_TECLA_MS` is read at call time: the host-route sections of `tests/test_install_wizard.py` set it to 0 and their `escribir()` helper (`~1018` at `1e339b9`) runs `entrada.update()` after typing, so `en_el_acto` makes the step behave as today.
- **Writes and checks:** the host «Parejas» `guardar()` publishes the fleet note through `working()` like Task 4; its `revisar_local()` calls for the selected pairs stay synchronous (they are the check before a write, on a click). **«Verificación» (`paso_final.revisar`):** `comprobaciones(...)` (already a function without Tk: `schtasks` via `watch.consulta`, D-Bus via `escritorio()`, files) runs through `segundo_plano.lanzar` with an `Indicador` «Comprobando lo instalado…», «Volver a comprobar» off meanwhile; the table is drawn on arrival.
- **Widgets:** the host-route steps (the audit's set-up) stay ≤ 40, except «Verificación» (≤ 6 + 4 per check row, as Task 4).

- [ ] **Step 1: The probe.**
  - Run: `xvfb-run -a /usr/bin/python3.12 tests/test_tk_equipo_lecturas.py` and the same with the runtime.
  - Key assertions: with `crypto.medir_escritura` replaced by a recorder of `threading.get_ident()` and the real `lanzar`, it never runs on the main thread; with a never-ending `Encargo`, «Crear y montar» is disabled and `espera` says it is measuring — «no se crea el contenedor mientras se mide»; on arrival it is enabled when the examination allows it, and the estimate is the division; typing a size five times starts no second probe (one recorded call).
- [ ] **Step 2: Keystrokes.**
  - Key assertions: five keystrokes within the debounce give one examination, of the last text (wrap `ventana.after` to assert the 250 ms delay; never «N calls in M ms»); «el examen de un texto viejo no cuenta»: an examination that lands after the field changed does not set `wiz.state.device_root` and does not enable «Siguiente»; with `en_el_acto` and the timer run by hand, the step behaves as today (same examen text, same `device_root`).
- [ ] **Step 3: Verificación and budget.** Same file: `tk_equipo.comprobaciones` (replaced by a thread recorder) never runs on the main thread; the table appears on arrival; widget counts of every step of `PASOS_EQUIPO` and `PASOS_EQUIPO_SOLO` printed and within the budget above.
- [ ] **Step 4: What already holds.** `tests/test_install_wizard.py` crypto and host-route sections (they set `segundo_plano.lanzar = segundo_plano.en_el_acto` at the start of each section) and the host-route sections of `tests/test_tk_medidas.py` pass on both legs. Docs. Commit «En este equipo, el asistente examina las carpetas y comprueba lo instalado sin quedarse parado, y mide la unidad sin bloquear la ventana».

**Budget:** no keystroke and no first paint waits for a folder walk, a `schtasks`, D-Bus or an 8 MiB write (0.1–5 s on a USB stick, today on the Tk thread when the drive cannot hold sparse files).

### Task 6: The installer on Python 3.14.8, Tk 9.0.4 and a pinned PyInstaller

**Files:**
- Modify:
  - `build_installer.py` (`PYINSTALLER`, `comprobar_pyinstaller()`, new `comprobar_tk()`, `main()`)
  - `prdrive-install.py` (new `--autoprueba RUTA`, `cmd_autoprueba()`)
  - `install/device.py` (`check_python()` body; new `preguntar_python()`)
  - `install/runtime_bin.py` (`extract(..., podar: bool = True)` keyword only)
  - `tests/_runtime_ci.py` (new subcommand `compilador`)
  - `.github/workflows/build-installer-release.yml`
  - `tests/test_install_device.py`, `tests/test_runtime_bin.py`
  - `.claude/rules/provisioning.md` (paths: the two workflows, the composite action, the two new tests)
  - `docs/agents/reference/provisioning.md` («The PyInstaller build»), `docs/agents/reference/updating.md` (the release gate), `docs/agents/reference/commands-testing.md` (commands, registry, CI), `docs/guia/instalacion.md` («Un ejecutable…»)
- Create: `.github/actions/compilar-instalador/action.yml`, `.github/workflows/instalador.yml`, `tests/test_build_installer.py`, `tests/test_autoprueba.py`.

**Interfaces:**
- **`build_installer.PYINSTALLER = "6.22.3"`** with a docstring giving the facts above (3.14 since 6.15.0; Tcl/Tk 9 with embedded data since 6.22.0; 6.22.3 published 2026-09-12). `comprobar_pyinstaller()` also refuses another version: `SystemExit` naming the pin and `python -m pip install pyinstaller==6.22.3`.
- **`build_installer.TK_MINIMO = (9, 0)`; `comprobar_tk() -> str`:** imports `tkinter` in the build process (it is the interpreter PyInstaller bundles), compares `tkinter.TkVersion` and returns `Tcl().eval("info patchlevel")`; below 9.0 it raises `SystemExit` explaining that the `.exe` carries the Tk of the Python that builds it and must be built with the pinned python-build-standalone 3.14.8 (Tk 9.0.4). `main()` calls both checks before `escribir_secreto()` and prints the Python and Tk versions.
- **`prdrive-install.py --autoprueba RUTA`** → `cmd_autoprueba(ruta) -> int`: never opens a visible window and never calls `report()` (a windowed `.exe` has no stdout, and `--probe`/`--check` open a report window and wait in `mainloop()`: they cannot run in CI). In a `try` per item, it writes `RUTA` (UTF-8 JSON) with: `python` (`platform.python_version()`), `congelado`, `tk` (patchlevel), `tk9` (`TkVersion >= 9`), `svg` (`icons.svg_disponible(root)` on a withdrawn `Tk()`), `tema` (`theme.apply(root)` without error), `letra` (the family the theme resolved for body text: the bundled Noto Sans when `ui/fuentes/` travelled), `pintadas_python` (`icons.PINTADAS` for the Python painter after `apply()`: 0 expected on Tk 9), `asistente` (`tk_install.build(root)` on the withdrawn root, then destroyed), `modulos` (`importlib.import_module` of every module the wizard and its steps import lazily — listed in a constant the builder derives by grepping `ui/tk_install.py`, `ui/tk_crypto.py`, `ui/tk_equipo.py` — each `"ok"` or the error), `datos` (each of `deploy.DEPLOY_FILES`, `deploy.DEPLOY_TREES`, `install.agente.CODIGO_FICHEROS` and `device-readme.md` — what `deploy.write_guide()` copies — present under `install.bundle_dir()`), `python_equipo` (`device.check_python().detalle`, informative), `unidades` (`len(device.list_volumes())`, informative: what `--probe` showed). Exit 0 iff `tk9`, `svg`, `tema`, `asistente`, every module and every data file are fine; else 1; the file is written in both cases (also on an unexpected exception: `{"error": …}`).
- **`install.device.preguntar_python(cmd: list[str]) -> subprocess.CompletedProcess`** (indirection point): runs `cmd + ["-I", "-c", SONDA_PYTHON]` with `stdin=DEVNULL`, captured text output, `timeout=TOPE_PYTHON_S` (10 s) and, on Windows, `creationflags=CREATE_NO_WINDOW`; never raises (a timeout returns `returncode=124`, an `OSError` 127, like `watch.consulta`). `SONDA_PYTHON` prints one JSON line `{"version": [maj, min, mic], "tk": TkVersion or null}` (the `tkinter` import inside a `try`).
- **`check_python(root=None) -> Check`** keeps its signature, labels and `ok` rules, but **never imports `tkinter` in the installer's process**: whenever it relies on the host's Python (`python_command()`), it asks it with `preguntar_python()`. Details: «{orden} (Python 3.12, con Tkinter 8.6)», «…, pero SIN Tkinter: saldrá el menú de consola», «… no ha contestado en 10 s», «… no se ha podido preguntar: …». A host Python older than 3.11 is said («demasiado viejo para la instalación ligera: pide 3.11 o posterior») and, with `root`, makes `ok` false (that device would not start here); without `root` `ok` stays true (the full install brings its own). The device-interpreter branch is unchanged (no subprocess).
- **`runtime_bin.extract(archivo, destino, plat, sha256, podar=True)`:** `podar=False` extracts every member (same validation, same stamp); only the build helper passes it.
- **`python tests/_runtime_ci.py compilador PLATAFORMA DESTINO CACHE`:** Windows platforms only (a Linux runtime has no shared `libpython` for PyInstaller: refuse with a message); the same verified archive as `runtime` (cache, SHA256SUMS), extracted with `podar=False`; `python -m pip --version` or else `python -m ensurepip --upgrade`; checks `Tcl().eval("info patchlevel") == pins.TK_XFT_VERSION` (9.0.4, the runtime's Tk); prints the interpreter and writes `PRDRIVE_PYTHON_COMPILAR` to `$GITHUB_ENV`.
- **`.github/actions/compilar-instalador/action.yml`** (composite; `shell: pwsh` steps; Windows runners): `actions/setup-python@v5` 3.11 (bootstrap only); `python tests/_runtime_ci.py clave`; `actions/cache@v4` of `${{ runner.temp }}/prdrive-cache` with key `runtime-windows-x64-<clave>` (the one `tests.yml` already fills); `python tests/_runtime_ci.py compilador windows-x64 "${{ runner.temp }}/py-compilar" "${{ runner.temp }}/prdrive-cache"`; read the pin with `python -c "import build_installer as b; print(b.PYINSTALLER)"` and `& $env:PRDRIVE_PYTHON_COMPILAR -m pip install --disable-pip-version-check --no-input "pyinstaller==$pin"`; `& $env:PRDRIVE_PYTHON_COMPILAR build_installer.py`; then the gate: `Start-Process dist\prdrive-install.exe -ArgumentList '--autoprueba', "$env:RUNNER_TEMP\autoprueba.json" -Wait -PassThru`, print the JSON, fail if the exit code is not 0 or the file is missing. Output `exe`: the built file. Each step with a time limit.
- **`.github/workflows/instalador.yml`** «Instalador»: `windows-latest`, checkout + the action + `actions/upload-artifact` of the `.exe` and `autoprueba.json`; `on: pull_request` (paths: `build_installer.py`, `prdrive-install.py`, `install/**`, `ui/**`, `common/**`, `sync.py`, `runsync.py`, `penwatch.py`, `agente.py`, `pregunta.py`, `VERSION`, `device-readme.md`, `tests/_runtime_ci.py`, `.github/actions/compilar-instalador/**`, the workflow), `workflow_dispatch`, and a `push` to `claude/adoring-pascal-5j258r` marked `# TEMPORAL: quitar antes del PR`. `permissions: contents: read`.
- **`build-installer-release.yml`:** «Set up Python», «Install build dependencies» and «Build installer executable» are replaced by `uses: ./.github/actions/compilar-instalador` (same `if: publicar`); «Find built executable» and «Create GitHub release» stay; a failed gate stops the job before `gh release create`.
- **`docs/guia/instalacion.md`:** to build, `python -m pip install pyinstaller==6.22.3` with Python 3.14 and Tk 9 (the pinned python-build-standalone; `build_installer.py` refuses Tk 8.6); **the `.exe` needs Windows 10 or later** (said as the supported floor, not as something measured on 8.1).

- [ ] **Step 1: The host's Python.**
  - Run: `python3 tests/test_install_device.py` (and with the runtime).
  - Key assertions: with `device.preguntar_python` replaced: 3.12 + Tk 8.6, no Tk, 3.10 (with and without `root`), rc 124, rc 127 and garbage give the details and `ok` above; the real `preguntar_python([sys.executable])` answers parseable JSON on both legs; the command carries `-I`, `stdin=DEVNULL`, the timeout and, with `IS_WIN` forced, `CREATE_NO_WINDOW` (wrap `subprocess.run` and read its kwargs); in a fresh interpreter, `check_python()` leaves `"tkinter" not in sys.modules`. The existing «sin Python propio ni instalado, no pasa» still holds.
- [ ] **Step 2: The build checks.**
  - Run: `python3 tests/test_build_installer.py` on both legs.
  - Key assertions: `comprobar_tk()` returns `"9.0.4"` on the Tk 9 leg and raises `SystemExit` naming Tk 9 on the Tk 8.6 leg; `comprobar_pyinstaller()` with a fake `PyInstaller` module (in `sys.modules`) of another version raises naming `6.22.3`, of the pinned version passes; `PYINSTALLER` is `X.Y.Z` and ≥ 6.22; `DATOS_FICHEROS` still covers `CODIGO_FICHEROS` (as `test_install_agente.py`).
- [ ] **Step 3: The self-test.**
  - Run: `xvfb-run -a … tests/test_autoprueba.py` on both legs.
  - Key assertions: `python prdrive-install.py --autoprueba F` in a subprocess ends within 60 s, writes `F` with every key above; on the Tk 9 leg exit 0 with `svg` true, `tk9` true, `pintadas_python` 0 and every module and data file `"ok"`; on the Tk 8.6 leg exit 1 with `tk9` and `svg` false, `pintadas_python` above 0, and every module and data file `"ok"`; no window remains (the process ended).
  - `python3 tests/test_runtime_bin.py`: `extract(..., podar=False)` keeps `Lib/site-packages/` and `Lib/ensurepip/` members of a fake Windows archive; the default prunes as before.
- [ ] **Step 4: CI.** After merging, push and read the first `Instalador` run (job log, the uploaded `autoprueba.json`): `python` 3.14.8, `tk` 9.0.4, `svg` true, `letra` the bundled family, exit 0. **This is where 6.22.3 + the pinned runtime is verified.** If PyInstaller fails to collect Tcl/Tk 9 or the self-test fails, the release workflow stays gated (it fails closed, it does not fall back to 3.11), and the finding goes in the report and Open risks.
- [ ] **Step 5:** Docs. Both legs. Commit «El instalador se compila con Python 3.14 y su Tk 9, y se prueba antes de publicarlo».

**Budget:** none in time (the `.exe` start is not measured, §4); it moves the wizard inside the `.exe` to the SVG painter (1b's gains: `theme.apply()` −82 % on Windows) and gives the release a gate it did not have.

---

## Wave 2 (base B2: Wave 1 merged and stage 2 merged; waits for stage 2 Task 14)

### Task 7: `tk.Tabla` on the canvas — «Dispositivos» and the flags editor

**Files:**
- Modify:
  - `ui/tk.py`: `Tabla` (and `SUPERFICIE_FILA` if needed) only; `FilaTabla`, `CeldaTexto`, `CeldaChip`, `CeldaIcono` keep their fields.
  - `ui/tk_tabla.py`: additions only (stage 2 Task 14 owns its design; nothing `tk_pairs.ListaParejas` uses changes).
  - `ui/tk_pairs.py`: `flags_form` only.
  - `tests/test_tk_tabla.py` (a new `Tabla` section), `tests/test_tk_screens.py` (flags and fleet sections, only where they read row widgets), `tests/test_tk_flota_vista.py` (counts), `tests/rendimiento/presupuesto.toml` (`widgets.flags`, `widgets.dispositivos` ceilings down to what this task measures).
  - `docs/agents/reference/ui.md` (`tk.Tabla`), `docs/agents/reference/catalogue.md` («The flags editor»), `docs/agents/reference/fleet.md` (the table line).
- Create: nothing.

**Interfaces:**
- **`ui.tk.Tabla(parent, columnas, al_elegir=None, vacio="", alto_fila=36)`** keeps its signature and what callers and tests read: `marco` (the widget to grid; `marco.winfo_children()` may be empty or hold the canvas), `grid(**k) -> Tabla`, `poner(filas: list[FilaTabla])` (diff by `iid`: a row whose cells and tone are equal is not redrawn), `elegir(iid, avisar=True)` (returns what `TablaLienzo.elegir` returns; callers ignore it), `al_elegir()` called **without arguments**, `filas: dict[str, list[str]]` (cell texts per row, `CeldaIcono.texto` for an icon cell), `orden`, `elegida`, `cabeceras`, `n`; plus `leer() -> list[tuple[str, ...]]` (drawn text per row, in order).
- **Drawn by `tk_tabla.TablaLienzo`** (subclass or wrapper — the builder decides from what Task 14 built). **What `Tabla` needs, to add to `tk_tabla.py` only where Task 14 did not:**
  - cells: text with a role (`Fuerte.`, `Mono.`, `MonoPista.`, `Pista.`), chip (`theme.chip`'s colours via `theme.colores_chip()`, its disc via `icons.disco()`), icon (`icons.get(widget, nombre, 16, theme.OK, fondo)`, as `Tabla._pintar()` today);
  - row tones exactly as `Tabla._pintar()` (`ui/tk.py:1008-1023` at `1e339b9`): surface per `SUPERFICIE_FILA`, `apagado` turns text cells to `Pista.`/`MonoPista.` on the card, the chosen row on `NotaAzul.`;
  - header row of `theme.rotulo(titulo)` in the `Rotulo` role on the paper, 28 design px high, with the hairline under it; rows `alto_fila` high (36 or 30) with today's paddings (`_lados()`, `E2`/`E1`);
  - columns: minimum width `icons.px(parent, ancho)`, growing to their content like today's grid (**no elision** in `Tabla`, unlike «Parejas»' paths), stretch columns taking the extra width;
  - the rounded card border as today: the canvas inside a `Card.TFrame` with `padding=icons.px(parent, 1)` if `TablaLienzo` does not draw the card itself (then `widgets` = 2);
  - `vacio` in `Card.Pista` centred where today's label was;
  - selection only with `al_elegir`: click, ↑/↓ (plus whatever keys Task 14 gave the list), focus ring; no hover, focus or selection without it (the flags table);
  - the wheel over the table scrolls the `Visor` (Task 14's rule);
  - **the first layout is drawn at the size the window will show with, before `ensenar()` uncloaks it**: no debounced `<Configure>` relayout may land after showing on the first open (Review Focus 6).
- **`flags_form`:** the table becomes the canvas `Tabla` (no change in the call); the red notice of `avisar()` is built the first time it is needed and then configured (title, body) or `grid_remove`d, not destroyed and rebuilt (R1). Widget count ≤ 34 with 0, 3 and 10 flags (constant in the number of rows).

- [ ] **Step 1: The gap list.** Read the merged `ui/tk_tabla.py` and `tests/test_tk_tabla.py`; write in the report which bullets above Task 14 already provides and which this task adds. Nothing `ListaParejas` uses may change: `tests/test_tk_parejas_vista.py` and the «Parejas» cases of `tests/test_tk_screens.py` pass unchanged.
- [ ] **Step 2: `Tabla` cases** (`tests/test_tk_tabla.py`, new section, both legs; on Tk 8.6 the disc and icons come from the Python painter):
  - `filas`, `orden`, `cabeceras` and `leer()` after `poner()` equal those of a fleet and a flags table built from today's fixtures (`tests/test_tk_screens.py`'s `FLOTA`, `flags_escritos(...)`);
  - `poner()` of the same rows leaves `find_all()` unchanged; one changed chip changes only that row's items;
  - ↓/↑ and a click at a row's y call `al_elegir()` once with no arguments and move `elegida`; without `al_elegir` nothing is selectable and the table takes no focus;
  - the item coordinates after the first `update_idletasks()` equal those after updating for 100 ms at the same size (no relayout after showing);
  - the wheel over the table scrolls the `Visor`; opening the fleet and the flags editor sends no `<<ThemeChanged>>` and creates no style.
- [ ] **Step 3: The screens.** `tests/test_tk_screens.py` fleet and flags sections, `tests/test_tk_segundo_plano.py` fleet section, `tests/test_tk_medidas.py` fleet walk, `tests/test_tk_flota_vista.py` (constant count, now without the 7 per row): both legs. Counts: `widgets.flags` ≤ 34; «Dispositivos» after arrival reported (expected 41 + one per date shown, ≈ 46 with the sample fleet).
- [ ] **Step 4: Look.** `correr.py --pr . --base <B2> --capturas --rondas 1`: compare `flota` captures of both trees (fleet with 12 rows, card, flags editor); differences limited to the anti-aliasing of chips and, if Task 14's list hovers, nothing at rest. In the report.
- [ ] **Step 5:** Docs. Both legs. Commit «Dispositivos y el editor de flags dibujan sus tablas de una vez».

**Budget:** «Llega la flota» → 20–60 ms with 12 devices on Windows; open the flags editor −40…−120 ms; `widgets.flags` 82 → 26–28; `widgets.dispositivos` constant in N.

---

## Wave 3

### Task 8: Close the stage

**Files:**
- Modify: `tests/rendimiento/presupuesto.toml` (`[techo]`/`[techo.<system>]` from the measured counts: `widgets.agente`, `widgets.wizard`, `widgets.dispositivos`, `widgets.flags`, `widgets.main.*`, `widgets.parejas.*`, `widgets.ajustes.*`, `estilos.*`/`tema.abrir.*` of the new screens, `modulos.*` if they moved), `docs/agents/reference/ui.md` (one coherence pass over what Tasks 2 and 7 touched), the spec («Estado» line: stage 3 done and measured; «Decisiones para revisar» 6: one sentence with what was verified — runtime, Tk, PyInstaller 6.22.3, the gate; R5: one sentence each for the fleet and «Verificación» budgets and why).
- Create: `docs/superpowers/pruebas/2026-10-xx-etapa-3-resultados.md`.

- [ ] **Step 1:** Push. Read the `Tests` run (job `tests`, Linux and Windows, Tk 9 only since 09/10; and `python-minimo`), the `Rendimiento` run (windows-x64, linux-x64) and the `Instalador` run for the pushed sha (GitHub MCP tools; if unavailable, `gh run list/view --log`). A Windows test failure is root-caused as a bug in code or test, never skipped.
- [ ] **Step 2: Ceilings.** Copy the counts the summary marks «techo bajable» into `presupuesto.toml`, Linux and Windows separately for `modulos.*`.
- [ ] **Step 3: Results.** Per moment of this stage (agent's question, wizard and `paso-dispositivo`, `open-dispositivos`, `llega-flota`, `open-flags`) on Windows and Linux: 0.7.1 (the base of the run), stage 3; the deterministic counts; which budgets are met and which are not, with the reason (expected: «Dispositivos» ≤ 35 and «Verificación» ≤ 40 not met with the same look; wizard launch above 300 ms); the installer facts from `autoprueba.json` (Python, Tk, font, SVG) and the `.exe` size.
- [ ] **Step 4:** `python3 tests/test_reglas_claude.py`; both legs. Commit «Etapa 3 medida en Windows y Linux», and push. The temporary `push:` triggers (`tests.yml`, `rendimiento.yml`, `instalador.yml`) stay until the owner opens the PR.

---

## Open risks

1. **«Dispositivos» ≤ 35 widgets is not reachable with the same look.** With the canvas table (1–2 widgets) the window holds the `Visor` and body (5), the header (10), the footer (5–6) and a card of 18 fixed widgets (its reserve frame, «Ficha», its own frame, name, id, 4 rótulos, «Versión», «Para», 2 «Estado» lines, `MAX_EQUIPOS` name lines) plus one label per date shown: **41 + dates, constant in the number of devices** (≈ 46 with the sample fleet; 0.7.1: 33 at open, ≈ 131 with 12 devices after arrival). 35 needs the «Equipos» block as two multi-line labels (names and dates), whose lines then sit 2 design px closer than today's per-line labels (`pady=(2, 0)`), plus one frame fewer in the footer and the card's reserve frame folded into its parent's grid: a visible change, left as an owner decision (D1 below).
2. **Wizard «Verificación» ≤ 40 is not reachable either:** the spec keeps `tabla_estado()` in ttk (R3, «detalle que se parte en líneas»), at 3 widgets per check plus a separator; the host route has ~17 checks (71 widgets). The tests bound it as ≤ 6 + 4 per row instead. Dropping the separators or drawing it on the canvas with wrapped text would meet 40; both change the look or contradict R3 (D2).
3. **Wizard launch ≤ 300 ms (informative) stays out of reach** (389 ms after 1b): `tk_install` imports `install.raiz_equipo`, which imports `crypto`, `deploy`, `device`, `platforms` and `common.fleet` at module level (`install/raiz_equipo.py:44-47`), and `Wizard.__init__` needs it; deferring that chain is a restructuring for stage 4, with `PRDRIVE_PERF=1` data.
4. **PyInstaller 6.22.3 with the python-build-standalone 3.14.8 Windows build is only verified by CI** (Task 6 Step 4). If its Tcl/Tk 9 collection fails there, the release workflow fails closed and the stage ships without a new `.exe` until fixed; the fallback is not Tk 8.6 (the spec wants the SVG path in the wizard).
5. **The release job's own wiring is exercised only at the next `VERSION` push to `main`.** The composite action runs on every `Instalador` run, but the release job's `if:` conditions and outputs around it are only checked by reading.
6. **Only PyInstaller is pinned**; its dependencies (`altgraph`, `packaging`, `pefile`, `pywin32-ctypes`, `pyinstaller-hooks-contrib`, `setuptools`) float within their ranges. A hash-locked requirements file would close it (later; not in the spec).
7. **`check_python()` now starts a process** (Windows: 100–300 ms, up to 10 s on a stuck launcher). It is off the Tk thread in the wizard (Tasks 4/5) and inside `working()` in «Comprobaciones»; `prdrive-install.py --check` pays it in the console.
8. **Debounced folder checks** turn «Siguiente» off for ~250 ms plus the examination after each keystroke on «Carpeta» and the host «Parejas»: a behaviour change to watch in review.
9. **The canvas `Tabla` depends on what Task 14 built.** If `TablaLienzo` was shaped around `ListaParejas` only (fixed columns, no icon cells, elision always on), Task 7 grows; it must not change what `ListaParejas` uses.
10. **The fleet table may hover** (visual change 3) if Task 14's list does.
11. **The timing check's `flota` flow depends on the editor of the first «Parejas» row being editable** (a pair used on the sample device) and on «Mostrar»/«Editar flags…» keeping their texts.
12. **Merge friction:** `tests/test_install_wizard.py` (Tasks 4 and 5), `tests/test_tk_medidas.py` (Tasks 2, 4, 5), `provisioning.md` and `commands-testing.md` (Tasks 1, 4, 6). The «own sections only» rule keeps conflicts textual.

## Decisions for the owner (taken in this plan, to review)

- **D1.** «Dispositivos» keeps the card's look and misses the 35-widget budget by ~6–11 (Open risk 1); the alternative is two multi-line labels for «Equipos» (2 px closer lines) and two frames fewer.
- **D2.** Wizard «Verificación» keeps `tabla_estado()` in ttk and is bounded per row (Open risk 2).
- **D3.** The release gate is a new `--autoprueba RUTA` instead of the spec's `--probe` (a windowed `.exe` opens a report window and waits in `mainloop()` on `--probe`/`--check`, which would hang CI); `--probe` is unchanged.
- **D4.** The `.exe` is built with an **unpruned** copy of the device's own pinned runtime (python-build-standalone 3.14.8) rather than setup-python's 3.14, so the installer runs exactly the Tk the devices run.
- **D5.** The «Dispositivos» card has fixed rows (visual change 5), as the spec's «etiquetas fijas que cambian con configure» implies; keeping today's flowing rows would need either one idle pass per device or reimplementing grid's arithmetic to reserve the card's height.

---

## Appendix: stage 4 («Limpieza»), for its own plan

Two items; their plan is written when stage 3 is measured.

1. **`PRDRIVE_PERF=1`.** Each window writes, to the run log of the device (`logs/`), one line per moment the timing check measures (`start-main`, `open-parejas`, `catalogo-llega`, `marcar`, `sincronizar-ventana`, `open-ajustes`, `pane-*`, `start-agente`, `start-wizard`, `paso-dispositivo`, `open-dispositivos`, `llega-flota`, `open-flags`), timed in the code at the same points the driver uses (`perf_counter` around the click handler and the first `update()`), and nothing when the variable is not set (one module-level check, no import cost). It is what locates the launch budget on the owner's own machine (Open risk 3).
2. **Real-machine rows** (`docs/superpowers/pruebas/`, a new `…-frontend-pendiente-en-real.md`; the `real-machine-tests` skill; cloud rows in `tests/maquina/` where the OS alone can answer):
   - **Cold start from a USB stick** (≈ 80 MB, ≈ 190 files; first open after plugging in, with the OS cache cold): main window and «Parejas» from launch on a real Windows and a real Linux; a person, a stick, a stopwatch (or `PRDRIVE_PERF=1`).
   - **`.pyc` on FAT32 and exFAT between systems** (`checked-hash`, §3): precompile on Linux, open on Windows (and back) and check no `.pyc` is rewritten and imports use them. Cloud candidate: a Linux job builds an exFAT and a FAT32 image with a precompiled `.prdrive/` and uploads it; a Windows job attaches it as a VHD (`diskpart`, `comun.volumen_windows()`), runs the pinned runtime against it and compares `.pyc` mtimes and `sys.flags`/import timings — an `fNN_pyc_entre_sistemas` pair of rows.
   - **The look on a real Windows screen** (light and dark, 100/150/200 %, Windows 10 and 11): every window of stages 1b–3 — main window, «Parejas» (the canvas list), «Ajustes», «Dispositivos» and the flags editor (the canvas `Tabla`), the wizard (including the `.exe` built by Task 6), the agent's question. Today only the cloud VM paints them, without a desktop (F20).

---

## Corrections after review (override the task text)

An adversarial review checked this plan against the code at `992f108` (findings: `$SCRATCH/e3/revision-plan/hallazgos.md`, with file:line references and three Tk probes, `sonda_*.py`; **read your task's entries there too**). Every finding is accepted. Where a correction and the task text disagree, the correction wins. Code line numbers in the findings are at `992f108` (stage 2 Tasks 11 and 12 merged).

### Global

- **BASE for Wave 1 is the tip after stage 2 Task 11** (`992f108` or later, given in each task message). Stage 2 Task 14 (the canvas list, `ui/tk_tabla.py`) is being built in parallel; Wave 1 does not touch `ui/tk_pairs.py`, `ui/tk_tabla.py`, `ui/theme.py` or `ui/icons.py`.
- **Hot spots shared with stage 2 Task 15 (m15):** `tests/rendimiento/*` and `presupuesto.toml`. Task 1 only **adds** keys and flows; Task 15 deletes `etapa2_*.py` and edits existing `[techo]` values. Whoever merges second rebases textually.
- **Review Focus 1 gains** (with their tests): the stale container examination (M2), the second probe write (M3), the late «Usar esta ruta» (M4). **Review Focus 3 gains:** «the release workflow is only rewired after a green `Instalador` run; a red one leaves it untouched» (B1).
- **Budget map (m13):** the «Wizard reads on the Tk thread» cell says «the spec's list: none (small reads on the chosen volume remain: `install_target()` in `revisar_desvio`, `Matriz.para()` and free space, `_paso_cifrado`'s detection, the VeraCrypt panel's `creacion_dispersa`/`sistema_de_ficheros`/`restos_en_claro`/`_libre`, `_carpeta_cifrada`'s `disk_usage`/`creacion_dispersa`/`letras_libres`)». The results file must not claim more.
- **«Verificación» bound (M6):** «fixed part + 4 per check row − 1»; the fixed part is ≤ 13 on the drive route and ≤ 7 on the host route, both counting the `Indicador`. Tests assert that one more check row adds exactly 4 widgets and print both fixed parts. The budget map row and Open risk 2 read accordingly.
- **No visible change beyond the spec's list.** Visual change 5 (fixed card rows) and visual change 3 (hover in the fleet table) are **removed** from the allowed list (M5, m16).

### Task 1 (timing check)

- m18: the `flota` flow also records `elegir-dispositivo` (`fdlg.tabla.elegir(otra)` + `fdlg.update()`, after `llega-flota`), `[meta_ms]` 16; 0.7.1 has the same API.
- n1: the merge-order rationale becomes «the merger re-runs Task 1's Step 2 once on B1′ before Wave 2».

### Task 2 (agent question, lazy horizontal bar)

- No correction: its claims were verified, including scrollbar thickness on both Tks (`sonda_barras.py`: the reserved strip is pixel-identical).

### Task 3 («Dispositivos»)

- **M5: flowing rows, as today.** The fixed set of labels is re-gridded (`grid(row=…)`) per device and unused ones `grid_remove`d; `reservar()` sets `hueco`'s row and column `minsize` from label sizes read synchronously (`sonda_req.py`: a label's `winfo_reqwidth/reqheight` is right after `configure`, no idle pass; a frame's is not), summing `max(reqheight + pady)` per grid row over each device's lines. Step 1's probe stays only as a Windows confirmation.
- m11: Step 2's constancy reads «the dialog's widget count **minus `dlg.tabla.marco`'s descendants** is the same with 3 and 25 devices»; Task 7 Step 3 asserts the whole count.
- m17: take the pixel-identical trims (fold `cabecera`'s frame and `donde` into `arriba`'s grid, `hueco` into `marco`'s grid, `acciones` + `cierre` into one footer; `ui/tk_fleet.py:246-264,282-289,443-461`), with a pixel/`leer_vista` parity check in the report. D1's «Equipos» alternative stays an owner question.

### Task 4 (wizard, drive route)

- **M4: a choice counter.** A step-local `turno`, bumped by every user choice (tree selection, «Usar esta ruta», «Actualizar lista»); a thread result applies only if its `turno` is still current. «Usar esta ruta» sets `wiz.state.device = None` («Siguiente» off) and shows the chip «Comprobando la ruta…» until its result lands or is superseded. `destino.is_dir()` moves into the thread with `volume_for`. For the list read: at paint keep `previa = wiz.state.device` and set `wiz.state.device = None`; on arrival select `previa` if listed and call `mostrar()`; a hand path that won meanwhile stays. Tests: «una ruta a mano que llega tarde no pisa la fila elegida después»; «Siguiente» is disabled between «Usar esta ruta» and its arrival.
- m9: Step 1 asserts the step's `Sondeo` has no pending id (`_id is None`, `not esperando`) and that no recorded arrival callback runs after releasing the `Encargo`; never count `after info`.
- m12: while the verification read is pending, «Desmontar el contenedor» is off along with «Volver a comprobar»; «Llevar VeraCrypt…» may stay on (its re-verify supersedes through the single `Sondeo`).
- n3: `comprobaciones_dispositivo` stays in `ui/tk_install.py` on the `tk_equipo.comprobaciones` precedent; say so in its docstring.
- n4: `device.check_python()` runs inside `trabajo()`, so a failure is a «sin comprobar» row, not a failed remote check.

### Task 5 (wizard, host route and encryption)

- **M2: one examination per input tuple.** The container step's examination is **one** debounced task with **one** `Sondeo`, keyed by `(fisica, equipo_ruta, forma)` read when the timer fires; either box re-arms it. An arrival applies only if `(caja.get(), punto.get() or equipo_ruta, forma)` still equals that tuple. `crear()` refuses (silently) unless `estado["examen"]` was made for the current tuple (`abrir_o_crear` does not re-check). `paso_carpeta` follows the same rule with `(ruta, forma)`. Test: «el examen del contenedor con otro punto de montaje no cuenta».
- **M3: one probe, ever, per device.** The probe's `Encargo` lives in the wizard state beside `velocidad_escritura` (one new `InstallState` field, or a documented `wiz` attribute). `refrescar_espera`: a done encargo gives its result (`or 0.0`) without relaunching; a pending one is waited on; a new probe starts only when there is none for this `estado.device`. Use `segundo_plano.lanzar`, not `lanzar_sin_repetir`. While a probe is pending «Crear y montar» is off; after `TOPE_SONDA_S` (60 s) `espera` says «no se ha podido medir» and the button comes back (a later arrival is still stored). Tests: «una sola sonda aunque el hilo acabe antes de mirarlo», «una sola sonda aunque se repinte el panel».
- m8: each debounce `after` hangs on its own entry (Tk drops it with the widget) or is cancelled on the entry's `<Destroy>`; never on the root. Step 2 adds «un cambio de paso con una tecla pendiente no examina nada ni da error».
- m10: on host «Parejas» the debounce only changes the line under each field; «Siguiente» there is `config_written`, unchanged. «Examinar…» launches its examination at once, without debounce.
- n5: «Task 5 makes the tests' `escribir()` helper run `entrada.update()`» (it does not today).

### Task 6 (installer)

- **B1: split it.** **6a** = everything except `.github/workflows/build-installer-release.yml`: the composite action, `instalador.yml`, `--autoprueba`, `check_python`, the build checks, docs, tests. **6b** = the release-workflow hunk alone, delivered as a separate patch (`cambio-6b.patch`) and committed by the merger **only after an `Instalador` run on the branch push is green** (python 3.14.8, tk 9.0.4, svg true, exit 0). If it is red, 6b is not committed, the run's link and log go in the report, and it becomes an owner question.
- **M1: strict only in CI.** `comprobar_tk(estricto)` and `comprobar_pyinstaller(estricto)` are strict when `GITHUB_ACTIONS` is set or `--estricto` is passed (the composite action passes it): `SystemExit` as planned. Otherwise they print a clear warning and carry on («Este Python trae Tk 8.6: el .exe pintará con el pintor de Python, más lento; el de las releases se compila con el Python fijado (3.14.8, Tk 9)» / «PyInstaller X.Y.Z en vez del fijado 6.22.3»). `tests/test_build_installer.py` covers both modes. The guide keeps `pip install pyinstaller==6.22.3` as the documented line and gives the PBS recipe as an option. **D4b** (owner): should local builds be strict too?
- m1: `timeout-minutes` goes on the `uses: ./.github/actions/compilar-instalador` step in both workflows; inside the action the gate uses `Start-Process … -PassThru` and `WaitForExit(180000)` + `Stop-Process -Force`, not `-Wait`.
- m2: the action exposes `exe`; `instalador.yml` asserts it, and 6b's `build-installer-release.yml` uses it instead of re-globbing `dist/`.
- m3: `persist-credentials: false` on the release job's checkout; hashed build dependencies are an owner question (not done here).
- m4: `check_python()` treats «no JSON answer» (rc ≠ 0, 124, 127, garbage) like «no Python» (`ok` false with `root`, true without); the detail names the Store alias when rc is 9009 or the path is under `WindowsApps`. A test fakes rc 9009.
- m5: the «< 3.11 with `root` → `ok` false» rule is new: say so, document it in `provisioning.md`.
- m6: `--autoprueba` is hidden from `--help` (`argparse.SUPPRESS`); it does not call `theme.apply()` apart from `tk_install.build()` (which applies it); `tests/test_autoprueba.py` greps the function-level imports of `tk_install.py`, `tk_crypto.py`, `tk_equipo.py` and asserts each is in the `modulos` constant.
- m7: `instalador.yml` keeps `push` (TEMPORAL) and `workflow_dispatch`; its `pull_request` paths are only the build's own (`build_installer.py`, `prdrive-install.py`, `install/**`, `common/pins.py`, `tests/_runtime_ci.py`, the action, the workflow). Broader is an owner question.
- m14: `PYINSTALLER`'s docstring rests the pin on «≥ 6.22 per the spec, latest patch, verified by `Instalador`», not on the embedded-data feature; `_runtime_ci compilador`'s reason is «the release `.exe` is Windows-only».

### Owner decision of 09/10: Tk 9 is the only supported Tk

- Task 6 gains the light-install gate the spec promises: `check_python()` reports the host Python's Tk version and, for the light install, a Tk below 9 makes `ok` false with a sentence that says why (python.org Windows Pythons ship Tk 8.6). The build is strict everywhere, not only in CI (D4b answered: yes), with a clear error pointing to the pinned-runtime recipe.
- Every builder verifies with the Tk 9 leg only; CI's `tests` job is Tk 9, plus `python-minimo` (Python 3.11, no display) for the non-UI floor. Tk 8.6 code paths stay until stage 4.

### Task 7 (`tk.Tabla` on the canvas)

- m16: no hover in `Tabla` (owner question).
- n2: Step 2 asserts no `after` of the table is pending after the first `update_idletasks()` and its items are unchanged after one more `update()`; no timed wait.

### Owner decision of 09/10: no fallback for the release

If the first `Instalador` run (Python 3.14.8, Tk 9.0.4) is red, there is no release until it is fixed: the release job is never pointed back at a Tk 8.6 build. 6b still lands only after a green `Instalador` run.

### Owner decisions, as taken here

- **D1:** keep the look, take the invisible trims (m17); report the miss. The «Equipos» alternative is asked.
- **D2:** keep `tabla_estado()` in ttk with the corrected bound (M6).
- **D3:** adopt `--autoprueba`, hidden from `--help`.
- **D4:** CI and release build on PBS 3.14.8; the release wiring only after a green run (B1); local builds warn (M1). **D4b** asked.
- **D5:** **not taken**: flowing rows (M5). Fixed rows are asked.
- Also asked: hover in the fleet table (m16), `instalador.yml`'s PR trigger breadth (m7), hashed build dependencies (m3).
