# The «Servidor…» explorer (`common/rcd.py`, `ui/servidor.py`, `ui/tk_servidor.py`)

Formerly none: a new area. Design: `docs/superpowers/specs/2026-10-27-explorador-servidor-design.md`. The catalogue it browses: `catalogue.md`; the window pattern it follows: `ui.md`.

This doc is a stub that grows with the feature; today it covers `common/rcd.py` (the process and its anti-orphan belts) and `ui/servidor.py` (the decision half).

## The resident `rclone rcd` (`common/rcd.py`)

The explorer talks to ONE `rclone rcd` over HTTP on `127.0.0.1` instead of paying an `rclone lsjson` start-up per folder.

- **Local and authenticated, always.** `--rc-addr 127.0.0.1:<port>` with a port from `puerto_libre()`; never `--rc-no-auth`, never `--rc-web-gui`. The user and password are random per start and travel in the child's **environment** (`RCLONE_RC_USER`/`RCLONE_RC_PASS`), never in argv (any local process can read argv). With them set, every method, `rc/noop` included, answers 401 without auth.
- **stderr goes to a host temp file, never a pipe**: `rcd` logs NOTICE lines continuously and a pipe nobody reads eventually blocks it. The file is the host's temp, never the device. `Rcd.esperar()` reads it when the process dies at start-up: «address already in use» (Windows: «Only one usage of each socket address») is `PuertoOcupado` (the port was free when chosen and taken before `rcd` opened it: the caller retries with another); anything else is `ConfigError` carrying that stderr.
- **`peticion()` bypasses the system proxy** (`ProxyHandler({})`): `HTTP_PROXY` would send loopback traffic to a proxy. An HTTP error status is returned, not raised; only a failure to talk raises `RcdCaido`. `Rcd.llamar()` turns a non-200 into `ErrorRc(mensaje, estado)`: `mensaje` is the JSON `error` field (rclone answers e.g. 404 `{"error": "error in ListJSON: directory not found", …}`), the body text if it is not JSON.
- **`arrancar()` does not wait** and must be called on the Tk thread; `esperar()` polls `rc/noop` every 0.1 s (`ESPERA_ARRANQUE = 10 s`) and is what goes to a thread. A 401 or a refused connection both keep it waiting: only the process dying, or the deadline, ends it.
- **`parar()` never raises**: `core/quit`, then `ESPERA_QUIT = 3 s` (measured against rclone v1.75.2: `core/quit` answers 200 and the process exits ≈1.5 s later), then `kill()`. The process is in `store._HIJOS` from `arrancar()` to `parar()`, so `store.matar_hijos()` also cuts it when the window closes or before the drive is ejected.
- **Indirection points** (tests replace them, no test starts rclone): `rcd.lanzar`, `rcd.peticion`, `rcd.puerto_libre`. `lanzar` builds its `Popen` arguments with the pure `_opciones_popen()` (`cwd = model.APP_DIR`, `stdin`/`stdout` to `DEVNULL`, `CREATE_NO_WINDOW` on Windows, `start_new_session` on POSIX), which is what the tests assert.

### Never an orphan holding the drive

A surviving `rcd` keeps `rclone.conf` and the binary of the **device** open and blocks the eject, so three belts, from most to least immediate:

1. **Orderly close**: `store.apuntar_hijo()`, cut by `store.matar_hijos()` (above).
2. **The window dies abruptly**: Windows, `atar_al_job()` puts the child in a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (ctypes; the handle lives in `_JOBS` and is never closed by us, so the OS closes it when the window process dies; a `False` return means no belt, it still starts). Linux, `_opciones_popen()` adds `preexec_fn=_morir_con_el_padre` (`prctl(PR_SET_PDEATHSIG, SIGKILL)`); macOS has no such call, so no `preexec_fn`. The `prctl` pointer is resolved **in the parent** (`_resolver_prctl()`, module global `_PRCTL`) so the child between `fork` and `exec` only calls it. **`PDEATHSIG` fires when the *thread* that forked dies, not the process**: `arrancar()` must run on the Tk (main) thread (verified against rclone v1.75.2: from a thread that ends, the child dies at once; from the main thread it lives), and only `esperar()` goes to a worker.
3. **One survives anyway**: `arrancar()` writes `state/rcd.json` (`fichero_estado()`, a function because tests move `STATE_DIR`) with `{"pid", "creado"}` (`store.creado()`), **never the password**. The next `arrancar()` calls `limpiar_huerfano()` first: it kills the tree (`store.matar_arbol()`, which needs the `start_new_session` of `_opciones_popen`) only if the pid is alive **and** its creation time matches within 1 s (otherwise another process inherited the number); an unknown creation time is not killed either. The file is always deleted; the function never raises. `parar()` deletes the file only if it still names its own pid. `--doctor` does not touch it.

Order in `arrancar()`: `limpiar_huerfano()` → `lanzar()` → `atar_al_job()` (Windows) → write `rcd.json` → `store.apuntar_hijo()`. A failure of `puerto_libre()` is a `ConfigError`. The tests force Windows by replacing `rcd.os` and fake `atar_al_job`; the real Job Object call only runs on Windows (`(saltado)` elsewhere), and `PDEATHSIG` is covered by asserting `_opciones_popen()`, not by starting a process.

## The decision half (`ui/servidor.py`)

No Tk, no disk, no network; `tk_servidor` only draws what it returns.

- **Listings**: `params_listado()` always sends `fs = "<remote>:/"` and `remote = ruta.lstrip("/")` as a JSON string (never URL-encoded; the root is `""`). `entradas_de()` keeps folders first, then `str.lower` order, skips items of the wrong shape, trims `ModTime` fractions to microseconds. `Entrada.modo/uid/gid` stay `None` until the permissions work fills them.
- **Last request wins**: `Navegacion.pedir()` numbers requests; `recibir()`/`fallo()` ignore any that is not the last one. `remote`, `ruta` and `entradas` change together, only in `recibir()`. `pedir()` always asks the shown `remote`; only `cambiar_remote()` asks another, so a failed or superseded change never sends a folder of the old table to the new remote. A `ModTime` before 1970 (rclone's `0001-01-01T00:00:00Z` for «unknown») is `fecha = None`, shown as «—».
- **Pairs**: `marca()` (exact path) and `dentro_de()` (path or ancestor at a `/` boundary) look only at pairs of the same `remote_name`.
- **Errors**: `frase_error()` checks `RcdCaido` first (its text quotes a connection error to `rcd`, which is not a server without network), then permission (`ErrorRc.estado == 403` or text), no network, not found (404 or text), timeout. `es_sin_red()` is what decides «Reintentar» at open.
