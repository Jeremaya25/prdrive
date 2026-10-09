# Fast frontend, stage 4 («Limpieza») Implementation Plan

> **For agentic workers:** builders are **Haiku**, reviewers **Sonnet** (owner, 09/10: the small changes that touch every window go to Haiku). Each builder sees only its task plus **Global Constraints**: everything a task needs is written in it. Steps use checkbox (`- [ ]`) syntax.

**Goal:** the device can time its own windows (`PRDRIVE_PERF=1`), the Tk 8.6 leftovers are documented and their tests fixed without removing what a 3.13 device still needs, and the real-machine checks the stages left open are written down or run in the cloud.

**Architecture:** one shared timing helper in `ui/__init__.py` (already imported by every window, so no new module before a first paint), then one task per window file that only adds marks, each owning disjoint files. The cloud row F21 reuses `tests/maquina/` and its VHD/loop helpers.

**Spec:** `docs/superpowers/specs/2026-10-08-frontend-rapido-design.md` («Limpieza»); the stage 3 plan's «Appendix: stage 4».

## Global Constraints

- **Protocol.** Work on a worktree of `claude/adoring-pascal-5j258r` (first `git merge --ff-only claude/adoring-pascal-5j258r`); ONE commit per task with the Spanish subject the task gives, body 2–4 lines, footer exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01JHY3t4qHyjjXzmXQXCxAVU`; never push, never open a PR, never bump `VERSION`, never write a marker that skips CI. The director merges.
- **Verification.** Tk tests: `xvfb-run -a -s "-screen 0 1920x1080x24" /tmp/claude-0/-home-user-prdrive/03b34008-f2da-52c1-8cde-5efd2782344d/scratchpad/runtime-linux64/bin/python3 tests/<file>.py`; headless: `python3 tests/<file>.py`; the full suite ONCE at the end (`tests/run_all.py`, same Python, every file passes). Each new test fails first (say so). Never kill processes you did not start.
- **Tk.** Tk 9 is the only supported Tk for new code, but **nothing a 3.13 device (Tk 8.6.15 on Windows) needs to open its window and reach «Ajustes → Actualizaciones → Actualizar…» is removed**, nor anything a Tk 8.6 *host* Python needs (the agent's question runs `pregunta.py` on the host's `pythonw.exe`; the launchers' host-Python fallbacks).
- **Marks.** `PRDRIVE_PERF` unset, `""` or `"0"` = off, and off costs one `os.environ.get` per mark: no import, no file, no `after_idle`, no thread. A mark never writes through `store.write_json`/`write_text` (the timing check counts those: `escrituras.marcar` = 0), never writes on the Tk thread, and a failed write (read-only, full or ejected device) is swallowed. Details are numbers and fixed words only, never names or paths (privacy: `perf.log` travels with the drive).
- No new module imported before any window's first paint (`tests/rendimiento/presupuesto.toml` `modulos.*` unchanged). `penwatch.py` and `runsync.py` untouched; stdlib only; Spanish comments and user text; `docs/agents/` in English; `tk_*` files may add marks (timing is not a decision).

---

## Wave 1

### Task 1: The timing helper, its test kit, the `apply-*` mark, and the timing check's pass-through

**Files:** `ui/__init__.py`; `ui/theme.py` (only the `apply-*` mark); Create `tests/_perf.py`, `tests/test_perf.py`; `tests/rendimiento/correr.py`; `docs/agents/reference/ui.md` (bullet «Timing on the device»), `docs/agents/reference/commands-testing.md` (the env var next to `PRDRIVE_SIN_SVG`/`PRDRIVE_TEMA`, and the helpers in the indirection registry).

**Interfaces (Wave 2 uses exactly these):**
- `perf_activo() -> bool` — reads `PRDRIVE_PERF` per call (like `theme.elegir_tema()`).
- `perf_empezar(momento: str) -> None` — when active, stores `time.perf_counter()` in a module dict `_INICIOS[momento]`.
- `perf_al_pintar(widget, momento: str, t0: float | None = None, **detalle) -> None` — when active, takes `t0` (or `_INICIOS.pop(momento, None)`; nothing if neither), and queues on the **root** (`widget.nametowidget(".")`, which outlives dialogs) an `after_idle` callback, wrapped in `try/except Exception`, that computes `(perf_counter() - t0) * 1000` and calls `perf_marca`.
- `perf_marca(momento: str, ms: float, *, host: bool = False, **detalle) -> None` — when active, appends `«<store.stamp()> <momento> <ms:.1f> ms <k=v …>»` to an in-memory queue; a daemon thread (started by the first active mark) writes the queue every second, and an `atexit` handler flushes the rest. Device lines go to `model.LOG_DIR / "perf.log"` (`LOG_DIR` created with `mkdir(parents=True, exist_ok=True)`); `host=True` lines go to `common.equipo.DIR / "perf.log"` only if that folder exists. Each write: `store.recortar_diario(ruta)` then `open(ruta, "a")`; any `OSError` swallowed. `model`, `store`, `equipo` imported inside, directories read at write time (tests rebind them).
- `perf_desde_inicio() -> float | None` — ms since the PROCESS was created (Windows: `GetProcessTimes` via `ctypes` against `time.time()`; Linux: `/proc/self/stat` field 22 and `os.sysconf("SC_CLK_TCK")` against the boot time from `/proc/stat` `btime`; else `None`). Used by every `start-*` mark (`perf_marca("start-main", perf_desde_inicio())`).
- `apply-main` / `apply-agente` / `apply-wizard`: in `ui/theme.py` `apply()`, the FIRST call of the process marks its duration with `perf_marca("apply-" + quien, ms)`, `quien` = `"main"`/`"agente"`/`"wizard"` from a module variable `ui.perf_quien` that each entry point sets (Task 2: `"main"` in `ui.start()`; Task 6: `"wizard"`, `"agente"`); default `"main"`.
- `tests/_perf.py`: `con_perf(tmp)` (context manager: sets `PRDRIVE_PERF=1`, rebinds `model.LOG_DIR`, `model.STATE_DIR`, `equipo.DIR` to `tmp/…`, and on exit flushes the queue synchronously and restores everything), `lineas(tmp, momento, host=False) -> list[str]` (the lines whose field after the stamp equals `momento`), `vaciar()` (flush the queue now).
- `tests/rendimiento/correr.py`: when the parent has `PRDRIVE_PERF` set, pass it to each child in `extra` (`entorno()` strips every `PRDRIVE_*` otherwise), and after each pass copy `<device>/.prdrive/logs/perf.log` (and the fake HOME's prdrive `perf.log`) to `--salida` as `perf-<arbol>-<flujo>-<pares>-<ronda>.log`.

- [ ] **Step 1: `tests/test_perf.py`, failing first.**
  - off: no file, no `after_idle` queued (wrap `root.after_idle` to count), no thread started (`threading.active_count()` unchanged);
  - on: `perf_marca` → after `vaciar()`, exactly one line with the moment, `ms` with one decimal, and `k=v` details;
  - `LOG_DIR` missing → created and the line written; `LOG_DIR` pointing to an existing FILE → no exception, nothing written; `host=True` with `equipo.DIR` missing → nothing written;
  - with `store.DIARIO_TOPE = 2048`, 400 marks → file size ≤ 2048 + one line, last line = last mark;
  - `perf_empezar("x")` + `perf_al_pintar(w, "x")` → one line; a second `perf_al_pintar(w, "x")` without `perf_empezar` → none;
  - queue-then-destroy: `perf_al_pintar(dlg, "x", t0)`, `dlg.destroy()`, `root.update()` → no Tcl error reported (the `anotar_errores(raiz)` pattern of `tests/test_tk_tabla.py`) and one line;
  - `perf_desde_inicio()` is a positive number on Linux, larger than the test's own elapsed time;
  - `apply-main` written once for two `theme.apply()` calls.
- [ ] **Step 2:** implement; `python3 tests/test_imports_perezosos.py`; full suite. Commit «El dispositivo puede apuntar lo que tardan sus ventanas (PRDRIVE_PERF=1)».

---

## Wave 2 (Tasks 2–6 in parallel; disjoint files; each only adds marks)

**The ownership table.** Each task implements exactly its rows. «end» means: call `perf_al_pintar(<widget>, "<momento>")` as the LAST statement of that point (the paint queued by the change runs before the idle mark). Windows opened with `mostrar()` get their end from `mostrar()` itself (Task 2): the opening code sets `dlg.perf_momento = "<momento>"` just before calling `mostrar(dlg, parent)`, and `mostrar` calls `perf_al_pintar(dlg, dlg.perf_momento)` right before `dlg.wait_window()` when that attribute exists (`mostrar`'s signature does not change: tests fake it as `(dlg, parent=None)`). Line numbers are at `61c14cb`; find by function name.

| Moment | Start (`perf_empezar`) | End | Task |
|---|---|---|---|
| `start-main` | process creation (`perf_desde_inicio`) | `ui/tk.py` `main_window`, after `ensenar(root)` returns, before `root.mainloop()` | 2 |
| `llega-instantanea` | `ui/tk.py` `llegar`, first line | `llegar`, after `la_compartida().poner(inst)` | 2 |
| `marcar` | `ui/tk.py` `al_marcar`, first line | end of `al_marcar` | 2 |
| `sincronizar-ventana` | `ui/tk.py` `sincronizar`, first line | `output_window`, after its `ensenar()` returns | 2 |
| `volver-pasada` | `ui/tk.py` `output_window`'s `al_destruir`, after its guard | end of `al_cerrar` | 2 |
| `log-10k` (only if ≥ 1000 lines; detail `lineas=N`) | first insert in `_volcar` | `terminado` | 2 |
| `volver-ajustes` | `ui/tk.py` `abrir_ajustes`, after `wait_window`/`mostrar` returns | end of `abrir_ajustes` | 2 |
| `open-parejas` / `reabrir-parejas` (second and later opens in the process) | `ui/tk.py` `abrir_parejas`, first line | `tk_pairs.open_dialog` sets `dlg.perf_momento` before its `mostrar` | 2 (start), 3 (attribute) |
| `catalogo-llega` | `ui/tk_pairs.py` `llegado`, first line | after `refrescar(...)` in `llegado` | 3 |
| `elegir-pareja` (only `avisar=True`) | `ListaParejas.elegir`, first line | end of `elegir` | 3 |
| `open-flags` | `EditorPareja.editar_flags`, first line | `flags_form` sets `dlg.perf_momento` before its `mostrar` | 3 |
| `open-dispositivos` | `tk_pairs` `ver_flota`, first line | `tk_fleet.open_dialog` sets `dlg.perf_momento` before its `mostrar` | 3 (start), 5 (attribute) |
| `open-ajustes` | `ui/tk.py` `abrir_ajustes`, first line | `tk_doctor.open_dialog` sets `dlg.perf_momento` before its `mostrar` | 2 (start), 4 (attribute) |
| `pane-<clave>` (every switch; the driver's `pane-otra-vez` is a later switch to a seen pane) | `tk_doctor` `elegir(clave)`, first line | after `ajustar(panel)` / `dibujar(clave)` in `elegir` | 4 |
| `llega-flota` | `tk_fleet` `llegada`, first line | after `pintar(...)` in `llegada` | 5 |
| `elegir-dispositivo` | `tk_fleet` `repasar`, first line | end of `repasar` | 5 |
| `start-wizard` (host) | process creation | `tk_install.run_wizard`, before `root.mainloop()` | 6 |
| `paso-<nombre>` (host; each step) | `Wizard.ir`, first line | end of `Wizard.repintar` | 6 |
| `start-agente` (host) | process creation | `tk_agente`, before `root.mainloop()` | 6 |
| `cold-parejas` | not emitted: it is `start-main` + `open-parejas` (said in `ui.md`) | | — |

Each Wave 2 task also: a test file `tests/test_perf_<ventana>.py` that, inside `_perf.con_perf(tmp)`, opens the real window with the fixtures copied from the named existing test file (copy the minimum setup; never import another test file), performs the action, and asserts `len(_perf.lineas(tmp, "<momento>")) == 1` for each of its moments, plus one run with `PRDRIVE_PERF` unset asserting no `perf.log` exists; the window's existing tests unchanged and green.

### Task 2: Main window and pass window (`ui/tk.py`, `ui/__init__.py` `start()` sets `ui.perf_quien = "main"`)
Rows marked 2, plus `mostrar()`'s `perf_momento` end (above). Extra tests: **cloak order** — with `tk.IS_WIN = True` and `tk._encubrir` replaced by a recorder (the pattern of `tests/test_tk_ensenar.py`), opening the main window writes `start-main` only after the recorder saw `_encubrir(h, False)`; **read-only device** — with `model.LOG_DIR` pointing to a FILE, the main window opens, marks, closes, and `marcar` still writes nothing through `store.write_json` (count it like the timing driver does). Fixtures from `tests/test_tk_principal_ancho.py` and `tests/test_tk_pasada.py`. Commit «La ventana principal y la de la pasada apuntan sus tiempos con PRDRIVE_PERF=1».

### Task 3: «Parejas» (`ui/tk_pairs.py`)
Rows marked 3. Fixtures from `tests/test_tk_parejas_vista.py`. Commit «Parejas apunta sus tiempos con PRDRIVE_PERF=1».

### Task 4: «Ajustes» (`ui/tk_doctor.py`)
Rows marked 4. Fixtures from `tests/test_tk_ajustes_vista.py`. Commit «Ajustes apunta sus tiempos con PRDRIVE_PERF=1».

### Task 5: «Dispositivos» (`ui/tk_fleet.py`)
Rows marked 5. Fixtures from `tests/test_tk_flota_vista.py`. Commit «Dispositivos apunta sus tiempos con PRDRIVE_PERF=1».

### Task 6: Host windows (`ui/tk_install.py`, `ui/tk_agente.py`, `pregunta.py`)
Rows marked 6, all with `host=True`; `run_wizard` sets `ui.perf_quien = "wizard"`, `pregunta.py` sets `"agente"` before its first `theme.apply()`. Extra test: with `equipo.DIR` missing, the wizard opens and steps with no file anywhere. Fixtures from `tests/test_tk_asistente.py` (the wizard) and `tests/test_unidad_nueva.py` (it builds the question window with `ui.tk_agente`). Commit «El asistente y la pregunta del agente apuntan sus tiempos en el equipo con PRDRIVE_PERF=1».

**Wave 2 budget:** `modulos.*` and every `widgets.*` unchanged; the timing check's medians unchanged (marks are off there).

---

## Wave 3 (after Wave 2 is merged)

### Task 7: Tk 8.6 — what stays, what goes, and say so

No production code is removed.

**Files:** `docs/agents/reference/ui.md` («Which Tk»); `tests/_vista.py` (gains `estilos(raiz)`, the 10-line helper with the Tk 8.6 fallback now in `tests/test_tk_visor.py`), `tests/test_tk_visor.py` and `tests/test_tk_tabla.py` (both import it from `tests/_vista.py`; `test_tk_tabla.py`'s `ttk::style theme styles` call goes through it); docstrings only: `ui/theme.py` `nitidez()` (drop the claim that Tk 9 changes the DPI line: `common/pins.py` measured it does not), `ui/icons.py` module docstring (drop «the light install uses the painter on Tk 8.6»: the light install refuses Tk < 9), `ui/tk.py` `_arrancar_barra` (delete its last sentence about a hypothetical Tk; do not touch the code), `install/runtime_bin.py` (examples naming 3.13 → 3.14.8).

- [ ] **Step 1:** «Which Tk» names the three Tk 8.6 reaches (a 3.13 device's window; the agent's question on the host's `pythonw.exe`; the launchers' host-Python fallbacks), the **keep list** (the hard need: `theme.pista_campo()`'s `TclError` → `pista_etiqueta()`, without which «Ajustes» fails before «Actualizaciones» and the device falls to the console, which cannot update), and the **removal list with its precondition** (no 3.13 device left AND host windows gated to Tk 9): `pista_etiqueta`, `gripcount=0`, the window PNG branch of `icons._foto`, `USAR_SVG`/`PRDRIVE_SIN_SVG` and the «no» path of `svg_disponible`, `_SinSvg` (after making the SVG describer total), and their tests (`tests/test_iconos_svg.py` 155-185 and 232-341, `tests/test_controles.py` 211-217 and 250-270).
- [ ] **Step 2 (local record, no CI leg):** run the whole suite once on `/usr/bin/python3.12` (Tk 8.6) under xvfb before and after; the report states `N/N` and the files that fail on 8.6 with the reason (expected: `test_tk_tabla.py` before, none after). Stop rule: if anything other than the listed docstrings would have to change to pass on 8.6, report it and do not change it.
- [ ] **Step 3:** full suite (Tk 9). Commit «Tk 8.6: lo que queda y por qué, y las pruebas que aún lo pisan».

### Task 8: The frontend real-machine checklist and the cloud row F21 (`.pyc` between systems)

**Files:** Create `docs/superpowers/pruebas/2026-10-09-frontend-pendiente-en-real.md`, `tests/maquina/productor_pyc.py`, `tests/maquina/f21_pyc_entre_sistemas_windows.py`; Modify `.github/workflows/maquina-real.yml`, `docs/superpowers/pruebas/maquina-real-resultados.md`.

- [ ] **Step 1: The checklist**, this skeleton: `# Plan: el frontend rápido en máquinas de verdad` · `Fecha: 2026-10-09 · Estado: **por hacer**.` · `## Equipos` (`W`: Windows 11 x64 with a prdrive device; `W10`: Windows 10 22H2; `L`: a Linux desktop) · one table `| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |` with rows `R1` cold start from a USB stick (≈80 MB, ≈190 files, OS cache cold) of the main window and «Parejas» (W, L; stopwatch or `PRDRIVE_PERF=1`: `logs/perf.log`), `R2` the look on a real screen, light and dark, 100/150/200 %, of every window of stages 1b–3 (main, «Parejas», «Ajustes» and its panes, «Dispositivos», the flags editor, the wizard from the stage 3 `.exe`, the agent's question) (W, W10), `R3` F21 = «nube» (link to `maquina-real-resultados.md`) · `## Qué hacer con lo que salga` (a difference → an issue with the screenshot; a time → the results file).
- [ ] **Step 2: F21, Linux → Windows.** In `maquina-real.yml`: a new job `pyc-linux` (ubuntu-latest): checkout; setup-python 3.11; the pinned runtime with `python tests/_runtime_ci.py runtime linux-x64 "$RUNNER_TEMP/runtime" "$RUNNER_TEMP/prdrive-cache"` (cached with `actions/cache` keyed by `python tests/_runtime_ci.py clave`, as `tests.yml` does); `python tests/maquina/productor_pyc.py "$RUNNER_TEMP/f21-arbol"`; `actions/upload-artifact@v4` name `f21-arbol`. The Windows matrix leg gets `needs: pyc-linux` with `if: ${{ !cancelled() }}` and a `download-artifact` step into `$RUNNER_TEMP/f21-arbol`, path exported as `F21_ARBOL`. `productor_pyc.py`: copies `common/`, `ui/`, `penwatch.py` into `<dest>/.prdrive/`, runs `install.deploy.precompilar(app, python, biblioteca=False)` with the pinned Linux interpreter, then writes one extra module `control_marca_tiempo.py` whose source mtime is set to an ODD second (`os.utime(src, (T | 1, T | 1))`, integer T) and compiles it in TIMESTAMP mode (`py_compile.compile(..., invalidation_mode=PycInvalidationMode.TIMESTAMP)`); writes a manifest (each `.pyc`: name, flags, source hash, size) next to the tree. `f21_pyc_entre_sistemas_windows.py` (`CODIGO = "F21"`, `SISTEMA = "W"`): for `fat32` and `exfat` (`comun.por_cada`), `comun.volumen_windows(tipo)` (no fixed letter), `shutil.copytree(F21_ARBOL, <letra>:\.prdrive)`, snapshot every `__pycache__/*.pyc` (name, flags, hash, `mtime_ns`, sha256), then ONE run of the pinned windows-x64 Python: `python -I -v -c "import sys; sys.path.insert(0, ROOT); import importlib; [try-import each module]"` where the modules are the stems of the `.cpython-314.pyc` files found (each import in `try/except ImportError`; Linux-only modules such as `ui.bandeja_linux` and `common.dbus` are expected to fail and counted, never fatal), then checks: every checked-hash `.pyc` byte-identical after the run; `-v` says «matches» for them; `control_marca_tiempo` rebuilt («code object from») — and the module also records `os.stat(src).st_mtime` on the volume: if FAT32 rounded the odd second so the timestamp `.pyc` still matches, it notes «control no aplicable en <tipo>» instead of failing; a source touched with the same size and mtime is rebuilt for a checked-hash module. `RESULTADO F21 W ok N/N · …` per the `real-machine-tests` skill.
- [ ] **Step 3:** add `install/deploy.py`, `install/runtime_bin.py`, `common/pins.py`, `install/platforms.py`, `tests/_runtime_ci.py` to `maquina-real.yml`'s `pull_request` paths.
- [ ] **Step 4:** `python -m py_compile tests/maquina/*.py`; the director pushes (a push touching `tests/maquina/**` runs `todas`) and records the `RESULTADO` lines. Commit «Lo que queda por probar en una máquina de verdad, y los .pyc de un sistema a otro en la nube».

---

## Wave 4

### Task 9: Close the stage
- [ ] Timing check on the merged tip: every count at or under its ceiling; medians unchanged by the marks.
- [ ] `PRDRIVE_PERF=1 xvfb-run … tests/rendimiento/correr.py --pr . --base . --trabajo <tmp> --python <runtime> --rondas 1` locally: the copied `perf-*.log` files hold one line per moment of the table; each within ±20 % (or ±10 ms) of the driver's number for the same moment and round, except `start-*` (device clock from process creation, the driver's from before spawning: said, not hidden).
- [ ] `docs/superpowers/pruebas/<date>-etapa-4-resultados.md`; spec «Estado» gets «Etapa 4 hecha, revisada y medida: `docs/superpowers/pruebas/<fichero>`». Commit «Etapa 4: lo medido y lo que queda por hacer en una máquina de verdad».

---

## Decisions for the owner (taken here with a default; to review)

1. **No Tk 8.6 code is removed in stage 4.** Removing it later needs both preconditions; gating host windows to Tk 9 (the agent install refusing a host Python below Tk 9, as the light install does) is a product decision outside this plan.
2. **`start-*` counts from process creation** (OS APIs), so it includes Python's start-up like the driver's T0 (which starts before spawning: a few ms apart).
3. **F21 calls `deploy.precompilar` on a copied tree** in the cloud: nothing is deployed (no rclone, no config, no device), so the plan reads it as within the `real-machine-tests` skill's «never deploy a device».
4. **The «Ajustes» panes stay as they are**; the binary-alpha measurement (`alfa-binario-pintor.yml`) informs the owner's decision.
5. **`perf.log` lives in `logs/`** (the folder «Abrir los logs» opens), created by the first mark; host windows write next to the agent's log only if the host folder exists.
6. **Details are numbers and fixed words only** (no pair names, paths or hosts).
7. **Off in every build** unless `PRDRIVE_PERF` is set; how to set it per entry point (Linux `PRDRIVE_PERF=1 ./runsync.sh`; Windows `set PRDRIVE_PERF=1` then `runsync.bat`) goes in `ui.md` and the device guide is not changed.
8. **Lines are buffered and written by a background thread** (never on the Tk thread); a crash can lose the last second of marks.
9. **The Windows accessibility check** (Tk 9.0.4's DLL and UI Automation) stays an open question of the spec, not a stage 4 row.
