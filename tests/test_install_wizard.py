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
# que es lo que interesa comprobar: el trabajo se hace de verdad. Se apunta el
# `progreso` que recibe: crear un contenedor fijo tiene que llevarlo.
esperas: list = []


def working_directo(parent, titulo, funcion, mensaje="", progreso=None):
    esperas.append((titulo, progreso))
    return True, funcion()


tk_install.working = working_directo

# Un rclone de mentira: el paso de instalación lo copia, no lo ejecuta.
RCLONE_FALSO = tmpdir() / "rclone-de-mentira"
RCLONE_FALSO.write_bytes(b"MZ")

# Ni rclone ni Python se descargan: las dos puertas se sustituyen por archivos
# de mentira con la forma de los de verdad. Se apunta qué se ha pedido.
import io  # noqa: E402
import tarfile  # noqa: E402

from common import pins  # noqa: E402
from install import platforms, rclone_bin, runtime_bin  # noqa: E402

pedido: list[str] = []


def archivo_python(plat) -> Path:
    ruta = tmpdir() / f"{plat.clave}.tar.gz"
    with tarfile.open(ruta, "w:gz") as tf:
        for rel in {plat.interprete, plat.interprete_consola}:
            info = tarfile.TarInfo(f"python/{rel}")
            info.size = 2
            tf.addfile(info, io.BytesIO(b"py"))
    return ruta


rclone_bin.rclone_for = lambda plat, progreso=None, allow_download=True: (
    pedido.append("rclone " + plat.clave) or RCLONE_FALSO)
runtime_bin.ensure_runtime = lambda plat, progreso=None, allow_download=True: (
    pedido.append("python " + plat.clave) or archivo_python(plat))

# Quitar de la lista una plataforma que el dispositivo ya lleva pregunta si se
# borra. La pregunta se sustituye, como `mostrar()`; la respuesta la da el test.
respuesta = {"borrar": False}
preguntas: list[str] = []
tk_install._preguntar_borrado = lambda wiz, plat: (
    preguntas.append(plat.clave) or respuesta["borrar"])

ANFITRION = platforms.host() or pins.plataforma("windows-x64")


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


def casilla(w, plat):
    """La casilla de la lista de plataformas de esa plataforma."""
    for b in widgets(w, ttk.Checkbutton):
        if str(b.cget("text")).startswith(plat.nombre):
            return b
    return None


def radio(w, prefijo):
    for b in widgets(w, ttk.Radiobutton):
        if str(b.cget("text")).startswith(prefijo):
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


PASO = {titulo: i for i, (titulo, _, _) in enumerate(tk_install.PASOS_INSTALACION)}

# --- todos los pasos se pintan -----------------------------------------------
dispositivo = tmpdir()
wiz = nuevo_asistente(dispositivo)
for i, (titulo, _, _) in enumerate(tk_install.PASOS_INSTALACION):
    try:
        en_paso(wiz, i)
        c(f"el paso «{titulo}» se pinta", True, True)
    except Exception as e:
        c(f"el paso «{titulo}» se pinta", f"{type(e).__name__}: {e}", True)

total = len(tk_install.PASOS_INSTALACION)
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

# --- «Usar esta conexión» no promete lo que no ha probado (#47) ---------------
# El botón solo convierte el formulario en un perfil; con el remoto se habla en
# «Comprobaciones». Antes pintaba «✔ nas (sftp)» en verde, que se leía como
# «conexión comprobada», también con la plantilla sin rellenar.


def etiquetas(wiz, estilo=None):
    """Los textos de las etiquetas VISIBLES del paso, o solo las de ese estilo."""
    return [str(l.cget("text")) for l in widgets(wiz.cuerpo, ttk.Label)
            if l.winfo_manager() and (estilo is None or str(l.cget("style")) == estilo)]


def promete(wiz) -> bool:
    """¿Dice el paso, de alguna forma, que la conexión está comprobada?"""
    return (any("✔" in t for t in etiquetas(wiz))
            or any(t.strip() for t in etiquetas(wiz, "Ok.TLabel")))


def opciones_del_formulario(wiz, texto):
    caja = widgets(wiz.cuerpo, tk.Text)[0]
    caja.delete("1.0", "end")
    caja.insert("1.0", texto)


def siguiente(wiz):
    return str(wiz.boton_siguiente.cget("state"))


usa = nuevo_asistente(dispositivo)
usa.perfil = profile.empty()
en_paso(usa, PASO["Conexión"])
# La plantilla tal cual: `host = ` vacío. Antes daba ✔ con «Siguiente» encendido.
boton(usa.cuerpo, "Usar esta conexión").invoke()
c("la plantilla sin rellenar no deja seguir", siguiente(usa), "disabled")
c("y dice qué falta, en rojo, en el propio paso",
  any("host = …" in t for t in etiquetas(usa, "Peligro.TLabel")), True)
c("sin ningún ✔", promete(usa), False)

opciones_del_formulario(usa, "host = nas.example\nuser = quien\n")
boton(usa.cuerpo, "Usar esta conexión").invoke()
c("con el formulario bien, se puede seguir", siguiente(usa), "normal")
c("el estado dice que está preparada y sin probar",
  any("sin probar" in t and "paso siguiente" in t for t in etiquetas(usa)), True)
c("con el dato de a dónde apunta", any("nas.example" in t for t in etiquetas(usa)), True)
c("pero sin ✔ ni verde: no se ha hablado con el remoto", promete(usa), False)
c("y sin rojo de antes", etiquetas(usa, "Peligro.TLabel"), [])
c("sin nada que avisar, el aviso no ocupa sitio", etiquetas(usa, "Aviso.TLabel"), [])

# Un sftp sin usuario funciona donde el usuario coincida: se deja seguir, avisando.
opciones_del_formulario(usa, "host = nas.example\n")
boton(usa.cuerpo, "Usar esta conexión").invoke()
c("un aviso no bloquea", siguiente(usa), "normal")
c("pero se enseña", any("user = …" in t for t in etiquetas(usa, "Aviso.TLabel")), True)

# Con una conexión que ya valía, un «Usar» que falla la suelta: un error al lado
# de un «Siguiente» encendido invitaría a seguir con la de antes.
opciones_del_formulario(usa, "port = 22\n")
boton(usa.cuerpo, "Usar esta conexión").invoke()
c("un «Usar» que falla deja el paso sin conexión", siguiente(usa), "disabled")
c("con el error a la vista", any("host = …" in t
                                 for t in etiquetas(usa, "Peligro.TLabel")), True)
c("y sin el aviso de la conexión de antes", etiquetas(usa, "Aviso.TLabel"), [])

# Importar un remote sin `type`: antes, ✔ verde y «Siguiente» gris a la vez.
conf_ajeno = tmpdir() / "rclone.conf"
conf_ajeno.write_text("[sintipo]\nhost = nas.example\n", encoding="utf-8")
importa = nuevo_asistente(dispositivo)
en_paso(importa, PASO["Conexión"])
radio(importa.cuerpo, "Importar").invoke()
elector = next(w for w in widgets(importa.cuerpo, ttk.Combobox)
               if str(w.cget("state")) == "readonly")
next(w for w in elector.master.winfo_children()
     if isinstance(w, ttk.Entry)).insert(0, str(conf_ajeno))
elector.set("sintipo")
boton(importa.cuerpo, "Usar esta conexión").invoke()
c("importar un remote sin tipo no deja seguir", siguiente(importa), "disabled")
c("y dice por qué", any("type = …" in t
                        for t in etiquetas(importa, "Peligro.TLabel")), True)
c("sin ✔ al lado del botón gris", promete(importa), False)

# La conexión que ya venía dada —incrustada en el .exe o en el checkout— tampoco
# se ha probado cuando se pinta el paso.
dada = nuevo_asistente(dispositivo)
en_paso(dada, PASO["Conexión"])
c("una conexión dada se puede usar", siguiente(dada), "normal")
c("y tampoco se da por comprobada", promete(dada), False)
c("dice de dónde sale", any(PERFIL.origen in t for t in etiquetas(dada)), True)

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

en_paso(vacio, PASO["Dispositivo"])
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

# --- el panel de VeraCrypt ----------------------------------------------------
#
# Tres cosas que se dicen ANTES de crear nada: la instalación sin cifrar que se
# quedaría al lado del contenedor, el tope de una unidad FAT32 y una contraseña
# más corta de lo que VeraCrypt recomienda. Ni VeraCrypt ni una unidad de verdad:
# las sondas de `crypto` se sustituyen.
from install import crypto  # noqa: E402
from ui import tk_crypto  # noqa: E402

# El panel importa su propio `working`: el mismo cambio que arriba.
tk_crypto.working = tk_install.working
sondas_crypto = {n: getattr(crypto, n) for n in (
    "find_veracrypt", "soporta_dispersos", "sistema_de_ficheros",
    "medir_escritura", "create_container", "mount_container")}
creados, montado_en = [], tmpdir()
crypto.find_veracrypt = lambda extra_dir=None: {"mount": "VeraCrypt.exe",
                                                "format": "VeraCrypt Format.exe"}
crypto.soporta_dispersos = lambda root: False
crypto.sistema_de_ficheros = lambda root: "FAT32"
crypto.medir_escritura = lambda root, muestra=0: 10 * 1024 ** 2
seguimientos: list = []
crypto.create_container = lambda *a, **k: (
    creados.append(a) or seguimientos.append(k.get("seguimiento")))
crypto.mount_container = lambda *a, **k: montado_en
preguntado: list[str] = []
askyesno_original = messagebox.askyesno
try:
    en_claro = tmpdir()
    (en_claro / ".prdrive").mkdir()
    (en_claro / ".prdrive" / "PRDRIVE").write_text("id=viejo\n", encoding="utf-8")
    (en_claro / "sync-data").mkdir()
    vc = nuevo_asistente(en_claro)
    vc.state.device_root = None
    vc.state.encryption = "veracrypt"
    en_paso(vc, PASO["Cifrado"])
    textos = " ".join(str(w.cget("text")) for w in widgets(vc.cuerpo, ttk.Label))
    c.contains("la instalación sin cifrar se avisa antes de crear", textos, "SIN CIFRAR")
    c.contains("nombrando lo que queda fuera", textos, "sync-data/")
    c.contains("el tope de FAT32 se dice junto al tamaño", textos, "como mucho 4095M")
    campos = widgets(vc.cuerpo, ttk.Entry)
    c("y el tamaño propuesto ya lo respeta",
      "4095M" in [e.get() for e in campos if not e.cget("show")], True)

    claves = [e for e in campos if e.cget("show")]
    for e in claves:
        e.insert(0, "corta")
    messagebox.askyesno = lambda *a, **k: preguntado.append(a[1]) or False
    boton(vc.cuerpo, "Crear y montar").invoke()
    c("una contraseña corta se pregunta, como haría VeraCrypt sin /silent",
      len(preguntado), 1)
    c("y si se dice que no, no se crea nada", creados, [])
    messagebox.askyesno = lambda *a, **k: preguntado.append(a[1]) or True
    boton(vc.cuerpo, "Crear y montar").invoke()
    c("si se dice que sí, se crea", len(creados), 1)
    c("con el tamaño dentro del tope", creados[0][2], 4095 * 1024 ** 2)
    c("y el destino queda en lo montado", vc.state.device_root, montado_en)
    # Sin dispersos se escribe el contenedor entero: la ventanita de espera
    # lleva el avance medido en la unidad (#46), y es el de ESA creación.
    creando = [p for t, p in esperas if t == "creando el contenedor"]
    c("un contenedor fijo se crea con su avance medido",
      isinstance(seguimientos[-1], crypto.Seguimiento), True)
    c("y la ventanita lo enseña", creando[-1] == seguimientos[-1].progreso, True)

    # Con dispersos, `/dynamic`: son segundos y no hay nada que medir.
    crypto.soporta_dispersos = lambda root: True
    crypto.sistema_de_ficheros = lambda root: "NTFS"
    dinamico = nuevo_asistente(tmpdir())
    dinamico.state.device_root = None
    dinamico.state.encryption = "veracrypt"
    en_paso(dinamico, PASO["Cifrado"])
    for e in [e for e in widgets(dinamico.cuerpo, ttk.Entry) if e.cget("show")]:
        e.insert(0, "una contraseña bastante larga")
    boton(dinamico.cuerpo, "Crear y montar").invoke()
    creando = [p for t, p in esperas if t == "creando el contenedor"]
    c("un contenedor dinámico se crea sin medir nada",
      (len(creados), seguimientos[-1], creando[-1]), (2, None, None))

    # Sin VeraCrypt en el equipo, en Windows no hace falta instalarlo: la
    # pantalla ofrece el VeraCrypt Portable oficial, que se baja y se comprueba
    # (#50). Aquí la descarga se sustituye por una carpeta de mentira.
    from _harness import falso_portatil
    from install import veracrypt_bin

    portable_vc = falso_portatil()
    reales_panel = (tk_crypto.IS_WIN, veracrypt_bin.ensure_veracrypt)
    tk_crypto.IS_WIN = True
    crypto.find_veracrypt = lambda extra_dir=None: (
        {"mount": str(Path(extra_dir) / "VeraCrypt-x64.exe"),
         "format": str(Path(extra_dir) / "VeraCrypt Format-x64.exe")}
        if extra_dir else None)
    veracrypt_bin.ensure_veracrypt = lambda progreso=None, allow_download=True: portable_vc
    try:
        sin_vc = nuevo_asistente(tmpdir())
        sin_vc.state.device_root = None
        sin_vc.state.encryption = "veracrypt"
        en_paso(sin_vc, PASO["Cifrado"])
        textos = " ".join(str(w.cget("text")) for w in widgets(sin_vc.cuerpo, ttk.Label))
        c.contains("sin VeraCrypt instalado se ofrece el portable oficial", textos,
                   "VeraCrypt Portable oficial")
        c.contains("diciendo que se comprueba", textos, "SHA-256")
        boton(sin_vc.cuerpo, "Descargar VeraCrypt Portable").invoke()
        c("y bajado, se usa", Path(sin_vc.state.veracrypt["mount"]).parent, portable_vc)
        textos = " ".join(str(w.cget("text")) for w in widgets(sin_vc.cuerpo, ttk.Label))
        c.contains("avisando de que cada paso pedirá administrador", textos,
                   "pedirá permiso de administrador")
    finally:
        tk_crypto.IS_WIN, veracrypt_bin.ensure_veracrypt = reales_panel
finally:
    messagebox.askyesno = askyesno_original
    for nombre, funcion in sondas_crypto.items():
        setattr(crypto, nombre, funcion)

# --- el paso de instalación ---------------------------------------------------
limpio = tmpdir()
wiz = nuevo_asistente(limpio)
en_paso(wiz, PASO["Instalación"])
c("sin instalar no se sale del paso de instalación",
  str(wiz.boton_siguiente.cget("state")), "disabled")

# La lista de plataformas: este equipo viene marcado, y la completa por defecto.
c("la lista trae una casilla por plataforma",
  sum(1 for p in pins.PLATAFORMAS if casilla(wiz.cuerpo, p) is not None),
  len(pins.PLATAFORMAS))
c("este equipo viene marcado", wiz.matriz.elegidas, {ANFITRION.clave})
c("y la instalación completa", wiz.matriz.completa, True)
c.contains("con el total de lo que ocupará",
           " ".join(str(w.cget("text")) for w in widgets(wiz.cuerpo, ttk.Label)),
           f"≈{ANFITRION.mb_rclone + ANFITRION.mb_python} MB")

pedido.clear()
boton(wiz.cuerpo, "Instalar el programa").invoke()
from install import deploy                                # noqa: E402

app = deploy.app_dir(limpio)
c("el programa aterriza en la carpeta oculta", (app / "runsync.py").is_file(), True)
c("con su motor", (app / "sync.py").is_file(), True)
c("y su vigilante", (app / "penwatch.py").is_file(), True)
c("se consigue rclone y Python de este equipo, y de nada más", sorted(pedido),
  sorted([f"rclone {ANFITRION.clave}", f"python {ANFITRION.clave}"]))
c("el binario de rclone va a su bin/",
  platforms.rclone_path(limpio, ANFITRION).is_file(), True)
c("y el Python propio a runtime/",
  platforms.provisioned(limpio).get(ANFITRION.clave), platforms.Instalada(True, True))
c("los lanzadores quedan en la raíz", (limpio / "runsync.bat").is_file(), True)
c("sin el .pyw: la completa no depende del Python del equipo",
  (limpio / "runsync.pyw").exists(), False)
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
  ["runsync.bat", "runsync.sh"])

# Sin contenedor no hay vestíbulo: la entrada de fuera es cosa de VeraCrypt.
from common import vestibulo as vest                      # noqa: E402

c("sin contenedor, nada de vestíbulo", (limpio / vest.MARCA).exists(), False)

# --- con contenedor: la entrada de fuera, con el mismo id -----------------------
#
# El dispositivo vive en lo montado y el vestíbulo en la raíz física, junto al
# .hc. Lo que las une es el id: el de la marca de fuera tiene que ser el del
# fichero de control de dentro, o nadie reconocería el dispositivo cerrado.
fisica = tmpdir()
(fisica / "PRDRIVE.hc").write_bytes(b"x")
montado = tmpdir()
wiz_vc = nuevo_asistente(montado)
wiz_vc.state.device = fisica
wiz_vc.state.encryption = "veracrypt"
en_paso(wiz_vc, PASO["Instalación"])
c.contains("el paso dice que va a dejar la entrada de fuera",
           " ".join(str(w.cget("text")) for w in widgets(wiz_vc.cuerpo, ttk.Label)),
           "Abrir PRDRIVE")
boton(wiz_vc.cuerpo, "Instalar el programa").invoke()
c("el programa va DENTRO del contenedor",
  (deploy.app_dir(montado) / "runsync.py").is_file(), True)
c("y fuera, nada del programa", (fisica / deploy.APP_SUBDIR).exists(), False)
c("fuera, el vestíbulo entero",
  all((fisica / n).is_file() for n in vest.TODOS), True)
c("con el mismo id que el fichero de control de dentro",
  vest.leer_id(fisica), device.control_id(montado))

# --- la ligera: sin Python propio, con el .pyw ---------------------------------
ligero = tmpdir()
wiz_l = nuevo_asistente(ligero)
en_paso(wiz_l, PASO["Instalación"])
radio(wiz_l.cuerpo, "Ligera").invoke()
c("elegir la ligera se apunta", wiz_l.matriz.completa, False)
c.contains("y el total deja de contar el Python",
           " ".join(str(w.cget("text")) for w in widgets(wiz_l.cuerpo, ttk.Label)),
           f"≈{ANFITRION.mb_rclone} MB")
pedido.clear()
boton(wiz_l.cuerpo, "Instalar el programa").invoke()
c("la ligera solo consigue rclone", pedido, [f"rclone {ANFITRION.clave}"])
c("no deja Python propio", platforms.runtime_stamp(ligero, ANFITRION), None)
c("y sí el .pyw, que usa el Python del equipo", (ligero / "runsync.pyw").is_file(), True)

# --- #49: una plataforma que no llega no deja nada a medias --------------------
# Lo reportado: con varias plataformas marcadas, el rclone de una que ni
# siquiera era la de este equipo no llegaba, la instalación se abortaba después
# de haber copiado el programa, y el mensaje no decía que bastaba con desmarcarla.
# Ahora lo de fuera se consigue ANTES de copiar nada: el dispositivo no se toca,
# el mensaje nombra la plataforma y el botón sigue ahí para reintentar.
from install import InstallError  # noqa: E402

otra_plat = next(p for p in pins.PLATAFORMAS if p.clave != ANFITRION.clave)
rclone_para, working_para = rclone_bin.rclone_for, tk_install.working


def rclone_sin_otra(plat, progreso=None, allow_download=True):
    if plat.clave == otra_plat.clave:
        raise InstallError(f"No he podido descargar rclone de https://x/{plat.clave}"
                           f".zip: The read operation timed out")
    return rclone_para(plat, progreso, allow_download)


def working_de_verdad(parent, titulo, funcion, mensaje="", progreso=None):
    """Lo que hace `working()` con una excepción: devolverla, no dejarla escapar."""
    try:
        return True, funcion()
    except Exception as e:                   # noqa: BLE001 — como el de verdad
        return False, e


rclone_bin.rclone_for, tk_install.working = rclone_sin_otra, working_de_verdad
try:
    a_medias = tmpdir()
    wiz_f = nuevo_asistente(a_medias)
    en_paso(wiz_f, PASO["Instalación"])
    casilla(wiz_f.cuerpo, otra_plat).invoke()
    c("la otra plataforma queda marcada", otra_plat.clave in wiz_f.matriz.elegidas, True)
    boton(wiz_f.cuerpo, "Instalar el programa").invoke()
    c("si falta una plataforma, no se copia el programa",
      (a_medias / deploy.APP_SUBDIR).exists(), False)
    c("ni los lanzadores", (a_medias / "runsync.bat").exists(), False)
    textos = " ".join(str(w.cget("text")) for w in widgets(wiz_f.cuerpo, ttk.Label))
    c.contains("el error nombra la plataforma que falta", textos, otra_plat.nombre)
    c.contains("y dice que se puede desmarcar", textos, f"desmarca {otra_plat.nombre}")
    c("no cuenta como instalado", wiz_f.state.deployed, False)
    c("«Siguiente» sigue apagado", str(wiz_f.boton_siguiente.cget("state")), "disabled")
    c("y el botón sigue ahí para reintentar",
      str(boton(wiz_f.cuerpo, "Instalar el programa").cget("state")), "normal")

    # Desmarcarla —no la lleva todavía, así que no pregunta nada— y reintentar.
    preguntas.clear()
    casilla(wiz_f.cuerpo, otra_plat).invoke()
    c("desmarcar una que no lleva no pregunta", preguntas, [])
    boton(wiz_f.cuerpo, "Instalar el programa").invoke()
    c("desmarcándola, se instala",
      (deploy.app_dir(a_medias) / "runsync.py").is_file(), True)
    c("con lo demás", platforms.provisioned(a_medias).get(ANFITRION.clave),
      platforms.Instalada(True, True))
    c("y sin ella", platforms.provisioned(a_medias).get(otra_plat.clave), None)
    c("ya se puede seguir", str(wiz_f.boton_siguiente.cget("state")), "normal")
finally:
    rclone_bin.rclone_for, tk_install.working = rclone_para, working_para

# --- quitar una plataforma que el dispositivo ya lleva -------------------------
# `limpio` ya lleva la de este equipo. Desmarcarla pregunta; lo que se conteste
# decide si entra en el plan como borrado.
quita = nuevo_asistente(limpio)
en_paso(quita, PASO["Instalación"])
c("un dispositivo que ya lleva esta plataforma la trae marcada",
  ANFITRION.clave in quita.matriz.elegidas, True)
respuesta["borrar"] = False
preguntas.clear()
casilla(quita.cuerpo, ANFITRION).invoke()
c("desmarcar lo que ya lleva pregunta si se borra", preguntas, [ANFITRION.clave])
c("decir que no: desmarcada, pero sin borrar", (quita.matriz.elegidas,
                                                 quita.matriz.plan().borrar), (set(), []))
casilla(quita.cuerpo, ANFITRION).invoke()             # otra vez marcada
respuesta["borrar"] = True
casilla(quita.cuerpo, ANFITRION).invoke()
c("decir que sí la manda borrar", [p.clave for p in quita.matriz.plan().borrar],
  [ANFITRION.clave])
c("sin nada marcado no se puede instalar",
  str(boton(quita.cuerpo, "Instalar el programa").cget("state")), "disabled")
casilla(quita.cuerpo, ANFITRION).invoke()
c("volver a marcarla anula el borrado", quita.matriz.plan().borrar, [])
respuesta["borrar"] = False

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


# --- el recorrido corto: una unidad que YA es un prdrive ----------------------
# `limpio` acaba de pasar por la instalación entera, así que sirve de dispositivo
# de verdad. Lo que se comprueba aquí es el desvío: que se reconoce, que no deja
# avanzar hasta elegir camino, y que actualizar no le cambia el identificador.
c("una unidad recién instalada se reconoce como prdrive",
  tk_install._ya_es_prdrive(limpio), True)
c("y una vacía no", tk_install._ya_es_prdrive(tmpdir()), False)

# El paso pinta la lista de unidades del sistema y selecciona la que ya esté
# elegida; sin esto, un directorio temporal no sale en esa lista y la selección
# se pierde. Se sustituye la consulta al sistema, no el paso.
device.list_volumes = lambda: [device.Volume(root=limpio, label="PRDRIVE",
                                             filesystem="exFAT",
                                             drive_type="Removable")]

corto = nuevo_asistente(limpio)
corto.state.device_root = None          # como si no se hubiera pasado por Cifrado
en_paso(corto, PASO["Dispositivo"])
c("con un prdrive detectado, «Siguiente» espera a que se elija camino",
  str(corto.boton_siguiente.cget("state")), "disabled")
c("y se ofrecen los dos caminos",
  sorted(str(b.cget("text")) for b in widgets(corto.cuerpo, ttk.Button)
         if "Actualizar el programa" in str(b.cget("text"))
         or "Reinstalar" in str(b.cget("text"))),
  ["Actualizar el programa", "Reinstalar desde cero"])

antes = device.control_id(limpio)
boton(corto.cuerpo, "Actualizar el programa").invoke()
c("elegir actualizar cambia al recorrido corto",
  [t for t, _, _ in corto.pasos], ["¿Dónde?", "Dispositivo", "Actualización"])
c("y planta al usuario en la pantalla de actualizar", corto.indice, 2)

(app / "sync.py").write_text("# version vieja\n", encoding="utf-8")
(limpio / "runsync.bat").write_bytes(b"rem el que puso el aprovisionamiento\r\n")
boton(corto.cuerpo, "Actualizar ahora").invoke()
c("se sustituye el código",
  "version vieja" in (app / "sync.py").read_text(encoding="utf-8"), False)
c("y se deja el VERSION del instalador", (app / "VERSION").is_file(), True)
c("los lanzadores no se tocan al actualizar",
  (limpio / "runsync.bat").read_bytes(), b"rem el que puso el aprovisionamiento\r\n")
# Renovarle el id sería tratarlo como un dispositivo nuevo, y dejaría colgado a
# cualquier vigilante que ya estuviera atado a este.
c("el identificador del dispositivo NO cambia", device.control_id(limpio), antes)
c("la configuración sigue en su sitio", config.is_file(), True)

# Reinstalar sigue estando disponible: reconocer el dispositivo no puede quitar
# la forma de cambiarle el remoto o el cifrado.
otro_corto = nuevo_asistente(limpio)
en_paso(otro_corto, PASO["Dispositivo"])
boton(otro_corto.cuerpo, "Reinstalar desde cero").invoke()
c("reinstalar mantiene el recorrido largo",
  len(otro_corto.pasos), len(tk_install.PASOS_INSTALACION))
c("y avanza al paso siguiente", otro_corto.indice, PASO["Cifrado"])

# --- «Añadir plataformas…»: sin volver a aprovisionar ---------------------------
# Lleva la misma lista a un dispositivo que ya existe. La configuración, las
# claves y el estado no se tocan: solo rclone y Python de lo que se marque.
config_antes = config.read_bytes()
mas = nuevo_asistente(limpio)
en_paso(mas, PASO["Dispositivo"])
boton(mas.cuerpo, "Añadir plataformas…").invoke()
c("«Añadir plataformas…» cambia a su recorrido corto",
  [t for t, _, _ in mas.pasos], ["¿Dónde?", "Dispositivo", "Plataformas"])
c("y planta al usuario en la lista", mas.indice, 2)
c("con lo que el dispositivo ya lleva marcado",
  ANFITRION.clave in mas.matriz.elegidas, True)

otra = next(p for p in pins.PLATAFORMAS if p.clave != ANFITRION.clave)
casilla(mas.cuerpo, otra).invoke()
c("marcar otra plataforma la añade", otra.clave in mas.matriz.elegidas, True)
pedido.clear()
boton(mas.cuerpo, "Aplicar").invoke()
c("se consigue rclone y Python de la nueva",
  {f"rclone {otra.clave}", f"python {otra.clave}"} <= set(pedido), True)
c("y queda en el dispositivo", platforms.provisioned(limpio).get(otra.clave),
  platforms.Instalada(True, True))
c("sin tocar la configuración", config.read_bytes(), config_antes)
c("ni perder lo que ya llevaba", ANFITRION.clave in platforms.provisioned(limpio), True)
c("y con los lanzadores de una completa", (limpio / "runsync.bat").is_file()
  and (limpio / "runsync.sh").is_file(), True)
c("sin contenedor, tampoco aquí hay vestíbulo", (limpio / vest.MARCA).exists(), False)

# Un dispositivo VeraCrypt de antes no tiene vestíbulo, y este es el camino para
# ponérselo sin reinstalar: el mismo que ya existe para los lanzadores. Se
# simula quitándoselo al que se acaba de hacer con contenedor.
for nombre in vest.TODOS:
    (fisica / nombre).unlink()
# Con VeraCrypt el atajo sale en el paso de cifrado, ya montado: antes de
# montar, el volumen no deja ver el `.prdrive/`.
viejo_vc = nuevo_asistente(montado)
viejo_vc.state.device = fisica
viejo_vc.state.encryption = "veracrypt"
en_paso(viejo_vc, PASO["Cifrado"])
boton(viejo_vc.cuerpo, "Añadir plataformas…").invoke()
boton(viejo_vc.cuerpo, "Aplicar").invoke()
c("«Añadir plataformas…» le pone el vestíbulo a un dispositivo VeraCrypt de antes",
  all((fisica / n).is_file() for n in vest.TODOS), True)
c("con su id de siempre", vest.leer_id(fisica), device.control_id(montado))

# Un dispositivo VeraCrypt de antes lleva además, en VeraCrypt\, la copia de una
# instalación: `VeraCrypt.exe`, una sola arquitectura y sin sello, que su
# vestíbulo de antes sabe abrir. `--update-components` no la toca; «Añadir
# plataformas…» es quien la cambia por el portable oficial —con sello y las dos
# arquitecturas— A LA VEZ que el vestíbulo, y así los dos quedan coherentes (#50).
from _harness import falso_portatil                       # noqa: E402
from common import components as comp                     # noqa: E402
from install import traveler as trav, veracrypt_bin       # noqa: E402

(fisica / "VeraCrypt").mkdir(exist_ok=True)
(fisica / "VeraCrypt" / "VeraCrypt.exe").write_bytes(b"MZ")
(fisica / "VeraCrypt" / "veracrypt-x64.sys").write_bytes(b"MZ")
def veracrypt_pendiente():
    return [p.asistente for p in comp.pendientes(deploy.app_dir(montado), fisica)
            if p.que == comp.VERACRYPT]


c("antes de nada, se sabe que ese VeraCrypt no se pone al día solo",
  veracrypt_pendiente(), [True])
portable = falso_portatil()
reales_vc = (trav.IS_WIN, veracrypt_bin.ensure_veracrypt)
trav.IS_WIN = True
veracrypt_bin.ensure_veracrypt = lambda progreso=None, allow_download=True: portable
try:
    viejo_vc = nuevo_asistente(montado)
    viejo_vc.state.device = fisica
    viejo_vc.state.encryption = "veracrypt"
    en_paso(viejo_vc, PASO["Cifrado"])
    boton(viejo_vc.cuerpo, "Añadir plataformas…").invoke()
    textos = " ".join(str(w.cget("text")) for w in widgets(viejo_vc.cuerpo, ttk.Label))
    c.contains("el paso dice que cambia el VeraCrypt de antes", textos,
               "lleva un VeraCrypt de antes")
    c.contains("por el portable, con las dos arquitecturas", textos, "con x64 y ARM64")
    c.contains("a la vez que la entrada que lo abre", textos, "a la vez que la entrada")
    boton(viejo_vc.cuerpo, "Aplicar").invoke()
    c("queda el VeraCrypt Portable, con su sello", trav.version_puesta(fisica),
      pins.VERACRYPT_VERSION)
    c("con las dos arquitecturas", trav.arquitecturas(fisica / "VeraCrypt"),
      ["arm64", "x64"])
    c("sin el VeraCrypt.exe de antes mezclado",
      (fisica / "VeraCrypt" / "VeraCrypt.exe").exists(), False)
    c("y con la entrada nueva, que sabe abrir el portable",
      "VeraCrypt-%VC_ARQ%.exe" in (fisica / vest.ABRIR_BAT).read_text(encoding="utf-8"),
      True)
    c("y su VeraCrypt ya no está pendiente", veracrypt_pendiente(), [])
finally:
    trav.IS_WIN, veracrypt_bin.ensure_veracrypt = reales_vc


# --- no se puede pasar del paso «Instalación» sin instalar -----------------------
# Bastaba con que `sync.py` estuviese ya en la unidad, así que al reinstalar sobre
# un dispositivo existente el botón «Siguiente» llegaba activado y se podía saltar
# la copia del código. El paso siguiente sí escribe un `sync_config.toml` nuevo, y
# quedaba un dispositivo con config nuevo sobre código viejo —lo que pide ese
# config su código no lo entiende— sin aviso ninguno hasta la primera pasada.
ya_instalado = tmpdir()
app = ya_instalado / deploy.APP_SUBDIR
app.mkdir(parents=True)
(app / "sync.py").write_text("# de una instalacion anterior", encoding="utf-8")

viejo = nuevo_asistente(ya_instalado)
c("con código viejo en la unidad, «Siguiente» sigue apagado",
  tk_install._ok_instalacion(viejo), False)
viejo.state.deployed = True
c("y se enciende al haber instalado de verdad",
  tk_install._ok_instalacion(viejo), True)

# --- «En este equipo»: el agente residente ------------------------------------
# El mismo asistente, otra lista de pasos. Nada de esto toca el equipo de
# verdad: la carpeta del agente va a un temporal, y preparar y activar se
# sustituyen por lo que apuntan (lo de dentro lo prueba test_install_agente).
import penwatch  # noqa: E402
from common import equipo  # noqa: E402
from install import agente as ia  # noqa: E402
from ui import tk_equipo  # noqa: E402

equipo.DIR = tmpdir("prdrive-asis-equipo-")
penwatch.CONFIG_FILE = tmpdir("prdrive-asis-pw-") / "watch.json"
tk_equipo.working = working_directo
preparados, activados = [], []
PREP = ia.Preparado(equipo.DIR / "agente" / "0.4.0", equipo.DIR / "runtime" / "x" / "py",
                    "sello")
ia.preparar = lambda progreso=None: preparados.append(1) or PREP
ia.activar = lambda prep, elegidas, espera: (activados.append((prep, elegidas, espera))
                                             or ["Agente arrancado."])
ia.candidatas = lambda: [ia.Candidata("u" * 32, "PRDRIVE-2", equipo.DAEMON,
                                      "enchufada ahora")]

casa = nuevo_asistente(None)
en_paso(casa, 0)
c("el primer paso es «¿Dónde?»", tk_install.PASOS_INSTALACION[0][0], "¿Dónde?")
c("  sale elegido «En una unidad»: quien prepara un pendrive no nota nada",
  (casa.donde, casa.pasos is tk_install.PASOS_INSTALACION), ("unidad", True))
c("  y se puede seguir sin tocar nada", str(casa.boton_siguiente.cget("state")), "normal")
radio = next(w for w in widgets(casa.cuerpo, ttk.Radiobutton)
             if w.cget("text") == "En este equipo")
radio.invoke()
c("«En este equipo» cambia la lista de pasos",
  [t for t, _, _ in casa.pasos], ["¿Dónde?", "Instalación", "Unidades", "Arranque",
                                  "Verificación"])
c("  sin moverse de la primera pantalla", casa.indice, 0)
casa.ir(+1)
c("«Instalación»: Siguiente apagado hasta instalar",
  str(casa.boton_siguiente.cget("state")), "disabled")
boton(casa.cuerpo, "Instalar el agente").invoke()
c("  instalar prepara el código y el Python", (preparados, casa.agente_prep), ([1], PREP))
c("  y enciende Siguiente", str(casa.boton_siguiente.cget("state")), "normal")
casa.ir(+1)
c("«Unidades» ofrece las que se saben sin red, con su modo",
  casa.agente_unidades, {"u" * 32: (equipo.DAEMON, "PRDRIVE-2")})
caja = next(iter(widgets(casa.cuerpo, ttk.Combobox)))
caja.set(equipo.TEXTO_MODO[equipo.SYNC])
caja.event_generate("<<ComboboxSelected>>")
c("  cambiar el modo lo apunta", casa.agente_unidades["u" * 32][0], equipo.SYNC)
casa.ir(+1)
c("«Arranque»: Siguiente apagado hasta registrar",
  str(casa.boton_siguiente.cget("state")), "disabled")
boton(casa.cuerpo, "Registrar y arrancar").invoke()
c("  registrar activa con lo elegido",
  activados, [(PREP, {"u" * 32: (equipo.SYNC, "PRDRIVE-2")}, 120.0)])
c("  y enciende Siguiente", str(casa.boton_siguiente.cget("state")), "normal")
casa.ir(+1)
c("«Verificación» se pinta y es la última",
  casa.boton_siguiente.cget("text"), "Terminar")
filas = {e: ok for e, ok, _ in tk_equipo.comprobaciones()}
c("  y dice lo que falta (aquí nada se instaló de verdad)",
  (filas["Agente instalado"], filas["penwatch"]), (False, True))
casa.ir(-4)
radio = next(w for w in widgets(casa.cuerpo, ttk.Radiobutton)
             if w.cget("text") == "En una unidad")
radio.invoke()
c("volver a «En una unidad» devuelve el recorrido de siempre",
  casa.pasos is tk_install.PASOS_INSTALACION, True)


sys.exit(c.report())
