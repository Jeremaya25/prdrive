#!/usr/bin/env python3
"""
volumen.py — El nombre y el icono con que se ve la unidad. Sin Tkinter.

La mitad que decide de «Ajustes» → «Nombre e icono de la unidad…»; la ventana es
`ui/tk_volumen.py` y solo dibuja. El fichero que manda es el `autorun.inf` de la
raíz, y leerlo y escribirlo es cosa de `common/autorun.py`: aquí se decide qué
va dentro, en qué raíz y con qué icono.

**En qué raíz:** la de la unidad que se ENCHUFA, que es la que enseña el
Explorador al conectarla. Sin cifrar o con BitLocker es `DEVICE_ROOT`: con
BitLocker el volumen que se ve al desbloquear es el mismo, y mientras está
bloqueado Windows no lee nada de dentro. Con VeraCrypt no: `DEVICE_ROOT` es el
contenedor montado, un volumen que aparece después; la que se enchufa es la raíz
física, y se encuentra por la marca del vestíbulo (`vestibulo.raiz_fisica()`).

**Dónde va el icono:** dentro de `.prdrive/`, con `icon=.prdrive\\icono-….ico`,
para no dejar nada más en la raíz. Con VeraCrypt no hay `.prdrive/` en la raíz
física, y el que hay dentro del contenedor el Explorador no lo vería hasta
abrirlo: ahí va junto al `autorun.inf`, oculto, como el resto del vestíbulo.

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
from pathlib import Path, PureWindowsPath

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

# El nombre de uno de nuestros iconos: `fuera` es el prefijo que lleva en la
# raíz física de un contenedor; dentro de `.prdrive/` va sin él.
_NOMBRE = re.compile(f"(?P<fuera>{re.escape(autorun.PREFIJO_RAIZ)})?"
                     + re.escape(autorun.BASE_ICONO)
                     + r"-(?P<clave>[a-z]+)(?:-[0-9a-f]{8})?"
                     + re.escape(autorun.EXTENSION_ICONO), re.IGNORECASE)


@dataclass(frozen=True)
class Estado:
    """Lo que tiene puesto la unidad ahora mismo, y dónde."""
    raiz: Path              # donde vive (o viviría) el autorun.inf
    fisica: bool            # True si no es DEVICE_ROOT: la de fuera del contenedor
    nombre: str             # el `label=`, vacío si no hay
    clave: str              # qué icono es: una de MARCAS, VERACRYPT, PROPIO…
    icono: str              # el `icon=` tal cual
    veracrypt: bool         # si la unidad lleva el traveler, y su icono se ofrece

    @property
    def carpeta(self) -> Path:
        """Donde van los iconos de prdrive: `.prdrive/` si está en esta raíz, y
        si no —la física de un contenedor— la propia raíz.

        Se saca de `raiz` y del NOMBRE de `APP_DIR`, no de `APP_DIR` a secas: en
        un dispositivo es la misma carpeta, y así lo que se escribe cuelga
        siempre de la raíz que enseña la ventana."""
        return self.raiz if self.fisica else self.raiz / model.APP_DIR.name


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
    """¿Lleva la unidad el VeraCrypt de viaje? El portable de ahora
    (`VeraCrypt-x64.exe`, `-arm64.exe`) o la copia de antes (`VeraCrypt.exe`)."""
    return bool(vestibulo.traveler_ejecutables(raiz))


def _nuestro(carpetas: tuple[str, ...], nombre: str) -> re.Match | None:
    """El nombre, si es uno de nuestros iconos y está donde lo dejaría prdrive:
    en la raíz con el prefijo, o en `.prdrive/` sin él. `carpetas` son las de
    la ruta relativa a la raíz."""
    hallado = _NOMBRE.fullmatch(nombre)
    if hallado is None:
        return None
    donde = () if hallado["fuera"] else (model.APP_DIR.name.lower(),)
    return hallado if tuple(c.lower() for c in carpetas) == donde else None


def clave_de(icono: str) -> str:
    """Qué opción es ese `icon=`. Uno que no reconozca es OTRO, no NINGUNO: lo
    puso alguien, y guardar solo el nombre no tiene por qué llevárselo."""
    if not icono:
        return NINGUNO
    if autorun.es_icono_veracrypt(icono):
        return VERACRYPT
    *carpetas, nombre = PureWindowsPath(icono).parts
    hallado = _nuestro(tuple(carpetas), nombre)
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
    """El nombre del fichero del icono, tal como va dentro de `.prdrive/`. Uno
    propio lleva detrás un trozo de su hash: otro dibujo, otro nombre (ver la
    nota del módulo)."""
    cola = f"-{hashlib.sha256(datos).hexdigest()[:8]}" if datos is not None else ""
    return f"{autorun.BASE_ICONO}-{clave}{cola}{autorun.EXTENSION_ICONO}"


def ubicar(estado: Estado, nombre: str) -> tuple[Path, str]:
    """(fichero en disco, valor de `icon=`) de un icono llamado `nombre`.

    `icon=` va relativo a la raíz de la unidad, con la barra de Windows, como el
    `VeraCrypt\\VeraCrypt-x64.exe` del traveler."""
    if estado.fisica:
        nombre = autorun.PREFIJO_RAIZ + nombre
        return estado.carpeta / nombre, nombre
    return estado.carpeta / nombre, f"{estado.carpeta.name}\\{nombre}"


def _icono(estado: Estado, clave: str,
           propio: bytes | None) -> tuple[str, Path | None, bytes | None]:
    """(valor de `icon=`, fichero a dejar, lo que va dentro).

    El fichero es None cuando no hay que escribir ninguno; lo que va dentro es
    None cuando se pinta —pintar tarda y se deja para cuando haga falta—."""
    marcas = {m.clave: m for m in MARCAS}
    if clave in marcas:
        fichero, icono = ubicar(estado, nombre_icono(clave))
        return icono, fichero, None
    if clave == PROPIO:
        if propio is not None:
            fichero, icono = ubicar(estado, nombre_icono(PROPIO, propio))
            return icono, fichero, propio
        if estado.clave == PROPIO:              # el que ya tiene, sin cambiarlo
            return estado.icono, None, None
        raise VolumenError("Elige primero el .ico que quieres ponerle.")
    if clave == VERACRYPT:
        # El ejecutable que lleva de verdad: el portable de ahora no trae el
        # `VeraCrypt.exe` de antes. El que ya tenía se respeta aunque falte el
        # traveler: cambiar solo el nombre no tiene por qué pedir explicaciones
        # sobre el icono.
        hallados = vestibulo.traveler_ejecutables(estado.raiz)
        if hallados:
            return hallados[0], None, None
        if estado.clave == VERACRYPT:
            return estado.icono, None, None
        raise VolumenError("Esta unidad no lleva VeraCrypt, así que no hay "
                           "icono suyo que ponerle.")
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
    if fichero is not None and not fichero.is_file():
        # Uno que ya está no se repinta: su nombre dice lo que lleva dentro.
        if datos is None:
            datos = icons.ico(campo={m.clave: m.campo for m in MARCAS}[clave])
        try:
            fichero.write_bytes(datos)
        except OSError as e:
            raise VolumenError(f"No he podido escribir el icono en "
                               f"{fichero.parent}: {e}") from e
        nuevo = fichero
        # Dentro de `.prdrive/` ya lo esconde la carpeta; en la raíz, él mismo.
        if fichero.parent == raiz:
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

    recoger(estado, icono)
    return escrito


def recoger(estado: Estado, en_uso: str) -> list[Path]:
    """Borra los iconos de prdrive de esa unidad que no son el que se usa.

    Se mira en la raíz y en `estado.carpeta`, y solo lo que lleva el nombre de
    un icono nuestro en el sitio donde lo dejaría prdrive: lo que no puso
    prdrive no se toca. Mirar también la raíz cuando los iconos van en
    `.prdrive/` es lo que se lleva los que se dejaron ahí antes. Lo que no se
    pueda borrar se queda —son unos KB— y se vuelve a intentar la próxima vez."""
    raiz = estado.raiz
    # Por partes y no como texto: un `icon=` escrito a mano con `/` que se
    # conserva tal cual es el mismo fichero, y no se puede borrar.
    usado = tuple(p.lower() for p in PureWindowsPath(en_uso).parts) if en_uso else ()
    borrados = []
    for carpeta in dict.fromkeys((raiz, estado.carpeta)):
        relativa = carpeta.relative_to(raiz).parts
        try:
            entradas = list(carpeta.iterdir())
        except OSError:
            continue
        for entrada in entradas:
            if (_nuestro(relativa, entrada.name) is None
                    or tuple(p.lower() for p in (*relativa, entrada.name)) == usado):
                continue
            try:
                entrada.unlink()
                borrados.append(entrada)
            except OSError:
                pass
    return borrados
