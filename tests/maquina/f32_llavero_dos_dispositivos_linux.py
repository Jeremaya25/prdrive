"""F32: el llavero entre un dispositivo en ext4 y otro en exFAT de verdad (Linux), con el rclone fijado (#115, #116)."""

import comun
import llavero_dos

CODIGO = "F32"
SISTEMA = "L"
QUE = ("el llavero con dos dispositivos contra el mismo remoto, uno en ext4 y otro en exFAT: traer "
       "el del remoto no deja al primero fallando (LL-6), el segundo no tiene conflictos sin tocar "
       "la base (LL-7) y «han cambiado todos» se repite una vez con --force")


def probar(p: comun.Prueba) -> None:
    """Monta los dos dispositivos, cada uno en un volumen sobre un dispositivo loop, y hace los tres guiones.

    El exFAT de Linux no redondea la hora hacia arriba como el de Windows: aquí se comprueba que
    las mismas pasadas van igual de bien, y el redondeo lo prueba la versión de Windows.
    """
    comun.rclone_fijado()
    with comun.volumen_linux("ext4") as ext4, comun.volumen_linux("exfat") as exfat:
        llavero_dos.escenario(p, "ext4", ext4, "exFAT", exfat)
