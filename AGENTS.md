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
launchers and the watcher locate them by fixed path), `prdrive-install.py` (what
gets compiled and handed out) and `build_installer.py`.

```
prdrive/               (the checkout; on a provisioned device it is `.prdrive/`)
├── sync.py            engine: build the rclone command, run it, report
├── runsync.py         the periodic service + who calls what
├── penwatch.py        mount watcher (deliberately self-contained)
├── VERSION            the version, in ONE place; ships to the device
├── common/            the config and rclone
│   ├── model.py       sync_config.toml parsed into resolved objects
│   ├── bisync.py      replicates rclone bisync's internals
│   ├── conflicts.py   conflict files: scan, side, state/conflicts.json
│   ├── results.py     each pair's last run (state/last_run.json)
│   ├── progress.py    rclone stats lines → the live progress line
│   ├── config_file.py reads AND writes the TOML (hand-rolled serializer)
│   ├── catalog.py     the pair catalogue on the remote: read, cache, write
│   ├── fleet.py       one note per device beside the catalogue
│   ├── update.py      is there a newer release, and how to fetch its code
│   ├── components.py  rclone/Python carried vs the pins — stamps, no network
│   ├── pins.py        pinned rclone + python-build-standalone; platform table
│   └── store.py       device JSON state + pid_alive(); atomic writes
├── ui/                asking the user, showing results
│   ├── __init__.py    Choice, Frontend, start(), fatal(), manual_args(), abrir()
│   ├── theme.py       palette, fonts, ttk styles — no window
│   ├── icons.py       icons rasterised here: no deps, no emoji
│   ├── prefs.py       what the UI preloads (state/ui_prefs.json)
│   ├── pair_editor.py what THIS device does with pairs — the decisions
│   ├── catalog_editor.py · remote_picker.py · conflict_editor.py ·
│   │   flags_editor.py · watch.py     the other decision halves, no Tk
│   ├── tk.py          TkFrontend: main + output window, modal()/mostrar()/working()
│   ├── tk_install.py  the install wizard          (every tk_* draws only)
│   ├── tk_pairs.py · tk_conflicts.py · tk_fleet.py · tk_watch.py ·
│   │   tk_update.py · tk_crypto.py
│   └── console.py     ConsoleFrontend: the text menu
├── install/           what the installer knows; no Tk, no device needed
│   ├── __init__.py    brand constants, InstallError, InstallState, python_command()
│   ├── profile.py     the connection: where it comes from, how it is written
│   ├── rclone_bin.py  get an rclone (any platform's), verified
│   ├── runtime_bin.py get a python-build-standalone runtime, verified; extract
│   ├── platforms.py   host, what the device carries, the step-5 Matriz/Plan
│   ├── components.py  fetch the pinned component, swap it in
│   ├── remote.py      the ephemeral rclone.conf and the pair catalogue
│   ├── device.py      what volumes exist, which is the device, mounted right?
│   ├── crypto.py      VeraCrypt and BitLocker
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
(`tests/test_penwatch_runtime.py`).

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
python runsync.py --auto       # periodic service with [daemon] defaults, no UI
python runsync.py --doctor     # any other args pass straight through to sync.py

python penwatch.py install|status|probe|uninstall   # the watcher, per machine/user

python prdrive-install.py          # install wizard for a NEW device (Tk only)
python prdrive-install.py --check  # rclone + connection + catalogue, then exit
python prdrive-install.py --probe  # what drives it sees, then exit
python prdrive-install.py --update E:\             # the device's code only
python prdrive-install.py --update-components E:\  # its rclone + runtime only
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
- `max-delete` defaults: 25 bisync / 50 mirror.
- rclone always runs with `cwd = model.APP_DIR`: `rclone.conf` uses paths
  relative to it (`key_file`, `known_hosts_file`).
- Any `*-mirror` pair deletes on the far side — never exercise one without
  `--dry-run` first. No pair mirrors the whole device.

### Logs and live progress

rclone writes to a temp file; `dispose_log()` keeps it in `logs/` only when the
run failed (or `--keep-logs` / `keep_logs = true`), to spare device write cycles.
On failure the tail is printed and `KNOWN_ERRORS` maps rclone messages to an
explanation — add new cases there.

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
`ui_prefs.json`, plus `last_run.json` and `conflicts.json` (written by `sync.py`,
not the daemon). `startup_defaults()` layers last choice > `[daemon]` in the TOML
> all pairs / 30 min; only the UI writes prefs (`manual`/`daemon`, not `doctor`),
`--auto`/`--daemon` only read. The service stops when the device disappears
(`SENTINEL`) or when runsync is launched again.

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
- **The main window runs syncs itself:** «Sincronizar ahora» and «Doctor» open a
  modeless `output_window`, the window disables whatever touches the same state,
  and on close re-reads `state/` and repaints. Only «Iniciar servicio» returns a
  `Choice` to runsync. `ui.manual_args()` (resync question + `--yes`) is shared
  with the console path. The pairs screen's «Simular», «Examinar…» and
  «Dispositivos…» write nothing, so none makes `open_dialog` return True.
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
  change. `tests/test_tk_medidas.py` checks every screen against a matrix of
  resolution **and** `tk scaling` — the scaling column is the half that matters.
- `tk.working(parent, title, funcion)` runs `funcion()` on a thread behind a bare
  progress bar, for slow or passphrase-carrying commands. No cancel button.

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
- `deploy.install_runtime()` extracts beside and **swaps**; if the old dir can't
  be moved aside (Windows: a `pythonw.exe` running from it) it fails whole and
  the old runtime stays. `remove_platform()` renames before deleting for the same
  reason. **No self-built executables, no `.vbs`.**
- The `.bat` avoids parenthesised blocks (a `)` in the device path would break
  them), is written with CRLF, and uses `chcp 65001` only in the error branch.
- **Launchers are immutable after provisioning**: written by step 5 and by
  «Añadir plataformas…» (an old device has no `.bat`, so its runtimes would be
  useless), **never** by `--update`, «Actualización» or `deploy_code()`
  (`tests/test_install_deploy.py` guards it).

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
  postponed with its reason (`rclone_en_uso` / `runtime_en_uso`).

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
  device disappears. `--mode`: `ui` (default), `sync`, `daemon`.
- It must never write to, or `chdir` into, the device (that blocks safe
  ejection); config, state and log live on the host, and every device access is
  wrapped in `try/except OSError` (a locked BitLocker volume errors rather than
  reporting "not found").
- `ui/watch.py` imports penwatch for reads and shells out for
  `install`/`uninstall`. One-way dependency.
- **Its own Python**: `install` copies the device's runtime for this host
  (`runtime_keys_for()` chain) into `HOST_DIR/runtime/<stamp_id>/` and points
  `watch.json` and the task/unit at it, because `sys.executable` silently died
  when the user upgraded Python. **One dir per version, never swapped in place**
  (on Windows you cannot rename the dir of a running `pythonw.exe`):
  `refresh_runtime()` copies beside, rewrites the pointer atomically,
  re-`register()`s, and `prune_runtimes()` keeps `python_exe`'s, `task_python`'s
  and the running process's dirs. No device runtime for this host → host Python,
  never one living on the device.

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
  `results.fallos()` feeds the amber banner, which stays until a good pass.

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
`nombre`, `version`, `plataformas`, `last_seen`, `last_result`), the id being the
`id=` of `.prdrive/PRDRIVE`. **Each device rewrites only its own**, so there is
nothing two devices can clobber and therefore no `catalog.push()` ceremony (that
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
  `rclone_bin.fetch()`, `conflicts.recorrer()`, `conflict_editor.mover()` /
  `borrar()`, `ui.abrir()`, `runsync.notificar_fallo()`,
  `components.rclone_en_uso()` / `runtime_en_uso()`, `_win_volumes()`,
  `_leer_estado_bitlocker()`, `_preguntar_borrado()`, `tk.mostrar()` /
  `confirmar_plan()`. Keep new ones in that shape.

## Documentation

- **`README.md`** — the front door of a public repo and the thorough one.
- **`device-readme.md`** — the *light* quick guide, **not** for repo readers: the
  installer copies it to the volume root as `README.md` (`deploy.write_guide()`,
  best-effort). Keep it short, task-shaped, free of internals; it is in
  `DATOS_FICHEROS`, so a build that forgets it fails at compile time.
- **`sync_config.example.toml`** — the schema reference for both
  `sync_config.toml` and the remote's `pairs.toml` (which also takes `[remote]`).
- **`LICENSE`** — Apache 2.0 verbatim; README's «Licencia» section points at it.

## Agent skills

- **Issue tracker** — GitHub Issues (`Jeremaya25/prdrive`) via the `gh` CLI. See
  `docs/agents/issue-tracker.md`.
- **Triage labels** — five canonical labels, each string equal to its role name.
  See `docs/agents/triage-labels.md`.
- **Domain docs** — single-context: one `CONTEXT.md` + `docs/adr/` at the repo
  root, created lazily. See `docs/agents/domain.md`.
