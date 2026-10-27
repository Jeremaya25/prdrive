# The «Servidor…» explorer (`common/rcd.py`, `ui/servidor.py`, `ui/tk_servidor.py`)

Formerly none: a new area. Design: `docs/superpowers/specs/2026-10-27-explorador-servidor-design.md`. The catalogue it browses: `catalogue.md`; the window pattern it follows: `ui.md`.

This doc is a stub that grows with the feature; today it covers only `common/rcd.py`.

## The resident `rclone rcd` (`common/rcd.py`)

The explorer talks to ONE `rclone rcd` over HTTP on `127.0.0.1` instead of paying an `rclone lsjson` start-up per folder.

- **Local and authenticated, always.** `--rc-addr 127.0.0.1:<port>` with a port from `puerto_libre()`; never `--rc-no-auth`, never `--rc-web-gui`. The user and password are random per start and travel in the child's **environment** (`RCLONE_RC_USER`/`RCLONE_RC_PASS`), never in argv (any local process can read argv). With them set, every method, `rc/noop` included, answers 401 without auth.
- **stderr goes to a host temp file, never a pipe**: `rcd` logs NOTICE lines continuously and a pipe nobody reads eventually blocks it. The file is the host's temp, never the device. `Rcd.esperar()` reads it when the process dies at start-up: «address already in use» (Windows: «Only one usage of each socket address») is `PuertoOcupado` (the port was free when chosen and taken before `rcd` opened it: the caller retries with another); anything else is `ConfigError` carrying that stderr.
- **`peticion()` bypasses the system proxy** (`ProxyHandler({})`): `HTTP_PROXY` would send loopback traffic to a proxy. An HTTP error status is returned, not raised; only a failure to talk raises `RcdCaido`. `Rcd.llamar()` turns a non-200 into `ErrorRc(mensaje, estado)`: `mensaje` is the JSON `error` field (rclone answers e.g. 404 `{"error": "error in ListJSON: directory not found", …}`), the body text if it is not JSON.
- **`arrancar()` does not wait** and must be called on the Tk thread; `esperar()` polls `rc/noop` every 0.1 s (`ESPERA_ARRANQUE = 10 s`) and is what goes to a thread. A 401 or a refused connection both keep it waiting: only the process dying, or the deadline, ends it.
- **`parar()` never raises**: `core/quit`, then `ESPERA_QUIT = 3 s` (measured against rclone v1.75.2: `core/quit` answers 200 and the process exits ≈1.5 s later), then `kill()`. The process is in `store._HIJOS` from `arrancar()` to `parar()`, so `store.matar_hijos()` also cuts it when the window closes or before the drive is ejected.
- **Indirection points** (tests replace them, no test starts rclone): `rcd.lanzar`, `rcd.peticion`, `rcd.puerto_libre`. `lanzar` builds its `Popen` arguments with the pure `_opciones_popen()` (`cwd = model.APP_DIR`, `stdin`/`stdout` to `DEVNULL`, `CREATE_NO_WINDOW` on Windows, `start_new_session` on POSIX), which is what the tests assert.
