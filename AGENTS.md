# AGENTS.md

Guidance for coding agents working in this repository. This file loads every session, so it holds only what applies everywhere; area detail lives in `docs/agents/reference/` (map below). **Read the matching doc before editing an area.**

## What this is

**prdrive**: portable two-way sync between *any* rclone remote and a removable drive (or a host folder, through a resident agent), driven by a bundled `rclone`. Pure Python **stdlib**, 3.11+ (`tomllib`): no build, no dependencies, no package manifest. Tests are plain scripts in `tests/`, no framework; nothing touches a real device or the network.

The code knows **no server**: the connection lives in a `profile.Profile` (asked by the wizard, imported from the user's `rclone.conf`, or embedded in the compiled `.exe`). The remote stores **configuration only** (the pair catalogue), never the program.

## Area docs (`docs/agents/reference/`)

Each opens with the files it covers. Claude Code also gets a one-line pointer to each doc when it reads or edits those files (path-scoped rules in `.claude/rules/`, one per doc); `tests/test_reglas_claude.py` keeps docs, rules and this table in sync.

| Doc | Read before touching |
|---|---|
| `engine.md` | `sync.py`, `model.py`, `bisync.py`, `config_file.py`: config → command, bisync prefix/baseline/filters, logs, progress, TOML writer |
| `conflicts-versions.md` | conflicts, `results.py`, `historial.py`, `versions = true` / `.prversions/` |
| `catalogue.md` | `catalog.py`, `catalog_editor`, `pair_editor`, `flags_editor`, `remote_picker` |
| `fleet.md` | `fleet.py`, `tk_fleet.py` |
| `service.md` | `runsync.py`, `ui/prefs.py`, `state/` locks, failure pop-up |
| `penwatch.md` | `penwatch.py` |
| `ui.md` | `ui/` in general: frontends, theme and sizing, `working()`/background reads, «Ajustes» |
| `repair.md` | `revision.py`, `ui/repair.py`, «Reparación» |
| `drive-name-icon.md` | `autorun.py`, `volumen.py`, the device's name |
| `pairing-qr.md` | `pairing.py`, `qr.py`, `tk_qr.py`, capture protection |
| `provisioning.md` | `prdrive-install.py`, `install/`, wizard, platforms/runtimes, `build_installer.py`, Windows ARM |
| `veracrypt.md` | `install/crypto.py`, `veracrypt_bin.py`, `traveler.py` |
| `vestibule.md` | `vestibulo.py`, `Abrir/Expulsar PRDRIVE`, Linux open/close without VeraCrypt |
| `updating.md` | `update.py`, `components.py`, `--update*`, `VERSION`/release, downloads |
| `agent.md` | `agente.py`, `install/agente.py`, `equipo.py`, `avisos.py`, `dbus.py` |
| `agent-scheduling.md` | `planificador.py`, `red.py`, `huella.py`, `moderacion.py`, `watch = true` |
| `agent-window.md` | window ↔ agent: «Pausar/Reanudar», mailboxes, `ui/watch.py`, agent self-update |
| `host-root.md` | `raiz_equipo.py`, `tk_equipo.py`, encrypted host root, «En este equipo» wizard |
| `tray.md` | `ui/bandeja*.py` |
| `commands-testing.md` | full CLI list, test harness, registry of test-replaceable indirection points |

Specs and real-hardware test plans/results: `docs/superpowers/{specs,pruebas}/` (the area docs cite them). Those cite sections of the former monolithic AGENTS.md by title: each area doc quotes its former titles on its «Formerly» line.

## Layout

`sync.py`, `runsync.py` and `penwatch.py` are located by fixed path by the volume-root launchers and the watcher: do not move them. `agente.py` is copied to the HOST, never to a device.

```
prdrive/            the checkout; on a provisioned device it is `.prdrive/`
├── sync.py         engine: build the rclone command, run it, report
├── runsync.py      window + periodic service; shells out to sync.py
├── penwatch.py     mount watcher (self-contained)
├── agente.py       resident agent: penwatch's successor on a host
├── prdrive-install.py  wizard launcher (what gets compiled) · build_installer.py (PyInstaller)
├── VERSION         the version, in ONE place; ships to the device
├── common/         config and rclone; no Tk
│   model (TOML → frozen `Mode`/`Pair`/`Config`) · bisync (rclone bisync internals) · conflicts · results (last_run.json) · historial (pass journal)
│   revision (the ONE diagnosis) · progress · config_file (reads AND writes TOML) · catalog · fleet · update · components (stamps vs pins, no network)
│   pins (pinned rclone/Python/VeraCrypt + platforms) · pairing (rclone.conf, QR payload) · vestibulo · autorun · store (JSON state, `pid_alive()`, atomic writes, `hide()`)
│   agent side: planificador (PURE scheduler) · huella · equipo (host dir, mailbox) · moderacion · red · dbus · avisos
├── ui/             asking the user, showing results
│   __init__ (`Choice`, `Frontend`, `start()`…) · theme · icons · qr · prefs · segundo_plano · cifrado · console · tk (TkFrontend, `modal()`/`mostrar()`/`working()`) · tk_*.py (draw only)
│   decision halves, no Tk: pair_editor · repair · catalog_editor · remote_picker · conflict_editor · flags_editor · watch · versions_editor · volumen
│   tray: bandeja (PURE) · bandeja_windows · bandeja_linux · tk_agente («¿Atender esta unidad?», a child of the agent)
├── install/        what the installer knows; no Tk, no device needed
│   profile · rclone_bin · runtime_bin · veracrypt_bin · descarga (retries, SHA256SUMS) · platforms · components · remote (ephemeral rclone.conf, catalogue)
│   device (volumes) · crypto (VeraCrypt, BitLocker) · traveler · vestibulo · agente · raiz_equipo · deploy (copy code, runtimes, launchers, config)
└── tests/          plain scripts; `run_all.py` runs each in its own process
```

On a provisioned device the code lives in `.prdrive/` at the volume root (hidden by the dot on POSIX, by `deploy.hide()` on Windows). `model.APP_DIR` = `Path(__file__).parent.parent` and `DEVICE_ROOT` its parent: **nothing depends on the folder name or drive letter**. The control file is **inside** `.prdrive/` (`.prdrive/PRDRIVE`), so identifying the drive needs only a root-relative path and it cannot be deleted without deleting the program.

## Dependency rules: do not cross them

- `tk_*` modules only draw. Every decision and disk touch lives in `pair_editor`/`catalog_editor`/`flags_editor`/`watch`/`install/`, which import no Tk and are tested headlessly.
- **`import tkinter` goes inside functions, never at module top**: `ui/` is imported by headless paths (`--auto`, the service), and the failure must surface when a window opens so `ui.start()` can fall back to the console menu.
- `theme.py`/`icons.py` own every colour, font and glyph (a `tk_*` module never writes a hex value); distances go through `theme.medida()`, never a bare integer.
- `penwatch.py` imports **neither** package: it is copied to the host and must keep working with the device unplugged. The agent imports penwatch, never the reverse.
- `install/` imports `common/` (`model.BASE_FLAGS`, `model.flags_to_args`, `config_file.save`, `store.pid_alive`: what the installer writes must be byte-for-byte what `sync.py` reads) but **not** `ui/` outside `tk_install`, and must work with **no device anywhere**. Icons go through `install.pintar()` → `install.pintar_iconos` (set by `prdrive-install.py` to `ui.icons.pintar`; unset, nothing is painted). `tests/test_agente_endurecido.py` walks `install/` for `ui` imports.
- `prdrive-install.py` is a launcher (arguments in, `ui/tk_install.py` out), except `--update`: the self-update applier, inline and windowless, run from the *downloaded* copy of the project.
- `runsync.py` never imports `sync.py` (it shells out to `model.SYNC_PY <pair>`); `sync.py` never imports `ui/` (that is why the ONE diagnosis lives in `common/revision.py`).

**Constants duplicated on purpose** (edit every copy; `tests/test_*` guard them):
- `deploy.APP_SUBDIR`; `STRUCT_MARKER`/`CONTROL_FILE` (`.prdrive/PRDRIVE`) in `penwatch.py`, `install/device.py` and `fleet.control_file()`: three copies because `install/` does not travel to the device (`test_install_device`, `test_fleet`).
- `RUNTIME_STAMP`/`RUNTIME_SUBDIR`; `penwatch.runtime_keys_for()` vs `install/platforms.candidates()` vs the fallback chain hard-coded in `runsync.bat` (`test_penwatch_runtime`).
- `penwatch.UI_LOCK_REL`/`DAEMON_LOCK_REL`/`HOST` vs `model.ui_lock()`/`model.daemon_lock()` and `prefs.HOST` (`test_instancia_unica`). The two lock paths are functions in `model.py` because tests move `STATE_DIR` at runtime; `runsync` and `ui/repair.py` both go through them, so penwatch's copy is the only one.
- `penwatch.CONTAINER_FILE`/`VESTIBULE_MARKER`/`OPEN_SCRIPT` and `TRAVELER_DIR`/`TRAVELER_EXE`/`TRAVELER_PORTABLE`/`TRAVELER_ARCHS` vs `common/vestibulo.py` (`TRAVELER*`), and `penwatch.UDISKS_TCRYPT_CONF` vs `install/vestibulo.TCRYPT_CONF` (`test_penwatch_vestibulo`). `install/` imports `common/vestibulo` directly, and `Abrir/Expulsar PRDRIVE.bat` are generated from the `TRAVELER*` names.

## Commands and verification

```bash
python sync.py [pares...]   # all pairs, or only these. --list (read-only) · --doctor · --resync · -y · --keep-logs
python sync.py --dry-run    # simulate; MANDATORY before any *-mirror run
python runsync.py           # UI (Tk, console fallback) + periodic service; --auto, --auto --once
python tests/run_all.py     # all tests, each in its own process; or run one script directly
```

The full list (`penwatch.py`, `agente.py`, `prdrive-install.py`, `build_installer.py`) is in `commands-testing.md`.

- Verification is `tests/run_all.py`, `--doctor`, `--dry-run`. Nothing to lint; no CI runs the tests. Tk tests skip without a display, so green without Tk has tested no window. The suite passes on Windows **and** Linux: a check about the other system forces `IS_WIN` or prints `(saltado) …`.
- `runsync.py` with no args always **stops a previously started service** first.
- Windows dev machine: the Bash tool is sandboxed. It redirects writes under `%LOCALAPPDATA%` (a `penwatch install` from there registers a task pointing at nothing) and hangs `tasklist | find`. Use PowerShell for both.

## Engine rules (detail: `engine.md`)

- **Parse once, at the boundary**: `model.parse_config()` → frozen `Mode`/`Pair`/`Config`; nothing downstream re-reads TOML keys. Validation raises `model.ConfigError`, never `sys.exit` (the UI shares the model); `install.InstallError` likewise.
- **A new rclone flag = edit the TOML, never code.** Flags merge `BASE_FLAGS` < `Mode.flags` < `[defaults.flags]` < `[pair.flags]`; the script owns `--config`, `--log-file`, `--dry-run`, `--workdir`, `--resync`.
- rclone always runs with `cwd = model.APP_DIR`: `rclone.conf` uses paths relative to it (`key_file`, `known_hosts_file`).
- `sync_config.toml` is per-device: generated from the catalogue at provisioning, then maintained by the pairs screen; still hand-editable (a pair that differs from the catalogue is *reported* «modificada aquí», not corrected). Nothing on the device travels to the remote: no pair mirrors `.prdrive/`.

## Safety invariants: do not weaken

- If a bisync baseline exists but the local path does **not**, `_bisync_preflight()` aborts with rc 2 instead of creating the folder (an empty local side reads as "everything was deleted"). Only pairs **without** a baseline get their local dir created.
- `max-delete` defaults: 25 bisync / 50 mirror, and they are **not the same unit**. bisync's is a **global** rclone flag it intercepts and reinterprets: `Options.applyContext()` (`cmd/bisync/cmd.go`) reads `--max-delete`, clamps it to 0..100 and sets `ci.MaxDelete = -1` so `fs/operations` never treats it as a count; `excessDeletes()` (`cmd/bisync/deltas.go`) then aborts when `deleted / oldCount` exceeds that **percentage** of the previous listing. `*-mirror`'s 50 is the ordinary `sync` flag: a plain **count** of files. Don't "fix" either number by comparing it to the other.
- Any `*-mirror` pair deletes on the far side: never exercise one without `--dry-run` first. No pair mirrors the whole device.
- Anything entering `bisync.expected_prefix()` (`local`, `remote`, `remote_path`, `mode`, `device_remote`, `RAIZ_UPSTREAM`) names the baseline: a change **shelves** it (`state/<pair>.old-<date>/`, then an explicit `--resync`), never renames it, and there is no listing rename (`engine.md`, `catalogue.md`).
- Anything that deletes or rewrites user data returns an `EditPlan` (`consequences`/`warnings`/`execute()`) shown through `tk_pairs.confirmar_plan()` before it runs; nothing repairs itself.

## Conventions

- **Writing code**: `docs/agents/code-writing-conventions.md`, before changing Python. Comments, docstrings and everything the user sees are in **Spanish**; keep the technical citations (rclone, VeraCrypt, kernel, specs) in code that mirrors them. Docs under `docs/agents/` are English.
- **Indirection points**: everything that touches the network, a real device or the desktop is a **module-level function tests can replace** (`catalog.run()`, `update.fetch()`, `tk.mostrar()`/`confirmar_plan()`, `equipo.DIR`…). New ones keep that shape; the registry is in `commands-testing.md`.
- **Windows traps**: `pid_alive()` uses `OpenProcess`, never `os.kill` (which *terminates* on Windows); background processes use `pythonw.exe` + `CREATE_NO_WINDOW`; child runs get `stdin=DEVNULL`, so a pair needing `--resync` is skipped rather than resynced unattended.
- `.gitignore` excludes device/user paths (`bin/`, `runtime/`, `keys/`, `filters/`, `logs/`, `state/`, `sync_config.toml`, `rclone.conf`, `prdrive-profile.toml`), build artefacts and `install/secret.py`.

## Documentation

- **`README.md`**: the user-facing front page. Spanish, short, no internals. Longer user guides: `docs/guia/`.
- **`device-readme.md`**: the *light* quick guide, **not** for repo readers: the installer copies it to the volume root as `README.md` (`deploy.write_guide()`, best-effort). Short, task-shaped, no internals; it is in `DATOS_FICHEROS`, so a build that forgets it fails at compile time.
- **`sync_config.example.toml`**: the schema reference for `sync_config.toml` and the remote's catalogue `remote.toml` (formerly `pairs.toml`; it also takes `[remote]`). **`LICENSE`**: Apache 2.0 verbatim.
- **`.github/pull_request_template.md`**: what every PR answers (agents' included): where it touches, which data is at stake, what happens to devices already in use, how it was checked. **A PR title is release text** (`--generate-notes`; `tk_update` shows it on every device): write it in Spanish, for the device's user.
- A behaviour change updates the matching `docs/agents/reference/` doc (and `docs/guia/` if users see it), not this file: keep this one small, it loads every session.

## Agent skills

- **Issue tracker**: GitHub Issues (`Jeremaya25/prdrive`) via the `gh` CLI. See `docs/agents/issue-tracker.md`.
- **Triage labels**: five canonical labels, each string equal to its role name. See `docs/agents/triage-labels.md`.
- **Domain docs**: single-context, one `CONTEXT.md` + `docs/adr/` at the repo root, created lazily. See `docs/agents/domain.md`.
