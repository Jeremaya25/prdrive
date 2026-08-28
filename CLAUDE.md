# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**prdrive**: portable two-way sync between *any* rclone remote and a removable
drive, driven by a bundled `rclone` binary. Pure Python **stdlib**, Python 3.11+
(`tomllib`). No build, no dependencies, no package manifest. Tests are plain
scripts under `tests/` — `python tests/run_all.py`, no framework, nothing touches
a real device or the network.

The code knows **no server**: everything about the connection lives in a
`profile.Profile` that the wizard asks for, imports from the user's `rclone.conf`,
or carries embedded in the compiled `.exe`. What the remote stores is
**configuration only** — the catalogue of pairs — never the program.

Four entry points stay at the repo root: three because the volume-root launchers
(`runsync.pyw` / `runsync.sh`) and `penwatch.py` locate them by fixed path, and
`prdrive-install.py` because it is what gets compiled and handed out. Everything
else is split by what it knows about:

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
│   └── store.py       the device's JSON state files + pid_alive(): reads that
│                       tolerate anything, atomic writes
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
│   ├── __init__.py    the brand constants, InstallError, InstallState, python_command()
│   ├── profile.py     the connection: where it comes from and how it is written
│   ├── rclone_bin.py  get hold of an rclone to start with
│   ├── remote.py      the ephemeral rclone.conf and the pair catalogue
│   ├── device.py      what volumes exist, which one is the device, was it mounted right
│   ├── crypto.py      VeraCrypt and BitLocker
│   └── deploy.py      copy the code in, write the device's config, --resync
└── tests/             plain scripts; run_all.py runs them in separate processes
```

The `tk_*` modules only draw. Everything that decides or touches disk lives in
`pair_editor.py` / `catalog_editor.py` / `flags_editor.py` / `watch.py` /
`install/`, which import no Tk and are tested headlessly. `theme.py` and
`icons.py` sit under the `tk_*` modules: they own every colour, font and glyph,
so a `tk_*` module never writes a hex value of its own.

`prdrive-install.py` also sits at the root and **is** tracked in git: it is the
fourth entry point, and it is a launcher — arguments in, `ui/tk_install.py` out.
The one exception is `--update`, which does its work right there and never opens
a window: it is the applier of the self-update, it runs from the *downloaded*
copy of the project rather than from a device, and a wizard step for it would be
a wizard nobody is sitting in front of. Everything else it knows lives in
`install/`, which **does** import `common/`
(`model.BASE_FLAGS`, `model.flags_to_args`, `config_file.save`,
`store.pid_alive`): what the installer writes has to be byte-for-byte what
`sync.py` will later read, and a second copy of those rules is a second place to
get them wrong. What it must NOT import is `ui/` outside `tk_install`, and it
must keep working with **no device anywhere** — it runs before one exists.

It ships as a PyInstaller executable (`build_installer.py`), and that build does
**two** things: it packs the tree the installer will deploy (`sync.py`,
`runsync.py`, `penwatch.py`, `common/`, `ui/` as `--add-data`), and it optionally
embeds a connection profile with its private key. Both halves matter:

- `common/` and `ui/` end up in the bundle **twice** — as importable bytecode
  (the installer uses them) and as copyable data (what gets deployed).
  PyInstaller cannot hand back the `.py` source of a module it imported, and
  source is what has to land on the device.
- **Without a profile** — the normal case for a clone of this repo — the binary is
  generic, carries no secret at all, and asks for the connection in step 1.
  **With one** (`prdrive-profile.toml` + `keys/` in the checkout) it is
  turnkey and must only ever be shared privately. This split is what lets the
  repo be public: `install/secret.py` is generated at build time, gitignored, and
  deleted in a `finally`.

Two traps that only show up frozen: `sys.executable` is the installer and not
Python (hence `install.python_command()`), and `sys.stdout` can be None with
`--windowed` (hence `report()`, which opens a window when there is no console).

`design/` holds the UI redesign mock-ups (`.dc.html` artboards) that `ui/` now
implements. They are design, not code: nothing imports them and nothing is
generated from them, so a change in `ui/` does not update them — they are the
record of what was decided, and `Sistema.dc.html` is the sheet `ui/theme.py`
translates.

`penwatch.py` must NOT import either package: it is copied to the host and has to
keep working with the device unplugged.

On a provisioned device the code lives in `.prdrive/` at the volume root — the
leading dot hides it on POSIX and `deploy.hide()` sets the hidden attribute on
Windows. `model.APP_DIR` is `Path(__file__).parent.parent` and `DEVICE_ROOT` is
its parent, so **nothing depends on the folder name or the drive letter**: a
development checkout called anything at all works the same. `deploy.APP_SUBDIR`
is the name the installer writes, and `penwatch.STRUCT_MARKER` /
`device.STRUCT_MARKER` are the two copies that have to agree with it — as are
`penwatch.CONTROL_FILE` / `device.CONTROL_FILE`, which is `.prdrive/PRDRIVE`.
The control file sits **inside** that folder rather than at the volume root:
identifying the drive only needs a path relative to its root, so anywhere does,
and inside it leaves nothing loose among the user's files and cannot be deleted
without deleting the program too. `tests/test_install_device.py` asserts the two
copies of both constants have not drifted.

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
python runsync.py --doctor     # any other args are passed straight through to sync.py

python penwatch.py install     # register the mount watcher on THIS machine/user
python penwatch.py status      # what is registered + whether the device is visible now
python penwatch.py probe       # detection only: candidate roots and what matched
python penwatch.py uninstall

python prdrive-install.py          # the install wizard for a NEW device (Tk only, no console menu)
python prdrive-install.py --check  # rclone + connection + catalogue, then exit
python prdrive-install.py --probe  # what drives it sees, then exit
python prdrive-install.py --update E:\   # replace the code of an installed device
python build_installer.py          # build the .exe (PyInstaller; embeds the profile if there is one)
python -m ui.icons                 # repaint APP_DIR/runsync.ico (no Tk, no display)

python tests/run_all.py        # todos los tests (scripts sueltos, sin framework)
python tests/test_pair_editor.py   # o uno solo
```

`runsync.py` with no args always **stops a previously started service** first.
Verification is by `tests/run_all.py`, `--doctor` and `--dry-run`; there is
nothing to lint.

Git note: this checkout sits on an exFAT/NTFS volume, so git refuses it as
"dubious ownership" — prefix commands with `-c safe.directory=F:/rclone-sync`.
`.gitignore` excludes everything device- or user-specific (`bin/`, `keys/`,
`filters/`, `logs/`, `state/`, `sync_config.toml`, `rclone.conf`,
`prdrive-profile.toml`), so what is tracked is the code (`sync.py`, `runsync.py`,
`penwatch.py`, `prdrive-install.py`, `build_installer.py`, `common/`, `ui/`,
`install/`, `tests/`) plus `VERSION`, `design/`, `sync_config.example.toml`,
`README.md`, `CLAUDE.md` and `.gitignore`. The installer's build artefacts (`build/`, `dist/`,
`*.spec`) and its embedded profile (`install/secret.py`) are ignored too — the
private key is what makes those last two non-negotiable. **Nothing on the device
travels to the remote any more**: no pair mirrors `.prdrive/`, so neither the key
nor the state nor the code can leak that way.

## Architecture

`sync.py` is the engine. `runsync.py` no longer imports it at all — it talks to
`common.model` for config and shells out to `model.SYNC_PY <pair>` per pair, so
the two never share in-process state. It never re-implements sync logic.

**Parse once, at the boundary.** `model.parse_config()` turns the TOML into frozen
value objects and nothing downstream re-reads TOML keys or repeats
`.get(key, default)`; in particular `defaults` stops being threaded through every
signature, because every layer it contributes is already merged:

- `Mode` — one entry per mode in `MODES`, carrying the rclone subcommand, which
  end is source and which is dest, and that mode's default flags. Adding a mode
  means adding one `Mode(...)` to that table.
- `Pair` — a `[[pair]]` with every layer resolved: `includes`/`excludes`, merged
  `flags`, `extra_flags`, and the endpoint properties (`local_endpoint`,
  `remote_endpoint`, `source`, `dest`, `local_abs`, `workdir`).
- `Config` — the pairs plus `[daemon]`, `keep_logs`, `device_remote`, with
  `select()` (aborts on unknown names) and `pen_environment()`.

An invalid `mode` is rejected at parse time rather than when that pair runs, so a
typo in the TOML stops `--list`/`--doctor`/a run alike instead of only the
affected pair. Same message, earlier.

Validation raises **`model.ConfigError`**, it does not `sys.exit`: the UI uses the
same model, and there killing the process means closing the window in the user's
face instead of showing which line is wrong. The CLI entry points catch it and
exit with its message, so nothing changes on the console. The two surviving
`sys.exit`s in `model.py` are the tomllib import (unrecoverable, at import time)
and the missing rclone binary (environment, not config).

**Config → command.** Flags merge in layers, last wins: `BASE_FLAGS` <
`Mode.flags` < `[defaults.flags]` < `[pair.flags]` — all of it inside
`model._build_pair`, so `Pair.flags` arrives ready. `build_command()` only adds
what depends on *this* run, and `model.flags_to_args()` turns `key = value` into
`--key value` (`true` → bare flag, `false`/`None` → dropped, list → repeated flag,
`_` → `-`). It lives in `model.py`, not in `sync.py`, because the UI has to show
what a flag turns into without importing the engine. **Adding an rclone flag means
editing the TOML, never the code.** The script owns `--config`, `--log-file`,
`--dry-run`, `--workdir`, `--resync`; `extra_flags` is the raw-string escape hatch.

**`RunContext`** carries what does not change between pairs in one invocation
(binary, env, `dry_run`, `force_resync`, `resync_approved`, `keep_logs`), so
`run_pair(ctx, pair)` replaces an eight-positional-argument call that ended in
four consecutive booleans.

**Why the ugly parts exist** (all of it is about bisync's baseline; the comments in
`sync.py` cite the rclone sources they replicate):

All of it lives in `common/bisync.py`, on purpose: it is the one place that
imitates rclone's own behaviour, and each section cites the rclone file it mirrors.

- *Session prefix.* bisync names its listings after the two endpoint strings.
  `canonical_path`/`session_name`/`expected_prefix` replicate
  `cmd/bisync/bilib/canonical.go` so the script knows the filename rclone will look
  for **before** running. `normalize_prefix()` renames an existing listing set when
  it no longer matches (device mounted as `E:` instead of `F:`); `heal_listings()` is
  the fallback that parses the `Tip: Path1/Path2` lines out of a failed log and
  retries **once**. Current state files are `F__sync-data_...` — drive-letter bound.
- *`device_remote`.* Setting `device_remote = "device"` in `[defaults]` makes the device side a
  `combine` remote defined via `RCLONE_CONFIG_<NAME>_TYPE/_UPSTREAMS` env vars
  (`Config.pen_environment()`, computed from **all** pairs so it is identical
  whatever you run), making the prefix machine-independent. An `alias` remote does *not* work —
  it returns the target Fs itself and the absolute path reappears. Not enabled in
  the current `sync_config.toml`.
- *Filters.* For `bisync` only (`Pair.wants_filters_file`), `filters_file_for()`
  generates `filters/<pair>.txt` from the TOML include/exclude patterns and passes
  `--filters-file`; in that case `--include/--exclude` are **not** also emitted
  (duplicate rules break change detection). bisync stores the md5 beside the file
  and only rewrites it during `--resync`, so `filters_state()` compares the hash
  itself and reports "needs resync" instead of letting rclone abort.
- *State.* One workdir per pair, `Pair.workdir` → `state/<pair>/`;
  `migrate_legacy_state()` moves the old flat layout. `pair_state()` returns a
  `PairState(status, detail, prefix)` with `fresh|ok|broken` read from the actual
  `.lst` files (`.lst-err` residue is ignored when a valid pair of listings
  exists). `resync_reasons(pair, state=None)` returns the reasons this pair needs
  a `--resync`, empty when it does not, and answers `[]` for non-bisync pairs —
  the mode guard lives inside it now, so no caller can forget it. `last_run(pair)`
  is the mtime of the newest listing, which **is** the last good pass: bisync
  rewrites both listings on success, so there is no run log to invent. Non-bisync
  pairs get None (a `copy` leaves no state) and the window shows a dash rather
  than a made-up time; `ui.pair_times()` returns the raw timestamps, not text, so
  the header can take the most recent one — sorting the strings would put 'ayer'
  ahead of '08:20'.
- *Resync approval.* `resolve_resync_approval()` asks **once** for all pairs before
  anything runs. `ask_yes_no()` returns the default when stdin is not a tty, so
  non-interactive runs skip those pairs (`SKIPPED = -1`, distinct from rc 0/failure)
  rather than resyncing unattended.

**Safety invariants — do not weaken:**

- If a bisync baseline exists but the local path does **not**, `_bisync_preflight()`
  aborts with rc 2 instead of creating the folder: an empty local side reads as
  "everything was deleted". Only pairs without a baseline get their local dir
  created.
- `max-delete` defaults (25 bisync / 50 mirror) exist for the same reason.
- rclone always runs with `cwd = model.APP_DIR` (i.e. `.prdrive/`, **not** the
  package dir) because `rclone.conf` uses paths relative to it (`key_file`,
  `known_hosts_file`) to stay portable. `model.APP_DIR` is
  `Path(__file__).parent.parent` precisely because `model.py` sits one level down;
  `DEVICE_ROOT` hangs off it. Moving these files changes those anchors.
- Any `*-mirror` pair deletes on the far side. Never exercise one without
  `--dry-run` first. There is **no longer** a pair that mirrors the whole device:
  the code no longer travels through the remote, so nothing needs one.

**Logs.** rclone always writes to a temp file; `dispose_log()` keeps it in `logs/`
only when the run failed (or `--keep-logs` / `keep_logs = true`), to spare write
cycles on the device. On failure the tail is printed and `KNOWN_ERRORS` maps rclone
messages to an explanation — add new cases there rather than in the caller.

`--log-file` only catches what rclone logs **after** it installs the log, so
`execute()` captures rclone's console (`stdout`+`stderr`) and `append_output()`
appends it to that same file under `DIRECT_OUTPUT_HEADER`. Without it, everything
that fails at startup — a flag that does not exist, a value it does not accept
(`conflict-resolve = "new"` when the valid one is `newer`) — left a **0-byte log**
and a failure with nothing to print and nothing to explain, which is the one case
where that message is all there is. Captured and not inherited because with no
console behind it (pythonw, the service) inherited output goes nowhere, and even
with one it stayed outside the file that later gets kept, shown and explained.

`strip_usage()` drops the help dump rclone prints after a bad flag, and it is not
cosmetic: those 12 KB bury the message in the 15 lines of `print_log_tail`, and
they mention `--max-delete` and `lock file`, so `explain_failure()` matched a
`KNOWN_ERRORS` needle inside rclone's own documentation and explained a failure
that never happened. **A false diagnosis is worse than none.** For the same
reason the two flag entries in `KNOWN_ERRORS` go **last**: a log carrying one of
the others is a real sync failure, and that is the one to explain.

**Daemon (`runsync.py`).** Coordination lives in `state/` so it travels with the
device: `daemon.lock.json` (pid/host/pairs/last cycle, written atomically),
`daemon.stop` (presence = stop request), `daemon.log` (self-trimming),
`ui_prefs.json` (last UI choice). `startup_defaults()` layers that memory over
`daemon_defaults()`: last choice > `[daemon]` in the TOML > all pairs / 30 min,
and it feeds both the UI prefill and `--auto`'s no-argument case. Only the UI
writes it (`save_prefs()` from `ui_flow`, for `manual`/`daemon` — not `doctor`);
`--auto` and `--daemon` only read, so an automatic start never overwrites what
was chosen by hand. `store.read_json`/`write_json` are the shared primitives under
both the lock and the prefs, and `store.pid_alive()` lives beside them because a
lock file with a pid inside is only worth anything if you can ask whether whoever
wrote it is still running: the daemon asks it about its own lock, and the
installer about the ephemeral key directories a killed run left behind.

**UI (`ui/`).** Two frontends implement the same four operations (`ask`,
`approve_resync`, `info`, `run_sync`), and `ui.start(config, msg)` returns the
choice **together with the frontend that took it** — whoever asked is who knows
how to show the answer, since a window cannot dump output to a console that does
not exist and vice versa. Both return `Choice(action, pairs, minutes)`, so callers
read `choice.action` instead of indexing a variable-length tuple.

`output_window` colours each line by what it says (`tk._tono`), and that table is
the vocabulary `sync.py` already prints — `=== pair ===`, `  ejecutando:`,
`[pair] OK.`, `[pair] FALLÓ`, the final `Hecho. n/m parejas OK…`. Read it beside
sync.py's `print()`s: if a wording changes there, a line stops being coloured
here, nothing breaks. It also offers **Guardar el log**, because `dispose_log()`
only keeps rclone's log when the run failed, so that window is the single copy of
a successful pass.

A plan's consequences are shown by `tk_pairs.confirmar_plan()`, a real window with
one line per consequence and each warning in its amber box — not an
`askokcancel`. Six lines of running text in a message box is exactly what nobody
reads, and this is the dialog that governs deletions. Tests replace
`tk_pairs.confirmar_plan`, the way they replace `mostrar()`.

`ConsoleFrontend.approve_resync` always returns False on purpose: with a real
terminal, `sync.py` inherits stdin and asks the question itself, with more context
than a dialog fits. Returning True there would append `--yes` and take that
conversation away from the user.

**The look lives in `ui/theme.py` and `ui/icons.py`, and nowhere else.** The
screens implement `design/`, and `Sistema.dc.html` is the sheet: warm paper, near
black ink, one blue accent, amber for warnings, monospace for paths and flags; no
rounded corners and no shadows, because those are the two things ttk cannot draw
and faking them with images would mean changing toolkit to decorate.

- **`theme.nitidez()` runs before the first `Tk()`, and that is the whole reason
  the window is sharp.** A process that does not declare DPI awareness is lied
  to about the screen: on a 4K at 200 % Windows reports 1472x920 at 96 ppp
  instead of 2944x1840 at 192, Tk draws at that size and the compositor
  **stretches the bitmap** to the real panel. That stretch is the blur, and no
  amount of font work fixes it — the glyphs are being painted with half the
  pixels available. Declared, `tk scaling` goes from 1,33 to 2,67 and everything
  measured in points grows on its own. It is **system** awareness and not
  per-monitor on purpose: Tk 8.6 does not handle `WM_DPICHANGED`, so on a
  second monitor at another zoom Windows stretches the window (blurry but the
  right size) instead of leaving it at half its physical size, which is worse.
  Tk reads the density once when its interpreter starts, so the call has to
  precede `Tk()`; it is a process property, and it is called from all five
  places that open a root because which one runs first depends on the entry
  point.
- **A design distance goes through `theme.medida()`, never as a bare integer.**
  Tk takes a plain number as pixels and a number with `p` as points, which it
  multiplies by `tk scaling`. `wraplength=760` measures 760 px at 100 % *and* at
  200 %, so on a dense screen the same text — which did grow — is squeezed into
  a column half as wide and three times as tall; the wizard's «Conexión» step
  went from asking 1042 px of width to 1449, and stopped overflowing.
  `theme.medida()` and `icons.px()` are the same idea in two shapes: `px()`
  returns an int, for what Tk cannot scale at all (the icons' bitmaps) and for
  what only takes an int (`rowheight`, which at a fixed 28 px clipped its own
  37 px rows); `medida()` returns Tk's own distance and needs no widget at hand.
  `tests/test_tk_densidad.py` guards both the effect and the habit: it fails if
  a `wraplength`/`rowheight` in bare pixels reappears anywhere in `ui/`.
- `theme.apply(widget)` switches to the **clam** theme and repaints everything.
  clam and not the native theme because it is the only bundled one that lets you
  set each border colour (`bordercolor`/`lightcolor`/`darkcolor`), and without
  that a button cannot be a 1 px box of the colour the design says. It runs
  **once per Tk interpreter** (styles are global inside one, and a session opens
  more than one: the main window, then the wizard).
- Styles are generated by crossing **role** (normal, hint, eyebrow, mono…) with
  **surface** (paper, card, grey strip, amber block), because a `ttk.Label` does
  not inherit its parent's background: the same hint on a white card and on the
  paper are two different styles. The alternative — passing the colour by hand at
  every call — is what guarantees one gets missed the day the palette moves.
- `icons.py` rasterises the glyphs itself: no dependencies (no Pillow), Tk cannot
  read SVG, and the design says «no emoji» — an emoji ✓ comes out in the system's
  emoji font, in colour, at a size nobody controls. Each icon is a list of
  primitives on the 16 grid and the rasteriser measures, per pixel, the distance
  to the nearest ink, which gives antialiasing for free at any size.
  `PhotoImage.put()` has no alpha, so `_rasterizar()` **takes the background and
  composes against it** — cheap, because the whole palette is flat — while
  `_capas_rgba()` keeps the alpha for the one caller that needs it, the `.ico`.
  `icons.get()` returns None on any failure and the caller keeps its text: an
  ornament cannot stop a window opening.
- Square caps and miter joins are done by `_expandir()`, **once per layer, not per
  pixel**: it moves the free ends outward by half the stroke and drops a wedge
  (two triangles, `b`-`A`-`T`-`C`) into every corner. Both matter at thick
  strokes and neither is optional — the app icon's arrowheads are two segments at
  a right angle, and without this they came out as a lozenge instead of a point.
  The wedge is the **quadrilateral** and not just the triangle `A`-`T`-`C`: the
  two stroke rectangles cross at the vertex, so the triangle alone leaves the
  point floating a hair away from the rest.
- `write_ico()` paints `runsync.ico`, which is what `iconphoto()` cannot reach:
  the icon of a shortcut, of a pinned taskbar button and of the installer's
  `.exe` (`build_installer.py` generates it into `build/` and passes `--icon`).
  It is Tk-free — `_capas_rgba` is plain Python — so it runs headless. Sizes ≤ 64
  go in as DIBs and 128/256 as PNG (`zlib` is stdlib): a raw 256×256 is 270 KB
  against 3 KB compressed, and PNG is what Windows expects at that size. The file
  is written into `.prdrive/` by the wizard's install step, and **repainted**
  rather than copied: it comes out of the same glyph table as the window's, so
  there is no second copy to drift. Inside the hidden folder and not at the
  volume root, because a stray icon among the user's files would be the only
  visible leftover.
- The layer order of `_capas_marca()` is the design's and is not decorative:
  both arrowheads go **after** both arcs. Grouped by colour, the amber arc paints
  over half the white arrowhead.
- The Checkbutton indicator is replaced by an image element (`_casilla_propia`):
  clam draws something closer to a cross and only lets you pick its colours. Its
  right-hand margin is *unpainted* pixels of the same PhotoImage — a new one is
  transparent — so the same image works on paper and on a card.
- `icons.px()` scales the design's pixel sizes by `tk scaling`: Tk scales fonts on
  a dense screen but not bitmaps, and a fixed 15 px icon next to grown text looks
  like a toy.
- A `ttk.Treeview` cannot colour a single cell, so the design's status chips
  become **row tags** (`theme.marcar_lista`), which is what the sheet prescribes
  for that table. Background and not foreground, so the selected row's blue still
  shows on top and monospace paths stay readable.

**Windows are shown already centred, never moved after the fact.** `modal()`
returns the dialog **withdrawn** and without a grab; `mostrar(dlg, parent)` centres
it, deiconifies, grabs and waits. The split exists because a window's size is not
known until its widgets are in, and positioning it afterwards means watching it
appear in a corner and jump. `grab_set()` and `centrar()`'s `update_idletasks()`
must stay on their current side of the `deiconify()`: Tk refuses to grab a window
that is not viewable. `main_window` and `output_window` do the same by hand.
`centrar()` only clamps to the screen when the parent is on the primary monitor —
with two screens the coordinates go negative and "correcting" would drag the dialog
across. Tests replace `mostrar()` (not `modal()`) to keep windows off the screen.
The install wizard's root does it by hand too, in `tk_install.run_wizard()`; it
centres **once**, at open, and not on every step — a wizard that re-centred as its
body changed size would walk across the screen while you use it. The one
exception is `Wizard.repintar()` re-centring when `Visor.crecer()` reports the
body actually changed size: growing without recolocating puts the footer past
the bottom edge, and that only happens on the step that grows it, not on every
step.

**Every screen sits inside a `tk.Visor`, so it fits on any screen.** Font sizes
are in points, so Tk grows them on a dense display or with the system zoom at
150 %, while a container measured in pixels does not grow with them — and a
window cannot be taller than the screen no matter what. `Visor` is a canvas of a
known size with the content inside: `interior` is where you draw, `encajar()`
sizes it to the content or to what fits, whichever is smaller, and `crecer()`
(the wizard's) only ever grows it. Scrollbars appear **only** when content is
left over, and their gutter is reserved with `minsize` whether they show or not
— a bar that took and gave back its own width would resize the window from step
to step, and would oscillate on and off around the threshold. `pantalla_util()`
is what "fits" means and it is a module-level function so a test can replace it
and pretend the screen is 1024x600.

- `cuerpo_visible(ventana, padding=…)` replaces the `ttk.Frame(dlg, padding=…)` +
  `.grid(sticky="nsew")` every dialog used to open with, and hangs the visor off
  the window so `mostrar()` calls `encajar()` without each dialog remembering to.
- The wizard's body was a `ttk.Frame(width=820, height=430)` with
  `grid_propagate(False)`, which is a **silent crop**: step 1 asks for 486 px of
  height on an ordinary 1080p screen and its last field simply was not drawn.
  Its size is now a starting minimum (`ANCHO_CUERPO`/`ALTO_CUERPO` through
  `icons.px`), not a cap.
- `output_window` needs no visor — the `Text` already scrolls — but its `104x28`
  are rows and columns of text, not pixels, so it asks for the ones that fit.
- `tests/test_tk_medidas.py` is the guard: every screen against a matrix of
  resolution **and** `tk scaling` — 1080p/2K/4K at 100 %, 150 % and 200 %, plus
  the small laptop sizes — checking that the window asks for no more than there
  is and that nothing is cropped without a scrollbar to reach it. The scaling
  column is the half that matters: a 4K on its own only proves there is room to
  spare, while a 1080p at 200 % is where the content stops fitting. It fakes both
  by replacing `pantalla_util` and calling `tk scaling` on the interpreter, which
  is reversible and is picked up by widgets created afterwards.

`tk.working(parent, title, funcion)` is the third way of showing something
running, next to `output_window` (a command whose output is the point) and a plain
modal. It runs `funcion()` on a thread and shows a bare progress bar, and it
exists for the two cases where the output cannot be shown: commands that take
minutes and say nothing (creating a VeraCrypt container) and commands whose very
command line is a secret (it carries the passphrase). It has no cancel button on
purpose — what goes through it cannot be cut in half without leaving things worse.

**`import tkinter` always goes inside the functions, never at module top level.**
`ui/` is imported by the headless paths too (`--auto`, the service), where tkinter
may not be installed and there may be no display; the failure has to surface when
the window is opened, which is when `ui.start()` can catch it and fall back to the
console menu. Verified in both directions. `save_prefs` stores `known` (the pair names that existed at
the time) so a pair added to the TOML later reads as new — and comes back
checked — instead of as one the user had unchecked; it skips the write entirely
when nothing changed, to spare the device. A record whose pairs are all gone falls
back to the TOML silently.

The service
stops when the device disappears (`SENTINEL` check) or when runsync is launched again.
Windows specifics that must be preserved: `pid_alive()` uses `OpenProcess`, never
`os.kill` (which *terminates* on Windows); the daemon is spawned with `pythonw.exe`
+ `CREATE_NO_WINDOW`, and rclone is spawned with `CREATE_NO_WINDOW` too, otherwise
every invocation flashes a console window; the daemon `chdir`s to the temp dir so
the device can be safely ejected. Child `sync.py` runs get `stdin=DEVNULL` on purpose,
so a pair needing `--resync` is skipped instead of resynced unattended.

**Provisioning a new device (`prdrive-install.py` + `install/` + `ui/tk_install.py`).**
Eight steps, and the order is not decorative: you cannot read the catalogue before
knowing which remote to talk to, nor pick pairs before knowing where the device
goes, nor initialise them before the `sync.py` that initialises them exists.

```
1 Dispositivo     which volume  — and the shortcut out, see below
2 Cifrado         VeraCrypt / BitLocker / none -> fixes state.device_root
3 Conexión        form, or import a remote from the user's rclone.conf
4 Comprobaciones  rclone + connect + read the catalogue
5 Instalación     copy .prdrive/, hide it, launchers, rclone.conf + keys
6 Parejas         pick from the catalogue, write sync_config.toml, make dirs
7 Inicialización  --resync of the bisync pairs
8 Verificación
```

**The device goes first so the wizard can recognise one it has already made.**
`_paso_destino` depends on nothing (`device.list_volumes()` and no more), so it
costs nothing to put it there, and `Cifrado` has to follow it because it is what
settles `state.device_root`, which `Instalación` writes to. Connection and
catalogue can wait: nothing needs them until `Parejas`.

Each step carries its own condition and «Siguiente» stays disabled until it is
met, so the window can never reach a place where the next button would fail.
There is **no console fallback** here, unlike `runsync.py`, and that is
deliberate: everything decided in it — which drive gets written, a passphrase
typed twice, the connection to the remote — happens once in a device's life, with
the screen in front of you, and a text menu replicating it would double the code
in the most delicate part of the project.

**The shortcut: a volume that is already a prdrive.** When `_paso_destino` sees
`device.install_target() == YA_INSTALADO`, it shows which version is on the device
and which one the installer carries, and offers two ways out. Three things about
it are load-bearing:

- **Both ways out, always.** Recognising the device must not take away the
  ability to re-provision it — changing remote, re-encrypting, redoing pairs all
  need the full wizard, and forcing someone to delete `.prdrive/` by hand to get
  there would be a trap. So «Reinstalar desde cero» sits next to «Actualizar».
- **`Wizard.pasos` is an instance attribute, not the old module global.** That is
  the whole mechanism: there are two step lists (`PASOS_INSTALACION`,
  `PASOS_ACTUALIZACION`) and the button picks one. `_ir_a_actualizar()` *sets*
  the index rather than advancing by one, because the shortcut can be entered
  from either the device step or the encryption step and «one more» does not land
  in the same place from both.
- **`_ok_destino` returns False until a way out is chosen**, so «Siguiente» stays
  dark next to the two buttons. Three ways forward with two destinations is the
  confusion the wizard's disabled-until-resolved idiom exists to prevent.

The short path installs the tree the **installer itself carries** (`bundle_dir()`,
the same source step 5 uses) — no network, no catalogue, no connection. The
GitHub-fetching updater is `common/update.py`, reached from the main window; here
the answer to "which code" is "the one in your hand". It calls
`ensure_control_file(renew=False)`, and that `False` matters: step 5 renews
because it is provisioning a device, and renewing here would strand a watcher
already bound to this device's id. Going backwards in version is allowed but
never silent — `_confirmar_retroceso()`.

With VeraCrypt `.prdrive/` lives *inside* the container, so the volume is
indistinguishable from an empty one until it is mounted. The detection therefore
runs again at the end of `_paso_cifrado`, which is the first moment it can
succeed.

**Step 5 no longer simulates first.** It used to be an `rclone sync` of a master
mirror, i.e. something that deleted in the destination whatever was not in the
source, and that is why it demanded a `--dry-run` and typing the path by hand.
Now it copies a folder of its own and touches nothing else, so it runs straight
through `ui.tk.working()` — a job that takes a while (the rclone binary is tens of
MB) and whose output tells nobody anything.

**The `Conexión` step is what makes the repo publishable.** `profile.load()` returns an
**empty** profile when there is nothing embedded and nothing in the checkout, and
that is not an error — it is the normal start for someone who just cloned. Before,
that path raised `InstallError` and the wizard died explaining that a key was
missing that the user had never had.

`install.InstallError` is raised instead of `sys.exit` for the same reason as
`model.ConfigError`: with a wizard open, killing the process closes the window in
the user's face instead of letting them read what happened and retry. The private
key is written to a temp directory that records the owning pid;
`remote.sweep_stale()` cleans up the ones left by installers that were killed hard
(no `atexit`, no signal handler), and asks `store.pid_alive()` before touching any
of them so two concurrent installs do not rob each other.

**The key never leaves the device.** `deploy.write_device_remote()` writes
`.prdrive/rclone.conf` and `.prdrive/keys/<name>` with **relative** paths
(`key_file = keys/…`), which is what makes the device work under any drive letter
— rclone resolves them against its cwd, which the project always fixes at
`model.APP_DIR`. Nothing mirrors `.prdrive/`, so the key stays put, protected by
whatever protects the volume.

**Updating a device in place (`common/update.py` + `ui/tk_update.py` +
`prdrive-install.py --update`).** The main window shows an amber block when
GitHub has a newer release, and its button does the whole thing. Three decisions
hold it up, and none of them is arbitrary:

- **The applier runs from the download, not from the device.** `install/` is
  deliberately absent from a provisioned device, so on-device code cannot call
  `deploy_code()`. The source zip of the tag does carry it, so the update runs
  `python <extracted>/prdrive-install.py --update <volume>` — **the new version
  installs itself**. The alternative, an applier living in `common/`, would be a
  second copy of the "what is the deployed tree" manifest, and it would be the
  one to fall behind the day a file is added.
- **The payload is the source zip of the tag (~270 KB), not the release `.exe`
  (12.6 MB).** The CI-built exe is generic — no embedded profile — so re-running
  it would ask for the connection again to do what is really a `copy2` of the
  code.
- **`.prdrive/` is never renamed.** `deploy_code()` copies file by file, and the
  stage-and-swap that looks tidier is worse here in three concrete ways:
  `rclone.exe` may be running from `.prdrive/bin/` (Windows will not rename its
  directory, and `catalog.run` holds `cwd=APP_DIR` for the length of a call); if
  `.prdrive/runsync.py` vanishes for even an instant, penwatch loses its
  `STRUCT_MARKER`, **re-arms its trigger and relaunches the UI on its own**
  within 5-15 s; and if `sync_config.toml` vanishes, a running service shuts
  itself down. Copying costs one thing — a module deleted upstream lingers on
  old devices — and that is exactly what re-running the installer already did.

`VERSION` at the repo root is the whole versioning story: it is in
`DEPLOY_FILES` and in `DATOS_FICHEROS`, `install.version()` reads it out of
`bundle_dir()` (there is no `__version__ = "3.0"` constant any more — it had
drifted from the tags), `update.installed_version()` reads it out of `APP_DIR`,
and the release workflow is **triggered by a push to `main` that touches
`VERSION`** and takes `v<VERSION>` as the tag rather than being told one — the
tag cannot disagree with the file because there is nowhere left to say it twice.
If that tag already exists there is no new version: a push exits green doing
nothing, a manual `workflow_dispatch` (the retry hatch) fails saying so. A
device with no `VERSION` is one installed before this existed: it reads as
unknown, which compares older than anything, which is correct.

`update.fetch()` is a module-level function for the same reason `catalog.run()`
is: every test replaces it, and **no test touches the network**. Same for
`state_file()` being a function — `sandbox()` rebinds `model.STATE_DIR` hot, and
a constant computed at import would point at the real device. Note `sandbox()`
does **not** rebind `APP_DIR`, which is why everything that writes takes its
destination explicitly (`download(tag, destino)`, `deploy_code(device_root, …)`).

`check()` never raises and honours a 24 h cache in `state/update.json`;
`pending()` reads that cache and **never** goes to the network, because it is
what the first paint asks. The window refreshes it on a thread after
`deiconify()`; `daemon_cycle()` refreshes it too, which is the only thing keeping
it current for the console menu. The console prints its own notice in
`console.main_menu` rather than riding `startup_msg` — that channel is shared by
both frontends and the window already draws its own, so it would show twice.

What a download has to survive before it is allowed near the device: TLS,
the zip CRC, every name in `update.OBLIGATORIOS` present, no member whose path
escapes the destination (`extractall` is the footgun; `_ruta_segura` checks the
names), and **the `VERSION` inside matching the tag asked for**. There is no
signature, and the README says so plainly rather than implying otherwise.

**Mount watcher (`penwatch.py`).** Third entry point, and the only one that
installs anything on the host. `install` copies the script to
`%LOCALAPPDATA%\prdriveWatch` / `~/.local/share/prdrive-watch`, writes `watch.json`
there and registers a **per-user** logon-triggered Task Scheduler task (XML via
`schtasks /Create /XML`, UTF-16 — UTF-8 is rejected; `DisallowStartIfOnBatteries`
must stay `false` or laptops never start it) or a systemd **user** unit
(`WantedBy=default.target`, plus `loginctl enable-linger`). No admin rights
anywhere. The watcher **polls** rather than subscribing to device events, because
on an encrypted device the arrival event fires long before the volume is readable —
what matters is "already readable", which is only knowable by trying. It
identifies the device by the control file **`.prdrive/PRDRIVE`** (optional
`id=<hex>` line inside), never by drive letter or mount point, and confirms
`.prdrive/runsync.py` before launching. It must never write to, or `chdir`
into, the device (that blocks safe ejection): its config, state and log live on the
host, and every device access is wrapped in `try/except OSError` because a locked
BitLocker volume errors rather than reporting "not found". It fires once per
mount — the trigger re-arms only when the device disappears. `--mode` decides what
runs: `ui` (default), `sync`, or `daemon` (→ `runsync.py --auto`).

**The catalogue is the source of truth for what pairs exist
(`common/catalog.py` + `ui/catalog_editor.py`).** `nas:/prdrive-catalog/pairs.toml`
is a file with the *same schema* as `sync_config.toml`, shared by every device, and
`prdrive-install.py` reads it to provision a new device. **A pair is created or
deleted there first**; each device then only *chooses* which of them it uses. That
split is the whole point and must not be collapsed back:

- **Catalogue side** (`plan_catalog_save`/`plan_catalog_remove`/`plan_catalog_defaults`)
  writes the remote and changes nothing on this device. **No pair is sacred any
  more**: when the code came down from the remote, the pair describing that mirror
  was required to install and the editor refused to delete it. The installer now
  carries the code, so the catalogue is data pairs and they are all equal.
- **Device side** (`plan_enable`/`plan_remove`/`plan_override`/`plan_revert`) writes
  `sync_config.toml` and never touches the remote. `[defaults]` is catalogue-governed
  too, via `plan_defaults`/`plan_revert_defaults`.

`sync_config.toml` still holds **complete** pair entries, not references: `sync.py`
must keep working with no network, and its schema did not change. Provenance is
therefore *derived*, not stored — `catalog.diff_keys()` compares the local entry
against `state/catalog.toml` (the last successful pull) to produce
`catálogo` / `modificada aquí` / `huérfana` / `sin usar`. **Do not add a
`from_catalog`-style key to the TOML**: `config_file.save()` demands strict
round-trip equality and the file is hand-editable.

Writing the catalogue is the riskiest thing in the project, so `catalog.push()`:
generates and verifies the text first (`config_file.dumps_checked`), **re-reads the
remote and refuses if it changed** since it was read (another device may have edited
it), copies `pairs.toml` → `pairs.toml.bak` on the remote, and only then uploads.
Rewriting keeps the header block and **loses the interleaved comments** — a
deliberate trade for reusing the serializer that refuses to write what it cannot
read back. `catalog.load()` never raises: no network falls back to
`state/catalog.toml`, and a cached catalogue is **not editable** (`Catalog.editable`),
because you cannot safely overwrite what you have not just read. `catalog.run()` is a
module-level function precisely so every test replaces it — **no test may touch the
network**. `catalog.NET_FLAGS` keeps a dead remote from freezing the window for
minutes.

The catalogue also carries an optional **`[remote]`** table: the non-secret
definition of the rclone remote itself (type, host, user…). It is what makes the
connection typed **once** — the first device writes it there and the rest inherit
it. `profile.align_with_catalog()` applies it, and it enforces one rule that is
not negotiable: **the catalogue decides the remote's name**, because every pair's
`remote_path` resolves against `[defaults].remote`. If the device's rclone.conf
called the remote something else, every sync would fail with an "unknown remote"
that looks nothing like the cause. The private key never goes in there.

**Editing pairs from the UI (`ui/pair_editor.py`) — the dangerous part.**
`bisync.expected_prefix()` is derived from `local`, `remote`, `remote_path` and
`mode`. Change any of them and the expected listing name changes, so on the next
run `normalize_prefix()` would **rename the old baseline to the new name** —
telling bisync that a listing of the *previous* destination describes the *new*
one. Everything missing from the new side then reads as deleted and propagates,
with `--max-delete 25` as the only brake. `normalize_prefix()` was written for the
benign case (device moves from `G:` to `F:`) and cannot tell the two apart.

So the editor shelves the baseline itself: `bisync.shelve_baseline()` renames
`state/<pair>/` to `state/<pair>.old-<date>/`, which leaves the pair `fresh` and
forces an explicit `--resync`. Shelved directories are inert because everything
that scans `state/` only looks at its top level.

Renaming a pair is the opposite case and is free: the prefix does **not** depend
on the pair name, only the paths do, so `bisync.rename_pair_state()` moves
`state/<name>/` and `filters/<name>.*` together (the `.md5` must travel with its
file) and the baseline stays valid.

**The decision is taken by comparing prefixes, not keys.** `_prefixes(raw)` parses
both the before and after configs and compares `bisync.expected_prefix()` per pair;
`ENDPOINT_KEYS` now only produces the human-readable message. That is what makes
`[defaults]` editable at all: `remote` and `device_remote` feed *every* pair's
endpoints, so one change there can invalidate several baselines with no pair having
been touched — which is why `EditPlan.shelve` is a **list**. A prefix that
*disappears* (bisync → another mode) also shelves: leaving an unchecked baseline
behind is exactly how you set up the dangerous case for the day it goes back.

`plan_*()` return an `EditPlan` **without touching anything**; its `consequences`
are shown before confirming. `EditPlan.execute()` does the disk surgery **before**
writing the config, and undoes it if the write fails: the combination to avoid is
"new config, old baseline", and this ordering can only ever fail towards "baseline
shelved for nothing", which a `--resync` fixes. Within the disk step, **rename runs
before shelve**, so an edit that changes the name *and* an endpoint moves state and
filters to the new name first and shelves that; the other order orphaned
`filters/<old name>.txt`.

**The flags editor (`ui/flags_editor.py`).** Flags are still written in TOML
syntax — the dialog is a text box, not a form of one row per flag — and the text
is parsed with **`tomllib`, not by hand**: its destination is a `[pair.flags]`
table, so the only way for the form and the file to mean the same thing is to use
the same parser. `dump()` renders through `config_file.dumps_table()` for the same
reason. Only what the serializer can write back is accepted (scalars and arrays of
scalars), because `save()` refuses to write a config that does not re-read equal
and that refusal would arrive with the dialog already closed. `RESERVED` rejects
the flags `sync.py` supplies per run and the filter ones derived from
include/exclude: repeating them does not replace them, and a second `--workdir` or
`--filters-file` points bisync at a baseline that is not its own.

`effective()` is the point of the whole thing — the four layers resolved into what
rclone would actually receive, each row labelled with the layer it came from — and
`warnings()` compares **merged** flag sets, never one layer, so it catches
`--max-delete` rising because the pair's own value was deleted or because the mode
changed, with no flag having been touched. Editing flags never shelves a baseline:
the listing name does not depend on them.

`ui/tk_pairs.flags_form()` is the drawing half; it does **not** close on invalid
input (losing what was typed, or saving only the part that parsed, is exactly what
must not happen here). Both the pair form and the `[defaults]` form open it, and
`pair_editor.merge_form()` — shared with `catalog_editor` — is what makes an
emptied box actually delete the key instead of leaving it half written.

**Writing the TOML (`common/config_file.py`).** `tomllib` only reads and the
project takes no dependencies, so the serializer is hand-rolled. It covers what
the schema uses: scalars, string arrays and one nested `flags` table. Two things
to preserve: `[pair.flags]` binds to the **last** `[[pair]]` written, so it is
emitted right after its own pair and never at the end; and `dumps_checked()`
re-parses what it just generated and refuses to write if it does not reproduce the
same dict — this file governs deletions, so failing loudly beats writing something
that does not read back. `save()` and `catalog.push()` both go through it. Work on
the **raw dict**, never on `model.Config`: its `Pair`s arrive with the `[defaults]`
already merged in. `header_of(text)` exists because some headers never touch this
disk: the catalogue arrives from the remote as text, and the installer hands
`save(head=...)` the header of a config whose file does not exist yet — the
default, `head=None`, keeps whatever header the target already had, which is what
editing pairs needs.

**penwatch from the UI.** `penwatch.py` keeps its `cmd_*` functions but they now
print rows produced by `status_rows()`/`probe_rows()`/`log_tail()`, so the CLI and
the UI show the same thing without parsing text. `ui/watch.py` imports penwatch
for reads and shells out for `install`/`uninstall`, whose output goes to the same
`output_window` used for `sync.py`. The dependency is one-way and must stay that
way: penwatch is copied to the host and has to work with the device unplugged.

## Conventions

- All comments, docstrings and user-facing output are **Spanish**. Keep it that way.
- Comments explain *why* against rclone's actual behaviour, often citing the rclone
  source file. Preserve that when touching bisync-related code.
- `sync_config.toml` is per-device: `prdrive-install.py` generates it from the remote
  catalogue when provisioning, and from then on the pairs screen maintains it. It
  can still be edited by hand — a pair that ends up differing from the catalogue is
  reported as "modificada aquí", not corrected.

## Documentation

Two documents, two audiences, and they must not drift into each other:

- **`README.md`** (this folder) is the front door of a public repository and the
  thorough one: the three-piece model, install, the flag layering, how bisync's
  baseline actually works and why the ugly parts exist, the service, the watcher,
  the security model, the architecture. Someone deciding whether to use or hack
  on this reads it.
- **`device-readme.md`** is the *light* quick guide, and it is **not** for
  readers of the repo: the installer copies it to the volume root as `README.md`
  (`deploy.write_guide()`), so it is what the user finds when they open the
  drive. Keep it short, task-shaped and free of internals. It used to live at the
  volume root and travel through the master mirror; with no mirror, either the
  installer writes it or it never arrives.

`write_guide()` is deliberately best-effort — it returns None if the template is
not in the bundle instead of raising. It is documentation, and a missing document
cannot abort an install that otherwise went fine; same criterion as `hide()` and
`icons.get()`. `build_installer.py` does list it in `DATOS_FICHEROS`, so a build
that forgets it fails loudly at compile time, which is the right place.

`sync_config.example.toml` is tracked and is the schema reference for **both**
files that use it — a device's `sync_config.toml` and the remote's `pairs.toml`
(which additionally takes `[remote]`). It is verified by hand with
`config_file.dumps_checked()`: if it stops round-tripping, the serializer and the
documented schema have drifted apart.

`LICENSE` is the Apache License 2.0, verbatim from apache.org, with the
appendix's copyright line filled in. `README.md`'s «Licencia» section points at
it; keep the two in step.

Nothing is left to settle before the repo goes public. The history is clean on
both counts checked: every commit on every ref is authored **and** committed by
`jeremaya <peredev@pm.me>` (verified with `git log --all --format='%an <%ae> |
%cn <%ce>'`), and no key, config or state file has ever been committed (verified
with `git log --diff-filter=A`).
