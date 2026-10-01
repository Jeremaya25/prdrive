#!/usr/bin/env python3
"""Lo que comparten los descargadores del instalador: reintentos y SHA256SUMS.

`rclone_bin` y `runtime_bin` bajan cosas que se van a ejecutar dentro del
dispositivo, con el mismo contrato: el archivo se resume EN MEMORIA contra la
suma que publica su autor antes de escribir nada, y si no cuadra la caché se
queda como estaba. Este módulo no toca ese contrato; aporta dos piezas que
sirven igual a cualquier otro descargador con la misma forma (el de VeraCrypt
las usa):
- `con_reintentos()`: un `fetch()` que se queda sin respuesta una vez no tumba
  el paso entero, aunque sea el zip de rclone de una plataforma que ni siquiera
  es la de este equipo.
- `suma_en()` y `sumas()`: sacar la línea de un SHA256SUMS y leerlo de un
  fichero puesto a mano junto al archivo, que permite dejar el zip y su
  SHA256SUMS bajados con el navegador y comprobarlos SIN red.

Qué se reintenta y qué no: solo lo que otro intento podría no tener (un tiempo
de espera, una conexión cortada, una transferencia incompleta, un 5xx). Nunca
un 404 (la URL no va a aparecer), ni un certificado que no se deja verificar
(es un proxy que intercepta o un reloj mal puesto, y reintentar solo lo
escondería detrás de medio minuto de espera), ni una suma que no cuadra. Esto
último es deliberado: `fetch()` devuelve el cuerpo entero o falla
(`http.client` lanza `IncompleteRead` si llega menos de lo anunciado), así que
un archivo que llega completo y no es el publicado no es un corte de red sino
otra cosa (un portal cautivo, un proxy que sirve una página de error, algo
viejo), y repetir hasta que un intento cuadre sería la forma de no enterarse.
Se le dice a quien instala, con las dos sumas, y el reintento lo decide él.
"""

from __future__ import annotations

import http.client
import ssl
import time
import urllib.error
from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")
"""Tipo genérico del valor que devuelve `con_reintentos`."""
Progreso = Callable[[str], None]
"""Función que recibe cada mensaje de avance."""

ESPERAS: tuple[float, ...] = (5.0, 15.0)
"""Segundos de espera ENTRE intentos, crecientes.

La primera es para un corte de un momento y la segunda para una red que se está
recuperando. Son tres intentos en total; con los 60 s por lectura de los
`fetch()`, una red que se queda muda hace rendirse en unos tres minutos y medio
por fichero y no al primer silencio.
"""
INTENTOS = len(ESPERAS) + 1
"""Número de intentos en total."""

FALLOS_DE_RED = (OSError, http.client.HTTPException)
"""Excepciones que puede dejar un `fetch()` cuando falla la red.

Es lo que captura quien llama: `urllib.error.URLError` es un `OSError` y un
cuerpo cortado a medias es un `http.client.IncompleteRead`, que no lo es. Lo
que no esté aquí (un fallo del propio código, un test que pide una URL
inesperada) sale tal cual.
"""

SUMAS = "SHA256SUMS"
"""Nombre con que publican sus sumas rclone y python-build-standalone.

También es el nombre con el que se busca la copia puesta a mano junto al
archivo.
"""


def esperar(segundos: float) -> None:
    """Hace la pausa entre dos intentos.

    Es de módulo a propósito, como `rclone_bin.fetch()`: los tests la
    sustituyen y ninguno duerme de verdad.
    """
    time.sleep(segundos)


def reintentable(e: BaseException) -> bool:
    """Indica si es un fallo de la red que otro intento podría no tener."""
    if isinstance(e, urllib.error.HTTPError):
        # Un 5xx es el servidor pasándolo mal; 408 y 429 lo dicen expresamente.
        # Cualquier otro 4xx (404, 403) contestará lo mismo mañana.
        return e.code >= 500 or e.code in (408, 429)
    if isinstance(e, urllib.error.URLError):
        # `urlopen` envuelve aquí lo que pasa al CONECTAR. Un certificado que
        # no se deja verificar no es un corte sino otra cosa que contesta en
        # lugar del servidor: no se insiste.
        return not isinstance(e.reason, ssl.SSLCertVerificationError)
    # Lo que pasa LEYENDO llega sin envolver: un tiempo de espera
    # (`TimeoutError`), una conexión reiniciada, un registro TLS cortado
    # (`ssl.SSLError`) o un cuerpo más corto que su `Content-Length`
    # (`IncompleteRead`). `fetch()` solo habla con la red, así que cualquier
    # `OSError` suyo es de la red.
    return isinstance(e, FALLOS_DE_RED)


def con_reintentos(pedir: Callable[[], T], que: str = "",
                   progreso: Progreso | None = None) -> T:
    """Ejecuta `pedir()`, hasta `INTENTOS` veces mientras falle por la red.

    Lo que no es de red (`reintentable()`) sale a la primera y tal cual. Tras
    el último intento sale también la última excepción tal cual: quien llama
    sabe qué estaba pidiendo y lo cuenta mejor, y `describir()` añade cuántas
    veces se ha probado. `pedir` es una función sin argumentos para que quien
    llama resuelva su `fetch` de módulo en cada intento y los tests puedan
    sustituirlo.

    Args:
        pedir: La petición.
        que: Qué se pide, para los mensajes de avance.
        progreso: Recibe un mensaje antes de cada reintento.
    """
    for n, espera in enumerate((*ESPERAS, None), start=1):
        try:
            return pedir()
        except Exception as e:
            if espera is None or not reintentable(e):
                raise
            if progreso:
                progreso(f"{que or 'La descarga'} ha fallado ({e}); intento "
                         f"{n + 1} de {INTENTOS} dentro de {espera:g} s")
            esperar(espera)
    raise AssertionError("inalcanzable")          # el último intento sale arriba


def describir(e: BaseException) -> str:
    """Devuelve el error como se le cuenta a quien instala.

    Si era de red añade cuántas veces se ha intentado, para distinguir «falló
    una vez» de «falló tres».
    """
    return f"{e} (probado {INTENTOS} veces)" if reintentable(e) else str(e)


def suma_en(texto: str, nombre: str) -> str | None:
    """Devuelve la suma de `nombre` en el texto de un SHA256SUMS.

    El formato es «<suma>  <fichero>»; el `*` delante del nombre es la marca de
    «modo binario» de coreutils, que no usan ni rclone ni
    python-build-standalone pero no cuesta nada tolerar. Las demás líneas (la
    cabecera y la firma PGP con que rclone envuelve el suyo) no tienen esa
    forma y se saltan; y la suma tiene que ser una suma, 64 cifras
    hexadecimales, para que «Hash: SHA256» no pase por la de un fichero que se
    llamara así.

    Returns:
        La suma en minúsculas, o `None` si no está.
    """
    for linea in texto.splitlines():
        partes = linea.split()
        if (len(partes) == 2 and partes[1].lstrip("*") == nombre
                and len(partes[0]) == 64
                and all(ch in "0123456789abcdefABCDEF" for ch in partes[0])):
            return partes[0].lower()
    return None


def sumas(url: str, local: Path, pedir: Callable[[], bytes],
          progreso: Progreso | None = None) -> tuple[str, str]:
    """Devuelve el texto del SHA256SUMS y de dónde ha salido.

    Primero el que haya puesto alguien a mano en `local` (el mismo fichero de
    la misma URL, bajado con el navegador) y solo si no está, la red, con
    reintentos. Así un archivo dejado a mano se puede comprobar sin red. No
    debilita nada: la suma de la red viaja desde el mismo servidor que el
    archivo, así que las dos defienden de lo mismo (un corte, un proxy, una
    caché vieja) y de nada más. Un SHA256SUMS equivocado (de otra versión, o
    una página de error guardada con ese nombre) no hace pasar nada: los
    nombres de archivo llevan la versión dentro y sin su línea no hay suma.

    Returns:
        `(texto, origen)`: el origen es la ruta local o la URL.
    """
    try:
        if local.is_file():
            return local.read_text(encoding="utf-8", errors="replace"), str(local)
    except OSError:
        pass
    datos = con_reintentos(pedir, f"Leer {url}", progreso)
    return datos.decode("utf-8", "replace"), url
