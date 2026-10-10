#!/usr/bin/env python3
"""Los tiempos de las ventanas con `PRDRIVE_PERF` (`ui/__init__.py`: los `perf_*`).

Con la variable apagada no se escribe nada, no se programa nada en Tk y no se
arranca ningún hilo. Encendida, cada marca acaba en `logs/perf.log` (o en
`equipo/perf.log` si es de un host) y el hilo, o el cierre, lo vuelca. Aquí se prueba:

- lo apagado: ni fichero, ni temporizador, ni hilo, ni inicio guardado;
- lo encendido: el formato de la línea, `vez`, las carpetas que faltan, una ruta
  que es un fichero, el tope del diario, el texto no ASCII, el inicio del proceso,
  un lote que no puede resolver su ruta (sin perder el resto) y que `con_perf`
  restaura lo suyo aunque el volcado falle;
- el hilo que vuelca cada segundo y el cierre (`atexit`), en procesos hijos;
- en Tk: que el inicio se gasta al cerrar, que el cierre es un temporizador que
  no corre dentro de `update_idletasks()` (ni, por tanto, su `update()` de drenaje),
  que la marca acaba DESPUÉS de los `<Configure>` del cambio (el drenaje
  con `update()`), que sobrevive a destruir la ventana, que `mostrar()` cierra el
  momento del diálogo y solo el suyo, que `perf_al_pintar` reenvía `host=` y el
  detalle, y que `apply()` mide su primera llamada, una sola vez.

La parte de Tk se salta sin pantalla o sin `tkinter`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from _harness import REPO, Checks, sandbox

import _perf

c = Checks("PRDRIVE_PERF: tiempos de las ventanas")

import ui  # noqa: E402
from common import equipo, model, store  # noqa: E402

errores: list[str] = []


def hijo(codigo: str, *args: str) -> subprocess.CompletedProcess:
    """Corre `codigo` en otro proceso Python, con `PRDRIVE_PERF=1` y la raíz del proyecto.

    Args:
        codigo: El programa, que recibe `args` en `sys.argv[1:]`.
        *args: Los argumentos del programa (aquí, la carpeta de `logs/` que usa).

    Returns:
        El resultado de `subprocess.run`, con la salida capturada.
    """
    entorno = dict(os.environ, PRDRIVE_PERF="1")
    return subprocess.run([sys.executable, "-c", codigo, *args], cwd=REPO, env=entorno,
                          capture_output=True, text=True, timeout=60)


# Programa del hijo que sale normalmente: la única escritura posible es la del cierre (`atexit`).
SALIDA_NORMAL = """
import sys
from pathlib import Path
from common import model
import ui
model.LOG_DIR = Path(sys.argv[1])
ui.perf_marca('salida', 3.0)
"""

# Programa del hijo que no sale: lo único que puede escribir la línea es el hilo, cada segundo.
HILO_SIN_SALIR = """
import os, sys, time
from pathlib import Path
from common import model
import ui
model.LOG_DIR = Path(sys.argv[1])
ui.perf_marca('hilo', 4.0)
ruta = model.LOG_DIR / 'perf.log'
limite = time.monotonic() + 10
while time.monotonic() < limite:
    if ruta.is_file() and 'hilo' in ruta.read_text(encoding='utf-8'):
        print('escrito', flush=True)
        break
    time.sleep(0.05)
os._exit(0)
"""


with sandbox() as raiz_prueba:
    tmp = Path(raiz_prueba)

    # 1. Apagado: ni fichero, ni hilo, ni inicio guardado.
    os.environ.pop("PRDRIVE_PERF", None)
    hilos = threading.active_count()
    with _perf.con_perf(tmp / "apagado", activo=False) as t:
        ui.perf_empezar("x")
        ui.perf_marca("x", 1.0, n=1)
        ui.perf_volcar()
    c("apagado: ni diario del dispositivo ni del equipo",
      ((t / "logs" / "perf.log").exists(), (t / "equipo" / "perf.log").exists()), (False, False))
    c("apagado: no arranca ningún hilo", threading.active_count(), hilos)
    c("apagado: perf_empezar no guarda el inicio", "x" in ui._INICIOS, False)

    # 2. Encendido: el formato, `vez`, y la carpeta que falta.
    with _perf.con_perf(tmp / "encendido") as t:
        ui.perf_marca("x", 12.34, n=3)
        _perf.vaciar()
        c("encendido: una línea «<momento> <ms> ms vez=1 <datos>», y se crea la carpeta",
          ([linea.split(" ", 2)[2] for linea in _perf.lineas(t, "x")], (t / "logs").is_dir()),
          (["x 12.3 ms vez=1 n=3"], True))
        ui.perf_marca("x", 1.0)
        _perf.vaciar()
        c("encendido: la segunda vez del mismo momento lleva vez=2",
          [linea.split(" ", 2)[2] for linea in _perf.lineas(t, "x")][1:], ["x 1.0 ms vez=2"])

    # 3. Un diario que no puede ser carpeta: no lanza nada y no escribe.
    base = tmp / "fichero"
    base.mkdir()
    (base / "logs").write_text("no es una carpeta", encoding="utf-8")
    try:
        with _perf.con_perf(base) as t:
            ui.perf_marca("x", 1.0)
            _perf.vaciar()
        ok = (base / "logs").read_text(encoding="utf-8") == "no es una carpeta"
    except Exception as e:                           # noqa: BLE001 — es lo que se prueba
        ok = f"{type(e).__name__}: {e}"
    c("una LOG_DIR que es un fichero: sin excepción, el fichero queda como estaba", ok, True)

    # 4. Lo del equipo va a su diario, y no al del dispositivo.
    with _perf.con_perf(tmp / "equipo") as t:
        ui.perf_marca("h", 2.0, host=True)
        _perf.vaciar()
        c("host=True: va al diario del equipo, que se crea, y no al del dispositivo",
          (len(_perf.lineas(t, "h", host=True)), len(_perf.lineas(t, "h"))), (1, 0))

    # 5. El tope del diario: se recorta antes de cada lote.
    previo_tope = store.DIARIO_TOPE
    store.DIARIO_TOPE = 2048
    try:
        with _perf.con_perf(tmp / "tope") as t:
            for i in range(400):
                ui.perf_marca("m", float(i), n=i)
                _perf.vaciar()
            tamano = (t / "logs" / "perf.log").stat().st_size
            ultima = _perf.lineas(t, "m")[-1]
    finally:
        store.DIARIO_TOPE = previo_tope
    c("el tope: el diario no pasa del tope más una línea, y su última línea es la última marca",
      (tamano <= 2048 + 120, ultima.split()[-1]), (True, "n=399"))

    # 6. Texto no ASCII: una línea, sin error.
    with _perf.con_perf(tmp / "unicode") as t:
        ui.perf_marca("u", 1.0, t="ñ€✓")
        _perf.vaciar()
        c("un dato no ASCII: una línea, con sus caracteres",
          [linea.split(" ", 2)[2] for linea in _perf.lineas(t, "u")], ["u 1.0 ms vez=1 t=ñ€✓"])

    # 7. Un lote cuya ruta no se resuelve no hace perder el del dispositivo, y el volcado no lanza.
    class RutaRota:
        """Un `equipo.DIR` que no se puede usar: dividirlo lanza, como un HOME sin resolver."""

        def __truediv__(self, _otra):
            raise RuntimeError("sin HOME")

    with _perf.con_perf(tmp / "ruta-rota") as t:
        ui.perf_marca("eq", 2.0, host=True)          # el lote del equipo va primero
        ui.perf_marca("dev", 1.0)
        equipo.DIR = RutaRota()
        try:
            ui.perf_volcar()
            volcado = "sin error"
        except Exception as e:                       # noqa: BLE001 — es lo que se prueba
            volcado = type(e).__name__
    c("una ruta del equipo que no se resuelve: el volcado no lanza y el lote del dispositivo se escribe",
      (volcado, len(_perf.lineas(t, "dev"))), ("sin error", 1))

    # 8. con_perf restaura sus rutas y su entorno aunque el volcado de salida lance.
    antes_con_perf = (model.LOG_DIR, model.STATE_DIR, equipo.DIR, os.environ.get("PRDRIVE_PERF"))
    volcar_original = ui.perf_volcar

    def volcado_roto() -> None:
        """Un volcado que falla, para ver que `con_perf` se restaura igual."""
        raise RuntimeError("roto")

    ui.perf_volcar = volcado_roto
    try:
        with _perf.con_perf(tmp / "restaura"):
            pass
    except RuntimeError:
        pass
    finally:
        ui.perf_volcar = volcar_original
    c("con_perf: si el volcado lanza, restaura rutas y entorno igualmente",
      (model.LOG_DIR, model.STATE_DIR, equipo.DIR, os.environ.get("PRDRIVE_PERF")), antes_con_perf)

    # 9. El hilo y el cierre, en procesos hijos: sin llamar a perf_volcar a mano, la línea llega.
    r = hijo(SALIDA_NORMAL, str(tmp / "salida" / "logs"))
    c("el cierre del proceso (atexit) escribe la marca pendiente",
      (r.returncode, [linea.split(" ", 2)[2] for linea in _perf.lineas(tmp / "salida", "salida")]),
      (0, ["salida 3.0 ms vez=1"]))
    r = hijo(HILO_SIN_SALIR, str(tmp / "hilo" / "logs"))
    c("el hilo vuelca cada segundo: la marca llega al diario sin salir del proceso",
      ("escrito" in r.stdout, len(_perf.lineas(tmp / "hilo", "hilo"))), (True, 1))

    # 10. El inicio del proceso (Linux y Windows): más que lo que lleva la propia prueba.
    if os.name == "nt" or sys.platform.startswith("linux"):
        antes = time.perf_counter()
        time.sleep(0.05)
        desde = ui.perf_desde_inicio()
        c("perf_desde_inicio (Linux y Windows): un número mayor que el tiempo que lleva esta prueba",
          desde is not None and desde > (time.perf_counter() - antes) * 1000, True)
    else:
        print("  (saltado) perf_desde_inicio: solo se mide en Linux y en Windows")

try:
    import tkinter as tk
    raiz = tk.Tk()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())


def anotar_errores(r) -> None:
    """Apunta las excepciones de los manejadores de Tk de `r` en vez de imprimirlas."""
    r.report_callback_exception = (
        lambda tipo, valor, _tb: errores.append(f"{tipo.__name__}: {valor}"))


@contextmanager
def contar_temporizadores(r):
    """Cuenta los `after` que se programan en la raíz `r` mientras dura el bloque.

    El cierre de `perf_al_pintar` es un temporizador: cada `after` programado en `r`
    añade una entrada, y la lista queda vacía si no se programó ninguno.

    Args:
        r: La raíz de Tk.

    Yields:
        La lista de los programados (los argumentos de cada `after`).
    """
    programados: list = []
    original = r.after

    def contar(*args, **kwargs):
        """Anota la programación y la deja pasar."""
        programados.append(args)
        return original(*args, **kwargs)

    r.after = contar
    try:
        yield programados
    finally:
        del r.after


def llega(t: Path, momento: str, host: bool = False) -> bool:
    """Vacía la cola de marcas y dice si `momento` ya tiene línea en el diario de `t`.

    Args:
        t: La carpeta que se le dio a `con_perf()`.
        momento: El nombre del momento.
        host: Si se mira el diario del equipo.

    Returns:
        `True` si ya hay al menos una línea de ese momento.
    """
    _perf.vaciar()
    return bool(_perf.lineas(t, momento, host=host))


def hasta(r, cumple, limite: float = 2.0) -> bool:
    """Procesa eventos de Tk hasta que `cumple()` sea cierto, como mucho `limite` segundos.

    Las marcas llegan como temporizadores: un `update()` las procesa, y entre vueltas
    se duerme un poco para no girar en vacío mientras la marca no llega.

    Args:
        r: La raíz de Tk.
        cumple: Función sin argumentos que dice si ya se puede seguir.
        limite: Segundos máximos de espera, para que una marca que no llega no cuelgue la prueba.

    Returns:
        `True` si `cumple()` se cumplió a tiempo.
    """
    fin = time.monotonic() + limite
    while not cumple():
        if time.monotonic() >= fin:
            return False
        r.update()
        time.sleep(0.005)
    return True


anotar_errores(raiz)

with sandbox() as raiz_tk:
    tmp = Path(raiz_tk)

    # 11. Apagado: no se programa nada en la raíz; encendido, un temporizador.
    with contar_temporizadores(raiz) as apagado:
        with _perf.con_perf(tmp / "tk-apagado", activo=False):
            ui.perf_al_pintar(raiz, "x", time.perf_counter())
    with contar_temporizadores(raiz) as encendido:
        with _perf.con_perf(tmp / "tk-encendido") as t:
            ui.perf_al_pintar(raiz, "x", time.perf_counter())
            hasta(raiz, lambda: llega(t, "x"))      # que el cierre corra dentro del bloque
    c("apagado: no se programa ningún temporizador; encendido, uno de after(0)",
      (len(apagado), len(encendido), [a[0] for a in encendido]), (0, 1, [0]))

    # 12. El inicio se gasta al cerrar: un segundo cierre sin perf_empezar no programa ni escribe.
    with _perf.con_perf(tmp / "consumo") as t, contar_temporizadores(raiz) as programados:
        ui.perf_empezar("z")
        ui.perf_al_pintar(raiz, "z")
        hasta(raiz, lambda: llega(t, "z"))
        ui.perf_al_pintar(raiz, "z")
        raiz.update()
        _perf.vaciar()
        c("perf_empezar y dos cierres: una línea y un temporizador; el segundo cierre no tiene inicio",
          (len(_perf.lineas(t, "z")), len(programados), [a[0] for a in programados]), (1, 1, [0]))
    with _perf.con_perf(tmp / "sin-inicio") as t, contar_temporizadores(raiz) as programados:
        ui.perf_al_pintar(raiz, "nunca")
        raiz.update()
        _perf.vaciar()
        c("perf_al_pintar sin inicio (ni t0 ni perf_empezar): no programa ni escribe",
          (len(programados), _perf.lineas(t, "nunca")), (0, []))

    # 13. El drenaje: la marca cierra después de los <Configure> que el cambio provoca en los
    #     widgets que mueve. Sin el update() del cierre, la marca va antes que ellos.
    def tabla(padre):
        """Una rejilla de 51 filas: devuelve la etiqueta de la esquina, la que cambia, y otra de la columna que se mueve."""
        marco = tk.Frame(padre)
        marco.pack()
        for fila in range(51):
            tk.Label(marco, text="x").grid(row=fila, column=0)
            tk.Label(marco, text="fila").grid(row=fila, column=1)
        return marco.grid_slaves(row=0, column=0)[0], marco.grid_slaves(row=25, column=1)[0]

    largo = "texto largo que empuja la columna " * 3
    cambia, movida = tabla(raiz)
    orden: list[str] = []
    for widget in (cambia, movida):                  # la que cambia de tamaño y la que se mueve
        widget.bind("<Configure>", lambda _e: orden.append("configure"), add="+")
    marca_real = ui.perf_marca

    def marca_en_orden(momento, ms, **detalle):
        """Anota el orden en que llega la marca y deja la real."""
        orden.append("marca")
        marca_real(momento, ms, **detalle)

    for texto in (largo, "x", largo, "x"):          # calentar la fuente y el diseño
        cambia.config(text=texto)
        raiz.update()
    ui.perf_marca = marca_en_orden
    try:
        with _perf.con_perf(tmp / "drenaje") as t:
            orden.clear()
            inicio = time.perf_counter()
            cambia.config(text=largo)
            ui.perf_al_pintar(cambia, "drenaje", inicio)
            # El temporizador ya vence y el redibujado sigue pendiente: este update() corre
            # primero el cierre, así que solo el drenaje lo pone detrás de los <Configure>.
            time.sleep(0.005)
            raiz.update()
            hasta(raiz, lambda: llega(t, "drenaje"))
            lineas_drenaje = len(_perf.lineas(t, "drenaje"))
    finally:
        ui.perf_marca = marca_real
    c("el drenaje: la marca llega después de los <Configure> del cambio, y deja una línea",
      (orden.count("marca"), bool(orden) and orden[-1] == "marca" and "configure" in orden, lineas_drenaje),
      (1, True, 1))

    # 14. Destruir la ventana antes de que pinte: sin error de Tk, y la marca se escribe.
    with _perf.con_perf(tmp / "destruir") as t:
        dlg = tk.Toplevel(raiz)
        ui.perf_al_pintar(dlg, "destruir", time.perf_counter())
        dlg.destroy()
        hasta(raiz, lambda: llega(t, "destruir"))
        c("destruir antes del pintado: sin error de Tk y una línea",
          (errores, len(_perf.lineas(t, "destruir"))), ([], 1))

    # 15. mostrar(): el momento que declara el diálogo, una vez; sin el atributo, ninguno.
    from ui import tk as uitk

    with _perf.con_perf(tmp / "mostrar") as t:
        dlg = tk.Toplevel(raiz)
        tk.Label(dlg, text="hola").pack()
        ui.perf_empezar("y")
        dlg.perf_momento = "y"
        raiz.after(50, dlg.destroy)
        uitk.mostrar(dlg)
        # Otro diálogo sin atributo, con un inicio "y" abierto: mostrar() no debe cerrarlo.
        ui.perf_empezar("y")
        otro = tk.Toplevel(raiz)
        tk.Label(otro, text="hola").pack()
        raiz.after(50, otro.destroy)
        uitk.mostrar(otro)
        _perf.vaciar()
        c("mostrar: el momento del diálogo se cierra una sola vez; sin atributo, nada y el inicio sigue abierto",
          (len(_perf.lineas(t, "y")), "y" in ui._INICIOS), (1, True))
        ui._INICIOS.pop("y", None)

    # 16. perf_al_pintar reenvía `host=` y el detalle a la marca: va al equipo, con su dato.
    with _perf.con_perf(tmp / "reenvio") as t:             # un momento nuevo: su vez empieza en 1
        ui.perf_al_pintar(raiz, "reenvio", time.perf_counter(), host=True, n=2)
        hasta(raiz, lambda: llega(t, "reenvio", host=True))
        en_equipo = _perf.lineas(t, "reenvio", host=True)
        c("perf_al_pintar: host= y el detalle llegan a la línea del equipo (n=2), no a la del dispositivo",
          (len(en_equipo), len(_perf.lineas(t, "reenvio")), bool(en_equipo) and en_equipo[0].endswith(" vez=1 n=2")),
          (1, 0, True))

    # 17. apply(): la primera llamada del proceso mide apply-main, y las siguientes no.
    from ui import theme

    with _perf.con_perf(tmp / "apply") as t:
        theme.apply(raiz)
        theme.apply(raiz)
        _perf.vaciar()
        c("apply: apply-main una sola vez para dos llamadas",
          len(_perf.lineas(t, "apply-main")), 1)

    # 18. Una ventana de host (quien = wizard) anota su apply en el diario del equipo.
    theme._apply_medido = False
    ui.perf_quien = "wizard"
    try:
        with _perf.con_perf(tmp / "apply-host") as t:
            theme.apply(raiz)
            _perf.vaciar()
            c("apply de host: apply-wizard va al diario del equipo, no al del dispositivo",
              (len(_perf.lineas(t, "apply-wizard", host=True)), len(_perf.lineas(t, "apply-wizard"))),
              (1, 0))
    finally:
        ui.perf_quien = "main"

    # 19. Una marca no se cierra dentro de un update_idletasks: el cierre es un temporizador,
    #     y solo el bucle de eventos (o un update() completo) lo corre.
    with _perf.con_perf(tmp / "idletasks") as t:
        ui.perf_empezar("x")
        ui.perf_al_pintar(raiz, "x")
        raiz.update_idletasks()
        _perf.vaciar()
        antes = len(_perf.lineas(t, "x"))
        hasta(raiz, lambda: llega(t, "x"))
        c("una marca no se cierra dentro de un update_idletasks: cierra con el bucle de eventos, una sola línea",
          (antes, len(_perf.lineas(t, "x"))), (0, 1))

    # 20. El drenaje tampoco corre dentro de update_idletasks: un temporizador de prueba que
    #     vence a la vez no corre hasta que el bucle de eventos lo procesa.
    with _perf.con_perf(tmp / "idletasks-drenaje") as t:
        corrio: list[bool] = []
        ui.perf_empezar("w")
        ui.perf_al_pintar(raiz, "w")
        raiz.after(0, lambda: corrio.append(True))
        raiz.update_idletasks()
        c("el drenaje no corre dentro de update_idletasks: el temporizador de prueba no ha corrido",
          corrio, [])
        hasta(raiz, lambda: llega(t, "w") and bool(corrio))
        c("con el bucle de eventos corren los dos: el temporizador de prueba y la marca",
          (corrio, len(_perf.lineas(t, "w"))), ([True], 1))

raiz.destroy()
sys.exit(c.report())
