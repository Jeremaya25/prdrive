"""F15: «Quitar hardware de forma segura» con la carpeta vigilada. Necesita un pendrive de verdad."""

import comun

CODIGO = "F15"
SISTEMA = "W"
QUE = "expulsar un pendrive desde el Explorador con la vigilancia puesta: pide un pendrive de verdad"


def probar(p: comun.Prueba) -> None:
    """Dice por qué no se puede hacer con un disco virtual.

    Con uno, «Expulsar» del Explorador no pide la unidad a quien la tiene
    abierta (`DBT_DEVICEQUERYREMOVE`): manda un `DBT_CUSTOMEVENT` y desmonta
    forzando, aunque otro programa tenga un fichero abierto dentro (visto el
    11/10/2026 con escritorio; en una máquina sin él, la orden no hace nada).
    Lo que se puede ver sin un pendrive (el bloqueo del volumen, `chkdsk`) lo
    ven F16 y F24.
    """
    raise comun.Saltada("un disco virtual no sirve para probar la extracción de un pendrive "
                        "(el Explorador lo desmonta forzando, sin DBT_DEVICEQUERYREMOVE): "
                        "queda para un pendrive de verdad")
