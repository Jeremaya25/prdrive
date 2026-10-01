#!/usr/bin/env python3
"""El `autorun.inf` de la raíz de la unidad: su nombre y su icono. Sin Tkinter.

En Windows moderno un `autorun.inf` no ejecuta nada al conectar (AutoRun está
desactivado para extraíbles desde Windows 7), pero el Explorador sigue leyendo
dos claves cuando llega el volumen: `label`, el nombre con el que enseña la
unidad en vez de «Disco extraíble», e `icon`. Es la forma de cambiar ambos sin
tocar el sistema de ficheros, cuya etiqueta es otro asunto (en Windows puede
pedir administrador, en Linux hay que desmontar y FAT32 guarda once caracteres
en mayúsculas).

Lo escriben el traveler de VeraCrypt (`install/traveler.py`) y «Nombre e icono
de la unidad» (`ui/volumen.py`), que corre donde `install/` no viaja: por eso
vive en `common/`. Para que ninguno pise lo del otro, el fichero se EDITA: se
cambian `label` e `icon` y todo lo demás se queda como estaba.

Comprobado en un Windows 11 real (M1 de
`docs/superpowers/pruebas/2026-09-24-veracrypt-unidad-g-resultados.md`): nombre
e icono se ven solo al volver a conectar la unidad, porque el Explorador lee el
fichero cuando llega el volumen.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import APP_NAME, vestibulo

FICHERO = "autorun.inf"
SECCION = "autorun"

MAX_NOMBRE = 32
"""Longitud máxima del nombre de la unidad.

No es un límite de Windows (no hay ninguno documentado para `label`): es el de
una etiqueta NTFS.
"""

ICONO_VERACRYPT = f"{vestibulo.TRAVELER}\\{vestibulo.traveler_portatil('x64')}"
"""Icono por defecto del traveler: el ejecutable de VeraCrypt que viaja en la unidad.

Es el del portable x64 cuando no se sabe cuál hay: un icono se lee sin ejecutar
nada, así que el Explorador de un Windows ARM lo enseña igual. Quien lo escribe
pone el que haya de verdad (`vestibulo.traveler_ejecutables()`).
"""
ICONOS_VERACRYPT = tuple(
    f"{vestibulo.TRAVELER}\\{nombre}"
    for nombre in (*(vestibulo.traveler_portatil(a)
                     for a in vestibulo.TRAVELER_ARQUITECTURAS),
                   vestibulo.TRAVELER_EXE))
r"""Todos los `icon=` que pueden ser de VeraCrypt.

Los del portable y el de una instalación (`VeraCrypt\VeraCrypt.exe`), que es lo
que dejaban versiones anteriores de prdrive.
"""


def es_icono_veracrypt(icono: str) -> bool:
    """Indica si ese `icon=` es uno de los ejecutables del traveler.

    No distingue mayúsculas ni el tipo de barra, como los lee Windows.
    """
    limpio = icono.strip().replace("/", "\\").lower()
    return limpio in {i.lower() for i in ICONOS_VERACRYPT}

BASE_ICONO = "icono"
EXTENSION_ICONO = ".ico"
PREFIJO_RAIZ = f".{APP_NAME}-"
"""Prefijo de los iconos que `ui/volumen.py` deja en la raíz de un contenedor VeraCrypt.

Los iconos que pinta o copia `ui/volumen.py` se llaman `icono-….ico` y van
dentro de `.prdrive/` (sin cifrar o con BitLocker). Con VeraCrypt la raíz que
se enchufa no tiene `.prdrive/` (está dentro del contenedor y el Explorador
busca el icono antes de que nadie lo abra), así que ahí van junto al
`autorun.inf`, ocultos y con este prefijo para saber de quién son.
"""
PREFIJO_ICONO = PREFIJO_RAIZ + BASE_ICONO


def es_icono(nombre: str) -> bool:
    """Indica si ese nombre es un icono que prdrive deja en una raíz.

    Solo cuenta el de la raíz de fuera de un contenedor VeraCrypt. Lo usa
    `install/device.RUIDO` (no son contenido de nadie). Los de dentro de
    `.prdrive/` no hacen falta: esa carpeta ya es ruido.
    """
    bajo = nombre.lower()
    return bajo.startswith(PREFIJO_ICONO) and bajo.endswith(EXTENSION_ICONO)


@dataclass(frozen=True)
class Autorun:
    """Lo que dice el `autorun.inf` de una raíz; sin fichero, todo vacío.

    Args:
        ruta: El fichero, o `None` si no existe.
        etiqueta: El valor de `label`.
        icono: El valor de `icon`.
        texto: El contenido completo, ya decodificado.
    """
    ruta: Path | None = None
    etiqueta: str = ""
    icono: str = ""
    texto: str = ""


def buscar(raiz: Path | str) -> Path | None:
    """Devuelve el `autorun.inf` de esa raíz, se escriba como se escriba.

    Windows no distingue mayúsculas, pero un volumen montado en Linux puede, y
    escribir `autorun.inf` junto a un `AUTORUN.INF` dejaría dos.

    Returns:
        La ruta, o `None` si no hay fichero o no se puede mirar.
    """
    try:
        for entrada in Path(raiz).iterdir():
            if entrada.name.lower() == FICHERO and entrada.is_file():
                return entrada
    except OSError:
        pass
    return None


def _decodificar(datos: bytes) -> str:
    """Decodifica el contenido del fichero.

    VeraCrypt lo escribe en UTF-16 y aquí también, pero uno hecho a mano puede
    venir en UTF-8 o en la página de códigos de Windows. Lo que no se entiende
    se sustituye: se lee para no perderlo, no para validarlo.
    """
    if datos.startswith((b"\xff\xfe", b"\xfe\xff")):
        return datos.decode("utf-16", errors="replace")
    if datos.startswith(b"\xef\xbb\xbf"):
        return datos[3:].decode("utf-8", errors="replace")
    try:
        return datos.decode("utf-8")
    except UnicodeDecodeError:
        return datos.decode("cp1252", errors="replace")


def _cabecera(linea: str) -> str | None:
    """Devuelve la sección en minúsculas si la línea es `[sección]`, o `None`."""
    limpia = linea.strip()
    if limpia.startswith("[") and limpia.endswith("]"):
        return limpia[1:-1].strip().lower()
    return None


def _clave(linea: str) -> str | None:
    """Devuelve la clave en minúsculas de una línea `clave=valor`, o `None`."""
    limpia = linea.strip()
    if not limpia or limpia.startswith(";") or "=" not in limpia:
        return None
    return limpia.split("=", 1)[0].strip().lower()


def claves(texto: str) -> dict[str, str]:
    """Devuelve las claves de `[autorun]` con su valor.

    Si una se repite vale la primera, que es la que devuelve
    `GetPrivateProfileString`, y como ella se le quitan las comillas que la
    envuelvan.
    """
    dentro, halladas = False, {}
    for linea in texto.splitlines():
        seccion = _cabecera(linea)
        if seccion is not None:
            dentro = seccion == SECCION
            continue
        clave = _clave(linea) if dentro else None
        if clave is None:
            continue
        valor = linea.split("=", 1)[1].strip()
        if len(valor) >= 2 and valor[0] == valor[-1] == '"':
            valor = valor[1:-1]
        halladas.setdefault(clave, valor)
    return halladas


def leer(raiz: Path | str) -> Autorun:
    """Lee el nombre y el icono que tiene puestos esa raíz.

    No lanza: sin fichero, o sin poder leerlo, es lo mismo que no tener
    ninguno.
    """
    ruta = buscar(raiz)
    if ruta is None:
        return Autorun()
    try:
        texto = _decodificar(ruta.read_bytes())
    except OSError:
        return Autorun()
    halladas = claves(texto)
    return Autorun(ruta, halladas.get("label", ""), halladas.get("icon", ""), texto)


def con(texto: str, etiqueta: str, icono: str) -> str:
    """Devuelve `texto` con `label` e `icon` puestos, o quitados si van vacíos.

    Todo lo demás queda tal cual: otras claves, otras secciones, comentarios.
    Las dos claves van justo debajo de `[autorun]`, en ese orden (donde las
    pone VeraCrypt); sin esa sección se añade una arriba.

    Returns:
        El texto nuevo, o una cadena vacía si no queda ninguna clave en todo el
        fichero (no hay nada que decirle al Explorador; `escribir()` lo
        entiende como borrarlo).
    """
    nuevas = [f"{k}={v}" for k, v in (("label", etiqueta), ("icon", icono)) if v]
    salida: list[str] = []
    dentro = puestas = False
    for linea in texto.splitlines():
        seccion = _cabecera(linea)
        if seccion is not None:
            dentro = seccion == SECCION
            salida.append(linea)
            if dentro and not puestas:
                salida += nuevas
                puestas = True
            continue
        if dentro and _clave(linea) in ("label", "icon"):
            continue
        salida.append(linea)
    if not puestas and nuevas:
        salida = [f"[{SECCION}]", *nuevas, *salida]
    if not any(_clave(linea) for linea in salida):
        return ""
    return "\n".join(salida).rstrip("\n") + "\n"


def sin(texto: str, quitar: Callable[[str, str], bool]) -> str:
    """Devuelve `texto` sin las claves de `[autorun]` que `quitar` rechaza.

    Es la otra mitad de `con()`: quien escribió unas claves las retira cuando
    dejan de ser verdad sin llevarse las de nadie más. Todo lo demás queda tal
    cual.

    Args:
        quitar: Recibe la clave (en minúsculas) y su valor; si devuelve True,
            esa línea se borra.
    """
    salida: list[str] = []
    dentro = False
    for linea in texto.splitlines():
        seccion = _cabecera(linea)
        if seccion is not None:
            dentro = seccion == SECCION
        elif dentro:
            clave = _clave(linea)
            if clave is not None and quitar(clave, linea.split("=", 1)[1].strip()):
                continue
        salida.append(linea)
    return "\n".join(salida) + "\n" if salida else ""


def escribir(raiz: Path | str, texto: str) -> Path | None:
    """Deja `texto` como el `autorun.inf` de esa raíz; vacío, lo borra.

    Va en UTF-16, como el de VeraCrypt (`_wfopen(…, L"w,ccs=UNICODE")`), que es
    lo que el Explorador sabe leer cuando el nombre lleva acentos, y con CRLF.

    Returns:
        El fichero escrito, o `None` si no queda fichero.

    Raises:
        OSError: Si no se puede escribir o borrar el fichero.
    """
    actual = buscar(raiz)
    if not texto.strip():
        if actual is not None:
            actual.unlink()
        return None
    destino = actual or Path(raiz) / FICHERO
    destino.write_text(texto, encoding="utf-16", newline="\r\n")
    return destino
