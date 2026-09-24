#!/usr/bin/env python3
"""
volumen.py — El nombre y el icono con que se ve la unidad. Sin Tkinter.

La mitad que decide de «Ajustes» → «Nombre e icono de la unidad…»; la ventana es
`ui/tk_volumen.py` y solo dibuja. El fichero que manda es el `autorun.inf` de la
raíz, y leerlo y escribirlo es cosa de `common/autorun.py`: aquí se decide qué
va dentro, en qué raíz y con qué icono.

**En qué raíz:** la de la unidad que se ENCHUFA, que es la que enseña el
Explorador al conectarla. Sin cifrar o con BitLocker es `DEVICE_ROOT`. Con
VeraCrypt no: esa es el contenedor montado, un volumen que aparece después; la
que se enchufa es la raíz física, y se encuentra por la marca del vestíbulo
(`vestibulo.raiz_fisica()`).

**El icono:** la marca de prdrive pintada aquí (`icons.ico()`) en uno de cinco
colores —para distinguir un dispositivo de otro a simple vista, que es para lo
que sirve cambiarlo—, un `.ico` del usuario, el de VeraCrypt si la unidad lo
lleva, o ninguno. Qué hay elegido se lee del propio `icon=`: el nombre del
fichero lleva la clave (`.prdrive-icono-verde.ico`), así que no hay un estado
aparte que pueda contradecir al fichero que manda.

**El nombre del fichero cambia con el dibujo.** El Explorador guarda los iconos
en caché por ruta: reescribir el mismo fichero con otro dibujo puede seguir
enseñando el de antes. Por eso cada color tiene su nombre, uno propio lleva
detrás un trozo de su hash, y al guardar se recogen los que ya no se usan.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from common import autorun, fleet, model, store, vestibulo

from . import icons


class VolumenError(Exception):
    """Lo que impide guardar, dicho para el usuario."""


@dataclass(frozen=True)
class Opcion:
    """Un color de la marca: la clave va en el nombre del fichero."""
    clave: str
    nombre: str
    campo: str


MARCAS = tuple(Opcion(clave, nombre, icons.CAMPOS[clave]) for clave, nombre in (
    ("azul", "Azul"), ("verde", "Verde"), ("granate", "Granate"),
    ("morado", "Morado"), ("grafito", "Grafito")))

VERACRYPT = "veracrypt"     # el ejecutable del traveler
PROPIO = "propio"           # un .ico que trae el usuario
NINGUNO = "ninguno"         # sin `icon=`: el que ponga Windows
OTRO = "otro"               # un `icon=` que no puso prdrive: se deja mientras no se cambie

# Un .ico de verdad cabe de sobra: el de la marca, con siete tamaños, son 43 KB, y
# uno con el de 256 px sin comprimir anda por los 400. Esto es para no copiar a
# la unidad una foto de 50 MB porque se llamaba .ico.
MAX_ICO = 4 * 1024 * 1024

_NOMBRE = re.compile(re.escape(autorun.PREFIJO_ICONO)
                     + r"-(?P<clave>[a-z]+)(?:-[0-9a-f]{8})?"
                     + re.escape(autorun.EXTENSION_ICONO) + "$", re.IGNORECASE)


@dataclass(frozen=True)
class Estado:
    """Lo que tiene puesto la unidad ahora mismo, y dónde."""
    raiz: Path              # donde vive (o viviría) el autorun.inf
    fisica: bool            # True si no es DEVICE_ROOT: la de fuera del contenedor
    nombre: str             # el `label=`, vacío si no hay
    clave: str              # qué icono es: una de MARCAS, VERACRYPT, PROPIO…
    icono: str              # el `icon=` tal cual
    veracrypt: bool         # si la unidad lleva el traveler, y su icono se ofrece


# ---------------------------------------------------------------------------
# Leer
# ---------------------------------------------------------------------------

def raiz_del_volumen() -> tuple[Path, bool]:
    """(raíz de la unidad que se enchufa, si es la física de un contenedor).

    Sin vestíbulo que encontrar —no hay contenedor, o no se ve desde aquí— es
    `DEVICE_ROOT`, y la ventana enseña la ruta: nadie escribe a ciegas."""
    fisica = vestibulo.raiz_fisica(fleet.device_id())
    if fisica is not None:
        return Path(fisica), True
    return Path(model.DEVICE_ROOT), False


def lleva_veracrypt(raiz: Path) -> bool:
    try:
        return (Path(raiz) / vestibulo.TRAVELER / vestibulo.TRAVELER_EXE).is_file()
    except OSError:
        return False


def clave_de(icono: str) -> str:
    """Qué opción es ese `icon=`. Uno que no reconozca es OTRO, no NINGUNO: lo
    puso alguien, y guardar solo el nombre no tiene por qué llevárselo."""
    if not icono:
        return NINGUNO
    if icono.lower() == autorun.ICONO_VERACRYPT.lower():
        return VERACRYPT
    hallado = _NOMBRE.match(icono)
    if hallado:
        clave = hallado["clave"].lower()
        if clave == PROPIO or clave in {m.clave for m in MARCAS}:
            return clave
    return OTRO


def leer() -> Estado:
    """Lo que hay puesto. No lanza: sin fichero es «sin nombre y sin icono»."""
    raiz, fisica = raiz_del_volumen()
    actual = autorun.leer(raiz)
    return Estado(raiz, fisica, actual.etiqueta, clave_de(actual.icono),
                  actual.icono, lleva_veracrypt(raiz))


# ---------------------------------------------------------------------------
# Validar lo que llega del formulario
# ---------------------------------------------------------------------------

def revisar_nombre(texto: str) -> str:
    """El nombre tal como se va a guardar. Vacío vale: es quitarlo."""
    nombre = texto.strip()
    # `isprintable()` y no «menor que 32»: U+2028 o U+0085 no son de control en
    # ASCII, pero `splitlines()` —y con él `common/autorun.py`— los toma por
    # saltos de línea, y el nombre se partiría en dos al releer el fichero.
    if not all(c == " " or c.isprintable() for c in nombre):
        raise VolumenError("El nombre no puede llevar saltos de línea, "
                           "tabuladores ni otros caracteres de control.")
    if len(nombre) > autorun.MAX_NOMBRE:
        raise VolumenError(f"El nombre tiene {len(nombre)} caracteres, y el de "
                           f"una unidad cabe en {autorun.MAX_NOMBRE}.")
    return nombre


def leer_ico(ruta: Path | str) -> bytes:
    """Los bytes de un `.ico` que trae el usuario, si lo son.

    Se mira la cabecera (ICONDIR: dos ceros, tipo 1 —icono—, al menos una
    imagen) y no la extensión: un PNG renombrado a `.ico` no es un icono."""
    ruta = Path(ruta)
    try:
        if ruta.stat().st_size > MAX_ICO:
            raise VolumenError(f"{ruta.name} ocupa demasiado para ser un icono "
                               f"(más de {MAX_ICO // 1024 ** 2} MB).")
        datos = ruta.read_bytes()
    except OSError as e:
        raise VolumenError(f"No he podido leer {ruta}: {e}") from e
    if (len(datos) < 6 + 16 or datos[:4] != b"\x00\x00\x01\x00"
            or int.from_bytes(datos[4:6], "little") == 0):
        raise VolumenError(f"{ruta.name} no es un icono de Windows (.ico).")
    return datos


# ---------------------------------------------------------------------------
# Guardar
# ---------------------------------------------------------------------------

def nombre_icono(clave: str, datos: bytes | None = None) -> str:
    """El nombre del fichero del icono. Uno propio lleva detrás un trozo de su
    hash: otro dibujo, otro nombre (ver la nota del módulo)."""
    cola = f"-{hashlib.sha256(datos).hexdigest()[:8]}" if datos is not None else ""
    return f"{autorun.PREFIJO_ICONO}-{clave}{cola}{autorun.EXTENSION_ICONO}"


def _icono(estado: Estado, clave: str,
           propio: bytes | None) -> tuple[str, str | None, bytes | None]:
    """(valor de `icon=`, fichero a dejar en la raíz, lo que va dentro).

    El fichero es None cuando no hay que escribir ninguno; lo que va dentro es
    None cuando se pinta —pintar tarda y se deja para cuando haga falta—."""
    marcas = {m.clave: m for m in MARCAS}
    if clave in marcas:
        nombre = nombre_icono(clave)
        return nombre, nombre, None
    if clave == PROPIO:
        if propio is not None:
            nombre = nombre_icono(PROPIO, propio)
            return nombre, nombre, propio
        if estado.clave == PROPIO:              # el que ya tiene, sin cambiarlo
            return estado.icono, None, None
        raise VolumenError("Elige primero el .ico que quieres ponerle.")
    if clave == VERACRYPT:
        # El que ya tenía se respeta aunque falte el traveler: cambiar solo el
        # nombre no tiene por qué pedir explicaciones sobre el icono.
        if not estado.veracrypt and estado.clave != VERACRYPT:
            raise VolumenError("Esta unidad no lleva VeraCrypt, así que no hay "
                               "icono suyo que ponerle.")
        return autorun.ICONO_VERACRYPT, None, None
    if clave == OTRO:
        return estado.icono, None, None
    if clave == NINGUNO:
        return "", None, None
    raise VolumenError(f"No sé qué icono es «{clave}».")


def guardar(estado: Estado, nombre: str, clave: str,
            propio: bytes | None = None) -> Path | None:
    """Pone ese nombre y ese icono. Devuelve el `autorun.inf` escrito, o None si
    no ha quedado ninguno (sin nombre y sin icono no hay nada que decir).

    El orden es para no dejar nunca el `autorun.inf` apuntando a un icono que no
    está: primero el icono, luego el fichero, y solo al final se recogen los
    iconos que ya no se usan. Lanza VolumenError."""
    nombre = revisar_nombre(nombre)
    icono, fichero, datos = _icono(estado, clave, propio)
    raiz = estado.raiz

    nuevo = None
    if fichero is not None and not (raiz / fichero).is_file():
        # Uno que ya está no se repinta: su nombre dice lo que lleva dentro.
        if datos is None:
            datos = icons.ico(campo={m.clave: m.campo for m in MARCAS}[clave])
        nuevo = raiz / fichero
        try:
            nuevo.write_bytes(datos)
        except OSError as e:
            raise VolumenError(f"No he podido escribir el icono en {raiz}: {e}") from e
        store.hide(nuevo)

    actual = autorun.leer(raiz)
    try:
        escrito = autorun.escribir(raiz, autorun.con(actual.texto, nombre, icono))
    except OSError as e:
        if nuevo is not None:
            try:
                nuevo.unlink()
            except OSError:
                pass
        destino = actual.ruta or raiz / autorun.FICHERO
        raise VolumenError(f"No he podido escribir {destino}: {e}") from e

    recoger(raiz, icono)
    return escrito


def recoger(raiz: Path, en_uso: str) -> list[Path]:
    """Borra los iconos de prdrive de esa raíz que no son el que se usa.

    Solo los que empiezan por el prefijo, en la raíz y nada más: lo que no puso
    prdrive no se toca. Lo que no se pueda borrar se queda —es un fichero
    oculto de unos KB— y se vuelve a intentar la próxima vez."""
    borrados = []
    try:
        entradas = list(Path(raiz).iterdir())
    except OSError:
        return borrados
    for entrada in entradas:
        if not autorun.es_icono(entrada.name) or entrada.name.lower() == en_uso.lower():
            continue
        try:
            entrada.unlink()
            borrados.append(entrada)
        except OSError:
            pass
    return borrados
