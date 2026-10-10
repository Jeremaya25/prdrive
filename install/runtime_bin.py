#!/usr/bin/env python3
"""Conseguir el Python que viaja dentro del dispositivo.

Es el hermano de `rclone_bin.py`, con el mismo contrato: lo que se descarga se
COMPRUEBA contra el `SHA256SUMS` que publica su autor antes de escribir nada, y
si no cuadra no se guarda nada. Esto se ejecutará en cada equipo donde se
enchufe el dispositivo, así que «lo que haya llegado» no vale.

Qué se baja: la distribución `install_only_stripped` de python-build-standalone
(astral-sh), de la release fijada en `common/pins.py`. Es un Python reubicable
(se descomprime donde sea y funciona) y, a diferencia del zip embebible
oficial, trae tkinter: sin tkinter no hay ventana.

Dónde se guarda: el archivo comprobado va a la caché del usuario
(`%LOCALAPPDATA%/prdrive-install/runtime/<release>/`), con su suma apuntada al
lado. La caché es por release y los ficheros se llaman por su destino, así que
distintas plataformas y versiones no se pisan. Al dispositivo llega una
EXTRACCIÓN de ese archivo, que hace `extract()` y coloca
`deploy.install_runtime()`.

Ponerlo a mano (`a_mano()`, `adoptar()`) es dejar ahí mismo el archivo con su
nombre exacto, junto al SHA256SUMS de la release: se comprueba igual que una
descarga, sin red, y solo entonces cuenta como caché. Un fallo de red al
bajarlo se reintenta (`descarga.con_reintentos()`); una suma que no cuadra, no.

Qué se escribe al extraer, y qué no:
- Todo miembro se valida ANTES de escribir el primero: uno solo que pretenda
  salirse del destino tumba la extracción entera. Un `extractall()` a secas es
  el clásico agujero, y un archivo es contenido ajeno aunque venga comprobado.
- No se crean enlaces simbólicos: exFAT no los tiene y el dispositivo casi
  siempre es exFAT. El único que hace falta (`bin/python3` en Linux, que en el
  archivo es un enlace a `python3.14`) se materializa escribiendo su destino
  con ese nombre, y no dos veces: son 30 MB.
- Se poda lo que no hace falta para ejecutar prdrive: pip, ensurepip, idle, los
  tests, las cabeceras y bibliotecas de C y, en Linux, `share/` (terminfo, man)
  y la `libpython.so`, que es para quien incrusta Python (el intérprete de
  python-build-standalone la lleva enlazada estática).
- El sello (`STAMP`) se escribe el ÚLTIMO. Un runtime a medias no lo tiene, y
  sin sello no cuenta como instalado: ni para el asistente ni para penwatch.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import shutil
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from common import components, pins
from common.pins import Plataforma
from common.update import _ruta_segura

from . import APP_NAME, IS_WIN, InstallError
from . import descarga

DOWNLOAD_TIMEOUT = 60  # segundos por lectura, no en total
USER_AGENT = f"{APP_NAME}-install"
"""`User-Agent` de las peticiones a GitHub."""
Progreso = Callable[[str], None]
"""Función que recibe cada mensaje de avance."""

STAMP = components.RUNTIME_STAMP
"""Nombre del sello de versión de cada runtime: `runtime/<clave>/STAMP`.

Los nombres los define `common/components.py`, que es quien los LEE desde el
dispositivo; aquí solo se escriben. Un segundo literal aquí sería el que se
quedaría atrás el día que cambiara el otro. penwatch los repite (no puede
importar nada del proyecto) y un test impide que las copias se separen.
"""
RUNTIME_SUBDIR = components.RUNTIME_SUBDIR
"""Carpeta de los runtimes dentro de `.prdrive/`."""

SUMS_URL = f"{pins.PBS_BASE_URL}/{pins.PYTHON_RELEASE}/SHA256SUMS"
"""URL del SHA256SUMS de la release fijada."""

RAIZ_ARCHIVO = "python"
"""Directorio raíz de todos los archivos de python-build-standalone."""


def _mm() -> str:
    """Devuelve `3.14` a partir de `3.14.8`.

    El tramo que aparece en las rutas del runtime.
    """
    return ".".join(pins.PYTHON_VERSION.split(".")[:2])


def podar(plat: Plataforma) -> tuple[str, ...]:
    """Devuelve los prefijos, relativos a la raíz del runtime, que NO viajan.

    Es lo que ninguna parte de prdrive importa. Quitarlo ahorra unos 15 MB por
    plataforma en Windows y bastante más en Linux; lo que no está aquí se queda
    aunque parezca que sobra, porque un runtime al que le falta un módulo falla
    en el equipo de otro y lejos de quien lo podría arreglar.
    """
    if plat.es_windows:
        return ("Lib/site-packages/", "Lib/ensurepip/", "Lib/idlelib/",
                "Lib/test/", "Lib/turtledemo/", "include/", "libs/", "Scripts/")
    lib = f"lib/python{_mm()}/"
    return ("share/", "include/", "lib/pkgconfig/", "lib/libpython",
            lib + "site-packages/", lib + "ensurepip/", lib + "idlelib/",
            lib + "test/", lib + "turtledemo/", f"{lib}config-{_mm()}")


def _podado(rel: str, prefijos: tuple[str, ...], plat: Plataforma) -> bool:
    """Indica si ese miembro se poda."""
    if any(rel.startswith(p) or rel == p.rstrip("/") for p in prefijos):
        return True
    # En `bin/` de Linux solo hace falta el intérprete: pip, idle, pydoc y los
    # `*-config` son guiones que apuntan al nombre versionado y aquí no se
    # usan.
    return (not plat.es_windows and rel.startswith("bin/")
            and rel not in (plat.interprete, plat.interprete_consola))


def archive_name(plat: Plataforma) -> str:
    """Devuelve el nombre del archivo de python-build-standalone para esa plataforma."""
    return (f"cpython-{pins.PYTHON_VERSION}+{pins.PYTHON_RELEASE}-{plat.triple}"
            f"-install_only_stripped.tar.gz")


def download_url(plat: Plataforma) -> str:
    """Devuelve la URL del archivo de ESA release.

    El `+` del nombre va escapado: GitHub lo sirve igual, pero en una ruta es
    un espacio para más de un proxy.
    """
    return (f"{pins.PBS_BASE_URL}/{pins.PYTHON_RELEASE}/"
            f"{urllib.parse.quote(archive_name(plat))}")


def fetch(url: str, timeout: float = DOWNLOAD_TIMEOUT) -> bytes:
    """Descarga una URL; es la única puerta de salida a la red de este módulo.

    Es de módulo a propósito, como `rclone_bin.fetch()`: los tests la
    sustituyen entera y ninguno habla con GitHub. Devuelve bytes y no un flujo
    porque lo que baja hay que resumirlo entero para comprobarlo, y lo que no
    está comprobado no se escribe en disco.
    """
    peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(peticion, timeout=timeout) as resp:
        return resp.read()


def a_mano(plat: Plataforma) -> str:
    """Devuelve cómo ponerlo a mano cuando la descarga no sale, con los nombres exactos.

    El archivo va donde lo dejaría la descarga (la caché guarda archivos, no
    extracciones), junto al SHA256SUMS de la misma release: con los dos,
    `adoptar()` lo comprueba igual que una descarga y sin red. El nombre se
    dice entero porque la URL lleva el `+` escapado y el navegador puede
    guardarlo de cualquiera de las dos maneras; el que cuenta es el de aquí.
    """
    return (f"Para ponerlo a mano, baja con el navegador estos dos ficheros:\n"
            f"    {download_url(plat)}\n"
            f"    {SUMS_URL}\n"
            f"y déjalos, sin descomprimir y con esos nombres exactos "
            f"({archive_name(plat)} y {descarga.SUMAS}), en:\n"
            f"    {cache_dir()}\n"
            f"Al volver a intentarlo se comprueban igual que una descarga, y no "
            f"hace falta red.")


def published_sha256(plat: Plataforma, progreso: Progreso | None = None) -> str:
    """Devuelve el SHA-256 que python-build-standalone publica para ese archivo.

    Sale del SHA256SUMS que haya dejado alguien a mano en la caché o, si no
    hay, de la red con reintentos (`descarga.sumas()`).

    Raises:
        InstallError: Si no se puede leer o no trae suma para ese archivo.
    """
    nombre = archive_name(plat)
    try:
        texto, origen = descarga.sumas(SUMS_URL, cache_dir() / descarga.SUMAS,
                                       lambda: fetch(SUMS_URL, 30), progreso)
    except descarga.FALLOS_DE_RED as e:
        raise InstallError(
            f"No he podido leer {SUMS_URL} para comprobar Python de "
            f"{plat.nombre}: {descarga.describir(e)}\n\n{a_mano(plat)}") from e
    suma = descarga.suma_en(texto, nombre)
    if suma is not None:
        return suma
    if origen != SUMS_URL:
        raise InstallError(
            f"{origen} no trae ninguna suma para {nombre}, así que no puedo "
            f"comprobarlo. ¿Es el SHA256SUMS de la release {pins.PYTHON_RELEASE}? "
            f"El que vale es el de {SUMS_URL}.")
    raise InstallError(
        f"{SUMS_URL} no trae ninguna suma para {nombre}, así que no puedo "
        f"comprobar lo que descargue.\n\n¿Ha cambiado python-build-standalone "
        f"cómo publica sus releases? La versión fijada está en common/pins.py.")


def cache_dir() -> Path:
    """Devuelve la caché de runtimes, una carpeta por release.

    Va por release y no por arquitectura, como la de rclone, porque aquí el
    nombre del fichero ya lleva el destino dentro: lo que no puede mezclarse es
    una release con otra.
    """
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    d = Path(base) / f"{APP_NAME}-install" / RUNTIME_SUBDIR / pins.PYTHON_RELEASE
    d.mkdir(parents=True, exist_ok=True)
    return d


def _suma_apuntada(archivo: Path) -> Path:
    """Devuelve el fichero `.sha256` que acompaña al archivo."""
    return archivo.with_name(archivo.name + ".sha256")


def recorded_sha256(archivo: Path) -> str:
    """Devuelve la suma que se comprobó al descargar ese archivo, o `''` si no hay."""
    try:
        return _suma_apuntada(archivo).read_text(encoding="ascii").strip()
    except OSError:
        return ""


def file_sha256(ruta: Path) -> str:
    """Devuelve el SHA-256 de un fichero, leído a trozos (son decenas de megas)."""
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def cached(plat: Plataforma) -> Path | None:
    """Devuelve el archivo de la caché si está y sigue siendo el que se comprobó.

    Se vuelve a resumir cada vez: son unos 30 MB y cuesta menos de un segundo,
    y a cambio una caché truncada o estropeada no llega nunca a un dispositivo.
    """
    archivo = cache_dir() / archive_name(plat)
    try:
        if not archivo.is_file():
            return None
        apuntada = recorded_sha256(archivo)
        if apuntada and file_sha256(archivo) == apuntada:
            return archivo
    except OSError:
        pass
    return None


def download_runtime(plat: Plataforma, progreso: Progreso | None = None) -> Path:
    """Baja el archivo, COMPRUEBA su SHA-256 y lo deja en la caché.

    El alcance de la comprobación es el mismo que el de rclone: la suma viaja
    por el mismo TLS y desde la misma release que el archivo, así que no
    protege de un GitHub (o una cuenta de astral-sh) comprometidos. Ataja todo
    lo demás: una descarga truncada, un proxy que devuelve otra cosa, una caché
    que sirve algo viejo. Y la release está FIJADA en `common/pins.py`: no se
    baja «lo último», se baja lo probado. Los fallos van como los de rclone: un
    corte o un tiempo de espera se reintentan (`descarga.con_reintentos()`),
    una suma que no cuadra no.

    Raises:
        InstallError: Si no se puede leer el SHA256SUMS, descargar o guardar, o
            lo descargado no es lo publicado.
    """
    def decir(msg: str) -> None:
        """Pasa un mensaje a `progreso`, si lo hay."""
        if progreso:
            progreso(msg)

    nombre = archive_name(plat)
    url = download_url(plat)
    decir(f"Python {pins.PYTHON_VERSION} para {plat.nombre}: leyendo SHA256SUMS")
    esperado = published_sha256(plat, progreso)

    decir(f"Descargando {url}")
    try:
        datos = descarga.con_reintentos(lambda: fetch(url), f"Descargar {nombre}",
                                        progreso)
    except descarga.FALLOS_DE_RED as e:
        raise InstallError(
            f"No he podido descargar Python para {plat.nombre} de {url}: "
            f"{descarga.describir(e)}\n\n{a_mano(plat)}") from e

    obtenido = hashlib.sha256(datos).hexdigest()
    if obtenido != esperado:
        raise InstallError(
            f"Lo descargado de {url} no es lo que python-build-standalone "
            f"publica.\n\n  esperado: {esperado}\n  obtenido: {obtenido}\n\n"
            f"No se ha guardado nada. Vuelve a intentarlo; si sigue pasando, algo "
            f"entre este equipo y GitHub cambia lo que llega (un proxy, un portal "
            f"de acceso).\n\n{a_mano(plat)}")
    decir(f"SHA-256 correcto: {obtenido}")

    destino = cache_dir() / nombre
    parcial = destino.with_name(destino.name + ".part")
    try:
        parcial.write_bytes(datos)
        os.replace(parcial, destino)
        _suma_apuntada(destino).write_text(obtenido + "\n", encoding="ascii")
    except OSError as e:
        parcial.unlink(missing_ok=True)
        raise InstallError(f"No he podido guardar {destino}: {e}") from e
    return destino


def adoptar(plat: Plataforma, progreso: Progreso | None = None) -> Path | None:
    """Devuelve el archivo que alguien ha dejado a mano en la caché, ya comprobado.

    Solo vale uno SIN suma apuntada: uno con su `.sha256` al lado salió de una
    descarga y, si ya no cuadra, es una caché estropeada que se vuelve a
    descargar como siempre (`cached()`). Uno sin `.sha256` es otra cosa: o lo
    ha puesto alguien con el nombre de `a_mano()`, o una descarga se cortó
    justo entre el renombrado y apuntar la suma. Los dos se comprueban contra
    el SHA256SUMS (el de al lado si se dejó, si no el de la red) y solo
    entonces se apunta su suma y cuenta como caché. Si no cuadra se dice y NO
    se descarga encima: alguien lo ha puesto ahí a propósito, y pisarlo en
    silencio sería no enterarse de que lo que tiene en la mano no es lo
    publicado.

    Returns:
        El archivo, o `None` si no hay ninguno por comprobar.

    Raises:
        InstallError: Si no se puede leer, no cuadra con la suma publicada o no
            se puede apuntar su suma.
    """
    archivo = cache_dir() / archive_name(plat)
    try:
        if not archivo.is_file() or _suma_apuntada(archivo).exists():
            return None
    except OSError:
        return None
    if progreso:
        progreso(f"Python para {plat.nombre}: comprobando {archivo}")
    esperado = published_sha256(plat, progreso)
    try:
        obtenido = file_sha256(archivo)
    except OSError as e:
        raise InstallError(f"No he podido leer {archivo}: {e}") from e
    if obtenido != esperado:
        raise InstallError(
            f"{archivo} no es el archivo que python-build-standalone publica para "
            f"{plat.nombre}.\n\n  esperado: {esperado}\n  obtenido: {obtenido}\n\n"
            f"No lo he usado. ¿Se cortó la descarga del navegador? Bórralo y "
            f"vuelve a bajarlo de {download_url(plat)}; o bórralo sin más y el "
            f"instalador lo descargará.")
    try:
        _suma_apuntada(archivo).write_text(obtenido + "\n", encoding="ascii")
    except OSError as e:
        raise InstallError(f"No he podido apuntar la suma de {archivo}: {e}") from e
    return archivo


def ensure_runtime(plat: Plataforma, progreso: Progreso | None = None,
                   allow_download: bool = True) -> Path:
    """Devuelve el archivo comprobado de esa plataforma; descarga solo si hace falta.

    Un archivo dejado a mano (`adoptar()`) cuenta aunque no se permita
    descargar, como en `rclone_bin.rclone_for()`: es un fichero de este equipo.

    Raises:
        InstallError: Si no hay archivo y no se permite descargar.
    """
    encontrado = cached(plat) or adoptar(plat, progreso)
    if not encontrado and not allow_download:
        raise InstallError(
            f"No hay Python para {plat.nombre} en la caché y no se ha "
            f"permitido descargarlo.")
    archivo = encontrado or download_runtime(plat, progreso)
    ensure_tk(plat, progreso, allow_download)
    return archivo


TK_DIR = "lib/tk-xft"
"""Dónde va el Tk con Xft dentro de un runtime de Linux, al lado del de serie.

No lo sustituye: el de serie es el que sirve en un equipo sin `libXft` (un
servidor sin escritorio), y es `ui` quien elige al arrancar (`ui.tk_con_xft`).
"""
TK_LIB = "libtcl9tk9.0.so"
"""La biblioteca, con el mismo nombre (y SONAME) que la de serie."""
TK_MIEMBROS = (TK_LIB, "LICENSE-tk.txt")
"""Lo que trae su paquete, y lo único que se acepta de él."""


def lleva_tk(plat: Plataforma) -> bool:
    """Indica si el runtime de esa plataforma lleva el Tk con Xft: los de Linux."""
    return not plat.es_windows


def tk_archive_name(plat: Plataforma) -> str:
    """Devuelve el nombre del paquete del Tk con Xft para esa plataforma."""
    return f"{pins.TK_XFT_TAG}-{plat.triple.split('-')[0]}-linux.tar.gz"


def tk_url(plat: Plataforma) -> str:
    """Devuelve la URL del paquete en su release (`pins.TK_XFT_TAG`)."""
    return f"{pins.TK_XFT_BASE_URL}/{pins.TK_XFT_TAG}/{tk_archive_name(plat)}"


def tk_esperado(plat: Plataforma) -> str:
    """Devuelve el SHA-256 fijado del paquete, o `''` si no hay ninguno fijado."""
    return pins.TK_XFT_SHA256.get(plat.triple.split("-")[0], "")


def tk_xft(plat: Plataforma) -> Path | None:
    """Devuelve el paquete del Tk con Xft de la caché, si está y es el fijado.

    Se resume cada vez, como `cached()`: son unos 700 KB.

    Returns:
        El paquete, o `None` si esa plataforma no lo lleva o no está comprobado.
    """
    esperado = tk_esperado(plat)
    if not lleva_tk(plat) or not esperado:
        return None
    archivo = cache_dir() / tk_archive_name(plat)
    try:
        if archivo.is_file() and file_sha256(archivo) == esperado:
            return archivo
    except OSError:
        pass
    return None


def ensure_tk(plat: Plataforma, progreso: Progreso | None = None,
              allow_download: bool = True) -> Path | None:
    """Deja en la caché el Tk con Xft de esa plataforma y lo devuelve; NUNCA falla.

    Sin él el runtime funciona igual, con el Tk de serie y la letra sin
    suavizar, así que un fallo de red o una suma que no cuadra se dicen y no
    paran una instalación: el sello del runtime no lo anotará y
    `components.python_pendiente()` lo seguirá ofreciendo. Lo que no cuadra no
    se guarda.

    Returns:
        El paquete comprobado, o `None` si no lo lleva o no se ha podido.
    """
    def decir(msg: str) -> None:
        """Pasa un mensaje a `progreso`, si lo hay."""
        if progreso:
            progreso(msg)

    esperado = tk_esperado(plat)
    if not lleva_tk(plat) or not esperado:
        return None
    encontrado = tk_xft(plat)
    if encontrado or not allow_download:
        return encontrado
    url = tk_url(plat)
    sin = (f"El Python de {plat.nombre} va con el Tk de serie: la ventana se verá "
           f"con la letra sin suavizar hasta que se actualice desde «Ajustes → "
           f"Actualizaciones».")
    decir(f"Tk con Xft para {plat.nombre}: descargando {url}")
    try:
        datos = descarga.con_reintentos(lambda: fetch(url), f"Descargar "
                                        f"{tk_archive_name(plat)}", progreso)
    except descarga.FALLOS_DE_RED as e:
        decir(f"No he podido descargar {url}: {descarga.describir(e)}. {sin}")
        return None
    obtenido = hashlib.sha256(datos).hexdigest()
    if obtenido != esperado:
        decir(f"Lo descargado de {url} no es lo fijado en common/pins.py "
              f"(esperado {esperado}, obtenido {obtenido}); no lo he guardado. {sin}")
        return None
    destino = cache_dir() / tk_archive_name(plat)
    parcial = destino.with_name(destino.name + ".part")
    try:
        parcial.write_bytes(datos)
        os.replace(parcial, destino)
    except OSError as e:
        parcial.unlink(missing_ok=True)
        decir(f"No he podido guardar {destino}: {e}. {sin}")
        return None
    return destino


def _extraer_tk(paquete: Path, destino: Path) -> None:
    """Escribe el Tk con Xft de `paquete` en `destino/lib/tk-xft/`.

    Del paquete solo se acepta lo de `TK_MIEMBROS`, como ficheros normales y en
    su raíz; cualquier otra cosa lo invalida entero antes de escribir nada.

    Raises:
        InstallError: Si el paquete no es lo esperado o no se puede escribir.
    """
    carpeta = destino.joinpath(*TK_DIR.split("/"))
    try:
        with tarfile.open(paquete, "r:gz") as tf:
            miembros = {}
            for m in tf.getmembers():
                nombre = m.name[2:] if m.name.startswith("./") else m.name
                if nombre in ("", "."):
                    continue
                if nombre not in TK_MIEMBROS or not m.isfile():
                    raise InstallError(f"{paquete} trae {m.name!r}, que no es del "
                                       f"Tk con Xft. No se ha escrito nada.")
                miembros[nombre] = m
            if TK_LIB not in miembros:
                raise InstallError(f"{paquete} no trae {TK_LIB}.")
            carpeta.mkdir(parents=True, exist_ok=True)
            for nombre, m in miembros.items():
                origen = tf.extractfile(m)
                if origen is None:
                    continue
                with origen, open(carpeta / nombre, "wb") as dst:
                    shutil.copyfileobj(origen, dst)
    except (tarfile.TarError, EOFError) as e:
        raise InstallError(f"{paquete} no es un paquete válido: {e}") from e
    except OSError as e:
        raise InstallError(f"No he podido escribir el Tk con Xft en {carpeta}: "
                           f"{e}") from e


def stamp_text(plat: Plataforma, sha256: str, con_tk: bool | None = None) -> str:
    """Devuelve el sello de un runtime: de qué archivo exacto salió.

    penwatch compara el texto entero con el de su copia en el equipo; cualquier
    diferencia (otra versión, otra release, otro archivo) es «refrescar».

    Args:
        con_tk: Si lleva el Tk con Xft (`tk = <tag>`). Sin decirlo, lo
            llevará si su paquete está comprobado en la caché, que es lo que
            hará `extract()`: así el sello que se espera y el que se escribe
            son el mismo.
    """
    if con_tk is None:
        con_tk = tk_xft(plat) is not None
    return (f"# {APP_NAME} — el Python de este dispositivo. Lo escribe el "
            f"instalador y lo compara penwatch. No lo toques.\n"
            f"python = {pins.PYTHON_VERSION}\n"
            f"release = {pins.PYTHON_RELEASE}\n"
            f"triple = {plat.triple}\n"
            f"sha256 = {sha256}\n"
            + (f"tk = {pins.TK_XFT_TAG}\n" if con_tk else ""))


def _relativo(nombre: str) -> str | None:
    """Devuelve la ruta del miembro relativa a la raíz del runtime, sin el `python/`.

    Un cambio de empaquetado se dice, no se extrae a ciegas.

    Returns:
        La ruta, o `None` para la raíz misma.

    Raises:
        InstallError: Si pretende salirse o no está bajo la raíz que publica
            python-build-standalone.
    """
    limpio = _ruta_segura(nombre)
    if limpio is None:
        raise InstallError(f"El archivo trae un miembro que se sale del destino: "
                           f"{nombre!r}. No se ha escrito nada.")
    limpio = limpio.rstrip("/")
    if limpio == RAIZ_ARCHIVO:
        return None
    if not limpio.startswith(RAIZ_ARCHIVO + "/"):
        raise InstallError(f"El archivo trae {nombre!r} fuera de {RAIZ_ARCHIVO}/. "
                           f"¿Ha cambiado el empaquetado? No se ha escrito nada.")
    return limpio[len(RAIZ_ARCHIVO) + 1:]


def extract(archivo: Path, destino: Path, plat: Plataforma, sha256: str, *,
            entero: bool = False) -> int:
    """Extrae el runtime en `destino` y le pone el sello.

    Son dos pasadas: la primera valida y decide sin tocar el disco; la segunda
    escribe. Así un archivo con un solo miembro malo no deja nada a medias.

    Args:
        entero: Si se extrae entero, sin podar lo que prdrive no usa
            (`podar()`). Solo el Python con el que se compila el instalador va
            entero (`tests/_runtime_ci.py compilador`): necesita pip.

    Returns:
        Cuántos ficheros ha escrito, el sello incluido.

    Raises:
        InstallError: Si el archivo no es válido, algún miembro es peligroso o
            no se puede escribir.
    """
    prefijos = podar(plat)
    estables = {plat.interprete, plat.interprete_consola}
    tk = tk_xft(plat)
    try:
        with tarfile.open(archivo, "r:gz") as tf:
            miembros = tf.getmembers()

            # Primera pasada: validar y decidir.
            regulares: dict[str, tarfile.TarInfo] = {}
            enlaces: dict[str, str] = {}
            for m in miembros:
                rel = _relativo(m.name)
                if rel is None:
                    continue
                if m.isfile():
                    regulares[rel] = m
                elif m.issym() and rel in estables:
                    objetivo = posixpath.normpath(
                        posixpath.join(posixpath.dirname(rel), m.linkname))
                    if m.linkname.startswith("/") or objetivo.startswith(".."):
                        raise InstallError(
                            f"{m.name} es un enlace que apunta fuera del runtime "
                            f"({m.linkname}). No se ha escrito nada.")
                    enlaces[rel] = objetivo

            # Un enlace estable se escribe con el contenido de su destino, y el
            # destino deja de escribirse con su propio nombre.
            renombrar: dict[str, str] = {}
            for enlace, objetivo in enlaces.items():
                if objetivo not in regulares:
                    raise InstallError(
                        f"{enlace} apunta a {objetivo}, que no está en el archivo.")
                renombrar[objetivo] = enlace

            escribir = []
            for rel, m in regulares.items():
                salida = renombrar.get(rel, rel)
                if not entero and _podado(salida, prefijos, plat):
                    continue
                escribir.append((salida, m))

            faltan = sorted(estables - {s for s, _ in escribir})
            if faltan:
                raise InstallError(
                    f"El archivo de Python para {plat.nombre} no trae "
                    f"{', '.join(faltan)}. No se ha escrito nada.")

            # Segunda pasada: escribir.
            destino.mkdir(parents=True, exist_ok=True)
            for salida, m in escribir:
                ruta = destino.joinpath(*salida.split("/"))
                ruta.parent.mkdir(parents=True, exist_ok=True)
                origen = tf.extractfile(m)
                if origen is None:
                    continue
                with origen, open(ruta, "wb") as dst:
                    shutil.copyfileobj(origen, dst)
                if not IS_WIN and m.mode & 0o111:
                    try:
                        ruta.chmod(ruta.stat().st_mode | 0o755)
                    except OSError:
                        pass  # exFAT: no hay permisos que poner
    except (tarfile.TarError, EOFError) as e:
        raise InstallError(f"{archivo} no es un archivo válido: {e}") from e
    except OSError as e:
        raise InstallError(f"No he podido extraer Python en {destino}: {e}") from e

    # El Tk con Xft, si está en la caché (`ensure_tk()`). Si no, el runtime va
    # con el de serie y su sello no lo anota.
    if tk is not None:
        _extraer_tk(tk, destino)

    # Va el ÚLTIMO: sin sello, lo de arriba no cuenta como un runtime
    # instalado.
    try:
        (destino / STAMP).write_text(stamp_text(plat, sha256, tk is not None),
                                     encoding="utf-8", newline="\n")
    except OSError as e:
        raise InstallError(f"No he podido escribir el sello en {destino}: {e}") from e
    return len(escribir) + 1
