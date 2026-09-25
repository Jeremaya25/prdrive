#!/usr/bin/env python3
"""
descarga.py — Lo que comparten los descargadores del instalador: reintentar lo
que falla por la red, y leer un SHA256SUMS.

`rclone_bin` y `runtime_bin` bajan cosas que se van a ejecutar dentro del
dispositivo, con el mismo contrato: el archivo se resume EN MEMORIA contra la
suma que publica su autor antes de escribir nada, y si no cuadra la caché se
queda como estaba. Este módulo no toca ese contrato; pone dos piezas que los dos
repetían o les faltaban, y que servirán igual a cualquier otro descargador con
la misma forma:

  * `con_reintentos()` — un `fetch()` que se queda sin respuesta una vez no
    tumba el paso entero. Antes, UN tiempo de espera leyendo el zip de rclone de
    una plataforma que ni siquiera era la de este equipo abortaba la instalación
    (#49), sin segundo intento.
  * `suma_en()` / `sumas()` — sacar la línea de un SHA256SUMS, y leerlo de un
    fichero puesto a mano junto al archivo cuando lo hay: es lo que permite dejar
    el zip y su SHA256SUMS bajados con el navegador y comprobarlos SIN red.

**Qué se reintenta y qué no.** Solo lo que otro intento podría no tener: un
tiempo de espera, una conexión cortada, una transferencia incompleta, un 5xx.
Nunca un 404 —la URL no va a aparecer—, ni un certificado que no se deja
verificar —es un proxy que intercepta, o un reloj mal puesto, y reintentar solo
lo escondería detrás de medio minuto de espera—, **ni una suma que no cuadra**.
Esa última es deliberada: `fetch()` devuelve el cuerpo entero o falla
(`http.client` lanza `IncompleteRead` si llega menos de lo anunciado), así que un
archivo que llega completo y no es el publicado no es un corte de red: es otra
cosa —un portal cautivo, un proxy que sirve una página de error o algo viejo—, y
repetir hasta que un intento cuadre sería exactamente la forma de no enterarse.
Eso se le dice a quien instala, con las dos sumas, y el reintento lo decide él.
"""

from __future__ import annotations

import http.client
import ssl
import time
import urllib.error
from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")
Progreso = Callable[[str], None]

# Las esperas ENTRE intentos, crecientes: la primera para un corte de un momento,
# la segunda para una red que se está recuperando. Tres intentos en total; con
# los 60 s por lectura de los `fetch()`, una red que se queda muda hace rendirse
# en unos tres minutos y medio por fichero, no al primer silencio.
ESPERAS: tuple[float, ...] = (5.0, 15.0)
INTENTOS = len(ESPERAS) + 1

# Lo que puede salir de un `fetch()` cuando falla la red, para el `except` de
# quien llama: `urllib.error.URLError` es un OSError, y un cuerpo cortado a
# medias es un `http.client.IncompleteRead`, que no lo es. Lo que no esté aquí
# —un fallo del propio código, un test que pide una URL que no esperaba— sale
# tal cual.
FALLOS_DE_RED = (OSError, http.client.HTTPException)

# El nombre con que publican sus sumas rclone y python-build-standalone, y con
# el que se busca la copia puesta a mano junto al archivo.
SUMAS = "SHA256SUMS"


def esperar(segundos: float) -> None:
    """La pausa entre dos intentos.

    De módulo a propósito, como `rclone_bin.fetch()`: los tests la sustituyen y
    ninguno duerme de verdad."""
    time.sleep(segundos)


def reintentable(e: BaseException) -> bool:
    """¿Es un fallo de la red que otro intento podría no tener?"""
    if isinstance(e, urllib.error.HTTPError):
        # Un 5xx es el servidor pasándolo mal; 408 y 429 lo dicen expresamente.
        # Cualquier otro 4xx —un 404, un 403— va a contestar lo mismo mañana.
        return e.code >= 500 or e.code in (408, 429)
    if isinstance(e, urllib.error.URLError):
        # `urlopen` envuelve aquí lo que pasa al CONECTAR. Un certificado que no
        # se deja verificar no es un corte: es otra cosa que contesta en lugar
        # del servidor, y no se insiste.
        return not isinstance(e.reason, ssl.SSLCertVerificationError)
    # Lo que pasa LEYENDO llega sin envolver: el tiempo de espera del #49
    # (TimeoutError, un OSError), una conexión reiniciada, un registro TLS
    # cortado (ssl.SSLError, también OSError) o un cuerpo más corto de lo que
    # anunciaba su Content-Length (http.client.IncompleteRead). `fetch()` solo
    # habla con la red, así que cualquier OSError suyo es de la red.
    return isinstance(e, FALLOS_DE_RED)


def con_reintentos(pedir: Callable[[], T], que: str = "",
                   progreso: Progreso | None = None) -> T:
    """`pedir()`, hasta `INTENTOS` veces mientras falle por la red.

    Lo que no es de red (`reintentable()`) sale a la primera y tal cual. Tras el
    último intento sale también tal cual, la última excepción: quien llama sabe
    qué estaba pidiendo y lo cuenta mejor, y `describir()` añade cuántas veces
    se ha probado. `pedir` es una función sin argumentos para que quien llama
    resuelva su `fetch` de módulo en cada intento, y los tests puedan
    sustituirlo."""
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
    """El error como se le cuenta a quien instala: si era de red, cuántas veces
    se ha intentado. Así se distingue «falló una vez» de «falló tres»."""
    return f"{e} (probado {INTENTOS} veces)" if reintentable(e) else str(e)


def suma_en(texto: str, nombre: str) -> str | None:
    """La suma de `nombre` en el texto de un SHA256SUMS, o None si no está.

    El formato es «<suma>  <fichero>»; el '*' delante del nombre es la marca de
    «modo binario» de coreutils, que no usan ni rclone ni python-build-standalone
    pero que no cuesta nada tolerar. Las demás líneas —la cabecera y la firma
    PGP con que rclone envuelve el suyo— no tienen esa forma y se saltan; y la
    suma tiene que ser una suma, 64 cifras hexadecimales, para que «Hash: SHA256»
    no pase por la de un fichero que se llamara así."""
    for linea in texto.splitlines():
        partes = linea.split()
        if (len(partes) == 2 and partes[1].lstrip("*") == nombre
                and len(partes[0]) == 64
                and all(ch in "0123456789abcdefABCDEF" for ch in partes[0])):
            return partes[0].lower()
    return None


def sumas(url: str, local: Path, pedir: Callable[[], bytes],
          progreso: Progreso | None = None) -> tuple[str, str]:
    """El texto del SHA256SUMS y de dónde ha salido: (texto, origen).

    Primero el que haya puesto alguien a mano en `local` —el mismo fichero de la
    misma URL, bajado con el navegador—, y solo si no está, la red, con
    reintentos. Es lo que hace que un archivo dejado a mano se pueda comprobar
    sin red. No debilita nada: la suma de la red también viaja desde el mismo
    servidor que el archivo, así que las dos defienden de lo mismo (un corte, un
    proxy, una caché vieja) y de nada más. Un SHA256SUMS equivocado —de otra
    versión, o una página de error guardada con ese nombre— no hace pasar nada:
    los nombres de archivo llevan la versión dentro, y sin su línea no hay
    suma."""
    try:
        if local.is_file():
            return local.read_text(encoding="utf-8", errors="replace"), str(local)
    except OSError:
        pass
    datos = con_reintentos(pedir, f"Leer {url}", progreso)
    return datos.decode("utf-8", "replace"), url
