#!/usr/bin/env python3
"""«Abrir llavero» en Linux (`common/keepassxc.py`, `common/llavero.py`): la fase 2.

Sin Linux de verdad y sin ejecutar nada: el AppImage es un fichero de mentira,
`--appimage-extract` se sustituye por una función que deja la carpeta que
dejaría, los procesos y sus líneas de órdenes se dicen, y `lanzar()` apunta la
orden. Corre igual en Windows. Lo que se sujeta:
- La configuración de Linux va en `config/linux/`, con `\\n`, sin rehacer los
  manifiestos al arrancar y con el proxy de lo extraído en este equipo.
- Un KeePassXC de Linux es de esta unidad si su orden nombra algo suyo (su
  configuración o su base): corre fuera de ella.
- El AppImage se extrae una vez por versión, se comprueba la copia antes de
  extraerla, un fallo no deja restos ni estropea lo que había, y las versiones
  viejas se van si nada corre desde ellas.
- El navegador: un manifiesto por navegador del equipo, como el que escribiría
  KeePassXC, solo donde no lo hay o es nuestro; al cerrar se quitan los
  nuestros, y el agente solo si no queda un KeePassXC de lo extraído.
- «Abrir llavero» lanza el `AppRun` extraído con la configuración de Linux, y
  no toca el registro.
- En Linux ARM64, sin paquete, el KeePassXC del equipo: con su configuración,
  avisando si no tiene passkeys, y el de Flathub con permiso para la unidad.
- «Combinar» abre una terminal y espera el código que deja su consola (las
  terminales no lo devuelven); sin terminal, se dice cómo hacerlo a mano.
- `Llavero.bat` y `llavero.sh` se ponen juntos y se quitan solo si son los
  nuestros.
"""

import hashlib
import os
import textwrap
import subprocess
import sys
import time
from pathlib import Path

from _harness import Checks, sandbox, tmpdir

import runsync
from common import components, keepassxc, llavero, model, pins, registro, store
from ui import llavero_editor

c = Checks("el llavero en Linux (common/keepassxc.py)")

# --- la configuración de Linux
PROXY = Path("/home/ana/.cache/prdrive/keepassxc/2.7.12/squashfs-root/usr/bin/keepassxc-proxy")
real_app = model.APP_DIR
try:
    with sandbox() as root:
        model.APP_DIR = root / ".prdrive"
        donde = keepassxc.carpeta_config("linux-x64")
        c("va en .prdrive/keepassxc/config/linux/, aparte de la de Windows",
          (donde.relative_to(model.APP_DIR).as_posix(),
           keepassxc.carpeta_config("windows-x64").relative_to(model.APP_DIR).as_posix()),
          ("keepassxc/config/linux", "keepassxc/config/windows"))
        keepassxc.ajustar_config(Path("/media/ana/PRDRIVE"), paquete="linux-x64", proxy=PROXY)
        ini = (donde / keepassxc.INI).read_bytes()
        c("  con el fin de línea de QSettings en Linux", b"\r\n" in ini, False)
        texto = ini.decode("utf-8")
        for linea in ("UseAtomicSaves=true", "UpdateBinaryPath=false", "UseCustomProxy=true",
                      f"CustomProxyLocation={PROXY}", "CheckForUpdates=false", "Enabled=true"):
            c.contains(f"  {linea}", texto, linea)
        c("  y la raíz apuntada, con su punto de montaje",
          (donde / keepassxc.RAIZ).read_text(encoding="utf-8"), "/media/ana/PRDRIVE\n")
        (donde / keepassxc.INI_LOCAL).write_bytes(
            b"[General]\nLastDatabases=/media/ana/PRDRIVE/.keychain/personal.kdbx\n")
        keepassxc.ajustar_config(Path("/run/media/ana/PRDRIVE"), paquete="linux-x64",
                                 proxy=PROXY)
        c("las recientes pasan al punto de montaje de este equipo",
          (donde / keepassxc.INI_LOCAL).read_bytes(),
          b"[General]\nLastDatabases=/run/media/ana/PRDRIVE/.keychain/personal.kdbx\n")
        (donde / keepassxc.INI).unlink()
        keepassxc.ajustar_config(Path("/media/ana/PRDRIVE"), paquete="linux-x64",
                                 proxy=Path("/home/josé/.cache/x/keepassxc-proxy"))
        c("un proxy que QSettings escaparía no se pone",
          "CustomProxyLocation" in (donde / keepassxc.INI).read_text(encoding="utf-8"), False)
finally:
    model.APP_DIR = real_app

# --- de qué unidad es un KeePassXC de Linux
reales_procesos = (store.procesos, store.orden_de, store.procesos_desde,
                   llavero.MIRAR_ORDENES)
try:
    raiz = tmpdir("prdrive-kpxc-linux-")
    app = raiz / ".prdrive"
    rclone = components.rclone_path(app, pins.plataforma("linux-x64"))
    rclone.parent.mkdir(parents=True)
    rclone.write_bytes(b"ELF")
    otra = tmpdir("prdrive-kpxc-otra-") / ".prdrive"
    extraido = tmpdir("prdrive-kpxc-cache-") / "2.7.12" / keepassxc.EXTRAIDO / "usr" / "bin"
    config_ = app / components.KEEPASSXC_SUBDIR / keepassxc.CONFIG_LINUX / keepassxc.INI
    base = raiz / model.LLAVERO_LOCAL / "personal.kdbx"
    PROCESOS = {
        10: (str(extraido / "keepassxc"), ["--config", str(config_), str(base)]),
        11: ("/usr/bin/keepassxc", []),
        12: ("/usr/bin/keepassxc", [str(base)]),
        13: (str(extraido / "keepassxc"),
             ["--config", str(otra / "keepassxc" / "config" / "linux" / "keepassxc.ini")]),
        14: (str(extraido / "keepassxc-proxy"), [str(base)]),
        15: ("/usr/bin/firefox", [str(base)]),
    }
    store.procesos = lambda: {pid: exe for pid, (exe, _) in PROCESOS.items()}
    store.orden_de = lambda pid: [PROCESOS[pid][0], *PROCESOS[pid][1]]
    store.procesos_desde = lambda carpeta: {}
    llavero.MIRAR_ORDENES = True
    c("es suyo el que lleva su configuración y el del equipo con su base; no el de otra "
      "unidad, ni el proxy, ni otro programa con la base",
      sorted(llavero.pids_keepassxc(app)), [10, 12])
    c("  el de la otra unidad es suyo allí", (llavero.pids_keepassxc(otra),
                                             llavero.keepassxc_abierto(otra)), ([13], True))
    real_app = model.APP_DIR
    model.APP_DIR = app
    try:
        c("otro KeePassXC abierto: el del equipo sin la base, y el de la otra unidad",
          keepassxc.otro_abierto(), True)
        c("al cerrar: los suyos, y el proxy no (no retiene la unidad)",
          keepassxc.procesos_de_la_unidad(), ([10, 12], []))
        del PROCESOS[11], PROCESOS[13]
        c("  sin los otros, no hay «otro»", keepassxc.otro_abierto(), False)
    finally:
        model.APP_DIR = real_app
finally:
    store.procesos, store.orden_de, store.procesos_desde, llavero.MIRAR_ORDENES = reales_procesos

# Un KeePassXC que se cierra y es hijo de quien espera (la ventana lo lanza y
# «Expulsar» lo espera) se queda zombi hasta que lo recogen: ya no está vivo.
if os.name != "nt":
    hijo = subprocess.Popen([sys.executable, "-c", "pass"])
    limite = time.monotonic() + 10
    while time.monotonic() < limite and store.pid_alive(hijo.pid):
        time.sleep(0.05)
    c("un hijo que ya ha salido, sin recoger, no está vivo", store.pid_alive(hijo.pid), False)
    hijo.wait()
    c("  y uno vivo, sí", store.pid_alive(os.getpid()), True)
else:
    print("  (saltado) los zombis son de POSIX: Windows mira el código de salida")

# --- el AppImage, extraído una vez por equipo y versión
APPIMAGE = b"\x7fELF el AppImage de mentira"
SHA = hashlib.sha256(APPIMAGE).hexdigest()
extracciones: list[Path] = []
falla_extraer = {"codigo": 0}


def extraer_falso(appimage: Path, donde: Path) -> int:
    """Deja lo que dejaría `--appimage-extract`, y apunta qué AppImage se extrajo."""
    extracciones.append(appimage)
    if falla_extraer["codigo"]:
        (donde / keepassxc.EXTRAIDO).mkdir()                     # a medias
        return falla_extraer["codigo"]
    bin_ = donde / keepassxc.EXTRAIDO / "usr" / "bin"
    bin_.mkdir(parents=True)
    for nombre in ("keepassxc", "keepassxc-cli", "keepassxc-proxy"):
        (bin_ / nombre).write_bytes(b"ELF " + appimage.read_bytes())
    (donde / keepassxc.EXTRAIDO / keepassxc.APPRUN).write_text("#!/bin/sh\n", encoding="utf-8")
    return 0


def poner_appimage(app: Path, datos: bytes, version: str = pins.KEEPASSXC_VERSION,
                   sha: str | None = None) -> None:
    """Deja el AppImage en la unidad con su sello (el SHA-256 de `datos`, o `sha`)."""
    carpeta = components.keepassxc_dir(app, "linux-x64")
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / components.KEEPASSXC_APPIMAGE).write_bytes(datos)
    sha = hashlib.sha256(datos).hexdigest() if sha is None else sha
    (carpeta / components.KEEPASSXC_STAMP).write_text(components.keepassxc_stamp_text(
        version, pins.KEEPASSXC["linux-x64"][0], sha, {components.KEEPASSXC_APPIMAGE: sha}),
        encoding="utf-8")


reales_extraer = (keepassxc.cache_equipo, keepassxc.extraer_appimage, store.procesos_desde)
try:
    cache = tmpdir("prdrive-kpxc-equipo-")
    keepassxc.cache_equipo = lambda: cache
    keepassxc.extraer_appimage = extraer_falso
    app = tmpdir("prdrive-kpxc-app-") / ".prdrive"
    try:
        keepassxc.preparar_appimage("linux-x64", app)
        c("sin AppImage con sello no se extrae nada", "lanzó nada", "OSError")
    except OSError as e:
        c.contains("sin AppImage con sello no se extrae nada", str(e), "no tiene sello")
    poner_appimage(app, APPIMAGE)
    (cache / "2.7.10" / keepassxc.EXTRAIDO).mkdir(parents=True)          # una vieja
    (cache / "2.7.11").mkdir()                                           # una en uso
    (cache / ".2.7.12.nuevo-999999999").mkdir()                          # un resto
    (cache / f".2.7.12.nuevo-{os.getpid()}9").mkdir()                    # ídem
    vivo = cache / f".2.7.12.nuevo-{os.getppid()}"                       # otra, extrayendo
    vivo.mkdir()
    store.procesos_desde = lambda carpeta: ({1: "keepassxc"} if Path(carpeta).name == "2.7.11"
                                            else {})
    hecho = keepassxc.preparar_appimage("linux-x64", app)
    c("la primera vez se extrae, en su versión", hecho,
      cache / pins.KEEPASSXC_VERSION / keepassxc.EXTRAIDO)
    c("  de una copia en el equipo, no del AppImage de la unidad",
      [p.parent.parent == cache and p.name == components.KEEPASSXC_APPIMAGE
       for p in extracciones], [True])
    c("  que no se queda", sorted(p.name for p in hecho.parent.iterdir()),
      [keepassxc.SELLO_EXTRAIDO, keepassxc.EXTRAIDO])
    c("  con el sello del AppImage del que salió",
      (hecho.parent / keepassxc.SELLO_EXTRAIDO).read_text(encoding="utf-8"), SHA + "\n")
    c("  y la vieja y los restos muertos se van; la que está en uso y la de otra ventana, no",
      sorted(p.name for p in cache.iterdir()),
      sorted(["2.7.11", pins.KEEPASSXC_VERSION, vivo.name]))
    c("la segunda vez no se extrae otra vez",
      (keepassxc.preparar_appimage("linux-x64", app), len(extracciones)), (hecho, 1))
    OTRO = b"\x7fELF otro AppImage de la misma version"
    poner_appimage(app, OTRO)
    keepassxc.preparar_appimage("linux-x64", app)
    c("un AppImage distinto en la unidad se vuelve a extraer",
      ((hecho / "usr" / "bin" / "keepassxc").read_bytes(), len(extracciones)),
      (b"ELF " + OTRO, 2))
    poner_appimage(app, b"\x7fELF estropeado", sha=SHA)
    try:
        keepassxc.preparar_appimage("linux-x64", app)
        c("una copia que no es la del sello no se extrae", "no lanzó", "OSError")
    except OSError as e:
        c.contains("una copia que no es la del sello no se extrae", str(e),
                   "no es la de la unidad")
    c("  ni toca lo que había", (len(extracciones),
                                 (hecho / "usr" / "bin" / "keepassxc").read_bytes()),
      (2, b"ELF " + OTRO))
    poner_appimage(app, APPIMAGE)
    falla_extraer["codigo"] = 1
    try:
        keepassxc.preparar_appimage("linux-x64", app)
        c("una extracción que falla se dice", "no lanzó", "OSError")
    except OSError as e:
        c.contains("una extracción que falla se dice", str(e), "código 1")
    c("  sin restos, y lo de antes sigue en su sitio",
      (sorted(p.name for p in cache.iterdir()),
       (hecho / "usr" / "bin" / "keepassxc").read_bytes()),
      (sorted(["2.7.11", pins.KEEPASSXC_VERSION, vivo.name]), b"ELF " + OTRO))
    falla_extraer["codigo"] = 0
finally:
    keepassxc.cache_equipo, keepassxc.extraer_appimage, store.procesos_desde = reales_extraer


# --- el navegador: los manifiestos
def leer(ruta: Path) -> str | None:
    """Devuelve el texto de un fichero, o `None` si no está."""
    try:
        return ruta.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


reales_nav = (keepassxc.bases_navegador, keepassxc.cache_equipo, store.procesos_desde,
              registro.leer, keepassxc.MANIFIESTOS)
try:
    casa = tmpdir("prdrive-kpxc-casa-")
    bases = {"config": casa / ".config", "data": casa / ".local" / "share", "home": casa}
    keepassxc.bases_navegador = lambda: bases
    cache = tmpdir("prdrive-kpxc-equipo-")
    keepassxc.cache_equipo = lambda: cache
    registro.leer = lambda clave: None
    keepassxc.MANIFIESTOS = True
    store.procesos_desde = lambda carpeta: {}
    proxy = cache / pins.KEEPASSXC_VERSION / keepassxc.EXTRAIDO / keepassxc.PROXY_LINUX
    (bases["config"] / "google-chrome").mkdir(parents=True)          # Chrome y Firefox
    (casa / ".mozilla").mkdir()
    brave = bases["config"] / "BraveSoftware" / "Brave-Browser" / "NativeMessagingHosts"
    brave.mkdir(parents=True)
    AJENO = '{"name": "org.keepassxc.keepassxc_browser", "path": "/usr/bin/keepassxc-proxy"}'
    (brave / f"{keepassxc.HOST_NATIVO}.json").write_text(AJENO, encoding="utf-8")
    rutas = {nombre: ruta for nombre, ruta, _ in keepassxc.manifiestos_linux()}
    c("los manifiestos van donde los busca cada navegador",
      (rutas["chrome"].relative_to(casa).as_posix(), rutas["firefox"].relative_to(casa).as_posix()),
      (".config/google-chrome/NativeMessagingHosts/org.keepassxc.keepassxc_browser.json",
       ".mozilla/native-messaging-hosts/org.keepassxc.keepassxc_browser.json"))
    c("al abrir se escriben", keepassxc.abrir_navegador_linux(proxy), [])
    c("  en los navegadores que hay, con el proxy de lo extraído",
      (leer(rutas["chrome"]), leer(rutas["firefox"]), leer(rutas["chromium"])),
      (keepassxc.manifiesto(proxy, False), keepassxc.manifiesto(proxy, True), None))
    c.contains("  Chromium, con sus extensiones", leer(rutas["chrome"]), keepassxc.ORIGENES[1])
    c.contains("  Firefox, con la suya", leer(rutas["firefox"]), keepassxc.EXTENSION_MOZILLA)
    c("  y el de un KeePassXC instalado no se toca", leer(rutas["brave"]), AJENO)
    viejo = cache / "2.7.11" / keepassxc.EXTRAIDO / keepassxc.PROXY_LINUX
    rutas["chrome"].write_text(keepassxc.manifiesto(viejo, False), encoding="utf-8")
    (rutas["firefox"].parent / "otro.programa.json").write_text("{}", encoding="utf-8")
    keepassxc.abrir_navegador_linux(proxy)
    c("uno nuestro de otra versión se rehace", leer(rutas["chrome"]),
      keepassxc.manifiesto(proxy, False))
    rutas["edge"].parent.mkdir(parents=True)
    rutas["edge"].write_text("no es JSON", encoding="utf-8")
    keepassxc.abrir_navegador_linux(proxy)
    c("  y uno que no se entiende, tampoco se toca", leer(rutas["edge"]), "no es JSON")

    store.procesos_desde = lambda carpeta: {7: str(proxy.with_name("keepassxc"))}
    c("el agente no quita nada con un KeePassXC de lo extraído abierto",
      (keepassxc.cerrar_navegador_linux(muertas=True), leer(rutas["chrome"]) is not None),
      ([], True))
    store.procesos_desde = lambda carpeta: {8: str(proxy)}
    keepassxc.cerrar_navegador(muertas=True)
    c("  con solo el proxy (lo que vive el navegador), sí",
      (leer(rutas["chrome"]), leer(rutas["firefox"])), (None, None))
    store.procesos_desde = lambda carpeta: {}
    keepassxc.abrir_navegador_linux(proxy)
    keepassxc.cerrar_navegador()
    c("al cerrar se quitan los nuestros", (leer(rutas["chrome"]), leer(rutas["firefox"])),
      (None, None))
    c("  y los de otros se quedan", (leer(rutas["brave"]), leer(rutas["edge"]),
                                    leer(rutas["firefox"].parent / "otro.programa.json")),
      (AJENO, "no es JSON", "{}"))
finally:
    (keepassxc.bases_navegador, keepassxc.cache_equipo, store.procesos_desde,
     registro.leer, keepassxc.MANIFIESTOS) = reales_nav


# --- «Abrir llavero» en Linux
class Proc:
    """Un KeePassXC de mentira que sigue abierto, o sale enseguida con `codigo`."""

    def __init__(self, codigo=None):
        self.codigo = codigo

    def poll(self):
        return self.codigo


DEF = {"remote": "nas", "catalog_path": "/prdrive-catalog/remote.toml"}
PAREJA = {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas"}


def config(**llave):
    """Un config con llavero, con esas claves en `[keychain]`."""
    return model.parse_config({"defaults": DEF, "pair": [PAREJA],
                               "keychain": {"base": "personal.kdbx", **llave}})


class Equipo:
    """Lo que el flujo pregunta al equipo, dicho a mano, y lo que se ha lanzado."""

    def __init__(self) -> None:
        self.paquete = "linux-x64"
        self.externo = None
        self.version = None
        self.nuestro = False
        self.otro = False
        self.codigo = None
        self.lanzadas: list = []

    def lanzar(self, orden, entorno):
        self.lanzadas.append((orden, entorno))
        return Proc(self.codigo)


def abrir(cfg, llave=None):
    """Hace «Abrir llavero» y devuelve si se abrió y lo que se dijo."""
    dicho = []

    def esperar(mensaje, funcion):
        try:
            return True, funcion()
        except Exception as e:                            # noqa: BLE001
            return False, e

    hecho = llavero_editor.abrir(cfg, dicho.append, esperar, lambda nombre: llave,
                                 lambda plan, titulo, nota: False, decir_sin_traer=True)
    return hecho, dicho


reales = (keepassxc.paquete_del_equipo, keepassxc.del_equipo, keepassxc.version_del_equipo,
          llavero.keepassxc_abierto, keepassxc.otro_abierto, llavero.atiende_el_servicio,
          llavero.pasada, keepassxc.lanzar, keepassxc.ESPERA_ARRANQUE,
          llavero.lanzar_vigilante, keepassxc.cache_equipo, keepassxc.extraer_appimage,
          registro.escribir, llavero.dormir, keepassxc.bases_navegador)
escritas: list = []
try:
    with sandbox() as root:
        model.APP_DIR = root / ".prdrive"
        eq = Equipo()
        cache = tmpdir("prdrive-kpxc-equipo-")
        keepassxc.paquete_del_equipo = lambda: eq.paquete
        keepassxc.del_equipo = lambda: eq.externo
        keepassxc.version_del_equipo = lambda externo: eq.version
        llavero.keepassxc_abierto = lambda app_dir=None: eq.nuestro
        keepassxc.otro_abierto = lambda: eq.otro
        llavero.atiende_el_servicio = lambda: True               # sin pasada antes de abrir
        llavero.pasada = lambda **k: (0, "")
        keepassxc.lanzar = eq.lanzar
        keepassxc.ESPERA_ARRANQUE = 0.01
        llavero.dormir = lambda segundos: None
        llavero.lanzar_vigilante = lambda: None
        keepassxc.cache_equipo = lambda: cache
        keepassxc.extraer_appimage = extraer_falso
        registro.escribir = lambda clave, valor: escritas.append(clave)
        casa = tmpdir("prdrive-kpxc-casa-")
        (casa / ".mozilla").mkdir()
        keepassxc.bases_navegador = lambda: {"config": casa / ".config", "home": casa,
                                             "data": casa / ".local" / "share"}
        llavero.carpeta().mkdir()
        base = llavero.carpeta() / "personal.kdbx"
        base.write_bytes(b"base")

        c("sin el AppImage en la unidad, se dice cómo ponerlo", abrir(config()),
          (False, [keepassxc.FALTA_KEEPASSXC]))
        poner_appimage(model.APP_DIR, APPIMAGE)
        os.environ["APPIMAGE"] = "/tmp/otro.AppImage"
        hecho, dicho = abrir(config())
        orden, entorno = eq.lanzadas[-1]
        apprun = cache / pins.KEEPASSXC_VERSION / keepassxc.EXTRAIDO / keepassxc.APPRUN
        donde = keepassxc.carpeta_config("linux-x64")
        c("se abre con el AppRun de lo extraído, su configuración de Linux y la base",
          (hecho, dicho, orden),
          (True, [], [str(apprun), "--config", str(donde / keepassxc.INI),
                      "--localconfig", str(donde / keepassxc.INI_LOCAL), str(base)]))
        c("  la configuración, con el proxy de lo extraído",
          f"CustomProxyLocation={apprun.parent / keepassxc.PROXY_LINUX}"
          in (donde / keepassxc.INI).read_text(encoding="utf-8"), True)
        c("  sin el APPIMAGE de otro, y con la raíz para lo que se exporte",
          ("APPIMAGE" in entorno, entorno["KPXC_INITIAL_DIR"]), (False, str(root)))
        c("  el navegador, con su manifiesto", leer(
            casa / ".mozilla" / "native-messaging-hosts" / f"{keepassxc.HOST_NATIVO}.json"),
          keepassxc.manifiesto(apprun.parent / keepassxc.PROXY_LINUX, True))
        c("  y sin tocar el registro", escritas, [])
        os.environ.pop("APPIMAGE")

        eq.nuestro = True
        ini = donde / keepassxc.INI
        ini.write_text("[General]\nUseAtomicSaves=false\n", encoding="utf-8")
        c("ya abierto: se lanza para traerlo delante, sin tocar su configuración",
          (abrir(config()), eq.lanzadas[-1][0][0], ini.read_text(encoding="utf-8")),
          ((True, []), str(apprun), "[General]\nUseAtomicSaves=false\n"))
        eq.nuestro = False

        eq.codigo = 1
        hecho, dicho = abrir(config())
        c("si se cae al abrirse, se dice que se lance desde una terminal",
          (hecho, len(dicho)), (False, 1))
        c.contains("  con lo que se lanzó", dicho[0] if dicho else "", str(apprun))
        eq.codigo = None

        # Linux ARM64: el del equipo
        eq.paquete = None
        c("sin paquete ni KeePassXC en el equipo, se dice", abrir(config()),
          (False, [keepassxc.sin_programa()]))
        c("  y la línea de la ventana, sin botón", llavero_editor.linea(config())[1:],
          (False, False))
        eq.externo = keepassxc.Externo(("/usr/bin/keepassxc",))
        eq.version = "2.7.6"
        eq.otro = True
        llave = root / "personal.keyx"
        llave.write_bytes(b"secreto")
        hecho, dicho = abrir(config(fichero_llave=True), llave=llave)
        c("con el del equipo: se abre aunque ya esté abierto (es el de la persona)",
          (hecho, eq.lanzadas[-1][0]),
          (True, ["/usr/bin/keepassxc", "--keyfile", str(llave), str(base)]))
        c("  avisando de que esa versión no tiene passkeys", dicho,
          [keepassxc.sin_passkeys("2.7.6")])
        c.contains("  (de cuál)", dicho[0] if dicho else "", "2.7.7")
        c("  y la línea de la ventana tiene botón", llavero_editor.linea(config()).abrir, True)
        eq.version = "2.7.12"
        c("con passkeys, sin aviso", abrir(config())[1], [])
        eq.externo = keepassxc.Externo(("/usr/bin/flatpak", "run", keepassxc.FLATPAK_ID),
                                       flatpak=True)
        abrir(config(fichero_llave=True), llave=llave)
        c("el de Flathub, con permiso para la unidad y el fichero llave, y la raíz por --env",
          eq.lanzadas[-1][0],
          ["/usr/bin/flatpak", "run", f"--filesystem={root}", f"--env=KPXC_INITIAL_DIR={root}",
           f"--filesystem={llave.parent}:ro", keepassxc.FLATPAK_ID, "--keyfile", str(llave),
           str(base)])
        c("sin versión conocida, sin aviso", keepassxc.sin_passkeys(None), None)
finally:
    (keepassxc.paquete_del_equipo, keepassxc.del_equipo, keepassxc.version_del_equipo,
     llavero.keepassxc_abierto, keepassxc.otro_abierto, llavero.atiende_el_servicio,
     llavero.pasada, keepassxc.lanzar, keepassxc.ESPERA_ARRANQUE,
     llavero.lanzar_vigilante, keepassxc.cache_equipo, keepassxc.extraer_appimage,
     registro.escribir, llavero.dormir, keepassxc.bases_navegador) = reales
    model.APP_DIR = real_app

# --- «Combinar» en Linux: una terminal, y el código que deja su consola
señal = tmpdir("prdrive-kpxc-combinar-")
codigo = señal / "codigo"
keepassxc.apuntar_codigo(codigo)
c("la consola apunta su pid al empezar",
  (codigo.with_name("pid").read_text(encoding="utf-8"), codigo.exists()),
  (f"{os.getpid()}\n", False))
keepassxc.apuntar_codigo(codigo, 3)
c("  y su código al acabar, que es lo que se espera", keepassxc.esperar_codigo(codigo), 3)
codigo.unlink()
real_dormir, real_vivo = llavero.dormir, store.pid_alive
llavero.dormir = lambda segundos: None
store.pid_alive = lambda pid: False
c("si su proceso se va sin código (se cerró la terminal), -1",
  keepassxc.esperar_codigo(codigo), -1)
codigo.with_name("pid").unlink()
c("  y si nunca llega a arrancar, -1", keepassxc.esperar_codigo(codigo, arranque=0.0), -1)
llavero.dormir, store.pid_alive = real_dormir, real_vivo

real_aqui = keepassxc.combinar_aqui
vistas: list = []
keepassxc.combinar_aqui = lambda base, copia, llave=None: vistas.append((base, copia, llave)) or 5
rc = runsync.combinar_llavero(["b.kdbx", "c.kdbx", "--keyfile", "k.keyx", "--codigo", str(codigo)])
c("runsync --combinar-llavero: con el fichero llave y --codigo, en cualquier orden",
  (rc, vistas[-1], codigo.read_text(encoding="utf-8")),
  (5, (Path("b.kdbx"), Path("c.kdbx"), Path("k.keyx")), "5\n"))
runsync.combinar_llavero(["b.kdbx", "c.kdbx", "--codigo", str(codigo), "--keyfile", "k.keyx"])
c("  (al revés también)", vistas[-1], (Path("b.kdbx"), Path("c.kdbx"), Path("k.keyx")))
c("  sin --codigo, como siempre", (runsync.combinar_llavero(["b.kdbx", "c.kdbx"]), vistas[-1]),
  (5, (Path("b.kdbx"), Path("c.kdbx"), None)))
keepassxc.combinar_aqui = real_aqui

if os.name != "nt":
    real_terminal = keepassxc.terminal
    keepassxc.terminal = lambda: None
    try:
        keepassxc.combinar(Path("b.kdbx"), Path("c.kdbx"))
        c("sin terminal no se combina, y se dice cómo", "no lanzó", "OSError")
    except OSError as e:
        c("sin terminal no se combina, y se dice cómo", str(e), keepassxc.SIN_TERMINAL)
    # Una «terminal» que corre la orden: apunta su pid y, como la consola,
    # su código (el de keepassxc-cli) en el --codigo que le llega.
    falsa = tmpdir("prdrive-kpxc-terminal-") / "terminal.py"
    falsa.write_text(textwrap.dedent("""\
        import os, sys, time
        from pathlib import Path
        args = sys.argv[1:]
        codigo = Path(args[args.index("--codigo") + 1])
        (codigo.parent / "orden").write_text(" ".join(args[2:]))
        (codigo.parent / "pid").write_text(str(os.getpid()))
        time.sleep(0.3)
        codigo.write_text("0")
        """), encoding="utf-8")
    keepassxc.terminal = lambda: [sys.executable, str(falsa)]
    hecho = keepassxc.combinar(Path("/m/.keychain/b.kdbx"), Path("/m/.keychain/c.kdbx"),
                               Path("/k/llave.keyx"))
    c("con terminal, se espera a que su consola acabe y se da su código", hecho, 0)
    keepassxc.terminal = real_terminal
else:
    print("  (saltado) en Windows «Combinar» abre su propia consola")

# --- los dos lanzadores de la raíz
raiz = tmpdir("prdrive-kpxc-lanzadores-")
puestos = llavero.escribir_lanzador(raiz)
c("activarlo pone Llavero.bat y llavero.sh", [p.name for p in puestos],
  [llavero.LANZADOR, llavero.LANZADOR_LINUX])
c("  llavero.sh llama a runsync.sh --llavero con sh (sin bit de ejecución, en exFAT)",
  (raiz / llavero.LANZADOR_LINUX).read_text(encoding="ascii").splitlines()[-1],
  'exec sh "$(dirname "$0")/runsync.sh" --llavero "$@"')
c("  con \\n", b"\r" in (raiz / llavero.LANZADOR_LINUX).read_bytes(), False)
(raiz / llavero.LANZADOR).write_text("@echo off\r\nrem cambiado a mano\r\n", encoding="ascii")
c("desactivarlo quita los nuestros; uno cambiado a mano, no",
  (llavero.quitar_lanzador(raiz), llavero.lanzadores_puestos(raiz)),
  ([llavero.LANZADOR_LINUX], [llavero.LANZADOR]))

sys.exit(c.report())
