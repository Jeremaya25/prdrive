"""F23: la ventana de VeraCrypt y su desmontaje automático, con la carpeta vigilada (fila C10)."""

import time

import comun
from common import avisos_carpeta as ac

CODIGO = "F23"
SISTEMA = "W"
QUE = ("VeraCrypt (C10): «Unmount All» de su ventana y su desmontaje automático por inactividad, "
       "sin forzar, con la vigilancia puesta")
K = ("u" * 32, "docs")
MINUTOS = 1
"""A cuántos minutos de inactividad desmonta; SIN forzar (de fábrica VeraCrypt fuerza: F28)."""


def probar(p: comun.Prueba) -> None:
    """Abre la ventana de VeraCrypt y deja que desmonte ella: con su botón y por inactividad."""
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

    try:
        with comun.bandeja_windows() as (bandeja, llegados):
            ventana = comun.VentanaVeraCrypt(
                c, comun.configuracion_veracrypt(MINUTOS, forzar=False))
            motor = ac.abrir(hwnd=bandeja.hwnd, veracrypt=True)
            bandeja.dispositivo, bandeja.volumen = motor.dispositivo, motor.volumen
            # 1. El botón de su ventana.
            print("  -- «Unmount All» de su ventana", flush=True)
            vigilar()
            if not any(a[0] == comun.DBT_DEVICEARRIVAL for a in llegados):
                raise comun.Saltada("esta máquina no entrega avisos de dispositivo a las ventanas "
                                    "(sin escritorio interactivo)")
            llegados.clear()
            ventana.desmontar_todo()
            p.ver("con la vigilancia puesta, su botón desmonta",
                  comun.esperar(lambda: not c.raiz.exists(), 15), True)
            p.ver("  sin preguntar si forzar", ventana.preguntas(), [])
            p.ver("  y la pareja se pierde", comun.avisos(motor, 10), {K: ac.PERDIDA})
            p.nota("su botón avisa a la ventana con "
                   + ", ".join(sorted({f"{hex(a[0])}/{a[1]}" for a in llegados})))
            # 2. Por inactividad, sin forzar.
            print(f"  -- desmontaje automático a {MINUTOS} min, sin forzar", flush=True)
            vigilar()
            t = time.monotonic()
            if comun.esperar(lambda: not c.raiz.exists(), MINUTOS * 60 + 180, 0.5):
                p.nota(f"el desmontaje automático llegó a los {time.monotonic() - t:.0f} s")
                p.ver("con la vigilancia puesta, el desmontaje automático sin forzar desmonta",
                      True, True)
                p.ver("  sin preguntar nada", ventana.preguntas(), [])
                p.ver("  y la pareja se pierde", comun.avisos(motor, 10), {K: ac.PERDIDA})
            else:
                p.saltados.append("el desmontaje automático: el volumen no se quedó inactivo en "
                                  f"{MINUTOS * 60 + 180} s")
                c.desmontar()
                comun.avisos(motor, 10)
            # 3. Por inactividad con un fichero abierto por otro: qué hace VeraCrypt, y el motor.
            print("  -- desmontaje automático con un fichero abierto por otro programa", flush=True)
            vigilar()
            otro = comun.ocupar(datos / "abierto.txt")
            comun.asentar(motor, 10)
            llegados.clear()
            if comun.esperar(lambda: any(a[0] == ac.DBT_DEVICEREMOVEPENDING for a in llegados),
                             MINUTOS * 60 + 180, 0.2):
                abiertas = []
                fin = time.monotonic() + 12
                while time.monotonic() < fin:
                    abiertas.append(motor.vigilancias())
                    time.sleep(0.5)
                anuncios = sum(1 for a in llegados if a[0] == ac.DBT_DEVICEREMOVEPENDING)
                p.nota(f"con un fichero abierto por otro, VeraCrypt anuncia el desmontaje "
                       f"{anuncios} veces en 12 s; la carpeta estuvo abierta en "
                       f"{sum(abiertas)} de {len(abiertas)} miradas")
                p.ver("  y no se desmonta (no fuerza)", c.raiz.exists(), True)
                p.ver("  sin preguntar nada", ventana.preguntas(), [])
                p.ver("  la vigilancia ha vuelto sola", motor.vigilancias(), 1)
                p.ver("  contando como un cambio", comun.avisos(motor, 3), {K: ac.CAMBIO})
                comun.desocupar(otro)
                otro = None
                # VeraCrypt no reintenta enseguida: vuelve a contar la inactividad,
                # y cuándo la da por inactiva no depende de esta prueba.
                t = time.monotonic()
                if comun.esperar(lambda: not c.raiz.exists(), MINUTOS * 60 + 180, 0.5):
                    p.nota(f"suelto el fichero, el intento siguiente lo desmonta a los "
                           f"{time.monotonic() - t:.0f} s")
                    p.ver("  suelto el fichero, el intento siguiente lo desmonta y la pareja "
                          "se pierde", comun.avisos(motor, 10).get(K), ac.PERDIDA)
                else:
                    p.saltados.append("el intento siguiente tras soltar el fichero: el volumen "
                                      f"no se quedó inactivo en {MINUTOS * 60 + 180} s")
            else:
                p.saltados.append("el desmontaje automático con un fichero abierto: no llegó a "
                                  "intentarse")
    finally:
        if otro is not None:
            otro.kill()
        if motor is not None:
            motor.cerrar()
        c.soltar()
        if ventana is not None and not ventana.cerrar():
            p.nota("la ventana de VeraCrypt no se cerró sola: se la ha matado")
