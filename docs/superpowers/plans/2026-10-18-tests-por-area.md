# Tests chosen by area, no windows locally: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `python tests/run_all.py --cambios -j auto` runs only the tests of the areas the branch's diff touches (plus the areas that import or launch what changed), never opening a Tk window locally; `run_all.py` with no arguments stops opening windows; CI keeps running all 180 files.

**Architecture:** a new pure module `tests/_seleccion.py` reads the area map that already exists in the `paths` of `.claude/rules/*.md` (sources and tests per area), builds a one-hop reverse import graph of the project's sources with `ast`, adds a hand table `LANZADO_POR` for scripts launched as processes, and turns a list of changed files into a `Seleccion`. `run_all.py` imports it lazily, only for `--cambios`/`--area`, and gains `--ventanas`; without it the `GUI` set is left out of every selection except explicit file names.

**Tech Stack:** Python 3.11+ stdlib only (`ast`, `fnmatch`, `subprocess` for `git`), the repo's plain-script tests (`tests/_harness.Checks`, `tmpdir()`).

**Spec:** `docs/superpowers/specs/2026-10-18-tests-por-area-design.md`

## Global Constraints

- Stdlib only; works on Python 3.11 (`python-minimo` CI job). Comments, docstrings (Google style) and every printed line in **Spanish**; `docs/agents/` and `AGENTS.md` in English. Read `docs/agents/code-writing-conventions.md` before writing Python.
- `tests/_seleccion.py` imports neither `_harness` nor anything from `common/`, `ui/`, `install/`, nor Tk, and importing it does nothing (no git, no file reads): all work happens in its functions. `run_all.py` imports it **inside** `main()`'s `--cambios`/`--area` branch only (the copies of `run_all.py` that `test_run_all.py` runs in temp folders have no `_seleccion.py` unless a case copies it).
- `GUI` in `run_all.py` stays the one definition of «test that opens a window». Nothing in this plan edits `GUI`, `GUI_NO`, `SERIE`, `PESO`, `-j`, `--display`, `--gui-jobs`, `--timeout` or the interrupt handling.
- Exact copy (printed by `run_all.py`):
  - suffix of the last line when window tests were left out: ` ({n} de ventanas sin correr: van en el CI, o con --ventanas)`, giving `Los {N} ficheros de test pasan{suffix}.` and `FALLAN {k} de {N}: {names}{suffix}`; empty suffix when `n == 0`, so the old lines are byte-identical;
  - header `Áreas (por los cambios de esta rama):` or `Áreas (por --area):`, then one line per motive, indented two spaces;
  - `Sin tests: {a, b}` (changed files that bring no test, when some tests do run);
  - `Fuera, por abrir ventanas (van en el CI; por nombre o con --ventanas): {x.py, y.py}`;
  - nothing to run, exit 0: `Estos cambios no tienen tests: {a, b}` · `Estos cambios solo tienen tests de ventanas.` · `No hay cambios contra main.`;
  - unknown area, exit 2: `No hay ningún área que se llame: {x, y}`;
  - `--cambios`/`--area` with file names, exit 2: `--cambios y --area no van con nombres de test`.
- Motive strings built by `_seleccion` (exact): `{área} ← {ruta}` · `{área} ← {g} importa {ruta}` · `{área} ← {g} lanza {ruta}` · `{área} ← pedida` · `{test} ← {ruta}` (a changed test) · `{test} ← importa {ruta}` (a changed helper) · `todo lo que no abre ventana ← {razón}` with razón `no se sabe qué cambió (sin git o sin base común con main)` or `{ruta} lo importan todos`.
- One commit per task, Spanish subject as given, footer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push.
- Run tests from **PowerShell** with the concrete interpreter and the real `LOCALAPPDATA`: `& "C:\Users\pjcer\AppData\Local\Python\pythoncore-3.14-64\python.exe" tests\<file>.py` (written `PY tests\<file>.py` below). Never the `python` alias with a redirected `LOCALAPPDATA`, never Git Bash for Python. Never touch `P:`. The checkout is CRLF (`core.autocrlf=true`): edit tracked files with Edit, not `sed -i`.
- The PostToolUse hook runs `tests/test_reglas_claude.py` after every edit of a rule, a reference doc or `AGENTS.md`, and reports its failure: expected while Task 1 is half done.

## Review Focus

1. **A branch with no changes against `main`** → `--cambios` says `No hay cambios contra main.` and exits 0; it must not fall back to «todo» nor fail. (Task 2: `elegir([])`; Task 4: launcher case.)
2. **File names with accents or spaces** (`docs/guia/…`, `Abrir PRDRIVE.bat`) → reported as they are, not as git's quoted octal. (Task 3: an untracked `ñandú x.txt`.)
3. **A file deleted or renamed on the branch** → still selects its area through the rule pattern, and a rename counts by both names. (Task 2: `common/motor_viejo.py`; Task 3: `c.py`→`d.py`.)
4. **`run_all.py` launched from another working directory** (an agent in `tests/`) → the same files: git always runs with `cwd=repo`. (Task 3: call with the process cwd elsewhere.)
5. **A helper imported as `import _x as y` or `from _x import z`** → both forms count as importing it. (Task 2: `test_lejos`/`test_llave`.)

---

### Task 1: One reading of the rules, and every test has an area

**Files:**
- Create: `tests/_seleccion.py`
- Modify: `tests/test_reglas_claude.py` (drop its own `CABECERA`/`leer()`/source globs, import them; add one check)
- Modify: `.claude/rules/{engine,service,repair,agent,agent-window,llavero,updating,ui,commands-testing,docs-maintenance}.md` (append `paths`)

**Interfaces:**
- Produces, in `tests/_seleccion.py`:
  - `REPO: Path` = `Path(__file__).resolve().parent.parent`
  - `CABECERA` — moved verbatim from `test_reglas_claude.py` (same regex, same docstring)
  - `FUENTES: tuple[str, ...] = ("*.py", "common/*.py", "ui/*.py", "install/*.py")`
  - `leer_regla(ruta: Path) -> tuple[list[str], str] | None` — the former `leer()` of `test_reglas_claude.py`, unchanged behaviour
  - `areas(repo: Path = REPO) -> dict[str, list[str]]` — rule stem → its patterns, for every `.claude/rules/*.md` whose header parses (the others are left out; `test_reglas_claude.py` reports them)
  - `areas_de(ruta: str, mapa: dict[str, list[str]]) -> set[str]` — the areas with a pattern that `fnmatch.fnmatchcase(ruta, patron)` (so a deleted file still matches)
  - `fuentes(repo: Path = REPO) -> list[str]` — sorted POSIX paths of the files matched by `FUENTES` (`glob(…, root_dir=repo)`)

- [ ] **Step 1: Make `test_reglas_claude.py` use the shared reading and add the check.** Replace its `CABECERA`, `leer()` and the inline `fuente = {…}` globs by `from _seleccion import CABECERA, areas, areas_de, fuentes, leer_regla` (the local `ficheros()` and `SIN_REGLA` stay). Before `sys.exit`, add:

```python
mapa = areas()
c("todo test está en los paths de alguna regla (decide qué corre run_all.py --cambios)",
  sorted(p.name for p in (REPO / "tests").glob("test_*.py")
         if not areas_de(f"tests/{p.name}", mapa)), [])
```

- [ ] **Step 2: Run it; it fails.** `PY tests\test_reglas_claude.py` → `ModuleNotFoundError: No module named '_seleccion'`.

- [ ] **Step 3: Create `tests/_seleccion.py`** with the module docstring (what it decides and that it is pure) and the Interfaces above.

- [ ] **Step 4: Run it; only the new check fails.** Expected: `FALLO  todo test está en los paths…` with exactly these 29 names: `test_agente_actualizar_unidad.py`, `test_agente_bitlocker.py`, `test_agente_pedir_al_conectar.py`, `test_agente_registro.py`, `test_buzon_carrera.py`, `test_hijos.py`, `test_keepassxc_pin.py`, `test_logs_acotados.py`, `test_maquina_real_yml.py`, `test_matar_arbol.py`, `test_parseo_seguro.py`, `test_perf.py`, `test_perf_ajustes.py`, `test_perf_anfitrion.py`, `test_perf_flota.py`, `test_perf_parejas.py`, `test_perf_principal.py`, `test_precompilar.py`, `test_rclone_portable.py`, `test_referencia_vacia.py`, `test_reglas_claude.py`, `test_rendimiento_informe.py`, `test_resync_desatendido.py`, `test_run_all.py`, `test_salida_utf8.py`, `test_servicio_ritmo.py`, `test_store_creado.py`, `test_store_ocupado.py`, `test_ventana_hora.py` (if the list differs, a test was added on `main` since: give it an area too).

- [ ] **Step 5: Append the `paths`** (each `  - "tests/<name>.py"` line, keeping the header's exact form):
  - `engine`: `test_logs_acotados`, `test_parseo_seguro`, `test_rclone_portable`, `test_referencia_vacia`, `test_salida_utf8`, `test_ventana_hora`
  - `service`: `test_resync_desatendido`, `test_servicio_ritmo`, `test_store_ocupado`; `repair`: `test_resync_desatendido`
  - `agent`: `test_agente_bitlocker`, `test_store_creado`, `test_agente_registro`
  - `agent-window`: `test_agente_actualizar_unidad`, `test_agente_pedir_al_conectar`, `test_buzon_carrera`
  - `llavero`: `test_agente_registro`, `test_keepassxc_pin`
  - `updating`: `test_precompilar`
  - `ui`: `test_hijos`, `test_matar_arbol`, `test_perf`, `test_perf_ajustes`, `test_perf_anfitrion`, `test_perf_flota`, `test_perf_parejas`, `test_perf_principal`
  - `commands-testing`: `test_run_all`, `test_rendimiento_informe`, `test_maquina_real_yml`
  - `docs-maintenance`: `tests/test_reglas_claude.py` and `.claude/rules/*.md`

- [ ] **Step 6: Run it; it passes.** `PY tests\test_reglas_claude.py` → last line `--- reglas de Claude Code y mapa de docs de AGENTS.md: N comprobaciones OK`, exit 0.

- [ ] **Step 7: Commit** `tests/_seleccion.py tests/test_reglas_claude.py .claude/rules/` — «Cada test tiene su área en las reglas, leídas en un solo sitio».

---

### Task 2: From changed files to tests

**Files:**
- Modify: `tests/_seleccion.py`
- Create: `tests/test_seleccion.py`
- Modify: `.claude/rules/commands-testing.md` (add `"tests/test_seleccion.py"` to `paths`, once the file exists)

**Interfaces:**
- Consumes: Task 1's `REPO`, `areas`, `areas_de`, `fuentes`.
- Produces, in `tests/_seleccion.py`:
  - `LANZADO_POR: dict[str, tuple[str, ...]]` — exactly the spec's table: `"sync.py": ("runsync.py", "ui/tk.py", "ui/console.py", "common/llavero.py", "agente.py")`, `"runsync.py": ("penwatch.py", "agente.py", "common/keepassxc.py", "common/llavero.py", "common/update.py")`, `"penwatch.py": ("ui/watch.py",)`, `"pregunta.py": ("agente.py",)`, `"agente.py": ("install/agente.py",)`. A module table tests replace by assignment.
  - `TODOS: frozenset[str] = frozenset({"common/__init__.py", "tests/_harness.py"})` — changing one selects everything without windows.
  - `importadores(repo: Path = REPO) -> dict[str, set[str]]` — for each source in `fuentes(repo)`, the sources that import it, from `ast.walk` over each whole file (imports inside functions count), resolving `import a.b`, `from a import b` (a submodule `b` counts as `a/b.py`; a name in `a/__init__.py` counts as `a/__init__.py`) and relative imports. Only one hop: never transitive.
  - `@dataclass class Seleccion` with `tests: list[str]` (sorted file names), `motivos: list[str]` (in order of first appearance, one per area or per test, Global Constraints' strings), `fuera: list[str]` (sorted `GUI` names left out), `sin_tests: list[str]` (changed files that brought no test, in input order).
  - `elegir(cambios: list[str] | None, *, gui: set[str], ventanas: bool, repo: Path = REPO) -> Seleccion`
  - `por_areas(nombres: list[str], *, gui: set[str], ventanas: bool, repo: Path = REPO) -> Seleccion` — raises `ValueError(desconocidas: list[str])` when a name is not a rule.

`elegir()` per changed path `ruta`, in order: in `TODOS` → whole result is «todo» with `{ruta} lo importan todos`; `tests/test_*.py` that exists → that test (`{test} ← {ruta}`) (a deleted one falls to the last rule below); `tests/_*.py` → each `tests/test_*.py` whose source matches `^\s*(import|from)\s+{stem}\b` (re.M) (`{test} ← importa {ruta}`), and **not** the rule areas of the helper; anything else → `areas_de(ruta)` (`{área} ← {ruta}`), plus for every `g` in `importadores(repo).get(ruta, ())` the areas of `g` (`{área} ← {g} importa {ruta}`), plus for every `g` in `LANZADO_POR.get(ruta, ())` the areas of `g` (`{área} ← {g} lanza {ruta}`). A path that added neither an area nor a test goes to `sin_tests`. Tests = union of the named tests and every existing `tests/test_*.py` whose `tests/{name}` is in a selected area; then `GUI` names move to `fuera` unless `ventanas`. `None` → «todo» with the «no se sabe…» reason. «Todo» means every existing test file minus `GUI` (into `fuera` unless `ventanas`), with that single motive. `[]` → empty `Seleccion`.

`por_areas()`: each requested area gets `{área} ← pedida`; then for every source in `fuentes(repo)` covered by a requested area, the importer and launcher expansion of `elegir()` (same motive strings); tests and `fuera` as in `elegir()`.

- [ ] **Step 1: Write `tests/test_seleccion.py` against a fake repository.** Docstring in Spanish (what it checks). `from _harness import Checks, tmpdir`, `import _seleccion`, `import run_all`. A helper `repo_falso() -> Path` writes into a `tmpdir()`:
  - `.claude/rules/motor.md` paths `sync.py`, `common/mot*.py`, `tests/test_motor.py`; `llave.md` `common/llave.py`, `tests/test_llave.py`; `lejos.md` `common/lejos.py`, `tests/test_lejos.py`; `servicio.md` `runsync.py`, `tests/test_servicio.py`, `tests/test_tk_servicio.py`; `pruebas.md` `tests/run_all.py`, `tests/_*.py`, `tests/test_run_all.py` (each `---\npaths:\n  - "…"\n---\nCuerpo.\n`);
  - `common/__init__.py` empty; `common/motor.py` empty; `common/llave.py` = `def f():\n    from common import motor\n`; `common/lejos.py` = `from . import llave\n`; `sync.py` = `from common import motor\n`; `runsync.py` = `SYNC = "sync.py"\n`;
  - `tests/_harness.py`, `tests/_falso.py`, `tests/run_all.py` empty; `tests/test_motor.py`, `test_servicio.py`, `test_tk_servicio.py`, `test_run_all.py`, `test_suelto.py` empty; `tests/test_llave.py` = `from _falso import x\n`; `tests/test_lejos.py` = `import _falso as f\n`.

  With `GUI = {"test_tk_servicio.py"}`, `_seleccion.LANZADO_POR = {"sync.py": ("runsync.py",)}` (restored in `finally`), and `e = lambda cambios, ventanas=False: _seleccion.elegir(cambios, gui=GUI, ventanas=ventanas, repo=R)`. `SIN_VENTANA = ["test_lejos.py", "test_llave.py", "test_motor.py", "test_run_all.py", "test_servicio.py", "test_suelto.py"]`. Checks (label → got, want):
  - «importadores: un import dentro de una función cuenta» → `importadores(R)["common/motor.py"]`, `{"common/llave.py", "sync.py"}`
  - «importadores: un import relativo cuenta» → `importadores(R)["common/llave.py"]`, `{"common/lejos.py"}`
  - «motor: su área y la de quien lo importa, un salto (lejos no)» → `e(["common/motor.py"]).tests`, `["test_llave.py", "test_motor.py"]`
  - «motor: dice por qué entra llave» → `"llave ← common/llave.py importa common/motor.py" in …motivos`, `True`
  - «sync.py: las áreas de quien lo lanza; la ventana, fuera» → `(sel.tests, sel.fuera)` for `e(["sync.py"])`, `(["test_motor.py", "test_servicio.py"], ["test_tk_servicio.py"])`
  - «sync.py: dice quién lo lanza» → `"servicio ← runsync.py lanza sync.py" in …motivos`, `True`
  - «con ventanas: la ventana entra» → `e(["sync.py"], True)` tests and fuera, `(["test_motor.py", "test_servicio.py", "test_tk_servicio.py"], [])`
  - «un fichero borrado cuenta por el patrón de su regla» → `e(["common/motor_viejo.py"]).tests`, `["test_motor.py"]`
  - «un test cambiado: ese test» → `e(["tests/test_lejos.py"]).tests`, `["test_lejos.py"]`
  - «un ayudante: los que lo importan, de las dos formas, y no su área» → `e(["tests/_falso.py"]).tests`, `["test_lejos.py", "test_llave.py"]`
  - «_harness: todo lo que no abre ventana» → `(sel.tests, sel.motivos)`, `(SIN_VENTANA, ["todo lo que no abre ventana ← tests/_harness.py lo importan todos"])`
  - «common/__init__.py: todo» → `e(["common/__init__.py"]).tests`, `SIN_VENTANA`
  - «un fichero sin regla: ningún test, y se dice» → `(sel.tests, sel.sin_tests)` for `e(["LICENSE"])`, `([], ["LICENSE"])`
  - «sin cambios: nada, y nada sin tests» → `e([])` as `(tests, motivos, sin_tests, fuera)`, `([], [], [], [])`
  - «sin git: todo lo que no abre ventana, y lo dice» → `(sel.tests, sel.motivos)` for `e(None)`, `(SIN_VENTANA, ["todo lo que no abre ventana ← no se sabe qué cambió (sin git o sin base común con main)"])`
  - «un test de ventana cambiado: fuera» → `e(["tests/test_tk_servicio.py"])` tests and fuera, `([], ["test_tk_servicio.py"])`
  - «--area llave: su área y la de quien importa sus fuentes» → `por_areas(["llave"], …).tests`, `["test_lejos.py", "test_llave.py"]`, and `motivos[0]` is `"llave ← pedida"`
  - «--area con un nombre que no es una regla: ValueError con los desconocidos» → `por_areas(["nada", "llave"], …)` raises, `e.args[0] == ["nada"]`

  Against the real repository (no fakes): `sel = _seleccion.elegir(["common/bisync.py"], gui=set(run_all.GUI), ventanas=False)`:
  - «de verdad: bisync elige engine» → `any(m.startswith("engine ← ") for m in sel.motivos)`, `True`
  - «de verdad: y ningún test de ventana» → `sorted(set(sel.tests) & run_all.GUI)`, `[]`
  - «de verdad: test_bisync_prefijo.py entra» → `"test_bisync_prefijo.py" in sel.tests`, `True`

  `LANZADO_POR` against the code (real module table): with `CONSTANTE = {"sync.py": "model.SYNC_PY", "runsync.py": "model.RUNSYNC_PY", "penwatch.py": "model.PENWATCH_PY"}`:
  - «LANZADO_POR: cada script y cada lanzador existen» → missing paths, `[]`
  - «LANZADO_POR: cada lanzador nombra el script (entre comillas o por su constante de model)» → `[(s, g) for s, gs in LANZADO_POR.items() for g in gs if f'"{s}"' not in texto(g) and (s not in CONSTANTE or CONSTANTE[s] not in texto(g))]`, `[]`

- [ ] **Step 2: Run it; it fails.** `PY tests\test_seleccion.py` → `AttributeError: module '_seleccion' has no attribute 'importadores'`.

- [ ] **Step 3: Implement** `LANZADO_POR`, `TODOS`, `importadores()`, `Seleccion`, `elegir()`, `por_areas()` in `tests/_seleccion.py` as specified in Interfaces.

- [ ] **Step 4: Run it; it passes.** `PY tests\test_seleccion.py` → `--- … N comprobaciones OK`, exit 0.

- [ ] **Step 5: Add `"tests/test_seleccion.py"` to `.claude/rules/commands-testing.md`** and run `PY tests\test_reglas_claude.py` → OK.

- [ ] **Step 6: Commit** `tests/_seleccion.py tests/test_seleccion.py .claude/rules/commands-testing.md` — «Los tests de lo que cambia: su área, y las de quien lo importa o lo lanza».

---

### Task 3: What changed, according to git

**Files:**
- Modify: `tests/_seleccion.py`
- Modify: `tests/test_seleccion.py`

**Interfaces:**
- Produces: `cambiados(repo: Path = REPO) -> list[str] | None` — a test-replaceable indirection point. Base: the first of `git merge-base HEAD origin/main`, `git merge-base HEAD main` that succeeds. Files: `git -c core.quotepath=off diff --name-only --no-renames <base>` plus `git -c core.quotepath=off ls-files --others --exclude-standard`, every git call with `cwd=repo`, `stdin=DEVNULL`, `capture_output=True`, `encoding="utf-8"`; merged without duplicates, sorted. `None` when git is missing (`OSError`), when neither base exists, or when a listing command fails.

- [ ] **Step 1: Add the git checks to `tests/test_seleccion.py`.** If `shutil.which("git") is None`: `print("  (saltado) sin git en este equipo")`. Otherwise, in a `tmpdir()` `G`, with a helper `git(*args)` running `["git", "-c", "user.name=t", "-c", "user.email=t@t", *args]` in `G` (check=True): `init -q -b main`; write `a.txt`, `b.py`, `c.py`; `add -A`; `commit -q -m base`; `checkout -q -b rama`; modify `b.py`, `mv c.py d.py` (`git mv`), `commit -q -am rama`; modify `a.txt` (unstaged); write and `add` `e.txt` (staged); write untracked `ñandú x.txt`. Then, with `os.chdir()` to another `tmpdir()` (restored in `finally`):
  - «cambiados: lo de la rama, lo preparado, lo modificado y lo nuevo; un renombrado por sus dos nombres; con tildes y espacios» → `_seleccion.cambiados(G)`, `["a.txt", "b.py", "c.py", "d.py", "e.txt", "ñandú x.txt"]`
  - after `git update-ref refs/remotes/origin/main HEAD`: «cambiados: origin/main manda sobre main» → `_seleccion.cambiados(G)`, `["a.txt", "e.txt", "ñandú x.txt"]`
  - «cambiados: fuera de un repositorio, None» → `_seleccion.cambiados(tmpdir())`, `None`

- [ ] **Step 2: Run it; it fails** with `AttributeError: … 'cambiados'`.

- [ ] **Step 3: Implement `cambiados()`** as in Interfaces, docstring stating it is an indirection point (tests replace it) and what `None` means.

- [ ] **Step 4: Run it; it passes.** `PY tests\test_seleccion.py` → OK, exit 0.

- [ ] **Step 5: Commit** `tests/_seleccion.py tests/test_seleccion.py` — «Qué ha cambiado contra main, según git».

---

### Task 4: `run_all.py`: no windows by default, `--cambios`, `--area`, `--ventanas`

**Files:**
- Modify: `tests/run_all.py` (`_analizar()`, `main()`, the module docstring; new `seleccionar()`, `_sufijo()`)
- Modify: `tests/test_run_all.py` (docstring list; sections 5, 5b and 14 pass `--ventanas`; new sections 18–20)
- Modify: `.github/workflows/tests.yml`

**Interfaces:**
- Consumes: `_seleccion.cambiados()`, `_seleccion.elegir()`, `_seleccion.por_areas()`, `_seleccion.Seleccion` (Tasks 2–3).
- Produces, in `tests/run_all.py`:
  - options: `--ventanas` (store_true); a mutually exclusive group with `--cambios` (store_true) and `--area ÁREA [ÁREA …]` (`nargs="+"`). Help texts in Spanish.
  - `seleccionar(a: argparse.Namespace, todos: list[Path]) -> tuple[list[Path], int] | int` — the files this pass runs and how many `GUI` files were left out, or an exit code when the pass ends here: 2 for an unknown test name (existing message), an unknown area, or names together with `--cambios`/`--area`; 0 when `--cambios`/`--area` select nothing. Prints the header block (Global Constraints) for `--cambios`/`--area`. Without names, `--cambios` or `--area`: `todos`, minus `GUI` unless `a.ventanas`. With names: exactly those, `GUI` included, 0 left out.
  - `_sufijo(n: int) -> str` — the last-line suffix from Global Constraints.

- [ ] **Step 1: Update `tests/test_run_all.py`.** Add `"--ventanas"` to the `lanzar()` calls of sections 5, 5b and 14 (their fake tests have `GUI` names). Add a template beside the other `LANZADOR_*`:

```python
LANZADOR_SELECCION = """\
import sys
import _seleccion
import run_all

PLAN = __PLAN__  # lo que dan cambiados(), elegir() y por_areas() falsos
_seleccion.cambiados = lambda repo=None: PLAN["cambios"]


def elegir(cambios, *, gui, ventanas, repo=None):
    return _seleccion.Seleccion(**PLAN["seleccion"])


def por_areas(nombres, *, gui, ventanas, repo=None):
    if PLAN.get("desconocidas"):
        raise ValueError(PLAN["desconocidas"])
    return _seleccion.Seleccion(**PLAN["seleccion"])


_seleccion.elegir = elegir
_seleccion.por_areas = por_areas
raise SystemExit(run_all.main(sys.argv[1:]))
"""
"""Corre `run_all.py` con una selección dada: la copia de `_seleccion.py` con sus funciones sustituidas."""
```

  New sections before «17.» (each with `preparar(...)`; for 19 pass `otros={"_seleccion.py": (TESTS_DIR / "_seleccion.py").read_text(encoding="utf-8")}`):
  - **18. Sin ventanas por defecto.** Folder `test_a.py`, `test_tk_servicio.py`, `test_tk_medidas.py` (all `(0, 0)`):
    - no args → `cabeceras`, `["test_a.py"]`; `ultima`, `"Los 1 ficheros de test pasan (2 de ventanas sin correr: van en el CI, o con --ventanas)."`
    - `--ventanas` → `cabeceras`, `["test_a.py", "test_tk_medidas.py", "test_tk_servicio.py"]`; `ultima`, `"Los 3 ficheros de test pasan."`
    - `test_tk_medidas.py` by name → `(rc, cabeceras, ultima)`, `(0, ["test_tk_medidas.py"], "Los 1 ficheros de test pasan.")`
    - folder `test_falla.py` `(0, 1)` + `test_tk_servicio.py` `(0, 0)`, no args → `ultima`, `"FALLAN 1 de 1: test_falla.py (1 de ventanas sin correr: van en el CI, o con --ventanas)"`
  - **19. `--cambios` y `--area`.** Folder `test_a.py`, `test_b.py`, `test_tk_servicio.py`, plan `seleccion = {"tests": ["test_a.py"], "motivos": ["engine ← common/bisync.py"], "fuera": ["test_tk_servicio.py"], "sin_tests": ["LICENSE"]}`, `cambios = ["common/bisync.py", "LICENSE"]`, via `lanzar_falso(carpeta, LANZADOR_SELECCION, plan, …)`:
    - `--cambios` → `cabeceras`, `["test_a.py"]`; contains `"Áreas (por los cambios de esta rama):"`, `"  engine ← common/bisync.py"`, `"Sin tests: LICENSE"`, `"Fuera, por abrir ventanas (van en el CI; por nombre o con --ventanas): test_tk_servicio.py"`; `ultima`, `"Los 1 ficheros de test pasan (1 de ventanas sin correr: van en el CI, o con --ventanas)."`
    - `--area engine` → `cabeceras`, `["test_a.py"]`; contains `"Áreas (por --area):"`
    - seleccion `{"tests": [], "motivos": [], "fuera": [], "sin_tests": ["LICENSE"]}` → `(rc, ultima, cabeceras)`, `(0, "Estos cambios no tienen tests: LICENSE", [])`
    - seleccion all empty → `(rc, ultima)`, `(0, "No hay cambios contra main.")`
    - seleccion `{"tests": [], "motivos": ["servicio ← runsync.py"], "fuera": ["test_tk_servicio.py"], "sin_tests": []}` → `(rc, ultima)`, `(0, "Estos cambios solo tienen tests de ventanas.")`
    - plan `desconocidas = ["nada"]`, `--area nada` → `rc`, `2`; contains `"No hay ningún área que se llame: nada"`
    - `--cambios test_a.py` → `(rc, cabeceras)`, `(2, [])`; `--cambios --area x` → `rc`, `2`
  - **20. El CI abre las ventanas.** `yml = (TESTS_DIR.parent / ".github/workflows/tests.yml").read_text(encoding="utf-8")`; `lineas = [l for l in yml.split("\n  python-minimo:")[0].splitlines() if "tests/run_all.py" in l]`:
    - «tests.yml: el trabajo tests corre run_all.py en Linux y en Windows» → `len(lineas)`, `2`
    - «tests.yml: los dos con --ventanas» → `[l for l in lineas if "--ventanas" not in l]`, `[]`

  Add the new behaviour to the module docstring's list (no windows by default and the suffix; `--cambios`/`--area` with their messages; the CI check).

- [ ] **Step 2: Run it; it fails.** `PY tests\test_run_all.py` → section 5 fails on `--ventanas` (unknown option, rc 2) and sections 18–20 fail.

- [ ] **Step 3: Implement** the options, `seleccionar()` and `_sufijo()` in `tests/run_all.py`; `main()` calls `seleccionar()` where it now builds `scripts` from `a.nombres`, returns an `int` result as is, and appends `_sufijo(fuera)` to both last lines. `import _seleccion` goes inside `seleccionar()`, in the `--cambios`/`--area` branch. Update the module docstring (what runs with no arguments, the three new options).

- [ ] **Step 4: Add `--ventanas` to the two `run_all.py` steps of job `tests`** in `.github/workflows/tests.yml` (`-j auto --display xvfb --ventanas` and `-j auto --gui-jobs 1 --ventanas`), and add to the file's header comment one line: the suite with no options opens no window; `--ventanas` makes CI open them all.

- [ ] **Step 5: Run it; it passes.** `PY tests\test_run_all.py` → OK, exit 0 (about 40 s). Then `PY tests\test_seleccion.py` → OK.

- [ ] **Step 6: Commit** `tests/run_all.py tests/test_run_all.py .github/workflows/tests.yml` — «run_all.py ya no abre ventanas salvo que se pidan, y elige por los cambios».

---

### Task 5: Agents, docs and permissions, and the real check

**Files:**
- Modify: `AGENTS.md` («Commands and verification»)
- Modify: `docs/agents/reference/commands-testing.md`
- Modify: `.claude/hooks/session_start.sh`
- Modify: `.claude/settings.json`
- Modify: `.claude/skills/new-area-doc/SKILL.md`

**Interfaces:**
- Consumes: the CLI from Task 4, `LANZADO_POR`/`cambiados()` from Tasks 2–3.

- [ ] **Step 1: `AGENTS.md`.** In the command block, replace the line `python tests/run_all.py     # all tests, each in its own process; or run one script directly` by:

```
python tests/run_all.py --cambios -j auto  # while working: the tests of what the diff against main touches, and of what imports or launches it; never a window
python tests/run_all.py -j auto            # every test that opens no window; --ventanas adds them (CI does); or run one script directly
```

  In the first verification bullet, `Verification is \`tests/run_all.py\`, \`--doctor\`, \`--dry-run\`.` becomes `Verification while working is \`tests/run_all.py --cambios -j auto\`, then \`--doctor\`, \`--dry-run\`. Tk tests never open a window locally unless named or \`--ventanas\`: CI runs all of them. A new test goes in the \`paths\` of its area's rule (\`commands-testing.md\`).`, and `CI (…) runs \`run_all.py\` on every PR` becomes `CI (…) runs every test (\`run_all.py --ventanas\`) on every PR`. Nothing else in `AGENTS.md`.

- [ ] **Step 2: `commands-testing.md`.**
  - In «Commands», the `run_all.py` line becomes `python tests/run_all.py [--cambios | --area ÁREA… | files] [--ventanas] -j N|auto  --display inherit|xvfb  --gui-jobs K  --timeout S  # no args: every test that opens no window; or run one script directly`.
  - In «Verification», after «Nothing to lint.», add one sentence: with no arguments `run_all.py` runs every file except `GUI` and its last line says how many were left out (quote the suffix); `--ventanas` adds them; names run exactly those, windows included; `--cambios`/`--area` choose by area (next section). In the CI sentence, the two commands gain `--ventanas`, and add that `tests/test_run_all.py` checks both steps carry it.
  - New section `## Choosing tests by area`, between «Verification» and «Timing check», in English, covering exactly: the map is the `paths` of `.claude/rules/*.md` (sources and tests per area; every `tests/test_*.py` must be in one: `test_reglas_claude.py`); `_seleccion.cambiados()`'s base and git commands; the per-file rules (source → its areas + one hop of importers + `LANZADO_POR`; changed test → itself; helper → its importers; `TODOS` → everything without windows; anything else → its rule areas, or nothing); `--area`'s expansion; `GUI` left out unless `--ventanas`; the three «nothing to run» endings and the «todo» fallback; that the selection can miss a two-hop dependency on purpose, because CI runs everything. Cite the spec path.
  - In «Indirection points», add a bullet **Test selection**: `_seleccion.cambiados()` (git, `None` without git or base; `tests/test_seleccion.py` runs the real one on a temp repository) and the module table `_seleccion.LANZADO_POR` (tests replace it by assignment).

- [ ] **Step 3: Hook, permissions, skill.**
  - `session_start.sh`: the last `echo` ends `Verificación: python tests/run_all.py --cambios -j auto (sin ventanas; las ventanas, en el CI)."`.
  - `settings.json` `permissions.allow`: add `"Bash(python tests/run_all.py *)"` and `"Bash(python3 tests/run_all.py *)"` after their existing exact entries.
  - `new-area-doc/SKILL.md`: under the rule's `paths`, one line: every `tests/test_*.py` of the area goes there too; it decides what `run_all.py --cambios` runs, and `tests/test_reglas_claude.py` fails for a test in no rule.

- [ ] **Step 4: Docs checks.** `PY tests\test_reglas_claude.py` → OK, exit 0.

- [ ] **Step 5: The real check on this branch, no window may open.** `PY tests\run_all.py --cambios -j auto` → the motives include a line starting `commands-testing ← ` and one starting `docs-maintenance ← `, and `test_reglas_claude.py ← tests/test_reglas_claude.py`; a `Sin tests:` line lists at least `.claude/settings.json`; no window appears on the desktop; last line `Los N ficheros de test pasan…`. Then `PY tests\run_all.py -j auto` → `Los 127 ficheros de test pasan (54 de ventanas sin correr: van en el CI, o con --ventanas).` (127 = 126 + `test_seleccion.py`). A failure in a file this branch does not touch: re-run it alone (`test_catalog.py` flakes under load), and report it instead of fixing it here.

- [ ] **Step 6: Commit** `AGENTS.md docs/agents/reference/commands-testing.md .claude/hooks/session_start.sh .claude/settings.json .claude/skills/new-area-doc/SKILL.md` — «Los agentes verifican con --cambios: los docs y los permisos».
