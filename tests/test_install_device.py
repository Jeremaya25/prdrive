#!/usr/bin/env python3
"""Detección de unidades, fichero de control y verificación final.

Las unidades salen de cuatro llamadas a kernel32, no de un `Get-Volume` por
PowerShell (3,5 segundos medidos, en el hilo de Tk al dibujar la primera
pantalla del asistente). Lo que se prueba aquí es `make_volume()`, la mitad
pura de esa enumeración, más la tabla de tipos: `GetLogicalDrives` devuelve
TAMBIÉN las unidades de red, que no pueden ser el dispositivo, así que hay que
descartarlas.

También se comprueba que la copia de `CONTROL_FILE`/`CONTROL_TEMPLATE` que vive
en `install/device.py` no se ha separado de la de `penwatch.py`. Están
duplicadas a propósito (penwatch no puede depender del dispositivo, y el
instalador acaba dentro de un .exe) pero si dejan de coincidir, el vigilante no
reconocería los dispositivos que haga el instalador.
"""

import sys
from pathlib import Path, PureWindowsPath

from _harness import Checks, tmpdir

from install import device

c = Checks("instalador: unidades y verificación del dispositivo")

# de lo que conteste el sistema a un Volume
sistema = device.make_volume("C", "Fixed", "Windows", "NTFS",
                             509604786176, 184530755584, system_drive="C:")
pen = device.make_volume("E", "Removable", "PRDRIVE", "exFAT",
                         8049885184, 1607237632, system_drive="C:")

# `PureWindowsPath` y no `Path`: lo que se comprueba es una raíz de Windows
# (`E:\\`), y `Path("E:/")` solo la escribe así EN Windows —fuera, «E:» es un
# nombre de fichero cualquiera y el test fallaba sin que nada estuviera roto.
c("la letra se convierte en una raíz", str(pen.root), str(PureWindowsPath("E:/")))
c("se marca la del sistema", sistema.is_system, True)
c("y solo esa", pen.is_system, False)
c("la etiqueta se lee", pen.label, "PRDRIVE")
c("los tamaños se pasan a GB", pen.size_gb, 7.5)
c("y el hueco libre también", pen.free_gb, 1.5)
c("'Removable' se reconoce", pen.removable, True)
c("'Fixed' no", sistema.removable, False)
c("de la unidad del sistema se avisa fuerte", "SISTEMA" in sistema.nota, True)

# La letra no siempre llega escrita igual según de dónde venga.
c("una letra en minúscula se normaliza",
  str(device.make_volume("e").root), str(PureWindowsPath("E:/")))
c("y con los dos puntos detrás también",
  str(device.make_volume("E:").root), str(PureWindowsPath("E:/")))

# Un pendrive que se declara 'Fixed' —lo normal en los SSD por USB— tiene que
# salir igualmente en la lista, con una nota: filtrarlo es lo que hacía que no
# apareciera el dispositivo del usuario.
fijo = device.make_volume("E", "Fixed", "PRDRIVE", "exFAT",
                          8049885184, 1607237632, system_drive="C:")
c.contains("un extraíble que se declara fijo se avisa, no se descarta",
           fijo.nota, "no se declara extraíble")

# Una unidad sin medio dentro —un CD o un lector de tarjetas vacíos— hace fallar
# a GetVolumeInformationW, y aun así tiene que salir: que la letra exista ya es
# un dato, y esconderla es justo lo que dejaba al usuario sin ver su unidad.
vacia = device.make_volume("Z", "CD-ROM", system_drive="C:")
c("una unidad sin medio dentro no revienta", str(vacia.root), str(PureWindowsPath("Z:/")))
c("sale sin etiqueta", vacia.label, "")
c("y sin tamaño", vacia.size, 0)

# la tabla de tipos de GetDriveTypeW
c("DRIVE_REMOVABLE", device.DRIVE_TYPES[2], "Removable")
c("DRIVE_FIXED", device.DRIVE_TYPES[3], "Fixed")
c("DRIVE_REMOTE", device.DRIVE_TYPES[4], "Network")
c("DRIVE_CDROM", device.DRIVE_TYPES[5], "CD-ROM")

# Ésta es la comprobación del cambio de comportamiento: `Get-Volume` no devolvía
# las unidades de red y `GetLogicalDrives` sí, así que sin el filtro el selector
# de destino se llenaría de unidades mapeadas que nadie puede elegir.
c("las de red no se ofrecen", "Network" in device.TIPOS_OCULTOS, True)
c("las extraíbles sí", "Removable" in device.TIPOS_OCULTOS, False)
c("y las fijas también, que muchos pendrives lo son",
  "Fixed" in device.TIPOS_OCULTOS, False)

# el fichero de control
base = tmpdir()
primero = device.ensure_control_file(base)
c("se crea con un id", len(primero), 32)
c("y se puede releer", device.control_id(base), primero)
c("llamarlo otra vez no cambia el id", device.ensure_control_file(base), primero)

# Reutilizar un volumen que ya fue de otro dispositivo exige renovar el id: dos
# dispositivos no pueden decir ser el mismo, o un vigilante atado a ese id
# lanzaría con el equivocado.
c("renovar sí lo cambia", device.ensure_control_file(base, renew=True) != primero, True)
c("un PRDRIVE sin id se trata como si no lo tuviera",
  device.control_id(tmpdir()), None)

# no separarse de penwatch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import penwatch  # noqa: E402

c("el nombre del fichero de control coincide con el de penwatch",
  device.CONTROL_FILE, penwatch.CONTROL_FILE)
c("y la plantilla también", device.CONTROL_TEMPLATE, penwatch.CONTROL_TEMPLATE)
c("y lo que penwatch busca dentro del dispositivo",
  str(device.STRUCT_MARKER), str(penwatch.STRUCT_MARKER))
# La marca es un identificador con efectos: da nombre al fichero de control, a
# la carpeta oculta y a la tarea programada. penwatch no puede importar `common`
# —se copia al equipo y arranca con el dispositivo desconectado—, así que la
# repite, y esto es lo que impide que las dos copias se separen.
from common import APP_NAME  # noqa: E402

c("y la marca no se ha separado de la de common/", penwatch.APP_NAME, APP_NAME)
c("la carpeta del código es la misma en los dos",
  penwatch.APP_SUBDIR, device.APP_SUBDIR)

# El Python del equipo se PREGUNTA (en un proceso aparte): lo que contesta depende
# de la máquina que corre el test, y la ligera pide Tk 9. Todo lo que pase por
# `check_python()` sin un Python propio en la raíz sustituye `preguntar_python()`
# por una respuesta fija con Tk 9; si no, estos tests fallarían en cualquier
# intérprete con Tk 8.6 (python.org en Windows, los de Linux, la pata
# `python-minimo` de la CI).
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
from contextlib import contextmanager  # noqa: E402

import install  # noqa: E402


def contesta(version=(3, 12, 1), tk=9.0, rc=0, salida=None, error=""):
    """Devuelve un `preguntar_python()` de mentira que contesta como un Python dado.

    Args:
        version: La versión que dice tener.
        tk: Su `TkVersion`, o `None` si no tiene tkinter.
        rc: El código con el que acaba.
        salida: Lo que escribe, si no es la línea JSON de la sonda.
        error: Lo que escribe por stderr.
    """
    texto = salida if salida is not None else json.dumps(
        {"version": list(version), "tk": tk}) + "\n"

    def falso(cmd):
        return subprocess.CompletedProcess(list(cmd), rc, texto, error)
    return falso


@contextmanager
def python_del_equipo(pregunta=None, orden=("/usr/bin/python3",)):
    """Pone un Python del equipo de mentira, que contesta `pregunta` (por defecto, Tk 9)."""
    reales = install.python_command, device.preguntar_python
    install.python_command = lambda windowless=False: list(orden)
    device.preguntar_python = pregunta or contesta()
    try:
        yield
    finally:
        install.python_command, device.preguntar_python = reales


# la verificación final
dispositivo = tmpdir()
faltan = {chk.etiqueta: chk.ok for chk in device.verify_device(dispositivo)}
c("un dispositivo vacío no pasa la verificación", any(faltan.values()) and
  faltan["Interfaz (runsync.py)"], False)
c("y se dice que falta el fichero de control", faltan["Fichero de control"], False)

app = dispositivo / device.APP_SUBDIR
(app / "keys").mkdir(parents=True)
(app / "bin" / device.bin_subdir()).mkdir(parents=True)
for rel in ("runsync.py", "sync.py", "rclone.conf"):
    (app / rel).write_text("#\n", encoding="utf-8")
(dispositivo / "runsync.bat").write_text("#\n", encoding="utf-8")
(dispositivo / "runsync.sh").write_text("#\n", encoding="utf-8")
(app / "keys" / "mi_clave").write_text("clave\n", encoding="utf-8")
(app / "bin" / device.bin_subdir() / device.exe_name()).write_text("bin\n",
                                                                   encoding="utf-8")
(app / "sync_config.toml").write_text(
    '[[pair]]\nname = "docs"\nlocal = "sync-data/docs"\n'
    'remote_path = "/datos/docs"\nmode = "bisync"\n', encoding="utf-8")
device.ensure_control_file(dispositivo)

with python_del_equipo():
    resultado = {chk.etiqueta: chk
                 for chk in device.verify_device(dispositivo, ["docs"], "mi_clave")}
c("un dispositivo completo pasa todas",
  [e for e, chk in resultado.items() if not chk.ok], [])

# El nombre del fichero de clave lo elige el usuario, así que llega del perfil.
# Un backend con contraseña o con agente no tiene ninguna, y entonces no falta
# nada: no se comprueba.
sin_clave = {chk.etiqueta for chk in device.verify_device(dispositivo)}
c("sin clave en el perfil no se busca ninguna",
  "Clave del remoto" in sin_clave, False)
con_otra = {chk.etiqueta: chk
            for chk in device.verify_device(dispositivo, key_name="la_que_no_es")}
c("y con otro nombre se echa en falta",
  con_otra["Clave del remoto"].ok, False)
c.contains("y se cuenta lo que lleva el config",
           resultado["El config se lee"].detalle, "docs")

# Si el config no tiene la pareja que se eligió, algo ha ido mal y hay que decirlo.
parcial = {chk.etiqueta: chk
           for chk in device.verify_device(dispositivo, ["docs", "claves"], "mi_clave")}
c("se detecta una pareja elegida que no acabó en el config",
  parcial["El config se lee"].ok, False)

# El lanzador que se comprueba es el de ESTE sistema, y ya no el .pyw: la
# instalación completa no lo lleva.
lanzador = "runsync.bat" if device.IS_WIN else "runsync.sh"
c(f"se comprueba el lanzador de este sistema ({lanzador})",
  f"Lanzador ({lanzador})" in resultado, True)

# El Python que usará este equipo: el del dispositivo si lo lleva. Es lo que
# hace que la verificación no exija un Python instalado en una completa.
from install import platforms, runtime_bin  # noqa: E402

anfitrion = platforms.host()
if anfitrion is not None:
    rt = platforms.runtime_dir(dispositivo, anfitrion)
    (rt / anfitrion.interprete).parent.mkdir(parents=True, exist_ok=True)
    for exe in {anfitrion.interprete, anfitrion.interprete_consola}:
        (rt / exe).write_bytes(b"py")
    (rt / runtime_bin.STAMP).write_text("sello\n", encoding="utf-8")
    con_python = {chk.etiqueta: chk for chk in device.verify_device(dispositivo)}
    py = con_python["Python para este equipo"]
    c("con Python propio, el del dispositivo cuenta", py.ok, True)
    c.contains("y se dice que es el suyo", py.detalle, "del dispositivo")

    # Sin Python propio y sin ninguno instalado, este equipo no podría usarlo.
    import install  # noqa: E402
    comando_real = install.python_command
    install.python_command = lambda windowless=False: None
    import shutil as _sh  # noqa: E402
    _sh.rmtree(rt)
    try:
        nada = {chk.etiqueta: chk for chk in device.verify_device(dispositivo)}
    finally:
        install.python_command = comando_real
    c("sin Python propio ni instalado, no pasa", nada["Python para este equipo"].ok, False)
    c.contains("y se dice cómo se arregla", nada["Python para este equipo"].detalle,
               "Añadir plataformas")

(app / "sync_config.toml").write_text("esto no es { toml", encoding="utf-8")
roto = {chk.etiqueta: chk for chk in device.verify_device(dispositivo)}
c("un config ilegible se detecta aquí y no al sincronizar",
  roto["El config se lee"].ok, False)

# El Python del equipo se PREGUNTA, en un proceso aparte. Importar tkinter aquí
# miraría el Tk del intérprete que corre el instalador (el del .exe, compilado),
# no el del equipo, que es el que arrancará la instalación ligera. Y la ligera
# pide Tk 9 (decisión del dueño, 09/10/2026): uno con Tk 8.6, como los Python de
# python.org para Windows, no sirve.
SIN_PROPIO = tmpdir()
"""Una raíz sin Python propio: cuenta el del equipo."""


def preguntar(pregunta, root=None, orden=("/usr/bin/python3",)):
    """Devuelve `check_python(root)` con el Python del equipo y su respuesta de mentira."""
    with python_del_equipo(pregunta, orden):
        return device.check_python(root)


bueno = preguntar(contesta())
c("un Python 3.12 con Tk 9 sirve", (bueno.etiqueta, bueno.ok),
  ("Python en este equipo", True))
c.contains("  y se dice cuál y con qué Tk", bueno.detalle,
           "/usr/bin/python3 (Python 3.12, con Tkinter 9.0)")
sin_tk = preguntar(contesta(tk=None))
c("sin tkinter sirve igual", sin_tk.ok, True)
c.contains("  y se avisa del menú de consola", sin_tk.detalle,
           "pero SIN Tkinter: saldrá el menú de consola")
viejo = preguntar(contesta(version=(3, 10, 12)))
c.contains("uno anterior a 3.11 se dice", viejo.detalle,
           "demasiado viejo para la instalación ligera: pide 3.11 o posterior")
c("  y sin raíz no falla: la completa lleva el suyo", viejo.ok, True)
viejo_raiz = preguntar(contesta(version=(3, 10, 12)), SIN_PROPIO)
c("  con raíz sí: ese dispositivo no arrancaría aquí",
  (viejo_raiz.etiqueta, viejo_raiz.ok), ("Python para este equipo", False))
c.contains("  y se dice", viejo_raiz.detalle, "demasiado viejo para la instalación ligera")
c.contains("  y cómo se arregla", viejo_raiz.detalle, "Añadir plataformas")
con_raiz = preguntar(contesta(), SIN_PROPIO)
c("con raíz, uno bueno del equipo cuenta", con_raiz.ok, True)
c.contains("  y se dice que es el del equipo, con su Tk", con_raiz.detalle,
           "el del equipo: /usr/bin/python3 (Python 3.12, con Tkinter 9.0)")

# Tk 8.6 (los Python de python.org para Windows, y los de la mayoría de las
# distribuciones de Linux): no sirve para la ligera, y se dice por qué.
tk86 = preguntar(contesta(tk=8.6))
c("un Python con Tk 8.6 no sirve para la ligera", (tk86.etiqueta, tk86.ok),
  ("Python en este equipo", False))
c.contains("  y se dice cuál y con qué Tk", tk86.detalle,
           "/usr/bin/python3 (Python 3.12, con Tkinter 8.6)")
c.contains("  y por qué", tk86.detalle, "la instalación ligera pide Tk 9")
c.contains("  y de dónde viene", tk86.detalle, "python.org")
c.contains("  y qué queda: la completa", tk86.detalle, "la instalación completa")
tk86_raiz = preguntar(contesta(tk=8.6), SIN_PROPIO)
c("con raíz, ese dispositivo no arrancaría con él", (tk86_raiz.etiqueta, tk86_raiz.ok),
  ("Python para este equipo", False))
c.contains("  y se dice por qué", tk86_raiz.detalle, "pide Tk 9")
c.contains("  con el Tk que tiene", tk86_raiz.detalle, "Tkinter 8.6")
c.contains("  y cómo se arregla", tk86_raiz.detalle, "Añadir plataformas")
c.contains("  o con un Python con Tk 9", tk86_raiz.detalle, "Tk 9")
tk86_viejo = preguntar(contesta(version=(3, 10, 12), tk=8.6))
c.contains("uno viejo y con Tk 8.6 dice las dos cosas", tk86_viejo.detalle, "pide 3.11")
c.contains("  la otra", tk86_viejo.detalle, "pide Tk 9")
c("  y el Tk lo hace no servir, aunque la edad sola no", tk86_viejo.ok, False)
tk9_justo = preguntar(contesta(tk=9.0), SIN_PROPIO)
c("Tk 9.0 sirve (es el mínimo)", tk9_justo.ok, True)
tk10 = preguntar(contesta(tk=10.0))
c("y un Tk posterior también", tk10.ok, True)

# Sin respuesta es como sin Python (`ok` igual que cuando no hay ninguno).
for nombre, pregunta, texto in (
        ("uno que no contesta a tiempo", contesta(rc=124, salida=""), "no ha contestado en 10 s"),
        ("uno que no se puede lanzar", contesta(rc=127, salida="", error="No such file"),
         "no se ha podido preguntar"),
        ("uno que contesta otra cosa", contesta(salida="hola\n"), "no se ha podido preguntar"),
        ("uno que acaba mal", contesta(rc=1, salida="", error="Fatal Python error"),
         "no se ha podido preguntar")):
    sin_raiz = preguntar(pregunta)
    con = preguntar(pregunta, SIN_PROPIO)
    c(f"{nombre}: no cuenta, ni sin raíz ni con ella", (sin_raiz.ok, con.ok), (False, False))
    c.contains(f"  y se dice ({texto})", sin_raiz.detalle, texto)
    c.contains("  también con raíz", con.detalle, texto)
    c.contains("  y con raíz, cómo se arregla", con.detalle, "Añadir plataformas")

# El alias de la Microsoft Store: `python` existe, pero solo abre la tienda.
tienda = preguntar(contesta(rc=9009, salida="", error="Python was not found; run without "
                            "arguments to install from the Microsoft Store"))
c("el alias de la Store (código 9009) no cuenta como Python", tienda.ok, False)
c.contains("  y se dice que es el alias de la Store", tienda.detalle, "Microsoft Store")
ruta_store = r"C:\Users\ana\AppData\Local\Microsoft\WindowsApps\python.exe"
tienda_ruta = preguntar(contesta(rc=1, salida=""), SIN_PROPIO, orden=(ruta_store,))
c("  ni el que vive en WindowsApps y no contesta", tienda_ruta.ok, False)
c.contains("  y se dice igual", tienda_ruta.detalle, "Microsoft Store")
c.contains("  (dice que parece el alias, no que lo es)", tienda_ruta.detalle, "parece el alias")
c.contains("  y el 9009 sí lo afirma", tienda.detalle, "es el alias de la Microsoft Store")
agotado_store = preguntar(contesta(rc=124, salida=""), SIN_PROPIO, orden=(ruta_store,))
c("un Python de WindowsApps que se agota no es el alias: no ha contestado",
  ("Microsoft Store" in agotado_store.detalle, "no ha contestado en 10 s" in agotado_store.detalle,
   agotado_store.ok), (False, True, False))
de_la_store = preguntar(contesta(), orden=(ruta_store,))
c("pero un Python de la Store que contesta sí sirve",
  (de_la_store.ok, "Microsoft Store" in de_la_store.detalle), (True, False))

# Cómo se pregunta: aislado, sin entrada, con tope y sin consola en Windows.
# Es un `Popen` propio (no `subprocess.run(timeout=)`): al pasarse de tiempo se
# mata al árbol entero, y nunca se espera a que se cierren las tuberías.
from common import store  # noqa: E402

vistas: list = []
matados: list = []


class PopenFalso:
    """Un `subprocess.Popen` de mentira: apunta cómo se lanza y contesta lo que se le diga."""

    contesta = ('{"version": [3, 12, 1], "tk": 9.0}\n', "")
    """Lo que devuelve `communicate()`; una excepción, lo que lanza."""
    al_lanzar: Exception | None = None
    """Lo que lanza el constructor, si algo."""
    pid = 4242

    def __init__(self, cmd, **kwargs):
        if self.al_lanzar is not None:
            raise self.al_lanzar
        vistas.append((list(cmd), kwargs))
        self.returncode = 0
        self.matado = False
        self.esperas: list = []

    def communicate(self, timeout=None):
        self.esperas.append(timeout)
        if isinstance(self.contesta, Exception):
            # La primera espera se pasa de tiempo; la de después de matarlo, ya no.
            if len(self.esperas) == 1:
                raise self.contesta
            return ("", "")
        return self.contesta

    def kill(self):
        self.matado = True


def pregunta_falsa(*, windows=False, **atributos):
    """Pregunta con `Popen` y `store.matar_arbol` falsos; devuelve (resultado, proceso, vistas)."""
    popen_real, win_real, matar_real = subprocess.Popen, device.IS_WIN, store.matar_arbol
    creados: list = []

    class Este(PopenFalso):
        def __init__(self, cmd, **kwargs):
            super().__init__(cmd, **kwargs)
            creados.append(self)

    for nombre, valor in atributos.items():
        setattr(Este, nombre, valor)
    vistas.clear()
    matados.clear()
    subprocess.Popen, device.IS_WIN, store.matar_arbol = Este, windows, matados.append
    try:
        res = device.preguntar_python(["py", "-3"] if windows else ["python3"])
    finally:
        subprocess.Popen, device.IS_WIN, store.matar_arbol = popen_real, win_real, matar_real
    return res, (creados[0] if creados else None), list(vistas)


windows, proceso_win, ((cmd_win, kw_win),) = pregunta_falsa(windows=True)
posix, _, ((cmd_posix, kw_posix),) = pregunta_falsa()
c("la orden es la del Python más -I -c y la sonda",
  cmd_win, ["py", "-3", "-I", "-c", device.SONDA_PYTHON])
c("  sin entrada (stdin=DEVNULL)", kw_win.get("stdin"), subprocess.DEVNULL)
c("  con su tope de 10 s", (proceso_win.esperas, device.TOPE_PYTHON_S), ([10.0], 10.0))
c("  recogiendo la salida como texto",
  (kw_win.get("stdout"), kw_win.get("stderr"), kw_win.get("text")),
  (subprocess.PIPE, subprocess.PIPE, True))
c("  y en Windows sin ventana de consola (CREATE_NO_WINDOW)",
  kw_win.get("creationflags"), install.CREATE_NO_WINDOW)
c("  que fuera de Windows no se pasa", "creationflags" in kw_posix, False)
c("  y en Windows no pide sesión nueva (no existe)", "start_new_session" in kw_win, False)
c("  fuera de Windows sí: hace falta un grupo para cortar el árbol",
  kw_posix.get("start_new_session"), True)
c("  y lo que contesta llega tal cual", windows.stdout, '{"version": [3, 12, 1], "tk": 9.0}\n')
c("  sin tocar a nadie si contesta a tiempo", (matados, proceso_win.matado), ([], False))

# Pasarse de tiempo: se mata al árbol (no solo al hijo), se recoge acotado y el
# código es el de `timeout(1)`.
agota, proceso, _ = pregunta_falsa(contesta=subprocess.TimeoutExpired(["x"], 10))
c("pasarse de tiempo da el código 124", agota.returncode, device.CODIGO_TIEMPO)
c("  matando al árbol entero del hijo", matados, [PopenFalso.pid])
c("  y al propio hijo", proceso.matado, True)
c("  esperando después solo un rato, no sin límite",
  proceso.esperas, [device.TOPE_PYTHON_S, device.TOPE_RECOGER_S])


class Tuberias(PopenFalso):
    """Un hijo cuyas tuberías no se cierran: ni siquiera tras matarlo contesta."""

    def communicate(self, timeout=None):
        self.esperas.append(timeout)
        raise subprocess.TimeoutExpired(["x"], timeout)


popen_real, matar_real = subprocess.Popen, store.matar_arbol
subprocess.Popen, store.matar_arbol = Tuberias, lambda pid: None
try:
    nieto_res = device.preguntar_python(["python3"])
finally:
    subprocess.Popen, store.matar_arbol = popen_real, matar_real
c("un nieto con las tuberías heredadas no deja esperando: 124 igual",
  nieto_res.returncode, device.CODIGO_TIEMPO)

no_lanzada, _, _ = pregunta_falsa(al_lanzar=FileNotFoundError(2, "No such file or directory"))
c("preguntar_python no lanza nada sin lanzarse: código 127",
  (no_lanzada.returncode, matados), (127, []))
con_error, _, _ = pregunta_falsa(al_lanzar=ValueError("embedded null byte"))
c("  ni con una orden inválida", con_error.returncode, 127)

# Con un nieto de verdad (solo POSIX; en Windows el árbol lo corta `taskkill /T`
# y se prueba en la máquina real): un «Python» que deja un hijo con las tuberías
# heredadas y no contesta. Debe volver al pasar el tope, y sin el nieto vivo.
if os.name == "posix":
    falso_py = tmpdir() / "falso-python.sh"
    pid_nieto = tmpdir() / "nieto.pid"
    falso_py.write_text(f"#!/bin/sh\nsleep 60 &\necho $! > '{pid_nieto}'\nsleep 60\n",
                        encoding="utf-8")
    falso_py.chmod(0o755)
    tope_real = device.TOPE_PYTHON_S
    device.TOPE_PYTHON_S = 1.0
    inicio = time.monotonic()
    try:
        colgado = device.preguntar_python([str(falso_py)])
    finally:
        device.TOPE_PYTHON_S = tope_real
    tardo = time.monotonic() - inicio
    c("un «Python» con un nieto colgado vuelve al pasar el tope (124)",
      (colgado.returncode, tardo < 10), (device.CODIGO_TIEMPO, True))
    try:
        apuntado = pid_nieto.read_text(encoding="utf-8").strip()
    except OSError:
        apuntado = None
    nieto = int(apuntado) if apuntado and apuntado.isdigit() else 0
    vivo = nieto > 0
    for _ in range(50):                      # la señal es asíncrona: un instante de margen
        vivo = vivo and store.pid_alive(nieto)
        if not vivo:
            break
        time.sleep(0.1)
    # Lo obtenido dice cuál de las tres cosas ha pasado si esto falla.
    if apuntado is None:
        suerte = "sin nieto.pid: el falso «Python» no llegó a apuntarlo antes del tope"
    elif not nieto:
        suerte = f"nieto.pid a medias: {apuntado!r}"
    else:
        suerte = f"el nieto {nieto} sigue vivo" if vivo else "muerto"
    c("  y el nieto ya no está vivo", suerte, "muerto")
else:
    print("  (saltado) el árbol de procesos de verdad solo se prueba en POSIX")

# El de verdad, en los dos Tk de la CI: contesta una línea JSON que se entiende.
real = device.preguntar_python([sys.executable])
try:
    leido = json.loads(real.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    leido = {}
c("el Python de este test contesta su versión",
  (real.returncode, leido.get("version")), (0, list(sys.version_info[:3])))
c("  y su Tk como número (o nada, sin tkinter)",
  isinstance(leido.get("tk"), (int, float, type(None))) and "tk" in leido, True)

# Y no se importa tkinter en el proceso del instalador, ni siquiera sin raíz.
from _harness import REPO  # noqa: E402

limpio = subprocess.run(
    [sys.executable, "-c",
     "import sys; sys.path.insert(0, sys.argv[1]); from install import device; "
     "device.check_python(); print('tkinter' in sys.modules)", str(REPO)],
    capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
# Solo importa que no se importe tkinter: lo que dice `ok` depende del Tk de la
# máquina que corre el test, y eso se prueba arriba con respuestas fijas.
c("check_python() no importa tkinter en su propio proceso",
  limpio.stdout.split(), ["False"])

sys.exit(c.report())
