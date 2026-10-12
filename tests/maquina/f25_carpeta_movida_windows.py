"""F25: renombrar la carpeta vigilada y poner otra con su nombre; y la de encima, que Windows no deja (fila C7)."""

import os

import comun
from common import avisos_carpeta as ac

CODIGO = "F25"
SISTEMA = "W"
QUE = ("renombrar la carpeta vigilada y crear otra con su nombre: se nota y se vuelve a oír la "
       "nueva; la de encima no se deja renombrar (C7)")
K = ("u" * 32, "docs")


def probar(p: comun.Prueba) -> None:
    """Mueve la carpeta vigilada y prueba a renombrar la de encima."""
    with comun.bandeja_windows() as (bandeja, _llegados), comun.volumen_windows("ntfs") as raiz:
        arriba, datos = raiz / "arriba", raiz / "arriba" / "datos"
        datos.mkdir(parents=True)
        motor = ac.abrir(hwnd=bandeja.hwnd)
        bandeja.dispositivo = motor.dispositivo
        try:
            p.ver("se vigila", motor.vigilar(K, datos, ()), None)
            try:
                os.rename(arriba, raiz / "arriba2")
                os.rename(raiz / "arriba2", arriba)
                dejo = True
            except OSError as e:
                dejo = False
                p.nota(f"renombrar la carpeta de encima: {type(e).__name__} (winerror "
                       f"{getattr(e, 'winerror', '?')})")
            p.ver("con la vigilancia puesta Windows no deja renombrar la carpeta de encima",
                  dejo, False)
            os.rename(datos, arriba / "vieja")
            datos.mkdir()
            (datos / "nuevo.txt").write_text("n", encoding="utf-8")
            p.nota(f"tras renombrarla y crear otra con su nombre, el motor dice: "
                   f"{comun.al_final(motor, 3) or 'nada'}")
            # Lo que hace el agente al acabar la pasada siguiente de la pareja.
            motor.descartar(K)
            aviso = motor.recoger().get(K) or ac.Aviso("")
            p.ver("al acabar su pasada siguiente se nota que la han movido: la pareja se pierde",
                  aviso.tipo, ac.PERDIDA)
            p.ver("  con su motivo", aviso.motivo, ac.MOTIVO_SE_FUE)
            p.ver("  sin nada suyo abierto", motor.vigilancias(), 0)
            p.ver("la carpeta nueva se vigila", motor.vigilar(K, datos, ()), None)
            (datos / "otro.txt").write_text("o", encoding="utf-8")
            p.ver("  y se oye", comun.avisos(motor), {K: ac.CAMBIO})
            comun.asentar(motor, 10)
            (arriba / "vieja" / "viejo.txt").write_text("v", encoding="utf-8")
            p.ver("  y la vieja ya no", comun.quieto(motor, 3.0), {})
            motor.dejar(K)
            os.rename(arriba, raiz / "arriba2")
            p.ver("sin la vigilancia, la de encima se renombra", (raiz / "arriba2").is_dir(), True)
        finally:
            motor.cerrar()
            bandeja.dispositivo = None
