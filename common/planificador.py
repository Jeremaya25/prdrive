#!/usr/bin/env python3
"""Qué le toca hacer ahora al agente, y cuándo volver a mirar.

Es la cabeza de `agente.py` y es PURO: sin reloj, ni disco, ni procesos. Recibe
todo como datos (las raíces que atiende y su estado, cómo le fue a cada pareja
la última vez, la batería, la red, la hora) y devuelve una decisión. Así cada
regla se prueba con una tabla de casos y un reloj de mentira
(`tests/test_planificador.py`), sin lanzar un solo proceso.

Las reglas, en el orden en que se aplican:
- Una cola para todo el equipo: mientras hay una pasada en marcha no se decide
  otra, sea de la raíz del equipo o de una unidad. Ahorra ancho de banda y
  evita que la misma pareja, en el equipo y en la unidad enchufada, vaya contra
  el mismo `remote_path` a la vez.
- «Sincronizar ahora» va primero y se salta toda la moderación (pausa, batería,
  red de uso medido, espera tras un fallo y «sin conexión»): lo ha pedido
  alguien que está delante.
- Moderarse: en pausa, con la batería por debajo del mínimo o en una red de uso
  medido (si la política lo dice) no se lanza nada.
- Sin conexión: lo que va a un remoto que ha fallado por red no se lanza pareja
  tras pareja para que falle igual; se sondea ese remoto (`Tarea` de tipo
  `SONDA`) y, cuando contesta, sus parejas vuelven. Se sondea cuando el sistema
  dice que la red ha cambiado (`common/red.py`), una vez por ráfaga de avisos
  (`CambioDeRed`), y si no, de tarde en tarde (`sondeo()`): cada 5 min donde
  no hay avisos, cada 30 donde los hay y el temporizador solo es el respaldo.
- Espera creciente por pareja: `intervalo · 2^k` tras k fallos seguidos, con
  tope de 4 h, y a cero tras una pasada buena.
- Una raíz bloqueada, ausente, en pausa o apartada simplemente no está: no es
  un fallo, no hace esperar más y no avisa de nada.

Nada de esto hace un `--resync`: una pareja que lo pide la salta su propio
`sync.py` (sin terminal la pregunta toma el «no») y aquí cuenta como `SALTADA`,
que no es ni un fallo ni una pasada buena.

`Pregunta` es el plazo de «¿Atender esta unidad?». Es también un dato del
planificador y no de la ventana que la hace, para que la cuenta atrás no
dependa de que la ventana llegue a abrirse ni una respuesta tardía cuente.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Iterable, Mapping

# El tipo de cada tarea.
PASADA = "pasada"
SONDA = "sonda"

# Cómo acabó una pasada, tal como se lo cuenta el agente al planificador.
OK = "ok"
FALLO = "fallo"
RED = "red"             # falló, y por la red: el remoto pasa a «sin conexión»
SALTADA = "saltada"     # pedía --resync y nadie lo ha aprobado

HORA = 3600.0
"""Segundos que tiene una hora."""


@dataclass(frozen=True)
class Politica:
    """Cómo se modera el agente.

    Sale de `agente.json`; aquí están sus valores de fábrica, que son los del
    diseño: sincroniza con batería, se para por debajo del 20 % y se pausa en
    una red de uso medido.

    Args:
        con_bateria: Si se sincroniza funcionando a batería.
        bateria_minima: Porcentaje por debajo del cual se para.
        pausar_red_medida: Si se pausa en una red de uso medido.
        tope_espera: Segundos máximos de espera tras fallos seguidos.
        sondeo_sin_conexion: Segundos entre sondas de un remoto sin conexión
            cuando el sistema no avisa de los cambios de red.
        sondeo_de_respaldo: Segundos entre sondas de un remoto sin conexión
            cuando el sistema sí avisa (`common/red.py`): la sonda va con cada
            cambio de red y el temporizador solo cubre lo que el aviso no ve,
            sobre todo el remoto que vuelve sin que cambie nada en este equipo
            (el NAS que se enciende). Es el intervalo de fábrica del servicio:
            ese remoto se nota, como mucho, una pasada normal más tarde.
        mirar_maximo: Cada cuánto se vuelve a mirar como mucho, aunque nada
            toque: el entorno (batería, red) se lee de nuevo en cada vuelta y
            puede haber cambiado.
        mirar_ocupado: Con una pasada en marcha, cada cuánto se mira si ha
            terminado.
    """
    con_bateria: bool = True
    bateria_minima: int = 20
    pausar_red_medida: bool = True
    tope_espera: float = 4 * HORA
    sondeo_sin_conexion: float = 5 * 60.0
    sondeo_de_respaldo: float = 30 * 60.0
    mirar_maximo: float = 60.0
    mirar_ocupado: float = 2.0


@dataclass(frozen=True)
class Pareja:
    """Una pareja de una raíz, con el remote al que va.

    Args:
        nombre: Nombre de la pareja.
        remoto: El remote de rclone al que va; agrupa el «sin conexión».
    """
    nombre: str
    remoto: str = ""


@dataclass(frozen=True)
class Raiz:
    """Una raíz atendida: la del equipo o una unidad.

    `atendible` resume su estado (abierta y sin nadie más sirviéndola); el
    motivo cuando no lo es lo sabe el agente, que es quien lo enseña.

    Args:
        clave: Identificador de la raíz.
        parejas: Sus parejas.
        intervalo: Segundos entre pasadas; infinito es el modo `sync` (una
            pasada por conexión y ya).
        atendible: Si se la puede atender ahora.
    """
    clave: str
    parejas: tuple[Pareja, ...]
    intervalo: float                    # segundos
    atendible: bool = True


@dataclass(frozen=True)
class Marca:
    """Lo que se recuerda de una pareja entre pasadas.

    Args:
        ultimo_intento: Cuándo se intentó por última vez, o `None` si nunca o
            si tocó volver a intentarlo.
        fallos: Fallos seguidos.
    """
    ultimo_intento: float | None = None
    fallos: int = 0


@dataclass(frozen=True)
class Entorno:
    """Lo que el agente ha medido fuera; todo son sondas sustituibles.

    Args:
        pausado: Si el usuario ha pausado el agente.
        con_bateria: Si el equipo funciona ahora a batería.
        bateria: Porcentaje de batería, si se sabe.
        red_medida: Si la red es de uso medido; `None` es «no se sabe» y cuenta
            como normal.
        sin_conexion: `(raíz, remoto)` sin conexión, con cuándo toca sondearlo
            otra vez.
    """
    pausado: bool = False
    con_bateria: bool = False
    bateria: int | None = None
    red_medida: bool | None = None
    sin_conexion: Mapping[tuple[str, str], float] = field(default_factory=dict)


@dataclass(frozen=True)
class Tarea:
    """Una pasada de una pareja o la sonda de un remoto.

    Args:
        tipo: `PASADA` o `SONDA`.
        raiz: Clave de la raíz.
        pareja: Nombre de la pareja; `None` en una sonda.
        remoto: El remote de rclone.
        urgente: Si la pidió alguien a mano («Sincronizar ahora»).
    """
    tipo: str
    raiz: str
    pareja: str | None = None
    remoto: str = ""
    urgente: bool = False


@dataclass(frozen=True)
class Decision:
    """Lo que decide el planificador.

    Args:
        tarea: La tarea a lanzar, o `None` si no toca nada.
        mirar_en: Segundos hasta la próxima vuelta.
        retenido: Por qué no se lanza nada, si es global.
    """
    tarea: Tarea | None
    mirar_en: float
    retenido: str | None = None


def espera(intervalo: float, fallos: int, tope: float = 4 * HORA) -> float:
    """Devuelve cuánto esperar tras la última pasada: `intervalo · 2^fallos`, con tope.

    El tope nunca acorta el intervalo elegido: con un intervalo de 6 h, fallar
    no puede hacer que se intente antes que sin fallar.
    """
    if fallos <= 0 or math.isinf(intervalo):
        return intervalo
    return min(intervalo * (2 ** min(fallos, 32)), max(tope, intervalo))


def registrar(marca: Marca, resultado: str, ahora: float) -> Marca:
    """Devuelve la marca de una pareja después de una pasada.

    Una pasada de `RED` no cuenta como intento: la pareja espera al remoto, no
    a su intervalo, y en cuanto la sonda diga que contesta vuelve a tocarle.
    Tampoco suma un fallo: el problema es la red, no la pareja.
    """
    if resultado == OK or resultado == SALTADA:
        return Marca(ahora, 0)
    if resultado == RED:
        return Marca(None, marca.fallos)
    return Marca(ahora, marca.fallos + 1)


def empieza_a_fallar(antes: Marca, despues: Marca) -> bool:
    """Indica si esta pasada es la primera que falla.

    Solo entonces se avisa: un servicio que lleva horas sin poder no manda un
    aviso por ciclo.
    """
    return antes.fallos == 0 and despues.fallos > 0


def moderacion(entorno: Entorno, politica: Politica) -> str | None:
    """Devuelve por qué no se lanza nada ahora mismo.

    Returns:
        El motivo, o `None` si se puede lanzar.
    """
    if entorno.pausado:
        return "en pausa"
    if entorno.con_bateria:
        if not politica.con_bateria:
            return "funcionando con batería"
        if entorno.bateria is not None and entorno.bateria < politica.bateria_minima:
            return f"batería por debajo del {politica.bateria_minima} %"
    if entorno.red_medida and politica.pausar_red_medida:
        return "red de uso medido"
    return None


def decidir(raices: Iterable[Raiz], marcas: Mapping[tuple[str, str], Marca],
            entorno: Entorno, ahora: float, politica: Politica = Politica(),
            ocupado: bool = False,
            urgentes: Iterable[tuple[str, str]] = ()) -> Decision:
    """Devuelve la siguiente tarea o, si no hay, cuándo volver a mirar.

    Args:
        raices: Las raíces que atiende el agente.
        marcas: Lo recordado de cada pareja, por `(raíz, pareja)`.
        entorno: Lo medido fuera.
        ahora: La hora, en segundos.
        politica: La moderación.
        ocupado: Si ya hay una pasada en marcha.
        urgentes: `(raíz, pareja)` pedidos a mano, en el orden en que se
            pidieron.
    """
    if ocupado:
        return Decision(None, politica.mirar_ocupado)

    raices = [r for r in raices if r.atendible]
    por_clave = {r.clave: r for r in raices}

    # 1. Lo pedido a mano, en el orden en que se pidió.
    for clave, nombre in urgentes:
        raiz = por_clave.get(clave)
        pareja = next((p for p in raiz.parejas if p.nombre == nombre), None) if raiz else None
        if pareja is not None:
            return Decision(Tarea(PASADA, clave, nombre, pareja.remoto, urgente=True),
                            politica.mirar_ocupado)

    # 2. Moderarse.
    motivo = moderacion(entorno, politica)
    if motivo is not None:
        return Decision(None, politica.mirar_maximo, motivo)

    proxima = ahora + politica.mirar_maximo

    # 3. Los remotos sin conexión: se sondean, no se prueban pareja a pareja.
    for (clave, remoto), cuando in sorted(entorno.sin_conexion.items(),
                                          key=lambda kv: kv[1]):
        if clave not in por_clave:
            continue
        if cuando <= ahora:
            return Decision(Tarea(SONDA, clave, None, remoto), politica.mirar_ocupado)
        proxima = min(proxima, cuando)

    # 4. La pareja que más tiempo lleva esperando su turno.
    elegida: tuple[float, Tarea] | None = None
    for raiz in raices:
        for pareja in raiz.parejas:
            if (raiz.clave, pareja.remoto) in entorno.sin_conexion:
                continue
            marca = marcas.get((raiz.clave, pareja.nombre), Marca())
            if marca.ultimo_intento is None:
                toca = -math.inf        # nunca se ha intentado: ya
            else:
                toca = marca.ultimo_intento + espera(raiz.intervalo, marca.fallos,
                                                     politica.tope_espera)
            if toca <= ahora:
                if elegida is None or toca < elegida[0]:
                    elegida = (toca, Tarea(PASADA, raiz.clave, pareja.nombre,
                                           pareja.remoto))
            else:
                proxima = min(proxima, toca)
    if elegida is not None:
        return Decision(elegida[1], politica.mirar_ocupado)
    return Decision(None, max(1.0, proxima - ahora))


def sin_conexion(entorno: Entorno, raiz: str, remoto: str,
                 proxima_sonda: float) -> Entorno:
    """Devuelve el entorno con ese remoto marcado sin conexión.

    Tras la primera pasada que falla por red la sonda va enseguida: si el
    remoto contesta, aquel fallo no era de la red (ver `agente.py`). Una sonda
    que falla pone la siguiente a lo que diga `sondeo()`.

    Args:
        proxima_sonda: Cuándo toca sondarlo.
    """
    nuevo = dict(entorno.sin_conexion)
    nuevo[(raiz, remoto)] = proxima_sonda
    return replace(entorno, sin_conexion=nuevo)


def con_conexion(entorno: Entorno, raiz: str, remoto: str) -> Entorno:
    """Devuelve el entorno con ese remoto otra vez disponible."""
    nuevo = {k: v for k, v in entorno.sin_conexion.items() if k != (raiz, remoto)}
    return replace(entorno, sin_conexion=nuevo)


def sondear_ya(entorno: Entorno, ahora: float) -> Entorno:
    """Devuelve el entorno con la sonda de cada remoto sin conexión adelantada a ahora.

    Es lo que piden «Probar ahora», la vuelta de la suspensión y una ráfaga de
    cambios de red ya asentada. La que ya tocaba antes se queda como estaba.
    """
    return replace(entorno, sin_conexion={k: min(v, ahora)
                                          for k, v in entorno.sin_conexion.items()})


def sondeo(politica: Politica, avisa_la_red: bool) -> float:
    """Devuelve cuánto esperar a la siguiente sonda de un remoto que no contesta.

    Args:
        politica: La moderación.
        avisa_la_red: Si el sistema dice ahora al agente cuándo cambia la red
            (`common/red.py`). Entonces la sonda va con el aviso y esto es
            solo el respaldo.
    """
    return politica.sondeo_de_respaldo if avisa_la_red else politica.sondeo_sin_conexion


ASENTAR_RED = 5.0
"""Segundos sin otro aviso de cambio de red antes de sondear.

Una red que vuelve avisa varias veces seguidas (cada interfaz, cada dirección,
la comprobación de conectividad): se sondea cuando se calma, una vez por
ráfaga, y para entonces el DHCP y el DNS ya han terminado.
"""
TOPE_RAFAGA_RED = 30.0
"""Segundos como mucho entre el primer aviso de una ráfaga y su sonda.

Una red que no para de cambiar (un Wi-Fi que cae y sube) no la aplaza siempre.
"""


@dataclass(frozen=True)
class CambioDeRed:
    """Una ráfaga de avisos de «la red ha cambiado» que todavía no se ha sondeado.

    Args:
        primero: Cuándo llegó el primer aviso de la ráfaga.
        ultimo: Cuándo llegó el último.
    """
    primero: float
    ultimo: float

    @property
    def sondear_en(self) -> float:
        """Devuelve cuándo toca sondear: asentada la ráfaga, o a su tope."""
        return min(self.ultimo + ASENTAR_RED, self.primero + TOPE_RAFAGA_RED)


def cambia_la_red(rafaga: CambioDeRed | None, ahora: float) -> CambioDeRed:
    """Devuelve la ráfaga con un aviso más de que la red ha cambiado.

    Args:
        rafaga: La ráfaga que está en curso, o `None` si no hay ninguna.
        ahora: Cuándo llega el aviso.
    """
    if rafaga is None:
        return CambioDeRed(ahora, ahora)
    return replace(rafaga, ultimo=max(rafaga.ultimo, ahora))


def red_asentada(rafaga: CambioDeRed | None, ahora: float, ocupado: bool) -> bool:
    """Indica si toca ya sondear los remotos sin conexión por esa ráfaga.

    Con una tarea en marcha se espera a que acabe: si fuera la sonda de un
    remoto sin conexión y fallara, apuntaría su siguiente sonda a la hora de
    `sondeo()` y el aviso de la red, que llegó mientras, se perdería.

    Args:
        rafaga: La ráfaga en curso, o `None`.
        ahora: La hora.
        ocupado: Si hay una pasada o una sonda en marcha.
    """
    return rafaga is not None and not ocupado and ahora >= rafaga.sondear_en


ATENDER = "atender"
"""Respuesta de la ventana a «¿Atender esta unidad?»: sí."""
AHORA_NO = "ahora_no"
"""Respuesta de la ventana a «¿Atender esta unidad?»: ahora no."""


@dataclass(frozen=True)
class Pregunta:
    """Una unidad nueva a la que se le ha preguntado si atenderla.

    Args:
        id: Id de la unidad.
        desde: Cuándo se preguntó.
        plazo: Segundos para contestar (`espera_unidad_nueva`).
    """
    id: str
    desde: float
    plazo: float

    @property
    def hasta(self) -> float:
        """Devuelve cuándo vence el plazo."""
        return self.desde + self.plazo


def resolver(pregunta: Pregunta, respuesta: str | None, ahora: float,
             cuando: float | None = None) -> str | None:
    """Devuelve qué vale la respuesta a esa pregunta.

    Lo que llega después del plazo no cuenta: para decir que sí tarde está la
    bandeja. Sin respuesta, al vencer el plazo es «Ahora no».

    Args:
        pregunta: La pregunta hecha.
        respuesta: Lo que ha contestado la ventana (`ATENDER` o `AHORA_NO`), o
            `None` si no ha contestado.
        ahora: La hora actual.
        cuando: A qué hora llegó la respuesta; por defecto, ahora.

    Returns:
        La respuesta válida, o `None` si todavía se espera.
    """
    llegada = ahora if cuando is None else cuando
    if respuesta in (ATENDER, AHORA_NO) and llegada <= pregunta.hasta:
        return respuesta
    if ahora >= pregunta.hasta:
        return AHORA_NO
    return None
