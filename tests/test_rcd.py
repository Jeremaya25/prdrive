#!/usr/bin/env python3
"""El `rclone rcd` vivo: cómo se lanza, cómo se espera, cómo se le llama y cómo se para.

La ventana «Servidor…» habla con un único `rclone rcd` por HTTP en 127.0.0.1.
Lo que se comprueba aquí es lo que no puede fallar sin que se note tarde: que
solo escuche en el bucle local y con credenciales (que van en el entorno, nunca
en la línea de órdenes), que su stderr no sea una tubería que nadie lee, que un
puerto ocupado se distinga de cualquier otro fallo de arranque, que un error de
rclone llegue con su mensaje, y que parar no deje el proceso vivo ni lance.

`rcd.lanzar`, `rcd.peticion` y `rcd.puerto_libre` se sustituyen: ningún test
arranca rclone. La única excepción es `peticion` contra un servidor HTTP de
mentira en el propio proceso, para comprobar que no pasa por el proxy del sistema.
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from _harness import Checks, sandbox

from common import catalog, model, rcd, store
from common.model import ConfigError

c = Checks("rclone rcd vivo")


class ProcesoFalso:
    """Un `Popen` de mentira: vive hasta que se le da un código de salida."""

    def __init__(self) -> None:
        self.returncode = None
        self.matado = False

    def poll(self):
        return self.returncode

    def kill(self) -> None:
        self.matado = True
        self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("rclone", timeout)
        return self.returncode


class Rastro:
    """Lo que `lanzar` y `peticion` falsos reciben, y lo que contestan."""

    def __init__(self) -> None:
        self.lanzado = []           # (orden, entorno, stderr)
        self.peticiones = []        # (url, cuerpo, cabeceras, timeout)
        self.respuestas = []        # lo que contesta cada `peticion`: (estado, texto) o una excepción
        self.proceso = ProcesoFalso()

    def lanzar(self, orden, entorno, stderr):
        self.lanzado.append((orden, entorno, stderr))
        return self.proceso

    def peticion(self, url, cuerpo, cabeceras, timeout):
        self.peticiones.append((url, cuerpo, cabeceras, timeout))
        respuesta = self.respuestas.pop(0) if self.respuestas else (200, "{}")
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta


def con_falsos(rastro: Rastro) -> None:
    rcd.lanzar = rastro.lanzar
    rcd.peticion = rastro.peticion
    rcd.puerto_libre = lambda: 5599
    catalog._binary = lambda: "/ruta/rclone"


lanzar_real, peticion_real, puerto_real = rcd.lanzar, rcd.peticion, rcd.puerto_libre
espera_quit = rcd.ESPERA_QUIT

c("las esperas son las acordadas",
  (rcd.ESPERA_ARRANQUE, rcd.ESPERA_QUIT, rcd.TIMEOUT_PETICION), (10.0, 3.0, 60.0))
c("un puerto ocupado es un error de configuración",
  issubclass(rcd.PuertoOcupado, ConfigError), True)

# puerto libre
puerto = puerto_real()
c("puerto_libre devuelve un puerto de verdad", isinstance(puerto, int) and 0 < puerto < 65536, True)

# cómo se lanza el proceso de verdad
opciones = rcd._opciones_popen(sys.stderr)
c("el hijo corre en la carpeta del programa", opciones["cwd"], str(model.APP_DIR))
c("sin entrada ni salida estándar",
  (opciones["stdin"], opciones["stdout"]), (subprocess.DEVNULL, subprocess.DEVNULL))
c("y con el stderr que se le da", opciones["stderr"] is sys.stderr, True)
if os.name == "nt":
    c("en Windows, sin ventana de consola", opciones["creationflags"], model.CREATE_NO_WINDOW)
    c("y sin sesión propia", "start_new_session" in opciones, False)
else:
    c("en POSIX, en una sesión propia", opciones["start_new_session"], True)
    c("y sin flags de Windows", "creationflags" in opciones, False)

with sandbox():
    # arrancar
    rastro = Rastro()
    con_falsos(rastro)
    r = rcd.arrancar()
    orden, entorno, err = rastro.lanzado[-1]
    c("se lanza rcd con el config del dispositivo", orden[1:4],
      ["rcd", "--config", str(model.RCLONE_CONF)])
    c("el binario es el que da el catálogo", orden[0], "/ruta/rclone")
    c("escucha solo en 127.0.0.1",
      "--rc-addr" in orden and orden[orden.index("--rc-addr") + 1], "127.0.0.1:5599")
    c("lleva los NET_FLAGS del catálogo", all(f in orden for f in catalog.NET_FLAGS), True)
    c("ni sin autenticación ni web", {"--rc-no-auth", "--rc-web-gui"} & set(orden), set())
    c("usuario y contraseña en el entorno",
      len(entorno["RCLONE_RC_USER"]) >= 32 and len(entorno["RCLONE_RC_PASS"]) >= 32, True)
    c("y nunca en argv", any(entorno["RCLONE_RC_PASS"] in a for a in orden), False)
    c("el entorno conserva el del proceso", entorno.get("PATH"), os.environ.get("PATH"))
    c("stderr no es una tubería que nadie lee", err is not subprocess.PIPE and err is not None, True)
    c("queda apuntado para matar_hijos()", r.proceso in store._HIJOS, True)
    c("la url es el bucle local", r.url, "http://127.0.0.1:5599/")
    c("vivo mientras no salga", r.vivo, True)
    r.proceso.returncode = 0
    c("y deja de estarlo al salir", r.vivo, False)
    r.proceso.returncode = None

    # dos arranques no comparten credenciales
    rastro.proceso = ProcesoFalso()
    rcd.arrancar()
    c("cada arranque tiene su contraseña",
      rastro.lanzado[0][1]["RCLONE_RC_PASS"] != rastro.lanzado[1][1]["RCLONE_RC_PASS"], True)
    store.soltar_hijo(rastro.proceso)

    # arrancar sin rclone: el error del catálogo, sin lanzar nada
    def sin_rclone():
        raise ConfigError("No encuentro el binario de rclone")
    catalog._binary = sin_rclone
    previo = len(rastro.lanzado)
    try:
        rcd.arrancar()
        sin_binario = None
    except ConfigError as e:
        sin_binario = str(e)
    c("sin rclone, ConfigError con su mensaje", sin_binario and "rclone" in sin_binario, True)
    c("y no lanza nada", len(rastro.lanzado), previo)
    catalog._binary = lambda: "/ruta/rclone"

    # arrancar con un binario que existe pero no se puede ejecutar
    def lanzar_sin_permiso(orden, entorno, stderr):
        raise PermissionError(13, "Permission denied")
    rcd.lanzar = lanzar_sin_permiso
    antes = set(store._HIJOS)
    try:
        rcd.arrancar()
        sin_permiso = None
    except ConfigError as e:
        sin_permiso = str(e)
    c("si el sistema no deja ejecutar rclone, ConfigError con el motivo",
      sin_permiso is not None and sin_permiso.startswith("No se puede ejecutar rclone:")
      and "Permission denied" in sin_permiso, True)
    c("y no queda nada apuntado", set(store._HIJOS), antes)

    # esperar: rc/noop falla dos veces y luego contesta
    rastro = Rastro()
    con_falsos(rastro)
    r = rcd.arrancar()
    rastro.respuestas = [rcd.RcdCaido("no contesta"), rcd.RcdCaido("no contesta"), (200, "{}")]
    r.esperar()
    c("esperar sondea rc/noop hasta que contesta",
      [p[0] for p in rastro.peticiones], ["http://127.0.0.1:5599/rc/noop"] * 3)

    # esperar: el proceso sale con el puerto ocupado
    rastro = Rastro()
    con_falsos(rastro)
    r = rcd.arrancar()
    rastro.lanzado[-1][2].write(
        b"Failed to start remote control: listen tcp 127.0.0.1:5599: bind: address already in use\n")
    rastro.proceso.returncode = 1
    rastro.respuestas = [rcd.RcdCaido("no contesta")] * 5
    try:
        r.esperar()
        salida = None
    except rcd.PuertoOcupado as e:
        salida = e
    c("un puerto ocupado se distingue", isinstance(salida, rcd.PuertoOcupado), True)

    # Windows lo dice con otra frase
    rastro = Rastro()
    con_falsos(rastro)
    r = rcd.arrancar()
    rastro.lanzado[-1][2].write(
        b"bind: Only one usage of each socket address (protocol/network address/port) is normally permitted.")
    rastro.proceso.returncode = 1
    try:
        r.esperar()
        salida = None
    except rcd.PuertoOcupado as e:
        salida = e
    c("y también la frase de Windows", isinstance(salida, rcd.PuertoOcupado), True)

    # esperar: el proceso sale por otra razón
    rastro = Rastro()
    con_falsos(rastro)
    r = rcd.arrancar()
    rastro.lanzado[-1][2].write("didn't find section [rara] en la configuración".encode())
    rastro.proceso.returncode = 1
    try:
        r.esperar()
        salida = None
    except ConfigError as e:
        salida = e
    c("otro fallo de arranque es ConfigError, no PuertoOcupado",
      isinstance(salida, ConfigError) and not isinstance(salida, rcd.PuertoOcupado), True)
    c("y lleva el stderr de rclone", "didn't find section [rara]" in str(salida), True)

    # esperar: nunca contesta
    rastro = Rastro()
    con_falsos(rastro)
    r = rcd.arrancar()
    rastro.respuestas = [rcd.RcdCaido("no contesta")] * 1000
    try:
        r.esperar(tope=0.2)
        salida = None
    except ConfigError as e:
        salida = e
    c("si nunca contesta, ConfigError al pasar el tope", isinstance(salida, ConfigError), True)

    # esperar: contesta un error (otro servidor en el puerto): no vale como listo
    rastro = Rastro()
    con_falsos(rastro)
    r = rcd.arrancar()
    rastro.respuestas = [(401, "Unauthorized")] * 1000
    try:
        r.esperar(tope=0.2)
        salida = None
    except ConfigError as e:
        salida = e
    c("un 401 no es estar listo", isinstance(salida, ConfigError), True)

    # llamar
    rastro = Rastro()
    con_falsos(rastro)
    r = rcd.arrancar()
    usuario, clave = rastro.lanzado[-1][1]["RCLONE_RC_USER"], rastro.lanzado[-1][1]["RCLONE_RC_PASS"]
    rastro.respuestas = [(200, '{"list": [1, 2]}')]
    resultado = r.llamar("operations/list", {"fs": "r:", "remote": ""})
    url, cuerpo, cabeceras, tope = rastro.peticiones[-1]
    c("llamar devuelve el JSON como dict", resultado, {"list": [1, 2]})
    c("a la url del método", url, "http://127.0.0.1:5599/operations/list")
    c("con los parámetros en JSON", json.loads(cuerpo), {"fs": "r:", "remote": ""})
    c("como JSON", cabeceras["Content-Type"], "application/json")
    autorizacion = base64.b64encode(f"{usuario}:{clave}".encode()).decode()
    c("con Authorization Basic del usuario y la contraseña",
      cabeceras["Authorization"], f"Basic {autorizacion}")
    c("con el tope de las peticiones", tope, rcd.TIMEOUT_PETICION)
    rastro.respuestas = [(200, "{}")]
    r.llamar("core/pid")
    c("sin parámetros manda un objeto vacío", json.loads(rastro.peticiones[-1][1]), {})

    # llamar: error de rclone
    rastro.respuestas = [(404, json.dumps({
        "error": "error in ListJSON: directory not found", "input": {"fs": "r:"},
        "path": "operations/list", "status": 404}))]
    try:
        r.llamar("operations/list", {"fs": "r:", "remote": "x"})
        error = None
    except rcd.ErrorRc as e:
        error = e
    c("un error de rclone es ErrorRc", isinstance(error, rcd.ErrorRc), True)
    c("con el mensaje de rclone", error and error.mensaje, "error in ListJSON: directory not found")
    c("y el estado HTTP", error and error.estado, 404)
    rastro.respuestas = [(500, '{"error": "directory not found"}')]
    try:
        r.llamar("operations/list")
        error = None
    except rcd.ErrorRc as e:
        error = e
    c("el estado es el de HTTP", (error.mensaje, error.estado), ("directory not found", 500))
    rastro.respuestas = [(502, "Bad Gateway")]
    try:
        r.llamar("operations/list")
        error = None
    except rcd.ErrorRc as e:
        error = e
    c("si el cuerpo no es JSON, el mensaje es el texto", (error.mensaje, error.estado), ("Bad Gateway", 502))
    rastro.respuestas = [rcd.RcdCaido("se cortó")]
    try:
        r.llamar("core/pid")
        caido = None
    except rcd.RcdCaido as e:
        caido = e
    c("RcdCaido pasa tal cual", isinstance(caido, rcd.RcdCaido), True)

    # parar: sale tras core/quit
    rastro = Rastro()
    con_falsos(rastro)
    r = rcd.arrancar()
    rastro.respuestas = [(200, "{}")]
    rastro.proceso.returncode = 0           # sale enseguida
    r.parar()
    c("parar llama a core/quit", rastro.peticiones[-1][0], "http://127.0.0.1:5599/core/quit")
    c("si sale a tiempo, no se mata", rastro.proceso.matado, False)
    c("y deja de estar apuntado", r.proceso in store._HIJOS, False)

    # parar: sigue vivo pasado ESPERA_QUIT
    rastro = Rastro()
    con_falsos(rastro)
    rcd.ESPERA_QUIT = 0.1
    r = rcd.arrancar()
    rastro.respuestas = [(200, "{}")]
    r.parar()
    c("si sigue vivo pasada la espera, se mata", rastro.proceso.matado, True)
    c("y también deja de estar apuntado", r.proceso in store._HIJOS, False)

    # parar: core/quit falla
    rastro = Rastro()
    con_falsos(rastro)
    r = rcd.arrancar()
    rastro.respuestas = [rcd.RcdCaido("ya no contesta")]
    try:
        r.parar()
        lanzo = False
    except Exception:
        lanzo = True
    c("parar no lanza aunque core/quit falle", lanzo, False)
    c("y mata al que no contesta", rastro.proceso.matado, True)
    rcd.ESPERA_QUIT = espera_quit

    # parar dos veces no pasa nada
    try:
        r.parar()
        lanzo = False
    except Exception:
        lanzo = True
    c("parar es repetible", lanzo, False)

# la petición de verdad no pasa por el proxy del sistema
class Manejador(BaseHTTPRequestHandler):
    visto = {}

    def do_POST(self):
        Manejador.visto = {"ruta": self.path, "autorizacion": self.headers.get("Authorization"),
                           "cuerpo": self.rfile.read(int(self.headers.get("Content-Length", 0)))}
        cuerpo = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *args):
        pass


servidor = HTTPServer(("127.0.0.1", 0), Manejador)
hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
hilo.start()
VARIABLES_PROXY = ("HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy")
proxys = {k: os.environ.get(k) for k in VARIABLES_PROXY}
# NO_PROXY se vacía: si cubriera 127.0.0.1, el test pasaría aunque `peticion` usara el proxy.
os.environ["HTTP_PROXY"] = os.environ["http_proxy"] = "http://127.0.0.1:9"
os.environ.pop("NO_PROXY", None)
os.environ.pop("no_proxy", None)
try:
    real = peticion_real(f"http://127.0.0.1:{servidor.server_port}/rc/noop", b"{}",
                         {"Authorization": "Basic eDp5"}, 5)
finally:
    for k, v in proxys.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    servidor.shutdown()
    servidor.server_close()
c("peticion no pasa por el proxy del sistema", real, (200, '{"ok": true}'))
c("y manda la ruta, la cabecera y el cuerpo",
  (Manejador.visto["ruta"], Manejador.visto["autorizacion"], Manejador.visto["cuerpo"]),
  ("/rc/noop", "Basic eDp5", b"{}"))

# un servidor que contesta con error: peticion devuelve el estado y el cuerpo
class Fallo(BaseHTTPRequestHandler):
    def do_POST(self):
        cuerpo = b'{"error": "no hay"}'
        self.send_response(404)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *args):
        pass


servidor = HTTPServer(("127.0.0.1", 0), Fallo)
threading.Thread(target=servidor.serve_forever, daemon=True).start()
try:
    c("un HTTPError devuelve su estado y su cuerpo",
      peticion_real(f"http://127.0.0.1:{servidor.server_port}/x", b"{}", {}, 5), (404, '{"error": "no hay"}'))
finally:
    servidor.shutdown()
    servidor.server_close()

# y un puerto sin nadie es RcdCaido
libre = puerto_real()
try:
    peticion_real(f"http://127.0.0.1:{libre}/x", b"{}", {}, 2)
    caido = None
except rcd.RcdCaido as e:
    caido = e
c("sin nadie escuchando, RcdCaido", isinstance(caido, rcd.RcdCaido), True)

sys.exit(c.report())
