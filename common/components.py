#!/usr/bin/env python3
"""
components.py — Qué lleva el dispositivo de fuera, y si sigue siendo lo fijado.

Tres cosas del dispositivo no son código de este proyecto: el binario de rclone,
el Python que lo ejecuta y, en uno cifrado con VeraCrypt, el VeraCrypt que viaja
fuera del contenedor. `common/pins.py` dice cuáles TOCAN; aquí se lee cuáles
LLEVA, y se restan.

Vive en `common/` y no en `install/` porque quien tiene que preguntárselo es el
dispositivo: la ventana pinta ese aviso en su primer pintado, y ahí no hay ni
red ni instalador. Todo lo de este módulo es leer ficheros diminutos del propio
dispositivo, así que contesta al instante y no lanza nunca —la misma regla que
`update.pending()` y `store.read_json()`—.

Quien ARREGLA lo que aquí se detecta es `install/components.py`, que sí baja y
verifica, y que no viaja al dispositivo: se ejecuta desde el zip del código, como
el aplicador de la actualización del programa.

**Por qué hay sellos.** Un binario no dice su versión sin ejecutarlo, y el de
otra plataforma no se puede ejecutar aquí: un Windows no arranca el rclone de
Linux ni un x64 el de ARM. Así que cada componente deja escrito de dónde salió:

  * `runtime/<clave>/PRDRIVE-RUNTIME` — lo escribe `runtime_bin.extract()`, el
    último de todo, de modo que una extracción a medias no tiene sello.
  * `bin/<arch>/<rclone>.PRDRIVE-RCLONE` — lo escribe `deploy.copy_rclone()`. Va
    junto al binario y lleva su nombre porque `bin/x64/` es de dos plataformas a
    la vez: ahí conviven el `rclone.exe` de Windows y el `rclone` de Linux.
  * `VeraCrypt/PRDRIVE-VERACRYPT` — en la raíz FÍSICA, no en `.prdrive/`: el
    VeraCrypt que abre el contenedor no puede vivir dentro de él. Lo escribe
    `install/traveler.py` el último, dentro de la carpeta nueva y antes de
    ponerla en su sitio, con la versión y el SHA-256 de cada fichero.

Un dispositivo aprovisionado antes de que existieran los sellos no tiene el de
rclone. Eso se lee como «no consta», y no consta **cuenta como pendiente**: es
la única respuesta honesta, y una actualización lo deja apuntado para siempre.

Con VeraCrypt no es igual, y a propósito. Una carpeta `VeraCrypt\\` sin sello es
la copia de una instalación que dejaban las versiones anteriores —`VeraCrypt.exe`
de una sola arquitectura—, y el vestíbulo de ese mismo dispositivo solo sabe
abrir esa disposición. Cambiarla por el portable sin cambiar a la vez el
vestíbulo dejaría la unidad sin forma de abrirse, y el vestíbulo no lo toca una
actualización de componentes (solo el paso 5 y «Añadir plataformas…»). Así que
sale como pendiente, pero marcada `asistente`: se dice, y no se toca.

Aquí viven también las rutas de los dos componentes dentro de `.prdrive/`, y
viven aquí para que haya UNA copia: `install/platforms.py` las importa en vez de
repetirlas. Es lo que garantiza que el instalador escriba donde el dispositivo
lee.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import APP_NAME, model, pins, vestibulo
from .pins import PLATAFORMAS, Plataforma

# La carpeta y el sello del runtime. `install/runtime_bin.py` los reexporta y
# `penwatch.py` repite el nombre del sello —no puede importar nada del
# proyecto—, con un test que impide que las copias se separen.
RUNTIME_SUBDIR = "runtime"
RUNTIME_STAMP = "PRDRIVE-RUNTIME"

# El de rclone es un sufijo y no un nombre fijo porque el sello acompaña a un
# fichero, no a una carpeta: `bin/x64/rclone.exe.PRDRIVE-RCLONE` y
# `bin/x64/rclone.PRDRIVE-RCLONE` conviven en el mismo sitio sin pisarse.
RCLONE_STAMP_SUFIJO = ".PRDRIVE-RCLONE"

# El del VeraCrypt de viaje va DENTRO de su carpeta, `VeraCrypt/`, en la raíz
# física: la carpeta entera se sustituye de un renombrado, y el sello con ella.
VERACRYPT_STAMP = "PRDRIVE-VERACRYPT"
# Las líneas de un fichero en ese sello: `fichero <nombre> = <sha256>`.
FICHERO_SELLO = "fichero "

RCLONE = "rclone"
PYTHON = "python"
VERACRYPT = "veracrypt"

# Lo que se enseña cuando no hay sello. No es un error: es un dispositivo de
# antes de que esto existiera, y lo que le hace falta es justo una actualización.
DESCONOCIDA = "no consta"


# ---------------------------------------------------------------------------
# Dónde vive cada componente
# ---------------------------------------------------------------------------

def _base(app_dir: Path | str | None) -> Path:
    """La carpeta del código. Sin argumento, la de ESTE dispositivo.

    Se resuelve al llamar y no al importar por lo mismo que
    `update.installed_version()` admite un `root`: el instalador pregunta por un
    volumen que no es el suyo, y `tests/_harness.sandbox()` no reengancha
    `model.APP_DIR`."""
    return Path(app_dir) if app_dir is not None else model.APP_DIR


def runtime_dir(app_dir: Path | str | None, plat: Plataforma) -> Path:
    return _base(app_dir) / RUNTIME_SUBDIR / plat.clave


def rclone_path(app_dir: Path | str | None, plat: Plataforma) -> Path:
    return _base(app_dir) / "bin" / plat.bin_dir / plat.rclone_exe


def rclone_stamp_path(app_dir: Path | str | None, plat: Plataforma) -> Path:
    ruta = rclone_path(app_dir, plat)
    return ruta.with_name(ruta.name + RCLONE_STAMP_SUFIJO)


def veracrypt_dir(raiz_fisica: Path | str) -> Path:
    """La carpeta del VeraCrypt de viaje. Cuelga de la raíz FÍSICA del volumen,
    junto al `.hc`, y no de `.prdrive/`: dentro del contenedor haría falta
    VeraCrypt para llegar a VeraCrypt."""
    return Path(raiz_fisica) / vestibulo.TRAVELER


def veracrypt_stamp_path(raiz_fisica: Path | str) -> Path:
    return veracrypt_dir(raiz_fisica) / VERACRYPT_STAMP


# ---------------------------------------------------------------------------
# Los sellos
# ---------------------------------------------------------------------------

def leer_sello(texto: str) -> dict[str, str]:
    """Un sello `clave = valor` como diccionario. Lo que no se entienda, fuera.

    Tolerante a propósito, igual que `store.read_json()`: esto lo lee la ventana
    al abrirse, y un fichero a medias —el dispositivo se extrajo a mitad de una
    escritura— tiene que significar «aquí no consta nada», no una excepción en
    el arranque."""
    datos: dict[str, str] = {}
    for linea in texto.splitlines():
        if linea.lstrip().startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        datos[clave.strip()] = valor.strip()
    return datos


def _texto(ruta: Path) -> str:
    try:
        return ruta.read_text(encoding="utf-8")
    except (OSError, ValueError):
        # ValueError además de OSError: un `.read_text` sobre un fichero a
        # medias —el dispositivo se extrajo a mitad de una escritura— no falla
        # con un error de E/S, falla con un `UnicodeDecodeError` (que ES un
        # ValueError), y es el mismo suceso que el resto de este módulo trata
        # como «no consta»: un fichero que no se puede leer como texto.
        return ""


def rclone_stamp_text(plat: Plataforma, version: str) -> str:
    """El sello de un rclone: qué versión se copió y para qué plataforma.

    Sin sha256, a diferencia del sello del runtime. Aquel lo lleva porque
    penwatch compara el TEXTO ENTERO para decidir si refresca su copia; aquí lo
    único que hay que poder contestar es «¿es la versión fijada?», y un resumen
    que nadie lee es un resumen que se queda sin comprobar."""
    return (f"# {APP_NAME} — el rclone de este dispositivo. Lo escribe el "
            f"instalador y lo lee la ventana. No lo toques.\n"
            f"rclone = {version}\n"
            f"plataforma = {plat.clave}\n")


def veracrypt_stamp_text(version: str, sha256_paquete: str,
                         ficheros: dict[str, str]) -> str:
    """El sello del VeraCrypt de viaje: de qué paquete salió y qué hay en él.

    A diferencia del de rclone, este SÍ lleva el resumen de cada fichero, y no
    para adornar: es a la vez el manifiesto de la caché del instalador
    (`install/veracrypt_bin.py` vuelve a resumir cada fichero contra él antes de
    usarlo) y el de la carpeta de la unidad, que es una copia exacta de esa
    caché. Así «qué versión es» y «qué ficheros son» salen del mismo sitio."""
    lineas = [f"# {APP_NAME} — el VeraCrypt que viaja en esta unidad. Lo escribe "
              f"el instalador y lo lee la ventana. No lo toques.",
              f"{VERACRYPT} = {version}",
              f"paquete = VeraCrypt Portable {version}.exe",
              f"sha256 = {sha256_paquete}"]
    lineas += [f"{FICHERO_SELLO}{nombre} = {resumen}"
               for nombre, resumen in sorted(ficheros.items())]
    return "\n".join(lineas) + "\n"


def veracrypt_ficheros(texto: str) -> dict[str, str]:
    """{nombre: sha256} de los ficheros que dice un sello del VeraCrypt de viaje.

    Un nombre que no sea un nombre suelto —con barra, `..` o unidad— no cuenta:
    esto se va a usar para leer y copiar, y un sello escrito a mano no puede
    llevar a nadie fuera de la carpeta."""
    salida: dict[str, str] = {}
    for clave, valor in leer_sello(texto).items():
        if not clave.startswith(FICHERO_SELLO):
            continue
        nombre = clave[len(FICHERO_SELLO):].strip()
        if (nombre and nombre not in (".", "..") and "/" not in nombre
                and "\\" not in nombre and ":" not in nombre):
            salida[nombre] = valor.lower()
    return salida


def runtime_stamp(app_dir: Path | str | None, plat: Plataforma) -> str | None:
    """El sello del runtime de esa plataforma, o None si no hay uno completo.

    Sin sello no hay runtime: `runtime_bin.extract()` lo escribe el último, así
    que una extracción interrumpida no lo tiene. Y sin intérprete tampoco."""
    d = runtime_dir(app_dir, plat)
    try:
        if not (d / plat.interprete).is_file():
            return None
        return (d / RUNTIME_STAMP).read_text(encoding="utf-8")
    except (OSError, ValueError):
        # Mismo motivo que en `_texto()`: un sello a medio escribir se lee como
        # `UnicodeDecodeError`, no como `OSError`, y el contrato de este módulo
        # —nunca lanza, la ventana lo llama en su primer pintado— es el mismo
        # para los dos.
        return None


# ---------------------------------------------------------------------------
# Qué está anticuado
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Pendiente:
    """Un componente que el dispositivo lleva y que no es el que el programa fija.

    El VeraCrypt de viaje no es de ninguna plataforma —lleva las dos
    arquitecturas de Windows a la vez— y vive fuera de `.prdrive/`: su
    `plataforma` es None y `ruta` dice dónde está su carpeta. `asistente` es el
    VeraCrypt sin sello de un dispositivo de antes: pendiente sí, pero no lo pone
    al día una actualización de componentes (ver el docstring del módulo)."""
    plataforma: Plataforma | None
    que: str                  # RCLONE | PYTHON | VERACRYPT
    lleva: str                # lo que hay ahora, o DESCONOCIDA
    deberia: str              # lo que dice common/pins.py
    ruta: Path | None = None
    asistente: bool = False

    @property
    def titulo(self) -> str:
        if self.que == VERACRYPT:
            return "VeraCrypt de la unidad"
        nombre = "rclone" if self.que == RCLONE else "Python"
        return f"{nombre} de {self.plataforma.nombre}"

    def describe(self) -> str:
        if self.asistente:
            return (f"{self.titulo}: una copia de antes, sin sello; se pone al día "
                    f"con «Añadir plataformas…» del instalador")
        return f"{self.titulo}: lleva {self.lleva}, toca {self.deberia}"


def _existe(ruta: Path) -> bool:
    try:
        return ruta.is_file()
    except OSError:
        return False        # bloqueado, desenchufado: no hay nada que decir


def rclone_pendiente(app_dir: Path | str | None,
                     plat: Plataforma) -> Pendiente | None:
    if not _existe(rclone_path(app_dir, plat)):
        return None
    sello = leer_sello(_texto(rclone_stamp_path(app_dir, plat)))
    lleva = sello.get(RCLONE) or DESCONOCIDA
    if lleva == pins.RCLONE_VERSION:
        return None
    return Pendiente(plat, RCLONE, lleva, pins.RCLONE_VERSION)


def python_pendiente(app_dir: Path | str | None,
                     plat: Plataforma) -> Pendiente | None:
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
    """El VeraCrypt de viaje de esa raíz física, si no es el que fija el programa.

    Sin carpeta —o sin ningún ejecutable de montar dentro— no lleva, y lo que no
    lleva no está anticuado. Con sello de otra versión, pendiente y actualizable.
    Sin sello es la copia de una instalación que dejaba prdrive antes: pendiente,
    marcada `asistente` (ver el docstring del módulo)."""
    if not vestibulo.traveler_ejecutables(raiz_fisica):
        return None
    carpeta = veracrypt_dir(raiz_fisica)
    lleva = leer_sello(_texto(carpeta / VERACRYPT_STAMP)).get(VERACRYPT)
    if lleva == pins.VERACRYPT_VERSION:
        return None
    return Pendiente(None, VERACRYPT, lleva or DESCONOCIDA, pins.VERACRYPT_VERSION,
                     ruta=carpeta, asistente=not lleva)


def raiz_fisica(app_dir: Path | str | None = None) -> Path | None:
    """La raíz física del contenedor VeraCrypt en el que vive ese dispositivo, o
    None si no vive en uno (o no se ve desde aquí).

    Por el id del fichero de control y la marca del vestíbulo, que es lo que une
    las dos mitades (`vestibulo.raiz_fisica()`: un stat por unidad, sin red).
    `fleet` se importa aquí dentro porque importa este módulo. Función de módulo
    para que los tests la sustituyan; nunca lanza."""
    try:
        from . import fleet
        return vestibulo.raiz_fisica(fleet.device_id(app_dir))
    except Exception:                                # noqa: BLE001
        return None


_BUSCAR = object()


def pendientes(app_dir: Path | str | None = None,
               fisica: Path | str | None | object = _BUSCAR) -> list[Pendiente]:
    """Los componentes del dispositivo que no son los que fija el programa.

    Solo mira lo que el dispositivo LLEVA. Una plataforma que no tiene no está
    anticuada: está sin instalar, y eso lo resuelve «Añadir plataformas…» del
    asistente, que es una decisión con sitio en disco de por medio y no cabe en
    un botón de un recuadro. Lo mismo el VeraCrypt de viaje: sin carpeta
    `VeraCrypt\\` no hay nada que poner al día.

    `fisica` es la raíz física del contenedor, si se sabe; sin ella se busca
    (`raiz_fisica()`), y None es «no vive en un contenedor».

    Ni lanza ni toca la red: es lo que pregunta la ventana al pintarse, y lo
    mismo que `update.pending()` a su manera."""
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


def actualizables(pends: list[Pendiente]) -> list[Pendiente]:
    """Los que puede poner al día una actualización de componentes: todos menos
    el VeraCrypt sin sello, que es cosa de «Añadir plataformas…»."""
    return [p for p in pends if not p.asistente]


def resumen(pends: list[Pendiente]) -> str:
    """Una línea por componente, para el recuadro de la ventana y el menú."""
    return "\n".join(p.describe() for p in pends)
