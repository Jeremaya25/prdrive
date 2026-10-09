#!/usr/bin/env python3
"""La ventana de una pasada sale primero y la pasada empieza después.

`output_window` construye y enseña su ventana y deja el `Popen` y el hilo que
lee la salida para el turno siguiente (`root.after(1, arrancar)`): lo que se ve
primero es la ventana, no el tiempo de lanzar el proceso. Aquí se comprueba:

- el orden: la ventana se enseña (`ensenar`) antes de que exista el proceso, por
  los tres caminos (sin bloquear, modal y con la raíz propia);
- cerrarla antes de que arranque no lanza nada, no corta nada y no deja el
  arranque pendiente; sin bloquear avisa una vez con el código 1;
- una orden que no se puede lanzar lo dice en la propia ventana (código 127),
  que sigue siendo utilizable («Guardar el log» guarda esa línea) y avisa al
  cerrarse con el 127;
- la ventana principal, con la ventana de salida de verdad, no se queda ocupada
  si la orden no se puede lanzar ni si la ventana se cierra antes de lanzarla.

Los cortes de una pasada ya en marcha (la X, la destrucción de la ventana, la
salida de la espera) están en `test_matar_arbol.py`.
"""

import functools
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from _harness import Checks, mkcfg, sandbox, tmpdir
from common import store, update

c = Checks("la ventana de la pasada sale antes que el proceso")

try:
    import _tkinter
    import tkinter as tk
    from tkinter import filedialog, ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from ui import tk as uitk  # noqa: E402

# Un `after` que sobrevive a su ventana no falla en Python: Tcl lo da por un
# error en segundo plano ("invalid command name") y se lo cuenta a `bgerror`.
# Aquí se recoge, para que cualquier arranque olvidado salga como fallo.
errores_tcl: list[str] = []
raiz.tk.createcommand("bgerror", errores_tcl.append)

ESPERA = 20.0             # segundos que se le dan a lo que debería ser inmediato
HOLA = [sys.executable, "-c", "print('hola')"]
"""Una orden que escribe una línea y acaba."""
NO_EXISTE = [str(Path(tempfile.gettempdir()) / "prdrive-no-existe" / "orden")]
"""Una orden que ningún sistema puede lanzar: `Popen` lanza `OSError`."""
ERROR_127 = "=== Terminado: ERROR (código 127) ==="
"""La última línea de una ventana cuya orden no se pudo lanzar."""


def recorrer(w):
    """Recorre los widgets que cuelgan de `w`, en profundidad."""
    pila = [w]
    while pila:
        x = pila.pop()
        yield x
        pila += list(x.winfo_children())


def esperar(condicion, espera: float = ESPERA) -> bool:
    """Mueve el bucle de eventos hasta que se cumple `condicion` o se acaba `espera`."""
    limite = time.monotonic() + espera
    while time.monotonic() < limite:
        raiz.update()
        if condicion():
            return True
        time.sleep(0.01)
    return False


def texto_de(ventana) -> str:
    """Devuelve lo que lleva escrito el `Text` de la ventana de salida."""
    return next(w for w in recorrer(ventana) if isinstance(w, tk.Text)).get("1.0", "end")


def boton(ventana, rotulo: str):
    """Devuelve el botón de la ventana con ese texto."""
    return next(w for w in recorrer(ventana)
                if isinstance(w, ttk.Button) and str(w.cget("text")) == rotulo)


def temporizadores() -> set:
    """Devuelve los `after` con plazo pendientes del intérprete (no los `after_idle`)."""
    return {t for t in raiz.tk.splitlist(raiz.tk.call("after", "info"))
            if raiz.tk.splitlist(raiz.tk.call("after", "info", t))[1] == "timer"}


def x_de_la_ventana(ventana) -> None:
    """Pulsa la X de la ventana: lo que Tk ejecuta con `WM_DELETE_WINDOW`."""
    ventana.tk.eval(ventana.protocol("WM_DELETE_WINDOW"))


def abrir(orden, **k):
    """Abre la ventana de salida sin bloquear, colgada de la raíz, y la devuelve.

    Returns:
        `(lo que devuelve output_window, la ventana nueva o None)`.
    """
    antes = set(raiz.winfo_children())
    valor = uitk.output_window("Prueba", orden, parent=raiz, modal=False, **k)
    nuevas = [w for w in raiz.winfo_children() if w not in antes]
    return valor, (nuevas[0] if nuevas else None)


def cerrar_cuando_acabe(antes: set, intentos: int = 1000) -> None:
    """Cierra la ventana modal nueva en cuanto ha dicho cómo acabó.

    Una espera modal no acaba sola: lo hace quien la cierra. Si la pasada no
    acaba nunca, la cierra a la fuerza para que la prueba falle en vez de
    colgarse.
    """
    nuevas = [w for w in raiz.winfo_children() if w not in antes]
    if nuevas and "Terminado" in texto_de(nuevas[0]):
        visto.append(texto_de(nuevas[0]))
        boton(nuevas[0], "Cerrar").invoke()
    elif intentos <= 0 and nuevas:
        nuevas[0].destroy()
    else:
        raiz.after(20, cerrar_cuando_acabe, antes, intentos - 1)


# Lo que la ventana hace, apuntado en orden. `ensenar` y `Popen` son los dos
# puntos de la prueba.
registro: list[str] = []
tras_ensenar: list = []            # qué hacer, en el turno siguiente, tras enseñar la ventana
visto: list[str] = []              # el texto de las ventanas modales antes de cerrarlas
cortes: list[int] = []
real_ensenar, real_popen, real_orden = uitk.ensenar, subprocess.Popen, uitk.orden_sync
real_matar, real_deiconify = store.matar_arbol, tk.Toplevel.deiconify


def ensenar_apuntando(ventana) -> None:
    """Enseña la ventana, lo apunta y programa lo que la prueba pide para después."""
    real_ensenar(ventana)
    registro.append("ensenar")
    for accion in tras_ensenar:
        ventana.after(0, functools.partial(accion, ventana))


def popen_apuntando(*a, **k):
    """Lanza el proceso de verdad y apunta que se ha lanzado una orden de la prueba.

    El tema también lanza procesos al aplicarse (la consulta del modo oscuro del
    sistema): no son los de la pasada y no se apuntan.
    """
    if a and a[0] in (HOLA, NO_EXISTE):
        registro.append("Popen")
    return real_popen(*a, **k)


uitk.ensenar = ensenar_apuntando
subprocess.Popen = popen_apuntando
store.matar_arbol = cortes.append
tk.Toplevel.deiconify = lambda self: None               # nada se enseña en un test
try:
    # sin bloquear: la ventana está y el proceso todavía no
    previos = temporizadores()
    recibido: list = []
    vuelta, ventana = abrir(HOLA, al_cerrar=recibido.append)
    c("sin bloquear vuelve enseguida", vuelta, None)
    c("  con la ventana enseñada y el proceso sin lanzar", registro, ["ensenar"])
    c("  su proceso aún no existe", ventana.proceso, None)
    c("  porque el arranque está programado para el turno siguiente",
      len(temporizadores() - previos), 1)
    c("al primer turno se lanza, ya con la ventana enseñada",
      esperar(lambda: ventana.proceso is not None), True)
    c("  en ese orden", registro, ["ensenar", "Popen"])
    c("  y el proceso es el `Popen` de verdad", isinstance(ventana.proceso, real_popen), True)
    c("la salida llega a la ventana y la pasada acaba bien",
      esperar(lambda: "Terminado: OK" in texto_de(ventana)), True)
    c("  con lo que escribió el proceso", "hola" in texto_de(ventana), True)
    boton(ventana, "Cerrar").invoke()
    raiz.update()
    c("al cerrarla avisa una vez, con el código de salida", recibido, [0])
    c("  y no cortó nada: el proceso ya había acabado", cortes, [])

    # modal: el arranque se programa antes de esperar
    registro.clear()
    raiz.after(20, cerrar_cuando_acabe, set(raiz.winfo_children()))
    rc = uitk.output_window("Prueba", HOLA, parent=raiz, modal=True)
    c("modal: espera y devuelve el código de salida", rc, 0)
    c("  la ventana se enseñó antes de lanzar el proceso", registro, ["ensenar", "Popen"])
    c("  y la pasada se vio entera",
      len(visto) == 1 and "hola" in visto[0] and "Terminado: OK" in visto[0], True)

    # cerrar antes de que arranque: ni se lanza ni se corta
    registro.clear()
    previos = temporizadores()
    recibido = []
    vuelta, ventana = abrir(HOLA, al_cerrar=recibido.append)
    x_de_la_ventana(ventana)
    c("cerrar antes de que arranque cancela el arranque", temporizadores() - previos, set())
    raiz.update()
    c("  no lanza el proceso", registro, ["ensenar"])
    c("  ni corta nada", cortes, [])
    c("  avisa una vez, con el código 1", recibido, [1])
    time.sleep(0.05)
    raiz.update()
    c("  ni se lanza después", registro, ["ensenar"])

    # lo mismo cuando la cierra su madre, sin pasar por la X
    registro.clear()
    previos = temporizadores()
    madre = tk.Toplevel(raiz)
    madre.withdraw()
    uitk.output_window("Prueba", HOLA, parent=madre, modal=False)
    madre.destroy()
    c("si se cierra la madre, el arranque se cancela", temporizadores() - previos, set())
    time.sleep(0.05)
    raiz.update()
    c("  no lanza nada", registro, ["ensenar"])
    c("  ni corta nada", cortes, [])

    # modal cerrada antes de arrancar
    registro.clear()
    tras_ensenar[:] = [x_de_la_ventana]
    rc = uitk.output_window("Prueba", HOLA, parent=raiz, modal=True)
    tras_ensenar.clear()
    c("modal cerrada antes de arrancar: devuelve 1", rc, 1)
    c("  sin lanzar el proceso", registro, ["ensenar"])
    c("  ni cortar nada", cortes, [])

    # una orden que no se puede lanzar
    registro.clear()
    previos = temporizadores()
    recibido = []
    vuelta, ventana = abrir(NO_EXISTE, al_cerrar=recibido.append)
    c("una orden que no existe no impide enseñar la ventana", registro, ["ensenar"])
    c("  dice que no se ha podido lanzar",
      esperar(lambda: "No se ha podido lanzar" in texto_de(ventana)), True)
    c("  con el veredicto del error 127 en el log", ERROR_127 in texto_de(ventana), True)
    c("  en el título", ventana.title().endswith("ERROR (código 127)"), True)
    c("  y en el recuadro de estado",
      any("ERROR (código 127)" in str(w.cget("text")) for w in recorrer(ventana)
          if isinstance(w, ttk.Label)), True)
    c("  no hay proceso", ventana.proceso, None)
    c("  y no queda nada programado (ni lectura ni arranque)",
      temporizadores() - previos, set())
    with tempfile.TemporaryDirectory() as carpeta:
        destino = str(Path(carpeta) / "log.txt")
        real_guardar = filedialog.asksaveasfilename
        filedialog.asksaveasfilename = lambda **k: destino
        try:
            boton(ventana, "Guardar el log").invoke()
        finally:
            filedialog.asksaveasfilename = real_guardar
        guardado = Path(destino).read_text(encoding="utf-8")
    c("«Guardar el log» guarda la línea del error",
      guardado.startswith("No se ha podido lanzar: "), True)
    c("  y el veredicto", guardado.rstrip().endswith(ERROR_127), True)
    boton(ventana, "Cerrar").invoke()
    raiz.update()
    c("al cerrarla avisa una vez, con el 127", recibido, [127])
    c("  sin cortar nada", cortes, [])

    # el 127 es de la ventana: un veredicto de quien llama no lo disimula
    vuelta, ventana = abrir(NO_EXISTE, veredictos={127: "no pasa nada"})
    esperar(lambda: "Terminado" in texto_de(ventana))
    c("ni un veredicto de quien llama lo hace pasar por bueno",
      ERROR_127 in texto_de(ventana), True)
    ventana.destroy()

    # modal con una orden que no se puede lanzar: devuelve el 127 al cerrarla
    visto.clear()
    raiz.after(20, cerrar_cuando_acabe, set(raiz.winfo_children()))
    rc = uitk.output_window("Prueba", NO_EXISTE, parent=raiz, modal=True)
    c("modal, una orden que no existe devuelve 127 en vez de lanzar el error", rc, 127)
    c("  y lo dijo en la ventana", len(visto) == 1 and ERROR_127 in visto[0], True)
    raiz.update()
    c("ningún `after` se quedó sin su ventana en todo lo anterior", errores_tcl, [])
    raiz.destroy()

    # la ventana principal, con la ventana de salida de verdad: «Sincronizar
    # ahora» abre una sin bloquear y la ventana se queda ocupada hasta que se
    # cierra, sea como sea
    from ui import cifrado, prefs, watch  # noqa: E402

    update.pending = lambda root=None: None
    update.check = lambda force=False: (None, None)
    uitk.pair_status_notes = lambda cfg: {}
    uitk.preguntar_resync = lambda root, pendientes, carpetas=None: False
    cifrado.expulsion = lambda **_k: None
    watch.resumen = lambda *a, **k: watch.Resumen("instalado", "daemon")
    prefs.PREFS = tmpdir("prdrive-tkpasada-") / "ui_prefs.json"
    UNA = mkcfg(["notas"])

    def principal(orden, conducir) -> None:
        """Abre la principal con esa orden como pasada y ejecuta `conducir` en su bucle."""
        uitk.orden_sync = lambda args: orden

        def _mainloop(self, n=0):
            """Conduce la ventana y cancela lo que dejó programado."""
            conducir(self)
            try:
                for pendiente in self.tk.splitlist(self.tk.call("after", "info")):
                    self.after_cancel(pendiente)
                self.destroy()
            except tk.TclError:
                pass
        tk.Tk.mainloop = _mainloop
        uitk.main_window(UNA, None)

    def esperar_en(root, condicion, espera: float = ESPERA) -> bool:
        """Como `esperar`, para una ventana principal que no es `raiz`."""
        limite = time.monotonic() + espera
        while time.monotonic() < limite:
            root.update()
            if condicion():
                return True
            time.sleep(0.01)
        return False

    def sincronizar_ahora(root):
        """Devuelve el botón «Sincronizar ahora» de la ventana principal.

        Se busca cada vez: hay versiones de la ventana que la repintan entera
        al ocuparse y el botón de antes ya no existe.
        """
        return boton(root, "Sincronizar ahora")

    def ocupada(root) -> bool:
        """Dice si la ventana principal tiene apagado «Sincronizar ahora»."""
        return sincronizar_ahora(root).instate(["disabled"])

    def sincronizar(root):
        """Pulsa «Sincronizar ahora» (cuando se deja) y devuelve la ventana de salida.

        La principal abre la salida en el turno siguiente al clic: se mueve el
        bucle de evento en evento hasta que aparece, para mirarla antes de que
        arranque su proceso, que va en el turno de después.
        """
        esperar_en(root, lambda: not ocupada(root))
        antes = set(root.winfo_children())
        registro.clear()               # la principal también se enseñó
        sincronizar_ahora(root).invoke()

        def nuevas():
            return [w for w in root.winfo_children()
                    if w not in antes and isinstance(w, tk.Toplevel)]

        limite = time.monotonic() + ESPERA
        while not nuevas() and time.monotonic() < limite:
            if not root.tk.dooneevent(_tkinter.DONT_WAIT):
                time.sleep(0.001)
        return nuevas()[0] if nuevas() else None

    anotado = {}

    def hasta_el_final(root) -> None:
        """Una pasada buena: ocupada mientras la ventana de salida está abierta."""
        salida = sincronizar(root)
        anotado["abierta"] = (ocupada(root), salida is not None, registro[:])
        esperar_en(root, lambda: "Terminado: OK" in texto_de(salida))
        anotado["acabada"] = ocupada(root)
        boton(salida, "Cerrar").invoke()
        anotado["vuelve"] = esperar_en(root, lambda: not ocupada(root))

    with sandbox():
        principal(HOLA, hasta_el_final)
    c("«Sincronizar ahora» abre la ventana y se apaga mientras corre",
      anotado["abierta"], (True, True, ["ensenar"]))
    c("  también cuando la pasada ya ha acabado, hasta cerrar la ventana",
      anotado["acabada"], True)
    c("  y al cerrarla vuelve a poder pulsarse", anotado["vuelve"], True)
    c("  habiendo lanzado el proceso después de enseñarla", registro, ["ensenar", "Popen"])

    def no_se_lanza(root) -> None:
        """Una orden que no existe: la ventana lo dice y la principal sigue ocupada."""
        salida = sincronizar(root)
        esperar_en(root, lambda: "Terminado" in texto_de(salida))
        anotado["dice"] = ERROR_127 in texto_de(salida)
        anotado["ocupada"] = ocupada(root)
        boton(salida, "Cerrar").invoke()
        anotado["libre"] = esperar_en(root, lambda: not ocupada(root))

    with sandbox():
        principal(NO_EXISTE, no_se_lanza)
    c("una orden que no se puede lanzar lo dice en la ventana de salida",
      anotado["dice"], True)
    c("  la principal sigue apagada mientras esa ventana está abierta",
      anotado["ocupada"], True)
    c("  y al cerrarla vuelve a poder pulsarse: no se queda ocupada", anotado["libre"], True)

    def cerrada_antes(root) -> None:
        """Se cierra la ventana de salida antes de que arranque su pasada."""
        salida = sincronizar(root)
        anotado["ocupada"] = ocupada(root)
        x_de_la_ventana(salida)
        anotado["libre"] = esperar_en(root, lambda: not ocupada(root))
        time.sleep(0.05)
        root.update()

    with sandbox():
        cortes.clear()
        principal(HOLA, cerrada_antes)
    c("cerrar la ventana de salida antes de que arranque la pasada",
      (anotado["ocupada"], registro, cortes), (True, ["ensenar"], []))
    c("  no deja la principal ocupada", anotado["libre"], True)
finally:
    uitk.ensenar = real_ensenar
    subprocess.Popen = real_popen
    store.matar_arbol = real_matar
    tk.Toplevel.deiconify = real_deiconify
    uitk.orden_sync = real_orden


# Con la raíz propia (`parent=None`), que es lo que usa `TkFrontend.run_sync`.
# tkinter no lleva bien dos intérpretes a la vez, así que va en un proceso aparte.
PROPIA = """
import subprocess, sys, time, tkinter as tk
sys.path.insert(0, sys.argv[1])
from ui import tk as uitk

ORDEN = [sys.executable, "-c", "print('hola')"]
registro = []
real_ensenar, real_popen = uitk.ensenar, subprocess.Popen
uitk.ensenar = lambda v: (real_ensenar(v), registro.append("ensenar"))[0]
# El tema también lanza procesos al aplicarse: solo se apunta el de la pasada.
subprocess.Popen = lambda *a, **k: ((registro.append("Popen") if a[0] == ORDEN else None),
                                    real_popen(*a, **k))[1]


def textos(w):
    return [w] if isinstance(w, tk.Text) else [t for h in w.winfo_children() for t in textos(h)]


def bucle(self, n=0):
    limite = time.time() + 30
    while time.time() < limite:
        self.update()
        if any("Terminado" in t.get("1.0", "end") for t in textos(self)):
            break
        time.sleep(0.01)
    self.destroy()


tk.Tk.mainloop = bucle
uitk.orden_sync = lambda args: ORDEN
rc = uitk.TkFrontend().run_sync("Propia", ["notas"])
print(rc, registro)
"""

REPO = Path(__file__).resolve().parent.parent
hijo = subprocess.run([sys.executable, "-c", PROPIA, str(REPO)], capture_output=True,
                      text=True, encoding="utf-8", timeout=120)
c("con la raíz propia: devuelve el código y enseña antes de lanzar",
  hijo.stdout.strip().splitlines()[-1:] if hijo.returncode == 0 else hijo.stderr[-400:],
  ["0 ['ensenar', 'Popen']"])
sys.exit(c.report())
