#!/usr/bin/env python3
"""El `daemon.lock.json` del agente sigue a la config que está atendiendo (#118).

El agente escribe las parejas y el intervalo de su servicio al TOMAR la raíz,
y tras cada pasada. Si la config cambia mientras la atiende (la ventana añade
el llavero, quita una pareja, cambia el intervalo), el registro se quedaba con
lo de antes: `llavero.atiende_el_servicio()` daba por no atendido el llavero y
«Abrir llavero» arrancaba además el vigilante. Aquí se comprueba que el
registro se pone al día al releer el servicio, y solo entonces: que no escribe
un registro que no es suyo, que no reescribe si nada de lo que apunta cambió,
y que un fallo al escribir no tumba la vuelta.
"""

import os
import time
from pathlib import Path

from _harness import Checks

import _agente_falso as F
import agente
import penwatch
from common import equipo, llavero, model, store

c = Checks("agente: el registro del servicio sigue a su config")
F.preparar()

UID = "a" * 32
LLAVERO = '\n[keychain]\nbase = "personal.kdbx"\n'
VIEJA = 1_000_000_000.0
"""Una fecha de hace mucho para el registro: si se reescribe, la fecha cambia."""
_fechas = [0]


def config(parejas, minutos: int = 10, con_llavero: bool = False, extra: str = "") -> str:
    """El `sync_config.toml` de la unidad con esas parejas, como lo dejaría su ventana."""
    pares = "".join(f'\n[[pair]]\nname = "{p}"\nlocal = "sync-data/{p}"\n'
                    f'remote_path = "/R/{p}"\n' for p in parejas)
    return (f'[defaults]\nremote = "nas"\n\n[daemon]\ninterval_minutes = {minutos}\n'
            + pares + (LLAVERO if con_llavero else "") + extra)


def editar(raiz: Path, texto: str) -> None:
    """Escribe el config de la unidad, con una fecha nueva (la que mira el agente)."""
    toml = raiz / ".prdrive" / "sync_config.toml"
    toml.write_text(texto, encoding="utf-8")
    _fechas[0] += 5
    os.utime(toml, (time.time() + _fechas[0], time.time() + _fechas[0]))


def asentar(ag) -> None:
    """Termina las pasadas en marcha, para que su resultado no meta ruido en el registro."""
    while ag.pasada is not None:
        F.acabar(ag.pasada.proc, 0, "OK\n")
        F.vueltas(ag, 1)


def releer(ag) -> None:
    """Pasa el tiempo que el agente tarda en volver a mirar el config, y da una vuelta."""
    F.pasar(agente.MIRAR_CONFIG)
    F.vueltas(ag, 1)


def registro(raiz: Path) -> Path:
    """La ruta del `daemon.lock.json` de la unidad."""
    return raiz / penwatch.DAEMON_LOCK_REL


RAIZ = F.unidad(UID, parejas=("docs", "fotos"),
                daemon='[daemon]\ninterval_minutes = 10\n')
equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(equipo.Unidad(UID, equipo.DAEMON)))
F.RAICES[:] = [RAIZ]

ag = F.nuevo()
F.vueltas(ag, 2)
asentar(ag)
c("el agente atiende la unidad, con sus dos parejas en el registro",
  F.lock(RAIZ).get("pairs"), ["docs", "fotos"])

# El llavero se activa: el TOML gana [keychain] mientras el agente atiende.
# `llavero.atiende_el_servicio()` lee el registro del host (`model.daemon_lock()`);
# se apunta al de la unidad, como en `test_instancia_unica`.
real_daemon_lock = model.daemon_lock
model.daemon_lock = lambda: registro(RAIZ)
try:
    editar(RAIZ, config(("docs", "fotos"), con_llavero=True))
    releer(ag)
    c("con [keychain] en el TOML, el registro del servicio lo lleva",
      F.lock(RAIZ).get("pairs"), ["docs", "fotos", model.LLAVERO])
    c("  y el llavero lo da por atendido: no hace falta el vigilante",
      llavero.atiende_el_servicio(), True)
finally:
    model.daemon_lock = real_daemon_lock

# Se quita una pareja.
asentar(ag)
editar(RAIZ, config(("docs",), con_llavero=True))
releer(ag)
c("quitar una pareja también se refleja en el registro",
  F.lock(RAIZ).get("pairs"), ["docs", model.LLAVERO])

# Cambia el intervalo: el registro lleva el que está atendiendo.
asentar(ag)
editar(RAIZ, config(("docs",), minutos=20, con_llavero=True))
releer(ag)
c("un cambio de intervalo también (interval_min)",
  F.lock(RAIZ).get("interval_min"), 20.0)

# Sin cambio de parejas ni de intervalo no se reescribe: no escribe en la unidad
# en cada vuelta. Se fecha el registro en el pasado y se ve que no se toca.
asentar(ag)
os.utime(registro(RAIZ), (VIEJA, VIEJA))
editar(RAIZ, config(("docs",), minutos=20, con_llavero=True,
                    extra="# un comentario que no cambia nada\n"))
releer(ag)
c("sin cambio de parejas ni de intervalo, el registro no se reescribe",
  registro(RAIZ).stat().st_mtime, VIEJA)

# Otro servicio se queda con el lock: el agente se aparta y, al releer, no lo
# escribe. El registro es de ese otro, y se queda como está.
asentar(ag)
F.otro_servicio(RAIZ)
F.vueltas(ag, 3)
c("otro servicio vivo con el lock: el agente se aparta", ag.conexiones[UID].lock, None)
antes = F.lock(RAIZ)
editar(RAIZ, config(("docs",), con_llavero=False))
releer(ag)
c("un registro que no es nuestro no se escribe al releer", F.lock(RAIZ), antes)

# Vuelve el agente, con el llavero en el TOML.
(RAIZ / penwatch.DAEMON_LOCK_REL).unlink()
F.vueltas(ag, 3)
c("cuando el lock vuelve a estar libre, el agente lo toma otra vez",
  F.lock(RAIZ).get("pid"), os.getpid())
c("  con las parejas de la config que tiene ahora",
  F.lock(RAIZ).get("pairs"), ["docs"])

# Un fallo al escribir no tumba la vuelta, y la pasada siguiente lo deja al día.
asentar(ag)
real_write = store.write_json


def falla_el_registro(path, data):
    """`write_json` que no puede escribir el registro de la unidad (en uso, solo lectura)."""
    if Path(path).name == "daemon.lock.json":
        return False
    return real_write(path, data)


store.write_json = falla_el_registro
try:
    editar(RAIZ, config(("docs",), con_llavero=True))
    try:
        releer(ag)
        cayo = None
    except Exception as e:  # noqa: BLE001 - lo que se busca es que no caiga
        cayo = e
finally:
    store.write_json = real_write
c("un fallo al escribir el registro no tumba la vuelta", cayo, None)
c("  y el registro en disco sigue como estaba", F.lock(RAIZ).get("pairs"), ["docs"])
F.pasar(10 * 60 + 1)                      # toca otra pasada: la que escribe el registro
F.vueltas(ag, 1)
asentar(ag)
c("la pasada siguiente lo deja al día",
  F.lock(RAIZ).get("pairs"), ["docs", model.LLAVERO])

# Una config que pasa a error (sin parejas) no escribe un registro a medias: se
# suelta como siempre, sin dejar parejas vacías.
asentar(ag)
editar(RAIZ, '[defaults]\nremote = "nas"\n\n[daemon]\ninterval_minutes = 10\n')
releer(ag)
c("un config sin parejas no escribe el registro: se suelta como siempre",
  F.lock(RAIZ), {})

raise SystemExit(c.report())
