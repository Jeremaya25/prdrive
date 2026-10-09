# Fast frontend, stage 4 («Limpieza») Implementation Plan

> **For agentic workers:** builders are **Haiku**, reviewers **Sonnet** (owner, 09/10: the small changes that touch every window go to Haiku, the quickest). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the device can time its own windows (`PRDRIVE_PERF=1`), the Tk 8.6 leftovers are documented and trimmed to what a 3.13 device still needs, and the real-machine checks the stages left open are written down or run in the cloud.

**Architecture:** one shared timing helper in the `ui` package (already imported by every window, so no new module before the first paint), then one small task per window file that only adds marks. The Tk 8.6 work deletes nothing a 3.13 device or a Tk 8.6 host needs. The cloud row reuses `tests/maquina/` and its VHD/loop helpers.

**Tech Stack:** Python stdlib, Tk 9 (the device runtime 3.14.8 / Tk 9.0.4), GitHub Actions (`maquina-real.yml`).

**Spec:** `docs/superpowers/specs/2026-10-08-frontend-rapido-design.md` (stage 4 = its «Limpieza»); the stage 3 plan's «Appendix: stage 4»; the maps written for this plan (Tk 8.6 paths, timing hook points, real-machine infrastructure), summarised in each task.

## Global Constraints

- **Tk 9 is the only supported Tk** for new code; but **nothing a 3.13 device (Tk 8.6.15 on Windows) needs to open its window and reach «Ajustes → Actualizaciones → Actualizar…» is removed**, and neither is anything a Tk 8.6 *host* Python needs (the agent's «¿Atender esta unidad?» runs `pregunta.py` with the host's `pythonw.exe`; the full launcher's last step and the light launcher run a host Python).
- `PRDRIVE_PERF` unset, `""` or `"0"` = off, and off costs one `os.environ.get` per mark: no import, no file, no `after_idle`.
- No new module imported before any window's first paint (`presupuesto.toml` `modulos.*` unchanged).
- A mark never writes through `store.write_json`/`write_text` (the timing check counts those: `escrituras.marcar` = 0), never inside the timed span, and a failed write (read-only or ejected device) is swallowed.
- `penwatch.py` and `runsync.py` untouched; stdlib only; Spanish comments and user text; `docs/agents/` in English.
- Every task: its tests fail first, the full suite passes on the Tk 9 runtime under xvfb, and CI (Linux, Windows, Python 3.11 without display) is green before the next merge.

## Review Focus

1. **The mark and the driver measure the same span.** A mark queued with `after_idle` at the end of the change fires after the redraw the change queued; a mark queued before `ensenar()` fires before the reveal (Windows cloak) — queue after it returns.
2. **A window on a read-only, full or just-ejected device** with `PRDRIVE_PERF=1` opens and works exactly as without it.
3. **Host-side windows** (wizard, agent question) have no device: they write to the host's prdrive folder when it exists and nothing otherwise.
4. **A 3.13 device on Tk 8.6** still opens its main window, «Ajustes» (whose search box needs `theme.pista_etiqueta()`), and «Actualizar…».
5. **The `.pyc` row's negative control**: a timestamp-mode `.pyc` compiled on Linux is rebuilt on the FAT32/exFAT volume on Windows (the reason for checked-hash), and the checked-hash ones are not.

---

## Wave 1

### Task 1: The timing helper (`ui.perf_*` in `ui/__init__.py`)

**Files:** Modify `ui/__init__.py`; Create `tests/test_perf.py`; Modify `docs/agents/reference/ui.md` (a «Timing on the device» bullet), `docs/agents/reference/commands-testing.md` (the env var next to `PRDRIVE_SIN_SVG`/`PRDRIVE_TEMA`).

**Interfaces (produced; Tasks 2–6 use exactly these):**
- `perf_activo() -> bool` — reads `PRDRIVE_PERF` per call (like `theme.elegir_tema()`), so tests can toggle it.
- `perf_marca(momento: str, ms: float, *, host: bool = False, **detalle) -> None` — when active, appends one line `«<store.stamp()> <momento> <ms:.1f> ms <k=v …>»` to `model.LOG_DIR / "perf.log"` (device) or, with `host=True`, to `common.equipo.DIR / "perf.log"` only if that folder exists; trims first with `store.recortar_diario(ruta)`; `open(ruta, "a")`; any `OSError` swallowed. `model`, `store`, `equipo` imported inside the function, and the directory read at call time (tests rebind `LOG_DIR`, `STATE_DIR`, `equipo.DIR`).
- `perf_al_pintar(widget, momento: str, t0: float, **detalle) -> None` — when active, `widget.after_idle(...)` a callback that computes `(perf_counter() - t0) * 1000` and calls `perf_marca`; when off, returns at once. Swallows a `TclError` from a destroyed widget.

- [ ] **Step 1:** `tests/test_perf.py` (headless, plus one Tk case): off → no file, no `after_idle` queued (wrap `widget.after_idle` to count); on → one line per mark with the moment and ms; `host=True` without the host folder → no file; read-only log dir → no exception; 400 marks keep the file under `store.DIARIO_TOPE`; `perf_al_pintar` fires after a queued redraw (configure a label, call it, `update()`, the line exists) and after the widget is destroyed does nothing. Run, see it fail.
- [ ] **Step 2:** implement the three functions in `ui/__init__.py`.
- [ ] **Step 3:** `python3 tests/test_imports_perezosos.py`, `tests/test_perf.py`, full suite. Commit «El dispositivo puede apuntar lo que tardan sus ventanas (PRDRIVE_PERF=1)».

---

## Wave 2 (five tasks in parallel, each in its own file; they only add marks)

Each task: add the marks listed, each as `t0 = time.perf_counter()` at the start point and `ui.perf_al_pintar(<widget>, "<momento>", t0)` (or `perf_marca` for a span that ends without a paint) at the end point; a test per file in `tests/test_perf.py`'s style (`PRDRIVE_PERF=1`, real windows from the existing fixtures of that file's tests, assert each moment's line appears once and nothing appears with it off); the file's existing tests unchanged and green. Start and end points come from the hook-point map (file:line at `2cff5a1`; re-locate by function name if lines moved).

### Task 2: Main window and pass window (`ui/tk.py`)
Moments: `start-main` (start: first line of `ui.start()`; end: queued after `ensenar(root)` returns, before `mainloop`), `llega-instantanea` (`llegar`, end after `la_compartida().poner(inst)`), `marcar` (`al_marcar`), `sincronizar-ventana` (`sincronizar` → end after `ensenar()` of the pass window in `output_window`), `volver-pasada` (`al_destruir` of the pass window → end of `al_cerrar`), `log-10k` (first `_volcar` insert → `terminado`), and a generic mark in `mostrar()` (end before `wait_window`) named by the caller (`mostrar(..., momento=None)`, default no mark). Commit «La ventana principal y la de la pasada apuntan sus tiempos con PRDRIVE_PERF=1».

### Task 3: «Parejas» (`ui/tk_pairs.py`)
Moments: `open-parejas`/`reabrir-parejas` (`abrir_parejas` in `ui/tk.py` passes `momento="open-parejas"` to `mostrar` — coordinate: Task 2 owns `mostrar`'s parameter, this task only passes it from `tk_pairs.open_dialog`), `catalogo-llega` (`llegado` → after `refrescar(...)`), `elegir-fila`/`elegir-pareja` (`ListaParejas.elegir`), `open-flags` (`EditorPareja.editar_flags` → `mostrar` in `flags_form`), `open-dispositivos` (`ver_flota`). Commit «Parejas apunta sus tiempos con PRDRIVE_PERF=1».

### Task 4: «Ajustes» (`ui/tk_doctor.py`)
Moments: `open-ajustes` (`abrir_ajustes` → `mostrar` in `open_dialog`), `pane-<clave>` (`elegir(clave)` → after `ajustar(panel)`/`dibujar(clave)`), `volver-ajustes` (after `wait_window` returns in `abrir_ajustes` → end of `abrir_ajustes`, in `ui/tk.py`: this one mark is Task 2's). Commit «Ajustes apunta sus tiempos con PRDRIVE_PERF=1».

### Task 5: «Dispositivos» (`ui/tk_fleet.py`)
Moments: `llega-flota` (`llegada` → after `pintar(...)`), `elegir-dispositivo` (the table's `al_elegir` → after `repasar`). Commit «Dispositivos apunta sus tiempos con PRDRIVE_PERF=1».

### Task 6: Host windows (`ui/tk_install.py`, `ui/tk_agente.py`, `pregunta.py`)
Moments with `host=True`: `start-wizard` (`run_wizard` → before `mainloop`), `paso-<nombre>` for every wizard step (`Wizard.ir` → end of `repintar`), `start-agente` (`pregunta.py` start → before `root.mainloop()` in `tk_agente`). Commit «El asistente y la pregunta del agente apuntan sus tiempos en el equipo con PRDRIVE_PERF=1».

**Wave 2 budget:** `modulos.*` and every `widgets.*` unchanged; the timing check's medians unchanged (marks are off there).

---

## Wave 3 (parallel with Wave 2: different files)

### Task 7: Tk 8.6 — what stays, what goes, and say so

Per the Tk 8.6 map: **no production code is removed** (every 8.6-only branch is reached by a 3.13 device or a Tk 8.6 host).

**Files:** `tests/test_tk_tabla.py` (its `ttk::style theme styles` call crashes on Tk 8.6: reuse the `estilos()` helper with the 8.6 fallback from `tests/test_tk_visor.py`), `tests/test_iconos_svg.py` (the `if tk.TkVersion < 9` branch stays: it is what proves the 8.6 probe says «no»), stale comments (`ui/theme.py` `nitidez()` docstring about the Tk 9 DPI line, which `common/pins.py` measured does not change; `ui/icons.py` module docstring about the light install on Tk 8.6; the hypothetical-Tk sentence of `ui/tk.py` `_arrancar_barra`; `install/runtime_bin.py` examples naming 3.13; the duplicated `sello = leer_sello(...)` in `common/components.py`), `docs/agents/reference/ui.md` «Which Tk».

- [ ] **Step 1:** «Which Tk» names the three Tk 8.6 reaches (a 3.13 device's window; the agent's question on the host's `pythonw.exe`; the launchers' host-Python fallbacks), the **keep list** (with the one hard need: `theme.pista_campo()`'s `TclError` → `pista_etiqueta()`, without which «Ajustes» fails before «Actualizaciones» and the device falls to the console, which cannot update), and the **removal list with its precondition** (no 3.13 device left AND host windows gated to Tk 9): `pista_etiqueta`, `gripcount=0`, the window PNG branch of `icons._foto`, `USAR_SVG`/`PRDRIVE_SIN_SVG` and the «no» path of `svg_disponible`, `_SinSvg` (after making the SVG describer total), their tests.
- [ ] **Step 2:** the test and comment fixes above; `tests/test_tk_tabla.py` passes on `/usr/bin/python3.12` (Tk 8.6) under xvfb too (local check only: there is no CI leg).
- [ ] **Step 3:** full suite (Tk 9). Commit «Tk 8.6: lo que queda y por qué, y las pruebas que aún lo pisan».

### Task 8: The frontend real-machine checklist and the cloud row F21 (`.pyc` between systems)

**Files:** Create `docs/superpowers/pruebas/2026-10-09-frontend-pendiente-en-real.md`; Create `tests/maquina/f21_pyc_entre_sistemas_linux.py` and `..._windows.py`; Modify `.github/workflows/maquina-real.yml`, `tests/maquina/comun.py` (only helpers the row needs), `docs/superpowers/pruebas/maquina-real-resultados.md` (the result rows).

- [ ] **Step 1: The checklist** (rows a person does, the 2026-09-25 checklist's format): cold start from a USB stick (≈80 MB, ≈190 files; OS cache cold) of the main window and «Parejas» on a real Windows and a real Linux (stopwatch or `PRDRIVE_PERF=1`); the look on a real Windows 10 and 11 screen, light and dark, 100/150/200 %, of every window of stages 1b–3 (main, «Parejas», «Ajustes» and its panes, «Dispositivos», the flags editor, the wizard from the Task 6 `.exe`, the agent's question); and F21 below as «nube».
- [ ] **Step 2: F21, Linux → Windows.** The Linux leg (a producer job before the matrix, or a step with `if: ${{ !cancelled() }}`: a matrix `needs` is skipped if a leg fails) fetches the linux-x64 runtime (`tests/_runtime_ci.py`), copies `common/`, `ui/`, `penwatch.py` into a temp `.prdrive/`, runs `install.deploy.precompilar(app, python, biblioteca=False)` and, as the negative control, compiles one extra module in **timestamp** mode; uploads the tree. The Windows module downloads it, `comun.volumen_windows("fat32")` and `("exfat")` (no fixed letter), copies the tree to `<letra>:\.prdrive`, runs the pinned windows-x64 Python with `-I` and `-v` importing every module, and checks: every checked-hash `.pyc` byte-identical after the imports (name, flags, hash, `mtime_ns`, sha256), `-v` says «matches» for them, the timestamp-mode one is rebuilt («code object from»), and a source touched with the same size and mtime is rebuilt. `RESULTADO F21 W ok N/N · …` per the skill's format. The reverse direction (Windows → Linux) is a «parcial» note unless it fits in the same run.
- [ ] **Step 3:** add `install/deploy.py`, `install/runtime_bin.py`, `common/pins.py`, `install/platforms.py` to `maquina-real.yml`'s `pull_request` paths; cache the runtime download like `tests.yml` does.
- [ ] **Step 4:** `python -m py_compile tests/maquina/*.py`; push (a branch push touching `tests/maquina/**` runs `todas`); read `RESULTADO` lines per the `real-machine-tests` skill; record them. Commit «Lo que queda por probar en una máquina de verdad, y los .pyc de un sistema a otro en la nube».

---

## Wave 4

### Task 9: Close the stage
- [ ] Timing check on the merged tip: every count at or under its ceiling, medians unchanged by the marks.
- [ ] One manual `PRDRIVE_PERF=1` run of the harness's sample device locally: `logs/perf.log` has one line per moment, within ±20 % of the driver's warm-up numbers for the same moments (the device clock starts later for `start-*`: said, not hidden).
- [ ] `docs/superpowers/pruebas/2026-10-xx-etapa-4-resultados.md`; spec «Estado» line; `AGENTS.md` only if a rule changed.

---

## Decisions for the owner (taken here; to review)

1. **No Tk 8.6 code is removed in stage 4** (Task 7): a 3.13 device and a Tk 8.6 host still reach it. Removing it later needs both preconditions; gating host windows to Tk 9 (the agent's install refusing a host Python below Tk 9, as the light install already does) is a product decision, not in this plan.
2. **`start-main` on the device starts at `ui.start()`**, not at process start (the driver's T0 includes the interpreter's boot): the device number is smaller by Python's start-up, and the docs say so.
3. **F21 calls `deploy.precompilar` on a copied tree** in the cloud: the `real-machine-tests` skill says «never deploy a device»; this deploys nothing (no rclone, no config, no device), but it is device-adjacent: the plan reads it as within the rule.
4. **The «Ajustes» panes stay as they are in stage 4.** Reaching 60 ms on Windows needs fewer native widgets (a canvas) or cheaper painting (binary alpha); the binary-alpha measurement (`alfa-binario-pintor.yml`) informs that decision, which is the owner's.
