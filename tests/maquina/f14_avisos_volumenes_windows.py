"""F14: ReadDirectoryChangesW en NTFS, exFAT y FAT32 de verdad, con la ventana de verdad de la bandeja."""

import os
import shutil

import comun
from common import avisos_carpeta as ac

CODIGO = "F14"
SISTEMA = "W"
QUE = "ReadDirectoryChangesW en volúmenes NTFS, exFAT y FAT32: los cambios avisan, la copia grande también"
K = ("u" * 32, "docs")
IGN = (".prversions", ".prdrive", ".keychain")


def probar(p: comun.Prueba) -> None:
    """Prueba los tres sistemas de ficheros, cada uno en su disco virtual."""
    with comun.bandeja_windows() as (bandeja, _avisos):
        for tipo, letra in (("ntfs", "R"), ("exfat", "S"), ("fat32", "T")):
            with comun.volumen_windows(tipo, letra) as raiz:
                datos = raiz / "datos"
                (datos / "sub").mkdir(parents=True)
                (datos / ".prversions").mkdir()
                motor = ac.abrir(hwnd=bandeja.hwnd)
                bandeja.dispositivo = motor.dispositivo
                try:
                    p.ver(f"{tipo}: se vigila, con su aviso de extracción", motor.vigilar(
                        K, datos, IGN), None)
                    cambio = {K: ac.CAMBIO}
                    (datos / "a.txt").write_text("a", encoding="utf-8")
                    p.ver(f"{tipo}: un fichero nuevo avisa", comun.avisos(motor), cambio)
                    (datos / "a.txt").write_text("aa", encoding="utf-8")
                    p.ver(f"{tipo}: guardarlo otra vez", comun.avisos(motor), cambio)
                    os.rename(datos / "a.txt", datos / "b.txt")
                    p.ver(f"{tipo}: renombrarlo", comun.avisos(motor), cambio)
                    os.rename(datos / "sub", datos / "movida")
                    p.ver(f"{tipo}: renombrar una carpeta", comun.avisos(motor), cambio)
                    (datos / "movida" / "c.txt").write_text("c", encoding="utf-8")
                    p.ver(f"{tipo}: y guardar dentro (el árbol se sigue solo)",
                          comun.avisos(motor), cambio)
                    (datos / ".prversions" / "v.txt").write_text("v", encoding="utf-8")
                    p.ver(f"{tipo}: .prversions no avisa", comun.quieto(motor), {})
                    origen = comun.arbol(comun.carpeta(f"copia-{tipo}"), 0, ficheros=5000)
                    shutil.copytree(origen, datos / "copia")
                    p.ver(f"{tipo}: copiar 5 000 ficheros avisa (cambio o desbordado)",
                          comun.avisos(motor).get(K) in (ac.CAMBIO, ac.DESBORDADO), True)
                    comun.asentar(motor)
                    p.ver(f"{tipo}: y luego, quieta, nada", comun.quieto(motor, 3.0), {})
                    p.ver(f"{tipo}: con su carpeta abierta todo el rato", motor.vigilancias(), 1)
                finally:
                    motor.cerrar()
                    bandeja.dispositivo = None
