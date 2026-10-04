# Conflicts, last run, pass journal and per-pair versions

Files: `common/conflicts.py`, `common/results.py`, `common/historial.py`, `ui/conflict_editor.py`, `ui/versions_editor.py`, `common/bisync.py` (filters).
Formerly AGENTS.md «Conflicts & failures» and «Per-pair versions».

## Conflicts

**Why the suffix carries the side.** With rclone's defaults the loser is `.conflictN` with the lowest free N (`cmd/bisync/resolve.go`: `resolve`, `numerate`): an order, not a side. So `MODES["bisync"]` sets `conflict-suffix = "conflicto-dispositivo,conflicto-remoto"`: two suffixes → the name says Path1/Path2 and stays numbered (`pathname` would overwrite an unresolved earlier copy). `conflicts.esquema()`/`leer_nombre()` replicate `setResolveDefaults` + `SuffixName` + `SuffixKeepExtension` from the pair's **merged** flags, so a user override keeps working; legacy `.conflictN` are still found, **without** a side. Path1 is `pair.source` (local in bisync): `conflicts.lado()`. Keep the citations.

- **Derived state.** `sync.run_pair()` scans after every non-dry-run bisync pass (good or bad) and prints an `AVISO`; `state/conflicts.json` stores only paths relative to `DEVICE_ROOT` and `cargar()` re-checks each exists, so the chip clears itself.
- **The original's side is inferred** only when there is exactly one copy with a known side; `Conflicto.version(lado)` is None when a side has 0 or ≥2 versions: never guess. Caveat: a copy made on device A syncs to device B, where it still reads «versión de este dispositivo».
- **Resolving is local-only.** `plan_conservar()` keeps one version under the real name and deletes the rest; `execute()` refuses if any file changed since the plan (size, mtime_ns), then `mover()` (`os.replace`, atomic: failure changes nothing), then `borrar()`s. Labels never show the raw suffix.

## Last run and the pass journal

- **Last run.** `results.apuntar()` from `sync.run_pair()`, not for dry-runs and not for SKIPPED (a skip is not a result; the resync chip covers it). `results.fallos()` feeds `revision`, which is what the «Reparación» line counts; the entry stays until a good pass. `results.ultimas_buenas()` is the other half, the date the main window shows; it survives a failure because `apuntar()` keeps the last good stamp in its own key.
- **Pass journal (#20).** `last_run.json` holds one pass per pair, so `historial.py` keeps the last `POR_PAREJA = 50` of each in `state/historial.jsonl`, one JSON line per pass: `pareja`, `inicio` (`store.stamp()`), `codigo`, `segundos`, `transferido` (bytes, or null).
  - Written inside `sync.record_result()`, so it follows `results`' rule (no dry-run, no SKIPPED); a call without a `Reloj` (`run_all()`'s `OSError` net, #36) still lands, timed now and without a duration.
  - **Appending is the normal write**; the atomic rewrite (`store.write_text`) happens only when a pair passes `RECORTE = 2 × N` or the file `TOPE_BYTES`, so the file is rewritten at most once per N appends (write cycles are why good logs are not kept).
  - `transferido` is `progress.final_del_log()`, read from the log's tail **before** `dispose_log()` deletes it. File counts are not stored: with `--stats-one-line` `xfr#` appears only while the transfer queue is non-empty (`StatsInfo.String()`) and deletes only in the multi-line block.
  - Reading skips half-written or foreign lines, and an append after a cut line starts on its own. `historial.racha()` is the logic behind the «Reparación» sentence.

## Per-pair versions (`versions = true` + `ui/versions_editor.py`)

A bisync pair with `versions = true` keeps, in `.prversions/` **inside its own root on each side**, what *that side* loses: overwritten files, deleted ones (including a delete arriving from the other side) and the loser of a conflict. Naming is rclone's `--suffix ~%Y%m%d-%H%M%S --suffix-keep-extension`, i.e. Syncthing's Simple File Versioning: `nota~20260922-093000.md`.

Everything below was **measured against rclone v1.75.1**, not read in its docs. Preserve the citations like the bisync ones.

- **The exclusion is not filtering, it is the precondition.** rclone refuses a `--backup-dir` that overlaps the destination (`destination and parameter to --backup-dir mustn't overlap`) and that abort is *critical*: it invalidates the baseline. `bisync.filters_content()` therefore emits `- .prversions/**`, and emits it **first**, because rclone applies rules in order and the first match wins: behind a `+ **/*.md` it would exclude nothing. The consequence: the two folders are **independent histories that never replicate**, exactly Syncthing's model for `.stversions`.
- **`--backup-dir` must be on the same remote as its side** (`parameter to --backup-dir has to be on the same remote as destination`), which is why the folder lives inside the pair and not at the device root: no extra `combine` upstream, no overlap validation against other pairs, nothing to configure.
- **`--conflict-loser delete` + `--backup-dir` does not delete**: the loser is routed through the backup dir. That is what keeps the vault free of `<name>.conflicto-remoto1` files, and a **deliberate divergence from Syncthing**, which leaves its conflict copies in the folder and syncs them.
- **A `--resync` also honours the backup dir**, so the side a resync overwrites is recoverable (otherwise it vanishes silently).
- `build_command()` injects the five flags; `conflict-loser` goes in with `setdefault` so a `[pair.flags]` still wins. The other four are in `flags_editor.RESERVED`. `RunContext.sello` is computed **once per invocation**, so everything one pass shelves shares a stamp.
- **`versions` does not move `expected_prefix()`.** `tests/test_versions.py` pins it, because that is where a slip costs a baseline.
- **The date comes from the NAME, never the mtime** (`versions_editor.SELLO`): copying the folder rewrites mtimes, and the stamp in the name is the whole reason the format exists. Purging is «Ajustes» → «Versiones…», both sides in one plan through `confirmar_plan()`; the remote side goes out as a single `rclone delete --files-from` with the exact list, never an age or a pattern, behind `working()` like the read of that side. **Restoring is deliberately not offered** (v1).
- Turning it **off** removes the exclusion, so whatever is stored starts syncing as ordinary content. `pair_editor._analizar_versiones()` says so as a warning before confirming; it is not fixed in code.
