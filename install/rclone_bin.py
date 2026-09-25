#!/usr/bin/env python3
"""
rclone_bin.py — Conseguir un rclone con el que arrancar.

El instalador corre en un equipo cualquiera, que puede no tener rclone. Se busca
en este orden y solo se descarga si no queda otra:

    1. bin/<arch>/ junto al instalador   <- ejecutándolo desde un checkout
    2. junto al propio ejecutable        <- el .exe y el rclone.exe en la misma carpeta
    3. el PATH del equipo
    4. la caché de descargas de instalaciones anteriores
    5. descarga del zip portable de rclone.org, de la versión FIJADA en
       `common/pins.py` —no la última que haya publicado rclone—

Eso es para ESTE equipo. El dispositivo puede llevar además rclone para otras
plataformas (`rclone_for()`): de esas no hay nada que buscar en el equipo, así que
salen de la caché, de un zip oficial dejado a mano en ella (`adoptar_zip()`) o de
la descarga.

Lo que se descarga se COMPRUEBA contra el SHA256SUMS que publica rclone antes de
tocar el disco, y si no cuadra no se guarda nada: esto se va a ejecutar y va a
acabar copiado dentro del dispositivo. El alcance de esa comprobación está
escrito sin adornos en `download_rclone()`. Un fallo de red se reintenta
(`descarga.con_reintentos()`); una suma que no cuadra, no —ver `descarga.py`—.

**Ponerlo a mano es dejar el ZIP, no el binario** (`a_mano()`). Un binario suelto
no se puede comprobar contra nada —rclone publica las sumas de sus zips—, así que
para otra plataforma no se aceptaba y el consejo de «copia un rclone a mano» no
servía (#49). El zip oficial, con su nombre exacto y junto a su SHA256SUMS, se
comprueba exactamente igual que una descarga, y sin red.

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
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from common import pins
from common.model import arch_dir, machine_arch
from common.pins import Plataforma

from . import APP_NAME, IS_WIN, RCLONE_BASE_URL, InstallError, bundle_dir
from . import descarga
from .runtime_bin import file_sha256     # el mismo resumen a trozos, una copia

DOWNLOAD_TIMEOUT = 60          # segundos por lectura, no en total
Progreso = Callable[[str], None]


def exe_name() -> str:
    return "rclone.exe" if os.name == "nt" else "rclone"


def os_arch(plat: Plataforma | None = None) -> tuple[str, str]:
    """(so, arquitectura) con los nombres que usa rclone en sus zips.

    Con `plat` son los de esa plataforma. Sin él, los de ESTE equipo, y ahí la
    arquitectura sale de `machine_arch()`, no de `platform.machine()`, por lo
    mismo que `bin_subdir()` se la pregunta al modelo: el instalador es un .exe
    x64 y en un Windows ARM se creería en un equipo x64, así que descargaba el
    rclone de amd64 para dejarlo en el `bin/arm` que mira el dispositivo."""
    if plat is not None:
        return plat.so, plat.rclone_arch
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


def cache_dir(plat: Plataforma | None = None) -> Path:
    """La caché de descargas: una carpeta por VERSIÓN fijada y arquitectura.

    Por arquitectura, porque si no la caché deshace el arreglo del ARM: un
    instalador que se creyó x64 en un equipo ARM dejaba ahí un rclone de amd64, y
    al volver a instalar `find_rclone()` lo encuentra antes de plantearse
    descargar, así que el `download_url()` correcto no llegaba a usarse nunca.

    Y por versión desde que el dispositivo puede actualizar sus componentes, por
    exactamente el mismo motivo una capa más arriba: mover `pins.RCLONE_VERSION`
    no serviría de nada mientras el equipo tuviera cacheado el binario de antes,
    que es el primero que se encuentra. Con la versión en la ruta, una caché de
    otra versión simplemente no existe para este código.

    El nombre del FICHERO no lleva la versión a propósito: es el mismo que va a
    tener en `bin/` del dispositivo. Windows y Linux de la misma CPU comparten
    carpeta sin pisarse, uno es `rclone.exe` y el otro `rclone`."""
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    d = (Path(base) / f"{APP_NAME}-install" / "rclone" / pins.RCLONE_VERSION
         / (plat.bin_dir if plat else bin_subdir()))
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


def _suma_apuntada(binario: Path) -> Path:
    return binario.with_name(binario.name + ".sha256")


def cached(plat: Plataforma | None = None) -> Path | None:
    """El binario de la caché, si está y sigue siendo el que se comprobó.

    Se vuelve a resumir en cada uso, igual que `runtime_bin.cached()`: la
    carpeta ya garantiza la VERSIÓN, lo que queda por garantizar son los bytes.
    Cuesta una fracción de segundo y a cambio una caché truncada o estropeada no
    llega nunca a un dispositivo, donde se va a ejecutar en cada equipo."""
    binario = cache_dir(plat) / (plat.rclone_exe if plat else exe_name())
    try:
        if not binario.is_file():
            return None
        apuntada = _suma_apuntada(binario).read_text(encoding="ascii").strip()
        if apuntada and file_sha256(binario) == apuntada:
            return binario
    except OSError:
        pass
    return None


def pinned_version(ruta: Path | str, plat: Plataforma | None = None) -> str:
    """La versión de ese binario si se puede AFIRMAR, o '' si no se sabe.

    Solo se puede afirmar de lo que salió de la caché, porque la caché va por
    versión. De un rclone encontrado en el PATH, dejado a mano junto al
    instalador o heredado de un checkout no se sabe nada, y el sello del
    dispositivo tiene que decir «no consta» en vez de mentir: un sello viejo al
    lado de un binario nuevo es peor que ningún sello. Ejecutarlo para
    preguntárselo tampoco vale — el de otra plataforma no arranca aquí.

    Y estar DENTRO de la carpeta de la caché no basta: `candidates()` añade ahí
    un binario sin comprobar a propósito —es lo que mantiene vivo el reaprovechar
    sin red de `ensure_rclone()`—, y es la misma carpeta donde `a_mano()` pide
    dejar el zip. Así que se exige `cached()`: solo lo que se ha vuelto a
    resumir y cuadra con su `.sha256` es lo que este sello puede afirmar —lo que
    salió de una descarga o de un zip dejado a mano, comprobados igual—."""
    en_cache = cached(plat)
    try:
        return (pins.RCLONE_VERSION
                if en_cache is not None
                and Path(ruta).resolve() == en_cache.resolve() else "")
    except OSError:
        return ""


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


def zip_name(version: str, plat: Plataforma | None = None) -> str:
    sysname, arch = os_arch(plat)
    return f"rclone-{version}-{sysname}-{arch}.zip"


def download_url(version: str, plat: Plataforma | None = None) -> str:
    """La URL del zip de ESA versión, nunca el alias `rclone-current-…`.

    El alias apunta a lo último que haya publicado rclone en el momento de
    pedirlo, y eso no se puede comprobar: la suma que tenemos en la mano es la
    de la versión fijada, y el alias puede ser ya otra. Fallaría la comprobación
    sin que nada vaya mal, que es la peor manera de fallar. Con la URL
    versionada las dos mitades hablan de lo mismo por construcción."""
    return f"{RCLONE_BASE_URL}/{version}/{zip_name(version, plat)}"


def sums_url(version: str) -> str:
    """El SHA256SUMS de ESA versión, junto a sus zips."""
    return f"{RCLONE_BASE_URL}/{version}/{descarga.SUMAS}"


def _nombre(plat: Plataforma | None) -> str:
    return plat.nombre if plat is not None else "este equipo"


def zip_a_mano(plat: Plataforma | None = None) -> Path:
    """Dónde tiene que estar el zip oficial para que cuente como puesto a mano.

    En la carpeta de la caché de esa plataforma y con su nombre EXACTO, el que
    lleva la versión, el sistema y la CPU: Windows ARM64 y Linux ARM64 comparten
    la carpeta `arm/`, y lo que las distingue es justo ese nombre. Uno de otra
    versión no se mira nunca, igual que la caché de otra versión."""
    return cache_dir(plat) / zip_name(pins.RCLONE_VERSION, plat)


def a_mano(plat: Plataforma | None = None) -> str:
    """Cómo ponerlo a mano cuando la descarga no sale. Con los nombres exactos.

    El zip y su SHA256SUMS, no el binario: es lo que se puede comprobar, y con
    el SHA256SUMS al lado se comprueba sin red (`descarga.sumas()`). Pedir «un
    rclone» a secas era dejar que se copiara el `rclone.exe` del equipo en la
    carpeta de Linux ARM64, que además es la misma que la de Windows ARM64."""
    version = pins.RCLONE_VERSION
    zip_ = zip_a_mano(plat)
    return (f"Para ponerlo a mano, baja con el navegador estos dos ficheros:\n"
            f"    {download_url(version, plat)}\n"
            f"    {sums_url(version)}\n"
            f"y déjalos, sin descomprimir y con esos nombres exactos "
            f"({zip_.name} y {descarga.SUMAS}), en:\n"
            f"    {zip_.parent}\n"
            f"Al volver a intentarlo se comprueban igual que una descarga, y no "
            f"hace falta red.")


def published_sha256(version: str, nombre_zip: str,
                     plat: Plataforma | None = None,
                     progreso: Progreso | None = None) -> str:
    """El SHA-256 que rclone publica para ese zip, sacado de su SHA256SUMS.

    El SHA256SUMS sale del que haya dejado alguien a mano en la caché de `plat`
    o, si no hay, de la red con reintentos (`descarga.sumas()`)."""
    url = sums_url(version)
    try:
        texto, origen = descarga.sumas(url, cache_dir(plat) / descarga.SUMAS,
                                       lambda: fetch(url, 30), progreso)
    except descarga.FALLOS_DE_RED as e:
        raise InstallError(
            f"No he podido leer {url} para comprobar rclone de {_nombre(plat)}: "
            f"{descarga.describir(e)}\n\n{a_mano(plat)}") from e
    suma = descarga.suma_en(texto, nombre_zip)
    if suma is not None:
        return suma
    if origen != url:
        raise InstallError(
            f"{origen} no trae ninguna suma para {nombre_zip}, así que no puedo "
            f"comprobarlo. ¿Es el SHA256SUMS de la {version}? El que vale es "
            f"el de {url}.")
    raise InstallError(
        f"{url} no trae ninguna suma para {nombre_zip}, así que no puedo "
        f"comprobar lo que descargue.\n\n¿Ha cambiado rclone cómo publica sus "
        f"versiones? La versión fijada está en common/pins.py.")


def _extraer(datos: bytes, origen: str, plat: Plataforma | None,
             decir: Progreso) -> Path:
    """Saca el binario de un zip YA comprobado y lo deja en la caché, con su suma.

    Lo comparten la descarga y el zip dejado a mano: los dos llegan aquí solo
    después de que su SHA-256 haya cuadrado con el publicado, y a partir de aquí
    ya se puede tocar el disco."""
    exe = plat.rclone_exe if plat else exe_name()
    # Se escribe a un `.part` y se renombra, por lo mismo que
    # `runtime_bin.download_runtime()`: una extracción cortada no puede quedarse
    # con el nombre bueno y parecer una caché completa.
    destino = cache_dir(plat) / exe
    parcial = destino.with_name(destino.name + ".part")
    renombrado = False       # como `apartado` en `deploy.install_runtime()`:
                             # marca desde dónde el fallo ya no es sobre `.part`
    try:
        with zipfile.ZipFile(io.BytesIO(datos)) as zf:
            # El zip trae una carpeta con versión dentro; el binario es el único
            # miembro que se llama así, pero si rclone cambia el empaquetado hay
            # que decirlo, no reventar con un StopIteration sin contexto.
            miembros = [m for m in zf.namelist() if m.rsplit("/", 1)[-1] == exe]
            if not miembros:
                raise InstallError(
                    f"El zip de rclone no contiene ningún {exe}. "
                    f"¿Ha cambiado el empaquetado en {origen}?")
            with zf.open(miembros[0]) as src, open(parcial, "wb") as dst:
                shutil.copyfileobj(src, dst)
        os.replace(parcial, destino)
        renombrado = True
        # La suma del ZIP, que es la que publica rclone y la que se acaba de
        # comprobar. Lo que se apunta al lado es para volver a mirar el binario
        # extraído, así que se resume ÉL, no el zip que ya no existe.
        _suma_apuntada(destino).write_text(file_sha256(destino) + "\n",
                                           encoding="ascii")
    except zipfile.BadZipFile as e:
        parcial.unlink(missing_ok=True)
        raise InstallError(f"El fichero de {origen} no es un zip válido: {e}") from e
    except OSError as e:
        # Antes del `os.replace` lo único a medias es `.part`; si ya había un
        # `destino` de una descarga buena anterior, es ajeno a este intento y no
        # se toca. Después del `os.replace` es al revés: ya no hay `.part`, pero
        # `destino` es el binario que se acaba de dejar aquí y puede haberse
        # quedado sin su `.sha256` (o con el de uno anterior en esa misma ruta)
        # —invisible para `cached()`, así que dejarlo ahí no cachea nada, solo
        # desmentiría el «no he podido guardar» de abajo.
        parcial.unlink(missing_ok=True)
        if renombrado:
            destino.unlink(missing_ok=True)
            _suma_apuntada(destino).unlink(missing_ok=True)
        raise InstallError(f"No he podido guardar {destino}: {e}") from e

    if not IS_WIN:
        destino.chmod(destino.stat().st_mode | stat.S_IXUSR | stat.S_IRUSR)
    decir(f"rclone listo: {destino}")
    return destino


def _decir(progreso: Progreso | None) -> Progreso:
    return progreso if progreso is not None else (lambda msg: None)


def download_rclone(progreso: Progreso | None = None,
                    plat: Plataforma | None = None) -> Path:
    """Baja el zip portable, COMPRUEBA su SHA-256, y deja el binario en la caché.

    Es el de la versión fijada en `common/pins.py`, para `plat` o, sin ella, para
    este equipo.

    Lo que se descarga aquí se va a ejecutar y va a acabar copiado dentro del
    dispositivo, así que se compara con la suma que rclone publica antes de
    escribir nada. Conviene ser honesto sobre hasta dónde llega eso: la suma
    viaja por el mismo TLS y desde el mismo servidor que el zip, así que **no**
    protege de que rclone.org esté comprometido —quien pudiera cambiar uno
    podría cambiar la otra—. Lo que sí ataja es todo lo demás: una descarga
    truncada, un proxy de empresa que devuelve otra cosa o una página de error,
    una caché que sirve un artefacto viejo, y el alias `current` moviéndose bajo
    los pies. Y sobre todo convierte «se ejecuta lo que haya llegado» en «se
    ejecuta lo que rclone dice que publicó».

    Un corte o un tiempo de espera se reintentan (`descarga.con_reintentos()`):
    el #49 era un solo «The read operation timed out» leyendo el zip de Linux
    ARM64, y tumbaba la instalación entera. Una suma que no cuadra NO se
    reintenta, y `descarga.py` dice por qué."""
    decir = _decir(progreso)
    version = pins.RCLONE_VERSION
    nombre = zip_name(version, plat)
    url = download_url(version, plat)

    decir(f"rclone {version} ({nombre}): leyendo su SHA256SUMS")
    esperado = published_sha256(version, nombre, plat, progreso)

    decir(f"Descargando {url}")
    try:
        datos = descarga.con_reintentos(lambda: fetch(url), f"Descargar {nombre}",
                                        progreso)
    except descarga.FALLOS_DE_RED as e:
        raise InstallError(
            f"No he podido descargar rclone para {_nombre(plat)} de {url}: "
            f"{descarga.describir(e)}\n\n{a_mano(plat)}") from e

    obtenido = hashlib.sha256(datos).hexdigest()
    if obtenido != esperado:
        # Ni se guarda ni se descomprime: no hay ningún motivo bueno para que
        # esto pase, y seguir sería ejecutar algo que no se sabe qué es.
        raise InstallError(
            f"Lo descargado de {url} no es lo que rclone publica.\n\n"
            f"  esperado: {esperado}\n"
            f"  obtenido: {obtenido}\n\n"
            f"No se ha guardado nada. Vuelve a intentarlo; si sigue pasando, algo "
            f"entre este equipo y rclone.org cambia lo que llega (un proxy, un "
            f"portal de acceso).\n\n{a_mano(plat)}")
    decir(f"SHA-256 correcto: {obtenido}")
    return _extraer(datos, url, plat, decir)


def adoptar_zip(plat: Plataforma | None = None,
                progreso: Progreso | None = None) -> Path | None:
    """El binario del zip oficial dejado a mano en la caché, ya comprobado.

    None si no hay zip en `zip_a_mano(plat)`. Si lo hay, se comprueba contra el
    SHA256SUMS exactamente como una descarga —el de al lado si se dejó, si no el
    de la red— y solo entonces se extrae, con su `.sha256`: desde ahí es una
    caché como cualquier otra, y `pinned_version()` la puede sellar.

    Si no cuadra se dice y NO se sigue descargando por detrás: alguien lo ha
    puesto ahí a propósito, y sustituirlo en silencio sería no enterarse de que
    lo que tiene en la mano no es rclone. El zip no se borra nunca: es suyo."""
    ruta = zip_a_mano(plat)
    try:
        if not ruta.is_file():
            return None
        datos = ruta.read_bytes()
    except OSError:
        return None
    decir = _decir(progreso)
    version = pins.RCLONE_VERSION
    decir(f"rclone {version}: comprobando el zip dejado a mano en {ruta}")
    esperado = published_sha256(version, ruta.name, plat, progreso)
    obtenido = hashlib.sha256(datos).hexdigest()
    if obtenido != esperado:
        raise InstallError(
            f"{ruta} no es el zip que rclone publica para {_nombre(plat)}.\n\n"
            f"  esperado: {esperado}\n"
            f"  obtenido: {obtenido}\n\n"
            f"No lo he usado. ¿Se cortó la descarga del navegador? Bórralo y "
            f"vuelve a bajarlo de {download_url(version, plat)}; o bórralo sin "
            f"más y el instalador lo descargará.")
    decir(f"SHA-256 correcto: {obtenido}")
    return _extraer(datos, str(ruta), plat, decir)


def _comprobado(plat: Plataforma | None, progreso: Progreso | None) -> Path | None:
    """Lo que hay en la caché y se puede afirmar: el binario comprobado, o el
    del zip oficial dejado a mano. None si no hay ninguno de los dos."""
    en_cache = cached(plat)
    if en_cache is not None:
        return en_cache
    return adoptar_zip(plat, progreso)


def _es_este_equipo(plat: Plataforma) -> bool:
    """¿Es `plat` la plataforma de este equipo? Con la misma respuesta que usa
    el dispositivo para su `bin/`, no con `platform.machine()`.

    «No es Windows» no significa «es Linux»: el rclone de un Mac copiado como
    el de Linux sería un binario que no arranca en ningún sitio."""
    so = "windows" if IS_WIN else ("linux" if sys.platform.startswith("linux")
                                   else sys.platform)
    return plat.so == so and plat.bin_dir == bin_subdir()


def rclone_for(plat: Plataforma, progreso: Progreso | None = None,
               allow_download: bool = True) -> Path:
    """El rclone que se copiará al dispositivo para esa plataforma.

    La de este equipo sigue la cadena de siempre (`find_rclone()`): así se puede
    aprovisionar sin red con un rclone puesto a mano, como antes. Las demás no
    tienen nada que buscar en este equipo: caché, zip oficial dejado a mano
    (`adoptar_zip()`) o descarga.

    El zip a mano cuenta aunque no se permita descargar: es un fichero de este
    equipo. Lo único que puede ir a la red es su SHA256SUMS, unos KB, y ni eso
    si se dejó al lado."""
    if _es_este_equipo(plat):
        encontrado = find_rclone()
        if encontrado:
            return encontrado
    comprobado = _comprobado(plat, progreso)
    if comprobado is not None:
        return comprobado
    if not allow_download:
        raise InstallError(
            f"No hay rclone para {plat.nombre} en la caché y no se ha permitido "
            f"descargarlo.")
    return download_rclone(progreso, plat)


def pinned_rclone(plat: Plataforma, progreso: Progreso | None = None) -> Path:
    """El rclone de la versión FIJADA para esa plataforma: caché o descarga.

    No es `rclone_for()`, y la diferencia es justo la que importa. Aquel acepta
    «cualquier rclone que haya por este equipo» —el del checkout, el del PATH—,
    que es lo que permite aprovisionar sin red con uno puesto a mano. Esto
    SUSTITUYE el binario que el dispositivo ya lleva, y cambiarlo por uno de
    versión desconocida sería ir hacia atrás sin enterarse. El zip oficial
    dejado a mano sí vale: se comprueba contra la suma de la versión fijada."""
    comprobado = _comprobado(plat, progreso)
    if comprobado is not None:
        return comprobado
    return download_rclone(progreso, plat)


def ensure_rclone(progreso: Progreso | None = None,
                  allow_download: bool = True) -> Path:
    """El rclone que se va a usar. Descarga solo si hace falta y se le permite."""
    encontrado = find_rclone() or adoptar_zip(None, progreso)
    if encontrado:
        return encontrado
    if not allow_download:
        raise InstallError(
            "No hay rclone en este equipo y no se ha permitido descargarlo.")
    return download_rclone(progreso)
