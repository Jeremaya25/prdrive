"""F27: los temporales que nacen y mueren en la carpeta vigilada no dejan nada que sincronizar (fila C6)."""

import shutil
import time

import comun
from common import avisos_carpeta as ac

CODIGO = "F27"
SISTEMA = "W"
QUE = ("temporales de editor, el .~lock de LibreOffice y un `git status` en la carpeta vigilada: "
       "al final no queda cambio; un guardado de verdad, sí (C6)")
K = ("u" * 32, "docs")
NADA = (None, ac.RETIRADO)


def probar(p: comun.Prueba) -> None:
    """Hace lo que hacen un editor y git, y mira lo último que dice el motor."""
    with comun.bandeja_windows() as (bandeja, _llegados), comun.volumen_windows("ntfs") as raiz:
        datos = raiz / "datos"
        datos.mkdir()
        (datos / "doc.odt").write_text("documento", encoding="utf-8")
        motor = ac.abrir(hwnd=bandeja.hwnd)
        bandeja.dispositivo = motor.dispositivo

        def pasada() -> None:
            """Lo que deja una pasada de la pareja: nada pendiente."""
            comun.asentar(motor, 10)
            motor.descartar(K)
            time.sleep(ac.CALLAR_TRAS_DESCARTE + 0.5)
            motor.recoger()

        try:
            p.ver("se vigila", motor.vigilar(K, datos, ()), None)
            (datos / "~tmp4f2.tmp").write_text("t", encoding="utf-8")
            time.sleep(0.3)
            (datos / "~tmp4f2.tmp").unlink()
            p.ver("un temporal que nace y muere no deja cambio",
                  comun.al_final(motor).get(K) in NADA, True)
            candado = datos / ".~lock.doc.odt#"
            candado.write_text("usuario", encoding="utf-8")
            abierto = comun.al_final(motor, 3).get(K)
            candado.unlink()
            p.ver("abrir y cerrar un documento sin guardar (su .~lock) tampoco",
                  comun.al_final(motor).get(K) in NADA, True)
            p.nota(f"mientras el documento está abierto el motor dice «{abierto}»: si dura más "
                   f"que la calma, cuesta una pasada")
            git = shutil.which("git")
            if git is None:
                p.saltados.append("git status: no hay git en esta máquina")
            else:
                orden = [git, "-c", "safe.directory=*", "-c", "user.name=prueba", "-c",
                         "user.email=prueba@example.invalid", "-C", str(datos)]
                for paso in (["init", "-q"], ["add", "doc.odt"], ["commit", "-q", "-m", "uno"]):
                    comun.ejecutar(orden + paso, timeout=60)
                p.ver("crear un repositorio dentro es un cambio",
                      comun.avisos(motor).get(K) in (ac.CAMBIO, ac.DESBORDADO), True)
                pasada()
                comun.ejecutar(orden + ["status", "--short"], timeout=60)
                dice = comun.al_final(motor).get(K)
                p.nota(f"tras un `git status` el motor dice «{dice}»")
                p.ver("un `git status` no deja cambio", dice in NADA, True)
            pasada()
            (datos / "doc.odt").write_text("documento guardado", encoding="utf-8")
            p.ver("guardar el documento de verdad sí es un cambio",
                  comun.al_final(motor), {K: ac.CAMBIO})
        finally:
            motor.cerrar()
            bandeja.dispositivo = None
