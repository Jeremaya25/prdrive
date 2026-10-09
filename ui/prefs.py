#!/usr/bin/env python3
"""Las parejas y el intervalo del servicio.

El servicio periódico es uno solo, se arranque a mano («Iniciar servicio») o al
enchufar el dispositivo (el vigilante, `runsync --auto`, o el agente del
equipo), y su configuración vive en `state/ui_prefs.json`: viaja en el
dispositivo y acompaña a la persona de una máquina a otra. Es también con lo
que sale precargada la ventana. Ese recuerdo manda sobre `[daemon]` del TOML,
que a su vez manda sobre los valores de fábrica.

Lo escriben tres sitios, cada uno con lo suyo:
- Las casillas de la ventana (`guardar_parejas`): las parejas marcadas.
  Conserva el intervalo guardado y no fija uno si no lo hay. Los clics no la
  llaman uno a uno: `SeleccionPendiente` apunta la última selección y la
  vuelca pasados `ESPERA_MS` sin más clics y siempre antes de lanzar una
  pasada, de iniciar el servicio o de cerrar la ventana.
- «Iniciar servicio» (`save_prefs`, desde `runsync`): las parejas marcadas y
  el intervalo con el que arranca, que es el que ya estaba guardado.
- «Ajustes → Configuración» (`guardar_intervalo`): SOLO el intervalo. Si ya
  había parejas elegidas se conservan tal cual; si no, el registro queda sin
  parejas y estas siguen saliendo de `[daemon]` del TOML.

«Sincronizar ahora» no escribe nada por sí mismo: lo que guarda es la casilla,
no la pasada. `--auto` y el servicio únicamente leen, para que un arranque
automático nunca reescriba lo que se decidió a mano.

El fichero conserva el nombre de cuando era «lo último que se eligió en la UI»:
renombrarlo pediría una migración para cambiar una palabra.

Aparte, en `state/ventana.json`, la ventana principal recuerda su ancho
(`ancho_recordado`, `recordar_ancho`): no es cosa del servicio y no va en
`ui_prefs.json`.
"""

from __future__ import annotations

import math
import socket
import sys
from pathlib import Path
from typing import Any, Mapping

from common import model, store
from common.model import Config

PREFS = model.STATE_DIR / "ui_prefs.json"
"""El fichero con la elección del servicio, en `state/` del dispositivo."""
HOST = socket.gethostname()
"""El nombre de este equipo, para anotar quién guardó la elección."""
ESPERA_MS = 250
"""Milisegundos que la ventana espera tras la última casilla antes de volcar la selección.

Marcar varias seguidas escribe `ui_prefs.json` una vez (`SeleccionPendiente`),
no una por clic.
"""
VENTANA = "ventana.json"
"""El fichero de `state/` donde la ventana principal recuerda su ancho.

No es `ui_prefs.json` a propósito: el agente del equipo vigila la fecha de ese
fichero y recarga su servicio con cualquier cambio (`agente.py`,
`_cargar_servicio`), y el ancho de una ventana no le dice nada al servicio.
"""


def read_prefs() -> dict:
    """Devuelve la última elección guardada; vacío si aún no hay ninguna."""
    return store.read_json(PREFS)


def save_prefs(action: str, pairs: list[str], interval_min: float,
               all_names: list[str]) -> None:
    """Recuerda lo elegido para el servicio.

    `action` se sigue guardando aunque ya solo llegue `daemon`: es lo que
    distingue los registros de antes, cuando una pasada manual también escribía
    aquí (ver `elegir`).

    Args:
        action: Qué se eligió.
        pairs: Las parejas elegidas.
        interval_min: El intervalo, en minutos.
        all_names: Las parejas que existían en ese momento (`known`): así una
            pareja añadida al TOML más tarde no se confunde con una que se
            había desmarcado.
    """
    data = {
        "action": action,
        "pairs": list(pairs),
        "interval_min": interval_min,
        "known": list(all_names),
        "host": HOST,
        "saved": store.stamp(),
    }
    old = read_prefs()
    if all(old.get(k) == v for k, v in data.items() if k not in ("host", "saved")):
        return  # misma elección que la vez anterior: no se gasta escritura en el dispositivo
    store.write_json(PREFS, data)  # si el dispositivo ya no está, recordar no es vital


def revisar_intervalo(texto: str) -> float:
    """Devuelve los minutos escritos en «Configuración», con la coma decimal admitida.

    Raises:
        ValueError: Con la frase que enseñar si no es un número de minutos de 1
            o más.
    """
    try:
        minutos = float(str(texto).strip().replace(",", "."))
    except ValueError:
        minutos = math.nan
    if not math.isfinite(minutos) or minutos < 1:
        raise ValueError("El intervalo tiene que ser un número de minutos: 1 o más.")
    return minutos


def guardar_intervalo(config: Config, minutos: float) -> bool:
    """Guarda el intervalo del servicio sin tocar sus parejas.

    Es lo que guarda «Ajustes → Configuración». Si el registro tiene parejas
    que siguen valiendo (las que `elegir` respeta), se conservan, y con ellas
    `action` y `known`: solo cambia el intervalo. Si no las tiene (no hay
    registro, es uno `manual` de antes o ninguna de sus parejas existe ya),
    queda un registro sin `pairs`, y las parejas del servicio siguen saliendo
    de `[daemon]` del TOML: guardar el intervalo no fija qué se sincroniza.

    Args:
        config: La configuración del dispositivo, para saber qué parejas hay.
        minutos: El intervalo, ya revisado (`revisar_intervalo`).

    Returns:
        False si no se ha podido escribir; True si se ha escrito o ya estaba
        así.
    """
    old = read_prefs()
    sin_sello = {k: v for k, v in old.items() if k not in ("host", "saved")}
    if "pairs" in old and _recordadas(config.names, old):
        data = {**sin_sello, "interval_min": max(1.0, float(minutos))}
    else:
        data = {"interval_min": max(1.0, float(minutos))}
    if data == sin_sello:
        return True  # ya estaba así: no se gasta escritura en el dispositivo
    return store.write_json(PREFS, {**data, "host": HOST, "saved": store.stamp()})


def guardar_parejas(config: Config, pairs: list[str]) -> bool:
    """Guarda las parejas marcadas en la ventana, sin fijar el intervalo.

    Es lo que guardan las casillas de la ventana (`SeleccionPendiente`).
    Conserva el intervalo ya guardado («Configuración») y, si no lo hay, no
    escribe uno: el del TOML sigue mandando. No guarda una selección vacía, que
    `elegir` leería como si no hubiera recuerdo.

    Args:
        config: La configuración del dispositivo, para saber qué parejas hay.
        pairs: Las parejas marcadas. Se guardan en el orden del TOML y sin las
            que ya no existen.

    Returns:
        True si se ha escrito o ya estaba así; False si no se ha podido
        escribir o la selección no tiene ninguna pareja.
    """
    elegidas = [n for n in config.names if n in set(pairs)]
    if not elegidas:
        return False
    old = read_prefs()
    data = {"action": "daemon", "pairs": elegidas, "known": list(config.names)}
    minutos = _minutos(old, None)
    if minutos is not None:
        data["interval_min"] = minutos
    if data == {k: v for k, v in old.items() if k not in ("host", "saved")}:
        return True  # ya estaba así: no se gasta escritura en el dispositivo
    return store.write_json(PREFS, {**data, "host": HOST, "saved": store.stamp()})


class SeleccionPendiente:
    """La última selección de casillas que aún no se ha escrito en `ui_prefs.json`.

    Un clic en una casilla solo la apunta (`poner`); la ventana la escribe
    (`volcar`) pasados `ESPERA_MS` sin más clics, y siempre antes de lanzar una
    pasada, de iniciar el servicio o de cerrarse, que es cuando el servicio y
    el agente pueden leerla. Se usa solo desde el hilo de Tk.
    """

    def __init__(self) -> None:
        self._pendiente: tuple[Config, list[str]] | None = None

    @property
    def pendiente(self) -> bool:
        """Indica si hay una selección apuntada sin escribir."""
        return self._pendiente is not None

    def poner(self, config: Config, pares: list[str]) -> None:
        """Apunta la selección, sustituyendo a la anterior. No escribe nada.

        Una selección vacía no sustituye a una pendiente con alguna pareja:
        desmarcarlas todas seguidas deja escrita la última que tenía alguna,
        como cuando cada clic escribía y la vacía no se guardaba.

        Args:
            config: La configuración del dispositivo, para saber qué parejas hay.
            pares: Las parejas marcadas.
        """
        if not pares and self._pendiente is not None and self._pendiente[1]:
            return
        self._pendiente = (config, list(pares))

    def volcar(self) -> bool | None:
        """Escribe la última selección apuntada y se olvida de ella.

        Nunca lanza: que el dispositivo no se deje escribir no es motivo para
        que una pasada o el cierre de la ventana no sigan adelante.

        Returns:
            `None` si no había nada apuntado (y no se toca el fichero); si lo
            había, lo que devuelve `guardar_parejas`: `False` si no se ha
            podido escribir o la selección no tenía ninguna pareja.
        """
        if self._pendiente is None:
            return None
        config, pares = self._pendiente
        self._pendiente = None
        try:
            return guardar_parejas(config, pares)
        except Exception:                                # noqa: BLE001
            return False


def daemon_defaults(config: Config) -> tuple[list[str], float]:
    """Devuelve `[daemon]` del TOML, saneado contra las parejas que existen."""
    return _de_daemon(config.names, config.daemon)


def _de_daemon(names: list[str], daemon: Mapping[str, Any]) -> tuple[list[str], float]:
    """Devuelve las parejas y el intervalo de una tabla `[daemon]`, saneados."""
    pedidas = daemon.get("pairs", names)
    pairs = [n for n in (pedidas if isinstance(pedidas, list) else names)
             if n in names] or list(names)
    try:
        interval = float(daemon.get("interval_minutes", model.DEFAULT_INTERVAL_MIN))
    except (TypeError, ValueError):
        interval = model.DEFAULT_INTERVAL_MIN
    return pairs, interval


def startup_defaults(config: Config) -> tuple[list[str], float, str | None]:
    """Devuelve las parejas, el intervalo y una nota con los que sale el servicio.

    Es con lo que sale precargada la UI y con lo que arranca `--auto` sin
    argumentos. Precedencia: lo guardado (al arrancar el servicio, o el
    intervalo de «Configuración») > `[daemon]` del TOML > todas las parejas
    cada 30 min.

    Returns:
        `(parejas, minutos, nota)`. La nota es `None` si no hay recuerdo y, si
        lo hay, el texto con el que la UI dice de dónde salen.
    """
    return elegir(config.names, config.daemon, read_prefs())


def _recordadas(all_names: list[str], prefs: Mapping[str, Any]) -> list[str]:
    """Devuelve las parejas del recuerdo que siguen valiendo, en el orden del TOML.

    Es una lista vacía si el recuerdo no decide las parejas: no lo hay, es un
    registro `manual` o nada de lo que nombra existe ya.
    """
    # Un registro `manual` solo puede ser de antes de que las pasadas manuales
    # dejaran de escribir aquí, y es el recuerdo de una pasada suelta que no
    # debe decidir el servicio. Se descarta por `manual` y no por «distinto de
    # `daemon`»: uno sin `action`, escrito a mano, sigue valiendo.
    if not prefs or prefs.get("action") == "manual":
        return []
    saved = prefs.get("pairs")
    remembered = {n for n in saved if isinstance(n, str)} if isinstance(saved, list) else set()
    known = prefs.get("known")
    if isinstance(known, list):
        # Parejas añadidas al TOML después de aquella elección: nadie las ha
        # desmarcado, así que entran marcadas.
        remembered |= {n for n in all_names if n not in known}
    return [n for n in all_names if n in remembered]


def _minutos(prefs: Mapping[str, Any], defecto: float | None) -> float | None:
    """Devuelve el intervalo guardado, como mínimo 1 min, o `defecto` si no vale."""
    try:
        minutos = float(prefs.get("interval_min", defecto))
    except (TypeError, ValueError):
        return defecto
    return max(1.0, minutos) if math.isfinite(minutos) else defecto


def elegir(all_names: list[str], daemon: Mapping[str, Any],
           prefs: Mapping[str, Any]) -> tuple[list[str], float, str | None]:
    """Devuelve lo mismo que `startup_defaults()` con los datos ya leídos.

    Son las parejas de la raíz, su tabla `[daemon]` y su `ui_prefs.json`. Está
    aparte y sin tocar el disco porque el agente del equipo (`agente.py`) hace
    de servicio de raíces que no son la suya: lee esos tres datos de cada una y
    decide con esta misma regla, en vez de con una segunda copia que se
    separaría de esta.

    Un registro sin `pairs` es el que deja «Configuración» cuando no había
    parejas elegidas: vale su intervalo, y las parejas son las del TOML.
    """
    d_pairs, d_interval = _de_daemon(all_names, daemon)
    if not prefs or prefs.get("action") == "manual":
        return d_pairs, d_interval, None
    when = prefs.get("saved")

    if "pairs" not in prefs:
        interval = _minutos(prefs, None)
        if interval is None:
            return d_pairs, d_interval, None
        return d_pairs, interval, ("Intervalo del servicio"
                                   + (f", elegido el {when}" if when else ""))

    pairs = _recordadas(all_names, prefs)
    if not pairs:
        # Nada de aquello existe ya (parejas renombradas, TOML regenerado): el
        # recuerdo entero es basura y se vuelve al TOML sin anunciar nada.
        return d_pairs, d_interval, None
    return pairs, _minutos(prefs, d_interval), ("Parejas e intervalo del servicio"
                                                + (f", elegidos el {when}" if when else ""))


def ruta_ventana() -> Path:
    """Devuelve el fichero donde la principal recuerda su ancho.

    Se calcula al llamar, no al importar: los tests mueven `model.STATE_DIR`.
    """
    return model.STATE_DIR / VENTANA


def clave_ancho(version_tk: str, escala: float) -> str:
    """Devuelve con qué clave se recuerda el ancho: lo que cambia cuánto mide el texto.

    El sistema, la versión de Tk y su `tk scaling` (píxeles por punto). El
    dispositivo viaja de un equipo a otro: un ancho medido al 150 % no vale al
    100 %, ni uno de Windows en Linux.

    Args:
        version_tk: `tkinter.TkVersion`, en texto («9.0», «8.6»).
        escala: `tk scaling` de la ventana.
    """
    return f"{sys.platform}:{version_tk}:{escala:.3f}"


def ancho_recordado(clave: str) -> int | None:
    """Devuelve el ancho que pidió el contenido de la principal la última vez, o `None`.

    Es el de después de llegar su lectura del dispositivo, el que la ventana
    reserva desde el primer pintado. Nunca lanza: un fichero que falta, está a
    medias o no dice un ancho para esa clave es `None`.

    Args:
        clave: La de `clave_ancho()`.
    """
    anchos = store.read_json(ruta_ventana()).get("ancho")
    ancho = anchos.get(clave) if isinstance(anchos, dict) else None
    # `type` y no `isinstance`: un `True` también es un `int`.
    return ancho if type(ancho) is int and ancho > 0 else None


def recordar_ancho(clave: str, ancho: int) -> bool:
    """Guarda el ancho de la principal para esa clave, solo si ha cambiado.

    Conserva los de otras claves. Nunca lanza: un dispositivo de solo lectura,
    o ya extraído, simplemente no lo recuerda.

    Args:
        clave: La de `clave_ancho()`.
        ancho: Lo que pide el contenido de la ventana, en píxeles.

    Returns:
        True si se ha escrito o ya estaba así; False si no se ha podido escribir.
    """
    ruta = ruta_ventana()
    datos = store.read_json(ruta)
    anchos = datos.get("ancho")
    anchos = dict(anchos) if isinstance(anchos, dict) else {}
    if type(anchos.get(clave)) is int and anchos[clave] == ancho:
        return True  # ya estaba así: no se gasta escritura en el dispositivo
    anchos[clave] = ancho
    return store.write_json(ruta, {**datos, "ancho": anchos})
