#!/usr/bin/env python3
"""
Detección de unidades, fichero de control y verificación final.

Las unidades ya no salen de un `Get-Volume` por PowerShell —tardaba 3,5 segundos
medidos, y `_paso_destino` lo llamaba en el hilo de Tk al dibujar la primera
pantalla del asistente— sino de cuatro llamadas a kernel32. Lo que se prueba aquí
es `make_volume()`, la mitad pura de esa enumeración, más la tabla de tipos:
`GetLogicalDrives` devuelve TAMBIÉN las unidades de red, que `Get-Volume` no
devolvía y que no pueden ser el dispositivo, así que hay que descartarlas.

También se comprueba que la copia de `CONTROL_FILE`/`CONTROL_TEMPLATE` que vive
en `install/device.py` no se ha separado de la de `penwatch.py`. Están duplicadas
a propósito —penwatch no puede depender del dispositivo, y el instalador acaba dentro de
un .exe— pero si dejan de coincidir, el vigilante no reconocería los dispositivos que
haga el instalador.
"""

import sys
from pathlib import Path

from _harness import Checks, tmpdir

from install import device

c = Checks("instalador: unidades y verificación del dispositivo")

# --- de lo que conteste el sistema a un Volume --------------------------------
sistema = device.make_volume("C", "Fixed", "Windows", "NTFS",
                             509604786176, 184530755584, system_drive="C:")
pen = device.make_volume("E", "Removable", "PRDRIVE", "exFAT",
                         8049885184, 1607237632, system_drive="C:")

c("la letra se convierte en una raíz", str(pen.root), str(Path("E:/")))
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
  str(device.make_volume("e").root), str(Path("E:/")))
c("y con los dos puntos detrás también",
  str(device.make_volume("E:").root), str(Path("E:/")))

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
c("una unidad sin medio dentro no revienta", str(vacia.root), str(Path("Z:/")))
c("sale sin etiqueta", vacia.label, "")
c("y sin tamaño", vacia.size, 0)

# --- la tabla de tipos de GetDriveTypeW ---------------------------------------
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

# --- el fichero de control ----------------------------------------------------
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

# --- no separarse de penwatch -------------------------------------------------
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

# --- la verificación final ----------------------------------------------------
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
(dispositivo / "runsync.pyw").write_text("#\n", encoding="utf-8")
(app / "keys" / "mi_clave").write_text("clave\n", encoding="utf-8")
(app / "bin" / device.bin_subdir() / device.exe_name()).write_text("bin\n",
                                                                   encoding="utf-8")
(app / "sync_config.toml").write_text(
    '[[pair]]\nname = "docs"\nlocal = "sync-data/docs"\n'
    'remote_path = "/datos/docs"\nmode = "bisync"\n', encoding="utf-8")
device.ensure_control_file(dispositivo)

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

(app / "sync_config.toml").write_text("esto no es { toml", encoding="utf-8")
roto = {chk.etiqueta: chk for chk in device.verify_device(dispositivo)}
c("un config ilegible se detecta aquí y no al sincronizar",
  roto["El config se lee"].ok, False)

sys.exit(c.report())
