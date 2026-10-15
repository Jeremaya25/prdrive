#!/usr/bin/env python3
"""Conseguir el KeePassXC oficial, comprobado, y dejarlo en la unidad.

Es el hermano de `veracrypt_bin.py`, con el mismo contrato: lo que se descarga
se COMPRUEBA antes de escribir nada y, si no cuadra, no se guarda nada. Es el
programa del llavero, y viaja en `.prdrive/keepassxc/<paquete>/`
(`components.keepassxc_dir()`).

Qué se baja: el paquete oficial de KeePassXC (el ZIP de Windows, el AppImage
de Linux), de la versión y con el SHA-256 fijados en `common/pins.py`
(`KEEPASSXC`). Ningún `.DIGEST` se lee aquí: el número lo escribió quien movió
la versión tras comprobar la firma PGP, y la comprobación es contra ESE número.
Ataja una descarga truncada, un proxy que devuelve otra cosa o una caché vieja.
Un corte de red se reintenta (`descarga.con_reintentos()`) y un paquete que no
cuadra no. Se guarda tal cual en la caché del usuario, una carpeta por versión;
el bajado a mano y dejado ahí con su nombre se comprueba igual (`ensure_zip()`).

Qué se escribe en la unidad:
- El ZIP entero, sin su carpeta de arriba (`KeePassXC-2.7.12-Win64/`), que ya
  trae `.portable` (H-3). Cada ruta se valida ANTES de escribir la primera
  (`components.ruta_relativa_segura()`: nada de `..`, `\\`, unidad ni ruta
  absoluta), con la defensa de `update._ruta_segura()` y por la misma razón:
  `extractall` es la trampa.
- El AppImage, un solo fichero, con el nombre fijo
  `components.KEEPASSXC_APPIMAGE`. No se extrae aquí: se extrae en cada equipo
  Linux que lo abre (`common/keepassxc.py`).

Cada fichero se vuelve a leer de la unidad y a resumir: una unidad que escribe
mal no deja un KeePassXC a medias con un sello que diga que está bien.

El sello dice de dónde salió el paquete, no que sus ficheros sigan siendo esos:
`al_dia()` mira además que cada ejecutable que fija `pins.KEEPASSXC_EJECUTABLES`
tenga su suma, y `instalar()` repone el paquete si uno no cuadra. Resumir 11 MB
es cosa del instalador y del aplicador, en segundo plano; la ventana, al
pintarse, solo lee lo que apuntó `keepassxc.comprobar()` en `state/`
(`components.keepassxc_pendiente()`), y `instalar()` lo olvida al reponer.

El cambio es el de `traveler.sustituir()`: se mira antes el sitio libre, se
extrae en `.<paquete>.nuevo-<pid>`, se escribe el sello el ÚLTIMO, se aparta el
de antes como `.<paquete>.viejo-<pid>` y se coloca el nuevo de un renombrado.
Quien lo pide mira antes que nada corra desde la carpeta (`procesos_desde()`):
un KeePassXC abierto, o el proxy que lanza el navegador.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from common import components, pins

from . import APP_NAME, InstallError, descarga, traveler

DOWNLOAD_TIMEOUT = 60  # segundos por lectura, no en total
USER_AGENT = f"{APP_NAME}-install"
"""`User-Agent` de las peticiones de descarga."""
Progreso = Callable[[str], None]
"""Función que recibe cada mensaje de avance."""
SELLO = components.KEEPASSXC_STAMP
"""Nombre del sello de la carpeta de KeePassXC."""
HOLGURA = 4 * 1024 ** 2
"""Bytes de más que se piden libres al extraer, por encima de lo que ocupa el ZIP."""
PAQUETE = "windows-x64"
"""El paquete que se pone si no se pide otro: el de Windows, el primero que hubo."""


class SinRed(InstallError):
    """No se ha podido BAJAR el paquete (sin red, un proxy, un tiempo de espera).

    Es distinto de que lo bajado no cuadre: aquello se puede arreglar dejando
    el paquete a mano en la caché; uno que no es el fijado no se esconde
    detrás de otra cosa.
    """


def paquete(clave: str = PAQUETE) -> tuple[str, str]:
    """Devuelve el nombre y el SHA-256 fijados del paquete oficial de esa clave.

    Raises:
        KeyError: Si no hay ese paquete.
    """
    return pins.KEEPASSXC[clave]


def es_appimage(clave: str = PAQUETE) -> bool:
    """Indica si el paquete de esa clave es un AppImage (Linux) y no un ZIP."""
    return paquete(clave)[0].endswith(".AppImage")


def _que(clave: str) -> str:
    """Devuelve cómo se llama el paquete en lo que se dice: «el AppImage» o «el ZIP»."""
    return "el AppImage" if es_appimage(clave) else "el ZIP"


def url(clave: str = PAQUETE) -> str:
    """Devuelve la URL versionada del paquete de esa clave."""
    return pins.KEEPASSXC_URL.format(version=pins.KEEPASSXC_VERSION,
                                     nombre=paquete(clave)[0])


def cache_dir() -> Path:
    """Devuelve la caché: una carpeta por VERSIÓN, como `veracrypt_bin.cache_dir()`."""
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    d = Path(base) / f"{APP_NAME}-install" / "keepassxc" / pins.KEEPASSXC_VERSION
    d.mkdir(parents=True, exist_ok=True)
    return d


def zip_en_cache(clave: str = PAQUETE) -> Path:
    """Devuelve dónde está (o estará) el paquete en la caché, con su nombre exacto.

    Es también donde dejarlo a mano si la descarga no sale.
    """
    return cache_dir() / paquete(clave)[0]


def fetch(direccion: str, timeout: float = DOWNLOAD_TIMEOUT) -> bytes:
    """Descarga una URL; es la única puerta de salida a la red de este módulo.

    Es de módulo a propósito, como `veracrypt_bin.fetch()`: los tests la
    sustituyen entera y ninguno habla con GitHub. Devuelve bytes porque lo que
    baja hay que resumirlo entero antes de escribir nada.
    """
    peticion = urllib.request.Request(direccion, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(peticion, timeout=timeout) as resp:
        return resp.read()


def a_mano(clave: str = PAQUETE) -> str:
    """Devuelve cómo poner el paquete a mano cuando la descarga no sale."""
    nombre, sha = paquete(clave)
    return (f"Sin conexión, baja a mano {_que(clave)} oficial de KeePassXC:\n  {url(clave)}\n"
            f"con el SHA-256\n  {sha}\ny déjalo, con ese nombre ({nombre}), en:\n"
            f"  {cache_dir()}\nAl volver a intentarlo se comprueba igual que una "
            f"descarga.")


def _resumen(ruta: Path) -> str:
    """Devuelve el SHA-256 de un fichero, leyéndolo a trozos."""
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for trozo in iter(lambda: f.read(1024 * 1024), b""):
            h.update(trozo)
    return h.hexdigest()


def _no_es_el_fijado(origen: str, esperado: str, obtenido: str) -> InstallError:
    """Devuelve el error de un paquete que no es el fijado."""
    return InstallError(
        f"{origen} no es el KeePassXC fijado.\n\n  esperado: {esperado}\n"
        f"  obtenido: {obtenido}\n\nNo se ha escrito nada.")


def ensure_zip(clave: str = PAQUETE, progreso: Progreso | None = None,
               allow_download: bool = True) -> Path:
    """Devuelve el paquete fijado de esa clave en la caché, comprobado (el ZIP o el AppImage).

    Lo que hay en la caché (bajado antes, o dejado a mano) se vuelve a resumir
    en cada uso. Uno que no cuadra se dice y NO se descarga encima: alguien lo
    dejó ahí, y no es el que se quería.

    Raises:
        SinRed: Si no está en la caché y no se puede descargar.
        InstallError: Si lo que hay o lo que baja no es el fijado; la caché
            queda como estaba.
    """
    def decir(msg: str) -> None:
        """Pasa un mensaje a `progreso`, si lo hay."""
        if progreso:
            progreso(msg)

    nombre, esperado = paquete(clave)
    ruta = zip_en_cache(clave)
    if ruta.is_file():
        obtenido = _resumen(ruta)
        if obtenido != esperado:
            raise InstallError(
                f"{ruta} no es el KeePassXC fijado.\n\n  esperado: {esperado}\n"
                f"  obtenido: {obtenido}\n\nBórralo y vuelve a intentarlo: se "
                f"descargará el bueno.")
        decir(f"KeePassXC {pins.KEEPASSXC_VERSION} en la caché, comprobado: {ruta}")
        return ruta
    if not allow_download:
        raise SinRed("No hay KeePassXC en la caché y no se ha permitido descargarlo.")

    direccion = url(clave)
    decir(f"Descargando KeePassXC {pins.KEEPASSXC_VERSION}: {direccion}")
    try:
        datos = descarga.con_reintentos(lambda: fetch(direccion), f"Descargar {nombre}",
                                        progreso)
    except descarga.FALLOS_DE_RED as e:
        raise SinRed(f"No he podido descargar KeePassXC de {direccion}: "
                     f"{descarga.describir(e)}\n\n{a_mano(clave)}") from e
    obtenido = hashlib.sha256(datos).hexdigest()
    if obtenido != esperado:
        raise _no_es_el_fijado(direccion, esperado, obtenido)
    decir(f"SHA-256 correcto: {obtenido}")
    parcial = ruta.with_name(ruta.name + ".part")
    try:
        parcial.write_bytes(datos)
        os.replace(parcial, ruta)
    except OSError as e:
        parcial.unlink(missing_ok=True)
        raise InstallError(f"No he podido guardar KeePassXC en {ruta}: {e}") from e
    return ruta


def miembros(zf: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, str]]:
    """Devuelve los ficheros del ZIP con su ruta dentro de la carpeta del paquete.

    El ZIP oficial lo mete todo en una carpeta (`KeePassXC-2.7.12-Win64/`), que
    se quita. Se valida TODO antes de escribir nada.

    Raises:
        InstallError: Si no hay una sola carpeta de arriba, si una ruta se sale
            de ella, si no trae `KeePassXC.exe` o si trae algo con el nombre
            del sello.
    """
    infos = [i for i in zf.infolist() if not i.is_dir()]
    arriba = {i.filename.split("/", 1)[0] for i in infos}
    if len(arriba) != 1 or any("/" not in i.filename for i in infos):
        raise InstallError("El ZIP de KeePassXC no trae una sola carpeta con el "
                           "programa. ¿Ha cambiado el empaquetado? No se ha escrito nada.")
    salida = []
    for info in infos:
        rel = info.filename.split("/", 1)[1]
        if not components.ruta_relativa_segura(rel):
            raise InstallError(f"El ZIP de KeePassXC trae un fichero que se sale de "
                               f"su carpeta: {info.filename!r}. No se ha escrito nada.")
        if rel == SELLO:
            raise InstallError(f"El ZIP de KeePassXC trae un {SELLO}, que no es suyo. "
                               f"No se ha escrito nada.")
        salida.append((info, rel))
    if components.KEEPASSXC_EXE not in {rel for _, rel in salida}:
        raise InstallError(f"El ZIP de KeePassXC no trae {components.KEEPASSXC_EXE}. "
                           f"¿Ha cambiado el empaquetado? No se ha escrito nada.")
    return salida


def _sello_al_dia(app_dir: Path | str, clave: str) -> bool:
    """Indica si el sello dice que la unidad lleva la versión fijada, del paquete fijado."""
    return (components.keepassxc_version(app_dir, clave) == pins.KEEPASSXC_VERSION
            and components.keepassxc_sello(app_dir, clave).get("sha256")
            == paquete(clave)[1])


def _fijados(clave: str) -> dict[str, str]:
    """Devuelve `{fichero: sha256}` de los ejecutables que `pins` fija de ese paquete.

    Vacío si esta versión de prdrive no fija ninguno: nada que dar por bueno.
    """
    return pins.KEEPASSXC_EJECUTABLES.get(pins.KEEPASSXC_VERSION, {}).get(clave, {})


def ficheros_que_no_cuadran(app_dir: Path | str, clave: str = PAQUETE) -> list[str]:
    """Devuelve cuáles de los ejecutables fijados de ese paquete no son los de la tabla.

    Un fichero que falta o que no se puede leer cuenta como que no cuadra. Lee
    cada uno entero (11 MB en Windows, 47 en Linux): lo hace el instalador y el
    aplicador, en segundo plano, nunca la ventana al pintarse (`components`).
    No mira las DLL ni el resto del paquete: es lo que se aceptó al dejar la
    carpeta fuera de la huella del agente (`pins.KEEPASSXC_EJECUTABLES`).
    """
    carpeta = components.keepassxc_dir(app_dir, clave)
    malos = []
    for nombre, suma in _fijados(clave).items():
        try:
            cuadra = _resumen(carpeta / nombre) == suma
        except OSError:
            cuadra = False
        if not cuadra:
            malos.append(nombre)
    return malos


def al_dia(app_dir: Path | str, clave: str = PAQUETE) -> bool:
    """Indica si la unidad lleva ya ese KeePassXC: el fijado, y con sus ejecutables intactos.

    El sello dice de dónde salió el paquete, no que sus ficheros sigan siendo
    esos, así que además cada ejecutable que fija `pins.KEEPASSXC_EJECUTABLES`
    ha de tener su suma. Si esta versión de prdrive no fija ninguno del paquete
    no hay con qué comprobarlo y no se da por al día: `keepassxc.comprobar()`
    tampoco lo dejaría lanzar.
    """
    return (_sello_al_dia(app_dir, clave) and bool(_fijados(clave))
            and not ficheros_que_no_cuadran(app_dir, clave))


def _mb(n: int) -> str:
    """Devuelve esos bytes en MiB, sin decimales."""
    return f"{n / 1024 ** 2:.0f}"


def instalar(app_dir: Path | str, clave: str = PAQUETE,
             progreso: Progreso | None = None) -> list[str]:
    """Deja en `app_dir/keepassxc/<clave>/` el KeePassXC fijado, con su sello.

    No mira si está en uso: eso lo hace quien lo pide (ver el docstring del
    módulo). Si ya está el bueno, con sus ejecutables intactos (`al_dia()`), no
    toca nada; con el sello al día y un ejecutable que no cuadra, lo vuelve a
    poner. Lo que `keepassxc.comprobar()` apuntó de ese paquete en `state/` se
    olvida al reponerlo y al ver que sus ficheros ya cuadraban.

    Returns:
        Lo hecho, una línea por paso; vacío si ya estaba.

    Raises:
        SinRed: Si no hay paquete y no se puede descargar.
        InstallError: Si no cuadra, no cabe o no se puede escribir; lo que
            había queda como estaba.
    """
    def decir(msg: str) -> None:
        """Pasa un mensaje a `progreso`, si lo hay."""
        if progreso:
            progreso(msg)

    if al_dia(app_dir, clave):
        components.keepassxc_olvidar_alterado(app_dir, clave)
        decir(f"KeePassXC {pins.KEEPASSXC_VERSION} ya está en la unidad.")
        return []
    malos = ficheros_que_no_cuadran(app_dir, clave) if _sello_al_dia(app_dir, clave) else []
    if malos:
        decir(f"KeePassXC {pins.KEEPASSXC_VERSION}: no cuadra con el oficial "
              f"{', '.join(malos)}; se vuelve a poner el paquete.")
    nombre, sha_zip = paquete(clave)
    archivo = ensure_zip(clave, progreso)
    carpeta = components.keepassxc_dir(app_dir, clave)
    base = carpeta.parent
    zf: zipfile.ZipFile | None = None
    if es_appimage(clave):
        lista: list[tuple[zipfile.ZipInfo, str]] = []
        try:
            total = archivo.stat().st_size
        except OSError as e:
            raise InstallError(f"No he podido leer {archivo}: {e}") from e
    else:
        try:
            zf = zipfile.ZipFile(archivo)
        except (OSError, zipfile.BadZipFile) as e:
            raise InstallError(f"No he podido abrir {archivo}: {e}") from e
    with zf if zf is not None else contextlib.nullcontext():
        if zf is not None:
            lista = miembros(zf)
            total = sum(info.file_size for info, _ in lista)
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise InstallError(f"No he podido crear {base}: {e}") from e
        libre = traveler.espacio_libre(base)
        if libre is not None and libre < total + HOLGURA:
            raise InstallError(
                f"No cabe KeePassXC en la unidad: hacen falta unos "
                f"{_mb(total + HOLGURA)} MB y quedan {_mb(libre)} MB libres. No se ha "
                f"tocado nada.")
        _barrer(base, clave)
        nuevo = base / f".{clave}.nuevo-{os.getpid()}"
        viejo = base / f".{clave}.viejo-{os.getpid()}"
        decir(f"{'Extrayendo' if zf is not None else 'Copiando'} KeePassXC "
              f"{pins.KEEPASSXC_VERSION} en {carpeta}")
        try:
            resumenes = (_extraer(zf, lista, nuevo) if zf is not None
                         else _copiar_appimage(archivo, sha_zip, nuevo))
            (nuevo / SELLO).write_text(
                components.keepassxc_stamp_text(pins.KEEPASSXC_VERSION, nombre, sha_zip,
                                                resumenes),
                encoding="utf-8", newline="\n")
        except (OSError, InstallError, zipfile.BadZipFile) as e:
            shutil.rmtree(nuevo, ignore_errors=True)
            if isinstance(e, InstallError):
                raise
            raise InstallError(f"No he podido extraer KeePassXC en {base}: {e}\n"
                               f"El que había sigue como estaba.") from e

    apartado = False
    if carpeta.exists():
        try:
            os.replace(carpeta, viejo)
            apartado = True
        except OSError as e:
            shutil.rmtree(nuevo, ignore_errors=True)
            raise InstallError(f"No he podido apartar {carpeta}: {e}\n\n¿Está KeePassXC "
                               f"abierto desde la unidad, o el navegador conectado a "
                               f"él? El que había sigue en su sitio.") from e
    try:
        os.replace(nuevo, carpeta)
    except OSError as e:
        if apartado:
            try:
                os.replace(viejo, carpeta)
            except OSError as otro:
                raise InstallError(
                    f"No he podido colocar KeePassXC en {carpeta} ({e}) ni devolver a "
                    f"su sitio el que había ({otro}): está en {viejo}.") from otro
        shutil.rmtree(nuevo, ignore_errors=True)
        raise InstallError(f"No he podido colocar KeePassXC en {carpeta}: {e}\n"
                           f"El que había sigue en su sitio.") from e
    if apartado:
        shutil.rmtree(viejo, ignore_errors=True)    # si no se deja, la próxima vez
    components.keepassxc_olvidar_alterado(app_dir, clave)
    decir(f"KeePassXC {pins.KEEPASSXC_VERSION} listo en {carpeta}")
    return [f"KeePassXC {pins.KEEPASSXC_VERSION} en {carpeta}"]


def _extraer(zf: zipfile.ZipFile, lista: list[tuple[zipfile.ZipInfo, str]],
             destino: Path) -> dict[str, str]:
    """Extrae la lista ya validada en `destino` y devuelve `{ruta: sha256}`.

    Cada fichero se escribe, se vuelve a leer de la unidad y se compara con lo
    que traía el ZIP (cuyo CRC comprueba `zipfile` al leerlo).

    Raises:
        InstallError: Si lo escrito no es lo que se leyó.
    """
    destino.mkdir(parents=True)
    resumenes: dict[str, str] = {}
    for info, rel in lista:
        final = destino.joinpath(*rel.split("/"))
        final.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        with zf.open(info) as origen, open(final, "wb") as salida:
            for trozo in iter(lambda: origen.read(1024 * 1024), b""):
                h.update(trozo)
                salida.write(trozo)
        if _resumen(final) != h.hexdigest():
            raise InstallError(f"La copia de {rel} en la unidad no es igual que la del "
                               f"ZIP. ¿Falla la unidad? No se ha tocado el KeePassXC "
                               f"que había.")
        resumenes[rel] = h.hexdigest()
    return resumenes


def _copiar_appimage(archivo: Path, esperado: str, destino: Path) -> dict[str, str]:
    """Copia el AppImage en `destino` con su nombre fijo y devuelve `{nombre: sha256}`.

    Se vuelve a leer de la unidad y a resumir, como cada fichero del ZIP. El
    bit de ejecución se pone si el sistema de ficheros lo guarda; en exFAT no
    hay, y no hace falta: el AppImage no se ejecuta desde la unidad.

    Raises:
        InstallError: Si lo escrito no es el AppImage fijado.
    """
    destino.mkdir(parents=True)
    final = destino / components.KEEPASSXC_APPIMAGE
    shutil.copyfile(archivo, final)
    resumen = _resumen(final)
    if resumen != esperado:
        raise InstallError(f"La copia del AppImage en la unidad no es igual que la "
                           f"descargada. ¿Falla la unidad? No se ha tocado el KeePassXC "
                           f"que había.")
    try:
        final.chmod(0o755)
    except OSError:
        pass
    return {components.KEEPASSXC_APPIMAGE: resumen}


def _barrer(base: Path, clave: str) -> None:
    """Borra lo que dejó un cambio anterior a medias, a mejor esfuerzo."""
    try:
        restos = [p for p in base.iterdir()
                  if p.name.startswith((f".{clave}.nuevo-", f".{clave}.viejo-"))]
    except OSError:
        return
    for resto in restos:
        shutil.rmtree(resto, ignore_errors=True)
