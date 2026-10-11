"""F18: VeraCrypt de verdad con la carpeta vigilada: avisa dentro, y al desmontar el motor la suelta a tiempo."""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import comun
from common import avisos_carpeta as ac

CODIGO = "F18"
SISTEMA = "W"
QUE = ("VeraCrypt: su volumen se vigila con avisos (avisos_veracrypt) y se desmonta sin forzar "
       "con la vigilancia puesta; cancelado, vuelve sola")
K = ("u" * 32, "docs")
INSTALADO = Path(r"C:\Program Files\VeraCrypt")
CLAVE = "prueba-prdrive-2026"
DBT_DEVICEARRIVAL = 0x8000


def veracrypt() -> tuple[Path, Path]:
    """Devuelve el `VeraCrypt.exe` y el `VeraCrypt Format.exe` que hay en esta máquina.

    El instalado, si lo hay (en la nube, con choco); si no, el Portable que el
    instalador de prdrive ya bajó a este equipo, copiado a la carpeta de
    pruebas para no escribirle nada al lado.

    Raises:
        Saltada: Si no hay ninguno.
    """
    if os.environ.get("GITHUB_ACTIONS") and not (INSTALADO / "VeraCrypt.exe").exists():
        comun.ejecutar(["choco", "install", "veracrypt", "-y", "--no-progress"], timeout=900)
    if (INSTALADO / "VeraCrypt.exe").exists():
        return INSTALADO / "VeraCrypt.exe", INSTALADO / "VeraCrypt Format.exe"
    bajados = Path(os.environ.get("LOCALAPPDATA", "")) / "prdrive-install" / "veracrypt"
    versiones = sorted((d for d in bajados.glob("*") if (d / "VeraCrypt-x64.exe").exists()),
                       key=lambda d: [int(x) for x in d.name.split(".") if x.isdigit()])
    if not versiones:
        raise comun.Saltada("no hay VeraCrypt en esta máquina (ni instalado ni el Portable de "
                            "prdrive)")
    if not comun.es_administrador():
        # Sin elevar, el Portable pide permiso (UAC) para cargar su controlador
        # y la orden se queda esperando a que alguien conteste.
        raise comun.Saltada("el VeraCrypt Portable necesita una sesión elevada")
    copia = comun.TMP / f"veracrypt-{versiones[-1].name}"
    if not (copia / "VeraCrypt-x64.exe").exists():
        shutil.copytree(versiones[-1], copia, dirs_exist_ok=True)
    return copia / "VeraCrypt-x64.exe", copia / "VeraCrypt Format-x64.exe"


def probar(p: comun.Prueba) -> None:
    """Monta un contenedor y lo desmonta con la vigilancia puesta, cancelada y sin ella."""
    vc, formato = veracrypt()
    letra = comun.letra_libre()
    raiz, datos = Path(f"{letra}:\\"), Path(f"{letra}:\\datos")
    hc = comun.carpeta("vc") / "prueba.hc"

    def montar() -> bool:
        """Monta el contenedor como lo monta prdrive (extraíble) y espera a verlo."""
        comun.ejecutar([str(vc), "/volume", str(hc), "/letter", letra, "/password", CLAVE,
                        "/pim", "0", "/mountoption", "rm", "/quit", "/silent"], timeout=120)
        return comun.esperar(raiz.exists, 60)

    def desmontar(forzar: bool = False) -> tuple[bool, float]:
        """Desmonta la letra (sin forzar) y devuelve si se ha ido y lo que tardó la orden."""
        t = time.monotonic()
        comun.ejecutar([str(vc), "/dismount", letra, "/quit", "/silent"]
                       + (["/force"] if forzar else []), timeout=120)
        tardo = time.monotonic() - t
        return comun.esperar(lambda: not raiz.exists(), 5), tardo

    comun.ejecutar([str(formato), "/create", str(hc), "/size", "60M", "/password", CLAVE,
                    "/encryption", "AES", "/hash", "sha512", "/filesystem", "NTFS",
                    "/pim", "0", "/silent", "/force"], timeout=600)
    if not hc.exists():
        raise comun.Saltada("VeraCrypt no ha creado el contenedor")
    api = ac.Win32()
    motor = otro = None
    try:
        with comun.bandeja_windows() as (bandeja, llegados):
            if not montar():
                raise comun.Saltada("VeraCrypt no ha montado el contenedor (¿su controlador?)")
            dispositivo = api.dispositivo_de(f"{letra}:")
            p.nota(f"{vc.name}: dispositivo de {letra}: {dispositivo}")
            p.ver("su volumen se reconoce como de VeraCrypt",
                  dispositivo.startswith(ac.DISPOSITIVOS_VERACRYPT), True)
            datos.mkdir(exist_ok=True)
            sin_ajuste = ac.ReadDirectoryChanges(api, bandeja.hwnd)
            try:
                p.ver("sin el ajuste no se vigila con avisos",
                      sin_ajuste.vigilar(K, datos, ()), ac.MOTIVO_VERACRYPT)
            finally:
                sin_ajuste.cerrar()
            motor = ac.abrir(hwnd=bandeja.hwnd, veracrypt=True)
            bandeja.dispositivo, bandeja.volumen = motor.dispositivo, motor.volumen
            p.ver("con el ajuste se vigila", motor.vigilar(K, datos, ()), None)
            (datos / "nuevo.txt").write_text("n", encoding="utf-8")
            p.ver("  avisa de un fichero nuevo", comun.avisos(motor), {K: ac.CAMBIO})
            p.ver("  y quieta no avisa de nada", comun.quieto(motor, 3.0), {})
            if not any(a[0] == DBT_DEVICEARRIVAL for a in llegados):
                p.saltados.append("los desmontajes: esta máquina no entrega avisos de dispositivo "
                                  "a las ventanas (sin escritorio interactivo)")
                return
            # 1. Con la vigilancia puesta, sin forzar.
            llegados.clear()
            se_fue, tardo = desmontar()
            p.ver("con la vigilancia puesta, desmontar sin forzar funciona", se_fue, True)
            p.nota(f"desmontar con la vigilancia puesta: {tardo:.2f} s; avisos a la ventana: "
                   + ", ".join(sorted({f"{hex(a[0])}/{a[1]}" for a in llegados})))
            p.ver("  y la pareja se pierde", comun.avisos(motor, 10), {K: ac.PERDIDA})
            p.ver("  sin nada suyo abierto", motor.vigilancias(), 0)
            # 2. Otro programa tiene un fichero abierto: no se desmonta, y la vigilancia vuelve.
            if not montar():
                raise comun.Saltada("VeraCrypt no ha vuelto a montar el contenedor")
            p.ver("montado otra vez, se vigila", motor.vigilar(K, datos, ()), None)
            otro = subprocess.Popen(
                [sys.executable, "-c", "import sys; f = open(sys.argv[1], 'w'); print('ya', "
                 "flush=True); sys.stdin.read()", str(datos / "abierto.txt")],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            otro.stdout.readline()
            comun.avisos(motor, 3)
            se_fue, tardo = desmontar()
            p.ver("con un fichero abierto por otro programa no se desmonta", se_fue, False)
            p.ver("  la carpeta se soltó al anunciarse", motor.vigilancias(), 0)
            p.ver("  y pasado el plazo la vigilancia vuelve sola",
                  comun.esperar(lambda: motor.vigilancias() == 1, ac.REABRIR_VERACRYPT + 5), True)
            p.ver("  contando como un cambio", comun.avisos(motor, 3), {K: ac.CAMBIO})
            otro.stdin.close()
            otro.wait(10)
            otro = None
            comun.quieto(motor, 2.0)
            (datos / "despues.txt").write_text("d", encoding="utf-8")
            p.ver("  y oye lo de después", comun.avisos(motor), {K: ac.CAMBIO})
            # 3. Sin soltarla (nadie atiende el aviso): es el agente el que estorbaría.
            bandeja.volumen = None
            se_fue, tardo = desmontar()
            p.ver("sin atender el aviso, la carpeta abierta impide desmontar", se_fue, False)
            p.nota(f"sin atender el aviso VeraCrypt se rinde a los {tardo:.2f} s")
            bandeja.volumen = motor.volumen
            se_fue, tardo = desmontar()
            p.ver("y atendiéndolo otra vez, se va", se_fue, True)
            p.ver("  y la pareja se pierde", comun.avisos(motor, 10), {K: ac.PERDIDA})
    finally:
        if otro is not None:
            otro.kill()
        if motor is not None:
            motor.cerrar()
        if raiz.exists() and not desmontar()[0] and os.environ.get("GITHUB_ACTIONS"):
            # Forzar deja el controlador portable sin descargar: solo en una
            # máquina de usar y tirar.
            desmontar(forzar=True)
