# «Servidor…» (piece 1: read-only remote explorer) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a «Servidor…» button in the main window opens a one-pane, read-only explorer of the whole rclone remote (folders and files, size, date, permissions, «⇄ Pareja» marks, «Sin acceso» lock), talking to a resident `rclone rcd` that can never be left orphaned holding the device.

**Architecture:** `common/rcd.py` owns the `rclone rcd` process (start on the Tk thread, HTTP over `127.0.0.1` with random credentials, three anti-orphan belts). `ui/servidor.py` is the pure decision half (parse `operations/list`, navigation with last-request-wins, remotes, pair overlay, error phrases, permissions). `ui/tk_servidor.py` only draws, on the `tk_fleet` pattern (`modal` + `Sondeo` + `Indicador` + `Tabla`). The main window gets one button.

**Tech Stack:** Python 3.11+ stdlib only (`subprocess`, `urllib.request`, `secrets`, `ctypes`, `json`, `socket`), Tk 9 via `ui/tk.py`, plain-script tests (`tests/_harness.Checks`, `sandbox()`, `tmpdir()`).

**Spec:** `docs/superpowers/specs/2026-10-27-explorador-servidor-design.md`

## Global Constraints

- Stdlib only; must import on Python 3.11. `import tkinter` only inside functions. `common/rcd.py` and `ui/servidor.py` import no Tk and touch no Tk object.
- Comments, docstrings (Google style), user-visible text in **Spanish**; `docs/agents/` in English. Read `docs/agents/code-writing-conventions.md` before writing Python.
- `tk_servidor` writes no hex colour and no bare integer distance: `theme`/`icons`, `theme.medida()`, `theme.E*`.
- Nothing in this plan writes to the remote. The only rclone methods called are `rc/noop`, `operations/list`, `operations/fsinfo`, `operations/stat`, `core/quit`.
- rclone runs with `cwd = model.APP_DIR` and `--config model.RCLONE_CONF`; the network flags are `catalog.NET_FLAGS`, imported, never copied.
- Credentials: `secrets.token_urlsafe(32)` each, passed only in the environment (`RCLONE_RC_USER`, `RCLONE_RC_PASS`), never in `argv`, never on disk. Listen only on `127.0.0.1`. Never pass `--rc-no-auth` or `--rc-web-gui`.
- Every listing uses `fs = "<remote>:/"` (the same string every time, so rclone reuses one cached backend and one SSH connection) and `remote = ruta.lstrip("/")`.
- Permissions are requested (`opt.metadata = True`) only when `operations/fsinfo` says `Features.ReadMetadata` is true **and** the remote's `type` in `rclone.conf` is in `LEE_PERMISOS_EN_EL_LISTADO = frozenset({"sftp", "local"})`.
- Tests never start rclone nor touch the network: they replace `rcd.lanzar`, `rcd.peticion`, `rcd.puerto_libre`, `rcd.arrancar` (module-level functions). A Tk test goes in `GUI` in `tests/run_all.py`.
- Every new source and test goes in the `paths` of `.claude/rules/servidor.md` (`tests/test_reglas_claude.py`).
- Verify each task with `python tests/run_all.py --cambios -j auto` (no windows locally; CI runs them). One commit per task, Spanish subject, footer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Exact copy:
  - window title `Servidor`; main-window button `Servidor…`, icon `nas`;
  - columns `Nombre`, `Tamaño`, `Modificado`, `Permisos`; empty table `Esta carpeta está vacía.`; footer `1 elemento` / `{n} elementos`;
  - indicator: `Conectando con el servidor…` · `Leyendo {ruta}…` · `Estás dentro de la pareja «{nombre}».` · `Este dispositivo no tiene conexión con ningún servidor.`;
  - errors: `No tienes permiso para ver esta carpeta.` · `Esa carpeta ya no existe en el servidor.` · `El servidor no ha contestado a tiempo.` · `Se ha perdido la conexión con rclone.` · `No hay conexión con el servidor.` · otherwise `rclone dice: {mensaje}`;
  - buttons `↑` (icon `arriba`), `Releer` (icon `reload`), `Reconectar` (after a lost `rcd`), `Reintentar` (no network at open);
  - pair mark appended to the name cell: `  ⇄ {nombre}`; locked folder: icon `candado`, row tone `apagado`; permissions cell `—` when unknown, else three octal digits (`755`).

## Review Focus

1. **A system or environment HTTP proxy** (`HTTP_PROXY`, Windows proxy settings) would capture the calls to `127.0.0.1` and every listing would fail: `peticion()` must bypass every proxy. Test in Task 1.
2. **`rcd`'s stderr on an unread pipe** fills its buffer during a long session and freezes rclone: stderr goes to a host temp file, read only when the start fails. Test in Task 1.
3. **Folder names with spaces, accents, `%`, `#`, `?`** and the root `/` must reach rclone verbatim (`remote` is a JSON string, never URL-encoded; `/` → `""`). Test in Task 3.
4. **A pair path as a string prefix** (`/datos/notas2` is not inside `/datos/notas`; another remote's pair with the same path does not mark). Test in Task 3.
5. **Closing the window while starting or while a listing is in flight**: `parar()` still runs, the late answer paints nothing, no Tk callback error. Test in Task 5.

---

### Task 1: `common/rcd.py`, the resident `rclone rcd` (start, call, stop) + the area's doc and rule

**Files:**
- Create: `common/rcd.py`, `tests/test_rcd.py`
- Create (skill `new-area-doc`): `docs/agents/reference/servidor.md`, `.claude/rules/servidor.md`, its row in the `AGENTS.md` table («`servidor.md` | `rcd.py`, `servidor.py`, `tk_servidor.py`: the «Servidor…» explorer and its resident `rclone rcd`»). The rule's `paths` list, now, every file this plan creates: `common/rcd.py`, `ui/servidor.py`, `ui/tk_servidor.py`, `docs/guia/servidor.md`, `tests/test_rcd.py`, `tests/test_servidor.py`, `tests/test_tk_servidor.py`.

**Interfaces:**
- Produces:
  - `class PuertoOcupado(ConfigError)`; `class RcdCaido(Exception)`; `class ErrorRc(Exception)` with attributes `mensaje: str`, `estado: int`.
  - `ESPERA_ARRANQUE = 10.0`, `ESPERA_QUIT = 2.0`, `TIMEOUT_PETICION = 60.0` (seconds).
  - `puerto_libre() -> int`: bind a socket to `("127.0.0.1", 0)`, read the port, close it.
  - `lanzar(orden: list[str], entorno: dict[str, str], stderr) -> subprocess.Popen`: `cwd=str(model.APP_DIR)`, `stdin=DEVNULL`, `stdout=DEVNULL`, `stderr=<the file given>`, `env=entorno`; `creationflags=model.CREATE_NO_WINDOW` on Windows; `start_new_session=True` on POSIX.
  - `peticion(url: str, cuerpo: bytes, cabeceras: dict[str, str], timeout: float) -> tuple[int, str]`: POST through `urllib.request.build_opener(urllib.request.ProxyHandler({}))`; an `HTTPError` returns `(e.code, body)`; `URLError`/`OSError` raise `RcdCaido`.
  - `class Rcd` with `proceso: subprocess.Popen`, `url: str` (`http://127.0.0.1:<puerto>/`), `vivo: bool` (property: `proceso.poll() is None`), `esperar(tope: float = ESPERA_ARRANQUE) -> None`, `llamar(metodo: str, params: dict | None = None) -> dict`, `parar() -> None`.
  - `arrancar() -> Rcd`: does **not** wait; must be called on the Tk thread (Task 2's reason).
- Consumes: `catalog.NET_FLAGS`, `catalog._binary()` (rclone or `ConfigError`), `store.apuntar_hijo()`/`soltar_hijo()`, `model.APP_DIR`, `model.RCLONE_CONF`, `model.CREATE_NO_WINDOW`.

- [ ] **Step 1: Scaffold the area doc and rule** with the `new-area-doc` skill (paths above). The doc can be a stub here; Task 7 fills it. Run `python tests/test_reglas_claude.py` → passes.

- [ ] **Step 2: Write the failing tests** in `tests/test_rcd.py` (replace `rcd.lanzar`, `rcd.peticion`, `rcd.puerto_libre` with fakes that record their arguments; `sandbox()` for `STATE_DIR`):

```python
r = rcd.arrancar()
orden, entorno, _ = lanzado[-1]
c("se lanza rcd con el config del dispositivo", orden[1:4], ["rcd", "--config", str(model.RCLONE_CONF)])
c("escucha solo en 127.0.0.1", "--rc-addr" in orden and orden[orden.index("--rc-addr") + 1], "127.0.0.1:5599")
c("lleva los NET_FLAGS del catálogo", all(f in orden for f in catalog.NET_FLAGS), True)
c("ni sin autenticación ni web", {"--rc-no-auth", "--rc-web-gui"} & set(orden), set())
c("usuario y contraseña en el entorno", len(entorno["RCLONE_RC_USER"]) >= 32 and len(entorno["RCLONE_RC_PASS"]) >= 32, True)
c("y nunca en argv", any(entorno["RCLONE_RC_PASS"] in a for a in orden), False)
c("stderr no es una tubería que nadie lee", lanzado[-1][2] is not subprocess.PIPE, True)   # Review Focus 2
c("queda apuntado para matar_hijos()", r.proceso in store._HIJOS, True)
# esperar(): rc/noop falla dos veces (RcdCaido) y luego contesta 200 → vuelve sin lanzar
# esperar(): el proceso sale antes con «address already in use» en su stderr → PuertoOcupado
# esperar(): el proceso sale con otro stderr → ConfigError cuyo texto lleva ese stderr
# esperar(): nunca contesta → ConfigError al pasar el tope (tope=0.2 en el test)
# llamar(): manda JSON, cabecera Authorization Basic con el usuario y la contraseña; 200 → dict
# llamar(): 500 con {"error": "directory not found"} → ErrorRc(mensaje="directory not found", estado=500)
# parar(): llama core/quit; un proceso que sigue vivo pasados ESPERA_QUIT recibe kill(); sale de store._HIJOS; no lanza aunque core/quit lance RcdCaido
```

Plus, against the **real** `peticion` (Review Focus 1): start `http.server.HTTPServer(("127.0.0.1", 0), handler)` in a thread, set `os.environ["HTTP_PROXY"] = os.environ["http_proxy"] = "http://127.0.0.1:9"`, and check `rcd.peticion(url, b"{}", {}, 5)` returns `(200, '{"ok": true}')`.

- [ ] **Step 3: Run** `python tests/test_rcd.py` → FAIL (`No module named 'common.rcd'`).

- [ ] **Step 4: Implement `common/rcd.py`.**
  - `arrancar()`: `orden = [catalog._binary(), "rcd", "--config", str(model.RCLONE_CONF), "--rc-addr", f"127.0.0.1:{puerto_libre()}", *catalog.NET_FLAGS]`; `entorno = {**os.environ, "RCLONE_RC_USER": …, "RCLONE_RC_PASS": …}`; stderr is `tempfile.TemporaryFile()` (host temp, never the device); `store.apuntar_hijo(proceso)`.
  - `esperar()`: poll `rc/noop` every 0.1 s; when the process has exited, read its stderr file and raise `PuertoOcupado` if it contains `address already in use` or `Only one usage of each socket address` (case-insensitive), else `ConfigError(f"rclone no ha podido arrancar:\n\n{stderr}")`.
  - `llamar()`: body `json.dumps(params or {})`, headers `Content-Type: application/json` and `Authorization: Basic …`; non-200 → `ErrorRc(json["error"] or the text, estado)`.
  - `parar()`: `core/quit` under `try`, wait `ESPERA_QUIT`, then `proceso.kill()`, `store.soltar_hijo()`; never raises.

- [ ] **Step 5: Run** `python tests/test_rcd.py` and `python tests/run_all.py --cambios -j auto` → PASS.

- [ ] **Step 6: Commit** `git commit -m "Servidor: el rclone rcd vivo, con credenciales en el entorno y solo en 127.0.0.1"`.

---

### Task 2: the anti-orphan belts (Job Object, `PDEATHSIG`, `state/rcd.json`)

**Files:**
- Modify: `common/rcd.py`
- Test: `tests/test_rcd.py`

**Interfaces:**
- Produces:
  - `fichero_estado() -> Path`: `model.STATE_DIR / "rcd.json"` (a function: tests move `STATE_DIR` at runtime).
  - `limpiar_huerfano() -> int | None`: reads `rcd.json`; if `store.pid_alive(pid)` and `abs(store.creado(pid) - creado) < 1.0`, calls `store.matar_arbol(pid)` and returns the pid; deletes the file in every case; never raises.
  - `atar_al_job(proceso: subprocess.Popen) -> bool` (Windows; module-level, replaceable).
  - `_morir_con_el_padre() -> None` (POSIX `preexec_fn`).
- Consumes: Task 1's `arrancar()`, `lanzar()`, `Rcd.parar()`; `store.pid_alive`, `store.creado`, `store.matar_arbol`, `store.write_json`, `store.read_json`, `store.borrar`.

- [ ] **Step 1: Write the failing tests:**

```python
# huérfano: rcd.json con un pid vivo y la misma hora de creación → se mata y se borra el fichero
c("un rcd colgado de antes se mata", rcd.limpiar_huerfano(), 4242); c("con matar_arbol", matados, [4242])
# misma pid, otra hora de creación (el número lo heredó otro proceso) → no se mata, el fichero se borra
# pid muerto → no se mata; fichero ilegible → None, sin lanzar
# arrancar() llama a limpiar_huerfano() antes de lanzar, y escribe rcd.json con {"pid", "creado"}
c("rcd.json no guarda la contraseña", entorno["RCLONE_RC_PASS"] in rcd.fichero_estado().read_text(), False)
# parar() borra rcd.json
# Windows (forzando IS_WIN / os.name con el patrón de los demás tests): arrancar() llama a atar_al_job(proceso); si devuelve False, arranca igual
# POSIX: lanzar() recibe preexec_fn=_morir_con_el_padre; en Windows no lleva preexec_fn
# el Popen se hace en el hilo que llama a arrancar(): threading.get_ident() del lanzar falso == el del test
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement.**
  - `_morir_con_el_padre`: calls a `prctl` function resolved **in the parent before the `Popen`** (`ctypes.CDLL(None, use_errno=True).prctl`, kept in a module global), as `prctl(1, signal.SIGKILL)` (`PR_SET_PDEATHSIG = 1`). The child only calls an already-resolved pointer: no import, no allocation after `fork`. The docstring says the signal fires when the **thread** that forked dies, so `arrancar()` must run on the Tk thread.
  - `atar_al_job`: `CreateJobObjectW(None, None)`; `SetInformationJobObject(job, 9, JOBOBJECT_EXTENDED_LIMIT_INFORMATION with BasicLimitInformation.LimitFlags = 0x2000)` (`JobObjectExtendedLimitInformation`, `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`); `AssignProcessToJobObject(job, int(proceso._handle))`. Keep the job handle in a module list for the life of the process (never closed by us). Any failure returns `False`.
  - `arrancar()` order: `limpiar_huerfano()` → `lanzar()` → `atar_al_job()` on Windows → `store.write_json(fichero_estado(), {"pid": …, "creado": store.creado(pid)})` → `apuntar_hijo()`.

- [ ] **Step 4: Run** `python tests/test_rcd.py` → PASS (the side for the other OS prints `(saltado) …` or is forced like in `tests/test_hijos.py`).

- [ ] **Step 5: Commit** `git commit -m "Servidor: el rcd muere con la ventana aunque esta caiga de golpe"`.

---

### Task 3: `ui/servidor.py`: entries, navigation, remotes, pairs, errors

**Files:**
- Create: `ui/servidor.py`, `tests/test_servidor.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Entrada`: `nombre: str`, `es_carpeta: bool`, `tamano: int | None`, `fecha: datetime | None`, `modo: int | None = None`, `uid: int | None = None`, `gid: int | None = None` (Task 4 fills the last three).
  - `entradas_de(respuesta: dict) -> tuple[Entrada, ...]`: from `respuesta["list"]` (`Name`, `IsDir`, `Size`, `ModTime` as in `lsjson`); folders first, then `str.lower` order; an item missing `Name` or of the wrong shape is skipped; `Size < 0` or a folder → `tamano=None`.
  - `remotes_de(texto_conf: str, por_defecto: str | None, device_remote: str | None) -> dict[str, str]`: name → `type`, from `pairing.parse_rclone_conf()`, without `type` `combine`/`alias` and without `device_remote`; `por_defecto` first if present, the rest by name.
  - `params_listado(remote: str, ruta: str, permisos: bool) -> dict`: `{"fs": f"{remote}:/", "remote": normalizar(ruta).lstrip("/"), "opt": {"noMimeType": True}}`, plus `"metadata": True` in `opt` when `permisos`.
  - `@dataclass(frozen=True) class Peticion`: `numero: int`, `remote: str`, `ruta: str`.
  - `class Navegacion(remote: str)`: `remote`, `ruta` (`"/"`), `entradas` (`()`), `sin_acceso: set[tuple[str, str]]`; `pedir(ruta: str) -> Peticion` (number +1 each time); `recibir(p: Peticion, entradas) -> bool` (False and no change unless `p` is the last asked; on True sets `ruta` and `entradas`); `fallo(p: Peticion, error: Exception) -> str | None` (None if stale; else the phrase, and if `es_de_permiso(error)` adds `(p.remote, p.ruta)` to `sin_acceso`); `cambiar_remote(nombre: str) -> Peticion` (asks `/`); `hijo(nombre: str) -> str` and `padre() -> str` (via `remote_picker.entrar`/`subir`).
  - `parejas_en(config: Config, remote: str) -> dict[str, str]`: normalized `remote_path` → pair name, only pairs whose `remote_name == remote`.
  - `marca(config, remote, ruta: str) -> str | None`; `dentro_de(config, remote, ruta: str) -> str | None`: the pair whose path equals `ruta` or is an ancestor at a `/` boundary.
  - `es_de_permiso(error: Exception) -> bool`; `frase_error(error: Exception) -> str` (copy in Global Constraints; checked in this order: permission, no network (`dial tcp`, `connection refused`, `no route to host`, `no such host`, `network is unreachable`), not found, timeout, `RcdCaido`, the rest); `tamano_legible(n: int | None) -> str`; `fecha_legible(fecha: datetime | None) -> str`; `cuantos(n: int) -> str`.
- Consumes: `remote_picker.normalizar/entrar/subir`, `pairing.parse_rclone_conf`, `model.Config`/`Pair.remote_name`/`Pair.remote_path`, Task 1's `ErrorRc`, `RcdCaido`.

- [ ] **Step 1: Write the failing tests** in `tests/test_servidor.py`:

```python
LISTA = {"list": [
  {"Name": "zeta.txt", "IsDir": False, "Size": 4096, "ModTime": "2026-10-01T10:00:00.000000000+02:00"},
  {"Name": "Fotos de verano", "IsDir": True, "Size": -1, "ModTime": "2026-03-12T09:00:00Z"},
  {"Name": "año 100% #1?", "IsDir": True, "Size": -1, "ModTime": "2026-01-01T00:00:00Z"},
  {"IsDir": True}, "no soy un objeto"]}
c("carpetas primero, luego por nombre", [e.nombre for e in servidor.entradas_de(LISTA)], ["año 100% #1?", "Fotos de verano", "zeta.txt"])
c("una carpeta no tiene tamaño", servidor.entradas_de(LISTA)[0].tamano, None)
c("la raíz se pide vacía", servidor.params_listado("nas", "/", False), {"fs": "nas:/", "remote": "", "opt": {"noMimeType": True}})
c("un nombre raro llega tal cual", servidor.params_listado("nas", "/año 100% #1?", False)["remote"], "año 100% #1?")   # Review Focus 3
c("siempre el mismo fs", {servidor.params_listado("nas", r, True)["fs"] for r in ("/", "/a", "/a/b")}, {"nas:/"})
c("con permisos lleva metadata", servidor.params_listado("nas", "/a", True)["opt"], {"noMimeType": True, "metadata": True})
CONF = "[nas]\ntype = sftp\n[pen]\ntype = combine\n[alias1]\ntype = alias\n[b2]\ntype = b2\n[otro]\ntype = sftp\n"
c("los internos no salen y el de defaults va primero", list(servidor.remotes_de(CONF, "otro", "pen")), ["otro", "b2", "nas"])
c("con su tipo", servidor.remotes_de(CONF, None, None)["nas"], "sftp")
# Navegacion: pedir A, pedir B, recibir(A) → False y la ruta sigue "/"; recibir(B) → True y ruta "/b"
# fallo(B, ErrorRc("permission denied", 500)) → "No tienes permiso para ver esta carpeta." y ("nas", "/b") en sin_acceso
# fallo de una petición vieja → None y sin_acceso sin cambios
# frase_error: "dial tcp 10.0.0.2:22: connect: connection refused", "no route to host", "no such host",
#   "network is unreachable" → "No hay conexión con el servidor."
# frase_error: "SSH_FX_PERMISSION_DENIED" y un 403 → permiso; "directory not found" → "Esa carpeta ya no existe en el servidor."; "i/o timeout" → "El servidor no ha contestado a tiempo."; RcdCaido() → "Se ha perdido la conexión con rclone."; "algo raro" → "rclone dice: algo raro"
# pares (mkcfg con parejas "Notas" en nas:/datos/notas y "Otra" en b2:/datos/notas):
c("marca la carpeta de la pareja en su remote", servidor.marca(cfg, "nas", "/datos/notas"), "Notas")
c("no la de otro remote", servidor.marca(cfg, "b2", "/datos/fotos"), None)
c("dentro de la pareja", servidor.dentro_de(cfg, "nas", "/datos/notas/2026"), "Notas")
c("un prefijo de texto no es estar dentro", servidor.dentro_de(cfg, "nas", "/datos/notas2"), None)   # Review Focus 4
c("tamaños", [servidor.tamano_legible(n) for n in (None, 0, 4096, 1572864, 52428800)], ["—", "0 B", "4 KB", "1,5 MB", "50 MB"])
c("cuántos", [servidor.cuantos(n) for n in (0, 1, 3)], ["0 elementos", "1 elemento", "3 elementos"])
# fecha_legible: hora local "dd/mm/aaaa hh:mm"; None → "—"
```

- [ ] **Step 2: Run** `python tests/test_servidor.py` → FAIL.

- [ ] **Step 3: Implement `ui/servidor.py`.** `tamano_legible`: base 1024, units `B KB MB GB TB`, one decimal with a comma below 10 (dropping `,0`), integer from 10 up. `ModTime` through `datetime.fromisoformat` after trimming the fraction to 6 digits; unreadable → `None`.

- [ ] **Step 4: Run** → PASS; `python tests/run_all.py --cambios -j auto` → PASS.

- [ ] **Step 5: Commit** `git commit -m "Servidor: qué se enseña y cómo se navega, sin Tk"`.

---

### Task 4: permissions: when to ask, the column, the early lock

**Files:**
- Modify: `ui/servidor.py`
- Test: `tests/test_servidor.py`

**Interfaces:**
- Produces:
  - `LEE_PERMISOS_EN_EL_LISTADO = frozenset({"sftp", "local"})`.
  - `pide_permisos(fsinfo: dict, tipo: str) -> bool`: `fsinfo.get("Features", {}).get("ReadMetadata") is True and tipo in LEE_PERMISOS_EN_EL_LISTADO`.
  - `entradas_de()` now also reads `Metadata.mode` (an octal string, `"40755"`, matched by `[0-7]{1,7}`), `Metadata.uid`, `Metadata.gid` (decimal strings); anything else → `None`, never an exception.
  - `texto_permisos(modo: int | None) -> str`: `"—"` or `f"{modo & 0o777:03o}"`.
  - `mi_uid_de(stat: dict | None) -> int | None`: `stat["item"]["Metadata"]["uid"]` as an int, or `None`.
  - `sin_acceso_previo(e: Entrada, mi_uid: int | None) -> bool`: the spec's table (below).
- Consumes: Task 3's `Entrada`, `entradas_de`.

- [ ] **Step 1: Write the failing tests:**

```python
c("SFTP de hoy: ReadMetadata falso → no", servidor.pide_permisos({"Features": {"ReadMetadata": False}}, "sftp"), False)
c("SFTP con el PR → sí", servidor.pide_permisos({"Features": {"ReadMetadata": True}}, "sftp"), True)
c("S3 lee metadatos por objeto → no", servidor.pide_permisos({"Features": {"ReadMetadata": True}}, "s3"), False)
c("crypt sobre SFTP → no", servidor.pide_permisos({"Features": {"ReadMetadata": True}}, "crypt"), False)
c("fsinfo raro → no", servidor.pide_permisos({}, "sftp"), False)
META = lambda m: {"list": [{"Name": "d", "IsDir": True, "Size": -1, "ModTime": "2026-01-01T00:00:00Z", "Metadata": m}]}
c("mode del formato del PR", servidor.entradas_de(META({"mode": "40755", "uid": "1000", "gid": "100"}))[0].modo, 0o40755)
c("modos raros dan None", [servidor.entradas_de(META({"mode": v}))[0].modo for v in ("rwxr-xr-x", "0x1ed", "", "9")], [None] * 4)
c("la columna", [servidor.texto_permisos(m) for m in (None, 0o40755, 0o100600, 0o40700)], ["—", "755", "600", "700"])
# sin_acceso_previo (carpeta, mi_uid=1000):
#   dueño 1000, 0o40300 → True  ·  dueño 1000, 0o40700 → False
#   dueño 0, 0o40700 → True (ni grupo ni otros)  ·  dueño 0, 0o40750 → False (depende del grupo: no se marca)
#   dueño 0, 0o40705 → False (otros pueden)  ·  mi_uid=0 → siempre False  ·  mi_uid None → False
#   un archivo → False  ·  modo None → False
c("mi uid del stat", servidor.mi_uid_de({"item": {"Metadata": {"uid": "1000"}}}), 1000)
c("sin metadatos, None", servidor.mi_uid_de({"item": {}}), None)
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (owner bits `0o500`, group `0o050`, other `0o005`; entering needs `r` and `x`). **Step 4: Run** → PASS.

- [ ] **Step 5: Commit** `git commit -m "Servidor: la columna de permisos, en «—» hasta que rclone los dé en SFTP"`.

---

### Task 5: `ui/tk_servidor.py`, the window

**Files:**
- Create: `ui/tk_servidor.py`, `tests/test_tk_servidor.py`
- Modify: `tests/run_all.py` (add `"test_tk_servidor.py"` to `GUI`)

**Interfaces:**
- Produces: `open_dialog(parent, config: Config) -> None`, and the module-level name `mostrar` (imported from `ui.tk`, the one tests replace).
- Consumes: Tasks 1–4; `config_file.load_raw()` (a `ConfigError` → `{}`), `remote_picker.remote_de(raw)`, `config.device_remote`, `model.RCLONE_CONF`; `tk.modal`, `tk.cuerpo_visible`, `tk.Sondeo`, `tk.Indicador`, `tk.Tabla` with `CeldaIcono`/`FilaTabla`; `segundo_plano.lanzar` with `functools.partial` (no Tk object inside).

- [ ] **Step 1: Write the failing test**, on the `tests/test_tk_flota_vista.py` pattern (skip without a display; `segundo_plano.lanzar = segundo_plano.en_el_acto`; replace `tk_servidor.mostrar`). A `RcdFalso` with `vivo`, `esperar()`, `parar()` (counts calls) and `llamar(metodo, params)` answering from a dict keyed by `(metodo, params.get("remote"))`; `rcd.arrancar` replaced by a function that returns it and counts calls. `sandbox()` writes an `rclone.conf` with `[nas] type = sftp`.

```python
# abrir: la tabla tiene las filas de "/" y la columna Permisos dice "—" en todas (fsinfo con ReadMetadata False)
c("se pidió fsinfo y no metadata", [p["opt"] for m, p in falso.llamadas if m == "operations/list"], [{"noMimeType": True}])
# doble clic en la carpeta "datos" → operations/list con remote "datos"; la ruta de arriba dice "/datos"
# la carpeta de la pareja enseña "  ⇄ Notas" en su celda de nombre
# dentro de la pareja: el indicador dice "Estás dentro de la pareja «Notas»."
# un ErrorRc("permission denied") al entrar en "privado": la tabla sigue con las filas de antes, el indicador dice
#   "No tienes permiso para ver esta carpeta." y la fila "privado" lleva el icono candado y tono apagado
# un RcdCaido: sale «Reconectar»; pulsarlo llama otra vez a rcd.arrancar() y repite la última petición
# arrancar() que lanza PuertoOcupado una vez: se reintenta una sola vez; dos veces → el indicador dice el error
# la primera petición al abrir falla con "connection refused": el indicador dice "No hay conexión con el servidor."
#   y sale «Reintentar»; pulsarlo repite la petición de apertura (sin relanzar rcd si sigue vivo)
# sin remotes en rclone.conf: el indicador dice "Este dispositivo no tiene conexión con ningún servidor." y no se arranca rcd
# Review Focus 5: con segundo_plano.lanzar de verdad y un llamar() que espera a un Event, cerrar el diálogo antes de
#   soltar el Event → parar() llamado una vez, ninguna excepción en report_callback_exception
# con fsinfo ReadMetadata True y tipo sftp: el listado lleva metadata, la columna enseña "755", y una carpeta
#   0o40700 de otro dueño sale con candado antes de entrar
```

- [ ] **Step 2: Run** `python tests/test_tk_servidor.py` (by name it opens windows locally) → FAIL.

- [ ] **Step 3: Implement `open_dialog`.**
  - Read `rclone.conf` and `raw` on the Tk thread (small local files); `remotes_de(...)` empty → only the indicator line, no `rcd`.
  - `rcd.arrancar()` on the Tk thread; then one `Encargo` that runs `esperar()`, `operations/fsinfo` (`{"fs": f"{remote}:"}`), `operations/stat` for `mi_uid` only if `pide_permisos`, and the first `operations/list`. `PuertoOcupado` → `arrancar()` again **on the Tk thread**, once.
  - Each later listing: `nav.pedir()` → `Encargo(partial(_listar, rcd, params))` → `Sondeo.esperar` → `nav.recibir()`/`nav.fallo()` → repaint. The `Indicador` says `Leyendo {ruta}…` while waiting.
  - Bindings on the table's canvas (`tabla.marco`): `<Double-1>` and `<Return>` enter the chosen folder, `<BackSpace>` goes up. `↑` and `Releer` in the bar; the remote `ttk.Combobox` (`state="readonly"`) calls `cambiar_remote`. The path is a plain label.
  - Closing (`WM_DELETE_WINDOW` and the dialog's `<Destroy>`): `segundo_plano.lanzar(partial(r.parar))` once (a flag guards against both firing).

- [ ] **Step 4: Run** `python tests/test_tk_servidor.py` → PASS; `python tests/run_all.py --cambios -j auto` → PASS (it skips the window test; CI runs it).

- [ ] **Step 5: Commit** `git commit -m "Servidor: la ventana que recorre el remoto"`.

---

### Task 6: the «Servidor…» button in the main window

**Files:**
- Modify: `ui/instantanea.py` (field + reader), `ui/principal.py` (`Estado.servidor`, `controles()["servidor"]`), `ui/tk_principal.py` (`Acciones.servidor`, the button, `controles_tk()`), `ui/tk.py` (`abrir_servidor()`, `Acciones(servidor=…)`, `"ui.tk_servidor"` in `PRECARGA`)
- Test: `tests/test_principal.py`, and whatever `--cambios` selects (`test_tk_principal*.py`, `test_imports_perezosos.py` run in CI)

**Interfaces:**
- Produces: `Instantanea.remotes_servidor: tuple[str, ...] = ()` (read in `instantanea.leer()` under its own `try` as `tuple(servidor.remotes_de(model.RCLONE_CONF.read_text(encoding="utf-8"), None, config.device_remote))`; a missing file → `()`, no entry in `fallos`); `Estado.servidor: bool` (`bool(inst and inst.remotes_servidor)`); `controles(e)["servidor"] == Control(True, libre and e.servidor)`; `VentanaPrincipal.abrir_servidor() -> None` calling `tk_servidor.open_dialog(self.root, self.config)`.
- Consumes: Task 3's `remotes_de`, Task 5's `open_dialog`.

- [ ] **Step 1: Write the failing rows** in `tests/test_principal.py`: without a reading → `servidor` visible and off; reading with remotes and no pass → on; during a pass (`en_curso`) → off; reading with `remotes_servidor=()` → off.

- [ ] **Step 2: Run** `python tests/test_principal.py` → FAIL. **Step 3: Implement.** The button goes in the `pantallas` frame, column 1, `sticky="w"`, `padx=(theme.E3, 0)`, `Quiet.TButton`, `theme.boton_icono(…, "nas", theme.ACENTO, theme.PAPEL)`. **Step 4: Run** `python tests/run_all.py --cambios -j auto` → PASS.

- [ ] **Step 5: Commit** `git commit -m "Servidor: el botón «Servidor…» de la ventana principal"`.

---

### Task 7: documentation and real-machine checks

**Files:**
- Modify: `docs/agents/reference/servidor.md` (fill it), `docs/agents/reference/commands-testing.md` (indirection registry: `rcd.lanzar`, `rcd.peticion`, `rcd.puerto_libre`, `rcd.arrancar`, `rcd.atar_al_job`), `docs/superpowers/specs/2026-10-27-explorador-servidor-design.md` (status line: «construido»)
- Create: `docs/guia/servidor.md` (for the device's user, Spanish, short: «Ver lo que hay en el servidor»), `docs/superpowers/pruebas/2026-10-27-servidor-pendiente-en-real.md` (skill `real-machine-tests` for its shape)

- [ ] **Step 1: `servidor.md`** in English: the three files, the `rcd` lifecycle and its three belts (with the `PDEATHSIG`-per-thread trap), the fixed `fs` rule, the proxy bypass, the permissions rule (`ReadMetadata` + `type`, why not S3, what to check when `RCLONE_VERSION` moves past rclone/rclone#9631), and what pieces 2 and 3 will add.
- [ ] **Step 2: The pending real-machine rows**, one per line: kill the window by force → `rcd` dies (Windows, Linux); eject after closing the explorer; another program holding the chosen port; a real SFTP with a folder without permission (lock after failing); `opt.metadata` against SFTP v1.75.2 neither breaks nor slows a listing; several folders use **one** SSH login (`sshd` log) and the time per click versus «Examinar…»; `operations/stat` of the root gives `uid` once rclone ships the PR.
- [ ] **Step 3: Run** `python tests/test_reglas_claude.py` and `python tests/run_all.py --cambios -j auto` → PASS.
- [ ] **Step 4: Commit** `git commit -m "Servidor: su documentación y lo que falta probar en una máquina real"`.
