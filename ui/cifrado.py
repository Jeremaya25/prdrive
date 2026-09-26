#!/usr/bin/env python3
"""
cifrado.py — Lo que la ventana necesita saber de un dispositivo VeraCrypt. Sin Tkinter.

Hasta ahora la ventana no sabía que el dispositivo iba cifrado: cerrarla no
cerraba el contenedor, y la guía decía que para quitar la unidad bastaba con
cerrar la ventana. Con VeraCrypt no basta, porque el `.hc` sigue abierto: Windows
no deja extraer la unidad, y tirar del cable puede estropear lo de dentro.

Aquí se decide si hay que ofrecer «Expulsar» y se lanza. Lo que expulsa no es
este proceso: es el script del vestíbulo (`install/vestibulo.py`), que vive FUERA
del contenedor. Este proceso corre desde DENTRO —el Python del dispositivo está
en `.prdrive/runtime/`—, y mientras corra, VeraCrypt no puede desmontar sin
forzar (reintenta solo 1,5 s, `Common/Dlgcode.h`). Así que la ventana lanza el
script y se cierra; el script espera a que se haya ido y le pide a VeraCrypt que
desmonte, sin `/silent`, para que VeraCrypt pregunte si queda algo abierto.

La raíz cifrada de un EQUIPO (fase 3) no tiene script: la abre y la cierra el
agente residente. Ahí el botón es «Bloquear», y lo que hace es pedírselo al
agente por su buzón (`agente.pide`) y cerrar la ventana: el agente espera a que
se haya ido y desmonta, también sin `/silent`.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from common import vestibulo


def expulsion() -> Path | None:
    """El script que cierra el contenedor de ESTE dispositivo, o None.

    None cuando el dispositivo no vive en un contenedor, o cuando su vestíbulo
    no tiene el script (un dispositivo de antes al que no se le ha pasado
    «Añadir plataformas…»): entonces no hay botón que ofrecer."""
    from common import fleet
    fisica = vestibulo.raiz_fisica(fleet.device_id())
    if fisica is None:
        return None
    script = fisica / (vestibulo.EXPULSAR_BAT if os.name == "nt"
                       else vestibulo.EXPULSAR_SH)
    try:
        return script if script.is_file() else None
    except OSError:
        return None


def lanzar_expulsion(script: Path) -> None:
    """Lanza el script de expulsar, suelto, para que sobreviva a esta ventana.

    En Windows, `os.startfile`: lo mismo que un doble clic, con su consola (el
    script enseña ahí que ya se puede quitar la unidad). En Linux, `sh` en una
    sesión nueva. En los dos, con el directorio de trabajo en la raíz física:
    heredar el de esta ventana lo dejaría dentro del contenedor, y eso solo ya
    impide desmontarlo.

    Indirección de módulo, como `ui.abrir()`: los tests la sustituyen."""
    if os.name == "nt":
        os.startfile(str(script), cwd=str(script.parent))   # type: ignore[attr-defined]
        return
    subprocess.Popen(["sh", str(script)], cwd=str(script.parent),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def bloqueo() -> str | None:
    """El id de ESTA raíz si es la raíz cifrada de este equipo, o None.

    Con eso el pie ofrece «Bloquear» en vez de «Expulsar». Solo lee ficheros: el
    `tipo=` del fichero de control y la lista del agente (`agente.json`)."""
    from common import equipo, fleet, model
    if not model.es_equipo():
        return None
    uid = fleet.device_id()
    unidad = equipo.leer_ajustes().unidades.get(uid or "")
    return uid if unidad is not None and unidad.cifrada else None


def pedir_bloqueo(uid: str) -> bool:
    """Le pide al agente que bloquee esta raíz. False si no hay agente vivo que
    lo lea, o no se ha podido escribir.

    Indirección de módulo, como `lanzar_expulsion()`: los tests la sustituyen."""
    from common import equipo
    if equipo.agente_vivo() is None:
        return False
    return equipo.pedir({"pide": equipo.PIDE_BLOQUEAR, "id": uid})
