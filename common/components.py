#!/usr/bin/env python3
r"""Qué componentes externos lleva el dispositivo y si siguen siendo los fijados.

Tres cosas del dispositivo no son código de este proyecto: el binario de
rclone, el Python que lo ejecuta y, en uno cifrado con VeraCrypt, el VeraCrypt
que viaja fuera del contenedor. `common/pins.py` dice cuáles TOCAN; aquí se lee
cuáles LLEVA y se restan.

Vive en `common/` y no en `install/` porque quien lo pregunta es el
dispositivo: la ventana pinta ese aviso en su primer pintado, sin red ni
instalador. Solo lee ficheros diminutos del propio dispositivo, así que
contesta al instante y no lanza nunca (la misma regla que `update.pending()` y
`store.read_json()`). Quien ARREGLA lo detectado es `install/components.py`,
que baja y verifica y se ejecuta desde el zip del código, como el aplicador de
la actualización del programa.

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

import sys
from dataclasses import dataclass
from pathlib import Path

from . import APP_NAME, model, pins, vestibulo
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

RCLONE = "rclone"
PYTHON = "python"
VERACRYPT = "veracrypt"

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
    if version == pins.PYTHON_VERSION and release == pins.PYTHON_RELEASE:
        return None
    return Pendiente(plat, PYTHON, f"{version} ({release})",
                     f"{pins.PYTHON_VERSION} ({pins.PYTHON_RELEASE})")


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
    viaje: sin carpeta `VeraCrypt\` no hay nada que poner al día. Ni lanza ni
    toca la red: lo pregunta la ventana al pintarse.

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
