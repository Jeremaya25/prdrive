#!/usr/bin/env python3
"""
El dispositivo cifrado, antes de abrirlo y al cerrarlo.

Con VeraCrypt, `.prdrive/PRDRIVE` está dentro del contenedor y el vigilante no
veía nada hasta que alguien lo abría a mano. Ahora reconoce el dispositivo
cerrado por la marca del vestíbulo (el mismo id) y le pide a VeraCrypt que lo
abra. Lo que se comprueba:

  * Una vez por conexión: si se cancela la contraseña, no se vuelve a preguntar
    hasta que la unidad desaparezca y vuelva. Y tampoco después de «Expulsar»,
    con la unidad todavía puesta: lo que se quiere entonces es quitarla.
  * Solo el dispositivo de ESTE vigilante: con otro id no se pide nada.
  * El vigilante no lanza runsync desde el vestíbulo: eso lo hace el bucle de
    siempre al ver el volumen montado, respetando el modo.
  * La orden: el VeraCrypt instalado antes que el que viaja, y sin contraseña.
  * Desde dentro: la ventana encuentra la raíz física por el mismo id, y
    «Reparación» avisa cuando a un contenedor dinámico se le acaba el sitio.

Ni VeraCrypt ni una unidad de verdad: raíces en carpetas temporales, un equipo de
mentira para el estado del vigilante, y la apertura y el lanzamiento sustituidos.
"""

import os
import shutil
import sys
import time
from pathlib import Path

from _harness import Checks, mkcfg, sandbox, tmpdir

import penwatch
from common import fleet, revision, vestibulo
from install import vestibulo as escritor
from ui import cifrado

c = Checks("el dispositivo cifrado: abrirlo al conectar y cerrarlo al quitar")

ID = "a" * 32

# --- 1. las copias de penwatch no se separan ------------------------------------
c("el contenedor de penwatch es el de common", penwatch.CONTAINER_FILE,
  vestibulo.CONTENEDOR)
c("y la marca también", penwatch.VESTIBULE_MARKER, vestibulo.MARCA)

# --- 2. un equipo de mentira ------------------------------------------------------
equipo = tmpdir("prdrive-equipo-")
for nombre, ruta in (("HOST_DIR", equipo), ("CONFIG_FILE", equipo / "watch.json"),
                     ("STATE_FILE", equipo / "state.json"),
                     ("LOG_FILE", equipo / "penwatch.log"),
                     ("STOP_FILE", equipo / "stop")):
    setattr(penwatch, nombre, ruta)


def vestibulo_en(device_id=ID, con_contenedor=True) -> Path:
    raiz = tmpdir("prdrive-fisica-")
    if con_contenedor:
        (raiz / vestibulo.CONTENEDOR).write_bytes(b"x")
    escritor.escribir(raiz, device_id)
    return raiz


fisica = vestibulo_en()
raices: list[Path] = []
penwatch.candidate_roots = lambda cfg: list(raices)
cfg = {"device_id": ID, "mode": "ui"}

raices[:] = [tmpdir(), fisica]
c("encuentra la raíz física de su dispositivo, cerrado",
  penwatch.find_vestibule(cfg), fisica)
c("sin id en el vigilante no pide nada: no sabría de quién es",
  penwatch.find_vestibule({"mode": "ui"}), None)
raices[:] = [vestibulo_en("otro-dispositivo")]
c("otro dispositivo cerrado no es el suyo", penwatch.find_vestibule(cfg), None)
raices[:] = [vestibulo_en(con_contenedor=False)]
c("una marca sin contenedor al lado tampoco", penwatch.find_vestibule(cfg), None)

# --- 3. la orden ----------------------------------------------------------------
reales = {"IS_WIN": penwatch.IS_WIN, "environ": dict(os.environ)}
try:
    penwatch.IS_WIN = True
    instalado = tmpdir("prdrive-programfiles-")
    (instalado / "VeraCrypt").mkdir()
    (instalado / "VeraCrypt" / "VeraCrypt.exe").write_bytes(b"MZ")
    (fisica / "VeraCrypt").mkdir(exist_ok=True)
    (fisica / "VeraCrypt" / "VeraCrypt.exe").write_bytes(b"MZ")
    os.environ["ProgramFiles"] = str(instalado)
    os.environ.pop("ProgramW6432", None)
    orden = penwatch.veracrypt_command(fisica)
    c("Windows: el VeraCrypt instalado antes que el que viaja (ERR_DRIVER_VERSION)",
      orden[0], str(instalado / "VeraCrypt" / "VeraCrypt.exe"))
    c("abre ESTE contenedor, como extraíble, y sale",
      (orden[orden.index("/volume") + 1], "rm" in orden, orden[-1]),
      (str(fisica / vestibulo.CONTENEDOR), True, "/quit"))
    c("sin contraseña: la pide VeraCrypt", "/password" in orden, False)
    c("y sin /auto, que abriría el Explorador", "/auto" in orden, False)
    os.environ["ProgramFiles"] = str(tmpdir())
    c("sin instalado, el que viaja",
      penwatch.veracrypt_command(fisica)[0], str(fisica / "VeraCrypt" / "VeraCrypt.exe"))
    c("sin ninguno, no hay orden", penwatch.veracrypt_command(vestibulo_en()), None)

    penwatch.IS_WIN = False
    binarios = tmpdir("prdrive-bin-")
    (binarios / "veracrypt").write_text("#!/bin/sh\n", encoding="utf-8")
    (binarios / "veracrypt").chmod(0o755)
    os.environ["PATH"] = str(binarios)
    os.environ["DISPLAY"] = ":99"
    os.environ.pop("WAYLAND_DISPLAY", None)
    c("Linux: veracrypt con el contenedor, en su ventana",
      penwatch.veracrypt_command(fisica),
      [str(binarios / "veracrypt"), str(fisica / vestibulo.CONTENEDOR)])
    os.environ.pop("DISPLAY")
    c("sin escritorio no hay dónde pedir la contraseña: nada",
      penwatch.veracrypt_command(fisica), None)
finally:
    penwatch.IS_WIN = reales["IS_WIN"]
    os.environ.clear()
    os.environ.update(reales["environ"])

# --- 4. el bucle: una vez por conexión ------------------------------------------
#
# Cada `watch_loop(once=True)` es un sondeo; el estado queda en el equipo de
# mentira entre uno y otro, como entre dos sondeos de verdad.
aperturas: list[Path] = []
lanzados: list[Path] = []
penwatch.open_container = lambda root: aperturas.append(root) or True
penwatch.launch = lambda root, cfg: lanzados.append(root) or True
penwatch.refresh_runtime = lambda root, cfg: cfg
montado: list[Path] = []
penwatch.find_pen = lambda cfg: montado[0] if montado else None
penwatch.write_json(penwatch.CONFIG_FILE, cfg)
penwatch.write_json(penwatch.STATE_FILE, {})


def sondeo():
    penwatch.watch_loop(once=True)


raices[:] = [fisica]
sondeo()
c("conectado y cerrado: se pide abrirlo", aperturas, [fisica])
c("y NO se lanza runsync desde el vestíbulo", lanzados, [])
sondeo()
c("el siguiente sondeo no vuelve a pedirlo (p. ej. si se canceló)", len(aperturas), 1)

montado.append(tmpdir("prdrive-montado-"))
sondeo()
c("abierto: el bucle de siempre lanza runsync, una vez", lanzados, montado[:1])
sondeo()
c("y no dos", len(lanzados), 1)

montado.clear()           # «Expulsar»: el contenedor se cierra, la unidad sigue
sondeo()
c("tras expulsar, con la unidad aún puesta, no se vuelve a pedir la contraseña",
  len(aperturas), 1)

raices.clear()            # y ahora sí se quita
sondeo()
raices[:] = [fisica]      # y se vuelve a conectar
sondeo()
c("al volver a conectarla, se pide de nuevo", len(aperturas), 2)
c.contains("y queda en el diario", penwatch.LOG_FILE.read_text(encoding="utf-8"),
           "dispositivo cifrado detectado")

# --- 5. lo que dicen status y probe ----------------------------------------------
reales_estado = penwatch.registered_state
penwatch.registered_state = lambda: "tarea: de mentira"
try:
    filas = dict(penwatch.status_rows())
finally:
    penwatch.registered_state = reales_estado
c.contains("status: el dispositivo está, cifrado y cerrado",
           filas["Dispositivo ahora mismo"], "cifrado y cerrado")
notas = dict(penwatch.probe_rows())
c.contains("probe: lo reconoce por su marca", notas[str(fisica)], "cifrado, cerrado")

# --- 6. desde dentro: la raíz física y el espacio de fuera -------------------------
raices[:] = [tmpdir(), vestibulo_en("otro-dispositivo"), fisica]
c("la ventana encuentra su raíz física por el id", vestibulo.raiz_fisica(ID), fisica)
c("sin id, ninguna", vestibulo.raiz_fisica(""), None)
c("con otro id, ninguna", vestibulo.raiz_fisica("b" * 32), None)

disperso = fisica / vestibulo.CONTENEDOR
disperso.unlink()
with open(disperso, "wb") as f:
    f.truncate(64 * 1024 ** 2)       # un contenedor dinámico: mide más de lo que ocupa
lleno = vestibulo_en()
(lleno / vestibulo.CONTENEDOR).write_bytes(b"\0" * 1024 * 1024)
if os.name != "nt":
    c("un fichero disperso se reconoce", vestibulo.disperso(disperso), True)
    c("uno escrito entero, no", vestibulo.disperso(lleno / vestibulo.CONTENEDOR), False)
c("uno que no está, tampoco", vestibulo.disperso(fisica / "no-existe"), False)

with sandbox():
    real_id, real_umbral = fleet.device_id, vestibulo.UMBRAL_LIBRE
    fleet.device_id = lambda app_dir=None: ID
    cfg_notas = mkcfg(["notas"])
    try:
        vestibulo.UMBRAL_LIBRE = 0
        c("con sitio de sobra fuera, nada que avisar",
          "espacio" in {h.clave for h in revision.revisar(cfg_notas)}, False)
        # Un umbral imposible: lo que queda fuera siempre es menos.
        vestibulo.UMBRAL_LIBRE = 1 << 62
        if os.name != "nt":
            hallazgos = revision.revisar(cfg_notas)
            aviso = next((h for h in hallazgos if h.clave == "espacio"), None)
            c("contenedor dinámico y poco sitio fuera: «Reparación» lo avisa",
              aviso is not None and aviso.gravedad, revision.AVISO)
            c.contains("diciendo dónde", aviso.detalle, str(fisica))
            c("y es del dispositivo, no de una pareja", aviso.pareja, None)
            c.contains("y lo imprime también --doctor",
                       "\n".join(revision.informe(cfg_notas)),
                       "se queda sin sitio fuera")
        raices[:] = [lleno]
        c("con un contenedor fijo el sitio de fuera no importa: nada",
          vestibulo.sin_sitio_fuera(vestibulo.leer_id(lleno)), None)
    finally:
        fleet.device_id, vestibulo.UMBRAL_LIBRE = real_id, real_umbral

# --- 7. «Expulsar»: qué script, y lanzarlo suelto ------------------------------------
raices[:] = [fisica]
real_id = fleet.device_id
fleet.device_id = lambda app_dir=None: ID
try:
    esperado = fisica / (vestibulo.EXPULSAR_BAT if os.name == "nt"
                         else vestibulo.EXPULSAR_SH)
    c("dentro de un contenedor, el script de expulsar de su vestíbulo",
      cifrado.expulsion(), esperado)
    esperado.unlink()
    c("un vestíbulo de antes, sin el script: no hay botón", cifrado.expulsion(), None)
    raices.clear()
    c("sin contenedor, tampoco", cifrado.expulsion(), None)
finally:
    fleet.device_id = real_id

if os.name != "nt" and shutil.which("sh"):
    fuera = tmpdir("prdrive-fuera-")
    marca = fuera / "hecho.txt"
    script = fuera / "expulsar.sh"
    script.write_text(f'pwd > "{marca}"\n', encoding="utf-8")
    cifrado.lanzar_expulsion(script)
    for _ in range(50):
        if marca.exists() and marca.read_text(encoding="utf-8").strip():
            break
        time.sleep(0.1)
    c("el script se lanza, suelto, con su directorio de trabajo FUERA del contenedor",
      marca.read_text(encoding="utf-8").strip() if marca.exists() else None,
      str(fuera.resolve()))

sys.exit(c.report())
