# The «Servidor…» explorer (`common/rcd.py`, `ui/servidor.py`, `ui/tk_servidor.py`)

Formerly none: a new area. Why and what (three pieces, the user's decisions): `docs/superpowers/specs/2026-10-27-explorador-servidor-design.md`. The catalogue it browses: `catalogue.md`; the window pattern it follows: `ui.md`; the user's page: `docs/guia/servidor.md`.

**Status: pieces 1 and 2 of 3 built.** Piece 1 browses the remote one folder at a time and never writes to it. Piece 2 («Bajar…», «Subir archivos…», «Subir carpeta…») copies between the remote and the device; it never deletes, moves or renames anything on either side. Piece 3 (manage) is not built; see the last section. The checks that need a real machine (a real SFTP, a window killed by force, an eject, FAT32/exFAT, 10 000 files) are in `docs/superpowers/pruebas/2026-10-27-servidor-pendiente-en-real.md`, not yet run.

The files:

- `common/rcd.py`: the resident `rclone rcd` (its process, its HTTP calls, its anti-orphan belts) and the jobs on it: `copiar()` (`sync/copy`), `progreso()`, `estado()`, `cancelar()`. No Tk; it knows nothing of what is asked.
- `ui/servidor.py`: the decision half. No Tk, no disk, no network: how a listing is read, what is requested, navigation, the pair marks, permissions, the error phrases.
- `ui/transferencia.py`: the decision half of the transfers. No Tk, no network, no disk: the rules, the folders, the collision count, the pair warnings and blocks, the progress and result texts.
- `ui/tk_servidor.py`: the window. It draws, and it chains a batch's steps (see «Transfers»); `open_dialog(parent, config)`.
- `ui/tk_transferencia.py`: the transfer panel and the collision prompt. Draw only.
- The button: `VentanaPrincipal.abrir_servidor()` in `ui/tk.py`, drawn by `ui/tk_principal.py`.

## The resident `rclone rcd` (`common/rcd.py`)

The explorer talks to ONE `rclone rcd` over HTTP on `127.0.0.1` for as long as the window is open, instead of paying an `rclone lsjson` start-up per folder (on SFTP, each click would reopen the connection: 0.5–2 s).

- **Local and authenticated, always.** `--rc-addr 127.0.0.1:<port>` with a port from `puerto_libre()`; never `--rc-no-auth`, never `--rc-web-gui`. User and password are `secrets.token_urlsafe(24)` each, per start, and travel in the child's **environment** (`RCLONE_RC_USER`/`RCLONE_RC_PASS`), never in argv, where any local process can read them. Probe (rclone v1.75.2): with them set, every method, `rc/noop` included, answers 401 without the header. The child's environment is the process's **minus every `RCLONE_RC_*` variable** (case-insensitive, for Windows), then our two: rclone reads each `rc` flag from its variable too, so a user's `RCLONE_RC_NO_AUTH`, `RCLONE_RC_WEB_GUI`, `RCLONE_RC_SERVE`, `RCLONE_RC_ADDR` or `RCLONE_RC_HTPASSWD` would undo these guarantees, and `--rc-no-auth` has no negation on argv.
- Flags: `catalog.NET_FLAGS` (imported, so a bad Wi-Fi fails in seconds, as in `lsjson`), `--config model.RCLONE_CONF`, `cwd = model.APP_DIR` (`rclone.conf` resolves `key_file` and `known_hosts_file` there), `stdin`/`stdout` to `DEVNULL`, `CREATE_NO_WINDOW` on Windows.
- **stderr goes to a host temp file, never a pipe**: `rcd` writes NOTICE lines continuously and a pipe nobody reads eventually blocks it. `Rcd.esperar()` reads that file when the process dies at start-up. «address already in use» (Windows: «Only one usage of each socket address»; probe: exit code 1) is `PuertoOcupado`, a `ConfigError` subclass: the port was free when chosen and taken before `rcd` opened it. Anything else is a `ConfigError` carrying that stderr.
- **`peticion()` bypasses the system proxy** (`ProxyHandler({})`): an `HTTP_PROXY` would send loopback traffic to a proxy. An HTTP error status is returned, not raised; only a failure to talk raises `RcdCaido`. Each call waits up to `TIMEOUT_PETICION` (60 s). `Rcd.llamar(..., timeout=)` overrides it; the batch's polls (`rcd.progreso()`, `rcd.estado()`) use `TIMEOUT_SONDEO` (5 s).
- **`Rcd.llamar()`** turns a non-200 into `ErrorRc(mensaje, estado)`: `mensaje` is the JSON `error` field (probe: 404 `{"error": "error in ListJSON: directory not found"}`), the body text if it is not JSON.
- **`arrancar()` does not wait** and must be called on the Tk thread (see the belts). `esperar(tope=ESPERA_ARRANQUE = 10 s)` polls `rc/noop` every `SONDEO = 0.1 s` and is what goes to a worker thread. A 401 or a refused connection both keep it waiting; only the process dying or the deadline ends it.
- **`parar()` never raises**: `core/quit`, then `ESPERA_QUIT = 3 s`, then `kill()`. Probe: `core/quit` answers 200 and the process exits ≈1.5 s later; 2 s is too tight: it would kill a process that is already quitting. It leaves `store` and deletes `state/rcd.json` only if the file still names its pid.
- **Indirection points** (no test starts rclone or touches the network): `rcd.lanzar`, `rcd.peticion`, `rcd.puerto_libre`, `rcd.arrancar`, `rcd.atar_al_job`, listed in `commands-testing.md`. `lanzar` builds its `Popen` arguments with the pure `_opciones_popen(stderr)` (`cwd`, `stdin`/`stdout`, `creationflags` on Windows; `start_new_session` on POSIX, plus `preexec_fn` on Linux only). Tests assert on that helper, because a faked `lanzar` shows nothing of what the real one passes.

### Never an orphan holding the drive

A surviving `rcd` keeps the **device's** `rclone.conf` and binary open and blocks the eject, so there are three belts, from most to least immediate:

1. **Orderly close.** `Rcd` is in `store._HIJOS` from `arrancar()` to `parar()` (`store.apuntar_hijo()`/`soltar_hijo()`). `store.matar_hijos()` cuts it when the main window closes and before the drive is ejected. The explorer's own close (`WM_DELETE_WINDOW` and `<Destroy>`) runs `parar()` in the background, once.
2. **The window dies abruptly.**
   - Windows: `atar_al_job()` puts the child in a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (ctypes). The handle is kept in `_JOBS` and never closed by us, so the OS closes it when the window's process dies and kills the job. `False` means no belt; the `rcd` still starts.
   - Linux: `_opciones_popen()` adds `preexec_fn=_morir_con_el_padre`, which calls `prctl(PR_SET_PDEATHSIG, SIGKILL)`. The `prctl` pointer is resolved **in the parent** (`_resolver_prctl()`, module global `_PRCTL`), so between `fork` and `exec` the child only calls it. macOS has no such call and no `preexec_fn`.
   - **The trap:** `PDEATHSIG` fires when the *thread* that forked dies, not when the process does. Probe (rclone v1.75.2): from a thread that ends, the child dies at once; from the main thread it lives. So `arrancar()` runs on the Tk (main) thread, which lasts as long as the window, and only `esperar()` goes to a worker. Starting `rcd` from any worker would kill it within seconds.
3. **One survives anyway.** `arrancar()` writes `state/rcd.json` (`fichero_estado()`, a function because tests move `STATE_DIR`) with `{"pid", "creado"}` (`store.creado()`), **never the password**. The next `arrancar()` calls `limpiar_huerfano()` first: it kills the tree (`store.matar_arbol()`, which needs the `start_new_session` of `_opciones_popen`) only if the pid is alive **and** its creation time matches within 1 s, so a pid inherited by another process is left alone. An unknown creation time is not killed either. The file is always deleted and the function never raises. `--doctor` does not touch any of this.

Order in `arrancar()`: `catalog._binary()` (no rclone is a `ConfigError`) → `puerto_libre()` (a failure is one too) → `limpiar_huerfano()` → `lanzar()` → `atar_al_job()` (Windows) → write `rcd.json` → `store.apuntar_hijo()`. Tests force Windows by replacing `rcd.os` and faking `atar_al_job`; the real Job Object call runs only on Windows (`(saltado)` elsewhere), and `PDEATHSIG` is covered by asserting `_opciones_popen()`, not by starting a process.

## Listings and the fixed `fs`

- Every listing and the `fsinfo` use **`fs = "<remote>:/"`**, always the same string. rclone caches one Fs object, and with it one SSH connection, per `fs` string. Probe: `srv:` and `srv:/` are two cached Fs, so two connections; repeated `srv:/` listings reuse one (≈3 ms). A `fs` per folder would log in again on every click, so `fsinfo` uses the same string too.
- `:/` is the absolute root. On SFTP `remote:` is the backend's default folder, the home folder, a different place (the same distinction `remote_picker.normalizar()` makes).
- `remote` is the folder without its leading slash, as a JSON string, never URL-encoded (a name with spaces, `%`, `#` or `?` arrives as it is; the root is `""`). `opt` is `{"noMimeType": true}`, plus `"metadata": true` when permissions are asked (below). Nothing is recursive and no hashes are asked: one request per folder.
- **The one exception:** the home folder's `uid` (permissions only, once per remote, and not for `local` remotes) is `operations/stat` with `fs = "<remote>:"`, `remote = ""`. That is a second cached Fs, so a **second SSH login**, paid only when permissions are on (pending row S6 checks it on a real server).

## Permissions

The explorer shows the permission bits as three octal digits (`755`), and marks folders the user cannot enter before trying. Both depend on what the backend gives, so:

- **Asked only where the listing carries them.** `servidor.pide_permisos(fsinfo, tipo)` is true only if `Features.ReadMetadata is True` **and** the remote's `type =` in `rclone.conf` is in `LEE_PERMISOS_EN_EL_LISTADO = {"sftp", "local"}`: backends whose metadata comes out of the same listing. The `type` is read from the config because `fsinfo`'s `Name` is the remote's name, not its backend's. A `crypt` over SFTP is `crypt`, so it is not asked.
- **Why not S3 or other backends that read metadata per object:** `opt.metadata` there costs a request per file, which would turn each folder into thousands of requests. Widening the set needs proof, in rclone's code, that the backend returns metadata in the listing.
- **Today:** rclone v1.75.2 gives SFTP `ReadMetadata = false` (probe), so nothing is asked and the column is `SIN_DATO` («—») in every row. This is intended, not a bug. Proposed in rclone/rclone#7310; implemented by rclone/rclone#9631 (open since 19/07/2026, awaiting review). The code is written for that PR's format and switches on by itself once a pinned `RCLONE_VERSION` includes it: `mode` is an octal string with the type bits (`100600`, `40755`), `uid`/`gid` are decimal, all in the listing (`opt.metadata`), and `ReadMetadata` becomes true.
- **Read defensively.** `Entrada.modo`/`uid`/`gid` come from `Metadata` only when they match `[0-7]{1,7}` (mode) or `[0-9]{1,10}` (ids); any other shape is `None`, never an exception. `texto_permisos()` shows `modo & 0o777` as three digits, or «—».
- **Pre-lock («candado previo»).** `servidor.mi_uid(tipo, stat)` gives the user's uid. For `sftp` (and any other non-`local` type) it is the home folder's `uid` (`mi_uid_de(stat)`). For a `local` remote it is `os.getuid()` of our own process (`servidor.uid_del_proceso()`, a test replacement point; `None` on Windows, where there is none): `rclone rcd` runs as us, while `operations/stat` of `<remote>:` would stat the `rcd`'s working directory, `.prdrive/` on the device, which may belong to someone else (an ext4 or NTFS-3G drive mounted by another uid) and would padlock folders the user can open. A `local` remote therefore never asks for the `stat` (`uid_se_pregunta_al_servidor()`). `sin_acceso_previo(entrada, mi_uid)` marks a folder only when entering is certainly impossible (entering needs `r` and `x`): the owner's bits lack `r`+`x` and the user is the owner; or the user is not the owner, neither group nor other has `r`+`x`, and `mi_uid != 0`. Root enters everything; an unknown uid marks nothing. A group-dependent case is not marked, because SFTP does not say which groups the user has.
- **After-failure lock.** A listing that fails with a permission error (`es_de_permiso`: a 403, or permission text) adds `(remote, ruta)` to `Navegacion.sin_acceso`. It stays while the window is open. It is the only lock today, since the column is `—`.
- **Checklist when `RCLONE_VERSION` moves past v1.75.2** (spec, «Permisos»): (1) `operations/fsinfo` of an SFTP remote says `ReadMetadata: true`; (2) a listing with `opt.metadata` gives `mode`/`uid`/`gid` in that format with no extra round trip (`sshd` log: one directory open per folder); (3) the home folder's `uid` comes from `operations/stat` of `<remote>:` with that version; (4) if any of this fails, the column stays «—» and nothing breaks.

## The decision half (`ui/servidor.py`)

No Tk, no disk, no network. The window calls it and draws what it returns.

- **Entries.** `entradas_de(respuesta)` reads `operations/list`'s `list`: folders first, then `str.lower` order; an item of the wrong shape is skipped, as `remote_picker.parse_lsd()` does; a response with no list is an empty folder. `ModTime` keeps microseconds (`_FRACCION`); a date before 1970 (rclone's `0001-01-01T00:00:00Z` for «unknown») or one that overflows `astimezone()` is `fecha = None`, shown «—». A folder's size is `None` (SFTP does not give it without walking the folder).
- **Last request wins.** `Navegacion.pedir()` numbers each request; `recibir()` and `fallo()` ignore any that is not the last. `remote`, `ruta` and `entradas` change together, and only in `recibir()`, so the table never shows folder A under path B. `pedir()` always asks the remote on screen; only `cambiar_remote()` asks another, so a failed or superseded remote change never sends a folder of the old table to the new remote.
- **Remotes.** `remotes_de(texto_conf, por_defecto, device_remote)`: the `rclone.conf` sections, without `combine` and `alias` (prdrive's own) and without the device's `device_remote`; `[defaults].remote` first, then by name.
- **Pairs.** `marca()` (the folder is exactly a pair's `remote_path`) and `dentro_de()` (the folder is that path or below it, at a `/` boundary) look only at pairs on the **same** `remote_name`. `dentro_de()` returns the DEEPEST pair (longest `remote_path`, so a root pair contains everything but a nested pair wins), not the first in config order.
- **Errors.** `frase_error()` checks `RcdCaido` **first** (its text quotes urllib's connection errors, so it must not read as «no network»), then permission, no network (`dial tcp`, `connection refused`, `no route to host`, `no such host`, `network is unreachable`), not found (404 or text), timeout; anything else is quoted as rclone said it. `es_sin_red()` and `es_de_permiso()` are both false for `RcdCaido`. `es_sin_red()` decides «Reintentar» at open.
- **Strings.** Sizes in base 1024 with a decimal comma below 10 (`1,5 KB`); dates `dd/mm/aaaa hh:mm` in local time.

## The window (`ui/tk_servidor.py`)

`open_dialog(parent, config)` is a modal «Servidor» built like «Dispositivos»: `Sondeo` + `tk.Indicador` + a `ttk.Treeview` list (see «The list»), with `segundo_plano.lanzar(partial(...))` for the work. Nothing of Tk runs in the thread. Tests replace `tk_servidor.mostrar` and `rcd.arrancar`.

- **Opens first, reads after (#66 in `ui.md`).** `conectar()` calls `rcd.arrancar()` on the Tk thread and the window appears at once with «Conectando con el servidor…». One `Encargo` (`_leer`) runs `esperar()`, `operations/fsinfo`, the home `stat` if permissions are asked, and the listing of `/`. The per-remote `(permisos, mi_uid)` is remembered, so later listings are one call.
- **Failures stay in the indicator.** The table keeps the previous folder. A permission failure repaints the rows (padlock). A failed remote change, or a change with no `rcd`, resets the combo to the remote on screen.
- **Buttons.** «Reconectar» after `RcdCaido`: relaunches `rcd` on the Tk thread, stops the old one in the background, repeats the last request. «Reintentar» when the opening request fails with `es_sin_red`, or `rcd` does not start (repeats it; relaunches `rcd` only if it is not alive). `PuertoOcupado` relaunches **once**, with another port, on the Tk thread; a second one is shown with «Reintentar». `RcdCaido` is never «sin red»: it gets «Reconectar».
- **The list is a `ttk.Treeview`, not `tk.Tabla`** (final review C1 + E2E-1; modelled on `tk_pairs.explorador_remoto`, `catalogue.md`). Two reasons, both seen on a real run:
  - `tk.Tabla` draws a row's `CeldaIcono(icono, nombre)` as the icon only (`.texto` is the accessible text, never drawn), so names and the pair mark were invisible.
  - `tk.Tabla` is one canvas that asks for its whole height (~39 px a row). Past ≈850 rows the canvas exceeds 32 767 px, X11 answers `BadAlloc` and Xlib's default handler exits the **whole prdrive process**. A `Treeview` only paints the rows it shows (`FILAS_VISIBLES = 12`, a scrollbar for the rest), so a folder of thousands costs the same as one of ten (5 000 entries: 0.35 s, request height 373 px). There is no cap and no paging: the use is browsing a server like a file manager.
- **Columns.** `#0` is the tree column («Nombre»): the only one of a `Treeview` that takes an icon, so it holds the icon (`carpeta`, `file` or `candado`, from `ui.icons`) plus the name text; the tree never expands, you enter. Then `Tamaño`, `Modificado`, `Permisos` as `values`. `COLUMNAS` holds titles and widths (`icons.px`), colours and fonts come from `theme`.
- **Rows.** The iid is the entry's name (unique within a folder; names such as `123`, `{x}` or with spaces are pinned by a test). `text` is `" {name}"`, plus `"  · pareja «{pareja}»"` for a pair's folder. A locked folder (`sin_acceso` or `sin_acceso_previo`) gets the `candado` icon and the `apagado` tag from `theme.marcar_lista()` (muted ink, italic); the others the `ok` tag. The padlock has no text. After a permission failure `retocar()` updates the existing rows' icon and tag in place (selection and scroll stay); a new listing rebuilds the list (`lista.delete` + `insert`).
- **Keys and mouse.** A double click on a **row** (`identify_region` is `tree` or `cell` and `identify_row` is non-empty; on the heading or in empty space it does nothing), Return and KP_Enter enter the selected folder (a file does nothing); BackSpace and «↑» go up. The handlers return `"break"` so the class binding that toggles an item open does not run.
- **«Esta carpeta está vacía.»** is a `Card.Pista.TLabel` placed over the list (`place`) only once a listing has arrived with no entries (`estado["abierto"]`): the window is created silent, so a connecting or unreachable one does not claim it is empty.
- **No remotes**: «Este dispositivo no tiene conexión con ningún servidor.», and the controls are disabled.
- **Closing** (`WM_DELETE_WINDOW` and `<Destroy>`) runs `parar()` once, in the background, guarded by a flag. `Sondeo` cancels with the window, so a late answer finds nobody. `tests/test_tk_servidor.py` covers this with real threads.

## Transfers («Bajar…», «Subir archivos…», «Subir carpeta…»)

The three buttons are in the window's **footer, beside «Cerrar»**, not in a top bar as the spec said (a deviation accepted during the build, not in the spec). The transfer panel sits between the list and the footer (grid row 3, `Panel.marco`; hidden when no batch is running).

**Rules.** A batch is ONE asynchronous `sync/copy` (`rcd.copiar()`), with `createEmptySrcDirs: true`, `_filter: {"IncludeRule": [...]}` and `_group` = `lote-<n>`. It never calls `sync/sync`, `sync/move`, purge or delete; that is a grep-able invariant. `copiar()` refuses an empty rule list (`ValueError`, before any call: without rules rclone copies the whole source).

- `transferencia.reglas_de(elementos)`: a file `x` → `/x`; a folder `x` → `/x/**`. The rclone pattern characters `* ? [ ] { } \` are escaped with `\` first. A wrong escape copies something else, so it is the most delicate function of the module.
- `transferencia.fs_de(lote)`: a batch's `fs` is the folder it copies from or to, `<remote>:/<ruta>` on the remote side, and the local folder on the other. The rules are relative to that folder. **This is the one place the fixed-`fs` rule above does not apply**: the listings use `<remote>:/` so one cached connection serves every click; a batch uses its own folder, so its first call opens one more cached connection for that folder. Its cost on a real SFTP server is not measured yet.
- Download: the selected rows are copied **with their structure** into the chosen folder. Upload to «Subir archivos…»: the selected files are copied by name into the folder shown; «Subir carpeta…» copies the chosen folder entire, under its own name, into the folder shown.
- Selection is `selectmode="extended"`. «Bajar…» is on with a connection, no batch running and at least one row chosen (a folder or a file). The two «Subir…» are on with a connection (`rcd` not `None`) and no batch running. Enter enters the chosen row when exactly one row is chosen and it is a folder; a double-click selects its row first and then enters it when it is a folder.
- The three dialogs are module functions that tests replace: `tk_servidor.elegir_destino(parent, inicial)` (`askdirectory`, «Elige dónde guardar»), `elegir_archivos` (`askopenfilenames`), `elegir_carpeta` (`askdirectory`). They open at the local folder last used in this window (the home folder when the window opens). Nothing is stored on disk.

**Pair warnings, both directions** (`transferencia.afectadas_subida`/`afectadas_bajada`, `bloqueo()`, `aviso()`). Pairs are matched by the deepest folder: the pairs that share the deepest matching path count, not the first in config order. Outside every pair folder, nothing is said.

| Direction | Mode | Result |
|---|---|---|
| Upload into a pair's remote folder (or a chosen item lands on one, or contains one) | `up-mirror` | **blocked**: the pair's next pass would delete what was uploaded |
| Upload | `bisync`, `down`, `down-mirror`, `up` | warning with «Seguir» / «Cancelar» (the mode's text) |
| Download into a pair's local folder (same matching, against `Pair.local_abs`) | `down-mirror` | **blocked** |
| Download | `bisync`, `up`, `up-mirror`, `down` | warning with «Seguir» / «Cancelar» |

With several pairs affected: any blocking one blocks; otherwise one warning names them all. The blocking text is shown in an ordinary notice; the warning's title is «Carpeta de una pareja».

**The flow** (`tk_servidor.empezar()` → `contar()` → `choques_contados()` → `copiar()` → `copia_lanzada()` → `sondear()`; each step on the Tk thread, each network step in `segundo_plano` with its own `Sondeo`, so navigating does not disturb a batch):

1. Pair check: block, or warn and ask.
2. Count the collisions in background, with «Mirando el destino…» in the indicator. Upload: a recursive `operations/list` of each chosen item under the destination (`_rutas_remotas`, not the whole destination) against a local `os.walk` (`_rutas_locales`). Download: the reverse. Only **files** count; a folder that exists is merged, not a collision.
3. With collisions, ONE prompt (`tk_transferencia.preguntar_choques`): «N elementos ya existen en {destino}. ¿Sobrescribirlos u omitirlos?» (singular for one) with «Sobrescribir», «Omitir», «Cancelar». Focus starts on «Cancelar»; Return on a focused button presses it, Escape and the window's X cancel. The prompt is the confirmation `AGENTS.md` asks for overwriting user data: it says how many and where.
4. `rcd.copiar()` with `_config: {"IgnoreExisting": true}` only for «Omitir». «Sobrescribir» gives no `_config`: differing files are overwritten, identical ones skipped. «Cancelar» copies nothing and returns the buttons.
5. The panel: `progreso_de()` every `INTERVALO_PROGRESO_MS` (500 ms), from `core/stats` and `job/status` together (`_sondear`; `status` first, so a `finished` status is followed by final stats).

**Collisions are an exact string match.** `transferencia.choques()` intersects the two sets of relative paths. On a case-insensitive filesystem (NTFS, exFAT, FAT32 on Windows) `Foto.JPG` on the remote and `foto.jpg` on the device are one file for the device but not for the count: no prompt, and the file is overwritten. Known and open; the pending row T5 records what happens on a real device. Do not fix it by lowering case on one side without thinking about the remote, which is case-sensitive.

**The panel** (`ui/tk_transferencia.Panel`): title «Subiendo a …» / «Bajando a …», the current file, «N de M archivos · X de Y» (bytes), a `ttk.Progressbar` (indeterminate while the total is unknown), speed and time left, and «Cancelar». Figures come from `progreso_de()` and tolerate missing, null or zero fields.

- **Cancel**: `cancelar_lote()` sets `cancelado`, shows «Cancelando…» at once, and calls `rcd.cancelar()` (`job/stop`, which does not raise if the job already ended). The panel ends «Cancelado: copiados X de N» with no «Reintentar». What was copied stays. Probe (27/10, rclone v1.75.2, `serve sftp`): cancelling mid-file leaves no partial on the download side, and an upload over an existing file keeps the old version.
- **Result**: `resultado_de()`: «Copiados N · omitidos M» (ok; omitted = `checks` − transfers, only when positive) · «Cancelado …» · an error (aviso, with «Reintentar»). A write refused by the server reads «No tienes permiso para escribir en {destino}.». Any other error is `servidor.frase_error()`, or rclone's own text when it is not one of the known phrases.
- **«Reintentar»** repeats the batch with the same collision decision (`reintentar_copia`). Already copied and identical files are skipped, so it carries on where it stopped.
- **A failed progress poll** (`_sondear`: `job/status` + `core/stats`, each with `rcd.TIMEOUT_SONDEO` = 5 s instead of 60 s; any `ErrorRc`, and any `RcdCaido`, a timeout included). What it means depends on the process, not on the exception: while `Rcd.vivo` the copy may still be running, so `sin_respuesta()` keeps the batch active (buttons off, no «Reintentar», close still asks) and polls again; after `FALLOS_PARA_AVISAR` (3) consecutive failures the window's line says «Sin respuesta de rclone…» and it goes away when a poll answers. The batch ends only on `job/status` `finished`, on a dead process, or on the close flow below. Hence two concurrent copies are impossible. With the process dead the copy died with it: the line says «Se perdió la conexión con rclone.» with «Reconectar», the panel shows the same, no «Reintentar», and the batch does not resume by itself. A launch or count that fails with `RcdCaido` ends the same way.
- After an upload into the folder on screen, the listing is read again, also after a failure or a cancel (`acabar()`: anything may have been written).
- **Closing with a batch running** (`cerrar_ventana()`): asks «Hay una transferencia en marcha. ¿Cancelarla y cerrar?» with «Cancelar y cerrar» / «Seguir». Yes: `cancelar` and wait up to `rcd.ESPERA_QUIT` (3 s) for `finished` in the background (`_cancelar_y_esperar`), then close and stop the `rcd` as always. Closing while the batch is still counting, or between `copiar` and the `jobid`, does not ask: the batch ends with the `rcd`.
- Buttons are enabled from `estado["rcd"] is not None`, not from `Rcd.vivo`: a dead `rcd` leaves them on, and the first call fails into the error path (`RcdCaido`, above).

**A window that dies abruptly** (see the belts above): the `rcd` is killed, and the file being copied may leave its temporary on the server. Nothing cleans it here (deleting is piece 3). The temporary's name is what rclone's SFTP backend writes before its final rename; the exact name is not confirmed in this tree and the pending row T6 records it. The user's guide says so.

## The button in the main window

- **«Servidor…»** sits in the `pantallas` row between «Parejas…» (column 0) and «Ajustes…» (column 2), `Quiet.TButton` with the `nas` icon. `VentanaPrincipal.abrir_servidor()` calls `tk_servidor.open_dialog(self.root, self.config)` and reads nothing again on return, since the window changes neither config nor state. `ui.tk_servidor` is in `ui.tk.PRECARGA`.
- **Enabled when** `principal.controles()["servidor"]` is `libre and e.servidor` (visible always): no pass in progress, and `Estado.servidor`, which is the shared read (`Instantanea.remotes_servidor`, `instantanea.leer()`, under its own `try`) finding at least one remote after `servidor.remotes_de()`. A missing `rclone.conf` gives `()` with no entry in `fallos`. Until the read arrives it is off.

## Known, not fixed

These were found in review and left on purpose; none changes what the user sees on a normal path.

- Each `rcd` call waits up to 60 s. A `rcd` that accepts connections but never answers can overrun `esperar()`'s tope, and `parar()`'s wait, which runs in the background.
- `esperar()`'s final `ConfigError` does not quote the last `ErrorRc` text.
- `remote_picker.normalizar()` (inherited) turns `\` into `/` and strips the ends of a name: on Linux, a folder called `a\b` or with a trailing space navigates to the wrong path.
- `_JOBS` keeps one handle per `arrancar()` (one per opened window). `_olvidar()` reads then deletes, so a race can drop a newer `rcd.json` (belt 3 only).
- `Instantanea` treats an unreadable `rclone.conf` as a failed read; the window treats it as empty. `rclone.conf` is not in `Instantanea.huella`, so an edit shows on the next read only.
- **Transfers** (found in the piece 2 review, left for the final review):
  - A batch whose polls keep failing while the `rcd` lives stays active until the process dies, `job/status` answers, or the window is closed (a `job/status` «job not found» after the job expired included): «Cancelar» sends `job/stop`, but the panel stays at «Cancelando…» until a poll answers.
  - Closing during the count or between `copiar` and its `jobid` does not ask «¿Cancelarla y cerrar?».
  - The buttons test `rcd is not None`, not `Rcd.vivo`, so a dead `rcd` leaves them enabled until the first call fails.

## Dependencies to keep in step

- `tests/test_precompilar.py` checks that every standard-library module the program imports is in `install/deploy.BIBLIOTECA` (the set precompiled for the device). `common/rcd.py` imports `http.client` and `urllib.error`, so both are there; a new stdlib import in these files goes there too.
- `ui/tk_principal.py` `FILAS`/`BANDAS` are the layout the button sits in (`ui.md`, «The band below the list»).

## Piece 3 (not built)

- **Piece 3, manage** (its own spec, plan and PR): rename, move, delete, each through an `EditPlan` shown by `tk_pairs.confirmar_plan()`, as everything that deletes or rewrites data (`AGENTS.md`). Pair folders are the danger: a hand edit on the remote side of a bisync pair looks like a change or a delete on the next pass. In piece 1 the pair marks and «Estás dentro de la pareja» only inform; in piece 3 they are what protects those folders.

## Tests

No test starts rclone or touches the network: `rcd.lanzar()` and `rcd.peticion()` are replaced.

- `tests/test_rcd.py`: `arrancar()` waits for `rc/noop` and respects its deadline; a process that exits first gives `ConfigError` with its stderr; user and password are in the environment and **not** in argv; the listen address is `127.0.0.1`; `parar()` does `core/quit`, then `kill`, and the process is in `store`; a stale `state/rcd.json` is killed only if pid and creation time match, and never holds the password; the Job Object and `PDEATHSIG` branches are forced with `IS_WIN` or print `(saltado) …`; `Popen` happens on the calling thread; the proxy bypass is checked against a real loopback server, with `NO_PROXY` cleared, so a `peticion()` that used a proxy would show.
- `tests/test_servidor.py` (no screen): entries, order and dates; the pair mark only on the same remote, and the «dentro de la pareja» notice; the root pair and nesting; the picker without `combine`/`alias`; stale responses dropped; error phrases and the after-failure lock; permissions: when they are asked (`ReadMetadata` false, backend outside the list, S3 with `ReadMetadata` true gives no), `mode` in the PR's format, malformed formats giving `None` and «—»; the pre-lock table (owner, group, other, root, unknown `mi_uid`).
- `tests/test_tk_servidor.py` (windows; CI runs them on Linux under xvfb and on Windows): the window opens before reading, the indicator, what the list DISPLAYS (`tree.item(iid, "text")` with the name and the pair mark, `"values"`, `"image"`; never the data the window holds), «—» in the permissions column, double click only on a row, «Reconectar», the empty-folder text only after a listing, a 5 000-entry folder that opens and shows all of them, closing.
- `tests/test_tk_medidas.py` (the size matrix, `ui.md`): «Servidor» is measured on every `PANTALLAS` entry in its tallest and widest realistic state: a fake `rcd` answers a 41-entry folder with long names, a pair's folder (mark), a folder locked by its permissions (padlock), a long remote name, and a root pair that puts «Estás dentro de la pareja…» in the indicator. It checks the window asks no more than `pantalla_util` and that nothing is clipped without a bar, and that the measured window really had the full list, the mark, the padlock and the notice. The sizing rule did not need to change: the `Treeview` keeps `FILAS_VISIBLES = 12` rows and the window sits in the `Visor` like every screen, so on a screen too small for it the `Visor` caps it and shows its own bar (at 1024x600 and 133 % it asks 559 px of 600 and needs none).
- Transfers (piece 2): `tests/test_rcd.py` (`copiar` sends `sync/copy` and never `sync/sync`, with the filter, `createEmptySrcDirs`, `_async`, the group, `IgnoreExisting` only with «Omitir», and no call at all for an empty rule list; `cancelar` sends `job/stop` and swallows only `ErrorRc`; `progreso`/`estado`); `tests/test_transferencia.py` (rules and escaping, folders, the collision count, the pair blocks and warnings in both directions, `progreso_de`, `resultado_de`); `tests/test_tk_transferencia.py` (the panel, the three answers of the collision prompt with «Cancelar» as the default); `tests/test_tk_servidor.py` (the buttons, the multiple selection, the block and the warning in the window, the one prompt, cancel, the result and «Reintentar», closing during a batch, the listing read again after an upload into the folder on screen); `tests/test_tk_medidas.py` (the window with the panel visible).
- `tests/test_principal.py`: when «Servidor…» can be pressed. `tests/test_instantanea.py`: the shared read's `remotes_servidor`.
- `tests/test_reglas_claude.py`: this doc, its rule, and the `paths` of the rule.

Real machine: `docs/superpowers/pruebas/2026-10-27-servidor-pendiente-en-real.md` (eight rows for piece 1, six for piece 2; none run yet).
