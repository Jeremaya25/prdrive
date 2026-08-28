#!/usr/bin/env python3
"""
deploy.py — Instalar el código en el dispositivo, dejarle su config y arrancar
las parejas.

Cuatro cosas, en este orden, y el orden importa:

  1. **Código.** `deploy_code()` copia a `<dispositivo>/.prdrive/` el árbol que el
     instalador lleva dentro, más el binario de rclone de esta arquitectura.
  2. **Conexión.** `write_device_remote()` escribe el `rclone.conf` del
     dispositivo y su clave. Va DESPUÉS del código porque vive dentro de
     `.prdrive/`, y con rutas RELATIVAS porque es lo que hace que el dispositivo
     funcione con otra letra de unidad: rclone las resuelve contra su cwd, y todo
     el proyecto lanza rclone con `cwd = model.APP_DIR`.
  3. **Config.** El `sync_config.toml` con las parejas elegidas, escrito con
     `common/config_file.py` —el mismo serializador que usa la ventana de
     parejas, que vuelve a parsear lo que genera y se niega a escribir si no
     cuadra—.
  4. **Inicialización.** Un `--resync` de las parejas bisync elegidas, lanzando
     el `sync.py` que acaba de aterrizar.

**Esto sustituye a la siembra**, que era un `rclone sync` del espejo maestro del
remoto hacia el dispositivo. El cambio no es de comodidad:

  * el remoto ya no tiene que guardar el programa, solo la configuración;
  * la clave privada deja de dar la vuelta por el servidor para volver a cada
     dispositivo nuevo;
  * y copiar aquí **no borra nada** fuera de `.prdrive/`, mientras que un espejo
     borraba en destino todo lo que no estuviera en el origen. Era lo más
     peligroso del proyecto y ya no existe.

Lo que NO hace, y sigue siendo deliberado: no inicializa parejas `*-mirror`. Un
espejo borra en el otro lado, y lanzarlo con la selección recién hecha y sin
mirar es la forma más rápida de vaciar el destino. Esas se ejecutan a mano y con
`--dry-run`.
"""

from __future__ import annotations

import shutil
import stat
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Mapping

from common import config_file, model

from . import APP_NAME, IS_WIN, InstallError, bundle_dir, python_command
from .profile import Profile, render_conf
from .rclone_bin import bin_subdir, exe_name
from .remote import Catalog, Rclone

# El punto la oculta en Linux y macOS por convención; en Windows hace falta
# además el atributo, que pone `hide()`. Con las dos cosas la carpeta está
# escondida en los dos mundos con un solo nombre.
APP_SUBDIR = f".{APP_NAME}"

# Qué se copia al dispositivo. `install/` NO está y es a propósito: el
# dispositivo no instala nada, y meter el instalador dentro sería arrastrar el
# camino de la clave incrustada a un sitio donde no pinta nada.
#
# `VERSION` sí va, y no es documentación: es lo único que le dice al dispositivo
# qué versión lleva puesta, y sin ello `common/update.py` no tiene contra qué
# comparar la última release. Un dispositivo sin ese fichero es uno instalado
# antes de que existiera el aviso, y se lee como versión desconocida.
DEPLOY_FILES = ("sync.py", "runsync.py", "penwatch.py", "VERSION")
DEPLOY_TREES = ("common", "ui")

# La guía rápida que se le deja al usuario en la raíz, con el nombre con el que
# la va a buscar. Antes vivía ahí y viajaba al remoto por el espejo maestro; sin
# espejo, o la escribe el instalador o no llega. Va aparte de DEPLOY_FILES
# porque es documentación: que falte no puede abortar una instalación.
GUIDE_SOURCE = "device-readme.md"
GUIDE_TARGET = "README.md"
NO_COPIAR = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")

FILE_ATTRIBUTE_HIDDEN = 0x02

LAUNCHER_PYW = f'''\
# runsync.pyw — Lanzador Windows SIN terminal. Doble clic y sale la UI.
# (La asociación .pyw -> pythonw.exe la crea el instalador estándar de Python.)
import runpy
import sys
from pathlib import Path

base = Path(__file__).resolve().parent / "{APP_SUBDIR}"
sys.path.insert(0, str(base))
runpy.run_path(str(base / "runsync.py"), run_name="__main__")
'''

LAUNCHER_SH = f'''\
#!/bin/sh
# runsync.sh — Lanzador para Linux y macOS. El equivalente del .pyw.
# Se escriben los dos siempre: un dispositivo hecho en Windows tiene que
# arrancar igual al enchufarlo en otro sitio, que es la premisa del proyecto.
base="$(cd "$(dirname "$0")" && pwd)/{APP_SUBDIR}"
exec python3 "$base/runsync.py" "$@"
'''


def app_dir(device_root: Path | str) -> Path:
    """Dónde vive el código dentro del dispositivo."""
    return Path(device_root) / APP_SUBDIR


# ---------------------------------------------------------------------------
# El código
# ---------------------------------------------------------------------------

def hide(path: Path | str) -> bool:
    """Marca la carpeta como oculta en Windows. Devuelve si lo ha conseguido.

    No lanza nunca: es un adorno, y un adorno no puede abortar una instalación
    que por lo demás ha ido bien —el mismo criterio que `icons.get()`—. En POSIX
    devuelve True sin hacer nada porque el punto del nombre ya la oculta."""
    if not IS_WIN:
        return True
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.SetFileAttributesW(  # type: ignore[attr-defined]
            str(path), FILE_ATTRIBUTE_HIDDEN))
    except Exception:
        return False


def deploy_source() -> Path:
    """De dónde se copia el código.

    Congelados es el directorio que PyInstaller extrae (ahí lo deja el
    `--add-data` de `build_installer.py`); ejecutando el .py es la raíz del
    checkout. `bundle_dir()` ya distingue los dos casos, así que aquí no hay
    ninguna rama."""
    return bundle_dir()


def deploy_code(device_root: Path | str, rclone_binary: Path | str | None = None,
                origen: Path | str | None = None) -> list[Path]:
    """Copia el programa al dispositivo. Devuelve lo que ha escrito.

    Es una copia, no un espejo: lo que ya hubiera en `.prdrive/` de una versión
    anterior se sobrescribe fichero a fichero, pero nada de fuera se toca. Por
    eso este paso no necesita el «simular y luego hacer» que sí exigía la
    siembra.

    Sin `rclone_binary` no se toca `bin/`, que es el caso de actualizar: el
    binario ya está puesto, no hace falta volver a bajarlo, y pasarle el que hay
    en el propio dispositivo daría `SameFileError`.

    Que sea copia y no espejo tiene una pega asumida: un módulo que se elimine
    del proyecto se queda para siempre en los dispositivos ya instalados. Se
    prefiere a la alternativa —renombrar `.prdrive/` y montar el árbol nuevo al
    lado—, que en Windows choca con el rclone que puede estar corriendo desde
    `bin/`, le hace perder a penwatch su marcador de estructura (y relanzar la
    interfaz solo) y apaga un servicio en marcha al desaparecerle el
    `sync_config.toml`."""
    base = Path(origen) if origen else deploy_source()
    destino = app_dir(device_root)
    escrito: list[Path] = []

    try:
        destino.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise InstallError(f"No he podido crear {destino}: {e}") from e
    hide(destino)

    for nombre in DEPLOY_FILES:
        src = base / nombre
        if not src.is_file():
            raise InstallError(
                f"El instalador no lleva {nombre} dentro (buscado en {base}).\n"
                "Si lo has compilado tú, revisa el --add-data de "
                "build_installer.py.")
        try:
            shutil.copy2(src, destino / nombre)
        except OSError as e:
            raise InstallError(f"No he podido copiar {nombre}: {e}") from e
        escrito.append(destino / nombre)

    for nombre in DEPLOY_TREES:
        src = base / nombre
        if not src.is_dir():
            raise InstallError(
                f"El instalador no lleva el paquete {nombre}/ dentro "
                f"(buscado en {base}).")
        try:
            shutil.copytree(src, destino / nombre, ignore=NO_COPIAR,
                            dirs_exist_ok=True)
        except OSError as e:
            raise InstallError(f"No he podido copiar {nombre}/: {e}") from e
        escrito.append(destino / nombre)

    if rclone_binary is not None:
        escrito.append(copy_rclone(device_root, rclone_binary))
    return escrito


def copy_rclone(device_root: Path | str, rclone_binary: Path | str) -> Path:
    """Deja el binario en `bin/<arch>/`, que es donde lo va a buscar el modelo.

    Se pregunta a `bin_subdir()` en vez de repetir la tabla de arquitecturas: es
    el mismo `bin/` que usará `sync.py` luego, y si dejaran de coincidir el
    instalador verificaría un binario y el dispositivo usaría otro.

    Va SIN el bit de ejecución en exFAT —que no lo tiene—, y por eso
    `model.rclone_binary()` se copia a un temporal cuando hace falta."""
    destino = app_dir(device_root) / "bin" / bin_subdir() / exe_name()
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rclone_binary, destino)
    except OSError as e:
        raise InstallError(f"No he podido copiar rclone a {destino}: {e}") from e
    if not IS_WIN:
        try:
            destino.chmod(destino.stat().st_mode | stat.S_IXUSR | stat.S_IRUSR)
        except OSError:
            pass        # exFAT: no hay permisos que poner, y no pasa nada
    return destino


def write_launchers(device_root: Path | str) -> list[Path]:
    """Los dos lanzadores, en la raíz del volumen.

    Van en `device_root` y no en el dispositivo físico: con VeraCrypt eso significa
    dentro del contenedor, junto a los datos. Es la decisión coherente —todo lo
    del producto vive dentro de lo cifrado— y el precio es que primero hay que
    montar el contenedor."""
    raiz = Path(device_root)
    escrito = []
    for nombre, texto in (("runsync.pyw", LAUNCHER_PYW), ("runsync.sh", LAUNCHER_SH)):
        ruta = raiz / nombre
        try:
            ruta.write_text(texto, encoding="utf-8", newline="\n")
        except OSError as e:
            raise InstallError(f"No he podido escribir {ruta}: {e}") from e
        escrito.append(ruta)
    if not IS_WIN:
        try:
            sh = raiz / "runsync.sh"
            sh.chmod(sh.stat().st_mode | stat.S_IXUSR)
        except OSError:
            pass
    return escrito


def write_guide(device_root: Path | str, origen: Path | str | None = None) -> Path | None:
    """Deja la guía rápida en la raíz. None si el instalador no la lleva dentro.

    Best-effort a propósito: es un documento, y un documento que falte no puede
    dejar a medias una instalación que por lo demás ha ido bien. El mismo
    criterio que `hide()` y que `icons.get()`."""
    base = Path(origen) if origen else deploy_source()
    fuente = base / GUIDE_SOURCE
    destino = Path(device_root) / GUIDE_TARGET
    try:
        if not fuente.is_file():
            return None
        shutil.copy2(fuente, destino)
    except OSError:
        return None
    return destino


# ---------------------------------------------------------------------------
# La conexión del dispositivo
# ---------------------------------------------------------------------------

def write_device_remote(device_root: Path | str, profile: Profile) -> list[Path]:
    """El `rclone.conf` del dispositivo y su clave, con rutas relativas.

    Relativas y no absolutas porque el dispositivo se monta con la letra que le
    toque: `key_file = keys/id_ed25519` vale en `F:` y en `/media/quien/PRDRIVE`,
    y una ruta absoluta solo en el equipo donde se instaló.

    La clave se escribe aquí y **no viaja por el remoto**: no hay ninguna pareja
    que espeje `.prdrive/`, así que se queda en el dispositivo, protegida por lo
    que lo proteja a él (BitLocker, VeraCrypt o nada)."""
    if not profile.configured:
        raise InstallError("No hay conexión configurada que escribir.")

    app = app_dir(device_root)
    keys = app / "keys"
    escrito: list[Path] = []

    key_rel = known_rel = None
    if profile.private_key is not None:
        try:
            keys.mkdir(parents=True, exist_ok=True)
            destino = keys / profile.key_name
            destino.write_bytes(profile.private_key)
            try:
                destino.chmod(0o600)
            except OSError:
                pass    # exFAT/Windows: no hay permisos POSIX que poner
        except OSError as e:
            raise InstallError(f"No he podido escribir la clave en {keys}: {e}") from e
        key_rel = f"keys/{profile.key_name}"
        escrito.append(destino)

        if profile.known_hosts.strip():
            kh = keys / "known_hosts"
            try:
                kh.write_text(profile.known_hosts, encoding="utf-8", newline="\n")
            except OSError as e:
                raise InstallError(f"No he podido escribir {kh}: {e}") from e
            known_rel = "keys/known_hosts"
            escrito.append(kh)

    conf = app / "rclone.conf"
    try:
        app.mkdir(parents=True, exist_ok=True)
        conf.write_text(render_conf(profile, key_file=key_rel, known_file=known_rel),
                        encoding="utf-8", newline="\n")
    except OSError as e:
        raise InstallError(f"No he podido escribir {conf}: {e}") from e
    escrito.append(conf)
    return escrito


# ---------------------------------------------------------------------------
# El sync_config.toml del dispositivo
# ---------------------------------------------------------------------------

def device_config(catalog: Catalog, selected: list[str],
                  catalog_path: str = "") -> dict:
    """El dict crudo del config de ESTE dispositivo: los defaults del catálogo,
    su [daemon] si lo trae, y solo las parejas elegidas.

    Crudo y no `model.Config` porque las `Pair` del modelo llegan con los
    `[defaults]` ya fundidos: volcarlas duplicaría los defaults dentro de cada
    pareja."""
    faltan = [n for n in selected if catalog.pair(n) is None]
    if faltan:
        raise InstallError(
            f"El catálogo no tiene estas parejas: {', '.join(faltan)}.")
    if not selected:
        raise InstallError(
            "Hay que elegir al menos una pareja: un sync_config.toml sin ninguna "
            "no lo acepta sync.py.")

    raw: dict = {}
    if catalog.raw.get("defaults"):
        raw["defaults"] = dict(catalog.raw["defaults"])
    daemon = _daemon_section(catalog, selected)
    if daemon:
        raw["daemon"] = daemon
    if catalog_path:
        # La ruta del catálogo se teclea en el paso 1 y hasta aquí solo servía
        # para descargarlo: no quedaba escrita en ningún sitio, así que el
        # dispositivo instalado volvía a la de por defecto y la ventana de
        # parejas buscaba el catálogo donde no estaba.
        raw.setdefault("defaults", {})["catalog_path"] = catalog_path
    raw["pair"] = [dict(catalog.pair(n)) for n in selected]      # type: ignore[arg-type]
    model.parse_config(raw)                                      # red final
    return raw


def _daemon_section(catalog: Catalog, selected: list[str]) -> dict:
    """El [daemon] del catálogo, recortado a lo que existe en este dispositivo.

    Si nombrara una pareja que este dispositivo no lleva, el servicio fallaría en
    cada ciclo intentando sincronizar algo que no está en su config."""
    daemon = catalog.raw.get("daemon")
    if not isinstance(daemon, dict) or not daemon:
        return {}
    salida = dict(daemon)
    if "pairs" in salida:
        quedan = [n for n in salida["pairs"] if n in selected]
        if quedan:
            salida["pairs"] = quedan
        else:
            salida.pop("pairs")     # sin parejas válidas, mejor el valor por defecto
    return salida


def device_header(catalog: Catalog, endpoint: str = "") -> str:
    """La cabecera del config generado: de dónde sale y cuándo.

    El endpoint del catálogo entra por parámetro y no escrito a mano: durante
    años decía una ruta fija que dejaba de ser verdad en cuanto alguien movía el
    catálogo, y una cabecera que miente es peor que no tener cabecera."""
    donde = endpoint or "el catálogo del remoto"
    propia = (
        f"# Generado por {APP_NAME}-install el {datetime.now():%Y-%m-%d %H:%M}.\n"
        "# Es el config de ESTE dispositivo: el catálogo global vive en\n"
        f"# {donde}. Se puede editar a mano o desde la ventana de\n"
        "# parejas de runsync.\n"
    )
    return propia + (("#\n" + catalog.head) if catalog.head else "")


def config_path(device_root: Path | str) -> Path:
    return app_dir(device_root) / "sync_config.toml"


def write_device_config(device_root: Path | str, catalog: Catalog,
                        selected: list[str], endpoint: str = "",
                        catalog_path: str = "") -> Path:
    """Escribe el sync_config.toml del dispositivo. Devuelve su ruta."""
    destino = config_path(device_root)
    destino.parent.mkdir(parents=True, exist_ok=True)
    config_file.save(device_config(catalog, selected, catalog_path), path=destino,
                     head=device_header(catalog, endpoint))
    return destino


# ---------------------------------------------------------------------------
# Carpetas locales
# ---------------------------------------------------------------------------

def local_dirs(catalog: Catalog, selected: list[str]) -> list[Path]:
    """Las carpetas del dispositivo que necesitan las parejas elegidas.

    Una pareja con `local = "."` no cuenta: es la raíz del volumen, que ya
    existe."""
    salida = []
    for nombre in selected:
        pareja = catalog.pair(nombre) or {}
        local = str(pareja.get("local", "")).replace("\\", "/").strip("/")
        if local and local != ".":
            salida.append(Path(local))
    return salida


def make_local_dirs(device_root: Path | str, catalog: Catalog,
                    selected: list[str]) -> list[Path]:
    """Crea esas carpetas. Devuelve las que se han creado ahora."""
    creadas = []
    for rel in local_dirs(catalog, selected):
        destino = Path(device_root) / rel
        if destino.is_dir():
            continue
        try:
            destino.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise InstallError(f"No he podido crear {destino}: {e}") from e
        creadas.append(destino)
    return creadas


# ---------------------------------------------------------------------------
# Inicialización de las parejas
# ---------------------------------------------------------------------------

def resync_targets(catalog: Catalog, selected: list[str]) -> list[str]:
    """Las parejas elegidas que hay que inicializar: solo las bisync.

    Las `*-mirror` se quedan fuera a propósito: un espejo borra en el otro lado,
    y lanzarlo recién instalado el dispositivo y con las carpetas locales todavía
    vacías propagaría ese vacío. Esas se ejecutan a mano y con --dry-run."""
    return [n for n in selected
            if (catalog.pair(n) or {}).get("mode", model.DEFAULT_MODE) == "bisync"]


def mirror_pairs(catalog: Catalog, selected: list[str]) -> list[str]:
    """Las elegidas que son espejo, para poder avisar de ellas."""
    return [n for n in selected
            if (catalog.pair(n) or {}).get("mode", "") in ("up-mirror", "down-mirror")]


def sync_py(device_root: Path | str) -> Path:
    return app_dir(device_root) / "sync.py"


def resync_command(device_root: Path | str, names: list[str]) -> list[str]:
    """La orden que inicializa las parejas bisync del dispositivo.

    Aquí está la trampa que hace fracasar al instalador compilado:
    `sys.executable` es el propio .exe, no Python, así que usarlo relanzaría el
    instalador en vez de sincronizar. Hay que buscar un intérprete de verdad.

    Va con --yes porque se lanza sin terminal: sin él, la pregunta del resync
    tomaría el valor por defecto (no) y las parejas se saltarían en silencio, que
    es justo lo contrario de lo que se ha pedido."""
    destino = sync_py(device_root)
    if not destino.is_file():
        raise InstallError(
            f"No encuentro {destino}. ¿Se ha instalado el código?")
    if not names:
        raise InstallError("No hay ninguna pareja bisync que inicializar.")
    python = python_command()
    if not python:
        raise InstallError(
            "No encuentro ningún Python instalado en este equipo, y hace falta "
            "para inicializar las parejas.\n\nInstala Python 3.11+ y vuelve a este "
            "paso; el código ya instalado no se pierde.")
    return [*python, str(destino), *names, "--resync", "--yes"]


# ---------------------------------------------------------------------------
# La clave de recuperación de BitLocker
# ---------------------------------------------------------------------------

def upload_recovery_key(rclone: Rclone, texto: str, etiqueta: str,
                        recovery_path: str) -> str:
    """Sube la clave de recuperación de BitLocker al remoto y devuelve su ruta.

    Va al remoto y NO al dispositivo a propósito: una clave de recuperación
    guardada dentro del volumen que descifra no sirve de nada."""
    if not texto.strip():
        raise InstallError("No hay ninguna clave de recuperación que subir.")
    if not recovery_path:
        raise InstallError(
            "No sé dónde guardar la clave de recuperación: falta 'recovery_path' "
            "en el perfil de conexión.")
    nombre = f"BitLocker-{etiqueta}-{datetime.now():%Y%m%d-%H%M}.txt"
    tmpdir = Path(tempfile.mkdtemp(prefix=f"{APP_NAME}-bde-"))
    local = tmpdir / nombre
    try:
        local.write_text(texto, encoding="utf-8")
        destino = rclone.endpoint(f"{recovery_path.rstrip('/')}/{nombre}")
        res = rclone.run("copyto", str(local), destino, capture=True, timeout=120)
        if res.returncode != 0:
            raise InstallError(
                f"No he podido subir la clave al remoto:\n\n{(res.stderr or '').strip()}")
        return destino
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# penwatch, desde el dispositivo ya instalado
# ---------------------------------------------------------------------------

def penwatch_install_command(device_root: Path | str, mode: str = "ui") -> list[str]:
    """Instala el vigilante EN ESTE EQUIPO usando el penwatch del dispositivo.

    Se usa el del dispositivo y no el que lleve el instalador dentro porque es el
    que va a quedarse: así lo que se registra apunta al dispositivo recién
    hecho."""
    destino = app_dir(device_root) / "penwatch.py"
    if not destino.is_file():
        raise InstallError(f"No encuentro {destino}. ¿Se ha instalado el código?")
    python = python_command()
    if not python:
        raise InstallError("No encuentro ningún Python instalado en este equipo.")
    return [*python, str(destino), "install", "--mode", mode]


def summary(catalog: Catalog, selected: list[str]) -> list[tuple[str, str]]:
    """Filas «pareja -> qué le va a pasar», para enseñar antes de tocar nada."""
    filas = []
    for nombre in selected:
        pareja: Mapping = catalog.pair(nombre) or {}
        modo = pareja.get("mode", model.DEFAULT_MODE)
        destino = f"{pareja.get('local', '?')}  <->  {pareja.get('remote_path', '?')}"
        if modo == "bisync":
            nota = "se inicializará con --resync"
        elif modo in ("up-mirror", "down-mirror"):
            nota = "ESPEJO: no se inicializa aquí, pruébala con --dry-run"
        else:
            nota = "no necesita inicialización"
        filas.append((f"{nombre} [{modo}]", f"{destino} — {nota}"))
    return filas
