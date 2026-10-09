# Faster CI Implementation Plan

> **For agentic workers:** builders are **Haiku**, reviewers **Sonnet**. Each builder sees only its task plus **Global Constraints**. Steps use checkbox (`- [ ]`) syntax.

**Goal:** a push's slowest CI job goes from ~5 min (Windows tests) and ~12 min (timing check) to ~2–4 min and ~6 min, without dropping any promise of `AGENTS.md`: `tests/run_all.py` on Linux under xvfb and on Windows with the device's pinned runtime, the Python 3.11 job without display, and the timing check against `main`.

**Where the time goes (measured, 09/10, runs 37943241770 / 37943241842 / 37965232632):** Tests job wall 285 s (Windows; its test step 265 s), Linux 215 s (step 187 s), Python 3.11 104 s (step 98 s); Rendimiento Windows 690 s, Linux 288 s; Instalador 44 s. Per push about 29 runner-minutes. Three keychain test files spin on a real 1.5 s deadline: ~40 s of every test job (22 % of Linux, 41 % of the 3.11 job). Windows Tk tests are 94 % of the Windows–Linux gap. A Sonnet audit ran the suite concurrently (13 full runs, prototype `run_all_par.py`): on Linux 136 of 137 files are safe with one Xvfb per worker; on Windows, GUI files share one desktop.

## Global Constraints

- **Protocol.** Worktree of `claude/adoring-pascal-5j258r` (first `git merge --ff-only claude/adoring-pascal-5j258r`); ONE commit per task, the Spanish subject given, body 2–4 lines, footer exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01JHY3t4qHyjjXzmXQXCxAVU`; never push, never open a PR, never write a marker that skips CI. The director merges and pushes.
- **Verification.** `xvfb-run -a -s "-screen 0 1920x1080x24" /tmp/claude-0/-home-user-prdrive/03b34008-f2da-52c1-8cde-5efd2782344d/scratchpad/runtime-linux64/bin/python3 tests/<file>.py`; headless `python3 tests/<file>.py`; full suite once at the end. Each new test fails first. Never kill processes you did not start.
- **Promises kept.** Every `tests/test_*.py` still runs in its own process on Linux (xvfb), Windows (pinned runtime) and the 3.11 job; the last lines of `run_all.py` stay `FALLAN n de N: <ficheros>` or `Los N ficheros de test pasan.` (people and scripts read them); exit status 1 on any failure. Stdlib only; Spanish comments; `docs/agents/` in English.

---

## Phase 1 (Tasks 1–3 in parallel; disjoint files except the docs paragraphs named)

### Task 1: The keychain tests stop spinning on a real clock

**Files:** `common/keepassxc.py`; `tests/test_keepassxc.py`, `tests/test_llavero_combinar.py`, `tests/test_keepassxc_linux.py`; `docs/agents/reference/commands-testing.md` (ONLY the registry of indirection points: one line).

- [ ] `esperar_arranque` (`common/keepassxc.py` ~1090) loops on `proc.poll()` until `time.monotonic()` passes `ESPERA_ARRANQUE = 1.5`, sleeping through `llavero.dormir(0.1)`; the three tests replace `dormir` with a no-op and their fake process never exits, so each call spins ~1.25–1.5 s of CPU (cProfile: 21.8 M `time.monotonic` calls in `test_keepassxc`). Add a module-level indirection `reloj = time.monotonic` in `common/keepassxc.py`, used by `esperar_arranque` (and any other deadline loop in the module that the same tests hit); in the three tests, the fake `dormir(s)` advances a fake clock that the tests install as `keepassxc.reloj`. Behaviour unchanged in production; every existing assertion still holds.
- [ ] Test first: a check in `tests/test_keepassxc.py` that one `esperar_arranque` with a never-exiting fake takes < 0.2 s of wall time and still returns «no arrancó» after the deadline. Measure the three files before/after (wall seconds) and report them.
- [ ] Commit «Las pruebas del llavero dejan de esperar de verdad el arranque de KeePassXC: 40 s menos en cada trabajo de la CI».

### Task 2: `run_all.py` runs test files in parallel

**Files:** `tests/run_all.py`; Create `tests/test_run_all.py`; `.github/workflows/tests.yml` (ONLY the lines that invoke `run_all.py`); `docs/agents/reference/commands-testing.md` (the paragraph about `run_all.py` and CI; not the registry).

Start from the audit's working prototype `/tmp/claude-0/-home-user-prdrive/03b34008-f2da-52c1-8cde-5efd2782344d/scratchpad/ci-vel/par-audit/run_all_par.py` and its report `/tmp/claude-0/-home-user-prdrive/03b34008-f2da-52c1-8cde-5efd2782344d/scratchpad/ci-vel/informe-paralelo.md` (sections 4–6: the serial set, the design, the estimates).
- [ ] CLI: `-j N|auto` (auto = `os.cpu_count()`; default `1` = today's behaviour exactly), `--display inherit|xvfb` (xvfb: one `Xvfb -displayfd … -screen 0 1920x1080x24 -nolisten tcp` per worker, started once per worker; falls back to `inherit` without Xvfb), `--gui-jobs K` (at most K files from the GUI set at once: the files that open Tk windows, listed in `run_all.py` as `GUI = {...}` and guarded by a test that every file importing `tkinter` or `ui.tk*` at top level or creating `tk.Tk()` is in it or explains why not), `--timeout S` (default 600; kills the child's whole tree), optional file names.
- [ ] Scheduling: a queue ordered by a static weight table (the slowest ~15 files from the measurement first); `SERIE = {nombre: razón}` runs after the pool, one at a time: `test_avisos_carpeta.py` (watches host mounts) always; `test_vestibulo.py` on Windows (system-wide process name); `test_superficie.py` and `test_tk_tabla.py` whenever workers share a display (pixels/focus).
- [ ] Isolation: each file its own `TMPDIR`/`TEMP`/`TMP` and `HOME`/`USERPROFILE` under a short base (≤ 60 chars, for `test_dbus`'s socket paths), created and removed per file; `stdin=DEVNULL`.
- [ ] Output: each file's stdout+stderr buffered and printed whole when it ends, under a lock: `##### <name>: OK|FALLA rc (<s> s)` then its output; in GitHub Actions (`GITHUB_ACTIONS=true`) wrapped in `::group::`/`::endgroup::`, failures printed again ungrouped with `::error::`; at the end the 10 slowest files, then the unchanged final lines.
- [ ] `tests/test_run_all.py` (headless, runs `run_all.py` on a temp dir of tiny fake test files): `-j 4` runs 8 sleeping files in about 2 sleeps, not 8; a failing file gives the `FALLAN 1 de N: <name>` last line and exit 1; a hanging file is killed at `--timeout` and reported; `SERIE` files never overlap anything (each fake writes start/end timestamps); `--gui-jobs 1` never overlaps two GUI fakes; the default `-j 1` output's last line equals today's.
- [ ] `tests.yml`: Linux `python tests/run_all.py -j auto --display xvfb` (keep the «Se abre una ventana» step and the `PRDRIVE_SIN_SVG=1` icon step as they are); Python 3.11 job `-j auto`; Windows `-j auto --gui-jobs 1`.
- [ ] Run the full suite locally with `-j 4 --display xvfb` three times and with `-j 1` once; all pass; report wall times. Commit «La suite corre varios ficheros a la vez: misma comprobación, un tercio del tiempo en Linux».

### Task 3: Lighter triggers for pushes

**Files:** `.github/workflows/rendimiento.yml`, `.github/workflows/tests.yml` (ONLY `on:`), `docs/agents/reference/commands-testing.md` (the `rendimiento.yml` paragraph).

- [ ] `rendimiento.yml`: a **draft** PR gets 3 rounds, everything else 7 (a ready PR, `workflow_dispatch` without `rondas`, the TEMPORAL push): `RENDIMIENTO_RONDAS: ${{ inputs.rondas || (github.event.pull_request.draft && '3' || '7') }}`, read by the job where `--rondas` is passed; `pull_request` gains `types: [opened, synchronize, reopened, ready_for_review]`, so marking a draft ready measures again. The push trigger gets no `paths` (it is the temporary stage-branch one).
- [ ] `tests.yml`: on `push` only, `paths-ignore: ["docs/superpowers/**", "docs/guia/**"]` (never `docs/agents/**`, `AGENTS.md`, `.claude/**`: tests read them); `pull_request` unchanged.
- [ ] Do NOT remove the TEMPORAL push triggers yet (they go with the PR, by the director).
- [ ] Docs: the paragraph says a draft PR runs 3 rounds (a quick signal) and a ready PR 7; the temporary push trigger line says which workflows a push runs. Commit «En un PR en borrador la comprobación de tiempos da tres vueltas y en uno listo siete; un push que solo toca documentos no pasa la suite».

---

## Phase 2 (after Phase 1 is measured on CI)

### Task 4: Windows GUI files across shards
Only if the Windows test job is still the slowest: `run_all.py --shard i/n` (files split by the weight table, GUI files spread evenly), a Windows matrix of 3 shards (each runner has its own desktop, so GUI files run in parallel safely), and a gate job named `tests (windows-latest)` that needs the shards, so the check names stay. Planned when Phase 1's numbers are in.

## Decisions for the owner (default taken)
1. **Draft PR = 3 timing rounds, ready PR = 7.** A draft gives a quicker, rougher timing signal while it is worked on; a ready PR keeps today's power. Pushes (the temporary stage-branch trigger) keep 7.
2. **Docs-only pushes do not run the test suite** (`docs/superpowers/**`, `docs/guia/**`, a `paths-ignore` on `tests.yml`'s push). The timing check's push trigger has no path filter: on the stage branch it still measures a docs-only push, and that trigger goes with the PR.
3. **Windows GUI tests stay in one lane in Phase 1**; parallel GUI on one desktop (or shards) is Phase 2.
