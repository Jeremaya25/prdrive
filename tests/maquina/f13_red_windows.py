"""F13: una carpeta compartida por red (SMB de verdad) no se vigila con avisos en Windows."""

from pathlib import Path

import comun
from common import avisos_carpeta as ac
from common import huella

CODIGO = "F13"
SISTEMA = "W"
QUE = "carpeta de red (SMB por la propia máquina): sin avisos, con motivo, y el recorrido la ve"
K = ("u" * 32, "red")
RECURSO = "prdrive-prueba"


def probar(p: comun.Prueba) -> None:
    """Comparte una carpeta y la vigila por su ruta UNC."""
    compartida = comun.carpeta("compartida")
    (compartida / "docs").mkdir()
    (compartida / "docs" / "a.txt").write_text("a", encoding="utf-8")
    if comun.ejecutar(["net", "share", f"{RECURSO}={compartida}", "/GRANT:Everyone,FULL"]
                      ).returncode != 0:
        raise comun.Saltada("no se ha podido compartir la carpeta")
    try:
        unc = Path(rf"\\localhost\{RECURSO}\docs")
        api = ac.Win32()
        p.ver("GetDriveTypeW dice que es de red", api.tipo_de_unidad(rf"\\localhost\{RECURSO}\\"),
              ac.DRIVE_REMOTE)
        motor = ac.ReadDirectoryChanges(api, 1)
        try:
            p.ver("no se vigila con avisos, y se dice", motor.vigilar(K, unc, ()),
                  ac.MOTIVO_RED_WINDOWS)
            p.ver("  sin nada abierto", motor.vigilancias(), 0)
        finally:
            motor.cerrar()
        foto = huella.de_carpeta(unc)
        p.ver("el recorrido sí la ve", foto is not None and foto.entradas, 1)
    finally:
        comun.ejecutar(["net", "share", RECURSO, "/delete", "/y"])
