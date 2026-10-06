"""F15: «Expulsar» del Explorador con la carpeta vigilada abierta: se cierra a tiempo, y vuelve si no se extrae."""

import subprocess

import comun
from common import avisos_carpeta as ac

CODIGO = "F15"
SISTEMA = "W"
QUE = "expulsar el disco desde el Explorador con la vigilancia puesta: no «en uso»; vetada, vuelve sola"
K = ("u" * 32, "docs")


def expulsar_explorador(letra: str) -> None:
    """Lo que hace la persona: «Expulsar» del menú de la unidad en el Explorador."""
    comun.ejecutar(["powershell", "-NoProfile", "-Command",
                    f"(New-Object -ComObject Shell.Application).Namespace(17)"
                    f".ParseName('{letra}:').InvokeVerb('Eject')"], timeout=60)


def probar(p: comun.Prueba) -> None:
    """Expulsa con la vigilancia puesta; luego con un fichero abierto por otro."""
    with comun.bandeja_windows() as (bandeja, avisos):
        with comun.volumen_windows("ntfs", "R") as raiz:
            (raiz / "datos").mkdir()
            motor = ac.abrir(hwnd=bandeja.hwnd)
            bandeja.dispositivo = motor.dispositivo
            try:
                p.ver("se vigila", motor.vigilar(K, raiz / "datos", ()), None)
                h = next(iter(motor._activas.values())).handle
                expulsar_explorador("R")
                se_fue = comun.esperar(lambda: not raiz.exists(), 30)
                p.nota("avisos a la ventana: " + ", ".join(sorted({hex(a[0]) for a in avisos})))
                p.ver("Windows pide la unidad al handle (DBT_DEVICEQUERYREMOVE)",
                      any(a[0] == ac.DBT_DEVICEQUERYREMOVE and a[2] == h for a in avisos), True)
                p.ver("y la expulsión sigue adelante: el volumen se va", se_fue, True)
                p.ver("la pareja se pierde", comun.avisos(motor, 10), {K: ac.PERDIDA})
            finally:
                motor.cerrar()
        avisos.clear()
        with comun.volumen_windows("ntfs", "R") as raiz:
            (raiz / "datos").mkdir()
            motor = ac.abrir(hwnd=bandeja.hwnd)
            bandeja.dispositivo = motor.dispositivo
            abierto = (raiz / "datos" / "abierto.txt").open("w", encoding="utf-8")
            try:
                motor.vigilar(K, raiz / "datos", ())
                expulsar_explorador("R")
                se_fue = comun.esperar(lambda: not raiz.exists(), 15)
                p.ver("con un fichero abierto por otro programa no se extrae", se_fue, False)
                p.ver("  el sistema lo dice (DBT_DEVICEQUERYREMOVEFAILED)",
                      any(a[0] == ac.DBT_DEVICEQUERYREMOVEFAILED for a in avisos), True)
                p.ver("  y la vigilancia vuelve sola", comun.esperar(
                    lambda: motor.vigilancias() == 1, 10), True)
                abierto.close()
                (raiz / "datos" / "despues.txt").write_text("d", encoding="utf-8")
                p.ver("  y oye lo de después", comun.avisos(motor), {K: ac.CAMBIO})
            finally:
                if not abierto.closed:
                    abierto.close()
                motor.cerrar()
                bandeja.dispositivo = None
