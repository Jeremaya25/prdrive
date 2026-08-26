#!/usr/bin/env python3
"""
El asistente de instalación, conducido sin nadie delante.

No se comprueba el aspecto: se comprueba el cableado, y sobre todo las condiciones
que impiden avanzar. Ese es el valor del asistente —que no te deje llegar al paso
destructivo sin haber pasado por los anteriores—, así que es lo que hay que
probar:

  * «Siguiente» no se enciende hasta que el paso está resuelto.
  * «Sembrar de verdad» no se enciende sin haber simulado antes, y si el destino
    tiene cosas ajenas, tampoco hasta escribir la ruta a mano.
  * El paso de parejas escribe de verdad el sync_config.toml.

Se conduce el armazón de verdad (`tk_install.build`), no una copia. Las ventanas
se crean ocultas y no se entra nunca en el bucle de eventos; ni rclone ni
VeraCrypt llegan a ejecutarse, porque lo que los lanzaría está sustituido.
"""

import sys
from pathlib import Path

from _harness import Checks, tmpdir

c = Checks("instalador: el asistente (cableado)")

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(0)

from install import remote                               # noqa: E402
from ui import tk_install                                # noqa: E402

messagebox.showinfo = lambda *a, **k: None
messagebox.showerror = lambda *a, **k: None
messagebox.showwarning = lambda *a, **k: None
messagebox.askokcancel = lambda *a, **k: True

CATALOGO = """\
[defaults]
remote = "synology"

[[pair]]
name = "perepen"
local = "."
remote_path = "/PJ/Perepen"
mode = "up-mirror"

[[pair]]
name = "obsidian"
local = "sync-data/obsidian"
remote_path = "/PJ/Obsidian"
mode = "bisync"
"""

# Nada de esto debe ejecutarse: si se ejecutara, el test lanzaría rclone.
lanzadas = []
tk_install.output_window = lambda titulo, cmd, parent=None: (
    lanzadas.append((titulo, cmd)) or 0)


def widgets(w, tipo):
    pila, salida = [w], []
    while pila:
        actual = pila.pop()
        pila += list(actual.winfo_children())
        if isinstance(actual, tipo):
            salida.append(actual)
    return salida


def boton(w, texto):
    for b in widgets(w, ttk.Button):
        if b.cget("text") == texto:
            return b
    return None


def nuevo_asistente(pen_root=None, selected=()):
    """Un asistente con las comprobaciones ya dadas por buenas."""
    root = tk.Toplevel(raiz)
    root.withdraw()
    wiz = tk_install.build(root)
    wiz.catalog = remote.parse_catalog(CATALOGO)
    wiz.rclone = remote.Rclone("RCLONE", "CONF")
    wiz.state.device = pen_root
    wiz.state.pen_root = pen_root
    wiz.state.selected = list(selected)
    return wiz


def en_paso(wiz, indice):
    wiz.indice = indice
    wiz.repintar()


# --- todos los pasos se pintan -----------------------------------------------
pen = tmpdir()
wiz = nuevo_asistente(pen)
for i, (titulo, _, _) in enumerate(tk_install.PASOS):
    try:
        en_paso(wiz, i)
        c(f"el paso «{titulo}» se pinta", True, True)
    except Exception as e:
        c(f"el paso «{titulo}» se pinta", f"{type(e).__name__}: {e}", True)

c("la cabecera dice por dónde va",
  wiz.cabecera.cget("text").startswith("Paso 7 de 7"), True)
c("en el último paso el botón cambia de nombre",
  wiz.boton_siguiente.cget("text"), "Terminar")
en_paso(wiz, 0)
c("y en el primero no se puede ir atrás", str(wiz.boton_atras.cget("state")), "disabled")

# --- las condiciones de cada paso --------------------------------------------
vacio = nuevo_asistente()
vacio.catalog = None
vacio.rclone = None
en_paso(vacio, 0)
c("sin catálogo no se sale de las comprobaciones",
  str(vacio.boton_siguiente.cget("state")), "disabled")

vacio.catalog = remote.parse_catalog(CATALOGO)
vacio.rclone = remote.Rclone("RCLONE", "CONF")
vacio.revisar()
c("con catálogo sí", str(vacio.boton_siguiente.cget("state")), "normal")

en_paso(vacio, 1)
c("sin destino no se sale del paso de destino",
  str(vacio.boton_siguiente.cget("state")), "disabled")

en_paso(vacio, 2)
c("sin saber dónde va la estructura no se sale del cifrado",
  str(vacio.boton_siguiente.cget("state")), "disabled")
boton(vacio.cuerpo, "Entendido, usar el pen tal cual")   # opción «sin cifrar»
vacio.state.device = pen
en_paso(vacio, 2)
boton(vacio.cuerpo, "Entendido, usar el pen tal cual").invoke()
c("elegir «sin cifrar» deja el destino listo", vacio.state.pen_root, pen)
c("y ya se puede seguir", str(vacio.boton_siguiente.cget("state")), "normal")

# --- el paso de la siembra, que es el destructivo ----------------------------
limpio = tmpdir()
wiz = nuevo_asistente(limpio)
en_paso(wiz, 3)
c("sin sembrar no se sale del paso de siembra",
  str(wiz.boton_siguiente.cget("state")), "disabled")
c("y «Sembrar de verdad» empieza apagado",
  str(boton(wiz.cuerpo, "Sembrar de verdad").cget("state")), "disabled")

boton(wiz.cuerpo, "Simular (--dry-run)").invoke()
c("simular lanza rclone con --dry-run", "--dry-run" in lanzadas[-1][1], True)
c("la simulación no marca el pen como sembrado", wiz.state.seeded, False)
c("pero enciende el botón de sembrar",
  str(boton(wiz.cuerpo, "Sembrar de verdad").cget("state")), "normal")

boton(wiz.cuerpo, "Sembrar de verdad").invoke()
c("sembrar de verdad va sin --dry-run", "--dry-run" in lanzadas[-1][1], False)
c("y marca el pen como sembrado", wiz.state.seeded, True)
c("ya se puede seguir", str(wiz.boton_siguiente.cget("state")), "normal")
# El PEREPEN sembrado traería el id del pen de origen: hay que renovarlo.
from install import device                                # noqa: E402
c("y el pen recibe un identificador propio",
  len(device.control_id(limpio) or ""), 32)

# Un destino con cosas ajenas: el botón sigue apagado aunque se haya simulado.
ajeno = tmpdir()
(ajeno / "TFM-sin-copia").mkdir()
otro = nuevo_asistente(ajeno)
en_paso(otro, 3)
boton(otro.cuerpo, "Simular (--dry-run)").invoke()
c("con un destino ajeno no basta con simular",
  str(boton(otro.cuerpo, "Sembrar de verdad").cget("state")), "disabled")

entrada = widgets(otro.cuerpo, ttk.Entry)[0]
entrada.insert(0, str(ajeno))
c("hay que escribir la ruta para desbloquearlo",
  str(boton(otro.cuerpo, "Sembrar de verdad").cget("state")), "normal")

# --- el paso de parejas escribe el config ------------------------------------
wiz = nuevo_asistente(limpio)
en_paso(wiz, 4)
c("sin config escrito no se sale del paso de parejas",
  str(wiz.boton_siguiente.cget("state")), "disabled")

boton(wiz.cuerpo, "Guardar el config y crear las carpetas").invoke()
config = limpio / "rclone-sync" / "sync_config.toml"
c("se escribe el sync_config.toml", config.is_file(), True)
c("con las parejas marcadas", sorted(wiz.state.selected), ["obsidian", "perepen"])
c("se crean sus carpetas locales", (limpio / "sync-data" / "obsidian").is_dir(), True)
c("y ya se puede seguir", str(wiz.boton_siguiente.cget("state")), "normal")

# --- la inicialización no toca los espejos -----------------------------------
lanzadas.clear()
(limpio / "rclone-sync" / "sync.py").write_text("#\n", encoding="utf-8")
en_paso(wiz, 5)
boton(wiz.cuerpo, "Inicializar ahora").invoke()
orden = lanzadas[-1][1]
c("se inicializa la pareja bisync", "obsidian" in orden, True)
# 'perepen' es un up-mirror del pen ENTERO al NAS: aquí no se toca.
c("y NUNCA el espejo del pen entero", "perepen" in orden, False)
c("con --resync", "--resync" in orden, True)

sys.exit(c.report())
