#!/usr/bin/env python3
"""Las lecturas del asistente de instalación y de «En este equipo», sin Tk.

Son las mitades que deciden o que tocan el disco, la red o un subproceso, y
devuelven un dato para pintar: la ruta a mano que se mira, el Python del
equipo, la verificación de un dispositivo, el examen de una carpeta escrita y
la sonda que mide lo que escribe una unidad. Los `tk_*` las llaman por el
módulo (`lecturas_asistente.nombre(...)`), así que los tests las sustituyen
aquí.

Nada de este módulo importa `tkinter`, ni siquiera dentro de una función. Lo
que necesita un widget llega como argumento (la caja que ancla una espera, el
`Sondeo` que la recoge): basta con que tenga `after`, `after_cancel` y `bind`.
Los módulos pesados de `install/` se importan dentro de la función que los usa.
"""

from __future__ import annotations

import time
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from . import segundo_plano

if TYPE_CHECKING:
    from install import device

ESPERA_TECLA_MS = 250
"""Milisegundos sin teclear antes de examinar lo escrito en una caja.

Se lee en cada tecla, no al importar: los tests lo ponen a 0 y mueven el bucle
de eventos después de escribir.
"""

MIDIENDO = "Midiendo lo que escribe la unidad…"
"""Lo que dice la línea de la espera mientras corre la sonda de escritura."""

TOPE_SONDA_S = 60.0  # segundos
"""Cuánto se espera a la sonda antes de dejar crear el contenedor sin su medida.

Un hilo no se puede cortar: pasado esto se dice que no se ha podido medir y
«Crear y montar» vuelve, y si la sonda contesta después se usa lo que diga. Se
lee al usarlo: los tests lo acortan.
"""


def examinar_ruta(destino: Path) -> str:
    """Mira si una ruta escrita a mano vale de destino para instalar.

    Corre en un hilo (`segundo_plano`): `is_dir()` de una carpeta de red que no
    contesta espera lo que tarde el sistema en rendirse, y `volume_for()`
    recorre las unidades.

    Args:
        destino: La ruta tal como se escribió, ya convertida a `Path`.

    Returns:
        Por qué no vale, o `''` si vale.
    """
    from install import device

    if not destino.is_dir():
        return f"No existe la carpeta {destino}."
    if device.volume_for(destino).is_system:
        return "Esa es la unidad del sistema."
    return ""


def python_del_equipo(donde: str) -> device.Check | None:
    """Pregunta con qué Python arrancaría lo instalado en este equipo.

    Va dentro del trabajo de «Comprobar», en su hilo: preguntarle a un Python
    puede tardar, y el paso no se queda parado mientras. Que la pregunta falle
    no tumba la comprobación del remoto, que es lo que decide si se sigue: la
    fila sale «sin comprobar».

    Args:
        donde: El recorrido (`Wizard.donde`). En este equipo no se pregunta: la
            raíz la sincroniza el agente con el suyo, que se instala en
            «Instalación».

    Returns:
        Lo que dice `device.check_python()`, o `None` si no toca o falló.
    """
    from install import device

    if donde == "equipo":
        return None
    try:
        return device.check_python()
    except Exception:                                    # noqa: BLE001 — «sin comprobar»
        return None


def comprobaciones_dispositivo(
        raiz, elegidas: list[str], clave: str | None, cifrado: str,
        unidad) -> list[tuple[str, bool | str | None, str]]:
    """Devuelve las filas de la verificación de un dispositivo, sin pintar nada.

    Mira el dispositivo, y con VeraCrypt la unidad de fuera: es lo que hace
    `_paso_final` en un hilo (`segundo_plano`), así que devuelve datos y no
    toca Tk. Vive aquí y no en `install/` porque junta lo que dicen varios
    módulos de `install/` solo para la tabla de ese paso (el precedente es
    `tk_equipo.comprobaciones()`).

    Args:
        raiz: La raíz del dispositivo (con VeraCrypt, lo montado).
        elegidas: Las parejas que tienen que estar en el config.
        clave: El nombre del fichero de clave del remoto, o `None` si la
            conexión no usa ninguno.
        cifrado: Cómo va cifrado (`InstallState.encryption`).
        unidad: La unidad física (`InstallState.device`): con VeraCrypt, donde
            van la entrada de fuera, el VeraCrypt que viaja y los restos.

    Returns:
        `(nombre, estado, detalle)` por comprobación, como las pinta
        `tabla_estado`.
    """
    from install import crypto, device, traveler, vestibulo

    checks = device.verify_device(raiz, elegidas, clave)
    # Solo con contenedor: sin él no hay nada que montar en el otro equipo, y
    # una fila roja diciendo que falta VeraCrypt sería mentira. Lo mismo con la
    # instalación en claro que quedó fuera: solo es un resto cuando la de verdad
    # está dentro de un contenedor.
    if cifrado == "veracrypt" and unidad:
        checks += vestibulo.comprobar(unidad, device.control_id(raiz))
        checks += traveler.comprobar(unidad)
        checks += crypto.comprobar_restos(unidad)
    return [(c.etiqueta, c.ok, c.detalle) for c in checks]


def libre(root) -> int:
    """Devuelve los bytes libres de ese volumen, o 0 si no se pueden saber.

    Args:
        root: Una carpeta del volumen.
    """
    import shutil

    try:
        return shutil.disk_usage(str(root)).free
    except OSError:
        return 0


class ExamenDiferido:
    """Examina lo escrito en una o varias cajas fuera del hilo de Tk, al dejar de teclear.

    Cada tecla (`tecla()`) deja en el acto lo que depende del examen como
    pendiente (`al_teclear`) y rearma una única espera de `ESPERA_TECLA_MS`
    colgada de `ancla`, nunca de la ventana: cambiar de paso destruye la caja
    y la espera muere con ella sin examinar nada. Al vencer, o con `ya()`, se
    lee la clave (lo escrito AHORA, no el texto que vio `validatecommand`) y
    el examen va a `segundo_plano.lanzar()` como `partial(funcion, *clave)`; lo
    recoge `sondeo`. Lo que llega solo cuenta si la clave sigue siendo la
    misma: el examen de un texto viejo no cuenta.

    Args:
        ancla: La caja de la que cuelgan la espera y el sondeo. Basta con que
            tenga `after`, `after_cancel` y `bind`, como un widget de Tk.
        clave: Devuelve lo que se examina, leído de las cajas en el hilo de Tk.
        funcion: El examen. Recibe la clave desplegada, no toca Tk y es una
            función de módulo (o un `partial` de datos).
        al_teclear: Deja en el acto lo que depende del examen como pendiente.
        al_llegar: Recibe el `Encargo` del examen de lo que sigue escrito.
        sondeo: El `ui.tk.Sondeo` que recoge el examen. Debe colgar de `ancla`,
            para que cambiar de paso cancele también la espera de la lectura.

    Attributes:
        examinada: La clave del último examen que contó, o `None` desde la
            última tecla.
        resultado: Lo que devolvió ese examen (`None` si falló).
        sondeo: El `Sondeo` del examen en curso.
    """

    def __init__(self, ancla, clave, funcion, al_teclear, al_llegar, sondeo) -> None:
        """Engancha la espera a la caja; no examina nada todavía."""
        self.ancla = ancla
        self.clave = clave
        self.funcion = funcion
        self.al_teclear = al_teclear
        self.al_llegar = al_llegar
        self.examinada = None
        self.resultado = None
        self.sondeo = sondeo
        self._id = None
        ancla.bind("<Destroy>", self._al_destruir, add="+")

    def tecla(self, *_) -> None:
        """Deja el examen pendiente y rearma la espera; es lo que hace cada tecla."""
        self._olvidar()
        self.al_teclear()
        self._quitar_espera()
        self._id = self.ancla.after(ESPERA_TECLA_MS, self._vencer)

    def ya(self) -> None:
        """Examina lo escrito ahora mismo, sin esperar a que se deje de teclear."""
        self._quitar_espera()
        self._olvidar()
        self._lanzar()

    def vigente(self):
        """Devuelve el último examen si es de lo que hay escrito ahora, o `None`."""
        if self.examinada is not None and self.examinada == self.clave():
            return self.resultado
        return None

    def _olvidar(self) -> None:
        """Da por caducado el último examen."""
        self.examinada = self.resultado = None

    def _lanzar(self) -> None:
        """Encarga el examen de lo escrito ahora."""
        clave = self.clave()
        encargo = segundo_plano.lanzar(partial(self.funcion, *clave))
        self.sondeo.esperar(encargo, partial(self._llega, clave))

    def _llega(self, clave, encargo) -> None:
        """Aplica el examen si lo escrito sigue siendo lo examinado."""
        if clave != self.clave():
            return               # se escribió otra cosa: su examen está en camino
        self.examinada = clave
        self.resultado = encargo.resultado if encargo.error is None else None
        self.al_llegar(encargo)

    def _vencer(self) -> None:
        """Se ha dejado de teclear: examina."""
        self._id = None
        self._lanzar()

    def _quitar_espera(self) -> None:
        """Cancela la espera de la última tecla, si la hay."""
        if self._id is not None:
            try:
                self.ancla.after_cancel(self._id)
            except Exception:                            # noqa: BLE001 — ya no está
                pass
            self._id = None

    def _al_destruir(self, evento) -> None:
        """Cancela la espera si lo que se destruye es la caja, no un hijo suyo."""
        if str(evento.widget) == str(self.ancla):
            self._quitar_espera()


def examen_contenedor(fisica: str, carpeta: str, forma: str, con_punto: bool):
    """Examina dónde irá el contenedor y, si se monta en una carpeta, esa carpeta.

    No toca Tk: es lo que corre en el hilo del paso del contenedor. En Linux la
    carpeta donde se abre es la raíz, así que también tiene que poder serlo.

    Args:
        fisica: Dónde va el `.hc`.
        carpeta: Dónde se monta (Linux) o la carpeta de la raíz (Windows).
        forma: La forma de la raíz (`raiz_equipo.PROPIA`, …).
        con_punto: Si se monta en `carpeta` (Linux).

    Returns:
        El `raiz_equipo.Examen` que manda: el de la carpeta si no vale, si no
        el del contenedor.
    """
    from install import raiz_equipo

    examen = raiz_equipo.examinar_contenedor(fisica, carpeta, forma)
    if con_punto:
        raiz_examen = raiz_equipo.examinar(carpeta, forma)
        if not raiz_examen.vale:
            examen = raiz_examen
    return examen


def examen_fallido(encargo):
    """Devuelve el examen que se enseña cuando el examen mismo ha fallado.

    Args:
        encargo: El `Encargo` del examen, con su `error`.

    Returns:
        Un `raiz_equipo.Examen` que no vale y dice qué pasó.
    """
    from install import raiz_equipo

    return raiz_equipo.Examen(raiz_equipo.NO_VALE,
                              f"No se ha podido examinar la carpeta: {encargo.error}")


class Sonda(NamedTuple):
    """La medida de lo que escribe un volumen, lanzada una sola vez.

    Args:
        unidad: La raíz del volumen físico donde se escribe.
        encargo: El `segundo_plano.Encargo` que corre `crypto.medir_escritura`.
        lanzada: `time.monotonic()` al lanzarla: el tope cuenta desde ahí.
    """

    unidad: Path
    encargo: segundo_plano.Encargo
    lanzada: float


def sonda_de(estado) -> Sonda:
    """Devuelve la sonda del volumen de `estado.device`, lanzándola si no la hay.

    Escribe 8 MiB en el dispositivo, así que se lanza una vez por volumen y
    asistente: la guarda `estado.sondas`, que sobrevive a repintar el panel, y
    una que ya acabó (aunque nadie la haya mirado todavía) no se repite. Va por
    `segundo_plano.lanzar()` con la función de módulo leída al lanzarla.

    Args:
        estado: El `InstallState` del asistente.
    """
    from install import crypto

    unidad = Path(estado.device)
    sonda = estado.sondas.get(unidad)
    if sonda is None:
        encargo = segundo_plano.lanzar(partial(crypto.medir_escritura, unidad))
        sonda = estado.sondas[unidad] = Sonda(unidad, encargo, time.monotonic())
    return sonda


def quedan_s(sonda: Sonda) -> float:
    """Devuelve los segundos que quedan para el tope de esa sonda, sin ser negativos.

    Args:
        sonda: La sonda, lanzada por `sonda_de()`.
    """
    return max(0.0, sonda.lanzada + TOPE_SONDA_S - time.monotonic())


def midiendo(estado) -> bool:
    """Indica si la sonda del volumen de `estado.device` escribe todavía, sin pasar su tope.

    Args:
        estado: El `InstallState` del asistente.
    """
    if estado.device is None:
        return False
    sonda = estado.sondas.get(Path(estado.device))
    return (sonda is not None and not sonda.encargo.hecho
            and time.monotonic() - sonda.lanzada < TOPE_SONDA_S)


def texto_espera(estado, bytes_: int) -> str:
    """Devuelve lo que tardará crear un contenedor fijo de `bytes_`, según la sonda.

    Lanza la sonda si este volumen no la tiene. Mientras escribe, dice que
    mide; pasado su tope sin respuesta, que no se ha podido; con su resultado
    lo guarda en `estado.velocidad_escritura` (0.0 si falló) y divide.

    Args:
        estado: El `InstallState` del asistente.
        bytes_: Lo que ocupará el contenedor.

    Returns:
        La frase para la línea de la espera.
    """
    from install import crypto

    encargo = sonda_de(estado).encargo
    if not encargo.hecho:
        if midiendo(estado):
            return MIDIENDO
        velocidad = None
    else:
        # 0.0 es «medido y no se ha podido»: lo que dijo la sonda, no otra sonda.
        velocidad = estado.velocidad_escritura = (
            (encargo.resultado if encargo.error is None else None) or 0.0)
    segundos = bytes_ / velocidad if velocidad else None
    return f"Hay que escribir el contenedor entero: {crypto.describir_espera(segundos)}."


def esperar_sondas(estado) -> None:
    """Espera, como mucho hasta su tope, a las sondas que aún escriben.

    Es lo que hace el asistente al cerrarse: un hilo no se puede cortar, y si el
    proceso acaba a mitad de la medida, `medir_escritura` no llega a borrar su
    `.prdrive-sonda.tmp` de la unidad de la persona. Una sonda ya terminada no
    cuesta nada.

    Args:
        estado: El `InstallState` del asistente; sus `sondas` son `Sonda`.
    """
    for sonda in list(estado.sondas.values()):
        while not sonda.encargo.hecho and quedan_s(sonda) > 0:
            time.sleep(0.02)
