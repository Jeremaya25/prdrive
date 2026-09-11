#!/usr/bin/env python3
"""
runtime_bin.py — Conseguir el Python que viaja dentro del dispositivo.

El hermano de `rclone_bin.py`, con el mismo contrato: lo que se descarga se
COMPRUEBA contra el `SHA256SUMS` que publica su autor antes de escribir nada, y si
no cuadra no se guarda nada. Esto se va a ejecutar en cada equipo donde se
enchufe el dispositivo, así que «lo que haya llegado» no vale.

**Qué se baja.** La distribución `install_only_stripped` de python-build-standalone
(astral-sh), de la release fijada en `common/pins.py`. Es un Python reubicable
—se descomprime donde sea y funciona— y, a diferencia del zip embebible oficial,
trae tkinter. Por eso es este y no aquel: sin tkinter no hay ventana.

**Dónde se guarda.** El archivo comprobado va a la caché del usuario
(`%LOCALAPPDATA%/prdrive-install/runtime/<release>/`), con su suma apuntada al
lado. La caché es por release y los ficheros se llaman por su destino, así que
distintas plataformas y distintas versiones no se pisan. Al dispositivo llega una
EXTRACCIÓN de ese archivo, que hace `extract()` y coloca `deploy.install_runtime()`.

**Qué se escribe al extraer, y qué no.**

  * Todo miembro se valida ANTES de escribir el primero: uno solo que pretenda
    salirse del destino tumba la extracción entera. Un `extractall()` a secas es
    el clásico agujero, y un archivo es contenido ajeno aunque venga comprobado.
  * No se crean enlaces simbólicos: exFAT no los tiene, y el dispositivo casi
    siempre es exFAT. El único que hace falta —`bin/python3` en Linux, que en el
    archivo es un enlace a `python3.13`— se materializa escribiendo su destino con
    ese nombre (y no dos veces: son 30 MB).
  * Se poda lo que no hace falta para ejecutar prdrive: pip, ensurepip, idle, los
    tests, las cabeceras y bibliotecas de C, y en Linux `share/` (terminfo, man) y
    la `libpython.so`, que es para quien incrusta Python —el intérprete de
    python-build-standalone la lleva enlazada estática—.
  * El sello (`STAMP`) se escribe el ÚLTIMO. Un runtime a medias no lo tiene, y
    sin sello no cuenta como instalado: ni para el asistente, ni para penwatch.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from common import pins
from common.pins import Plataforma
from common.update import _ruta_segura

from . import APP_NAME, IS_WIN, InstallError

DOWNLOAD_TIMEOUT = 60          # segundos por lectura, no en total
USER_AGENT = f"{APP_NAME}-install"
Progreso = Callable[[str], None]

# El sello de versión de cada runtime del dispositivo: `runtime/<clave>/STAMP`.
# penwatch lo compara con el de su copia en el equipo para saber si tiene que
# refrescarla, así que el nombre está repetido allí —y un test impide que las dos
# copias se separen—.
STAMP = "PRDRIVE-RUNTIME"
RUNTIME_SUBDIR = "runtime"

SUMS_URL = f"{pins.PBS_BASE_URL}/{pins.PYTHON_RELEASE}/SHA256SUMS"

# El directorio raíz de todos los archivos de python-build-standalone.
RAIZ_ARCHIVO = "python"


def _mm() -> str:
    """'3.13' de '3.13.15': el tramo que aparece en las rutas del runtime."""
    return ".".join(pins.PYTHON_VERSION.split(".")[:2])


def podar(plat: Plataforma) -> tuple[str, ...]:
    """Los prefijos (relativos a la raíz del runtime) que NO viajan.

    Lo que hay aquí es lo que ninguna parte de prdrive importa. Quitarlo ahorra
    unos 15 MB por plataforma en Windows y bastante más en Linux; lo que no está
    aquí se queda, aunque parezca que sobra, porque un runtime al que le falta un
    módulo falla en el equipo de otro y lejos de quien lo podría arreglar."""
    if plat.es_windows:
        return ("Lib/site-packages/", "Lib/ensurepip/", "Lib/idlelib/",
                "Lib/test/", "Lib/turtledemo/", "include/", "libs/", "Scripts/")
    lib = f"lib/python{_mm()}/"
    return ("share/", "include/", "lib/pkgconfig/", "lib/libpython",
            lib + "site-packages/", lib + "ensurepip/", lib + "idlelib/",
            lib + "test/", lib + "turtledemo/", f"{lib}config-{_mm()}")


def _podado(rel: str, prefijos: tuple[str, ...], plat: Plataforma) -> bool:
    if any(rel.startswith(p) or rel == p.rstrip("/") for p in prefijos):
        return True
    # En bin/ de Linux solo hace falta el intérprete: pip, idle, pydoc y los
    # *-config son guiones que apuntan al nombre versionado y aquí no se usan.
    return (not plat.es_windows and rel.startswith("bin/")
            and rel not in (plat.interprete, plat.interprete_consola))


# ---------------------------------------------------------------------------
# Nombres y URL
# ---------------------------------------------------------------------------

def archive_name(plat: Plataforma) -> str:
    return (f"cpython-{pins.PYTHON_VERSION}+{pins.PYTHON_RELEASE}-{plat.triple}"
            f"-install_only_stripped.tar.gz")


def download_url(plat: Plataforma) -> str:
    """La URL del archivo de ESA release. El '+' del nombre va escapado: GitHub
    lo sirve igual, pero en una ruta es un espacio para más de un proxy."""
    return (f"{pins.PBS_BASE_URL}/{pins.PYTHON_RELEASE}/"
            f"{urllib.parse.quote(archive_name(plat))}")


def fetch(url: str, timeout: float = DOWNLOAD_TIMEOUT) -> bytes:
    """La única puerta de salida a la red de este módulo.

    De módulo a propósito, igual que `rclone_bin.fetch()`: los tests la
    sustituyen entera y ninguno habla con GitHub. Devuelve bytes y no un flujo
    porque lo que baja hay que resumirlo entero para comprobarlo, y lo que no
    está comprobado no se escribe en disco."""
    peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(peticion, timeout=timeout) as resp:
        return resp.read()


def published_sha256(plat: Plataforma) -> str:
    """El SHA-256 que python-build-standalone publica para ese archivo."""
    nombre = archive_name(plat)
    texto = fetch(SUMS_URL, 30).decode("utf-8", "replace")
    for linea in texto.splitlines():
        partes = linea.split()
        if len(partes) == 2 and partes[1].lstrip("*") == nombre:
            return partes[0].lower()
    raise InstallError(
        f"{SUMS_URL} no trae ninguna suma para {nombre}, así que no puedo "
        f"comprobar lo que descargue.\n\n¿Ha cambiado python-build-standalone "
        f"cómo publica sus releases? La versión fijada está en common/pins.py.")


# ---------------------------------------------------------------------------
# La caché
# ---------------------------------------------------------------------------

def cache_dir() -> Path:
    """La caché de runtimes, una carpeta por release.

    Por release y no por arquitectura (como la de rclone) porque aquí el nombre
    del fichero ya lleva el destino dentro: lo que no puede mezclarse es una
    release con otra."""
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    d = Path(base) / f"{APP_NAME}-install" / RUNTIME_SUBDIR / pins.PYTHON_RELEASE
    d.mkdir(parents=True, exist_ok=True)
    return d


def _suma_apuntada(archivo: Path) -> Path:
    return archivo.with_name(archivo.name + ".sha256")


def recorded_sha256(archivo: Path) -> str:
    """La suma que se comprobó al descargar ese archivo ('' si no hay)."""
    try:
        return _suma_apuntada(archivo).read_text(encoding="ascii").strip()
    except OSError:
        return ""


def file_sha256(ruta: Path) -> str:
    """El SHA-256 de un fichero, leído a trozos (son decenas de megas)."""
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def cached(plat: Plataforma) -> Path | None:
    """El archivo de la caché, si está y sigue siendo el que se comprobó.

    Se vuelve a resumir cada vez: son unos 30 MB y cuesta menos de un segundo, y
    a cambio una caché truncada o estropeada no llega nunca a un dispositivo."""
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
    """Baja el archivo, COMPRUEBA su SHA-256, y lo deja en la caché.

    El alcance de la comprobación es el mismo que el de rclone, y conviene
    decirlo igual de claro: la suma viaja por el mismo TLS y desde la misma
    release que el archivo, así que no protege de un GitHub —o una cuenta de
    astral-sh— comprometidos. Ataja todo lo demás: una descarga truncada, un
    proxy que devuelve otra cosa, una caché que sirve algo viejo. Y la release
    está FIJADA en `common/pins.py`: no se baja «lo último», se baja lo probado."""
    def decir(msg: str) -> None:
        if progreso:
            progreso(msg)

    nombre = archive_name(plat)
    url = download_url(plat)
    decir(f"Python {pins.PYTHON_VERSION} para {plat.nombre}: leyendo SHA256SUMS")
    esperado = published_sha256(plat)

    decir(f"Descargando {url}")
    try:
        datos = fetch(url)
    except (urllib.error.URLError, OSError) as e:
        raise InstallError(
            f"No he podido descargar Python para {plat.nombre} de {url}: {e}") from e

    obtenido = hashlib.sha256(datos).hexdigest()
    if obtenido != esperado:
        raise InstallError(
            f"Lo descargado de {url} no es lo que python-build-standalone "
            f"publica.\n\n  esperado: {esperado}\n  obtenido: {obtenido}\n\n"
            f"No se ha guardado nada. Vuelve a intentarlo.")
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


def ensure_runtime(plat: Plataforma, progreso: Progreso | None = None,
                   allow_download: bool = True) -> Path:
    """El archivo comprobado de esa plataforma. Descarga solo si hace falta."""
    encontrado = cached(plat)
    if encontrado:
        return encontrado
    if not allow_download:
        raise InstallError(
            f"No hay Python para {plat.nombre} en la caché y no se ha "
            f"permitido descargarlo.")
    return download_runtime(plat, progreso)


# ---------------------------------------------------------------------------
# Extraer
# ---------------------------------------------------------------------------

def stamp_text(plat: Plataforma, sha256: str) -> str:
    """El sello de un runtime: de qué archivo exacto salió.

    penwatch compara el texto entero con el de su copia en el equipo; cualquier
    diferencia —otra versión, otra release, otro archivo— es «refrescar»."""
    return (f"# {APP_NAME} — el Python de este dispositivo. Lo escribe el "
            f"instalador y lo compara penwatch. No lo toques.\n"
            f"python = {pins.PYTHON_VERSION}\n"
            f"release = {pins.PYTHON_RELEASE}\n"
            f"triple = {plat.triple}\n"
            f"sha256 = {sha256}\n")


def _relativo(nombre: str) -> str | None:
    """La ruta del miembro relativa a la raíz del runtime, sin el 'python/'.

    None para la raíz misma. InstallError si pretende salirse o no está bajo la
    raíz que publica python-build-standalone: un cambio de empaquetado se dice,
    no se extrae a ciegas."""
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


def extract(archivo: Path, destino: Path, plat: Plataforma, sha256: str) -> int:
    """Extrae el runtime en `destino` y le pone el sello. Devuelve cuántos
    ficheros ha escrito (el sello incluido).

    Dos pasadas: la primera valida y decide, sin tocar el disco; la segunda
    escribe. Así un archivo con un solo miembro malo no deja nada a medias."""
    prefijos = podar(plat)
    estables = {plat.interprete, plat.interprete_consola}
    try:
        with tarfile.open(archivo, "r:gz") as tf:
            miembros = tf.getmembers()

            # --- primera pasada: validar y decidir ---------------------------
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
                if _podado(salida, prefijos, plat):
                    continue
                escribir.append((salida, m))

            faltan = sorted(estables - {s for s, _ in escribir})
            if faltan:
                raise InstallError(
                    f"El archivo de Python para {plat.nombre} no trae "
                    f"{', '.join(faltan)}. No se ha escrito nada.")

            # --- segunda pasada: escribir ---------------------------------------
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
                        pass        # exFAT: no hay permisos que poner
    except (tarfile.TarError, EOFError) as e:
        raise InstallError(f"{archivo} no es un archivo válido: {e}") from e
    except OSError as e:
        raise InstallError(f"No he podido extraer Python en {destino}: {e}") from e

    # El ÚLTIMO: sin sello, lo de arriba no cuenta como un runtime instalado.
    try:
        (destino / STAMP).write_text(stamp_text(plat, sha256), encoding="utf-8",
                                     newline="\n")
    except OSError as e:
        raise InstallError(f"No he podido escribir el sello en {destino}: {e}") from e
    return len(escribir) + 1
