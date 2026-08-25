# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Portable two-way sync between a Synology NAS (SFTP) and a USB pen drive, driven by
a bundled `rclone` binary. Pure Python **stdlib**, Python 3.11+ (`tomllib`). No
build, no dependencies, no test suite, no package manifest.

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
```

`runsync.py` with no args always **stops a previously started service** first.
Verification is by `--doctor` and `--dry-run`; there is nothing to lint or test.

Git note: the repo sits on an exFAT/NTFS pen, so git refuses it as "dubious
ownership" — prefix commands with `-c safe.directory=F:/rclone-sync`. There are no
commits yet, no remote, and `.gitignore` excludes everything device-specific
(`bin/`, `keys/`, `filters/`, `logs/`, `state/`, `sync_config.toml`,
`rclone.conf`), so only `sync.py`, `runsync.py` and `README.md` are tracked.

## Architecture

`sync.py` is the engine, `runsync.py` is a launcher that imports it (`import sync`)
and reuses `load_config`, `STATE_DIR`, `pair_needs_resync`. It never re-implements
sync logic: it shells out to `sync.py <pair>` per pair.

**Config → command.** `sync_config.toml` has `[defaults]` + one `[[pair]]` each.
`MODES` maps `mode` → (rclone subcommand, source end, dest end):
`bisync|up|down|up-mirror|down-mirror`. `build_command()` merges flags in layers,
last wins: `BASE_FLAGS` < `MODE_DEFAULT_FLAGS[mode]` < `[defaults.flags]` <
`[pair.flags]`, then `flags_to_args()` turns `key = value` into `--key value`
(`true` → bare flag, `false`/`None` → dropped, list → repeated flag, `_` → `-`).
**Adding an rclone flag means editing the TOML, never `sync.py`.** The script owns
`--config`, `--log-file`, `--dry-run`, `--workdir`, `--resync`; `extra_flags` is
the raw-string escape hatch.

**Why the ugly parts exist** (all of it is about bisync's baseline; the comments in
`sync.py` cite the rclone sources they replicate):

- *Session prefix.* bisync names its listings after the two endpoint strings.
  `canonical_path`/`session_name`/`expected_prefix` replicate
  `cmd/bisync/bilib/canonical.go` so the script knows the filename rclone will look
  for **before** running. `normalize_prefix()` renames an existing listing set when
  it no longer matches (pen mounted as `E:` instead of `F:`); `heal_listings()` is
  the fallback that parses the `Tip: Path1/Path2` lines out of a failed log and
  retries **once**. Current state files are `F__sync-data_...` — drive-letter bound.
- *`pen_remote`.* Setting `pen_remote = "pen"` in `[defaults]` makes the pen side a
  `combine` remote defined via `RCLONE_CONFIG_<NAME>_TYPE/_UPSTREAMS` env vars
  (`pen_environment()`, computed from **all** pairs so it is identical whatever you
  run), making the prefix machine-independent. An `alias` remote does *not* work —
  it returns the target Fs itself and the absolute path reappears. Not enabled in
  the current `sync_config.toml`.
- *Filters.* For `bisync` only, `filters_file_for()` generates
  `filters/<pair>.txt` from the TOML include/exclude patterns and passes
  `--filters-file`; in that case `--include/--exclude` are **not** also emitted
  (duplicate rules break change detection). bisync stores the md5 beside the file
  and only rewrites it during `--resync`, so `filters_state()` compares the hash
  itself and reports "needs resync" instead of letting rclone abort.
- *State.* One workdir per pair, `state/<pair>/`; `migrate_legacy_state()` moves the
  old flat layout. `pair_state()` returns `fresh|ok|broken` from the actual `.lst`
  files (`.lst-err` residue is ignored when a valid pair of listings exists).
- *Resync approval.* `resolve_resync_approval()` asks **once** for all pairs before
  anything runs. `ask_yes_no()` returns the default when stdin is not a tty, so
  non-interactive runs skip those pairs (`SKIPPED = -1`, distinct from rc 0/failure)
  rather than resyncing unattended.

**Safety invariants — do not weaken:**

- If a bisync baseline exists but the local path does **not**, `run_pair()` aborts
  instead of creating the folder: an empty local side reads as "everything was
  deleted". Only pairs without a baseline get their local dir created.
- `max-delete` defaults (25 bisync / 50 mirror) exist for the same reason.
- rclone always runs with `cwd = SCRIPT_DIR` because `rclone.conf` uses paths
  relative to it (`key_file`, `known_hosts_file`) to stay portable.
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
was chosen by hand. `save_prefs` stores `known` (the pair names that existed at
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

## Conventions

- All comments, docstrings and user-facing output are **Spanish**. Keep it that way.
- Comments explain *why* against rclone's actual behaviour, often citing the rclone
  source file. Preserve that when touching bisync-related code.
- `sync_config.toml` is per-device and generated by `perepen-install.py` (not in
  this repo) from a catalogue on the NAS; it can be edited by hand.

## Documentation

The authoritative manual is the **pen root** `../README.md` (13 sections: daily use,
service, modes, config, filters, bisync internals, troubleshooting, security). The
`README.md` inside this folder is an older version and has drifted — it predates
`--doctor`, `runsync.py`, `pen_remote`, per-pair filter files, the `state/<pair>/`
layout and the "logs only on failure" policy. When changing behaviour, update
`../README.md`, and either update or stop extending the local one.
