#!/usr/bin/env python3
"""El KeePassXC del llavero, comprobado y puesto en la unidad (`install/keepassxc_bin.py`).

Se fabrica un ZIP de mentira con la forma del oficial (una sola carpeta
`KeePassXC-2.7.12-Win64/` con `.portable`, el programa y alguna subcarpeta) y
se fija su SHA-256 en `pins` para la prueba. Se comprueba lo que puede hacer
daño:
- Que un ZIP que no es el fijado no se guarda, ni bajado ni dejado a mano.
- Que una ruta que se sale de la carpeta tumba el ZIP entero antes de escribir
  el primer fichero.
- Que el sello va el último y dice la verdad de cada fichero, y que un cambio
  que falla deja el KeePassXC de antes como estaba.
- Que la ventana lo cuenta como pendiente, también si falta, solo con el
  llavero activo, y que el aplicador lo pospone si algo corre desde su carpeta.

Ninguno habla con la red: `fetch()` se sustituye, y la caché va a un
`LOCALAPPDATA` de mentira.
"""

import hashlib
import io
import os
import sys
import urllib.error
import zipfile

from _harness import Checks, tmpdir

from common import components, pins
from install import InstallError, components as icomponents, descarga, keepassxc_bin, traveler

c = Checks("KeePassXC del llavero (install/keepassxc_bin.py)")

descarga.esperar = lambda segundos: None
os.environ["LOCALAPPDATA"] = str(tmpdir("prdrive-kpx-cache-"))
ARRIBA = "KeePassXC-2.7.12-Win64/"


def hacer_zip(ficheros: dict[str, bytes], arriba: str = ARRIBA) -> bytes:
    """Devuelve un ZIP con esos ficheros dentro de la carpeta de arriba."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(arriba, b"")                      # la entrada de la carpeta
        for nombre, datos in ficheros.items():
            zf.writestr(arriba + nombre, datos)
    return buf.getvalue()


BUENO = {".portable": b"", "KeePassXC.exe": b"MZ el programa", "keepassxc-cli.exe": b"MZ cli",
         "keepassxc-proxy.exe": b"MZ proxy", "plugins/platforms/qwindows.dll": b"MZ qt"}
ZIP = hacer_zip(BUENO)
NOMBRE = pins.KEEPASSXC["windows-x64"][0]
pins.KEEPASSXC["windows-x64"] = (NOMBRE, hashlib.sha256(ZIP).hexdigest())

pedidas: list[str] = []


def servir(datos):
    """Hace que `fetch()` devuelva esos datos, o lance si son una excepción."""
    def _fetch(direccion, timeout=0):
        pedidas.append(direccion)
        if isinstance(datos, BaseException):
            raise datos
        return datos
    keepassxc_bin.fetch = _fetch


def rechaza(etiqueta, hacer, fragmento, tipo=InstallError):
    """Comprueba que `hacer()` lance `tipo` con ese fragmento en el mensaje."""
    try:
        hacer()
        c(etiqueta, "no lanzó", tipo.__name__)
    except tipo as e:
        c.contains(etiqueta, str(e), fragmento)


# la URL es la versionada, nunca una que se mueva
c("la URL lleva la versión y el nombre del ZIP", keepassxc_bin.url(),
  f"https://github.com/keepassxreboot/keepassxc/releases/download/"
  f"{pins.KEEPASSXC_VERSION}/{NOMBRE}")
c("Windows ARM64 usa el paquete de x64 (A1, A2)",
  (pins.KEEPASSXC_PARA["windows-arm64"], pins.KEEPASSXC_PARA["windows-x64"]),
  ("windows-x64", "windows-x64"))

# la caché: se baja, se comprueba y se guarda; luego se usa sin red
servir(ZIP)
pedidas.clear()
ruta = keepassxc_bin.ensure_zip()
c("se baja, se comprueba y queda en la caché", ruta.read_bytes(), ZIP)
c("  pidiendo la URL versionada", pedidas, [keepassxc_bin.url()])
pedidas.clear()
keepassxc_bin.ensure_zip()
c("la segunda vez sale de la caché, sin red", pedidas, [])

ruta.write_bytes(b"otra cosa")
servir(ZIP)
pedidas.clear()
rechaza("uno dejado en la caché que no es el fijado se dice",
        keepassxc_bin.ensure_zip, "Bórralo")
c("  y no se descarga encima", (pedidas, ruta.read_bytes()), ([], b"otra cosa"))
ruta.unlink()

servir(b"un ZIP que no es el bueno")
rechaza("un ZIP bajado que no es el fijado no se guarda", keepassxc_bin.ensure_zip,
        "no es el KeePassXC fijado")
c("  y la caché queda como estaba", ruta.exists(), False)

servir(urllib.error.URLError("sin red"))
rechaza("sin red se dice cómo ponerlo a mano", keepassxc_bin.ensure_zip,
        "déjalo, con ese nombre", keepassxc_bin.SinRed)
rechaza("sin permiso para descargar, tampoco", lambda: keepassxc_bin.ensure_zip(
    allow_download=False), "no se ha permitido", keepassxc_bin.SinRed)

# las rutas del ZIP, todas validadas antes de escribir nada
for que, malo in (("una ruta con ..", {**BUENO, "../fuera.exe": b"x"}),
                  ("una unidad", {**BUENO, "C:/fuera.exe": b"x"})):
    with zipfile.ZipFile(io.BytesIO(hacer_zip(malo))) as zf:
        rechaza(f"{que} tumba el ZIP entero", lambda: keepassxc_bin.miembros(zf), "se sale")
# En Windows `zipfile` convierte la barra invertida al construir el nombre, así
# que esa se prueba en el validador, que es lo que la para.
c("una ruta con \\ no es segura", components.ruta_relativa_segura("a\\b.dll"), False)
c("  ni una absoluta, ni una vacía", (components.ruta_relativa_segura("/a"),
                                     components.ruta_relativa_segura("")), (False, False))
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as zf:
    zf.writestr("KeePassXC.exe", b"MZ")
with zipfile.ZipFile(buf) as zf:
    rechaza("sin carpeta de arriba se dice", lambda: keepassxc_bin.miembros(zf),
            "una sola carpeta")
with zipfile.ZipFile(io.BytesIO(hacer_zip({".portable": b""}))) as zf:
    rechaza("sin KeePassXC.exe se dice", lambda: keepassxc_bin.miembros(zf),
            "no trae KeePassXC.exe")
with zipfile.ZipFile(io.BytesIO(hacer_zip({**BUENO, components.KEEPASSXC_STAMP: b"x"}))) as zf:
    rechaza("un sello dentro del ZIP no se acepta", lambda: keepassxc_bin.miembros(zf),
            "no es suyo")
with zipfile.ZipFile(io.BytesIO(ZIP)) as zf:
    c("el bueno da sus rutas sin la carpeta de arriba",
      sorted(rel for _, rel in keepassxc_bin.miembros(zf)), sorted(BUENO))

# ponerlo en la unidad
servir(ZIP)
app = tmpdir("prdrive-kpx-app-") / ".prdrive"
app.mkdir()
hecho = keepassxc_bin.instalar(app)
carpeta = components.keepassxc_dir(app, "windows-x64")
c("se pone en keepassxc/windows-x64/", (carpeta / "KeePassXC.exe").read_bytes(),
  BUENO["KeePassXC.exe"])
c("  con su .portable", (carpeta / ".portable").is_file(), True)
c("  y sus subcarpetas", (carpeta / "plugins" / "platforms" / "qwindows.dll").is_file(), True)
sello = (carpeta / components.KEEPASSXC_STAMP).read_text(encoding="utf-8")
c("el sello dice la versión", components.keepassxc_version(app, "windows-x64"),
  pins.KEEPASSXC_VERSION)
c("  y el SHA-256 de cada fichero", components.keepassxc_ficheros(sello),
  {rel: hashlib.sha256(datos).hexdigest() for rel, datos in BUENO.items()})
c("  y lo cuenta", len(hecho), 1)
c("no deja restos del cambio", sorted(p.name for p in carpeta.parent.iterdir()),
  ["windows-x64"])
c("ya está al día", keepassxc_bin.al_dia(app), True)
pedidas.clear()
c("ponerlo otra vez no toca nada", (keepassxc_bin.instalar(app), pedidas), ([], []))

# sustituir uno anterior
(carpeta / components.KEEPASSXC_STAMP).write_text(
    components.keepassxc_stamp_text("2.7.10", "viejo.zip", "00", {}), encoding="utf-8")
(carpeta / "solo-en-la-vieja.dll").write_bytes(b"x")
c("uno de otra versión no está al día", keepassxc_bin.al_dia(app), False)
keepassxc_bin.instalar(app)
c("se sustituye la carpeta entera", ((carpeta / "solo-en-la-vieja.dll").exists(),
                                     components.keepassxc_version(app, "windows-x64")),
  (False, pins.KEEPASSXC_VERSION))

# lo que falla deja lo de antes como estaba
(carpeta / components.KEEPASSXC_STAMP).write_text(
    components.keepassxc_stamp_text("2.7.10", "viejo.zip", "00", {}), encoding="utf-8")
real_libre = traveler.espacio_libre
traveler.espacio_libre = lambda raiz: 1024
rechaza("sin sitio no se toca nada", lambda: keepassxc_bin.instalar(app), "No cabe")
traveler.espacio_libre = real_libre
c("  y lo de antes sigue", components.keepassxc_version(app, "windows-x64"), "2.7.10")

real_resumen = keepassxc_bin._resumen
keepassxc_bin._resumen = lambda r: "mentira" if r.name == "KeePassXC.exe" else real_resumen(r)
rechaza("una unidad que escribe mal no deja un KeePassXC a medias",
        lambda: keepassxc_bin.instalar(app), "no es igual")
keepassxc_bin._resumen = real_resumen
c("  lo de antes sigue", components.keepassxc_version(app, "windows-x64"), "2.7.10")
c("  sin restos", sorted(p.name for p in carpeta.parent.iterdir()), ["windows-x64"])
keepassxc_bin.instalar(app)

# lo que ve la ventana: pendiente solo con el llavero activo
otro = tmpdir("prdrive-kpx-disp-") / ".prdrive"
(otro / "bin" / "x64").mkdir(parents=True)
(otro / "bin" / "x64" / "rclone.exe").write_bytes(b"MZ")
(otro / "sync_config.toml").write_text('[defaults]\nremote = "nas"\n', encoding="utf-8")
c("sin llavero no se pide KeePassXC",
  [p.que for p in components.pendientes(otro, fisica=None)
   if p.que == components.KEEPASSXC], [])
(otro / "sync_config.toml").write_text('[keychain]\nbase = "personal.kdbx"\n',
                                       encoding="utf-8")
pends = [p for p in components.pendientes(otro, fisica=None) if p.que == components.KEEPASSXC]
c("con llavero y sin KeePassXC, «no consta»", [(p.lleva, p.deberia) for p in pends],
  [(components.DESCONOCIDA, pins.KEEPASSXC_VERSION)])
c("  con su título", pends[0].titulo if pends else None, "KeePassXC del llavero")
(otro / "bin" / "x64" / "rclone.exe").unlink()
(otro / "bin" / "x64" / "rclone").write_bytes(b"ELF")
c("un dispositivo solo de Linux no lo pide (es la fase 2)",
  [p.que for p in components.pendientes(otro, fisica=None)
   if p.que == components.KEEPASSXC], [])

# el aplicador: lo pone, y lo pospone si algo corre desde su carpeta
raiz = otro.parent
(otro / "bin" / "arm").mkdir(parents=True)
(otro / "bin" / "arm" / "rclone.exe").write_bytes(b"MZ")
pend = next(p for p in components.pendientes(otro, fisica=None)
            if p.que == components.KEEPASSXC)
real_procesos = icomponents.procesos_desde
icomponents.procesos_desde = lambda carpeta: {4242: str(carpeta / "keepassxc-proxy.exe")}
res = icomponents.aplicar(raiz, pends=[pend])
c("con el proxy del navegador vivo se pospone", (res.hechos, len(res.pospuestos)), ([], 1))
c.contains("  diciendo qué cerrar", res.pospuestos[0] if res.pospuestos else "",
           "Cierra KeePassXC y el navegador")
icomponents.procesos_desde = lambda carpeta: {}
res = icomponents.aplicar(raiz, pends=[pend])
icomponents.procesos_desde = real_procesos
c("sin nada corriendo se pone", (len(res.hechos), res.fallidos), (1, []))
c("  y deja de estar pendiente", [p.que for p in components.pendientes(otro, fisica=None)
                                  if p.que == components.KEEPASSXC], [])

sys.exit(c.report())
