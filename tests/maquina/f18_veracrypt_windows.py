"""F18: VeraCrypt de verdad con la carpeta vigilada: avisa dentro, y al desmontar el motor la suelta a tiempo."""

import comun
from common import avisos_carpeta as ac

CODIGO = "F18"
SISTEMA = "W"
QUE = ("VeraCrypt: su volumen se vigila con avisos (avisos_veracrypt) y se desmonta sin forzar "
       "con la vigilancia puesta; cancelado, vuelve sola")
K = ("u" * 32, "docs")


def probar(p: comun.Prueba) -> None:
    """Monta un contenedor y lo desmonta con la vigilancia puesta, cancelada y sin ella."""
    c = comun.Contenedor()
    datos = c.raiz / "datos"
    api = ac.Win32()
    motor = otro = None
    try:
        with comun.bandeja_windows() as (bandeja, llegados):
            if not c.montar():
                raise comun.Saltada("VeraCrypt no ha montado el contenedor (¿su controlador?)")
            dispositivo = api.dispositivo_de(f"{c.letra}:")
            p.nota(f"{c.vc.name}: dispositivo de {c.letra}: {dispositivo}")
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
            comun.asentar(motor, 10)
            p.ver("  y quieta no avisa de nada", comun.quieto(motor, 3.0), {})
            if not any(a[0] == comun.DBT_DEVICEARRIVAL for a in llegados):
                p.saltados.append("los desmontajes: esta máquina no entrega avisos de dispositivo "
                                  "a las ventanas (sin escritorio interactivo)")
                return
            # 1. Con la vigilancia puesta, sin forzar.
            llegados.clear()
            se_fue, tardo = c.desmontar()
            p.ver("con la vigilancia puesta, desmontar sin forzar funciona", se_fue, True)
            p.nota(f"desmontar con la vigilancia puesta: {tardo:.2f} s; avisos a la ventana: "
                   + ", ".join(sorted({f"{hex(a[0])}/{a[1]}" for a in llegados})))
            p.ver("  y la pareja se pierde", comun.avisos(motor, 10), {K: ac.PERDIDA})
            p.ver("  sin nada suyo abierto", motor.vigilancias(), 0)
            # 2. Otro programa tiene un fichero abierto: no se desmonta, y la vigilancia vuelve.
            if not c.montar():
                raise comun.Saltada("VeraCrypt no ha vuelto a montar el contenedor")
            p.ver("montado otra vez, se vigila", motor.vigilar(K, datos, ()), None)
            otro = comun.ocupar(datos / "abierto.txt")
            comun.avisos(motor, 3)
            se_fue, tardo = c.desmontar()
            p.ver("con un fichero abierto por otro programa no se desmonta", se_fue, False)
            p.ver("  la carpeta se soltó al anunciarse", motor.vigilancias(), 0)
            p.ver("  y pasado el plazo la vigilancia vuelve sola",
                  comun.esperar(lambda: motor.vigilancias() == 1, ac.REABRIR_VERACRYPT + 5), True)
            p.ver("  contando como un cambio", comun.avisos(motor, 3), {K: ac.CAMBIO})
            comun.desocupar(otro)
            otro = None
            comun.quieto(motor, 2.0)
            (datos / "despues.txt").write_text("d", encoding="utf-8")
            p.ver("  y oye lo de después", comun.avisos(motor), {K: ac.CAMBIO})
            # 3. Sin soltarla (nadie atiende el aviso): es el agente el que estorbaría.
            bandeja.volumen = None
            se_fue, tardo = c.desmontar()
            p.ver("sin atender el aviso, la carpeta abierta impide desmontar", se_fue, False)
            p.nota(f"sin atender el aviso VeraCrypt se rinde a los {tardo:.2f} s")
            bandeja.volumen = motor.volumen
            # 4. Como lo pide `Expulsar PRDRIVE.bat`: sin /silent, para que
            # VeraCrypt pregunte si forzar; con la carpeta suelta no pregunta.
            se_fue, tardo = c.desmontar(callado=False)
            p.ver("y atendiéndolo, como lo pide «Expulsar PRDRIVE.bat» (sin /silent), se va sin "
                  "preguntar", se_fue, True)
            p.ver("  y la pareja se pierde", comun.avisos(motor, 10), {K: ac.PERDIDA})
    finally:
        if otro is not None:
            otro.kill()
        if motor is not None:
            motor.cerrar()
        c.soltar()
