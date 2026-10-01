#!/usr/bin/env python3
r"""Lo que el agente residente guarda en el equipo, y cómo se lee.

El agente (`agente.py`) vive FUERA de toda raíz: en `%LOCALAPPDATA%\prdrive\` o
en `~/.local/share/prdrive/`. Es una ruta fija por sistema, como el `HOST_DIR`
de penwatch, y por eso la sabe cualquiera sin preguntar: el agente, el
instalador que lo pone y la ventana de una unidad que quiera pedirle algo. No
hay ningún secreto aquí: ni clave, ni `rclone.conf`, ni listados.

    agente/<versión>/     la copia del código con la que corre el agente
    runtime/<stamp_id>/   su Python, uno por versión (como el de penwatch)
    agente.json           QUÉ hace: raíces que atiende (unidades y la del equipo,
                          con su contenedor si va cifrada), su modo, plazos,
                          moderación, `pedir_al_iniciar`
    instalacion.json      DÓNDE está: código, Python, cuándo se registró
    agente.lock.json      una sola instancia por usuario
    agente.pide           el buzón: lo que otros le piden al agente
    estado.json           lo que el agente está haciendo, para quien lo pregunte
    agente.log            su diario
    update.json           lo último que dijo GitHub de la versión nueva

En cada raíz, `state/servicio.pide` es el buzón de lo que su ventana pide al
servicio de ESA raíz (`BUZON_SERVICIO`), con la misma forma que `agente.pide`.

Los dos JSON de configuración están separados a propósito y cada uno tiene UN
escritor. `agente.json` lo crea el asistente y a partir de ahí solo lo escribe
el agente: la ventana de una unidad es el código de esa unidad, que puede ir en
otra versión, y no toca la configuración del equipo sino que la pide por el
buzón. `instalacion.json` solo lo escriben el instalador y el actualizador, que
son quienes cambian el código y el Python de sitio.

Un buzón es un fichero con una petición JSON por línea. Quien pide AÑADE una
línea (varios pueden pedir a la vez sin pisarse); el agente lo recoge
renombrándolo antes de leerlo, así que lo que llegue mientras lee va a un buzón
nuevo y no se pierde. Sin puertos ni sockets: la misma forma que `daemon.stop`.

Leer nunca lanza: un fichero que falta o que trae basura se lee como los
valores de fábrica, con la misma regla que `store.py`.
"""

from __future__ import annotations

import json
import math
import os
import socket
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from . import APP_NAME, store
from .planificador import Politica
from .store import pid_alive

IS_WIN = os.name == "nt"
HOST = socket.gethostname()             # el mismo que apunta `ui/prefs.py`

UI, DAEMON, SYNC, NADA = "ui", "daemon", "sync", "nada"
MODOS = (UI, DAEMON, SYNC, NADA)
"""Modos al enchufar una unidad: los tres de penwatch y `nada`."""
MODO_AL_ATENDER = DAEMON                # lo natural para un programa en segundo plano
TEXTO_MODO = {UI: "abrir la ventana", DAEMON: "sincronizar en segundo plano",
              SYNC: "una pasada al enchufarla", NADA: "nada"}
"""Cómo se nombra cada modo de cara al usuario."""

ESPERA_UNIDAD_NUEVA = 120.0             # segundos para contestar «¿Atenderla?»
ESPERA_MINIMA, ESPERA_MAXIMA = 10.0, 3600.0


def dir_equipo() -> Path:
    """Devuelve dónde vive el agente en el equipo: por usuario, sin privilegios."""
    if IS_WIN:
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / APP_NAME


DIR = dir_equipo()
"""Carpeta del agente en este equipo.

Es una variable de módulo y las rutas son funciones que la leen: los tests la
reapuntan a un temporal, igual que `model.STATE_DIR`.
"""


def ajustes_json() -> Path:
    """Devuelve la ruta de `agente.json`."""
    return DIR / "agente.json"


def instalacion_json() -> Path:
    """Devuelve la ruta de `instalacion.json`."""
    return DIR / "instalacion.json"


def lock_json() -> Path:
    """Devuelve la ruta de `agente.lock.json`."""
    return DIR / "agente.lock.json"


def pasada_json() -> Path:
    """Devuelve la ruta de `pasada.json`, la pasada en curso del agente."""
    return DIR / "pasada.json"


def buzon() -> Path:
    """Devuelve la ruta del buzón del agente, `agente.pide`."""
    return DIR / "agente.pide"


def estado_json() -> Path:
    """Devuelve la ruta de `estado.json`."""
    return DIR / "estado.json"


def diario_log() -> Path:
    """Devuelve la ruta del diario del agente, `agente.log`."""
    return DIR / "agente.log"


def dir_codigo() -> Path:
    """Devuelve la carpeta `agente/`, con el código por versión."""
    return DIR / "agente"


def dir_runtimes() -> Path:
    """Devuelve la carpeta `runtime/`, con un Python por versión."""
    return DIR / "runtime"


def dir_rclone() -> Path:
    """Devuelve la carpeta `rclone/`: `rclone/<versión fijada>/` es el del agente.

    Es el rclone que pasa a las pasadas y a las ventanas que lanza en lugar del
    de cada unidad.
    """
    return DIR / "rclone"


def dir_veracrypt() -> Path:
    """Devuelve la carpeta `veracrypt/`: `veracrypt/<versión fijada>/` es el del agente.

    Sirve para abrir y cerrar una raíz cifrada en un equipo sin VeraCrypt
    instalado, y solo existe si hace falta
    (`install/agente.quiere_veracrypt()`).
    """
    return DIR / "veracrypt"


@dataclass(frozen=True)
class Unidad:
    r"""Una raíz de la lista del agente.

    Es una unidad que se enchufa o, con `ruta`, la raíz de este equipo: una
    carpeta del ordenador que está siempre en el mismo sitio. Van en la misma
    lista porque para el agente son lo mismo (una raíz con su id, su modo y su
    propio código); solo cambia cómo se encuentra: una unidad recorriendo los
    volúmenes, la raíz del equipo mirando en su `ruta`, que se guarda y no se
    deduce del nombre de la carpeta.

    Args:
        id: El id del fichero de control de la raíz.
        modo: Qué se hace al conectarla (`MODOS`).
        nombre: Nombre para mostrar.
        ruta: Dónde está la raíz del equipo; vacía en una unidad.
        contenedor: El `PRDRIVE.hc` de una raíz del equipo cifrada. Con él,
            `ruta` es donde se monta (la letra `P:\` en Windows, una carpeta
            fija como `~/PRDRIVE` en Linux) y la raíz solo está mientras esté
            abierto.
        codigo: Huella del código que tenía la unidad cuando se dijo que sí
            (`agente.huella()`, sha256 en hex). Con otra se vuelve a preguntar:
            el id lo lleva escrito la unidad y se copia, así que no basta para
            ejecutar lo que traiga. Vacía: atendida sin haberla visto (el
            asistente, `atender ID` desenchufada); se apunta la primera vez que
            se conecta. Las raíces del equipo no la llevan.
    """
    id: str
    modo: str = MODO_AL_ATENDER
    nombre: str = ""
    ruta: str = ""
    contenedor: str = ""
    codigo: str = ""

    @property
    def es_raiz(self) -> bool:
        """Indica si es la raíz de este equipo (tiene `ruta`) y no una unidad."""
        return bool(self.ruta)

    @property
    def cifrada(self) -> bool:
        """Indica si es una raíz del equipo que vive en un contenedor."""
        return self.es_raiz and bool(self.contenedor)

    @property
    def letra(self) -> str:
        r"""Devuelve la letra fija de una raíz cifrada en Windows (`P`).

        Es una cadena vacía si no hay.

        Se pasa a VeraCrypt con `/letter`: los programas apuntan a la raíz, y
        un almacén de Obsidian en `P:\obsidian` se rompería si mañana fuese
        `Q:`.
        """
        r = self.ruta
        if self.cifrada and len(r) >= 2 and r[1] == ":" and r[0].isalpha():
            return r[0].upper()
        return ""


@dataclass(frozen=True)
class Ajustes:
    """Los ajustes del agente, saneados (`agente.json`).

    Args:
        unidades: Las raíces que atiende, por id.
        espera_unidad_nueva: Segundos que se espera la respuesta a
            «¿Atenderla?».
        politica: La moderación (batería, red de uso medido).
        extra_roots: Carpetas donde buscar unidades además de las del sistema
            (penwatch `--extra-root`), p. ej. un punto de montaje fuera de lo
            habitual.
        pedir_al_iniciar: Si se pide la contraseña de la raíz cifrada al
            iniciar sesión. Se pide una vez: si se cancela no se vuelve a pedir
            hasta «Desbloquear».
    """
    unidades: Mapping[str, Unidad] = field(default_factory=dict)
    espera_unidad_nueva: float = ESPERA_UNIDAD_NUEVA
    politica: Politica = Politica()
    extra_roots: tuple[str, ...] = ()
    pedir_al_iniciar: bool = True

    def con_unidad(self, unidad: Unidad) -> "Ajustes":
        """Devuelve unos ajustes iguales con esa unidad añadida o sustituida."""
        unidades = dict(self.unidades)
        unidades[unidad.id] = unidad
        return replace(self, unidades=unidades)

    @property
    def raices(self) -> dict[str, Unidad]:
        """Devuelve las raíces de este equipo: las de la lista con `ruta`."""
        return {uid: u for uid, u in self.unidades.items() if u.es_raiz}

    @property
    def cifradas(self) -> dict[str, Unidad]:
        """Devuelve las raíces de este equipo que viven en un contenedor VeraCrypt."""
        return {uid: u for uid, u in self.unidades.items() if u.cifrada}


def _numero(valor: Any, defecto: float, minimo: float, maximo: float) -> float:
    """Devuelve `valor` acotado a `[minimo, maximo]`.

    Si no es un número válido, devuelve `defecto`.
    """
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return defecto
    if math.isnan(valor):
        return defecto
    return min(max(float(valor), minimo), maximo)


def desde_dict(datos: Mapping[str, Any]) -> Ajustes:
    """Devuelve unos ajustes saneados a partir de lo que haya en el JSON.

    Lo que no se entiende se ignora con su valor de fábrica, entrada a entrada:
    un modo desconocido no tira la unidad entera ni una unidad rota las demás.
    """
    unidades: dict[str, Unidad] = {}
    crudas = datos.get("unidades")
    if isinstance(crudas, dict):
        for uid, u in crudas.items():
            if not isinstance(uid, str) or not uid.strip() or not isinstance(u, dict):
                continue
            modo = u.get("modo") if u.get("modo") in MODOS else MODO_AL_ATENDER
            nombre = u.get("nombre") if isinstance(u.get("nombre"), str) else ""
            ruta = u.get("ruta") if isinstance(u.get("ruta"), str) else ""
            hc = u.get("contenedor") if isinstance(u.get("contenedor"), str) else ""
            codigo = u.get("codigo") if isinstance(u.get("codigo"), str) else ""
            unidades[uid.strip()] = Unidad(uid.strip(), modo, nombre, ruta.strip(),
                                           hc.strip() if ruta.strip() else "",
                                           codigo.strip())
    m = datos.get("moderacion") if isinstance(datos.get("moderacion"), dict) else {}
    fabrica = Politica()
    politica = replace(
        fabrica,
        con_bateria=m["con_bateria"] if isinstance(m.get("con_bateria"), bool)
        else fabrica.con_bateria,
        bateria_minima=int(_numero(m.get("bateria_minima"), fabrica.bateria_minima, 0, 100)),
        pausar_red_medida=m["pausar_red_medida"]
        if isinstance(m.get("pausar_red_medida"), bool) else fabrica.pausar_red_medida)
    extra = datos.get("extra_roots")
    return Ajustes(
        unidades=unidades,
        espera_unidad_nueva=_numero(datos.get("espera_unidad_nueva"),
                                    ESPERA_UNIDAD_NUEVA, ESPERA_MINIMA, ESPERA_MAXIMA),
        politica=politica,
        extra_roots=tuple(r for r in extra if isinstance(r, str) and r)
        if isinstance(extra, list) else (),
        pedir_al_iniciar=datos["pedir_al_iniciar"]
        if isinstance(datos.get("pedir_al_iniciar"), bool) else True)


def a_dict(aj: Ajustes) -> dict:
    """Convierte unos ajustes al dict que se guarda en `agente.json`."""
    return {
        "unidades": {u.id: {"modo": u.modo, "nombre": u.nombre,
                            **({"ruta": u.ruta} if u.ruta else {}),
                            **({"contenedor": u.contenedor} if u.contenedor else {}),
                            **({"codigo": u.codigo} if u.codigo else {})}
                     for u in aj.unidades.values()},
        "espera_unidad_nueva": aj.espera_unidad_nueva,
        "moderacion": {"con_bateria": aj.politica.con_bateria,
                       "bateria_minima": aj.politica.bateria_minima,
                       "pausar_red_medida": aj.politica.pausar_red_medida},
        "extra_roots": list(aj.extra_roots),
        "pedir_al_iniciar": aj.pedir_al_iniciar,
    }


def leer_ajustes() -> Ajustes:
    """Lee `agente.json`; sin fichero o con basura, los valores de fábrica."""
    return desde_dict(store.read_json(ajustes_json()))


def guardar_ajustes(aj: Ajustes) -> bool:
    """Escribe `agente.json`.

    Returns:
        False si no se ha podido crear la carpeta o escribir.
    """
    try:
        DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return store.write_json(ajustes_json(), a_dict(aj))


def leer_instalacion() -> dict:
    """Lee `instalacion.json`; sin fichero o con basura, un dict vacío."""
    return store.read_json(instalacion_json())


def instalado() -> bool:
    """Indica si hay un agente instalado en este equipo.

    Se da por instalado si su código está donde dice `instalacion.json`.
    """
    datos = leer_instalacion()
    codigo = datos.get("codigo")
    if not isinstance(codigo, str):
        return False
    try:
        return (Path(codigo) / "agente.py").is_file()
    except OSError:
        return False


def agente_vivo() -> dict | None:
    """Devuelve el registro del agente si es de un proceso vivo de ESTE equipo.

    Returns:
        El registro, o `None`.
    """
    info = store.read_json(lock_json())
    if info.get("host") != HOST:
        return None
    try:
        pid = int(info.get("pid", -1))
    except (TypeError, ValueError):
        return None
    return info if pid_alive(pid) else None


def apuntar_pasada(datos: dict) -> bool:
    """Apunta en `pasada.json` la pasada que el agente acaba de lanzar.

    La pasada es un proceso aparte: si el agente se va (SIGTERM al cerrar
    sesión, o el instalador lo termina) sigue, y quien venga detrás tiene que
    saber que está ahí antes de lanzar otra o de sustituir el código
    (`pasada_viva()`).

    Args:
        datos: `pid`, `unidad` y `pareja` de la pasada.
    """
    return store.write_json(pasada_json(), {**datos, "host": HOST,
                                            "arranque": store.arranque_del_sistema()})


ESPERA_TRAS_CORTE = 150.0
"""Segundos que se deja en paz a la pareja de una pasada cortada.

El `.lck` de bisync que queda caduca solo a los dos minutos (`--max-lock 2m`,
`common/model.py`), y lanzarla antes falla con «prior lock file found» y avisa
de un fallo que no lo es. Lleva un margen.
"""


def apuntar_corte(pasada: dict) -> bool:
    """Apunta cuándo se cortó esa pasada, en el mismo `pasada.json`.

    La corta el instalador (`install/agente.parar_agente()`); lo apunta para el
    agente que venga.
    """
    return store.write_json(pasada_json(), {**pasada, "cortada": time.time()})


def pasada_cortada() -> dict | None:
    """Devuelve el registro de una pasada cortada en este equipo.

    Lleva `cortada` (segundos de época); cuánto hace lo decide quien lo lee.

    Returns:
        El registro, o `None`.
    """
    info = store.read_json(pasada_json())
    if info.get("host") != HOST or not isinstance(info.get("cortada"), (int, float)):
        return None
    return info


def pasada_viva() -> dict | None:
    """Devuelve el registro de `pasada.json` si esa pasada sigue viva EN ESTE EQUIPO.

    Un pid de otro arranque del sistema no dice nada (tras reiniciar se
    reutilizan), así que se compara también cuándo arrancó el sistema.

    Returns:
        El registro, o `None`.
    """
    info = store.read_json(pasada_json())
    if not vivo_aqui(info):
        return None
    antes, ahora = info.get("arranque"), store.arranque_del_sistema()
    if isinstance(antes, (int, float)) and ahora is not None \
            and abs(antes - ahora) > store.HOLGURA_ARRANQUE:
        return None
    return info


def vivo_aqui(info: dict | None) -> bool:
    """Indica si es el registro de un proceso vivo DE ESTE EQUIPO.

    Un pid muerto, de otro equipo o ilegible es un resto.
    """
    if not info or info.get("host") != HOST:
        return False
    try:
        return pid_alive(int(info.get("pid", -1)))
    except (TypeError, ValueError):
        return False


def tomar_lock(datos: dict) -> dict | None:
    """Apunta que este proceso es el agente de este equipo, si no lo es otro.

    Mirar y escribir son UN paso (`store.tomar_registro()`): de dos arranques a
    la vez (la tarea del inicio de sesión y el acceso del menú, por ejemplo)
    solo uno lo crea y el otro se va. Sin poder escribir en la carpeta del
    agente, sigue: no hay dónde apuntar a otro.

    Returns:
        `None` si lo ha tomado; si no, el registro del agente que lo es.
    """
    tomado, otro = store.tomar_registro(lock_json(), datos, vivo_aqui)
    return None if tomado is not False else (otro or {})


def leer_estado() -> dict:
    """Lee `estado.json`; sin fichero o con basura, un dict vacío."""
    return store.read_json(estado_json())


# Lo que se le puede pedir, con los campos que lleva cada cosa.
PIDE_ATENDER = "atender"        # id: una unidad conectada a la que se dijo «Ahora no»
PIDE_MODO = "modo"              # id, modo
PIDE_AJUSTE = "ajuste"          # clave, valor
PIDE_PASADA = "pasada"          # id, parejas (vacío: todas): «Sincronizar ahora»
PIDE_PAUSA = "pausa"
PIDE_SIGUE = "sigue"
PIDE_PARAR = "parar"            # que termine (el instalador, antes de sustituirlo)
PIDE_RAIZ = "añadir_raiz"       # id, ruta, nombre[, contenedor]: la raíz de este equipo
PIDE_DESBLOQUEAR = "desbloquear"    # [id]: abrir el contenedor de la raíz cifrada
PIDE_BLOQUEAR = "bloquear"          # [id]: cerrarlo
PIDE_ABRIR = "abrir"            # id: la ventana de esa raíz (la cifrada, desbloqueándola antes)
PIDE_DESPERTAR = "despertar"    # el equipo vuelve de la suspensión: mirarlo todo ya
PIDE_SONDEAR = "sondear"        # los remotos sin conexión: probarlos ya («Probar ahora»)
PIDE_ACTUALIZAR = "actualizar"  # bajar la versión nueva y ponerla (agente y raíces del equipo)
PIDE_REANUDAR = "reanudar"      # (buzón de la raíz) «Iniciar servicio» con el agente: volver ya
AJUSTES_PEDIBLES = ("espera_unidad_nueva", "pedir_al_iniciar")

BUZON_SERVICIO = "servicio.pide"
"""Nombre del buzón de UNA raíz, dentro de su `state/`.

Es lo que la ventana de esa raíz pide al servicio que la atiende, y solo lo que
es de ella (`PIDE_SERVICIO`): `reanudar`, `pasada` con sus parejas y
`bloquear`. El id no hace falta: es el de la raíz donde está el fichero. Lo del
equipo (un ajuste, el modo de una unidad, añadir una raíz) va al buzón del
agente.
"""
PIDE_SERVICIO = (PIDE_REANUDAR, PIDE_PASADA, PIDE_BLOQUEAR)


def pedir(peticion: Mapping[str, Any], buzon_de: Path | None = None) -> bool:
    """Deja una petición en el buzón del agente o, con `buzon_de`, en el de una raíz.

    Va sellada con la hora (`cuando`): un «parar» que el agente de entonces no
    llegó a leer no puede tumbar al siguiente.

    Returns:
        True si se ha podido escribir.
    """
    destino = buzon_de if buzon_de is not None else buzon()
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        with destino.open("a", encoding="utf-8") as f:
            f.write(json.dumps({**dict(peticion), "cuando": time.time()},
                               ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False


def recoger(buzon_de: Path | None = None) -> list[dict]:
    """Devuelve lo que hay en el buzón, vaciándolo; solo lo llama el agente.

    Se renombra antes de leer, así que lo que llegue después va a un buzón
    nuevo. Se ignoran las líneas que no son JSON o no llevan `pide`.
    """
    origen = buzon_de if buzon_de is not None else buzon()
    tomado = origen.with_name(f"{origen.name}.{os.getpid()}")
    try:
        os.replace(origen, tomado)
    except OSError:
        return []
    peticiones: list[dict] = []
    try:
        for linea in tomado.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                dato = json.loads(linea)
            except ValueError:
                continue
            if isinstance(dato, dict) and isinstance(dato.get("pide"), str):
                peticiones.append(dato)
    except OSError:
        pass
    finally:
        tomado.unlink(missing_ok=True)
    return peticiones
