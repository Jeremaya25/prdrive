#!/usr/bin/env python3
"""Las lecturas del asistente, sin Tk: lo que decide `ui/lecturas_asistente.py`.

Lo que se comprueba es lo que cuida los datos y las decisiones del asistente:
- `ExamenDiferido`: un examen de un texto que ya no está escrito NO cuenta (ni
  enciende «Siguiente» ni deja crear un contenedor sobre una carpeta sin mirar);
  una tecla deja el examen pendiente, y `ya()` lo hace en el acto (y olvida el
  anterior hasta que llega el nuevo); un `<Destroy>` de un hijo de la caja no
  cancela su espera, el de la propia caja sí.
- La sonda de escritura de una unidad: una sola por unidad, `midiendo()` solo
  mientras escribe y hasta su tope, y lo que dice `texto_espera()` en cada
  estado (midiendo, no se ha podido, con su división).
- `esperar_sondas()`: al cerrar espera a la sonda que aún escribe, y solo hasta
  su tope, para que no quede su `.prdrive-sonda.tmp` en la unidad.
- Los exámenes y comprobaciones que no pintan: la carpeta del contenedor, la
  ruta a mano, el Python del equipo y la verificación del dispositivo.

Nada de esto abre Tk: el módulo no lo importa ni dentro de una función, y el
test lo comprueba. Las esperas de las cajas y del sondeo son apuntadores a
mano, y las funciones de `install/` que tocan el disco se sustituyen.
"""

import sys
import time
from pathlib import Path
from types import SimpleNamespace

from _harness import Checks, tmpdir

c = Checks("asistente sin Tk: las lecturas que no pintan")

from ui import lecturas_asistente as la  # noqa: E402

c("importar las lecturas no carga tkinter", "tkinter" in sys.modules, False)

from install import crypto, device, raiz_equipo, traveler, vestibulo  # noqa: E402
from ui import segundo_plano  # noqa: E402

LANZAR_REAL = segundo_plano.lanzar
ESPERA_REAL = la.ESPERA_TECLA_MS
TOPE_REAL = la.TOPE_SONDA_S


class Pendientes:
    """Un `lanzar()` que no corre nada: guarda cada encargo para soltarlo a mano.

    Attributes:
        encargos: Los encargos lanzados, en orden.
    """

    def __init__(self) -> None:
        """Empieza sin encargos."""
        self.encargos: list = []

    def __call__(self, funcion):
        """Devuelve un encargo sin correrlo."""
        encargo = segundo_plano.Encargo(funcion)
        self.encargos.append(encargo)
        return encargo


class Ancla:
    """Lo que una espera pide de una caja: `after`, `after_cancel` y `bind`.

    Attributes:
        pendientes: `id → (ms, función, argumentos)` de cada `after` sin cancelar.
        enlaces: Los `bind` pedidos.
        funciones: `evento → función` de cada `bind`, para dispararlo a mano.
    """

    def __init__(self) -> None:
        """Empieza sin esperas."""
        self.pendientes: dict = {}
        self.enlaces: list = []
        self.funciones: dict = {}
        self._n = 0

    def after(self, ms, funcion, *args):
        """Apunta la espera; no se dispara sola."""
        self._n += 1
        ident = f"ancla#{self._n}"
        self.pendientes[ident] = (ms, funcion, args)
        return ident

    def after_cancel(self, ident) -> None:
        """Quita la espera apuntada."""
        self.pendientes.pop(ident, None)

    def bind(self, evento, funcion, add=None) -> None:
        """Apunta el enlace y su función."""
        self.enlaces.append(evento)
        self.funciones[evento] = funcion

    def __str__(self) -> str:
        """Se nombra como una caja, para el `<Destroy>`."""
        return "ancla"

    def disparar(self, ms: int) -> int:
        """Dispara las esperas de ese plazo y devuelve cuántas había."""
        listas = [i for i, (plazo, _, _) in self.pendientes.items() if plazo == ms]
        for ident in listas:
            _, funcion, args = self.pendientes.pop(ident)
            funcion(*args)
        return len(listas)


class SondeoFalso:
    """Lo que el `Sondeo` de la caja: guarda el encargo y lo recoge a mano.

    Attributes:
        encargo: El último encargo esperado.
        al_llegar: A quién avisar al recogerlo.
    """

    def __init__(self) -> None:
        """Empieza sin nada que esperar."""
        self.encargo = None
        self.al_llegar = None

    def esperar(self, encargo, al_llegar) -> None:
        """Guarda lo que hay que recoger; no llega hasta `recoger()`."""
        self.encargo, self.al_llegar = encargo, al_llegar

    def recoger(self) -> bool:
        """Entrega el encargo si ya ha terminado, como haría el sondeo."""
        if self.encargo is not None and self.encargo.hecho:
            self.al_llegar(self.encargo)
            return True
        return False


# 1. ExamenDiferido: un examen de un texto viejo no cuenta
pendientes = Pendientes()
segundo_plano.lanzar = pendientes
llegadas: list = []
texto = {"caja": "A"}
al_teclear: list = []
diferido = None
try:
    ancla, sondeo = Ancla(), SondeoFalso()
    diferido = la.ExamenDiferido(
        ancla, lambda: (texto["caja"],), lambda t: f"examen de {t}",
        lambda: al_teclear.append(True), llegadas.append, sondeo)
    c("ExamenDiferido engancha un destruir a la caja, y no examina al crearse",
      (ancla.enlaces, pendientes.encargos), (["<Destroy>"], []))

    diferido.tecla()
    texto["caja"] = "B"                       # se sigue tecleando
    diferido.tecla()
    c("cada tecla deja el examen pendiente, y la espera se rearma una sola vez",
      (len(al_teclear), len(ancla.pendientes), ancla.disparar(ESPERA_REAL)),
      (2, 1, 1))
    c("  y al vencer, examina lo escrito AHORA (B), no lo de la primera tecla",
      [e._funcion.args for e in pendientes.encargos], [("B",)])
    texto["caja"] = "C"                       # cambia otra vez antes de que llegue
    pendientes.encargos[0].correr()
    sondeo.recoger()
    c("el examen de B llega tarde: no cuenta (lo escrito es C)",
      (diferido.examinada, diferido.vigente(), llegadas), (None, None, []))

    diferido.ya()
    pendientes.encargos[1].correr()
    sondeo.recoger()
    c("un examen de lo escrito ahora sí cuenta",
      (diferido.examinada, diferido.resultado, len(llegadas)),
      (("C",), "examen de C", 1))
    c("  y vigente() lo da mientras no se vuelva a teclear",
      diferido.vigente(), "examen de C")
    texto["caja"] = "D"                       # se cambia sin pasar por tecla()
    c("  pero si lo escrito cambia sin una tecla, ya no vale: vigente() es None",
      (diferido.vigente(), diferido.examinada), (None, ("C",)))
    diferido.tecla()
    c("  y una tecla lo caduca en el acto", diferido.vigente(), None)
finally:
    segundo_plano.lanzar = LANZAR_REAL

# Un examen que falla no deja un resultado que valga.
pendientes = Pendientes()
segundo_plano.lanzar = pendientes
try:
    ancla, sondeo = Ancla(), SondeoFalso()
    fallida = la.ExamenDiferido(ancla, lambda: ("x",),
                                lambda t: 1 / 0, lambda: None, lambda e: None, sondeo)
    fallida.ya()
    pendientes.encargos[0].correr()
    sondeo.recoger()
    c("un examen que lanza deja su error y ningún resultado",
      (fallida.resultado, pendientes.encargos[0].error is not None), (None, True))
    c("  y examen_fallido lo dice como un examen que no vale",
      (la.examen_fallido(pendientes.encargos[0]).vale,
       "No se ha podido examinar la carpeta" in
       la.examen_fallido(pendientes.encargos[0]).texto), (False, True))
finally:
    segundo_plano.lanzar = LANZAR_REAL

# 1b. ya() olvida el examen anterior: hasta que llega el nuevo no hay ninguno que valga
pendientes = Pendientes()
segundo_plano.lanzar = pendientes
try:
    ancla, sondeo = Ancla(), SondeoFalso()
    de_ya = la.ExamenDiferido(ancla, lambda: ("C",), lambda t: f"examen de {t}",
                              lambda: None, lambda e: None, sondeo)
    de_ya.ya()
    pendientes.encargos[0].correr()
    sondeo.recoger()
    c("un examen vale mientras lo escrito no cambie", de_ya.vigente(), "examen de C")
    de_ya.ya()
    c("ya() olvida el examen anterior en el acto: vigente() es None hasta que llegue el nuevo",
      (de_ya.examinada, de_ya.resultado, de_ya.vigente()), (None, None, None))
    pendientes.encargos[1].correr()
    sondeo.recoger()
    c("  y cuando llega el examen de ahora, vale otra vez", de_ya.vigente(), "examen de C")
finally:
    segundo_plano.lanzar = LANZAR_REAL


# 1c. El <Destroy> de un hijo de la caja no cancela su espera; el de la caja sí
class Hijo:
    """Un widget dentro de la caja: su nombre de Tk empieza por el de la caja."""

    def __str__(self) -> str:
        """Se nombra como un hijo de la caja."""
        return "ancla.marco"


ancla, sondeo = Ancla(), SondeoFalso()
de_destruir = la.ExamenDiferido(ancla, lambda: ("x",), lambda t: t,
                                lambda: None, lambda e: None, sondeo)
de_destruir.tecla()
c("con una tecla, la espera del examen está puesta", len(ancla.pendientes), 1)
ancla.funciones["<Destroy>"](SimpleNamespace(widget=Hijo()))
c("el <Destroy> de un hijo de la caja no cancela la espera", len(ancla.pendientes), 1)
ancla.funciones["<Destroy>"](SimpleNamespace(widget=ancla))
c("el <Destroy> de la propia caja sí la cancela", len(ancla.pendientes), 0)


# 2. la sonda de escritura: una por unidad, y sus estados
def estado_de(unidad) -> SimpleNamespace:
    """Un `InstallState` de mentira con lo que usan las sondas."""
    return SimpleNamespace(device=unidad, sondas={}, velocidad_escritura=None)


pendientes = Pendientes()
segundo_plano.lanzar = pendientes
try:
    unidad = tmpdir("prdrive-lecturas-sonda-")
    estado = estado_de(unidad)
    sonda = la.sonda_de(estado)
    la.sonda_de(estado)
    c("la sonda de una unidad se lanza una sola vez",
      (len(pendientes.encargos), sonda.unidad), (1, unidad))
    c("  y se guarda en el estado de su unidad", estado.sondas[unidad] is sonda, True)
    c("mientras escribe, está midiendo", la.midiendo(estado), True)
    c("  y la línea dice que mide", la.texto_espera(estado, 1024 ** 3), la.MIDIENDO)
    c("  sin lanzar otra", len(pendientes.encargos), 1)

    pendientes.encargos[0].resultado, pendientes.encargos[0].hecho = 10 * 1024 ** 2, True
    c("cuando acaba, deja de medir", la.midiendo(estado), False)
    c("  y la división sale del resultado",
      la.texto_espera(estado, 100 * 1024 ** 2),
      "Hay que escribir el contenedor entero: "
      + crypto.describir_espera(10.0) + ".")
    c("  y lo guarda en el estado", estado.velocidad_escritura, 10 * 1024 ** 2)

    # Una sonda que falla: 0.0 es «medido y no se ha podido», no otra sonda.
    estado_fallo = estado_de(tmpdir("prdrive-lecturas-sonda-"))
    la.sonda_de(estado_fallo)
    pendientes.encargos[-1].error, pendientes.encargos[-1].hecho = OSError("x"), True
    texto_fallo = la.texto_espera(estado_fallo, 1024 ** 3)
    c("una sonda que falla dice que no se ha podido medir",
      (estado_fallo.velocidad_escritura, texto_fallo),
      (0.0, "Hay que escribir el contenedor entero: "
            + crypto.describir_espera(None) + "."))
    c("  y no lanza otra", len(pendientes.encargos), 2)

    # El tope: una sonda que no contesta deja de contar como medición.
    la.TOPE_SONDA_S = 0.05
    colgada = estado_de(tmpdir("prdrive-lecturas-sonda-"))
    la.sonda_de(colgada)
    c("una sonda dentro de su tope, escribiendo", la.midiendo(colgada), True)
    time.sleep(0.08)
    c("  y pasado su tope ya no", la.midiendo(colgada), False)
    c("  y la línea dice que no se ha podido medir",
      la.texto_espera(colgada, 1024 ** 3),
      "Hay que escribir el contenedor entero: " + crypto.describir_espera(None) + ".")
    c("  sin lanzar otra", len(pendientes.encargos), 3)
    c("sin unidad no hay sonda que mirar", la.midiendo(estado_de(None)), False)
    c("el tiempo que queda nunca es negativo", la.quedan_s(colgada.sondas[colgada.device]), 0.0)
finally:
    segundo_plano.lanzar = LANZAR_REAL
    la.TOPE_SONDA_S = TOPE_REAL

# Al cerrar se espera a la sonda que aún escribe: y se acaba, lo que tarde menos que el tope.
ESCRIBIENDO = Path(tmpdir("prdrive-lecturas-cerrar-"))


def medir_lenta(root, muestra=0):
    """Una sonda que tarda: deja su temporal mientras escribe y lo quita al acabar."""
    temporal = Path(root) / crypto.SONDA_NOMBRE
    try:
        temporal.write_bytes(b"\0" * 4096)
        time.sleep(0.3)
        return 1024.0 ** 2
    finally:
        temporal.unlink(missing_ok=True)


real_medir = crypto.medir_escritura
crypto.medir_escritura = medir_lenta
try:
    segundo_plano.lanzar = LANZAR_REAL
    estado = estado_de(ESCRIBIENDO)
    la.sonda_de(estado)
    for _ in range(200):                  # que el hilo haya empezado a escribir
        if (ESCRIBIENDO / crypto.SONDA_NOMBRE).exists():
            break
        time.sleep(0.01)
    existia_al_cerrar = (ESCRIBIENDO / crypto.SONDA_NOMBRE).exists()
    la.esperar_sondas(estado)
    c("con una sonda escribiendo, el temporal existe al cerrar",
      existia_al_cerrar, True)
    c("al cerrar se espera a la sonda: ya terminó",
      estado.sondas[ESCRIBIENDO].encargo.hecho, True)
    c("  y el temporal se ha quitado", (ESCRIBIENDO / crypto.SONDA_NOMBRE).exists(), False)
    c("  y su medida llega", estado.sondas[ESCRIBIENDO].encargo.resultado, 1024.0 ** 2)
finally:
    crypto.medir_escritura = real_medir
    segundo_plano.lanzar = LANZAR_REAL

# Sin esperar más de su tope: una sonda que no acaba no retiene el cierre.
la.TOPE_SONDA_S = 0.1
colgada_real = Pendientes()
segundo_plano.lanzar = colgada_real
try:
    estado = estado_de(tmpdir("prdrive-lecturas-cerrar-"))
    la.sonda_de(estado)
    inicio = time.monotonic()
    la.esperar_sondas(estado)
    tardo = time.monotonic() - inicio
    c("una sonda que no acaba se espera solo hasta su tope",
      (tardo < 1.0, estado.sondas[estado.device].encargo.hecho), (True, False))
finally:
    segundo_plano.lanzar = LANZAR_REAL
    la.TOPE_SONDA_S = TOPE_REAL


# 3. El examen de la carpeta del contenedor: manda la carpeta si no vale
examinar_real = raiz_equipo.examinar_contenedor
examinar_carpeta_real = raiz_equipo.examinar
try:
    raiz_equipo.examinar_contenedor = lambda f, carpeta, forma: raiz_equipo.Examen(
        raiz_equipo.NUEVA, f"contenedor en {f}")
    raiz_equipo.examinar = lambda carpeta, forma: raiz_equipo.Examen(
        raiz_equipo.NO_VALE, f"{carpeta} tiene cosas")
    sin_punto = la.examen_contenedor("/x", "/y", raiz_equipo.PROPIA, False)
    con_punto = la.examen_contenedor("/x", "/y", raiz_equipo.PROPIA, True)
    c("sin carpeta de montaje (Windows) manda el contenedor",
      (sin_punto.vale, sin_punto.texto), (True, "contenedor en /x"))
    c("con carpeta de montaje, la que no vale manda",
      (con_punto.vale, con_punto.texto), (False, "/y tiene cosas"))
finally:
    raiz_equipo.examinar_contenedor = examinar_real
    raiz_equipo.examinar = examinar_carpeta_real


# 4. La ruta a mano, el Python del equipo, la verificación y el espacio libre
volumen_real = device.volume_for
try:
    carpeta = tmpdir("prdrive-lecturas-ruta-")
    c("una ruta que no existe lo dice",
      la.examinar_ruta(carpeta / "no-existe"), f"No existe la carpeta {carpeta / 'no-existe'}.")
    device.volume_for = lambda r: device.Volume(root=Path(r), label="SISTEMA",
                                                is_system=True)
    c("la unidad del sistema no vale", la.examinar_ruta(carpeta),
      "Esa es la unidad del sistema.")
    device.volume_for = lambda r: device.Volume(root=Path(r), label="PEN")
    c("una carpeta de una unidad normal vale", la.examinar_ruta(carpeta), "")
finally:
    device.volume_for = volumen_real

python_real = device.check_python
llamadas: list = []


def python_que_falla():
    """Una pregunta al Python que se cae."""
    llamadas.append(1)
    raise OSError("no contesta")


try:
    device.check_python = lambda root=None: device.Check("Python", True, "3.14")
    c("el Python del equipo se pregunta en una unidad", la.python_del_equipo("unidad"),
      device.Check("Python", True, "3.14"))
    c("y no se pregunta en este equipo", la.python_del_equipo("equipo"), None)
    device.check_python = python_que_falla
    c("si la pregunta falla, la fila sale «sin comprobar» (None)",
      (la.python_del_equipo("unidad"), len(llamadas)), (None, 1))
finally:
    device.check_python = python_real

verify_real = device.verify_device
vestibulo_real, traveler_real, restos_real = (
    vestibulo.comprobar, traveler.comprobar, crypto.comprobar_restos)
mirado: list = []
try:
    device.verify_device = lambda raiz, esperadas=None, key_name=None: [
        device.Check("Dispositivo", True, "ok")]
    vestibulo.comprobar = lambda unidad, control: (mirado.append("vestibulo"),
                                                   [device.Check("Entrada", True, "")])[1]
    traveler.comprobar = lambda unidad: (mirado.append("viajero"),
                                         [device.Check("VeraCrypt", True, "")])[1]
    crypto.comprobar_restos = lambda unidad: (mirado.append("restos"),
                                              [device.Check("Restos", "aviso", "x")])[1]
    sin_cifrar = la.comprobaciones_dispositivo("/r", ["p0"], None, "none", "/u")
    c("sin VeraCrypt solo se mira el dispositivo", (sin_cifrar, mirado),
      ([("Dispositivo", True, "ok")], []))
    con = la.comprobaciones_dispositivo("/r", ["p0"], None, "veracrypt", "/u")
    c("con VeraCrypt se mira también la unidad de fuera, en su orden",
      (mirado, [f[0] for f in con]),
      (["vestibulo", "viajero", "restos"], ["Dispositivo", "Entrada", "VeraCrypt", "Restos"]))
    c("y las filas son (nombre, estado, detalle)", con[1], ("Entrada", True, ""))
    # Sin unidad de fuera no hay entrada, viajero ni restos que mirar, aunque sea
    # con VeraCrypt: no se pregunta por una unidad que no se conoce.
    for sin_unidad in (None, ""):
        mirado.clear()
        sin_fuera = la.comprobaciones_dispositivo("/r", ["p0"], None, "veracrypt",
                                                  sin_unidad)
        c(f"con VeraCrypt y unidad {sin_unidad!r}, solo se mira el dispositivo",
          (sin_fuera, mirado), ([("Dispositivo", True, "ok")], []))
finally:
    device.verify_device = verify_real
    vestibulo.comprobar, traveler.comprobar, crypto.comprobar_restos = (
        vestibulo_real, traveler_real, restos_real)

c("libre dice 0 si no puede saber el espacio",
  la.libre(tmpdir() / "no-existe" / "nada"), 0)
c("  y los bytes libres de una carpeta que existe",
  la.libre(tmpdir()) > 0, True)

c("el módulo nunca ha cargado tkinter", "tkinter" in sys.modules, False)
sys.exit(c.report())
