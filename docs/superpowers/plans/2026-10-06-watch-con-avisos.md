# `watch = true` con los avisos del sistema — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A watched pair costs ~nothing while its folder is quiet: Linux hears inotify instead of walking every 10 s, and wherever there are no notices the walk spaces itself out (approach B).

**Architecture:** A new Tk-free `common/avisos_carpeta.py` owns the inotify descriptor (one per agent) and turns kernel events into one `Aviso` per pair (`CAMBIO`, `DESBORDADO`, `PERDIDA`). The agent arms a pair on the existing `Muestreo` thread, drains the descriptor from `Vigia`'s `poll`, and feeds notices to the pure planner (`pl.avisado()`); pairs that cannot be armed keep the walk, now paced by `pl.a_recorrer()`. Windows keeps walking (with B) in this phase.

**Tech Stack:** Python 3.11 stdlib only; `ctypes` for `inotify_init1`/`inotify_add_watch`/`inotify_rm_watch`; plain-script tests (`tests/_harness.Checks`).

**Spec:** `docs/superpowers/specs/2026-10-06-watch-con-avisos-design.md`

## Spec assessment and decisions

The spec is sound: the measurements justify A, B keeps every platform no worse, and the safety story (unmount works with watches on Linux, Windows needs `DBT_DEVICEQUERYREMOVE`) is right. What it leaves open or gets subtly wrong, and what this plan does about it:

1. **Open questions 1 and 2 (Windows handle, VeraCrypt on Windows) block only the Windows engine.** This plan is **phase 1**: B everywhere, inotify on Linux, Windows walks with B (approach C *for now*). Nothing in phase 1 is thrown away whatever the answers; the Windows engine is «Phase 2» at the end, not started.
2. **Open question 3 (the cap): adopt the proposal, plus a budget.** With notices there is no entry cap. But `max_user_watches` is **per user, shared with every other program** (VS Code, file managers, Dropbox): an agent that takes it all breaks the user's editor with «ENOSPC: System limit for number of file watchers reached». The agent never holds more than **half** of it (`PRESUPUESTO = 0.5`); a pair that would pass that walks instead, with the walk's 20 000-entry cap.
3. **Arming must not run on the agent loop.** The spec's 19 ms for 442 folders is with a hot cache; a cold USB stick takes seconds. `vigilar()` runs on the `Muestreo` thread (one at a time, already waited for by «Bloquear»/«Expulsar» through `_mirando()`), with a lock around the maps.
4. **«Un aviso despierta la vuelta» would spin during a big copy** (thousands of events → thousands of `vuelta()`s). Instead `Vigia` drains the descriptor when it is readable, mutes it for `CALLAR_AVISOS` (0.25 s) and keeps waiting until the tick. The pass waits for the 20 s calm anyway; a 2 s tick changes nothing the user sees. Draining in `Vigia` (not in `vuelta()`) also means an exception or an early return in `vuelta()` cannot leave a readable descriptor making `poll` return at once forever.
5. **Folder moves and overflow leave the watch tree stale.** A folder moved in (`IN_MOVED_TO|IN_ISDIR`) has subfolders with no watch; one moved out keeps watches that now report from outside; an `IN_Q_OVERFLOW` may have lost an `IN_CREATE|IN_ISDIR`. All three are `DESBORDADO`: counted as a change AND the pair is re-armed on the thread (`vigilar()` is idempotent and sweeps watches it no longer reaches). A folder *created* inside (`IN_CREATE|IN_ISDIR`) is armed inline: it is (nearly) empty when it is created.
6. **Overlapping pairs share watches.** `inotify_add_watch` on an inode already watched by the same descriptor returns the same `wd`, so a `local = "."` pair and a `sync-data/docs` pair share the docs subtree. The engine keeps `wd → {pairs}`; `dejar()` removes a watch only when no pair needs it. The top-level ignore rule (`IGNORAR_CAMBIOS`, `ruido_en()`) applies per pair, only to events in that pair's root watch.
7. **Pacing (B) exempts the keychain.** Its folder is a handful of files (a walk costs microseconds) and it is what matters most to have current; on Windows in phase 1 a 2-minute pace would delay every KeePassXC save. `a_recorrer()` walks the keychain every `sondeo`, also on battery.
8. **«Último cambio visto»** is a new field, `Vigilada.movida`, set only when a walk sees a change or a notice arrives (not by a baseline photo, not by a pass): a freshly connected, quiet pair walks every `sondeo_quieto`.
9. **`IN_ATTRIB` on a folder is not a change**, matching the walk (folders count by name only). `IN_CLOSE_WRITE` without `IN_MODIFY`, as the spec says: a file kept open and written forever (a VM disk, a mailbox) is only seen when it is closed — said in the doc.
10. **`statfs` → `/proc/self/mountinfo`.** The filesystem type comes from the mount entry whose mount point is the longest prefix of the folder (no `struct statfs` layout per architecture in `ctypes`). The network table also lists shared-with-another-system types (`9p`, `virtiofs`, `vboxsf`): the same reasoning, changes made on the other side never notify.
11. **`PERDIDA` is not a change**, as today: a deleted or moved-away pair folder makes the walk return no photo, and the interval (with `_bisync_preflight()`) decides.

## Global Constraints

- Pure stdlib, Python 3.11+; `ctypes` only in `common/avisos_carpeta.py`. No new dependency, no new thread on Linux.
- `common/planificador.py` stays PURE (no clock, disk, process).
- `install/` and `penwatch.py` untouched; `agente.py` imports `common.avisos_carpeta` lazily inside `poner_avisos_carpeta()` like `poner_red()` does with `common.red`.
- New indirection points keep the module-level shape: `agente.poner_avisos_carpeta()`, `avisos_carpeta.limite_de_vigilancias()`, `avisos_carpeta.sistema_de()`; registered in `docs/agents/reference/commands-testing.md`.
- Values pinned by the spec: `PoliticaCambios.sondeo_quieto = 120.0`, `sondeo_bateria = 60.0`; `sondeo` 10 s, `calma` 20 s, `separacion` 120 s, `tope_entradas` 20 000 unchanged. inotify mask exactly `IN_CLOSE_WRITE | IN_ATTRIB | IN_CREATE | IN_DELETE | IN_MOVED_FROM | IN_MOVED_TO | IN_DELETE_SELF | IN_MOVE_SELF` (plus the add flags `IN_ONLYDIR | IN_DONT_FOLLOW | IN_EXCL_UNLINK`); never `IN_MODIFY`.
- Comments, docstrings, log lines and status text in Spanish; docs under `docs/agents/` in English. Google-style docstrings (`docs/agents/code-writing-conventions.md`).
- The suite passes on Linux and Windows: Linux-only checks print `(saltado) …` elsewhere.
- Safety invariants in AGENTS.md are untouched; nothing here deletes or rewrites user data.

## Review Focus

1. **A big copy into a watched folder** (tens of thousands of files in a minute): the agent's loop still turns once per tick, the CPU goes to the copy, at most one pass follows the calm, and an overflow re-arms instead of losing new subfolders. → Task 3 `vigia: una ráfaga no adelanta la vuelta`; Task 2 `desbordado rearma`.
2. **A folder renamed inside the watched tree, then a file saved inside it**: the save is still seen. → Task 2 `una carpeta movida se sigue viendo tras rearmar`.
3. **Two pairs whose folders overlap** (`local = "."` and `sync-data/docs`): a save in docs reaches both; dropping one keeps the other hearing. → Task 2 `parejas solapadas`.
4. **The user's own editor needs inotify watches**: the agent never takes more than half of `max_user_watches`; past that the pair walks and says why. → Task 2 `presupuesto`; Task 4 `sin avisos: recorre y lo dice`.
5. **The root stops being served while arming is in flight** (its window opens, «Bloquear», unplugged): no watch is left behind and no notice of the old connection fires a pass. → Task 2 `dejar durante vigilar`; Task 4 `armado de una conexión vieja no cuenta`.

---

### Task 1: The walk spaces itself out (approach B) and the planner hears notices

**Files:**
- Modify: `common/planificador.py` (`PoliticaCambios`, `Vigilada`, `observar`, `tras_pasada`, `a_recorrer`; new `avisado`)
- Modify: `agente.py:2258` (`_vigilar` passes `con_bateria`)
- Test: `tests/test_watch_pareja.py` (planner section), `tests/test_agente_watch.py` (keep its wiring tests at the old pace; one B wiring check)

**Interfaces:**
- Produces: `PoliticaCambios.sondeo_quieto: float = 120.0`, `PoliticaCambios.sondeo_bateria: float = 60.0`; `Vigilada.avisos: bool = False` (the pair hears notices: never walked), `Vigilada.movida: float | None = None` (last change seen); `avisado(vigilada: Vigilada, ahora: float) -> Vigilada`; `a_recorrer(..., con_bateria: bool = False)`.

- [ ] **Step 1: Write the failing planner tests** (append to the planner part of `tests/test_watch_pareja.py`, reusing its `RAIZ`, `DOCS`, `T0`, `H1`, `H2`):

```python
V = pl.PoliticaCambios()
c("de fábrica, sondeo_quieto 120 s y sondeo_bateria 60 s", (V.sondeo_quieto, V.sondeo_bateria), (120.0, 60.0))
quieta = {DOCS: pl.Vigilada(H1, None, T0)}                       # sin cambio visto
c("quieta: no a los 10 s", pl.a_recorrer([RAIZ], quieta, T0 + 10), [])
c("  sí a los sondeo_quieto", pl.a_recorrer([RAIZ], quieta, T0 + 120), [DOCS])
movida = {DOCS: pl.Vigilada(H2, None, T0, movida=T0)}
c("tras un cambio visto, cada sondeo", pl.a_recorrer([RAIZ], movida, T0 + 10), [DOCS])
c("  hasta sondeo_quieto después", pl.a_recorrer([RAIZ], {DOCS: pl.Vigilada(H2, None, T0 + 115, movida=T0)}, T0 + 125), [])
c("a batería, nunca antes de sondeo_bateria", (pl.a_recorrer([RAIZ], movida, T0 + 10, con_bateria=True), pl.a_recorrer([RAIZ], movida, T0 + 60, con_bateria=True)), ([], [DOCS]))
c("observar un cambio apunta movida", pl.observar(pl.Vigilada(H1, None, T0), H2, T0 + 10).movida, T0 + 10)
c("  la foto de partida no", pl.observar(pl.Vigilada(), H1, T0).movida, None)
c("tras_pasada conserva avisos y movida", (lambda t: (t.avisos, t.movida, t.cambio))(pl.tras_pasada(pl.Vigilada(None, T0, T0, avisos=True, movida=T0), None, T0 + 5)), (True, T0, None))
c("una pareja con avisos no se recorre", pl.a_recorrer([RAIZ], {DOCS: pl.Vigilada(avisos=True)}, T0 + 3600), [])
a = pl.avisado(pl.Vigilada(avisos=True), T0)
c("avisado pone el cambio y movida a ahora", (a.cambio, a.movida), (T0, T0))
c("  una abandonada no cambia", pl.avisado(pl.Vigilada(abandonada=True), T0), pl.Vigilada(abandonada=True))
c("  y la pasada se adelanta como con una foto", pl.toca_por_cambios(a, pl.Marca(T0 - 500)), T0 + V.calma)
llave = pl.Raiz("u", (pl.Pareja("keychain", "nas", vigila=True, llavero=True),), 3600.0)
c("el llavero va siempre al sondeo, también a batería", pl.a_recorrer([llave], {("u", "keychain"): pl.Vigilada(H1, None, T0)}, T0 + 10, con_bateria=True), [("u", "keychain")])
```

- [ ] **Step 2: Run** `python tests/test_watch_pareja.py` — expected: FAIL (`sondeo_quieto` / `movida` / `avisado` missing).

- [ ] **Step 3: Implement in `common/planificador.py`.** `observar()` sets `movida=ahora` with `cambio`; `tras_pasada()` becomes `replace(vigilada, huella=huella, cambio=None, revisada=ahora, fallidas=…)` (keeps `avisos`, `movida`); `avisado()` as asserted; `a_recorrer()` skips `v.avisos` and walks when `revisada is None` or `ahora - revisada >= _cada(pareja, v, ahora, politica, con_bateria)`, where `_cada` is `sondeo` for `pareja.llavero`, else `sondeo` if `movida` is within `sondeo_quieto`, else `sondeo_quieto`, raised to `sondeo_bateria` on battery. Update the module docstring's watch bullet and the `PoliticaCambios`/`Vigilada` docstrings.

- [ ] **Step 4: Wire the battery and keep the old wiring tests meaningful.** `agente._vigilar` passes `con_bateria=self.entorno.con_bateria`. In `tests/test_agente_watch.py`: `CAMBIOS = pl.PoliticaCambios(sondeo_quieto=pl.PoliticaCambios().sondeo)` and a local `nuevo()` that returns `F.nuevo()` with `ag.cambios = CAMBIOS` (sections 1–12 test wiring at the old pace; `ag5` keeps `tope_entradas=5` on top of it). Add section 13 with the factory policy: quiet pair walked about every 120 s over 400 s (3–4 walks), and after `moderacion.energia = Energia(con_bateria=True, porcentaje=80)` about every 60 s once a change was seen.

- [ ] **Step 5: Run** `python tests/test_watch_pareja.py && python tests/test_agente_watch.py && python tests/test_agente_llavero.py && python tests/test_planificador.py` — expected: all OK.

- [ ] **Step 6: Commit** `git commit -m "watch: el recorrido se espacia con la carpeta quieta y a batería"`

---

### Task 2: `common/avisos_carpeta.py`, inotify on Linux

**Files:**
- Create: `common/avisos_carpeta.py`
- Modify: `common/huella.py` (rename `_se_ignora` → public `se_ignora`, same behaviour)
- Test: `tests/test_avisos_carpeta.py` (new; Linux-only checks, `(saltado)` elsewhere)

**Interfaces:**
- Produces:
  - Constants `CAMBIO = "cambio"`, `DESBORDADO = "desbordado"`, `PERDIDA = "perdida"`; `class Aviso(NamedTuple): tipo: str; motivo: str = ""`. Precedence when several arrive for one pair before `recoger()`: `PERDIDA` > `DESBORDADO` > `CAMBIO`.
  - `DE_RED: frozenset[str]` (fstype names: `nfs`, `nfs4`, `cifs`, `smb3`, `smbfs`, `ncpfs`, `afs`, `ceph`, `glusterfs`, `lustre`, `9p`, `virtiofs`, `vboxsf`, `fuse.sshfs`, `fuse.rclone`, `fuse.gvfsd-fuse`, `fuse.s3fs`, `fuse.vmhgfs-fuse`, `davfs`, `fuse.davfs2`, `fuse.curlftpfs`); `PRESUPUESTO = 0.5`.
  - `limite_de_vigilancias() -> int` (reads `/proc/sys/fs/inotify/max_user_watches`; 8192 if unreadable); `sistema_de(carpeta: Path | str) -> str` (fstype of the longest mount-point prefix of its realpath in `/proc/self/mountinfo`, octal escapes undone; `""` if unknown). Both indirection points.
  - `abrir() -> Inotify | None` (`None` off Linux; raises `OSError` if `inotify_init1` fails).
  - `class Inotify`: `fd: int`; `vigilar(clave: tuple[str, str], carpeta: Path, ignorar: tuple[str, ...]) -> str | None` (`None` = armed; else the Spanish reason it walks; idempotent: re-arming refreshes and sweeps); `dejar(clave)`; `dejar_raiz(uid: str)`; `leer() -> None` (drains the fd into pending; never raises on `EAGAIN`); `recoger() -> dict[tuple[str, str], Aviso]` (`leer()` then hand over and clear); `descartar(clave)` (`leer()` then drop that pair's pending); `cerrar()`. Thread-safety: `vigilar()` may run on another thread than the rest (`threading.RLock`, held per watch added, never across a `scandir`); `dejar()` during `vigilar()` cancels it (it undoes what it added and returns `"dejada"`). `_add_watch(ruta: str) -> int` and `_rm_watch(wd: int)` are methods so a test can make them fail.

- [ ] **Step 1: Write the failing tests** in `tests/test_avisos_carpeta.py`. A helper `esperar_aviso(motor, clave, segundos=2)` polls `motor.recoger()`. Checks (each a `c(...)` with these assertions):
  - `vigilar` on a temp tree with `sub/` and `.prversions/` returns `None`; `recoger()` is `{}` right after.
  - `CAMBIO` after each of: create a file, write+close an existing one, `os.rename` a file, delete one, `os.utime` one, create `nueva/` and then `nueva/f.txt` (the second write is seen too, i.e. the new folder got its own watch).
  - Writing inside `.prversions/` and `.prdrive/` at the pair root, and `chmod` of `sub/` (an `IN_ATTRIB` on a folder): `{}`.
  - `local = "."` style: patterns from `model.RUIDO_DEL_SISTEMA` passed in `ignorar` → a file created in `$RECYCLE.BIN/` at the root: `{}`.
  - Moving `sub/` to `otra/` → `DESBORDADO`; after `vigilar()` again, a write in `otra/` → `CAMBIO`, a write in a folder moved OUT of the tree → `{}` (`una carpeta movida se sigue viendo tras rearmar`).
  - **Parejas solapadas**: `vigilar(("u","raiz"), T, ())` and `vigilar(("u","docs"), T/"docs", ())`; a write in `docs/` → both keys `CAMBIO`; `dejar(("u","docs"))`; another write → only `("u","raiz")`.
  - Removing the pair folder → `PERDIDA` with a non-empty `motivo`.
  - **Presupuesto**: `avisos_carpeta.limite_de_vigilancias = lambda: 6` before `abrir()`, a tree with 5 folders → a reason containing `"carpetas"`; afterwards `motor._wd_ruta == {}` (nothing left behind).
  - **ENOSPC**: `motor._add_watch` raising `OSError(errno.ENOSPC, …)` on the third call → reason containing `"max_user_watches"`; nothing left behind.
  - **Red**: `avisos_carpeta.sistema_de = lambda c: "nfs4"` → reason containing `"nfs4"`, no watch added.
  - **sistema_de** of `/proc` is `"proc"`; of a path under this temp dir is non-empty.
  - **dejar durante vigilar**: `_add_watch` wrapped to call `motor.dejar(clave)` on its second call → `vigilar()` returns `"dejada"` and `_wd_ruta == {}`.
  - **desbordado rearma**: feed `_procesar(-1, IN_Q_OVERFLOW, 0, "")` → every armed pair `DESBORDADO`.
  - Optional, root only: mount a `tmpfs`, arm a pair inside, `umount` succeeds (`rc == 0`) and the pair gets `PERDIDA`; otherwise `(saltado) sin permisos para montar`.

- [ ] **Step 2: Run** `python tests/test_avisos_carpeta.py` — expected: FAIL (`ModuleNotFoundError: common.avisos_carpeta`).

- [ ] **Step 3: Implement `common/avisos_carpeta.py`.** Module docstring cites inotify(7) for each flag and states the contract (whether a folder changed, not which file), the overlap, the budget and what is not seen (other machines on a network folder; a file written but never closed). Event handling, per `struct inotify_event` (`"iIII"` + `len` name bytes, `os.fsdecode`):
  - `wd == -1` / `IN_Q_OVERFLOW` → `DESBORDADO` for every armed pair.
  - `IN_IGNORED` → forget the wd (no `rm_watch`); `PERDIDA` for the pairs whose root it was. `IN_UNMOUNT` → `PERDIDA` for every pair of that wd. `IN_DELETE_SELF`/`IN_MOVE_SELF` on a pair's root → `PERDIDA`; on a subfolder → nothing (the parent already told).
  - Named events: skipped for a pair when the wd is that pair's root and `huella.se_ignora(nombre, patrones)`; `IN_ATTRIB|IN_ISDIR` skipped; `IN_MOVED_FROM|IN_MOVED_TO` with `IN_ISDIR` → `DESBORDADO`; anything else → `CAMBIO`. `IN_CREATE|IN_ISDIR` also arms the new folder inline for the pairs that did not skip it (watch first, then `scandir`, children recursively; `ENOSPC`/budget there → `PERDIDA` with the reason).
  - `vigilar()`: `sistema_de()` in `DE_RED` → reason; register the pair; walk folders only (`is_dir(follow_symlinks=False)`, top-level ignore, `PermissionError`/`FileNotFoundError` on a subfolder skipped, on the root → reason); a new wd past `int(limite_de_vigilancias() * PRESUPUESTO)` → undo, reason; finally sweep the pair out of wds it no longer reached.

- [ ] **Step 4: Run** `python tests/test_avisos_carpeta.py && python tests/test_watch_pareja.py` — expected: OK.

- [ ] **Step 5: Commit** `git commit -m "watch: avisos de inotify para saber si una carpeta ha cambiado"`

---

### Task 3: `Vigia` hears the descriptor without turning faster

**Files:**
- Modify: `agente.py` (`Vigia.__init__`, new `Vigia.oir()`, `Vigia.esperar()`; constant `CALLAR_AVISOS = 0.25`)
- Test: `tests/test_avisos_carpeta.py` (Vigia section, Linux)

**Interfaces:**
- Consumes: `Inotify.fd`, `Inotify.leer()` (Task 2).
- Produces: `Vigia.oir(fd: int, leer: Callable[[], None]) -> None` (no-op on Windows or without `poll`). `esperar(segundos)` keeps its contract (returns `True` only for a mount change; ends early only for the wake pipe or mountinfo).

- [ ] **Step 1: Write the failing tests**: with a real `Inotify` armed on a temp folder and `vigia.oir(motor.fd, contar_y_leer)`:
  - `vigia: una ráfaga no adelanta la vuelta` — a thread writes 2 000 files during `vigia.esperar(1.0)`: it returns after ≥ 0.9 s, returns `False`, and the drain counter is ≤ `1.0 / agente.CALLAR_AVISOS + 2`.
  - After it, `motor.recoger()` has `CAMBIO` (drained events are kept, not lost).
  - `vigia.despertar()` still ends the wait at once while the descriptor is muted.
  - A `leer` that raises is unregistered: the next `esperar(0.3)` takes ≥ 0.25 s (no spin).

- [ ] **Step 2: Run** — expected: FAIL (`Vigia` has no `oir`).

- [ ] **Step 3: Implement.** `esperar()` loops until the deadline: the pipe and mountinfo end it (compare `fd` with `self._f.fileno()`, not "any other fd"); the heard fd calls `leer()`, then `self._poll.modify(fd, 0)` until `CALLAR_AVISOS` later; restore `POLLIN` before returning; `poll()` timeouts with `math.ceil` so sub-millisecond rests do not busy-loop.

- [ ] **Step 4: Run** `python tests/test_avisos_carpeta.py && python tests/test_bandeja.py` — expected: OK (the existing Vigia checks in `test_bandeja.py` still pass).

- [ ] **Step 5: Commit** `git commit -m "agente: el vigía lee los avisos de carpeta sin dar más vueltas"`

---

### Task 4: The agent arms, hears and falls back

**Files:**
- Modify: `agente.py` — `Mirar` (`armar: bool = False`), `Muestreo` (`avisos`, `armadas`), `Agente` (fields `avisos_carpeta: Any = None`, `sin_avisos: dict[tuple[str, str], str]`, `rearmar: set[tuple[str, str]]`), `_vigilar`, new `_recoger_avisos`, `_recoger_fotos` (arm results), `_rehacer_foto`, `_olvidar_vigiladas`, `_bloqueos`, `_expulsiones`, `_vigilancia`/`resumen` (`vigila_recorre`), `cmd_status`, new `poner_avisos_carpeta(agente, vigia)`, `cmd_run` (set it up and close it); module docstring bullet «Mira los cambios locales».
- Test: `tests/test_agente_watch.py` (new sections with a fake engine)

**Interfaces:**
- Consumes: Task 1 (`Vigilada.avisos`, `pl.avisado`), Task 2 (`Aviso`, `CAMBIO`/`DESBORDADO`/`PERDIDA`, the `Inotify` methods), Task 3 (`Vigia.oir`).
- Produces: `poner_avisos_carpeta(agente: Agente, vigia: Vigia) -> Any` (indirection point; `None` on Windows or when `abrir()` fails, said once in `agente.log`); `resumen()["unidades"][i]["vigila_recorre"]: dict[str, str]` (pair → why it walks); `status` line `  Recorre su carpeta (sin avisos del sistema): docs (<motivo>)`.

Behaviour to implement (each line is pinned by a test below):
- A watched pair served for the first time this serving period gets `Vigilada(avisos=True)` and an arm job (`Mirar(..., armar=True)`) in the next `Muestreo`, before any walk; arming ignores moderation (it is how notices keep being recorded while moderated).
- Arm result `None` → stays armed; a reason → `Vigilada()` (walks, baseline first), `sin_avisos[clave] = motivo`, one line in `agente.log` and the root's `daemon.log`. A result for a pair no longer valid, or from an older `Conexion`, calls `dejar(clave)` and is otherwise dropped.
- Every turn `_recoger_avisos()` (before `_recoger_fotos()`): notices for pairs not valid, not armed, or with their pass running are dropped; `CAMBIO` → `pl.avisado`; `DESBORDADO` → `pl.avisado` + `rearmar`; `PERDIDA` → `dejar`, `Vigilada()`, `sin_avisos` with its `motivo`, one log line.
- `_rehacer_foto()` of an armed pair: `descartar(clave)`, `pl.tras_pasada(v, None, ahora)` (stays armed; no photo asked).
- A pair that stops being served, or a root that (re)connects or goes: `dejar` / `dejar_raiz`, and `sin_avisos`/`rearmar` forgotten for it.
- «Bloquear» and «Expulsar»: `dejar_raiz(uid)` right before `_soltar(con)` and the launch.

- [ ] **Step 1: Write the failing tests** (new sections 14–16 in `tests/test_agente_watch.py`). `AvisosFalsos` records `("vigilar"|"dejar"|"dejar_raiz"|"descartar", arg)` in `LLAMADAS` (also appended to a shared `ORDEN` list that the fake `expulsar.expulsar` and `agente.lanzar` append to), returns `MOTIVOS.get(clave)` from `vigilar`, and `recoger()` hands over `PENDIENTES`. `ag.avisos_carpeta = AvisosFalsos()` after `nuevo()`.
  - `una pareja con avisos no se recorre`: after connecting and the first passes, `("vigilar", (UID, "docs"))` in `LLAMADAS`, `mirada() == 0` over 300 s, `ag.vigiladas[(UID, "docs")].avisos is True`.
  - `un aviso es una pasada tras la calma`: `PENDIENTES[(UID,"docs")] = Aviso(CAMBIO)` → `hasta_pasada(ag, 60)` ≥ `calma`, `por_cambios`.
  - `un aviso con su pasada en marcha no cuenta`: aviso queued while docs' pass runs; after it ends (`descartar` called), no second pass in 200 s.
  - `DESBORDADO` → a pass and a second `vigilar` of that pair.
  - `PERDIDA vuelve a recorrer`: `mirada() > 0` afterwards, `ag.vigiladas[..].avisos is False`, one diary line containing the motivo, `vigila_recorre == {"docs": motivo}`, `status` prints `Recorre su carpeta`.
  - `sin avisos: recorre y lo dice`: `MOTIVOS[(UID,"docs")] = "carpeta de red (nfs4): …"` → walked, said once in diary and `daemon.log`.
  - With moderation (battery 10 %): a `CAMBIO` makes no pass while held for 120 s; releasing it → a pass within `2*TICK` (the change was recorded while held and its calm is long over).
  - `armado de una conexión vieja no cuenta`: an arm result whose `Mirar.con` is an older `Conexion` → `("dejar", clave)` recorded and the pair not armed.
  - A root paused from its window → `("dejar", (UID,"docs"))`; resumed → `vigilar` again.
  - Unplugged → `("dejar_raiz", UID)`.
  - **«Expulsar» y «Bloquear»**: in `ORDEN`, `("dejar_raiz", uid)` comes before the eject call / the VeraCrypt launch (section 12's setup for «Bloquear»; `F.COMPATIBLES` for «Expulsar»).
  - Without an engine (`avisos_carpeta = None`) sections 1–13 behave as before (they already run that way).

- [ ] **Step 2: Run** `python tests/test_agente_watch.py` — expected: the new sections FAIL.

- [ ] **Step 3: Implement** the behaviour list above. `poner_avisos_carpeta()`: off Linux → `diario("en este sistema las carpetas vigiladas se recorren (cada 10 s tras un cambio, cada 2 min quietas)")`, `None`; on Linux `avisos_carpeta.abrir()`, `vigia.oir(motor.fd, motor.leer)`, `diario("oigo los cambios de las carpetas vigiladas (inotify)")`; an `OSError` → said, `None`. With no engine, `_vigilancia()` reports every walked pair with the reason «este sistema no avisa de los cambios de las carpetas».

- [ ] **Step 4: Run** `python tests/run_all.py` — expected: all OK.

- [ ] **Step 5: Commit** `git commit -m "agente: las parejas vigiladas oyen los avisos del sistema y recorren solo sin ellos"`

---

### Task 5: Docs, rules, checklist, measurement

**Files:**
- Modify: `docs/agents/reference/agent-scheduling.md` («Files» line; the `watch = true` section: notices first, walk as fallback with its pace, the budget, overlap, what is not seen, status keys), `docs/agents/reference/agent.md` (Linux: a watch does not hold a mount; nothing else stays open), `docs/agents/reference/commands-testing.md` (indirection registry), `.claude/rules/agent-scheduling.md` (`common/avisos_carpeta.py`, `tests/test_avisos_carpeta.py`), `AGENTS.md` (layout line: `avisos_carpeta`), `docs/superpowers/pruebas/2026-09-25-equipo-pendiente-en-real.md` (rows F9–F12: exFAT and FAT32 sticks on L, «Expulsar»/`eject`/VeraCrypt «Bloquear» with watches on L, a network folder on L falls back, VS Code + the agent on a small `max_user_watches`), the spec (status: phase 1 implemented, questions 1–2 open, 3 decided with the budget).
- Test: `tests/test_reglas_claude.py`, `tests/run_all.py`

- [ ] **Step 1: Write the docs** as listed.
- [ ] **Step 2: Measure.** A scratch script (not committed) arms an `Inotify` on 15 000 files in 442 folders, waits 30 s in `Vigia.esperar(TICK)` loops with `leer` registered, and prints `resource.getrusage` CPU per second; record the number in the spec's «Lo medido». Criterion: the engine at rest adds ≪ 1 ms/s.
- [ ] **Step 3: Run** `python tests/run_all.py` — expected: all OK, including `test_reglas_claude.py`.
- [ ] **Step 4: Commit** `git commit -m "docs: watch con avisos del sistema (fase 1)"`

---

### Phase 2: the Windows engine

Decided 06/10/2026: question 1 **accepted** (a directory handle per watched pair stays open between passes, closed when the system asks for the drive and before «Expulsar»/«Bloquear»); question 2 as the spec proposes (VeraCrypt volumes walk until checked on real hardware). Real-hardware tests are marked pending in the checklist.

Decisions on top of the spec:
- **VeraCrypt is detected per volume, not per root**: `QueryDosDeviceW("X:")` starting with `\Device\VeraCryptVolume` (VeraCrypt's `NT_MOUNT_PREFIX`) or `\Device\TrueCryptVolume`. It covers the host root and a stick's container opened by `Abrir PRDRIVE` (`Unidad.cifrada` only knows the first).
- **One watcher thread issues every `ReadDirectoryChangesW`**, so no I/O belongs to the short-lived `Muestreo` thread. `vigilar()` asks it through a request queue and a control event and waits for the answer. `dejar()` and the tray's `DBT_DEVICEQUERYREMOVE` close the handle in their own thread (`CancelIoEx` + `CloseHandle`): Windows waits for the handle to be closed before it answers the user. The watcher keeps the event and buffer of a closed handle until its cancelled read completes. Every `wd`-like map is under one lock.
- **It never wakes the agent's loop**: it re-issues each read at once (the kernel buffer never fills between ticks) and `recoger()` hands over at the tick.
- **No re-arming on Windows**: `bWatchSubtree` follows moves and new folders. Overflow (0 bytes, `ERROR_NOTIFY_ENUM_DIR`) is `DESBORDADO`, and re-arming an armed pair is a no-op. Any other read error is `PERDIDA`.
- **No notification registration, no handle**: if `RegisterDeviceNotificationW` fails, the handle is closed and the pair walks. No tray, no engine.
- **Device events**: `QUERYREMOVE` closes the handle and keeps the pair suspended (it hears nothing and does not walk: the drive is leaving); `QUERYREMOVEFAILED` reopens it; `REMOVEPENDING`/`REMOVECOMPLETE` are `PERDIDA`.
- **At most 63 pairs** (`WaitForMultipleObjects`' 64 minus the control event); past that the pair walks.

### Task 6: `ReadDirectoryChanges` engine

**Files:** Modify `common/avisos_carpeta.py` (`Win32`, `ReadDirectoryChanges`, `avisos_de_windows()`, `abrir(hwnd=None)`); Test `tests/test_avisos_carpeta.py` (fake `Win32` everywhere; the real one only on Windows).

**Interfaces:** Produces `avisos_de_windows(datos: bytes) -> list[tuple[int, str]]` (`FILE_NOTIFY_INFORMATION`: action, relative name); `ReadDirectoryChanges(api, hwnd, tam_bufer=64 KiB)` with the `Inotify` methods (`fd` is `None`, `leer()` a no-op) plus `dispositivo(evento: int, handle: int) -> None`; `abrir(hwnd: int | None = None)`: Linux → `Inotify`, Windows → `ReadDirectoryChanges` if `hwnd`, else `None`.

- [ ] Tests (fake): parsing of a 2-entry buffer; armed → read issued, `vigilancias() == 1`; a completion with a name → `CAMBIO`, with `.prversions\x` → nothing; 0 bytes / `ERROR_NOTIFY_ENUM_DIR` → `DESBORDADO` and read re-issued; another error → `PERDIDA` and handle closed; `DRIVE_REMOTE` → reason, nothing opened; VeraCrypt device → reason, nothing opened; registration fails → reason, handle closed; `dejar()` closes handle + unregisters and the zombie's event is closed when its read completes; `dejar` during `vigilar` → `DEJADA`; QUERYREMOVE closes the handle, keeps registration, no notice; FAILED reopens (a new read); REMOVECOMPLETE → `PERDIDA`; the 64th pair → reason; `cerrar()` joins the thread with nothing open.
- [ ] Tests (real, Windows only): a temp folder: a write → `CAMBIO`; `.prversions` → nothing; tiny buffer → `DESBORDADO`; after `dejar()` the folder can be deleted; `dispositivo_de("C:")` is not VeraCrypt; `tipo_de_unidad` of the temp drive is not `DRIVE_REMOTE`.
- [ ] Implement, run `python tests/test_avisos_carpeta.py`, commit.

### Task 7: the tray routes handle events

**Files:** Modify `ui/bandeja_windows.py` (`Bandeja.dispositivo`, `Api.handle_de(lparam) -> int | None`, constants); Test `tests/test_bandeja_windows.py`.

- [ ] Tests: `WM_DEVICECHANGE` with `DBT_DEVICEQUERYREMOVE` and a handle header → `dispositivo(0x8001, h)` called on the tray thread before the window answers; a volume header (not a handle) → not called; `REMOVECOMPLETE` still wakes `montajes()`; without `dispositivo` set nothing breaks.
- [ ] Implement, run, commit.

### Task 8: the agent on Windows, docs

**Files:** Modify `agente.py` (`poner_avisos_carpeta()`: on Windows needs the tray's `hwnd`, wires `bandeja.dispositivo`; `Vigia.oir()` only with an `fd`), `tests/test_agente_watch.py`; docs: `agent-scheduling.md`, `agent.md` (the invariant rewritten for Windows), `commands-testing.md`, the checklist (W rows marked pending), the spec status.

- [ ] Tests: with `IS_WIN` forced and a fake tray with `hwnd`, `poner_avisos_carpeta()` returns the engine and sets `bandeja.dispositivo`; without tray it returns `None` and says the pairs walk.
- [ ] Implement, docs, `python tests/run_all.py`, commit, push.
