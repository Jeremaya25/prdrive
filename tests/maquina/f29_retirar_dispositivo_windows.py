"""F29: retirar el dispositivo de un volumen (cfgmgr32): la cadena volumen → disco → padres, sobre un disco virtual."""

import comun
from common import expulsar

CODIGO = "F29"
SISTEMA = "W"
QUE = ("retirar el dispositivo de un volumen (cfgmgr32): la cadena disco → padres se lee de verdad, "
       "un disco virtual no se retira y la petición a Windows contesta sin tocar nada")
DEVINST_INVALIDO = 0xFFFFFFFF
"""Un `DEVINST` que no es de ningún dispositivo: la petición contesta con un error y no toca nada."""


def probar(p: comun.Prueba) -> None:
    """Lee la cadena de un disco virtual, comprueba que no se retira y que cfgmgr32 contesta."""
    with comun.volumen_windows("ntfs") as raiz:
        letra = expulsar._letra(raiz)
        cadena = expulsar._cadena_windows(letra)
        p.ver("la cadena de dispositivos del volumen se lee (el disco y algún padre)",
              cadena is not None and len(cadena) >= 2, True)
        if cadena:
            p.nota("cadena: " + " → ".join(
                f"{n.id}{' [extraíble]' if n.extraible else ''}" for n in cadena))
            p.ver("  sin repetir ningún dispositivo", len({n.id for n in cadena}), len(cadena))
        bus = expulsar._bus_windows(letra)
        p.nota(f"bus del volumen (extraíble declarado, tipo): {bus}")
        p.ver("el bus se lee", bus is not None, True)
        elegido = expulsar._elegir_nodo(cadena or [])
        p.nota(f"con solo la cadena se retiraría: {elegido.id if elegido else 'ningún dispositivo'}")
        p.ver("un disco virtual no se da por retirable: lo para el bus, no la cadena",
              expulsar._dispositivo_a_retirar(letra), None)

        cm = expulsar._cfgmgr32()
        cr, veto, quien = expulsar._pedir_retirada(cm, DEVINST_INVALIDO)
        p.nota(f"CM_Request_Device_EjectW de un DEVINST que no existe: CONFIGRET {cr:#x}, "
               f"veto {veto}, nombre {quien!r}")
        p.ver("la petición a Windows contesta con un error y no se cuelga ni rompe",
              cr != expulsar.CR_SUCCESS, True)
        cr, veto, quien = expulsar._retirar_dispositivo("ROOT\\NO_EXISTE\\0000")
        p.ver("un id de instancia que no existe no se encuentra, y no se pide nada",
              (cr != expulsar.CR_SUCCESS, veto, quien), (True, 0, ""))

        r = expulsar.expulsar(raiz)
        p.ver("«Expulsar» de un disco virtual sale como siempre (se desmonta; no hay dispositivo que retirar)",
              r.ok, True)
        if not r.ok:
            p.nota(f"«Expulsar» dijo: {r.texto}")
