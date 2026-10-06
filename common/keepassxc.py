#!/usr/bin/env python3
"""KeePassXC en este equipo: su configuración, el navegador, lanzarlo y cerrarlo.

Es lo que hay detrás de «Abrir llavero» (`ui/tk_llavero.py`; `runsync.py
--llavero`) y, al expulsar (`cerrar_llavero()`; `runsync.py --cerrar-llavero`),
de cerrarlo, subir lo pendiente y dejar el registro como estaba. La base y su
sincronización son de `common/llavero.py`; esto es el programa. Windows (x64,
y ARM64 con el x64 emulado) y Linux (x64 con el AppImage; ARM64 con el
KeePassXC del equipo, §11 de la especificación).

Dónde está cada cosa:
- El programa, en `.prdrive/keepassxc/<paquete>/`. En Windows, tal cual viene
  en el ZIP (con `.portable`). En Linux, el AppImage entero, que no se ejecuta
  desde la unidad: se extrae una vez por equipo y versión en
  `~/.cache/prdrive/keepassxc/<versión>/` (`preparar_appimage()`). Así no hace
  falta FUSE 2, da igual que el volumen sea `noexec` (o exFAT, que no guarda
  el bit de ejecución ni los enlaces del AppImage), y ni KeePassXC ni su proxy
  retienen el volumen. Lo pone y lo cambia `install/keepassxc_bin.py`, que
  sustituye esa carpeta entera.
- Su configuración, aparte, en `.prdrive/keepassxc/config/windows/` o
  `config/linux/` (`keepassxc.ini`, `keepassxc_local.ini` y `raiz.txt`), y se
  le pasa con `--config` y `--localconfig` (`src/main.cpp`). Así cambiar de
  versión no la toca.
- Los JSON del navegador: en Windows, en `<exe>/config/`, donde los pone
  `.portable` (`NativeMessageInstaller::getNativeMessagePath()`), y KeePassXC
  los rehace en cada arranque (`updateBinaryPaths()`), así que perderlos no
  importa. En Linux, en las carpetas de cada navegador del equipo, y los
  escribe prdrive (`abrir_navegador_linux()`).
- La ruta del fichero llave, en `state/keychain.json`, una por equipo. El
  fichero ni se abre: solo hace falta para combinar (`--key-file` de
  `keepassxc-cli`); al abrir, KeePassXC lo pide en su diálogo.

Lo que toca el equipo (`registro.*`, `store.procesos()`, `lanzar()`) son
funciones de módulo que los tests sustituyen; lo demás decide sin tocar nada,
o toca solo ficheros del dispositivo.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Mapping, NamedTuple

from . import APP_NAME, components, conflicts, llavero, model, pins, registro, results, store

CONFIG_SUBDIR = Path("config") / "windows"
"""Dónde va la configuración del KeePassXC de Windows, dentro de `.prdrive/keepassxc/`."""
CONFIG_LINUX = Path("config") / "linux"
"""Y la del de Linux: otra, porque las rutas de un sistema no le sirven al otro."""
INI = "keepassxc.ini"
"""La configuración que viaja (`Roaming` en `src/core/Config.cpp`)."""
INI_LOCAL = "keepassxc_local.ini"
"""La del equipo (`Local`): las bases recientes, el último directorio, el desbloqueo rápido."""
RAIZ = "raiz.txt"
"""La raíz del volumen con la que se abrió la última vez, para mover las rutas recientes."""
FIN_DE_LINEA = "\r\n"
"""Con el que escribe QSettings en Windows, para un fichero que se crea aquí (en Linux, `\\n`)."""

SIEMPRE = {
    "UseAtomicSaves": "true",           # deshace un «Deshabilitar almacenajes seguros» (H-11)
    "Browser/UpdateBinaryPath": "true",  # que rehaga los JSON del navegador al arrancar
    "GUI/CheckForUpdates": "false",     # la versión la pone prdrive
}
"""Lo que se pone en `keepassxc.ini` en cada arranque, diga lo que diga."""
SIEMPRE_LINUX = {
    "UseAtomicSaves": "true",
    # Los manifiestos del navegador los escribe prdrive (`abrir_navegador_linux()`):
    # rehacerlos al arrancar pisaría los de un KeePassXC instalado.
    "Browser/UpdateBinaryPath": "false",
    "GUI/CheckForUpdates": "false",
    # Extraído, el AppImage no tiene `$APPIMAGE`, que es lo que pondría en un
    # manifiesto (`getInstalledProxyPath()`): se le da el proxy de verdad.
    "Browser/UseCustomProxy": "true",
}
"""Lo de `SIEMPRE` en Linux; `Browser/CustomProxyLocation` se añade al lanzar (`ajustar_config()`)."""
AL_CREAR = {
    "Browser/Enabled": "true",
    # La ruta del fichero llave la recuerda prdrive por equipo; KeePassXC
    # propondría en un equipo la del otro.
    "RememberLastKeyFiles": "false",
    "UpdateCheckMessageShown": "true",
    "BackupBeforeSave": "false",        # ya es lo de fábrica
    "GUI/MinimizeOnClose": "false",     # ídem
}
"""Lo que se pone en `keepassxc.ini` solo al crearlo: después manda la persona."""
AL_CREAR_LOCAL = {
    "Security/QuickUnlock": "false",    # Windows Hello deja una credencial en el equipo (H-1)
}
"""Lo que se pone en `keepassxc_local.ini` solo al crearlo."""
RECIENTES = ("LastOpenedDatabases", "LastDatabases", "LastActiveDatabase", "LastDir")
"""Las claves con rutas que se mueven a la raíz de ahora (las cuatro son `Local`)."""

HOST_NATIVO = "org.keepassxc.keepassxc_browser"
"""El nombre del anfitrión de mensajería nativa (`NativeMessageInstaller.cpp`, `HOST_NAME`)."""
NAVEGADORES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Software\\Google\\Chrome", ("chrome", "vivaldi", "brave")),
    ("Software\\Microsoft\\Edge", ("edge",)),
    ("Software\\Mozilla", ("firefox", "tor-browser")),
    ("Software\\Chromium", ("chromium",)),
)
"""Las cuatro claves de `HKCU` que mira KeePassXC (`TARGET_DIR_*`), y los navegadores de cada una.

Chrome, Vivaldi y Brave comparten la de Chrome, y Firefox y Tor la de Mozilla
(H-5). El primer nombre es el del JSON al que apunta prdrive; los demás, los
que puede haber dejado un KeePassXC instalado (`getBrowserName()`).
"""

CLI = "keepassxc-cli.exe"
"""La línea de órdenes de KeePassXC, que viene en el mismo ZIP que el programa."""
EXTRAIDO = "squashfs-root"
"""La carpeta que deja `--appimage-extract` donde se le ejecuta."""
SELLO_EXTRAIDO = "PRDRIVE-EXTRAIDO"
"""Al lado de `EXTRAIDO`: el SHA-256 del AppImage del que salió. Se escribe el último."""
APPRUN = "AppRun"
"""El arranque del AppImage extraído: elige `keepassxc`, `cli` o `proxy`."""
CLI_LINUX = Path("usr") / "bin" / "keepassxc-cli"
"""La línea de órdenes, dentro de lo extraído (encuentra sus bibliotecas sola: `RUNPATH`)."""
PROXY_LINUX = Path("usr") / "bin" / "keepassxc-proxy"
"""El proxy del navegador, dentro de lo extraído."""
ESPERA_EXTRAER = 180.0  # segundos
"""Lo más que se espera a `--appimage-extract` (son ~125 MB)."""
FLATPAK_ID = "org.keepassxc.KeePassXC"
"""El KeePassXC de Flathub."""
PASSKEYS_DESDE = (2, 7, 7)
"""La primera versión de KeePassXC con passkeys (§11: Debian 12 y Ubuntu 24.04 no la tienen)."""
PROXY = "keepassxc-proxy.exe"
"""El proxy del navegador: lo lanza el navegador, y retiene el volumen (K6, H-16)."""
CREATE_NEW_CONSOLE = 0x00000010
"""Flag de creación de procesos de Windows: el hijo tiene su propia consola, a la vista."""

VC_FALTA = (0xC0000135, -1073741515)
"""`STATUS_DLL_NOT_FOUND`, con y sin signo: falta el runtime de Visual C++ (K3)."""
ESPERA_ARRANQUE = 1.5  # segundos
"""Lo que se mira si KeePassXC se cae nada más lanzarlo (sin el runtime, no llega a abrirse)."""
DESDE_LA_ULTIMA = 120.0  # segundos
"""«Traer lo último»: una pasada antes de abrir si la última buena es más vieja."""


# --- dónde está cada cosa

def paquete_del_equipo() -> str | None:
    """Devuelve el paquete de KeePassXC que sirve en este equipo, o `None` si ninguno.

    Windows ARM64 usa el x64 emulado; Linux ARM64 no tiene, y usa el del equipo
    (`del_equipo()`); otro sistema, ninguno (`pins.KEEPASSXC_PARA`). Es de
    módulo para que los tests elijan el equipo.
    """
    arm = model.arch_dir() == "arm"
    if os.name == "nt":
        return pins.KEEPASSXC_PARA.get("windows-arm64" if arm else "windows-x64")
    if sys.platform.startswith("linux"):
        return pins.KEEPASSXC_PARA.get("linux-arm64" if arm else "linux-x64")
    return None


def es_appimage(paquete: str | None) -> bool:
    """Indica si ese paquete es el AppImage de Linux (y no el ZIP de Windows)."""
    return bool(paquete) and components.keepassxc_programa(paquete) == components.KEEPASSXC_APPIMAGE


def ejecutable() -> Path | None:
    """Devuelve el programa de KeePassXC de la unidad para este equipo, o `None` si no hay paquete.

    `KeePassXC.exe` en Windows; en Linux, el AppImage, que no se lanza tal
    cual (`preparar_appimage()`).
    """
    paquete = paquete_del_equipo()
    return None if paquete is None else components.keepassxc_exe(model.APP_DIR, paquete)


def cli() -> Path | None:
    """Devuelve con qué combinar desde este equipo (`keepassxc-cli`), o `None` si no hay.

    En Windows, el `keepassxc-cli.exe` del ZIP. En Linux, el AppImage de la
    unidad, que lo lleva dentro (`cli_lanzable()` lo extrae), o el
    `keepassxc-cli` del equipo en Linux ARM64.
    """
    paquete = paquete_del_equipo()
    if paquete is None:
        hallado = shutil.which("keepassxc-cli") if sys.platform.startswith("linux") else None
        return Path(hallado) if hallado else None
    exe = components.keepassxc_exe(model.APP_DIR, paquete)
    return exe if es_appimage(paquete) else exe.with_name(CLI)


def cli_lanzable(programa: Path) -> Path:
    """Devuelve el `keepassxc-cli` que se ejecuta a partir de lo que dio `cli()`.

    Del AppImage, el de dentro de lo extraído en este equipo (lo extrae si
    hace falta); si no, el mismo.

    Raises:
        OSError: Si no se ha podido extraer.
    """
    paquete = paquete_del_equipo()
    if es_appimage(paquete) and programa == components.keepassxc_exe(model.APP_DIR, paquete):
        return preparar_appimage(paquete) / CLI_LINUX
    return programa


def carpeta_config(paquete: str | None = None) -> Path:
    """Devuelve la carpeta de la configuración de KeePassXC (`keepassxc/config/<sistema>/`).

    Args:
        paquete: El de KeePassXC que se va a lanzar; por defecto, el de este
            equipo.
    """
    paquete = paquete_del_equipo() if paquete is None else paquete
    sub = CONFIG_LINUX if es_appimage(paquete) else CONFIG_SUBDIR
    return model.APP_DIR / components.KEEPASSXC_SUBDIR / sub


# --- Linux: el AppImage, extraído en el equipo

def cache_equipo() -> Path:
    """Devuelve dónde se extrae el AppImage en este equipo (`~/.cache/prdrive/keepassxc/`).

    Es la caché del usuario (`XDG_CACHE_HOME`), no el temporal: sobrevive a un
    reinicio y no hay que extraerlo cada vez. Es de módulo para que los tests
    la lleven a un temporal.
    """
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / APP_NAME / components.KEEPASSXC_SUBDIR


def extraer_appimage(appimage: Path, donde: Path) -> int:
    """Corre `<appimage> --appimage-extract` en `donde`, que deja ahí `squashfs-root/`.

    Lo hace el propio AppImage (su runtime), sin FUSE. Es de módulo para que
    los tests no ejecuten nada.

    Returns:
        Su código: 0 si ha ido bien.
    """
    entorno_ = {k: v for k, v in os.environ.items() if k not in ("APPIMAGE", "APPDIR")}
    try:
        return subprocess.run([str(appimage), "--appimage-extract"], cwd=donde,
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, env=entorno_,
                              timeout=ESPERA_EXTRAER).returncode
    except subprocess.TimeoutExpired:
        return -1


def _resumen(ruta: Path) -> str:
    """Devuelve el SHA-256 de un fichero, leyéndolo a trozos."""
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for trozo in iter(lambda: f.read(1024 * 1024), b""):
            h.update(trozo)
    return h.hexdigest()


_VERSION_SEGURA = re.compile(r"[0-9A-Za-z][0-9A-Za-z.\-]*")


def preparar_appimage(paquete: str, app_dir: Path | None = None) -> Path:
    """Devuelve la carpeta extraída del AppImage de la unidad en este equipo.

    Se extrae una vez por versión, en `cache_equipo()/<versión>/`, y la
    siguiente vez se usa si su `SELLO_EXTRAIDO` es el SHA-256 del AppImage que
    dice el sello de la unidad. Para extraer, el AppImage se copia antes a la
    caché y se comprueba contra ese mismo SHA-256: así da igual que el volumen
    sea `noexec` o exFAT. Lo extraído se coloca de un renombrado, con el sello
    escrito el último, y las versiones viejas se borran si no corre nada desde
    ellas.

    Args:
        paquete: El paquete de Linux (`linux-x64`).
        app_dir: La carpeta del código de la unidad; por defecto, esta.

    Returns:
        La carpeta `squashfs-root/`, con `AppRun` dentro.

    Raises:
        OSError: Si falta el sello, la copia no cuadra o no se ha podido
            extraer.
    """
    app = model.APP_DIR if app_dir is None else app_dir
    appimage = components.keepassxc_exe(app, paquete)
    sello = components.keepassxc_sello(app, paquete)
    version = sello.get(components.KEEPASSXC, "")
    try:
        texto = (components.keepassxc_dir(app, paquete) / components.KEEPASSXC_STAMP).read_text(
            encoding="utf-8")
    except (OSError, ValueError):
        texto = ""
    esperado = components.keepassxc_ficheros(texto).get(components.KEEPASSXC_APPIMAGE)
    if not esperado or not _VERSION_SEGURA.fullmatch(version):
        raise OSError("el KeePassXC de la unidad no tiene sello: «Actualizar…» lo vuelve "
                      "a poner")
    destino = cache_equipo() / version
    hecho = destino / EXTRAIDO
    try:
        if ((destino / SELLO_EXTRAIDO).read_text(encoding="utf-8").strip() == esperado
                and (hecho / APPRUN).is_file()):
            return hecho
    except OSError:
        pass
    nuevo = cache_equipo() / f".{version}.nuevo-{os.getpid()}"
    shutil.rmtree(nuevo, ignore_errors=True)
    nuevo.mkdir(parents=True)
    try:
        copia = nuevo / components.KEEPASSXC_APPIMAGE
        shutil.copyfile(appimage, copia)
        if _resumen(copia) != esperado:
            raise OSError("la copia del AppImage no es la de la unidad: ¿falla la unidad?")
        copia.chmod(0o700)
        codigo = extraer_appimage(copia, nuevo)
        if codigo != 0 or not (nuevo / EXTRAIDO / APPRUN).is_file():
            raise OSError(f"no se ha podido extraer el AppImage (código {codigo})")
        copia.unlink()
        (nuevo / SELLO_EXTRAIDO).write_text(esperado + "\n", encoding="utf-8")
        viejo = cache_equipo() / f".{version}.viejo-{os.getpid()}"
        apartado = destino.exists()
        if apartado:
            os.replace(destino, viejo)
        try:
            os.replace(nuevo, destino)
        except OSError:
            if apartado:
                os.replace(viejo, destino)
            raise
        shutil.rmtree(viejo, ignore_errors=True)
    except BaseException:
        shutil.rmtree(nuevo, ignore_errors=True)
        raise
    _barrer_versiones(version)
    return hecho


_RESTO = re.compile(r"\..+\.(?:nuevo|viejo)-(\d+)")


def _barrer_versiones(actual: str) -> None:
    """Borra lo extraído de otras versiones, si no corre nada desde ellas, y los restos.

    Un resto (`.<versión>.nuevo-<pid>`) solo si su proceso ya no vive: otra
    ventana puede estar extrayendo a la vez.
    """
    try:
        otras = [p for p in cache_equipo().iterdir() if p.is_dir() and p.name != actual]
    except OSError:
        return
    # Uno abierto de una versión que no se sabe (`abiertos_de_la_cache()`) puede
    # ser de cualquiera: esta vez no se barre ninguna.
    sin_version = None in abiertos_de_la_cache().values()
    for otra in otras:
        resto = _RESTO.fullmatch(otra.name)
        if resto is not None:
            if not store.pid_alive(int(resto.group(1))):
                shutil.rmtree(otra, ignore_errors=True)
        elif not otra.name.startswith(".") and not sin_version \
                and not store.procesos_desde(otra):
            shutil.rmtree(otra, ignore_errors=True)


def lanzado_por_prdrive(orden_: list[str]) -> bool:
    """Indica si esa línea de órdenes es la de un KeePassXC que abrió prdrive en Linux.

    Es la de `orden()`: su `--config` está en `keepassxc/config/linux/` de una
    unidad, sea cuál sea. Así se lanza siempre de lo extraído en la caché.
    """
    final = (components.KEEPASSXC_SUBDIR, *CONFIG_LINUX.parts)
    return any(Path(arg).parent.parts[-len(final):] == final
               for arg in orden_[1:] if os.path.isabs(arg))


def abiertos_de_la_cache() -> dict[int, str | None]:
    """Devuelve los KeePassXC que corren de lo extraído: `{pid: su versión, o None si no se sabe}`.

    Se ve por su ejecutable (`store.procesos_desde()`), salvo para quien no es
    root: KeePassXC se hace no volcable al arrancar y su `exe` no se deja
    mirar (`store.sin_exe()`). Entonces cuenta uno que abrió prdrive
    (`lanzado_por_prdrive()`), sin saber de qué versión.
    """
    salida: dict[int, str | None] = {}
    cache = cache_equipo()
    for pid, exe in store.procesos_desde(cache).items():
        if Path(exe).name == llavero.KEEPASSXC_LINUX:
            try:
                salida[pid] = Path(exe).resolve().relative_to(cache.resolve()).parts[0]
            except (OSError, ValueError, IndexError):
                salida[pid] = None
    for pid, nombre in store.sin_exe().items():
        if nombre == llavero.KEEPASSXC_LINUX and lanzado_por_prdrive(store.orden_de(pid)):
            salida.setdefault(pid, None)
    return salida


class Externo(NamedTuple):
    """El KeePassXC instalado en este equipo Linux, para cuando la unidad no trae uno.

    Args:
        orden: Cómo se lanza (`keepassxc`, o `flatpak run org.keepassxc.KeePassXC`).
        flatpak: Si es el de Flathub, que necesita permisos para ver la unidad.
    """
    orden: tuple[str, ...]
    flatpak: bool = False


def del_equipo() -> Externo | None:
    """Devuelve el KeePassXC instalado en este equipo Linux, o `None`.

    Es Linux ARM64, que no tiene AppImage (§11): el del sistema, o el de
    Flathub. Solo mira si están, sin ejecutar nada: lo pregunta la ventana al
    pintarse. Es de módulo para que los tests elijan el equipo.
    """
    if not sys.platform.startswith("linux"):
        return None
    propio = shutil.which(llavero.KEEPASSXC_LINUX)
    if propio:
        return Externo((propio,))
    flatpak = shutil.which("flatpak")
    instalado = [Path.home() / ".local/share/flatpak/app" / FLATPAK_ID,
                 Path("/var/lib/flatpak/app") / FLATPAK_ID]
    if flatpak and any(p.is_dir() for p in instalado):
        return Externo((flatpak, "run", FLATPAK_ID), flatpak=True)
    return None


def version_del_equipo(externo: Externo) -> str | None:
    """Devuelve la versión del KeePassXC del equipo, o `None` si no se sabe.

    `keepassxc-cli --version` (la GUI la diría solo con pantalla), o `flatpak
    info`. Es de módulo para que los tests no ejecuten nada.
    """
    if externo.flatpak:
        orden_ = [externo.orden[0], "info", FLATPAK_ID]
    else:
        cli_ = shutil.which("keepassxc-cli")
        if not cli_:
            return None
        orden_ = [cli_, "--version"]
    try:
        salida = subprocess.run(orden_, capture_output=True, text=True, timeout=15,
                                stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    hallada = re.search(r"(\d+\.\d+\.\d+)", salida)
    return hallada.group(1) if hallada else None


def sin_passkeys(version: str | None) -> str | None:
    """Devuelve el aviso de un KeePassXC del equipo sin passkeys, o `None`."""
    if version is None:
        return None
    try:
        partes = tuple(int(x) for x in version.split(".")[:3])
    except ValueError:
        return None
    if partes >= PASSKEYS_DESDE:
        return None
    return (f"Este equipo tiene KeePassXC {version}: abre la base, pero no tiene passkeys "
            f"(llegan en la {'.'.join(map(str, PASSKEYS_DESDE))}). Las contraseñas sí.")


# --- la configuración, línea a línea

_SECCION = re.compile(r"^\s*\[(.*)\]\s*$")


def _partir(clave: str) -> tuple[str, str]:
    """Devuelve la sección y la clave del ini: `GUI/X` → (`GUI`, `X`); sin `/`, `[General]`."""
    if "/" in clave:
        seccion, nombre = clave.split("/", 1)
        return seccion, nombre
    return "General", clave


def _completa(seccion: str, nombre: str) -> str:
    """Devuelve la clave como la nombra KeePassXC: sin sección si es `[General]`."""
    return nombre if seccion.lower() == "general" else f"{seccion}/{nombre}"


def editar_ini(texto: str, valores: Mapping[str, str],
               cambiar: Callable[[str, str], str] | None = None,
               fin: str = FIN_DE_LINEA) -> str:
    """Cambia unas claves de un ini de QSettings y deja el resto byte a byte.

    No se lee y reescribe el fichero entero (como haría `configparser`): se
    tocan solo las líneas de esas claves, y las que faltan se añaden al final
    de su sección, o en una sección nueva al final. Las claves se comparan sin
    mayúsculas, como QSettings en Windows. Las que no son `[General]` van con
    su sección delante (`GUI/CheckForUpdates`), como en `src/core/Config.cpp`.

    Args:
        texto: El ini, o "" si no existe.
        valores: Clave → valor que tiene que quedar.
        cambiar: Para las claves que están y no van en `valores`: recibe la
            clave y su valor tal cual y devuelve el valor que tiene que quedar.
        fin: El fin de línea si el texto no trae ninguno.
    """
    nl = "\r\n" if "\r\n" in texto else ("\n" if "\n" in texto else fin)
    lineas = texto.splitlines(keepends=True)
    pedidas = {k.lower(): v for k, v in valores.items()}
    vistas: set[str] = set()
    ultima: dict[str, int] = {}          # sección → su última línea
    seccion = "General"
    for i, linea in enumerate(lineas):
        cuerpo = linea.rstrip("\r\n")
        m = _SECCION.match(cuerpo)
        if m is not None:
            seccion = m.group(1)
            ultima[seccion.lower()] = i
            continue
        if "=" not in cuerpo or cuerpo.lstrip().startswith((";", "#")):
            continue
        izquierda, valor = cuerpo.split("=", 1)
        clave = _completa(seccion, izquierda.strip())
        ultima[seccion.lower()] = i
        nuevo = pedidas.get(clave.lower())
        if nuevo is not None:
            vistas.add(clave.lower())
        elif cambiar is not None:
            nuevo = cambiar(clave, valor)
        if nuevo is not None and nuevo != valor:
            lineas[i] = f"{izquierda}={nuevo}{linea[len(cuerpo):]}"

    faltan: dict[str, list[str]] = {}
    for clave, valor in valores.items():
        if clave.lower() not in vistas:
            sec, nombre = _partir(clave)
            faltan.setdefault(sec, []).append(f"{nombre}={valor}{nl}")
    if not faltan:
        return "".join(lineas)

    def cerrar(i: int) -> None:
        """Pone fin de línea a la línea `i` si no lo tiene, para escribir detrás."""
        if not lineas[i].endswith(("\n", "\r")):
            lineas[i] += nl

    dentro = sorted(((ultima[s.lower()], nuevas) for s, nuevas in faltan.items()
                     if s.lower() in ultima), reverse=True)
    for i, nuevas in dentro:
        cerrar(i)
        lineas[i + 1:i + 1] = nuevas
    for sec, nuevas in faltan.items():
        if sec.lower() in ultima:
            continue
        if lineas:
            cerrar(len(lineas) - 1)
            if lineas[-1].strip():
                lineas.append(nl)
        lineas.append(f"[{sec}]{nl}")
        lineas.extend(nuevas)
    return "".join(lineas)


_RAIZ_SEGURA = re.compile(r"[A-Za-z0-9_.\-:/()]+(?: [A-Za-z0-9_.\-:/()]+)*")
"""Una raíz que se busca tal cual en un ini de QSettings: nada que escape o entrecomille."""


def forma_ini(raiz: Path | str) -> str | None:
    """Devuelve la raíz como queda en las rutas de KeePassXC (`E:` o `C:/x/raíz`).

    KeePassXC guarda las rutas con `/` (`QFileInfo::absoluteFilePath()`). Una
    raíz con algo que QSettings escaparía (fuera de ASCII, comas, comillas…)
    da `None`: buscarla tal cual podría no encontrarla, o cambiar lo que no es.
    """
    texto = str(raiz).replace("\\", "/").rstrip("/")
    return texto if _RAIZ_SEGURA.fullmatch(texto) else None


def mover_raiz(valor: str, antes: str, ahora: str) -> str:
    """En el valor de una ruta reciente, cambia la raíz `antes` por `ahora`.

    Cada elemento de una lista de QSettings (`a, b` o `"a", "b"`) que empiece
    por la raíz anterior, con `/` o con `\\` (que QSettings escribe `\\\\`).

    Args:
        valor: El valor tal cual, detrás del `=`.
        antes: La raíz anterior, como la da `forma_ini()`.
        ahora: La de ahora, ídem.
    """
    atras = antes.replace("/", "\\\\")
    patron = re.compile(r'(^\s*|"|,\s*)(' + re.escape(antes) + "|" + re.escape(atras)
                        + r')(?=/|\\\\|"|,|\s*$)', re.IGNORECASE)

    def poner(m: re.Match) -> str:
        """Pone la raíz de ahora con las barras de la que había."""
        con_atras = atras != antes and m.group(2).lower() == atras.lower()
        return m.group(1) + (ahora.replace("/", "\\\\") if con_atras else ahora)

    return patron.sub(poner, valor)


def _escribir(ruta: Path, datos: bytes) -> None:
    """Escribe un fichero de la configuración de una vez (temporal y `os.replace`).

    Raises:
        OSError: Si no se ha podido.
    """
    tmp = ruta.with_name(ruta.name + ".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    with os.fdopen(fd, "wb") as f:
        f.write(datos)
    os.replace(tmp, ruta)


def ajustar_config(raiz: Path | None = None, paquete: str | None = None,
                   proxy: Path | None = None) -> list[str]:
    """Deja la configuración de KeePassXC como la quiere prdrive, con KeePassXC cerrado.

    Cada arranque, `SIEMPRE` (en Linux, `SIEMPRE_LINUX` y el proxy) y las
    rutas recientes movidas a la raíz de ahora (la de la vez anterior está en
    `raiz.txt`: la letra o el punto de montaje cambian de un equipo a otro).
    Al crear un fichero, además `AL_CREAR` / `AL_CREAR_LOCAL`. Los dos
    ficheros a la vez: KeePassXC trata un `keepassxc_local.ini` sin su
    `keepassxc.ini` como una configuración vieja y lo mueve (`Config::init()`).
    Los bytes se leen y se escriben tal cual (`surrogateescape`): QSettings
    escapa lo que no es ASCII, pero un fichero tocado a mano no se estropea.

    Args:
        raiz: La raíz del volumen; sin ella, la de este dispositivo.
        paquete: El KeePassXC que se va a lanzar; por defecto, el de este
            equipo. Dice qué carpeta y qué fin de línea.
        proxy: En Linux, el `keepassxc-proxy` de lo extraído en este equipo,
            para `Browser/CustomProxyLocation`. Una ruta que QSettings
            escaparía (`forma_ini()`) no se pone.

    Returns:
        Los ficheros que ha escrito.

    Raises:
        OSError: Si no se ha podido leer o escribir.
    """
    raiz = model.DEVICE_ROOT if raiz is None else raiz
    paquete = paquete_del_equipo() if paquete is None else paquete
    linux = es_appimage(paquete)
    donde = carpeta_config(paquete)
    siempre = dict(SIEMPRE_LINUX if linux else SIEMPRE)
    if linux and proxy is not None and forma_ini(proxy) is not None:
        siempre["Browser/CustomProxyLocation"] = str(proxy)
    fin = "\n" if linux else FIN_DE_LINEA
    donde.mkdir(parents=True, exist_ok=True)
    ahora = forma_ini(raiz)
    try:
        antes = (donde / RAIZ).read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        antes = None
    recientes = {k.lower() for k in RECIENTES}

    def cambiar(clave: str, valor: str) -> str:
        """Mueve a la raíz de ahora las rutas de las claves recientes."""
        return mover_raiz(valor, antes, ahora) if clave.lower() in recientes else valor

    movida = bool(antes and ahora and antes.lower() != ahora.lower())
    escritos = []
    for nombre, fijas, al_crear in ((INI, siempre, AL_CREAR), (INI_LOCAL, {}, AL_CREAR_LOCAL)):
        ruta = donde / nombre
        try:
            texto, nuevo = ruta.read_bytes().decode("utf-8", "surrogateescape"), False
        except FileNotFoundError:
            texto, nuevo = "", True
        editado = editar_ini(texto, {**al_crear, **fijas} if nuevo else fijas,
                             cambiar if movida else None, fin)
        if nuevo or editado != texto:
            _escribir(ruta, editado.encode("utf-8", "surrogateescape"))
            escritos.append(nombre)
    if ahora is not None and ahora != antes:
        _escribir(donde / RAIZ, (ahora + "\n").encode("utf-8"))
        escritos.append(RAIZ)
    return escritos


# --- el navegador (HKCU\Software\…\NativeMessagingHosts)

def clave_nativa(base: str) -> str:
    """Devuelve la clave de KeePassXC-Browser bajo la de un navegador."""
    return f"{base}\\NativeMessagingHosts\\{HOST_NATIVO}"


def json_nativo(carpeta: Path, navegador: str) -> Path:
    """Devuelve el JSON de mensajería nativa de ese navegador en esa carpeta (`%1/%2_%3.json`)."""
    return carpeta / f"{HOST_NATIVO}_{navegador}.json"


def abrir_navegador(exe: Path) -> list[str]:
    """Apunta las cuatro claves del navegador a los JSON del KeePassXC de la unidad.

    Se escriben las cuatro, haya lo que haya: en Windows `isBrowserEnabled()`
    solo mira que la clave tenga valor, y al arrancar `updateBinaryPaths()`
    rehace el JSON y la clave de todo lo «habilitado». Es lo que configura un
    equipo nuevo sin pasos (B2, B3); KeePassXC se las quedaría igualmente (B5).

    Returns:
        Lo que no se ha podido escribir, para decirlo; vacío si todo bien.
    """
    carpeta = exe.parent / "config"
    fallos = []
    for base, nombres in NAVEGADORES:
        try:
            registro.escribir(clave_nativa(base), str(json_nativo(carpeta, nombres[0])))
        except OSError as e:
            fallos.append(f"{clave_nativa(base)}: {e}")
    return fallos


def instalado() -> Path | None:
    """Devuelve dónde deja los JSON un KeePassXC instalado (`%LOCALAPPDATA%\\KeePassXC`)."""
    local = os.environ.get("LOCALAPPDATA")
    return Path(local) / "KeePassXC" if local else None


def _comparable(ruta: str) -> str:
    """Devuelve una ruta de Windows para comparar: con `\\` y en minúsculas."""
    return ruta.replace("/", "\\").lower()


def de_la_unidad(valor: str, raiz: Path | None, carpeta_app: str | None = None) -> bool:
    """Indica si una clave del navegador apunta a un KeePassXC de prdrive que ya no tiene que estar.

    Es así si apunta dentro de este volumen, o a un `…\\.prdrive\\keepassxc\\…`
    que ya no existe (otra unidad, o esta con otra letra, que se quitó sin
    expulsar). No hace falta recordar nada: se deduce. Lo que se mira es esa
    carpeta, no el JSON: KeePassXC lo escribe al arrancar, después de que
    «Abrir llavero» ponga la clave, y entretanto la unidad sigue ahí.

    Args:
        valor: Lo que dice la clave: la ruta de un JSON.
        raiz: El volumen que se cierra, o `None` para mirar solo si ya no
            existe (lo que hace el agente).
        carpeta_app: El nombre de `.prdrive/`; por defecto, el de este
            programa (`model.APP_DIR`). El agente, que no vive en una, da el
            de las raíces.
    """
    v = _comparable(valor)
    if raiz is not None and v.startswith(_comparable(str(raiz)).rstrip("\\") + "\\"):
        return True
    marca = f"\\{carpeta_app or model.APP_DIR.name}\\{components.KEEPASSXC_SUBDIR}\\"
    # Cambiar `/` por `\\` no mueve nada: la carpeta sale del valor tal cual.
    hallada = re.search(re.escape(marca), valor.replace("/", "\\"), re.IGNORECASE)
    return hallada is not None and not Path(valor[:hallada.end()]).exists()


class Cambio(NamedTuple):
    """Lo que se hace con una clave del registro al cerrar.

    Args:
        clave: La clave, bajo `HKCU`.
        valor: El JSON al que vuelve a apuntar, o `None` para borrarla.
    """
    clave: str
    valor: str | None


def plan_cerrar_navegador(raiz: Path | None = None, carpeta_app: str | None = None,
                          muertas: bool = False) -> list[Cambio]:
    """Decide qué claves del navegador se quitan o se devuelven al cerrar el llavero.

    Solo las que son de prdrive (`de_la_unidad()`): las de otros programas no
    se tocan. Si hay un KeePassXC instalado con el JSON de ese navegador, la
    clave vuelve a apuntarle; si no, se borra.

    Args:
        raiz: El volumen que se cierra; por defecto, este.
        carpeta_app: El nombre de `.prdrive/` (`de_la_unidad()`).
        muertas: Solo las que apuntan a un KeePassXC de prdrive que ya no
            existe, sin volumen que se cierre: lo que hace el agente cuando
            una unidad se va sin expulsar.
    """
    raiz = None if muertas else (model.DEVICE_ROOT if raiz is None else raiz)
    suyo = instalado()
    plan = []
    for base, nombres in NAVEGADORES:
        clave = clave_nativa(base)
        valor = registro.leer(clave)
        if not valor or not de_la_unidad(valor, raiz, carpeta_app):
            continue
        destino = None
        if suyo is not None:
            destino = next((json_nativo(suyo, n) for n in nombres
                            if json_nativo(suyo, n).is_file()), None)
        plan.append(Cambio(clave, None if destino is None else str(destino)))
    return plan


def cerrar_navegador(raiz: Path | None = None, carpeta_app: str | None = None,
                     muertas: bool = False) -> list[str]:
    """Deja las claves del navegador como estaban antes del llavero (§7 de la especificación).

    Además de lo de `plan_cerrar_navegador()` (con sus mismos argumentos), la
    `NativeMessagingHosts` de un navegador se borra si se queda vacía. En
    Linux, los manifiestos de prdrive (`cerrar_navegador_linux()`). Nunca
    lanza: se hace al expulsar, y un fallo aquí no puede impedir quitar la
    unidad.

    Returns:
        Lo que no se ha podido hacer; vacío si todo bien.
    """
    fallos = cerrar_navegador_linux(muertas) if MANIFIESTOS else []
    for cambio in plan_cerrar_navegador(raiz, carpeta_app, muertas):
        try:
            if cambio.valor is not None:
                registro.escribir(cambio.clave, cambio.valor)
                continue
            registro.borrar(cambio.clave)
            padre = cambio.clave.rsplit("\\", 1)[0]
            if registro.vacia(padre):
                registro.borrar(padre)
        except OSError as e:
            fallos.append(f"{cambio.clave}: {e}")
    return fallos


# --- el navegador en Linux (los manifiestos de mensajería nativa)

MANIFIESTOS = os.name != "nt"
"""Si se escriben y se quitan los manifiestos de Linux; los tests lo encienden en cualquier sistema."""
ORIGENES = ("chrome-extension://pdffhmdngciaglkoonimfcmckehcpafo/",
            "chrome-extension://oboonakemofpalcgghocfoadofidjkkk/")
"""Las extensiones de los navegadores Chromium que pueden hablar con KeePassXC (`ALLOWED_ORIGINS`)."""
EXTENSION_MOZILLA = "keepassxc-browser@keepassxc.org"
"""Y la de Firefox y Tor (`ALLOWED_EXTENSIONS`)."""
NAVEGADORES_LINUX: tuple[tuple[str, str, str, bool], ...] = (
    ("chrome", "config", "google-chrome/NativeMessagingHosts", False),
    ("chromium", "config", "chromium/NativeMessagingHosts", False),
    ("firefox", "home", ".mozilla/native-messaging-hosts", True),
    ("vivaldi", "config", "vivaldi/NativeMessagingHosts", False),
    ("tor-browser", "data", "torbrowser/tbb/x86_64/tor-browser/Browser/TorBrowser/Data/"
                            "Browser/.mozilla/native-messaging-hosts", True),
    ("brave", "config", "BraveSoftware/Brave-Browser/NativeMessagingHosts", False),
    ("edge", "config", "microsoft-edge/NativeMessagingHosts", False),
)
"""Dónde busca cada navegador su manifiesto en Linux (`TARGET_DIR_*` y `getNativeMessagePath()`).

`(navegador, base, carpeta, de Mozilla)`; la base es `config`
(`XDG_CONFIG_HOME`), `data` (`XDG_DATA_HOME`) o `home`.
"""


def bases_navegador() -> dict[str, Path]:
    """Devuelve las carpetas de las que cuelgan los manifiestos: `config`, `data` y `home`.

    Las de QStandardPaths en Linux. Es de módulo para que los tests las lleven
    a un temporal.
    """
    casa = Path.home()
    return {"config": Path(os.environ.get("XDG_CONFIG_HOME") or casa / ".config"),
            "data": Path(os.environ.get("XDG_DATA_HOME") or casa / ".local" / "share"),
            "home": casa}


def manifiestos_linux() -> list[tuple[str, Path, bool]]:
    """Devuelve `(navegador, manifiesto, de Mozilla)` de cada navegador de `NAVEGADORES_LINUX`."""
    bases = bases_navegador()
    return [(nombre, bases[base].joinpath(*carpeta.split("/")) / f"{HOST_NATIVO}.json", moz)
            for nombre, base, carpeta, moz in NAVEGADORES_LINUX]


def manifiesto(proxy: Path, mozilla: bool) -> str:
    """Devuelve el manifiesto que escribiría KeePassXC con ese proxy (`constructFile()`).

    Con sus claves en orden y sangrado de cuatro, como `QJsonDocument::toJson()`.
    """
    datos: dict = {"name": HOST_NATIVO,
                   "description": "KeePassXC integration with native messaging support",
                   "path": str(proxy), "type": "stdio"}
    if mozilla:
        datos["allowed_extensions"] = [EXTENSION_MOZILLA]
    else:
        datos["allowed_origins"] = list(ORIGENES)
    return json.dumps(datos, indent=4, sort_keys=True) + "\n"


def manifiesto_nuestro(ruta: Path) -> bool | None:
    """Indica si ese manifiesto es de prdrive: su proxy está en lo extraído (`cache_equipo()`).

    Returns:
        True si es nuestro; False si es de otro (un KeePassXC instalado) o no
        se entiende; `None` si no hay.
    """
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return False
    proxy = datos.get("path") if isinstance(datos, dict) else None
    if not isinstance(proxy, str) or not os.path.isabs(proxy):
        return False
    base = os.path.realpath(cache_equipo())
    return os.path.realpath(proxy).startswith(base + os.sep)


def abrir_navegador_linux(proxy: Path) -> list[str]:
    """Apunta el navegador al KeePassXC de la unidad: un manifiesto por navegador del equipo.

    Es lo de las claves del registro en Windows (B2): un equipo nuevo conecta
    sin marcar nada en KeePassXC. Solo en los navegadores que hay (su carpeta
    existe) y solo donde no haya manifiesto o sea nuestro: el de un KeePassXC
    instalado no se toca. Su proxy también llega al nuestro, que escucha en el
    mismo sitio (`BrowserShared::localServerPath()`), y si se le pisara no
    habría cómo devolvérselo.

    Returns:
        Lo que no se ha podido escribir, para decirlo; vacío si todo bien.
    """
    fallos = []
    for _, ruta, mozilla in manifiestos_linux():
        if not ruta.parent.parent.is_dir() or manifiesto_nuestro(ruta) is False:
            continue
        texto = manifiesto(proxy, mozilla)
        try:
            if ruta.is_file() and ruta.read_text(encoding="utf-8") == texto:
                continue
            ruta.parent.mkdir(exist_ok=True)
            _escribir(ruta, texto.encode("utf-8"))
        except OSError as e:
            fallos.append(f"{ruta}: {e}")
    return fallos


def plan_cerrar_navegador_linux(muertas: bool = False) -> list[Path]:
    """Decide qué manifiestos se quitan al cerrar el llavero en Linux: los de prdrive.

    Args:
        muertas: Solo si no queda abierto ningún KeePassXC de lo extraído: lo
            que hace el agente cuando una unidad se va sin expulsar. Uno abierto
            puede ser el de otra unidad, que los sigue usando.
    """
    if muertas and abiertos_de_la_cache():
        return []
    return [ruta for _, ruta, _ in manifiestos_linux() if manifiesto_nuestro(ruta)]


def cerrar_navegador_linux(muertas: bool = False) -> list[str]:
    """Quita los manifiestos de prdrive (`plan_cerrar_navegador_linux()`); los de otros, no.

    Returns:
        Lo que no se ha podido quitar; vacío si todo bien. Nunca lanza.
    """
    fallos = []
    for ruta in plan_cerrar_navegador_linux(muertas):
        try:
            ruta.unlink()
        except OSError as e:
            fallos.append(f"{ruta}: {e}")
    return fallos


# --- el fichero llave de cada equipo

def registro_llaves(estado: Path | None = None) -> Path:
    """Devuelve dónde se apunta la ruta del fichero llave en cada equipo (`state/keychain.json`).

    Es función porque los tests mueven `STATE_DIR`.

    Args:
        estado: La carpeta `state/` del dispositivo; sin ella, la de este. El
            instalador da la del que está preparando.
    """
    return (model.STATE_DIR if estado is None else Path(estado)) / "keychain.json"


def llave_apuntada() -> Path | None:
    """Devuelve la ruta del fichero llave apuntada para este equipo, o `None`.

    No mira si el fichero sigue ahí: eso lo decide quien abre.
    """
    equipos = store.read_json(registro_llaves()).get("equipos")
    dato = equipos.get(llavero.equipo()) if isinstance(equipos, dict) else None
    ruta = dato.get("fichero_llave") if isinstance(dato, dict) else None
    return Path(ruta) if isinstance(ruta, str) and ruta else None


def apuntar_llave(ruta: Path | None, estado: Path | None = None) -> bool:
    """Apunta la ruta del fichero llave en este equipo, o la olvida con `None`.

    Solo la ruta: el fichero ni se abre, y de los otros equipos no se toca nada.

    Args:
        ruta: Dónde está el fichero llave en este equipo.
        estado: La carpeta `state/` del dispositivo (`registro_llaves()`).

    Returns:
        False si no se ha podido escribir.
    """
    datos = store.read_json(registro_llaves(estado))
    equipos = datos.get("equipos") if isinstance(datos.get("equipos"), dict) else {}
    if ruta is None:
        equipos.pop(llavero.equipo(), None)
    else:
        equipos[llavero.equipo()] = {"fichero_llave": str(ruta)}
    datos["equipos"] = equipos
    destino = registro_llaves(estado)
    destino.parent.mkdir(parents=True, exist_ok=True)
    return store.write_json(destino, datos)


# --- lanzarlo

def otro_abierto() -> bool:
    """Indica si este equipo tiene abierto un KeePassXC que no es el de la unidad.

    Con `SingleInstance` (uno por usuario, sea cual sea su configuración:
    `Application.cpp`), el nuestro le pasaría la base a ése, que tiene otra
    configuración y otro proxy para el navegador.
    """
    nuestros = set(llavero.pids_keepassxc(model.APP_DIR))
    nombres = {components.KEEPASSXC_EXE.lower(), llavero.KEEPASSXC_LINUX}
    return any(nombre.lower() in nombres and pid not in nuestros
               for pid, nombre in store.nombres().items())


def orden(exe: Path, base: Path, paquete: str | None = None) -> list[str]:
    """Devuelve la orden que abre KeePassXC con su configuración y la base.

    Nunca lleva `--keyfile`: KeePassXC no se limita a rellenar el campo, sino
    que intenta desbloquear al instante con la contraseña vacía
    (`DatabaseOpenWidget::enterKey()` llama a `openDatabase()`), y con una base
    de contraseña y fichero llave sale «Desbloquear la base de datos ha fallado
    y no introdujo una contraseña». El fichero llave se elige en su diálogo.
    En Linux, `exe` es el `AppRun` de lo extraído, y la configuración es la de
    `config/linux/`: `--config` es también lo que dice de qué unidad es
    (`llavero.pids_keepassxc()`).
    """
    donde = carpeta_config(paquete)
    return [str(exe), "--config", str(donde / INI), "--localconfig", str(donde / INI_LOCAL),
            str(base)]


def orden_externo(externo: Externo, base: Path, raiz: Path | None = None) -> list[str]:
    """Devuelve la orden que abre la base con el KeePassXC del equipo (Linux ARM64).

    Con su propia configuración: es el de la persona. El de Flathub recibe
    permiso para la unidad solo para esta vez (`flatpak run --filesystem=`), y
    `KPXC_INITIAL_DIR` por `--env`, porque el entorno no entra en su caja. Sin
    `--keyfile`, como `orden()`.
    """
    raiz = model.DEVICE_ROOT if raiz is None else raiz
    salida = list(externo.orden)
    if externo.flatpak:
        salida[2:2] = [f"--filesystem={raiz}", f"--env=KPXC_INITIAL_DIR={raiz}"]  # tras «run» y el id
    return salida + [str(base)]


def entorno(raiz: Path | None = None) -> dict[str, str]:
    """Devuelve el entorno de KeePassXC: el de ahora con `KPXC_INITIAL_DIR` en la raíz.

    Así lo que se exporte cae en la raíz del volumen, a la vista: ni en
    `.keychain/`, oculta, ni en la carpeta personal del equipo (PK5). Sin
    `APPIMAGE` ni `APPDIR`, por si vienen de otro AppImage: el nuestro corre
    extraído.
    """
    salida = {k: v for k, v in os.environ.items() if k not in ("APPIMAGE", "APPDIR")}
    salida["KPXC_INITIAL_DIR"] = str(model.DEVICE_ROOT if raiz is None else raiz)
    return salida


def lanzar(orden_: list[str], entorno_: dict[str, str]) -> subprocess.Popen:
    """Lanza KeePassXC suelto: no es hijo de la ventana y no retiene nada suyo.

    El directorio de trabajo es el temporal, no el volumen. Es de módulo para
    que los tests no abran nada.
    """
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL, "close_fds": True,
                    "cwd": tempfile.gettempdir(), "env": entorno_}
    if os.name == "nt":
        kwargs["creationflags"] = model.CREATE_NO_WINDOW | model.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(orden_, **kwargs)


def esperar_arranque(proc, segundos: float = ESPERA_ARRANQUE) -> int | None:
    """Devuelve el código de KeePassXC si sale enseguida, o `None` si sigue abierto.

    Sin el runtime de Visual C++ (K3) no llega a abrir ninguna ventana: el
    cargador lo termina con `VC_FALTA`. Uno que le pasa la base al que ya
    estaba abierto (`SingleInstance`) sale con 0.
    """
    limite = time.monotonic() + segundos
    while True:
        codigo = proc.poll()
        if codigo is not None or time.monotonic() >= limite:
            return codigo
        llavero.dormir(0.1)


# --- combinar una copia de conflicto (§8)

def orden_combinar(programa: Path, base: Path, copia: Path,
                   llave: Path | None = None) -> list[str]:
    """Devuelve la orden que combina la copia en la base: lo de las dos queda en la base.

    `--same-credentials`: la copia es la misma base guardada en otro
    dispositivo, así que la contraseña (y el fichero llave) se piden una vez.
    """
    salida = [str(programa), "merge", "--same-credentials"]
    if llave is not None:
        salida += ["--key-file", str(llave)]
    return salida + [str(base), str(copia)]


TERMINALES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("x-terminal-emulator", ("-e",)),
    ("gnome-terminal", ("--",)),
    ("konsole", ("-e",)),
    ("xfce4-terminal", ("-x",)),
    ("mate-terminal", ("-x",)),
    ("kitty", ()),
    ("alacritty", ("-e",)),
    ("xterm", ("-e",)),
)
"""Los emuladores de terminal de Linux que se prueban para «Combinar», y cómo se les pasa la orden.

`x-terminal-emulator` es el que elige Debian (y Ubuntu); los demás, en el
orden de los escritorios más comunes. Los que piden la orden en un solo texto
(`lxterminal`, `tilix`) no están.
"""
ESPERA_TERMINAL = 30.0  # segundos
"""Lo que se espera a que la consola de «Combinar» arranque (apunta su pid)."""
SIN_TERMINAL = ("No encuentro ninguna terminal en este equipo para pedir la contraseña de "
                "la base. Combínalas desde KeePassXC: «Base de datos → Combinar desde base "
                "de datos…».")


def terminal() -> list[str] | None:
    """Devuelve cómo abrir una orden en una terminal a la vista en Linux, o `None`.

    Es de módulo para que los tests no abran ninguna.
    """
    for nombre, antes in TERMINALES:
        ruta = shutil.which(nombre)
        if ruta:
            return [ruta, *antes]
    return None


def combinar(base: Path, copia: Path, llave: Path | None = None) -> int:
    """Combina la copia en la base en una consola a la vista, y espera a que se cierre.

    La contraseña la pide `keepassxc-cli` en esa consola; prdrive no la ve
    nunca. La consola es `runsync.py --combinar-llavero` (`combinar_aqui()`).
    En Windows, con el Python de consola, porque la ventana corre con
    `pythonw`, que no tiene. En Linux, en una terminal (`terminal()`): muchas
    vuelven enseguida y ninguna dice el código de lo que corre, así que la
    consola apunta su pid al empezar y su código al acabar (`--codigo`), y se
    espera a eso (`esperar_codigo()`). Es de módulo para que los tests no
    abran nada.

    Returns:
        El código de `keepassxc-cli`: 0 si se ha combinado (o no había nada
        que combinar); -1 si la consola se cerró sin acabar.

    Raises:
        OSError: En Linux, si no hay ninguna terminal.
    """
    python = Path(sys.executable)
    consola = python.with_name("python.exe")
    if os.name == "nt" and consola.exists():
        python = consola
    orden_ = [str(python), str(model.RUNSYNC_PY), "--combinar-llavero", str(base), str(copia)]
    if llave is not None:
        orden_ += ["--keyfile", str(llave)]
    if os.name == "nt":
        return subprocess.run(orden_, cwd=tempfile.gettempdir(),
                              creationflags=CREATE_NEW_CONSOLE).returncode
    abre = terminal()
    if abre is None:
        raise OSError(SIN_TERMINAL)
    señal = Path(tempfile.mkdtemp(prefix="prdrive-combinar-"))
    try:
        codigo = señal / "codigo"
        subprocess.Popen([*abre, *orden_, "--codigo", str(codigo)], cwd=tempfile.gettempdir(),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return esperar_codigo(codigo)
    finally:
        shutil.rmtree(señal, ignore_errors=True)


def esperar_codigo(codigo: Path, arranque: float = ESPERA_TERMINAL) -> int:
    """Espera el código que deja la consola de «Combinar» en Linux (`apuntar_codigo()`).

    Al lado de `codigo` va `pid`, que la consola escribe al empezar: si en
    `arranque` segundos no aparece, la terminal no ha arrancado; si su proceso
    se va sin dejar código, alguien cerró la terminal. Las dos son -1.
    """
    pid_ = codigo.with_name("pid")
    limite = time.monotonic() + arranque
    while True:
        try:
            return int(codigo.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pass
        try:
            pid = int(pid_.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = None
        if pid is None and time.monotonic() >= limite:
            return -1
        if pid is not None and not store.pid_alive(pid):
            try:
                return int(codigo.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                return -1
        llavero.dormir(0.5)


def apuntar_codigo(codigo: Path, valor: int | None = None) -> None:
    """La consola de «Combinar» apunta su pid (sin `valor`) o su código, para quien espera."""
    destino = codigo.with_name("pid") if valor is None else codigo
    store.write_text(destino, f"{os.getpid() if valor is None else valor}\n")


def ejecutar_cli(orden_: list[str]) -> int:
    """Corre `keepassxc-cli` en esta consola y devuelve su código; de módulo para los tests."""
    return subprocess.run(orden_, cwd=tempfile.gettempdir()).returncode


def combinar_aqui(base: Path, copia: Path, llave: Path | None = None,
                  esperar: Callable[[str], object] = input) -> int:
    """Hace `runsync.py --combinar-llavero`: `keepassxc-cli merge` en esta consola.

    Dice qué va a pasar y deja que `keepassxc-cli` pida la contraseña. Si no
    sale bien, espera a que se lea por qué antes de cerrar la consola.

    Args:
        base: La base, donde queda lo de las dos.
        copia: La copia de conflicto.
        llave: El fichero llave de este equipo, si la base lo pide.
        esperar: Lo que espera a la persona antes de cerrar (`input`).

    Returns:
        El código de `keepassxc-cli`, o 2 si no está.
    """
    print(f"prdrive · combinar el llavero\n\nLo de «{copia.name}» entra en «{base.name}». "
          "Escribe la contraseña de la base: la pide KeePassXC, no prdrive.\n")
    programa = cli()
    if programa is None or not programa.is_file():
        print("Falta keepassxc-cli en el dispositivo: no se ha tocado nada.")
        esperar("Pulsa Intro para cerrar esta ventana.")
        return 2
    paquete = paquete_del_equipo()
    try:
        programa = cli_lanzable(programa)
    except OSError as e:
        print(f"No se ha podido preparar keepassxc-cli ({e}): no se ha tocado nada.")
        esperar("Pulsa Intro para cerrar esta ventana.")
        return 2
    if es_appimage(paquete):
        # Con la configuración de la unidad, como el programa: si no, la CLI
        # crearía la suya en ~/.config/keepassxc del equipo.
        donde = carpeta_config(paquete)
        os.environ["KPXC_CONFIG"] = str(donde / INI)
        os.environ["KPXC_CONFIG_LOCAL"] = str(donde / INI_LOCAL)
    codigo = ejecutar_cli(orden_combinar(programa, base, copia, llave))
    if codigo != 0:
        print(f"\nNo se ha combinado (código {codigo}). No se ha tocado nada.")
        esperar("Pulsa Intro para cerrar esta ventana.")
    return codigo


# --- abrir el llavero

class Apertura(NamedTuple):
    """Lo que hace falta para abrir el llavero en este equipo (`mirar_apertura()`).

    Args:
        motivo: Por qué no se puede abrir, para decirlo; `None` si se puede.
        exe: El programa de la unidad: `KeePassXC.exe`, o el AppImage.
        base: La base (puede no estar aún: la trae la pasada).
        abierto: El KeePassXC de la unidad ya está abierto: se trae delante y
            no se toca su configuración.
        otro: Hay otro KeePassXC abierto en el equipo.
        pasada: Toca traer lo último antes de abrir.
        pide_llave: La base pide fichero llave (`[keychain] fichero_llave`).
        nombre_llave: Su nombre, solo como pista para la persona.
        llave: Su ruta en este equipo, si está apuntada y sigue ahí.
        paquete: El paquete de KeePassXC de la unidad que se lanza.
        externo: Sin paquete para este equipo (Linux ARM64), el KeePassXC
            instalado en él.
    """
    motivo: str | None
    exe: Path | None = None
    base: Path | None = None
    abierto: bool = False
    otro: bool = False
    pasada: bool = False
    pide_llave: bool = False
    nombre_llave: str = ""
    llave: Path | None = None
    paquete: str | None = None
    externo: Externo | None = None


SIN_LLAVERO = "Este dispositivo no lleva llavero."
SIN_KEEPASSXC_AQUI = (
    "Para este equipo no hay KeePassXC en el dispositivo (no lo hay para Linux ARM64) ni "
    "instalado. Instala KeePassXC, de Flathub o de tu distribución (para las passkeys, la "
    "2.7.7 o posterior), y vuelve a abrir el llavero. Mientras, se sincroniza igual.")
OTRO_SISTEMA = "El llavero se abre en Windows y en Linux; en este sistema solo se sincroniza."
FALTA_KEEPASSXC = ("Falta KeePassXC en el dispositivo. Abre la ventana de prdrive y pulsa "
                   "«Actualizar…» en el recuadro de lo que lleva el dispositivo.")


def sin_programa() -> str:
    """Devuelve por qué este equipo no tiene con qué abrir el llavero (sin paquete ni instalado)."""
    return SIN_KEEPASSXC_AQUI if sys.platform.startswith("linux") else OTRO_SISTEMA


def mirar_apertura(config: model.Config, ahora: float | None = None) -> Apertura:
    """Decide qué hace falta para abrir el llavero, sin tocar nada.

    Args:
        config: El del dispositivo.
        ahora: La hora (`time.time()`), para saber si la última pasada es vieja.
    """
    if config.llavero is None or config.pareja_llavero is None:
        return Apertura(SIN_LLAVERO)
    paquete = paquete_del_equipo()
    externo = del_equipo() if paquete is None else None
    if paquete is None and externo is None:
        return Apertura(sin_programa())
    exe = None if paquete is None else components.keepassxc_exe(model.APP_DIR, paquete)
    if exe is not None and not exe.is_file():
        return Apertura(FALTA_KEEPASSXC, exe=exe, paquete=paquete)
    base = llavero.carpeta() / config.llavero["base"]
    abierto = llavero.keepassxc_abierto()
    pasada = False
    if not abierto:
        ahora = time.time() if ahora is None else ahora
        ultima = results.ultimas_buenas([model.LLAVERO]).get(model.LLAVERO)
        vieja = ultima is None or ahora - ultima > DESDE_LA_ULTIMA
        pasada = not base.exists() or (vieja and not llavero.atiende_el_servicio())
    pide = bool(config.llavero.get("fichero_llave"))
    llave = llave_apuntada() if pide else None
    if llave is not None and not llave.is_file():
        llave = None
    # Con el del equipo no hay «otro»: es el de la persona, y que reciba la base
    # en el que ya tiene abierto es justo lo que se quiere.
    otro = not abierto and externo is None and otro_abierto()
    return Apertura(None, exe=exe, base=base, abierto=abierto, otro=otro, pasada=pasada,
                    pide_llave=pide,
                    nombre_llave=str(config.llavero.get("nombre_llave") or ""), llave=llave,
                    paquete=paquete, externo=externo)


class Abierto(NamedTuple):
    """Cómo ha ido lanzar KeePassXC (`abrir()`).

    Args:
        codigo: Su código si salió enseguida (`esperar_arranque()`), o `None`
            si sigue abierto.
        avisos: Lo que no se ha podido preparar, aunque se haya abierto.
        programa: Lo que se ha lanzado, para decir dónde mirar si se cae.
    """
    codigo: int | None
    avisos: tuple[str, ...] = ()
    programa: Path | None = None


def abrir(ap: Apertura) -> Abierto:
    """Prepara el equipo y lanza KeePassXC con la base (pasos 6–8 de §6).

    Con el KeePassXC de la unidad ya abierto, solo se lanza: `SingleInstance` le
    pasa la base al abierto y lo trae delante; su configuración no se toca con
    él corriendo, porque la reescribiría al salir.

    - Windows: la configuración y las claves del registro del navegador, y
      `KeePassXC.exe` de la unidad.
    - Linux x64: el AppImage, extraído en este equipo si hace falta
      (`preparar_appimage()`, unos segundos la primera vez), su configuración
      con el proxy de lo extraído, y su `AppRun`.
    - Linux ARM64: el KeePassXC del equipo, con su configuración y sus
      manifiestos, que son de la persona; si no tiene passkeys, se dice.

    Args:
        ap: Lo que dijo `mirar_apertura()`, sin `motivo`.

    Raises:
        OSError: Si no se ha podido extraer o lanzar.
    """
    avisos: list[str] = []
    if ap.externo is not None:
        aviso = sin_passkeys(version_del_equipo(ap.externo))
        if aviso:
            avisos.append(aviso)
        orden_ = orden_externo(ap.externo, ap.base)
        proc = lanzar(orden_, entorno())
        return Abierto(esperar_arranque(proc), tuple(avisos), Path(orden_[0]))
    if es_appimage(ap.paquete):
        carpeta = preparar_appimage(ap.paquete)
        programa = carpeta / APPRUN
        if not ap.abierto:
            try:
                ajustar_config(paquete=ap.paquete, proxy=carpeta / PROXY_LINUX)
            except OSError as e:
                avisos.append(f"No se ha podido preparar la configuración de KeePassXC: {e}")
            fallos = abrir_navegador_linux(carpeta / PROXY_LINUX)
            if fallos:
                avisos.append(f"El navegador no encontrará este KeePassXC: no se han podido "
                              f"escribir {len(fallos)} de sus manifiestos ({fallos[0]}).")
    else:
        programa = ap.exe
        if not ap.abierto:
            try:
                ajustar_config(paquete=ap.paquete)
            except OSError as e:
                avisos.append(f"No se ha podido preparar la configuración de KeePassXC: {e}")
            fallos = abrir_navegador(ap.exe)
            if fallos:
                avisos.append(f"El navegador no encontrará este KeePassXC: no se han podido "
                              f"escribir {len(fallos)} de sus {len(NAVEGADORES)} claves del "
                              f"registro ({fallos[0]}).")
    proc = lanzar(orden(programa, ap.base, ap.paquete), entorno())
    return Abierto(esperar_arranque(proc), tuple(avisos), programa)


# --- cerrarlo al expulsar (§10)

ESPERA_CIERRE = 180.0  # segundos
"""Lo que se espera a que KeePassXC salga después de pedírselo: puede estar preguntando."""
TOPE_PASADA = 60.0  # segundos
"""Lo más que dura la pasada de lo pendiente al expulsar."""
ESPERA_VIGILANTE = 90.0  # segundos
"""Lo que se espera a que el vigilante se vaya: si está en una pasada, la acaba."""


def procesos_de_la_unidad() -> tuple[list[int], list[int]]:
    """Devuelve los pids del KeePassXC de la unidad y de su proxy (`llavero.pids_keepassxc()`).

    El proxy solo en Windows, donde corre desde la unidad y la retiene (K6,
    H-16). En Linux corre desde lo extraído en el equipo, que no retiene nada:
    se deja, y el navegador sigue conectado para la próxima vez.
    """
    proxies: list[int] = []
    for paquete in components.paquetes_keepassxc(model.APP_DIR):
        if es_appimage(paquete):
            continue
        carpeta = components.keepassxc_dir(model.APP_DIR, paquete)
        for pid, exe in store.procesos_desde(carpeta).items():
            if Path(exe).name.lower() == PROXY:
                proxies.append(pid)
    return llavero.pids_keepassxc(model.APP_DIR), proxies


def pedir_cierre(pid: int) -> None:
    """Le pide a un programa que se cierre, como lo haría la persona (`WM_CLOSE`).

    `taskkill /PID`, nunca `/F`: si KeePassXC tiene algo sin guardar, pregunta.
    Es de módulo para que los tests no cierren nada.
    """
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True,
                       creationflags=model.CREATE_NO_WINDOW)
    else:
        try:
            os.kill(pid, 15)                  # SIGTERM: KeePassXC sale como al cerrarlo
        except OSError:
            pass


def terminar(pid: int) -> None:
    """Termina un proceso sin preguntarle; solo para el proxy, que no guarda nada.

    Es de módulo para que los tests no maten nada.
    """
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True,
                       creationflags=model.CREATE_NO_WINDOW)
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def cerrar_huerfano(app_dir: Path | None = None) -> int:
    """Le pide que se cierre al KeePassXC de una unidad que se ha ido; devuelve a cuántos.

    Es cosa de Linux, y quien llama lo mira: allí corre extraído en el equipo
    y no muere con la unidad, como en Windows, así que seguiría con la base
    abierta en memoria, y sus passkeys. Se le pide como lo haría la persona
    (`pedir_cierre()`): con algo sin guardar, pregunta él. Su orden sigue
    nombrando la unidad aunque ya no esté (`llavero.pids_keepassxc()`).

    Args:
        app_dir: El `.prdrive/` de la unidad; por defecto, el de esta.
    """
    pids = llavero.pids_keepassxc(model.APP_DIR if app_dir is None else app_dir)
    for pid in pids:
        pedir_cierre(pid)
    return len(pids)


def esperar_salida(pids: list[int], segundos: float) -> bool:
    """Espera a que salgan esos procesos; indica si han salido todos a tiempo."""
    limite = time.monotonic() + segundos
    while any(store.pid_alive(pid) for pid in pids):
        if time.monotonic() >= limite:
            return False
        llavero.dormir(0.5)
    return True


class Cierre(NamedTuple):
    """Cómo ha ido cerrar el llavero para expulsar.

    Args:
        listo: Si ya nada del llavero retiene la unidad.
        lineas: Lo que hay que decir; vacío si todo ha ido bien, que es lo que
            pasa casi siempre y por eso no se dice nada.
    """
    listo: bool
    lineas: tuple[str, ...] = ()


SIGUE_ABIERTO = ("KeePassXC no se ha cerrado: puede que esté preguntando algo, o que esté "
                 "puesto para minimizarse al cerrar. Ciérralo desde su menú (Base de datos "
                 "→ Salir) y vuelve a expulsar.")
SUBIRA = "El llavero se subirá la próxima vez: ahora no ha podido (código {rc})."


def cerrar_llavero(config: model.Config) -> Cierre:
    """Deja el llavero listo para quitar la unidad (los pasos 1–5 de §10).

    1. Cierra el KeePassXC de la unidad como lo haría la persona y espera a
       que salga (si tiene algo sin guardar, pregunta él). Quien llama ya ha
       preguntado si se cierra.
    2. Termina su proxy, que vive lo que el navegador.
    3. Para el vigilante del llavero y espera a que se vaya.
    4. Si queda algo sin subir, una pasada con un tope de `TOPE_PASADA`.
    5. Deja las claves del navegador como estaban (`cerrar_navegador()`).

    Tarda (espera a KeePassXC y a la pasada): la ventana lo llama en
    `working()`.

    Returns:
        Si se puede quitar la unidad y lo que hay que decir.
    """
    pareja = config.pareja_llavero
    if pareja is None:
        return Cierre(True)
    lineas: list[str] = []
    programas, proxies = procesos_de_la_unidad()
    for pid in programas:
        pedir_cierre(pid)
    if programas and not esperar_salida(programas, ESPERA_CIERRE):
        return Cierre(False, (SIGUE_ABIERTO,))
    for pid in proxies:
        terminar(pid)
    if llavero.vigilante_vivo():
        try:
            llavero.parada_vigilante().touch()
        except OSError:
            pass
        limite = time.monotonic() + ESPERA_VIGILANTE
        while llavero.vigilante_vivo() and time.monotonic() < limite:
            llavero.dormir(0.5)
    if llavero.pendiente(pareja):
        rc, _ = llavero.pasada(tope=TOPE_PASADA)
        if rc != 0:
            rotas = llavero.rotas(pareja.local_abs)
            if rotas:
                lineas.append("La base del llavero no está entera, y no se ha subido: "
                              f"{rotas[0].motivo}. «Abrir llavero» lo vuelve a intentar.")
            elif any(x.copias for x in conflicts.escanear(pareja)):
                lineas.append("El llavero tiene copias de conflicto: «Abrir llavero» "
                              "ofrecerá combinarlas.")
            else:
                lineas.append(SUBIRA.format(rc=rc))
    fallos = cerrar_navegador()
    if fallos:
        lineas.append("No se han podido dejar como estaban algunas claves del navegador "
                      f"({fallos[0]}). No impiden quitar la unidad.")
    return Cierre(True, tuple(lineas))
