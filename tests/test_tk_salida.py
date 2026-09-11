#!/usr/bin/env python3
"""
El progreso en la ventana de salida.

sync.py cuenta cómo va cada pareja con una línea de progreso cada pocos segundos
(ver test_progress.py). Aquí se comprueba el otro lado: que la ventana la
reconoce, la pinta con su tono y la reescribe en su sitio en vez de apilar una
por lectura —una línea viva por pareja, que al terminar se queda con la última—.

La ventana se abre con un proceso de verdad que escribe lo que escribiría
sync.py, oculta y colgada de una raíz que tampoco se enseña.
"""

import sys
import time

from _harness import Checks

from common import progress
from ui import tk as uitk

c = Checks("progreso en la ventana de salida")


def linea(texto):
    return f"  {progress.ETIQUETA} {texto}\n"


# --- el tono: sin Tk -----------------------------------------------------------------
c("la línea de progreso tiene su tono", uitk._tono(linea("1,1 MB de 3,4 MB · 32 % · 0 B/s")),
  "progreso")
c("también la de cero", uitk._tono(linea("0 B de 0 B · 0 B/s")), "progreso")
c("y lo demás sigue como estaba",
  [uitk._tono(l) for l in ("=== notas (bisync) ===", "  ejecutando: rclone bisync",
                           "[notas] OK.", "[notas] FALLÓ (código 1). Log: x")],
  ["cabecera", "orden", "ok", "fallo"])

# --- la ventana ----------------------------------------------------------------------
try:
    import tkinter as tk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

SALIDA = [
    "=== notas (bisync) ===\n",
    "  ejecutando: rclone bisync ...\n",
    linea("1,1 MB de 3,4 MB · 32 % · 0 B/s"),
    linea("2,1 MB de 3,4 MB · 61 % · 1,1 MB/s"),
    linea("3,4 MB de 3,4 MB · 100 % · 1,0 MB/s"),
    "[notas] OK.\n",
    "\n",
    "=== fotos (up) ===\n",
    "  ejecutando: rclone copy ...\n",
    linea("10,0 MB de 1,0 GB · 1 % · 5,0 MB/s"),
    linea("0 B de 0 B · 0 B/s"),
    "[fotos] OK.\n",
    "\n",
    "Hecho. 2/2 parejas OK.\n",
]
# Con pausas, para que las líneas lleguen en lecturas distintas de la ventana,
# que es lo que pasa de verdad: una estadística cada pocos segundos.
ESCRIBIR = ("import sys, time\n"
            "for l in sys.argv[1:]:\n"
            "    sys.stdout.write(l); sys.stdout.flush(); time.sleep(0.15)\n")


def recorrer(w):
    pila = [w]
    while pila:
        x = pila.pop()
        yield x
        pila += list(x.winfo_children())


real_deiconify = tk.Toplevel.deiconify
tk.Toplevel.deiconify = lambda self: None               # nada se enseña en un test
try:
    antes = set(raiz.winfo_children())
    uitk.output_window("Prueba", [sys.executable, "-c", ESCRIBIR, *SALIDA],
                       parent=raiz, modal=False)
    ventana = next(w for w in raiz.winfo_children() if w not in antes)
    texto = next(w for w in recorrer(ventana) if isinstance(w, tk.Text))
    vistas = set()
    limite = time.monotonic() + 30
    while time.monotonic() < limite and "Terminado" not in texto.get("1.0", "end"):
        raiz.update()
        vistas.add(sum(1 for l in texto.get("1.0", "end").splitlines()
                       if l.strip().startswith(progress.ETIQUETA)))
        time.sleep(0.03)

    lineas = texto.get("1.0", "end").splitlines()
    en_progreso = [l for l in lineas if l.strip().startswith(progress.ETIQUETA)]
    c("queda una línea de progreso por pareja, la última de cada una", en_progreso,
      [linea("3,4 MB de 3,4 MB · 100 % · 1,0 MB/s").rstrip("\n"),
       linea("0 B de 0 B · 0 B/s").rstrip("\n")])
    c("mientras corría, nunca hubo dos de la misma pareja", max(vistas) <= 2, True)
    c("y en su sitio: entre la orden y el OK de su pareja",
      [lineas[i - 1].strip()[:10] + " | " + lineas[i + 1].strip()
       for i, l in enumerate(lineas) if l.strip().startswith(progress.ETIQUETA)],
      ["ejecutando | [notas] OK.", "ejecutando | [fotos] OK."])
    c("lo demás no se toca", [l for l in lineas if l.strip() and not
                              l.strip().startswith(progress.ETIQUETA)][:4],
      ["=== notas (bisync) ===", "  ejecutando: rclone bisync ...", "[notas] OK.",
       "=== fotos (up) ==="])

    marcadas = texto.tag_ranges("progreso")
    trozos = [texto.get(marcadas[i], marcadas[i + 1]).strip()
              for i in range(0, len(marcadas), 2)]
    c("y con el tono de progreso", trozos, [l.strip() for l in en_progreso])
    c("que la ventana pinta con el acento", str(texto.tag_cget("progreso", "foreground")),
      uitk.theme.ACENTO)
    ventana.destroy()
finally:
    tk.Toplevel.deiconify = real_deiconify

raiz.destroy()
sys.exit(c.report())
