"""F23: la ventana de VeraCrypt y su desmontaje automático, con la carpeta vigilada (fila C10)."""

import subprocess
import time

import comun
from common import avisos_carpeta as ac

CODIGO = "F23"
SISTEMA = "W"
QUE = ("VeraCrypt (C10): «Unmount All» de su ventana y su desmontaje automático por inactividad, "
       "sin forzar, con la vigilancia puesta")
K = ("u" * 32, "docs")
BOTONES = ("unmount all", "dismount all")
"""El botón de desmontar todo: «Unmount All» desde la 1.26.2x, antes «Dismount All»."""
MINUTOS = 1
CONFIGURACION = (
    '<?xml version="1.0" encoding="utf-8"?>\n<VeraCrypt>\n\t<configuration>\n'
    f'\t\t<config key="MaxVolumeIdleTime">{MINUTOS}</config>\n'
    '\t\t<config key="ForceAutoDismount">0</config>\n'
    '\t</configuration>\n</VeraCrypt>\n')
"""Desmontar a los `MINUTOS` de inactividad y SIN forzar (de fábrica VeraCrypt fuerza)."""
BM_CLICK, WM_CLOSE = 0x00F5, 0x0010


def probar(p: comun.Prueba) -> None:
    """Abre la ventana de VeraCrypt y deja que desmonte ella: con su botón y por inactividad."""
    c = comun.Contenedor()
    if not c.portable:
        raise comun.Saltada("solo con el Portable: no se toca la configuración de un VeraCrypt "
                            "instalado")
    (c.vc.parent / "Configuration.xml").write_text(CONFIGURACION, encoding="utf-8")
    datos = c.raiz / "datos"
    motor = otro = ventana = None
    principal = 0

    def preguntas() -> list[str]:
        """Los títulos de las ventanas de VeraCrypt que no son la principal (una pregunta, un error)."""
        return [t or "(sin título)" for h, t, _hijos in comun.ventanas_de(ventana.pid)
                if h != principal]

    def vigilar() -> None:
        """Monta el contenedor y pone la vigilancia."""
        if not c.montar():
            raise comun.Saltada("VeraCrypt no ha montado el contenedor")
        datos.mkdir(exist_ok=True)
        p.ver("  montado, se vigila", motor.vigilar(K, datos, ()), None)
        comun.asentar(motor, 10)

    try:
        with comun.bandeja_windows() as (bandeja, llegados):
            ventana = subprocess.Popen([str(c.vc)])
            boton = 0

            def hay_boton() -> bool:
                """Busca la ventana principal por su botón de desmontar todo."""
                nonlocal principal, boton
                for h, _t, hijos in comun.ventanas_de(ventana.pid):
                    for hh, texto in hijos:
                        if texto.lower() in BOTONES:
                            principal, boton = h, hh
                            return True
                return False

            if not comun.esperar(hay_boton, 30, 0.5):
                raise comun.Saltada("la ventana de VeraCrypt no se ha abierto, o no en inglés")
            motor = ac.abrir(hwnd=bandeja.hwnd, veracrypt=True)
            bandeja.dispositivo, bandeja.volumen = motor.dispositivo, motor.volumen
            # 1. El botón de su ventana.
            print("  -- «Unmount All» de su ventana", flush=True)
            vigilar()
            if not any(a[0] == comun.DBT_DEVICEARRIVAL for a in llegados):
                raise comun.Saltada("esta máquina no entrega avisos de dispositivo a las ventanas "
                                    "(sin escritorio interactivo)")
            llegados.clear()
            comun.mandar(boton, BM_CLICK)
            p.ver("con la vigilancia puesta, su botón desmonta",
                  comun.esperar(lambda: not c.raiz.exists(), 15), True)
            p.ver("  sin preguntar si forzar", preguntas(), [])
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
                p.ver("  sin preguntar nada", preguntas(), [])
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
                p.ver("  sin preguntar nada", preguntas(), [])
                p.ver("  la vigilancia ha vuelto sola", motor.vigilancias(), 1)
                p.ver("  contando como un cambio", comun.avisos(motor, 3), {K: ac.CAMBIO})
                comun.desocupar(otro)
                otro = None
                # VeraCrypt no reintenta enseguida: vuelve a contar la inactividad.
                t = time.monotonic()
                p.ver("  suelto el fichero, el intento siguiente lo desmonta",
                      comun.esperar(lambda: not c.raiz.exists(), MINUTOS * 60 + 180, 0.5), True)
                p.nota(f"el intento siguiente llegó a los {time.monotonic() - t:.0f} s")
                p.ver("  y la pareja se pierde", comun.avisos(motor, 10).get(K), ac.PERDIDA)
            else:
                p.saltados.append("el desmontaje automático con un fichero abierto: no llegó a "
                                  "intentarse")
    finally:
        if otro is not None:
            otro.kill()
        if motor is not None:
            motor.cerrar()
        c.soltar()
        if ventana is not None:
            # Cerrada por las buenas y sin volúmenes, el Portable descarga su controlador.
            if principal:
                comun.mandar(principal, WM_CLOSE)
            try:
                ventana.wait(20)
            except subprocess.TimeoutExpired:
                p.nota("la ventana de VeraCrypt no se cerró sola: se la ha matado")
                ventana.kill()
