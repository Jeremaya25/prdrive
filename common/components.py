#!/usr/bin/env python3
r"""Qué componentes externos lleva el dispositivo y si siguen siendo los fijados.

Hay cosas del dispositivo que no son código de este proyecto: el binario de
rclone, el Python que lo ejecuta, en uno cifrado con VeraCrypt el VeraCrypt que
viaja fuera del contenedor y, con el llavero, KeePassXC. `common/pins.py` dice
cuáles TOCAN; aquí se lee cuáles LLEVA y se restan.

Vive en `common/` y no en `install/` porque quien lo pregunta es el
dispositivo: la ventana pinta ese aviso en su primer pintado, sin red ni
instalador. Solo lee ficheros diminutos del propio dispositivo (lo único que
escribe es el apunte de KeePassXC de más arriba), así que contesta al instante
y no lanza nunca (la misma regla que `update.pending()` y `store.read_json()`).
Quien ARREGLA lo detectado es `install/components.py`, que baja y verifica y se
ejecuta desde el zip del código, como el aplicador de la actualización del
programa.

Por qué hay sellos: un binario no dice su versión sin ejecutarlo y el de otra
plataforma no se puede ejecutar aquí (un Windows no arranca el rclone de Linux
ni un x64 el de ARM). Cada componente deja escrito de dónde salió:
- `runtime/<clave>/PRDRIVE-RUNTIME`: lo escribe `runtime_bin.extract()` el
  último de todo, así que una extracción a medias no tiene sello.
- `bin/<arch>/<rclone>.PRDRIVE-RCLONE`: lo escribe `deploy.copy_rclone()`.
  Lleva el nombre del binario porque `bin/x64/` es de dos plataformas a la vez
  (`rclone.exe` y `rclone`).
- `VeraCrypt/PRDRIVE-VERACRYPT`: en la raíz FÍSICA, no en `.prdrive/` (el
  VeraCrypt que abre el contenedor no puede vivir dentro de él). Lo escribe
  `install/traveler.py` el último, con la versión y el SHA-256 de cada fichero.
- `keepassxc/<paquete>/PRDRIVE-KEEPASSXC`: lo escribe
  `install/keepassxc_bin.py` el último, con la versión y el SHA-256 de cada
  fichero. Dice de dónde salió el paquete, no que sus ficheros sigan siendo
  esos: eso lo comprueba `keepassxc.comprobar()` al lanzar (con la forma del
  árbol oficial, `keepassxc_arbol_no_cuadra()`, y la suma del ejecutable), y lo
  que encuentra lo deja en `state/keepassxc-no-oficial.json`
  (`keepassxc_alterado()`) para que esta ventana ofrezca «Actualizar…» sin
  resumir nada.

Un dispositivo aprovisionado antes de los sellos no tiene el de rclone: se lee
como «no consta» y eso CUENTA como pendiente, que es la única respuesta
honesta.

Con VeraCrypt no es igual, a propósito: una carpeta `VeraCrypt\` sin sello es
la copia de una instalación (`VeraCrypt.exe` de una sola arquitectura) y el
vestíbulo de ese dispositivo solo sabe abrir esa disposición. Cambiarla sin
cambiar a la vez el vestíbulo dejaría la unidad sin forma de abrirse, y el
vestíbulo no lo toca una actualización de componentes (solo el paso 5 y «Añadir
plataformas…»). Sale como pendiente marcada `asistente`: se dice y no se toca.

También viven aquí las rutas de los componentes dentro de `.prdrive/` para que
haya UNA copia: `install/platforms.py` las importa, y eso garantiza que el
instalador escriba donde el dispositivo lee.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from . import APP_NAME, model, pins, store, vestibulo
from .pins import PLATAFORMAS, Plataforma

RUNTIME_SUBDIR = "runtime"
"""Carpeta del runtime dentro de `.prdrive/`.

`install/runtime_bin.py` la reexporta y `penwatch.py` repite el nombre del
sello (no puede importar nada del proyecto); un test impide que las copias se
separen.
"""
RUNTIME_STAMP = "PRDRIVE-RUNTIME"
"""Nombre del sello del runtime; ver `RUNTIME_SUBDIR`."""

RCLONE_STAMP_SUFIJO = ".PRDRIVE-RCLONE"
"""Sufijo del sello de rclone, que acompaña a un fichero y no a una carpeta.

Por eso es un sufijo: `bin/x64/rclone.exe.PRDRIVE-RCLONE` y
`bin/x64/rclone.PRDRIVE-RCLONE` conviven sin pisarse.
"""

VERACRYPT_STAMP = "PRDRIVE-VERACRYPT"
"""Nombre del sello del VeraCrypt de viaje.

Va DENTRO de su carpeta `VeraCrypt/`, en la raíz física: la carpeta entera se
sustituye con un renombrado y el sello con ella.
"""
FICHERO_SELLO = "fichero "
"""Prefijo de las líneas de fichero del sello del VeraCrypt.

Cada una es `fichero <nombre> = <sha256>`.
"""

KEEPASSXC_SUBDIR = "keepassxc"
"""Carpeta de KeePassXC dentro de `.prdrive/`, con una subcarpeta por paquete.

Los paquetes son los de `pins.KEEPASSXC` (`windows-x64`, `linux-x64`). Al lado, en
`keepassxc/config/`, va su configuración, que no es del paquete: cambiar de
versión sustituye la carpeta del paquete entera sin tocarla.
"""
KEEPASSXC_STAMP = "PRDRIVE-KEEPASSXC"
"""Nombre del sello de KeePassXC, dentro de la carpeta de su paquete."""
KEEPASSXC_EXE = "KeePassXC.exe"
"""El ejecutable de KeePassXC dentro de la carpeta del paquete de Windows."""
KEEPASSXC_APPIMAGE = "KeePassXC.AppImage"
"""El AppImage de KeePassXC dentro de la carpeta del paquete de Linux.

Con un nombre fijo y no el de la release (`KeePassXC-2.7.12-x86_64.AppImage`):
cambiar de versión sustituye la carpeta, y quien lo busca no tiene que saber
de qué versión es.
"""
KEEPASSXC_NO_OFICIAL = "keepassxc-no-oficial.json"
"""Fichero de `state/` donde se apunta un KeePassXC cuyo sello está al día pero no sus ficheros.

`keepassxc.comprobar()` resume el ejecutable justo antes de lanzarlo y, si no es
el fijado, lo deja aquí: `{paquete: {"version": …, "fichero": …}}`. Lo lee
`keepassxc_pendiente()`, que no puede resumir 11 MB al pintar la ventana, para
ofrecer el «Actualizar…» de siempre. Lo borra `keepassxc_bin.instalar()` al
reponer el paquete, o al ver que sus ficheros ya cuadran.
"""

KEEPASSXC_ARBOL = Path(__file__).resolve().parent / "keepassxc_arbol.json"
"""La tabla fijada de TODOS los ficheros de cada paquete de KeePassXC que se lanza desde la unidad.

`{versión: {paquete: {ruta relativa con "/": [tamaño, sha256]}}}`, de cada
fichero del ZIP oficial sin su carpeta de arriba (`keepassxc_bin.miembros()`).
La escribe `generar_arbol_keepassxc.py`, que añade la versión fijada sin quitar
las otras. Va en `common/`, así que viaja con el código y entra en la huella del
agente. La lee `keepassxc_arbol()`; la usa `keepassxc_arbol_no_cuadra()`.
"""
KEEPASSXC_CONFIG_PAQUETE = "config"
"""La carpeta del paquete de Windows donde KeePassXC (y prdrive) dejan los JSON del navegador.

Un fichero normal directamente en ella se admite aunque no esté en el árbol:
los JSON de mensajería nativa y los `.ini` que la CLI portátil deja ahí (H-3).
Ni el cargador de Windows ni Qt cargan código de esa carpeta. Lo que haya más
adentro (`config/sub/…`) no se admite.
"""
KEEPASSXC_RESUMIR_HASTA = 4096  # bytes
"""Hasta qué tamaño se resume, además de medirse, un fichero del árbol de KeePassXC.

Es donde cabe una instrucción: el `qt.conf` del ZIP oficial (44 bytes) dice a
Qt de dónde cargar los plugins, y otro del mismo tamaño podría mandarlo a otra
carpeta. Resumir lo que no pasa de 4 KiB no cuesta nada (en 2.7.12, tres
ficheros).
"""
_ARBOLES: dict | None = None
"""`KEEPASSXC_ARBOL` ya leído en este proceso (`keepassxc_arbol()`); `None`, sin leer."""

RCLONE = "rclone"
PYTHON = "python"
VERACRYPT = "veracrypt"
KEEPASSXC = "keepassxc"

DESCONOCIDA = "no consta"
"""Lo que se enseña cuando no hay sello.

No es un error: es un dispositivo de antes de que existieran los sellos, y lo
que le hace falta es justo una actualización.
"""


def _base(app_dir: Path | str | None) -> Path:
    """Devuelve la carpeta del código; sin argumento, la de ESTE dispositivo.

    Se resuelve al llamar y no al importar: el instalador pregunta por un
    volumen que no es el suyo y `tests/_harness.sandbox()` no reengancha
    `model.APP_DIR`.
    """
    return Path(app_dir) if app_dir is not None else model.APP_DIR


def runtime_dir(app_dir: Path | str | None, plat: Plataforma) -> Path:
    """Devuelve la carpeta del runtime de esa plataforma."""
    return _base(app_dir) / RUNTIME_SUBDIR / plat.clave


def rclone_path(app_dir: Path | str | None, plat: Plataforma) -> Path:
    """Devuelve la ruta del rclone de esa plataforma."""
    return _base(app_dir) / "bin" / plat.bin_dir / plat.rclone_exe


def rclone_stamp_path(app_dir: Path | str | None, plat: Plataforma) -> Path:
    """Devuelve la ruta del sello de ese rclone."""
    ruta = rclone_path(app_dir, plat)
    return ruta.with_name(ruta.name + RCLONE_STAMP_SUFIJO)


def veracrypt_dir(raiz_fisica: Path | str) -> Path:
    """Devuelve la carpeta del VeraCrypt de viaje.

    Cuelga de la raíz FÍSICA del volumen, junto al `.hc`, y no de `.prdrive/`:
    dentro del contenedor haría falta VeraCrypt para llegar a VeraCrypt.
    """
    return Path(raiz_fisica) / vestibulo.TRAVELER


def veracrypt_stamp_path(raiz_fisica: Path | str) -> Path:
    """Devuelve la ruta del sello del VeraCrypt de viaje."""
    return veracrypt_dir(raiz_fisica) / VERACRYPT_STAMP


def keepassxc_dir(app_dir: Path | str | None, paquete: str) -> Path:
    """Devuelve la carpeta del KeePassXC de ese paquete (`pins.KEEPASSXC`)."""
    return _base(app_dir) / KEEPASSXC_SUBDIR / paquete


def keepassxc_programa(paquete: str) -> str:
    """Devuelve el nombre del programa de ese paquete: `KeePassXC.exe` o el AppImage."""
    return KEEPASSXC_APPIMAGE if paquete.startswith("linux-") else KEEPASSXC_EXE


def keepassxc_exe(app_dir: Path | str | None, paquete: str) -> Path:
    """Devuelve el programa de KeePassXC de ese paquete (`keepassxc_programa()`)."""
    return keepassxc_dir(app_dir, paquete) / keepassxc_programa(paquete)


def paquete_keepassxc(plat: Plataforma) -> str | None:
    """Devuelve qué paquete de KeePassXC usa esa plataforma, o `None` si ninguno."""
    return pins.KEEPASSXC_PARA.get(plat.clave)


def paquetes_keepassxc(app_dir: Path | str | None = None) -> list[str]:
    """Devuelve los paquetes de KeePassXC que necesita ese dispositivo.

    Uno por cada plataforma que lleva (la que tiene su rclone, como
    `fleet.plataformas_instaladas()`) y que tiene paquete, sin repetir: un
    dispositivo con Windows x64 y ARM64 lleva un solo KeePassXC, el de x64, y
    Linux ARM64 ninguno (usa el del equipo).
    """
    salida: list[str] = []
    for plat in PLATAFORMAS:
        paquete = paquete_keepassxc(plat)
        if paquete and paquete not in salida and _existe(rclone_path(app_dir, plat)):
            salida.append(paquete)
    return salida


def llavero_activo(app_dir: Path | str | None = None) -> bool:
    """Indica si ese dispositivo tiene el llavero: `[keychain]` en su `sync_config.toml`.

    Lee el TOML sin el modelo, y nunca lanza: lo pregunta la ventana al
    pintarse. Sin argumento es el config de este dispositivo
    (`model.CONFIG_FILE`, que los tests reenganchan).
    """
    import tomllib
    ruta = (Path(app_dir) / "sync_config.toml") if app_dir is not None else model.CONFIG_FILE
    try:
        with open(ruta, "rb") as f:
            raw = tomllib.load(f)
    except (OSError, ValueError):
        return False
    return isinstance(raw.get("keychain"), dict)


def keepassxc_stamp_text(version: str, nombre: str, sha256_paquete: str,
                         ficheros: dict[str, str]) -> str:
    """Devuelve el sello de KeePassXC: de qué paquete salió y qué hay en él.

    Como el de VeraCrypt, lleva el SHA-256 de cada fichero, aquí con su ruta
    relativa a la carpeta del paquete (`plugins/…`), siempre con `/`.

    Args:
        version: La versión de KeePassXC.
        nombre: El nombre del paquete oficial (el ZIP o el AppImage).
        sha256_paquete: Su SHA-256.
        ficheros: `{ruta relativa: sha256}`.
    """
    lineas = [f"# {APP_NAME} — el KeePassXC del llavero. Lo escribe el instalador "
              f"y lo lee la ventana. No lo toques.",
              f"{KEEPASSXC} = {version}",
              f"paquete = {nombre}",
              f"sha256 = {sha256_paquete}"]
    lineas += [f"{FICHERO_SELLO}{ruta} = {resumen}"
               for ruta, resumen in sorted(ficheros.items())]
    return "\n".join(lineas) + "\n"


def ruta_relativa_segura(ruta: str) -> bool:
    """Indica si es una ruta relativa que no sale de su carpeta.

    Con `/` como separador; nada de `\\`, unidad, `..`, `.`, partes vacías ni
    rutas absolutas. Es lo que se exige a cada fichero del ZIP de KeePassXC y a
    cada línea de su sello.
    """
    if not ruta or ruta.startswith("/") or "\\" in ruta or ":" in ruta or "\0" in ruta:
        return False
    return all(parte not in ("", ".", "..") for parte in ruta.split("/"))


def keepassxc_ficheros(texto: str) -> dict[str, str]:
    """Devuelve `{ruta relativa: sha256}` de los ficheros que declara su sello.

    Una ruta que se salga de la carpeta no cuenta (`ruta_relativa_segura()`).
    """
    salida: dict[str, str] = {}
    for clave, valor in leer_sello(texto).items():
        if not clave.startswith(FICHERO_SELLO):
            continue
        ruta = clave[len(FICHERO_SELLO):].strip()
        if ruta_relativa_segura(ruta):
            salida[ruta] = valor.lower()
    return salida


def keepassxc_usa_arbol(paquete: str) -> bool:
    """Indica si de ese paquete se comprueba el árbol entero (`keepassxc_arbol_no_cuadra()`).

    Es todo paquete que se ejecuta desde la unidad: el de Windows. El AppImage
    de Linux es un solo fichero que se copia y se comprueba entero en el equipo.
    """
    return keepassxc_programa(paquete) != KEEPASSXC_APPIMAGE


def _leer_arboles() -> dict:
    """Devuelve `KEEPASSXC_ARBOL` leído, o `{}` si no se puede leer o no se entiende."""
    try:
        datos = json.loads(KEEPASSXC_ARBOL.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


def keepassxc_arbol(version: str, paquete: str) -> dict[str, tuple[int, str]] | None:
    """Devuelve el árbol oficial de ese paquete de KeePassXC: `{ruta: (tamaño, sha256)}`.

    Lee `KEEPASSXC_ARBOL` una vez por proceso. Es de módulo para que los tests
    la sustituyan por un árbol de mentira.

    Returns:
        El árbol, con las rutas relativas con `/`; `None` si la tabla no tiene
        esa versión y paquete o si su fila no se entiende entera (una ruta que
        se sale de la carpeta, un tamaño o una suma mal escritos): lo que no se
        sabe no se da por bueno.
    """
    global _ARBOLES
    if _ARBOLES is None:
        _ARBOLES = _leer_arboles()
    fila = _ARBOLES.get(version, {})
    fila = fila.get(paquete) if isinstance(fila, dict) else None
    if not isinstance(fila, dict) or not fila:
        return None
    arbol: dict[str, tuple[int, str]] = {}
    for ruta, valor in fila.items():
        if not (isinstance(ruta, str) and ruta_relativa_segura(ruta)
                and isinstance(valor, list) and len(valor) == 2):
            return None
        tamano, suma = valor
        if (not isinstance(tamano, int) or isinstance(tamano, bool) or tamano < 0
                or not isinstance(suma, str) or len(suma) != 64
                or any(ch not in "0123456789abcdef" for ch in suma)):
            return None
        arbol[ruta] = (tamano, suma)
    return arbol


REPARSE_POINT = 0x400
"""`FILE_ATTRIBUTE_REPARSE_POINT`: un enlace, una unión u otro punto de reanálisis de Windows."""


def _es_enlace(entrada: os.DirEntry) -> bool:
    """Indica si esa entrada es un enlace simbólico, una unión o cualquier punto de reanálisis.

    Raises:
        OSError: Si no se puede mirar.
    """
    if entrada.is_symlink():
        return True
    es_union = getattr(entrada, "is_junction", None)  # Python 3.12+
    if es_union is not None and es_union():
        return True
    info = entrada.stat(follow_symlinks=False)
    return bool(getattr(info, "st_file_attributes", 0) & REPARSE_POINT)


def keepassxc_arbol_no_cuadra(carpeta: Path | str,
                              arbol: dict[str, tuple[int, str]]) -> tuple[str, str] | None:
    """Mira que la carpeta de un paquete tenga la forma del árbol oficial, sin resumir nada.

    Recorre la carpeta entera con `os.scandir`, sin seguir enlaces, y compara
    cada fichero con `arbol` (rutas con `casefold()`: Windows no distingue
    mayúsculas). No cuadra si hay un fichero que no está en el árbol, si falta
    uno, si uno tiene otro tamaño, si hay un enlace simbólico, una unión o algo
    que no es un fichero ni una carpeta, o si la carpeta no se puede leer. Se
    admiten fuera del árbol el sello (`KEEPASSXC_STAMP`) y cualquier fichero
    normal directamente en `KEEPASSXC_CONFIG_PAQUETE`. Una carpeta vacía que no
    es del árbol no cuenta: no lleva nada que cargar. Un fichero del árbol de
    hasta `KEEPASSXC_RESUMIR_HASTA` se resume (el `.portable`, los `.qm` vacíos); de los demás solo
    se mira el tamaño, así que uno cambiado en su sitio con el mismo tamaño no
    se ve aquí (de los ejecutables lo ve su suma, en `keepassxc.comprobar()`).

    Lista unos 131 ficheros y resume unos bytes: milisegundos, y vale para la
    ventana en segundo plano y para el instalador.

    Args:
        carpeta: La carpeta del paquete (`keepassxc_dir()`).
        arbol: Lo que dio `keepassxc_arbol()`.

    Returns:
        `(ruta relativa con "/", motivo en español)` del primer fichero que no
        cuadra, en un orden estable; `None` si todo cuadra.
    """
    esperados = {ruta.casefold(): (ruta, tamano, suma) for ruta, (tamano, suma) in arbol.items()}
    sello = KEEPASSXC_STAMP.casefold()
    config = KEEPASSXC_CONFIG_PAQUETE.casefold()
    try:
        info = os.lstat(carpeta)
    except OSError as e:
        return ".", f"no se ha podido leer la carpeta ({e})"
    if (stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & REPARSE_POINT):
        return ".", "la carpeta del paquete es un enlace o no es una carpeta"
    vistos: set[str] = set()
    pendientes = [("", os.fspath(carpeta))]
    while pendientes:
        rel_dir, ruta_dir = pendientes.pop(0)
        try:
            with os.scandir(ruta_dir) as it:
                entradas = sorted(it, key=lambda e: e.name)
        except OSError as e:
            return rel_dir or ".", f"no se ha podido leer la carpeta ({e})"
        for entrada in entradas:
            rel = f"{rel_dir}/{entrada.name}" if rel_dir else entrada.name
            clave = rel.casefold()
            try:
                if _es_enlace(entrada):
                    return rel, "es un enlace, y el paquete oficial no trae ninguno"
                if entrada.is_dir(follow_symlinks=False):
                    pendientes.append((rel, entrada.path))
                    continue
                normal = entrada.is_file(follow_symlinks=False)
                tamano = entrada.stat(follow_symlinks=False).st_size
            except OSError as e:
                return rel, f"no se ha podido leer ({e})"
            if not normal:
                return rel, "no es un fichero normal"
            if clave in vistos:
                return rel, "está repetido con otras mayúsculas"
            vistos.add(clave)
            if clave in esperados:
                _, oficial, suma = esperados[clave]
                if tamano != oficial:
                    return rel, f"tiene otro tamaño ({tamano} bytes; el oficial, {oficial})"
                if tamano <= KEEPASSXC_RESUMIR_HASTA:
                    try:
                        with open(entrada.path, "rb") as f:
                            leido = f.read(KEEPASSXC_RESUMIR_HASTA + 1)
                    except OSError as e:
                        return rel, f"no se ha podido leer ({e})"
                    if hashlib.sha256(leido).hexdigest() != suma:
                        return rel, "no es el del paquete oficial"
                continue
            if (not rel_dir and clave == sello) or rel_dir.casefold() == config:
                continue
            return rel, "no es del paquete oficial"
    for clave in sorted(set(esperados) - vistos):
        return esperados[clave][0], "falta"
    return None


def keepassxc_sello(app_dir: Path | str | None, paquete: str) -> dict[str, str]:
    """Devuelve el sello de ese KeePassXC como diccionario; vacío si no hay."""
    return leer_sello(_texto(keepassxc_dir(app_dir, paquete) / KEEPASSXC_STAMP))


def keepassxc_version(app_dir: Path | str | None, paquete: str) -> str | None:
    """Devuelve la versión que dice el sello de ese KeePassXC.

    Returns:
        La versión, o `None` si no hay ejecutable o el sello no la dice.
    """
    if not _existe(keepassxc_exe(app_dir, paquete)):
        return None
    return keepassxc_sello(app_dir, paquete).get(KEEPASSXC) or None


def _estado(app_dir: Path | str | None) -> Path:
    """Devuelve la carpeta `state/` de ese dispositivo; sin argumento, la de ESTE.

    Como `_base()`, se resuelve al llamar: sin argumento es `model.STATE_DIR`,
    que los tests reenganchan.
    """
    return model.STATE_DIR if app_dir is None else Path(app_dir) / "state"


def keepassxc_alterado(app_dir: Path | str | None, paquete: str) -> dict[str, str]:
    """Devuelve lo apuntado de que un fichero de ese KeePassXC no cuadra, o `{}`.

    Es `{"version": …, "fichero": …}`: la versión que decía el sello cuando
    `keepassxc.comprobar()` rechazó ese fichero. Un fichero que falta, a medias
    o que no es un objeto se lee como «no consta nada»; nunca lanza.
    """
    apunte = store.read_json(_estado(app_dir) / KEEPASSXC_NO_OFICIAL).get(paquete)
    if not isinstance(apunte, dict):
        return {}
    version, fichero = apunte.get("version"), apunte.get("fichero")
    if not (isinstance(version, str) and version and isinstance(fichero, str) and fichero):
        return {}
    return {"version": version, "fichero": fichero}


def keepassxc_anotar_alterado(app_dir: Path | str | None, paquete: str, version: str,
                              fichero: str) -> bool:
    """Apunta que ese fichero del KeePassXC de ese paquete no es el oficial.

    Solo se apunta el último: basta para que la ventana ofrezca «Actualizar…»,
    que repone el paquete entero. Es un favor a quien mira después, no una
    condición de nada: si el dispositivo es de solo lectura o ya se extrajo, no
    se escribe y se devuelve `False`; nunca lanza.

    Args:
        version: La que decía el sello; si cambia, el apunte deja de contar.
        fichero: Su ruta dentro de la carpeta del paquete, con `/`.
    """
    ruta = _estado(app_dir) / KEEPASSXC_NO_OFICIAL
    datos = store.read_json(ruta)
    nuevo = {"version": version, "fichero": fichero}
    if datos.get(paquete) == nuevo:
        return True
    datos[paquete] = nuevo
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return store.write_json(ruta, datos)


def keepassxc_olvidar_alterado(app_dir: Path | str | None, paquete: str) -> bool:
    """Olvida lo apuntado de ese paquete; quien no tenía nada apuntado no es un error.

    Con el último apunte se va el fichero entero. Nunca lanza.

    Returns:
        `False` solo si había algo apuntado y no se ha podido quitar.
    """
    ruta = _estado(app_dir) / KEEPASSXC_NO_OFICIAL
    datos = store.read_json(ruta)
    if paquete not in datos:
        return True
    del datos[paquete]
    if datos:
        return store.write_json(ruta, datos)
    try:
        ruta.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return True


def leer_sello(texto: str) -> dict[str, str]:
    """Devuelve un sello `clave = valor` como diccionario; lo que no se entienda, fuera.

    Es tolerante a propósito, como `store.read_json()`: la ventana lo lee al
    abrirse y un fichero a medias (el dispositivo se extrajo a mitad de una
    escritura) tiene que significar «aquí no consta nada», no una excepción en
    el arranque.
    """
    datos: dict[str, str] = {}
    for linea in texto.splitlines():
        if linea.lstrip().startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        datos[clave.strip()] = valor.strip()
    return datos


def _texto(ruta: Path) -> str:
    """Lee un fichero como texto; cadena vacía si no se puede."""
    try:
        return ruta.read_text(encoding="utf-8")
    except (OSError, ValueError):
        # También `ValueError`: un fichero a medias (dispositivo extraído a
        # mitad de escritura) falla con `UnicodeDecodeError`, no con un error
        # de E/S, y es el mismo suceso que el resto del módulo trata como «no
        # consta».
        return ""


def rclone_stamp_text(plat: Plataforma, version: str) -> str:
    """Devuelve el sello de un rclone: qué versión se copió y para qué plataforma.

    Sin sha256, a diferencia del sello del runtime: aquel lo lleva porque
    penwatch compara el TEXTO ENTERO para decidir si refresca su copia, y aquí
    solo hay que contestar «¿es la versión fijada?».
    """
    return (f"# {APP_NAME} — el rclone de este dispositivo. Lo escribe el "
            f"instalador y lo lee la ventana. No lo toques.\n"
            f"rclone = {version}\n"
            f"plataforma = {plat.clave}\n")


def veracrypt_stamp_text(version: str, sha256_paquete: str,
                         ficheros: dict[str, str], paquete: str | None = None) -> str:
    """Devuelve el sello del VeraCrypt de viaje: de qué paquete salió y qué hay en él.

    A diferencia del de rclone, este SÍ lleva el resumen de cada fichero: es a
    la vez el manifiesto de la caché del instalador (`install/veracrypt_bin.py`
    vuelve a resumir cada fichero contra él antes de usarlo) y el de la carpeta
    de la unidad, que es una copia exacta de esa caché.

    Args:
        version: La versión de VeraCrypt.
        sha256_paquete: SHA-256 de lo descargado.
        ficheros: `{nombre: sha256}` de cada fichero que se conserva.
        paquete: Nombre de lo descargado cuando no es el Portable de Windows
            (el AppImage de Linux, `install/veracrypt_bin.py`).
    """
    lineas = [f"# {APP_NAME} — el VeraCrypt que viaja en esta unidad. Lo escribe "
              f"el instalador y lo lee la ventana. No lo toques.",
              f"{VERACRYPT} = {version}",
              f"paquete = {paquete or f'VeraCrypt Portable {version}.exe'}",
              f"sha256 = {sha256_paquete}"]
    lineas += [f"{FICHERO_SELLO}{nombre} = {resumen}"
               for nombre, resumen in sorted(ficheros.items())]
    return "\n".join(lineas) + "\n"


def veracrypt_ficheros(texto: str) -> dict[str, str]:
    """Devuelve `{nombre: sha256}` de los ficheros que declara el sello.

    Un nombre que no sea suelto (con barra, `..` o unidad) no cuenta: esto se
    usa para leer y copiar, y un sello escrito a mano no puede llevar a nadie
    fuera de la carpeta.
    """
    salida: dict[str, str] = {}
    for clave, valor in leer_sello(texto).items():
        if not clave.startswith(FICHERO_SELLO):
            continue
        nombre = clave[len(FICHERO_SELLO):].strip()
        if (nombre and nombre not in (".", "..") and "/" not in nombre
                and "\\" not in nombre and ":" not in nombre):
            salida[nombre] = valor.lower()
    return salida


def veracrypt_integro(carpeta: Path | str, necesarios: tuple[str, ...] = (),
                      version: str | None = None) -> bool:
    """Comprueba que esa carpeta de VeraCrypt es la que dice su sello, byte a byte.

    Exige el sello (y de `version`, si se pide), cada fichero que nombra con su
    SHA-256 y ninguno de `necesarios` sin nombrar. Es
    `install/veracrypt_bin.verificada()` en `common/` porque también lo hace el
    agente, que no lleva `install/`, cada vez que va a lanzar SU VeraCrypt: lo
    que pide administrador tiene que ser lo que se comprobó al instalar. No
    lanza nunca.

    Args:
        carpeta: La carpeta del VeraCrypt.
        necesarios: Ficheros que el sello tiene que nombrar.
        version: Versión que debe declarar el sello, si se exige.

    Returns:
        True si todo cuadra.
    """
    import hashlib
    carpeta = Path(carpeta)
    try:
        texto = (carpeta / VERACRYPT_STAMP).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return False
    if version is not None and leer_sello(texto).get(VERACRYPT) != version:
        return False
    ficheros = veracrypt_ficheros(texto)
    if not ficheros or not all(n in ficheros for n in necesarios):
        return False
    try:
        for nombre, esperado in ficheros.items():
            h = hashlib.sha256()
            with open(carpeta / nombre, "rb") as f:
                for trozo in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(trozo)
            if h.hexdigest() != esperado:
                return False
    except OSError:
        return False
    return True


def runtime_stamp(app_dir: Path | str | None, plat: Plataforma) -> str | None:
    """Devuelve el sello del runtime de esa plataforma.

    Sin sello no hay runtime (`runtime_bin.extract()` lo escribe el último, así
    que una extracción interrumpida no lo tiene) y sin intérprete tampoco.

    Returns:
        El texto del sello, o `None` si no hay uno completo.
    """
    d = runtime_dir(app_dir, plat)
    try:
        if not (d / plat.interprete).is_file():
            return None
        return (d / RUNTIME_STAMP).read_text(encoding="utf-8")
    except (OSError, ValueError):
        # Mismo motivo que en `_texto()`: un sello a medio escribir falla con
        # `UnicodeDecodeError`, y el contrato del módulo (nunca lanza, la
        # ventana lo llama en su primer pintado) es el mismo para los dos.
        return None


@dataclass(frozen=True)
class Pendiente:
    """Un componente que el dispositivo lleva y que no es el que el programa fija.

    El VeraCrypt de viaje no es de ninguna plataforma (lleva las dos
    arquitecturas de Windows a la vez) y vive fuera de `.prdrive/`: su
    `plataforma` es `None` y `ruta` dice dónde está su carpeta. `asistente` es
    el VeraCrypt sin sello de un dispositivo de antes: pendiente, pero no lo
    pone al día una actualización de componentes (ver el docstring del módulo).

    Args:
        plataforma: La plataforma del componente, o `None` para el VeraCrypt.
        que: `RCLONE`, `PYTHON` o `VERACRYPT`.
        lleva: Lo que hay ahora, o `DESCONOCIDA`.
        deberia: Lo que dice `common/pins.py`.
        ruta: Carpeta del componente, para el VeraCrypt.
        asistente: Si solo se arregla desde el asistente del instalador.
    """
    plataforma: Plataforma | None
    que: str
    lleva: str
    deberia: str
    ruta: Path | None = None
    asistente: bool = False

    @property
    def titulo(self) -> str:
        """Devuelve el nombre del componente para mostrar."""
        if self.que == VERACRYPT:
            return "VeraCrypt de la unidad"
        if self.que == KEEPASSXC:
            return "KeePassXC del llavero"
        nombre = "rclone" if self.que == RCLONE else "Python"
        return f"{nombre} de {self.plataforma.nombre}"

    def describe(self) -> str:
        """Devuelve una frase con lo que lleva, lo que toca y cómo se arregla."""
        if self.asistente:
            return (f"{self.titulo}: una copia de antes, sin sello; se pone al día "
                    f"con «Añadir plataformas…» del instalador")
        return f"{self.titulo}: lleva {self.lleva}, toca {self.deberia}"


def _existe(ruta: Path) -> bool:
    """Indica si es un fichero, sin lanzar.

    Un volumen bloqueado o desenchufado cuenta como que no.
    """
    try:
        return ruta.is_file()
    except OSError:
        return False        # bloqueado, desenchufado: no hay nada que decir


def rclone_pendiente(app_dir: Path | str | None,
                     plat: Plataforma) -> Pendiente | None:
    """Devuelve el rclone de esa plataforma si no es el fijado.

    Returns:
        El `Pendiente`, o `None` si no lleva rclone o es el correcto.
    """
    if not _existe(rclone_path(app_dir, plat)):
        return None
    sello = leer_sello(_texto(rclone_stamp_path(app_dir, plat)))
    lleva = sello.get(RCLONE) or DESCONOCIDA
    if lleva == pins.RCLONE_VERSION:
        return None
    return Pendiente(plat, RCLONE, lleva, pins.RCLONE_VERSION)


def python_pendiente(app_dir: Path | str | None,
                     plat: Plataforma) -> Pendiente | None:
    """Devuelve el Python de esa plataforma si no es el fijado.

    Returns:
        El `Pendiente`, o `None` si no lleva runtime o es el correcto.
    """
    texto = runtime_stamp(app_dir, plat)
    if texto is None:
        return None
    sello = leer_sello(texto)
    version = sello.get("python") or DESCONOCIDA
    release = sello.get("release") or DESCONOCIDA
    # En Linux cuenta también el Tk con Xft (`pins.TK_XFT_TAG`): uno sin él
    # funciona, pero con la letra sin suavizar. Solo si hay uno fijado para su
    # arquitectura; si no, no hay nada que ofrecerle.
    quiere_tk = (not plat.es_windows
                 and bool(pins.TK_XFT_SHA256.get(plat.triple.split("-")[0])))
    tk = sello.get("tk") or ""
    if (version == pins.PYTHON_VERSION and release == pins.PYTHON_RELEASE
            and (not quiere_tk or tk == pins.TK_XFT_TAG)):
        return None
    con = " + Tk con Xft"
    return Pendiente(plat, PYTHON, f"{version} ({release})" + (con if tk else ""),
                     f"{pins.PYTHON_VERSION} ({pins.PYTHON_RELEASE})"
                     + (con if quiere_tk else ""))


def veracrypt_pendiente(raiz_fisica: Path | str) -> Pendiente | None:
    """Devuelve el VeraCrypt de viaje de esa raíz física si no es el fijado.

    Sin carpeta (o sin ningún ejecutable de montar dentro) no lleva, y lo que
    no lleva no está anticuado. Con sello de otra versión es pendiente y
    actualizable; sin sello es la copia de una instalación anterior y sale
    marcada `asistente`.
    """
    if not vestibulo.traveler_ejecutables(raiz_fisica):
        return None
    carpeta = veracrypt_dir(raiz_fisica)
    lleva = leer_sello(_texto(carpeta / VERACRYPT_STAMP)).get(VERACRYPT)
    if lleva == pins.VERACRYPT_VERSION:
        return None
    return Pendiente(None, VERACRYPT, lleva or DESCONOCIDA, pins.VERACRYPT_VERSION,
                     ruta=carpeta, asistente=not lleva)


def keepassxc_pendiente(app_dir: Path | str | None, paquete: str) -> Pendiente | None:
    """Devuelve el KeePassXC de ese paquete si no es el fijado.

    A diferencia de rclone, uno que no está también cuenta: quien pregunta ya
    sabe que el dispositivo tiene llavero (`llavero_activo()`), y sin KeePassXC
    el llavero no se abre. Sale como «no consta», igual que un rclone sin sello,
    y es lo que hace que activar el llavero desde «Ajustes» lo traiga con el
    «Actualizar…» de siempre.

    El sello solo dice de dónde salió el paquete, no que sus ficheros sigan
    siendo esos. Resumirlos aquí (11 MB en Windows, 47 en Linux) frenaría el
    primer pintado, así que se mira lo que apuntó quien sí los resumió
    (`keepassxc_alterado()`): con el sello al día y un fichero que no cuadró, el
    paquete sale pendiente igual, como lo que lleva con ficheros que no cuadran.
    """
    lleva = keepassxc_version(app_dir, paquete) or DESCONOCIDA
    if lleva == pins.KEEPASSXC_VERSION:
        if keepassxc_alterado(app_dir, paquete).get("version") != lleva:
            return None
        lleva = f"{lleva} (con ficheros que no cuadran)"
    return Pendiente(None, KEEPASSXC, lleva, pins.KEEPASSXC_VERSION,
                     ruta=keepassxc_dir(app_dir, paquete))


def raiz_fisica(app_dir: Path | str | None = None) -> Path | None:
    """Devuelve la raíz física del contenedor VeraCrypt en el que vive ese dispositivo.

    Se busca por el id del fichero de control y la marca del vestíbulo, que une
    las dos mitades (`vestibulo.raiz_fisica()`: un stat por unidad, sin red).
    `fleet` se importa dentro porque importa este módulo. Es función de módulo
    para que los tests la sustituyan; nunca lanza.

    Returns:
        La raíz, o `None` si no vive en un contenedor o no se ve desde aquí.
    """
    try:
        from . import fleet
        return vestibulo.raiz_fisica(fleet.device_id(app_dir))
    except Exception:                                # noqa: BLE001
        return None


_BUSCAR = object()
"""Valor centinela de `pendientes(fisica=...)`: «buscar la raíz física»."""


def pendientes(app_dir: Path | str | None = None,
               fisica: Path | str | None | object = _BUSCAR) -> list[Pendiente]:
    r"""Devuelve los componentes del dispositivo que no son los que fija el programa.

    Solo mira lo que el dispositivo LLEVA: una plataforma que no tiene no está
    anticuada sino sin instalar, y eso lo resuelve «Añadir plataformas…», que
    es una decisión con espacio en disco de por medio. Igual el VeraCrypt de
    viaje: sin carpeta `VeraCrypt\` no hay nada que poner al día. KeePassXC
    es la excepción: con el llavero activo, uno que falta también cuenta
    (`keepassxc_pendiente()`). Ni lanza ni toca la red: lo pregunta la ventana
    al pintarse.

    Args:
        app_dir: Carpeta del código; por defecto, la de este dispositivo.
        fisica: Raíz física del contenedor si se sabe; por defecto se busca
            (`raiz_fisica()`), y `None` es «no vive en un contenedor».
    """
    salida: list[Pendiente] = []
    for plat in PLATAFORMAS:
        # rclone primero: es el que sincroniza, y sin él el dispositivo no hace
        # nada en ningún equipo.
        for encontrar in (rclone_pendiente, python_pendiente):
            hallado = encontrar(app_dir, plat)
            if hallado is not None:
                salida.append(hallado)
    if fisica is _BUSCAR:
        fisica = raiz_fisica(app_dir)
    if fisica is not None:
        try:
            hallado = veracrypt_pendiente(fisica)       # type: ignore[arg-type]
        except (OSError, ValueError):
            hallado = None
        if hallado is not None:
            salida.append(hallado)
    if llavero_activo(app_dir):
        for paquete in paquetes_keepassxc(app_dir):
            try:
                hallado = keepassxc_pendiente(app_dir, paquete)
            except (OSError, ValueError):
                hallado = None
            if hallado is not None:
                salida.append(hallado)
    return salida


def corre_desde(carpeta: Path | str) -> bool:
    """Indica si el intérprete de ESTE proceso vive dentro de esa carpeta.

    Está aquí y no en `install/` porque lo preguntan las dos puntas: la
    ventana, para avisar antes de empezar de que tendrá que cerrarse, y el
    aplicador, para no cambiar la carpeta de un intérprete vivo (Windows deja
    apartarla pero luego no borrarla, y lo que sí borra es su biblioteca
    estándar). Nunca lanza.
    """
    try:
        Path(sys.executable).resolve().relative_to(Path(carpeta).resolve())
        return True
    except (ValueError, OSError):
        return False


def propio(pends: list[Pendiente],
           app_dir: Path | str | None = None) -> Pendiente | None:
    """Devuelve el Python pendiente con el que corre este mismo proceso.

    Es el caso normal de una instalación completa: la ventana arranca desde
    `runtime/<clave>/` de este equipo, así que ese runtime no se puede cambiar
    mientras siga abierta. Hay como mucho uno.

    Returns:
        El `Pendiente`, o `None` si el proceso no corre de ningún runtime
        pendiente.
    """
    for p in pends:
        if (p.que == PYTHON and p.plataforma is not None
                and corre_desde(runtime_dir(app_dir, p.plataforma))):
            return p
    return None


def actualizables(pends: list[Pendiente]) -> list[Pendiente]:
    """Devuelve los pendientes que puede poner al día una actualización de componentes.

    Son todos menos el VeraCrypt sin sello, que es cosa de «Añadir
    plataformas…».
    """
    return [p for p in pends if not p.asistente]


def resumen(pends: list[Pendiente]) -> str:
    """Devuelve una línea por componente, para el recuadro de la ventana y el menú."""
    return "\n".join(p.describe() for p in pends)
