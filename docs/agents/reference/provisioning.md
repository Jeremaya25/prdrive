# Provisioning a device and the build (`prdrive-install.py` + `install/` + `ui/tk_install.py`)

Formerly AGENTS.md «Provisioning a device» (general part), «The PyInstaller build».
VeraCrypt → `veracrypt.md`; the vestibule → `vestibule.md`; updating an installed device → `updating.md`; the agent's install → `agent.md`.

## The steps

The order is load-bearing: you cannot read the catalogue before knowing the remote, pick pairs before knowing where the device goes, or initialise them before the `sync.py` that does so exists.

```
1 Dispositivo     which volume + the "already a prdrive" shortcut
2 Cifrado         VeraCrypt / BitLocker / none  → fixes state.device_root
3 Conexión        form, or import a remote from the user's rclone.conf
4 Comprobaciones  rclone + connect + read the catalogue
5 Instalación     full/light + platform list; copy .prdrive/, hide it, rclone +
                  runtime per platform, launchers, rclone.conf + keys
6 Parejas         pick from the catalogue, write sync_config.toml, make dirs,
                  publish the device's note in the fleet registry
7 Llavero         optional: none, a base of one's own, or the remote's
                  (KeePassXC + [keychain] + .keychain/, `llavero.md`)
8 Inicialización  --resync of the bisync pairs (and the keychain's first pass)
9 Verificación
```

(The list starts with «¿Dónde?», unit or this host, which the step titles count too.)

Each step disables «Siguiente» until its condition is met. **No console fallback** (unlike `runsync.py`): this happens once in a device's life. Step 5 copies a folder of its own and touches nothing else, so it needs no `--dry-run` ceremony and runs straight through `ui.tk.working()`. With VeraCrypt `.prdrive/` lives *inside* the container, so the volume looks empty until mounted: detection re-runs at the end of `_paso_cifrado`.

## Nothing in the wizard spawns a shell

To a behavioural AV engine an unsigned `.exe` in `%TEMP%` spawning `powershell.exe` is the shape of a dropper. Windows is asked directly instead:

- BitLocker state (now `common/bitlocker.py`, re-exported by `install/crypto.py`, so the device can ask it too: `common/cifrada.py`) through `IShellItem2::GetInt32` with a PROPERTYKEY from `PSGetPropertyKeyFromName` (**never** a remembered one). Only state `On` counts as protected: *Waiting for activation* must fail, or the private key lands on a volume whose key is still in the clear.
- The volume list through kernel32, needing `SetThreadErrorMode(SEM_FAILCRITICALERRORS)` (an empty card reader otherwise pops a "no disk" modal) and `TIPOS_OCULTOS` (`GetLogicalDrives` returns mapped network drives).
- There is **no recovery-key feature**: reading one needs elevation.

## The «already a prdrive» shortcut

On `device.install_target() == YA_INSTALADO` step 1 shows the device's version vs the installer's and offers **«Actualizar»**, **«Añadir plataformas…»** and **«Reinstalar desde cero»**. Reinstall is **always** offered, so re-provisioning (new remote, re-encrypt, redo pairs) never needs deleting `.prdrive/` by hand.

- `Wizard.pasos` is an **instance** attribute: three step lists (`PASOS_INSTALACION`, `PASOS_ACTUALIZACION`, `PASOS_PLATAFORMAS`); the button picks one and sets the index. `_ok_destino` stays False until a way out is chosen.
- `install_target()` looks for the **device before the content** (`.prdrive` is in `RUIDO`), or a freshly provisioned volume reads as `VACIO` and the shortcut is missing on the newest device that can exist.
- The short path installs the tree the **installer carries** (`bundle_dir()`, the source step 5 uses): no network. It calls `ensure_control_file(renew=False)`: step 5 renews because it provisions, but renewing here would strand a watcher bound to this device's id. Going back in version is allowed, never silent (`_confirmar_retroceso()`).

## Connection (step 3)

- **`Conexión` is what makes the repo publishable**: `profile.load()` returns an **empty** profile when nothing is embedded and nothing is in the checkout. Not an error: the normal start for a fresh clone. The private key goes to a temp dir recording the owning pid; `remote.sweep_stale()` cleans what hard-killed installers left, asking `store.pid_alive()` first.
- **«Usar esta conexión» talks to nobody** (#47): it turns the form into a `Profile`, so the step says «preparada, sin probar» in plain ink (no ✔, no green: those read as "connection tested"); the remote is first touched in «Comprobaciones».
  - `profile.py` checks locally, on both paths (form and import): a `type`, and `OBLIGATORIAS` = only what rclone marks `Required` with no way round (sftp `host` unless `ssh` is set: an empty host dials `:22`, this machine; webdav `url`; nothing for s3). Those block: the error goes in red in the step and the previous connection is dropped, so «Siguiente» is off.
  - `profile.avisos()` only warns (amber, still enabled): an sftp without `user` logs in as whoever runs rclone on each host. Whether the `type` exists is not checked: that needs rclone, which step 4 has.
- **The key never leaves the device**: `deploy.write_device_remote()` writes `.prdrive/rclone.conf` + `.prdrive/keys/<name>` with **relative** paths (`key_file = keys/…`), which is what makes the device work under any drive letter (rclone resolves them against `cwd = model.APP_DIR`).

## Platforms: the zero-install part

Step 5 and the «Plataformas» short path draw `_lista_plataformas()` over a `platforms.Matriz`: full/light, one checkbox per `pins.PLATAFORMAS` entry (Windows/Linux × x64/ARM64; macOS deliberately absent), per-row sizes and a live total vs free space.

- **Full** = rclone + a python-build-standalone runtime per platform in `.prdrive/runtime/<clave>/`; the root gets exactly `runsync.bat`, `runsync.sh`, `README.md` (a stale `runsync.pyw` is removed). **Light** = rclone only, plus `runsync.pyw` (useful only with a host Python). rclone stays in `bin/<arch>/` (`windows-x64` and `linux-x64` share `bin/x64`: `rclone.exe` vs `rclone`).
- **Deselecting a provisioned platform deletes only if confirmed** (`Matriz.quitar()` → `_preguntar_borrado()`); unconfirmed = left in place.
- **Downloads are pinned and verified** from `common/pins.py`. Python is **3.14** (3.14.8, release 20261001, since 08/10/2026): its builds ship Tcl/Tk 9.0.4 on all four platforms, so Windows and Linux run the same Tk (3.13 was Tk 8.6.15 on Windows and already 9.0.4 on Linux). Windows needs `DLLs/zlib1.dll` and `DLLs/libtommath.dll` (hard imports of `tcl90.dll`/`_tkinter.pyd`); `podar()` never touches `DLLs/`. Devices on 3.13.16 see the runtime as a pending component (`components.py` compares version and release). Windows on Tk 9 is covered by real-machine row **F20** (`tests/maquina/f20_tk9_windows.py`: the pinned runtime fetched by the installer itself, then the bundled font, capture protection #59 via `GetWindowDisplayAffinity` on Tk 9's `wm frame`, and the UI test scripts run with its interpreter): ok 16/16 on 08/10/2026. That VM has no interactive desktop: looks on a real Windows remain unchecked.
  - **Linux's Tk is built without Xft** (`…no-xft.x11` in its version string), on 3.13 and 3.14 alike: X11 core bitmap fonts only, no antialiasing, `ui/fuentes/` unusable. So the Linux runtimes carry **a Tk built with Xft beside the stock one**: `.github/workflows/tk-xft.yml` builds the same Tk (`pins.TK_XFT_VERSION`, 9.0.4) with `--enable-xft --disable-rpath` and SONAME `libtcl9tk9.0.so` on `manylinux_2_28` (x86_64, aarch64), checks the sources' SHA-256 and publishes a **prerelease** `tk-xft-<version>-<revision>` (prerelease + `--latest=false`, so `update.py`'s `/releases/latest` never sees it; an existing tag is never overwritten: bump `REVISION`). `pins.TK_XFT_SHA256` pins each package (not read from its own `SHA256SUMS`). Measured 08/10/2026: needs glibc ≥ 2.14 (x86_64) / 2.17 (aarch64) plus the host's `libXft`/`fontconfig`/`freetype`/`libX11`; 1.6 MiB.
    - `runtime_bin.ensure_runtime()` also calls `ensure_tk()`, which **never fails**: no network or a hash mismatch is said through `progreso` and the runtime ships with the stock Tk. `extract()` writes the package's two members (`TK_MIEMBROS`, nothing else accepted) to `lib/tk-xft/` when `tk_xft(plat)` finds it verified in the cache, and the stamp gets `tk = <tag>`; `stamp_text()` defaults to the same rule, so the expected stamp and the written one agree. `components.python_pendiente()` reports a Linux runtime without that line as pending (only if a hash is pinned for its arch), so devices get it from «Ajustes → Actualizaciones».
    - **Choosing at start-up:** `ui.tk_con_xft()` runs when `ui` is imported, before any `import tkinter`: on Linux, if `sys.prefix/lib/tk-xft/libtcl9tk9.0.so` exists, it `ctypes.CDLL(..., RTLD_GLOBAL)`s it; `_tkinter`'s `NEEDED libtcl9tk9.0.so` then matches that SONAME and the stock one is never mapped. Without `libXft` the load raises `OSError`, silently, and the stock Tk loads as before. Anything that imports `tkinter` before `ui` gets the stock one. `tests/test_tk_xft.py`.
  - **Tk 9.0.4 does not redraw on a DPI change**: no per-monitor DPI calls in its DLL, and its manifest declares system awareness, the same as `theme.nitidez()`. It does bring `ttk::entry -placeholder` and SVG photos.
  - **The UI is measured on both.** CI runs the **whole suite** twice, on Linux and Windows (job `tests-tk9` of `tests.yml`): with `setup-python` 3.11 (Tk 8.6) and with the pinned runtime's interpreter (3.14.8, Tk 9.0.4), fetched by `tests/_runtime_ci.py` with the installer's own `runtime_bin` before the suite. Locally the same: `xvfb-run -a <runtime>/bin/python3 tests/run_all.py`, or one script (`test_tk_medidas.py`, `test_tk_servicio.py`, `test_tk_densidad.py`, `test_daemon_aviso.py`). 03/10/2026, Linux runtime: measures and service pass whole; density fails the same 1-px Xvfb rounding it fails with Tk 8.6; the failure pop-up aborted the process (`service.md`). `rendimiento.yml` times the real windows on that runtime against `main` (`commands-testing.md` «Timing check»).
  - `runtime_bin.extract()` validates every member before writing the first, prunes pip/idle/tests/C headers (on Linux also `share/` and `libpython*.so`: the interpreter is static), never creates symlinks (exFAT) but materialises `bin/python3` by writing its target under that name, and writes the `PRDRIVE-RUNTIME` stamp **last** (no stamp = not installed).
- **Everything is fetched before the device is touched (#49).** `deploy.conseguir_plataformas(plan)` gets every rclone and runtime into the host cache, verified; only then `apply_platforms(…, conseguido=)` deletes and copies. Step 5 calls it **before** `deploy_code()`. It stops at the first platform that fails (each file was already retried three times; the rest would be minutes more behind a bare bar) and raises one `InstallError` that names it, says the device is untouched and that it can be unticked. `wiz.revisar()` in the error branch of step 5 and «Plataformas» keeps the button in view under that dozen-line message (`test_tk_medidas`).
- `deploy.install_runtime()` extracts beside and **swaps**; if the old dir can't be moved aside (Windows: a `pythonw.exe` running from it) it fails whole and the old runtime stays. `remove_platform()` renames before deleting for the same reason. **No self-built executables, no `.vbs`.**
- The `.bat` avoids parenthesised blocks (a `)` in the device path would break them), is written with CRLF, and uses `chcp 65001` only in the error branch.
- **Launchers are immutable after provisioning**: written by step 5 and by «Añadir plataformas…» (an old device has no `.bat`, so its runtimes would be useless), **never** by `--update`, «Actualización» or `deploy_code()` (`tests/test_install_deploy.py` guards it). The vestibule outside a VeraCrypt container follows the same rule.

## The PyInstaller build (`build_installer.py`)

Packs the tree the installer deploys (`sync.py`, `runsync.py`, `penwatch.py`, `common/`, `ui/` as `--add-data`) and optionally embeds a connection profile.

- `common/` and `ui/` are in the bundle **twice**: importable bytecode (the installer uses it) and copyable source (what lands on the device). PyInstaller cannot hand back the `.py` of a module it imported.
- **Without a profile** (a plain clone) the binary is generic and asks for the connection in `Conexión`; **with one** (`prdrive-profile.toml` + `keys/`) it is turnkey and must only be shared privately. That split is what lets the repo be public: `install/secret.py` is generated at build time, gitignored, deleted in a `finally`.
- **Frozen-only traps**: `sys.executable` is the installer, not Python (anything the wizard launches from the device goes through `deploy.device_python()`); `sys.stdout` can be None with `--windowed`.
- The `.exe` carries **no** runtimes or rclone: step 5 downloads them per platform (verified, cached in `%LOCALAPPDATA%/prdrive-install/`).
- **Windows on ARM.** Everything arch-dependent (`model.arch_dir()` for `bin/<arch>/`, `rclone_bin.os_arch()`/`cache_dir()`) hangs off `model.maquina_nativa_windows()`: Windows tells an emulated x64 process it is `AMD64`, and only `IsWow64Process2()` answers truthfully. Resolve on the **host**, never store it on the device. Emulated x64 runs but ARM on x64 does not, so fallbacks are one-way: `BIN_FALLBACK_DIRS`, and the runtime chain windows-arm64 → windows-x64 → host Python in `runsync.bat` (whose `%PROCESSOR_ARCHITECTURE%` *is* truthful), `platforms.candidates()` and `penwatch.runtime_keys_for()`. `tests/test_arch.py` fakes the probe.
