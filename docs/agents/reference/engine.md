# Engine: config → command, bisync, logs

Files: `sync.py`, `common/model.py`, `common/bisync.py`, `common/config_file.py`.
Formerly AGENTS.md «Architecture», «bisync», «Logs and live progress», «Writing the TOML».
The safety invariants (missing local dir, `max-delete`, mirrors) stay in AGENTS.md.

## Process split

`sync.py` is the engine. `runsync.py` never imports it: it reads config via `common.model` and shells out to `model.SYNC_PY <pair>` per pair, so they share no in-process state.

## Parse once, at the boundary

`model.parse_config()` turns the TOML into frozen `Mode`/`Pair`/`Config`. Nothing downstream re-reads TOML keys, repeats `.get(key, default)` or threads `defaults` through signatures. New mode = one `Mode(...)` in `MODES`; an invalid one fails at parse time, so a typo stops `--list`/`--doctor`/runs alike.

Validation raises **`model.ConfigError`**, never `sys.exit`: the UI shares the model and exiting would close the window. CLI entry points catch it and exit with its message. `install.InstallError` exists for the same reason.

## Config → command

Flags merge last-wins inside `model._build_pair`: `BASE_FLAGS` < `Mode.flags` < `[defaults.flags]` < `[pair.flags]`. `Pair.flags` arrives ready; `build_command()` adds only what depends on *this* run.

`model.flags_to_args()`: `key = value` → `--key value` (`true` → bare flag, `false`/`None` → dropped, list → repeated, `_` → `-`). It lives in `model.py` so the UI can show a flag's effect without importing the engine.

**A new rclone flag = edit the TOML, never code.** The script owns `--config`, `--log-file`, `--dry-run`, `--workdir`, `--resync`; `extra_flags` is the raw-string escape hatch. `RunContext` holds what is constant across the pairs of one invocation.

## bisync (`common/bisync.py`)

The one place that imitates rclone's behaviour; each section cites the rclone source it mirrors. **Preserve the citations.**

- **Session prefix.** `canonical_path`/`session_name`/`expected_prefix` replicate `cmd/bisync/bilib/canonical.go`, so the listing name is known **before** running. Used only by `pair_editor` (does this baseline still belong to this pair?) and `--doctor`.
- **`device_remote`, on by default** (`DEFAULT_DEVICE_REMOTE = "disp"`; `deploy.device_config()` `setdefault`s it into each new device's `[defaults]`). It makes the device side a `combine` remote via `RCLONE_CONFIG_<NAME>_TYPE/_UPSTREAMS` (`Config.pen_environment()`, built from **all** pairs), so the prefix is machine-independent; `alias` does not work. It belongs to the **device's** defaults: in the catalogue it would move every installed device's prefix at once.
- **Quoting `upstreams`.** rclone parses it as an `fs.SpaceSepList` (`fs/types.go`): space-separated CSV, a field quoted only if it **starts** with a quote. So the quotes wrap the whole `name=path`, never just the path: `.="F:\"` gives `bare " in non-quoted-field` and takes **every** pair of the device down. They exist for a drive root's trailing backslash and for spaces. `model._upstream()` is the only builder.
- **The device root needs a named upstream.** rclone cleans the path first, so `local = "."` becomes upstream `""` and fails with `combine for remote "": directory not found`. `model.RAIZ_UPSTREAM` (`"raiz"`) names it, hence `top_level_dir` (the name) and `top_level_abs` (the folder). The name is part of the prefix: changing it invalidates those baselines.
- **No listing rename** (`normalize_prefix`, `rename_prefix`, `heal_listings` were deleted with `device_remote`). Renaming a listing set tells bisync that a listing of the *previous* destination describes the *new* one, and the benign case is indistinguishable from the malignant. Legacy devices are fixed by hand; no migration code. `tests/test_bisync_prefijo.py` asserts the absence and guards both halves of `device_remote`.
- **Filters.** bisync only (`Pair.wants_filters_file`): `filters_file_for()` writes `filters/<pair>.txt` and passes `--filters-file`; `--include`/`--exclude` are then **not** also emitted (duplicate rules break change detection). Code-owned rules (`Pair.reglas`: the keychain's, and `REGLA_SIN_LLAVERO` on root pairs, `llavero.md`) go right after `- .prversions/**`, before the TOML's; outside bisync they become `--include`/`--exclude`. bisync rewrites the md5 beside the file only on `--resync`, so `filters_state()` compares the hash itself and reports "needs resync".
- **State.** One workdir per pair, `Pair.workdir` → `state/<pair>/` (`migrate_legacy_state()` moves the old flat layout). `pair_state()` → `PairState(status, detail, prefix)`, `fresh|ok|broken`, read from the real `.lst` files. `resync_reasons(pair)` = why a pair needs `--resync` (`[]` for non-bisync; the mode guard is inside). `last_run(pair)` = mtime of the newest listing = the last good pass (None for non-bisync).
  - A `.lst-err` is the baseline rclone sets aside when a pass aborts (`cmd/bisync/operations.go`, `markFailed()` in `lockfile.go`; with `--recover` the next pass goes back to `.lst-old` and leaves them). The state line says what they are and that they may be deleted by hand; **nothing deletes them**: bisync's workdir is not ours to clean.
- **Resync approval.** `resolve_resync_approval()` asks **once** for all pairs before anything runs; `ask_yes_no()` returns the default when stdin is not a tty, so non-interactive runs skip those pairs (`SKIPPED = -1`) rather than resync unattended.

## Logs and live progress

rclone writes to a temp file; `dispose_log()` keeps it in `logs/` only if the run failed (or `--keep-logs` / `keep_logs = true`), to spare device write cycles. On failure the tail is printed and `KNOWN_ERRORS` maps rclone messages to an explanation: add new cases there.

Device vanished mid-pass (#36): `keep_log()` leaves the log in the temp dir, says so in one `AVISO` line (any half-copy in `logs/` removed) and returns that path, so tail and explanation still come out. `run_all()` turns an `OSError` from the pairs after it into a `FALLÓ` line, never a traceback.

- `--log-file` only catches what rclone logs **after** installing the log, so `execute()` captures rclone's `stdout`+`stderr` (captured, not inherited: with no console behind it, inherited output is lost) and `append_output()` appends it under `DIRECT_OUTPUT_HEADER`.
- `strip_usage()` drops the 12 KB help dump rclone prints after a bad flag: it mentions `--max-delete` and `lock file`, so `explain_failure()` matched a `KNOWN_ERRORS` needle inside rclone's own docs. **A false diagnosis is worse than none.** The two flag entries in `KNOWN_ERRORS` go **last**.
- **Live progress.** `BASE_FLAGS` has `--stats 2s --stats-one-line` (base layer, so a pair can override it); `execute()` runs rclone inside `seguir_progreso(logfile)`, a thread tailing the temp log: the **only** channel, no rc API or ports. Strictly best-effort: an unmatched line gives no progress and the thread swallows *any* exception.
  - The file is closed before `execute()` returns (Windows cannot delete or move an open file); `main()` line-buffers stdout (behind the window it is a pipe); `print_log_tail()` drops stats lines.
  - The regex mirrors `StatsInfo.String()` (`fs/accounting/stats.go`) and requires the ETA, so a line cut mid-write never yields a half number.

## Writing the TOML (`common/config_file.py`)

`tomllib` only reads and the project has no deps, so the serializer is hand-rolled: scalars, string arrays and one nested `flags` table. Preserve:

- `[pair.flags]` binds to the **last** `[[pair]]` written, so it is emitted right after its pair.
- `dumps_checked()` re-parses its output and refuses to write if the dict does not reproduce. `save()` and `catalog.push()` both go through it.
- **A table it does not know** (not in `TABLAS_CONOCIDAS`, e.g. a newer version's `[keychain]`) is written as is at the end. `model.parse_config()` ignores it on read, and dropping it on write would make `dumps_checked()` refuse the whole file, so a catalogue carrying it could not be edited. A subtable inside it is still refused by that check.
- Work on the **raw dict**, never `model.Config` (its `Pair`s have `[defaults]` merged). `save(head=None)` keeps the target's header.
