#!/usr/bin/env python3
"""La ventana principal cambia en su sitio: la vista, la lectura, la pasada y el tic.

`ui/tk_principal.py` dibuja un `principal.Estado` y, con otro, cambia solo lo
que difiere. Aquí se comprueba que eso no se deja nada y que no toca de más:

- tras cien series de estados al azar, lo que enseña la vista es lo mismo que
  enseña una vista nueva con el último estado (`tests/_vista.leer_vista`), y
  después de cada cambio lo que se ve y se puede pulsar es la tabla de
  `principal.controles()`;
- el mismo estado dos veces no toca nada; una casilla que sigue conserva lo
  marcado y una nueva nace de `marcadas`; el tabulador sigue el orden de la
  ventana aunque un bloque se cree tarde; «Marcar todas» y el chip de la
  cabecera tienen su sitio reservado.

Y lo que hace con ella la ventana de verdad (`ui.tk.main_window`, con el bucle
de eventos sustituido por una sonda):

- se pinta sin leer el dispositivo y lee después; al llegar la lectura crece
  hacia abajo sin moverse de su centro (y sube solo si se saldría por abajo);
  una lectura nueva deja sin aplicar la que estaba en camino;
- «Sincronizar ahora» se ocupa en el clic y abre la salida en el turno
  siguiente; si algo falla antes, no se queda ocupada;
- volver de «Ajustes» sin cambios no toca nada, y a «Ajustes» y «Parejas» se
  les pasa la lectura compartida;
- marcar no escribe en el clic, y lo marcado se escribe antes de cerrar, de
  sincronizar, de iniciar el servicio, de expulsar o de bloquear;
- al cerrar la pasada sigue ocupada hasta que llega la lectura nueva, y no
  vuelve a enseñar entretanto lo que se leyó antes de la pasada.

Y que un bloque que falla a medio pintar no deja la vista creyendo que pintó.
"""

import dataclasses
import random
import sys
import time
from pathlib import Path

from _harness import Checks, mkcfg, sandbox, tmpdir

c = Checks("ventana principal en su sitio (ui/tk_principal.py)")

import ui  # noqa: E402  — antes que tkinter: en Linux trae su Tk con Xft
from ui import principal, theme  # noqa: E402

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    theme.nitidez()
    raiz = tk.Tk()
    raiz.withdraw()
    theme.apply(raiz)
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from _vista import leer_vista, visibles  # noqa: E402

from common import model, update  # noqa: E402
from ui import (cifrado, instantanea, prefs, segundo_plano, tk_doctor,  # noqa: E402
                tk_pairs, tk_principal, watch)
from ui import tk as uitk  # noqa: E402
from ui.principal import Estado, Fila, Linea  # noqa: E402


def nada(*_a, **_k) -> None:
    """Una acción que no hace nada."""


ACCIONES = tk_principal.Acciones(*([nada] * len(tk_principal.Acciones._fields)))


def vista_nueva(e):
    """Devuelve una vista recién hecha con el estado `e`, en su ventana oculta."""
    top = tk.Toplevel(raiz)
    top.withdraw()
    marco = ttk.Frame(top, padding=(theme.E5, theme.E5, theme.E5, theme.E4))
    marco.grid(row=0, column=0, sticky="nsew")
    marco.columnconfigure(0, weight=1)
    v = tk_principal.VistaPrincipal(marco, ACCIONES)
    v.aplicar(e)
    return top, v


def igualar(v, e) -> None:
    """Deja las casillas de la vista como nacerían con `e`, y su «N de M» al día.

    Una casilla que sigue conserva lo que tenía, y una vista nueva nace de
    `e.marcadas`: para comparar el resto, las dos se igualan antes de leerlas.
    La regla de conservar se prueba aparte.
    """
    for nombre, var in v.casillas.items():
        var.set(nombre in e.marcadas)
    v.contar()


def fallos_de_tabla(v, e) -> list:
    """Devuelve los controles en que la vista no dice lo que la tabla.

    Si se ve, en todos; si se puede pulsar, en los que se ven: en uno escondido
    no significa nada (`principal.Control`).
    """
    malos = []
    real = v.controles_tk()
    for clave, ctl in principal.controles(e).items():
        visible, activo = real[clave]
        if visible != ctl.visible or (ctl.visible and activo != ctl.activo):
            malos.append((clave, (visible, activo), tuple(ctl)))
    return malos


def todos(w) -> set:
    """Devuelve los nombres de todos los widgets que cuelgan de `w`."""
    pila, nombres = [w], set()
    while pila:
        x = pila.pop()
        nombres.add(str(x))
        pila += list(x.winfo_children())
    return nombres


# 1. estados al azar: la vista cambiada en su sitio enseña lo mismo que una nueva
NOMBRES = ("docs", "fotos", "claves", "musica", "notas", "trabajo")
MODOS = ("bisync", "up", "down", "backup-mirror")
CUANDOS = ("—", "10:20", "ayer", "03/09")
CHIPS_FILA = (None, ("requiere resync", "Aviso."), ("1 conflicto", "Aviso."),
              ("3 conflictos", "Aviso."))
AVISOS = (None, "Servicio anterior (pid 4242) detenido.")
VERSIONES = (None,
             "Hay una actualización: v9.9.9\nTienes la 0.7.1. «Actualizar…» baja la "
             "versión nueva y reabre la ventana.",
             "Hay una actualización: v9.9.10\nTienes la 0.7.1. «Actualizar…» baja la "
             "versión nueva y reabre la ventana.")
COMPONENTES = (None,
               "Lo que lleva el dispositivo de fuera (rclone, Python, VeraCrypt) no es lo "
               "que fija esta versión:\nrclone 1.70.0 (fija 1.71.0)",
               "Lo que lleva el dispositivo de fuera (rclone, Python, VeraCrypt) no es lo "
               "que fija esta versión:\nPython 3.13 (fija 3.14)\nrclone 1.70.0 (fija 1.71.0)")
LLAVEROS = (None, Linea("personal.kdbx, al día.", False, "Abrir llavero", True),
            Linea("personal.kdbx, al día.", False, "Abrir llavero", False),
            Linea("personal.kdbx: la última pasada falló.", True, "Abrir llavero", True))
ARRANQUES = (None,
             Linea("En este equipo no se arranca nada al enchufarlo.", False, "Configurar…",
                   True),
             Linea("El arranque automático de este equipo es de otra versión.", True,
                   "Revisar…", True))
PAUSAS = (None, watch.PAUSA, watch.PAUSA_AGENTE)
SERVICIOS = ((principal.INICIAR, "Iniciar servicio"), (watch.PAUSAR, "Pausar"),
             (watch.REANUDAR, "Reanudar"), (watch.SEGUIR, "Reanudar todo"))
PIES = (None, principal.EXPULSAR, principal.BLOQUEAR)


def estado_al_azar(rng) -> Estado:
    """Un estado de la ventana al azar, con la forma que le da `principal.estado`."""
    en_curso = rng.random() < 0.3
    cargando = rng.random() < 0.25
    reparacion = 0 if cargando else rng.choice((0, 0, 1, 3))
    filas = tuple(Fila(n, rng.choice(MODOS), rng.choice(CUANDOS),
                       None if cargando else rng.choice(CHIPS_FILA))
                  for n in rng.sample(NOMBRES, rng.randint(0, len(NOMBRES))))
    if en_curso:
        chip = ("sincronizando…", "Acento.", "sync")
    elif cargando:
        chip = ("…", "", None)
    elif reparacion:
        chip = (f"{reparacion} que revisar" if reparacion > 1 else "1 que revisar",
                "Aviso.", "warn")
    else:
        chip = ("al día", "Ok.", "ok")
    version = rng.choice(VERSIONES)
    componentes = None if (version or cargando) else rng.choice(COMPONENTES)
    arranque = None if cargando else rng.choice(ARRANQUES)
    return Estado(
        dispositivo=rng.choice(("F:\\", "…/media/quien/PRDRIVE")),
        remotos=rng.choice(("nas", "nas, otro")), chip=chip, aviso=rng.choice(AVISOS),
        reparacion=reparacion, version=version, componentes=componentes,
        componentes_boton=componentes is not None and rng.random() < 0.5, filas=filas,
        ultima=rng.choice(("", "última pasada ayer")),
        marcadas=frozenset(rng.sample(NOMBRES, rng.randint(0, len(NOMBRES)))),
        llavero=None if cargando else rng.choice(LLAVEROS), arranque=arranque,
        pausa=None if arranque is None else rng.choice(PAUSAS),
        servicio=SERVICIOS[0] if cargando else rng.choice(SERVICIOS),
        pie=None if cargando else rng.choice(PIES), en_curso=en_curso, cargando=cargando)


SECUENCIAS = 100
distintas: list = []
tabla_mal: list = []
for semilla in range(SECUENCIAS):
    rng = random.Random(semilla)
    serie = [estado_al_azar(rng) for _ in range(rng.randint(2, 6))]
    top, v = vista_nueva(serie[0])
    tabla_mal += [(semilla, 0, m) for m in fallos_de_tabla(v, serie[0])]
    for paso, e in enumerate(serie[1:], 1):
        v.aplicar(e)
        tabla_mal += [(semilla, paso, m) for m in fallos_de_tabla(v, e)]
    otra, fresca = vista_nueva(serie[-1])
    igualar(v, serie[-1])
    igualar(fresca, serie[-1])
    if leer_vista(v.marco) != leer_vista(fresca.marco):
        distintas.append(semilla)
    top.destroy()
    otra.destroy()
c(f"{SECUENCIAS} series al azar: lo cambiado en su sitio enseña lo mismo que una vista "
  "nueva", distintas, [])
c("  y después de cada cambio, lo que se ve y se puede pulsar es la tabla de "
  "`principal.controles()`", tabla_mal[:3], [])


# 2. el mismo estado dos veces no toca nada
rng = random.Random(1234)
e1 = estado_al_azar(rng)
while not e1.filas:
    e1 = estado_al_azar(rng)
top, v = vista_nueva(e1)
antes = (todos(top), leer_vista(v.marco))
tocados: list = []
ESPIADOS = ((tk.Misc, "_configure"), (tk.Grid, "grid_configure"), (tk.Grid, "grid_remove"),
            (tk.BaseWidget, "destroy"), (tk.BaseWidget, "__init__"), (ttk.Widget, "state"))
reales = {par: getattr(*par) for par in ESPIADOS}


def espiar(clase, nombre):
    """Sustituye un método de Tk por uno que apunta su uso y llama al de verdad."""
    real = reales[(clase, nombre)]

    def espia(self, *a, **k):
        """Apunta la llamada y la pasa."""
        tocados.append(nombre)
        return real(self, *a, **k)
    setattr(clase, nombre, espia)


for par in ESPIADOS:
    espiar(*par)
try:
    otra_vez = v.aplicar(Estado(**{**e1.__dict__}))
finally:
    for (clase, nombre), real in reales.items():
        setattr(clase, nombre, real)
c("el mismo estado otra vez: `aplicar()` dice que nada cambió de tamaño", otra_vez, False)
c("  sin configurar, colocar, crear ni destruir nada", tocados, [])
c("  los mismos widgets, y enseñando lo mismo", (todos(top), leer_vista(v.marco)), antes)

# Pasar a «ocupado» no rehace la lista: solo cambian el chip, los botones y la
# línea de «Reparación…».
fila_antes = todos(v._tarjeta)
v.aplicar(e1.__class__(**{**e1.__dict__, "en_curso": not e1.en_curso,
                          "chip": ("sincronizando…", "Acento.", "sync")}))
c("ocuparse no crea ni destruye nada en la lista", todos(v._tarjeta), fila_antes)
e2 = Estado(**{**e1.__dict__, "llavero": Linea("personal.kdbx, al día.", False,
                                              "Abrir llavero", True)})
v.aplicar(e2)
c("un botón que solo se apaga no cambia el tamaño",
  v.aplicar(Estado(**{**e2.__dict__, "llavero": e2.llavero._replace(activo=False)})), False)
c("  y un aviso que aparece, sí",
  v.aplicar(Estado(**{**e2.__dict__, "aviso": "Servicio anterior detenido."})), True)
top.destroy()


# 3. la casilla de una fila que sigue conserva lo marcado; la de una nueva nace de `marcadas`
def lista(nombres, marcadas, **cambios) -> Estado:
    """Un estado quieto con esas filas y esas marcadas."""
    base = dict(dispositivo="F:\\", remotos="nas", chip=("al día", "Ok.", "ok"), aviso=None,
                reparacion=0, version=None, componentes=None, componentes_boton=False,
                filas=tuple(Fila(n, "bisync", "—", None) for n in nombres), ultima="",
                marcadas=frozenset(marcadas), llavero=None, arranque=None, pausa=None,
                servicio=(principal.INICIAR, "Iniciar servicio"), pie=None,
                en_curso=False, cargando=False)
    base.update(cambios)
    return Estado(**base)


top, v = vista_nueva(lista(["a", "b"], ["a"]))
c("las casillas nacen de `marcadas`", {n: x.get() for n, x in v.casillas.items()},
  {"a": True, "b": False})
casilla_a = v.filas["a"]["casilla"]
v.casillas["a"].set(False)
v.casillas["b"].set(True)
v.aplicar(lista(["a", "b", "c"], ["a", "c"]))
c("una fila que sigue conserva su casilla; una nueva nace de `marcadas`",
  {n: x.get() for n, x in v.casillas.items()}, {"a": False, "b": True, "c": True})
c("  y el «N de M» lo cuenta", str(v._resumen.cget("text")), "2 de 3")
v.aplicar(lista(["c", "a", "b"], ["a", "c"]))
c("cambiar el orden no rehace las filas: la misma casilla", v.filas["a"]["casilla"],
  casilla_a)
c("  en su fila nueva", int(casilla_a.grid_info()["row"]), 2)
c("  y el tabulador las recorre en el orden de la lista",
  [str(w.cget("text")) for w in v._tarjeta.winfo_children()
   if isinstance(w, ttk.Checkbutton)], ["c", "a", "b"])
v.aplicar(lista(["b"], ["a", "c"]))
c("una fila que se va se lleva su casilla", sorted(v.casillas), ["b"])
c("  y con una sola pareja no hay «Marcar todas»",
  visibles(v.marco, "TButton", principal.MARCAR_TODAS)
  + visibles(v.marco, "TButton", principal.DESMARCAR_TODAS), [])
c("  ni el sitio que se le reservaba", int(v._rotulo.grid_columnconfigure(1, "minsize")), 0)
top.destroy()

# 4. un bloque que se crea tarde queda en el orden del tabulador
top, v = vista_nueva(lista(["a", "b"], ["a"]))
v.aplicar(lista(["a", "b"], ["a"], aviso="Servicio anterior detenido.", reparacion=2,
                chip=("2 que revisar", "Aviso.", "warn"),
                llavero=LLAVEROS[1], arranque=ARRANQUES[1], pausa=watch.PAUSA,
                pie=principal.EXPULSAR))
filas_en_orden = [int(w.grid_info()["row"]) for w in v.marco.winfo_children()
                  if w.winfo_manager() == "grid"]
c("los bloques que se crean tarde quedan en el orden de apilado de la ventana (el del Tab)",
  filas_en_orden, sorted(filas_en_orden))
pie_en_orden = [str(w.cget("text")) for w in v._pie.winfo_children()
                if isinstance(w, ttk.Button) and w.winfo_manager()]
c("  y «Expulsar», detrás de los otros dos del pie", pie_en_orden,
  ["Sincronizar ahora", "Iniciar servicio", "Expulsar"])

# 5. «Marcar todas» y el chip de la cabecera tienen su sitio reservado
reservado = int(v._rotulo.grid_columnconfigure(1, "minsize"))
anchos = []
for texto in (principal.MARCAR_TODAS, principal.DESMARCAR_TODAS):
    v._todas.configure(text=texto)
    anchos.append(v._todas.winfo_reqwidth())
v.contar()
c("«Marcar todas» tiene reservado el ancho de sus dos textos",
  all(reservado >= a for a in anchos), True)
top.destroy()

c("el chip reservado es el de un dispositivo sin nada que revisar",
  principal.estado(mkcfg(["a"]), aviso=None, nueva=None, instalada=None, tiempos={},
                   marcadas=(), en_curso=False, inst=instantanea.vacia(mkcfg(["a"]))).chip,
  tk_principal.CHIP_RESERVADO)
top, v = vista_nueva(lista(["a"], ["a"], chip=("…", "", None), cargando=True))
v.marco.update_idletasks()
ancho_cargando = v._arriba.winfo_reqwidth()
c("el hueco del chip de la cabecera es el de «al día»",
  int(v._arriba.grid_columnconfigure(1, "minsize")),
  theme.chip(v._arriba, *tk_principal.CHIP_RESERVADO).winfo_reqwidth())
v.aplicar(lista(["a"], ["a"]))
v.marco.update_idletasks()
c("  así que la cabecera no cambia de ancho al pasar de «…» a «al día»",
  v._arriba.winfo_reqwidth(), ancho_cargando)
top.destroy()

# 5b. un bloque que falla a medio pintar no deja apuntado un estado que no se ve
top, v = vista_nueva(lista(["a", "b"], ["a"]))
con_llavero = lista(["a", "b"], ["a"], llavero=LLAVEROS[1])
real_llavero = tk_principal.VistaPrincipal._pintar_llavero


def llavero_roto(self, antes, e, ctl):
    """Hace de un bloque que falla a medio pintar (la ventana cerrándose)."""
    raise tk.TclError("a medio cerrar")


tk_principal.VistaPrincipal._pintar_llavero = llavero_roto
try:
    try:
        v.aplicar(con_llavero)
        fallo = None
    except tk.TclError as error:
        fallo = str(error)
finally:
    tk_principal.VistaPrincipal._pintar_llavero = real_llavero
c("un bloque que falla a medio pintar: el error sigue su camino", fallo, "a medio cerrar")
c("  y la vista no da por aplicado ningún estado", v.estado, None)
c("  así que el mismo estado, otra vez, se pinta entero",
  (v.aplicar(con_llavero), v.estado is con_llavero,
   len(visibles(v.marco, "TButton", "Abrir llavero"))), (True, True, 1))
top.destroy()


# 6. la ventana de verdad
REAL_MAINLOOP, REAL_LANZAR = tk.Tk.mainloop, segundo_plano.lanzar
update.pending = lambda root=None: None
update.check = lambda force=False: (None, None)
for _m in (ui, uitk):
    _m.pair_status_notes = lambda cfg: {}
uitk.preguntar_resync = lambda root, pendientes, carpetas=None: False
SCRIPT = Path("E:/Expulsar PRDRIVE.bat")
cifrado.expulsion = lambda **_k: SCRIPT
watch.resumen = lambda: watch.Resumen("sin_instalar")
prefs.PREFS = tmpdir("prdrive-principal-vista-") / "ui_prefs.json"
lanzadas: list = []
REAL_OUTPUT = uitk.output_window
uitk.output_window = lambda titulo, cmd, **k: lanzadas.append(cmd)
TRES = mkcfg(["a", "b", "c"], {"pairs": ["a"]})


def hasta(root, condicion, espera: float = 2.0) -> bool:
    """Mueve el bucle de eventos hasta que se cumple `condicion` o pasa `espera`."""
    limite = time.monotonic() + espera
    while not condicion() and time.monotonic() < limite:
        root.update()
        time.sleep(0.005)
    return bool(condicion())


def boton(root, texto):
    """Devuelve el botón a la vista con ese texto, o `None`."""
    return next(iter(visibles(root, "TButton", texto)), None)


def activo(root, texto) -> bool:
    """Indica si el botón a la vista con ese texto se puede pulsar."""
    b = boton(root, texto)
    return b is not None and not b.instate(["disabled"])


def casilla(root, nombre):
    """Devuelve la casilla a la vista de esa pareja."""
    return next(iter(visibles(root, "TCheckbutton", nombre)))


def textos(root) -> list[str]:
    """Los textos de las etiquetas a la vista."""
    return [str(w.cget("text")) for w in visibles(root, "TLabel")]


def abrir(cfg, conducir, lanzar=segundo_plano.en_el_acto, aviso=None):
    """Abre la principal con `conducir` en lugar de su bucle de eventos.

    Al acabar cancela lo que quedara programado y la cierra (si no la cerró el
    propio botón). Devuelve la elección con que se cierra.
    """
    def _mainloop(self, n=0):
        """Conduce la ventana y la cierra."""
        try:
            conducir(self)
        finally:
            try:
                for pendiente in self.tk.splitlist(self.tk.call("after", "info")):
                    self.after_cancel(pendiente)
                self.destroy()
            except tk.TclError:
                pass
    segundo_plano.lanzar = lanzar
    tk.Tk.mainloop = _mainloop
    try:
        return uitk.main_window(cfg, aviso)
    finally:
        tk.Tk.mainloop, segundo_plano.lanzar = REAL_MAINLOOP, REAL_LANZAR


def sin_terminar(funcion):
    """Un `segundo_plano.lanzar` cuyo encargo no termina hasta que el test lo corre."""
    return segundo_plano.Encargo(funcion)


# 6a. primero se pinta, después se lee; al llegar, crece sin moverse
with sandbox():
    visto: dict = {}

    def cargando(root) -> None:
        """Mira la ventana antes de la lectura, la deja llegar y la vuelve a mirar."""
        visto["antes"] = {
            "chip": "…" in textos(root), "al día": "al día" in textos(root),
            "sincronizar": activo(root, "Sincronizar ahora"),
            "servicio": activo(root, "Iniciar servicio"),
            "parejas": activo(root, "Parejas…"), "ajustes": activo(root, "Ajustes…"),
            "expulsar": boton(root, "Expulsar") is not None,
            "arranque": boton(root, "Configurar…") is not None}
        visto["lanzada"] = root.instantanea is not None
        root.update_idletasks()
        visto["leyendo"] = (root.instantanea is not None, root.instantanea_lista)
        x, y, alto = root.winfo_x(), root.winfo_y(), root.winfo_reqheight()
        ancho = root.winfo_width()
        root.instantanea.correr()
        visto["llega"] = hasta(root, lambda: root.instantanea_lista)
        hasta(root, lambda: root.winfo_width() == root.winfo_reqwidth())
        root.update()                            # y la posición, que llega aparte
        visto["fallos"] = root.instantanea.resultado.fallos
        visto["después"] = {
            "expulsar": boton(root, "Expulsar") is not None,
            "arranque": boton(root, "Configurar…") is not None,
            "sincronizar": activo(root, "Sincronizar ahora"),
            "servicio": activo(root, "Iniciar servicio")}
        visto["crece"] = root.winfo_reqheight() > alto
        visto["ancha"] = root.winfo_width() > ancho
        visto["y"] = (root.winfo_y(), y)
        # El doble del centro, para no partir píxeles: crecer un número impar
        # de píxeles lo deja medio píxel a un lado.
        visto["centro"] = abs((2 * root.winfo_x() + root.winfo_width()) - (2 * x + ancho))
        visto["compartida"] = root.sondeo_instantanea is not None

    abrir(TRES, cargando, lanzar=sin_terminar)
    c("primer pintado: el chip es «…» y no «al día»",
      (visto["antes"]["chip"], visto["antes"]["al día"]), (True, False))
    c("  «Sincronizar ahora» e «Iniciar servicio» apagados",
      (visto["antes"]["sincronizar"], visto["antes"]["servicio"]), (False, False))
    c("  «Parejas…» y «Ajustes…» se pueden pulsar",
      (visto["antes"]["parejas"], visto["antes"]["ajustes"]), (True, True))
    c("  sin «Expulsar» ni la línea del arranque automático",
      (visto["antes"]["expulsar"], visto["antes"]["arranque"]), (False, False))
    c("  y la lectura no se lanza antes de enseñarla, sino en cuanto Tk tiene un momento",
      (visto["lanzada"], visto["leyendo"]), (False, (True, False)))
    c("al llegar la lectura se aplica", visto["llega"], True)
    c("  sin ningún lector que fallara", visto["fallos"], {})
    c("  con «Expulsar», la línea del arranque y los dos botones encendidos",
      visto["después"], {"expulsar": True, "arranque": True, "sincronizar": True,
                         "servicio": True})
    c("  la ventana crece", visto["crece"], True)
    c("  y se ensancha (no tenía ancho recordado)", visto["ancha"], True)
    c("  sin bajar", visto["y"][0], visto["y"][1])
    c("  ni moverse de su centro horizontal", visto["centro"] <= 1, True)

# 6b. si al crecer se saldría por abajo, sube lo justo
REAL_UTIL = uitk.pantalla_util
with sandbox():
    visto = {}

    def se_saldria(root) -> None:
        """Deja la pantalla útil a la altura del borde de abajo y deja llegar la lectura."""
        abajo = root.winfo_y() + root.winfo_reqheight()
        uitk.pantalla_util = lambda win, a=abajo: (1920, a)
        root.update_idletasks()
        root.instantanea.correr()
        hasta(root, lambda: root.instantanea_lista)
        visto["abajo"] = (root.winfo_y() + root.winfo_reqheight(), abajo)
        visto["y"] = root.winfo_y()

    try:
        abrir(TRES, se_saldria, lanzar=sin_terminar)
    finally:
        uitk.pantalla_util = REAL_UTIL
    c("si al crecer se saldría por abajo, sube justo hasta el borde",
      visto["abajo"][0], visto["abajo"][1])

# 6c. una lectura nueva deja sin aplicar la que estaba en camino
with sandbox():
    model.CONFIG_FILE.write_text(
        "[defaults]\nremote = \"nas\"\n\n[[pair]]\nname = \"a\"\n"
        "local = \"sync-data/a\"\nremote_path = \"/R/a\"\n", encoding="utf-8")
    encargos: list = []
    visto = {}

    def apuntando(funcion):
        """Como `sin_terminar`, y apunta cada encargo."""
        encargos.append(segundo_plano.Encargo(funcion))
        return encargos[-1]

    def dos_lecturas(root) -> None:
        """Lanza una segunda lectura con la primera en camino y las acaba al revés."""
        root.update_idletasks()
        sondeo = root.sondeo_instantanea
        boton(root, "Parejas…").invoke()          # guarda algo: relee la config
        visto["dos"] = (len(encargos), root.instantanea is encargos[-1],
                        root.sondeo_instantanea is sondeo)
        encargos[0].correr()
        root.update()
        time.sleep(0.05)
        root.update()
        visto["vieja"] = root.instantanea_lista
        encargos[1].correr()
        visto["nueva"] = hasta(root, lambda: root.instantanea_lista)

    real_parejas = tk_pairs.open_dialog
    tk_pairs.open_dialog = lambda parent, config, compartida=None: True
    try:
        abrir(model.load_config(), dos_lecturas, lanzar=apuntando)
    finally:
        tk_pairs.open_dialog = real_parejas
    c("volver de «Parejas» con cambios lanza otra lectura, con el mismo sondeo",
      visto["dos"], (2, True, True))
    c("  la que estaba en camino, al acabar, no se aplica", visto["vieja"], False)
    c("  la nueva sí", visto["nueva"], True)

# 6d. «Sincronizar ahora»: ocupada en el clic, la salida en el turno siguiente
with sandbox():
    orden: list = []
    visto = {}
    real_aplicar, real_manual = tk_principal.VistaPrincipal.aplicar, uitk.manual_args

    def aplicar_apuntando(self, e):
        """Apunta cada estado aplicado, ocupado o no."""
        orden.append(("aplicar", e.en_curso))
        return real_aplicar(self, e)

    def pasada(root) -> None:
        """Pulsa «Sincronizar ahora» y apunta qué pasa en el clic y después."""
        root.update_idletasks()
        orden.clear()
        lanzadas.clear()
        boton(root, "Sincronizar ahora").invoke()
        visto["en el clic"] = (list(orden), activo(root, "Sincronizar ahora"),
                               "sincronizando…" in textos(root))
        hasta(root, lambda: "output_window" in orden)
        visto["después"] = list(orden)

    tk_principal.VistaPrincipal.aplicar = aplicar_apuntando
    uitk.manual_args = lambda config, pairs, approve: (orden.append("manual_args"),
                                                       list(pairs))[1]
    uitk.output_window = lambda titulo, cmd, **k: orden.append("output_window")
    try:
        abrir(TRES, pasada)
    finally:
        tk_principal.VistaPrincipal.aplicar, uitk.manual_args = real_aplicar, real_manual
        uitk.output_window = lambda titulo, cmd, **k: lanzadas.append(cmd)
    c("«Sincronizar ahora»: en el clic solo se ocupa la ventana",
      visto["en el clic"], ([("aplicar", True)], False, True))
    c("  y en el turno siguiente pregunta lo del resync y abre la salida",
      visto["después"], [("aplicar", True), "manual_args", "output_window"])

# 6e. si la salida no llega a abrirse, la ventana no se queda ocupada
for que_falla in ("output_window", "manual_args"):
    with sandbox():
        visto = {}
        errores: list = []

        def revienta(*_a, **_k):
            """Hace de la pieza que falla."""
            raise RuntimeError("no se ha podido")

        def falla(root) -> None:
            """Pulsa «Sincronizar ahora» con una pieza que falla y mira cómo queda."""
            root.update_idletasks()
            root.report_callback_exception = lambda *a: errores.append(a[1])
            boton(root, "Sincronizar ahora").invoke()
            visto["libre"] = hasta(root, lambda: activo(root, "Sincronizar ahora"))
            visto["chip"] = "sincronizando…" in textos(root)

        real = getattr(uitk, que_falla)
        setattr(uitk, que_falla, revienta)
        try:
            abrir(TRES, falla)
        finally:
            setattr(uitk, que_falla, real)
        c(f"si `{que_falla}` falla, «Sincronizar ahora» vuelve a poder pulsarse",
          (visto["libre"], visto["chip"]), (True, False))
        c("  y el error no se esconde", [str(e) for e in errores], ["no se ha podido"])

# 6f. volver de «Ajustes» sin cambios no toca nada; con la lectura compartida
with sandbox():
    visto = {}
    pasadas: list = []
    llamadas = {"aplicar": 0, "encajar": 0}
    real_aplicar, real_encajar = tk_principal.VistaPrincipal.aplicar, uitk.Visor.encajar

    def contar_aplicar(self, e):
        llamadas["aplicar"] += 1
        return real_aplicar(self, e)

    def contar_encajar(self, ventana=None):
        llamadas["encajar"] += 1
        return real_encajar(self, ventana)

    def ajustes_sin_cambios(parent, config, lanzar, **k):
        """Hace de «Ajustes»: apunta lo que recibe y no cambia nada."""
        pasadas.append(k)
        return {}

    def volver(root) -> None:
        """Abre «Ajustes» con la lectura ya aplicada y cuenta lo que se repinta al volver."""
        root.update_idletasks()
        visto["inst"] = root.instantanea.resultado
        llamadas.update(aplicar=0, encajar=0)
        boton(root, "Ajustes…").invoke()
        visto["llamadas"] = dict(llamadas)

    real_doctor = tk_doctor.open_dialog
    tk_doctor.open_dialog = ajustes_sin_cambios
    tk_principal.VistaPrincipal.aplicar, uitk.Visor.encajar = contar_aplicar, contar_encajar
    try:
        abrir(TRES, volver)
    finally:
        tk_doctor.open_dialog = real_doctor
        tk_principal.VistaPrincipal.aplicar, uitk.Visor.encajar = real_aplicar, real_encajar
    c("volver de «Ajustes» sin cambios no aplica nada ni encaja la ventana",
      visto["llamadas"], {"aplicar": 0, "encajar": 0})
    k = pasadas[0]
    c("  a «Ajustes» se le pasa la lectura compartida, y el vigilante de la lectura",
      (k["compartida"].actual is visto["inst"], k["vigilante"] == visto["inst"].vigilante),
      (True, True))

# 6g. lo pedido al agente se enseña hasta que una lectura lanzada después lo cuenta
with sandbox():
    model.CONFIG_FILE.write_text(
        "[defaults]\nremote = \"nas\"\n\n[[pair]]\nname = \"a\"\n"
        "local = \"sync-data/a\"\nremote_path = \"/R/a\"\n", encoding="utf-8")
    encargos = []
    visto = {}

    def apuntando(funcion):
        """Como `sin_terminar`, y apunta cada encargo."""
        encargos.append(segundo_plano.Encargo(funcion))
        return encargos[-1]

    def leer_hasta(root, encargo) -> None:
        """Acaba ese encargo y espera a que se aplique."""
        encargo.correr()
        hasta(root, lambda: root.instantanea_lista)

    def pausar(root) -> None:
        """Pulsa «Pausar» con una lectura en camino, y deja llegar esa y otra."""
        root.update_idletasks()
        leer_hasta(root, encargos[0])
        boton(root, "Parejas…").invoke()         # otra lectura, en camino
        boton(root, "Pausar").invoke()
        visto["pedido"] = boton(root, "Reanudar") is not None
        leer_hasta(root, encargos[1])
        visto["vieja"] = boton(root, "Reanudar") is not None
        boton(root, "Parejas…").invoke()
        leer_hasta(root, encargos[2])
        visto["nueva"] = boton(root, "Pausar") is not None

    reales_agente = (watch.resumen, watch.pedir_servicio, tk_pairs.open_dialog)
    watch.resumen = lambda: watch.Resumen("agente", "daemon", True)
    watch.pedir_servicio = lambda accion: True
    tk_pairs.open_dialog = lambda parent, config, compartida=None: True
    try:
        abrir(model.load_config(), pausar, lanzar=apuntando)
    finally:
        watch.resumen, watch.pedir_servicio, tk_pairs.open_dialog = reales_agente
    c("«Pausar» enseña lo pedido al agente", visto["pedido"], True)
    c("  y una lectura lanzada antes de pedirlo no lo deshace", visto["vieja"], True)
    c("  una lanzada después manda: el agente aún no lo ha aplicado",
      visto["nueva"], True)

# 6h. marcar no escribe en el clic
real_guardar = prefs.guardar_parejas
escritas: list = []
prefs.guardar_parejas = lambda config, pares: (escritas.append(list(pares)),
                                               real_guardar(config, pares))[1]
try:
    with sandbox():
        prefs.PREFS.unlink(missing_ok=True)
        visto = {}

        def marcar(root) -> None:
            """Marca una casilla y mira cuándo se escribe."""
            root.update_idletasks()
            escritas.clear()
            casilla(root, "b").invoke()
            visto["en el clic"] = list(escritas)
            visto["al rato"] = hasta(root, lambda: escritas)
            visto["escrito"] = prefs.read_prefs().get("pairs")

        abrir(TRES, marcar)
        c("marcar una casilla no escribe nada en el clic", visto["en el clic"], [])
        c("  y la escribe al rato, una vez, sin pulsar nada más",
          (visto["al rato"], len(escritas), visto["escrito"]), (True, 1, ["a", "b"]))

    # 6i. lo marcado se escribe antes de cerrar, de sincronizar, del servicio y de expulsar
    def tras_marcar(accion):
        """Marca «b» y, sin dejar que pase el rato, hace `accion(root)`."""
        def conducir(root) -> None:
            root.update_idletasks()
            casilla(root, "b").invoke()
            accion(root)
        return conducir

    with sandbox():
        prefs.PREFS.unlink(missing_ok=True)
        cortados: list = []
        real_matar = uitk.store.matar_hijos
        uitk.store.matar_hijos = lambda: cortados.append(1) or 0
        try:
            abrir(TRES, tras_marcar(lambda root: root.destroy()))
        finally:
            uitk.store.matar_hijos = real_matar
        c("lo marcado se escribe al cerrar la ventana", prefs.read_prefs().get("pairs"),
          ["a", "b"])
        c("  y al cerrarse corta sus lecturas, una vez", len(cortados), 1)

    with sandbox():
        prefs.PREFS.unlink(missing_ok=True)
        lanzadas.clear()
        visto = {}

        def sincronizar(root) -> None:
            boton(root, "Sincronizar ahora").invoke()
            hasta(root, lambda: lanzadas)
            visto["pairs"] = prefs.read_prefs().get("pairs")

        abrir(TRES, tras_marcar(sincronizar))
        c("lo marcado se escribe al lanzar «Sincronizar ahora»",
          (visto["pairs"], [cmd[2:] for cmd in lanzadas]), (["a", "b"], [["a", "b"]]))

    with sandbox():
        prefs.PREFS.unlink(missing_ok=True)
        visto = {}

        def iniciar(root) -> None:
            """Pulsa «Iniciar servicio» y apunta lo escrito antes de que se cierre."""
            cerrar = root.destroy

            def apuntar_y_cerrar() -> None:
                visto.setdefault("pairs", prefs.read_prefs().get("pairs"))
                cerrar()
            root.destroy = apuntar_y_cerrar
            boton(root, "Iniciar servicio").invoke()

        eleccion = abrir(TRES, tras_marcar(iniciar))
        c("lo marcado se escribe al iniciar el servicio, antes de cerrar la ventana",
          (visto["pairs"], eleccion.pairs), (["a", "b"], ("a", "b")))

    reales_mb = (messagebox.askokcancel, cifrado.lanzar_expulsion)
    with sandbox():
        prefs.PREFS.unlink(missing_ok=True)
        visto = {}
        cortados: list = []
        real_matar = uitk.store.matar_hijos
        messagebox.askokcancel = lambda *a, **k: True

        def expulsion_apuntada(script) -> None:
            """Apunta qué script se lanza y qué había escrito al lanzarlo."""
            visto["script"] = script
            visto["pairs"] = prefs.read_prefs().get("pairs")
            visto["cortados"] = len(cortados)

        def expulsar(root) -> None:
            # La lectura dijo un script; al pulsar se busca otra vez.
            cifrado.expulsion = lambda **_k: Path("F:/Otro PRDRIVE.bat")
            boton(root, "Expulsar").invoke()

        cifrado.lanzar_expulsion = expulsion_apuntada
        uitk.store.matar_hijos = lambda: cortados.append(1) or 0
        try:
            abrir(TRES, tras_marcar(expulsar))
        finally:
            messagebox.askokcancel, cifrado.lanzar_expulsion = reales_mb
            uitk.store.matar_hijos = real_matar
            cifrado.expulsion = lambda **_k: SCRIPT
        c("lo marcado se escribe antes de lanzar el script de expulsar",
          visto["pairs"], ["a", "b"])
        c("  y antes se cortan las lecturas que queden", visto["cortados"], 1)
        c("  con el script que hay al pulsar, no el de la lectura", visto["script"],
          Path("F:/Otro PRDRIVE.bat"))

    reales_bloqueo = (messagebox.askokcancel, cifrado.bloqueo, cifrado.pedir_bloqueo)
    with sandbox():
        prefs.PREFS.unlink(missing_ok=True)
        visto = {}
        cortados = []
        real_matar = uitk.store.matar_hijos
        messagebox.askokcancel = lambda *a, **k: True
        cifrado.bloqueo = lambda: "raiz-1"

        def bloqueo_apuntado(uid) -> bool:
            """Apunta a quién se le pide bloquear y qué había escrito al pedirlo."""
            visto["uid"] = uid
            visto["pairs"] = prefs.read_prefs().get("pairs")
            visto["cortados"] = len(cortados)
            return True

        cifrado.pedir_bloqueo = bloqueo_apuntado
        uitk.store.matar_hijos = lambda: cortados.append(1) or 0
        try:
            abrir(TRES, tras_marcar(lambda root: boton(root, "Bloquear").invoke()))
        finally:
            messagebox.askokcancel, cifrado.bloqueo, cifrado.pedir_bloqueo = reales_bloqueo
            uitk.store.matar_hijos = real_matar
        c("lo marcado se escribe antes de pedirle al agente que bloquee",
          (visto["uid"], visto["pairs"]), ("raiz-1", ["a", "b"]))
        c("  y antes se cortan las lecturas que queden", visto["cortados"], 1)
finally:
    prefs.guardar_parejas = real_guardar
    uitk.output_window = REAL_OUTPUT

# 6j. si «Expulsar» o «Bloquear» no llegan a hacerse, la ventana sigue y vuelve a leer
# (sus lecturas se cortaron justo antes)
reales_6j = (messagebox.askokcancel, messagebox.showerror, cifrado.lanzar_expulsion,
             cifrado.bloqueo, cifrado.pedir_bloqueo)


def no_se_lanza(script) -> None:
    """Hace de un script de expulsar que no se puede lanzar."""
    raise OSError("no está")


for texto in ("Expulsar", "Bloquear"):
    with sandbox():
        visto = {}
        encargos = []

        def apuntando(funcion):
            """Como `sin_terminar`, y apunta cada encargo."""
            encargos.append(segundo_plano.Encargo(funcion))
            return encargos[-1]

        def falla_al_soltar(root, texto=texto) -> None:
            """Deja llegar la lectura, pulsa el botón y mira cómo queda."""
            root.update_idletasks()
            encargos[0].correr()
            hasta(root, lambda: root.instantanea_lista)
            antes = len(encargos)
            boton(root, texto).invoke()
            visto["abierta"] = bool(root.winfo_exists())
            visto["lecturas"] = len(encargos) - antes
            visto["la última"] = root.instantanea is encargos[-1]

        messagebox.askokcancel = lambda *a, **k: True
        messagebox.showerror = lambda *a, **k: visto.setdefault("error", True)
        cifrado.lanzar_expulsion = no_se_lanza
        cifrado.bloqueo = (lambda: "raiz-1") if texto == "Bloquear" else (lambda: None)
        cifrado.pedir_bloqueo = lambda uid: False
        try:
            abrir(TRES, falla_al_soltar, lanzar=apuntando)
        finally:
            (messagebox.askokcancel, messagebox.showerror, cifrado.lanzar_expulsion,
             cifrado.bloqueo, cifrado.pedir_bloqueo) = reales_6j
        c(f"si «{texto}» no se hace, lo dice y la ventana sigue abierta",
          (visto.get("error"), visto["abierta"]), (True, True))
        c("  y vuelve a leer, porque cortó sus lecturas",
          (visto["lecturas"], visto["la última"]), (1, True))

# 6k. al cerrar la pasada sigue ocupada hasta que llega la lectura nueva: no vuelve a
# enseñar lo que se leyó antes de la pasada, y aplica la nueva una sola vez
for lectura_nueva in ("bien", "falla"):
    with sandbox():
        encargos = []
        cierres: list = []
        aplicados: list = []
        visto = {}
        cuenta = {"n": 1}
        real_aplicar, real_leer = tk_principal.VistaPrincipal.aplicar, instantanea.leer

        def leer_con_cuenta(config, **k):
            """La lectura de verdad con las cosas que revisar de `cuenta`; `None` falla."""
            if cuenta["n"] is None:
                raise OSError("la unidad no contesta")
            return dataclasses.replace(real_leer(config, **k), cuenta=cuenta["n"])

        def apuntando(funcion):
            """Como `sin_terminar`, y apunta cada encargo."""
            encargos.append(segundo_plano.Encargo(funcion))
            return encargos[-1]

        def aplicar_apuntando(self, e):
            """Apunta cada estado que se aplica."""
            aplicados.append((e.en_curso, e.chip[0], e.reparacion))
            return real_aplicar(self, e)

        def pasada_que_arregla(root, lectura_nueva=lectura_nueva) -> None:
            """Una pasada que arregla lo que había que revisar, y su cierre."""
            root.update_idletasks()
            encargos[0].correr()
            hasta(root, lambda: root.instantanea_lista)
            visto["antes"] = "Hay 1 cosa que revisar." in textos(root)
            boton(root, "Sincronizar ahora").invoke()
            hasta(root, lambda: cierres)
            cuenta["n"] = 0 if lectura_nueva == "bien" else None
            aplicados.clear()
            cierres[0](0)                                # se cierra la ventana de la pasada
            root.update()
            visto["al cerrar"] = (
                activo(root, "Sincronizar ahora"), "sincronizando…" in textos(root),
                "1 que revisar" in textos(root), "Hay 1 cosa que revisar." in textos(root),
                len(encargos), list(aplicados))
            encargos[-1].correr()
            visto["llega"] = hasta(root, lambda: root.instantanea_lista)
            visto["después"] = (activo(root, "Sincronizar ahora"), "al día" in textos(root),
                                "Hay 1 cosa que revisar." in textos(root), list(aplicados))

        tk_principal.VistaPrincipal.aplicar = aplicar_apuntando
        instantanea.leer = leer_con_cuenta
        uitk.output_window = lambda titulo, cmd, **k: cierres.append(k["al_cerrar"])
        try:
            abrir(TRES, pasada_que_arregla, lanzar=apuntando)
        finally:
            tk_principal.VistaPrincipal.aplicar, instantanea.leer = real_aplicar, real_leer
            uitk.output_window = REAL_OUTPUT
        c(f"lectura que va {lectura_nueva}: antes de la pasada había 1 cosa que revisar",
          visto["antes"], True)
        c("  al cerrar la pasada sigue ocupada, sin volver a enseñar lo de antes, y lee",
          visto["al cerrar"], (False, True, False, False, 2, []))
        c("  al llegar la lectura queda libre, al día, y se aplica una vez",
          (visto["llega"], visto["después"]),
          (True, (True, True, False, [(False, "al día", 0)])))

raiz.destroy()
sys.exit(c.report())
