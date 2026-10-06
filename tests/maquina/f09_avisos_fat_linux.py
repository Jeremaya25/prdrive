"""F9: inotify en FAT32 y exFAT de verdad (y ext4): cada cambio avisa, una copia grande también."""

import os
import shutil

import comun
from common import avisos_carpeta as ac

CODIGO = "F9"
SISTEMA = "L"
QUE = "inotify en volúmenes FAT32, exFAT y ext4: los cambios avisan, la copia grande también"
K = ("u" * 32, "docs")
IGN = (".prversions", ".prdrive", ".keychain")


def tipos(motor) -> dict:
    """Los avisos recogidos, con su tipo."""
    return {k: a.tipo for k, a in motor.recoger().items()}


def probar(p: comun.Prueba) -> None:
    """Prueba los tres sistemas de ficheros."""
    for tipo in ("vfat", "exfat", "ext4"):
        with comun.volumen_linux(tipo) as punto:
            datos = punto / "datos"
            (datos / "sub").mkdir(parents=True)
            (datos / ".prversions").mkdir()
            p.ver(f"{tipo}: mountinfo lo dice", ac.sistema_de(datos), tipo)
            motor = ac.abrir()
            try:
                p.ver(f"{tipo}: se vigila", motor.vigilar(K, datos, IGN), None)
                cambio = {K: ac.CAMBIO}
                (datos / "a.txt").write_text("a", encoding="utf-8")
                p.ver(f"{tipo}: un fichero nuevo avisa", tipos(motor), cambio)
                (datos / "a.txt").write_text("aa", encoding="utf-8")
                p.ver(f"{tipo}: guardarlo otra vez", tipos(motor), cambio)
                os.rename(datos / "a.txt", datos / "b.txt")
                p.ver(f"{tipo}: renombrarlo", tipos(motor), cambio)
                (datos / "nueva").mkdir()
                p.ver(f"{tipo}: una carpeta nueva", tipos(motor), cambio)
                (datos / "nueva" / "c.txt").write_text("c", encoding="utf-8")
                p.ver(f"{tipo}: y lo de dentro", tipos(motor), cambio)
                (datos / ".prversions" / "v.txt").write_text("v", encoding="utf-8")
                p.ver(f"{tipo}: .prversions no avisa", tipos(motor), {})
                os.rename(datos / "sub", datos / "movida")
                p.ver(f"{tipo}: mover una carpeta pide rehacer", tipos(motor),
                      {K: ac.DESBORDADO})
                p.ver(f"{tipo}: rehecha", motor.vigilar(K, datos, IGN), None)
                (datos / "movida" / "d.txt").write_text("d", encoding="utf-8")
                p.ver(f"{tipo}: lo de la movida se ve", tipos(motor), cambio)
                origen = comun.arbol(comun.carpeta(f"copia-{tipo}"), 0, ficheros=5000)
                shutil.copytree(origen, datos / "copia")
                p.ver(f"{tipo}: copiar 5 000 ficheros avisa (cambio o desbordado)",
                      tipos(motor).get(K) in (ac.CAMBIO, ac.DESBORDADO), True)
                p.ver(f"{tipo}: y luego, quieta, nada", tipos(motor), {})
            finally:
                motor.cerrar()
