#!/usr/bin/env python3
"""La hora de creación de un proceso (`store.creado()`), con procesos de verdad.

El registro del vigilante del llavero apunta su pid, y un pid reutilizado en el
mismo arranque pasa por vivo: lo que distingue al vigilante de otra Python que
tomó su número es la hora en que cada uno se creó (`llavero.es_el_vigilante()`,
#158). Windows la da `GetProcessTimes` (un FILETIME); Linux, el campo 22 de
`/proc/<pid>/stat` y el `btime` de `/proc/stat`.

Se prueba en los dos sistemas contra un hijo de verdad, y la aritmética que no
depende del sistema (el FILETIME, el campo 22 de un `stat` con un nombre raro)
con valores conocidos, para que también se vea en el otro.
"""

import os
import subprocess
import sys
import threading
import time

from _harness import Checks

from common import llavero, store

c = Checks("hora de creación de un proceso (store.creado)")

HIJO = ("import time\n"
        "print(time.time(), flush=True)\n"
        "time.sleep(60)\n")
"""Un Python que dice la hora en que ya está en marcha y espera a que lo maten."""
TOPE = 30.0  # segundos que se da a un hijo antes de matarlo
SEPARACION = 1.5  # segundos entre un hijo y el siguiente


def lanzar():
    """Lanza un hijo y devuelve `(proceso, hora antes de lanzarlo, hora que dice al arrancar)`."""
    antes = time.time()
    proceso = subprocess.Popen([sys.executable, "-c", HIJO], stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, text=True)
    guardia = threading.Timer(TOPE, proceso.kill)
    guardia.daemon = True
    guardia.start()
    return proceso, antes, float(proceso.stdout.readline())


def linea_stat(nombre: str, ticks: int) -> bytes:
    """Un `/proc/<pid>/stat` con ese nombre de programa y ese `starttime` (campo 22)."""
    intermedios = " ".join(str(n) for n in range(4, 22))          # campos 4 a 21
    return f"42 ({nombre}) S {intermedios} {ticks} 1000 2000\n".encode()


hijos = []
try:
    # un hijo de verdad
    uno, antes, dicho = lanzar()
    hijos.append(uno)
    creado = store.creado(uno.pid)
    c("un hijo vivo tiene hora de creación", isinstance(creado, float), True)
    c("  no es anterior a justo antes de lanzarlo (en Linux `btime` recorta hasta 1 s)",
      creado >= antes - 2.0, True)
    c("  ni posterior a cuando el propio hijo dice que ya corre (la época es la de `time.time()`)",
      creado <= dicho + 0.05, True)
    c("  y se creó hace poco, no en otra época (FILETIME de 1601, ticks sin sumar el arranque)",
      dicho - creado < 10.0, True)
    c("  la misma en cada lectura: es lo que el registro compara", store.creado(uno.pid), creado)
    c("  y la del propio proceso no es posterior a la de su hijo",
      store.creado(os.getpid()) <= creado, True)

    # dos hijos, separados: la hora los distingue
    started = store.stamp()
    time.sleep(SEPARACION)
    dos, _, _ = lanzar()
    hijos.append(dos)
    separados = store.creado(dos.pid) - creado
    c("dos hijos lanzados con 1,5 s de diferencia se distinguen por su hora",
      SEPARACION - 0.5 <= separados <= SEPARACION + 2.0, True)

    # lo que el llavero hace con ella, con hijos de verdad
    c("el registro de un vigilante (con su `creado`) reconoce a su proceso",
      llavero._creado_como_el_registro(uno.pid, {"creado": creado}), True)
    c("  y no al otro, que tomara su pid: se creó 1,5 s después",
      llavero._creado_como_el_registro(dos.pid, {"creado": creado}), False)
    c("sin `creado`, el proceso creado antes de `started` es el del registro",
      llavero._creado_como_el_registro(uno.pid, {"started": started}), True)
    c("  y uno creado mucho después de `started` no",
      llavero._creado_como_el_registro(
          uno.pid, {"started": time.strftime(store.FORMATO, time.localtime(time.time() - 3600))}),
      False)

    # lo que no se puede mirar
    c("un pid imposible no tiene hora",
      (store.creado(0), store.creado(-1), store.creado(store.PID_MAXIMO)), (None, None, None))
    if os.name == "nt":
        print("  (saltado) solo en POSIX: en Windows el objeto de un proceso muerto sigue "
              "abriéndose mientras alguien tenga su handle (el `Popen` que lo lanzó)")
    else:
        dos.kill()
        dos.wait()
        c("un proceso que ya no existe no tiene hora", store.creado(dos.pid), None)
finally:
    for hijo in hijos:
        hijo.kill()
        hijo.wait()
        hijo.stdout.close()

# La conversión de un FILETIME (dos DWORD, intervalos de 100 ns desde 1601-01-01 UTC) a época
# Unix, con fechas conocidas: la hace Windows, pero la cuenta se comprueba en cualquier sitio.
for etiqueta, filetime, epoca in (
        ("el origen de la época Unix", 116444736000000000, 0.0),
        ("el 1 de enero de 2000", 125911584000000000, 946684800.0),
        ("con décimas de segundo", 125911584000000000 + 5_000_000, 946684800.5)):
    c(f"FILETIME: {etiqueta}",
      store._epoca_de_filetime(filetime >> 32, filetime & 0xFFFFFFFF), epoca)

# El campo 22 de un `/proc/<pid>/stat`: el nombre del programa va entre paréntesis y puede
# llevar espacios y paréntesis, así que se cuenta desde el último.
for etiqueta, nombre in (("un nombre corriente", "python3"),
                         ("con espacios", "mi programa"),
                         ("con paréntesis y espacios", "(a b) c) d")):
    c(f"campo 22 del stat, {etiqueta}", store._inicio_en_ticks(linea_stat(nombre, 987654)), 987654)
try:
    store._inicio_en_ticks(b"esto no es un stat")
    rechazado = False
except ValueError:
    rechazado = True
c("  y lo que no es un stat se rechaza", rechazado, True)

sys.exit(c.report())
