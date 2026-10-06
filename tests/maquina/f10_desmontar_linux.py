"""F10: desmontar un volumen con vigilancias puestas funciona y pierde la pareja."""

import comun
from common import avisos_carpeta as ac

CODIGO = "F10"
SISTEMA = "L"
QUE = "desmontar FAT32 y exFAT con vigilancias puestas: umount no protesta y la pareja se pierde"
K = ("u" * 32, "docs")


def probar(p: comun.Prueba) -> None:
    """Desmonta con la vigilancia puesta."""
    comun.por_cada(p, ("vfat", "exfat"), lambda tipo: uno(p, tipo))


def uno(p: comun.Prueba, tipo: str) -> None:
    """Desmonta un sistema de ficheros con la vigilancia puesta."""
    with comun.volumen_linux(tipo) as punto:
        (punto / "datos" / "sub").mkdir(parents=True)
        motor = ac.abrir()
        try:
            p.ver(f"{tipo}: se vigila", motor.vigilar(K, punto / "datos", ()), None)
            rc = comun.ejecutar(["umount", str(punto)], timeout=60).returncode
            p.ver(f"{tipo}: umount con vigilancias puestas sale bien", rc, 0)
            avisos = motor.recoger()
            p.ver(f"{tipo}: la pareja se pierde", {k: a.tipo for k, a in avisos.items()},
                  {K: ac.PERDIDA})
            p.ver(f"{tipo}: sin vigilancias que quitar", motor.vigilancias(), 0)
        finally:
            motor.cerrar()
