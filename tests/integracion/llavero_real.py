#!/usr/bin/env python3
"""El llavero con el KeePassXC y el rclone de verdad, de punta a punta: lo que los tests no ven.

No es un test de `run_all.py` (no empieza por `test_`): baja KeePassXC y rclone
de verdad, abre KeePassXC con pantalla y, en Windows, escribe las claves del
navegador en HKCU. Lo corre `.github/workflows/llavero-real.yml` en una máquina
de usar y tirar; en un equipo propio, solo con `--de-verdad`.

Monta un dispositivo como el instalador (`install/deploy`), con un remoto
`local` en un temporal, y hace lo que haría la persona, con el código DEL
DISPOSITIVO y cada paso en su propio proceso, como la ventana:
1. KeePassXC del paquete de este sistema, bajado y comprobado
   (`keepassxc_bin.instalar`, el paso «Llavero» y «Actualizar…»).
2. Una base nueva (`keepassxc-cli db-create`) y «Usar esta base…»
   (`llavero_editor.plan_activar`), que escribe el catálogo por rclone.
3. «Abrir llavero» (`llavero_editor.abrir`): la primera pasada sube la base y
   crea la carpeta del remoto, KeePassXC se abre y es de la unidad, su
   configuración va a la de la unidad, y el navegador llega a él: un
   `change-public-keys` de KeePassXC-Browser por el proxy de su manifiesto (en
   Windows, el JSON al que apunta la clave de HKCU, que escribe KeePassXC).
4. Un guardado (`keepassxc-cli add`) lo sube solo el vigilante.
5. Un conflicto de verdad (la base cambia en los dos lados): bisync deja la
   copia al lado, y «Combinar» (`conflict_editor.plan_combinar`) la mete en la
   base con `keepassxc-cli merge` y la aparta a `.prversions/`. Solo se cambia
   la consola donde la persona escribiría la contraseña: va por la entrada.
6. La pasada siguiente quita la copia del remoto, sin que la pare el freno de
   borrados.
7. «Expulsar» (`runsync.py --cerrar-llavero`): KeePassXC se cierra, el
   vigilante se va, lo pendiente sube y el navegador queda como estaba.

Sale con 1 si algo no es lo esperado, y dice qué.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLAVE = "clave-de-prueba"
BASE = "Personal.kdbx"
IS_WIN = os.name == "nt"
ESPERA_SUBIDA = 240.0
"""Segundos: la calma (20 s) y la separación desde la última pasada (120 s), con margen."""
ORIGEN_CHROME = "chrome-extension://oboonakemofpalcgghocfoadofidjkkk/"
fallos: list[str] = []


def ver(que: str, obtenido, esperado) -> None:
    """Apunta una comprobación y la dice."""
    bien = obtenido == esperado
    print(f"  {'OK   ' if bien else 'FALLO'} {que}" + ("" if bien else
          f"\n          obtenido: {obtenido!r}\n          esperado: {esperado!r}"), flush=True)
    if not bien:
        fallos.append(que)


def resumen(ruta: Path) -> str:
    """Devuelve el SHA-256 de un fichero, o '' si no está."""
    try:
        return hashlib.sha256(ruta.read_bytes()).hexdigest()
    except OSError:
        return ""


def esperar(condicion, tope: float, cada: float = 2.0) -> float | None:
    """Espera a que se cumpla `condicion()`; devuelve los segundos, o `None` si no."""
    t = time.monotonic()
    while time.monotonic() - t < tope:
        if condicion():
            return round(time.monotonic() - t, 1)
        time.sleep(cada)
    return None


def hijo() -> dict[str, str]:
    """El entorno de un proceso hijo: el de ahora, con la consola en UTF-8.

    Solo la consola (`PYTHONIOENCODING`): en Windows la de un hijo con la
    salida en una tubería es cp1252, y aquí se lee en UTF-8. `PYTHONUTF8`
    cambiaría también el `open()` del código que se prueba, y taparía un
    `encoding=` que falte.
    """
    return {**os.environ, "PYTHONIOENCODING": "utf-8"}


def contar(salida: str) -> None:
    """Enseña la salida de un paso, sangrada."""
    for linea in salida.strip().splitlines():
        print(f"    | {linea}", flush=True)


# --- el lado del dispositivo: SU `common/` y SU `ui/`, en otro proceso

def en_dispositivo(app: Path, paso: str, *args: str, entrada: str | None = None) -> str:
    """Corre un paso con el código del dispositivo; devuelve su última línea (lanza si falla)."""
    r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--en-dispositivo",
                        str(app), paso, *args], input=entrada, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=hijo(), cwd=tempfile.gettempdir(),
                       timeout=900)
    contar((r.stdout or "") + (r.stderr or ""))
    if r.returncode != 0:
        raise RuntimeError(f"el paso «{paso}» ha salido con {r.returncode}")
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""


def paso_dispositivo(app: Path, paso: str, args: list[str]) -> int:
    """Hace un paso importando el código del dispositivo, como su ventana."""
    sys.path.insert(0, str(app))
    from common import catalog, config_file, conflicts, keepassxc, llavero, model, registro
    from ui import conflict_editor, llavero_editor

    if model.APP_DIR.resolve() != app.resolve():
        print(f"no es el código del dispositivo: {model.APP_DIR}")
        return 2
    if paso == "cli":
        print(keepassxc.cli_lanzable(keepassxc.cli()))
    elif paso == "activar":
        raw = config_file.load_raw()
        cat, _ = catalog.load(raw)
        plan = llavero_editor.plan_activar(raw, cat, Path(args[0]))
        print("hecho:", *plan.execute(), sep="\n  ")
    elif paso == "abrir":
        def trabajando(_mensaje, funcion):
            try:
                return True, funcion()
            except Exception as e:                     # noqa: BLE001 (como `tk.working()`)
                return False, e
        dicho: list[str] = []
        hecho = llavero_editor.abrir(model.load_config(), dicho.append, trabajando,
                                     lambda _nombre: None, lambda _plan, _t, _n: False,
                                     decir_sin_traer=True)
        print(json.dumps({"abierto": hecho, "dicho": dicho}, ensure_ascii=False))
    elif paso == "combinar":
        # Lo de la consola de «Combinar», en este proceso: la contraseña llega
        # por la entrada en vez de escribirla la persona.
        keepassxc.combinar = lambda base, copia, llave=None: keepassxc.combinar_aqui(
            base, copia, llave, esperar=lambda *_: None)
        hallados = conflicts.escanear(model.load_config().pareja_llavero)
        hechos = conflict_editor.plan_combinar(hallados[0], None).execute() if hallados else []
        print(json.dumps(hechos, ensure_ascii=False))
    elif paso == "listado":
        # Lo que prdrive lee del listado de rclone, frente a lo que hay en la unidad.
        pareja = model.load_config().pareja_llavero
        donde = pareja.local_abs
        print(json.dumps({
            "listado": llavero.listado_local(pareja),
            "unidad": {r.name: [r.stat().st_size, r.stat().st_mtime_ns]
                       for r in llavero.bases(donde)},
            "sin_listar": llavero.sin_listar(pareja), "pendiente": llavero.pendiente(pareja)}))
    elif paso == "estado":
        paquete = keepassxc.paquete_del_equipo()
        config = model.load_config()
        claves = ({b: registro.leer(keepassxc.clave_nativa(b)) for b, _ in keepassxc.NAVEGADORES}
                  if IS_WIN else {})
        manifiestos = ({} if IS_WIN else
                       {n: str(r) for n, r, _ in keepassxc.manifiestos_linux() if r.is_file()})
        print(json.dumps({
            "abierto": llavero.keepassxc_abierto(), "vigilante": llavero.vigilante_vivo(),
            "claves": claves, "manifiestos": manifiestos,
            "config": sorted(p.name for p in keepassxc.carpeta_config(paquete).glob("*")),
            "linea": llavero_editor.linea(config).texto}, ensure_ascii=False))
    else:
        print(f"paso desconocido: {paso}")
        return 2
    return 0


# --- el lado del repositorio: preparar y mirar

def preparar(raiz: Path, remoto: Path) -> Path:
    """Monta un dispositivo como el instalador, con un remoto `local`; devuelve su `.prdrive`."""
    sys.path.insert(0, str(REPO))
    from common import config_file
    from install import deploy, device, rclone_bin
    from install.profile import Profile
    from install.remote import Catalog

    (remoto / "prdrive-catalog").mkdir(parents=True)
    (remoto / "notas").mkdir()
    ruta_catalogo = f"{remoto.as_posix()}/prdrive-catalog/remote.toml"
    catalogo = {"defaults": {"remote": "nas", "catalog_path": ruta_catalogo},
                "pair": [{"name": "notas", "local": "sync-data/notas",
                          "remote_path": f"{remoto.as_posix()}/notas", "mode": "bisync"}]}
    cabecera = "# catálogo de prueba\n"
    (remoto / "prdrive-catalog" / "remote.toml").write_text(
        config_file.dumps(catalogo, cabecera), encoding="utf-8")
    binario = rclone_bin.cached() or rclone_bin.download_rclone(lambda *_: None)
    deploy.deploy_code(raiz, binario)
    deploy.write_device_remote(raiz, Profile(remote_name="nas", options={"type": "local"},
                                             catalog_path=ruta_catalogo))
    deploy.write_device_config(raiz, Catalog(raw=catalogo, head=cabecera,
                                             endpoint=f"nas:{ruta_catalogo}"),
                               ["notas"], catalog_path=ruta_catalogo)
    deploy.write_launchers(raiz)
    device.ensure_control_file(raiz)
    (raiz / "sync-data" / "notas").mkdir(parents=True, exist_ok=True)
    return deploy.app_dir(raiz)


def hablar_con_keepassxc(proxy: str, tope: float = 15.0) -> dict:
    """Hace de KeePassXC-Browser: lanza el proxy y le manda `change-public-keys`.

    Sin KeePassXC al otro lado el proxy no contesta nunca: se espera `tope`
    segundos, en un hilo, y se da por fallido.
    """
    p = subprocess.Popen([proxy, ORIGEN_CHROME], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    respuesta: dict = {"fallo": f"el proxy no contesta en {tope:.0f} s"}

    def hablar() -> None:
        def b64(n: int) -> str:
            return base64.b64encode(os.urandom(n)).decode()
        msg = json.dumps({"action": "change-public-keys", "publicKey": b64(32),
                          "nonce": b64(24), "clientID": b64(24)}).encode()
        try:
            p.stdin.write(struct.pack("<I", len(msg)) + msg)
            p.stdin.flush()
            largo = struct.unpack("<I", p.stdout.read(4))[0]
            leido = json.loads(p.stdout.read(largo))
        except (OSError, ValueError, struct.error) as e:
            respuesta["fallo"] = repr(e)
            return
        respuesta.clear()
        respuesta.update(leido)

    hilo = threading.Thread(target=hablar, daemon=True)
    hilo.start()
    hilo.join(tope)
    p.kill()
    return respuesta


def por_que_no_arranca() -> None:
    """Cuenta por qué no se ve KeePassXC (Linux): las bibliotecas que no encuentra y lo que dice.

    Es lo extraído en la caché: `ldd` del programa y del plugin de Qt para X11
    (con las bibliotecas que lleva el AppImage delante, como `AppRun`), y
    unos segundos de arrancarlo a mano con `QT_DEBUG_PLUGINS`.
    """
    from common import keepassxc as kx
    from common import pins
    raiz = kx.cache_equipo() / pins.KEEPASSXC_VERSION / "squashfs-root"
    # Con su configuración en un temporal: sin eso dejaría `~/.config/keepassxc`.
    temporal = Path(tempfile.mkdtemp(prefix="prdrive-diagnostico-"))
    entorno = {**os.environ, "LD_LIBRARY_PATH": str(raiz / "usr" / "lib"),
               "QT_DEBUG_PLUGINS": "1", "KPXC_CONFIG": str(temporal / "keepassxc.ini"),
               "KPXC_CONFIG_LOCAL": str(temporal / "keepassxc_local.ini")}
    print(f"    ¿Por qué no se ve KeePassXC? (lo extraído en {raiz})")
    for binario in (raiz / "usr" / "bin" / "keepassxc",
                    raiz / "usr" / "plugins" / "platforms" / "libqxcb.so"):
        r = subprocess.run(["ldd", str(binario)], capture_output=True, text=True, env=entorno)
        faltan = [x.strip() for x in r.stdout.splitlines() if "not found" in x]
        print(f"    ldd {binario.name}: " + (", ".join(faltan) if faltan else "no falta nada"))
    for args in (["--version"], []):            # la versión, y la ventana: 10 s
        try:
            r = subprocess.run([str(raiz / "AppRun"), *args], capture_output=True, text=True,
                               env=entorno, timeout=10)
            salida = (r.stdout + r.stderr).strip().splitlines()
            print(f"    AppRun {' '.join(args)}: código {r.returncode}")
        except subprocess.TimeoutExpired as e:
            salida = ((e.stdout or b"").decode(errors="replace")
                      + (e.stderr or b"").decode(errors="replace")).strip().splitlines()
            print(f"    AppRun {' '.join(args)}: sigue abierto a los 10 s")
        mostrar(salida)


def mostrar(salida: list[str]) -> None:
    """Enseña lo que dijo KeePassXC con `QT_DEBUG_PLUGINS`."""
    # La depuración de los plugins es muy larga: solo lo que suena a error, y el final.
    errores = [x for x in salida if re.search(
        r"[Ee]rror|[Cc]annot (load|open)|Could not|failed|not found|[Uu]nable|Abort"
        r"|This application", x)]
    for linea in (errores[-20:] + ["…"] + salida[-5:]) if errores else salida[-10:]:
        print(f"    | {linea}")


class Cli:
    """El `keepassxc-cli` de la unidad (el extraído, en Linux), con la contraseña por la entrada.

    Con su configuración en un temporal: es la persona usándolo, no prdrive, y
    sin eso dejaría `~/.config/keepassxc` en este equipo.
    """

    def __init__(self, app: Path, temporal: Path):
        self.programa = en_dispositivo(app, "cli")
        self.entorno = {**os.environ, "KPXC_CONFIG": str(temporal / "cli.ini"),
                        "KPXC_CONFIG_LOCAL": str(temporal / "cli_local.ini")}

    def __call__(self, *args: str, entrada: str = CLAVE + "\n") -> subprocess.CompletedProcess:
        return subprocess.run([self.programa, *args], input=entrada, capture_output=True,
                              text=True, env=self.entorno, timeout=120)

    def entradas(self, base: Path) -> list[str]:
        """Los títulos de las entradas de la base."""
        return sorted(self("ls", "-q", str(base)).stdout.split())


def volcar(app: Path) -> None:
    """Enseña los logs de las pasadas y los listados de rclone, para ver qué pasó en el CI."""
    for log in sorted((app / "logs").glob("keychain_*.log")):
        print(f"\n--- {log.name}")
        lineas = log.read_text(encoding="utf-8", errors="replace").splitlines()
        desde = next((i for i, x in enumerate(lineas) if "Synching Path1" in x), 0)
        for linea in lineas[desde:]:
            if "lock file renewed" not in linea and " ETA " not in linea:
                print(f"    {linea}")
    for lst in sorted((app / "state" / "keychain").glob("*.lst")):
        print(f"\n--- {lst.name}")
        print(lst.read_text(encoding="utf-8", errors="replace"))


def estado(app: Path) -> dict:
    """Lo que dice el dispositivo de su llavero en este equipo."""
    return json.loads(en_dispositivo(app, "estado"))


def pasada(app: Path) -> tuple[int, str]:
    """Una pasada del llavero con el `sync.py` del dispositivo: (código, salida)."""
    r = subprocess.run([sys.executable, str(app / "sync.py"), "keychain", "-y", "--keep-logs"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=hijo(), cwd=tempfile.gettempdir(), timeout=600)
    contar(r.stdout + r.stderr)
    return r.returncode, r.stdout


def main() -> int:
    # Lo que se cuenta lleva «», tildes y rutas: que no lo rompa una consola cp1252.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--en-dispositivo" in sys.argv:
        i = sys.argv.index("--en-dispositivo")
        return paso_dispositivo(Path(sys.argv[i + 1]), sys.argv[i + 2], sys.argv[i + 3:])
    if not os.environ.get("CI") and "--de-verdad" not in sys.argv:
        print("Esto baja KeePassXC y rclone, abre KeePassXC y, en Windows, escribe las "
              "claves del navegador: solo corre en el CI, o con --de-verdad.")
        return 2
    # Resuelto: en el Windows del CI el temporal es `RUNNER~1`, un nombre 8.3.
    # En `RUNNER_TEMP`, si lo hay: el CI sube de ahí los logs cuando algo falla.
    temporal = Path(tempfile.mkdtemp(prefix="prdrive-real-",
                                     dir=os.environ.get("RUNNER_TEMP") or None)).resolve()
    raiz, remoto = temporal / "unidad", temporal / "remoto"
    raiz.mkdir()
    if not IS_WIN:
        # La carpeta personal en el temporal: los manifiestos y lo extraído van
        # ahí, y Chrome y Firefox «están» (sus carpetas existen).
        casa = temporal / "casa"
        for d in (".config/google-chrome", ".mozilla", ".cache", ".local/share"):
            (casa / d).mkdir(parents=True)
        # La de ejecución, corta y en /tmp: el servidor del navegador de KeePassXC
        # es un socket en `$XDG_RUNTIME_DIR/app/org.keepassxc.KeePassXC/…BrowserServer`
        # (66 caracteres más), y la ruta de un socket no pasa de 108. La del
        # temporal del CI es larga (120 en total): KeePassXC no podía escuchar.
        # En un equipo es `/run/user/<uid>` (80).
        ejecucion = Path(tempfile.mkdtemp(prefix="kpx-", dir="/tmp"))
        os.environ.update(HOME=str(casa), XDG_CONFIG_HOME=str(casa / ".config"),
                          XDG_CACHE_HOME=str(casa / ".cache"),
                          XDG_DATA_HOME=str(casa / ".local/share"),
                          XDG_RUNTIME_DIR=str(ejecucion))

    print("== 1. Un dispositivo, y KeePassXC bajado y comprobado", flush=True)
    app = preparar(raiz, remoto)
    from common import components, pins
    from common import keepassxc as kx
    from install import keepassxc_bin
    paquete = "windows-x64" if IS_WIN else "linux-x64"
    t = time.monotonic()
    keepassxc_bin.instalar(app, paquete, lambda *_: None)
    ver(f"KeePassXC {pins.KEEPASSXC_VERSION} ({paquete}), bajado y comprobado en "
        f"{round(time.monotonic() - t)} s", components.keepassxc_version(app, paquete),
        pins.KEEPASSXC_VERSION)

    print("== 2. Una base nueva, y «Usar esta base…»", flush=True)
    cli = Cli(app, temporal)
    propia = temporal / "propia" / BASE
    propia.parent.mkdir()
    r = cli("db-create", "-p", str(propia), entrada=f"{CLAVE}\n{CLAVE}\n")
    ver("keepassxc-cli db-create crea la base", (r.returncode, propia.is_file()), (0, True))
    en_dispositivo(app, "activar", str(propia))
    catalogo = (remoto / "prdrive-catalog" / "remote.toml").read_text(encoding="utf-8")
    ver("el catálogo del remoto lleva el llavero", "[keychain]" in catalogo, True)
    local = raiz / ".keychain" / BASE
    ver("la unidad, la base y los dos lanzadores",
        [local.is_file(), (raiz / "Llavero.bat").is_file(), (raiz / "llavero.sh").is_file()],
        [True, True, True])

    print("== 3. «Abrir llavero»", flush=True)
    ver("se abre sin nada que decir", json.loads(en_dispositivo(app, "abrir")),
        {"abierto": True, "dicho": []})
    remota = remoto / "prdrive-catalog" / "keychain" / BASE
    ver("la primera pasada sube la base (y crea keychain/ en el remoto)",
        resumen(remota), resumen(local))
    se_ve = esperar(lambda: estado(app)["abierto"], 30) is not None
    ver("KeePassXC se reconoce como de la unidad", se_ve, True)
    if not se_ve and not IS_WIN:
        por_que_no_arranca()
    e = estado(app)
    ver("el vigilante, en marcha", e["vigilante"], True)
    ver("su configuración, en la de la unidad",
        e["config"], ["keepassxc.ini", "keepassxc_local.ini", "raiz.txt"])
    ver("la línea de la ventana lo dice", e["linea"], f"{BASE}, abierto en KeePassXC.")
    if IS_WIN:
        # Al arrancar, KeePassXC se queda con las cuatro (B1 de
        # `2026-10-04-keepassxc-portatil-resultados.md`): con `/` y con el
        # último navegador de cada una (`brave`, `tor-browser`), pero en la
        # carpeta de la unidad. Eso es lo que importa, y que el JSON esté.
        carpeta = components.keepassxc_exe(app, paquete).parent / "config"
        valores = [v for v in e["claves"].values() if v]
        ver("las cuatro claves del navegador apuntan a JSON de la unidad, que están",
            (len(valores), {kx._comparable(str(Path(v).parent)) for v in valores},
             all(Path(v).is_file() for v in valores)),
            (4, {kx._comparable(str(carpeta))}, True))
        manifiesto = kx.json_nativo(carpeta, "chrome")
        ver("y KeePassXC escribe el de Chrome al arrancar (updateBinaryPaths)",
            esperar(manifiesto.is_file, 30) is not None, True)
    else:
        ver("los manifiestos de Chrome y Firefox, escritos", sorted(e["manifiestos"]),
            ["chrome", "firefox"])
        manifiesto = Path(e["manifiestos"].get("chrome", "no-hay"))
        ver("y nada en ~/.config/keepassxc",
            (Path(os.environ["XDG_CONFIG_HOME"]) / "keepassxc").exists(), False)
    # Recién abierto, su servidor del navegador puede no escuchar todavía, y el
    # proxy no vuelve a intentar la conexión: se le dan unos intentos.
    respuesta: dict = {}
    for _ in range(4):
        try:
            proxy = json.loads(manifiesto.read_text(encoding="utf-8"))["path"]
            respuesta = hablar_con_keepassxc(proxy, tope=5)
        except (OSError, ValueError, KeyError) as fallo:
            respuesta = {"fallo": repr(fallo)}
        if respuesta.get("action"):
            break
        time.sleep(2)
    ver("el navegador llega a KeePassXC por el proxy de su manifiesto",
        (respuesta.get("action"), respuesta.get("version"), respuesta.get("success")),
        ("change-public-keys", pins.KEEPASSXC_VERSION, "true"))

    print("== 4. Un guardado sube solo", flush=True)
    ver("keepassxc-cli add guarda en la base de la unidad",
        cli("add", "-q", str(local), "desde-este-dispositivo").returncode, 0)
    nuevo = resumen(local)
    t = esperar(lambda: resumen(remota) == nuevo, ESPERA_SUBIDA, 5)
    print(f"    (subió en {t} s)", flush=True)
    ver(f"el vigilante lo sube en menos de {ESPERA_SUBIDA:.0f} s", t is not None, True)

    print("== 5. Un conflicto de verdad, y «Combinar»", flush=True)
    ver("la base cambia aquí", cli("add", "-q", str(local), "conflicto-aqui").returncode, 0)
    time.sleep(1.5)
    ver("  y en el remoto, después", cli("add", "-q", str(remota), "conflicto-alla").returncode, 0)
    rc, _ = pasada(app)
    en_dispositivo(app, "listado")
    copia = BASE.replace(".kdbx", ".conflicto-dispositivo1.kdbx")
    ver("la pasada deja al lado la copia de este lado (no la manda a .prversions)",
        (rc, sorted(p.name for p in local.parent.glob("*.conflicto-*.kdbx"))), (0, [copia]))
    hechos = json.loads(en_dispositivo(app, "combinar", entrada=CLAVE + "\n"))
    ver("«Combinar» la mete en la base", hechos, [f"«{copia}» combinada en «{BASE}»"])
    ver("  la base tiene lo de los dos lados",
        [x for x in cli.entradas(local) if x.startswith("conflicto-")],
        ["conflicto-alla", "conflicto-aqui"])
    ver("  y la copia está en .prversions",
        [p.name.startswith(copia[:-5] + "~") for p in (local.parent / ".prversions").glob(
            "*.conflicto-*")], [True])

    print("== 6. Su borrado llega al remoto", flush=True)
    rc, salida = pasada(app)
    ver("la pasada va bien, sin que la pare el freno de borrados",
        (rc, "se repite la pasada sin el freno" in salida), (0, True))
    ver("el remoto se queda con la base y LEEME.txt",
        sorted(p.name for p in remota.parent.iterdir() if p.is_file()), ["LEEME.txt", BASE])

    print("== 7. «Expulsar»", flush=True)
    r = subprocess.run([sys.executable, str(app / "runsync.py"), "--cerrar-llavero"],
                       input="s\n", capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=hijo(), timeout=600, cwd=tempfile.gettempdir())
    contar(r.stdout + r.stderr)
    ver("--cerrar-llavero sale con 0", r.returncode, 0)
    e = estado(app)
    ver("KeePassXC cerrado y el vigilante ido", (e["abierto"], e["vigilante"]), (False, False))
    ver("la base, igual en los dos lados", resumen(remota), resumen(local))
    if IS_WIN:
        ver("las claves del navegador, quitadas", [v for v in e["claves"].values() if v], [])
    else:
        ver("los manifiestos, quitados", e["manifiestos"], {})
    if fallos:
        volcar(app)
        print(f"\nLo de la prueba se queda en {temporal} (logs en {app / 'logs'}).")
    else:
        shutil.rmtree(temporal, ignore_errors=True)
        if not IS_WIN:
            shutil.rmtree(os.environ["XDG_RUNTIME_DIR"], ignore_errors=True)

    print("\n" + ("TODO BIEN" if not fallos else f"FALLAN {len(fallos)}: " + "; ".join(fallos)))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
