"""F28: el desmontaje automático de VeraCrypt FORZANDO (el de fábrica), con la carpeta vigilada (fila C10)."""

import os
import time

import comun
from common import avisos_carpeta as ac

CODIGO = "F28"
SISTEMA = "W"
QUE = ("VeraCrypt (C10): su desmontaje automático forzando, con la vigilancia puesta: la pareja "
       "se pierde, nada queda abierto y VeraCrypt sigue sano")
K = ("u" * 32, "docs")
MINUTOS = 1
ESPERA = MINUTOS * 60 + 180


def probar(p: comun.Prueba) -> None:
    """Deja que VeraCrypt desmonte forzando: con solo la vigilancia dentro, y con un fichero de otro."""
    if not comun.es_administrador() or os.environ.get("GITHUB_ACTIONS"):
        # En la nube no hay escritorio que entregue el aviso, y forzar con la
        # carpeta abierta deja el controlador sin descargar.
        raise comun.Saltada("solo en un equipo con escritorio y sesión elevada")
    c = comun.Contenedor()
    datos = c.raiz / "datos"
    motor = otro = ventana = None

    def vigilar() -> None:
        """Monta el contenedor y pone la vigilancia."""
        if not c.montar():
            raise comun.Saltada("VeraCrypt no ha montado el contenedor")
        datos.mkdir(exist_ok=True)
        p.ver("  montado, se vigila", motor.vigilar(K, datos, ()), None)
        comun.asentar(motor, 10)

    def anunciados(llegados: list) -> str:
        """Los avisos de volumen que han llegado a la ventana."""
        return ", ".join(sorted({f"{hex(a[0])}/{a[1]}" for a in llegados})) or "ninguno"

    try:
        with comun.bandeja_windows() as (bandeja, llegados):
            ventana = comun.VentanaVeraCrypt(
                c, comun.configuracion_veracrypt(MINUTOS, forzar=True))
            motor = ac.abrir(hwnd=bandeja.hwnd, veracrypt=True)
            bandeja.dispositivo, bandeja.volumen = motor.dispositivo, motor.volumen
            # 1. Solo la vigilancia dentro.
            print(f"  -- desmontaje automático a {MINUTOS} min, forzando", flush=True)
            vigilar()
            if not any(a[0] == comun.DBT_DEVICEARRIVAL for a in llegados):
                raise comun.Saltada("esta máquina no entrega avisos de dispositivo a las ventanas")
            llegados.clear()
            t = time.monotonic()
            if not comun.esperar(lambda: not c.raiz.exists(), ESPERA, 0.5):
                raise comun.Saltada(f"el volumen no se quedó inactivo en {ESPERA} s")
            p.nota(f"forzando, el desmontaje automático llegó a los {time.monotonic() - t:.0f} s; "
                   f"avisos: {anunciados(llegados)}")
            p.ver("forzando y con la vigilancia puesta, se desmonta sin preguntar nada",
                  ventana.preguntas(), [])
            p.ver("  y la pareja se pierde", comun.avisos(motor, 10), {K: ac.PERDIDA})
            p.ver("  sin nada suyo abierto", motor.vigilancias(), 0)
            # 2. Con un fichero abierto por otro programa: VeraCrypt se lo lleva por delante.
            print("  -- lo mismo con un fichero abierto por otro programa", flush=True)
            vigilar()
            otro = comun.ocupar(datos / "abierto.txt")
            comun.asentar(motor, 10)
            llegados.clear()
            t = time.monotonic()
            se_fue = comun.esperar(lambda: not c.raiz.exists(), ESPERA, 0.5)
            p.nota(f"con un fichero abierto por otro, forzando: a los {time.monotonic() - t:.0f} s; "
                   f"avisos: {anunciados(llegados)}")
            p.ver("con un fichero abierto por otro programa, VeraCrypt desmonta igual (fuerza)",
                  se_fue, True)
            p.ver("  sin preguntar nada", ventana.preguntas(), [])
            p.ver("  y la pareja se pierde", comun.avisos(motor, 10).get(K), ac.PERDIDA)
            p.ver("  sin nada suyo abierto", motor.vigilancias(), 0)
            comun.desocupar(otro)
            otro = None
            # 3. Después de forzar, VeraCrypt sigue sano.
            p.ver("después, el contenedor se monta otra vez", c.montar(), True)
            p.ver("  se vigila", motor.vigilar(K, datos, ()), None)
            (datos / "despues.txt").write_text("d", encoding="utf-8")
            p.ver("  se oye", comun.avisos(motor), {K: ac.CAMBIO})
            p.ver("  y se desmonta sin forzar", c.desmontar()[0], True)
    finally:
        if otro is not None:
            otro.kill()
        if motor is not None:
            motor.cerrar()
        c.soltar()
        if ventana is not None and not ventana.cerrar():
            p.nota("la ventana de VeraCrypt no se cerró sola: se la ha matado")
