# External security & performance audit (2026-10-08)

Source: the handoff of an external audit session (four research-only agents over the working tree as of `fc7982d`). The findings below are copied verbatim from that report, which existed only in chat; this file is their durable record. The verification of each finding against the tree, and the plan of fixes, is `docs/superpowers/plans/2026-10-08-correcciones-auditoria.md`.

### SECURITY — ranked

**S1 · HIGH — Catalogue/TOML rclone flags reach argv unvalidated → host RCE.**
`sync.py:411-414` appends `model.flags_to_args(flags)` + `pair.extra_flags` (from `model.py:765-767`). `RESERVED` is enforced only in `ui/flags_editor.py:132-134` (UI dialog only); hand-edited `sync_config.toml` and catalogue pairs (`ui/pair_editor.py:621`, `install/deploy.py:767`) skip it. Verified repro: `extra_flags = ["--sftp-ssh", "cmd.exe /c …"]` lands in argv (rclone runs the external ssh binary); `flags = {resync = true}` forces unattended `--resync`, bypassing `resolve_resync_approval()` (`sync.py:702-730`); `extra_flags` is appended **after** the script-owned `--config/--log-file/--dry-run/--workdir`, overriding them (rclone last-wins).
**Fix direction:** enforce `RESERVED` + script-owned-flag filtering at parse time (`model.parse_config` / `config_file.dumps_checked`), and/or emit `extra_flags` before script-owned flags.

**S2 · HIGH — `local` not confined to device root in the parser.**
`common/model.py:893-903` `normalizar_local` keeps `..` and drive letters; containment `_local_de_equipo` runs only `if equipo` (`model.py:735-740`). Verified: `local="../../fuera"` → `D:\fuera`. UI picker checks (`ui/pair_editor.py:524-554`) don't cover parser/catalogue/hand-edit paths. Attack: catalogue pair `local="C:/Users/…"` + `down-mirror` deletes host files (aggravated because `sync_config.toml` is excluded from the agent fingerprint — see S3).
**Fix direction:** reject `..`/absolute `local` in `_build_pair` for units too (reuse `problema_local_equipo`).

**S3 · HIGH — Agent acceptance fingerprint excludes `sync_config.toml`/`state/` → tamper an accepted drive → host RCE.**
`agente.py:628-633` (`HUELLA_SIN_CARPETAS`/`HUELLA_SIN_FICHEROS`), `_opciones_hijo` `agente.py:593-620` runs drive code with the agent's interpreter but device flags (S1). Documented gap at `docs/agents/reference/agent.md:62`. Changing only `sync_config.toml` (no hashed code) → `extra_flags` executed by host rclone next pass.
**Fix direction:** runtime flag allow-list (preserves legitimate window edits while blocking payload flags); consider hashing config-with-known-legit-edits or re-asking on config change.

**S4 · HIGH — penwatch has no consent/fingerprint model.**
`penwatch.py:772-802` copies device runtime by a stamp hash that comes *from the device* (`stamp_id` = sha256 of device-supplied stamp text); `:991-1038` executes device-supplied VeraCrypt EXE existence-check-only; `:1505-1522` adopts the device's `device_id` or returns None → id check skipped (`find_pen`, `:441-460`) → any volume with `.prdrive/` launches; `refresh_runtime` re-registers the logon task with the device's interpreter (persists after removal). Contrast: `agente.py:636-682` has `huella()`; `agente.veracrypt_propio()` (`agente.py:543-572`) re-hashes before launch.
**Fix direction:** fingerprint `.prdrive` at install and before launch; refuse `device_id is None` for launching; verify travelling VeraCrypt against `pins.VERACRYPT_SHA256`.

**S5 · HIGH — No `.prdrive/` exclusion in pair filters → root pair uploads SSH key + `rclone.conf`.**
`common/bisync.py:185-207` `filters_content()` adds only `- .prversions/**` (+ `model.REGLA_SIN_LLAVERO` = `- /.keychain/**` when `[keychain]` exists, `model.py:190,1142`). Verified: `local="."` with no keychain → zero rules. Violates `AGENTS.md` invariant "no pair mirrors `.prdrive/`" — unenforced.
**Fix direction:** code-owned exclusion of `.prdrive/**` (and decide on `PRDRIVE` control file) in `filters_content()` + `sync.py:315-335 filter_args()`; test in `tests/`.

**S6 · MEDIUM — Unattended `*-mirror` runs delete for real, no dry-run gate.**
`runsync.py:481-501` `run_pair_quiet`, `:1097-1120`, `penwatch.py:991-1007` never add `--dry-run`; brake is UI text only (`pair_editor.mirror_warning`).
**Fix direction:** require explicit consent flag / refuse `*-mirror` in unattended paths unless previously dry-run-validated (design decision — flag for user).

**S7 · MEDIUM — Catalogue `[remote]` → device `rclone.conf` verbatim, unescaped (injection); backend secrets exported to catalogue.**
`install/profile.py:156-168` `render_conf` writes values unescaped (newline → TOML injection); `:495-535` `align_with_catalog` replaces backend options verbatim (no `NOMBRE_VALIDO` check — that's `from_form` only); `:552-557` `to_catalog_remote` exports typed `password`/`token`/`secret_access_key` into the "non-secret" `[remote]` block, contradicting `catalogue.md:37`.

**S8 · MEDIUM — No timeout on sync/rclone processes → one wedged pass stalls service/agent forever.**
`sync.py:498` (`subprocess.run` no timeout), `runsync.py:491`, agent `Pasada` (`agente.py:2575/2606` polled forever); `daemon_cycle` checks stop only between pairs (`runsync.py:533`). Correct patterns exist: `llavero.pasada(tope)`→`matar_arbol`, `expulsar._ejecutar(timeout=30)`.

**S9 · MEDIUM — Predictable shared-temp executable path.**
`common/model.py:399-417`: fixed name `/tmp/rclone_portable`, `copy2` then chmod then exec → symlink/TOCTOU → code exec as victim on multi-user Linux. Only fixed-name temp in the project (rest use `mkstemp`/`mkdtemp`).

**S10 · MEDIUM — Device-writable lock records DoS window/service.**
`runsync.py:324-355,457-470,1067-1073`: liveness is `pid_alive` only (no boot-time identity); contrast `equipo.pasada_viva()` (`equipo.py:434-450`) which checks `arranque_del_sistema()`. Device-planted `state/ui.lock.json`/`daemon.lock.json` with `host==this machine` + any live pid blocks window/`--auto`.

**S11 · MEDIUM — Closing output window orphans rclone.**
`ui/tk.py:1924-1935,2104-2108`: no `CREATE_NEW_PROCESS_GROUP`/`start_new_session`; `terminate()` without `wait()` kills `sync.py` only; rclone grandchild keeps writing; `.lck` left held. Correct pattern: `llavero.pasada` (`taskkill /T`/`os.killpg`).

**S12 · LOW (documented/accepted, note only):** VeraCrypt password in Windows argv (`install/crypto.py:942-997`; POSIX uses `--stdin`); update chain unsigned (`common/update.py:23-25`); `webbrowser.open` on unvalidated URL from API *or* huella-excluded `state/update.json` (`ui/tk_update.py:186`); PATH rclone adopted unverified at provisioning (`rclone_bin.py:129-152`); `config_file.save` tmp/`.bak` without O_EXCL unlike `store.write_text` (`config_file.py:280-286` vs `store.py:84-102`); systemd unit unescaped (`penwatch.py:1357-1358`).

### PERFORMANCE — ranked (constants verified in source)

**P1 · HIGH — Agent 2 s tick ignores planner's own `mirar_en`.**
`agente.py:175` `TICK=2.0`, loop `:4241-4253` always sleeps TICK; `planificador.py:386` computes `Decision.mirar_en` (idle up to 60 s) but only `retenido`/`tarea` are read (`agente.py:2269-2275`). Per `vuelta()`: stat present + `_contrato` re-reads `instalacion.json` (uncached `rclone_propio`, `:2008→534-538`), `daemon.lock.json`, `ui.lock.json`+`pid_alive`, 2 config stats → ≈7 file-ops/2 s/root ≈ **12 600 device file-ops/h/root**; volume never idles. Also agent itself never `prioridad.bajar()` (only children).
**Fix:** honor `mirar_en` (bounded below by `PARAR_ESPERA=10.0` or mailbox watch); cache `rclone_propio()`; rate-limit lock reads.

**P2 · HIGH — `watch=true` fallback = full recursive scandir+stat every 10 s.**
`common/huella.py:88-107`; cadence `planificador.py:596-601` (`sondeo=10`, quiet=120, battery=60, `tope_entradas=20_000`); keychain hard-wired 10 s even on battery (`planificador.py:748-749`). Applies to **default Windows config** (VeraCrypt ⇒ no inotify, `avisos_carpeta.py:663-674`), network shares, over-budget watches. Up to 360 walks/h/pair ≈ 7.2 M stats/h at cap; network `local` = one RPC per file per walk.
**Fix:** two-tier probe (root mtime + entry count without per-file stat) before full hash; backoff when quiet; exempt keychain 10 s floor on battery.

**P3 · MED-HIGH — Conflict scan walks whole local tree after every pass, no ignore, no cap.**
`sync.py:647` → `common/conflicts.py:267-293` `os.walk(pair.local_abs)` (no `IGNORAR`, no `tope`; walks `.prversions/**`, `.prdrive/**`, `$RECYCLE.BIN`); rewrites `state/conflicts.json` unconditionally (`:336`). Also runs at window open (`ui/tk.py:1118-1154`).
**Fix:** ignore tuple + `tope_entradas` (mirror `huella`), prune subdirs, gate on movement evidence / conditional save.

**P4 · MEDIUM — runsync daemon idle-polls 3 device files every 2 s.**
`runsync.py:106 POLL_SECONDS=2.0`, loop `:889-906` → ~5 400 device file-ops/h idle. Also `tomar_lock` 0.3 s spin up to 30 min (`:807-838`) → 6 000 reads; `update.check()` synchronous in cycle (`:568`).
**Fix:** POLL_SECONDS → 5–10 s (stop latency budget already 15 s); backoff on lock wait; thread the update check.

**P5 · MEDIUM — penwatch polls drive map twice every 5 s forever.**
`penwatch.py:172 POLL_SECONDS=5.0`; `watch_loop` `:1064-1137` runs `find_pen` + (when no device) `find_vestibule` = second `candidate_roots()` → ~1 440 dir scans/h, 30–70 k syscalls/h even with no device. Agent already has mount-event watching (`agente.py:3892-3935`) to copy.
**Fix:** reuse one candidate list; back off to 15–30 s; ideally mount events + fallback poll.

**P6 · MEDIUM — Full process enumeration every 10 s (agent + Tk thread).**
`store.py:506-572` Toolhelp snapshot + `OpenProcess`+`QueryFullProcessImageNameW` per PID; per package; Linux second full `/proc` walk. Callers: `agente.py:2184-2198` per root, `runsync.py:618-622`, and **on Tk thread** `ui/tk.py:986`→`llavero_editor.py:149`. ≈430 k syscalls/h, 0.5–1.5 % CPU.
**Fix:** one snapshot per sweep (hoist out of per-package/per-root loop), 2–3 s TTL cache shared by all callers; cheaper primitive exists: `store.procesos_llamados` (`store.py:349`).

**P7 · MEDIUM — Two fresh D-Bus connections every 60 s; aligned per-minute device burst on loop thread.**
`agente.py:190 MIRAR_ENTORNO=60` → `moderacion.py:212-218,271-275` new bus connection each call (144/h; tail: up to ~10–15 s loop stall with 5 s `espera`). `MIRAR_EMBLEMA=60` group (`agente.py:231`) fires 4–5 device reads + `IOCTL_STORAGE_QUERY_PROPERTY` in the *same tick* on the loop thread (`:3660-3735`, `expulsar.py:241-273`).
**Fix:** persistent bus connection (or 3–5 min cache / signal subscription); stagger or thread the emblem burst.

**P8 · MED-HIGH — Whole diagnosis on Tk thread before window shows; render() recomputes it.**
`ui/tk.py:944-945` `leer_estado`→`revision.revisar` (`revision.py:312-336`, ~100–300 syscalls + possible process sweep) synchronous pre-`deiconify`; again at `:1015,1072,1139,1189,1199,1312`. `render()` `:1334-1335` re-runs `resync_reasons`/`filters_file_for`/`last_run` → filters file read+md5 twice per pair per repaint + `mkdir` (`bisync.py:210-244`); `filters_file_for` may *write* during paint (`bisync.py:225`).
**Fix:** `segundo_plano.lanzar()` + show window with previous state (pattern already used for Parejas/Dispositivos); render consumes `vista["hallazgos"]`; memoise on mtimes.

**P9 · MEDIUM — Pass journal fully parsed on every append.**
`sync.py:567`→`historial.py:251-271` `recortar_si_toca` reads+parses up to 1 MiB/`~5 k` JSON lines on every `apuntar` (per pair per pass); `rachas` parses again per diagnosis.
**Fix:** decide recorte from `stat().st_size`/line counter; cache parsed list keyed `(mtime,size)`.

**P10 · LOW-MED — `logs/` and `agente.dlog` unbounded.**
`sync.py:183-191,247-252` one file per failed run, **no pruning anywhere**; failing pair @30-min = 48 logs/day forever; failure path reads log whole 3–4× (`sync.py:262,288,668`; `moderacion.es_de_red` lowercases whole text). `agente.dlog` (`agente.py:829-843`) no cap vs runsync's 256 KB (`runsync.py:147-157`).
**Fix:** keep last K per pair (mirror `historial.RECORTE`); cap `agente.dlog`; read only last 256 KB for tail.

**P11 · LOW — Misc:** duplicate `resync_reasons`/`migrate_legacy_state` per invocation (`sync.py:707-715` vs `:600-602`); single `Muestreo` slot held by hung walk blocks all roots (`agente.py:2336`); Linux tray re-decodes device `.ico` ~1/min (no cache, `bandeja_linux.py:176-217` vs Windows' `(path,size,mtime)` cache); `resumen()`/`bandeja.vista()` rebuilt+deep-compared every tick; per-pair interpreter spawn per cycle (could batch: `sync.py a b c` already supported); keychain `REMOTO_ABIERTO=5 min` full remote pass while KeePassXC open (`llavero.py:172`).

### Verified clean (do NOT "fix")

No `shell=True`/`os.exec`; downloads SHA-256-verified in memory before write (`rclone_bin.py:430-441`, `runtime_bin.py:289-297`, pins); zip-slip guarded (`update.py:321-336`); `pid_alive` uses `OpenProcess`; O_EXCL locks with side-lock removal; `EditPlan`/`confirmar_plan` gating intact; no pipe deadlocks; no busy-waits; inotify storms collapse by design; single sync subprocess at a time; state writes change-gated; `red.py` fully event-driven; pair names validated (`model.problema_nombre`); no double window↔agent polling.
