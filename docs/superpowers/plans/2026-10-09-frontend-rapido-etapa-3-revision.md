# Adversarial review of `plan-etapa-3.md` against the code

Tree: branch `claude/adoring-pascal-5j258r`. The review started at `ae93325`; stage 2 Tasks 11 and 12
were merged during it (`992f108`, `4543359`), so **code line numbers below are at `992f108`** (the plan's
are "at 1e339b9"; both are given where they differ). Plan line numbers refer to
`$SCRATCH/e3/plan-etapa-3.md` as delivered (406 lines).

**Verified true (no action):**
- Agent window: 16 widgets, broken down exactly as the plan says (`ui/tk_agente.py:73-108`); the new layout's arithmetic (Visor 4 + 7 = 11) holds.
- `Visor` details (`ui/tk.py:180-427`): `rowconfigure(1, minsize=self.horizontal.winfo_reqheight())` at :232, `_mover` and `_revisar` touch `self.horizontal`. The only external readers of `visor.horizontal` are `tests/test_tk_medidas.py:230,1037` and `tests/test_tk_servicio.py:644` (it was :605 before Task 11 merged). Nothing in `tests/rendimiento/` reads it.
- `pintar_ficha`/`reservar()` (`ui/tk_fleet.py:295-339`, one card painted and one `update_idletasks()` per device); `Tabla` signature with `alto_fila` and `_pintar` (`ui/tk.py:877-1036`); `flags_form` uses `Tabla` and `avisar()` rebuilds the red notice (`ui/tk_pairs.py:2239-2254`).
- The wizard claims: `_paso_destino.mostrar` sets `wiz.state.device = None` (`ui/tk_install.py:870-882`), `volume_for` calls `list_volumes` (`install/device.py:388`), `_filas_python` runs on the Tk thread (`ui/tk_install.py:729,737-746`), `publish_fleet_note` runs in the click (`:1571`, `ui/tk_equipo.py:757`), the verification is synchronous (`ui/tk_install.py:1839-1860`), and the probe is in `refrescar_espera` (`ui/tk_crypto.py:305-338`, `install/crypto.py:469-503`).
- `check_python()` imports `tkinter` in its own process (`install/device.py:648-653`). `--check`/`--probe` end in `report()`, which with `sys.stdout is None` opens a Tk window and runs `mainloop()` (`prdrive-install.py:73-103`), so D3's reason is real. `deploy.DEPLOY_FILES/DEPLOY_TREES`, `install.agente.CODIGO_FICHEROS`, `icons.svg_disponible`, `icons.PINTADAS` and `install.bundle_dir` all exist.
- The PyInstaller facts match the architect's PyPI dump (`sondas/pyinstaller.json`): 6.22.3 was uploaded 2026-09-12, needs `<3.16,>=3.8`, the `win_amd64` sha256 starts `500bd58c…`, and the dependency list is the same. The changelog (`sondas/changes.html`) has 6.15.0 «Add Python 3.14 support» and 6.22.0 «Tcl/Tk 9 builds with embedded data archives». So the pin is justified (see m14 for one wording caveat).
- 0.7.1 (`$SCRATCH/mainsrc`) has everything Task 1's `flota` and `wizard` flows need: «Dispositivos…» in «Parejas» (`ui/tk_pairs.py:1103`), `dlg.sondeo`/`dlg.tabla` on the fleet dialog, `Sondeo._encargo`/`_mirar`, «Mostrar»/«Editar flags…», «¿Dónde?» as step 1, and `fleet.leer(raw_local=None)`. `Dispositivo` fields are at `common/fleet.py:152-159`.
- `tests.yml` fills `runtime-windows-x64-<clave>` on push to `main` (`.github/workflows/tests.yml:17-22,60-91`), so the release job on `main` can restore that cache.

**Probes run by the reviewer** (`$SCRATCH/e3/revision-plan/sonda_*.py`, under xvfb, on Tk 8.6.14 and 9.0.4):
- `sonda_req.py`: a `ttk.Label` with `wraplength` reports its new `winfo_reqwidth/reqheight` **immediately after `configure(text=…)`**, with no idle pass (8.6: 36×20 → 197×128; 9.0: 32×18 → 202×98). A parent frame's `winfo_reqheight()` is **not** updated until an idle pass (20 → 128 only after `update_idletasks`). This answers Task 3 Step 1 in advance, and it bears on D5 (M5).
- `sonda_barras.py`: with `theme.apply()`, a vertical scrollbar's width equals a horizontal one's height at scaling 1.0, 1.333 and 2.0 on both Tks (8.6: 14/14; 9.0: 11/11, 15/15, 21/21). Task 2's reserved strip is therefore pixel-identical.
- `sonda_after.py`: right after a step frame is destroyed, `after info` still lists a destroyed progressbar's tick and an `after` registered on a destroyed entry. Both are gone one tick later, and the entry's callback never runs. A bare `after info` check straight after a step change is therefore not a clean signal (m9). An `after` hung on the **root** does run against dead widgets (m8).

---

## BLOCKER

### B1. Task 6: the release workflow is meant to stay wired to an unverified build even when that build fails
- **Plan:** Step 4, line 302 («If PyInstaller fails…, the release workflow stays gated (it fails closed…)»); Open risk 4, line 371; line 289.
- **Code:** `.github/workflows/build-installer-release.yml` publishes only from a `main` push that touches `VERSION`. «Create GitHub release» is the step that creates the tag. `common/update.py` finds new versions through `/releases/latest` and downloads the **tag's source zip** (`updating.md` «VERSION»).
- **What goes wrong:**
  - If PBS 3.14.8 with PyInstaller 6.22.3 cannot collect Tcl/Tk 9 on the Windows runner, or `--autoprueba` fails for a runner reason, the plan leaves `build-installer-release.yml` pointing at that failing path.
  - The spec says every stage ships as a PR with its version. So the owner's merge of this stage, with its `VERSION` bump, would fail in the release job. No tag and no release would be created, and **no device would be offered stage 1–3 through «Buscar actualizaciones»**: the code update channel is blocked by an installer build problem.
  - "Fails closed" is right for the `.exe`. It is wrong for the release as a whole, which today also carries the device code.
- **Correction (Task 6):**
  - Split the commit.
    - **6a** carries everything except `build-installer-release.yml`: the composite action, `instalador.yml`, `--autoprueba`, `check_python`, the build checks, the docs and the tests.
    - **6b** carries the release-workflow hunk alone. It is committed only after an `Instalador` run on the branch push is green, with `python` 3.14.8, `tk` 9.0.4, `svg` true and exit 0.
  - If that run is red, 6b is **not** committed. `build-installer-release.yml` stays as at B1, the run's link and log go in the report, and the finding becomes an owner question in the morning summary.
  - Add to Review Focus 3: «the release workflow is only rewired after a green `Instalador` run; a red one leaves it untouched».

---

## MAJOR

### M1. Task 6: `comprobar_tk()` and the PyInstaller pin refuse every local build, including the owner's turnkey `.exe` and any Linux build
- **Plan:** lines 280-281, 290, 297; Review Focus 3.
- **Code:**
  - `docs/guia/instalacion.md:137-151` documents `pip install pyinstaller` then `python build_installer.py` on any Python, with the **turnkey** variant that embeds `prdrive-profile.toml` + `keys/`. Those files are gitignored, so that variant can only be built on the owner's machine (`provisioning.md` «The PyInstaller build»).
  - `build_installer.py:244-282` also builds on Linux.
  - Stock Python 3.11–3.14 from python.org ships Tk 8.6 on Windows. The PyInstaller changelog itself names python.org **3.15.0b3** as the first build with embedded Tk 9 data.
  - The PBS Linux runtime is out too: `_runtime_ci compilador` refuses Linux by design.
- **What goes wrong:**
  - The morning after, `python build_installer.py` refuses on the owner's usual Python. It refuses on Tk 8.6, and on any PyInstaller other than 6.22.3.
  - The only working recipe is the CI's: an unpruned PBS 3.14.8, `ensurepip`, `pip install pyinstaller==6.22.3`. The plan documents it only in the user guide, pointing at a `tests/` helper.
  - On Linux there is no supported path at all.
  - The spec asks that `build_installer.py` *comprueba* Tk ≥ 9 for the release `.exe`, not that local builds be forbidden.
- **Correction (Task 6):**
  - `comprobar_tk(estricto: bool)` and `comprobar_pyinstaller(estricto: bool)`. They are strict when `GITHUB_ACTIONS` is set or `--estricto` is passed: the composite action passes it. In strict mode they raise `SystemExit` as planned.
  - Otherwise they print a clear warning and carry on. Proposed text: «Este Python trae Tk 8.6: el .exe pintará con el pintor de Python, más lento; el de las releases se compila con el Python fijado (3.14.8, Tk 9)» / «PyInstaller X.Y.Z en vez del fijado 6.22.3».
  - The release is still protected by strict mode plus `--autoprueba`.
  - `tests/test_build_installer.py` covers both modes.
  - The guide gives the PBS recipe as an option, and keeps `pip install pyinstaller==6.22.3` as the documented line.
  - Whether to make local builds strict later is an owner question (D4b below).

### M2. Task 5: a container examination that depends on two fields is checked against one, so a stale result can enable «Crear y montar» over a non-empty Linux folder
- **Plan:** line 250 («one pending `after` per field… a `Sondeo` per field… applied only if the field still holds the text examined»).
- **Code:**
  - `ui/tk_equipo.py:471-489`: `revisar()` examines `re_.examinar_contenedor(wiz.equipo_fisica, wiz.equipo_ruta, forma)`, and on Linux also `re_.examinar(wiz.equipo_ruta)` for the mount point. Both the «Contenedor en» box (`caja`, :543) and the «Se abre en» box (`punto`, :545 → `revisar_punto` → `revisar(fisica.get())`) feed it.
  - `crear()` (:499-537) trusts `estado["examen"]` and runs `re_.abrir_o_crear(vc, wiz.equipo_fisica, wiz.equipo_ruta, …)`.
  - `install/raiz_equipo.py:672-703` does **not** re-check that the mount point is empty. The examination is the only guard for «la carpeta… tiene que estar vacía: lo que hubiera quedaría tapado» (`raiz_equipo.py:606-614`).
- **What goes wrong:**
  - An examination of `fisica=A` with `punto=P1` lands after the user typed `punto=P2`, a non-empty folder. `caja` still holds `A`, so a per-field check passes.
  - «Crear y montar» is re-enabled on an examination of P1. The container mounts over P2 and hides its contents.
  - With two Sondeos, two arrivals can also apply in either order.
- **Correction (Task 5 Interfaces):**
  - The examination of the container step is **one** debounced task with **one** `Sondeo`, keyed by the tuple `(fisica, equipo_ruta, forma)` read when the timer fires. Either box re-arms it.
  - An arrival applies only if `(caja.get(), punto.get() or equipo_ruta, forma)` still equals that tuple.
  - `crear()` refuses (returns silently) unless `estado["examen"]` was made for the current tuple. That is defence in depth, since `abrir_o_crear` does not re-check.
  - The same tuple rule applies to `paso_carpeta`, with `(ruta, forma)`.
  - New test «el examen del contenedor con otro punto de montaje no cuenta»: an `Encargo` released by hand for `(A, P1)` after `punto` changed to `P2` leaves «Crear y montar» disabled and `estado["examen"]` unchanged.

### M3. Task 5: the 8 MiB write probe can run twice, against the plan's own «una vez»
- **Plan:** line 249 (`lanzar_sin_repetir(("sonda", str(estado.device)), None, …)`); Step 1, line 256.
- **Code:**
  - `ui/segundo_plano.py:130-136`: `lanzar_sin_repetir` reuses only a live encargo (`not vivo[1].hecho`) younger than `VIDA_MAXIMA` (120 s).
  - `ui/tk_crypto.py:321-324`: today the "measured once" rule is `estado.velocidad_escritura is None`, and `refrescar_espera` is a `tam.trace_add("write")` callback (:337).
  - The panel is rebuilt by `wiz.repintar()` (:174, :192, :409).
- **What goes wrong:** a second probe writes to the user's drive in three cases.
  1. The probe finishes and `hecho` turns true. A size keystroke comes before the panel's `Sondeo` polls (≤ `SONDEO_MS`), so `velocidad_escritura` is still `None`.
  2. The panel is repainted while the probe runs. The `Sondeo` dies, the arrival is dropped, and the next `refrescar_espera` after the thread ends finds `velocidad_escritura is None` and no live encargo.
  3. The probe takes more than 120 s on a dying stick.
- **Correction (Task 5):**
  - Keep the probe's `Encargo` in the wizard state, beside `velocidad_escritura`. It is one new `InstallState` field, or a `wiz` attribute documented in the class docstring.
  - `refrescar_espera`:
    - a done encargo gives its result (`or 0.0`) with no relaunch;
    - a pending one is waited on;
    - a new probe is launched only when there is none for this `estado.device`.
  - Use `segundo_plano.lanzar`, not `lanzar_sin_repetir`.
  - Tests:
    - «una sola sonda aunque el hilo acabe antes de mirarlo»: an `Encargo` marked `hecho` by hand, then five size writes, gives one recorded call and the division uses its result;
    - «una sola sonda aunque se repinte el panel»: a repaint while pending, then release, then re-entering the panel gives one call and the result is shown.
  - While a probe is pending, «Crear y montar» is off whatever the «dinámico» box says, because the probe writes beside the container. If the probe has not answered after `TOPE_SONDA_S` (say 60 s), `espera` says «no se ha podido medir» and the button comes back on; a later arrival is still stored.

### M4. Task 4: a pending «Usar esta ruta» can override a newer choice, and «Siguiente» stays on with the previous device while it resolves
- **Plan:** lines 222-223; Review Focus 1, line 107.
- **Code:**
  - `ui/tk_install.py:911-927`: `usar_ruta()` checks `destino.is_dir()` on the Tk thread, then `device.volume_for(destino)`, then sets `wiz.state.device`.
  - `_ok_destino` (`:1974-1985`) reads only `wiz.state.device`.
  - The plan's only arrival guard is "if the text is still the one asked about".
- **What goes wrong:**
  - The user picks volume **Y** in the tree, then types a path **P** and presses «Usar esta ruta». `volume_for(P)` runs in the thread.
  - The user then clicks row **Z**. The entry still says P, so the arrival applies P and silently replaces Z. The chip flips to «Destino: P».
  - If the user presses «Siguiente» before the arrival, they proceed with Y while believing they chose P.
  - Either way «Siguiente» can act on a choice that is not the latest. That is Review Focus 1's own rule, applied to the step that decides **which drive gets written**.
  - `destino.is_dir()` on an unreachable UNC path (`\\servidor\x`) also blocks the Tk thread for the SMB timeout.
- **Correction (Task 4 Interfaces):**
  - Keep a step-local `turno` counter, bumped by every user choice: tree selection, «Usar esta ruta» and «Actualizar lista». A thread result applies only if its `turno` is still the current one.
  - Pressing «Usar esta ruta» sets `wiz.state.device = None` («Siguiente» off) and shows the chip «Comprobando la ruta…» until the result lands or is superseded.
  - `is_dir()` moves into the threaded function together with `volume_for`.
  - The «Siguiente»-off-while-reading mechanism for the list itself needs no new `Wizard` attribute:
    - at paint, keep `previa = wiz.state.device` in the step and set `wiz.state.device = None`;
    - on arrival, select `previa` if it is listed and call `mostrar()`;
    - if a hand path won meanwhile, leave it as the plan says.
  - Tests (Step 1): «una ruta a mano que llega tarde no pisa la fila elegida después»; «Siguiente» is disabled between «Usar esta ruta» and its arrival.

### M5. D5 / visual change 5: the fixed-row card is a visible change the spec does not ask for, and its rationale does not hold
- **Plan:** line 77 (visual change 5), lines 193-195, D5 at line 387.
- **Code and evidence:**
  - Today the rows flow: a one-line «Estado» moves «Equipos» up (`ui/tk_fleet.py:307-323`).
  - The spec's «etiquetas fijas que cambian con `configure`» (§2, «Dispositivos») is about not building widgets, not about layout. «Fuera de alcance» excludes «cambios de aspecto».
  - `sonda_req.py` shows label sizes are synchronous after `configure` on both Tks. Reserving the card's height for flowing rows is therefore a sum over each device's lines of `max(reqheight + pady)` per grid row. That costs no idle pass and creates no widget. It is not "reimplementing grid's arithmetic": the width arithmetic is the same in both designs.
- **What goes wrong:** the owner wakes to a visible layout change in «Dispositivos» that was decided only to make reservation easier.
- **Correction:**
  - D5 becomes **owner question**, with the default **flowing rows, no visible change**:
    - the fixed set of labels is re-gridded (`grid(row=…)`) per device;
    - unused labels are `grid_remove`d;
    - `reservar()` sets `hueco`'s row and column `minsize`, as today, from the arithmetic above on label sizes read synchronously;
    - Task 3 Step 1 keeps the probe only as a Windows confirmation.
  - Remove visual change 5 from the allowed list.
  - The `leer_vista` equality test in Step 2 works unchanged: cells are per device.

### M6. Task 4 and 5: the «Verificación» bound "≤ 6 + 4 per check row" is wrong for the drive route, so Step 2 cannot pass as written
- **Plan:** lines 45, 230, 236, 252; Open risk 2 / D2.
- **Code:**
  - Drive route, `ui/tk_install.py:1826-1961`: `_texto` 1 + `tabla` 1 + the new `Indicador` (3: `marco`, `barra`, `texto`, `ui/tk.py:1573-1584`) + `tabla_estado`'s card 1 + rótulo «Y ya que estamos» 1 + `extras` 1 + 5 buttons = **13 fixed**. Each row then adds 3 (`theme.chip` is one label) plus a separator from the second row on (`ui/tk.py:800-829`). Total **12 + 4n**.
  - Host route, `ui/tk_equipo.py:1091-1116` plus the Indicador: 7 fixed, total **6 + 4n**. The plan's figure fits only this route.
- **What goes wrong:** the drive-route assertion fails for any n. A builder trying to meet it would drop visible widgets (the «Y ya que estamos» buttons, the rótulo), which is a look change.
- **Correction:** state the bound as «fixed part + 4 per row − 1». The fixed part is ≤ 13 on the drive route and ≤ 7 on the host route, both counting the `Indicador`. The test asserts that adding one check row adds exactly 4 widgets, and prints both fixed parts. The budget map row (line 45) and Open risk 2 are corrected accordingly.

---

## MINOR

1. **Task 6: no per-step time limit inside a composite action** (line 287 «Each step with a time limit»). Composite steps take `name/id/if/run/shell/uses/with/env/working-directory/continue-on-error`; `timeout-minutes` is a job-step key (please confirm against the runner docs). *Correction:* put `timeout-minutes` on the `uses: ./.github/actions/compilar-instalador` step in both workflows. Inside the action, the gate uses `$p = Start-Process … -PassThru; if (-not $p.WaitForExit(180000)) { Stop-Process $p -Force; exit 1 }` instead of `-Wait`.
2. **Task 6: the release-only glue is untested before a `VERSION` push** (Open risk 5). *Correction:* the action exposes `exe`. `build-installer-release.yml` uses that output instead of re-globbing `dist/`, and `instalador.yml` asserts the same output, so only `gh release create` is untested.
3. **Task 6: the supply chain of the job that holds `contents: write`.** `actions/checkout@v4` persists the token in `.git/config` (`build-installer-release.yml`, Checkout step). After the change, freshly pip-installed packages run in that job: `pyinstaller-hooks-contrib`, `pefile`, `altgraph`, `packaging`, `setuptools` float (Open risk 6). *Correction:*
   - add `persist-credentials: false` to that checkout (the tag check needs no auth; `gh` gets `GH_TOKEN` explicitly);
   - either pin the dependencies in a hashed `requirements` file next to the action, or record it as an owner question.
4. **Task 6: the Windows Store `python` alias.** `install/__init__.py:146-150` returns the first `shutil.which("python")`. On stock Windows 10/11 that is `…\WindowsApps\python.exe`, which answers rc 9009 and "Python was not found…". *Correction:* `check_python()` treats "no JSON answer" (rc ≠ 0, 124, 127, garbage) like "no Python": `ok` false with `root`, true without. The detail names the Store alias when rc is 9009 or the path is under `WindowsApps`. A test fakes rc 9009.
5. **Task 6: `check_python` is said to keep its «ok rules» but adds one** (line 284: «keeps its signature, labels and `ok` rules» vs «< 3.11 … with `root`, makes `ok` false»). The new rule is reasonable, since the light install needs `tomllib`, but it is outside the spec's §4 text. *Correction:* say plainly that it is a new rule, document it in `provisioning.md`, and list it in the PR's behaviour changes.
6. **Task 6: `--autoprueba` details.**
   - (a) Hide it from `--help` (`help=argparse.SUPPRESS`, like `--esperar`).
   - (b) Do not call `theme.apply(root)` separately from `tk_install.build(root)`, which applies the theme itself (`ui/tk_install.py:308`). Read `tema` from `build()` succeeding, or use a fresh `Tk()` for each.
   - (c) The `modulos` constant will drift from the code. Add a case to `tests/test_autoprueba.py` that greps the function-level `from . import X`/`from ui import X` in `tk_install.py`, `tk_crypto.py` and `tk_equipo.py` and asserts each is in the constant, like `test_imports_perezosos.importados_tarde()`.
7. **Task 6: `instalador.yml` on every PR touching `ui/**` or `common/**`** (line 288) adds roughly 6–10 Windows-runner minutes per PR. The spec asks only that the release flow test the `.exe`. *Correction:* keep `push` (TEMPORAL) and `workflow_dispatch`; restrict `pull_request` to the build's own paths (`build_installer.py`, `prdrive-install.py`, `install/**`, `common/pins.py`, `tests/_runtime_ci.py`, the action, the workflow). Broadening it is an owner question.
8. **Task 5: debounce timers and step changes** (line 250). `Wizard.repintar()` destroys the step (`ui/tk_install.py:187-196`). An `after` hung on the root, which is what "wrap `ventana.after`" suggests, still fires against dead widgets (`sonda_after.py`). *Correction:* hang each debounce `after` on its own entry, so Tk drops it silently with the widget, or cancel it on the entry's `<Destroy>`. Add to Step 2: «un cambio de paso con una tecla pendiente no examina nada ni da error» (the recorder sees no call).
9. **Task 4 Step 1: "no pending `after` of that step (`after info`)" is a noisy signal** (line 235). Straight after `repintar()`, `after info` still lists the destroyed progressbar's tick (`sonda_after.py`). *Correction:* assert that the step's `Sondeo` has no pending id (`_id is None` and `not esperando`) and that no recorded arrival callback runs after releasing the `Encargo`. Do not count `after info`.
10. **Task 5: the host «Parejas» claim** (line 73, visual change 1; line 375). `ok_parejas` is `wiz.state.config_written` (`ui/tk_equipo.py:771-773`), so the debounce does not change «Siguiente» there, and `guardar()` re-validates synchronously (:737-743). *Correction:* the debounce on host «Parejas» only changes the line under each field; «Siguiente» gating there is unchanged. Also add "«Examinar…» launches its examination at once, without debounce", as at first paint (`:310-316`).
11. **Task 3 Step 2's constancy assertion cannot hold before Task 7** (line 204). `tk.Tabla` still adds about 7 widgets per row in Task 3 (`ui/tk.py:948-1000`; the plan's own Task 3 budget says so). *Correction:* «the dialog's widget count **minus `dlg.tabla.marco`'s descendants** is the same with 3 and 25 devices». Task 7 Step 3 then asserts the whole count.
12. **Task 4: `Desmontar el contenedor` while the verification thread reads the container.** `ui/tk_install.py:1938-1949`; `crypto.dismount` has no force (`install/crypto.py:1365-1377`). *Correction:* while the verification read is pending, «Desmontar el contenedor» is off along with «Volver a comprobar». «Llevar VeraCrypt…» may stay on: its own re-verify supersedes the pending one through the single `Sondeo`.
13. **Budget map line 46 overstates "Wizard reads on the Tk thread: none".** What remains on selection or paint:
    - `install_target()` in `revisar_desvio` (`ui/tk_install.py:884-898,945-952`);
    - `Matriz.para()` and free space in «Instalación»/«Plataformas»;
    - `_paso_cifrado`'s detection;
    - in the VeraCrypt panel, `creacion_dispersa`/`sistema_de_ficheros`/`restos_en_claro`/`_libre` (`ui/tk_crypto.py:199-235`);
    - in `_carpeta_cifrada`, `disk_usage`, `creacion_dispersa` and `letras_libres` (`ui/tk_equipo.py:393-418`).

    These are small reads outside the spec's R4 list. *Correction:* change the cell to «the spec's list: none (small reads on the chosen volume remain: …)», so the results file does not claim more than is true.
14. **Task 6: docstring and claim accuracy.**
    - (a) `PYINSTALLER`'s docstring should not imply that 6.22.0's "embedded data archives" feature is what makes the PBS build work. The changelog cites python.org 3.15.0b3, and whether PBS 3.14.8 for Windows embeds its Tcl library is unknown. The pin rests on "≥ 6.22 per the spec, latest patch, verified by `Instalador`".
    - (b) `_runtime_ci compilador`'s reason (line 286, "a Linux runtime has no shared `libpython`") is wrong. The PBS Linux archive does carry `libpython*.so`, which `podar()` removes (`install/runtime_bin.py:106`). The real reason is "the release `.exe` is Windows-only".
15. **Global Constraints, line 67, misses the files of stage 2 Task 15.** Task 15 owns `tests/rendimiento/*` and `presupuesto.toml` (stage 2 plan, Task 15). Task 1 (Wave 1) edits `driver.py`, `correr.py`, `informe.py` and `presupuesto.toml`. *Correction:* list them, and carve out the exception: «Task 1 adds keys and flows only. Task 15 deletes `etapa2_*.py` and edits existing `[techo]` values. Whoever merges second rebases textually.» Keep it in the hot-spot list.
16. **Visual change 3 (hover in the fleet table) is not asked for** (line 75). Today's `Tabla` has none, and «mismo aspecto» applies. *Correction:* the default for `Tabla` is no hover. Add it to the owner questions, since «Parejas» has it through Task 14.
17. **D1: invisible trims are available and not taken.** Folding `cabecera`'s frame and `donde` into `arriba`'s grid, `hueco` into `marco`'s grid, and `acciones` + `cierre` into one footer saves 3–5 widgets with no pixel change (`ui/tk_fleet.py:246-264,282-289,443-461`). *Correction:* Task 3 takes the trims that stay pixel-identical (Step 2 parity in the report). That leaves only the «Equipos» block as the owner question. Expected after Task 7: ~37–38 + dates.
18. **The spec's open-window table has «Elegir otra … fila ≤ 16 ms» and the stage changes how a «Dispositivos» row is chosen, but nothing measures it.** *Correction:* Task 1 adds `elegir-dispositivo` to the `flota` flow (`fdlg.tabla.elegir(otra)` + `fdlg.update()`, after `llega-flota`), with `[meta_ms]` 16. 0.7.1 has the same API.

## NIT

1. **Merge-order rationale** (line 92): «the timing check last, so its local A/B ran against everything» is false. Task 1 is built on B1 in parallel. *Correction:* «the merger re-runs Task 1's Step 2 once on B1′ before Wave 2».
2. **Task 7 Step 2** (line 341): «after updating for 100 ms» is a timed wait the Global Constraints forbid. *Correction:* assert that no `after` belonging to the table is pending after the first `update_idletasks()`, and that its items are unchanged after one more `update()`.
3. **`comprobaciones_dispositivo` in `ui/tk_install.py`** (line 226) is a disk-touching helper in a `tk_*` module. That is acceptable only on the `tk_equipo.comprobaciones` precedent the Global Constraints cite. Say so, or move it to `install/device.py` in Wave 2.
4. **Task 4 «Comprobaciones»:** wrap `device.check_python()` in `trabajo()` so that a failure becomes a «sin comprobar» row instead of failing the whole remote check.
5. **Task 5 line 250:** «their `escribir()` helper… runs `entrada.update()`» reads as existing behaviour. Today it does not (`tests/test_install_wizard.py:1018-1021`). Say «Task 5 makes it run».
6. **Proportion.** The plan is mostly decision-level and the right length. It over-specifies mechanics that turn out unimplementable or wrong: per-step timeouts in a composite action, the exact `Start-Process -Wait` gate, and the «Verificación» formula. It under-specifies the three decisions builders cannot make alone: the input tuple an arrival is checked against (M2), where the «Siguiente»-off state lives (M4), and where the probe's `Encargo` lives (M3). The «Inputs» and «Budget map» sections are useful provenance; no transcript-like code blocks.

---

## Review Focus: the five most likely real-world failures, and whether a task owns them

| # | Failure | Owned? |
|---|---|---|
| 1 | The PBS + PyInstaller 6.22.3 `.exe` fails the gate on the runner, and the release (with the device update) is blocked | Not as written: B1 |
| 2 | The owner cannot build his turnkey `.exe` locally (Tk 8.6 / other PyInstaller) | No: M1 |
| 3 | A stale container examination enables «Crear y montar» over a non-empty Linux mount point | No: M2 |
| 4 | A second 8 MiB probe on the user's stick | No: M3 |
| 5 | A late «Usar esta ruta» replaces a newer drive choice, or «Siguiente» proceeds with the old one | Partly (only "text unchanged"): M4 |

Runner-up: the Windows Store `python` alias reported as a working Python (m4). *Correction:* add items 3–5 to Review Focus 1 with their test names, and B1's rule to Review Focus 3.

---

## Owner decisions D1–D5

| | Can it be taken now? | Safe default |
|---|---|---|
| **D1** («Dispositivos» misses ≤ 35) | **Yes.** Keeping the look is the spec's rule. Report the miss in the results. | Keep the look and take the invisible trims (m17). The visible «Equipos» alternative is the owner question. |
| **D2** («Verificación» over 40) | **Yes.** The spec itself keeps `tabla_estado()` in ttk (R3), so R5 and R3 conflict inside the spec. | Keep it in ttk, with the corrected bound (M6). |
| **D3** (`--autoprueba` instead of `--probe`) | **Yes.** Internal, and `--probe` cannot run windowed in CI. | Adopt, hidden from `--help` (m6a). |
| **D4** (build with the unpruned PBS runtime) | **The CI half: yes.** Internal, and verified by `Instalador`. **The release wiring: only after a green run** (B1). **Strict local refusal: no** (M1). | CI and release build on PBS 3.14.8; release wiring gated on green; local builds warn. New **D4b** for the owner: «¿compilar en local también exige Tk 9 y PyInstaller 6.22.3?». |
| **D5** (fixed card rows) | **No.** A visible change the spec does not ask for, and avoidable (M5). | Flowing rows with the reserve computed from synchronous label sizes; ask the owner whether he wants fixed rows. |

Add as owner questions too: hover in the fleet table (m16); the PR trigger breadth of `instalador.yml` (m7); hashed build dependencies (m3).

---

## Verdict

- **Can start as written, with these corrections:**
  - **Task 1:** m15, m18, n1.
  - **Task 2:** none needed; its claims were verified, including scrollbar thickness on both Tks.
  - **Task 3:** M5 (flowing rows), m11, m17.
  - **Task 7:** n2, m16; Wave 2, unchanged dependency on stage 2 Task 14.
- **Rework before dispatch:**
  - **Task 4:** M4, M6, m9, m12, m13, n4.
  - **Task 5:** M2, M3, m8, m10, n5.

  The fixes are interface-level, so the same builders can take them once the corrections are in the plan.
- **Task 6:**
  - 6a (`check_python`, the build checks in warn/strict form, `--autoprueba`, the composite action, `instalador.yml`, docs, tests) can be built now with M1, m1–m7 and m14.
  - **6b, the `build-installer-release.yml` rewiring, waits for a green `Instalador` run on the branch.** If that run is red, it waits for the owner (B1).
  - D4b, whether local builds must be strict, is the owner's.
- **Wave 1 parallelism is sound** once m15 is written into the constraints. No two Wave 1 tasks share a source file. Shared test and doc files are section-disjoint and listed as hot spots. No Wave 1 task touches `ui/theme.py`, `ui/icons.py`, `ui/tk_pairs.py`, `ui/tk_tabla.py` or `AGENTS.md`. `penwatch.py` and `runsync.py` are untouched by every task. No `install/` change imports `ui/`. No new ttk style appears after the first widget: the lazy horizontal scrollbar uses `Horizontal.TScrollbar`, configured in `apply()`.
