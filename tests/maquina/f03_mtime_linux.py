"""F3: la hora de lo que baja del remoto a ext4, exFAT y FAT32 (vfat) de verdad (Linux), con el rclone fijado (#114)."""

import comun

CODIGO = "F3"
SISTEMA = "L"
QUE = ("la hora de lo que baja del remoto a ext4, exFAT y FAT32: sin `modify-window` la pasada "
       "siguiente lo da por cambiado donde la unidad redondea; con la de fábrica, no")


def probar(p: comun.Prueba) -> None:
    """Prueba los tres sistemas de ficheros, cada uno en un volumen sobre un dispositivo loop."""
    comun.rclone_fijado()
    comun.por_cada(p, ("ext4", "exfat", "vfat"), lambda tipo: uno(p, tipo))


def uno(p: comun.Prueba, tipo: str) -> None:
    """Prueba un sistema de ficheros en su volumen."""
    with comun.volumen_linux(tipo) as raiz:
        comun.probar_hora(p, "fat32" if tipo == "vfat" else tipo, raiz)
