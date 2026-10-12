"""F26: 20 000 ficheros copiados a la carpeta vigilada, y uno reescrito sin parar: lo que le cuesta al motor (fila C5)."""

import subprocess
import sys
import time

import comun
from common import avisos_carpeta as ac

CODIGO = "F26"
SISTEMA = "W"
QUE = ("una ráfaga de 20 000 ficheros y un fichero reescrito sin parar en la carpeta vigilada: "
       "una lectura por segundo como mucho y casi nada de procesador (C5)")
K = ("u" * 32, "docs")
FICHEROS = 20000
SEGUNDOS = 15
CREAR = ("import os, sys\nd = sys.argv[1]\nos.makedirs(d)\n"
         "for i in range(int(sys.argv[2])):\n"
         "    with open(os.path.join(d, f'f{i}.txt'), 'w') as f:\n        f.write('x')\n")
REESCRIBIR = ("import sys, time\nfin = time.monotonic() + float(sys.argv[2])\nn = 0\n"
              "while time.monotonic() < fin:\n"
              "    with open(sys.argv[1], 'w') as f:\n        f.write(str(n))\n    n += 1\n"
              "print(n)\n")


class Contada(ac.Win32):
    """Las llamadas a Windows de verdad, contando las lecturas que se lanzan."""

    lecturas = 0

    def leer_cambios(self, *args) -> None:
        """Cuenta la lectura y la lanza."""
        Contada.lecturas += 1
        super().leer_cambios(*args)


def medir(orden: list[str]) -> tuple[float, float, int, str]:
    """Corre otro programa y devuelve lo que duró y lo que gastó ESTE proceso: procesador y lecturas."""
    antes, cpu, t = Contada.lecturas, time.process_time(), time.monotonic()
    r = subprocess.run(orden, capture_output=True, text=True, timeout=900)
    return (time.monotonic() - t, time.process_time() - cpu, Contada.lecturas - antes,
            r.stdout.strip())


def probar(p: comun.Prueba) -> None:
    """Mide el motor mientras otro programa llena la carpeta y mientras reescribe un fichero."""
    with comun.bandeja_windows() as (bandeja, _llegados), \
            comun.volumen_windows("ntfs", mb=512) as raiz:
        datos = raiz / "datos"
        datos.mkdir()
        motor = ac.ReadDirectoryChanges(Contada(), bandeja.hwnd)
        bandeja.dispositivo = motor.dispositivo
        try:
            p.ver("se vigila", motor.vigilar(K, datos, ()), None)
            dur, cpu, lecturas, _ = medir([sys.executable, "-c", CREAR, str(datos / "copia"),
                                           str(FICHEROS)])
            p.nota(f"{FICHEROS} ficheros en {dur:.1f} s: {lecturas} lecturas y {cpu * 1000:.0f} ms "
                   f"de procesador del motor ({cpu / dur:.1%})")
            p.ver("la ráfaga cuesta una lectura por segundo como mucho",
                  lecturas <= dur / ac.AGRUPAR + 3, True)
            p.ver("  y menos de un 2 % de un procesador", cpu / dur < 0.02, True)
            p.ver("  y avisa (cambio o desbordado)",
                  comun.avisos(motor).get(K) in (ac.CAMBIO, ac.DESBORDADO), True)
            comun.asentar(motor)
            p.ver("  y luego, quieta, nada", comun.quieto(motor, 3.0), {})
            dur, cpu, lecturas, veces = medir([sys.executable, "-c", REESCRIBIR,
                                               str(datos / "vivo.txt"), str(SEGUNDOS)])
            p.nota(f"un fichero reescrito {veces} veces en {dur:.1f} s: {lecturas} lecturas y "
                   f"{cpu * 1000:.0f} ms de procesador del motor ({cpu / dur:.1%})")
            p.ver("reescribir un fichero sin parar cuesta una lectura por segundo como mucho",
                  lecturas <= dur / ac.AGRUPAR + 3, True)
            p.ver("  y menos de un 2 % de un procesador", cpu / dur < 0.02, True)
            # En un disco rápido el búfer de un segundo se llena: desbordado, que también cuenta.
            p.ver("  y avisa (cambio o desbordado)",
                  comun.avisos(motor).get(K) in (ac.CAMBIO, ac.DESBORDADO), True)
        finally:
            motor.cerrar()
            bandeja.dispositivo = None
