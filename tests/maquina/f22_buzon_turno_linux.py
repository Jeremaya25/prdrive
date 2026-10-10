"""F22: el turno del buzón (`flock` sobre su carpeta) en FAT32, exFAT y ext4 de verdad."""

import os
import sys

import comun
from common import equipo

sys.path.insert(0, str(comun.REPO / "tests"))
import _buzon_procesos  # noqa: E402

CODIGO = "F22"
SISTEMA = "L"
QUE = ("el turno del buzón en volúmenes FAT32, exFAT y ext4: el cerrojo de la carpeta "
       "excluye y ninguna petición dada por dejada se pierde")
ESCRITORES = 2          # los que piden a la vez en el buzón
SEGUNDOS = 2.0          # lo que pide cada uno


def probar(p: comun.Prueba) -> None:
    """Prueba los tres sistemas de ficheros."""
    comun.por_cada(p, ("vfat", "exfat", "ext4"), lambda tipo: uno(p, tipo))


def excluye(carpeta) -> bool | str:
    """Indica si el cerrojo exclusivo de una carpeta espera al compartido.

    Returns:
        True o False, o el error si `flock` no se deja en esa carpeta.
    """
    import fcntl                        # no lo hay en Windows, y `correr.py` carga todas las filas

    a = b = -1
    try:
        a, b = os.open(carpeta, os.O_RDONLY), os.open(carpeta, os.O_RDONLY)
        fcntl.flock(a, fcntl.LOCK_SH | fcntl.LOCK_NB)
        try:
            fcntl.flock(b, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False
    except OSError as e:
        return repr(e)
    finally:
        for fd in (a, b):
            if fd >= 0:
                os.close(fd)


def uno(p: comun.Prueba, tipo: str) -> None:
    """Prueba un sistema de ficheros: el cerrojo, y peticiones con procesos de verdad."""
    with comun.volumen_linux(tipo) as punto:
        estado = punto / ".prdrive" / "state"
        estado.mkdir(parents=True)
        p.ver(f"{tipo}: el cerrojo de la carpeta del buzón excluye al agente de quien pide",
              excluye(estado), True)
        cuenta = _buzon_procesos.pedir_y_recoger(
            comun.REPO, [estado / equipo.BUZON_SERVICIO], comun.carpeta(f"buzon-{tipo}"),
            ESCRITORES, SEGUNDOS)
        p.ver(f"{tipo}: los que piden y el que recoge acaban bien", cuenta.codigos,
              [0] * (ESCRITORES + 1))
        p.ver(f"{tipo}: se ha pedido de verdad", cuenta.dichas > 100, True)
        p.ver(f"{tipo}: ninguna petición dada por dejada se pierde", cuenta.perdidas, 0)
        p.ver(f"{tipo}: y ninguna llega dos veces", cuenta.repetidas, 0)
        p.nota(f"{tipo}: {cuenta.dichas} peticiones de {ESCRITORES} procesos a la vez")
