#!/usr/bin/env python3
"""El arranque y la desinstalación del vigilante, tal como se cuentan.

Dos cosas que decía mal, vistas en un equipo de verdad (J1 y J6 en
`docs/superpowers/pruebas/2026-09-24-veracrypt-unidad-g-resultados.md`, #41):
- Tras «Vigilante arrancado.», `status` decía «parado» los primeros segundos:
  `schtasks /Run` y `systemctl start` vuelven al pedir el arranque, y el pid del
  vigilante no está en `state.json` hasta que el proceso arranca. `start_now`
  espera a verlo antes de decir «arrancado», y si no llega lo dice como es.
- `uninstall` hablaba de `.prdrive/PRDRIVE` también en un dispositivo cifrado,
  donde ese fichero está dentro del contenedor y lo que queda fuera es la marca
  del vestíbulo.

Nada lanza un proceso ni escribe en el equipo de verdad: las rutas del equipo
van a un temporal, y `run_quiet`, `Popen`, `sleep` y `pid_alive` se sustituyen.
"""

import io
import time
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

from _harness import Checks, tmpdir

import penwatch

c = Checks("penwatch: arrancar y desinstalar, dicho como es")

ID = "3f9c1a2b4d5e6f708192a3b4c5d6e7f8"

# 1. un equipo de mentira
EQUIPO = tmpdir("prdrive-pwinstala-")
for nombre, ruta in (("HOST_DIR", EQUIPO), ("CONFIG_FILE", EQUIPO / "watch.json"),
                     ("STATE_FILE", EQUIPO / "state.json"),
                     ("LOG_FILE", EQUIPO / "penwatch.log"),
                     ("STOP_FILE", EQUIPO / "stop"),
                     ("SELF_COPY", EQUIPO / "penwatch.py")):
    setattr(penwatch, nombre, ruta)
penwatch.log = lambda msg: None

# 2. arrancar: no se dice «arrancado» hasta que el vigilante lo confirma
VIVOS: set[int] = set()
penwatch.pid_alive = lambda pid: pid in VIVOS

ahora = [0.0]            # el reloj de mentira, en segundos
dormidas: list[float] = []
eventos: dict[int, object] = {}   # qué pasa en la n-ésima vez que se duerme


def dormir(segundos: float) -> None:
    """Hace pasar el reloj de mentira y deja que el vigilante «arranque» a su hora."""
    dormidas.append(segundos)
    ahora[0] += segundos
    accion = eventos.get(len(dormidas))
    if accion is not None:
        accion()


def vigilante_arranca(pid: int = 4242) -> None:
    """Apunta el pid, como hace `watch_loop` nada más empezar."""
    penwatch.write_json(penwatch.STATE_FILE, {"watcher_pid": pid, "started": "ahora"})
    VIVOS.add(pid)


penwatch.time = SimpleNamespace(monotonic=lambda: ahora[0], sleep=dormir)
orden: list[list[str]] = []


def pedir_arranque(ok=True):
    """Devuelve un `run_quiet` que apunta la orden y contesta como `schtasks`."""
    def run(cmd):
        """Apunta `cmd` y devuelve el resultado de mentira."""
        orden.append(cmd)
        return SimpleNamespace(returncode=0 if ok else 1, stdout="",
                               stderr="" if ok else "acceso denegado")
    return run


def reiniciar() -> None:
    """Deja el equipo como recién instalado: sin pid y con el reloj a cero."""
    penwatch.write_json(penwatch.STATE_FILE, {"launched": True})
    VIVOS.clear()
    dormidas.clear()
    eventos.clear()
    orden.clear()
    ahora[0] = 0.0


reales = (penwatch.IS_WIN, penwatch.run_quiet)
penwatch.IS_WIN = True            # la ruta de schtasks; el `pid_alive` de Windows va sustituido
try:
    penwatch.run_quiet = pedir_arranque()

    # El vigilante tarda unos sondeos en escribir su pid: «arrancado», y `status`
    # ya lo ve vivo.
    reiniciar()
    eventos[3] = vigilante_arranca
    mensaje = penwatch.start_now({})
    c("pide el arranque a la tarea", orden,
      [["schtasks", "/Run", "/TN", penwatch.TASK_NAME]])
    c("espera a que el vigilante aparezca antes de decir nada", len(dormidas), 3)
    c("y entonces dice que ha arrancado", mensaje, "Vigilante arrancado.")
    c("y `status` no lo ve parado", penwatch.watcher_alive(), True)

    # Ya estaba escrito cuando se mira (arranque instantáneo): no se espera.
    reiniciar()
    vigilante_arranca()
    c("si ya está vivo, no espera", (penwatch.start_now({}), dormidas),
      ("Vigilante arrancado.", []))

    # No aparece nunca: no se promete lo que no se sabe, y la espera tiene tope.
    reiniciar()
    mensaje = penwatch.start_now({})
    c("si no aparece, no dice «arrancado»", mensaje.startswith("Vigilante arrancado"),
      False)
    c.contains("sino que está pedido", mensaje, "Vigilante pedido")
    c.contains("y manda mirar `status`", mensaje, "status")
    c("la espera tiene tope",
      penwatch.START_WAIT_SECONDS <= sum(dormidas) < penwatch.START_WAIT_SECONDS + 1,
      True)

    # Un pid apuntado de un vigilante que ya no vive no cuenta.
    reiniciar()
    penwatch.write_json(penwatch.STATE_FILE, {"watcher_pid": 99})
    c("un pid que no vive no es un vigilante vivo", penwatch.watcher_alive(), False)
    penwatch.write_json(penwatch.STATE_FILE, {"watcher_pid": "no es un número"})
    c("ni un estado ilegible rompe nada", penwatch.watcher_alive(), False)

    # Si la tarea no se puede lanzar, no hay nada que esperar.
    reiniciar()
    penwatch.run_quiet = pedir_arranque(ok=False)
    mensaje = penwatch.start_now({})
    c("si la tarea no arranca, lo dice y no espera",
      (dormidas, "No he podido" in mensaje), ([], True))
finally:
    penwatch.IS_WIN, penwatch.run_quiet = reales

# La vía sin systemd ni tarea: lanza el proceso y espera igual.
lanzados: list[list[str]] = []


class _Popen:
    """`Popen` de mentira: apunta los argumentos y no lanza nada."""

    def __init__(self, args, **_kwargs):
        """Apunta los argumentos del lanzamiento."""
        lanzados.append(list(args))


reales = (penwatch.IS_WIN, penwatch.shutil.which, penwatch.subprocess.Popen)
penwatch.IS_WIN = False
penwatch.shutil.which = lambda nombre: None
penwatch.subprocess.Popen = _Popen
try:
    reiniciar()
    eventos[2] = vigilante_arranca
    mensaje = penwatch.start_now({"python_exe": "python-del-equipo"})
    c("sin systemd lanza `run` con su Python",
      [(orden_[0], orden_[-1]) for orden_ in lanzados], [("python-del-equipo", "run")])
    c("y también espera a que aparezca", (mensaje, len(dormidas)),
      ("Vigilante arrancado.", 2))
finally:
    penwatch.IS_WIN, penwatch.shutil.which, penwatch.subprocess.Popen = reales

# 3. desinstalar: dice lo que de verdad queda en el dispositivo
penwatch.time = time
CONTROL = str(penwatch.CONTROL_FILE)
MARCA = penwatch.VESTIBULE_MARKER


def raiz_con(*ficheros: str) -> Path:
    """Crea una raíz con esos ficheros, cada uno con el id, y la devuelve."""
    raiz = tmpdir("prdrive-raiz-")
    for nombre in ficheros:
        destino = raiz / nombre
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(f"id={ID}\n", encoding="utf-8")
    return raiz


def desinstala(cfg: dict, raices: list[Path]) -> str:
    """Corre `uninstall` con esa configuración y esas raíces.

    Returns:
        La última línea que imprime, que es la que habla del dispositivo.
    """
    penwatch.HOST_DIR.mkdir(parents=True, exist_ok=True)
    penwatch.write_json(penwatch.CONFIG_FILE, cfg)
    reales_ = (penwatch.candidate_roots, penwatch.unregister,
               penwatch.stop_running_watcher)
    penwatch.candidate_roots = lambda cfg_=None: list(raices)
    penwatch.unregister = lambda: []
    penwatch.stop_running_watcher = lambda: None
    salida = io.StringIO()
    try:
        with redirect_stdout(salida):
            rc = penwatch.cmd_uninstall(SimpleNamespace())
    finally:
        (penwatch.candidate_roots, penwatch.unregister,
         penwatch.stop_running_watcher) = reales_
    c("uninstall termina bien", rc, 0)
    c("y borra la carpeta del equipo", penwatch.HOST_DIR.exists(), False)
    return salida.getvalue().strip().splitlines()[-1]


# Sin cifrar: está el fichero de control, y es lo que queda.
plano = raiz_con(CONTROL, str(penwatch.STRUCT_MARKER))
frase = desinstala({"device_id": ID}, [plano])
c.contains("sin cifrar: dice que sigue el fichero de control", frase, CONTROL)
c("sin cifrar: y no habla de la marca del vestíbulo", MARCA in frase, False)

# Cifrado: fuera lo reconoce la marca, y el fichero de control está dentro.
fisica = raiz_con(MARCA)
(fisica / penwatch.CONTAINER_FILE).write_bytes(b"x")
frase = desinstala({"device_id": ID}, [fisica])
c.contains("cifrado: dice que queda la marca del vestíbulo", frase, MARCA)
c.contains("cifrado: y que el fichero de control está dentro del contenedor", frase,
           "dentro del contenedor")
c.contains("cifrado: nombra dónde está la marca", frase, str(fisica))

# Con el contenedor abierto se ven las dos raíces: la física y el volumen montado.
frase = desinstala({"device_id": ID}, [fisica, plano])
c.contains("cifrado y abierto: sigue siendo la marca lo que queda fuera", frase, MARCA)

# Sin el dispositivo a la vista no se sabe cuál es: se dice neutro, con las dos.
frase = desinstala({"device_id": ID}, [])
c.contains("sin dispositivo: nombra el fichero de control", frase, CONTROL)
c.contains("sin dispositivo: y la marca del vestíbulo", frase, MARCA)
c.contains("sin dispositivo: y cuándo es cada uno", frase, "si es cifrado")

# Sin configuración (nunca instalado aquí), tampoco falla.
frase = desinstala({}, [])
c.contains("sin id, lo mismo, neutro", frase, "Desinstalado.")

raise SystemExit(c.report())
