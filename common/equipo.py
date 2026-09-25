#!/usr/bin/env python3
"""
equipo.py — Lo que el agente residente guarda en el equipo, y cómo se lee.

El agente (`agente.py`) vive FUERA de toda raíz: en `%LOCALAPPDATA%\\prdrive\\`
o en `~/.local/share/prdrive/`. Es una ruta fija por sistema, como el
`HOST_DIR` de penwatch, y por eso la sabe cualquiera sin preguntar: el propio
agente, el instalador que lo pone, y la ventana de una unidad que quiera pedirle
algo. Aquí no hay ningún secreto: ni clave, ni `rclone.conf`, ni listados.

    agente/<versión>/     la copia del código con la que corre el agente
    runtime/<stamp_id>/   su Python, uno por versión (como el de penwatch)
    agente.json           QUÉ hace: unidades que atiende, su modo, plazos, moderación
    instalacion.json      DÓNDE está: código, Python, cuándo se registró
    agente.lock.json      una sola instancia por usuario
    agente.pide           el buzón: lo que otros le piden al agente
    estado.json           lo que el agente está haciendo, para quien lo pregunte
    agente.log            su diario

Los dos JSON de configuración están separados a propósito y cada uno tiene UN
escritor. `agente.json` lo crea el asistente y a partir de ahí solo lo escribe el
agente: la ventana de una unidad es el código de esa unidad, que puede ir en otra
versión, y no toca la configuración del equipo, sino que la pide por el buzón.
`instalacion.json` solo lo escriben el instalador y el actualizador, que son
quienes cambian el código y el Python de sitio.

Leer nunca lanza: un fichero que falta o que trae basura se lee como los valores
de fábrica, con la misma regla que `store.py`.
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

# Qué hace el agente con una unidad al enchufarla. Los tres de penwatch y uno más.
UI, DAEMON, SYNC, NADA = "ui", "daemon", "sync", "nada"
MODOS = (UI, DAEMON, SYNC, NADA)
MODO_AL_ATENDER = DAEMON                # lo natural para un programa en segundo plano
TEXTO_MODO = {UI: "abrir la ventana", DAEMON: "sincronizar en segundo plano",
              SYNC: "una pasada al enchufarla", NADA: "nada"}

ESPERA_UNIDAD_NUEVA = 120.0             # segundos para contestar «¿Atenderla?»
ESPERA_MINIMA, ESPERA_MAXIMA = 10.0, 3600.0


def dir_equipo() -> Path:
    """Dónde vive el agente en el equipo. Por usuario, sin privilegios."""
    if IS_WIN:
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / APP_NAME


# Variable de módulo, y las rutas funciones que la leen: los tests la reapuntan a
# un temporal, igual que `model.STATE_DIR`.
DIR = dir_equipo()


def ajustes_json() -> Path:
    return DIR / "agente.json"


def instalacion_json() -> Path:
    return DIR / "instalacion.json"


def lock_json() -> Path:
    return DIR / "agente.lock.json"


def buzon() -> Path:
    return DIR / "agente.pide"


def estado_json() -> Path:
    return DIR / "estado.json"


def diario_log() -> Path:
    return DIR / "agente.log"


def dir_codigo() -> Path:
    return DIR / "agente"


def dir_runtimes() -> Path:
    return DIR / "runtime"


# ---------------------------------------------------------------------------
# agente.json
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Unidad:
    id: str
    modo: str = MODO_AL_ATENDER
    nombre: str = ""


@dataclass(frozen=True)
class Ajustes:
    unidades: Mapping[str, Unidad] = field(default_factory=dict)
    espera_unidad_nueva: float = ESPERA_UNIDAD_NUEVA
    politica: Politica = Politica()
    # Carpetas donde buscar unidades además de las del sistema (penwatch
    # `--extra-root`): un punto de montaje fuera de lo habitual.
    extra_roots: tuple[str, ...] = ()

    def con_unidad(self, unidad: Unidad) -> "Ajustes":
        unidades = dict(self.unidades)
        unidades[unidad.id] = unidad
        return replace(self, unidades=unidades)


def _numero(valor: Any, defecto: float, minimo: float, maximo: float) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return defecto
    if math.isnan(valor):
        return defecto
    return min(max(float(valor), minimo), maximo)


def desde_dict(datos: Mapping[str, Any]) -> Ajustes:
    """Unos ajustes saneados a partir de lo que haya en el JSON.

    Lo que no se entiende se ignora con su valor de fábrica, entrada a entrada:
    un modo desconocido no tira la unidad entera, ni una unidad rota las demás."""
    unidades: dict[str, Unidad] = {}
    crudas = datos.get("unidades")
    if isinstance(crudas, dict):
        for uid, u in crudas.items():
            if not isinstance(uid, str) or not uid.strip() or not isinstance(u, dict):
                continue
            modo = u.get("modo") if u.get("modo") in MODOS else MODO_AL_ATENDER
            nombre = u.get("nombre") if isinstance(u.get("nombre"), str) else ""
            unidades[uid.strip()] = Unidad(uid.strip(), modo, nombre)
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
        if isinstance(extra, list) else ())


def a_dict(aj: Ajustes) -> dict:
    return {
        "unidades": {u.id: {"modo": u.modo, "nombre": u.nombre}
                     for u in aj.unidades.values()},
        "espera_unidad_nueva": aj.espera_unidad_nueva,
        "moderacion": {"con_bateria": aj.politica.con_bateria,
                       "bateria_minima": aj.politica.bateria_minima,
                       "pausar_red_medida": aj.politica.pausar_red_medida},
        "extra_roots": list(aj.extra_roots),
    }


def leer_ajustes() -> Ajustes:
    return desde_dict(store.read_json(ajustes_json()))


def guardar_ajustes(aj: Ajustes) -> bool:
    try:
        DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return store.write_json(ajustes_json(), a_dict(aj))


# ---------------------------------------------------------------------------
# instalacion.json, el lock y el estado
# ---------------------------------------------------------------------------

def leer_instalacion() -> dict:
    return store.read_json(instalacion_json())


def instalado() -> bool:
    """¿Hay un agente instalado en este equipo? Que su código esté donde dice."""
    datos = leer_instalacion()
    codigo = datos.get("codigo")
    if not isinstance(codigo, str):
        return False
    try:
        return (Path(codigo) / "agente.py").is_file()
    except OSError:
        return False


def agente_vivo() -> dict | None:
    """El registro del agente si es de un proceso vivo de ESTE equipo, o None."""
    info = store.read_json(lock_json())
    if info.get("host") != HOST:
        return None
    try:
        pid = int(info.get("pid", -1))
    except (TypeError, ValueError):
        return None
    return info if pid_alive(pid) else None


def leer_estado() -> dict:
    return store.read_json(estado_json())


# ---------------------------------------------------------------------------
# El buzón
# ---------------------------------------------------------------------------
#
# Un fichero con una petición JSON por línea. Quien pide AÑADE una línea (varios
# pueden pedir a la vez sin pisarse); el agente lo recoge renombrándolo antes de
# leerlo, así que lo que llegue mientras lee va a un buzón nuevo y no se pierde.
# Sin puertos ni sockets: la misma forma que `daemon.stop`.

# Lo que se le puede pedir, con los campos que lleva cada cosa.
PIDE_ATENDER = "atender"        # id: una unidad conectada a la que se dijo «Ahora no»
PIDE_MODO = "modo"              # id, modo
PIDE_AJUSTE = "ajuste"          # clave, valor
PIDE_PASADA = "pasada"          # id, parejas (vacío: todas): «Sincronizar ahora»
PIDE_PAUSA = "pausa"
PIDE_SIGUE = "sigue"
PIDE_PARAR = "parar"            # que termine (el instalador, antes de sustituirlo)
AJUSTES_PEDIBLES = ("espera_unidad_nueva",)


def pedir(peticion: Mapping[str, Any]) -> bool:
    """Deja una petición en el buzón del agente. True si se ha podido escribir.

    Va sellada con la hora (`cuando`): un «parar» que el agente de entonces no
    llegó a leer no puede tumbar al siguiente."""
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        with buzon().open("a", encoding="utf-8") as f:
            f.write(json.dumps({**dict(peticion), "cuando": time.time()},
                               ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False


def recoger() -> list[dict]:
    """Lo que hay en el buzón, vaciándolo. Solo lo llama el agente."""
    origen = buzon()
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
