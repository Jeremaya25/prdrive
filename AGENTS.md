# AGENTS.md

Guidance for coding agents working in this repository.

## What this is

**prdrive**: portable two-way sync between *any* rclone remote and a removable
drive, driven by a bundled `rclone`. Pure Python **stdlib**, 3.11+ (`tomllib`):
no build, no dependencies, no package manifest. Tests are plain scripts under
`tests/` — no framework, nothing touches a real device or the network.

The code knows **no server**: the connection lives in a `profile.Profile` the
wizard asks for, imports from the user's `rclone.conf`, or carries embedded in
the compiled `.exe`. The remote stores **configuration only** — the catalogue of
pairs — never the program.

## Layout

Root entry points: `sync.py`, `runsync.py`, `penwatch.py` (the volume-root
launchers and the watcher locate them by fixed path), `agente.py` (the resident
agent, copied to the HOST, never to a device), `prdrive-install.py` (what gets
compiled and handed out) and `build_installer.py`.

```
prdrive/               (the checkout; on a provisioned device it is `.prdrive/`)
├── sync.py            engine: build the rclone command, run it, report
├── runsync.py         the periodic service + who calls what
├── penwatch.py        mount watcher (deliberately self-contained)
├── agente.py          the resident agent: penwatch's successor on a host
├── VERSION            the version, in ONE place; ships to the device
├── common/            the config and rclone
│   ├── model.py       sync_config.toml parsed into resolved objects
│   ├── bisync.py      replicates rclone bisync's internals
│   ├── conflicts.py   conflict files: scan, side, state/conflicts.json
│   ├── results.py     each pair's last run (state/last_run.json)
│   ├── historial.py   the pass journal: last N passes per pair (state/historial.jsonl)
│   ├── revision.py    what is wrong, as data: the ONE diagnosis
│   ├── progress.py    rclone stats lines → the live progress line
│   ├── config_file.py reads AND writes the TOML (hand-rolled serializer)
│   ├── catalog.py     the pair catalogue on the remote: read, cache, write
│   ├── fleet.py       one note per device beside the catalogue
│   ├── update.py      is there a newer release, and how to fetch its code
│   ├── components.py  rclone/Python/VeraCrypt carried vs the pins — stamps, no network
│   ├── pins.py        pinned rclone + python-build-standalone + VeraCrypt
│   │                   Portable (URL + SHA-256); platform table
│   ├── pairing.py     reads rclone.conf; the connection as a QR payload
│   ├── vestibulo.py   what a VeraCrypt device leaves OUTSIDE its container
│   ├── autorun.py     the root's autorun.inf: the drive's name and icon, edited
│   ├── planificador.py the agent's scheduler: PURE (data in, decision out)
│   ├── equipo.py      the agent's host dir: agente.json, instalacion.json, buzón
│   ├── moderacion.py  battery, metered network, "is this failure the network?"
│   ├── dbus.py        a stdlib D-Bus client (the calling half)
│   ├── avisos.py      native notifications, no Tk
│   └── store.py       device JSON state + pid_alive(); atomic writes; hide()
├── ui/                asking the user, showing results
│   ├── __init__.py    Choice, Frontend, start(), fatal(), manual_args(), abrir()
│   ├── theme.py       palette, fonts, ttk styles — no window
│   ├── icons.py       icons rasterised here: no deps, no emoji
│   ├── qr.py          a QR encoder: ISO/IEC 18004, byte mode, no deps, no Tk
│   ├── prefs.py       the service's pairs + interval (state/ui_prefs.json)
│   ├── pair_editor.py what THIS device does with pairs — the decisions
│   ├── repair.py      what to do about a finding: the repair plans
│   ├── catalog_editor.py · remote_picker.py · conflict_editor.py ·
│   │   flags_editor.py · watch.py · versions_editor.py · volumen.py
│   │                   the other decision halves, no Tk
│   ├── tk.py          TkFrontend: main + output window, modal()/mostrar()/working()
│   ├── cifrado.py     is this device inside a VeraCrypt container? «Expulsar»
│   ├── tk_install.py  the install wizard          (every tk_* draws only)
│   ├── tk_equipo.py   the wizard's «En este equipo» steps
│   ├── tk_agente.py   «¿Atender esta unidad?», a child process of the agent
│   ├── bandeja.py     what the agent's tray shows and asks: PURE, no Tk
│   ├── bandeja_windows.py  the Windows tray: Shell_NotifyIconW, its own thread
│   ├── tk_pairs.py · tk_repair.py · tk_conflicts.py · tk_fleet.py ·
│   │   tk_watch.py · tk_update.py · tk_crypto.py · tk_doctor.py ·
│   │   tk_qr.py · tk_versions.py · tk_volumen.py
│   └── console.py     ConsoleFrontend: the text menu
├── install/           what the installer knows; no Tk, no device needed
│   ├── __init__.py    brand constants, InstallError, InstallState, python_command()
│   ├── profile.py     the connection: where it comes from, how it is written
│   ├── rclone_bin.py  get an rclone (any platform's), verified
│   ├── runtime_bin.py get a python-build-standalone runtime, verified; extract
│   ├── veracrypt_bin.py get the VeraCrypt Portable, verified, opened without running it
│   ├── descarga.py    what they share: retry the network, read a SHA256SUMS
│   ├── platforms.py   host, what the device carries, the step-5 Matriz/Plan
│   ├── components.py  fetch the pinned component, swap it in
│   ├── remote.py      the ephemeral rclone.conf and the pair catalogue
│   ├── device.py      what volumes exist, which is the device, mounted right?
│   ├── crypto.py      VeraCrypt and BitLocker
│   ├── traveler.py    the VeraCrypt Portable (x64 + ARM64) on the volume, swapped
│   ├── vestibulo.py   the launchers outside the container: open, eject
│   ├── agente.py      put the resident agent on this host, and take it off
│   ├── raiz_equipo.py the host root: which folder, its container, install it, other sync clients
│   └── deploy.py      copy the code in, rclone + runtimes, launchers, config
└── tests/             plain scripts; run_all.py runs them in separate processes
```

**Dependency rules — do not cross them:**

- `tk_*` modules only draw. Every decision and disk touch lives in
  `pair_editor` / `catalog_editor` / `flags_editor` / `watch` / `install/`, which
  import no Tk and are tested headlessly.
- `theme.py` / `icons.py` own every colour, font and glyph; a `tk_*` module never
  writes a hex value of its own.
- `penwatch.py` imports **neither** package: it is copied to the host and must
  keep working with the device unplugged.
- `install/` **does** import `common/` (`model.BASE_FLAGS`, `model.flags_to_args`,
  `config_file.save`, `store.pid_alive`) — what the installer writes must be
  byte-for-byte what `sync.py` later reads. It must **not** import `ui/` outside
  `tk_install`, and must work with **no device anywhere**.
- `prdrive-install.py` is a launcher (arguments in, `ui/tk_install.py` out),
  except `--update`: the self-update applier, inline and windowless, run from the
  *downloaded* copy of the project.

**On a provisioned device** the code lives in `.prdrive/` at the volume root (the
dot hides it on POSIX; `deploy.hide()` sets the hidden attribute on Windows).
`model.APP_DIR` is `Path(__file__).parent.parent`, `DEVICE_ROOT` its parent, so
**nothing depends on the folder name or drive letter**. The control file sits
**inside** `.prdrive/`, so identifying the drive needs only a path relative to
the root and it cannot be deleted without deleting the program.

Constants duplicated across modules that must not drift: `deploy.APP_SUBDIR`, and
`STRUCT_MARKER` / `CONTROL_FILE` (`.prdrive/PRDRIVE`) in `penwatch.py`,
`install/device.py` and `fleet.control_file()` — three copies, because `install/`
does not travel to the device (`tests/test_install_device.py`, `test_fleet.py`);
`RUNTIME_STAMP` / `RUNTIME_SUBDIR`, and `penwatch.runtime_keys_for()` vs
`install/platforms.candidates()`, the fallback chain `runsync.bat` hard-codes
(`tests/test_penwatch_runtime.py`); `penwatch.UI_LOCK_REL` / `DAEMON_LOCK_REL` /
`HOST` vs `model.ui_lock()` / `model.daemon_lock()` and `prefs.HOST`
(`tests/test_instancia_unica.py`). Those two paths are functions in `model.py`
and not constants because the tests move `STATE_DIR` at runtime; `runsync` and
`ui/repair.py` both go through them, so penwatch's copy is the only one.
`penwatch.CONTAINER_FILE` / `VESTIBULE_MARKER` / `OPEN_SCRIPT` and
`TRAVELER_DIR` / `TRAVELER_EXE` / `TRAVELER_PORTABLE` / `TRAVELER_ARCHS` vs
`common/vestibulo.py` (`TRAVELER*`), and `penwatch.UDISKS_TCRYPT_CONF` vs
`install/vestibulo.TCRYPT_CONF` (`tests/test_penwatch_vestibulo.py`); `install/`
imports the former directly, and `Abrir/Expulsar PRDRIVE.bat` are generated
from the `TRAVELER*` names.

## The PyInstaller build (`build_installer.py`)

Packs the tree the installer deploys (`sync.py`, `runsync.py`, `penwatch.py`,
`common/`, `ui/` as `--add-data`) and optionally embeds a connection profile.

- `common/` and `ui/` are in the bundle **twice** — importable bytecode (the
  installer uses them) and copyable source (what lands on the device):
  PyInstaller cannot hand back the `.py` of a module it imported.
- **Without a profile** (a plain clone) the binary is generic and asks for the
  connection in `Conexión`; **with one** (`prdrive-profile.toml` + `keys/`) it is
  turnkey and must only be shared privately. That split is what lets the repo be
  public: `install/secret.py` is generated at build time, gitignored, deleted in
  a `finally`.
- **Frozen-only traps:** `sys.executable` is the installer, not Python — anything
  the wizard launches from the device goes through `deploy.device_python()`;
  `sys.stdout` can be None with `--windowed`.
- The `.exe` carries **no** runtimes or rclone: step 5 downloads them per
  platform (verified, cached in `%LOCALAPPDATA%/prdrive-install/`).
- **Windows on ARM:** everything arch-dependent (`model.arch_dir()` for
  `bin/<arch>/`, `rclone_bin.os_arch()` / `cache_dir()`) hangs off
  `model.maquina_nativa_windows()`, because Windows tells an emulated x64 process
  it is `AMD64` and only `IsWow64Process2()` answers truthfully; resolve on the
  **host**, never store it on the device. Emulated x64 runs but ARM on x64 does
  not, so fallbacks are one-way: `BIN_FALLBACK_DIRS`, and the runtime chain
  windows-arm64 → windows-x64 → host Python in `runsync.bat` (whose
  `%PROCESSOR_ARCHITECTURE%` *is* truthful), `platforms.candidates()` and
  `penwatch.runtime_keys_for()`. `tests/test_arch.py` fakes the probe.

## Commands

```bash
python sync.py [pares...]      # every pair in sync_config.toml, or only these
python sync.py --list          # pairs + resolved endpoints (safe, read-only)
python sync.py --doctor        # bisync state: prefixes, filters, locks
python sync.py --dry-run       # simulate; MANDATORY before any *-mirror run
python sync.py --resync        # rebuild the bisync baseline
python sync.py -y/--yes        # auto-approve the resync question (cron/scripts)
python sync.py --keep-logs     # keep logs of successful runs too

python runsync.py              # UI (Tk, console fallback) + periodic service
python runsync.py --auto       # periodic service with the service's config, no UI
python runsync.py --auto --once  # one pass of the service's pairs, then exit
python runsync.py --doctor     # any other args pass straight through to sync.py

python penwatch.py install|status|probe|uninstall   # the watcher, per machine/user
python agente.py run|status                         # the resident agent (host copy)
python agente.py atender ID | modo ID MODO | pasada ID [pareja…] | pausa | sigue | parar
python agente.py abrir [ID]                         # the window of the host root
python agente.py desbloquear [ID] | bloquear [ID]   # open / close the encrypted host root
python agente.py ajuste pedir_al_iniciar sí|no      # or espera_unidad_nueva SEG

python prdrive-install.py          # install wizard for a NEW device (Tk only)
python prdrive-install.py --check  # rclone + connection + catalogue, then exit
python prdrive-install.py --probe  # what drives it sees, then exit
python prdrive-install.py --update E:\             # the device's code only
python prdrive-install.py --update-components E:\  # its rclone + runtime only
python prdrive-install.py --instalar-agente        # the resident agent on THIS host
python prdrive-install.py --desinstalar-agente     # and off again (no drive touched)
python build_installer.py          # build the .exe (embeds the profile if any)
python -m ui.icons                 # repaint APP_DIR/runsync.ico (headless)

python tests/run_all.py            # all tests; or run one script directly
```

- `runsync.py` with no args always **stops a previously started service** first.
- Verification is `tests/run_all.py`, `--doctor`, `--dry-run`. Nothing to lint.
- `.gitignore` excludes device/user paths (`bin/`, `runtime/`, `keys/`,
  `filters/`, `logs/`, `state/`, `sync_config.toml`, `rclone.conf`,
  `prdrive-profile.toml`), build artefacts and `install/secret.py`.
  **Nothing on the device travels to the remote** — no pair mirrors `.prdrive/`.

## Architecture

`sync.py` is the engine. `runsync.py` never imports it — it reads config via
`common.model` and shells out to `model.SYNC_PY <pair>` per pair, so the two
never share in-process state.

**Parse once, at the boundary.** `model.parse_config()` turns the TOML into
frozen value objects (`Mode`, `Pair`, `Config`); nothing downstream re-reads TOML
keys, repeats `.get(key, default)` or threads `defaults` through signatures.
Adding a mode = one `Mode(...)` in `MODES`; an invalid one is rejected at parse
time, so a typo stops `--list`/`--doctor`/a run alike. Validation raises
**`model.ConfigError`**, never `sys.exit` — the UI shares this model and killing
the process would close the window in the user's face; CLI entry points catch it
and exit with its message. `install.InstallError` exists for the same reason.

**Config → command.** Flags merge last-wins — `BASE_FLAGS` < `Mode.flags` <
`[defaults.flags]` < `[pair.flags]` — inside `model._build_pair`, so `Pair.flags`
arrives ready and `build_command()` adds only what depends on *this* run.
`model.flags_to_args()` turns `key = value` into `--key value` (`true` → bare
flag, `false`/`None` → dropped, list → repeated, `_` → `-`); it lives in
`model.py` so the UI can show what a flag becomes without importing the engine.
**Adding an rclone flag means editing the TOML, never the code.** The script owns
`--config`, `--log-file`, `--dry-run`, `--workdir`, `--resync`; `extra_flags` is
the raw-string escape hatch. `RunContext` carries what does not change between
pairs in one invocation.

### bisync (`common/bisync.py`)

The one place that imitates rclone's own behaviour; each section cites the rclone
source it mirrors. **Preserve those citations.**

- **Session prefix.** `canonical_path` / `session_name` / `expected_prefix`
  replicate `cmd/bisync/bilib/canonical.go`, so the script knows the listing name
  **before** running. Used only by `pair_editor` (does this baseline still belong
  to this pair?) and `--doctor`.
- **`device_remote`, on by default** (`DEFAULT_DEVICE_REMOTE = "disp"`;
  `deploy.device_config()` `setdefault`s it into each new device's `[defaults]`).
  It makes the device side a `combine` remote via
  `RCLONE_CONFIG_<NAME>_TYPE/_UPSTREAMS` (`Config.pen_environment()`, computed
  from **all** pairs), so the prefix is machine-independent; `alias` does not
  work. It belongs to the **device's** defaults — in the catalogue it would move
  every installed device's prefix at once.
- **Quoting `upstreams`.** rclone parses it as an `fs.SpaceSepList`
  (`fs/types.go`): space-separated CSV where a field is quoted only if it
  **starts** with a quote. The quotes therefore wrap the whole `name=path`, never
  just the path — `.="F:\"` yields `bare " in non-quoted-field` and takes
  **every** pair on the device down. They exist for a drive root's trailing
  backslash and for spaces. `model._upstream()` is the one place that builds it.
- **The device root needs a named upstream.** rclone cleans the path before
  resolving it, so `local = "."` becomes upstream `""` and fails with `combine
  for remote "": directory not found`. `model.RAIZ_UPSTREAM` (`"raiz"`) names it
  — hence `top_level_dir` (the name) and `top_level_abs` (the folder) are two
  properties. The name is in the prefix: changing it invalidates those baselines.
- **No listing rename** (`normalize_prefix`, `rename_prefix`, `heal_listings`
  were deleted with `device_remote`): renaming a listing set tells bisync that a
  listing of the *previous* destination describes the *new* one, and the benign
  case is indistinguishable from the malignant one. Legacy devices are fixed by
  hand — no migration code. `tests/test_bisync_prefijo.py` asserts the absence
  and guards both halves of `device_remote`.
- **Filters.** For `bisync` only (`Pair.wants_filters_file`), `filters_file_for()`
  writes `filters/<pair>.txt` and passes `--filters-file`; `--include`/`--exclude`
  are then **not** also emitted (duplicate rules break change detection). bisync
  rewrites the md5 beside the file only during `--resync`, so `filters_state()`
  compares the hash itself and reports "needs resync".
- **State.** One workdir per pair, `Pair.workdir` → `state/<pair>/`
  (`migrate_legacy_state()` moves the old flat layout). `pair_state()` returns
  `PairState(status, detail, prefix)` — `fresh|ok|broken` read from the actual
  `.lst` files. `resync_reasons(pair)` returns why a pair needs `--resync` (`[]`
  for non-bisync; the mode guard is inside it). `last_run(pair)` is the mtime of
  the newest listing, which **is** the last good pass; non-bisync pairs get None.
- **Resync approval.** `resolve_resync_approval()` asks **once** for all pairs
  before anything runs, and `ask_yes_no()` returns the default when stdin is not
  a tty — non-interactive runs skip those pairs (`SKIPPED = -1`) rather than
  resyncing unattended.

### Safety invariants — do not weaken

- If a bisync baseline exists but the local path does **not**,
  `_bisync_preflight()` aborts with rc 2 instead of creating the folder (an empty
  local side reads as "everything was deleted"). Only pairs **without** a
  baseline get their local dir created.
- `max-delete` defaults: 25 bisync / 50 mirror, and they are not the same unit.
  bisync's is a **global** rclone flag it intercepts and reinterprets: it reads
  `--max-delete` in `Options.applyContext()` (`cmd/bisync/cmd.go`), clamps it to
  0..100 and immediately sets `ci.MaxDelete = -1` so `fs/operations` never
  treats it as a count; `excessDeletes()` (`cmd/bisync/deltas.go`) then aborts
  when `deleted / oldCount` exceeds that **percentage** of the previous
  listing. `*-mirror`'s 50 is the ordinary `sync` flag: a plain **count** of
  files. Don't "fix" either number by comparing it to the other.
- rclone always runs with `cwd = model.APP_DIR`: `rclone.conf` uses paths
  relative to it (`key_file`, `known_hosts_file`).
- Any `*-mirror` pair deletes on the far side — never exercise one without
  `--dry-run` first. No pair mirrors the whole device.

### Logs and live progress

rclone writes to a temp file; `dispose_log()` keeps it in `logs/` only when the
run failed (or `--keep-logs` / `keep_logs = true`), to spare device write cycles.
On failure the tail is printed and `KNOWN_ERRORS` maps rclone messages to an
explanation — add new cases there. If the device vanished mid-pass (#36),
`keep_log()` leaves the log in the temp dir, says so in one `AVISO` line (any
half-copy in `logs/` removed) and returns that path, so the tail and the
explanation still come out; `run_all()` turns an `OSError` from the pairs after
it into a `FALLÓ` line, never a traceback.

- `--log-file` only catches what rclone logs **after** installing the log, so
  `execute()` captures rclone's `stdout`+`stderr` (captured, not inherited: with
  no console behind it inherited output is lost) and `append_output()` appends it
  under `DIRECT_OUTPUT_HEADER`.
- `strip_usage()` drops the 12 KB help dump rclone prints after a bad flag: it
  mentions `--max-delete` and `lock file`, so `explain_failure()` matched a
  `KNOWN_ERRORS` needle inside rclone's own documentation. **A false diagnosis is
  worse than none.** The two flag entries in `KNOWN_ERRORS` go **last**.
- **Live progress.** `BASE_FLAGS` carries `--stats 2s --stats-one-line` (base
  layer, so a pair can override it) and `execute()` runs rclone inside
  `seguir_progreso(logfile)`, a thread tailing the temp log — the **only**
  channel, no rc API or ports. Strictly best-effort: an unmatched line yields no
  progress and the thread swallows *any* exception. The file is closed before
  `execute()` returns (Windows cannot delete or move an open file); `main()`
  switches stdout to line buffering (behind the window it is a pipe);
  `print_log_tail()` drops stats lines. The regex mirrors `StatsInfo.String()`
  (`fs/accounting/stats.go`) and requires the ETA, so a line cut mid-write never
  yields a half number.

### Daemon (`runsync.py`)

Coordination lives in `state/` so it travels with the device: `daemon.lock.json`
(pid/host/pairs/cycle), `daemon.stop` (presence = stop request), `daemon.log`,
`ui.lock.json` (pid/host of the open window), `ui_prefs.json`, plus
`last_run.json`, `historial.jsonl` and `conflicts.json` (written by `sync.py`,
not the daemon). The service stops when the device disappears (`SENTINEL`) or
when runsync is launched again.

**One service, two ways to start it (#14).** By hand («Iniciar servicio») or on
plugging in (the watcher → `runsync --auto`), it is the same service with the
same config: pairs + interval in `ui_prefs.json`, on the device.
`startup_defaults()` layers that record > `[daemon]` in the TOML > all pairs /
30 min, for the window, `--auto` and the watcher alike; explicit `--auto`
arguments still win (shortcuts, cron, and watchers not yet reinstalled). **Only
starting the service writes it** (`_atender()`, action `daemon`): a manual pass
with a few pairs ticked must not decide what the service syncs at the next plug-in.
A record with `action == "manual"` predates that and is ignored (by `== "manual"`,
so a hand-written record without `action` still counts). The file keeps its old
name: renaming it would need a migration to change a word. `--auto --once`
(`una_pasada()`) is one pass of those pairs with no service behind it; with a
live service on this host it does nothing and does **not** stop it — swapping a
service for a single pass would leave the device without one.

**One window at a time, and the watcher waits for it.** `ui_flow()` checks
`ui.lock.json` **before** `stop_previous_daemon()` and refuses to open a second
window — opening runsync stops the previous service, so two windows would take
the service from each other. A record whose pid is dead, or that belongs to
another host, is the trace of a device pulled without closing anything, and is
cleaned exactly like the daemon's. The lock is taken around `_atender()` and
released in a `finally`. `penwatch` reads both locks (never writes them) and
launches nothing while either is alive: the pass is logged and the trigger is
spent, so it does not retry every minute behind an open window. Both facts are
said out loud — the pause in the watcher line of the main window (and the
console menu), the other in the message that confirms the service — but only
when this host's watcher attends to this device (`watch.resumen().vigila_este`);
otherwise they would describe something that does not exist here.

**Windows specifics to preserve:** `pid_alive()` uses `OpenProcess`, never
`os.kill` (which *terminates* on Windows); the daemon is spawned with
`pythonw.exe` + `CREATE_NO_WINDOW`, rclone with `CREATE_NO_WINDOW` too (else
every invocation flashes a console); the daemon `chdir`s to the temp dir so the
device can be ejected; child `sync.py` runs get `stdin=DEVNULL`, so a pair
needing `--resync` is skipped rather than resynced unattended.

**Failure pop-up.** `daemon_cycle()` calls `notificar_fallo()` only when a pair
*starts* failing (compared against the previous cycle's `last_results`), so a
healthy service is silent and a persistent outage does not reopen a window every
cycle. `ui.avisar_fallo()` runs it in its **own thread with its own Tk
interpreter**, and everything Tk must die there: `theme.olvidar()` /
`icons.olvidar()` drop the per-interpreter caches and `gc.collect()` runs in that
thread, or the main thread frees the images at exit (`Tcl_AsyncDelete`). No
display → False, and the notice stays in `daemon.log`. One window at a time.

## UI (`ui/`)

Two frontends implement the same four operations (`ask`, `approve_resync`,
`info`, `run_sync`) and both return `Choice(action, pairs, minutes)`.
`ui.start(config, msg)` returns the choice **together with the frontend that took
it** — a window cannot dump output to a console that does not exist.

- **`import tkinter` always goes inside functions, never at module top.** `ui/`
  is imported by headless paths (`--auto`, the service) where tkinter may be
  absent; the failure must surface when the window opens, so `ui.start()` can
  fall back to the console menu.
- `output_window` colours each line by content (`tk._tono`) using the vocabulary
  `sync.py` already prints (`=== pair ===`, `  ejecutando:`, `[pair] OK.`…);
  change the wording there and a line stops being coloured, nothing breaks. It
  offers **Guardar el log** — the only copy of a good pass. The progress line is
  the exception: `_tono` recognises it by `progress.ETIQUETA`, **imported**, not
  retyped, and `append()` rewrites consecutive progress lines in place.
- `tk_pairs.confirmar_plan()` is a real window, one line per consequence, each
  warning in an amber box — not an `askokcancel`. This is the dialog that governs
  deletions. Tests replace it, like `mostrar()`.
- **«Expulsar», only inside a VeraCrypt container** (`ui/cifrado.py`). Closing
  the window does not close the `.hc`, and with it open the drive cannot be
  removed. This process runs *from inside* the container (the device's Python
  is in `.prdrive/runtime/`) and VeraCrypt only retries a busy dismount for
  1.5 s, so the button does not dismount: it launches the vestibule's
  `Expulsar PRDRIVE` script with its cwd on the physical root
  (`lanzar_expulsion()`, an indirection point) and closes. The script waits,
  then asks VeraCrypt without `/silent`. Disabled while a pass runs; with the
  window open there is no service (opening it stopped it).
- **The main window runs syncs itself:** «Sincronizar ahora», and whatever
  «Reparación» hands back, open a
  modeless `output_window`, the window disables whatever touches the same state,
  and on close re-reads `state/` and repaints. Only «Iniciar servicio» returns a
  `Choice` to runsync. The checkboxes are shared by both buttons and open with
  the service's pairs; «Marcar todas»/«Desmarcar todas» (two pairs or more)
  and the «N de M» follow them through each checkbox's `command`, **not** a
  variable `trace`: a widget's command dies with it, a trace's Tcl command does
  not, and it would hold the whole window and its images until exit. «Repetir
  cada» sits by the footer because the interval is the service's.
  `ui.manual_args()` (resync question + `--yes`) is shared with the console
  path. The pairs screen's «Simular», «Examinar…» and «Dispositivos…» write
  nothing, so none makes `open_dialog` return True.
- **The watcher line** replaced the «Arranque automático…» button: what this host
  does when the device is plugged in, from `watch.resumen()` (files only, no
  `schtasks`/`systemctl`: it is asked on first paint) and worded by
  `watch.linea()`, which the console menu shares. States: `sin_instalar`,
  `otro_dispositivo` (a host has one watcher; `watch.json`'s `device_id` is
  another prdrive's), `desfasado` (amber), `instalado` + mode. Its button opens
  `tk_watch` and the line is re-read on return; it stays enabled during a pass.
- `ConsoleFrontend.approve_resync` always returns False on purpose: with a real
  terminal `sync.py` inherits stdin and asks the question itself, with more
  context than a dialog fits.
- `save_prefs` stores `known` (the pair names that existed then) so a pair added
  later reads as new and comes back checked.

### Theme, icons and window sizing

Warm paper, near-black ink, one blue accent, amber for warnings, monospace for
paths and flags; no rounded corners, no shadows. Styles cross **role** with
**surface**, because a `ttk.Label` does not inherit its parent's background;
`theme.apply()` switches to **clam**, once per Tk interpreter.

- **`theme.nitidez()` runs before the first `Tk()`** (all five places that open a
  root) and declares **system** DPI awareness — not per-monitor, Tk 8.6 ignores
  `WM_DPICHANGED`. Without it the compositor stretches the bitmap, and that
  stretch is the blur no font work can fix.
- **Design distances go through `theme.medida()`, never a bare integer** (Tk
  reads a plain number as unscaled pixels); `icons.px()` is for what Tk cannot
  scale at all. An eyebrow's gutter is reserved with `theme.ancho_rotulo()` +
  `columnconfigure(minsize=…)`, never a `width=` in characters.
  `tests/test_tk_densidad.py` enforces both.
- `icons.py` rasterises the glyphs itself (no deps, Tk cannot read SVG, «no
  emoji»); `icons.get()` returns None on failure and the caller keeps its text.
  `write_ico()` paints `runsync.ico` headless — **repainted** into `.prdrive/`,
  never copied, so no second glyph table drifts. A `ttk.Treeview` cannot colour
  one cell, so status chips are row tags (`theme.marcar_lista`).
- **Windows are shown already centred, never moved after the fact.** `modal()`
  returns the dialog **withdrawn** and without a grab; `mostrar(dlg, parent)`
  centres, deiconifies, grabs and waits, and `grab_set()` / `update_idletasks()`
  must stay on their current side of the `deiconify()`. Tests replace
  `mostrar()`, not `modal()`.
- **Every screen sits inside a `tk.Visor`** (`encajar()` sizes `interior` to the
  content or to what fits; scrollbars only when content is left over). The wizard
  root centres **once**, and `Wizard.reencajar()` hangs off `revisar()`, not
  `repintar()`, because three things change a step's height without a step
  change. When even growing does not fit (a long error above the button that
  retries it), `Visor.ver(widget)` scrolls just enough to show that widget whole.
  `tests/test_tk_medidas.py` checks every screen against a matrix of
  resolution **and** `tk scaling` — the scaling column is the half that matters.
  The main window opens its own interpreter, so it is measured on the same
  matrix in `tests/test_tk_servicio.py`, in its worst case: twelve pairs, the
  amber watcher line and «Expulsar» in the footer.
- `tk.working(parent, title, funcion)` runs `funcion()` on a thread behind a bare
  progress bar, for slow or passphrase-carrying commands. No cancel button.
  An optional `progreso()` → `(fracción, texto)` or None turns the bar
  determinate with the text below while it answers, and back when it stops; it
  is asked from the Tk thread every 120 ms, so it must only read what another
  thread measured, and any exception counts as None — the poll is the only
  thing that closes the window. The text's row is reserved from the start
  (`tests/test_tk_espera.py`, and the matrix in `test_tk_medidas.py`).

### «Ajustes» (`ui/tk_doctor.py`) — where new affordances go

The main window is deliberately lean, so **anything done once in a device's life
belongs behind the gear, not beside «Sincronizar ahora»**. The screen is
«Ajustes» —the module keeps the old name— and it is not the `--doctor` command:
«Reparación» is its first entry, the pairing code its second, and
`ENTRADAS` is the list to add to. It receives `lanzar` and `abrir_reparacion`
from the main window rather than importing them, because the output window and
«Reparación» are the *main* window's children and it disables itself while a
pass runs — this screen knows none of that, and closes itself before handing
over so two modals never hold the grab at once.

### «Reparación» (`common/revision.py` + `ui/repair.py` + `ui/tk_repair.py`)

**One diagnosis, three layers.** `revision.revisar(config)` returns `Hallazgo`s
(clave, título, detalle, pareja, gravedad, dato) and `revision.informe(config)`
returns the same thing as the text `sync.py --doctor` prints — which is now all
`doctor()` does. It lives in `common/` for one reason: **`sync.py` does not
import `ui/`**, so a diagnosis on the window's side would be a second one, and
the two would drift. `ui/repair.py` answers "and what do I do about it" with
plans in the `EditPlan` shape (`consequences`/`warnings`/`execute()`), and
`ui/tk_repair.py` only draws.

- **What has a button and what doesn't.** `prefijo` shelves the baseline
  (`bisync.shelve_baseline`), `lock` deletes the stray `.lck`s, `resync` and
  `fallo` are not disk plans (a pass through `lanzar`, and opening the log).
  **A missing local dir deliberately has none**: creating it is exactly what
  `_bisync_preflight()` refuses to do when a baseline exists, because an empty
  local side reads as "everything was deleted". The screen says so instead.
  Nor does **`espacio`**: a *dynamic* (sparse) VeraCrypt container with under
  `vestibulo.UMBRAL_LIBRE` (1 GiB) free on the physical drive. It grows as it is
  written, so when the drive fills the volume inside throws I/O errors mid-pass
  and rclone cannot say why — the fix is freeing space outside.
- **Deleting a lock asks who is syncing first.** `repair.sincronizacion_en_curso()`
  reads `model.daemon_lock()` and errs towards "yes, someone is": another host's
  record cannot be checked with `pid_alive`, and refusing to delete costs
  nothing while deleting under a live pass does not.
- **A `fallo` says since when** (#20): `revision._fallos()` adds one sentence
  from the pass journal, «Falla desde el 12/09 · 0 de las últimas 14 bien.»
  («al menos desde» when every recorded pass failed: the streak may predate the
  journal). It goes in the `detalle`, so `--doctor` prints it too; no journal,
  or one whose last line is not a failure, and the finding reads as before.
- **Nothing repairs itself**, not on open and not on click: every plan goes
  through `tk_pairs.confirmar_plan()`. After executing, the screen re-runs
  `revisar()` whole rather than crossing out the row it just fixed.
- **The conflicts are a section, not a window.** `tk_conflicts.seccion()` builds
  the tree into whatever frame it is given; there is no `open_dialog` any more,
  so the only way in is through «Reparación». `conflict_editor` is untouched.
- **The main window says it in one line.** Up to three amber blocks (last run
  failed, files in conflict, resync pending) became `revision.cuenta()` in the
  header chip plus one line with a «Reparación…» button, hidden while a pass
  runs — the same rule that used to disable those blocks' buttons. The update /
  components block stays as it was: an offer is not a fault, and counting them
  together is what made everything weigh the same.

## The drive's name and icon (`common/autorun.py` + `ui/volumen.py` + `ui/tk_volumen.py`)

«Ajustes» → «Nombre e icono de la unidad…» sets what Windows Explorer shows for
the drive through the root's `autorun.inf`: `label=` and `icon=` are still read
on arrival although AutoRun has run nothing from removable media since Windows 7.
No admin, any filesystem, accents allowed — the filesystem label is untouched.
Seen on real hardware only for the traveler's file (M1 in the VeraCrypt results):
it shows **after replugging**, and the window says so.

- **The file is edited, never rewritten.** `autorun.con()` replaces `label` and
  `icon` under `[autorun]` and keeps every other line; `autorun.sin()` drops
  only the keys its caller names. `traveler.write_autorun()` edits too: it keeps
  an existing label, an icon that is not VeraCrypt's and every foreign line,
  re-points a VeraCrypt icon at the executable the drive carries now
  (`vestibulo.traveler_ejecutables()`; `autorun.ICONOS_VERACRYPT` recognises the
  old `VeraCrypt\VeraCrypt.exe` too), and **removes** the `action=` /
  `shell\montar…` / `shell\desmontar…` it used to write — Windows ignores them on
  a removable drive (M2) and they pointed at an exe the portable does not have.
  UTF-16 + CRLF, like VeraCrypt's own; `buscar()` matches the name
  case-insensitively. Nothing left → file deleted.
- **Which root:** the one that is plugged in. Unencrypted and BitLocker are the
  same case, `DEVICE_ROOT` (BitLocker's unlocked volume *is* the one plugged
  in); `vestibulo.raiz_fisica()` when the device lives in a VeraCrypt container
  (the mounted volume is not what the user plugs in). The window prints the path
  it writes to.
- **Where the icon lives:** `Estado.carpeta`. In `.prdrive/`
  (`icon=.prdrive\icono-verde.ico`, derived from `APP_DIR.name`, not
  hard-coded), so the root holds nothing but `autorun.inf`. On a container's
  physical root there is no `.prdrive/` — the one inside cannot be read before
  the container is opened, and Explorer reads the icon on arrival — so there it
  sits beside `autorun.inf`, hidden with `store.hide()` (moved there from
  `install/deploy.py`, which re-exports it) and prefixed
  (`.prdrive-icono-verde.ico`), and counts as noise through `device.es_ruido()`,
  since hashed names cannot sit in the `RUIDO` set. A stray plaintext
  `.prdrive/` on that root is never touched (`crypto.restos_en_claro()`).
- **The choice is read back from `icon=` itself** — no separate state: the icon
  file name carries the key (`icono-verde.ico`), a user's `.ico` a hash slice
  (`icono-propio-<8 hex>.ico`), and it counts only in the place prdrive would
  put it (prefixed at the root, bare inside `.prdrive/`). A new drawing is a new
  name because Explorer caches icons by path; `recoger()` then deletes our other
  icons, at the root too, which moves an old root icon into `.prdrive/` on the
  next save. An `icon=` prdrive did not write reads as `OTRO` and survives a
  name-only save.
- The five colours are `icons.CAMPOS` (brand field only; white and amber stay).
  Painting one is ~2 s (the 256 px size), so the save runs in `tk.working()` and
  an existing file is never repainted. Unverified on real Windows: an icon
  inside the hidden `.prdrive/` or with the hidden attribute itself; whether
  Explorer reads the file when a BitLocker drive is *unlocked* (locked, it
  cannot); and a *change* of name or icon (M1 saw a first write) — the
  per-drawing file name is there so the icon cache cannot win.

## Pairing a phone (`common/pairing.py` + `ui/qr.py` + `ui/tk_qr.py`)

«Ajustes» → «Emparejar un móvil…» shows the device's connection as a QR so a
phone can read it. Three pieces, none of which knows about the other two's medium:

- **`ui/qr.py` is a full QR encoder**, written here for the same reason
  `ui/icons.py` draws its own icons: no dependencies. Byte mode only (the payload
  is UTF-8 with base64 inside — the other three modes would save nothing), but
  everything else is complete: 40 versions, four ECC levels, block-interleaved
  Reed-Solomon, all eight masks and the penalty score that picks one. Constants
  cite **ISO/IEC 18004** the way `common/bisync.py` cites rclone's source;
  **preserve those citations.** Only two tables can't be derived
  (`_CORRECCION_POR_BLOQUE`, `_BLOQUES`) — everything else is computed, and
  `tests/test_qr.py` pins the derivations against the published byte-mode
  capacities, which is what would catch a mistyped digit in either table.
- **`common/pairing.py` builds the payload, and lives in `common/` on purpose:**
  `install/` does not travel to a provisioned device and this runs *on* one, with
  no network. Same reason `parse_rclone_conf()` moved here and
  `install/profile.py` re-exports it — **one reader of rclone.conf, not two**, and
  `RUTAS_DERIVADAS` is shared for the same reason.
- **The payload format is `profile.dumps()`'s, plus three keys** (the `prdrive`
  marker, `private_key_b64`, `known_hosts`). Those three are surplus to
  `profile.loads()`, so the *same text* goes straight into it — no second
  parser, no translation layer. `tests/test_qr.py` does that whole round trip
  (device → payload → QR → decoded → `profile.loads()`) and is what keeps the two
  formats from drifting. **All bare keys must precede `[options]`**: in TOML a
  stray line after the table header would put the private key inside the
  backend's options and from there into the phone's rclone.conf.
- **This shows a private key on screen and says so**, in an amber block. It is
  not a token and it does not expire: whoever photographs the screen gets the
  remote. The window stores nothing and copies nothing to the clipboard.
- The pairing window asks for correction **L**, not the module's default M: the
  medium is a screen (no creases, no print, no dirt) and what is scarce is
  capacity — an RSA-3072 key does not fit in *any* version at M. It fails with a
  sentence rather than a stack trace when even L is not enough.
- `icons.matriz()` rasterises the modules — pure black and white, integer module
  size, quiet zone added there — and does **not** cache: the caller holds the
  reference or Tk loses the image.

## Provisioning a device (`prdrive-install.py` + `install/` + `ui/tk_install.py`)

Eight steps; the order is load-bearing (you cannot read the catalogue before
knowing the remote, pick pairs before knowing where the device goes, or
initialise them before the `sync.py` that does so exists):

```
1 Dispositivo     which volume + the "already a prdrive" shortcut
2 Cifrado         VeraCrypt / BitLocker / none  → fixes state.device_root
3 Conexión        form, or import a remote from the user's rclone.conf
4 Comprobaciones  rclone + connect + read the catalogue
5 Instalación     full/light + platform list; copy .prdrive/, hide it, rclone +
                  runtime per platform, launchers, rclone.conf + keys
6 Parejas         pick from the catalogue, write sync_config.toml, make dirs,
                  publish the device's note in the fleet registry
7 Inicialización  --resync of the bisync pairs
8 Verificación
```

Each step disables «Siguiente» until its condition is met. **No console
fallback** here (unlike `runsync.py`): this happens once in a device's life.

**Nothing in the wizard spawns a shell** — to a behavioural AV engine an unsigned
`.exe` in `%TEMP%` spawning `powershell.exe` is the shape of a dropper. Windows
is asked directly instead: BitLocker state through `IShellItem2::GetInt32` with a
PROPERTYKEY from `PSGetPropertyKeyFromName` (**never** a remembered one), where
only state `On` counts as protected — *Waiting for activation* must fail, or the
private key lands on a volume whose key is still in the clear; and the volume
list through kernel32, needing `SetThreadErrorMode(SEM_FAILCRITICALERRORS)` (an
empty card reader otherwise pops a "no disk" modal) and `TIPOS_OCULTOS`
(`GetLogicalDrives` returns mapped network drives). There is **no recovery-key
feature**: reading one needs elevation.

**The "already a prdrive" shortcut.** On `device.install_target() ==
YA_INSTALADO` the device step shows the device's version vs the installer's and
offers **«Actualizar»**, **«Añadir plataformas…»** and **«Reinstalar desde
cero»** — reinstall **always**, so re-provisioning (new remote, re-encrypt, redo
pairs) stays possible without deleting `.prdrive/` by hand.

- `Wizard.pasos` is an **instance** attribute: three step lists
  (`PASOS_INSTALACION`, `PASOS_ACTUALIZACION`, `PASOS_PLATAFORMAS`), and the
  button picks one and sets the index. `_ok_destino` stays False until a way out
  is chosen.
- `install_target()` looks for the **device before the content** (`.prdrive` is
  in `RUIDO`), or a freshly provisioned volume reads as `VACIO` and the shortcut
  is missing on the newest device that can exist.
- The short path installs the tree the **installer carries** (`bundle_dir()`, the
  same source step 5 uses) — no network — and calls
  `ensure_control_file(renew=False)`: step 5 renews because it provisions, but
  renewing here would strand a watcher bound to this device's id. Going backwards
  in version is allowed but never silent (`_confirmar_retroceso()`).

**VeraCrypt: what not to weaken.** Every claim below is checked against
VeraCrypt's source (tag `VeraCrypt_1.26.24`, and `master` where it matters), not
its docs, and the citations are in the code — keep them like the rclone ones in
`common/bisync.py`. The design and the evidence table are in
`docs/superpowers/specs/2026-09-23-veracrypt-ciclo-de-vida-design.md`.

What a **real Windows run** found is in
`docs/superpowers/pruebas/2026-09-24-veracrypt-unidad-g-resultados.md` (the plan
is the file beside it; the helper scripts lived outside the repo). Read it
before touching VeraCrypt on Windows. It has:
- a table per test;
- findings H-1…H-10 with their evidence;
- the fixes and a second pass after them (sections 8–10);
- what the plan got wrong, e.g. the portable package has no `VeraCrypt.exe`,
  unplugging leaves a ghost volume, and a forced dismount *may* keep the `.hc`
  held.

Still unverified on real hardware:
- an installed VeraCrypt (`ERR_DRIVER_VERSION`);
- the «retenido» branch;
- the new eject wait;
- Linux;
- the VeraCrypt Portable of #50 (tests V1–V7 in the issue; results go in
  `docs/superpowers/pruebas/`): V1 create + mount on Windows x64 with nothing
  installed, from the cache; V2/V3 the same drive opened on Windows ARM64 and
  back, the `.bat` choosing by `%PROCESSOR_ARCHITECTURE%`; V4 another VeraCrypt
  version installed (installed first, no `ERR_DRIVER_VERSION`); V5
  `--update-components` with a nearly full drive, and the swap with room; V6 a
  corrupt / cut download; V7 `_esperar_copia_elevada()` seeing
  `VeraCrypt Format-x64.exe`. Also unverified: whether the traveler's `.sys` is
  held open while its driver is loaded (`veracrypt_en_uso()` only probes the
  files), and Explorer showing the icon of `VeraCrypt-x64.exe` on Windows ARM;
- the creation progress counters (#46, tests P1–P7 in the issue): whether
  `IOCTL_DISK_PERFORMANCE` on `\\.\X:` answers **without admin**, whether it
  counts the filesystem's zero-fill and the elevated Format copy's writes, the
  SLC curve of a long fixed creation, and `/sys/dev/block/…/stat` on a USB
  stick. The Linux path was only seen counting on a local virtio disk;
- opening and closing on Linux **without** VeraCrypt (udisks2 / cryptsetup,
  #51): written against udisks `master` and cryptsetup `main`, not run on any
  distribution. The plan is U1–U10 in the issue; **U9** (write on Linux through
  each route, check the sums on Windows with VeraCrypt, and back) is the one
  that says whether the data survives, U4 decides penwatch's `loop-setup`, and
  U8 is H-10's ghost on Linux (unplugged with the container open), unhandled.

Agent trap: this machine's Bash tool is sandboxed. It redirects writes under
`%LOCALAPPDATA%` (a `penwatch install` from there registers a task that points
at nothing) and hangs `tasklist | find`. Use PowerShell for both.

- **Creation speed is `/dynamic`, and it is asked before it is used.** `/quick`
  does *not* stop VeraCrypt writing the whole container: `FormatNoFs()` walks it
  writing a zeroed sector every 128 MiB *on purpose* (`Common/Format.c`), and
  NTFS zero-fills each gap — which is why a container is instant on an internal
  SSD and half an hour per 50 GiB on USB. `/dynamic` makes the file sparse and
  the walk costs one cluster per chunk. VeraCrypt **aborts** with
  `ERR_DYNAMIC_NOT_SUPPORTED` when the host has no sparse support
  (`Format/Tcformat.c`), so `crypto.soporta_dispersos()` asks first — by the
  `FILE_SUPPORTS_SPARSE_FILES` flag, the same evidence VeraCrypt uses, never by
  the filesystem's name. On Linux there is no equivalent: `--quick` is forced off
  for file containers in 1.26.24 (`Main/TextUserInterface.cpp`; `master` drops
  that line), so there the only lever is the size, and
  `crypto.suggested_size()` stops proposing nearly the whole disk.
- **A fixed container shows its real progress, and the estimate is a floor.**
  `medir_escritura()`'s 8 MiB probe measures the *burst*: USB sticks drop to a
  half or a quarter once their SLC cache fills (#46: «unos 23 min» said, 40 min
  and still writing), so `describir_espera()` says «al menos» and why. While
  creating, `crypto.Seguimiento` reads the **drive's own write counter** —
  `crypto.bytes_escritos()`, an indirection point: `DISK_PERFORMANCE.BytesWritten`
  via `IOCTL_DISK_PERFORMANCE` on the volume opened with access 0 (ctypes, no
  shell), or field 7 of `/sys/dev/block/<maj>:<min>/stat` × 512 — noting the
  first reading **before** VeraCrypt launches, then once a second on its own
  thread until `create_container()` returns. `avance()` is pure: fraction capped
  at 99 %, time left from the last 60 s (so it rises when the cache runs out),
  and **None — back to the bare bar — when the counter fails, goes down, never
  moved or stops for 30 s**. Better no number than a false one. Only when not
  `/dynamic`; the creation waits exactly as before.
- **A FAT32 host caps the container at 4095 MiB** (`crypto.tope_contenedor()`),
  checked in `create_container()` before VeraCrypt runs. Not 4 GiB − 1: VeraCrypt
  rounds `/size` **up** to the sector size (`Format/Tcformat.c`). The name is
  compared whole — `exfat` contains «fat» and has no cap.
- **The container exists when the elevated copy is done, not when our process
  exits.** The travelling `VeraCrypt Format`, without admin rights, relaunches
  itself elevated (`/q UAC`) and exits 0 while the copy is still writing;
  mounting in that gap left a volume with no filesystem, and the container was
  useless. `create_container()` notes the processes with that executable's name
  before launching and waits for the new ones to exit
  (`_esperar_copia_elevada()`). The list comes from a Toolhelp snapshot
  (`crypto._procesos()`, an indirection point): WMI did not show the elevated
  copy. No time limit, like the command itself.
- **`/m rm` is not cosmetic.** Mounted without it, Windows creates
  `$RECYCLE.BIN` *inside* the container, i.e. inside what rclone syncs. It does
  **not** stop `System Volume Information`: Windows 11 24H2 creates it on mount
  as on any USB stick (seen on a real drive). Harmless — no pair syncs the
  device root, and `device.RUIDO` ignores it.
- **The password is checked the way `/silent` stops VeraCrypt from checking
  it.** `CheckPasswordLength(…, Silent, Silent)` skips the short-password
  question (`Format/Tcformat.c`, `Common/Password.c`), so
  `crypto.revisar_contrasena()` asks it: under `PASSWORD_LEN_WARNING = 20` a
  question with «No» as default, over `MAX_PASSWORD = 128` an error — both in
  **UTF-8 bytes**, as VeraCrypt measures.
- **There is no favourite, on purpose.** `write_favorite()` stored the container
  as `\\?\Volume{GUID}\PRDRIVE.hc`, and `VolumeGuidPathToDevicePath()`
  (`Common/Dlgcode.c`) only resolves paths ending in `}\` — the arrival timer in
  `Mount/Mount.c` skipped it every time, so it **never** mounted. Setting
  `StartOnLogon` in `Configuration.xml` registers nothing (`ManageStartupSeq()`
  only runs from the Preferences and Favourites dialogs), and the file was
  rewritten from scratch, wiping the user's favourites. The note in `crypto.py`
  says why it is not coming back.
- **No VeraCrypt installed is fine on Windows: the official Portable, never
  run to unpack it (#50, #38).** `install/veracrypt_bin.py` downloads
  `pins.VERACRYPT_URL` (versioned, never an alias), checks it **in memory**
  against `pins.VERACRYPT_SHA256` — IDRIX publishes no sums file, so whoever
  moves the pin checks the Authenticode and PGP signatures by hand once and
  writes the hash down — and reads the self-extractor with the stdlib
  (`Setup/SelfExtract.c`): both markers from the **end**, like
  `FindStringInFile()` (`VCINSTRT` also sits in the extractor's code), the
  package CRC of `VerifyPackageIntegrity()` (up to the end marker, bytes
  0x130–0x1ff zeroed by `WipeSignatureAreas()`), the compressed length reaching
  the end marker, each file's CRC, and every name validated before the first
  write. Only exes, drivers, `.cat`, `.inf` and licences are kept, in a cache
  per version whose stamp (`PRDRIVE-VERACRYPT`, written last) carries each
  file's SHA-256 and is re-hashed on every use. `SinRed` (could not *download*,
  after `descarga.con_reintentos()`) is distinct from a package that does not
  check out, which is never retried; the package saved by hand in the cache
  under its exact name is adopted with the same checks (`adoptar()`), and the
  error says the exact URL and pinned SHA-256. `crypto.find_veracrypt()`
  tries the user's folder (installation or portable layout, never mixed), then
  the **installed** one, then the verified cache; the portable's names come
  from `crypto.arquitectura_vc()`, i.e. `model.machine_arch()` — the native
  machine, like VeraCrypt's `IsARM()`. The panel's «Descargar VeraCrypt
  Portable» button fetches it; with it, every step asks for UAC.
- **`traveler.py` puts the Portable on the volume, both architectures, as a
  component.** There is no CLI for this: VeraCrypt's own dialog extracts the
  binaries from its self-extractor (`Mount/Mount.c`, `TravelerDlgProc`), and in
  portable mode it copies `VeraCrypt-x64.exe`, `-arm64.exe` and both drivers
  with those names — which is what travels now, unrenamed. It works because
  `DriverLoad()` (`Common/Dlgcode.c`) loads `<exe dir>\veracrypt-x64.sys` or
  `-arm64.sys`. The folder is **swapped**, never copied over: new beside
  (`.VeraCrypt.nuevo-<pid>`), old moved aside, rename; free space on the
  physical root is checked first (`traveler.espacio_libre()`, an indirection
  point) and if it does not fit nothing is touched; copies are re-hashed against
  the stamp, which is written last. Leftovers are noise
  (`vestibulo.es_resto_traveler()` in `device.es_ruido()`). `crypto.size_to_bytes`
  with `viajero=True` leaves `RESERVA_VIAJERO` (256 MiB) instead of 50 MiB so a
  'max' container still leaves room for that swap. **Without network** (only
  `SinRed`) and with a VeraCrypt on this host, the old path: copy the
  installation, renaming `VeraCrypt.exe` / `veracrypt.sys`… to the portable
  names from the architecture in their **PE header** (`maquina_pe()`), exactly
  what VeraCrypt's own dialog does for an MSI install (the installer leaves
  **`veracrypt.sys`**, `Setup/Setup.c`: `szFiles[i]+1`). That copy has one
  architecture and **no stamp**, and it never replaces a stamped portable.
  Three things that must stay said out loud: it still needs **administrator** on
  the host, the signature is **not** verified the way VeraCrypt verifies it
  (the portable is checked against the hand-verified pin; an installation copy
  against nothing), and each architecture works **only on its own**: `IsARM()`
  asks for the *native* machine, so an emulated x64 VeraCrypt on Windows ARM
  looks for the arm64 driver, and a driver is never emulated. This is **not** the
  one-way fallback of `BIN_FALLBACK_DIRS`. The folder lives on the **physical**
  root beside the `.hc`, never inside the container, and `"veracrypt"`
  therefore belongs in `device.RUIDO`.
- **Re-encrypting leaves the old tree where it was.** «Reinstalar desde cero»
  with VeraCrypt over an unencrypted prdrive creates the container beside it;
  `crypto.restos_en_claro()` finds the plaintext `.prdrive/` (with the key) and
  the data folders, the panel says so in red before creating, and step 8 keeps a
  red row. **Nothing deletes it**: those folders may hold unsynced changes.

**The vestibule (`common/vestibulo.py` + `install/vestibulo.py`).** With
VeraCrypt everything — code, launchers, guide, control file — is inside
`PRDRIVE.hc`, so a machine sees an opaque file until it is opened. The physical
root therefore gets `Abrir PRDRIVE.bat` / `Expulsar PRDRIVE.bat`,
`abrir-prdrive.sh` / `expulsar-prdrive.sh`, `LEEME-PRDRIVE.txt` and the hidden
marker `.prdrive-vestibulo`, whose `id=` is **the same** as `.prdrive/PRDRIVE`
inside: that id is what joins the two halves. `common/` holds the names and
`leer_id()` (the device needs them; `install/` does not travel); `install/`
writes the texts. Five things not to weaken:

- **The password never passes through us.** `VeraCrypt.exe /volume X /quit`
  without `/password` asks with VeraCrypt's own dialog (`Mount/Mount.c`,
  `WM_INITDIALOG`). No `/auto`: it also opens an Explorer window.
- **The installed VeraCrypt before the travelling one**: with another version's
  driver loaded, the traveller fails with `ERR_DRIVER_VERSION`
  (`Common/Dlgcode.c`, `DriverAttach`). Of the travelling one, the Portable of
  this machine's architecture (`VeraCrypt-%VC_ARQ%.exe`, from
  `%PROCESSOR_ARCHITECTURE%`, truthful in a `.bat`), then the
  `VeraCrypt\VeraCrypt.exe` of an old device; penwatch does the same with
  `native_arch()`. `VC_IMAGEN` is the image name `tasklist` looks for.
- **The exit code is not the mount.** The traveller without admin rights
  relaunches itself elevated with `/q UAC` and exits 0 after two seconds
  (`InitApp`, `LaunchElevatedProcess`), so the `.bat` waits to *see* the drive
  (by the control file's id) — 10 s with the installed one, 180 s with the
  traveller.
- **Eject is `/dismount <letter> /quit` without `/silent`**, after a short
  wait: VeraCrypt only retries 30 × 50 ms (`Common/Dlgcode.h`), and without
  `/silent` it asks whether to force. `/unmount` does not exist before 1.26.24.
  With the travelling VeraCrypt that question comes from the elevated copy,
  which `start /wait` does not wait for, so while a `VeraCrypt.exe` that was not
  running before is alive the 30 s do not count (`:vc_pendiente`, via
  `tasklist`, which sees an elevated process's name without elevation).
  **The letter going is not enough**: forcing it with a file still open inside
  drops the letter while Windows keeps refusing to remove the drive, so the
  script says «ya puedes quitar la unidad» only once `:libre` sees the `.hc`
  free.
- **A letter with the id is not proof the container is open.** Unplugging
  without ejecting leaves the inner letter behind, serving the control file from
  cache, and `Abrir` used to launch prdrive from it. With the real volume
  mounted the driver holds the `.hc` without write sharing (`TCOpenVolume()`,
  `Driver/Ntvol.c`), so a letter with the id beside a free `.hc` is that ghost:
  the script says how to get out («Expulsar», then «Abrir») instead of
  launching. `:libre` opens the `.hc` for append with `type nul`, which changes
  nothing, and answers «held» when there is no `.hc` to look at. Its blind spot
  is a shared mount (`MountVolume()` in `Common/Dlgcode.c` falls back to one
  when someone else had the file open), and there it costs two extra clicks.

Same rules as the launchers inside: CRLF, no parenthesised blocks, `chcp 65001`
before any accent, written by step 5 (right after `ensure_control_file()`, which
is where the id comes from) and by «Añadir plataformas…», **never** by
`--update`. `vestibulo.destino(state)` decides whether there is one (the `.hc`
on the physical root and the device mounted elsewhere). Its six names are in
`device.RUIDO`, built from `vestibulo.TODOS`. `tests/test_vestibulo.py` reads the
`.bat`, **runs** the `.sh` (with `sh`, and `dash`/`bash --posix` when present)
against fake `veracrypt`/`udisksctl`/`cryptsetup`/`losetup`/`mount`/`sudo`/
`pkexec` on a toy system, and, on Windows, runs `:libre` against a container
held the way the driver holds it. Rewriting the vestibule goes through
`deploy.unhide()` first: Windows refuses `open(…, "w")` on a hidden file, and
the marker is hidden.

**Linux without VeraCrypt (#51).** A container as prdrive makes it (AES, SHA-512,
PIM 0, no hidden volume) is also opened by udisks2 and cryptsetup, so
`abrir-prdrive.sh` takes the first of: VeraCrypt (as before) → udisks2, only if
`TCRYPT_CONF` (`/etc/udisks2/tcrypt.conf`) exists → cryptsetup with `sudo` →
a message with the three ways out. Citations in `install/vestibulo.py` and rows
15–22 of the spec's table. Not to weaken:

- **The password still never passes through us**, and that is why there is no
  opening without a terminal: `udisksctl unlock` reads the controlling tty
  (`read_passphrase()`, `tools/udisksctl.c`) and cryptsetup reads the tty only
  if stdin is one, otherwise **stdin itself** (`tools_get_key()`,
  `src/utils_password.c`). So no `pkexec` to *open* — it could not carry the
  password without piping it; `pkexec` only *closes* (no container password
  there), when the window's «Expulsar» launches the script without a tty.
- **prdrive never creates `tcrypt.conf`** (root, `/etc`, restarting a system
  service): the script and `LEEME` say how (`ACTIVAR_UDISKS`), and the
  cryptsetup route hints at it. Without it udisks never marks the loop
  `crypto_unknown`, so there is no `Encrypted` interface to unlock
  (`src/udiskslinuxblock.c`, `src/main.c`).
- **Closing is deduced, never recorded**: `losetup -j` → the loop,
  `/sys/block/loopN/holders/` → the dm, its name → who opened it (`veracryptN`
  VeraCrypt, `prdrive-<id8>` our cryptsetup, anything else udisks2's
  `tcrypt-…`), `/proc/mounts` → where. No loop → `veracrypt -d` if installed. It
  reports closed only after re-reading that state.
- A loop that udisks set up and did not unlock is deleted (it holds the `.hc`,
  and the drive could not be removed); a wrong udisks password does **not** fall
  through to cryptsetup — only «udisks does not recognise it» does.
- cryptsetup mounts at `/mnt/prdrive-<id8>` with `uid`/`gid` (exFAT/NTFS keep no
  owner), retrying without them for ext4; the empty dir is left behind.
- The scripts append `/usr/sbin:/sbin` to `PATH` (Debian keeps `losetup` and
  `cryptsetup` there, out of a user's `PATH`), and every system path goes
  through `$PRDRIVE_SISTEMA` (`VAR_SISTEMA`), empty in real life: it is how the
  test points them at a toy `/etc`, `/sys`, `/proc`, `/media`, `/mnt`.
- Devices provisioned before this keep their old VeraCrypt-only `.sh` until
  step 5 or «Añadir plataformas…» rewrites the vestibule — never `--update`.

Other step notes:

- With VeraCrypt, `.prdrive/` lives *inside* the container, so the volume looks
  empty until mounted — detection re-runs at the end of `_paso_cifrado`.
- Step 5 copies a folder of its own and touches nothing else, so it needs no
  `--dry-run` ceremony and runs straight through `ui.tk.working()`.
- **`Conexión` is what makes the repo publishable:** `profile.load()` returns an
  **empty** profile when nothing is embedded and nothing is in the checkout — not
  an error, the normal start for a fresh clone. The private key goes to a temp
  dir recording the owning pid; `remote.sweep_stale()` cleans what hard-killed
  installers left, asking `store.pid_alive()` first.
- **«Usar esta conexión» talks to nobody** (#47): it turns the form into a
  `Profile`, so the step says «preparada, sin probar» in plain ink — no ✔, no
  green, which read as "connection tested"; the remote is first touched in
  «Comprobaciones». What can be checked locally is, in `profile.py`, on both
  paths (form and import): a `type`, and `OBLIGATORIAS` — only what rclone marks
  `Required` with no way round (sftp `host` unless `ssh` is set: an empty host
  dials `:22`, this machine; webdav `url`; nothing for s3). Those block: the
  error goes in red in the step itself and the previous connection is dropped,
  so «Siguiente» is off. `profile.avisos()` only warns (amber, still enabled):
  an sftp without `user` logs in as whoever runs rclone on each host. Whether
  the `type` exists is not checked — that needs rclone, which step 4 has.
- **The key never leaves the device**, and `deploy.write_device_remote()` writes
  `.prdrive/rclone.conf` + `.prdrive/keys/<name>` with **relative** paths
  (`key_file = keys/…`) — that is what makes the device work under any drive
  letter, since rclone resolves them against `cwd = model.APP_DIR`.

**Platforms: the zero-install part.** Step 5 and the «Plataformas» short path
draw `_lista_plataformas()` over a `platforms.Matriz`: full/light, one checkbox
per `pins.PLATAFORMAS` entry (Windows/Linux × x64/ARM64 — macOS deliberately
absent), per-row sizes and a live total vs free space.

- **Full** = rclone + a python-build-standalone runtime per platform in
  `.prdrive/runtime/<clave>/`; root gets exactly `runsync.bat`, `runsync.sh`,
  `README.md` (a stale `runsync.pyw` is removed). **Light** = rclone only, plus
  `runsync.pyw` (useful only with a host Python). rclone stays in `bin/<arch>/`
  (`windows-x64` and `linux-x64` share `bin/x64`: `rclone.exe` vs `rclone`).
- **Deselecting a provisioned platform deletes only if confirmed**
  (`Matriz.quitar()` → `_preguntar_borrado()`); unconfirmed = left in place.
- **Downloads are pinned and verified** from `common/pins.py` (Python 3.13, not
  3.14 — those builds ship Tk 9 and the UI is measured on Tk 8.6).
  `runtime_bin.extract()` validates every member before writing the first, prunes
  pip/idle/tests/C headers (on Linux also `share/` and `libpython*.so` — the
  interpreter is static), never creates symlinks (exFAT) but materialises
  `bin/python3` by writing its target under that name, and writes the
  `PRDRIVE-RUNTIME` stamp **last** (no stamp = not installed).
- **Everything is fetched before the device is touched (#49).**
  `deploy.conseguir_plataformas(plan)` gets every rclone and runtime into the
  host cache, verified, and `apply_platforms(…, conseguido=)` only then deletes
  and copies; step 5 calls it **before** `deploy_code()`. It stops at the first
  platform that fails (each file was already retried three times, so trying the
  rest is minutes more behind a bare bar) and raises one `InstallError` that
  names it, says the device is untouched and that it can be unticked. The
  `wiz.revisar()` in step 5's (and «Plataformas»') error branch is what keeps
  the button in view under that dozen-line message (`test_tk_medidas`).
- `deploy.install_runtime()` extracts beside and **swaps**; if the old dir can't
  be moved aside (Windows: a `pythonw.exe` running from it) it fails whole and
  the old runtime stays. `remove_platform()` renames before deleting for the same
  reason. **No self-built executables, no `.vbs`.**
- The `.bat` avoids parenthesised blocks (a `)` in the device path would break
  them), is written with CRLF, and uses `chcp 65001` only in the error branch.
- **Launchers are immutable after provisioning**: written by step 5 and by
  «Añadir plataformas…» (an old device has no `.bat`, so its runtimes would be
  useless), **never** by `--update`, «Actualización» or `deploy_code()`
  (`tests/test_install_deploy.py` guards it). The vestibule outside a VeraCrypt
  container follows the same rule.

## Updating a device in place (`common/update.py` + `ui/tk_update.py` + `--update`)

The main window shows an amber block when GitHub has a newer release.

- **The applier runs from the download, not the device.** `install/` is
  deliberately absent from a provisioned device, so the update runs `python
  <extracted>/prdrive-install.py --update <volume>` — **the new version installs
  itself**. An applier in `common/` would be a second copy of the "what is the
  deployed tree" manifest.
- **The payload is the source zip of the tag (~270 KB), not the release `.exe`**
  — the CI exe is generic and would re-ask for the connection.
- **`.prdrive/` is never renamed:** `deploy_code()` copies file by file, because
  stage-and-swap breaks three ways — `rclone.exe` may be running from
  `.prdrive/bin/`; if `runsync.py` vanishes for an instant penwatch loses its
  `STRUCT_MARKER` and relaunches the UI; if `sync_config.toml` vanishes a running
  service shuts itself down.
- It does not touch `bin/`, `runtime/` or the launchers: runtimes are a
  component, not app code.

**`VERSION` at the repo root is the whole versioning story.** `install.version()`
reads it from `bundle_dir()`, `update.installed_version()` from `APP_DIR`. The
release workflow is **triggered by a push to `main` that touches `VERSION`** and
tags `v<VERSION>`, so the tag cannot disagree with the file; if the tag exists
there is no new version. A device with no `VERSION` reads as unknown, older than
anything. `check()` never raises and honours a 24 h cache in
`state/update.json`; `pending()` reads that cache and **never** goes to the
network (it is what the first paint asks).

**Components travel a different road, same shape.** `common/components.py` reads
the stamps (`runtime/<clave>/PRDRIVE-RUNTIME`, `bin/<arch>/<rclone>.PRDRIVE-RCLONE`)
and subtracts them from `pins.py`; pure and network-free, so the window asks it
while painting, exactly like `update.pending()`. `install/components.py` fixes
what it finds, from the zip for the same reason the code applier does. Four
things that must not be weakened:

- **The zip downloaded is the INSTALLED tag's** (`update.source_tag()`), not the
  latest release's: the pins travel with the program, so the machinery that
  fetches components must be the one from the version that pins them.
- **The rclone cache is keyed by pinned version** (`rclone_bin.cache_dir()`) and
  re-hashed against the sum recorded beside it on every use; without the version
  segment, moving `pins.RCLONE_VERSION` changes nothing because `find_rclone()`
  finds the cache before it considers downloading.
- **Only what can be asserted gets stamped** (`rclone_bin.pinned_version()`):
  nothing is known about an rclone found on the PATH, so it is left **without** a
  stamp. A stamp that lies is worse than none — the device would stop asking for
  the update it needs.
- **The swap is `install_runtime()`'s, for rclone too**: copy beside, move aside,
  rename; never `copy2` over the binary that is there. Whatever is in use is
  postponed with its reason (`rclone_en_uso` / `runtime_en_uso` /
  `veracrypt_en_uso`).

**The travelling VeraCrypt is the third component** (#50). Its stamp,
`VeraCrypt/PRDRIVE-VERACRYPT`, lives on the **physical** root, so
`components.pendientes(app_dir, fisica)` takes that root, or finds it through
`components.raiz_fisica()` (control-file id → vestibule marker, an indirection
point); a device not in a container has none. `Pendiente.plataforma` is None
and `ruta` is the folder. **An unstamped `VeraCrypt\` (an old device's
installation copy) is never touched by `--update-components` or `--update`**:
its vestibule only opens `VeraCrypt\VeraCrypt.exe`, and the vestibule is not a
component's to rewrite. It reads as pending with `asistente=True`, the window
says «Añadir plataformas…» and offers no button when that is all there is
(`components.actualizables()`), and `aplicar()` postpones it with that reason.
«Añadir plataformas…» writes the new vestibule **first** (it opens both
layouts) and then swaps in the stamped Portable (`traveler.llevar()`), so the
two stay coherent whatever happens to the second.

**What a download must survive** before going near the device: TLS, the zip CRC,
every name in `update.OBLIGATORIOS` present, no member whose path escapes the
destination (`_ruta_segura` — `extractall` is the footgun), and the `VERSION`
inside matching the tag asked for. There is no signature and the README says so.
`rclone_bin.download_rclone()` (and `runtime_bin`, same contract) pulls
`SHA256SUMS` and hashes the archive in memory before writing — a mismatch leaves
the cache untouched — from the **versioned** URL, never the `rclone-current-…`
alias, which moves. That defends against a truncated transfer, a proxy or a stale
cache, not against a compromised rclone.org. `rclone_for(plat)` keeps the old
lookup chain (checkout, next to the exe, PATH, cache) for **this** host so
offline provisioning still works.

`install/descarga.py` is what both downloaders share, and what a third (a
VeraCrypt one) should use: `con_reintentos()` retries **only** what another
attempt might not have (timeouts, resets, `IncompleteRead`, 5xx/408/429) three
times with growing waits (`ESPERAS`, via the indirection point `esperar()`);
never a 404, a certificate that fails verification, or a **hash mismatch** —
`fetch()` returns the whole body or raises, so a complete file that is not the
published one is something else answering, and retrying until one matches is
how not to notice. **Placing it by hand means the official ZIP, not the binary**
(rclone publishes sums of zips): `rclone_bin.a_mano()` / `runtime_bin.a_mano()`
name the exact files and folder (`rclone_bin.zip_a_mano()`), `adoptar_zip()` /
`adoptar()` verify it like a download and only then extract/record its sum, and
`descarga.sumas()` reads a `SHA256SUMS` left beside it **before** the network —
that is what makes it work offline, and it defends against exactly what the
network copy does, since both come from the same server. A hand-placed file that
does not match is reported and **not** downloaded over. A loose binary is still
accepted only for this host, and still unstamped.

## Mount watcher (`penwatch.py`)

The only entry point that installs anything on the host. `install` copies the
script to `%LOCALAPPDATA%\prdriveWatch` / `~/.local/share/prdrive-watch`, writes
`watch.json`, and registers a **per-user** logon-triggered Task Scheduler task
(XML via `schtasks /Create /XML`, UTF-16 — UTF-8 is rejected;
`DisallowStartIfOnBatteries` must stay `false`) or a systemd **user** unit
(`WantedBy=default.target` + `loginctl enable-linger`). No admin rights.

- It **polls** rather than subscribing to device events: on an encrypted device
  the arrival event fires long before the volume is readable.
- It identifies the device by the control file **`.prdrive/PRDRIVE`** (optional
  `id=<hex>` line), never by drive letter, and confirms `.prdrive/runsync.py`
  before launching. Fires once per mount — the trigger re-arms only when the
  device disappears. `--mode`: `ui` (default, `runsync.py`), `daemon`
  (`--auto`), `sync` (`--auto --once`). **No pairs, no interval**: they are the
  service's, live on the device and `runsync` reads them there, so penwatch still
  reads no device config. A legacy `watch.json` carrying them is ignored (the
  `Modo` status row still shows them while present: the old copy uses them). The
  old `sync` without pairs launched a bare `runsync.py`, which opened the window.
- **The host copy is never refreshed by itself**: `install` copies the script,
  `refresh_runtime()` only the Python. `copia_al_dia()` compares `SELF_COPY` with
  its own `__file__` (the device's, when called from the window or `.prdrive/`);
  on a mismatch `status_rows()` adds a warning row and the main window's line
  reads `desfasado`. Reinstalling is the fix.
- It must never write to, or `chdir` into, the device (that blocks safe
  ejection); config, state and log live on the host, and every device access is
  wrapped in `try/except OSError` (a locked BitLocker volume errors rather than
  reporting "not found"). It does **read** the device's `ui.lock.json` and
  `daemon.lock.json` (`aplicacion_en_marcha()`): with a window open or the
  service running on this machine it launches nothing, and the skipped trigger
  is not a failure — `_disparo_row()` says so instead of printing «FALLÓ».
- **A VeraCrypt device, closed.** `find_pen()` sees nothing until the container
  is open, so `find_vestibule()` looks for the vestibule marker
  (`VESTIBULE_MARKER`, same id as `device_id`, `CONTAINER_FILE` beside it) and
  `open_container()` launches VeraCrypt with the same command as
  `Abrir PRDRIVE.bat` — no password (VeraCrypt asks in its own window), the
  installed one before the travelling one, on Linux only with a display. It
  does **not** launch runsync: the ordinary loop does, once the volume shows up
  mounted, so the `mode` is respected and nothing races for the window lock.
  **Once per connection** (`state["vestibule"]`): a cancelled password is not
  asked again, nor after «Expulsar» with the drive still plugged; it re-arms
  only when the physical root disappears. The mounted volume disappearing with
  its vestibule still there marks it as asked too: a watcher installed with the
  container open never saw it closed, and «Expulsar» brought up the password.
  No id in `watch.json` → never asks. **Linux without VeraCrypt** (or without a
  display) it opens nothing: udisks2 and cryptsetup ask on a terminal it does
  not have. It logs the route this host has (`linux_open_route()`, same order
  as the script) and the `sh …/abrir-prdrive.sh` to run, once per connection
  as always. Doing the `udisksctl loop-setup` itself waits on **U4** (#51: does
  the desktop then ask for the password on its own?). Opened by hand,
  `posix_roots()` already finds it — `/proc/self/mounts` (`MOUNTS_FILE`) plus
  `/media`, `/run/media`, `/mnt` one and two levels down
  (`POSIX_MOUNT_BASES`, both replaceable by tests) — and the launch goes on as
  usual.
- `ui/watch.py` imports penwatch for reads and shells out for
  `install`/`uninstall`. One-way dependency. So does
  `common/vestibulo.raiz_fisica()`, lazily and guarded like `ui/watch.py`: one
  drive walk in the whole project (`penwatch.candidate_roots()`), the one that
  already avoids the «no disk» modal.
- **Its own Python**: `install` copies the device's runtime for this host
  (`runtime_keys_for()` chain) into `HOST_DIR/runtime/<stamp_id>/` and points
  `watch.json` and the task/unit at it, because `sys.executable` silently died
  when the user upgraded Python. **One dir per version, never swapped in place**
  (on Windows you cannot rename the dir of a running `pythonw.exe`):
  `refresh_runtime()` copies beside, rewrites the pointer atomically,
  re-`register()`s, and `prune_runtimes()` keeps `python_exe`'s, `task_python`'s
  and the running process's dirs. No device runtime for this host → host Python,
  never one living on the device.

## The resident agent (`agente.py` + `common/planificador.py` + `install/agente.py`)

Phases 1 to 4 of `docs/superpowers/specs/2026-09-25-instalacion-en-el-equipo-design.md`
(read it before touching this): the agent attends the prdrive drives plugged
into the host and, optionally, **the host root** (below), plain or in a
VeraCrypt container; with no root it is the **«solo agente»** install. On
Windows it has a tray (below). The later phases (window ↔ agent mailboxes,
«Actualizar», the Linux tray) are specified there and not built yet. **Nothing of this has run on a real machine**: what has to be
checked there, phase by phase, is the living list in
`docs/superpowers/pruebas/2026-09-25-equipo-pendiente-en-real.md` — add to it
whatever you build that only a real host can prove.

- **Lives outside every root**, in `equipo.DIR` (`%LOCALAPPDATA%\prdrive\`,
  `~/.local/share/prdrive/`): `agente/<version>/` (agente.py, penwatch.py,
  common/, ui/ — never install/), `runtime/<stamp_id>/` (its own
  python-build-standalone, extracted by `runtime_bin.extract()`), `agente.json`
  (WHAT: drives, modes, `espera_unidad_nueva`, moderation), `instalacion.json`
  (WHERE: code, python), `agente.lock.json`, `agente.pide`, `estado.json`,
  `agente.log`. **No secret there.** `tests/_harness.py` points `equipo.DIR` at
  a temp dir for every test.
- **One writer per file.** `agente.json` is written by `install/agente.py` the
  first time only; afterwards **only the agent** writes it, and everybody else
  (the wizard re-run, the CLI, later the window) appends a JSON line to the
  mailbox `agente.pide` (`equipo.pedir()`); the agent consumes it by renaming it
  first (`equipo.recoger()`). `instalacion.json` is the installer's.
- **The agent never runs a drive's code before «Atender».** A drive whose id is
  not in `agente.json` gets a notification + a countdown window (`agente.py
  pregunta` → `ui/tk_agente.py`, exit code 0/1/2); the deadline is
  `planificador.Pregunta`, not the window's. No answer / late answer / no
  display = «Ahora no» for THIS connection only (re-armed when the root
  disappears). Only its control file and `state/fleet.json` are read.
  `tests/test_unidad_nueva.py` asserts no launched process carries its paths.
- **It is the drive's service through the drive's own files** (spec section 3),
  so old drives work: it writes `daemon.lock.json` (`"agente": true`), obeys
  `daemon.stop` after the pair in flight (releases, deletes the stop, and
  **pauses** instead of exiting), stays paused while a live `ui.lock.json` of
  this host exists and for `GRACIA` seconds after (so a service started from the
  window has time to write its lock), and **steps aside** while another live
  pid of this host holds the lock. A stale lock (dead pid / other host) is
  overwritten. `runsync.stop_previous_daemon()` says "pauses" when the lock is
  the agent's. `tests/test_agente_contrato.py` drives the real
  `stop_previous_daemon()` against it.
- **Every pass is the root's own `sync.py`**, a child with the agent's Python
  (`pythonw` on Windows), `stdin=DEVNULL` (a pair needing `--resync` is skipped),
  cwd `equipo.DIR`. One pass at a time on the whole host. Nothing stays open in
  a drive between passes. A drive unplugged mid-pass records nothing.
- **`common/planificador.py` is pure** and holds every rule: single queue,
  urgent («Sincronizar ahora») skips all moderation, pause / battery / metered
  hold everything, `intervalo · 2^k` backoff capped at 4 h (never below the
  interval), mode `sync` = infinite interval, offline remotes are PROBED
  (`SONDA`, an `rclone lsd remote:` with `catalog.NET_FLAGS`) instead of
  retried. A `RED` result doesn't count a failure; the agent probes at once and,
  if the remote answers, re-records it as `FALLO` (the classification was
  wrong). Network needles live in `moderacion.ERRORES_DE_RED`, and
  `sync.KNOWN_ERRORS` uses `moderacion.es_de_red` as a **callable needle** —
  one list, because the agent doesn't carry `sync.py`.
- **Notifications only when a pair STARTS failing** (`planificador.empieza_a_fallar`)
  or a remote goes offline — `common/avisos.py` (D-Bus `Notify`; Windows
  `Shell_NotifyIconW` NIF_INFO on a temporary message-only window, **unverified
  on real Windows**). No Tk in the agent process: `tests/test_install_agente.py`
  checks `tkinter` isn't in `sys.modules` after importing it.
- **`common/dbus.py`** cites the *D-Bus Specification* like `ui/qr.py` cites
  ISO/IEC 18004 — keep the citations. Client half only (address, EXTERNAL,
  marshalling, calls, properties, `AddMatch`); exporting objects is the Linux
  tray's phase. `tests/test_dbus.py` pins the canonical `Hello` bytes.
- **Detection** reuses `penwatch.candidate_roots()` (still the one drive walk):
  Linux wakes on `POLLPRI` of `/proc/self/mountinfo` and bursts; Windows bursts
  on the tray window's `WM_DEVICECHANGE` (both then fall back to a 30 s walk),
  and without a tray polls every `penwatch.POLL_SECONDS` like penwatch. Two sightings
  before a drive counts. VeraCrypt vestibules of LISTED drives are opened once
  per connection (`penwatch.open_container(root, cwd=…)`), never for others;
  a disconnection is recorded as «already asked» until a walk shows no vestibule
  («Expulsar» must not bring the password up again).
- **Pairs and interval stay the drive's**: `leer_servicio()` reads the raw TOML
  (not `model.parse_config()`: the drive may be another version) and applies
  `prefs.elegir()` — the pure core of `startup_defaults()`, one rule, not two.
- **Installing** (`install/agente.py`): code and runtime each in a per-version
  dir, swapped with `os.replace`, old ones pruned; imports penwatch's
  `device_id`/`mode` and **uninstalls penwatch** (and says so); registers with
  `penwatch.register_task()` (the task XML is now `penwatch.task_xml()` with the
  command as a parameter) or an XDG autostart (`penwatch.autostart_desktop()`,
  `Exec=` quoted per the Desktop Entry spec) — **not** systemd: notifications,
  the question and VeraCrypt's password need the graphical session.
  Uninstalling removes `equipo.DIR` and never touches a drive.
- **Dependency rules:** the agent imports penwatch, never the reverse; penwatch
  still imports nothing of the project (`test_install_agente.py` walks its AST).
  `agente.py` is in `build_installer.DATOS_FICHEROS` but NOT in
  `deploy.DEPLOY_FILES`: it goes to hosts, not devices.
- **The window's watcher line** (`watch.resumen()`) asks `equipo` first: with an
  agent installed it reports `agente` / `agente_nueva` and offers no button
  (changing the mode from the window is the phase-5 mailbox). The wizard's
  final step offers «Que lo atienda el agente de este equipo» instead of
  installing penwatch.
- **The wizard's first step is «¿Dónde?»** in every route (`PASOS_INSTALACION`,
  both short routes, `PASOS_EQUIPO`, `PASOS_EQUIPO_SOLO`), so «Dispositivo» and
  «Carpeta» keep index 1 and «Atrás» always lands where it says.

### The host root (`install/raiz_equipo.py` + `ui/tk_equipo.py`)

A folder of the host with `.prdrive/` inside is, for the engine, one more device
(`DEVICE_ROOT` is `.prdrive/`'s parent and nothing else). What differs, and must
not be weakened:

- **`tipo=equipo`** is a line of the control file (`device.ensure_control_file(
  tipo=)`, which keeps the id when only the type changes); `model.tipo_raiz()` /
  `es_equipo()` read it, an old penwatch only reads `id=`. The fleet note carries
  `tipo = "equipo"` (drives write no key, so their notes are unchanged) and
  `tk_fleet` labels it.
- **No pair of the whole root, nor one leaving it** (`local = "."`, `..`, an
  absolute path): it would sync `.prdrive/` with the key, and with the home
  folder as root, all of `~`. `model.problema_local_equipo()` is the ONE rule;
  `parse_config(equipo=True)` applies it and `load_config()` passes
  `es_equipo()`. It is a keyword and not read inside `parse_config` because the
  **catalogue** goes through the same function, and there a root pair is legit
  for drives — so `catalog_editor`, `install/remote.py` and `config_file` stay
  as they were, while `pair_editor` (every red-net call), `tk_pairs`,
  `deploy.device_config(equipo=)`, `write_device_config()` (reads the root's
  type) and `device._check_config` pass it. `pair_editor.ruta_local_relativa()`
  also refuses the root when picking it.
- **What the root carries:** code, rclone for THIS host only
  (`raiz_equipo.plan_rclone()`, fetched before writing, #49), connection + key,
  control file. **No runtime, no launchers, no guide**: the agent syncs it with
  its Python, and its window opens from the menu entry «prdrive»
  (`install/agente.poner_menu()`: an XDG `.desktop` on Linux, a Start Menu `.lnk`
  via `IShellLinkW` on Windows — `crear_lnk()` is an indirection point,
  **unverified on real Windows**) that runs `agente.py abrir`.
  `device.verify_device()` skips the launcher and Python rows for such a root;
  the wizard's initialisation passes the agent's console Python to
  `deploy.resync_command(python=)`.
- **Own folder (`~/PRDRIVE`) or home (`~`), chosen once.** `examinar()` refuses
  a relative path, a file, a drive prdrive, anything crossing `equipo.DIR`
  (except home, which always contains it); a root that already is `tipo=equipo`
  is reinstalled keeping its id — the agent lists it by id.
- **Other sync clients** (`carpetas_sincronizadas()`, an indirection point: the
  `OneDrive*` env vars and Dropbox's `info.json`) are an amber warning in both
  directions, never a block. The «Parejas» step shows each pair's resolved path
  and lets its `local` be changed HERE only (`device_config(locales=)`: the pair
  reads as «modificada aquí»).
- **The agent** keeps the root in the same list as drives: `equipo.Unidad.ruta`
  (non-empty = host root; `Ajustes.raices`). `_recorrer()` passes those paths as
  penwatch extra roots, so the walk is still one. A root missing from its path is
  notified ONCE (`Agente.ausentes`) and nothing runs until it is back — never
  searched for or recreated. `PIDE_RAIZ` (`añadir_raiz`) is how a wizard re-run
  with the agent installed adds it; `install.agente.aplicar_unidades(raiz=)`
  writes it directly only when there is no `agente.json`. `candidatas()` never
  offers a root as a drive. Uninstalling never deletes the root, and says where
  it stays.
- **The «Unidades» step** can add the fleet's drives (`raiz_equipo.de_la_flota()`:
  one `rclone copy` of `devices/` to a temp dir, never `cat` of the folder, #48),
  but as `tk_equipo.PREGUNTAR` — not in the list: a drive is never synced without
  a yes.
- `ui/watch.py` reports `agente_raiz` for a window opened on the host root.

### The encrypted host root (phase 3)

With «Una carpeta propia», the wizard's «Cifrado» step (`tk_equipo.paso_cifrado`,
between «Carpeta» and «Conexión», because it fixes `state.device_root` as in a
drive) can put the root in `<carpeta>-cifrado/PRDRIVE.hc`, with only the
vestibule **marker** beside it (`raiz_equipo.marcar()`: same id as the control
file inside; no `.bat`/`.sh`/guide — the agent is the opener). Mounted at a
**fixed letter** on Windows (`equipo.Unidad.ruta` = `P:\`, `Unidad.letra`) or at
the carpeta itself on Linux (`crypto.mount_container(punto_fijo=)`), and
`Unidad.contenedor` holds the `.hc`. Not to weaken:

- **Installed VeraCrypt only** (`raiz_equipo.veracrypt_instalado()` =
  `penwatch.installed_veracrypt()`, one definition for the wizard and the
  agent). No portable, no download, no installer: without it the step says how
  to install it and offers only «Sin cifrar». Inside: NTFS on Windows, exFAT on
  Linux (a fresh ext4 is root's).
- **The password never passes through the agent.** The wizard uses it once to
  create and mount (`raiz_equipo.abrir_o_crear()`) and leaves the container
  open for the agent. From then on `penwatch.veracrypt_command(None, container,
  dest)` has no `/password`, and does carry `/letter` + `/m rm`.
- **Open is SEEN, not assumed**: the id at the letter with the `.hc` held
  (`common/vestibulo.retenido()`, the `:libre` probe; None on POSIX, where the
  mount point decides). Id at the letter beside a free `.hc` is H-10's ghost:
  `Agente._fantasmas()` drops it and says «Bloquear y volver a desbloquear»
  once. `agente.punto_ocupado()` refuses another drive on the letter and a
  mount point with content (it would be hidden) — the agent never picks another
  letter or folder.
- **Locked is not absent**: no notice, no backoff. Only a missing `.hc` is
  notified (once). `pedir_al_iniciar` (default on, `agente.json`, a
  `PIDE_AJUSTE` like `espera_unidad_nueva`) asks ONCE per agent start after
  `ESTABLE` walks; cancelled, not again until `desbloquear`.
- **Bloquear** (`PIDE_BLOQUEAR`, `Agente._bloqueos()`): stop queuing, wait for
  the pair in flight and for the root's window to go (`ESPERA_VENTANA`; the
  window's «Bloquear» asks and closes itself — runsync's window does not listen
  to `daemon.stop`), release the lock, then dismount **without `/silent`**
  (`agente.orden_bloquear()`), so VeraCrypt asks before forcing. Locked =
  `agente.bloqueada()`: `.hc` free and letter gone (Windows), mount point
  unmounted (Linux). VeraCrypt exiting with it still open → «sigue abierta» and
  the root is attended again.
- `ui/cifrado.bloqueo()` turns the window's «Expulsar» into «Bloquear» for such
  a root; `vestibulo.raiz_fisica()` walks `carpetas_de_contenedor()` as extra
  roots, so `espacio` and the leftovers check work unchanged. The fleet note
  adds `cifrado = "veracrypt"` (`fleet._cifrado()`, from `agente.json`).
- Switching a plain root to encrypted leaves the plain tree where it was
  (`raiz_equipo.restos()`: red in the step on Windows, a red row in
  «Verificación»); on Linux the mount point must be empty, so it is refused.
  Uninstalling never closes or deletes the container, and says if it is open.
- A «Desbloquear» in flight is an `agente.Desbloqueo` holding VeraCrypt's
  process: a second one does not launch another password window, and one that
  never shows the root open (VeraCrypt exited `GRACIA_ABRIR` ago, or
  `ESPERA_ABRIR` passed) is forgotten (`_seguir_desbloqueos()`) so it is
  offered again.

### The tray (phase 4: Windows)

Same split as the rest of `ui/`: **`ui/bandeja.py` decides, `ui/bandeja_windows.py`
draws**, and neither imports tkinter (`test_install_agente.py` checks it).

- **`bandeja.vista(resumen)` is pure**: from `Agente.resumen()` (what goes to
  `estado.json`, which gained `equipo` — each host root with its state —
  `pedir_al_iniciar`, and per drive `en_lista`/`ahora_no`/`preguntando`/
  `error`/`fallando`) it returns the icon, the tooltip and the menu tree.
  Every `Entrada` carries **mailbox-shaped requests** (`equipo.PIDE_*`); the
  agent takes them through `Agente.pedir()` → a `queue.SimpleQueue` drained in
  `_buzon()` with the file mailbox, so there is one handler for both. New:
  `PIDE_ABRIR` (the window of a root: `_lanzar_ventana()`, which checks only the
  UI lock — our own service lock is expected and runsync pauses it; a locked
  encrypted root is unlocked first with `abrir=True` and its window opens on
  connect) and `PIDE_DESPERTAR` (back from suspend: re-read battery/network,
  probe every offline remote now, burst the walk).
- **Never «Abrir» for a drive that is not in the list**, even asked by hand:
  that is running its code before the yes. It gets «…, conectada · Atender…».
- **Icon priority** (`bandeja.estado()`): pause > a pass in flight > avisos
  (failing pairs, a root's `error`, offline remotes, a missing root, a ghost) >
  held by battery/metered (pause icon) > an encrypted root locked (not an
  aviso: it is the normal state) > bien. The five `.ico` are
  `icons.capas_bandeja()` — the brand plus a corner badge whose **colour** is
  what reads at 16 px — painted by `copiar_codigo()` and, if missing, by the
  agent on start (`write_bandeja(solo_si_faltan=True)`), never copied.
- **`bandeja_windows.Bandeja`** runs its own thread with its window and message
  loop; the agent talks to it only via `PostMessageW` (`poner()`, `globo()`,
  `cerrar()`), it talks back via `pedir()` and `montajes()` (→
  `Vigia.despertar()`, which on Linux writes a pipe polled beside mountinfo).
  Everything Win32 is in `Api`; `tests/test_bandeja_windows.py` drives the rest
  with a fake one and a real queue-based loop. Not to weaken:
  - **A hidden top-level window, not a message-only one** (the spec said
    message-only): those get no broadcasts, and `WM_DEVICECHANGE` for volumes
    (VeraCrypt's `BroadcastDeviceChange()`) and `TaskbarCreated` are broadcasts.
  - **`arrancar()` succeeds with the window, not the icon**: at logon the
    taskbar may not exist yet, `NIM_ADD` fails, and `TaskbarCreated` adds it
    later (also after an Explorer restart).
  - The menu is `TrackPopupMenu(TPM_RETURNCMD)` after `SetForegroundWindow`,
    with a `WM_NULL` after it, or it does not close when clicking away; `&` in
    names is doubled (`texto_menu()`).
  - Notices hang off the tray icon (`NIM_MODIFY` + `NIF_INFO`) through
    `avisos.GLOBO`; without it, `avisos` falls back to its temporary icon.
- **Walks with a tray**: `cmd_run()` bursts on `WM_DEVICECHANGE` and falls back
  to `RECORRIDO_RESPALDO` (30 s); without one (`poner_bandeja()` → None, an
  indirection point) it keeps penwatch's 5 s. Linux has no tray until phase 6.
- «Cerrar el agente» is `PIDE_PARAR`: the next logon starts it again. Not in the
  spec's list; there is no other way to close a tray icon.

## Conflicts & failures (`conflicts.py`, `results.py`, `ui/conflict_editor.py`)

**Why the suffix carries the side.** With rclone's defaults the loser is
`.conflictN` with the lowest free N (`cmd/bisync/resolve.go`: `resolve`,
`numerate`) — an order, not a side. So `MODES["bisync"]` sets `conflict-suffix =
"conflicto-dispositivo,conflicto-remoto"`: two suffixes → the name says
Path1/Path2 and stays numbered (`pathname` would overwrite an unresolved earlier
copy). `conflicts.esquema()` / `leer_nombre()` replicate `setResolveDefaults` +
`SuffixName` + `SuffixKeepExtension` from the pair's **merged** flags, so a user
override keeps working; legacy `.conflictN` are still found, **without** a side.
Path1 is `pair.source` (local in bisync) — `conflicts.lado()`. Keep the citations.

- **Derived state.** `sync.run_pair()` scans after every non-dry-run bisync pass
  (good or bad) and prints an `AVISO`; `state/conflicts.json` stores only paths
  relative to `DEVICE_ROOT` and `cargar()` re-checks each exists, so the chip
  clears itself.
- **The original's side is inferred** only when there is exactly one copy with a
  known side; `Conflicto.version(lado)` is None when a side has 0 or ≥2 versions
  — never guess. Caveat: a copy made on device A syncs to device B, where it
  still reads «versión de este dispositivo».
- **Resolving is local-only.** `plan_conservar()` keeps one version under the real
  name and deletes the rest; `execute()` refuses if any file changed since the
  plan (size, mtime_ns), then `mover()` (`os.replace`, atomic — failure changes
  nothing), then `borrar()`s. Labels never show the raw suffix.
- **Last run.** `results.apuntar()` from `sync.run_pair()`, not for dry-runs and
  not for SKIPPED (a skip is not a result; the resync chip covers it).
  `results.fallos()` feeds `revision`, which is what the «Reparación» line
  counts; the entry stays until a good pass. `results.ultimas_buenas()` is the
  other half — the date the main window shows — and it survives a failure
  because `apuntar()` keeps the last good stamp in its own key.
- **Pass journal (#20).** `last_run.json` holds one pass per pair, so
  `historial.py` keeps the last `POR_PAREJA = 50` of each in
  `state/historial.jsonl`, one JSON line per pass: `pareja`, `inicio`
  (`store.stamp()`), `codigo`, `segundos`, `transferido` (bytes, or null).
  Written inside `sync.record_result()`, so it follows `results`' rule (no
  dry-run, no SKIPPED) and a call without a `Reloj` — `run_all()`'s `OSError`
  net (#36) — still lands, timed now and without a duration. **Appending is
  the normal write**; the atomic rewrite (`store.write_text`) happens only when
  a pair passes `RECORTE = 2 × N` or the file `TOPE_BYTES`, so the file is
  rewritten at most once per N appends — write cycles are why good logs are
  not kept. `transferido` is
  `progress.final_del_log()`, read from the log's tail **before**
  `dispose_log()` deletes it; file counts are not stored, because with
  `--stats-one-line` `xfr#` appears only while the transfer queue is non-empty
  (`StatsInfo.String()`) and deletes only in the multi-line block. Reading
  skips half-written or foreign lines, and an append after a cut line starts
  on its own. `historial.racha()` is the logic behind the «Reparación» sentence.

## Per-pair versions (`versions = true` + `ui/versions_editor.py`)

A bisync pair with `versions = true` keeps, in `.prversions/` **inside its own
root on each side**, what *that side* loses: overwritten files, deleted ones
(including a delete arriving from the other side) and the loser of a conflict.
Naming is rclone's `--suffix ~%Y%m%d-%H%M%S --suffix-keep-extension`, i.e.
Syncthing's Simple File Versioning — `nota~20260922-093000.md`.

Everything below was **measured against rclone v1.75.1**, not read in its docs.
Preserve the citations like the bisync ones.

- **The exclusion is not filtering, it is the precondition.** rclone refuses a
  `--backup-dir` that overlaps the destination (`destination and parameter to
  --backup-dir mustn't overlap`) and that abort is *critical*: it invalidates the
  baseline. `bisync.filters_content()` therefore emits `- .prversions/**`, and
  emits it **first**, because rclone applies rules in order and the first match
  wins — behind a `+ **/*.md` it would exclude nothing. The consequence is that
  the two folders are **independent histories that never replicate**, which is
  exactly Syncthing's model for `.stversions`.
- **`--backup-dir` must be on the same remote as its side** (`parameter to
  --backup-dir has to be on the same remote as destination`), which is why the
  folder lives inside the pair and not at the device root: no extra `combine`
  upstream, no overlap validation against other pairs, nothing to configure.
- **`--conflict-loser delete` + `--backup-dir` does not delete**: the loser is
  routed through the backup dir. That is what keeps the vault free of
  `<name>.conflicto-remoto1` files, and it is a **deliberate divergence from
  Syncthing**, which leaves its conflict copies in the folder and syncs them.
- **A `--resync` also honours the backup dir**, so the side a resync overwrites
  is recoverable — today it vanishes silently.
- `build_command()` injects the five flags; `conflict-loser` goes in with
  `setdefault` so a `[pair.flags]` still wins. The other four are in
  `flags_editor.RESERVED`. `RunContext.sello` is computed **once per
  invocation**, so everything one pass shelves shares a stamp.
- **`versions` does not move `expected_prefix()`.** `tests/test_versions.py`
  pins it, because that is where a slip costs a baseline.
- **The date comes from the NAME, never the mtime** (`versions_editor.SELLO`):
  copying the folder rewrites mtimes, and the stamp in the name is the whole
  reason the format exists. Purging is «Ajustes» → «Versiones…», both sides in one
  plan through `confirmar_plan()`; the remote side goes out as a single
  `rclone delete --files-from` with the exact list, never an age or a pattern.
  **Restoring is deliberately not offered** (v1).
- Turning it **off** removes the exclusion, so whatever is stored starts syncing
  as ordinary content. `pair_editor._analizar_versiones()` says so as a warning
  before confirming; it is not fixed in code.

## The catalogue (`common/catalog.py` + `ui/catalog_editor.py`)

`nas:/prdrive-catalog/pairs.toml` — same schema as `sync_config.toml`, shared by
every device, read by the installer when provisioning. **A pair is created or
deleted there first**; each device only *chooses* which it uses. Do not collapse
that split: the catalogue side (`plan_catalog_save`/`_remove`/`_defaults`) writes
the remote and changes nothing local; the device side (`plan_enable`/`_remove`/
`_override`/`_revert`) writes `sync_config.toml` and never the remote.
`[defaults]` is catalogue-governed too. No pair is sacred.

`sync_config.toml` holds **complete** pair entries, not references (`sync.py`
must work with no network). Provenance is **derived**, not stored:
`catalog.diff_keys()` compares the local entry against `state/catalog.toml` (the
last successful pull) → `catálogo` / `modificada aquí` / `huérfana` / `sin usar`.
**Do not add a `from_catalog` key** — `config_file.save()` demands strict
round-trip equality and the file is hand-editable.

`catalog.push()` is the riskiest thing in the project: it generates and verifies
the text (`config_file.dumps_checked`), **re-reads the remote and refuses if it
changed**, copies `pairs.toml` → `pairs.toml.bak`, and only then uploads;
rewriting keeps the header block and **loses interleaved comments**.
`catalog.load()` never raises — no network falls back to `state/catalog.toml`,
and a cached catalogue is **not editable** (`Catalog.editable`).
`catalog.NET_FLAGS` keeps a dead remote from freezing the window.

**The path names the file, never its folder (#48).** `rclone cat` of a folder
does not fail: it concatenates every file inside, recursively — `pairs.toml`,
the `.bak`, the `devices/` notes (measured with rclone v1.75.1) — and `tomllib`
answers "Cannot declare ('defaults',) twice". Both readers (`catalog.pull()`,
`remote.pull_catalog()`) therefore ask `catalog.explicar_carpeta()`, which runs
`lsjson --stat` (and, for a folder, `--stat` of its `pairs.toml` to suggest it)
**only when something smells**: the content did not parse, or the path does not
end in `.toml` (which also catches an empty folder and one holding only
`pairs.toml`, both of which `cat` reads with rc 0). Never on the happy path and
never after a failed `cat`: offline, the question would time out too. An
unanswerable `--stat` diagnoses nothing. What is **typed** is refused without
network by `catalog.problema_de_ruta()` — the wizard's Conexión
(`profile.from_form`/`from_rclone_conf`; `with_catalog_path` does not raise,
it runs per keystroke, and `Profile.problema_catalogo` holds the step shut) and
both `[defaults]` forms, only when `catalog_path` **changes**
(`validar_ruta_editada()`): an extension-less path already on a device keeps
working.

An optional **`[remote]`** table carries the non-secret definition of the rclone
remote (type, host, user…): the first device writes it, the rest inherit it via
`profile.align_with_catalog()`. **The catalogue decides the remote's name** —
every `remote_path` resolves against `[defaults].remote`, so a differently-named
remote would fail every sync with "unknown remote". The key never goes there.

## Editing pairs from the UI (`ui/pair_editor.py`) — the dangerous part

`bisync.expected_prefix()` derives from `local`, `remote`, `remote_path`, `mode`.
Change any and the expected listing name changes; reusing the old baseline under
the new name would tell bisync that a listing of the *previous* destination
describes the *new* one, so everything missing from the new side reads as deleted
and propagates, with `--max-delete 25` as the only brake. Hence the plan shelves,
never renames.

- `bisync.shelve_baseline()` renames `state/<pair>/` → `state/<pair>.old-<date>/`,
  leaving the pair `fresh` and forcing an explicit `--resync`. Shelved dirs are
  inert (scans only look at the top level).
- **Renaming a pair is free** — the prefix doesn't depend on the name.
  `bisync.rename_pair_state()` moves `state/<name>/` and `filters/<name>.*`
  together (the `.md5` must travel with its file).
- **The decision compares prefixes, not keys.** `_prefixes(raw)` parses the
  before and after configs and compares `expected_prefix()` per pair;
  `ENDPOINT_KEYS` only produces the human-readable message. That is what makes
  `[defaults]` editable — `remote`/`device_remote` feed *every* pair, so
  `EditPlan.shelve` is a **list**. A prefix that *disappears* (bisync → another
  mode) also shelves.
- `plan_*()` return an `EditPlan` **without touching anything**; its
  `consequences` are shown before confirming. `EditPlan.execute()` does the disk
  surgery **before** writing the config and undoes it if the write fails (it can
  only fail towards "baseline shelved for nothing", which a `--resync` fixes).
  **Rename runs before shelve**, else `filters/<old name>.txt` is orphaned.
- `simular_args(raw, name)` is the whole of «Simular»: `[name, "--dry-run"]`.
  **No `--yes`** — a pair with no baseline must come back "Saltada: requiere
  --resync", precisely what you want to read before approving anything. The
  output window is modal and the screen re-`grab_set()`s afterwards.
- `ruta_local_relativa(path)` turns a directory picked with the system dialog
  into the pair's `local`, relative to `DEVICE_ROOT`, and **refuses** anything
  outside the device (a `../..` local syncs whatever machine it is plugged into).

## The remote folder picker (`ui/remote_picker.py` + `tk_pairs.explorador_remoto`)

«Examinar…» beside `remote_path`. `listar()` is `rclone lsd` through
`catalog.run()`, and `_LINEA` parses its fixed five-field line as a whole regex,
not by splitting on spaces: a folder name with spaces must survive intact, and a
line that is not a listing must not become a folder. `crear()` is the only thing
that writes and it is a `mkdir`. **Deleting remote folders is deliberately not
offered** — the remote belongs to the whole fleet and there is no consequences
ceremony behind this dialog. The button is disabled exactly when the catalogue
block is (`cat.editable`), the proxy for "there is a connection".

## The fleet registry (`common/fleet.py` + `ui/tk_fleet.py`)

`<catalog dir>/devices/<device id>.toml` — one small TOML per device (`id`,
`nombre`, `version`, `plataformas`, `last_seen`, `last_result`, and optionally
`equipos`, `equipos_visto`, `ultima_buena`), the id being the `id=` of
`.prdrive/PRDRIVE`. **Each device rewrites only its own**, so there is nothing
two devices can clobber and therefore no `catalog.push()` ceremony (that
protects a file governing deletions; this is a presence note).

- `fleet.olvidar(quien, raw)` is the **one** exception and deletes a note instead
  of writing one, so a dead device does not sit in the list forever. It destroys
  nothing (the owner republishes next time it is plugged in), so it takes an
  `askokcancel`, not `confirmar_plan()`. **A device cannot forget itself** — that
  guard is in `fleet`, not the window, because it is a property of the operation.
  Unlike `publicar()`/`leer()` it returns the reason it failed.
- `nombre` lives in `state/fleet.json` on the device, not only in the note: it
  must survive with no network, and reading a hostname would rename the device on
  every machine it is plugged into. `deploy` writes it at provisioning and calls
  `fleet.recordar()` so the first pass doesn't repeat it.
- **Published after every real pass, good or bad** (`sync.py main()`, never for
  `--dry-run`): a fleet where everyone says 'ok' cannot show which device has
  been failing for weeks. `hace_falta_publicar()` throttles it, because the
  daemon runs one `sync.py` per pair per cycle.
- `publicar()` and `leer()` **never raise**; a note is not the sync, and
  `parse()` tolerates a half-written or future-version one. Staleness is
  `DIAS_OBSOLETO = 7`; an unreadable date counts as stale.

**Where it has been, and since when it fails (#17).** Everything is computed at
publish time, with **no new write on the device**:

- **`equipos` / `equipos_visto`** are two *parallel* string lists (latest first,
  no repeats, at most `MAX_EQUIPOS = 5`), not a list of tables, because
  `config_file.dumps_table()` writes only scalars and string arrays, and teaching
  it inline tables would touch the serializer behind `sync_config.toml` and the
  catalogue. `nota_de()` inherits the list from `publicado` in that device's
  `state/fleet.json` (`<app_dir>/state/` when given an `app_dir`) **only if its
  `id` matches** (a «Reinstalar desde cero» is another device), puts
  `equipo_actual()` in front with the pass's `store.stamp()`, and leaves the list
  alone when the hostname is empty. `parse()` pairs the lists by position: a
  non-string name is dropped with its date, a missing date is `""`, and it cuts
  to `MAX_EQUIPOS` on read. `_tabla()` is the one dict both `dumps()` and
  `recordar()` write, so the throttle compares against what was published.
- **The hostname is published as is, always, and the window says so** in its
  header. Whoever can read `devices/` holds the remote's key and every synced
  file; a machine's network name is far less. `equipos` means «where it could
  publish from»: a failed publish records nothing, and the retry happens by
  itself on the next pass because the host still differs from the last note's.
- **`ultima_buena`** comes from `results.Fallo.buena` (the pair's `_buena()`),
  read in the **same** `results.fallos()` call as `last_result` —
  `fleet.estado(config)` returns both, so they cannot contradict each other. It
  is the **oldest** `buena` among the failing pairs, or `SIN_BUENA` (`"ninguna"`)
  when any has none. «None that is recorded», not «never»: a pair that never
  succeeded and a record older than the `buena` key look the same.
- **`_sin_fecha()`** adds only the current host (`equipos[0]`) and
  `ultima_buena`: same machine → the 6 h rhythm is unchanged; another machine →
  published on the first pass; `ultima_buena` only moves with `last_result`. A
  `publicado` from before these keys publishes once after updating.
- **The card** (`tk_fleet.ficha()`, pure, no Tk) sits under the table, in the
  same window — a fourth-level modal was the alternative. The table dropped
  «Versión» and «Para» into it. Its space is **reserved for the largest card in
  the fleet** (`reservar()` paints each one and measures; the «Equipos» block
  always holds `MAX_EQUIPOS` lines): the `Visor` fits once, on opening, and
  without that, picking a longer card grew the content and brought up a
  scrollbar that was not there. `test_tk_medidas` walks the whole list to hold
  that.

## The flags editor (`ui/flags_editor.py`)

Flags are written in TOML syntax (a text box, not a row-per-flag form) and parsed
with **`tomllib`, not by hand** — the destination is a `[pair.flags]` table, and
`dump()` renders through `config_file.dumps_table()`, so only what the serializer
can write back is accepted. `RESERVED` rejects the flags `sync.py` supplies per
run and the filter ones — a second `--workdir` or `--filters-file` points bisync
at the wrong baseline. `effective()` resolves the four layers into what rclone
would actually receive; `warnings()` compares **merged** flag sets, never one
layer, so it catches `--max-delete` rising because the pair's own value was
deleted or the mode changed. Editing flags never shelves a baseline.
`tk_pairs.flags_form()` does **not** close on invalid input, and
`pair_editor.merge_form()` (shared with `catalog_editor`) makes an emptied box
delete the key.

## Writing the TOML (`common/config_file.py`)

`tomllib` only reads and the project takes no dependencies, so the serializer is
hand-rolled: scalars, string arrays and one nested `flags` table. Two things to
preserve: `[pair.flags]` binds to the **last** `[[pair]]` written, so it is
emitted right after its own pair; and `dumps_checked()` re-parses what it
generated and refuses to write if the dict does not reproduce. `save()` and
`catalog.push()` both go through it. Work on the **raw dict**, never
`model.Config` (its `Pair`s arrive with `[defaults]` merged). `save(head=None)`
keeps the target's existing header.

## Conventions

- All comments, docstrings and user-facing output are **Spanish**. Keep it so.
- Comments explain *why* against rclone's actual behaviour, often citing the
  rclone source file. Preserve that when touching bisync-related code.
- `sync_config.toml` is per-device: generated from the catalogue at provisioning,
  then maintained by the pairs screen. Still hand-editable — a pair that differs
  from the catalogue is *reported* as "modificada aquí", not corrected.
- Everything that touches the network, a real device or the desktop is a
  **module-level indirection point so every test can replace it**: `catalog.run()`
  (which `fleet` and `remote_picker` go through), `update.fetch()`,
  `rclone_bin.fetch()` / `runtime_bin.fetch()`, `descarga.esperar()`,
  `veracrypt_bin.fetch()` / `ensure_veracrypt()`,
  `conflicts.recorrer()`, `conflict_editor.mover()` /
  `borrar()`, `ui.abrir()`, `runsync.notificar_fallo()`,
  `components.rclone_en_uso()` / `runtime_en_uso()` / `veracrypt_en_uso()`,
  `common.components.raiz_fisica()`, `traveler.espacio_libre()`, `_win_volumes()`,
  `vestibulo.raiz_fisica()`, `cifrado.lanzar_expulsion()`,
  `crypto.sistema_de_ficheros()`, `crypto.bytes_escritos()`,
  `_leer_estado_bitlocker()`, `_preguntar_borrado()`, `pairing.construir()`,
  `watch.resumen()`, `tk.mostrar()` / `confirmar_plan()`, and for the agent
  `agente.lanzar()` / `hay_pantalla()` / `avisar()` / `abrir_contenedor()` /
  `diario()`, `avisos.enviar()`, `moderacion.energia()` / `red_medida()`,
  `install.agente.conseguir_runtime()` / `lanzar()` / `autostart_file()` /
  `acceso_menu()` / `crear_lnk()`, `raiz_equipo.carpetas_sincronizadas()` /
  `veracrypt_instalado()` / `abrir_o_crear()`, `penwatch.installed_veracrypt()`,
  `vestibulo.retenido()`, `cifrado.pedir_bloqueo()`, `agente.poner_bandeja()`, the tray's
  `bandeja_windows.Api`, and `equipo.DIR`. Keep new ones in that shape.

## Documentation

- **`README.md`** — the front door of a public repo and the thorough one.
- **`device-readme.md`** — the *light* quick guide, **not** for repo readers: the
  installer copies it to the volume root as `README.md` (`deploy.write_guide()`,
  best-effort). Keep it short, task-shaped, free of internals; it is in
  `DATOS_FICHEROS`, so a build that forgets it fails at compile time.
- **`sync_config.example.toml`** — the schema reference for both
  `sync_config.toml` and the remote's `pairs.toml` (which also takes `[remote]`).
- **`LICENSE`** — Apache 2.0 verbatim; README's «Licencia» section points at it.
- **`.github/pull_request_template.md`** — what every PR answers, agents' included:
  where it touches, which data is at stake, what happens to devices already in
  use, and how it was checked (no CI runs the tests). **A PR title is release
  text**: the release workflow uses `--generate-notes`, and `tk_update` shows
  those notes on every device — write it in Spanish, for the device's user.

## Agent skills

- **Issue tracker** — GitHub Issues (`Jeremaya25/prdrive`) via the `gh` CLI. See
  `docs/agents/issue-tracker.md`.
- **Triage labels** — five canonical labels, each string equal to its role name.
  See `docs/agents/triage-labels.md`.
- **Domain docs** — single-context: one `CONTEXT.md` + `docs/adr/` at the repo
  root, created lazily. See `docs/agents/domain.md`.
