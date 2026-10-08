# Audit fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the audit findings that hold against the current tree. The config, the catalogue and the device's own files can no longer make rclone run a program, leave the device, or upload `.prdrive/`. Then the cheap robustness and log fixes.

**Architecture:** Every rule goes where the project already puts its rules: the parser (`model.parse_config`, the one gate that hand-edited TOML, catalogue pairs and the installer all pass through), the code-owned filter rules (`Pair.reglas`), and the installer's rendering of `rclone.conf`. No new module. Two findings (S4, S6) need a design decision first and are outlined only.

**Tech Stack:** Python 3.11 stdlib; plain-script tests (`tests/_harness.Checks`, `sandbox()`).

**Spec:** `docs/superpowers/specs/2026-10-08-auditoria-externa.md` (the audit, verbatim). Each finding below was re-checked against `fc7982d`, several with read-only repros (`scratch` scripts, not committed).

## Verification of the findings

| ID | Verdict | Severity now | What was checked |
|---|---|---|---|
| S1 | **Confirmed** (repro) | High | `[pair.flags] resync = true` → `--resync` on every pass (`build_command` only pops `resync-mode`). `extra_flags = ["--config", "/tmp/x"]` lands after the script's `--config`. `RESERVED` is checked only by the flags dialog (`ui/flags_editor._validar`). |
| S1b | **New, confirmed** (repro) | High | Same as S1 through another key: `remote = "nas,ssh='sh -c id'"` (or `":sftp,host=…,ssh=…"`) reaches rclone untouched as `nas,ssh='sh -c id':R/x`. That is an rclone connection string, which overrides backend options. `remote` is never validated. |
| S2 | **Confirmed** (repro) | High | `local = "../../fuera"` → combine upstream `..=<parent of the device>`. `C:/…` escapes on Windows. On POSIX a leading `/` is stripped by `normalizar_local` (stays inside). |
| S3 | **Confirmed** | High → closed by S1/S1b | `agent.md` already lists it as «Not covered». `rclone.conf` *is* hashed, but `--config state/x.conf` (state/ is not) bypasses that. |
| S4 | **Confirmed** | Medium-High | Plus: the host copy of penwatch never refreshes itself, so any hardening only reaches hosts that run `penwatch install` again. → **Decision D1.** |
| S5 | **Confirmed** (repro) | High | A root pair with no keychain gets zero code rules; `.prdrive/` (key, `rclone.conf`) goes up. Also: a root `down-mirror` would *delete* `.prdrive/`, and the exclusion prevents that too. The fix changes the filters file, so every root bisync pair needs one `--resync`. |
| S6 | **Confirmed** (by design) | Medium | rclone `sync --max-delete N` deletes N files and then stops, so a broken mirror loses 50 more files on every unattended pass. bisync aborts the whole pass instead, so it does not erode. → **Decision D2.** |
| S7 | **Confirmed** | Medium | Plus: the catalogue's `[remote].name` is also unvalidated (`[nas]\n…`). `ssh = "…"` from the catalogue needs no newline at all. Only the wizard path is affected. |
| S8 | Plausible, low impact | Low | rclone's defaults `--timeout 5m` / `--contimeout 1m` already cut network stalls. The agent polls its pass asynchronously. A process stuck on local I/O (D state) cannot be killed anyway. → no code (D3). |
| S9 | **Confirmed** | Low-Medium | Mitigated on modern distros by `protected_symlinks`/`protected_regular`. A second bug: two concurrent copies onto a running binary → `ETXTBSY`. |
| S10 | **Confirmed, reframed** | Low-Medium (robustness) | Not a security boundary: whoever can write `state/` already runs the device's code. The real bug is PID reuse after a reboot: a stale `ui.lock.json` whose pid is alive again blocks the window. |
| S11 | **Confirmed** | Medium | `on_close()` → `proc.terminate()` on `sync.py` only; rclone keeps running with its `.lck`. |
| S12 | Accepted (documented) | Low | One cheap item: on Windows `webbrowser.open` is `os.startfile`, so a non-URL in the device's `state/update.json` would *run* a file from «Ver la página». Fixed (Task 11). Rest unchanged. |
| P1 | Partial | Low | 2 s tick is real, but these are small, cached reads. The proposed fix (sleep until `mirar_en`, up to 60 s) would break the window↔agent handshake: `runsync.stop_previous_daemon` waits `STOP_WAIT_SECONDS = 15`. No change. |
| P2 | Already addressed | — | The 2026-10-06 plan's approach B: 10 s only while the folder moves, 120 s quiet, 60 s on battery; the keychain exemption is that plan's decision 7. Windows notices are its phase 2. |
| P3 | **Confirmed** | Medium | `conflicts.recorrer` walks `.prversions/`, and on root pairs `.prdrive/` and system noise. `_guardar` rewrites `conflicts.json` (new stamp) every pass. |
| P4 | **Confirmed** | Low | `POLL_SECONDS = 2`; `tomar_lock` spins every 0.3 s for up to 30 min. |
| P5 | Confirmed | Low | No action; it follows D1. |
| P6 | Overstated | Low | Only roots with a keychain, only on Windows, every 10 s. No action. |
| P7 | Overstated | Low | Two D-Bus connections a minute, each with a 2 s cap. No action. |
| P8 | Partial | Low | The conflict walk is already threaded; what remains synchronous is a few small reads. Measure on a real device before refactoring. No action. |
| P9 | Overstated | — | The journal is capped at `RECORTE` (100) lines per pair, about 20 KB per pair. No action. |
| P10 | **Confirmed** | Medium | `logs/` is never pruned. Plus: the agent's `dlog` appends to the device's `state/daemon.log` with no cap (runsync's own `dlog` caps at 256 KB). |
| P11 | Low | — | No action. |

Baseline: `python tests/run_all.py` → 100/102 green. `test_iconos.py` and `test_start.py` fail **only because this container has no `tkinter` module** (pre-existing, unrelated; CI has Tk).

## Decisions for the user

**Decided (2026-10-08): D1 (a) retire penwatch; D2 (a) hold after the brake; D3 and D4 as proposed.**

- **D1 (S4, penwatch).** (a) **Retire it** (recommended): the wizard and the window offer only the agent; `penwatch install` refuses new installs and names the agent; installed copies keep working and `status` adds a warning row. The agent is already its successor, with the consent model (`huella`). Hardening reaches only reinstalled hosts either way. (b) Harden it: refuse to launch without `device_id`; move `agente.huella()` into `penwatch.py` (the agent already imports penwatch) and check it before each launch; adopt a device runtime only at install. (c) Accept and document.
- **D2 (S6, unattended mirrors).** (a) **Hold after the brake** (recommended): a `*-mirror` pass that stops on `--max-delete` is not retried by the service or the agent until a person runs it from the window, and «Reparación» says so. This stops the erosion and changes nothing for healthy pairs. (b) An approval gate: mirrors run unattended only after one supervised run; pairs that already have a good run are grandfathered. (c) Both. (d) Leave as is.
- **D3 (S8): no code.** Default unless you want a progress-based watchdog.
- **D4: warn about an already-uploaded `.prdrive/`.** Included in Task 3 unless you say no. Prdrive never deletes on the remote by itself, so the warning names the folder to delete.

## Global Constraints

- Stdlib only, Python 3.11. Validation raises `model.ConfigError` / `install.InstallError`, never `sys.exit`.
- Comments, docstrings and user text in Spanish; docs under `docs/agents/` in English; Google docstrings (`docs/agents/code-writing-conventions.md`).
- AGENTS.md safety invariants untouched. Nothing here deletes user data on either side; nothing resyncs unattended.
- `penwatch.py` is untouched (only D1 changes it). `install/` imports `common/`, never `ui/`.
- New test-replaceable indirection points are module-level and registered in `docs/agents/reference/commands-testing.md`.
- One PR per group below. Each bumps `VERSION` (the merge publishes) and has a Spanish title written for the device's user, following `.github/pull_request_template.md`.
- Verify with `python tests/run_all.py`, plus the task's own script.

## Review Focus

1. **A device in use whose TOML has a flag, `remote` or `local` that is now refused.** It must not sync half its pairs or crash. `load_config` raises one `ConfigError`; the window shows it through `ui.fatal` and the agent shows «sin servicio». Since the fix is a hand edit, the message names the pair, the key and what to remove. → Tasks 1 and 2: every refusal test asserts the pair name and the key are in the message.
2. **A root bisync pair after the update.** The window offers one `--resync`, and its confirmation warns about a `.prdrive/` already on the remote. The service and the agent skip that pair and never resync it by themselves. → Task 3, `una pareja raíz de antes pide un --resync` and `el aviso del resync nombra .prdrive`.
3. **Legitimate flags written the usual ways keep working**: `--bwlimit=8M` (with `=`), `-v`, `max-delete = 25`, `conflict-resolve = "newer"`, the keychain's `resync-mode`. → Task 1, `lo de siempre sigue valiendo`.
4. **Log pruning with pairs whose names are prefixes of each other** (`a` and `a_b`): pruning `a` never touches `a_b`'s logs. → Task 8, `podar a no toca los de a_b`.
5. **A catalogue whose `[remote]` was written by an older device and holds `pass` or `ssh`.** A new device ignores those options, the wizard says so, and the device still provisions. → Task 4, `el catálogo no pasa ssh ni secretos`.

---

## PR A — the config cannot run programs nor leave the device (Tasks 1–3)

### Task 1: rclone flags and remote names are checked at parse time (S1, S1b, S3)

**Files:**
- Modify: `common/model.py` (new `FLAGS_RESERVADOS`, `normalizar_flag`, `problema_flag`, `NOMBRE_REMOTE`, `problema_remote`; called from `_build_pair` and `parse_config`)
- Modify: `ui/flags_editor.py` (`RESERVED = model.FLAGS_RESERVADOS`, `normalize = model.normalizar_flag`, `_validar` uses `model.problema_flag`, `parse_extra` uses `model.problema_extra`)
- Create: `tests/test_parseo_seguro.py` (shared by Tasks 1–3)
- Modify docs: `docs/agents/reference/engine.md` (flags bullet), `docs/agents/reference/agent.md` («Not covered» keeps only the travelling VeraCrypt), `docs/guia/configuracion.md`, `sync_config.example.toml` (comment above `[defaults.flags]`)

**Interfaces:**
- Produces: `model.FLAGS_RESERVADOS: Mapping[str, str]` (today's `RESERVED`, moved as is). Nothing is added to it: a refusal at load time is a `ui.fatal` that keeps the window closed until the TOML is edited by hand, so this task refuses only what is a security problem. `model.normalizar_flag(nombre: str) -> str` (today's `flags_editor.normalize`). `model.problema_flag(nombre: str) -> str | None`. `model.problema_extra(args: Iterable[str]) -> str | None` (the first refused argument's reason). `model.NOMBRE_REMOTE: re.Pattern`. `model.problema_remote(nombre: Any) -> str | None`, whose reason starts «'remote' no vale».

- [ ] **Step 1: Write the failing tests** in `tests/test_parseo_seguro.py`, with helpers `una(**pareja) -> dict` (one pair `p`, `local = "sync-data/p"`, `remote_path = "R/p"`, `[defaults] remote = "nas"`), `rechaza(data, equipo=False) -> str` (the `ConfigError` text, `""` if it parses) and `_texto(f) -> str` (the text of the `ConfigError` that `f()` raises, `""` if none):

```python
for flags in ({"resync": True}, {"workdir": "/tmp/w"}, {"filters-file": "x"},
              {"password-command": "x"}, {"metadata-mapper": "x"},
              {"rc": True}, {"rc-addr": ":5572"}, {"sftp-ssh": "sh"}):
    clave = next(iter(flags))
    c.contains(f"[pair.flags] {clave} no se admite", rechaza(una(flags=flags)), clave)
    c.contains(f"  y dice de qué pareja", rechaza(una(flags=flags)), "[p]")
c.contains("[defaults.flags] config no se admite",
           rechaza({**una(), "defaults": {"remote": "nas", "flags": {"config": "x"}}}), "[defaults]")
for extra in (["--sftp-ssh", "sh -c id"], ["--sftp-ssh=sh -c id"], ["--config", "/tmp/x"],
              ["--webdav-bearer-token-command", "x"], ["--log-file=/tmp/l"], ["--Resync"]):
    c(f"extra_flags {extra[0]} no se admite", bool(rechaza(una(extra_flags=extra))), True)
for remoto in ("nas,ssh='sh -c id'", ":sftp,host=x", "nas:", "-nas", "a b "):
    c.contains(f"remote {remoto!r} no se admite", rechaza(una(remote=remoto)), "remote")
c.contains("[defaults] remote tampoco", rechaza({**una(), "defaults": {"remote": "nas,x=y"}}), "remote")
# lo de siempre sigue valiendo
cfg = model.parse_config(una(flags={"transfers": 4, "checksum": True, "max-delete": 25,
                                    "conflict-resolve": "newer"},
                             extra_flags=["--bwlimit=8M", "-v", "--exclude-if-present", ".nosync"]))
c("lo de siempre sigue valiendo", cfg.pairs[0].extra_flags[0], "--bwlimit=8M")
for remoto in ("nas", "mi nas", "nas.casa", "Nube_2", "año"):
    c(f"remote {remoto!r} vale", rechaza(una(remote=remoto)), "")
c.contains("el cuadro de flags dice lo mismo", _texto(lambda: flags_editor.parse(
    'password-command = "x"')), "password-command")
c.contains("y el de argumentos extra también", _texto(lambda: flags_editor.parse_extra(
    "--sftp-ssh\nsh -c id")), "sftp-ssh")
```

- [ ] **Step 2: Run it and see it fail**

Run: `python tests/test_parseo_seguro.py` · Expected: FALLO on every refusal (they parse today).

- [ ] **Step 3: Implement in `common/model.py`.**
  - `problema_flag(nombre)` normalises (`strip`, `_`→`-`, lower case). It returns the `FLAGS_RESERVADOS` reason, or for a flag that runs a program on this computer: «lanza un programa en este equipo, y el config viaja con el dispositivo: no se admite». A flag runs a program when its normalised name ends in `-command` or `-ssh`, is `metadata-mapper` or `rc`, or starts with `rc-`. The docstring cites rclone: `--password-command` (fs/config), `--metadata-mapper` (fs/config/configflags), backend/sftp `ssh`, backend/webdav `bearer_token_command`, fs/rc/rcflags. The suffix rule also blocks remote-side `--sftp-*-command` as flags; those still work in `rclone.conf`.
  - `problema_extra`: each token starting with `--` is checked by its name (`token[2:].split("=", 1)[0]`). Single-dash short flags pass (none of them runs a program). `flags_editor.parse_extra` raises `ConfigError` with that reason, so the dialog says it when the text is typed, not later at the plan.
  - `NOMBRE_REMOTE = re.compile(r"(?!-)[\w.+@-]+(?: [\w.+@-]+)*")` (rclone's remote-name rule: no `,` `:` `=` quotes, no leading `-`, no trailing space). `problema_remote` uses `fullmatch`.
  - `parse_config` checks `[defaults].flags` and `[defaults].extra_flags` once, prefixing errors with `[defaults]`. `_build_pair` checks the pair's own, and `remote_name` (which covers `[defaults].remote` through its fallback), prefixing with `[<pair>]`.
  - `ui/flags_editor.py` re-exports the moved names and calls `model.problema_flag` in `_validar`.

- [ ] **Step 4: Run** `python tests/test_parseo_seguro.py`, `python tests/test_flags_editor.py`, `python tests/test_versions.py`, `python tests/test_llavero.py` · Expected: all OK (the keychain pair is built by code and keeps `resync-mode`).

- [ ] **Step 5: Update the docs listed above.** `agent.md` «Not covered»: the flags line goes; the travelling VeraCrypt stays. `configuracion.md`: which flags and remote names are refused, and why.

- [ ] **Step 6: Commit** — `git commit -m "El config ya no puede pasar a rclone flags que lancen programas ni nombres de remote con opciones"`

### Task 2: `local` stays inside the root, and never names the program's or the keychain's folder (S2)

**Files:**
- Modify: `common/model.py` (new `problema_local`; `_build_pair` calls it for every root; `_local_de_equipo` removed)
- Modify: `ui/pair_editor.py:549` (comment points to `model.problema_local`)
- Test: `tests/test_parseo_seguro.py` (section «local»); `tests/test_raiz_equipo.py` unchanged and still green

**Interfaces:**
- Consumes: `model.problema_local_equipo` (unchanged; `install/raiz_equipo.py` keeps calling it).
- Produces: `model.problema_local(local: Any, equipo: bool = False) -> str | None`.

- [ ] **Step 1: Write the failing tests:**

```python
app = model.APP_DIR.name            # «.prdrive» en un dispositivo, el nombre del checkout aquí
for local in ("../../fuera", "a/../../b", "C:/Users/x", "C:\\Users\\x", "d:x",
              app, f"{app}/keys", model.LLAVERO_LOCAL, f"{model.LLAVERO_LOCAL.upper()}/x"):
    c.contains(f"local {local!r} no vale en una unidad", rechaza(una(local=local)), "[p]")
for local, queda in ((".", "."), ("sync-data/docs", "sync-data/docs"),
                     ("/sync-data/docs", "sync-data/docs")):   # la barra de antes se tolera
    c(f"local {local!r} vale", model.parse_config(una(local=local)).pairs[0].local, queda)
```

- [ ] **Step 2: Run** `python tests/test_parseo_seguro.py` · Expected: FALLO on the escaping and program-folder cases.

- [ ] **Step 3: Implement `problema_local`.** For a host root it first returns `problema_local_equipo`'s reason. Then, for every root, it refuses (on the raw text, `\` read as `/`): a `..` segment, a drive prefix `^[A-Za-z]:`, and a first segment equal (case-insensitively) to `APP_DIR.name` («es la carpeta del programa, con su clave») or `LLAVERO_LOCAL` («es la del llavero, que tiene su propia pareja»). A leading `/` stays tolerated on units: `normalizar_local` strips it and devices in use may have it.

- [ ] **Step 4: Run** `python tests/test_parseo_seguro.py`, `python tests/test_raiz_equipo.py`, `python tests/test_pair_editor.py` · Expected: OK.

- [ ] **Step 5: Commit** — `git commit -m "La carpeta local de una pareja ya no puede salir del dispositivo ni ser la del programa"`

### Task 3: root pairs never carry the program's folder, and say so if they did (S5, D4)

**Files:**
- Modify: `common/model.py` (`REGLA_SIN_PROGRAMA`; `parse_config` gives root pairs the code rules)
- Modify: `common/bisync.py` (new `programa_en_listado`)
- Modify: `common/revision.py` (`_resync` puts the remote folder to delete in `dato` and in the detail)
- Modify: `ui/repair.py` (`aviso_resync` adds the warning)
- Test: `tests/test_parseo_seguro.py` (section «raíz»), `tests/test_llavero.py:107,111` (new expected tuples), `tests/test_repair.py`
- Docs: `docs/agents/reference/engine.md` (code-owned rules), AGENTS.md safety line «no pair mirrors `.prdrive/`» gains «(enforced: `REGLA_SIN_PROGRAMA`)», `docs/guia/configuracion.md` and `docs/guia/seguridad.md` (one resync after updating; delete `.prdrive/` from the remote if it was ever uploaded)

**Interfaces:**
- Produces: `model.REGLA_SIN_PROGRAMA: str = f"- /{APP_DIR.name}/**"`. Root pair `reglas` == `(REGLA_SIN_PROGRAMA,)`, or `(REGLA_SIN_PROGRAMA, REGLA_SIN_LLAVERO)` with `[keychain]`; other pairs unchanged. `bisync.programa_en_listado(pair: Pair) -> bool`. On a `resync` finding, `Hallazgo.dato == (f"{pair.remote_endpoint.rstrip('/')}/{model.APP_DIR.name}/",)` when the root pair uploaded the program folder, `()` otherwise (`dato` is a tuple: `Hallazgo` is frozen).

- [ ] **Step 1: Write the failing tests:**

```python
raiz = model.parse_config(una(local=".", mode="bisync")).pairs[0]
c("la raíz deja fuera el programa", raiz.reglas, (model.REGLA_SIN_PROGRAMA,))
c("  primera regla del fichero de filtros",
  bisync.filters_content(raiz).splitlines()[2], model.REGLA_SIN_PROGRAMA)
c("  y con versiones, detrás de .prversions",
  bisync.filters_content(replace(raiz, versions=True)).splitlines()[2:4],
  [f"- {model.VERSIONS_DIR}/**", model.REGLA_SIN_PROGRAMA])
espejo = model.parse_config(una(local=".", mode="up-mirror")).pairs[0]
c("fuera de bisync va como --exclude", sync.filter_args(espejo, None)[:2],
  ["--exclude", f"/{model.APP_DIR.name}/**"])
c("una pareja de carpeta no lleva reglas", model.parse_config(una()).pairs[0].reglas, ())
with sandbox():          # el fichero de filtros de antes, con su md5 de antes
    viejo = model.FILTERS_DIR / "p.txt"; viejo.write_text(bisync.FILTERS_HEADER + "\n")
    Path(str(viejo) + ".md5").write_text(hashlib.md5(viejo.read_bytes()).hexdigest())
    c("una pareja raíz de antes pide un --resync",
      bisync.filters_state(bisync.filters_file_for(raiz)).status, "changed")
    # un listado path2 con la carpeta del programa dentro
    lst = raiz.workdir / (bisync.expected_prefix(raiz) + bisync.PATH2_SUFFIX)
    lst.parent.mkdir(parents=True); lst.write_text(
        f'- 10 - - 2026-01-01T00:00:00.000000000+0000 "{model.APP_DIR.name}/rclone.conf"\n')
    c("se ve que subió el programa", bisync.programa_en_listado(raiz), True)
```

In `tests/test_repair.py`: `el aviso del resync nombra .prdrive`. `repair.aviso_resync(Hallazgo("resync", "t", "d", "p", revision.AVISO, ("nas:R/p/.prdrive/",)))` has a warning containing `nas:R/p/.prdrive/` and «bórrala»; with `dato=()`, no such warning.

- [ ] **Step 2: Run** `python tests/test_parseo_seguro.py` and `python tests/test_repair.py` · Expected: FALLO.

- [ ] **Step 3: Implement.**
  - `parse_config` builds the root rules once, after the keychain-name check, and gives them to every root pair.
  - `programa_en_listado` reads the pair's path2 `.lst` (best effort; missing or unreadable → `False`) and looks for a quoted path starting with `"<APP_DIR.name>/`.
  - `_resync` sets that `dato` when `pair.es_raiz and bisync.programa_en_listado(pair)`, and then adds to the detail «Hasta ahora subía la carpeta del programa (con su clave y rclone.conf) al remoto».
  - `aviso_resync` adds the warning «El resync deja de subir la carpeta del programa, pero no la borra del remoto: bórrala tú de `<dato[0]>`, que lleva la clave.» It is said before the resync on purpose: after it, the new listing no longer shows the folder.

- [ ] **Step 4: Update `tests/test_llavero.py:107,111`** to the new tuples, then run `python tests/run_all.py` · Expected: all green except the two Tk-less files in this container.

- [ ] **Step 5: Docs** as listed. The PR's «Dispositivos que ya existen» says: root bisync pairs ask for one `--resync` from the window, and the service and the agent skip them until then; non-bisync root pairs need nothing; a copy already on the remote stays there until deleted by hand.

- [ ] **Step 6: Commit** — `git commit -m "Una pareja de la raíz entera ya no sube la carpeta del programa"`

## PR B — the installer: rclone.conf from the catalogue (Task 4)

### Task 4: catalogue `[remote]` → `rclone.conf` with no line breaks, no command options, no secrets exported (S7)

**Files:**
- Modify: `install/profile.py` (`render_conf`, `with_catalog_remote`, `align_with_catalog`, `to_catalog_remote`; new `OPCIONES_QUE_EJECUTAN`, `es_secreta`)
- Test: `tests/test_install_profile.py`
- Docs: `docs/agents/reference/catalogue.md` (`[remote]` paragraph: what is never inherited)

**Interfaces:**
- Produces: `profile.OPCIONES_QUE_EJECUTAN = frozenset({"ssh", "bearer_token_command"})` (backend/sftp, backend/webdav). `profile.es_secreta(clave: str) -> bool`: true for exactly `key`, `pass` or `password`, or for a name containing `pass`, `token`, `secret`, `credential`, `_pem`, `sas_url` or `account_key`.

- [ ] **Step 1: Write the failing tests:** `render_conf rechaza un valor con salto de línea` (`InstallError`); `render_conf rechaza un nombre de remote que no es NOMBRE_VALIDO` (`"nas]\n[x"`); `el catálogo no pasa ssh ni secretos` (`align_with_catalog` with `[remote] type="sftp", host="h", ssh="sh -c id"` → no `ssh` in `options`, and one note says so); `to_catalog_remote no lleva secretos` (`pass`, `token`, `secret_access_key`, `key_pem`, `ssh` out; `type`, `host`, `user`, `port` kept); `lo tecleado aquí sí admite ssh` (`from_form(..., {"type": "sftp", "host": "h", "ssh": "ssh -J x"})` keeps it).
- [ ] **Step 2: Run** `python tests/test_install_profile.py` · Expected: FALLO.
- [ ] **Step 3: Implement.** `render_conf` raises `InstallError` for a remote name outside `NOMBRE_VALIDO`, a key outside `[A-Za-z0-9_]+`, or a value containing `\n` or `\r` (rclone.conf has no escape for them). Both catalogue readers drop `OPCIONES_QUE_EJECUTAN` and add the note «El catálogo traía `ssh`: no se hereda, porque es una orden de este equipo.» `to_catalog_remote` leaves out `es_secreta` and `OPCIONES_QUE_EJECUTAN`.
- [ ] **Step 4: Run** `python tests/test_install_profile.py`, `python tests/test_install_wizard.py`, `python tests/test_install_deploy.py` · Expected: OK.
- [ ] **Step 5: Commit** — `git commit -m "El asistente no hereda del catálogo órdenes ni secretos, ni escribe un rclone.conf roto"`

## PR C — processes and locks (Tasks 5–7)

### Task 5: closing the output window stops the whole pass (S11)

**Files:**
- Modify: `common/store.py` (new `matar_arbol`), `common/llavero.py:572` (its `matar_arbol` calls `store.matar_arbol`; it stays a test-replaceable point), `ui/tk.py:1924-1935,2104-2108`
- Create: `tests/test_matar_arbol.py`
- Docs: `docs/agents/reference/commands-testing.md` (register `store.matar_arbol`)

**Interfaces:**
- Produces: `store.matar_arbol(pid: int) -> None`. On Windows, `taskkill /F /T /PID` with `CREATE_NO_WINDOW`; on POSIX, `os.killpg(pid, SIGKILL)`; never raises. The caller must have started the child as a session leader on POSIX.

- [ ] **Step 1: Write the failing test** `tests/test_matar_arbol.py`: start `[sys.executable, "-c", <starts a grandchild that sleeps 60 s and writes its pid to a file>]` with `start_new_session=True` (POSIX) or `CREATE_NEW_PROCESS_GROUP` (Windows). Wait for the pid file, call `store.matar_arbol(hijo.pid)`, then poll up to 5 s: `c("el nieto también muere", store.pid_alive(nieto), False)`.
- [ ] **Step 2: Run** · Expected: FALLO (`AttributeError: matar_arbol`).
- [ ] **Step 3: Implement** `store.matar_arbol` and delegate `llavero.matar_arbol` to it. In `ui/tk.py`, `subprocess.Popen` adds `start_new_session=True` on POSIX and `CREATE_NEW_PROCESS_GROUP` on Windows; `on_close()` calls `store.matar_arbol(proc.pid)` instead of `proc.terminate()`.
- [ ] **Step 4: Run** `python tests/test_matar_arbol.py`, `python tests/test_llavero.py`, `python tests/test_tk_salida.py` · Expected: OK (Tk skips without a display).
- [ ] **Step 5: Commit** — `git commit -m "Cerrar la ventana de una sincronización la para entera, con su rclone"`

### Task 6: the executable copy of rclone is private and content-named (S9)

**Files:**
- Modify: `common/model.py:399-417` (`ejecutable`)
- Create: `tests/test_rclone_portable.py` (POSIX only; prints `(saltado) …` on Windows)

**Interfaces:**
- Produces: `model.ejecutable(binary: Path) -> str`, same contract. The copy lives in `<XDG_CACHE_HOME or ~/.cache>/prdrive/rclone-<st_size>-<st_mtime_ns>`, in a directory with mode `0o700` owned by the user.

- [ ] **Step 1: Write the failing tests** (`XDG_CACHE_HOME` pointed at `tmpdir()`, a fake non-executable `rclone`):
  - `la copia va a la caché del usuario`
  - `con bit de ejecución`
  - `su carpeta es solo del usuario (0o700)`
  - `la segunda vez no copia otra vez` (same path, same `st_mtime_ns`)
  - `un enlace plantado en su sitio se sustituye, no se sigue`: the symlink's target keeps its content.
- [ ] **Step 2: Run** · Expected: FALLO (today it writes `/tmp/rclone_portable`).
- [ ] **Step 3: Implement.** If the final name exists as a regular file of the right size, return it. Otherwise copy through `tempfile.mkstemp(dir=carpeta)`, `chmod 0o700` and `os.replace` (replacing a running binary by rename is fine). Refuse (`OSError`) a cache directory owned by someone else. Best effort: remove other `rclone-*` files there.
- [ ] **Step 4: Run** `python tests/test_rclone_portable.py`, `python tests/test_arch.py` · Expected: OK.
- [ ] **Step 5: Commit** — `git commit -m "La copia ejecutable de rclone en Linux va a una carpeta privada"`

### Task 7: lock records carry the boot time (S10)

**Files:**
- Modify: `common/store.py` (new `vivo_en_este_arranque`), `common/equipo.py` (`vivo_aqui` and `pasada_viva` use it), `runsync.py` (writers at :342, :650, :858; readers `_viva_aqui`, `servicio_en_marcha`, `stop_previous_daemon`), `agente.py` (writer at :2102; reader `_otro_servicio`), `common/llavero.py:456`, `ui/repair.py:61`
- Test: `tests/test_instancia_unica.py`
- Docs: `docs/agents/reference/service.md`: penwatch's copy (`_vivo_aqui`) stays pid-only on purpose, since it only skips a launch.

**Interfaces:**
- Produces: `store.vivo_en_este_arranque(info: Mapping | None, host: str) -> bool`. It requires the same host and a live int pid, plus, when `info["arranque"]` is a number and `arranque_del_sistema()` is known, `abs(diff) <= HOLGURA_ARRANQUE`. Records without `arranque` (written by older versions) fall back to the pid alone. Every writer adds `"arranque": store.arranque_del_sistema()`.

- [ ] **Step 1: Write the failing tests** (with `store.arranque_del_sistema` replaced by a fixed value):
  - `un registro de otro arranque no cuenta aunque su pid viva`: `ui.lock.json` holding this process's pid and `arranque = fijo - 10_000` → the window's check returns `None`.
  - `uno de este arranque sí`
  - `uno sin arranque, de antes, va por el pid`
- [ ] **Step 2: Run** `python tests/test_instancia_unica.py` · Expected: FALLO on the first.
- [ ] **Step 3: Implement** the helper, the writers and the readers listed.
- [ ] **Step 4: Run** `python tests/test_instancia_unica.py`, `python tests/test_agente_contrato.py`, `python tests/test_repair.py`, `python tests/test_llavero.py` · Expected: OK.
- [ ] **Step 5: Commit** — `git commit -m "Un registro de ventana o de servicio de antes de reiniciar ya no bloquea la ventana"`

## PR D — bounded logs and quieter idling (Tasks 8–11)

### Task 8: `logs/` and the device's `daemon.log` stay bounded (P10)

**Files:**
- Modify: `sync.py:183-191` (`keep_log` calls `podar_logs`), `common/store.py` (new `recortar_diario`), `runsync.py:147-157` and `agente.py:829-843` (both `dlog` call it)
- Create: `tests/test_logs_acotados.py`

**Interfaces:**
- Produces: `sync.LOGS_POR_PAREJA = 20`; `sync.podar_logs(nombre: str) -> None`, which keeps the newest 20 files matching `^<re.escape(nombre)>_\d{8}_\d{6}(_\d+)?\.log$`. `store.DIARIO_TOPE = 256 * 1024`, `store.DIARIO_QUEDAN = 300`, and `store.recortar_diario(ruta: Path) -> None`: past the cap it rewrites the last 300 lines atomically (`store.write_text`); it never raises.

- [ ] **Step 1: Write the failing tests** (in `sandbox()`): `quedan los 20 más nuevos` (25 logs of `a`); `podar a no toca los de a_b`; `el diario del agente se recorta` (a 300 KB `state/daemon.log`, one `agente.dlog` → ≤ 301 lines).
- [ ] **Step 2: Run** `python tests/test_logs_acotados.py` · Expected: FALLO.
- [ ] **Step 3: Implement.** `runsync.DLOG_MAX_BYTES` becomes `store.DIARIO_TOPE`; the agent keeps its `_SIN_ENLACE` open for the append.
- [ ] **Step 4: Run** `python tests/test_logs_acotados.py`, `python tests/test_ultima_pasada.py`, `python tests/test_results.py`, `python tests/test_daemon_aviso.py` · Expected: OK.
- [ ] **Step 5: Commit** — `git commit -m "Los logs de las pasadas que fallan ya no se acumulan sin fin en el dispositivo"`

### Task 9: the conflict scan skips what is not the pair's and does not rewrite unchanged state (P3)

**Files:**
- Modify: `common/conflicts.py:267-336` (`recorrer`, `escanear`, `_guardar`)
- Test: `tests/test_conflicts.py`

**Interfaces:**
- Produces: `conflicts.recorrer(raiz: Path, ignorar: tuple[str, ...] = ()) -> Iterator[Path]`, which prunes top-level entries matching `huella.se_ignora`. `escanear` passes `(model.VERSIONS_DIR,)`, plus `(model.APP_DIR.name, model.LLAVERO_LOCAL) + model.RUIDO_DEL_SISTEMA` on root pairs.

- [ ] **Step 1: Write the failing tests:**
  - `lo de .prversions no es un conflicto`: a conflict-named file inside `.prversions/` → not reported.
  - `en la raíz tampoco lo de .prdrive`
  - `sin cambios no se reescribe conflicts.json`: same scan twice, `st_mtime_ns` unchanged.
- [ ] **Step 2: Run** `python tests/test_conflicts.py` · Expected: FALLO.
- [ ] **Step 3: Implement** the pruning (`os.walk` subfolders filtered at the top level) and make `_guardar` return early when the merged `parejas` equals what is on disk. Nothing reads `cuando`.
- [ ] **Step 4: Run** `python tests/test_conflicts.py`, `python tests/test_conflict_editor.py`, `python tests/test_revision.py` · Expected: OK.
- [ ] **Step 5: Commit** — `git commit -m "Buscar conflictos ya no recorre las versiones guardadas ni la carpeta del programa"`

### Task 10: the runsync service idles at 5 s and waits for the lock at 2 s (P4)

**Files:**
- Modify: `runsync.py:106` (`POLL_SECONDS = 5.0`), `runsync.py:838` (new `ESPERA_LOCK = 2.0` instead of `0.3`)
- Test: `tests/test_auto.py`

- [ ] **Step 1: Write the failing test** `el servicio ve el stop a tiempo`: `runsync.POLL_SECONDS * 2 < runsync.STOP_WAIT_SECONDS` and `runsync.POLL_SECONDS >= 5`.
- [ ] **Step 2: Run** · Expected: FALLO on `>= 5`.
- [ ] **Step 3: Implement** both constants, each with its docstring (the 15 s budget of `stop_previous_daemon`).
- [ ] **Step 4: Run** `python tests/run_all.py` · Expected: green except the two Tk-less files here.
- [ ] **Step 5: Commit** — `git commit -m "El servicio mira el dispositivo cada 5 s en vez de cada 2 s"`

### Task 11: «Ver la página» only opens the project's GitHub page (S12)

**Files:**
- Modify: `common/update.py:193,250` (both `Release(url=…)` go through `pagina_segura`)
- Test: `tests/test_update.py`

**Interfaces:**
- Produces: `update.pagina_segura(url: str) -> str`: `url` if it starts with `f"https://github.com/{REPO}/"`, otherwise `PAGINA`.

- [ ] **Step 1: Write the failing tests:**
  - `una página que no es de GitHub no se abre`: `state/update.json` with `url = "C:\\Windows\\System32\\calc.exe"` → `Release.url == update.PAGINA`.
  - `la de la release sí`
- [ ] **Step 2: Run** `python tests/test_update.py` · Expected: FALLO.
- [ ] **Step 3: Implement** `pagina_segura` and use it in both places.
- [ ] **Step 4: Run** `python tests/test_update.py` · Expected: OK.
- [ ] **Step 5: Commit** — `git commit -m "«Ver la página» solo abre la página del proyecto"`

## After the decisions (outline only; detailed once D1/D2 are answered)

- **D1 (a), retire penwatch:** `ui/tk_install.py:1835` and `ui/tk_watch.py`/`ui/watch.py` offer to install the agent instead. `penwatch.cmd_install` refuses and names the agent. `status_rows()` adds «obsoleto: instala el agente». Docs: `penwatch.md`, `service.md`, `docs/guia/servicio-y-vigilante.md`. Tests: `test_penwatch_instalacion.py`, `test_watch.py`.
- **D2 (a), hold after the brake:** `sync.py` reports a mirror stopped by `--max-delete` in `results` (a `freno` flag). The planner (`planificador.py`) and `runsync.daemon_cycle` skip that pair until a run started from the window clears it. `revision.py` shows a `freno` finding. Tests: `test_planificador.py`, `test_auto.py`, `test_revision.py`.

## Not doing, and why

S8 (D3), the rest of S12 (documented and accepted), P1, P2, P5–P9 and P11: see the verification table. Each is overstated against the code, already handled, or would cost more code than it saves.
