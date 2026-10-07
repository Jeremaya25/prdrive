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
            import ctypes
            h = api.abrir_carpeta(str(P / "datos"))
            try:
                aviso = api.registrar(bandeja.hwnd, h)
                error = ctypes.get_last_error()
                p.nota(f"PREGUNTA 2: registrar el aviso de extracción de un handle de su volumen "
                       + ("SE PUEDE" if aviso else f"NO se puede (error {error})"))
                if aviso:
                    api.desregistrar(aviso)
                se_fue = desmontar(forzar=False)
                p.nota(f"con un handle abierto dentro, desmontar sin forzar "
                       f"{'FUNCIONA' if se_fue else 'NO funciona'}; avisos a la ventana: "
                       + (", ".join(sorted({f"{hex(a[0])}/{a[3]}" for a in avisos})) or "ninguno"))
            finally:
                api.cerrar(h)
            if not P.exists():
                montar(hc)
            p.ver("sin nada abierto dentro, desmontar sin forzar funciona",
                  desmontar(forzar=False), True)
    finally:
        if P.exists():
            desmontar(forzar=True)
