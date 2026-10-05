# Commands, verification and test conventions

Formerly AGENTS.md «Commands» (full list), its verification notes, and the registry of indirection points from «Conventions».

## Commands

```bash
python sync.py [pares...]      # every pair in sync_config.toml, or only these
python sync.py --list          # pairs + resolved endpoints (safe, read-only)
python sync.py --doctor        # bisync state: prefixes, filters, locks
python sync.py --dry-run       # simulate; MANDATORY before any *-mirror run
python sync.py --resync        # rebuild the bisync baseline
python sync.py -y/--yes        # auto-approve the resync question (cron/scripts)
python sync.py --keep-logs     # keep logs of successful runs too

python runsync.py              # UI (Tk, console fallback) + periodic service
python runsync.py --auto       # periodic service with the service's config, no UI
python runsync.py --auto --once  # one pass of the service's pairs, then exit
python runsync.py --llavero   # «Abrir llavero» without the window (what Llavero.bat runs)
python runsync.py --vigilar-llavero  # the keychain watcher (started by «Abrir llavero»)
python runsync.py --combinar-llavero BASE COPIA [--keyfile K]  # the «Combinar» console
python runsync.py --cerrar-llavero   # what Expulsar PRDRIVE.bat runs before dismounting
python runsync.py --doctor     # any other args pass straight through to sync.py

python penwatch.py install|status|probe|uninstall   # the watcher, per machine/user
python agente.py run|status                         # the resident agent (host copy)
python agente.py atender ID | modo ID MODO | pasada ID [pareja…] | pausa | sigue | parar
python agente.py abrir [ID]                         # the window of the host root (the menu entry;
                                                    # starts a stopped agent, and with no root says how it is)
python agente.py desbloquear [ID] | bloquear [ID]   # open / close the encrypted host root
python agente.py ajuste pedir_al_iniciar sí|no      # or espera_unidad_nueva SEG
python agente.py actualizar                         # fetch the new release and put it in place
python agente.py actualizar ID                      # put that root on the agent's version (the tray's «Actualizar a la vX»)

python prdrive-install.py          # install wizard for a NEW device (Tk only)
python prdrive-install.py --check  # rclone + connection + catalogue, then exit
python prdrive-install.py --probe  # what drives it sees, then exit
python prdrive-install.py --update E:\             # the device's code only
python prdrive-install.py --update-components E:\  # its rclone + runtime only
python prdrive-install.py --instalar-agente        # the resident agent on THIS host
python prdrive-install.py --desinstalar-agente     # and off again (no drive touched)
python prdrive-install.py --update-agente          # the installed agent (and open host roots) to this version
python build_installer.py          # build the .exe (embeds the profile if any)
python -m ui.icons                 # repaint APP_DIR/runsync.ico (headless)

python tests/run_all.py            # all tests; or run one script directly
```

`runsync.py` with no args always **stops a previously started service** first.

## Verification

Verification is `tests/run_all.py` (each script in its own process), `--doctor` and `--dry-run`. Nothing to lint. CI (`.github/workflows/tests.yml`) runs `run_all.py` on every PR and push to `main`, on `ubuntu-latest` under `xvfb-run` (with `python3-tk`) and on `windows-latest`, Python 3.11; it runs as an unprivileged user (a check that writes to `/` fails there), and no test may depend on what the real `%LOCALAPPDATA%` caches hold. The PR template still asks how it was checked. Tk tests skip themselves without a display, so an all-green run without Tk has tested no window.

- The suite passes on Windows **and** Linux. A check about the other system's branch forces it (`IS_WIN`, and for a Linux mount point `Unidad.letra`) in any system, or prints `(saltado) …` when it cannot run there (Unix sockets, the Linux tray's `select()` on a pipe).
- `tests/_harness.py` points `equipo.DIR`, `XDG_DATA_HOME`/`XDG_CONFIG_HOME`/`XDG_CACHE_HOME` and `keepassxc.bases_navegador()` (the browsers' manifest folders, Firefox's under the home folder) at temp dirs for every test, so no test sees or deletes the runner's agent, menu entries, extracted KeePassXC or browser manifests, and turns `os.kill(pid, 0)` into a real question on Windows: there 0 is `CTRL_C_EVENT`, a Ctrl+C to the whole console, and forcing `IS_WIN = False` reaches it.
- Tk 8.6 (system Python) vs Tk 9.0.4 (the Linux runtimes): see «The UI is measured on both» in `provisioning.md`.

## Indirection points

Everything that touches the network, a real device or the desktop is a **module-level indirection point so every test can replace it**. Keep new ones in that shape. Registry:

- **Network and downloads**: `catalog.run()` (`fleet` and `remote_picker` go through it), `update.fetch()`, `rclone_bin.fetch()`, `runtime_bin.fetch()`, `veracrypt_bin.fetch()`/`ensure_veracrypt()`, `keepassxc_bin.fetch()`, `descarga.esperar()`.
- **Window and desktop actions**: `ui.abrir()`, `runsync.notificar_fallo()`, `tk.mostrar()`/`confirmar_plan()`, `tk.proteger_de_capturas()`/`tk._afinidad_de_pantalla()`, `segundo_plano.lanzar()` (tests set it to `en_el_acto()`), `tk_equipo.escritorio()`, `pairing.construir()`, `watch.resumen()`, `watch.pedir_al_agente()`/`pedir_a_la_raiz()`, `cifrado.lanzar_expulsion()`/`pedir_bloqueo()`, `_preguntar_borrado()`.
- **Files and conflicts**: `conflicts.recorrer()`, `conflict_editor.mover()`/`borrar()`.
- **Components and VeraCrypt**: `components.rclone_en_uso()`/`runtime_en_uso()`/`veracrypt_en_uso()`/`lanzar_suelto()`/`esperar_a()`/`procesos_desde()`, `common.components.raiz_fisica()`, `traveler.espacio_libre()`, `vestibulo.raiz_fisica()`/`retenido()`, `crypto.sistema_de_ficheros()`/`bytes_escritos()`/`_procesos()`, `penwatch.installed_veracrypt()`.
- **Host OS**: `_win_volumes()`, `_leer_estado_bitlocker()`, `store.procesos()` (under `procesos_desde()`), `registro.leer()`/`escribir()`/`borrar()`/`vacia()` (HKCU).
- **The keychain**: `llavero.dormir()`/`pasada()`/`lanzar_vigilante()`/`keepassxc_abierto()`/`atiende_el_servicio()`, `keepassxc.paquete_del_equipo()`/`lanzar()`/`otro_abierto()`/`cli()`/`combinar()`/`ejecutar_cli()`/`pedir_cierre()`/`terminar()`, on Linux `keepassxc.cache_equipo()`/`extraer_appimage()`/`del_equipo()`/`version_del_equipo()`/`bases_navegador()`/`terminal()` and `store.orden_de()` (with `llavero.MIRAR_ORDENES` to look at command lines on any OS), `llavero.matar_arbol()`, `tk_llavero.avisar()`/`elegir_llave()`/`elegir_base()`/`preguntar()`.
- **The agent**: `agente.lanzar()`/`hay_pantalla()`/`avisar()`/`abrir_contenedor()`/`diario()`/`poner_bandeja()`/`explorar()`/`arrancar_agente()`/`poner_red()`/`rclone_propio()`/`veracrypt_propio()`/`procesos()`, `agente.hilo()` (the version check and the `watch` walks), `agente.huella_local()` (the photo of a watched folder, over `huella.de_carpeta()`), `agente.keepassxc_abierto()` (whether a root's KeePassXC runs), `agente.limpiar_navegador()` (the dead browser keys or Linux manifests; `_agente_falso` makes it a no-op), `agente.cerrar_keepassxc_huerfano()` (a gone root's KeePassXC on Linux; no-op there too), `agente.keepassxc_huerfano_abierto()` (whether it still runs; `False` there), `agente.buscar_version()`/`ejecutar()`/`cache_version()`, `avisos.enviar()`, `moderacion.energia()`/`red_medida()`, `runsync.pedir_reanudar()`/`agente_sirve()`, `equipo.DIR`.
- **Installing the agent and the host root**: `install.pintar_iconos`, `install.agente.conseguir_runtime()`/`lanzar()`/`autostart_file()`/`acceso_menu()`/`crear_lnk()`/`matar_arbol()`/`conseguir_rclone()`/`conseguir_veracrypt()`, `raiz_equipo.carpetas_sincronizadas()`/`veracrypt_instalado()`/`abrir_o_crear()`/`veracrypt_portatil()`.
- **Trays and network notices**: `bandeja_windows.Api`, the Linux tray's `conectar`/`conectar_sistema`, `red.AvisosDeRed`'s `api` (`red.ApiWindows`)/`conectar_sistema`/`conectar_netlink`.
