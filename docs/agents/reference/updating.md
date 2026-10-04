# Updating a device in place (`common/update.py` + `ui/tk_update.py` + `--update`)

Formerly AGENTS.md «Updating a device in place». The versioning story and the components (rclone, Python, VeraCrypt) are here too.

The main window shows an amber block when GitHub has a newer release.

- **The applier runs from the download, not the device.** `install/` is deliberately absent from a provisioned device, so the update runs `python <extracted>/prdrive-install.py --update <volume>`: **the new version installs itself**. An applier in `common/` would be a second copy of the "what is the deployed tree" manifest.
- **The payload is the source zip of the tag (~270 KB), not the release `.exe`**: the CI exe is generic and would re-ask for the connection.
- **`.prdrive/` is never renamed.** `deploy_code()` copies file by file because stage-and-swap breaks three ways: `rclone.exe` may be running from `.prdrive/bin/`; if `runsync.py` vanishes for an instant penwatch loses its `STRUCT_MARKER` and relaunches the UI; if `sync_config.toml` vanishes a running service shuts itself down.
- It does not touch `bin/`, `runtime/` or the launchers: runtimes are a component, not app code.

## VERSION

`VERSION` at the repo root is the whole versioning story. `install.version()` reads it from `bundle_dir()`, `update.installed_version()` from `APP_DIR`. The release workflow (`.github/workflows/build-installer-release.yml`) is **triggered by a push to `main` that touches `VERSION`** and tags `v<VERSION>`, so the tag cannot disagree with the file; if the tag exists there is no new version. A device with no `VERSION` reads as unknown, older than anything. `check()` never raises and honours a 24 h cache in `state/update.json`; `pending()` reads that cache and **never** goes to the network (it is what the first paint asks).

## Components

Components travel a different road, same shape. `common/components.py` reads the stamps (`runtime/<clave>/PRDRIVE-RUNTIME`, `bin/<arch>/<rclone>.PRDRIVE-RCLONE`) and subtracts them from `pins.py`; pure and network-free, so the window asks it while painting, like `update.pending()`. `install/components.py` fixes what it finds, from the zip for the same reason the code applier does. Not to weaken:

- **The zip downloaded is the INSTALLED tag's** (`update.source_tag()`), not the latest release's: the pins travel with the program, so the machinery that fetches components must be the one from the version that pins them.
- **The rclone cache is keyed by pinned version** (`rclone_bin.cache_dir()`) and re-hashed against the sum recorded beside it on every use. Without the version segment, moving `pins.RCLONE_VERSION` changes nothing because `find_rclone()` finds the cache before it considers downloading.
- **Only what can be asserted gets stamped** (`rclone_bin.pinned_version()`): nothing is known about an rclone found on the PATH, so it is left **without** a stamp. A stamp that lies is worse than none: the device would stop asking for the update it needs.
- **The swap is `install_runtime()`'s, for rclone too**: copy beside, move aside, rename; never `copy2` over the binary that is there. Whatever is in use is postponed with its reason (`rclone_en_uso`/`runtime_en_uso`/`veracrypt_en_uso`). Leftover `runtime/.<clave>.nuevo|viejo|borrar-<pid>` of a process no longer alive are swept (`deploy.barrer_restos_runtime()`, from `install_runtime()` and `--update-components`); a live pid is left alone.

### The window's own Python: the relay («relevo»)

On a full install the window runs from `runtime/<clave>/`, and a runtime must not be swapped under a live interpreter. Not because Windows refuses: on G: the rename **succeeded** with a `pythonw.exe` inside, but the moved-aside folder could not be deleted (`.windows-x64.viejo-<pid>` kept the 21 files that process had loaded) and the rest, its stdlib, was deleted under it.

- `common.components.propio()` spots the case before starting; the confirm says the window will close.
- The window passes `--relevo <its pid>`. The applier skips that runtime and first checks `quien_retiene()` (`procesos_desde()`: Toolhelp + `QueryFullProcessImageNameW`, or `/proc/*/exe`). Anything else running from it (a second window, a forgotten «Ya hay una ventana…» box) is named and the window stays open (rc 1).
- `relevo_en_marcha()` refuses a second relay for the same device (a `dispositivo` file sits beside `owner.pid`).
- `components.preparar_relevo()` extracts the **same** pinned runtime into the host temp dir (`prdrive-relevo-*`, swept by the next one like `remote.sweep_stale()`), plus a copy of the code (the staged zip is deleted as soon as the window regains control). It launches it detached (`lanzar_suelto()`, cwd = temp, no inherited pipes: the output window reads until EOF) with `--esperar` both pids and `--reabrir`.
- The applier exits `update.CODIGO_RELEVO` (3). The output window shows it through `veredictos=` (not «ERROR»), `tk_update` returns `CERRAR` and the main window closes.
- `cmd_relevo()` runs behind `ui.tk_relevo.mientras()`: `working()` hung off `root_oculto()` with `suelto=True`, because a `transient` of a withdrawn root never shows (measured). `install.components.AvanceRelevo` says what it waits for (pids) and the % copied (the `.nuevo-<pid>` folder against the identical runtime already extracted in temp).
- It waits with `esperar_a(libre=runtime/)` (30 min cap, then gives up untouched), runs `--update-components`, and reopens the window with the device's Python. Only on failure does it show `relevo.log` via `report()` (it runs under `pythonw`, stdout is None). With no Tk it does the same work unseen.
- `lanzar_suelto()`/`esperar_a()`/`procesos_desde()` are indirection points.

### The travelling VeraCrypt is the third component (#50)

Its stamp, `VeraCrypt/PRDRIVE-VERACRYPT`, lives on the **physical** root, so `components.pendientes(app_dir, fisica)` takes that root or finds it through `components.raiz_fisica()` (control-file id → vestibule marker, an indirection point); a device not in a container has none. `Pendiente.plataforma` is None and `ruta` is the folder.

**An unstamped `VeraCrypt\` (an old device's installation copy) is never touched by `--update-components` or `--update`**: its vestibule only opens `VeraCrypt\VeraCrypt.exe`, and the vestibule is not a component's to rewrite. It reads as pending with `asistente=True`; the window says «Añadir plataformas…» and offers no button when that is all there is (`components.actualizables()`); `aplicar()` postpones it with that reason. «Añadir plataformas…» writes the new vestibule **first** (it opens both layouts) and then swaps in the stamped Portable (`traveler.llevar()`), so the two stay coherent whatever happens to the second.

## What a download must survive

Before going near the device: TLS, the zip CRC, every name in `update.OBLIGATORIOS` present, no member whose path escapes the destination (`_ruta_segura`; `extractall` is the footgun), and the `VERSION` inside matching the tag asked for. There is no signature; `docs/guia/seguridad.md` says so.

`rclone_bin.download_rclone()` (and `runtime_bin`, same contract) pulls `SHA256SUMS` and hashes the archive in memory before writing (a mismatch leaves the cache untouched), from the **versioned** URL, never the `rclone-current-…` alias, which moves. That defends against a truncated transfer, a proxy or a stale cache, not against a compromised rclone.org. `rclone_for(plat)` keeps the old lookup chain (checkout, next to the exe, PATH, cache) for **this** host so offline provisioning still works.

`install/descarga.py` is what both downloaders share, and what a third (a VeraCrypt one) should use: `con_reintentos()` retries **only** what another attempt might not have (timeouts, resets, `IncompleteRead`, 5xx/408/429) three times with growing waits (`ESPERAS`, via the indirection point `esperar()`); never a 404, a certificate that fails verification, or a **hash mismatch**: `fetch()` returns the whole body or raises, so a complete file that is not the published one is something else answering, and retrying until one matches is how not to notice.

**Placing it by hand means the official ZIP, not the binary** (rclone publishes sums of zips): `rclone_bin.a_mano()`/`runtime_bin.a_mano()` name the exact files and folder (`rclone_bin.zip_a_mano()`); `adoptar_zip()`/`adoptar()` verify it like a download and only then extract/record its sum; `descarga.sumas()` reads a `SHA256SUMS` left beside it **before** the network (that makes it work offline, and it defends against exactly what the network copy does, since both come from the same server). A hand-placed file that does not match is reported and **not** downloaded over. A loose binary is still accepted only for this host, and still unstamped.
