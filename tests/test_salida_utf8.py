#!/usr/bin/env python3
"""
Lo que se escribe en castellano llega entero al otro lado de la tubería.

Todo lo que sale de `sync.py` está en castellano, y casi nunca lo lee una
consola: lo recoge `runsync.run_pair_quiet` para el diario del servicio, o la
ventana de salida mientras corre. Hacia una tubería Python codifica con la del
sistema —cp1252 en Windows— y el que lee esperaba UTF-8, así que las tildes
llegaban descompuestas. Esto recorre esa tubería de verdad: un hijo que escribe
como escribe sync.py, y un padre que lee como leen los dos que leen.
"""

import subprocess
import sys
from pathlib import Path

from _harness import Checks

c = Checks("salida en UTF-8 por la tubería")

RAIZ = Path(__file__).resolve().parent.parent

# Las que de verdad se imprimen: el AVISO de conflictos, los ConfigError, el
# «FALLÓ» que colorea la ventana, y el guion largo de los estados del doctor.
TEXTO = "configuración — [obsidian] FALLÓ. Sincronización con tildes: áéíóúñÁÉÍÓÚÑ «»"

HIJO = (
    "import sys; sys.path.insert(0, %r); "
    "import sync; sync.preparar_salida(); "
    "print(%r); print(%r, file=sys.stderr)" % (str(RAIZ), TEXTO, TEXTO)
)


def leer(**kwargs):
    """Lanza el hijo y devuelve lo que el padre ve, con los ajustes que se le den."""
    return subprocess.run([sys.executable, "-c", HIJO], capture_output=True, **kwargs)


# --- tal y como lo capturan runsync.run_pair_quiet y la ventana de salida -------
proc = leer(text=True, encoding="utf-8", errors="replace")
c("stdout llega entero", proc.stdout.strip(), TEXTO)
c("stderr llega entero", proc.stderr.strip(), TEXTO)
c("sin caracteres de reemplazo", "�" in proc.stdout + proc.stderr, False)

# --- y en bytes, que es lo que acaba en el fichero -----------------------------
crudo = leer()
c("lo que sale son bytes UTF-8", crudo.stdout.strip(), TEXTO.encode("utf-8"))
c("y stderr también", crudo.stderr.strip(), TEXTO.encode("utf-8"))

# --- los dos extremos de cada tubería dicen UTF-8 -------------------------------
# El arreglo son dos mitades y las dos tienen que estar: si el hijo escribe UTF-8
# y el padre decodifica con la del sistema, se rompe igual.
for fichero, quien in (("runsync.py", "el servicio"), ("ui/tk.py", "la ventana de salida")):
    texto = (RAIZ / fichero).read_text(encoding="utf-8")
    trozo = texto[texto.index("subprocess."):]
    c(f"{quien} lee UTF-8 explícito",
      'encoding="utf-8"' in trozo[:trozo.index(")\n")], True)

sys.exit(c.report())
