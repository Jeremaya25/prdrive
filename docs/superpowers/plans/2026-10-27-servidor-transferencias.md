# «Servidor…» piece 2: download and upload — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** from the «Servidor» explorer, download selected files/folders to the computer and upload files or a folder to the folder being shown, one `sync/copy` per batch, with a single overwrite/skip prompt, pair-mode warnings/blocks, and a progress panel with Cancel.

**Architecture:** `common/rcd.py` gains four thin rc wrappers (`copiar`, `progreso`, `estado`, `cancelar`). A new pure module `ui/transferencia.py` decides everything (filter rules, fs strings, collision count, pair warnings/blocks, progress and result texts). A new draw-only module `ui/tk_transferencia.py` holds the progress panel and the three-way collision dialog. `ui/tk_servidor.py` wires buttons, multi-select, system file dialogs and the batch flow.

**Tech Stack:** Python 3.11+ stdlib only, Tk 9 (`ttk.Treeview`, `ttk.Progressbar`, `tkinter.filedialog`), plain-script tests (`tests/_harness.Checks`).

**Spec:** `docs/superpowers/specs/2026-10-27-servidor-transferencias-design.md` (piece 1: `docs/agents/reference/servidor.md`).

## Global Constraints

- Stdlib only; imports on 3.11; `import tkinter` (and `tkinter.filedialog`) only inside functions; `ui/transferencia.py` imports no Tk and touches no disk or network.
- Spanish comments/docstrings/UI text; `docs/agents/` in English; read `docs/agents/code-writing-conventions.md` and `docs/agents/reference/servidor.md` first.
- `tk_*` modules: colours/fonts/glyphs from `theme`/`icons`, distances via `theme.medida()`/`theme.E*`; nothing Tk inside work sent to `segundo_plano`; `rcd.arrancar()` only on the Tk thread (unchanged here).
- **Copies are always `sync/copy`. Never `sync/sync`, `sync/move`, `operations/purge`, `deletefile` or anything that deletes.**
- Remote fs strings always through the absolute root: `"<remote>:/<ruta sin barra inicial>"` (as piece 1).
- Tests never start rclone nor touch the network: replace `rcd.peticion` or pass a fake `Rcd`; replace the module-level dialog functions.
- Every new source/test goes in `.claude/rules/servidor.md` `paths`; a Tk test goes in `GUI` in `tests/run_all.py`.
- Verify with `python3 tests/run_all.py --cambios -j auto`; Tk tests with `PY=/tmp/claude-0/-home-user-prdrive/a9227951-c24b-54b6-9582-83a4e18c5019/scratchpad/ci/runtime/bin/python3; xvfb-run -a $PY tests/<f>.py`. Commit footer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` + `Claude-Session: https://claude.ai/code/session_0158B15k9NNa1wRurV7n183V`.
- Exact copy:
  - buttons `Bajar…`, `Subir archivos…`, `Subir carpeta…`, `Cancelar`, `Reintentar`;
  - collision dialog: title `Ya existen`, text `{n} elementos ya existen en {destino}. ¿Sobrescribirlos u omitirlos?` (`1 elemento ya existe en {destino}. ¿Sobrescribirlo u omitirlo?` when n == 1), buttons `Sobrescribir`, `Omitir`, `Cancelar` (default focus `Cancelar`);
  - indicator while counting: `Mirando el destino…`;
  - panel titles `Subiendo a {destino}` / `Bajando a {destino}`; line `{hechos} de {total} archivos · {bytes} de {total_bytes}`; line `{velocidad}/s · quedan {eta}`; `Cancelando…`;
  - results: `Copiados {x}` + (` · omitidos {y}` when y > 0) (tone ok); `Cancelado: copiados {x} de {n}` (tone aviso); permission error `No tienes permiso para escribir en {destino}.`, other errors through `servidor.frase_error` (tone aviso, with `Reintentar`);
  - close prompt: title `Transferencia en marcha`, text `Hay una transferencia en marcha. ¿Cancelarla y cerrar?`, buttons `Cancelar y cerrar` / `Seguir`;
  - pair texts (upload): `bisync` `Lo que subas a «{pareja}» lo bajará al dispositivo su próxima pasada; si sobrescribes algo que también ha cambiado allí, saldrá un conflicto.` · `down`/`down-mirror` `Lo que subas a «{pareja}» lo bajará al dispositivo su próxima pasada.` · `up` `«{pareja}» solo sube del dispositivo: lo que subas aquí se quedará en el servidor.` · `up-mirror` (block) `«{pareja}» deja el servidor igual que el dispositivo: lo que subas aquí lo borraría su próxima pasada. Súbelo a su carpeta del dispositivo.`;
  - pair texts (download): `bisync` `Lo que bajes a la carpeta de «{pareja}» lo subirá al servidor su próxima pasada.` · `up`/`up-mirror` `Lo que bajes a la carpeta de «{pareja}» lo subirá al servidor su próxima pasada.` · `down` `«{pareja}» solo baja del servidor: lo que bajes aquí se quedará en el dispositivo.` · `down-mirror` (block) `«{pareja}» deja su carpeta igual que el servidor: lo que bajes aquí lo borraría su próxima pasada. Bájalo fuera de ella.`;
  - warning dialog title `Carpeta de una pareja`, buttons `Seguir` / `Cancelar`; block dialog title `No se puede`.

## Review Focus

1. **Names with rclone pattern characters** (`* ? [ ] { } \`, a leading `!`/`+`/`-`, spaces, accents) must copy exactly the chosen item and nothing else. Test in Task 2 (rules) and Task 6 (the rules reach `rcd.copiar`).
2. **A selection mixing files and folders, and a folder that already exists in the destination** — a pre-existing folder is merged, not counted; only files count. Test in Task 2.
3. **The upload target being an ANCESTOR of a pair** (upload `notas/` into `/datos` when a pair lives in `/datos/notas`) and the download target being an ancestor of a pair's local folder. Test in Task 3.
4. **Closing the window, or the rcd dying, while a batch runs**: close asks; «Cancelar y cerrar» stops the job before `parar()`; a late progress answer paints nothing. Test in Task 6.
5. **Missing/zero stats fields** (`totalBytes` 0 before the listing finishes, `eta` null, no `transferring`): the panel shows an indeterminate bar, never raises. Test in Task 4.

---

### Task 1: rc transfer wrappers in `common/rcd.py`

**Files:** Modify `common/rcd.py`; Test `tests/test_rcd.py`.

**Interfaces — Produces:**
- `copiar(r: Rcd, origen: str, destino: str, reglas: list[str], omitir: bool, grupo: str) -> int`
- `progreso(r: Rcd, grupo: str) -> dict` (`core/stats {"group": grupo}`)
- `estado(r: Rcd, jobid: int) -> dict` (`job/status {"jobid": jobid}`)
- `cancelar(r: Rcd, jobid: int) -> None` (`job/stop`; swallows `ErrorRc` — a finished job answers an error)

- [ ] **Step 1: failing tests** with a fake `Rcd` recording `llamar(metodo, params)`:

```python
jid = rcd.copiar(falso, "nas:/datos", "/home/u/Descargas", ["/a.txt", "/c/**"], omitir=False, grupo="lote-1")
c("es sync/copy", falso.llamadas[-1][0], "sync/copy")
c("con lo elegido", falso.llamadas[-1][1], {"srcFs": "nas:/datos", "dstFs": "/home/u/Descargas",
  "createEmptySrcDirs": True, "_filter": {"IncludeRule": ["/a.txt", "/c/**"]}, "_async": True, "_group": "lote-1"})
c("devuelve el jobid", jid, 7)
rcd.copiar(falso, "a", "b", ["/x"], omitir=True, grupo="g")
c("omitir es IgnoreExisting", falso.llamadas[-1][1]["_config"], {"IgnoreExisting": True})
c("nunca otro método de sync", {m for m, _ in falso.llamadas if m.startswith("sync/")}, {"sync/copy"})
# cancelar → job/stop {"jobid": 7}; con ErrorRc("job not found", 500) no lanza
# progreso → core/stats {"group": "g"}; estado → job/status {"jobid": 7}
```

- [ ] **Step 2:** run `python3 tests/test_rcd.py` → FAIL. **Step 3:** implement (each a few lines over `r.llamar`). **Step 4:** run → PASS; `--cambios` PASS. **Step 5:** commit «Servidor: rcd sabe copiar un lote, seguirlo y cancelarlo».

---

### Task 2: `ui/transferencia.py` — batch, filter rules, fs strings, collisions

**Files:** Create `ui/transferencia.py`, `tests/test_transferencia.py`; Modify `.claude/rules/servidor.md` (add both).

**Interfaces — Produces:**
- `@dataclass(frozen=True) Elemento(nombre: str, es_carpeta: bool)`
- `@dataclass(frozen=True) Lote(sentido: str, remote: str, ruta_remota: str, carpeta_local: str, elementos: tuple[Elemento, ...])` — `sentido` is `BAJAR = "bajar"` or `SUBIR = "subir"`; `ruta_remota` is the remote folder (source when downloading, destination when uploading) in `remote_picker.normalizar` form; `carpeta_local` likewise for the computer side.
- `reglas_de(elementos) -> list[str]`: file `x` → `/x`; folder `x` → `/x/**`. Escape every rclone glob metacharacter `\ * ? [ ] { }` with `\`; a name starting with `!`, `+` or `-` is safe because each rule is passed as its own `IncludeRule` entry (no `+ `/`- ` prefix parsing) — test it anyway.
- `fs_de(lote) -> tuple[str, str]`: `(origen, destino)`; remote side `f"{remote}:/{ruta_remota.lstrip('/')}"` (so the root is `"nas:/"`), local side `carpeta_local` as given.
- `choques(rutas_origen: set[str], rutas_destino: set[str]) -> int`: count of origin **file** paths (relative, `/`-separated) present in destination. Callers pass files only; directories are not in either set.
- `texto_choques(n: int, destino: str) -> str`: the exact copy (singular/plural).

- [ ] **Step 1: failing tests**:

```python
E = transferencia.Elemento
c("archivo", transferencia.reglas_de([E("a.txt", False)]), ["/a.txt"])
c("carpeta", transferencia.reglas_de([E("fotos", True)]), ["/fotos/**"])
c("patrones escapados", transferencia.reglas_de([E("raro [1]*?{x}\\", True)]), ["/raro \\[1\\]\\*\\?\\{x\\}\\\\/**"])
c("espacios y acentos tal cual", transferencia.reglas_de([E("Música antigua", True)]), ["/Música antigua/**"])
c("un ! o un - al principio no son reglas", transferencia.reglas_de([E("!x", False), E("- y", False)]), ["/!x", "/- y"])
L = transferencia.Lote
c("bajar desde la raíz", transferencia.fs_de(L("bajar", "nas", "/", "/home/u/D", ())), ("nas:/", "/home/u/D"))
c("subir a una carpeta", transferencia.fs_de(L("subir", "nas", "/datos/x", "/home/u", ())), ("/home/u", "nas:/datos/x"))
c("choques: solo archivos que coinciden", transferencia.choques({"a.txt", "c/d.txt", "c/e.txt"}, {"a.txt", "c/e.txt", "z.txt"}), 2)
c("nada en el destino", transferencia.choques({"a"}, set()), 0)
c("singular", transferencia.texto_choques(1, "/datos"), "1 elemento ya existe en /datos. ¿Sobrescribirlo u omitirlo?")
c("plural", transferencia.texto_choques(3, "/datos"), "3 elementos ya existen en /datos. ¿Sobrescribirlos u omitirlos?")
```

- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS (`python3 tests/test_transferencia.py`, `test_reglas_claude.py`, `--cambios`). **Step 5:** commit «Servidor: qué copia un lote, decidido sin Tk».

---

### Task 3: pair warnings and blocks

**Files:** Modify `ui/transferencia.py`; Test `tests/test_transferencia.py`.

**Interfaces — Produces:**
- `@dataclass(frozen=True) Afectada(pareja: str, modo: str)`
- `afectadas_subida(config, remote: str, ruta_destino: str, elementos) -> tuple[Afectada, ...]`: pairs on `remote` whose `remote_path` contains `ruta_destino` (deepest only, via `servidor.dentro_de`) **plus** pairs whose `remote_path` lies under `ruta_destino/<elemento>` for an uploaded **folder** element, or equals `ruta_destino/<elemento>` for any element. No duplicates; config order.
- `afectadas_bajada(config, carpeta_destino: str, elementos) -> tuple[Afectada, ...]`: the same against each pair's `Pair.local_abs` (resolve `carpeta_destino` with `Path(...).resolve()`; compare with `Path.is_relative_to`, never string prefixes).
- `bloqueo(sentido: str, afectadas) -> str | None`: the block text of the first `up-mirror` (upload) / `down-mirror` (download) pair.
- `aviso(sentido: str, afectadas) -> str | None`: when not blocked, the warning texts of every affected pair joined with a blank line; `None` with no pair.
- Texts: exactly those in Global Constraints.

- [ ] **Step 1: failing tests** (with `mkcfg` pairs: «Notas» bisync `nas:/datos/notas` local `sync-data/notas`; «Copia» up-mirror `nas:/copia`; «Bajadas» down-mirror `nas:/bajadas` local `sync-data/bajadas`; «Todo» bisync `b2:/`):

```python
c("subir dentro de una bisync avisa", transferencia.aviso("subir", transferencia.afectadas_subida(cfg, "nas", "/datos/notas/2026", [E("a.txt", False)])), AVISO_BISYNC_NOTAS)
c("subir a una up-mirror bloquea", transferencia.bloqueo("subir", transferencia.afectadas_subida(cfg, "nas", "/copia", [E("a", False)])), BLOQUEO_COPIA)
c("subir por encima de una pareja la alcanza", [a.pareja for a in transferencia.afectadas_subida(cfg, "nas", "/datos", [E("notas", True)])], ["Notas"])
c("otro remote no cuenta", transferencia.afectadas_subida(cfg, "nas", "/", [E("x", False)]), ())
c("la raíz de b2 cuenta todo", [a.pareja for a in transferencia.afectadas_subida(cfg, "b2", "/z", [E("x", False)])], ["Todo"])
c("bajar dentro de una down-mirror bloquea", transferencia.bloqueo("bajar", transferencia.afectadas_bajada(cfg, str(DEVICE/"sync-data/bajadas/sub"), [E("a", False)])), BLOQUEO_BAJADAS)
# bajar a sync-data con un elemento «notas» (carpeta) alcanza a «Notas» (su local es sync-data/notas)
c("bajar por encima de la carpeta de una pareja la alcanza", [a.pareja for a in transferencia.afectadas_bajada(cfg, str(DEVICE/"sync-data"), [E("notas", True)])], ["Notas"])
c("bajar fuera de las parejas no dice nada", (transferencia.bloqueo("bajar", ()), transferencia.aviso("bajar", ())), (None, None))
c("prefijo de texto no es estar dentro", transferencia.afectadas_subida(cfg, "nas", "/datos/notas2", [E("a", False)]), ())
# subir a "/" de nas una carpeta "copia" y otra "datos": alcanza «Copia» (up-mirror) y «Notas» → bloqueo de «Copia»
c("varias: bloqueo si alguna es up-mirror", transferencia.bloqueo("subir", transferencia.afectadas_subida(cfg, "nas", "/", [E("copia", True), E("datos", True)])), BLOQUEO_COPIA)
```

- [ ] **Steps 2–5:** FAIL → implement → PASS → commit «Servidor: avisar o bloquear según la pareja que recibe lo copiado».

---

### Task 4: progress and result texts

**Files:** Modify `ui/transferencia.py`; Test `tests/test_transferencia.py`.

**Interfaces — Produces:**
- `@dataclass(frozen=True) Progreso(titulo: str, archivo: str, cuenta: str, fraccion: float | None, ritmo: str)`
- `progreso_de(stats: dict, lote: Lote, destino_visible: str) -> Progreso`: `titulo` = `Subiendo a {destino_visible}` / `Bajando a {destino_visible}`; `archivo` = name of the first `transferring[]` entry or `""`; `cuenta` = `{transfers} de {totalTransfers} archivos · {bytes} de {totalBytes}` (sizes via `servidor.tamano_legible`); `fraccion` = `bytes/totalBytes` clamped to 0..1, `None` if `totalBytes` is 0/missing; `ritmo` = `{velocidad}/s · quedan {eta}` with eta as `N s` (< 60), `N min` (< 3600), `N h`; empty eta → only the speed; no speed → `""`.
- `@dataclass(frozen=True) Resultado(texto: str, tono: str, reintentar: bool)` — `tono` is `"ok"` or `"aviso"`.
- `resultado_de(estado: dict, stats: dict, cancelado: bool, destino_visible: str) -> Resultado`: success → `Copiados {transfers}` + ` · omitidos {omitidos}` where `omitidos = checks - transfers` if > 0 (`IgnoreExisting` and identical files count as checks); cancelled → `Cancelado: copiados {transfers} de {totalTransfers}`, no retry; `success: false` → if `servidor.es_de_permiso(...)` then `No tienes permiso para escribir en {destino_visible}.`, else `servidor.frase_error(rcd.ErrorRc(estado["error"], 0))`; retry.

- [ ] **Step 1: failing tests** (Review Focus 5):

```python
P = transferencia.progreso_de
c("vacío no lanza", P({}, lote_subir, "/datos"), transferencia.Progreso("Subiendo a /datos", "", "0 de 0 archivos · 0 B de 0 B", None, ""))
c("a medias", P({"transfers": 3, "totalTransfers": 41, "bytes": 125829120, "totalBytes": 838860800,
   "speed": 4404019.2, "eta": 120, "transferring": [{"name": "fotos/a.jpg"}]}, lote_bajar, "/home/u/D"),
  transferencia.Progreso("Bajando a /home/u/D", "fotos/a.jpg", "3 de 41 archivos · 120 MB de 800 MB", 0.15, "4,2 MB/s · quedan 2 min"))
c("eta nula", P({"speed": 1024, "eta": None}, lote_subir, "/").ritmo, "1 KB/s")
c("ok con omitidos", transferencia.resultado_de({"success": True}, {"transfers": 38, "checks": 41}, False, "/datos"), transferencia.Resultado("Copiados 38 · omitidos 3", "ok", False))
c("cancelado", transferencia.resultado_de({"success": False}, {"transfers": 12, "totalTransfers": 41}, True, "/datos").texto, "Cancelado: copiados 12 de 41")
c("permiso al escribir", transferencia.resultado_de({"success": False, "error": "permission denied"}, {}, False, "/datos"), transferencia.Resultado("No tienes permiso para escribir en /datos.", "aviso", True))
c("otro error, en llano", transferencia.resultado_de({"success": False, "error": "i/o timeout"}, {}, False, "/datos").texto, "El servidor no ha contestado a tiempo.")
```


- [ ] **Steps 2–5:** FAIL → implement → PASS → commit «Servidor: lo que dice el progreso de un lote y cómo acabó».

---

### Task 5: `ui/tk_transferencia.py` — the panel and the collision dialog (draw only)

**Files:** Create `ui/tk_transferencia.py`, `tests/test_tk_transferencia.py`; Modify `tests/run_all.py` (`GUI`), `.claude/rules/servidor.md`.

**Interfaces — Produces:**
- `class Panel(padre)`: `.marco` (placed by the caller with `grid`), `mostrar_progreso(p: transferencia.Progreso)`, `mostrar_cancelando()`, `mostrar_resultado(r: transferencia.Resultado)`, `ocultar()`; callbacks set as attributes `al_cancelar` and `al_reintentar` (no-arg callables). Widgets exposed for tests: `.titulo`, `.archivo`, `.cuenta`, `.barra` (`ttk.Progressbar`; indeterminate and started via `tk._arrancar_barra` when `fraccion is None`, determinate `value = fraccion*100` otherwise), `.ritmo`, `.cancelar`, `.resultado`, `.reintentar`. Result uses `tk.bloque_aviso` with tone `Verde.` for ok, `Ambar` for aviso.
- `preguntar_choques(parent, texto: str) -> str | None`: modal (`tk.modal` + this module's `mostrar`) with the exact title and buttons; returns `"sobrescribir"`, `"omitir"` or `None` (Cancelar, Escape, X); initial focus on `Cancelar`. Module-level so `tk_servidor` tests can replace it.

- [ ] **Step 1: failing tests** under Xvfb (skip without display): panel with a `Progreso` of `fraccion=0.15` → `barra["mode"] == "determinate"` and value 15; with `None` → indeterminate; texts land in their labels; `mostrar_resultado(ok)` hides the progress widgets and shows the text; Reintentar visible only when `reintentar`; clicking Cancelar calls `al_cancelar` once; `preguntar_choques` with `mostrar` replaced by a function that invokes each button → the three return values; Escape → `None`; no hex/bare ints (grep in the test like other tk tests do, if a helper exists; else skip).
- [ ] **Steps 2–5:** FAIL → implement → PASS → commit «Servidor: el panel de progreso y el aviso de choques».

---

### Task 6: wire it into `ui/tk_servidor.py`

**Files:** Modify `ui/tk_servidor.py`, `tests/test_tk_servidor.py`, `tests/test_tk_medidas.py`.

**Interfaces — Consumes:** Tasks 1–5. **Produces (module level, replaceable):**
- `elegir_destino(parent, inicial: str) -> str | None` (`filedialog.askdirectory`), `elegir_archivos(parent, inicial: str) -> list[str]` (`askopenfilenames`), `elegir_carpeta(parent, inicial: str) -> str | None` (`askdirectory`).
- `_rutas_remotas(r: rcd.Rcd, remote: str, base: str, elementos) -> set[str]`: relative **file** paths under `base` for each element (`operations/list` recursive on a folder element, `operations/stat` on a file element; a 404 means "not there", not an error). `_rutas_locales(carpeta: str, elementos) -> set[str]`: same with `os.walk`/`os.path.isfile`. Both module-level, no Tk (the `_leer` pattern of piece 1).

**Behaviour:**
- List `selectmode="extended"`; double-click/Return enter only when the selection is exactly one folder.
- Bar: `Bajar…` (enabled with a selection and an rcd), `Subir archivos…`, `Subir carpeta…` (enabled with an rcd); all three disabled while a batch runs.
- Flow per spec «Flujo de un lote»: pick → `afectadas_*` → block (`tk.avisar`, title `No se puede`) or warning (`tk.preguntar`, title `Carpeta de una pareja`, `Seguir`/`Cancelar`) → count collisions in background (indicator `Mirando el destino…`) → `tk_transferencia.preguntar_choques` if > 0 → `rcd.copiar(..., grupo=f"lote-{n}")` in background → poll `progreso` + `estado` every 500 ms via `segundo_plano` + `Sondeo` → result; upload into the shown folder → `repetir()` (reread).
- Download keeps the remote structure: selected `fotos/` lands as `<destino>/fotos/…`.
- Cancel: `rcd.cancelar` in background, panel `Cancelando…`, then the result.
- Close with a running batch: `tk.preguntar(dlg, "Transferencia en marcha", texto, "Cancelar y cerrar", "Seguir")`; yes → cancel, wait for `finished` up to `rcd.ESPERA_QUIT`, then the existing close path; no → stay open.
- `RcdCaido` while polling → panel result `Se perdió la conexión con rclone.` + the existing «Reconectar» in the indicator.
- The last local folder used is kept in the dialog state for the next pick (memory only).

- [ ] **Step 1: failing tests** in `tests/test_tk_servidor.py` (fake `Rcd` answering `sync/copy`, `core/stats`, `job/status`, `job/stop`, `operations/list` recurse/`stat`; dialogs replaced):
  - buttons' enabled state with/without selection, with/without rcd, during a batch;
  - upload into «Copia» (up-mirror) → `avisar` called with `No se puede`, no `sync/copy`;
  - upload into «Notas» → `preguntar` with the bisync text; `Cancelar` → no copy;
  - 2 collisions → `preguntar_choques` called with the plural text; `"omitir"` → `sync/copy` with `IgnoreExisting`; `None` → no copy;
  - a name `raro [1]*` downloaded → the `IncludeRule` reaching `sync/copy` is escaped (Review Focus 1);
  - progress stats advancing → panel labels change; finished success with checks > transfers → `Copiados … · omitidos …`; upload into shown folder → a new `operations/list` of it;
  - Cancel → `job/stop` sent once, `Cancelando…`, then `Cancelado: …`;
  - close mid-batch → prompt; `Seguir` keeps the window; `Cancelar y cerrar` sends `job/stop` before `parar()` and no `report_callback_exception` (Review Focus 4, with real threads like the piece-1 close test).
  - In `tests/test_tk_medidas.py`: the «Servidor» matrix case also shows the panel mid-progress and still fits all 10 screens.
- [ ] **Steps 2–5:** FAIL → implement → PASS (`xvfb-run -a $PY tests/test_tk_servidor.py`, `tests/test_tk_medidas.py`, `--cambios`) → commit «Servidor: bajar y subir archivos y carpetas desde el explorador».

---

### Task 7: docs and real-machine rows

**Files:** Modify `docs/agents/reference/servidor.md` (transfers section: rules/escaping, `sync/copy` only, pair warnings/blocks both directions, panel/cancel/close, the `.partial` left by a hard kill), `docs/agents/reference/commands-testing.md` (registry: `elegir_destino`, `elegir_archivos`, `elegir_carpeta`, `tk_transferencia.preguntar_choques`), `docs/guia/servidor.md` (download/upload, the single collision prompt, the pair warnings, cancel, the leftover temporary file), `docs/superpowers/pruebas/2026-10-27-servidor-pendiente-en-real.md` (rows: real SFTP with/without final rename; cancel a big upload on Windows; download to the device on FAT32/exFAT and re-run — nothing recopied; upload 10 000 small files and time it), spec status line → built.

- [ ] Write, run `python3 tests/test_reglas_claude.py` and `--cambios`, commit «Servidor: documentación de bajar y subir».
