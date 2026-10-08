#!/usr/bin/env python3
"""Los logs del dispositivo no crecen sin fin.

- **`logs/`**: una pasada que falla deja un fichero y nada los quitaba. Se
  conservan los `LOGS_POR_PAREJA` más nuevos de cada pareja (por la fecha del
  nombre, no por la mtime), sin tocar los de otra pareja cuyo nombre empiece
  igual, y sin que un fallo al podar rompa el guardado del log.
- **`state/daemon.log`**: el diario del servicio (runsync) y el del agente
  pasan de `store.DIARIO_TOPE` y se quedan con las últimas
  `store.DIARIO_QUEDAN` líneas.
"""

import os
import sys
from pathlib import Path

from _harness import Checks, sandbox, tmpdir

import _agente_falso as F
import agente
import runsync
import sync
from common import model, store

c = Checks("logs y diarios acotados")
F.preparar()


def hacer_log(nombre: str, sello: str, n: int | None = None) -> Path:
    """Crea en `logs/` el log de una pasada con ese sello."""
    sufijo = f"_{n}" if n is not None else ""
    ruta = model.LOG_DIR / f"{nombre}_{sello}{sufijo}.log"
    ruta.write_text("x\n", encoding="utf-8")
    return ruta


def sellos(nombre: str) -> list[str]:
    """Los logs de `logs/` de una pareja, por nombre (los sellos empiezan por 2026)."""
    return sorted(p.name for p in model.LOG_DIR.glob(f"{nombre}_2026*.log"))


with sandbox():
    # 25 logs de `a`, uno por segundo: la mtime es la de ahora para todos, así
    # que solo el sello del nombre dice cuál es más nuevo.
    for i in range(25):
        hacer_log("a", f"20260101_0000{i:02d}")
    sync.podar_logs("a")
    c("quedan los 20 más nuevos", len(sellos("a")), sync.LOGS_POR_PAREJA)
    c("  y son los de los sellos más altos",
      sellos("a"), [f"a_20260101_0000{i:02d}.log" for i in range(5, 25)])

with sandbox():
    for i in range(25):
        hacer_log("a", f"20260101_0000{i:02d}")
    for i in range(3):
        hacer_log("a_b", f"20260101_0000{i:02d}")
    sync.podar_logs("a")
    c("podar a no toca los de a_b", len(sellos("a_b")), 3)
    c("  y a se queda en su tope", len(sellos("a")), sync.LOGS_POR_PAREJA)

with sandbox():
    # el sufijo `_N` de un reintento dentro del mismo segundo cuenta como un
    # entero: `_10` es más nuevo que `_9`, aunque como texto sea menor.
    for i in range(sync.LOGS_POR_PAREJA - 1):
        hacer_log("a", f"20260101_0000{i:02d}")
    hacer_log("a", "20260102_000000")
    hacer_log("a", "20260102_000000", 9)
    hacer_log("a", "20260102_000000", 10)
    sync.podar_logs("a")
    quedan = sellos("a")
    c("el reintento _10 es más nuevo que _9", "a_20260102_000000_10.log" in quedan
      and "a_20260102_000000_9.log" in quedan, True)
    c("  y se va el más viejo", "a_20260101_000000.log" in quedan, False)

with sandbox():
    # el orden es el del nombre: un log viejo tocado ahora no se salva
    for i in range(sync.LOGS_POR_PAREJA + 2):
        hacer_log("a", f"20260101_0000{i:02d}")
    viejo = model.LOG_DIR / "a_20260101_000000.log"
    os.utime(viejo, None)
    sync.podar_logs("a")
    c("la mtime no manda: el log viejo se va aunque se haya tocado ahora",
      viejo.exists(), False)

with sandbox():
    # lo que no es un log de pasada no se toca
    hacer_log("a", "20260101_000001")
    ajeno = model.LOG_DIR / "a_notas.log"
    ajeno.write_text("x\n", encoding="utf-8")
    sync.podar_logs("a")
    c("un fichero que no es un log de pasada se queda", ajeno.exists(), True)
    c("podar sin pasar del tope no borra nada", len(sellos("a")), 1)
    sync.podar_logs("no-existe")
    c("podar una pareja sin logs no hace nada", (len(sellos("a")), ajeno.exists()), (1, True))

with sandbox():
    # nunca lanza: ni con un `logs/` que no se lista ni con un fichero que no se borra
    model.LOG_DIR.rmdir()
    sync.podar_logs("a")
    c("sin carpeta de logs, podar no lanza", True, True)
    model.LOG_DIR.mkdir()
    for i in range(sync.LOGS_POR_PAREJA + 3):
        hacer_log("a", f"20260101_0000{i:02d}")
    borrar_real = Path.unlink

    def unlink_roto(self, missing_ok=False):
        """Un dispositivo que no deja borrar."""
        raise OSError(30, "Read-only file system")

    Path.unlink = unlink_roto
    try:
        sync.podar_logs("a")
        c("un fichero que no se borra no rompe la poda", True, True)
    finally:
        Path.unlink = borrar_real

with sandbox():
    # keep_log poda después de guardar el suyo
    for i in range(sync.LOGS_POR_PAREJA):
        hacer_log("a", f"20260101_0000{i:02d}")
    tmp = sync.temp_log("a")
    tmp.write_text("fallo\n", encoding="utf-8")
    final = sync.keep_log("a", tmp)
    c("keep_log guarda el log nuevo", final.parent == model.LOG_DIR and final.exists(), True)
    c("  y deja los LOGS_POR_PAREJA más nuevos", len(sellos("a")), sync.LOGS_POR_PAREJA)
    c("  entre ellos, el que acaba de guardar", final.name in sellos("a"), True)

    # si el movimiento falla, no se poda: el log se queda en el temporal
    antes = sellos("a")
    movido = sync.shutil.move

    def mover_roto(origen, destino):
        """Un dispositivo que desaparece a mitad de la copia."""
        raise OSError(5, "Input/output error")

    sync.shutil.move = mover_roto
    try:
        tmp2 = sync.temp_log("a")
        tmp2.write_text("fallo\n", encoding="utf-8")
        devuelto = sync.keep_log("a", tmp2)
    finally:
        sync.shutil.move = movido
    c("si no se pudo mover, devuelve el temporal", devuelto, tmp2)
    c("  y no ha podado nada", sellos("a"), antes)
    tmp2.unlink(missing_ok=True)

with sandbox():
    # un reloj atrasado (o un dispositivo que viaja a otra zona horaria) hace
    # que el log recién guardado tenga un sello MÁS VIEJO que los que ya había:
    # la poda no puede borrar justo el log del fallo que se está mirando
    for i in range(sync.LOGS_POR_PAREJA):
        hacer_log("a", f"20990101_0000{i:02d}")
    tmp = sync.temp_log("a")
    tmp.write_text("fallo\n", encoding="utf-8")
    final = sync.keep_log("a", tmp)
    c("con un reloj atrasado, el log recién guardado existe", final.exists(), True)
    c("  y la pareja se queda en LOGS_POR_PAREJA ficheros",
      len(list(model.LOG_DIR.glob("a_*.log"))), sync.LOGS_POR_PAREJA)
    c("  sin el más viejo de los anteriores", (model.LOG_DIR / "a_20990101000000.log").exists(),
      False)

with sandbox():
    # `conservar` no se borra nunca y no cuenta en el ranking: del resto quedan
    # LOGS_POR_PAREJA - 1
    for i in range(sync.LOGS_POR_PAREJA + 4):
        hacer_log("a", f"20260101_0000{i:02d}")
    guardado = hacer_log("a", "20250101_000000")
    sync.podar_logs("a", guardado)
    c("podar con `conservar` deja ese log", guardado.exists(), True)
    c("  y en total LOGS_POR_PAREJA", len(list(model.LOG_DIR.glob("a_*.log"))),
      sync.LOGS_POR_PAREJA)
    c("  y de los demás, los más nuevos",
      sellos("a"), [f"a_20260101_0000{i:02d}.log" for i in range(5, sync.LOGS_POR_PAREJA + 4)])

# --- el diario del servicio y el del agente

c("el tope del diario son 256 KB", store.DIARIO_TOPE, 256 * 1024)
c("  y se quedan 300 líneas", store.DIARIO_QUEDAN, 300)
c("runsync ya no guarda un tope suyo", hasattr(runsync, "DLOG_MAX_BYTES"), False)

ruta = tmpdir("prdrive-diario-") / "daemon.log"
store.recortar_diario(ruta)
c("recortar un diario que no existe no hace nada ni crea nada", ruta.exists(), False)

ruta.write_text("".join(f"linea {i}\n" for i in range(1000)), encoding="utf-8")
antes = ruta.read_bytes()
store.recortar_diario(ruta)
c("por debajo del tope no se reescribe", ruta.read_bytes(), antes)

ruta.write_text("".join(f"linea {i:06d} " + "x" * 80 + "\n" for i in range(3000)),
                encoding="utf-8")
c("  (el diario de la prueba pasa del tope)", ruta.stat().st_size > store.DIARIO_TOPE, True)
store.recortar_diario(ruta)
lineas = ruta.read_text(encoding="utf-8").splitlines()
c("pasado el tope se queda con las últimas 300 líneas", len(lineas), store.DIARIO_QUEDAN)
c("  las más nuevas", lineas[-1].startswith("linea 002999"), True)
c("  empezando por la 2700", lineas[0].startswith("linea 002700"), True)
c("  sin dejar un temporal", sorted(p.name for p in ruta.parent.iterdir()), ["daemon.log"])

# lo que no se puede leer ni reescribir no lanza
store.recortar_diario(ruta.parent)
c("recortar algo que no es un fichero no lanza", True, True)

# un diario enorme: solo se mira su cola (DIARIO_TOPE bytes), no el fichero entero
grande = tmpdir("prdrive-grande-") / "daemon.log"
cola = [f"cola {i:06d} " + "x" * 80 for i in range(store.DIARIO_QUEDAN)]
grande.write_bytes(b"basura sin saltos de linea " * (4 * 1024 * 1024 // 27)
                   + "\n".join(["linea partida"] + cola).encode("utf-8") + b"\n")
c("  (el diario enorme de la prueba pasa del tope)",
  grande.stat().st_size > 8 * store.DIARIO_TOPE, True)
store.recortar_diario(grande)
lineas = grande.read_text(encoding="utf-8").splitlines()
c("un diario enorme acaba con sus últimas 300 líneas", lineas[-store.DIARIO_QUEDAN:], cola)
c("  y no pasa de DIARIO_TOPE", grande.stat().st_size <= store.DIARIO_TOPE, True)

# 400 líneas de 2 KB: las últimas 300 pesarían más que el tope
largas = [f"larga {i:04d} " + "y" * 2040 for i in range(400)]
grande.write_text("\n".join(largas) + "\n", encoding="utf-8")
c("  (400 líneas de 2 KB pasan del tope)", grande.stat().st_size > store.DIARIO_TOPE, True)
store.recortar_diario(grande)
lineas = grande.read_text(encoding="utf-8").splitlines()
c("con líneas muy largas el diario recortado tampoco pasa de DIARIO_TOPE",
  grande.stat().st_size <= store.DIARIO_TOPE, True)
c("  se queda con las últimas líneas, enteras (la que cortaba la ventana se descarta)",
  (len(lineas) > 0, lineas == largas[-len(lineas):]), (True, True))

# una sola línea más larga que el tope no deja nada que valga: queda vacío, sin lanzar
grande.write_bytes(b"z" * (2 * store.DIARIO_TOPE))
store.recortar_diario(grande)
c("una línea más larga que el tope deja el diario vacío", grande.stat().st_size, 0)

# un FIFO llamado daemon.log no cuelga la apertura (O_NONBLOCK): fstat lo rechaza
if not hasattr(os, "mkfifo"):
    print("  (saltado) FIFO: este sistema no tiene os.mkfifo")
else:
    import threading

    tuberia = tmpdir("prdrive-fifo-") / "daemon.log"
    os.mkfifo(tuberia)
    hilo = threading.Thread(target=store.recortar_diario, args=(tuberia,), daemon=True)
    hilo.start()
    hilo.join(5)
    c("un FIFO llamado daemon.log no deja colgado el recorte", hilo.is_alive(), False)

# un daemon.log que es un enlace a un fichero de fuera no se lee: sus últimas
# líneas acabarían copiadas en el diario del dispositivo
fuera = tmpdir("prdrive-fuera-")
ajeno = fuera / "secreto.log"
ajeno.write_text("".join(f"secreto {i:06d} " + "x" * 80 + "\n" for i in range(3000)),
                 encoding="utf-8")
original = ajeno.read_bytes()
unidad = tmpdir("prdrive-unidad-")
enlazado = unidad / "daemon.log"
if os.name == "nt":
    print("  (saltado) enlaces: Windows pide un permiso para crearlos y no tiene O_NOFOLLOW")
else:
    try:
        os.symlink(ajeno, enlazado)
    except (OSError, NotImplementedError):
        print("  (saltado) sin permiso para crear enlaces")
    else:
        c("  (el fichero de fuera pasa del tope)", ajeno.stat().st_size > store.DIARIO_TOPE, True)
        store.recortar_diario(enlazado)
        c("un diario que es un enlace no se recorta: el destino queda como estaba",
          ajeno.read_bytes(), original)
        c("  el enlace sigue siendo un enlace, no una copia de lo de fuera",
          enlazado.is_symlink(), True)
        c("  y no deja un temporal", sorted(p.name for p in unidad.iterdir()), ["daemon.log"])

# el diario de runsync
with sandbox():
    runsync.DLOG = model.STATE_DIR / "daemon.log"
    runsync.DLOG.write_text("".join(f"linea {i:06d} " + "x" * 80 + "\n" for i in range(3500)),
                            encoding="utf-8")
    runsync.dlog("nueva")
    lineas = runsync.DLOG.read_text(encoding="utf-8").splitlines()
    c("el diario de runsync se recorta y añade la suya",
      (len(lineas) <= store.DIARIO_QUEDAN + 1, lineas[-1].endswith("nueva")), (True, True))

# el diario del agente
raiz = F.unidad("d" * 32, parejas=("docs",))
diario = agente.estado_de(raiz) / "daemon.log"
diario.parent.mkdir(parents=True, exist_ok=True)
diario.write_text("".join(f"linea {i:06d} " + "x" * 80 + "\n" for i in range(3500)),
                  encoding="utf-8")
c("  (el diario del agente de la prueba pasa del tope)",
  diario.stat().st_size > store.DIARIO_TOPE, True)
agente.dlog(raiz, "hola")
lineas = diario.read_text(encoding="utf-8").splitlines()
c("el diario del agente se recorta", len(lineas) <= store.DIARIO_QUEDAN + 1, True)
c("  y añade la línea nueva", lineas[-1].endswith("hola"), True)

sys.exit(c.report())
