# Frontend rápido, etapa 1a (sin riesgo visual) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every window starts sooner and the pass window stops choking on long logs, with not one pixel of the 0.7.1 look changed; and from now on every PR is timed against `main` on Windows and Linux.

**Architecture:** Eight independent changes, each its own commit:
- the permanent timing check and a Tk 9 CI leg, first, so the rest is measured;
- the PNG encoder memoised and a per-interpreter font table;
- lazy imports plus a tiny `pregunta.py` entry for the agent's question;
- the service noticing a stop request every second, and the relaunched window waiting for its parent's lock;
- `.pyc` precompiled on the device with its own runtime;
- the pass log written in blocks with the whole output kept aside, and a cheaper waiting bar;
- a time-limited system query in `ui/watch.py`;
- the «Parejas» editor that no longer loses unsaved edits when the catalogue arrives.

**Tech Stack:** Python 3.11+ stdlib only; tkinter (Tk 8.6 and Tk 9.0.4); plain-script tests (`tests/_harness.Checks`); GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-08-frontend-rapido-design.md` (version 2, §3, §4, §5, §2 "cuatro cosas pequeñas", «Etapas» 1a).

**Reference implementations.** Each task was implemented and tested in a scratch copy by a reader agent while the plan was prepared.

- Artifact paths are relative to this session's scratchpad, `/tmp/claude-0/-home-user-prdrive/03b34008-f2da-52c1-8cde-5efd2782344d/scratchpad/`.
- Apply the artifact, review every hunk against the task's Interfaces, then run the task's tests.
- If an artifact is missing (another session), implement from the Interfaces and the test list. They carry every decision.
- All artifacts were made against code identical to this branch's current code (`44423a3`); the branch since then only adds docs and `banco/`.

## Global Constraints

- **Python and dependencies:** stdlib only; Python ≥ 3.11 for all code (CI leg 1). Device runtime is python-build-standalone 3.14.8 with Tk 9.0.4 (CI leg 2).
- **Language:** comments, docstrings and user-visible text in Spanish; `docs/agents/` in English; follow `docs/agents/code-writing-conventions.md`.
- **Tk rules:**
  - `import tkinter` only inside functions.
  - `tk_*` modules only draw.
  - `theme.py`/`icons.py` own colours, fonts and glyphs.
  - Distances go through `theme.medida()`.
- **Indirection points:** a new one is a module-level function tests replace, added to the registry in `docs/agents/reference/commands-testing.md`.
- **New modules:** every new root/`common`/`ui`/`install` module is listed in a `.claude/rules/*.md` `paths` (`tests/test_reglas_claude.py` fails otherwise).
- **`penwatch.py` must not change one byte.** `penwatch.copia_al_dia()` compares its bytes, and any change shows every installed watcher as «desfasado».
- **No visual change in this stage.** The 25 headless icon outputs stay byte-identical.
- **Both legs, every task, before its commit:**
  - Tk 8.6: `xvfb-run -a -s "-screen 0 1920x1080x24" /usr/bin/python3.12 tests/run_all.py`
  - Tk 9: `xvfb-run -a -s "-screen 0 1920x1080x24" $SCRATCH/runtime-linux64/bin/python3 tests/run_all.py`
  - `$SCRATCH` is the scratchpad above.
  - A known flake under CPU load is `test_avisos_carpeta.py` (inotify timing): re-run it alone before calling it a failure.
- **Commits:** on `claude/adoring-pascal-5j258r`; Spanish message saying what changes for the user; footer lines as in recent commits.
- **No PR:** the owner opens it when they are back.

## Review Focus

1. **FAT32/exFAT device moved between Windows and Linux:** the `.pyc` must not be rewritten on every host switch (checked-hash). Test: Task 5, "mtime shifted 7 h, pyc reused".
2. **Read-only or full device, or no runtime for this host:** install and update still succeed; precompile silently does nothing. Test: Task 5, "file where `__pycache__` should be → False, deploy continues".
3. **A pass printing more than 20 000 lines:** «Guardar el log» saves every line. Test: Task 6, 25 000-line end-to-end save.
4. **Typing in the «Parejas» editor while a slow remote catalogue arrives:** the text survives. Test: Task 8, real threads with `RemotoLento`.
5. **The service's failure pop-up opened twice in the same thread:** no dead fonts. Test: Task 2, `theme._LETRA == {}` after two pop-ups in `test_daemon_aviso.py`.

---

### Task 1: Permanent timing check and the Tk 9 CI leg

**Files:**
- Create:
  - `tests/_runtime_ci.py`
  - `tests/rendimiento/{correr.py, informe.py, driver.py, dispositivo.py, suelo.py, utiles.py, captura.py, entrada.py, presupuesto.toml}`
  - `tests/test_rendimiento_informe.py`
  - `.github/workflows/rendimiento.yml`
- Modify:
  - `.github/workflows/tests.yml` (new job `tests-tk9`; job `tests` byte-for-byte unchanged)
  - `.claude/rules/commands-testing.md` (paths `tests/rendimiento/*`, `.github/workflows/tests.yml`, `.github/workflows/rendimiento.yml`)
  - `docs/agents/reference/commands-testing.md` (Verification; Commands; new «Timing check» section)
  - `docs/agents/reference/provisioning.md` («The UI is measured on both»)
  - `AGENTS.md` (CI line; `tests/` layout line)
- Delete: `banco/` and `.github/workflows/banco-ui.yml` (`git rm -r`).
- Artifacts: `plan/ci/out/` (copy the tree as-is); notes `plan/notas-ci.md`.

**Interfaces:**
- Produces:
  - `python tests/_runtime_ci.py runtime PLAT DESTINO CACHE` writes `PRDRIVE_PYTHON=<interpreter>` to `$GITHUB_ENV`.
  - `python tests/_runtime_ci.py clave` prints `20261001-3.14.8-tk-xft-9.0.4-1`.
  - `python tests/rendimiento/correr.py --pr DIR --base DIR --trabajo DIR [--python PY] [--rondas 7] [--capturas]`.
  - Budget file `tests/rendimiento/presupuesto.toml` with `[techo]`, `[techo.linux]`, `[techo.windows]`, `[meta]`, `[meta_ms]`, and flat keys such as `"widgets.parejas.p50"`, `"modulos.main"`.
- Later tasks lower ceilings in `[techo]` when they cut a count. Task 3 sets `modulos.main = 225` and `modulos.agente = 161`.
- The driver's agent flow runs `pregunta.py --nombre X --segundos N [--cambiada]` if the tree has it (Task 3).

- [ ] **Step 1:** `git rm -r banco .github/workflows/banco-ui.yml`; copy `plan/ci/out/` over the repo root.
- [ ] **Step 2: Temporary trigger.** In both `tests.yml` (job `tests-tk9` only) and `rendimiento.yml`, add `push: branches: [claude/adoring-pascal-5j258r]` with the comment `# TEMPORAL: quitar antes del PR`. `rendimiento.yml` uses `inputs.base || 'main'` as its base on push. This is the only way to get Windows evidence before the owner opens a PR; Task 9 removes it.
- [ ] **Step 3: Run the report's own test.**
  - Run: `python3 tests/test_rendimiento_informe.py`
  - Expected: 24 OK, 0 failures.
- [ ] **Step 4: Run the rules and the runtime helper.**
  - Run: `python3 tests/test_reglas_claude.py`, then `python3 tests/_runtime_ci.py clave`.
  - Expected: rules OK; `20261001-3.14.8-tk-xft-9.0.4-1`.
- [ ] **Step 5: Local A/B of the tree against itself.**
  - Run: `xvfb-run -a -s "-screen 0 1920x1080x24" python3 tests/rendimiento/correr.py --pr . --base . --trabajo $SCRATCH/rend --python $SCRATCH/runtime-linux64/bin/python3 --rondas 2`
  - Expected: exit 0, `resumen.md` with no failures, "9 de 9 pintadas".
- [ ] **Step 6:** Both legs of the suite (Global Constraints). Expected: everything passes.
- [ ] **Step 7: Docs.** Apply the doc edits listed in `plan/notas-ci.md`: `AGENTS.md`, `commands-testing.md`, `provisioning.md`.
- [ ] **Step 8:** Commit «La CI mide cuánto tardan las ventanas frente a main y pasa la suite también con el Python del dispositivo».

### Task 2: PNG encoder without per-pixel work, and the font table

**Files:**
- Modify:
  - `ui/icons.py`: `_png` loop only.
  - `ui/theme.py`: `_Letra`, `_LETRA`, `ANCLA`, `_letra`, `_clave_letra`, `_fuente_fija`, `fuente_tk`, `_metricas`, `_instaladas`, `_familias_instaladas`; callers `relleno_control`, `icono_linea`, `ancho_rotulo`, `familia`, `cargar_fuentes`, `olvidar`.
  - `tests/test_daemon_aviso.py`
  - `docs/agents/reference/ui.md`, `docs/agents/reference/service.md`
  - `.claude/rules/ui.md` (path `tests/test_iconos_bytes.py`)
- Create: `tests/test_iconos_bytes.py`, `tests/test_tk_letra.py`.
- Artifact: `plan/letra/propuesta.diff`; notes `plan/notas-letra.md`.

**Interfaces:**
- `icons._png(rgba, size=None) -> bytes`: same signature; memoises per call by row identity (`id(fila)`) and pixel tuple. No module-level cache.
- `theme.fuente_tk(widget, rol: str = "texto") -> tkfont.Font`: public, one Font per (interpreter, `tk scaling`, font spec), kept alive by a hidden item on the raw-Tcl canvas `".prdrive-letra"`.
- `theme._metricas(widget, letra) -> tuple[int, int, int]`: `(linespace, ascent, size)`.
- `theme.olvidar(interp)` also drops `_LETRA[id(interp)]` and destroys its canvas.

- [ ] **Step 1:** Apply `plan/letra/propuesta.diff` (`git apply`).
- [ ] **Step 2: Hash pins.**
  - Run: `python3 tests/test_iconos_bytes.py`
  - Expected: 17 OK.
  - This pins 23 SHA-256 values in full and 2 by decompressed content (`ico()` `bf2cd2af…71f0`, `png_marca(32)` `ca1089bb…7e50`), because zlib-ng on Windows changes the compressed stream.
- [ ] **Step 3: Font table on both Tks.**
  - Run: `xvfb-run -a /usr/bin/python3.12 tests/test_tk_letra.py` and the same with `$SCRATCH/runtime-linux64/bin/python3`.
  - Expected: 36 OK each.
  - Key assertions: metrics equal a fresh `tkfont.Font` at scales 1.0/1.3333/2.0/2.6667; `apply()` creates ≤ 8 Fonts; a second interpreter in the same thread gets fresh fonts; `olvidar` empties `_LETRA`.
- [ ] **Step 4:** Both legs. Expected: everything passes (`test_daemon_aviso` includes `theme._LETRA == {}`).
- [ ] **Step 5:** Commit «Las ventanas se pintan antes: los iconos se codifican sin recorrer píxel a píxel y la letra se mide una vez».

### Task 3: Lazy imports and `pregunta.py`

**Files:**
- Create: `pregunta.py`, `tests/test_imports_perezosos.py`.
- Modify (Python):
  - `ui/__init__.py`, `ui/tk.py`, `ui/tk_update.py`, `common/update.py`, `runsync.py`
  - `agente.py` (`orden_pregunta`, `_preguntar`)
  - `install/agente.py` (`CODIGO_FICHEROS`), `build_installer.py` (`DATOS_FICHEROS`)
  - `tests/_agente_falso.py` (`preguntas()`)
  - tests: `test_unidad_nueva.py`, `test_agente_actualizar_unidad.py`, `test_agente_endurecido.py`, `test_install_agente.py`
- Modify (docs and rules):
  - `.claude/rules/agent.md` (path `pregunta.py`), `.claude/rules/ui.md` (path `tests/test_imports_perezosos.py`)
  - `AGENTS.md` (layout line; dependency rule)
  - `docs/agents/reference/`: `ui.md`, `updating.md`, `service.md`, `commands-testing.md`, `provisioning.md`, `agent.md`
  - `tests/rendimiento/presupuesto.toml` (`modulos.main = 225`, `modulos.agente = 161` in `[techo.linux]`)
- Artifact: `plan/imports/stage1a-imports.diff` (against `plan/imports/base/`); notes `plan/notas-imports.md`.

**Interfaces:**
- **`ui.tk` constants and preload functions:**
  - `PRECARGA = ("ui.tk_pairs", "ui.tk_doctor", "ui.tk_watch", "ui.tk_repair", "ui.tk_update")`
  - `PRECARGA_LLAVERO = ("common.cifrada", "common.keepassxc", "ui.llavero_editor", "ui.tk_llavero")`
  - `PAUSA_PRECARGA_MS = 1`
  - `precarga_de(config) -> tuple[str, ...]`
  - `precargar(nombres=PRECARGA) -> None` (swallows errors; indirection point)
  - `precargar_a_ratos(root, nombres) -> None` (an `after(1)` chain, one import per turn, never `after_idle`)
  - `linea_llavero(config)`
- **What stays at module level** (tests replace these there):
  - in `ui.tk`: `pair_status_notes`, `abrir`, `mostrar`, `output_window`, `working`, `ensenar`, `modal`, `pantalla_util`, `Visor`, `Sondeo`, `IS_WIN`, `_atributo_dwm`, `_encubrir`, `_tono`, and `progress`;
  - in `runsync`: `time`, `ui`, `model`, `prioridad`, `store`, `read_lock`, `pen_present`, `pareja_llavero`, `atender_llavero`, `daemon_cycle`.
- **`pregunta.leer(argv) -> tuple[str, int, bool] | None`.** `python pregunta.py --nombre N --segundos S [--cambiada]` exits with `tk_agente.main(...)`, or `tk_agente.SIN_VENTANA` (2) on bad arguments.
- **`agente.orden_pregunta(nombre, espera, cambiada) -> list[str]`** falls back to `[…/agente.py, "pregunta", …]` if `pregunta.py` is missing.
- **`install/agente.CODIGO_FICHEROS = ("pregunta.py", "agente.py", "penwatch.py", "VERSION")`.**

- [ ] **Step 1:** Apply `stage1a-imports.diff`. It edits `runsync.py`, which Task 4 also edits; apply this task first.
- [ ] **Step 2: Import closures and preload.**
  - Run: `python3 tests/test_imports_perezosos.py`
  - Expected: 21 OK headless.
  - Key assertions: `import ui`, `ui.tk`, `runsync`, `common.update` and `pregunta` load none of `PESADOS`; `import ui.tk` loads no `ui.tk_*`; `import pregunta` loads `ui.tk_agente` but neither `agente` nor `tkinter`; `precargar_a_ratos` schedules one job per name.
- [ ] **Step 3:** `python3 tests/test_unidad_nueva.py` and `python3 tests/test_install_agente.py`.
  - Expected: the command line is `[python, SCRIPT_DIR/"pregunta.py", "--nombre", …]`, with the fallback when it is missing.
  - Expected: `pregunta.py` exits 2 without arguments.
  - Expected: `pregunta.py` comes before `agente.py` in `CODIGO_FICHEROS`, and everything in it is in `DATOS_FICHEROS`.
- [ ] **Step 4:** Both legs. Expected: everything passes.
- [ ] **Step 5:** Commit «La pregunta del agente y la ventana arrancan antes: cada módulo se importa cuando hace falta».

### Task 4: The service stops within a second; the relaunched window waits for its parent

**Files:**
- Modify: `runsync.py`, `tests/test_auto.py:89-93`, `tests/test_instancia_unica.py`, `docs/agents/reference/service.md`, `docs/agents/reference/agent.md`, `docs/agents/reference/commands-testing.md`.
- Create: `tests/test_servicio_ritmo.py`.
- Artifact: the `runsync.py` and tests hunks of `plan/servicio/stage1a-servicio.patch`; notes `plan/notas-servicio.md`.

**Interfaces:**
- **`runsync` constants:**
  - `STOP_POLL_SECONDS = 1.0`: new. The daemon's idle loop checks `stop_requested()`/`pen_present()` this often.
  - `POLL_SECONDS = 5.0`: unchanged. `read_lock()` and `atender_llavero()` are gated by `time.monotonic()` to this; `vigilar_llavero` keeps sleeping it.
  - `STOP_WAIT_STEP = 0.1`: new. `stop_previous_daemon()` sleeps this instead of the literal 0.3.
  - `STOP_WAIT_SECONDS = 15.0`: unchanged.
- **Relaunch wait:**
  - `ESPERA_PADRE = 3.0` and `PASO_PADRE = 0.05`.
  - `padre_pid() -> int`: `os.getppid()`; an indirection point.
  - `tomar_ui()` waits for the record to change or disappear, only on its first attempt and only when the record's pid is `padre_pid()`.
  - `_soltado_por_el_padre(visto) -> bool` does that wait.

- [ ] **Step 1:** Apply the `runsync.py` hunks onto the Task 3 result. Keep Task 3's function-level `from common import llavero` in `daemon_main` and this task's sliced loop.
- [ ] **Step 2: Rhythm.**
  - Run: `python3 tests/test_servicio_ritmo.py`
  - Expected: 16 OK.
  - Key assertions: a stop at t=1007.3 is seen within 1.0 s; `atender_llavero` and `read_lock` run at t = 1000.0 and 1005.0 only; the launcher returns after 6 sleeps of 0.1 s; with a real thread, `daemon.stop` ends the loop within 2 s.
- [ ] **Step 3: One instance.**
  - Run: `python3 tests/test_instancia_unica.py` and `python3 tests/test_auto.py`.
  - Expected: 84 OK. Parent releasing at +0.3 s gives `None` after 0.30–0.36 s; parent never releasing gives the record after `ESPERA_PADRE`; a non-parent holder gives a refusal with no wait.
- [ ] **Step 4:** Docs from `notas-servicio.md` (C and B): service.md «Rhythm» and «One window at a time»; agent.md: 0.3 s becomes 0.1 s; commands-testing.md: `runsync.padre_pid()`.
- [ ] **Step 5:** Both legs. Commit «Al abrir la ventana, el servicio para en un segundo, y tras actualizar la ventana nueva ya no choca con la vieja».

### Task 5: `.pyc` precompiled on the device

**Files:**
- Modify:
  - `install/deploy.py`, `install/platforms.py`, `install/components.py`, `install/agente.py`, `prdrive-install.py`
  - tests: `test_install_agente.py`, `test_install_components.py`
- Create: `tests/test_precompilar.py`.
- Docs: `docs/agents/reference/updating.md`, `provisioning.md`, `commands-testing.md`, `agent.md`; `docs/guia/instalacion.md`.
- Artifact: the `install/*`, `prdrive-install.py` and tests hunks of `plan/servicio/stage1a-servicio.patch`.

**Interfaces:**
- **`install/deploy.py` constants:**
  - `PRECOMPILAR_TOPE = 60.0`
  - `PRECOMPILAR_SUELTOS = ("penwatch.py",)`
  - `BIBLIOTECA` (the stdlib list; a test guards it with an `ast` scan)
- **`deploy.precompilar(destino, python, *, prefijo=None, biblioteca=True, tope=PRECOMPILAR_TOPE, progreso=None) -> bool`:**
  - an indirection point; never raises; accepts `python=None`;
  - checked-hash pycs;
  - skips files already up to date;
  - runs `python -I [-X pycache_prefix=P]` with an inline script.
- **`deploy.precompilar_dispositivo(device_root, progreso=None) -> bool`:** uses `platforms.device_interpreter(root, platforms.host(), consola=True)`, so nothing runs without a stamped runtime for this host.
- **Where it is called:**
  - at the end of `deploy_code(…, progreso=None)`;
  - in `apply_platforms()` when a runtime for this host lands;
  - in `cmd_update_components(raiz, relevo=None, fase=None)` when the host runtime's stamp changed (`platforms.sello_del_equipo(device_root) -> str | None`).
- **`AvanceRelevo.precompilando()`:** shows `(0.99, "Dejando listo el arranque rápido…")`.
- **`install/agente.calentar_codigo(codigo, python, progreso=None) -> bool`:** called in `preparar()` after `poner_runtime`; `prefijo=equipo.DIR/"pycache"`.

- [ ] **Step 1:** Apply the remaining hunks of `stage1a-servicio.patch`. `install/agente.py` already has Task 3's `CODIGO_FICHEROS`; keep both.
- [ ] **Step 2: Precompile.**
  - Run: `python3 tests/test_precompilar.py`
  - Expected: 35 OK.
  - Key assertions:
    - header flags `0b11` and the hash equal to `importlib.util.source_hash(src)`;
    - the source's mtime shifted −7 h is still imported from the same pyc;
    - a changed body with the same size and mtime is recompiled;
    - a second call rewrites nothing;
    - a broken `.py` does not stop the rest;
    - with a prefix, no `__pycache__` appears in the tree and the stdlib's own pycs are untouched;
    - `tope=0.001`, `python=None`, a missing interpreter, and a file where `__pycache__` should be all return `False` without raising;
    - `BIBLIOTECA` covers every stdlib import of the device code.
- [ ] **Step 3:** `python3 tests/test_install_components.py` and `python3 tests/test_install_agente.py`.
  - Expected: the relevo calls `fase()` once and precompiles once only when the stamp changes.
  - Expected: the agent warms `(prep.codigo, prep.python, equipo.DIR/"pycache")`.
- [ ] **Step 4:** Docs from `notas-servicio.md` (A). Both legs. Commit «Tras instalar o actualizar, el primer arranque ya no compila el programa entero».

### Task 6: The pass log in blocks, the whole output kept, and a cheaper waiting bar

**Files:**
- Modify: `ui/tk.py` (`output_window`, `_Salida`, `_volcar`, `LINEAS_VENTANA`, `PASO_BARRA_MS`, `SALTO_BARRA`, `_arrancar_barra`), `tests/test_tk_salida.py`, `tests/test_tk_espera.py`, `docs/agents/reference/ui.md`.
- Artifacts: `plan/ventana/patches/A-log-en-bloque.patch`, then `B-barra-de-espera.patch`; notes `plan/notas-ventana.md`.

**Interfaces:**
- **`LINEAS_VENTANA = 20_000`.**
- **`class _Salida`** (no Tk; `completa: list[str]`, `viva: bool`): `anadir(lineas) -> tuple[bool, list[tuple[str, str]]]`. It collapses consecutive progress lines inside and across batches, using the `progreso-vivo` mark.
- **`_volcar(texto, salida, lineas) -> None`:** one `insert` and one `see` per poll; trims the widget to the last `LINEAS_VENTANA` lines.
- **`guardar()`** writes `"".join(salida.completa)`.
- **The waiting bar:**
  - `PASO_BARRA_MS = 48` and `SALTO_BARRA = PASO_BARRA_MS / 12`.
  - `_arrancar_barra(barra)` calls Tcl `start 48 4`, falling back to `barra.start(48)`.

- [ ] **Step 1:** Apply A, then B (B is relative to A).
- [ ] **Step 2: The pass log.**
  - Run: `xvfb-run -a /usr/bin/python3.12 tests/test_tk_salida.py` and the same with the runtime.
  - Expected: 43 OK each.
  - Key assertions:
    - 25 000 lines in mixed batches leave the widget equal to the last 20 000 lines;
    - `insert` and `see` are called once per batch;
    - each tone covers exactly its lines, and no two progress lines are adjacent;
    - end to end, «Guardar el log» writes all 24 502 lines.
- [ ] **Step 3: The waiting bar.**
  - Run: `python3 tests/test_tk_espera.py` on both.
  - Expected: 26 OK. `working()` and `Indicador` run at `(48.0, 4.0)`; the fallback is asked for `[48]`.
- [ ] **Step 4:** ui.md edits from the notes. Both legs. Commit «La ventana de una pasada larga ya no se atasca, guarda el log entero y la barra de espera gasta la cuarta parte».

### Task 7: A time-limited system query from the UI

**Files:**
- Modify: `ui/watch.py`, `ui/tk_equipo.py`, `tests/test_watch.py`, `tests/test_install_wizard.py`, `docs/agents/reference/commands-testing.md`, `docs/agents/reference/penwatch.md`.
- Artifact: `plan/ventana/patches/C-consulta-en-ui-watch-sin-tocar-penwatch.patch`.

**Interfaces:**
- `watch.CONSULTA_S = 8.0` and `watch.CODIGO_TIEMPO = 124`.
- `watch.consulta(cmd: list[str], timeout: float = CONSULTA_S) -> subprocess.CompletedProcess`:
  - an indirection point;
  - returns 124 on timeout and 127 on `OSError`;
  - sets `CREATE_NO_WINDOW` only when `sys.platform == "win32"`.
- `tk_equipo.comprobaciones()` uses it, and 124 gives `(False, "el sistema no contesta")`.

- [ ] **Step 1:** Apply C. Run `python3 tests/test_watch.py` and `python3 tests/test_install_wizard.py`.
  - Expected: a silent child with `timeout=0.5` gives 124 in under 10 s, `print('hola')` gives `(0, "hola")`, and a missing binary gives 127.
  - Expected: return codes 0, 1 and 124 map to registrado, no está registrado and el sistema no contesta.
- [ ] **Step 2:** `git diff --stat -- penwatch.py` prints nothing. Docs. Both legs. Commit «Comprobar el arranque automático ya no puede colgar el asistente».

### Task 8: «Parejas» keeps unsaved edits when the catalogue arrives

**Files:**
- Modify: `ui/tk_pairs.py` (`EditorPareja.poner_explorable`, `pintar_eleccion`, `refrescar`, `cambiar_vista`), `tests/test_tk_segundo_plano.py`, `tests/test_tk_screens.py`, `docs/agents/reference/catalogue.md`.
- Artifact: `plan/ventana/patches/D-editor-parejas.patch`.

**Interfaces:**
- **`EditorPareja.poner_explorable(explorable: bool) -> None`:** sets the remote «Examinar…» state.
- **`pintar_eleccion()`:** the title, chip and buttons, split out of `cargar_editor()`.
- **`refrescar()`:** keeps the fields when `hay_cambios()` holds and the same pair stays selected.
- **`cambiar_vista()`:** sets `estado["cargado"] = None` after the user accepts discarding.

- [ ] **Step 1: The fix.**
  - Apply D. Run `xvfb-run -a /usr/bin/python3.12 tests/test_tk_segundo_plano.py` and `tests/test_tk_screens.py`, and the same with the runtime.
  - Expected: 106 OK in `test_tk_segundo_plano`.
  - Typed `/R/notas-nueva` survives the catalogue's arrival, the list updates, and «Examinar…» is normal.
  - Leaving the pair asks first; «Descartar» restores the original.
  - Without typing, the editor reloads `/R/notas-v2`.
  - The new `test_tk_screens` case fails on the old `tk_pairs.py`, which is the bug reproduced.
- [ ] **Step 2:** catalogue.md edit. Both legs. Commit «Parejas ya no borra lo que se está escribiendo cuando llega el catálogo del remoto».

### Task 9: Measure on Windows, set the ceilings, close the stage

**Files:**
- Modify: `tests/rendimiento/presupuesto.toml` (`[techo.windows]`), `.github/workflows/tests.yml`, `.github/workflows/rendimiento.yml` (remove the temporary `push` trigger only when the owner opens the PR).
- Create: `docs/superpowers/pruebas/2026-10-08-etapa-1a-resultados.md`.

- [ ] **Step 1: Push and read the runs.**
  - Push. Read the `Tests` run (jobs `tests` and `tests-tk9`, Linux and Windows) and the `Rendimiento` run (windows-x64, linux-x64) for the pushed sha.
  - Read the logs' tails and `$GITHUB_STEP_SUMMARY`. Use the GitHub MCP tools: `actions_list` `list_workflow_jobs`, then `get_job_logs` with `tail_lines`.
- [ ] **Step 2: If `tests-tk9` fails on Windows,** it is the first ever Windows run of the whole suite on Tk 9: root-cause it as a bug in code or test. Never skip a test.
- [ ] **Step 3: Windows ceilings.** Copy the Windows counts the summary prints into `[techo.windows]`.
- [ ] **Step 4: Record the results.**
  - Write the results file: per moment, base (`main`, 0.7.1) against this branch, on Windows and Linux, plus the deterministic counts.
  - Then add one line to the spec's «Estado» saying stage 1a is done and measured.
- [ ] **Step 5:** Commit «Etapa 1a medida en Windows y Linux», and push.
