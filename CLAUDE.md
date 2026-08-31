# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this is

**prdrive**: portable two-way sync between *any* rclone remote and a removable
drive, driven by a bundled `rclone` binary. Pure Python **stdlib**, 3.11+
(`tomllib`). No build, no dependencies, no package manifest. Tests are plain
scripts under `tests/` — no framework, nothing touches a real device or the
network.

The code knows **no server**: everything about the connection lives in a
`profile.Profile` the wizard asks for, imports from the user's `rclone.conf`, or
carries embedded in the compiled `.exe`. The remote stores **configuration
only** — the catalogue of pairs — never the program.

## Layout

Four entry points at the repo root: `sync.py`, `runsync.py`, `penwatch.py`,
`prdrive-install.py`. The first three because volume-root launchers
(`runsync.pyw` / `runsync.sh`) and `penwatch.py` locate them by fixed path;
`prdrive-install.py` because it is what gets compiled and handed out.

```
prdrive/               (the checkout; on a provisioned device it is `.prdrive/`)
├── sync.py            entry point: build the rclone command, run it, report
├── runsync.py         entry point: the periodic service + who calls what
├── penwatch.py        entry point: mount watcher (deliberately self-contained)
├── VERSION            the version, in ONE place; it ships to the device
├── common/            knows the config and rclone
│   ├── model.py       sync_config.toml parsed into resolved objects
│   ├── bisync.py      everything that replicates rclone bisync's internals
│   ├── config_file.py reads AND writes sync_config.toml (hand-rolled serializer)
│   ├── catalog.py     the global pair catalogue on the remote: read, cache, write
│   ├── update.py      is there a newer release, and how to fetch its code — no Tk
│   └── store.py       device JSON state files + pid_alive(); tolerant reads, atomic writes
├── ui/                knows how to ask the user and show results
│   ├── __init__.py    Choice, the Frontend protocol, start(), fatal()
│   ├── theme.py       the visual system in ttk: palette, fonts, styles — no window
│   ├── icons.py       the icons, rasterised here: no deps, no emoji
│   ├── prefs.py       what the UI starts preloaded with (state/ui_prefs.json)
│   ├── pair_editor.py what THIS device does with pairs — the decisions, no Tk
│   ├── catalog_editor.py  add/edit/remove in the remote catalogue — no Tk
│   ├── flags_editor.py    rclone flags: text <-> table, layers, warnings — no Tk
│   ├── watch.py       adapter over penwatch.py — no Tk
│   ├── tk.py          TkFrontend: main window, output window, modal()/mostrar()/working()
│   ├── tk_pairs.py    the pairs screen + the flags dialog (drawing only)
│   ├── tk_watch.py    the auto-start screen (drawing only)
│   ├── tk_install.py  the install wizard, step by step (drawing only)
│   ├── tk_crypto.py   the wizard's encryption step: VeraCrypt/BitLocker (drawing only)
│   ├── tk_update.py   the «there's a new version» screen (drawing only)
│   └── console.py     ConsoleFrontend: the text menu
├── install/           what the installer knows; no Tk, no device needed
│   ├── __init__.py    brand constants, InstallError, InstallState, python_command()
│   ├── profile.py     the connection: where it comes from and how it is written
│   ├── rclone_bin.py  get hold of an rclone to start with
│   ├── remote.py      the ephemeral rclone.conf and the pair catalogue
│   ├── device.py      what volumes exist, which one is the device, was it mounted right
│   ├── crypto.py      VeraCrypt and BitLocker
│   └── deploy.py      copy the code in, write the device's config, --resync
└── tests/             plain scripts; run_all.py runs them in separate processes
```

**Dependency rules — do not cross them:**

- `tk_*` modules only draw. Every decision and disk touch lives in
  `pair_editor` / `catalog_editor` / `flags_editor` / `watch` / `install/`,
  which import no Tk and are tested headlessly.
- `theme.py` / `icons.py` own every colour, font and glyph; a `tk_*` module
  never writes a hex value of its own.
- `penwatch.py` imports **neither** package: it is copied to the host and must
  keep working with the device unplugged.
- `install/` **does** import `common/` (`model.BASE_FLAGS`,
  `model.flags_to_args`, `config_file.save`, `store.pid_alive`) — what the
  installer writes must be byte-for-byte what `sync.py` later reads. It must
  **not** import `ui/` outside `tk_install`, and must work with **no device
  anywhere**.
- `prdrive-install.py` is a launcher (arguments in, `ui/tk_install.py` out). The
  one exception is `--update`, which does its work inline with no window: it is
  the self-update applier, run from the *downloaded* copy of the project.

**On a provisioned device** the code lives in `.prdrive/` at the volume root
(the leading dot hides it on POSIX; `deploy.hide()` sets the hidden attribute on
Windows). `model.APP_DIR` is `Path(__file__).parent.parent` and `DEVICE_ROOT`
its parent, so **nothing depends on the folder name or drive letter** — a
development checkout named anything works the same. Constants that must not
drift, guarded by `tests/test_install_device.py`: `deploy.APP_SUBDIR` and the
two copies each of `STRUCT_MARKER` and `CONTROL_FILE` (`.prdrive/PRDRIVE`) in
`penwatch.py` / `install/device.py`. The control file sits **inside** that
folder: identifying the drive only needs a path relative to its root, and inside
it cannot be deleted without deleting the program.

`design/` holds the UI redesign mock-ups (`.dc.html` artboards) that `ui/`
implements. They are the record of what was decided, not code — nothing imports
or generates them. `Sistema.dc.html` is the sheet `ui/theme.py` translates.

## The PyInstaller build (`build_installer.py`)

It does **two** things: packs the tree the installer will deploy (`sync.py`,
`runsync.py`, `penwatch.py`, `common/`, `ui/` as `--add-data`), and optionally
embeds a connection profile with its private key.

- `common/` and `ui/` end up in the bundle **twice** — as importable bytecode
  (the installer uses them) and as copyable source (what lands on the device).
  PyInstaller cannot hand back the `.py` source of a module it imported.
- **Without a profile** (the normal case for a clone) the binary is generic,
  carries no secret, and asks for the connection in step 1. **With one**
  (`prdrive-profile.toml` + `keys/` in the checkout) it is turnkey and must only
  be shared privately. This split is what lets the repo be public:
  `install/secret.py` is generated at build time, gitignored, deleted in a
  `finally`.

**Traps that only show up frozen:** `sys.executable` is the installer, not
Python (`install.python_command()`); `sys.stdout` can be None with `--windowed`
(`report()` opens a window when there is no console).

**Windows on ARM** — what `model.maquina_nativa_windows()` exists for. rclone
lives in `bin/<arch>/`, chosen by `model.arch_dir()`. The installer is an x64
`.exe`, and Windows lies to an emulated x64 process about the hardware:
`platform.machine()`, `PROCESSOR_ARCHITECTURE`, `GetNativeSystemInfo()` all
answer `AMD64` on a Snapdragon; `PROCESSOR_ARCHITEW6432` is only set for 32-bit
processes. Only `IsWow64Process2()` tells the truth, and `arch_dir()`,
`rclone_bin.os_arch()` / `cache_dir()` all hang off that one answer. It matters
because the two sides do not run the same Python — the installer wrote rclone to
`bin/x64`, the device's native ARM64 `runsync.py` looked in `bin/arm`. The
download cache is per-arch; `BIN_FALLBACK_DIRS` lets an ARM64 host fall back to
`bin/x64` (not symmetric — emulated x64 runs, ARM on x64 does not). Resolved on
the **host**, never stored on the device. `tests/test_arch.py` fakes the probe.

## Commands

```bash
python sync.py                 # sync every pair in sync_config.toml
python sync.py obsidian        # only these pairs
python sync.py --list          # pairs + resolved endpoints (safe, read-only)
python sync.py --doctor        # bisync state diagnosis: prefixes, filters, locks
python sync.py --dry-run       # simulate; MANDATORY before any *-mirror run
python sync.py --resync        # rebuild the bisync baseline
python sync.py -y/--yes        # auto-approve the resync question (cron/scripts)
python sync.py --keep-logs     # keep logs of successful runs too

python runsync.py              # UI (Tk, console fallback) + periodic service
python runsync.py --auto       # start the periodic service with [daemon] defaults, no UI
python runsync.py --doctor     # any other args pass straight through to sync.py

python penwatch.py install     # register the mount watcher on THIS machine/user
python penwatch.py status      # what is registered + whether the device is visible now
python penwatch.py probe       # detection only: candidate roots and what matched
python penwatch.py uninstall

python prdrive-install.py          # install wizard for a NEW device (Tk only, no console menu)
python prdrive-install.py --check  # rclone + connection + catalogue, then exit
python prdrive-install.py --probe  # what drives it sees, then exit
python prdrive-install.py --update E:\   # replace the code of an installed device
python build_installer.py          # build the .exe (embeds the profile if there is one)
python -m ui.icons                 # repaint APP_DIR/runsync.ico (no Tk, no display)

python tests/run_all.py            # all tests (loose scripts, no framework)
python tests/test_pair_editor.py   # or just one
```

- `runsync.py` with no args always **stops a previously started service** first.
- Verification is `tests/run_all.py`, `--doctor`, `--dry-run`. Nothing to lint.
- Git: this checkout sits on an exFAT/NTFS volume, so git refuses it as "dubious
  ownership" — prefix commands with `-c safe.directory=F:/rclone-sync`.
- `.gitignore` excludes device/user-specific paths (`bin/`, `keys/`, `filters/`,
  `logs/`, `state/`, `sync_config.toml`, `rclone.conf`, `prdrive-profile.toml`),
  build artefacts (`build/`, `dist/`, `*.spec`), and `install/secret.py`.
  **Nothing on the device travels to the remote** — no pair mirrors `.prdrive/`.

## Architecture

`sync.py` is the engine. `runsync.py` never imports it — it reads config via
`common.model` and shells out to `model.SYNC_PY <pair>` per pair, so the two
never share in-process state.

**Parse once, at the boundary.** `model.parse_config()` turns the TOML into
frozen value objects; nothing downstream re-reads TOML keys or repeats
`.get(key, default)`, and `defaults` stops being threaded through signatures
because every layer it contributes is already merged.

- `Mode` — one entry per mode in `MODES`: the rclone subcommand, which end is
  source/dest, that mode's default flags. Adding a mode = one `Mode(...)`.
- `Pair` — a `[[pair]]` fully resolved: `includes`/`excludes`, merged `flags`,
  `extra_flags`, endpoint properties (`source`, `dest`, `local_abs`, `workdir`…).
- `Config` — pairs plus `[daemon]`, `keep_logs`, `device_remote`; `select()`
  (aborts on unknown names), `pen_environment()`.

An invalid `mode` is rejected at parse time, so a typo stops
`--list`/`--doctor`/a run alike. Validation raises **`model.ConfigError`**, not
`sys.exit` — the UI shares this model and killing the process would close the
window in the user's face. CLI entry points catch it and exit with its message.
The only surviving `sys.exit`s in `model.py` are the `tomllib` import and the
missing rclone binary.

**Config → command.** Flags merge last-wins: `BASE_FLAGS` < `Mode.flags` <
`[defaults.flags]` < `[pair.flags]`, all inside `model._build_pair` so
`Pair.flags` arrives ready. `build_command()` adds only what depends on *this*
run. `model.flags_to_args()` turns `key = value` into `--key value` (`true` →
bare flag, `false`/`None` → dropped, list → repeated flag, `_` → `-`); it lives
in `model.py` so the UI can show what a flag becomes without importing the
engine. **Adding an rclone flag means editing the TOML, never the code.** The
script owns `--config`, `--log-file`, `--dry-run`, `--workdir`, `--resync`;
`extra_flags` is the raw-string escape hatch.

**`RunContext`** carries what does not change between pairs in one invocation
(binary, env, `dry_run`, `force_resync`, `resync_approved`, `keep_logs`).

### bisync (`common/bisync.py`)

The one place that imitates rclone's own behaviour; each section cites the
rclone source file it mirrors. Preserve those citations.

- **Session prefix.** bisync names its listings after the two endpoint strings.
  `canonical_path` / `session_name` / `expected_prefix` replicate
  `cmd/bisync/bilib/canonical.go` so the script knows the filename rclone will
  look for **before** running. `normalize_prefix()` renames an existing listing
  set when it no longer matches (device mounted `E:` instead of `F:`);
  `heal_listings()` parses `Tip: Path1/Path2` out of a failed log and retries
  **once**. Current state files are `F__sync-data_...` — drive-letter bound.
- **`device_remote`.** `device_remote = "device"` in `[defaults]` makes the
  device side a `combine` remote via `RCLONE_CONFIG_<NAME>_TYPE/_UPSTREAMS` env
  vars (`Config.pen_environment()`, computed from **all** pairs), making the
  prefix machine-independent. An `alias` remote does *not* work. Not currently
  enabled.
- **Filters.** For `bisync` only (`Pair.wants_filters_file`), `filters_file_for()`
  generates `filters/<pair>.txt` and passes `--filters-file`; `--include`/
  `--exclude` are then **not** also emitted (duplicate rules break change
  detection). bisync stores the md5 beside the file and rewrites it only during
  `--resync`, so `filters_state()` compares the hash itself and reports "needs
  resync".
- **State.** One workdir per pair, `Pair.workdir` → `state/<pair>/`;
  `migrate_legacy_state()` moves the old flat layout. `pair_state()` returns a
  `PairState(status, detail, prefix)` — `fresh|ok|broken` read from the actual
  `.lst` files. `resync_reasons(pair, state=None)` returns the reasons this pair
  needs a `--resync` (`[]` for non-bisync pairs — the mode guard is inside it).
  `last_run(pair)` is the mtime of the newest listing, which **is** the last
  good pass (bisync rewrites both listings on success); non-bisync pairs get
  None and the window shows a dash. `ui.pair_times()` returns raw timestamps.
- **Resync approval.** `resolve_resync_approval()` asks **once** for all pairs
  before anything runs. `ask_yes_no()` returns the default when stdin is not a
  tty, so non-interactive runs skip those pairs (`SKIPPED = -1`) rather than
  resyncing unattended.

### Safety invariants — do not weaken

- If a bisync baseline exists but the local path does **not**,
  `_bisync_preflight()` aborts with rc 2 instead of creating the folder (an
  empty local side reads as "everything was deleted"). Only pairs **without** a
  baseline get their local dir created.
- `max-delete` defaults: 25 bisync / 50 mirror.
- rclone always runs with `cwd = model.APP_DIR` (`.prdrive/`, not the package
  dir) because `rclone.conf` uses paths relative to it (`key_file`,
  `known_hosts_file`).
- Any `*-mirror` pair deletes on the far side — never exercise one without
  `--dry-run` first. No pair mirrors the whole device any more.

### Logs

rclone writes to a temp file; `dispose_log()` keeps it in `logs/` only when the
run failed (or `--keep-logs` / `keep_logs = true`), to spare device write
cycles. On failure the tail is printed and `KNOWN_ERRORS` maps rclone messages
to an explanation — add new cases there.

- `--log-file` only catches what rclone logs **after** it installs the log, so
  `execute()` captures rclone's `stdout`+`stderr` and `append_output()` appends
  it under `DIRECT_OUTPUT_HEADER`. Without it, startup failures (a bad flag, a
  value rclone rejects) left a 0-byte log with nothing to explain. Captured, not
  inherited, because with no console behind it (pythonw, the service) inherited
  output goes nowhere.
- `strip_usage()` drops the 12 KB help dump rclone prints after a bad flag: it
  buries the real message and mentions `--max-delete` / `lock file`, so
  `explain_failure()` matched a `KNOWN_ERRORS` needle inside rclone's own
  documentation and explained a failure that never happened. **A false diagnosis
  is worse than none.** The two flag entries in `KNOWN_ERRORS` go **last**.

### Daemon (`runsync.py`)

Coordination lives in `state/` so it travels with the device:
`daemon.lock.json` (pid/host/pairs/cycle, atomic), `daemon.stop` (presence =
stop request), `daemon.log` (self-trimming), `ui_prefs.json`.
`startup_defaults()` layers memory over `daemon_defaults()`: last choice >
`[daemon]` in the TOML > all pairs / 30 min. Only the UI writes prefs
(`save_prefs()` for `manual`/`daemon`, not `doctor`); `--auto`/`--daemon` only
read. `store.read_json`/`write_json` are the shared primitives; `store.pid_alive()`
sits beside them.

The service stops when the device disappears (`SENTINEL` check) or when runsync
is launched again. **Windows specifics to preserve:** `pid_alive()` uses
`OpenProcess`, never `os.kill` (which *terminates* on Windows); the daemon is
spawned with `pythonw.exe` + `CREATE_NO_WINDOW`, rclone with `CREATE_NO_WINDOW`
too (else every invocation flashes a console); the daemon `chdir`s to the temp
dir so the device can be ejected. Child `sync.py` runs get `stdin=DEVNULL`, so a
pair needing `--resync` is skipped rather than resynced unattended.

## UI (`ui/`)

Two frontends implement the same four operations (`ask`, `approve_resync`,
`info`, `run_sync`). `ui.start(config, msg)` returns the choice **together with
the frontend that took it** — a window cannot dump output to a console that does
not exist, and vice versa. Both return `Choice(action, pairs, minutes)`.

- `output_window` colours each line by content (`tk._tono`) using the vocabulary
  `sync.py` already prints (`=== pair ===`, `  ejecutando:`, `[pair] OK.`,
  `[pair] FALLÓ`, `Hecho. n/m parejas OK…`). Change the wording there and a line
  stops being coloured; nothing breaks. It offers **Guardar el log** — the only
  copy of a successful pass.
- `tk_pairs.confirmar_plan()` is a real window, one line per consequence, each
  warning in an amber box — not an `askokcancel`. This is the dialog that
  governs deletions. Tests replace it, like `mostrar()`.
- `ConsoleFrontend.approve_resync` always returns False on purpose: with a real
  terminal `sync.py` inherits stdin and asks the question itself, with more
  context than a dialog fits.
- **`import tkinter` always goes inside functions, never at module top.** `ui/`
  is imported by headless paths (`--auto`, the service) where tkinter may be
  absent; the failure must surface when the window opens so `ui.start()` can
  fall back to the console menu.
- `save_prefs` stores `known` (the pair names that existed then) so a pair added
  later reads as new and comes back checked; it skips the write when nothing
  changed; a record whose pairs are all gone falls back to the TOML silently.

### Theme & icons (`ui/theme.py` + `ui/icons.py`, nowhere else)

Implements `design/`; `Sistema.dc.html` is the sheet: warm paper, near-black
ink, one blue accent, amber for warnings, monospace for paths and flags; no
rounded corners and no shadows (ttk cannot draw them).

- **`theme.nitidez()` runs before the first `Tk()`** and declares DPI awareness.
  Without it a dense screen is misreported (4K at 200 % → 1472×920 at 96 ppp),
  Tk draws at that size and the compositor stretches the bitmap — that stretch
  is the blur, and no font work fixes it. **System** awareness, not per-monitor
  (Tk 8.6 doesn't handle `WM_DPICHANGED`). Called from all five places that open
  a root.
- **Design distances go through `theme.medida()`, never a bare integer** — Tk
  takes a plain number as pixels, unscaled, so `wraplength=760` is half as wide
  on a dense screen. `icons.px()` returns an int for what Tk cannot scale at all
  (bitmaps) and what only takes an int (`rowheight`).
  `tests/test_tk_densidad.py` fails if a bare-pixel `wraplength`/`rowheight`
  reappears in `ui/`.
- `theme.apply(widget)` switches to **clam** (the only bundled theme that lets
  you set each border colour) and repaints. Runs **once per Tk interpreter**.
- Styles cross **role** (normal, hint, eyebrow, mono…) with **surface** (paper,
  card, grey strip, amber block), because a `ttk.Label` does not inherit its
  parent's background.
- `icons.py` rasterises the glyphs itself: no dependencies, Tk cannot read SVG,
  the design says «no emoji». Each icon is primitives on a 16-grid; the
  rasteriser measures per-pixel distance to the nearest ink (free antialiasing).
  `_rasterizar()` composes against the background (`PhotoImage.put()` has no
  alpha); `_capas_rgba()` keeps the alpha for the `.ico`. `icons.get()` returns
  None on any failure and the caller keeps its text.
- `_expandir()` does square caps / miter joins **once per layer**: moves free
  ends out by half the stroke and drops a quadrilateral wedge into each corner
  (without it the app icon's right-angle arrowheads render as lozenges).
- `write_ico()` paints `runsync.ico` (shortcut, taskbar and installer-`.exe`
  icon, which `iconphoto()` cannot reach). Tk-free, runs headless. Sizes ≤ 64 go
  in as DIBs, 128/256 as PNG (`zlib` is stdlib). Written into `.prdrive/` and
  **repainted**, not copied — same glyph table as the window's, no second copy
  to drift.
- `_capas_marca()` layer order is the design's: both arrowheads **after** both
  arcs, or the amber arc paints over the white arrowhead.
- The Checkbutton indicator is replaced by an image (`_casilla_propia`); its
  right-hand margin is unpainted transparent pixels so the same image works on
  paper and on a card.
- A `ttk.Treeview` cannot colour a single cell, so status chips become **row
  tags** (`theme.marcar_lista`) — background, not foreground, so the selected
  row's blue still shows.

### Window sizing

**Windows are shown already centred, never moved after the fact.** `modal()`
returns the dialog **withdrawn** and without a grab; `mostrar(dlg, parent)`
centres, deiconifies, grabs and waits — a window's size is not known until its
widgets are in. `grab_set()` and `update_idletasks()` must stay on their current
side of the `deiconify()` (Tk refuses to grab a non-viewable window).
`centrar()` clamps to the screen only when the parent is on the primary monitor.
Tests replace `mostrar()`, not `modal()`. The wizard root centres **once**, at
open (`tk_install.run_wizard()`); the exception is `Wizard.reencajar()`
re-centring when `Visor.crecer()` reports the body actually changed size.

`reencajar()` hangs off **`Wizard.revisar()`**, not `repintar()`: the «ya es un
prdrive» panel, the checks table filling in, and the verification table redraw
all change a step's height without a step change, and all three already end by
calling `revisar()`. While the fit lived in `repintar()` those three kept the
previous box and cropped the content **with no scrollbar** (the visor's
`interior` is a canvas item with height pinned by `itemconfigure`, so the
`<Configure>` the scrollbar hangs off never fires).

**Every screen sits inside a `tk.Visor`.** `interior` is where you draw;
`encajar()` sizes it to the content or to what fits, whichever is smaller;
`crecer()` (the wizard's) only ever grows it. Scrollbars appear **only** when
content is left over, and their gutter is reserved with `minsize` whether they
show or not. `pantalla_util()` is module-level so a test can pretend the screen
is 1024×600.

- `cuerpo_visible(ventana, padding=…)` replaces the `ttk.Frame(dlg, padding=…)`
  + `.grid(sticky="nsew")` every dialog used to open with.
- The wizard body's `ANCHO_CUERPO`/`ALTO_CUERPO` (via `icons.px`) are a starting
  minimum, not a cap — the old `ttk.Frame(width, height)` + `grid_propagate(False)`
  was a silent crop.
- `output_window` needs no visor (the `Text` scrolls); its `104x28` are text
  rows/cols, not pixels.
- `tests/test_tk_medidas.py` checks every screen against a matrix of resolution
  **and** `tk scaling` (1080p/2K/4K at 100/150/200 %, plus small laptops) — the
  scaling column is the half that matters. It also drives the "already a
  prdrive" case on a roomy screen and a 1024×600.

`tk.working(parent, title, funcion)` runs `funcion()` on a thread behind a bare
progress bar — for commands that take minutes and say nothing (creating a
VeraCrypt container) or whose command line is a secret (it carries the
passphrase). No cancel button on purpose.

## Provisioning a new device (`prdrive-install.py` + `install/` + `ui/tk_install.py`)

Eight steps; the order is load-bearing (you cannot read the catalogue before
knowing the remote, pick pairs before knowing where the device goes, or
initialise them before the `sync.py` that does so exists):

```
1 Dispositivo     which volume + the "already a prdrive" shortcut
2 Cifrado         VeraCrypt / BitLocker / none  → fixes state.device_root
3 Conexión        form, or import a remote from the user's rclone.conf
4 Comprobaciones  rclone + connect + read the catalogue
5 Instalación     copy .prdrive/, hide it, launchers, rclone.conf + keys
6 Parejas         pick from the catalogue, write sync_config.toml, make dirs
7 Inicialización  --resync of the bisync pairs
8 Verificación
```

`_paso_destino` depends only on `device.list_volumes()`, so it costs nothing to
put first; `Cifrado` follows because it settles `state.device_root`, which
`Instalación` writes to. Each step disables «Siguiente» until its condition is
met. **No console fallback** here (unlike `runsync.py`) — everything decided
happens once in a device's life with the screen in front of you.

**Nothing in the wizard spawns a shell.** An unsigned `.exe` running out of
`%TEMP%` that spawns `powershell.exe` is, to a behavioural AV engine, the shape
of a dropper — Sophos Intercept X blocked the installer outright. Two things now
ask Windows directly:

- **BitLocker status.** Reads `System.Volume.BitLockerProtection` via
  `IShellItem2::GetInt32` (the property Explorer uses to draw the padlock), no
  elevation. **Ask `PSGetPropertyKeyFromName` for the PROPERTYKEY**, never a
  remembered one (the `System.Volume.*` set is a different key that returns
  `ERROR_NOT_FOUND`). `BitLockerStatus.protected` accepts only state `On` — a
  volume in *Waiting for activation* (encrypted, key still in the clear) must
  fail, or the remote's private key gets written onto it.
- **Volume list.** `_win_volumes()` does it in four kernel32 calls (~35 ms vs
  `Get-Volume`'s measured 3.5 s, on the Tk thread while drawing the first
  screen). Needs `SetThreadErrorMode(SEM_FAILCRITICALERRORS)` (else an empty
  card reader pops a "no disk" modal) and `TIPOS_OCULTOS` (`GetLogicalDrives`
  returns mapped network drives).

`make_volume()` / `BitLockerStatus` are pure and tested; `_win_volumes()` /
`_leer_estado_bitlocker()` are module-level so tests replace them. There is **no
recovery-key feature** — reading a BitLocker recovery password genuinely needs
elevation, and it was not worth the last `runas`.

**The "already a prdrive" shortcut.** When `_paso_destino` sees
`device.install_target() == YA_INSTALADO` it shows the device's version vs the
installer's and offers **«Actualizar»** and **«Reinstalar desde cero»** —
**both, always**, because re-provisioning (new remote, re-encrypt, redo pairs)
must stay possible without deleting `.prdrive/` by hand.

- `Wizard.pasos` is an **instance** attribute: two step lists
  (`PASOS_INSTALACION`, `PASOS_ACTUALIZACION`), the button picks one.
  `_ir_a_actualizar()` *sets* the index (the shortcut is reachable from the
  device step and the encryption step, which don't land in the same place from
  "one more").
- `_ok_destino` returns False until a way out is chosen, so «Siguiente» stays
  dark next to the two buttons.
- `install_target()` looks for the **device before the content**: `.prdrive` is
  in `RUIDO` (or a device the installer just made reads as `AJENO` next time),
  so a freshly provisioned volume with no user data used to come back `VACIO`
  and the shortcut was the one thing not offered on the newest device that can
  exist.
- The short path installs the tree the **installer carries** (`bundle_dir()`,
  the same source step 5 uses) — no network. It calls
  `ensure_control_file(renew=False)` (step 5 renews because it provisions;
  renewing here would strand a watcher bound to this device's id). Going
  backwards in version is allowed but never silent (`_confirmar_retroceso()`).

**Other step notes:**

- With VeraCrypt, `.prdrive/` lives *inside* the container, so the volume looks
  empty until mounted — detection re-runs at the end of `_paso_cifrado`.
- **Step 5 no longer simulates first.** It used to be an `rclone sync` of a
  master mirror (deletes in the destination), hence the mandatory `--dry-run`
  and typed path. Now it copies a folder of its own and touches nothing else, so
  it runs straight through `ui.tk.working()`.
- **`Conexión` is what makes the repo publishable.** `profile.load()` returns an
  **empty** profile when nothing is embedded and nothing is in the checkout —
  not an error, the normal start for someone who just cloned.
- `install.InstallError` is raised instead of `sys.exit` (same reason as
  `model.ConfigError`). The private key is written to a temp dir that records
  the owning pid; `remote.sweep_stale()` cleans dirs left by hard-killed
  installers, asking `store.pid_alive()` first.
- **The key never leaves the device.** `deploy.write_device_remote()` writes
  `.prdrive/rclone.conf` and `.prdrive/keys/<name>` with **relative** paths
  (`key_file = keys/…`), which is what makes the device work under any drive
  letter (rclone resolves them against `cwd = model.APP_DIR`). Nothing mirrors
  `.prdrive/`.

## Updating a device in place (`common/update.py` + `ui/tk_update.py` + `--update`)

The main window shows an amber block when GitHub has a newer release; its button
does the whole thing.

- **The applier runs from the download, not the device.** `install/` is
  deliberately absent from a provisioned device, so the update runs `python
  <extracted>/prdrive-install.py --update <volume>` — **the new version installs
  itself**. An applier in `common/` would be a second copy of the "what is the
  deployed tree" manifest.
- **The payload is the source zip of the tag (~270 KB), not the release `.exe`
  (12.6 MB)** — the CI exe is generic and would re-ask for the connection.
- **`.prdrive/` is never renamed.** `deploy_code()` copies file by file.
  Stage-and-swap breaks three ways: `rclone.exe` may be running from
  `.prdrive/bin/`; if `.prdrive/runsync.py` vanishes for an instant penwatch
  loses its `STRUCT_MARKER` and relaunches the UI within 5–15 s; if
  `sync_config.toml` vanishes a running service shuts itself down. The cost —
  a module deleted upstream lingers on old devices — is what re-running the
  installer already did.

**`VERSION` at the repo root is the whole versioning story.** It is in
`DEPLOY_FILES` and `DATOS_FICHEROS`; `install.version()` reads it from
`bundle_dir()`, `update.installed_version()` from `APP_DIR`. The release
workflow is **triggered by a push to `main` that touches `VERSION`** and takes
`v<VERSION>` as the tag — the tag cannot disagree with the file. If the tag
already exists there is no new version (a push exits green; a manual
`workflow_dispatch` fails saying so). A device with no `VERSION` reads as
unknown, which compares older than anything.

`check()` never raises and honours a 24 h cache in `state/update.json`.
`pending()` reads that cache and **never** goes to the network (it is what the
first paint asks). The window refreshes on a thread after `deiconify()`;
`daemon_cycle()` refreshes it too (the only thing keeping it current for the
console menu, which prints its own notice in `console.main_menu`).

**What a download must survive** before it goes near the device: TLS, the zip
CRC, every name in `update.OBLIGATORIOS` present, no member whose path escapes
the destination (`_ruta_segura` — `extractall` is the footgun), and the
`VERSION` inside matching the tag asked for. There is no signature and the
README says so.

**`rclone_bin.download_rclone()` verifies before it writes:** reads
`downloads.rclone.org/version.txt`, pulls `<version>/SHA256SUMS`, hashes the zip
in memory — a mismatch leaves the cache untouched. The URL is the **versioned**
one, not the `rclone-current-…` alias (which moves, so a release landing
mid-fetch would make the sum describe a different file). It does **not** defend
against a compromised rclone.org (same TLS, same host) — only against a
truncated transfer, a proxy, a stale cache, the alias moving.

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
  before launching.
- It must never write to, or `chdir` into, the device (that blocks safe
  ejection); config, state and log live on the host, and every device access is
  wrapped in `try/except OSError` (a locked BitLocker volume errors rather than
  reporting "not found").
- Fires once per mount — the trigger re-arms only when the device disappears.
  `--mode`: `ui` (default), `sync`, or `daemon` (→ `runsync.py --auto`).
- `ui/watch.py` imports penwatch for reads and shells out for
  `install`/`uninstall` (output to `output_window`). One-way dependency.

## The catalogue (`common/catalog.py` + `ui/catalog_editor.py`)

`nas:/prdrive-catalog/pairs.toml` — same schema as `sync_config.toml`, shared by
every device, read by `prdrive-install.py` when provisioning. **A pair is
created or deleted there first**; each device only *chooses* which it uses. Do
not collapse that split:

- **Catalogue side** (`plan_catalog_save`/`_remove`/`_defaults`) writes the
  remote, changes nothing local. **No pair is sacred** — the installer carries
  the code now, so the catalogue is all data pairs, all equal.
- **Device side** (`plan_enable`/`_remove`/`_override`/`_revert`) writes
  `sync_config.toml`, never the remote. `[defaults]` is catalogue-governed too
  (`plan_defaults`/`plan_revert_defaults`).

`sync_config.toml` holds **complete** pair entries, not references (`sync.py`
must work with no network). Provenance is **derived**, not stored:
`catalog.diff_keys()` compares the local entry against `state/catalog.toml` (the
last successful pull) → `catálogo` / `modificada aquí` / `huérfana` / `sin usar`.
**Do not add a `from_catalog` key** — `config_file.save()` demands strict
round-trip equality and the file is hand-editable.

`catalog.push()` is the riskiest thing in the project: it generates and verifies
the text (`config_file.dumps_checked`), **re-reads the remote and refuses if it
changed**, copies `pairs.toml` → `pairs.toml.bak`, and only then uploads.
Rewriting keeps the header block and **loses interleaved comments**.
`catalog.load()` never raises — no network falls back to `state/catalog.toml`,
and a cached catalogue is **not editable** (`Catalog.editable`).
`catalog.NET_FLAGS` keeps a dead remote from freezing the window.

The catalogue also carries an optional **`[remote]`** table: the non-secret
definition of the rclone remote (type, host, user…). The first device writes it,
the rest inherit it via `profile.align_with_catalog()`. **The catalogue decides
the remote's name** — every pair's `remote_path` resolves against
`[defaults].remote`, so a differently-named remote would fail every sync with an
"unknown remote". The private key never goes there.

## Editing pairs from the UI (`ui/pair_editor.py`) — the dangerous part

`bisync.expected_prefix()` derives from `local`, `remote`, `remote_path`,
`mode`. Change any and the expected listing name changes, so on the next run
`normalize_prefix()` would **rename the old baseline to the new name** — telling
bisync that a listing of the *previous* destination describes the *new* one.
Everything missing from the new side then reads as deleted and propagates, with
`--max-delete 25` as the only brake. `normalize_prefix()` was written for the
benign case (`G:` → `F:`) and cannot tell the two apart.

- The editor shelves the baseline: `bisync.shelve_baseline()` renames
  `state/<pair>/` → `state/<pair>.old-<date>/`, leaving the pair `fresh` and
  forcing an explicit `--resync`. Shelved dirs are inert (scans only look at the
  top level).
- **Renaming a pair is free** — the prefix doesn't depend on the name.
  `bisync.rename_pair_state()` moves `state/<name>/` and `filters/<name>.*`
  together (the `.md5` must travel with its file).
- **The decision compares prefixes, not keys.** `_prefixes(raw)` parses the
  before and after configs and compares `bisync.expected_prefix()` per pair;
  `ENDPOINT_KEYS` only produces the human-readable message. This is what makes
  `[defaults]` editable — `remote`/`device_remote` feed *every* pair, so
  `EditPlan.shelve` is a **list**. A prefix that *disappears* (bisync → another
  mode) also shelves.
- `plan_*()` return an `EditPlan` **without touching anything**; its
  `consequences` are shown before confirming. `EditPlan.execute()` does the disk
  surgery **before** writing the config and undoes it if the write fails (it can
  only ever fail towards "baseline shelved for nothing", which a `--resync`
  fixes). **Rename runs before shelve** (else `filters/<old name>.txt` is
  orphaned).

## The flags editor (`ui/flags_editor.py`)

Flags are written in TOML syntax (a text box, not a row-per-flag form) and
parsed with **`tomllib`, not by hand** — the destination is a `[pair.flags]`
table. `dump()` renders through `config_file.dumps_table()`. Only what the
serializer can write back is accepted (scalars, arrays of scalars). `RESERVED`
rejects the flags `sync.py` supplies per run and the filter ones — a second
`--workdir` or `--filters-file` points bisync at the wrong baseline.

`effective()` resolves the four layers into what rclone would actually receive,
each row labelled with its layer. `warnings()` compares **merged** flag sets,
never one layer, so it catches `--max-delete` rising because the pair's own
value was deleted or the mode changed. Editing flags never shelves a baseline.

`ui/tk_pairs.flags_form()` is the drawing half and does **not** close on invalid
input. Both the pair form and the `[defaults]` form open it;
`pair_editor.merge_form()` (shared with `catalog_editor`) makes an emptied box
delete the key.

## Writing the TOML (`common/config_file.py`)

`tomllib` only reads and the project takes no dependencies, so the serializer is
hand-rolled. It covers scalars, string arrays and one nested `flags` table. Two
things to preserve: `[pair.flags]` binds to the **last** `[[pair]]` written, so
it is emitted right after its own pair; and `dumps_checked()` re-parses what it
generated and refuses to write if the dict does not reproduce. `save()` and
`catalog.push()` both go through it. Work on the **raw dict**, never
`model.Config` (its `Pair`s arrive with `[defaults]` merged). `header_of(text)`
is for headers that never hit disk; `save(head=None)` keeps the target's
existing header.

## Conventions

- All comments, docstrings and user-facing output are **Spanish**. Keep it that
  way.
- Comments explain *why* against rclone's actual behaviour, often citing the
  rclone source file. Preserve that when touching bisync-related code.
- `sync_config.toml` is per-device: generated from the catalogue at
  provisioning, then maintained by the pairs screen. Still hand-editable — a
  pair that ends up differing from the catalogue is *reported* as "modificada
  aquí", not corrected.
- Recurring idiom: `catalog.run()`, `update.fetch()`, `rclone_bin.fetch()`,
  `model.state_file()`, the `penwatch` reads, `_win_volumes()`,
  `_leer_estado_bitlocker()` are module-level indirection points **so every test
  replaces them** — no test touches the network or a real device.

## Documentation

- **`README.md`** is the front door of a public repo and the thorough one (the
  three-piece model, install, flag layering, how bisync's baseline works, the
  service, the watcher, the security model, the architecture).
- **`device-readme.md`** is the *light* quick guide — **not** for repo readers.
  The installer copies it to the volume root as `README.md`
  (`deploy.write_guide()`). Keep it short, task-shaped, free of internals.
  `write_guide()` is best-effort (returns None if the template is missing rather
  than aborting an otherwise-fine install; same criterion as `hide()` /
  `icons.get()`). `build_installer.py` lists it in `DATOS_FICHEROS`, so a build
  that forgets it fails at compile time.
- **`sync_config.example.toml`** is tracked and is the schema reference for both
  `sync_config.toml` and the remote's `pairs.toml` (which additionally takes
  `[remote]`). Verified by hand with `config_file.dumps_checked()`.
- **`LICENSE`** is the Apache License 2.0, verbatim, appendix copyright filled
  in. README's «Licencia» section points at it; keep the two in step.
