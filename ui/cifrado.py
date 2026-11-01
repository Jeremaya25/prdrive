#!/usr/bin/env python3
"""Lo que la ventana necesita saber de un dispositivo VeraCrypt, sin Tkinter.

Cerrar la ventana no cierra el contenedor, y con el `.hc` abierto Windows no
deja extraer la unidad y tirar del cable puede estropear lo de dentro. Aquí se
decide si hay que ofrecer «Expulsar» y se lanza.

Lo que expulsa no es este proceso sino el script del vestíbulo
(`install/vestibulo.py`), que vive FUERA del contenedor. Este proceso corre
desde DENTRO (el Python del dispositivo está en `.prdrive/runtime/`) y mientras
corra VeraCrypt no puede desmontar sin forzar: reintenta solo 1,5 s
(`Common/Dlgcode.h`). Así que la ventana lanza el script y se cierra; el script
espera a que se haya ido y le pide a VeraCrypt que desmonte, sin `/silent`,
para que pregunte si queda algo abierto.

La raíz cifrada de un EQUIPO no tiene script: la abre y la cierra el agente
residente. Ahí el botón es «Bloquear» y lo que hace es pedírselo al agente por
el buzón de la raíz (`state/servicio.pide`) y cerrar la ventana: el agente
espera a que se haya ido y desmonta, también sin `/silent`.

También decide la casilla «Proteger la contraseña de VeraCrypt de los
keyloggers» de «Ajustes → Configuración» (#199): una línea de la marca del
vestíbulo, que la ventana lee en su lectura de fondo (`escritorio_seguro()`) y
escribe al «Guardar» (`guardar_escritorio_seguro()`).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import NamedTuple

from common import vestibulo


def expulsion(fisica: Path | None | object = vestibulo.BUSCAR) -> Path | None:
    """Devuelve el script que cierra el contenedor de ESTE dispositivo, o `None`.

    Es `None` cuando el dispositivo no vive en un contenedor o cuando su
    vestíbulo no tiene el script (un dispositivo de antes al que no se le ha
    pasado «Añadir plataformas…»): entonces no hay botón que ofrecer.

    Args:
        fisica: La raíz física del contenedor si quien llama ya la ha buscado
            (`ui/instantanea.py` la busca una vez para todas sus lecturas);
            `None` es «no vive en un contenedor». Por defecto se busca.
    """
    if fisica is vestibulo.BUSCAR:
        from common import fleet
        fisica = vestibulo.raiz_fisica(fleet.device_id())
    if fisica is None:
        return None
    script = fisica / (vestibulo.EXPULSAR_BAT if os.name == "nt"    # type: ignore[operator]
                       else vestibulo.EXPULSAR_SH)
    try:
        return script if script.is_file() else None
    except OSError:
        return None


def lanzar_expulsion(script: Path) -> None:
    """Lanza el script de expulsar, suelto, para que sobreviva a esta ventana.

    En Windows es `os.startfile`: lo mismo que un doble clic, con su consola
    (el script enseña ahí que ya se puede quitar la unidad). En Linux, `sh` en
    una sesión nueva. En los dos, con el directorio de trabajo en la raíz
    física: heredar el de esta ventana lo dejaría dentro del contenedor y eso
    solo ya impide desmontarlo. Es una indirección de módulo, como
    `ui.abrir()`: los tests la sustituyen.
    """
    if os.name == "nt":
        os.startfile(str(script), cwd=str(script.parent))   # type: ignore[attr-defined]
        return
    subprocess.Popen(["sh", str(script)], cwd=str(script.parent),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def nombrar_letra() -> None:
    """Le pasa al Explorador el nombre y el icono de este volumen, si es uno de VeraCrypt.

    Y antes borra las claves que se quedaron de volúmenes ya cerrados
    (`common/explorador.py`: el Explorador no lee el `autorun.inf` de un volumen
    VeraCrypt). Lo hacen la ventana, en un hilo tras su primer pintado, y el
    servicio al arrancar: así arranca prdrive desde un contenedor recién
    abierto (`Abrir PRDRIVE.bat`, penwatch). Si este dispositivo no vive en la
    letra de un volumen VeraCrypt no se toca el registro. No lanza.
    """
    from common import explorador, model
    if not explorador.letra_veracrypt(model.DEVICE_ROOT):
        return
    explorador.limpiar()
    explorador.poner(model.DEVICE_ROOT)


def olvidar_letra() -> None:
    """Quita el nombre y el icono que prdrive le puso a la letra de este volumen.

    Va tras lanzar la expulsión: el volumen se va y la letra queda para otra
    unidad (`common/explorador.py`). Solo las claves de este dispositivo; fuera
    de Windows, o sin ninguna, no hace nada. No lanza.
    """
    from common import explorador, fleet, model
    explorador.quitar(model.DEVICE_ROOT, fleet.device_id() or None)


def bloqueo() -> str | None:
    """Devuelve el id de ESTA raíz si es la raíz cifrada de este equipo, o `None`.

    Con eso el pie ofrece «Bloquear» en vez de «Expulsar». Solo lee ficheros:
    el `tipo=` del fichero de control y la lista del agente (`agente.json`).
    """
    from common import equipo, fleet, model
    if not model.es_equipo():
        return None
    uid = fleet.device_id()
    unidad = equipo.leer_ajustes().unidades.get(uid or "")
    return uid if unidad is not None and unidad.cifrada else None


def pedir_bloqueo(uid: str) -> bool:
    """Le pide al agente que bloquee esta raíz y devuelve si ha podido.

    Va por el buzón de la raíz (`state/servicio.pide`) y no por el del equipo:
    es cosa de esta raíz. El id va igual, aunque el agente se fía del sitio del
    buzón y no de él. Devuelve `False` si no hay agente vivo que lo lea o no se
    ha podido escribir. Es una indirección de módulo, como
    `lanzar_expulsion()`: los tests la sustituyen.
    """
    from common import equipo, model
    if equipo.agente_vivo() is None:
        return False
    return equipo.pedir({"pide": equipo.PIDE_BLOQUEAR, "id": uid},
                        model.STATE_DIR / equipo.BUZON_SERVICIO)


class EscritorioSeguro(NamedTuple):
    """La casilla «Proteger la contraseña de VeraCrypt de los keyloggers» de este dispositivo.

    Args:
        fisica: Donde está la marca del vestíbulo: la raíz física de la unidad o
            la carpeta del contenedor de la raíz del equipo. Ahí se escribe.
        valor: Si la marca la pide (`vestibulo.escritorio_seguro()`).
        bat_anterior: Si al lado hay un «Abrir PRDRIVE.bat» de antes de la opción,
            que no la cumple (no lleva `vestibulo.ETIQUETA_PROTECCION_BAT`). Los
            lanzadores llegan con «Añadir plataformas…», nunca al actualizar.
    """
    fisica: Path
    valor: bool
    bat_anterior: bool


def escritorio_seguro(fisica: Path | None) -> EscritorioSeguro | None:
    """Devuelve la casilla de la protección contra keyloggers, o `None` si no hay.

    No la hay si el dispositivo no vive en un contenedor VeraCrypt (`fisica`
    `None`) o si junto al contenedor no está la marca. Lee la marca y el «Abrir
    PRDRIVE.bat» de la raíz física, así que va en la lectura de fondo de la
    ventana (`instantanea.leer()`), nunca en el hilo de Tk. Es función de módulo
    para que los tests la sustituyan.

    Args:
        fisica: La raíz física que la lectura ya ha buscado.
    """
    if fisica is None:
        return None
    try:
        if not (fisica / vestibulo.MARCA).is_file():
            return None
    except OSError:
        return None
    try:
        lineas = (fisica / vestibulo.ABRIR_BAT).read_text(
            encoding="utf-8", errors="replace").splitlines()
        anterior = vestibulo.ETIQUETA_PROTECCION_BAT not in (ln.strip() for ln in lineas)
    except OSError:
        anterior = False        # la carpeta de una raíz del equipo no tiene .bat
    return EscritorioSeguro(fisica, vestibulo.escritorio_seguro(fisica), anterior)


def guardar_escritorio_seguro(fisica: Path, valor: bool) -> bool:
    """Enciende o apaga la protección contra keyloggers en la marca; `False` si no puede.

    Es función de módulo para que los tests la sustituyan.
    """
    try:
        vestibulo.poner_escritorio_seguro(fisica, valor)
    except OSError:
        return False
    return True


def ayuda_escritorio_seguro(bat_anterior: bool) -> str:
    """Devuelve la frase de debajo de la casilla: qué cubre y qué no, en llano.

    Args:
        bat_anterior: Si el «Abrir PRDRIVE» de la unidad es de antes de la opción.
    """
    texto = ("En Windows, VeraCrypt te pide la contraseña en un escritorio aparte, donde "
             "los demás programas de tu sesión no ven lo que tecleas; si al escribirla "
             "ves tus ventanas detrás, Windows no lo ha permitido y no va protegida. En "
             "Linux solo protege en una sesión Wayland. Frena a la mayoría de los "
             "keyloggers, no a uno con permisos de administrador. Cubre la ventana de "
             "VeraCrypt al abrir, no lo que escribes en el asistente ni en una "
             "terminal. Si no se puede, se abre como siempre y se avisa. Lo guarda la "
             "marca de fuera del contenedor, así que vale en cualquier equipo.")
    if bat_anterior:
        texto += (" El «Abrir PRDRIVE» de esta unidad es anterior y no lo cumple: "
                  "ponlo al día con «Añadir plataformas…» del instalador.")
    return texto
