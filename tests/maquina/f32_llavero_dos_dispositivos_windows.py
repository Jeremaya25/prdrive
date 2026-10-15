"""F32: el llavero entre un dispositivo en NTFS y otro en exFAT de verdad (Windows), con el rclone fijado (#115, #116)."""

import comun
import llavero_dos

CODIGO = "F32"
SISTEMA = "W"
QUE = ("el llavero con dos dispositivos contra el mismo remoto, uno en NTFS y otro en exFAT: traer "
       "el del remoto no deja al primero fallando (LL-6), el segundo no tiene conflictos sin tocar "
       "la base (LL-7) y «han cambiado todos» se repite una vez con --force")

MB = 256
"""Lo que mide cada disco: el rclone fijado solo ya pesa unos 60 MB, y el dispositivo lleva el programa."""


def probar(p: comun.Prueba) -> None:
    """Monta los dos dispositivos, cada uno en su disco virtual, y hace los tres guiones."""
    comun.rclone_fijado()
    with (comun.volumen_windows("ntfs", mb=MB) as ntfs,
          comun.volumen_windows("exfat", mb=MB) as exfat):
        llavero_dos.escenario(p, "NTFS", ntfs, "exFAT", exfat)
