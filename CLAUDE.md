# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Portable two-way sync between a Synology NAS (SFTP) and a USB pen drive, driven by
a bundled `rclone` binary. Pure Python **stdlib**, Python 3.11+ (`tomllib`). No
build, no dependencies, no package manifest. Tests are plain scripts under
`tests/` — `python tests/run_all.py`, no framework, nothing touches the pen.

Three entry points stay at the repo root because the pen-root launchers
(`runsync.pyw`/`.bat`/`.sh`) and `penwatch.py` locate them by fixed path;
everything else is split by what it knows about:

```
rclone-sync/
├── sync.py            entry point: build the rclone command, run it, report
├── runsync.py         entry point: the periodic service + who calls what
├── penwatch.py        entry point: mount watcher (deliberately self-contained)
├── common/            knows the config and rclone
│   ├── model.py       sync_config.toml parsed into resolved objects
│   ├── bisync.py      everything that replicates rclone bisync's internals
│   ├── config_file.py reads AND writes sync_config.toml (hand-rolled serializer)
│   ├── catalog.py     the global pair catalogue on the NAS: read, cache, write
│   └── store.py       the pen's JSON state files: tolerant reads, atomic writes
├── ui/                knows how to ask the user and show results
│   ├── __init__.py    Choice, the Frontend protocol, start(), fatal()
│   ├── prefs.py       what the UI starts preloaded with (state/ui_prefs.json)
│   ├── pair_editor.py what THIS pen does with pairs — the decisions, no Tk
│   ├── catalog_editor.py  add/edit/remove in the NAS catalogue — no Tk
│   ├── watch.py       adapter over penwatch.py — no Tk
│   ├── tk.py          TkFrontend: main window, output window, modal()/mostrar()
│   ├── tk_pairs.py    the pairs screen (drawing only)
│   ├── tk_watch.py    the auto-start screen (drawing only)
│   └── console.py     ConsoleFrontend: the text menu
└── tests/             plain scripts; run_all.py runs them in separate processes
```

The `tk_*` modules only draw. Everything that decides or touches disk lives in
`pair_editor.py` / `catalog_editor.py` / `watch.py`, which import no Tk and are
tested headlessly.

`perepen-install.py` also sits at the root and **is** tracked in git. It is
deliberately autonomous — one file, stdlib only, no imports from `common/`/`ui/`
— because it runs before any pen exists, from the NAS, with an embedded SFTP key.
It duplicates `BASE_FLAGS`, `flags_to_args` and a TOML emitter on purpose; don't
"fix" that by making it import the package.

`penwatch.py` must NOT import either package: it is copied to the host and has to
keep working with the pen unplugged.

The repo is the `rclone-sync/` folder of the pen; `PEN_ROOT` is its **parent**
directory (`F:\` here). Everything is resolved relative to the script location so
the drive letter never matters.

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
python penwatch.py status      # what is registered + whether the pen is visible now
python penwatch.py probe       # detection only: candidate roots and what matched
python penwatch.py uninstall

python tests/run_all.py        # todos los tests (scripts sueltos, sin framework)
python tests/test_pair_editor.py   # o uno solo
```

`runsync.py` with no args always **stops a previously started service** first.
Verification is by `tests/run_all.py`, `--doctor` and `--dry-run`; there is
nothing to lint.

Git note: the repo sits on an exFAT/NTFS pen, so git refuses it as "dubious
ownership" — prefix commands with `-c safe.directory=F:/rclone-sync`. There is no
remote, and `.gitignore` excludes everything device-specific (`bin/`, `keys/`,
`filters/`, `logs/`, `state/`, `sync_config.toml`, `rclone.conf`), so what is
tracked is the code (`sync.py`, `runsync.py`, `penwatch.py`, `perepen-install.py`,
`common/`, `ui/`, `tests/`) plus `README.md`, `CLAUDE.md` and `.gitignore`. The
catalogue cache (`state/catalog.toml`, `state/catalog.json`) is ignored with the
rest of `state/`, and the `perepen` pair already excludes `rclone-sync/state/**`,
so it never travels to the NAS either.

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
- `Config` — the pairs plus `[daemon]`, `keep_logs`, `pen_remote`, with
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
what depends on *this* run, and `flags_to_args()` turns `key = value` into
`--key value` (`true` → bare flag, `false`/`None` → dropped, list → repeated flag,
`_` → `-`). **Adding an rclone flag means editing the TOML, never the code.** The
script owns `--config`, `--log-file`, `--dry-run`, `--workdir`, `--resync`;
`extra_flags` is the raw-string escape hatch.

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
  it no longer matches (pen mounted as `E:` instead of `F:`); `heal_listings()` is
  the fallback that parses the `Tip: Path1/Path2` lines out of a failed log and
  retries **once**. Current state files are `F__sync-data_...` — drive-letter bound.
- *`pen_remote`.* Setting `pen_remote = "pen"` in `[defaults]` makes the pen side a
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
  the mode guard lives inside it now, so no caller can forget it.
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
- rclone always runs with `cwd = model.APP_DIR` (i.e. `rclone-sync/`, **not** the
  package dir) because `rclone.conf` uses paths relative to it (`key_file`,
  `known_hosts_file`) to stay portable. `model.APP_DIR` is
  `Path(__file__).parent.parent` precisely because `model.py` sits one level down;
  `PEN_ROOT` hangs off it. Moving these files changes those anchors.
- The `perepen` pair is `up-mirror` of the **whole pen** to the NAS; it deletes on
  the remote. Never exercise it without `--dry-run`.

**Logs.** rclone always writes to a temp file; `dispose_log()` keeps it in `logs/`
only when the run failed (or `--keep-logs` / `keep_logs = true`), to spare write
cycles on the pen. On failure the tail is printed and `KNOWN_ERRORS` maps rclone
messages to an explanation — add new cases there rather than in the caller.

**Daemon (`runsync.py`).** Coordination lives in `state/` so it travels with the
pen: `daemon.lock.json` (pid/host/pairs/last cycle, written atomically),
`daemon.stop` (presence = stop request), `daemon.log` (self-trimming),
`ui_prefs.json` (last UI choice). `startup_defaults()` layers that memory over
`daemon_defaults()`: last choice > `[daemon]` in the TOML > all pairs / 30 min,
and it feeds both the UI prefill and `--auto`'s no-argument case. Only the UI
writes it (`save_prefs()` from `ui_flow`, for `manual`/`daemon` — not `doctor`);
`--auto` and `--daemon` only read, so an automatic start never overwrites what
was chosen by hand. `store.read_json`/`write_json` are the shared primitives under
both the lock and the prefs.

**UI (`ui/`).** Two frontends implement the same four operations (`ask`,
`approve_resync`, `info`, `run_sync`), and `ui.start(config, msg)` returns the
choice **together with the frontend that took it** — whoever asked is who knows
how to show the answer, since a window cannot dump output to a console that does
not exist and vice versa. Both return `Choice(action, pairs, minutes)`, so callers
read `choice.action` instead of indexing a variable-length tuple.

`ConsoleFrontend.approve_resync` always returns False on purpose: with a real
terminal, `sync.py` inherits stdin and asks the question itself, with more context
than a dialog fits. Returning True there would append `--yes` and take that
conversation away from the user.

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

**`import tkinter` always goes inside the functions, never at module top level.**
`ui/` is imported by the headless paths too (`--auto`, the service), where tkinter
may not be installed and there may be no display; the failure has to surface when
the window is opened, which is when `ui.start()` can catch it and fall back to the
console menu. Verified in both directions. `save_prefs` stores `known` (the pair names that existed at
the time) so a pair added to the TOML later reads as new — and comes back
checked — instead of as one the user had unchecked; it skips the write entirely
when nothing changed, to spare the pen. A record whose pairs are all gone falls
back to the TOML silently.

The service
stops when the pen disappears (`SENTINEL` check) or when runsync is launched again.
Windows specifics that must be preserved: `pid_alive()` uses `OpenProcess`, never
`os.kill` (which *terminates* on Windows); the daemon is spawned with `pythonw.exe`
+ `CREATE_NO_WINDOW`, and rclone is spawned with `CREATE_NO_WINDOW` too, otherwise
every invocation flashes a console window; the daemon `chdir`s to the temp dir so
the pen can be safely ejected. Child `sync.py` runs get `stdin=DEVNULL` on purpose,
so a pair needing `--resync` is skipped instead of resynced unattended.

**Mount watcher (`penwatch.py`).** Third entry point, and the only one that
installs anything on the host. `install` copies the script to
`%LOCALAPPDATA%\PerePenWatch` / `~/.local/share/perepen-watch`, writes `watch.json`
there and registers a **per-user** logon-triggered Task Scheduler task (XML via
`schtasks /Create /XML`, UTF-16 — UTF-8 is rejected; `DisallowStartIfOnBatteries`
must stay `false` or laptops never start it) or a systemd **user** unit
(`WantedBy=default.target`, plus `loginctl enable-linger`). No admin rights
anywhere. The watcher **polls** rather than subscribing to device events, because
on an encrypted pen the arrival event fires long before the volume is readable —
what matters is "already readable", which is only knowable by trying. It
identifies the pen by the control file **`PEREPEN` at the volume root** (optional
`id=<hex>` line inside), never by drive letter or mount point, and confirms
`rclone-sync/runsync.py` before launching. It must never write to, or `chdir`
into, the pen (that blocks safe ejection): its config, state and log live on the
host, and every pen access is wrapped in `try/except OSError` because a locked
BitLocker volume errors rather than reporting "not found". It fires once per
mount — the trigger re-arms only when the pen disappears. `--mode` decides what
runs: `ui` (default), `sync`, or `daemon` (→ `runsync.py --auto`).

**The catalogue is the source of truth for what pairs exist
(`common/catalog.py` + `ui/catalog_editor.py`).** `synology:/PJ/Perepen-catalog/pairs.toml`
is a file with the *same schema* as `sync_config.toml`, shared by every device, and
`perepen-install.py` reads it to provision a new pen. **A pair is created or
deleted there first**; each pen then only *chooses* which of them it uses. That
split is the whole point and must not be collapsed back:

- **Catalogue side** (`plan_catalog_save`/`plan_catalog_remove`/`plan_catalog_defaults`)
  writes the NAS and changes nothing on this pen. `perepen` cannot be deleted from
  the catalogue — `perepen-install.py` aborts without it.
- **Pen side** (`plan_enable`/`plan_remove`/`plan_override`/`plan_revert`) writes
  `sync_config.toml` and never touches the NAS. `[defaults]` is catalogue-governed
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
remote and refuses if it changed** since it was read (another pen may have edited
it), copies `pairs.toml` → `pairs.toml.bak` on the NAS, and only then uploads.
Rewriting keeps the header block and **loses the interleaved comments** — a
deliberate trade for reusing the serializer that refuses to write what it cannot
read back. `catalog.load()` never raises: no network falls back to
`state/catalog.toml`, and a cached catalogue is **not editable** (`Catalog.editable`),
because you cannot safely overwrite what you have not just read. `catalog.run()` is a
module-level function precisely so every test replaces it — **no test may touch the
network**. `catalog.NET_FLAGS` keeps a dead NAS from freezing the window for minutes.

**Editing pairs from the UI (`ui/pair_editor.py`) — the dangerous part.**
`bisync.expected_prefix()` is derived from `local`, `remote`, `remote_path` and
`mode`. Change any of them and the expected listing name changes, so on the next
run `normalize_prefix()` would **rename the old baseline to the new name** —
telling bisync that a listing of the *previous* destination describes the *new*
one. Everything missing from the new side then reads as deleted and propagates,
with `--max-delete 25` as the only brake. `normalize_prefix()` was written for the
benign case (pen moves from `G:` to `F:`) and cannot tell the two apart.

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
`[defaults]` editable at all: `remote` and `pen_remote` feed *every* pair's
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

**Writing the TOML (`common/config_file.py`).** `tomllib` only reads and the
project takes no dependencies, so the serializer is hand-rolled. It covers what
the schema uses: scalars, string arrays and one nested `flags` table. Two things
to preserve: `[pair.flags]` binds to the **last** `[[pair]]` written, so it is
emitted right after its own pair and never at the end; and `dumps_checked()`
re-parses what it just generated and refuses to write if it does not reproduce the
same dict — this file governs deletions, so failing loudly beats writing something
that does not read back. `save()` and `catalog.push()` both go through it. Work on
the **raw dict**, never on `model.Config`: its `Pair`s arrive with the `[defaults]`
already merged in. `header_of(text)` exists because the catalogue arrives as text,
not as a file.

**penwatch from the UI.** `penwatch.py` keeps its `cmd_*` functions but they now
print rows produced by `status_rows()`/`probe_rows()`/`log_tail()`, so the CLI and
the UI show the same thing without parsing text. `ui/watch.py` imports penwatch
for reads and shells out for `install`/`uninstall`, whose output goes to the same
`output_window` used for `sync.py`. The dependency is one-way and must stay that
way: penwatch is copied to the host and has to work with the pen unplugged.

## Conventions

- All comments, docstrings and user-facing output are **Spanish**. Keep it that way.
- Comments explain *why* against rclone's actual behaviour, often citing the rclone
  source file. Preserve that when touching bisync-related code.
- `sync_config.toml` is per-device: `perepen-install.py` generates it from the NAS
  catalogue when provisioning, and from then on the pairs screen maintains it. It
  can still be edited by hand — a pair that ends up differing from the catalogue is
  reported as "modificada aquí", not corrected.

## Documentation

The authoritative manual is the **pen root** `../README.md` (14 sections: daily use,
service, modes, config, filters, bisync internals, troubleshooting, security). The
`README.md` inside this folder is an older version and has drifted — it predates
`--doctor`, `runsync.py`, `pen_remote`, per-pair filter files, the `state/<pair>/`
layout and the "logs only on failure" policy. When changing behaviour, update
`../README.md`, and either update or stop extending the local one.
