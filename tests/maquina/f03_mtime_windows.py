"""F3: la hora de lo que baja del remoto a NTFS, exFAT y FAT32 de verdad (Windows), con el rclone fijado (#114)."""

import comun

CODIGO = "F3"
SISTEMA = "W"
QUE = ("la hora de lo que baja del remoto a NTFS, exFAT y FAT32: sin `modify-window` la pasada "
       "siguiente lo da por cambiado; con la de fábrica, no, y sin pedir ningún --resync")


def probar(p: comun.Prueba) -> None:
    """Prueba los tres sistemas de ficheros, cada uno en su disco virtual."""
    comun.rclone_fijado()
    comun.por_cada(p, ("ntfs", "exfat", "fat32"), lambda tipo: uno(p, tipo))


def uno(p: comun.Prueba, tipo: str) -> None:
    """Prueba un sistema de ficheros en su disco virtual."""
    with comun.volumen_windows(tipo) as raiz:
        comun.probar_hora(p, tipo, raiz)
