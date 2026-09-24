#!/usr/bin/env python3
"""
autorun.py — El `autorun.inf` de la raíz de la unidad: su nombre y su icono. Sin Tkinter.

En Windows moderno un `autorun.inf` **no ejecuta nada** al conectar —AutoRun lleva
desactivado para las unidades extraíbles desde Windows 7—, pero el Explorador
sigue leyendo dos de sus claves cuando llega el volumen: `label`, el nombre con
el que enseña la unidad en vez de «Disco extraíble», e `icon`, su icono. Es la
forma de cambiar las dos cosas sin tocar el sistema de ficheros: su etiqueta es
otro asunto —en Windows puede pedir administrador, en Linux hay que desmontar, y
FAT32 guarda once caracteres en mayúsculas—, y aquí cabe «Pendrive de Pere».

Lo escriben dos: el traveler de VeraCrypt (`install/traveler.py`), que añade las
órdenes de montar y desmontar, y «Nombre e icono de la unidad» (`ui/volumen.py`)
desde el propio dispositivo. Vive en `common/` porque ese segundo corre donde
`install/` no viaja. Y para que ninguno pise lo del otro, aquí el fichero se
**edita**: se cambian `label` e `icon` y todo lo demás se queda como estaba.

Comprobado en un Windows 11 de verdad (la M1 de
`docs/superpowers/pruebas/2026-09-24-veracrypt-unidad-g-resultados.md`): nombre e
icono se ven, pero **solo al volver a conectar la unidad**, porque el Explorador
lee el fichero cuando llega el volumen.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import APP_NAME, vestibulo

FICHERO = "autorun.inf"
SECCION = "autorun"

# Lo más largo que se deja poner de nombre. No es un límite de Windows —no hay
# ninguno documentado para `label`—: es el de una etiqueta NTFS.
MAX_NOMBRE = 32

# El icono del traveler: el propio ejecutable de VeraCrypt que viaja en la unidad.
ICONO_VERACRYPT = f"{vestibulo.TRAVELER}\\{vestibulo.TRAVELER_EXE}"

# Los iconos que pinta o copia `ui/volumen.py` van en la raíz, junto a este
# fichero, ocultos y con este prefijo. Van en la raíz y no en `.prdrive/` porque
# con VeraCrypt la raíz física no tiene `.prdrive/`: está dentro del contenedor, y
# el Explorador lee el icono antes de que nadie lo abra.
PREFIJO_ICONO = f".{APP_NAME}-icono"
EXTENSION_ICONO = ".ico"


def es_icono(nombre: str) -> bool:
    """¿Es uno de los iconos que deja aquí prdrive? Para `install/device.RUIDO`
    —no son contenido de nadie— y para saber cuáles se pueden recoger."""
    bajo = nombre.lower()
    return bajo.startswith(PREFIJO_ICONO) and bajo.endswith(EXTENSION_ICONO)


@dataclass(frozen=True)
class Autorun:
    """Lo que dice el `autorun.inf` de una raíz. Sin fichero, todo vacío."""
    ruta: Path | None = None
    etiqueta: str = ""
    icono: str = ""
    texto: str = ""


def buscar(raiz: Path | str) -> Path | None:
    """El `autorun.inf` de esa raíz, se escriba como se escriba.

    Windows no distingue mayúsculas, pero un volumen montado en Linux puede
    hacerlo, y escribir `autorun.inf` junto a un `AUTORUN.INF` dejaría dos.
    None si no hay o no se puede mirar."""
    try:
        for entrada in Path(raiz).iterdir():
            if entrada.name.lower() == FICHERO and entrada.is_file():
                return entrada
    except OSError:
        pass
    return None


def _decodificar(datos: bytes) -> str:
    """El texto del fichero. VeraCrypt lo escribe en UTF-16 y aquí también, pero
    uno escrito a mano puede venir en UTF-8 o en la página de códigos de Windows.
    Lo que no se entiende se sustituye: esto se lee para no perderlo, no para
    validarlo."""
    if datos.startswith((b"\xff\xfe", b"\xfe\xff")):
        return datos.decode("utf-16", errors="replace")
    if datos.startswith(b"\xef\xbb\xbf"):
        return datos[3:].decode("utf-8", errors="replace")
    try:
        return datos.decode("utf-8")
    except UnicodeDecodeError:
        return datos.decode("cp1252", errors="replace")


def _cabecera(linea: str) -> str | None:
    """El nombre de la sección si la línea es `[sección]`, en minúsculas."""
    limpia = linea.strip()
    if limpia.startswith("[") and limpia.endswith("]"):
        return limpia[1:-1].strip().lower()
    return None


def _clave(linea: str) -> str | None:
    """La clave de una línea `clave=valor`, en minúsculas; None si es otra cosa."""
    limpia = linea.strip()
    if not limpia or limpia.startswith(";") or "=" not in limpia:
        return None
    return limpia.split("=", 1)[0].strip().lower()


def claves(texto: str) -> dict[str, str]:
    """Las claves de `[autorun]` con su valor. Si una se repite vale la primera,
    que es la que devuelve `GetPrivateProfileString`, y como ella se le quitan
    las comillas que la envuelvan."""
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
    """Qué nombre e icono tiene puestos esa raíz. No lanza: sin fichero, o sin
    poder leerlo, es lo mismo que no tener ninguno."""
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
    """`texto` con `label` e `icon` puestos a esos valores —o quitados, si van
    vacíos— y todo lo demás tal cual: otras claves, otras secciones, comentarios.

    Las dos van justo debajo de `[autorun]`, en ese orden, que es donde las pone
    VeraCrypt; sin esa sección se añade una arriba. Si no queda ninguna clave en
    todo el fichero devuelve la cadena vacía: no hay nada que decirle al
    Explorador, y `escribir()` lo entiende como borrarlo."""
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


def escribir(raiz: Path | str, texto: str) -> Path | None:
    """Deja `texto` como el `autorun.inf` de esa raíz; vacío, lo borra.
    Devuelve lo escrito, o None si no queda fichero. Lanza OSError.

    En UTF-16, como el de VeraCrypt (`_wfopen(…, L"w,ccs=UNICODE")`): es lo que
    el Explorador sabe leer cuando el nombre lleva acentos. Y con CRLF, que es lo
    que lee Windows, venga de donde venga quien lo escribe."""
    actual = buscar(raiz)
    if not texto.strip():
        if actual is not None:
            actual.unlink()
        return None
    destino = actual or Path(raiz) / FICHERO
    destino.write_text(texto, encoding="utf-16", newline="\r\n")
    return destino
