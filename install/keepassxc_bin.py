#!/usr/bin/env python3
"""Conseguir el KeePassXC oficial, comprobado, y dejarlo en la unidad.

Es el hermano de `veracrypt_bin.py`, con el mismo contrato: lo que se descarga
se COMPRUEBA antes de escribir nada y, si no cuadra, no se guarda nada. Es el
programa del llavero, y viaja en `.prdrive/keepassxc/<paquete>/`
(`components.keepassxc_dir()`).

Qué se baja: el ZIP oficial de KeePassXC, de la versión y con el SHA-256
fijados en `common/pins.py` (`KEEPASSXC`). Ningún `.DIGEST` se lee aquí: el
número lo escribió quien movió la versión tras comprobar la firma PGP, y la
comprobación es contra ESE número. Ataja una descarga truncada, un proxy que
devuelve otra cosa o una caché vieja. Un corte de red se reintenta
(`descarga.con_reintentos()`) y un ZIP que no cuadra no. El ZIP se guarda tal
cual en la caché del usuario, una carpeta por versión; el bajado a mano y
dejado ahí con su nombre se comprueba igual (`ensure_zip()`).

Qué se escribe en la unidad: el ZIP entero, sin su carpeta de arriba
(`KeePassXC-2.7.12-Win64/`), que ya trae `.portable` (H-3). Cada ruta se valida
ANTES de escribir la primera (`components.ruta_relativa_segura()`: nada de
`..`, `\\`, unidad ni ruta absoluta), con la defensa de `update._ruta_segura()`
y por la misma razón: `extractall` es la trampa. Cada fichero se vuelve a leer
de la unidad y a resumir: una unidad que escribe mal no deja un KeePassXC a
medias con un sello que diga que está bien.

El cambio es el de `traveler.sustituir()`: se mira antes el sitio libre, se
extrae en `.<paquete>.nuevo-<pid>`, se escribe el sello el ÚLTIMO, se aparta el
de antes como `.<paquete>.viejo-<pid>` y se coloca el nuevo de un renombrado.
Quien lo pide mira antes que nada corra desde la carpeta (`procesos_desde()`):
un KeePassXC abierto, o el proxy que lanza el navegador.
"""

from __future__ import annotations

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
"""El paquete que se pone si no se pide otro: el único que hay en la fase 1."""


class SinRed(InstallError):
    """No se ha podido BAJAR el ZIP (sin red, un proxy, un tiempo de espera).

    Es distinto de que lo bajado no cuadre: aquello se puede arreglar dejando
    el ZIP a mano en la caché; un ZIP que no es el fijado no se esconde detrás
    de otra cosa.
    """


def paquete(clave: str = PAQUETE) -> tuple[str, str]:
    """Devuelve el nombre y el SHA-256 fijados del ZIP de ese paquete.

    Raises:
        KeyError: Si no hay ese paquete.
    """
    return pins.KEEPASSXC[clave]


def url(clave: str = PAQUETE) -> str:
    """Devuelve la URL versionada del ZIP de ese paquete."""
    return pins.KEEPASSXC_URL.format(version=pins.KEEPASSXC_VERSION,
                                     nombre=paquete(clave)[0])


def cache_dir() -> Path:
    """Devuelve la caché: una carpeta por VERSIÓN, como `veracrypt_bin.cache_dir()`."""
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    d = Path(base) / f"{APP_NAME}-install" / "keepassxc" / pins.KEEPASSXC_VERSION
    d.mkdir(parents=True, exist_ok=True)
    return d


def zip_en_cache(clave: str = PAQUETE) -> Path:
    """Devuelve dónde está (o estará) el ZIP en la caché, con su nombre exacto.

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
    """Devuelve cómo poner el ZIP a mano cuando la descarga no sale."""
    nombre, sha = paquete(clave)
    return (f"Sin conexión, baja a mano el ZIP oficial de KeePassXC:\n  {url(clave)}\n"
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
    """Devuelve el error de un ZIP que no es el fijado."""
    return InstallError(
        f"{origen} no es el KeePassXC fijado.\n\n  esperado: {esperado}\n"
        f"  obtenido: {obtenido}\n\nNo se ha escrito nada.")


def ensure_zip(clave: str = PAQUETE, progreso: Progreso | None = None,
               allow_download: bool = True) -> Path:
    """Devuelve el ZIP fijado de ese paquete en la caché, comprobado.

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


def al_dia(app_dir: Path | str, clave: str = PAQUETE) -> bool:
    """Indica si la unidad lleva ya ese KeePassXC: la versión fijada, del ZIP fijado."""
    return (components.keepassxc_version(app_dir, clave) == pins.KEEPASSXC_VERSION
            and components.keepassxc_sello(app_dir, clave).get("sha256")
            == paquete(clave)[1])


def _mb(n: int) -> str:
    """Devuelve esos bytes en MiB, sin decimales."""
    return f"{n / 1024 ** 2:.0f}"


def instalar(app_dir: Path | str, clave: str = PAQUETE,
             progreso: Progreso | None = None) -> list[str]:
    """Deja en `app_dir/keepassxc/<clave>/` el KeePassXC fijado, con su sello.

    No mira si está en uso: eso lo hace quien lo pide (ver el docstring del
    módulo). Si ya está el bueno no toca nada.

    Returns:
        Lo hecho, una línea por paso; vacío si ya estaba.

    Raises:
        SinRed: Si no hay ZIP y no se puede descargar.
        InstallError: Si no cuadra, no cabe o no se puede escribir; lo que
            había queda como estaba.
    """
    def decir(msg: str) -> None:
        """Pasa un mensaje a `progreso`, si lo hay."""
        if progreso:
            progreso(msg)

    if al_dia(app_dir, clave):
        decir(f"KeePassXC {pins.KEEPASSXC_VERSION} ya está en la unidad.")
        return []
    nombre, sha_zip = paquete(clave)
    archivo = ensure_zip(clave, progreso)
    carpeta = components.keepassxc_dir(app_dir, clave)
    base = carpeta.parent
    try:
        zf = zipfile.ZipFile(archivo)
    except (OSError, zipfile.BadZipFile) as e:
        raise InstallError(f"No he podido abrir {archivo}: {e}") from e
    with zf:
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
        decir(f"Extrayendo KeePassXC {pins.KEEPASSXC_VERSION} en {carpeta}")
        try:
            resumenes = _extraer(zf, lista, nuevo)
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


def _barrer(base: Path, clave: str) -> None:
    """Borra lo que dejó un cambio anterior a medias, a mejor esfuerzo."""
    try:
        restos = [p for p in base.iterdir()
                  if p.name.startswith((f".{clave}.nuevo-", f".{clave}.viejo-"))]
    except OSError:
        return
    for resto in restos:
        shutil.rmtree(resto, ignore_errors=True)
