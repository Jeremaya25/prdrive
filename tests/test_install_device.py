#!/usr/bin/env python3
"""
Detección de unidades, fichero de control y verificación final.

Lo interesante aquí es el JSON de Get-Volume: `ConvertTo-Json` devuelve un OBJETO
cuando solo hay un volumen y una LISTA cuando hay varios, así que el caso de «un
único pendrive conectado» es exactamente el que rompe si se trata como lista. Se
prueba con salida enlatada, sin llamar a PowerShell.

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

VARIOS = ('[{"DriveLetter":"C","FileSystemLabel":"Windows","FileSystem":"NTFS",'
          '"DriveType":"Fixed","Size":509604786176,"SizeRemaining":184530755584},'
          '{"DriveLetter":"E","FileSystemLabel":"PRDRIVE","FileSystem":"exFAT",'
          '"DriveType":"Removable","Size":8049885184,"SizeRemaining":1607237632}]')
UNO = ('{"DriveLetter":"E","FileSystemLabel":"PRDRIVE","FileSystem":"exFAT",'
       '"DriveType":"Removable","Size":8049885184,"SizeRemaining":1607237632}')

# --- el JSON de Get-Volume ----------------------------------------------------
volumenes = device.parse_volumes_json(VARIOS, system_drive="C:")
c("varias unidades", [str(v.root) for v in volumenes],
  [str(Path("C:/")), str(Path("E:/"))])
c("se marca la del sistema", [v.is_system for v in volumenes], [True, False])
c("y solo esa", volumenes[1].is_system, False)

# Este es el caso que fallaba: con un solo pendrive, ConvertTo-Json no da lista.
uno = device.parse_volumes_json(UNO, system_drive="C:")
c("una sola unidad no revienta", len(uno), 1)
c("y se lee igual", uno[0].label, "PRDRIVE")

c("los tamaños se pasan a GB", uno[0].size_gb, 7.5)
c("y el hueco libre también", uno[0].free_gb, 1.5)
c("'Removable' se reconoce", uno[0].removable, True)
c("'Fixed' no", volumenes[0].removable, False)

# Un pendrive que se declara 'Fixed' —lo normal en SSD por USB— tiene que salir
# igualmente en la lista, con una nota: filtrarlo es lo que hacía que no
# apareciera el dispositivo del usuario.
fijo = device.parse_volumes_json(
    UNO.replace('"Removable"', '"Fixed"'), system_drive="C:")[0]
c("un extraíble que se declara fijo no se descarta", len(uno), 1)
c.contains("pero se avisa", fijo.nota, "no se declara extraíble")
c("de la unidad del sistema se avisa fuerte", "SISTEMA" in volumenes[0].nota, True)
c("nada raro que decir de un JSON vacío", device.parse_volumes_json(""), [])
c("ni de uno ilegible", device.parse_volumes_json("{no es json"), [])

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
