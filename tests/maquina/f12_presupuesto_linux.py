"""F12: con max_user_watches de verdad, el agente se queda con la mitad y deja el resto."""

import ctypes
import os
from pathlib import Path

import comun
from common import avisos_carpeta as ac

CODIGO = "F12"
SISTEMA = "L"
QUE = "fs.inotify.max_user_watches de verdad: el agente no pasa de la mitad y otro programa cabe"
LIMITE = Path("/proc/sys/fs/inotify/max_user_watches")
K = ("u" * 32, "docs")


def probar(p: comun.Prueba) -> None:
    """Baja el límite, prueba y lo deja como estaba."""
    antes = LIMITE.read_text(encoding="ascii").strip()
    try:
        LIMITE.write_text("20000\n", encoding="ascii")
    except OSError as e:
        raise comun.Saltada(f"no se puede cambiar max_user_watches: {e}")
    try:
        grande = comun.arbol(comun.carpeta("grande"), 10100)
        motor = ac.abrir()
        try:
            motivo = motor.vigilar(K, grande, ())
            p.ver("una pareja de 10 100 carpetas no cabe en la mitad: se dice por qué",
                  "max_user_watches" in (motivo or ""), True)
            p.ver("  sin dejar nada puesto", motor.vigilancias(), 0)
            mediana = comun.arbol(comun.carpeta("mediana"), 3000)
            p.ver("una de 3 000 sí", motor.vigilar(K, mediana, ()), None)
            otra = comun.arbol(comun.carpeta("editor"), 9000)
            libc = ctypes.CDLL(None, use_errno=True)
            fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
            puestas = 0
            for d in [otra, *otra.rglob("d*")]:
                if libc.inotify_add_watch(fd, os.fsencode(str(d)), 0x100) >= 0:
                    puestas += 1
            os.close(fd)
            p.ver("otro programa (un editor) pone 9 000 vigilancias más", puestas, 9001)
        finally:
            motor.cerrar()
    finally:
        LIMITE.write_text(antes + "\n", encoding="ascii")
