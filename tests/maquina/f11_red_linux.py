"""F11: una carpeta de red (NFS de verdad) no se vigila con avisos: se recorre y se dice por qué."""

from pathlib import Path

import comun
from common import avisos_carpeta as ac
from common import huella

CODIGO = "F11"
SISTEMA = "L"
QUE = "carpeta de red (NFS por la propia máquina): sin avisos, con motivo, y el recorrido la ve"
K = ("u" * 32, "red")
EXPORTADA = Path("/srv/prdrive-nfs")


def probar(p: comun.Prueba) -> None:
    """Monta un NFS de la propia máquina y lo vigila."""
    comun.apt("nfs-kernel-server", "nfs-common")
    (EXPORTADA / "docs").mkdir(parents=True, exist_ok=True)
    (EXPORTADA / "docs" / "a.txt").write_text("a", encoding="utf-8")
    Path("/etc/exports").write_text(f"{EXPORTADA} 127.0.0.1(rw,sync,no_subtree_check,"
                                    f"no_root_squash)\n", encoding="utf-8")
    comun.ejecutar(["exportfs", "-ra"])
    comun.ejecutar(["systemctl", "restart", "nfs-server"], timeout=120)
    punto = comun.carpeta("nfs")
    if comun.ejecutar(["mount", "-t", "nfs4", f"127.0.0.1:{EXPORTADA}", str(punto)],
                      timeout=120).returncode != 0:
        raise comun.Saltada("no se ha podido montar el NFS de la propia máquina")
    try:
        p.ver("mountinfo dice nfs4", ac.sistema_de(punto / "docs"), "nfs4")
        motor = ac.abrir()
        try:
            motivo = motor.vigilar(K, punto / "docs", ())
            p.ver("no se vigila con avisos, y se dice que es de red",
                  "red" in (motivo or ""), True)
            p.ver("  sin vigilancias puestas", motor.vigilancias(), 0)
        finally:
            motor.cerrar()
        foto = huella.de_carpeta(punto / "docs")
        p.ver("el recorrido sí la ve", foto is not None and foto.entradas, 1)
    finally:
        comun.ejecutar(["umount", "-l", str(punto)])
