#!/usr/bin/env python3
"""El progreso en la ventana de salida.

`sync.py` cuenta cómo va cada pareja con una línea de progreso cada pocos
segundos (ver `test_progress.py`). Aquí se comprueba el otro lado: que la
ventana la reconoce, la pinta con su tono y la reescribe en su sitio en vez de
apilar una por lectura: una línea viva por pareja, que al terminar se queda con
la última.

La ventana se abre con un proceso de verdad que escribe lo que escribiría
`sync.py`, oculta y colgada de una raíz que tampoco se enseña.

Las líneas llegan en tandas (`_volcar`: un `insert` y un `see` por vuelta del
sondeo): lo que se comprueba es que meterlas así no cambia nada de lo que se
ve (el tono de cada una, el progreso reescrito en su sitio aunque caiga dentro
de una tanda o entre dos), que el texto se queda con las últimas 20 000 y que
«Guardar el log» lleva la salida entera.
"""

import random
import sys
import tempfile
import time
from pathlib import Path

from _harness import Checks

from common import progress
from ui import tk as uitk

c = Checks("progreso en la ventana de salida")


def linea(texto):
    """Devuelve una línea de progreso con ese texto."""
    return f"  {progress.ETIQUETA} {texto}\n"


# el tono: sin Tk
c("la línea de progreso tiene su tono", uitk._tono(linea("1,1 MB de 3,4 MB · 32 % · 0 B/s")),
  "progreso")
c("también la de cero", uitk._tono(linea("0 B de 0 B · 0 B/s")), "progreso")
c("y lo demás sigue como estaba",
  [uitk._tono(l) for l in ("=== notas (bisync) ===", "  ejecutando: rclone bisync",
                           "[notas] OK.", "[notas] FALLÓ (código 1). Log: x")],
  ["cabecera", "orden", "ok", "fallo"])



def referencia(lineas):
    """La salida que debe quedar: el progreso seguido se reduce a la última.

    Es el cálculo más simple posible y no usa `_tono` ni `_Salida`: con él se
    comparan los dos.
    """
    salida: list[str] = []
    for l in lineas:
        es_progreso = l.strip().startswith(progress.ETIQUETA)
        if es_progreso and salida and salida[-1].strip().startswith(progress.ETIQUETA):
            salida[-1] = l
        else:
            salida.append(l)
    return salida


def flujo(grupos: int = 250) -> list[str]:
    """Una pasada larga: 96 ficheros, tres lecturas de progreso seguidas y el OK, por grupo.

    Son 25 000 líneas con 750 de progreso, y en tandas de cualquier tamaño las
    tres de cada grupo caen muchas veces partidas entre dos.
    """
    salida: list[str] = []
    for g in range(grupos):
        salida += [f"  [p{g}] fichero-{i}.txt  (100 KiB)\n" for i in range(96)]
        salida += [linea(f"{k} MB de 9 MB · {33 * k} % · 1,0 MB/s") for k in (1, 2, 3)]
        salida.append(f"[p{g}] OK.\n")
    return salida


# la tanda, sin Tk
tanda = uitk._Salida()
sustituye, trozos = tanda.anadir([
    "=== notas (bisync) ===\n", "  ejecutando: rclone bisync ...\n",
    linea("1,1 MB de 3,4 MB · 32 %"), linea("2,1 MB de 3,4 MB · 61 %"),
    "  uno.txt\n", "  dos.txt\n", "[notas] OK.\n"])
c("una tanda: el progreso seguido se reduce a la última, en su sitio",
  (sustituye, trozos),
  (False, [("=== notas (bisync) ===\n", "cabecera"),
           ("  ejecutando: rclone bisync ...\n", "orden"),
           (linea("2,1 MB de 3,4 MB · 61 %"), "progreso"),
           ("  uno.txt\n  dos.txt\n", "normal"),
           ("[notas] OK.\n", "ok")]))
c("  y la copia entera, igual", tanda.completa, referencia([
    "=== notas (bisync) ===\n", "  ejecutando: rclone bisync ...\n",
    linea("2,1 MB de 3,4 MB · 61 %"), "  uno.txt\n", "  dos.txt\n", "[notas] OK.\n"]))
c("  sin línea viva al acabar en otra cosa", tanda.viva, False)

tanda = uitk._Salida()
tanda.anadir(["  ejecutando: rclone copy\n", linea("1 MB de 9 MB")])
c("acabar en progreso deja la línea viva", tanda.viva, True)
sustituye, trozos = tanda.anadir([linea("2 MB de 9 MB"), linea("3 MB de 9 MB"),
                                  "[fotos] OK.\n"])
c("la tanda siguiente sustituye la viva del texto, y solo deja la última",
  (sustituye, trozos),
  (True, [(linea("3 MB de 9 MB"), "progreso"), ("[fotos] OK.\n", "ok")]))
c("  la copia entera tiene una sola, la última", tanda.completa,
  ["  ejecutando: rclone copy\n", linea("3 MB de 9 MB"), "[fotos] OK.\n"])

tanda = uitk._Salida()
tanda.anadir([linea("1 MB de 9 MB")])
sustituye, trozos = tanda.anadir(["  otro.txt\n", linea("2 MB de 9 MB")])
c("si la tanda siguiente empieza por otra cosa, la viva se queda como estaba",
  (sustituye, tanda.completa),
  (False, [linea("1 MB de 9 MB"), "  otro.txt\n", linea("2 MB de 9 MB")]))

tanda = uitk._Salida()
t0 = time.perf_counter()
tanda.anadir(["  fichero-%d.txt  (100 KiB)\n" % i for i in range(25000)])
c("25 000 líneas del mismo tono se juntan en un trozo, y no cuestan nada",
  (len(tanda.completa), time.perf_counter() - t0 < 2.0), (25000, True))

# la ventana
try:
    import tkinter as tk
    from tkinter import filedialog, ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

TONOS = ("normal", "cabecera", "orden", "ok", "aviso", "fallo", "progreso")


def caja():
    """Devuelve un `tk.Text` como el de la ventana: desactivado y con sus tonos."""
    texto = tk.Text(raiz, wrap="char", width=104, height=28, state="disabled")
    for nombre in TONOS:
        texto.tag_configure(nombre)
    return texto


def lineas_de(texto) -> list[str]:
    """Las líneas que tiene el texto, cada una con su salto."""
    return texto.get("1.0", "end-1c").splitlines(keepends=True)


def tonos_de(texto) -> dict[str, str]:
    """Lo que cubre cada tono en el texto, de punta a punta."""
    salida = {}
    for nombre in TONOS:
        rangos = texto.tag_ranges(nombre)
        salida[nombre] = "".join(str(texto.get(rangos[i], rangos[i + 1]))
                                 for i in range(0, len(rangos), 2))
    return salida


class Cuenta:
    """Un `tk.Text` que cuenta las llamadas que se le hacen, por nombre."""

    def __init__(self, texto) -> None:
        """Envuelve el texto."""
        self.texto, self.llamadas = texto, {}

    def __getattr__(self, nombre):
        """Devuelve el método del texto, apuntando cada llamada."""
        metodo = getattr(self.texto, nombre)

        def llamar(*a, **k):
            """Apunta la llamada y la hace."""
            self.llamadas[nombre] = self.llamadas.get(nombre, 0) + 1
            return metodo(*a, **k)
        return llamar


# 25 000 líneas con progreso en medio de las tandas
completo = flujo()
c("el flujo de prueba tiene 25 000 líneas y 750 de progreso",
  (len(completo), sum(1 for l in completo if l.strip().startswith(progress.ETIQUETA))),
  (25000, 750))
esperado = referencia(completo)
visibles = esperado[-uitk.LINEAS_VENTANA:]
texto = caja()
salida = uitk._Salida()
cuenta = Cuenta(texto)
tamanos = [97, 1, 150, 333, 2000, 1, 7, 1000]      # el 97 parte el primer progreso
n_tandas, i = 0, 0
while i < len(completo):
    n = tamanos[n_tandas % len(tamanos)]
    uitk._volcar(cuenta, salida, completo[i:i + n])
    n_tandas, i = n_tandas + 1, i + n
c("en tandas: la copia entera es la salida con el progreso reducido",
  salida.completa == esperado, True)
c("  son 24 500 líneas (750 de progreso pasan a 250)", len(salida.completa), 24500)
c("  el texto se queda con las últimas 20 000, exactas",
  lineas_de(texto) == visibles, True)
c("  y con nada más: 20 000 líneas", len(lineas_de(texto)), 20000)
c("  un `insert` y un `see` por tanda, no por línea",
  (cuenta.llamadas["insert"], cuenta.llamadas["see"], n_tandas),
  (n_tandas, n_tandas, n_tandas))
c("  el texto sigue desactivado", str(texto.cget("state")), "disabled")
esperado_tonos = {nombre: "".join(l for l in visibles if uitk._tono(l) == nombre)
                  for nombre in TONOS}
c("  cada línea con su tono", tonos_de(texto), esperado_tonos)
c("  ninguna de progreso pegada a otra",
  any(a.strip().startswith(progress.ETIQUETA) and b.strip().startswith(progress.ETIQUETA)
      for a, b in zip(lineas_de(texto), lineas_de(texto)[1:])), False)

# la línea viva, a los dos lados de una tanda
texto = caja()
salida = uitk._Salida()
uitk._volcar(texto, salida, ["  ejecutando: rclone\n", linea("1 MB de 9 MB")])
c("la viva queda marcada al principio de su línea",
  texto.get("progreso-vivo", "end-1c"), linea("1 MB de 9 MB"))
uitk._volcar(texto, salida, [linea("2 MB de 9 MB"), linea("3 MB de 9 MB")])
c("la tanda siguiente la reescribe: una sola, la última",
  lineas_de(texto), ["  ejecutando: rclone\n", linea("3 MB de 9 MB")])
c("  y la marca sigue al principio de ella",
  texto.get("progreso-vivo", "end-1c"), linea("3 MB de 9 MB"))
uitk._volcar(texto, salida, ["[p] OK.\n", "\n", linea("1 MB de 4 MB")])
c("otra pareja abre otra línea viva, y la de antes se queda",
  (lineas_de(texto)[1:], texto.get("progreso-vivo", "end-1c")),
  ([linea("3 MB de 9 MB"), "[p] OK.\n", "\n", linea("1 MB de 4 MB")],
   linea("1 MB de 4 MB")))

# una línea de progreso sin salto de línea (la última de una salida cortada)
texto = caja()
salida = uitk._Salida()
uitk._volcar(texto, salida, ["  uno.txt\n", linea("1 MB de 9 MB").rstrip("\n")])
c("sin salto de línea al final, la marca también está al principio de su línea",
  texto.get("progreso-vivo", "end-1c"), linea("1 MB de 9 MB").rstrip("\n"))
uitk._volcar(texto, salida, [linea("2 MB de 9 MB")])
c("  y la siguiente la reescribe", lineas_de(texto),
  ["  uno.txt\n", linea("2 MB de 9 MB")])

# el tope, con uno pequeño para no escribir 20 000 líneas por cada caso
tope_real = uitk.LINEAS_VENTANA
uitk.LINEAS_VENTANA = 100
try:
    texto = caja()
    salida = uitk._Salida()
    todas = [f"  l{i}\n" for i in range(250)]
    for i in range(0, 250, 30):
        uitk._volcar(texto, salida, todas[i:i + 30])
    c("el tope: cien líneas, las últimas", lineas_de(texto), todas[-100:])
    c("  y la copia entera, todas", salida.completa, todas)
    texto = caja()
    salida = uitk._Salida()
    uitk._volcar(texto, salida, todas)
    c("  una sola tanda mayor que el tope también", lineas_de(texto), todas[-100:])
finally:
    uitk.LINEAS_VENTANA = tope_real

# el tiempo: 10 000 líneas, en tandas como las de un sondeo (era 4,8 s)
texto = caja()
salida = uitk._Salida()
diez_mil = [f"  [pareja] transferido fichero-{i}.txt  (100 KiB)\n" for i in range(10000)]
t0 = time.perf_counter()
for i in range(0, 10000, 240):
    uitk._volcar(texto, salida, diez_mil[i:i + 240])
    raiz.update_idletasks()
c("10 000 líneas en tandas de 240 caben en un par de segundos",
  time.perf_counter() - t0 < 2.0, True)

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
# El hijo hace lo mismo que `sync.py` antes de escribir nada (`preparar_salida`):
# UTF-8 por la tubería. Las líneas de progreso llevan un · en medio, y sin esto
# salían en cp1252 mientras la ventana ya lee UTF-8 — que es el fallo que se
# acaba de arreglar, pero del revés.
ESCRIBIR = ("import sys, time\n"
            "sys.stdout.reconfigure(encoding='utf-8')\n"
            "for l in sys.argv[1:]:\n"
            "    sys.stdout.write(l); sys.stdout.flush(); time.sleep(0.15)\n")


def recorrer(w):
    """Recorre los widgets que cuelgan de `w`, en profundidad."""
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

    # una pasada larga de verdad: la ventana, el proceso y «Guardar el log»
    hijo = ("import sys\n"
            "sys.stdout.reconfigure(encoding='utf-8')\n"
            "for g in range(250):\n"
            "    for i in range(96):\n"
            "        sys.stdout.write(f'  [p{g}] fichero-{i}.txt  (100 KiB)\\n')\n"
            "    for k in (1, 2, 3):\n"
            "        sys.stdout.write(f'  {sys.argv[1]} {k} MB de 9 MB · {33 * k} % · 1,0 MB/s\\n')\n"
            "    sys.stdout.write(f'[p{g}] OK.\\n')\n")
    antes = set(raiz.winfo_children())
    uitk.output_window("Larga", [sys.executable, "-c", hijo, progress.ETIQUETA],
                       parent=raiz, modal=False)
    ventana = next(w for w in raiz.winfo_children() if w not in antes)
    texto = next(w for w in recorrer(ventana) if isinstance(w, tk.Text))
    limite = time.monotonic() + 60
    while time.monotonic() < limite and "Terminado" not in texto.get("end-3l", "end"):
        raiz.update()
        time.sleep(0.03)
    esperado = referencia(flujo()) + ["\n=== Terminado: OK ===\n"]
    c("la ventana termina la pasada larga", "Terminado: OK" in texto.get("end-3l", "end"), True)
    c("  el texto tiene las últimas 20 000 líneas, con el final",
      lineas_de(texto) == "".join(esperado).splitlines(keepends=True)[-uitk.LINEAS_VENTANA:],
      True)
    with tempfile.TemporaryDirectory() as carpeta:
        destino = str(Path(carpeta) / "log.txt")
        real_guardar = filedialog.asksaveasfilename
        filedialog.asksaveasfilename = lambda **k: destino
        try:
            next(w for w in recorrer(ventana) if isinstance(w, ttk.Button)
                 and str(w.cget("text")) == "Guardar el log").invoke()
        finally:
            filedialog.asksaveasfilename = real_guardar
        guardado = Path(destino).read_text(encoding="utf-8")
    c("«Guardar el log» lleva la salida entera, no las 20 000 de la ventana",
      guardado == "".join(esperado), True)
    c("  son 24 502 líneas, con una sola de progreso por pareja",
      (len(guardado.splitlines()), sum(1 for l in guardado.splitlines()
                                       if l.strip().startswith(progress.ETIQUETA))),
      (24502, 250))
    ventana.destroy()

    # un código que quien llama no da por error
    #
    # El aplicador de componentes sale con 3 cuando lo ha dejado todo listo
    # para el relevo, y la ventana decía «ERROR (código 3)» justo en el caso
    # bueno.
    def terminar(rc, veredictos):
        """Abre la ventana con un proceso que sale con `rc` y devuelve la ventana."""
        antes = set(raiz.winfo_children())
        uitk.output_window("Prueba", [sys.executable, "-c", f"raise SystemExit({rc})"],
                           parent=raiz, modal=False, veredictos=veredictos)
        ventana = next(w for w in raiz.winfo_children() if w not in antes)
        texto = next(w for w in recorrer(ventana) if isinstance(w, tk.Text))
        limite = time.monotonic() + 30
        while time.monotonic() < limite and "Terminado" not in texto.get("1.0", "end"):
            raiz.update()
            time.sleep(0.03)
        final = texto.get("1.0", "end").strip().splitlines()[-1]
        ventana.destroy()
        return final

    c("un código con veredicto dice el suyo, no ERROR",
      terminar(3, {3: "OK, falta cerrar la ventana"}),
      "=== Terminado: OK, falta cerrar la ventana ===")
    c("sin veredicto, el mismo código sigue siendo un error",
      terminar(3, None), "=== Terminado: ERROR (código 3) ===")
    c("y el veredicto de uno no tapa otro",
      terminar(1, {3: "OK, falta cerrar la ventana"}), "=== Terminado: ERROR (código 1) ===")
finally:
    tk.Toplevel.deiconify = real_deiconify

raiz.destroy()
sys.exit(c.report())
