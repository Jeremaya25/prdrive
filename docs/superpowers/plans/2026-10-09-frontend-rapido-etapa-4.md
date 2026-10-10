# Fast frontend, stage 4 («Limpieza») Implementation Plan

> **For agentic workers:** builders are **Haiku**, reviewers **Sonnet** (owner, 09/10: the small changes that touch every window go to Haiku). Each builder sees only its task plus **Global Constraints**: everything a task needs is written in it. Steps use checkbox (`- [ ]`) syntax.

**Goal:** the device can time its own windows (`PRDRIVE_PERF=1`), the Tk 8.6 leftovers are documented and their tests fixed without removing what a 3.13 device still needs, and the real-machine checks the stages left open are written down or run in the cloud.

**Architecture:** one shared timing helper in `ui/__init__.py` (already in `sys.modules` before every window's first paint: `runsync.py`, `prdrive-install.py` and `pregunta.py` all import `ui` first), plus the one hook in `ui.tk.mostrar` every dialog shares; then one task per window file that only adds marks, each owning disjoint files. The cloud row F21 runs in two jobs of its own.

**Spec:** `docs/superpowers/specs/2026-10-08-frontend-rapido-design.md` («Limpieza»); the stage 3 plan's «Appendix: stage 4».

## Global Constraints

- **Protocol.** Work on a worktree of `claude/adoring-pascal-5j258r` (first `git merge --ff-only claude/adoring-pascal-5j258r`); ONE commit per task with the Spanish subject the task gives, body 2–4 lines, footer exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01JHY3t4qHyjjXzmXQXCxAVU`; never push, never open a PR, never bump `VERSION`, never write a marker that skips CI. The director merges.
- **Verification.** Tk tests: `xvfb-run -a -s "-screen 0 1920x1080x24" /tmp/claude-0/-home-user-prdrive/03b34008-f2da-52c1-8cde-5efd2782344d/scratchpad/runtime-linux64/bin/python3 tests/<file>.py`; headless: `python3 tests/<file>.py`; the full suite ONCE at the end (`tests/run_all.py`, same Python, every file passes). Each new test fails first (say so). A Tk test file starts with the repo's pattern of skipping itself (`print("  (saltado) …")` and exit with the report) when `tkinter` or a display is missing: the CI job «Python 3.11 sin pantalla» has neither. Never kill processes you did not start.
- **Tk.** Tk 9 is the only supported Tk for new code, but **nothing a 3.13 device (Tk 8.6.15 on Windows) needs to open its window, «Ajustes» or «Parejas», and reach «Actualizaciones → Actualizar…» is removed**, nor anything a Tk 8.6 *host* Python needs.
- **Marks.** `PRDRIVE_PERF` unset, `""` or `"0"` = off, and off costs one `os.environ.get` per mark: no import, no file, no `after_idle`, no thread. A mark never calls `store.write_json` (the timing check counts those: `escrituras.marcar` = 0) and never writes on the Tk thread; trimming is `store.recortar_diario`'s (it rewrites with `write_text` only past 256 KiB, off the Tk thread here). A failed write (read-only, full or ejected device) is swallowed. Details are numbers and fixed words only, never names or paths (`perf.log` travels with the drive).
- **Imports.** `perf_empezar`/`perf_al_pintar`/`perf_marca` are imported in each module's HEADER (`from . import perf_empezar, perf_al_pintar` next to the module's other `from . import`), never inside a function: a lazy `from . import` inside `main_window` fails `tests/test_imports_perezosos.py`. No new module before any first paint (`tests/rendimiento/presupuesto.toml` `modulos.*` unchanged). `penwatch.py` and `runsync.py` untouched; stdlib only; Spanish comments and user text; `docs/agents/` in English. Adding a mark to a `tk_*` file is allowed: timing is not a decision.

---

## Wave 1 (Tasks 1 and 8 in parallel)

### Task 1: The timing helper, the `mostrar` hook, its test kit, the `apply-*` mark, and the timing check's `--env`

**Files:** `ui/__init__.py`; `ui/tk.py` (ONLY `mostrar`); `ui/theme.py` (ONLY the `apply-*` mark); Create `tests/_perf.py`, `tests/test_perf.py`; `tests/rendimiento/correr.py`; `docs/agents/reference/ui.md` (bullet «Timing on the device»), `docs/agents/reference/commands-testing.md`.

**Interfaces (Wave 2 uses exactly these; all in `ui/__init__.py`):**
- `perf_activo() -> bool` — reads `PRDRIVE_PERF` per call (like `theme.elegir_tema()`).
- `perf_empezar(momento: str) -> None` — when active, `_INICIOS[momento] = time.perf_counter()`.
- `perf_al_pintar(widget, momento: str, t0: float | None = None, *, host: bool = False, **detalle) -> None` — when active: `t0` or `_INICIOS.pop(momento, None)` (nothing if neither); queue on the ROOT (`widget.nametowidget(".")`, which outlives dialogs), inside `try/except Exception`, an `after_idle` callback that FIRST drains what the change left pending with `root.update()`, then computes `(time.perf_counter() - t0) * 1000` and calls `perf_marca(momento, ms, host=host, **detalle)`. The drain is what makes the mark end where the timing check's `update()` ends: a bare idle callback fires before the layout and the redraws the change triggers (measured: 0.9 ms against 46.7 ms for a change that moves 400 widgets). The callback is wrapped in `try/except Exception`.
- `perf_marca(momento: str, ms: float | None, *, host: bool = False, **detalle) -> None` — when active (and `ms` is not `None`), appends `«<store.stamp()> <momento> <ms:.1f> ms vez=<N> <k=v …>»` (`N` = how many times this process has marked `momento`, from 1) to an in-memory queue; a daemon thread, started by the first active mark, writes the queue every second, and an `atexit` handler writes what is left. Device lines go to `model.LOG_DIR / "perf.log"`, host lines (`host=True`) to `common.equipo.DIR / "perf.log"`; in both cases the folder is created (`mkdir(parents=True, exist_ok=True)`: `PRDRIVE_PERF=1` is an explicit opt-in), then `store.recortar_diario(ruta)`, then `open(ruta, "a", encoding="utf-8", errors="replace")`; `(OSError, ValueError)` swallowed. `model`, `store`, `equipo` imported inside; directories read at write time (tests rebind them).
- `perf_desde_inicio() -> float | None` — ms since the PROCESS was created (Windows: `GetProcessTimes` via `ctypes`, creation FILETIME against `time.time()`; Linux: `/proc/self/stat` field 22 and `os.sysconf("SC_CLK_TCK")` against `btime` from `/proc/stat`; else `None`). The `start-*` marks use it as their `t0` equivalent: `perf_al_pintar(root, "start-main", time.perf_counter() - perf_desde_inicio() / 1000)` (Wave 2 writes exactly that; nothing when it is `None`).
- `ui.tk.mostrar(dlg, parent=None)` keeps its signature (17 test files fake it as `(dlg, parent=None)`). Right before its `dlg.wait_window()`: `momento = getattr(dlg, "perf_momento", None)`, and if set, `perf_al_pintar(dlg, momento)`. The opening code sets `dlg.perf_momento` and calls `perf_empezar(<same name>)` at its start (Wave 2).
- `apply-*`: in `ui/theme.py` `apply()`, the FIRST call of the process marks its own duration with `perf_marca("apply-" + ui.perf_quien, ms)`; `ui.perf_quien` is a module variable, default `"main"`, that the wizard and the agent's question set (Task 6).
- `tests/_perf.py`: `con_perf(tmp)` (context manager: sets `PRDRIVE_PERF=1`, rebinds `model.LOG_DIR`, `model.STATE_DIR` and `common.equipo.DIR` to folders under `tmp`, and on exit writes the queue synchronously and restores everything), `lineas(tmp, momento, host=False) -> list[str]` (the lines whose field after the stamp equals `momento`), `vaciar()` (write the queue now).
- `tests/rendimiento/correr.py`: a repeatable `--env CLAVE=VALOR` option merged into each child's `extra` (`entorno()` strips every `PRDRIVE_*` otherwise); after each pass, if `PRDRIVE_PERF` was passed, copy `<device>/.prdrive/logs/perf.log` and the fake host's prdrive `perf.log` to `--salida` as `perf-<arbol>-<flujo>-<pares>-<ronda>.log`.

- [ ] **Step 1: `tests/test_perf.py`, failing first.**
  - off: no file, no `after_idle` queued on the root (wrap `root.after_idle` to count), `threading.active_count()` unchanged;
  - on: `perf_marca("x", 12.34, n=3)` then `vaciar()` → one line `… x 12.3 ms vez=1 n=3`; a second → `vez=2`;
  - `LOG_DIR` that does not exist → created, line written; `LOG_DIR` that is an existing FILE → no exception, nothing written; `host=True` with `equipo.DIR` missing → created, line written there and not in `LOG_DIR`;
  - with `store.DIARIO_TOPE = 2048`, 400 marks → file size ≤ 2048 + one line, last line = last mark;
  - a detail value `"ñ€✓"` → no exception, one line;
  - `perf_empezar("x")` + `perf_al_pintar(w, "x")` → one line; again without `perf_empezar` → none;
  - drain: change one label so 50 sibling labels move (grid), `perf_al_pintar` it; time a twin change with `update()`; the mark's ms ≥ 0.8 × the twin's;
  - queue-then-destroy: `perf_al_pintar(dlg, "x", t0)`, `dlg.destroy()`, `root.update()` → no Tcl background error (the `anotar_errores(raiz)` pattern of `tests/test_tk_tabla.py`) and one line;
  - `mostrar` with `dlg.perf_momento = "y"` (real `ui.tk.mostrar`, dialog destroyed by an `after`) → one `y` line; without the attribute → none;
  - `perf_desde_inicio()` on Linux is a positive number larger than the test's own elapsed time;
  - `apply-main` written once for two `theme.apply()` calls.
- [ ] **Step 2:** implement; `python3 tests/test_imports_perezosos.py`; docs: `ui.md` «Timing on the device» (file locations, line format, `vez`, that the drain exists to match the timing check, how to turn it on per entry point — Linux `PRDRIVE_PERF=1 ./runsync.sh`, Windows `set PRDRIVE_PERF=1` then `runsync.bat` —, that `start-*` counts from process creation, that `cold-parejas` is `start-main` + `open-parejas`); `commands-testing.md`: `PRDRIVE_PERF=1` after the `PRDRIVE_SIN_SVG=1` sentence, `correr.py --env`, and `ui.perf_marca` in the registry of indirection points. Full suite. Commit «El dispositivo puede apuntar lo que tardan sus ventanas (PRDRIVE_PERF=1)».

### Task 8: The frontend real-machine checklist and the cloud row F21 (`.pyc` between systems)

**Files:** Create `docs/superpowers/pruebas/2026-10-09-frontend-pendiente-en-real.md`, `tests/maquina/f21_pyc_entre_sistemas_linux.py`, `tests/maquina/f21_pyc_entre_sistemas_windows.py`; Modify `.github/workflows/maquina-real.yml`, `.claude/skills/real-machine-tests/SKILL.md` (one line: the frontend checklist exists), `docs/superpowers/pruebas/maquina-real-resultados.md` (filled by the director).

- [ ] **Step 1: The checklist**, this skeleton: `# Plan: el frontend rápido en máquinas de verdad` · `Fecha: 2026-10-09 · Estado: **por hacer**.` · `## Equipos` (`W`: Windows 11 x64 with a prdrive device; `W10`: Windows 10 22H2; `L`: a Linux desktop) · one table `| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |` with rows `E1` cold start from a USB stick (≈80 MB, ≈190 files, OS cache cold) of the main window and «Parejas» (W, L; stopwatch or `PRDRIVE_PERF=1`: `logs/perf.log`), `E2` the look on a real screen, light and dark, 100/150/200 %, of every window of stages 1b–3 (main, «Parejas», «Ajustes» and its panes, «Dispositivos», the flags editor, the wizard from the installer `.exe` built by the `Instalador` workflow, the agent's question) (W, W10), `E3` `F21 · nube` (link to `maquina-real-resultados.md`) · `## Qué hacer con lo que salga` (a difference → an issue with the screenshot; a time → the results file).
- [ ] **Step 2: F21 in two jobs OUTSIDE the existing matrix** (the matrix legs start together and cannot hand an artifact to each other). In `maquina-real.yml`:
  - job `pyc-linux` (ubuntu-latest): checkout; setup-python 3.11; `actions/cache` of `$RUNNER_TEMP/prdrive-cache` keyed by `python tests/_runtime_ci.py clave`; `python tests/_runtime_ci.py runtime linux-x64 "$RUNNER_TEMP/runtime" "$RUNNER_TEMP/prdrive-cache"`; `F21_ARBOL=$RUNNER_TEMP/f21-arbol python tests/maquina/correr.py F21 --de-verdad`; `actions/upload-artifact@v4` name `f21-arbol` path `$RUNNER_TEMP/f21-arbol`;
  - job `pyc-windows` (windows-latest, `needs: pyc-linux`): checkout; setup-python 3.11; the same cache and `runtime windows-x64`; `actions/download-artifact@v4` name `f21-arbol` into `$RUNNER_TEMP/f21-arbol`; `F21_ARBOL=…` `python tests/maquina/correr.py F21 --de-verdad` (as admin, like the existing Windows leg);
  - both run on the same triggers as the existing job, plus `install/deploy.py`, `install/runtime_bin.py`, `common/pins.py`, `install/platforms.py`, `tests/_runtime_ci.py` in the `pull_request` paths.
  - `f21_pyc_entre_sistemas_linux.py` (`CODIGO = "F21"`, `SISTEMA = "L"`): copies `common/`, `ui/`, `penwatch.py` into `$F21_ARBOL/.prdrive/`; asserts `install.deploy.precompilar(app, python, biblioteca=False) is True` with the pinned Linux interpreter (`common.pins.interprete_consola`) and that ≥ 1 `__pycache__/*.cpython-314.pyc` exists per tree; writes `control_marca_tiempo.py` with its source mtime set to an ODD second (`os.utime(src, (T | 1, T | 1))`, integer T) and compiles it in TIMESTAMP mode (`py_compile.compile(..., invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)`); writes `manifiesto.json` (each `.pyc`: name, flags, source hash, size).
  - `f21_pyc_entre_sistemas_windows.py` (`CODIGO = "F21"`, `SISTEMA = "W"`), for `fat32` and `exfat` (`comun.por_cada`): `comun.volumen_windows(tipo)` (no fixed letter); `shutil.copytree($F21_ARBOL/.prdrive, <letra>:\.prdrive)`; snapshot every `.pyc` (name, flags, hash, `mtime_ns`, sha256); `os.utime` every source +7 h (sources moved in time, as between systems); ONE run of the pinned windows-x64 Python: `python -I -v -c "import sys, importlib; sys.path.insert(0, ROOT); …"` importing each module whose `.cpython-314.pyc` was found, each in `try/except Exception` (failures written with `p.nota()`, never fatal: `ui.bandeja_linux`, `common.dbus` and others are Linux-only); classify each module from stderr: **reused** = a line `# <pyc> matches <src>` for it; **rebuilt** = `code object from <…>.py` with no `matches` line. Checks: every checked-hash module reused and its `.pyc` byte-identical after the run; `control_marca_tiempo` rebuilt — unless `int(os.stat(src).st_mtime)` on the volume was rounded so the timestamp still matches, then `p.nota("control no aplicable en <tipo>")`; the compared set is not empty (fail otherwise); a checked-hash source changed with the same size and mtime is rebuilt. Result lines per the `real-machine-tests` skill.
- [ ] **Step 3:** `python -m py_compile tests/maquina/*.py`; `python tests/maquina/correr.py --lista` shows F21 for L and W. The director pushes and records the `RESULTADO` lines. Commit «Lo que queda por probar en una máquina de verdad, y los .pyc de un sistema a otro en la nube».

---

## Wave 2 (Tasks 2–6 in parallel, on Task 1; disjoint files; each only adds marks)

**The ownership table.** Each task implements exactly its rows. «start» = `perf_empezar("<momento>")` as the FIRST statement there; «end» = `perf_al_pintar(<widget>, "<momento>")` as the LAST statement there (Task 1's drain makes it end after the paint); «via mostrar» = set `dlg.perf_momento = "<momento>"` right before the existing `mostrar(dlg, …)` call (Task 1's hook ends it). Line numbers at `61c14cb`; find by function name. The device writes one name per place, with `vez=N`: there is no `reabrir-parejas` or `pane-otra-vez` on the device (they are `vez ≥ 2`).

| Moment | Start | End | Task |
|---|---|---|---|
| `start-main` | process creation (`perf_desde_inicio`) | `ui/tk.py` `main_window`: right after `ensenar(root)`, BEFORE `root.after_idle(refrescar_instantanea)` | 2 |
| `llega-instantanea` | `ui/tk.py` `llegar` | `llegar`, after `la_compartida().poner(inst)` | 2 |
| `marcar` | `ui/tk.py` `al_marcar` | end of `al_marcar` | 2 |
| `sincronizar-ventana` | `ui/tk.py` `sincronizar` | in `lanzar`, right after `output_window(...)` returns (it returns after its `ensenar`): `perf_al_pintar(<the pass window>, "sincronizar-ventana")` | 2 |
| `volver-pasada` | the pass window's `al_destruir`, after its guard | end of `al_cerrar` | 2 |
| `log-10k` (only when the pass printed ≥ 1000 lines; detail `lineas=N`) | first insert in `_volcar` | `terminado` | 2 |
| `open-ajustes` | `ui/tk.py` `abrir_ajustes` | via mostrar in `tk_doctor.open_dialog` | 2 (start), 4 (via mostrar) |
| `volver-ajustes` | `abrir_ajustes`, right after the dialog returns | end of `abrir_ajustes` | 2 |
| `open-parejas` | `ui/tk.py` `abrir_parejas` | via mostrar in `tk_pairs.open_dialog` | 2 (start), 3 (via mostrar) |
| `catalogo-llega` | `tk_pairs` `llegado` | after `refrescar(...)` in `llegado` | 3 |
| `elegir-pareja` / `elegir-dispositivo` | `ui/tk_tabla.py` `TablaLienzo.elegir`, after its early returns | end of `TablaLienzo.elegir`: `if self.momento_elegir: perf_al_pintar(self.marco, self.momento_elegir, t0)` (class attribute `momento_elegir = None`; only `avisar=True` calls mark) | 3 (`tk_tabla.py`; `ListaParejas.__init__` sets `"elegir-pareja"`), 5 (`tk_fleet.open_dialog` sets the fleet table's `momento_elegir = "elegir-dispositivo"`) |
| `open-flags` | `tk_pairs` `EditorPareja.editar_flags` | via mostrar in `flags_form` | 3 |
| `open-dispositivos` | `tk_pairs` `ver_flota` | via mostrar in `tk_fleet.open_dialog` | 3 (start), 5 (via mostrar) |
| `pane-<clave>` | `tk_doctor` `elegir(clave)`, after its early return for the current pane | after `ajustar(panel)` / `dibujar(clave)` in `elegir` | 4 |
| `llega-flota` | `tk_fleet` `llegada` | after `pintar(...)` in `llegada` | 5 |
| `start-wizard` (host) | process creation | `tk_install.run_wizard`, before `root.mainloop()` | 6 |
| `paso-<slug>` (host; each step) | `Wizard.ir` | end of `Wizard.repintar`; slug = the step title lower-cased, accents removed, runs of non-alphanumerics → `-` (`paso-donde`, `paso-dispositivo`, `paso-parejas-y-configuracion`) | 6 |
| `start-agente` (host) | process creation | `tk_agente`, before `root.mainloop()` | 6 |

Each Wave 2 task also creates its own test file — Task 2 `tests/test_perf_principal.py`, 3 `test_perf_parejas.py`, 4 `test_perf_ajustes.py`, 5 `test_perf_flota.py`, 6 `test_perf_anfitrion.py` — that, inside `_perf.con_perf(tmp)`, opens the real window with fixtures copied from the named existing test file (copy the minimum setup, never import another test file; where those fixtures fake `ui.tk.mostrar`, use the real one for the `open-*` assertions), performs each action and asserts `len(_perf.lineas(tmp, "<momento>")) == 1` for each of its moments after `_perf.vaciar()`, plus one run with `PRDRIVE_PERF` unset asserting no `perf.log` exists; the window's existing tests unchanged and green.

### Task 2: Main window and pass window (`ui/tk.py`, except `mostrar`)
Rows marked 2. Extra tests: **cloak order** — with `tk.IS_WIN = True` and `tk._encubrir` replaced by a recorder (the pattern of `tests/test_tk_ensenar.py`), the `start-main` line's callback runs only after the recorder saw `_encubrir(h, False)`; **read-only device** — with `model.LOG_DIR` pointing to a FILE, the main window opens, marks, closes, and a tick still makes 0 `store.write_json` calls. Fixtures from `tests/test_tk_principal_ancho.py` and `tests/test_tk_pasada.py`. Commit «La ventana principal y la de la pasada apuntan sus tiempos con PRDRIVE_PERF=1».

### Task 3: «Parejas» (`ui/tk_pairs.py`, `ui/tk_tabla.py`)
Rows marked 3. Fixtures from `tests/test_tk_parejas_vista.py`; the `elegir-pareja` test clicks a row (`TablaLienzo` click at the row's y), not `ListaParejas.elegir`. Commit «Parejas apunta sus tiempos con PRDRIVE_PERF=1».

### Task 4: «Ajustes» (`ui/tk_doctor.py`)
Rows marked 4. Fixtures from `tests/test_tk_ajustes_vista.py`. Commit «Ajustes apunta sus tiempos con PRDRIVE_PERF=1».

### Task 5: «Dispositivos» (`ui/tk_fleet.py`)
Rows marked 5. Fixtures from `tests/test_tk_flota_vista.py`. Commit «Dispositivos apunta sus tiempos con PRDRIVE_PERF=1».

### Task 6: Host windows (`ui/tk_install.py`, `ui/tk_agente.py`, `pregunta.py`)
Rows marked 6, all with `host=True`; `run_wizard` sets `ui.perf_quien = "wizard"`, `pregunta.py` sets `ui.perf_quien = "agente"` before the question window's first `theme.apply()`. Extra test: with `equipo.DIR` missing, the wizard opens and steps, and its lines land in the created `equipo.DIR`. Fixtures from `tests/test_tk_asistente.py` (the wizard) and `tests/test_unidad_nueva.py` (it builds the question window with `ui.tk_agente`). Commit «El asistente y la pregunta del agente apuntan sus tiempos en el equipo con PRDRIVE_PERF=1».

**Wave 2 budget:** `modulos.*` and every `widgets.*` unchanged; the timing check's medians unchanged (marks are off there).

---

## Wave 3 (after Wave 2 is merged)

### Task 7: Tk 8.6 — what stays, what goes, and say so

No production code is removed.

**Files:** `docs/agents/reference/ui.md` («Which Tk»); `tests/_vista.py` (gains `estilos(interprete)`, the helper with the Tk 8.6 fallback now at `tests/test_tk_visor.py:60-70`), `tests/test_tk_visor.py` and `tests/test_tk_tabla.py` (import it from `tests/_vista.py`; `test_tk_tabla.py` uses it at BOTH `ttk::style theme styles` call sites, lines ~1118 and ~1130); docstrings and comments only: `ui/theme.py` `nitidez()` (drop the claim that Tk 9 changes the DPI line: `common/pins.py` measured that 9.0.4 does not either), `ui/icons.py` module docstring (drop «the light install uses the painter on Tk 8.6»: the light install refuses Tk < 9), `ui/tk.py` `_arrancar_barra` (delete its last sentence about a hypothetical Tk; do not touch the code), `install/runtime_bin.py` lines ~32 and ~87-88 (3.13 examples → `python3.14`, «Devuelve 3.14 a partir de 3.14.8»).

- [ ] **Step 1:** «Which Tk» names the three Tk 8.6 reaches — (1) a 3.13 device's window; (2) the agent's «¿Atender esta unidad?» window, which runs on the agent's Python (a host Python, or an older runtime until the agent updates); (3) the launchers' host-Python fallbacks (`runsync.bat` step 3, the light launcher) —, the **keep list** with its hard need (`theme.pista_campo()`'s `TclError` branch → `pista_etiqueta()`: without it, opening «Ajustes» or «Parejas» raises inside the click handler, Tkinter swallows it, and the window simply does not open, so a 3.13 device cannot reach «Actualizar…»), and the **removal list with its precondition** (no 3.13 device left AND host windows gated to Tk 9): `pista_etiqueta`, `gripcount=0`, the window PNG branch of `icons._foto`, `USAR_SVG`/`PRDRIVE_SIN_SVG` and the «no» path of `svg_disponible`, `_SinSvg` (after making the SVG describer total), and their tests (`tests/test_iconos_svg.py` ~155-185 and ~232-341, `tests/test_controles.py` ~211-217 and ~250-270).
- [ ] **Step 2 (local record, no CI leg):** run the whole suite once on `/usr/bin/python3.12` (Tk 8.6) under xvfb before and after; the report states `N/N` and the files that fail on 8.6 with the reason (expected: `test_tk_tabla.py` before, none after). Stop rule: if anything other than the listed files would have to change to pass on 8.6, report it and do not change it.
- [ ] **Step 3:** full suite (Tk 9). Commit «Tk 8.6: lo que queda y por qué, y las pruebas que aún lo pisan».

---

## Wave 4

### Task 9: Close the stage
- [ ] Timing check on the merged tip: every count at or under its ceiling; medians unchanged by the marks.
- [ ] `xvfb-run … tests/rendimiento/correr.py --pr . --base . --trabajo <tmp> --python <runtime> --rondas 1 --env PRDRIVE_PERF=1` locally: the `perf-*.log` files hold the moments of the table; for each driver moment, the `vez=1` line is within ±20 % (or ±10 ms) of the driver's `record()` value of the SAME pass, except `start-*` (device clock from process creation, the driver's from before spawning: said, not hidden) and moments the driver times with a hook the device cannot have (say which).
- [ ] `docs/superpowers/pruebas/<date>-etapa-4-resultados.md` (the date of the run); spec «Estado» gets «Etapa 4 hecha, revisada y medida: `docs/superpowers/pruebas/<fichero>`». Commit «Etapa 4: lo medido y lo que queda por hacer en una máquina de verdad».

---

## Decisions for the owner (taken here with a default; to review)

1. **No Tk 8.6 code is removed in stage 4.** Removing it later needs both preconditions; gating host windows to Tk 9 (the agent install refusing a host Python below Tk 9, as the light install does) is a product decision outside this plan.
2. **`start-*` counts from process creation** (OS APIs), so it includes Python's start-up like the driver's T0 (a few ms apart).
3. **In timing mode a mark drains pending work with `update()`** before stopping its clock (to end where the timing check ends). Only with `PRDRIVE_PERF=1`; it can run a queued input event a few ms earlier than without it.
4. **F21 calls `deploy.precompilar` on a copied tree** in the cloud: nothing is deployed (no rclone, no config, no device), so the plan reads it as within the `real-machine-tests` skill's «never deploy a device».
5. **The «Ajustes» panes stay as they are**; the binary-alpha measurement (`alfa-binario-pintor.yml`) informs the owner's decision.
6. **`perf.log` lives in `logs/`** (the folder «Abrir los logs» opens) and, for host windows, next to the agent's log; both folders are created by the first mark.
7. **Details are numbers and fixed words only** (no pair names, paths or hosts).
8. **Off in every build** unless `PRDRIVE_PERF` is set; how to set it per entry point goes in `ui.md`; the device guide is not changed.
9. **Lines are buffered and written by a background thread** (never on the Tk thread); a crash can lose the last second of marks.
10. **The Windows accessibility check** (Tk 9.0.4's DLL and UI Automation) stays an open question of the spec, not a stage 4 row.
