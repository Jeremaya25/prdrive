"""F18: la pregunta 2 del diseño, con VeraCrypt de verdad: ¿avisa antes de desmontar?"""

from pathlib import Path

import comun
from common import avisos_carpeta as ac

CODIGO = "F18"
SISTEMA = "W"
QUE = "VeraCrypt: su volumen se reconoce, y si desmontarlo sin forzar avisa a un handle vigilado (pregunta 2)"
K = ("u" * 32, "docs")
DIR_VC = Path(r"C:\Program Files\VeraCrypt")
VC, FORMATO = DIR_VC / "VeraCrypt.exe", DIR_VC / "VeraCrypt Format.exe"
CLAVE = "prueba-prdrive-2026"
P = Path("P:\\")


def montar(hc: Path) -> bool:
    """Monta el contenedor en P: y espera a verlo."""
    comun.ejecutar([str(VC), "/volume", str(hc), "/letter", "P", "/password", CLAVE,
                    "/pim", "0", "/quit", "/silent"], timeout=120)
    return comun.esperar(P.exists, 60)


def desmontar(forzar: bool) -> bool:
    """Desmonta P: (forzando o no) y devuelve si se ha ido."""
    comun.ejecutar([str(VC), "/dismount", "P", "/quit", "/silent"]
                   + (["/force"] if forzar else []), timeout=120)
    return comun.esperar(lambda: not P.exists(), 20)


def probar(p: comun.Prueba) -> None:
    """Instala VeraCrypt, monta un contenedor y desmonta con un handle vigilado dentro."""
    if not VC.exists():
        comun.ejecutar(["choco", "install", "veracrypt", "-y", "--no-progress"], timeout=900)
    if not VC.exists() or not FORMATO.exists():
        raise comun.Saltada("no se ha podido instalar VeraCrypt en esta máquina")
    hc = comun.carpeta("vc") / "prueba.hc"
    comun.ejecutar([str(FORMATO), "/create", str(hc), "/size", "60M", "/password", CLAVE,
                    "/encryption", "AES", "/hash", "sha512", "/filesystem", "NTFS",
                    "/pim", "0", "/silent", "/force"], timeout=600)
    if not hc.exists() or not montar(hc):
        raise comun.Saltada("VeraCrypt no ha creado o montado el contenedor (¿su controlador?)")
    try:
        api = ac.Win32()
        dispositivo = api.dispositivo_de("P:")
        p.nota(f"dispositivo de P: {dispositivo}")
        p.ver("su volumen se reconoce como de VeraCrypt",
              dispositivo.startswith(ac.DISPOSITIVOS_VERACRYPT), True)
        motor = ac.ReadDirectoryChanges(api, 1)
        try:
            p.ver("y no se vigila con avisos", motor.vigilar(K, P / "datos", ()),
                  ac.MOTIVO_VERACRYPT)
        finally:
            motor.cerrar()
        (P / "datos").mkdir(exist_ok=True)
        with comun.bandeja_windows() as (bandeja, avisos):
            sin_comprobar = ac.Win32()
            sin_comprobar.dispositivo_de = lambda unidad: ""
            m2 = ac.ReadDirectoryChanges(sin_comprobar, bandeja.hwnd)
            bandeja.dispositivo = m2.dispositivo
            try:
                p.ver("(experimento) se vigila igual, saltándose la comprobación",
                      m2.vigilar(K, P / "datos", ()), None)
                se_fue = desmontar(forzar=False)
                pide = any(a[0] == ac.DBT_DEVICEQUERYREMOVE for a in avisos)
                bloqueo = any(a[3] == comun.GUID_IO_VOLUME_LOCK for a in avisos)
                p.nota(f"PREGUNTA 2: desmontar sin forzar con una carpeta vigilada "
                       f"{'FUNCIONA' if se_fue else 'NO funciona'}; DBT_DEVICEQUERYREMOVE "
                       f"{'llega' if pide else 'no llega'}; aviso de bloqueo (GUID_IO_VOLUME_LOCK) "
                       f"{'llega' if bloqueo else 'no llega'}")
                p.nota("avisos: " + ", ".join(sorted({f"{hex(a[0])}/{a[3]}" for a in avisos})))
            finally:
                m2.cerrar()
                bandeja.dispositivo = None
    finally:
        if P.exists():
            desmontar(forzar=True)
