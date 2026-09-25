#!/usr/bin/env python3
"""
Reintentar lo que falla por la red, y solo eso (`install/descarga.py`).

Es la pieza que faltaba en el #49: UN tiempo de espera leyendo el zip de rclone
de una plataforma que ni siquiera era la de este equipo tumbaba la instalación,
sin segundo intento. Lo que se prueba aquí es la frontera, que es donde está el
criterio:

  * lo que otro intento podría no tener —un tiempo de espera, una conexión
    cortada, una transferencia incompleta, un 5xx— se reintenta, con esperas
    crecientes, y al final se rinde con el error de verdad;
  * lo que no —un 404, un certificado que no se deja verificar, un fallo del
    propio código— sale a la primera.

Una suma que no cuadra tampoco se reintenta, pero eso no es asunto de este
módulo sino de quien llama: se prueba en `test_rclone_bin.py` y
`test_runtime_bin.py`.

`descarga.esperar()` se sustituye: ningún test duerme de verdad.
"""

import http.client
import ssl
import urllib.error

from _harness import Checks, tmpdir

from install import descarga

c = Checks("instalador: reintentos de descarga")

esperas: list[float] = []
esperar_real = descarga.esperar
descarga.esperar = esperas.append


def falla(*errores, luego=b"hecho"):
    """Una `pedir()` que lanza esos errores, uno por llamada, y luego contesta."""
    pendientes = list(errores)
    llamadas = {"n": 0}

    def pedir():
        llamadas["n"] += 1
        if pendientes:
            raise pendientes.pop(0)
        return luego
    return pedir, llamadas


try:
    c("son tres intentos: uno y dos reintentos", descarga.INTENTOS, 3)
    c("con esperas crecientes", list(descarga.ESPERAS),
      sorted(descarga.ESPERAS))

    # --- qué se reintenta -----------------------------------------------------
    for nombre, error in (
            ("el tiempo de espera del #49", TimeoutError("The read operation timed out")),
            ("una conexión reiniciada", ConnectionResetError(104, "reset")),
            ("no poder conectar", urllib.error.URLError(OSError("getaddrinfo failed"))),
            ("un cuerpo más corto de lo anunciado", http.client.IncompleteRead(b"x", 10)),
            ("un registro TLS cortado", ssl.SSLError("record layer failure")),
            ("un 503", urllib.error.HTTPError("u", 503, "no", {}, None)),
            ("un 429", urllib.error.HTTPError("u", 429, "calma", {}, None))):
        c(f"se reintenta {nombre}", descarga.reintentable(error), True)

    for nombre, error in (
            ("un 404: la URL no va a aparecer", urllib.error.HTTPError("u", 404, "no", {}, None)),
            ("un 403", urllib.error.HTTPError("u", 403, "no", {}, None)),
            ("un certificado que no se deja verificar",
             urllib.error.URLError(ssl.SSLCertVerificationError("self signed"))),
            ("un fallo del propio código", ValueError("otra cosa"))):
        c(f"NO se reintenta {nombre}", descarga.reintentable(error), False)

    # --- con_reintentos ---------------------------------------------------------
    pedir, llamadas = falla(TimeoutError("uno"), TimeoutError("dos"))
    dicho: list[str] = []
    c("dos fallos de red y el tercero contesta: sale bien",
      descarga.con_reintentos(pedir, "Bajar el zip", dicho.append), b"hecho")
    c("tras tres llamadas", llamadas["n"], 3)
    c("esperando lo previsto entre una y otra", esperas, list(descarga.ESPERAS))
    c.contains("y se cuenta que se reintenta", " ".join(dicho), "intento 2 de 3")
    c.contains("diciendo qué", " ".join(dicho), "Bajar el zip")

    esperas.clear()
    pedir, llamadas = falla(*[TimeoutError(f"fallo {i}") for i in range(10)])
    try:
        descarga.con_reintentos(pedir)
        c("si falla siempre, se rinde", "siguió", "TimeoutError")
    except TimeoutError as e:
        c("si falla siempre, se rinde", "TimeoutError", "TimeoutError")
        c("con el último error, tal cual", str(e), "fallo 2")
    c("tras INTENTOS llamadas, ni una más", llamadas["n"], descarga.INTENTOS)
    c("y sin esperar después del último", len(esperas), descarga.INTENTOS - 1)

    esperas.clear()
    pedir, llamadas = falla(urllib.error.HTTPError("u", 404, "Not Found", {}, None))
    try:
        descarga.con_reintentos(pedir)
        c("un 404 sale a la primera", "siguió", "HTTPError")
    except urllib.error.HTTPError:
        c("un 404 sale a la primera", "HTTPError", "HTTPError")
    c("sin segundo intento", llamadas["n"], 1)
    c("ni espera", esperas, [])

    # Lo que no es de red —en los tests, una URL que el código no debía pedir—
    # no se come como si lo fuera.
    pedir, llamadas = falla(AssertionError("URL inesperada"))
    try:
        descarga.con_reintentos(pedir)
        c("un fallo del código no se reintenta", "siguió", "AssertionError")
    except AssertionError:
        c("un fallo del código no se reintenta", "AssertionError", "AssertionError")
    c("y sale a la primera", llamadas["n"], 1)

    c.contains("describir() dice cuántas veces se probó lo que era de red",
               descarga.describir(TimeoutError("se acabó")), "probado 3 veces")
    c("y no se lo inventa de lo que no lo era",
      descarga.describir(ValueError("otra cosa")), "otra cosa")

    # --- el SHA256SUMS ------------------------------------------------------------
    texto = ("-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\n"
             f"{'a' * 64}  rclone-v1-linux-arm64.zip\n"
             f"{'B' * 64}  *rclone-v1-windows-amd64.zip\n")
    c("suma_en() encuentra su línea", descarga.suma_en(texto, "rclone-v1-linux-arm64.zip"),
      "a" * 64)
    c("tolera el '*' de modo binario, y la devuelve en minúsculas",
      descarga.suma_en(texto, "rclone-v1-windows-amd64.zip"), "b" * 64)
    c("None si no está", descarga.suma_en(texto, "rclone-v1-haiku.zip"), None)
    c("la cabecera de la firma no se confunde con una suma",
      descarga.suma_en(texto, "SHA256"), None)

    # Con un SHA256SUMS puesto a mano, no se va a la red.
    carpeta = tmpdir("prdrive-descarga-")
    local = carpeta / descarga.SUMAS
    pedir, llamadas = falla(luego=b"de la red")
    c("sin fichero al lado, de la red",
      descarga.sumas("https://x/SHA256SUMS", local, pedir), ("de la red", "https://x/SHA256SUMS"))
    local.write_text("de la mano\n", encoding="utf-8")
    pedir, llamadas = falla(AssertionError("no debía ir a la red"))
    c("con el fichero al lado, ese, y dice de dónde sale",
      descarga.sumas("https://x/SHA256SUMS", local, pedir), ("de la mano\n", str(local)))
    c("sin tocar la red", llamadas["n"], 0)

    esperas.clear()
    pedir, llamadas = falla(TimeoutError("uno"), luego=b"al segundo")
    local.unlink()
    c("el de la red también se reintenta",
      descarga.sumas("https://x/SHA256SUMS", local, pedir)[0], "al segundo")
    c("una vez", llamadas["n"], 2)
finally:
    descarga.esperar = esperar_real

raise SystemExit(c.report())
