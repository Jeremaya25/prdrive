# Periodic service (`runsync.py`)

Files: `runsync.py`, `ui/prefs.py`, `common/prioridad.py`, `common/model.py` (`ui_lock()`/`daemon_lock()`), `ui/__init__.py` (`avisar_fallo`).
Formerly AGENTS.md «Daemon (`runsync.py`)».

Coordination lives in `state/` so it travels with the device: `daemon.lock.json` (pid/host/boot/pairs/cycle), `daemon.stop` (presence = stop request), `daemon.log`, `ui.lock.json` (pid/host/boot of the open window), `ui_prefs.json`; plus `last_run.json`, `historial.jsonl`, `conflicts.json` (written by `sync.py`, not the daemon). The service stops when the device disappears (`SENTINEL`) or when runsync is launched again.

## What `runsync.py` imports

`keepassxc`, `llavero` and `update` are imported inside the functions that use them: the window path never needs them and the service loads `llavero` only with `[keychain]` (`import runsync` went from 114 to 45 ms). `ui`, `model`, `store` and `prioridad` stay bound at module level: tests replace `runsync.ui.start`, `runsync.model.load_config` and `runsync.prioridad.bajar`. `daemon_main()` imports `common.update` at start: the service lives for days, and a late import after a program update would read new files next to old modules (`updating.md`).

## One service, two ways to start it (#14)

By hand («Iniciar servicio») or on plug-in (watcher → `runsync --auto`): the same service with the same config, pairs + interval in `ui_prefs.json` on the device. With the resident agent as the root's service the window offers «Pausar»/«Reanudar» instead (`agent-window.md`).

`startup_defaults()` layers that record > `[daemon]` in the TOML > all pairs / 30 min, for the window, `--auto` and the watcher alike. Explicit `--auto` arguments still win (shortcuts, cron, watchers not yet reinstalled).

**Three writers, each with its own part** (#65):

- Ticking or unticking a pair in the window (`tk.al_marcar()` → `prefs.guardar_parejas()`) writes the ticked pairs at once, keeping the saved interval and pinning none if there is none. An empty selection is not saved (`elegir()` would read it as no record), so the last one stays. This is how the service, `--auto` and the agent see the selection without «Iniciar servicio».
- Starting the service (`_atender()`, action `daemon`) writes the ticked pairs with the interval already saved.
- «Ajustes → Configuración» (`prefs.guardar_intervalo()`) writes **only the interval**. It keeps a record's `pairs`/`known`/`action` untouched when `elegir()` honours them; otherwise it leaves a record **without `pairs`**, which `elegir()` reads as «saved interval, the TOML's pairs»: saving the interval never pins the pair selection, and a later hand edit of `[daemon] pairs` still counts. (An agent older than this reads such a record as no record and falls back to `[daemon]`'s interval: degraded, never wrong pairs.)
- «Sincronizar ahora» itself writes nothing: what persists is the tick, not the pass.
- A record with `action == "manual"` predates this and is ignored (by `== "manual"`, so a hand-written record without `action` still counts); saving the interval over one replaces it. The file keeps its old name: renaming needs a migration to change a word.

`--auto --once` (`una_pasada()`) is one pass of those pairs with no service behind it. With a live service on this host it does nothing and does **not** stop it: swapping a service for a single pass would leave the device without one.

## Rhythm: the service must not delay the window

Opening the window stops the service first (`stop_previous_daemon()`), so how fast the service notices `daemon.stop` is how late the window appears (it used to be 0–5 s, up to 15 s mid-pass).

- **`STOP_POLL_SECONDS = 1.0`:** the idle loop between cycles looks at `stop_requested()` and `pen_present()` (two `stat`s) every second. It sleeps `min(STOP_POLL_SECONDS, time to the next cycle)`.
- **`POLL_SECONDS = 5.0` is kept for the slow looks:** `read_lock()` («another service has the record») and `atender_llavero()` (the keychain's photo of the processes) are gated by `time.monotonic()` to that period, and `vigilar_llavero()` keeps sleeping it. The first slow look is at the start of the wait.
- **`STOP_WAIT_STEP = 0.1`:** the launcher looks every 0.1 s (it was 0.3) whether the old service released its record; `STOP_WAIT_SECONDS = 15.0` is unchanged. The window still opens **after** the service stopped: with a window open there is no service.
- With the resident agent as the root's service the wait is also its tick (`TICK`, 2 s), so the window waits about a second more on average. `tests/test_servicio_ritmo.py` pins a stop at t = 1007.3 seen within 1 s, the slow looks at 1000.0 and 1005.0 only, the launcher's six 0.1 s sleeps, and a real thread ended by `daemon.stop` within 2 s.

## A lock record names its boot

`ui.lock.json`, `daemon.lock.json` (runsync's service and the agent), `llavero.lock.json` and the agent's `agente.lock.json` carry `"arranque": store.arranque_del_sistema()` next to `pid`/`host`. The file travels with the device, so after a reboot it can hold a pid that the new boot handed to an unrelated process; without the boot time that pid reads as alive and a window that no longer exists blocks the new one.

Liveness is `store.vivo_en_este_arranque(info, host)`: same host, an int pid in `1..2**31-1` (a larger one is unreadable, not a process) that is alive, and, when the record has a numeric `arranque` and this system's boot time is known, a difference within `HOLGURA_ARRANQUE` (600 s). A record with no `arranque` (written by an older version) or one whose boot cannot be compared falls back to the pid alone. These readers go through it, each keeping its own `HOST` source:

- runsync: `_viva_aqui()` (so `ui_en_marcha()`, `tomar_ui()`, `tomar_lock()`, the vigilante's `tomar_registro()` and the service loop's «otro servicio» check), `servicio_en_marcha()` and `stop_previous_daemon()`.
- the agent: `Agente._otro_servicio()`, and `agente._registro_vivo(raiz, rel)` / `agente._aplicacion_en_marcha(raiz)` for every look at a root's `ui.lock.json` (and, in `_aplicacion_en_marcha`, its `daemon.lock.json`): the pause in `_contrato`, `_abrir_ventana`/`_lanzar_ventana`, the «bloquear»/«expulsar» waits, `_con_ventana` and the `abrir` command. They are the agent's own copies of penwatch's `_vivo_aqui()`/`aplicacion_en_marcha()`, with the boot time and the same phrases: the agent **pauses a root** on what they say, so a stale window record with a recycled pid would hold it paused «en pausa: hay una ventana de runsync abierta» for good, and the agent never cleans that file.
- shared: `equipo.vivo_aqui()` (-> `tomar_lock()`), `agente_vivo()` and `pasada_viva()`, `llavero.vivo_aqui()`, `repair.sincronizacion_en_curso()` and `tk_update.servicio_vivo()`. `agente_vivo()` matters most: the installer's `parar_agente()` ends the pid it returns (`taskkill /F` on Windows), and `install/agente.py` skips starting the agent when it returns a record, so a recycled pid read as alive would kill an unrelated process.

`repair.sincronizacion_en_curso()` keeps «ante la duda, sí» for a record of ANOTHER host (its boot cannot be compared); only a same-host record from another boot or with a dead pid counts as nobody.

**Pid-only on purpose**: `penwatch._vivo_aqui()` and `penwatch.aplicacion_en_marcha()` (the watcher's own decision to launch or not: it imports nothing from the project, `store` included, and a wrong «alive» only costs that plug-in's launch, the trigger being spent as the next section says). The agent no longer calls them.

**What the boot check does and does not promise.** `arranque` is `store.arranque_del_sistema()`: `btime` from `/proc/stat` on Linux, `time.time() - GetTickCount64() / 1000` on Windows.

- It detects a restart.
- It does **not** detect a Windows Fast Startup shutdown («Apagar» with Fast Startup on): the kernel is hibernated and resumed, `GetTickCount64` keeps counting, the computed boot stays the same and a record from before the shutdown whose pid was recycled reads as alive. There the check falls back to the pid alone, as it did before the field existed. A reboot whose previous session lasted less than 10 minutes falls back the same way.
- It tolerates `HOLGURA_ARRANQUE` = 600 s of difference: the Windows value drifts with every wall-clock correction, and some records live for days.
- Owners refresh `arranque` whenever they rewrite their own record (`runsync.daemon_cycle()` for the service lock, `Agente._apuntar_en_lock()` for a root's `daemon.lock.json`): a live process never spans a reboot, so recomputing cancels the drift. Records written once (`ui.lock.json`, `llavero.lock.json`, the agent's `agente.lock.json`) keep the value of their start.

Follow-up idea: record the pid together with the process creation time (`GetProcessTimes` / the `starttime` of `/proc/<pid>/stat`), which tells a recycled pid on any shutdown path.

## One window at a time; the watcher waits for it

`ui_flow()` takes `ui.lock.json` **before** `stop_previous_daemon()` and refuses a second window (opening runsync stops the previous service, so two windows would take it from each other).

- **Check and take are one step** (`tomar_ui()`): created with `O_EXCL`, never via `store.write_json` (its rename overwrites). Check-then-write let two runsync launched 6 s apart by two relays both open a window on a real device (28/09/2026).
- A record whose pid is dead, from another host or from another boot is the trace of a device pulled without closing. `_retirar_ui()` removes it only while holding a second exclusive file, `ui.lock.json.romper`, and only if it re-reads the same record (a plain delete could take a window that just replaced it); then the exclusive create is retried once. Windows refuses to delete a file another process is reading (WinError 32), so `_borrar()` retries; **every** delete of `ui.lock.json` and `daemon.lock.json` goes through it (`soltar_ui()`, the service's `finally`, `stop_service()`), since a relaunched window reads the first every 50 ms and the window reads the second every 0.1 s while it stops the service.
- **A relaunched window waits for its parent** (`tomar_ui()`): after an update the old window starts the new one (`ui/tk_update.py`) and closes afterwards, so the new one could find the old one's record and say «Ya hay una ventana abierta». On its first attempt, if the live record's pid is `padre_pid()` (`os.getppid()`; an indirection point), `_soltado_por_el_padre()` waits up to `ESPERA_PADRE = 3.0` s, looking every `PASO_PADRE = 0.05` s, for the record to change or disappear, and then takes it. A holder that is **not** the parent is refused at once, with no wait, and a parent that never lets go is refused after the 3 s. The wait does not spend the one retry: a parent that **dies** holding the record leaves a trace, which the next attempt retires and takes (before, the window opened without the record and a later launch could open a second one). `tests/test_instancia_unica.py`.
- Everything after the take, up to `_atender()`, runs inside the `finally` that releases it.
- `penwatch` reads both locks (never writes) and launches nothing while either is alive: the pass is logged and the trigger spent, so it does not retry every minute behind an open window. Both facts are said out loud (the pause in the watcher line of the main window and console menu; the other in the message confirming the service), but only when this host's watcher attends this device (`watch.resumen().vigila_este`): otherwise they would describe something that does not exist here.

## Windows specifics to preserve

- `pid_alive()` uses `OpenProcess`, never `os.kill` (which *terminates* on Windows).
- The daemon is spawned with `pythonw.exe` + `CREATE_NO_WINDOW`; rclone with `CREATE_NO_WINDOW` too (else every invocation flashes a console).
- The daemon `chdir`s to the temp dir so the device can be ejected.
- The daemon and `--auto --once` lower their own priority (`prioridad.bajar()`, `common/prioridad.py`) before launching anything, so every `sync.py` and rclone under them inherits it: `BELOW_NORMAL_PRIORITY_CLASS` on Windows, `nice` 10 and I/O best-effort 7 on Linux. The window's own passes keep normal priority: someone is waiting for them.
- Child `sync.py` runs get `stdin=DEVNULL`: a pair needing `--resync` is skipped, not resynced unattended.

## Failure pop-up

`daemon_cycle()` calls `notificar_fallo()` only when a pair *starts* failing (against the previous cycle's `last_results`): a healthy service is silent and a persistent outage does not reopen a window each cycle. No display → False; the notice stays in `daemon.log`. One window at a time.

`ui.avisar_fallo()` runs in its **own thread with its own Tk interpreter**, and everything Tk must die there: `theme.olvidar()`/`icons.olvidar()` drop the per-interpreter caches (theme: the applied set, the element images, the seating table of the surfaces `_asientos` and the font table `_LETRA` with its hidden canvas and named fonts) and `gc.collect()` runs in that thread, or the main thread frees the images at exit (`Tcl_AsyncDelete`).

**That thread is one per process and never ends** (`ui._aviso_abierto`, a queue of jobs). Tcl/Tk 9.0.4 (the Linux runtimes) aborts with `Tcl_Panic: epoll_ctl: Invalid argument` when a NEW thread creates a Tk interpreter after another thread created its own and exited (reproduced with four lines of tkinter, no prdrive code; several interpreters in a row in the SAME thread, or in threads alive at once, are fine). A thread per notice would kill the service on the second pop-up of a Linux runtime. `tests/test_daemon_aviso.py` pins «same thread, still alive»; the abort itself only shows with the runtime's own Python.
