#!/usr/bin/env python3
"""
rclone_bin.py — Conseguir un rclone con el que arrancar.

El instalador corre en un equipo cualquiera, que puede no tener rclone. Se busca
en este orden y solo se descarga si no queda otra:

    1. bin/<arch>/ junto al instalador   <- ejecutándolo desde un checkout
    2. junto al propio ejecutable        <- el .exe y el rclone.exe en la misma carpeta
    3. el PATH del equipo
    4. la caché de descargas de instalaciones anteriores
    5. descarga del zip portable de rclone.org

Lo que se descarga se COMPRUEBA contra el SHA256SUMS que publica rclone antes de
tocar el disco, y si no cuadra no se guarda nada: esto se va a ejecutar y va a
acabar copiado dentro del dispositivo. El alcance de esa comprobación está
escrito sin adornos en `download_rclone()`.

La descarga va a la caché del usuario, nunca al dispositivo: en este punto puede
que todavía no exista. El binario que acabe usando el dispositivo es UNA COPIA de
éste, que deja `deploy.copy_rclone()` en su `bin/<arch>/`.
"""

from __future__ import annotations

import hashlib
import io
import os
import platform
import shutil
import stat
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from common.model import arch_dir, machine_arch

from . import APP_NAME, RCLONE_BASE_URL, InstallError, bundle_dir

DOWNLOAD_TIMEOUT = 60          # segundos por lectura, no en total
Progreso = Callable[[str], None]


def exe_name() -> str:
    return "rclone.exe" if os.name == "nt" else "rclone"


def os_arch() -> tuple[str, str]:
    """(so, arquitectura) con los nombres que usa rclone en sus zips.

    La arquitectura sale de `machine_arch()`, no de `platform.machine()`, por lo
    mismo que `bin_subdir()` se la pregunta al modelo: el instalador es un .exe
    x64 y en un Windows ARM se creería en un equipo x64, así que descargaba el
    rclone de amd64 para dejarlo en el `bin/arm` que mira el dispositivo."""
    sysname = {"windows": "windows", "darwin": "osx", "linux": "linux"}.get(
        platform.system().lower(), "linux")
    # ARM o x86 lo decide `arch_dir()`, no una segunda tabla de aquí: tenía una
    # y se le había quedado corta —'aarch64_be' era ARM para el dispositivo y
    # amd64 para el instalador—, que es exactamente el desajuste que este módulo
    # no puede permitirse, porque el zip que baja acaba dentro de la carpeta que
    # elige el otro. Dentro de x86 sí queda algo que decidir: 32 o 64 bits.
    machine = machine_arch()
    if arch_dir() == "arm":
        arch = "arm64"
    elif machine in {"i386", "i686", "x86"}:
        arch = "386"
    else:
        arch = "amd64"
    return sysname, arch


def bin_subdir() -> str:
    """El subdirectorio de bin/ del dispositivo, que no usa los nombres de rclone.

    Se pregunta al modelo del proyecto en vez de repetir la tabla: es el mismo
    bin/ que va a usar sync.py luego, y si dejaran de coincidir el instalador
    verificaría un binario y el dispositivo usaría otro."""
    return arch_dir()


def cache_dir() -> Path:
    """La caché de descargas, con una carpeta por arquitectura.

    Separada por arquitectura porque si no la caché es lo que deshace el
    arreglo: un instalador que se creyó x64 en un equipo ARM dejó ahí un rclone
    de amd64, y al volver a instalar `find_rclone()` lo encuentra antes de
    plantearse descargar, así que el `download_url()` correcto no llega a
    usarse nunca. El binario del zip depende de la arquitectura; el sitio donde
    se guarda, también."""
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    d = Path(base) / "prdrive-install" / bin_subdir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def candidates() -> list[Path]:
    """Dónde se mira, en orden, antes de plantearse descargar nada."""
    exe = exe_name()
    aqui = bundle_dir()
    rutas = [aqui / "bin" / bin_subdir() / exe, aqui / exe]
    en_path = shutil.which("rclone")
    if en_path:
        rutas.append(Path(en_path))
    rutas.append(cache_dir() / exe)
    return rutas


def find_rclone() -> Path | None:
    """El primer rclone utilizable, sin descargar nada. None si no hay ninguno."""
    for ruta in candidates():
        try:
            if ruta.is_file():
                return ruta
        except OSError:
            continue
    return None


VERSION_URL = f"{RCLONE_BASE_URL}/version.txt"
USER_AGENT = f"{APP_NAME}-install"


def fetch(url: str, timeout: float = DOWNLOAD_TIMEOUT) -> bytes:
    """La única puerta de salida a la red de este módulo.

    De módulo a propósito, igual que `update.fetch()` y `catalog.run()`: los
    tests la sustituyen entera y así ninguno habla con rclone.org. Devuelve
    bytes y no un flujo porque lo que baja hay que resumirlo entero para
    comprobarlo, y porque lo que no está comprobado no se escribe en disco."""
    peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(peticion, timeout=timeout) as resp:
        return resp.read()


def latest_version() -> str:
    """La versión que rclone publica como actual, en la forma 'v1.75.0'.

    Hace falta saberla para poder comprobar nada: las sumas viven en
    `<versión>/SHA256SUMS` y ahí dentro los ficheros se nombran con su versión,
    no como `rclone-current-…`."""
    texto = fetch(VERSION_URL, 30).decode("utf-8", "replace").strip()
    # version.txt dice «rclone v1.75.0».
    for parte in texto.split():
        if parte.startswith("v") and parte[1:2].isdigit():
            return parte
    raise InstallError(
        f"No entiendo lo que contesta {VERSION_URL}: {texto[:120]!r}\n"
        f"Con conexión limitada, copia un rclone a mano en {cache_dir()}.")


def zip_name(version: str) -> str:
    sysname, arch = os_arch()
    return f"rclone-{version}-{sysname}-{arch}.zip"


def download_url(version: str) -> str:
    """La URL del zip de ESA versión, nunca el alias `rclone-current-…`.

    El alias apunta a lo último que haya publicado rclone en el momento de
    pedirlo, y eso no se puede comprobar: entre leer `version.txt` y bajar el
    zip puede salir una versión nueva, y entonces la suma que tenemos en la mano
    es de un fichero y el fichero es otro. Fallaría la comprobación sin que nada
    vaya mal, que es la peor manera de fallar. Con la URL versionada las dos
    mitades hablan de lo mismo por construcción."""
    return f"{RCLONE_BASE_URL}/{version}/{zip_name(version)}"


def published_sha256(version: str, nombre_zip: str) -> str:
    """El SHA-256 que rclone publica para ese zip, sacado de su SHA256SUMS."""
    url = f"{RCLONE_BASE_URL}/{version}/SHA256SUMS"
    texto = fetch(url, 30).decode("utf-8", "replace")
    for linea in texto.splitlines():
        partes = linea.split()
        # El formato es «<suma>  <fichero>»; el '*' delante del nombre es la
        # marca de «modo binario» de coreutils, que rclone no usa pero que no
        # cuesta nada tolerar.
        if len(partes) == 2 and partes[1].lstrip("*") == nombre_zip:
            return partes[0].lower()
    raise InstallError(
        f"{url} no trae ninguna suma para {nombre_zip}, así que no puedo "
        f"comprobar lo que descargue.\n\n¿Ha cambiado rclone cómo publica sus "
        f"versiones? Mientras tanto, baja rclone a mano de {RCLONE_BASE_URL} y "
        f"déjalo en {cache_dir()}.")


def download_rclone(progreso: Progreso | None = None) -> Path:
    """Baja el zip portable, COMPRUEBA su SHA-256, y deja el binario en la caché.

    Lo que se descarga aquí se va a ejecutar y va a acabar copiado dentro del
    dispositivo, así que se compara con la suma que rclone publica antes de
    escribir nada. Conviene ser honesto sobre hasta dónde llega eso: la suma
    viaja por el mismo TLS y desde el mismo servidor que el zip, así que **no**
    protege de que rclone.org esté comprometido —quien pudiera cambiar uno
    podría cambiar la otra—. Lo que sí ataja es todo lo demás: una descarga
    truncada, un proxy de empresa que devuelve otra cosa o una página de error,
    una caché que sirve un artefacto viejo, y el alias `current` moviéndose bajo
    los pies. Y sobre todo convierte «se ejecuta lo que haya llegado» en «se
    ejecuta lo que rclone dice que publicó»."""
    def decir(msg: str) -> None:
        if progreso:
            progreso(msg)

    version = latest_version()
    nombre = zip_name(version)
    url = download_url(version)

    decir(f"rclone publica {version}; leyendo su SHA256SUMS")
    esperado = published_sha256(version, nombre)

    decir(f"Descargando {url}")
    try:
        datos = fetch(url)
    except (urllib.error.URLError, OSError) as e:
        raise InstallError(
            f"No he podido descargar rclone de {url}: {e}\n"
            f"Con conexión limitada, copia un rclone a mano en {cache_dir()}.") from e

    obtenido = hashlib.sha256(datos).hexdigest()
    if obtenido != esperado:
        # Ni se guarda ni se descomprime: no hay ningún motivo bueno para que
        # esto pase, y seguir sería ejecutar algo que no se sabe qué es.
        raise InstallError(
            f"Lo descargado de {url} no es lo que rclone publica.\n\n"
            f"  esperado: {esperado}\n"
            f"  obtenido: {obtenido}\n\n"
            f"No se ha guardado nada. Vuelve a intentarlo; si sigue pasando, "
            f"baja rclone a mano de {RCLONE_BASE_URL} y déjalo en {cache_dir()}.")
    decir(f"SHA-256 correcto: {obtenido}")

    # A partir de aquí ya se puede tocar el disco.
    destino = cache_dir() / exe_name()
    try:
        with zipfile.ZipFile(io.BytesIO(datos)) as zf:
            # El zip trae una carpeta con versión dentro; el binario es el único
            # miembro que se llama así, pero si rclone cambia el empaquetado hay
            # que decirlo, no reventar con un StopIteration sin contexto.
            miembros = [m for m in zf.namelist() if m.rsplit("/", 1)[-1] == exe_name()]
            if not miembros:
                raise InstallError(
                    f"El zip de rclone no contiene ningún {exe_name()}. "
                    f"¿Ha cambiado el empaquetado en {url}?")
            with zf.open(miembros[0]) as src, open(destino, "wb") as dst:
                shutil.copyfileobj(src, dst)
    except zipfile.BadZipFile as e:
        raise InstallError(f"El fichero descargado de {url} no es un zip válido: {e}") from e

    if os.name != "nt":
        destino.chmod(destino.stat().st_mode | stat.S_IXUSR | stat.S_IRUSR)
    decir(f"rclone listo: {destino}")
    return destino


def ensure_rclone(progreso: Progreso | None = None,
                  allow_download: bool = True) -> Path:
    """El rclone que se va a usar. Descarga solo si hace falta y se le permite."""
    encontrado = find_rclone()
    if encontrado:
        return encontrado
    if not allow_download:
        raise InstallError(
            "No hay rclone en este equipo y no se ha permitido descargarlo.")
    return download_rclone(progreso)
