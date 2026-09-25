#!/usr/bin/env python3
"""
planificador.py — Qué le toca hacer ahora al agente, y cuándo volver a mirar.

Es la cabeza de `agente.py` y es PURO: no tiene reloj, ni disco, ni procesos.
Recibe todo como datos —las raíces que atiende y en qué estado están, cómo le fue
a cada pareja la última vez, la batería, la red, la hora— y devuelve una
decisión. Así cada regla se prueba con una tabla de casos y un reloj de mentira
(`tests/test_planificador.py`), sin lanzar un solo proceso.

Las reglas, en el orden en que se aplican:

  * **Una cola para todo el equipo.** Mientras hay una pasada en marcha no se
    decide otra: una sola a la vez, sea de la raíz del equipo o de una unidad.
    Ahorra ancho de banda y evita que la misma pareja, en el equipo y en la
    unidad enchufada, vaya contra el mismo `remote_path` a la vez.
  * **«Sincronizar ahora» va primero** y se salta toda la moderación: la pausa,
    la batería, la red de uso medido, la espera tras un fallo y el «sin
    conexión». Lo ha pedido alguien que está delante.
  * **Moderarse.** En pausa, con la batería por debajo del mínimo, o en una red
    de uso medido (si la política lo dice), no se lanza nada.
  * **Sin conexión.** Lo que va a un remoto que ha fallado por red no se lanza
    pareja tras pareja para que falle igual: se sondea ese remoto de vez en
    cuando (`Tarea` de tipo `SONDA`) y, cuando contesta, sus parejas vuelven.
  * **Espera creciente por pareja:** `intervalo · 2^k` tras k fallos seguidos,
    con un tope de 4 h, y a cero tras una pasada buena.
  * **Una raíz bloqueada, ausente, en pausa o apartada** simplemente no está: no
    es un fallo, no hace esperar más y no avisa de nada.

Nada de esto hace un `--resync`: una pareja que lo pide la salta su propio
`sync.py` (sin terminal, la pregunta toma el «no»), y aquí cuenta como
`SALTADA`, que no es ni un fallo ni una pasada buena.

Al final, `Pregunta`: el plazo de «¿Atender esta unidad?». También es un dato
del planificador y no de la ventana que la hace, para que la cuenta atrás no
dependa de que la ventana llegue a abrirse, ni una respuesta tardía cuente.
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


@dataclass(frozen=True)
class Politica:
    """Cómo se modera el agente. Sale de `agente.json`; aquí, sus valores de
    fábrica, que son los del diseño: sincroniza con batería, se para por
    debajo del 20 %, se pausa en una red de uso medido."""
    con_bateria: bool = True
    bateria_minima: int = 20
    pausar_red_medida: bool = True
    tope_espera: float = 4 * HORA
    sondeo_sin_conexion: float = 5 * 60.0
    # Cada cuánto se vuelve a mirar como mucho, aunque nada toque: el entorno
    # (batería, red) se lee de nuevo en cada vuelta y puede haber cambiado.
    mirar_maximo: float = 60.0
    # Con una pasada en marcha, cada cuánto se mira si ha terminado.
    mirar_ocupado: float = 2.0


@dataclass(frozen=True)
class Pareja:
    nombre: str
    remoto: str = ""        # el remote de rclone al que va; agrupa el «sin conexión»


@dataclass(frozen=True)
class Raiz:
    """Una raíz atendida: la del equipo o una unidad.

    `atendible` resume su estado —abierta y sin nadie más sirviéndola—; el
    motivo cuando no lo es lo sabe el agente, que es quien lo enseña. Un
    intervalo infinito es el modo `sync`: una pasada por conexión y ya."""
    clave: str
    parejas: tuple[Pareja, ...]
    intervalo: float                    # segundos
    atendible: bool = True


@dataclass(frozen=True)
class Marca:
    """Lo que se recuerda de una pareja entre pasadas."""
    ultimo_intento: float | None = None
    fallos: int = 0                     # fallos seguidos


@dataclass(frozen=True)
class Entorno:
    """Lo que el agente ha medido fuera: todo son sondas sustituibles."""
    pausado: bool = False
    con_bateria: bool = False           # ¿funciona ahora a batería?
    bateria: int | None = None          # porcentaje, si se sabe
    red_medida: bool | None = None      # None: no se sabe, y cuenta como normal
    # (raíz, remoto) sin conexión → cuándo toca sondearlo otra vez.
    sin_conexion: Mapping[tuple[str, str], float] = field(default_factory=dict)


@dataclass(frozen=True)
class Tarea:
    tipo: str
    raiz: str
    pareja: str | None = None           # None en una SONDA
    remoto: str = ""
    urgente: bool = False


@dataclass(frozen=True)
class Decision:
    tarea: Tarea | None
    mirar_en: float                     # segundos hasta la próxima vuelta
    retenido: str | None = None         # por qué no se lanza nada, si es global


def espera(intervalo: float, fallos: int, tope: float = 4 * HORA) -> float:
    """Cuánto esperar tras la última pasada: `intervalo · 2^fallos`, con tope.

    El tope nunca acorta el intervalo elegido: con un intervalo de 6 h, fallar
    no puede hacer que se intente antes que sin fallar."""
    if fallos <= 0 or math.isinf(intervalo):
        return intervalo
    return min(intervalo * (2 ** min(fallos, 32)), max(tope, intervalo))


def registrar(marca: Marca, resultado: str, ahora: float) -> Marca:
    """La marca de una pareja después de una pasada.

    Una pasada de `RED` no cuenta como intento: la pareja espera al remoto, no a
    su intervalo, y en cuanto la sonda diga que contesta vuelve a tocarle. Ni
    suma un fallo: el problema es la red, no la pareja."""
    if resultado == OK or resultado == SALTADA:
        return Marca(ahora, 0)
    if resultado == RED:
        return Marca(None, marca.fallos)
    return Marca(ahora, marca.fallos + 1)


def empieza_a_fallar(antes: Marca, despues: Marca) -> bool:
    """¿Esta pasada es la primera que falla? Solo entonces se avisa: un servicio
    que lleva horas sin poder no manda un aviso por ciclo."""
    return antes.fallos == 0 and despues.fallos > 0


def moderacion(entorno: Entorno, politica: Politica) -> str | None:
    """Por qué no se lanza nada ahora mismo, o None si se puede."""
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
    """La siguiente tarea, o ninguna y cuándo volver a mirar."""
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
    """El entorno con ese remoto marcado sin conexión, y cuándo sondearlo.

    Tras la primera pasada que falla por red, la sonda va enseguida: si el
    remoto contesta, aquel fallo no era de la red (ver `agente.py`). Una sonda
    que falla pone la siguiente a `Politica.sondeo_sin_conexion`."""
    nuevo = dict(entorno.sin_conexion)
    nuevo[(raiz, remoto)] = proxima_sonda
    return replace(entorno, sin_conexion=nuevo)


def con_conexion(entorno: Entorno, raiz: str, remoto: str) -> Entorno:
    """El entorno con ese remoto otra vez disponible."""
    nuevo = {k: v for k, v in entorno.sin_conexion.items() if k != (raiz, remoto)}
    return replace(entorno, sin_conexion=nuevo)


# ---------------------------------------------------------------------------
# «¿Atender esta unidad?» — el plazo
# ---------------------------------------------------------------------------

ATENDER = "atender"
AHORA_NO = "ahora_no"


@dataclass(frozen=True)
class Pregunta:
    """Una unidad nueva a la que se le ha preguntado si atenderla."""
    id: str
    desde: float
    plazo: float                        # segundos: `espera_unidad_nueva`

    @property
    def hasta(self) -> float:
        return self.desde + self.plazo


def resolver(pregunta: Pregunta, respuesta: str | None, ahora: float,
             cuando: float | None = None) -> str | None:
    """Qué vale la respuesta a esa pregunta, o None si todavía se espera.

    `respuesta` es lo que ha contestado la ventana (`ATENDER`/`AHORA_NO`) o None
    si no ha contestado; `cuando`, a qué hora llegó —por defecto, ahora—. Lo que
    llega después del plazo no cuenta: para decir que sí tarde está la bandeja.
    Sin respuesta, al vencer el plazo es «Ahora no»."""
    llegada = ahora if cuando is None else cuando
    if respuesta in (ATENDER, AHORA_NO) and llegada <= pregunta.hasta:
        return respuesta
    if ahora >= pregunta.hasta:
        return AHORA_NO
    return None
