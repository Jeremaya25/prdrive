#!/usr/bin/env python3
"""El `rclone rcd` vivo: cómo se lanza, cómo se espera, cómo se le llama y cómo se para.

La ventana «Servidor…» habla con un único `rclone rcd` por HTTP en 127.0.0.1.
Lo que se comprueba aquí es lo que no puede fallar sin que se note tarde: que
solo escuche en el bucle local y con credenciales (que van en el entorno, nunca
en la línea de órdenes), que su stderr no sea una tubería que nadie lee, que un
puerto ocupado se distinga de cualquier otro fallo de arranque, que un error de
rclone llegue con su mensaje, y que parar no deje el proceso vivo ni lance.

Y que no pueda quedar huérfano con ficheros del dispositivo abiertos: el Job Object
de Windows, `PDEATHSIG` de Linux y `state/rcd.json` con el pid y la hora de creación
(nunca la contraseña), que el siguiente arranque usa para matar al que sobrevivió.

`rcd.lanzar`, `rcd.peticion` y `rcd.puerto_libre` se sustituyen: ningún test
arranca rclone. Tampoco se mata nada de verdad: `store.matar_arbol`, `pid_alive` y
`creado` se sustituyen. Lo propio de Windows se fuerza con `rcd.os` y un
`atar_al_job` falso (y falso por defecto en todo el fichero: ninguna comprobación
toca los Job Objects de verdad con un proceso de mentira); la llamada real a esa
función solo corre en Windows.

La única excepción es `peticion` contra un servidor HTTP de mentira en el propio proceso, para comprobar que no pasa por el proxy del sistema.
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

from _harness import Checks, sandbox

from common import catalog, model, rcd, store
from common.model import ConfigError

c = Checks("rclone rcd vivo")


class ProcesoFalso:
    """Un `Popen` de mentira: vive hasta que se le da un código de salida."""

    def __init__(self, pid: int = 4_000_001) -> None:
        self.returncode = None
        self.matado = False
        self.pid = pid

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
# En Windows `arrancar()` llama a `atar_al_job`; con un `ProcesoFalso` no debe tocar la API real.
atar_real = rcd.atar_al_job
sin_job = lambda proceso: False  # noqa: E731
rcd.atar_al_job = sin_job

# Nada de lo de `store` que mira o mata procesos de verdad: lo que viva en el equipo no es de este test.
matados: list[int] = []
vivos: set[int] = set()
horas: dict[int, float] = {}
store.matar_arbol = matados.append
store.pid_alive = lambda pid: pid in vivos
store.creado = horas.get
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

    # el entorno de quien lanza prdrive no deshace las garantías
    ajenas = {"RCLONE_RC_NO_AUTH": "true", "RCLONE_RC_WEB_GUI": "true", "RCLONE_RC_SERVE": "true",
              "RCLONE_RC_ADDR": "0.0.0.0:5572", "RCLONE_RC_HTPASSWD": "/x", "RCLONE_RC_USER": "otro"}
    previo = {k: os.environ.get(k) for k in ajenas}
    os.environ.update(ajenas)
    try:
        rastro.proceso = ProcesoFalso()
        rcd.arrancar()
        limpio = rastro.lanzado[-1][1]
    finally:
        for k, v in previo.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        store.soltar_hijo(rastro.proceso)
    c("las RCLONE_RC_* del usuario no pasan al hijo",
      sorted(k for k in limpio if k.startswith("RCLONE_RC_")), ["RCLONE_RC_PASS", "RCLONE_RC_USER"])
    c("  y el usuario es el generado, no el de fuera",
      (limpio["RCLONE_RC_USER"] != "otro", len(limpio["RCLONE_RC_USER"]) >= 32), (True, True))
    c("  el resto del entorno sigue", limpio.get("PATH"), os.environ.get("PATH"))

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

    # --- los cinturones contra el huérfano ---
    c("el fichero de estado cuelga de STATE_DIR (que los tests mueven)",
      rcd.fichero_estado(), model.STATE_DIR / "rcd.json")

    def escribir_estado(contenido) -> None:
        rcd.fichero_estado().parent.mkdir(parents=True, exist_ok=True)
        rcd.fichero_estado().write_text(
            contenido if isinstance(contenido, str) else json.dumps(contenido), encoding="utf-8")

    # huérfano vivo con la misma hora de creación: se mata y se borra el fichero
    matados.clear()
    vivos.add(4242)
    horas[4242] = 1_000_000.0
    escribir_estado({"pid": 4242, "creado": 1_000_000.4})
    c("un rcd colgado de antes se mata", rcd.limpiar_huerfano(), 4242)
    c("con matar_arbol", matados, [4242])
    c("y se borra el fichero", rcd.fichero_estado().exists(), False)

    # misma pid, otra hora de creación: la heredó otro proceso
    matados.clear()
    escribir_estado({"pid": 4242, "creado": 900_000.0})
    c("si el pid lo heredó otro proceso (otra hora), no se mata", rcd.limpiar_huerfano(), None)
    c("y no se llama a matar_arbol", matados, [])
    c("pero el fichero se borra", rcd.fichero_estado().exists(), False)

    # pid muerto
    escribir_estado({"pid": 777, "creado": 1_000_000.0})
    horas[777] = 1_000_000.0
    c("un pid que ya no vive no se mata", (rcd.limpiar_huerfano(), matados), (None, []))
    c("y el fichero se borra", rcd.fichero_estado().exists(), False)

    # no se sabe cuándo se creó el que vive: no se arriesga
    vivos.add(555)
    escribir_estado({"pid": 555, "creado": 1_000_000.0})
    c("si no se puede leer su hora de creación, no se mata", (rcd.limpiar_huerfano(), matados), (None, []))
    escribir_estado({"pid": 4242, "creado": None})
    c("ni si lo apuntado no trae hora", (rcd.limpiar_huerfano(), matados), (None, []))

    # nunca a sí mismo
    vivos.add(os.getpid())
    horas[os.getpid()] = 1_000_000.0
    escribir_estado({"pid": os.getpid(), "creado": 1_000_000.0})
    c("nunca se mata a sí mismo", (rcd.limpiar_huerfano(), matados), (None, []))

    # ilegible o ausente o con basura
    for nombre, contenido in (("ilegible", "{no es json"), ("una lista", "[1, 2]"),
                              ("con tipos raros", {"pid": "4242", "creado": "ayer"}),
                              ("con un booleano por pid", {"pid": True, "creado": 1.0})):
        escribir_estado(contenido)
        try:
            resultado = rcd.limpiar_huerfano()
            lanzo = False
        except Exception:
            resultado, lanzo = "lanzó", True
        c(f"un fichero {nombre}: None, sin lanzar", (resultado, lanzo, matados), (None, False, []))
        c(f"  y se borra ({nombre})", rcd.fichero_estado().exists(), False)
    c("sin fichero: None, sin lanzar", rcd.limpiar_huerfano(), None)

    # si matar falla, tampoco lanza
    def matar_roto(pid):
        raise RuntimeError("no se deja")
    escribir_estado({"pid": 4242, "creado": 1_000_000.0})
    store.matar_arbol = matar_roto
    try:
        resultado = rcd.limpiar_huerfano()
    except Exception:
        resultado = "lanzó"
    c("limpiar_huerfano no lanza aunque matar falle", resultado, None)
    store.matar_arbol = matados.append
    matados.clear()

    # arrancar(): limpia antes de lanzar, y apunta {pid, creado} sin la contraseña
    escribir_estado({"pid": 4242, "creado": 1_000_000.0})
    rastro = Rastro()
    visto = {}
    horas[rastro.proceso.pid] = 2_000_000.5

    def lanzar_mirando(orden, entorno, stderr):
        visto["matados_al_lanzar"] = list(matados)
        visto["hilo"] = threading.get_ident()
        visto["fichero_al_lanzar"] = rcd.fichero_estado().exists()
        return rastro.lanzar(orden, entorno, stderr)
    con_falsos(rastro)
    rcd.lanzar = lanzar_mirando
    r = rcd.arrancar()
    c("arrancar mata al huérfano antes de lanzar", visto["matados_al_lanzar"], [4242])
    c("y el fichero viejo ya no está al lanzar", visto["fichero_al_lanzar"], False)
    c("el Popen se hace en el hilo que llama a arrancar()", visto["hilo"], threading.get_ident())
    estado = json.loads(rcd.fichero_estado().read_text(encoding="utf-8"))
    c("rcd.json guarda el pid y la hora de creación",
      estado, {"pid": rastro.proceso.pid, "creado": 2_000_000.5})
    clave = rastro.lanzado[-1][1]["RCLONE_RC_PASS"]
    usuario = rastro.lanzado[-1][1]["RCLONE_RC_USER"]
    texto = rcd.fichero_estado().read_text(encoding="utf-8")
    c("rcd.json no guarda la contraseña", clave in texto, False)
    c("ni el usuario", usuario in texto, False)
    c("sigue apuntado para matar_hijos()", r.proceso in store._HIJOS, True)

    # y si ese rcd sobrevive, el siguiente arranque lo mata
    matados.clear()
    vivos.add(rastro.proceso.pid)
    rastro2 = Rastro()
    rastro2.proceso = ProcesoFalso(pid=4_000_002)
    horas[4_000_002] = 3_000_000.0
    con_falsos(rastro2)
    rcd.arrancar()
    c("un segundo arranque mata al primero si sobrevivió", matados, [rastro.proceso.pid])
    c("y apunta al nuevo", json.loads(rcd.fichero_estado().read_text(encoding="utf-8"))["pid"], 4_000_002)
    store.soltar_hijo(r.proceso)
    store.soltar_hijo(rastro2.proceso)

    # parar() borra rcd.json
    matados.clear()
    rastro = Rastro()
    con_falsos(rastro)
    r = rcd.arrancar()
    c("hay rcd.json mientras vive", rcd.fichero_estado().exists(), True)
    rastro.respuestas = [(200, "{}")]
    rastro.proceso.returncode = 0
    r.parar()
    c("parar() borra rcd.json", rcd.fichero_estado().exists(), False)

    # pero no el de otro rcd más reciente
    rastro_a, rastro_b = Rastro(), Rastro()
    rastro_b.proceso = ProcesoFalso(pid=4_000_003)
    con_falsos(rastro_a)
    ra = rcd.arrancar()
    con_falsos(rastro_b)
    rb = rcd.arrancar()
    rastro_a.proceso.returncode = 0
    ra.parar()
    c("parar() no borra el apunte de otro rcd", rcd.fichero_estado().exists(), True)
    rastro_b.proceso.returncode = 0
    rb.parar()
    c("y el último sí lo borra", rcd.fichero_estado().exists(), False)

    # puerto_libre que falla: ConfigError, no OSError
    def sin_puertos():
        raise OSError(98, "sin puertos")
    con_falsos(Rastro())
    rcd.puerto_libre = sin_puertos
    try:
        rcd.arrancar()
        sin_puerto = None
    except ConfigError as e:
        sin_puerto = str(e)
    except OSError:
        sin_puerto = "OSError"
    c("si no hay puerto, ConfigError y no OSError", sin_puerto and sin_puerto.startswith("No se puede abrir"), True)

    # POSIX: el hijo muere con el padre (preexec_fn)
    previo_prctl = rcd._PRCTL
    llamadas = []
    rcd._PRCTL = lambda *a: llamadas.append(a) or 0
    rcd._morir_con_el_padre()
    c("_morir_con_el_padre pide PR_SET_PDEATHSIG con SIGKILL", llamadas, [(1, 9, 0, 0, 0)])
    rcd._PRCTL = None
    rcd._morir_con_el_padre()                      # sin prctl, no hace nada y no lanza
    rcd._PRCTL = previo_prctl
    opciones = rcd._opciones_popen(subprocess.DEVNULL)
    if sys.platform.startswith("linux"):
        c("en Linux, el hijo lleva preexec_fn=_morir_con_el_padre",
          opciones.get("preexec_fn") is rcd._morir_con_el_padre, True)
        c("y prctl está resuelto en el padre (global del módulo)", rcd._PRCTL is not None, True)
        c("y sigue siendo jefe de su sesión (para matar_arbol)", opciones["start_new_session"], True)
    else:
        print("  (saltado) preexec_fn solo en Linux: no hay PDEATHSIG en este sistema")

    # Windows, forzado: Job Object en vez de preexec_fn
    os_real = rcd.os
    rcd.os = SimpleNamespace(name="nt", environ=os.environ, path=os.path, getpid=os.getpid)
    try:
        opciones = rcd._opciones_popen(subprocess.DEVNULL)
        c("en Windows no hay preexec_fn (no existe)", "preexec_fn" in opciones, False)
        c("ni sesión propia, sí sin consola",
          ("start_new_session" in opciones, opciones["creationflags"]), (False, model.CREATE_NO_WINDOW))
        atados = []
        rcd.atar_al_job = lambda p: atados.append(p) or True
        rastro = Rastro()
        con_falsos(rastro)
        r = rcd.arrancar()
        c("en Windows, arrancar() ata el proceso al job", atados, [rastro.proceso])
        c("y apunta rcd.json igual", json.loads(rcd.fichero_estado().read_text(encoding="utf-8"))["pid"],
          rastro.proceso.pid)
        store.soltar_hijo(rastro.proceso)
        rcd.atar_al_job = lambda p: atados.append(p) or False
        rastro = Rastro()
        con_falsos(rastro)
        r = rcd.arrancar()
        c("si atar_al_job devuelve False, arranca igual",
          (len(atados), r.proceso in store._HIJOS, rcd.fichero_estado().exists()), (2, True, True))
        store.soltar_hijo(rastro.proceso)
    finally:
        rcd.os = os_real
        rcd.atar_al_job = sin_job

    # POSIX, forzado también: que no dependa de en qué sistema corre el test
    rcd.os = SimpleNamespace(name="posix", environ=os.environ, path=os.path, getpid=os.getpid)
    try:
        atados = []
        rcd.atar_al_job = lambda p: atados.append(p) or True
        rastro = Rastro()
        con_falsos(rastro)
        rcd.arrancar()
        c("en POSIX, arrancar() no toca el job", atados, [])
        store.soltar_hijo(rastro.proceso)
    finally:
        rcd.os = os_real
        rcd.atar_al_job = sin_job

    # atar_al_job de verdad
    if os.name == "nt":
        dormilon = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                    creationflags=model.CREATE_NO_WINDOW)
        try:
            c("atar_al_job mete un proceso real en un Job Object", atar_real(dormilon), True)
            c("y guarda el handle del job", len(rcd._JOBS) >= 1, True)
        finally:
            dormilon.kill()
            dormilon.wait()
    else:
        dormilon = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            c("fuera de Windows, atar_al_job devuelve False sin lanzar", atar_real(dormilon), False)
        finally:
            dormilon.kill()
            dormilon.wait()
        print("  (saltado) la llamada real a los Job Objects solo corre en Windows")

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


# transferencias: copiar, seguir y cancelar un lote por rc
class RcdFalso:
    """Un `Rcd` de mentira: anota cada llamada y contesta lo que se le da (o lanza)."""

    def __init__(self, respuesta=None) -> None:
        self.llamadas = []   # (metodo, params)
        self.respuesta = respuesta if respuesta is not None else {}

    def llamar(self, metodo, params=None):
        self.llamadas.append((metodo, params))
        if isinstance(self.respuesta, Exception):
            raise self.respuesta
        return self.respuesta


falso = RcdFalso({"jobid": 7, "executeId": "x"})
jid = rcd.copiar(falso, "nas:/datos", "/home/u/Descargas", ["/a.txt", "/c/**"], omitir=False, grupo="lote-1")
c("copiar es sync/copy", falso.llamadas[-1][0], "sync/copy")
c("con lo elegido", falso.llamadas[-1][1], {
    "srcFs": "nas:/datos", "dstFs": "/home/u/Descargas",
    "createEmptySrcDirs": True, "_filter": {"IncludeRule": ["/a.txt", "/c/**"]},
    "_async": True, "_group": "lote-1"})
c("sin omitir no lleva _config", "_config" in falso.llamadas[-1][1], False)
c("devuelve el jobid", jid, 7)
rcd.copiar(falso, "a", "b", ["/x"], omitir=True, grupo="g")
c("omitir es IgnoreExisting", falso.llamadas[-1][1]["_config"], {"IgnoreExisting": True})
c("nunca otro método de sync", {m for m, _ in falso.llamadas if m.startswith("sync/")}, {"sync/copy"})

# sin reglas, rclone copiaría el origen entero: se rechaza antes de llamar a rcd
for reglas_malas in ([], ["/a", ""], ["  "]):
    falso = RcdFalso({"jobid": 7})
    error = None
    try:
        rcd.copiar(falso, "nas:/datos", "/home/u/Descargas", reglas_malas, omitir=False, grupo="g")
    except ValueError as e:
        error = e
    c(f"reglas {reglas_malas!r}: ValueError", isinstance(error, ValueError), True)
    c(f"reglas {reglas_malas!r}: no llama a rcd", falso.llamadas, [])
c("y el mensaje lo dice", str(error), "copiar necesita al menos una regla")

falso = RcdFalso({})
rcd.cancelar(falso, 7)
c("cancelar es job/stop con el jobid", falso.llamadas[-1], ("job/stop", {"jobid": 7}))
falso = RcdFalso(rcd.ErrorRc("job not found", 500))
lanzo = False
try:
    rcd.cancelar(falso, 7)
except Exception:
    lanzo = True
c("cancelar traga el ErrorRc de un job ya terminado", lanzo, False)
falso = RcdFalso(rcd.RcdCaido("sin conexión"))
lanzo = None
try:
    rcd.cancelar(falso, 7)
except rcd.RcdCaido as e:
    lanzo = e
c("pero no traga RcdCaido", isinstance(lanzo, rcd.RcdCaido), True)

falso = RcdFalso({"bytes": 10})
c("progreso devuelve core/stats del grupo", rcd.progreso(falso, "g"), {"bytes": 10})
c("y lo pide con core/stats", falso.llamadas[-1], ("core/stats", {"group": "g"}))
falso = RcdFalso({"jobid": 7, "finished": False})
c("estado devuelve job/status del jobid", rcd.estado(falso, 7), {"jobid": 7, "finished": False})
c("y lo pide con job/status", falso.llamadas[-1], ("job/status", {"jobid": 7}))

sys.exit(c.report())
