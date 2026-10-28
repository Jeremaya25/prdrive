# «Servidor…» piece 3: new folder, rename, move, delete — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** from the «Servidor» explorer, create a folder, rename one item, move items (cut → navigate → paste) and delete items on the server, each action a sequence of async rclone jobs (one per item) followed in piece 2's panel, with pair-root/catalogue blocks and per-mode pair warnings.

**Architecture:** `common/rcd.py` gains `lanzar_orden()` (one async order from a whitelist) and `tamano()`. A new pure module `ui/gestion.py` decides everything (name/paste validation, touched paths, blocks, warnings, the rc orders, the confirmation plan, panel and result texts). Piece 2's batch machine moves out of `tk_servidor.py` closures into `ui/tk_lote.Seguimiento`, which runs a LIST of launchers in sequence (a copy is a list of one). A new draw-only `ui/tk_gestion.py` holds the name dialog and the toolbar/menu; `ui/tk_servidor.py` wires the four flows and the cut line.

**Tech Stack:** Python 3.11+ stdlib only, Tk 9 (`ttk`), plain-script tests (`tests/_harness.Checks`).

**Spec:** `docs/superpowers/specs/2026-10-27-servidor-gestion-design.md` (pieces 1–2: `docs/agents/reference/servidor.md`, `docs/superpowers/specs/2026-10-27-servidor-transferencias-design.md`).

## Global Constraints

- Stdlib only; imports on 3.11; `import tkinter` only inside functions; `ui/gestion.py` imports no Tk and touches no disk or network.
- Spanish comments/docstrings/UI text; `docs/agents/` in English; read `docs/agents/code-writing-conventions.md` and `docs/agents/reference/servidor.md` first.
- `tk_*` modules: colours/fonts/glyphs from `theme`/`icons`, distances via `theme.medida()`/`theme.E*`; nothing Tk inside work sent to `segundo_plano`.
- **Orders that delete or move leave ONLY through `rcd.lanzar_orden()`**, whose whitelist is `ORDENES_PERMITIDAS = {"operations/mkdir", "operations/movefile", "operations/deletefile", "operations/purge", "sync/move"}`. `copiar()` stays `sync/copy` only. Nothing calls `sync/sync` or `job/batch`.
- **Never launch onto a name that exists**: rclone's `movefile` onto an "identical" file deletes the source without writing; `mkdir` on an existing folder does not fail; `sync/move` onto an existing folder merges and overwrites. The destination's names are re-read (non-recursive `operations/list`) right before launching, compared with `casefold()` on both sides.
- Remote fs strings always through the absolute root: `"<remote>:/<ruta sin barra inicial>"`; a `remote` parameter is the path without its leading slash (`""` for the root).
- Pair matching only against pairs on the SAME `remote_name`, by path segments via `remote_picker.normalizar()`, deepest pair wins (all pairs sharing that depth).
- Read `nav.remote`, `nav.ruta` and the selection BEFORE opening any dialog (piece 2 rule).
- Piece 2's tests (`tests/test_tk_servidor.py`, `tests/test_transferencia.py`, `tests/test_tk_transferencia.py`) must pass **unchanged**: do not edit them. `tk_servidor.INTERVALO_PROGRESO_MS`, `SIN_RESPUESTA`, `FALLOS_PARA_AVISAR`, `PERDIDA`, `TEXTO_CIERRE`, `TITULO_CIERRE` keep their names and values, and setting `tk_servidor.INTERVALO_PROGRESO_MS` at runtime must still take effect.
- Tests never start rclone nor touch the network. Every new source/test goes in `.claude/rules/servidor.md` `paths`; a Tk test goes in `GUI` in `tests/run_all.py`.
- Verify with `python3 tests/run_all.py --cambios -j auto`; Tk tests with `PY=/tmp/claude-0/-home-user-prdrive/a9227951-c24b-54b6-9582-83a4e18c5019/scratchpad/ci/runtime/bin/python3; xvfb-run -a $PY tests/<f>.py`. Commit footer exactly: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_0158B15k9NNa1wRurV7n183V` (no other model name).
- Exact copy (singular/plural as shown):
  - toolbar/menu: `Nueva carpeta…`, `Renombrar…`, `Cortar`, `Borrar…`, `Pegar aquí`; keys F2, Delete (`<Delete>`), Ctrl+X, Ctrl+V, Ctrl+Shift+N;
  - name dialog: titles `Nueva carpeta` / `Renombrar`, buttons `Aceptar` / `Cancelar`; reasons `Escribe un nombre.` · `Un nombre no puede llevar «/».` · `Ese nombre no vale.` (`.`, `..`) · `Ya hay algo que se llama «{n}» en esta carpeta.`;
  - cut line: `{n} elementos para mover desde {carpeta}` / `1 elemento para mover desde {carpeta}`, buttons `Pegar aquí`, `Cancelar`; on another remote it appends ` · Solo se puede pegar en el mismo servidor.` and `Pegar aquí` is disabled;
  - paste refusals (title `No se puede`): `Ya están en esta carpeta.` · `No se puede mover una carpeta dentro de sí misma.` · `Ya hay «{x}» en {destino}: renómbralo antes.` / `Ya hay «{x}» y {k} más en {destino}: renómbralos antes.`;
  - indicator: `Mirando qué hay dentro…` (delete count), `Mirando el destino…` (name checks, = `tk_servidor.MIRANDO`);
  - blocks (title `No se puede`): pair root `Ahí está la carpeta de la pareja «{p}»: tocarla desde aquí rompería la pareja.` · catalogue `Ahí está el catálogo de las parejas: tocarlo desde aquí dejaría a los dispositivos sin él.` · up-mirror arrival `«{p}» deja el servidor igual que el dispositivo: lo que pongas aquí lo borraría su próxima pasada.`;
  - warnings (one per pair and side): leaves bisync/down-mirror `La próxima pasada de «{p}» lo quitará también del dispositivo.` · leaves down `El dispositivo conserva su copia: «{p}» no borra.` · leaves up/up-mirror `La próxima pasada de «{p}» lo volverá a subir desde el dispositivo.` · arrives bisync/down/down-mirror `La próxima pasada de «{p}» lo copiará al dispositivo.` · arrives up `El dispositivo no lo recibirá: «{p}» solo sube.`;
  - confirmation: delete title `Borrar del servidor`, note `El servidor no tiene papelera.`; others with warnings title `Carpeta de una pareja`, note `""`. Consequences: `Se borrará para siempre «{x}», con {n} archivos ({tamaño}).` (`con 1 archivo`; an empty folder `Se borrará para siempre «{x}», vacía.`), a file `Se borrará para siempre «{x}» ({tamaño}).` · `«{a}» pasará a llamarse «{b}».` · `Se moverán {n} elementos de {origen} a {destino}.` (`Se moverá «{x}» de {origen} a {destino}.`) · `Se creará la carpeta «{n}» en {carpeta}.`;
  - panel titles: `Borrando en {carpeta}`, `Moviendo a {destino}`, `Renombrando «{a}» a «{b}»`, `Creando la carpeta «{n}»`; count line `{i} de {n} elementos` + (BORRAR with `deletes` > 0) ` · {d} archivos borrados`; cancelling `Cancelando… se para al acabar «{x}».`;
  - results ok: `Borrado «{x}».` / `Borrados {n}.` · `Movido «{x}» a {destino}.` / `Movidos {n} a {destino}.` · `Renombrado a «{b}».` · `Creada «{n}».`; partial `Borrados {k} de {n}: «{x}» no se pudo: {frase}` / `Movidos {k} de {n}: …`; single-item failure `No se pudo borrar «{x}»: {frase}` / `No se pudo mover «{x}»: {frase}` / `No se pudo renombrar «{a}»: {frase}` / `No se pudo crear «{n}»: {frase}`; frase: 404 → `ya no estaba`, permission → `No tienes permiso para {borrar|mover|renombrar|crear} en {carpeta}.`, otherwise `servidor.frase_error()`; cancelled `Cancelado: borrados {k} de {n}` / `Cancelado: movidos {k} de {n}` + (last launched order ended in error) ` · «{x}» puede haber quedado a medias`. Results never offer `Reintentar` (tone `aviso` on any failure or cancel, `ok` otherwise);
  - close prompt while a management job runs: title `Cambio en marcha`, text `Hay un cambio en marcha en el servidor. ¿Cancelarlo y cerrar?`, buttons `Cancelar y cerrar` / `Seguir`; no-answer line `Sin respuesta de rclone… el cambio sigue en marcha; se vuelve a intentar.`

## Review Focus

1. **A paste or rename whose target exists only with different case** (`Fotos` vs `fotos`) must be refused, except renaming an item to a case variant of its OWN name. Test in Task 2.
2. **Cancelling between items**: with three items, cancel during the first → the second and third orders are never launched, `job/stop` goes once to the first, result `Cancelado: borrados 1 de 3` (or `0 de 3` if the first failed). Test in Task 4 (machine) and Task 6 (window).
3. **A sequence where a middle order fails** (404, permission) — the next ones still run, and the result names the failed one. Test in Task 3 (text) and Task 4 (machine keeps going).
4. **The catalogue at the remote ROOT** (`catalog_path = "remote.toml"`, carpeta `""`): only `remote.toml`/`pairs.toml` there are blocked, not every path on the remote. Test in Task 2.
5. **The explorer window at the smallest supported size with the new toolbar** still fits (`tests/test_tk_medidas.py` already measures it; it must stay green). Checked in Task 6.

---

### Task 1: `lanzar_orden()` and `tamano()` in `common/rcd.py`  *(Haiku)*

**Files:** Modify `common/rcd.py`; Test `tests/test_rcd.py`.

**Interfaces — Produces:**
- `ORDENES_PERMITIDAS: frozenset[str]` (the five paths above).
- `lanzar_orden(r: Rcd, orden: dict, grupo: str) -> int`: `r.llamar(orden["_path"], {**params_without__path, "_async": True, "_group": grupo})`, returns `int(...["jobid"])`. `ValueError("orden no permitida: {path}")` before any call if `_path` is missing or not in the whitelist. The caller's dict is not mutated.
- `tamano(r: Rcd, fs: str) -> tuple[int, int]`: `operations/size {"fs": fs}` with `fs` = the folder itself (`<remote>:/<path>`; rclone's `rcSize` reads only `fs`, a `remote` param is ignored and the whole remote is counted) → `(count, bytes)`; a missing, non-int or bool field counts 0. Uses the default timeout (a big folder takes time).

- [ ] **Step 1: failing tests** (fake `Rcd` recording `llamar(metodo, params, timeout=None)`):

```python
orden = {"_path": "operations/purge", "fs": "nas:/", "remote": "datos/viejo"}
jid = rcd.lanzar_orden(falso, orden, "gestion-1")
c("lanza la orden asíncrona con su grupo", falso.llamadas[-1],
  ("operations/purge", {"fs": "nas:/", "remote": "datos/viejo", "_async": True, "_group": "gestion-1"}))
c("devuelve el jobid", jid, 7)
c("no toca la orden de quien llama", orden, {"_path": "operations/purge", "fs": "nas:/", "remote": "datos/viejo"})
for mala in ({"_path": "sync/sync"}, {"_path": "job/batch", "inputs": []}, {"_path": "operations/delete"}, {"fs": "nas:/"}):
    # ValueError, and falso.llamadas unchanged
c("tamano lee count y bytes", rcd.tamano(falso_size({"count": 4, "bytes": 8}), "nas:/a/x"), (4, 8))
c("tamano con campos raros cuenta 0", rcd.tamano(falso_size({"count": "x", "bytes": True}), "nas:/a"), (0, 0))
c("tamano pide operations/size", ultima_llamada, ("operations/size", {"fs": "nas:/a/x"}))
```

- [ ] **Step 2:** run `python3 tests/test_rcd.py` → FAIL (`AttributeError`).
- [ ] **Step 3:** implement both in `common/rcd.py` beside `copiar()`, with Spanish docstrings citing the probe (spec «Lo comprobado»).
- [ ] **Step 4:** `python3 tests/test_rcd.py` → all OK.
- [ ] **Step 5:** commit `rcd: una orden asíncrona de una lista cerrada, y el tamaño de una carpeta`.

### Task 2: decisions of `ui/gestion.py` — validation, touched paths, blocks, warnings  *(Sonnet)*

**Files:** Create `ui/gestion.py`; Modify `ui/transferencia.py` (shared pair helpers); Test: create `tests/test_gestion.py`; `tests/test_transferencia.py` must stay green untouched.

**Interfaces — Consumes:** `transferencia.Elemento(nombre, es_carpeta)`, `transferencia.Afectada(pareja, modo)`, `remote_picker.normalizar`, `catalog.NOMBRES` (`("remote.toml", "pairs.toml")`).

**Produces:**
- In `ui/transferencia.py` (and `afectadas_subida` rewritten on top of them, same behaviour):
  - `parejas_que_contienen(config, remote, ruta) -> set[str]`: names of the deepest pairs whose `remote_path` equals `ruta` or is an ancestor of it.
  - `parejas_bajo(config, remote, ruta) -> set[str]`: names of pairs whose `remote_path` equals `ruta` or is below it.
- In `ui/gestion.py`:
  - constants `BORRAR = "borrar"`, `RENOMBRAR = "renombrar"`, `MOVER = "mover"`, `NUEVA = "nueva"`.
  - `@dataclass(frozen=True) Operacion(tipo: str, remote: str, carpeta: str, elementos: tuple[Elemento, ...] = (), destino: str | None = None, nombre: str | None = None)`. RENOMBRAR has one element and `nombre`; NUEVA has no elements and `nombre`; MOVER has `destino`; paths are absolute (`/datos/x`), root `/`.
  - `validar_nombre(nombre: str, existentes: Iterable[str], actual: str | None = None) -> str | None` (reasons from Global Constraints; `nombre.strip() == ""` → empty; same exact name as `actual` → `None` and the caller does nothing; a casefold match with `actual` itself is allowed).
  - `validar_pegado(op: Operacion, nombres_en_destino: Iterable[str]) -> str | None` (same folder; destino equal to or under a cut FOLDER; occupied names with the `y {k} más` form).
  - `rutas_tocadas(op) -> tuple[tuple[str, ...], tuple[str, ...]]` = `(salen, llegan)` per the spec table.
  - `bloqueo(op, config, catalogo: tuple[str, str] | None) -> str | None`: first matching rule in this order: pair root (any touched path equals a pair's `remote_path` or contains one: `parejas_bajo`), catalogue (`catalogo` = `(remote, carpeta)` from `model.carpeta_del_catalogo()`; when `carpeta` is not the root: the folder itself, its ancestors and anything under it; when it is the root: only `/<n>` for `n` in `catalog.NOMBRES`; only when `op.remote == catalogo[0]`), up-mirror arrival (an `llegan` path strictly inside an up-mirror pair, deepest match).
  - `avisos(op, config) -> tuple[str, ...]`: for each side (leaves first, then arrives), each deepest containing pair, the mode's text; no duplicates; config order.

- [ ] **Step 1: failing tests in `tests/test_gestion.py`**, with a config like piece 2's `CFG2` (Copia up-mirror `/datos/copia`, Notas bisync `/datos/notas`, Baja down `/datos/baja`, Espejo down-mirror `/datos/espejo`, Sube up `/datos/sube`, a nested pair `Hondo` bisync `/datos/notas/hondo`, and a pair on remote `otro` at `/datos/copia`):
  - `validar_nombre`: `""`, `"   "` → `Escribe un nombre.`; `"a/b"` → `Un nombre no puede llevar «/».`; `"."`, `".."` → `Ese nombre no vale.`; `"Fotos"` with existentes `["fotos"]` → `Ya hay algo que se llama «Fotos» en esta carpeta.`; `"Foto.jpg"` with existentes `["foto.jpg"]`, actual `"foto.jpg"` → `None`; `"nota "` (trailing space) → `None`.
  - `validar_pegado`: destino == carpeta → `Ya están en esta carpeta.`; cut folder `/a/x`, destino `/a/x/sub` → `No se puede mover una carpeta dentro de sí misma.`; cut FILE `/a/x` and destino `/a/xy` → no refusal; occupied `["X.txt"]` vs element `x.txt` → `Ya hay «x.txt» en /b: renómbralo antes.`; two occupied → `… y 1 más …: renómbralos antes.`.
  - `rutas_tocadas` for the four kinds, root folder included (`carpeta="/"` → `/x`, never `//x`).
  - `bloqueo`: delete `/datos/notas` → pair-root text with `Notas`; delete `/datos` (contains roots) → pair-root text; rename `/datos/viejo` to `notas`… i.e. `Operacion(RENOMBRAR, "nas", "/datos", (Elemento("viejo", True),), nombre="espejo")` → pair-root text with `Espejo`; delete `/datos/notas/a.txt` → `None`; same paths on remote `otro` other than its own pair → `None`; catalogue `("nas", "/prdrive-catalog/")`: delete `/prdrive-catalog` → catalogue text, delete `/prdrive-catalog/remote.toml` → catalogue text, delete `/` items containing it → catalogue text (if no pair rule fires first); catalogue at root `("nas", "")`: delete `/remote.toml` → catalogue text, delete `/otra.txt` → `None`; move `/tmp/a.txt` into `/datos/copia/sub` → up-mirror text; NUEVA in `/datos/copia` → up-mirror text; delete inside `/datos/copia` → `None` (leaving up-mirror is a warning, not a block).
  - `avisos`: delete in Notas → bisync leaves text; delete in Hondo → only Hondo's text (deepest); move from Baja to Notas → `El dispositivo conserva su copia: «Baja» no borra.` then `La próxima pasada de «Notas» lo copiará al dispositivo.`; NUEVA in Sube → up arrives text; rename inside Espejo → leaves and arrives texts for Espejo; outside every pair → `()`.
- [ ] **Step 2:** `python3 tests/test_gestion.py` → FAIL (no module).
- [ ] **Step 3:** implement the helpers in `transferencia.py` and the functions above in `ui/gestion.py`.
- [ ] **Step 4:** `python3 tests/test_gestion.py` and `python3 tests/test_transferencia.py` → all OK.
- [ ] **Step 5:** add `ui/gestion.py` and `tests/test_gestion.py` to `.claude/rules/servidor.md` `paths`; run `python3 tests/test_reglas_claude.py`; commit `gestion: qué se puede tocar en el servidor y qué dirá cada pareja`.

### Task 3: `ui/gestion.py` — orders, plan, texts  *(Sonnet)*

**Files:** Modify `ui/gestion.py`; Test `tests/test_gestion.py`.

**Interfaces — Consumes:** Task 2's `Operacion`; `transferencia.Progreso`, `transferencia.Resultado`; `servidor.tamano_legible`, `servidor.frase_error`, `servidor.es_de_permiso`, `servidor` 404 check (`rcd.ErrorRc.estado == 404` or `servidor` not-found text).

**Produces:**
- `ordenes_de(op) -> list[dict]`, one per element (NUEVA: one), each `{"_path": …, …}` (spec «Piezas»): BORRAR folder `{"_path": "operations/purge", "fs": "<r>:/", "remote": "<ruta sin barra>"}`, file `operations/deletefile` same keys; RENOMBRAR/MOVER folder `{"_path": "sync/move", "srcFs": "<r>:/<origen>", "dstFs": "<r>:/<destino>", "deleteEmptySrcDirs": True}`, file `{"_path": "operations/movefile", "srcFs": "<r>:/", "srcRemote": …, "dstFs": "<r>:/", "dstRemote": …}`; NUEVA `{"_path": "operations/mkdir", "fs": "<r>:/", "remote": …}`. Names raw, never escaped. A folder `srcFs` for an item at the root is `"<r>:/x"`.
- `@dataclass(frozen=True) Plan(consequences: tuple[str, ...], warnings: tuple[str, ...])`.
- `plan_de(op, conteos: dict[str, tuple[int, int]], avisos: tuple[str, ...]) -> Plan` (`conteos` maps EVERY element's name to `(archivos, bytes)`: a folder's from `rcd.tamano`, a file's `(1, size from the listing)`; used only for BORRAR; consequence copy from Global Constraints).
- `titulo_de(op) -> str`, `progreso_de(op, stats: dict, hechos: int, total: int) -> transferencia.Progreso` (`archivo=""`, `ritmo=""`, `fraccion = hechos/total` or `None` when total is 0), `cancelando_de(op, indice: int) -> str` (the element at `indice`).
- `resultado_de(op, estados: list[dict], stats: dict, cancelado: bool) -> transferencia.Resultado` — `estados[i]` is the final `job/status` of order `i`; an order succeeded when `estado.get("success")` is true. `reintentar` is always `False`.

- [ ] **Step 1: failing tests**: `ordenes_de` for each kind with names `"con espacio"`, `"100%"`, `"a#b?"`, `"*[x]{y}"` (raw in the params), an element at the root; `plan_de` lines for a folder of 1234 files and 3 650 722 202 bytes (`3,4 GB`), a 1-file folder, an empty folder, a file, plus avisos passed through as warnings; `titulo_de` four kinds; `progreso_de` with `{}` stats (no exception, fraction for 1 of 3), with `deletes: 120` on BORRAR (`1 de 3 elementos · 120 archivos borrados`); `resultado_de`: all ok (1 and 3 elements, each kind), a middle failure 404 (`Borrados 2 de 3: «b» no se pudo: ya no estaba`), a permission failure on a single delete (`No se pudo borrar «x»: No tienes permiso para borrar en /datos.`), cancelled after 1 of 3 ok (`Cancelado: borrados 1 de 3`), cancelled with the last launched in error (`… · «b» puede haber quedado a medias`), RENOMBRAR failure, NUEVA ok.
- [ ] **Step 2:** run → FAIL. **Step 3:** implement. **Step 4:** run → OK.
- [ ] **Step 5:** commit `gestion: las órdenes para rclone y los textos de cada acción`.

### Task 4: `ui/tk_lote.Seguimiento` — piece 2's batch machine, extracted and sequenced  *(Sonnet)*

**Files:** Create `ui/tk_lote.py`; Modify `ui/tk_servidor.py` (transfers use it), `ui/tk_transferencia.py` (`Panel.mostrar_cancelando(texto: str = CANCELANDO)`); Test: create `tests/test_tk_lote.py` (in `GUI`); `tests/test_tk_servidor.py` must pass **unchanged**.

**Interfaces — Produces:**

```python
@dataclass(eq=False)
class Trabajo:
    rcd: rcd.Rcd
    grupo: str
    lanzadores: list[Callable[[rcd.Rcd, str], int]]          # cada uno lanza una orden y da su jobid (en un hilo)
    progreso: Callable[[dict, int, int], transferencia.Progreso]   # (stats, hechos, total)
    resultado: Callable[[list[dict], dict, bool], transferencia.Resultado]  # (estados, stats, cancelado)
    al_acabar: Callable[[transferencia.Resultado], None] = lambda r: None   # releer, elegir lo nuevo…
    reintento: Callable[[], None] | None = None               # se ofrece si el resultado lo pide
    sin_respuesta: str = ""                                   # la línea tras FALLOS_PARA_AVISAR fallos
    cancelando: Callable[[int], str] | None = None            # texto de «Cancelando…» según el que va
    panel_tardio: bool = False                                # sin panel hasta un sondeo sin acabar
    # estado: jobid, indice, estados, cancelado, cerrando, fallos, panel_visto

class Seguimiento:
    def __init__(self, ventana, panel, sondeo, *, decir, intervalo_ms: Callable[[], int],
                 fallos_para_avisar: Callable[[], int], perdida: str,
                 al_cambiar: Callable[[], None]) -> None: ...
    activo: Trabajo | None
    reintento: Callable[[], None] | None
    def abrir(self, t: Trabajo) -> Trabajo        # lo hace el lote en marcha; panel oculto; al_cambiar()
    def vigente(self, t: Trabajo) -> bool
    def lanzar(self, t: Trabajo) -> None          # empieza por lanzadores[0]
    def acabar_con_error(self, t: Trabajo, error: Exception, reintento) -> None   # para fallos de antes de lanzar
    def soltar(self) -> None                      # sin resultado (p. ej. «Cancelar» en un diálogo)
    def cancelar(self) -> None                    # una vez: job/stop al que va, no lanza más
    def reintentar(self) -> None
    def cerrar_cancelando(self, despues: Callable[[], None]) -> bool   # True si había trabajo lanzado y se espera
    def parar(self) -> None                       # la ventana se cierra: quita el temporizador
```

Move into it, unchanged in behaviour: `_sondear`, `_cancelar_y_esperar` (module functions), the poll loop, `sin_respuesta` (`FALLOS_PARA_AVISAR`, «job not found», dead `rcd` → `decir(servidor.frase_error(...), boton="Reconectar")` + `perdida`), cancel-once, `acabar`/`acabar_con_error`. New: after an order finishes, append its status to `t.estados`; if not cancelled and more launchers remain, launch the next (same group, `fallos` reset); when finished or cancelled, `resultado(estados, stats, cancelado)` → panel (or, when `panel_tardio` and the panel was never shown and the tone is `ok`, `decir(texto, "Pista.")`). `cancelar()` shows `panel.mostrar_cancelando(t.cancelando(indice))` when given. `tk_servidor.py` passes `intervalo_ms=lambda: INTERVALO_PROGRESO_MS`, `fallos_para_avisar=lambda: FALLOS_PARA_AVISAR`, `perdida=PERDIDA`, and builds transfer `Trabajo`s with `lanzadores=[partial(_lanzar_copia, lote, omitir)]` (signature becomes `(lote, omitir, r, grupo)`), `sin_respuesta=SIN_RESPUESTA`, `resultado=lambda e, s, c: transferencia.resultado_de(e[-1] if e else {}, s, c, destino, omitidos)`. The close prompt text/title come from the running `Trabajo`'s kind: transfers keep `TITULO_CIERRE`/`TEXTO_CIERRE`.

- [ ] **Step 1: failing tests in `tests/test_tk_lote.py`** (a hidden `Tk` root with a `Panel`, a real `Sondeo`, `segundo_plano.lanzar = segundo_plano.en_el_acto`, a fake rcd answering `job/status` per jobid and `core/stats`): three launchers run in order with jobids 1, 2, 3, each launched only after the previous `finished`; `resultado` receives three statuses; a middle failed status does not stop the next launcher; `cancelar()` during order 1 → one `job/stop` with jobid 1, launchers 2–3 never called, `resultado(..., cancelado=True)` with one status; `panel_tardio` + all finished on the first poll → panel never mapped and `decir` got the ok text; `panel_tardio` + first poll not finished → panel shown; «job not found» on order 2 → ends with `No se sabe cómo acabó: revisa la carpeta.` and launcher 3 never called; `rcd.vivo = False` + failing poll → `decir(..., boton="Reconectar")`.
- [ ] **Step 2:** run under xvfb → FAIL. **Step 3:** implement `tk_lote.py`, then switch `tk_servidor.py`'s transfer flow onto it (delete the moved closures).
- [ ] **Step 4:** `xvfb-run -a $PY tests/test_tk_lote.py`, `xvfb-run -a $PY tests/test_tk_servidor.py` (unchanged file, all 243 OK), `xvfb-run -a $PY tests/test_tk_transferencia.py`, `python3 tests/test_transferencia.py` → all OK.
- [ ] **Step 5:** add `ui/tk_lote.py` and `tests/test_tk_lote.py` to the rule paths and `test_tk_lote.py` to `GUI`; commit `Servidor: la máquina de lotes sale a tk_lote y encadena varias órdenes`.

### Task 5: `ui/tk_gestion.py` — name dialog, toolbar and context menu  *(Sonnet)*

**Files:** Create `ui/tk_gestion.py`; Test: create `tests/test_tk_gestion.py` (in `GUI`).

**Interfaces — Produces:**
- `pedir_nombre(parent, titulo: str, inicial: str, validar: Callable[[str], str | None], es_archivo: bool = False) -> str | None`: modal (`tk.modal`, `cuerpo_visible`), one `ttk.Entry`, the reason in a `Pista`-style label under it, `Aceptar` disabled while `validar(texto)` returns a reason (except the initial empty state shows no reason until typed); Return = Aceptar when enabled, Escape/X = `None`. With `es_archivo` the selection covers `inicial` up to its last `.` when that dot is not the first character; otherwise the whole text. Returns the text as typed (no strip).
- `Barra(padre, acciones: dict[str, Callable[[], None]])` with `.marco`, buttons `.nueva`, `.renombrar`, `.cortar`, `.borrar` (copy from Global Constraints, `Quiet.TButton`), and `encender(nueva: bool, renombrar: bool, cortar: bool, borrar: bool) -> None`.
- `menu_contextual(padre, acciones: dict[str, Callable[[], None]], estados: dict[str, bool]) -> "tk.Menu"`: entries `Nueva carpeta…`, `Renombrar…`, `Cortar`, `Pegar aquí`, `Borrar…`, each disabled when its state is False. Keys of `acciones`/`estados`: `"nueva"`, `"renombrar"`, `"cortar"`, `"pegar"`, `"borrar"`.

- [ ] **Step 1: failing tests**: `pedir_nombre` driven with `after()` callbacks (type, check the reason label text and `Aceptar` state, press Return/Escape) — `"foto.jpg"` with `es_archivo` selects `foto`; `".bashrc"` selects all; `"carpeta"` selects all; typing `"a/b"` shows `Un nombre no puede llevar «/».` and disables Aceptar; Return then does nothing; fixing it and Return returns the text; Escape returns `None`. `Barra` labels and `encender`; `menu_contextual` labels and disabled entries.
- [ ] **Step 2:** FAIL. **Step 3:** implement (colours/fonts from `theme`, distances from `theme.E*`). **Step 4:** OK under xvfb.
- [ ] **Step 5:** rule paths + `GUI`; add `tk_gestion.pedir_nombre` to the indirection registry in `docs/agents/reference/commands-testing.md`; commit `Servidor: el diálogo de nombre y la barra de gestión`.

### Task 6: the window — toolbar, keys, menu, new folder, rename, delete  *(Sonnet)*

**Files:** Modify `ui/tk_servidor.py`; Test: create `tests/_servidor_falso.py` (a COPY of the module-level fakes of `tests/test_tk_servidor.py`: `item`, `lista`, `RcdFalso`, `respuestas`, `abrir`, `cerrar`, `bombear`, the dialog fakes — `test_tk_servidor.py` is not edited) and `tests/test_tk_servidor_gestion.py` (in `GUI`).

**Interfaces — Consumes:** Tasks 1–5. Tests replace `tk_gestion.pedir_nombre`, `tk_pairs.confirmar_plan`, `tk_servidor.avisar`.

**Behaviour:** the `Barra` sits in a new row between the indicator line and the list (grid rows shift; `dlg.barra` exposed); on/off from `libre = rcd is not None and no running Trabajo` plus the selection rule (spec «Cuándo se encienden»), refreshed in `actualizar_botones()`. Right-click (`<Button-3>`, and `<Button-2>` on macOS-style Tk is not needed) selects the row under the pointer if not selected and posts `menu_contextual`. Keys bound on the list: `<F2>`, `<Delete>`, `<Control-x>`, `<Control-v>`, `<Control-N>` (Shift). Each flow: capture remote/ruta/selection → (dialog) → `gestion.bloqueo(op, config, catalogo)` (`catalogo` from `model.carpeta_del_catalogo(raw.get("defaults", {}))`) → background check (`operations/list` of the destination for NUEVA/RENOMBRAR; `rcd.tamano` per folder + listing sizes for BORRAR) with the indicator text → re-validate names → `tk_pairs.confirmar_plan(dlg, plan, titulo, nota)` when required → `Seguimiento.lanzar(Trabajo(... lanzadores=[partial(_lanzar_orden, o) for o in gestion.ordenes_de(op)], panel_tardio=True, sin_respuesta=SIN_RESPUESTA_GESTION ...))` → `al_acabar`: re-read the folder on screen and select the new name/folder when present. Closing while a management Trabajo runs uses `TITULO_CIERRE_GESTION`/`TEXTO_CIERRE_GESTION`.

- [ ] **Step 1: failing tests** with the fake: toolbar labels and on/off (none selected / one / two / batch running / no rcd); F2 with one row opens the name dialog with `inicial` = its name and `es_archivo`; a rename launches exactly one `operations/movefile` (file) or `sync/move` (folder) with the right fs/remote, after an `operations/list` of the folder; renaming to an existing name (case-insensitive) is refused without launching; NUEVA launches `operations/mkdir`; delete of a folder + a file asks `operations/size` once (for the folder), shows `confirmar_plan` with the exact consequence lines and title `Borrar del servidor`, and on «no» launches nothing; on «yes» launches `operations/purge` then `operations/deletefile` in that order (the second only after the first's `job/status` finished); a block (delete `/datos/notas`) shows `No se puede` with the pair text and launches nothing; a warning (delete inside Notas) shows the plan with the bisync warning; the listing is re-read after each action; closing during a running delete asks `Cambio en marcha`; `<Delete>` and the context menu reach the same flows; `tests/test_tk_medidas.py` still green.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** `test_tk_servidor_gestion.py`, `test_tk_servidor.py` (unchanged), `test_tk_medidas.py` OK under xvfb.
- [ ] **Step 5:** rule paths + `GUI`; commit `Servidor: crear carpeta, renombrar y borrar en el servidor`.

### Task 7: the window — cut and paste  *(Sonnet)*

**Files:** Modify `ui/tk_servidor.py`; Test `tests/test_tk_servidor_gestion.py`.

**Behaviour:** «Cortar» stores `(remote, carpeta, elementos)` and shows the cut line (a `ttk.Frame` row above the list with a label and `Pegar aquí`/`Cancelar` buttons; `dlg.cortado` exposed); it survives navigation; changing remote, «Cancelar», or the end of a paste clears it; on another remote the label appends the other-remote text and `Pegar aquí` is disabled. «Pegar aquí» (button, menu, Ctrl+V): capture destino = `nav.ruta` → `gestion.validar_pegado` with the destination's names from a fresh `operations/list` (background, `Mirando el destino…`) → `bloqueo` → plan only with warnings → launch one order per element → re-read, select the moved names.

- [ ] **Step 1: failing tests**: cut two items in `/datos`, navigate to `/otra`, the line reads `2 elementos para mover desde /datos`; paste launches `sync/move` for the folder (`srcFs nas:/datos/fotos`, `dstFs nas:/otra/fotos`, `deleteEmptySrcDirs`) and `operations/movefile` for the file, in order; the line disappears after; paste into `/datos` → `Ya están en esta carpeta.`; paste into `/datos/fotos/sub` → `No se puede mover una carpeta dentro de sí misma.`; destination already has `LEEME.TXT` → `Ya hay «leeme.txt» en /otra: renómbralo antes.` and nothing launched, line kept; switching to remote `otro` disables `Pegar aquí` and shows the text; switching remote clears the cut; paste into an up-mirror pair → blocked; cancel during the first of two moves → the second never launched, result `Cancelado: movidos 0 de 2` or `1 de 2` per status.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** OK under xvfb (plus the unchanged `test_tk_servidor.py`).
- [ ] **Step 5:** commit `Servidor: mover con cortar y pegar`.

### Task 8: documentation  *(Haiku)*

**Files:** Modify `docs/agents/reference/servidor.md` (status line → pieces 1–3 built; a «Management» section: rules, the whitelist invariant replacing piece 2's «never calls sync/move, purge or delete», the block/warn table, the flow, `tk_lote.Seguimiento`, the probe findings incl. `job/stop` not stopping `job/batch`/`purge`; «Known, not fixed» gains the race, other devices' pairs, servers without server-side move, case-only rename; remove the «Piece 3 (not built)» section and the «batch state machine in Tk closures» note), `docs/guia/servidor.md` (how to create/rename/move/delete; what is blocked and why; delete is forever; other devices' pairs; Cancelar stops before the next item), `docs/superpowers/pruebas/2026-10-27-servidor-pendiente-en-real.md` (rows G1 server without server-side move, G2 case-only rename on a case-insensitive server, G3 delete 10 000 files on a real server, G4 cancel a large delete on a real server: the item finishes), `docs/agents/reference/commands-testing.md` (new tests), spec status → built.

- [ ] **Step 1:** edit; **Step 2:** `python3 tests/test_reglas_claude.py` and `python3 tests/run_all.py --cambios -j auto` OK; **Step 3:** commit `Docs: la pieza 3 del explorador del servidor`.
