# The agent sees a BitLocker-locked drive: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the resident agent recognises a listed drive that is plugged in but locked with BitLocker, shows it in the tray as «(bloqueada)» and offers «Desbloquear…», which opens Windows' own prompt.

**Architecture:** the agent remembers, per listed drive, the Windows volume name (`\\?\Volume{GUID}\`) where it last attended it with BitLocker on (`equipo.Unidad.volumen`, in the host's `agente.json`). The walk compares unreadable drive letters against those names and asks the existing unelevated reader whether the match is `BDE_LOCKED`. The result travels in `resumen()["bitlocker"]` to the pure tray; the unlock is `bdeunlock.exe`, launched through a replaceable module function.

**Tech Stack:** Python 3.11+ stdlib only (`ctypes` for `kernel32`), the repo's plain-script tests (`tests/_harness.Checks`, `tests/_agente_falso`).

**Spec:** `docs/superpowers/specs/2026-10-10-agente-bitlocker-bloqueada-design.md`

## Global Constraints

- Stdlib only. Comments, docstrings (Google style) and user-facing text in **Spanish**; `docs/agents/` in English. Read `docs/agents/code-writing-conventions.md` before writing Python.
- `ui/bandeja.py` stays pure and imports no Tk; `agente.py` imports no Tk; `penwatch.py` is not touched.
- Everything that touches the OS is a module-level function a test can replace: `bitlocker.volumen_de()` (over `bitlocker._leer_volumen()`), `cifrada.bitlocker_de()` (existing), `agente.desbloquear_bitlocker()`.
- No Windows gate in the agent's detection: off Windows `volumen_de()` returns `""`, so nothing is ever remembered and nothing is ever looked for. Only the cadence reads `IS_WIN`.
- Nothing is read from or run on a locked drive. Nothing in this change skips a step of the normal connect path (two sightings, code fingerprint, mode).
- No path under test is a drive letter or a fixed absolute path: roots are `tmpdir()`s and the fakes answer for them (`commands-testing.md`).
- Exact copy: label «{nombre} (bloqueada)»; entries «Desbloquear…» and «Desbloqueando: la contraseña la pide Windows»; tooltip phrase «{nombre} bloqueada»; diary «{nombre}: bloqueada con BitLocker en {raiz}»; notice title «{nombre}: no he podido abrir el desbloqueo de Windows», text «Desbloquéala desde el Explorador.»; `agente.py status` line «Bloqueada con BitLocker: {nombre} en {raiz} (agente.py desbloquear {id})».
- Cadence values: `RECORRIDO_WINDOWS` (5 s) while a known drive is locked, `RECORRIDO_RESPALDO` (30 s) otherwise; `RAFAGA` (60 s) after an unlock request.
- One commit per task, Spanish subject as given, footer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push.
- Run tests from PowerShell with a concrete interpreter and the real `LOCALAPPDATA`: `& "C:\Users\pjcer\AppData\Local\Python\pythoncore-3.14-64\python.exe" tests\<file>.py`. Never touch `P:` or the installed agent in `%LOCALAPPDATA%\prdrive`. Each new check fails before its code exists.

## Review Focus

1. **Windows fails a volume read mid-walk** (drive pulled, COM or `kernel32` error): the walk carries on for every other drive. → Task 1 (`volumen_de()` never raises), Task 4 (a nameless root among others).
2. **`agente.json` edited by hand or by another agent version** (`volumen` not a string, another shape, upper-case GUID, on a host root): dropped or normalised, and the drive still loads. → Task 2.
3. **Drive unplugged while locked, with Windows' prompt open:** it leaves the tray, its process is forgotten, and replugged it offers «Desbloquear…» live again. → Task 5.
4. **`desbloquear` with no id, or with an encrypted host root's id, while a BitLocker drive is locked:** still goes to VeraCrypt's root and never launches `bdeunlock`. → Task 5.
5. **A shown drive is switched to `nada` or leaves the list:** gone at the next walk, and a request for it launches nothing. → Task 4, Task 5.

---

### Task 1: `common/bitlocker.py` knows a volume's name and how to unlock it

**Files:**
- Modify: `common/bitlocker.py`
- Test: `tests/test_cifrada.py` (append before `sys.exit`)

**Interfaces (produces):**
- `BitLockerStatus.locked -> bool`: `known and state == BDE_LOCKED`.
- `BitLockerStatus.present -> bool`: `known and state not in (BDE_OFF, BDE_NOT_ENCRYPTABLE)`.
- `_leer_volumen(raiz: str) -> str`: `kernel32.GetVolumeNameForVolumeMountPointW(raiz, buf, 50)`; raises `OSError` when Windows refuses. `ctypes` imported inside.
- `volumen_de(raiz: Path | str, es_win: bool = os.name == "nt") -> str`: the name in lower case; `""` off Windows, when `raiz` is not the root of a drive letter, or on **any** exception. Calls `_leer_volumen` through the module at call time.
- `orden_desbloquear(raiz: Path | str, es_win: bool = os.name == "nt") -> list[str] | None`: `[<SystemRoot>\System32\bdeunlock.exe, "E:\\"]`; `None` off Windows, for a non-root path, or when the file is missing. `SystemRoot` is read like `agente.orden_explorar()` does (`SystemRoot`, `WINDIR`, `C:\Windows`).
- Private `_raiz_de_letra(raiz) -> str`: `"E:\\"` (upper case) or `""`, decided with `PureWindowsPath` so it gives the same answer on Linux.

- [ ] **Step 1: failing checks** in `tests/test_cifrada.py`:

```python
S = bitlocker.BitLockerStatus
c("locked: solo el estado bloqueado y comprobado",
  [S(True, e).locked for e in (bitlocker.BDE_LOCKED, bitlocker.BDE_ON)]
  + [S(False, bitlocker.BDE_LOCKED).locked], [True, False, False])
c("present: cualquier estado conocido menos apagado y no cifrable",
  {e: S(True, e).present for e in bitlocker.BDE_TEXTOS},
  {e: e not in (bitlocker.BDE_OFF, bitlocker.BDE_NOT_ENCRYPTABLE) for e in bitlocker.BDE_TEXTOS})
c("  sin comprobar, no", S(False).present, False)
leer_volumen = bitlocker._leer_volumen
try:
    pedidas = []
    bitlocker._leer_volumen = lambda r: pedidas.append(r) or "\\\\?\\Volume{ABCD-12}\\"
    c("volumen_de: el nombre, en minúsculas, pedido con la raíz de la letra",
      (bitlocker.volumen_de("e:", True), bitlocker.volumen_de(Path("E:\\"), True), pedidas),
      ("\\\\?\\volume{abcd-12}\\",) * 2 + (["E:\\", "E:\\"],))
    c("  fuera de Windows, de una carpeta o de una ruta relativa, nada",
      [bitlocker.volumen_de("E:\\", False), bitlocker.volumen_de("E:\\datos", True),
       bitlocker.volumen_de("datos", True), bitlocker.volumen_de("/media/x", True)], [""] * 4)
    for fallo in (OSError("retirada"), RuntimeError("COM")):
        def revienta(r, e=fallo):
            raise e
        bitlocker._leer_volumen = revienta
        c(f"  si Windows falla ({type(fallo).__name__}), nada y sin lanzar",
          bitlocker.volumen_de("E:\\", True), "")
finally:
    bitlocker._leer_volumen = leer_volumen
```

plus, with `os.environ["SystemRoot"]` pointed at a `tmpdir()` (restored in `finally`): `orden_desbloquear("e:", True)` is `None` without `System32/bdeunlock.exe`; with the file it is `[str(tmp / "System32" / "bdeunlock.exe"), "E:\\"]`; `orden_desbloquear("E:\\", False)` and `orden_desbloquear("E:\\datos", True)` are `None`.

- [ ] **Step 2:** run `tests\test_cifrada.py`; it fails with `AttributeError: ... 'locked'`.
- [ ] **Step 3:** implement the interfaces above; extend the module docstring to say the agent also asks here.
- [ ] **Step 4:** run `tests\test_cifrada.py` and `tests\test_crypto_bitlocker.py`: both pass.
- [ ] **Step 5:** commit «BitLocker: el nombre de un volumen y la orden que lo desbloquea, sin elevar».

### Task 2: `agente.json` remembers a drive's volume

**Files:**
- Modify: `common/equipo.py` (`Unidad`, `desde_dict()`, `a_dict()`)
- Create: `tests/test_agente_bitlocker.py` (docstring listing what it pins; grows in Tasks 3–5)

**Interfaces (produces):**
- `equipo.Unidad.volumen: str = ""`, the **last** field, documented in the class `Args:`.
- `equipo.FORMA_VOLUMEN`: compiled regex for `\\?\volume{…}\` (lower case, whole string), with its docstring.
- `desde_dict()` keeps `volumen` only when it is a string that matches after `.strip().lower()` and the unit has no `ruta`; `a_dict()` writes the key only when set.

- [ ] **Step 1: failing checks** (start of the new file; `V1 = "\\\\?\\volume{11111111-1111-1111-1111-111111111111}\\"`):

```python
def ida_y_vuelta(u):
    return equipo.desde_dict(equipo.a_dict(equipo.Ajustes(unidades={u.id: u}))).unidades[u.id]

c("agente.json: el volumen va y vuelve", ida_y_vuelta(equipo.Unidad(A, volumen=V1)).volumen, V1)
c("  sin volumen no se escribe la clave",
  "volumen" in equipo.a_dict(equipo.Ajustes(unidades={A: equipo.Unidad(A)}))["unidades"][A], False)
cruda = lambda v, **mas: equipo.desde_dict({"unidades": {A: {"volumen": v, **mas}}}).unidades[A]
c("  en mayúsculas se guarda en minúsculas", cruda(V1.upper()).volumen, V1)
c("  lo que no tiene esa forma, o no es texto, se descarta y la unidad sigue",
  [cruda(v).volumen for v in ("E:\\", "volume{x}", 7, None, V1 + "x")], [""] * 5)
c("  una raíz de este equipo no lo lleva", cruda(V1, ruta="/algo").volumen, "")
c("  un agente.json de antes se lee igual",
  equipo.desde_dict({"unidades": {A: {"modo": "daemon"}}}).unidades[A].volumen, "")
```

- [ ] **Step 2:** run it; fails with `TypeError: ... unexpected keyword argument 'volumen'`.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** run `tests\test_agente_bitlocker.py`, `tests\test_planificador.py`, `tests\test_cifrada.py`, `tests\test_install_agente.py`: pass.
- [ ] **Step 5:** commit «agente.json recuerda el volumen de una unidad con BitLocker».

### Task 3: the agent remembers the volume when it attends a drive

**Files:**
- Modify: `agente.py` (import `bitlocker, cifrada` from `common`; `Agente._apuntar_volumen()`; calls in `_conectar()` and `_atender()`)
- Test: `tests/test_agente_bitlocker.py`

**Interfaces:**
- Consumes: `bitlocker.volumen_de(raiz)`, `cifrada.bitlocker_de(raiz) -> BitLockerStatus`, `Unidad.volumen`.
- Produces: `Agente._apuntar_volumen(self, con: Conexion) -> None`. Rule, in order: unit not listed or `es_raiz` → nothing; state not `known` → nothing; `present` → `nuevo = volumen_de(con.raiz)`, and an empty name leaves it untouched; known and not `present` → `nuevo = ""`; equal to the stored one → no write; otherwise one `_guardar()` that also clears `nuevo` from every other unit holding it, and a diary line.
- Called in `_conectar()` after the name is saved (so never for `vieja`, unlisted or `cambiada` drives, which return earlier) and in `_atender()` after each `_guardar()`.

Test fakes, set once at the top of the file after `F.preparar()`:

```python
VOLUMENES: dict[Path, str] = {}     # raíz → nombre de volumen; sin entrada, ""
ESTADOS: dict[Path, int] = {}       # raíz → BDE_*; sin entrada, sin comprobar
bitlocker.volumen_de = lambda raiz, es_win=True: VOLUMENES.get(Path(raiz), "")
cifrada.bitlocker_de = lambda raiz: (bitlocker.BitLockerStatus(True, ESTADOS[Path(raiz)])
                                     if Path(raiz) in ESTADOS
                                     else bitlocker.BitLockerStatus(False, detail="sin comprobar"))
```

- [ ] **Step 1: failing checks.** With `RA = F.unidad(A, nombre="Trabajo")` listed with its fingerprint (helper `lista()` as in `tests/test_agente_expulsar.py`), `F.RAICES[:] = [RA]`, a fresh agent and `F.vueltas(ag, 3)` each time:
  - `ESTADOS[RA] = BDE_ON`, `VOLUMENES[RA] = V1` → `equipo.leer_ajustes().unidades[A].volumen == V1`, and the same for `BDE_SUSPENDED`.
  - reconnecting with the same values writes nothing (count the calls to `equipo.guardar_ajustes` through a wrapper).
  - no entry in `ESTADOS` (unknown) → the stored `V1` stays.
  - `BDE_ON` with no entry in `VOLUMENES` → stays.
  - `ESTADOS[RA] = BDE_OFF` → `""`.
  - a second listed drive `B` holding `V1`; `A` connects on `V1` → `B.volumen == ""`, `A.volumen == V1`.
  - a drive whose fingerprint differs (`cambiada`) and an unlisted one → nothing stored; after answering yes (`F.preguntas()[-1].rc = 0`, one more turn) → stored.
  - a host root (`Unidad(Q, ..., ruta=str(RQ))`, built as in `test_agente_expulsar.py`) with `ESTADOS[RQ] = BDE_ON`, `VOLUMENES[RQ] = V2` → `volumen == ""`.
- [ ] **Step 2:** run; the first check fails (`'' != V1`).
- [ ] **Step 3:** implement.
- [ ] **Step 4:** run `tests\test_agente_bitlocker.py`, `tests\test_unidad_nueva.py`, `tests\test_agente_contrato.py`, `tests\test_agente_endurecido.py`: pass.
- [ ] **Step 5:** commit «El agente apunta el volumen de las unidades con BitLocker que atiende».

### Task 4: the walk sees a known drive locked

**Files:**
- Modify: `agente.py` (`Agente.bitlocker`, `_recorrer()`, `_mirar_bitlocker()`, `cada_recorrido()`, `cmd_run()`, `resumen()`, `cmd_status()`, the dataclass docstring)
- Test: `tests/test_agente_bitlocker.py`

**Interfaces:**
- Consumes: Task 3's fakes and `Unidad.volumen`.
- Produces:
  - `Agente.bitlocker: dict[str, Path]` (id → root), rebuilt on every walk.
  - `Agente._mirar_bitlocker(self, resto: list[Path]) -> None`. `resto` is every candidate root that gave neither a control file nor a vestibule, including those that raised `OSError`; `_recorrer()` collects it and calls this before `self.recorridos += 1`. Candidates: listed units with `volumen`, not `es_raiz`, `modo != equipo.NADA`, not in `self.conexiones`. With no candidate, no root is asked anything. A root matches by `bitlocker.volumen_de(raiz)`; it counts only if `cifrada.bitlocker_de(raiz).locked`. First match per id wins. Diary line for each id not in the previous map.
  - `Agente.cada_recorrido(self) -> float`: `RECORRIDO_WINDOWS if IS_WIN and (self.bandeja is None or self.bitlocker) else RECORRIDO_RESPALDO`. `cmd_run()` uses it for `proximo` instead of the fixed `cada`.
  - `resumen()["bitlocker"]`: `[{"id", "nombre", "raiz", "desbloqueando"}]` sorted by `(nombre, id)`; `nombre` is `unidad.nombre or id[:8]`; `desbloqueando` is `False` until Task 5.
  - `agente.py status` (`cmd_status()`) prints the status line of Global Constraints for each entry of `estado.json`.

- [ ] **Step 1: failing checks.** `E = tmpdir("prdrive-letra-")` is the locked letter: `VOLUMENES[E] = V1`, `ESTADOS[E] = bitlocker.BDE_LOCKED`, `F.RAICES[:] = [E]`, drive `A` listed with `volumen=V1`:

```python
F.vueltas(ag, 1)
c("bloqueada y conocida: sale en el resumen a la primera",
  ag.resumen()["bitlocker"],
  [{"id": A, "nombre": "Trabajo", "raiz": str(E), "desbloqueando": False}])
c("  no es una conexión ni se lanza nada", (A in ag.conexiones, F.LANZADOS), (False, []))
c("  y el diario lo dice una vez",
  [d for d in F.DIARIO if "BitLocker" in d], [f"Trabajo: bloqueada con BitLocker en {E}"])
```

  then, each on its own walk: three more walks add no diary line; `ESTADOS[E]` set to each of `BDE_ON`, `BDE_OFF`, `BDE_SUSPENDED` or removed (unknown) → `[]`; `VOLUMENES[E] = V2` (unknown volume) → `[]`; unit in mode `equipo.NADA` → `[]`, and back to `DAEMON` → shown; unit removed from the list → `[]`; a root with no name before `E` in `F.RAICES` does not hide it; with no listed unit carrying `volumen`, `volumen_de` is never called (count the calls); a root that answers with an error (a `type(Path())` subclass whose `is_file()` raises `PermissionError`; `raiz / x` keeps the subclass) is still matched.
  - **Unlocked:** `F.RAICES[:] = [RA]`, `VOLUMENES[RA] = V1`, `ESTADOS[RA] = BDE_ON`, `F.vueltas(ag, 3)` → `A in ag.conexiones`, `ag.resumen()["bitlocker"] == []`, its lock is taken as usual. With another fingerprint on `RA` → not served and a question is asked, as always.
  - **Cadence:** with a fake `ag.bandeja`, `agente.IS_WIN = True`: `ag.cada_recorrido()` is `agente.RECORRIDO_WINDOWS` with one locked and `agente.RECORRIDO_RESPALDO` with none; with `ag.bandeja = None` it is `RECORRIDO_WINDOWS`; with `agente.IS_WIN = False` it is `RECORRIDO_RESPALDO`. Restore `IS_WIN` in `finally`.
  - **Status:** with `estado.json` written by the agent and `equipo.agente_vivo` answering for it, `agente.py status` through `agente.main()` with stdout captured → contains the status line.
- [ ] **Step 2:** run; fails with `KeyError: 'bitlocker'`.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** run `tests\test_agente_bitlocker.py`, `tests\test_bandeja.py`, `tests\test_agente_veracrypt.py`, `tests\test_agente_raiz.py`, `tests\test_unidad_nueva.py`: pass.
- [ ] **Step 5:** commit «El agente ve una unidad de la lista bloqueada con BitLocker».

### Task 5: «Desbloquear…» opens Windows' prompt

**Files:**
- Modify: `agente.py` (`desbloquear_bitlocker()`, `Agente.desbloqueos_bitlocker`, `_desbloquear_bitlocker()`, the `PIDE_DESBLOQUEAR` branch of the mailbox handler, `resumen()`, `_mirar_bitlocker()` pruning, the `desbloquear` subcommand's help), `common/equipo.py` (the comment beside `PIDE_DESBLOQUEAR`)
- Test: `tests/test_agente_bitlocker.py`

**Interfaces:**
- Consumes: `bitlocker.orden_desbloquear(raiz)`, `Agente.bitlocker`.
- Produces:
  - `agente.desbloquear_bitlocker(raiz: Path) -> Any | None` (module level, replaceable): launches `bitlocker.orden_desbloquear(raiz)` with `lanzar()`, `stdin/stdout/stderr=DEVNULL`, `cwd=str(equipo.DIR)`, `close_fds=True`, and returns the process; `None` when there is no order. Lets `OSError` out.
  - `Agente.desbloqueos_bitlocker: dict[str, Any]` (id → process).
  - `Agente._desbloquear_bitlocker(self, uid: str, ahora: float) -> None`: a live previous process → nothing; otherwise launch; `None` or `OSError` → the notice of Global Constraints (urgent) and no entry; success → store the process, `rafaga_hasta = max(rafaga_hasta, ahora + RAFAGA)`, a diary line.
  - Mailbox: `PIDE_DESBLOQUEAR` with an id in `self.bitlocker` whose unit is still listed and not in mode `nada` (the mailbox is read before the walk) → `_desbloquear_bitlocker()`. With the id of a listed non-root unit that has `volumen` but is not locked now → diary «{nombre}: no está bloqueada con BitLocker ahora», nothing else. Anything else (empty id included) → today's path.
  - `resumen()["bitlocker"][i]["desbloqueando"]`: its process exists and `poll() is None`.
  - `_mirar_bitlocker()` drops from `desbloqueos_bitlocker` every id no longer locked.

Test fake: `DESBLOQUEOS: list[Path] = []`, `PROCESOS: list = []`, and a `def desbloqueo_falso(raiz)` that appends `Path(raiz)` to the first, a `F.Proc(["bdeunlock.exe", str(raiz)])` to the second and returns that process; `agente.desbloquear_bitlocker = desbloqueo_falso`. `F.Proc` also lands in `F.LANZADOS`: checks about «nothing launched» filter it out.

- [ ] **Step 1: failing checks**, starting from Task 4's locked state:
  - `equipo.pedir({"pide": equipo.PIDE_DESBLOQUEAR, "id": A})`, one turn → `DESBLOQUEOS == [E]`, `ag.resumen()["bitlocker"][0]["desbloqueando"] is True`, `ag.rafaga_hasta >= F.reloj() - agente.TICK + agente.RAFAGA`.
  - a second request with the process alive → still one launch.
  - `PROCESOS[-1].rc = 1` (cancelled), one turn → `desbloqueando is False`; a new request launches again (`len(DESBLOQUEOS) == 2`).
  - the fake returning `None`, and raising `OSError("x")` → no entry, and `F.AVISOS` gains `("Trabajo: no he podido abrir el desbloqueo de Windows", "Desbloquéala desde el Explorador.")` each time.
  - **Review Focus 3:** request, process alive, `F.RAICES[:] = []`, walk → `ag.resumen()["bitlocker"] == []` and `ag.desbloqueos_bitlocker == {}`; `F.RAICES[:] = [E]`, walk → shown with `desbloqueando False`.
  - **Review Focus 4:** with an encrypted host root `Q` listed (as in `tests/test_agente_veracrypt.py`), requests with `id: ""` and `id: Q` → no new entry in `DESBLOQUEOS`, and the root's own unlock is asked (what that test already observes).
  - **Review Focus 5:** drive switched to `nada` (`equipo.pedir({"pide": equipo.PIDE_MODO, "id": A, "modo": "nada"})`) then a request → nothing launched and a diary line; an id that is not locked now → «no está bloqueada con BitLocker ahora».
  - **Unlocked while asking:** process alive, `F.RAICES[:] = [RA]` (readable), three turns → connected, `desbloqueos_bitlocker == {}`.
  - **CLI:** `sys.argv = ["agente.py", "desbloquear", A]`, `agente.main()` → `equipo.recoger()` holds `(PIDE_DESBLOQUEAR, A)`.
  - **The real launcher** (restore the real `agente.desbloquear_bitlocker` for this block): with `bitlocker.orden_desbloquear = lambda raiz: ["x.exe", "E:\\"]` → one `F.LANZADOS` entry with exactly those args and `cwd == str(equipo.DIR)`; with it returning `None` → returns `None`, nothing launched.
- [ ] **Step 2:** run; fails at the first check (`DESBLOQUEOS == []`).
- [ ] **Step 3:** implement.
- [ ] **Step 4:** run `tests\test_agente_bitlocker.py`, `tests\test_agente_veracrypt.py`, `tests\test_bandeja.py`, `tests\test_agente_raiz.py`: pass.
- [ ] **Step 5:** commit ««Desbloquear…» abre la ventana de BitLocker de Windows para una unidad bloqueada».

### Task 6: the tray shows it

**Files:**
- Modify: `ui/bandeja.py` (`_bitlocker()`, `vista()`, `estado()`, module docstring)
- Test: `tests/test_bandeja.py` (append; build the summaries by hand with `{**ag.resumen(), "bitlocker": [...]}` so the file needs no BitLocker fakes)

**Interfaces:**
- Consumes: `resumen["bitlocker"]` (Task 4/5 shape).
- Produces: `bandeja._bitlocker(resumen) -> list[Entrada]`, one per entry: `Entrada(f"{nombre} (bloqueada)", hijos=(hijo,), emblema=MARCA)`, where `hijo` is `Entrada("Desbloquear…", _pide(equipo.PIDE_DESBLOQUEAR, id=uid), defecto=True, icono=I_DESBLOQUEAR)` or, when `desbloqueando`, `Entrada("Desbloqueando: la contraseña la pide Windows", activa=False)`. `vista()` places them right after `_unidades(resumen)`. `estado()` returns `(icons.BLOQUEADO, f"{nombre} bloqueada")` for the first entry, after the host roots' three lock states and before «esperando unidades».

- [ ] **Step 1: failing checks:**

```python
BL = {"id": "k" * 32, "nombre": "Trabajo", "raiz": "E:\\", "desbloqueando": False}
v = bandeja.vista({**ag.resumen(), "bitlocker": [BL]})
d = next(e for e in v.menu if e.texto == "Trabajo (bloqueada)")
c("una unidad bloqueada con BitLocker: su desplegable, con la marca y una sola entrada",
  (d.emblema, [(h.texto, h.pide, h.defecto, h.icono, h.activa) for h in d.hijos]),
  (bandeja.MARCA, [("Desbloquear…", ({"pide": equipo.PIDE_DESBLOQUEAR, "id": "k" * 32},),
                    True, bandeja.I_DESBLOQUEAR, True)]))
```

  plus: with `desbloqueando: True` the child is `("Desbloqueando: la contraseña la pide Windows", (), False)` (text, `pide`, `activa`); the submenu comes after every connected drive's and before «Pausar»; a summary with only that entry (no roots, no drives) gives `bandeja.estado()` `(icons.BLOQUEADO, "Trabajo bloqueada")`; with a locked encrypted root too, the root's phrase wins; `pausado`, a pass in flight and an aviso each still win over it; `bandeja.avisos()` does not mention it; `bandeja.vista(r) == bandeja.vista({**r, "bitlocker": []})` for a summary `r` without the key.
- [ ] **Step 2:** run `tests\test_bandeja.py`; fails with `StopIteration`.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** run `tests\test_bandeja.py`, `tests\test_bandeja_windows.py`, `tests\test_bandeja_linux.py`, `tests\test_agente_bitlocker.py`: pass. Add to `tests\test_agente_bitlocker.py` one end-to-end check: with the real agent in Task 4's locked state, `bandeja.vista(ag.resumen())` has «Trabajo (bloqueada)», and feeding its child's `pide` to `ag.pedir()` plus one turn launches the unlock.
- [ ] **Step 5:** commit «La bandeja enseña la unidad bloqueada con BitLocker y ofrece desbloquearla».

### Task 7: docs, the real-machine list and the whole suite

**Files:**
- Modify: `docs/agents/reference/agent.md` («Files and ownership»: `agente.json` also holds each drive's `volumen`; «Detection»: a paragraph on the locked BitLocker drive), `docs/agents/reference/tray.md` (the submenu and the icon priority), `docs/agents/reference/commands-testing.md` (the `desbloquear [ID]` line; the registry: `agente.desbloquear_bitlocker()`, `bitlocker.volumen_de()` over `_leer_volumen()`, and that the agent asks `cifrada.bitlocker_de()`), `docs/agents/reference/veracrypt.md` only if it describes `common/bitlocker.py`'s functions, `docs/guia/agente-residente.md` (Spanish, for the user: what they will see, and that the first time on a computer the drive must be unlocked by hand), `docs/superpowers/pruebas/2026-09-25-equipo-pendiente-en-real.md` (new section «Una unidad bloqueada con BitLocker», rows B1–B6 = the six checks of the spec's «En real», in the table shape of the other sections).

- [ ] **Step 1:** write the docs. Area docs describe the current contract, not the history.
- [ ] **Step 2:** run `tests\test_reglas_claude.py`, `tests\test_run_all.py`, `tests\test_imports_perezosos.py`, `tests\test_install_agente.py`: pass.
- [ ] **Step 3:** run the whole suite with the device's pinned Tk 9 runtime (extracted into the scratchpad from the installer cache, as `windows-arm64-dev-machine` describes): `<runtime>\python.exe tests\run_all.py -j auto --gui-jobs 1`. Expected last line: `Los N ficheros de test pasan.` Report any failure with its output, and whether it also fails on the base commit.
- [ ] **Step 4:** commit «BitLocker en el agente: documentación y lo que falta ver en un equipo de verdad».
