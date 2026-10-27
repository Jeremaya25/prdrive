"""F34: VeraCrypt INSTALADO en la bandeja ante un volumen que se desenchufa, y el fantasma al volver (#41)."""

import os
import subprocess

import comun
from common import vestibulo

CODIGO = "F34"
SISTEMA = "W"
QUE = ("VeraCrypt instalado (#41): ¿la letra de dentro se va al desconectar el disco con la "
       "bandeja en segundo plano y sin ella?; y al volver, el `.hc` queda libre (el fantasma)")


def vivo() -> bool:
    """Indica si hay un `VeraCrypt.exe` en marcha."""
    r = subprocess.run(["tasklist", "/fi", "imagename eq VeraCrypt.exe", "/nh"],
                       capture_output=True, text=True, timeout=30)
    return "veracrypt.exe" in r.stdout.lower()


def matar() -> None:
    """Acaba con cualquier VeraCrypt en segundo plano."""
    subprocess.run(["taskkill", "/f", "/im", "VeraCrypt.exe"], capture_output=True, timeout=30)


def probar(p: comun.Prueba) -> None:
    """Desconecta el VHD con el contenedor montado, con y sin VeraCrypt en la bandeja."""
    if not comun.es_administrador():
        raise comun.Saltada("diskpart y VeraCrypt piden una sesión elevada")
    with comun.volumen_windows("exFAT") as fisica:
        letra_fisica = str(fisica)[0]
        fichero = comun.vhd_de[letra_fisica]
        carpeta_hc = fisica / "cifrado"
        c = comun.Contenedor(carpeta_hc)
        if c.portable:
            raise comun.Saltada("esta prueba es del VeraCrypt INSTALADO y aquí solo hay el Portable")
        hc = c.hc

        def montar_con_control() -> bool:
            """Monta el contenedor y deja dentro un fichero de control como el de prdrive."""
            if not c.montar():
                return False
            control = c.raiz / ".prdrive" / "PRDRIVE"
            control.parent.mkdir(exist_ok=True)
            control.write_text("id=" + "f" * 32 + "\n", encoding="utf-8")
            return True

        def desconectar() -> bool:
            """Desconecta el VHD y devuelve si la letra física se fue."""
            comun.soltar_vhd(fichero)
            return comun.esperar(lambda: not fisica.exists(), 20)

        try:
            # Caso A: VeraCrypt en segundo plano (`/q background`).
            if not montar_con_control():
                raise comun.Saltada("VeraCrypt no ha montado el contenedor (¿su controlador?)")
            subprocess.Popen([str(c.vc), "/q", "background"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            if not comun.esperar(vivo, 15):
                p.saltados.append("caso A: VeraCrypt no ha quedado vivo en segundo plano")
            else:
                if not desconectar():
                    p.saltados.append("caso A: diskpart no deja desconectar el VHD con el "
                                      ".hc abierto")
                else:
                    se_fue = comun.esperar(lambda: not c.raiz.exists(), 20)
                    p.nota(f"A (en segundo plano, VeraCrypt instalado): al desconectar el "
                           f"disco, la letra de dentro {'se va' if se_fue else 'SIGUE'} "
                           f"en 20 s; VeraCrypt sigue vivo: {vivo()}")
                matar()
                if c.raiz.exists():
                    c.desmontar(forzar=True)
                comun.conectar_vhd(fichero, letra_fisica)
            matar()

            # Caso B: sin VeraCrypt en la bandeja (el montaje con /quit no deja ninguno).
            if not fisica.exists() and not comun.conectar_vhd(fichero, letra_fisica):
                raise comun.Saltada("no se ha podido volver a conectar el VHD")
            if not montar_con_control():
                raise comun.Saltada("VeraCrypt no ha vuelto a montar el contenedor")
            p.ver("B: montado, con el .hc retenido", vestibulo.retenido(hc), True)
            p.nota(f"B: VeraCrypt vivo tras montar: {vivo()}")
            if not desconectar():
                raise comun.Saltada("B: diskpart no deja desconectar el VHD con el .hc abierto")
            fantasma = c.raiz.exists()
            lee = False
            if fantasma:
                try:
                    lee = (c.raiz / ".prdrive" / "PRDRIVE").read_text(encoding="utf-8").startswith("id=")
                except OSError:
                    lee = False
            p.nota(f"B (sin bandeja): al desconectar, la letra de dentro "
                   f"{'SIGUE (fantasma)' if fantasma else 'se va'}; "
                   f"`.prdrive/PRDRIVE` se lee: {lee}")
            if not fantasma:
                p.saltados.append("B: no ha quedado fantasma, así que no hay frontera que mirar")
            if not comun.conectar_vhd(fichero, letra_fisica):
                raise comun.Saltada("B: no se ha podido volver a conectar el VHD")
            p.ver("B: al volver a conectar, el .hc está", hc.exists(), True)
            if fantasma:
                p.ver("B: con el fantasma puesto, `retenido(hc)` es False (la frontera de "
                      "`Agente._fantasmas_extraibles`)", vestibulo.retenido(hc), False)
        finally:
            matar()
            if c.raiz.exists():
                if os.environ.get("GITHUB_ACTIONS"):
                    c.desmontar(forzar=True)        # máquina de usar y tirar
                else:
                    c.soltar()
