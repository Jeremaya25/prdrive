#!/usr/bin/env python3
"""
El asistente de instalación, conducido sin nadie delante.

No se comprueba el aspecto: se comprueba el cableado, y sobre todo las condiciones
que impiden avanzar. Ese es el valor del asistente —que no te deje llegar a un
paso sin haber resuelto los anteriores—, así que es lo que hay que probar:

  * «Siguiente» no se enciende hasta que el paso está resuelto, empezando por el
    primero: sin conexión configurada no se va a ninguna parte.
  * El paso de instalación deja de verdad el programa en el dispositivo, y con un
    destino ajeno no se enciende hasta escribir la ruta a mano.
  * El paso de parejas escribe de verdad el sync_config.toml.
  * La inicialización no toca los espejos.

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

from install import profile, remote                      # noqa: E402
from ui import tk_install                                # noqa: E402

messagebox.showinfo = lambda *a, **k: None
messagebox.showerror = lambda *a, **k: None
messagebox.showwarning = lambda *a, **k: None
messagebox.askokcancel = lambda *a, **k: True

CATALOGO = """\
[defaults]
remote = "nas"

[[pair]]
name = "respaldo"
local = "."
remote_path = "/respaldo"
mode = "up-mirror"

[[pair]]
name = "docs"
local = "sync-data/docs"
remote_path = "/datos/docs"
mode = "bisync"
"""

PERFIL = profile.from_form("nas", {"type": "sftp", "host": "nas.example"})

# Nada de esto debe ejecutarse: si se ejecutara, el test lanzaría rclone.
lanzadas = []
tk_install.output_window = lambda titulo, cmd, parent=None: (
    lanzadas.append((titulo, cmd)) or 0)

# `working()` corre su función en un hilo y abre una barra de progreso, que sin
# bucle de eventos se quedaría colgada. Se sustituye por la ejecución directa,
# que es lo que interesa comprobar: el trabajo se hace de verdad.
tk_install.working = lambda parent, titulo, funcion, mensaje="": (True, funcion())

# Un rclone de mentira: el paso de instalación lo copia, no lo ejecuta.
RCLONE_FALSO = tmpdir() / "rclone-de-mentira"
RCLONE_FALSO.write_bytes(b"MZ")


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


def nuevo_asistente(device_root=None, selected=()):
    """Un asistente con la conexión y las comprobaciones ya dadas por buenas."""
    root = tk.Toplevel(raiz)
    root.withdraw()
    wiz = tk_install.build(root)
    wiz.perfil = PERFIL
    wiz.catalog = remote.parse_catalog(CATALOGO)
    wiz.rclone = remote.Rclone("RCLONE", "CONF", remote_name="nas")
    wiz.binario = str(RCLONE_FALSO)
    wiz.state.device = device_root
    wiz.state.device_root = device_root
    wiz.state.selected = list(selected)
    return wiz


def en_paso(wiz, indice):
    wiz.indice = indice
    wiz.repintar()


PASO = {titulo: i for i, (titulo, _, _) in enumerate(tk_install.PASOS)}

# --- todos los pasos se pintan -----------------------------------------------
dispositivo = tmpdir()
wiz = nuevo_asistente(dispositivo)
for i, (titulo, _, _) in enumerate(tk_install.PASOS):
    try:
        en_paso(wiz, i)
        c(f"el paso «{titulo}» se pinta", True, True)
    except Exception as e:
        c(f"el paso «{titulo}» se pinta", f"{type(e).__name__}: {e}", True)

total = len(tk_install.PASOS)
c("la cabecera dice por dónde va",
  wiz.cabecera.cget("text").startswith(f"Paso {total} de {total}"), True)
c("en el último paso el botón cambia de nombre",
  wiz.boton_siguiente.cget("text"), "Terminar")
en_paso(wiz, 0)
c("y en el primero no se puede ir atrás", str(wiz.boton_atras.cget("state")), "disabled")

# --- la conexión es lo primero, y sin ella no se avanza ----------------------
# Es el cambio que hace publicable el proyecto: quien clona el repositorio no
# tiene ningún perfil, y antes eso mataba el asistente en el primer paso.
sin_conexion = nuevo_asistente(dispositivo)
sin_conexion.perfil = profile.empty()
en_paso(sin_conexion, PASO["Conexión"])
c("un perfil vacío no revienta, solo no deja seguir",
  str(sin_conexion.boton_siguiente.cget("state")), "disabled")

sin_conexion.perfil = PERFIL
sin_conexion.revisar()
c("con conexión configurada sí", str(sin_conexion.boton_siguiente.cget("state")),
  "normal")

# --- las condiciones de los demás pasos --------------------------------------
vacio = nuevo_asistente()
vacio.catalog = None
vacio.rclone = None
en_paso(vacio, PASO["Comprobaciones"])
c("sin catálogo no se sale de las comprobaciones",
  str(vacio.boton_siguiente.cget("state")), "disabled")

vacio.catalog = remote.parse_catalog(CATALOGO)
vacio.rclone = remote.Rclone("RCLONE", "CONF", remote_name="nas")
vacio.revisar()
c("con catálogo sí", str(vacio.boton_siguiente.cget("state")), "normal")

en_paso(vacio, PASO["Destino"])
c("sin destino no se sale del paso de destino",
  str(vacio.boton_siguiente.cget("state")), "disabled")

en_paso(vacio, PASO["Cifrado"])
c("sin saber dónde va la estructura no se sale del cifrado",
  str(vacio.boton_siguiente.cget("state")), "disabled")
vacio.state.device = dispositivo
en_paso(vacio, PASO["Cifrado"])
boton(vacio.cuerpo, "Entendido, usar el dispositivo tal cual").invoke()
c("elegir «sin cifrar» deja el destino listo", vacio.state.device_root, dispositivo)
c("y ya se puede seguir", str(vacio.boton_siguiente.cget("state")), "normal")

# --- el paso de instalación ---------------------------------------------------
limpio = tmpdir()
wiz = nuevo_asistente(limpio)
en_paso(wiz, PASO["Instalación"])
c("sin instalar no se sale del paso de instalación",
  str(wiz.boton_siguiente.cget("state")), "disabled")

boton(wiz.cuerpo, "Instalar el programa").invoke()
from install import deploy                                # noqa: E402

app = deploy.app_dir(limpio)
c("el programa aterriza en la carpeta oculta", (app / "runsync.py").is_file(), True)
c("con su motor", (app / "sync.py").is_file(), True)
c("y su vigilante", (app / "penwatch.py").is_file(), True)
c("el binario de rclone también",
  (app / "bin" / deploy.bin_subdir() / deploy.exe_name()).is_file(), True)
c("los lanzadores quedan en la raíz", (limpio / "runsync.pyw").is_file(), True)
c("se escribe el rclone.conf del dispositivo", (app / "rclone.conf").is_file(), True)
c("queda marcado como instalado", wiz.state.deployed, True)
c("ya se puede seguir", str(wiz.boton_siguiente.cget("state")), "normal")

# Sin id propio, dos dispositivos dirían ser el mismo y un vigilante atado a uno
# concreto lanzaría con el equivocado.
from install import device                                # noqa: E402

c("y el dispositivo recibe un identificador propio",
  len(device.control_id(limpio) or ""), 32)

# Instalar NO es un espejo: nada de lo que hubiera fuera de .prdrive/ se toca.
# Con la siembra esto no se podía prometer.
c("y el resto del volumen sigue ahí",
  sorted(p.name for p in limpio.iterdir() if p.name.startswith("runsync")),
  ["runsync.pyw", "runsync.sh"])

# Un destino con cosas ajenas: el botón está apagado hasta escribir la ruta.
ajeno = tmpdir()
(ajeno / "TFM-sin-copia").mkdir()
otro = nuevo_asistente(ajeno)
en_paso(otro, PASO["Instalación"])
c("con un destino ajeno el botón empieza apagado",
  str(boton(otro.cuerpo, "Instalar el programa").cget("state")), "disabled")

entrada = widgets(otro.cuerpo, ttk.Entry)[0]
entrada.insert(0, str(ajeno))
c("hay que escribir la ruta para desbloquearlo",
  str(boton(otro.cuerpo, "Instalar el programa").cget("state")), "normal")

# --- el paso de parejas escribe el config ------------------------------------
wiz = nuevo_asistente(limpio)
en_paso(wiz, PASO["Parejas y configuración"])
c("sin config escrito no se sale del paso de parejas",
  str(wiz.boton_siguiente.cget("state")), "disabled")

boton(wiz.cuerpo, "Guardar el config y crear las carpetas").invoke()
config = deploy.config_path(limpio)
c("se escribe el sync_config.toml", config.is_file(), True)
c("con las parejas marcadas", sorted(wiz.state.selected), ["docs", "respaldo"])
c("se crean sus carpetas locales", (limpio / "sync-data" / "docs").is_dir(), True)
c("y ya se puede seguir", str(wiz.boton_siguiente.cget("state")), "normal")
c.contains("la cabecera dice de qué catálogo sale",
           config.read_text(encoding="utf-8"), PERFIL.endpoint_catalog)

# --- la inicialización no toca los espejos -----------------------------------
lanzadas.clear()
en_paso(wiz, PASO["Inicialización"])
boton(wiz.cuerpo, "Inicializar ahora").invoke()
orden = lanzadas[-1][1]
c("se inicializa la pareja bisync", "docs" in orden, True)
# Un espejo borra en el otro lado, y aquí las carpetas locales acaban de crearse
# vacías: lanzarlo propagaría ese vacío.
c("y NUNCA un espejo", "respaldo" in orden, False)
c("con --resync", "--resync" in orden, True)

# --- la verificación final ----------------------------------------------------
en_paso(wiz, PASO["Verificación"])
etiquetas = [w.cget("text") for w in widgets(wiz.cuerpo, ttk.Label)]
c("el último paso enseña la lista de comprobación",
  any("sync_config.toml" in str(t) for t in etiquetas), True)

sys.exit(c.report())
