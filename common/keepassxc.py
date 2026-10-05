#!/usr/bin/env python3
"""KeePassXC en este equipo: su configuración, el navegador y lanzarlo con la base.

Es lo que hay detrás de «Abrir llavero» (`ui/tk_llavero.py`; `runsync.py
--llavero`) y, al expulsar, de dejar el registro como estaba. La base y su
sincronización son de `common/llavero.py`; esto es el programa. Solo Windows
(x64, y ARM64 con el x64 emulado); Linux es la fase 2 de la especificación.

Dónde está cada cosa:
- El programa, en `.prdrive/keepassxc/<paquete>/`, tal cual viene en el ZIP
  (con `.portable`). Lo pone y lo cambia `install/keepassxc_bin.py`, que
  sustituye esa carpeta entera.
- Su configuración, aparte, en `.prdrive/keepassxc/config/windows/`
  (`keepassxc.ini`, `keepassxc_local.ini` y `raiz.txt`), y se le pasa con
  `--config` y `--localconfig` (`src/main.cpp`). Así cambiar de versión no la
  toca.
- Los JSON del navegador, en `<exe>/config/`: con `.portable` van ahí
  (`NativeMessageInstaller::getNativeMessagePath()`), y KeePassXC los rehace en
  cada arranque (`updateBinaryPaths()`), así que perderlos no importa.
- La ruta del fichero llave, en `state/keychain.json`, una por equipo. El
  fichero ni se abre: solo se le pasa a KeePassXC con `--keyfile`.

Lo que toca el equipo (`registro.*`, `store.procesos()`, `lanzar()`) son
funciones de módulo que los tests sustituyen; lo demás decide sin tocar nada,
o toca solo ficheros del dispositivo.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Mapping, NamedTuple

from . import components, llavero, model, pins, registro, results, store

CONFIG_SUBDIR = Path("config") / "windows"
"""Dónde va la configuración de KeePassXC, dentro de `.prdrive/keepassxc/`."""
INI = "keepassxc.ini"
"""La configuración que viaja (`Roaming` en `src/core/Config.cpp`)."""
INI_LOCAL = "keepassxc_local.ini"
"""La del equipo (`Local`): las bases recientes, el último directorio, el desbloqueo rápido."""
RAIZ = "raiz.txt"
"""La raíz del volumen con la que se abrió la última vez, para mover las rutas recientes."""
FIN_DE_LINEA = "\r\n"
"""Con el que escribe QSettings en Windows, para un fichero que se crea aquí."""

SIEMPRE = {
    "UseAtomicSaves": "true",           # deshace un «Deshabilitar almacenajes seguros» (H-11)
    "Browser/UpdateBinaryPath": "true",  # que rehaga los JSON del navegador al arrancar
    "GUI/CheckForUpdates": "false",     # la versión la pone prdrive
}
"""Lo que se pone en `keepassxc.ini` en cada arranque, diga lo que diga."""
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

    Windows ARM64 usa el x64 emulado (`pins.KEEPASSXC_PARA`). Es de módulo para
    que los tests elijan el equipo.
    """
    if os.name != "nt":
        return None
    return pins.KEEPASSXC_PARA.get("windows-arm64" if model.arch_dir() == "arm"
                                   else "windows-x64")


def ejecutable() -> Path | None:
    """Devuelve el `KeePassXC.exe` de la unidad para este equipo, o `None` si no hay paquete."""
    paquete = paquete_del_equipo()
    return None if paquete is None else components.keepassxc_exe(model.APP_DIR, paquete)


def cli() -> Path | None:
    """Devuelve el `keepassxc-cli.exe` de la unidad para este equipo, o `None` si no hay paquete."""
    exe = ejecutable()
    return None if exe is None else exe.with_name(CLI)


def carpeta_config() -> Path:
    """Devuelve la carpeta de la configuración de KeePassXC (`keepassxc/config/windows/`)."""
    return model.APP_DIR / components.KEEPASSXC_SUBDIR / CONFIG_SUBDIR


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


def ajustar_config(raiz: Path | None = None) -> list[str]:
    """Deja la configuración de KeePassXC como la quiere prdrive, con KeePassXC cerrado.

    Cada arranque, `SIEMPRE` y las rutas recientes movidas a la raíz de ahora
    (la de la vez anterior está en `raiz.txt`: la letra cambia de un equipo a
    otro). Al crear un fichero, además `AL_CREAR` / `AL_CREAR_LOCAL`. Los dos
    ficheros a la vez: KeePassXC trata un `keepassxc_local.ini` sin su
    `keepassxc.ini` como una configuración vieja y lo mueve (`Config::init()`).
    Los bytes se leen y se escriben tal cual (`surrogateescape`): QSettings
    escapa lo que no es ASCII, pero un fichero tocado a mano no se estropea.

    Args:
        raiz: La raíz del volumen; sin ella, la de este dispositivo.

    Returns:
        Los ficheros que ha escrito.

    Raises:
        OSError: Si no se ha podido leer o escribir.
    """
    raiz = model.DEVICE_ROOT if raiz is None else raiz
    donde = carpeta_config()
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
    for nombre, siempre, al_crear in ((INI, SIEMPRE, AL_CREAR), (INI_LOCAL, {}, AL_CREAR_LOCAL)):
        ruta = donde / nombre
        try:
            texto, nuevo = ruta.read_bytes().decode("utf-8", "surrogateescape"), False
        except FileNotFoundError:
            texto, nuevo = "", True
        editado = editar_ini(texto, {**al_crear, **siempre} if nuevo else siempre,
                             cambiar if movida else None)
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


def de_la_unidad(valor: str, raiz: Path) -> bool:
    """Indica si una clave del navegador apunta a un KeePassXC de prdrive que ya no tiene que estar.

    Es así si apunta dentro de este volumen, o a un `…\\.prdrive\\keepassxc\\…`
    que ya no existe (otra unidad, o esta con otra letra, que se quitó sin
    expulsar). No hace falta recordar nada: se deduce.
    """
    v = _comparable(valor)
    if v.startswith(_comparable(str(raiz)).rstrip("\\") + "\\"):
        return True
    marca = f"\\{_comparable(model.APP_DIR.name)}\\{components.KEEPASSXC_SUBDIR}\\"
    return marca in v and not Path(valor).exists()


class Cambio(NamedTuple):
    """Lo que se hace con una clave del registro al cerrar.

    Args:
        clave: La clave, bajo `HKCU`.
        valor: El JSON al que vuelve a apuntar, o `None` para borrarla.
    """
    clave: str
    valor: str | None


def plan_cerrar_navegador(raiz: Path | None = None) -> list[Cambio]:
    """Decide qué claves del navegador se quitan o se devuelven al cerrar el llavero.

    Solo las que son de prdrive (`de_la_unidad()`): las de otros programas no
    se tocan. Si hay un KeePassXC instalado con el JSON de ese navegador, la
    clave vuelve a apuntarle; si no, se borra.
    """
    raiz = model.DEVICE_ROOT if raiz is None else raiz
    suyo = instalado()
    plan = []
    for base, nombres in NAVEGADORES:
        clave = clave_nativa(base)
        valor = registro.leer(clave)
        if not valor or not de_la_unidad(valor, raiz):
            continue
        destino = None
        if suyo is not None:
            destino = next((json_nativo(suyo, n) for n in nombres
                            if json_nativo(suyo, n).is_file()), None)
        plan.append(Cambio(clave, None if destino is None else str(destino)))
    return plan


def cerrar_navegador(raiz: Path | None = None) -> list[str]:
    """Deja las claves del navegador como estaban antes del llavero (§7 de la especificación).

    Además de lo de `plan_cerrar_navegador()`, la `NativeMessagingHosts` de un
    navegador se borra si se queda vacía. Nunca lanza: se hace al expulsar, y
    un fallo aquí no puede impedir quitar la unidad.

    Returns:
        Lo que no se ha podido hacer; vacío si todo bien.
    """
    fallos = []
    for cambio in plan_cerrar_navegador(raiz):
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

    Con `SingleInstance`, el nuestro le pasaría la base a ése, que tiene otra
    configuración y otro proxy para el navegador.
    """
    nuestros: set[int] = set()
    for paquete in components.paquetes_keepassxc(model.APP_DIR):
        nuestros.update(store.procesos_desde(components.keepassxc_dir(model.APP_DIR, paquete)))
    nombre = components.KEEPASSXC_EXE.lower()
    return any(Path(exe).name.lower() == nombre and pid not in nuestros
               for pid, exe in store.procesos().items())


def orden(exe: Path, base: Path, llave: Path | None = None) -> list[str]:
    """Devuelve la orden que abre KeePassXC con su configuración y la base.

    `--keyfile` solo rellena el campo del diálogo de desbloqueo
    (`mainWindow.openDatabase(filename, password, keyfile)`).
    """
    donde = carpeta_config()
    salida = [str(exe), "--config", str(donde / INI), "--localconfig", str(donde / INI_LOCAL)]
    if llave is not None:
        salida += ["--keyfile", str(llave)]
    return salida + [str(base)]


def entorno(raiz: Path | None = None) -> dict[str, str]:
    """Devuelve el entorno de KeePassXC: el de ahora con `KPXC_INITIAL_DIR` en la raíz.

    Así lo que se exporte cae en la raíz del volumen, a la vista: ni en
    `.keychain/`, oculta, ni en la carpeta personal del equipo (PK5).
    """
    salida = dict(os.environ)
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


def combinar(base: Path, copia: Path, llave: Path | None = None) -> int:
    """Combina la copia en la base en una consola a la vista, y espera a que se cierre.

    La contraseña la pide `keepassxc-cli` en esa consola; prdrive no la ve
    nunca. La consola es `runsync.py --combinar-llavero` (`combinar_aqui()`)
    con el Python de consola, porque la ventana corre con `pythonw`, que no
    tiene. Es de módulo para que los tests no abran nada.

    Returns:
        El código de `keepassxc-cli`: 0 si se ha combinado (o no había nada
        que combinar).
    """
    python = Path(sys.executable)
    consola = python.with_name("python.exe")
    if os.name == "nt" and consola.exists():
        python = consola
    orden_ = [str(python), str(model.RUNSYNC_PY), "--combinar-llavero", str(base), str(copia)]
    if llave is not None:
        orden_ += ["--keyfile", str(llave)]
    kwargs: dict = {"cwd": tempfile.gettempdir()}
    if os.name == "nt":
        kwargs["creationflags"] = CREATE_NEW_CONSOLE
    return subprocess.run(orden_, **kwargs).returncode


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
        exe: El `KeePassXC.exe` de la unidad.
        base: La base (puede no estar aún: la trae la pasada).
        abierto: El KeePassXC de la unidad ya está abierto: se trae delante y
            no se toca su configuración.
        otro: Hay otro KeePassXC abierto en el equipo.
        pasada: Toca traer lo último antes de abrir.
        pide_llave: La base pide fichero llave (`[keychain] fichero_llave`).
        nombre_llave: Su nombre, solo como pista para la persona.
        llave: Su ruta en este equipo, si está apuntada y sigue ahí.
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


SIN_LLAVERO = "Este dispositivo no lleva llavero."
SOLO_WINDOWS = "De momento, el llavero solo se abre en Windows."
FALTA_KEEPASSXC = ("Falta KeePassXC en el dispositivo. Abre la ventana de prdrive y pulsa "
                   "«Actualizar…» en el recuadro de lo que lleva el dispositivo.")


def mirar_apertura(config: model.Config, ahora: float | None = None) -> Apertura:
    """Decide qué hace falta para abrir el llavero, sin tocar nada.

    Args:
        config: El del dispositivo.
        ahora: La hora (`time.time()`), para saber si la última pasada es vieja.
    """
    if config.llavero is None or config.pareja_llavero is None:
        return Apertura(SIN_LLAVERO)
    exe = ejecutable()
    if exe is None:
        return Apertura(SOLO_WINDOWS)
    if not exe.is_file():
        return Apertura(FALTA_KEEPASSXC, exe=exe)
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
    return Apertura(None, exe=exe, base=base, abierto=abierto,
                    otro=not abierto and otro_abierto(), pasada=pasada, pide_llave=pide,
                    nombre_llave=str(config.llavero.get("nombre_llave") or ""), llave=llave)


class Abierto(NamedTuple):
    """Cómo ha ido lanzar KeePassXC (`abrir()`).

    Args:
        codigo: Su código si salió enseguida (`esperar_arranque()`), o `None`
            si sigue abierto.
        avisos: Lo que no se ha podido preparar, aunque se haya abierto.
    """
    codigo: int | None
    avisos: tuple[str, ...] = ()


def abrir(ap: Apertura, llave: Path | None = None) -> Abierto:
    """Prepara el equipo y lanza KeePassXC con la base (pasos 6–8 de §6).

    Con el KeePassXC de la unidad ya abierto, solo se lanza: `SingleInstance` le
    pasa la base al abierto y lo trae delante; su configuración no se toca con
    él corriendo, porque la reescribiría al salir.

    Args:
        ap: Lo que dijo `mirar_apertura()`, sin `motivo`.
        llave: La ruta del fichero llave en este equipo, o `None`.

    Raises:
        OSError: Si no se ha podido lanzar.
    """
    avisos: list[str] = []
    if not ap.abierto:
        try:
            ajustar_config()
        except OSError as e:
            avisos.append(f"No se ha podido preparar la configuración de KeePassXC: {e}")
        fallos = abrir_navegador(ap.exe)
        if fallos:
            avisos.append(f"El navegador no encontrará este KeePassXC: no se han podido "
                          f"escribir {len(fallos)} de sus {len(NAVEGADORES)} claves del "
                          f"registro ({fallos[0]}).")
    proc = lanzar(orden(ap.exe, ap.base, llave), entorno())
    return Abierto(esperar_arranque(proc), tuple(avisos))
