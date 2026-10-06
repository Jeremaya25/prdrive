"""F16: «Expulsar» de la bandeja: tras dejar las vigilancias (lo que hace el agente) la unidad se suelta."""

from pathlib import Path

import comun
from common import avisos_carpeta as ac
from common import expulsar

CODIGO = "F16"
SISTEMA = "W"
QUE = "«Expulsar» del agente (expulsar.expulsar) con la vigilancia puesta: sin dejarla falla; dejándola, sale"
U = "u" * 32
K = (U, "docs")


def probar(p: comun.Prueba) -> None:
    """Expulsa sin soltar el handle (control) y soltándolo (lo que hace el agente)."""
    with comun.bandeja_windows() as (bandeja, avisos):
        with comun.volumen_windows("ntfs", "R") as raiz:
            (raiz / "datos").mkdir()
            motor = ac.abrir(hwnd=bandeja.hwnd)
            bandeja.dispositivo = motor.dispositivo
            try:
                p.ver("se vigila", motor.vigilar(K, raiz / "datos", ()), None)
                control = expulsar.expulsar(Path("R:\\"))
                p.nota(f"sin soltar el handle: ok={control.ok} ({control.texto}); avisos: "
                       + ", ".join(sorted({f"{hex(a[0])}/{a[3]}" for a in avisos})))
                if not control.ok:
                    motor.dejar_raiz(U)
                    r = expulsar.expulsar(Path("R:\\"))
                    p.ver("tras dejar las vigilancias de la raíz, «Expulsar» sale bien", r.ok, True)
                    p.ver("  y nada vuelve a abrirla", motor.vigilancias(), 0)
                else:
                    p.nota("la expulsión no necesitó soltar el handle (el bloqueo lo cerró)")
            finally:
                motor.cerrar()
                bandeja.dispositivo = None
